from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCallRecord:
    skill_name: str = ""
    args_hash: str = ""
    timestamp: float = 0.0
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LoopDetectResult:
    is_loop: bool = False
    loop_type: str = ""
    loop_skill: str = ""
    consecutive_same: int = 0
    consecutive_skill: int = 0
    consecutive_file_read: int = 0
    total_calls: int = 0
    empty_result_streak: int = 0
    loop_detail: str = ""


LOOP_BREAK_PROMPT = (
    "你已经读取了足够的文件，请根据已有信息回答用户问题。"
    "不要再调用更多工具，直接给出基于已收集信息的回答。"
)

MAX_TOTAL_CALLS = 15
MAX_CONSECUTIVE_SAME = 2
MAX_CONSECUTIVE_SKILL = 4
MAX_CONSECUTIVE_FILE_READ = 6
MAX_EMPTY_RESULTS = 2

_FILE_READ_SKILLS = frozenset({
    "file_read", "read_file", "cat_file", "get_file_content",
    "file_service", "open_file", "view_file",
})


class LoopDetector:
    def __init__(
        self,
        max_total_calls: int = MAX_TOTAL_CALLS,
        max_consecutive_same: int = MAX_CONSECUTIVE_SAME,
        max_consecutive_skill: int = MAX_CONSECUTIVE_SKILL,
        max_consecutive_file_read: int = MAX_CONSECUTIVE_FILE_READ,
        max_empty_results: int = MAX_EMPTY_RESULTS,
    ) -> None:
        self._lock = threading.Lock()
        self._history: List[ToolCallRecord] = []
        self._max_total_calls = max_total_calls
        self._max_consecutive_same = max_consecutive_same
        self._max_consecutive_skill = max_consecutive_skill
        self._max_consecutive_file_read = max_consecutive_file_read
        self._max_empty_results = max_empty_results
        self._loop_detected_count = 0
        self._result_history: List[bool] = []

    def record(self, skill_name: str, args: Dict[str, Any]) -> LoopDetectResult:
        with self._lock:
            args_hash = self._hash_args(args)
            record = ToolCallRecord(
                skill_name=skill_name,
                args_hash=args_hash,
                timestamp=time.time(),
                args=args,
            )
            self._history.append(record)
            result = self._detect()
            return result

    def _detect(self) -> LoopDetectResult:
        total = len(self._history)
        result = LoopDetectResult(total_calls=total)

        if total == 0:
            return result

        if total > self._max_total_calls:
            result.is_loop = True
            result.loop_type = "total_limit"
            result.loop_detail = f"总调用 {total} 次超过上限 {self._max_total_calls}"
            self._loop_detected_count += 1
            return result

        consecutive_same = self._count_consecutive_same()
        result.consecutive_same = consecutive_same
        if consecutive_same >= self._max_consecutive_same:
            result.is_loop = True
            result.loop_type = "same_call"
            result.loop_skill = self._history[-1].skill_name if self._history else ""
            result.loop_detail = f"连续 {consecutive_same} 次调用相同工具"
            self._loop_detected_count += 1
            return result

        consecutive_skill = self._count_consecutive_skill()
        result.consecutive_skill = consecutive_skill
        if consecutive_skill >= self._max_consecutive_skill:
            result.is_loop = True
            result.loop_type = "skill_limit"
            result.loop_skill = self._history[-1].skill_name if self._history else ""
            result.loop_detail = f"连续 {consecutive_skill} 次调用同类工具"
            self._loop_detected_count += 1
            return result

        consecutive_file_read = self._count_consecutive_file_read()
        result.consecutive_file_read = consecutive_file_read
        if consecutive_file_read >= self._max_consecutive_file_read:
            result.is_loop = True
            result.loop_type = "file_read_limit"
            result.loop_skill = self._history[-1].skill_name if self._history else ""
            result.loop_detail = f"最近 10 次调用中有 {consecutive_file_read} 次文件读取"
            self._loop_detected_count += 1
            return result

        empty_streak = self._count_empty_result_streak()
        result.empty_result_streak = empty_streak
        if empty_streak >= self._max_empty_results:
            result.is_loop = True
            result.loop_type = "empty_result_limit"
            result.loop_skill = self._history[-1].skill_name if self._history else ""
            result.loop_detail = "连续多次调用返回空结果"
            self._loop_detected_count += 1
            return result

        recent_skills = [r.skill_name for r in self._history[-8:]]
        if len(recent_skills) >= 6:
            from collections import Counter
            skill_counts = Counter(recent_skills)
            most_common_skill, count = skill_counts.most_common(1)[0]
            if count >= 6:
                result.is_loop = True
                result.loop_type = "high_frequency"
                result.loop_skill = most_common_skill
                result.loop_detail = f"最近 8 次调用中 {most_common_skill} 出现 {count} 次"
                self._loop_detected_count += 1
                return result

        return result

    def _count_consecutive_same(self) -> int:
        if not self._history:
            return 0
        last = self._history[-1]
        count = 1
        for i in range(len(self._history) - 2, -1, -1):
            rec = self._history[i]
            if rec.skill_name == last.skill_name and rec.args_hash == last.args_hash:
                count += 1
            else:
                break
        return count

    def _count_consecutive_skill(self) -> int:
        if not self._history:
            return 0
        last_name = self._history[-1].skill_name
        count = 1
        for i in range(len(self._history) - 2, -1, -1):
            if self._history[i].skill_name == last_name:
                count += 1
            else:
                break
        return count

    def _count_consecutive_file_read(self) -> int:
        if not self._history:
            return 0
        count = 0
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i].skill_name in _FILE_READ_SKILLS:
                count += 1
            else:
                break
        return count

    def _count_empty_result_streak(self) -> int:
        if not self._result_history:
            return 0
        count = 0
        for i in range(len(self._result_history) - 1, -1, -1):
            if not self._result_history[i]:
                count += 1
            else:
                break
        return count

    def get_break_prompt(self, loop_type: str) -> str:
        if loop_type == "file_read_limit":
            return LOOP_BREAK_PROMPT
        if loop_type == "same_call":
            return (
                "检测到你正在重复调用相同的工具和参数，请停止重复调用，"
                "直接根据已获取的信息回答用户问题。"
            )
        if loop_type == "skill_limit":
            return (
                f"该工具已连续调用次数过多，请改用其他工具或直接给出回答。"
            )
        if loop_type == "total_limit":
            return (
                "已达到单次对话工具调用上限，请根据已收集的所有信息生成总结回答。"
            )
        if loop_type == "empty_result_limit":
            return (
                "连续多次工具调用均未返回有效结果，请停止调用工具，"
                "直接根据已有信息回答，或告知用户无法完成。"
            )
        if loop_type == "high_frequency":
            return (
                "检测到某工具调用频率过高，请停止重复调用同一工具，"
                "基于已有信息直接回答用户问题。"
            )
        return LOOP_BREAK_PROMPT

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._loop_detected_count = 0

    def record_result(self, success: bool) -> LoopDetectResult:
        with self._lock:
            self._result_history.append(success)
            return self._detect()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_calls": len(self._history),
                "loop_detected_count": self._loop_detected_count,
                "max_total_calls": self._max_total_calls,
                "skills_called": list({r.skill_name for r in self._history}),
            }

    @staticmethod
    def _hash_args(args: Dict[str, Any]) -> str:
        try:
            serialized = str(sorted(args.items()))
            return hashlib.md5(serialized.encode()).hexdigest()[:12]
        except Exception:
            return "unknown"
