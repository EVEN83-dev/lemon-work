# -*- coding: utf-8 -*-
"""Simplified Plan mode - task planning and execution"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum
import time


class PlanStatus(Enum):
    DRAFT = 'draft'
    PENDING = 'pending'
    APPROVED = 'approved'
    EXECUTING = 'executing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


@dataclass
class PlanStep:
    id: int
    description: str
    tool_suggestion: str = ''
    status: str = 'pending'
    result: Optional[str] = None
    duration: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'description': self.description,
            'tool_suggestion': self.tool_suggestion,
            'status': self.status,
            'result': self.result,
            'duration': self.duration,
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

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps if s.status == 'completed')
        return completed / len(self.steps)

    @property
    def is_complete(self) -> bool:
        return self.status == PlanStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == PlanStatus.FAILED

    def approve(self):
        self.status = PlanStatus.APPROVED
        self.approved_at = time.time()

    def start_execution(self):
        self.status = PlanStatus.EXECUTING

    def complete_step(self, step_id: int, result: str, duration: float = 0):
        for step in self.steps:
            if step.id == step_id:
                step.status = 'completed'
                step.result = result
                step.duration = duration
                break
        self._check_completion()

    def fail_step(self, step_id: int, error: str):
        for step in self.steps:
            if step.id == step_id:
                step.status = 'failed'
                step.result = error
                break
        self.status = PlanStatus.FAILED

    def skip_step(self, step_id: int, reason: str):
        for step in self.steps:
            if step.id == step_id:
                step.status = 'skipped'
                step.result = f'Skipped: {reason}'
                break

    def get_next_step(self) -> Optional[PlanStep]:
        for step in self.steps:
            if step.status == 'pending':
                return step
        return None

    def _check_completion(self):
        all_done = all(s.status in ('completed', 'skipped') for s in self.steps)
        if all_done:
            self.status = PlanStatus.COMPLETED
            self.completed_at = time.time()

    def to_dict(self) -> Dict:
        return {
            'user_request': self.user_request,
            'status': self.status.value,
            'progress': f'{self.progress:.0%}',
            'steps': [s.to_dict() for s in self.steps],
            'created_at': self.created_at,
            'approved_at': self.approved_at,
            'completed_at': self.completed_at,
        }


class PlanGenerator:

    @staticmethod
    def generate_project_analysis_plan(user_request: str, project_path: str = '') -> AgentPlan:
        steps = [
            PlanStep(id=1, description='Scan project directory structure', tool_suggestion='scan_project_structure'),
            PlanStep(id=2, description='Read key files (README, config, entry)', tool_suggestion='file_read'),
            PlanStep(id=3, description='Identify tech stack and dependencies', tool_suggestion='file_search'),
            PlanStep(id=4, description='Analyze core architecture and module relationships', tool_suggestion='file_read'),
            PlanStep(id=5, description='Generate structured analysis report', tool_suggestion='LLM summary'),
        ]
        return AgentPlan(user_request=user_request, steps=steps)

    @staticmethod
    def generate_code_fix_plan(user_request: str, file_path: str = '') -> AgentPlan:
        steps = [
            PlanStep(id=1, description='Locate problem code', tool_suggestion='file_search'),
            PlanStep(id=2, description='Analyze root cause', tool_suggestion='read_file'),
            PlanStep(id=3, description='Formulate fix plan', tool_suggestion='LLM analysis'),
            PlanStep(id=4, description='Execute fix', tool_suggestion='edit_file'),
            PlanStep(id=5, description='Verify fix result', tool_suggestion='execute_code'),
        ]
        return AgentPlan(user_request=user_request, steps=steps)

    @staticmethod
    def generate_custom_plan(user_request: str, steps_description: List[str]) -> AgentPlan:
        steps = [
            PlanStep(id=i + 1, description=desc, tool_suggestion='auto')
            for i, desc in enumerate(steps_description)
        ]
        return AgentPlan(user_request=user_request, steps=steps)


class PlanExecutor:

    def __init__(self):
        self._plans: Dict[str, AgentPlan] = {}
        self._current_plan_id: Optional[str] = None

    def create_plan(self, plan: AgentPlan) -> str:
        plan_id = f'plan_{int(time.time())}'
        self._plans[plan_id] = plan
        return plan_id

    def get_plan(self, plan_id: str) -> Optional[AgentPlan]:
        return self._plans.get(plan_id)

    def approve_plan(self, plan_id: str):
        plan = self._plans.get(plan_id)
        if plan:
            plan.approve()

    def start_execution(self, plan_id: str):
        plan = self._plans.get(plan_id)
        if plan and plan.status == PlanStatus.APPROVED:
            plan.start_execution()
            self._current_plan_id = plan_id

    def complete_step(self, plan_id: str, step_id: int, result: str):
        plan = self._plans.get(plan_id)
        if plan:
            plan.complete_step(step_id, result)

    def fail_step(self, plan_id: str, step_id: int, error: str):
        plan = self._plans.get(plan_id)
        if plan:
            plan.fail_step(step_id, error)

    def get_active_plan(self) -> Optional[AgentPlan]:
        if self._current_plan_id:
            return self._plans.get(self._current_plan_id)
        return None

    def get_all_plans(self) -> List[Dict]:
        return [
            {
                'id': pid,
                'request': plan.user_request[:50],
                'status': plan.status.value,
                'progress': f'{plan.progress:.0%}',
                'steps': len(plan.steps),
            }
            for pid, plan in self._plans.items()
        ]


_generator = PlanGenerator()
_executor = PlanExecutor()


def get_plan_generator() -> PlanGenerator:
    return _generator


def get_plan_executor() -> PlanExecutor:
    return _executor
