# -*- coding: utf-8 -*-
"""
快慢工具分级渲染
================
FastToolChip:   <200ms 的快工具，折叠为单行芯片（工具名 + 耗时）
SlowToolCard:   ≥200ms 的慢工具，保留三行卡片 + 流式预览
两者共享 ToolCall 状态对象作为数据源。
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget, QFrame,
)

from ui.design.tokens import Lemon
from ui.design.icons import ICON_RUNNING, ICON_SUCCESS, ICON_FAILED, load_pixmap
from ui.whitebox.state_model import ToolCall, ToolCallStatus


class FastToolChip(QFrame):
    collapsed_clicked = pyqtSignal(str)

    def __init__(self, tool_call: ToolCall, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.call_id = tool_call.call_id
        self._tool_name = tool_call.tool_name
        self._duration_ms = tool_call.duration_ms
        self._status = tool_call.status
        self._init_ui(tool_call)

    def _init_ui(self, tc: ToolCall):
        T = Lemon
        self.setObjectName("fastToolChip")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame#fastToolChip {{ background: {T.SURFACE}; "
            f"border: 1px solid {T.BORDER}; border-radius: {T.R_S}px; }}"
            f"QFrame#fastToolChip:hover {{ border-color: {T.BRAND_ORANGE}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.SP_S, 2, T.SP_S, 2)
        layout.setSpacing(T.SP_XS)

        status_color = self._status_color()
        dot = QLabel("●")
        dot.setStyleSheet(
            f"color: {status_color}; font-size: 8px; background: transparent; border: none;"
        )
        dot.setFixedSize(10, 10)
        layout.addWidget(dot)

        name = QLabel(tc.tool_name)
        name.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        layout.addWidget(name)

        if tc.duration_ms > 0:
            dur = QLabel(f"{tc.duration_ms}ms")
            dur.setStyleSheet(
                f"color: {T.TEXT_MUTED}; font-size: 10px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            dur.setFixedWidth(40)
            dur.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(dur)

        if tc.result_summary:
            result = QLabel(tc.result_summary[:40])
            result.setStyleSheet(
                f"color: {T.TEXT_MUTED}; font-size: 10px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            layout.addWidget(result)

    def _status_color(self) -> str:
        if self._status == ToolCallStatus.SUCCESS:
            return Lemon.SUCCESS
        if self._status == ToolCallStatus.FAILED:
            return Lemon.ERROR
        if self._status == ToolCallStatus.RUNNING:
            return Lemon.STATUS_RUNNING
        return Lemon.SECONDARY

    def update_from_model(self, tc: ToolCall) -> None:
        self._status = tc.status
        self._duration_ms = tc.duration_ms
        self.deleteLater()
        parent = self.parent()
        if parent:
            chip = FastToolChip(tc, parent)
            layout = parent.layout()
            if layout:
                idx = layout.indexOf(self)
                if idx >= 0:
                    layout.removeWidget(self)
                    layout.insertWidget(idx, chip)


class SlowToolCard(QFrame):
    card_clicked = pyqtSignal(str)
    expand_toggled = pyqtSignal(str, bool)

    def __init__(self, tool_call: ToolCall, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.call_id = tool_call.call_id
        self._tool_name = tool_call.tool_name
        self._status = tool_call.status
        self._start_time = tool_call.started_at or time.time()
        self._expanded = False
        self._init_ui(tool_call)

    def _init_ui(self, tc: ToolCall):
        T = Lemon
        status_key = self._status_key()
        border_color = self._border_color()
        self.setObjectName("slowToolCard")
        self.setStyleSheet(
            f"QFrame#slowToolCard {{ background: {T.SURFACE}; "
            f"border-left: 3px solid {border_color}; "
            f"border-top: 1px solid {T.BORDER}; border-right: 1px solid {T.BORDER}; "
            f"border-bottom: 1px solid {T.BORDER}; "
            f"border-radius: {T.R_S}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(T.SP_XS)

        row1 = QHBoxLayout()
        row1.setSpacing(T.SP_S)

        self._icon_label = QLabel()
        icon_name = self._icon_for_status()
        pm = load_pixmap(icon_name, "card", stroke_color=border_color)
        self._icon_label.setPixmap(pm)
        self._icon_label.setFixedSize(24, 24)
        row1.addWidget(self._icon_label)

        self._name_label = QLabel(f"{tc.tool_name}")
        self._name_label.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_SUB}px; font-weight: bold; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        row1.addWidget(self._name_label)
        row1.addStretch()

        self._duration_label = QLabel("")
        self._duration_label.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        self._duration_label.setFixedWidth(52)
        self._duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row1.addWidget(self._duration_label)

        self._expand_btn = QPushButton("...")
        self._expand_btn.setObjectName("ghostBtn")
        self._expand_btn.setCursor(Qt.PointingHandCursor)
        self._expand_btn.setFixedSize(20, 20)
        self._expand_btn.clicked.connect(self._toggle_expand)
        row1.addWidget(self._expand_btn)

        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(T.SP_XS)
        args_str = ", ".join(
            f"{k}: {str(v)[:40]}" for k, v in list(tc.args.items())[:3]
        )
        self._args_label = QLabel(args_str or "—")
        self._args_label.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        self._args_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row2.addWidget(self._args_label)
        layout.addLayout(row2)

        self._result_label = QLabel("")
        self._result_label.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        self._result_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if tc.result_summary:
            self._result_label.setText(tc.result_summary[:120])
        layout.addWidget(self._result_label)

        if tc.status == ToolCallStatus.RUNNING:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._update_elapsed)
            self._timer.start(200)
        else:
            self._timer = None
            if tc.duration_ms > 0:
                self._duration_label.setText(f"{tc.duration_ms / 1000:.1f}s")

    def _status_key(self) -> str:
        if self._status == ToolCallStatus.RUNNING:
            return "running"
        if self._status == ToolCallStatus.SUCCESS:
            return "completed"
        if self._status == ToolCallStatus.FAILED:
            return "failed"
        return "running"

    def _border_color(self) -> str:
        if self._status == ToolCallStatus.RUNNING:
            return Lemon.STATUS_RUNNING
        if self._status == ToolCallStatus.SUCCESS:
            return Lemon.SUCCESS
        if self._status == ToolCallStatus.FAILED:
            return Lemon.ERROR
        if self._status == ToolCallStatus.DENIED:
            return Lemon.ACCENT_ORANGE
        return Lemon.SECONDARY

    def _icon_for_status(self) -> str:
        if self._status == ToolCallStatus.RUNNING:
            return ICON_RUNNING
        if self._status == ToolCallStatus.SUCCESS:
            return ICON_SUCCESS
        if self._status in (ToolCallStatus.FAILED, ToolCallStatus.DENIED):
            return ICON_FAILED
        return ICON_RUNNING

    def update_from_model(self, tc: ToolCall) -> None:
        T = Lemon
        self._status = tc.status
        border_color = self._border_color()
        self.setStyleSheet(
            f"QFrame#slowToolCard {{ background: {T.SURFACE}; "
            f"border-left: 3px solid {border_color}; "
            f"border-top: 1px solid {T.BORDER}; border-right: 1px solid {T.BORDER}; "
            f"border-bottom: 1px solid {T.BORDER}; "
            f"border-radius: {T.R_S}px; }}"
        )
        icon_name = self._icon_for_status()
        pm = load_pixmap(icon_name, "card", stroke_color=border_color)
        self._icon_label.setPixmap(pm)
        if tc.result_summary:
            color = T.PRIMARY if tc.status == ToolCallStatus.SUCCESS else T.ERROR if tc.status == ToolCallStatus.FAILED else T.SECONDARY
            self._result_label.setStyleSheet(
                f"color: {color}; font-size: {T.FS_CAPTION}px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            self._result_label.setText(tc.result_summary[:120])
        if tc.duration_ms > 0:
            self._duration_label.setText(f"{tc.duration_ms / 1000:.1f}s")
        if tc.status != ToolCallStatus.RUNNING and self._timer:
            self._timer.stop()
            self._timer = None
        if tc.status in (ToolCallStatus.SUCCESS, ToolCallStatus.FAILED):
            self._animate_icon_swap()

    def _animate_icon_swap(self):
        T = Lemon
        effect = QGraphicsOpacityEffect(self._icon_label)
        self._icon_label.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(T.DUR_NORMAL)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _update_elapsed(self):
        elapsed = int((time.time() - self._start_time) * 1000)
        self._duration_label.setText(f"{elapsed / 1000:.1f}s")

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._expand_btn.setText("^" if self._expanded else "...")
        self.expand_toggled.emit(self.call_id, self._expanded)


def create_tool_widget(tc: ToolCall, parent: Optional[QWidget] = None) -> QWidget:
    if tc.is_fast or tc.status == ToolCallStatus.SUCCESS and tc.duration_ms < 200:
        return FastToolChip(tc, parent)
    return SlowToolCard(tc, parent)
