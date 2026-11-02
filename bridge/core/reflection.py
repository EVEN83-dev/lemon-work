"""
C3: Self-Reflection Module

ReflectionLoop: task complete → auto critique → write to memory + critique.md.
Connects to agent_loop's context compression point.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class CritiqueItem:
    category: str
    severity: str
    description: str
    suggestion: str
    affected_step: int = -1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "suggestion": self.suggestion,
            "affectedStep": self.affected_step,
        }


@dataclass
class ReflectionResult:
    task_summary: str
    overall_score: float
    critiques: List[CritiqueItem] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    timestamp: float = 0.0
    session_id: str = ""
    reflection_id: str = ""

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        if not self.reflection_id:
            self.reflection_id = uuid.uuid4().hex[:12]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "taskSummary": self.task_summary,
            "overallScore": self.overall_score,
            "critiques": [c.to_dict() for c in self.critiques],
            "strengths": self.strengths,
            "improvements": self.improvements,
            "timestamp": self.timestamp,
            "sessionId": self.session_id,
            "reflectionId": self.reflection_id,
        }


_QUALITY_PATTERNS = [
    (re.compile(r"(error|错误|失败|failed|exception)", re.IGNORECASE), "error_handling", "high"),
    (re.compile(r"(TODO|FIXME|HACK|XXX)", re.IGNORECASE), "incomplete_code", "medium"),
    (re.compile(r"(hardcoded|硬编码|magic.number)", re.IGNORECASE), "maintainability", "medium"),
    (re.compile(r"(no.test|未经测试|untested)", re.IGNORECASE), "test_coverage", "high"),
    (re.compile(r"(security|安全|vulnerability|注入|injection)", re.IGNORECASE), "security", "critical"),
    (re.compile(r"(performance|性能|slow|缓慢|N\+1)", re.IGNORECASE), "performance", "medium"),
    (re.compile(r"(deprecated|过时|legacy|老旧)", re.IGNORECASE), "technical_debt", "low"),
]

_EFFICIENCY_SIGNALS = {
    "repeated_reads": re.compile(r"read_file.*same.*path|重复读取", re.IGNORECASE),
    "unnecessary_calls": re.compile(r"called.*but.*unused|不必要调用", re.IGNORECASE),
    "loop_detected": re.compile(r"loop.detected|循环检测", re.IGNORECASE),
}

_STRENGTH_PATTERNS = [
    re.compile(r"(clean.code|清晰|well.structured|结构良好)", re.IGNORECASE),
    re.compile(r"(comprehensive|全面|thorough|彻底)", re.IGNORECASE),
    re.compile(r"(optimized|优化|efficient|高效)", re.IGNORECASE),
    re.compile(r"(tested|已测试|validated|验证)", re.IGNORECASE),
    re.compile(r"(documented|文档完善|commented)", re.IGNORECASE),
]


class ReflectionLoop:
    def __init__(
        self,
        memory_system: Optional[Any] = None,
        output_dir: str = "",
        critique_callback: Optional[Callable[[ReflectionResult], None]] = None,
    ):
        self._memory_system = memory_system
        if not output_dir:
            output_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "reflections")
        self._output_dir = output_dir
        self._critique_callback = critique_callback
        self._lock = Lock()
        self._history: List[ReflectionResult] = []
        os.makedirs(self._output_dir, exist_ok=True)

    def reflect(
        self,
        session_id: str,
        task_description: str,
        tool_calls: List[Dict[str, Any]],
        tool_results: List[str],
        final_output: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ReflectionResult:
        critiques = self._analyze_quality(final_output, tool_calls, tool_results)
        efficiency_critiques = self._analyze_efficiency(tool_calls, tool_results)
        critiques.extend(efficiency_critiques)
        strengths = self._extract_strengths(final_output, tool_results)
        improvements = [c.suggestion for c in critiques if c.severity in ("high", "critical")]
        overall_score = self._compute_score(critiques, strengths, tool_calls, tool_results)
        summary = self._generate_summary(task_description, tool_calls, critiques, strengths)

        result = ReflectionResult(
            task_summary=summary,
            overall_score=overall_score,
            critiques=critiques,
            strengths=strengths,
            improvements=improvements,
            session_id=session_id,
        )

        with self._lock:
            self._history.append(result)

        self._write_critique_md(result)
        self._store_to_memory(result)

        if self._critique_callback:
            try:
                self._critique_callback(result)
            except Exception:
                pass

        return result

    def get_history(self, session_id: str = "", limit: int = 20) -> List[ReflectionResult]:
        with self._lock:
            results = self._history
            if session_id:
                results = [r for r in results if r.session_id == session_id]
            return results[-limit:]

    def get_average_score(self, session_id: str = "") -> float:
        with self._lock:
            results = self._history
            if session_id:
                results = [r for r in results if r.session_id == session_id]
            if not results:
                return 0.0
            return sum(r.overall_score for r in results) / len(results)

    def _analyze_quality(
        self,
        final_output: str,
        tool_calls: List[Dict[str, Any]],
        tool_results: List[str],
    ) -> List[CritiqueItem]:
        critiques: List[CritiqueItem] = []
        all_text = final_output + " " + " ".join(tool_results)
        for pattern, category, severity in _QUALITY_PATTERNS:
            matches = pattern.findall(all_text)
            if matches:
                critiques.append(CritiqueItem(
                    category=category,
                    severity=severity,
                    description=f"Detected {len(matches)} instance(s) of {category}",
                    suggestion=self._suggest_fix(category),
                    affected_step=-1,
                ))
        for i, result in enumerate(tool_results):
            if "error" in result.lower() and "success" not in result.lower():
                critiques.append(CritiqueItem(
                    category="tool_failure",
                    severity="high",
                    description=f"Tool call at step {i} returned an error",
                    suggestion="Review error and add retry or fallback logic",
                    affected_step=i,
                ))
        return critiques

    def _analyze_efficiency(
        self,
        tool_calls: List[Dict[str, Any]],
        tool_results: List[str],
    ) -> List[CritiqueItem]:
        critiques: List[CritiqueItem] = []
        read_paths: Dict[str, int] = {}
        for i, tc in enumerate(tool_calls):
            skill = tc.get("skill_name", tc.get("name", ""))
            args = tc.get("args", {})
            if skill in ("read_file", "file_read", "cat_file"):
                path = args.get("path", args.get("file_path", ""))
                if path:
                    read_paths[path] = read_paths.get(path, 0) + 1
                    if read_paths[path] > 2:
                        critiques.append(CritiqueItem(
                            category="redundant_reads",
                            severity="low",
                            description=f"File {path} read {read_paths[path]} times",
                            suggestion="Cache file reads or batch them",
                            affected_step=i,
                        ))
        return critiques

    def _extract_strengths(self, final_output: str, tool_results: List[str]) -> List[str]:
        strengths: List[str] = []
        all_text = final_output + " " + " ".join(tool_results)
        for pattern in _STRENGTH_PATTERNS:
            if pattern.search(all_text):
                strengths.append(pattern.pattern.split("|")[0].replace(r".", " "))
        if len(tool_results) > 0 and all("error" not in r.lower() for r in tool_results):
            strengths.append("All tool calls succeeded")
        return strengths

    def _compute_score(
        self,
        critiques: List[CritiqueItem],
        strengths: List[str],
        tool_calls: List[Dict[str, Any]],
        tool_results: List[str],
    ) -> float:
        score = 1.0
        severity_weights = {"critical": 0.3, "high": 0.15, "medium": 0.08, "low": 0.03}
        for c in critiques:
            score -= severity_weights.get(c.severity, 0.05)
        score += len(strengths) * 0.05
        if tool_results:
            success_rate = sum(1 for r in tool_results if "error" not in r.lower()) / len(tool_results)
            score = score * 0.6 + success_rate * 0.4
        return max(0.0, min(1.0, score))

    def _suggest_fix(self, category: str) -> str:
        suggestions = {
            "error_handling": "Add explicit error handling and retry logic",
            "incomplete_code": "Complete all TODO/FIXME items before marking task done",
            "maintainability": "Extract hardcoded values to configuration",
            "test_coverage": "Add unit tests for the implemented functionality",
            "security": "Review and fix security vulnerabilities immediately",
            "performance": "Profile and optimize the identified performance bottleneck",
            "technical_debt": "Plan migration away from deprecated APIs",
        }
        return suggestions.get(category, "Review and improve")

    def _generate_summary(
        self,
        task_description: str,
        tool_calls: List[Dict[str, Any]],
        critiques: List[CritiqueItem],
        strengths: List[str],
    ) -> str:
        parts = [
            f"Task: {task_description[:200]}",
            f"Tool calls: {len(tool_calls)}",
            f"Critiques: {len(critiques)} ({sum(1 for c in critiques if c.severity == 'critical')} critical)",
            f"Strengths: {len(strengths)}",
        ]
        if critiques:
            top = sorted(critiques, key=lambda c: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(c.severity, 4))
            parts.append(f"Top issue: {top[0].category} — {top[0].description}")
        return " | ".join(parts)

    def _write_critique_md(self, result: ReflectionResult) -> None:
        file_path = os.path.join(self._output_dir, f"critique_{result.reflection_id}.md")
        lines: List[str] = [
            f"# Self-Reflection Report",
            f"",
            f"- **Session**: {result.session_id}",
            f"- **Time**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(result.timestamp))}",
            f"- **Score**: {result.overall_score:.2f}/1.0",
            f"- **Task**: {result.task_summary}",
            f"",
            f"## Strengths",
            f"",
        ]
        for s in result.strengths:
            lines.append(f"- {s}")
        lines.append("")
        lines.append("## Critiques")
        lines.append("")
        for c in result.critiques:
            lines.append(f"- **[{c.severity.upper()}] {c.category}**: {c.description}")
            lines.append(f"  - Suggestion: {c.suggestion}")
        lines.append("")
        lines.append("## Suggested Improvements")
        lines.append("")
        for imp in result.improvements:
            lines.append(f"- {imp}")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            pass

    def _store_to_memory(self, result: ReflectionResult) -> None:
        if self._memory_system is None:
            return
        try:
            if hasattr(self._memory_system, 'store'):
                self._memory_system.store(
                    layer="session",
                    key=f"reflection:{result.reflection_id}",
                    value=result.to_dict(),
                    metadata={"tags": ["reflection", "critique"], "importance": 0.7},
                )
            elif hasattr(self._memory_system, 'add'):
                self._memory_system.add(
                    content=json.dumps(result.to_dict(), ensure_ascii=False),
                    category="reflection",
                )
        except Exception:
            pass
