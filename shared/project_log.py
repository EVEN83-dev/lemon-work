# -*- coding: utf-8 -*-
"""
项目日志持久化机制 (ProjectLog)
==============================
以文字形式保留项目整个生命周期的记录：
1. 项目立项 / 启动 / 暂停 / 恢复 / 完成 的事件流
2. 每个 agent 的任务分配 / 进行中 / 完成事件
3. 会话切割 / 接管事件（与 SessionContinuity 联动）
4. 多 agent 协同事件（任务转发、结果汇总）
5. 错误与异常事件
6. 阶段性总结（每 N 小时自动生成）

输出：
- Markdown 主日志（人类可读，按时间线）
- JSON 结构化日志（机器可读，便于 agent 调阅）
- 阶段性总结文档（每 24h 生成一次）
"""
import os
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from enum import Enum


class EventType(Enum):
    """项目事件类型"""
    PROJECT_INIT = "project_init"           # 项目立项
    PROJECT_START = "project_start"         # 项目启动
    PROJECT_PAUSE = "project_pause"         # 项目暂停
    PROJECT_RESUME = "project_resume"       # 项目恢复
    PROJECT_COMPLETE = "project_complete"   # 项目完成
    PROJECT_ABORT = "project_abort"         # 项目中止

    AGENT_ASSIGNED = "agent_assigned"       # agent 被分配任务
    AGENT_STARTED = "agent_started"         # agent 开始执行
    AGENT_PROGRESS = "agent_progress"       # agent 进度更新
    AGENT_COMPLETED = "agent_completed"     # agent 完成任务
    AGENT_FAILED = "agent_failed"           # agent 任务失败
    AGENT_IDLE = "agent_idle"               # agent 空闲

    SESSION_CREATED = "session_created"     # 新会话创建
    SESSION_HANDED_OFF = "session_handed_off"  # 会话移交
    SESSION_RESUMED = "session_resumed"     # 会话恢复

    TASK_DISPATCHED = "task_dispatched"     # 任务派发
    TASK_FORWARDED = "task_forwarded"       # 任务转发
    TASK_AGGRAGATED = "task_aggregated"     # 结果聚合

    ERROR = "error"                         # 错误
    WARNING = "warning"                     # 警告
    INFO = "info"                           # 信息

    MILESTONE = "milestone"                 # 里程碑
    PHASE_SUMMARY = "phase_summary"         # 阶段总结


