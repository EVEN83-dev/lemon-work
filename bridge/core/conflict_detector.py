# -*- coding: utf-8 -*-
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class LockState(Enum):
    FREE = "free"
    LOCKED = "locked"


class ConflictType(Enum):
    READ_READ = "read_read"
    READ_WRITE = "read_write"
    WRITE_WRITE = "write_write"
    CONCLUSION_MISMATCH = "conclusion_mismatch"


@dataclass
class FileLock:
    file_path: str
    owner_agent: str = ""
    lock_type: str = "write"
    locked_at: float = 0.0
    timeout_seconds: float = 60.0
    queue: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        if self.locked_at <= 0:
            return True
        return (time.time() - self.locked_at) > self.timeout_seconds

    @property
    def state(self) -> str:
        if self.owner_agent and not self.is_expired:
            return LockState.LOCKED.value
        return LockState.FREE.value


@dataclass
class ConflictRecord:
    conflict_id: str
    conflict_type: str
    agents: List[str]
    file_path: str = ""
    details: str = ""
    resolution: str = ""
    resolved_by: str = ""
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "conflict_type": self.conflict_type,
            "agents": self.agents,
            "file_path": self.file_path,
            "details": self.details,
            "resolution": self.resolution,
            "resolved_by": self.resolved_by,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


