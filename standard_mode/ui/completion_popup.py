# -*- coding: utf-8 -*-
"""
代码补全弹窗 — LSP 补全结果显示（v0.6.0 新增）
==============================================
功能：
- 补全项列表显示
- 键盘导航（↑/↓/Enter/Esc）
- 类型图标
- 详情预览
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, 
    QListWidget, QListWidgetItem, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor

from ui.theme import BG_SECONDARY, BG_SURFACE, TEXT_PRIMARY, TEXT_SECONDARY, XIAOMI_ORANGE, BORDER_DEFAULT
from core.i18n import _t

# 补全项类型图标
KIND_ICONS = {
    1: "📝",   # Text
    2: "📦",   # Method
    3: "⚡",   # Function
    4: "🔨",   # Constructor
    5: "📊",   # Field
    6: "📌",   # Variable
    7: "🏗️",  # Class
    8: "🔌",   # Interface
    9: "📦",   # Module
    10: "🏠",  # Property
    11: "🔢",  # Unit
    12: "💰",  # Value
    13: "🔢",  # Enum
    14: "🔑",  # Keyword
    15: "📝",  # Snippet
    16: "🎨",  # Color
    17: "📄",  # File
    18: "📁",  # Reference
    19: "📁",  # Folder
    20: "📦",  # EnumMember
    21: "📐",  # Constant
    22: "🏗️",  # Struct
    23: "⚡",   # Event
    24: "📤",   # Operator
    25: "🎯",   # TypeParameter
}


class CompletionPopup(QWidget):
    """
    代码补全弹窗
    
    信号：
    - item_selected(str): 用户选择补全项
    - cancelled(): 用户取消
    """
    
    item_selected = pyqtSignal(str)
    cancelled = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._init_ui()
        self.hide()
    
    def _init_ui(self):
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedWidth(400)
        self.setMaximumHeight(300)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 标题栏
        self.header = QFrame()
        self.header.setFixedHeight(28)
        self.header.setStyleSheet(f"""
            QFrame {{
                background: {BG_SECONDARY};
                border-bottom: 1px solid {BORDER_DEFAULT};
            }}
        """)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 0, 10, 0)
        
        self.title_label = QLabel(_t('ui.code_completion'))
        self.title_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: 600;")
        header_layout.addWidget(self.title_label)
        
        self.count_label = QLabel(_t('ui.items_count', count=0))
        self.count_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        header_layout.addStretch()
        header_layout.addWidget(self.count_label)
        
        layout.addWidget(self.header)
        
        # 补全列表
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {BG_SURFACE};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px 10px;
                border-bottom: 1px solid {BORDER_DEFAULT};
            }}
            QListWidget::item:selected {{
                background: rgba(255, 105, 0, 0.15);
                color: {XIAOMI_ORANGE};
            }}
            QListWidget::item:hover {{
                background: rgba(255, 255, 255, 0.05);
            }}
        """)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget, 1)
        
        # 详情面板
        self.detail_frame = QFrame()
        self.detail_frame.setFixedHeight(60)
        self.detail_frame.setStyleSheet(f"""
            QFrame {{
                background: {BG_SECONDARY};
                border-top: 1px solid {BORDER_DEFAULT};
            }}
        """)
        detail_layout = QVBoxLayout(self.detail_frame)
        detail_layout.setContentsMargins(10, 6, 10, 6)
        
        self.detail_label = QLabel()
        self.detail_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        self.detail_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_label)
        
        layout.addWidget(self.detail_frame)
        
        self.setFocusPolicy(Qt.StrongFocus)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
    
    def set_items(self, items):
        """
        设置补全项列表
        
        Args:
            items: List[CompletionItem]
        """
        self._items = items
        self.list_widget.clear()
        
        for item in items:
            icon = KIND_ICONS.get(item.kind, "📝")
            text = f"{icon} {item.label}"
            
            list_item = QListWidgetItem(text)
            list_item.setData(Qt.UserRole, item.insert_text)
            list_item.setData(Qt.UserRole + 1, item.detail)
            list_item.setData(Qt.UserRole + 2, item.documentation)
            self.list_widget.addItem(list_item)
        
        self.count_label.setText(_t('ui.items_count', count=len(items)))
        
        if items:
            self.list_widget.setCurrentRow(0)
            self._update_detail()
    
    def show_at_cursor(self, editor_global_pos):
        """在光标位置显示"""
        self.move(editor_global_pos)
        self.show()
        self.setFocus()
    
    def keyPressEvent(self, event):
        """键盘事件处理"""
        key = event.key()
        
        if key == Qt.Key_Escape:
            self.hide()
            self.cancelled.emit()
        
        elif key == Qt.Key_Up:
            current_row = self.list_widget.currentRow()
            if current_row > 0:
                self.list_widget.setCurrentRow(current_row - 1)
                self._update_detail()
        
        elif key == Qt.Key_Down:
            current_row = self.list_widget.currentRow()
            if current_row < self.list_widget.count() - 1:
                self.list_widget.setCurrentRow(current_row + 1)
                self._update_detail()
        
        elif key in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab):
            self._select_current_item()
        
        else:
            super().keyPressEvent(event)
    
    def _on_item_clicked(self, item):
        """单击项目"""
        self._update_detail()
    
    def _on_item_double_clicked(self, item):
        """双击选择"""
        self._select_current_item()
    
    def _select_current_item(self):
        """选择当前项"""
        current = self.list_widget.currentItem()
        if current:
            insert_text = current.data(Qt.UserRole)
            self.hide()
            self.item_selected.emit(insert_text)
    
    def _update_detail(self):
        """更新详情显示"""
        current = self.list_widget.currentItem()
        if current:
            detail = current.data(Qt.UserRole + 1) or ""
            doc = current.data(Qt.UserRole + 2) or ""
            self.detail_label.setText(f"{detail}\n{doc}" if detail and doc else detail or doc)
        else:
            self.detail_label.clear()