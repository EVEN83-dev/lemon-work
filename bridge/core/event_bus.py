"""
B-004: EventBus - decoupled from PyQt5.

Thread-safe publish/subscribe event system using standard library only.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from enum import Enum
from queue import Queue
from typing import Any, Callable, Dict, List, Optional


class EventType(str, Enum):
    MESSAGE_SENT = "message_sent"
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_DELTA = "message_delta"
    TOOL_BEFORE = "tool_before"
    TOOL_AFTER = "tool_after"
    TOOL_ERROR = "tool_error"
    SESSION_CREATED = "session_created"
    SESSION_SWITCHED = "session_switched"
    SESSION_CLOSED = "session_closed"
    ENGINE_STATUS_CHANGED = "engine_status_changed"
    SETTINGS_CHANGED = "settings_changed"
    CHART_DETECTED = "chart_detected"
    ERROR = "error"
    STREAM_START = "stream_start"
    STREAM_END = "stream_end"


class _EventBus:
    _instance: Optional[_EventBus] = None
    _lock = threading.Lock()

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._once_subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._queue: Queue = Queue()
        self._running = False

    @classmethod
    def instance(cls) -> _EventBus:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def subscribe(self, event_type: EventType, handler: Callable, once: bool = False) -> None:
        if once:
            self._once_subscribers[event_type.value].append(handler)
        else:
            self._subscribers[event_type.value].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable) -> None:
        key = event_type.value
        if handler in self._subscribers[key]:
            self._subscribers[key].remove(handler)
        if handler in self._once_subscribers[key]:
            self._once_subscribers[key].remove(handler)

    def publish(self, event_type: EventType, data: Any = None) -> None:
        key = event_type.value
        for handler in self._subscribers[key]:
            try:
                handler(data)
            except Exception:
                pass
        once_handlers = self._once_subscribers[key][:]
        self._once_subscribers[key].clear()
        for handler in once_handlers:
            try:
                handler(data)
            except Exception:
                pass

    def publish_sync(self, event_type: EventType, data: Any = None) -> None:
        self.publish(event_type, data)

    def clear(self) -> None:
        self._subscribers.clear()
        self._once_subscribers.clear()


def get_event_bus() -> _EventBus:
    return _EventBus.instance()
