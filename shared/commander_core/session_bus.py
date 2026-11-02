# -*- coding: utf-8 -*-
"""
commander_core.session_bus — 跨会话/Agent 消息总线
===================================================
统一咩咩和混合模式的消息传递基础设施。

咩咩需要：tool_session_send / tool_session_read 跨会话通信
混合模式需要：CommandAgent.message_to_chat / WorkAgent 间通信

SessionBus 提供：
  - 会话订阅/发布
  - 点对点消息
  - 消息历史存储
"""

import json
import time
import threading
from typing import Any, Callable, Dict, List, Optional


class SessionMessage:
    """会话消息。"""

    def __init__(self, sender: str, content: str,
                 session_id: str = "", timestamp: Optional[float] = None,
                 msg_type: str = "chat", metadata: Optional[Dict] = None):
        self.sender = sender
        self.content = content
        self.session_id = session_id
        self.timestamp = timestamp or time.time()
        self.msg_type = msg_type  # chat / system / tool / error
        self.metadata = metadata or {}

    def to_dict(self) -> Dict:
        return {
            "sender": self.sender,
            "content": self.content,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "msg_type": self.msg_type,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SessionMessage":
        return cls(
            sender=data.get("sender", ""),
            content=data.get("content", ""),
            session_id=data.get("session_id", ""),
            timestamp=data.get("timestamp"),
            msg_type=data.get("msg_type", "chat"),
            metadata=data.get("metadata", {}),
        )

    def __repr__(self):
        return f"<Msg [{self.msg_type}] {self.sender}: {self.content[:50]}>"


class SessionBus:
    """会话消息总线。

    支持：
    1. 多会话隔离（每个 session_id 独立的消息历史和订阅者）
    2. 发布/订阅模式
    3. 点对点消息
    4. 可配置的历史记录上限
    """

    def __init__(self, max_history_per_session: int = 500):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._history: Dict[str, List[SessionMessage]] = {}
        self._max_history = max_history_per_session
        self._lock = threading.RLock()

    # ====================================================================
    # 订阅
    # ====================================================================

    def subscribe(self, session_id: str, callback: Callable) -> None:
        """订阅指定会话的消息。

        Args:
            session_id: 会话 ID（空字符串表示全局订阅）
            callback: 消息回调 (SessionMessage) -> None
        """
        with self._lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = []
            self._subscribers[session_id].append(callback)

    def unsubscribe(self, session_id: str, callback: Callable) -> None:
        """取消订阅。"""
        with self._lock:
            if session_id in self._subscribers:
                try:
                    self._subscribers[session_id].remove(callback)
                except ValueError:
                    pass

    # ====================================================================
    # 发布
    # ====================================================================

    def publish(self, message: SessionMessage) -> None:
        """发布消息到会话。

        Args:
            message: SessionMessage 对象
        """
        session_id = message.session_id
        with self._lock:
            # 存储历史
            if session_id not in self._history:
                self._history[session_id] = []
            self._history[session_id].append(message)
            # 裁剪历史
            if len(self._history[session_id]) > self._max_history:
                self._history[session_id] = self._history[session_id][-self._max_history:]

            # 获取订阅者（包括全局 "" 和具体 session_id）
            subs = list(self._subscribers.get(session_id, []))
            subs.extend(self._subscribers.get("", []))

        # 通知订阅者（在锁外执行）
        for cb in subs:
            try:
                cb(message)
            except Exception:
                pass

    def send(self, sender: str, content: str,
             session_id: str = "", msg_type: str = "chat",
             metadata: Optional[Dict] = None) -> SessionMessage:
        """便捷发送方法。"""
        msg = SessionMessage(
            sender=sender,
            content=content,
            session_id=session_id,
            msg_type=msg_type,
            metadata=metadata,
        )
        self.publish(msg)
        return msg

    def send_system(self, content: str, session_id: str = "") -> SessionMessage:
        """发送系统消息。"""
        return self.send("system", content, session_id, msg_type="system")

    def send_error(self, content: str, session_id: str = "") -> SessionMessage:
        """发送错误消息。"""
        return self.send("error", content, session_id, msg_type="error")

    # ====================================================================
    # 历史查询
    # ====================================================================

    def get_history(self, session_id: str = "",
                    limit: int = 50) -> List[SessionMessage]:
        """获取会话历史。"""
        with self._lock:
            history = self._history.get(session_id, [])
            return list(history[-limit:])

    def clear_history(self, session_id: str = "") -> None:
        """清空会话历史。"""
        with self._lock:
            if session_id:
                self._history.pop(session_id, None)
            else:
                self._history.clear()

    def list_sessions(self) -> List[str]:
        """列出所有活跃会话。"""
        with self._lock:
            return list(self._history.keys())

    def get_session_stats(self) -> Dict[str, Any]:
        """获取会话统计信息。"""
        with self._lock:
            return {
                "total_sessions": len(self._history),
                "total_messages": sum(len(h) for h in self._history.values()),
                "subscriber_count": sum(len(s) for s in self._subscribers.values()),
            }


def subscribe_actor_events(bus: SessionBus, actor_system):
    def _on_actor_event(from_id, msg_type, payload):
        bus.send(
            sender=from_id,
            content=json.dumps(payload) if isinstance(payload, dict) else str(payload),
            session_id="actor_system",
            msg_type="tool" if msg_type == "tool_result" else "system",
            metadata={"msg_type": msg_type, "from_actor": from_id},
        )
    if hasattr(actor_system, 'on_message'):
        actor_system.on_message("__bus__", _on_actor_event)
