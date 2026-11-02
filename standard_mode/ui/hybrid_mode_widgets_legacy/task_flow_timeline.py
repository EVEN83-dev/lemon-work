# -*- coding: utf-8 -*-
"""
v6.0-H B-1 — 任务流时间线组件
==============================
双视图：依赖图（DAG）和甘特图。
依赖图：垂直时间线 + 任务节点 + 依赖箭头。
甘特图：横向条形图展示并行任务时间进度。
"""

import math
from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QComboBox, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF, QSize
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush, QPainterPath

from ui.design.tokens import Lemon

_TASK_COLORS = {
    "pending": Lemon.SECONDARY,
    "ready": Lemon.ACCENT_BLUE,
    "assigned": Lemon.ACCENT_ORANGE,
    "running": Lemon.ACCENT_BLUE,
    "completed": Lemon.SUCCESS,
    "failed": Lemon.ERROR,
    "cancelled": Lemon.DARK_TEXT_3,
    "waiting_approval": Lemon.BRAND_ORANGE,
}

_TASK_LABELS = {
    "pending": "待执行",
    "ready": "就绪",
    "assigned": "已分配",
    "running": "执行中",
    "completed": "完成",
    "failed": "失败",
    "cancelled": "取消",
    "waiting_approval": "等待审批",
}

_ROLE_COLORS = {
    "coordinator": Lemon.ACCENT_BLUE,
    "researcher": Lemon.ACCENT_GREEN,
    "coder": Lemon.BRAND_ORANGE,
    "reviewer": Lemon.ACCENT_PURPLE,
    "tester": Lemon.ACCENT_ORANGE,
    "documenter": Lemon.ACCENT_PINK,
}


class TaskNodeCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, task_id: str, description: str = "",
                 status: str = "pending", role: str = "",
                 dependencies: Optional[List[str]] = None,
                 parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self._description = description
        self._status = status
        self._role = role
        self._dependencies = dependencies or []
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("taskNode")
        self.setFixedHeight(52)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Lemon.SP_S, Lemon.SP_XS, Lemon.SP_S, Lemon.SP_XS)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(Lemon.SP_XS)

        status_color = _TASK_COLORS.get(self._status, Lemon.SECONDARY)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background: {status_color}; border-radius: 4px;")
        header.addWidget(dot)

        name = QLabel(self.task_id)
        name.setFont(QFont(Lemon.FONT, Lemon.FS_CAPTION, QFont.Bold))
        name.setStyleSheet(f"color: {Lemon.DARK_TEXT_1}; border: none;")
        header.addWidget(name)

        if self._role:
            rc = _ROLE_COLORS.get(self._role, Lemon.DARK_TEXT_2)
            badge = QLabel(self._role)
            badge.setFont(QFont(Lemon.FONT, 9))
            badge.setStyleSheet(f"""
                color: {rc}; background: {rc}22;
                border-radius: 3px; padding: 0px 3px;
            """)
            header.addWidget(badge)

        header.addStretch()

        st = _TASK_LABELS.get(self._status, self._status)
        sl = QLabel(st)
        sl.setFont(QFont(Lemon.FONT, 9))
        sl.setStyleSheet(f"color: {status_color}; border: none;")
        header.addWidget(sl)

        layout.addLayout(header)

        if self._description:
            desc = QLabel(self._description[:50])
            desc.setFont(QFont(Lemon.FONT, 9))
            desc.setStyleSheet(f"color: {Lemon.DARK_TEXT_3}; border: none;")
            layout.addWidget(desc)

        self._apply_style()

    def _apply_style(self):
        sc = _TASK_COLORS.get(self._status, Lemon.SECONDARY)
        bg = Lemon.DARK_BG_3 if self._status == "running" else Lemon.SURFACE
        self.setStyleSheet(f"""
            QFrame#taskNode {{
                background: {bg};
                border-left: 3px solid {sc};
                border-top: 1px solid {Lemon.BORDER};
                border-right: 1px solid {Lemon.BORDER};
                border-bottom: 1px solid {Lemon.BORDER};
                border-radius: {Lemon.R_S}px;
            }}
        """)

    def update_status(self, status: str):
        self._status = status
        self._apply_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.task_id)
        super().mousePressEvent(event)


