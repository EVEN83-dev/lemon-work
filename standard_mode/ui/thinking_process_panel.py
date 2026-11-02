"""
修复B: 思考过程可视化面板 - 对标 TRAE 的 thinking panel
实时展示 Agent 思考步骤: 意图分析→工具调用→结果→总结→完成
SVG 图标使用 Lucide 简笔画风格, 主色 {Lemon.PRIMARY}, 强调色 {Lemon.SECONDARY}
V6.0: 增加状态图标(running spinner/success checkmark/error cross) + update_status()
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QEvent
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)
from ui.design.tokens import Lemon

_STEP_ICONS = {
    "context_inject": f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{Lemon.PRIMARY}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    "tool_call": f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{Lemon.PRIMARY}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    "tool_result": f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{Lemon.PRIMARY}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    "summarizing": f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{Lemon.PRIMARY}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
    "done": f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{Lemon.PRIMARY}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
    "intent_analyze": f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{Lemon.PRIMARY}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    "progress_compress": f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{Lemon.PRIMARY}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></svg>',
    "progress_result": f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{Lemon.PRIMARY}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
}

_STEP_COLORS = {
    "context_inject": Lemon.SECONDARY,
    "tool_call": "#3B82F6",
    "tool_result": "#10B981",
    "summarizing": "#F59E0B",
    "done": Lemon.SECONDARY,
    "intent_analyze": Lemon.ACCENT_PURPLE,
    "progress_compress": "#6366F1",
    "progress_result": "#10B981",
}

_STATUS_ICONS = {
    "running": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="' + Lemon.ACCENT_BLUE + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>',
    "success": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="' + Lemon.SUCCESS + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    "error": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="' + Lemon.ERROR + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    "pending": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="' + Lemon.SECONDARY + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/></svg>',
}

_STATUS_BORDER_COLORS = {
    "running": Lemon.ACCENT_BLUE,
    "success": Lemon.SUCCESS,
    "error": Lemon.ERROR,
    "pending": Lemon.SECONDARY,
}


@dataclass
class ThinkingStep:
    step_id: str
    type: str
    description: str
    status: str = "running"
    timestamp: float = 0.0
    duration_ms: float = 0.0
    children: list = field(default_factory=list)


class ThinkingStepWidget(QFrame):
    def __init__(self, step_type: str, description: str,
                 details: Dict[str, Any], duration_ms: float,
                 step_index: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._step_type = step_type
        self._description = description
        self._details = details
        self._expanded = False
        self._status = "running"

        color = _STEP_COLORS.get(step_type, Lemon.SECONDARY)
        self.setStyleSheet(
            f"ThinkingStepWidget {{ "
            f"border-left: 3px solid {color}; "
            f"background: {Lemon.SURFACE}; "
            f"border-radius: 0 4px 4px 0; "
            f"padding: 4px 8px; "
            f"margin: 1px 0; }}"
        )
        self.setFixedHeight(28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        self._status_label = QLabel()
        self._status_label.setFixedSize(16, 16)
        self._status_label.setStyleSheet("border: none; padding: 0; margin: 0;")
        self._set_status_icon("running")
        layout.addWidget(self._status_label)

        icon_svg = _STEP_ICONS.get(step_type, _STEP_ICONS.get("done", ""))
        icon_label = QLabel()
        icon_label.setFixedSize(16, 16)
        icon_label.setStyleSheet("border: none; padding: 0; margin: 0;")
        icon_label.setText(icon_svg)
        layout.addWidget(icon_label)

        idx_label = QLabel(f"{step_index}.")
        idx_label.setFixedWidth(20)
        idx_label.setStyleSheet("color: " + Lemon.SECONDARY + "; font-size: 11px; border: none;")
        layout.addWidget(idx_label)

        desc_label = QLabel(description[:120])
        desc_label.setStyleSheet("color: " + Lemon.PRIMARY + "; font-size: 12px; border: none;")
        desc_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(desc_label)

        if duration_ms > 0:
            dur_label = QLabel(f"{duration_ms:.0f}ms")
            dur_label.setStyleSheet("color: " + Lemon.SECONDARY + "; font-size: 10px; border: none;")
            layout.addWidget(dur_label)

        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(150)
        self._spin_timer.timeout.connect(self._animate_spinner)
        self._spin_angle = 0
        self._spin_timer.start()

    def _set_status_icon(self, status: str) -> None:
        svg = _STATUS_ICONS.get(status, _STATUS_ICONS["pending"])
        self._status_label.setText(svg)

    def update_status(self, status: str) -> None:
        """V6.0: 更新步骤状态(running/success/error/pending)。"""
        self._status = status
        self._set_status_icon(status)
        border_color = _STATUS_BORDER_COLORS.get(status, Lemon.SECONDARY)
        type_color = _STEP_COLORS.get(self._step_type, Lemon.SECONDARY)
        final_color = border_color if status != "running" else type_color
        self.setStyleSheet(
            "ThinkingStepWidget { "
            "border-left: 3px solid " + final_color + "; "
            "background: " + Lemon.SURFACE + "; "
            "border-radius: 0 4px 4px 0; "
            "padding: 4px 8px; "
            "margin: 1px 0; }"
        )
        if status != "running":
            self._spin_timer.stop()

    def _animate_spinner(self) -> None:
        """V6.0: 旋转running图标动画。"""
        self._spin_angle = (self._spin_angle + 45) % 360
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(8, 8)
        painter.rotate(self._spin_angle)
        painter.setPen(QPen(QColor(Lemon.ACCENT_BLUE), 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(0, -5, 0, -7)
        painter.setPen(QPen(QColor(Lemon.ACCENT_BLUE + "88"), 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(0, 5, 0, 7)
        painter.end()
        self._status_label.setPixmap(pixmap)


class ThinkingProcessPanel(QWidget):
    thinking_step = pyqtSignal(str, str, dict)
    thinking_reset = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._steps: List[Dict[str, Any]] = []
        self._step_counter = 0
        self._collapsed = False
        self._active_widgets: Dict[str, ThinkingStepWidget] = {}
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(
            "ThinkingProcessPanel { background: {Lemon.BG}; border: 1px solid {Lemon.BORDER}; "
            "border-radius: 6px; }"
        )

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet("background: #FAFAFA; border-bottom: 1px solid {Lemon.BORDER}; border-radius: 6px 6px 0 0;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 10, 0)

        title_label = QLabel("思考过程")
        title_label.setStyleSheet(
            "color: {Lemon.PRIMARY}; font-size: 13px; font-weight: 500; border: none; background: transparent;"
        )
        header_layout.addWidget(title_label)

        self._count_label = QLabel("0 步")
        self._count_label.setStyleSheet(
            "color: {Lemon.SECONDARY}; font-size: 11px; border: none; background: transparent;"
        )
        header_layout.addWidget(self._count_label)

        header_layout.addStretch()

        self._toggle_btn = QPushButton("收起")
        self._toggle_btn.setFixedSize(40, 20)
        self._toggle_btn.setStyleSheet(
            "QPushButton { color: {Lemon.SECONDARY}; font-size: 11px; border: 1px solid {Lemon.BORDER}; "
            "border-radius: 3px; background: {Lemon.BG}; }"
            "QPushButton:hover { background: {Lemon.SURFACE}; }"
        )
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        header_layout.addWidget(self._toggle_btn)

        main_layout.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: {Lemon.BG}; }"
            "QScrollBar:vertical { width: 4px; background: transparent; }"
            "QScrollBar::handle:vertical { background: {Lemon.DARK_TEXT_1}; border-radius: 2px; }"
        )

        self._steps_container = QWidget()
        self._steps_layout = QVBoxLayout(self._steps_container)
        self._steps_layout.setContentsMargins(8, 4, 8, 4)
        self._steps_layout.setSpacing(2)
        self._steps_layout.addStretch()

        self._scroll.setWidget(self._steps_container)
        self._scroll.setMaximumHeight(200)
        main_layout.addWidget(self._scroll)

    @pyqtSlot(str, str, dict)
    def add_step(self, step_type: str, description: str,
                 details: Dict[str, Any] = None, duration_ms: float = 0.0):
        self._step_counter += 1
        step_data = {
            "stepType": step_type,
            "description": description,
            "details": details or {},
            "durationMs": duration_ms,
            "timestamp": time.time(),
            "index": self._step_counter,
        }
        self._steps.append(step_data)

        widget = ThinkingStepWidget(
            step_type, description, details or {}, duration_ms,
            self._step_counter, self._steps_container,
        )
        step_key = str(self._step_counter) + "_" + description[:40]
        self._active_widgets[step_key] = widget
        insert_pos = self._steps_layout.count() - 1
        self._steps_layout.insertWidget(insert_pos, widget)

        self._count_label.setText(f"{self._step_counter} 步")
        self.thinking_step.emit(step_type, description, details or {})

        QTimer.singleShot(50, self._scroll_to_bottom)

    def update_step_status(self, description: str, status: str) -> None:
        """V6.0: 根据描述匹配步骤并更新状态。"""
        for key, widget in self._active_widgets.items():
            if description[:40] in key:
                widget.update_status(status)
                if status in ("success", "error"):
                    self._active_widgets.pop(key, None)
                break

    def clear_steps(self):
        self._steps.clear()
        self._step_counter = 0
        self._active_widgets.clear()
        self._count_label.setText("0 步")
        while self._steps_layout.count() > 1:
            item = self._steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.thinking_reset.emit()

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._scroll.setVisible(not self._collapsed)
        self._toggle_btn.setText("展开" if self._collapsed else "收起")
        if self._collapsed:
            self.setFixedHeight(32)
        else:
            self.setMinimumHeight(60)
            self.setMaximumHeight(240)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def get_step_count(self) -> int:
        return self._step_counter

    def get_steps(self) -> List[Dict[str, Any]]:
        return list(self._steps)
