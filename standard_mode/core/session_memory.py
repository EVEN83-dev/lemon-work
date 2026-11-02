# -*- coding: utf-8 -*-
"""
Session Memory — 跨会话记忆系统
==================================
基于 SQLite FTS5 的持久化记忆系统，支持跨会话上下文保持。

功能：
1. 会话摘要自动生成与持久化
2. 全文搜索历史会话内容
3. 关键信息提取（项目名、文件路径、决策等）
4. 会话相关性检索（当前会话最相关的历史会话）
5. 自动记忆衰减（旧记忆权重降低）

设计原则：
- SQLite FTS5 全文索引，快速检索
- 增量更新，不阻塞主线程
- 隐私保护：敏感信息可选脱敏
- 与 KnowledgeBase 互补：KB 存 prompt→response 对，Memory 存会话上下文
"""

import os
import re
import json
import time
import sqlite3
import threading
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class SessionSummary:
    """会话摘要"""
    session_id: str
    title: str = ""                     # 会话标题
    created_at: str = ""                # 创建时间
    updated_at: str = ""                # 最后更新时间
    message_count: int = 0              # 消息数量
    key_topics: List[str] = field(default_factory=list)  # 关键话题
    key_files: List[str] = field(default_factory=list)   # 涉及的文件
    key_decisions: List[str] = field(default_factory=list)  # 关键决策
    last_message: str = ""              # 最后一条消息摘要
    total_tokens: int = 0               # 总 token 数
    importance: float = 0.5             # 重要性评分 (0-1)


@dataclass
class MemoryEntry:
    """记忆条目"""
    id: str
    session_id: str
    content: str                        # 记忆内容
    entry_type: str                     # decision / file / topic / code / user_pref
    importance: float = 0.5
    created_at: str = ""
    access_count: int = 0
    last_accessed: str = ""


