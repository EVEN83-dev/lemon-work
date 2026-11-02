# -*- coding: utf-8 -*-
"""
GitStatusPanel — Git 状态实时同步面板
======================================
定时（5秒）或 Agent 操作文件后获取 git status，
渲染 Modified/Added/Deleted 文件列表。
与 RunRegistry Artifact 联动：新增 Artifact 高亮对应文件，
"丢弃修改"回滚文件并更新 Artifact 状态。
"""
from __future__ import annotations

import os
import subprocess
from typing import Dict, List, Optional, Set

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QWidget, QScrollArea, QFrame, QSizePolicy,
)

from ui.design.tokens import Lemon


_STATUS_ICONS = {
    "M": ("M", "#FF9100"),
    "A": ("A", "#00C853"),
    "D": ("D", "#FF1744"),
    "R": ("R", "#448AFF"),
    "C": ("C", "#B388FF"),
    "?": ("?", "#8A8A8A"),
    "!": ("!", "#666666"),
}


class _GitFileRow(QFrame):
    revert_requested = pyqtSignal(str)
    file_clicked = pyqtSignal(str)

    def __init__(self, file_path: str, status_code: str,
                 highlighted: bool = False, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self._init_ui(file_path, status_code, highlighted)

    def _init_ui(self, path: str, status: str, highlighted: bool):
        T = Lemon
        self.setObjectName("gitFileRow")
        bg = T.DARK_BG_3 if not highlighted else f"rgba(255,107,0,0.08)"
        self.setStyleSheet(
            f"QFrame#gitFileRow {{ background: {bg}; "
            f"border: none; border-radius: {T.R_S}px; }}"
            f"QFrame#gitFileRow:hover {{ background: {T.SURFACE}; }}"
        )
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.SP_S, 2, T.SP_S, 2)
        layout.setSpacing(T.SP_XS)

        code_char, code_color = _STATUS_ICONS.get(
            status[0] if status else "?",
            ("?", T.SECONDARY),
        )
        status_label = QLabel(code_char)
        status_label.setStyleSheet(
            f"color: {code_color}; font-size: {T.FS_CAPTION}px; "
            f"font-weight: bold; background: transparent; border: none;"
        )
        status_label.setFixedWidth(14)
        layout.addWidget(status_label)

        path_label = QLabel(path)
        path_label.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(path_label)

        if status[0] in ("M", "A"):
            revert_btn = QPushButton("丢弃")
            revert_btn.setCursor(Qt.PointingHandCursor)
            revert_btn.setFixedSize(36, 18)
            revert_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {T.TEXT_MUTED}; "
                f"border: 1px solid {T.BORDER}; border-radius: 3px; "
                f"font-size: 10px; font-family: '{T.FONT}'; }}"
                f"QPushButton:hover {{ color: {T.ERROR}; border-color: {T.ERROR}; }}"
            )
            revert_btn.clicked.connect(lambda: self.revert_requested.emit(self._file_path))
            layout.addWidget(revert_btn)


class GitStatusPanel(QWidget):
    revert_requested = pyqtSignal(str)
    file_clicked = pyqtSignal(str)
    status_refreshed = pyqtSignal(dict)

    REFRESH_INTERVAL_MS = 5000

    def __init__(self, project_path: str = "", parent=None):
        super().__init__(parent)
        self._project_path = project_path
        self._highlighted_paths: Set[str] = set()
        self._rows: Dict[str, _GitFileRow] = {}
        self._init_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(self.REFRESH_INTERVAL_MS)
        self.refresh()

    def _init_ui(self):
        T = Lemon
        self.setStyleSheet(f"background: {T.BG};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_S, T.SP_S, T.SP_S, T.SP_S)
        layout.setSpacing(T.SP_XS)

        header = QHBoxLayout()
        header.setSpacing(T.SP_S)
        title = QLabel("Git 状态")
        title.setStyleSheet(
            f"color: {T.DARK_TEXT_1}; font-size: {T.FS_SUB}px; "
            f"font-weight: bold; font-family: '{T.FONT}'; "
            f"background: transparent; border: none;"
        )
        header.addWidget(title)
        header.addStretch()

        refresh_btn = QPushButton("刷新")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setFixedSize(40, 20)
        refresh_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {T.TEXT_MUTED}; "
            f"border: 1px solid {T.BORDER}; border-radius: 3px; "
            f"font-size: 10px; font-family: '{T.FONT}'; }}"
            f"QPushButton:hover {{ color: {T.BRAND_ORANGE}; border-color: {T.BRAND_ORANGE}; }}"
        )
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {T.BG}; border: none; }}")

        self._container = QWidget()
        self._container.setStyleSheet(f"background: {T.BG};")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(1)
        self._container_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        self._empty_label = QLabel("工作区干净")
        self._empty_label.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        self._empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._empty_label)

    def refresh(self) -> None:
        status_data = self._get_git_status()
        self._render_status(status_data)
        self.status_refreshed.emit(status_data)

    def _get_git_status(self) -> Dict[str, str]:
        result = {}
        if not self._project_path or not os.path.isdir(self._project_path):
            return result
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain=v1"],
                cwd=self._project_path,
                capture_output=True, text=True, timeout=5,
            )
            for line in proc.stdout.strip().split("\n"):
                if not line or len(line) < 4:
                    continue
                status = line[:2].strip()
                path = line[3:].strip()
                if path:
                    result[path] = status
        except Exception:
            pass
        return result

    def _render_status(self, status_data: Dict[str, str]) -> None:
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        has_changes = bool(status_data)
        self._empty_label.setVisible(not has_changes)
        self._scroll.setVisible(has_changes)

        for path, status in status_data.items():
            highlighted = path in self._highlighted_paths
            row = _GitFileRow(path, status, highlighted, self._container)
            row.revert_requested.connect(self._on_revert)
            row.file_clicked.connect(self.file_clicked.emit)
            self._rows[path] = row
            self._container_layout.addWidget(row)

    def highlight_artifact_paths(self, paths: List[str]) -> None:
        self._highlighted_paths = set(paths)
        self.refresh()

    def _on_revert(self, file_path: str) -> None:
        if not self._project_path:
            return
        try:
            subprocess.run(
                ["git", "checkout", "--", file_path],
                cwd=self._project_path,
                capture_output=True, timeout=10,
            )
        except Exception:
            pass
        self.revert_requested.emit(file_path)
        self.refresh()

    def set_project_path(self, path: str) -> None:
        self._project_path = path
        self.refresh()
