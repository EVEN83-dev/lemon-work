"""
B-009: Lemon Bridge Communication Protocol

Defines JSON message schemas for ArkTS frontend <-> Python Bridge WebSocket communication.
All messages are JSON objects with a required "type" field.

Also re-exports card protocol types for convenience.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageType(str, Enum):
    CHAT = "chat"
    STREAM_DELTA = "stream_delta"
    STREAM_START = "stream_start"
    STREAM_END = "stream_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    DONE = "done"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"
    SKILL_LIST = "skill_list"
    ENGINE_LIST = "engine_list"
    SESSION_LIST = "session_list"
    SESSION_CREATE = "session_create"
    SESSION_INFO = "session_info"
    SETTING_SAVE = "setting_save"
    SETTING_LOAD = "setting_load"
    FILE_UPLOAD = "file_upload"
    FILE_RESULT = "file_result"
    CODE_RUN = "code_run"
    CODE_RESULT = "code_result"
    APP_LAUNCH = "app_launch"
    APP_RESULT = "app_result"
    SYSTEM_REQUEST = "system_request"
    SYSTEM_RESULT = "system_result"
    TOOL_EXECUTE = "tool_execute"
    TOOL_EXECUTE_RESULT = "tool_execute_result"
    PLAN_PROPOSED = "plan_proposed"
    PLAN_CONFIRMED = "plan_confirmed"
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_RESPONSE = "permission_response"
    INTENT_RECOGNIZE = "intent_recognize"
    INTENT_RESULT = "intent_result"
    AGENT_DISPATCH = "agent_dispatch"
    AGENT_RESULT = "agent_result"
    PLUGIN_EVENT = "plugin_event"
    EMBED_TEXT = "embed_text"
    EMBED_RESULT = "embed_result"
    MCP_CALL = "mcp_call"
    MCP_RESULT = "mcp_result"
    POMODORO_START = "pomodoro_start"
    POMODORO_STOP = "pomodoro_stop"
    POMODORO_RESULT = "pomodoro_result"
    MEMORY_ADD = "memory_add"
    MEMORY_SEARCH = "memory_search"
    MEMORY_RESULT = "memory_result"
    COMMAND_PARSE = "command_parse"
    COMMAND_RESULT = "command_result"
    TASK_CREATE = "task_create"
    TASK_RESULT = "task_result"
    PROGRESS_START = "progress_start"
    PROGRESS_TOOL = "progress_tool"
    PROGRESS_SUMMARY = "progress_summary"
    PROGRESS_DONE = "progress_done"
    INTERMEDIATE_FINDING = "intermediate_finding"
    FORCE_SUMMARY = "force_summary"
    THINKING_STEP = "thinking_step"


class ErrorCode(str, Enum):
    ENGINE_UNAVAILABLE = "ENGINE_UNAVAILABLE"
    SKILL_NOT_FOUND = "SKILL_NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    TIMEOUT = "TIMEOUT"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_FAILED = "AUTH_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL = "INTERNAL"
    SANDBOX_ERROR = "SANDBOX_ERROR"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TASK_CANCELLED = "TASK_CANCELLED"


@dataclass
class BridgeMessage:
    type: str
    id: str = ""
    sessionId: str = ""
    timestamp: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = time.time()

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "id": self.id,
            "sessionId": self.sessionId,
            "timestamp": self.timestamp,
            **self.payload,
        }, ensure_ascii=False)

    @staticmethod
    def from_json(raw: str) -> BridgeMessage:
        data = json.loads(raw)
        msg_type = data.pop("type", "")
        msg_id = data.pop("id", "")
        session_id = data.pop("sessionId", "")
        ts = data.pop("timestamp", 0.0)
        return BridgeMessage(
            type=msg_type,
            id=msg_id,
            sessionId=session_id,
            timestamp=ts,
            payload=data,
        )


def make_chat_message(session_id: str, content: str, skill: str = "",
                      files: Optional[List[str]] = None) -> BridgeMessage:
    payload: Dict[str, Any] = {"content": content}
    if skill:
        payload["skill"] = skill
    if files:
        payload["files"] = files
    return BridgeMessage(type=MessageType.CHAT, sessionId=session_id, payload=payload)


def make_stream_delta(content: str, session_id: str = "") -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.STREAM_DELTA,
        sessionId=session_id,
        payload={"content": content},
    )


def make_stream_start(session_id: str = "", model: str = "") -> BridgeMessage:
    payload: Dict[str, Any] = {}
    if model:
        payload["model"] = model
    return BridgeMessage(type=MessageType.STREAM_START, sessionId=session_id, payload=payload)


def make_stream_end(session_id: str = "") -> BridgeMessage:
    return BridgeMessage(type=MessageType.STREAM_END, sessionId=session_id)


def make_tool_call(name: str, args: Dict[str, Any], session_id: str = "",
                   call_id: str = "") -> BridgeMessage:
    payload: Dict[str, Any] = {"name": name, "args": args}
    if call_id:
        payload["callId"] = call_id
    return BridgeMessage(type=MessageType.TOOL_CALL, sessionId=session_id, payload=payload)


def make_tool_result(content: str, call_id: str = "", session_id: str = "",
                     success: bool = True) -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.TOOL_RESULT,
        sessionId=session_id,
        payload={"content": content, "callId": call_id, "success": success},
    )


def make_done(final_content: str, session_id: str = "") -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.DONE,
        sessionId=session_id,
        payload={"finalContent": final_content},
    )


def make_error(code: ErrorCode, message: str, session_id: str = "") -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.ERROR,
        sessionId=session_id,
        payload={"code": code.value, "message": message},
    )


def make_skill_list(skills: List[Dict[str, Any]]) -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.SKILL_LIST,
        payload={"skills": skills},
    )


def make_engine_list(engines: List[Dict[str, Any]]) -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.ENGINE_LIST,
        payload={"engines": engines},
    )


def make_session_list(sessions: List[Dict[str, Any]]) -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.SESSION_LIST,
        payload={"sessions": sessions},
    )


def make_session_info(session: Dict[str, Any]) -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.SESSION_INFO,
        payload={"session": session},
    )


def make_code_result(status: str, output: str, duration: float = 0.0,
                     error: str = "") -> BridgeMessage:
    payload: Dict[str, Any] = {"status": status, "output": output, "duration": duration}
    if error:
        payload["error"] = error
    return BridgeMessage(type=MessageType.CODE_RESULT, payload=payload)


def make_file_result(file_id: str, filename: str, url: str = "",
                     size: int = 0) -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.FILE_RESULT,
        payload={"fileId": file_id, "filename": filename, "url": url, "size": size},
    )


from .card_protocol import (
    CardType, CardAction, CardMetadata, CardData,
    make_text_card, make_code_card, make_document_card, make_search_card,
    make_image_card, make_chart_card, make_pomodoro_card, make_task_card,
    make_memory_card, make_skill_call_card, make_weather_card, make_calendar_card,
    make_file_card, make_contact_card, make_audio_card, make_error_card,
    make_tool_execution_card,
)


def make_progress_start(session_id: str, step: int = 0, total_steps: int = 0,
                        description: str = "") -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.PROGRESS_START,
        sessionId=session_id,
        payload={"step": step, "totalSteps": total_steps, "description": description},
    )


def make_progress_tool(session_id: str, skill_name: str, step: int = 0,
                       total_steps: int = 0, description: str = "") -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.PROGRESS_TOOL,
        sessionId=session_id,
        payload={"skillName": skill_name, "step": step,
                 "totalSteps": total_steps, "description": description},
    )


def make_progress_summary(session_id: str, step: int = 0,
                          total_steps: int = 0, description: str = "") -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.PROGRESS_SUMMARY,
        sessionId=session_id,
        payload={"step": step, "totalSteps": total_steps, "description": description},
    )


def make_progress_done(session_id: str, step: int = 0,
                       total_steps: int = 0, description: str = "") -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.PROGRESS_DONE,
        sessionId=session_id,
        payload={"step": step, "totalSteps": total_steps, "description": description},
    )


def make_intermediate_finding(session_id: str, content: str,
                              source_skill: str = "", importance: str = "normal",
                              files_analyzed: int = 0) -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.INTERMEDIATE_FINDING,
        sessionId=session_id,
        payload={"content": content, "sourceSkill": source_skill,
                 "importance": importance, "filesAnalyzed": files_analyzed},
    )


def make_force_summary(session_id: str, content: str, status: str = "partial",
                       score: int = 0) -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.FORCE_SUMMARY,
        sessionId=session_id,
        payload={"content": content, "status": status, "score": score},
    )


def make_permission_request(session_id: str, skill_name: str, args: Dict[str, Any],
                            request_id: str = "") -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.PERMISSION_REQUEST,
        sessionId=session_id,
        payload={"skillName": skill_name, "args": args, "requestId": request_id},
    )


def make_permission_response(session_id: str, request_id: str,
                             approved: bool) -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.PERMISSION_RESPONSE,
        sessionId=session_id,
        payload={"requestId": request_id, "approved": approved},
    )


def make_thinking_step(session_id: str, step_type: str,
                       description: str, details: Dict[str, Any] = None,
                       duration_ms: float = 0.0) -> BridgeMessage:
    return BridgeMessage(
        type=MessageType.THINKING_STEP,
        sessionId=session_id,
        payload={
            "stepType": step_type,
            "description": description,
            "details": details or {},
            "durationMs": duration_ms,
        },
    )
