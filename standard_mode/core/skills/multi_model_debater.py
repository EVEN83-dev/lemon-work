# -*- coding: utf-8 -*-
"""
Skill: multi_model_debater — 多模型辩论决策
============================================
模拟多方辩论过程（正方/反方/中立方），基于主题和上下文动态生成论证，
多轮评分投票，综合裁决。

v2.0: 动态论证 — 基于主题关键词和上下文生成论点，不再使用随机模板
"""

import json
import os
import re
import traceback
from typing import Dict, Any, List

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "multi_model_debater",
    "description": "多模型辩论决策：模拟多方辩论过程（正方/反方/中立方），多轮评分投票，综合裁决",
    "category": "debate",
    "version": "2.0.0",
}


def _analyze_topic(topic: str, context: str) -> Dict[str, Any]:
    """分析辩论主题，提取关键维度"""
    dimensions = {
        'feasibility': 0.5,    # 技术可行性
        'market': 0.5,         # 市场前景
        'risk': 0.5,           # 风险程度
        'cost': 0.5,           # 成本投入
        'urgency': 0.5,        # 紧迫性
    }

    all_text = (topic + " " + context).lower()

    # 可行性分析
    feasibility_pos = ['proven','mature','stable','reliable','established','validated','demonstrated']
    feasibility_neg = ['experimental','unproven','novel','early','prototype','immature']
    for kw in feasibility_pos:
        if kw in all_text:
            dimensions['feasibility'] = min(1.0, dimensions['feasibility'] + 0.15)
    for kw in feasibility_neg:
        if kw in all_text:
            dimensions['feasibility'] = max(0.1, dimensions['feasibility'] - 0.12)

    # 市场前景
    market_pos = ['growth','demand','opportunity','scalable','trending','popular']
    market_neg = ['niche','limited','saturated','declining','uncertain']
    for kw in market_pos:
        if kw in all_text:
            dimensions['market'] = min(1.0, dimensions['market'] + 0.15)
    for kw in market_neg:
        if kw in all_text:
            dimensions['market'] = max(0.1, dimensions['market'] - 0.12)

    # 风险程度
    risk_pos = ['risk','danger','threat','vulnerability','unstable','volatile']
    risk_neg = ['safe','secure','stable','tested','proven','mitigated']
    for kw in risk_pos:
        if kw in all_text:
            dimensions['risk'] = min(1.0, dimensions['risk'] + 0.12)
    for kw in risk_neg:
        if kw in all_text:
            dimensions['risk'] = max(0.1, dimensions['risk'] - 0.1)

    return dimensions


def _generate_stance(topic: str, position: str, context: str,
                      dimensions: Dict[str, float], round_num: int) -> Dict:
    """基于主题分析动态生成立场论点"""
    argument_parts = []
    score_base = 0.5

    if position == 'proponent':
        # 正方：强调可行性和市场前景
        if dimensions['feasibility'] > 0.5:
            argument_parts.append("技术可行性已得到验证，方案成熟度高")
            score_base += 0.1
        if dimensions['market'] > 0.5:
            argument_parts.append("市场需求明确，具备规模化推广条件")
            score_base += 0.1
        if dimensions['urgency'] > 0.5:
            argument_parts.append("时机窗口有限，需尽快行动")
            score_base += 0.05
        if dimensions['risk'] < 0.5:
            argument_parts.append("风险可控，已有成熟的风险缓解策略")
            score_base += 0.08
        if not argument_parts:
            argument_parts.append(topic + " 具有推进价值，预期收益大于投入成本")
            score_base += 0.05

        # 随轮次深入
        if round_num > 1:
            argument_parts.append("经多轮论证，正方立场更加坚定")
            score_base += 0.03 * round_num

        score = min(0.95, score_base + (round_num * 0.02))
        return {
            'position': '正方',
            'argument': "支持 \"" + topic + "\": " + "；".join(argument_parts),
            'score': round(score, 2),
        }

    elif position == 'opponent':
        # 反方：强调风险和成本
        if dimensions['risk'] > 0.5:
            argument_parts.append("存在显著风险因素，可能影响项目稳定性")
            score_base += 0.08
        if dimensions['cost'] > 0.5:
            argument_parts.append("投入成本较高，ROI 尚不明确")
            score_base += 0.05
        if dimensions['feasibility'] < 0.5:
            argument_parts.append("技术成熟度不足，落地难度被低估")
            score_base += 0.1
        if dimensions['market'] < 0.5:
            argument_parts.append("市场验证不充分，需求可能被高估")
            score_base += 0.08
        if not argument_parts:
            argument_parts.append(topic + " 需要更多论证，当前决策依据不足")
            score_base += 0.03

        if round_num > 1:
            argument_parts.append("多轮分析表明反方担忧仍然成立")
            score_base += 0.02 * round_num

        score = min(0.85, score_base + (round_num * 0.015))
        return {
            'position': '反方',
            'argument': "反对 \"" + topic + "\": " + "；".join(argument_parts),
            'score': round(score, 2),
        }

    else:  # neutral
        # 中立方：权衡利弊
        if dimensions['feasibility'] > 0.6 and dimensions['risk'] > 0.4:
            argument_parts.append("技术上可行但风险不可忽视，建议分阶段推进")
        elif dimensions['market'] > 0.6 and dimensions['cost'] > 0.5:
            argument_parts.append("市场前景好但成本偏高，建议先 MVP 验证")
        else:
            argument_parts.append("利弊需要结合具体场景评估，不宜一刀切")

        if context:
            argument_parts.append("基于提供的背景信息，建议收集更多数据支撑决策")

        if round_num > 1:
            argument_parts.append("建议在正反方之间寻找折中方案")

        score = 0.45 + round_num * 0.02
        return {
            'position': '中立方',
            'argument': "中立评估 \"" + topic + "\": " + "；".join(argument_parts),
            'score': round(min(0.75, score), 2),
        }


