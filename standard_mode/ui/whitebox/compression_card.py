# -*- coding: utf-8 -*-
"""
CompressionCard — v6.0-S C-2: 上下文压缩可视化卡片
====================================================
当上下文被压缩时展示摘要：原始/压缩令牌数、压缩比、保留轮次。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QFrame, QWidget

from ui.design.tokens import Lemon


class CompressionCard(QFrame):
    def __init__(self, info: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._info = info
        self._init_ui(info)

    def _init_ui(self, info: Dict[str, Any]) -> None:
        T = Lemon
        self.setObjectName("compressionCard")
        self.setStyleSheet(
            "QFrame#compressionCard { background: " + T.INFO_BG_DARK + "; "
            "border: 1px solid " + T.INFO_BORDER_DARK + "; "
            "border-left: 4px solid " + T.ACCENT_BLUE + "; "
            "border-radius: " + str(T.R_M) + "px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        layout.setSpacing(T.SP_XS)

        row1 = QHBoxLayout()
        row1.setSpacing(T.SP_S)
        header = QLabel("[上下文压缩]")
        header.setStyleSheet("color: " + T.ACCENT_BLUE + "; font-size: " + str(T.FS_SUB) + "px; font-weight: bold;")
        row1.addWidget(header)
        row1.addStretch()
        layout.addLayout(row1)

        orig = info.get("original_tokens", 0)
        comp = info.get("compressed_tokens", 0)
        ratio = info.get("ratio", 0)
        kept = info.get("kept_recent", 5)
        removed = info.get("messages_removed", 0)

        detail = str(orig) + " -> " + str(comp) + " tokens  |  " + str(int(ratio * 100)) + "% compressed  |  kept last " + str(kept) + " turns  |  " + str(removed) + " msgs removed"
        detail_label = QLabel(detail)
        detail_label.setStyleSheet("color: " + T.SECONDARY + "; font-size: " + str(T.FS_CAPTION) + "px;")
        detail_label.setWordWrap(True)
        layout.addWidget(detail_label)
