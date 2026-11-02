# -*- coding: utf-8 -*-
"""Knowledge base / RAG system - retrieval augmented generation"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from collections import defaultdict
import time
import hashlib


@dataclass
class KnowledgeEntry:
    entry_id: str
    content: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    access_count: int = 0
    relevance_score: float = 0.0


@dataclass
class SearchResult:
    entry_id: str
    content: str
    score: float
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class KnowledgeBase:

    def __init__(self, max_entries: int = 10000):
        self._entries: Dict[str, KnowledgeEntry] = {}
        self._inverted_index: Dict[str, List[str]] = defaultdict(list)
        self._metadata_index: Dict[str, List[str]] = defaultdict(list)
        self._max_entries = max_entries
        self._embedding_dim: int = 768
        self._stats = {
            'total_queries': 0,
            'total_entries_added': 0,
            'avg_search_time': 0.0,
        }

    def add_entry(self, content: str, source: str, metadata: Dict = None) -> str:
        entry_id = hashlib.md5(f'{content}_{time.time()}'.encode()).hexdigest()[:12]
        entry = KnowledgeEntry(
            entry_id=entry_id, content=content, source=source,
            metadata=metadata or {}, created_at=time.time(), updated_at=time.time(),
        )
        self._entries[entry_id] = entry
        self._update_inverted_index(entry_id, content)
        if metadata:
            for key, value in metadata.items():
                self._metadata_index[f'{key}:{value}'].append(entry_id)
        self._stats['total_entries_added'] += 1
        if len(self._entries) > self._max_entries:
            self._evict_oldest()
        return entry_id

    def search(self, query: str, top_k: int = 5, filters: Dict = None) -> List[SearchResult]:
        start_time = time.time()
        self._stats['total_queries'] += 1

        keyword_scores = self._keyword_search(query)

        filtered_ids: set = set()
        if filters:
            for key, value in filters.items():
                matched = self._metadata_index.get(f'{key}:{value}', [])
                if not matched:
                    return []
                if not filtered_ids:
                    filtered_ids = set(matched)
                else:
                    filtered_ids &= set(matched)
        else:
            filtered_ids = set(self._entries.keys())

        results = []
        for entry_id in filtered_ids:
            entry = self._entries.get(entry_id)
            if entry is None:
                continue
            keyword_score = keyword_scores.get(entry_id, 0)
            content_score = 1.0 if query.lower() in entry.content.lower() else 0.0
            popularity_score = min(1.0, entry.access_count / 100.0)
            final_score = keyword_score * 0.5 + content_score * 0.3 + popularity_score * 0.2
            if final_score > 0:
                results.append(SearchResult(
                    entry_id=entry_id, content=entry.content,
                    score=final_score, source=entry.source, metadata=entry.metadata,
                ))

        results.sort(key=lambda x: x.score, reverse=True)
        top_results = results[:top_k]

        for r in top_results:
            entry = self._entries.get(r.entry_id)
            if entry:
                entry.access_count += 1
                entry.relevance_score = r.score

        elapsed = time.time() - start_time
        self._stats['avg_search_time'] = self._stats['avg_search_time'] * 0.9 + elapsed * 0.1
        return top_results

    def _keyword_search(self, query: str) -> Dict[str, float]:
        scores: Dict[str, float] = defaultdict(float)
        query_words = query.lower().split()
        for word in query_words:
            if word in self._inverted_index:
                for entry_id in self._inverted_index[word]:
                    scores[entry_id] += 1.0
        if scores:
            max_score = max(scores.values())
            scores = {k: v / max_score for k, v in scores.items()}
        return dict(scores)

    def _update_inverted_index(self, entry_id: str, content: str):
        words = content.lower().split()
        for word in set(words):
            if len(word) > 2:
                self._inverted_index[word].append(entry_id)

    def _evict_oldest(self):
        if not self._entries:
            return
        oldest_id = min(self._entries, key=lambda k: self._entries[k].created_at)
        self.remove_entry(oldest_id)

    def remove_entry(self, entry_id: str) -> bool:
        entry = self._entries.pop(entry_id, None)
        if entry is None:
            return False
        for word in entry.content.lower().split():
            if len(word) > 2 and word in self._inverted_index:
                idx_list = self._inverted_index[word]
                if entry_id in idx_list:
                    idx_list.remove(entry_id)
        return True

    def get_stats(self) -> Dict:
        return {
            'total_entries': len(self._entries),
            'total_queries': self._stats['total_queries'],
            'total_added': self._stats['total_entries_added'],
            'avg_search_time': f"{self._stats['avg_search_time']:.4f}s",
            'index_size': len(self._inverted_index),
        }


_kb: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb
