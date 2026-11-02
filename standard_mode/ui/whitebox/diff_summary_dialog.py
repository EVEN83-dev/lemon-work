# -*- coding: utf-8 -*-
"""
DiffSummaryDialog — 变更汇总面板
==================================
从 RunRegistry 获取当前 Run 的所有 Artifact (kind=file_diff/file_created)，
列出文件级变更，支持单个接受/拒绝和批量操作。
拒绝时调用 Git checkout 回滚文件。
"""
from __future__ import annotations

import os
import subprocess
from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget, QScrollArea, QFrame, QSizePolicy,
)

from ui.design.tokens import Lemon
from ui.whitebox.state_model import (
    Artifact, ArtifactKind, RunRegistry,
)


class _ArtifactRow(QFrame):
    accepted = pyqtSignal(str)
    rejected = pyqtSignal(str)

    def __init__(self, artifact: Artifact, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._artifact = artifact
        self._status = "pending"
        self._init_ui(artifact)

    def _init_ui(self, art: Artifact):
        T = Lemon
        self.setObjectName("artifactRow")
        self.setStyleSheet(
            f"QFrame#artifactRow {{ background: {T.SURFACE}; "
            f"border: 1px solid {T.BORDER}; border-radius: {T.R_S}px; "
            f"padding: 0; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(T.SP_S)

        kind_icon = "✏️" if art.kind == ArtifactKind.FILE_DIFF else "📄"
        if art.kind == ArtifactKind.FILE_DELETED:
            kind_icon = "🗑️"
        icon_label = QLabel(kind_icon)
        icon_label.setStyleSheet(
            f"font-size: 14px; background: transparent; border: none;"
        )
        icon_label.setFixedWidth(20)
        layout.addWidget(icon_label)

        path_label = QLabel(art.title)
        path_label.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_BODY}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(path_label)

        self._status_label = QLabel("待处理")
        self._status_label.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        self._status_label.setFixedWidth(60)
        layout.addWidget(self._status_label)

        reject_btn = QPushButton("拒绝")
        reject_btn.setObjectName("rejectBtn")
        reject_btn.setCursor(Qt.PointingHandCursor)
        reject_btn.setFixedHeight(24)
        reject_btn.setStyleSheet(
            f"QPushButton#rejectBtn {{ background: {T.ERROR_BG_DARK}; "
            f"color: {T.ERROR}; border: 1px solid {T.ERROR_BORDER_DARK}; "
            f"border-radius: {T.R_S}px; padding: 0 {T.SP_S}px; "
            f"font-family: '{T.FONT}'; font-size: {T.FS_CAPTION}px; }}"
            f"QPushButton#rejectBtn:hover {{ background: {T.ERROR}; color: white; }}"
        )
        reject_btn.clicked.connect(lambda: self._on_reject())
        layout.addWidget(reject_btn)

        accept_btn = QPushButton("接受")
        accept_btn.setObjectName("acceptBtn")
        accept_btn.setCursor(Qt.PointingHandCursor)
        accept_btn.setFixedHeight(24)
        accept_btn.setStyleSheet(
            f"QPushButton#acceptBtn {{ background: {T.SUCCESS_BG_DARK}; "
            f"color: {T.SUCCESS}; border: 1px solid {T.SUCCESS_BORDER_DARK}; "
            f"border-radius: {T.R_S}px; padding: 0 {T.SP_S}px; "
            f"font-family: '{T.FONT}'; font-size: {T.FS_CAPTION}px; }}"
            f"QPushButton#acceptBtn:hover {{ background: {T.SUCCESS}; color: white; }}"
        )
        accept_btn.clicked.connect(lambda: self._on_accept())
        layout.addWidget(accept_btn)

    def _on_accept(self):
        self._status = "accepted"
        self._status_label.setText("已接受")
        self._status_label.setStyleSheet(
            f"color: {Lemon.SUCCESS}; font-size: {Lemon.FS_CAPTION}px; "
            f"font-family: '{Lemon.FONT}'; background: transparent; border: none;"
        )
        self.accepted.emit(self._artifact.artifact_id)

    def _on_reject(self):
        self._status = "reverted"
        file_path = self._artifact.path_or_content
        if file_path and os.path.exists(file_path):
            try:
                project_dir = os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__)))))
                subprocess.run(
                    ["git", "checkout", "--", file_path],
                    cwd=project_dir, capture_output=True, timeout=10,
                )
            except Exception:
                pass
        self._status_label.setText("已拒绝")
        self._status_label.setStyleSheet(
            f"color: {Lemon.ERROR}; font-size: {Lemon.FS_CAPTION}px; "
            f"font-family: '{Lemon.FONT}'; background: transparent; border: none;"
        )
        self.rejected.emit(self._artifact.artifact_id)

    @property
    def artifact_id(self) -> str:
        return self._artifact.artifact_id


