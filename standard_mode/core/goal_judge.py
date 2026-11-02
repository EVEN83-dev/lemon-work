# -*- coding: utf-8 -*-
"""
Goal Judge — 目标达成判断器
===========================
在 agent_chat 循环结束后，用轻量级 chat 调用判断：
1. 用户原始目标是否已达成
2. 是否需要继续追问/补充执行

避免 Agent 在目标已达成时浪费 token 继续循环。
"""

import json
import logging
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """你是一个目标判断助手。根据用户的原始目标和 Agent 的执行结果，判断目标是否已达成。

回复格式（严格 JSON）：
{"achieved": true/false, "reason": "简短说明", "suggestion": "如果未达成，建议下一步操作"}

判断标准：
- achieved=true: Agent 输出直接回答了用户问题，或已成功执行了用户要求的操作
- achieved=false: Agent 输出明显偏离目标，或执行失败，或用户问题未被回答

只输出 JSON，不要有任何其他文字。"""


class GoalJudge:
    """轻量级目标判断器"""

    def __init__(self, engine_manager=None):
        self._engine_manager = engine_manager

    def _get_engine_manager(self):
        if self._engine_manager is not None:
            return self._engine_manager
        from shared.engine_manager import get_engine_manager
        self._engine_manager = get_engine_manager()
        return self._engine_manager

    def judge(self, original_goal: str, agent_output: str,
              tool_calls_made: Optional[List[Dict]] = None) -> Dict:
        """判断目标是否达成

        Returns:
            {"achieved": bool, "reason": str, "suggestion": str}
        """
        if not original_goal or not agent_output:
            return {"achieved": False, "reason": "空输入", "suggestion": "重新提问"}

        try:
            engine_mgr = self._get_engine_manager()
            if not engine_mgr._engines:
                engine_mgr.initialize()

            engine_name = "ollama"
            engine = engine_mgr._engines.get(engine_name)
            if not engine:
                for name in engine_mgr._engines:
                    engine = engine_mgr._engines[name]
                    engine_name = name
                    break

            if not engine:
                return self._heuristic_judge(original_goal, agent_output, tool_calls_made)

            tool_summary = ""
            if tool_calls_made:
                names = [tc.get("name", "?") for tc in tool_calls_made[:10]]
                tool_summary = f"已执行工具: {', '.join(names)}"

            user_msg = (
                f"用户目标: {original_goal[:500]}\n\n"
                f"Agent 输出:\n{agent_output[:2000]}\n\n"
                f"{tool_summary}"
            )

            messages = [
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]

            try:
                response = engine.chat(messages)
            except Exception:
                return self._heuristic_judge(original_goal, agent_output, tool_calls_made)

            return self._parse_judge_response(response)

        except Exception as e:
            logger.warning(f"[GoalJudge] 判断异常: {e}")
            return self._heuristic_judge(original_goal, agent_output, tool_calls_made)

    def _parse_judge_response(self, response: str) -> Dict:
        try:
            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])
            result = json.loads(text)
            if "achieved" in result:
                return {
                    "achieved": bool(result["achieved"]),
                    "reason": result.get("reason", ""),
                    "suggestion": result.get("suggestion", ""),
                }
        except (json.JSONDecodeError, ValueError):
            pass

        lower = response.lower()
        if any(w in lower for w in ["true", "达成", "已完成", "成功"]):
            return {"achieved": True, "reason": "LLM判断达成", "suggestion": ""}
        return {"achieved": False, "reason": "解析失败", "suggestion": response[:200]}

    @staticmethod
    def _heuristic_judge(goal: str, output: str, tool_calls: Optional[List[Dict]] = None) -> Dict:
        """无 LLM 时的启发式判断"""
        if not output or len(output.strip()) < 10:
            return {"achieved": False, "reason": "输出过短", "suggestion": "重新执行"}

        error_keywords = ["error", "失败", "异常", "无法", "未找到", "traceback"]
        lower_out = output.lower()
        error_count = sum(1 for kw in error_keywords if kw in lower_out)

        if error_count >= 2 and tool_calls and len(tool_calls) == 0:
            return {"achieved": False, "reason": "多次错误且无工具调用", "suggestion": "更换策略"}

        if tool_calls and len(tool_calls) > 0 and "成功" in output:
            return {"achieved": True, "reason": "工具调用成功+输出包含成功", "suggestion": ""}

        if len(output) > 200 and error_count == 0:
            return {"achieved": True, "reason": "输出充实且无错误", "suggestion": ""}

        return {"achieved": False, "reason": "启发式无法判定", "suggestion": "继续执行或更换策略"}
