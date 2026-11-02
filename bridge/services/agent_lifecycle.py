# -*- coding: utf-8 -*-
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class AgentState(Enum):
    CREATING = "creating"
    IDLE = "idle"
    WORKING = "working"
    WAITING_INPUT = "waiting_input"
    PAUSED = "paused"
    TERMINATED = "terminated"


_VALID_TRANSITIONS: Dict[str, Set[str]] = {
    AgentState.CREATING.value: {AgentState.IDLE.value, AgentState.TERMINATED.value},
    AgentState.IDLE.value: {AgentState.WORKING.value, AgentState.WAITING_INPUT.value, AgentState.PAUSED.value, AgentState.TERMINATED.value},
    AgentState.WORKING.value: {AgentState.IDLE.value, AgentState.WAITING_INPUT.value, AgentState.PAUSED.value, AgentState.TERMINATED.value},
    AgentState.WAITING_INPUT.value: {AgentState.WORKING.value, AgentState.IDLE.value, AgentState.PAUSED.value, AgentState.TERMINATED.value},
    AgentState.PAUSED.value: {AgentState.WORKING.value, AgentState.IDLE.value, AgentState.TERMINATED.value},
    AgentState.TERMINATED.value: set(),
}


@dataclass
class AgentContext:
    agent_id: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: Dict[str, Any] = field(default_factory=dict)
    custom_data: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content, "timestamp": time.time()})
        self.last_updated = time.time()
        if len(self.messages) > 100:
            self.messages = self.messages[-100:]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "message_count": len(self.messages),
            "tool_results": len(self.tool_results),
            "custom_data_keys": list(self.custom_data.keys()),
            "created_at": self.created_at,
            "last_updated": self.last_updated,
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "messages": list(self.messages),
            "tool_results": dict(self.tool_results),
            "custom_data": dict(self.custom_data),
            "created_at": self.created_at,
            "last_updated": self.last_updated,
        }

    @staticmethod
    def from_snapshot(data: Dict[str, Any]) -> "AgentContext":
        ctx = AgentContext(
            agent_id=data.get("agent_id", ""),
            messages=data.get("messages", []),
            tool_results=data.get("tool_results", {}),
            custom_data=data.get("custom_data", {}),
            created_at=data.get("created_at", time.time()),
            last_updated=data.get("last_updated", time.time()),
        )
        return ctx


@dataclass
class AgentRecord:
    agent_id: str
    name: str = ""
    role_id: str = ""
    state: str = AgentState.CREATING.value
    context: Optional[AgentContext] = None
    message_queue: List[Dict[str, Any]] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    terminated_at: Optional[float] = None
    last_heartbeat: float = field(default_factory=time.time)
    restart_count: int = 0
    max_restarts: int = 3
    crash_history: List[Dict[str, Any]] = field(default_factory=list)

    def transition_to(self, new_state: str) -> bool:
        allowed = _VALID_TRANSITIONS.get(self.state, set())
        if new_state in allowed:
            old_state = self.state
            self.state = new_state
            if new_state == AgentState.IDLE.value and self.started_at is None:
                self.started_at = time.time()
            if new_state == AgentState.TERMINATED.value:
                self.terminated_at = time.time()
            return True
        logger.warning("[AgentLifecycle] Invalid transition: %s -> %s for %s",
                        self.state, new_state, self.agent_id)
        return False


_HEARTBEAT_INTERVAL = 5.0
_HEARTBEAT_TIMEOUT = 30.0
_CONTEXT_SAVE_DIR = os.path.join(os.path.expanduser("~"), ".lemoncode", "data", "agent_contexts")


