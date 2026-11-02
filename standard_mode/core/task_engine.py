# -*- coding: utf-8 -*-
"""
任务分解引擎 — 大任务拆分为子任务树
=====================================
核心能力：
- 任务树：父子任务层级管理
- 依赖分析：检测任务间依赖关系
- 拓扑排序：确定执行顺序
- 并行执行：无依赖的任务可并行
- 失败重试 + 回滚机制

架构：
┌─────────────────────────────────────┐
│           TaskEngine                 │
│  ┌───────────────────────────────┐  │
│  │  TaskTree                     │  │
│  │  ├── RootTask                 │  │
│  │  │   ├── SubTask1 (独立)      │  │
│  │  │   ├── SubTask2 → SubTask1  │  │
│  │  │   └── SubTask3 (独立)      │  │
│  │  └── Decomposer               │  │
│  └───────────────────────────────┘  │
│  ┌───────────────────────────────┐  │
│  │  Scheduler (拓扑排序+并行)     │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
"""

import threading
import time
from typing import List, Dict, Optional, Set, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

from PyQt5.QtCore import QObject, pyqtSignal


class TaskStatus(Enum):
    PENDING = "pending"
    READY = "ready"        # 依赖已满足，等待执行
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Task:
    """任务节点"""
    id: str
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    parent_id: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务ID列表
    children: List[str] = field(default_factory=list)       # 子任务ID列表
    assigned_provider: str = ""      # 分配的 AI 提供商
    result: Any = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def elapsed(self) -> float:
        if self.started_at:
            end = self.completed_at or time.time()
            return end - self.started_at
        return 0.0
    
    @property
    def is_terminal(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED,
                               TaskStatus.CANCELLED, TaskStatus.SKIPPED)
    
    @property
    def can_retry(self) -> bool:
        return self.status == TaskStatus.FAILED and self.retry_count < self.max_retries


class TaskTree:
    """任务树管理器"""
    
    def __init__(self, root_name: str = "Root Task"):
        self._tasks: Dict[str, Task] = {}
        self._root_id = self._add_task(root_name, description="根任务")
    
    @property
    def root_id(self) -> str:
        return self._root_id
    
    @property
    def root(self) -> Task:
        return self._tasks[self._root_id]
    
    def _add_task(self, name: str, description: str = "", 
                  parent_id: str = None, priority: TaskPriority = TaskPriority.NORMAL) -> str:
        """添加任务节点"""
        import uuid
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            id=task_id,
            name=name,
            description=description,
            priority=priority,
            parent_id=parent_id,
        )
        self._tasks[task_id] = task
        
        if parent_id and parent_id in self._tasks:
            self._tasks[parent_id].children.append(task_id)
        
        return task_id
    
    def add_task(self, name: str, description: str = "",
                 parent_id: str = None, depends_on: List[str] = None,
                 priority: TaskPriority = TaskPriority.NORMAL) -> str:
        """添加子任务"""
        if parent_id is None:
            parent_id = self._root_id
        
        task_id = self._add_task(name, description, parent_id, priority)
        
        if depends_on:
            for dep_id in depends_on:
                if dep_id in self._tasks:
                    self._tasks[task_id].dependencies.append(dep_id)
        
        return task_id
    
    def add_dependency(self, task_id: str, depends_on: str):
        """添加任务依赖"""
        if task_id in self._tasks and depends_on in self._tasks:
            if depends_on not in self._tasks[task_id].dependencies:
                self._tasks[task_id].dependencies.append(depends_on)
    
    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)
    
    def get_children(self, task_id: str) -> List[Task]:
        task = self._tasks.get(task_id)
        if not task:
            return []
        return [self._tasks[cid] for cid in task.children if cid in self._tasks]
    
    def get_all_tasks(self) -> List[Task]:
        return list(self._tasks.values())
    
    def get_pending_tasks(self) -> List[Task]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
    
    def get_ready_tasks(self) -> List[Task]:
        """获取所有依赖已满足、可以执行的任务"""
        ready = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            # 检查所有依赖是否已完成
            deps_met = all(
                dep_id in self._tasks and self._tasks[dep_id].status == TaskStatus.COMPLETED
                for dep_id in task.dependencies
            )
            if deps_met:
                ready.append(task)
        return ready
    
    def update_status(self, task_id: str, status: TaskStatus, 
                      result: Any = None, error: str = None):
        """更新任务状态"""
        if task_id not in self._tasks:
            return
        task = self._tasks[task_id]
        task.status = status
        
        if status == TaskStatus.RUNNING:
            task.started_at = time.time()
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            task.completed_at = time.time()
        
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        
        if status == TaskStatus.FAILED:
            task.retry_count += 1
    
    def get_topological_order(self) -> List[str]:
        """拓扑排序 — 返回任务执行顺序"""
        in_degree = {tid: 0 for tid in self._tasks}
        adj = {tid: [] for tid in self._tasks}
        
        for tid, task in self._tasks.items():
            for dep_id in task.dependencies:
                if dep_id in adj:
                    adj[dep_id].append(tid)
                    in_degree[tid] += 1
        
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        order = []
        
        while queue:
            tid = queue.popleft()
            order.append(tid)
            for neighbor in adj[tid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        # 检测环
        if len(order) != len(self._tasks):
            # 有环，按优先级排序返回
            remaining = [tid for tid in self._tasks if tid not in order]
            remaining.sort(key=lambda tid: self._tasks[tid].priority.value, reverse=True)
            order.extend(remaining)
        
        return order
    
    def get_parallel_groups(self) -> List[List[str]]:
        """获取可并行执行的任务组（拓扑层级）"""
        order = self.get_topological_order()
        
        # 按依赖层级分组
        levels = {}
        for tid in order:
            task = self._tasks[tid]
            if not task.dependencies:
                levels[tid] = 0
            else:
                levels[tid] = max(
                    levels.get(dep, 0) for dep in task.dependencies
                ) + 1
        
        max_level = max(levels.values()) if levels else 0
        groups = [[] for _ in range(max_level + 1)]
        for tid, level in levels.items():
            groups[level].append(tid)
        
        return groups
    
    def get_progress(self) -> Dict:
        """获取任务树进度"""
        total = len(self._tasks)
        completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)
        running = sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING)
        pending = sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)
        
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": pending,
            "progress": completed / max(total, 1),
        }
    
    def to_dict(self) -> Dict:
        """序列化为字典"""
        def task_to_dict(t: Task) -> Dict:
            return {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "status": t.status.value,
                "priority": t.priority.value,
                "parent_id": t.parent_id,
                "dependencies": t.dependencies,
                "children": t.children,
                "assigned_provider": t.assigned_provider,
                "error": t.error,
                "retry_count": t.retry_count,
                "elapsed": t.elapsed,
            }
        
        return {
            "root_id": self._root_id,
            "tasks": {tid: task_to_dict(t) for tid, t in self._tasks.items()},
            "progress": self.get_progress(),
        }


class TaskDecomposer:
    """任务分解器 — 将大任务拆分为子任务（规则引擎）"""
    
    @staticmethod
    def decompose(description: str) -> List[Dict]:
        """
        根据任务描述自动分解为子任务
        
        策略：
        1. 按关键词识别任务类型
        2. 按常见模式拆分
        3. 生成依赖关系
        """
        subtasks = []
        
        desc_lower = description.lower()
        
        # 检测是否包含"创建项目"类任务
        if any(kw in desc_lower for kw in ['创建', '新建', '初始化', 'create', 'init']):
            subtasks.append({
                "name": "分析需求",
                "description": "分析项目需求和技术选型",
                "depends_on": [],
                "priority": TaskPriority.HIGH,
            })
            subtasks.append({
                "name": "创建项目结构",
                "description": "初始化项目目录和基础文件",
                "depends_on": [0],
                "priority": TaskPriority.HIGH,
            })
        
        # 检测是否包含"实现功能"类任务
        if any(kw in desc_lower for kw in ['实现', '开发', '编写', 'implement', 'develop', 'code']):
            subtasks.append({
                "name": "设计接口/架构",
                "description": "设计模块接口和数据结构",
                "depends_on": [len(subtasks) - 1] if subtasks else [],
                "priority": TaskPriority.HIGH,
            })
            subtasks.append({
                "name": "实现核心逻辑",
                "description": "编写核心功能代码",
                "depends_on": [len(subtasks) - 1],
                "priority": TaskPriority.NORMAL,
            })
            subtasks.append({
                "name": "编写测试",
                "description": "编写单元测试和集成测试",
                "depends_on": [len(subtasks) - 1],
                "priority": TaskPriority.NORMAL,
            })
        
        # 检测是否包含"优化/重构"类任务
        if any(kw in desc_lower for kw in ['优化', '重构', '改进', 'optimize', 'refactor', 'improve']):
            subtasks.append({
                "name": "分析现状",
                "description": "分析当前代码的问题和瓶颈",
                "depends_on": [],
                "priority": TaskPriority.HIGH,
            })
            subtasks.append({
                "name": "制定优化方案",
                "description": "制定具体的优化策略",
                "depends_on": [len(subtasks) - 1],
                "priority": TaskPriority.HIGH,
            })
            subtasks.append({
                "name": "实施优化",
                "description": "执行代码优化和重构",
                "depends_on": [len(subtasks) - 1],
                "priority": TaskPriority.NORMAL,
            })
        
        # 检测是否包含"修复bug"类任务
        if any(kw in desc_lower for kw in ['修复', 'bug', 'fix', 'debug', '解决']):
            subtasks.append({
                "name": "复现问题",
                "description": "定位和复现 bug",
                "depends_on": [],
                "priority": TaskPriority.CRITICAL,
            })
            subtasks.append({
                "name": "分析根因",
                "description": "分析 bug 的根本原因",
                "depends_on": [len(subtasks) - 1],
                "priority": TaskPriority.CRITICAL,
            })
            subtasks.append({
                "name": "修复并验证",
                "description": "修复 bug 并验证修复效果",
                "depends_on": [len(subtasks) - 1],
                "priority": TaskPriority.CRITICAL,
            })
        
        # 如果没有匹配到任何模式，创建默认子任务
        if not subtasks:
            subtasks.append({
                "name": "分析任务",
                "description": f"分析: {description[:100]}",
                "depends_on": [],
                "priority": TaskPriority.HIGH,
            })
            subtasks.append({
                "name": "执行任务",
                "description": f"执行: {description[:100]}",
                "depends_on": [0],
                "priority": TaskPriority.NORMAL,
            })
            subtasks.append({
                "name": "验证结果",
                "description": "验证执行结果",
                "depends_on": [1],
                "priority": TaskPriority.NORMAL,
            })
        
        return subtasks


class AIDecomposer:
    """
    AI 驱动的任务分解器（v2.0 新增）
    
    使用 AI 模型智能分解任务，比规则引擎更灵活：
    - 理解复杂任务语义
    - 自动识别依赖关系
    - 动态调整分解粒度
    - 支持跨模型分配建议
    """
    
    DECOMPOSE_PROMPT = """你是一个专业的任务分解专家。请将以下任务分解为子任务。

要求：
1. 每个子任务描述清晰、可独立执行
2. 标注子任务之间的依赖关系
3. 为每个子任务建议最合适的AI模型（local=本地Ollama, cloud=云端MIMO/DeepSeek）
4. 输出JSON格式，不要任何额外文字

任务描述：
{description}

输出格式（严格JSON）：
{{
  "subtasks": [
    {{
      "name": "子任务名称",
      "description": "详细描述",
      "depends_on": [0],  // 依赖的子任务索引（从0开始），无依赖则为[]
      "priority": "high|normal|low",
      "suggested_provider": "local|cloud"
    }}
  ]
}}"""

    def __init__(self, ai_provider=None):
        """
        Args:
            ai_provider: IAIProvider 实例，用于 AI 驱动的分解
        """
        self._provider = ai_provider
    
    def set_provider(self, provider):
        """设置 AI 提供商"""
        self._provider = provider
    
    def decompose(self, description: str) -> List[Dict]:
        """
        使用 AI 模型分解任务
        
        如果 AI 不可用，回退到规则引擎
        """
        if not self._provider or not self._provider.is_available():
            # 回退到规则引擎
            return TaskDecomposer.decompose(description)
        
        prompt = self.DECOMPOSE_PROMPT.format(description=description)
        
        from core.ai_provider import ChatRequest, Message
        request = ChatRequest(
            messages=[Message("user", prompt)],
            temperature=0.3,
            max_tokens=2048,
        )
        response = self._provider.chat(request)
        
        if response.finish_reason != "stop":
            return TaskDecomposer.decompose(description)
        
        # 解析 JSON 响应
        try:
            import json as json_module
            # 提取 JSON（可能被包裹在 ```json 中）
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            data = json_module.loads(content.strip())
            subtasks_raw = data.get("subtasks", [])
            
            subtasks = []
            for st in subtasks_raw:
                priority_map = {
                    "high": TaskPriority.HIGH,
                    "normal": TaskPriority.NORMAL,
                    "low": TaskPriority.LOW,
                    "critical": TaskPriority.CRITICAL,
                }
                subtasks.append({
                    "name": st.get("name", "未命名任务"),
                    "description": st.get("description", ""),
                    "depends_on": st.get("depends_on", []),
                    "priority": priority_map.get(st.get("priority", "normal"), TaskPriority.NORMAL),
                    "suggested_provider": st.get("suggested_provider", "local"),
                })
            
            return subtasks if subtasks else TaskDecomposer.decompose(description)
            
        except (json_module.JSONDecodeError, KeyError, IndexError):
            return TaskDecomposer.decompose(description)


class ResultAggregator:
    """
    结果聚合器（v2.0 新增）
    
    将多个子任务的执行结果聚合为最终输出：
    - 按依赖关系排序
    - 合并同类结果
    - 生成最终摘要
    """
    
    @staticmethod
    def aggregate(tree: TaskTree) -> Dict:
        """聚合任务树中所有已完成任务的结果"""
        results = []
        errors = []
        
        for task in tree.get_all_tasks():
            if task.status == TaskStatus.COMPLETED:
                results.append({
                    "id": task.id,
                    "name": task.name,
                    "result": str(task.result)[:500] if task.result else "",
                    "provider": task.assigned_provider,
                    "elapsed": round(task.elapsed, 2),
                })
            elif task.status == TaskStatus.FAILED:
                errors.append({
                    "id": task.id,
                    "name": task.name,
                    "error": task.error,
                })
        
        progress = tree.get_progress()
        
        return {
            "success": len(errors) == 0,
            "task_count": progress["total"],
            "completed": progress["completed"],
            "failed": progress["failed"],
            "results": results,
            "errors": errors,
            "summary": f"共 {progress['total']} 个任务，{progress['completed']} 个完成，{progress['failed']} 个失败",
        }
    
    @staticmethod
    def to_markdown(aggregation: Dict) -> str:
        """将聚合结果转换为 Markdown 格式"""
        lines = [
            f"## 任务执行结果",
            f"",
            f"**状态**: {'✅ 全部成功' if aggregation['success'] else '❌ 存在失败'}",
            f"**进度**: {aggregation['completed']}/{aggregation['task_count']} 完成",
            f"",
        ]
        
        if aggregation["results"]:
            lines.append("### 已完成任务")
            lines.append("")
            for r in aggregation["results"]:
                provider_tag = f" `[{r['provider']}]`" if r['provider'] else ""
                lines.append(f"- **{r['name']}**{provider_tag} ({r['elapsed']}s)")
                if r["result"]:
                    lines.append(f"  {r['result'][:200]}")
            lines.append("")
        
        if aggregation["errors"]:
            lines.append("### 失败任务")
            lines.append("")
            for e in aggregation["errors"]:
                lines.append(f"- **{e['name']}**: {e['error']}")
            lines.append("")
        
        return "\n".join(lines)


class TaskEngine(QObject):
    """
    任务分解引擎（v2.0 — 支持 AI 分解 + 跨模型协同）
    
    功能：
    - 规则引擎 + AI 双模式分解大任务为子任务树
    - 拓扑排序确定执行顺序
    - 并行执行无依赖任务
    - 跨模型分配：不同子任务分配给不同 AI 提供商
    - 失败重试和状态追踪
    - 结果聚合和 Markdown 输出
    """
    
    # 信号
    task_added = pyqtSignal(str, str)          # (task_id, name)
    task_status_changed = pyqtSignal(str, str)  # (task_id, status)
    task_completed = pyqtSignal(str, object)    # (task_id, result)
    task_failed = pyqtSignal(str, str)          # (task_id, error)
    all_tasks_completed = pyqtSignal()
    progress_updated = pyqtSignal(dict)         # 进度信息
    task_assigned = pyqtSignal(str, str)        # (task_id, provider_name) — v2.0 新增
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tree: Optional[TaskTree] = None
        self._rule_decomposer = TaskDecomposer()
        self._ai_decomposer: Optional[AIDecomposer] = None
        self._executor: Optional[Callable] = None
        self._provider_map: Dict[str, str] = {}  # task_id → provider_name
        self._lock = threading.Lock()
        self._running = False
        self._parallel_groups: List[List[str]] = []
        self._use_ai_decompose = False
    
    @property
    def tree(self) -> Optional[TaskTree]:
        return self._tree
    
    def enable_ai_decompose(self, ai_provider=None):
        """启用 AI 驱动的任务分解"""
        self._ai_decomposer = AIDecomposer(ai_provider)
        self._use_ai_decompose = True
    
    def disable_ai_decompose(self):
        """禁用 AI 分解，使用规则引擎"""
        self._use_ai_decompose = False
    
    def create_from_description(self, description: str) -> TaskTree:
        """从任务描述创建任务树（支持 AI 分解）"""
        self._tree = TaskTree(description)
        
        # 选择分解器
        if self._use_ai_decompose and self._ai_decomposer:
            subtasks = self._ai_decomposer.decompose(description)
        else:
            subtasks = self._rule_decomposer.decompose(description)
        
        # 先创建所有子任务
        task_ids = []
        for i, st in enumerate(subtasks):
            tid = self._tree.add_task(
                name=st["name"],
                description=st.get("description", ""),
                priority=st.get("priority", TaskPriority.NORMAL),
            )
            task_ids.append(tid)
            
            # 记录建议的 AI 提供商
            suggested = st.get("suggested_provider", "")
            if suggested:
                self._provider_map[tid] = suggested
            
            self.task_added.emit(tid, st["name"])
        
        # 建立依赖关系
        for i, st in enumerate(subtasks):
            for dep_idx in st.get("depends_on", []):
                if dep_idx < len(task_ids):
                    self._tree.add_dependency(task_ids[i], task_ids[dep_idx])
        
        return self._tree
    
    def set_executor(self, executor: Callable[[Task], Any]):
        """设置任务执行回调"""
        self._executor = executor
    
    def assign_provider(self, task_id: str, provider_name: str):
        """手动分配任务给特定 AI 提供商"""
        self._provider_map[task_id] = provider_name
        self.task_assigned.emit(task_id, provider_name)
    
    def get_task_provider(self, task_id: str) -> str:
        """获取任务分配的 AI 提供商"""
        return self._provider_map.get(task_id, "auto")
    
    def get_next_batch(self) -> List[Task]:
        """获取下一批可执行的任务"""
        if not self._tree:
            return []
        return self._tree.get_ready_tasks()
    
    def execute_task(self, task_id: str) -> bool:
        """执行单个任务"""
        if not self._tree or not self._executor:
            return False
        
        task = self._tree.get_task(task_id)
        if not task:
            return False
        
        # 记录分配的提供商
        provider = self._provider_map.get(task_id, "auto")
        task.assigned_provider = provider
        
        self._tree.update_status(task_id, TaskStatus.RUNNING)
        self.task_status_changed.emit(task_id, TaskStatus.RUNNING.value)
        
        try:
            result = self._executor(task)
            self._tree.update_status(task_id, TaskStatus.COMPLETED, result=result)
            self.task_status_changed.emit(task_id, TaskStatus.COMPLETED.value)
            self.task_completed.emit(task_id, result)
            self._update_progress()
            return True
        except Exception as e:
            self._tree.update_status(task_id, TaskStatus.FAILED, error=str(e))
            self.task_status_changed.emit(task_id, TaskStatus.FAILED.value)
            self.task_failed.emit(task_id, str(e))
            self._update_progress()
            return False
    
    def execute_all(self, parallel: bool = False):
        """执行所有任务"""
        if not self._tree:
            return
        
        self._running = True
        self._parallel_groups = self._tree.get_parallel_groups()
        
        if parallel:
            self._execute_parallel()
        else:
            self._execute_sequential()
        
        self._running = False
    
    def _execute_sequential(self):
        """顺序执行所有任务"""
        order = self._tree.get_topological_order()
        for task_id in order:
            if not self._running:
                break
            self.execute_task(task_id)
    
    def _execute_parallel(self):
        """并行执行（按层级）"""
        for group in self._parallel_groups:
            if not self._running:
                break
            
            threads = []
            for task_id in group:
                t = threading.Thread(target=self.execute_task, args=(task_id,))
                t.start()
                threads.append(t)
            
            for t in threads:
                t.join()
    
    def retry_failed(self):
        """重试所有失败的任务"""
        if not self._tree:
            return
        
        for task in self._tree.get_all_tasks():
            if task.can_retry:
                task.status = TaskStatus.PENDING
                self.task_status_changed.emit(task.id, TaskStatus.PENDING.value)
    
    def cancel_all(self):
        """取消所有任务"""
        self._running = False
        if self._tree:
            for task in self._tree.get_all_tasks():
                if task.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING):
                    self._tree.update_status(task.id, TaskStatus.CANCELLED)
                    self.task_status_changed.emit(task.id, TaskStatus.CANCELLED.value)
    
    def aggregate_results(self) -> Dict:
        """聚合所有任务结果"""
        if not self._tree:
            return {"success": False, "summary": "无任务树"}
        return ResultAggregator.aggregate(self._tree)
    
    def get_results_markdown(self) -> str:
        """获取结果的 Markdown 格式"""
        aggregation = self.aggregate_results()
        return ResultAggregator.to_markdown(aggregation)
    
    def _update_progress(self):
        """更新进度"""
        if self._tree:
            progress = self._tree.get_progress()
            self.progress_updated.emit(progress)
            
            if progress["pending"] == 0 and progress["running"] == 0:
                self.all_tasks_completed.emit()
    
    def get_summary(self) -> Dict:
        """获取引擎状态摘要"""
        if not self._tree:
            return {"status": "no_tree"}
        
        progress = self._tree.get_progress()
        parallel_groups = self._tree.get_parallel_groups()
        
        return {
            "status": "running" if self._running else "idle",
            "progress": progress,
            "parallel_groups": len(parallel_groups),
            "topological_order": self._tree.get_topological_order()[:10],
            "task_count": progress["total"],
            "use_ai_decompose": self._use_ai_decompose,
            "provider_assignments": dict(self._provider_map),
        }