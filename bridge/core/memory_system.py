from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple


class MemoryLayer:
    SESSION = "session"
    USER = "user"
    PROJECT = "project"
    KNOWLEDGE = "knowledge"


@dataclass
class MemoryEntry:
    entry_id: str
    layer: str
    key: str
    value: Any
    metadata: Optional[dict] = None
    created_at: float = 0.0
    accessed_at: float = 0.0
    access_count: int = 0
    expires_at: float = 0.0
    importance: float = 0.5
    is_starred: bool = False
    is_archived: bool = False
    vector: Optional[List[float]] = None

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.accessed_at == 0.0:
            self.accessed_at = time.time()
        if self.metadata is None:
            self.metadata = {}

    def eviction_score(self) -> float:
        if self.is_starred:
            return 0.0
        recency = max(0.0, 1.0 - (time.time() - self.accessed_at) / 86400.0)
        frequency = min(self.access_count / 10.0, 1.0)
        return 1.0 - (recency * 0.5 + frequency * 0.3 + self.importance * 0.2)


_EMBEDDER_INSTANCE: Optional[Any] = None
_EMBEDDER_AVAILABLE: Optional[bool] = None


def _get_embedder():
    global _EMBEDDER_INSTANCE, _EMBEDDER_AVAILABLE
    if _EMBEDDER_AVAILABLE is not None:
        return _EMBEDDER_INSTANCE if _EMBEDDER_AVAILABLE else None
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from shared.vector_database import VectorDatabaseManager
        _EMBEDDER_INSTANCE = VectorDatabaseManager(embedding_type="tfidf")
        _EMBEDDER_AVAILABLE = True
    except Exception:
        try:
            from bridge.services.local_embedder import LocalEmbedderService
            _EMBEDDER_INSTANCE = LocalEmbedderService()
            _EMBEDDER_AVAILABLE = True
        except Exception:
            _EMBEDDER_AVAILABLE = False
    return _EMBEDDER_INSTANCE if _EMBEDDER_AVAILABLE else None


def _embed_text(text: str) -> Optional[List[float]]:
    embedder = _get_embedder()
    if embedder is None:
        return None
    try:
        if hasattr(embedder, 'embedding_model'):
            return embedder.embedding_model.embed(text)
        elif hasattr(embedder, 'embed'):
            vec = embedder.embed(text)
            if hasattr(vec, 'values'):
                return vec.values
            return vec
    except Exception:
        pass
    return None


def _cosine_sim(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2:
        return 0.0
    min_len = min(len(v1), len(v2))
    dot = sum(v1[i] * v2[i] for i in range(min_len))
    n1 = math.sqrt(sum(x * x for x in v1[:min_len]))
    n2 = math.sqrt(sum(x * x for x in v2[:min_len]))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (n1 * n2)


import sys


class SessionMemory:
    def __init__(self, session_id: str, max_entries: int = 200):
        self.session_id = session_id
        self.max_entries = max_entries
        self._entries: OrderedDict[str, MemoryEntry] = OrderedDict()
        self._lock = Lock()

    def store(self, key: str, value: Any, metadata: Optional[dict] = None) -> str:
        entry_id = str(uuid.uuid4())
        vec = _embed_text(key + " " + str(value))
        entry = MemoryEntry(
            entry_id=entry_id,
            layer=MemoryLayer.SESSION,
            key=key,
            value=value,
            metadata=metadata,
            vector=vec,
        )
        with self._lock:
            if key in self._entries:
                del self._entries[key]
            self._entries[key] = entry
            if len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return entry_id

    def retrieve(self, key: str) -> Optional[MemoryEntry]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.accessed_at = time.time()
                entry.access_count += 1
            return entry

    def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        query_vec = _embed_text(query)
        if query_vec is not None:
            scored: List[Tuple[float, MemoryEntry]] = []
            with self._lock:
                for entry in self._entries.values():
                    if entry.vector is not None:
                        sim = _cosine_sim(query_vec, entry.vector)
                        if sim > 0:
                            scored.append((sim, entry))
            scored.sort(key=lambda x: x[0], reverse=True)
            if scored:
                return [entry for _, entry in scored[:limit]]
        keywords = query.lower().split()
        results: List[Tuple[float, MemoryEntry]] = []
        with self._lock:
            for entry in self._entries.values():
                text = (entry.key + " " + str(entry.value)).lower()
                score = sum(1 for kw in keywords if kw in text)
                if score > 0:
                    results.append((score, entry))
        results.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in results[:limit]]

    def get_context_window(self, max_tokens: int = 4000) -> List[MemoryEntry]:
        result: List[MemoryEntry] = []
        total = 0
        with self._lock:
            for entry in reversed(list(self._entries.values())):
                tokens = self._estimate_tokens(entry.value)
                if total + tokens > max_tokens:
                    break
                result.append(entry)
                total += tokens
        result.reverse()
        return result

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def _estimate_tokens(self, value: Any) -> int:
        return len(str(value)) // 3

    def _all_entries(self) -> List[MemoryEntry]:
        with self._lock:
            return list(self._entries.values())

    def _remove_entry(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)


