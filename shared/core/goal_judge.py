# -*- coding: utf-8 -*-
"""目标达成判定（v5.5 补全）。

决定 Agent 何时应该停止（避免无意义的工具循环）。
调用点：engine_manager.py L3954 => GoalJudge(self).judge(prompt, content, tool_calls_made)
返回：dict{"achieved": bool, "reason": str}
"""
import logging

logger = logging.getLogger(__name__)


class GoalJudge:
    def __init__(self, engine_manager=None):
        self._em = engine_manager

    def judge(self, prompt: str, content: str, tool_calls_made: list) -> dict:
        """基于规则轻量判定目标是否达成。

        规则：
          - content 为空 => 未达成（仍需继续/总结）
          - prompt 是问句且 content 给出了实质性回答（>80 字）=> 达成
          - 工具调用产生了结果但 content 仍过短 => 未完全达成
        """
        if not content or not content.strip():
            return {"achieved": False, "reason": "最终输出为空，目标未达成"}
        text = content.strip()
        # 问句类：用户问"什么/如何/为什么/对比/有哪些"等
        is_question = any(k in prompt for k in [
            "?", "？", "什么", "如何", "怎么", "为什么", "哪些", "区别", "对比",
            "有哪些", "干什么", "亮点", "定位",
        ])
        if is_question:
            if len(text) >= 50:
                return {"achieved": True, "reason": "已对问题给出实质性回答"}
            return {"achieved": False, "reason": "问题类任务但回答过短"}
        # 动作类：有工具产出且 content 非空即可视为达成
        if len(text) >= 30:
            return {"achieved": True, "reason": "已输出执行结果"}
        return {"achieved": False, "reason": "输出过短，目标可能未达成"}
