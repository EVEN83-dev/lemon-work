# -*- coding: utf-8 -*-
"""Multi-Agent orchestrator - coordination, voting, task assignment, real execution"""
import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class AgentRole(Enum):
    COORDINATOR = 'coordinator'
    WORKER = 'worker'
    REVIEWER = 'reviewer'
    SPECIALIST = 'specialist'


class AgentStatus(Enum):
    IDLE = 'idle'
    WORKING = 'working'
    WAITING = 'waiting'
    COMPLETED = 'completed'
    ERROR = 'error'


class TaskPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class SubAgent:
    agent_id: str
    name: str
    role: AgentRole
    capabilities: List[str]
    status: AgentStatus = AgentStatus.IDLE
    current_task: Optional[str] = None
    performance_score: float = 0.0
    tasks_completed: int = 0
    error_count: int = 0


@dataclass
class AgentTask:
    task_id: str
    description: str
    assigned_to: Optional[str] = None
    priority: TaskPriority = TaskPriority.MEDIUM
    status: str = 'pending'
    result: Any = None
    created_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""


@dataclass
class VotingRecord:
    task_id: str
    voter_id: str
    vote: str
    weight: float = 1.0
    reason: str = ''
    timestamp: float = 0.0


class MultiAgentOrchestrator:
    MAX_CONCURRENT = 4
    DEFAULT_WORKER_TIMEOUT = 300

    def __init__(self, spawn_fn: Optional[Callable] = None, bus=None,
                 worker_timeout: int = 0):
        self._agents: Dict[str, SubAgent] = {}
        self._tasks: Dict[str, AgentTask] = {}
        self._voting_records: List[VotingRecord] = []
        self._task_queue: List[str] = []
        self._completed_tasks: List[str] = []
        self._spawn_fn = spawn_fn
        self._bus = bus
        self._worker_timeout = worker_timeout or self.DEFAULT_WORKER_TIMEOUT
        self._semaphore = threading.Semaphore(self.MAX_CONCURRENT)
        self._lock = threading.Lock()
        self._callbacks: Dict[str, List[Callable]] = {}
        self._active_worker_timers: Dict[str, threading.Timer] = {}
        self._init_default_agents()

    def _init_default_agents(self):
        for agent in [
            SubAgent('coordinator', 'Coordinator', AgentRole.COORDINATOR,
                     ['task_decomposition', 'agent_selection', 'result_aggregation']),
            SubAgent('coder', 'Code Engineer', AgentRole.WORKER,
                     ['code_generation', 'code_refactoring', 'bug_fixing']),
            SubAgent('reviewer', 'Code Reviewer', AgentRole.REVIEWER,
                     ['code_review', 'quality_check', 'security_audit']),
            SubAgent('researcher', 'Researcher', AgentRole.SPECIALIST,
                     ['web_research', 'document_analysis', 'knowledge_query']),
        ]:
            self.register_agent(agent)

    def set_spawn_fn(self, spawn_fn: Callable) -> None:
        self._spawn_fn = spawn_fn

    def set_bus(self, bus) -> None:
        self._bus = bus
        self._start_bus_consumer()

    def _start_bus_consumer(self) -> None:
        if not self._bus:
            return
        try:
            bus_type = type(self._bus).__name__
            if bus_type == "AgentCommBus":
                self._bus.subscribe_type("status_update", self._on_comm_bus_message)
                self._bus.subscribe_type("context_share", self._on_comm_bus_message)
                self._bus.subscribe_broadcast(self._on_comm_bus_message)
            elif hasattr(self._bus, 'subscribe'):
                self._bus.subscribe("*", self._on_bus_message)
            logger.info("[MultiAgentOrchestrator] bus消费已接线 (type=%s)", bus_type)
        except Exception as e:
            logger.warning("[MultiAgentOrchestrator] bus订阅失败: %s", e)

    def _on_comm_bus_message(self, message: Any) -> None:
        """消费 AgentCommBus (bridge/services/agent_bus.py) 的消息。"""
        try:
            msg_type = getattr(message, 'message_type', '')
            sender = getattr(message, 'sender_id', '')
            payload = getattr(message, 'payload', {})
            if isinstance(payload, str):
                import json as _json
                try:
                    payload = _json.loads(payload)
                except Exception:
                    payload = {}
            self._process_bus_event(msg_type, sender, payload)
        except Exception as e:
            logger.debug("[MultiAgentOrchestrator] comm_bus消息处理失败: %s", e)

    def _on_bus_message(self, message: Any) -> None:
        """消费 AgentBus (shared/agent_message.py) 的消息。"""
        try:
            msg_type = getattr(message, 'message_type', '')
            from_agent = getattr(message, 'from_agent', '')
            payload = getattr(message, 'payload', {})
            self._process_bus_event(msg_type, from_agent, payload)
        except Exception as e:
            logger.debug("[MultiAgentOrchestrator] bus消息处理失败: %s", e)

    def _process_bus_event(self, msg_type: str, sender: str, payload: Dict) -> None:
        """统一处理来自任何bus的事件。"""
        if msg_type in ("context_share", "CONTEXT_SHARE"):
            task_id = payload.get("source_task", payload.get("task_id", ""))
            if task_id and task_id in self._tasks:
                task = self._tasks[task_id]
                if not task.result:
                    task.result = payload.get("content_preview", payload.get("content", ""))
        elif msg_type in ("status_update", "STATUS_UPDATE"):
            agent_id = sender
            if agent_id in self._agents:
                state = payload.get("state", "")
                if state in ("completed", "failed", "terminated"):
                    self._agents[agent_id].status = AgentStatus.IDLE
                    self._agents[agent_id].current_task = None

    def register_agent(self, agent: SubAgent):
        self._agents[agent.agent_id] = agent

    def create_task(self, description: str, priority: TaskPriority = TaskPriority.MEDIUM) -> AgentTask:
        task_id = f'task_{int(time.time())}_{id(description) % 10000}'
        task = AgentTask(task_id=task_id, description=description, priority=priority, created_at=time.time())
        self._tasks[task_id] = task
        self._task_queue.append(task_id)
        return task

    def assign_task(self, task_id: str, agent_id: str) -> bool:
        task = self._tasks.get(task_id)
        agent = self._agents.get(agent_id)
        if task is None or agent is None:
            return False
        if agent.status != AgentStatus.IDLE:
            return False
        task.assigned_to = agent_id
        task.status = 'assigned'
        agent.current_task = task_id
        agent.status = AgentStatus.WORKING
        return True

    def select_best_agent(self, task_id: str, required_capabilities: List[str] = None) -> Optional[str]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        candidates = []
        for agent_id, agent in self._agents.items():
            if agent.status != AgentStatus.IDLE:
                continue
            if required_capabilities:
                match_score = sum(1 for cap in required_capabilities if cap in agent.capabilities)
                if match_score > 0:
                    candidates.append((agent_id, match_score + agent.performance_score))
            else:
                candidates.append((agent_id, agent.performance_score))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def execute_task(self, task_id: str) -> Optional[str]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        if task.status not in ('pending', 'assigned'):
            return None
        if not task.assigned_to:
            best = self.select_best_agent(task_id)
            if not best:
                task.status = 'pending'
                return None
            self.assign_task(task_id, best)
        task.status = 'executing'
        self._emit("task_executing", task)
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            task.status = 'assigned'
            logger.info("[MultiAgentOrchestrator] 并发上限, 任务%s排队", task_id)
            return None

        timed_out = threading.Event()

        def _on_worker_timeout():
            timed_out.set()
            logger.warning("[MultiAgentOrchestrator] worker超时(%ds), 取消任务%s",
                           self._worker_timeout, task_id)
            self._cancel_task_worker(task_id)

        timeout_timer = threading.Timer(self._worker_timeout, _on_worker_timeout)
        timeout_timer.daemon = True
        timeout_timer.start()
        self._active_worker_timers[task_id] = timeout_timer

        try:
            agent = self._agents.get(task.assigned_to)
            if not agent:
                task.status = 'failed'
                task.error = f"Agent {task.assigned_to} not found"
                return None
            if timed_out.is_set():
                task.status = 'failed'
                task.error = f"Worker timeout ({self._worker_timeout}s) before execution"
                task.completed_at = time.time()
                agent.status = AgentStatus.IDLE
                agent.current_task = None
                agent.error_count += 1
                self._emit("task_failed", task)
                return task.status

            if self._spawn_fn:
                result = self._spawn_fn(agent.agent_id, task.description)
                if timed_out.is_set():
                    task.status = 'failed'
                    task.error = f"Worker timeout ({self._worker_timeout}s) during spawn_fn"
                else:
                    task.result = result
                    task.status = 'completed'
                task.completed_at = time.time()
                agent.status = AgentStatus.IDLE
                agent.current_task = None
                if task.status == 'completed':
                    agent.tasks_completed += 1
                    agent.performance_score = min(1.0, agent.performance_score + 0.1)
                else:
                    agent.error_count += 1
            else:
                try:
                    from shared.sub_agent import get_sub_agent_orchestrator, SubAgentSpec
                    orch = get_sub_agent_orchestrator()
                    spec = SubAgentSpec(
                        name=agent.name,
                        task_description=task.description,
                        role_id=agent.agent_id,
                        timeout_seconds=self._worker_timeout,
                    )
                    sub_id = orch.spawn(spec)
                    result = orch.wait_one(sub_id, timeout=self._worker_timeout)
                    if timed_out.is_set():
                        orch.cancel(sub_id)
                        task.status = 'failed'
                        task.error = f"Worker timeout ({self._worker_timeout}s)"
                    elif result.status == "success":
                        task.result = result.content
                        task.status = 'completed'
                    elif result.status == "timeout":
                        task.status = 'failed'
                        task.error = f"SubAgent timeout ({self._worker_timeout}s)"
                    else:
                        task.status = 'failed'
                        task.error = result.error or f"SubAgent status: {result.status}"
                    task.completed_at = time.time()
                    agent.status = AgentStatus.IDLE
                    agent.current_task = None
                    if task.status == 'completed':
                        agent.tasks_completed += 1
                        agent.performance_score = min(1.0, agent.performance_score + 0.1)
                    else:
                        agent.error_count += 1
                except Exception as e:
                    logger.error("[MultiAgentOrchestrator] execute_task失败: %s", e)
                    task.status = 'failed'
                    task.error = str(e)
                    task.completed_at = time.time()
                    if agent:
                        agent.status = AgentStatus.IDLE
                        agent.current_task = None
                        agent.error_count += 1
        finally:
            self._active_worker_timers.pop(task_id, None)
            timeout_timer.cancel()
            self._semaphore.release()
        if task.status == 'completed':
            if task_id in self._task_queue:
                self._task_queue.remove(task_id)
            self._completed_tasks.append(task_id)
            self._emit("task_completed", task)
        elif task.status == 'failed':
            self._emit("task_failed", task)
        return task.status

    def _cancel_task_worker(self, task_id: str) -> None:
        """取消任务的worker执行，唯一取消权威委托给 SubAgentOrchestrator.cancel。

        禁止本类自建第二套取消逻辑（如直接操作 permit / 自建 cancel_event），
        所有取消必须经由 SubAgentOrchestrator 的 cancel_event + 进程级 kill，
        避免两套机制打架（对照 deepseeknova swarm.rs 的 CancellationCoordinator）。
        """
        task = self._tasks.get(task_id)
        if not task or task.status != 'executing':
            return
        try:
            from shared.sub_agent import get_sub_agent_orchestrator
            orch = get_sub_agent_orchestrator()
            sub_ids = orch.find_by_task_description(task.description)
            for sub_id in sub_ids:
                orch.cancel(sub_id)
                logger.info("[MultiAgentOrchestrator] 取消委托至 SubAgentOrchestrator.cancel(%s)", sub_id)
        except Exception as e:
            logger.warning("[MultiAgentOrchestrator] 取消委托失败: %s", e)
        task.status = 'failed'
        task.error = task.error or "Worker cancelled (timeout or explicit cancel)"
        task.completed_at = time.time()
        if task.assigned_to:
            agent = self._agents.get(task.assigned_to)
            if agent:
                agent.status = AgentStatus.IDLE
                agent.current_task = None
                agent.error_count += 1
        self._emit("task_failed", task)

    def cancel_task(self, task_id: str) -> bool:
        """外部调用的取消入口，统一委托给 SubAgentOrchestrator.cancel。

        对照 deepseeknova swarm.rs: CancellationCoordinator::cancel(task_id)
        最终调用 worker.abort() — 本实现中 worker.abort = SubAgentOrchestrator.cancel。
        """
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status in ('completed', 'failed'):
            return False
        self._cancel_task_worker(task_id)
        return True

    def complete_task(self, task_id: str, result: Any):
        task = self._tasks.get(task_id)
        if task:
            task.status = 'completed'
            task.result = result
            task.completed_at = time.time()
            if task.assigned_to:
                agent = self._agents.get(task.assigned_to)
                if agent:
                    agent.status = AgentStatus.IDLE
                    agent.current_task = None
                    agent.tasks_completed += 1
                    agent.performance_score = min(1.0, agent.performance_score + 0.1)
            if task_id in self._task_queue:
                self._task_queue.remove(task_id)
            self._completed_tasks.append(task_id)
            self._emit("task_completed", task)

    def fail_task(self, task_id: str, error: str = "") -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        task.status = 'failed'
        task.error = error
        task.completed_at = time.time()
        if task.assigned_to:
            agent = self._agents.get(task.assigned_to)
            if agent:
                agent.status = AgentStatus.IDLE
                agent.current_task = None
                agent.error_count += 1
        self._emit("task_failed", task)

    def submit_vote(self, task_id: str, voter_id: str, vote: str, reason: str = '') -> VotingRecord:
        record = VotingRecord(task_id=task_id, voter_id=voter_id, vote=vote, reason=reason, timestamp=time.time())
        self._voting_records.append(record)
        return record

    def tally_votes(self, task_id: str) -> Dict:
        relevant = [v for v in self._voting_records if v.task_id == task_id]
        if not relevant:
            return {'result': 'no_votes', 'count': 0}
        approve = sum(1 for v in relevant if v.vote == 'approve')
        reject = sum(1 for v in relevant if v.vote == 'reject')
        abstain = sum(1 for v in relevant if v.vote == 'abstain')
        total = len(relevant)
        if approve / total >= 0.6:
            result = 'approved'
        elif reject / total >= 0.6:
            result = 'rejected'
        else:
            result = 'pending'
        return {'result': result, 'approve': approve, 'reject': reject, 'abstain': abstain, 'total': total}

    def get_pending_tasks(self) -> List[Dict]:
        return [
            {'task_id': tid, 'description': self._tasks[tid].description,
             'priority': self._tasks[tid].priority.value,
             'assigned_to': self._tasks[tid].assigned_to, 'status': self._tasks[tid].status}
            for tid in self._task_queue
        ]

    def get_agent_status(self) -> List[Dict]:
        return [
            {'agent_id': aid, 'name': agent.name, 'role': agent.role.value,
             'status': agent.status.value, 'current_task': agent.current_task,
             'tasks_completed': agent.tasks_completed, 'performance': agent.performance_score}
            for aid, agent in self._agents.items()
        ]

    def get_orchestrator_stats(self) -> Dict:
        return {
            'total_agents': len(self._agents),
            'idle_agents': sum(1 for a in self._agents.values() if a.status == AgentStatus.IDLE),
            'working_agents': sum(1 for a in self._agents.values() if a.status == AgentStatus.WORKING),
            'total_tasks': len(self._tasks),
            'pending_tasks': len(self._task_queue),
            'completed_tasks': len(self._completed_tasks),
            'total_votes': len(self._voting_records),
            'concurrent_slots': self.MAX_CONCURRENT,
        }

    def on(self, event_name: str, callback: Callable) -> None:
        if event_name not in self._callbacks:
            self._callbacks[event_name] = []
        self._callbacks[event_name].append(callback)

    def _emit(self, event_name: str, data: Any) -> None:
        for cb in self._callbacks.get(event_name, []):
            try:
                cb(data)
            except Exception:
                pass
        if self._bus:
            try:
                from shared.agent_message import AgentMessage, MessageType
                self._bus.publish(AgentMessage(
                    from_agent="multi_agent_orchestrator",
                    to_agent="*",
                    message_type=MessageType.STATUS_UPDATE.value,
                    payload={"event": event_name, "task_id": getattr(data, 'task_id', ''), "status": getattr(data, 'status', '')},
                ))
            except Exception:
                pass


_orchestrator: Optional[MultiAgentOrchestrator] = None
_orch_lock = threading.Lock()


def get_multi_agent_orchestrator() -> MultiAgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        with _orch_lock:
            if _orchestrator is None:
                _orchestrator = MultiAgentOrchestrator()
    return _orchestrator
