# -*- coding: utf-8 -*-
import json
import os
import time
import threading
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Set

logger = logging.getLogger(__name__)

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


class AgentLifecycleState:
    CREATED = "created"
    CONFIGURED = "configured"
    STARTED = "started"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


_VALID_TRANSITIONS: Dict[str, Set[str]] = {
    AgentLifecycleState.CREATED: {AgentLifecycleState.CONFIGURED, AgentLifecycleState.TERMINATED},
    AgentLifecycleState.CONFIGURED: {AgentLifecycleState.STARTED, AgentLifecycleState.TERMINATED},
    AgentLifecycleState.STARTED: {AgentLifecycleState.RUNNING, AgentLifecycleState.FAILED, AgentLifecycleState.TERMINATED},
    AgentLifecycleState.RUNNING: {AgentLifecycleState.PAUSED, AgentLifecycleState.COMPLETED, AgentLifecycleState.FAILED, AgentLifecycleState.TERMINATED},
    AgentLifecycleState.PAUSED: {AgentLifecycleState.RUNNING, AgentLifecycleState.TERMINATED},
    AgentLifecycleState.COMPLETED: set(),
    AgentLifecycleState.FAILED: set(),
    AgentLifecycleState.TERMINATED: set(),
}


def is_valid_transition(from_state: str, to_state: str) -> bool:
    allowed = _VALID_TRANSITIONS.get(from_state, set())
    return to_state in allowed


@dataclass
class SandboxPolicy:
    allowed_paths: List[str] = field(default_factory=list)
    denied_paths: List[str] = field(default_factory=list)
    network_allowed: bool = False
    max_file_size_mb: float = 10.0
    read_only: bool = False


@dataclass
class SubAgentSpec:
    name: str
    task_description: str
    parent_worktree: str = ""
    tools_allowed: List[str] = field(default_factory=list)
    model_override: str = ""
    max_iterations: int = 10
    confirm_callback: Optional[Callable] = None
    role_id: str = ""
    max_token_budget: int = 50000
    timeout_seconds: int = 300
    sandbox: Optional[SandboxPolicy] = None
    isolated_cwd: str = ""
    memory_namespace: str = ""
    parent_cancel_event: Optional[threading.Event] = None


@dataclass
class SubAgentResult:
    subagent_id: str
    name: str
    status: str
    content: str = ""
    tool_calls_made: List[Dict] = field(default_factory=list)
    iterations: int = 0
    duration_sec: float = 0.0
    error: str = ""


@dataclass
class AgentInstance:
    instance_id: str
    spec: SubAgentSpec
    lifecycle_state: str = AgentLifecycleState.CREATED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[SubAgentResult] = None
    thread: Optional[threading.Thread] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    retry_count: int = 0
    max_retries: int = 3
    cpu_usage_pct: float = 0.0
    memory_usage_mb: float = 0.0
    pid: Optional[int] = None
    last_active_at: float = field(default_factory=time.time)
    sandbox: Optional[SandboxPolicy] = None
    isolated_cwd: str = ""
    memory_namespace: str = ""
    child_cancel_events: List[threading.Event] = field(default_factory=list)
    parent_cancel_event: Optional[threading.Event] = None

    def transition_to(self, new_state: str) -> bool:
        if is_valid_transition(self.lifecycle_state, new_state):
            self.lifecycle_state = new_state
            self.last_active_at = time.time()
            return True
        logger.warning("[AgentInstance] Invalid transition: %s -> %s for %s",
                        self.lifecycle_state, new_state, self.instance_id)
        return False


_IDLE_TIMEOUT = 1800


