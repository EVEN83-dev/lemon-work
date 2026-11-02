# -*- coding: utf-8 -*-
"""
Menu Bar — 顶部菜单栏

参照 Trae/VS Code 的顶部菜单设计，提供文件、编辑、查看等标准菜单功能。

菜单结构：
- 文件(F): 新建文件、打开文件夹、保存、关闭
- 编辑(E): 撤销、重做、剪切、复制、粘贴、查找、替换
- 选择(S): 全选、选择行
- 查看(V): 切换侧边栏、切换面板、切换终端
- 转到(G): 转到文件、转到行、转到符号
- 运行(R): 运行、调试、停止
- 帮助(H): 关于、文档

信号:
    menu_action_triggered(str): 菜单动作触发，值为动作ID
"""

import os
import sys
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QMenu, QAction, QFrame, QSizePolicy,
    QLineEdit,
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont, QKeySequence, QIcon, QPixmap, QPainter, QColor

sys.path.insert(0, os.path.dirname(__file__))
from theme import (
    BG_ROOT, BG_SURFACE, BG_SURFACE_HOVER, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_TERTIARY, LEMON_ORANGE,
    RADIUS_SM, FONT_SIZE_SM,
)
from ui.design.tokens import Lemon


class LemonMenuBar(QWidget):
    """顶部菜单栏

    信号:
        menu_action_triggered(str): 菜单动作ID
    """

    menu_action_triggered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"""
            QWidget {{
                background: {BG_ROOT};
                border-bottom: 1px solid {BORDER_SUBTLE};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(0)

        # Logo 区域（左侧）
        logo_frame = QFrame()
        logo_frame.setFixedWidth(120)
        logo_frame.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border-right: 1px solid {BORDER_SUBTLE};
            }}
        """)
        logo_layout = QHBoxLayout(logo_frame)
        logo_layout.setContentsMargins(8, 0, 8, 0)

        logo_label = QPushButton("LEMON")
        logo_label.setFixedHeight(24)
        logo_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        logo_label.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {LEMON_ORANGE};
                border: none;
                padding: 0 8px;
            }}
            QPushButton:hover {{
                background: {BG_SURFACE_HOVER};
            }}
        """)
        logo_layout.addWidget(logo_label)
        layout.addWidget(logo_frame)

        # 菜单按钮区域
        menu_frame = QFrame()
        menu_frame.setStyleSheet("background: transparent;")
        menu_layout = QHBoxLayout(menu_frame)
        menu_layout.setContentsMargins(8, 0, 8, 0)
        menu_layout.setSpacing(2)

        # 菜单项定义（★ v4.7.17: 帮助不在这里，放在右侧工具区最末端）
        menus = [
            {
                "label": "文件(&F)",
                "items": [
                    {"id": "new_file", "label": "新建文件", "shortcut": "Ctrl+N"},
                    {"id": "open_folder", "label": "打开文件夹", "shortcut": "Ctrl+O"},
                    {"separator": True},
                    {"id": "save", "label": "保存", "shortcut": "Ctrl+S"},
                    {"id": "save_all", "label": "全部保存", "shortcut": "Ctrl+Shift+S"},
                    {"separator": True},
                    {"id": "close_editor", "label": "关闭编辑器", "shortcut": "Ctrl+W"},
                ],
            },
            {
                "label": "编辑(&E)",
                "items": [
                    {"id": "undo", "label": "撤销", "shortcut": "Ctrl+Z"},
                    {"id": "redo", "label": "重做", "shortcut": "Ctrl+Y"},
                    {"separator": True},
                    {"id": "cut", "label": "剪切", "shortcut": "Ctrl+X"},
                    {"id": "copy", "label": "复制", "shortcut": "Ctrl+C"},
                    {"id": "paste", "label": "粘贴", "shortcut": "Ctrl+V"},
                    {"separator": True},
                    {"id": "find", "label": "查找", "shortcut": "Ctrl+F"},
                    {"id": "replace", "label": "替换", "shortcut": "Ctrl+H"},
                ],
            },
            {
                "label": "选择(&S)",
                "items": [
                    {"id": "select_all", "label": "全选", "shortcut": "Ctrl+A"},
                    {"id": "select_line", "label": "选择行", "shortcut": "Ctrl+L"},
                    {"id": "expand_selection", "label": "扩展选择", "shortcut": "Shift+Alt+→"},
                ],
            },
            {
                "label": "视图(&V)",
                "items": [
                    {"id": "toggle_sidebar", "label": "切换侧边栏", "shortcut": "Ctrl+B"},
                    {"id": "toggle_panel", "label": "切换面板", "shortcut": "Ctrl+J"},
                    {"id": "toggle_terminal", "label": "切换终端", "shortcut": "Ctrl+`"},
                    {"separator": True},
                    {"id": "toggle_explorer", "label": "资源管理器", "shortcut": "Ctrl+Shift+E"},
                    {"id": "toggle_search", "label": "搜索", "shortcut": "Ctrl+Shift+F"},
                    {"id": "toggle_git", "label": "源码管理", "shortcut": "Ctrl+Shift+G"},
                ],
            },
            {
                "label": "转到(&G)",
                "items": [
                    {"id": "go_to_file", "label": "转到文件", "shortcut": "Ctrl+P"},
                    {"id": "go_to_line", "label": "转到行", "shortcut": "Ctrl+G"},
                    {"id": "go_to_symbol", "label": "转到符号", "shortcut": "Ctrl+Shift+O"},
                    {"id": "go_to_definition", "label": "转到定义", "shortcut": "F12"},
                ],
            },
            {
                "label": "运行(&R)",
                "items": [
                    {"id": "run", "label": "运行", "shortcut": "F5"},
                    {"id": "debug", "label": "调试", "shortcut": "F5"},
                    {"id": "stop", "label": "停止", "shortcut": "Shift+F5"},
                    {"separator": True},
                    {"id": "run_config", "label": "运行配置", "shortcut": ""},
                ],
            },
        ]

        for menu_def in menus:
            btn = QPushButton(menu_def["label"])
            btn.setFixedHeight(28)
            btn.setMinimumWidth(60)
            btn.setFont(QFont("Microsoft YaHei", 9))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {TEXT_PRIMARY};
                    border: none;
                    padding: 0 12px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: {BG_SURFACE_HOVER};
                    color: {LEMON_ORANGE};
                }}
            """)

            # 创建子菜单
            menu = QMenu(self)
            for item in menu_def["items"]:
                if item.get("separator"):
                    menu.addSeparator()
                else:
                    action = QAction(item["label"], self)
                    if item.get("shortcut"):
                        action.setShortcut(QKeySequence(item["shortcut"]))
                    action.triggered.connect(lambda _, aid=item["id"]: self.menu_action_triggered.emit(aid))
                    menu.addAction(action)

            btn.setMenu(menu)
            menu_layout.addWidget(btn)

        # 运行之后、搜索框之前加 16px 间距（视觉分组）
        menu_layout.addSpacing(16)

        # ★ v4.7.17 整改：搜索框 + 积分器 + 帮助 全部直接加到 menu_layout（与菜单同一排、间距精准）
        # 不再独立 right_tools_frame，避免 menu_frame stretch 造成巨大空白

        # 搜索框（CodeBuddy 风格：真 QLineEdit + SVG 放大镜 + Ctrl+Shift+F 提示）
        search_container = QFrame()
        search_container.setFixedHeight(28)
        search_container.setMinimumWidth(280)
        search_container.setStyleSheet(f"""
            QFrame {{
                background: {BG_SURFACE};
                border: 1px solid {BORDER_SUBTLE};
                border-radius: 999px;
            }}
            QFrame:focus-within {{
                border-color: {LEMON_ORANGE};
            }}
        """)
        sc_layout = QHBoxLayout(search_container)
        sc_layout.setContentsMargins(10, 0, 8, 0)
        sc_layout.setSpacing(6)

        search_icon_label = QPushButton()
        search_icon_label.setFixedSize(14, 14)
        search_icon_label.setFlat(True)
        search_icon_label.setCursor(Qt.ArrowCursor)
        search_icon_label.setStyleSheet("background: transparent; border: none;")
        search_icon_label.setIcon(self._build_search_icon(TEXT_TERTIARY))
        sc_layout.addWidget(search_icon_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索 消息 / 文件 / 命令…")
        self.search_input.setFrame(False)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                color: {TEXT_PRIMARY};
                font-family: 'Microsoft YaHei', sans-serif;
                font-size: {FONT_SIZE_SM};
                selection-background-color: {LEMON_ORANGE};
            }}
        """)
        self.search_input.returnPressed.connect(self._on_search_submit)
        sc_layout.addWidget(self.search_input, 1)

        kbd_label = QPushButton("Ctrl+Shift+F")
        kbd_label.setFlat(True)
        kbd_label.setCursor(Qt.ArrowCursor)
        kbd_label.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE};
                border-radius: 3px;
                font-size: 9px;
                font-family: 'Consolas', monospace;
                padding: 1px 4px;
            }}
        """)
        kbd_label.setToolTip("快捷键：Ctrl+Shift+F")
        sc_layout.addWidget(kbd_label)

        menu_layout.addWidget(search_container)

        # 积分器（CodeBuddy 风格：胶囊 + 星号 + 数字 + 左右翻页）
        credits_btn = QPushButton("★ 2,010    ‹ ›")
        credits_btn.setFixedHeight(28)
        credits_btn.setCursor(Qt.PointingHandCursor)
        credits_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 193, 7, 0.08);
                color: {Lemon.ACCENT_GOLD};
                border: 1px solid rgba(255, 193, 7, 0.3);
                border-radius: 999px;
                padding: 0 12px;
                font-weight: 600;
                font-family: 'Microsoft YaHei', sans-serif;
                font-size: {FONT_SIZE_SM};
            }}
            QPushButton:hover {{
                background: rgba(255, 193, 7, 0.18);
                border-color: rgba(255, 193, 7, 0.55);
            }}
        """)
        credits_btn.clicked.connect(lambda: self.menu_action_triggered.emit("show_credits"))
        menu_layout.addWidget(credits_btn)

        # ★ v4.7.17 整改：帮助按钮放到菜单最右（与搜索/积分同一排）
        menu_layout.addSpacing(12)
        help_btn = QPushButton("帮助(&H)")
        help_btn.setFixedHeight(28)
        help_btn.setMinimumWidth(60)
        help_btn.setFont(QFont("Microsoft YaHei", 9))
        help_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_PRIMARY};
                border: none;
                padding: 0 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                background: {BG_SURFACE_HOVER};
                color: {LEMON_ORANGE};
            }}
        """)
        help_menu = QMenu(self)
        help_items = [
            ("documentation", "文档", ""),
            ("shortcuts", "键盘快捷方式", "Ctrl+K Ctrl+S"),
            ("separator", None, None),
            ("about", "关于 LemonCode", ""),
        ]
        for item in help_items:
            if item[0] == "separator":
                help_menu.addSeparator()
            else:
                action = QAction(item[1], self)
                if item[2]:
                    action.setShortcut(QKeySequence(item[2]))
                action.triggered.connect(lambda _, aid=item[0]: self.menu_action_triggered.emit(aid))
                help_menu.addAction(action)
        help_btn.setMenu(help_menu)
        menu_layout.addWidget(help_btn)

        layout.addWidget(menu_frame, 1)

    def trigger_action(self, action_id: str):
        """程序化触发菜单动作"""
        self.menu_action_triggered.emit(action_id)

    def _on_search_submit(self):
        """搜索框回车：发射 toggle_search 动作携带查询词"""
        query = self.search_input.text().strip()
        # 通过动态属性携带 query，再发射信号
        self._pending_search_query = query
        self.menu_action_triggered.emit("search_submit")
        self.search_input.clear()

    def get_pending_search_query(self) -> str:
        """获取最近一次搜索回车的内容（消费一次）"""
        q = getattr(self, "_pending_search_query", "")
        self._pending_search_query = ""
        return q

    def _build_search_icon(self, color: str):
        """构造放大镜 SVG 图标（避免使用 emoji）"""
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" '
            'viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="11" cy="11" r="7"/>'
            '<line x1="21" y1="21" x2="16.5" y2="16.5"/>'
            '</svg>'
        )
        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        from PyQt5.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(svg.encode('utf-8'))
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
