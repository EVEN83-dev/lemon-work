# -*- coding: utf-8 -*-
"""364章 T4.3: 分层记忆 — 短期/长期/语义三层记忆"""

import json
import os
import time
from typing import Dict, List, Optional
from collections import deque


class LayeredMemory:
    def __init__(self, short_term_size: int = 100, long_term_file: str = "",
                 semantic_dim: int = 128):
        self._short_term = deque(maxlen=short_term_size)
        self._long_term: List[Dict] = []
        self._semantic_index: Dict[str, List[float]] = {}
        self._long_term_file = long_term_file or ""
        if self._long_term_file and os.path.isfile(self._long_term_file):
            self._load_long_term()

    def add_short_term(self, key: str, value: object, metadata: Optional[Dict] = None):
        self._short_term.append({
            "key": key, "value": value, "metadata": metadata or {},
            "timestamp": time.time(),
        })

    def get_short_term(self, key: str) -> Optional[object]:
        for item in reversed(self._short_term):
            if item["key"] == key:
                return item["value"]
        return None

    def list_short_term(self, limit: int = 20) -> List[Dict]:
        items = list(self._short_term)
        return items[-limit:]

    def consolidate(self, min_access: int = 2) -> int:
        promoted = 0
        access_counts: Dict[str, int] = {}
        for item in self._short_term:
            k = item["key"]
            access_counts[k] = access_counts.get(k, 0) + 1

        for item in self._short_term:
            if access_counts.get(item["key"], 0) >= min_access:
                if not any(e["key"] == item["key"] for e in self._long_term):
                    self._long_term.append(dict(item))
                    promoted += 1

        if promoted > 0 and self._long_term_file:
            self._save_long_term()
        return promoted

    def get_long_term(self, key: str) -> Optional[object]:
        for item in self._long_term:
            if item["key"] == key:
                return item["value"]
        return None

    def search_long_term(self, query: str) -> List[Dict]:
        results = []
        q = query.lower()
        for item in self._long_term:
            val = str(item.get("value", "")).lower()
            key = item.get("key", "").lower()
            if q in val or q in key:
                results.append(item)
        return results[:20]

    def add_semantic(self, key: str, embedding: List[float]):
        self._semantic_index[key] = embedding

    def search_semantic(self, query_embedding: List[float], top_k: int = 5) -> List[Dict]:
        if not self._semantic_index:
            return []
        scored = []
        for key, emb in self._semantic_index.items():
            sim = self._cosine_sim(query_embedding, emb)
            scored.append({"key": key, "similarity": sim})
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]

    def stats(self) -> Dict:
        return {
            "short_term": len(self._short_term),
            "long_term": len(self._long_term),
            "semantic": len(self._semantic_index),
        }

    @staticmethod
    def _cosine_sim(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _save_long_term(self):
        with open(self._long_term_file, "w", encoding="utf-8") as f:
            json.dump(self._long_term, f, ensure_ascii=False, indent=2)

    def _load_long_term(self):
        with open(self._long_term_file, "r", encoding="utf-8") as f:
            self._long_term = json.load(f)
