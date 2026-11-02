# -*- coding: utf-8 -*-
"""
PlanPanel — 常驻可滚动计划面板
================================
从弹窗改为常驻面板，执行中各 Step 实时打勾（复用 StepStatus）。
订阅 RunRegistry.step_updated 信号做增量更新。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QScrollArea, QVBoxLayout, QHBoxLayout, QLabel,
    QWidget, QSizePolicy, QPushButton, QFrame,
)

from ui.design.tokens import Lemon
from ui.whitebox.state_model import (
    RunRegistry, Run, Step, StepStatus,
)


_STEP_DISPLAY = {
    StepStatus.PENDING: ("○", Lemon.TEXT_MUTED, Lemon.TEXT_SECONDARY),
    StepStatus.ACTIVE: ("●", Lemon.STATUS_RUNNING, Lemon.STATUS_RUNNING),
    StepStatus.DONE: ("●", Lemon.SUCCESS, Lemon.SUCCESS),
    StepStatus.FAILED: ("●", Lemon.ERROR, Lemon.ERROR),
    StepStatus.SKIPPED: ("—", Lemon.TEXT_MUTED, Lemon.TEXT_MUTED),
}


class _StepCheckRow(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, step: Step, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._step_id = step.step_id
        self._status = step.status
        self._init_ui(step)

    def _init_ui(self, step: Step):
        T = Lemon
        self.setObjectName("stepCheckRow")
        self.setStyleSheet(
            f"QFrame#stepCheckRow {{ background: transparent; border: none; "
            f"padding: {T.SP_XS}px 0; }}"
        )
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.SP_S, 2, T.SP_S, 2)
        layout.setSpacing(T.SP_S)

        icon_char, icon_color, text_color = _STEP_DISPLAY.get(
            step.status, ("?", T.TEXT_MUTED, T.TEXT_SECONDARY))

        self._icon = QLabel(icon_char)
        self._icon.setStyleSheet(
            f"color: {icon_color}; font-size: {T.FS_SUB}px; "
            f"font-weight: bold; background: transparent; border: none;"
        )
        self._icon.setFixedWidth(20)
        layout.addWidget(self._icon)

        self._title = QLabel(step.title or "(step)")
        self._title.setStyleSheet(
            f"color: {text_color}; font-size: {T.FS_BODY}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        self._title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self._title)

        tc_count = len(step.tool_calls)
        if tc_count:
            badge = QLabel(f"{tc_count}")
            badge.setStyleSheet(
                f"color: {T.TEXT_TERTIARY}; font-size: {T.FS_CAPTION}px; "
                f"background: {T.DARK_BG_4}; border-radius: 8px; "
                f"padding: 1px 6px; border: none;"
            )
            layout.addWidget(badge)

    def update_status(self, status: StepStatus) -> None:
        self._status = status
        icon_char, icon_color, text_color = _STEP_DISPLAY.get(
            status, ("?", Lemon.TEXT_MUTED, Lemon.TEXT_SECONDARY))
        self._icon.setText(icon_char)
        self._icon.setStyleSheet(
            f"color: {icon_color}; font-size: {Lemon.FS_SUB}px; "
            f"font-weight: bold; background: transparent; border: none;"
        )
        self._title.setStyleSheet(
            f"color: {text_color}; font-size: {Lemon.FS_BODY}px; "
            f"font-family: '{Lemon.FONT}'; background: transparent; border: none;"
        )

    def mousePressEvent(self, event):
        self.clicked.emit(self._step_id)
        super().mousePressEvent(event)


class PlanPanel(QScrollArea):
    step_clicked = pyqtSignal(str, str)

    def __init__(self, registry: RunRegistry, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._registry = registry
        self._run_id: str = ""
        self._step_rows: Dict[str, _StepCheckRow] = {}
        self._init_ui()

    def _init_ui(self):
        T = Lemon
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(
            f"QScrollArea {{ background: {T.SURFACE}; border: none; }}"
        )
        self._container = QWidget()
        self._container.setStyleSheet(f"background: {T.SURFACE};")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(T.SP_S, T.SP_S, T.SP_S, T.SP_S)
        self._layout.setSpacing(2)
        self._layout.setAlignment(Qt.AlignTop)
        self.setWidget(self._container)

    def bind_run(self, run_id: str) -> None:
        self._run_id = run_id
        self._rebuild()

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._step_rows.clear()
        if not self._run_id:
            return
        run = self._registry.get_run(self._run_id)
        if not run:
            return
        T = Lemon
        header = QLabel("Plan")
        header.setStyleSheet(
            f"color: {T.TEXT_TERTIARY}; font-size: {T.FS_CAPTION}px; "
            f"font-weight: 600; font-family: '{T.FONT}'; "
            f"background: transparent; border: none; "
            f"padding-bottom: {T.SP_XS}px; border-bottom: 1px solid {T.BORDER};"
        )
        self._layout.addWidget(header)
        for step in run.steps:
            row = _StepCheckRow(step)
            row.clicked.connect(self._on_step_clicked)
            self._step_rows[step.step_id] = row
            self._layout.addWidget(row)
        if not run.steps:
            empty = QLabel("No plan steps yet")
            empty.setStyleSheet(
                f"color: {T.TEXT_MUTED}; font-size: {T.FS_CAPTION}px; "
                f"background: transparent; border: none; padding: {T.SP_M}px;"
            )
            self._layout.addWidget(empty)

    def on_step_updated(self, run_id: str, step_id: str) -> None:
        if run_id != self._run_id:
            return
        row = self._step_rows.get(step_id)
        if not row:
            run = self._registry.get_run(run_id)
            if run:
                self._rebuild()
            return
        run = self._registry.get_run(run_id)
        if not run:
            return
        for step in run.steps:
            if step.step_id == step_id:
                row.update_status(step.status)
                return

    def on_run_updated(self, run_id: str) -> None:
        if run_id != self._run_id:
            return
        self._rebuild()

    def _on_step_clicked(self, step_id: str) -> None:
        self.step_clicked.emit(self._run_id, step_id)
