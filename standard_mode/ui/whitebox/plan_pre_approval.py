# -*- coding: utf-8 -*-
"""
PlanPreApproval — 计划预批准模式
=================================
当 Agent 生成计划后，用户可一次性批准整个计划。
批准后，计划内所有工具调用自动放行（免打扰），除非遇到高风险操作。

状态机:
  IDLE → PLAN_PENDING → PLAN_APPROVED / PLAN_DENIED
  PLAN_APPROVED: 计划内工具自动批准，高风险仍需确认
  PLAN_DENIED:   回到逐个审批模式

集成点:
  - StateProjector 在检测到计划步骤时触发 plan_ready 信号
  - RunRegistry 持有 plan_approved 标志
  - ApprovalCard 检查 plan_approved 状态，自动批准低/中风险工具
"""
from __future__ import annotations

from typing import List, Optional, Set

from PyQt5.QtCore import QObject, pyqtSignal

from ui.whitebox.state_model import (
    RunRegistry, Run, Step, StepStatus, Approval, ApprovalStatus,
)

_HIGH_RISK_TOOLS = {"bash", "delete", "rm"}
_HIGH_RISK_PATTERNS = {"rm -rf", "sudo", "chmod", "format"}


class PlanPreApproval(QObject):
    plan_ready = pyqtSignal(str, list)
    plan_approved_signal = pyqtSignal(str)
    plan_denied_signal = pyqtSignal(str)
    auto_approved_tool = pyqtSignal(str, str)

    def __init__(self, registry: RunRegistry, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._approved_plans: Set[str] = set()
        self._denied_plans: Set[str] = set()

    def submit_plan(self, run_id: str, steps: List[Step]) -> None:
        run = self._registry.get_run(run_id)
        if not run:
            return
        if run_id in self._approved_plans or run_id in self._denied_plans:
            return
        summary_steps = []
        for s in steps:
            summary_steps.append({
                "step_id": s.step_id,
                "title": s.title,
                "tool_count": len(s.tool_calls),
                "risk_level": self._assess_step_risk(s),
            })
        self.plan_ready.emit(run_id, summary_steps)

    def approve_plan(self, run_id: str) -> None:
        self._approved_plans.add(run_id)
        self._denied_plans.discard(run_id)
        run = self._registry.get_run(run_id)
        if run:
            run.plan_approved = True
            self._registry.run_updated.emit(run_id)
        self.plan_approved_signal.emit(run_id)
        self._auto_approve_pending(run_id)

    def deny_plan(self, run_id: str) -> None:
        self._denied_plans.add(run_id)
        self._approved_plans.discard(run_id)
        run = self._registry.get_run(run_id)
        if run:
            run.plan_approved = False
            self._registry.run_updated.emit(run_id)
        self.plan_denied_signal.emit(run_id)

    def is_tool_auto_approved(self, run_id: str, tool_name: str,
                              args: dict = None) -> bool:
        if run_id not in self._approved_plans:
            return False
        if tool_name in _HIGH_RISK_TOOLS:
            return False
        if args:
            for pattern in _HIGH_RISK_PATTERNS:
                for v in args.values():
                    if isinstance(v, str) and pattern in v.lower():
                        return False
        return True

    def _auto_approve_pending(self, run_id: str) -> None:
        for approval_id, approval in list(self._registry._approvals.items()):
            if approval.run_id != run_id:
                continue
            if approval.status != ApprovalStatus.PENDING:
                continue
            if not self.is_tool_auto_approved(run_id, approval.tool_name):
                continue
            self._registry.decide_approval(approval_id, ApprovalStatus.GRANTED, "plan_pre_approval")
            self.auto_approved_tool.emit(run_id, approval_id)

    def _assess_step_risk(self, step: Step) -> str:
        for tc in step.tool_calls:
            if tc.tool_name in _HIGH_RISK_TOOLS:
                return "high"
            for v in tc.args.values():
                if isinstance(v, str):
                    for pattern in _HIGH_RISK_PATTERNS:
                        if pattern in v.lower():
                            return "high"
        has_write = any(tc.tool_name in ("write", "edit", "multiedit")
                        for tc in step.tool_calls)
        if has_write:
            return "medium"
        return "low"

    def clear(self) -> None:
        self._approved_plans.clear()
        self._denied_plans.clear()
