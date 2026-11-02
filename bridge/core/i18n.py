"""
B-004: i18n - simple internationalization support.
"""
from __future__ import annotations

from typing import Dict


_translations: Dict[str, Dict[str, str]] = {
    "zh": {
        "welcome": "欢迎使用 Lemon Agent",
        "new_chat": "新对话",
        "send": "发送",
        "thinking": "思考中...",
        "error.engine_unavailable": "AI 引擎不可用",
        "error.skill_not_found": "未找到该技能",
        "error.timeout": "请求超时",
        "error.internal": "内部错误",
        "skill.execute": "正在执行技能: {name}",
        "session.created": "会话已创建",
    },
    "en": {
        "welcome": "Welcome to Lemon Agent",
        "new_chat": "New Chat",
        "send": "Send",
        "thinking": "Thinking...",
        "error.engine_unavailable": "AI engine unavailable",
        "error.skill_not_found": "Skill not found",
        "error.timeout": "Request timed out",
        "error.internal": "Internal error",
        "skill.execute": "Executing skill: {name}",
        "session.created": "Session created",
    },
}

_current_lang = "zh"


def set_language(lang: str) -> None:
    global _current_lang
    if lang in _translations:
        _current_lang = lang


def get_language() -> str:
    return _current_lang


def t(key: str, **kwargs) -> str:
    text = _translations.get(_current_lang, {}).get(key, key)
    if kwargs:
        text = text.format(**kwargs)
    return text
