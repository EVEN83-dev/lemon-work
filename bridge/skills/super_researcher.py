import textwrap
import urllib.parse
from collections import Counter

from .models import SkillResult, SkillDef

METADATA = {
    "name": "super_researcher",
    "version": "1.0.0",
    "category": "research",
    "description": "Enhanced research with multiple rounds and configurable breadth.",
}


def execute(topic: str, rounds: int = 3, breadth: int = 5, **kwargs) -> SkillResult:
    rounds = max(2, min(5, rounds))
    breadth = max(3, min(8, breadth))

    round_queries = _generate_round_queries(topic, rounds, breadth)

    try:
        import requests
        all_findings = []
        for i, queries in enumerate(round_queries):
            round_findings = []
            for query in queries:
                results = _search_single(query, max_results=2)
                round_findings.extend(results)
            all_findings.append({"round": i + 1, "queries": queries, "results": round_findings})

        has_results = any(f["results"] for f in all_findings)
        if has_results:
            report = _compile_full_report(topic, rounds, breadth, all_findings)
            return SkillResult.ok(
                output=report,
                data={
                    "needs_llm": False,
                    "rounds_completed": rounds,
                    "total_results": sum(len(f["results"]) for f in all_findings),
                },
            )
        else:
            report = _build_local_report(topic, rounds, breadth, round_queries)
            return SkillResult.ok(
                output=report,
                data={"needs_llm": False, "rounds_completed": rounds, "total_results": 0},
            )
    except Exception:
        report = _build_local_report(topic, rounds, breadth, round_queries)
        return SkillResult.ok(
            output=report,
            data={"needs_llm": False, "rounds_completed": 0},
        )


def _generate_round_queries(topic: str, rounds: int, breadth: int) -> list:
    aspects = [
        topic + " overview and fundamentals",
        topic + " history and origins",
        topic + " current state and trends",
        topic + " challenges and controversies",
        topic + " future predictions and research",
    ]
    all_rounds = []
    for r in range(rounds):
        start = (r * breadth) % len(aspects)
        round_queries = []
        for b in range(breadth):
            idx = (start + b) % len(aspects)
            round_queries.append(aspects[idx])
        all_rounds.append(round_queries)
    return all_rounds


def _search_single(query: str, max_results: int) -> list:
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
            results.append({"query": query, "snippet": abstract, "source": data.get("AbstractURL", "")})
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and "Text" in topic:
                results.append({"query": query, "snippet": topic["Text"], "source": topic.get("FirstURL", "")})
    except Exception:
        pass
    return results[:max_results]


def _compile_full_report(topic: str, rounds: int, breadth: int, all_findings: list) -> str:
    lines = []
    lines.append("=" * 64)
    lines.append("SUPER RESEARCH REPORT: " + topic)
    lines.append("=" * 64)
    lines.append("")
    lines.append("Configuration: " + str(rounds) + " rounds, " + str(breadth) + " breadth per round")
    lines.append("Total results: " + str(sum(len(f["results"]) for f in all_findings)))
    lines.append("")

    all_snippets = []
    for round_data in all_findings:
        lines.append("--- Round " + str(round_data["round"]) + " ---")
        lines.append("Queries: " + ", ".join(round_data["queries"]))
        if round_data["results"]:
            for r in round_data["results"]:
                lines.append("  - " + r["snippet"][:200])
                if r.get("source"):
                    lines.append("    Source: " + r["source"])
                all_snippets.append(r["snippet"])
        else:
            lines.append("  (No results for this round)")
        lines.append("")

    lines.append("--- KEY TERM ANALYSIS ---")
    lines.append("")
    all_words = " ".join(all_snippets).lower().split()
    word_freq = Counter(w for w in all_words if len(w) > 4)
    top_words = word_freq.most_common(10)
    for word, count in top_words:
        lines.append("  " + word + ": " + str(count) + " occurrences")
    lines.append("")

    lines.append("--- RESEARCH SYNTHESIS ---")
    lines.append("")
    lines.append("Topic: " + topic)
    lines.append("Rounds completed: " + str(rounds))
    lines.append("Sources found: " + str(len(all_snippets)))
    if top_words:
        lines.append("Dominant themes: " + ", ".join(w for w, _ in top_words[:5]))
    lines.append("")

    return "\n".join(lines)


def _build_local_report(topic: str, rounds: int, breadth: int, round_queries: list) -> str:
    lines = []
    lines.append("=" * 64)
    lines.append("SUPER RESEARCH REPORT: " + topic)
    lines.append("=" * 64)
    lines.append("")
    lines.append("Mode: Local analysis (network unavailable or no results)")
    lines.append("Configuration: " + str(rounds) + " rounds, " + str(breadth) + " breadth per round")
    lines.append("")

    topic_words = topic.lower().split()
    keyword_freq = Counter(w for w in topic_words if len(w) > 2)

    lines.append("--- QUERY PLAN ---")
    lines.append("")
    for round_data in round_queries:
        ri = round_queries.index(round_data) + 1
        lines.append("Round " + str(ri) + ":")
        for q in round_data:
            lines.append("  - " + q)
        lines.append("")

    lines.append("--- TOPIC DECOMPOSITION ---")
    lines.append("")
    lines.append("Core keywords: " + ", ".join(keyword_freq.keys()))
    lines.append("")

    aspects = ["overview", "history", "current trends", "challenges", "future outlook"]
    lines.append("--- RESEARCH DIRECTIONS ---")
    lines.append("")
    for asp in aspects:
        lines.append("  - " + topic + " " + asp)
    lines.append("")

    lines.append("--- SUGGESTED SEARCH URLS ---")
    lines.append("")
    encoded = urllib.parse.quote(topic)
    lines.append("  - https://duckduckgo.com/?q=" + encoded)
    lines.append("  - https://scholar.google.com/scholar?q=" + encoded)
    lines.append("  - https://en.wikipedia.org/wiki/Special:Search/" + encoded)
    lines.append("  - https://arxiv.org/search/?query=" + encoded + "&searchtype=all")
    lines.append("")

    lines.append("--- STRUCTURED OUTLINE ---")
    lines.append("")
    lines.append("1. Introduction to " + topic)
    lines.append("2. Historical Context and Evolution")
    lines.append("3. Current State of the Art")
    lines.append("4. Key Challenges and Debates")
    lines.append("5. Future Directions and Open Questions")
    lines.append("6. Conclusions and Recommendations")
    lines.append("")
    lines.append("Note: Install 'requests' for live search results.")

    return "\n".join(lines)


def register(registry) -> None:
    registry.register(SkillDef(
        name="super_researcher",
        description="Enhanced multi-round research with configurable breadth per round.",
        category="research",
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic to research",
                },
                "rounds": {
                    "type": "integer",
                    "description": "Number of research rounds (2-5)",
                    "minimum": 2,
                    "maximum": 5,
                },
                "breadth": {
                    "type": "integer",
                    "description": "Number of aspects per round (3-8)",
                    "minimum": 3,
                    "maximum": 8,
                },
            },
            "required": ["topic"],
        },
        handler=execute,
        timeout=90,
    ))
