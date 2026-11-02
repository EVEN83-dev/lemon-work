"""
B-P2-002: Pomodoro Skill

Timer-based productivity skill with start/pause/stop,
completion callbacks, and persistence.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .models import SkillResult
from ..protocol.card_protocol import CardData, CardType, make_pomodoro_card


@dataclass
class PomodoroTask:
    task_id: str = ""
    minutes: int = 25
    status: str = "idle"
    start_time: float = 0.0
    elapsed_seconds: float = 0.0
    remaining_seconds: float = 0.0
    total_seconds: float = 1500.0
    completed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "taskId": self.task_id,
            "status": self.status,
            "minutes": self.minutes,
            "totalSeconds": self.total_seconds,
            "remaining": int(self.remaining_seconds),
            "elapsed": int(self.elapsed_seconds),
            "completed": self.completed,
        }


class PomodoroSkill:
    name = "pomodoro_skill"
    description = "番茄钟计时器"

    def __init__(self):
        self._tasks: Dict[str, PomodoroTask] = {}
        self._timers: Dict[str, asyncio.Task] = {}
        self._on_complete: Optional[Callable[[PomodoroTask], Any]] = None
        self._daily_count: int = 0

    def set_on_complete(self, callback: Callable[[PomodoroTask], Any]) -> None:
        self._on_complete = callback

    async def start(self, minutes: int = 25, task_id: str = "") -> Dict[str, Any]:
        if not task_id:
            task_id = uuid.uuid4().hex[:12]

        task = PomodoroTask(
            task_id=task_id,
            minutes=minutes,
            status="running",
            start_time=time.time(),
            total_seconds=minutes * 60,
            remaining_seconds=minutes * 60,
        )
        self._tasks[task_id] = task

        self._timers[task_id] = asyncio.create_task(self._tick(task_id))

        return task.to_dict()

    async def pause(self, task_id: str) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task or task.status != "running":
            return {"error": "Task not found or not running"}

        task.status = "paused"
        task.elapsed_seconds = time.time() - task.start_time
        task.remaining_seconds = max(0, task.total_seconds - task.elapsed_seconds)

        timer = self._timers.pop(task_id, None)
        if timer:
            timer.cancel()

        return task.to_dict()

    async def resume(self, task_id: str) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task or task.status != "paused":
            return {"error": "Task not found or not paused"}

        task.status = "running"
        task.start_time = time.time() - task.elapsed_seconds
        self._timers[task_id] = asyncio.create_task(self._tick(task_id))

        return task.to_dict()

    async def stop(self, task_id: str) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "Task not found"}

        task.status = "stopped"
        task.completed = False

        timer = self._timers.pop(task_id, None)
        if timer:
            timer.cancel()

        return task.to_dict()

    async def get_status(self, task_id: str) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task:
            return {"error": "Task not found"}

        if task.status == "running":
            elapsed = time.time() - task.start_time
            task.elapsed_seconds = elapsed
            task.remaining_seconds = max(0, task.total_seconds - elapsed)

        return task.to_dict()

    async def _tick(self, task_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(1)
                task = self._tasks.get(task_id)
                if not task or task.status != "running":
                    break

                elapsed = time.time() - task.start_time
                task.elapsed_seconds = elapsed
                task.remaining_seconds = max(0, task.total_seconds - elapsed)

                if task.remaining_seconds <= 0:
                    task.status = "completed"
                    task.completed = True
                    self._daily_count += 1
                    self._timers.pop(task_id, None)

                    if self._on_complete:
                        try:
                            if asyncio.iscoroutinefunction(self._on_complete):
                                await self._on_complete(task)
                            else:
                                self._on_complete(task)
                        except Exception:
                            pass
                    break
        except asyncio.CancelledError:
            pass

    def get_daily_count(self) -> int:
        return self._daily_count

    def to_card(self, task_id: str) -> str:
        task = self._tasks.get(task_id)
        if not task:
            return make_pomodoro_card(total_seconds=1500, remaining=1500, is_running=False, task_id=task_id).to_json_str()
        return make_pomodoro_card(
            total_seconds=int(task.total_seconds),
            remaining=int(task.remaining_seconds),
            is_running=task.status == "running",
            task_id=task.task_id,
        ).to_json_str()


_pomodoro_instance: Optional[PomodoroSkill] = None


def _get_instance() -> PomodoroSkill:
    global _pomodoro_instance
    if _pomodoro_instance is None:
        _pomodoro_instance = PomodoroSkill()
    return _pomodoro_instance


def _wrapped_handler(**kwargs: Any) -> SkillResult:
    intent = kwargs.pop("intent", "pomodoro")
    payload = kwargs
    result = _handler(intent, payload)
    if isinstance(result, dict):
        if result.get("success", True):
            return SkillResult.ok(output=str(result.get("data", result)), data=result)
        return SkillResult.fail(result.get("error", "Unknown error"))
    return SkillResult.ok(output=str(result))


def _handler(intent: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    inst = _get_instance()
    action = payload.get("action", "status")
    task_id = payload.get("task_id", "")
    minutes = payload.get("minutes", 25)

    import asyncio as _asyncio
    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if action == "start":
        if loop and loop.is_running():
            coro = inst.start(minutes=minutes, task_id=task_id)
            future = _asyncio.run_coroutine_threadsafe(coro, loop)
            result = future.result(timeout=5)
        else:
            result = _asyncio.run(inst.start(minutes=minutes, task_id=task_id))
    elif action == "pause":
        if loop and loop.is_running():
            future = _asyncio.run_coroutine_threadsafe(inst.pause(task_id), loop)
            result = future.result(timeout=5)
        else:
            result = _asyncio.run(inst.pause(task_id))
    elif action == "resume":
        if loop and loop.is_running():
            future = _asyncio.run_coroutine_threadsafe(inst.resume(task_id), loop)
            result = future.result(timeout=5)
        else:
            result = _asyncio.run(inst.resume(task_id))
    elif action == "stop":
        if loop and loop.is_running():
            future = _asyncio.run_coroutine_threadsafe(inst.stop(task_id), loop)
            result = future.result(timeout=5)
        else:
            result = _asyncio.run(inst.stop(task_id))
    elif action == "status":
        if loop and loop.is_running():
            future = _asyncio.run_coroutine_threadsafe(inst.get_status(task_id), loop)
            result = future.result(timeout=5)
        else:
            result = _asyncio.run(inst.get_status(task_id))
    elif action == "daily_count":
        result = {"daily_count": inst.get_daily_count()}
    else:
        result = {"error": "Unknown action: " + str(action)}

    return {
        "skill": "pomodoro_skill",
        "action": action,
        "data": result,
        "needs_llm": False,
    }


def register(registry=None) -> None:
    info = {
        "name": "pomodoro_skill",
        "description": "番茄钟计时器 - 支持开始/暂停/恢复/停止, 完成回调, 每日统计",
        "version": "2.0",
        "category": "productivity",
        "intent_tags": ["pomodoro", "timer", "focus", "break", "tomato"],
        "has_handler": True,
        "handler": _handler,
        "needs_llm": False,
    }
    if registry is not None and hasattr(registry, 'register'):
        from .models import SkillDef, SkillMetadata
        registry.register(SkillDef(
            name="pomodoro_skill",
            description=info["description"],
            category=info["category"],
            handler=_wrapped_handler,
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["start", "pause", "resume", "stop", "status", "daily_count"]},
                    "task_id": {"type": "string"},
                    "minutes": {"type": "integer", "minimum": 1, "maximum": 120},
                },
            },
        ))
    else:
        return info
