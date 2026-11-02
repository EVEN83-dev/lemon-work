# -*- coding: utf-8 -*-
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class MessageType(Enum):
    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    TASK_DELEGATE = "task_delegate"
    STATUS_UPDATE = "status_update"
    ERROR_REPORT = "error_report"
    HEARTBEAT = "heartbeat"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESPONSE = "approval_response"
    CONTEXT_SYNC = "context_sync"
    CONTEXT_SHARE = "context_share"
    PLAN_REQUEST = "plan_request"
    PLAN_RESULT = "plan_result"


class MessagePriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3
    CRITICAL = 4


_ACK_TIMEOUT_DEFAULT = 30.0
_MAX_ACK_RETRIES = 3
_WAL_MODE = "PRAGMA journal_mode=WAL"


@dataclass
class AgentMessage:
    message_id: str = ""
    from_agent: str = ""
    to_agent: str = ""
    message_type: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    priority: int = 1
    correlation_id: str = ""
    ttl_seconds: float = 300.0
    context_id: str = ""
    requires_ack: bool = False
    ack_timeout: float = 0.0

    def __post_init__(self):
        if not self.message_id:
            self.message_id = "msg_" + uuid.uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = time.time()
        if not self.correlation_id:
            self.correlation_id = self.message_id
        if self.requires_ack and self.ack_timeout <= 0:
            self.ack_timeout = _ACK_TIMEOUT_DEFAULT

    def to_json(self) -> str:
        return json.dumps({
            "message_id": self.message_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "priority": self.priority,
            "correlation_id": self.correlation_id,
            "ttl_seconds": self.ttl_seconds,
            "context_id": self.context_id,
            "requires_ack": self.requires_ack,
            "ack_timeout": self.ack_timeout,
        }, ensure_ascii=False)

    @staticmethod
    def from_json(data: str) -> "AgentMessage":
        d = json.loads(data)
        return AgentMessage(
            message_id=d.get("message_id", ""),
            from_agent=d.get("from_agent", ""),
            to_agent=d.get("to_agent", ""),
            message_type=d.get("message_type", ""),
            payload=d.get("payload", {}),
            timestamp=d.get("timestamp", 0.0),
            priority=d.get("priority", 1),
            correlation_id=d.get("correlation_id", ""),
            ttl_seconds=d.get("ttl_seconds", 300.0),
            context_id=d.get("context_id", ""),
            requires_ack=d.get("requires_ack", False),
            ack_timeout=d.get("ack_timeout", 0.0),
        )

    def is_expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return (time.time() - self.timestamp) > self.ttl_seconds


class PriorityMessageQueue:
    def __init__(self, max_size: int = 10000):
        self._queues: Dict[int, List[AgentMessage]] = {}
        self._lock = threading.Lock()
        self._max_size = max_size
        self._total = 0

    def enqueue(self, message: AgentMessage) -> bool:
        with self._lock:
            if self._total >= self._max_size:
                self._evict_oldest()
            p = message.priority
            if p not in self._queues:
                self._queues[p] = []
            self._queues[p].append(message)
            self._total += 1
        return True

    def dequeue(self) -> Optional[AgentMessage]:
        with self._lock:
            for p in sorted(self._queues.keys(), reverse=True):
                if self._queues[p]:
                    msg = self._queues[p].pop(0)
                    self._total -= 1
                    return msg
        return None

    def peek(self) -> Optional[AgentMessage]:
        with self._lock:
            for p in sorted(self._queues.keys(), reverse=True):
                if self._queues[p]:
                    return self._queues[p][0]
        return None

    def size(self) -> int:
        with self._lock:
            return self._total

    def clear(self) -> None:
        with self._lock:
            self._queues.clear()
            self._total = 0

    def _evict_oldest(self) -> None:
        lowest = min(self._queues.keys()) if self._queues else None
        if lowest is not None and self._queues[lowest]:
            self._queues[lowest].pop(0)
            self._total -= 1
            if not self._queues[lowest]:
                del self._queues[lowest]


