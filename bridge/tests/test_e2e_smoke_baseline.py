# -*- coding: utf-8 -*-
"""H7: e2e_smoke pytest集成 + 基线分测试"""
import json
import os
import unittest

BASELINE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "eval_baseline.json"
)


def _load_baseline():
    with open(BASELINE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestE2ESmokeBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = _load_baseline()

    def test_run_all_score_above_baseline(self):
        from bridge.eval.e2e_smoke import run_all
        result = run_all()
        baseline_score = self.baseline.get("e2e_smoke", 0.0)
        self.assertGreaterEqual(
            result["score"],
            baseline_score,
            f"e2e_smoke score {result['score']:.2f} < baseline {baseline_score}",
        )

    def test_baseline_file_has_required_keys(self):
        required = ["e2e_smoke", "skills_bench", "agent_bench"]
        for key in required:
            self.assertIn(key, self.baseline, f"Missing key: {key}")

    def test_baseline_values_in_range(self):
        for key, val in self.baseline.items():
            self.assertGreaterEqual(val, 0.0, f"{key} < 0.0")
            self.assertLessEqual(val, 1.0, f"{key} > 1.0")

    def test_run_all_returns_score_key(self):
        from bridge.eval.e2e_smoke import run_all
        result = run_all()
        self.assertIn("score", result)
        self.assertGreaterEqual(result["score"], 0.0)
        self.assertLessEqual(result["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
