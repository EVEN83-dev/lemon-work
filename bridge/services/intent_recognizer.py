"""
Intent Recognizer Service

4-stage pipeline: correlation -> domain -> function -> skill match.
Falls back to CommandParser regex rules when LLM unavailable.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from bridge.services.domain_knowledge import DomainKnowledgeService
from bridge.services.command_parser import CommandParser, INTENT_RULES

logger = logging.getLogger("lemon_bridge.intent")


class IntentRecognizer:
    def __init__(self, domain_service: DomainKnowledgeService | None = None):
        self._domains = domain_service or DomainKnowledgeService()
        self._command_parser = CommandParser()

    def recognize(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        if not text:
            return {"isRelevant": False, "domain": "", "functions": [], "skillId": "", "confidence": 0.0}

        if text.startswith("/"):
            parsed = self._command_parser.parse(text)
            return {
                "isRelevant": True,
                "domain": "system",
                "functions": [parsed.command_name],
                "skillId": parsed.skill_id,
                "confidence": 1.0,
                "commandType": parsed.command_type.value,
            }

        domain = self._domains.match_domain(text)
        is_relevant = len(domain) > 0

        parsed = self._command_parser.parse(text)
        skill_id = parsed.skill_id if parsed.command_type.value == "skill" else ""

        functions = self._extract_functions(text)

        confidence = 0.5
        if skill_id:
            confidence = 0.8
        if domain and skill_id:
            confidence = 0.9

        return {
            "isRelevant": is_relevant or len(skill_id) > 0,
            "domain": domain,
            "functions": functions,
            "skillId": skill_id,
            "confidence": confidence,
        }

    def _extract_functions(self, text: str) -> List[str]:
        function_keywords: Dict[str, List[str]] = {
            "query": ["\u67e5\u8be2", "\u67e5\u770b", "\u641c\u7d22", "\u627e"],
            "create": ["\u521b\u5efa", "\u65b0\u5efa", "\u751f\u6210", "\u5199"],
            "delete": ["\u5220\u9664", "\u79fb\u9664", "\u6e05\u9664"],
            "update": ["\u4fee\u6539", "\u66f4\u65b0", "\u7f16\u8f91"],
            "start": ["\u542f\u52a8", "\u5f00\u59cb", "\u8fd0\u884c"],
            "stop": ["\u505c\u6b62", "\u6682\u505c", "\u7ed3\u675f"],
            "analyze": ["\u5206\u6790", "\u5ba1\u67e5", "\u68c0\u67e5"],
        }
        result: List[str] = []
        for func, keywords in function_keywords.items():
            for kw in keywords:
                if kw in text:
                    result.append(func)
                    break
        return result