class UserMemory:
    def __init__(self, user_id: str, storage_dir: str = ""):
        self.user_id = user_id
        if not storage_dir:
            storage_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "memory", "users")
        self.storage_dir = os.path.expanduser(storage_dir)
        self._entries: Dict[str, MemoryEntry] = {}
        self._lock = Lock()

    @property
    def _file_path(self) -> str:
        return os.path.join(self.storage_dir, self.user_id, "memory.json")

    def store(self, key: str, value: Any, metadata: Optional[dict] = None) -> str:
        entry_id = str(uuid.uuid4())
        vec = _embed_text(key + " " + str(value))
        entry = MemoryEntry(
            entry_id=entry_id,
            layer=MemoryLayer.USER,
            key=key,
            value=value,
            metadata=metadata,
            vector=vec,
        )
        with self._lock:
            self._entries[key] = entry
        return entry_id

    def retrieve(self, key: str) -> Optional[MemoryEntry]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.accessed_at = time.time()
                entry.access_count += 1
            return entry

    def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        query_vec = _embed_text(query)
        if query_vec is not None:
            scored: List[Tuple[float, MemoryEntry]] = []
            with self._lock:
                for entry in self._entries.values():
                    if entry.vector is not None:
                        sim = _cosine_sim(query_vec, entry.vector)
                        if sim > 0:
                            scored.append((sim, entry))
            scored.sort(key=lambda x: x[0], reverse=True)
            if scored:
                return [entry for _, entry in scored[:limit]]
        keywords = query.lower().split()
        results: List[Tuple[float, MemoryEntry]] = []
        with self._lock:
            for entry in self._entries.values():
                text = (entry.key + " " + str(entry.value)).lower()
                score = sum(1 for kw in keywords if kw in text)
                if score > 0:
                    results.append((score, entry))
        results.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in results[:limit]]

    def get_preferences(self) -> dict:
        result = {}
        with self._lock:
            for key, entry in self._entries.items():
                tags = entry.metadata.get("tags", []) if entry.metadata else []
                if "preference" in tags:
                    result[key] = entry
        return result

    def get_habits(self) -> dict:
        result = {}
        with self._lock:
            for key, entry in self._entries.items():
                tags = entry.metadata.get("tags", []) if entry.metadata else []
                if "habit" in tags:
                    result[key] = entry
        return result

    def get_stats(self) -> dict:
        result = {}
        with self._lock:
            for key, entry in self._entries.items():
                tags = entry.metadata.get("tags", []) if entry.metadata else []
                if "stat" in tags:
                    result[key] = entry
        return result

    def save(self) -> bool:
        try:
            file_path = self._file_path
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with self._lock:
                data = []
                for entry in self._entries.values():
                    if not entry.is_archived:
                        d = asdict(entry)
                        data.append(d)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load(self) -> bool:
        try:
            file_path = self._file_path
            if not os.path.exists(file_path):
                return False
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._entries.clear()
                for d in data:
                    d.pop("is_starred", None)
                    d.pop("is_archived", None)
                    entry = MemoryEntry(**d)
                    self._entries[entry.key] = entry
            return True
        except Exception:
            return False