class AgentLifecycleManager:
    def __init__(self, bus=None, heartbeat_interval: float = _HEARTBEAT_INTERVAL,
                 heartbeat_timeout: float = _HEARTBEAT_TIMEOUT):
        self._agents: Dict[str, AgentRecord] = {}
        self._lock = threading.RLock()
        self._callbacks: Dict[str, List[Callable]] = {}
        self._bus = bus
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._restart_callback: Optional[Callable] = None

    def create_agent(self, agent_id: str, name: str = "", role_id: str = "",
                      tools: Optional[List[str]] = None) -> str:
        if not agent_id:
            agent_id = "agent_" + uuid.uuid4().hex[:8]
        with self._lock:
            if agent_id in self._agents:
                return agent_id
            record = AgentRecord(
                agent_id=agent_id,
                name=name or agent_id,
                role_id=role_id,
                tools=tools or [],
                context=AgentContext(agent_id=agent_id),
            )
            self._agents[agent_id] = record
        self._emit("on_created", {"agent_id": agent_id, "name": name, "role_id": role_id})
        self._save_context(agent_id)
        logger.info("[AgentLifecycle] Created agent %s (%s, role=%s)", agent_id, name, role_id)
        return agent_id

    def terminate_agent(self, agent_id: str, reason: str = "manual") -> bool:
        with self._lock:
            record = self._agents.get(agent_id)
            if not record:
                return False
            record.transition_to(AgentState.TERMINATED.value)
        self._emit("on_terminated", {
            "agent_id": agent_id, "reason": reason,
            "restart_count": record.restart_count,
        })
        self._notify_state_change(agent_id, AgentState.TERMINATED.value, record)
        logger.info("[AgentLifecycle] Terminated agent %s (%s)", agent_id, reason)
        return True

    def set_state(self, agent_id: str, new_state: str) -> bool:
        with self._lock:
            record = self._agents.get(agent_id)
            if not record:
                return False
            old_state = record.state
            if not record.transition_to(new_state):
                return False
            record.last_heartbeat = time.time()
        self._emit("on_state_changed", {
            "agent_id": agent_id,
            "old_state": old_state,
            "new_state": new_state,
        })
        self._notify_state_change(agent_id, new_state, record)
        return True

    def heartbeat(self, agent_id: str, state: Optional[str] = None,
                   current_task: str = "", metadata: Optional[Dict] = None) -> bool:
        with self._lock:
            record = self._agents.get(agent_id)
            if not record:
                return False
            record.last_heartbeat = time.time()
            if state and record.state != state:
                old_state = record.state
                if record.transition_to(state):
                    self._emit("on_state_changed", {
                        "agent_id": agent_id, "old_state": old_state, "new_state": state,
                    })
            if metadata and record.context:
                record.context.custom_data.update(metadata)
        return True

    def get_state(self, agent_id: str) -> Optional[str]:
        with self._lock:
            record = self._agents.get(agent_id)
            return record.state if record else None

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._agents.get(agent_id)
            if not record:
                return None
            return {
                "agent_id": record.agent_id,
                "name": record.name,
                "role_id": record.role_id,
                "state": record.state,
                "tools": record.tools,
                "created_at": record.created_at,
                "started_at": record.started_at,
                "last_heartbeat": record.last_heartbeat,
                "restart_count": record.restart_count,
                "context": record.context.to_dict() if record.context else None,
            }

    def get_all_agents(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {aid: self.get_agent(aid) for aid in self._agents if self.get_agent(aid)}

    def get_context(self, agent_id: str) -> Optional[AgentContext]:
        with self._lock:
            record = self._agents.get(agent_id)
            return record.context if record else None

    def add_context_message(self, agent_id: str, role: str, content: str) -> bool:
        with self._lock:
            record = self._agents.get(agent_id)
            if not record or not record.context:
                return False
            record.context.add_message(role, content)
        return True

    def save_all_contexts(self) -> int:
        count = 0
        with self._lock:
            for agent_id in self._agents:
                if self._save_context(agent_id):
                    count += 1
        return count

    def restore_context(self, agent_id: str) -> bool:
        ctx_dir = os.path.join(_CONTEXT_SAVE_DIR, agent_id)
        snapshot_path = os.path.join(ctx_dir, "snapshot.json")
        if not os.path.exists(snapshot_path):
            return False
        try:
            with open(snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ctx = AgentContext.from_snapshot(data)
            with self._lock:
                record = self._agents.get(agent_id)
                if record:
                    record.context = ctx
                    return True
            return False
        except Exception as e:
            logger.error("[AgentLifecycle] Restore context error for %s: %s", agent_id, e)
            return False

    def on_restart(self, callback: Callable[[str, Dict[str, Any]], bool]) -> None:
        self._restart_callback = callback

    def on_event(self, event_name: str, callback: Callable) -> None:
        if event_name not in self._callbacks:
            self._callbacks[event_name] = []
        self._callbacks[event_name].append(callback)

    def start(self) -> None:
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("[AgentLifecycle] Monitor started (interval=%.1fs, timeout=%.1fs)",
                     self._heartbeat_interval, self._heartbeat_timeout)

    def stop(self) -> None:
        self._running = False
        self.save_all_contexts()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        logger.info("[AgentLifecycle] Monitor stopped")

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._agents)
            by_state: Dict[str, int] = {}
            for record in self._agents.values():
                by_state[record.state] = by_state.get(record.state, 0) + 1
            total_restarts = sum(r.restart_count for r in self._agents.values())
        return {
            "total_agents": total,
            "by_state": by_state,
            "total_restarts": total_restarts,
        }

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._check_heartbeats()
            except Exception as e:
                logger.error("[AgentLifecycle] Monitor error: %s", e)
            time.sleep(self._heartbeat_interval)

    def _check_heartbeats(self) -> None:
        now = time.time()
        with self._lock:
            for agent_id, record in self._agents.items():
                if record.state == AgentState.TERMINATED.value:
                    continue
                elapsed = now - record.last_heartbeat
                if elapsed > self._heartbeat_timeout:
                    logger.warning("[AgentLifecycle] Agent %s heartbeat timeout (%.1fs)", agent_id, elapsed)
                    self._handle_crash(agent_id, record)

    def _handle_crash(self, agent_id: str, record: AgentRecord) -> None:
        record.crash_history.append({
            "timestamp": time.time(),
            "state_at_crash": record.state,
            "restart_count": record.restart_count,
        })
        self._emit("on_crash_detected", {"agent_id": agent_id, "state": record.state})
        if record.restart_count >= record.max_restarts:
            record.transition_to(AgentState.TERMINATED.value)
            self._emit("on_terminated", {
                "agent_id": agent_id, "reason": "max_restarts_exceeded",
                "restart_count": record.restart_count,
            })
            self._notify_state_change(agent_id, AgentState.TERMINATED.value, record)
            logger.error("[AgentLifecycle] Agent %s exceeded max restarts (%d)",
                          agent_id, record.max_restarts)
            return
        self._save_context(agent_id)
        if self._restart_callback:
            try:
                success = self._restart_callback(agent_id, {
                    "restart_count": record.restart_count,
                    "state_at_crash": record.state,
                    "context_snapshot": record.context.snapshot() if record.context else {},
                })
                if success:
                    record.restart_count += 1
                    record.transition_to(AgentState.CREATING.value)
                    record.last_heartbeat = time.time()
                    self._emit("on_restarting", {
                        "agent_id": agent_id,
                        "attempt": record.restart_count,
                        "max_restarts": record.max_restarts,
                    })
                    logger.info("[AgentLifecycle] Restarting agent %s (attempt %d/%d)",
                                agent_id, record.restart_count, record.max_restarts)
            except Exception as e:
                logger.error("[AgentLifecycle] Restart callback error for %s: %s", agent_id, e)

    def _save_context(self, agent_id: str) -> bool:
        with self._lock:
            record = self._agents.get(agent_id)
            if not record or not record.context:
                return False
            ctx = record.context
        ctx_dir = os.path.join(_CONTEXT_SAVE_DIR, agent_id)
        os.makedirs(ctx_dir, exist_ok=True)
        snapshot_path = os.path.join(ctx_dir, "snapshot.json")
        try:
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(ctx.snapshot(), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("[AgentLifecycle] Save context error for %s: %s", agent_id, e)
            return False

    def _notify_state_change(self, agent_id: str, new_state: str, record: AgentRecord) -> None:
        if not self._bus:
            return
        try:
            from bridge.services.agent_bus import AgentCommMessage, get_agent_comm_bus
            bus = self._bus or get_agent_comm_bus()
            bus.broadcast(AgentCommMessage(
                sender_id="lifecycle_manager",
                message_type="agent_state_changed",
                payload={
                    "agent_id": agent_id,
                    "new_state": new_state,
                    "role_id": record.role_id,
                    "restart_count": record.restart_count,
                },
                priority=1,
            ))
        except Exception:
            pass

    def _emit(self, event_name: str, data: Any) -> None:
        for cb in self._callbacks.get(event_name, []):
            try:
                cb(data)
            except Exception:
                pass


_global_lifecycle: Optional[AgentLifecycleManager] = None
_lc_lock = threading.Lock()


def get_agent_lifecycle_manager() -> AgentLifecycleManager:
    global _global_lifecycle
    if _global_lifecycle is None:
        with _lc_lock:
            if _global_lifecycle is None:
                _global_lifecycle = AgentLifecycleManager()
    return _global_lifecycle
