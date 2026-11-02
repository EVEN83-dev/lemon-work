# -*- coding: utf-8 -*-
"""
终端分屏容器 — 支持纵向/横向拆分多个 pane
================================================
对标 PyCharm JediTerm split：每个 pane 独立绑定 ShellBridge 会话。

架构：
  TerminalSplitContainer
    -> QSplitter (纵向/横向)
      -> TerminalPane (单个 pane = SimpleTerminalPanel + 分屏控制条)
        -> SimpleTerminalPanel
        -> PaneControlBar (拆分/关闭按钮)

用法：
  container = TerminalSplitContainer(cwd="D:/project")
  container.split_horizontal()  # 横向拆分
  container.split_vertical()    # 纵向拆分
"""
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QFrame, QPushButton, QToolButton, QLabel, QMenu, QAction,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView

try:
    from ui.theme import *
except ImportError:
    from standard_mode.ui.theme import *
try:
    from ui.terminal_panel_simple import SimpleTerminalPanel
except ImportError:
    from standard_mode.ui.terminal_panel_simple import SimpleTerminalPanel


class PaneControlBar(QFrame):
    """单个 pane 顶部控制条：拆分/关闭"""

    split_requested = pyqtSignal(str)  # 'horizontal' | 'vertical'
    close_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setStyleSheet(f"background: {BG_SECONDARY}; border-bottom: 1px solid {BORDER_SUBTLE};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(4)

        self.btn_split_v = QToolButton()
        self.btn_split_v.setText("||")
        self.btn_split_v.setToolTip("纵向拆分")
        self.btn_split_v.setFixedSize(22, 18)
        self.btn_split_v.setStyleSheet(f"""
            QToolButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 3px;
                font-size: 10px;
            }}
            QToolButton:hover {{ color: {XIAOMI_ORANGE}; border-color: {XIAOMI_ORANGE}; }}
        """)
        self.btn_split_v.clicked.connect(lambda: self.split_requested.emit('vertical'))
        layout.addWidget(self.btn_split_v)

        self.btn_split_h = QToolButton()
        self.btn_split_h.setText("=")
        self.btn_split_h.setToolTip("横向拆分")
        self.btn_split_h.setFixedSize(22, 18)
        self.btn_split_h.setStyleSheet(f"""
            QToolButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 3px;
                font-size: 10px;
            }}
            QToolButton:hover {{ color: {XIAOMI_ORANGE}; border-color: {XIAOMI_ORANGE}; }}
        """)
        self.btn_split_h.clicked.connect(lambda: self.split_requested.emit('horizontal'))
        layout.addWidget(self.btn_split_h)

        layout.addStretch()

        self.btn_close = QToolButton()
        self.btn_close.setText("x")
        self.btn_close.setToolTip("关闭窗格")
        self.btn_close.setFixedSize(22, 18)
        self.btn_close.setStyleSheet(f"""
            QToolButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 3px;
                font-size: 10px;
            }}
            QToolButton:hover {{ color: {ERROR}; border-color: {ERROR}; }}
        """)
        self.btn_close.clicked.connect(self.close_requested.emit)
        layout.addWidget(self.btn_close)


class TerminalPane(QWidget):
    """单个终端窗格 = 控制条 + SimpleTerminalPanel"""

    split_requested = pyqtSignal(str, object)  # direction, source_pane
    close_requested = pyqtSignal(object)        # source_pane

    def __init__(self, cwd=None, parent=None):
        super().__init__(parent)
        self._cwd = cwd or os.getcwd()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._control_bar = PaneControlBar(self)
        self._control_bar.split_requested.connect(self._on_split)
        self._control_bar.close_requested.connect(lambda: self.close_requested.emit(self))
        layout.addWidget(self._control_bar)

        self._terminal = SimpleTerminalPanel()
        self._terminal.set_cwd(self._cwd)
        layout.addWidget(self._terminal, 1)

    def _on_split(self, direction):
        self.split_requested.emit(direction, self)

    @property
    def terminal(self):
        return self._terminal

    @property
    def cwd(self):
        return self._cwd

    def set_cwd(self, path):
        self._cwd = path
        self._terminal.set_cwd(path)

    def shutdown(self):
        self._terminal.shutdown()


class TerminalSplitContainer(QWidget):
    """终端分屏容器 — 管理多个 TerminalPane 的拆分/关闭"""

    pane_count_changed = pyqtSignal(int)

    def __init__(self, cwd=None, parent=None):
        super().__init__(parent)
        self._cwd = cwd or os.getcwd()
        self._panes = []
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"background: {BG_PRIMARY};")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {BORDER_SUBTLE};
                width: 2px;
            }}
            QSplitter::handle:hover {{
                background: {XIAOMI_ORANGE};
            }}
        """)
        self._layout.addWidget(self._splitter)

        self._add_pane()

    def _add_pane(self, direction=None, source_pane=None):
        pane = TerminalPane(cwd=self._cwd)
        pane.split_requested.connect(self._on_split_requested)
        pane.close_requested.connect(self._on_close_requested)

        if direction and source_pane:
            idx = self._splitter.indexOf(source_pane)
            if direction == 'vertical':
                if self._splitter.orientation() == Qt.Horizontal:
                    inner = self._splitter.widget(idx)
                    if isinstance(inner, QSplitter) and inner.orientation() == Qt.Vertical:
                        inner.addWidget(pane)
                    else:
                        vs = QSplitter(Qt.Vertical)
                        vs.setStyleSheet(self._splitter.styleSheet())
                        existing = self._splitter.widget(idx)
                        self._splitter.replaceWidget(idx, vs)
                        vs.addWidget(existing)
                        vs.addWidget(pane)
                        vs.setSizes([vs.height() // 2, vs.height() // 2])
                else:
                    self._splitter.addWidget(pane)
            elif direction == 'horizontal':
                if self._splitter.orientation() == Qt.Vertical:
                    inner = self._splitter.widget(idx)
                    if isinstance(inner, QSplitter) and inner.orientation() == Qt.Horizontal:
                        inner.addWidget(pane)
                    else:
                        hs = QSplitter(Qt.Horizontal)
                        hs.setStyleSheet(self._splitter.styleSheet())
                        existing = self._splitter.widget(idx)
                        self._splitter.replaceWidget(idx, hs)
                        hs.addWidget(existing)
                        hs.addWidget(pane)
                        hs.setSizes([hs.width() // 2, hs.width() // 2])
                else:
                    self._splitter.addWidget(pane)
        else:
            self._splitter.addWidget(pane)

        self._panes.append(pane)
        self._equalize_sizes()
        self.pane_count_changed.emit(len(self._panes))

    def _on_split_requested(self, direction, source_pane):
        self._add_pane(direction, source_pane)

    def _on_close_requested(self, source_pane):
        if len(self._panes) <= 1:
            return
        source_pane.shutdown()
        self._splitter.removeWidget(source_pane)
        source_pane.deleteLater()
        self._panes.remove(source_pane)
        self._equalize_sizes()
        self.pane_count_changed.emit(len(self._panes))

    def _equalize_sizes(self):
        n = self._splitter.count()
        if n <= 0:
            return
        total = self._splitter.width() if self._splitter.orientation() == Qt.Horizontal else self._splitter.height()
        if total <= 0:
            total = 600
        per = total // n
        self._splitter.setSizes([per] * n)

    def split_horizontal(self):
        if self._panes:
            self._add_pane('horizontal', self._panes[-1])
        else:
            self._add_pane()

    def split_vertical(self):
        if self._panes:
            self._add_pane('vertical', self._panes[-1])
        else:
            self._add_pane()

    @property
    def pane_count(self):
        return len(self._panes)

    @property
    def active_terminal(self):
        if self._panes:
            return self._panes[0].terminal
        return None

    def shutdown(self):
        for p in self._panes:
            p.shutdown()
        self._panes.clear()
