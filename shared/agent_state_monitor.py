# -*- coding: utf-8 -*-
import os
import threading
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentHealth(Enum):
    ALIVE = "alive"
    SLOW = "slow"
    DEAD = "dead"


_HEALTHY_THRESHOLD = 3.0
_DEAD_THRESHOLD = 15.0
_HEARTBEAT_INTERVAL = 5.0
_MAX_RESTART_ATTEMPTS = 3
_RESTART_COOLDOWN = 30.0


@dataclass
class AgentHealthRecord:
    agent_id: str
    health: str = AgentHealth.ALIVE.value
    last_heartbeat: float = 0.0
    last_state_change: float = field(default_factory=time.time)
    restart_count: int = 0
    last_restart_at: float = 0.0
    current_task: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentStateMonitor:
    def __init__(self, bus=None, heartbeat_interval: float = _HEARTBEAT_INTERVAL,
                 healthy_threshold: float = _HEALTHY_THRESHOLD,
                 dead_threshold: float = _DEAD_THRESHOLD,
                 max_restart_attempts: int = _MAX_RESTART_ATTEMPTS,
                 snapshot_dir: str = ""):
        self._bus = bus
        self._heartbeat_interval = heartbeat_interval
        self._healthy_threshold = healthy_threshold
        self._dead_threshold = dead_threshold
        self._max_restart_attempts = max_restart_attempts
        self._records: Dict[str, AgentHealthRecord] = {}
        self._lock = threading.Lock()
        self._callbacks: Dict[str, List[Callable]] = {}
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._restart_callback: Optional[Callable] = None
        self._report_callback: Optional[Callable] = None
        self._snapshot_dir = snapshot_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "state", "snapshots")

    def register_agent(self, agent_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            if agent_id not in self._records:
                self._records[agent_id] = AgentHealthRecord(
                    agent_id=agent_id,
                    last_heartbeat=time.time(),
                    metadata=metadata or {},
                )

    def unregister_agent(self, agent_id: str) -> None:
        with self._lock:
            self._records.pop(agent_id, None)

    def update_heartbeat(self, agent_id: str, status: str = "idle",
                          current_task: str = "", metadata: Optional[Dict] = None) -> None:
        with self._lock:
            if agent_id not in self._records:
                self._records[agent_id] = AgentHealthRecord(agent_id=agent_id)
            record = self._records[agent_id]
            record.last_heartbeat = time.time()
            record.current_task = current_task
            if metadata:
                record.metadata.update(metadata)
            if record.health != AgentHealth.ALIVE.value:
                old_health = record.health
                record.health = AgentHealth.ALIVE.value
                record.last_state_change = time.time()
                self._emit("health_changed", {
                    "agent_id": agent_id,
                    "old_health": old_health,
                    "new_health": AgentHealth.ALIVE.value,
                })

    def on_restart(self, callback: Callable[[str, Dict[str, Any]], bool]) -> None:
        self._restart_callback = callback

    def on_report(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._report_callback = callback

    def on_event(self, event_name: str, callback: Callable) -> None:
        if event_name not in self._callbacks:
            self._callbacks[event_name] = []
        self._callbacks[event_name].append(callback)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("[AgentStateMonitor] Started (interval=%.1fs, healthy=%.1fs, dead=%.1fs)",
                     self._heartbeat_interval, self._healthy_threshold, self._dead_threshold)

    def stop(self) -> None:
        self._running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        logger.info("[AgentStateMonitor] Stopped")

    def get_health(self, agent_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._records.get(agent_id)
            if not record:
                return None
            elapsed = time.time() - record.last_heartbeat
            return {
                "agent_id": agent_id,
                "health": record.health,
                "elapsed_since_heartbeat": round(elapsed, 1),
                "current_task": record.current_task,
                "restart_count": record.restart_count,
                "metadata": record.metadata,
            }

    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        result = {}
        with self._lock:
            for agent_id in self._records:
                record = self._records[agent_id]
                elapsed = time.time() - record.last_heartbeat
                result[agent_id] = {
                    "agent_id": agent_id,
                    "health": record.health,
                    "elapsed_since_heartbeat": round(elapsed, 1),
                    "current_task": record.current_task,
                    "restart_count": record.restart_count,
                }
        return result

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._records)
            alive = sum(1 for r in self._records.values() if r.health == AgentHealth.ALIVE.value)
            slow = sum(1 for r in self._records.values() if r.health == AgentHealth.SLOW.value)
            dead = sum(1 for r in self._records.values() if r.health == AgentHealth.DEAD.value)
            total_restarts = sum(r.restart_count for r in self._records.values())
        return {
            "total_agents": total,
            "alive": alive,
            "slow": slow,
            "dead": dead,
            "total_restarts": total_restarts,
        }

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._check_health()
                self._write_snapshot()
            except Exception as e:
                logger.error("[AgentStateMonitor] Health check error: %s", e)
            time.sleep(self._heartbeat_interval)

    def _check_health(self) -> None:
        now = time.time()
        actions: List[Dict[str, Any]] = []
        with self._lock:
            for agent_id, record in self._records.items():
                elapsed = now - record.last_heartbeat
                old_health = record.health
                if elapsed > self._dead_threshold:
                    new_health = AgentHealth.DEAD.value
                elif elapsed > self._healthy_threshold:
                    new_health = AgentHealth.SLOW.value
                else:
                    new_health = AgentHealth.ALIVE.value
                if new_health != old_health:
                    record.health = new_health
                    record.last_state_change = now
                    actions.append({
                        "agent_id": agent_id,
                        "old_health": old_health,
                        "new_health": new_health,
                        "record": record,
                    })
        for action in actions:
            self._emit("health_changed", action)
            if action["new_health"] == AgentHealth.DEAD.value:
                self._handle_dead_agent(action["agent_id"], action["record"])

    def _handle_dead_agent(self, agent_id: str, record: AgentHealthRecord) -> None:
        if record.restart_count >= self._max_restart_attempts:
            logger.warning("[AgentStateMonitor] Agent %s exceeded max restarts (%d), reporting to user",
                           agent_id, record.restart_count)
            self._emit("agent_unrecoverable", {
                "agent_id": agent_id,
                "restart_count": record.restart_count,
                "last_heartbeat": record.last_heartbeat,
            })
            if self._report_callback:
                try:
                    self._report_callback({
                        "agent_id": agent_id,
                        "event": "unrecoverable",
                        "restart_count": record.restart_count,
                    })
                except Exception:
                    pass
            return
        now = time.time()
        if now - record.last_restart_at < _RESTART_COOLDOWN:
            return
        if self._restart_callback:
            try:
                success = self._restart_callback(agent_id, {
                    "restart_count": record.restart_count,
                    "current_task": record.current_task,
                })
                if success:
                    with self._lock:
                        record.restart_count += 1
                        record.last_restart_at = now
                    logger.info("[AgentStateMonitor] Agent %s restart initiated (attempt %d/%d)",
                                agent_id, record.restart_count, self._max_restart_attempts)
                    self._emit("agent_restarting", {
                        "agent_id": agent_id,
                        "attempt": record.restart_count,
                        "max_attempts": self._max_restart_attempts,
                    })
            except Exception as e:
                logger.error("[AgentStateMonitor] Restart callback error for %s: %s", agent_id, e)

    def _emit(self, event_name: str, data: Any) -> None:
        for cb in self._callbacks.get(event_name, []):
            try:
                cb(data)
            except Exception:
                pass

    def _write_snapshot(self) -> None:
        try:
            os.makedirs(self._snapshot_dir, exist_ok=True)
        except Exception:
            return
        try:
            snapshot = {
                "timestamp": time.time(),
                "summary": self.get_summary(),
                "agents": self.get_all_health(),
            }
            ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(snapshot["timestamp"]))
            path = os.path.join(self._snapshot_dir, f"monitor_{ts_str}.json")
            import json
            with open(path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            snaps = sorted(
                [os.path.join(self._snapshot_dir, f2) for f2 in os.listdir(self._snapshot_dir)
                 if f2.startswith("monitor_") and f2.endswith(".json")])
            for old in snaps[:-10]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass


_global_monitor: Optional[AgentStateMonitor] = None
_monitor_lock = threading.Lock()


def get_agent_state_monitor() -> AgentStateMonitor:
    global _global_monitor
    if _global_monitor is None:
        with _monitor_lock:
            if _global_monitor is None:
                _global_monitor = AgentStateMonitor()
    return _global_monitor
