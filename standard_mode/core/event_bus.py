# -*- coding: utf-8 -*-
"""
事件总线 — 统一事件管理架构
============================
核心能力：
- 单例模式，全局唯一事件总线
- 异步/同步两种发布模式
- 订阅/取消订阅机制
- 异常隔离：单个处理器异常不影响其他处理器

信号流向：
    用户输入 → MESSAGE_SENT → AI处理 → MESSAGE_RECEIVED → UI更新
    工具调用 → TOOL_BEFORE → 执行 → TOOL_AFTER/TOOL_ERROR → UI更新
    文件变更 → FILE_SAVED → Git状态刷新 → 快照创建
    会话切换 → SESSION_SWITCHED → 工作区加载 → UI刷新
    快照创建 → SNAPSHOT_CREATED → UI更新（显示回退按钮）
    快照回退 → SNAPSHOT_RESTORED → 文件刷新 → UI更新
    设置变更 → SETTINGS_CHANGED → 所有模块重新加载配置
    崩溃恢复 → CRASH_RECOVERED → 状态恢复 → UI提示

使用方式：
    from event_bus import EventBus, EventType

    # 订阅事件
    EventBus.instance().subscribe(EventType.MESSAGE_RECEIVED, self.on_message)

    # 发布事件（异步，不阻塞）
    EventBus.instance().publish(EventType.MESSAGE_RECEIVED, {"text": "hello"})

    # 发布事件（同步，等待所有处理器完成）
    EventBus.instance().publish_sync(EventType.TOOL_BEFORE, {"tool": "write"})
"""

import threading
import queue
from enum import Enum
from typing import Callable, Any, Dict, List, Set
from dataclasses import dataclass, field


class EventType(Enum):
    """事件类型枚举"""

    # 消息事件
    MESSAGE_SENT = "message_sent"               # 用户发送消息
    MESSAGE_RECEIVED = "message_received"       # 收到 AI 回复
    MESSAGE_DELTA = "message_delta"             # 流式增量文本

    # 工具事件
    TOOL_BEFORE = "tool_before"                 # 工具执行前
    TOOL_AFTER = "tool_after"                   # 工具执行后
    TOOL_ERROR = "tool_error"                   # 工具执行错误

    # 文件事件
    FILE_OPENED = "file_opened"                 # 文件打开
    FILE_SAVED = "file_saved"                   # 文件保存
    FILE_DELETED = "file_deleted"               # 文件删除

    # 会话事件
    SESSION_CREATED = "session_created"         # 会话创建
    SESSION_SWITCHED = "session_switched"       # 会话切换
    SESSION_CLOSED = "session_closed"           # 会话关闭

    # 工作区事件
    WORKSPACE_CHANGED = "workspace_changed"     # 工作区切换

    # 可视化事件
    CHART_DETECTED = "chart_detected"           # 检测到图表标记
    CHART_RENDERED = "chart_rendered"           # 图表渲染完成

    # 快照事件
    SNAPSHOT_CREATED = "snapshot_created"       # 快照已创建
    SNAPSHOT_RESTORED = "snapshot_restored"     # 快照已回退

    # 调试事件
    DEBUG_STARTED = "debug_started"             # 调试启动
    DEBUG_STOPPED = "debug_stopped"             # 调试停止
    BREAKPOINT_HIT = "breakpoint_hit"           # 断点命中

    # 系统事件
    OLLAMA_STATUS_CHANGED = "ollama_status_changed"   # Ollama 状态变化
    CRASH_RECOVERED = "crash_recovered"               # 崩溃恢复
    SETTINGS_CHANGED = "settings_changed"             # 设置变更
    STATUS_UPDATE = "status_update"                   # 通用状态更新


@dataclass
class Event:
    """事件对象"""
    type: EventType
    data: Any = None
    timestamp: float = field(default_factory=lambda: __import__('time').time())


class EventBus:
    """事件总线 — 单例模式

    特性：
    - 异步发布：通过后台线程处理，不阻塞发布者
    - 异常隔离：单个处理器抛异常不影响其他处理器
    - 线程安全：使用锁保护订阅列表
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 订阅者：{EventType: [(handler, once_flag), ...]}
        self._subscribers: Dict[EventType, List[tuple]] = {}
        self._sub_lock = threading.RLock()

        # 异步事件队列
        self._async_queue: queue.Queue = queue.Queue()
        self._async_thread = threading.Thread(target=self._async_worker, daemon=True)
        self._async_thread.start()

        # 统计
        self._stats: Dict[str, int] = {"published": 0, "processed": 0, "errors": 0}

    @classmethod
    def instance(cls) -> 'EventBus':
        """获取单例实例"""
        return cls()

    # ============================================================
    # 订阅 / 取消订阅
    # ============================================================

    def subscribe(self, event_type: EventType, handler: Callable, once: bool = False):
        """订阅事件

        Args:
            event_type: 事件类型
            handler: 处理函数，签名 (data: Any) -> None
            once: 是否只处理一次（处理后自动取消订阅）
        """
        with self._sub_lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append((handler, once))

    def unsubscribe(self, event_type: EventType, handler: Callable):
        """取消订阅"""
        with self._sub_lock:
            if event_type in self._subscribers:
                self._subscribers[event_type] = [
                    (h, o) for h, o in self._subscribers[event_type] if h != handler
                ]

    def clear_subscribers(self, event_type: EventType = None):
        """清除订阅者"""
        with self._sub_lock:
            if event_type:
                self._subscribers.pop(event_type, None)
            else:
                self._subscribers.clear()

    # ============================================================
    # 发布事件
    # ============================================================

    def publish(self, event_type: EventType, data: Any = None):
        """异步发布事件（不阻塞发布者）

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        self._stats["published"] += 1
        event = Event(type=event_type, data=data)
        self._async_queue.put(event)

    def publish_sync(self, event_type: EventType, data: Any = None):
        """同步发布事件（等待所有处理器完成）

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        self._stats["published"] += 1
        self._dispatch(Event(type=event_type, data=data))

    # ============================================================
    # 内部处理
    # ============================================================

    def _async_worker(self):
        """异步事件处理线程"""
        while True:
            try:
                event = self._async_queue.get()
                if event is None:
                    break
                self._dispatch(event)
                self._async_queue.task_done()
            except Exception as e:
                print(f"[EventBus] 异步处理异常: {e}", flush=True)
                self._stats["errors"] += 1

    def _dispatch(self, event: Event):
        """分发事件给所有订阅者"""
        with self._sub_lock:
            subs = list(self._subscribers.get(event.type, []))

        to_remove = []
        for handler, once in subs:
            try:
                handler(event.data)
                self._stats["processed"] += 1
                if once:
                    to_remove.append((handler, once))
            except Exception as e:
                print(f"[EventBus] 处理器异常 ({event.type.value}): {e}", flush=True)
                self._stats["errors"] += 1
                # 异常隔离：不中断其他处理器

        # 清理一次性订阅
        if to_remove:
            with self._sub_lock:
                for item in to_remove:
                    if item in self._subscribers.get(event.type, []):
                        self._subscribers[event.type].remove(item)

    # ============================================================
    # 工具方法
    # ============================================================

    def get_stats(self) -> Dict[str, int]:
        """获取事件统计"""
        return dict(self._stats)

    def get_subscriber_count(self, event_type: EventType = None) -> int:
        """获取订阅者数量"""
        with self._sub_lock:
            if event_type:
                return len(self._subscribers.get(event_type, []))
            return sum(len(v) for v in self._subscribers.values())

    def shutdown(self):
        """关闭事件总线"""
        self._async_queue.put(None)
        self._async_thread.join(timeout=5)