class ProjectMemory:
    def __init__(self, project_path: str, storage_dir: str = ""):
        self.project_path = project_path
        if not storage_dir:
            storage_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "memory", "projects")
        self.storage_dir = os.path.expanduser(storage_dir)
        self._entries: Dict[str, MemoryEntry] = {}
        self._lock = Lock()

    @property
    def _project_hash(self) -> str:
        return hashlib.md5(self.project_path.encode("utf-8")).hexdigest()

    @property
    def _file_path(self) -> str:
        return os.path.join(self.storage_dir, self._project_hash, "memory.json")

    def store(self, key: str, value: Any, metadata: Optional[dict] = None) -> str:
        entry_id = str(uuid.uuid4())
        vec = _embed_text(key + " " + str(value))
        entry = MemoryEntry(
            entry_id=entry_id,
            layer=MemoryLayer.PROJECT,
            key=key,
            value=value,
            metadata=metadata,
            vector=vec,
        )
        with self._lock:
            self._entries[key] = entry
        return entry_id

    def retrieve(self, key: str) -> Optional[MemoryEntry]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.accessed_at = time.time()
                entry.access_count += 1
            return entry

    def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        query_vec = _embed_text(query)
        if query_vec is not None:
            scored: List[Tuple[float, MemoryEntry]] = []
            with self._lock:
                for entry in self._entries.values():
                    if entry.vector is not None:
                        sim = _cosine_sim(query_vec, entry.vector)
                        if sim > 0:
                            scored.append((sim, entry))
            scored.sort(key=lambda x: x[0], reverse=True)
            if scored:
                return [entry for _, entry in scored[:limit]]
        keywords = query.lower().split()
        results: List[Tuple[float, MemoryEntry]] = []
        with self._lock:
            for entry in self._entries.values():
                text = (entry.key + " " + str(entry.value)).lower()
                score = sum(1 for kw in keywords if kw in text)
                if score > 0:
                    results.append((score, entry))
        results.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in results[:limit]]

    def get_project_context(self) -> dict:
        result = {}
        with self._lock:
            for key, entry in self._entries.items():
                tags = entry.metadata.get("tags", []) if entry.metadata else []
                if "project_context" in tags or key.startswith("project:"):
                    result[key] = entry
        return result

    def index_file(self, file_path: str, content: str) -> str:
        key = "file:" + file_path
        metadata = {"tags": ["indexed_file"], "source": file_path}
        return self.store(key, content, metadata)

    def get_file_index(self) -> List[MemoryEntry]:
        results = []
        with self._lock:
            for entry in self._entries.values():
                if entry.key.startswith("file:"):
                    results.append(entry)
        return results

    def save(self) -> bool:
        try:
            file_path = self._file_path
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with self._lock:
                data = [asdict(entry) for entry in self._entries.values() if not entry.is_archived]
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load(self) -> bool:
        try:
            file_path = self._file_path
            if not os.path.exists(file_path):
                return False
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._entries.clear()
                for d in data:
                    d.pop("is_starred", None)
                    d.pop("is_archived", None)
                    entry = MemoryEntry(**d)
                    self._entries[entry.key] = entry
            return True
        except Exception:
            return False


