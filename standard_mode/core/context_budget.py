# -*- coding: utf-8 -*-
"""364章 T1.4: 上下文预算管理器 — 五段 token 预算分配+截断"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class BudgetConfig:
    system_prompt: float = 0.10
    history: float = 0.40
    retrieval: float = 0.10
    file_content: float = 0.25
    tool_result: float = 0.15


@dataclass
class ContextBudget:
    max_tokens: int = 32768
    config: BudgetConfig = field(default_factory=BudgetConfig)

    def allocate(self) -> Dict[str, int]:
        c = self.config
        total = 1.0
        return {
            "system_prompt": int(self.max_tokens * c.system_prompt / total),
            "history": int(self.max_tokens * c.history / total),
            "retrieval": int(self.max_tokens * c.retrieval / total),
            "file_content": int(self.max_tokens * c.file_content / total),
            "tool_result": int(self.max_tokens * c.tool_result / total),
        }

    def _est_tokens(self, msg: Dict) -> int:
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        return len(content) // 4 + 50

    def truncate_messages(self, messages: List[Dict], budget: int) -> List[Dict]:
        """反向保留裁剪（保尾部丢头部）。

        ★ 396A-1② 修复：system 角色消息永驻 —— 超预算时只压缩其余消息，
        system（含工具菜单/人设/防注入规则）永不丢；system 自身超预算时
        保留全部 system（宁可整体超也不丢防线）。
        """
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]
        total = sum(self._est_tokens(m) for m in system_msgs)
        result: List[Dict] = [dict(m) for m in system_msgs]
        n_sys = len(result)
        for msg in reversed(other_msgs):
            estimated = self._est_tokens(msg)
            if total + estimated > budget:
                remaining = budget - total
                if remaining > 100:
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                    truncated_msg = dict(msg)
                    truncated_msg["content"] = content[:remaining * 4] + "\n[...截断...]"
                    result.insert(n_sys, truncated_msg)
                break
            result.insert(n_sys, msg)
            total += estimated
        return result

    def truncate_tool_results(self, results: List[Dict], budget: int) -> List[Dict]:
        total = 0
        out = []
        for r in results:
            text = str(r.get("result", ""))
            estimated = len(text) // 4 + 20
            if total + estimated > budget:
                remaining = budget - total
                if remaining > 50:
                    truncated = text[:remaining * 4]
                    r = dict(r)
                    r["result"] = truncated + "\n[...截断...]"
                    out.append(r)
                break
            out.append(r)
            total += estimated
        return out

    def plan(self, messages: List[Dict], tool_results: List[Dict]) -> Dict:
        budgets = self.allocate()
        truncated_msgs = self.truncate_messages(messages, budgets["history"])
        truncated_tools = self.truncate_tool_results(tool_results, budgets["tool_result"])
        return {
            "budgets": budgets,
            "messages": truncated_msgs,
            "tool_results": truncated_tools,
            "total_messages": len(messages),
            "kept_messages": len(truncated_msgs),
            "total_tools": len(tool_results),
            "kept_tools": len(truncated_tools),
        }
