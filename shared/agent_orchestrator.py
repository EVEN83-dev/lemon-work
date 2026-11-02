# -*- coding: utf-8 -*-
"""
Agent 统筹协调器 (AgentOrchestrator) — 长周期版本
================================================
[NOTE] 本模块保留用于长周期(24h+)项目调度场景，依赖 SessionContinuity + ProjectLog。
短周期编排请使用 shared.orchestration_engine.OrchestrationEngine。
两者不冲突，可共存。

长周期能力（本模块独有）:
- 心跳超时检测+自动重试/转派
- 会话持续性自动 handoff
- 里程碑驱动总结+广播
- 优先级队列+依赖关系
"""
import os
import sys
import re
import time
import threading
import queue
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

# 修复 Windows 控制台/重定向 GBK 编码问题（含 emoji 的 print 会失败）
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 项目内模块
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from session_continuity import SessionContinuity
from project_log import ProjectLog, EventType


# ============================================================
# 数据结构
# ============================================================

class WorkflowState(Enum):
    """项目工作流状态"""
    INIT = "init"               # 立项
    PLANNING = "planning"       # 规划中
    READY = "ready"             # 准备启动
    RUNNING = "running"         # 进行中
    PAUSED = "paused"           # 暂停
    HANDOFF = "handoff"         # 会话移交中
    COMPLETED = "completed"     # 完成
    ABORTED = "aborted"         # 中止
    ERROR = "error"             # 错误


class TaskState(Enum):
    """任务状态"""
    PENDING = "pending"         # 待派发
    ASSIGNED = "assigned"       # 已分配
    IN_PROGRESS = "in_progress" # 进行中
    COMPLETED = "completed"     # 完成
    FAILED = "failed"           # 失败
    BLOCKED = "blocked"         # 阻塞（依赖未完成）
    SKIPPED = "skipped"         # 跳过


@dataclass
class Task:
    """任务定义"""
    task_id: str
    project_id: str
    title: str
    description: str
    assigned_agent: Optional[str] = None  # 指定 agent_id
    required_role: Optional[str] = None   # 或指定角色，由 orchestrator 分配
    dependencies: List[str] = field(default_factory=list)  # 依赖的其他 task_id
    state: TaskState = TaskState.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress: int = 0  # 0-100
    result: str = ""
    retry_count: int = 0
    max_retries: int = 2
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    """agent 在 orchestrator 中的状态"""
    agent_id: str
    role: str
    name: str
    available: bool = True
    current_task: Optional[str] = None  # 当前执行的 task_id
    last_heartbeat: float = field(default_factory=time.time)
    tasks_completed: int = 0
    tasks_failed: int = 0
    session_handoffs: int = 0  # 会话移交次数
    is_busy: bool = False
    workload_score: float = 0.0  # 工作量评分（0-1，越高越忙）
    total_work_time: float = 0.0  # 总工作时间（秒）


# ============================================================
# Agent 统筹协调器
# ============================================================

