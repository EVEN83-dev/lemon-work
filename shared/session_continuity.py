# -*- coding: utf-8 -*-
"""
会话持续性管理器 (SessionContinuity)
====================================
解决 MIMO Code 上下文限制问题：
1. 检测上下文长度，超阈值时主动切割会话
2. 保留旧会话的总结性日志（handoff 文档）
3. 新会话创建后，自动注入上一会话的总结作为起始上下文
4. 多个 agent 共享同一项目时，可互相调阅彼此的会话历史
5. 支持 24/48/72 小时长周期运作（自动会话迭代）

设计原则：
- 单次会话上下文 ≤ 80% 模型上下文窗口（保留 20% 给回复）
- 每次切割时生成 handoff 文档（最近 N 轮 + 任务清单 + 已完成项）
- 切割后立即创建新会话，让 agent "无缝接管"
- 所有会话历史以 JSON + Markdown 双格式持久化
"""
import os
import json
import time
import threading
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from collections import deque

from shared.handoff_quality import HandoffQualityEvaluator


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Message:
    """单条消息"""
    role: str  # 'user' / 'assistant' / 'system' / 'tool'
    content: str
    timestamp: float = field(default_factory=time.time)
    tokens: int = 0  # 估算 token 数


@dataclass
class SessionRecord:
    """单次会话记录"""
    session_id: str
    agent_id: str  # 归属 agent
    project_id: str  # 归属项目
    started_at: float
    ended_at: Optional[float] = None
    message_count: int = 0
    total_tokens: int = 0
    summary: str = ""  # 本次会话总结（handoff 用）
    handoff_doc: str = ""  # 移交文档（给下一会话）
    status: str = "active"  # active / closed / handed_off
    messages: List[Dict] = field(default_factory=list)  # 完整消息列表


# ============================================================
# 会话持续性管理器
# ============================================================

