# -*- coding: utf-8 -*-
"""
Skill Visualizer — 右侧面板 Skill 可视化仪表盘状态管理
========================================================
为前端右侧面板提供 Skill 执行过程的可视化数据，
包括 Skill 调用记录、任务进度、思考过程、文件变更等。

核心能力：
- Skill 调用生命周期管理（启动 → 完成/失败/取消）
- 任务进度追踪（多子任务支持）
- 思考过程记录（working/thinking 双状态）
- 文件变更汇总（diff 追踪）
- 全局状态快照（get_dashboard_state）
- 事件回调系统（桥接前端推送更新）

使用方式：
    from skill_visualizer import get_skill_visualizer

    viz = get_skill_visualizer()
    record_id = viz.start_skill_call("sk1", "python_executor", {...})
    viz.complete_skill_call(record_id, "执行成功")

    viz.add_task("task1", "重构用户模块")
    viz.update_task("task1", progress=0.5)

    viz.add_thinking("正在分析代码结构...", is_working=True)

    state = viz.get_dashboard_state()
"""

import os
import time
import uuid
import threading
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ==================== 日志模块 ====================

try:
    from shared.logger import get_logger
    _logger = get_logger("skill_visualizer")
except ImportError:
    import logging
    _logger = logging.getLogger("skill_visualizer")
    _logger.setLevel(logging.DEBUG)
    if not _logger.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        _logger.addHandler(_h)

# ==================== 技能元数据（可选集成） ====================

try:
    from .skills_registry import get_skills_registry
    _skills_registry = get_skills_registry()
except Exception:
    _skills_registry = None


# ==================== 枚举定义 ====================

