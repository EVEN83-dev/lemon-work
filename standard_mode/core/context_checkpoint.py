# -*- coding: utf-8 -*-
"""
Context Checkpoint — 上下文检查点与自动重建
============================================
每 N 轮 Tool Call Loop 自动保存对话快照，
当 token 超限或上下文被截断时自动重建摘要上下文。
"""

import json
import os
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

CHECKPOINT_DIR = os.path.join(os.path.expanduser("~"), ".lemoncode", "checkpoints")
CHECKPOINT_INTERVAL = 5
MAX_CONTEXT_TOKENS = 120000
REBUILD_THRESHOLD = 0.85


@dataclass
class ContextSnapshot:
    round_index: int
    messages: List[Dict]
    tool_calls_made: List[Dict]
    token_estimate: int
    timestamp: float = field(default_factory=time.time)


class ContextCheckpointer:
    """上下文检查点管理器

    - 每 CHECKPOINT_INTERVAL 轮自动保存
    - should_rebuild() 检测 token 逼近上限
    - rebuild_context() 将完整历史压缩为摘要消息
    """

    def __init__(self, session_id: str = "", checkpoint_dir: str = ""):
        self.session_id = session_id or f"sess_{int(time.time())}"
        self._dir = checkpoint_dir or CHECKPOINT_DIR
        self._snapshots: List[ContextSnapshot] = []
        self._lock = threading.Lock()
        self._rebuilt = False

    def should_checkpoint(self, round_index: int) -> bool:
        return round_index > 0 and round_index % CHECKPOINT_INTERVAL == 0

    def save(self, round_index: int, messages: List[Dict],
             tool_calls_made: List[Dict], token_estimate: int = 0) -> str:
        snap = ContextSnapshot(
            round_index=round_index,
            messages=[dict(m) for m in messages],
            tool_calls_made=list(tool_calls_made),
            token_estimate=token_estimate or self._estimate_tokens(messages),
        )
        with self._lock:
            self._snapshots.append(snap)
        self._persist(snap)
        logger.info(f"[Checkpoint] saved round={round_index}, tokens~{snap.token_estimate}")
        return f"cp_{self.session_id}_{round_index}"

    def should_rebuild(self, messages: List[Dict]) -> bool:
        est = self._estimate_tokens(messages)
        if est > MAX_CONTEXT_TOKENS * REBUILD_THRESHOLD:
            logger.info(f"[Checkpoint] should_rebuild: tokens~{est} > {int(MAX_CONTEXT_TOKENS * REBUILD_THRESHOLD)}")
            return True
        return False

    def rebuild_context(self, messages: List[Dict], engine_manager=None) -> List[Dict]:
        """将完整历史压缩为：system + 摘要 + 最近 N 条（★ v5.3: 配对平衡切割，不拆散 tool_call/tool_result）"""
        if not messages:
            return messages

        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        # ★ v5.3: 从末尾往前取最近消息，直到配对平衡（无孤儿 tool 消息）
        #   对齐 dsh tool-pairing / DeepseekNova "配对保留+孤儿清理"
        KEEP_BASE = 4
        keep_start = max(0, len(non_system) - KEEP_BASE)
        # 收集被保留消息中所有 tool 消息的 tool_call_id
        keep_tool_ids = set()
        for m in non_system[keep_start:]:
            if m.get("role") == "tool" and m.get("tool_call_id"):
                keep_tool_ids.add(m.get("tool_call_id"))
        # 往前扩展，直到这些 tool_call_id 对应的 assistant(tool_calls) 消息也被包含
        while keep_start > 0:
            _need_assistant = bool(keep_tool_ids)
            if not _need_assistant:
                break
            # 往前找是否已有能覆盖 keep_tool_ids 的 assistant 消息
            _assistant_covered = set()
            for m in non_system[keep_start:]:
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        _assistant_covered.add(tc.get("id"))
            if keep_tool_ids.issubset(_assistant_covered):
                break
            keep_start -= 1
            # 若前一条是 tool，并入其 tool_call_id
            if keep_start - 1 >= 0 and non_system[keep_start - 1].get("role") == "tool":
                _tm = non_system[keep_start - 1]
                if _tm.get("tool_call_id"):
                    keep_tool_ids.add(_tm.get("tool_call_id"))
            if keep_start <= 0:
                break
        # 边界：若最前面仍是孤儿 tool（其 assistant 在更早被切掉），丢弃该孤儿 tool
        keep_msgs = non_system[keep_start:]
        _known_assistant_ids = set()
        for m in keep_msgs:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    _known_assistant_ids.add(tc.get("id"))
        keep_msgs = [m for m in keep_msgs if not (
            m.get("role") == "tool" and m.get("tool_call_id") and m.get("tool_call_id") not in _known_assistant_ids
        )]

        summary_parts = []
        for m in non_system[:keep_start]:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if content:
                summary_parts.append(f"[{role}] {content[:300]}")

        tool_summary = []
        with self._lock:
            for snap in self._snapshots:
                for tc in snap.tool_calls_made:
                    tool_summary.append(f"{tc.get('name', '?')}({tc.get('status', '?')})")

        summary_text = "【上下文摘要 - 自动重建】\n"
        summary_text += f"原始对话 {len(non_system)} 条，压缩为摘要。\n"
        if summary_parts:
            summary_text += "历史要点:\n" + "\n".join(summary_parts[-10:]) + "\n"
        if tool_summary:
            summary_text += f"已执行工具: {', '.join(tool_summary[-15:])}\n"

        rebuilt = list(system_msgs)
        rebuilt.append({"role": "assistant", "content": summary_text})
        rebuilt.extend(keep_msgs)

        with self._lock:
            self._rebuilt = True
        logger.info(f"[Checkpoint] rebuilt: {len(messages)} → {len(rebuilt)} messages (配对平衡保留{len(keep_msgs)}条)")
        return rebuilt

    def _persist(self, snap: ContextSnapshot):
        try:
            os.makedirs(self._dir, exist_ok=True)
            fname = f"cp_{self.session_id}_{snap.round_index}.json"
            path = os.path.join(self._dir, fname)
            data = {
                "round_index": snap.round_index,
                "messages": snap.messages,
                "tool_calls_made": snap.tool_calls_made,
                "token_estimate": snap.token_estimate,
                "timestamp": snap.timestamp,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[Checkpoint] persist failed: {e}")

    def load_latest(self) -> Optional[ContextSnapshot]:
        try:
            if not os.path.isdir(self._dir):
                return None
            files = [f for f in os.listdir(self._dir) if f.startswith(f"cp_{self.session_id}_")]
            if not files:
                return None
            files.sort(key=lambda f: int(f.split("_")[-1].replace(".json", "")))
            with open(os.path.join(self._dir, files[-1]), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return ContextSnapshot(**data)
        except Exception as e:
            logger.warning(f"[Checkpoint] load failed: {e}")
            return None

    @staticmethod
    def _estimate_tokens(messages: List[Dict]) -> int:
        total = 0
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += len(content) // 3
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        total += len(str(item.get("text", ""))) // 3
        return total
