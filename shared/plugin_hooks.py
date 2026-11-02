from __future__ import annotations

import re
import time
import uuid
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


class HookPoint:
    BEFORE_PROCESS = "before_process"
    AFTER_PROCESS = "after_process"
    BEFORE_TOOL_EXECUTE = "before_tool_execute"
    AFTER_TOOL_EXECUTE = "after_tool_execute"
    ON_ERROR = "on_error"
    ON_SKILL_ACTIVATE = "on_skill_activate"
    ON_SESSION_START = "on_session_start"
    ON_SESSION_END = "on_session_end"


@dataclass
class HookRegistration:
    hook_id: str
    point: str
    handler: Callable[[dict], Optional[dict]]
    priority: int = 50
    enabled: bool = True
    description: str = ""


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: Dict[str, HookRegistration] = {}
        self._lock = threading.Lock()

    def register(self, hook: HookRegistration) -> bool:
        with self._lock:
            if hook.hook_id in self._hooks:
                return False
            self._hooks[hook.hook_id] = hook
            return True

    def unregister(self, hook_id: str) -> bool:
        with self._lock:
            if hook_id in self._hooks:
                del self._hooks[hook_id]
                return True
            return False

    def enable(self, hook_id: str) -> bool:
        with self._lock:
            hook = self._hooks.get(hook_id)
            if hook is None:
                return False
            hook.enabled = True
            return True

    def disable(self, hook_id: str) -> bool:
        with self._lock:
            hook = self._hooks.get(hook_id)
            if hook is None:
                return False
            hook.enabled = False
            return True

    def get_hooks(self, point: str) -> List[HookRegistration]:
        with self._lock:
            matched = [h for h in self._hooks.values() if h.point == point and h.enabled]
            return sorted(matched, key=lambda h: h.priority)

    def list_all(self) -> List[HookRegistration]:
        with self._lock:
            return list(self._hooks.values())


class EventBus:
    def __init__(self) -> None:
        self._subscriptions: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, handler: Callable[[dict], Optional[dict]], priority: int = 50) -> str:
        sub_id = uuid.uuid4().hex
        with self._lock:
            self._subscriptions[sub_id] = {
                "event_type": event_type,
                "handler": handler,
                "priority": priority,
            }
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            if subscription_id in self._subscriptions:
                del self._subscriptions[subscription_id]
                return True
            return False

    def publish(self, event_type: str, data: dict) -> dict:
        with self._lock:
            subs = [
                (s["priority"], s["handler"])
                for s in self._subscriptions.values()
                if s["event_type"] == event_type
            ]
        subs.sort(key=lambda x: x[0])

        results: list = []
        errors: list = []

        for _, handler in subs:
            try:
                result = handler(data)
                results.append(result)
            except Exception as exc:
                errors.append(f"{handler.__name__}: {exc}")

        return {"results": results, "errors": errors}


class LoggingHook:
    def __init__(self, max_entries: int = 1000) -> None:
        self._buffer: deque = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def _handler(self, event_data: dict) -> Optional[dict]:
        entry = {
            "timestamp": time.time(),
            "point": event_data.get("_point", "unknown"),
            "summary": {k: v for k, v in event_data.items() if k != "_point"},
        }
        with self._lock:
            self._buffer.append(entry)
        return None

    def create_registrations(self) -> List[HookRegistration]:
        hooks = []
        for point in [
            HookPoint.BEFORE_PROCESS,
            HookPoint.AFTER_PROCESS,
            HookPoint.BEFORE_TOOL_EXECUTE,
            HookPoint.AFTER_TOOL_EXECUTE,
            HookPoint.ON_ERROR,
            HookPoint.ON_SKILL_ACTIVATE,
            HookPoint.ON_SESSION_START,
            HookPoint.ON_SESSION_END,
        ]:
            hooks.append(
                HookRegistration(
                    hook_id=f"logging_{point}",
                    point=point,
                    handler=self._handler,
                    priority=99,
                    description="Logging hook",
                )
            )
        return hooks

    def get_logs(self) -> List[dict]:
        with self._lock:
            return list(self._buffer)


class EmotionAnalysisHook:
    _KEYWORDS: Dict[str, List[str]] = {
        "happy": ["happy", "glad", "great", "awesome", "wonderful", "love", "excellent", "thanks", "thank"],
        "sad": ["sad", "unhappy", "depressed", "sorry", "miss", "lost", "cry", "unfortunate"],
        "angry": ["angry", "mad", "furious", "hate", "annoyed", "frustrated", "irritated", "outraged"],
    }

    def _handler(self, event_data: dict) -> Optional[dict]:
        text = str(event_data.get("input", "")).lower()
        emotion = "neutral"
        for emo, keywords in self._KEYWORDS.items():
            if any(kw in text for kw in keywords):
                emotion = emo
                break
        event_data["emotion"] = emotion
        return event_data

    def create_registration(self) -> HookRegistration:
        return HookRegistration(
            hook_id="emotion_analysis",
            point=HookPoint.BEFORE_PROCESS,
            handler=self._handler,
            priority=30,
            description="Emotion analysis hook",
        )


class UsageStatsHook:
    def __init__(self) -> None:
        self._stats: Dict[str, Dict] = {}
        self._start_times: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _before_handler(self, event_data: dict) -> Optional[dict]:
        tool_id = event_data.get("tool_id", "unknown")
        call_key = uuid.uuid4().hex
        with self._lock:
            self._start_times[call_key] = (time.monotonic(), tool_id)
        event_data["_usage_call_key"] = call_key
        return event_data

    def _after_handler(self, event_data: dict) -> Optional[dict]:
        call_key = event_data.get("_usage_call_key", "")
        with self._lock:
            entry = self._start_times.pop(call_key, None)
        if entry is not None:
            start_time, tool_id = entry
            duration = time.monotonic() - start_time
            with self._lock:
                if tool_id not in self._stats:
                    self._stats[tool_id] = {"tool_id": tool_id, "call_count": 0, "total_duration": 0.0, "avg_duration": 0.0}
                s = self._stats[tool_id]
                s["call_count"] += 1
                s["total_duration"] += duration
                s["avg_duration"] = s["total_duration"] / s["call_count"]
        return event_data

    def create_registrations(self) -> List[HookRegistration]:
        return [
            HookRegistration(
                hook_id="usage_stats_before",
                point=HookPoint.BEFORE_TOOL_EXECUTE,
                handler=self._before_handler,
                priority=40,
                description="Usage stats before hook",
            ),
            HookRegistration(
                hook_id="usage_stats_after",
                point=HookPoint.AFTER_TOOL_EXECUTE,
                handler=self._after_handler,
                priority=60,
                description="Usage stats after hook",
            ),
        ]

    def get_stats(self) -> Dict[str, Dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._stats.items()}


_CODE_PATTERN = re.compile(r"```(\w*)\s*[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_PATTERN = re.compile(r"`[^`]+`")
_LANG_HINTS = {
    "python": "python", "py": "python",
    "javascript": "javascript", "js": "javascript",
    "typescript": "typescript", "ts": "typescript",
    "java": "java", "c": "c", "cpp": "cpp", "css": "css",
    "html": "html", "sql": "sql", "bash": "bash", "sh": "bash",
    "go": "go", "rust": "rust", "ruby": "ruby", "php": "php",
}


class CodeFormattingHook:
    def _handler(self, event_data: dict) -> Optional[dict]:
        result = str(event_data.get("result", ""))
        if _CODE_PATTERN.search(result) or _INLINE_CODE_PATTERN.search(result):
            event_data["has_code"] = True
            lang_match = _CODE_PATTERN.search(result)
            if lang_match:
                raw = lang_match.group(1).lower()
                event_data["language_hint"] = _LANG_HINTS.get(raw, raw if raw else "unknown")
            else:
                event_data["language_hint"] = "unknown"
        return event_data

    def create_registration(self) -> HookRegistration:
        return HookRegistration(
            hook_id="code_formatting",
            point=HookPoint.AFTER_TOOL_EXECUTE,
            handler=self._handler,
            priority=70,
            description="Code formatting detection hook",
        )


class PluginHookBridge:
    def __init__(self, registry: HookRegistry) -> None:
        self._registry = registry
        self._plugins: Dict[str, List[str]] = {}
        self._lock = threading.Lock()

    def load_plugin(self, plugin: dict) -> bool:
        plugin_name = plugin.get("name", "")
        if not plugin_name:
            return False
        with self._lock:
            if plugin_name in self._plugins:
                return False
            hook_ids: List[str] = []
            for idx, hook_spec in enumerate(plugin.get("hooks", [])):
                hook_id = f"plugin_{plugin_name}_{idx}"
                reg = HookRegistration(
                    hook_id=hook_id,
                    point=hook_spec["point"],
                    handler=hook_spec["handler"],
                    priority=hook_spec.get("priority", 50),
                    description=hook_spec.get("description", f"Plugin {plugin_name} hook {idx}"),
                )
                if not self._registry.register(reg):
                    continue
                hook_ids.append(hook_id)
            self._plugins[plugin_name] = hook_ids
            return True

    def unload_plugin(self, plugin_name: str) -> bool:
        with self._lock:
            hook_ids = self._plugins.pop(plugin_name, None)
            if hook_ids is None:
                return False
            for hid in hook_ids:
                self._registry.unregister(hid)
            return True

    def list_plugins(self) -> list:
        with self._lock:
            return list(self._plugins.keys())


class HookOrchestrator:
    def __init__(self) -> None:
        self.registry = HookRegistry()
        self.event_bus = EventBus()
        self._error_log: list[dict] = []

    def fire(self, point: str, data: dict) -> dict:
        data["_point"] = point
        hooks = self.registry.get_hooks(point)
        for hook in hooks:
            try:
                result = hook.handler(data)
                if result is not None and isinstance(result, dict):
                    data.update(result)
            except Exception as e:
                self._error_log.append({
                    "hook_id": hook.hook_id,
                    "point": point,
                    "error": str(e),
                    "timestamp": time.time(),
                })
        event_result = self.event_bus.publish(point, data)
        if event_result.get("errors"):
            for err in event_result["errors"]:
                self._error_log.append({
                    "source": "event_bus",
                    "point": point,
                    "error": err,
                    "timestamp": time.time(),
                })
        data.pop("_point", None)
        return data

    def get_errors(self, limit: int = 50) -> list[dict]:
        return self._error_log[-limit:]