class SkillStatus(Enum):
    """Skill 执行状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ==================== 数据模型 ====================

@dataclass
class SkillCallRecord:
    """Skill 调用记录"""
    skill_id: str                        # 调用唯一标识
    skill_name: str                      # 技能名称
    status: SkillStatus                  # 当前状态
    started_at: str                      # 启动时间（ISO 格式）
    completed_at: Optional[str] = None   # 完成时间
    duration_ms: float = 0.0             # 执行耗时（毫秒）
    input_params: Dict = field(default_factory=dict)   # 输入参数
    output_summary: str = ""             # 输出摘要（前200字符）
    error_message: Optional[str] = None  # 错误信息
    icon_svg: Optional[str] = None       # 技能 SVG 图标路径数据

    def to_dict(self) -> Dict:
        """转为可序列化字典"""
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "input_params": self.input_params,
            "output_summary": self.output_summary,
            "error_message": self.error_message,
            "icon_svg": self.icon_svg,
        }


@dataclass
class TaskRecord:
    """任务记录"""
    task_id: str                         # 任务唯一标识
    title: str                           # 任务标题
    status: str = "pending"              # 状态：pending/in_progress/completed/failed
    progress: float = 0.0                # 进度 0.0-1.0
    sub_tasks: List[Dict] = field(default_factory=list)  # 子任务 [{title, status, progress}]
    created_at: str = ""                 # 创建时间
    completed_at: Optional[str] = None   # 完成时间

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "sub_tasks": self.sub_tasks,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


@dataclass
class FileChange:
    """文件变更记录"""
    file_path: str                       # 文件路径
    lines_added: int = 0                 # 新增行数
    lines_deleted: int = 0               # 删除行数
    diff_content: Optional[str] = None   # unified diff 文本
    change_type: str = "modified"        # 变更类型：modified/created/deleted

    def to_dict(self) -> Dict:
        return {
            "file_path": self.file_path,
            "lines_added": self.lines_added,
            "lines_deleted": self.lines_deleted,
            "diff_content": self.diff_content,
            "change_type": self.change_type,
        }


@dataclass
class ThinkingRecord:
    """思考过程记录"""
    content: str                         # 思考内容
    timestamp: str                       # 时间戳
    is_working: bool = False             # True=工作中，False=思考中

    def to_dict(self) -> Dict:
        return {
            "content": self.content,
            "timestamp": self.timestamp,
            "is_working": self.is_working,
        }


# ==================== SkillVisualizer 主类 ====================

class SkillVisualizer:
    """Skill 可视化仪表盘状态管理器

    负责追踪所有 Skill 调用、任务进度、思考过程和文件变更，
    通过事件回调系统向前端推送实时更新。
    """

    # 历史记录上限
    MAX_SKILL_HISTORY = 200
    MAX_THINKING_HISTORY = 500
    MAX_FILE_CHANGES = 100

    def __init__(self):
        """初始化所有状态容器和事件回调"""
        self._lock = threading.RLock()

        # ---- Skill 调用记录 ----
        # _skill_records: {record_id: SkillCallRecord}
        self._skill_records: Dict[str, SkillCallRecord] = {}
        # _skill_history: 按完成时间排序的历史记录 ID 列表
        self._skill_history: List[str] = []

        # ---- 任务记录 ----
        # _tasks: {task_id: TaskRecord}
        self._tasks: Dict[str, TaskRecord] = {}

        # ---- 思考过程记录 ----
        # _thinking_records: List[ThinkingRecord]
        self._thinking_records: List[ThinkingRecord] = []

        # ---- 文件变更记录 ----
        # _file_changes: List[FileChange]
        self._file_changes: List[FileChange] = []

        # ---- 事件回调 ----
        self._on_skill_status_changed: List[Callable] = []
        self._on_task_updated: List[Callable] = []
        self._on_thinking_added: List[Callable] = []
        self._on_file_changed: List[Callable] = []

        _logger.info("SkillVisualizer 初始化完成")

    # ================================================================
    # 事件回调注册
    # ================================================================

    def register_callback(self, event: str, callback: Callable):
        """注册事件回调

        Args:
            event: 事件名称，可选值：
                'skill_status_changed', 'task_updated',
                'thinking_added', 'file_changed'
            callback: 回调函数
        """
        with self._lock:
            if event == "skill_status_changed":
                self._on_skill_status_changed.append(callback)
            elif event == "task_updated":
                self._on_task_updated.append(callback)
            elif event == "thinking_added":
                self._on_thinking_added.append(callback)
            elif event == "file_changed":
                self._on_file_changed.append(callback)
            else:
                _logger.warning(f"未知事件类型: {event}")

    def unregister_callback(self, event: str, callback: Callable):
        """取消事件回调"""
        with self._lock:
            target = None
            if event == "skill_status_changed":
                target = self._on_skill_status_changed
            elif event == "task_updated":
                target = self._on_task_updated
            elif event == "thinking_added":
                target = self._on_thinking_added
            elif event == "file_changed":
                target = self._on_file_changed

            if target is not None and callback in target:
                target.remove(callback)

    def _fire_callback(self, callbacks: List[Callable], *args):
        """触发回调（异常隔离）"""
        for cb in callbacks:
            try:
                cb(*args)
            except Exception as e:
                _logger.error(f"回调执行异常: {e}")

    # ================================================================
    # Skill 调用管理
    # ================================================================

    def start_skill_call(
        self,
        skill_id: str,
        skill_name: str,
        input_params: Optional[Dict] = None,
        icon_svg: Optional[str] = None,
    ) -> str:
        """启动一个 Skill 调用

        Args:
            skill_id: Skill 唯一标识
            skill_name: Skill 名称
            input_params: 输入参数
            icon_svg: SVG 图标路径数据

        Returns:
            record_id: 调用记录 ID
        """
        record_id = _generate_id("sk")

        with self._lock:
            record = SkillCallRecord(
                skill_id=skill_id,
                skill_name=skill_name,
                status=SkillStatus.RUNNING,
                started_at=_now_iso(),
                input_params=input_params or {},
                icon_svg=icon_svg,
            )
            self._skill_records[record_id] = record

            _logger.debug(f"Skill 启动: {skill_name} (record={record_id})")

        # 触发回调
        self._fire_callback(
            self._on_skill_status_changed, record.to_dict()
        )
        return record_id

    def complete_skill_call(
        self,
        record_id: str,
        output_summary: str = "",
        success: bool = True,
        error_msg: Optional[str] = None,
    ):
        """完成一个 Skill 调用

        Args:
            record_id: 调用记录 ID
            output_summary: 输出摘要
            success: 是否成功
            error_msg: 错误信息（失败时）
        """
        with self._lock:
            record = self._skill_records.get(record_id)
            if record is None:
                _logger.warning(f"Skill 记录不存在: {record_id}")
                return

            record.status = SkillStatus.COMPLETED if success else SkillStatus.FAILED
            record.completed_at = _now_iso()
            record.output_summary = output_summary[:200] if output_summary else ""
            record.error_message = error_msg

            # 计算耗时
            try:
                start = _parse_iso(record.started_at)
                end = _parse_iso(record.completed_at)
                record.duration_ms = (end - start).total_seconds() * 1000
            except Exception:
                record.duration_ms = 0.0

            # 加入历史队列
            self._skill_history.append(record_id)
            # 限制历史记录数量
            while len(self._skill_history) > self.MAX_SKILL_HISTORY:
                old_id = self._skill_history.pop(0)
                self._skill_records.pop(old_id, None)

            _logger.debug(
                f"Skill {'完成' if success else '失败'}: "
                f"{record.skill_name} ({record.duration_ms:.0f}ms)"
            )

        # 触发回调
        self._fire_callback(
            self._on_skill_status_changed, record.to_dict()
        )

    def cancel_skill_call(self, record_id: str):
        """取消一个 Skill 调用

        Args:
            record_id: 调用记录 ID
        """
        with self._lock:
            record = self._skill_records.get(record_id)
            if record is None:
                _logger.warning(f"Skill 记录不存在: {record_id}")
                return
            if record.status != SkillStatus.RUNNING:
                return

            record.status = SkillStatus.CANCELLED
            record.completed_at = _now_iso()
            try:
                start = _parse_iso(record.started_at)
                end = _parse_iso(record.completed_at)
                record.duration_ms = (end - start).total_seconds() * 1000
            except Exception:
                record.duration_ms = 0.0

            # 加入历史队列
            self._skill_history.append(record_id)
            while len(self._skill_history) > self.MAX_SKILL_HISTORY:
                old_id = self._skill_history.pop(0)
                self._skill_records.pop(old_id, None)

            _logger.debug(f"Skill 已取消: {record.skill_name}")

        # 触发回调
        self._fire_callback(
            self._on_skill_status_changed, record.to_dict()
        )

    def get_skill_history(self, limit: int = 20) -> List[Dict]:
        """获取最近完成的 Skill 调用历史

        Args:
            limit: 返回数量上限

        Returns:
            最近完成的 Skill 调用记录列表
        """
        with self._lock:
            # 取最近 limit 条已完成记录
            recent_ids = self._skill_history[-limit:]
            return [
                self._skill_records[rid].to_dict()
                for rid in reversed(recent_ids)
                if rid in self._skill_records
            ]

    def get_active_skills(self) -> List[Dict]:
        """获取当前正在运行的 Skill

        Returns:
            运行中的 Skill 调用记录列表
        """
        with self._lock:
            return [
                r.to_dict()
                for r in self._skill_records.values()
                if r.status == SkillStatus.RUNNING
            ]

    # ================================================================
    # 任务进度管理
    # ================================================================

    def add_task(
        self,
        task_id: str,
        title: str,
        sub_tasks: Optional[List[Dict]] = None,
    ) -> Dict:
        """添加一个任务

        Args:
            task_id: 任务 ID
            title: 任务标题
            sub_tasks: 子任务列表 [{title, status, progress}]

        Returns:
            任务字典
        """
        with self._lock:
            task = TaskRecord(
                task_id=task_id,
                title=title,
                status="pending",
                created_at=_now_iso(),
                sub_tasks=sub_tasks or [],
            )
            self._tasks[task_id] = task

            _logger.debug(f"任务已添加: {title} (id={task_id})")

        # 触发回调
        self._fire_callback(self._on_task_updated, task.to_dict())
        return task.to_dict()

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        sub_task_index: Optional[int] = None,
        sub_task_status: Optional[str] = None,
    ):
        """更新任务状态

        Args:
            task_id: 任务 ID
            status: 新状态
            progress: 整体进度 0.0-1.0
            sub_task_index: 子任务索引
            sub_task_status: 子任务状态
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                _logger.warning(f"任务不存在: {task_id}")
                return

            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = max(0.0, min(1.0, progress))

            # 更新子任务
            if sub_task_index is not None and 0 <= sub_task_index < len(task.sub_tasks):
                sub = task.sub_tasks[sub_task_index]
                if sub_task_status is not None:
                    sub["status"] = sub_task_status
                # 自动计算子任务进度
                if sub_task_status == "completed":
                    sub["progress"] = 1.0
                elif sub_task_status == "in_progress":
                    sub["progress"] = sub.get("progress", 0.5)

            # 自动推导整体状态
            if status is None and task.sub_tasks:
                all_completed = all(
                    st.get("status") == "completed" for st in task.sub_tasks
                )
                any_failed = any(
                    st.get("status") == "failed" for st in task.sub_tasks
                )
                if all_completed:
                    task.status = "completed"
                    task.progress = 1.0
                elif any_failed:
                    task.status = "failed"
                elif any(st.get("status") == "in_progress" for st in task.sub_tasks):
                    task.status = "in_progress"
                    # 计算平均进度
                    total_prog = sum(st.get("progress", 0.0) for st in task.sub_tasks)
                    task.progress = total_prog / len(task.sub_tasks)

            # 标记完成时间
            if task.status == "completed" and task.completed_at is None:
                task.completed_at = _now_iso()
            if task.status == "failed" and task.completed_at is None:
                task.completed_at = _now_iso()

        # 触发回调
        self._fire_callback(self._on_task_updated, task.to_dict())

    def get_tasks(self) -> List[Dict]:
        """获取所有任务

        Returns:
            任务列表
        """
        with self._lock:
            return [t.to_dict() for t in self._tasks.values()]

    def get_task_progress(self) -> Dict:
        """获取任务进度汇总

        Returns:
            {total, completed, in_progress, pending, failed, percentage}
        """
        with self._lock:
            tasks = list(self._tasks.values())
            total = len(tasks)
            completed = sum(1 for t in tasks if t.status == "completed")
            in_progress = sum(1 for t in tasks if t.status == "in_progress")
            pending = sum(1 for t in tasks if t.status == "pending")
            failed = sum(1 for t in tasks if t.status == "failed")
            percentage = (completed / total * 100) if total > 0 else 0.0

            return {
                "total": total,
                "completed": completed,
                "in_progress": in_progress,
                "pending": pending,
                "failed": failed,
                "percentage": round(percentage, 1),
            }

    # ================================================================
    # 思考过程管理
    # ================================================================

    def add_thinking(self, content: str, is_working: bool = False) -> Dict:
        """添加一条思考记录

        Args:
            content: 思考内容
            is_working: True=工作中，False=思考中

        Returns:
            思考记录字典
        """
        record = ThinkingRecord(
            content=content,
            timestamp=_now_iso(),
            is_working=is_working,
        )

        with self._lock:
            self._thinking_records.append(record)
            # 限制思考记录数量
            while len(self._thinking_records) > self.MAX_THINKING_HISTORY:
                self._thinking_records.pop(0)

        # 触发回调
        self._fire_callback(
            self._on_thinking_added, record.to_dict()
        )
        return record.to_dict()

    def get_thinking_history(self, limit: int = 50) -> List[Dict]:
        """获取最近的思考记录

        Args:
            limit: 返回数量上限

        Returns:
            思考记录列表
        """
        with self._lock:
            recent = self._thinking_records[-limit:]
            return [r.to_dict() for r in recent]

    def clear_thinking(self):
        """清空思考记录"""
        with self._lock:
            self._thinking_records.clear()
            _logger.debug("思考记录已清空")

    # ================================================================
    # 文件变更管理
    # ================================================================

    def add_file_change(
        self,
        file_path: str,
        lines_added: int = 0,
        lines_deleted: int = 0,
        diff_content: Optional[str] = None,
        change_type: str = "modified",
    ):
        """添加一条文件变更记录

        Args:
            file_path: 文件路径
            lines_added: 新增行数
            lines_deleted: 删除行数
            diff_content: unified diff 文本
            change_type: 变更类型 modified/created/deleted
        """
        change = FileChange(
            file_path=file_path,
            lines_added=lines_added,
            lines_deleted=lines_deleted,
            diff_content=diff_content,
            change_type=change_type,
        )

        with self._lock:
            # 合并同一文件的多条变更记录
            existing = self._find_file_change(file_path)
            if existing:
                existing.lines_added += lines_added
                existing.lines_deleted += lines_deleted
                if diff_content:
                    # 追加 diff 内容
                    if existing.diff_content:
                        existing.diff_content += "\n" + diff_content
                    else:
                        existing.diff_content = diff_content
                if change_type != "modified":
                    existing.change_type = change_type
            else:
                self._file_changes.append(change)
                # 限制文件变更记录数量
                while len(self._file_changes) > self.MAX_FILE_CHANGES:
                    self._file_changes.pop(0)

        # 触发回调
        self._fire_callback(
            self._on_file_changed, self._get_file_changes_summary()
        )

    def _find_file_change(self, file_path: str) -> Optional[FileChange]:
        """查找已有的文件变更记录"""
        for fc in self._file_changes:
            if fc.file_path == file_path:
                return fc
        return None

    def get_file_changes(self) -> Dict:
        """获取文件变更汇总

        Returns:
            {total_added, total_deleted, files: [...]}
        """
        return self._get_file_changes_summary()

    def _get_file_changes_summary(self) -> Dict:
        """构建文件变更汇总"""
        with self._lock:
            total_added = sum(fc.lines_added for fc in self._file_changes)
            total_deleted = sum(fc.lines_deleted for fc in self._file_changes)
            files = [fc.to_dict() for fc in self._file_changes]

            return {
                "total_added": total_added,
                "total_deleted": total_deleted,
                "files": files,
            }

    def clear_file_changes(self):
        """清空文件变更记录"""
        with self._lock:
            self._file_changes.clear()
            _logger.debug("文件变更记录已清空")

    # ================================================================
    # 仪表盘状态快照
    # ================================================================

    def get_dashboard_state(self) -> Dict:
        """获取完整仪表盘状态快照

        供前端一次性获取所有可视化面板数据。

        Returns:
            {
                'active_skills': [...],
                'recent_skills': [...],
                'tasks': [...],
                'task_progress': {...},
                'thinking': [...],
                'file_changes': {...},
                'timestamp': '...'
            }
        """
        with self._lock:
            active_skills = [
                r.to_dict()
                for r in self._skill_records.values()
                if r.status == SkillStatus.RUNNING
            ]
            recent_skills = [
                self._skill_records[rid].to_dict()
                for rid in reversed(self._skill_history[-20:])
                if rid in self._skill_records
            ]
            tasks = [t.to_dict() for t in self._tasks.values()]

            # 任务进度
            task_list = list(self._tasks.values())
            total = len(task_list)
            completed = sum(1 for t in task_list if t.status == "completed")
            in_progress = sum(1 for t in task_list if t.status == "in_progress")
            pending = sum(1 for t in task_list if t.status == "pending")
            failed = sum(1 for t in task_list if t.status == "failed")
            percentage = (completed / total * 100) if total > 0 else 0.0

            thinking = [
                r.to_dict() for r in self._thinking_records[-50:]
            ]

            total_added = sum(fc.lines_added for fc in self._file_changes)
            total_deleted = sum(fc.lines_deleted for fc in self._file_changes)

            return {
                "active_skills": active_skills,
                "recent_skills": recent_skills,
                "tasks": tasks,
                "task_progress": {
                    "total": total,
                    "completed": completed,
                    "in_progress": in_progress,
                    "pending": pending,
                    "failed": failed,
                    "percentage": round(percentage, 1),
                },
                "thinking": thinking,
                "file_changes": {
                    "total_added": total_added,
                    "total_deleted": total_deleted,
                    "files": [fc.to_dict() for fc in self._file_changes],
                },
                "timestamp": _now_iso(),
            }

    # ================================================================
    # 重置
    # ================================================================

    def reset(self):
        """重置所有状态"""
        with self._lock:
            self._skill_records.clear()
            self._skill_history.clear()
            self._tasks.clear()
            self._thinking_records.clear()
            self._file_changes.clear()
            _logger.info("SkillVisualizer 状态已重置")


