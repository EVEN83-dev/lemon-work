import logging
import re
import string
from collections import Counter
from typing import Any, Dict, List

from .models import SkillResult, SkillDef

logger = logging.getLogger(__name__)

METADATA = {
    "name": "deep_researcher",
    "version": "2.0.0",
    "category": "research",
    "description": "Deep research on a topic with configurable depth and source count.",
}

_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "not", "no", "nor", "so", "if", "then",
    "than", "too", "very", "just", "about", "also", "some", "any", "all",
    "each", "every", "both", "few", "more", "most", "other", "into", "over",
    "after", "before", "between", "under", "again", "there", "when", "where",
    "why", "how", "what", "which", "who", "whom", "such", "only", "own",
    "same", "up", "out", "off", "down", "as", "we", "you", "they", "he",
    "she", "i", "me", "my", "your", "his", "her", "our", "their", "them",
    "him", "us", "am", "through", "during", "while", "because", "since",
    "until", "although", "though", "even", "however", "yet", "still",
    "much", "many", "well", "back", "even", "new", "old", "first", "last",
    "long", "great", "little", "own", "get", "make", "go", "know", "take",
    "see", "come", "think", "look", "want", "give", "use", "find", "tell",
    "ask", "work", "seem", "feel", "try", "leave", "call", "keep", "let",
    "begin", "show", "hear", "play", "run", "move", "live", "believe",
    "hold", "bring", "happen", "write", "provide", "sit", "stand", "lose",
    "pay", "meet", "include", "continue", "set", "learn", "change", "lead",
    "understand", "watch", "follow", "stop", "create", "speak", "read",
    "allow", "add", "spend", "grow", "open", "walk", "win", "offer",
    "remember", "love", "consider", "appear", "buy", "wait", "serve",
    "die", "send", "expect", "build", "stay", "fall", "cut", "reach",
    "kill", "remain", "suggest", "raise", "pass", "sell", "require",
    "report", "decide", "pull", "develop", "eat", "already", "along",
    "among", "another", "anything", "around", "away", "became", "become",
    "behind", "beside", "beyond", "cause", "certain", "clear", "close",
    "common", "complete", "enough", "especially", "ever", "example",
    "fact", "far", "given", "going", "gone", "got", "hard", "help",
    "high", "home", "important", "instead", "itself", "keep", "kept",
    "known", "late", "left", "less", "likely", "little", "look", "might",
    "must", "need", "never", "next", "nothing", "often", "once", "order",
    "part", "perhaps", "point", "possible", "probably", "quite", "rather",
    "really", "right", "room", "say", "seems", "several", "short",
    "simply", "small", "something", "sometimes", "sort", "state", "still",
    "sure", "system", "thing", "thought", "true", "turned", "used", "using",
    "usually", "whether", "without", "world", "would", "year", "years",
})


