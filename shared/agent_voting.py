# -*- coding: utf-8 -*-
"""
Agent 投票决策机制 (AgentVoting)
================================
多 Agent 协同中的重要决策投票系统。

功能：
1. 发起投票 — 任意 agent 可针对重要决策发起投票
2. 多种投票策略 — 多数决、共识决、加权投票、绝对多数
3. 投票期限 — 支持超时自动截止，避免阻塞
4. 结果通知 — 投票结束后通知所有参与者
5. 决策记录 — 所有投票记录到 ProjectLog，便于审计

使用示例：
    voting = AgentVoting(orchestrator)
    session = voting.start_vote(
        topic="是否重构数据库层",
        description="当前数据库访问层存在性能问题...",
        initiator="agent_backend",
        voter_ids=["agent_backend", "agent_frontend", "agent_architect"],
        strategy=VotingStrategy.SUPERMAJORITY,
    )
    voting.cast_vote(session.vote_id, "agent_frontend", VoteOption.AGREE, reason="支持重构")
    voting.cast_vote(session.vote_id, "agent_architect", VoteOption.DISAGREE, reason="风险过大")
    result = voting.close_vote(session.vote_id)
"""

import time
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum


# ============================================================
# 枚举与数据结构
# ============================================================

class VotingStrategy(Enum):
    """投票策略"""
    MAJORITY = "majority"           # 多数决（>50% 赞成即通过）
    SUPERMAJORITY = "supermajority" # 绝对多数（>=2/3 赞成才通过）
    CONSENSUS = "consensus"         # 共决议（全员一致才通过）
    WEIGHTED = "weighted"           # 加权投票（按 agent 权重计算）


class VoteOption(Enum):
    """投票选项"""
    AGREE = "agree"         # 赞成
    DISAGREE = "disagree"   # 反对
    ABSTAIN = "abstain"     # 弃权


class VoteStatus(Enum):
    """投票状态"""
    OPEN = "open"           # 进行中
    CLOSED = "closed"       # 已关闭
    EXPIRED = "expired"     # 已超时
    CANCELLED = "cancelled" # 已取消


@dataclass
class VoteRecord:
    """单次投票记录"""
    voter_id: str
    option: VoteOption
    reason: str = ""
    weight: float = 1.0     # 权重（加权投票时使用）
    timestamp: float = field(default_factory=time.time)


@dataclass
class VotingSession:
    """投票会话"""
    vote_id: str
    topic: str
    description: str
    initiator: str
    voter_ids: List[str]
    strategy: VotingStrategy
    status: VoteStatus = VoteStatus.OPEN
    votes: List[VoteRecord] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    deadline: Optional[float] = None     # 超时时间戳
    closed_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VotingResult:
    """投票结果"""
    vote_id: str
    topic: str
    passed: bool               # 是否通过
    strategy: VotingStrategy
    agree_count: int
    disagree_count: int
    abstain_count: int
    total_voters: int
    participation_rate: float  # 参与率
    agree_ratio: float         # 赞成比例
    details: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# Agent 投票决策器
# ============================================================

