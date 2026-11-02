# -*- coding: utf-8 -*-
"""
v6.0-H A-2 — Agent 添加/移除对话框
==================================
添加新 Agent 的对话框：角色选择、名字输入、能力标签。
终止确认对话框。
"""

from typing import List, Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QFrame, QSizePolicy,
    QButtonGroup
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from ui.design.tokens import Lemon
from ui.theme import SVG_ICONS

ROLES = ["coordinator", "researcher", "coder", "reviewer", "tester", "documenter"]

CAPABILITIES = [
    ("read_file", "读文件"),
    ("write_file", "写文件"),
    ("execute_command", "执行命令"),
    ("call_git", "调用 Git"),
    ("search_web", "搜索网页"),
    ("run_test", "运行测试"),
]

_ROLE_COLORS = {
    "coordinator": Lemon.ACCENT_BLUE,
    "researcher": Lemon.ACCENT_GREEN,
    "coder": Lemon.BRAND_ORANGE,
    "reviewer": Lemon.ACCENT_PURPLE,
    "tester": Lemon.ACCENT_ORANGE,
    "documenter": Lemon.ACCENT_PINK,
}

_ROLE_DEFAULT_CAPS = {
    "coordinator": ["read_file", "call_git"],
    "researcher": ["read_file", "search_web"],
    "coder": ["read_file", "write_file", "execute_command", "call_git"],
    "reviewer": ["read_file", "run_test"],
    "tester": ["read_file", "execute_command", "run_test"],
    "documenter": ["read_file", "write_file"],
}


class AddAgentDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加 Agent")
        self.setMinimumWidth(360)
        self.selected_role = ""
        self.selected_name = ""
        self.selected_capabilities: List[str] = []
        self._cap_checks = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Lemon.SP_L, Lemon.SP_L, Lemon.SP_L, Lemon.SP_L)
        layout.setSpacing(Lemon.SP_M)

        title = QLabel("添加新 Agent")
        title.setFont(QFont(Lemon.FONT, Lemon.FS_TITLE, QFont.Bold))
        title.setStyleSheet(f"color: {Lemon.BRAND_ORANGE}; border: none;")
        layout.addWidget(title)

        role_layout = QHBoxLayout()
        role_layout.setSpacing(Lemon.SP_S)

        role_label = QLabel("角色:")
        role_label.setFont(QFont(Lemon.FONT, Lemon.FS_BODY))
        role_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_2}; border: none;")
        role_layout.addWidget(role_label)

        self._role_combo = QComboBox()
        self._role_combo.addItems(ROLES)
        self._role_combo.setFixedHeight(30)
        self._role_combo.setStyleSheet(f"""
            QComboBox {{
                background: {Lemon.SURFACE};
                border: 1px solid {Lemon.BORDER};
                border-radius: {Lemon.R_S}px;
                color: {Lemon.DARK_TEXT_1};
                padding: 4px 10px;
                font-family: {Lemon.FONT};
                font-size: {Lemon.FS_BODY}px;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {Lemon.DARK_BG_2};
                color: {Lemon.DARK_TEXT_1};
                border: 1px solid {Lemon.BORDER};
                selection-background-color: {Lemon.BRAND_ORANGE}33;
            }}
        """)
        self._role_combo.currentTextChanged.connect(self._on_role_changed)
        role_layout.addWidget(self._role_combo, 1)

        layout.addLayout(role_layout)

        name_layout = QHBoxLayout()
        name_layout.setSpacing(Lemon.SP_S)

        name_label = QLabel("名字:")
        name_label.setFont(QFont(Lemon.FONT, Lemon.FS_BODY))
        name_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_2}; border: none;")
        name_layout.addWidget(name_label)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("可选，默认用角色名+序号")
        self._name_input.setFixedHeight(30)
        self._name_input.setStyleSheet(f"""
            QLineEdit {{
                background: {Lemon.SURFACE};
                border: 1px solid {Lemon.BORDER};
                border-radius: {Lemon.R_S}px;
                color: {Lemon.DARK_TEXT_1};
                padding: 4px 10px;
                font-family: {Lemon.FONT};
                font-size: {Lemon.FS_BODY}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {Lemon.BRAND_ORANGE};
            }}
        """)
        name_layout.addWidget(self._name_input, 1)

        layout.addLayout(name_layout)

        cap_label = QLabel("能力标签:")
        cap_label.setFont(QFont(Lemon.FONT, Lemon.FS_BODY))
        cap_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_2}; border: none;")
        layout.addWidget(cap_label)

        cap_grid = QHBoxLayout()
        cap_grid.setSpacing(Lemon.SP_S)

        for i, (cap_id, cap_name) in enumerate(CAPABILITIES):
            cb = QCheckBox(cap_name)
            cb.setFont(QFont(Lemon.FONT, Lemon.FS_CAPTION))
            cb.setStyleSheet(f"""
                QCheckBox {{
                    color: {Lemon.DARK_TEXT_2};
                    spacing: 4px;
                }}
                QCheckBox::indicator {{
                    width: 14px;
                    height: 14px;
                    border: 1px solid {Lemon.BORDER};
                    border-radius: 3px;
                    background: {Lemon.SURFACE};
                }}
                QCheckBox::indicator:checked {{
                    background: {Lemon.BRAND_ORANGE};
                    border: 1px solid {Lemon.BRAND_ORANGE};
                }}
            """)
            self._cap_checks[cap_id] = cb
            cap_grid.addWidget(cb)

        layout.addLayout(cap_grid)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {Lemon.BORDER};")
        layout.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(Lemon.SP_S)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {Lemon.DARK_TEXT_3};
                border: 1px solid {Lemon.BORDER};
                border-radius: {Lemon.R_S}px;
                padding: 4px 20px;
                font-family: {Lemon.FONT};
                font-size: {Lemon.FS_BODY}px;
            }}
            QPushButton:hover {{
                background: {Lemon.SURFACE};
            }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("确认添加")
        confirm_btn.setFixedHeight(32)
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Lemon.BRAND_ORANGE};
                color: white;
                border: none;
                border-radius: {Lemon.R_S}px;
                padding: 4px 20px;
                font-family: {Lemon.FONT};
                font-size: {Lemon.FS_BODY}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Lemon.BRAND_ORANGE_LIGHT};
            }}
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

        self.setStyleSheet(f"""
            AddAgentDialog {{
                background: {Lemon.DARK_BG_2};
            }}
        """)

        self._on_role_changed(ROLES[0])

    def _on_role_changed(self, role: str):
        default_caps = _ROLE_DEFAULT_CAPS.get(role, [])
        for cap_id, cb in self._cap_checks.items():
            cb.setChecked(cap_id in default_caps)

    def _on_confirm(self):
        self.selected_role = self._role_combo.currentText()
        self.selected_name = self._name_input.text().strip()
        self.selected_capabilities = [
            cap_id for cap_id, cb in self._cap_checks.items() if cb.isChecked()
        ]
        self.accept()

    @staticmethod
    def get_agent_config(parent=None) -> Optional[dict]:
        dlg = AddAgentDialog(parent)
        if dlg.exec_() == QDialog.Accepted:
            return {
                "role": dlg.selected_role,
                "name": dlg.selected_name,
                "capabilities": dlg.selected_capabilities,
            }
        return None


