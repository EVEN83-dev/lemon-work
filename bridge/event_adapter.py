# -*- coding: utf-8 -*-
"""
A-1: Bridge Event Adapter — 桥接 Bridge 协议事件到 standard_mode Qt 信号系统
============================================================================

将 bridge/agent_loop.py 的 BridgeMessage 回调体系转换为 PyQt5 信号，
使 standard_mode/ui/main_window.py 能够统一消费 bridge 层的事件，
而不需要直接依赖 bridge 内部协议。

架构断链修复核心：
  bridge/agent_loop → _on_message(BridgeMessage)
      ↓
  EventAdapter.on_bridge_message(BridgeMessage)
      ↓  (分拣类型 → emit 对应 Qt 信号)
  main_window 槽函数

使用方式：
    adapter = EventAdapter(parent=window)
    agent_loop.set_message_callback(adapter.on_bridge_message)
    adapter.stream_delta.connect(window._on_stream_token)
    adapter.stream_end.connect(window._on_stream_done)
    ...
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from bridge.protocol import (
    BridgeMessage, MessageType, ErrorCode,
    make_error,
)

logger = logging.getLogger(__name__)


class EventAdapter(QObject):
    """
    BridgeMessage → Qt Signal 适配器

    将 bridge 协议的结构化消息分拣为细粒度 Qt 信号，
    供 standard_mode UI 组件订阅。
    """

    stream_start = pyqtSignal(str)            # session_id
    stream_delta = pyqtSignal(str, str)       # session_id, content
    stream_end = pyqtSignal(str)              # session_id
    tool_call = pyqtSignal(str, dict)         # session_id, {name, args, callId}
    tool_result = pyqtSignal(str, str, bool)  # session_id, content, success
    done = pyqtSignal(str, str)               # session_id, final_content
    error = pyqtSignal(str, str, str)         # session_id, error_code, message
    progress_start = pyqtSignal(str, int, int, str)   # session_id, step, total, desc
    progress_tool = pyqtSignal(str, str, int, int, str)  # session_id, skill, step, total, desc
    progress_summary = pyqtSignal(str, int, int, str)   # session_id, step, total, desc
    progress_done = pyqtSignal(str, int, int, str)      # session_id, step, total, desc
    intermediate_finding = pyqtSignal(str, str, str)    # session_id, content, importance
    force_summary = pyqtSignal(str, str, str)           # session_id, content, status
    permission_request = pyqtSignal(str, str, dict)     # session_id, skill_name, args
    thinking_step = pyqtSignal(str, str, str)           # session_id, step_type, description
    plan_proposed = pyqtSignal(str, dict)               # session_id, plan_data
    skill_list = pyqtSignal(list)                       # skills list

    _TYPE_HANDLER_MAP: Dict[str, str] = {}

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._build_type_handler_map()
        self._last_session_id: str = ""

    def _build_type_handler_map(self) -> None:
        if EventAdapter._TYPE_HANDLER_MAP:
            return
        mapping = {
            MessageType.STREAM_START: "_handle_stream_start",
            MessageType.STREAM_DELTA: "_handle_stream_delta",
            MessageType.STREAM_END: "_handle_stream_end",
            MessageType.TOOL_CALL: "_handle_tool_call",
            MessageType.TOOL_RESULT: "_handle_tool_result",
            MessageType.DONE: "_handle_done",
            MessageType.ERROR: "_handle_error",
            MessageType.PROGRESS_START: "_handle_progress_start",
            MessageType.PROGRESS_TOOL: "_handle_progress_tool",
            MessageType.PROGRESS_SUMMARY: "_handle_progress_summary",
            MessageType.PROGRESS_DONE: "_handle_progress_done",
            MessageType.INTERMEDIATE_FINDING: "_handle_intermediate_finding",
            MessageType.FORCE_SUMMARY: "_handle_force_summary",
            MessageType.PERMISSION_REQUEST: "_handle_permission_request",
            MessageType.THINKING_STEP: "_handle_thinking_step",
            MessageType.PLAN_PROPOSED: "_handle_plan_proposed",
            MessageType.SKILL_LIST: "_handle_skill_list",
        }
        EventAdapter._TYPE_HANDLER_MAP = {k.value: v for k, v in mapping.items()}

    def on_bridge_message(self, msg: BridgeMessage) -> None:
        sid = msg.sessionId or self._last_session_id
        if msg.sessionId:
            self._last_session_id = msg.sessionId

        handler_name = self._TYPE_HANDLER_MAP.get(msg.type)
        if handler_name is None:
            logger.debug("EventAdapter: 未处理消息类型 %s", msg.type)
            return
        handler = getattr(self, handler_name, None)
        if handler is not None:
            try:
                handler(sid, msg.payload)
            except Exception:
                logger.exception("EventAdapter 处理 %s 异常", msg.type)

    def _handle_stream_start(self, sid: str, payload: Dict[str, Any]) -> None:
        self.stream_start.emit(sid)

    def _handle_stream_delta(self, sid: str, payload: Dict[str, Any]) -> None:
        content = payload.get("content", "")
        self.stream_delta.emit(sid, content)

    def _handle_stream_end(self, sid: str, payload: Dict[str, Any]) -> None:
        self.stream_end.emit(sid)

    def _handle_tool_call(self, sid: str, payload: Dict[str, Any]) -> None:
        self.tool_call.emit(sid, payload)

    def _handle_tool_result(self, sid: str, payload: Dict[str, Any]) -> None:
        content = payload.get("content", "")
        success = payload.get("success", True)
        self.tool_result.emit(sid, content, success)

    def _handle_done(self, sid: str, payload: Dict[str, Any]) -> None:
        final_content = payload.get("finalContent", "")
        self.done.emit(sid, final_content)

    def _handle_error(self, sid: str, payload: Dict[str, Any]) -> None:
        code = payload.get("code", ErrorCode.INTERNAL.value)
        message = payload.get("message", "未知错误")
        self.error.emit(sid, code, message)

    def _handle_progress_start(self, sid: str, payload: Dict[str, Any]) -> None:
        step = payload.get("step", 0)
        total = payload.get("totalSteps", 0)
        desc = payload.get("description", "")
        self.progress_start.emit(sid, step, total, desc)

    def _handle_progress_tool(self, sid: str, payload: Dict[str, Any]) -> None:
        skill = payload.get("skillName", "")
        step = payload.get("step", 0)
        total = payload.get("totalSteps", 0)
        desc = payload.get("description", "")
        self.progress_tool.emit(sid, skill, step, total, desc)

    def _handle_progress_summary(self, sid: str, payload: Dict[str, Any]) -> None:
        step = payload.get("step", 0)
        total = payload.get("totalSteps", 0)
        desc = payload.get("description", "")
        self.progress_summary.emit(sid, step, total, desc)

    def _handle_progress_done(self, sid: str, payload: Dict[str, Any]) -> None:
        step = payload.get("step", 0)
        total = payload.get("totalSteps", 0)
        desc = payload.get("description", "")
        self.progress_done.emit(sid, step, total, desc)

    def _handle_intermediate_finding(self, sid: str, payload: Dict[str, Any]) -> None:
        content = payload.get("content", "")
        importance = payload.get("importance", "normal")
        self.intermediate_finding.emit(sid, content, importance)

    def _handle_force_summary(self, sid: str, payload: Dict[str, Any]) -> None:
        content = payload.get("content", "")
        status = payload.get("status", "partial")
        self.force_summary.emit(sid, content, status)

    def _handle_permission_request(self, sid: str, payload: Dict[str, Any]) -> None:
        skill_name = payload.get("skillName", "")
        args = payload.get("args", {})
        self.permission_request.emit(sid, skill_name, args)

    def _handle_thinking_step(self, sid: str, payload: Dict[str, Any]) -> None:
        step_type = payload.get("stepType", "")
        description = payload.get("description", "")
        self.thinking_step.emit(sid, step_type, description)

    def _handle_plan_proposed(self, sid: str, payload: Dict[str, Any]) -> None:
        self.plan_proposed.emit(sid, payload)

    def _handle_skill_list(self, sid: str, payload: Dict[str, Any]) -> None:
        skills = payload.get("skills", [])
        self.skill_list.emit(skills)


class BridgeEngineCompat(QObject):
    """
    bridge/engines/EngineManager → shared/engine_manager 接口兼容层

    将 bridge 层无 Qt 依赖的 EngineManager 适配为
    standard_mode 期望的 shared/engine_manager API 子集，
    使 main_window 可以无缝切换到 bridge 层引擎。

    兼容接口：
    - chat(prompt, engine, model, history) → ChatResponse
    - stream_chat(prompt, engine, model) → Generator[str]
    - get_status() → Dict
    - set_model(engine, model)
    - set_mode(mode)
    - is_available / is_busy 等状态查询
    """

    message_complete = pyqtSignal(str)
    token_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    thinking_received = pyqtSignal(str)
    engine_changed = pyqtSignal(str)

    def __init__(self, bridge_engine_manager=None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._bridge_em = bridge_engine_manager
        self._active_role: str = ""
        self._mode: str = "auto"
        self._current_model: Dict[str, str] = {}

    def set_bridge_engine_manager(self, em) -> None:
        self._bridge_em = em

    def _ensure_bridge_em(self):
        if self._bridge_em is None:
            from bridge.engines.engine_manager import EngineManager
            self._bridge_em = EngineManager()
        return self._bridge_em

    @property
    def bridge_engine_manager(self):
        return self._bridge_em

    def chat(self, prompt: str, engine: str = "", model: str = "",
             history=None, **kwargs):
        em = self._ensure_bridge_em()
        messages = []
        if history:
            for m in history:
                if isinstance(m, dict) and "role" in m and "content" in m:
                    messages.append(m)
        messages.append({"role": "user", "content": prompt})
        engine_name = engine or em.get_primary_name() or "ollama"
        try:
            content = em.chat(messages, engine_name=engine_name, **kwargs)
            self.message_complete.emit(content)
            return _CompatChatResponse(content=content)
        except Exception as e:
            err_msg = "Bridge引擎调用失败: " + str(e)
            self.error_occurred.emit(err_msg)
            return _CompatChatResponse(content=err_msg)

    def stream_chat(self, prompt: str, engine: str = "", model: str = "",
                    **kwargs):
        em = self._ensure_bridge_em()
        messages = [{"role": "user", "content": prompt}]
        engine_name = engine or em.get_primary_name() or "ollama"
        try:
            for token in em.chat_stream(messages, engine_name=engine_name, **kwargs):
                self.token_received.emit(token)
                yield token
        except Exception as e:
            err_msg = "Bridge流式调用失败: " + str(e)
            self.error_occurred.emit(err_msg)
            yield err_msg

    def get_status(self) -> Dict[str, Any]:
        em = self._ensure_bridge_em()
        health = em.health_check()
        status = {}
        for name, available in health.items():
            status[name] = {
                "available": available,
                "model": self._current_model.get(name, ""),
            }
        return status

    def set_model(self, engine: str, model: str) -> None:
        self._current_model[engine] = model
        self.engine_changed.emit(engine)

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def get_mode(self) -> str:
        return self._mode

    def list_models(self, engine: str = "") -> list:
        return []

    def is_available(self, engine: str = "") -> bool:
        em = self._ensure_bridge_em()
        health = em.health_check()
        if engine:
            return health.get(engine, False)
        return any(health.values())


class _CompatChatResponse:
    __slots__ = ("content", "engine", "model", "usage")

    def __init__(self, content: str = "", engine: str = "", model: str = "",
                 usage: Optional[Dict[str, Any]] = None):
        self.content = content
        self.engine = engine
        self.model = model
        self.usage = usage or {}


def get_event_adapter() -> EventAdapter:
    if not hasattr(get_event_adapter, "_instance"):
        get_event_adapter._instance = EventAdapter()
    return get_event_adapter._instance


def get_bridge_engine_compat() -> BridgeEngineCompat:
    if not hasattr(get_bridge_engine_compat, "_instance"):
        get_bridge_engine_compat._instance = BridgeEngineCompat()
    return get_bridge_engine_compat._instance
