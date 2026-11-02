"""
每日一句格言 Skill（骨架）

功能：按日期返回一句格言/名言，支持按分类筛选与随机抽取。
骨架说明：本文件为可运行的最小实现，内置少量示例格言；
        后续可扩展为从本地 JSON / 远程 API 拉取真实格言库。
"""
from __future__ import annotations

import random
import time
from typing import Any, Dict, List, Optional

from .models import SkillDef, SkillResult

# 内置示例格言库（骨架阶段占位，可按需扩充或替换为外部数据源）
_QUOTES: List[Dict[str, str]] = [
    {"text": "千里之行，始于足下。", "author": "老子", "category": "励志"},
    {"text": "学而不思则罔，思而不学则殆。", "author": "孔子", "category": "学习"},
    {"text": "天行健，君子以自强不息。", "author": "《周易》", "category": "励志"},
    {"text": "不积跬步，无以至千里。", "author": "荀子", "category": "励志"},
    {"text": "知之者不如好之者，好之者不如乐之者。", "author": "孔子", "category": "学习"},
    {"text": "路漫漫其修远兮，吾将上下而求索。", "author": "屈原", "category": "励志"},
    {"text": "纸上得来终觉浅，绝知此事要躬行。", "author": "陆游", "category": "实践"},
    {"text": "博观而约取，厚积而薄发。", "author": "苏轼", "category": "学习"},
]


class DailyQuoteSkill:
    """每日一句格言技能：按日期确定性选取，或随机抽取。"""

    name = "daily_quote_skill"
    description = "每日一句格言：按日期返回一句格言，支持分类筛选与随机抽取"

    def __init__(self) -> None:
        self._quotes: List[Dict[str, str]] = list(_QUOTES)

    # ---- 对外接口 ----

    def get_daily(self, category: str = "") -> Dict[str, Any]:
        """按当天日期确定性返回一句格言（同一天结果稳定）。"""
        pool = self._filter_by_category(category)
        if not pool:
            return {"error": f"分类 '{category}' 下暂无格言"}
        # 以日期为随机种子，保证同一天返回同一句
        day_seed = int(time.strftime("%Y%m%d"))
        rng = random.Random(day_seed)
        quote = rng.choice(pool)
        return self._format(quote, mode="daily")

    def get_random(self, category: str = "") -> Dict[str, Any]:
        """随机返回一句格言。"""
        pool = self._filter_by_category(category)
        if not pool:
            return {"error": f"分类 '{category}' 下暂无格言"}
        quote = random.choice(pool)
        return self._format(quote, mode="random")

    def list_categories(self) -> Dict[str, Any]:
        """列出当前格言库中所有可用分类。"""
        cats = sorted({q.get("category", "") for q in self._quotes if q.get("category")})
        return {"categories": cats, "total": len(self._quotes)}

    # ---- 内部辅助 ----

    def _filter_by_category(self, category: str) -> List[Dict[str, str]]:
        if not category:
            return self._quotes
        return [q for q in self._quotes if q.get("category") == category]

    def _format(self, quote: Dict[str, str], mode: str) -> Dict[str, Any]:
        return {
            "mode": mode,
            "date": time.strftime("%Y-%m-%d"),
            "text": quote.get("text", ""),
            "author": quote.get("author", ""),
            "category": quote.get("category", ""),
        }


# ---- SkillDef 注册封装（供 registry 自动发现） ----

def build_skill_def() -> SkillDef:
    """构造并返回本技能的 SkillDef 定义。"""
    skill = DailyQuoteSkill()
    return SkillDef(
        name=skill.name,
        description=skill.description,
        category="life",  # 分类可按项目 SkillDef.category 枚举调整
        version="0.1.0",
        handler=skill,  # 若 SkillDef 采用 handler 回调模式，此处替换为对应入口
    )


# 便捷入口：供直接调用测试
if __name__ == "__main__":
    s = DailyQuoteSkill()
    print("每日一句:", s.get_daily())
    print("随机一句:", s.get_random())
    print("可用分类:", s.list_categories())
