from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class MessageItem:
    role: str
    content: str
    metadata: Optional[Dict[str, object]] = None
    token_count: int = 0
    is_key_decision: bool = False


class CompressionTrigger:
    def __init__(
        self,
        token_threshold_pct: float = 0.8,
        message_threshold: int = 50,
    ) -> None:
        self.token_threshold_pct = token_threshold_pct
        self.message_threshold = message_threshold

    def should_compress(
        self,
        token_count: int,
        max_tokens: int,
        message_count: int,
    ) -> bool:
        if token_count > max_tokens * self.token_threshold_pct:
            return True
        if message_count > self.message_threshold:
            return True
        return False


_EN_DECISION_KEYWORDS = re.compile(
    r"\b(decided|confirmed|approved|rejected|created|deleted|error|fixed|resolved|changed|updated|agreed|cancelled|completed)\b",
    re.IGNORECASE,
)

_CN_DECISION_KEYWORDS = re.compile(
    r"(决定|确认|批准|拒绝|创建|删除|错误|修复|解决|更改|更新|同意|取消|完成|已定|敲定|采纳|否决)",
)

_SUMMARY_PROMPT_TEMPLATE = (
    "Summarize the following conversation history, preserving:\n"
    "1. All key decisions and their rationale\n"
    "2. Tool call results and outcomes\n"
    "3. Important context needed for future conversation\n\n"
    "Conversation history:\n{history}\n\nSummary:"
)


class SummaryGenerator:
    def __init__(self) -> None:
        self._decision_keywords_en = _EN_DECISION_KEYWORDS
        self._decision_keywords_cn = _CN_DECISION_KEYWORDS

    def generate_summary(
        self,
        messages: List[MessageItem],
        llm_callback: Optional[Callable[[str], str]] = None,
    ) -> str:
        if llm_callback is not None:
            return self._generate_with_llm(messages, llm_callback)
        return self._generate_with_extraction(messages)

    def _generate_with_llm(
        self,
        messages: List[MessageItem],
        llm_callback: Callable[[str], str],
    ) -> str:
        history = self._format_messages(messages)
        prompt = _SUMMARY_PROMPT_TEMPLATE.format(history=history)
        return llm_callback(prompt)

    def _generate_with_extraction(self, messages: List[MessageItem]) -> str:
        key_points: List[str] = []
        tool_results: List[str] = []

        for msg in messages:
            content = msg.content.strip()
            if not content:
                continue

            if msg.role == "tool" or (msg.metadata and msg.metadata.get("tool_name")):
                tool_results.append(f"[Tool:{msg.metadata.get('tool_name', 'unknown')}] {content[:300]}")
                continue

            has_en = self._decision_keywords_en.search(content)
            has_cn = self._decision_keywords_cn.search(content)
            if has_en or has_cn or msg.is_key_decision:
                key_points.append(f"[{msg.role}] {content[:500]}")

        parts: List[str] = []
        if key_points:
            parts.append("Key decisions and events:")
            for i, pt in enumerate(key_points, 1):
                parts.append(f"  {i}. {pt}")
        if tool_results:
            parts.append("Tool call results:")
            for i, tr in enumerate(tool_results, 1):
                parts.append(f"  {i}. {tr}")

        if not parts:
            all_contents = [m.content.strip() for m in messages if m.content.strip()]
            combined = " ".join(all_contents)
            if len(combined) > 1000:
                combined = combined[:1000] + "..."
            parts.append(f"Context summary: {combined}")

        return "\n".join(parts)

    def _format_messages(self, messages: List[MessageItem]) -> str:
        lines: List[str] = []
        for msg in messages:
            role_label = msg.role.upper()
            if msg.metadata and msg.metadata.get("tool_name"):
                role_label = f"{role_label}[{msg.metadata['tool_name']}]"
            lines.append(f"{role_label}: {msg.content[:500]}")
        return "\n".join(lines)


