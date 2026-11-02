# -*- coding: utf-8 -*-
"""
Actor 系统 — 动态子 Agent 协作（spawn / waiter / registry）
===========================================================
蒸馏自 MiMo-Code opencode/src/actor/（spawn.ts / waiter.ts / registry.ts），
用 Python threading + Event 实现同等语义：

核心概念：
1. ActorRegistry - 子 Agent 注册表：分配 actor_id、登记状态、按父级查询
2. ActorSpawner  - spawn(): 动态创建子 Agent（peer/subagent 两种模式），
                   返回 ActorHandle；后台线程跑 task_fn，完成后写 outcome
3. ActorWaiter   - wait(): 等待子 Agent 达到终态（idle+success/failure/cancelled）
                   或超时，返回 WaitResult

两种 spawn 模式（对齐 MiMo-Code）：
- subagent: 共享父 Agent 会话，轻量子任务（默认 ephemeral）
- peer:     独立工作目录/隔离环境的对等 Agent（可绑定 cwd 实现 worktree 隔离）

使用示例：
    from shared.actor_system import ActorSystem
    system = ActorSystem()
    handle = system.spawn(agent_type="coder", task="重构 utils.py",
                          task_fn=lambda: run_coder("重构 utils.py"))
    result = system.wait(handle.actor_id, timeout_ms=600000)
    print(result.status, result.result)
"""
import os
import sys
import time
import uuid
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any


_CHDIR_LOCK = threading.Lock()


def _run_in_cwd(cwd, task_fn, task_args, kwargs, cancel_event, registry, actor_id):
    """在指定 cwd 下安全执行 task_fn，不污染其他线程的 os.getcwd()。

    使用模块级全局锁串行化所有 chdir 操作：
    同一时刻只有一个 Actor 在做 chdir + 执行 + chdir_back，
    避免并行 Actor 的 cwd 交叉污染。

    注意：这意味着 peer 模式的多个 Actor 会被串行化执行 cwd 敏感操作，
    但 task_fn 内部若不依赖 os.getcwd()（如纯 HTTP 调用引擎），
    则不受锁影响。
    """
    with _CHDIR_LOCK:
        old_cwd = os.getcwd()
        try:
            os.chdir(cwd)
            result = task_fn(*task_args, **kwargs)
            registry.complete(actor_id, "success", result=result)
        except Exception as e:
            registry.complete(actor_id, "failure", error=str(e))
        finally:
            try:
                os.chdir(old_cwd)
            except OSError:
                pass


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ActorRecord:
    """子 Agent 注册记录"""
    actor_id: str
    agent_type: str          # agent 类型 (coder/explorer/planner...)
    description: str         # 描述
    mode: str                # "peer" | "subagent"
    lifecycle: str           # "ephemeral" | "persistent"
    parent_actor_id: str     # 父 Agent id（"main" 表示主 Agent）
    session_id: str          # 所属会话
    status: str              # pending / running / idle
    outcome: str             # "" / success / failure / cancelled
    background: bool         # 是否后台运行
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    last_turn_time: float = field(default_factory=time.time)
    turn_count: int = 0
    error: Optional[str] = None
    result: Optional[str] = None
    cwd: Optional[str] = None          # peer 独立工作目录（worktree）
    _outcome_event: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> Dict:
        return {
            "actor_id": self.actor_id,
            "agent_type": self.agent_type,
            "description": self.description,
            "mode": self.mode,
            "lifecycle": self.lifecycle,
            "parent_actor_id": self.parent_actor_id,
            "session_id": self.session_id,
            "status": self.status,
            "outcome": self.outcome,
            "background": self.background,
            "created": self.created,
            "updated": self.updated,
            "last_turn_time": self.last_turn_time,
            "turn_count": self.turn_count,
            "error": self.error,
            "result": self.result,
            "cwd": self.cwd,
        }


@dataclass
class WaitResult:
    """wait() 返回结果 — 对齐 MiMo-Code WaitResult"""
    status: str              # idle / running / timeout / unknown
    outcome: str             # success / failure / cancelled / ""
    actor_id: str
    description: Optional[str] = None
    agent: Optional[str] = None
    background: Optional[bool] = None
    turn_count: Optional[int] = None
    result: Optional[str] = None
    error: Optional[str] = None
    timed_out: bool = False


# ============================================================================
# ActorRegistry — 子 Agent 注册表
# ============================================================================

