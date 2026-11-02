# -*- coding: utf-8 -*-
"""
v3.0 Module C — 混合工作区
========================
三栏布局整合 Agent 面板 + 任务流 + Agent 通讯。
左栏: Agent 集群卡片 (HybridAgentPanel)
中栏: 任务流 DAG/时间线 (TaskFlowPanel)
右栏: Agent 通讯消息流 (AgentChatPanel)
顶部: 控制栏 (启动/暂停/模式切换)
"""

import os
import sys
from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QFrame, QSizePolicy, QComboBox, QToolButton
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QFont

from ui.design.tokens import Lemon
from ui.theme import (
    BG_DARK, BG_PANEL, BG_SURFACE, BG_SURFACE_HOVER,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    LEMON_ORANGE, LEMON_ORANGE_LIGHT, SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR,
    BORDER_RADIUS, FONT_FAMILY, BORDER_DEFAULT,
    SVG_ICONS, svg_to_qicon
)

from ui.hybrid_agent_panel import HybridAgentPanel, ROLE_COLORS, STATE_LABELS
from ui.task_flow_panel import TaskFlowPanel
from ui.agent_chat_panel import AgentChatPanel


class ControlBar(QFrame):
    start_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        icon = QLabel()
        icon.setFixedSize(18, 18)
        db_svg = SVG_ICONS.get("database", "")
        if db_svg:
            icon.setStyleSheet(f"color: {LEMON_ORANGE};")
            icon.setText(db_svg.replace('width="16" height="16"', 'width="18" height="18"'))
        layout.addWidget(icon)

        title = QLabel("Hybrid Mode")
        title.setFont(QFont(FONT_FAMILY, 13, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE}; border: none;")
        layout.addWidget(title)

        self._status_label = QLabel("STOPPED")
        self._status_label.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
        self._status_label.setStyleSheet(f"""
            color: {ERROR_COLOR};
            background: {ERROR_COLOR}22;
            border-radius: 3px;
            padding: 2px 8px;
        """)
        layout.addWidget(self._status_label)

        layout.addStretch()

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["sequential", "parallel", "hierarchical"])
        self._mode_combo.setFixedWidth(110)
        self._mode_combo.setFixedHeight(26)
        self._mode_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_SURFACE};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {BORDER_RADIUS};
                color: {TEXT_PRIMARY};
                padding: 2px 8px;
                font-family: {FONT_FAMILY};
                font-size: 10px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                selection-background-color: {LEMON_ORANGE}33;
            }}
        """)
        self._mode_combo.currentTextChanged.connect(self.mode_changed.emit)
        layout.addWidget(self._mode_combo)

        self._start_btn = QPushButton("Start")
        self._start_btn.setFixedSize(64, 28)
        self._start_btn.setStyleSheet(f"""
            QPushButton {{
                background: {SUCCESS_COLOR};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS};
                font-family: {FONT_FAMILY};
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #5cbf60; }}
        """)
        self._start_btn.clicked.connect(self.start_requested.emit)
        layout.addWidget(self._start_btn)

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setFixedSize(64, 28)
        self._pause_btn.setStyleSheet(f"""
            QPushButton {{
                background: {WARNING_COLOR};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS};
                font-family: {FONT_FAMILY};
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #ffc040; }}
        """)
        self._pause_btn.clicked.connect(self.pause_requested.emit)
        layout.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setFixedSize(64, 28)
        self._stop_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ERROR_COLOR};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS};
                font-family: {FONT_FAMILY};
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #ff6b6b; }}
        """)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        layout.addWidget(self._stop_btn)

        self.setStyleSheet(f"""
            ControlBar {{
                background: {BG_PANEL};
                border-bottom: 1px solid {BORDER_DEFAULT};
            }}
        """)

    def set_status(self, status: str):
        status_map = {
            "stopped": (ERROR_COLOR, "STOPPED"),
            "running": (SUCCESS_COLOR, "RUNNING"),
            "paused": (WARNING_COLOR, "PAUSED"),
            "error": (ERROR_COLOR, "ERROR"),
        }
        color, label = status_map.get(status, (TEXT_TERTIARY, status.upper()))
        self._status_label.setText(label)
        self._status_label.setStyleSheet(f"""
            color: {color};
            background: {color}22;
            border-radius: 3px;
            padding: 2px 8px;
        """)


class HybridWorkspace(QWidget):
    start_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)
    agent_action = pyqtSignal(str, str)
    task_clicked = pyqtSignal(str)
    message_sent = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._control_bar = ControlBar()
        self._control_bar.start_requested.connect(self.start_requested.emit)
        self._control_bar.pause_requested.connect(self.pause_requested.emit)
        self._control_bar.stop_requested.connect(self.stop_requested.emit)
        self._control_bar.mode_changed.connect(self.mode_changed.emit)
        layout.addWidget(self._control_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {BORDER_DEFAULT};
            }}
        """)

        self._agent_panel = HybridAgentPanel()
        self._agent_panel.agent_action.connect(self.agent_action.emit)
        splitter.addWidget(self._agent_panel)

        self._task_panel = TaskFlowPanel()
        self._task_panel.task_clicked.connect(self.task_clicked.emit)
        splitter.addWidget(self._task_panel)

        self._chat_panel = AgentChatPanel()
        self._chat_panel.message_sent.connect(self.message_sent.emit)
        splitter.addWidget(self._chat_panel)

        splitter.setSizes([280, 400, 320])

        layout.addWidget(splitter, 1)

        self.setStyleSheet(f"""
            HybridWorkspace {{
                background: {BG_DARK};
            }}
        """)

    def set_status(self, status: str):
        self._control_bar.set_status(status)

    def add_agent(self, agent_id: str, role: str = "idle", state: str = "idle",
                  task: str = "", cpu: float = 0.0, mem: float = 0.0):
        self._agent_panel.add_agent(agent_id, role, state, task, cpu, mem)

    def remove_agent(self, agent_id: str):
        self._agent_panel.remove_agent(agent_id)

    def update_agent(self, agent_id: str, **kwargs):
        self._agent_panel.update_agent(agent_id, **kwargs)

    def add_task(self, task_id: str, description: str = "",
                 status: str = "pending", assigned_role: str = "",
                 dependencies: Optional[List[str]] = None):
        self._task_panel.add_task(task_id, description, status, assigned_role, dependencies)

    def update_task_status(self, task_id: str, status: str):
        self._task_panel.update_task_status(task_id, status)

    def clear_tasks(self):
        self._task_panel.clear_tasks()

    def add_message(self, sender_id: str, sender_role: str = "",
                    message_type: str = "direct", content: str = "",
                    timestamp: str = "", priority: str = "normal",
                    is_self: bool = False):
        self._chat_panel.add_message(sender_id, sender_role, message_type,
                                     content, timestamp, priority, is_self)

    def clear_messages(self):
        self._chat_panel.clear_messages()