class TerminateConfirmDialog(QDialog):
    def __init__(self, agent_id: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("终止 Agent")
        self.setMinimumWidth(300)
        self._agent_id = agent_id
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Lemon.SP_L, Lemon.SP_L, Lemon.SP_L, Lemon.SP_L)
        layout.setSpacing(Lemon.SP_M)

        warn_svg = SVG_ICONS.get("alert-triangle", "")
        icon_label = QLabel()
        icon_label.setFixedSize(24, 24)
        icon_label.setStyleSheet(f"color: {Lemon.ERROR};")
        icon_label.setText(warn_svg.replace('width="16" height="16"', 'width="24" height="24"'))

        msg_label = QLabel(f"确定要终止 Agent \"{self._agent_id}\" 吗？\n此操作不可撤销。")
        msg_label.setFont(QFont(Lemon.FONT, Lemon.FS_BODY))
        msg_label.setStyleSheet(f"color: {Lemon.DARK_TEXT_1}; border: none;")
        msg_label.setWordWrap(True)

        header = QHBoxLayout()
        header.setSpacing(Lemon.SP_S)
        header.addWidget(icon_label)
        header.addWidget(msg_label, 1)
        layout.addLayout(header)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {Lemon.DARK_TEXT_3};
                border: 1px solid {Lemon.BORDER};
                border-radius: {Lemon.R_S}px;
                padding: 4px 20px;
                font-family: {Lemon.FONT};
            }}
            QPushButton:hover {{ background: {Lemon.SURFACE}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        term_btn = QPushButton("确认终止")
        term_btn.setFixedHeight(32)
        term_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Lemon.ERROR};
                color: white;
                border: none;
                border-radius: {Lemon.R_S}px;
                padding: 4px 20px;
                font-family: {Lemon.FONT};
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #ff6b6b; }}
        """)
        term_btn.clicked.connect(self.accept)
        btn_row.addWidget(term_btn)

        layout.addLayout(btn_row)

        self.setStyleSheet(f"TerminateConfirmDialog {{ background: {Lemon.DARK_BG_2}; }}")

    @staticmethod
    def confirm(agent_id: str, parent=None) -> bool:
        dlg = TerminateConfirmDialog(agent_id, parent)
        return dlg.exec_() == QDialog.Accepted
