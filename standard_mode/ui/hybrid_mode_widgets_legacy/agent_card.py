# -*- coding: utf-8 -*-
"""
v6.0-H A-1 — Agent 卡片组件
===========================
单个 Agent 的可视化卡片，含角色图标、状态灯动画、任务描述、进度条、操作按钮。
"""

from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QProgressBar, QTextEdit
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush

from ui.design.tokens import Lemon
from ui.theme import SVG_ICONS

_ROLE_COLORS = {
    "coordinator": Lemon.ACCENT_BLUE,
    "researcher": Lemon.ACCENT_GREEN,
    "coder": Lemon.BRAND_ORANGE,
    "reviewer": Lemon.ACCENT_PURPLE,
    "tester": Lemon.ACCENT_ORANGE,
    "documenter": Lemon.ACCENT_PINK,
}

_ROLE_ICONS = {
    "coordinator": "layers",
    "researcher": "search",
    "coder": "code",
    "reviewer": "eye",
    "tester": "shield-check",
    "documenter": "file-text",
}

_STATE_COLORS = {
    "working": Lemon.ACCENT_BLUE,
    "waiting_input": Lemon.BRAND_ORANGE,
    "idle": Lemon.SECONDARY,
    "paused": Lemon.ACCENT_ORANGE,
    "terminated": Lemon.ERROR,
    "error": Lemon.ERROR,
    "creating": Lemon.ACCENT_ORANGE,
}

_STATE_LABELS = {
    "working": "工作中",
    "waiting_input": "等待输入",
    "idle": "空闲",
    "paused": "已暂停",
    "terminated": "已终止",
    "error": "错误",
    "creating": "创建中",
}


class StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = Lemon.SECONDARY
        self._opacity = 1.0
        self._state = "idle"
        self.setFixedSize(10, 10)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._phase = 0

    def set_state(self, state: str):
        self._state = state
        self._color = _STATE_COLORS.get(state, Lemon.SECONDARY)
        if state == "working":
            self._timer.start(500)
        elif state == "waiting_input":
            self._timer.start(1000)
        else:
            self._timer.stop()
            self._opacity = 1.0
        self.update()

    def _tick(self):
        if self._state == "working":
            self._phase = (self._phase + 1) % 2
            self._opacity = 1.0 if self._phase == 0 else 0.3
        elif self._state == "waiting_input":
            self._phase = (self._phase + 1) % 20
            t = self._phase / 20.0
            self._opacity = 0.4 + 0.6 * (0.5 + 0.5 * __import__('math').sin(t * 2 * 3.14159))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self._color)
        c.setAlphaF(self._opacity)
        p.setBrush(QBrush(c))
        p.setPen(Qt.NoPen)
        p.drawEllipse(1, 1, 8, 8)
        p.end()


