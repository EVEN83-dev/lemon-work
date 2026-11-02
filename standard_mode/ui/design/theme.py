# -*- coding: utf-8 -*-
"""Lemon Agent 全局QSS主题表
所属窗口: 全局  品牌组件: LemonTheme
令牌引用: Lemon.PRIMARY/SECONDARY/BG/SURFACE/BORDER/BORDER_HOVER/SUCCESS/ERROR
           Lemon.SP_*/R_*/FS_*/FONT/DUR_*
"""
from .tokens import Lemon, LemonDark, tokens, set_theme, is_dark_theme


def _t() -> type:
    return tokens()


try:
    from PyQt5.QtCore import QObject, pyqtSignal

    class ThemeManager(QObject):
        """v6.0-S B-3: 全局主题管理器，深色/浅色切换+信号广播。"""
        theme_changed = pyqtSignal(bool)

        _instance = None

        @classmethod
        def instance(cls):
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

        def __init__(self, parent=None):
            super().__init__(parent)
            self._dark = is_dark_theme()

        def is_dark(self) -> bool:
            return self._dark

        def toggle(self) -> None:
            self._dark = not self._dark
            set_theme(self._dark)
            self.theme_changed.emit(self._dark)

        def apply_dark(self, dark: bool) -> None:
            if dark != self._dark:
                self._dark = dark
                set_theme(dark)
                self.theme_changed.emit(dark)

except Exception:
    class ThemeManager:
        """Fallback when PyQt5 unavailable."""
        _instance = None

        @classmethod
        def instance(cls):
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

        def is_dark(self):
            return True

        def toggle(self):
            pass

        def apply_dark(self, dark):
            pass