class ContextCompressor:
    def __init__(self, keep_recent_rounds: int = 5) -> None:
        self.keep_recent_rounds = keep_recent_rounds
        self._decision_keywords_en = _EN_DECISION_KEYWORDS
        self._decision_keywords_cn = _CN_DECISION_KEYWORDS
        self._state_path: str = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "agent_completion_state.json",
        )
        self._session_id: str = ""
        self._prev_completed: List[Dict[str, object]] = []
        self._todos: List[Dict[str, object]] = []
        self._load_completion_state()

    def _load_completion_state(self) -> None:
        try:
            if os.path.exists(self._state_path):
                with open(self._state_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                for session in state.get("sessions", []):
                    self._prev_completed.extend(session.get("completed_tasks", []))
        except Exception:
            self._prev_completed = []

    def _save_completion_state(self) -> None:
        completed_tasks: List[Dict[str, object]] = []
        for todo in self._todos:
            content = str(todo.get("content", ""))
            if any(kw in content.lower() for kw in ("done", "completed", "完成", "[done]")):
                completed_tasks.append({
                    "id": todo.get("id", ""),
                    "content": content,
                    "ts": int(time.time()),
                })

        try:
            existing: Dict[str, object] = {"sessions": []}
            if os.path.exists(self._state_path):
                with open(self._state_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
        except Exception:
            existing = {"sessions": []}

        sessions = existing.get("sessions", [])
        found = False
        for session in sessions:
            if session.get("sid") == self._session_id:
                existing_tasks = session.get("completed_tasks", [])
                existing_ids = {t.get("id") for t in existing_tasks if isinstance(t, dict)}
                for ct in completed_tasks:
                    if ct.get("id") not in existing_ids:
                        existing_tasks.append(ct)
                session["completed_tasks"] = existing_tasks
                found = True
                break
        if not found and self._session_id:
            sessions.append({
                "sid": self._session_id,
                "completed_tasks": completed_tasks,
            })
        existing["sessions"] = sessions

        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _mark_prev_completed_in_summary(self, summary_text: str) -> str:
        if not self._prev_completed:
            return summary_text
        markers: List[str] = []
        for task in self._prev_completed:
            content = str(task.get("content", ""))
            short = content[:60]
            markers.append(f"[DONE-之前完成] {short}")
        prefix = "\n".join(markers)
        return f"{prefix}\n{summary_text}"

    def compress(
        self,
        messages: List[MessageItem],
        max_tokens: int,
        llm_callback: Optional[Callable[[str], str]] = None,
    ) -> List[MessageItem]:
        if not messages:
            return messages

        for msg in messages:
            if msg.role == "user" and msg.content:
                self._todos.append({"id": str(id(msg)), "content": msg.content})

        messages = self._detect_key_decisions(messages)

        system_msgs: List[MessageItem] = []
        rest: List[MessageItem] = []

        for msg in messages:
            if msg.role == "system":
                system_msgs.append(msg)
            else:
                rest.append(msg)

        if not rest:
            return messages

        recent_count = self.keep_recent_rounds * 2
        recent = rest[-recent_count:] if len(rest) > recent_count else rest[:]
        older = rest[:-recent_count] if len(rest) > recent_count else []

        key_decision_msgs: List[MessageItem] = []
        compressible: List[MessageItem] = []

        for msg in older:
            if msg.is_key_decision:
                key_decision_msgs.append(msg)
            else:
                compressible.append(msg)

        if not compressible:
            result = system_msgs + key_decision_msgs + recent
            self._recount_tokens(result)
            return result

        generator = SummaryGenerator()
        summary_text = generator.generate_summary(compressible, llm_callback)
        original_count = len(compressible)

        summary_msg = MessageItem(
            role="system",
            content=self._mark_prev_completed_in_summary(summary_text),
            metadata={"compressed": True, "original_count": original_count},
            token_count=self._estimate_tokens(summary_text),
            is_key_decision=False,
        )

        result = system_msgs + [summary_msg] + key_decision_msgs + recent
        self._recount_tokens(result)
        self._save_completion_state()
        return result

    def progressive_compress(
        self,
        messages: List[MessageItem],
        max_tokens: int,
        llm_callback: Optional[Callable[[str], str]] = None,
    ) -> List[MessageItem]:
        result = self.compress(messages, max_tokens, llm_callback)
        trigger = CompressionTrigger()

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            total_tokens = sum(m.token_count for m in result)
            total_messages = len(result)

            if not trigger.should_compress(total_tokens, max_tokens, total_messages):
                break

            non_system = [m for m in result if m.role != "system" and not (m.metadata and m.metadata.get("compressed"))]
            if not non_system:
                break

            compressible = non_system[:max(1, len(non_system) // 3)]
            compressible = [m for m in compressible if not m.is_key_decision]
            if not compressible:
                break

            generator = SummaryGenerator()
            summary_text = generator.generate_summary(compressible, llm_callback)

            summary_msg = MessageItem(
                role="system",
                content=summary_text,
                metadata={"compressed": True, "original_count": len(compressible)},
                token_count=self._estimate_tokens(summary_text),
                is_key_decision=False,
            )

            compressible_ids = set(id(m) for m in compressible)
            result = [m for m in result if id(m) not in compressible_ids]
            result.insert(len([m for m in result if m.role == "system"]), summary_msg)

            iteration += 1

        self._recount_tokens(result)
        return result

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        cn_chars = len(re.findall(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', text))
        en_chars = len(text) - cn_chars
        return (en_chars // 4) + (cn_chars // 2)

    def _detect_key_decisions(self, messages: List[MessageItem]) -> List[MessageItem]:
        for msg in messages:
            if msg.is_key_decision:
                continue
            if msg.role == "tool":
                continue
            content = msg.content
            if self._decision_keywords_en.search(content) or self._decision_keywords_cn.search(content):
                msg.is_key_decision = True
        return messages

    def _recount_tokens(self, messages: List[MessageItem]) -> None:
        for msg in messages:
            if msg.token_count == 0:
                msg.token_count = self._estimate_tokens(msg.content)


class CompressionQualityEvaluator:
    def evaluate(
        self,
        original_messages: List[MessageItem],
        compressed_messages: List[MessageItem],
        summary: str,
    ) -> Dict[str, object]:
        original_tokens = sum(m.token_count for m in original_messages)
        compressed_tokens = sum(m.token_count for m in compressed_messages)

        if original_tokens > 0:
            token_reduction_pct = round((1.0 - compressed_tokens / original_tokens) * 100, 2)
        else:
            token_reduction_pct = 0.0

        total_key_decisions = sum(1 for m in original_messages if m.is_key_decision)
        preserved_key_msgs = [m for m in compressed_messages if m.is_key_decision]

        summary_lower = summary.lower()
        preserved_from_summary = 0
        for m in original_messages:
            if m.is_key_decision and m not in compressed_messages:
                snippet = m.content[:80].lower()
                if snippet and snippet in summary_lower:
                    preserved_from_summary += 1

        key_decisions_preserved = len(preserved_key_msgs) + preserved_from_summary

        if total_key_decisions > 0:
            completeness_score = round(min(1.0, key_decisions_preserved / total_key_decisions), 4)
        else:
            completeness_score = 1.0

        return {
            "token_reduction_pct": token_reduction_pct,
            "key_decisions_preserved": key_decisions_preserved,
            "total_key_decisions": total_key_decisions,
            "completeness_score": completeness_score,
        }


class CompressionManager:
    def __init__(
        self,
        token_threshold_pct: float = 0.8,
        message_threshold: int = 50,
        keep_recent_rounds: int = 5,
    ) -> None:
        self._lock = threading.Lock()
        self._trigger = CompressionTrigger(
            token_threshold_pct=token_threshold_pct,
            message_threshold=message_threshold,
        )
        self._compressor = ContextCompressor(keep_recent_rounds=keep_recent_rounds)
        self._evaluator = CompressionQualityEvaluator()
        self._last_summary: str = ""
        self._last_report: Dict[str, object] = {}
        self._last_original: List[MessageItem] = []
        self._last_compressed: List[MessageItem] = []

    def auto_compress(
        self,
        messages: List[MessageItem],
        max_tokens: int,
        llm_callback: Optional[Callable[[str], str]] = None,
    ) -> List[MessageItem]:
        total_tokens = sum(m.token_count for m in messages)
        message_count = len(messages)

        if not self._trigger.should_compress(total_tokens, max_tokens, message_count):
            return messages

        with self._lock:
            self._last_original = list(messages)
            compressed = self._compressor.progressive_compress(messages, max_tokens, llm_callback)
            self._last_compressed = list(compressed)

            summary_msg = None
            for m in compressed:
                if m.metadata and m.metadata.get("compressed"):
                    summary_msg = m
                    break

            self._last_summary = summary_msg.content if summary_msg else ""
            self._last_report = self._evaluator.evaluate(
                self._last_original, self._last_compressed, self._last_summary,
            )
            self._last_report["original_count"] = len(self._last_original)
            self._last_report["compressed_count"] = len(self._last_compressed)
            self._last_report["timestamp"] = time.time()

            return compressed

    def get_compression_report(self) -> Dict[str, object]:
        with self._lock:
            return dict(self._last_report)

    def get_summary_preview(self) -> str:
        with self._lock:
            return self._last_summary

    def edit_summary(self, new_summary: str) -> None:
        with self._lock:
            if not self._last_compressed:
                return
            for m in self._last_compressed:
                if m.metadata and m.metadata.get("compressed"):
                    m.content = new_summary
                    m.token_count = self._compressor._estimate_tokens(new_summary)
                    break
            self._last_summary = new_summary
