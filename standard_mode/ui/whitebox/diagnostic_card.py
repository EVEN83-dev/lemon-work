# -*- coding: utf-8 -*-
"""
DiagnosticCard — LSP 诊断修复建议卡片
======================================
当 Agent 修改文件后触发 LSP 诊断，发现 Error 级别问题时弹出此卡片。
展示错误列表 + Agent 建议修复方案 + [应用修复] / [忽略] 按钮。
"""
from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget, QFrame,
)

from ui.design.tokens import Lemon


class DiagnosticCard(QFrame):
    fix_requested = pyqtSignal(str, list)
    dismissed = pyqtSignal(str)

    def __init__(self, file_path: str, diagnostics: list,
                 fix_suggestion: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._file_path = file_path
        self._diagnostics = diagnostics
        self._fix_suggestion = fix_suggestion
        self._init_ui(file_path, diagnostics, fix_suggestion)

    def _init_ui(self, file_path: str, diagnostics: list,
                 fix_suggestion: str):
        T = Lemon
        error_count = sum(1 for d in diagnostics
                          if d.get("severity", 1) <= 1)
        self.setObjectName("diagnosticCard")
        self.setStyleSheet(
            f"QFrame#diagnosticCard {{ background: {T.ERROR_BG_DARK}; "
            f"border: 1px solid {T.ERROR_BORDER_DARK}; "
            f"border-left: 4px solid {T.ERROR}; "
            f"border-radius: {T.R_M}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(T.SP_XS)

        row1 = QHBoxLayout()
        row1.setSpacing(T.SP_S)
        header = QLabel(f"LSP 诊断: {error_count} 个错误")
        header.setStyleSheet(
            f"color: {T.ERROR}; font-size: {T.FS_SUB}px; "
            f"font-weight: bold; font-family: '{T.FONT}'; "
            f"background: transparent; border: none;"
        )
        row1.addWidget(header)
        row1.addStretch()
        layout.addLayout(row1)

        file_label = QLabel(os_path_basename(file_path))
        file_label.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        layout.addWidget(file_label)

        for diag in diagnostics[:5]:
            severity = diag.get("severity", 2)
            msg = diag.get("message", "未知错误")[:80]
            line = diag.get("line", "?")
            color = T.ERROR if severity <= 1 else T.ACCENT_ORANGE if severity == 2 else T.SECONDARY
            err_label = QLabel(f"L{line}: {msg}")
            err_label.setStyleSheet(
                f"color: {color}; font-size: {T.FS_CAPTION}px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            layout.addWidget(err_label)

        if len(diagnostics) > 5:
            more = QLabel(f"...还有 {len(diagnostics) - 5} 个问题")
            more.setStyleSheet(
                f"color: {T.TEXT_MUTED}; font-size: {T.FS_CAPTION}px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            layout.addWidget(more)

        if fix_suggestion:
            sug_label = QLabel(f"建议: {fix_suggestion[:120]}")
            sug_label.setWordWrap(True)
            sug_label.setStyleSheet(
                f"color: {T.ACCENT_GREEN}; font-size: {T.FS_CAPTION}px; "
                f"font-family: '{T.FONT}'; background: transparent; border: none;"
            )
            layout.addWidget(sug_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(T.SP_S)
        btn_row.addStretch()

        dismiss_btn = QPushButton("忽略")
        dismiss_btn.setCursor(Qt.PointingHandCursor)
        dismiss_btn.setFixedHeight(26)
        dismiss_btn.setStyleSheet(
            f"QPushButton {{ background: {T.SURFACE}; color: {T.SECONDARY}; "
            f"border: 1px solid {T.BORDER}; border-radius: {T.R_S}px; "
            f"padding: 0 {T.SP_M}px; font-family: '{T.FONT}'; font-size: {T.FS_CAPTION}px; }}"
            f"QPushButton:hover {{ border-color: {T.BRAND_ORANGE}; }}"
        )
        dismiss_btn.clicked.connect(lambda: self._on_dismiss())
        btn_row.addWidget(dismiss_btn)

        fix_btn = QPushButton("应用修复")
        fix_btn.setCursor(Qt.PointingHandCursor)
        fix_btn.setFixedHeight(26)
        fix_btn.setStyleSheet(
            f"QPushButton {{ background: {T.SUCCESS_BG_DARK}; color: {T.SUCCESS}; "
            f"border: 1px solid {T.SUCCESS_BORDER_DARK}; border-radius: {T.R_S}px; "
            f"padding: 0 {T.SP_M}px; font-family: '{T.FONT}'; font-size: {T.FS_CAPTION}px; }}"
            f"QPushButton:hover {{ background: {T.SUCCESS}; color: white; }}"
        )
        fix_btn.clicked.connect(lambda: self._on_fix())
        btn_row.addWidget(fix_btn)

        layout.addLayout(btn_row)

    def _on_fix(self):
        self.fix_requested.emit(self._file_path, self._diagnostics)
        self.setParent(None)
        self.deleteLater()

    def _on_dismiss(self):
        self.dismissed.emit(self._file_path)
        self.setParent(None)
        self.deleteLater()


def os_path_basename(path: str) -> str:
    import os
    return os.path.basename(path) if path else ""
