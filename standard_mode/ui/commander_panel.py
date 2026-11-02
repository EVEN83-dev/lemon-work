# -*- coding: utf-8 -*-
"""398-A2 Commander 底栏监管面板 — 402C-2 紧凑态。

布局（自上而下，full mode）：
  ① 拓扑卡组：窗口名 / 角色徽章(指挥★|员工) / 引擎 / 状态徽章 / 当前命令号
  ② 统计条：本轮 N/M 完成 · 工具调用数 · 耗时
  ③ 审批区（HQ 到达时显示）：[批准分发][停止][修改后分发]
  ④ 消息流：HI/HQ/HR 事件滚动（最新在上 + 时间戳）

紧凑态（compact mode）折叠为状态栏单行摘要条：
  "⌘ 指挥 [轮 N/M] · 工具 N · 耗时 Ns · [状态徽章]"
  click → 请求主窗口弹出完整面板（request_expand 信号）。

样式铁律：颜色一律引用 ui/design/tokens.py 既有变量，不发明新色值。
挂载方式：main.py statusBar().addPermanentWidget(panel) 嵌入底栏（改动 ≤25 行）。
弹出面板：QDockWidget 形态悬浮显示（start hidden），尺寸记忆上次位置。
"""
from typing import Optional

from PyQt5.QtCore import QSettings, Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDockWidget, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMenu, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ui.design.tokens import Lemon


C = {
    "bg": Lemon.DARK_BG_2,
    "bg_card": Lemon.DARK_BG_4,
    "border": Lemon.DARK_BG_4,
    "text": Lemon.DARK_TEXT_1,
    "text_dim": Lemon.DARK_TEXT_3,
    "green": Lemon.STATUS_ONLINE,
    "blue": Lemon.STATUS_RUNNING,
    "orange": Lemon.BRAND_ORANGE,
    "red": Lemon.ERROR,
    "gray": Lemon.SYNTAX_COMMENT,
}

ROLE_ICON = {"commander": "★", "worker": "●"}
STATUS_LABEL = {
    "idle": "空闲", "running": "执行中",
    "done": "已完成", "awaiting_approval": "等审批",
}
STATUS_COLOR = {
    "idle": C["gray"], "running": C["blue"],
    "done": C["green"], "awaiting_approval": C["orange"],
}

_SUMMARY_FMT = "⌘ 指挥 [轮 {done}/{total}] · 工具 {tools} · 耗时 {secs}s · [{badge}]"


