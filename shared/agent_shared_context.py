# -*- coding: utf-8 -*-
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_AGENT_PRIVATE_PREFIX = "agent:"
_SESSION_SHARED_PREFIX = "shared:"
_MAX_CONTEXT_SIZE = 50000
_MAX_KEY_SIZE = 1024


@dataclass
class ContextEntry:
    key: str
    value: Any
    owner: str
    scope: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    version: int = 1
    ttl_seconds: float = 0.0

    def is_expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return (time.time() - self.updated_at) > self.ttl_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "owner": self.owner,
            "scope": self.scope,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
        }


class SharedContext:
    def __init__(self, persist_dir: str = ""):
        self._entries: Dict[str, ContextEntry] = {}
        self._lock = threading.Lock()
        self._subscribers: Dict[str, List[callable]] = {}
        self._persist_dir = persist_dir or os.path.join(
            os.path.expanduser("~"), ".lemoncode", "data", "agent_context"
        )
        self._persist_enabled = False

    def enable_persistence(self, persist_dir: str = "") -> None:
        if persist_dir:
            self._persist_dir = persist_dir
        self._persist_enabled = True
        os.makedirs(self._persist_dir, exist_ok=True)
        self._load_from_disk()

    def set_private(self, agent_id: str, key: str, value: Any, ttl_seconds: float = 0.0) -> None:
        full_key = f"{_AGENT_PRIVATE_PREFIX}{agent_id}:{key}"
        entry = ContextEntry(
            key=full_key,
            value=value,
            owner=agent_id,
            scope="private",
            ttl_seconds=ttl_seconds,
        )
        with self._lock:
            existing = self._entries.get(full_key)
            if existing:
                entry.version = existing.version + 1
                entry.created_at = existing.created_at
            self._entries[full_key] = entry
        if self._persist_enabled:
            self._persist_entry(full_key, entry)

    def get_private(self, agent_id: str, key: str) -> Optional[Any]:
        full_key = f"{_AGENT_PRIVATE_PREFIX}{agent_id}:{key}"
        with self._lock:
            entry = self._entries.get(full_key)
            if not entry:
                return None
            if entry.is_expired():
                del self._entries[full_key]
                return None
            return entry.value

    def delete_private(self, agent_id: str, key: str) -> bool:
        full_key = f"{_AGENT_PRIVATE_PREFIX}{agent_id}:{key}"
        with self._lock:
            return self._entries.pop(full_key, None) is not None

    def list_private_keys(self, agent_id: str) -> List[str]:
        prefix = f"{_AGENT_PRIVATE_PREFIX}{agent_id}:"
        with self._lock:
            return [k[len(prefix):] for k in self._entries if k.startswith(prefix) and not self._entries[k].is_expired()]

    def set_shared(self, session_id: str, key: str, value: Any, owner: str = "", ttl_seconds: float = 0.0) -> None:
        full_key = f"{_SESSION_SHARED_PREFIX}{session_id}:{key}"
        entry = ContextEntry(
            key=full_key,
            value=value,
            owner=owner,
            scope="shared",
            ttl_seconds=ttl_seconds,
        )
        with self._lock:
            existing = self._entries.get(full_key)
            if existing:
                entry.version = existing.version + 1
                entry.created_at = existing.created_at
            self._entries[full_key] = entry
        self._notify_subscribers(full_key, entry)
        if self._persist_enabled:
            self._persist_entry(full_key, entry)

    def get_shared(self, session_id: str, key: str) -> Optional[Any]:
        full_key = f"{_SESSION_SHARED_PREFIX}{session_id}:{key}"
        with self._lock:
            entry = self._entries.get(full_key)
            if not entry:
                return None
            if entry.is_expired():
                del self._entries[full_key]
                return None
            return entry.value

    def delete_shared(self, session_id: str, key: str) -> bool:
        full_key = f"{_SESSION_SHARED_PREFIX}{session_id}:{key}"
        with self._lock:
            return self._entries.pop(full_key, None) is not None

    def list_shared_keys(self, session_id: str) -> List[str]:
        prefix = f"{_SESSION_SHARED_PREFIX}{session_id}:"
        with self._lock:
            return [k[len(prefix):] for k in self._entries if k.startswith(prefix) and self._entries[k].scope == "shared" and not self._entries[k].is_expired()]

    def get_agent_context(self, agent_id: str, session_id: str = "") -> Dict[str, Any]:
        private_data: Dict[str, Any] = {}
        shared_data: Dict[str, Any] = {}
        with self._lock:
            for full_key, entry in self._entries.items():
                if entry.is_expired():
                    continue
                if entry.scope == "private" and entry.owner == agent_id:
                    short_key = full_key.split(":", 2)[-1]
                    private_data[short_key] = entry.value
                if session_id and entry.scope == "shared":
                    shared_prefix = f"{_SESSION_SHARED_PREFIX}{session_id}:"
                    if full_key.startswith(shared_prefix):
                        short_key = full_key[len(shared_prefix):]
                        shared_data[short_key] = entry.value
        return {"private": private_data, "shared": shared_data}

    def clear_agent(self, agent_id: str) -> int:
        removed = 0
        prefix = f"{_AGENT_PRIVATE_PREFIX}{agent_id}:"
        with self._lock:
            for key in list(self._entries.keys()):
                if key.startswith(prefix):
                    del self._entries[key]
                    removed += 1
        return removed

    def clear_session(self, session_id: str) -> int:
        removed = 0
        prefix = f"{_SESSION_SHARED_PREFIX}{session_id}:"
        with self._lock:
            for key in list(self._entries.keys()):
                if key.startswith(prefix):
                    del self._entries[key]
                    removed += 1
        return removed

    def cleanup_expired(self) -> int:
        removed = 0
        with self._lock:
            for key in list(self._entries.keys()):
                if self._entries[key].is_expired():
                    del self._entries[key]
                    removed += 1
        return removed

    def subscribe(self, key_pattern: str, callback: callable) -> str:
        import uuid
        sub_id = "ctxsub_" + uuid.uuid4().hex[:8]
        with self._lock:
            if key_pattern not in self._subscribers:
                self._subscribers[key_pattern] = []
            self._subscribers[key_pattern].append((sub_id, callback))
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        with self._lock:
            for pattern, subs in self._subscribers.items():
                for i, (sid, cb) in enumerate(subs):
                    if sid == sub_id:
                        subs.pop(i)
                        return True
        return False

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._entries)
            private = sum(1 for e in self._entries.values() if e.scope == "private")
            shared = sum(1 for e in self._entries.values() if e.scope == "shared")
            expired = sum(1 for e in self._entries.values() if e.is_expired())
        return {"total_entries": total, "private_entries": private, "shared_entries": shared, "expired_entries": expired}

    def _notify_subscribers(self, full_key: str, entry: ContextEntry) -> None:
        with self._lock:
            subs = list(self._subscribers.items())
        for pattern, callbacks in subs:
            if pattern == "*" or pattern in full_key:
                for sub_id, cb in callbacks:
                    try:
                        cb(full_key, entry.to_dict())
                    except Exception:
                        pass

    def _persist_entry(self, full_key: str, entry: ContextEntry) -> None:
        if not self._persist_enabled:
            return
        try:
            path = os.path.join(self._persist_dir, full_key.replace(":", "_") + ".json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_from_disk(self) -> int:
        if not os.path.exists(self._persist_dir):
            return 0
        count = 0
        for fname in os.listdir(self._persist_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(self._persist_dir, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry = ContextEntry(
                    key=data["key"],
                    value=data["value"],
                    owner=data.get("owner", ""),
                    scope=data.get("scope", "private"),
                    created_at=data.get("created_at", time.time()),
                    updated_at=data.get("updated_at", time.time()),
                    version=data.get("version", 1),
                    ttl_seconds=data.get("ttl_seconds", 0.0),
                )
                if not entry.is_expired():
                    self._entries[entry.key] = entry
                    count += 1
            except Exception:
                pass
        return count


_global_shared_context: Optional[SharedContext] = None
_ctx_lock = threading.Lock()


def get_shared_context() -> SharedContext:
    global _global_shared_context
    if _global_shared_context is None:
        with _ctx_lock:
            if _global_shared_context is None:
                _global_shared_context = SharedContext()
    return _global_shared_context
