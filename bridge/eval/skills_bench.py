from __future__ import annotations

import json
import os
import sys
import time
import traceback
from typing import Any, Dict, List

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from bridge.skills.registry import get_skills_registry


TEST_CASES: List[Dict[str, Any]] = [
    {"skill": "math_solver", "args": {"expression": "2+3*4", "operation": "simplify"}, "expect_success": True},
    {"skill": "math_solver", "args": {"expression": "x**2-1", "operation": "solve", "variable": "x"}, "expect_success": True},
    {"skill": "finance_assistant", "args": {"analysis_type": "loan", "principal": 100000, "rate": 5.0, "periods": 30}, "expect_success": True},
    {"skill": "code_formatter", "args": {"code": "x=1;y=2", "language": "python"}, "expect_success": True},
    {"skill": "code_graph", "args": {"code": "def foo():\n    bar()\ndef bar():\n    pass", "language": "python"}, "expect_success": True},
    {"skill": "code_psychologist", "args": {"code": "def hello():\n    x = 1\n    return x\n", "language": "python"}, "expect_success": True},
    {"skill": "code_reviewer", "args": {"code": "import os\nos.system('rm -rf /')", "language": "python", "review_type": "security"}, "expect_success": True},
    {"skill": "academic_writer", "args": {"topic": "machine learning", "style": "apa"}, "expect_success": True},
    {"skill": "requirement_amplifier", "args": {"requirement": "user login page", "detail_level": 3}, "expect_success": True},
    {"skill": "fact_checker", "args": {"claim": "Python was created in 1991"}, "expect_success": True},
    {"skill": "deep_researcher", "args": {"topic": "quantum computing", "depth": 1}, "expect_success": True},
    {"skill": "super_researcher", "args": {"topic": "renewable energy", "rounds": 1}, "expect_success": True},
    {"skill": "deploy_helper", "args": {"project_type": "web", "target": "localhost"}, "expect_success": True},
    {"skill": "pomodoro_skill", "args": {"minutes": 25}, "expect_success": True},
    {"skill": "env_checker", "args": {}, "expect_success": True},
    {"skill": "config_manager", "args": {"action": "read", "path": os.path.join(_project_root, "bridge", "eval", "_test_config.json")}, "expect_success": True},
    {"skill": "log_analyzer", "args": {"path": "nonexistent.log"}, "expect_success": False},
    {"skill": "physics_experiment", "args": {"experiment": "pendulum", "params": {"length": 1.0}}, "expect_success": True},
    {"skill": "html_to_video", "args": {"content": "<h1>Hello</h1>", "duration": 10}, "expect_success": True},
    {"skill": "multi_model_debater", "args": {"topic": "AI safety", "perspectives": 2}, "expect_success": True},
    {"skill": "frontend_designer", "args": {"framework": "html", "component_type": "form", "description": "login form"}, "expect_success": True},
    {"skill": "search_code_semantic", "args": {"query": "def main", "top_k": 3}, "expect_success": True},
    {"skill": "meta_skill", "args": {"task_description": "convert CSV to JSON"}, "expect_success": True},
    {"skill": "pdf_reader", "args": {"path": "nonexistent.pdf", "extract_type": "text"}, "expect_success": False},
    {"skill": "image_analyzer", "args": {"image_path": "nonexistent.png"}, "expect_success": False},
    {"skill": "image_processor", "args": {"path": "nonexistent.jpg", "operation": "info"}, "expect_success": False},
    {"skill": "git", "args": {"subcommand": "status"}, "expect_success": False},
    {"skill": "lsp_skill", "args": {"action": "diagnose", "file_path": "test.py"}, "expect_success": True},
    {"skill": "dap_skill", "args": {"expression": "1+1"}, "expect_success": True},
    {"skill": "test_runner_skill", "args": {}, "expect_success": True},
]


def run_bench(output_path: str = "") -> Dict[str, Any]:
    registry = get_skills_registry()
    registry.auto_discover()

    results: List[Dict[str, Any]] = []
    success_count = 0
    total_count = len(TEST_CASES)

    for i, tc in enumerate(TEST_CASES):
        skill_name = tc["skill"]
        args = tc.get("args", {})
        expect_success = tc.get("expect_success", True)

        start = time.time()
        try:
            result = registry.execute(skill_name, args)
            duration_ms = (time.time() - start) * 1000
            actual_success = result.success
            matched = actual_success == expect_success
            if matched:
                success_count += 1
            entry = {
                "index": i + 1,
                "skill": skill_name,
                "args_keys": list(args.keys()),
                "expect_success": expect_success,
                "actual_success": actual_success,
                "matched": matched,
                "duration_ms": round(duration_ms, 1),
                "error": result.error if not actual_success else "",
                "output_preview": result.output[:100] if result.output else "",
            }
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            entry = {
                "index": i + 1,
                "skill": skill_name,
                "args_keys": list(args.keys()),
                "expect_success": expect_success,
                "actual_success": False,
                "matched": False,
                "duration_ms": round(duration_ms, 1),
                "error": str(e)[:200],
                "output_preview": "",
            }
        results.append(entry)

    pass_rate = round(success_count / total_count * 100, 1) if total_count > 0 else 0

    by_skill: Dict[str, Dict[str, Any]] = {}
    for r in results:
        sn = r["skill"]
        if sn not in by_skill:
            by_skill[sn] = {"total": 0, "matched": 0, "total_ms": 0}
        by_skill[sn]["total"] += 1
        by_skill[sn]["total_ms"] += r["duration_ms"]
        if r["matched"]:
            by_skill[sn]["matched"] += 1

    avg_duration = round(sum(r["duration_ms"] for r in results) / max(len(results), 1), 1)

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_tests": total_count,
        "passed": success_count,
        "pass_rate": pass_rate,
        "avg_duration_ms": avg_duration,
        "results": results,
        "by_skill": by_skill,
    }

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    date_str = time.strftime("%Y%m%d")
    eval_dir = os.path.join(_project_root, "data", "eval_results")
    try:
        os.makedirs(eval_dir, exist_ok=True)
        eval_path = os.path.join(eval_dir, f"{date_str}.json")
        with open(eval_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return report


if __name__ == "__main__":
    default_path = os.path.join(_project_root, "bridge", "eval", "skills_report.json")
    report = run_bench(default_path)
    print("=" * 60)
    print("Skills Benchmark Report")
    print("=" * 60)
    print("Total: " + str(report["total_tests"]))
    print("Passed: " + str(report["passed"]))
    print("Pass rate: " + str(report["pass_rate"]) + "%")
    print("Avg duration: " + str(report["avg_duration_ms"]) + "ms")
    print("")
    print("By skill:")
    for sn, stats in sorted(report["by_skill"].items()):
        rate = round(stats["matched"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0
        avg_ms = round(stats["total_ms"] / stats["total"], 1)
        print("  " + sn + ": " + str(stats["matched"]) + "/" + str(stats["total"]) + " (" + str(rate) + "%) avg=" + str(avg_ms) + "ms")
