# -*- coding: utf-8 -*-
"""
Skill: fact_checker — 事实核查
================================
对声明进行多源信息验证，检测矛盾，评估可信度。
"""

import json
import os
import re
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "fact_checker",
    "description": "事实核查：对声明进行多源信息验证，检测矛盾，评估可信度。多源对比输出一致性和可信度。",
    "category": "debate",
    "version": "1.0.0",
}


def execute(
    claim: str = "",
    sources: str = "",
    check_mode: str = "full",
) -> SkillResult:
    """事实核查

    Args:
        claim: 待核查的声明
        sources: JSON 信息源 [{"source":"名称","content":"内容"}]
        check_mode: quick/full/detailed
    """
    if not claim:
        return SkillResult(success=False, error="claim 参数为空")

    try:
        sources_list = []
        if sources:
            try:
                sources_list = json.loads(sources) if isinstance(sources, str) else sources
            except json.JSONDecodeError:
                pass

        # 1. 声明分析：提取关键实体
        # 简单提取：中文词组 + 英文单词
        keywords = re.findall(r'[\u4e00-\u9fa5]{2,4}|[A-Z][a-zA-Z]+|\d+(?:\.\d+)?%?', claim)
        stop_words = {'的', '是', '了', '在', '和', '与', '也', '都', '但', '而'}
        keywords = [k for k in keywords if k not in stop_words]

        # 2. 如果有信息源，进行交叉验证
        verification_results = []
        consistency_score = 0.0

        if sources_list and len(sources_list) >= 2:
            import difflib
            contents = [s.get('content', '') for s in sources_list]
            # 计算两两相似度
            similarities = []
            for i in range(len(contents)):
                for j in range(i + 1, len(contents)):
                    ratio = difflib.SequenceMatcher(None, contents[i], contents[j]).ratio()
                    similarities.append(ratio)
            consistency_score = sum(similarities) / len(similarities) if similarities else 0

            # 检查关键词在源中的出现率
            for src in sources_list:
                content = src.get('content', '')
                hit_count = sum(1 for k in keywords if k in content)
                hit_rate = hit_count / max(1, len(keywords))
                verification_results.append({
                    'source': src.get('source', '未知'),
                    'keyword_hit_rate': round(hit_rate, 3),
                    'supports': hit_rate > 0.3,
                })

        # 3. 可信度评估
        if verification_results:
            support_count = sum(1 for v in verification_results if v['supports'])
            avg_hit = sum(v['keyword_hit_rate'] for v in verification_results) / len(verification_results)
            credibility = (consistency_score * 0.4 + avg_hit * 0.3 + (support_count / len(verification_results)) * 0.3)
        else:
            # 无信息源，仅基于声明本身的分析
            credibility = 0.5  # 默认中性
            support_count = 0
            avg_hit = 0

        # 4. 生成报告
        report = f"""# 事实核查报告

## 待核查声明
> {claim}

## 关键词提取
{', '.join(keywords[:10]) if keywords else '（无法提取有效关键词）'}

## 交叉验证
"""
        if verification_results:
            for v in verification_results:
                icon = '✅' if v['supports'] else '❌'
                report += f"- {icon} {v['source']}: 关键词命中率 {v['keyword_hit_rate']:.1%}\n"
            report += f"\n一致性分数: {consistency_score:.1%}\n"
        else:
            report += "（未提供信息源，无法交叉验证）\n"

        # 可信度评级
        if credibility >= 0.7:
            level = '🟢 较高'
        elif credibility >= 0.4:
            level = '🟡 中等'
        else:
            level = '🔴 较低'

        report += f"\n## 可信度评估\n{level} ({credibility:.1%})\n"

        return SkillResult(
            success=True,
            output=f"事实核查完成: {claim[:50]}\n可信度: {level} ({credibility:.1%})",
            data={'report': report, 'credibility': round(credibility, 3), 'consistency': round(consistency_score, 3),
                  'keywords': keywords, 'verifications': verification_results},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"事实核查失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="fact_checker",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "待核查的声明"},
                "sources": {"type": "string", "description": "JSON 信息源"},
                "check_mode": {"type": "string", "enum": ["quick", "full", "detailed"], "description": "核查模式", "default": "full"},
            },
            "required": ["claim"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
