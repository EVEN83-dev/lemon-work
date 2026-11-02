# -*- coding: utf-8 -*-
"""
Lemon Code 统一身份模块 (v4.1.10)
============================================
集中定义 Lemon Code 的品牌身份、身份类问题检测与标准身份回答，
供 mimo_panel / main_window / serve_bridge / mimo_page.html 共用，
避免品牌名散落硬编码、避免底层模型自称 Claude Code / MiMo Code 等身份错乱。

背景：
- 截图反馈：Lemon 终端问"你是什么模型"，底层模型回答
  "我是 Claude Code，由 Xiaomi MiMo 团队开发"，型号又答 qwen2.5-coder:3b。
- 根因：MiMo 引擎（mimo.exe / opencode fork）系统提示词内置
  "You are MiMo Code Agent, built by Xiaomi MiMo Team. You are powered by ..."，
  qwen2.5-coder:3b 等 3B 小模型在身份问题上容易产生幻觉；
  Lemon Code 侧此前未统一注入自己的品牌身份，也未做本地拦截。
- 修复：Lemon Code 侧统一注入品牌身份提示词；身份类问题在本地直接生成
  标准回答，不依赖底层模型（100% 可控）。
"""

import re

# ==================== 品牌常量 ====================
LEMON_BRAND_EN = "Lemon Code"
LEMON_BRAND_ZH = "柠檬·Lemon Code"
LEMON_DEV_TEAM = "Lemon 团队"

# ==================== 身份类问题检测 ====================

def detect_identity_question(text: str) -> bool:
    """检测是否为询问 AI 身份的提问（你是谁 / 什么模型 / 模型型号等）。

    只匹配"在问自己身份"的提问，避免误伤"什么模型更好用"等正常问题。
    """
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()

    # 中文直接问身份
    direct_patterns = [
        r"你.{0,6}是谁",
        r"你.{0,6}叫什么",
        r"你.{0,6}名字",
        r"你是.{0,6}(什么|哪|谁|啥)",
        r"你.{0,6}(什么模型|哪个模型|用的什么|用的哪|模型型号|是什么模型)",
        r"^(什么模型|模型型号|型号)(是|啊|呢|呀|吗|是啥|是哪个|是什么)?$",
        r"你是谁.{0,4}(开发|做|创造)",
        r"你.{0,6}什么.{0,4}(ai|AI|智能体|机器人)",
    ]
    for pat in direct_patterns:
        if re.search(pat, low):
            return True

    # 英文问身份
    en_patterns = [
        r"\b(who|what|which)\s+(are\s+you|is\s+your\s+(name|model|ai)|model|ai)\b",
        r"your\s+(name|model)",
        r"what\s+model",
    ]
    for pat in en_patterns:
        if re.search(pat, low):
            return True
    return False


# ==================== 标准身份回答 ====================

def build_identity_answer(engine: str = "", model: str = "") -> str:
    """生成标准身份回答。

    Args:
        engine: 当前引擎标识（mimocode / ollama / deepseek / host / native / auto）
        model:  当前底层模型标识（如 qwen2.5-coder:3b / mimo-auto / deepseek-chat）
    """
    # 引擎显示名
    engine_names = {
        "mimocode": "MiMo Code（夺舍桥）",
        "ollama": "本地 Ollama",
        "deepseek": "DeepSeek API",
        "host": "外部 Agent（夺舍）",
        "native": "Lemon Code 原生",
        "auto": "自动模式",
    }
    eng_display = engine_names.get((engine or "").lower(), engine or "自动模式")

    lines = [
        f"我是 {LEMON_BRAND_ZH} 的 AI 编程助手，由 {LEMON_DEV_TEAM} 开发，"
        f"运行在 {LEMON_BRAND_EN} 编辑器中。",
        "",
        "我不是 Claude Code，也不是 MiMo Code，我只是运行在它们/底层引擎之上的助手外壳。",
        "",
        f"当前引擎：{eng_display}",
        f"底层模型：{model or '由引擎自动选择'}",
    ]
    return "\n".join(lines)


def build_identity_system_prompt(engine: str = "", model: str = "") -> str:
    """构建注入给引擎的品牌身份系统提示词片段（追加到系统提示词末尾）。

    作用：让可注入系统提示词的引擎（ollama / deepseek）在回答身份问题时，
    能按 Lemon Code 品牌如实回答，不再自称 Claude Code / MiMo Code。
    """
    return (
        f"你是 {LEMON_BRAND_ZH} 的 AI 编程助手，由 {LEMON_DEV_TEAM} 开发，"
        f"运行在 {LEMON_BRAND_EN} 编辑器中。\n"
        f"你不是 Claude Code，也不是 MiMo Code，不要自称它们的产品名。\n"
        f"如果用户问你是什么模型/引擎，如实回答：当前引擎 {engine or '自动'}，"
        f"底层模型 {model or '由引擎自动选择'}。"
    )
