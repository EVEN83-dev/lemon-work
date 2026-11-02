from __future__ import annotations

import json
import os
import time
from typing import Any, Dict

from bridge.eval.agent_bench import AgentBench
from bridge.eval.e2e_smoke import run_e2e_smoke
from bridge.eval.skills_bench import run_bench
from bridge.services.trajectory_tracker import TrajectoryTrackerService


class IntegrationChain:
    def __init__(self, tracer: Any = None, output_dir: str = ""):
        self._tracer = tracer
        if not output_dir:
            output_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "data", "eval_results",
            )
        self._output_dir = output_dir
        os.makedirs(self._output_dir, exist_ok=True)

    def run_all(self) -> Dict[str, Any]:
        combined: Dict[str, Any] = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

        try:
            agent_bench = AgentBench()
            combined["agent_bench"] = agent_bench.run()
        except Exception as e:
            combined["agent_bench"] = {"error": str(e)}

        try:
            combined["e2e_smoke"] = {"passed": run_e2e_smoke()}
        except Exception as e:
            combined["e2e_smoke"] = {"error": str(e)}

        try:
            combined["skills_bench"] = run_bench()
        except Exception as e:
            combined["skills_bench"] = {"error": str(e)}

        try:
            if self._tracer is not None:
                tracker = TrajectoryTrackerService(self._tracer)
                combined["trajectory_tracker"] = tracker.get_stats("default")
            else:
                combined["trajectory_tracker"] = {"skipped": True, "reason": "no tracer provided"}
        except Exception as e:
            combined["trajectory_tracker"] = {"error": str(e)}

        date_str = time.strftime("%Y%m%d")
        report_path = os.path.join(self._output_dir, f"{date_str}.json")
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(combined, f, ensure_ascii=False, indent=2, default=str)
        except Exception:
            pass

        return combined
