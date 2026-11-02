"""
B-004: Response Cache - simple in-memory cache for AI responses.
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class ResponseCache:
    def __init__(self, max_size: int = 200, ttl_seconds: int = 3600):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._cache: Dict[str, Tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _make_key(self, prompt: str, model: str, temperature: float = 0.0) -> str:
        raw = f"{model}:{temperature}:{prompt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def get(self, prompt: str, model: str, temperature: float = 0.0) -> Optional[str]:
        key = self._make_key(prompt, model, temperature)
        with self._lock:
            if key in self._cache:
                content, ts = self._cache[key]
                if time.time() - ts < self._ttl:
                    return content
                del self._cache[key]
        return None

    def put(self, prompt: str, model: str, content: str,
            temperature: float = 0.0) -> None:
        key = self._make_key(prompt, model, temperature)
        with self._lock:
            if len(self._cache) >= self._max_size:
                oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[key] = (content, time.time())

    def invalidate(self, prompt: str, model: str, temperature: float = 0.0) -> None:
        key = self._make_key(prompt, model, temperature)
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)
