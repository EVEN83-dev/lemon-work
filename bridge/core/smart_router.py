"""
H5: Smart Router - cost-aware multi-model intelligent routing.

Selects the best engine based on cost, win rate, and latency signals.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from bridge.engines.engine_manager import EngineManager


class SmartRouter:
    WEIGHT_COST = 0.4
    WEIGHT_WIN_RATE = 0.35
    WEIGHT_LATENCY = 0.25

    def __init__(self, engine_manager: EngineManager, cost_table: Dict[str, float]):
        self._engine_manager = engine_manager
        self._cost_table = cost_table
        self._session_memory: Optional[Any] = None
        self._latency_history: Dict[str, List[float]] = {}

    def set_session_memory(self, session_memory: Any) -> None:
        self._session_memory = session_memory

    def record_latency(self, engine_name: str, latency_ms: float) -> None:
        if engine_name not in self._latency_history:
            self._latency_history[engine_name] = []
        self._latency_history[engine_name].append(latency_ms)
        if len(self._latency_history[engine_name]) > 50:
            self._latency_history[engine_name] = self._latency_history[engine_name][-50:]

    def _get_avg_latency(self, engine_name: str) -> Optional[float]:
        history = self._latency_history.get(engine_name)
        if not history:
            return None
        return sum(history) / len(history)

    def _get_win_rate(self, engine_name: str) -> float:
        if self._session_memory is None:
            return 0.5
        try:
            key = f"score_{engine_name}"
            if hasattr(self._session_memory, "get_metadata"):
                val = self._session_memory.get_metadata(key)
                if val is not None:
                    return float(val)
        except Exception:
            pass
        return 0.5

    def _compute_cost_score(self, engine_name: str) -> float:
        cost = self._cost_table.get(engine_name, 1.0)
        if cost <= 0:
            return 1.0
        max_cost = max(self._cost_table.values()) if self._cost_table else 1.0
        if max_cost <= 0:
            return 1.0
        return 1.0 - (cost / max_cost)

    def _compute_latency_score(self, engine_name: str) -> float:
        max_latency_str = os.environ.get("LEMON_MAX_LATENCY_MS")
        if not max_latency_str:
            return 1.0
        try:
            max_latency = float(max_latency_str)
        except ValueError:
            return 1.0
        avg = self._get_avg_latency(engine_name)
        if avg is None:
            return 0.8
        if avg <= max_latency:
            return 1.0
        return max(0.0, 1.0 - (avg - max_latency) / max_latency)

    def _compute_message_factor(self, message: str) -> float:
        token_estimate = len(message) / 4.0
        return min(token_estimate / 1000.0, 1.0)

    def _get_available_engines(self) -> List[str]:
        if hasattr(self._engine_manager, 'list_available_engines'):
            return self._engine_manager.list_available_engines()
        if hasattr(self._engine_manager, 'list_engines'):
            return self._engine_manager.list_engines()
        return []

    def score(self, message: str, task_type: str = "general") -> str:
        available = self._get_available_engines()
        if not available:
            raise RuntimeError("No available engines for routing")

        if len(available) == 1:
            return available[0]

        message_factor = self._compute_message_factor(message)
        cost_weight = self.WEIGHT_COST * (0.3 + 0.7 * message_factor)

        best_engine = available[0]
        best_score = -1.0

        for engine_name in available:
            cost_score = self._compute_cost_score(engine_name)
            win_rate_score = self._get_win_rate(engine_name)
            latency_score = self._compute_latency_score(engine_name)

            total = (
                cost_weight * cost_score
                + self.WEIGHT_WIN_RATE * win_rate_score
                + self.WEIGHT_LATENCY * latency_score
            )

            if total > best_score:
                best_score = total
                best_engine = engine_name

        return best_engine

    @staticmethod
    def build_default(engine_manager: EngineManager) -> SmartRouter:
        default_cost_table: Dict[str, float] = {
            "ollama": 0.0,
            "deepseek": 0.14,
            "openai": 2.0,
            "zhipu": 0.1,
        }
        return SmartRouter(engine_manager, default_cost_table)
