from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

COMPACTION_SYSTEM_PROMPT = (
    "You are a context compaction system. Compress conversation history by:\n"
    "1. Extracting key user requirements and constraints\n"
    "2. Summarizing tool call results into concise bullet points\n"
    "3. Preserving important decisions and conclusions\n"
    "4. Removing redundant information\n"
    "Output the compressed context in markdown format."
)

COMPACTION_USER_PROMPT = (
    "Please compress the following conversation history. "
    "Preserve all important information including:\n"
    "- User's original question and requirements\n"
    "- Key findings from tool calls\n"
    "- Decisions made during the conversation\n"
    "- Code snippets that are still relevant\n\n"
    "Conversation to compress:\n{conversation}\n\nCompressed version:"
)

_IMPORTANT_USER_KEYWORDS = re.compile(
    r"(分析|对比|为什么|如何|必须|要求|需要|解释|比较|检查|修复|优化|实现|设计)"
)

_EN_DECISION_KW = re.compile(
    r"\b(decided|confirmed|approved|rejected|created|deleted|error|fixed|resolved|changed|updated)\b",
    re.IGNORECASE,
)
_CN_DECISION_KW = re.compile(
    r"(决定|确认|批准|拒绝|创建|删除|错误|修复|解决|更改|更新|完成|发现|检测到)"
)


@dataclass
class CompressionStats:
    original_tokens: int = 0
    compressed_tokens: int = 0
    compression_ratio: float = 0.0
    messages_compressed: int = 0
    important_info_preserved: bool = True


