# -*- coding: utf-8 -*-
"""LLM 驱动的自主开发生成器（L3-2）。

把 AutoDevLoop 的 generator 从「静态 AST 规则」升级为「真 LLM 理解需求」：
  - 读目标文件内容 + 用户需求 → EngineManager.chat() 生成 JSON 编辑计划
  - 解析为 EditPlan（old/new/reason）列表
  - LLM 不可用 / 输出非法时降级到 _default_generator（静态规则），不抛异常

用法：
  from llm_dev_generator import llm_generator
  loop = AutoDevLoop(generator=llm_generator, ...)

设计原则：
  - 与 EngineManager 解耦：chat 不可用时自动降级静态规则
  - 返回 EditPlan 列表，与 AutoDevLoop._apply_edits 兼容
  - JSON 围栏/裸 JSON 兼容（复用 task_decomposer 的解析思路）
"""
import json
import logging
import os
import re
from typing import Dict, List, Optional

log = logging.getLogger("llm.dev.generator")

# 让本文件既能以包内模块导入，也能被测试脚本直接导入
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_dev_loop import EditPlan, _default_generator  # noqa: E402

SYSTEM_PROMPT = (
    "你是代码编辑工具，不是一个聊天助手。你的唯一职责是根据用户提供的"
    "文件内容和修改需求，输出 JSON 编辑计划数组。\n"
    "输出格式（严格遵守）：\n"
    '[{"old":"文件中逐字存在的原文片段（含缩进）","new":"替换后的内容","reason":"修改原因"}]\n'
    "铁律：\n"
    "1. 只输出这个 JSON 数组本身，禁止任何其他文字、解释、问候语、Markdown 围栏\n"
    "2. 禁止闲聊（如「你好」「我是」「我能帮助你」这类回复）\n"
    "3. old 必须是文件中存在的原文；无法精确匹配时输出 []\n"
)


def _call_llm(prompt: str) -> Optional[str]:
    """调 EngineManager.chat() 返回文本；不可用/输出非 JSON 返回 None。"""
    try:
        from shared.engine_manager import get_engine_manager
        mgr = get_engine_manager()
        resp = mgr.chat(prompt, system_prompt=SYSTEM_PROMPT,
                        role="coder", use_cache=False)
        if resp is None:
            return None
        text = resp.content if hasattr(resp, "content") else str(resp)
        # 关键：若输出不像 JSON（无 [ 或无 { ），视为闲聊/失败 → 返回 None 走降级
        if not text or ("[" not in text and "{" not in text):
            log.info("LLM 输出非 JSON（%.40s…），降级静态规则", text[:40].replace("\n", " "))
            return None
        return text
    except Exception as e:  # noqa: BLE001
        log.warning("LLM 调用失败，降级静态规则: %s", e)
        return None


def _parse_edits(text: str) -> List[dict]:
    """从 LLM 输出解析编辑计划列表（兼容围栏/裸 JSON）。"""
    if not text:
        return []
    # 去围栏
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    # 找 JSON 数组
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception as e:  # noqa: BLE001
        log.warning("LLM 输出 JSON 解析失败: %s", e)
        return []
    if not isinstance(data, list):
        return []
    edits = []
    for d in data:
        if not isinstance(d, dict):
            continue
        old = d.get("old")
        new = d.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            continue
        edits.append({"old": old, "new": new,
                      "reason": d.get("reason", "LLM 自主编辑")})
    return edits


def llm_generator(user_request: str, ctx: Dict) -> List[EditPlan]:
    """LLM 驱动生成器：读文件 → LLM 生成编辑 → 校验后返回 EditPlan。

    校验规则（防止 LLM 幻觉破坏文件）：
      - old 必须在文件中存在
      - new 非空
      - 任一 old 不存在则丢弃该编辑（宁缺毋滥）
    """
    files = ctx.get("files", [])
    if not files:
        return _default_generator(user_request, ctx)

    plans: List[EditPlan] = []
    for fp in files:
        if not os.path.isfile(fp):
            continue
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()

        # 构造 LLM 提示：需求 + 文件内容
        prompt = (
            "用户需求：%s\n\n"
            "目标文件：%s\n\n"
            "文件内容：\n```\n%s\n```\n"
            "请输出编辑计划 JSON 数组。" % (user_request, fp, content[:4000])
        )
        llm_text = _call_llm(prompt)
        edits = _parse_edits(llm_text) if llm_text else []

        if not edits:
            # LLM 未产出有效编辑 → 降级静态规则
            log.info("LLM 未产出有效编辑，降级静态规则: %s", fp)
            plans.extend(_default_generator(user_request, {"files": [fp]}))
            continue

        for e in edits:
            if e["old"] not in content:
                log.info("LLM 编辑 old 未命中，丢弃: %.40s…", e["old"])
                continue
            if not e["new"]:
                continue
            plans.append(EditPlan(
                file_path=fp,
                old=e["old"],
                new=e["new"],
                reason=e.get("reason", "LLM 自主编辑"),
            ))
    return plans