class AgentVoting:
    """
    Agent 投票决策器
    ================
    - 支持多种投票策略
    - 线程安全
    - 超时自动关闭
    - 结果通知回调
    - 决策审计日志
    """

    DEFAULT_VOTE_TIMEOUT = 300  # 默认投票超时 5 分钟
    _vote_counter = 0
    _counter_lock = threading.Lock()

    def __init__(self, orchestrator=None, project_log=None):
        """
        Args:
            orchestrator: AgentOrchestrator 实例（可选，用于获取 agent 列表和广播）
            project_log: ProjectLog 实例（可选，用于审计日志）
        """
        self._orchestrator = orchestrator
        self._project_log = project_log
        self._sessions: Dict[str, VotingSession] = {}
        self._lock = threading.RLock()
        self._callbacks: Dict[str, List[Callable]] = {
            'vote_started': [],
            'vote_cast': [],
            'vote_closed': [],
            'vote_expired': [],
        }
        # Agent 权重映射（加权投票时使用）
        self._weights: Dict[str, float] = {}

    # ============================================================
    # 投票发起
    # ============================================================

    def start_vote(self,
                   topic: str,
                   description: str,
                   initiator: str,
                   voter_ids: List[str],
                   strategy: VotingStrategy = VotingStrategy.MAJORITY,
                   timeout: float = None,
                   metadata: Dict = None) -> VotingSession:
        """
        发起投票

        Args:
            topic: 投票主题
            description: 详细描述
            initiator: 发起者 agent_id
            voter_ids: 参与投票的 agent 列表
            strategy: 投票策略
            timeout: 超时时间（秒），None 使用默认
            metadata: 附加元数据

        Returns:
            VotingSession 投票会话
        """
        with self._lock:
            vote_id = self._gen_vote_id()
            timeout = timeout or self.DEFAULT_VOTE_TIMEOUT
            deadline = time.time() + timeout

            session = VotingSession(
                vote_id=vote_id,
                topic=topic,
                description=description,
                initiator=initiator,
                voter_ids=list(voter_ids),
                strategy=strategy,
                deadline=deadline,
                metadata=metadata or {},
            )
            self._sessions[vote_id] = session

            # 记录审计日志
            self._log_vote_event(session, "vote_started",
                                 f"发起投票: {topic} (策略={strategy.value}, 参与者={len(voter_ids)})")

            # 通知回调
            self._emit('vote_started', session)

            # 启动超时检测线程
            self._start_timeout_watcher(vote_id, timeout)

            return session

    def cast_vote(self, vote_id: str, voter_id: str,
                  option: VoteOption, reason: str = "") -> bool:
        """
        投票

        Args:
            vote_id: 投票会话 ID
            voter_id: 投票者 agent_id
            option: 投票选项
            reason: 投票理由

        Returns:
            是否成功
        """
        with self._lock:
            session = self._sessions.get(vote_id)
            if not session:
                return False
            if session.status != VoteStatus.OPEN:
                return False
            if voter_id not in session.voter_ids:
                return False
            # 检查是否已投过票（覆盖旧投票）
            session.votes = [v for v in session.votes if v.voter_id != voter_id]

            weight = self._weights.get(voter_id, 1.0)
            record = VoteRecord(
                voter_id=voter_id,
                option=option,
                reason=reason,
                weight=weight,
            )
            session.votes.append(record)

            self._log_vote_event(session, "vote_cast",
                                 f"{voter_id} 投票: {option.value}" + (f" ({reason})" if reason else ""))

            self._emit('vote_cast', {'session': session, 'vote': record})

            # 检查是否所有人都已投票（共识决可提前结束）
            if session.strategy == VotingStrategy.CONSENSUS:
                voted_ids = {v.voter_id for v in session.votes}
                if voted_ids == set(session.voter_ids):
                    self._close_vote_internal(vote_id)

            return True

    def close_vote(self, vote_id: str) -> Optional[VotingResult]:
        """
        手动关闭投票并计算结果

        Args:
            vote_id: 投票会话 ID

        Returns:
            VotingResult 投票结果，或 None（会话不存在）
        """
        with self._lock:
            return self._close_vote_internal(vote_id)

    def cancel_vote(self, vote_id: str, reason: str = "") -> bool:
        """取消投票"""
        with self._lock:
            session = self._sessions.get(vote_id)
            if not session or session.status != VoteStatus.OPEN:
                return False
            session.status = VoteStatus.CANCELLED
            session.closed_at = time.time()
            session.result = {"cancelled": True, "reason": reason}
            self._log_vote_event(session, "vote_cancelled", f"投票取消: {reason}")
            return True

    # ============================================================
    # 结果计算
    # ============================================================

    def _close_vote_internal(self, vote_id: str) -> Optional[VotingResult]:
        """内部关闭投票并计算结果"""
        session = self._sessions.get(vote_id)
        if not session:
            return None
        if session.status != VoteStatus.OPEN:
            return self._build_result(session) if session.result else None

        session.status = VoteStatus.CLOSED
        session.closed_at = time.time()

        result = self._compute_result(session)
        session.result = {
            "passed": result.passed,
            "agree_count": result.agree_count,
            "disagree_count": result.disagree_count,
            "abstain_count": result.abstain_count,
            "participation_rate": result.participation_rate,
            "agree_ratio": result.agree_ratio,
        }

        self._log_vote_event(session, "vote_closed",
                             f"投票结束: {'通过' if result.passed else '未通过'} "
                             f"(赞成={result.agree_count}, 反对={result.disagree_count}, "
                             f"弃权={result.abstain_count}, 参与率={result.participation_rate:.0%})")

        self._emit('vote_closed', result)

        # 通知所有参与者（通过 orchestrator 广播）
        if self._orchestrator:
            try:
                for voter_id in session.voter_ids:
                    self._orchestrator._emit('vote_result', {
                        'vote_id': vote_id,
                        'voter_id': voter_id,
                        'passed': result.passed,
                        'topic': session.topic,
                    })
            except Exception:
                pass

        return result

    def _compute_result(self, session: VotingSession) -> VotingResult:
        """根据投票策略计算结果"""
        agree_count = sum(1 for v in session.votes if v.option == VoteOption.AGREE)
        disagree_count = sum(1 for v in session.votes if v.option == VoteOption.DISAGREE)
        abstain_count = sum(1 for v in session.votes if v.option == VoteOption.ABSTAIN)
        total_voters = len(session.voter_ids)
        voted_count = len(session.votes)
        participation_rate = voted_count / total_voters if total_voters > 0 else 0.0

        # 加权计算
        if session.strategy == VotingStrategy.WEIGHTED:
            weighted_agree = sum(v.weight for v in session.votes if v.option == VoteOption.AGREE)
            weighted_total = sum(v.weight for v in session.votes if v.option != VoteOption.ABSTAIN)
            agree_ratio = weighted_agree / weighted_total if weighted_total > 0 else 0.0
        else:
            effective_count = agree_count + disagree_count  # 排除弃权
            agree_ratio = agree_count / effective_count if effective_count > 0 else 0.0

        # 判断是否通过
        passed = False
        if session.strategy == VotingStrategy.MAJORITY:
            passed = agree_ratio > 0.5
        elif session.strategy == VotingStrategy.SUPERMAJORITY:
            passed = agree_ratio >= 2.0 / 3.0
        elif session.strategy == VotingStrategy.CONSENSUS:
            passed = agree_count == total_voters and disagree_count == 0
        elif session.strategy == VotingStrategy.WEIGHTED:
            passed = agree_ratio > 0.5

        # 至少需要 1 人参与
        if voted_count == 0:
            passed = False

        return VotingResult(
            vote_id=session.vote_id,
            topic=session.topic,
            passed=passed,
            strategy=session.strategy,
            agree_count=agree_count,
            disagree_count=disagree_count,
            abstain_count=abstain_count,
            total_voters=total_voters,
            participation_rate=round(participation_rate, 3),
            agree_ratio=round(agree_ratio, 3),
            details={
                "strategy": session.strategy.value,
                "initiator": session.initiator,
                "voted_count": voted_count,
                "weighted": session.strategy == VotingStrategy.WEIGHTED,
            },
        )

    def _build_result(self, session: VotingSession) -> VotingResult:
        """从已有结果的 session 构建 VotingResult"""
        r = session.result or {}
        return VotingResult(
            vote_id=session.vote_id,
            topic=session.topic,
            passed=r.get("passed", False),
            strategy=session.strategy,
            agree_count=r.get("agree_count", 0),
            disagree_count=r.get("disagree_count", 0),
            abstain_count=r.get("abstain_count", 0),
            total_voters=len(session.voter_ids),
            participation_rate=r.get("participation_rate", 0.0),
            agree_ratio=r.get("agree_ratio", 0.0),
        )

    # ============================================================
    # 超时检测
    # ============================================================

    def _start_timeout_watcher(self, vote_id: str, timeout: float):
        """启动超时检测线程"""
        def _watcher():
            # 等待超时
            time.sleep(timeout)
            with self._lock:
                session = self._sessions.get(vote_id)
                if session and session.status == VoteStatus.OPEN:
                    session.status = VoteStatus.EXPIRED
                    session.closed_at = time.time()
                    result = self._compute_result(session)
                    session.result = {
                        "passed": result.passed,
                        "agree_count": result.agree_count,
                        "disagree_count": result.disagree_count,
                        "abstain_count": result.abstain_count,
                        "participation_rate": result.participation_rate,
                        "agree_ratio": result.agree_ratio,
                        "expired": True,
                    }
                    self._log_vote_event(session, "vote_expired",
                                         f"投票超时自动关闭")
                    self._emit('vote_expired', result)

        t = threading.Thread(target=_watcher, daemon=True)
        t.start()

    # ============================================================
    # 权重管理
    # ============================================================

    def set_weight(self, agent_id: str, weight: float):
        """设置 agent 投票权重"""
        with self._lock:
            self._weights[agent_id] = max(0.0, weight)

    def get_weights(self) -> Dict[str, float]:
        """获取所有权重"""
        return dict(self._weights)

    # ============================================================
    # 查询
    # ============================================================

    def get_vote(self, vote_id: str) -> Optional[VotingSession]:
        """获取投票会话"""
        return self._sessions.get(vote_id)

    def get_active_votes(self) -> List[VotingSession]:
        """获取所有进行中的投票"""
        with self._lock:
            return [s for s in self._sessions.values() if s.status == VoteStatus.OPEN]

    def get_vote_history(self, limit: int = 20) -> List[VotingSession]:
        """获取投票历史"""
        with self._lock:
            sessions = list(self._sessions.values())
            sessions.sort(key=lambda s: s.created_at, reverse=True)
            return sessions[:limit]

    def get_agent_votes(self, agent_id: str) -> List[VotingSession]:
        """获取 agent 参与的所有投票"""
        with self._lock:
            return [s for s in self._sessions.values() if agent_id in s.voter_ids]

    def get_statistics(self) -> Dict:
        """获取投票统计"""
        with self._lock:
            total = len(self._sessions)
            active = sum(1 for s in self._sessions.values() if s.status == VoteStatus.OPEN)
            closed = sum(1 for s in self._sessions.values() if s.status == VoteStatus.CLOSED)
            expired = sum(1 for s in self._sessions.values() if s.status == VoteStatus.EXPIRED)
            passed = sum(1 for s in self._sessions.values()
                         if s.result and s.result.get("passed"))
            return {
                "total_votes": total,
                "active": active,
                "closed": closed,
                "expired": expired,
                "passed": passed,
                "failed": closed + expired - passed,
                "pass_rate": round(passed / max(closed + expired, 1), 3),
            }

    # ============================================================
    # 事件订阅
    # ============================================================

    def on(self, event_name: str, callback: Callable):
        """订阅事件：vote_started / vote_cast / vote_closed / vote_expired"""
        if event_name in self._callbacks:
            self._callbacks[event_name].append(callback)

    def _emit(self, event_name: str, data: Any):
        for cb in self._callbacks.get(event_name, []):
            try:
                cb(data)
            except Exception as e:
                print(f"[AgentVoting] 事件回调异常 ({event_name}): {e}")

    # ============================================================
    # 内部工具
    # ============================================================

    @classmethod
    def _gen_vote_id(cls) -> str:
        with cls._counter_lock:
            cls._vote_counter += 1
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            return f"vote_{ts}_{cls._vote_counter:04d}"

    def _log_vote_event(self, session: VotingSession, event: str, message: str):
        """记录投票事件到 ProjectLog"""
        if self._project_log:
            try:
                from .project_log import EventType
                self._project_log.log(
                    event_type=EventType.INFO,
                    project_id=session.metadata.get("project_id", ""),
                    agent_id=session.initiator,
                    title=f"[投票] {message}",
                    description=f"vote_id={session.vote_id}, topic={session.topic}",
                    metadata={"vote_id": session.vote_id, "event": event},
                )
            except Exception as e:
                print(f"[AgentVoting] 日志记录失败: {e}")
