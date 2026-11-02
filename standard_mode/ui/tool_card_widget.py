# -*- coding: utf-8 -*-
"""Lemon Agent 工具执行卡片 — 三行视觉规范
所属窗口: LemonChatFlow  品牌组件: ToolCardWidget
令牌引用: Lemon.PRIMARY/SECONDARY/BG/SURFACE/BORDER/SUCCESS/ERROR
           Lemon.SP_*/R_*/FS_*/FONT/DUR_*/
规范: 三行布局(图标+工具名+耗时 / 参数摘要 / 结果摘要)
      状态流转: running→completed图标淡入200ms, failed左边框2px ERROR
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal,
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget, QFrame,
)

from ui.design.tokens import Lemon, AnimationLimiter
from ui.design.icons import (
    ICON_FAILED, ICON_RUNNING, ICON_SUCCESS, ICON_TIMEOUT,
    load_pixmap,
)

_STATUS_STYLE = {
    "running": {
        "icon": ICON_RUNNING,
        "stroke": Lemon.SECONDARY,
        "object_name": "toolCardRunning",
    },
    "completed": {
        "icon": ICON_SUCCESS,
        "stroke": Lemon.SUCCESS,
        "object_name": "toolCardCompleted",
    },
    "failed": {
        "icon": ICON_FAILED,
        "stroke": Lemon.ERROR,
        "object_name": "toolCardFailed",
    },
    "timeout": {
        "icon": ICON_TIMEOUT,
        "stroke": Lemon.ERROR,
        "object_name": "toolCardFailed",
    },
}


class ToolCardWidget(QFrame):
    card_clicked = pyqtSignal(str)
    card_expanded = pyqtSignal(str)

    def __init__(self, call_id: str, tool_name: str, status: str,
                 args: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.call_id = call_id
        self._tool_name = tool_name
        self._status = status
        self._args = args
        self._expanded = False
        self._start_time = time.time()
        self._init_ui(tool_name, status, args)

    def _init_ui(self, tool_name: str, status: str, args: dict):
        T = Lemon
        cfg = _STATUS_STYLE.get(status, _STATUS_STYLE["running"])
        self.setObjectName(cfg["object_name"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(T.SP_XS)

        # Row 1: 24px icon + tool name + duration
        row1 = QHBoxLayout()
        row1.setSpacing(T.SP_S)

        self._icon_label = QLabel()
        pm = load_pixmap(cfg["icon"], "card", stroke_color=cfg["stroke"])
        self._icon_label.setPixmap(pm)
        self._icon_label.setFixedSize(24, 24)
        row1.addWidget(self._icon_label)

        self._name_label = QLabel(f"执行: {tool_name}")
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
        self._duration_label.setFixedWidth(48)
        self._duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row1.addWidget(self._duration_label)

        self._expand_btn = QPushButton("...")
        self._expand_btn.setObjectName("ghostBtn")
        self._expand_btn.setCursor(Qt.PointingHandCursor)
        self._expand_btn.setFixedSize(20, 20)
        self._expand_btn.clicked.connect(self._toggle_expand)
        row1.addWidget(self._expand_btn)

        layout.addLayout(row1)

        # Row 2: args summary
        row2 = QHBoxLayout()
        row2.setSpacing(T.SP_XS)
        args_str = ", ".join(f"{k}: {str(v)[:40]}" for k, v in list(args.items())[:3])
        self._args_label = QLabel(args_str or "—")
        self._args_label.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        self._args_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row2.addWidget(self._args_label)
        layout.addLayout(row2)

        # Row 3: result summary
        row3 = QHBoxLayout()
        row3.setSpacing(T.SP_XS)
        self._result_label = QLabel("")
        self._result_label.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        self._result_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row3.addWidget(self._result_label)
        layout.addLayout(row3)

        if status == "running":
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._update_elapsed)
            self._timer.start(200)
        else:
            self._timer = None

    def update_status(self, status: str, description: str, duration_ms: int = 0):
        T = Lemon
        self._status = status
        cfg = _STATUS_STYLE.get(status, _STATUS_STYLE["running"])
        self.setObjectName(cfg["object_name"])

        pm = load_pixmap(cfg["icon"], "card", stroke_color=cfg["stroke"])
        self._icon_label.setPixmap(pm)

        if description:
            color = T.PRIMARY if status == "completed" else T.ERROR if status == "failed" else T.SECONDARY
            self._result_label.setStyleSheet(
                f"color: {color}; font-size: {T.FS_CAPTION}px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            self._result_label.setText(description[:120])

        if duration_ms > 0:
            self._duration_label.setText(f"{duration_ms / 1000:.1f}s")

        if status != "running" and self._timer:
            self._timer.stop()
            self._timer = None

        if status != "running":
            elapsed = int((time.time() - self._start_time) * 1000)
            if duration_ms <= 0:
                self._duration_label.setText(f"{elapsed / 1000:.1f}s")

        if status in ("completed", "failed", "timeout"):
            self._animate_icon_swap()

    def _animate_icon_swap(self):
        T = Lemon
        limiter = AnimationLimiter.instance()

        def _do_anim():
            effect = QGraphicsOpacityEffect(self._icon_label)
            self._icon_label.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity")
            anim.setDuration(T.DUR_NORMAL)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(limiter.unregister)
            anim.start(QPropertyAnimation.DeleteWhenStopped)

            if self._status in ("completed",):
                self._animate_bounce()

        limiter.schedule(_do_anim)

    def _animate_bounce(self):
        """v6.0-S: Running→Success缩放回弹(1.0→1.05→1.0, 250ms)。"""
        T = Lemon
        limiter = AnimationLimiter.instance()
        if not limiter.can_start():
            return
        limiter.register()

        from PyQt5.QtWidgets import QGraphicsScale
        scale = QGraphicsScale(self)
        self.setTransformOriginPoint(self.width() / 2, self.height() / 2)
        self._scale_obj = scale

        anim = QPropertyAnimation(scale, b"xScale")
        anim.setDuration(T.DUR_BOUNCE)
        anim.setStartValue(1.0)
        anim.setKeyValueAt(0.4, 1.05)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(limiter.unregister)
        anim.finished.connect(lambda: self._cleanup_scale())
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _update_elapsed(self):
        elapsed = int((time.time() - self._start_time) * 1000)
        self._duration_label.setText(f"{elapsed / 1000:.1f}s")

    def _toggle_expand(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._expand_btn.setText("^")
            self._args_label.setText(
                f"{self._args_label.text() or ''}\n{str(self._args)[:200]}"
            )
            self.card_expanded.emit(self.call_id)
        else:
            self._expand_btn.setText("...")
            args_str = ", ".join(f"{k}: {str(v)[:40]}" for k, v in list(self._args.items())[:3])
            self._args_label.setText(args_str or "—")
            self.card_expanded.emit(self.call_id)

    def _cleanup_scale(self):
        if hasattr(self, '_scale_obj'):
            self._scale_obj = None
