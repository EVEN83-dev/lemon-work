# -*- coding: utf-8 -*-
"""
消息持久化存储 — 基于 SQLite3
==============================
核心能力：
- 会话管理：创建/列表/删除/切换
- 消息存储：用户消息、AI回复、工具调用结果全部持久化
- 全文搜索：关键词搜索历史消息
- 快照关联：快照记录与消息会话关联

架构：
┌──────────────────────────────────────────────┐
│              MessageStore                      │
│  ┌─────────────┐ ┌──────────────────────┐    │
│  │ sessions    │ │ messages              │    │
│  │ - id        │ │ - id                  │    │
│  │ - title     │ │ - session_id          │    │
│  │ - created_at│ │ - role (user/ai/tool) │    │
│  │ - updated_at│ │ - content             │    │
│  │ - project   │ │ - timestamp           │    │
│  └─────────────┘ │ - metadata_json       │    │
│  ┌─────────────┐ └──────────────────────┘    │
│  │ snapshots   │                              │
│  │ - id        │                              │
│  │ - session_id│                              │
│  │ - label     │                              │
│  │ - commit    │                              │
│  │ - created_at│                              │
│  └─────────────┘                              │
└──────────────────────────────────────────────┘
"""

import os
import json
import sqlite3
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime


class MessageStore:
    """消息持久化存储 — SQLite3"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            # 默认路径：~/.mimo_agent/messages.db
            home = os.path.expanduser("~")
            data_dir = os.path.join(home, ".mimo_agent")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "messages.db")

        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（每次创建新连接，线程安全）"""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # WAL 模式，提高并发性能
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        """初始化数据库表结构"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id          TEXT PRIMARY KEY,
                        title       TEXT NOT NULL DEFAULT '新会话',
                        created_at  TEXT NOT NULL,
                        updated_at  TEXT NOT NULL,
                        project_path TEXT
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id  TEXT NOT NULL,
                        role        TEXT NOT NULL,  -- user / assistant / tool / status
                        content     TEXT NOT NULL,
                        timestamp   TEXT NOT NULL,
                        metadata_json TEXT,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS snapshots (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id  TEXT,
                        label       TEXT,
                        commit_hash TEXT,
                        created_at  TEXT NOT NULL
                    );

                    -- 索引
                    CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
                    CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
                    CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
                    CREATE INDEX IF NOT EXISTS idx_snapshots_session ON snapshots(session_id);
                    -- ★ 复合索引：加速分页查询（session_id + id 联合）
                    CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id);
                    -- ★ 复合索引：加速归档查询（timestamp 优先）
                    CREATE INDEX IF NOT EXISTS idx_messages_ts_session ON messages(timestamp, session_id);
                """)

                # FTS 全文搜索表（如果 SQLite 支持 FTS5）
                # ★ 使用外部内容模式 (content='messages') 而非 contentless 模式
                #   SQLite 3.51.0 中 contentless FTS5 的 'delete' 命令会导致 "SQL logic error"
                #   外部内容模式可正常支持 DELETE 触发器
                try:
                    conn.execute("""
                        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                        USING fts5(content, content='messages', content_rowid='rowid', tokenize='unicode61')
                    """)
                    # 触发器：自动同步 FTS
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages
                        BEGIN
                            INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
                        END
                    """)
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages
                        BEGIN
                            INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
                        END
                    """)
                    # ★ 添加更新触发器
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages
                        BEGIN
                            INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
                            INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
                        END
                    """)
                except sqlite3.Error as e:
                    print(f"[MessageStore] FTS5 初始化失败（将禁用全文搜索）: {e}", flush=True)
                    # FTS5 不可用时跳过，不影响核心功能

                # ★ 归档表：超过指定天数的消息从 messages 移到 messages_archive
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS messages_archive (
                        id          INTEGER PRIMARY KEY,
                        session_id  TEXT NOT NULL,
                        role        TEXT NOT NULL,
                        content     TEXT NOT NULL,
                        timestamp   TEXT NOT NULL,
                        metadata_json TEXT,
                        archived_at TEXT NOT NULL
                    );
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_archive_session ON messages_archive(session_id);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_archive_timestamp ON messages_archive(timestamp);"
                )

                conn.commit()
            finally:
                conn.close()

    # ============================================================
    # 会话管理
    # ============================================================

    def create_session(self, session_id: str, title: str = "新会话",
                       project_path: str = "") -> Dict:
        """创建新会话"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO sessions (id, title, created_at, updated_at, project_path) VALUES (?, ?, ?, ?, ?)",
                    (session_id, title, now, now, project_path)
                )
                conn.commit()
                return {"id": session_id, "title": title, "created_at": now, "updated_at": now, "project_path": project_path}
            except sqlite3.Error as e:
                print(f"[MessageStore] 创建会话失败: {e}", flush=True)
                conn.rollback()
                raise
            finally:
                conn.close()

    def update_session_title(self, session_id: str, title: str):
        """更新会话标题"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
                    (title, now, session_id)
                )
                conn.commit()
            finally:
                conn.close()

    def update_session_timestamp(self, session_id: str):
        """更新会话的最后修改时间"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE sessions SET updated_at=? WHERE id=?",
                    (now, session_id)
                )
                conn.commit()
            finally:
                conn.close()

    def list_sessions(self, limit: int = 20) -> List[Dict]:
        """列出最近会话"""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) as msg_count "
                    "FROM sessions s ORDER BY s.updated_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def delete_session(self, session_id: str) -> bool:
        """删除会话及其所有消息"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
                conn.execute("DELETE FROM snapshots WHERE session_id=?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
                conn.commit()
                return True
            except Exception:
                return False
            finally:
                conn.close()

    def get_session(self, session_id: str) -> Optional[Dict]:
        """获取单个会话信息"""
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE id=?", (session_id,)
                ).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    # ============================================================
    # 消息管理
    # ============================================================

    def add_message(self, session_id: str, role: str, content: str,
                    metadata: dict = None) -> Optional[int]:
        """添加消息

        Args:
            session_id: 会话ID
            role: 角色 (user/assistant/tool/status)
            content: 消息内容
            metadata: 附加元数据（如工具名称、文件路径等）

        Returns:
            消息ID，失败返回 None
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "INSERT INTO messages (session_id, role, content, timestamp, metadata_json) VALUES (?, ?, ?, ?, ?)",
                    (session_id, role, content, now, meta_json)
                )
                # 更新会话时间戳
                conn.execute(
                    "UPDATE sessions SET updated_at=? WHERE id=?",
                    (now, session_id)
                )
                conn.commit()
                return cursor.lastrowid
            except Exception as e:
                print(f"[MessageStore] 添加消息失败: {e}", flush=True)
                return None
            finally:
                conn.close()

    def get_messages(self, session_id: str, limit: int = 50,
                     offset: int = 0) -> List[Dict]:
        """获取会话消息列表（分页查询，默认每次50条）"""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE session_id=? ORDER BY id ASC LIMIT ? OFFSET ?",
                    (session_id, limit, offset)
                ).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    if d.get('metadata_json'):
                        try:
                            d['metadata'] = json.loads(d['metadata_json'])
                        except Exception:
                            d['metadata'] = {}
                    else:
                        d['metadata'] = {}
                    result.append(d)
                return result
            finally:
                conn.close()

    def get_message_count(self, session_id: str) -> int:
        """获取会话消息数量"""
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM messages WHERE session_id=?",
                    (session_id,)
                ).fetchone()
                return row['cnt'] if row else 0
            finally:
                conn.close()

    # ============================================================
    # 搜索
    # ============================================================

    def search_messages(self, keyword: str, limit: int = 50) -> List[Dict]:
        """全文搜索消息

        Args:
            keyword: 搜索关键词
            limit: 最多返回条数

        Returns:
            匹配的消息列表，包含会话信息
        """
        with self._lock:
            conn = self._get_conn()
            try:
                # 尝试 FTS5 全文搜索
                try:
                    rows = conn.execute(
                        "SELECT m.*, s.title as session_title "
                        "FROM messages_fts fts "
                        "JOIN messages m ON m.id = fts.rowid "
                        "JOIN sessions s ON s.id = m.session_id "
                        "WHERE messages_fts MATCH ? "
                        "ORDER BY m.timestamp DESC LIMIT ?",
                        (keyword, limit)
                    ).fetchall()
                    if rows:
                        return [dict(r) for r in rows]
                except Exception:
                    pass

                # 降级：LIKE 搜索
                pattern = f"%{keyword}%"
                rows = conn.execute(
                    "SELECT m.*, s.title as session_title "
                    "FROM messages m "
                    "JOIN sessions s ON s.id = m.session_id "
                    "WHERE m.content LIKE ? "
                    "ORDER BY m.timestamp DESC LIMIT ?",
                    (pattern, limit)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ============================================================
    # 快照管理
    # ============================================================

    def add_snapshot(self, session_id: str, label: str, commit_hash: str = None) -> Optional[int]:
        """记录快照"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "INSERT INTO snapshots (session_id, label, commit_hash, created_at) VALUES (?, ?, ?, ?)",
                    (session_id, label, commit_hash, now)
                )
                conn.commit()
                return cursor.lastrowid
            except Exception:
                return None
            finally:
                conn.close()

    def get_snapshots(self, session_id: str) -> List[Dict]:
        """获取会话的快照列表"""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM snapshots WHERE session_id=? ORDER BY created_at DESC",
                    (session_id,)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ============================================================
    # 统计与维护
    # ============================================================

    def get_stats(self) -> Dict:
        """获取数据库统计信息"""
        with self._lock:
            conn = self._get_conn()
            try:
                sessions = conn.execute("SELECT COUNT(*) as cnt FROM sessions").fetchone()
                messages = conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()
                snapshots = conn.execute("SELECT COUNT(*) as cnt FROM snapshots").fetchone()
                db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                return {
                    "sessions": sessions['cnt'],
                    "messages": messages['cnt'],
                    "snapshots": snapshots['cnt'],
                    "db_size_bytes": db_size,
                    "db_path": self.db_path,
                }
            finally:
                conn.close()

    def cleanup_old_sessions(self, keep: int = 100):
        """清理旧会话，只保留最近 keep 个"""
        with self._lock:
            conn = self._get_conn()
            try:
                old_ids = conn.execute(
                    "SELECT id FROM sessions ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
                    (keep,)
                ).fetchall()
                for row in old_ids:
                    sid = row['id']
                    conn.execute("DELETE FROM messages WHERE session_id=?", (sid,))
                    conn.execute("DELETE FROM snapshots WHERE session_id=?", (sid,))
                    conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
                conn.commit()
                return len(old_ids)
            finally:
                conn.close()

    # ============================================================
    # ★ 消息归档（性能优化：老消息移到归档表）
    # ============================================================

    def archive_old_messages(self, days: int = 30) -> int:
        """将超过指定天数的消息从 messages 移到 messages_archive
        
        Args:
            days: 超过此天数的消息将被归档
            
        Returns:
            归档的消息数量
        """
        cutoff = datetime.now().strftime("%Y-%m-%d 00:00:00")
        # 计算截止日期
        from datetime import timedelta
        cutoff_dt = datetime.now() - timedelta(days=days)
        cutoff = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
        archived_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with self._lock:
            conn = self._get_conn()
            try:
                # 1. 将老消息插入归档表
                conn.execute("""
                    INSERT OR IGNORE INTO messages_archive 
                        (id, session_id, role, content, timestamp, metadata_json, archived_at)
                    SELECT id, session_id, role, content, timestamp, metadata_json, ?
                    FROM messages
                    WHERE timestamp < ?
                """, (archived_at, cutoff))
                # 2. 从 FTS 中删除
                try:
                    old_rows = conn.execute(
                        "SELECT id, content FROM messages WHERE timestamp < ?", (cutoff,)
                    ).fetchall()
                    for r in old_rows:
                        conn.execute(
                            "INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', ?, ?)",
                            (r['id'], r['content'])
                        )
                except Exception:
                    pass
                # 3. 从 messages 表删除
                cursor = conn.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))
                count = cursor.rowcount
                conn.commit()
                if count > 0:
                    print(f"[MessageStore] 归档 {count} 条老消息（>{days}天）", flush=True)
                return count
            finally:
                conn.close()

    def get_archived_messages(self, session_id: str, limit: int = 50,
                              offset: int = 0) -> List[Dict]:
        """获取归档的消息"""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM messages_archive WHERE session_id=? ORDER BY id ASC LIMIT ? OFFSET ?",
                    (session_id, limit, offset)
                ).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    if d.get('metadata_json'):
                        try:
                            d['metadata'] = json.loads(d['metadata_json'])
                        except Exception:
                            d['metadata'] = {}
                    else:
                        d['metadata'] = {}
                    result.append(d)
                return result
            finally:
                conn.close()

    def vacuum(self):
        """执行 VACUUM 优化数据库文件（减少碎片）"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("VACUUM")
                print("[MessageStore] VACUUM 完成", flush=True)
            finally:
                conn.close()
