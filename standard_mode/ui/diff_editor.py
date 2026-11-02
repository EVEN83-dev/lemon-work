# -*- coding: utf-8 -*-
"""
代码编辑器 — 语法高亮 + Trae 风格 Diff 视图
- 删除行：红色背景 + 红色文字
- 新增行：绿色背景 + 绿色文字
- 正常行：语法高亮
"""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTextEdit,
    QLabel, QFrame, QSplitter, QPushButton, QScrollBar
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import (
    QTextCharFormat, QColor, QFont, QTextCursor, QSyntaxHighlighter, QPainter,
    QMouseEvent,
)

from ui.syntax_highlighter import create_highlighter
from ui.design.tokens import Lemon

C = {
    'bg': Lemon.DARK_BG_2,
    'border': 'Lemon.DARK_BG_4',
    'text': Lemon.DARK_TEXT_1,
    'text_dim': Lemon.STATUS_OFFLINE,
    'text_muted': Lemon.SYNTAX_COMMENT,
    'green': Lemon.STATUS_ONLINE,
    'green_bg': '#0d2818',
    'green_bg_light': Lemon.DIFF_ADD_LINE_BG,
    'red': Lemon.ERROR,
    'red_bg': '#2d0f14',
    'red_bg_light': Lemon.DIFF_REMOVE_LINE_BG,
    'accent': Lemon.STATUS_RUNNING,
    'gutter_bg': Lemon.DARK_BG_2,
    'gutter_green': '#1a4026',
    'gutter_red': '#3d1a1f',
    'gutter_add': Lemon.STATUS_ONLINE,
    'gutter_del': Lemon.ERROR,
}


class DiffGutterSignWidget(QWidget):
    """行号区域 — 绿色/红色背景标记 diff 行"""
    def __init__(self):
        super().__init__()
        self.setFixedWidth(56)
        self.setStyleSheet(f"background: {C['gutter_bg']}; border-right: 1px solid {C['border']};")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._label = QLabel("")
        self._label.setAlignment(Qt.AlignTop | Qt.AlignRight)
        self._label.setFont(QFont("Cascadia Code", 12))
        self._label.setStyleSheet(f"color: {C['text_muted']}; background: transparent; padding: 12px 10px 0 0;")
        self._layout.addWidget(self._label)

    def set_numbers(self, text):
        self._label.setText(text)

    def set_html(self, html):
        self._label.setText(html)
        self._label.setTextFormat(Qt.RichText)


class LineNumberWidget(QWidget):
    """自定义行号控件 — 使用 cursorRect 精确对齐"""
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setFixedWidth(52)
        self.setStyleSheet(f"background: {C['gutter_bg']};")
        editor.verticalScrollBar().valueChanged.connect(self.update)
        editor.document().blockCountChanged.connect(self.update)
        editor.textChanged.connect(self.update)
        # ★ 直接从编辑器获取字体，确保完全一致
        self._update_font()
        editor.currentCharFormatChanged.connect(self._update_font)
    
    def _update_font(self):
        """同步编辑器字体"""
        self._font = self.editor.currentFont()
        self._font_metrics = self.editor.fontMetrics()
        self.update()

    def mousePressEvent(self, event):
        """V6.0: 点击行号区域折叠/展开代码块。"""
        if event.button() == Qt.LeftButton:
            doc = self.editor.document()
            fm = self.editor.fontMetrics()
            block = doc.begin()
            while block.isValid():
                if block.isVisible():
                    cursor = QTextCursor(block)
                    cursor.movePosition(QTextCursor.StartOfBlock)
                    rect = self.editor.cursorRect(cursor)
                    y_offset = rect.top() + (rect.height() - fm.height()) // 2
                    if y_offset <= event.y() <= y_offset + fm.height():
                        block_text = block.text()
                        stripped = block_text.rstrip()
                        if stripped.endswith(':') or stripped.endswith('{'):
                            code_editor = self.parent()
                            if hasattr(code_editor, 'toggle_fold'):
                                code_editor.toggle_fold(block.blockNumber())
                        break
                block = block.next()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(C['gutter_bg']))
        
        painter.setPen(QColor(C['border']))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        
        painter.setPen(QColor(C['text_muted']))
        painter.setFont(self._font)
        fm = self._font_metrics
        
        doc = self.editor.document()
        viewport = self.editor.viewport()
        
        doc_margin = doc.documentMargin()
        code_editor = self.parent()
        folded = getattr(code_editor, '_folded_blocks', set())
        
        block = doc.begin()
        while block.isValid():
            if block.isVisible():
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.StartOfBlock)
                rect = self.editor.cursorRect(cursor)
                
                if rect.bottom() >= 0 and rect.top() <= self.editor.viewport().height():
                    line_num = block.blockNumber() + 1
                    text = str(line_num)
                    y_offset = rect.top() + (rect.height() - fm.height()) // 2
                    painter.drawText(4, y_offset, self.width() - 14, fm.height(),
                                   Qt.AlignRight | Qt.AlignTop, text)
                    
                    block_text = block.text()
                    stripped = block_text.rstrip()
                    if stripped.endswith(':') or stripped.endswith('{'):
                        next_block = block.next()
                        if next_block.isValid():
                            next_text = next_block.text()
                            next_indent = len(next_text) - len(next_text.lstrip())
                            cur_indent = len(block_text) - len(block_text.lstrip())
                            if next_indent > cur_indent:
                                bx = self.width() - 10
                                by = y_offset + fm.height() // 2
                                painter.setPen(QColor(C['text_dim']))
                                if block.blockNumber() in folded:
                                    painter.drawText(bx - 4, by + 4, "▶")
                                else:
                                    painter.drawText(bx - 4, by + 4, "▼")
                                painter.setPen(QColor(C['text_muted']))
            
            block = block.next()
        painter.end()