def global_qss() -> str:
    T = _t()
    return f"""
/* ===== QScrollBar ===== */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {T.SCROLLBAR_THUMB};
    min-height: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {T.SCROLLBAR_THUMB_HOVER};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {T.SCROLLBAR_THUMB};
    min-width: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {T.SCROLLBAR_THUMB_HOVER};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ===== QFrame#lemonCard ===== */
QFrame#lemonCard {{
    background: {T.BG};
    border: 1px solid {T.BORDER};
    border-radius: {T.R_M}px;
    padding: {T.SP_M}px;
}}
QFrame#lemonCard:hover {{
    border: 1px solid {T.BORDER_HOVER};
}}

/* ===== QLabel#caption ===== */
QLabel#caption {{
    color: {T.SECONDARY};
    font-size: {T.FS_CAPTION}px;
}}

/* ===== QLabel#bodyText ===== */
QLabel#bodyText {{
    color: {T.PRIMARY};
    font-size: {T.FS_BODY}px;
    line-height: 1.6;
}}

/* ===== QLabel#titleText ===== */
QLabel#titleText {{
    color: {T.PRIMARY};
    font-size: {T.FS_TITLE}px;
    font-weight: bold;
}}

/* ===== QLineEdit / QTextEdit ===== */
QLineEdit, QTextEdit {{
    border: 1px solid {T.BORDER};
    border-radius: {T.R_S}px;
    padding: {T.SP_S}px {T.SP_M}px;
    background: {T.BG};
    color: {T.PRIMARY};
    font-size: {T.FS_BODY}px;
    selection-background-color: {T.BRAND_LEMON}44;
}}
QLineEdit:focus, QTextEdit:focus {{
    border: 1px solid {T.PRIMARY};
}}

/* ===== QPushButton (通用) ===== */
QPushButton {{
    border: 1px solid {T.BORDER};
    border-radius: {T.R_S}px;
    padding: {T.SP_S}px {T.SP_M}px;
    background: transparent;
    color: {T.PRIMARY};
    font-size: {T.FS_BODY}px;
}}
QPushButton:hover {{
    background: {T.SURFACE};
}}
QPushButton:pressed {{
    background: {T.BORDER};
}}

/* ===== QPushButton#primaryBtn ===== */
QPushButton#primaryBtn {{
    background: {T.PRIMARY};
    color: {T.BG};
    border: none;
    font-weight: bold;
}}
QPushButton#primaryBtn:hover {{
    background: {T.BORDER_HOVER};
}}
QPushButton#primaryBtn:pressed {{
    background: {T.PRIMARY};
}}

/* ===== QPushButton#ghostBtn (幽灵按钮) ===== */
QPushButton#ghostBtn {{
    border: none;
    background: transparent;
    color: {T.SECONDARY};
    font-size: {T.FS_CAPTION}px;
    padding: {T.SP_S}px;
}}
QPushButton#ghostBtn:hover {{
    background: {T.SURFACE};
    color: {T.PRIMARY};
}}

/* ===== QToolButton ===== */
QToolButton {{
    border: 1px solid {T.BORDER};
    border-radius: {T.R_S}px;
    padding: {T.SP_S}px;
    background: transparent;
    color: {T.PRIMARY};
}}
QToolButton:hover {{
    background: {T.SURFACE};
}}

/* ===== QComboBox ===== */
QComboBox {{
    border: 1px solid {T.BORDER};
    border-radius: {T.R_S}px;
    padding: {T.SP_S}px {T.SP_M}px;
    background: {T.BG};
    color: {T.PRIMARY};
    font-size: {T.FS_BODY}px;
}}
QComboBox:focus {{
    border: 1px solid {T.PRIMARY};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

/* ===== QTabWidget / QTabBar ===== */
QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: {T.SP_S}px {T.SP_M}px;
    color: {T.SECONDARY};
    font-size: {T.FS_BODY}px;
}}
QTabBar::tab:selected {{
    color: {T.PRIMARY};
    border-bottom: 2px solid {T.PRIMARY};
}}
QTabBar::tab:hover {{
    color: {T.PRIMARY};
}}

/* ===== QSplitter ===== */
QSplitter::handle {{
    background: {T.BORDER};
    width: 1px;
}}
QSplitter::handle:hover {{
    background: {T.BORDER_HOVER};
}}

/* ===== QToolTip ===== */
QToolTip {{
    background: {T.PRIMARY};
    color: {T.BG};
    border: none;
    padding: {T.SP_S}px;
    font-size: {T.FS_CAPTION}px;
}}

/* ===== QMenu ===== */
QMenu {{
    background: {T.BG};
    border: 1px solid {T.BORDER};
    padding: {T.SP_S}px 0;
}}
QMenu::item {{
    padding: {T.SP_S}px {T.SP_M}px;
    color: {T.PRIMARY};
    font-size: {T.FS_BODY}px;
}}
QMenu::item:selected {{
    background: {T.SURFACE};
}}

/* ===== QCheckBox ===== */
QCheckBox {{
    color: {T.PRIMARY};
    font-size: {T.FS_BODY}px;
    spacing: {T.SP_S}px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {T.BORDER};
    border-radius: 3px;
    background: {T.BG};
}}
QCheckBox::indicator:checked {{
    background: {T.PRIMARY};
    border: 1px solid {T.PRIMARY};
}}

/* ===== QProgressBar ===== */
QProgressBar {{
    border: none;
    border-radius: {T.R_S}px;
    background: {T.SURFACE};
    height: 4px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {T.PRIMARY};
    border-radius: {T.R_S}px;
}}

/* ===== ToolCardWidget (状态卡片) ===== */
QFrame#toolCardRunning {{
    background: {T.BG};
    border: 1px solid {T.BORDER};
    border-left: 3px solid {T.SECONDARY};
    border-radius: {T.R_S}px;
    padding: {T.SP_S}px {T.SP_M}px;
}}
QFrame#toolCardCompleted {{
    background: {T.BG};
    border: 1px solid {T.SUCCESS}33;
    border-left: 3px solid {T.SUCCESS};
    border-radius: {T.R_S}px;
    padding: {T.SP_S}px {T.SP_M}px;
}}
QFrame#toolCardFailed {{
    background: {T.BG};
    border: 1px solid {T.ERROR}33;
    border-left: 3px solid {T.ERROR};
    border-radius: {T.R_S}px;
    padding: {T.SP_S}px {T.SP_M}px;
}}
"""


def dark_qss() -> str:
    from .tokens import set_theme
    set_theme(dark=True)
    qss = global_qss()
    set_theme(dark=False)
    return qss
