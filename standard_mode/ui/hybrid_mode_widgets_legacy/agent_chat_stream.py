# -*- coding: utf-8 -*-
"""
v6.0-H B-2 — Agent 间对话流组件
================================
角色着色消息气泡 + 消息类型标签 + 折叠长消息 + 用户介入输入框。
"""

from typing import Dict, List, Optional
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QTextEdit, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QFont

from ui.design.tokens import Lemon
from ui.theme import SVG_ICONS

_ROLE_COLORS = {
    "coordinator": Lemon.ACCENT_BLUE,
    "researcher": Lemon.ACCENT_GREEN,
    "coder": Lemon.BRAND_ORANGE,
    "reviewer": Lemon.ACCENT_PURPLE,
    "tester": Lemon.ACCENT_ORANGE,
    "documenter": Lemon.ACCENT_PINK,
    "user": Lemon.ACCENT_PINK,
    "system": Lemon.BRAND_LEMON,
}

_ROLE_ICONS = {
    "coordinator": "layers",
    "researcher": "search",
    "coder": "code",
    "reviewer": "eye",
    "tester": "shield-check",
    "documenter": "file-text",
    "user": "user",
    "system": "bot",
}

_MSG_TYPE_LABELS = {
    "task_assign": "任务分配",
    "task_result": "结果汇报",
    "collab_request": "协作请求",
    "conflict_alert": "冲突告警",
    "context_share": "上下文共享",
    "status_update": "状态更新",
    "plan_request": "规划请求",
    "plan_result": "规划结果",
    "direct": "直接消息",
    "broadcast": "广播",
    "group": "群组消息",
    "user_input": "用户输入",
}

_MSG_TYPE_COLORS = {
    "task_assign": Lemon.BRAND_ORANGE,
    "task_result": Lemon.SUCCESS,
    "collab_request": Lemon.ACCENT_BLUE,
    "conflict_alert": Lemon.ERROR,
    "context_share": Lemon.ACCENT_PURPLE,
    "status_update": Lemon.DARK_TEXT_3,
    "plan_request": Lemon.ACCENT_BLUE,
    "plan_result": Lemon.ACCENT_BLUE,
    "direct": Lemon.ACCENT_BLUE,
    "broadcast": Lemon.ACCENT_ORANGE,
    "group": Lemon.ACCENT_GREEN,
    "user_input": Lemon.ACCENT_PINK,
}

_COLLAPSE_LINE_LIMIT = 5


class MessageBubble(QFrame):
    toggle_collapse = pyqtSignal(str)

    def __init__(self, msg_id: str, sender_id: str, sender_role: str = "",
                 msg_type: str = "direct", content: str = "",
                 timestamp: str = "", priority: str = "normal",
                 is_user: bool = False, parent=None):
        super().__init__(parent)
        self.msg_id = msg_id
        self._role = sender_role
        self._is_user = is_user
        self._collapsed = True
        self._content = content
        self._line_count = content.count("\n") + 1
        self._needs_collapse = self._line_count > _COLLAPSE_LINE_LIMIT
        self.setObjectName("msgBubble")
        self._build_ui(sender_id, sender_role, msg_type,
                       content, timestamp, priority, is_user)

    def _build_ui(self, sender_id: str, role: str, msg_type: str,
                  content: str, ts: str, priority: str, is_user: bool):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Lemon.SP_S, Lemon.SP_XS, Lemon.SP_S, Lemon.SP_XS)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(Lemon.SP_XS)

        role_color = _ROLE_COLORS.get(role, Lemon.DARK_TEXT_2)
        icon_name = _ROLE_ICONS.get(role, "bot")
        icon_svg = SVG_ICONS.get(icon_name, "")
        if icon_svg:
            icon = QLabel()
            icon.setFixedSize(14, 14)
            icon.setStyleSheet(f"color: {role_color};")
            icon.setText(icon_svg.replace('width="16" height="16"', 'width="14" height="14"'))
            header.addWidget(icon)

        sender = QLabel(sender_id)
        sender.setFont(QFont(Lemon.FONT, Lemon.FS_CAPTION, QFont.Bold))
        sender.setStyleSheet(f"color: {role_color}; border: none;")
        header.addWidget(sender)

        type_color = _MSG_TYPE_COLORS.get(msg_type, Lemon.DARK_TEXT_3)
        type_text = _MSG_TYPE_LABELS.get(msg_type, msg_type)
        type_label = QLabel(f"[{type_text}]")
        type_label.setFont(QFont(Lemon.FONT, 9))
        type_label.setStyleSheet(f"""
            color: {type_color};
            background: {type_color}22;
            border-radius: 3px;
            padding: 0px 3px;
        """)
        header.addWidget(type_label)

        if priority in ("high", "urgent"):
            p_icon = SVG_ICONS.get("alert-triangle" if priority == "urgent" else "chevron-up", "")
            if p_icon:
                p_label = QLabel()
                p_label.setFixedSize(12, 12)
                p_c = Lemon.ERROR if priority == "urgent" else Lemon.ACCENT_ORANGE
                p_label.setStyleSheet(f"color: {p_c};")
                p_label.setText(p_icon.replace('width="16" height="16"', 'width="12" height="12"'))
                header.addWidget(p_label)

        header.addStretch()

        if is_user:
            user_badge = QLabel("USER")
            user_badge.setFont(QFont(Lemon.FONT, 8, QFont.Bold))
            user_badge.setStyleSheet(f"""
                color: {Lemon.ACCENT_PINK};
                background: {Lemon.ACCENT_PINK}22;
                border: 1px solid {Lemon.ACCENT_PINK}44;
                border-radius: 3px;
                padding: 0px 3px;
            """)
            header.addWidget(user_badge)

        if ts:
            time_label = QLabel(ts[-8:] if len(ts) > 8 else ts)
            time_label.setFont(QFont(Lemon.FONT, 8))
            time_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_3}; border: none;")
            header.addWidget(time_label)

        layout.addLayout(header)

        if self._needs_collapse and self._collapsed:
            display = "\n".join(content.split("\n")[:_COLLAPSE_LINE_LIMIT])
            self._body_label = QLabel(display)
            self._body_label.setWordWrap(True)
            layout.addWidget(self._body_label)

            self._expand_btn = QPushButton("展开")
            self._expand_btn.setFixedHeight(18)
            self._expand_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {Lemon.ACCENT_BLUE};
                    border: none; font-family: {Lemon.FONT}; font-size: 9px;
                    text-align: left; padding: 0px;
                }}
                QPushButton:hover {{ color: {Lemon.BRAND_ORANGE}; }}
            """)
            self._expand_btn.clicked.connect(self._toggle)
            layout.addWidget(self._expand_btn)
        else:
            self._body_label = QLabel(content[:500])
            self._body_label.setWordWrap(True)
            self._expand_btn = None
            layout.addWidget(self._body_label)

        self._body_label.setFont(QFont(Lemon.FONT, Lemon.FS_CAPTION))
        self._body_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_1}; border: none;")
        self._body_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._apply_bubble_style(role, is_user)

    def _apply_bubble_style(self, role: str, is_user: bool):
        rc = _ROLE_COLORS.get(role, Lemon.BORDER)
        if is_user:
            rc = Lemon.ACCENT_PINK
        align = "right" if is_user else "left"
        opp = "left" if is_user else "right"
        margin_side = f"margin-{align}" if is_user else f"margin-{opp}"
        self.setStyleSheet(f"""
            QFrame#msgBubble {{
                background: {Lemon.SURFACE};
                border-{align}: 3px solid {rc};
                border-top: 1px solid {Lemon.BORDER};
                border-bottom: 1px solid {Lemon.BORDER};
                border-{opp}: 1px solid {Lemon.BORDER};
                border-radius: {Lemon.R_S}px;
                margin-{opp}: 30px;
            }}
        """)

    def _toggle(self):
        if not self._needs_collapse:
            return
        self._collapsed = not self._collapsed
        if self._collapsed:
            display = "\n".join(self._content.split("\n")[:_COLLAPSE_LINE_LIMIT])
            self._body_label.setText(display)
            self._expand_btn.setText("展开")
        else:
            self._body_label.setText(self._content[:500])
            self._expand_btn.setText("收起")


class AgentChatStream(QWidget):
    message_sent = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: List[MessageBubble] = []
        self._max_messages = 200
        self._msg_counter = 0
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Lemon.SP_S, Lemon.SP_S, Lemon.SP_S, Lemon.SP_S)
        layout.setSpacing(Lemon.SP_XS)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(Lemon.SP_S)

        title = QLabel("Agent 通讯")
        title.setFont(QFont(Lemon.FONT, Lemon.FS_TITLE, QFont.Bold))
        title.setStyleSheet(f"color: {Lemon.BRAND_ORANGE}; border: none;")
        toolbar.addWidget(title)

        toolbar.addStretch()

        self._msg_count = QLabel("(0)")
        self._msg_count.setFont(QFont(Lemon.FONT, Lemon.FS_CAPTION))
        self._msg_count.setStyleSheet(f"color: {Lemon.DARK_TEXT_3}; border: none;")
        toolbar.addWidget(self._msg_count)

        layout.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: {Lemon.BG}; border: none; }}
            QScrollBar:vertical {{
                background: {Lemon.BG}; width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {Lemon.SCROLLBAR_THUMB}; border-radius: 3px;
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

        input_row = QHBoxLayout()
        input_row.setSpacing(Lemon.SP_XS)

        self._input = QTextEdit()
        self._input.setFixedHeight(32)
        self._input.setPlaceholderText("输入消息（广播给所有 Agent）...")
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background: {Lemon.SURFACE};
                color: {Lemon.DARK_TEXT_1};
                border: 1px solid {Lemon.BORDER};
                border-radius: {Lemon.R_S}px;
                padding: 4px 8px;
                font-family: {Lemon.FONT};
                font-size: {Lemon.FS_CAPTION}px;
            }}
            QTextEdit:focus {{
                border: 1px solid {Lemon.BRAND_ORANGE};
            }}
        """)
        input_row.addWidget(self._input, 1)

        send_btn = QPushButton("Send")
        send_btn.setFixedSize(48, 32)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Lemon.BRAND_ORANGE};
                color: white;
                border: none;
                border-radius: {Lemon.R_S}px;
                font-family: {Lemon.FONT};
                font-size: {Lemon.FS_CAPTION}px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {Lemon.BRAND_ORANGE_LIGHT}; }}
        """)
        send_btn.clicked.connect(self._on_send)
        input_row.addWidget(send_btn)

        layout.addLayout(input_row)

    def add_message(self, sender_id: str, sender_role: str = "",
                    msg_type: str = "direct", content: str = "",
                    timestamp: str = "", priority: str = "normal",
                    is_user: bool = False):
        if len(self._messages) >= self._max_messages:
            old = self._messages.pop(0)
            self._msg_layout.removeWidget(old)
            old.deleteLater()

        self._msg_counter += 1
        msg_id = f"msg_{self._msg_counter}"
        bubble = MessageBubble(msg_id, sender_id, sender_role, msg_type,
                               content, timestamp, priority, is_user)

        idx = self._msg_layout.count() - 1
        self._msg_layout.insertWidget(idx, bubble)
        self._messages.append(bubble)
        self._msg_count.setText(f"({len(self._messages)})")

        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if not text:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        self.add_message("user", "user", "user_input", text, ts, "normal", is_user=True)
        self.message_sent.emit("user", text, "broadcast")
        self._input.clear()

    def clear_messages(self):
        for m in self._messages:
            self._msg_layout.removeWidget(m)
            m.deleteLater()
        self._messages.clear()
        self._msg_count.setText("(0)")
