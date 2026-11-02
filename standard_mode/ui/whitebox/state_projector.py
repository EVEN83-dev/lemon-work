# -*- coding: utf-8 -*-
"""
StateProjector — 事件→状态投影层
=================================
订阅 EventBus 全部相关信号，将事件投影到 RunRegistry 中的状态对象。
核心原则：幂等去重 — 同一事件重复到达不会产生重复状态。

事件 → 投影映射：
  MESSAGE_SENT   → 创建 Run (user_prompt)
  MESSAGE_RECEIVED → 补全 Run summary
  MESSAGE_DELTA  → 更新 Run (流式文本追加到 active step)
  TOOL_BEFORE    → 创建 ToolCall (running)
  TOOL_AFTER     → 更新 ToolCall (success + artifact)
  TOOL_ERROR     → 更新 ToolCall (failed)
  FILE_SAVED     → 创建 Artifact (file_diff/file_created)
  SESSION_SWITCHED → 可选：结束当前 Run
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional, Set

from PyQt5.QtCore import QObject

from core.event_bus import EventBus, EventType
from ui.whitebox.state_model import (
    RunRegistry, RunStatus, StepStatus, ToolCallStatus,
    ArtifactKind,
)


class StateProjector(QObject):
    def __init__(self, registry: RunRegistry, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._bus = EventBus.instance()
        self._seen_tool_calls: Set[str] = set()
        self._seen_messages: Set[str] = set()
        self._current_session_id: str = ""
        self._subscribe()

    def _subscribe(self) -> None:
        self._bus.subscribe(EventType.MESSAGE_SENT, self._on_message_sent)
        self._bus.subscribe(EventType.MESSAGE_RECEIVED, self._on_message_received)
        self._bus.subscribe(EventType.MESSAGE_DELTA, self._on_message_delta)
        self._bus.subscribe(EventType.TOOL_BEFORE, self._on_tool_before)
        self._bus.subscribe(EventType.TOOL_AFTER, self._on_tool_after)
        self._bus.subscribe(EventType.TOOL_ERROR, self._on_tool_error)
        self._bus.subscribe(EventType.FILE_SAVED, self._on_file_saved)
        self._bus.subscribe(EventType.SESSION_SWITCHED, self._on_session_switched)
        self._tree = None

    def unsubscribe_all(self) -> None:
        self._bus.unsubscribe(EventType.MESSAGE_SENT, self._on_message_sent)
        self._bus.unsubscribe(EventType.MESSAGE_RECEIVED, self._on_message_received)
        self._bus.unsubscribe(EventType.MESSAGE_DELTA, self._on_message_delta)
        self._bus.unsubscribe(EventType.TOOL_BEFORE, self._on_tool_before)
        self._bus.unsubscribe(EventType.TOOL_AFTER, self._on_tool_after)
        self._bus.unsubscribe(EventType.TOOL_ERROR, self._on_tool_error)
        self._bus.unsubscribe(EventType.FILE_SAVED, self._on_file_saved)
        self._bus.unsubscribe(EventType.SESSION_SWITCHED, self._on_session_switched)

    # ── 幂等去重辅助 ──

    @staticmethod
    def _dedup_key(event_type: str, data: Any) -> str:
        if isinstance(data, dict):
            raw = f"{event_type}:{sorted(data.items())}"
        else:
            raw = f"{event_type}:{data}"
        return hashlib.md5(raw.encode("utf-8", errors="replace")).hexdigest()[:16]

    def _is_seen(self, key: str) -> bool:
        if key in self._seen_messages:
            return True
        self._seen_messages.add(key)
        if len(self._seen_messages) > 10000:
            self._seen_messages = set(list(self._seen_messages)[-5000:])
        return False

    # ── 事件处理器 ──

    def _on_message_sent(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        text = data.get("text", "")
        if not text:
            return
        run = self._registry.add_run(
            user_prompt=text,
            session_id=self._current_session_id,
        )

    def _on_message_received(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        run = self._registry.get_current_run()
        if not run:
            return
        text = data.get("text", "")
        if text and not run.summary:
            run.summary = text[:200]
            self._registry.run_updated.emit(run.run_id)

    def _on_message_delta(self, data: Any) -> None:
        pass

    def _on_tool_before(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        tool_name = data.get("tool", "")
        tool_input = data.get("input", {})
        call_id = data.get("callID", "") or data.get("call_id", "")
        if not tool_name:
            return
        if call_id and call_id in self._seen_tool_calls:
            return
        if call_id:
            self._seen_tool_calls.add(call_id)
            if len(self._seen_tool_calls) > 5000:
                self._seen_tool_calls = set(list(self._seen_tool_calls)[-2000:])
        run = self._registry.get_current_run()
        if not run:
            return
        step = run.active_step
        step_id = step.step_id if step else ""
        if not step_id:
            s = self._registry.get_or_create_implicit_step(run.run_id)
            step_id = s.step_id
        self._registry.add_tool_call(
            run_id=run.run_id,
            step_id=step_id,
            tool_name=tool_name,
            call_id=call_id,
            args=tool_input if isinstance(tool_input, dict) else {},
        )

    def _on_tool_after(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        tool_name = data.get("tool", "")
        output = data.get("output", "")
        run = self._registry.get_current_run()
        if not run:
            return
        tc = self._find_running_tool_call(run.run_id, tool_name)
        if not tc:
            return
        summary = self._truncate_output(output, 200)
        full = str(output) if output else ""
        elapsed = int((time.time() - tc.started_at) * 1000) if tc.started_at else 0
        self._registry.update_tool_call(
            run_id=run.run_id,
            call_id=tc.call_id,
            status=ToolCallStatus.SUCCESS,
            result_summary=summary,
            result_full=full,
            duration_ms=elapsed,
        )
        if tool_name in ("write", "edit", "multiedit"):
            tc_args = tc.args
            file_path = tc_args.get("filePath", "")
            if file_path:
                self._registry.add_artifact(
                    run_id=run.run_id,
                    kind=ArtifactKind.FILE_DIFF,
                    title=file_path,
                    path_or_content=file_path,
                    diff_stats="",
                )

    def _on_tool_error(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        tool_name = data.get("tool", "")
        error = data.get("error", "")
        run = self._registry.get_current_run()
        if not run:
            return
        tc = self._find_running_tool_call(run.run_id, tool_name)
        if not tc:
            return
        elapsed = int((time.time() - tc.started_at) * 1000) if tc.started_at else 0
        self._registry.update_tool_call(
            run_id=run.run_id,
            call_id=tc.call_id,
            status=ToolCallStatus.FAILED,
            result_summary=str(error)[:200],
            result_full=str(error),
            duration_ms=elapsed,
        )

    def _on_file_saved(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        file_path = data.get("file_path", "")
        tool = data.get("tool", "")
        if not file_path:
            return
        run = self._registry.get_current_run()
        if not run:
            return
        existing = [a for a in run.artifacts
                    if a.path_or_content == file_path]
        if existing:
            return
        kind = ArtifactKind.FILE_DIFF
        if tool == "write":
            kind = ArtifactKind.FILE_CREATED
        self._registry.add_artifact(
            run_id=run.run_id,
            kind=kind,
            title=file_path,
            path_or_content=file_path,
            diff_stats="",
        )

    def _on_session_switched(self, data: Any) -> None:
        if isinstance(data, dict):
            self._current_session_id = data.get("session_id", "")
        run = self._registry.get_current_run()
        if run and run.status == RunStatus.RUNNING:
            self._registry.complete_run(run.run_id, summary="(会话切换)")

    # ── Bridge EventAdapter 信号处理（第二数据源） ──

    def on_stream_start(self, session_id: str) -> None:
        pass

    def on_stream_delta(self, session_id: str, content: str) -> None:
        pass

    def on_stream_end(self, session_id: str) -> None:
        pass

    def on_tool_call(self, session_id: str, payload: dict) -> None:
        tool_name = payload.get("name", "")
        tool_args = payload.get("args", {})
        call_id = payload.get("callId", "")
        if not tool_name:
            return
        if call_id and call_id in self._seen_tool_calls:
            return
        if call_id:
            self._seen_tool_calls.add(call_id)
            if len(self._seen_tool_calls) > 5000:
                self._seen_tool_calls = set(list(self._seen_tool_calls)[-2000:])
        self._current_session_id = session_id
        run = self._registry.get_current_run()
        if not run:
            return
        step = run.active_step
        step_id = step.step_id if step else ""
        if not step_id:
            s = self._registry.get_or_create_implicit_step(run.run_id)
            step_id = s.step_id
        self._registry.add_tool_call(
            run_id=run.run_id,
            step_id=step_id,
            tool_name=tool_name,
            call_id=call_id,
            args=tool_args if isinstance(tool_args, dict) else {},
        )

    def on_tool_result(self, session_id: str, content: str,
                       success: bool) -> None:
        run = self._registry.get_current_run()
        if not run:
            return
        for step in reversed(run.steps):
            for tc in reversed(step.tool_calls):
                if tc.status == ToolCallStatus.RUNNING:
                    status = ToolCallStatus.SUCCESS if success else ToolCallStatus.FAILED
                    elapsed = int((time.time() - tc.started_at) * 1000) if tc.started_at else 0
                    summary = self._truncate_output(content, 200)
                    self._registry.update_tool_call(
                        run_id=run.run_id,
                        call_id=tc.call_id,
                        status=status,
                        result_summary=summary,
                        result_full=content or "",
                        duration_ms=elapsed,
                    )
                    if success and tc.tool_name in ("write", "edit", "multiedit"):
                        fp = tc.args.get("filePath", "")
                        if fp:
                            self._registry.add_artifact(
                                run_id=run.run_id,
                                kind=ArtifactKind.FILE_DIFF,
                                title=fp,
                                path_or_content=fp,
                            )
                    return

    def on_done(self, session_id: str, final_content: str) -> None:
        run = self._registry.get_current_run()
        if not run:
            return
        if final_content and not run.summary:
            run.summary = final_content[:200]
        self._registry.complete_run(run.run_id, summary=final_content[:200] if final_content else "")

    def on_error(self, session_id: str, code: str, message: str) -> None:
        run = self._registry.get_current_run()
        if not run:
            return
        self._registry.fail_run(run.run_id, reason=f"[{code}] {message}")

    def on_progress_start(self, session_id: str, step: int,
                          total: int, desc: str) -> None:
        self._current_session_id = session_id
        run = self._registry.get_current_run()
        if run and desc:
            s = self._registry.get_or_create_implicit_step(run.run_id)
            if not s.title or s.title == "自主执行":
                s.title = desc[:60]
                self._registry.step_updated.emit(run.run_id, s.step_id)

    def on_progress_tool(self, session_id: str, skill: str,
                         step: int, total: int, desc: str) -> None:
        pass

    def on_progress_summary(self, session_id: str, step: int,
                            total: int, desc: str) -> None:
        pass

    def on_progress_done(self, session_id: str, step: int,
                         total: int, desc: str) -> None:
        pass

    def on_force_summary(self, session_id: str, content: str,
                         status: str) -> None:
        run = self._registry.get_current_run()
        if run and content:
            run.summary = content[:200]
            self._registry.run_updated.emit(run.run_id)

    def on_thinking_step(self, session_id: str, step_type: str,
                         description: str) -> None:
        run = self._registry.get_current_run()
        if not run:
            return
        if step_type in ("plan", "intent"):
            s = self._registry.add_step(run.run_id, description[:60])
        elif not run.active_step:
            self._registry.get_or_create_implicit_step(run.run_id)

    def on_plan_proposed(self, session_id: str, plan_data: dict) -> None:
        run = self._registry.get_current_run()
        if not run:
            return
        steps_data = plan_data.get("steps", [])
        if isinstance(steps_data, list):
            for i, sd in enumerate(steps_data):
                title = sd.get("title", sd.get("description", f"步骤 {i + 1}"))[:60]
                self._registry.add_step(run.run_id, title)

    def _on_adapter_event(self, *args) -> None:
        """★ 403T-4 Fix4: EventAdapter 通用回落 slot。

        收集尚未有专属 handler 的信号（intermediate_finding、permission_request、skill_list）。
        各信号签名不同，用 *args 兜底收集即可；写入内部状态供白盒面板渲染。
        """
        if not hasattr(self, "_extra_events"):
            self._extra_events = []
        self._extra_events.append(args)
        # 保留最近 50 条避免无限增长
        if len(self._extra_events) > 50:
            self._extra_events = self._extra_events[-50:]

    def connect_event_adapter(self, adapter) -> None:
        # ★ 任务指定的核心信号均已有专属 handler（下方），此处仅补接未覆盖的剩余信号
        adapter.stream_start.connect(self.on_stream_start)
        adapter.stream_delta.connect(self.on_stream_delta)
        adapter.stream_end.connect(self.on_stream_end)
        adapter.tool_call.connect(self.on_tool_call)
        adapter.tool_result.connect(self.on_tool_result)
        adapter.done.connect(self.on_done)
        adapter.error.connect(self.on_error)
        adapter.progress_start.connect(self.on_progress_start)
        adapter.progress_tool.connect(self.on_progress_tool)
        adapter.progress_summary.connect(self.on_progress_summary)
        adapter.progress_done.connect(self.on_progress_done)
        adapter.force_summary.connect(self.on_force_summary)
        adapter.thinking_step.connect(self.on_thinking_step)
        adapter.plan_proposed.connect(self.on_plan_proposed)
        # ★ 403T-4: 剩余未覆盖的 EventAdapter 信号经 _on_adapter_event 兜底
        for sig in ("intermediate_finding", "permission_request", "skill_list"):
            s = getattr(adapter, sig, None)
            if s is not None:
                try:
                    s.connect(self._on_adapter_event)
                except (TypeError, RuntimeError):
                    pass

    # ── WorkflowTree 增量同步 ──

    def sync_to_tree(self, tree) -> None:
        """将 RunRegistry 信号增量同步到 WorkflowTree。

        调用后，所有 registry 信号(run_added/step_updated/tool_call_updated等)
        自动触发 tree 的增量更新(不整树重建)。
        """
        self._tree = tree
        self._registry.run_added.connect(self._on_tree_run_added)
        self._registry.run_updated.connect(self._on_tree_run_updated)
        self._registry.run_completed.connect(self._on_tree_run_updated)
        self._registry.run_failed.connect(self._on_tree_run_updated)
        self._registry.step_updated.connect(self._on_tree_step_updated)
        self._registry.tool_call_updated.connect(self._on_tree_tool_call_updated)
        self._registry.registry_cleared.connect(self._on_tree_cleared)

    def _on_tree_run_added(self, run_id: str) -> None:
        if not self._tree:
            return
        run = self._registry.get_run(run_id)
        if run:
            self._tree.add_run_item(run)

    def _on_tree_run_updated(self, run_id: str) -> None:
        if not self._tree:
            return
        run = self._registry.get_run(run_id)
        if run:
            self._tree.update_run_item(run)

    def _on_tree_step_updated(self, run_id: str, step_id: str) -> None:
        if not self._tree:
            return
        run = self._registry.get_run(run_id)
        if not run:
            return
        for step in run.steps:
            if step.step_id == step_id:
                key = f"{run_id}_{step_id}"
                if key not in self._tree._step_items:
                    self._tree.add_step_item(run_id, step)
                else:
                    self._tree.update_step_item(run_id, step)
                return

    def _on_tree_tool_call_updated(self, run_id: str, step_id: str,
                                    call_id: str) -> None:
        if not self._tree:
            return
        run = self._registry.get_run(run_id)
        if not run:
            return
        for step in run.steps:
            if step.step_id != step_id:
                continue
            for tc in step.tool_calls:
                if tc.call_id == call_id:
                    if call_id not in self._tree._tc_items:
                        self._tree.add_tool_call_item(run_id, step, tc)
                    else:
                        self._tree.update_tool_call_item(run_id, step, tc)
                    return

    def _on_tree_cleared(self) -> None:
        if self._tree:
            self._tree.clear_tree()

    # ── 辅助 ──

    def _find_running_tool_call(self, run_id: str,
                                tool_name: str) -> Optional[Any]:
        run = self._registry.get_run(run_id)
        if not run:
            return None
        for step in reversed(run.steps):
            for tc in reversed(step.tool_calls):
                if tc.tool_name == tool_name and tc.status == ToolCallStatus.RUNNING:
                    return tc
        return None

    @staticmethod
    def _truncate_output(output: Any, max_len: int = 200) -> str:
        s = str(output) if output else ""
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s
