# -*- coding: utf-8 -*-
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from bridge.services.task_graph import TaskGraph, TaskNode, TaskStatus

logger = logging.getLogger(__name__)


class OrchestrationMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HIERARCHICAL = "hierarchical"


class FailurePolicy(Enum):
    RETRY = "retry"
    SKIP = "skip"
    ABORT = "abort"


@dataclass
class ReplanResult:
    replan_id: str
    trigger_task_id: str
    trigger_reason: str
    strategy: str
    new_tasks: List[Dict[str, Any]] = field(default_factory=list)
    removed_tasks: List[str] = field(default_factory=list)
    modified_tasks: List[str] = field(default_factory=list)
    success: bool = False


class SequentialOrchestrator:
    def __init__(self, task_graph: TaskGraph, spawn_fn: Optional[Callable] = None,
                 failure_policy: str = FailurePolicy.RETRY.value, max_retries: int = 3):
        self._graph = task_graph
        self._spawn_fn = spawn_fn
        self._failure_policy = failure_policy
        self._max_retries = max_retries
        self._retry_counts: Dict[str, int] = {}
        self._backoff_base = 1.0
        self._callbacks: Dict[str, List[Callable]] = {}
        self._running = False
        self._cancelled = False

    def execute(self) -> Dict[str, Any]:
        self._running = True
        self._cancelled = False
        order = self._graph.get_topological_order()
        results: Dict[str, Any] = {}
        for task_id in order:
            if self._cancelled:
                break
            node = self._graph.get_task(task_id)
            if not node or node.status in (TaskStatus.COMPLETED.value, TaskStatus.SKIPPED.value if hasattr(TaskStatus, 'SKIPPED') else "skipped"):
                continue
            if node.status == TaskStatus.PENDING.value:
                deps = self._graph.get_dependencies_of(task_id)
                pending_deps = [d for d in deps if self._graph.get_task(d) and self._graph.get_task(d).status != TaskStatus.COMPLETED.value]
                if pending_deps:
                    continue
            success = self._execute_task(task_id)
            if not success:
                if self._failure_policy == FailurePolicy.ABORT.value:
                    break
                elif self._failure_policy == FailurePolicy.SKIP.value:
                    self._graph.set_task_status(task_id, TaskStatus.CANCELLED.value)
        self._running = False
        return self._graph.get_progress()

    def cancel(self) -> None:
        self._cancelled = True
        self._running = False

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _execute_task(self, task_id: str) -> bool:
        node = self._graph.get_task(task_id)
        if not node:
            return False
        self._graph.set_task_status(task_id, TaskStatus.RUNNING.value)
        self._emit("task_started", {"task_id": task_id})
        retry = self._retry_counts.get(task_id, 0)
        while retry <= self._max_retries:
            try:
                result = self._spawn_fn(task_id, node.description, node.assigned_role) if self._spawn_fn else None
                self._graph.set_task_status(task_id, TaskStatus.COMPLETED.value, result=str(result) if result else "done")
                self._emit("task_completed", {"task_id": task_id, "result": result})
                return True
            except Exception as e:
                retry += 1
                self._retry_counts[task_id] = retry
                if retry <= self._max_retries:
                    backoff = self._backoff_base * (2 ** (retry - 1))
                    logger.info("[SequentialOrch] Retry %s (attempt %d, backoff %.1fs): %s",
                                task_id, retry, backoff, e)
                    self._emit("task_retry", {"task_id": task_id, "attempt": retry, "backoff": backoff})
                    time.sleep(min(backoff, 8.0))
                else:
                    self._graph.set_task_status(task_id, TaskStatus.FAILED.value, error=str(e))
                    self._emit("task_failed", {"task_id": task_id, "error": str(e)})
                    return False
        return False

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass


class ParallelOrchestrator:
    def __init__(self, task_graph: TaskGraph, spawn_fn: Optional[Callable] = None,
                 failure_policy: str = FailurePolicy.RETRY.value, max_retries: int = 3,
                 max_workers: int = 4):
        self._graph = task_graph
        self._spawn_fn = spawn_fn
        self._failure_policy = failure_policy
        self._max_retries = max_retries
        self._max_workers = max_workers
        self._callbacks: Dict[str, List[Callable]] = {}
        self._cancelled = False

    def execute(self) -> Dict[str, Any]:
        self._cancelled = False
        completed_ids: set = set()
        max_iterations = len(self._graph._nodes) * 2 + 10
        iteration = 0
        while not self._cancelled and iteration < max_iterations:
            iteration += 1
            ready = self._graph.get_ready_tasks()
            running = self._graph.get_running_tasks()
            if not ready and not running:
                break
            slots = self._max_workers - len(running)
            to_run = ready[:max(slots, 0)] if slots > 0 else []
            threads: List[threading.Thread] = []
            for node in to_run:
                self._graph.set_task_status(node.task_id, TaskStatus.RUNNING.value)
                t = threading.Thread(target=self._execute_task, args=(node.task_id,), daemon=True)
                threads.append(t)
                t.start()
            if threads:
                for t in threads:
                    t.join(timeout=600)
            else:
                time.sleep(0.5)
        return self._graph.get_progress()

    def cancel(self) -> None:
        self._cancelled = True

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _execute_task(self, task_id: str) -> None:
        node = self._graph.get_task(task_id)
        if not node:
            return
        retry = 0
        while retry <= self._max_retries:
            try:
                result = self._spawn_fn(task_id, node.description, node.assigned_role) if self._spawn_fn else None
                self._graph.set_task_status(task_id, TaskStatus.COMPLETED.value, result=str(result) if result else "done")
                self._emit("task_completed", {"task_id": task_id})
                return
            except Exception as e:
                retry += 1
                if retry <= self._max_retries:
                    backoff = 1.0 * (2 ** (retry - 1))
                    time.sleep(min(backoff, 8.0))
                else:
                    self._graph.set_task_status(task_id, TaskStatus.FAILED.value, error=str(e))
                    self._emit("task_failed", {"task_id": task_id, "error": str(e)})
                    return

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass


class HierarchicalOrchestrator:
    MAX_DEPTH = 3

    def __init__(self, task_graph: TaskGraph, spawn_fn: Optional[Callable] = None,
                 failure_policy: str = FailurePolicy.RETRY.value, max_retries: int = 3):
        self._graph = task_graph
        self._spawn_fn = spawn_fn
        self._failure_policy = failure_policy
        self._max_retries = max_retries
        self._callbacks: Dict[str, List[Callable]] = {}
        self._cancelled = False

    def execute(self) -> Dict[str, Any]:
        self._cancelled = False
        ready = self._graph.get_ready_tasks()
        for node in ready:
            if self._cancelled:
                break
            self._execute_recursive(node.task_id, depth=0)
        return self._graph.get_progress()

    def _execute_recursive(self, task_id: str, depth: int) -> None:
        if depth > self.MAX_DEPTH or self._cancelled:
            return
        node = self._graph.get_task(task_id)
        if not node:
            return
        self._graph.set_task_status(task_id, TaskStatus.RUNNING.value)
        try:
            result = self._spawn_fn(task_id, node.description, node.assigned_role) if self._spawn_fn else None
            self._graph.set_task_status(task_id, TaskStatus.COMPLETED.value, result=str(result) if result else "done")
            dependents = self._graph.get_dependents_of(task_id)
            child_threads: List[threading.Thread] = []
            for child_id in dependents:
                child_node = self._graph.get_task(child_id)
                if child_node and child_node.status in (TaskStatus.READY.value, TaskStatus.PENDING.value):
                    t = threading.Thread(target=self._execute_recursive, args=(child_id, depth + 1), daemon=True)
                    child_threads.append(t)
                    t.start()
            for t in child_threads:
                t.join(timeout=300)
        except Exception as e:
            self._graph.set_task_status(task_id, TaskStatus.FAILED.value, error=str(e))

    def cancel(self) -> None:
        self._cancelled = True

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass


class Orchestrator:
    MAX_REPLAN_COUNT = 2

    def __init__(self, spawn_fn: Optional[Callable] = None, bus=None):
        self._spawn_fn = spawn_fn
        self._bus = bus
        self._graphs: Dict[str, TaskGraph] = {}
        self._orchestrators: Dict[str, Any] = {}
        self._failure_policies: Dict[str, str] = {}
        self._replan_counts: Dict[str, int] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()

    def create_graph(self, graph_id: str = "") -> TaskGraph:
        if not graph_id:
            graph_id = "tg_" + uuid.uuid4().hex[:8]
        graph = TaskGraph(graph_id)
        with self._lock:
            self._graphs[graph_id] = graph
            self._replan_counts[graph_id] = 0
        return graph

    def execute(self, graph_id: str, mode: str = OrchestrationMode.SEQUENTIAL.value,
                 failure_policy: str = FailurePolicy.RETRY.value,
                 max_workers: int = 4) -> Optional[Dict[str, Any]]:
        graph = self._graphs.get(graph_id)
        if not graph:
            return None
        self._failure_policies[graph_id] = failure_policy
        if mode == OrchestrationMode.SEQUENTIAL.value:
            orch = SequentialOrchestrator(graph, self._spawn_fn, failure_policy)
        elif mode == OrchestrationMode.PARALLEL.value:
            orch = ParallelOrchestrator(graph, self._spawn_fn, failure_policy, max_workers=max_workers)
        elif mode == OrchestrationMode.HIERARCHICAL.value:
            orch = HierarchicalOrchestrator(graph, self._spawn_fn, failure_policy)
        else:
            orch = SequentialOrchestrator(graph, self._spawn_fn, failure_policy)
        orch.on("task_completed", lambda d: self._emit("task_completed", d))
        orch.on("task_failed", lambda d: self._on_task_failed(graph_id, d))
        orch.on("task_retry", lambda d: self._emit("task_retry", d))
        with self._lock:
            self._orchestrators[graph_id] = orch
        result = orch.execute()
        self._emit("orchestration_done", {"graph_id": graph_id, "result": result})
        return result

    def cancel(self, graph_id: str) -> bool:
        orch = self._orchestrators.get(graph_id)
        if orch:
            orch.cancel()
            return True
        return False

    def replan(self, graph_id: str, trigger_task_id: str, reason: str = "failure",
                strategy: str = "local_retry") -> Optional[ReplanResult]:
        graph = self._graphs.get(graph_id)
        if not graph:
            return None
        replan_count = self._replan_counts.get(graph_id, 0)
        if replan_count >= self.MAX_REPLAN_COUNT:
            logger.warning("[Orchestrator] Max replan count reached for %s", graph_id)
            return None
        self._replan_counts[graph_id] = replan_count + 1
        result = ReplanResult(
            replan_id="replan_" + uuid.uuid4().hex[:8],
            trigger_task_id=trigger_task_id,
            trigger_reason=reason,
            strategy=strategy,
        )
        if strategy == "local_retry":
            node = graph.get_task(trigger_task_id)
            if node:
                graph.set_task_status(trigger_task_id, TaskStatus.PENDING.value)
                result.modified_tasks.append(trigger_task_id)
                result.success = True
        elif strategy == "path_adjust":
            node = graph.get_task(trigger_task_id)
            if node:
                graph.set_task_status(trigger_task_id, TaskStatus.CANCELLED.value)
                dependents = graph.get_dependents_of(trigger_task_id)
                for dep_id in dependents:
                    dep_node = graph.get_task(dep_id)
                    if dep_node and trigger_task_id in dep_node.dependencies:
                        dep_node.dependencies.remove(trigger_task_id)
                        graph.add_dependency(dep_id, trigger_task_id)
                        result.modified_tasks.append(dep_id)
                result.removed_tasks.append(trigger_task_id)
                result.success = True
        elif strategy == "full_replan":
            for tid in list(graph._nodes.keys()):
                node = graph.get_task(tid)
                if node and node.status not in (TaskStatus.COMPLETED.value,):
                    graph.set_task_status(tid, TaskStatus.PENDING.value)
                    result.modified_tasks.append(tid)
            result.success = True
        self._emit("replan_executed", {
            "graph_id": graph_id,
            "replan_id": result.replan_id,
            "strategy": strategy,
            "trigger_task": trigger_task_id,
            "reason": reason,
            "replan_count": self._replan_counts[graph_id],
        })
        logger.info("[Orchestrator] Replan %s for graph %s: strategy=%s, trigger=%s, reason=%s",
                     result.replan_id, graph_id, strategy, trigger_task_id, reason)
        return result

    def get_graph(self, graph_id: str) -> Optional[TaskGraph]:
        return self._graphs.get(graph_id)

    def get_progress(self, graph_id: str) -> Optional[Dict[str, Any]]:
        graph = self._graphs.get(graph_id)
        return graph.get_progress() if graph else None

    def list_graphs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [{"graph_id": gid, "progress": g.get_progress()} for gid, g in self._graphs.items()]

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _on_task_failed(self, graph_id: str, data: Dict) -> None:
        task_id = data.get("task_id", "")
        policy = self._failure_policies.get(graph_id, FailurePolicy.RETRY.value)
        if policy == FailurePolicy.RETRY.value:
            replan_result = self.replan(graph_id, task_id, reason="failure", strategy="local_retry")
            if replan_result and replan_result.success:
                self.execute(graph_id, mode=OrchestrationMode.SEQUENTIAL.value,
                              failure_policy=FailurePolicy.RETRY.value)
        self._emit("task_failed", {**data, "graph_id": graph_id, "policy": policy})

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass
