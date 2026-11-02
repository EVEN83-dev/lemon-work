# -*- coding: utf-8 -*-
"""364章 T4.2: 子代理编排 — 多代理协作与任务分配"""

import time
import uuid
from typing import Callable, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class AgentRole(Enum):
    COORDINATOR = "coordinator"
    WORKER = "worker"
    REVIEWER = "reviewer"


class AgentState(Enum):
    IDLE = "idle"
    WORKING = "working"
    DONE = "done"
    FAILED = "failed"


@dataclass
class SubAgentSpec:
    agent_id: str
    role: AgentRole
    name: str
    capacity: int = 1
    state: AgentState = AgentState.IDLE
    current_task: str = ""
    completed_tasks: int = 0
    failed_tasks: int = 0


@dataclass
class SubTask:
    task_id: str
    description: str
    assigned_to: str = ""
    status: str = "pending"
    result: object = None
    error: str = ""
    redispatch_count: int = 0     # 389M-6: 已重派次数（上限 1）
    parent_task_id: str = ""      # 389M-6: 重派来源任务


class SubAgentOrchestrator:
    def __init__(self, max_concurrency: int = 3):
        self.max_concurrency = max_concurrency
        self._agents: Dict[str, SubAgentSpec] = {}
        self._tasks: Dict[str, SubTask] = {}
        self._execution_log: List[Dict] = []

    def register_agent(self, name: str, role: str = "worker",
                       capacity: int = 1) -> str:
        aid = f"agent_{uuid.uuid4().hex[:6]}"
        self._agents[aid] = SubAgentSpec(
            agent_id=aid, role=AgentRole(role), name=name, capacity=capacity)
        return aid

    def submit_task(self, description: str, preferred_agent: str = "") -> str:
        tid = f"task_{uuid.uuid4().hex[:6]}"
        self._tasks[tid] = SubTask(task_id=tid, description=description,
                                    assigned_to=preferred_agent)
        return tid

    def assign_task(self, task_id: str) -> Optional[str]:
        task = self._tasks.get(task_id)
        if not task or task.status != "pending":
            return None

        best = None
        for agent in self._agents.values():
            if agent.state != AgentState.IDLE:
                continue
            if agent.role == AgentRole.WORKER:
                if best is None or agent.completed_tasks > best.completed_tasks:
                    best = agent

        if best is None:
            return None

        task.assigned_to = best.agent_id
        task.status = "assigned"
        best.state = AgentState.WORKING
        best.current_task = task_id
        return best.agent_id

    def complete_task(self, task_id: str, result: object = None,
                      error: str = "") -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False

        agent = self._agents.get(task.assigned_to)
        task.result = result
        task.error = error

        if error:
            task.status = "failed"
            if agent:
                agent.failed_tasks += 1
        else:
            task.status = "completed"
            if agent:
                agent.completed_tasks += 1

        if agent:
            agent.state = AgentState.IDLE
            agent.current_task = ""

        self._execution_log.append({
            "task_id": task_id, "agent": task.assigned_to,
            "status": task.status, "timestamp": time.time(),
        })

        # ★389M-6: 失败重派 —— 主 Agent 收到 failed 回写后最多重派 1 次
        #   （换收窄 DOD：描述追加失败原因与"只完成核心交付物"约束），
        #   重派记录进执行日志（审计链）。
        if error and task.redispatch_count < 1:
            task.redispatch_count += 1
            _rd_id = self.submit_task(
                description=(f"{task.description}\n"
                             f"[重派 第2次] 上次失败原因: {str(error)[:200]}\n"
                             "[DOD 收窄] 只完成核心交付物，忽略边缘要求。"),
            )
            _rd_task = self._tasks.get(_rd_id)
            if _rd_task is not None:
                _rd_task.parent_task_id = task_id
                _rd_task.redispatch_count = task.redispatch_count
            self._execution_log.append({
                "task_id": _rd_id, "agent": "", "status": "redispatched",
                "parent_task_id": task_id, "attempt": task.redispatch_count,
                "reason": str(error)[:200], "timestamp": time.time(),
            })
        return True

    def get_status(self) -> Dict:
        idle = sum(1 for a in self._agents.values() if a.state == AgentState.IDLE)
        working = sum(1 for a in self._agents.values() if a.state == AgentState.WORKING)
        pending = sum(1 for t in self._tasks.values() if t.status == "pending")
        completed = sum(1 for t in self._tasks.values() if t.status == "completed")
        failed = sum(1 for t in self._tasks.values() if t.status == "failed")

        return {
            "agents": {"total": len(self._agents), "idle": idle, "working": working},
            "tasks": {"total": len(self._tasks), "pending": pending,
                      "completed": completed, "failed": failed},
            "max_concurrency": self.max_concurrency,
        }

    def list_agents(self) -> List[Dict]:
        return [{"id": a.agent_id, "name": a.name, "role": a.role.value,
                 "state": a.state.value, "completed": a.completed_tasks,
                 "failed": a.failed_tasks}
                for a in self._agents.values()]

    def get_execution_log(self) -> List[Dict]:
        return self._execution_log
