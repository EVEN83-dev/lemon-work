# -*- coding: utf-8 -*-
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class ResourceLevel(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


_CPU_WARNING_PCT = 80.0
_CPU_CRITICAL_PCT = 95.0
_CPU_WARNING_DURATION = 10.0
_MEMORY_WARNING_MB = 512.0
_MEMORY_CRITICAL_MB = 1024.0
_MONITOR_INTERVAL = 5.0
_IDLE_TIMEOUT = 1800.0


@dataclass
class ResourceSnapshot:
    agent_id: str
    cpu_pct: float = 0.0
    memory_mb: float = 0.0
    level: str = ResourceLevel.NORMAL.value
    timestamp: float = field(default_factory=time.time)
    pid: Optional[int] = None
    thread_count: int = 0
    duration_at_warning: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "cpu_pct": round(self.cpu_pct, 1),
            "memory_mb": round(self.memory_mb, 1),
            "level": self.level,
            "timestamp": self.timestamp,
            "pid": self.pid,
            "thread_count": self.thread_count,
            "duration_at_warning": round(self.duration_at_warning, 1),
        }


@dataclass
class ResourceThresholds:
    cpu_warning_pct: float = _CPU_WARNING_PCT
    cpu_critical_pct: float = _CPU_CRITICAL_PCT
    cpu_warning_duration: float = _CPU_WARNING_DURATION
    memory_warning_mb: float = _MEMORY_WARNING_MB
    memory_critical_mb: float = _MEMORY_CRITICAL_MB
    monitor_interval: float = _MONITOR_INTERVAL
    idle_timeout: float = _IDLE_TIMEOUT


