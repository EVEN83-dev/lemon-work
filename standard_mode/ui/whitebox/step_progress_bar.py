# -*- coding: utf-8 -*-
"""
StepProgressBar — 步骤进度条
============================
水平排列的步骤指示器，每步显示:
  pending:  灰色空心圆 ○
  active:   蓝色实心圆 + 脉冲动画 ●
  done:     绿色实心圆 + 对勾 ✓
  failed:   红色实心圆 + 叉 ✗
  skipped:  灰色横线 —
步间连线: 灰色横线（完成段变绿，失败段变红）
"""
from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget, QFrame,
)

from ui.design.tokens import Lemon
from ui.whitebox.state_model import Step, StepStatus


_STEP_DISPLAY = {
    StepStatus.PENDING: ("○", Lemon.TEXT_MUTED, Lemon.BORDER),
    StepStatus.ACTIVE: ("●", Lemon.STATUS_RUNNING, Lemon.STATUS_RUNNING),
    StepStatus.DONE: ("✓", Lemon.SUCCESS, Lemon.SUCCESS),
    StepStatus.FAILED: ("✗", Lemon.ERROR, Lemon.ERROR),
    StepStatus.SKIPPED: ("—", Lemon.TEXT_MUTED, Lemon.TEXT_MUTED),
}


class _StepDot(QLabel):
    step_clicked = pyqtSignal(int)

    def __init__(self, index: int, step: Step, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._index = index
        self._step = step
        char, fg, _ = _STEP_DISPLAY.get(step.status, ("○", Lemon.TEXT_MUTED, Lemon.BORDER))
        self.setText(char)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"color: {fg}; font-size: 12px; font-weight: bold; "
            f"font-family: '{Lemon.FONT}'; background: transparent; border: none;"
        )
        self.setToolTip(step.title)
        if step.status == StepStatus.ACTIVE:
            self._start_pulse()

    def _start_pulse(self):
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._anim = QPropertyAnimation(effect, b"opacity")
        self._anim.setDuration(1200)
        self._anim.setStartValue(1.0)
        self._anim.setKeyValueAt(0.5, 0.4)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.setLoopCount(-1)
        self._anim.start(QPropertyAnimation.DeleteWhenStopped)

    def mousePressEvent(self, event):
        self.step_clicked.emit(self._index)
        super().mousePressEvent(event)


class _StepConnector(QLabel):
    def __init__(self, from_status: StepStatus, to_status: StepStatus,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(2)
        self.setFixedWidth(24)
        line_color = Lemon.BORDER
        if from_status == StepStatus.DONE:
            line_color = Lemon.SUCCESS
        elif from_status == StepStatus.FAILED:
            line_color = Lemon.ERROR
        self.setStyleSheet(
            f"background: {line_color}; border: none; border-radius: 1px;"
        )


class StepProgressBar(QWidget):
    step_clicked = pyqtSignal(int)

    def __init__(self, steps: List[Step], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._steps = steps
        self._dots: List[_StepDot] = []
        self._init_ui(steps)

    def _init_ui(self, steps: List[Step]):
        T = Lemon
        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignLeft)

        for i, step in enumerate(steps):
            if i > 0:
                connector = _StepConnector(steps[i - 1].status, step.status, self)
                layout.addWidget(connector)
            dot = _StepDot(i, step, self)
            dot.step_clicked.connect(self.step_clicked.emit)
            self._dots.append(dot)
            layout.addWidget(dot)

            title = QLabel(step.title[:12])
            title.setStyleSheet(
                f"color: {T.TEXT_MUTED}; font-size: 10px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            title.setFixedWidth(60)
            layout.addWidget(title)

        layout.addStretch()

    def update_steps(self, steps: List[Step]) -> None:
        for i, step in enumerate(steps):
            if i < len(self._dots):
                self._dots[i]._step = step
                char, fg, _ = _STEP_DISPLAY.get(
                    step.status, ("○", Lemon.TEXT_MUTED, Lemon.BORDER)
                )
                self._dots[i].setText(char)
                self._dots[i].setStyleSheet(
                    f"color: {fg}; font-size: 12px; font-weight: bold; "
                    f"font-family: '{Lemon.FONT}'; background: transparent; border: none;"
                )
