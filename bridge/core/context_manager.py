from __future__ import annotations

import re
import threading
import time
import hashlib
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


_MAX_TOOL_RESULT_TOKENS = 2000
_COMPRESSION_THRESHOLD_PCT = 0.8
_FORCED_COMPRESSION_PCT = 1.0
_WARNING_THRESHOLD_PCT = 0.8
_TOTAL_TOKEN_LIMIT = 200_000
_SINGLE_INPUT_LIMIT = 100_000
_MAX_SESSION_ROUNDS = 20
_SUMMARY_TEMPLATE = "读取文件 {path}，内容 {length} 字符，关键信息：{preview}"

_L1_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".lemoncode", "context_cache", "l1")


class TokenEstimator:
    _CN_PATTERN = re.compile(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]')
    _EN_WORD_PATTERN = re.compile(r'[a-zA-Z0-9]+')
    _CN_TOKEN_RATIO = 2.0
    _EN_WORD_TOKEN_RATIO = 1.3
    _PUNCT_TOKEN_RATIO = 0.5

    def __init__(self, tokenizer_callback: Optional[Callable[[str], int]] = None):
        self._tokenizer_callback = tokenizer_callback

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        if self._tokenizer_callback is not None:
            try:
                result = self._tokenizer_callback(text)
                if isinstance(result, int) and result > 0:
                    return result
            except Exception:
                pass
        return self._char_estimate(text)

    def _char_estimate(self, text: str) -> int:
        cn_chars = len(self._CN_PATTERN.findall(text))
        remaining = self._CN_PATTERN.sub("", text)
        en_words = len(self._EN_WORD_PATTERN.findall(remaining))
        en_word_chars = sum(len(w) for w in self._EN_WORD_PATTERN.findall(remaining))
        punct_chars = len(remaining) - en_word_chars
        tokens = int(cn_chars * self._CN_TOKEN_RATIO + en_words * self._EN_WORD_TOKEN_RATIO + punct_chars * self._PUNCT_TOKEN_RATIO)
        return max(tokens, 1)

    def estimate_messages(self, messages: List[Dict[str, Any]]) -> int:
        return sum(self.estimate(m.get("content", "")) for m in messages)


_DEFAULT_ESTIMATOR = TokenEstimator()


@dataclass
class CompressionLogEntry:
    timestamp: float = 0.0
    session_id: str = ""
    messages_compressed: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    reason: str = ""


class ContextLayer(ABC):
    @abstractmethod
    def get_messages(self) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def token_count(self) -> int:
        ...

    @abstractmethod
    def clear(self) -> None:
        ...

    @abstractmethod
    def load(self) -> bool:
        ...

    @abstractmethod
    def save(self) -> bool:
        ...


