# -*- coding: utf-8 -*-
"""364章 T4.4: Hooks — 工具调用前后钩子"""

import time
from typing import Callable, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class HookEvent:
    hook_type: str
    tool_name: str
    timestamp: float = 0.0
    args: Dict = field(default_factory=dict)
    result: object = None
    error: str = ""


HookCallback = Callable[[HookEvent], None]


class HookManager:
    def __init__(self):
        self._before_hooks: Dict[str, List[HookCallback]] = {}
        self._after_hooks: Dict[str, List[HookCallback]] = {}
        self._error_hooks: Dict[str, List[HookCallback]] = {}
        self._log: List[HookEvent] = []

    def register_before(self, tool_name: str, callback: HookCallback):
        self._before_hooks.setdefault(tool_name, []).append(callback)

    def register_after(self, tool_name: str, callback: HookCallback):
        self._after_hooks.setdefault(tool_name, []).append(callback)

    def register_error(self, tool_name: str, callback: HookCallback):
        self._error_hooks.setdefault(tool_name, []).append(callback)

    def fire_before(self, tool_name: str, args: Dict = None):
        event = HookEvent(hook_type="before", tool_name=tool_name,
                          timestamp=time.time(), args=args or {})
        for cb in self._before_hooks.get(tool_name, []):
            try:
                cb(event)
            except Exception:
                pass
        for cb in self._before_hooks.get("*", []):
            try:
                cb(event)
            except Exception:
                pass
        self._log.append(event)

    def fire_after(self, tool_name: str, result: object = None, args: Dict = None):
        event = HookEvent(hook_type="after", tool_name=tool_name,
                          timestamp=time.time(), result=result, args=args or {})
        for cb in self._after_hooks.get(tool_name, []):
            try:
                cb(event)
            except Exception:
                pass
        for cb in self._after_hooks.get("*", []):
            try:
                cb(event)
            except Exception:
                pass
        self._log.append(event)

    def fire_error(self, tool_name: str, error: str, args: Dict = None):
        event = HookEvent(hook_type="error", tool_name=tool_name,
                          timestamp=time.time(), error=error, args=args or {})
        for cb in self._error_hooks.get(tool_name, []):
            try:
                cb(event)
            except Exception:
                pass
        for cb in self._error_hooks.get("*", []):
            try:
                cb(event)
            except Exception:
                pass
        self._log.append(event)

    def get_log(self, tool_name: str = "", hook_type: str = "",
                limit: int = 50) -> List[Dict]:
        events = self._log
        if tool_name:
            events = [e for e in events if e.tool_name == tool_name]
        if hook_type:
            events = [e for e in events if e.hook_type == hook_type]
        return [{"type": e.hook_type, "tool": e.tool_name,
                 "timestamp": e.timestamp, "error": e.error}
                for e in events[-limit:]]

    def clear_hooks(self, tool_name: str = ""):
        if tool_name:
            self._before_hooks.pop(tool_name, None)
            self._after_hooks.pop(tool_name, None)
            self._error_hooks.pop(tool_name, None)
        else:
            self._before_hooks.clear()
            self._after_hooks.clear()
            self._error_hooks.clear()