class AgentOrchestrator:
    """
    Agent 统筹协调器
    ================
    - 单例运行：每个项目一个 orchestrator
    - 长周期：通过内部循环线程持续调度
    - 异步事件驱动：任务完成 / agent 状态变化 / 会话 handoff 都通过事件回调
    - 容错：单 agent 失败不阻塞整体，自动重试或转派
    """

    # 配置
    HEARTBEAT_TIMEOUT = 120  # 120秒无心跳视为卡死
    ORCHESTRATOR_INTERVAL = 5  # 主循环间隔 5 秒
    MAX_TASK_DURATION = 3600  # 单任务最长 1 小时

    def __init__(self, project_id: str, project_name: str,
                 session_continuity: SessionContinuity,
                 project_log: ProjectLog,
                 multi_instance_manager=None,
                 dispatch_callback: Callable = None):
        """
        Args:
            project_id: 项目 ID
            project_name: 项目名称
            session_continuity: 会话持续性管理器
            project_log: 项目日志
            multi_instance_manager: 多实例管理器（可选，用于真实派发）
            dispatch_callback: 任务派发回调函数 (task, agent_id) -> bool
        """
        self.project_id = project_id
        self.project_name = project_name
        self._sc = session_continuity
        self._pl = project_log
        self._mim = multi_instance_manager
        self._dispatch_cb = dispatch_callback

        self._state = WorkflowState.INIT
        self._agents: Dict[str, AgentState] = {}
        self._tasks: Dict[str, Task] = {}
        self._task_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._lock = threading.RLock()
        self._running = False
        self._orchestrator_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)

        # 记录项目立项
        self._pl.log_project_init(project_id, project_name, "")
        self._state = WorkflowState.PLANNING

    # ============================================================
    # Agent 注册
    # ============================================================

    def register_agent(self, agent_id: str, role: str, name: str = "") -> bool:
        """注册一个 agent 到 orchestrator"""
        with self._lock:
            if agent_id in self._agents:
                return False
            self._agents[agent_id] = AgentState(
                agent_id=agent_id, role=role, name=name or agent_id,
            )
            self._pl.log(EventType.INFO, self.project_id, agent_id=agent_id,
                         title=f"Agent 注册: {name or agent_id} (角色: {role})")
            return True

    def unregister_agent(self, agent_id: str):
        """注销 agent"""
        with self._lock:
            self._agents.pop(agent_id, None)
            self._pl.log(EventType.INFO, self.project_id, agent_id=agent_id,
                         title=f"Agent 注销: {agent_id}")

    def heartbeat(self, agent_id: str, progress: int = None, note: str = ""):
        """agent 心跳：报告自己还活着，可选附带进度"""
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return
            agent.last_heartbeat = time.time()
            if progress is not None and agent.current_task:
                task = self._tasks.get(agent.current_task)
                if task:
                    task.progress = max(task.progress, progress)
                    self._pl.log_agent_progress(self.project_id, agent_id,
                                                  task.task_id, progress, note)

    # ============================================================
    # 任务管理
    # ============================================================

    def add_task(self, task_id: str, title: str, description: str,
                  required_role: str = None, assigned_agent: str = None,
                  dependencies: List[str] = None, priority: int = 0) -> Task:
        """添加任务到队列"""
        with self._lock:
            if task_id in self._tasks:
                return self._tasks[task_id]
            task = Task(
                task_id=task_id,
                project_id=self.project_id,
                title=title,
                description=description,
                required_role=required_role,
                assigned_agent=assigned_agent,
                dependencies=dependencies or [],
            )
            self._tasks[task_id] = task
            # 优先级队列：(priority, created_at, task_id)
            self._task_queue.put((priority, task.created_at, task_id))
            self._pl.log(EventType.INFO, self.project_id,
                         title=f"任务入队: {title}",
                         description=description[:200],
                         metadata={'task_id': task_id, 'priority': priority})
            return task

    def add_milestone(self, milestone_id: str, name: str,
                       tasks: List[Dict]) -> bool:
        """
        添加里程碑（一组任务）
        Args:
            milestone_id: 里程碑 ID
            name: 里程碑名称
            tasks: 任务列表 [{'task_id', 'title', 'description', 'required_role', 'dependencies', 'priority'}, ...]
        """
        with self._lock:
            self._pl.log_milestone(self.project_id, name, f"包含 {len(tasks)} 个任务")
            for t in tasks:
                self.add_task(
                    task_id=t['task_id'],
                    title=t['title'],
                    description=t.get('description', ''),
                    required_role=t.get('required_role'),
                    assigned_agent=t.get('assigned_agent'),
                    dependencies=t.get('dependencies', []),
                    priority=t.get('priority', 0),
                )
            return True

    def mark_task_completed(self, task_id: str, result: str = "") -> bool:
        """agent 报告任务完成"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.state != TaskState.IN_PROGRESS:
                return False

            task.state = TaskState.COMPLETED
            task.completed_at = time.time()
            task.result = result
            task.progress = 100

            # 释放 agent
            if task.assigned_agent:
                agent = self._agents.get(task.assigned_agent)
                if agent:
                    # 累加工作时间
                    if task.started_at:
                        agent.total_work_time += (time.time() - task.started_at)
                    agent.current_task = None
                    agent.is_busy = False
                    agent.tasks_completed += 1

            self._pl.log_agent_completed(self.project_id, task.assigned_agent or "",
                                          task_id, result)
            self._emit('task_completed', task)

            # 主动触发一次派发，让依赖此任务的后继任务立即被分配
            self._dispatch_pending_tasks()
            return True

    def mark_task_failed(self, task_id: str, error: str = "") -> bool:
        """agent 报告任务失败"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            task.retry_count += 1
            task.state = TaskState.FAILED

            # 释放 agent
            if task.assigned_agent:
                agent = self._agents.get(task.assigned_agent)
                if agent:
                    # 累加工作时间（失败也计入）
                    if task.started_at:
                        agent.total_work_time += (time.time() - task.started_at)
                    agent.current_task = None
                    agent.is_busy = False
                    agent.tasks_failed += 1

            self._pl.log_agent_failed(self.project_id, task.assigned_agent or "",
                                       task_id, error)

            # 重试判断
            if task.retry_count <= task.max_retries:
                task.state = TaskState.PENDING
                self._task_queue.put((10, time.time(), task_id))  # 重试优先级提高
                self._pl.log(EventType.WARNING, self.project_id,
                             title=f"任务重试 ({task.retry_count}/{task.max_retries}): {task.title}",
                             description=error[:200])
            else:
                self._pl.log(EventType.ERROR, self.project_id,
                             title=f"任务放弃 (重试次数耗尽): {task.title}",
                             description=error[:200])

            self._emit('task_failed', task)
            return True

    # ============================================================
    # 工作流状态机
    # ============================================================

    def start(self) -> bool:
        """启动工作流（开始 orchestrator 主循环）"""
        with self._lock:
            if self._state in (WorkflowState.RUNNING,):
                return True
            if self._state not in (WorkflowState.PLANNING, WorkflowState.READY,
                                    WorkflowState.PAUSED, WorkflowState.ERROR):
                return False

            self._state = WorkflowState.RUNNING
            self._running = True
            self._stop_event.clear()
            self._pl.log_project_start(self.project_id)

            # 启动 orchestrator 线程
            self._orchestrator_thread = threading.Thread(
                target=self._orchestration_loop,
                name=f"Orchestrator-{self.project_id}",
                daemon=True,
            )
            self._orchestrator_thread.start()
            self._emit('workflow_started', None)
            return True

    def pause(self, reason: str = "") -> bool:
        """暂停工作流"""
        with self._lock:
            if self._state != WorkflowState.RUNNING:
                return False
            self._state = WorkflowState.PAUSED
            self._pl.log_project_pause(self.project_id, reason)
            self._emit('workflow_paused', None)
            return True

    def resume(self) -> bool:
        """恢复工作流"""
        with self._lock:
            if self._state != WorkflowState.PAUSED:
                return False
            self._state = WorkflowState.RUNNING
            self._pl.log_project_resume(self.project_id)
            self._emit('workflow_resumed', None)
            return True

    def stop(self, complete: bool = False) -> bool:
        """停止工作流"""
        with self._lock:
            self._running = False
            self._stop_event.set()
            if complete:
                self._state = WorkflowState.COMPLETED
                self._pl.log_project_complete(self.project_id, "工作流完成")
            else:
                self._state = WorkflowState.ABORTED
                self._pl.log(EventType.PROJECT_ABORT, self.project_id,
                             title="工作中止")
            if self._orchestrator_thread and self._orchestrator_thread.is_alive():
                self._orchestrator_thread.join(timeout=10)
            self._emit('workflow_stopped', None)
            return True

    # ============================================================
    # 主调度循环（核心逻辑）
    # ============================================================

    def _orchestration_loop(self):
        """orchestrator 主循环：持续调度任务到可用 agent"""
        print(f"[Orchestrator] 主循环启动 (project={self.project_id})")
        while not self._stop_event.is_set() and self._running:
            try:
                if self._state == WorkflowState.RUNNING:
                    self._tick()
                time.sleep(self.ORCHESTRATOR_INTERVAL)
            except Exception as e:
                print(f"[Orchestrator] 主循环异常: {e}")
                self._pl.log_error(self.project_id, f"orchestrator 异常: {e}")
                time.sleep(10)  # 异常后等10秒再试
        print(f"[Orchestrator] 主循环结束 (project={self.project_id})")

    def _tick(self):
        """单次调度循环"""
        with self._lock:
            # 1. 检查 agent 心跳，发现卡死的 agent
            self._check_agent_health()

            # 2. 检查 agent 上下文使用情况，触发 handoff
            self._check_session_continuity()

            # 3. 从队列取任务，派发给可用 agent
            self._dispatch_pending_tasks()

            # 4. 检查项目是否所有任务完成
            self._check_project_completion()

    def _check_agent_health(self):
        """检查 agent 健康状态"""
        now = time.time()
        for agent_id, agent in list(self._agents.items()):
            if not agent.is_busy:
                continue
            if now - agent.last_heartbeat > self.HEARTBEAT_TIMEOUT:
                # agent 卡死
                print(f"[Orchestrator] ⚠️ Agent {agent_id} 心跳超时 ({now - agent.last_heartbeat:.0f}s)")
                self._pl.log(EventType.WARNING, self.project_id, agent_id=agent_id,
                             title=f"Agent 心跳超时",
                             description=f"超过 {self.HEARTBEAT_TIMEOUT}s 无心跳")

                # 释放 agent
                if agent.current_task:
                    task = self._tasks.get(agent.current_task)
                    if task and task.state == TaskState.IN_PROGRESS:
                        # 任务超时，标记失败（会触发重试逻辑）
                        self.mark_task_failed(agent.current_task, "agent 心跳超时")

                agent.is_busy = False
                agent.current_task = None

    def _check_session_continuity(self):
        """检查 agent 的会话上下文使用，必要时触发 handoff"""
        if not self._sc:
            return
        try:
            statuses = self._sc.get_all_agents_status()
            for status in statuses:
                if status.get('need_handoff'):
                    agent_id = status['agent_id']
                    print(f"[Orchestrator] 🔄 Agent {agent_id} 上下文耗尽，触发 handoff")
                    old_session = status.get('active_session')
                    # 触发 handoff
                    new_session = self._sc.handoff_session(
                        agent_id,
                        summary=f"由 orchestrator 自动触发，token={status['current_tokens']}"
                    )
                    agent = self._agents.get(agent_id)
                    if agent:
                        agent.session_handoffs += 1
                    self._pl.log_session_handed_off(
                        self.project_id, agent_id,
                        old_session or "", new_session.session_id,
                        reason=f"上下文 token={status['current_tokens']} 超阈值 {status['threshold']}"
                    )
        except Exception as e:
            print(f"[Orchestrator] 会话检查异常: {e}")

    def _dispatch_pending_tasks(self):
        """派发待处理任务到可用 agent"""
        # 取出非空队列
        dispatched = 0
        skipped_blocked = 0
        max_blocked = 50  # 最多跳过 50 个被阻塞的任务后退出（避免死循环）
        while dispatched < 10:  # 单轮最多派10个任务
            if self._task_queue.empty():
                break
            try:
                priority, _, task_id = self._task_queue.get_nowait()
            except queue.Empty:
                break

            task = self._tasks.get(task_id)
            if not task:
                continue

            # 检查依赖
            if not self._check_dependencies(task):
                # 依赖未满足，重新入队（降优先级）
                self._task_queue.put((priority + 1, time.time(), task_id))
                skipped_blocked += 1
                if skipped_blocked >= max_blocked:
                    break  # 避免死循环
                continue

            # 找可用 agent
            agent = self._find_available_agent(task)
            if not agent:
                # 无可用 agent，重新入队
                self._task_queue.put((priority, time.time(), task_id))
                break  # 后续可能也无 agent，先退出

            # 派发
            self._dispatch_task(task, agent)
            dispatched += 1
            skipped_blocked = 0  # 成功派发后重置阻塞计数

    def _check_dependencies(self, task: Task) -> bool:
        """检查任务依赖是否全部完成"""
        for dep_id in task.dependencies:
            dep = self._tasks.get(dep_id)
            if not dep or dep.state != TaskState.COMPLETED:
                return False
        return True

    def _find_available_agent(self, task: Task) -> Optional[AgentState]:
        """找一个可用的 agent（委托给工作量平衡策略）"""
        return self._find_available_agent_balanced(task)

    def _calculate_workload_score(self, agent: AgentState) -> float:
        """
        计算工作量评分（0-1），越高表示越忙。
        综合考虑：
        - 当前是否忙碌 (is_busy → 1.0)
        - 已完成任务数占比（相对于所有 agent 的平均值）
        - 近期失败率
        - 工作时间
        """
        # 忙碌权重最高
        busy_score = 1.0 if agent.is_busy else 0.0

        # 任务数占比：相对于所有 agent 的平均值
        all_agents = list(self._agents.values())
        avg_completed = (sum(a.tasks_completed for a in all_agents) / len(all_agents)) if all_agents else 1.0
        task_ratio_score = min(agent.tasks_completed / max(avg_completed, 1.0), 1.0)

        # 近期失败率
        total_tasks = agent.tasks_completed + agent.tasks_failed
        fail_rate = (agent.tasks_failed / total_tasks) if total_tasks > 0 else 0.0

        # 工作时间评分：相对于最长工作时间的占比
        max_work_time = max((a.total_work_time for a in all_agents), default=1.0) or 1.0
        work_time_score = min(agent.total_work_time / max_work_time, 1.0)

        # 加权综合评分：忙碌 40%，任务占比 25%，失败率 20%，工作时间 15%
        score = (busy_score * 0.4
                 + task_ratio_score * 0.25
                 + fail_rate * 0.20
                 + work_time_score * 0.15)

        # 缓存评分
        agent.workload_score = round(score, 4)
        return agent.workload_score

    def _find_available_agent_balanced(self, task: Task) -> Optional[AgentState]:
        """
        使用工作量平衡策略选择 agent：
        1. 优先匹配角色
        2. 在同角色中选择工作量评分最低的
        3. 考虑任务依赖亲和性（如果依赖的任务由同一 agent 完成，优先继续）
        """
        # 1. 指定 agent（最高优先级，不使用平衡策略）
        if task.assigned_agent:
            agent = self._agents.get(task.assigned_agent)
            if agent and agent.available and not agent.is_busy:
                return agent
            return None

        # 2. 按角色匹配 + 工作量平衡 + 亲和性
        if task.required_role:
            candidates = [a for a in self._agents.values()
                          if a.role == task.required_role and a.available and not a.is_busy]
        else:
            candidates = [a for a in self._agents.values()
                          if a.available and not a.is_busy]

        if not candidates:
            return None

        # 2.1 任务依赖亲和性：检查依赖任务是否由某个候选 agent 完成
        affinity_agent = None
        if task.dependencies:
            for dep_id in task.dependencies:
                dep_task = self._tasks.get(dep_id)
                if dep_task and dep_task.assigned_agent:
                    dep_agent = self._agents.get(dep_task.assigned_agent)
                    if dep_agent and dep_agent in candidates:
                        affinity_agent = dep_agent
                        break

        # 2.2 计算所有候选的工作量评分
        scored = [(a, self._calculate_workload_score(a)) for a in candidates]
        scored.sort(key=lambda x: x[1])

        # 2.3 亲和性 agent 的工作量评分如果不超过最低分的 1.3 倍，优先选择
        if affinity_agent:
            affinity_score = self._calculate_workload_score(affinity_agent)
            min_score = scored[0][1]
            if affinity_score <= min_score * 1.3 + 0.1:
                return affinity_agent

        # 2.4 返回工作量评分最低的
        return scored[0][0]

    def _dispatch_task(self, task: Task, agent: AgentState):
        """实际派发任务到 agent"""
        task.state = TaskState.ASSIGNED
        task.started_at = time.time()
        task.assigned_agent = agent.agent_id
        agent.current_task = task.task_id
        agent.is_busy = True

        self._pl.log_task_dispatched(self.project_id,
                                       "orchestrator", agent.agent_id,
                                       task.task_id, task.title)

        # 调用真实派发回调（如果有）
        if self._dispatch_cb:
            try:
                success = self._dispatch_cb(task, agent.agent_id)
                if success:
                    task.state = TaskState.IN_PROGRESS
                    self._pl.log_agent_started(self.project_id, agent.agent_id, task.task_id)
                else:
                    self.mark_task_failed(task.task_id, "派发回调返回失败")
            except Exception as e:
                self.mark_task_failed(task.task_id, f"派发回调异常: {e}")
        else:
            # 无回调，仅标记为进行中（用于测试）
            task.state = TaskState.IN_PROGRESS
            self._pl.log_agent_started(self.project_id, agent.agent_id, task.task_id)

    def _check_project_completion(self):
        """检查项目是否所有任务完成"""
        if not self._tasks:
            return
        all_done = all(t.state in (TaskState.COMPLETED, TaskState.SKIPPED)
                       for t in self._tasks.values())
        if all_done and self._state == WorkflowState.RUNNING:
            print(f"[Orchestrator] ✅ 项目 {self.project_id} 所有任务完成")
            self.stop(complete=True)

    # ============================================================
    # 事件订阅
    # ============================================================

    def on(self, event_name: str, callback: Callable):
        """订阅事件：task_completed / task_failed / workflow_started / ..."""
        self._callbacks[event_name].append(callback)

    def _emit(self, event_name: str, data: Any):
        for cb in self._callbacks.get(event_name, []):
            try:
                cb(data)
            except Exception as e:
                print(f"[Orchestrator] 事件回调异常 ({event_name}): {e}")

    # ============================================================
    # 状态查询
    # ============================================================

    def get_status(self) -> Dict:
        """获取 orchestrator 完整状态"""
        with self._lock:
            tasks_by_state = defaultdict(int)
            for t in self._tasks.values():
                tasks_by_state[t.state.value] += 1
            return {
                'project_id': self.project_id,
                'project_name': self.project_name,
                'state': self._state.value,
                'running': self._running,
                'agents': [{
                    'agent_id': a.agent_id,
                    'role': a.role,
                    'name': a.name,
                    'is_busy': a.is_busy,
                    'current_task': a.current_task,
                    'tasks_completed': a.tasks_completed,
                    'tasks_failed': a.tasks_failed,
                    'session_handoffs': a.session_handoffs,
                    'last_heartbeat_ago': time.time() - a.last_heartbeat,
                } for a in self._agents.values()],
                'tasks_total': len(self._tasks),
                'tasks_by_state': dict(tasks_by_state),
                'queue_size': self._task_queue.qsize(),
            }

    def get_workload_report(self) -> Dict:
        """返回所有 agent 的工作量报告"""
        with self._lock:
            agents = list(self._agents.values())
            total_completed = sum(a.tasks_completed for a in agents)
            total_failed = sum(a.tasks_failed for a in agents)
            total_work_time = sum(a.total_work_time for a in agents)
            avg_completed = (total_completed / len(agents)) if agents else 0.0

            agent_reports = []
            for a in agents:
                score = self._calculate_workload_score(a)
                total_tasks = a.tasks_completed + a.tasks_failed
                fail_rate = (a.tasks_failed / total_tasks) if total_tasks > 0 else 0.0
                agent_reports.append({
                    'agent_id': a.agent_id,
                    'name': a.name,
                    'role': a.role,
                    'is_busy': a.is_busy,
                    'workload_score': score,
                    'tasks_completed': a.tasks_completed,
                    'tasks_failed': a.tasks_failed,
                    'fail_rate': round(fail_rate, 4),
                    'total_work_time': round(a.total_work_time, 2),
                    'current_task': a.current_task,
                    'session_handoffs': a.session_handoffs,
                })

            # 按工作量评分降序排列（最忙的在前）
            agent_reports.sort(key=lambda x: x['workload_score'], reverse=True)

            return {
                'project_id': self.project_id,
                'timestamp': time.time(),
                'total_completed': total_completed,
                'total_failed': total_failed,
                'total_work_time': round(total_work_time, 2),
                'avg_completed': round(avg_completed, 2),
                'agent_count': len(agents),
                'agents': agent_reports,
            }

    def print_status(self):
        """打印当前状态（用于调试）"""
        s = self.get_status()
        print(f"\n[Orchestrator] 项目: {s['project_name']} ({s['project_id']})")
        print(f"  状态: {s['state']}  运行中: {s['running']}")
        print(f"  任务: {s['tasks_total']} 个 (队列 {s['queue_size']})")
        for state, count in s['tasks_by_state'].items():
            print(f"    - {state}: {count}")
        print(f"  Agents: {len(s['agents'])} 个")
        for a in s['agents']:
            busy = "忙" if a['is_busy'] else "闲"
            print(f"    - {a['name']}({a['role']}) [{busy}] 完成={a['tasks_completed']} 失败={a['tasks_failed']} handoff={a['session_handoffs']}")

    # ============================================================
    # 里程碑驱动总结
    # ============================================================

    def add_milestone_with_tracking(self, milestone_id: str, name: str,
                                     tasks: List[Dict],
                                     broadcast_on_complete: bool = True) -> bool:
        """
        添加里程碑并启用完成追踪

        里程碑所有任务完成时自动触发：
        1. 生成里程碑总结报告
        2. 广播给所有 agent
        3. 记录到 ProjectLog

        Args:
            milestone_id: 里程碑 ID
            name: 里程碑名称
            tasks: 任务列表
            broadcast_on_complete: 完成时是否广播
        """
        with self._lock:
            # 存储里程碑元信息
            self._milestones: Dict[str, Dict] = getattr(self, '_milestones', {})
            self._milestones[milestone_id] = {
                "id": milestone_id,
                "name": name,
                "task_ids": [t['task_id'] for t in tasks],
                "broadcast_on_complete": broadcast_on_complete,
                "completed": False,
                "completed_at": None,
                "summary": None,
                "created_at": time.time(),
            }

            # 添加任务（复用已有方法）
            self.add_milestone(milestone_id, name, tasks)

            # 订阅任务完成事件（仅订阅一次）
            if not getattr(self, '_milestone_tracking_installed', False):
                self.on('task_completed', self._on_task_completed_for_milestone)
                self._milestone_tracking_installed = True

            return True

    def _on_task_completed_for_milestone(self, task_data):
        """任务完成时检查里程碑是否完成"""
        with self._lock:
            milestones = getattr(self, '_milestones', {})
            for mid, ms in milestones.items():
                if ms["completed"]:
                    continue
                task_ids = ms["task_ids"]
                # 检查此里程碑的所有任务是否都已完成
                all_done = all(
                    self._tasks.get(tid) and self._tasks[tid].state == TaskState.COMPLETED
                    for tid in task_ids
                )
                if all_done:
                    ms["completed"] = True
                    ms["completed_at"] = time.time()
                    # 生成总结
                    summary = self._generate_milestone_summary(mid, ms)
                    ms["summary"] = summary

                    # 广播
                    if ms["broadcast_on_complete"]:
                        self._broadcast_milestone_completion(mid, ms, summary)

    def _generate_milestone_summary(self, milestone_id: str, milestone: Dict) -> Dict:
        """生成里程碑总结报告"""
        task_ids = milestone["task_ids"]
        tasks_info = []
        total_duration = 0.0

        for tid in task_ids:
            task = self._tasks.get(tid)
            if task:
                duration = 0.0
                if task.started_at and task.completed_at:
                    duration = task.completed_at - task.started_at
                    total_duration += duration
                tasks_info.append({
                    "task_id": tid,
                    "title": task.title,
                    "agent": task.assigned_agent or "未分配",
                    "state": task.state.value,
                    "duration": round(duration, 2),
                    "retry_count": task.retry_count,
                })

        # 按 agent 分组统计
        agent_stats: Dict[str, Dict] = {}
        for ti in tasks_info:
            agent = ti["agent"]
            if agent not in agent_stats:
                agent_stats[agent] = {"tasks": 0, "total_duration": 0.0}
            agent_stats[agent]["tasks"] += 1
            agent_stats[agent]["total_duration"] += ti["duration"]

        summary = {
            "milestone_id": milestone_id,
            "milestone_name": milestone["name"],
            "completed_at": datetime.fromtimestamp(milestone["completed_at"]).strftime('%Y-%m-%d %H:%M:%S'),
            "total_tasks": len(task_ids),
            "total_duration": round(total_duration, 2),
            "tasks": tasks_info,
            "agent_stats": agent_stats,
            "created_at": datetime.fromtimestamp(milestone["created_at"]).strftime('%Y-%m-%d %H:%M:%S'),
        }

        return summary

    def _broadcast_milestone_completion(self, milestone_id: str,
                                         milestone: Dict, summary: Dict):
        """广播里程碑完成"""
        # 1. 记录到 ProjectLog
        self._pl.log_milestone(
            self.project_id,
            f"✅ 里程碑完成: {milestone['name']}",
            f"共 {summary['total_tasks']} 个任务，耗时 {summary['total_duration']:.1f}s"
        )

        # 2. 通过事件总线广播
        self._emit('milestone_completed', {
            'milestone_id': milestone_id,
            'milestone_name': milestone['name'],
            'summary': summary,
        })

        # 3. 通知所有 agent（通过心跳回调）
        for agent_id, agent in self._agents.items():
            self._pl.log(EventType.INFO, self.project_id, agent_id=agent_id,
                         title=f"里程碑完成通知: {milestone['name']}",
                         description=f"共 {summary['total_tasks']} 个任务已完成")

        print(f"[Orchestrator] 🎯 里程碑完成: {milestone['name']} "
              f"({summary['total_tasks']} 个任务, {summary['total_duration']:.1f}s)")

    def get_milestones(self) -> List[Dict]:
        """获取所有里程碑状态"""
        milestones = getattr(self, '_milestones', {})
        result = []
        for mid, ms in milestones.items():
            entry = dict(ms)
            # 计算进度
            task_ids = ms["task_ids"]
            completed_count = sum(
                1 for tid in task_ids
                if self._tasks.get(tid) and self._tasks[tid].state == TaskState.COMPLETED
            )
            entry["progress"] = round(completed_count / max(len(task_ids), 1) * 100, 1)
            entry["completed_tasks"] = completed_count
            result.append(entry)
        return result


# ============================================================
# 380B: 小模型编排骨架 — guided loop（与上方长周期 AgentOrchestrator 独立）
# ============================================================

import json
import logging as _logging
import concurrent.futures
import hashlib

_guided_logger = _logging.getLogger("agent_orchestrator.guided")

_CHECKPOINT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "data", "orchestrator_state")
os.makedirs(_CHECKPOINT_DIR, exist_ok=True)


def _task_id_for(prompt: str) -> str:
    return hashlib.md5(prompt.encode("utf-8")).hexdigest()[:12]


def _classify_complexity_lite(prompt: str) -> str:
    """384A-2: 轻量复杂度分类（纯代码规则，禁用 LLM 预判）。

    385B-1 词边界修复（二轮）：
    - 英文指示词改 \b 词边界正则（"then" 不得命中 "strengthen"）
    - 中文单字指示词（先/再/并）降权为 0.5（"合并/首先/再次" 单字易误伤），
      且弱命中最多计 1.0，需与强指示词/长度信号共现才判 complex

    分 simple / complex 两档：
    - simple: 短问题、无多实体/多约束信号 → 2 步短模板（执行+校验汇总）
    - complex: 多步信号、多实体、长问题 → 维持 3+ 步模板
    """
    # 强指示词（多字词/短语，直接子串匹配）
    _COMPLEX_INDICATORS_STRONG = [
        "然后", "接着", "之后", "同时", "并且", "还要",
        "第一步", "第二步", "依次", "多步", "分步", "分别",
        "多个", "所有", "全部", "整个", "完整",
        "生成并", "写代码并", "搜索并", "分析并",
    ]
    # 弱指示词（单字，0.5 计分，上限 1.0）
    _COMPLEX_INDICATORS_WEAK = ["先", "再", "并"]
    # 英文指示词（词边界正则，杜绝 strengthen→then 类误命中）
    _COMPLEX_PATTERNS_EN = [
        r"\bfirst\b", r"\bthen\b", r"\bafter\b", r"\bnext\b",
        r"\bstep by step\b", r"\band then\b", r"\bafter that\b",
        r"\balso\b", r"\badditionally\b",
    ]
    _MULTI_ENTITY_PATTERNS = [
        r"和.{1,6}都", r"分别", r"两者", r"三个", r"多个",
        r"\bboth\b", r"\beach of\b", r"\ball of\b", r"\bmultiple\b",
    ]
    prompt_len = len(prompt)
    _lower = prompt.lower()
    _strong_hits = sum(1 for kw in _COMPLEX_INDICATORS_STRONG if kw in prompt)
    _en_hits = sum(1 for pat in _COMPLEX_PATTERNS_EN if re.search(pat, _lower))
    _weak_hits = min(sum(1 for kw in _COMPLEX_INDICATORS_WEAK if kw in prompt), 2)
    _complex_score = _strong_hits + _en_hits + 0.5 * _weak_hits
    _multi_entity = sum(1 for pat in _MULTI_ENTITY_PATTERNS if re.search(pat, prompt))
    # ★390B-4: 判定依据审计（score/entity/len 随分类日志落盘，供 checkpoint 追溯）
    _tier = None
    if _complex_score >= 3 or prompt_len > 400 or (_multi_entity >= 1 and _complex_score >= 1):
        _tier = "complex"
    elif _complex_score >= 2 or _multi_entity >= 1:
        _tier = "medium"
    elif _complex_score == 0 and prompt_len <= 200:
        _tier = "simple"
    elif _complex_score <= 1 and prompt_len <= 300:
        _tier = "simple"
    else:
        _tier = "medium"
    try:
        _guided_logger.info(
            f"[390B-4] 复杂度三档判定: tier={_tier} score={_complex_score} "
            f"entity={_multi_entity} len={prompt_len}")
    except Exception:
        pass
    return _tier


# ★390B-1: 任务类型守卫 —— 创作类禁用执行类工具
# 背景（385B-1 MISS 主因）：写作题被 execute_code 接管（"代码执行器在写作文"）。
# 纯规则判定（无 LLM 依赖）；命中 → 编排层做三重防护：
#   ① system 硬规则注入（禁执行类工具 + 指定创作通道）
#   ② candidate_skills 收紧为创作/读写类
#   ③ checkpoint 记 guard_triggered
_CREATIVE_KEYWORDS = [
    "写作", "写一", "写篇", "写首", "写个故事", "写封", "作文", "文案", "创作",
    "改写", "润色", "扩写", "缩写", "总结一下", "帮我写", "写一份", "写个周报",
    "写封邮件", "写段", "编写一段", "翻译", "译成", "译为",
    "write an", "write a", "essay", "draft", "rewrite", "polish", "summarize",
]
# 执行类工具（创作类任务禁止）：编码执行/命令行/系统级
_EXEC_TOOLS = {"execute_code", "terminal_run", "run_command", "docker_skill",
               "package_manager", "deploy_helper"}


def _classify_task_type(prompt: str) -> str:
    """★390B-1: 任务类型判定（纯规则）。creative=创作/翻译/总结类；general=其他。"""
    _lower = (prompt or "").lower()
    for kw in _CREATIVE_KEYWORDS:
        if kw in _lower or kw in (prompt or ""):
            return "creative"
    return "general"


# 385B-1: simple 档 2 步短模板（执行 + 校验汇总）。
# 384A-2 首轮"simple 直通 agent_chat"被证伪（8/14，直通退化为裸能力）——
# 简单题仍走编排护栏，仅步数压缩为 2。
_SIMPLE_PLAN_TEMPLATE = [
    {
        "step_id": "simple_execute",
        "goal": "执行用户请求",
        "candidate_skills": [],
        "criterion": {"type": "return_success", "description": "工具调用成功"},
    },
    {
        "step_id": "simple_verify",
        "goal": "校验上一步结果并给出简要汇总（缺漏则补调工具）",
        "candidate_skills": [],
        "criterion": {"type": "field_complete",
                      "description": "结论字段齐备（无显式字段时以本步完成为准）"},
    },
]


def run_guided_loop(engine_manager, prompt: str, engine: str = "ollama", **kwargs) -> Dict[str, Any]:
    """小模型编排循环（380B 核心入口）。

    流程：
        ① 规则分派：task_classifier + route_skills 定域
        ② 取计划：get_plan(domain, prompt)
        ③ 单步执行：构造短 system + 进度注入 + 工具菜单 + 环形记忆
           → 调引擎 generate_with_tools
           → 无 tool_calls 则重试 1 次
        ④ 判据验收：代码判（产物存在 / SkillResult.success / 关键字段）
           不过→重试 1 次→仍不过→标记 failed，继续
        ⑤ 环形记忆：每步摘要追加到 ring buffer（≤10 条滚动）
        ⑥ 全步完成→本地汇总

    首版 fallback：若编排流程中任何环节异常，回退到 agent_chat 原路径（零回归）。

    Args:
        engine_manager: EngineManager 实例
        prompt: 用户输入
        engine: 引擎名（默认 ollama）
        **kwargs: 透传给 agent_chat 的参数

    Returns:
        Dict — 与 agent_chat 返回格式一致，额外含 guided_loop=True 标记
    """
    try:
        from shared.plan_templates import get_plan
        from shared.skill_domain_router import route_skills, route_domains
        from shared.skill_trajectory import recall_similar_trajectories
        from core.task_classifier import get_task_classifier

        _guided_logger.info(f"[382B] run_guided_loop 入口: engine={engine}, prompt={prompt[:80]}")

        # ① 规则分派
        classifier = get_task_classifier()
        classification = classifier.classify(prompt)
        _all_tools = engine_manager._get_tool_definitions()
        _available = {t.get("function", {}).get("name", "") for t in _all_tools}
        _routed_skills = route_skills(prompt, available=_available)
        _domains = route_domains(prompt)
        _domain = _domains[0] if _domains else "general"
        _guided_logger.info(f"[382B] 分派: domain={_domain}, complexity={classification.complexity.value}, skills={sorted(_routed_skills)[:6]}")

        # ★390B-1: 任务类型守卫 —— 创作类（写作/翻译/总结）禁执行类工具。
        # 385B-1 MISS 主因：写作题被 execute_code 接管。三重防护：
        #   ① plan 每步 goal 前缀硬规则（进单步 system）
        #   ② candidate_skills 剔除执行类并收紧为创作/读写通道
        #   ③ guard_triggered 标记进 result（checkpoint 步骤日志同步打点）
        _task_type = _classify_task_type(prompt)
        _guard_prefix = ""
        if _task_type == "creative":
            _guard_prefix = (
                "【创作类任务守卫：本任务为写作/翻译/总结类，禁止调用 execute_code/"
                "terminal_run 等执行类工具；应使用 translator/office_generator/"
                "academic_writer/write_file 等创作与读写工具完成】\n")
            _routed_skills = {s for s in _routed_skills if s not in _EXEC_TOOLS}
            _guided_logger.info("[390B-1] creative 守卫生效: 剔除执行类路由 + 硬规则注入")

        # ② 取计划
        plan = get_plan(_domain, prompt)
        if _task_type == "creative":
            for _ps in plan:
                _ps["candidate_skills"] = [s for s in _ps.get("candidate_skills", [])
                                           if s not in _EXEC_TOOLS]
                _ps["goal"] = _guard_prefix + str(_ps.get("goal", ""))
        _plan_template_name = _domain if _domain in ("research", "math", "file_ops", "code_review", "system") else "general"

        # 385B-1: 动态复杂度分流二轮 — simple 档走 2 步短模板（保留编排护栏）。
        # 384A-2 首轮"直通 agent_chat"已证伪（8/14 < 13/15，直通退化为裸能力）。
        _lite_class = _classify_complexity_lite(prompt)
        _classification_reason = (f"lite={_lite_class}, len={len(prompt)}, "
                                  f"domain={_domain}, task_type={_task_type}")
        if _lite_class == "simple":
            _guided_logger.info(
                f"[385B-1] simple 档: 2 步短模板编排（执行+校验汇总）")
            _simple_plan = [dict(s) for s in _SIMPLE_PLAN_TEMPLATE]
            if _task_type == "creative":
                for _ps in _simple_plan:
                    _ps["candidate_skills"] = [s for s in _ps.get("candidate_skills", [])
                                               if s not in _EXEC_TOOLS]
                    _ps["goal"] = _guard_prefix + str(_ps.get("goal", ""))
            # 385B-3: 调研类任务即使 simple 档也前置目录快照（防猜路径/防本机当竞品）
            if _domain in ("research", "general"):
                from shared.plan_templates import get_dir_snapshot_step
                _simple_plan = [get_dir_snapshot_step()] + _simple_plan
                _guided_logger.info("[385B-3] simple 档调研类: 前置 dir_snapshot 纯代码子步")
            _r = _execute_guided_plan(
                engine_manager, prompt, engine, _simple_plan,
                _routed_skills, _domain, classification,
                _plan_template_name="simple_2step",
                _classification_reason=_classification_reason,
                _routed_domains=_domains,
                **({"_exclude_tools": sorted(_EXEC_TOOLS)} if _task_type == "creative" else {}),
                **kwargs
            )
            if _task_type == "creative":
                _r["guard_triggered"] = True
                _r["task_type"] = "creative"
            return _r

        # ★390B-4: complex 档追加校验步（域模板 3 步 + 校验 = 4 步，预算 5 覆盖）
        if _lite_class == "complex":
            plan.append({
                "step_id": "universal_verify",
                "goal": "校验前序步骤产出的完整性与正确性，缺漏补做，并给出简短汇总",
                "candidate_skills": [],
                "criterion": {"type": "field_complete",
                              "description": "汇总字段齐备（无显式字段时以本步完成为准）"},
            })
            _guided_logger.info("[390B-4] complex 档: 追加 universal_verify 校验步")
        # ③~⑥ 编排主体
        _r = _execute_guided_plan(
            engine_manager, prompt, engine, plan,
            _routed_skills, _domain, classification,
            _plan_template_name=_plan_template_name,
            _classification_reason=_classification_reason,
            _routed_domains=_domains,
            **({"_exclude_tools": sorted(_EXEC_TOOLS)} if _task_type == "creative" else {}),
            **kwargs
        )
        if _task_type == "creative":
            _r["guard_triggered"] = True
            _r["task_type"] = "creative"
        return _r

    except Exception as e:
        _guided_logger.warning(f"[380B] 编排异常，回退 agent_chat: {e}")
        _fallback_kwargs = dict(kwargs)
        _fallback_kwargs["_inside_guided_loop"] = True
        return engine_manager.agent_chat(prompt, engine=engine, **_fallback_kwargs)

