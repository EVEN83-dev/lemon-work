# -*- coding: utf-8 -*-
"""
v3.0 Module C — 任务流面板
========================
DAG 可视化 + 时间线视图。
- DAG 模式：节点图 + 依赖边 + 状态着色
- 时间线模式：垂直时间线 + 任务步骤卡片
"""

import os
import sys
from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QToolButton,
    QComboBox, QTextEdit
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize, QRectF
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush, QPainterPath

from ui.design.tokens import Lemon
from ui.theme import (
    BG_DARK, BG_PANEL, BG_SURFACE, BG_SURFACE_HOVER,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    LEMON_ORANGE, SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR, INFO_COLOR,
    BORDER_RADIUS, FONT_FAMILY, BORDER_DEFAULT,
    SVG_ICONS, svg_to_qicon
)

TASK_STATUS_COLORS = {
    "pending": TEXT_TERTIARY,
    "ready": INFO_COLOR,
    "assigned": WARNING_COLOR,
    "running": "#448AFF",
    "completed": SUCCESS_COLOR,
    "failed": ERROR_COLOR,
    "cancelled": TEXT_TERTIARY,
}

TASK_STATUS_LABELS = {
    "pending": "等待",
    "ready": "就绪",
    "assigned": "已分配",
    "running": "运行中",
    "completed": "完成",
    "failed": "失败",
    "cancelled": "取消",
}

ROLE_COLORS = {
    "coordinator": "#448AFF",
    "researcher": "#69F0AE",
    "coder": "#FFD600",
    "reviewer": "#B388FF",
    "tester": "#FF9100",
    "documenter": "#FF80AB",
}


class TaskNodeWidget(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, task_id: str, description: str = "",
                 status: str = "pending", assigned_role: str = "",
                 parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self._status = status
        self._description = description
        self._role = assigned_role
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(6)

        status_color = TASK_STATUS_COLORS.get(self._status, TEXT_TERTIARY)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"""
            background: {status_color};
            border-radius: 4px;
        """)
        header.addWidget(dot)

        name = QLabel(self.task_id)
        name.setFont(QFont(FONT_FAMILY, 10, QFont.Bold))
        name.setStyleSheet(f"color: {TEXT_PRIMARY}; border: none;")
        header.addWidget(name)

        if self._role:
            role_color = ROLE_COLORS.get(self._role, TEXT_SECONDARY)
            badge = QLabel(self._role)
            badge.setFont(QFont(FONT_FAMILY, 8))
            badge.setStyleSheet(f"""
                color: {role_color};
                background: {role_color}22;
                border: 1px solid {role_color}44;
                border-radius: 3px;
                padding: 1px 4px;
            """)
            header.addWidget(badge)

        header.addStretch()

        status_label = QLabel(TASK_STATUS_LABELS.get(self._status, self._status))
        status_label.setFont(QFont(FONT_FAMILY, 8))
        status_label.setStyleSheet(f"color: {status_color}; border: none;")
        header.addWidget(status_label)

        layout.addLayout(header)

        if self._description:
            desc = QLabel(self._description[:50])
            desc.setFont(QFont(FONT_FAMILY, 9))
            desc.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none;")
            layout.addWidget(desc)

        self._apply_style()

    def _apply_style(self):
        status_color = TASK_STATUS_COLORS.get(self._status, TEXT_TERTIARY)
        bg = BG_SURFACE_HOVER if self._status == "running" else BG_SURFACE
        self.setStyleSheet(f"""
            TaskNodeWidget {{
                background: {bg};
                border-left: 3px solid {status_color};
                border-top: 1px solid {BORDER_DEFAULT};
                border-right: 1px solid {BORDER_DEFAULT};
                border-bottom: 1px solid {BORDER_DEFAULT};
                border-radius: {BORDER_RADIUS};
            }}
        """)

    def update_status(self, status: str):
        self._status = status
        self._apply_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.task_id)
        super().mousePressEvent(event)


class TimelineStep(QFrame):
    def __init__(self, task_id: str, description: str = "",
                 status: str = "pending", role: str = "",
                 duration_ms: int = 0, parent=None):
        super().__init__(parent)
        self._build_ui(task_id, description, status, role, duration_ms)

    def _build_ui(self, task_id: str, desc: str, status: str, role: str, duration_ms: int):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        timeline_col = QVBoxLayout()
        timeline_col.setSpacing(0)

        dot = QLabel()
        dot.setFixedSize(10, 10)
        status_color = TASK_STATUS_COLORS.get(status, TEXT_TERTIARY)
        dot.setStyleSheet(f"background: {status_color}; border-radius: 5px;")
        timeline_col.addWidget(dot, 0, Qt.AlignHCenter)

        line = QLabel()
        line.setFixedWidth(2)
        line.setFixedHeight(32)
        line.setStyleSheet(f"background: {BORDER_DEFAULT};")
        timeline_col.addWidget(line, 0, Qt.AlignHCenter)

        layout.addLayout(timeline_col)

        content = QVBoxLayout()
        content.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(6)

        name = QLabel(task_id)
        name.setFont(QFont(FONT_FAMILY, 10, QFont.Bold))
        name.setStyleSheet(f"color: {TEXT_PRIMARY}; border: none;")
        header.addWidget(name)

        if role:
            role_color = ROLE_COLORS.get(role, TEXT_SECONDARY)
            role_label = QLabel(role)
            role_label.setFont(QFont(FONT_FAMILY, 8))
            role_label.setStyleSheet(f"""
                color: {role_color};
                background: {role_color}22;
                border-radius: 3px;
                padding: 1px 4px;
            """)
            header.addWidget(role_label)

        header.addStretch()

        if duration_ms > 0:
            dur = QLabel(f"{duration_ms}ms")
            dur.setFont(QFont(FONT_FAMILY, 8))
            dur.setStyleSheet(f"color: {TEXT_TERTIARY}; border: none;")
            header.addWidget(dur)

        content.addLayout(header)

        if desc:
            desc_label = QLabel(desc[:60])
            desc_label.setFont(QFont(FONT_FAMILY, 9))
            desc_label.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none;")
            content.addWidget(desc_label)

        layout.addLayout(content, 1)

        self.setStyleSheet("TimelineStep { background: transparent; border: none; }")


class TaskFlowPanel(QWidget):
    task_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "dag"
        self._task_widgets: Dict[str, TaskNodeWidget] = {}
        self._timeline_widgets: List[TimelineStep] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        title = QLabel("任务流")
        title.setFont(QFont(FONT_FAMILY, 14, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE}; border: none;")
        toolbar.addWidget(title)

        toolbar.addStretch()

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["DAG", "时间线"])
        self._mode_combo.setFixedWidth(90)
        self._mode_combo.setFixedHeight(26)
        self._mode_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_SURFACE};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {BORDER_RADIUS};
                color: {TEXT_PRIMARY};
                padding: 2px 8px;
                font-family: {FONT_FAMILY};
                font-size: 11px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background: {BG_PANEL};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                selection-background-color: {LEMON_ORANGE}33;
            }}
        """)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self._mode_combo)

        progress_label = QLabel("0/0")
        progress_label.setFont(QFont(FONT_FAMILY, 10))
        progress_label.setStyleSheet(f"color: {TEXT_TERTIARY}; border: none;")
        self._progress_label = progress_label
        toolbar.addWidget(progress_label)

        layout.addLayout(toolbar)

        self._stack = QWidget()
        self._stack_layout = QVBoxLayout(self._stack)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)

        self._dag_scroll = QScrollArea()
        self._dag_scroll.setWidgetResizable(True)
        self._dag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._dag_scroll.setStyleSheet(f"""
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

        self._dag_container = QWidget()
        self._dag_layout = QVBoxLayout(self._dag_container)
        self._dag_layout.setContentsMargins(4, 4, 4, 4)
        self._dag_layout.setSpacing(4)
        self._dag_layout.addStretch()
        self._dag_scroll.setWidget(self._dag_container)

        self._stack_layout.addWidget(self._dag_scroll)

        self._timeline_scroll = QScrollArea()
        self._timeline_scroll.setWidgetResizable(True)
        self._timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._timeline_scroll.setStyleSheet(f"""
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

        self._timeline_container = QWidget()
        self._timeline_layout = QVBoxLayout(self._timeline_container)
        self._timeline_layout.setContentsMargins(8, 8, 8, 8)
        self._timeline_layout.setSpacing(0)
        self._timeline_layout.addStretch()
        self._timeline_scroll.setWidget(self._timeline_container)

        self._stack_layout.addWidget(self._timeline_scroll)
        self._timeline_scroll.hide()

        layout.addWidget(self._stack, 1)

    def _on_mode_changed(self, idx: int):
        self._mode = "dag" if idx == 0 else "timeline"
        if self._mode == "dag":
            self._dag_scroll.show()
            self._timeline_scroll.hide()
        else:
            self._dag_scroll.hide()
            self._timeline_scroll.show()

    def add_task(self, task_id: str, description: str = "",
                 status: str = "pending", assigned_role: str = "",
                 dependencies: Optional[List[str]] = None):
        if task_id in self._task_widgets:
            return

        node = TaskNodeWidget(task_id, description, status, assigned_role)
        node.clicked.connect(self.task_clicked.emit)
        idx = self._dag_layout.count() - 1
        self._dag_layout.insertWidget(idx, node)
        self._task_widgets[task_id] = node

        step = TimelineStep(task_id, description, status, assigned_role)
        tidx = self._timeline_layout.count() - 1
        self._timeline_layout.insertWidget(tidx, step)
        self._timeline_widgets.append(step)

        self._update_progress()

    def update_task_status(self, task_id: str, status: str):
        node = self._task_widgets.get(task_id)
        if node:
            node.update_status(status)

        idx = list(self._task_widgets.keys()).index(task_id) if task_id in self._task_widgets else -1
        if 0 <= idx < len(self._timeline_widgets):
            old = self._timeline_widgets[idx]
            self._timeline_layout.removeWidget(old)
            old.deleteLater()
            desc = node._description if node else ""
            role = node._role if node else ""
            new_step = TimelineStep(task_id, desc, status, role)
            self._timeline_layout.insertWidget(idx, new_step)
            self._timeline_widgets[idx] = new_step

        self._update_progress()

    def clear_tasks(self):
        for w in self._task_widgets.values():
            self._dag_layout.removeWidget(w)
            w.deleteLater()
        self._task_widgets.clear()

        for w in self._timeline_widgets:
            self._timeline_layout.removeWidget(w)
            w.deleteLater()
        self._timeline_widgets.clear()

        self._update_progress()

    def _update_progress(self):
        total = len(self._task_widgets)
        completed = sum(1 for w in self._task_widgets.values()
                       if w._status in ("completed", "failed", "cancelled"))
        self._progress_label.setText(f"{completed}/{total}")
