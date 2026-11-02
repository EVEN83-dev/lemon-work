from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


_HIGH_PRIORITY_PATTERNS = [
    "module.json5", "package.json", "build-profile.json5",
    "entryability", "main.ets", "main.ts", "main.py",
    "app.json5", "app.ets", "index.ets",
]

_MID_PRIORITY_PATTERNS = [
    "services/", "service/", "core/",
    "controller", "manager", "handler",
    "orchestrator", "engine",
]

_LOW_PRIORITY_PATTERNS = [
    "components/", "ui/", "views/",
    "styles/", "assets/", "resources/",
    "test/", "tests/", "__tests__",
]

_MAX_KEY_FILES = 10
_CACHE_TTL_SECONDS = 600


@dataclass
class FileReadCacheEntry:
    path: str = ""
    content: str = ""
    timestamp: float = 0.0
    token_count: int = 0


@dataclass
class FilePriority:
    path: str = ""
    priority: int = 0
    category: str = "low"
    reason: str = ""


class SmartFileReader:
    def __init__(self, read_callback: Optional[Callable[[str], str]] = None) -> None:
        self._lock = threading.Lock()
        self._cache: Dict[str, FileReadCacheEntry] = {}
        self._read_callback = read_callback
        self._stats: Dict[str, Any] = {
            "total_reads": 0,
            "cache_hits": 0,
            "skipped_low_priority": 0,
        }

    def set_read_callback(self, callback: Callable[[str], str]) -> None:
        self._read_callback = callback

    def prescan_directory(self, root_path: str) -> List[FilePriority]:
        if not os.path.isdir(root_path):
            return []
        files = self._list_source_files(root_path)
        prioritized = [self._assess_priority(f) for f in files]
        prioritized.sort(key=lambda p: (-p.priority, p.path))
        return prioritized

    def smart_read(self, root_path: str, max_files: int = _MAX_KEY_FILES) -> Dict[str, str]:
        prioritized = self.prescan_directory(root_path)
        key_files = prioritized[:max_files]
        results: Dict[str, str] = {}
        for fp in key_files:
            content = self._read_with_cache(fp.path)
            if content is not None:
                results[fp.path] = content
        return results

    def read_file(self, path: str) -> Optional[str]:
        return self._read_with_cache(path)

    def batch_read(self, paths: List[str]) -> Dict[str, str]:
        results: Dict[str, str] = {}
        for p in paths:
            content = self._read_with_cache(p)
            if content is not None:
                results[p] = content
        return results

    def get_key_files(self, root_path: str, max_files: int = _MAX_KEY_FILES) -> List[str]:
        prioritized = self.prescan_directory(root_path)
        return [fp.path for fp in prioritized[:max_files]]

    def assess_priority(self, path: str) -> FilePriority:
        return self._assess_priority(path)

    def invalidate_cache(self, path: str = "") -> None:
        with self._lock:
            if path:
                self._cache.pop(path, None)
            else:
                self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            stats = dict(self._stats)
            stats["cache_size"] = len(self._cache)
            return stats

    def _read_with_cache(self, path: str) -> Optional[str]:
        with self._lock:
            cached = self._cache.get(path)
            if cached and (time.time() - cached.timestamp) < _CACHE_TTL_SECONDS:
                self._stats["cache_hits"] += 1
                return cached.content

        if self._read_callback:
            try:
                content = self._read_callback(path)
            except Exception:
                return None
        elif os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                return None
        else:
            return None

        with self._lock:
            self._stats["total_reads"] += 1
            self._cache[path] = FileReadCacheEntry(
                path=path,
                content=content,
                timestamp=time.time(),
                token_count=len(content) // 4,
            )
        return content

    def _assess_priority(self, path: str) -> FilePriority:
        normalized = path.replace("\\", "/").lower()
        basename = os.path.basename(path).lower()

        for pattern in _HIGH_PRIORITY_PATTERNS:
            if pattern.lower() in basename or pattern.lower() in normalized:
                return FilePriority(
                    path=path, priority=100, category="high",
                    reason=f"匹配高优先级模式: {pattern}",
                )

        for pattern in _MID_PRIORITY_PATTERNS:
            if pattern.lower() in normalized:
                return FilePriority(
                    path=path, priority=50, category="mid",
                    reason=f"匹配中优先级模式: {pattern}",
                )

        for pattern in _LOW_PRIORITY_PATTERNS:
            if pattern.lower() in normalized:
                return FilePriority(
                    path=path, priority=10, category="low",
                    reason=f"匹配低优先级模式: {pattern}",
                )

        return FilePriority(
            path=path, priority=30, category="default",
            reason="默认优先级",
        )

    @staticmethod
    def _list_source_files(root: str, max_depth: int = 5) -> List[str]:
        result: List[str] = []
        skip_dirs = {".git", "node_modules", "__pycache__", ".hvigor", "build", "oh_modules", ".idea"}
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath.replace(root, "").count(os.sep)
            if depth >= max_depth:
                dirnames.clear()
                continue
            dirnames[:] = [d for d in dirnames if d.lower() not in skip_dirs]
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext in (".ets", ".ts", ".py", ".json", ".json5", ".js", ".md", ".yaml", ".yml", ".toml"):
                    result.append(os.path.join(dirpath, fn))
        return result
