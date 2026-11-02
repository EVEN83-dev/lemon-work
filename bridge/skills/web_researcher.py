import urllib.parse
from collections import Counter

from .models import SkillResult, SkillDef

METADATA = {
    "name": "web_researcher",
    "version": "1.0.0",
    "category": "research",
    "description": "Quick web search and summarize.",
}


def execute(query: str, max_results: int = 5, **kwargs) -> SkillResult:
    max_results = max(3, min(10, max_results))

    try:
        import requests
        results = _search(query, max_results)
        if results:
            report = _build_results_report(query, results)
            return SkillResult.ok(
                output=report,
                data={"needs_llm": False, "results_count": len(results), "results": results},
            )
        else:
            report = _build_fallback_report(query, max_results)
            return SkillResult.ok(
                output=report,
                data={"needs_llm": False, "results_count": 0},
            )
    except ImportError:
        report = _build_fallback_report(query, max_results)
        return SkillResult.ok(
            output=report,
            data={"needs_llm": False, "results_count": 0, "mode": "local"},
        )
    except Exception as e:
        report = _build_fallback_report(query, max_results)
        return SkillResult.ok(
            output=report,
            data={"needs_llm": False, "results_count": 0, "error": str(e)},
        )


def _search(query: str, max_results: int) -> list:
    import requests
    results = []
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        abstract = data.get("Abstract", "")
        if abstract:
            results.append({"title": data.get("Heading", ""), "snippet": abstract, "url": data.get("AbstractURL", "")})
        for topic in data.get("RelatedTopics", [])[:max_results - len(results)]:
            if isinstance(topic, dict) and "Text" in topic:
                results.append({"title": topic.get("Text", "")[:80], "snippet": topic["Text"], "url": topic.get("FirstURL", "")})
    except Exception:
        pass
    return results[:max_results]


def _build_results_report(query: str, results: list) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("WEB RESEARCH: " + query)
    lines.append("=" * 60)
    lines.append("")
    lines.append("Results found: " + str(len(results)))
    lines.append("")

    for i, r in enumerate(results, 1):
        lines.append(str(i) + ". " + r.get("title", "Untitled"))
        snippet = r.get("snippet", "")
        if snippet:
            lines.append("   " + snippet[:300])
        url = r.get("url", "")
        if url:
            lines.append("   URL: " + url)
        lines.append("")

    all_text = " ".join(r.get("snippet", "") for r in results).lower()
    words = all_text.split()
    word_freq = Counter(w for w in words if len(w) > 4)
    top = word_freq.most_common(8)

    if top:
        lines.append("--- KEY TERMS ---")
        lines.append("")
        for word, count in top:
            lines.append("  " + word + " (" + str(count) + ")")
        lines.append("")

    lines.append("--- SUMMARY ---")
    lines.append("")
    lines.append("Query: " + query)
    lines.append("Sources: " + str(len(results)))
    if top:
        lines.append("Dominant terms: " + ", ".join(w for w, _ in top[:5]))

    return "\n".join(lines)


def _build_fallback_report(query: str, max_results: int) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("WEB RESEARCH: " + query)
    lines.append("=" * 60)
    lines.append("")
    lines.append("Mode: Local analysis (network unavailable or no results)")
    lines.append("")

    query_words = query.lower().split()
    keywords = [w for w in query_words if len(w) > 2]

    lines.append("--- QUERY ANALYSIS ---")
    lines.append("")
    lines.append("Original query: " + query)
    lines.append("Keywords extracted: " + ", ".join(keywords))
    lines.append("")

    lines.append("--- SUGGESTED SEARCH STRATEGIES ---")
    lines.append("")
    search_variants = [
        query,
        " ".join(keywords[:3]) + " overview",
        " ".join(keywords[:3]) + " tutorial",
        " ".join(keywords[:3]) + " review",
    ]
    for i, variant in enumerate(search_variants, 1):
        lines.append(str(i) + ". " + variant)

    lines.append("")

    lines.append("--- DIRECT SEARCH URLS ---")
    lines.append("")
    encoded = urllib.parse.quote(query)
    lines.append("  DuckDuckGo:  https://duckduckgo.com/?q=" + encoded)
    lines.append("  Google:      https://www.google.com/search?q=" + encoded)
    lines.append("  Wikipedia:   https://en.wikipedia.org/wiki/Special:Search/" + encoded)
    lines.append("  Scholar:     https://scholar.google.com/scholar?q=" + encoded)
    if len(keywords) >= 2:
        combined = urllib.parse.quote(" AND ".join(keywords[:3]))
        lines.append("  Combined:    https://duckduckgo.com/?q=" + combined)
    lines.append("")

    lines.append("--- RESEARCH ANGLES ---")
    lines.append("")
    angles = ["definition and basics", "current trends", "comparison with alternatives", "best practices", "common issues and solutions"]
    for angle in angles:
        lines.append("  - " + query + " " + angle)
    lines.append("")

    lines.append("Note: Install 'requests' for live web search results.")

    return "\n".join(lines)


def register(registry) -> None:
    registry.register(SkillDef(
        name="web_researcher",
        description="[DEPRECATED] Use business.web_researcher instead. Legacy DuckDuckGo JSON API researcher.",
        category="research",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (3-10)",
                    "minimum": 3,
                    "maximum": 10,
                },
            },
            "required": ["query"],
        },
        handler=execute,
        timeout=30,
        deprecated=True,
        deprecation_message="Superseded by business.web_researcher (DDG HTML scraping with BS4, content extraction, deduplication).",
    ))
