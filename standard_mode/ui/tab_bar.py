# -*- coding: utf-8 -*-
"""通用自定义 QTabBar：自绘关闭按钮（×）+ 双击/右键菜单信号。

用于 SessionWorkspace（会话 Tab）与 main_window（编辑器 Tab），解决 PyQt5
默认主题下 setTabsClosable(True) 关闭按钮图标不可见的问题。

v4.7.x 新增：
  - 双击 tab → emit `tab_double_clicked(index)`（用于重命名）
  - 右键 tab → emit `tab_context_menu_requested(index, global_pos)`（用于菜单）
"""
from PyQt5.QtCore import Qt, pyqtSignal, QPoint, QElapsedTimer
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtWidgets import QTabBar
from ui.design.tokens import Lemon


class CustomTabBar(QTabBar):
    """自定义标签栏：自绘关闭按钮（×）+ 命中检测 + 双击 / 右键支持。

    Qt 默认的 setTabsClosable(True) 在 PyQt5 多套主题下图标常显示为透明方块。
    本类在 paintEvent 直接画一个圆形 × 按钮，mousePressEvent 检测点击，
    然后 emit Qt 自带的 tabCloseRequested 信号（外部已连 _on_tab_close_*）。
    """

    # 关闭按钮绘制尺寸（与 tab 高度匹配，留 4px 内边距）
    _CLOSE_SIZE = 16
    _CLOSE_PAD_RIGHT = 6

    # ★ v4.7.x: 双击与右键信号（供外部重命名/菜单使用）
    tab_double_clicked = pyqtSignal(int)            # index
    tab_context_menu_requested = pyqtSignal(int, QPoint)  # index, global_pos

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.ElideRight)
        self.setDocumentMode(True)
        self.setMouseTracking(True)
        self._hover_close_index = -1
        self._pressed_close_index = -1
        # ★ v4.7.x: 双击检测（用 QElapsedTimer 精确测量间隔，PyQt5 QTabBar 默认 mouseDoubleClickEvent 不可靠）
        self._last_click_time = QElapsedTimer()
        self._last_click_index = -1

    def tabSizeHint(self, index):
        hint = super().tabSizeHint(index)
        hint.setWidth(max(110, hint.width() + self._CLOSE_SIZE + self._CLOSE_PAD_RIGHT + 4))
        return hint

    def minimumTabSizeHint(self, index):
        hint = super().minimumTabSizeHint(index)
        hint.setWidth(110)
        return hint

    def _close_button_rect(self, index):
        """返回 (tab_rect, btn_rect)；tab 被滚动隐藏时返回 None"""
        if index < 0:
            return None
        rect = self.tabRect(index)
        if rect.isNull() or rect.width() <= 0:
            return None
        sz = self._CLOSE_SIZE
        x = rect.right() - sz - self._CLOSE_PAD_RIGHT
        y = rect.center().y() - sz // 2
        return rect, type(rect)(x, y, sz, sz)

    def mouseMoveEvent(self, event):
        idx = self._index_at_close(event.pos())
        if idx != self._hover_close_index:
            self._hover_close_index = idx
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_close_index != -1:
            self._hover_close_index = -1
            self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            idx = self._index_at_close(event.pos())
            if idx >= 0:
                self._pressed_close_index = idx
                event.accept()
                return
            # ★ v4.7.x: 非关闭按钮区左键单击 — 检测双击（间隔 ≤ 400ms 且同 index）
            idx = self.tabAt(event.pos())
            if idx >= 0:
                if (self._last_click_time.isValid()
                        and self._last_click_time.elapsed() < 400
                        and self._last_click_index == idx):
                    # 触发双击信号
                    self.tab_double_clicked.emit(idx)
                    # 重置避免三连击再触发
                    self._last_click_time.invalidate()
                    self._last_click_index = -1
                    event.accept()
                    return
                else:
                    # 记录本次单击
                    self._last_click_time.restart()
                    self._last_click_index = idx
        self._pressed_close_index = -1
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self._pressed_close_index >= 0):
            idx = self._index_at_close(event.pos())
            if idx == self._pressed_close_index:
                self.tabCloseRequested.emit(idx)
                self._pressed_close_index = -1
                event.accept()
                return
        self._pressed_close_index = -1
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """★ v4.7.x: 双击 tab 触发重命名信号（外部接 QInputDialog）"""
        if event.button() == Qt.LeftButton:
            idx = self.tabAt(event.pos())
            if idx >= 0:
                self.tab_double_clicked.emit(idx)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """★ v4.7.x: 右键 tab 弹上下文菜单（外部构造 QMenu）"""
        idx = self.tabAt(event.pos())
        if idx >= 0:
            self.tab_context_menu_requested.emit(idx, event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def _index_at_close(self, pos):
        for i in range(self.count()):
            res = self._close_button_rect(i)
            if res is None:
                continue
            _, btn = res
            if btn.adjusted(-2, -2, 2, 2).contains(pos):
                return i
        return -1

    def paintEvent(self, event):
        # ★ v4.7.x: 先用 BG_SECONDARY 色填充整个 tab bar 区域，覆盖 PyQt5 主题默认 frame 顶部白线
        painter_bg = QPainter(self)
        painter_bg.fillRect(self.rect(), QColor("{Lemon.DARK_MID_2}"))  # BG_SECONDARY
        painter_bg.end()
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for i in range(self.count()):
            res = self._close_button_rect(i)
            if res is None:
                continue
            _, btn = res
            is_hover = (i == self._hover_close_index)
            is_pressed = (i == self._pressed_close_index)
            is_selected = (i == self.currentIndex())

            # 1) 圆形背景
            if is_pressed:
                bg = QColor(255, 122, 47, 90)
            elif is_hover:
                bg = QColor(255, 122, 47, 60)
            elif is_selected:
                bg = QColor(255, 255, 255, 18)
            else:
                bg = QColor(0, 0, 0, 0)
            if bg.alpha() > 0:
                painter.setBrush(bg)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(btn)

            # 2) × 字符（stroke 短线）
            pen = QPen(QColor("{Lemon.STATUS_OFFLINE}"), 1.6)
            if is_hover or is_pressed:
                pen.setColor(QColor("{Lemon.BRAND_ORANGE}"))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            cx = btn.center().x()
            cy = btn.center().y()
            r = 4
            painter.drawLine(cx - r, cy - r, cx + r, cy + r)
            painter.drawLine(cx + r, cy - r, cx - r, cy + r)