class DiffSummaryDialog(QDialog):
    artifact_accepted = pyqtSignal(str)
    artifact_rejected = pyqtSignal(str)
    all_accepted = pyqtSignal()

    def __init__(self, artifacts: List[Artifact],
                 registry: RunRegistry, parent=None):
        super().__init__(parent)
        self._artifacts = artifacts
        self._registry = registry
        self._rows = {}
        self._init_ui(artifacts)

    def _init_ui(self, artifacts: List[Artifact]):
        T = Lemon
        self.setWindowTitle("变更汇总")
        self.setMinimumSize(600, 400)
        self.resize(700, 500)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG}; color: {T.PRIMARY}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_L, T.SP_L, T.SP_L, T.SP_L)
        layout.setSpacing(T.SP_M)

        header = QLabel(f"文件变更 ({len(artifacts)} 个文件)")
        header.setStyleSheet(
            f"color: {T.DARK_TEXT_1}; font-size: {T.FS_H}px; "
            f"font-weight: bold; font-family: '{T.FONT}'; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {T.BG}; border: none; }}"
        )
        container = QWidget()
        container.setStyleSheet(f"background: {T.BG};")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(T.SP_S)
        container_layout.setAlignment(Qt.AlignTop)

        for art in artifacts:
            row = _ArtifactRow(art, container)
            row.accepted.connect(self._on_artifact_accepted)
            row.rejected.connect(self._on_artifact_rejected)
            self._rows[art.artifact_id] = row
            container_layout.addWidget(row)

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(T.SP_S)
        btn_row.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedHeight(32)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {T.SURFACE}; color: {T.SECONDARY}; "
            f"border: 1px solid {T.BORDER}; border-radius: {T.R_S}px; "
            f"padding: 0 {T.SP_L}px; font-family: '{T.FONT}'; }}"
            f"QPushButton:hover {{ border-color: {T.BRAND_ORANGE}; }}"
        )
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        accept_all_btn = QPushButton("全部接受")
        accept_all_btn.setCursor(Qt.PointingHandCursor)
        accept_all_btn.setFixedHeight(32)
        accept_all_btn.setStyleSheet(
            f"QPushButton {{ background: {T.SUCCESS_BG_DARK}; color: {T.SUCCESS}; "
            f"border: 1px solid {T.SUCCESS_BORDER_DARK}; border-radius: {T.R_S}px; "
            f"padding: 0 {T.SP_L}px; font-family: '{T.FONT}'; font-weight: bold;}}"
            f"QPushButton:hover {{ background: {T.SUCCESS}; color: white; }}"
        )
        accept_all_btn.clicked.connect(self._on_accept_all)
        btn_row.addWidget(accept_all_btn)

        layout.addLayout(btn_row)

    def _on_artifact_accepted(self, artifact_id: str):
        self.artifact_accepted.emit(artifact_id)

    def _on_artifact_rejected(self, artifact_id: str):
        self.artifact_rejected.emit(artifact_id)

    def _on_accept_all(self):
        for aid, row in self._rows.items():
            if row._status == "pending":
                row._on_accept()
        self.all_accepted.emit()