# ==================== 全局单例 ====================

_visualizer_instance: Optional[SkillVisualizer] = None
_visualizer_lock = threading.Lock()


def get_skill_visualizer() -> SkillVisualizer:
    """获取全局 SkillVisualizer 单例

    Returns:
        SkillVisualizer 实例
    """
    global _visualizer_instance
    if _visualizer_instance is None:
        with _visualizer_lock:
            if _visualizer_instance is None:
                _visualizer_instance = SkillVisualizer()
    return _visualizer_instance


def reset_skill_visualizer() -> None:
    """★ v5.8: 重置全局 SkillVisualizer 状态（模块级入口，测试/热重载用）。"""
    get_skill_visualizer().reset()


# ==================== 工具函数 ====================

def _generate_id(prefix: str = "") -> str:
    """生成唯一 ID

    Args:
        prefix: 前缀

    Returns:
        唯一标识字符串
    """
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    """获取当前 UTC 时间的 ISO 格式字符串"""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> datetime:
    """解析 ISO 时间字符串为 datetime 对象"""
    # 处理带时区和不带时区的格式
    try:
        # Python 3.11+ 支持 Z 后缀
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        # 回退：尝试 strptime
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ]:
            try:
                return datetime.strptime(iso_str, fmt)
            except ValueError:
                continue
        # 最终回退
        return datetime.now(timezone.utc)