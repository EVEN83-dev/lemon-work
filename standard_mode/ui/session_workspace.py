# -*- coding: utf-8 -*-
"""CodeBuddy 风格顶部会话 Tab 栏 + 多会话实例池（v4.7.2）

背景：用户反馈咩咩前端界面 + 窗口管理不够好，参考 CodeBuddy 的顶部会话
Tab 栏（滑轨式多标签切换）改造。取代旧「单AI多窗口模式 MultiSessionPanel」
与「多AI协同」：主窗口右侧改为一个多会话工作区 —— 顶部一条会话 Tab 栏
（可新建 + / 关闭 × / 左右滑轨溢出滚动），下方是被激活的 MIMOCodePanel。

会话完全隔离：每个 Tab = 一个独立的面板实例（由外部 panel_factory 创建，
如 MIMOCodePanel → 独立 WebEngine → 独立消息历史 / 模型 / 咩咩任务流），
切换 Tab 即切换整个会话上下文，隔离粒度对齐 CodeBuddy。
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QToolButton, QStyle,
)
from ui.theme import BG_ROOT, BG_SECONDARY, BORDER_SUBTLE, MIMO_ORANGE, TEXT_PRIMARY, TEXT_TERTIARY, FONT_SIZE_SM, FONT_SIZE_XS
from ui.design.tokens import Lemon

# 关闭按钮 × 图标（内联 SVG，stroke 用 %23 编码 #）
_CLOSE_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'>"
    "<line x1='3' y1='3' x2='9' y2='9' stroke='%23c9d1d9' stroke-width='1.6' stroke-linecap='round'/>"
    "<line x1='9' y1='3' x2='3' y2='9' stroke='%23c9d1d9' stroke-width='1.6' stroke-linecap='round'/>"
    "</svg>"
)

_TAB_STYLE = f"""
QTabWidget::pane {{
    background: {BG_ROOT};
    border: none;
    margin: 0;
    padding: 0;
}}
QTabBar {{
    background: {BG_SECONDARY};
    border-bottom: 1px solid rgba(255,255,255,0.06);
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    background: {BG_SECONDARY};
    color: {TEXT_TERTIARY};
    border: none;
    border-right: 1px solid rgba(255,255,255,0.04);
    border-bottom: 2px solid transparent;
    padding: 5px 12px 5px 14px;
    font-size: {FONT_SIZE_SM};
    min-width: 70px;
    max-width: 200px;
}}
QTabBar::tab:hover {{
    background: rgba(255,122,47,0.06);
    color: {TEXT_PRIMARY};
}}
QTabBar::tab:selected {{
    background: {BG_ROOT};
    color: {Lemon.BRAND_ORANGE_LIGHT};
    border-bottom: 2px solid {MIMO_ORANGE};
    font-weight: 600;
}}
QTabBar::close-button {{
    image: url({_CLOSE_SVG});
    width: 18px;
    height: 18px;
    margin: 0 4px 0 6px;
    subcontrol-origin: padding;
    subcontrol-position: right;
}}
QTabBar::close-button:hover {{
    background: rgba(255,80,60,0.35);
    border-radius: 9px;
}}
QTabBar::scroller {{
    width: 22px;
}}
"""

_ADD_BTN_STYLE = f"""
QToolButton {{
    background: rgba(255,122,47,0.10);
    color: {MIMO_ORANGE};
    border: 1px solid rgba(255,122,47,0.25);
    border-radius: 4px;
    font-size: 18px;
    font-weight: 700;
    padding: 0;
    margin: 2px 6px 2px 2px;
}}
QToolButton:hover {{
    color: #fff;
    background: rgba(255,122,47,0.30);
    border: 1px solid rgba(255,122,47,0.55);
}}
QToolButton:pressed {{
    background: rgba(255,122,47,0.45);
}}
"""


class SessionWorkspace(QWidget):
    """多会话 Tab 工作区：顶部 Tab 栏 + 面板实例池。

    每个会话由外部 panel_factory 创建独立面板实例，实现完全隔离。
    外部（MIMOWindow）通过信号感知 Tab 的新建 / 切换 / 关闭。
    """

    session_switched = pyqtSignal(str)    # session_id
    session_closed = pyqtSignal(str)      # session_id
    new_session_requested = pyqtSignal()  # 用户点击「+」

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panel_factory = None
        self._panels = {}          # session_id -> widget
        self._sid_by_widget = {}   # id(widget) -> session_id
        self._seq = 0
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ★ 布局模式（right/bottom/hidden）：新建会话面板时自动继承
        self._layout_mode = 'right'

        self.tab_bar = QTabWidget()
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setMovable(True)
        self.tab_bar.setDocumentMode(True)
        self.tab_bar.setUsesScrollButtons(True)  # 溢出时出现左右滑轨按钮
        self.tab_bar.setElideMode(Qt.ElideMiddle)
        self.tab_bar.setStyleSheet(_TAB_STYLE)
        self.tab_bar.tabCloseRequested.connect(self._on_tab_close_requested)
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tab_bar)

        self._add_btn = QToolButton(self.tab_bar)
        self._add_btn.setText("+")
        self._add_btn.setToolTip("新建会话（Ctrl+N）")
        self._add_btn.setFixedSize(36, 30)
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setStyleSheet(_ADD_BTN_STYLE)
        self._add_btn.clicked.connect(self.new_session_requested.emit)
        self.tab_bar.setCornerWidget(self._add_btn, Qt.TopRightCorner)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def set_panel_factory(self, factory):
        """设置会话面板工厂：每次新建会话调用，返回隔离的面板实例。"""
        self._panel_factory = factory

    def create_session(self, name=None):
        """新建一个会话（面板实例），返回该面板；同时激活它。"""
        if self._panel_factory is None:
            print("[SessionWorkspace] 错误: panel_factory 未设置", flush=True)
            raise RuntimeError("SessionWorkspace.set_panel_factory() 未设置")
        self._seq += 1
        sid = "sess_%d" % self._seq
        print(f"[SessionWorkspace] create_session: sid={sid}, 调用 panel_factory...", flush=True)
        panel = self._panel_factory()
        if panel is None:
            print("[SessionWorkspace] panel_factory 返回 None!", flush=True)
            return None
        name = name or ("会话 %d" % self._seq)
        self._panels[sid] = panel
        self._sid_by_widget[id(panel)] = sid
        # ★第361章: 会话 ID 注入面板 — 任务列表/子代理状态按会话隔离的依据
        try:
            panel._session_sid = sid
            # ★ Lemon Work: 首轮任务完成 → 自动命名会话（标题 + 时间标）
            if hasattr(panel, "title_suggested"):
                panel.title_suggested.connect(
                    lambda _s, name, _sid=sid: self.rename_session(_sid, name))
        except Exception:
            pass
        # ★ 新会话面板继承当前布局模式（TRAE 同款三档布局）
        try:
            if hasattr(panel, 'set_layout_mode'):
                panel.set_layout_mode(self._layout_mode)
        except Exception:
            pass
        idx = self.tab_bar.addTab(panel, name)
        self.tab_bar.setCurrentIndex(idx)
        print(f"[SessionWorkspace] Tab 已添加: idx={idx}, name={name}, panel={panel}", flush=True)
        return panel

    def current_panel(self):
        """当前激活会话的面板实例。"""
        return self.tab_bar.currentWidget()

    def current_session_id(self):
        w = self.tab_bar.currentWidget()
        if w is not None:
            return self._sid_by_widget.get(id(w))
        return None

    def get_panel(self, session_id):
        return self._panels.get(session_id)

    def session_count(self):
        return self.tab_bar.count()

    def rename_session(self, session_id, name):
        w = self._panels.get(session_id)
        if w is None:
            return
        for i in range(self.tab_bar.count()):
            if self.tab_bar.widget(i) is w:
                self.tab_bar.setTabText(i, name)
                break

    def apply_layout_mode(self, mode):
        """★ 布局三档切换（TRAE 同款）：向所有会话面板广播布局模式。

        mode: 'right'（右侧栏）/ 'bottom'（编辑器下方）/ 'hidden'（收起）
        hidden 时不换前端 class（宿主由 MIMOWindow 隐藏），仅记录，
        恢复显示前会再次收到 right/bottom 广播。
        """
        if mode not in ('right', 'bottom', 'hidden'):
            return
        self._layout_mode = mode
        for panel in list(self._panels.values()):
            try:
                if panel is not None and hasattr(panel, 'set_layout_mode'):
                    panel.set_layout_mode(mode)
            except Exception:
                pass

    def close_all(self):
        while self.tab_bar.count() > 0:
            w = self.tab_bar.widget(0)
            self.tab_bar.removeTab(0)
            if w is not None:
                w.deleteLater()
        self._panels.clear()
        self._sid_by_widget.clear()

    # ------------------------------------------------------------------
    # ★ v4.7.3: 跨会话指挥 API —— 供咩咩「总指挥」工具（session_*）调用
    # ------------------------------------------------------------------
    def _tab_name(self, session_id):
        panel = self._panels.get(session_id)
        if panel is None:
            return str(session_id)
        for i in range(self.tab_bar.count()):
            if self.tab_bar.widget(i) is panel:
                return self.tab_bar.tabText(i)
        return str(session_id)

    def _panel_busy(self, panel):
        """面板是否忙碌：咩咩 worker 运行中即视为忙碌。"""
        if panel is None:
            return False
        try:
            w = getattr(panel, "_miemie_worker", None)
            if w is not None and w.isRunning():
                return True
            return bool(getattr(panel, "_is_busy", False))
        except Exception:
            return False

    def list_sessions_info(self):
        """列出所有会话：{ok, items:[{id,name,busy}]}。"""
        items = []
        for sid in list(self._panels.keys()):
            items.append({
                "id": sid,
                "name": self._tab_name(sid),
                "busy": self._panel_busy(self._panels[sid]),
            })
        return {"ok": True, "items": items}

    def read_session(self, session_id=None, max_chars=2000):
        """读取指定会话（或当前会话）最近输出文本。"""
        panel = self._panels.get(session_id) if session_id else self.current_panel()
        if panel is None:
            return {"ok": False, "error": "会话不存在"}
        try:
            try:
                max_chars = int(max_chars)
            except Exception:
                max_chars = 2000
            text = panel.get_output_text(max_chars)
            return {"ok": True, "session": self._tab_name(session_id) if session_id else "current",
                    "busy": self._panel_busy(panel), "text": text}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_to_session(self, session_id, text):
        """向指定会话注入一条命令（触发该会话咩咩面板执行）。"""
        panel = self._panels.get(session_id)
        if panel is None:
            return {"ok": False, "error": "会话不存在: %s" % session_id}
        try:
            panel.inject_user_message(text)
            return {"ok": True, "sent": str(text)[:120], "session": self._tab_name(session_id)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def is_session_busy(self, session_id=None):
        """查询会话忙碌状态（不指定则为当前会话）。"""
        panel = self._panels.get(session_id) if session_id else self.current_panel()
        return self._panel_busy(panel)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _on_tab_close_requested(self, index):
        widget = self.tab_bar.widget(index)
        sid = self._sid_by_widget.pop(id(widget), None)
        if sid:
            self._panels.pop(sid, None)
        self.tab_bar.removeTab(index)
        if widget is not None:
            if hasattr(widget, 'cleanup'):
                widget.cleanup()
            widget.deleteLater()
        # 关闭最后一个会话后自动补一个，保证始终有会话可用
        if self.tab_bar.count() == 0:
            try:
                self.create_session()
            except Exception:
                pass
        if sid:
            self.session_closed.emit(sid)

    def _on_tab_changed(self, index):
        if index < 0:
            return
        widget = self.tab_bar.widget(index)
        if widget is None:
            return
        sid = self._sid_by_widget.get(id(widget))
        if sid:
            self.session_switched.emit(sid)