class DependencyGraphView(QWidget):
    task_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes: Dict[str, TaskNodeCard] = {}
        self._edges: Dict[str, List[str]] = {}
        self._topo_order: List[str] = []
        self._build_ui()

    def _build_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(Lemon.SP_S, Lemon.SP_S, Lemon.SP_S, Lemon.SP_S)
        self._layout.setSpacing(Lemon.SP_XS)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: {Lemon.BG}; border: none; }}
            QScrollBar:vertical {{
                background: {Lemon.BG}; width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {Lemon.SCROLLBAR_THUMB}; border-radius: 3px;
            }}
        """)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(Lemon.SP_XS)
        self._container_layout.addStretch()

        self._scroll.setWidget(self._container)
        self._layout.addWidget(self._scroll, 1)

    def add_task(self, task_id: str, description: str = "",
                 status: str = "pending", role: str = "",
                 dependencies: Optional[List[str]] = None):
        if task_id in self._nodes:
            return
        node = TaskNodeCard(task_id, description, status, role, dependencies)
        node.clicked.connect(self.task_clicked.emit)
        self._nodes[task_id] = node
        self._edges[task_id] = dependencies or []
        self._rebuild_layout()

    def update_task_status(self, task_id: str, status: str):
        node = self._nodes.get(task_id)
        if node:
            node.update_status(status)

    def clear(self):
        for n in self._nodes.values():
            self._container_layout.removeWidget(n)
            n.deleteLater()
        self._nodes.clear()
        self._edges.clear()

    def _rebuild_layout(self):
        while self._container_layout.count() > 1:
            item = self._container_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        self._topo_order = self._topo_sort()
        for task_id in self._topo_order:
            node = self._nodes.get(task_id)
            if node:
                idx = self._container_layout.count() - 1
                self._container_layout.insertWidget(idx, node)

    def _topo_sort(self) -> List[str]:
        in_degree = {tid: 0 for tid in self._nodes}
        for tid, deps in self._edges.items():
            for d in deps:
                if d in in_degree:
                    in_degree[tid] += 1
        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        result = []
        while queue:
            queue.sort(key=lambda t: t)
            tid = queue.pop(0)
            result.append(tid)
            for other, deps in self._edges.items():
                if tid in deps:
                    in_degree[other] -= 1
                    if in_degree[other] == 0:
                        queue.append(other)
        for tid in self._nodes:
            if tid not in result:
                result.append(tid)
        return result


class GanttBar(QFrame):
    def __init__(self, task_id: str, status: str = "pending",
                 role: str = "", start_pct: float = 0.0,
                 width_pct: float = 0.0, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self._status = status
        self._role = role
        self._start_pct = start_pct
        self._width_pct = width_pct
        self.setFixedHeight(24)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        spacer = QWidget()
        spacer.setFixedWidth(int(self._start_pct * 600))
        layout.addWidget(spacer)

        bar = QFrame()
        color = _TASK_COLORS.get(self._status, Lemon.SECONDARY)
        bar_w = max(int(self._width_pct * 600), 8)
        bar.setFixedWidth(bar_w)
        bar.setStyleSheet(f"""
            background: {color};
            border-radius: 4px;
        """)
        layout.addWidget(bar)

        lbl = QLabel(self.task_id)
        lbl.setFont(QFont(Lemon.FONT, 9))
        lbl.setStyleSheet(f"color: {Lemon.DARK_TEXT_3}; border: none; margin-left: 4px;")
        layout.addWidget(lbl)

        layout.addStretch()
        self.setStyleSheet("GanttBar { background: transparent; border: none; }")


class GanttChartView(QWidget):
    task_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: Dict[str, dict] = {}
        self._build_ui()

    def _build_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(Lemon.SP_S, Lemon.SP_S, Lemon.SP_S, Lemon.SP_S)
        self._layout.setSpacing(2)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: {Lemon.BG}; border: none; }}
            QScrollBar:vertical {{
                background: {Lemon.BG}; width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {Lemon.SCROLLBAR_THUMB}; border-radius: 3px;
            }}
        """)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(2)
        self._container_layout.addStretch()

        self._scroll.setWidget(self._container)
        self._layout.addWidget(self._scroll, 1)

    def add_task(self, task_id: str, status: str = "pending",
                 role: str = "", start_pct: float = 0.0,
                 width_pct: float = 0.0):
        self._tasks[task_id] = {
            "status": status, "role": role,
            "start_pct": start_pct, "width_pct": width_pct,
        }
        self._rebuild()

    def update_task(self, task_id: str, status: str = "",
                    start_pct: float = -1, width_pct: float = -1):
        t = self._tasks.get(task_id)
        if not t:
            return
        if status:
            t["status"] = status
        if start_pct >= 0:
            t["start_pct"] = start_pct
        if width_pct >= 0:
            t["width_pct"] = width_pct
        self._rebuild()

    def clear(self):
        self._tasks.clear()
        self._rebuild()

    def _rebuild(self):
        while self._container_layout.count() > 1:
            item = self._container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for tid, t in self._tasks.items():
            bar = GanttBar(tid, t["status"], t["role"],
                           t["start_pct"], t["width_pct"])
            idx = self._container_layout.count() - 1
            self._container_layout.insertWidget(idx, bar)


class TaskFlowTimeline(QWidget):
    task_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(Lemon.SP_S, Lemon.SP_S, Lemon.SP_S, 0)
        toolbar.setSpacing(Lemon.SP_S)

        title = QLabel("任务流")
        title.setFont(QFont(Lemon.FONT, Lemon.FS_TITLE, QFont.Bold))
        title.setStyleSheet(f"color: {Lemon.BRAND_ORANGE}; border: none;")
        toolbar.addWidget(title)

        toolbar.addStretch()

        self._view_combo = QComboBox()
        self._view_combo.addItems(["依赖图", "甘特图"])
        self._view_combo.setFixedWidth(90)
        self._view_combo.setFixedHeight(26)
        self._view_combo.setStyleSheet(f"""
            QComboBox {{
                background: {Lemon.SURFACE};
                border: 1px solid {Lemon.BORDER};
                border-radius: {Lemon.R_S}px;
                color: {Lemon.DARK_TEXT_1};
                padding: 2px 8px;
                font-family: {Lemon.FONT};
                font-size: {Lemon.FS_CAPTION}px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {Lemon.DARK_BG_2};
                color: {Lemon.DARK_TEXT_1};
                border: 1px solid {Lemon.BORDER};
                selection-background-color: {Lemon.BRAND_ORANGE}33;
            }}
        """)
        self._view_combo.currentIndexChanged.connect(self._on_view_changed)
        toolbar.addWidget(self._view_combo)

        self._progress_label = QLabel("0/0")
        self._progress_label.setFont(QFont(Lemon.FONT, Lemon.FS_CAPTION))
        self._progress_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_3}; border: none;")
        toolbar.addWidget(self._progress_label)

        layout.addLayout(toolbar)

        self._dep_view = DependencyGraphView()
        self._dep_view.task_clicked.connect(self.task_clicked.emit)

        self._gantt_view = GanttChartView()
        self._gantt_view.hide()

        layout.addWidget(self._dep_view, 1)
        layout.addWidget(self._gantt_view, 1)

    def _on_view_changed(self, idx: int):
        if idx == 0:
            self._dep_view.show()
            self._gantt_view.hide()
        else:
            self._dep_view.hide()
            self._gantt_view.show()

    def add_task(self, task_id: str, description: str = "",
                 status: str = "pending", role: str = "",
                 dependencies: Optional[List[str]] = None,
                 start_pct: float = 0.0, width_pct: float = 0.0):
        self._dep_view.add_task(task_id, description, status, role, dependencies)
        self._gantt_view.add_task(task_id, status, role, start_pct, width_pct)
        self._update_progress()

    def update_task_status(self, task_id: str, status: str,
                           start_pct: float = -1, width_pct: float = -1):
        self._dep_view.update_task_status(task_id, status)
        self._gantt_view.update_task(task_id, status, start_pct, width_pct)
        self._update_progress()

    def clear_tasks(self):
        self._dep_view.clear()
        self._gantt_view.clear()
        self._update_progress()

    def _update_progress(self):
        total = len(self._dep_view._nodes)
        done = sum(1 for n in self._dep_view._nodes.values()
                   if n._status in ("completed", "failed", "cancelled"))
        self._progress_label.setText(f"{done}/{total}")