def _execute_guided_plan(engine_manager, prompt, engine, plan,
                          routed_skills, domain, classification,
                          _plan_template_name="general",
                          _classification_reason="",
                          _routed_domains=None,
                          **kwargs) -> Dict[str, Any]:
    """执行编排计划 — 每步调 agent_chat（复用全部防护），注入短 system + 进度。"""
    start_time = time.time()
    _ring_buffer = []
    all_tool_calls_made = []
    step_results = []
    _step_content = ""
    _step_tool_calls = []
    _dir_snapshot = ""   # 385B-3: 目录快照（code_exec 子步产出，注入后续 LLM 步）
    _MAX_RING = 10

    # 385B-2: 预算口径并表 — 单一真源 engine_manager._STEP_BUDGETS["guided_loop"]。
    # engine_manager 实例经参数传入（_execute_guided_plan 首参），直接读实例属性，
    # 无需 import engine_manager → 天然规避循环导入。
    # 383A 遗留收尾：删除本地 _BUDGET_MAP 与硬编码 _MAX_STEP_ITERS=6（双源必漂移）。
    _budgets_tbl = getattr(engine_manager, "_STEP_BUDGETS", {}).get("guided_loop", {})
    if (not _budgets_tbl
            or {k for k in _budgets_tbl if not k.startswith("_")} != {"simple", "moderate", "complex"}
            or (_budgets_tbl.get("simple"), _budgets_tbl.get("moderate"),
                _budgets_tbl.get("complex")) != (2, 3, 5)
            or _budgets_tbl.get("_step_iters") != 6):
        # fail-fast：口径异常立即暴露，禁止静默回退本地魔法数字
        raise RuntimeError(
            "[385B-2] engine_manager._STEP_BUDGETS['guided_loop'] 口径异常: "
            f"{_budgets_tbl!r}（期望 simple=2/moderate=3/complex=5, _step_iters=6）")
    _MAX_STEP_ITERS = _budgets_tbl["_step_iters"]

    # B1: 提取流式回调（复用 agent_chat 的 stream_callback 通道）
    _stream_cb = kwargs.get("stream_callback", None)

    # B2: 任务 ID + 断点续跑检测
    _task_id = _task_id_for(prompt)
    _resume_from = 0
    _checkpoint_file = os.path.join(_CHECKPOINT_DIR, f"{_task_id}.json")
    if os.path.exists(_checkpoint_file):
        try:
            with open(_checkpoint_file, "r", encoding="utf-8") as f:
                _cp = json.load(f)
            _resume_from = _cp.get("current_step_idx", 0)
            _ring_buffer = _cp.get("ring_buffer", [])
            _guided_logger.info(f"[382B] 断点续跑: task={_task_id}, 从步骤 {_resume_from} 继续")
        except Exception:
            _resume_from = 0

    # B3.3: 任务级预算器 — 按复杂度映射步数上限
    # 385B-2: 预算并表 — 读上方已校验的 _STEP_BUDGETS["guided_loop"]（单一真源）
    _complexity_val = getattr(classification, 'complexity', None)
    _complexity_str = _complexity_val.value if hasattr(_complexity_val, 'value') else str(_complexity_val) if _complexity_val else "moderate"
    _step_budget = _budgets_tbl.get(_complexity_str, 3)
    # 385B-3: 预算裁剪只对 LLM 步生效 —— code_exec 纯代码子步（目录快照）不占预算名额
    _code_steps = [s for s in plan if s.get("code_exec")]
    _llm_steps = [s for s in plan if not s.get("code_exec")]
    if len(_llm_steps) > _step_budget:
        _guided_logger.info(
            f"[382B] LLM 计划 {len(_llm_steps)} 步超预算({_step_budget}), 裁剪"
            f"（code 子步 {len(_code_steps)} 步不占预算）")
        plan = _code_steps + _llm_steps[:_step_budget]

    # B5: 模板白盒化 — 计划卡发射（命中域/模板名/每步判据类型）
    _template_info = {
        "domain": domain,
        "template_name": _plan_template_name,
        "total_steps": len(plan),
        "step_criteria": [s.get("criterion", {}).get("type", "return_success") for s in plan],
        "classification": _classification_reason,
    }
    if _stream_cb:
        _stream_cb(f"\n📋 命中 {domain} 域模板({len(plan)}步), 判据: {', '.join(_template_info['step_criteria'])}\n")
    try:
        engine_manager.tool_call_made.emit({
            "name": "[编排] 计划模板",
            "arguments": {"domain": domain, "template": _plan_template_name},
            "result": f"命中 {domain} 域模板({len(plan)}步), 判据类型: {', '.join(_template_info['step_criteria'])}",
            "success": True,
            "guided_step": True,
            "step_id": "plan_template",
            "template_info": _template_info,
        })
    except Exception:
        pass

    # ★391B-2: 跨步上下文水位跟踪器（每步 result 的 context_tokens 峰值；
    #   超 num_ctx 80% 时给后续步注入压缩指令，事件入 checkpoint 审计）
    _ctx_watermark = {"peak": 0, "hinted": []}
    for step_idx, step in enumerate(plan):
        step_id = step.get("step_id", f"step_{step_idx+1}")
        step_goal = step.get("goal", "")
        candidates = step.get("candidate_skills", [])
        criterion = step.get("criterion", {})

        # B2: 跳过已完成步（断点续跑）
        if step_idx < _resume_from:
            step_results.append({
                "step_id": step_id, "goal": step_goal,
                "passed": True, "needs_escalation": False,
                "tool_calls": 0, "resumed": True,
            })
            _guided_logger.info(f"[382B] 跳过已完成步: {step_id}")
            continue

        # B2: 检查中断信号
        if engine_manager._is_cancelled():
            _guided_logger.info(f"[382B] 中断信号，停止于步骤 {step_id}")
            _save_checkpoint(_checkpoint_file, step_idx, _ring_buffer, step_results, prompt,
                             _classification_reason)
            break

        _guided_logger.info(f"[382B] 步骤 {step_idx+1}/{len(plan)}: {step_id} - {step_goal}")

        # B1: 流式播报各步目标
        if _stream_cb:
            _stream_cb(f"\n▶ 步骤 {step_idx+1}/{len(plan)}: {step_goal}\n")

        # 385B-3: 纯代码子步（code_exec）——直调注册表执行，不耗模型轮次。
        # 产出目录快照注入后续 LLM 步 system，消除"猜测路径首调失败"与本机目录误判。
        if step.get("code_exec"):
            _ce = step["code_exec"]
            _ce_tool = _ce.get("tool", "list_directory")
            _ce_args = dict(_ce.get("args", {"path": "."}))
            try:
                from standard_mode.core.skills_registry import get_skills_registry
                _reg = get_skills_registry()
                _sr = _reg.execute(_ce_tool, _ce_args)
                _ce_ok = bool(getattr(_sr, "success", True))
                _ce_out = str(getattr(_sr, "output", _sr) or "")[:1500]
            except Exception as _ce_err:  # noqa: BLE001
                _ce_ok, _ce_out = False, f"目录快照执行失败: {_ce_err}"
            if _ce_ok:
                _dir_snapshot = _ce_out
            _ce_desc = "目录快照✓" if _ce_ok else "目录快照✗"
            _guided_logger.info(f"[385B-3] code 子步 {step_id}: {_ce_tool}({_ce_args}) → {_ce_desc}")
            all_tool_calls_made.append({
                "name": _ce_tool, "args": _ce_args, "success": _ce_ok,
                "result": _ce_out[:120], "code_step": True,
            })
            step_results.append({
                "step_id": step_id, "goal": step_goal,
                "passed": _ce_ok, "needs_escalation": not _ce_ok,
                "tool_calls": 1, "code_step": True,
            })
            _ring_buffer.append(f"{step_goal[:30]}|{_ce_tool}|{'PASS' if _ce_ok else 'FAIL'}")
            if len(_ring_buffer) > _MAX_RING:
                _ring_buffer = _ring_buffer[-_MAX_RING:]
            try:
                engine_manager.tool_call_made.emit({
                    "name": f"[编排] {step_id}",
                    "arguments": _ce_args,
                    "result": f"步骤 {step_idx+1}/{len(plan)} · 纯代码子步 · {_ce_desc}",
                    "success": _ce_ok, "guided_step": True, "step_id": step_id,
                    "step_idx": step_idx, "step_total": len(plan),
                    "code_step": True,
                })
            except Exception:
                pass
            continue

        # 进度注入
        _progress_text = f"[编排进度: 第{step_idx+1}/{len(plan)}步] 本步目标: {step_goal}"
        if _ring_buffer:
            _progress_text += f"\n[已完成摘要] {'; '.join(_ring_buffer[-3:])}"

        # 历史案例注入
        _trajectory_hint = ""
        try:
            from shared.skill_trajectory import recall_similar_trajectories
            _hits = recall_similar_trajectories(prompt, top_k=1)
            if _hits:
                _trajectory_hint = f"历史成功案例: 类似任务曾调用 {_hits[0]['skill']} 完成。"
        except Exception:
            pass

        # B3: 用户语义记忆注入
        _user_profile_hint = ""
        try:
            from shared.user_memory import inject_into_prompt
            _profile_block = inject_into_prompt("", query=prompt, max_chars=200)
            if _profile_block:
                _user_profile_hint = _profile_block
        except Exception:
            pass

        # 构造短 system prompt（B4: ≤500 token ≈ 800 字符）
        # ★391B-2: 上下文水位 —— 跨步峰值超 num_ctx 80% 时注入压缩指令
        #   （优先复用已有信息减少重复读取；引擎侧 ContextBudget/裁剪仍兜底）
        _ctx_compress_hint = ""
        try:
            from shared.engine_manager import get_ollama_num_ctx as _gnctx
            if _ctx_watermark["peak"] > _gnctx() * 0.8:
                _ctx_compress_hint = (
                    "⚠ 上下文水位已超80%: 前序步骤详情已压缩为环形摘要，"
                    "优先复用已有信息，禁止重复读取已读文件/重复搜索。\n")
                if step_id not in _ctx_watermark["hinted"]:
                    _ctx_watermark["hinted"].append(step_id)
                    _guided_logger.warning(
                        f"[391B-2] 步骤 {step_id} 上下文水位 {_ctx_watermark['peak']} tok "
                        f"超 80% 阈值 —— 注入压缩指令")
        except Exception:
            pass
        _short_system = (
            f"你是 Lemon Code Agent。当前任务: {prompt[:200]}\n"
            f"{_progress_text}\n"
            f"判据: {criterion.get('description', '本步成功完成即可')} (类型: {criterion.get('type', 'return_success')})\n"
            f"铁律: 必须调用工具，禁止裸答。每次只调一个工具。\n"
            # ★391B-1: 分块读取策略 —— read_file 默认只回前 200 行（上限 400），
            #   先读开头判断相关性，相关段用 offset 精读，禁止整吞大文件
            f"读取策略: read_file 默认返回前200行；先读开头判断相关性，需要更多时按返回提示用 offset 续读，禁止一次 max_lines>400。\n"
            f"{_ctx_compress_hint}"
        )
        if _trajectory_hint:
            _short_system += f"{_trajectory_hint}\n"
        if _user_profile_hint:
            _short_system += f"{_user_profile_hint}\n"
        if candidates:
            _short_system += f"本步候选技能: {', '.join(candidates[:5])}\n"
        # 385B-3: 目录快照注入（真实目录 → 消除猜测路径；显式标注防把本机目录当调研对象）
        if _dir_snapshot:
            _short_system += (
                f"[本机目录快照（仅供路径参考，禁止当作调研对象或竞品）]\n"
                f"{_dir_snapshot[:500]}\n"
            )

        # ① 首次执行：调 agent_chat（复用全部防护+超时+循环控制）
        _guided_kwargs = {k: v for k, v in kwargs.items() if k not in ("engine",)}
        _guided_kwargs["system_prompt"] = _short_system
        _guided_kwargs["max_iterations"] = _MAX_STEP_ITERS
        _guided_kwargs["_inside_guided_loop"] = True

        # 386B-3: 步骤级总超时兜底（默认 60s）—— 引擎 60s/调用 与 工具 30s 均为
        # 单次调用级，多迭代叠加可无限拖延；此处对整步限时，超时判步失败走重试。
        step_result = _run_step_with_deadline(
            engine_manager, prompt, engine, _guided_kwargs,
            timeout_sec=_STEP_BUDGET_DEADLINE, step_id=step_id)

        _step_tool_calls = step_result.get("tool_calls_made", [])
        _step_content = step_result.get("content", "")
        all_tool_calls_made.extend(_step_tool_calls)
        # ★391B-2: 跨步上下文水位更新（391A-3 后 result 带引擎真值 context_tokens）
        try:
            _step_ctx = int(step_result.get("context_tokens") or 0)
            if _step_ctx > _ctx_watermark["peak"]:
                _ctx_watermark["peak"] = _step_ctx
        except Exception:
            pass

        # B1: 流式播报工具结果摘要
        if _stream_cb and _step_tool_calls:
            for tc in _step_tool_calls[-2:]:
                _tname = tc.get("name", "?")
                _tsucc = "成功" if tc.get("success") else "失败"
                _tresult_short = str(tc.get("result", ""))[:80]
                _stream_cb(f"  🔧 {_tname}({_tsucc}): {_tresult_short}\n")

        # ④ 判据验收（386B-1: detailed 版，记录实际命中明细）
        _criterion_type = criterion.get("type", "return_success")
        _passed, _judge_detail = _judge_criterion_detailed(
            _criterion_type, criterion, all_tool_calls_made, _step_tool_calls,
            step_content=_step_content)

        # 不过→重试 1 次（追加补救指令；386B-3: 重试同样限时）
        _step_timed_out = bool(step_result.get("step_timeout"))
        if not _passed:
            _why = "总超时" if _step_timed_out else "判据未通过"
            _guided_logger.info(f"[382B] 步骤 {step_id} {_why}，重试 1 次")
            # 386B-1 二轮：重试指令携带判据明细（告诉模型缺什么，提高重试成功率）
            _retry_system = (_short_system
                             + f"\n上一步未达成目标（判据明细: {_judge_detail[:150]}）"
                               f"，请换方式重试。\n")
            _guided_kwargs["system_prompt"] = _retry_system
            try:
                retry_result = _run_step_with_deadline(
                    engine_manager, prompt, engine, _guided_kwargs,
                    timeout_sec=_STEP_BUDGET_DEADLINE, step_id=step_id + ":retry")
                _retry_tc = retry_result.get("tool_calls_made", [])
                all_tool_calls_made.extend(_retry_tc)
                _step_content = retry_result.get("content", _step_content)
                _step_timed_out = _step_timed_out and bool(retry_result.get("step_timeout"))
                _passed, _judge_detail = _judge_criterion_detailed(
                    _criterion_type, criterion, all_tool_calls_made, _retry_tc,
                    step_content=_step_content)
            except Exception as e:
                _guided_logger.warning(f"[382B] 重试异常: {e}")

        # ⑤ 环形记忆（三元组摘要 — 目标+工具名+判据结果）
        _status = "PASS" if _passed else "FAIL"
        _last_tool = _step_tool_calls[0].get("name", "none") if _step_tool_calls else "none"
        _summary = f"{step_goal[:40]}|{_last_tool}|{_status}"
        _ring_buffer.append(_summary[:200])
        if len(_ring_buffer) > _MAX_RING:
            _ring_buffer = _ring_buffer[-_MAX_RING:]

        step_results.append({
            "step_id": step_id,
            "goal": step_goal,
            "passed": _passed,
            "needs_escalation": not _passed,
            "tool_calls": len(_step_tool_calls),
            # ★391B-2: 上下文水位审计（checkpoint 可查峰值与压缩指令触发步）
            "ctx_peak": _ctx_watermark["peak"],
            "ctx_compress_hinted": step_id in _ctx_watermark.get("hinted", []),
            # 386B-1: 判据类型与实际命中明细（checkpoint 可查）
            "criterion_type": _criterion_type,
            "criterion_detail": _judge_detail[:200],
            # 386B-3: 步骤超时留痕
            "timed_out": _step_timed_out,
        })

        # B2: 每步落盘断点
        _save_checkpoint(_checkpoint_file, step_idx + 1, _ring_buffer, step_results, prompt,
                         _classification_reason)

        # 向 UI 发编排进度卡（复用 tool_call_made 信号 + step_id）
        try:
            engine_manager.tool_call_made.emit({
                "name": f"[编排] {step_id}",
                "arguments": {"goal": step_goal},
                "result": f"步骤 {step_idx+1}/{len(plan)} · 目标: {step_goal} · 工具: {_last_tool} · 判据结果({'✓' if _passed else '✗'})",
                "success": _passed,
                "guided_step": True,
                "step_id": step_id,
                "step_idx": step_idx,
                "step_total": len(plan),
                "step_goal": step_goal,
                "tool_used": _last_tool,
                "criterion_passed": _passed,
                "criterion_type": _criterion_type,
                "needs_escalation": not _passed,
                "template_info": _template_info,
            })
        except Exception:
            pass

        _guided_logger.info(f"[382B] 步骤 {step_id}: passed={_passed}, tools={len(_step_tool_calls)}")

    # ⑥ 本地汇总
    _success_steps = [s for s in step_results if s["passed"]]
    _failed_steps = [s for s in step_results if not s["passed"]]
    _needs_escalation = len(_failed_steps) > 0
    _elapsed = time.time() - start_time

    # 385B-3: 幻觉嫌疑扫描 —— 调研/兜底域报告文本命中本机绝对路径 → 标记嫌疑。
    # 软降级：不改 passed（护栏仍按工具判据），只降 completion_score 并留审计标记。
    _hallucination_hits = []
    if domain in ("research", "general") and _step_content:
        _hallucination_hits = _HALLUCINATED_PATH_RE.findall(_step_content)
        if _hallucination_hits:
            _guided_logger.warning(
                f"[385B-3] 幻觉嫌疑: 报告文本命中本机绝对路径 x{len(_hallucination_hits)} "
                f"（样例: {_hallucination_hits[:3]}）")
            for _s in step_results:
                if _s.get("passed") and not _s.get("code_step"):
                    _s["hallucination_suspect"] = True

    _summary_parts = []
    _summary_parts.append(f"编排完成: {len(_success_steps)}/{len(plan)} 步通过 (模板: {_plan_template_name})")
    for s in _failed_steps:
        _summary_parts.append(f"  失败步 {s['step_id']}: {s['goal']} — 建议切大模型体系")
    if _success_steps:
        _summary_parts.append(f"  成功步: {', '.join(s['step_id'] for s in _success_steps)}")
    if _hallucination_hits:
        _summary_parts.append(
            f"  ⚠ 幻觉嫌疑: 报告命中本机绝对路径 x{len(_hallucination_hits)}（本机目录不是调研对象）")
    _final_content = "\n".join(_summary_parts)

    if _step_content and _step_content.strip():
        _final_content += f"\n\n{_step_content}"

    # B1: 流式播报最终汇总
    if _stream_cb:
        _stream_cb(f"\n{'='*40}\n{_final_content[:500]}\n")

    # B3: 记录用户语义记忆
    try:
        from shared.user_memory import record_fact
        record_fact(prompt, source="guided_loop")
        if _step_content:
            record_fact(_step_content[:300], source="guided_output")
    except Exception:
        pass

    # 379-2: 轨迹记录
    if engine == "ollama" and all_tool_calls_made:
        try:
            from shared.skill_trajectory import record_skill_trajectory
            record_skill_trajectory(prompt, all_tool_calls_made)
        except Exception:
            pass

    # B2: 任务完成，清理断点文件
    if not _needs_escalation:
        try:
            if os.path.exists(_checkpoint_file):
                os.remove(_checkpoint_file)
        except Exception:
            pass

    _model = kwargs.get("model", "")
    if not _model:
        try:
            _model = engine_manager._configs.get(engine, type('EC', (), {'model': 'unknown'})()).model
        except Exception:
            _model = "unknown"

    return {
        "content": _final_content,
        "engine": engine,
        "model": _model,
        "iterations": len(plan),
        "tool_calls_made": all_tool_calls_made,
        "total_time": _elapsed,
        "guided_loop": True,
        "guided_domain": domain,
        "guided_plan": plan,
        "guided_steps": step_results,
        "guided_template": _plan_template_name,
        "routed_domains": list(_routed_domains or [domain]),  # ★390B-2: 路由命中打点
        "needs_escalation": _needs_escalation,
        "complexity_detected": classification.complexity.value if hasattr(classification, 'complexity') else None,
        "complexity_classification": _classification_reason,
        "timeout_occurred": False,
        "validation": None,
        "completion_score": (
            float(len(_success_steps)) / max(len(plan), 1)
            * (0.5 if _hallucination_hits else 1.0)
        ),
        "hallucination_suspect": bool(_hallucination_hits),
        "hallucination_hits": len(_hallucination_hits),
        "reflections": 0,
    }