class CodeEditor(QWidget):
    """
    代码编辑器（v2.0 — 支持真正的文本编辑 / v0.7.0 LSP 集成）

    功能：
    - 可编辑文本 + 语法高亮
    - 实时行号更新
    - 撤销/重做 (Ctrl+Z / Ctrl+Y)
    - 当前行高亮
    - Tab 缩进支持
    - 文件修改追踪（dirty flag）
    - Ctrl+S 保存信号
    - v0.7.0: LSP 实时补全（输入 "." 或 "::" 触发）
    - v0.7.0: Ctrl+点击跳转定义
    - v0.7.0: 诊断波浪线标注（红色错误/黄色警告）
    """

    save_requested = pyqtSignal(str, str)  # (file_path, content)
    content_changed = pyqtSignal()
    # ★ v0.7.0 LSP 信号
    lsp_completion_requested = pyqtSignal(str, int, int)   # (file_path, line, character)
    lsp_definition_requested = pyqtSignal(str, int, int)   # (file_path, line, character)
    lsp_didchange = pyqtSignal(str, str, int)              # (file_path, content, version)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path = ""
        self._is_dirty = False
        self._last_saved_text = ""
        self._doc_version = 0
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._emit_didchange)
        self._diagnostics: list = []
        self._bracket_highlight_timer = QTimer(self)
        self._bracket_highlight_timer.setSingleShot(True)
        self._bracket_highlight_timer.setInterval(800)
        self._bracket_highlight_timer.timeout.connect(self._clear_bracket_highlight)
        self._folded_blocks: set = set()
        self._init_ui()
        self._init_folding()
        self.editor.installEventFilter(self)
    
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

        # 可编辑的文本编辑器
        self.editor = QTextEdit()
        self.editor.setReadOnly(False)  # ★ 可编辑
        self.editor.setFont(QFont("Cascadia Code", 13))
        self.editor.setTabStopWidth(32)  # 4空格缩进
        self.editor.setAcceptRichText(False)
        self.editor.setStyleSheet(f"""
            QTextEdit {{
                background: {C['bg']};
                color: {C['text']};
                border: none;
                padding: 12px 16px;
                selection-background-color: {Lemon.INFO_BG_DARK};
            }}
        """)
        self.highlighter = create_highlighter("", self.editor.document())
        
        # 连接文本变化信号
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor, 1)
        
        # ★ 自定义行号控件（随滚动同步）
        self.line_numbers = LineNumberWidget(self.editor, self)
        self.line_numbers.setStyleSheet(f"background: {C['gutter_bg']}; border-right: 1px solid {C['border']};")
        layout.insertWidget(0, self.line_numbers)

    def _init_folding(self):
        self._folding_enabled = True
        self._fold_points = []
        self._current_fold_level = 0
        self.editor.document().blockCountChanged.connect(self._update_fold_points)

    def _update_fold_points(self):
        if not self._folding_enabled:
            return
        doc = self.editor.document()
        self._fold_points = []
        block = doc.begin()
        prev_indent = -1
        while block.isValid():
            text = block.text().strip()
            current_indent = len(block.text()) - len(block.text().lstrip()) if text else 0
            if text and current_indent > prev_indent and prev_indent >= 0:
                self._fold_points.append({
                    'block_number': block.blockNumber(),
                    'indent': current_indent,
                    'text': text[:50]
                })
            prev_indent = current_indent if text else -1
            block = block.next()

    def toggle_fold(self, block_number: int):
        if not self._folding_enabled:
            return
        if block_number in self._folded_blocks:
            self._folded_blocks.discard(block_number)
        else:
            self._folded_blocks.add(block_number)
        self._apply_folding()

    def _apply_folding(self):
        doc = self.editor.document()
        block = doc.begin()
        hide = False
        hide_indent = -1
        while block.isValid():
            bn = block.blockNumber()
            text = block.text().strip()
            current_indent = len(block.text()) - len(block.text().lstrip()) if text else 0
            if bn in self._folded_blocks:
                hide = True
                hide_indent = current_indent
                block.setVisible(True)
                block = block.next()
                continue
            if hide:
                if text and current_indent <= hide_indent:
                    hide = False
                    block.setVisible(True)
                else:
                    block.setVisible(False)
            else:
                block.setVisible(True)
            block = block.next()
        self.editor.update()
    
    def set_code(self, code: str, file_path: str = ""):
        """设置编辑器内容"""
        self._file_path = file_path
        self.editor.blockSignals(True)
        self.editor.setPlainText(code)
        self.editor.blockSignals(False)
        self._last_saved_text = code
        self._is_dirty = False
        self.line_numbers.update()
        # 根据文件扩展名切换高亮器
        self.highlighter.setDocument(None)
        self.highlighter = create_highlighter(file_path, self.editor.document())
    
    def get_content(self) -> str:
        """获取当前编辑器内容"""
        return self.editor.toPlainText()

    def set_file_content(self, file_path: str) -> None:
        """V6.0: 从磁盘读取文件并设置编辑器内容。"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            self.set_code(content, file_path=file_path)
        except Exception as e:
            self.set_code("", file_path=file_path)

    def get_file_content(self) -> str:
        """V6.0: 获取编辑器内容（与 get_content 等价，API 对称）。"""
        return self.editor.toPlainText()

    def _handle_key_press(self, event) -> None:
        """V6.0: 拦截按键 — 自动缩进 + 括号匹配。"""
        key = event.key()
        text = event.text()
        if key == Qt.Key_Return or key == Qt.Key_Enter:
            self._do_auto_indent()
            return
        if text in (')', ']', '}'):
            self._do_bracket_match(text)
            self.editor.keyPressEvent(event)
            return
        self.editor.keyPressEvent(event)

    def _do_auto_indent(self) -> None:
        """V6.0: 按回车时自动缩进 — 继承上一行缩进，冒号/花括号后额外4空格。"""
        cursor = self.editor.textCursor()
        block = cursor.block()
        text = block.text()
        indent = ""
        for ch in text:
            if ch in (' ', '\t'):
                indent += ch
            else:
                break
        stripped = text.rstrip()
        if stripped.endswith(':') or stripped.endswith('{'):
            indent += "    "
        cursor.insertText("\n" + indent)
        self.editor.setTextCursor(cursor)

    def _do_bracket_match(self, closing: str) -> None:
        """V6.0: 输入闭合括号时高亮匹配的开放括号。"""
        pairs = {')': '(', ']': '[', '}': '{'}
        open_ch = pairs.get(closing)
        if not open_ch:
            return
        cursor = self.editor.textCursor()
        doc = self.editor.document()
        pos = cursor.position()
        depth = 1
        search_pos = pos - 1
        while search_pos >= 0 and depth > 0:
            block = doc.findBlock(search_pos)
            if not block.isValid():
                break
            block_text = block.text()
            block_start = block.position()
            rel_pos = search_pos - block_start
            if 0 <= rel_pos < len(block_text):
                ch = block_text[rel_pos]
                if ch == closing:
                    depth += 1
                elif ch == open_ch:
                    depth -= 1
                if depth == 0:
                    match_pos = block_start + rel_pos
                    sel = QTextEdit.ExtraSelection()
                    sel.cursor = QTextCursor(doc)
                    sel.cursor.setPosition(match_pos)
                    sel.cursor.setPosition(match_pos + 1, QTextCursor.KeepAnchor)
                    sel.format.setBackground(QColor(Lemon.BRAND_LEMON + "44"))
                    sel.format.setForeground(QColor(Lemon.BRAND_LEMON))
                    self.editor.setExtraSelections([sel])
                    self._bracket_highlight_timer.start()
                    break
            search_pos -= 1

    def _clear_bracket_highlight(self) -> None:
        """V6.0: 清除括号匹配高亮。"""
        self.editor.setExtraSelections([])

    def toggle_fold(self, block_number: int) -> None:
        """V6.0: 切换代码折叠 — 基于缩进级别。"""
        doc = self.editor.document()
        block = doc.findBlockByNumber(block_number)
        if not block.isValid():
            return
        text = block.text()
        base_indent = len(text) - len(text.lstrip())
        if base_indent >= len(text):
            return
        is_folded = block_number in self._folded_blocks
        if is_folded:
            self._folded_blocks.discard(block_number)
        else:
            self._folded_blocks.add(block_number)
        next_block = block.next()
        while next_block.isValid():
            next_text = next_block.text()
            next_indent = len(next_text) - len(next_text.lstrip())
            if next_indent <= base_indent and next_text.strip():
                break
            next_block.setVisible(is_folded)
            next_block = next_block.next()
        self.editor.document().markContentsDirty(block_number, 1)
        self.line_numbers.update()
    
    def mark_saved(self):
        """标记为已保存"""
        self._last_saved_text = self.editor.toPlainText()
        self._is_dirty = False
    
    def _on_text_changed(self):
        """文本变化处理 — v0.7.0 增加防抖 didChange"""
        self.line_numbers.update()
        current_text = self.editor.toPlainText()
        self._is_dirty = (current_text != self._last_saved_text)
        self.content_changed.emit()
        # ★ v0.7.0: 防抖触发 textDocument/didChange
        if self._file_path:
            self._debounce_timer.start()
    
    def go_to_line(self, line_num: int):
        """跳转到指定行"""
        doc = self.editor.document()
        if 1 <= line_num <= doc.blockCount():
            block = doc.findBlockByNumber(line_num - 1)
            cursor = self.editor.textCursor()
            cursor.setPosition(block.position())
            self.editor.setTextCursor(cursor)
            self.editor.setFocus()
            return True
        return False
    
    def get_current_line(self) -> int:
        """获取当前光标所在行"""
        cursor = self.editor.textCursor()
        return cursor.blockNumber() + 1
    
    def undo(self):
        self.editor.undo()
    
    def redo(self):
        self.editor.redo()
    
    def cut(self):
        self.editor.cut()
    
    def copy(self):
        self.editor.copy()
    
    def paste(self):
        self.editor.paste()
    
    def select_all(self):
        self.editor.selectAll()
    
    def find_text(self, text: str, forward: bool = True) -> bool:
        """在编辑器中查找文本"""
        flags = QTextDocument.FindFlags()
        if not forward:
            flags |= QTextDocument.FindBackward
        found = self.editor.find(text, flags)
        return found
    
    def replace_text(self, find_text: str, replace_text: str, replace_all: bool = False):
        """替换文本"""
        if replace_all:
            content = self.editor.toPlainText()
            new_content = content.replace(find_text, replace_text)
            self.editor.setPlainText(new_content)
            return content.count(find_text)
        else:
            cursor = self.editor.textCursor()
            if cursor.hasSelection():
                cursor.insertText(replace_text)
                return 1
            return 0
    
    def set_focus(self):
        self.editor.setFocus()

    # ============================================================
    # v0.7.0 LSP 集成
    # ============================================================

    def _emit_didchange(self):
        """防抖后发送 textDocument/didChange 通知"""
        if not self._file_path:
            return
        self._doc_version += 1
        self.lsp_didchange.emit(self._file_path, self.editor.toPlainText(), self._doc_version)

    def eventFilter(self, obj, event):
        """事件过滤器 — 捕获按键和鼠标事件用于 LSP + V6.0编辑器增强。"""
        if obj is self.editor:
            if event.type() == event.KeyPress:
                key = event.key()
                text = event.text()
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    self._do_auto_indent()
                    return True
                if text in (')', ']', '}'):
                    self.editor.keyPressEvent(event)
                    self._do_bracket_match(text)
                    return True
            if event.type() == event.KeyRelease:
                self._handle_key_release(event)
            elif event.type() == event.MouseButtonPress:
                self._handle_mouse_press(event)
        return super().eventFilter(obj, event)

    def _handle_key_release(self, event):
        """按键释放处理 — 检测 "." 或 "::" 触发补全"""
        if not self._file_path:
            return
        key = event.key()
        text = event.text()
        # 检测补全触发字符
        trigger = False
        if text == ".":
            trigger = True
        elif text == ":":
            # 检查是否输入了 "::"
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor)
            if cursor.selectedText().endswith("::"):
                trigger = True
        # 也支持手动触发 (Ctrl+Space)
        if key == Qt.Key_Space and (event.modifiers() & Qt.ControlModifier):
            trigger = True

        if trigger:
            cursor = self.editor.textCursor()
            line = cursor.blockNumber()
            character = cursor.positionInBlock()
            self.lsp_completion_requested.emit(self._file_path, line, character)

    def _handle_mouse_press(self, event):
        """鼠标点击处理 — Ctrl+Click 跳转定义"""
        if not self._file_path:
            return
        # Ctrl+左键点击 → 跳转定义
        if event.button() == Qt.LeftButton and (event.modifiers() & Qt.ControlModifier):
            # 将鼠标位置转换为光标位置
            cursor = self.editor.cursorForPosition(event.pos())
            if cursor:
                line = cursor.blockNumber()
                character = cursor.positionInBlock()
                self.lsp_definition_requested.emit(self._file_path, line, character)

    def update_diagnostics(self, file_path: str, diagnostics: list):
        """更新诊断标注 — 波浪线下划线（红色错误/黄色警告）

        Args:
            file_path: 文件路径
            diagnostics: [Diagnostic] 列表，每个含 range / message / severity
        """
        if file_path != self._file_path:
            return
        self._diagnostics = diagnostics

        # 清除旧标注 — 通过重新设置整个文档格式
        cursor = QTextCursor(self.editor.document())
        cursor.select(QTextCursor.Document)
        fmt = QTextCharFormat()
        fmt.setFontUnderline(False)
        cursor.mergeCharFormat(fmt)

        # 应用新标注
        for diag in diagnostics:
            try:
                start_line = diag.range.start.line
                start_char = diag.range.start.character
                end_line = diag.range.end.line
                end_char = diag.range.end.character
                # 将 LSP 行号（0-based）转换为文档位置
                doc = self.editor.document()
                start_block = doc.findBlockByNumber(start_line)
                end_block = doc.findBlockByNumber(end_line)
                if not start_block.isValid() or not end_block.isValid():
                    continue
                start_pos = start_block.position() + start_char
                end_pos = end_block.position() + end_char
                if end_pos <= start_pos:
                    end_pos = start_pos + 1

                cursor = QTextCursor(doc)
                cursor.setPosition(start_pos)
                cursor.setPosition(end_pos, QTextCursor.KeepAnchor)

                fmt = QTextCharFormat()
                # severity: 1=Error(红), 2=Warning(黄), 3=Info(蓝), 4=Hint(灰)
                if diag.severity == 1:
                    fmt.setUnderlineColor(QColor("{Lemon.ERROR}"))
                    fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
                    fmt.setToolTip(f"❌ {diag.message}")
                elif diag.severity == 2:
                    fmt.setUnderlineColor(QColor("Lemon.ACCENT_GOLD"))
                    fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
                    fmt.setToolTip(f"⚠ {diag.message}")
                else:
                    fmt.setUnderlineColor(QColor("{Lemon.STATUS_RUNNING}"))
                    fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
                    fmt.setToolTip(f"ℹ {diag.message}")
                cursor.mergeCharFormat(fmt)
            except Exception:
                continue


class DiffGutterWidget(QWidget):
    """Diff 行号控件 — 斑马条纹风格，左侧颜色条标记修改行"""
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setFixedWidth(60)
        self._diff_lines = []  # [(status, line), ...]
        self._top_padding = 12
        editor.verticalScrollBar().valueChanged.connect(self.update)
        editor.document().blockCountChanged.connect(self.update)

    def set_diff_lines(self, diff_lines):
        self._diff_lines = diff_lines
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(C['gutter_bg']))

        # 右侧分隔线
        painter.setPen(QColor(C['border']))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

        font = QFont("Cascadia Code", 13)
        painter.setFont(font)
        fm = painter.fontMetrics()
        line_height = fm.height()

        # 获取可见行范围
        cursor = self.editor.cursorForPosition(self.editor.rect().topLeft())
        first_block = cursor.block()
        last_block = self.editor.cursorForPosition(self.editor.rect().bottomLeft()).block()

        doc = self.editor.document()
        first_block_pos = doc.documentLayout().blockBoundingRect(first_block).top()
        viewport_top = self.editor.verticalScrollBar().value()
        y_offset = -(first_block_pos - viewport_top) + self._top_padding

        block = first_block
        block_num = block.blockNumber()
        y = y_offset

        while block.isValid() and block_num <= last_block.blockNumber():
            if block.isVisible():
                status = 'same'
                if block_num < len(self._diff_lines):
                    status = self._diff_lines[block_num][0]

                # 斑马条纹：左侧颜色条
                if status == 'add':
                    painter.fillRect(0, int(y), 4, line_height, QColor(C['green']))
                    painter.fillRect(4, int(y), self.width() - 4, line_height, QColor(C['green_bg']))
                    painter.setPen(QColor(C['green']))
                elif status == 'remove':
                    painter.fillRect(0, int(y), 4, line_height, QColor(C['red']))
                    painter.fillRect(4, int(y), self.width() - 4, line_height, QColor(C['red_bg']))
                    painter.setPen(QColor(C['red']))
                else:
                    painter.setPen(QColor(C['text_muted']))

                # 行号
                text = str(block_num + 1)
                painter.drawText(8, int(y + fm.ascent()), self.width() - 14, line_height,
                               Qt.AlignRight, text)

                y += line_height
            block = block.next()
            block_num += 1


class DiffEditor(QWidget):
    """Trae 风格 Diff 视图 — 全文件显示 + 斑马条纹 + 差异导航 + 修改原因"""

    apply_requested = pyqtSignal(str, str)  # (file_path, new_content)
    discard_requested = pyqtSignal(str)      # (file_path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._diff_lines = None
        self._new_content = ""
        self._file_path = ""
        self._diff_positions = []  # 差异行索引列表
        self._current_diff_idx = -1
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ===== 顶部工具栏 =====
        toolbar = QFrame()
        toolbar.setFixedHeight(44)
        toolbar.setStyleSheet(f"background: {C['gutter_bg']}; border-bottom: 1px solid {C['border']};")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(14, 6, 14, 6)
        tb_layout.setSpacing(10)

        # 文件图标 + 路径
        self.file_icon = QLabel("📝")
        self.file_icon.setStyleSheet("font-size: 16px; background: transparent;")
        tb_layout.addWidget(self.file_icon)

        self.file_label = QLabel("")
        self.file_label.setStyleSheet(f"color: {C['text']}; font-size: 14px; font-weight: 600; background: transparent;")
        tb_layout.addWidget(self.file_label)

        # 差异统计
        self.diff_stat_label = QLabel("")
        self.diff_stat_label.setStyleSheet(f"""
            color: {C['text_dim']}; 
            font-size: 12px; 
            background: rgba(255,255,255,0.05);
            padding: 4px 10px;
            border-radius: 4px;
        """)
        tb_layout.addWidget(self.diff_stat_label)

        tb_layout.addStretch()

        # 差异导航按钮
        self.prev_btn = QPushButton("▲ 上一处")
        self.next_btn = QPushButton("下一处 ▼")
        self.prev_btn.setToolTip("跳转到上一个修改位置")
        self.next_btn.setToolTip("跳转到下一个修改位置")
        for btn in [self.prev_btn, self.next_btn]:
            btn.setFixedHeight(28)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255,255,255,0.06);
                    color: {C['text_dim']};
                    border: 1px solid {C['border']};
                    border-radius: 4px;
                    padding: 0 12px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background: rgba(255,255,255,0.1);
                    color: {C['text']};
                    border-color: {C['accent']};
                }}
                QPushButton:disabled {{
                    color: {C['text_muted']};
                    background: transparent;
                }}
            """)
        self.prev_btn.clicked.connect(self._prev_diff)
        self.next_btn.clicked.connect(self._next_diff)
        tb_layout.addWidget(self.prev_btn)
        tb_layout.addWidget(self.next_btn)

        # 分隔线
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {C['border']};")
        tb_layout.addWidget(sep)

        # 操作按钮
        self.apply_btn = QPushButton("✓ 应用修改")
        self.discard_btn = QPushButton("✗ 放弃")
        self.apply_btn.setToolTip("将修改应用到原文件")
        self.discard_btn.setToolTip("放弃所有修改，恢复原文件")
        self.apply_btn.setFixedHeight(28)
        self.discard_btn.setFixedHeight(28)
        self.apply_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(63, 185, 80, 0.15);
                color: {C['green']};
                border: 1px solid rgba(63, 185, 80, 0.3);
                border-radius: 4px;
                padding: 0 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: rgba(63, 185, 80, 0.25);
            }}
        """)
        self.discard_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(248, 81, 73, 0.1);
                color: {C['red']};
                border: 1px solid rgba(248, 81, 73, 0.25);
                border-radius: 4px;
                padding: 0 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: rgba(248, 81, 73, 0.2);
            }}
        """)
        self.apply_btn.clicked.connect(self._on_apply)
        self.discard_btn.clicked.connect(self._on_discard)
        tb_layout.addWidget(self.discard_btn)
        tb_layout.addWidget(self.apply_btn)

        layout.addWidget(toolbar)

        # ===== 修改原因展示区 =====
        self.reason_panel = QFrame()
        self.reason_panel.setMaximumHeight(0)
        self.reason_panel.setStyleSheet(f"background: rgba(255,105,0,0.06); border-bottom: 1px solid rgba(255,105,0,0.15);")
        reason_layout = QVBoxLayout(self.reason_panel)
        reason_layout.setContentsMargins(16, 10, 16, 10)
        reason_layout.setSpacing(6)

        reason_header = QHBoxLayout()
        self.reason_icon = QLabel("💡")
        self.reason_icon.setStyleSheet("font-size: 14px; background: transparent;")
        self.reason_title = QLabel("修改说明")
        self.reason_title.setStyleSheet(f"color: {Lemon.BRAND_ORANGE_LIGHT}; font-size: 13px; font-weight: 600; background: transparent;")
        reason_header.addWidget(self.reason_icon)
        reason_header.addWidget(self.reason_title)
        reason_header.addStretch()
        reason_layout.addLayout(reason_header)

        self.reason_text = QLabel("")
        self.reason_text.setWordWrap(True)
        self.reason_text.setStyleSheet(f"color: {C['text_dim']}; font-size: 13px; line-height: 1.6; background: transparent;")
        reason_layout.addWidget(self.reason_text)

        layout.addWidget(self.reason_panel)

        # ===== 编辑器区域 =====
        editor_area = QHBoxLayout()
        editor_area.setContentsMargins(0, 0, 0, 0)
        editor_area.setSpacing(0)

        # 行号（斑马条纹）
        self.line_numbers = DiffGutterWidget(None, self)
        editor_area.addWidget(self.line_numbers)

        # 编辑器
        self.editor = QTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setFont(QFont("Cascadia Code", 13))
        self.editor.setStyleSheet(f"""
            QTextEdit {{
                background: {C['bg']};
                color: {C['text']};
                border: none;
                padding: 12px 16px;
                selection-background-color: {Lemon.INFO_BG_DARK};
            }}
        """)
        editor_area.addWidget(self.editor, 1)

        layout.addLayout(editor_area, 1)

        # 把 editor 传给行号控件
        self.line_numbers.editor = self.editor

    def set_diff(self, file_path, new_content, diff_lines, reason=""):
        """设置 diff 显示 — Trae 风格全文件高亮 + 斑马条纹"""
        self._diff_lines = diff_lines
        self._new_content = new_content
        self._file_path = file_path
        self._diff_positions = []

        # 更新工具栏
        self.file_label.setText(file_path.split('/')[-1])
        self.file_label.setToolTip(file_path)

        # 统计差异
        add_count = sum(1 for s, _ in diff_lines if s == 'add')
        del_count = sum(1 for s, _ in diff_lines if s == 'remove')

        # 计算差异位置
        for i, (s, _) in enumerate(diff_lines):
            if s in ('add', 'remove'):
                self._diff_positions.append(i)

        # 更新统计标签
        stat_parts = []
        if add_count > 0:
            stat_parts.append(f'<span style="color:{C["green"]};">+{add_count} 新增</span>')
        if del_count > 0:
            stat_parts.append(f'<span style="color:{C["red"]};">-{del_count} 删除</span>')
        if stat_parts:
            self.diff_stat_label.setText("  ".join(stat_parts))
            self.diff_stat_label.setTextFormat(Qt.RichText)
        else:
            self.diff_stat_label.setText("无变更")

        # 更新导航按钮状态
        has_diffs = len(self._diff_positions) > 0
        self.prev_btn.setEnabled(has_diffs)
        self.next_btn.setEnabled(has_diffs)
        self.apply_btn.setEnabled(has_diffs)
        self.discard_btn.setEnabled(has_diffs)

        # 修改原因
        if reason:
            self.reason_panel.setMaximumHeight(16777215)
            self.reason_text.setText(reason)
        else:
            self.reason_panel.setMaximumHeight(0)

        # 渲染编辑器内容
        self.editor.clear()
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.Start)

        for status, line in diff_lines:
            fmt = QTextCharFormat()
            fmt.setFont(QFont("Cascadia Code", 13))

            if status == "add":
                fmt.setBackground(QColor(C['green_bg_light']))
                fmt.setForeground(QColor(C['green']))
                prefix = "+"
            elif status == "remove":
                fmt.setBackground(QColor(C['red_bg_light']))
                fmt.setForeground(QColor(C['red']))
                prefix = "−"
            else:
                fmt.setForeground(QColor(C['text_dim']))
                prefix = " "

            cursor.insertText(f"{prefix} {line}\n", fmt)

        # 更新行号控件
        self.line_numbers.set_diff_lines(diff_lines)

        # 跳转到第一处差异
        if self._diff_positions:
            self._current_diff_idx = 0
            self._go_to_diff(0)

    def set_code(self, code: str, file_path: str = ""):
        """纯代码显示模式（无 diff）"""
        self._file_path = file_path
        self._diff_lines = []
        self._diff_positions = []
        self._new_content = code

        if file_path:
            self.file_label.setText(file_path.split('/')[-1])
            self.file_label.setToolTip(file_path)
        self.diff_stat_label.setText("原始文件")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.discard_btn.setEnabled(False)
        self.reason_panel.setMaximumHeight(0)

        self.editor.setPlainText(code)
        self.line_numbers.set_diff_lines([])

    def _prev_diff(self):
        """上一处差异"""
        if not self._diff_positions:
            return
        self._current_diff_idx = (self._current_diff_idx - 1) % len(self._diff_positions)
        self._go_to_diff(self._current_diff_idx)

    def _next_diff(self):
        """下一处差异"""
        if not self._diff_positions:
            return
        self._current_diff_idx = (self._current_diff_idx + 1) % len(self._diff_positions)
        self._go_to_diff(self._current_diff_idx)

    def _go_to_diff(self, idx):
        """跳转到指定差异行"""
        if 0 <= idx < len(self._diff_positions):
            line_num = self._diff_positions[idx]
            doc = self.editor.document()
            block = doc.findBlockByNumber(line_num)
            cursor = self.editor.textCursor()
            cursor.setPosition(block.position())
            self.editor.setTextCursor(cursor)
            self.editor.centerCursor()

    def _on_apply(self):
        """应用修改"""
        self.apply_requested.emit(self._file_path, self._new_content)

    def _on_discard(self):
        """放弃修改"""
        self.discard_requested.emit(self._file_path)