class SubscriptionManager:
    def __init__(self):
        self._type_subs: Dict[str, Dict[str, Callable[[AgentMessage], None]]] = {}
        self._agent_subs: Dict[str, Dict[str, Callable[[AgentMessage], None]]] = {}
        self._broadcast_subs: Dict[str, Callable[[AgentMessage], None]] = {}
        self._lock = threading.Lock()

    def subscribe_by_type(self, message_type: str, callback: Callable[[AgentMessage], None]) -> str:
        sub_id = "tsub_" + uuid.uuid4().hex[:8]
        with self._lock:
            if message_type not in self._type_subs:
                self._type_subs[message_type] = {}
            self._type_subs[message_type][sub_id] = callback
        return sub_id

    def subscribe_by_agent(self, agent_id: str, callback: Callable[[AgentMessage], None]) -> str:
        sub_id = "asub_" + uuid.uuid4().hex[:8]
        with self._lock:
            if agent_id not in self._agent_subs:
                self._agent_subs[agent_id] = {}
            self._agent_subs[agent_id][sub_id] = callback
        return sub_id

    def subscribe_broadcast(self, callback: Callable[[AgentMessage], None]) -> str:
        sub_id = "bsub_" + uuid.uuid4().hex[:8]
        with self._lock:
            self._broadcast_subs[sub_id] = callback
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        with self._lock:
            for store in [self._type_subs, self._agent_subs]:
                for key, subs in store.items():
                    if sub_id in subs:
                        del subs[sub_id]
                        if not subs:
                            del store[key]
                        return True
            if sub_id in self._broadcast_subs:
                del self._broadcast_subs[sub_id]
                return True
        return False

    def get_recipients(self, message: AgentMessage) -> List[Callable[[AgentMessage], None]]:
        callbacks: List[Callable[[AgentMessage], None]] = []
        with self._lock:
            for sub_id, cb in self._broadcast_subs.items():
                callbacks.append(cb)
            type_subs = self._type_subs.get(message.message_type, {})
            for sub_id, cb in type_subs.items():
                callbacks.append(cb)
            agent_subs = self._agent_subs.get(message.to_agent, {})
            for sub_id, cb in agent_subs.items():
                callbacks.append(cb)
        return callbacks


class AckTracker:
    def __init__(self, max_retries: int = _MAX_ACK_RETRIES):
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._events: Dict[str, threading.Event] = {}

    def register(self, message: AgentMessage) -> None:
        if not message.requires_ack:
            return
        with self._lock:
            self._pending[message.message_id] = {
                "message": message,
                "retry_count": 0,
                "registered_at": time.time(),
                "acked": False,
                "failed": False,
            }
            self._events[message.message_id] = threading.Event()

    def ack(self, message_id: str, success: bool = True) -> None:
        with self._lock:
            entry = self._pending.get(message_id)
            if entry:
                entry["acked"] = True
                entry["ack_success"] = success
            event = self._events.get(message_id)
        if event:
            event.set()

    def wait_for_ack(self, message_id: str, timeout: float = 0.0) -> bool:
        event = self._events.get(message_id)
        if not event:
            return False
        entry = self._pending.get(message_id)
        effective_timeout = timeout or (entry["message"].ack_timeout if entry else _ACK_TIMEOUT_DEFAULT)
        return event.wait(timeout=effective_timeout)

    def get_retry_candidates(self) -> List[AgentMessage]:
        now = time.time()
        candidates: List[AgentMessage] = []
        with self._lock:
            for mid, entry in list(self._pending.items()):
                if entry["acked"] or entry["failed"]:
                    continue
                msg = entry["message"]
                elapsed = now - entry["registered_at"]
                timeout = msg.ack_timeout or _ACK_TIMEOUT_DEFAULT
                if elapsed > timeout * (entry["retry_count"] + 1):
                    if entry["retry_count"] >= self._max_retries:
                        entry["failed"] = True
                        event = self._events.get(mid)
                        if event:
                            event.set()
                    else:
                        entry["retry_count"] += 1
                        candidates.append(msg)
        return candidates

    def cleanup(self, max_age: float = 3600.0) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            for mid in list(self._pending.keys()):
                entry = self._pending[mid]
                if entry["acked"] or entry["failed"]:
                    if now - entry["registered_at"] > max_age:
                        del self._pending[mid]
                        self._events.pop(mid, None)
                        removed += 1
        return removed

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._pending)
            acked = sum(1 for e in self._pending.values() if e["acked"])
            failed = sum(1 for e in self._pending.values() if e["failed"])
            pending = total - acked - failed
            return {"total": total, "acked": acked, "failed": failed, "pending": pending}


