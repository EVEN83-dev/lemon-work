# -*- coding: utf-8 -*-
"""
RunFoldWidget — Run 自动折叠/展开摘要行
=========================================
一个 Run 对应一个 RunFoldWidget:
  - 折叠态: 单行摘要 (状态灯 + 用户prompt + 工具数 + 耗时 + 展开按钮)
  - 展开态: 摘要行 + Steps列表 + ToolCall卡片 + Artifacts列表
折叠策略: Run 完成后自动折叠(3秒延迟)，用户可手动展开
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QFrame,
)

from ui.design.tokens import Lemon
from ui.design.icons import ICON_RUNNING, ICON_SUCCESS, ICON_FAILED, ICON_TOOL, ICON_DOC, load_pixmap
from ui.whitebox.state_model import (
    Run, RunStatus, Step, StepStatus, ToolCall, ToolCallStatus,
    Artifact, ArtifactKind, RunRegistry,
)
from ui.whitebox.tool_renderers import FastToolChip, SlowToolCard, create_tool_widget


_RUN_STATUS_DISPLAY = {
    RunStatus.QUEUED: ("●", Lemon.SECONDARY, "排队中"),
    RunStatus.RUNNING: ("●", Lemon.STATUS_RUNNING, "执行中"),
    RunStatus.WAITING_APPROVAL: ("●", Lemon.BRAND_ORANGE, "等待审批"),
    RunStatus.COMPLETED: ("●", Lemon.SUCCESS, "已完成"),
    RunStatus.FAILED: ("●", Lemon.ERROR, "失败"),
    RunStatus.CANCELLED: ("●", Lemon.TEXT_MUTED, "已取消"),
}

_STEP_STATUS_DISPLAY = {
    StepStatus.PENDING: (Lemon.TEXT_MUTED, "○"),
    StepStatus.ACTIVE: (Lemon.STATUS_RUNNING, "●"),
    StepStatus.DONE: (Lemon.SUCCESS, "●"),
    StepStatus.FAILED: (Lemon.ERROR, "●"),
    StepStatus.SKIPPED: (Lemon.TEXT_MUTED, "—"),
}


class _RunSummaryBar(QFrame):
    fold_toggled = pyqtSignal(str, bool)

    def __init__(self, run: Run, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._run_id = run.run_id
        self._is_expanded = run.is_expanded
        self._init_ui(run)

    def _init_ui(self, run: Run):
        T = Lemon
        self.setObjectName("runSummaryBar")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame#runSummaryBar {{ background: {T.DARK_BG_3}; "
            f"border: 1px solid {T.BORDER}; border-radius: {T.R_M}px; "
            f"padding: 0; }}"
            f"QFrame#runSummaryBar:hover {{ border-color: {T.BRAND_ORANGE}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(T.SP_S)

        dot_char, dot_color, _ = _RUN_STATUS_DISPLAY.get(
            run.status, ("●", Lemon.SECONDARY, "")
        )
        status_dot = QLabel(dot_char)
        status_dot.setStyleSheet(
            f"color: {dot_color}; font-size: 10px; background: transparent; border: none;"
        )
        status_dot.setFixedSize(12, 12)
        layout.addWidget(status_dot)

        prompt = run.user_prompt[:60] + ("..." if len(run.user_prompt) > 60 else "")
        prompt_label = QLabel(prompt)
        prompt_label.setStyleSheet(
            f"color: {T.DARK_TEXT_1}; font-size: {T.FS_BODY}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        prompt_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(prompt_label)

        tc_count = sum(len(s.tool_calls) for s in run.steps)
        tools_label = QLabel(f"🔧{tc_count}")
        tools_label.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        layout.addWidget(tools_label)

        if run.elapsed_ms > 0:
            dur = f"{run.elapsed_ms / 1000:.1f}s"
        elif run.started_at:
            dur = f"{(time.time() - run.started_at):.1f}s"
        else:
            dur = ""
        if dur:
            dur_label = QLabel(dur)
            dur_label.setStyleSheet(
                f"color: {T.TEXT_MUTED}; font-size: {T.FS_CAPTION}px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            dur_label.setFixedWidth(50)
            dur_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(dur_label)

        self._toggle_btn = QPushButton("▼" if self._is_expanded else "▶")
        self._toggle_btn.setObjectName("ghostBtn")
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setFixedSize(18, 18)
        self._toggle_btn.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: 10px; border: none; background: transparent;"
        )
        self._toggle_btn.clicked.connect(self._toggle)
        layout.addWidget(self._toggle_btn)

    def _toggle(self):
        self._is_expanded = not self._is_expanded
        self._toggle_btn.setText("▼" if self._is_expanded else "▶")
        self.fold_toggled.emit(self._run_id, self._is_expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._is_expanded = expanded
        self._toggle_btn.setText("▼" if expanded else "▶")


class _StepWidget(QFrame):
    def __init__(self, step: Step, run_id: str,
                 registry: RunRegistry, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._step = step
        self._run_id = run_id
        self._registry = registry
        self._tool_widgets: Dict[str, QWidget] = {}
        self._init_ui(step)

    def _init_ui(self, step: Step):
        T = Lemon
        self.setObjectName("stepWidget")
        self.setStyleSheet(
            f"QFrame#stepWidget {{ background: transparent; "
            f"border: none; border-left: 2px solid {T.BORDER}; "
            f"margin-left: {T.SP_M}px; padding-left: {T.SP_S}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_XS, 0, T.SP_XS)
        layout.setSpacing(T.SP_XS)

        status_color, status_char = _STEP_STATUS_DISPLAY.get(
            step.status, (Lemon.SECONDARY, "○")
        )
        header = QHBoxLayout()
        header.setSpacing(T.SP_XS)
        status_label = QLabel(status_char)
        status_label.setStyleSheet(
            f"color: {status_color}; font-size: 10px; background: transparent; border: none;"
        )
        status_label.setFixedSize(10, 10)
        header.addWidget(status_label)

        title = QLabel(step.title)
        title.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_CAPTION}px; font-weight: bold; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        if len(step.tool_calls) > 1:
            fast_row = QHBoxLayout()
            fast_row.setSpacing(T.SP_XS)
            has_fast = False
            for tc in step.tool_calls:
                if tc.is_fast and tc.status == ToolCallStatus.SUCCESS:
                    chip = FastToolChip(tc)
                    fast_row.addWidget(chip)
                    self._tool_widgets[tc.call_id] = chip
                    has_fast = True
                else:
                    card = SlowToolCard(tc)
                    layout.addWidget(card)
                    self._tool_widgets[tc.call_id] = card
            if has_fast:
                fast_row.addStretch()
                layout.addLayout(fast_row)
        elif len(step.tool_calls) == 1:
            tc = step.tool_calls[0]
            widget = create_tool_widget(tc)
            layout.addWidget(widget)
            self._tool_widgets[tc.call_id] = widget

    def update_tool_call(self, tc: ToolCall) -> None:
        widget = self._tool_widgets.get(tc.call_id)
        if widget and isinstance(widget, SlowToolCard):
            widget.update_from_model(tc)


class _ArtifactsRow(QWidget):
    def __init__(self, artifacts: List[Artifact], parent: Optional[QWidget] = None):
        super().__init__(parent)
        T = Lemon
        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.SP_M, 2, T.SP_M, 2)
        layout.setSpacing(T.SP_XS)
        for art in artifacts[:5]:
            kind_icon = "📄"
            if art.kind == ArtifactKind.FILE_DIFF:
                kind_icon = "✏️"
            elif art.kind == ArtifactKind.FILE_CREATED:
                kind_icon = "📄"
            elif art.kind == ArtifactKind.FILE_DELETED:
                kind_icon = "🗑️"
            label = QLabel(f"{kind_icon} {art.title[:30]}")
            label.setStyleSheet(
                f"color: {T.ACCENT_GREEN}; font-size: {T.FS_CAPTION}px; "
                f"font-family: '{T.FONT}'; background: {T.SUCCESS_BG_DARK}; "
                f"border: 1px solid {T.SUCCESS_BORDER_DARK}; "
                f"border-radius: {T.R_S}px; padding: 1px {T.SP_S}px;"
            )
            layout.addWidget(label)
        layout.addStretch()


class RunFoldWidget(QFrame):
    run_fold_toggled = pyqtSignal(str, bool)
    auto_fold_delay_ms = 3000

    def __init__(self, run: Run, registry: RunRegistry,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._run = run
        self._registry = registry
        self._step_widgets: Dict[str, _StepWidget] = {}
        self._auto_fold_timer: Optional[QTimer] = None
        self._init_ui(run)

    def _init_ui(self, run: Run):
        T = Lemon
        self.setObjectName("runFoldWidget")
        self.setStyleSheet(
            f"QFrame#runFoldWidget {{ background: transparent; border: none; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, T.SP_S, 0, T.SP_S)
        layout.setSpacing(0)

        self._summary_bar = _RunSummaryBar(run, self)
        self._summary_bar.fold_toggled.connect(self._on_fold_toggle)
        layout.addWidget(self._summary_bar)

        self._detail_container = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_container)
        self._detail_layout.setContentsMargins(0, T.SP_XS, 0, 0)
        self._detail_layout.setSpacing(T.SP_XS)

        for step in run.steps:
            sw = _StepWidget(step, run.run_id, self._registry, self._detail_container)
            self._step_widgets[step.step_id] = sw
            self._detail_layout.addWidget(sw)

        if run.artifacts:
            art_row = _ArtifactsRow(run.artifacts, self._detail_container)
            self._detail_layout.addWidget(art_row)

        layout.addWidget(self._detail_container)
        self._detail_container.setVisible(run.is_expanded)

    def _on_fold_toggle(self, run_id: str, expanded: bool):
        self._detail_container.setVisible(expanded)
        self._run.is_expanded = expanded
        self.run_fold_toggled.emit(run_id, expanded)

    def update_run(self, run: Run) -> None:
        self._run = run
        self._summary_bar.deleteLater()
        new_bar = _RunSummaryBar(run, self)
        new_bar.fold_toggled.connect(self._on_fold_toggle)
        new_bar.set_expanded(run.is_expanded)
        layout = self.layout()
        layout.insertWidget(0, new_bar)
        self._summary_bar = new_bar
        self._detail_container.setVisible(run.is_expanded)

        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            if not run.is_expanded and not self._auto_fold_timer:
                pass
            elif run.is_expanded and not self._auto_fold_timer:
                self._schedule_auto_fold()

    def _schedule_auto_fold(self) -> None:
        if self._auto_fold_timer:
            self._auto_fold_timer.stop()
        self._auto_fold_timer = QTimer(self)
        self._auto_fold_timer.setSingleShot(True)
        self._auto_fold_timer.timeout.connect(self._auto_fold)
        self._auto_fold_timer.start(self.auto_fold_delay_ms)

    def _auto_fold(self) -> None:
        if self._run.is_expanded:
            self._run.is_expanded = False
            self._detail_container.setVisible(False)
            self._summary_bar.set_expanded(False)
            self.run_fold_toggled.emit(self._run.run_id, False)

    def add_step(self, step: Step) -> None:
        sw = _StepWidget(step, self._run.run_id, self._registry, self._detail_container)
        self._step_widgets[step.step_id] = sw
        self._detail_layout.addWidget(sw)
        if not self._run.is_expanded:
            self._run.is_expanded = True
            self._detail_container.setVisible(True)
            self._summary_bar.set_expanded(True)

    def update_tool_call(self, tc: ToolCall) -> None:
        sw = self._step_widgets.get(tc.step_id)
        if sw:
            sw.update_tool_call(tc)