def _save_checkpoint(filepath, current_step_idx, ring_buffer, step_results, prompt,
                     classification_reason=""):
    """B2: 保存断点状态到 JSON 文件。"""
    try:
        _cp = {
            "current_step_idx": current_step_idx,
            "ring_buffer": ring_buffer,
            "step_results": step_results,
            "prompt_hash": _task_id_for(prompt),
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "classification": classification_reason,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(_cp, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _guided_logger.debug(f"[382B] 断点保存失败(忽略): {e}")


def _call_engine_with_tools(engine_manager, engine_obj, engine_name, messages, tools, **kwargs):
    """调用引擎的 generate_with_tools，带 60s 超时保护。"""
    if not hasattr(engine_obj, "generate_with_tools"):
        raise RuntimeError(f"引擎 {engine_name} 不支持 generate_with_tools")

    model = kwargs.get("model", "")
    call_kwargs = {}
    if model:
        call_kwargs["model"] = model

    def _do_call():
        try:
            return engine_obj.generate_with_tools(messages, tools, **call_kwargs)
        except TypeError:
            return engine_obj.generate_with_tools(messages, tools)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
        _future = _pool.submit(_do_call)
        try:
            result = _future.result(timeout=60)
        except concurrent.futures.TimeoutError:
            _guided_logger.warning(f"[380B] 引擎调用超时 60s，放弃本轮")
            return {"content": "", "tool_calls": []}
        except Exception as e:
            _guided_logger.warning(f"[380B] 引擎调用异常: {e}")
            return {"content": "", "tool_calls": []}

    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        return {"content": result, "tool_calls": []}
    return {"content": str(result), "tool_calls": []}


def _invoke_tool_safe(router, tool_name, tool_args, engine_manager):
    """安全调用工具，返回 SkillResult。"""
    from shared.engine_manager import _invoke_tool_with_timeout
    return _invoke_tool_with_timeout(router, tool_name, tool_args, 30)


def _format_result_safe(tool_name, sr):
    """安全格式化 SkillResult。"""
    try:
        from shared.engine_manager import _format_skill_result
        return _format_skill_result(tool_name, sr)
    except Exception:
        out = getattr(sr, "output", "")
        if not getattr(sr, "success", False):
            return f"错误: {getattr(sr, 'error', str(out))}"
        return str(out)


# 385B-3: 幻觉嫌疑正则 —— 本机绝对路径（盘符/用户目录）出现在调研报告文本中
_HALLUCINATED_PATH_RE = re.compile(
    r"\b[A-Za-z]:[\\\\/]+(?:Users|Users/[\w.\- ]+|\u9879\u76ee\u5907\u4efd)?"
    r"|\b[A-Za-z]:[\\\\/]+\w"
    r"|/Users/[\w.\- ]+"
    r"|\\\\Users\\\\"
)


# 386B-3: 步骤级总超时兜底（秒）—— 覆盖单步全部迭代的墙钟上限
_STEP_BUDGET_DEADLINE = 60


def _run_step_with_deadline(engine_manager, prompt, engine, guided_kwargs,
                            timeout_sec: int = 60, step_id: str = "?"):
    """386B-3: 整步限时执行 agent_chat。超时返回 step_timeout 结果（判步失败，
    走既有重试/回退路径），daemon 线程兜底，禁止无限等待。

    Returns:
        dict: agent_chat 结果，或 {"step_timeout": True, ...} 占位结果。
    """
    _box = {}

    def _runner():
        try:
            _box["r"] = engine_manager.agent_chat(prompt, engine=engine, **guided_kwargs)
        except Exception as e:  # noqa: BLE001
            _box["err"] = e

    _t = threading.Thread(target=_runner, daemon=True, name=f"guided-step-{step_id}")
    _t.start()
    _t.join(timeout_sec)
    if _t.is_alive():
        _guided_logger.warning(
            f"[386B-3] 步骤 {step_id} 总超时 {timeout_sec}s —— 判步失败进入重试路径"
            f"（后台线程 daemon 化，不阻塞主流程）")
        return {"content": "", "tool_calls_made": [], "iterations": 0,
                "step_timeout": True}
    if "err" in _box:
        raise _box["err"]
    return _box.get("r", {"content": "", "tool_calls_made": [], "iterations": 0})


def _judge_criterion_detailed(criterion_type, criterion, all_tool_calls,
                              step_tool_calls, step_content: str = ""):
    """386B-1: 判据验收（详细版）—— 纯代码判，不问模型。

    返回 (passed: bool, detail: str)，detail 供 checkpoint 记录实际命中明细。

    criterion_type:
        基础三型：
        - "artifact_exists": 检查产物文件是否存在
        - "return_success":  检查工具调用是否返回 success
        - "field_complete":  检查返回关键字段非空
        386B-1 内容型三型（防过松判据稀释 HIT）：
        - "contains_keywords": {list, min_hits} 最近成功结果文本命中 ≥N 个关键词
        - "matches_regex":     {pattern} 结果文本命中正则
        - "output_struct":     {fields} 结果文本必含全部字段名
    """
    try:
        if criterion_type == "artifact_exists":
            _path = criterion.get("path", "")
            if _path and os.path.exists(_path):
                return True, f"artifact exists: {_path}"
            for tc in all_tool_calls[-3:]:
                if tc.get("success") and _path and _path in str(tc.get("result", "")):
                    return True, f"artifact mentioned: {_path}"
            return False, f"artifact missing: {_path or '(no path)'}"

        if criterion_type == "return_success":
            for tc in all_tool_calls[-3:]:
                if tc.get("success"):
                    return True, f"success via {tc.get('name', '?')}"
            return False, "no successful tool call"

        if criterion_type == "field_complete":
            _field = criterion.get("field", "")
            if not _field:
                return True, "no field required"
            for tc in all_tool_calls[-3:]:
                if tc.get("success") and _field in str(tc.get("result", "")):
                    return True, f"field '{_field}' present"
            return False, f"field '{_field}' absent"

        # ---- 386B-1 内容型三型 ----
        _probe_parts = [str(tc.get("result", "")) for tc in all_tool_calls[-3:]
                        if tc.get("success")]
        if step_content:
            _probe_parts.append(step_content)
        _probe = "\n".join(_probe_parts)

        if criterion_type == "contains_keywords":
            _kws = criterion.get("list", []) or []
            if not _kws:
                return True, "no keywords configured"
            _min = int(criterion.get("min_hits", 1))
            _hits = [k for k in _kws if k in _probe]
            _ok = len(_hits) >= _min
            return _ok, (f"keywords {len(_hits)}/{len(_kws)} (need {_min}) "
                         f"hit={_hits[:5]} miss={[k for k in _kws if k not in _hits][:5]}")

        if criterion_type == "matches_regex":
            _pat = criterion.get("pattern", "")
            if not _pat:
                return True, "no pattern configured"
            _m = re.search(_pat, _probe)
            if _m:
                return True, f"regex hit: {_m.group(0)[:80]!r}"
            return False, f"regex miss: {_pat[:60]}"

        if criterion_type == "output_struct":
            _fields = criterion.get("fields", []) or []
            if not _fields:
                return True, "no fields configured"
            _missing = [f for f in _fields if f not in _probe]
            _ok = not _missing
            return _ok, (f"struct {'complete' if _ok else 'missing=' + str(_missing[:5])}"
                         f" (fields={_fields})")

        # 默认：有成功工具调用即通过
        _ok = any(tc.get("success") for tc in all_tool_calls[-3:])
        return _ok, "default: any success" if _ok else "default: no success"
    except Exception as e:  # noqa: BLE001
        return False, f"judge error: {e}"


def _judge_criterion(criterion_type, criterion, all_tool_calls, step_tool_calls,
                     step_content: str = ""):
    """判据验收：代码判（不问模型）。386B-1 起为 _judge_criterion_detailed 的布尔包装。"""
    _ok, _ = _judge_criterion_detailed(criterion_type, criterion, all_tool_calls,
                                       step_tool_calls, step_content)
    return _ok
