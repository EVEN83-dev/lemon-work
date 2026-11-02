# -*- coding: utf-8 -*-
"""
v3.0 Module C — Agent 聊天面板
============================
多 Agent 消息流，角色着色气泡。
- 消息气泡按发送者角色着色
- 消息类型标签（DIRECT / BROADCAST / GROUP）
- 时间戳 + 优先级标记
- 自动滚动到最新消息
"""

import os
import sys
from typing import Dict, List, Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QTextEdit, QComboBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor

from ui.design.tokens import Lemon
from ui.theme import (
    BG_DARK, BG_PANEL, BG_SURFACE, BG_SURFACE_HOVER,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    LEMON_ORANGE, SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR, INFO_COLOR,
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
    "system": LEMON_ORANGE,
}

MSG_TYPE_LABELS = {
    "direct": "DIRECT",
    "broadcast": "BROADCAST",
    "group": "GROUP",
    "status_update": "STATUS",
    "task_assign": "TASK",
    "task_result": "RESULT",
    "context_share": "CTX",
    "plan_request": "PLAN",
    "plan_result": "PLAN-R",
}

MSG_TYPE_COLORS = {
    "direct": INFO_COLOR,
    "broadcast": WARNING_COLOR,
    "group": "#69F0AE",
    "status_update": TEXT_TERTIARY,
    "task_assign": LEMON_ORANGE,
    "task_result": SUCCESS_COLOR,
    "context_share": "#B388FF",
    "plan_request": "#448AFF",
    "plan_result": "#448AFF",
}

PRIORITY_ICONS = {
    "low": SVG_ICONS.get("chevron_down", ""),
    "normal": "",
    "high": SVG_ICONS.get("chevron_up", ""),
    "urgent": SVG_ICONS.get("warn", ""),
}


class MessageBubble(QFrame):
    def __init__(self, sender_id: str, sender_role: str = "",
                 message_type: str = "direct", content: str = "",
                 timestamp: str = "", priority: str = "normal",
                 is_self: bool = False, parent=None):
        super().__init__(parent)
        self._build_ui(sender_id, sender_role, message_type,
                       content, timestamp, priority, is_self)

    def _build_ui(self, sender_id: str, role: str, msg_type: str,
                  content: str, ts: str, priority: str, is_self: bool):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        header = QHBoxLayout()
        header.setSpacing(6)

        role_color = ROLE_COLORS.get(role, TEXT_SECONDARY)

        role_icon_name = {
            "coordinator": "folder_open",
            "researcher": "search",
            "coder": "tool",
            "reviewer": "eye",
            "tester": "check",
            "documenter": "file_doc",
            "system": "sparkles",
        }.get(role, "sparkles")

        icon_svg = SVG_ICONS.get(role_icon_name, "")
        if icon_svg:
            icon = QLabel()
            icon.setFixedSize(14, 14)
            icon.setStyleSheet(f"color: {role_color};")
            icon.setText(icon_svg.replace('width="16" height="16"', 'width="14" height="14"'))
            header.addWidget(icon)

        sender_label = QLabel(sender_id)
        sender_label.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
        sender_label.setStyleSheet(f"color: {role_color}; border: none;")
        header.addWidget(sender_label)

        type_color = MSG_TYPE_COLORS.get(msg_type, TEXT_TERTIARY)
        type_label = QLabel(MSG_TYPE_LABELS.get(msg_type, msg_type.upper()))
        type_label.setFont(QFont(FONT_FAMILY, 7, QFont.Bold))
        type_label.setStyleSheet(f"""
            color: {type_color};
            background: {type_color}22;
            border-radius: 3px;
            padding: 0px 3px;
        """)
        header.addWidget(type_label)

        if priority in ("high", "urgent"):
            p_icon = PRIORITY_ICONS.get(priority, "")
            if p_icon:
                p_label = QLabel()
                p_label.setFixedSize(12, 12)
                p_color = ERROR_COLOR if priority == "urgent" else WARNING_COLOR
                p_label.setStyleSheet(f"color: {p_color};")
                p_label.setText(p_icon.replace('width="16" height="16"', 'width="12" height="12"'))
                header.addWidget(p_label)

        header.addStretch()

        if ts:
            time_label = QLabel(ts[-8:] if len(ts) > 8 else ts)
            time_label.setFont(QFont(FONT_FAMILY, 7))
            time_label.setStyleSheet(f"color: {TEXT_TERTIARY}; border: none;")
            header.addWidget(time_label)

        layout.addLayout(header)

        display_content = content[:500] if content and content.strip() else ""
        if not content or not content.strip():
            display_content = "（Agent 生成内容为空，已显示工具调用记录）"
        body = QLabel(display_content)
        body.setFont(QFont(FONT_FAMILY, 10))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if not content or not content.strip():
            body.setStyleSheet("color: #888; font-style: italic; border: none;")
        else:
            body.setStyleSheet(f"color: {TEXT_PRIMARY}; border: none;")
        layout.addWidget(body)

        align = "right" if is_self else "left"
        border_color = role_color if role else BORDER_DEFAULT
        self.setStyleSheet(f"""
            MessageBubble {{
                background: {BG_SURFACE};
                border-{align}: 3px solid {border_color};
                border-top: 1px solid {BORDER_DEFAULT};
                border-bottom: 1px solid {BORDER_DEFAULT};
                border-{"left" if is_self else "right"}: 1px solid {BORDER_DEFAULT};
                border-radius: {BORDER_RADIUS};
                margin-{align}: 20px;
            }}
        """)


