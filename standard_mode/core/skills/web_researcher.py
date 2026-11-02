# -*- coding: utf-8 -*-
"""
Skill: web_researcher — 网络爬虫与数据调研
============================================
抓取 URL 或搜索关键词，提取正文。支持 DuckDuckGo 搜索。
"""

import re
import traceback
from typing import Dict, Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "web_researcher",
    "description": "网络爬虫与数据调研：抓取 URL 或搜索关键词，提取正文。支持 DuckDuckGo 搜索。",
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


def _lib_missing(lib_name: str) -> SkillResult:
    return SkillResult(success=False, error=f"依赖库 '{lib_name}' 未安装", output=f"pip install {lib_name}")


def execute(
    url: str = "",
    query: str = "",
    max_pages: int = 3,
    extract_text: bool = True,
    render_js: bool = False,
) -> SkillResult:
    """网络调研 — 抓取页面 / 搜索信息
    
    ★ T365.13: render_js=True 时使用 JSRenderer 抓取JS动态页面
    """
    if not url and not query:
        return SkillResult(success=False, error="url 或 query 必须有一个")

    # ★ T365.13: JS渲染路径
    if render_js and url:
        try:
            from core.js_renderer import JSRenderer
            jr = JSRenderer()
            if not jr.is_available():
                return SkillResult(success=False, error="render_js需要Playwright，请执行: pip install playwright && playwright install chromium")
            fmt = "text" if extract_text else "html"
            result = jr.fetch(url, output_format=fmt)
            if result.get("success"):
                return SkillResult(success=True,
                                   output=f"JS渲染抓取完成\n标题: {result.get('title', '')}\n{result.get('output', '')}",
                                   data={'url': url, 'title': result.get('title', ''), 'format': fmt})
            return SkillResult(success=False, error=result.get('error', 'JS渲染失败'))
        except Exception as e:
            return SkillResult(success=False, error=f"JS渲染失败: {e}")

    requests = _lazy_import('requests')
    if requests is None:
        return _lib_missing('requests')

    bs4 = _lazy_import('bs4')
    if bs4 is None:
        return _lib_missing('beautifulsoup4')

    try:
        results = []
        search_backend = ""  # ★391B-3: 实际使用的搜索后端（bing/duckduckgo/空=URL直抓）

        if url:
            r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            r.encoding = r.apparent_encoding
            lxml_available = _lazy_import('lxml') is not None
            soup = bs4.BeautifulSoup(r.text, 'lxml' if lxml_available else 'html.parser')
            title = soup.title.string if soup.title else '(无标题)'

            if extract_text:
                for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                    tag.decompose()
                text = soup.get_text(separator='\n', strip=True)
                text = re.sub(r'\n{3,}', '\n\n', text)[:5000]
            else:
                text = r.text[:5000]

            results.append({'url': url, 'title': title, 'status': r.status_code, 'content': text})

        elif query:
            # ★391B-3: 搜索后端回退链 —— Bing 主源（国内可达）→ DuckDuckGo 兜底 →
            #   明示失败（禁静默空结果）。DDG 在国内被墙（WinError 10061 实证），
            #   原写死 DDG 导致搜索功能整体不可用。
            _UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            _q = requests.utils.quote(query)
            links = []
            search_backend = ""
            # --- 后端 1: Bing（cn.bing.com，解析 li.b_algo 结果块）---
            try:
                r = requests.get(f"https://cn.bing.com/search?q={_q}&count={max_pages}",
                                 timeout=12, headers=_UA)
                if r.status_code == 200:
                    soup = bs4.BeautifulSoup(r.text, 'html.parser')
                    for li in soup.select('li.b_algo')[:max_pages]:
                        a = li.select_one('h2 a')
                        if a and a.get('href'):
                            links.append({'title': a.get_text(strip=True), 'url': a['href']})
                    if links:
                        search_backend = "bing"
            except Exception:
                pass
            # --- 后端 2: DuckDuckGo 兜底（境外可达环境）---
            if not links:
                try:
                    r = requests.get(f"https://html.duckduckgo.com/html/?q={_q}",
                                     timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
                    soup = bs4.BeautifulSoup(r.text, 'html.parser')
                    for a in soup.select('.result__a')[:max_pages]:
                        href = a.get('href', '')
                        title = a.get_text(strip=True)
                        if href:
                            links.append({'title': title, 'url': href})
                    if links:
                        search_backend = "duckduckgo"
                except Exception:
                    pass
            # --- 双后端全失败：明示错误，禁静默空结果 ---
            if not links:
                return SkillResult(
                    success=False,
                    error=(f"搜索失败: Bing 与 DuckDuckGo 均不可达（query={query}）。"
                           f"请检查网络后重试，或直接提供 url 参数抓取"))

            for link in links[:max_pages]:
                try:
                    sub_r = requests.get(link['url'], timeout=10, headers=_UA)
                    sub_r.encoding = sub_r.apparent_encoding
                    sub_soup = bs4.BeautifulSoup(sub_r.text, 'html.parser')
                    for tag in sub_soup(['script', 'style']):
                        tag.decompose()
                    text = sub_soup.get_text(separator='\n', strip=True)[:2000]
                    results.append({'url': link['url'], 'title': link['title'], 'status': sub_r.status_code, 'content': text})
                except Exception as e:
                    results.append({'url': link['url'], 'title': link['title'], 'error': str(e)})

        output_parts = []
        for r in results:
            output_parts.append(f"标题: {r.get('title', '')}\nURL: {r.get('url', '')}\n摘要: {r.get('content', '')[:200]}...")
        _backend_note = f"（搜索源: {search_backend}）" if query and search_backend else ""
        return SkillResult(
            success=True,
            output=f"调研完成，共抓取 {len(results)} 页{_backend_note}\n" + "\n---\n".join(output_parts),
            data={'results': results, 'count': len(results),
                  **({'search_backend': search_backend} if query else {})},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"网络调研失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="web_researcher",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "直接抓取的 URL"},
                "query": {"type": "string", "description": "搜索关键词"},
                "max_pages": {"type": "integer", "description": "最多抓取页数", "default": 3},
                "extract_text": {"type": "boolean", "description": "是否提取纯文本", "default": True},
                "render_js": {"type": "boolean", "description": "T365.13: 是否使用Playwright渲染JS动态页面", "default": False},
            },
        },
        handler=execute,
        category=METADATA["category"],
        timeout=60,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