class ContextCompactor:
    def __init__(
        self,
        max_tokens: int = 4096,
        compression_threshold: float = 0.7,
        keep_recent: int = 5,
    ) -> None:
        self._engine: Optional[Any] = None
        self._max_tokens = max_tokens
        self._threshold = compression_threshold
        self._keep_recent = keep_recent
        self._lock = threading.Lock()
        self._history: List[CompressionStats] = []
        self._turn_threshold: int = 15
        self._last_compression_info: Optional[Dict[str, Any]] = None

    def set_engine(self, engine: Any) -> None:
        self._engine = engine

    def should_compress(self, current_tokens: int, message_count: int = 0) -> bool:
        if current_tokens > self._max_tokens * self._threshold:
            return True
        if message_count > 0 and message_count >= self._turn_threshold * 2:
            return True
        return False

    def get_last_compression_info(self) -> Optional[Dict[str, Any]]:
        return self._last_compression_info

    def compact(self, messages: List[Dict[str, Any]],
                llm_callback: Optional[Callable[[str], str]] = None) -> List[Dict[str, Any]]:
        if not messages:
            return messages

        original_tokens = self._estimate_tokens_messages(messages)
        if not self.should_compress(original_tokens):
            return messages

        try:
            compressed = self._do_compress(messages, llm_callback)
        except Exception as e:
            logger.warning(f"Compaction failed, using fallback: {e}")
            compressed = self._fallback_compress(messages)

        compressed_tokens = self._estimate_tokens_messages(compressed)
        ratio = round(1.0 - compressed_tokens / max(original_tokens, 1), 4)

        with self._lock:
            self._history.append(CompressionStats(
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                compression_ratio=ratio,
                messages_compressed=len(messages) - len(compressed),
            ))
            self._last_compression_info = {
                "original_tokens": original_tokens,
                "compressed_tokens": compressed_tokens,
                "ratio": ratio,
                "messages_removed": len(messages) - len(compressed),
                "kept_recent": self._keep_recent,
            }

        return compressed

    def _do_compress(self, messages: List[Dict[str, Any]],
                     llm_callback: Optional[Callable[[str], str]]) -> List[Dict[str, Any]]:
        system_msgs = [m for m in messages if m.get("role") == "system"]
        dialogue = [m for m in messages if m.get("role") != "system"]

        if not dialogue:
            return messages

        tool_summary = self._summarize_tool_results(dialogue)
        important_user = self._extract_important_user_messages(dialogue)
        important_assistant = self._extract_important_assistant_responses(dialogue)
        conversation_text = self._format_for_compression(dialogue, tool_summary)

        if llm_callback is not None:
            try:
                compressed_summary = llm_callback(
                    COMPACTION_USER_PROMPT.format(conversation=conversation_text)
                )
            except Exception:
                compressed_summary = self._rule_based_compress(conversation_text)
        elif self._engine is not None:
            try:
                compressed_summary = self._call_engine(conversation_text)
            except Exception:
                compressed_summary = self._rule_based_compress(conversation_text)
        else:
            compressed_summary = self._rule_based_compress(conversation_text)

        parts: List[str] = ["[压缩前的对话摘要]"]
        if important_user:
            parts.append("## 用户核心需求")
            for u in important_user:
                parts.append(f"- {u}")
        if important_assistant:
            parts.append("## 关键结论")
            for a in important_assistant:
                parts.append(f"- {a}")
        parts.append("## 详细摘要")
        parts.append(compressed_summary)

        summary_content = "\n".join(parts)

        result = list(system_msgs)
        result.append({
            "role": "user",
            "content": summary_content,
            "metadata": {"compressed": True, "original_count": len(dialogue)},
        })

        recent = dialogue[-self._keep_recent:] if len(dialogue) > self._keep_recent else []
        result.extend(recent)

        return result

    def _summarize_tool_results(self, messages: List[Dict[str, Any]]) -> str:
        tool_msgs = [
            m for m in messages
            if m.get("role") == "tool"
            or (m.get("role") == "assistant" and m.get("tool_calls"))
        ]
        if not tool_msgs:
            return ""
        parts = ["[工具调用摘要]"]
        for i, msg in enumerate(tool_msgs[:20], 1):
            content = msg.get("content", "")[:100]
            if content:
                parts.append(f"  {i}. {content}")
        return "\n".join(parts)

    def _extract_important_user_messages(self, messages: List[Dict[str, Any]]) -> List[str]:
        important: List[str] = []
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if _IMPORTANT_USER_KEYWORDS.search(content):
                important.append(content[:200])
        return important[-5:]

    def _extract_important_assistant_responses(self, messages: List[Dict[str, Any]]) -> List[str]:
        important: List[str] = []
        for msg in messages:
            if msg.get("role") != "assistant" or msg.get("tool_calls"):
                continue
            content = msg.get("content", "")
            if len(content) > 50 and (_EN_DECISION_KW.search(content) or _CN_DECISION_KW.search(content)):
                important.append(content[:200])
        return important[-3:]

    def _format_for_compression(self, messages: List[Dict[str, Any]],
                                tool_summary: str) -> str:
        parts: List[str] = []
        if tool_summary:
            parts.append(tool_summary)
            parts.append("")
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                parts.append(f"**User**: {content[:300]}")
            elif role == "assistant" and not msg.get("tool_calls"):
                parts.append(f"**Assistant**: {content[:300]}")
            elif role == "tool":
                parts.append(f"**Tool**: {content[:150]}")
        return "\n".join(parts)

    def _call_engine(self, text: str) -> str:
        if self._engine is None:
            return self._rule_based_compress(text)
        msgs = [
            {"role": "system", "content": COMPACTION_SYSTEM_PROMPT},
            {"role": "user", "content": COMPACTION_USER_PROMPT.format(conversation=text)},
        ]
        return self._engine.chat(msgs)

    def _rule_based_compress(self, text: str) -> str:
        lines = text.split("\n")
        important: List[str] = []
        keywords = ["用户", "问题", "分析", "结论", "发现", "重要", "注意",
                     "必须", "Tool", "User", "Assistant", "关键", "决定", "修复"]
        for line in lines:
            if any(kw in line for kw in keywords) or len(line.strip()) > 50:
                important.append(line.strip())
        if len(important) > 50:
            important = important[:30] + ["...(省略中间部分)..."] + important[-20:]
        return "\n".join(important)

    def _fallback_compress(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        system_msgs = [m for m in messages if m.get("role") == "system"]
        important: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                continue
            if role == "user" or len(content) > 100:
                important.append(msg)
        if len(important) > 10:
            important = important[:5] + important[-5:]
        return system_msgs + important

    @staticmethod
    def _estimate_tokens_messages(messages: List[Dict[str, Any]]) -> int:
        total = 0
        for m in messages:
            content = m.get("content", "")
            cn = len(re.findall(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', content))
            en = len(content) - cn
            total += (en // 4) + (cn // 2)
        return total

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            if not self._history:
                return {"total_compressions": 0}
            latest = self._history[-1]
            avg_ratio = sum(
                1 - (h.compressed_tokens / max(h.original_tokens, 1))
                for h in self._history
            ) / len(self._history)
            return {
                "total_compressions": len(self._history),
                "avg_compression_ratio": round(avg_ratio, 3),
                "last_original_tokens": latest.original_tokens,
                "last_compressed_tokens": latest.compressed_tokens,
            }