class L1PrefixCache(ContextLayer):
    def __init__(self, project_id: str = ""):
        self._project_id = project_id
        self._system_prompt: str = ""
        self._project_context: str = ""
        self._messages: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._hit_count: int = 0
        self._miss_count: int = 0
        self._cache_key: str = ""

    def set_system_prompt(self, prompt: str) -> None:
        with self._lock:
            self._system_prompt = prompt
            self._rebuild_messages()
            self._save_to_disk()

    def set_project_context(self, context: str, project_id: str = "") -> None:
        with self._lock:
            if project_id:
                self._project_id = project_id
            self._project_context = context
            self._rebuild_messages()
            self._save_to_disk()

    def load_from_disk(self, project_id: str = "") -> bool:
        with self._lock:
            pid = project_id or self._project_id
            if not pid:
                return False
            cache_path = os.path.join(_L1_CACHE_DIR, f"{hashlib.md5(pid.encode()).hexdigest()}.json")
            if not os.path.exists(cache_path):
                self._miss_count += 1
                return False
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._system_prompt = data.get("system_prompt", "")
                self._project_context = data.get("project_context", "")
                self._messages = data.get("messages", [])
                self._cache_key = data.get("cache_key", "")
                self._hit_count += 1
                return True
            except Exception:
                self._miss_count += 1
                return False

    def _save_to_disk(self) -> None:
        if not self._project_id:
            return
        os.makedirs(_L1_CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(_L1_CACHE_DIR, f"{hashlib.md5(self._project_id.encode()).hexdigest()}.json")
        current_key = hashlib.md5((self._system_prompt + self._project_context).encode()).hexdigest()
        if current_key == self._cache_key:
            return
        self._cache_key = current_key
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({
                    "system_prompt": self._system_prompt,
                    "project_context": self._project_context,
                    "messages": self._messages,
                    "cache_key": self._cache_key,
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _rebuild_messages(self) -> None:
        self._messages = []
        if self._system_prompt:
            self._messages.append({"role": "system", "content": self._system_prompt})
        if self._project_context:
            ctx_msg = {"role": "system", "content": "[Project Context]\n" + self._project_context}
            self._messages.append(ctx_msg)

    def get_messages(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._messages)

    def token_count(self) -> int:
        with self._lock:
            return _DEFAULT_ESTIMATOR.estimate_messages(self._messages)

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()
            self._system_prompt = ""
            self._project_context = ""

    def load(self) -> bool:
        return self.load_from_disk()

    def save(self) -> bool:
        with self._lock:
            self._save_to_disk()
        return True

    def hit_rate(self) -> float:
        total = self._hit_count + self._miss_count
        return self._hit_count / total if total > 0 else 0.0


class L2SessionCache(ContextLayer):
    def __init__(self, max_rounds: int = _MAX_SESSION_ROUNDS):
        self._max_rounds = max_rounds
        self._history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._round_count: int = 0

    def append(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            msg: Dict[str, Any] = {"role": role, "content": content}
            if metadata:
                msg["metadata"] = metadata
            self._history.append(msg)
            if role == "user":
                self._round_count += 1

    def get_messages(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history)

    def get_recent(self, rounds: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            r = rounds or self._max_rounds
            msgs_per_round = 2
            keep = r * msgs_per_round
            return list(self._history[-keep:]) if len(self._history) > keep else list(self._history)

    def token_count(self) -> int:
        with self._lock:
            return _DEFAULT_ESTIMATOR.estimate_messages(self._history)

    def round_count(self) -> int:
        with self._lock:
            return self._round_count

    def needs_compression(self) -> bool:
        with self._lock:
            return self._round_count > self._max_rounds

    def compress_older(self, summary: str) -> List[Dict[str, Any]]:
        with self._lock:
            keep_count = self._max_rounds * 2
            older = self._history[:-keep_count] if len(self._history) > keep_count else []
            if not older:
                return []
            summary_msg = {"role": "system", "content": "[Previous conversation summary]\n" + summary}
            self._history = [summary_msg] + self._history[-keep_count:]
            self._round_count = self._max_rounds
            return older

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self._round_count = 0

    def load(self) -> bool:
        return True

    def save(self) -> bool:
        return True


class L3BudgetCache:
    def __init__(self, total_limit: int = _TOTAL_TOKEN_LIMIT, single_input_limit: int = _SINGLE_INPUT_LIMIT):
        self._total_limit = total_limit
        self._single_input_limit = single_input_limit
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._lock = threading.RLock()
        self._warning_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._force_callbacks: List[Callable[[Dict[str, Any]], None]] = []

    def track_input(self, token_count: int) -> None:
        with self._lock:
            self._input_tokens += token_count
            self._check_thresholds()

    def track_output(self, token_count: int) -> None:
        with self._lock:
            self._output_tokens += token_count
            self._check_thresholds()

    def pre_estimate(self, estimated_input: int) -> Tuple[bool, str]:
        with self._lock:
            total = self._input_tokens + self._output_tokens
            if total + estimated_input > self._total_limit:
                return False, f"Token budget exceeded: current={total}, estimated={estimated_input}, limit={self._total_limit}"
            if estimated_input > self._single_input_limit:
                return False, f"Single input exceeds limit: estimated={estimated_input}, limit={self._single_input_limit}"
            return True, ""

    def usage(self) -> Dict[str, Any]:
        with self._lock:
            total = self._input_tokens + self._output_tokens
            pct = round(total / self._total_limit, 4) if self._total_limit > 0 else 0.0
            return {
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
                "total_tokens": total,
                "total_limit": self._total_limit,
                "usage_pct": pct,
                "warning": pct >= _WARNING_THRESHOLD_PCT,
                "forced": pct >= _FORCED_COMPRESSION_PCT,
            }

    def on_warning(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._warning_callbacks.append(callback)

    def on_force(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._force_callbacks.append(callback)

    def _check_thresholds(self) -> None:
        usage = self.usage()
        if usage["forced"]:
            for cb in self._force_callbacks:
                try:
                    cb(usage)
                except Exception:
                    pass
        elif usage["warning"]:
            for cb in self._warning_callbacks:
                try:
                    cb(usage)
                except Exception:
                    pass

    def reset(self) -> None:
        with self._lock:
            self._input_tokens = 0
            self._output_tokens = 0


class ContextManager:
    def __init__(self, max_tokens: int = 4096, reserved_tokens: int = 512):
        self._max_tokens = max_tokens
        self._reserved_tokens = reserved_tokens
        self._contexts: Dict[str, List[Dict[str, str]]] = {}
        self._lock = threading.Lock()
        self._compression_log: List[CompressionLogEntry] = []
        self._tool_result_max_tokens = _MAX_TOOL_RESULT_TOKENS
        self._compactor: Optional[Any] = None
        self._l1: L1PrefixCache = L1PrefixCache()
        self._l2_instances: Dict[str, L2SessionCache] = {}
        self._l3: L3BudgetCache = L3BudgetCache()
        self._compressor: Optional[Any] = None
        self._token_estimator: TokenEstimator = _DEFAULT_ESTIMATOR

    def set_max_tokens(self, max_tokens: int) -> None:
        self._max_tokens = max_tokens

    def check_token_budget(self, session_id: str = "") -> Dict[str, Any]:
        """检查 Token 预算状态"""
        if session_id and session_id in self._contexts:
            current_tokens = self._estimate_total_tokens(self._contexts[session_id])
        else:
            all_msgs = []
            for msgs in self._contexts.values():
                all_msgs.extend(msgs)
            current_tokens = self._estimate_total_tokens(all_msgs) if all_msgs else 0

        budget = self._max_tokens
        usage_ratio = current_tokens / budget if budget > 0 else 0.0

        status = {
            "current_tokens": current_tokens,
            "budget": budget,
            "usage_ratio": round(usage_ratio, 3),
            "status": "normal",
            "action": "none",
        }

        if usage_ratio >= 0.95:
            status["status"] = "critical"
            status["action"] = "force_compress"
        elif usage_ratio >= 0.8:
            status["status"] = "warning"
            status["action"] = "suggest_compress"

        return status

    def set_compactor(self, compactor: Any) -> None:
        self._compactor = compactor

    def set_compressor(self, compressor: Any) -> None:
        self._compressor = compressor

    def set_token_estimator(self, estimator: TokenEstimator) -> None:
        self._token_estimator = estimator

    def get_l1(self) -> L1PrefixCache:
        return self._l1

    def get_l2(self, session_id: str) -> L2SessionCache:
        if session_id not in self._l2_instances:
            self._l2_instances[session_id] = L2SessionCache()
        return self._l2_instances[session_id]

    def get_l3(self) -> L3BudgetCache:
        return self._l3

    def init_project_context(self, project_id: str, system_prompt: str, project_context: str) -> None:
        self._l1._project_id = project_id
        self._l1.set_system_prompt(system_prompt)
        self._l1.set_project_context(project_context, project_id)
        loaded = self._l1.load_from_disk(project_id)
        if not loaded:
            self._l1._rebuild_messages()

    def smart_truncate(self, session_id: str, llm_callback: Optional[Any] = None) -> List[Dict[str, str]]:
        messages = self._contexts.get(session_id, [])
        if not messages:
            return []
        estimated = self._estimate_total_tokens(messages)
        if self._compactor and self._compactor.should_compress(estimated):
            compressed = self._compactor.compact(messages, llm_callback)
            self._contexts[session_id] = compressed
            return compressed
        return self.truncate(session_id)

    def get_context(self, session_id: str) -> List[Dict[str, str]]:
        return self._contexts.get(session_id, [])

    def set_context(self, session_id: str, messages: List[Dict[str, str]]) -> None:
        self._contexts[session_id] = messages

    def append(self, session_id: str, role: str, content: str) -> None:
        if session_id not in self._contexts:
            self._contexts[session_id] = []
        content = self._truncate_tool_result(content, role)
        self._contexts[session_id].append({"role": role, "content": content})
        l2 = self.get_l2(session_id)
        l2.append(role, content)
        token_est = self._estimate_tokens(content)
        if role in ("user", "assistant"):
            self._l3.track_input(token_est)
        self._check_auto_compress(session_id, llm_callback=None)

    def add_message(self, session_id: str, role: str, content: str) -> None:
        self.append(session_id, role, content)

    def append_with_metadata(self, session_id: str, role: str, content: str,
                             metadata: Optional[Dict[str, Any]] = None) -> None:
        if session_id not in self._contexts:
            self._contexts[session_id] = []
        content = self._truncate_tool_result(content, role)
        msg: Dict[str, Any] = {"role": role, "content": content}
        if metadata:
            msg["metadata"] = metadata
        self._contexts[session_id].append(msg)
        l2 = self.get_l2(session_id)
        l2.append(role, content, metadata)
        token_est = self._estimate_tokens(content)
        if role in ("user", "assistant"):
            self._l3.track_input(token_est)

    def truncate(self, session_id: str, keep_system: bool = True) -> List[Dict[str, str]]:
        messages = self._contexts.get(session_id, [])
        if not messages:
            return []
        self._auto_compress_tool_results(session_id)
        messages = self._contexts.get(session_id, [])
        estimated = self._estimate_total_tokens(messages)
        limit = self._max_tokens - self._reserved_tokens
        if estimated <= limit:
            return messages
        system_msgs: List[Dict[str, str]] = []
        rest: List[Dict[str, str]] = []
        for m in messages:
            if m.get("role") == "system":
                system_msgs.append(m)
            else:
                rest.append(m)
        kept: List[Dict[str, str]] = []
        total = 0
        for m in reversed(rest):
            est = self._estimate_tokens(m.get("content", ""))
            if total + est > limit:
                break
            kept.insert(0, m)
            total += est
        result = system_msgs + kept
        self._contexts[session_id] = result
        return result

    def clear(self, session_id: str) -> None:
        if session_id in self._contexts:
            del self._contexts[session_id]
        if session_id in self._l2_instances:
            self._l2_instances[session_id].clear()

    def compress(self, session_id: str, summary: str) -> None:
        messages = self._contexts.get(session_id, [])
        system_msgs = [m for m in messages if m.get("role") == "system"]
        summary_msg = {"role": "system", "content": "[Previous conversation summary]\n" + summary}
        self._contexts[session_id] = system_msgs + [summary_msg]
        l2 = self.get_l2(session_id)
        l2.compress_older(summary)

    def get_compression_log(self, session_id: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            logs = list(self._compression_log)
        if session_id:
            logs = [l for l in logs if l.session_id == session_id]
        return [
            {
                "timestamp": l.timestamp,
                "sessionId": l.session_id,
                "messagesCompressed": l.messages_compressed,
                "tokensBefore": l.tokens_before,
                "tokensAfter": l.tokens_after,
                "reason": l.reason,
            }
            for l in logs[-limit:]
        ]

    def get_token_usage(self, session_id: str) -> Dict[str, Any]:
        messages = self._contexts.get(session_id, [])
        total = self._estimate_total_tokens(messages)
        pct = round(total / self._max_tokens, 4) if self._max_tokens > 0 else 0.0
        l3_usage = self._l3.usage()
        return {
            "total_tokens": total,
            "max_tokens": self._max_tokens,
            "usage_pct": pct,
            "message_count": len(messages),
            "needs_compression": pct > _COMPRESSION_THRESHOLD_PCT,
            "l3_input_tokens": l3_usage["input_tokens"],
            "l3_output_tokens": l3_usage["output_tokens"],
            "l3_usage_pct": l3_usage["usage_pct"],
        }

    def pre_check_budget(self, estimated_input_tokens: int) -> Tuple[bool, str]:
        return self._l3.pre_estimate(estimated_input_tokens)

    def get_full_context(self, session_id: str) -> List[Dict[str, Any]]:
        l1_msgs = self._l1.get_messages()
        l2_msgs = self.get_l2(session_id).get_recent()
        combined: List[Dict[str, Any]] = list(l1_msgs) + list(l2_msgs)
        return combined

    def _check_auto_compress(self, session_id: str, llm_callback: Optional[Any] = None) -> None:
        l2 = self.get_l2(session_id)
        if not l2.needs_compression():
            return
        l3_usage = self._l3.usage()
        if l3_usage["forced"]:
            self._force_compress(session_id, llm_callback)
        elif l2.round_count() > _MAX_SESSION_ROUNDS + 10:
            self._compress_older_rounds(session_id, llm_callback)

    def _compress_older_rounds(self, session_id: str, llm_callback: Optional[Any] = None) -> None:
        l2 = self.get_l2(session_id)
        older = l2.get_messages()[:-(_MAX_SESSION_ROUNDS * 2)] if len(l2.get_messages()) > _MAX_SESSION_ROUNDS * 2 else []
        if not older:
            return
        tokens_before = l2.token_count()
        summary = self._generate_summary(older, llm_callback)
        l2.compress_older(summary)
        tokens_after = l2.token_count()
        with self._lock:
            self._compression_log.append(CompressionLogEntry(
                timestamp=time.time(),
                session_id=session_id,
                messages_compressed=len(older),
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                reason="l2_round_compression",
            ))
        self.compress(session_id, summary)

    def _force_compress(self, session_id: str, llm_callback: Optional[Any] = None) -> None:
        messages = self._contexts.get(session_id, [])
        if not messages:
            return
        tokens_before = self._estimate_total_tokens(messages)
        summary = self._generate_summary(messages, llm_callback)
        system_msgs = [m for m in messages if m.get("role") == "system"]
        force_msg = {"role": "system", "content": "[Force-compressed context]\n" + summary}
        compressed = system_msgs + [force_msg]
        self._contexts[session_id] = compressed
        tokens_after = self._estimate_total_tokens(compressed)
        l2 = self.get_l2(session_id)
        l2.compress_older(summary)
        with self._lock:
            self._compression_log.append(CompressionLogEntry(
                timestamp=time.time(),
                session_id=session_id,
                messages_compressed=len(messages) - len(system_msgs),
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                reason="l3_force_compression",
            ))

    def _generate_summary(self, messages: List[Dict[str, Any]], llm_callback: Optional[Any] = None) -> str:
        if self._compressor is not None:
            try:
                from bridge.core.context_compressor import MessageItem, SummaryGenerator
                items = []
                for m in messages:
                    items.append(MessageItem(
                        role=m.get("role", ""),
                        content=m.get("content", ""),
                        metadata=m.get("metadata"),
                        token_count=self._estimate_tokens(m.get("content", "")),
                    ))
                generator = SummaryGenerator()
                return generator.generate_summary(items, llm_callback)
            except Exception:
                pass
        key_points: List[str] = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if not content:
                continue
            if role == "tool":
                key_points.append(f"[Tool result] {content[:200]}")
            elif any(kw in content for kw in ["决定", "确认", "修复", "创建", "删除", "decided", "confirmed", "fixed", "created"]):
                key_points.append(f"[{role}] {content[:300]}")
        if key_points:
            return "压缩摘要:\n" + "\n".join(key_points[:20])
        all_text = " ".join(m.get("content", "") for m in messages if m.get("content"))
        return all_text[:2000] if len(all_text) > 2000 else all_text

    def _truncate_tool_result(self, content: str, role: str) -> str:
        if role != "tool":
            return content
        estimated = self._estimate_tokens(content)
        if estimated <= self._tool_result_max_tokens:
            return content
        max_chars = self._tool_result_max_tokens * 4
        truncated = content[:max_chars]
        path = self._extract_file_path(content)
        if path:
            preview = content[:200].strip()
            return _SUMMARY_TEMPLATE.format(path=path, length=len(content), preview=preview)
        return truncated + "\n...[已截断，原始内容过长]"

    def _auto_compress_tool_results(self, session_id: str) -> None:
        messages = self._contexts.get(session_id, [])
        if not messages:
            return
        usage = self.get_token_usage(session_id)
        if not usage["needs_compression"]:
            return
        tokens_before = usage["total_tokens"]
        compressed_count = 0
        new_msgs: List[Dict[str, str]] = []
        for m in messages:
            if m.get("role") == "tool" and not m.get("metadata", {}).get("compressed"):
                content = m.get("content", "")
                if len(content) > 500:
                    path = self._extract_file_path(content)
                    if path:
                        summary = _SUMMARY_TEMPLATE.format(
                            path=path, length=len(content), preview=content[:200],
                        )
                    else:
                        summary = content[:300] + "...[已压缩]"
                    new_msgs.append({
                        "role": "tool",
                        "content": summary,
                        "metadata": {"compressed": True, "original_length": len(content)},
                    })
                    compressed_count += 1
                else:
                    new_msgs.append(m)
            else:
                new_msgs.append(m)
        if compressed_count > 0:
            self._contexts[session_id] = new_msgs
            with self._lock:
                self._compression_log.append(CompressionLogEntry(
                    timestamp=time.time(),
                    session_id=session_id,
                    messages_compressed=compressed_count,
                    tokens_before=tokens_before,
                    tokens_after=self._estimate_total_tokens(new_msgs),
                    reason="auto_compress_tool_results",
                ))

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return _DEFAULT_ESTIMATOR.estimate(text)

    @staticmethod
    def _estimate_total_tokens(messages: List[Dict[str, str]]) -> int:
        return _DEFAULT_ESTIMATOR.estimate_messages(messages)

    @staticmethod
    def _extract_file_path(content: str) -> str:
        patterns = [
            r'(?:文件|File|path|路径)[:\s]+[`"]?([A-Za-z]:[\\/][^\s`"\'，,]+)',
            r'([A-Za-z]:[\\/][^\s`"\'，,]+\.(?:ets|ts|py|json|json5|js|md))',
        ]
        for p in patterns:
            match = re.search(p, content)
            if match:
                return match.group(1)
        return ""
