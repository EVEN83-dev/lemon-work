# -*- coding: utf-8 -*-
import threading
import time
import uuid
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class OrchestrationMode(Enum):
    SEQUENCE = "sequence"
    PARALLEL = "parallel"
    HIERARCHY = "hierarchy"
    AUTO = "auto"


class StepState(Enum):
    PENDING = "pending"
    WAITING_DEPS = "waiting_deps"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class PlanStatus(Enum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OrchestrationStep:
    step_id: str
    agent_role: str
    task_description: str
    dependencies: List[str] = field(default_factory=list)
    state: str = StepState.PENDING.value
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    agent_id: Optional[str] = None
    parent_step_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    estimated_duration: float = 30.0
    retry_count: int = 0
    max_retries: int = 2
    context_data: Dict[str, Any] = field(default_factory=dict)

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
            "retry_count": self.retry_count,
        }


@dataclass
class OrchestrationPlan:
    plan_id: str = ""
    mode: str = ""
    goal: str = ""
    steps: List[OrchestrationStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    status: str = PlanStatus.DRAFT.value
    completed_at: Optional[float] = None
    session_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = "orch_" + uuid.uuid4().hex[:8]

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.state in (StepState.COMPLETED.value, StepState.SKIPPED.value))
        return done / len(self.steps)

    @property
    def estimated_remaining(self) -> float:
        pending = [s for s in self.steps if s.state in (StepState.PENDING.value, StepState.WAITING_DEPS.value, StepState.RUNNING.value)]
        completed_durations = [s.duration for s in self.steps if s.state == StepState.COMPLETED.value and s.duration > 0]
        if completed_durations:
            avg = sum(completed_durations) / len(completed_durations)
            return avg * len(pending)
        return sum(s.estimated_duration for s in pending)

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
            "session_id": self.session_id,
        }


class OrchestratorBase(ABC):
    @abstractmethod
    def execute(self, plan: OrchestrationPlan) -> OrchestrationPlan:
        ...

    @abstractmethod
    def cancel(self, plan_id: str) -> bool:
        ...

    @abstractmethod
    def get_status(self, plan_id: str) -> Optional[Dict[str, Any]]:
        ...


