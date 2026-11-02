from __future__ import annotations

import heapq
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from bridge.core.permission import PLAN_APPROVAL_REQUIRED, PLAN_PROGRESS_UPDATED


class PlanStatus(Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GOAPActionStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorldState:
    facts: Dict[str, Any] = field(default_factory=dict)

    def satisfies(self, preconditions: Dict[str, Any]) -> bool:
        for key, value in preconditions.items():
            if key not in self.facts:
                return False
            if isinstance(value, set):
                if not isinstance(self.facts[key], set):
                    return False
                if not value.issubset(self.facts[key]):
                    return False
            elif self.facts[key] != value:
                return False
        return True

    def apply(self, effects: Dict[str, Any]) -> "WorldState":
        new_facts = dict(self.facts)
        for key, value in effects.items():
            if isinstance(value, dict):
                if key in new_facts and isinstance(new_facts[key], dict):
                    new_facts[key] = dict(new_facts[key])
                    new_facts[key].update(value)
                else:
                    new_facts[key] = dict(value)
            elif isinstance(value, set):
                if key in new_facts and isinstance(new_facts[key], set):
                    new_facts[key] = self.facts[key] | value
                else:
                    new_facts[key] = set(value)
            else:
                new_facts[key] = value
        return WorldState(facts=new_facts)

    def copy(self) -> "WorldState":
        return WorldState(facts=dict(self.facts))

    def heuristic_distance(self, goal: "WorldState") -> int:
        distance = 0
        for key, value in goal.facts.items():
            if key not in self.facts:
                distance += 1
            elif isinstance(value, set) and isinstance(self.facts[key], set):
                missing = value - self.facts[key]
                distance += len(missing)
            elif self.facts[key] != value:
                distance += 1
        return distance


@dataclass
class GOAPAction:
    name: str
    description: str = ""
    preconditions: Dict[str, Any] = field(default_factory=dict)
    effects: Dict[str, Any] = field(default_factory=dict)
    cost: float = 1.0
    skill_name: str = ""
    skill_args: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def is_available(self, state: WorldState) -> bool:
        return state.satisfies(self.preconditions)

    def execute_effects(self, state: WorldState) -> WorldState:
        return state.apply(self.effects)


@dataclass
class PlanStep:
    id: int
    description: str
    tool_suggestion: str = ""
    status: str = "pending"
    result: Optional[str] = None
    duration: float = 0.0
    goap_action: Optional[str] = None
    started_at: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "description": self.description,
            "tool_suggestion": self.tool_suggestion,
            "status": self.status,
            "result": self.result,
            "duration": self.duration,
            "goap_action": self.goap_action,
            "started_at": self.started_at,
            "error": self.error,
        }


@dataclass
class AgentPlan:
    user_request: str
    steps: List[PlanStep]
    status: PlanStatus = PlanStatus.DRAFT
    created_at: float = field(default_factory=time.time)
    approved_at: Optional[float] = None
    completed_at: Optional[float] = None
    current_step: int = 0
    plan_id: str = ""
    goal_state: Optional[WorldState] = None

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = "plan_" + uuid.uuid4().hex[:8]

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps if s.status == "completed")
        return completed / len(self.steps)

    @property
    def is_complete(self) -> bool:
        return self.status == PlanStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == PlanStatus.FAILED

    @property
    def estimated_remaining(self) -> float:
        completed_durations = [s.duration for s in self.steps if s.status == "completed" and s.duration > 0]
        if not completed_durations:
            return 0.0
        avg = sum(completed_durations) / len(completed_durations)
        remaining = sum(1 for s in self.steps if s.status == "pending")
        return avg * remaining

    def approve(self):
        self.status = PlanStatus.APPROVED
        self.approved_at = time.time()

    def start_execution(self):
        self.status = PlanStatus.EXECUTING

    def pause(self):
        if self.status == PlanStatus.EXECUTING:
            self.status = PlanStatus.PAUSED

    def resume(self):
        if self.status == PlanStatus.PAUSED:
            self.status = PlanStatus.EXECUTING

    def complete_step(self, step_id: int, result: str, duration: float = 0):
        for step in self.steps:
            if step.id == step_id:
                step.status = "completed"
                step.result = result
                step.duration = duration
                break
        self._check_completion()

    def fail_step(self, step_id: int, error: str):
        for step in self.steps:
            if step.id == step_id:
                step.status = "failed"
                step.error = error
                step.result = error
                break
        self.status = PlanStatus.FAILED

    def skip_step(self, step_id: int, reason: str):
        for step in self.steps:
            if step.id == step_id:
                step.status = "skipped"
                step.result = "Skipped: " + reason
                break
        self._check_completion()

    def get_next_step(self) -> Optional[PlanStep]:
        for step in self.steps:
            if step.status == "pending":
                return step
        return None

    def _check_completion(self):
        all_done = all(s.status in ("completed", "skipped") for s in self.steps)
        if all_done:
            self.status = PlanStatus.COMPLETED
            self.completed_at = time.time()

    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "user_request": self.user_request,
            "status": self.status.value,
            "progress": round(self.progress, 2),
            "estimated_remaining": round(self.estimated_remaining, 1),
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "completed_at": self.completed_at,
        }