class AgentResourceMonitor:
    def __init__(self, thresholds: Optional[ResourceThresholds] = None):
        self._thresholds = thresholds or ResourceThresholds()
        self._snapshots: Dict[str, ResourceSnapshot] = {}
        self._warning_since: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._callbacks: Dict[str, List[Callable]] = {}
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._pid_map: Dict[str, int] = {}
        self._action_callback: Optional[Callable] = None

    def register_agent(self, agent_id: str, pid: Optional[int] = None) -> None:
        with self._lock:
            if agent_id not in self._snapshots:
                self._snapshots[agent_id] = ResourceSnapshot(agent_id=agent_id, pid=pid)
            if pid:
                self._pid_map[agent_id] = pid

    def unregister_agent(self, agent_id: str) -> None:
        with self._lock:
            self._snapshots.pop(agent_id, None)
            self._pid_map.pop(agent_id, None)
            self._warning_since.pop(agent_id, None)

    def update_pid(self, agent_id: str, pid: int) -> None:
        with self._lock:
            self._pid_map[agent_id] = pid
            if agent_id in self._snapshots:
                self._snapshots[agent_id].pid = pid

    def on_action(self, callback: Callable[[str, str, Dict[str, Any]], None]) -> None:
        self._action_callback = callback

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
        logger.info("[AgentResourceMonitor] Started (interval=%.1fs)", self._thresholds.monitor_interval)

    def stop(self) -> None:
        self._running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
        logger.info("[AgentResourceMonitor] Stopped")

    def get_snapshot(self, agent_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            snap = self._snapshots.get(agent_id)
            return snap.to_dict() if snap else None

    def get_all_snapshots(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {aid: s.to_dict() for aid, s in self._snapshots.items()}

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._snapshots)
            warning = sum(1 for s in self._snapshots.values() if s.level == ResourceLevel.WARNING.value)
            critical = sum(1 for s in self._snapshots.values() if s.level == ResourceLevel.CRITICAL.value)
            total_cpu = sum(s.cpu_pct for s in self._snapshots.values())
            total_mem = sum(s.memory_mb for s in self._snapshots.values())
        return {
            "total_agents": total,
            "warning_count": warning,
            "critical_count": critical,
            "total_cpu_pct": round(total_cpu, 1),
            "total_memory_mb": round(total_mem, 1),
            "psutil_available": PSUTIL_AVAILABLE,
        }

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._collect_snapshots()
                self._check_thresholds()
            except Exception as e:
                logger.error("[AgentResourceMonitor] Monitor error: %s", e)
            time.sleep(self._thresholds.monitor_interval)

    def _collect_snapshots(self) -> None:
        if not PSUTIL_AVAILABLE:
            return
        with self._lock:
            agents = dict(self._pid_map)
        for agent_id, pid in agents.items():
            try:
                proc = psutil.Process(pid)
                cpu = proc.cpu_percent(interval=0.1)
                mem_info = proc.memory_info()
                mem_mb = mem_info.rss / (1024 * 1024)
                threads = proc.num_threads()
                with self._lock:
                    if agent_id in self._snapshots:
                        snap = self._snapshots[agent_id]
                        snap.cpu_pct = cpu
                        snap.memory_mb = mem_mb
                        snap.thread_count = threads
                        snap.timestamp = time.time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                with self._lock:
                    self._pid_map.pop(agent_id, None)

    def _check_thresholds(self) -> None:
        now = time.time()
        with self._lock:
            for agent_id, snap in self._snapshots.items():
                old_level = snap.level
                if snap.memory_mb >= self._thresholds.memory_critical_mb:
                    snap.level = ResourceLevel.CRITICAL.value
                elif snap.cpu_pct >= self._thresholds.cpu_critical_pct:
                    snap.level = ResourceLevel.CRITICAL.value
                elif snap.memory_mb >= self._thresholds.memory_warning_mb:
                    snap.level = ResourceLevel.WARNING.value
                elif snap.cpu_pct >= self._thresholds.cpu_warning_pct:
                    if agent_id not in self._warning_since:
                        self._warning_since[agent_id] = now
                    duration = now - self._warning_since[agent_id]
                    snap.duration_at_warning = duration
                    if duration >= self._thresholds.cpu_warning_duration:
                        snap.level = ResourceLevel.WARNING.value
                else:
                    snap.level = ResourceLevel.NORMAL.value
                    self._warning_since.pop(agent_id, None)
                    snap.duration_at_warning = 0.0
                if snap.level != old_level:
                    self._handle_level_change(agent_id, snap, old_level)

    def _handle_level_change(self, agent_id: str, snap: ResourceSnapshot, old_level: str) -> None:
        logger.info("[AgentResourceMonitor] Agent %s: %s -> %s (cpu=%.1f%%, mem=%.1fMB)",
                     agent_id, old_level, snap.level, snap.cpu_pct, snap.memory_mb)
        self._emit("resource_level_changed", {
            "agent_id": agent_id,
            "old_level": old_level,
            "new_level": snap.level,
            "cpu_pct": snap.cpu_pct,
            "memory_mb": snap.memory_mb,
        })
        if snap.level == ResourceLevel.CRITICAL.value:
            self._handle_critical(agent_id, snap)

    def _handle_critical(self, agent_id: str, snap: ResourceSnapshot) -> None:
        logger.warning("[AgentResourceMonitor] Agent %s CRITICAL: cpu=%.1f%%, mem=%.1fMB - forcing termination",
                        agent_id, snap.cpu_pct, snap.memory_mb)
        self._emit("resource_critical", {
            "agent_id": agent_id,
            "cpu_pct": snap.cpu_pct,
            "memory_mb": snap.memory_mb,
            "action": "force_terminate",
        })
        if self._action_callback:
            try:
                self._action_callback(agent_id, "force_terminate", snap.to_dict())
            except Exception as e:
                logger.error("[AgentResourceMonitor] Action callback error: %s", e)
        if PSUTIL_AVAILABLE and snap.pid:
            try:
                proc = psutil.Process(snap.pid)
                proc.terminate()
                logger.info("[AgentResourceMonitor] Sent SIGTERM to pid %d", snap.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def _emit(self, event_name: str, data: Any) -> None:
        for cb in self._callbacks.get(event_name, []):
            try:
                cb(data)
            except Exception:
                pass


_global_resource_monitor: Optional[AgentResourceMonitor] = None
_rm_lock = threading.Lock()


def get_agent_resource_monitor() -> AgentResourceMonitor:
    global _global_resource_monitor
    if _global_resource_monitor is None:
        with _rm_lock:
            if _global_resource_monitor is None:
                _global_resource_monitor = AgentResourceMonitor()
    return _global_resource_monitor
