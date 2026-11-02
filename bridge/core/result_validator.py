from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ValidationResult:
    score: int = 0
    covers_all_tools: bool = False
    answers_question: bool = False
    length_appropriate: bool = False
    issues: List[str] = field(default_factory=list)
    recommendation: str = ""


class ResultValidator:
    def __init__(self, min_score: int = 3, max_retries: int = 1) -> None:
        self._min_score = min_score
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._validation_history: List[Dict[str, Any]] = []

    def validate(
        self,
        summary: str,
        user_question: str,
        tool_calls: List[Dict[str, Any]],
        tool_results: List[str],
    ) -> ValidationResult:
        result = ValidationResult()

        covers = self._check_tool_coverage(summary, tool_calls)
        result.covers_all_tools = covers

        answers = self._check_answers_question(summary, user_question)
        result.answers_question = answers

        length_ok = self._check_length(summary)
        result.length_appropriate = length_ok

        score = 0
        if covers:
            score += 2
        if answers:
            score += 2
        if length_ok:
            score += 1

        issues: List[str] = []
        if not covers:
            issues.append("总结未覆盖所有工具调用结果")
        if not answers:
            issues.append("总结未直接回答用户问题")
        if not length_ok:
            issues.append("总结长度不合理")

        result.score = score
        result.issues = issues

        if score >= 4:
            result.recommendation = "分析完成"
        elif score >= 3:
            result.recommendation = "部分完成"
        else:
            result.recommendation = "需要更多信息"

        with self._lock:
            self._validation_history.append({
                "timestamp": time.time(),
                "score": score,
                "covers_all_tools": covers,
                "answers_question": answers,
                "length_appropriate": length_ok,
                "issues": issues,
                "recommendation": result.recommendation,
            })

        return result

    def should_retry(self, result: ValidationResult) -> bool:
        return result.score < self._min_score

    def generate_fallback_summary(
        self,
        tool_calls: List[Dict[str, Any]],
        tool_results: List[str],
        user_question: str,
    ) -> str:
        parts: List[str] = []
        parts.append(f"关于「{user_question}」，已分析部分文件，以下是初步结论：\n")

        skill_names = set()
        for tc in tool_calls:
            func = tc.get("function", tc)
            name = func.get("name", tc.get("skill_name", "unknown"))
            skill_names.add(name)

        parts.append(f"调用了 {len(skill_names)} 种工具，共 {len(tool_calls)} 次调用。")

        for i, (tc, tr) in enumerate(zip(tool_calls, tool_results)):
            func = tc.get("function", tc)
            name = func.get("name", tc.get("skill_name", "unknown"))
            key_info = tr[:200].strip() if tr else "（无输出）"
            parts.append(f"\n{i + 1}. [{name}] {key_info}")

        parts.append("\n以上为基于已收集信息的初步分析。")

        return "\n".join(parts)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            if not self._validation_history:
                return {"total_validations": 0, "avg_score": 0.0}
            scores = [h["score"] for h in self._validation_history]
            return {
                "total_validations": len(self._validation_history),
                "avg_score": round(sum(scores) / len(scores), 2),
                "last_score": scores[-1],
            }

    def _check_tool_coverage(self, summary: str, tool_calls: List[Dict[str, Any]]) -> bool:
        if not tool_calls:
            return True
        mentioned = 0
        for tc in tool_calls:
            func = tc.get("function", tc)
            name = func.get("name", tc.get("skill_name", ""))
            args = func.get("arguments", func.get("args", {}))
            if isinstance(args, str):
                try:
                    import json
                    args = json.loads(args)
                except Exception:
                    args = {}
            if name and name in summary:
                mentioned += 1
                continue
            if isinstance(args, dict):
                for v in args.values():
                    if isinstance(v, str) and v in summary:
                        mentioned += 1
                        break
        coverage = mentioned / len(tool_calls) if tool_calls else 1.0
        return coverage >= 0.5

    def _check_answers_question(self, summary: str, user_question: str) -> bool:
        if not user_question:
            return True
        question_words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', user_question.lower())
        if not question_words:
            return True
        summary_lower = summary.lower()
        matched = sum(1 for w in question_words if w in summary_lower)
        return matched / len(question_words) >= 0.3

    @staticmethod
    def _check_length(summary: str) -> bool:
        return 20 <= len(summary) <= 5000