_PLANS_DIR = os.path.join(os.path.expanduser("~"), ".lemoncode", "data", "plans")
_MAX_SEARCH_DEPTH = 20
_SEARCH_TIMEOUT_SECONDS = 5.0
_MAX_REPLAN_COUNT = 3


class GOAPPlanner:
    def __init__(self):
        self._actions: Dict[str, GOAPAction] = {}
        self._register_default_actions()

    def _register_default_actions(self) -> None:
        defaults = [
            GOAPAction(name="scan_project", description="扫描项目目录结构", preconditions={}, effects={"project_scanned": True}, cost=1.0, skill_name="scan_project", tags=["analysis"]),
            GOAPAction(name="read_key_files", description="读取关键配置和入口文件", preconditions={"project_scanned": True}, effects={"key_files_read": True}, cost=1.5, skill_name="batch_read_files", tags=["analysis"]),
            GOAPAction(name="identify_tech_stack", description="识别技术栈和依赖", preconditions={"key_files_read": True}, effects={"tech_stack_identified": True}, cost=1.0, skill_name="file_search", tags=["analysis"]),
            GOAPAction(name="analyze_architecture", description="分析核心架构和模块关系", preconditions={"tech_stack_identified": True}, effects={"architecture_analyzed": True}, cost=2.0, skill_name="file_read", tags=["analysis"]),
            GOAPAction(name="generate_report", description="生成结构化分析报告", preconditions={"architecture_analyzed": True}, effects={"report_generated": True}, cost=1.0, skill_name="llm_summary", tags=["synthesis"]),
            GOAPAction(name="locate_problem", description="定位问题代码", preconditions={}, effects={"problem_located": True}, cost=1.5, skill_name="file_search", tags=["debug"]),
            GOAPAction(name="analyze_root_cause", description="分析根本原因", preconditions={"problem_located": True}, effects={"root_cause_analyzed": True}, cost=2.0, skill_name="file_read", tags=["debug"]),
            GOAPAction(name="formulate_fix", description="制定修复方案", preconditions={"root_cause_analyzed": True}, effects={"fix_formulated": True}, cost=1.5, skill_name="llm_analysis", tags=["fix"]),
            GOAPAction(name="execute_fix", description="执行修复", preconditions={"fix_formulated": True}, effects={"fix_executed": True}, cost=2.0, skill_name="edit_file", tags=["fix"]),
            GOAPAction(name="verify_fix", description="验证修复结果", preconditions={"fix_executed": True}, effects={"fix_verified": True}, cost=1.5, skill_name="execute_code", tags=["verify"]),
            GOAPAction(name="search_documentation", description="搜索相关文档和API", preconditions={}, effects={"docs_searched": True}, cost=1.0, skill_name="search_web", tags=["research"]),
            GOAPAction(name="read_documentation", description="阅读文档内容", preconditions={"docs_searched": True}, effects={"docs_read": True}, cost=1.5, skill_name="fetch_url", tags=["research"]),
            GOAPAction(name="create_file", description="创建新文件", preconditions={}, effects={"file_created": True}, cost=2.0, skill_name="write_file", tags=["create"]),
            GOAPAction(name="write_tests", description="编写测试用例", preconditions={"file_created": True}, effects={"tests_written": True}, cost=2.0, skill_name="write_file", tags=["test"]),
            GOAPAction(name="run_tests", description="运行测试验证", preconditions={"tests_written": True}, effects={"tests_passed": True}, cost=1.5, skill_name="execute_code", tags=["test"]),
            GOAPAction(name="search_code", description="搜索代码中的关键词和模式", preconditions={}, effects={"code_searched": True}, cost=1.0, skill_name="code_search", tags=["search"]),
            GOAPAction(name="search_files", description="搜索项目文件", preconditions={}, effects={"files_searched": True}, cost=1.0, skill_name="file_search", tags=["search"]),
            GOAPAction(name="read_file", description="读取文件内容", preconditions={}, effects={"file_read": True}, cost=1.0, skill_name="file_read", tags=["read"]),
            GOAPAction(name="batch_read_files", description="批量读取多个文件", preconditions={"files_searched": True}, effects={"files_read": True}, cost=1.5, skill_name="batch_read_files", tags=["read"]),
            GOAPAction(name="edit_file", description="编辑已有文件", preconditions={"file_read": True}, effects={"file_edited": True}, cost=2.0, skill_name="edit_file", tags=["modify"]),
            GOAPAction(name="modify_code", description="修改代码实现", preconditions={"code_searched": True}, effects={"code_modified": True}, cost=2.0, skill_name="edit_file", tags=["modify"]),
            GOAPAction(name="refactor_code", description="重构代码结构", preconditions={"architecture_analyzed": True}, effects={"code_refactored": True}, cost=3.0, skill_name="edit_file", tags=["modify"]),
            GOAPAction(name="delete_file", description="删除文件", preconditions={}, effects={"file_deleted": True}, cost=2.5, skill_name="file_delete", tags=["delete"]),
            GOAPAction(name="execute_code", description="执行代码或脚本", preconditions={}, effects={"code_executed": True}, cost=1.5, skill_name="execute_code", tags=["execute"]),
            GOAPAction(name="run_linter", description="运行代码检查工具", preconditions={"project_scanned": True}, effects={"lint_completed": True}, cost=1.5, skill_name="execute_code", tags=["execute"]),
            GOAPAction(name="run_build", description="运行构建命令", preconditions={"code_modified": True}, effects={"build_completed": True}, cost=2.5, skill_name="execute_code", tags=["execute"]),
            GOAPAction(name="install_dependency", description="安装项目依赖", preconditions={}, effects={"dependency_installed": True}, cost=1.5, skill_name="execute_code", tags=["execute"]),
            GOAPAction(name="search_web", description="搜索网络信息", preconditions={}, effects={"web_searched": True}, cost=1.0, skill_name="search_web", tags=["research"]),
            GOAPAction(name="fetch_url", description="获取URL内容", preconditions={"web_searched": True}, effects={"url_fetched": True}, cost=1.0, skill_name="fetch_url", tags=["research"]),
            GOAPAction(name="analyze_dependencies", description="分析依赖关系图", preconditions={"key_files_read": True}, effects={"dependencies_analyzed": True}, cost=2.0, skill_name="file_read", tags=["analysis"]),
            GOAPAction(name="analyze_performance", description="分析性能瓶颈", preconditions={"code_executed": True}, effects={"performance_analyzed": True}, cost=2.0, skill_name="llm_analysis", tags=["analysis"]),
            GOAPAction(name="generate_documentation", description="生成代码文档", preconditions={"architecture_analyzed": True}, effects={"docs_generated": True}, cost=2.0, skill_name="llm_summary", tags=["synthesis"]),
            GOAPAction(name="review_code", description="代码审查", preconditions={"file_read": True}, effects={"code_reviewed": True}, cost=2.0, skill_name="llm_analysis", tags=["review"]),
            GOAPAction(name="validate_changes", description="验证变更是否正确", preconditions={"code_modified": True}, effects={"changes_validated": True}, cost=1.5, skill_name="execute_code", tags=["verify"]),
        ]
        for action in defaults:
            self._actions[action.name] = action

    def register_action(self, action: GOAPAction) -> None:
        self._actions[action.name] = action

    def unregister_action(self, name: str) -> bool:
        if name in self._actions:
            del self._actions[name]
            return True
        return False

    def plan(self, initial_state: WorldState, goal_state: WorldState,
             available_actions: Optional[List[str]] = None) -> List[GOAPAction]:
        actions_pool = list(self._actions.values())
        if available_actions:
            action_set = set(available_actions)
            actions_pool = [a for a in actions_pool if a.name in action_set]

        result = self._a_star_search(initial_state, goal_state, actions_pool)
        return result

    def _a_star_search(self, initial: WorldState, goal: WorldState,
                       actions: List[GOAPAction], max_iterations: int = 1000) -> List[GOAPAction]:
        counter = 0
        open_set: List[Tuple[float, int, WorldState, List[GOAPAction]]] = []
        initial_h = initial.heuristic_distance(goal)
        heapq.heappush(open_set, (initial_h, counter, initial, []))
        closed_states: Set[str] = set()
        counter += 1
        iterations = 0
        start_time = time.time()

        while open_set and iterations < max_iterations:
            iterations += 1
            if time.time() - start_time > _SEARCH_TIMEOUT_SECONDS:
                break
            f, _, current_state, path = heapq.heappop(open_set)
            if len(path) >= _MAX_SEARCH_DEPTH:
                continue

            state_key = self._state_key(current_state)
            if state_key in closed_states:
                continue
            closed_states.add(state_key)

            if current_state.satisfies(goal.facts):
                return path

            for action in actions:
                if not action.is_available(current_state):
                    continue
                new_state = action.execute_effects(current_state)
                new_key = self._state_key(new_state)
                if new_key in closed_states:
                    continue
                g = len(path) + 1 + action.cost
                h = new_state.heuristic_distance(goal)
                new_path = path + [action]
                heapq.heappush(open_set, (g + h, counter, new_state, new_path))
                counter += 1

        if open_set:
            best_path = min(open_set, key=lambda x: x[0])
            return best_path[3]
        return []

    def _state_key(self, state: WorldState) -> str:
        items = sorted(state.facts.items())
        return json.dumps(items, sort_keys=True, default=str)

    def parse_goal(self, natural_language_goal: str) -> WorldState:
        goal = WorldState(facts={})
        goal_lower = natural_language_goal.lower()
        if any(kw in goal_lower for kw in ["分析", "analysis", "analyze", "了解", "scan"]):
            goal.facts["report_generated"] = True
        if any(kw in goal_lower for kw in ["修复", "fix", "修复bug", "bug", "debug", "解决"]):
            goal.facts["fix_verified"] = True
        if any(kw in goal_lower for kw in ["创建", "create", "新建", "build", "搭建", "开发"]):
            goal.facts["file_created"] = True
            if any(kw in goal_lower for kw in ["测试", "test"]):
                goal.facts["tests_passed"] = True
        if any(kw in goal_lower for kw in ["调研", "research", "文档", "doc"]):
            goal.facts["docs_read"] = True
        if any(kw in goal_lower for kw in ["修改", "modify", "编辑", "edit", "更新", "update", "重构", "refactor"]):
            goal.facts["code_modified"] = True
            if any(kw in goal_lower for kw in ["测试", "test", "验证", "verify"]):
                goal.facts["changes_validated"] = True
        if not goal.facts:
            goal.facts["report_generated"] = True
        return goal

    def generate_plan(self, user_request: str, initial_state: Optional[WorldState] = None,
                      available_actions: Optional[List[str]] = None) -> AgentPlan:
        if initial_state is None:
            initial_state = WorldState(facts={})
        goal = self.parse_goal(user_request)
        action_sequence = self.plan(initial_state, goal, available_actions)

        steps = []
        for i, action in enumerate(action_sequence):
            steps.append(PlanStep(
                id=i + 1,
                description=action.description,
                tool_suggestion=action.skill_name,
                goap_action=action.name,
            ))

        plan = AgentPlan(
            user_request=user_request,
            steps=steps,
            status=PlanStatus.DRAFT,
            goal_state=goal,
        )
        return plan


