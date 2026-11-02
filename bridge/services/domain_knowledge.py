"""
Domain Knowledge Service

Defines vertical domains and their associated skills/tags.
Used by IntentRecognizer for domain classification.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("lemon_bridge.domain")


DOMAINS: List[Dict[str, Any]] = [
    {
        "id": "food",
        "label": "\u7f8e\u98df",
        "tags": ["\u70b9\u5355", "\u8ba2\u5355", "\u63a8\u8350", "\u9910\u5385", "\u83dc\u54c1"],
        "skills": ["web_researcher"],
    },
    {
        "id": "travel",
        "label": "\u65c5\u6e38",
        "tags": ["\u884c\u7a0b", "\u8ba2\u7968", "\u9152\u5e97", "\u666f\u70b9", "\u51fa\u884c"],
        "skills": ["web_researcher"],
    },
    {
        "id": "shopping",
        "label": "\u8d2d\u7269",
        "tags": ["\u5546\u54c1", "\u8d2d\u7269\u8f66", "\u8ba2\u5355", "\u4ef7\u683c", "\u6bd4\u4ef7"],
        "skills": ["web_researcher"],
    },
    {
        "id": "education",
        "label": "\u6559\u80b2",
        "tags": ["\u8bfe\u7a0b", "\u4e60\u9898", "\u8fdb\u5ea6", "\u5b66\u4e60", "\u8003\u8bd5"],
        "skills": ["math_solver", "code_reviewer"],
    },
    {
        "id": "tools",
        "label": "\u5de5\u5177",
        "tags": ["\u8ba1\u7b97", "\u8f6c\u6362", "\u641c\u7d22", "\u5206\u6790", "\u5904\u7406"],
        "skills": ["math_solver", "math_plotter", "code_reviewer", "test_generator"],
    },
    {
        "id": "system",
        "label": "\u7cfb\u7edf",
        "tags": ["\u8bbe\u7f6e", "\u6743\u9650", "\u6587\u4ef6", "\u901a\u77e5", "\u5f55\u97f3", "\u5929\u6c14", "\u65e5\u5386", "\u756a\u8304\u949f", "\u8bb0\u5fc6"],
        "skills": ["pomodoro_skill", "weather_service", "calendar_service", "file_service", "audio_service"],
    },
    {
        "id": "code",
        "label": "\u4ee3\u7801",
        "tags": ["\u7f16\u7a0b", "\u4ee3\u7801", "\u51fd\u6570", "\u7b97\u6cd5", "\u8c03\u8bd5", "\u5ba1\u67e5", "\u751f\u6210"],
        "skills": ["code_reviewer", "code_formatter", "test_generator", "code_graph"],
    },
    {
        "id": "office",
        "label": "\u529e\u516c",
        "tags": ["\u6587\u6863", "\u5468\u62a5", "\u65e5\u62a5", "\u62a5\u544a", "PPT", "Excel", "Word", "PDF"],
        "skills": ["office_generator", "pdf_reader"],
    },
]


class DomainKnowledgeService:
    def __init__(self, domains: List[Dict[str, Any]] | None = None):
        self._domains = domains or DOMAINS

    def list_domains(self) -> Dict[str, Any]:
        return {
            "domains": [
                {"id": d["id"], "label": d["label"], "tags": d["tags"]}
                for d in self._domains
            ]
        }

    def get_domain(self, domain_id: str) -> Dict[str, Any] | None:
        for d in self._domains:
            if d["id"] == domain_id:
                return d
        return None

    def get_skills_for_domain(self, domain_id: str) -> List[str]:
        domain = self.get_domain(domain_id)
        if domain:
            return domain.get("skills", [])
        return []

    def match_domain(self, text: str) -> str:
        text_lower = text.lower()
        best_domain = ""
        best_count = 0
        for d in self._domains:
            count = 0
            for tag in d["tags"]:
                if tag in text_lower:
                    count += 1
            if count > best_count:
                best_count = count
                best_domain = d["id"]
        return best_domain
