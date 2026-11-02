"""
B-P2-003: Memory Service

Cross-conversation memory management with CRUD,
auto-extraction, and category-based search.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..protocol.card_protocol import make_memory_card


@dataclass
class Memory:
    id: int = 0
    user_id: str = "default"
    content: str = ""
    category: str = "fact"
    source_session: str = ""
    created_at: float = 0.0
    expires_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "sourceSession": self.source_session,
            "createdAt": self.created_at,
        }


EXTRACTION_PATTERNS = [
    (r"(?:我喜欢|我爱|我偏好|我prefer)\s*(.+)", "preference"),
    (r"(?:我叫|我的名字是|我是)\s*(.+)", "fact"),
    (r"(?:我习惯|我通常|我一般)\s*(.+)", "habit"),
    (r"(?:我不喜欢|我讨厌|我恨)\s*(.+)", "preference"),
    (r"(?:我的|my)\s*(\w+)\s*(?:是|=)\s*(.+)", "fact"),
]


class MemoryService:
    def __init__(self, db_path: str = ""):
        if not db_path:
            db_path = str(Path(__file__).parent.parent / "data" / "memory.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'fact',
                source_session TEXT DEFAULT '',
                created_at REAL NOT NULL,
                expires_at REAL DEFAULT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)"
        )
        self._conn.commit()

    def add(
        self,
        content: str,
        category: str = "fact",
        user_id: str = "default",
        source_session: str = "",
    ) -> Dict[str, Any]:
        now = time.time()
        cursor = self._conn.execute(
            "INSERT INTO memories (user_id, content, category, source_session, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, content, category, source_session, now),
        )
        self._conn.commit()
        return {"id": cursor.lastrowid, "status": "created"}

    def search(self, query: str, user_id: str = "default", limit: int = 10) -> List[Dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT id, content, category, source_session, created_at FROM memories WHERE user_id = ? AND content LIKE ? ORDER BY created_at DESC LIMIT ?",
            (user_id, f"%{query}%", limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "content": r[1],
                "category": r[2],
                "sourceSession": r[3],
                "createdAt": r[4],
            }
            for r in rows
        ]

    def list_memories(
        self, user_id: str = "default", category: str = "", limit: int = 50
    ) -> List[Dict[str, Any]]:
        if category:
            cursor = self._conn.execute(
                "SELECT id, content, category, source_session, created_at FROM memories WHERE user_id = ? AND category = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, category, limit),
            )
        else:
            cursor = self._conn.execute(
                "SELECT id, content, category, source_session, created_at FROM memories WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "content": r[1],
                "category": r[2],
                "sourceSession": r[3],
                "createdAt": r[4],
            }
            for r in rows
        ]

    def delete(self, memory_id: int, user_id: str = "default") -> Dict[str, str]:
        self._conn.execute(
            "DELETE FROM memories WHERE id = ? AND user_id = ?",
            (memory_id, user_id),
        )
        self._conn.commit()
        return {"status": "deleted"}

    def extract_and_store(self, text: str, user_id: str = "default", source_session: str = "") -> List[Dict[str, Any]]:
        results = []
        for pattern, category in EXTRACTION_PATTERNS:
            match = re.search(pattern, text)
            if match:
                content = match.group(0)
                existing = self.search(content, user_id, limit=1)
                if not existing:
                    result = self.add(content, category, user_id, source_session)
                    results.append(result)
        return results

    def to_card(self, memories: List[Dict[str, Any]], title: str = "") -> str:
        return make_memory_card(memories, title).to_json_str()

    def close(self) -> None:
        self._conn.close()
