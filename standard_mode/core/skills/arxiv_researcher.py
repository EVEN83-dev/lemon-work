# -*- coding: utf-8 -*-
"""
Skill: arxiv_researcher — arXiv 论文搜索（蒸馏自 MiMo Code）
=============================================================
搜索 arXiv 学术论文数据库，返回论文标题、作者、摘要、PDF链接。
"""

import json
import os
import re
import traceback
from typing import Dict, Any
from xml.etree import ElementTree

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "arxiv_researcher",
    "description": "搜索 arXiv 学术论文数据库，返回论文标题、作者、摘要、PDF链接。蒸馏自 MiMo Code arxiv skill。",
    "category": "research",
    "version": "1.0.0",
}


def _lazy_import(lib_name: str):
    try:
        mod = __import__(lib_name)
        for part in lib_name.split('.')[1:]:
            mod = getattr(mod, part)
        return mod
    except (ImportError, AttributeError):
        return None


def execute(
    query: str = "",
    max_results: int = 5,
    sort_by: str = "relevance",
    category: str = "",
) -> SkillResult:
    """搜索 arXiv 论文"""
    if not query:
        return SkillResult(success=False, error="query 参数为空")

    requests = _lazy_import('requests')
    if requests is None:
        return SkillResult(success=False, error="依赖库 'requests' 未安装", output="pip install requests")

    try:
        # 构建 arXiv API URL
        sort_map = {'relevance': 'relevance', 'lastUpdatedDate': 'submittedDate', 'submittedDate': 'submittedDate'}
        sort_param = sort_map.get(sort_by, 'relevance')

        url = f"http://export.arxiv.org/api/query?search_query=all:{query.replace(' ', '+')}&start=0&max_results={max_results}&sortBy={sort_param}"
        if category:
            url += f"&cat={category}"

        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            return SkillResult(success=False, error=f"arXiv API 返回 HTTP {resp.status_code}")

        # 解析 Atom XML
        root = ElementTree.fromstring(resp.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        papers = []
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns).text.strip().replace('\n', ' ') if entry.find('atom:title', ns) is not None else ''
            summary = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')[:300] if entry.find('atom:summary', ns) is not None else ''
            authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns) if a.find('atom:name', ns) is not None]
            pdf_link = ''
            for link in entry.findall('atom:link', ns):
                if link.get('title') == 'pdf':
                    pdf_link = link.get('href', '')
            entry_id = entry.find('atom:id', ns).text if entry.find('atom:id', ns) is not None else ''
            published = entry.find('atom:published', ns).text if entry.find('atom:published', ns) is not None else ''
            papers.append({
                'title': title,
                'authors': authors[:5],
                'summary': summary,
                'pdf_url': pdf_link,
                'arxiv_url': entry_id,
                'published': published[:10] if published else '',
            })

        if not papers:
            return SkillResult(success=True, output=f"搜索 '{query}': 未找到论文", data={'papers': []})

        output_parts = [f"arXiv 搜索 '{query}' 找到 {len(papers)} 篇论文:"]
        for i, p in enumerate(papers, 1):
            output_parts.append(f"\n{i}. {p['title']}")
            output_parts.append(f"   作者: {', '.join(p['authors'])}")
            output_parts.append(f"   摘要: {p['summary'][:200]}...")
            if p['pdf_url']:
                output_parts.append(f"   PDF: {p['pdf_url']}")

        return SkillResult(
            success=True,
            output="\n".join(output_parts),
            data={'papers': papers, 'query': query, 'count': len(papers)},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"arXiv 搜索失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="arxiv_researcher",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "最大返回数", "default": 5},
                "sort_by": {"type": "string", "enum": ["relevance", "lastUpdatedDate", "submittedDate"], "description": "排序方式"},
                "category": {"type": "string", "description": "arXiv 分类（如 cs.AI）"},
            },
            "required": ["query"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
