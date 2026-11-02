# -*- coding: utf-8 -*-
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskNode:
    task_id: str
    description: str
    assigned_role: str = ""
    assigned_agent: str = ""
    dependencies: List[str] = field(default_factory=list)
    status: str = TaskStatus.PENDING.value
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    estimated_duration: float = 30.0
    priority: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "assigned_role": self.assigned_role,
            "assigned_agent": self.assigned_agent,
            "dependencies": self.dependencies,
            "status": self.status,
            "result": self.result[:200] if self.result else None,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.duration,
            "estimated_duration": self.estimated_duration,
            "priority": self.priority,
        }


class TaskGraph:
    def __init__(self, graph_id: str = ""):
        self.graph_id = graph_id or "tg_" + uuid.uuid4().hex[:8]
        self._nodes: Dict[str, TaskNode] = {}
        self._edges: Dict[str, List[str]] = {}
        self._reverse_edges: Dict[str, List[str]] = {}
        self._lock = threading.Lock()
        self._callbacks: Dict[str, List[Callable]] = {}

    def add_task(self, task_id: str, description: str, assigned_role: str = "",
                  dependencies: Optional[List[str]] = None, priority: int = 1,
                  estimated_duration: float = 30.0, metadata: Optional[Dict] = None) -> TaskNode:
        with self._lock:
            if task_id in self._nodes:
                return self._nodes[task_id]
            node = TaskNode(
                task_id=task_id,
                description=description,
                assigned_role=assigned_role,
                dependencies=dependencies or [],
                priority=priority,
                estimated_duration=estimated_duration,
                metadata=metadata or {},
            )
            self._nodes[task_id] = node
            self._edges[task_id] = []
            self._reverse_edges[task_id] = []
            for dep_id in (dependencies or []):
                if dep_id in self._nodes:
                    self._edges[dep_id].append(task_id)
                    self._reverse_edges[task_id].append(dep_id)
            if not (dependencies or []):
                node.status = TaskStatus.READY.value
            else:
                self._update_ready_status(task_id)
        self._emit("task_added", node)
        return node

    def add_dependency(self, task_id: str, depends_on: str) -> bool:
        with self._lock:
            if task_id not in self._nodes or depends_on not in self._nodes:
                return False
            if depends_on not in self._reverse_edges[task_id]:
                self._reverse_edges[task_id].append(depends_on)
                self._edges[depends_on].append(task_id)
                if depends_on not in self._nodes[task_id].dependencies:
                    self._nodes[task_id].dependencies.append(depends_on)
            if self._has_cycle():
                self._reverse_edges[task_id].remove(depends_on)
                self._edges[depends_on].remove(task_id)
                self._nodes[task_id].dependencies.remove(depends_on)
                logger.error("[TaskGraph] Cycle detected adding %s -> %s", depends_on, task_id)
                return False
            self._update_ready_status(task_id)
        return True

    def remove_task(self, task_id: str) -> bool:
        with self._lock:
            if task_id not in self._nodes:
                return False
            for dep_id in self._reverse_edges.get(task_id, []):
                if task_id in self._edges.get(dep_id, []):
                    self._edges[dep_id].remove(task_id)
            for child_id in self._edges.get(task_id, []):
                if task_id in self._reverse_edges.get(child_id, []):
                    self._reverse_edges[child_id].remove(task_id)
                if task_id in self._nodes[child_id].dependencies:
                    self._nodes[child_id].dependencies.remove(task_id)
                self._update_ready_status(child_id)
            del self._nodes[task_id]
            self._edges.pop(task_id, None)
            self._reverse_edges.pop(task_id, None)
        return True

    def insert_task(self, task_id: str, description: str, assigned_role: str = "",
                     depends_on: Optional[List[str]] = None, dependents: Optional[List[str]] = None,
                     priority: int = 1) -> TaskNode:
        with self._lock:
            all_deps = list(depends_on or [])
            node = self.add_task(task_id, description, assigned_role, all_deps, priority)
            if dependents:
                for child_id in dependents:
                    if child_id in self._nodes:
                        self.add_dependency(child_id, task_id)
        return node

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        return self._nodes.get(task_id)

    def set_task_status(self, task_id: str, status: str, result: Optional[str] = None,
                         error: Optional[str] = None, agent_id: str = "") -> bool:
        with self._lock:
            node = self._nodes.get(task_id)
            if not node:
                return False
            old_status = node.status
            node.status = status
            if result is not None:
                node.result = result
            if error is not None:
                node.error = error
            if agent_id:
                node.assigned_agent = agent_id
            if status == TaskStatus.RUNNING.value and node.started_at is None:
                node.started_at = time.time()
            if status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
                node.completed_at = time.time()
            if status == TaskStatus.COMPLETED.value:
                for child_id in self._edges.get(task_id, []):
                    self._update_ready_status(child_id)
        self._emit("task_status_changed", {
            "task_id": task_id, "old_status": old_status, "new_status": status,
        })
        return True

    def get_ready_tasks(self) -> List[TaskNode]:
        with self._lock:
            ready = []
            for node in self._nodes.values():
                if node.status == TaskStatus.READY.value:
                    ready.append(node)
            ready.sort(key=lambda n: n.priority, reverse=True)
            return ready

    def get_pending_tasks(self) -> List[TaskNode]:
        with self._lock:
            return [n for n in self._nodes.values() if n.status == TaskStatus.PENDING.value]

    def get_running_tasks(self) -> List[TaskNode]:
        with self._lock:
            return [n for n in self._nodes.values() if n.status == TaskStatus.RUNNING.value]

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [n.to_dict() for n in self._nodes.values()]

    def get_progress(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._nodes)
            if total == 0:
                return {"total": 0, "progress": 0.0}
            completed = sum(1 for n in self._nodes.values() if n.status == TaskStatus.COMPLETED.value)
            failed = sum(1 for n in self._nodes.values() if n.status == TaskStatus.FAILED.value)
            running = sum(1 for n in self._nodes.values() if n.status == TaskStatus.RUNNING.value)
            pending = total - completed - failed - running
            return {
                "total": total,
                "completed": completed,
                "failed": failed,
                "running": running,
                "pending": pending,
                "progress": round(completed / total, 2) if total > 0 else 0.0,
            }

    def detect_cycle(self) -> bool:
        with self._lock:
            return self._has_cycle()

    def get_critical_path(self) -> List[str]:
        with self._lock:
            return self._compute_critical_path()

    def get_topological_order(self) -> List[str]:
        with self._lock:
            return self._topological_sort()

    def get_dependencies_of(self, task_id: str) -> List[str]:
        with self._lock:
            return list(self._reverse_edges.get(task_id, []))

    def get_dependents_of(self, task_id: str) -> List[str]:
        with self._lock:
            return list(self._edges.get(task_id, []))

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _update_ready_status(self, task_id: str) -> None:
        node = self._nodes.get(task_id)
        if not node or node.status != TaskStatus.PENDING.value:
            return
        all_deps_done = all(
            self._nodes.get(dep_id) and self._nodes[dep_id].status == TaskStatus.COMPLETED.value
            for dep_id in node.dependencies
        )
        if all_deps_done:
            node.status = TaskStatus.READY.value

    def _has_cycle(self) -> bool:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in self._nodes}
        def dfs(node_id: str) -> bool:
            color[node_id] = GRAY
            for neighbor in self._edges.get(node_id, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    return True
                if color[neighbor] == WHITE and dfs(neighbor):
                    return True
            color[node_id] = BLACK
            return False
        for nid in self._nodes:
            if color[nid] == WHITE:
                if dfs(nid):
                    return True
        return False

    def _topological_sort(self) -> List[str]:
        in_degree: Dict[str, int] = {nid: 0 for nid in self._nodes}
        for nid in self._nodes:
            for child in self._edges.get(nid, []):
                if child in in_degree:
                    in_degree[child] += 1
        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        order: List[str] = []
        while queue:
            nid = queue.popleft()
            order.append(nid)
            for child in self._edges.get(nid, []):
                if child in in_degree:
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        queue.append(child)
        return order

    def _compute_critical_path(self) -> List[str]:
        earliest: Dict[str, float] = {}
        for nid in self._topological_sort():
            node = self._nodes.get(nid)
            if not node:
                continue
            deps = self._reverse_edges.get(nid, [])
            if not deps:
                earliest[nid] = node.estimated_duration
            else:
                earliest[nid] = max(earliest.get(d, 0) for d in deps) + node.estimated_duration
        if not earliest:
            return []
        end_node = max(earliest, key=earliest.get)
        path: List[str] = [end_node]
        current = end_node
        while True:
            deps = self._reverse_edges.get(current, [])
            if not deps:
                break
            prev = max(deps, key=lambda d: earliest.get(d, 0))
            path.insert(0, prev)
            current = prev
        return path

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass
