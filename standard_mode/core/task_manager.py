# -*- coding: utf-8 -*-
"""
Task Manager — 任务依赖管理（v0.9.0 新增）
==========================================
扩展原 todo_write Skill，支持：
  1. 任务依赖管理（task A depends on task B）
  2. 任务状态机：pending → running → completed / failed / blocked
  3. 依赖任务未完成时阻塞当前任务（状态自动变为 blocked）
  4. 依赖关系图形化展示（A→B→C 流程图，ASCII + HTML）
  5. 任务拓扑排序（自动计算可执行顺序）
  6. 任务执行顺序校验

设计原则：
  - 完全兼容原 todo_write 的接口（todos JSON 数组）
  - 新增 depends_on 字段表示依赖关系
  - 状态自动流转：尝试将 pending 任务转为 running 时，先检查所有依赖
"""

import json
import threading
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict, deque


# ============================================================
# 任务状态机
# ============================================================

class TaskStatus:
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"        # 依赖未完成，被阻塞
    CANCELLED = "cancelled"


# 状态合法流转
VALID_TRANSITIONS: Dict[str, Set[str]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.BLOCKED: {TaskStatus.RUNNING, TaskStatus.PENDING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),  # 终态
    TaskStatus.FAILED: {TaskStatus.PENDING, TaskStatus.RUNNING},  # 允许重试
    TaskStatus.CANCELLED: set(),  # 终态
}

# 状态图标
STATUS_ICONS = {
    TaskStatus.PENDING: "○",
    TaskStatus.RUNNING: "→",
    TaskStatus.COMPLETED: "✓",
    TaskStatus.FAILED: "✗",
    TaskStatus.BLOCKED: "⊗",
    TaskStatus.CANCELLED: "⊘",
}

# 状态颜色（用于 HTML 渲染）
STATUS_COLORS = {
    TaskStatus.PENDING: "Lemon.STATUS_OFFLINE",
    TaskStatus.RUNNING: "Lemon.STATUS_RUNNING",
    TaskStatus.COMPLETED: "Lemon.STATUS_ONLINE",
    TaskStatus.FAILED: "#f85149",
    TaskStatus.BLOCKED: "Lemon.ACCENT_GOLD",
    TaskStatus.CANCELLED: "Lemon.SYNTAX_COMMENT",
}


@dataclass
class Task:
    """单个任务"""
    id: str
    content: str = ""
    status: str = TaskStatus.PENDING
    priority: str = "medium"           # high / medium / low
    depends_on: List[str] = field(default_factory=list)  # 依赖的任务 id 列表
    created_at: float = 0.0
    updated_at: float = 0.0
    completed_at: Optional[float] = None
    error_message: str = ""
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


# ============================================================
# 任务管理器
# ============================================================

class TaskManager:
    """任务管理器 — 支持依赖关系和状态机

    用法：
        tm = TaskManager()
        tm.add_task(Task(id="A", content="任务 A"))
        tm.add_task(Task(id="B", content="任务 B", depends_on=["A"]))
        tm.add_task(Task(id="C", content="任务 C", depends_on=["B"]))

        # 检查 B 是否可以执行
        can_run, reason = tm.can_run("B")  # False, "依赖任务未完成: A"

        # 完成任务 A
        tm.transition("A", TaskStatus.RUNNING)
        tm.transition("A", TaskStatus.COMPLETED)

        # 现在 B 可以执行
        can_run, reason = tm.can_run("B")  # True, ""
        tm.transition("B", TaskStatus.RUNNING)
    """

    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.RLock()  # ★ 使用可重入锁，避免 render_* 调用 topo/levels 时死锁
        import time
        self._time = time.time

    # ---------- 任务 CRUD ----------

    def add_task(self, task: Task) -> bool:
        """添加任务"""
        with self._lock:
            if task.id in self._tasks:
                return False
            now = self._time()
            if not task.created_at:
                task.created_at = now
            task.updated_at = now
            self._tasks[task.id] = task
            # 添加后自动检查依赖状态
            self._update_blocked_status(task.id)
            return True

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        with self._lock:
            return self._tasks.get(task_id)

    def remove_task(self, task_id: str) -> bool:
        """删除任务"""
        with self._lock:
            if task_id not in self._tasks:
                return False
            del self._tasks[task_id]
            # 从其他任务的 depends_on 中移除
            for t in self._tasks.values():
                if task_id in t.depends_on:
                    t.depends_on.remove(task_id)
            return True

    def list_tasks(self) -> List[Task]:
        """列出所有任务"""
        with self._lock:
            return list(self._tasks.values())

    def clear(self):
        """清空所有任务"""
        with self._lock:
            self._tasks.clear()

    # ---------- 状态机 ----------

    def transition(self, task_id: str, new_status: str) -> Tuple[bool, str]:
        """任务状态流转

        Returns:
            (success, message)
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False, f"任务不存在: {task_id}"

            current = task.status
            if new_status == current:
                return True, f"状态未变（{current}）"

            # 校验状态流转合法性
            if new_status not in VALID_TRANSITIONS.get(current, set()):
                return False, f"非法状态流转: {current} → {new_status}"

            # 尝试转为 running 时，必须先满足依赖
            if new_status == TaskStatus.RUNNING:
                ok, reason = self._check_dependencies(task_id)
                if not ok:
                    # 自动标记为 blocked
                    task.status = TaskStatus.BLOCKED
                    task.updated_at = self._time()
                    task.error_message = reason
                    return False, f"依赖未满足，已转为 blocked: {reason}"

            # 执行状态变更
            task.status = new_status
            task.updated_at = self._time()
            if new_status == TaskStatus.COMPLETED:
                task.completed_at = self._time()
            elif new_status == TaskStatus.FAILED:
                task.error_message = task.error_message or "执行失败"
            elif new_status == TaskStatus.PENDING:
                # 重置时清除错误
                task.error_message = ""

            # 状态变更后，重新计算所有 blocked 任务的依赖
            self._refresh_all_blocked()

            return True, f"状态变更: {current} → {new_status}"

    def _check_dependencies(self, task_id: str) -> Tuple[bool, str]:
        """检查任务依赖是否满足（调用者必须持有 _lock）"""
        task = self._tasks.get(task_id)
        if not task:
            return False, "任务不存在"

        unmet = []
        for dep_id in task.depends_on:
            dep = self._tasks.get(dep_id)
            if not dep:
                unmet.append(f"{dep_id}(不存在)")
            elif dep.status != TaskStatus.COMPLETED:
                unmet.append(f"{dep_id}({dep.status})")

        if unmet:
            return False, f"依赖任务未完成: {', '.join(unmet)}"
        return True, ""

    def _update_blocked_status(self, task_id: str):
        """更新任务的 blocked 状态（调用者必须持有 _lock）"""
        task = self._tasks.get(task_id)
        if not task:
            return
        if task.status == TaskStatus.PENDING and task.depends_on:
            ok, _ = self._check_dependencies(task_id)
            if not ok:
                task.status = TaskStatus.BLOCKED

    def _refresh_all_blocked(self):
        """刷新所有 blocked/pending 任务的依赖状态（调用者必须持有 _lock）"""
        for tid, task in self._tasks.items():
            if task.status in (TaskStatus.BLOCKED, TaskStatus.PENDING):
                if task.depends_on:
                    ok, _ = self._check_dependencies(tid)
                    if ok and task.status == TaskStatus.BLOCKED:
                        # 依赖已满足，转回 pending
                        task.status = TaskStatus.PENDING
                        task.error_message = ""
                    elif not ok and task.status == TaskStatus.PENDING:
                        # 依赖未满足，转为 blocked
                        task.status = TaskStatus.BLOCKED

    def can_run(self, task_id: str) -> Tuple[bool, str]:
        """检查任务是否可以执行（不实际改变状态）"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False, "任务不存在"
            if task.status not in (TaskStatus.PENDING, TaskStatus.BLOCKED):
                return False, f"任务状态为 {task.status}，无法执行"
            return self._check_dependencies(task_id)

    # ---------- 拓扑排序 ----------

    def topological_sort(self) -> Tuple[List[str], List[str]]:
        """拓扑排序 — 计算任务执行顺序

        Returns:
            (sorted_ids, cyclic_ids) — 排序后的 id 列表 + 检测到的循环依赖
        """
        with self._lock:
            # 构建依赖图
            in_degree: Dict[str, int] = {tid: 0 for tid in self._tasks}
            graph: Dict[str, List[str]] = defaultdict(list)

            for tid, task in self._tasks.items():
                for dep_id in task.depends_on:
                    if dep_id in self._tasks:
                        graph[dep_id].append(tid)
                        in_degree[tid] += 1

            # Kahn 算法
            queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
            sorted_ids: List[str] = []

            while queue:
                # 按优先级和创建时间排序
                queue_list = sorted(
                    queue,
                    key=lambda t: (
                        {"high": 0, "medium": 1, "low": 2}.get(self._tasks[t].priority, 1),
                        self._tasks[t].created_at,
                    ),
                )
                tid = queue_list[0]
                queue.remove(tid)
                sorted_ids.append(tid)

                for next_id in graph[tid]:
                    in_degree[next_id] -= 1
                    if in_degree[next_id] == 0:
                        queue.append(next_id)

            # 检测循环依赖
            cyclic_ids = [tid for tid, deg in in_degree.items() if deg > 0]

            return sorted_ids, cyclic_ids

    # ---------- 批量导入 / 导出 ----------

    def load_from_list(self, task_list: List[Dict], merge: bool = False) -> int:
        """从字典列表加载任务"""
        if not merge:
            self.clear()
        count = 0
        for item in task_list:
            if not isinstance(item, dict):
                continue
            tid = item.get("id", str(len(self._tasks) + 1))
            task = Task(
                id=tid,
                content=item.get("content", ""),
                status=item.get("status", TaskStatus.PENDING),
                priority=item.get("priority", "medium"),
                depends_on=item.get("depends_on", []),
            )
            if self.add_task(task):
                count += 1
            elif merge:
                # 更新已存在的任务
                with self._lock:
                    self._tasks[tid] = task
                    count += 1
        # 加载完成后统一刷新 blocked 状态
        with self._lock:
            self._refresh_all_blocked()
        return count

    def export_to_list(self) -> List[Dict]:
        """导出任务列表"""
        with self._lock:
            return [t.to_dict() for t in self._tasks.values()]

    # ---------- 图形化展示 ----------

    def render_ascii_graph(self) -> str:
        """渲染 ASCII 流程图（A→B→C 形式）"""
        with self._lock:
            if not self._tasks:
                return "(无任务)"

            # 构建依赖关系字符串
            lines = []
            sorted_ids, cyclic = self.topological_sort()

            if cyclic:
                lines.append(f"⚠ 检测到循环依赖: {', '.join(cyclic)}")
                # 退化为按 id 排序
                sorted_ids = sorted(self._tasks.keys())

            # 按层级渲染
            levels = self._compute_levels()
            max_level = max(levels.values()) if levels else 0

            for level in range(max_level + 1):
                level_tasks = [
                    tid for tid in sorted_ids
                    if levels.get(tid, 0) == level
                ]
                if not level_tasks:
                    continue

                # 渲染当前层
                task_strs = []
                for tid in level_tasks:
                    task = self._tasks[tid]
                    icon = STATUS_ICONS.get(task.status, "?")
                    content_short = task.content[:30] if task.content else tid
                    task_strs.append(f"[{icon} {tid}] {content_short}")

                lines.append("  ".join(task_strs))

                # 渲染连接线
                if level < max_level:
                    next_level_ids = [
                        tid for tid in sorted_ids
                        if levels.get(tid, 0) == level + 1
                    ]
                    if next_level_ids:
                        # 找到所有从当前层到下一层的依赖
                        arrows = []
                        for next_tid in next_level_ids:
                            for dep_id in self._tasks[next_tid].depends_on:
                                if levels.get(dep_id, 0) == level:
                                    arrows.append(f"{dep_id}→{next_tid}")
                        if arrows:
                            lines.append("    " + "  ".join(arrows))

            # 渲染统计
            status_count = defaultdict(int)
            for t in self._tasks.values():
                status_count[t.status] += 1
            stats = " | ".join(
                f"{STATUS_ICONS.get(s, '?')} {s}: {c}"
                for s, c in status_count.items()
            )
            lines.append("")
            lines.append(f"统计: {len(self._tasks)} 个任务 | {stats}")

            return "\n".join(lines)

    def render_html_graph(self) -> str:
        """渲染 HTML 流程图（用于内联展示）"""
        with self._lock:
            if not self._tasks:
                return '<div style="color:Lemon.STATUS_OFFLINE;">(无任务)</div>'

            sorted_ids, cyclic = self.topological_sort()
            if cyclic:
                cyclic_warning = (
                    f'<div style="color:Lemon.ACCENT_GOLD;margin-bottom:8px;">'
                    f'⚠ 检测到循环依赖: {", ".join(cyclic)}</div>'
                )
            else:
                cyclic_warning = ""

            levels = self._compute_levels()
            max_level = max(levels.values()) if levels else 0

            # 按层级渲染
            level_html = []
            for level in range(max_level + 1):
                level_tasks = [
                    tid for tid in sorted_ids
                    if levels.get(tid, 0) == level
                ]
                if not level_tasks:
                    continue

                cards = []
                for tid in level_tasks:
                    task = self._tasks[tid]
                    color = STATUS_COLORS.get(task.status, "Lemon.STATUS_OFFLINE")
                    icon = STATUS_ICONS.get(task.status, "?")
                    content = task.content[:50] if task.content else tid
                    deps = ", ".join(task.depends_on) if task.depends_on else "—"
                    cards.append(
                        f'<div style="display:inline-block;margin:4px;padding:6px 10px;'
                        f'border:1px solid {color};border-radius:4px;'
                        f'background:Lemon.DARK_BG_1;min-width:120px;">'
                        f'<div style="color:{color};font-weight:600;">{icon} {tid}</div>'
                        f'<div style="color:Lemon.PLACEHOLDER;font-size:12px;margin-top:2px;">{content}</div>'
                        f'<div style="color:Lemon.SYNTAX_COMMENT;font-size:10px;margin-top:2px;">依赖: {deps}</div>'
                        f'</div>'
                    )
                level_html.append(
                    f'<div style="margin:8px 0;">{"".join(cards)}</div>'
                )
                # 添加箭头层
                if level < max_level:
                    level_html.append(
                        f'<div style="color:Lemon.STATUS_RUNNING;text-align:center;font-size:14px;">↓</div>'
                    )

            # 统计
            status_count = defaultdict(int)
            for t in self._tasks.values():
                status_count[t.status] += 1
            stats_html = " ".join(
                f'<span style="color:{STATUS_COLORS.get(s, "Lemon.STATUS_OFFLINE")};">'
                f'{STATUS_ICONS.get(s, "?")} {s}: {c}</span>'
                for s, c in status_count.items()
            )

            return (
                f'<div style="font-family:Consolas,monospace;padding:10px;'
                f'background:Lemon.DARK_BG_2;border-radius:6px;">'
                f'{cyclic_warning}'
                f'{"".join(level_html)}'
                f'<div style="margin-top:8px;padding-top:8px;'
                f'border-top:1px solid Lemon.DARK_BG_4;font-size:11px;">'
                f'共 {len(self._tasks)} 个任务 | {stats_html}'
                f'</div>'
                f'</div>'
            )

    def _compute_levels(self) -> Dict[str, int]:
        """计算每个任务的层级（依赖链深度）"""
        levels: Dict[str, int] = {}

        def get_level(tid: str, visited: Set[str]) -> int:
            if tid in levels:
                return levels[tid]
            if tid in visited:
                return 0  # 循环依赖，返回 0
            visited.add(tid)
            task = self._tasks.get(tid)
            if not task or not task.depends_on:
                levels[tid] = 0
                return 0
            max_dep_level = max(
                (get_level(dep, visited) for dep in task.depends_on if dep in self._tasks),
                default=-1,
            )
            levels[tid] = max_dep_level + 1
            return levels[tid]

        for tid in self._tasks:
            get_level(tid, set())

        return levels

    # ---------- 状态查询 ----------

    def get_summary(self) -> Dict:
        """获取任务统计摘要"""
        with self._lock:
            status_count = defaultdict(int)
            priority_count = defaultdict(int)
            for t in self._tasks.values():
                status_count[t.status] += 1
                priority_count[t.priority] += 1
            sorted_ids, cyclic = self.topological_sort()
            return {
                "total": len(self._tasks),
                "status": dict(status_count),
                "priority": dict(priority_count),
                "execution_order": sorted_ids,
                "has_cycle": len(cyclic) > 0,
                "cyclic_tasks": cyclic,
            }


# ============================================================
# 全局单例
# ============================================================

_global_manager: Optional[TaskManager] = None
_manager_lock = threading.Lock()
# ★第361章: 会话分桶 — 每个对话会话独立任务列表（Trae/CodeBuddy 式任务隔离）
_scoped_managers: Dict[str, TaskManager] = {}


def get_task_manager(scope: str = "default") -> TaskManager:
    """获取 TaskManager（按 scope 分桶，默认全局单例兼容旧调用）

    ★第361章: scope=会话ID（session_id）→ 每会话独立任务列表；
    不传 scope 的旧调用方自动落到 "default" 桶，行为不变。
    """
    key = str(scope or "default")
    if key == "default":
        global _global_manager
        if _global_manager is None:
            with _manager_lock:
                if _global_manager is None:
                    _global_manager = TaskManager()
        return _global_manager
    mgr = _scoped_managers.get(key)
    if mgr is None:
        with _manager_lock:
            mgr = _scoped_managers.get(key)
            if mgr is None:
                mgr = TaskManager()
                _scoped_managers[key] = mgr
    return mgr
