# -*- coding: utf-8 -*-
"""364章 T3.1: 异步任务队列 — 后台长任务调度"""

import threading
import time
import uuid
from typing import Callable, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AsyncTask:
    task_id: str
    name: str
    fn: Callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: object = None
    error: str = ""
    progress: float = 0.0
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()


class AsyncTaskQueue:
    def __init__(self, max_workers: int = 2):
        self.max_workers = max_workers
        self._tasks: Dict[str, AsyncTask] = {}
        self._queue: List[str] = []
        self._lock = threading.Lock()
        self._running = 0
        self._worker_thread = None
        self._stop_event = threading.Event()

    def submit(self, name: str, fn: Callable, *args, **kwargs) -> str:
        task_id = str(uuid.uuid4())[:8]
        task = AsyncTask(task_id=task_id, name=name, fn=fn, args=args, kwargs=kwargs)
        with self._lock:
            self._tasks[task_id] = task
            self._queue.append(task_id)
        self._ensure_worker()
        return task_id

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                task.status = TaskStatus.CANCELLED
                if task_id in self._queue:
                    self._queue.remove(task_id)
                return True
        return False

    def get_status(self, task_id: str) -> Optional[Dict]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {
                "task_id": task.task_id,
                "name": task.name,
                "status": task.status.value,
                "progress": task.progress,
                "error": task.error,
                "duration": (task.finished_at or time.time()) - task.started_at if task.started_at else 0,
            }

    def list_tasks(self) -> List[Dict]:
        with self._lock:
            task_ids = list(self._tasks.keys())
        return [self.get_status(tid) for tid in task_ids]

    def _ensure_worker(self):
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def _worker_loop(self):
        while not self._stop_event.is_set():
            task_id = None
            with self._lock:
                if self._running < self.max_workers and self._queue:
                    task_id = self._queue.pop(0)
                    if task_id:
                        self._running += 1
                        self._tasks[task_id].status = TaskStatus.RUNNING
                        self._tasks[task_id].started_at = time.time()

            if task_id is None:
                time.sleep(0.1)
                continue

            task = self._tasks[task_id]
            if task.status == TaskStatus.CANCELLED:
                with self._lock:
                    self._running -= 1
                continue

            try:
                task.result = task.fn(*task.args, **task.kwargs)
                task.status = TaskStatus.COMPLETED
                task.progress = 1.0
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
            finally:
                task.finished_at = time.time()
                with self._lock:
                    self._running -= 1

    def shutdown(self):
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
