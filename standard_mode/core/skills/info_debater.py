# -*- coding: utf-8 -*-
"""
Skill: info_debater — 多源信息辩驳与验证
==========================================
对比多源信息、检测矛盾、验证声明、达成共识。
"""

import json
import re
import traceback
from typing import Dict, Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "info_debater",
    "description": "多源信息辩驳与验证：对比多源信息、检测矛盾、验证声明、达成共识。Lemon Code 创新功能。",
    "category": "debate",
    "version": "1.0.0",
}


def execute(
    sources: str = "",
    claim: str = "",
    mode: str = "compare",
) -> SkillResult:
    """多源信息辩驳与验证

    Args:
        sources: JSON 字符串，格式: [{"source": "名称", "content": "内容"}, ...]
        claim: 待验证的声明（可选）
        mode: compare/verify/contradict/consensus
    """
    if not sources:
        return SkillResult(success=False, error="sources 参数为空")

    try:
        sources_list = json.loads(sources) if isinstance(sources, str) else sources
    except json.JSONDecodeError as e:
        return SkillResult(success=False, error=f"sources JSON 解析失败: {e}")

    if not isinstance(sources_list, list) or len(sources_list) < 2:
        return SkillResult(success=False, error="至少需要 2 个信息源")

    try:
        import difflib as _difflib

        contents = [s.get('content', '') for s in sources_list]
        source_names = [s.get('source', f'src_{i}') for i, s in enumerate(sources_list)]

        # 差异检测
        diffs = []
        for i in range(len(contents)):
            for j in range(i + 1, len(contents)):
                diff = _difflib.SequenceMatcher(None, contents[i], contents[j])
                ratio = diff.ratio()
                diffs.append({
                    'source_a': source_names[i],
                    'source_b': source_names[j],
                    'similarity': round(ratio, 3),
                    'difference': round(1 - ratio, 3),
                })

        # 关键词提取
        all_text = ' '.join(contents)
        stop_words = {'的', '是', '了', '在', '和', '与', '或', '也', '都', '但', '而',
                      'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'to', 'of', 'in', 'on', 'at', 'for', 'with'}
        words = re.findall(r'[\u4e00-\u9fa5]{2,4}|[a-zA-Z]+', all_text)
        word_freq = {}
        for w in words:
            if w.lower() not in stop_words and len(w) >= 2:
                word_freq[w] = word_freq.get(w, 0) + 1
        top_keywords = sorted(word_freq.items(), key=lambda x: -x[1])[:10]

        if mode == 'compare':
            common_keywords = [w for w, _ in top_keywords[:5]]
            output = (
                f"=== 多源信息对比报告 ===\n"
                f"源数量: {len(sources_list)}\n"
                f"相似度矩阵:\n" +
                "\n".join([f"  {d['source_a']} ↔ {d['source_b']}: 相似度 {d['similarity']:.1%}, 差异 {d['difference']:.1%}"
                           for d in diffs]) +
                f"\n\n共同关键词 (Top 5): {', '.join(common_keywords)}\n"
            )

        elif mode == 'verify' and claim:
            claim_words = re.findall(r'[\u4e00-\u9fa5]{2,4}|[a-zA-Z]+', claim)
            supports = []
            for i, content in enumerate(contents):
                hit_count = sum(1 for w in claim_words if w in content)
                support_rate = hit_count / max(1, len(claim_words))
                supports.append({'source': source_names[i], 'support_rate': round(support_rate, 3)})
            avg_support = sum(s['support_rate'] for s in supports) / len(supports)
            output = f"声明验证: '{claim[:50]}'\n平均支持率: {avg_support:.1%}\n" + "\n".join(
                [f"  {s['source']}: 支持率 {s['support_rate']:.1%}" for s in supports])

        elif mode == 'contradict':
            contradictions = [d for d in diffs if d['similarity'] < 0.5]
            output = f"矛盾检测: {len(contradictions)} 对源存在显著差异\n"
            for c in contradictions:
                output += f"  {c['source_a']} ↔ {c['source_b']}: 相似度仅 {c['similarity']:.1%}\n"

        elif mode == 'consensus':
            high_sim = [d for d in diffs if d['similarity'] > 0.7]
            common_kw = [w for w, _ in top_keywords[:8]]
            output = f"共识分析: {len(high_sim)}/{len(diffs)} 对源高度一致\n共识关键词: {', '.join(common_kw)}\n"

        else:
            output = f"已完成 {mode} 分析（源数量: {len(sources_list)}）"

        return SkillResult(success=True, output=output, data={'diffs': diffs, 'keywords': top_keywords})

    except Exception as e:
        return SkillResult(success=False, error=f"信息辩驳失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="info_debater",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "sources": {"type": "string", "description": "JSON 数组: [{\"source\":\"名称\",\"content\":\"内容\"},...]"},
                "claim": {"type": "string", "description": "待验证的声明（可选）"},
                "mode": {
                    "type": "string",
                    "enum": ["compare", "verify", "contradict", "consensus"],
                    "description": "分析模式",
                },
            },
            "required": ["sources"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