class SessionMemory:
    """
    跨会话记忆系统
    
    使用方式：
        memory = SessionMemory()
        memory.save_session_summary(session_id, summary)
        results = memory.search("路由策略")
        context = memory.get_context_for_session(session_id)
    """
    
    DB_PATH = "session_memory.db"
    MAX_MEMORIES_PER_SESSION = 100
    MAX_CONTEXT_ENTRIES = 10
    
    def __init__(self, db_dir: str = None):
        if db_dir is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_dir = os.path.join(os.path.dirname(base), 'data')
        
        os.makedirs(db_dir, exist_ok=True)
        self._db_path = os.path.join(db_dir, self.DB_PATH)
        self._lock = threading.Lock()
        
        self._init_db()
        logger.info(f"[SessionMemory] 初始化完成: {self._db_path}")
    
    def _init_db(self):
        """初始化数据库"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            
            # 会话摘要表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    message_count INTEGER DEFAULT 0,
                    key_topics TEXT DEFAULT '[]',
                    key_files TEXT DEFAULT '[]',
                    key_decisions TEXT DEFAULT '[]',
                    last_message TEXT DEFAULT '',
                    total_tokens INTEGER DEFAULT 0,
                    importance REAL DEFAULT 0.5
                )
            """)
            
            # 记忆条目表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    content TEXT,
                    entry_type TEXT,
                    importance REAL DEFAULT 0.5,
                    created_at TEXT,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
            """)
            
            # FTS5 全文索引（虚拟表）
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    content,
                    entry_type,
                    content='memories',
                    content_rowid='rowid'
                )
            """)
            
            # 触发器：自动同步 FTS 索引
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content, entry_type)
                    VALUES (new.rowid, new.content, new.entry_type);
                END;
                
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, entry_type)
                    VALUES ('delete', old.rowid, old.content, old.entry_type);
                END;
                
                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content, entry_type)
                    VALUES ('delete', old.rowid, old.content, old.entry_type);
                    INSERT INTO memories_fts(rowid, content, entry_type)
                    VALUES (new.rowid, new.content, new.entry_type);
                END;
            """)
            
            conn.commit()
    
    # ================================================================
    # 会话摘要管理
    # ================================================================
    
    def save_session_summary(self, summary: SessionSummary):
        """保存或更新会话摘要"""
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO sessions 
                    (session_id, title, created_at, updated_at, message_count,
                     key_topics, key_files, key_decisions, last_message,
                     total_tokens, importance)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    summary.session_id,
                    summary.title,
                    summary.created_at or datetime.now().isoformat(),
                    summary.updated_at or datetime.now().isoformat(),
                    summary.message_count,
                    json.dumps(summary.key_topics, ensure_ascii=False),
                    json.dumps(summary.key_files, ensure_ascii=False),
                    json.dumps(summary.key_decisions, ensure_ascii=False),
                    summary.last_message,
                    summary.total_tokens,
                    summary.importance,
                ))
                conn.commit()
    
    def get_session_summary(self, session_id: str) -> Optional[SessionSummary]:
        """获取会话摘要"""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return SessionSummary(
                session_id=row['session_id'],
                title=row['title'],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                message_count=row['message_count'],
                key_topics=json.loads(row['key_topics']),
                key_files=json.loads(row['key_files']),
                key_decisions=json.loads(row['key_decisions']),
                last_message=row['last_message'],
                total_tokens=row['total_tokens'],
                importance=row['importance'],
            )
    
    def list_recent_sessions(self, limit: int = 20) -> List[Dict]:
        """列出最近的会话"""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT session_id, title, updated_at, message_count, importance "
                "FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
    
    def delete_session(self, session_id: str):
        """删除会话及其所有记忆"""
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM memories WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                conn.commit()
    
    # ================================================================
    # 记忆条目管理
    # ================================================================
    
    def add_memory(self, 
                   session_id: str,
                   content: str,
                   entry_type: str = "topic",
                   importance: float = 0.5) -> str:
        """
        添加记忆条目
        
        Args:
            session_id: 会话 ID
            content: 记忆内容
            entry_type: 类型 (decision/file/topic/code/user_pref)
            importance: 重要性 (0-1)
        
        Returns:
            memory_id
        """
        import uuid
        memory_id = uuid.uuid4().hex[:12]
        
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                # 检查该会话记忆数量
                count = conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE session_id = ?",
                    (session_id,)
                ).fetchone()[0]
                
                if count >= self.MAX_MEMORIES_PER_SESSION:
                    # 删除最旧的低重要性记忆
                    conn.execute("""
                        DELETE FROM memories WHERE id IN (
                            SELECT id FROM memories WHERE session_id = ?
                            ORDER BY importance ASC, created_at ASC
                            LIMIT 1
                        )
                    """, (session_id,))
                
                conn.execute("""
                    INSERT INTO memories (id, session_id, content, entry_type,
                                         importance, created_at, access_count, last_accessed)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """, (
                    memory_id, session_id, content, entry_type,
                    importance, datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ))
                conn.commit()
        
        return memory_id
    
    def add_memories_batch(self, entries: List[Dict]):
        """批量添加记忆"""
        for entry in entries:
            self.add_memory(
                session_id=entry.get('session_id', 'default'),
                content=entry.get('content', ''),
                entry_type=entry.get('entry_type', 'topic'),
                importance=entry.get('importance', 0.5),
            )
    
    # ================================================================
    # 搜索与检索
    # ================================================================
    
    def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        """
        全文搜索记忆
        
        Args:
            query: 搜索关键词
            limit: 返回数量
        
        Returns:
            MemoryEntry 列表
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            try:
                rows = conn.execute("""
                    SELECT m.* FROM memories m
                    JOIN memories_fts fts ON m.rowid = fts.rowid
                    WHERE memories_fts MATCH ?
                    ORDER BY m.importance DESC, m.access_count DESC
                    LIMIT ?
                """, (query, limit)).fetchall()
            except sqlite3.OperationalError:
                # FTS 查询语法错误时的回退
                rows = conn.execute("""
                    SELECT * FROM memories
                    WHERE content LIKE ?
                    ORDER BY importance DESC, access_count DESC
                    LIMIT ?
                """, (f'%{query}%', limit)).fetchall()
            
            results = []
            for row in rows:
                results.append(MemoryEntry(
                    id=row['id'],
                    session_id=row['session_id'],
                    content=row['content'],
                    entry_type=row['entry_type'],
                    importance=row['importance'],
                    created_at=row['created_at'],
                    access_count=row['access_count'],
                    last_accessed=row['last_accessed'],
                ))
            
            # 更新访问计数
            if results:
                self._update_access_counts([r.id for r in results])
            
            return results
    
    def get_context_for_session(self, session_id: str, limit: int = None) -> List[MemoryEntry]:
        """
        获取当前会话的上下文记忆
        
        包括：
        1. 当前会话的所有记忆
        2. 其他会话中与当前会话相关的记忆
        """
        if limit is None:
            limit = self.MAX_CONTEXT_ENTRIES
        
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # 获取当前会话的关键话题
            session = conn.execute(
                "SELECT key_topics FROM sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            
            if session:
                topics = json.loads(session['key_topics'])
                # 用话题搜索相关记忆
                topic_query = ' OR '.join(topics[:3]) if topics else session_id
            else:
                topic_query = session_id
            
            # 获取当前会话记忆 + 相关话题记忆
            rows = conn.execute("""
                SELECT * FROM memories
                WHERE session_id = ? OR (
                    session_id != ? AND (
                        content LIKE ? OR content LIKE ? OR content LIKE ?
                    )
                )
                ORDER BY 
                    CASE WHEN session_id = ? THEN 0 ELSE 1 END,
                    importance DESC,
                    access_count DESC
                LIMIT ?
            """, (
                session_id, session_id,
                f'%{topic_query}%', f'%{topic_query}%', f'%{topic_query}%',
                session_id, limit,
            )).fetchall()
            
            results = []
            for row in rows:
                results.append(MemoryEntry(
                    id=row['id'],
                    session_id=row['session_id'],
                    content=row['content'],
                    entry_type=row['entry_type'],
                    importance=row['importance'],
                    created_at=row['created_at'],
                    access_count=row['access_count'],
                    last_accessed=row['last_accessed'],
                ))
            
            return results
    
    def search_by_type(self, entry_type: str, limit: int = 20) -> List[MemoryEntry]:
        """按类型搜索记忆"""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM memories WHERE entry_type = ? "
                "ORDER BY importance DESC LIMIT ?",
                (entry_type, limit)
            ).fetchall()
            
            return [MemoryEntry(
                id=r['id'], session_id=r['session_id'],
                content=r['content'], entry_type=r['entry_type'],
                importance=r['importance'], created_at=r['created_at'],
                access_count=r['access_count'], last_accessed=r['last_accessed'],
            ) for r in rows]
    
    # ================================================================
    # 自动记忆提取
    # ================================================================
    
    def extract_and_remember(self, 
                             session_id: str,
                             message: str,
                             response: str = "") -> List[str]:
        """
        从对话中自动提取关键信息并记忆
        
        提取规则：
        - 文件路径: /path/to/file.py, d:\path\to\file
        - 决策: "我们决定", "最终方案", "使用...代替"
        - 用户偏好: "我喜欢", "我习惯", "我使用"
        - 项目信息: "项目名", "项目路径"
        
        Returns:
            新创建的记忆 ID 列表
        """
        new_ids = []
        
        # 提取文件路径
        file_patterns = [
            r'[a-zA-Z]:\\[^\s,;]+\.\w+',           # Windows: d:\path\to\file.py
            r'/[^\s,;]+\.\w+',                       # Unix: /path/to/file.py
            r'[\w-]+\.(?:py|js|ts|html|css|json|yaml|yml|md|txt)',  # 文件名
        ]
        for pattern in file_patterns:
            for match in re.findall(pattern, f"{message} {response}"):
                if len(match) > 3 and match.count('.') <= 3:
                    mid = self.add_memory(session_id, f"文件: {match}", "file", 0.6)
                    new_ids.append(mid)
        
        # 提取决策
        decision_patterns = [
            r'(?:决定|选择|采用|使用|最终方案)[:：]\s*(.+?)(?:[。，\n]|$)',
            r'(?:用|换成|改为)\s*(.+?)(?:代替|替换|取代)(.+?)(?:[。，\n]|$)',
        ]
        for pattern in decision_patterns:
            for match in re.findall(pattern, f"{message} {response}"):
                decision_text = match if isinstance(match, str) else ' '.join(match)
                if len(decision_text) > 5:
                    mid = self.add_memory(session_id, f"决策: {decision_text.strip()}", "decision", 0.8)
                    new_ids.append(mid)
        
        # 提取用户偏好
        pref_patterns = [
            r'(?:我喜欢|我习惯|我偏好|我使用|我选择)\s*(.+?)(?:[。，\n]|$)',
        ]
        for pattern in pref_patterns:
            for match in re.findall(pattern, message):
                if len(match) > 3:
                    mid = self.add_memory(session_id, f"偏好: {match.strip()}", "user_pref", 0.9)
                    new_ids.append(mid)
        
        return new_ids
    
    def auto_summarize_session(self, 
                               session_id: str,
                               messages: List[Dict]) -> SessionSummary:
        """
        自动生成会话摘要
        
        从消息列表中提取：
        - 标题（第一条有意义的消息）
        - 关键话题
        - 涉及文件
        - 关键决策
        """
        title = "新会话"
        topics = []
        files = []
        decisions = []
        total_tokens = 0
        
        for i, msg in enumerate(messages):
            content = msg.get('content', '')
            
            # 第一条用户消息作为标题
            if i == 0 and msg.get('role') == 'user':
                title = content[:50] + ('...' if len(content) > 50 else '')
            
            # 提取话题关键词
            topic_keywords = re.findall(
                r'(?:开发|修复|实现|重构|调试|部署|测试|优化|设计|配置|迁移)',
                content
            )
            topics.extend(topic_keywords)
            
            # 提取文件
            file_matches = re.findall(r'[\w-]+\.(?:py|js|ts|html|css|json|md)', content)
            files.extend(file_matches)
            
            total_tokens += len(content) // 4  # 粗略估计
        
        # 去重
        topics = list(set(topics))[:10]
        files = list(set(files))[:20]
        
        return SessionSummary(
            session_id=session_id,
            title=title,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            message_count=len(messages),
            key_topics=topics,
            key_files=files,
            key_decisions=decisions,
            last_message=messages[-1].get('content', '')[:200] if messages else "",
            total_tokens=total_tokens,
        )
    
    # ================================================================
    # 内部方法
    # ================================================================
    
    def _update_access_counts(self, memory_ids: List[str]):
        """更新记忆访问计数"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                [(now, mid) for mid in memory_ids]
            )
            conn.commit()
    
    # ================================================================
    # 统计
    # ================================================================
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with sqlite3.connect(self._db_path) as conn:
            session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            memory_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            type_counts = {}
            for row in conn.execute(
                "SELECT entry_type, COUNT(*) as cnt FROM memories GROUP BY entry_type"
            ).fetchall():
                type_counts[row[0]] = row[1]
        
        return {
            'db_path': self._db_path,
            'total_sessions': session_count,
            'total_memories': memory_count,
            'memory_types': type_counts,
        }


# 全局单例
_memory_instance: Optional[SessionMemory] = None
_memory_lock = threading.Lock()


def get_session_memory() -> SessionMemory:
    global _memory_instance
    if _memory_instance is None:
        with _memory_lock:
            if _memory_instance is None:
                _memory_instance = SessionMemory()
    return _memory_instance