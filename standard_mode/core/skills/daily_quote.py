# -*- coding: utf-8 -*-
"""
Skill: daily_quote — 每日一句格言
=================================
从内置格言库中随机抽取一句格言，支持按主题分类筛选，
并可搭配作者、出处信息，用于每日激励 / 早安问候 / 文案生成。
"""

import os
import random
import traceback
from typing import Dict, Any, List

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "daily_quote",
    "description": "每日一句格言：从内置格言库随机抽取格言，支持主题筛选与作者信息。",
    "category": "documentation",
    "version": "1.0.0",
}

# 内置格言库（骨架示例，可按需扩充）
QUOTE_LIBRARY: List[Dict[str, str]] = [
    {"text": "千里之行，始于足下。", "author": "老子", "theme": "励志"},
    {"text": "学而不思则罔，思而不学则殆。", "author": "孔子", "theme": "学习"},
    {"text": "天行健，君子以自强不息。", "author": "《周易》", "theme": "励志"},
    {"text": "不积跬步，无以至千里。", "author": "荀子", "theme": "坚持"},
    {"text": "路漫漫其修远兮，吾将上下而求索。", "author": "屈原", "theme": "追求"},
]


def _pick_quote(theme: str = "", seed: int | None = None) -> Dict[str, str]:
    """按主题筛选并随机抽取一句格言。

    Args:
        theme: 主题关键词（空串表示不筛选）
        seed: 随机种子（用于可复现测试，None 表示真随机）

    Returns:
        命中的格言 dict（含 text / author / theme）
    """
    pool = QUOTE_LIBRARY
    if theme:
        pool = [q for q in pool if theme in q.get("theme", "")]
    if not pool:
        raise ValueError(f"格言库中未找到主题为「{theme}」的格言")
    rng = random.Random(seed)
    return rng.choice(pool)


def execute(
    theme: str = "",
    with_author: str = "true",
    seed: str = "",
) -> SkillResult:
    """执行 daily_quote：返回一句格言。

    Args:
        theme: 主题筛选（如 励志 / 学习 / 坚持，空串随机）
        with_author: 是否附带作者信息（"true"/"false"）
        seed: 随机种子（用于可复现，空串真随机）
    """
    try:
        seed_int = int(seed) if seed else None
        quote = _pick_quote(theme=theme, seed=seed_int)

        text = quote["text"]
        if with_author.lower() == "true" and quote.get("author"):
            text = f"{text} —— {quote['author']}"

        return SkillResult(
            success=True,
            output=text,
            data={
                "text": quote["text"],
                "author": quote.get("author", ""),
                "theme": quote.get("theme", ""),
                "full": text,
            },
        )
    except ValueError as e:
        return SkillResult(success=False, error=str(e))
    except Exception as e:
        return SkillResult(success=False, error=f"每日格言执行失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="daily_quote",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "theme": {
                    "type": "string",
                    "description": "主题筛选（如 励志/学习/坚持，空串随机）",
                    "default": "",
                },
                "with_author": {
                    "type": "string",
                    "description": "是否附带作者信息（true/false）",
                    "default": "true",
                },
                "seed": {
                    "type": "string",
                    "description": "随机种子（可复现，空串真随机）",
                    "default": "",
                },
            },
        },
        handler=execute,
        category=METADATA["category"],
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
