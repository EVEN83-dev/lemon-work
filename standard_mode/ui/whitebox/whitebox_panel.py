# -*- coding: utf-8 -*-
"""
WhiteboxPanel — 白盒化总面板
=============================
组合所有白盒子组件:
  - RunFoldWidget列表 (每Run一个)
  - StepProgressBar (当前Run的步骤进度)
  - ApprovalCard (待审批卡片)
  - PlanPreApproval (计划预批准)
订阅 RunRegistry 信号，自动增删更新
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (
    QScrollArea, QVBoxLayout, QWidget, QLabel, QSizePolicy,
)

from ui.design.tokens import Lemon
from ui.whitebox.state_model import (
    Run, RunStatus, Step, ToolCall, ToolCallStatus,
    Approval, ApprovalStatus, RunRegistry,
)
from ui.whitebox.state_projector import StateProjector
from ui.whitebox.run_fold_widget import RunFoldWidget
from ui.whitebox.approval_card import ApprovalCard
from ui.whitebox.step_progress_bar import StepProgressBar
from ui.whitebox.plan_pre_approval import PlanPreApproval
from ui.whitebox.monitor_widget import MonitorWidget
from ui.whitebox.workflow_tree import WorkflowTree


class WhiteboxPanel(QScrollArea):
    approval_decided = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._registry = RunRegistry(parent=self)
        self._projector = StateProjector(self._registry, parent=self)
        self._plan_pre_approval = PlanPreApproval(self._registry, parent=self)
        self._run_widgets: Dict[str, RunFoldWidget] = {}
        self._approval_cards: Dict[str, ApprovalCard] = {}
        self._current_progress: Optional[StepProgressBar] = None
        self._workflow_tree: Optional[WorkflowTree] = None
        self._plan_panel = None
        self._init_ui()
        self._connect_registry_signals()

    def _init_ui(self):
        T = Lemon
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(
            f"QScrollArea {{ background: {T.BG}; border: none; }}"
        )
        self._container = QWidget()
        self._container.setStyleSheet(f"background: {T.BG};")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(T.SP_S, T.SP_S, T.SP_S, T.SP_S)
        self._layout.setSpacing(T.SP_S)
        self._layout.setAlignment(Qt.AlignTop)

        self._monitor = MonitorWidget(self._container)
        self._layout.addWidget(self._monitor)
        self.setWidget(self._container)

    def _connect_registry_signals(self):
        self._registry.run_added.connect(self._on_run_added)
        self._registry.run_updated.connect(self._on_run_updated)
        self._registry.run_completed.connect(self._on_run_completed)
        self._registry.run_failed.connect(self._on_run_failed)
        self._registry.step_updated.connect(self._on_step_updated)
        self._registry.tool_call_updated.connect(self._on_tool_call_updated)
        self._registry.approval_requested.connect(self._on_approval_requested)
        self._registry.approval_decided.connect(self._on_approval_decided)
        self._registry.artifact_added.connect(self._on_artifact_added)
        self._registry.registry_cleared.connect(self._on_registry_cleared)
        self._plan_pre_approval.plan_ready.connect(self._on_plan_ready)
        self._plan_pre_approval.auto_approved_tool.connect(
            self._on_auto_approved)

    def _on_run_added(self, run_id: str):
        run = self._registry.get_run(run_id)
        if not run:
            return
        w = RunFoldWidget(run, self._registry, self._container)
        self._run_widgets[run_id] = w
        self._layout.insertWidget(0, w)
        self.set_current_run(run_id)

    def _on_run_updated(self, run_id: str):
        w = self._run_widgets.get(run_id)
        run = self._registry.get_run(run_id)
        if w and run:
            w.update_run(run)
            self._update_progress_bar(run)

    def _on_run_completed(self, run_id: str):
        pass

    def _on_run_failed(self, run_id: str):
        pass

    def _on_step_updated(self, run_id: str, step_id: str):
        run = self._registry.get_run(run_id)
        if not run:
            return
        step = None
        for s in run.steps:
            if s.step_id == step_id:
                step = s
                break
        if not step:
            return
        w = self._run_widgets.get(run_id)
        if w:
            existing_steps = {sw._step.step_id for sw in w._step_widgets.values()}
            if step_id not in existing_steps:
                w.add_step(step)
            self._update_progress_bar(run)
        if len(run.steps) >= 2 and not run.plan_approved:
            self._plan_pre_approval.submit_plan(run_id, run.steps)

    def _on_tool_call_updated(self, run_id: str, step_id: str, call_id: str):
        run = self._registry.get_run(run_id)
        if not run:
            return
        for step in run.steps:
            for tc in step.tool_calls:
                if tc.call_id == call_id:
                    w = self._run_widgets.get(run_id)
                    if w:
                        w.update_tool_call(tc)
                    return

    def _on_approval_requested(self, run_id: str, approval_id: str):
        approval = self._registry.get_approval(approval_id)
        if not approval:
            return
        if self._plan_pre_approval.is_tool_auto_approved(
                run_id, approval.tool_name):
            self._registry.decide_approval(
                approval_id, ApprovalStatus.GRANTED, "plan_pre_approval")
            return
        card = ApprovalCard(approval, self._container)
        card.approved.connect(
            lambda aid: self._on_card_approved(aid))
        card.denied.connect(
            lambda aid: self._on_card_denied(aid))
        self._approval_cards[approval_id] = card
        self._layout.addWidget(card)

    def _on_approval_decided(self, run_id: str, approval_id: str):
        card = self._approval_cards.pop(approval_id, None)
        if card:
            card.cleanup()
            card.setParent(None)
            card.deleteLater()

    def _on_artifact_added(self, run_id: str, artifact_id: str):
        w = self._run_widgets.get(run_id)
        run = self._registry.get_run(run_id)
        if w and run:
            w.update_run(run)

    def _on_registry_cleared(self):
        for w in self._run_widgets.values():
            w.setParent(None)
            w.deleteLater()
        self._run_widgets.clear()
        for c in self._approval_cards.values():
            c.cleanup()
            c.setParent(None)
            c.deleteLater()
        self._approval_cards.clear()
        if self._current_progress:
            self._current_progress.setParent(None)
            self._current_progress.deleteLater()
            self._current_progress = None

    def _on_plan_ready(self, run_id: str, steps_summary: list):
        if len(steps_summary) > 0:
            high_risk = any(s.get("risk_level") == "high" for s in steps_summary)
            if not high_risk:
                self._plan_pre_approval.approve_plan(run_id)

    def _on_auto_approved(self, run_id: str, approval_id: str):
        pass

    def _on_card_approved(self, approval_id: str):
        self._registry.decide_approval(
            approval_id, ApprovalStatus.GRANTED, "user")
        self.approval_decided.emit(approval_id, "granted")

    def _on_card_denied(self, approval_id: str):
        self._registry.decide_approval(
            approval_id, ApprovalStatus.DENIED, "user")
        self.approval_decided.emit(approval_id, "denied")

    def _update_progress_bar(self, run: Run):
        if not run.steps:
            return
        if self._current_progress:
            self._current_progress.update_steps(run.steps)
        else:
            self._current_progress = StepProgressBar(
                run.steps, self._container)
            self._layout.insertWidget(0, self._current_progress)

    @property
    def registry(self) -> RunRegistry:
        return self._registry

    @property
    def projector(self) -> StateProjector:
        return self._projector

    @property
    def plan_pre_approval(self) -> PlanPreApproval:
        return self._plan_pre_approval

    def create_workflow_tree(self) -> WorkflowTree:
        """创建并返回绑定 registry 的 WorkflowTree，同时启动 projector→tree 增量同步。"""
        if self._workflow_tree is None:
            self._workflow_tree = WorkflowTree(self._registry, parent=None)
            self._projector.sync_to_tree(self._workflow_tree)
            self._workflow_tree.full_sync(self._registry)
        return self._workflow_tree

    def create_plan_panel(self):
        """创建并返回绑定 registry 的 PlanPanel。"""
        if self._plan_panel is None:
            from ui.plan_panel import PlanPanel
            self._plan_panel = PlanPanel(self._registry, parent=None)
            self._registry.step_updated.connect(self._plan_panel.on_step_updated)
            self._registry.run_updated.connect(self._plan_panel.on_run_updated)
        return self._plan_panel

    def bind_trajectory_panel(self, trajectory_panel) -> None:
        """将 TrajectoryPanel 的 event_clicked 信号绑定到 WorkflowTree 高亮。"""
        if self._workflow_tree:
            trajectory_panel.event_clicked.connect(
                self._workflow_tree.highlight_item
            )

    def set_current_run(self, run_id: str) -> None:
        """设置当前活跃 Run，PlanPanel 绑定到此 Run。"""
        if self._plan_panel:
            self._plan_panel.bind_run(run_id)