class AgentCard(QFrame):
    view_detail = pyqtSignal(str)
    pause_clicked = pyqtSignal(str)
    terminate_clicked = pyqtSignal(str)
    card_clicked = pyqtSignal(str)

    def __init__(self, agent_id: str, role: str = "coder",
                 name: str = "", state: str = "idle",
                 task: str = "", progress: int = 0,
                 elapsed_ms: int = 0, parent=None):
        super().__init__(parent)
        self.agent_id = agent_id
        self._role = role
        self._name = name or agent_id
        self._state = state
        self._task = task
        self._progress = progress
        self._elapsed_ms = elapsed_ms
        self._selected = False
        self.setFixedHeight(180)
        self.setMinimumWidth(220)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("agentCard")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Lemon.SP_M, Lemon.SP_S, Lemon.SP_M, Lemon.SP_S)
        layout.setSpacing(Lemon.SP_S)

        header = QHBoxLayout()
        header.setSpacing(Lemon.SP_S)

        role_color = _ROLE_COLORS.get(self._role, Lemon.SECONDARY)
        icon_name = _ROLE_ICONS.get(self._role, "bot")
        icon_svg = SVG_ICONS.get(icon_name, SVG_ICONS.get("bot", ""))
        icon_label = QLabel()
        icon_label.setFixedSize(24, 24)
        icon_label.setStyleSheet(f"color: {role_color};")
        icon_label.setText(icon_svg.replace('width="16" height="16"', 'width="24" height="24"'))
        header.addWidget(icon_label)

        name_label = QLabel(self._name)
        name_label.setFont(QFont(Lemon.FONT, Lemon.FS_SUB, QFont.Bold))
        name_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_1}; border: none;")
        name_label.setToolTip(self._name)
        header.addWidget(name_label, 1)

        self._status_dot = StatusDot()
        self._status_dot.set_state(self._state)
        header.addWidget(self._status_dot)

        state_text = _STATE_LABELS.get(self._state, self._state)
        self._state_label = QLabel(state_text)
        self._state_label.setFont(QFont(Lemon.FONT, Lemon.FS_CAPTION))
        state_color = _STATE_COLORS.get(self._state, Lemon.SECONDARY)
        self._state_label.setStyleSheet(f"color: {state_color}; border: none;")
        header.addWidget(self._state_label)

        layout.addLayout(header)

        role_badge = QLabel(self._role)
        role_badge.setFont(QFont(Lemon.FONT, Lemon.FS_CAPTION))
        role_badge.setStyleSheet(f"""
            color: {role_color};
            background: {role_color}22;
            border: 1px solid {role_color}44;
            border-radius: {Lemon.R_S}px;
            padding: 1px 6px;
        """)
        layout.addWidget(role_badge)

        self._task_label = QLabel(self._task[:80] if self._task else "无任务")
        self._task_label.setFont(QFont(Lemon.FONT, Lemon.FS_CAPTION))
        self._task_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_3}; border: none;")
        self._task_label.setWordWrap(True)
        self._task_label.setMaximumHeight(40)
        layout.addWidget(self._task_label)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(Lemon.SP_S)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(self._progress)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {Lemon.DARK_BG_3};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {role_color};
                border-radius: 3px;
            }}
        """)
        progress_row.addWidget(self._progress_bar, 1)

        self._elapsed_label = QLabel(self._format_elapsed(self._elapsed_ms))
        self._elapsed_label.setFont(QFont(Lemon.FONT, 9))
        self._elapsed_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_3}; border: none;")
        self._elapsed_label.setFixedWidth(48)
        progress_row.addWidget(self._elapsed_label)

        layout.addLayout(progress_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        detail_btn = QPushButton("查看详情")
        detail_btn.setFixedHeight(24)
        detail_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {Lemon.ACCENT_BLUE};
                border: 1px solid {Lemon.ACCENT_BLUE}44;
                border-radius: {Lemon.R_S}px;
                padding: 2px 8px;
                font-family: {Lemon.FONT};
                font-size: {Lemon.FS_CAPTION}px;
            }}
            QPushButton:hover {{
                background: {Lemon.ACCENT_BLUE}22;
            }}
        """)
        detail_btn.clicked.connect(lambda: self.view_detail.emit(self.agent_id))
        btn_row.addWidget(detail_btn)

        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setFixedHeight(24)
        self._pause_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {Lemon.ACCENT_ORANGE};
                border: 1px solid {Lemon.ACCENT_ORANGE}44;
                border-radius: {Lemon.R_S}px;
                padding: 2px 8px;
                font-family: {Lemon.FONT};
                font-size: {Lemon.FS_CAPTION}px;
            }}
            QPushButton:hover {{
                background: {Lemon.ACCENT_ORANGE}22;
            }}
        """)
        self._pause_btn.clicked.connect(lambda: self.pause_clicked.emit(self.agent_id))
        btn_row.addWidget(self._pause_btn)

        term_btn = QPushButton("终止")
        term_btn.setFixedHeight(24)
        term_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {Lemon.ERROR};
                border: 1px solid {Lemon.ERROR}44;
                border-radius: {Lemon.R_S}px;
                padding: 2px 8px;
                font-family: {Lemon.FONT};
                font-size: {Lemon.FS_CAPTION}px;
            }}
            QPushButton:hover {{
                background: {Lemon.ERROR}22;
            }}
        """)
        term_btn.clicked.connect(lambda: self.terminate_clicked.emit(self.agent_id))
        btn_row.addWidget(term_btn)

        layout.addLayout(btn_row)
        self._apply_style()

    def _apply_style(self):
        border = Lemon.BRAND_ORANGE if self._selected else Lemon.BORDER
        bg = Lemon.DARK_BG_3 if self._selected else Lemon.SURFACE
        self.setStyleSheet(f"""
            QFrame#agentCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {Lemon.R_M}px;
            }}
            QFrame#agentCard:hover {{
                border: 1px solid {Lemon.BRAND_ORANGE};
            }}
        """)

    def set_selected(self, sel: bool):
        self._selected = sel
        self._apply_style()

    def update_state(self, state: str, task: str = "",
                     progress: int = -1, elapsed_ms: int = -1):
        self._state = state
        self._status_dot.set_state(state)
        state_color = _STATE_COLORS.get(state, Lemon.SECONDARY)
        self._state_label.setText(_STATE_LABELS.get(state, state))
        self._state_label.setStyleSheet(f"color: {state_color}; border: none;")
        if task:
            self._task_label.setText(task[:80])
            self._task = task
        if progress >= 0:
            self._progress = progress
            self._progress_bar.setValue(progress)
        if elapsed_ms >= 0:
            self._elapsed_ms = elapsed_ms
            self._elapsed_label.setText(self._format_elapsed(elapsed_ms))
        if state == "paused":
            self._pause_btn.setText("恢复")
        else:
            self._pause_btn.setText("暂停")

    @staticmethod
    def _format_elapsed(ms: int) -> str:
        if ms <= 0:
            return "--"
        s = ms // 1000
        if s < 60:
            return f"{s}s"
        m = s // 60
        s = s % 60
        if m < 60:
            return f"{m}m{s}s"
        h = m // 60
        m = m % 60
        return f"{h}h{m}m"

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.card_clicked.emit(self.agent_id)
        super().mousePressEvent(event)
