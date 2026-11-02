"""
B-004: Session Memory - conversation history management.

Pure Python session/message storage with SQLite persistence.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Message:
    id: str = ""
    session_id: str = ""
    role: str = ""
    content: str = ""
    timestamp: float = 0.0
    tool_calls: str = ""
    tool_results: str = ""
    model: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:16]
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class Session:
    id: str = ""
    title: str = "New Chat"
    created_at: float = 0.0
    updated_at: float = 0.0
    message_count: int = 0
    model: str = ""
    metadata: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:16]
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "messageCount": self.message_count,
            "model": self.model,
        }


class SessionMemory:
    def __init__(self, db_path: str = ""):
        if not db_path:
            config_dir = os.path.join(os.path.expanduser("~"), ".lemon_bridge")
            os.makedirs(config_dir, exist_ok=True)
            db_path = os.path.join(config_dir, "sessions.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT 'New Chat',
                created_at REAL,
                updated_at REAL,
                message_count INTEGER DEFAULT 0,
                model TEXT DEFAULT '',
                metadata TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT DEFAULT '',
                timestamp REAL,
                tool_calls TEXT DEFAULT '',
                tool_results TEXT DEFAULT '',
                model TEXT DEFAULT '',
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
            conn.commit()
            conn.close()

    def create_session(self, title: str = "New Chat", model: str = "") -> Session:
        session = Session(title=title, model=model)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at, model) VALUES (?, ?, ?, ?, ?)",
                (session.id, session.title, session.created_at, session.updated_at, session.model),
            )
            conn.commit()
            conn.close()
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT id, title, created_at, updated_at, message_count, model FROM sessions WHERE id=?",
                      (session_id,))
            row = c.fetchone()
            conn.close()
        if row is None:
            return None
        return Session(id=row[0], title=row[1], created_at=row[2],
                       updated_at=row[3], message_count=row[4], model=row[5])

    def list_sessions(self, limit: int = 50, offset: int = 0) -> List[Session]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "SELECT id, title, created_at, updated_at, message_count, model FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = c.fetchall()
            conn.close()
        return [Session(id=r[0], title=r[1], created_at=r[2],
                        updated_at=r[3], message_count=r[4], model=r[5]) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            c.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            conn.commit()
            affected = c.rowcount
            conn.close()
        return affected > 0

    def add_message(self, session_id: str, role: str, content: str,
                    model: str = "", tool_calls: str = "",
                    tool_results: str = "") -> Message:
        msg = Message(session_id=session_id, role=role, content=content,
                      model=model, tool_calls=tool_calls, tool_results=tool_results)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "INSERT INTO messages (id, session_id, role, content, timestamp, tool_calls, tool_results, model) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (msg.id, msg.session_id, msg.role, msg.content, msg.timestamp,
                 msg.tool_calls, msg.tool_results, msg.model),
            )
            c.execute(
                "UPDATE sessions SET updated_at=?, message_count=message_count+1 WHERE id=?",
                (time.time(), session_id),
            )
            conn.commit()
            conn.close()
        return msg

    def get_messages(self, session_id: str, limit: int = 100,
                     offset: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "SELECT id, role, content, timestamp, tool_calls, tool_results, model FROM messages WHERE session_id=? ORDER BY timestamp ASC LIMIT ? OFFSET ?",
                (session_id, limit, offset),
            )
            rows = c.fetchall()
            conn.close()
        return [
            {
                "id": r[0], "role": r[1], "content": r[2],
                "timestamp": r[3], "toolCalls": json.loads(r[4]) if r[4] else [],
                "toolResults": json.loads(r[5]) if r[5] else [],
                "model": r[6],
            }
            for r in rows
        ]

    def get_context(self, session_id: str, max_messages: int = 20) -> List[Dict[str, str]]:
        messages = self.get_messages(session_id, limit=max_messages)
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    def search_messages(self, session_id: str, query: str,
                        limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "SELECT id, role, content, timestamp FROM messages WHERE session_id=? AND content LIKE ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, f"%{query}%", limit),
            )
            rows = c.fetchall()
            conn.close()
        return [{"id": r[0], "role": r[1], "content": r[2], "timestamp": r[3]} for r in rows]
