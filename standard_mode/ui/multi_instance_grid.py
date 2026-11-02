# -*- coding: utf-8 -*-
"""
多实例网格面板 — 右侧多窗格显示（v2.0 新增）
==============================================
功能：
- 支持 1/2/4 分屏网格布局
- 每个窗格独立显示一个 MIMO Code 实例的输出
- 点击窗格可最大化/恢复
- 支持拖拽重排
- 底部终端栏显示 Director 聚合结果
"""

from typing import Optional, Dict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QPushButton, QTextEdit, QSizePolicy,
    QSplitter, QScrollArea, QTabWidget
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QTextCursor
from ui.design.tokens import Lemon

C = {
    'bg': Lemon.DARK_BG_2,
    'bg_dark': Lemon.DARK_BG_2,
    'border': 'Lemon.DARK_BG_4',
    'border_active': Lemon.STATUS_RUNNING,
    'text': Lemon.DARK_TEXT_1,
    'text_dim': Lemon.STATUS_OFFLINE,
    'text_muted': Lemon.SYNTAX_COMMENT,
    'accent': Lemon.STATUS_RUNNING,
    'orange': Lemon.BRAND_ORANGE,
    'green': Lemon.STATUS_ONLINE,
    'red': Lemon.ERROR,
    'yellow': '#d2991d',
    'purple': '#a371f7',
    'director_bg': 'Lemon.DARK_MID_5',
    'worker_bg': Lemon.DARK_BG_2,
    'header_bg': 'Lemon.DARK_BG_2',
    'gutter_bg': Lemon.DARK_BG_2,
}

ROLE_COLORS = {
    "director": "#e6b422",  # 金色
    "build": Lemon.STATUS_ONLINE,     # 绿色
    "plan": Lemon.STATUS_RUNNING,      # 蓝色
    "compose": "#a371f7",   # 紫色
    "general": Lemon.STATUS_OFFLINE,   # 灰色
}

ROLE_ICONS = {
    "director": "🎯",
    "build": "🔨",
    "plan": "📐",
    "compose": "✏️",
    "general": "⚙",
}


class InstancePane(QWidget):
    """单个实例的输出窗格"""
    
    clicked = pyqtSignal(str)          # instance_id
    maximize_requested = pyqtSignal(str)  # instance_id
    
    def __init__(self, instance_id: str, name: str, role: str, port: int, parent=None):
        super().__init__(parent)
        self._instance_id = instance_id
        self._name = name
        self._role = role
        self._port = port
        self._maximized = False
        self._init_ui()
    
    def _init_ui(self):
        self.setStyleSheet(f"""
            QWidget {{
                background: {C['worker_bg']};
                border: 1px solid {C['border']};
                border-radius: 6px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # === 标题栏 ===
        header = QFrame()
        header.setFixedHeight(32)
        role_color = ROLE_COLORS.get(self._role, C['text_dim'])
        header.setStyleSheet(f"""
            QFrame {{
                background: {C['header_bg']};
                border: none;
                border-radius: 6px 6px 0 0;
                border-bottom: 1px solid {C['border']};
            }}
        """)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(10, 4, 6, 4)
        h_layout.setSpacing(6)
        
        # 角色图标
        icon = ROLE_ICONS.get(self._role, "⚙")
        icon_label = QLabel(icon)
        icon_label.setFixedWidth(20)
        icon_label.setStyleSheet("background: transparent; font-size: 13px;")
        h_layout.addWidget(icon_label)
        
        # 名称
        name_label = QLabel(self._name)
        name_label.setStyleSheet(f"""
            color: {role_color}; font-weight: 700; font-size: 12px;
            background: transparent;
        """)
        h_layout.addWidget(name_label)
        
        # 端口号
        port_label = QLabel(f":{self._port}")
        port_label.setStyleSheet(f"color: {C['text_muted']}; font-size: 10px; background: transparent;")
        h_layout.addWidget(port_label)
        
        h_layout.addStretch()
        
        # 状态指示灯
        self._status_dot = QLabel("⚪")
        self._status_dot.setFixedSize(16, 16)
        self._status_dot.setStyleSheet("background: transparent; font-size: 10px;")
        h_layout.addWidget(self._status_dot)
        
        # 最大化按钮
        max_btn = QPushButton("⛶")
        max_btn.setFixedSize(22, 22)
        max_btn.setToolTip("最大化/恢复")
        max_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C['text_muted']};
                border: none;
                border-radius: 3px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: Lemon.DARK_BG_3;
                color: {C['accent']};
            }}
        """)
        max_btn.clicked.connect(lambda: self.maximize_requested.emit(self._instance_id))
        h_layout.addWidget(max_btn)
        
        layout.addWidget(header)
        
        # === 输出区域 ===
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Cascadia Code", 9))
        self.output.setStyleSheet(f"""
            QTextEdit {{
                background: {C['bg']};
                color: {C['text']};
                border: none;
                padding: 8px 10px;
                font-size: 11px;
                selection-background-color: {Lemon.INFO_BG_DARK};
            }}
            QScrollBar:vertical {{
                background: {C['bg_dark']};
                width: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C['border']};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C['text_muted']};
            }}
        """)
        layout.addWidget(self.output, 1)
    
    def append_output(self, text: str):
        """追加输出"""
        self.output.append(text)
        # 滚动到底部
        scrollbar = self.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def append_html(self, html: str):
        """追加 HTML 格式输出"""
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.output.setTextCursor(cursor)
        self.output.insertHtml(html + "<br>")
        scrollbar = self.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_output(self):
        """清空输出"""
        self.output.clear()
    
    def set_status(self, state: str):
        """设置状态指示灯"""
        colors = {
            "running": "{Lemon.STATUS_ONLINE}",
            "busy": "#d2991d",
            "starting": "{Lemon.STATUS_RUNNING}",
            "error": "{Lemon.ERROR}",
            "stopped": "{Lemon.SYNTAX_COMMENT}",
        }
        color = colors.get(state, "{Lemon.SYNTAX_COMMENT}")
        self._status_dot.setStyleSheet(f"background: transparent; color: {color}; font-size: 10px;")
    
    def set_active(self, active: bool):
        """设置活动状态边框"""
        if active:
            self.setStyleSheet(f"""
                QWidget {{
                    background: {C['worker_bg']};
                    border: 2px solid {C['accent']};
                    border-radius: 6px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QWidget {{
                    background: {C['worker_bg']};
                    border: 1px solid {C['border']};
                    border-radius: 6px;
                }}
            """)
    
    def mousePressEvent(self, event):
        self.clicked.emit(self._instance_id)
        super().mousePressEvent(event)


