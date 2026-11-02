# -*- coding: utf-8 -*-
"""398-A1: 指挥调度器 Commander——指挥窗口+员工窗口的命令分发与汇报闭环。

设计决策（≥3，任务书交付物）
[D1] 队列=list[Command](@dataclass)，idx 即命令编号（dispatch/report 靠 idx 匹配）。
    列表下标 O(1) 优于 deque；JSON 持久化直觉对应集群文本行顺序。
[D2] 命令级扁平状态机 pending→running→done|rejected，由命令集合推导窗口状态
    (idle/running/awaiting_approval)。单命令翻转单点发信号，拒绝不影响同窗口其他命令。
[D3] 写令牌=threading.Lock+_write_holder:Optional[int]；0/1 互斥直接映射，无需 queue。
    acquire(blocking=False)=peek 能力；holder 记录 cmd_idx 可定位写锁卡死。
[D4] 持久化=tmp+os.replace 原子写+threading.Lock（对齐 blackboard.py 经验）。
    JSON 文件可审计/diff，故障恢复只需删/拷。
[D5] HQ 审批=threading.Event：set 时放行 manual 阻塞，auto 直接通过；无轮询线程。
复用边界：仅登记 session_id 引用（MultiSessionManager 负责会话创建，禁止自建）。
"""

import dataclasses
import json
import os
import re
import threading
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATE_DIR = os.path.join(_ROOT, "data", "commander_state")
_WRITE_KEYWORDS = ("write_file", "edit_file", "multi_edit", "delete_file")


class CommanderRole(Enum):
    COMMANDER = "commander"
    WORKER = "worker"


class WindowStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    AWAITING_APPROVAL = "awaiting_approval"


class CmdStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    REJECTED = "rejected"


class DispatchMode(Enum):
    SERIAL = "serial"
    PARALLEL = "parallel"


@dataclasses.dataclass
class WindowInfo:
    session_id: str
    name: str
    role: CommanderRole
    engine: str
    model: str = ""
    status: WindowStatus = WindowStatus.IDLE


@dataclasses.dataclass
class Command:
    idx: int
    text: str
    target_worker: Optional[str] = None  # 期望的 worker session_id；None=任意
    status: CmdStatus = CmdStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    assigned_worker: Optional[str] = None
    started_at: Optional[float] = None
    is_write: bool = False