class PlanGenerator:
    _planner = GOAPPlanner()

    @staticmethod
    def generate_project_analysis_plan(user_request: str, project_path: str = "") -> AgentPlan:
        initial = WorldState(facts={"project_scanned": False})
        goal = WorldState(facts={"report_generated": True})
        action_sequence = PlanGenerator._planner.plan(initial, goal)
        steps = [
            PlanStep(id=i + 1, description=a.description, tool_suggestion=a.skill_name, goap_action=a.name)
            for i, a in enumerate(action_sequence)
        ]
        return AgentPlan(user_request=user_request, steps=steps, goal_state=goal)

    @staticmethod
    def generate_code_fix_plan(user_request: str, file_path: str = "") -> AgentPlan:
        initial = WorldState(facts={})
        goal = WorldState(facts={"fix_verified": True})
        action_sequence = PlanGenerator._planner.plan(initial, goal)
        steps = [
            PlanStep(id=i + 1, description=a.description, tool_suggestion=a.skill_name, goap_action=a.name)
            for i, a in enumerate(action_sequence)
        ]
        return AgentPlan(user_request=user_request, steps=steps, goal_state=goal)

    @staticmethod
    def generate_custom_plan(user_request: str, steps_description: List[str]) -> AgentPlan:
        steps = [
            PlanStep(id=i + 1, description=desc, tool_suggestion="auto")
            for i, desc in enumerate(steps_description)
        ]
        return AgentPlan(user_request=user_request, steps=steps)

    @staticmethod
    def generate_goap_plan(user_request: str, initial_state: Optional[WorldState] = None) -> AgentPlan:
        return PlanGenerator._planner.generate_plan(user_request, initial_state)


