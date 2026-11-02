"""
B-P2-005: Task Manager

Background task lifecycle management with SQLite persistence.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class TaskInfo:
    task_id: str = ""
    task_type: str = ""
    status: str = "pending"
    progress: int = 0
    params: Dict[str, Any] = None
    result: Dict[str, Any] = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "taskId": self.task_id,
            "type": self.task_type,
            "status": self.status,
            "progress": self.progress,
            "params": self.params or {},
            "result": self.result or {},
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class TaskManager:
    def __init__(self, db_path: str = ""):
        if not db_path:
            db_path = str(Path(__file__).parent.parent / "data" / "tasks.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._running: Dict[str, asyncio.Task] = {}
        self._on_complete_callbacks: Dict[str, Callable] = {}
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                progress INTEGER DEFAULT 0,
                params TEXT DEFAULT '{}',
                result TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self._conn.commit()

    async def create(
        self, task_type: str, params: Dict[str, Any], task_id: str = ""
    ) -> Dict[str, Any]:
        if not task_id:
            task_id = uuid.uuid4().hex[:12]
        now = time.time()
        self._conn.execute(
            "INSERT INTO tasks (task_id, task_type, status, params, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, task_type, "pending", json.dumps(params), now, now),  # noqa: F821
        )
        self._conn.commit()
        return {"taskId": task_id, "status": "pending"}

    async def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT task_id, task_type, status, progress, params, result, created_at, updated_at FROM tasks WHERE task_id = ?",
            (task_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "taskId": row[0],
            "type": row[1],
            "status": row[2],
            "progress": row[3],
            "params": json.loads(row[4]),  # noqa: F821
            "result": json.loads(row[5]),  # noqa: F821
            "createdAt": row[6],
            "updatedAt": row[7],
        }

    async def update_progress(self, task_id: str, progress: int, status: str = "") -> None:
        now = time.time()
        if status:
            self._conn.execute(
                "UPDATE tasks SET progress = ?, status = ?, updated_at = ? WHERE task_id = ?",
                (progress, status, now, task_id),
            )
        else:
            self._conn.execute(
                "UPDATE tasks SET progress = ?, updated_at = ? WHERE task_id = ?",
                (progress, now, task_id),
            )
        self._conn.commit()

    async def complete(self, task_id: str, result: Dict[str, Any]) -> None:
        now = time.time()
        self._conn.execute(
            "UPDATE tasks SET status = 'completed', progress = 100, result = ?, updated_at = ? WHERE task_id = ?",
            (json.dumps(result), now, task_id),  # noqa: F821
        )
        self._conn.commit()

        callback = self._on_complete_callbacks.pop(task_id, None)
        if callback:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(task_id, result)
                else:
                    callback(task_id, result)
            except Exception:
                pass

    async def cancel(self, task_id: str) -> Dict[str, str]:
        now = time.time()
        self._conn.execute(
            "UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE task_id = ?",
            (now, task_id),
        )
        self._conn.commit()

        running_task = self._running.pop(task_id, None)
        if running_task:
            running_task.cancel()

        return {"status": "cancelled"}

    async def list_tasks(
        self, task_type: str = "", status: str = "", limit: int = 50
    ) -> List[Dict[str, Any]]:
        query = "SELECT task_id, task_type, status, progress, created_at FROM tasks"
        conditions = []
        params_list: list = []
        if task_type:
            conditions.append("task_type = ?")
            params_list.append(task_type)
        if status:
            conditions.append("status = ?")
            params_list.append(status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params_list.append(limit)

        cursor = self._conn.execute(query, params_list)
        rows = cursor.fetchall()
        return [
            {
                "taskId": r[0],
                "type": r[1],
                "status": r[2],
                "progress": r[3],
                "createdAt": r[4],
            }
            for r in rows
        ]

    def on_complete(self, task_id: str, callback: Callable) -> None:
        self._on_complete_callbacks[task_id] = callback

    def recover_pending(self) -> List[str]:
        cursor = self._conn.execute(
            "SELECT task_id FROM tasks WHERE status IN ('pending', 'running')"
        )
        rows = cursor.fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self._conn.close()
