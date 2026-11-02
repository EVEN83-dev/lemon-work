# -*- coding: utf-8 -*-
"""
V6.0 6.1: DiffApprovalDialog — Side-by-side diff viewer with Accept/Reject
for Agent file operations. Wraps existing SideBySideDiffEditor.
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from PyQt5.QtGui import QFont

from ui.design.tokens import Lemon

try:
    from ui.diff_editor import SideBySideDiffEditor
    _HAS_DIFF_EDITOR = True
except Exception:
    _HAS_DIFF_EDITOR = False


class DiffApprovalDialog(QDialog):
    accepted = pyqtSignal(str, str)
    rejected = pyqtSignal(str)

    def __init__(self, file_path: str, old_content: str, new_content: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._file_path = file_path
        self._new_content = new_content
        self.setWindowTitle("代码变更审查 — " + file_path)
        self.setMinimumSize(900, 500)
        self.resize(1200, 700)
        self.setStyleSheet(
            "QDialog { background: " + Lemon.BG + "; color: " + Lemon.DARK_TEXT_1 + "; }"
        )
        self._init_ui(file_path, old_content, new_content)

    def _init_ui(self, file_path: str, old_content: str, new_content: str) -> None:
        T = Lemon
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_M, T.SP_M, T.SP_M)
        layout.setSpacing(T.SP_S)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        file_label = QLabel(file_path)
        file_label.setStyleSheet(
            "color: " + T.ACCENT_BLUE + "; font-size: " + str(T.FS_SUB) + "px; font-weight: bold;"
        )
        header_layout.addWidget(file_label)

        old_lines = old_content.count('\n') + 1
        new_lines = new_content.count('\n') + 1
        added = max(0, new_lines - old_lines)
        removed = max(0, old_lines - new_lines)
        stats = "+" + str(added) + " -" + str(removed) + " lines"
        stats_label = QLabel(stats)
        stats_label.setStyleSheet(
            "color: " + T.SECONDARY + "; font-size: " + str(T.FS_CAPTION) + "px;"
        )
        header_layout.addWidget(stats_label)
        header_layout.addStretch()
        layout.addWidget(header)

        if _HAS_DIFF_EDITOR:
            self._diff_editor = SideBySideDiffEditor(self)
            self._diff_editor.set_diff(old_content, new_content, file_path)
            layout.addWidget(self._diff_editor, 1)
        else:
            fallback = QLabel("Diff 编辑器不可用（diff_editor.py 导入失败）")
            fallback.setStyleSheet("color: " + T.ERROR + "; padding: 40px;")
            layout.addWidget(fallback, 1)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, T.SP_S, 0, 0)

        footer_layout.addStretch()

        reject_btn = QPushButton("拒绝 (Reject)")
        reject_btn.setFixedSize(140, 36)
        reject_btn.setStyleSheet(
            "QPushButton { background: " + T.ERROR + "; color: #fff; border: none; "
            "border-radius: 6px; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background: " + T.ACCENT_RED + "; }"
        )
        reject_btn.clicked.connect(self._on_reject)
        footer_layout.addWidget(reject_btn)

        accept_btn = QPushButton("接受 (Accept)")
        accept_btn.setFixedSize(140, 36)
        accept_btn.setStyleSheet(
            "QPushButton { background: " + T.SUCCESS + "; color: #000; border: none; "
            "border-radius: 6px; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background: " + T.ACCENT_GREEN + "; }"
        )
        accept_btn.clicked.connect(self._on_accept)
        footer_layout.addWidget(accept_btn)

        layout.addWidget(footer)

    def _on_accept(self) -> None:
        self.accepted.emit(self._file_path, self._new_content)
        self.accept()

    def _on_reject(self) -> None:
        self.rejected.emit(self._file_path)
        self.reject()