class PlanExecutor:
    def __init__(self):
        self._plans: Dict[str, AgentPlan] = {}
        self._current_plan_id: Optional[str] = None
        self._lock = threading.Lock()
        self._callbacks: Dict[str, List[Callable]] = {}
        self._replan_counts: Dict[str, int] = {}

    def create_plan(self, plan: AgentPlan) -> str:
        plan_id = plan.plan_id
        with self._lock:
            self._plans[plan_id] = plan
            plan.status = PlanStatus.PENDING
            self._replan_counts[plan_id] = 0
        self._emit("plan_created", plan)
        self._emit(PLAN_APPROVAL_REQUIRED, plan)
        self._persist_plan(plan_id)
        return plan_id

    def get_plan(self, plan_id: str) -> Optional[AgentPlan]:
        return self._plans.get(plan_id)

    def approve_plan(self, plan_id: str) -> bool:
        plan = self._plans.get(plan_id)
        if plan and plan.status == PlanStatus.PENDING:
            plan.approve()
            self._emit("plan_approved", plan)
            self._persist_plan(plan_id)
            return True
        return False

    def reject_plan(self, plan_id: str, reason: str = "") -> bool:
        plan = self._plans.get(plan_id)
        if plan and plan.status == PlanStatus.PENDING:
            plan.status = PlanStatus.CANCELLED
            self._emit("plan_rejected", plan)
            self._persist_plan(plan_id)
            return True
        return False

    def edit_plan_steps(self, plan_id: str, steps: List[PlanStep]) -> bool:
        plan = self._plans.get(plan_id)
        if plan and plan.status in (PlanStatus.PENDING, PlanStatus.DRAFT):
            plan.steps = steps
            self._emit("plan_edited", plan)
            self._persist_plan(plan_id)
            return True
        return False

    def edit_step(self, plan_id: str, step_id: int, description: str = "",
                  tool_suggestion: str = "") -> bool:
        plan = self._plans.get(plan_id)
        if not plan or plan.status not in (PlanStatus.PENDING, PlanStatus.DRAFT):
            return False
        for step in plan.steps:
            if step.id == step_id:
                if description:
                    step.description = description
                if tool_suggestion:
                    step.tool_suggestion = tool_suggestion
                self._emit("plan_edited", plan)
                self._persist_plan(plan_id)
                return True
        return False

    def delete_step(self, plan_id: str, step_id: int) -> bool:
        plan = self._plans.get(plan_id)
        if not plan or plan.status not in (PlanStatus.PENDING, PlanStatus.DRAFT):
            return False
        plan.steps = [s for s in plan.steps if s.id != step_id]
        for i, step in enumerate(plan.steps):
            step.id = i + 1
        self._emit("plan_edited", plan)
        self._persist_plan(plan_id)
        return True

    def reorder_steps(self, plan_id: str, step_ids_in_order: List[int]) -> bool:
        plan = self._plans.get(plan_id)
        if not plan or plan.status not in (PlanStatus.PENDING, PlanStatus.DRAFT):
            return False
        step_map = {s.id: s for s in plan.steps}
        reordered = []
        for new_idx, sid in enumerate(step_ids_in_order):
            if sid in step_map:
                step_map[sid].id = new_idx + 1
                reordered.append(step_map[sid])
        for sid, step in step_map.items():
            if step not in reordered:
                step.id = len(reordered) + 1
                reordered.append(step)
        plan.steps = reordered
        self._emit("plan_edited", plan)
        self._persist_plan(plan_id)
        return True

    def start_execution(self, plan_id: str) -> bool:
        plan = self._plans.get(plan_id)
        if plan and plan.status == PlanStatus.APPROVED:
            plan.start_execution()
            self._current_plan_id = plan_id
            self._emit("plan_execution_started", plan)
            self._start_next_step(plan)
            self._persist_plan(plan_id)
            return True
        return False

    def pause_execution(self, plan_id: str) -> bool:
        plan = self._plans.get(plan_id)
        if plan:
            plan.pause()
            self._emit("plan_paused", plan)
            self._persist_plan(plan_id)
            return True
        return False

    def resume_execution(self, plan_id: str) -> bool:
        plan = self._plans.get(plan_id)
        if plan:
            plan.resume()
            self._emit("plan_resumed", plan)
            self._start_next_step(plan)
            self._persist_plan(plan_id)
            return True
        return False

    def complete_step(self, plan_id: str, step_id: int, result: str, duration: float = 0) -> None:
        plan = self._plans.get(plan_id)
        if plan:
            plan.complete_step(step_id, result, duration)
            self._emit("step_completed", plan)
            self._emit(PLAN_PROGRESS_UPDATED, plan)
            self._start_next_step(plan)
            self._persist_plan(plan_id)

    def fail_step(self, plan_id: str, step_id: int, error: str) -> None:
        plan = self._plans.get(plan_id)
        if plan:
            plan.fail_step(step_id, error)
            self._emit("step_failed", plan)
            self._persist_plan(plan_id)

    def _start_next_step(self, plan: AgentPlan) -> None:
        if plan.status != PlanStatus.EXECUTING:
            return
        next_step = plan.get_next_step()
        if next_step:
            next_step.status = "executing"
            next_step.started_at = time.time()

    def replan(self, plan_id: str, failed_step_id: int, error: str) -> Optional[AgentPlan]:
        plan = self._plans.get(plan_id)
        if not plan:
            return None
        current_replan = self._replan_counts.get(plan_id, 0)
        if current_replan >= _MAX_REPLAN_COUNT:
            plan.status = PlanStatus.FAILED
            self._emit("plan_failed_max_replan", plan)
            self._persist_plan(plan_id)
            return None
        failed_idx = None
        for i, step in enumerate(plan.steps):
            if step.id == failed_step_id:
                failed_idx = i
                break
        if failed_idx is None:
            return None
        completed_steps = plan.steps[:failed_idx]
        completed_desc = [s.description for s in completed_steps if s.status == "completed"]
        remaining_desc = [s.description for s in plan.steps[failed_idx:]]
        new_plan = PlanGenerator.generate_custom_plan(
            "重规划: " + plan.user_request + " (原因: " + error + ")",
            remaining_desc,
        )
        new_plan.status = PlanStatus.PENDING
        self._plans[new_plan.plan_id] = new_plan
        self._replan_counts[new_plan.plan_id] = current_replan + 1
        self._emit("plan_replanned", new_plan)
        self._emit(PLAN_APPROVAL_REQUIRED, new_plan)
        self._persist_plan(new_plan.plan_id)
        return new_plan

    def get_active_plan(self) -> Optional[AgentPlan]:
        if self._current_plan_id:
            return self._plans.get(self._current_plan_id)
        return None

    def get_all_plans(self) -> List[Dict]:
        return [
            {
                "id": pid,
                "request": plan.user_request[:50],
                "status": plan.status.value,
                "progress": round(plan.progress, 2),
                "steps": len(plan.steps),
                "estimated_remaining": round(plan.estimated_remaining, 1),
            }
            for pid, plan in self._plans.items()
        ]

    def load_plan(self, plan_id: str) -> Optional[AgentPlan]:
        plan_path = os.path.join(_PLANS_DIR, plan_id + ".json")
        if not os.path.exists(plan_path):
            return None
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            steps = [
                PlanStep(
                    id=s["id"],
                    description=s.get("description", ""),
                    tool_suggestion=s.get("tool_suggestion", ""),
                    status=s.get("status", "pending"),
                    result=s.get("result"),
                    duration=s.get("duration", 0.0),
                    goap_action=s.get("goap_action"),
                    started_at=s.get("started_at"),
                    error=s.get("error"),
                )
                for s in data.get("steps", [])
            ]
            plan = AgentPlan(
                user_request=data.get("user_request", ""),
                steps=steps,
                status=PlanStatus(data.get("status", "draft")),
                created_at=data.get("created_at", time.time()),
                approved_at=data.get("approved_at"),
                completed_at=data.get("completed_at"),
                current_step=data.get("current_step", 0),
                plan_id=plan_id,
            )
            self._plans[plan_id] = plan
            return plan
        except Exception:
            return None

    def _persist_plan(self, plan_id: str) -> None:
        plan = self._plans.get(plan_id)
        if not plan:
            return
        os.makedirs(_PLANS_DIR, exist_ok=True)
        plan_path = os.path.join(_PLANS_DIR, plan_id + ".json")
        try:
            with open(plan_path, "w", encoding="utf-8") as f:
                json.dump(plan.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def on(self, event_name: str, callback: Callable) -> None:
        if event_name not in self._callbacks:
            self._callbacks[event_name] = []
        self._callbacks[event_name].append(callback)

    def _emit(self, event_name: str, data: Any) -> None:
        for cb in self._callbacks.get(event_name, []):
            try:
                cb(data)
            except Exception:
                pass


_generator = PlanGenerator()
_executor = PlanExecutor()


def get_plan_generator() -> PlanGenerator:
    return _generator


def get_plan_executor() -> PlanExecutor:
    return _executor


def get_goap_planner() -> GOAPPlanner:
    return PlanGenerator._planner


class GOAPAgentLoopIntegration:
    def __init__(self, plan_executor: Optional[PlanExecutor] = None):
        self._executor = plan_executor or get_plan_executor()
        self._planner = get_goap_planner()
        self._goap_mode = False
        self._current_plan_id: Optional[str] = None

    @property
    def is_goap_mode(self) -> bool:
        return self._goap_mode

    def enable_goap_mode(self) -> None:
        self._goap_mode = True

    def disable_goap_mode(self) -> None:
        self._goap_mode = False

    def process_request(self, user_request: str) -> Optional[AgentPlan]:
        if not self._goap_mode:
            return None
        plan = self._planner.generate_plan(user_request)
        self._current_plan_id = self._executor.create_plan(plan)
        return plan

    def approve_current_plan(self) -> bool:
        if not self._current_plan_id:
            return False
        return self._executor.approve_plan(self._current_plan_id)

    def reject_current_plan(self, reason: str = "") -> bool:
        if not self._current_plan_id:
            return False
        return self._executor.reject_plan(self._current_plan_id, reason)

    def start_current_plan(self) -> bool:
        if not self._current_plan_id:
            return False
        return self._executor.start_execution(self._current_plan_id)

    def pause_current_plan(self) -> bool:
        if not self._current_plan_id:
            return False
        return self._executor.pause_execution(self._current_plan_id)

    def resume_current_plan(self) -> bool:
        if not self._current_plan_id:
            return False
        return self._executor.resume_execution(self._current_plan_id)

    def get_current_step(self) -> Optional[PlanStep]:
        plan = self._executor.get_plan(self._current_plan_id or "")
        if plan:
            return plan.get_next_step()
        return None

    def report_step_result(self, step_id: int, success: bool, result: str = "", duration: float = 0) -> None:
        if not self._current_plan_id:
            return
        if success:
            self._executor.complete_step(self._current_plan_id, step_id, result, duration)
        else:
            self._executor.fail_step(self._current_plan_id, step_id, result)
            self._executor.replan(self._current_plan_id, step_id, result)

    def get_current_plan(self) -> Optional[AgentPlan]:
        if not self._current_plan_id:
            return None
        return self._executor.get_plan(self._current_plan_id)

    def on_plan_event(self, event_name: str, callback: Callable) -> None:
        self._executor.on(event_name, callback)


_integration: Optional[GOAPAgentLoopIntegration] = None


def get_goap_integration() -> GOAPAgentLoopIntegration:
    global _integration
    if _integration is None:
        _integration = GOAPAgentLoopIntegration()
    return _integration


_DECOMPOSE_SYSTEM_PROMPT = (
    "你是一个任务分解专家。给定用户请求和可用动作列表，将请求分解为有序的GOAP动作序列。"
    "只输出JSON数组，每个元素包含 name(动作名) 和 reason(选择理由)。"
    "不要输出任何其他文字。"
)


class LLMActionDecomposer:
    def __init__(self, engine_manager=None):
        self._engine_manager = engine_manager
        self._planner = GOAPPlanner()

    def set_engine_manager(self, engine_manager) -> None:
        self._engine_manager = engine_manager

    def decompose(self, user_request: str, available_actions: Optional[List[str]] = None) -> List[GOAPAction]:
        if self._engine_manager is None:
            return self._fallback_decompose(user_request, available_actions)
        try:
            return self._llm_decompose(user_request, available_actions)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("[LLMActionDecomposer] LLM分解失败，回退规则分解: %s", e)
            return self._fallback_decompose(user_request, available_actions)

    def _llm_decompose(self, user_request: str, available_actions: Optional[List[str]]) -> List[GOAPAction]:
        actions_pool = list(self._planner._actions.values())
        if available_actions:
            action_set = set(available_actions)
            actions_pool = [a for a in actions_pool if a.name in action_set]
        action_descriptions = "\n".join(
            f"- {a.name}: {a.description} (前提: {a.preconditions}, 效果: {a.effects})"
            for a in actions_pool
        )
        user_msg = (
            f"用户请求: {user_request}\n\n"
            f"可用动作:\n{action_descriptions}\n\n"
            f"请输出有序的JSON动作序列，格式: [{{\"name\": \"action_name\", \"reason\": \"...\"}}]"
        )
        messages = [
            {"role": "system", "content": _DECOMPOSE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        response = self._engine_manager.chat(messages, engine_name="ollama")
        if isinstance(response, dict):
            content = response.get("content", "")
        else:
            content = str(response)
        action_names = self._parse_action_list(content, actions_pool)
        if not action_names:
            return self._fallback_decompose(user_request, available_actions)
        result = []
        for name in action_names:
            action = self._planner._actions.get(name)
            if action:
                result.append(action)
        if not result:
            return self._fallback_decompose(user_request, available_actions)
        return result

    def _parse_action_list(self, content: str, actions_pool: List[GOAPAction]) -> List[str]:
        import re as _re
        json_match = _re.search(r'\[.*\]', content, _re.DOTALL)
        if not json_match:
            return []
        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        names = []
        known = {a.name for a in actions_pool}
        for item in parsed:
            if isinstance(item, dict):
                name = item.get("name", "")
            elif isinstance(item, str):
                name = item
            else:
                continue
            if name in known:
                names.append(name)
        return names

    def _fallback_decompose(self, user_request: str, available_actions: Optional[List[str]]) -> List[GOAPAction]:
        initial = WorldState(facts={})
        goal = self._planner.parse_goal(user_request)
        return self._planner.plan(initial, goal, available_actions)


class AdaptiveReplanner:
    def __init__(self, planner: Optional[GOAPPlanner] = None, decomposer: Optional[LLMActionDecomposer] = None):
        self._planner = planner or GOAPPlanner()
        self._decomposer = decomposer or LLMActionDecomposer()
        self._replan_history: List[Dict[str, Any]] = []
        self._max_replan = 5

    def replan_from_failure(
        self,
        user_request: str,
        failed_action: str,
        failure_reason: str,
        completed_actions: List[str],
        current_state: WorldState,
    ) -> Optional[AgentPlan]:
        history_count = sum(1 for h in self._replan_history if h.get("request") == user_request)
        if history_count >= self._max_replan:
            return None
        self._replan_history.append({
            "request": user_request,
            "failed_action": failed_action,
            "failure_reason": failure_reason,
            "completed_actions": list(completed_actions),
            "timestamp": time.time(),
        })
        new_facts = dict(current_state.facts)
        new_facts[f"_failed_{failed_action}"] = True
        new_facts[f"_fail_reason_{failed_action}"] = failure_reason[:200]
        for action_name in completed_actions:
            action = self._planner._actions.get(action_name)
            if action:
                new_state = WorldState(facts=new_facts)
                if action.is_available(new_state):
                    new_facts = action.execute_effects(WorldState(facts=new_facts)).facts
        new_initial = WorldState(facts=new_facts)
        goal = self._planner.parse_goal(user_request)
        available = [
            a.name for a in self._planner._actions.values()
            if a.name != failed_action
        ]
        action_sequence = self._planner.plan(new_initial, goal, available)
        if not action_sequence:
            try:
                action_sequence = self._decomposer.decompose(
                    f"{user_request} (注意: {failed_action}已失败，原因: {failure_reason})",
                    available,
                )
            except Exception:
                return None
        if not action_sequence:
            return None
        steps = []
        for i, action in enumerate(action_sequence):
            steps.append(PlanStep(
                id=i + 1,
                description=f"[重规划] {action.description}",
                tool_suggestion=action.skill_name,
                goap_action=action.name,
                status="pending",
            ))
        plan = AgentPlan(
            user_request=f"重规划: {user_request} (跳过失败的{failed_action})",
            steps=steps,
            status=PlanStatus.DRAFT,
            goal_state=goal,
        )
        return plan

    def get_replan_count(self, user_request: str) -> int:
        return sum(1 for h in self._replan_history if h.get("request") == user_request)

    def reset(self) -> None:
        self._replan_history.clear()


class ExponentialBackoffRetry:
    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        max_retries: int = 3,
        jitter: bool = True,
    ):
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._max_retries = max_retries
        self._jitter = jitter
        self._attempts: Dict[str, int] = {}
        self._last_delay: Dict[str, float] = {}

    def get_delay(self, action_name: str) -> float:
        attempt = self._attempts.get(action_name, 0)
        delay = min(self._base_delay * (2 ** attempt), self._max_delay)
        if self._jitter:
            import random
            delay = delay * (0.5 + random.random() * 0.5)
        self._attempts[action_name] = attempt + 1
        self._last_delay[action_name] = delay
        return delay

    def should_retry(self, action_name: str) -> bool:
        return self._attempts.get(action_name, 0) < self._max_retries

    def record_success(self, action_name: str) -> None:
        self._attempts.pop(action_name, None)
        self._last_delay.pop(action_name, None)

    def record_failure(self, action_name: str) -> float:
        delay = self.get_delay(action_name)
        return delay

    def get_stats(self, action_name: str) -> Dict[str, Any]:
        return {
            "action": action_name,
            "attempts": self._attempts.get(action_name, 0),
            "last_delay": self._last_delay.get(action_name, 0.0),
            "can_retry": self.should_retry(action_name),
        }

    def reset(self, action_name: Optional[str] = None) -> None:
        if action_name:
            self._attempts.pop(action_name, None)
            self._last_delay.pop(action_name, None)
        else:
            self._attempts.clear()
            self._last_delay.clear()