class AgentPool:
    def __init__(self, role_id: str, pool_size: int = 2, idle_timeout: int = _IDLE_TIMEOUT):
        self.role_id = role_id
        self.pool_size = pool_size
        self._idle_timeout = idle_timeout
        self._available: List[AgentInstance] = []
        self._in_use: Dict[str, AgentInstance] = {}
        self._lock = threading.Lock()
        self._pre_created = False
        self._cleanup_thread: Optional[threading.Thread] = None
        self._running = False

    def pre_create(self, spec_template: SubAgentSpec) -> None:
        for _ in range(self.pool_size):
            instance = AgentInstance(
                instance_id="pool_" + uuid.uuid4().hex[:8],
                spec=spec_template,
                lifecycle_state=AgentLifecycleState.CONFIGURED,
            )
            self._available.append(instance)
        self._pre_created = True

    def acquire(self, spec: Optional[SubAgentSpec] = None) -> Optional[AgentInstance]:
        with self._lock:
            if self._available:
                instance = self._available.pop(0)
                if spec:
                    instance.spec = spec
                instance.transition_to(AgentLifecycleState.STARTED)
                self._in_use[instance.instance_id] = instance
                return instance
            if len(self._in_use) < self.pool_size * 2:
                instance = AgentInstance(
                    instance_id="pool_" + uuid.uuid4().hex[:8],
                    spec=spec or SubAgentSpec(name="", task_description=""),
                    lifecycle_state=AgentLifecycleState.STARTED,
                )
                self._in_use[instance.instance_id] = instance
                return instance
        return None

    def release(self, instance_id: str) -> None:
        with self._lock:
            instance = self._in_use.pop(instance_id, None)
            if instance:
                instance.transition_to(AgentLifecycleState.COMPLETED)
                instance.result = None
                instance.cancel_event.clear()
                self._available.append(instance)

    def start_cleanup(self) -> None:
        self._running = True
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def stop_cleanup(self) -> None:
        self._running = False
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "role_id": self.role_id,
                "pool_size": self.pool_size,
                "available": len(self._available),
                "in_use": len(self._in_use),
                "idle_timeout": self._idle_timeout,
            }

    def _cleanup_loop(self) -> None:
        while self._running:
            try:
                now = time.time()
                with self._lock:
                    stale = [i for i in self._available
                             if now - i.last_active_at > self._idle_timeout]
                    for inst in stale:
                        self._available.remove(inst)
                        logger.info("[AgentPool] Evicted idle instance %s (idle > %ds)",
                                    inst.instance_id, self._idle_timeout)
            except Exception as e:
                logger.error("[AgentPool] Cleanup error: %s", e)
            time.sleep(60)


class AgentMonitor:
    def __init__(self):
        self._history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._anomaly_events: List[Dict[str, Any]] = []
        self._role_stats: Dict[str, Dict[str, Any]] = {}

    def record_execution(self, instance: AgentInstance) -> None:
        with self._lock:
            entry = {
                "instance_id": instance.instance_id,
                "name": instance.spec.name,
                "role_id": instance.spec.role_id,
                "status": instance.lifecycle_state,
                "duration": (instance.completed_at or time.time()) - (instance.started_at or time.time()),
                "error": instance.result.error if instance.result else "",
                "timestamp": time.time(),
                "cpu_pct": instance.cpu_usage_pct,
                "memory_mb": instance.memory_usage_mb,
            }
            self._history.append(entry)
            if len(self._history) > 1000:
                self._history = self._history[-1000:]
            role_id = instance.spec.role_id
            if role_id not in self._role_stats:
                self._role_stats[role_id] = {"count": 0, "successes": 0, "failures": 0, "total_duration": 0.0}
            stats = self._role_stats[role_id]
            stats["count"] += 1
            if instance.lifecycle_state == AgentLifecycleState.COMPLETED:
                stats["successes"] += 1
            elif instance.lifecycle_state == AgentLifecycleState.FAILED:
                stats["failures"] += 1
            if instance.started_at and instance.completed_at:
                stats["total_duration"] += instance.completed_at - instance.started_at

    def record_anomaly(self, instance_id: str, anomaly_type: str, details: str) -> None:
        with self._lock:
            self._anomaly_events.append({
                "instance_id": instance_id,
                "type": anomaly_type,
                "details": details,
                "timestamp": time.time(),
            })

    def get_execution_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._history)
            if total == 0:
                return {"total_executions": 0}
            successes = sum(1 for h in self._history if h["status"] == AgentLifecycleState.COMPLETED)
            failures = sum(1 for h in self._history if h["status"] == AgentLifecycleState.FAILED)
            durations = [h["duration"] for h in self._history if h["duration"] > 0]
            avg_duration = sum(durations) / len(durations) if durations else 0.0
            return {
                "total_executions": total,
                "successes": successes,
                "failures": failures,
                "success_rate": round(successes / total, 4) if total > 0 else 0.0,
                "avg_duration": round(avg_duration, 2),
                "anomaly_count": len(self._anomaly_events),
            }

    def get_role_stats(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            result = {}
            for role_id, stats in self._role_stats.items():
                avg = stats["total_duration"] / stats["count"] if stats["count"] > 0 else 0.0
                result[role_id] = {
                    "count": stats["count"],
                    "successes": stats["successes"],
                    "failures": stats["failures"],
                    "success_rate": round(stats["successes"] / stats["count"], 4) if stats["count"] > 0 else 0.0,
                    "avg_duration": round(avg, 2),
                }
            return result

    def get_recent_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history[-limit:])

    def get_anomalies(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._anomaly_events[-limit:])


