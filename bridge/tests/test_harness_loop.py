from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from bridge.agent_loop import AgentLoop
from bridge.core.session_memory import SessionMemory


class TestHarnessLoop(unittest.TestCase):
    def setUp(self):
        self.session_memory = SessionMemory(
            db_path=os.path.join(os.path.dirname(__file__), "_test_harness_sessions.db")
        )
        self.engine_manager = MagicMock()
        self.engine_manager.get_engine.return_value = None

    def tearDown(self):
        db_path = os.path.join(os.path.dirname(__file__), "_test_harness_sessions.db")
        if os.path.exists(db_path):
            os.remove(db_path)

    @patch("bridge.eval.agent_bench.AgentBench")
    def test_eval_harness_stores_result(self, MockAgentBench):
        mock_report = {
            "pass_rate": 0.8,
            "pass_count": 8,
            "total": 10,
            "avg_score": 0.75,
            "threshold_met": True,
            "tasks": [],
            "timestamp": "2026-08-27 12:00:00",
        }
        mock_bench_instance = MockAgentBench.return_value
        mock_bench_instance.run.return_value = mock_report

        loop = AgentLoop(
            engine_manager=self.engine_manager,
            session_memory=self.session_memory,
        )

        session_id = "test_harness_session"
        loop._eval_harness(session_id)

        messages = self.session_memory.get_messages(session_id)
        harness_msgs = [m for m in messages if "harness_pass_rate" in m.get("content", "")]
        self.assertTrue(len(harness_msgs) >= 1, "Expected at least one harness message in session_memory")

        content = harness_msgs[0]["content"]
        data = json.loads(content)
        self.assertAlmostEqual(data["harness_pass_rate"], 0.8)

    @patch("bridge.eval.agent_bench.AgentBench")
    def test_eval_harness_exception_does_not_raise(self, MockAgentBench):
        MockAgentBench.return_value.run.side_effect = RuntimeError("bench crashed")

        loop = AgentLoop(
            engine_manager=self.engine_manager,
            session_memory=self.session_memory,
        )

        session_id = "test_harness_fail"
        loop._eval_harness(session_id)

        messages = self.session_memory.get_messages(session_id)
        self.assertIsInstance(messages, list)


if __name__ == "__main__":
    unittest.main()
