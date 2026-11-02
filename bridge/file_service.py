"""
B-008: File Service - handles file upload/download with temp storage.

Supports local filesystem storage with automatic cleanup.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_UPLOAD_DIR = os.path.join(os.path.expanduser("~"), ".lemon_bridge", "uploads")
DEFAULT_MAX_SIZE_MB = 50
DEFAULT_CLEANUP_HOURS = 24
ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp",
    ".csv", ".xlsx", ".xls", ".json",
    ".py", ".js", ".ts", ".java", ".cpp", ".c",
}


class FileService:
    def __init__(self, upload_dir: str = DEFAULT_UPLOAD_DIR,
                 max_size_mb: int = DEFAULT_MAX_SIZE_MB,
                 cleanup_hours: int = DEFAULT_CLEANUP_HOURS):
        self._upload_dir = upload_dir
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._cleanup_seconds = cleanup_hours * 3600
        self._lock = threading.Lock()
        os.makedirs(self._upload_dir, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        db_path = os.path.join(os.path.dirname(self._upload_dir), "files.db")
        self._db_path = db_path
        conn = sqlite3.connect(self._db_path)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS files (
            file_id TEXT PRIMARY KEY,
            original_name TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            size INTEGER DEFAULT 0,
            mime_type TEXT DEFAULT '',
            uploaded_at REAL,
            expires_at REAL,
            owner_id TEXT DEFAULT ''
        )""")
        conn.commit()
        conn.close()

    def save_file(self, filename: str, data: bytes, owner_id: str = "",
                  mime_type: str = "") -> Dict[str, Any]:
        if len(data) > self._max_size_bytes:
            return {"error": f"File too large (max {self._max_size_bytes // 1024 // 1024}MB)"}
        ext = os.path.splitext(filename)[1].lower()
        if ext and ext not in ALLOWED_EXTENSIONS:
            return {"error": f"File type not allowed: {ext}"}
        file_id = uuid.uuid4().hex[:16]
        stored_name = f"{file_id}{ext}"
        stored_path = os.path.join(self._upload_dir, stored_name)
        with open(stored_path, "wb") as f:
            f.write(data)
        uploaded_at = time.time()
        expires_at = uploaded_at + self._cleanup_seconds
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "INSERT INTO files (file_id, original_name, stored_path, size, mime_type, uploaded_at, expires_at, owner_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (file_id, filename, stored_path, len(data), mime_type,
                 uploaded_at, expires_at, owner_id),
            )
            conn.commit()
            conn.close()
        return {
            "fileId": file_id,
            "filename": filename,
            "size": len(data),
            "mimeType": mime_type,
            "path": stored_path,
        }

    def get_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "SELECT file_id, original_name, stored_path, size, mime_type, uploaded_at FROM files WHERE file_id=?",
                (file_id,),
            )
            row = c.fetchone()
            conn.close()
        if row is None:
            return None
        stored_path = row[2]
        if not os.path.exists(stored_path):
            return None
        return {
            "fileId": row[0],
            "filename": row[1],
            "path": stored_path,
            "size": row[3],
            "mimeType": row[4],
            "uploadedAt": row[5],
        }

    def read_file_content(self, file_id: str) -> Optional[bytes]:
        info = self.get_file(file_id)
        if info is None:
            return None
        try:
            with open(info["path"], "rb") as f:
                return f.read()
        except Exception:
            return None

    def delete_file(self, file_id: str) -> bool:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT stored_path FROM files WHERE file_id=?", (file_id,))
            row = c.fetchone()
            if row:
                stored_path = row[0]
                if os.path.exists(stored_path):
                    os.unlink(stored_path)
                c.execute("DELETE FROM files WHERE file_id=?", (file_id,))
                conn.commit()
            conn.close()
            return row is not None

    def cleanup_expired(self) -> int:
        now = time.time()
        count = 0
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT file_id, stored_path FROM files WHERE expires_at < ?", (now,))
            rows = c.fetchall()
            for file_id, stored_path in rows:
                if os.path.exists(stored_path):
                    os.unlink(stored_path)
                c.execute("DELETE FROM files WHERE file_id=?", (file_id,))
                count += 1
            conn.commit()
            conn.close()
        if count > 0:
            logger.info(f"Cleaned up {count} expired files")
        return count

    def list_files(self, owner_id: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            if owner_id:
                c.execute(
                    "SELECT file_id, original_name, size, mime_type, uploaded_at FROM files WHERE owner_id=? ORDER BY uploaded_at DESC LIMIT ?",
                    (owner_id, limit),
                )
            else:
                c.execute(
                    "SELECT file_id, original_name, size, mime_type, uploaded_at FROM files ORDER BY uploaded_at DESC LIMIT ?",
                    (limit,),
                )
            rows = c.fetchall()
            conn.close()
        return [
            {
                "fileId": r[0],
                "filename": r[1],
                "size": r[2],
                "mimeType": r[3],
                "uploadedAt": r[4],
            }
            for r in rows
        ]