class SessionContinuity:
    """
    会话持续性管理器
    ================
    - 单 agent 视角：跟踪本 agent 的会话序列，自动切割 + 接管
    - 多 agent 视角：所有 agent 的会话历史可被互相调阅
    - 项目视角：每个项目维护会话时间线，支持长周期运作
    """

    # 默认配置
    DEFAULT_CONTEXT_WINDOW = 32768  # 假设模型 32K 上下文
    DEFAULT_SAFE_RATIO = 0.75  # 75% 阈值（保留 25% 给回复）
    DEFAULT_HANDOFF_RECENT_TURNS = 6  # handoff 文档保留最近 6 轮
    DEFAULT_MAX_SESSIONS_PER_AGENT = 50  # 每个 agent 最多保留 50 个历史会话

    def __init__(self, storage_dir: str, context_window: int = None, project_log=None):
        self._storage_dir = storage_dir
        self._context_window = context_window or self.DEFAULT_CONTEXT_WINDOW
        self._safe_threshold = int(self._context_window * self.DEFAULT_SAFE_RATIO)
        self._sessions: Dict[str, SessionRecord] = {}  # session_id -> record
        self._active_sessions: Dict[str, str] = {}  # agent_id -> active session_id
        self._lock = threading.RLock()
        self._project_log = project_log  # 可选的 ProjectLog 实例
        self._quality_evaluator = HandoffQualityEvaluator()
        self._ensure_storage()

        # 内存缓存：每个 agent 的当前 token 估算
        self._current_tokens: Dict[str, int] = {}

    def _ensure_storage(self):
        """确保存储目录存在"""
        os.makedirs(self._storage_dir, exist_ok=True)
        os.makedirs(os.path.join(self._storage_dir, 'sessions'), exist_ok=True)
        os.makedirs(os.path.join(self._storage_dir, 'handoffs'), exist_ok=True)

    # ============================================================
    # 会话管理 API
    # ============================================================

    def start_session(self, agent_id: str, project_id: str,
                      initial_context: str = "") -> SessionRecord:
        """启动新会话。如果有上一会话，自动注入 handoff 文档。"""
        with self._lock:
            # 检查是否有上一会话需要 handoff
            prev_session_id = self._active_sessions.get(agent_id)
            handoff_doc = ""
            if prev_session_id and prev_session_id in self._sessions:
                prev = self._sessions[prev_session_id]
                handoff_doc = self._generate_handoff_doc(prev)
                prev.handoff_doc = handoff_doc
                prev.status = "handed_off"
                prev.ended_at = time.time()
                self._persist_session(prev)

            # 创建新会话
            session_id = self._gen_session_id(agent_id, project_id)
            session = SessionRecord(
                session_id=session_id,
                agent_id=agent_id,
                project_id=project_id,
                started_at=time.time(),
            )

            # 注入 handoff 文档作为系统消息
            if handoff_doc:
                session.messages.append({
                    'role': 'system',
                    'content': f"# 上一会话移交文档\n\n{handoff_doc}",
                    'timestamp': time.time(),
                    'tokens': self._estimate_tokens(handoff_doc),
                })
                session.total_tokens += session.messages[0]['tokens']
            if initial_context:
                session.messages.append({
                    'role': 'system',
                    'content': initial_context,
                    'timestamp': time.time(),
                    'tokens': self._estimate_tokens(initial_context),
                })
                session.total_tokens += session.messages[-1]['tokens']

            session.message_count = len(session.messages)
            self._sessions[session_id] = session
            self._active_sessions[agent_id] = session_id
            self._current_tokens[agent_id] = session.total_tokens
            self._persist_session(session)
            return session

    def append_message(self, agent_id: str, role: str, content: str) -> Dict:
        """
        追加消息到当前会话。
        返回 {'action': 'continue' / 'handoff_required', 'session_id': ..., 'tokens': ...}
        """
        with self._lock:
            session_id = self._active_sessions.get(agent_id)
            if not session_id or session_id not in self._sessions:
                # 自动启动新会话
                session = self.start_session(agent_id, project_id="default")
                session_id = session.session_id

            session = self._sessions[session_id]
            tokens = self._estimate_tokens(content)
            session.messages.append({
                'role': role,
                'content': content,
                'timestamp': time.time(),
                'tokens': tokens,
            })
            session.message_count += 1
            session.total_tokens += tokens
            self._current_tokens[agent_id] = session.total_tokens

            # 检查是否需要 handoff
            action = 'continue'
            if session.total_tokens >= self._safe_threshold:
                action = 'handoff_required'

            self._persist_session(session)
            return {
                'action': action,
                'session_id': session_id,
                'tokens': session.total_tokens,
                'threshold': self._safe_threshold,
                'message_count': session.message_count,
            }

    def handoff_session(self, agent_id: str, summary: str = "") -> SessionRecord:
        """主动触发会话移交（切割）：关闭当前会话 + 启动新会话

        集成 HandoffQualityEvaluator：
        - handoff 完成后评估文档质量
        - 评分 < 60 时自动补充关键信息
        - 记录质量评分到 ProjectLog
        """
        with self._lock:
            session_id = self._active_sessions.get(agent_id)
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                session.summary = summary or f"会话 {session_id} 共 {session.message_count} 条消息"
                session.status = "handed_off"
                session.ended_at = time.time()
                session.handoff_doc = self._generate_handoff_doc(session)

                # ---- 质量评估 ----
                handoff_dict = self._session_to_handoff_dict(session)
                quality_report = self._quality_evaluator.evaluate(handoff_dict)

                # 评分 < 60 时自动补充
                if quality_report.score < 60:
                    enriched_dict = self._quality_evaluator.auto_enrich(handoff_dict)
                    session.handoff_doc = self._rebuild_handoff_md(session, enriched_dict)
                    quality_report.enriched_doc = enriched_dict

                # 记录质量评分到 ProjectLog
                if self._project_log is not None:
                    try:
                        from .project_log import EventType
                        self._project_log.log(
                            event_type=EventType.INFO,
                            project_id=session.project_id,
                            agent_id=agent_id,
                            session_id=session_id,
                            title=f"Handoff 质量评估: {quality_report.score}分 ({quality_report.level})",
                            description=f"缺失字段: {', '.join(quality_report.missing_fields) or '无'}; "
                                        f"薄弱环节: {'; '.join(quality_report.weak_areas) or '无'}",
                            metadata={
                                'quality_score': quality_report.score,
                                'quality_level': quality_report.level,
                                'missing_fields': quality_report.missing_fields,
                                'weak_areas': quality_report.weak_areas,
                                'was_enriched': quality_report.score < 60,
                            },
                        )
                    except Exception as e:
                        print(f"[SessionContinuity] 质量评分日志记录失败: {e}")

                self._persist_session(session)

            # 启动新会话（自动注入 handoff）
            project_id = self._sessions[session_id].project_id if session_id in self._sessions else "default"
            new_session = self.start_session(agent_id, project_id)
            return new_session

    def get_active_session(self, agent_id: str) -> Optional[SessionRecord]:
        """获取 agent 当前的活动会话"""
        with self._lock:
            sid = self._active_sessions.get(agent_id)
            return self._sessions.get(sid) if sid else None

    def get_session_history(self, agent_id: str, limit: int = 10) -> List[SessionRecord]:
        """获取 agent 最近 N 个会话（含已关闭的）"""
        with self._lock:
            records = [s for s in self._sessions.values() if s.agent_id == agent_id]
            records.sort(key=lambda x: x.started_at, reverse=True)
            return records[:limit]

    def get_project_sessions(self, project_id: str) -> List[SessionRecord]:
        """获取项目下所有 agent 的会话历史（用于跨 agent 调阅）"""
        with self._lock:
            return [s for s in self._sessions.values() if s.project_id == project_id]

    def load_handoff_for_agent(self, agent_id: str) -> str:
        """加载 agent 最近一次会话的 handoff 文档（用于新会话接管）"""
        with self._lock:
            history = self.get_session_history(agent_id, limit=2)
            if len(history) >= 2:
                # 第二近的就是上一个会话（最近的可能是当前活动）
                prev = history[1] if history[0].status == 'active' else history[0]
                return prev.handoff_doc or prev.summary
            return ""

    # ============================================================
    # 内部工具
    # ============================================================

    def _gen_session_id(self, agent_id: str, project_id: str) -> str:
        """生成会话 ID"""
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        hash_suffix = hashlib.md5(f"{agent_id}{project_id}{ts}{time.time()}".encode()).hexdigest()[:6]
        return f"sess_{agent_id}_{ts}_{hash_suffix}"

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数（粗略：1 中文字 ≈ 2 token，1 英文字 ≈ 0.25 token）"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return chinese_chars * 2 + other_chars // 4

    def _generate_handoff_doc(self, session: SessionRecord) -> str:
        """生成 handoff 文档（移交文档）"""
        recent_msgs = session.messages[-self.DEFAULT_HANDOFF_RECENT_TURNS * 2:]  # 最近 N 轮（user+assistant 各一条）

        doc_parts = [
            f"# 会话移交文档",
            f"",
            f"- **会话ID**: {session.session_id}",
            f"- **Agent**: {session.agent_id}",
            f"- **项目**: {session.project_id}",
            f"- **开始时间**: {datetime.fromtimestamp(session.started_at).strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **结束时间**: {datetime.fromtimestamp(session.ended_at or time.time()).strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **消息数**: {session.message_count}",
            f"- **总Token**: {session.total_tokens}",
            f"- **总结**: {session.summary or '（无总结）'}",
            f"",
            f"## 最近对话（最近 {self.DEFAULT_HANDOFF_RECENT_TURNS} 轮）",
            f"",
        ]

        for msg in recent_msgs:
            role_cn = {'user': '👤用户', 'assistant': '🤖助手', 'system': '⚙系统', 'tool': '🔧工具'}.get(msg['role'], msg['role'])
            content_preview = msg['content'][:500] + ('...' if len(msg['content']) > 500 else '')
            doc_parts.append(f"### {role_cn}")
            doc_parts.append(f"```\n{content_preview}\n```")
            doc_parts.append("")

        doc_parts.extend([
            f"## 待办事项（请在新会话中继续）",
            f"",
            f"1. 继续上一会话未完成的任务",
            f"2. 保持上下文一致性",
            f"3. 引用本移交文档中的关键信息",
            f"",
            f"---",
            f"*本文档由 SessionContinuity 自动生成于 {datetime.now().isoformat()}*",
        ])

        return "\n".join(doc_parts)

    def _session_to_handoff_dict(self, session: SessionRecord) -> dict:
        """将 SessionRecord 转换为结构化 handoff 字典（供质量评估器使用）"""
        recent_msgs = session.messages[-self.DEFAULT_HANDOFF_RECENT_TURNS * 2:]
        return {
            "agent_id": session.agent_id,
            "session_id": session.session_id,
            "summary": session.summary or "",
            "timestamp": session.started_at,
            "project_id": session.project_id,
            "tasks": [],      # SessionRecord 无此字段，由评估器标记缺失
            "completed": [],
            "pending": [],
            "technical_decisions": [],
            "file_changes": [],
            "api_usage": [],
            "recent_messages": [
                {"role": m["role"], "content": m["content"][:200]}
                for m in recent_msgs
            ],
            "next_steps": [],
        }

    def _rebuild_handoff_md(self, session: SessionRecord, enriched_dict: dict) -> str:
        """根据补充后的结构化字典重建 handoff Markdown 文档"""
        doc_parts = [
            f"# 会话移交文档",
            f"",
            f"- **会话ID**: {session.session_id}",
            f"- **Agent**: {session.agent_id}",
            f"- **项目**: {session.project_id}",
            f"- **开始时间**: {datetime.fromtimestamp(session.started_at).strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **结束时间**: {datetime.fromtimestamp(session.ended_at or time.time()).strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **消息数**: {session.message_count}",
            f"- **总Token**: {session.total_tokens}",
            f"- **总结**: {session.summary or '（无总结）'}",
            f"",
        ]

        # 任务清单（从补充后的数据生成）
        tasks = enriched_dict.get("tasks", [])
        completed = enriched_dict.get("completed", [])
        pending = enriched_dict.get("pending", [])

        if tasks or completed or pending:
            doc_parts.append("## 任务清单")
            doc_parts.append("")
            if tasks and tasks != ["（未记录具体任务）"]:
                doc_parts.append("### 所有任务")
                for t in tasks:
                    doc_parts.append(f"- {t}" if isinstance(t, str) else f"- {t.get('name', t)}")
                doc_parts.append("")
            if completed:
                doc_parts.append("### 已完成")
                for c in completed:
                    doc_parts.append(f"- ✅ {c}" if isinstance(c, str) else f"- ✅ {c.get('name', c)}")
                doc_parts.append("")
            if pending:
                doc_parts.append("### 待办")
                for p in pending:
                    doc_parts.append(f"- ⏳ {p}" if isinstance(p, str) else f"- ⏳ {p.get('name', p)}")
                doc_parts.append("")

        # 上下文信息
        tech_decisions = enriched_dict.get("technical_decisions", [])
        file_changes = enriched_dict.get("file_changes", [])
        api_usage = enriched_dict.get("api_usage", [])

        if tech_decisions or file_changes or api_usage:
            doc_parts.append("## 上下文信息")
            doc_parts.append("")
            if tech_decisions and tech_decisions != ["未记录"]:
                doc_parts.append("### 技术决策")
                for d in tech_decisions:
                    doc_parts.append(f"- {d}" if isinstance(d, str) else f"- {d}")
                doc_parts.append("")
            if file_changes:
                doc_parts.append("### 文件变更")
                for fc in file_changes:
                    doc_parts.append(f"- {fc}" if isinstance(fc, str) else f"- {fc}")
                doc_parts.append("")
            if api_usage:
                doc_parts.append("### API 使用")
                for a in api_usage:
                    doc_parts.append(f"- {a}" if isinstance(a, str) else f"- {a}")
                doc_parts.append("")

        # 最近对话
        recent_messages = enriched_dict.get("recent_messages", [])
        if recent_messages:
            doc_parts.append(f"## 最近对话（最近 {self.DEFAULT_HANDOFF_RECENT_TURNS} 轮）")
            doc_parts.append("")
            for msg in recent_messages:
                if isinstance(msg, dict):
                    role_cn = {'user': '👤用户', 'assistant': '🤖助手', 'system': '⚙系统', 'tool': '🔧工具'}.get(msg.get('role', ''), msg.get('role', ''))
                    content_preview = (msg.get('content', '') or '')[:500]
                    content_preview += '...' if len(msg.get('content', '') or '') > 500 else ''
                    doc_parts.append(f"### {role_cn}")
                    doc_parts.append(f"```\n{content_preview}\n```")
                    doc_parts.append("")

        # 接班指引
        next_steps = enriched_dict.get("next_steps", [])
        if next_steps:
            doc_parts.append("## 待办事项（请在新会话中继续）")
            doc_parts.append("")
            for i, step in enumerate(next_steps, 1):
                doc_parts.append(f"{i}. {step}")
            doc_parts.append("")

        doc_parts.extend([
            "",
            "---",
            f"*本文档由 SessionContinuity 自动生成于 {datetime.now().isoformat()}*",
            f"*（经 HandoffQualityEvaluator 自动补充）*",
        ])

        return "\n".join(doc_parts)

    def _persist_session(self, session: SessionRecord):
        """持久化会话到磁盘（JSON 格式）"""
        try:
            filepath = os.path.join(self._storage_dir, 'sessions', f"{session.session_id}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(asdict(session), f, ensure_ascii=False, indent=2)

            # 同时写一份 handoff markdown（便于人类查阅）
            if session.handoff_doc:
                md_path = os.path.join(self._storage_dir, 'handoffs', f"{session.session_id}_handoff.md")
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(session.handoff_doc)
        except Exception as e:
            print(f"[SessionContinuity] persist 错误: {e}")

    # ============================================================
    # 监控 API
    # ============================================================

    def get_agent_status(self, agent_id: str) -> Dict:
        """获取 agent 的会话状态"""
        with self._lock:
            session = self.get_active_session(agent_id)
            history = self.get_session_history(agent_id, limit=50)
            return {
                'agent_id': agent_id,
                'active_session': session.session_id if session else None,
                'current_tokens': self._current_tokens.get(agent_id, 0),
                'safe_threshold': self._safe_threshold,
                'token_usage_percent': (self._current_tokens.get(agent_id, 0) * 100 // self._safe_threshold) if self._safe_threshold else 0,
                'total_sessions': len(history),
                'need_handoff': session and session.total_tokens >= self._safe_threshold,
            }

    def get_all_agents_status(self) -> List[Dict]:
        """获取所有 agent 的会话状态"""
        with self._lock:
            agent_ids = set(self._active_sessions.keys()) | set(self._current_tokens.keys())
            return [self.get_agent_status(aid) for aid in agent_ids]

    def set_context_window(self, window_size: int):
        """动态调整上下文窗口大小（用于引擎切换）"""
        with self._lock:
            self._context_window = window_size
            self._safe_threshold = int(window_size * self.DEFAULT_SAFE_RATIO)

    # ============================================================
    # 跨 Agent 会话查询 API
    # ============================================================

    def query_sessions(self,
                       project_id: str = None,
                       agent_id: str = None,
                       status: str = None,
                       time_start: float = None,
                       time_end: float = None,
                       keyword: str = None,
                       limit: int = 50,
                       offset: int = 0) -> Dict:
        """
        跨 Agent 会话查询接口

        支持多维度筛选和分页：
        - 按 project_id 筛选
        - 按 agent_id 筛选
        - 按 status 筛选 (active / closed / handed_off)
        - 按时间范围筛选
        - 按关键词搜索（在 summary 和 messages 中搜索）
        - 分页 (limit + offset)

        Args:
            project_id: 项目 ID（None=不限）
            agent_id: Agent ID（None=不限）
            status: 会话状态（None=不限）
            time_start: 起始时间戳（None=不限）
            time_end: 结束时间戳（None=不限）
            keyword: 搜索关键词（None=不限）
            limit: 返回数量上限
            offset: 偏移量

        Returns:
            {
                "total": int,       # 总匹配数
                "returned": int,    # 本页返回数
                "offset": int,
                "sessions": [...],  # 会话记录列表
            }
        """
        with self._lock:
            # 筛选
            results = []
            for session in self._sessions.values():
                # project_id 筛选
                if project_id and session.project_id != project_id:
                    continue
                # agent_id 筛选
                if agent_id and session.agent_id != agent_id:
                    continue
                # status 筛选
                if status and session.status != status:
                    continue
                # 时间范围筛选
                if time_start and session.started_at < time_start:
                    continue
                if time_end and session.started_at > time_end:
                    continue
                # 关键词搜索
                if keyword:
                    keyword_lower = keyword.lower()
                    found = False
                    # 在 summary 中搜索
                    if keyword_lower in (session.summary or "").lower():
                        found = True
                    # 在 messages 中搜索
                    if not found:
                        for msg in session.messages:
                            content = msg.get("content", "")
                            if keyword_lower in content.lower():
                                found = True
                                break
                    # 在 handoff_doc 中搜索
                    if not found and keyword_lower in (session.handoff_doc or "").lower():
                        found = True
                    if not found:
                        continue

                results.append(session)

            # 按时间降序排列
            results.sort(key=lambda s: s.started_at, reverse=True)

            total = len(results)
            page = results[offset:offset + limit]

            # 序列化会话记录
            session_list = []
            for s in page:
                session_list.append({
                    "session_id": s.session_id,
                    "agent_id": s.agent_id,
                    "project_id": s.project_id,
                    "started_at": datetime.fromtimestamp(s.started_at).strftime('%Y-%m-%d %H:%M:%S'),
                    "ended_at": datetime.fromtimestamp(s.ended_at).strftime('%Y-%m-%d %H:%M:%S') if s.ended_at else None,
                    "message_count": s.message_count,
                    "total_tokens": s.total_tokens,
                    "status": s.status,
                    "summary": s.summary[:200] if s.summary else "",
                    "has_handoff": bool(s.handoff_doc),
                })

            return {
                "total": total,
                "returned": len(session_list),
                "offset": offset,
                "sessions": session_list,
            }

    def query_session_detail(self, session_id: str,
                              include_messages: bool = False,
                              message_limit: int = 20) -> Optional[Dict]:
        """
        查询单个会话详情

        Args:
            session_id: 会话 ID
            include_messages: 是否包含消息内容
            message_limit: 消息数量上限

        Returns:
            会话详情字典，或 None
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            detail = {
                "session_id": session.session_id,
                "agent_id": session.agent_id,
                "project_id": session.project_id,
                "started_at": datetime.fromtimestamp(session.started_at).strftime('%Y-%m-%d %H:%M:%S'),
                "ended_at": datetime.fromtimestamp(session.ended_at).strftime('%Y-%m-%d %H:%M:%S') if session.ended_at else None,
                "message_count": session.message_count,
                "total_tokens": session.total_tokens,
                "status": session.status,
                "summary": session.summary,
                "handoff_doc": session.handoff_doc[:500] if session.handoff_doc else None,
            }

            if include_messages:
                messages = session.messages[-message_limit:]
                detail["messages"] = [
                    {
                        "role": m.get("role", ""),
                        "content": m.get("content", "")[:1000],
                        "timestamp": datetime.fromtimestamp(m.get("timestamp", 0)).strftime('%Y-%m-%d %H:%M:%S'),
                        "tokens": m.get("tokens", 0),
                    }
                    for m in messages
                ]

            return detail

    def get_session_statistics(self, project_id: str = None) -> Dict:
        """
        获取会话统计信息

        Args:
            project_id: 项目 ID（None=全局）

        Returns:
            {
                "total_sessions": int,
                "active_sessions": int,
                "total_messages": int,
                "total_tokens": int,
                "by_agent": {...},
                "by_status": {...},
                "avg_session_length": float,
            }
        """
        with self._lock:
            sessions = list(self._sessions.values())
            if project_id:
                sessions = [s for s in sessions if s.project_id == project_id]

            total_sessions = len(sessions)
            active_sessions = sum(1 for s in sessions if s.status == "active")
            total_messages = sum(s.message_count for s in sessions)
            total_tokens = sum(s.total_tokens for s in sessions)

            # 按 agent 分组
            by_agent: Dict[str, Dict] = {}
            for s in sessions:
                aid = s.agent_id
                if aid not in by_agent:
                    by_agent[aid] = {"sessions": 0, "messages": 0, "tokens": 0}
                by_agent[aid]["sessions"] += 1
                by_agent[aid]["messages"] += s.message_count
                by_agent[aid]["tokens"] += s.total_tokens

            # 按状态分组
            by_status: Dict[str, int] = {}
            for s in sessions:
                by_status[s.status] = by_status.get(s.status, 0) + 1

            # 平均会话长度
            avg_length = (total_messages / total_sessions) if total_sessions > 0 else 0.0

            return {
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
                "total_messages": total_messages,
                "total_tokens": total_tokens,
                "by_agent": by_agent,
                "by_status": by_status,
                "avg_session_length": round(avg_length, 1),
            }

    def get_cross_agent_context(self, project_id: str,
                                 requesting_agent: str,
                                 recent_limit: int = 5) -> str:
        """
        获取跨 Agent 上下文摘要

        当某个 Agent 需要了解其他 Agent 的工作进展时调用。

        Args:
            project_id: 项目 ID
            requesting_agent: 请求者的 agent_id
            recent_limit: 每个其他 Agent 最多返回的最近会话数

        Returns:
            Markdown 格式的跨 Agent 上下文摘要
        """
        with self._lock:
            other_sessions = [
                s for s in self._sessions.values()
                if s.project_id == project_id and s.agent_id != requesting_agent
            ]

            if not other_sessions:
                return f"# 跨 Agent 上下文\n\n项目 {project_id} 暂无其他 Agent 的会话记录。\n"

            # 按 agent 分组
            by_agent: Dict[str, List] = {}
            for s in other_sessions:
                by_agent.setdefault(s.agent_id, []).append(s)

            lines = [
                f"# 跨 Agent 上下文摘要",
                f"",
                f"项目: {project_id}",
                f"请求者: {requesting_agent}",
                f"其他 Agent 数: {len(by_agent)}",
                f"",
            ]

            for aid, sessions in by_agent.items():
                sessions.sort(key=lambda s: s.started_at, reverse=True)
                recent = sessions[:recent_limit]

                lines.append(f"## Agent: {aid}")
                lines.append(f"总会话数: {len(sessions)}")
                lines.append(f"")

                for s in recent:
                    start = datetime.fromtimestamp(s.started_at).strftime('%Y-%m-%d %H:%M')
                    lines.append(f"- **{s.session_id}** ({s.status})")
                    lines.append(f"  开始: {start}, 消息数: {s.message_count}, Token: {s.total_tokens}")
                    if s.summary:
                        lines.append(f"  总结: {s.summary[:200]}")
                    lines.append("")

            lines.extend([
                "---",
                f"*由 SessionContinuity 自动生成于 {datetime.now().isoformat()}*",
            ])

            return "\n".join(lines)
