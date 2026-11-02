"""
B-P3-003: Memory Distiller Service

LLM-assisted distillation of session memory,
importance scoring, auto-distill triggers,
and v6.0-S C-1 pattern extraction (preferences/decisions/tech-stack).
"""
from __future__ import annotations

import re
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .memory_service import MemoryService


@dataclass
class DistillResult:
    original_tokens: int = 0
    compressed_tokens: int = 0
    summary: str = ""
    key_points: List[str] = field(default_factory=list)
    preferences: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    tech_stack: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "originalTokens": self.original_tokens,
            "compressedTokens": self.compressed_tokens,
            "summary": self.summary,
            "keyPoints": self.key_points,
            "preferences": self.preferences,
            "decisions": self.decisions,
            "techStack": self.tech_stack,
        }


_PREFERENCE_PATTERNS = [
    re.compile(r"(?:我喜欢|偏好|倾向|prefer|favor|like to)\s*(.{2,40})"),
    re.compile(r"(?:不要|避免|never|avoid|don'?t)\s*(.{2,40})"),
]

_DECISION_PATTERNS = [
    re.compile(r"(?:决定|选择|选用|decided|chose|selected)\s*(.{2,40})"),
    re.compile(r"(?:采用|使用|use|adopt)\s*(.{2,40})\s*(?:方案|架构|方案|approach)"),
]

_TECH_PATTERNS = [
    re.compile(r"(?:Python|TypeScript|ArkTS|Rust|Go|Java|C\+\+|React|Vue|Flutter|Qt|PyQt)"),
    re.compile(r"(?:框架|库|framework|library|SDK|引擎|engine)\s*[:：]?\s*(.{2,30})"),
    re.compile(r"(?:数据库|database|DB)\s*[:：]?\s*(\w+)"),
]


class MemoryDistillerService:
    TOKEN_THRESHOLD: int = 4000
    MAX_KEY_POINTS: int = 10
    DEDUP_SIMILARITY: float = 0.85

    def __init__(self, memory_service: MemoryService) -> None:
        self._memory = memory_service
        self._distill_lock = threading.Lock()
        self._last_distill_time = 0.0
        self._dedup_cache: List[str] = []

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 2)

    def distill(self, entries: List[Dict[str, Any]]) -> DistillResult:
        total_tokens = 0
        for e in entries:
            total_tokens += self.estimate_tokens(e.get("content", ""))

        key_points = self._extract_key_points(entries)
        prefs = self._extract_patterns(entries, _PREFERENCE_PATTERNS)
        decisions = self._extract_patterns(entries, _DECISION_PATTERNS)
        tech_stack = self._extract_tech_stack(entries)

        parts = []
        if prefs:
            parts.append("[偏好] " + "; ".join(prefs))
        if decisions:
            parts.append("[决策] " + "; ".join(decisions))
        if tech_stack:
            parts.append("[技术栈] " + "; ".join(tech_stack))
        if key_points:
            parts.append("[要点] " + "; ".join(key_points[:5]))

        summary = " | ".join(parts)
        compressed_tokens = self.estimate_tokens(summary)

        return DistillResult(
            original_tokens=total_tokens,
            compressed_tokens=compressed_tokens,
            summary=summary,
            key_points=key_points,
            preferences=prefs,
            decisions=decisions,
            tech_stack=tech_stack,
        )

    def _extract_key_points(self, entries: List[Dict[str, Any]]) -> List[str]:
        points: List[str] = []
        for e in entries:
            content = e.get("content", "")
            if content:
                points.append(content[:80])
            if len(points) >= self.MAX_KEY_POINTS:
                break
        return points

    def _extract_patterns(self, entries: List[Dict[str, Any]], patterns: List[re.Pattern]) -> List[str]:
        found: List[str] = []
        for e in entries:
            content = e.get("content", "")
            for pat in patterns:
                for m in pat.finditer(content):
                    text = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    if text and not self._is_near_duplicate(text, found):
                        found.append(text)
                    if len(found) >= 10:
                        return found
        return found

    def _extract_tech_stack(self, entries: List[Dict[str, Any]]) -> List[str]:
        techs: List[str] = []
        for e in entries:
            content = e.get("content", "")
            for pat in _TECH_PATTERNS:
                for m in pat.finditer(content):
                    text = m.group(0).strip()
                    if text and text not in techs:
                        techs.append(text)
                    if len(techs) >= 15:
                        return techs
        return techs

    def _is_near_duplicate(self, text: str, existing: List[str]) -> bool:
        text_lower = text.lower()
        for ex in existing:
            ex_lower = ex.lower()
            overlap = sum(1 for c in text_lower if c in ex_lower) / max(len(text_lower), 1)
            if overlap >= self.DEDUP_SIMILARITY:
                return True
        return False

    def assess_importance(self, entry: Dict[str, Any]) -> int:
        score = 0
        category = entry.get("category", "")
        if category == "preference":
            score += 3
        elif category == "fact":
            score += 2
        elif category == "habit":
            score += 1

        created_at = entry.get("createdAt", 0)
        age_hours = (time.time() - created_at) / 3600
        if age_hours < 1:
            score += 2
        elif age_hours < 24:
            score += 1
        return score

    def should_distill(self, user_id: str = "default") -> bool:
        memories = self._memory.list_memories(user_id=user_id, limit=200)
        total = sum(self.estimate_tokens(m.get("content", "")) for m in memories)
        return total > self.TOKEN_THRESHOLD

    def auto_distill(self, user_id: str = "default") -> Optional[DistillResult]:
        if not self.should_distill(user_id):
            return None
        with self._distill_lock:
            if time.time() - self._last_distill_time < 30:
                return None
            memories = self._memory.list_memories(user_id=user_id, limit=200)
            result = self.distill(memories)
            if self._is_near_duplicate(result.summary, self._dedup_cache):
                return None
            self._dedup_cache.append(result.summary)
            if len(self._dedup_cache) > 20:
                self._dedup_cache = self._dedup_cache[-10:]
            self._memory.add(result.summary, category="summary", user_id=user_id)
            self._last_distill_time = time.time()
            return result

    def auto_distill_async(self, user_id: str = "default") -> None:
        """v6.0-S C-1: 后台线程执行自动蒸馏。"""
        t = threading.Thread(target=self._do_async_distill, args=(user_id,), daemon=True)
        t.start()

    def _do_async_distill(self, user_id: str) -> None:
        try:
            self.auto_distill(user_id)
        except Exception:
            pass
