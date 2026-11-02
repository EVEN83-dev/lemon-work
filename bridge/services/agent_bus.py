# -*- coding: utf-8 -*-
import json
import os
import sqlite3
import threading
import time
import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class CommMode(Enum):
    DIRECT = "direct"
    BROADCAST = "broadcast"
    GROUP = "group"


class MessagePriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3
    CRITICAL = 4


@dataclass
class AgentCommMessage:
    message_id: str = ""
    sender_id: str = ""
    recipient_id: str = ""
    group_id: str = ""
    message_type: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    priority: int = 1
    correlation_id: str = ""
    comm_mode: str = CommMode.DIRECT.value
    ttl_seconds: float = 300.0
    retry_count: int = 0
    max_retries: int = 3

    def __post_init__(self):
        if not self.message_id:
            self.message_id = "cmsg_" + uuid.uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = time.time()
        if not self.correlation_id:
            self.correlation_id = self.message_id

    def is_expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return (time.time() - self.timestamp) > self.ttl_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "group_id": self.group_id,
            "message_type": self.message_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "priority": self.priority,
            "correlation_id": self.correlation_id,
            "comm_mode": self.comm_mode,
            "ttl_seconds": self.ttl_seconds,
            "retry_count": self.retry_count,
        }


@dataclass
class DeadLetterEntry:
    message: AgentCommMessage
    failure_reason: str
    failed_at: float = field(default_factory=time.time)
    retried: bool = False


