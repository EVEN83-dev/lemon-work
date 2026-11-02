# -*- coding: utf-8 -*-
"""长对话上下文检查点（v5.5 补全）。

用于在 token 接近上限时 save/rebuild 压缩历史，避免长对话崩溃。
调用点：engine_manager.py L3324 => ContextCheckpointer()
当前提供最小可用实现（接口占位 + 基础摘要压缩），后续可接 LLM 摘要。
"""
import logging

logger = logging.getLogger(__name__)

_CTX_LIMIT_SOFT = 8000  # 软上限（token 估算；中文长对话约 1.2 万字即触发）


class ContextCheckpointer:
    def __init__(self):
        self._checkpoints = []

    def estimate_tokens(self, messages: list) -> int:
        """粗略估算 messages 的 token 数（中文约 1.5 字/token，英文约 4 字符/token）。"""
        total_chars = 0
        for m in messages:
            c = m.get("content", "")
            if isinstance(c, str):
                total_chars += len(c)
        # 中文为主：按 1.5 字/token 估算（比英文 4 字符/token 更占额度）
        return int(total_chars / 1.5) + len(messages) * 4

    def should_compact(self, messages: list) -> bool:
        return self.estimate_tokens(messages) > _CTX_LIMIT_SOFT

    # —— 对齐 engine_manager 调用点（v3.81）——
    def should_checkpoint(self, iteration: int) -> bool:
        """每隔若干轮保存一次检查点。"""
        return iteration > 0 and iteration % 3 == 0

    def save(self, iteration: int, messages: list, tool_calls_made: list = None):
        """保存一个检查点（记录轮次 + 消息规模）。"""
        self._checkpoints.append({
            "iteration": iteration,
            "n_messages": len(messages),
            "est_tokens": self.estimate_tokens(messages),
        })
        logger.info(f"[ContextCheckpoint] save iter={iteration} n={len(messages)}")
        return len(self._checkpoints) - 1

    def should_rebuild(self, messages: list) -> bool:
        return self.should_compact(messages)

    def rebuild_context(self, messages: list, engine_mgr=None) -> list:
        """★ v5.5 修复：压缩时严格保持 tool/assistant 配对（避免 400 invalid_request_error）。

        关键约束（OpenAI/DeepSeek function calling 协议）：
          - role='tool' 消息必须紧跟 role='assistant' 含 tool_calls 的消息
          - role='assistant' 含 tool_calls 必须有对应 role='tool' 消息跟随
        策略：整组丢弃 "assistant(tool_calls) + 后续 tool 消息" 序列，只保留纯文本对话

        ★ v5.7 修复（tests/test_context_checkpoint.py 实锤）：孤儿 tool 消息
          当 tool 消息未能紧跟其宿主 assistant(tool_calls) 时（工具结果乱序/丢失/
          中断续接等脏数据场景），旧的 skip 计数会失效，导致该 tool 消息被当作
          普通消息保留下来。压缩结果里出现「前面没有 assistant(tool_calls) 的 tool
          消息」会直接触发 DeepSeek/OpenAI 的 400 invalid_request_error。
          由于本策略本就丢弃全部工具序列，故 tool 消息一律不保留。
        """
        if not self.should_compact(messages):
            return messages
        if len(messages) <= 8:
            return messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        # ★ 成对丢弃：assistant(tool_calls) 及其后所有 tool 消息一起丢弃
        kept = []
        skip_next_tool = 0
        for m in messages:
            if m.get("role") == "system":
                continue  # system 单独处理
            if skip_next_tool > 0:
                # 之前是含 tool_calls 的 assistant，要跳过 N 个 tool
                if m.get("role") == "tool":
                    skip_next_tool -= 1
                else:
                    # 不应出现但兜底：清零避免无限跳
                    skip_next_tool = 0
                    kept.append(m)
                continue
            if m.get("role") == "assistant" and m.get("tool_calls"):
                # 整组丢弃（标记跳过后续 N 个 tool 消息）
                tcs = m.get("tool_calls", [])
                if isinstance(tcs, list):
                    skip_next_tool = len(tcs)
                continue
            if m.get("role") == "tool":
                # ★ v5.7: 孤儿 tool 消息（宿主 assistant 已丢弃 / 跳过计数未覆盖）
                #   保留会导致协议违规 → 400，故一律丢弃
                continue
            kept.append(m)
        # 取最近 6 条保留消息
        recent = kept[-6:]
        compacted = system_msgs + [{
            "role": "system",
            "content": (
                f"[历史对话已压缩，丢弃 {len(messages) - len(kept) - len(system_msgs)} 条 tool 序列；"
                f"保留最近 {len(recent)} 条纯文本对话；原共 {len(messages)} 条]"
            ),
        }] + recent
        logger.info(f"[ContextCheckpoint] rebuild: {len(messages)} -> {len(compacted)} (dropped {len(messages)-len(compacted)} msgs)")
        return compacted
