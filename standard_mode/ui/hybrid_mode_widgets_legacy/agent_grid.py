# -*- coding: utf-8 -*-
"""
v6.0-H A-1 — Agent 卡片网格容器
================================
支持 1-6 个 Agent 卡片的自适应网格布局。
窗口缩放时自动调整列数。
监听 AgentOrchestrator 事件，动态添加/移除卡片。
"""

from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QSizePolicy, QToolButton
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt5.QtGui import QFont

from ui.design.tokens import Lemon
from ui.theme import SVG_ICONS
from ui.hybrid_mode_widgets_legacy.agent_card import AgentCard, _ROLE_COLORS


class AgentGrid(QWidget):
    agent_view_detail = pyqtSignal(str)
    agent_pause = pyqtSignal(str)
    agent_terminate = pyqtSignal(str)
    agent_selected = pyqtSignal(str)
    add_agent_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: Dict[str, AgentCard] = {}
        self._selected_id = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Lemon.SP_S, Lemon.SP_S, Lemon.SP_S, Lemon.SP_S)
        layout.setSpacing(Lemon.SP_S)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(Lemon.SP_S)

        title = QLabel("Agent 集群")
        title.setFont(QFont(Lemon.FONT, Lemon.FS_TITLE, QFont.Bold))
        title.setStyleSheet(f"color: {Lemon.BRAND_ORANGE}; border: none;")
        toolbar.addWidget(title)

        self._count_label = QLabel("(0)")
        self._count_label.setFont(QFont(Lemon.FONT, Lemon.FS_BODY))
        self._count_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_3}; border: none;")
        toolbar.addWidget(self._count_label)

        toolbar.addStretch()

        add_btn = QToolButton()
        add_svg = SVG_ICONS.get("plus", "+")
        add_btn.setText(add_svg)
        add_btn.setFixedSize(28, 28)
        add_btn.setToolTip("添加 Agent")
        add_btn.setStyleSheet(f"""
            QToolButton {{
                background: {Lemon.SURFACE};
                border: 1px solid {Lemon.BORDER};
                border-radius: {Lemon.R_S}px;
                color: {Lemon.BRAND_ORANGE};
                font-size: 14px;
            }}
            QToolButton:hover {{
                border: 1px solid {Lemon.BRAND_ORANGE};
                background: {Lemon.BRAND_ORANGE}22;
            }}
        """)
        add_btn.clicked.connect(self.add_agent_requested.emit)
        toolbar.addWidget(add_btn)

        layout.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {Lemon.BG};
                border: none;
            }}
            QScrollBar:vertical {{
                background: {Lemon.BG};
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {Lemon.SCROLLBAR_THUMB};
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {Lemon.SCROLLBAR_THUMB_HOVER};
            }}
        """)

        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._grid_layout.setSpacing(Lemon.SP_S)
        self._grid_layout.setHorizontalSpacing(Lemon.SP_S)
        self._grid_layout.setVerticalSpacing(Lemon.SP_S)

        scroll.setWidget(self._grid_container)
        layout.addWidget(scroll, 1)

    def _compute_cols(self) -> int:
        w = self.width()
        if w < 500:
            return 1
        elif w < 750:
            return 2
        elif w < 1000:
            return 3
        else:
            return 3

    def add_agent(self, agent_id: str, role: str = "coder",
                  name: str = "", state: str = "idle",
                  task: str = "", progress: int = 0,
                  elapsed_ms: int = 0):
        if agent_id in self._cards:
            return
        card = AgentCard(agent_id, role, name, state, task, progress, elapsed_ms)
        card.view_detail.connect(self.agent_view_detail.emit)
        card.pause_clicked.connect(self.agent_pause.emit)
        card.terminate_clicked.connect(self.agent_terminate.emit)
        card.card_clicked.connect(self._on_card_clicked)
        self._cards[agent_id] = card
        self._relayout()
        self._update_count()

    def remove_agent(self, agent_id: str):
        card = self._cards.pop(agent_id, None)
        if not card:
            return
        self._grid_layout.removeWidget(card)
        card.deleteLater()
        if self._selected_id == agent_id:
            self._selected_id = ""
        self._relayout()
        self._update_count()

    def update_agent(self, agent_id: str, **kwargs):
        card = self._cards.get(agent_id)
        if card:
            card.update_state(
                kwargs.get("state", card._state),
                kwargs.get("task", ""),
                kwargs.get("progress", -1),
                kwargs.get("elapsed_ms", -1),
            )

    def get_agent_ids(self) -> List[str]:
        return list(self._cards.keys())

    def _on_card_clicked(self, agent_id: str):
        if self._selected_id and self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(False)
        self._selected_id = agent_id
        self._cards[agent_id].set_selected(True)
        self.agent_selected.emit(agent_id)

    def _relayout(self):
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        cols = self._compute_cols()
        cards = list(self._cards.values())
        for i, card in enumerate(cards):
            row = i // cols
            col = i % cols
            self._grid_layout.addWidget(card, row, col)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _update_count(self):
        n = len(self._cards)
        self._count_label.setText(f"({n})")
