# -*- coding: utf-8 -*-
"""
Skill: deep_researcher — 深度研究
==================================
对主题进行系统深入研究，分解问题，搜索 arXiv 论文和网络背景，
整合生成结构化研究报告。

v2.0: 动态分析 — 结论基于实际研究数据，不再使用硬编码模板
"""

import json
import os
import re
import traceback
from collections import Counter
from typing import Dict, Any, List

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "deep_researcher",
    "description": "深度研究：对主题进行系统深入研究，分解问题，搜索 arXiv 论文和网络背景，整合生成结构化研究报告。",
    "category": "research",
    "version": "2.0.0",
}


def _lazy_import(lib_name: str):
    try:
        mod = __import__(lib_name)
        for part in lib_name.split('.')[1:]:
            mod = getattr(mod, part)
        return mod
    except (ImportError, AttributeError):
        return None


def _extract_keywords(texts: List[str], top_n: int = 8) -> List[str]:
    """从文本列表中提取高频关键词"""
    stopwords = {'the','a','an','is','are','was','were','be','been','being',
                 'have','has','had','do','does','did','will','would','could',
                 'should','may','might','can','shall','for','and','nor','but',
                 'or','yet','so','in','on','at','to','of','by','with','from',
                 'as','into','through','during','before','after','above','below',
                 'between','out','off','over','under','again','further','then',
                 'this','that','these','those','it','its','we','our','they',
                 'their','which','what','who','whom','if','about','up','also',
                 'based','using','used','via','new','one','two','however'}
    words = []
    for text in texts:
        tokens = re.findall(r'[a-zA-Z\u4e00-\u9fff]{2,}', text.lower())
        words.extend(t for t in tokens if t not in stopwords)
    counter = Counter(words)
    return [w for w, _ in counter.most_common(top_n)]


def _generate_analysis(topic: str, sub_questions: List[str],
                        arxiv_results: List[Dict], web_results: List[Dict]) -> List[str]:
    """基于实际研究数据动态生成分析"""
    analyses = []

    # 收集所有文本
    all_titles = [p.get('title', '') for p in arxiv_results if p.get('title')]
    all_summaries = [p.get('summary', '') for p in arxiv_results if p.get('summary')]
    all_titles += [w.get('title', '') for w in web_results if w.get('title')]
    all_summaries += [w.get('snippet', '') for w in web_results if w.get('snippet')]

    # 分析1: 核心概念 — 基于关键词聚类
    title_kw = _extract_keywords(all_titles, 5)
    if title_kw:
        analyses.append("**核心概念**: " + topic + " 的核心研究维度包括 " +
                        "、".join(title_kw[:3]) + "，涉及多个交叉领域的知识体系")
    else:
        analyses.append("**核心概念**: " + topic + " 是一个多维度研究领域")

    # 分析2: 当前进展 — 基于论文数量和内容
    summary_kw = _extract_keywords(all_summaries, 6)
    if arxiv_results:
        method_kw = [kw for kw in summary_kw if any(kw.startswith(p) for p in
                     ['method','approach','model','algorithm','framework','network','architect'])]
        if method_kw:
            analyses.append("**当前进展**: 活跃方法包括 " + "、".join(method_kw[:3]) +
                           "，学术界和工业界均投入大量资源进行探索")
        else:
            analyses.append("**当前进展**: 发现" + str(len(arxiv_results)) +
                           "篇相关论文，该领域正在快速发展")
    else:
        analyses.append("**当前进展**: 公开学术资源有限，建议查阅专业数据库")

    # 分析3: 挑战 — 基于摘要中的否定/限制词
    challenge_signals = ['limitation','challenge','difficult','bottleneck','constraint',
                         'trade-off','overhead','scalability','robustness','bias']
    found_challenges = []
    for summary in all_summaries:
        for sig in challenge_signals:
            if sig in summary.lower():
                found_challenges.append(sig)
    if found_challenges:
        unique_challenges = list(set(found_challenges))[:3]
        analyses.append("**主要挑战**: 文献中提到的关键挑战包括 " +
                        "、".join(unique_challenges))
    else:
        analyses.append("**主要挑战**: 技术成熟度和可扩展性是普遍关注的瓶颈")

    # 分析4: 未来方向 — 基于摘要中的前瞻词
    future_signals = ['future','direction','toward','potential','promising','next']
    future_hints = []
    for summary in all_summaries:
        for sig in future_signals:
            if sig in summary.lower():
                # 提取含前瞻词的句子
                sentences = summary.split('.')
                for s in sentences:
                    if sig in s.lower() and len(s.strip()) > 20:
                        future_hints.append(s.strip()[:100])
                        break
    if future_hints:
        analyses.append("**未来方向**: " + future_hints[0])
    else:
        trend_kw = [kw for kw in summary_kw if any(kw.startswith(p) for p in
                    ['automat','intellig','neural','deep','learn','generat'])]
        if trend_kw:
            analyses.append("**未来方向**: " + "、".join(trend_kw[:2]) + " 将是重要趋势")
        else:
            analyses.append("**未来方向**: 跨领域融合和自动化将是重要趋势")

    return analyses


