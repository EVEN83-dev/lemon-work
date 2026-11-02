# -*- coding: utf-8 -*-
"""
shared/event_bus.py — v6 统一跨运行时事件总线

设计来源（三套旧总线 EventType + Qt 信号映射，双写兼容，不替换旧链路）：
  - bridge/core/event_bus.py:        14 EventType (message_*, tool_*, session_*, stream_*)
  - standard_mode/core/event_bus.py: 25 EventType (+ file_*, workspace_*, chart_*, snapshot_*, debug_*, system_*)
  - bridge/services/agent_bus.py:    自由字符串 (agent 通信, 无枚举)
  - Qt signals (~220个, 三目录):      engine/stream/agent/session 等

统一原则:
  - 事件类型采用命名空间字符串 (如 engine.stream.delta, agent.round_closed)
  - 提供 from_qt_signal 助手把既有 Qt 信号双写注入统一总线
  - 订阅异常隔离、环形缓冲落盘、降级队列、显式 success 字段
"""
import json
import os
import threading
import time
import logging
import queue
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 事件类型常量（三套旧总线 + Qt 信号的并集，命名空间化）
# ============================================================

class EventType:
    """统一事件类型字符串常量。

    映射来源:
      bridge/core/event_bus (14个) -> 加上 engine. / message. / session. 前缀
      standard_mode/core/event_bus (25个) -> 加上 file. / workspace. / debug. 前缀
      bridge/services/agent_bus -> agent.comm 自由字符串
      Qt signals -> 各自的模块前缀
    """

    # engine 引擎 (旧: ENGINE_STATUS_CHANGED, OLLAMA_STATUS_CHANGED)
    ENGINE_STATUS_CHANGED = "engine.status_changed"       # 原 ENGINE_STATUS_CHANGED
    ENGINE_STREAM_START  = "engine.stream.start"          # 旧 stream_start / stream_start signal
    ENGINE_STREAM_DELTA  = "engine.stream.delta"          # 旧 message_delta / stream_delta / token_received
    ENGINE_STREAM_END    = "engine.stream.end"            # 旧 stream_end / stream_end signal
    ENGINE_MESSAGE_COMPLETE = "engine.message_complete"    # 旧 message_complete signal
    ENGINE_ERROR         = "engine.error"                 # 旧 error / error_occurred
    ENGINE_THINKING      = "engine.thinking"              # 旧 thinking_received
    ENGINE_CHANGED       = "engine.changed"               # 旧 engine_changed / set_model signal
    MODEL_LIST_UPDATED   = "engine.model_list_updated"     # 旧 model_list_updated signal

    # message/agent 消息与工具 (旧: MESSAGE_*, TOOL_*)
    MESSAGE_SENT         = "message.sent"
    MESSAGE_RECEIVED     = "message.received"
    AGENT_TASK_STARTED   = "agent.task_started"           # 旧 task_started
    AGENT_TASK_FINISHED  = "agent.task_finished"          # 旧 task_finished
    AGENT_ROUND_CLOSED   = "agent.round_closed"           # 新: LLM 回合完成
    AGENT_DISPATCH       = "agent.dispatch"               # 旧 AGENT_DISPATCH

    # tool 工具 (旧: TOOL_BEFORE/AFTER/ERROR)
    TOOL_CALL            = "tool.call"                    # 旧 TOOL_CALL / tool_call signal
    TOOL_RESULT          = "tool.result"                  # 旧 TOOL_RESULT / tool_result signal
    TOOL_ERROR           = "tool.error"                   # 旧 tool_error

    # session 会话 (旧: SESSION_CREATED/SWITCHED/CLOSED)
    SESSION_CREATED      = "session.created"
    SESSION_SWITCHED     = "session.switched"
    SESSION_CLOSED       = "session.closed"
    WS_CLIENT_CONNECTED  = "ws.client.connected"          # 新
    WS_CLIENT_DISCONNECTED = "ws.client.disconnected"     # 新

    # file 文件 (旧: FILE_OPENED/SAVED/DELETED from sm event_bus)
    FILE_CHANGED         = "file.changed"                 # 新: QFileSystemWatcher/file_watcher 输出
    FILE_OPENED          = "file.opened"
    FILE_SAVED           = "file.saved"
    FILE_DELETED         = "file.deleted"

    # scheduler 调度 (窗口A 解耦，预留类型)
    SCHEDULER_FIRED      = "scheduler.fired"              # 预留: window A
    SCHEDULER_LOG        = "scheduler.log"                # 预留: window A run log

    # system 系统 (旧: CRASH_RECOVERED, SETTINGS_CHANGED, STATUS_UPDATE)
    SETTINGS_CHANGED     = "system.settings_changed"
    STATUS_UPDATE        = "system.status_update"
    ERROR                = "system.error"                 # 旧 ERROR

    # permission 计划
    PERMISSION_REQUESTED = "permission.requested"         # 旧 permission_request signal
    PERMISSION_RESPONDED = "permission.responded"         # 旧 permission signal

    # plan
    PLAN_PROPOSED        = "plan.proposed"                # 旧 PLAN_PROPOSED signal
    PLAN_CONFIRMED       = "plan.confirmed"               # 旧 PLAN_CONFIRMED


