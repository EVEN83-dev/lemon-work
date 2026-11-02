# -*- coding: utf-8 -*-
"""
白盒状态对象模型 — 五对象 + RunRegistry
========================================
核心设计：UI 渲染状态对象，事件只是更新对象的信号。
  - Run:      一次完整执行（聚合根）
  - Step:     计划中的步骤
  - ToolCall: 单次工具调用
  - Approval: 一次审批请求
  - Artifact: 成果物

所有对象可序列化/反序列化（round-trip 无损），
RunRegistry 维护对象生命周期并发射细粒度信号供 UI 订阅。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal, QTimer


# ============================================================
# 枚举
# ============================================================
class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolCallStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"
    EXPIRED = "expired"


class ArtifactKind(str, Enum):
    FILE_DIFF = "file_diff"
    FILE_CREATED = "file_created"
    FILE_DELETED = "file_deleted"
    CHART = "chart"
    DOC = "doc"
    COMMAND_OUTPUT = "command_output"


# ============================================================
# 数据类
# ============================================================
@dataclass
class ToolCall:
    call_id: str = ""
    step_id: str = ""
    tool_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    status: ToolCallStatus = ToolCallStatus.PENDING
    result_summary: str = ""
    result_full: str = ""
    duration_ms: int = 0
    is_fast: bool = False
    started_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ToolCall:
        d = dict(d)
        d["status"] = ToolCallStatus(d.get("status", "pending"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Step:
    step_id: str = ""
    run_id: str = ""
    title: str = ""
    status: StepStatus = StepStatus.PENDING
    tool_calls: List[ToolCall] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Step:
        d = dict(d)
        d["status"] = StepStatus(d.get("status", "pending"))
        tcs = d.pop("tool_calls", [])
        obj = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        obj.tool_calls = [ToolCall.from_dict(tc) for tc in tcs]
        return obj


@dataclass
class Approval:
    approval_id: str = ""
    run_id: str = ""
    tool_name: str = ""
    args_preview: str = ""
    risk_level: str = "medium"
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: float = 0.0
    decided_at: float = 0.0
    decided_by: str = ""
    expires_at: float = 0.0
    args_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Approval:
        d = dict(d)
        d["status"] = ApprovalStatus(d.get("status", "pending"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Artifact:
    artifact_id: str = ""
    run_id: str = ""
    kind: ArtifactKind = ArtifactKind.FILE_DIFF
    title: str = ""
    path_or_content: str = ""
    diff_stats: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Artifact:
        d = dict(d)
        d["kind"] = ArtifactKind(d.get("kind", "file_diff"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RunStats:
    tool_calls: int = 0
    files_changed: int = 0
    tokens_used: int = 0
    retries: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RunStats:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Run:
    run_id: str = ""
    session_id: str = ""
    user_prompt: str = ""
    status: RunStatus = RunStatus.QUEUED
    started_at: float = 0.0
    finished_at: float = 0.0
    elapsed_ms: int = 0
    steps: List[Step] = field(default_factory=list)
    artifacts: List[Artifact] = field(default_factory=list)
    stats: RunStats = field(default_factory=RunStats)
    summary: str = ""
    is_expanded: bool = True
    plan_approved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["steps"] = [s.to_dict() for s in self.steps]
        d["artifacts"] = [a.to_dict() for a in self.artifacts]
        d["stats"] = self.stats.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Run:
        d = dict(d)
        d["status"] = RunStatus(d.get("status", "queued"))
        steps_data = d.pop("steps", [])
        artifacts_data = d.pop("artifacts", [])
        stats_data = d.pop("stats", {})
        obj = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        obj.steps = [Step.from_dict(s) for s in steps_data]
        obj.artifacts = [Artifact.from_dict(a) for a in artifacts_data]
        obj.stats = RunStats.from_dict(stats_data) if stats_data else RunStats()
        return obj

    @property
    def active_step(self) -> Optional[Step]:
        for s in self.steps:
            if s.status == StepStatus.ACTIVE:
                return s
        return None

    @property
    def pending_approvals(self) -> List[Approval]:
        return []

    def compute_stats(self) -> None:
        tc_count = 0
        for step in self.steps:
            tc_count += len(step.tool_calls)
        self.stats.tool_calls = tc_count
        self.stats.files_changed = len([a for a in self.artifacts
                                        if a.kind in (ArtifactKind.FILE_DIFF,
                                                       ArtifactKind.FILE_CREATED,
                                                       ArtifactKind.FILE_DELETED)])
        if self.started_at and self.finished_at:
            self.elapsed_ms = int((self.finished_at - self.started_at) * 1000)


# ============================================================
# RunRegistry — QObject 信号中心
# ============================================================
class RunRegistry(QObject):
    run_added = pyqtSignal(str)
    run_updated = pyqtSignal(str)
    run_completed = pyqtSignal(str)
    run_failed = pyqtSignal(str)
    step_updated = pyqtSignal(str, str)
    tool_call_updated = pyqtSignal(str, str, str)
    approval_requested = pyqtSignal(str, str)
    approval_decided = pyqtSignal(str, str)
    artifact_added = pyqtSignal(str, str)
    registry_cleared = pyqtSignal()

    APPROVAL_TIMEOUT_MS = 600000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._runs: Dict[str, Run] = {}
        self._approvals: Dict[str, Approval] = {}
        self._approval_timers: Dict[str, QTimer] = {}
        self._current_run_id: Optional[str] = None

    # ── Run 生命周期 ──

    def add_run(self, user_prompt: str, session_id: str = "") -> Run:
        run = Run(
            run_id=uuid.uuid4().hex[:12],
            session_id=session_id,
            user_prompt=user_prompt,
            status=RunStatus.RUNNING,
            started_at=time.time(),
            is_expanded=True,
        )
        self._runs[run.run_id] = run
        self._current_run_id = run.run_id
        self.run_added.emit(run.run_id)
        return run

    def get_run(self, run_id: str) -> Optional[Run]:
        return self._runs.get(run_id)

    def get_current_run(self) -> Optional[Run]:
        if self._current_run_id:
            return self._runs.get(self._current_run_id)
        return None

    def complete_run(self, run_id: str, summary: str = "") -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        run.status = RunStatus.COMPLETED
        run.finished_at = time.time()
        run.summary = summary
        run.compute_stats()
        self.run_updated.emit(run_id)
        self.run_completed.emit(run_id)

    def fail_run(self, run_id: str, reason: str = "") -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        run.status = RunStatus.FAILED
        run.finished_at = time.time()
        run.summary = reason or run.summary
        run.compute_stats()
        self.run_updated.emit(run_id)
        self.run_failed.emit(run_id)

    def cancel_run(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        run.status = RunStatus.CANCELLED
        run.finished_at = time.time()
        run.compute_stats()
        self.run_updated.emit(run_id)

    def set_run_waiting_approval(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        run.status = RunStatus.WAITING_APPROVAL
        self.run_updated.emit(run_id)

    def set_run_running(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        run.status = RunStatus.RUNNING
        self.run_updated.emit(run_id)

    # ── Step 生命周期 ──

    def add_step(self, run_id: str, title: str, step_id: str = "") -> Step:
        run = self._runs.get(run_id)
        if not run:
            run = Run(run_id=run_id, status=RunStatus.RUNNING)
            self._runs[run_id] = run
        step = Step(
            step_id=step_id or uuid.uuid4().hex[:8],
            run_id=run_id,
            title=title,
            status=StepStatus.ACTIVE,
            started_at=time.time(),
        )
        run.steps.append(step)
        self.step_updated.emit(run_id, step.step_id)
        return step

    def update_step(self, run_id: str, step_id: str,
                    status: StepStatus = None) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        for step in run.steps:
            if step.step_id == step_id:
                if status is not None:
                    step.status = status
                if status in (StepStatus.DONE, StepStatus.FAILED, StepStatus.SKIPPED):
                    step.finished_at = time.time()
                self.step_updated.emit(run_id, step_id)
                return

    def get_or_create_implicit_step(self, run_id: str) -> Step:
        run = self._runs.get(run_id)
        if not run:
            run = Run(run_id=run_id, status=RunStatus.RUNNING)
            self._runs[run_id] = run
        active = run.active_step
        if active:
            return active
        step = Step(
            step_id=uuid.uuid4().hex[:8],
            run_id=run_id,
            title="自主执行",
            status=StepStatus.ACTIVE,
            started_at=time.time(),
        )
        run.steps.append(step)
        self.step_updated.emit(run_id, step.step_id)
        return step

    # ── ToolCall 生命周期 ──

    def add_tool_call(self, run_id: str, step_id: str,
                      tool_name: str, call_id: str = "",
                      args: Dict[str, Any] = None) -> ToolCall:
        run = self._runs.get(run_id)
        if not run:
            return ToolCall()
        step = None
        for s in run.steps:
            if s.step_id == step_id:
                step = s
                break
        if not step:
            step = self.get_or_create_implicit_step(run_id)
        for tc in step.tool_calls:
            if tc.call_id == call_id and call_id:
                return tc
        tc = ToolCall(
            call_id=call_id or uuid.uuid4().hex[:8],
            step_id=step.step_id,
            tool_name=tool_name,
            args=args or {},
            status=ToolCallStatus.RUNNING,
            started_at=time.time(),
        )
        step.tool_calls.append(tc)
        self.tool_call_updated.emit(run_id, step.step_id, tc.call_id)
        return tc

    def update_tool_call(self, run_id: str, call_id: str,
                         status: ToolCallStatus = None,
                         result_summary: str = "",
                         result_full: str = "",
                         duration_ms: int = 0) -> None:
        run = self._runs.get(run_id)
        if not run:
            return
        for step in run.steps:
            for tc in step.tool_calls:
                if tc.call_id == call_id:
                    if status is not None:
                        tc.status = status
                    if result_summary:
                        tc.result_summary = result_summary
                    if result_full:
                        tc.result_full = result_full
                    if duration_ms:
                        tc.duration_ms = duration_ms
                    tc.is_fast = (tc.duration_ms > 0 and tc.duration_ms < 200
                                  and tc.status == ToolCallStatus.SUCCESS)
                    self.tool_call_updated.emit(run_id, step.step_id, call_id)
                    return

    # ── Approval 生命周期 ──

    def request_approval(self, run_id: str, tool_name: str,
                         args_preview: str = "",
                         risk_level: str = "medium",
                         args_hash: str = "") -> Approval:
        approval = Approval(
            approval_id=uuid.uuid4().hex[:8],
            run_id=run_id,
            tool_name=tool_name,
            args_preview=args_preview,
            risk_level=risk_level,
            status=ApprovalStatus.PENDING,
            requested_at=time.time(),
            expires_at=time.time() + self.APPROVAL_TIMEOUT_MS / 1000.0,
            args_hash=args_hash,
        )
        self._approvals[approval.approval_id] = approval
        self.set_run_waiting_approval(run_id)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda aid=approval.approval_id: self._expire_approval(aid))
        timer.start(self.APPROVAL_TIMEOUT_MS)
        self._approval_timers[approval.approval_id] = timer
        self.approval_requested.emit(run_id, approval.approval_id)
        return approval

    def decide_approval(self, approval_id: str, decision: ApprovalStatus,
                        decided_by: str = "user") -> None:
        approval = self._approvals.get(approval_id)
        if not approval:
            return
        if approval.status != ApprovalStatus.PENDING:
            return
        approval.status = decision
        approval.decided_at = time.time()
        approval.decided_by = decided_by
        timer = self._approval_timers.pop(approval_id, None)
        if timer:
            timer.stop()
        run = self._runs.get(approval.run_id)
        if run and run.status == RunStatus.WAITING_APPROVAL:
            run.status = RunStatus.RUNNING
            self.run_updated.emit(run.run_id)
        self.approval_decided.emit(approval.run_id, approval_id)

    def get_approval(self, approval_id: str) -> Optional[Approval]:
        return self._approvals.get(approval_id)

    def _expire_approval(self, approval_id: str) -> None:
        approval = self._approvals.get(approval_id)
        if not approval or approval.status != ApprovalStatus.PENDING:
            return
        approval.status = ApprovalStatus.EXPIRED
        approval.decided_at = time.time()
        approval.decided_by = "timeout"
        self._approval_timers.pop(approval_id, None)
        run = self._runs.get(approval.run_id)
        if run and run.status == RunStatus.WAITING_APPROVAL:
            run.status = RunStatus.RUNNING
            self.run_updated.emit(run.run_id)
        self.approval_decided.emit(approval.run_id, approval_id)

    # ── Artifact 生命周期 ──

    def add_artifact(self, run_id: str, kind: ArtifactKind,
                     title: str, path_or_content: str = "",
                     diff_stats: str = "") -> Artifact:
        run = self._runs.get(run_id)
        if not run:
            return Artifact()
        artifact = Artifact(
            artifact_id=uuid.uuid4().hex[:8],
            run_id=run_id,
            kind=kind,
            title=title,
            path_or_content=path_or_content,
            diff_stats=diff_stats,
        )
        run.artifacts.append(artifact)
        run.compute_stats()
        self.artifact_added.emit(run_id, artifact.artifact_id)
        return artifact

    # ── 查询 ──

    def all_runs(self) -> List[Run]:
        return list(self._runs.values())

    def runs_for_session(self, session_id: str) -> List[Run]:
        return [r for r in self._runs.values() if r.session_id == session_id]

    def get_artifacts_for_run(self, run_id: str) -> List[Artifact]:
        run = self._runs.get(run_id)
        return run.artifacts if run else []

    def get_all_artifacts(self, session_id: str = "") -> List[Artifact]:
        artifacts = []
        for run in self._runs.values():
            if session_id and run.session_id != session_id:
                continue
            artifacts.extend(run.artifacts)
        return artifacts

    # ── 序列化/反序列化 ──

    def serialize_run(self, run_id: str) -> str:
        run = self._runs.get(run_id)
        if not run:
            return "{}"
        return json.dumps(run.to_dict(), ensure_ascii=False)

    def deserialize_run(self, json_str: str) -> Optional[Run]:
        try:
            d = json.loads(json_str)
            run = Run.from_dict(d)
            self._runs[run.run_id] = run
            return run
        except Exception:
            return None

    def save_session(self, session_id: str, path: str) -> bool:
        runs = self.runs_for_session(session_id)
        data = [r.to_dict() for r in runs]
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load_session(self, path: str) -> int:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = 0
            for d in data:
                run = Run.from_dict(d)
                self._runs[run.run_id] = run
                count += 1
            return count
        except Exception:
            return 0

    def clear(self) -> None:
        for timer in self._approval_timers.values():
            timer.stop()
        self._approval_timers.clear()
        self._runs.clear()
        self._approvals.clear()
        self._current_run_id = None
        self.registry_cleared.emit()

    def cleanup_old_runs(self, max_age_hours: int = 24) -> int:
        cutoff = time.time() - max_age_hours * 3600
        to_remove = []
        for rid, run in self._runs.items():
            if run.status in (RunStatus.COMPLETED, RunStatus.FAILED,
                              RunStatus.CANCELLED):
                if run.finished_at and run.finished_at < cutoff:
                    to_remove.append(rid)
        for rid in to_remove:
            del self._runs[rid]
        return len(to_remove)