class SubAgentOrchestrator:
    MAX_CONCURRENT = 4

    def __init__(self, engine_manager=None, max_concurrent: int = 0, bus=None, state_monitor=None):
        self._engine_manager = engine_manager
        self._max_concurrent = max_concurrent or self.MAX_CONCURRENT
        self._pool = ThreadPoolExecutor(max_workers=self._max_concurrent)
        self._futures: Dict[str, Future] = {}
        self._results: Dict[str, SubAgentResult] = {}
        self._specs: Dict[str, SubAgentSpec] = {}
        self._statuses: Dict[str, str] = {}
        self._instances: Dict[str, AgentInstance] = {}
        self._pools: Dict[str, AgentPool] = {}
        self._monitor = AgentMonitor()
        self._lock = threading.Lock()
        self._cancel_flags: Dict[str, threading.Event] = {}
        self._lifecycle_callbacks: Dict[str, List[Callable]] = {}
        self._parent_child_map: Dict[int, List[threading.Event]] = {}
        self._bus = bus
        self._state_monitor = state_monitor

    def _get_engine_manager(self):
        if self._engine_manager is not None:
            return self._engine_manager
        from shared.engine_management import get_engine_manager
        self._engine_manager = get_engine_manager()
        return self._engine_manager

    def set_bus(self, bus) -> None:
        self._bus = bus

    def set_state_monitor(self, monitor) -> None:
        self._state_monitor = monitor

    def create_pool(self, role_id: str, pool_size: int = 2) -> AgentPool:
        pool = AgentPool(role_id, pool_size)
        self._pools[role_id] = pool
        pool.start_cleanup()
        return pool

    def get_pool(self, role_id: str) -> Optional[AgentPool]:
        return self._pools.get(role_id)

    def spawn(self, spec: SubAgentSpec) -> str:
        subagent_id = "sub_" + uuid.uuid4().hex[:8]
        if not spec.isolated_cwd:
            spec.isolated_cwd = os.path.join(
                _ROOT, "data", "sandboxes", subagent_id)
        if not spec.memory_namespace:
            spec.memory_namespace = f"ns_{subagent_id}"
        if spec.sandbox is None:
            spec.sandbox = SandboxPolicy(
                allowed_paths=[spec.isolated_cwd],
                denied_paths=[],
                network_allowed=False,
            )
        instance = AgentInstance(
            instance_id=subagent_id,
            spec=spec,
            lifecycle_state=AgentLifecycleState.STARTED,
            started_at=time.time(),
            sandbox=spec.sandbox,
            isolated_cwd=spec.isolated_cwd,
            memory_namespace=spec.memory_namespace,
            parent_cancel_event=spec.parent_cancel_event,
        )
        if spec.parent_cancel_event:
            parent_id = id(spec.parent_cancel_event)
            if parent_id not in self._parent_child_map:
                self._parent_child_map[parent_id] = []
            self._parent_child_map[parent_id].append(instance.cancel_event)
        with self._lock:
            self._specs[subagent_id] = spec
            self._statuses[subagent_id] = AgentLifecycleState.RUNNING
            self._cancel_flags[subagent_id] = instance.cancel_event
            self._instances[subagent_id] = instance

        self._emit_lifecycle(subagent_id, AgentLifecycleState.STARTED)
        self._publish_status(subagent_id, AgentLifecycleState.STARTED, spec)
        self._register_with_monitor(subagent_id, spec)
        future = self._pool.submit(self._run_subagent, subagent_id, spec, instance)
        with self._lock:
            self._futures[subagent_id] = future

        logger.info("[SubAgent] spawn %s (%s): %s", subagent_id, spec.name, spec.task_description[:60])
        return subagent_id

    def spawn_from_pool(self, role_id: str, spec: SubAgentSpec) -> Optional[str]:
        pool = self._pools.get(role_id)
        if not pool:
            return self.spawn(spec)
        instance = pool.acquire(spec)
        if not instance:
            return self.spawn(spec)
        instance.spec = spec
        instance.transition_to(AgentLifecycleState.STARTED)
        instance.started_at = time.time()
        with self._lock:
            self._instances[instance.instance_id] = instance
            self._statuses[instance.instance_id] = AgentLifecycleState.RUNNING
        self._emit_lifecycle(instance.instance_id, AgentLifecycleState.STARTED)
        self._publish_status(instance.instance_id, AgentLifecycleState.STARTED, spec)
        future = self._pool.submit(self._run_subagent, instance.instance_id, spec, instance)
        with self._lock:
            self._futures[instance.instance_id] = future
        return instance.instance_id

    def _run_subagent(self, subagent_id: str, spec: SubAgentSpec, instance: AgentInstance):
        start = time.time()
        cancel_event = instance.cancel_event
        timeout_seconds = spec.timeout_seconds
        timed_out = threading.Event()
        parent_cancel = spec.parent_cancel_event

        def _cancel_parent_hook():
            if parent_cancel and parent_cancel.is_set():
                cancel_event.set()
                parent_id = id(parent_cancel)
                for child_evt in self._parent_child_map.get(parent_id, []):
                    child_evt.set()
                logger.info("[SubAgent] %s 父代理取消，子链强终止", subagent_id)

        def _on_timeout():
            timed_out.set()
            cancel_event.set()
            _cancel_parent_hook()
            logger.warning("[SubAgent] %s 超时(%ds), 触发取消", subagent_id, timeout_seconds)

        timer = threading.Timer(timeout_seconds, _on_timeout)
        timer.daemon = True
        timer.start()

        def _sample_resources():
            try:
                import psutil
                proc = psutil.Process(os.getpid())
                mem_info = proc.memory_info()
                instance.memory_usage_mb = mem_info.rss / (1024 * 1024)
                instance.cpu_usage_pct = proc.cpu_percent(interval=0.1)
            except Exception:
                pass

        try:
            _cancel_parent_hook()
            if cancel_event.is_set():
                self._set_result(subagent_id, SubAgentResult(
                    subagent_id=subagent_id, name=spec.name,
                    status="cancelled", duration_sec=time.time() - start,
                ), instance, AgentLifecycleState.TERMINATED)
                return
            if instance.isolated_cwd:
                try:
                    os.makedirs(instance.isolated_cwd, exist_ok=True)
                except Exception:
                    pass
            if instance.sandbox and instance.sandbox.read_only:
                logger.info("[SubAgent] %s sandbox=readonly, 写操作将被拒绝", subagent_id)
            instance.transition_to(AgentLifecycleState.RUNNING)
            self._emit_lifecycle(subagent_id, AgentLifecycleState.RUNNING)
            self._publish_status(subagent_id, AgentLifecycleState.RUNNING, spec)

            engine_mgr = self._get_engine_manager()
            if not engine_mgr._engines:
                engine_mgr.initialize()

            kwargs = {
                "engine": "ollama",
                "max_iterations": spec.max_iterations,
                "is_subagent": True,
                "parent_context": {"subagent_name": spec.name},
                "memory_namespace": spec.memory_namespace,
            }
            if spec.model_override:
                kwargs["model"] = spec.model_override
            if spec.confirm_callback:
                kwargs["confirm_callback"] = spec.confirm_callback

            if cancel_event.is_set():
                self._set_result(subagent_id, SubAgentResult(
                    subagent_id=subagent_id, name=spec.name,
                    status="cancelled", duration_sec=time.time() - start,
                ), instance, AgentLifecycleState.TERMINATED)
                return

            resource_sampler = threading.Thread(target=self._resource_monitor_loop,
                                                args=(subagent_id, instance, cancel_event, timed_out),
                                                daemon=True)
            resource_sampler.start()

            result = engine_mgr.agent_chat(spec.task_description, **kwargs)

            if cancel_event.is_set() and not timed_out.is_set():
                status = "cancelled"
                lifecycle = AgentLifecycleState.TERMINATED
            elif timed_out.is_set():
                status = "timeout"
                lifecycle = AgentLifecycleState.TERMINATED
                logger.warning("[SubAgent] %s 执行超时, 标记为timeout", subagent_id)
            elif result.get("error"):
                status = "failed"
                lifecycle = AgentLifecycleState.FAILED
            elif result.get("cancelled"):
                status = "cancelled"
                lifecycle = AgentLifecycleState.TERMINATED
            else:
                status = "success"
                lifecycle = AgentLifecycleState.COMPLETED

            _sample_resources()

            self._set_result(subagent_id, SubAgentResult(
                subagent_id=subagent_id, name=spec.name, status=status,
                content=result.get("content", ""),
                tool_calls_made=result.get("tool_calls_made", []),
                iterations=result.get("iterations", 0),
                duration_sec=time.time() - start,
                error=result.get("error", ""),
            ), instance, lifecycle)

            if status == "success" and result.get("content"):
                self._merge_result_to_parent(spec, result)

        except Exception as e:
            logger.error("[SubAgent] %s exception: %s", subagent_id, e)
            instance.retry_count += 1
            if instance.retry_count <= instance.max_retries and not cancel_event.is_set():
                self._monitor.record_anomaly(subagent_id, "crash_retry", str(e))
                self._emit_lifecycle(subagent_id, "retry_" + str(instance.retry_count))
                self._publish_status(subagent_id, "retry", spec, error=str(e))
            else:
                self._set_result(subagent_id, SubAgentResult(
                    subagent_id=subagent_id, name=spec.name, status="failed",
                    error=str(e), duration_sec=time.time() - start,
                ), instance, AgentLifecycleState.FAILED)
        finally:
            timer.cancel()

    def _resource_monitor_loop(self, subagent_id: str, instance: AgentInstance,
                                cancel_event: threading.Event,
                                timed_out: threading.Event) -> None:
        while not cancel_event.is_set() and not timed_out.is_set():
            try:
                import psutil
                proc = psutil.Process(os.getpid())
                mem_info = proc.memory_info()
                instance.memory_usage_mb = mem_info.rss / (1024 * 1024)
                instance.cpu_usage_pct = proc.cpu_percent(interval=0.0)
            except ImportError:
                break
            except Exception:
                pass
            cancel_event.wait(timeout=5.0)

    def _merge_result_to_parent(self, spec: SubAgentSpec, result: Dict[str, Any]) -> None:
        if not self._bus:
            return
        try:
            from shared.agent_message import AgentMessage, MessageType
            content = result.get("content", "")
            tool_calls = result.get("tool_calls_made", [])
            self._bus.publish(AgentMessage(
                from_agent=spec.name or "subagent",
                to_agent="*",
                message_type=MessageType.CONTEXT_SHARE.value,
                payload={
                    "source": "subagent_result",
                    "name": spec.name,
                    "content_preview": content[:500],
                    "tool_calls_count": len(tool_calls),
                    "iterations": result.get("iterations", 0),
                },
            ))
        except Exception:
            pass

    def _set_result(self, subagent_id: str, result: SubAgentResult,
                    instance: AgentInstance, lifecycle: str):
        with self._lock:
            self._results[subagent_id] = result
            self._statuses[subagent_id] = result.status
        instance.transition_to(lifecycle)
        instance.completed_at = time.time()
        instance.result = result
        self._monitor.record_execution(instance)
        self._emit_lifecycle(subagent_id, lifecycle)
        self._publish_status(subagent_id, lifecycle, instance.spec, result=result)
        self._update_monitor_heartbeat(subagent_id, lifecycle)
        pool = self._pools.get(instance.spec.role_id)
        if pool and subagent_id in pool._in_use:
            pool.release(subagent_id)

    def pause(self, subagent_id: str) -> bool:
        instance = self._instances.get(subagent_id)
        if instance and instance.lifecycle_state == AgentLifecycleState.RUNNING:
            if instance.transition_to(AgentLifecycleState.PAUSED):
                self._emit_lifecycle(subagent_id, AgentLifecycleState.PAUSED)
                self._publish_status(subagent_id, AgentLifecycleState.PAUSED, instance.spec)
                return True
        return False

    def find_by_task_description(self, description: str) -> List[str]:
        """根据任务描述查找活跃的subagent_id（供外部取消委托方使用）。

        取消权威约定：MultiAgentOrchestrator 的取消必须委托给
        SubAgentOrchestrator.cancel()，通过此方法定位目标 subagent。
        """
        with self._lock:
            results = []
            for sub_id, instance in self._instances.items():
                if (instance.spec
                    and instance.spec.task_description == description
                    and instance.lifecycle_state in (AgentLifecycleState.RUNNING, AgentLifecycleState.STARTED)):
                    results.append(sub_id)
            return results

    def resume(self, subagent_id: str) -> bool:
        instance = self._instances.get(subagent_id)
        if instance and instance.lifecycle_state == AgentLifecycleState.PAUSED:
            if instance.transition_to(AgentLifecycleState.RUNNING):
                self._emit_lifecycle(subagent_id, AgentLifecycleState.RUNNING)
                self._publish_status(subagent_id, AgentLifecycleState.RUNNING, instance.spec)
                return True
        return False

    def terminate(self, subagent_id: str) -> bool:
        """强制终止，等价于 cancel + SIGKILL。同时传播子链。"""
        instance = self._instances.get(subagent_id)
        if not instance:
            return False
        instance.cancel_event.set()
        parent_id = id(instance.parent_cancel_event) if instance.parent_cancel_event else None
        if parent_id and parent_id in self._parent_child_map:
            for child_evt in self._parent_child_map[parent_id]:
                child_evt.set()
        if instance.pid and instance.pid != os.getpid():
            try:
                import signal
                os.kill(instance.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        instance.transition_to(AgentLifecycleState.TERMINATED)
        self._emit_lifecycle(subagent_id, AgentLifecycleState.TERMINATED)
        self._publish_status(subagent_id, AgentLifecycleState.TERMINATED, instance.spec)
        return True

    def get_lifecycle_state(self, subagent_id: str) -> str:
        instance = self._instances.get(subagent_id)
        return instance.lifecycle_state if instance else "unknown"

    def get_instance(self, subagent_id: str) -> Optional[AgentInstance]:
        return self._instances.get(subagent_id)

    def get_all_instances(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                aid: {
                    "instance_id": inst.instance_id,
                    "name": inst.spec.name,
                    "role_id": inst.spec.role_id,
                    "lifecycle": inst.lifecycle_state,
                    "started_at": inst.started_at,
                    "completed_at": inst.completed_at,
                    "cpu_pct": inst.cpu_usage_pct,
                    "memory_mb": inst.memory_usage_mb,
                    "pid": inst.pid,
                }
                for aid, inst in self._instances.items()
            }

    def wait_all(self, timeout: float = 300) -> List[SubAgentResult]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                running = [sid for sid, s in self._statuses.items() if s == AgentLifecycleState.RUNNING]
            if not running:
                break
            time.sleep(0.5)
        else:
            with self._lock:
                for sid in list(self._statuses.keys()):
                    if self._statuses[sid] == AgentLifecycleState.RUNNING:
                        self.terminate(sid)

        with self._lock:
            return list(self._results.values())

    def wait_one(self, subagent_id: str, timeout: float = 120) -> SubAgentResult:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if subagent_id in self._results:
                    return self._results[subagent_id]
            time.sleep(0.3)
        self.terminate(subagent_id)
        with self._lock:
            return self._results.get(subagent_id, SubAgentResult(
                subagent_id=subagent_id, name="", status="timeout",
            ))

    def cancel(self, subagent_id: str):
        """统一取消权威入口。

        取消流程：
        1. cancel_event.set() — 通知 _run_subagent 循环退出
        2. 进程级 kill — 若子Agent有独立 pid:
           - Windows: os.kill → TerminateProcess (不可拦截)
           - POSIX: SIGTERM → 优雅终止, 失败则 terminate() 走 SIGKILL
        3. 传播子链: 通过 _parent_child_map set 所有子 cancel_event
        4. 状态转换 TERMINATED
        """
        instance = self._instances.get(subagent_id)
        if not instance:
            return
        instance.cancel_event.set()
        parent_id = id(instance.parent_cancel_event) if instance.parent_cancel_event else None
        if parent_id and parent_id in self._parent_child_map:
            for child_evt in self._parent_child_map[parent_id]:
                child_evt.set()
        if instance.pid and instance.pid != os.getpid():
            try:
                import signal
                os.kill(instance.pid, signal.SIGTERM)
                logger.info("[SubAgentOrchestrator] cancel: SIGTERM → pid %d", instance.pid)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        instance.transition_to(AgentLifecycleState.TERMINATED)
        self._emit_lifecycle(subagent_id, AgentLifecycleState.TERMINATED)
        self._publish_status(subagent_id, AgentLifecycleState.TERMINATED, instance.spec)

    def get_status(self, subagent_id: str) -> dict:
        with self._lock:
            spec = self._specs.get(subagent_id)
            status = self._statuses.get(subagent_id, "unknown")
            result = self._results.get(subagent_id)
            instance = self._instances.get(subagent_id)
        return {
            "id": subagent_id,
            "name": spec.name if spec else "",
            "status": status,
            "lifecycle": instance.lifecycle_state if instance else "unknown",
            "result": {
                "content": result.content[:200],
                "iterations": result.iterations,
                "tool_calls": len(result.tool_calls_made),
            } if result else None,
            "cpu_pct": instance.cpu_usage_pct if instance else 0.0,
            "memory_mb": instance.memory_usage_mb if instance else 0.0,
            "pid": instance.pid if instance else None,
        }

    def get_monitor(self) -> AgentMonitor:
        return self._monitor

    def on_lifecycle(self, callback: Callable) -> None:
        if "lifecycle" not in self._lifecycle_callbacks:
            self._lifecycle_callbacks["lifecycle"] = []
        self._lifecycle_callbacks["lifecycle"].append(callback)

    def _emit_lifecycle(self, subagent_id: str, state: str) -> None:
        for cb in self._lifecycle_callbacks.get("lifecycle", []):
            try:
                cb(subagent_id, state)
            except Exception:
                pass

    def _publish_status(self, subagent_id: str, state: str, spec: Optional[SubAgentSpec] = None,
                         result: Optional[SubAgentResult] = None, error: str = "") -> None:
        if not self._bus:
            return
        try:
            from shared.agent_message import AgentMessage, MessageType, MessagePriority
            payload: Dict[str, Any] = {"state": state, "agent_id": subagent_id}
            if spec:
                payload["role_id"] = spec.role_id
                payload["task"] = spec.task_description[:100]
            if result:
                payload["status"] = result.status
            if error:
                payload["error"] = error
            self._bus.publish(AgentMessage(
                from_agent=subagent_id,
                to_agent="*",
                message_type=MessageType.STATUS_UPDATE.value,
                payload=payload,
                priority=MessagePriority.LOW.value,
            ))
        except Exception:
            pass

    def _register_with_monitor(self, subagent_id: str, spec: SubAgentSpec) -> None:
        if not self._state_monitor:
            return
        try:
            self._state_monitor.register_agent(subagent_id, metadata={
                "role_id": spec.role_id,
                "name": spec.name,
            })
            self._state_monitor.update_heartbeat(subagent_id, "running", current_task=spec.task_description[:100])
        except Exception:
            pass

    def _update_monitor_heartbeat(self, subagent_id: str, lifecycle: str) -> None:
        if not self._state_monitor:
            return
        try:
            status = "idle" if lifecycle in (AgentLifecycleState.COMPLETED, AgentLifecycleState.FAILED, AgentLifecycleState.TERMINATED) else lifecycle
            self._state_monitor.update_heartbeat(subagent_id, status)
        except Exception:
            pass

    def shutdown(self):
        for pool in self._pools.values():
            pool.stop_cleanup()
        self._pool.shutdown(wait=False)


_global_orchestrator: Optional[SubAgentOrchestrator] = None
_orch_lock = threading.Lock()


def get_sub_agent_orchestrator() -> SubAgentOrchestrator:
    global _global_orchestrator
    if _global_orchestrator is None:
        with _orch_lock:
            if _global_orchestrator is None:
                _global_orchestrator = SubAgentOrchestrator()
    return _global_orchestrator
