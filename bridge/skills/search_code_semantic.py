# -*- coding: utf-8 -*-
"""
search_code_semantic — 语义代码搜索 Skill
==========================================
基于 SmartFileReader 的文件优先级评分 + 正则/关键词匹配，
提供轻量级语义代码搜索能力。无需向量数据库，零依赖。

工具名: search_code_semantic
参数: query (string), top_k (int, 默认5)
返回: 相关代码片段列表（文件路径 + 相似度分数 + 上下文）
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional

from bridge.skills.models import SkillDef, SkillResult, SkillCategory, SkillRiskLevel
from bridge.core.smart_file_reader import SmartFileReader


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "because", "but", "and", "or", "if", "while", "about", "up", "it",
    "its", "this", "that", "these", "those", "what", "which", "who",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
    "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会",
    "着", "没有", "看", "好", "自己", "这",
})


def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r'[a-zA-Z_]\w*|[\u4e00-\u9fff]+', text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def _compute_relevance(query_tokens: List[str], content: str,
                       file_path: str, priority_score: int) -> float:
    score = 0.0
    content_lower = content.lower()
    path_lower = file_path.lower()
    for token in query_tokens:
        count = content_lower.count(token)
        if count > 0:
            score += min(count, 10) * 10.0
        if token in path_lower:
            score += 30.0
    camel_parts = re.findall(r'[A-Z][a-z]+', content[:500])
    for part in camel_parts:
        if part.lower() in [t.lower() for t in query_tokens]:
            score += 5.0
    score += priority_score * 0.5
    return score


def search_code_semantic(query: str, top_k: int = 5,
                         project_root: str = "") -> SkillResult:
    start = time.time()
    root = project_root or _PROJECT_ROOT
    if not os.path.isdir(root):
        return SkillResult.fail(f"项目目录不存在: {root}")
    reader = SmartFileReader()
    priorities = reader.prescan_directory(root)
    query_tokens = _tokenize(query)
    if not query_tokens:
        return SkillResult.fail("搜索词为空或全部为停用词")
    candidates: List[Dict[str, Any]] = []
    max_scan = min(len(priorities), top_k * 10)
    for fp in priorities[:max_scan]:
        file_path = fp.path
        if not os.path.isfile(file_path):
            continue
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(50000)
        except Exception:
            continue
        relevance = _compute_relevance(query_tokens, content, file_path, fp.priority)
        if relevance <= 0:
            continue
        best_line = ""
        best_line_score = 0
        for i, line in enumerate(content.split("\n")[:500]):
            line_score = sum(line.lower().count(t) for t in query_tokens)
            if line_score > best_line_score:
                best_line_score = line_score
                best_line = line.strip()[:120]
        candidates.append({
            "path": os.path.relpath(file_path, root),
            "relevance": round(relevance, 1),
            "priority": fp.priority,
            "best_line": best_line,
            "category": fp.category,
        })
    candidates.sort(key=lambda x: x["relevance"], reverse=True)
    results = candidates[:top_k]
    elapsed = (time.time() - start) * 1000
    if not results:
        return SkillResult.ok(
            output=f"未找到与 '{query}' 相关的代码",
            data={"query": query, "results": [], "elapsed_ms": elapsed},
            duration_ms=elapsed,
        )
    output_lines = [f"语义搜索 '{query}' — 找到 {len(results)} 个相关文件:\n"]
    for i, r in enumerate(results):
        output_lines.append(
            f"{i + 1}. [{r['category']}] {r['path']} (相关度: {r['relevance']})\n"
            f"   {r['best_line']}"
        )
    return SkillResult.ok(
        output="\n".join(output_lines),
        data={"query": query, "results": results, "elapsed_ms": elapsed},
        duration_ms=elapsed,
    )


SKILL_DEF = SkillDef(
    name="search_code_semantic",
    description="语义代码搜索：根据自然语言描述查找最相关的代码文件和片段。"
                "当用户询问'在哪里'、'如何实现'时优先使用此工具。",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索查询（自然语言描述或关键词）",
            },
            "top_k": {
                "type": "integer",
                "description": "返回结果数量（默认5）",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    handler=search_code_semantic,
    category=SkillCategory.CODE,
    risk_level=SkillRiskLevel.SAFE,
    requires_confirm=False,
    timeout=15,
    version="1.0.0",
    applicable_scenarios=["code_search", "code_navigation", "code_understanding"],
    fallback_skill="read",
    input_schema={
        "query": {"type": "string", "required": True},
        "top_k": {"type": "integer", "default": 5},
    },
)


def register(registry) -> None:
    registry.register(SKILL_DEF)
