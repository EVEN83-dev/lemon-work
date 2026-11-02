# -*- coding: utf-8 -*-
"""H5 — SmartRouter cost-aware routing tests"""
import os
from unittest.mock import MagicMock

from bridge.core.smart_router import SmartRouter


def _mock_engine_manager(available: list) -> MagicMock:
    em = MagicMock()
    em.list_available_engines.return_value = available
    return em


def test_high_cost_task_routes_to_local():
    em = _mock_engine_manager(["ollama", "deepseek", "openai"])
    cost_table = {"ollama": 0.0, "deepseek": 0.14, "openai": 2.0}
    router = SmartRouter(em, cost_table)
    long_message = "x " * 5000
    result = router.score(long_message, task_type="general")
    assert result == "ollama", f"Expected ollama for high-cost task, got {result}"


def test_low_cost_task_can_route_to_cloud():
    em = _mock_engine_manager(["ollama", "deepseek", "openai"])
    cost_table = {"ollama": 0.0, "deepseek": 0.14, "openai": 2.0}
    session_memory = MagicMock()
    session_memory.get_metadata.side_effect = lambda k: {
        "score_deepseek": 0.9,
        "score_ollama": 0.3,
        "score_openai": 0.2,
    }.get(k)
    router = SmartRouter(em, cost_table)
    router.set_session_memory(session_memory)
    short_message = "hi"
    result = router.score(short_message, task_type="general")
    assert result != "openai", "openai should not be chosen due to high cost"
    assert result in ("ollama", "deepseek"), f"Expected local or cheap cloud, got {result}"


def test_single_engine_returns_itself():
    em = _mock_engine_manager(["ollama"])
    router = SmartRouter(em, {"ollama": 0.0})
    result = router.score("anything")
    assert result == "ollama"


def test_no_engines_raises():
    em = _mock_engine_manager([])
    router = SmartRouter(em, {})
    try:
        router.score("hello")
        assert False, "Should have raised RuntimeError"
    except RuntimeError:
        pass


def test_build_default():
    em = _mock_engine_manager(["ollama", "deepseek"])
    router = SmartRouter.build_default(em)
    assert router._cost_table == {"ollama": 0.0, "deepseek": 0.14, "openai": 2.0, "zhipu": 0.1}
    result = router.score("test message")
    assert result in ("ollama", "deepseek")


def test_latency_env_prefer_fast_engine():
    os.environ["LEMON_MAX_LATENCY_MS"] = "500"
    try:
        em = _mock_engine_manager(["ollama", "deepseek"])
        cost_table = {"ollama": 0.0, "deepseek": 0.14}
        router = SmartRouter(em, cost_table)
        router.record_latency("ollama", 200.0)
        router.record_latency("deepseek", 3000.0)
        result = router.score("short query")
        assert result == "ollama", f"Expected ollama (within latency), got {result}"
    finally:
        del os.environ["LEMON_MAX_LATENCY_MS"]


def test_win_rate_influences_choice():
    em = _mock_engine_manager(["ollama", "deepseek"])
    cost_table = {"ollama": 0.0, "deepseek": 0.14}
    session_memory = MagicMock()
    session_memory.get_metadata.side_effect = lambda k: {
        "score_ollama": 0.1,
        "score_deepseek": 0.95,
    }.get(k)
    router = SmartRouter(em, cost_table)
    router.set_session_memory(session_memory)
    short_message = "quick"
    result = router.score(short_message)
    assert result == "deepseek", f"Expected deepseek (high win rate on cheap task), got {result}"


if __name__ == "__main__":
    test_high_cost_task_routes_to_local()
    test_low_cost_task_can_route_to_cloud()
    test_single_engine_returns_itself()
    test_no_engines_raises()
    test_build_default()
    test_latency_env_prefer_fast_engine()
    test_win_rate_influences_choice()
    print("ALL H5 TESTS PASSED")