class MultiInstanceGrid(QWidget):
    """
    多实例网格面板
    
    布局模式：
    - 1窗格：全屏单窗格
    - 2窗格：左右分屏
    - 4窗格：2x2 网格
    - 5窗格：2x2 网格 + 底部 Director 聚合栏
    """
    
    instance_selected = pyqtSignal(str)       # instance_id
    instance_maximized = pyqtSignal(str)      # instance_id
    send_to_instance = pyqtSignal(str, str)   # (instance_id, message)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._panes: Dict[str, InstancePane] = {}
        self._maximized_pane: Optional[str] = None
        self._layout_mode = 1  # 1=单窗格, 2=2窗格, 4=4窗格
        self._init_ui()
    
    def _init_ui(self):
        self.setStyleSheet(f"background: {C['bg_dark']};")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)
        
        # === 顶部工具栏 ===
        toolbar = QFrame()
        toolbar.setFixedHeight(34)
        toolbar.setStyleSheet(f"background: {C['header_bg']}; border: 1px solid {C['border']}; border-radius: 6px;")
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(10, 4, 6, 4)
        t_layout.setSpacing(6)
        
        title = QLabel("多实例协同")
        title.setStyleSheet(f"color: {C['text']}; font-weight: 700; font-size: 13px; background: transparent;")
        t_layout.addWidget(title)
        
        t_layout.addStretch()
        
        # 布局模式按钮
        for mode, icon, tip in [
            (1, "▣", "单窗格"),
            (2, "◫", "双窗格"),
            (4, "⊞", "四窗格"),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(28, 28)
            btn.setToolTip(tip)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C['text_dim']};
                    border: 1px solid {C['border']};
                    border-radius: 4px;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background: Lemon.DARK_BG_3;
                    color: {C['accent']};
                }}
            """)
            btn.clicked.connect(lambda checked, m=mode: self._set_layout_mode(m))
            t_layout.addWidget(btn)
        
        main_layout.addWidget(toolbar)
        
        # === 网格区域 ===
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(4)
        main_layout.addLayout(self._grid, 1)
        
        # === Director 聚合栏（底部） ===
        self._director_bar = QFrame()
        self._director_bar.setFixedHeight(28)
        self._director_bar.setStyleSheet(f"background: {C['director_bg']}; border: 1px solid {C['border']}; border-radius: 4px;")
        db_layout = QHBoxLayout(self._director_bar)
        db_layout.setContentsMargins(10, 2, 10, 2)
        
        self._director_status = QLabel("🎯 指挥官: 未启动")
        self._director_status.setStyleSheet(f"color: {ROLE_COLORS['director']}; font-size: 11px; font-weight: 600; background: transparent;")
        db_layout.addWidget(self._director_status)
        db_layout.addStretch()
        self._worker_count_label = QLabel("")
        self._worker_count_label.setStyleSheet(f"color: {C['text_dim']}; font-size: 10px; background: transparent;")
        db_layout.addWidget(self._worker_count_label)
        
        main_layout.addWidget(self._director_bar)
        self._director_bar.hide()
    
    def add_pane(self, instance_id: str, name: str, role: str, port: int):
        """添加实例窗格"""
        if instance_id in self._panes:
            return
        
        pane = InstancePane(instance_id, name, role, port)
        pane.clicked.connect(lambda iid=instance_id: self.instance_selected.emit(iid))
        pane.maximize_requested.connect(self._on_maximize_pane)
        self._panes[instance_id] = pane
        
        self._relayout()
    
    def remove_pane(self, instance_id: str):
        """移除实例窗格"""
        if instance_id not in self._panes:
            return
        
        pane = self._panes.pop(instance_id)
        pane.setParent(None)
        self._grid.removeWidget(pane)
        self._relayout()
    
    def _relayout(self):
        """重新排列窗格"""
        # 清空网格
        for i in reversed(range(self._grid.count())):
            item = self._grid.itemAt(i)
            if item and item.widget():
                self._grid.removeWidget(item.widget())
        
        if not self._panes:
            return
        
        panes = list(self._panes.values())
        count = len(panes)
        
        if count == 1 or self._maximized_pane:
            # 单窗格
            if self._maximized_pane and self._maximized_pane in self._panes:
                self._grid.addWidget(self._panes[self._maximized_pane], 0, 0)
            else:
                self._grid.addWidget(panes[0], 0, 0)
            self._director_bar.show()
        
        elif count == 2:
            self._grid.addWidget(panes[0], 0, 0)
            self._grid.addWidget(panes[1], 0, 1)
            self._director_bar.show()
        
        elif count <= 4:
            for i, pane in enumerate(panes[:4]):
                row, col = i // 2, i % 2
                self._grid.addWidget(pane, row, col)
            self._director_bar.show()
        
        else:
            # 5 个窗格：2x2 + 底部 Director 聚合
            for i, pane in enumerate(panes[:4]):
                row, col = i // 2, i % 2
                self._grid.addWidget(pane, row, col)
            self._director_bar.show()
    
    def _set_layout_mode(self, mode: int):
        """设置布局模式（1/2/4窗格）"""
        self._layout_mode = mode
        self._maximized_pane = None
        # 显示前 mode 个窗格
        panes = list(self._panes.values())
        for i, pane in enumerate(panes):
            if i >= mode:
                self._grid.removeWidget(pane)
        self._relayout()
    
    def _on_maximize_pane(self, instance_id: str):
        """最大化/恢复窗格"""
        if self._maximized_pane == instance_id:
            self._maximized_pane = None
        else:
            self._maximized_pane = instance_id
        self._relayout()
        self.instance_maximized.emit(instance_id)
    
    def append_output(self, instance_id: str, text: str):
        """向指定实例追加输出"""
        pane = self._panes.get(instance_id)
        if pane:
            pane.append_output(text)
    
    def append_html(self, instance_id: str, html: str):
        """向指定实例追加 HTML 输出"""
        pane = self._panes.get(instance_id)
        if pane:
            pane.append_html(html)
    
    def set_instance_status(self, instance_id: str, state: str):
        """设置实例状态指示灯"""
        pane = self._panes.get(instance_id)
        if pane:
            pane.set_status(state)
    
    def set_active_instance(self, instance_id: str):
        """设置活动实例"""
        for iid, pane in self._panes.items():
            pane.set_active(iid == instance_id)
    
    def update_director_status(self, text: str):
        """更新 Director 状态栏"""
        self._director_status.setText(f"🎯 {text}")
    
    def update_worker_count(self, count: int, total: int):
        """更新 Worker 计数"""
        self._worker_count_label.setText(f"👥 {count}/{total} Workers")
    
    def clear_all(self):
        """清空所有窗格"""
        for pane in self._panes.values():
            pane.clear_output()
    
    def get_pane(self, instance_id: str) -> Optional[InstancePane]:
        return self._panes.get(instance_id)