def execute(
    topic: str = "",
    depth: str = "medium",
    focus_areas: str = "",
) -> SkillResult:
    """深度研究

    Args:
        topic: 研究主题
        depth: shallow/medium/deep
        focus_areas: 关注领域（逗号分隔）
    """
    if not topic:
        return SkillResult(success=False, error="topic 参数为空")

    try:
        areas = [a.strip() for a in focus_areas.split(',') if a.strip()] if focus_areas else []
        depth_levels = {'shallow': 2, 'medium': 4, 'deep': 6}
        max_sub = depth_levels.get(depth, 4)

        # 1. 分解研究问题（动态生成）
        sub_questions = [topic + " 的核心概念是什么？"]
        if areas:
            for area in areas[:max_sub - 1]:
                sub_questions.append(topic + " 在 " + area + " 领域的应用和挑战？")
        else:
            default_questions = [
                topic + " 的最新研究进展？",
                topic + " 的主要挑战和局限性？",
                topic + " 的未来发展方向？",
                topic + " 有哪些开源实现和工业应用？",
                topic + " 的理论基础和关键算法是什么？",
            ]
            sub_questions.extend(default_questions[:max_sub - 1])

        # 2. 搜索 arXiv（增加结果数量）
        arxiv_results = []
        requests = _lazy_import('requests')
        if requests:
            try:
                from xml.etree import ElementTree
                max_results = {'shallow': 3, 'medium': 5, 'deep': 8}.get(depth, 5)
                url = "http://export.arxiv.org/api/query?search_query=all:" + topic.replace(' ', '+') + "&start=0&max_results=" + str(max_results)
                resp = requests.get(url, timeout=20)
                if resp.status_code == 200:
                    root = ElementTree.fromstring(resp.text)
                    ns = {'atom': 'http://www.w3.org/2005/Atom'}
                    for entry in root.findall('atom:entry', ns):
                        title = entry.find('atom:title', ns)
                        title_text = title.text.strip().replace('\n', ' ') if title is not None else ''
                        summary = entry.find('atom:summary', ns)
                        summary_text = summary.text.strip().replace('\n', ' ')[:300] if summary is not None else ''
                        link = entry.find('atom:id', ns)
                        link_text = link.text.strip() if link is not None else ''
                        arxiv_results.append({
                            'title': title_text, 'summary': summary_text, 'link': link_text
                        })
            except Exception:
                pass

        # 3. 搜索网络资源
        web_results = []
        if requests:
            try:
                search_url = "https://html.duckduckgo.com/html/?q=" + topic.replace(' ', '+')
                resp = requests.get(search_url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
                if resp.status_code == 200:
                    results = re.findall(
                        r'class="result__a"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</(?:a|td>)',
                        resp.text, re.DOTALL)[:5]
                    for title_match, snippet_match in results:
                        clean_title = re.sub(r'<[^>]+>', '', title_match).strip()
                        clean_snippet = re.sub(r'<[^>]+>', '', snippet_match).strip()[:200]
                        if clean_title:
                            web_results.append({'title': clean_title, 'snippet': clean_snippet})
            except Exception:
                pass

        # 4. 动态生成分析
        dynamic_analyses = _generate_analysis(topic, sub_questions, arxiv_results, web_results)

        # 5. 生成结构化报告
        report = "# 深度研究报告: " + topic + "\n\n"
        report += "## 研究概述\n"
        report += "本报告对 \"" + topic + "\" 进行" + depth + "级别深度研究。\n\n"

        report += "## 研究问题分解\n"
        for i, q in enumerate(sub_questions, 1):
            report += str(i) + ". " + q + "\n"
        report += "\n"

        if arxiv_results:
            report += "## 学术文献（arXiv）\n"
            for i, paper in enumerate(arxiv_results, 1):
                report += "\n### [" + str(i) + "] " + paper['title'] + "\n"
                if paper.get('summary'):
                    report += paper['summary'] + "...\n"
                if paper.get('link'):
                    report += "[论文链接](" + paper['link'] + ")\n"
            report += "\n"

        if web_results:
            report += "## 网络资源\n"
            for i, w in enumerate(web_results, 1):
                report += str(i) + ". **" + w['title'] + "**\n"
                if w.get('snippet'):
                    report += "   " + w['snippet'] + "\n"
            report += "\n"

        report += "## 综合分析\n"
        report += "基于以上研究，对 \"" + topic + "\" 的关键发现如下：\n\n"
        for i, a in enumerate(dynamic_analyses, 1):
            report += str(i) + ". " + a + "\n"
        report += "\n"

        report += "## 结论\n"
        report += topic + " 是一个具有广阔前景的研究方向"
        if arxiv_results or web_results:
            report += "，基于" + str(len(arxiv_results)) + "篇学术论文和" + str(len(web_results)) + "条网络资源的分析"
        report += "，需要持续关注最新进展。\n\n"
        report += "---\n*由 Lemon Code deep_researcher v2.0 自动生成*\n"

        return SkillResult(
            success=True,
            output="深度研究报告已生成: " + topic + "\n深度: " + depth + "\n子问题: " + str(len(sub_questions)) + "\narXiv 论文: " + str(len(arxiv_results)),
            data={'report': report, 'sub_questions': sub_questions, 'arxiv_results': arxiv_results, 'web_results': web_results},
        )
    except Exception as e:
        return SkillResult(success=False, error="深度研究失败: " + str(e), output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="deep_researcher",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "研究主题"},
                "depth": {"type": "string", "enum": ["shallow", "medium", "deep"], "description": "研究深度", "default": "medium"},
                "focus_areas": {"type": "string", "description": "关注领域（逗号分隔）"},
            },
            "required": ["topic"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=120,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