class ActorRegistry:
    """子 Agent 注册表 — 分配 actor_id + 状态登记 + 查询"""

    def __init__(self):
        self._records: Dict[str, ActorRecord] = {}
        self._by_parent: Dict[str, List[str]] = {}  # parent_actor_id -> [actor_id...]
        self._lock = threading.Lock()
        self._seq = 0

    def allocate_actor_id(self, agent_type: str) -> str:
        """分配一个唯一 actor_id（如 subagent-0007）"""
        with self._lock:
            self._seq += 1
            return f"{agent_type}-{self._seq:04d}"

    def register(self, record: ActorRecord):
        """登记一个子 Agent"""
        with self._lock:
            self._records[record.actor_id] = record
            self._by_parent.setdefault(record.parent_actor_id, []).append(record.actor_id)

    def get(self, actor_id: str) -> Optional[ActorRecord]:
        with self._lock:
            return self._records.get(actor_id)

    def update_status(self, actor_id: str, status: str):
        with self._lock:
            rec = self._records.get(actor_id)
            if rec:
                rec.status = status
                rec.updated = time.time()

    def update_turn(self, actor_id: str):
        """推进 turn 计数 + 刷新活跃时间（防 stall 误判）"""
        with self._lock:
            rec = self._records.get(actor_id)
            if rec:
                rec.turn_count += 1
                rec.last_turn_time = time.time()
                rec.updated = time.time()

    def complete(self, actor_id: str, outcome: str, result: str = None, error: str = None):
        """标记终态并唤醒 wait()"""
        with self._lock:
            rec = self._records.get(actor_id)
            if not rec:
                return
            rec.status = "idle"
            rec.outcome = outcome
            rec.result = result
            rec.error = error
            rec.updated = time.time()
            rec._outcome_event.set()

    def cancel(self, actor_id: str):
        """取消子 Agent（graceful）"""
        self.complete(actor_id, "cancelled")

    def list_active(self) -> List[ActorRecord]:
        """列出活跃（pending/running）子 Agent"""
        with self._lock:
            return [r for r in self._records.values() if r.status in ("pending", "running")]

    def list_by_parent(self, parent_actor_id: str) -> List[ActorRecord]:
        """列出某父 Agent 的所有子 Agent"""
        with self._lock:
            ids = self._by_parent.get(parent_actor_id, [])
            return [self._records[i] for i in ids if i in self._records]

    def list_all(self) -> List[Dict]:
        with self._lock:
            return [r.to_dict() for r in self._records.values()]


# ============================================================================
# ActorWaiter — 等待子 Agent 完成
# ============================================================================

class ActorWaiter:
    """等待子 Agent 达到终态（借鉴 MiMo-Code waiter.ts）"""

    DEFAULT_TIMEOUT_MS = 600_000  # 10 分钟（对齐 MiMo-Code）

    def __init__(self, registry: ActorRegistry):
        self._registry = registry

    def wait(self, actor_id: str, timeout_ms: Optional[int] = None) -> WaitResult:
        """阻塞等待子 Agent 完成。

        快速路径：已 idle 且 outcome 非空 → 立即返回快照。
        慢路径：注册表快路径不满足 → 订阅 _outcome_event，带超时。
        """
        timeout = timeout_ms if timeout_ms is not None else self.DEFAULT_TIMEOUT_MS
        rec = self._registry.get(actor_id)
        if not rec:
            return WaitResult(status="unknown", outcome="", actor_id=actor_id)

        # 快速路径：已经是终态
        if rec.status == "idle" and rec.outcome:
            return self._snapshot(rec)

        # 慢路径：等待事件，带超时
        timeout_sec = max(0.001, timeout / 1000.0)
        got = rec._outcome_event.wait(timeout_sec)
        if not got:
            return WaitResult(
                status=rec.status, outcome=rec.outcome or "", actor_id=actor_id,
                description=rec.description, agent=rec.agent_type,
                background=rec.background, turn_count=rec.turn_count,
                timed_out=True,
            )
        return self._snapshot(self._registry.get(actor_id) or rec)

    @staticmethod
    def _snapshot(rec: ActorRecord) -> WaitResult:
        return WaitResult(
            status=rec.status, outcome=rec.outcome or "", actor_id=rec.actor_id,
            description=rec.description, agent=rec.agent_type,
            background=rec.background, turn_count=rec.turn_count,
            result=rec.result, error=rec.error,
            timed_out=False,
        )


# ============================================================================
# ActorSpawner — 动态创建子 Agent
# ============================================================================