def execute(
    topic: str = "",
    rounds: int = 2,
    participants: str = "proponent,opponent,neutral",
    context: str = "",
) -> SkillResult:
    """多模型辩论决策

    Args:
        topic: 辩论主题
        rounds: 辩论轮数
        participants: 参与方（逗号分隔）: proponent,opponent,neutral
        context: 背景信息
    """
    if not topic:
        return SkillResult(success=False, error="topic 参数为空")

    try:
        roles = [r.strip() for r in participants.split(',') if r.strip()]
        rounds = min(max(1, rounds), 5)

        # 分析主题
        dimensions = _analyze_topic(topic, context)

        debate_log = []
        final_scores = {role: 0.0 for role in roles}

        for round_num in range(1, rounds + 1):
            round_entries = []
            for role in roles:
                stance = _generate_stance(topic, role, context, dimensions, round_num)
                stance['round'] = round_num
                round_entries.append(stance)
                final_scores[role] += stance['score']
            debate_log.append({'round': round_num, 'entries': round_entries})

        # 计算平均分
        avg_scores = {}
        for role in roles:
            avg_scores[role] = round(final_scores[role] / rounds, 3)

        # 综合裁决
        winner = max(avg_scores, key=lambda r: avg_scores[r])
        position_names = {'proponent': '正方', 'opponent': '反方', 'neutral': '中立方'}
        winner_name = position_names.get(winner, winner)
        consensus = avg_scores[winner] > 0.7

        # 生成报告
        report = "# 多模型辩论决策报告\n\n"
        report += "## 辩论主题\n" + topic + "\n\n"
        report += "## 辩论设置\n"
        report += "- 轮数: " + str(rounds) + "\n"
        report += "- 参与方: " + ", ".join([position_names.get(r, r) for r in roles]) + "\n"
        if context:
            report += "- 背景: " + context[:100] + "\n"
        report += "\n## 主题维度分析\n"
        report += "- 可行性: " + str(round(dimensions['feasibility'] * 100)) + "%\n"
        report += "- 市场前景: " + str(round(dimensions['market'] * 100)) + "%\n"
        report += "- 风险程度: " + str(round(dimensions['risk'] * 100)) + "%\n"
        report += "- 成本评估: " + str(round(dimensions['cost'] * 100)) + "%\n\n"

        report += "## 辩论过程\n"
        for round_data in debate_log:
            report += "\n### 第 " + str(round_data['round']) + " 轮\n"
            for entry in round_data['entries']:
                report += "- **" + entry['position'] + "**: " + entry['argument'] + " (评分: " + str(entry['score']) + ")\n"

        report += "\n## 最终评分\n"
        for role, score in avg_scores.items():
            name = position_names.get(role, role)
            bar_full = int(score * 20)
            bar = ''
            for _ in range(bar_full):
                bar += '█'
            for _ in range(20 - bar_full):
                bar += '░'
            pct = round(score * 100, 1)
            report += "- " + name + ": " + str(pct) + "% " + bar + "\n"

        report += "\n## 裁决结果\n"
        winner_pct = round(avg_scores[winner] * 100, 1)
        report += "胜方: **" + winner_name + "** (平均分: " + str(winner_pct) + "%)\n"
        if consensus:
            report += "共识程度: 高（超过70%阈值）\n"
        else:
            report += "共识程度: 中等（需进一步论证）\n"

        report += "\n## 建议\n"
        if consensus:
            report += "辩论结果明确，建议采纳 " + winner_name + " 的立场推进。"
        else:
            report += "辩论结果尚无明确共识，建议增加论据或进行更多轮论证。"

        return SkillResult(
            success=True,
            output="辩论完成: " + topic + "\n胜方: " + winner_name + " (" + str(winner_pct) + "%)",
            data={'report': report, 'winner': winner, 'winner_name': winner_name,
                  'scores': avg_scores, 'consensus': consensus, 'debate_log': debate_log,
                  'dimensions': dimensions},
        )
    except Exception as e:
        return SkillResult(success=False, error="辩论决策失败: " + str(e), output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="multi_model_debater",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "辩论主题"},
                "rounds": {"type": "integer", "description": "辩论轮数(1-5)", "default": 2},
                "participants": {"type": "string", "description": "参与方(逗号分隔)", "default": "proponent,opponent,neutral"},
                "context": {"type": "string", "description": "背景信息"},
            },
            "required": ["topic"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
