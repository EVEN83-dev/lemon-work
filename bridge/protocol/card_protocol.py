"""
B-P2-004: Card Protocol

Defines card data format for frontend-backend communication.
All card types and their data schemas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CardType(str, Enum):
    TEXT = "text"
    CODE = "code"
    DOCUMENT = "document"
    SEARCH = "search"
    IMAGE = "image"
    CHART = "chart"
    POMODORO = "pomodoro"
    TASK = "task"
    MEMORY = "memory"
    SKILL_CALL = "skill_call"
    TOOL_EXECUTION = "tool_execution"
    WEATHER = "weather"
    CALENDAR = "calendar"
    FILE = "file"
    CONTACT = "contact"
    AUDIO = "audio"
    ERROR = "error"


@dataclass
class CardAction:
    label: str
    action: str

    def to_dict(self) -> Dict[str, str]:
        return {"label": self.label, "action": self.action}


@dataclass
class CardMetadata:
    skill: str = ""
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"skill": self.skill, "duration_ms": self.duration_ms}


@dataclass
class CardData:
    type: CardType = CardType.TEXT
    title: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    actions: List[CardAction] = field(default_factory=list)
    metadata: CardMetadata = field(default_factory=CardMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "card": {
                "type": self.type.value,
                "title": self.title,
                "data": self.data,
                "actions": [a.to_dict() for a in self.actions],
                "metadata": self.metadata.to_dict(),
            }
        }

    def to_json_str(self) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)


def make_text_card(content: str, title: str = "") -> CardData:
    return CardData(
        type=CardType.TEXT,
        title=title,
        data={"content": content},
    )


def make_code_card(
    code: str,
    language: str = "python",
    can_run: bool = True,
    can_copy: bool = True,
    title: str = "",
) -> CardData:
    actions = []
    if can_run:
        actions.append(CardAction("运行", "run"))
    if can_copy:
        actions.append(CardAction("复制", "copy"))
    return CardData(
        type=CardType.CODE,
        title=title,
        data={"code": code, "language": language, "can_run": can_run, "can_copy": can_copy},
        actions=actions,
    )


def make_document_card(
    content: str,
    format: str = "md",
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.DOCUMENT,
        title=title,
        data={"content": content, "format": format},
        actions=[
            CardAction("编辑", "edit"),
            CardAction("下载", "download"),
        ],
    )


def make_search_card(
    results: List[Dict[str, str]],
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.SEARCH,
        title=title,
        data={"results": results},
    )


def make_image_card(
    original_url: str = "",
    processed_url: str = "",
    description: str = "",
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.IMAGE,
        title=title,
        data={"original_url": original_url, "processed_url": processed_url, "description": description},
    )


def make_chart_card(
    chart_type: str = "line",
    title: str = "",
    **kwargs,
) -> CardData:
    data = {"chart_type": chart_type, **kwargs}
    return CardData(type=CardType.CHART, title=title, data=data)


def make_pomodoro_card(
    total_seconds: int = 1500,
    remaining: int = 1500,
    is_running: bool = False,
    task_id: str = "",
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.POMODORO,
        title=title,
        data={
            "total_seconds": total_seconds,
            "remaining": remaining,
            "is_running": is_running,
            "task_id": task_id,
        },
        actions=[
            CardAction("开始", "start"),
            CardAction("暂停", "pause"),
            CardAction("停止", "stop"),
        ],
    )


def make_task_card(
    task_name: str,
    progress: int = 0,
    description: str = "",
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.TASK,
        title=title,
        data={"task_name": task_name, "progress": progress, "description": description},
    )


def make_memory_card(
    items: List[Dict[str, Any]],
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.MEMORY,
        title=title,
        data={"items": items},
    )


def make_skill_call_card(
    skill_name: str,
    status: str = "running",
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.SKILL_CALL,
        title=title,
        data={"skill_name": skill_name, "status": status},
    )


def make_weather_card(
    location: str = "",
    temperature: int = 0,
    condition: str = "",
    wind: str = "",
    humidity: str = "",
    feels_like: int = 0,
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.WEATHER,
        title=title or location,
        data={
            "location": location,
            "temperature": temperature,
            "condition": condition,
            "wind": wind,
            "humidity": humidity,
            "feels_like": feels_like,
        },
    )


def make_calendar_card(
    events: List[Dict[str, str]],
    date: str = "",
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.CALENDAR,
        title=title or "日程",
        data={"events": events, "date": date},
    )


def make_file_card(
    name: str = "",
    size: str = "",
    type: str = "",
    path: str = "",
    modified: str = "",
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.FILE,
        title=title,
        data={"name": name, "size": size, "type": type, "path": path, "modified": modified},
        actions=[
            CardAction("打开", "open"),
            CardAction("分享", "share"),
        ],
    )


def make_contact_card(
    name: str = "",
    phone: str = "",
    email: str = "",
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.CONTACT,
        title=title,
        data={"name": name, "phone": phone, "email": email},
        actions=[
            CardAction("拨打", "call"),
            CardAction("短信", "sms"),
        ],
    )


def make_audio_card(
    title: str = "",
    duration_sec: int = 0,
    uri: str = "",
) -> CardData:
    return CardData(
        type=CardType.AUDIO,
        title=title,
        data={"title": title, "duration_sec": duration_sec, "uri": uri},
        actions=[
            CardAction("播放", "play"),
            CardAction("删除", "delete"),
        ],
    )


def make_error_card(
    message: str,
    code: str = "ERROR",
    title: str = "",
) -> CardData:
    return CardData(
        type=CardType.ERROR,
        title=title,
        data={"message": message, "code": code},
    )


def make_tool_execution_card(
    tool_name: str,
    status: str = "running",
    args: dict = None,
    description: str = "",
    duration_ms: int = 0,
    call_id: str = "",
) -> CardData:
    return CardData(
        type=CardType.TOOL_EXECUTION,
        title=f"执行: {tool_name}",
        data={
            "toolName": tool_name,
            "status": status,
            "args": args or {},
            "description": description,
            "durationMs": duration_ms,
            "callId": call_id,
        },
        metadata=CardMetadata(skill=tool_name, duration_ms=duration_ms),
    )