class AgentBus:
    def __init__(self, persist_path: str = ""):
        self._subscriptions = SubscriptionManager()
        self._priority_queue = PriorityMessageQueue()
        self._ack_tracker = AckTracker()
        self._lock = threading.Lock()
        self._agent_statuses: Dict[str, Dict[str, Any]] = {}
        self._heartbeat_timeout: float = 120.0
        self._message_counter: int = 0
        self._retry_thread: Optional[threading.Thread] = None
        self._running = False
        if not persist_path:
            data_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "data")
            os.makedirs(data_dir, exist_ok=True)
            persist_path = os.path.join(data_dir, "agent_messages.db")
        self._db_path = persist_path
        self._init_db()
        self._start_retry_thread()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        c = conn.cursor()
        c.execute(_WAL_MODE)
        c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                message_type TEXT NOT NULL,
                payload TEXT DEFAULT '{}',
                timestamp REAL NOT NULL,
                priority INTEGER DEFAULT 1,
                correlation_id TEXT DEFAULT '',
                context_id TEXT DEFAULT '',
                requires_ack INTEGER DEFAULT 0,
                ack_timeout REAL DEFAULT 0,
                acked INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_to ON messages(to_agent)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_type ON messages(message_type)")
        conn.commit()
        self._migrate_schema(conn)
        conn.close()

    def subscribe(self, agent_id: str, callback: Callable[[AgentMessage], None]) -> str:
        return self._subscriptions.subscribe_by_agent(agent_id, callback)

    def subscribe_type(self, message_type: str, callback: Callable[[AgentMessage], None]) -> str:
        return self._subscriptions.subscribe_by_type(message_type, callback)

    def subscribe_broadcast(self, callback: Callable[[AgentMessage], None]) -> str:
        return self._subscriptions.subscribe_broadcast(callback)

    def unsubscribe(self, sub_id: str) -> bool:
        return self._subscriptions.unsubscribe(sub_id)

    def publish(self, message: AgentMessage, require_ack: bool = False) -> str:
        if require_ack:
            message.requires_ack = True
        self._persist_message(message)
        self._ack_tracker.register(message)
        if message.to_agent == "*":
            self._broadcast(message)
        else:
            self._deliver(message)
        with self._lock:
            self._message_counter += 1
        return message.message_id

    def send_direct(self, message: AgentMessage) -> str:
        self._persist_message(message)
        if message.requires_ack:
            self._ack_tracker.register(message)
        self._deliver(message)
        with self._lock:
            self._message_counter += 1
        return message.message_id

    def wait_for_ack(self, message_id: str, timeout: float = 0.0) -> bool:
        return self._ack_tracker.wait_for_ack(message_id, timeout)

    def ack(self, message_id: str, success: bool = True) -> None:
        self._ack_tracker.ack(message_id, success)
        self._mark_acked(message_id)

    def report_heartbeat(self, agent_id: str, status: str = "idle",
                          current_task: str = "", metadata: Optional[Dict] = None) -> None:
        self._agent_statuses[agent_id] = {
            "status": status,
            "current_task": current_task,
            "last_heartbeat": time.time(),
            "metadata": metadata or {},
        }
        self.publish(AgentMessage(
            from_agent=agent_id,
            to_agent="*",
            message_type=MessageType.HEARTBEAT.value,
            payload={"status": status, "current_task": current_task},
            priority=MessagePriority.LOW.value,
        ))

    def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        status = self._agent_statuses.get(agent_id)
        if not status:
            return None
        last_hb = status.get("last_heartbeat", 0)
        elapsed = time.time() - last_hb
        is_alive = elapsed < self._heartbeat_timeout
        return {
            **status,
            "is_alive": is_alive,
            "seconds_since_heartbeat": round(elapsed, 1),
        }

    def get_all_statuses(self) -> Dict[str, Dict[str, Any]]:
        result = {}
        for agent_id in self._agent_statuses:
            result[agent_id] = self.get_agent_status(agent_id)
        return result

    def detect_failed_agents(self) -> List[str]:
        failed = []
        now = time.time()
        for agent_id, status in self._agent_statuses.items():
            last_hb = status.get("last_heartbeat", 0)
            if now - last_hb > self._heartbeat_timeout:
                failed.append(agent_id)
        return failed

    def query_messages(self, to_agent: str = "", message_type: str = "",
                       context_id: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self._db_path)
        c = conn.cursor()
        q = "SELECT * FROM messages WHERE 1=1"
        params: List[Any] = []
        if to_agent:
            q += " AND to_agent = ?"
            params.append(to_agent)
        if message_type:
            q += " AND message_type = ?"
            params.append(message_type)
        if context_id:
            q += " AND context_id = ?"
            params.append(context_id)
        q += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        c.execute(q, params)
        rows = c.fetchall()
        conn.close()
        results = []
        for row in rows:
            results.append({
                "message_id": row[0], "from_agent": row[1], "to_agent": row[2],
                "message_type": row[3], "payload": json.loads(row[4]) if row[4] else {},
                "timestamp": row[5], "priority": row[6], "correlation_id": row[7],
                "context_id": row[8] if len(row) > 8 else "",
                "requires_ack": bool(row[9]) if len(row) > 9 else False,
                "ack_timeout": row[10] if len(row) > 10 else 0.0,
                "acked": bool(row[11]) if len(row) > 11 else False,
                "retry_count": row[12] if len(row) > 12 else 0,
            })
        return results

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            counter = self._message_counter
        return {
            "total_published": counter,
            "ack_tracker": self._ack_tracker.stats(),
            "priority_queue_size": self._priority_queue.size(),
            "registered_agents": len(self._agent_statuses),
            "failed_agents": len(self.detect_failed_agents()),
        }

    def shutdown(self) -> None:
        self._running = False
        if self._retry_thread and self._retry_thread.is_alive():
            self._retry_thread.join(timeout=5)

    def _deliver(self, message: AgentMessage) -> None:
        recipients = self._subscriptions.get_recipients(message)
        for callback in recipients:
            try:
                callback(message)
            except Exception:
                pass

    def _broadcast(self, message: AgentMessage) -> None:
        self._deliver(message)

    def _persist_message(self, message: AgentMessage) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO messages (message_id, from_agent, to_agent,
                    message_type, payload, timestamp, priority, correlation_id,
                    context_id, requires_ack, ack_timeout, acked, retry_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message.message_id, message.from_agent, message.to_agent,
                message.message_type, json.dumps(message.payload, ensure_ascii=False),
                message.timestamp, message.priority, message.correlation_id,
                message.context_id, int(message.requires_ack), message.ack_timeout,
                0, 0, time.time(),
            ))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _mark_acked(self, message_id: str) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("UPDATE messages SET acked = 1 WHERE message_id = ?", (message_id,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _migrate_schema(self, conn) -> None:
        c = conn.cursor()
        try:
            c.execute("SELECT context_id FROM messages LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE messages ADD COLUMN context_id TEXT DEFAULT ''")
            conn.commit()
        try:
            c.execute("SELECT requires_ack FROM messages LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE messages ADD COLUMN requires_ack INTEGER DEFAULT 0")
            conn.commit()
        try:
            c.execute("SELECT ack_timeout FROM messages LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE messages ADD COLUMN ack_timeout REAL DEFAULT 0")
            conn.commit()
        try:
            c.execute("SELECT retry_count FROM messages LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE messages ADD COLUMN retry_count INTEGER DEFAULT 0")
            conn.commit()
        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_context ON messages(context_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_unacked ON messages(acked) WHERE acked = 0")
        conn.commit()

    def _start_retry_thread(self) -> None:
        self._running = True
        self._retry_thread = threading.Thread(target=self._retry_loop, daemon=True)
        self._retry_thread.start()

    def _retry_loop(self) -> None:
        while self._running:
            try:
                candidates = self._ack_tracker.get_retry_candidates()
                for msg in candidates:
                    self._deliver(msg)
                    try:
                        conn = sqlite3.connect(self._db_path)
                        c = conn.cursor()
                        c.execute("UPDATE messages SET retry_count = retry_count + 1 WHERE message_id = ?",
                                  (msg.message_id,))
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass
                self._ack_tracker.cleanup(max_age=3600.0)
            except Exception:
                pass
            time.sleep(5)


_global_bus: Optional[AgentBus] = None
_bus_lock = threading.Lock()


def get_agent_bus() -> AgentBus:
    global _global_bus
    if _global_bus is None:
        with _bus_lock:
            if _global_bus is None:
                _global_bus = AgentBus()
    return _global_bus
