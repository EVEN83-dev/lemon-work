# -*- coding: utf-8 -*-
"""Skill: clipboard_helper — 剪贴板历史/划词处理"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "clipboard_helper",
    "description": "剪贴板助手：读取/写入剪贴板，支持文本格式化（去空行/排序/去重/大小写转换），纯只读操作。",
    "category": "productivity",
    "version": "1.0.0",
}

_HISTORY_MAX = 100
_history = []


def execute(action: str = "read", text: str = "", format_op: str = "") -> SkillResult:
    if action == "read":
        content = _read_clipboard()
        if content is None:
            return SkillResult(success=False, error="无法读取剪贴板")
        _add_history(content)
        return SkillResult(success=True, output=f"剪贴板内容:\n{content}",
                           data={"content": content, "action": "read"})

    if action == "write":
        if not text:
            return SkillResult(success=False, error="write操作需要text参数")
        ok = _write_clipboard(text)
        if ok:
            _add_history(text)
            return SkillResult(success=True, output=f"已写入剪贴板: {text[:100]}",
                               data={"action": "write", "length": len(text)})
        return SkillResult(success=False, error="写入剪贴板失败")

    if action == "format":
        content = text or _read_clipboard() or ""
        if not content:
            return SkillResult(success=False, error="无内容可格式化")
        formatted = _format_text(content, format_op)
        return SkillResult(success=True, output=f"格式化结果({format_op}):\n{formatted}",
                           data={"action": "format", "format_op": format_op})

    if action == "history":
        lines = [f"{i+1}. {h[:80]}" for i, h in enumerate(_history[-20:])]
        return SkillResult(success=True, output="剪贴板历史:\n" + "\n".join(lines),
                           data={"count": len(_history), "action": "history"})

    return SkillResult(success=False, error=f"未知操作: {action}")


def _read_clipboard() -> str:
    try:
        import pyperclip
        return pyperclip.paste()
    except ImportError:
        pass
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        clipboard = app.clipboard()
        return clipboard.text()
    except Exception:
        pass
    return None


def _write_clipboard(text: str) -> bool:
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except ImportError:
        pass
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        clipboard = app.clipboard()
        clipboard.setText(text)
        return True
    except Exception:
        return False


def _format_text(text: str, op: str) -> str:
    if op == "dedup":
        lines = list(dict.fromkeys(text.splitlines()))
        return "\n".join(lines)
    if op == "sort":
        return "\n".join(sorted(text.splitlines()))
    if op == "strip":
        return "\n".join(l for l in text.splitlines() if l.strip())
    if op == "upper":
        return text.upper()
    if op == "lower":
        return text.lower()
    if op == "trim":
        return "\n".join(l.strip() for l in text.splitlines())
    return text


def _add_history(content: str):
    if content and content not in _history[-5:]:
        _history.append(content)
        while len(_history) > _HISTORY_MAX:
            _history.pop(0)


def register(registry) -> None:
    registry.register(SkillDef(
        name="clipboard_helper",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["read", "write", "format", "history"],
                           "description": "操作类型", "default": "read"},
                "text": {"type": "string", "description": "写入/格式化的文本"},
                "format_op": {"type": "string",
                              "enum": ["dedup", "sort", "strip", "upper", "lower", "trim"],
                              "description": "格式化操作"},
            },
            "required": [],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=10,
    ))


def get_metadata():
    return METADATA