class ActorSpawner:
    """动态创建子 Agent（借鉴 MiMo-Code spawn.ts）"""

    def __init__(self, registry: ActorRegistry):
        self._registry = registry
        self._lock = threading.Lock()
        self._cancel_events: Dict[str, threading.Event] = {}

    def spawn(self,
              agent_type: str,
              task: str,
              task_fn: Callable[..., str],
              description: str = None,
              mode: str = "subagent",
              lifecycle: str = "ephemeral",
              background: bool = False,
              parent_actor_id: str = "main",
              session_id: str = "default",
              cwd: str = None,
              task_args: tuple = (),
              task_kwargs: Dict = None,
              ) -> str:
        """创建一个子 Agent 并后台启动其工作线程。

        task_fn: 实际执行任务的函数，返回结果字符串。
        返回 actor_id；调用方可用 wait(actor_id) 等待完成。
        """
        actor_id = self._registry.allocate_actor_id(agent_type)
        rec = ActorRecord(
            actor_id=actor_id,
            agent_type=agent_type,
            description=description or agent_type,
            mode=mode,
            lifecycle=lifecycle,
            parent_actor_id=parent_actor_id,
            session_id=session_id,
            status="pending",
            outcome="",
            background=background,
            cwd=cwd,
        )
        self._registry.register(rec)

        # 取消标志（graceful 取消）
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[actor_id] = cancel_event

        def _worker():
            self._registry.update_status(actor_id, "running")
            self._registry.update_turn(actor_id)
            try:
                if cancel_event.is_set():
                    self._registry.complete(actor_id, "cancelled", result="cancelled before start")
                    return
                kwargs = dict(task_kwargs or {})
                if cwd and os.path.isdir(cwd):
                    _run_in_cwd(cwd, task_fn, task_args, kwargs, cancel_event,
                                self._registry, actor_id)
                else:
                    result = task_fn(*task_args, **kwargs)
                    self._registry.complete(actor_id, "success", result=result)
            except Exception as e:
                self._registry.complete(actor_id, "failure", error=str(e))
            finally:
                with self._lock:
                    self._cancel_events.pop(actor_id, None)

        t = threading.Thread(
            target=_worker,
            name=f"actor-{actor_id}",
            daemon=True,
        )
        t.start()
        return actor_id

    def cancel(self, actor_id: str, mode: str = "graceful"):
        """取消子 Agent — graceful: 置取消标志；forced: 直接标记 cancelled"""
        with self._lock:
            cancel_event = self._cancel_events.get(actor_id)
        if cancel_event:
            cancel_event.set()
        if mode == "forced":
            self._registry.cancel(actor_id)


# ============================================================================
# ActorSystem — 组合入口
# ============================================================================

class ActorMessageBus:
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()

    def register(self, actor_id: str, handler: Callable):
        with self._lock:
            self._handlers.setdefault(actor_id, []).append(handler)

    def unregister(self, actor_id: str):
        with self._lock:
            self._handlers.pop(actor_id, None)

    def send_message(self, from_id: str, to_id: str, msg_type: str, payload: Any):
        with self._lock:
            handlers = list(self._handlers.get(to_id, []))
        for h in handlers:
            try:
                h(from_id, msg_type, payload)
            except Exception:
                pass

    def broadcast(self, from_id: str, msg_type: str, payload: Any):
        with self._lock:
            all_ids = list(self._handlers.keys())
        for aid in all_ids:
            if aid != from_id:
                self.send_message(from_id, aid, msg_type, payload)


class ActorSystem:
    """Actor 系统组合入口 — registry + spawner + waiter 三合一"""

    def __init__(self):
        self.registry = ActorRegistry()
        self.spawner = ActorSpawner(self.registry)
        self.waiter = ActorWaiter(self.registry)
        self._message_bus = ActorMessageBus()

    # ---- 便捷方法 ----
    def spawn(self, agent_type: str, task: str, task_fn: Callable[..., str], **kwargs) -> str:
        """便捷：创建子 Agent，返回 actor_id"""
        return self.spawner.spawn(agent_type, task, task_fn, **kwargs)

    def wait(self, actor_id: str, timeout_ms: Optional[int] = None) -> WaitResult:
        """便捷：等待子 Agent 完成"""
        return self.waiter.wait(actor_id, timeout_ms)

    def cancel(self, actor_id: str, mode: str = "graceful"):
        self.spawner.cancel(actor_id, mode)

    def list_active(self) -> List[ActorRecord]:
        return self.registry.list_active()

    def list_all(self) -> List[Dict]:
        return self.registry.list_all()

    def get(self, actor_id: str) -> Optional[ActorRecord]:
        return self.registry.get(actor_id)

    # ---- 并行协作（多 Agent 同时跑，全部完成返回） ----
    def spawn_many_wait_all(self, jobs: List[Dict], timeout_ms: Optional[int] = None) -> List[WaitResult]:
        """批量创建子 Agent 并等待全部完成。

        jobs: [{agent_type, task, task_fn, ...spawn kwargs}]
        返回按 jobs 顺序排列的 WaitResult 列表。
        """
        handles = []
        for job in jobs:
            agent_type = job.get("agent_type", "worker")
            task = job.get("task", "")
            task_fn = job.get("task_fn")
            kwargs = {k: v for k, v in job.items() if k not in ("agent_type", "task", "task_fn")}
            aid = self.spawn(agent_type, task, task_fn, **kwargs)
            handles.append(aid)
        return [self.wait(aid, timeout_ms) for aid in handles]

    def send_message(self, from_actor_id, to_actor_id, msg_type, payload):
        self._message_bus.send_message(from_actor_id, to_actor_id, msg_type, payload)

    def broadcast(self, from_actor_id, msg_type, payload):
        self._message_bus.broadcast(from_actor_id, msg_type, payload)

    def on_message(self, actor_id, handler):
        self._message_bus.register(actor_id, handler)
