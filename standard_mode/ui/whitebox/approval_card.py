# -*- coding: utf-8 -*-
"""
ApprovalCard — 审批卡片组件
============================
risk_level 三档颜色:
  low:    绿色边框 + "低风险"
  medium: 橙色边框 + "中风险"
  high:   红色边框 + "高风险"
倒计时: 自动过期时间显示
操作按钮: 批准 / 拒绝
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget, QFrame,
)

from ui.design.tokens import Lemon
from ui.whitebox.state_model import Approval, ApprovalStatus


_RISK_STYLES = {
    "low": {
        "border": Lemon.SUCCESS,
        "bg": Lemon.SUCCESS_BG_DARK,
        "label": "低风险",
        "label_color": Lemon.SUCCESS,
    },
    "medium": {
        "border": Lemon.ACCENT_ORANGE,
        "bg": Lemon.WARNING_BG_DARK,
        "label": "中风险",
        "label_color": Lemon.ACCENT_ORANGE,
    },
    "high": {
        "border": Lemon.ERROR,
        "bg": Lemon.ERROR_BG_DARK,
        "label": "高风险",
        "label_color": Lemon.ERROR,
    },
}


class ApprovalCard(QFrame):
    approved = pyqtSignal(str)
    denied = pyqtSignal(str)

    def __init__(self, approval: Approval, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._approval = approval
        self._timer: Optional[QTimer] = None
        self._init_ui(approval)

    def _init_ui(self, ap: Approval):
        T = Lemon
        risk = ap.risk_level or "medium"
        risk_cfg = _RISK_STYLES.get(risk, _RISK_STYLES["medium"])
        self.setObjectName("approvalCard")
        self.setStyleSheet(
            f"QFrame#approvalCard {{ background: {risk_cfg['bg']}; "
            f"border: 1px solid {risk_cfg['border']}; "
            f"border-left: 4px solid {risk_cfg['border']}; "
            f"border-radius: {T.R_M}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(T.SP_XS)

        row1 = QHBoxLayout()
        row1.setSpacing(T.SP_S)

        risk_label = QLabel(risk_cfg["label"])
        risk_label.setStyleSheet(
            f"color: {risk_cfg['label_color']}; font-size: {T.FS_CAPTION}px; "
            f"font-weight: bold; font-family: '{T.FONT}'; "
            f"background: transparent; border: none;"
        )
        row1.addWidget(risk_label)

        tool_label = QLabel(f"[{ap.tool_name}]")
        tool_label.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_SUB}px; "
            f"font-weight: bold; font-family: '{T.FONT}'; "
            f"background: transparent; border: none;"
        )
        row1.addWidget(tool_label)
        row1.addStretch()

        self._countdown_label = QLabel("")
        self._countdown_label.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        row1.addWidget(self._countdown_label)
        layout.addLayout(row1)

        if ap.args_preview:
            preview = QLabel(ap.args_preview[:120])
            preview.setWordWrap(True)
            preview.setStyleSheet(
                f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            layout.addWidget(preview)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(T.SP_S)
        btn_row.addStretch()

        deny_btn = QPushButton("拒绝")
        deny_btn.setObjectName("denyBtn")
        deny_btn.setCursor(Qt.PointingHandCursor)
        deny_btn.setFixedHeight(28)
        deny_btn.setStyleSheet(
            f"QPushButton#denyBtn {{ background: {T.ERROR_BG_DARK}; "
            f"color: {T.ERROR}; border: 1px solid {T.ERROR_BORDER_DARK}; "
            f"border-radius: {T.R_S}px; padding: 0 {T.SP_M}px; "
            f"font-family: '{T.FONT}'; font-size: {T.FS_CAPTION}px; }}"
            f"QPushButton#denyBtn:hover {{ background: {T.ERROR}; color: white; }}"
        )
        deny_btn.clicked.connect(lambda: self._on_decide(False))
        btn_row.addWidget(deny_btn)

        approve_btn = QPushButton("批准")
        approve_btn.setObjectName("approveBtn")
        approve_btn.setCursor(Qt.PointingHandCursor)
        approve_btn.setFixedHeight(28)
        approve_btn.setStyleSheet(
            f"QPushButton#approveBtn {{ background: {T.SUCCESS_BG_DARK}; "
            f"color: {T.SUCCESS}; border: 1px solid {T.SUCCESS_BORDER_DARK}; "
            f"border-radius: {T.R_S}px; padding: 0 {T.SP_M}px; "
            f"font-family: '{T.FONT}'; font-size: {T.FS_CAPTION}px; }}"
            f"QPushButton#approveBtn:hover {{ background: {T.SUCCESS}; color: white; }}"
        )
        approve_btn.clicked.connect(lambda: self._on_decide(True))
        btn_row.addWidget(approve_btn)

        layout.addLayout(btn_row)

        if ap.status == ApprovalStatus.PENDING and ap.expires_at > 0:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._update_countdown)
            self._timer.start(1000)
            self._update_countdown()

        if ap.status != ApprovalStatus.PENDING:
            self._set_decided_state(ap.status)

    def _on_decide(self, approved: bool):
        if approved:
            self.approved.emit(self._approval.approval_id)
        else:
            self.denied.emit(self._approval.approval_id)
        self._set_decided_state(
            ApprovalStatus.GRANTED if approved else ApprovalStatus.DENIED
        )

    def _set_decided_state(self, status: ApprovalStatus):
        if self._timer:
            self._timer.stop()
            self._timer = None
        if status == ApprovalStatus.GRANTED:
            self._countdown_label.setText("已批准")
            self._countdown_label.setStyleSheet(
                f"color: {Lemon.SUCCESS}; font-size: {Lemon.FS_CAPTION}px; "
                f"font-family: '{Lemon.FONT}'; background: transparent; border: none;"
            )
        elif status == ApprovalStatus.DENIED:
            self._countdown_label.setText("已拒绝")
            self._countdown_label.setStyleSheet(
                f"color: {Lemon.ERROR}; font-size: {Lemon.FS_CAPTION}px; "
                f"font-family: '{Lemon.FONT}'; background: transparent; border: none;"
            )
        elif status == ApprovalStatus.EXPIRED:
            self._countdown_label.setText("已过期")
            self._countdown_label.setStyleSheet(
                f"color: {Lemon.TEXT_MUTED}; font-size: {Lemon.FS_CAPTION}px; "
                f"font-family: '{Lemon.FONT}'; background: transparent; border: none;"
            )

    def _update_countdown(self):
        if self._approval.expires_at <= 0:
            return
        remaining = self._approval.expires_at - time.time()
        if remaining <= 0:
            self._countdown_label.setText("已过期")
            if self._timer:
                self._timer.stop()
            return
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        self._countdown_label.setText(f"{mins}:{secs:02d}")

    def cleanup(self) -> None:
        if self._timer:
            self._timer.stop()