class ConflictDetector:
    def __init__(self, bus=None):
        self._file_locks: Dict[str, FileLock] = {}
        self._active_access: Dict[str, Dict[str, str]] = {}
        self._conflicts: List[ConflictRecord] = {}
        self._lock = threading.Lock()
        self._bus = bus
        self._arbiter_callback: Optional[Callable] = None
        self._callbacks: Dict[str, List[Callable]] = {}
        self._conflicts = []

    def acquire_lock(self, agent_id: str, file_path: str, lock_type: str = "write",
                      timeout: float = 60.0) -> Dict[str, Any]:
        with self._lock:
            fl = self._file_locks.get(file_path)
            if fl and not fl.is_expired and fl.owner_agent != agent_id:
                if lock_type == "read" and fl.lock_type == "read":
                    pass
                else:
                    wait_entry = {
                        "agent_id": agent_id,
                        "lock_type": lock_type,
                        "requested_at": time.time(),
                    }
                    fl.queue.append(wait_entry)
                    return {
                        "acquired": False,
                        "reason": f"File locked by {fl.owner_agent} ({fl.lock_type})",
                        "queue_position": len(fl.queue),
                    }
            fl = FileLock(
                file_path=file_path,
                owner_agent=agent_id,
                lock_type=lock_type,
                locked_at=time.time(),
                timeout_seconds=timeout,
            )
            self._file_locks[file_path] = fl
            if file_path not in self._active_access:
                self._active_access[file_path] = {}
            self._active_access[file_path][agent_id] = lock_type
        self._emit("lock_acquired", {
            "agent_id": agent_id, "file_path": file_path, "lock_type": lock_type,
        })
        return {"acquired": True, "reason": "Lock acquired"}

    def release_lock(self, agent_id: str, file_path: str) -> bool:
        with self._lock:
            fl = self._file_locks.get(file_path)
            if not fl or fl.owner_agent != agent_id:
                return False
            if file_path in self._active_access:
                self._active_access[file_path].pop(agent_id, None)
                if not self._active_access[file_path]:
                    del self._active_access[file_path]
            if fl.queue:
                next_entry = fl.queue.pop(0)
                fl.owner_agent = next_entry["agent_id"]
                fl.lock_type = next_entry["lock_type"]
                fl.locked_at = time.time()
                self._emit("lock_transferred", {
                    "file_path": file_path,
                    "new_owner": fl.owner_agent,
                    "lock_type": fl.lock_type,
                })
            else:
                del self._file_locks[file_path]
        self._emit("lock_released", {
            "agent_id": agent_id, "file_path": file_path,
        })
        return True

    def check_conflict(self, agent_id: str, file_path: str, operation: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            accessors = self._active_access.get(file_path, {})
            if len(accessors) <= 1:
                return None
            other_agents = {aid: op for aid, op in accessors.items() if aid != agent_id}
            if not other_agents:
                return None
            for other_id, other_op in other_agents.items():
                if operation == "write" or other_op == "write":
                    conflict_type = ConflictType.WRITE_WRITE.value if operation == "write" and other_op == "write" else ConflictType.READ_WRITE.value
                    return {
                        "conflict": True,
                        "conflict_type": conflict_type,
                        "file_path": file_path,
                        "agents": [agent_id, other_id],
                        "operations": {agent_id: operation, other_id: other_op},
                    }
        return None

    def detect_conclusion_mismatch(self, conclusions: Dict[str, str], task_id: str = "") -> Optional[ConflictRecord]:
        if len(conclusions) < 2:
            return None
        values = list(conclusions.values())
        if len(set(values)) == 1:
            return None
        agents = list(conclusions.keys())
        import uuid
        record = ConflictRecord(
            conflict_id="conflict_" + uuid.uuid4().hex[:8],
            conflict_type=ConflictType.CONCLUSION_MISMATCH.value,
            agents=agents,
            details=f"Agents disagree: {conclusions}",
        )
        with self._lock:
            self._conflicts.append(record)
        self._emit("conflict_detected", record.to_dict())
        return record

    def arbitrate(self, conflict_id: str, arbiter_role: str = "reviewer") -> Optional[Dict[str, Any]]:
        record = None
        with self._lock:
            for c in self._conflicts:
                if c.conflict_id == conflict_id and not c.resolved_at:
                    record = c
                    break
        if not record:
            return None
        if record.conflict_type == ConflictType.CONCLUSION_MISMATCH.value and self._arbiter_callback:
            try:
                decision = self._arbiter_callback(record.agents, record.details, arbiter_role)
                record.resolution = decision.get("resolution", "arbiter_decided")
                record.resolved_by = arbiter_role
                record.resolved_at = time.time()
                self._emit("conflict_resolved", record.to_dict())
                self._broadcast_arbitration(record)
                return record.to_dict()
            except Exception as e:
                logger.error("[ConflictDetector] Arbitration error: %s", e)
        record.resolution = "queued_sequential"
        record.resolved_by = "auto"
        record.resolved_at = time.time()
        self._emit("conflict_resolved", record.to_dict())
        return record.to_dict()

    def set_arbiter(self, callback: Callable) -> None:
        self._arbiter_callback = callback

    def get_lock_status(self, file_path: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            fl = self._file_locks.get(file_path)
            if not fl:
                return {"file_path": file_path, "state": LockState.FREE.value}
            return {
                "file_path": file_path,
                "state": fl.state,
                "owner": fl.owner_agent,
                "lock_type": fl.lock_type,
                "queue_length": len(fl.queue),
                "locked_at": fl.locked_at,
                "is_expired": fl.is_expired,
            }

    def get_all_locks(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {fp: self.get_lock_status(fp) for fp in self._file_locks}

    def get_conflicts(self, unresolved_only: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            conflicts = self._conflicts
            if unresolved_only:
                conflicts = [c for c in conflicts if not c.resolved_at]
            return [c.to_dict() for c in conflicts]

    def cleanup_expired(self) -> int:
        cleaned = 0
        with self._lock:
            for fp in list(self._file_locks.keys()):
                fl = self._file_locks[fp]
                if fl.is_expired:
                    if fp in self._active_access:
                        self._active_access[fp].pop(fl.owner_agent, None)
                    if fl.queue:
                        next_entry = fl.queue.pop(0)
                        fl.owner_agent = next_entry["agent_id"]
                        fl.lock_type = next_entry["lock_type"]
                        fl.locked_at = time.time()
                    else:
                        del self._file_locks[fp]
                    cleaned += 1
        return cleaned

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _broadcast_arbitration(self, record: ConflictRecord) -> None:
        if not self._bus:
            return
        try:
            from bridge.services.agent_bus import AgentCommMessage, get_agent_comm_bus
            bus = self._bus or get_agent_comm_bus()
            bus.broadcast(AgentCommMessage(
                sender_id="conflict_detector",
                message_type="arbitration_result",
                payload=record.to_dict(),
                priority=2,
            ))
        except Exception:
            pass

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass


_global_detector: Optional[ConflictDetector] = None
_det_lock = threading.Lock()


def get_conflict_detector() -> ConflictDetector:
    global _global_detector
    if _global_detector is None:
        with _det_lock:
            if _global_detector is None:
                _global_detector = ConflictDetector()
    return _global_detector
