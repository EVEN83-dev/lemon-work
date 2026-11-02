import re
from .models import SkillResult, SkillDef

METADATA = {
    "name": "fact_checker",
    "version": "1.0.0",
    "category": "research",
    "description": "Fact checking by cross-referencing multiple sources.",
}


def execute(claim: str, sources: int = 3, **kwargs) -> SkillResult:
    if not claim.strip():
        return SkillResult.fail("claim is required")

    sources = max(3, min(5, sources))

    try:
        import requests
        search_results = _search_claim(claim, sources)
        if search_results:
            output = _build_verification_report(claim, search_results)
            return SkillResult.ok(output=output, data={"needs_llm": False, "sources_found": len(search_results), "has_web_data": True})
        else:
            output = _build_no_results_report(claim)
            return SkillResult.ok(output=output, data={"needs_llm": False, "sources_found": 0, "has_web_data": False})
    except ImportError:
        output = _build_offline_report(claim, sources)
        return SkillResult.ok(output=output, data={"needs_llm": False, "sources_found": 0, "has_web_data": False, "mode": "offline_analysis"})
    except Exception as e:
        output = _build_error_report(claim, str(e))
        return SkillResult.ok(output=output, data={"needs_llm": False, "error": str(e), "has_web_data": False})


def _build_verification_report(claim: str, search_results: list) -> str:
    parts = [
        "=== Fact Check Report ===",
        "",
        "Claim: " + claim,
        "Sources consulted: " + str(len(search_results)),
        "",
        "[Source Findings]",
    ]

    for i, r in enumerate(search_results, 1):
        title = r.get("title", "Untitled")
        snippet = r.get("snippet", "N/A")
        url = r.get("url", "N/A")
        parts.append("")
        parts.append("Source " + str(i) + ": " + title)
        parts.append("  URL: " + url)
        parts.append("  Snippet: " + snippet[:300])
        parts.append("  Relevance: " + _assess_relevance(claim, snippet))

    parts.append("")
    parts.append("[Cross-Reference Analysis]")

    claim_keywords = _extract_keywords(claim)
    supporting = 0
    contradicting = 0
    neutral = 0

    for r in search_results:
        snippet = r.get("snippet", "").lower()
        title = r.get("title", "").lower()
        text = title + " " + snippet
        stance = _assess_stance(claim, text)
        if stance == "supporting":
            supporting += 1
        elif stance == "contradicting":
            contradicting += 1
        else:
            neutral += 1

    parts.append("  Sources supporting claim: " + str(supporting))
    parts.append("  Sources contradicting claim: " + str(contradicting))
    parts.append("  Sources neutral/unrelated: " + str(neutral))

    keyword_coverage = _keyword_coverage(claim_keywords, search_results)
    parts.append("  Keyword coverage: " + str(round(keyword_coverage * 100)) + "%")

    parts.append("")
    parts.append("[Verification Summary]")

    if len(search_results) == 0:
        parts.append("  No web sources found. Cannot verify claim.")
        parts.append("  Confidence: LOW")
        parts.append("  Accuracy Rating: UNVERIFIED (0/5)")
    else:
        score = _compute_accuracy_score(supporting, contradicting, neutral, keyword_coverage)
        confidence = _compute_confidence(supporting, contradicting, len(search_results), keyword_coverage)
        parts.append("  Accuracy Rating: " + str(score) + "/5")
        parts.append("  Confidence: " + confidence)
        parts.append("  Rating Explanation: " + _score_explanation(score))

    parts.append("")
    parts.append("Legend:")
    parts.append("  Accuracy: 1=Completely False, 2=Mostly False, 3=Mixed/Unverified, 4=Mostly True, 5=Completely True")
    parts.append("  Confidence: LOW/MEDIUM/HIGH based on source count and agreement")
    parts.append("")
    parts.append("Note: This is automated cross-reference analysis. Manual verification recommended for important claims.")

    return "\n".join(parts)


def _build_no_results_report(claim: str) -> str:
    parts = [
        "=== Fact Check Report ===",
        "",
        "Claim: " + claim,
        "Sources consulted: 0",
        "",
        "[Result]",
        "No web sources found matching this claim.",
        "",
        "[Claim Decomposition]",
    ]

    keywords = _extract_keywords(claim)
    parts.append("Key terms: " + ", ".join(keywords))
    parts.append("")
    parts.append("[Verification Status]")
    parts.append("  Accuracy Rating: UNVERIFIED (0/5)")
    parts.append("  Confidence: LOW")
    parts.append("  No corroborating or contradicting sources were found.")
    parts.append("  The claim could not be verified through web search.")
    parts.append("")
    parts.append("[Recommendations]")
    parts.append("  - Try rephrasing the claim with different keywords")
    parts.append("  - Check authoritative sources directly")
    parts.append("  - Consider that novel or very specific claims may not have web coverage")

    return "\n".join(parts)