class WindowCard(QWidget):
    """单个窗口拓扑卡（横向 QHBoxLayout）。"""

    def __init__(self, session_id: str, name: str, role: str, engine: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._session_id = session_id
        self._role = role
        self.setStyleSheet(
            f"background:{C['bg_card']};border:1px solid {C['border']};border-radius:6px;")
        lo = QHBoxLayout(self)
        lo.setContentsMargins(8, 4, 8, 4)
        lo.setSpacing(6)

        icon = ROLE_ICON.get(role, "●")
        color = C["orange"] if role == "commander" else C["green"]
        lo.addWidget(self._lbl(icon, color, 14, bold=True))
        lo.addWidget(self._lbl(name, C["text"], 12, bold=True))
        lo.addWidget(self._lbl("·", C["text_dim"], 12))
        lo.addWidget(self._lbl(engine, C["text_dim"], 11))
        lo.addWidget(self._lbl(f"[{role}]", C["gray"], 10))
        self.status_lbl = self._lbl("空闲", STATUS_COLOR["idle"], 11, bold=True)
        lo.addWidget(self.status_lbl)
        self.cmd_lbl = self._lbl("", C["text_dim"], 11)
        lo.addWidget(self.cmd_lbl)
        lo.addStretch(1)

    @staticmethod
    def _lbl(text: str, color: str, size: int, bold: bool = False) -> QLabel:
        fw = "700" if bold else "400"
        lb = QLabel(text)
        lb.setStyleSheet(
            f"color:{color};font-size:{size}px;font-weight:{fw};"
            f"background:transparent;border:none;")
        return lb

    def matches(self, session_id: str) -> bool:
        return self._session_id == session_id

    def update_state(self, status: str, cmd_idx_display: str = "") -> None:
        self.status_lbl.setText(STATUS_LABEL.get(status, status))
        self.status_lbl.setStyleSheet(
            f"color:{STATUS_COLOR.get(status, C['gray'])};font-size:11px;"
            f"font-weight:700;background:transparent;border:none;")
        self.cmd_lbl.setText(cmd_idx_display)


class CommanderPanel(QWidget):
    """监管面板，支持 compact 摘要态 / full 全展态。"""

    modify_and_redispatch = pyqtSignal(str)
    request_expand = pyqtSignal()   # compact 模式点击摘要 → 请求主窗口弹出完整面板

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._commander = None
        self._card_widgets = []  # WindowCard refs
        self._pending_approval_round_id = None
        self._pending_approval_cmd_idx = None
        self._compact = False
        self._expanded_dock = None
        self._build_ui()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 紧凑摘要条（仅 compact mode 显示）──
        self._summary_row = QFrame()
        self._summary_row.setStyleSheet(
            f"background:{C['bg_card']};border-top:1px solid {C['border']};")
        s_lo = QHBoxLayout(self._summary_row)
        s_lo.setContentsMargins(8, 2, 8, 2)
        s_lo.setSpacing(6)
        self._summary_icon = QLabel("⌘")
        self._summary_icon.setStyleSheet(f"color:{C['orange']};font-size:12px;font-weight:700;")
        s_lo.addWidget(self._summary_icon)
        self._summary_label = QLabel("指挥 初始中…")
        self._summary_label.setStyleSheet(
            f"color:{C['text']};font-size:11px;background:transparent;border:none;")
        s_lo.addWidget(self._summary_label, 1)
        self._summary_badge = QLabel("空闲")
        self._summary_badge.setStyleSheet(
            f"color:{STATUS_COLOR['idle']};font-size:10px;font-weight:700;"
            f"background:transparent;border:none;")
        s_lo.addWidget(self._summary_badge)
        self._summary_row.hide()
        self._summary_row.setCursor(Qt.PointingHandCursor if hasattr(Qt, 'PointingHandCursor') else Qt.ArrowCursor)
        self._summary_row.mousePressEvent = lambda e: self.request_expand.emit()
        self._summary_label.mousePressEvent = lambda e: self.request_expand.emit()
        root.addWidget(self._summary_row)

        # ── ② 完整主体（full mode）──
        self._body = QWidget()
        lo = QVBoxLayout(self._body)
        lo.setContentsMargins(6, 6, 6, 6)
        lo.setSpacing(4)

        self.cards_host = QWidget()
        self.cards_layout = QHBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(6)
        self.cards_layout.addStretch(1)
        lo.addWidget(self.cards_host)

        self.stats_lbl = QLabel("本轮 0/0 完成 · 工具调用 0 · 耗时 0s")
        self.stats_lbl.setStyleSheet(
            f"color:{C['text_dim']};font-size:11px;background:{C['bg']};"
            f"padding:4px 8px;border-radius:4px;")
        lo.addWidget(self.stats_lbl)

        approval_box = QFrame()
        approval_box.setStyleSheet(
            f"background:{C['bg']};border:1px solid {C['orange']};border-radius:6px;")
        appr_lo = QHBoxLayout(approval_box)
        appr_lo.setContentsMargins(6, 4, 6, 4)
        self.approval_title = QLabel("⏸ 等审批")
        self.approval_title.setStyleSheet(
            f"color:{C['orange']};font-weight:700;font-size:12px;background:transparent;border:none;")
        appr_lo.addWidget(self.approval_title)
        appr_lo.addStretch(1)
        self.btn_approve = QPushButton("批准分发")
        self.btn_stop = QPushButton("停止")
        self.btn_modify = QPushButton("修改后分发")
        for btn in (self.btn_approve, self.btn_stop, self.btn_modify):
            btn.setStyleSheet(
                f"background:{C['bg_card']};color:{C['text']};border:1px solid {C['border']};"
                f"border-radius:4px;padding:4px 10px;font-size:11px;")
            appr_lo.addWidget(btn)
        self._edit_dlg = None
        self.btn_approve.clicked.connect(self._on_approve)
        self.btn_stop.clicked.connect(self._on_reject)
        self.btn_modify.clicked.connect(self._on_modify)
        approval_box.hide()
        self.approval_box = approval_box
        lo.addWidget(approval_box)

        self.events_list = QListWidget()
        self.events_list.setMaximumHeight(120)
        self.events_list.setStyleSheet(
            f"background:{C['bg']};color:{C['text']};border:none;font-size:11px;")
        lo.addWidget(self.events_list)

        root.addWidget(self._body)

    # ---------------------------------------------------------- compact toggle

    def set_compact_mode(self, compact: bool) -> None:
        self._compact = compact
        self._summary_row.setVisible(compact)
        self._body.setVisible(not compact)
        if compact:
            self._refresh_summary()

    def is_compact(self) -> bool:
        return self._compact

    # ---------------------------------------------------------- commander 绑定

    def bind_commander(self, commander) -> None:
        self._commander = commander
        commander.dispatch_made.connect(self._on_dispatch)
        commander.worker_reported.connect(self._on_report)
        commander.approval_needed.connect(self._on_approval_needed)
        commander.round_closed.connect(self._on_round_closed)
        self._rebuild_cards(commander)
        self._refresh_stats(commander)
        self._refresh_summary()

    def _rebuild_cards(self, commander) -> None:
        for c in self._card_widgets:
            c.deleteLater()
        self._card_widgets.clear()
        for sid, wi in commander.windows.items():
            card = WindowCard(wi.session_id, wi.name, wi.role.value, wi.engine)
            self._card_widgets.append(card)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

    # ---------------------------------------------------------- 信号回调

    def _on_dispatch(self, data: dict) -> None:
        wid = data.get("worker_id", "?")
        idx = data.get("cmd_idx", "?")
        self._push_event(f"[HI] 分发 #{idx} → {wid}")
        self._update_card(wid, "running", f"#{idx}")
        self._refresh_summary()

    def _on_report(self, data: dict) -> None:
        wid = data.get("worker_id", "?")
        idx = data.get("cmd_idx", "?")
        summary = data.get("result_summary", "")[:40]
        self._push_event(f"[HI] {wid} 完成 #{idx} {summary}")
        if self._commander:
            self._refresh_stats(self._commander)
        self._refresh_summary()

    def _on_approval_needed(self, data: dict) -> None:
        self._pending_approval_round_id = data.get("round_id")
        self._pending_approval_cmd_idx = data.get("cmd_idx")
        wid = data.get("worker_id", "?")
        idx = data.get("cmd_idx", "?")
        self.approval_box.show()
        self.approval_title.setText(f"⏸ 等审批 #{idx} ({wid})")
        self._update_card(wid, "awaiting_approval", f"#{idx}")
        self._push_event(f"[HQ] 等审批 #{idx} ({wid})")
        self._refresh_summary()

    def _on_round_closed(self, data: dict) -> None:
        n_done = data.get("n_done", 0)
        n_total = data.get("n_total", 0)
        secs = data.get("secs", 0)
        tools = data.get("tool_calls", 0)
        self._push_event(f"[HR] 闭环 {n_done}/{n_total} · {tools}工具 · {secs}s")
        self.approval_box.hide()
        if self._commander:
            self._refresh_stats(self._commander)
        self._refresh_summary()

    # ---------------------------------------------------------- 内部

    def _push_event(self, text: str) -> None:
        import time as _t
        ts = _t.strftime("%H:%M:%S", _t.localtime())
        item = QListWidgetItem(f"{ts} {text}")
        self.events_list.insertItem(0, item)

    def _update_card(self, worker_id: str, status: str, cmd_text: str = "") -> None:
        for c in self._card_widgets:
            if c.matches(worker_id):
                c.update_state(status, cmd_text)
                return

    def _refresh_stats(self, commander) -> None:
        windows = commander.windows
        cmds = commander.commands
        done_n = sum(1 for c in cmds if c.status.value == "done")
        total_n = len(cmds) if cmds else 0
        tools_n = sum(1 for c in cmds if c.status.value == "done")
        secs = 0
        if cmds:
            import time as _t
            secs = round(_t.time() - min(
                (c.started_at for c in cmds if c.started_at), default=_t.time()), 1)
        self.stats_lbl.setText(f"本轮 {done_n}/{total_n} 完成 · 工具调用 {tools_n} · 耗时 {secs}s")

    def _refresh_summary(self) -> None:
        if self._commander is None:
            return
        cmds = self._commander.commands
        done_n = sum(1 for c in cmds if c.status.value == "done")
        total_n = len(cmds) if cmds else 0
        tools_n = sum(1 for c in cmds if c.status.value == "done")
        secs = 0
        if cmds:
            import time as _t
            secs = round(_t.time() - min(
                (c.started_at for c in cmds if c.started_at), default=_t.time()), 1)
        # 状态徽章：优先 "等审批" > "执行中" > "空闲/已完成"
        statuses = [wi.status for wi in self._commander.windows.values()] if hasattr(self._commander, 'windows') else []
        if self._pending_approval_round_id is not None:
            badge_key = "awaiting_approval"
        elif any(getattr(wi, 'status', None) in ("running", "busy") for wi in (self._commander.windows.values() if hasattr(self._commander, 'windows') else [])):
            badge_key = "running"
        elif total_n > 0 and done_n == total_n:
            badge_key = "done"
        else:
            badge_key = "idle"
        badge_text = STATUS_LABEL.get(badge_key, "空闲")
        self._summary_label.setText(
            _SUMMARY_FMT.format(done=done_n, total=total_n, tools=tools_n, secs=secs, badge=badge_text))
        self._summary_badge.setText(STATUS_LABEL.get(badge_key, "空闲"))
        self._summary_badge.setStyleSheet(
            f"color:{STATUS_COLOR.get(badge_key, C['gray'])};font-size:10px;"
            f"font-weight:700;background:transparent;border:none;")

    # ---------------------------------------------------------- 审批按钮

    def _on_approve(self) -> None:
        if self._commander is None or self._pending_approval_round_id is None:
            return
        self._commander.approve(self._pending_approval_round_id)
        self.approval_box.hide()
        self._pending_approval_round_id = None
        self._refresh_summary()

    def _on_reject(self) -> None:
        if self._commander is None or self._pending_approval_round_id is None:
            return
        self._commander.reject(self._pending_approval_round_id, "用户拒绝")
        self.approval_box.hide()
        self._pending_approval_round_id = None
        self._refresh_summary()

    def _on_modify(self) -> None:
        if self._commander is None or self._pending_approval_cmd_idx is None:
            return
        cmd_idx = self._pending_approval_cmd_idx
        cur_text = ""
        if 0 <= cmd_idx < len(self._commander.commands):
            cur_text = self._commander.commands[cmd_idx].text
        edit = QPlainTextEdit()
        edit.setPlainText(cur_text)
        edit.setWindowTitle(f"修改命令 #{cmd_idx}")
        edit.setMinimumSize(400, 200)
        parent_widget = QWidget()
        vlo = QVBoxLayout(parent_widget)
        vlo.setContentsMargins(4, 4, 4, 4)
        vlo.addWidget(edit)
        btn = QPushButton("确认分发")
        btn.setStyleSheet(
            f"background:{C['green']};color:{C['text']};padding:4px 12px;")
        vlo.addWidget(btn)
        btn.clicked.connect(lambda: (
            self.modify_and_redispatch.emit(edit.toPlainText()),
            parent_widget.close(),
        ))
        parent_widget.setWindowTitle(f"修改命令 #{cmd_idx}")
        parent_widget.setMinimumSize(420, 260)
        parent_widget.show()


# ---- 给 main.py 用的便捷封装（402C-2 拆分：紧凑条 + 完整弹出）----

def create_commander_dock(commander, parent: Optional[QWidget] = None) -> QDockWidget:
    """保留 398 兼容：返回完整面板的浮动 dock（不含紧凑状态栏摘要）。"""
    panel = CommanderPanel(parent)
    panel.bind_commander(commander)
    dock = QDockWidget("Commander", parent)
    dock.setWidget(panel)
    dock.setFeatures(QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetMovable)
    dockAllowedAreas = Qt.BottomDockWidgetArea | Qt.RightDockWidgetArea
    dock.setAllowedAreas(dockAllowedAreas)
    return dock
