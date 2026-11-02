import os
import json
import time
import math
import logging
from typing import Optional, Dict, List, Union
from collections import defaultdict

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".lemoncode", "vector_memory")

_COSINE_THRESHOLD = 0.9
_EXPIRY_SECONDS = 2592000
_DEDUP_CHECK_COUNT = 10


def _bow_vector(text: str, vocab: Dict[str, int]) -> List[float]:
    vec = [0.0] * len(vocab)
    for w in text.lower().split():
        idx = vocab.get(w)
        if idx is not None:
            vec[idx] += 1.0
    return vec


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(a * a for a in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def _build_vocab(*texts: str) -> Dict[str, int]:
    vocab: Dict[str, int] = {}
    idx = 0
    for text in texts:
        for word in text.lower().split():
            if word not in vocab:
                vocab[word] = idx
                idx += 1
    return vocab


class MemoryStore:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._vdb = None
        self._initialized = False
        self._sessions: Dict[str, List[Dict]] = defaultdict(list)
        self._deduplicated_count = 0
        self._expired_purged_count = 0
        self._index_path = os.path.join(self._db_path, "memory_index.json")
        self._load_index()

    def _load_index(self):
        try:
            if os.path.exists(self._index_path):
                with open(self._index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for sid, entries in data.get("sessions", {}).items():
                    self._sessions[sid] = entries
                self._deduplicated_count = data.get("deduplicated_count", 0)
                self._expired_purged_count = data.get("expired_purged_count", 0)
        except Exception as e:
            logger.debug(f"[MemoryStore] 加载索引失败: {e}")

    def _save_index(self):
        try:
            os.makedirs(os.path.dirname(self._index_path), exist_ok=True)
            with open(self._index_path, "w", encoding="utf-8") as f:
                json.dump({
                    "sessions": dict(self._sessions),
                    "deduplicated_count": self._deduplicated_count,
                    "expired_purged_count": self._expired_purged_count,
                }, f, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"[MemoryStore] 保存索引失败: {e}")

    def _ensure_db(self):
        if self._initialized:
            return self._vdb is not None
        self._initialized = True
        try:
            from shared.vector_database import VectorDatabaseManager
            os.makedirs(self._db_path, exist_ok=True)
            self._vdb = VectorDatabaseManager(self._db_path, embedding_type="tfidf")
            collections = self._vdb.list_collections()
            if "agent_memories" not in collections:
                self._vdb.create_collection("agent_memories")
            logger.info(f"[MemoryStore] 向量记忆库已初始化: {self._db_path}")
            return True
        except Exception as e:
            logger.warning(f"[MemoryStore] 向量库初始化失败，降级为空: {e}")
            self._vdb = None
            return False

    def _check_dedup(self, session_id: str, text: str) -> Optional[str]:
        entries = self._sessions.get(session_id, [])
        recent = entries[-_DEDUP_CHECK_COUNT:]
        if not recent:
            return None
        all_texts = [text] + [e.get("text", "") for e in recent]
        vocab = _build_vocab(*all_texts)
        new_vec = _bow_vector(text, vocab)
        for entry in recent:
            entry_vec = _bow_vector(entry.get("text", ""), vocab)
            sim = _cosine_similarity(new_vec, entry_vec)
            if sim > _COSINE_THRESHOLD:
                self._deduplicated_count += 1
                self._save_index()
                logger.debug(f"[MemoryStore] 去重命中: session={session_id}, sim={sim:.3f}")
                return entry.get("id")
        return None

    def _purge_expired(self, session_id: str):
        entries = self._sessions.get(session_id, [])
        if not entries:
            return
        cutoff = time.time() - _EXPIRY_SECONDS
        before = len(entries)
        kept = [e for e in entries if e.get("created_at", 0) > cutoff]
        purged = before - len(kept)
        if purged > 0:
            self._sessions[session_id] = kept
            self._expired_purged_count += purged
            self._save_index()
            logger.debug(f"[MemoryStore] 清理过期: session={session_id}, purged={purged}")

    def add_memory(self, text: str, metadata: Optional[Dict] = None,
                   session_id: Optional[str] = None) -> Union[bool, str]:
        if session_id:
            self._purge_expired(session_id)
            existing_id = self._check_dedup(session_id, text)
            if existing_id is not None:
                return existing_id

        created_at = time.time()
        entry_id = f"mem_{int(created_at * 1000)}_{abs(hash(text)) % 100000}"

        if session_id:
            self._sessions[session_id].append({
                "id": entry_id,
                "text": text,
                "created_at": created_at,
            })
            self._save_index()

        if not self._ensure_db():
            if session_id:
                return entry_id
            return False
        try:
            meta = metadata or {}
            meta["timestamp"] = meta.get("timestamp", created_at)
            meta["created_at"] = created_at
            if session_id:
                meta["session_id"] = session_id
            # ★ 修复: VectorDatabaseManager.add_document 签名是 (collection_name, document: VectorDocument)
            #   而非 content=/metadata= 关键字。构造 VectorDocument 对象再调用。
            try:
                from shared.vector_database import VectorDocument
                self._vdb.add_document(
                    collection_name="agent_memories",
                    document=VectorDocument(
                        id=entry_id,
                        content=text,
                        metadata=meta,
                    ),
                )
            except (ImportError, TypeError):
                # 兜底: 若 VectorDocument 不可用或签名仍不匹配，退化为仅本地索引（不阻断主流程）
                logger.debug("[MemoryStore] VectorDocument 兜底: 仅本地索引")
            if session_id:
                return entry_id
            return True
        except Exception as e:
            logger.debug(f"[MemoryStore] add_memory 失败: {e}")
            if session_id:
                return entry_id
            return False

    def search_memories(self, query: str, top_k: int = 5) -> List[Dict]:
        if not self._ensure_db():
            return []
        try:
            results = self._vdb.query_similar(
                collection_name="agent_memories",
                query=query,
                n_results=top_k,
            )
            return results
        except Exception as e:
            logger.debug(f"[MemoryStore] search_memories 失败: {e}")
            return []

    def query_memories(self, session_id: str, query: str = "",
                       top_k: int = 5) -> Dict:
        self._purge_expired(session_id)
        memories: List[Dict] = []
        injected = 0
        cutoff = time.time() - _EXPIRY_SECONDS

        if query:
            raw = self.search_memories(query, top_k=top_k)
            for m in raw:
                meta = m.get("metadata", m)
                created = meta.get("created_at", meta.get("timestamp", 0))
                if created > cutoff:
                    memories.append(m)
                    injected += 1
        else:
            session_entries = self._sessions.get(session_id, [])
            for e in session_entries[-top_k:]:
                if e.get("created_at", 0) > cutoff:
                    memories.append({"content": e.get("text", ""), "metadata": e})
                    injected += 1

        return {
            "memories": memories,
            "stats": {
                "injected": injected,
                "deduplicated": self._deduplicated_count,
                "expired_purged": self._expired_purged_count,
            }
        }

    def inject_into_prompt(self, system_prompt: str, query: str, max_chars: int = 1000) -> str:
        memories = self.search_memories(query, top_k=3)
        if not memories:
            return system_prompt
        mem_text = "\n".join([
            f"- {m.get('content', '')[:200]}"
            for m in memories
            if m.get("content")
        ])
        if not mem_text:
            return system_prompt
        if len(mem_text) > max_chars:
            mem_text = mem_text[:max_chars] + "..."
        injection = f"\n\n## 相关历史记忆\n{mem_text}\n"
        return system_prompt + injection

    def save_conversation_summary(self, prompt: str, response: str,
                                  engine: str = "",
                                  session_id: Optional[str] = None) -> Union[bool, str]:
        summary = f"Q: {prompt[:300]}\nA: {response[:500]}"
        return self.add_memory(summary, {"engine": engine, "type": "conversation"},
                               session_id=session_id)

    def get_stats(self) -> Dict:
        total_entries = sum(len(v) for v in self._sessions.values())
        return {
            "total_entries": total_entries,
            "total_sessions": len(self._sessions),
            "deduplicated_count": self._deduplicated_count,
            "expired_purged_count": self._expired_purged_count,
        }

    def save(self):
        self._save_index()
        if self._vdb and hasattr(self._vdb, 'persist'):
            try:
                self._vdb.persist()
            except Exception:
                pass


_memory_store_instance: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _memory_store_instance
    if _memory_store_instance is None:
        _memory_store_instance = MemoryStore()
    return _memory_store_instance