# ============================================================
# Event 数据模型
# ============================================================

@dataclass
class Event:
    """统一事件模型（可序列化到 JSONL）"""
    type: str
    source: str = ""                  # 发射来源标识
    payload: Any = None               # 业务数据
    ts: float = field(default_factory=time.time)
    session_id: str = ""              # 关联的 session（WS per-session 路由用）
    event_id: str = ""                # 唯一标识（可选，用于去重）

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "source": self.source,
            "payload": self.payload if isinstance(self.payload, (dict, list, str, int, float, bool, type(None))) else str(self.payload),
            "ts": self.ts,
            "session_id": self.session_id,
            "event_id": self.event_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


# ============================================================
# UnifiedEventBus — 统一事件总线（线程安全单例）
# ============================================================

class UnifiedEventBus:
    """v6 统一跨运行时事件总线。

    能力:
      - publish/subscribe（按 type 前缀通配订阅）
      - 环形缓冲持久化到 data/event_bus/recent.jsonl（封顶截断）
      - 订阅者异常隔离（一个订阅者崩不掉总线）
      - 降级队列 data/event_bus/pending/（总线故障时落盘重放）
      - bridge_from_qt_signal: 把 Qt 信号双写注入本总线
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    @classmethod
    def instance(cls) -> 'UnifiedEventBus':
        return cls()

    def __init__(self, buffer_size: int = 200, persist_dir: str = ""):
        if self._initialized:
            return
        self._initialized = True
        self._subscribers: Dict[str, List[tuple]] = defaultdict(list)  # type -> [(cb, session_id_or_None, once)]
        self._wild_subscribers: List[tuple] = []                        # 通配订阅 [(cb, prefix, session_id)]
        self._sub_lock = threading.RLock()
        self._buffer: deque = deque(maxlen=buffer_size)
        self._buffer_size = buffer_size
        self._persist_dir = persist_dir or os.path.join("data", "event_bus")
        os.makedirs(self._persist_dir, exist_ok=True)
        self._pending_dir = os.path.join(self._persist_dir, "pending")
        os.makedirs(self._pending_dir, exist_ok=True)
        self._recent_file = os.path.join(self._persist_dir, "recent.jsonl")
        self._stats = {"published": 0, "delivered": 0, "errors": 0, "dropped": 0}
        self._stats_lock = threading.Lock()
        self._qt_bridges: List[Any] = []  # 保存 Qt 信号桥接引用防止 GC

    # ----------------------------------------------------------
    # subscribe / unsubscribe
    # ----------------------------------------------------------

    def subscribe(self, event_type: str, callback: Callable[[Event], None],
                  session_id: str = "", once: bool = False) -> str:
        """订阅事件。event_type 支持精确匹配或 '*' 通配（前缀匹配）。"""
        sub_id = f"sub_{int(time.time()*1000)}_{id(callback)}"
        with self._sub_lock:
            if event_type == "*":
                self._wild_subscribers.append((callback, "", session_id))
            elif event_type.endswith(".*"):
                prefix = event_type[:-1]  # "file." 匹配 "file.changed" 等
                self._wild_subscribers.append((callback, prefix, session_id))
            else:
                self._subscribers[event_type].append((callback, session_id, once))
        return sub_id

    def unsubscribe(self, event_type: str, callback: Callable) -> bool:
        with self._sub_lock:
            if event_type == "*":
                self._wild_subscribers = [(c, p, s) for c, p, s in self._wild_subscribers if c != callback]
            elif event_type.endswith("*"):
                prefix = event_type[:-1]
                self._wild_subscribers = [(c, p, s) for c, p, s in self._wild_subscribers if c != callback or p != prefix]
            else:
                original = self._subscribers.get(event_type, [])
                self._subscribers[event_type] = [(c, s, o) for c, s, o in original if c != callback]
                return len(self._subscribers[event_type]) < len(original)
        return False

    # ----------------------------------------------------------
    # publish
    # ----------------------------------------------------------

    def publish(self, event: Event) -> dict:
        """发布事件到总线。成功返回 {"success": True}，失败返回 {"success": False, "error": ...}。"""
        try:
            # 1. 写入环形缓冲
            with self._sub_lock:
                self._buffer.append(event)
            # 2. 异步持久到 recent.jsonl（非阻塞，失败降级落盘到 pending/）
            self._persist_recent(event)
            # 3. 分发订阅者（异常隔离）
            self._dispatch(event)
            with self._stats_lock:
                self._stats["published"] += 1
            return {"success": True, "event_id": event.event_id}
        except Exception as e:
            logger.error(f"[EventBus] publish failed: {e}")
            with self._stats_lock:
                self._stats["errors"] += 1
            # 降级落盘
            self._enqueue_pending(event)
            return {"success": False, "error": str(e)}

    def _dispatch(self, event: Event):
        """事件分发给所有匹配的订阅者（异常隔离）"""
        targets = []
        with self._sub_lock:
            # 精确匹配
            targets.extend(self._subscribers.get(event.type, []))
            # 通配匹配
            for cb, prefix, sid in self._wild_subscribers:
                if event.type.startswith(prefix):
                    targets.append((cb, sid, False))

        for cb, sub_session_id, once in targets:
            # 如果订阅者有 session 过滤，只投递匹配的事件
            if sub_session_id and event.session_id and sub_session_id != event.session_id:
                continue
            try:
                cb(event)
                with self._stats_lock:
                    self._stats["delivered"] += 1
            except Exception as e:
                logger.warning(f"[EventBus] subscriber {cb.__name__ if hasattr(cb,'__name__') else cb} error: {e}")
                with self._stats_lock:
                    self._stats["errors"] += 1

    # ----------------------------------------------------------
    # 环形缓冲持久化
    # ----------------------------------------------------------

    def _persist_recent(self, event: Event):
        """落盘 recent.jsonl（失败降级到 pending/）"""
        try:
            with open(self._recent_file, 'a', encoding='utf-8') as f:
                f.write(event.to_json() + "\n")
        except Exception as e:
            logger.warning(f"[EventBus] persist recent failed, enqueue pending: {e}")
            self._enqueue_pending(event)

    def _enqueue_pending(self, event: Event):
        """降级: 事件落盘到 pending/ 队列，等待恢复后重放"""
        try:
            fname = f"pending_{int(time.time()*1000000)}.jsonl"
            fpath = os.path.join(self._pending_dir, fname)
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(event.to_json() + "\n")
        except Exception as e:
            logger.error(f"[EventBus] even pending enqueue failed: {e}")
            with self._stats_lock:
                self._stats["dropped"] += 1

    def get_recent_events(self, limit: int = 50) -> List[dict]:
        """读取最近 N 条事件（从环形缓冲）"""
        with self._sub_lock:
            recent = list(self._buffer)[-limit:]
        return [e.to_dict() for e in recent]

    def replay_pending(self, max_retry: int = 3) -> dict:
        """重放 pending 目录中的事件。返回 {"success": bool, "replayed": int, "failed": int}。"""
        replayed = 0
        failed = 0
        try:
            for fn in sorted(os.listdir(self._pending_dir)):
                if not fn.endswith('.jsonl'):
                    continue
                fpath = os.path.join(self._pending_dir, fn)
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        for line in f:
                            data = json.loads(line)
                            event = Event(**{k: data.get(k, "") for k in ["type","source","payload","ts","session_id","event_id"]})
                            self._dispatch(event)
                    os.remove(fpath)
                    replayed += 1
                except Exception as e:
                    logger.warning(f"[EventBus] replay {fn} failed: {e}")
                    failed += 1
        except Exception as e:
            return {"success": False, "replayed": replayed, "failed": failed, "error": str(e)}
        return {"success": True, "replayed": replayed, "failed": failed}

    # ----------------------------------------------------------
    # Qt 信号桥接（双写注入，保留旧链路）
    # ----------------------------------------------------------

    def bridge_from_qt_signal(self, qt_signal, event_type: str, source: str = "",
                               session_id_getter=None, payload_fn=None):
        """把既有 Qt 信号双写到统一总线。

        Args:
            qt_signal: Qt 信号对象 (如 engine.stream_delta)
            event_type: 统一 EventType 字符串
            source: 事件来源标识
            session_id_getter: 从信号参数提取 session_id 的函数 (args -> str)
            payload_fn: 从信号参数构造 payload 的函数 (args -> Any)
        """
        def _handler(*args):
            sid = session_id_getter(args) if session_id_getter else ""
            payload = payload_fn(args) if payload_fn else list(args)
            event = Event(type=event_type, source=source, payload=payload, session_id=sid)
            self.publish(event)

        qt_signal.connect(_handler)
        self._qt_bridges.append((qt_signal, _handler))
        return {"success": True}

    def get_stats(self) -> dict:
        with self._stats_lock:
            return dict(self._stats)

    def get_subscriber_count(self) -> int:
        with self._sub_lock:
            total = sum(len(v) for v in self._subscribers.values())
            total += len(self._wild_subscribers)
            return total

    def shutdown(self):
        """清理资源"""
        self._buffer.clear()
        with self._sub_lock:
            self._subscribers.clear()
            self._wild_subscribers.clear()


# ============================================================
# 全局单例工厂
# ============================================================

def get_event_bus(**kwargs) -> UnifiedEventBus:
    """获取全局 UnifiedEventBus 单例"""
    return UnifiedEventBus(**kwargs)