class AgentCommBus:
    _DB_WAL = "PRAGMA journal_mode=WAL"

    def __init__(self, persist_path: str = ""):
        self._agent_subs: Dict[str, Dict[str, Callable]] = {}
        self._type_subs: Dict[str, Dict[str, Callable]] = {}
        self._broadcast_subs: Dict[str, Callable] = {}
        self._groups: Dict[str, Set[str]] = {}
        self._lock = threading.Lock()
        self._priority_queues: Dict[int, List[AgentCommMessage]] = {}
        self._dead_letters: List[DeadLetterEntry] = []
        self._max_dead_letters = 1000
        self._online_agents: Set[str] = set()
        self._message_counter = 0
        self._delivery_thread: Optional[threading.Thread] = None
        self._running = False
        if not persist_path:
            data_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "data")
            os.makedirs(data_dir, exist_ok=True)
            persist_path = os.path.join(data_dir, "agent_comm_messages.db")
        self._db_path = persist_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        c = conn.cursor()
        c.execute(self._DB_WAL)
        c.execute("""
            CREATE TABLE IF NOT EXISTS comm_messages (
                message_id TEXT PRIMARY KEY,
                sender_id TEXT NOT NULL,
                recipient_id TEXT DEFAULT '',
                group_id TEXT DEFAULT '',
                message_type TEXT NOT NULL,
                payload TEXT DEFAULT '{}',
                timestamp REAL NOT NULL,
                priority INTEGER DEFAULT 1,
                correlation_id TEXT DEFAULT '',
                comm_mode TEXT DEFAULT 'direct',
                session_id TEXT DEFAULT '',
                created_at REAL DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_sender ON comm_messages(sender_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_recipient ON comm_messages(recipient_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_type ON comm_messages(message_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_session ON comm_messages(session_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_correlation ON comm_messages(correlation_id)")
        conn.commit()
        self._migrate_schema(conn)
        conn.close()
        self._running = True
        self._delivery_thread = threading.Thread(target=self._delivery_loop, daemon=True)
        self._delivery_thread.start()

    def _migrate_schema(self, conn) -> None:
        c = conn.cursor()
        try:
            c.execute("SELECT session_id FROM comm_messages LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE comm_messages ADD COLUMN session_id TEXT DEFAULT ''")
            conn.commit()

    def register_agent(self, agent_id: str) -> None:
        with self._lock:
            self._online_agents.add(agent_id)

    def unregister_agent(self, agent_id: str) -> None:
        with self._lock:
            self._online_agents.discard(agent_id)
            self._agent_subs.pop(agent_id, None)

    def is_online(self, agent_id: str) -> bool:
        with self._lock:
            return agent_id in self._online_agents

    def subscribe(self, agent_id: str, callback: Callable[[AgentCommMessage], None]) -> str:
        sub_id = "asub_" + uuid.uuid4().hex[:8]
        with self._lock:
            if agent_id not in self._agent_subs:
                self._agent_subs[agent_id] = {}
            self._agent_subs[agent_id][sub_id] = callback
        return sub_id

    def subscribe_type(self, message_type: str, callback: Callable[[AgentCommMessage], None]) -> str:
        sub_id = "tsub_" + uuid.uuid4().hex[:8]
        with self._lock:
            if message_type not in self._type_subs:
                self._type_subs[message_type] = {}
            self._type_subs[message_type][sub_id] = callback
        return sub_id

    def subscribe_broadcast(self, callback: Callable[[AgentCommMessage], None]) -> str:
        sub_id = "bsub_" + uuid.uuid4().hex[:8]
        with self._lock:
            self._broadcast_subs[sub_id] = callback
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        with self._lock:
            for store in [self._agent_subs, self._type_subs]:
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

    def send_direct(self, message: AgentCommMessage) -> str:
        message.comm_mode = CommMode.DIRECT.value
        self._persist_message(message)
        self._enqueue(message)
        return message.message_id

    def broadcast(self, message: AgentCommMessage) -> str:
        message.comm_mode = CommMode.BROADCAST.value
        message.recipient_id = "*"
        self._persist_message(message)
        self._deliver_broadcast(message)
        return message.message_id

    def send_to_group(self, group_id: str, message: AgentCommMessage) -> str:
        message.comm_mode = CommMode.GROUP.value
        message.group_id = group_id
        self._persist_message(message)
        members = self._get_group_members(group_id)
        if not members:
            self._add_dead_letter(message, f"Group '{group_id}' has no members")
            return message.message_id
        for member_id in members:
            msg_copy = AgentCommMessage(
                message_id=message.message_id + "_" + member_id,
                sender_id=message.sender_id,
                recipient_id=member_id,
                group_id=group_id,
                message_type=message.message_type,
                payload=message.payload,
                priority=message.priority,
                correlation_id=message.correlation_id,
                comm_mode=CommMode.GROUP.value,
            )
            self._deliver_to_agent(member_id, msg_copy)
        return message.message_id

    def create_group(self, group_id: str, role_filter: str = "") -> None:
        with self._lock:
            if group_id not in self._groups:
                self._groups[group_id] = set()
            if role_filter:
                self._add_agents_by_role(group_id, role_filter)

    def add_to_group(self, group_id: str, agent_id: str) -> bool:
        with self._lock:
            if group_id not in self._groups:
                self._groups[group_id] = set()
            self._groups[group_id].add(agent_id)
            return True

    def remove_from_group(self, group_id: str, agent_id: str) -> bool:
        with self._lock:
            if group_id in self._groups:
                self._groups[group_id].discard(agent_id)
                return True
            return False

    def list_groups(self) -> Dict[str, List[str]]:
        with self._lock:
            return {gid: list(members) for gid, members in self._groups.items()}

    def query_history(self, session_id: str = "", sender_id: str = "",
                       recipient_id: str = "", message_type: str = "",
                       start_time: float = 0, end_time: float = 0,
                       limit: int = 50) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self._db_path)
        c = conn.cursor()
        q = "SELECT * FROM comm_messages WHERE 1=1"
        params: List[Any] = []
        if session_id:
            q += " AND session_id = ?"
            params.append(session_id)
        if sender_id:
            q += " AND sender_id = ?"
            params.append(sender_id)
        if recipient_id:
            q += " AND recipient_id = ?"
            params.append(recipient_id)
        if message_type:
            q += " AND message_type = ?"
            params.append(message_type)
        if start_time > 0:
            q += " AND timestamp >= ?"
            params.append(start_time)
        if end_time > 0:
            q += " AND timestamp <= ?"
            params.append(end_time)
        q += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)
        c.execute(q, params)
        rows = c.fetchall()
        conn.close()
        results = []
        for row in rows:
            results.append({
                "message_id": row[0], "sender_id": row[1], "recipient_id": row[2],
                "group_id": row[3], "message_type": row[4],
                "payload": json.loads(row[5]) if row[5] else {},
                "timestamp": row[6], "priority": row[7], "correlation_id": row[8],
                "comm_mode": row[9], "session_id": row[10] if len(row) > 10 else "",
            })
        return results

    def replay_messages(self, session_id: str, start_time: float = 0,
                         end_time: float = 0, callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        messages = self.query_history(
            session_id=session_id, start_time=start_time, end_time=end_time, limit=10000
        )
        if callback:
            for msg in messages:
                try:
                    callback(msg)
                except Exception:
                    pass
        return messages

    def get_dead_letters(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "message": dl.message.to_dict(),
                    "failure_reason": dl.failure_reason,
                    "failed_at": dl.failed_at,
                    "retried": dl.retried,
                }
                for dl in self._dead_letters[-limit:]
            ]

    def retry_dead_letter(self, message_id: str) -> bool:
        with self._lock:
            for i, dl in enumerate(self._dead_letters):
                if dl.message.message_id == message_id and not dl.retried:
                    msg = dl.message
                    msg.retry_count += 1
                    if msg.retry_count > msg.max_retries:
                        return False
                    dl.retried = True
                    self._dead_letters.pop(i)
                    self._enqueue(msg)
                    return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "online_agents": len(self._online_agents),
                "groups": len(self._groups),
                "total_published": self._message_counter,
                "dead_letter_count": len(self._dead_letters),
                "queue_size": sum(len(q) for q in self._priority_queues.values()),
            }

    def shutdown(self) -> None:
        self._running = False
        if self._delivery_thread and self._delivery_thread.is_alive():
            self._delivery_thread.join(timeout=5)

    def _enqueue(self, message: AgentCommMessage) -> None:
        with self._lock:
            p = message.priority
            if p not in self._priority_queues:
                self._priority_queues[p] = []
            self._priority_queues[p].append(message)
            self._message_counter += 1

    def _dequeue(self) -> Optional[AgentCommMessage]:
        with self._lock:
            for p in sorted(self._priority_queues.keys(), reverse=True):
                if self._priority_queues[p]:
                    msg = self._priority_queues[p].pop(0)
                    return msg
        return None

    def _delivery_loop(self) -> None:
        while self._running:
            msg = self._dequeue()
            if msg:
                self._route_message(msg)
            else:
                time.sleep(0.01)

    def _route_message(self, message: AgentCommMessage) -> None:
        if message.comm_mode == CommMode.BROADCAST.value:
            self._deliver_broadcast(message)
        elif message.comm_mode == CommMode.GROUP.value:
            members = self._get_group_members(message.group_id)
            for mid in members:
                self._deliver_to_agent(mid, message)
        else:
            if message.recipient_id and message.recipient_id != "*":
                delivered = self._deliver_to_agent(message.recipient_id, message)
                if not delivered:
                    self._add_dead_letter(message, f"Recipient '{message.recipient_id}' not online")

    def _deliver_to_agent(self, agent_id: str, message: AgentCommMessage) -> bool:
        with self._lock:
            subs = dict(self._agent_subs.get(agent_id, {}))
        delivered = False
        for sub_id, callback in subs.items():
            try:
                callback(message)
                delivered = True
            except Exception as e:
                logger.debug("[AgentCommBus] Delivery error to %s: %s", agent_id, e)
        type_subs = self._type_subs.get(message.message_type, {})
        for sub_id, callback in type_subs.items():
            try:
                callback(message)
                delivered = True
            except Exception:
                pass
        return delivered

    def _deliver_broadcast(self, message: AgentCommMessage) -> None:
        with self._lock:
            bcast_subs = dict(self._broadcast_subs)
            agent_subs = {aid: dict(subs) for aid, subs in self._agent_subs.items()}
        for sub_id, callback in bcast_subs.items():
            try:
                callback(message)
            except Exception:
                pass
        for agent_id, subs in agent_subs.items():
            for sub_id, callback in subs.items():
                try:
                    callback(message)
                except Exception:
                    pass

    def _get_group_members(self, group_id: str) -> Set[str]:
        with self._lock:
            return set(self._groups.get(group_id, set()))

    def _add_agents_by_role(self, group_id: str, role_filter: str) -> None:
        try:
            from shared.role_system import get_role_manager
            rm = get_role_manager()
            for role_id, role_def in rm.get_all_roles().items():
                if role_filter in role_id or role_filter in role_def.name:
                    self._groups[group_id].add(role_id)
        except Exception:
            pass

    def _add_dead_letter(self, message: AgentCommMessage, reason: str) -> None:
        with self._lock:
            self._dead_letters.append(DeadLetterEntry(message=message, failure_reason=reason))
            if len(self._dead_letters) > self._max_dead_letters:
                self._dead_letters = self._dead_letters[-self._max_dead_letters:]
        logger.warning("[AgentCommBus] Dead letter: %s -> %s (%s)",
                        message.sender_id, message.recipient_id, reason)

    def _persist_message(self, message: AgentCommMessage, session_id: str = "") -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO comm_messages (message_id, sender_id, recipient_id,
                    group_id, message_type, payload, timestamp, priority,
                    correlation_id, comm_mode, session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message.message_id, message.sender_id, message.recipient_id,
                message.group_id, message.message_type,
                json.dumps(message.payload, ensure_ascii=False),
                message.timestamp, message.priority, message.correlation_id,
                message.comm_mode, session_id, time.time(),
            ))
            conn.commit()
            conn.close()
        except Exception:
            pass


_global_comm_bus: Optional[AgentCommBus] = None
_comm_lock = threading.Lock()


def get_agent_comm_bus() -> AgentCommBus:
    global _global_comm_bus
    if _global_comm_bus is None:
        with _comm_lock:
            if _global_comm_bus is None:
                _global_comm_bus = AgentCommBus()
    return _global_comm_bus