@dataclass
class ProjectEvent:
    """项目事件"""
    event_id: str
    event_type: str  # EventType.value
    timestamp: float
    project_id: str
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    title: str = ""
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProjectLog:
    """
    项目日志持久化
    ==============
    - 单项目视角：记录项目的所有事件，按时间线存储
    - 多项目视角：可同时管理多个项目的日志
    - 检索：按时间 / 类型 / agent / 任务 ID 检索
    - 总结：阶段性自动生成项目总结
    """

    # 阶段总结间隔（秒）
    PHASE_SUMMARY_INTERVAL = 24 * 3600  # 24小时

    def __init__(self, storage_dir: str):
        self._storage_dir = storage_dir
        self._events: List[ProjectEvent] = []
        self._events_by_project: Dict[str, List[ProjectEvent]] = {}
        self._lock = threading.RLock()
        self._last_summary_time: Dict[str, float] = {}  # project_id -> last summary timestamp
        self._ensure_storage()
        self._load_existing_logs()

    def _ensure_storage(self):
        os.makedirs(self._storage_dir, exist_ok=True)
        os.makedirs(os.path.join(self._storage_dir, 'projects'), exist_ok=True)
        os.makedirs(os.path.join(self._storage_dir, 'summaries'), exist_ok=True)

    def _load_existing_logs(self):
        """启动时加载已有日志（用于长周期运作的恢复）"""
        projects_dir = os.path.join(self._storage_dir, 'projects')
        if not os.path.exists(projects_dir):
            return
        for fname in os.listdir(projects_dir):
            if not fname.endswith('_events.json'):
                continue
            try:
                fpath = os.path.join(projects_dir, fname)
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                project_id = data.get('project_id', '')
                events_data = data.get('events', [])
                events = [ProjectEvent(**e) for e in events_data]
                self._events_by_project[project_id] = events
                self._events.extend(events)
                # 找到最近一次 phase_summary 的时间
                for e in reversed(events):
                    if e.event_type == EventType.PHASE_SUMMARY.value:
                        self._last_summary_time[project_id] = e.timestamp
                        break
                print(f"[ProjectLog] 加载项目 {project_id} 的 {len(events)} 条历史事件")
            except Exception as e:
                print(f"[ProjectLog] 加载 {fname} 失败: {e}")

    # ============================================================
    # 事件记录 API
    # ============================================================

    def log(self, event_type: EventType, project_id: str,
            agent_id: str = None, task_id: str = None, session_id: str = None,
            title: str = "", description: str = "", metadata: Dict = None) -> ProjectEvent:
        """记录一条项目事件"""
        with self._lock:
            event = ProjectEvent(
                event_id=self._gen_event_id(),
                event_type=event_type.value,
                timestamp=time.time(),
                project_id=project_id,
                agent_id=agent_id,
                task_id=task_id,
                session_id=session_id,
                title=title,
                description=description,
                metadata=metadata or {},
            )
            self._events.append(event)
            self._events_by_project.setdefault(project_id, []).append(event)
            self._persist_event(event)

            # 检查是否需要生成阶段性总结（避免对 PHASE_SUMMARY 事件本身递归）
            if event_type != EventType.PHASE_SUMMARY:
                self._check_phase_summary(project_id)

            return event

    def log_project_init(self, project_id: str, name: str, description: str = ""):
        return self.log(EventType.PROJECT_INIT, project_id,
                        title=f"项目立项: {name}", description=description,
                        metadata={'name': name})

    def log_project_start(self, project_id: str):
        return self.log(EventType.PROJECT_START, project_id, title="项目启动")

    def log_project_pause(self, project_id: str, reason: str = ""):
        return self.log(EventType.PROJECT_PAUSE, project_id,
                        title="项目暂停", description=reason)

    def log_project_resume(self, project_id: str):
        return self.log(EventType.PROJECT_RESUME, project_id, title="项目恢复")

    def log_project_complete(self, project_id: str, summary: str = ""):
        return self.log(EventType.PROJECT_COMPLETE, project_id,
                        title="项目完成", description=summary)

    def log_agent_assigned(self, project_id: str, agent_id: str,
                            task_id: str, task_desc: str):
        return self.log(EventType.AGENT_ASSIGNED, project_id,
                        agent_id=agent_id, task_id=task_id,
                        title=f"任务分配给 {agent_id}", description=task_desc)

    def log_agent_started(self, project_id: str, agent_id: str, task_id: str):
        return self.log(EventType.AGENT_STARTED, project_id,
                        agent_id=agent_id, task_id=task_id,
                        title=f"{agent_id} 开始执行任务")

    def log_agent_progress(self, project_id: str, agent_id: str,
                            task_id: str, progress: int, note: str = ""):
        return self.log(EventType.AGENT_PROGRESS, project_id,
                        agent_id=agent_id, task_id=task_id,
                        title=f"{agent_id} 进度 {progress}%",
                        description=note,
                        metadata={'progress': progress})

    def log_agent_completed(self, project_id: str, agent_id: str,
                              task_id: str, result: str = ""):
        return self.log(EventType.AGENT_COMPLETED, project_id,
                        agent_id=agent_id, task_id=task_id,
                        title=f"{agent_id} 完成任务",
                        description=result[:500])

    def log_agent_failed(self, project_id: str, agent_id: str,
                          task_id: str, error: str):
        return self.log(EventType.AGENT_FAILED, project_id,
                        agent_id=agent_id, task_id=task_id,
                        title=f"{agent_id} 任务失败",
                        description=error)

    def log_session_created(self, project_id: str, agent_id: str, session_id: str):
        return self.log(EventType.SESSION_CREATED, project_id,
                        agent_id=agent_id, session_id=session_id,
                        title=f"{agent_id} 创建新会话 {session_id}")

    def log_session_handed_off(self, project_id: str, agent_id: str,
                                 old_session: str, new_session: str, reason: str = ""):
        return self.log(EventType.SESSION_HANDED_OFF, project_id,
                        agent_id=agent_id, session_id=new_session,
                        title=f"{agent_id} 会话移交: {old_session} → {new_session}",
                        description=reason,
                        metadata={'old_session': old_session, 'new_session': new_session})

    def log_task_dispatched(self, project_id: str, from_agent: str,
                              to_agent: str, task_id: str, task_desc: str):
        return self.log(EventType.TASK_DISPATCHED, project_id,
                        agent_id=from_agent, task_id=task_id,
                        title=f"任务派发: {from_agent} → {to_agent}",
                        description=task_desc,
                        metadata={'from': from_agent, 'to': to_agent})

    def log_milestone(self, project_id: str, milestone: str, description: str = ""):
        return self.log(EventType.MILESTONE, project_id,
                        title=f"里程碑: {milestone}", description=description)

    def log_error(self, project_id: str, error: str, agent_id: str = None):
        return self.log(EventType.ERROR, project_id, agent_id=agent_id,
                        title="错误", description=error)

    # ============================================================
    # 检索 API
    # ============================================================

    def get_project_events(self, project_id: str,
                            event_type: EventType = None,
                            agent_id: str = None,
                            since: float = None,
                            limit: int = 100) -> List[ProjectEvent]:
        """检索项目事件"""
        with self._lock:
            events = self._events_by_project.get(project_id, [])
            filtered = []
            for e in reversed(events):  # 从最新开始
                if event_type and e.event_type != event_type.value:
                    continue
                if agent_id and e.agent_id != agent_id:
                    continue
                if since and e.timestamp < since:
                    continue
                filtered.append(e)
                if len(filtered) >= limit:
                    break
            return list(reversed(filtered))  # 按时间正序返回

    def get_agent_history(self, project_id: str, agent_id: str,
                           limit: int = 50) -> List[ProjectEvent]:
        """获取 agent 在项目中的所有事件（用于 agent 接管时调阅）"""
        return self.get_project_events(project_id, agent_id=agent_id, limit=limit)

    def get_recent_summary(self, project_id: str, hours: int = 24) -> str:
        """获取项目最近 N 小时的文字总结（用于新 agent 接管时阅读）"""
        with self._lock:
            since = time.time() - hours * 3600
            events = self.get_project_events(project_id, since=since, limit=500)

            if not events:
                return f"# 项目 {project_id} 最近 {hours} 小时无事件记录"

            lines = [
                f"# 项目 {project_id} 最近 {hours} 小时总结",
                f"",
                f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"事件总数: {len(events)}",
                f"",
                f"## 事件时间线",
                f"",
            ]

            current_date = ""
            for e in events:
                dt = datetime.fromtimestamp(e.timestamp)
                date_str = dt.strftime('%Y-%m-%d')
                time_str = dt.strftime('%H:%M:%S')
                if date_str != current_date:
                    lines.append(f"### {date_str}")
                    lines.append("")
                    current_date = date_str

                emoji = self._event_emoji(e.event_type)
                agent_info = f" [{e.agent_id}]" if e.agent_id else ""
                lines.append(f"- {time_str} {emoji} {e.title}{agent_info}")
                if e.description:
                    desc_preview = e.description[:200] + ('...' if len(e.description) > 200 else '')
                    lines.append(f"  > {desc_preview}")

            lines.extend([
                f"",
                f"## 统计",
                f"",
            ])
            type_counts = {}
            for e in events:
                type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1
            for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
                lines.append(f"- {t}: {c} 次")

            return "\n".join(lines)

    def _event_emoji(self, event_type: str) -> str:
        emoji_map = {
            EventType.PROJECT_INIT.value: "🚀",
            EventType.PROJECT_START.value: "▶",
            EventType.PROJECT_PAUSE.value: "⏸",
            EventType.PROJECT_RESUME.value: "⏵",
            EventType.PROJECT_COMPLETE.value: "✅",
            EventType.PROJECT_ABORT.value: "❌",
            EventType.AGENT_ASSIGNED.value: "📋",
            EventType.AGENT_STARTED.value: "🏃",
            EventType.AGENT_PROGRESS.value: "📊",
            EventType.AGENT_COMPLETED.value: "✓",
            EventType.AGENT_FAILED.value: "✗",
            EventType.AGENT_IDLE.value: "💤",
            EventType.SESSION_CREATED.value: "📝",
            EventType.SESSION_HANDED_OFF.value: "🔄",
            EventType.SESSION_RESUMED.value: "📂",
            EventType.TASK_DISPATCHED.value: "📤",
            EventType.TASK_FORWARDED.value: "↪",
            EventType.TASK_AGGRAGATED.value: "📥",
            EventType.ERROR.value: "🔥",
            EventType.WARNING.value: "⚠",
            EventType.INFO.value: "ℹ",
            EventType.MILESTONE.value: "🎯",
            EventType.PHASE_SUMMARY.value: "📑",
        }
        return emoji_map.get(event_type, "•")

    # ============================================================
    # 阶段性总结
    # ============================================================

    def _check_phase_summary(self, project_id: str):
        """检查是否需要生成阶段性总结"""
        # 首次记录该项目时，跳过（仅初始化时间戳，不立即生成总结）
        if project_id not in self._last_summary_time:
            self._last_summary_time[project_id] = time.time()
            return
        last = self._last_summary_time.get(project_id, 0)
        if time.time() - last < self.PHASE_SUMMARY_INTERVAL:
            return

        self._generate_phase_summary(project_id)

    def _generate_phase_summary(self, project_id: str) -> str:
        """生成阶段性总结文档"""
        summary = self.get_recent_summary(project_id, hours=int(self.PHASE_SUMMARY_INTERVAL / 3600))

        # 记录总结事件
        event = self.log(EventType.PHASE_SUMMARY, project_id,
                          title=f"阶段总结 ({datetime.now().strftime('%Y-%m-%d')})",
                          description=summary[:500])
        self._last_summary_time[project_id] = event.timestamp

        # 持久化到 summaries 目录
        try:
            summary_path = os.path.join(self._storage_dir, 'summaries',
                                          f"{project_id}_{int(event.timestamp)}.md")
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(summary)
        except Exception as e:
            print(f"[ProjectLog] 阶段总结持久化失败: {e}")

        return summary

    # ============================================================
    # 持久化
    # ============================================================

    def _gen_event_id(self) -> str:
        return f"evt_{int(time.time()*1000)}_{id(self) % 10000}"

    def _persist_event(self, event: ProjectEvent):
        """持久化单个事件（追加到项目事件文件）"""
        try:
            projects_dir = os.path.join(self._storage_dir, 'projects')
            os.makedirs(projects_dir, exist_ok=True)
            filepath = os.path.join(projects_dir, f"{event.project_id}_events.json")

            # 读取现有
            data = {'project_id': event.project_id, 'events': []}
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    pass

            data['events'].append(asdict(event))
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ProjectLog] persist 错误: {e}")

    # ============================================================
    # 导出 API
    # ============================================================

    def export_markdown(self, project_id: str, output_path: str = None) -> str:
        """导出整个项目的 Markdown 日志（人类可读）"""
        with self._lock:
            events = self._events_by_project.get(project_id, [])
            if not events:
                return f"# 项目 {project_id} 无事件记录"

            lines = [
                f"# 项目日志: {project_id}",
                f"",
                f"**总事件数**: {len(events)}",
                f"**起始时间**: {datetime.fromtimestamp(events[0].timestamp).strftime('%Y-%m-%d %H:%M:%S')}",
                f"**最近时间**: {datetime.fromtimestamp(events[-1].timestamp).strftime('%Y-%m-%d %H:%M:%S')}",
                f"",
                f"---",
                f"",
                f"## 完整事件时间线",
                f"",
            ]

            current_date = ""
            for e in events:
                dt = datetime.fromtimestamp(e.timestamp)
                date_str = dt.strftime('%Y-%m-%d')
                time_str = dt.strftime('%H:%M:%S')
                if date_str != current_date:
                    lines.append(f"### 📅 {date_str}")
                    lines.append("")
                    current_date = date_str

                emoji = self._event_emoji(e.event_type)
                agent_info = f" `{e.agent_id}`" if e.agent_id else ""
                task_info = f" `{e.task_id}`" if e.task_id else ""
                lines.append(f"- **{time_str}** {emoji} {e.title}{agent_info}{task_info}")
                if e.description:
                    lines.append(f"  > {e.description}")
                lines.append("")

            content = "\n".join(lines)
            if output_path:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            return content
