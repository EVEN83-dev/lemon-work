# -*- coding: utf-8 -*-
"""
v3.0 Module C — 混合模式 Agent 卡片面板
========================================
展示多 Agent 卡片网格 + Agent 详情侧边栏。
卡片显示：角色图标、Agent ID、状态灯、当前任务、资源占用。
详情侧边栏：完整状态、上下文快照、操作按钮。
"""

import os
import sys
from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QSizePolicy, QToolButton,
    QProgressBar
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize, pyqtProperty, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QPainter, QColor, QPen

from ui.design.tokens import Lemon
from ui.theme import (
    BG_DARK, BG_PANEL, BG_SURFACE, BG_SURFACE_HOVER,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    LEMON_ORANGE, SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR,
    BORDER_RADIUS, FONT_FAMILY, BORDER_DEFAULT,
    SVG_ICONS, svg_to_qicon
)

ROLE_COLORS = {
    "coordinator": "#448AFF",
    "researcher": "#69F0AE",
    "coder": "#FFD600",
    "reviewer": "#B388FF",
    "tester": "#FF9100",
    "documenter": "#FF80AB",
}

ROLE_ICONS = {
    "coordinator": "layers",
    "researcher": "search",
    "coder": "code",
    "reviewer": "eye",
    "tester": "shield-check",
    "documenter": "file-text",
}

STATE_COLORS = {
    "creating": WARNING_COLOR,
    "idle": TEXT_TERTIARY,
    "working": "#448AFF",
    "waiting_input": LEMON_ORANGE,
    "paused": WARNING_COLOR,
    "terminated": ERROR_COLOR,
}

STATE_LABELS = {
    "creating": "创建中",
    "idle": "空闲",
    "working": "工作中",
    "waiting_input": "等待输入",
    "paused": "已暂停",
    "terminated": "已终止",
}


class StatusDot(QWidget):
    def __init__(self, color: str = TEXT_TERTIARY, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(8, 8)

    def set_color(self, color: str):
        self._color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(self._color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, 8, 8)
        p.end()


class AgentCard(QFrame):
    clicked = pyqtSignal(str)
    double_clicked = pyqtSignal(str)

    def __init__(self, agent_id: str, role: str = "idle", state: str = "idle",
                 task: str = "", cpu: float = 0.0, mem: float = 0.0, parent=None):
        super().__init__(parent)
        self.agent_id = agent_id
        self._role = role
        self._state = state
        self._selected = False
        self.setFixedHeight(88)
        self.setCursor(Qt.PointingHandCursor)
        self._build_ui(role, state, task, cpu, mem)

    def _build_ui(self, role: str, state: str, task: str, cpu: float, mem: float):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)

        role_color = ROLE_COLORS.get(role, TEXT_TERTIARY)
        role_icon_name = ROLE_ICONS.get(role, "bot")
        icon_svg = SVG_ICONS.get(role_icon_name, SVG_ICONS.get("bot", ""))
        icon_label = QLabel()
        icon_label.setFixedSize(20, 20)
        icon_label.setStyleSheet(f"color: {role_color};")
        icon_label.setText(icon_svg.replace('width="16" height="16"', 'width="20" height="20"'))
        header.addWidget(icon_label)

        name_label = QLabel(self.agent_id)
        name_label.setFont(QFont(FONT_FAMILY, 11, QFont.Bold))
        name_label.setStyleSheet(f"color: {TEXT_PRIMARY}; border: none;")
        header.addWidget(name_label)

        header.addStretch()

        self._status_dot = StatusDot(STATE_COLORS.get(state, TEXT_TERTIARY))
        header.addWidget(self._status_dot)

        state_label = QLabel(STATE_LABELS.get(state, state))
        state_label.setFont(QFont(FONT_FAMILY, 9))
        state_label.setStyleSheet(f"color: {STATE_COLORS.get(state, TEXT_TERTIARY)}; border: none;")
        header.addWidget(state_label)

        layout.addLayout(header)

        if task:
            task_label = QLabel(task[:40])
            task_label.setFont(QFont(FONT_FAMILY, 9))
            task_label.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none;")
            task_label.setWordWrap(False)
            layout.addWidget(task_label)
        else:
            empty = QLabel("无任务")
            empty.setFont(QFont(FONT_FAMILY, 9))
            empty.setStyleSheet(f"color: {TEXT_TERTIARY}; border: none;")
            layout.addWidget(empty)

        res_layout = QHBoxLayout()
        res_layout.setSpacing(8)

        cpu_label = QLabel(f"CPU {cpu:.0f}%")
        cpu_label.setFont(QFont(FONT_FAMILY, 8))
        cpu_color = ERROR_COLOR if cpu > 80 else WARNING_COLOR if cpu > 50 else TEXT_TERTIARY
        cpu_label.setStyleSheet(f"color: {cpu_color}; border: none;")
        res_layout.addWidget(cpu_label)

        mem_label = QLabel(f"MEM {mem:.0f}MB")
        mem_label.setFont(QFont(FONT_FAMILY, 8))
        mem_color = ERROR_COLOR if mem > 512 else WARNING_COLOR if mem > 256 else TEXT_TERTIARY
        mem_label.setStyleSheet(f"color: {mem_color}; border: none;")
        res_layout.addWidget(mem_label)

        res_layout.addStretch()
        layout.addLayout(res_layout)

        self._apply_style(False)

    def _apply_style(self, selected: bool):
        border = LEMON_ORANGE if selected else BORDER_DEFAULT
        bg = BG_SURFACE_HOVER if selected else BG_SURFACE
        self.setStyleSheet(f"""
            AgentCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {BORDER_RADIUS};
            }}
            AgentCard:hover {{
                border: 1px solid {LEMON_ORANGE};
            }}
        """)

    def set_selected(self, sel: bool):
        self._selected = sel
        self._apply_style(sel)

    def update_state(self, state: str, task: str = "", cpu: float = 0.0, mem: float = 0.0):
        self._state = state

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.agent_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self.agent_id)
        super().mouseDoubleClickEvent(event)