def execute(topic: str, depth: int = 3, sources: int = 5, **kwargs) -> SkillResult:
    depth = max(1, min(5, depth))
    sources = max(3, min(10, sources))

    has_requests = False
    try:
        import requests
        has_requests = True
    except ImportError:
        pass

    if has_requests:
        try:
            search_results = _web_search(topic, sources)
            sub_topics = _extract_sub_topics(topic, depth, search_results)
            for sub in sub_topics:
                sub_results = _web_search(sub, max(2, sources // 2))
                search_results.extend(sub_results)

            deduped = _deduplicate_results(search_results)
            report = _build_structured_report(topic, deduped, depth)
            return SkillResult.ok(
                output=report,
                data={
                    "needs_llm": False,
                    "sources_count": len(deduped),
                    "sub_topics": sub_topics,
                    "research_mode": "web",
                },
            )
        except Exception as e:
            logger.exception("Web research failed for topic '%s'", topic)
            report = _local_analysis_report(topic, depth, sources, error=str(e))
            return SkillResult.ok(
                output=report,
                data={
                    "needs_llm": False,
                    "sources_count": 0,
                    "research_mode": "local_fallback",
                    "fallback_reason": str(e),
                },
            )
    else:
        report = _local_analysis_report(topic, depth, sources)
        return SkillResult.ok(
            output=report,
            data={
                "needs_llm": False,
                "sources_count": 0,
                "research_mode": "local_only",
            },
        )


def _web_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    import requests

    results: List[Dict[str, Any]] = []
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
            results.append({
                "title": data.get("Heading", query),
                "snippet": abstract,
                "source": data.get("AbstractURL", ""),
            })

        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and "Text" in topic:
                results.append({
                    "title": topic.get("Text", "")[:80],
                    "snippet": topic["Text"],
                    "source": topic.get("FirstURL", ""),
                })
            elif isinstance(topic, dict) and "Topics" in topic:
                for sub in topic["Topics"][:2]:
                    if isinstance(sub, dict) and "Text" in sub:
                        results.append({
                            "title": sub.get("Text", "")[:80],
                            "snippet": sub["Text"],
                            "source": sub.get("FirstURL", ""),
                        })

        definition = data.get("Definition", "")
        if definition and not any(r["snippet"] == definition for r in results):
            results.append({
                "title": data.get("DefinitionTitle", query),
                "snippet": definition,
                "source": data.get("DefinitionURL", ""),
            })

    except requests.exceptions.Timeout:
        logger.warning("Web search timed out for query: %s", query)
    except requests.exceptions.HTTPError as e:
        logger.warning("Web search HTTP error for query '%s': %s", query, e)
    except requests.exceptions.RequestException as e:
        logger.warning("Web search request failed for query '%s': %s", query, e)
    except (ValueError, KeyError) as e:
        logger.warning("Web search response parsing failed for query '%s': %s", query, e)

    return results[:max_results]


def _extract_sub_topics(topic: str, depth: int, search_results: List[Dict[str, Any]]) -> List[str]:
    topics: List[str] = []

    if search_results:
        word_freq = _compute_word_frequency(search_results, top_n=depth * 3)
        topic_words = [w for w, _ in word_freq if w.lower() not in _STOP_WORDS and len(w) > 3]
        for word in topic_words[:depth]:
            topics.append(f"{topic} {word}")
    else:
        heuristic_suffixes = {
            2: ["overview"],
            3: ["overview", "recent developments"],
            4: ["overview", "recent developments", "analysis"],
            5: ["overview", "recent developments", "analysis", "future outlook"],
        }
        suffixes = heuristic_suffixes.get(depth, ["overview"])
        for suffix in suffixes[:depth]:
            topics.append(f"{topic} {suffix}")

    return topics


def _compute_word_frequency(results: List[Dict[str, Any]], top_n: int = 10) -> List[tuple]:
    all_text = " ".join(r.get("snippet", "") for r in results)
    all_text += " " + " ".join(r.get("title", "") for r in results)
    words = re.findall(r"[a-zA-Z]{3,}", all_text.lower())
    filtered = [w for w in words if w not in _STOP_WORDS]
    counter = Counter(filtered)
    return counter.most_common(top_n)


def _deduplicate_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_snippets: set = set()
    deduped: List[Dict[str, Any]] = []
    for r in results:
        snippet_key = r.get("snippet", "")[:120].strip().lower()
        if snippet_key and snippet_key in seen_snippets:
            continue
        if snippet_key:
            seen_snippets.add(snippet_key)
        deduped.append(r)
    return deduped


def _build_structured_report(topic: str, results: List[Dict[str, Any]], depth: int) -> str:
    sections: List[str] = []

    sections.append(f"# Research Report: {topic}")
    sections.append("")
    sections.append(f"**Depth Level:** {depth}/5")
    sections.append(f"**Sources Found:** {len(results)}")

    if results:
        key_terms = _compute_word_frequency(results, top_n=5)
        if key_terms:
            terms_str = ", ".join(w for w, _ in key_terms)
            sections.append(f"**Key Terms:** {terms_str}")

    sections.append("")
    sections.append("---")
    sections.append("")

    sections.append("## Summary")
    sections.append("")
    if results:
        combined = " ".join(r.get("snippet", "") for r in results)
        sentences = re.split(r'(?<=[.!?])\s+', combined)
        top_sentences = sentences[:max(3, depth)]
        sections.append(" ".join(top_sentences))
    else:
        sections.append(f"No direct results were found for '{topic}'. The topic may be too specific or the search service may be unavailable.")
    sections.append("")

    sections.append("## Key Findings")
    sections.append("")
    if results:
        for i, r in enumerate(results, 1):
            title = r.get("title", "Untitled")
            snippet = r.get("snippet", "No details available")
            source = r.get("source", "")
            sections.append(f"### {i}. {title}")
            sections.append("")
            sections.append(snippet)
            if source:
                sections.append(f"\nSource: {source}")
            sections.append("")
    else:
        sections.append("No findings from web search.")
        sections.append("")

    if depth >= 3 and results:
        sections.append("## Topic Analysis")
        sections.append("")
        word_freq = _compute_word_frequency(results, top_n=8)
        if word_freq:
            sections.append("### Frequent Terms")
            sections.append("")
            for word, count in word_freq:
                sections.append(f"- **{word}**: {count} occurrences")
            sections.append("")

    if depth >= 4 and results:
        sections.append("## Perspectives")
        sections.append("")
        perspectives = _extract_perspectives(results)
        for p in perspectives:
            sections.append(f"- {p}")
        sections.append("")

    if depth >= 5 and results:
        sections.append("## Open Questions")
        sections.append("")
        questions = _generate_questions(topic, results)
        for q in questions:
            sections.append(f"- {q}")
        sections.append("")

    sections.append("## References")
    sections.append("")
    ref_count = 0
    for r in results:
        source = r.get("source", "")
        if source:
            ref_count += 1
            sections.append(f"{ref_count}. [{source}]({source})")
    if ref_count == 0:
        sections.append("No external references available.")
    sections.append("")

    return "\n".join(sections)


def _extract_perspectives(results: List[Dict[str, Any]]) -> List[str]:
    perspectives: List[str] = []
    perspective_patterns = [
        r"however[, ]",
        r"on the other hand",
        r"critics? (argue|say|claim)",
        r"supporters? (argue|say|claim)",
        r"some (believe|think|argue)",
        r"others (believe|think|argue)",
        r"debate",
        r"controvers",
        r"disagree",
    ]

    for r in results:
        snippet = r.get("snippet", "")
        for pattern in perspective_patterns:
            if re.search(pattern, snippet, re.IGNORECASE):
                sentence = _extract_sentence_around(snippet, pattern)
                if sentence and sentence not in perspectives:
                    perspectives.append(sentence)
                break

    if not perspectives:
        for r in results[:2]:
            snippet = r.get("snippet", "")
            sentences = re.split(r'(?<=[.!?])\s+', snippet)
            if sentences and sentences[0]:
                perspectives.append(sentences[0])

    return perspectives[:5]


def _extract_sentence_around(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return ""
    start = text.rfind(". ", 0, match.start()) + 2
    end = text.find(". ", match.end())
    if end == -1:
        end = len(text)
    else:
        end += 1
    start = max(0, start)
    return text[start:end].strip()


def _generate_questions(topic: str, results: List[Dict[str, Any]]) -> List[str]:
    questions: List[str] = []
    word_freq = _compute_word_frequency(results, top_n=4)
    top_words = [w for w, _ in word_freq]

    questions.append(f"What are the most significant developments in {topic}?")
    if top_words:
        questions.append(f"How does {' '.join(top_words[:2])} relate to the broader context of {topic}?")
    questions.append(f"What evidence supports the main claims about {topic}?")
    if len(top_words) >= 2:
        questions.append(f"Are there conflicting viewpoints on {top_words[0]} and {top_words[1]} within {topic}?")
    questions.append(f"What areas of {topic} remain underexplored?")

    return questions[:5]


def _local_analysis_report(topic: str, depth: int, sources: int, error: str = "") -> str:
    sections: List[str] = []

    mode_label = "Local Analysis (Limited Research)" if not error else "Local Analysis (Web Search Failed)"
    sections.append(f"# {mode_label}: {topic}")
    sections.append("")
    sections.append(f"**Depth Level:** {depth}/5")
    sections.append(f"**Target Sources:** {sources}")
    sections.append(f"**Mode:** Limited (no web search)")
    if error:
        sections.append(f"**Fallback Reason:** {error}")
    sections.append("")
    sections.append("---")
    sections.append("")

    sections.append("## Topic Decomposition")
    sections.append("")
    components = _decompose_topic(topic)
    for i, comp in enumerate(components, 1):
        sections.append(f"{i}. {comp}")
    sections.append("")

    sections.append("## Keyword Analysis")
    sections.append("")
    keywords = _extract_keywords(topic)
    for kw in keywords:
        sections.append(f"- **{kw['word']}**: frequency {kw['score']}, category: {kw['category']}")
    sections.append("")

    if depth >= 3:
        sections.append("## Suggested Research Angles")
        sections.append("")
        angles = _suggest_angles(topic, depth)
        for angle in angles:
            sections.append(f"- {angle}")
        sections.append("")

    sections.append("## Search Queries to Try")
    sections.append("")
    queries = _generate_search_queries(topic, depth)
    for q in queries:
        sections.append(f"- `{q}`")
    sections.append("")

    sections.append("---")
    sections.append("")
    sections.append("*This report was generated using local analysis only. Web search was not available. Findings are limited to structural and keyword-based analysis of the topic.*")

    return "\n".join(sections)


def _decompose_topic(topic: str) -> List[str]:
    parts = re.split(r"\s+(?:of|in|on|for|and|vs?\.?|versus)\s+", topic, flags=re.IGNORECASE)
    if len(parts) <= 1:
        words = topic.split()
        if len(words) > 1:
            parts = [" ".join(words[:len(words) // 2]), " ".join(words[len(words) // 2:])]
        else:
            parts = [topic]

    components: List[str] = []
    for part in parts:
        cleaned = part.strip()
        if cleaned:
            components.append(cleaned)

    if not components:
        components = [topic]

    return components


def _extract_keywords(topic: str) -> List[Dict[str, Any]]:
    words = re.findall(r"[a-zA-Z]{2,}", topic)
    keywords: List[Dict[str, Any]] = []
    for w in words:
        lower = w.lower()
        if lower in _STOP_WORDS:
            category = "stopword"
            score = 1
        elif w[0].isupper():
            category = "proper_noun"
            score = 5
        elif len(w) > 6:
            category = "substantive"
            score = 4
        else:
            category = "general"
            score = 2
        keywords.append({"word": w, "score": score, "category": category})

    keywords.sort(key=lambda k: k["score"], reverse=True)
    return keywords


def _suggest_angles(topic: str, depth: int) -> List[str]:
    angles: List[str] = []
    angles.append(f"Historical evolution and origins of {topic}")
    if depth >= 3:
        angles.append(f"Current state of the art in {topic}")
        angles.append(f"Key challenges and limitations in {topic}")
    if depth >= 4:
        angles.append(f"Comparative analysis: {topic} vs. alternatives")
        angles.append(f"Stakeholder perspectives on {topic}")
    if depth >= 5:
        angles.append(f"Future trajectory and emerging trends in {topic}")
        angles.append(f"Interdisciplinary connections of {topic}")
    return angles


def _generate_search_queries(topic: str, depth: int) -> List[str]:
    queries: List[str] = [topic]
    modifiers = {
        2: ["overview"],
        3: ["overview", "recent research"],
        4: ["overview", "recent research", "analysis review"],
        5: ["overview", "recent research", "analysis review", "future trends predictions"],
    }
    suffixes = modifiers.get(depth, ["overview"])
    for suffix in suffixes:
        queries.append(f"{topic} {suffix}")
    return queries


def register(registry) -> None:
    registry.register(SkillDef(
        name="deep_researcher",
        description="Deep research on a topic using web search with configurable depth and source count.",
        category="research",
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic to research deeply",
                },
                "depth": {
                    "type": "integer",
                    "description": "Research depth from 1 (brief) to 5 (comprehensive)",
                    "minimum": 1,
                    "maximum": 5,
                },
                "sources": {
                    "type": "integer",
                    "description": "Number of sources to consult (3-10)",
                    "minimum": 3,
                    "maximum": 10,
                },
            },
            "required": ["topic"],
        },
        handler=execute,
        timeout=60,
    ))
