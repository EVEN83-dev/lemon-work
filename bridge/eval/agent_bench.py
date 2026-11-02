# -*- coding: utf-8 -*-
"""
C4：Agent 端到端评测基准
========================
10 道真实任务，mock AgentLoop 执行，评分 pass_rate + 耗时 + trajectory 事件数
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


@dataclass
class AgentEvalTask:
    task_id: str
    name: str
    user_message: str
    expected_keywords: List[str] = field(default_factory=list)
    forbidden_keywords: List[str] = field(default_factory=list)
    min_tool_calls: int = 0
    max_tool_calls: int = 15
    difficulty: str = "medium"
    category: str = "general"


@dataclass
class AgentEvalResult:
    task_id: str
    passed: bool
    score: float
    output_preview: str = ""
    tool_call_count: int = 0
    duration_seconds: float = 0.0
    keywords_hit: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)


AGENT_EVAL_TASKS: List[AgentEvalTask] = [
    AgentEvalTask("agent_01", "写函数", "写一个 Python 函数计算斐波那契数列第 n 项", ["fibonacci", "def ", "return"], [], 1, 3),
    AgentEvalTask("agent_02", "改 bug", "修复 app.py 中 ImportError: No module named 'utils'", ["import", "fix", "error"], [], 1, 5, category="debugging"),
    AgentEvalTask("agent_03", "查依赖", "查看项目 requirements.txt 里的依赖列表", ["requirements", "install", "依赖"], [], 1, 3, category="dependency"),
    AgentEvalTask("agent_04", "生成测试", "为 calculator.py 的 add 函数生成 pytest 测试", ["test", "def test_", "assert", "add"], [], 1, 5, category="testing"),
    AgentEvalTask("agent_05", "重构", "把 process_data() 函数重构为 async/await 模式", ["async", "await", "def "], [], 1, 5, category="refactoring"),
    AgentEvalTask("agent_06", "读文件总结", "读取 README.md 并总结项目功能", ["README", "总结", "功能"], [], 1, 4, difficulty="easy"),
    AgentEvalTask("agent_07", "搜索代码", "在代码中搜索所有 class 定义", ["class ", "搜索", "定义"], [], 1, 4, category="search"),
    AgentEvalTask("agent_08", "跑命令", "运行 pytest 并报告测试结果", ["pytest", "pass", "fail", "test"], [], 1, 3, category="execution"),
    AgentEvalTask("agent_09", "多步规划", "创建新模块 validators.py 并添加邮箱验证函数和测试", ["validators", "validate", "email", "test"], [], 2, 8, difficulty="hard"),
    AgentEvalTask("agent_10", "错误处理", "给 fetch_data() 函数加 try/except 错误处理", ["try", "except", "error", "fetch"], [], 1, 5, category="error_handling"),
]


def _mock_agent_executor(task: AgentEvalTask) -> Dict[str, Any]:
    output = f"Completed: {task.name}. "
    for kw in task.expected_keywords[:2]:
        output += f"Found {kw}. "
    return {
        "output": output,
        "tool_calls": [{"name": "read_file"}, {"name": "edit_file"}],
        "trajectory_events": 5,
    }


class AgentBench:
    def __init__(self, output_dir: str = ""):
        if not output_dir:
            output_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "eval")
        self._output_dir = output_dir
        os.makedirs(self._output_dir, exist_ok=True)

    def run(
        self,
        agent_executor: Optional[Callable] = None,
        tasks: Optional[List[AgentEvalTask]] = None,
    ) -> Dict[str, Any]:
        executor = agent_executor or _mock_agent_executor
        task_list = tasks or AGENT_EVAL_TASKS
        results: List[AgentEvalResult] = []

        for task in task_list:
            start = time.time()
            try:
                raw = executor(task)
                duration = time.time() - start
                output = raw.get("output", "")
                tool_calls = raw.get("tool_calls", [])

                keywords_hit = [kw for kw in task.expected_keywords if kw.lower() in output.lower()]
                violations = [fb for fb in task.forbidden_keywords if fb.lower() in output.lower()]
                kw_score = len(keywords_hit) / len(task.expected_keywords) if task.expected_keywords else 1.0
                tool_score = min(len(tool_calls) / max(task.min_tool_calls, 1), 1.0)
                penalty = len(violations) * 0.3
                total_score = max(0.0, (kw_score * 0.6 + tool_score * 0.4) - penalty)
                passed = total_score >= 0.5 and len(violations) == 0

                results.append(AgentEvalResult(
                    task_id=task.task_id, passed=passed, score=total_score,
                    output_preview=output[:200], tool_call_count=len(tool_calls),
                    duration_seconds=round(duration, 2), keywords_hit=keywords_hit,
                    violations=violations,
                ))
            except Exception as e:
                results.append(AgentEvalResult(
                    task_id=task.task_id, passed=False, score=0.0,
                    output_preview=f"Exception: {e}", duration_seconds=round(time.time() - start, 2),
                ))

        pass_count = sum(1 for r in results if r.passed)
        avg_score = sum(r.score for r in results) / len(results) if results else 0.0
        report = {
            "pass_rate": pass_count / len(results) if results else 0.0,
            "pass_count": pass_count,
            "total": len(results),
            "avg_score": round(avg_score, 3),
            "threshold_met": pass_count >= 5,
            "tasks": [asdict(r) for r in results],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        report_path = os.path.join(self._output_dir, "agent_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        return report


if __name__ == "__main__":
    bench = AgentBench()
    report = bench.run()
    print(f"Pass rate: {report['pass_rate']:.0%} ({report['pass_count']}/{report['total']})")
    print(f"Threshold (5/10): {'MET' if report['threshold_met'] else 'NOT MET'}")
    print(f"Report: {os.path.join(bench._output_dir, 'agent_report.json')}")
