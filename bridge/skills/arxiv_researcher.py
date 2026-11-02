import logging
import xml.etree.ElementTree as ET

from .models import SkillResult, SkillDef, SkillMetadata

logger = logging.getLogger(__name__)

METADATA = {
    "name": "arxiv_researcher",
    "version": "2.0.0",
    "category": "research",
    "description": "Search arxiv papers with HTTPS, retry, and pagination support.",
}

ARXIV_API = "https://export.arxiv.org/api/query"
_MAX_RETRIES = 3
_RETRY_DELAY = 2
_PAGE_SIZE = 20


def execute(query: str, max_papers: int = 10, page: int = 0, **kwargs) -> SkillResult:
    max_papers = max(5, min(50, max_papers))

    try:
        import requests
    except ImportError:
        report = _build_local_analysis(query, max_papers)
        return SkillResult.ok(
            output=report,
            data={"needs_llm": False, "query": query, "mode": "local_analysis"},
        )

    try:
        papers = _search_arxiv(query, max_papers, page)
        if papers:
            output = _format_papers(query, papers)
            return SkillResult.ok(
                output=output,
                data={
                    "needs_llm": False,
                    "papers": papers,
                    "papers_count": len(papers),
                    "query": query,
                    "page": page,
                    "has_more": len(papers) >= max_papers,
                },
            )
        else:
            report = _build_local_analysis(query, max_papers)
            return SkillResult.ok(
                output=report,
                data={"needs_llm": False, "papers": [], "papers_count": 0, "query": query},
            )
    except Exception as e:
        logger.warning("ArXiv research error for '%s': %s", query, e)
        return SkillResult.fail("ArXiv research error: " + str(e))


def _build_local_analysis(query: str, max_papers: int) -> str:
    import textwrap

    keywords = [w.strip() for w in query.replace(",", " ").split() if len(w.strip()) > 2]
    lines = [
        "=== ArXiv Research: " + query + " ===",
        "Mode: Local analysis (network unavailable)",
        "",
        "Query Analysis:",
        "  Original query: " + query,
        "  Extracted keywords: " + ", ".join(keywords[:10]),
        "",
        "Suggested ArXiv Search Strategies:",
    ]
    for i, kw in enumerate(keywords[:8], 1):
        lines.append("  " + str(i) + ". all:\"" + kw + "\"")
    lines.append("")
    lines.append("Suggested Combined Queries:")
    if len(keywords) >= 2:
        lines.append("  - all:\"" + " AND ".join(keywords[:3]) + "\"")
        lines.append("  - all:\"" + " OR ".join(keywords[:3]) + "\"")
    lines.append("")
    lines.append("Direct ArXiv URLs:")
    import urllib.parse
    encoded = urllib.parse.quote("all:" + query)
    lines.append("  - https://arxiv.org/search/?query=" + urllib.parse.quote(query) + "&searchtype=all")
    lines.append("  - https://export.arxiv.org/api/query?search_query=" + encoded + "&max_results=" + str(max_papers))
    lines.append("")
    lines.append("Research Directions for '" + query + "':")
    aspects = ["survey", "recent advances", "benchmarks", "methodology", "applications"]
    for a in aspects:
        lines.append("  - " + query + " " + a)
    lines.append("")
    lines.append("Note: Install the 'requests' package for live ArXiv API access.")
    return "\n".join(lines)


def _search_arxiv(query: str, max_papers: int, page: int = 0) -> list:
    import requests
    import time as _time

    papers = []
    start = page * max_papers
    remaining = max_papers
    current_start = start

    while remaining > 0:
        batch_size = min(_PAGE_SIZE, remaining)
        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.get(
                    ARXIV_API,
                    params={
                        "search_query": "all:" + query,
                        "start": current_start,
                        "max_results": batch_size,
                    },
                    timeout=20,
                    headers={"User-Agent": "LemonAgent/2.0"},
                )
                resp.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                logger.info(
                    "ArXiv API retry %d/%d for '%s' (start=%d): %s",
                    attempt + 1, _MAX_RETRIES, query, current_start, e,
                )
                if attempt < _MAX_RETRIES - 1:
                    _time.sleep(_RETRY_DELAY * (attempt + 1))
                else:
                    logger.warning("ArXiv API failed after %d retries: %s", _MAX_RETRIES, e)
                    return papers

        try:
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            page_entries = root.findall("atom:entry", ns)
            if not page_entries:
                break
            for entry in page_entries:
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                published_el = entry.find("atom:published", ns)
                link_el = entry.find("atom:id", ns)
                author_els = entry.findall("atom:author", ns)

                title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""
                summary = summary_el.text.strip().replace("\n", " ")[:500] if summary_el is not None and summary_el.text else ""
                published = published_el.text[:10] if published_el is not None and published_el.text else ""
                url = link_el.text.strip() if link_el is not None and link_el.text else ""
                authors = ", ".join(
                    a_el.text
                    for a_el in (a.find("atom:name", ns) for a in author_els)
                    if a_el is not None and a_el.text
                )

                doi_el = entry.find("atom:doi", ns)
                doi = doi_el.text.strip() if doi_el is not None and doi_el.text else ""

                if title and title != "Error":
                    papers.append({
                        "title": title,
                        "summary": summary,
                        "published": published,
                        "url": url,
                        "authors": authors,
                        "doi": doi,
                    })
        except ET.ParseError as e:
            logger.warning("ArXiv XML parse error: %s", e)
            break

        current_start += batch_size
        remaining -= len(page_entries)
        if len(page_entries) < batch_size:
            break

    return papers


def _format_papers(query: str, papers: list) -> str:
    lines = ["=== ArXiv Research: " + query + " ==="]
    lines.append("Found " + str(len(papers)) + " papers\n")
    for i, p in enumerate(papers, 1):
        lines.append(str(i) + ". " + p["title"])
        if p.get("authors"):
            lines.append("   Authors: " + p["authors"])
        if p.get("published"):
            lines.append("   Published: " + p["published"])
        lines.append("   " + p.get("summary", "No abstract available")[:200])
        if p.get("url"):
            lines.append("   URL: " + p["url"])
        if p.get("doi"):
            lines.append("   DOI: " + p["doi"])
        lines.append("")
    return "\n".join(lines)


def register(registry) -> None:
    from .models import SkillMetadata
    registry.register(SkillDef(
        name="arxiv_researcher",
        description="Search arxiv papers with HTTPS, retry (3 attempts), and pagination. Returns structured paper data.",
        category="research",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for arxiv papers",
                },
                "max_papers": {
                    "type": "integer",
                    "description": "Maximum number of papers to retrieve (5-50)",
                    "minimum": 5,
                    "maximum": 50,
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for pagination (0-based)",
                    "minimum": 0,
                    "default": 0,
                },
            },
            "required": ["query"],
        },
        handler=execute,
        timeout=60,
        metadata=SkillMetadata(
            version="2.0.0",
            tags=["arxiv", "research", "papers", "academic"],
            dependencies=["requests"],
        ),
    ))
