# -*- coding: utf-8 -*-
"""
Activity Bar — 左侧活动栏（图标导航栏）

简笔画风格图标，通过 QPainter 绘制，保持风格统一。
仅显示图标，无文字标签。

信号:
    activity_changed(str): 活动切换，值为活动ID
"""

import os
import sys
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QFrame, QLabel
from PyQt5.QtCore import pyqtSignal, Qt

sys.path.insert(0, os.path.dirname(__file__))
from theme import (
    BG_ROOT, BG_SURFACE_HOVER, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_TERTIARY, LEMON_ORANGE, svg_to_pixmap,
)

ICON_SIZE = 40              # ★ v3.92: 图标放大，与 VSCode 视觉量级一致
BTN_SIZE = 64                # ★ v3.92: 按钮尺寸同步放大

# ★ W3 图标大一统：活动栏图标名 → theme.SVG_ICONS 图标名映射。
# 原 QPainter 手绘（files/search/git/run/test/extensions/settings）与 theme 的
# 极简线条 SVG 体系是两套独立实现，现统一改为 theme 渲染。
_ACTIVITY_ICON_MAP = {
    "files": "folder",
    "search": "search",
    "git": "git",
    "run": "run",
    "test": "flask",
    "extensions": "grid",
    "settings": "settings",
}


class IconLabel(QLabel):
    """极简线条 SVG 图标标签（复用 theme.svg_to_pixmap 统一渲染）"""

    def __init__(self, icon_name, color=TEXT_TERTIARY, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._color = color
        self.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.setAlignment(Qt.AlignCenter)
        self._refresh()

    def set_color(self, color):
        self._color = color
        self._refresh()

    def _refresh(self):
        svg_name = _ACTIVITY_ICON_MAP.get(self._icon_name, self._icon_name)
        pixmap = svg_to_pixmap(svg_name, size=ICON_SIZE, color=self._color)
        if pixmap is not None:
            self.setPixmap(pixmap)
        else:
            self.setText(self._icon_name)


class ActivityBarButton(QPushButton):
    """活动栏按钮 — 仅图标，无文字"""

    def __init__(self, icon_name, tooltip, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setFixedSize(BTN_SIZE, BTN_SIZE)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setStyleSheet(self._style(False))

        # 图标
        self._icon_label = IconLabel(icon_name, TEXT_TERTIARY, self)
        self._icon_label.move(12, 12)
        self._icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.clicked.connect(lambda: self.setChecked(True))

    def _style(self, active):
        if active:
            return f"""
                QPushButton {{
                    background: {BG_ROOT};
                    border: none;
                    border-left: 2px solid {LEMON_ORANGE};
                    border-radius: 0;
                }}
                QPushButton:hover {{
                    background: {BG_SURFACE_HOVER};
                }}
            """
        else:
            return f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-left: 2px solid transparent;
                    border-radius: 0;
                }}
                QPushButton:hover {{
                    background: {BG_SURFACE_HOVER};
                }}
                QPushButton:checked {{
                    background: {BG_ROOT};
                    border-left: 2px solid {LEMON_ORANGE};
                }}
            """

    def set_active(self, active):
        self.setChecked(active)
        self.setStyleSheet(self._style(active))
        color = TEXT_PRIMARY if active else TEXT_TERTIARY
        self._icon_label.set_color(color)


# 活动定义（仅图标，无文字标签）
ACTIVITIES = [
    ("files", "资源管理器 (Ctrl+Shift+E)"),
    ("search", "搜索 (Ctrl+Shift+F)"),
    ("git", "源码管理 (Ctrl+Shift+G)"),
    ("run", "运行和调试 (Ctrl+Shift+D)"),
    ("test", "测试 (Ctrl+Shift+T)"),
    ("extensions", "扩展 (Ctrl+Shift+X)"),
]

BOTTOM_ACTIVITIES = [
    ("settings", "设置 (Ctrl+,)"),
]

# 活动 ID 映射
ACTIVITY_IDS = {
    "files": "explorer",
    "search": "search",
    "git": "source_control",
    "run": "run_debug",
    "test": "testing",
    "extensions": "extensions",
    "settings": "settings",
}


class ActivityBar(QWidget):
    """左侧活动栏 — 简笔画图标导航

    信号:
        activity_changed(str): 活动 ID 变化
    """

    activity_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = "explorer"
        self._buttons = {}
        self._init_ui()

    def _init_ui(self):
        self.setFixedWidth(BTN_SIZE)
        self.setStyleSheet(f"background: {BG_ROOT}; border-right: 1px solid {BORDER_SUBTLE};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignTop)

        # 顶部活动按钮
        for icon_name, tooltip in ACTIVITIES:
            btn = ActivityBarButton(icon_name, tooltip, self)
            aid = ACTIVITY_IDS[icon_name]
            btn.clicked.connect(lambda _, a=aid: self._on_activity(a))
            self._buttons[aid] = btn
            layout.addWidget(btn)

        # 弹性空间
        layout.addStretch()

        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet(f"background: {BORDER_SUBTLE}; max-height: 1px; margin: 4px 8px;")
        layout.addWidget(separator)

        # 底部活动按钮
        for icon_name, tooltip in BOTTOM_ACTIVITIES:
            btn = ActivityBarButton(icon_name, tooltip, self)
            aid = ACTIVITY_IDS[icon_name]
            btn.clicked.connect(lambda _, a=aid: self._on_activity(a))
            self._buttons[aid] = btn
            layout.addWidget(btn)

        # 默认选中资源管理器
        if "explorer" in self._buttons:
            self._buttons["explorer"].set_active(True)

    def _on_activity(self, activity_id):
        if activity_id == self._current:
            return
        self._current = activity_id
        for aid, btn in self._buttons.items():
            btn.set_active(aid == activity_id)
        self.activity_changed.emit(activity_id)

    def get_current(self):
        return self._current

    def set_activity(self, activity_id):
        if activity_id in self._buttons:
            self._on_activity(activity_id)