class KnowledgeMemory:
    def __init__(self, storage_dir: str = ""):
        if not storage_dir:
            storage_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "data")
        self.storage_dir = os.path.expanduser(storage_dir)
        self._db_path = os.path.join(self.storage_dir, "knowledge.db")
        self._lock = Lock()
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(self.storage_dir, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                importance REAL DEFAULT 0.5,
                access_count INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0,
                accessed_at REAL DEFAULT 0,
                is_starred INTEGER DEFAULT 0,
                is_archived INTEGER DEFAULT 0,
                source TEXT DEFAULT '',
                vector BLOB DEFAULT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_key ON knowledge(key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_importance ON knowledge(importance)")
        conn.commit()
        conn.close()

    def store(self, key: str, content: str, category: str = "",
              tags: Optional[List[str]] = None, importance: float = 0.5,
              source: str = "") -> str:
        entry_id = uuid.uuid4().hex[:16]
        now = time.time()
        vec = _embed_text(key + " " + content)
        vec_blob = json.dumps(vec) if vec else None
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO knowledge (id, key, content, category, tags, importance,
                    access_count, created_at, accessed_at, is_starred, is_archived, source, vector)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry_id, key, content, category,
                json.dumps(tags or [], ensure_ascii=False),
                importance, 0, now, now, 0, 0, source, vec_blob,
            ))
            conn.commit()
            conn.close()
        return entry_id

    def retrieve(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT * FROM knowledge WHERE key = ? AND is_archived = 0 ORDER BY importance DESC LIMIT 1", (key,))
            row = c.fetchone()
            if row:
                now = time.time()
                c.execute("UPDATE knowledge SET access_count = access_count + 1, accessed_at = ? WHERE id = ?", (now, row[0]))
                conn.commit()
                conn.close()
                return self._row_to_dict(row)
            conn.close()
            return None

    def search(self, query: str, category: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        query_vec = _embed_text(query)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            q = "SELECT * FROM knowledge WHERE is_archived = 0"
            params: List[Any] = []
            if category:
                q += " AND category = ?"
                params.append(category)
            q += " ORDER BY importance DESC, accessed_at DESC LIMIT ?"
            params.append(limit * 3)
            c.execute(q, params)
            rows = c.fetchall()
            conn.close()
        if query_vec is not None:
            scored: List[Tuple[float, Dict[str, Any]]] = []
            for row in rows:
                entry = self._row_to_dict(row)
                text = entry["key"] + " " + entry["content"]
                entry_vec = _embed_text(text)
                if entry_vec is not None:
                    sim = _cosine_sim(query_vec, entry_vec)
                    scored.append((sim, entry))
            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                return [e for _, e in scored[:limit]]
        keywords = query.lower().split()
        fallback: List[Tuple[float, Dict[str, Any]]] = []
        for row in rows:
            entry = self._row_to_dict(row)
            text = (entry["key"] + " " + entry["content"] + " " + " ".join(entry.get("tags", []))).lower()
            score = sum(text.count(kw) for kw in keywords) + entry.get("importance", 0.5)
            fallback.append((score, entry))
        fallback.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in fallback[:limit]]

    def star(self, entry_id: str) -> bool:
        return self._set_flag(entry_id, "is_starred", 1)

    def unstar(self, entry_id: str) -> bool:
        return self._set_flag(entry_id, "is_starred", 0)

    def archive(self, entry_id: str) -> bool:
        return self._set_flag(entry_id, "is_archived", 1)

    def restore(self, entry_id: str) -> bool:
        return self._set_flag(entry_id, "is_archived", 0)

    def auto_evict(self, max_entries: int = 10000) -> int:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM knowledge WHERE is_archived = 0")
            count = c.fetchone()[0]
            if count <= max_entries:
                conn.close()
                return 0
            excess = count - max_entries
            c.execute("""
                DELETE FROM knowledge WHERE is_archived = 0 AND is_starred = 0
                AND id IN (
                    SELECT id FROM knowledge WHERE is_archived = 0 AND is_starred = 0
                    ORDER BY importance ASC, accessed_at ASC LIMIT ?
                )
            """, (excess,))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            return deleted if deleted is not None else 0

    def _set_flag(self, entry_id: str, flag: str, value: int) -> bool:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("UPDATE knowledge SET " + flag + " = ? WHERE id = ?", (value, entry_id))
            affected = c.rowcount
            conn.commit()
            conn.close()
            return affected > 0

    def _row_to_dict(self, row: tuple) -> Dict[str, Any]:
        return {
            "id": row[0], "key": row[1], "content": row[2],
            "category": row[3], "tags": json.loads(row[4]) if row[4] else [],
            "importance": row[5], "access_count": row[6],
            "created_at": row[7], "accessed_at": row[8],
            "is_starred": bool(row[9]), "is_archived": bool(row[10]),
            "source": row[11],
        }


def _relevance_score(entry: MemoryEntry, query: str) -> float:
    keywords = query.lower().split()
    if not keywords:
        return 0.0
    text = (entry.key + " " + str(entry.value)).lower()
    return sum(text.count(kw) for kw in keywords)


class MemoryDistiller:
    _DECISION_PATTERNS = [
        re.compile(r"(决定|确认|批准|拒绝|创建|删除|修复|decided|confirmed|fixed|approved|rejected)", re.IGNORECASE),
    ]
    _API_PATTERNS = [
        re.compile(r"(API|api|接口|endpoint|function|class|def |async def )"),
    ]
    _CODE_PATTERNS = [
        re.compile(r"(```[\s\S]*?```|def \w+|class \w+)"),
    ]
    _ERROR_PATTERNS = [
        re.compile(r"(error|Error|错误|异常|exception|traceback|失败)", re.IGNORECASE),
    ]

    def distill_session(self, entries: List[MemoryEntry]) -> Dict[str, List[Dict[str, Any]]]:
        result: Dict[str, List[Dict[str, Any]]] = {
            "decisions": [],
            "api_definitions": [],
            "code_snippets": [],
            "error_solutions": [],
        }
        for entry in entries:
            content = str(entry.value)
            tags = entry.metadata.get("tags", []) if entry.metadata else []

            for pattern in self._DECISION_PATTERNS:
                if pattern.search(content):
                    result["decisions"].append({
                        "key": entry.key,
                        "content": content[:500],
                        "importance": entry.importance,
                    })
                    break

            for pattern in self._API_PATTERNS:
                if pattern.search(content):
                    result["api_definitions"].append({
                        "key": entry.key,
                        "content": content[:500],
                    })
                    break

            for pattern in self._CODE_PATTERNS:
                if pattern.search(content):
                    result["code_snippets"].append({
                        "key": entry.key,
                        "content": content[:1000],
                    })
                    break

            for pattern in self._ERROR_PATTERNS:
                if pattern.search(content):
                    result["error_solutions"].append({
                        "key": entry.key,
                        "content": content[:500],
                    })
                    break

        return result

    def merge_similar(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen_keys: Dict[str, int] = {}
        for entry in entries:
            key = entry.get("key", "")
            if key in seen_keys:
                idx = seen_keys[key]
                existing = merged[idx]
                if len(entry.get("content", "")) > len(existing.get("content", "")):
                    merged[idx] = entry
            else:
                seen_keys[key] = len(merged)
                merged.append(entry)
        return merged


class MemoryRetriever:
    LAYER_ORDER = [MemoryLayer.SESSION, MemoryLayer.PROJECT, MemoryLayer.USER, MemoryLayer.KNOWLEDGE]

    def __init__(
        self,
        session_mem: SessionMemory,
        user_mem: UserMemory,
        project_mem: ProjectMemory,
        knowledge_mem: KnowledgeMemory,
    ):
        self.session_mem = session_mem
        self.user_mem = user_mem
        self.project_mem = project_mem
        self.knowledge_mem = knowledge_mem

    def retrieve_across_layers(
        self,
        query: str,
        layers: Optional[List[str]] = None,
        limit: int = 10,
        time_filter: Optional[Tuple[float, float]] = None,
        type_filter: str = "",
    ) -> List[Tuple[str, Any]]:
        if layers is None:
            layers = list(self.LAYER_ORDER)
        candidates: List[Tuple[str, Any, float]] = []
        for layer_name in layers:
            if layer_name == MemoryLayer.KNOWLEDGE:
                results = self.knowledge_mem.search(query, category=type_filter, limit=limit * 3)
                for entry in results:
                    score = len(query.lower().split()) + entry.get("importance", 0.5)
                    candidates.append((layer_name, entry, score))
            elif layer_name == MemoryLayer.SESSION:
                entries = self.session_mem.search(query, limit=limit * 3)
                for entry in entries:
                    rel = _relevance_score(entry, query)
                    recency = max(0.0, 1.0 - (time.time() - entry.accessed_at) / 86400.0)
                    score = rel + entry.importance + recency
                    candidates.append((layer_name, entry, score))
            else:
                mem = self.project_mem if layer_name == MemoryLayer.PROJECT else self.user_mem
                entries = mem.search(query, limit=limit * 3)
                for entry in entries:
                    rel = _relevance_score(entry, query)
                    recency = max(0.0, 1.0 - (time.time() - entry.accessed_at) / 86400.0)
                    score = rel + entry.importance + recency
                    candidates.append((layer_name, entry, score))
        candidates.sort(key=lambda x: x[2], reverse=True)
        return [(layer_name, entry) for layer_name, entry, _ in candidates[:limit]]


class MemoryArchiver:
    def __init__(
        self,
        session_mem: SessionMemory,
        user_mem: UserMemory,
        project_mem: ProjectMemory,
        knowledge_mem: KnowledgeMemory,
    ):
        self.session_mem = session_mem
        self.user_mem = user_mem
        self.project_mem = project_mem
        self.knowledge_mem = knowledge_mem

    def auto_archive(self, session_id: str) -> int:
        entries = self.session_mem._all_entries()
        archived = 0
        to_remove: List[str] = []
        now = time.time()
        for entry in entries:
            tags = entry.metadata.get("tags", []) if entry.metadata else []
            promoted = False

            if entry.importance >= 0.7:
                self.project_mem.store(entry.key, entry.value, entry.metadata)
                promoted = True

            if "preference" in tags:
                self.user_mem.store(entry.key, entry.value, entry.metadata)
                promoted = True

            if "best_practice" in tags or "pattern" in tags:
                self.knowledge_mem.store(
                    key=entry.key,
                    content=str(entry.value)[:2000],
                    category="distilled",
                    tags=tags,
                    importance=entry.importance,
                )
                promoted = True

            if entry.is_starred:
                to_remove.append(entry.key)
                archived += 1
                continue

            if entry.expires_at > 0 and entry.expires_at < now:
                to_remove.append(entry.key)
                archived += 1
                continue

            if entry.importance < 0.3 and (now - entry.created_at) > 86400:
                self.knowledge_mem.archive(entry.entry_id)
                to_remove.append(entry.key)
                archived += 1
                continue

            if promoted:
                to_remove.append(entry.key)
                archived += 1

        for key in to_remove:
            self.session_mem._remove_entry(key)

        return archived

    def evaluate_importance(self, entry: MemoryEntry) -> float:
        score = 0.4
        score += min(entry.access_count * 0.05, 0.3)
        recency = max(0.0, 1.0 - (time.time() - entry.accessed_at) / 86400.0)
        score += recency * 0.2
        tags = entry.metadata.get("tags", []) if entry.metadata else []
        important_tags = {"preference", "best_practice", "pattern", "project_context"}
        tag_overlap = len(set(tags) & important_tags)
        score += tag_overlap * 0.05
        return min(max(score, 0.0), 1.0)


class MemorySystem:
    def __init__(
        self,
        session_id: str,
        user_id: str = "default",
        project_path: str = "",
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.project_path = project_path
        self.session_mem = SessionMemory(session_id)
        self.user_mem = UserMemory(user_id)
        self.project_mem = ProjectMemory(project_path)
        self.knowledge_mem = KnowledgeMemory()
        self.distiller = MemoryDistiller()
        self.retriever = MemoryRetriever(
            self.session_mem, self.user_mem, self.project_mem, self.knowledge_mem
        )
        self.archiver = MemoryArchiver(
            self.session_mem, self.user_mem, self.project_mem, self.knowledge_mem
        )
        self._layer_map: Dict[str, Any] = {
            MemoryLayer.SESSION: self.session_mem,
            MemoryLayer.USER: self.user_mem,
            MemoryLayer.PROJECT: self.project_mem,
            MemoryLayer.KNOWLEDGE: self.knowledge_mem,
        }

    def store(self, layer: str, key: str, value: Any, metadata: Optional[dict] = None) -> str:
        mem = self._layer_map.get(layer)
        if mem is None:
            raise ValueError("Unknown layer: " + layer)
        return mem.store(key, value, metadata)

    def retrieve(self, layer: str, key: str) -> Any:
        mem = self._layer_map.get(layer)
        if mem is None:
            raise ValueError("Unknown layer: " + layer)
        return mem.retrieve(key)

    def search(
        self,
        query: str,
        layers: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Tuple[str, Any]]:
        return self.retriever.retrieve_across_layers(query, layers, limit)

    def distill_session(self) -> Dict[str, List[Dict[str, Any]]]:
        entries = self.session_mem._all_entries()
        distilled = self.distiller.distill_session(entries)
        for category, items in distilled.items():
            merged = self.distiller.merge_similar(items)
            for item in merged:
                self.knowledge_mem.store(
                    key=item.get("key", ""),
                    content=item.get("content", ""),
                    category="distilled_" + category,
                    tags=["distilled", category],
                    importance=0.6,
                )
        return distilled

    def get_context(
        self, max_tokens: int = 4000
    ) -> List[Tuple[str, Any]]:
        result: List[Tuple[str, Any]] = []
        total = 0
        session_entries = self.session_mem.get_context_window(max_tokens)
        for entry in session_entries:
            tokens = self.session_mem._estimate_tokens(entry.value)
            total += tokens
            result.append((MemoryLayer.SESSION, entry))
        remaining = max_tokens - total
        if remaining > 0:
            for layer_name in [MemoryLayer.PROJECT, MemoryLayer.USER]:
                mem = self._layer_map[layer_name]
                with mem._lock:
                    for entry in list(mem._entries.values()):
                        tokens = len(str(entry.value)) // 3
                        if total + tokens > max_tokens:
                            break
                        total += tokens
                        result.append((layer_name, entry))
        return result

    def archive_session(self) -> int:
        return self.archiver.auto_archive(self.session_id)

    def evict_knowledge(self, max_entries: int = 10000) -> int:
        return self.knowledge_mem.auto_evict(max_entries)

    def save_all(self) -> bool:
        results = [
            self.user_mem.save(),
            self.project_mem.save(),
        ]
        return all(results)

    def load_all(self) -> bool:
        results = [
            self.user_mem.load(),
            self.project_mem.load(),
        ]
        return any(results)

    def get_stats(self) -> dict:
        total_tokens = 0
        layer_counts = {}
        for layer_name, mem in self._layer_map.items():
            if layer_name == MemoryLayer.SESSION:
                count = mem.size()
            elif layer_name == MemoryLayer.KNOWLEDGE:
                count = len(mem.search("", limit=1))
                count = 1
            else:
                with mem._lock:
                    count = len(mem._entries)
            layer_counts[layer_name] = count
            entries = mem._all_entries() if hasattr(mem, "_all_entries") else []
            for entry in entries:
                total_tokens += len(str(entry.value)) // 3
        return {
            "layer_counts": layer_counts,
            "total_entries": sum(layer_counts.values()),
            "total_tokens": total_tokens,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "project_path": self.project_path,
        }


class PersistentMemorySystem:
    MEMORY_TYPES = ("user_profile", "project", "conversation", "ephemeral")

    def __init__(self, db_path: str = ""):
        if not db_path:
            config_dir = os.path.join(os.path.expanduser("~"), ".lemon_bridge")
            os.makedirs(config_dir, exist_ok=True)
            db_path = os.path.join(config_dir, "persistent_memory.db")
        self._db_path = db_path
        self._lock = Lock()
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                memory_type TEXT NOT NULL,
                session_id TEXT,
                content TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                access_count INTEGER DEFAULT 0,
                last_accessed REAL DEFAULT 0,
                created_at REAL DEFAULT 0,
                tags TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}'
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_pmem_type ON memories(memory_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pmem_session ON memories(session_id)")
        conn.commit()
        conn.close()

    def store_entry(self, memory_type: str, content: str,
                    session_id: str = "", importance: float = 0.5,
                    tags: Optional[List[str]] = None,
                    metadata: Optional[Dict[str, Any]] = None) -> str:
        entry_id = uuid.uuid4().hex[:16]
        now = time.time()
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO memories
                (id, memory_type, session_id, content, importance,
                 access_count, last_accessed, created_at, tags, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry_id, memory_type, session_id, content, importance,
                0, now, now,
                json.dumps(tags or []), json.dumps(metadata or {}),
            ))
            conn.commit()
            conn.close()
        return entry_id

    def retrieve_entries(self, memory_type: str = "", session_id: str = "",
                         min_importance: float = 0.0, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            query = "SELECT * FROM memories WHERE importance >= ?"
            params: List[Any] = [min_importance]
            if memory_type:
                query += " AND memory_type = ?"
                params.append(memory_type)
            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)
            query += " ORDER BY importance DESC, last_accessed DESC LIMIT ?"
            params.append(limit)
            c.execute(query, params)
            rows = c.fetchall()
            now = time.time()
            results: List[Dict[str, Any]] = []
            for row in rows:
                results.append({
                    "id": row[0], "memory_type": row[1], "session_id": row[2],
                    "content": row[3], "importance": row[4], "access_count": row[5],
                    "last_accessed": row[6], "created_at": row[7],
                    "tags": json.loads(row[8]), "metadata": json.loads(row[9]),
                })
                c.execute(
                    "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                    (now, row[0]),
                )
            conn.commit()
            conn.close()
        return results

    def get_user_profile(self, key: str = "") -> Dict[str, Any]:
        entries = self.retrieve_entries(memory_type="user_profile", limit=100)
        profile: Dict[str, Any] = {}
        for e in entries:
            tags = e.get("tags", [])
            if key and key not in tags:
                continue
            profile[e["id"]] = {
                "content": e["content"],
                "importance": e["importance"],
                "tags": tags,
            }
        return profile

    def update_user_profile(self, key: str, value: str, importance: float = 0.8) -> str:
        return self.store_entry(
            memory_type="user_profile",
            content=value,
            importance=importance,
            tags=["profile", key],
        )

    def get_project_memory(self, project_path: str = "") -> List[Dict[str, Any]]:
        return self.retrieve_entries(
            memory_type="project",
            session_id=project_path,
            min_importance=0.3,
        )

    def add_project_memory(self, project_path: str, content: str,
                           importance: float = 0.5, tags: Optional[List[str]] = None) -> str:
        return self.store_entry(
            memory_type="project",
            content=content,
            session_id=project_path,
            importance=importance,
            tags=tags or [],
        )

    def distill(self, max_age_days: float = 30, min_importance: float = 0.2) -> Dict[str, Any]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            now = time.time()
            max_age_seconds = max_age_days * 86400
            c.execute("""
                DELETE FROM memories
                WHERE memory_type = 'ephemeral'
                AND (? - last_accessed > ?)
            """, (now, max_age_seconds))
            c.execute("""
                DELETE FROM memories
                WHERE importance < ?
                AND (? - last_accessed > ?)
                AND memory_type NOT IN ('user_profile')
            """, (min_importance, now, max_age_seconds * 2))
            deleted = c.rowcount
            conn.commit()
            conn.close()
        return {
            "deleted_count": deleted,
            "max_age_days": max_age_days,
            "min_importance": min_importance,
        }

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            stats: Dict[str, int] = {}
            for mtype in self.MEMORY_TYPES:
                c.execute("SELECT COUNT(*) FROM memories WHERE memory_type = ?", (mtype,))
                stats[mtype] = c.fetchone()[0]
            c.execute("SELECT AVG(importance) FROM memories")
            avg_importance = c.fetchone()[0] or 0.0
            conn.close()
        return {
            "total_memories": sum(stats.values()),
            "by_type": stats,
            "avg_importance": round(avg_importance, 3),
        }
