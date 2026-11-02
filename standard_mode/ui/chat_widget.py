# -*- coding: utf-8 -*-
"""Lemon Agent 对话流组件 — 五段式结构
所属窗口: BottomPanel.mimo_console  品牌组件: LemonChatFlow
令牌引用: Lemon.PRIMARY/SECONDARY/BG/SURFACE/BORDER/BORDER_HOVER/SUCCESS/ERROR
           Lemon.SP_*/R_*/FS_*/FONT/DUR_*/BRAND_LEMON
规范: 用户气泡(右对齐)→思考折叠面板→工具卡片序列→AI回答(左对齐)→Quick Actions
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from PyQt5.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal,
)
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.design.tokens import Lemon
from ui.design.icons import (
    ICON_FAILED, ICON_GEAR, ICON_INTENT, ICON_RUNNING,
    ICON_STAR, ICON_SUCCESS, ICON_TIMEOUT, ICON_TOOL,
    load_icon, load_pixmap,
)


class UserBubble(QWidget):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("lemonCard")
        T = Lemon
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(0)
        inner = QHBoxLayout()
        inner.addStretch()
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_BODY}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        bubble = QWidget()
        bubble.setStyleSheet(
            f"background: {T.SURFACE}; border-radius: {T.R_M}px; "
            f"border-top-right-radius: {T.R_S}px; padding: {T.SP_S}px {T.SP_M}px;"
        )
        bl = QVBoxLayout(bubble)
        bl.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        bl.addWidget(label)
        inner.addWidget(bubble)
        layout.addLayout(inner)


class ThinkingStepRow(QWidget):
    def __init__(self, step_type: str, description: str, duration_ms: float,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        T = Lemon
        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.SP_S, 2, T.SP_S, 2)
        layout.setSpacing(T.SP_S)

        _ICON_MAP = {
            "context_inject": ICON_GEAR,
            "intent_analyze": ICON_INTENT,
            "tool_select": ICON_TOOL,
            "tool_call": ICON_TOOL,
            "tool_result": ICON_GEAR,
            "summarizing": ICON_DOC,
            "done": ICON_STAR,
        }
        icon_name = _ICON_MAP.get(step_type, ICON_GEAR)
        icon_label = QLabel()
        pm = load_pixmap(icon_name, "inline")
        icon_label.setPixmap(pm)
        icon_label.setFixedSize(16, 16)
        layout.addWidget(icon_label)

        line = QWidget()
        line.setFixedWidth(2)
        line.setStyleSheet(f"background: {T.BORDER};")
        layout.addWidget(line)

        desc_label = QLabel(description)
        desc_label.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        desc_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(desc_label)

        dur_str = f"{duration_ms / 1000:.1f}s" if duration_ms > 0 else ""
        if dur_str:
            dur_label = QLabel(dur_str)
            dur_label.setStyleSheet(
                f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
                f"background: transparent; border: none;"
            )
            dur_label.setFixedWidth(48)
            dur_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(dur_label)


class ThinkingPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._steps: List[ThinkingStepRow] = []
        self._expanded = False
        self._step_count = 0
        self._total_duration = 0.0
        self._init_ui()

    def _init_ui(self):
        T = Lemon
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._header = QPushButton("思考过程")
        self._header.setObjectName("ghostBtn")
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setStyleSheet(
            f"QPushButton {{ color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; border: none; background: transparent; "
            f"text-align: left; padding: {T.SP_S}px {T.SP_M}px; }}"
            f"QPushButton:hover {{ color: {T.PRIMARY}; background: {T.SURFACE}; }}"
        )
        self._header.clicked.connect(self._toggle)
        self._layout.addWidget(self._header)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(T.SP_M, 0, T.SP_M, T.SP_S)
        self._content_layout.setSpacing(0)
        self._content.setVisible(False)
        self._layout.addWidget(self._content)

    def add_step(self, step_type: str, description: str,
                 details: dict = None, duration_ms: float = 0.0):
        self._step_count += 1
        if duration_ms > 0:
            self._total_duration += duration_ms
        row = ThinkingStepRow(step_type, description, duration_ms)
        self._steps.append(row)
        self._content_layout.addWidget(row)
        self._update_header()

    def _update_header(self):
        dur_str = f"{self._total_duration / 1000:.1f}s" if self._total_duration > 0 else ""
        self._header.setText(
            f"思考过程 · {self._step_count} 步 · {dur_str}"
        )

    def _toggle(self):
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)

    def clear_steps(self):
        self._steps.clear()
        self._step_count = 0
        self._total_duration = 0.0
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._header.setText("思考过程")
        self._expanded = False
        self._content.setVisible(False)


class ToolCardItem(QWidget):
    def __init__(self, call_id: str, tool_name: str, status: str,
                 args: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.call_id = call_id
        self._tool_name = tool_name
        self._status = status
        self._args = args
        self._start_time = time.time()
        self._init_ui(tool_name, status, args)

    def _init_ui(self, tool_name: str, status: str, args: dict):
        T = Lemon
        self.setObjectName(
            f"toolCard{'Running' if status == 'running' else 'Completed' if status == 'completed' else 'Failed'}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(T.SP_XS)

        row1 = QHBoxLayout()
        row1.setSpacing(T.SP_S)

        self._icon_label = QLabel()
        icon_name = ICON_RUNNING if status == "running" else ICON_SUCCESS if status == "completed" else ICON_FAILED
        pm = load_pixmap(icon_name, "inline")
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
            f"background: transparent; border: none;"
        )
        self._duration_label.setFixedWidth(48)
        self._duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row1.addWidget(self._duration_label)
        layout.addLayout(row1)

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
            self._timer.start(100)
        else:
            self._timer = None

    def update_status(self, status: str, description: str, duration_ms: int = 0):
        T = Lemon
        self._status = status
        self.setObjectName(
            f"toolCard{'Running' if status == 'running' else 'Completed' if status == 'completed' else 'Failed'}"
        )
        icon_name = ICON_RUNNING if status == "running" else ICON_SUCCESS if status == "completed" else ICON_FAILED
        stroke = T.SECONDARY if status == "running" else T.SUCCESS if status == "completed" else T.ERROR
        pm = load_pixmap(icon_name, "inline", stroke_color=stroke)
        self._icon_label.setPixmap(pm)
        if description:
            color = T.PRIMARY if status == "completed" else T.ERROR
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

    def _update_elapsed(self):
        elapsed = int((time.time() - self._start_time) * 1000)
        self._duration_label.setText(f"{elapsed / 1000:.1f}s")


class AIResponseBlock(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        T = Lemon
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        self._layout.setSpacing(0)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._label.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_BODY}px; "
            f"font-family: '{T.FONT}'; line-height: {T.LINE_HEIGHT_BODY}; "
            f"background: transparent; border: none;"
        )
        self._layout.addWidget(self._label)

        self._cursor_label = QLabel("")
        self._cursor_label.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_BODY}px; "
            f"background: transparent; border: none;"
        )
        self._cursor_visible = False
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._blink_cursor)
        self._cursor_timer.start(Lemon.DUR_SLOW)

    def append_text(self, text: str):
        current = self._label.text()
        self._label.setText(current + text)

    def set_text(self, text: str):
        self._label.setText(text)

    def start_cursor(self):
        self._cursor_visible = True
        self._cursor_label.setText("|")

    def stop_cursor(self):
        self._cursor_visible = False
        self._cursor_label.setText("")

    def _blink_cursor(self):
        if not self._cursor_visible:
            return
        if self._cursor_label.text() == "|":
            self._cursor_label.setText("")
        else:
            self._cursor_label.setText("|")


class QuickActions(QWidget):
    copy_clicked = pyqtSignal()
    regenerate_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        T = Lemon
        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_XS, T.SP_M, T.SP_XS)
        layout.setSpacing(T.SP_S)

        for text, signal in [
            ("复制", self.copy_clicked),
            ("重新生成", self.regenerate_clicked),
        ]:
            btn = QPushButton(text)
            btn.setObjectName("ghostBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(signal.emit)
            layout.addWidget(btn)
        layout.addStretch()


class LemonChatFlow(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        T = Lemon
        self._tool_cards: Dict[str, ToolCardItem] = {}
        self._current_thinking: Optional[ThinkingPanel] = None
        self._current_ai: Optional[AIResponseBlock] = None
        self._current_actions: Optional[QuickActions] = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(T.SP_S)
        self._layout.addStretch()

    def add_user_message(self, text: str):
        self._new_round()
        bubble = UserBubble(text)
        self._insert_widget(bubble)

    def add_thinking_step(self, step_type: str, description: str,
                          details: dict = None, duration_ms: float = 0.0):
        if self._current_thinking is None:
            self._current_thinking = ThinkingPanel()
            self._insert_widget(self._current_thinking)
        self._current_thinking.add_step(step_type, description, details, duration_ms)

    def add_tool_card(self, call_id: str, tool_name: str, status: str,
                      args: dict, description: str = "", duration_ms: int = 0):
        if call_id in self._tool_cards:
            self._tool_cards[call_id].update_status(status, description, duration_ms)
        elif status == "running":
            card = ToolCardItem(call_id, tool_name, status, args)
            self._tool_cards[call_id] = card
            self._insert_widget(card)
            self._animate_entry(card)

    def start_ai_response(self):
        if self._current_ai is None:
            self._current_ai = AIResponseBlock()
            self._insert_widget(self._current_ai)
            self._current_ai.start_cursor()

    def append_ai_text(self, text: str):
        if self._current_ai:
            self._current_ai.append_text(text)

    def end_ai_response(self, full_text: str = ""):
        if self._current_ai:
            if full_text:
                self._current_ai.set_text(full_text)
            self._current_ai.stop_cursor()
            actions = QuickActions()
            self._current_actions = actions
            self._insert_widget(actions)
            self._animate_entry(actions)

    def add_context_counter(self, current: int, maximum: int, compressed: bool = False):
        T = Lemon
        ratio = current / maximum if maximum > 0 else 0
        color = T.ERROR if ratio > 0.8 else T.SECONDARY
        text = f"上下文 {current} / {maximum}"
        if compressed:
            text += " · 已压缩"
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {color}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none; "
            f"padding: {T.SP_XS}px {T.SP_M}px;"
        )
        self._insert_widget(label)

    def _new_round(self):
        self._current_thinking = None
        self._current_ai = None
        self._current_actions = None
        self._tool_cards.clear()

    def _insert_widget(self, widget: QWidget):
        stretch_idx = self._layout.count() - 1
        self._layout.insertWidget(stretch_idx, widget)

    def _animate_entry(self, widget: QWidget):
        T = Lemon
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        widget.setGeometry(widget.x(), widget.y() + 8, widget.width(), widget.height())
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(T.DUR_NORMAL)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        pos_anim = QPropertyAnimation(widget, b"geometry")
        pos_anim.setDuration(T.DUR_NORMAL)
        geo = widget.geometry()
        pos_anim.setStartValue(geo.adjusted(0, 8, 0, 8))
        pos_anim.setEndValue(geo)
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        pos_anim.start(QPropertyAnimation.DeleteWhenStopped)

    def clear_all(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._layout.addStretch()
        self._tool_cards.clear()
        self._current_thinking = None
        self._current_ai = None
        self._current_actions = None

    def add_file_changes(self, changes: list) -> None:
        if changes:
            card = FileChangeCard(changes)
            self._insert_widget(card)
            self._animate_entry(card)

    def add_plan(self, plan_data: dict) -> None:
        from ui.plan_panel import PlanConfirmationPanel
        panel = PlanConfirmationPanel()
        panel.set_plan(plan_data)
        panel.plan_accepted.connect(lambda: self._on_plan_response("accepted"))
        panel.plan_rejected.connect(lambda: self._on_plan_response("rejected"))
        panel.plan_modified.connect(lambda d: self._on_plan_response("modified", d))
        self._insert_widget(panel)
        self._animate_entry(panel)

    def _on_plan_response(self, action: str, data: dict = None):
        pass


class FileChangeCard(QWidget):
    view_diff_clicked = pyqtSignal(str)

    def __init__(self, changes: list, parent=None):
        super().__init__(parent)
        T = Lemon
        self.setObjectName("lemonCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(T.SP_XS)

        header = QHBoxLayout()
        title = QLabel("文件变更清单")
        title.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_SUB}px; font-weight: bold; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        header.addWidget(title)
        header.addStretch()
        count_label = QLabel(f"{len(changes)} 个文件")
        count_label.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"background: transparent; border: none;"
        )
        header.addWidget(count_label)
        layout.addLayout(header)

        _OP_ICONS = {
            "file_edit": "edit",
            "file_write": "add",
            "file_create": "add",
            "file_delete": "del",
            "file_read": "view",
        }
        _OP_COLORS = {
            "file_edit": T.PRIMARY,
            "file_write": T.SUCCESS,
            "file_create": T.SUCCESS,
            "file_delete": T.ERROR,
            "file_read": T.SECONDARY,
        }

        for change in changes[:10]:
            skill = change.get("skill", "unknown")
            path = change.get("path", "unknown")
            success = change.get("success", True)
            op_color = _OP_COLORS.get(skill, T.SECONDARY)
            row = QHBoxLayout()
            row.setSpacing(T.SP_S)

            op_label = QLabel(f"[{skill.replace('file_', '').upper()}]")
            op_label.setStyleSheet(
                f"color: {op_color}; font-size: {T.FS_CAPTION}px; font-weight: bold; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            op_label.setFixedWidth(48)
            row.addWidget(op_label)

            path_label = QLabel(path)
            path_label.setStyleSheet(
                f"color: {T.PRIMARY}; font-size: {T.FS_BODY}px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            row.addWidget(path_label)

            status_text = "OK" if success else "FAIL"
            status_color = T.SUCCESS if success else T.ERROR
            status_label = QLabel(status_text)
            status_label.setStyleSheet(
                f"color: {status_color}; font-size: {T.FS_CAPTION}px; "
                f"background: transparent; border: none;"
            )
            status_label.setFixedWidth(32)
            row.addWidget(status_label)

            diff_btn = QPushButton("Diff")
            diff_btn.setObjectName("ghostBtn")
            diff_btn.setCursor(Qt.PointingHandCursor)
            p = path
            diff_btn.clicked.connect(lambda checked, pp=p: self.view_diff_clicked.emit(pp))
            row.addWidget(diff_btn)

            layout.addLayout(row)

        if len(changes) > 10:
            more = QLabel(f"... 还有 {len(changes) - 10} 个文件")
            more.setStyleSheet(
                f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
                f"background: transparent; border: none;"
            )
            layout.addWidget(more)


class DiffViewWidget(QWidget):
    def __init__(self, path: str, old_content: str, new_content: str, parent=None):
        super().__init__(parent)
        T = Lemon
        self.setWindowTitle(f"Diff: {path}")
        self.resize(800, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_M, T.SP_M, T.SP_M)

        path_label = QLabel(path)
        path_label.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_TITLE}px; font-weight: bold; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        layout.addWidget(path_label)

        from PyQt5.QtWidgets import QTextEdit
        diff_edit = QTextEdit()
        diff_edit.setReadOnly(True)
        diff_html = self._render_diff(old_content, new_content)
        diff_edit.setHtml(diff_html)
        diff_edit.setStyleSheet(
            f"background: {T.BG}; color: {T.PRIMARY}; border: 1px solid {T.BORDER}; "
            f"border-radius: {T.R_S}px; font-family: 'Consolas', monospace; "
            f"font-size: {T.FS_BODY}px;"
        )
        layout.addWidget(diff_edit, 1)

    @staticmethod
    def _render_diff(old: str, new: str) -> str:
        T = Lemon
        old_lines = old.splitlines()
        new_lines = new.splitlines()

        html_parts = [
            f'<div style="font-family: Consolas, monospace; font-size: 13px; '
            f'line-height: 1.5; white-space: pre;">'
        ]

        import difflib
        diff = difflib.unified_diff(old_lines, new_lines, lineterm='')
        for line in diff:
            line_escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            if line.startswith('+') and not line.startswith('+++'):
                html_parts.append(
                    f'<div style="background: {T.SUCCESS}15; color: {T.SUCCESS}; '
                    f'border-left: 3px solid {T.SUCCESS}; padding: 0 8px;">'
                    f'{line_escaped}</div>'
                )
            elif line.startswith('-') and not line.startswith('---'):
                html_parts.append(
                    f'<div style="background: {T.ERROR}15; color: {T.ERROR}; '
                    f'border-left: 3px solid {T.ERROR}; padding: 0 8px;">'
                    f'{line_escaped}</div>'
                )
            elif line.startswith('@@'):
                html_parts.append(
                    f'<div style="background: {T.BRAND_LEMON}15; color: {T.BRAND_LEMON}; '
                    f'padding: 0 8px;">{line_escaped}</div>'
                )
            else:
                html_parts.append(f'<div>{line_escaped}</div>')

        html_parts.append('</div>')
        return ''.join(html_parts)
