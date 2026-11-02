"""
C2: Local Embedder Service — TF-IDF first, embedding fallback.

Real TF-IDF vectorization with term-document frequency counting,
cosine similarity, and a no-model semantic search path.
"""
from __future__ import annotations

import hashlib
import math
import re
import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class EmbeddingVector:
    values: List[float] = field(default_factory=list)
    dimension: int = 0
    model: str = "tfidf-v1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "model": self.model,
            "valuesPreview": self.values[:4],
        }


@dataclass
class SearchResult:
    id: str
    score: float
    content: str

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "score": self.score, "content": self.content}


_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "and", "but", "or", "nor", "not", "so", "yet", "both",
    "either", "neither", "each", "every", "all", "any", "few", "more",
    "most", "other", "some", "such", "no", "only", "own", "same", "than",
    "too", "very", "just", "because", "if", "when", "while", "where",
    "how", "what", "which", "who", "whom", "this", "that", "these", "those",
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you",
    "your", "yours", "yourself", "yourselves", "he", "him", "his",
    "himself", "she", "her", "hers", "herself", "it", "its", "itself",
    "they", "them", "their", "theirs", "themselves",
    "de", "la", "le", "les", "un", "une", "des", "du", "et",
})


def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r'[a-zA-Z\u4e00-\u9fff][a-zA-Z0-9_\-\u4e00-\u9fff]*', text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def _tokenize_cjk(text: str) -> List[str]:
    tokens = []
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff':
            tokens.append(ch)
    cjk_bigrams = []
    for i in range(len(tokens) - 1):
        cjk_bigrams.append(tokens[i] + tokens[i + 1])
    return cjk_bigrams + tokens


class TFIDFIndex:
    def __init__(self, max_features: int = 8000):
        self._doc_freq: Counter = Counter()
        self._doc_count: int = 0
        self._vocab: Dict[str, int] = {}
        self._idf: Dict[str, float] = {}
        self._max_features = max_features

    def add_document(self, doc_id: str, text: str) -> None:
        tokens = _tokenize(text) + _tokenize_cjk(text)
        seen = set(tokens)
        for t in seen:
            self._doc_freq[t] += 1
        self._doc_count += 1
        self._rebuild_idf()

    def add_documents(self, docs: Dict[str, str]) -> None:
        for doc_id, text in docs.items():
            tokens = set(_tokenize(text) + _tokenize_cjk(text))
            for t in tokens:
                self._doc_freq[t] += 1
            self._doc_count += 1
        self._rebuild_idf()

    def vectorize(self, text: str) -> List[float]:
        tokens = _tokenize(text) + _tokenize_cjk(text)
        tf = Counter(tokens)
        total = len(tokens) if tokens else 1
        vec: List[float] = []
        sorted_vocab = sorted(self._idf.keys(), key=lambda k: self._idf.get(k, 0), reverse=True)
        for term in sorted_vocab[:self._max_features]:
            tf_val = tf.get(term, 0) / total
            idf_val = self._idf.get(term, 0.0)
            vec.append(tf_val * idf_val)
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def _rebuild_idf(self) -> None:
        if self._doc_count == 0:
            return
        for term, df in self._doc_freq.most_common(self._max_features):
            self._idf[term] = math.log((1 + self._doc_count) / (1 + df)) + 1.0


class LocalEmbedderService:
    DIMENSION: int = 32

    def __init__(self):
        self._tfidf = TFIDFIndex()
        self._embedding_available: bool = False
        self._embedding_model: Optional[Any] = None
        self._try_init_embedding()

    def _try_init_embedding(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            self._embedding_available = True
        except Exception:
            self._embedding_available = False

    def embed(self, text: str) -> EmbeddingVector:
        if self._embedding_available and self._embedding_model is not None:
            try:
                vec = self._embedding_model.encode(text).tolist()
                return EmbeddingVector(values=vec, dimension=len(vec), model="sentence-transformer")
            except Exception:
                pass
        values = self._hash_embed(text)
        return EmbeddingVector(values=values, dimension=self.DIMENSION, model="stub-v1")

    def embed_batch(self, texts: List[str]) -> List[EmbeddingVector]:
        if self._embedding_available and self._embedding_model is not None:
            try:
                vecs = self._embedding_model.encode(texts).tolist()
                return [
                    EmbeddingVector(values=v, dimension=len(v), model="sentence-transformer")
                    for v in vecs
                ]
            except Exception:
                pass
        return [self.embed(t) for t in texts]

    def similarity(self, v1: EmbeddingVector, v2: EmbeddingVector) -> float:
        if v1.dimension != v2.dimension or not v1.values or not v2.values:
            return 0.0
        dot = 0.0
        n1 = 0.0
        n2 = 0.0
        for i in range(min(len(v1.values), len(v2.values))):
            dot += v1.values[i] * v2.values[i]
            n1 += v1.values[i] ** 2
            n2 += v2.values[i] ** 2
        if n1 == 0.0 or n2 == 0.0:
            return 0.0
        return dot / (math.sqrt(n1) * math.sqrt(n2))

    def search(self, query: str, candidates: Dict[str, str], top_k: int = 5) -> List[SearchResult]:
        self._tfidf.add_documents(candidates)
        query_vec = self._tfidf.vectorize(query)
        results: List[Tuple[float, str, str]] = []
        for cid, content in candidates.items():
            doc_vec = self._tfidf.vectorize(content)
            score = self._cosine_raw(query_vec, doc_vec)
            if score > 0:
                results.append((score, cid, content))
        results.sort(key=lambda x: x[0], reverse=True)
        return [SearchResult(id=cid, score=score, content=content)
                for score, cid, content in results[:top_k]]

    def search_with_vectors(
        self,
        query_vec: List[float],
        candidate_vecs: Dict[str, List[float]],
        candidate_contents: Dict[str, str],
        top_k: int = 5,
    ) -> List[SearchResult]:
        results: List[Tuple[float, str, str]] = []
        for cid, cvec in candidate_vecs.items():
            score = self._cosine_raw(query_vec, cvec)
            if score > 0:
                results.append((score, cid, candidate_contents.get(cid, "")))
        results.sort(key=lambda x: x[0], reverse=True)
        return [SearchResult(id=cid, score=score, content=content)
                for score, cid, content in results[:top_k]]

    @staticmethod
    def _cosine_raw(v1: List[float], v2: List[float]) -> float:
        min_len = min(len(v1), len(v2))
        if min_len == 0:
            return 0.0
        dot = sum(v1[i] * v2[i] for i in range(min_len))
        n1 = math.sqrt(sum(v * v for v in v1[:min_len]))
        n2 = math.sqrt(sum(v * v for v in v2[:min_len]))
        if n1 == 0.0 or n2 == 0.0:
            return 0.0
        return dot / (n1 * n2)

    def _hash_embed(self, text: str) -> List[float]:
        values: List[float] = []
        for i in range(self.DIMENSION):
            chunk = f"{text}:{i}".encode("utf-8")
            digest = hashlib.sha256(chunk).digest()
            val = struct.unpack(">f", digest[:4])[0]
            val = (val % 2.0) - 1.0
            values.append(val)
        norm = math.sqrt(sum(v ** 2 for v in values))
        if norm > 0:
            values = [v / norm for v in values]
        return values
