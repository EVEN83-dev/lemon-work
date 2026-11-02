# -*- coding: utf-8 -*-
"""
[DEPRECATED] 本模块已废弃，请使用 shared.orchestration_engine 代替。
保留仅为向后兼容，新代码请直接导入:
  from shared.orchestration_engine import OrchestrationEngine, get_orchestration_engine

兼容重导出：
  - OrchestrationPlanner → shared.orchestration_engine.OrchestrationPlanner
  - OrchestrationExecutor → shared.orchestration_engine.OrchestrationEngine
  - get_orchestration_planner → shared.orchestration_engine.get_orchestration_planner
  - get_orchestration_executor → shared.orchestration_engine.get_orchestration_engine
"""
import threading
import time
import uuid
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class OrchestrationMode(Enum):
    SEQUENCE = "sequence"
    PARALLEL = "parallel"
    HIERARCHY = "hierarchy"


class StepState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class OrchestrationStep:
    step_id: str
    agent_role: str
    task_description: str
    dependencies: List[str] = field(default_factory=list)
    state: str = "pending"
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    agent_id: Optional[str] = None
    parent_step_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    estimated_duration: float = 30.0

    @property
    def duration(self) -> float:
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "agent_role": self.agent_role,
            "task_description": self.task_description,
            "dependencies": self.dependencies,
            "state": self.state,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "agent_id": self.agent_id,
            "parent_step_id": self.parent_step_id,
            "children": self.children,
            "estimated_duration": self.estimated_duration,
            "duration": self.duration,
        }


@dataclass
class OrchestrationPlan:
    plan_id: str = ""
    mode: str = ""
    goal: str = ""
    steps: List[OrchestrationStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    status: str = "draft"
    completed_at: Optional[float] = None

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = "orch_" + uuid.uuid4().hex[:8]

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.state in ("completed", "skipped"))
        return done / len(self.steps)

    @property
    def estimated_remaining(self) -> float:
        pending = [s for s in self.steps if s.state == "pending"]
        completed_durations = [s.duration for s in self.steps if s.state == "completed" and s.duration > 0]
        if completed_durations:
            avg = sum(completed_durations) / len(completed_durations)
            return avg * len(pending)
        total_est = sum(s.estimated_duration for s in pending)
        return total_est

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "mode": self.mode,
            "goal": self.goal,
            "status": self.status,
            "progress": round(self.progress, 2),
            "estimated_remaining": round(self.estimated_remaining, 1),
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class OrchestrationPlanner:
    """[DEPRECATED] 兼容重导出，委托到 shared.orchestration_engine.OrchestrationPlanner。"""

    def __init__(self):
        from shared.orchestration_engine import OrchestrationPlanner as _RealPlanner
        self._real = _RealPlanner()

    def plan_sequence(self, goal: str, tasks: List[Dict[str, Any]]) -> "OrchestrationPlan":
        warnings.warn("[DEPRECATED] 使用 shared.orchestration_engine.OrchestrationPlanner", DeprecationWarning, stacklevel=2)
        return self._real.plan_sequence(goal, tasks)

    def plan_parallel(self, goal: str, tasks: List[Dict[str, Any]]) -> "OrchestrationPlan":
        warnings.warn("[DEPRECATED] 使用 shared.orchestration_engine.OrchestrationPlanner", DeprecationWarning, stacklevel=2)
        return self._real.plan_parallel(goal, tasks)

    def plan_hierarchy(self, goal: str, parent_tasks: List[Dict[str, Any]],
                       child_map: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> "OrchestrationPlan":
        warnings.warn("[DEPRECATED] 使用 shared.orchestration_engine.OrchestrationPlanner", DeprecationWarning, stacklevel=2)
        return self._real.plan_hierarchy(goal, parent_tasks, child_map)

    def auto_plan(self, goal: str, available_roles: Optional[List[str]] = None) -> "OrchestrationPlan":
        warnings.warn("[DEPRECATED] 使用 shared.orchestration_engine.OrchestrationPlanner", DeprecationWarning, stacklevel=2)
        return self._real.auto_plan(goal, available_roles)


class OrchestrationExecutor:
    """[DEPRECATED] 兼容重导出，委托到 shared.orchestration_engine.OrchestrationEngine。"""

    def __init__(self, spawn_callback: Optional[Callable] = None):
        warnings.warn("[DEPRECATED] 使用 shared.orchestration_engine.OrchestrationEngine", DeprecationWarning, stacklevel=2)
        from shared.orchestration_engine import get_orchestration_engine
        self._engine = get_orchestration_engine()
        if spawn_callback:
            self._engine.set_spawn_fn(spawn_callback)

    def create_plan(self, plan: "OrchestrationPlan") -> str:
        return self._engine.create_plan(plan.goal, plan.mode)

    def get_plan(self, plan_id: str):
        return self._engine.get_plan(plan_id)

    def execute(self, plan_id: str) -> bool:
        result = self._engine.execute_plan(plan_id)
        return result is not None

    def cancel(self, plan_id: str) -> bool:
        return self._engine.cancel_plan(plan_id)

    def on(self, event_name: str, callback: Callable) -> None:
        self._engine.on(event_name, callback)

    def get_active_plans(self) -> List[Dict[str, Any]]:
        return self._engine.get_active_plans()

    def get_all_plans(self) -> List[Dict[str, Any]]:
        return self._engine.get_all_plans()


_global_planner: Optional[OrchestrationPlanner] = None
_global_executor: Optional[OrchestrationExecutor] = None
_orch_lock = threading.Lock()


def get_orchestration_planner() -> OrchestrationPlanner:
    """[DEPRECATED] 委托到 shared.orchestration_engine.get_orchestration_planner。"""
    from shared.orchestration_engine import get_orchestration_planner as _real
    return _real()


def get_orchestration_executor() -> OrchestrationExecutor:
    """[DEPRECATED] 委托到 shared.orchestration_engine.get_orchestration_engine。"""
    from shared.orchestration_engine import get_orchestration_engine as _real
    engine = _real()
    return OrchestrationExecutor(spawn_callback=engine._spawn_fn)