class SequenceOrchestrator(OrchestratorBase):
    def __init__(self, spawn_fn: Optional[Callable] = None,
                 bus=None, shared_context=None):
        self._spawn_fn = spawn_fn
        self._bus = bus
        self._shared_context = shared_context
        self._plans: Dict[str, OrchestrationPlan] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()

    def execute(self, plan: OrchestrationPlan) -> OrchestrationPlan:
        with self._lock:
            self._plans[plan.plan_id] = plan
        plan.status = PlanStatus.RUNNING.value
        self._emit("plan_started", plan)
        for step in plan.steps:
            if plan.status != PlanStatus.RUNNING.value:
                break
            self._run_step(plan, step)
            if step.state == StepState.FAILED.value:
                plan.status = PlanStatus.FAILED.value
                plan.completed_at = time.time()
                self._emit("plan_failed", plan)
                return plan
        if plan.status == PlanStatus.RUNNING.value:
            plan.status = PlanStatus.COMPLETED.value
            plan.completed_at = time.time()
            self._emit("plan_completed", plan)
        return plan

    def cancel(self, plan_id: str) -> bool:
        with self._lock:
            plan = self._plans.get(plan_id)
        if plan:
            plan.status = PlanStatus.CANCELLED.value
            self._emit("plan_cancelled", plan)
            return True
        return False

    def get_status(self, plan_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            plan = self._plans.get(plan_id)
        return plan.to_dict() if plan else None

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _run_step(self, plan: OrchestrationPlan, step: OrchestrationStep) -> None:
        step.state = StepState.RUNNING.value
        step.started_at = time.time()
        self._emit("step_started", step)
        retry = 0
        while retry <= step.max_retries:
            try:
                result = self._spawn(step)
                step.result = OrchestrationEngine._resolve_spawn_result(result)
                OrchestrationEngine._enforce_result_contract(step)
                step.state = StepState.COMPLETED.value
                step.completed_at = time.time()
                self._emit("step_completed", step)
                self._publish_context(plan, step)
                return
            except Exception as e:
                retry += 1
                step.error = str(e)
                step.retry_count = retry
                if retry > step.max_retries:
                    step.state = StepState.FAILED.value
                    step.completed_at = time.time()
                    self._emit("step_failed", step)
                    return
                step.state = StepState.RETRYING.value
                self._emit("step_retry", step)

    def _spawn(self, step: OrchestrationStep) -> Optional[str]:
        if self._spawn_fn:
            return self._spawn_fn(step.agent_role, step.task_description, step.context_data)
        return None

    def _publish_context(self, plan: OrchestrationPlan, step: OrchestrationStep) -> None:
        if self._bus and step.result:
            from shared.agent_message import AgentMessage, MessageType
            self._bus.publish(AgentMessage(
                from_agent=step.agent_id or step.agent_role,
                to_agent="*",
                message_type=MessageType.CONTEXT_SHARE.value,
                payload={"step_id": step.step_id, "result": step.result[:500]},
                context_id=plan.session_id,
            ))
        if self._shared_context and step.result:
            self._shared_context.set_shared(
                plan.session_id or plan.plan_id,
                f"step_{step.step_id}_result",
                step.result[:2000],
                owner=step.agent_id or step.agent_role,
            )

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass


class ParallelOrchestrator(OrchestratorBase):
    def __init__(self, spawn_fn: Optional[Callable] = None,
                 bus=None, shared_context=None, max_workers: int = 4):
        self._spawn_fn = spawn_fn
        self._bus = bus
        self._shared_context = shared_context
        self._max_workers = max_workers
        self._plans: Dict[str, OrchestrationPlan] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()
        self._pool = None

    def execute(self, plan: OrchestrationPlan) -> OrchestrationPlan:
        with self._lock:
            self._plans[plan.plan_id] = plan
        plan.status = PlanStatus.RUNNING.value
        self._emit("plan_started", plan)
        threads: List[threading.Thread] = []
        for step in plan.steps:
            if plan.status != PlanStatus.RUNNING.value:
                break
            t = threading.Thread(target=self._run_step, args=(plan, step), daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=600)
        any_failed = any(s.state == StepState.FAILED.value for s in plan.steps)
        all_done = all(s.state in (StepState.COMPLETED.value, StepState.SKIPPED.value) for s in plan.steps)
        if any_failed:
            plan.status = PlanStatus.FAILED.value
            self._emit("plan_partial_failure", plan)
        elif all_done:
            plan.status = PlanStatus.COMPLETED.value
            plan.completed_at = time.time()
            self._emit("plan_completed", plan)
        return plan

    def cancel(self, plan_id: str) -> bool:
        with self._lock:
            plan = self._plans.get(plan_id)
        if plan:
            plan.status = PlanStatus.CANCELLED.value
            self._emit("plan_cancelled", plan)
            return True
        return False

    def get_status(self, plan_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            plan = self._plans.get(plan_id)
        return plan.to_dict() if plan else None

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _run_step(self, plan: OrchestrationPlan, step: OrchestrationStep) -> None:
        step.state = StepState.RUNNING.value
        step.started_at = time.time()
        self._emit("step_started", step)
        retry = 0
        while retry <= step.max_retries:
            try:
                result = self._spawn_fn(step.agent_role, step.task_description, step.context_data) if self._spawn_fn else None
                step.result = OrchestrationEngine._resolve_spawn_result(result)
                OrchestrationEngine._enforce_result_contract(step)
                step.state = StepState.COMPLETED.value
                step.completed_at = time.time()
                self._emit("step_completed", step)
                return
            except Exception as e:
                retry += 1
                step.error = str(e)
                step.retry_count = retry
                if retry > step.max_retries:
                    step.state = StepState.FAILED.value
                    step.completed_at = time.time()
                    self._emit("step_failed", step)
                    return
                step.state = StepState.RETRYING.value
                self._emit("step_retry", step)

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass


class HierarchyOrchestrator(OrchestratorBase):
    def __init__(self, spawn_fn: Optional[Callable] = None,
                 bus=None, shared_context=None):
        self._spawn_fn = spawn_fn
        self._bus = bus
        self._shared_context = shared_context
        self._plans: Dict[str, OrchestrationPlan] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()

    def execute(self, plan: OrchestrationPlan) -> OrchestrationPlan:
        with self._lock:
            self._plans[plan.plan_id] = plan
        plan.status = PlanStatus.RUNNING.value
        self._emit("plan_started", plan)
        root_steps = [s for s in plan.steps if s.parent_step_id is None]
        for root in root_steps:
            if plan.status != PlanStatus.RUNNING.value:
                break
            self._run_step(plan, root)
            children = [s for s in plan.steps if s.parent_step_id == root.step_id]
            child_threads: List[threading.Thread] = []
            for child in children:
                t = threading.Thread(target=self._run_step, args=(plan, child), daemon=True)
                child_threads.append(t)
                t.start()
            for t in child_threads:
                t.join(timeout=300)
            if root.state == StepState.FAILED.value:
                plan.status = PlanStatus.FAILED.value
                plan.completed_at = time.time()
                self._emit("plan_failed", plan)
                return plan
        all_done = all(s.state in (StepState.COMPLETED.value, StepState.SKIPPED.value) for s in plan.steps)
        if all_done and plan.status == PlanStatus.RUNNING.value:
            plan.status = PlanStatus.COMPLETED.value
            plan.completed_at = time.time()
            self._emit("plan_completed", plan)
        return plan

    def cancel(self, plan_id: str) -> bool:
        with self._lock:
            plan = self._plans.get(plan_id)
        if plan:
            plan.status = PlanStatus.CANCELLED.value
            self._emit("plan_cancelled", plan)
            return True
        return False

    def get_status(self, plan_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            plan = self._plans.get(plan_id)
        return plan.to_dict() if plan else None

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _run_step(self, plan: OrchestrationPlan, step: OrchestrationStep) -> None:
        step.state = StepState.RUNNING.value
        step.started_at = time.time()
        self._emit("step_started", step)
        retry = 0
        while retry <= step.max_retries:
            try:
                result = self._spawn_fn(step.agent_role, step.task_description, step.context_data) if self._spawn_fn else None
                step.result = OrchestrationEngine._resolve_spawn_result(result)
                OrchestrationEngine._enforce_result_contract(step)
                step.state = StepState.COMPLETED.value
                step.completed_at = time.time()
                self._emit("step_completed", step)
                if self._shared_context and step.result:
                    self._shared_context.set_shared(
                        plan.session_id or plan.plan_id,
                        f"step_{step.step_id}_result",
                        step.result[:2000],
                        owner=step.agent_id or step.agent_role,
                    )
                return
            except Exception as e:
                retry += 1
                step.error = str(e)
                step.retry_count = retry
                if retry > step.max_retries:
                    step.state = StepState.FAILED.value
                    step.completed_at = time.time()
                    self._emit("step_failed", step)
                    return
                step.state = StepState.RETRYING.value
                self._emit("step_retry", step)

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass


class OrchestrationPlanner:
    DEPENDENCY_KEYWORDS = ["然后", "之后", "接着", "before", "after", "then", "依次", "顺序"]
    PARALLEL_KEYWORDS = ["同时", "并行", "一起", "parallel", "concurrently", "simultaneously"]
    HIERARCHY_KEYWORDS = ["分别", "各自", "分派", "decompose", "delegate", "分配给"]

    def plan_sequence(self, goal: str, tasks: List[Dict[str, Any]]) -> OrchestrationPlan:
        steps = []
        prev_id = ""
        for i, task in enumerate(tasks):
            step_id = "step_" + str(i + 1)
            deps = [prev_id] if prev_id else []
            steps.append(OrchestrationStep(
                step_id=step_id,
                agent_role=task.get("role", "backend"),
                task_description=task.get("description", ""),
                dependencies=deps,
                estimated_duration=task.get("estimated_duration", 30.0),
                max_retries=task.get("max_retries", 2),
                context_data=task.get("context_data", {}),
            ))
            prev_id = step_id
        return OrchestrationPlan(
            mode=OrchestrationMode.SEQUENCE.value,
            goal=goal,
            steps=steps,
        )

    def plan_parallel(self, goal: str, tasks: List[Dict[str, Any]]) -> OrchestrationPlan:
        steps = []
        for i, task in enumerate(tasks):
            steps.append(OrchestrationStep(
                step_id="step_" + str(i + 1),
                agent_role=task.get("role", "backend"),
                task_description=task.get("description", ""),
                dependencies=[],
                estimated_duration=task.get("estimated_duration", 30.0),
                max_retries=task.get("max_retries", 2),
                context_data=task.get("context_data", {}),
            ))
        return OrchestrationPlan(
            mode=OrchestrationMode.PARALLEL.value,
            goal=goal,
            steps=steps,
        )

    def plan_hierarchy(self, goal: str, parent_tasks: List[Dict[str, Any]],
                        child_map: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> OrchestrationPlan:
        steps = []
        child_map = child_map or {}
        for i, task in enumerate(parent_tasks):
            parent_id = "step_" + str(i + 1)
            parent_step = OrchestrationStep(
                step_id=parent_id,
                agent_role=task.get("role", "orchestrator"),
                task_description=task.get("description", ""),
                dependencies=[],
                estimated_duration=task.get("estimated_duration", 60.0),
            )
            child_tasks = child_map.get(parent_id, [])
            for j, child in enumerate(child_tasks):
                child_id = parent_id + "_child_" + str(j + 1)
                parent_step.children.append(child_id)
                steps.append(OrchestrationStep(
                    step_id=child_id,
                    agent_role=child.get("role", "backend"),
                    task_description=child.get("description", ""),
                    dependencies=[parent_id],
                    parent_step_id=parent_id,
                    estimated_duration=child.get("estimated_duration", 30.0),
                    max_retries=child.get("max_retries", 2),
                ))
            steps.append(parent_step)
        return OrchestrationPlan(
            mode=OrchestrationMode.HIERARCHY.value,
            goal=goal,
            steps=steps,
        )

    def auto_plan(self, goal: str, available_roles: Optional[List[str]] = None) -> OrchestrationPlan:
        from shared.role_system import get_role_manager
        rm = get_role_manager()
        matched = rm.route_task(goal)
        if not matched:
            matched = ["orchestrator"]
        if available_roles:
            matched = [r for r in matched if r in available_roles] or matched[:1]
        if len(matched) <= 1:
            tasks = [{"role": matched[0] if matched else "orchestrator", "description": goal}]
            return self.plan_sequence(goal, tasks)
        goal_lower = goal.lower()
        if any(kw in goal_lower for kw in self.HIERARCHY_KEYWORDS):
            parent_tasks = [{"role": "orchestrator", "description": "Decompose and delegate: " + goal}]
            child_map = {"step_1": [{"role": r, "description": f"Execute subtask for: {goal}"} for r in matched[:5]]}
            return self.plan_hierarchy(goal, parent_tasks, child_map)
        if any(kw in goal_lower for kw in self.PARALLEL_KEYWORDS):
            tasks = [{"role": r, "description": f"Parallel subtask for: {goal}"} for r in matched[:5]]
            return self.plan_parallel(goal, tasks)
        if any(kw in goal_lower for kw in self.DEPENDENCY_KEYWORDS):
            tasks = [{"role": r, "description": f"Sequential subtask for: {goal}"} for r in matched[:5]]
            return self.plan_sequence(goal, tasks)
        tasks = [{"role": r, "description": f"Subtask for: {goal}"} for r in matched[:5]]
        if len(tasks) > 2:
            return self.plan_parallel(goal, tasks)
        return self.plan_sequence(goal, tasks)


class OrchestrationEngine:
    """唯一权威编排内核。

    step.result 回写契约（禁止 v1 假闭环 — state=completed 但 result 为空）：
    ─────────────────────────────────────────────────────────────────
    1. spawn_fn 返回 dict → 取 content/reply 字段写入 step.result
    2. spawn_fn 返回 str  → 直接写入 step.result
    3. spawn_fn 返回 None → step.result = "" + 标注 "(spawn completed but returned empty)"
    4. 若 spawn_fn 返回含 file 路径 → _read_result_file() 读取落盘文件回写
    5. 严禁: step.state = completed 而 step.result 仍为 None（旧 v1 假闭环老毛病）

    对照 deepseeknova swarm.rs:
      step.result 回写 ≈ TaskResult::output 字段由 worker 执行完毕后必须填充，
      Worker::run() 产出 report_text / file_path → executor 读取并写入 TaskResult.output。
    """

    RESULT_WRITE_CONTRACT = (
        "step.result 必须在 step.state=completed 时非 None："
        "dict→取content/reply, str→直接写, None→空串+标注, "
        "file→_read_result_file读取。禁止 state=completed+result=None。"
    )

    def __init__(self, spawn_fn: Optional[Callable] = None, bus=None, shared_context=None):
        self._spawn_fn = spawn_fn
        self._bus = bus
        self._shared_context = shared_context
        self._planner = OrchestrationPlanner()
        self._orchestrators: Dict[str, OrchestratorBase] = {}
        self._plans: Dict[str, OrchestrationPlan] = {}
        self._lock = threading.Lock()
        self._callbacks: Dict[str, List[Callable]] = {}
        self._state_monitor = None

    def set_spawn_fn(self, spawn_fn: Callable) -> None:
        self._spawn_fn = spawn_fn

    def set_bus(self, bus) -> None:
        self._bus = bus

    def set_shared_context(self, ctx) -> None:
        self._shared_context = ctx

    def set_state_monitor(self, monitor) -> None:
        self._state_monitor = monitor

    @staticmethod
    def _read_result_file(file_path: str, max_chars: int = 2000) -> str:
        """读取落盘文件内容用于 step.result 回写。

        对照 swarm.rs: worker 产出 file_path → executor 调 fs::read_to_string 回填。
        """
        if not file_path or not os.path.isfile(file_path):
            return "(file unavailable: %s)" % file_path
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(max_chars)
        except Exception as e:
            return "(file read error: %s)" % e

    @staticmethod
    def _enforce_result_contract(step: OrchestrationStep) -> None:
        """强制回写契约：step.state=completed 时 step.result 不可为 None。

        若 result 仍为空，写入空串 + 标注，而非留 None（旧 v1 假闭环）。
        """
        if step.state in (StepState.COMPLETED.value,) and step.result is None:
            step.result = ""
            logger.warning("[OrchestrationEngine] 回写契约修正: step %s completed 但 result=None → 空串", step.step_id)
        if step.state == StepState.COMPLETED.value and not step.result:
            step.result = step.result or "(spawn completed but returned empty)"

    @staticmethod
    def _resolve_spawn_result(result: Any) -> str:
        """解析 spawn_fn 返回值，统一转为 step.result 字符串。

        回写契约核心逻辑：
        1. dict → 取 content/reply, 若含 file → 读取落盘文件
        2. str  → 直接写
        3. None → 空串（由 _enforce_result_contract 补标注）

        对照 swarm.rs: TaskResult::output = worker.run().into_output()
        """
        if result is None:
            return ""
        if isinstance(result, dict):
            file_path = result.get("file", "")
            if file_path and os.path.isfile(file_path):
                return OrchestrationEngine._read_result_file(file_path)
            content = result.get("content", result.get("reply", ""))
            if content:
                return str(content)
            return str(result)
        return str(result)

    def create_plan(self, goal: str, mode: str = OrchestrationMode.AUTO.value,
                     tasks: Optional[List[Dict[str, Any]]] = None,
                     available_roles: Optional[List[str]] = None) -> OrchestrationPlan:
        if mode == OrchestrationMode.AUTO.value:
            plan = self._planner.auto_plan(goal, available_roles)
        elif mode == OrchestrationMode.SEQUENCE.value and tasks:
            plan = self._planner.plan_sequence(goal, tasks)
        elif mode == OrchestrationMode.PARALLEL.value and tasks:
            plan = self._planner.plan_parallel(goal, tasks)
        elif mode == OrchestrationMode.HIERARCHY.value and tasks:
            plan = self._planner.plan_hierarchy(goal, tasks)
        else:
            plan = self._planner.auto_plan(goal, available_roles)
        plan.status = PlanStatus.READY.value
        with self._lock:
            self._plans[plan.plan_id] = plan
        self._emit("plan_created", plan)
        return plan

    def execute_plan(self, plan_id: str) -> Optional[OrchestrationPlan]:
        plan = self._plans.get(plan_id)
        if not plan or plan.status != PlanStatus.READY.value:
            return None
        orchestrator = self._get_orchestrator(plan.mode)
        if not orchestrator:
            return None
        with self._lock:
            self._orchestrators[plan_id] = orchestrator
        if self._state_monitor:
            self._state_monitor.start()
        self._emit("plan_executing", plan)
        result = orchestrator.execute(plan)
        self._emit("plan_done", result)
        return result

    def cancel_plan(self, plan_id: str) -> bool:
        orchestrator = self._orchestrators.get(plan_id)
        if orchestrator:
            return orchestrator.cancel(plan_id)
        return False

    def get_plan(self, plan_id: str) -> Optional[OrchestrationPlan]:
        return self._plans.get(plan_id)

    def get_plan_status(self, plan_id: str) -> Optional[Dict[str, Any]]:
        plan = self._plans.get(plan_id)
        if not plan:
            return None
        orchestrator = self._orchestrators.get(plan_id)
        if orchestrator:
            return orchestrator.get_status(plan_id)
        return plan.to_dict()

    def get_all_plans(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [p.to_dict() for p in self._plans.values()]

    def get_active_plans(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [p.to_dict() for p in self._plans.values() if p.status == PlanStatus.RUNNING.value]

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _get_orchestrator(self, mode: str) -> Optional[OrchestratorBase]:
        if mode == OrchestrationMode.SEQUENCE.value:
            return SequenceOrchestrator(self._spawn_fn, self._bus, self._shared_context)
        elif mode == OrchestrationMode.PARALLEL.value:
            return ParallelOrchestrator(self._spawn_fn, self._bus, self._shared_context)
        elif mode == OrchestrationMode.HIERARCHY.value:
            return HierarchyOrchestrator(self._spawn_fn, self._bus, self._shared_context)
        logger.warning("[OrchestrationEngine] Unknown mode: %s, falling back to sequence", mode)
        return SequenceOrchestrator(self._spawn_fn, self._bus, self._shared_context)

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass


_global_engine: Optional[OrchestrationEngine] = None
_engine_lock = threading.Lock()


def get_orchestration_engine() -> OrchestrationEngine:
    global _global_engine
    if _global_engine is None:
        with _engine_lock:
            if _global_engine is None:
                _global_engine = OrchestrationEngine()
    return _global_engine


def get_orchestration_planner() -> OrchestrationPlanner:
    return OrchestrationPlanner()


_DEPRECATED_V2_COMPAT = {
    "OrchestrationMode": OrchestrationMode,
    "StepState": StepState,
    "OrchestrationStep": OrchestrationStep,
    "OrchestrationPlan": OrchestrationPlan,
    "OrchestrationPlanner": OrchestrationPlanner,
    "OrchestrationExecutor": type("OrchestrationExecutor", (object,), {
        "__init__": lambda self, **kw: None,
        "create_plan": lambda self, plan: get_orchestration_engine().create_plan(
            plan.goal, plan.mode),
        "execute": lambda self, plan_id: get_orchestration_engine().execute_plan(plan_id),
        "cancel": lambda self, plan_id: get_orchestration_engine().cancel_plan(plan_id),
        "get_plan": lambda self, plan_id: get_orchestration_engine().get_plan(plan_id),
    }),
    "get_orchestration_planner": get_orchestration_planner,
    "get_orchestration_executor": lambda: get_orchestration_engine(),
}


_DEPRECATED_SERVICE_COMPAT = {
    "AgentOrchestratorService": type("AgentOrchestratorService", (object,), {
        "__init__": lambda self: None,
        "dispatch": lambda self, *a, **kw: None,
        "collect": lambda self, *a, **kw: None,
        "cancel": lambda self, *a, **kw: {"status": "deprecated"},
    }),
}