class SideBySideDiffEditor(QWidget):
    """双栏并排对比视图 — 类似 PyCharm Compare With
    - 左栏：原始文件（只读）
    - 右栏：修改后文件（只读）
    - 同步滚动 + 差异行高亮 + 行号映射
    - 差异导航（上一个/下一个差异）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._left_lines = []
        self._right_lines = []
        self._diff_map = []  # [(left_idx, right_idx, status), ...]
        self._diff_positions = []  # 差异行在编辑器中的位置索引
        self._current_diff_idx = -1
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ===== 顶部工具栏 =====
        toolbar = QFrame()
        toolbar.setFixedHeight(36)
        toolbar.setStyleSheet(f"background: {C['gutter_bg']}; border-bottom: 1px solid {C['border']};")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 4, 10, 4)
        tb_layout.setSpacing(8)

        self.title_label = QLabel("文件对比")
        self.title_label.setStyleSheet(f"color: {C['text_dim']}; font-size: 12px; font-weight: 600; background: transparent;")
        tb_layout.addWidget(self.title_label)

        tb_layout.addStretch()

        self.diff_count_label = QLabel("")
        self.diff_count_label.setStyleSheet(f"color: {C['text_muted']}; font-size: 11px; background: transparent;")
        tb_layout.addWidget(self.diff_count_label)

        # 差异导航按钮
        for icon, tip, slot in [
            ("▲", "上一个差异", self._prev_diff),
            ("▼", "下一个差异", self._next_diff),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(26, 26)
            btn.setToolTip(tip)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C['text_dim']};
                    border: 1px solid {C['border']};
                    border-radius: 3px;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background: Lemon.DARK_BG_3;
                    color: {C['accent']};
                }}
            """)
            btn.clicked.connect(slot)
            tb_layout.addWidget(btn)

        layout.addWidget(toolbar)

        # ===== 双栏内容区 =====
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {C['border']};
            }}
        """)

        # 左栏 — 原始文件
        left_panel = self._create_panel("原始文件")
        splitter.addWidget(left_panel)

        # 右栏 — 修改后文件
        right_panel = self._create_panel("修改后文件")
        splitter.addWidget(right_panel)

        splitter.setSizes([500, 500])
        layout.addWidget(splitter, 1)

        # 同步滚动
        self._sync_scroll = True
        self._left_editor.verticalScrollBar().valueChanged.connect(self._on_left_scroll)
        self._right_editor.verticalScrollBar().valueChanged.connect(self._on_right_scroll)

    def _create_panel(self, label_text):
        """创建对比面板（行号 + 编辑器）"""
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # 标签
        label = QLabel(f"  {label_text}")
        label.setFixedHeight(24)
        label.setStyleSheet(f"background: {C['gutter_bg']}; color: {C['text_dim']}; font-size: 11px; font-weight: 600; border-bottom: 1px solid {C['border']};")
        panel_layout.addWidget(label)

        # 编辑器区域（行号 + 编辑器）
        editor_area = QWidget()
        ea_layout = QHBoxLayout(editor_area)
        ea_layout.setContentsMargins(0, 0, 0, 0)
        ea_layout.setSpacing(0)

        # 行号
        gutter = QFrame()
        gutter.setFixedWidth(52)
        gutter.setStyleSheet(f"background: {C['gutter_bg']}; border-right: 1px solid {C['border']};")
        g_layout = QVBoxLayout(gutter)
        g_layout.setContentsMargins(0, 12, 10, 0)
        g_layout.setSpacing(0)

        line_numbers = QLabel("")
        line_numbers.setAlignment(Qt.AlignTop | Qt.AlignRight)
        line_numbers.setFont(QFont("Cascadia Code", 13))
        line_numbers.setStyleSheet(f"color: {C['text_muted']}; background: transparent;")
        g_layout.addWidget(line_numbers)
        ea_layout.addWidget(gutter)

        # 编辑器
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setFont(QFont("Cascadia Code", 13))
        editor.setStyleSheet(f"""
            QTextEdit {{
                background: {C['bg']};
                color: {C['text']};
                border: none;
                padding: 12px 16px;
                selection-background-color: {Lemon.INFO_BG_DARK};
            }}
        """)
        ea_layout.addWidget(editor, 1)

        panel_layout.addWidget(editor_area, 1)

        # 存储引用
        if label_text == "原始文件":
            self._left_editor = editor
            self._left_numbers = line_numbers
        else:
            self._right_editor = editor
            self._right_numbers = line_numbers

        return panel

    def set_comparison(self, left_path: str, left_content: str,
                       right_path: str, right_content: str):
        """设置双栏对比内容"""
        self._left_lines = left_content.splitlines() if left_content else []
        self._right_lines = right_content.splitlines() if right_content else []

        self.title_label.setText(f"  {left_path}  ↔  {right_path}")

        # 计算差异
        self._compute_diff()

        # 渲染左栏
        self._render_left()
        # 渲染右栏
        self._render_right()

        # 更新差异计数
        diff_count = len(self._diff_positions)
        self.diff_count_label.setText(f"{diff_count} 处差异")

    def _compute_diff(self):
        """计算两个文件之间的差异（LCS 算法）"""
        left = self._left_lines
        right = self._right_lines

        m, n = len(left), len(right)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if left[i-1] == right[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])

        # 回溯构建差异映射
        self._diff_map = []
        i, j = m, n
        while i > 0 or j > 0:
            if i > 0 and j > 0 and left[i-1] == right[j-1]:
                self._diff_map.append((i-1, j-1, "same"))
                i -= 1
                j -= 1
            elif j > 0 and (i == 0 or dp[i][j-1] >= dp[i-1][j]):
                self._diff_map.append((i-1 if i > 0 else -1, j-1, "add"))
                j -= 1
            else:
                self._diff_map.append((i-1, j-1 if j > 0 else -1, "remove"))
                i -= 1

        self._diff_map.reverse()

    def _render_left(self):
        """渲染左栏（原始文件）"""
        editor = self._left_editor
        editor.clear()
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.Start)

        line_numbers = []
        diff_positions = []
        line_idx = 0

        for left_idx, right_idx, status in self._diff_map:
            if left_idx < 0:
                continue

            line = self._left_lines[left_idx] if left_idx < len(self._left_lines) else ""
            fmt = QTextCharFormat()
            fmt.setFont(QFont("Cascadia Code", 13))

            if status == "remove":
                fmt.setBackground(QColor(C['red_bg_light']))
                fmt.setForeground(QColor(C['red']))
                num_color = C['gutter_del']
                num_bg = C['gutter_red']
                diff_positions.append((line_idx, "remove"))
            elif status == "add":
                fmt.setForeground(QColor(C['text_dim']))
                num_color = C['text_muted']
                num_bg = C['gutter_bg']
            else:
                fmt.setForeground(QColor(C['text_dim']))
                num_color = C['text_muted']
                num_bg = C['gutter_bg']

            cursor.insertText(f"  {line}\n", fmt)
            line_numbers.append(
                f'<span style="color:{num_color};background:{num_bg};">{left_idx + 1}</span>'
            )
            line_idx += 1

        self._left_numbers.setText("<br>".join(line_numbers))
        self._left_diff_positions = diff_positions

    def _render_right(self):
        """渲染右栏（修改后文件）"""
        editor = self._right_editor
        editor.clear()
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.Start)

        line_numbers = []
        diff_positions = []
        line_idx = 0

        for left_idx, right_idx, status in self._diff_map:
            if right_idx < 0:
                continue

            line = self._right_lines[right_idx] if right_idx < len(self._right_lines) else ""
            fmt = QTextCharFormat()
            fmt.setFont(QFont("Cascadia Code", 13))

            if status == "add":
                fmt.setBackground(QColor(C['green_bg_light']))
                fmt.setForeground(QColor(C['green']))
                num_color = C['gutter_add']
                num_bg = C['gutter_green']
                diff_positions.append((line_idx, "add"))
            elif status == "remove":
                fmt.setForeground(QColor(C['text_dim']))
                num_color = C['text_muted']
                num_bg = C['gutter_bg']
            else:
                fmt.setForeground(QColor(C['text_dim']))
                num_color = C['text_muted']
                num_bg = C['gutter_bg']

            cursor.insertText(f"  {line}\n", fmt)
            line_numbers.append(
                f'<span style="color:{num_color};background:{num_bg};">{right_idx + 1}</span>'
            )
            line_idx += 1

        self._right_numbers.setText("<br>".join(line_numbers))
        self._diff_positions = diff_positions

    def _on_left_scroll(self, value):
        if self._sync_scroll:
            self._sync_scroll = False
            self._right_editor.verticalScrollBar().setValue(value)
            self._sync_scroll = True

    def _on_right_scroll(self, value):
        if self._sync_scroll:
            self._sync_scroll = False
            self._left_editor.verticalScrollBar().setValue(value)
            self._sync_scroll = True

    def _next_diff(self):
        if not self._diff_positions:
            return
        self._current_diff_idx = (self._current_diff_idx + 1) % len(self._diff_positions)
        self._go_to_diff(self._current_diff_idx)

    def _prev_diff(self):
        if not self._diff_positions:
            return
        self._current_diff_idx = (self._current_diff_idx - 1) % len(self._diff_positions)
        self._go_to_diff(self._current_diff_idx)

    def _go_to_diff(self, idx):
        if idx < 0 or idx >= len(self._diff_positions):
            return
        line_idx, _ = self._diff_positions[idx]
        editor = self._right_editor
        block = editor.document().findBlockByNumber(line_idx)
        if block.isValid():
            cursor = editor.textCursor()
            cursor.setPosition(block.position())
            editor.setTextCursor(cursor)
            editor.setFocus()
            # 高亮当前行
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#1a3350"))
            fmt.setProperty(QTextCharFormat.FullWidthSelection, True)
            cursor.movePosition(QTextCursor.StartOfLine, QTextCursor.MoveAnchor)
            cursor.movePosition(QTextCursor.EndOfLine, QTextCursor.KeepAnchor)
            extra = [QTextEdit.ExtraSelection()]
            extra[0].format = fmt
            extra[0].cursor = cursor
            self._right_editor.setExtraSelections(extra)
        self.diff_count_label.setText(f"{idx + 1}/{len(self._diff_positions)} 处差异")
        self._current_diff_idx = idx