class AgentDetailPanel(QFrame):
    action_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._agent_id = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Agent 详情")
        title.setFont(QFont(FONT_FAMILY, 13, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE}; border: none;")
        layout.addWidget(title)

        self._name_label = QLabel("选择一个 Agent")
        self._name_label.setFont(QFont(FONT_FAMILY, 11, QFont.Bold))
        self._name_label.setStyleSheet(f"color: {TEXT_PRIMARY}; border: none;")
        layout.addWidget(self._name_label)

        self._role_label = QLabel("")
        self._role_label.setFont(QFont(FONT_FAMILY, 10))
        self._role_label.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none;")
        layout.addWidget(self._role_label)

        self._state_label = QLabel("")
        self._state_label.setFont(QFont(FONT_FAMILY, 10))
        self._state_label.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none;")
        layout.addWidget(self._state_label)

        self._task_label = QLabel("")
        self._task_label.setFont(QFont(FONT_FAMILY, 10))
        self._task_label.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none;")
        self._task_label.setWordWrap(True)
        layout.addWidget(self._task_label)

        self._resource_label = QLabel("")
        self._resource_label.setFont(QFont(FONT_FAMILY, 9))
        self._resource_label.setStyleSheet(f"color: {TEXT_TERTIARY}; border: none;")
        layout.addWidget(self._resource_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {BORDER_DEFAULT};")
        layout.addWidget(sep)

        self._context_text = QLabel("上下文快照为空")
        self._context_text.setFont(QFont(FONT_FAMILY, 9))
        self._context_text.setStyleSheet(f"color: {TEXT_TERTIARY}; border: none;")
        self._context_text.setWordWrap(True)
        layout.addWidget(self._context_text)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setFixedHeight(28)
        self._pause_btn.setStyleSheet(f"""
            QPushButton {{
                background: {WARNING_COLOR};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS};
                padding: 4px 12px;
                font-family: {FONT_FAMILY};
                font-size: 11px;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
        """)
        self._pause_btn.clicked.connect(lambda: self.action_requested.emit(self._agent_id, "pause"))
        btn_layout.addWidget(self._pause_btn)

        self._resume_btn = QPushButton("恢复")
        self._resume_btn.setFixedHeight(28)
        self._resume_btn.setStyleSheet(f"""
            QPushButton {{
                background: {SUCCESS_COLOR};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS};
                padding: 4px 12px;
                font-family: {FONT_FAMILY};
                font-size: 11px;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
        """)
        self._resume_btn.clicked.connect(lambda: self.action_requested.emit(self._agent_id, "resume"))
        btn_layout.addWidget(self._resume_btn)

        self._terminate_btn = QPushButton("终止")
        self._terminate_btn.setFixedHeight(28)
        self._terminate_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ERROR_COLOR};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS};
                padding: 4px 12px;
                font-family: {FONT_FAMILY};
                font-size: 11px;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
        """)
        self._terminate_btn.clicked.connect(lambda: self.action_requested.emit(self._agent_id, "terminate"))
        btn_layout.addWidget(self._terminate_btn)

        layout.addLayout(btn_layout)

        self.setStyleSheet(f"""
            AgentDetailPanel {{
                background: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {BORDER_RADIUS};
            }}
        """)

    def set_agent(self, agent_id: str, role: str = "", state: str = "",
                  task: str = "", cpu: float = 0.0, mem: float = 0.0,
                  context_snapshot: str = ""):
        self._agent_id = agent_id
        self._name_label.setText(agent_id)
        role_color = ROLE_COLORS.get(role, TEXT_SECONDARY)
        self._role_label.setText(f"角色: {role}")
        self._role_label.setStyleSheet(f"color: {role_color}; border: none;")
        self._state_label.setText(f"状态: {STATE_LABELS.get(state, state)}")
        self._state_label.setStyleSheet(f"color: {STATE_COLORS.get(state, TEXT_SECONDARY)}; border: none;")
        self._task_label.setText(f"任务: {task}" if task else "无任务")
        self._resource_label.setText(f"CPU: {cpu:.1f}% | MEM: {mem:.0f}MB")
        self._context_text.setText(context_snapshot if context_snapshot else "上下文快照为空")


class HybridAgentPanel(QWidget):
    agent_selected = pyqtSignal(str)
    agent_action = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: Dict[str, AgentCard] = {}
        self._selected_id = ""
        self._build_ui()

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        card_area = QWidget()
        card_layout = QVBoxLayout(card_area)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel("Agent 集群")
        title.setFont(QFont(FONT_FAMILY, 14, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE}; border: none;")
        header.addWidget(title)

        self._count_label = QLabel("(0)")
        self._count_label.setFont(QFont(FONT_FAMILY, 11))
        self._count_label.setStyleSheet(f"color: {TEXT_TERTIARY}; border: none;")
        header.addWidget(self._count_label)

        header.addStretch()

        add_btn = QToolButton()
        add_btn.setText(SVG_ICONS.get("plus", "+"))
        add_btn.setFixedSize(28, 28)
        add_btn.setStyleSheet(f"""
            QToolButton {{
                background: {BG_SURFACE};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {BORDER_RADIUS};
                color: {LEMON_ORANGE};
            }}
            QToolButton:hover {{
                border: 1px solid {LEMON_ORANGE};
            }}
        """)
        header.addWidget(add_btn)

        card_layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {BG_DARK};
                border: none;
            }}
            QScrollBar:vertical {{
                background: {BG_DARK};
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: #444;
                border-radius: 3px;
            }}
        """)

        self._card_container = QWidget()
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(4)
        self._card_layout.addStretch()

        scroll.setWidget(self._card_container)
        card_layout.addWidget(scroll, 1)

        main_layout.addWidget(card_area, 3)

        self._detail = AgentDetailPanel()
        self._detail.setFixedWidth(240)
        self._detail.action_requested.connect(self.agent_action.emit)
        main_layout.addWidget(self._detail, 1)

    def add_agent(self, agent_id: str, role: str = "idle", state: str = "idle",
                  task: str = "", cpu: float = 0.0, mem: float = 0.0):
        if agent_id in self._cards:
            return
        card = AgentCard(agent_id, role, state, task, cpu, mem)
        card.clicked.connect(self._on_card_clicked)
        card.double_clicked.connect(self._on_card_double_clicked)
        idx = self._card_layout.count() - 1
        self._card_layout.insertWidget(idx, card)
        self._cards[agent_id] = card
        self._update_count()

    def remove_agent(self, agent_id: str):
        card = self._cards.pop(agent_id, None)
        if card:
            self._card_layout.removeWidget(card)
            card.deleteLater()
            if self._selected_id == agent_id:
                self._selected_id = ""
            self._update_count()

    def update_agent(self, agent_id: str, **kwargs):
        card = self._cards.get(agent_id)
        if not card:
            return
        card.update_state(
            kwargs.get("state", card._state),
            kwargs.get("task", ""),
            kwargs.get("cpu", 0.0),
            kwargs.get("mem", 0.0),
        )
        if self._selected_id == agent_id:
            self._detail.set_agent(agent_id, **kwargs)

    def _on_card_clicked(self, agent_id: str):
        if self._selected_id and self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(False)
        self._selected_id = agent_id
        self._cards[agent_id].set_selected(True)
        card = self._cards[agent_id]
        self._detail.set_agent(agent_id, role=card._role, state=card._state)
        self.agent_selected.emit(agent_id)

    def _on_card_double_clicked(self, agent_id: str):
        self._on_card_clicked(agent_id)

    def _update_count(self):
        self._count_label.setText(f"({len(self._cards)})")

    def get_agent_ids(self) -> List[str]:
        return list(self._cards.keys())