class Commander(QObject):
    dispatch_made = pyqtSignal(dict)      # HI {worker_id, cmd_idx, cluster_idx}
    worker_reported = pyqtSignal(dict)    # HI {worker_id, cmd_idx, result_summary}
    approval_needed = pyqtSignal(dict)    # HQ {round_id, cmd_idx, worker_id}
    round_closed = pyqtSignal(dict)       # HR {round_id, n_done, n_total, secs, tool_calls}

    def __init__(self, mode: str = "serial", manual: bool = False, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._mode = DispatchMode(mode)
        self._manual = manual
        self._round_id = f"round_{uuid.uuid4().hex[:8]}"
        self._windows: Dict[str, WindowInfo] = {}
        self._commands: List[Command] = []
        self._next_cmd_idx = 0
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._write_holder: Optional[int] = None
        self._approval_event: Optional[threading.Event] = None
        self._approval_round_id: Optional[str] = None
        self._approval_cmd_idx: Optional[int] = None
        self._started_at = time.time()
        self._n_done_total = 0

    # ---- 窗口登记 ----
    def register_window(self, session_id: str, role: str, engine: str, model: str = "") -> None:
        role_enum = CommanderRole(role) if isinstance(role, str) else role
        if self._mode == DispatchMode.PARALLEL and engine == "ollama":
            for _sid, _wi in self._windows.items():
                if _wi.engine == "ollama" and _sid != session_id:
                    raise ValueError(
                        f"parallel 禁多 ollama 窗口: 已注册 {_wi.name} + 当前 {session_id}；换用 deepseek（4060 8GB 并行=排队伪并行）")
        self._windows[session_id] = WindowInfo(session_id=session_id, name=session_id[:12],
                                              role=role_enum, engine=engine, model=model)
        self._save()

    # ---- 集群提交 ----
    _CMD_RE = re.compile(r'(?:^\s*(?:命令\s*(\d+)|(\d+)\s*[\.\)：）]|^\s*[-*]\s+)(.*?)$)', re.MULTILINE)

    def submit_cluster(self, cluster_text: str) -> List[int]:
        idxs: List[int] = []
        text = cluster_text.strip()
        if not text:
            return idxs
        matches = list(self._CMD_RE.finditer(text))
        bodies = [(m.group(3) or "").strip() for m in matches] if matches else [ln.strip() for ln in text.splitlines() if ln.strip()]
        for body in bodies:
            if not body:
                continue
            idx = len(self._commands)
            self._commands.append(Command(idx=idx, text=body, is_write=any(kw in body for kw in _WRITE_KEYWORDS)))
            idxs.append(idx)
        self._save()
        return idxs

    # ---- 派发 ----
    def dispatch_next(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            cmd = self._pick_next_command()
            if cmd is None:
                if self._all_done() and not self._approval_event:
                    self._emit_round_closed()
                return None
            worker_id = self._pick_worker_for(cmd)
            if worker_id is None:
                return None
            cmd.status = CmdStatus.RUNNING
            cmd.assigned_worker = worker_id
            cmd.started_at = time.time()
            self._windows[worker_id].status = WindowStatus.RUNNING
            rec = {"worker_id": worker_id, "cmd_idx": cmd.idx, "cluster_idx": self._next_cmd_idx}
            self._save()
        self.dispatch_made.emit(rec)
        return {"ok": True, "worker_id": worker_id, "cmd_idx": cmd.idx, "action": "dispatched"}

    def report_result(self, worker_id: str, cmd_idx: int, result: Any = None) -> Dict[str, Any]:
        with self._lock:
            cmd = self._commands[cmd_idx] if 0 <= cmd_idx < len(self._commands) else None
            if cmd is None or cmd.assigned_worker != worker_id:
                return {"ok": False, "reason": "cmd_not_found_or_worker_mismatch"}
            cmd.status = CmdStatus.DONE
            cmd.result = self._normalize_result(result)
            self._n_done_total += 1
            if self._write_holder == cmd_idx:
                if self._write_lock.locked():
                    try:
                        self._write_lock.release()
                    except RuntimeError:
                        pass
                self._write_holder = None
            wi = self._windows.get(worker_id)
            if wi:
                any_running = any(c.assigned_worker == worker_id and c.status == CmdStatus.RUNNING for c in self._commands)
                wi.status = WindowStatus.DONE if self._worker_all_done(worker_id) else (WindowStatus.RUNNING if any_running else WindowStatus.IDLE)
            rec = {"worker_id": worker_id, "cmd_idx": cmd.idx, "result_summary": (str(result)[:200] if result else "")}
            self._save()
        self.worker_reported.emit(rec)
        action_taken = "reported"
        if self._manual and self._last_done_cmd() is not None:
            self._trigger_approval(self._last_done_cmd())
            action_taken = "approval_triggered"
        elif not self._manual:
            self.dispatch_next()
            action_taken = "dispatched_next"
        return {"ok": True, "worker_id": worker_id, "cmd_idx": cmd.idx, "action": action_taken}

    def approve(self, round_id: str) -> bool:
        if round_id != self._round_id:
            return False
        with self._lock:
            if self._approval_event is None:
                return True
            self._approval_event.set()
            self._approval_event = None
            self._approval_round_id = None
            self._approval_cmd_idx = None
            self._save()
        if self._mode == DispatchMode.SERIAL:
            self.dispatch_next()
        return True

    def reject(self, round_id: str, reason: str = "") -> bool:
        if round_id != self._round_id:
            return False
        with self._lock:
            if self._approval_event is not None:
                self._approval_event.clear()
                self._approval_event = None
                self._approval_round_id = None
                self._approval_cmd_idx = None
            for c in reversed(self._commands):
                if c.status == CmdStatus.DONE:
                    c.status = CmdStatus.REJECTED
                    break
            self._save()
        if self._mode == DispatchMode.SERIAL:
            self.dispatch_next()
        return True

    # ---- 持久化 ----
    def _save(self) -> None:
        os.makedirs(_STATE_DIR, exist_ok=True)
        snap = self.to_dict()
        path = os.path.join(_STATE_DIR, f"{self._round_id}.json")
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, path)
        except Exception:
            pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_id": self._round_id, "mode": self._mode.value, "manual": self._manual,
            "windows": {sid: {**{k: (v.value if isinstance(v, Enum) else v) for k, v in dataclasses.asdict(wi).items()}}
                       for sid, wi in self._windows.items()},
            "commands": [{**{k: (v.value if isinstance(v, Enum) else v) for k, v in dataclasses.asdict(c).items()}}
                         for c in self._commands],
            "next_cmd_idx": self._next_cmd_idx, "n_done_total": self._n_done_total,
            "write_holder": self._write_holder, "started_at": self._started_at,
            "elapsed": round(time.time() - self._started_at, 2),
        }

    # ---- 内部 ----
    def _pick_next_command(self) -> Optional[Command]:
        if self._mode == DispatchMode.SERIAL:
            for c in self._commands:
                if c.status != CmdStatus.PENDING:
                    continue
                if c.is_write and not self._try_acquire_write(c.idx):
                    continue
                return c
            return None
        for c in self._commands:
            if c.status == CmdStatus.PENDING and not c.is_write:
                return c
        for c in self._commands:
            if c.status == CmdStatus.PENDING and c.is_write and self._try_acquire_write(c.idx):
                return c
        return None

    def _try_acquire_write(self, cmd_idx: int) -> bool:
        acquired = self._write_lock.acquire(blocking=False)
        if acquired:
            self._write_holder = cmd_idx
            return True
        return False

    def _pick_worker_for(self, cmd: Command) -> Optional[str]:
        if cmd.target_worker and cmd.target_worker in self._windows and self._windows[cmd.target_worker].status != WindowStatus.RUNNING:
            return cmd.target_worker
        for sid, wi in self._windows.items():
            if wi.role == CommanderRole.WORKER and wi.status != WindowStatus.RUNNING:
                if self._mode == DispatchMode.PARALLEL and wi.engine == "ollama":
                    if any(o_wi.engine == "ollama" and o_wi.status == WindowStatus.RUNNING
                           for o_sid, o_wi in self._windows.items() if o_sid != sid):
                        continue
                return sid
        return None

    def _worker_all_done(self, worker_id: str) -> bool:
        return (any(c.assigned_worker == worker_id for c in self._commands) and
                all(c.status in (CmdStatus.DONE, CmdStatus.REJECTED) for c in self._commands if c.assigned_worker == worker_id))

    def _all_done(self) -> bool:
        return bool(self._commands) and all(c.status in (CmdStatus.DONE, CmdStatus.REJECTED) for c in self._commands)

    def _last_done_cmd(self) -> Optional[int]:
        for i in range(len(self._commands) - 1, -1, -1):
            if self._commands[i].status == CmdStatus.DONE:
                return i
        return None

    def _trigger_approval(self, cmd_idx: int) -> None:
        self._approval_event = threading.Event()
        self._approval_round_id = self._round_id
        self._approval_cmd_idx = cmd_idx
        self._save()
        self.approval_needed.emit({"round_id": self._round_id, "cmd_idx": cmd_idx,
                                  "worker_id": self._commands[cmd_idx].assigned_worker})

    def _emit_round_closed(self) -> None:
        self.round_closed.emit({"round_id": self._round_id, "n_done": self._n_done_total,
                                "n_total": len(self._commands), "secs": round(time.time() - self._started_at, 2),
                                "tool_calls": sum(1 for c in self._commands if c.status == CmdStatus.DONE)})

    @staticmethod
    def _normalize_result(result: Any) -> Dict[str, Any]:
        if result is None:
            return {}
        if isinstance(result, dict):
            return result
        return {"value": str(result)[:500]}

    # ---- 只读查询 ----
    @property
    def round_id(self) -> str:
        return self._round_id

    @property
    def mode(self) -> str:
        return self._mode.value

    @property
    def windows(self) -> Dict[str, WindowInfo]:
        return dict(self._windows)

    @property
    def commands(self) -> List[Command]:
        return list(self._commands)