def _build_offline_report(claim: str, target_sources: int) -> str:
    parts = [
        "=== Fact Check Report (Offline Mode) ===",
        "",
        "Claim: " + claim,
        "Target sources: " + str(target_sources),
        "Mode: Offline (requests library not available)",
        "",
        "[Claim Decomposition]",
    ]

    keywords = _extract_keywords(claim)
    parts.append("Key terms: " + ", ".join(keywords))
    parts.append("")

    parts.append("[Claim Structure Analysis]")
    sentences = re.split(r'[.!?]+', claim)
    sentences = [s.strip() for s in sentences if s.strip()]
    parts.append("Number of sub-claims: " + str(len(sentences)))
    for i, s in enumerate(sentences, 1):
        parts.append("  Sub-claim " + str(i) + ": " + s)
        claim_type = _classify_claim_type(s)
        parts.append("    Type: " + claim_type)
    parts.append("")

    parts.append("[Quantitative Assertions]")
    numbers = re.findall(r'\b\d+[\d,.]*\b', claim)
    percents = re.findall(r'\b\d+[\d,.]*\s*%', claim)
    if numbers or percents:
        for p in percents:
            parts.append("  Percentage: " + p)
        for n in numbers:
            if '%' not in n:
                parts.append("  Number: " + n)
    else:
        parts.append("  No quantitative assertions detected")
    parts.append("")

    parts.append("[Verifiability Assessment]")
    has_dates = bool(re.search(r'\b(19|20)\d{2}\b', claim))
    has_proper = bool(re.search(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', claim))
    has_numbers = bool(numbers)
    has_super = bool(re.search(r'\b(most|least|best|worst|first|last|only|largest|smallest)\b', claim, re.I))
    parts.append("  Contains dates: " + ("Yes" if has_dates else "No"))
    parts.append("  Contains proper nouns: " + ("Yes" if has_proper else "No"))
    parts.append("  Contains numbers: " + ("Yes" if has_numbers else "No"))
    parts.append("  Contains superlatives: " + ("Yes" if has_super else "No"))
    parts.append("")

    parts.append("[Verification Status]")
    parts.append("  Accuracy Rating: UNVERIFIED (0/5)")
    parts.append("  Confidence: LOW")
    parts.append("  Reason: Web search unavailable (requests not installed)")
    parts.append("")
    parts.append("[Recommendations]")
    parts.append("  - Install requests library for web-based verification")
    parts.append("  - Manually search authoritative sources for the key terms above")
    parts.append("  - Pay special attention to any quantitative or superlative claims")

    return "\n".join(parts)


def _build_error_report(claim: str, error: str) -> str:
    parts = [
        "=== Fact Check Report ===",
        "",
        "Claim: " + claim,
        "Error during search: " + error,
        "",
        "[Claim Decomposition]",
    ]

    keywords = _extract_keywords(claim)
    parts.append("Key terms: " + ", ".join(keywords))
    parts.append("")
    parts.append("[Verification Status]")
    parts.append("  Accuracy Rating: UNVERIFIED (0/5)")
    parts.append("  Confidence: LOW")
    parts.append("  Reason: Search error - " + error)

    return "\n".join(parts)


def _search_claim(claim: str, max_sources: int) -> list:
    import requests
    results = []
    queries = [claim, '"' + claim + '" evidence', claim + " fact check"]
    for query in queries:
        if len(results) >= max_sources:
            break
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
            for topic in data.get("RelatedTopics", [])[:2]:
                if isinstance(topic, dict) and "Text" in topic and len(results) < max_sources:
                    results.append({"title": topic.get("Text", "")[:80], "snippet": topic["Text"], "url": topic.get("FirstURL", "")})
        except Exception:
            continue
    return results[:max_sources]


def _extract_keywords(text: str) -> list:
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then",
        "once", "and", "but", "or", "nor", "not", "so", "yet", "both",
        "either", "neither", "each", "every", "all", "any", "few", "more",
        "most", "other", "some", "such", "no", "only", "own", "same", "than",
        "too", "very", "just", "because", "if", "when", "where", "how",
        "what", "which", "who", "whom", "this", "that", "these", "those",
        "it", "its", "he", "she", "they", "them", "we", "you", "i", "me",
    }
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    keywords = [w for w in words if w not in stop_words]
    seen = set()
    unique = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return unique


def _assess_relevance(claim: str, snippet: str) -> str:
    claim_kw = set(_extract_keywords(claim))
    snippet_kw = set(_extract_keywords(snippet))
    if not claim_kw:
        return "LOW"
    overlap = len(claim_kw & snippet_kw) / len(claim_kw)
    if overlap >= 0.5:
        return "HIGH"
    elif overlap >= 0.2:
        return "MEDIUM"
    return "LOW"


def _assess_stance(claim: str, text: str) -> str:
    contradiction_words = ["false", "wrong", "incorrect", "myth", "debunked", "disputed", "misleading", "untrue", "fabricat"]
    support_words = ["true", "correct", "confirmed", "verified", "accurate", "established", "proven", "evidence"]
    text_lower = text.lower()
    has_contra = any(w in text_lower for w in contradiction_words)
    has_support = any(w in text_lower for w in support_words)
    if has_contra and not has_support:
        return "contradicting"
    if has_support and not has_contra:
        return "supporting"
    if has_contra and has_support:
        return "neutral"
    relevance = _assess_relevance(claim, text)
    if relevance == "HIGH":
        return "neutral"
    return "neutral"


def _keyword_coverage(keywords: list, search_results: list) -> float:
    if not keywords:
        return 0.0
    all_snippet_text = " ".join(r.get("snippet", "").lower() for r in search_results)
    all_title_text = " ".join(r.get("title", "").lower() for r in search_results)
    all_text = all_snippet_text + " " + all_title_text
    covered = sum(1 for kw in keywords if kw.lower() in all_text)
    return covered / len(keywords)


def _compute_accuracy_score(supporting: int, contradicting: int, neutral: int, keyword_coverage: float) -> int:
    total = supporting + contradicting + neutral
    if total == 0:
        return 3
    ratio = supporting / total
    contra_ratio = contradicting / total
    if contra_ratio > 0.5:
        return 1
    if contra_ratio > 0.3:
        return 2
    if ratio > 0.6 and keyword_coverage > 0.5:
        return 4
    if ratio > 0.6 and keyword_coverage <= 0.5:
        return 3
    if ratio > 0.3:
        return 3
    return 2


def _compute_confidence(supporting: int, contradicting: int, total: int, keyword_coverage: float) -> str:
    if total <= 1:
        return "LOW"
    agreement = max(supporting, contradicting) / total
    if total >= 3 and agreement > 0.6 and keyword_coverage > 0.4:
        return "HIGH"
    if total >= 2 and agreement > 0.4:
        return "MEDIUM"
    return "LOW"


def _score_explanation(score: int) -> str:
    explanations = {
        1: "Completely False - majority of sources contradict the claim",
        2: "Mostly False - significant contradicting evidence found",
        3: "Mixed/Unverified - sources are ambiguous or insufficient",
        4: "Mostly True - majority of sources support the claim",
        5: "Completely True - all sources corroborate the claim",
    }
    return explanations.get(score, "Unknown rating")


def _classify_claim_type(text: str) -> str:
    if re.search(r'\b(is|are|was|were)\b', text, re.I):
        return "Factual assertion"
    if re.search(r'\b(causes?|leads?|results? in|affects?)\b', text, re.I):
        return "Causal claim"
    if re.search(r'\b(all|none|every|no\s+one|always|never)\b', text, re.I):
        return "Universal claim"
    if re.search(r'\b(most|majority|minority|typically|usually)\b', text, re.I):
        return "Statistical/probabilistic claim"
    if re.search(r'\b(should|ought|must|need)\b', text, re.I):
        return "Normative claim"
    return "Descriptive claim"


def register(registry) -> None:
    registry.register(SkillDef(
        name="fact_checker",
        description="Fact checking by cross-referencing multiple web sources.",
        category="research",
        parameters={
            "type": "object",
            "properties": {
                "claim": {
                    "type": "string",
                    "description": "The claim to fact-check",
                },
                "sources": {
                    "type": "integer",
                    "description": "Number of sources to cross-reference (3-5)",
                    "minimum": 3,
                    "maximum": 5,
                },
            },
            "required": ["claim"],
        },
        handler=execute,
        timeout=45,
    ))
