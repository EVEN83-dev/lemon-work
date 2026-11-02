"""
C4: Eval Benchmark — 10 real task samples + eval runner + report generation.

Threshold: 5/10 pass = acceptable.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class EvalTask:
    task_id: str
    name: str
    description: str
    expected_tools: List[str] = field(default_factory=list)
    expected_outcomes: List[str] = field(default_factory=list)
    forbidden_actions: List[str] = field(default_factory=list)
    max_tool_calls: int = 10
    timeout_seconds: float = 60.0
    difficulty: str = "medium"
    category: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "taskId": self.task_id,
            "name": self.name,
            "description": self.description,
            "expectedTools": self.expected_tools,
            "expectedOutcomes": self.expected_outcomes,
            "forbiddenActions": self.forbidden_actions,
            "maxToolCalls": self.max_tool_calls,
            "timeoutSeconds": self.timeout_seconds,
            "difficulty": self.difficulty,
            "category": self.category,
        }


@dataclass
class EvalResult:
    task_id: str
    passed: bool
    score: float
    details: str
    tool_calls_made: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "taskId": self.task_id,
            "passed": self.passed,
            "score": self.score,
            "details": self.details,
            "toolCallsMade": self.tool_calls_made,
            "violations": self.violations,
            "durationSeconds": self.duration_seconds,
        }


SAMPLE_TASKS: List[EvalTask] = [
    EvalTask(
        task_id="eval_001",
        name="Read and summarize file",
        description="Read the file src/main.py and provide a brief summary of its purpose and key functions",
        expected_tools=["read_file", "file_read"],
        expected_outcomes=["summary", "key functions identified"],
        max_tool_calls=5,
        difficulty="easy",
        category="file_analysis",
    ),
    EvalTask(
        task_id="eval_002",
        name="Find and fix syntax error",
        description="The file src/parser.py has a syntax error. Find it, explain the error, and fix it",
        expected_tools=["read_file", "edit_file"],
        expected_outcomes=["error located", "error fixed", "file modified"],
        forbidden_actions=["delete entire file"],
        max_tool_calls=8,
        difficulty="medium",
        category="debugging",
    ),
    EvalTask(
        task_id="eval_003",
        name="Run tests and report results",
        description="Run the test suite using pytest and report which tests pass and which fail",
        expected_tools=["run_shell"],
        expected_outcomes=["test results", "pass/fail counts"],
        max_tool_calls=4,
        difficulty="easy",
        category="testing",
    ),
    EvalTask(
        task_id="eval_004",
        name="Search for API endpoint definitions",
        description="Find all API endpoint definitions in the codebase and list them with their HTTP methods and paths",
        expected_tools=["grep_search", "search_code", "read_file"],
        expected_outcomes=["endpoint list", "HTTP methods"],
        max_tool_calls=6,
        difficulty="medium",
        category="code_search",
    ),
    EvalTask(
        task_id="eval_005",
        name="Refactor function to use async",
        description="Refactor the function process_data() in src/processor.py to use async/await pattern",
        expected_tools=["read_file", "edit_file"],
        expected_outcomes=["async keyword added", "await calls added", "function signature changed"],
        forbidden_actions=["change unrelated functions"],
        max_tool_calls=8,
        difficulty="hard",
        category="refactoring",
    ),
    EvalTask(
        task_id="eval_006",
        name="Create new module with tests",
        description="Create a new module src/validators.py with email validation function and corresponding test file",
        expected_tools=["write_file", "run_shell"],
        expected_outcomes=["validators.py created", "test_validators.py created", "tests pass"],
        max_tool_calls=10,
        difficulty="hard",
        category="code_generation",
    ),
    EvalTask(
        task_id="eval_007",
        name="Check git status and recent changes",
        description="Show the current git status and list the 5 most recent commits with their messages",
        expected_tools=["git_status", "run_shell"],
        expected_outcomes=["branch info", "changed files", "commit messages"],
        max_tool_calls=4,
        difficulty="easy",
        category="version_control",
    ),
    EvalTask(
        task_id="eval_008",
        name="Find security vulnerabilities",
        description="Scan the codebase for common security vulnerabilities: SQL injection, hardcoded secrets, and unsafe deserialization",
        expected_tools=["grep_search", "read_file"],
        expected_outcomes=["vulnerabilities listed", "remediation suggestions"],
        forbidden_actions=["modify any files"],
        max_tool_calls=10,
        difficulty="hard",
        category="security",
    ),
    EvalTask(
        task_id="eval_009",
        name="Add error handling to function",
        description="Add proper try/except error handling to the fetch_data() function in src/api.py, handling network errors and timeouts",
        expected_tools=["read_file", "edit_file"],
        expected_outcomes=["try/except added", "specific exception types", "error logging"],
        max_tool_calls=6,
        difficulty="medium",
        category="error_handling",
    ),
    EvalTask(
        task_id="eval_010",
        name="Generate documentation from code",
        description="Read src/calculator.py and generate comprehensive docstrings for all public functions following Google style",
        expected_tools=["read_file", "edit_file"],
        expected_outcomes=["docstrings added", "Google style format", "all public functions documented"],
        max_tool_calls=8,
        difficulty="medium",
        category="documentation",
    ),
]


class EvalRunner:
    def __init__(
        self,
        agent_executor: Optional[Callable] = None,
        tasks: Optional[List[EvalTask]] = None,
        output_dir: str = "",
    ):
        self._agent_executor = agent_executor
        self._tasks = tasks or SAMPLE_TASKS
        if not output_dir:
            output_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "eval_reports")
        self._output_dir = output_dir
        os.makedirs(self._output_dir, exist_ok=True)

    def run_single(
        self,
        task: EvalTask,
        agent_executor: Optional[Callable] = None,
    ) -> EvalResult:
        executor = agent_executor or self._agent_executor
        if executor is None:
            return EvalResult(
                task_id=task.task_id,
                passed=False,
                score=0.0,
                details="No agent executor provided",
            )

        start = time.time()
        try:
            result = executor(
                task_description=task.description,
                expected_tools=task.expected_tools,
                max_tool_calls=task.max_tool_calls,
                timeout=task.timeout_seconds,
            )
            duration = time.time() - start

            tool_calls = result.get("tool_calls", [])
            output = result.get("output", "")
            violations = self._check_violations(tool_calls, task.forbidden_actions)
            tool_score = self._score_tool_usage(tool_calls, task.expected_tools)
            outcome_score = self._score_outcomes(output, task.expected_outcomes)
            penalty = len(violations) * 0.2
            total_score = max(0.0, (tool_score * 0.4 + outcome_score * 0.6) - penalty)
            passed = total_score >= 0.5 and len(violations) == 0

            return EvalResult(
                task_id=task.task_id,
                passed=passed,
                score=total_score,
                details=output[:500],
                tool_calls_made=[tc.get("name", "") for tc in tool_calls],
                violations=violations,
                duration_seconds=duration,
            )
        except Exception as e:
            return EvalResult(
                task_id=task.task_id,
                passed=False,
                score=0.0,
                details=f"Exception: {str(e)}",
                duration_seconds=time.time() - start,
            )

    def run_all(
        self,
        agent_executor: Optional[Callable] = None,
        task_ids: Optional[List[str]] = None,
    ) -> List[EvalResult]:
        results: List[EvalResult] = []
        tasks = self._tasks
        if task_ids:
            tasks = [t for t in tasks if t.task_id in task_ids]
        for task in tasks:
            result = self.run_single(task, agent_executor)
            results.append(result)
        self._generate_report(results)
        return results

    def dry_run_validate(self) -> Dict[str, Any]:
        validated: List[Dict[str, Any]] = []
        for task in self._tasks:
            issues: List[str] = []
            if not task.description:
                issues.append("Missing description")
            if not task.expected_tools:
                issues.append("No expected tools")
            if not task.expected_outcomes:
                issues.append("No expected outcomes")
            if task.max_tool_calls < 1:
                issues.append("max_tool_calls must be >= 1")
            validated.append({
                "taskId": task.task_id,
                "name": task.name,
                "valid": len(issues) == 0,
                "issues": issues,
            })
        all_valid = all(v["valid"] for v in validated)
        return {
            "allValid": all_valid,
            "taskCount": len(validated),
            "tasks": validated,
        }

    def _check_violations(self, tool_calls: List[Dict], forbidden: List[str]) -> List[str]:
        violations: List[str] = []
        for tc in tool_calls:
            tool_name = tc.get("name", tc.get("skill_name", ""))
            args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
            for fb in forbidden:
                if fb.lower() in args_str.lower() or fb.lower() in tool_name.lower():
                    violations.append(f"Forbidden action '{fb}' in {tool_name}")
        return violations

    def _score_tool_usage(self, tool_calls: List[Dict], expected_tools: List[str]) -> float:
        if not expected_tools:
            return 1.0
        used_tools = set(
            tc.get("name", tc.get("skill_name", "")).replace("skill_", "")
            for tc in tool_calls
        )
        expected = set(t.replace("skill_", "") for t in expected_tools)
        overlap = len(used_tools & expected)
        return overlap / len(expected) if expected else 1.0

    def _score_outcomes(self, output: str, expected_outcomes: List[str]) -> float:
        if not expected_outcomes:
            return 1.0
        output_lower = output.lower()
        matched = sum(1 for outcome in expected_outcomes if outcome.lower() in output_lower)
        return matched / len(expected_outcomes)

    def _generate_report(self, results: List[EvalResult]) -> str:
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        avg_score = sum(r.score for r in results) / total if total else 0.0
        threshold_met = passed >= 5

        lines = [
            "# Eval Benchmark Report",
            "",
            f"- **Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **Total tasks**: {total}",
            f"- **Passed**: {passed}",
            f"- **Failed**: {total - passed}",
            f"- **Average score**: {avg_score:.2f}",
            f"- **Threshold (5/10)**: {'MET' if threshold_met else 'NOT MET'}",
            "",
            "## Results",
            "",
            "| Task | Score | Passed | Duration | Details |",
            "|------|-------|--------|----------|---------|",
        ]
        for r in results:
            details = r.details[:40].replace("|", "/")
            lines.append(f"| {r.task_id} | {r.score:.2f} | {'PASS' if r.passed else 'FAIL'} | {r.duration_seconds:.1f}s | {details} |")

        if any(r.violations for r in results):
            lines.append("")
            lines.append("## Violations")
            lines.append("")
            for r in results:
                for v in r.violations:
                    lines.append(f"- **{r.task_id}**: {v}")

        report = "\n".join(lines)
        report_path = os.path.join(self._output_dir, f"eval_report_{int(time.time())}.md")
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report)
        except Exception:
            pass
        return report
