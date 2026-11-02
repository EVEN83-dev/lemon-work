# -*- coding: utf-8 -*-
"""
终端快捷键自定义面板
====================
弹窗式快捷键编辑器，支持按键录制、冲突检测、即时保存。
"""
import json
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox,
)
from PyQt5.QtGui import QKeyEvent, QFont

try:
    from ui.theme import *
except ImportError:
    from standard_mode.ui.theme import *
try:
    from ui.terminal_config import load_shortcuts, save_shortcuts, DEFAULT_SHORTCUTS, SHORTCUT_LABELS
except ImportError:
    from standard_mode.ui.terminal_config import load_shortcuts, save_shortcuts, DEFAULT_SHORTCUTS, SHORTCUT_LABELS


class ShortcutEditWidget(QLabel):
    """可录制按键的标签控件"""

    shortcut_changed = pyqtSignal(str)

    def __init__(self, current: str = "", parent=None):
        super().__init__(current or "点击录制...", parent)
        self._recording = False
        self._keys = []
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(28)
        self._update_style()

    def _update_style(self):
        if self._recording:
            self.setStyleSheet(f"""
                background: {XIAOMI_ORANGE}22; color: {XIAOMI_ORANGE};
                border: 2px solid {XIAOMI_ORANGE}; border-radius: 4px;
                font-family: "JetBrains Mono","Consolas",monospace; font-size: 11px;
            """)
            self.setText("按键录制中...")
        else:
            self.setStyleSheet(f"""
                background: {BG_PRIMARY}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 4px;
                font-family: "JetBrains Mono","Consolas",monospace; font-size: 11px;
            """)

    def mousePressEvent(self, event):
        self._recording = True
        self._keys = []
        self._update_style()
        self.setFocus()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        if not self._recording:
            return super().keyPressEvent(event)
        if event.key() == Qt.Key_Escape:
            self._recording = False
            self._update_style()
            return
        parts = []
        if event.modifiers() & Qt.ControlModifier:
            parts.append("Ctrl")
        if event.modifiers() & Qt.ShiftModifier:
            parts.append("Shift")
        if event.modifiers() & Qt.AltModifier:
            parts.append("Alt")
        key = event.key()
        if key not in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            from PyQt5.QtCore import QKeyCombination
            name = QKeyCombination(event.modifiers(), event.key()).toString()
            if not parts and name:
                self.setText(name)
            elif parts:
                parts.append(name.split("+")[-1] if "+" in name else name)
                self.setText("+".join(parts))
            self._recording = False
            self._update_style()
            self.shortcut_changed.emit(self.text())
        event.accept()

    def focusOutEvent(self, event):
        if self._recording:
            self._recording = False
            self._update_style()
        super().focusOutEvent(event)


class ShortcutEditPanel(QDialog):
    """终端快捷键设置弹窗"""

    shortcuts_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("终端快捷键设置")
        self.setMinimumSize(520, 440)
        self.setStyleSheet(f"background: {BG_SECONDARY}; color: {TEXT_PRIMARY};")

        self._shortcuts = load_shortcuts()
        self._editors = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("快捷键自定义")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: bold; background: transparent;")
        layout.addWidget(title)

        hint = QLabel("点击快捷键列开始录制，按新组合键替换，Esc 取消")
        hint.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px; background: transparent;")
        layout.addWidget(hint)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["功能", "快捷键", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background: {BG_PRIMARY}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_SUBTLE}; gridline-color: {BORDER_SUBTLE};
                font-size: 12px;
            }}
            QHeaderView::section {{
                background: {BG_SECONDARY}; color: {TEXT_TERTIARY};
                border: none; padding: 6px; font-size: 11px;
            }}
        """)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_reset = QPushButton("恢复默认")
        btn_reset.setFixedSize(80, 30)
        btn_reset.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 4px;
            }}
            QPushButton:hover {{ color: {XIAOMI_ORANGE}; border-color: {XIAOMI_ORANGE}; }}
        """)
        btn_reset.clicked.connect(self._reset_defaults)
        btn_row.addWidget(btn_reset)

        btn_save = QPushButton("保存")
        btn_save.setFixedSize(80, 30)
        btn_save.setStyleSheet(f"""
            QPushButton {{
                background: {XIAOMI_ORANGE}; color: white;
                border: none; border-radius: 4px; font-weight: bold;
            }}
            QPushButton:hover {{ background: #e55a2b; }}
        """)
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)

        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedSize(80, 30)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 4px;
            }}
            QPushButton:hover {{ color: {TEXT_PRIMARY}; border-color: {TEXT_PRIMARY}; }}
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        layout.addLayout(btn_row)
        self._populate_table()

    def _populate_table(self):
        self._table.setRowCount(len(DEFAULT_SHORTCUTS))
        self._editors = {}
        for row, (key, default) in enumerate(DEFAULT_SHORTCUTS.items()):
            label = SHORTCUT_LABELS.get(key, key)
            label_item = QTableWidgetItem(label)
            label_item.setFlags(Qt.ItemIsEnabled)
            self._table.setItem(row, 0, label_item)

            current = self._shortcuts.get(key, default)
            editor = ShortcutEditWidget(current)
            editor.shortcut_changed.connect(lambda v, k=key: self._on_shortcut_changed(k, v))
            self._editors[key] = editor
            self._table.setCellWidget(row, 1, editor)

            reset_btn = QPushButton("重置")
            reset_btn.setFixedSize(44, 24)
            reset_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {TEXT_TERTIARY};
                    border: 1px solid {BORDER_SUBTLE}; border-radius: 3px; font-size: 10px;
                }}
                QPushButton:hover {{ color: {XIAOMI_ORANGE}; border-color: {XIAOMI_ORANGE}; }}
            """)
            reset_btn.clicked.connect(lambda _, k=key, d=default, r=row: self._reset_one(k, d, r))
            self._table.setCellWidget(row, 2, reset_btn)

    def _on_shortcut_changed(self, key: str, value: str):
        self._shortcuts[key] = value
        conflicts = [k for k, v in self._shortcuts.items() if v == value and k != key]
        if conflicts:
            QMessageBox.warning(self, "快捷键冲突",
                                f"快捷键 {value} 已被 {SHORTCUT_LABELS.get(conflicts[0], conflicts[0])} 使用")

    def _reset_one(self, key: str, default: str, row: int):
        self._shortcuts[key] = default
        editor = self._editors.get(key)
        if editor:
            editor.setText(default)

    def _reset_defaults(self):
        self._shortcuts = dict(DEFAULT_SHORTCUTS)
        self._populate_table()

    def _save(self):
        save_shortcuts(self._shortcuts)
        self.shortcuts_changed.emit(self._shortcuts)
        self.accept()
