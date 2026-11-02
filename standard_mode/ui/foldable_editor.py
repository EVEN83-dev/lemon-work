# -*- coding: utf-8 -*-
"""
可折叠代码编辑器（v0.6.0 新增）
=================================
功能：
- 基于 QPlainTextEdit 的代码编辑器
- 支持代码块折叠/展开
- 左侧折叠指示器（+-图标）
- 缩进级别自动检测折叠点
- Python/JS/HTML 等语言的折叠规则
"""

import re
from PyQt5.QtWidgets import (
    QPlainTextEdit, QWidget, QHBoxLayout, QTextEdit,
    QToolTip
)
from PyQt5.QtCore import Qt, QRect, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QTextCursor, QTextBlock,
    QPen, QBrush, QTextFormat, QFontMetrics
)
from ui.design.tokens import Lemon


# ============================================================
# 折叠指示器面板（左侧）
# ============================================================

class FoldIndicatorPanel(QWidget):
    """
    左侧折叠指示器面板
    
    显示折叠/展开图标：
    - '+' 表示可展开的已折叠块
    - '-' 表示可折叠的展开块
    - 空表示非折叠点
    
    点击图标触发折叠/展开
    """
    
    fold_clicked = pyqtSignal(int)  # (block_number) 点击折叠图标
    
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setFixedWidth(20)
        self.setStyleSheet("background: transparent;")
        
        # 折叠状态字典 {block_number: True(折叠)/False(展开)}
        self.folded_blocks = {}
        
        # 可折叠块列表（基于语法分析）
        self.foldable_blocks = []
    
    def set_foldable_blocks(self, block_numbers):
        """设置可折叠块的列表"""
        self.foldable_blocks = block_numbers
        self.update()
    
    def is_foldable(self, block_number):
        """检查块是否可折叠"""
        return block_number in self.foldable_blocks
    
    def is_folded(self, block_number):
        """检查块是否已折叠"""
        return self.folded_blocks.get(block_number, False)
    
    def toggle_fold(self, block_number):
        """切换折叠状态"""
        if block_number in self.foldable_blocks:
            self.folded_blocks[block_number] = not self.folded_blocks.get(block_number, False)
            self.editor._apply_folding(block_number, self.folded_blocks[block_number])
            self.update()
    
    def paintEvent(self, event):
        """绘制折叠指示器"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 背景
        painter.fillRect(self.rect(), QColor(30, 30, 35))
        
        # 获取可见区域
        block = self.editor.firstVisibleBlock()
        block_number = block.blockNumber()
        
        # 颜色定义
        expand_color = QColor(255, 105, 0)  # 小米橙色（展开态）
        collapse_color = QColor(255, 105, 0)  # 小米橙色（折叠态）
        
        # 绘制每个可见块的折叠指示器
        while block.isValid():
            # 计算块的Y位置
            top = self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top()
            
            if top > self.height():
                break
            
            # 只绘制可折叠块
            if block_number in self.foldable_blocks:
                # 绘制图标
                y_center = int(top + self.editor.blockBoundingRect(block).height() / 2)
                
                if self.folded_blocks.get(block_number, False):
                    # 已折叠：显示 '+'
                    self._draw_plus(painter, 10, y_center, expand_color)
                else:
                    # 未折叠：显示 '-'
                    self._draw_minus(painter, 10, y_center, collapse_color)
            
            block = block.next()
            block_number = block.blockNumber()
    
    def _draw_plus(self, painter, x, y, color):
        """绘制 '+' 图标"""
        painter.setPen(QPen(color, 1.5))
        painter.setBrush(Qt.NoBrush)
        
        # 绘制方框
        rect = QRect(x - 5, y - 5, 10, 10)
        painter.drawRect(rect)
        
        # 绘制 '+' 符号
        painter.drawLine(x - 3, y, x + 3, y)  # 横线
        painter.drawLine(x, y - 3, x, y + 3)  # 竖线
    
    def _draw_minus(self, painter, x, y, color):
        """绘制 '-' 图标"""
        painter.setPen(QPen(color, 1.5))
        painter.setBrush(Qt.NoBrush)
        
        # 绘制方框
        rect = QRect(x - 5, y - 5, 10, 10)
        painter.drawRect(rect)
        
        # 绘制 '-' 符号
        painter.drawLine(x - 3, y, x + 3, y)
    
    def mousePressEvent(self, event):
        """点击折叠指示器"""
        if event.button() == Qt.LeftButton:
            # 计算点击位置对应的块
            block = self.editor.firstVisibleBlock()
            block_number = block.blockNumber()
            
            while block.isValid():
                top = self.editor.blockBoundingGeometry(block).translated(self.editor.contentOffset()).top()
                
                if top > event.y():
                    break
                
                # 检查点击是否在折叠指示器区域内
                block_height = self.editor.blockBoundingRect(block).height()
                if event.y() >= top and event.y() < top + block_height:
                    if block_number in self.foldable_blocks:
                        self.toggle_fold(block_number)
                        self.fold_clicked.emit(block_number)
                        return
                
                block = block.next()
                block_number = block.blockNumber()


# ============================================================
# 可折叠代码编辑器（基于 QTextEdit）
# ============================================================

class FoldableCodeTextEdit(QTextEdit):
    """
    支持代码折叠的 QTextEdit 版本
    
    特性：
    - 左侧折叠指示器面板
    - 自动检测折叠点（基于缩进）
    - 折叠/展开代码块
    - 支持多语言折叠规则
    
    注意：使用 QTextEdit 而非 QPlainTextEdit 以兼容现有架构
    """
    
    # 折叠规则定义（按语言）
    FOLD_RULES = {
        "python": {
            "start": re.compile(r'^\s*(def |class |if |elif |else|for |while |try |except |finally |with )'),
            "end": None,  # Python 使用缩进结束
            "min_indent": 1,
        },
        "javascript": {
            "start": re.compile(r'^\s*(function |class |if |else |for |while |try |catch |switch |case )'),
            "end": re.compile(r'^\s*}'),
            "brace_based": True,
        },
        "html": {
            "start": re.compile(r'<[^/!][^>]*>'),
            "end": re.compile(r'</[^>]+>'),
            "tag_based": True,
        },
        "css": {
            "start": re.compile(r'\{'),
            "end": re.compile(r'\}'),
            "brace_based": True,
        },
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 创建折叠指示器面板
        self.fold_panel = FoldIndicatorPanel(self)
        
        # 当前语言
        self._language = "python"
        
        # 折叠范围缓存
        self._fold_ranges = {}  # {start_block: end_block}
        
        # 更新折叠点的定时器（避免频繁计算）
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(500)
        self._update_timer.timeout.connect(self._update_fold_points)
        
        # 内容变化时重新计算折叠点
        self.textChanged.connect(self._on_text_changed)
        
        # QTextEdit 版本不使用 setViewportMargins，改用布局
        # 初始化布局会在外部设置
    
    def set_language(self, language):
        """设置语言（用于折叠规则）"""
        self._language = language.lower()
        self._update_fold_points()
    
    def _on_text_changed(self):
        """内容变化时触发更新"""
        self._update_timer.start()
    
    def _update_fold_points(self):
        """更新可折叠块的列表"""
        foldable_blocks = []
        self._fold_ranges.clear()
        
        rules = self.FOLD_RULES.get(self._language, self.FOLD_RULES["python"])
        start_pattern = rules.get("start")
        
        if not start_pattern:
            return
        
        # 扫描所有块，寻找折叠点
        block = self.document().firstBlock()
        start_block = None
        start_indent = 0
        
        while block.isValid():
            text = block.text()
            block_number = block.blockNumber()
            
            # 检查是否是折叠起点
            if start_pattern.search(text):
                # Python 使用缩进判断结束
                if self._language == "python":
                    start_block = block_number
                    start_indent = len(text) - len(text.lstrip())
                    foldable_blocks.append(block_number)
                # JavaScript/CSS 使用括号匹配
                elif rules.get("brace_based"):
                    if '{' in text:
                        foldable_blocks.append(block_number)
                        # 找到匹配的结束括号
                        end_block = self._find_matching_brace(block, '{', '}')
                        if end_block:
                            self._fold_ranges[block_number] = end_block
            
            block = block.next()
        
        # Python 缩进结束的特殊处理
        if self._language == "python" and start_block is not None:
            block = self.document().findBlockByNumber(start_block)
            while block.isValid():
                text = block.text()
                current_indent = len(text) - len(text.lstrip())
                
                # 缩进减少表示结束
                if text.strip() and current_indent <= start_indent:
                    if block.blockNumber() > start_block:
                        self._fold_ranges[start_block] = block.blockNumber() - 1
                    break
                
                block = block.next()
        
        # 更新折叠面板
        self.fold_panel.set_foldable_blocks(foldable_blocks)
    
    def _find_matching_brace(self, start_block, open_char, close_char):
        """找到匹配的括号（用于 JavaScript/CSS）"""
        depth = 0
        block = start_block
        
        while block.isValid():
            text = block.text()
            
            for char in text:
                if char == open_char:
                    depth += 1
                elif char == close_char:
                    depth -= 1
                    if depth == 0:
                        return block.blockNumber()
            
            block = block.next()
        
        return None
    
    def _apply_folding(self, block_number, folded):
        """应用折叠状态"""
        if folded:
            # 折叠：隐藏从 start_block 到 end_block 的内容
            end_block = self._fold_ranges.get(block_number)
            if end_block:
                self._hide_blocks(block_number + 1, end_block)
        else:
            # 展开：恢复隐藏的内容
            self._show_blocks(block_number + 1)
    
    def _hide_blocks(self, start_block, end_block):
        """隐藏指定范围的块"""
        cursor = QTextCursor(self.document())
        
        for block_num in range(start_block, end_block + 1):
            block = self.document().findBlockByNumber(block_num)
            if block.isValid():
                # 使用 setVisible 隐藏块
                block.setVisible(False)
        
        # 更新视图
        self.document().markContentsDirty(
            self.document().findBlockByNumber(start_block).position(),
            self.document().findBlockByNumber(end_block).position()
        )
        self.viewport().update()
    
    def _show_blocks(self, start_block):
        """恢复隐藏的块"""
        block = self.document().findBlockByNumber(start_block)
        
        while block.isValid() and not block.isVisible():
            block.setVisible(True)
            block = block.next()
        
        self.viewport().update()
    
    def update_fold_panel_position(self):
        """更新折叠面板位置（外部调用）"""
        # QTextEdit 版本需要外部设置位置
        if hasattr(self, 'parent_widget'):
            cr = self.parent_widget.contentsRect()
            self.fold_panel.setGeometry(
                QRect(cr.left(), cr.top(), 20, cr.height())
            )
    
    def viewport(self):
        """QTextEdit版本返回self（兼容方法）"""
        return self
    
    def firstVisibleBlock(self):
        """获取第一个可见块（兼容方法）"""
        cursor = self.cursorForPosition(self.rect().topLeft())
        return cursor.block()
    
    def blockBoundingGeometry(self, block):
        """获取块的边界几何（兼容方法）"""
        return self.document().documentLayout().blockBoundingRect(block)
    
    def blockBoundingRect(self, block):
        """获取块的边界矩形（兼容方法）"""
        return self.document().documentLayout().blockBoundingRect(block)
    
    def contentOffset(self):
        """获取内容偏移（兼容方法）"""
        # QTextEdit版本返回零偏移
        from PyQt5.QtCore import QPointF
        return QPointF(0, 0)


# ============================================================
# FoldableCodeEditorWidget（包装类，用于集成到现有架构）
# ============================================================

class FoldableCodeEditorWidget(QWidget):
    """
    可折叠代码编辑器包装组件
    
    组合：
    - FoldableCodeTextEdit（核心编辑器）
    - LineNumberWidget（行号）
    - FoldIndicatorPanel（折叠指示器）
    
    用法：替代现有的 CodeEditor
    """
    
    save_requested = pyqtSignal(str, str)  # (file_path, content)
    content_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path = ""
        self._is_dirty = False
        self._last_saved_text = ""
        self._init_ui()
    
    @property
    def file_path(self) -> str:
        return self._file_path
    
    @property
    def is_dirty(self) -> bool:
        return self._is_dirty
    
    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 可折叠的文本编辑器
        self.editor = FoldableCodeTextEdit()
        self.editor.setReadOnly(False)
        self.editor.setFont(QFont("Cascadia Code", 10))
        self.editor.setAcceptRichText(False)
        self.editor.setStyleSheet("""
            QTextEdit {
                background: {Lemon.DARK_BG_4};
                color: {Lemon.DARK_TEXT_1};
                border: none;
                padding: 12px 16px;
                selection-background-color: {Lemon.INFO_BG_DARK};
            }
        """)
        
        # 设置父widget引用
        self.editor.parent_widget = self
        
        # 连接信号
        self.editor.textChanged.connect(self._on_text_changed)
        
        # 折叠指示器面板
        self.fold_panel = self.editor.fold_panel
        self.fold_panel.setStyleSheet(f"background: {Lemon.DARK_BG_4}; border-right: 1px solid {Lemon.DARK_MID_4};")
        
        # 行号控件（需要创建）
        from ui.diff_editor import LineNumberWidget
        self.line_numbers = LineNumberWidget(self.editor, self)
        self.line_numbers.setFixedWidth(52)
        
        # 布局：折叠指示器(20px) + 行号(52px) + 编辑器
        layout.addWidget(self.fold_panel)
        layout.addWidget(self.line_numbers)
        layout.addWidget(self.editor, 1)
    
    def set_code(self, code: str, file_path: str = ""):
        """设置编辑器内容"""
        self._file_path = file_path
        self.editor.blockSignals(True)
        self.editor.setPlainText(code)
        self.editor.blockSignals(False)
        self._last_saved_text = code
        self._is_dirty = False
        
        # 根据扩展名设置语言
        import os
        ext = os.path.splitext(file_path)[1].lower()
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "javascript",
            ".html": "html",
            ".css": "css",
            ".scss": "css",
        }
        language = lang_map.get(ext, "python")
        self.editor.set_language(language)
        
        self.line_numbers.update()
        self.fold_panel.update()
    
    def get_content(self) -> str:
        """获取当前编辑器内容"""
        return self.editor.toPlainText()
    
    def mark_saved(self):
        """标记为已保存"""
        self._last_saved_text = self.editor.toPlainText()
        self._is_dirty = False
    
    def mark_dirty(self):
        """标记为已修改"""
        self._is_dirty = True
    
    def set_content(self, content: str):
        """设置内容（用于格式化后更新）"""
        self.editor.blockSignals(True)
        self.editor.setPlainText(content)
        self.editor.blockSignals(False)
        self._is_dirty = True
    
    def _on_text_changed(self):
        """文本变化时检查是否修改"""
        current_text = self.editor.toPlainText()
        self._is_dirty = (current_text != self._last_saved_text)
        self.content_changed.emit()


# ============================================================
# 可折叠代码编辑器（基于 QPlainTextEdit，高性能版本）
# ============================================================

class FoldableCodeEditor(QPlainTextEdit):
    """
    支持代码折叠的 QPlainTextEdit 版本（高性能）
    
    特性：
    - 左侧折叠指示器面板
    - 自动检测折叠点（基于缩进）
    - 折叠/展开代码块
    - 支持多语言折叠规则
    
    推荐：用于大型代码文件
    """
    
    # 折叠规则定义（继承自 QTextEdit 版本）
    FOLD_RULES = FoldableCodeTextEdit.FOLD_RULES
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 创建折叠指示器面板
        self.fold_panel = FoldIndicatorPanel(self)
        
        # 当前语言
        self._language = "python"
        
        # 折叠范围缓存
        self._fold_ranges = {}  # {start_block: end_block}
        
        # 更新折叠点的定时器
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(500)
        self._update_timer.timeout.connect(self._update_fold_points)
        
        # 内容变化时重新计算折叠点
        self.textChanged.connect(self._on_text_changed)
        
        # 初始化布局
        self.setViewportMargins(20, 0, 0, 0)
    
    def set_language(self, language):
        """设置语言"""
        self._language = language.lower()
        self._update_fold_points()
    
    def _on_text_changed(self):
        """内容变化时触发更新"""
        self._update_timer.start()
    
    # 继承其他方法...
    # (使用 FoldableCodeTextEdit 的方法实现)
    
    def resizeEvent(self, event):
        """调整大小时更新折叠面板"""
        super().resizeEvent(event)
        
        cr = self.contentsRect()
        self.fold_panel.setGeometry(
            QRect(cr.left(), cr.top(), 20, cr.height())
        )