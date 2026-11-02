# -*- coding: utf-8 -*-
"""Token budget manager - prevent unbounded conversation growth"""
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class TokenBudget:
    max_input_tokens: int = 100000
    max_output_tokens: int = 4096
    max_total_tokens: int = 200000
    max_turns: int = 50
    warning_threshold: float = 0.8

    input_used: int = 0
    output_used: int = 0
    total_used: int = 0
    turns: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_total_tokens - self.total_used)

    @property
    def usage_ratio(self) -> float:
        if self.max_total_tokens == 0:
            return 0.0
        return self.total_used / self.max_total_tokens

    @property
    def is_warning(self) -> bool:
        return self.usage_ratio >= self.warning_threshold

    @property
    def is_exceeded(self) -> bool:
        return self.total_used >= self.max_total_tokens

    def add_usage(self, input_tokens: int, output_tokens: int = 0):
        self.input_used += input_tokens
        self.output_used += output_tokens
        self.total_used += input_tokens + output_tokens
        if output_tokens > 0:
            self.turns += 1

    def reset(self):
        self.input_used = 0
        self.output_used = 0
        self.total_used = 0
        self.turns = 0

    def get_status(self) -> Dict:
        return {
            'total_used': self.total_used,
            'max_total': self.max_total_tokens,
            'remaining': self.remaining,
            'usage_ratio': f'{self.usage_ratio:.1%}',
            'turns': self.turns,
            'max_turns': self.max_turns,
            'is_warning': self.is_warning,
            'is_exceeded': self.is_exceeded,
        }


class TokenBudgetManager:

    def __init__(self, max_total: int = 200000):
        self._default_budget = TokenBudget(max_total_tokens=max_total)
        self._session_budgets: Dict[str, TokenBudget] = {}

    def get_budget(self, session_id: str) -> TokenBudget:
        if session_id not in self._session_budgets:
            self._session_budgets[session_id] = TokenBudget(
                max_total_tokens=self._default_budget.max_total_tokens
            )
        return self._session_budgets[session_id]

    def check_and_warn(self, session_id: str) -> Optional[str]:
        budget = self.get_budget(session_id)
        if budget.is_exceeded:
            return f'Token budget exhausted ({budget.total_used}/{budget.max_total_tokens}), start a new session or clear history.'
        elif budget.is_warning:
            return f'Token budget low ({budget.usage_ratio:.1%}), consider clearing history.'
        return None

    def enforce_limit(self, session_id: str, estimated_tokens: int) -> bool:
        budget = self.get_budget(session_id)
        return budget.total_used + estimated_tokens <= budget.max_total_tokens

    def reset_session(self, session_id: str):
        if session_id in self._session_budgets:
            self._session_budgets[session_id].reset()

    def get_usage_report(self, session_id: str) -> Dict:
        budget = self.get_budget(session_id)
        return budget.get_status()