class AgentChatPanel(QWidget):
    message_sent = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: List[MessageBubble] = []
        self._max_messages = 200
        self._filter_role = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        title = QLabel("Agent 通讯")
        title.setFont(QFont(FONT_FAMILY, 14, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE}; border: none;")
        toolbar.addWidget(title)

        toolbar.addStretch()

        self._msg_count = QLabel("(0)")
        self._msg_count.setFont(QFont(FONT_FAMILY, 10))
        self._msg_count.setStyleSheet(f"color: {TEXT_TERTIARY}; border: none;")
        toolbar.addWidget(self._msg_count)

        filter_label = QLabel("过滤:")
        filter_label.setFont(QFont(FONT_FAMILY, 9))
        filter_label.setStyleSheet(f"color: {TEXT_SECONDARY}; border: none;")
        toolbar.addWidget(filter_label)

        self._filter_combo = QComboBox()
        self._filter_combo.addItem("全部")
        for role in ROLE_COLORS:
            self._filter_combo.addItem(role)
        self._filter_combo.setFixedWidth(100)
        self._filter_combo.setFixedHeight(24)
        self._filter_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_SURFACE};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {BORDER_RADIUS};
                color: {TEXT_PRIMARY};
                padding: 2px 6px;
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
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_combo)

        layout.addLayout(toolbar)

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

        self._msg_container = QWidget()
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(4, 4, 4, 4)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch()

        scroll.setWidget(self._msg_container)
        self._scroll = scroll
        layout.addWidget(scroll, 1)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(6)

        self._input = QTextEdit()
        self._input.setFixedHeight(36)
        self._input.setPlaceholderText("输入消息...")
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {BORDER_RADIUS};
                padding: 4px 8px;
                font-family: {FONT_FAMILY};
                font-size: 11px;
            }}
            QTextEdit:focus {{
                border: 1px solid {LEMON_ORANGE};
            }}
        """)
        input_layout.addWidget(self._input, 1)

        send_btn = QPushButton("Send")
        send_btn.setFixedSize(50, 36)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS};
                font-family: {FONT_FAMILY};
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {LEMON_ORANGE_LIGHT if 'LEMON_ORANGE_LIGHT' in dir() else '#ff8c42'};
            }}
        """)
        send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(send_btn)

        layout.addLayout(input_layout)

    def add_message(self, sender_id: str, sender_role: str = "",
                    message_type: str = "direct", content: str = "",
                    timestamp: str = "", priority: str = "normal",
                    is_self: bool = False):
        if len(self._messages) >= self._max_messages:
            old = self._messages.pop(0)
            self._msg_layout.removeWidget(old)
            old.deleteLater()

        bubble = MessageBubble(sender_id, sender_role, message_type,
                               content, timestamp, priority, is_self)

        show = True
        if self._filter_role and self._filter_role != "全部":
            show = sender_role == self._filter_role
        bubble.setVisible(show)

        idx = self._msg_layout.count() - 1
        self._msg_layout.insertWidget(idx, bubble)
        self._messages.append(bubble)
        self._msg_count.setText(f"({len(self._messages)})")

        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_filter_changed(self, role: str):
        self._filter_role = role
        for bubble in self._messages:
            if role == "全部" or not role:
                bubble.setVisible(True)
            else:
                bubble.setVisible(bubble._role == role if hasattr(bubble, '_role') else True)

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if not text:
            return
        self.message_sent.emit("user", text, "direct")
        self._input.clear()

    def clear_messages(self):
        for m in self._messages:
            self._msg_layout.removeWidget(m)
            m.deleteLater()
        self._messages.clear()
        self._msg_count.setText("(0)")
