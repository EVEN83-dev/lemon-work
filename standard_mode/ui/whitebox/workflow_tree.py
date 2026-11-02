# -*- coding: utf-8 -*-
"""
WorkflowTree — 三级可折叠任务树
================================
三列: [状态图标, 标题, 耗时]
  根 = Run  (任务描述 + run 状态色)
  枝 = Step (StepStatus 图标)
  叶 = ToolCall (工具名 + 耗时)

特性:
  - 递归展开/折叠
  - 双击 ToolCall 叶弹 result_full 详情
  - 自动滚动到 active 节点
  - Lemon 令牌统一深色树配色
"""
from __future__ import annotations

import time
from typing import Dict, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QHeaderView, QDialog,
    QVBoxLayout, QTextEdit, QDialogButtonBox, QLabel,
)

from ui.design.tokens import Lemon
from ui.whitebox.state_model import (
    Run, RunStatus, Step, StepStatus,
    ToolCall, ToolCallStatus, RunRegistry,
)


_RUN_STATUS_ICON = {
    RunStatus.QUEUED: ("○", Lemon.SECONDARY),
    RunStatus.RUNNING: ("●", Lemon.STATUS_RUNNING),
    RunStatus.WAITING_APPROVAL: ("●", Lemon.BRAND_ORANGE),
    RunStatus.COMPLETED: ("●", Lemon.SUCCESS),
    RunStatus.FAILED: ("●", Lemon.ERROR),
    RunStatus.CANCELLED: ("○", Lemon.TEXT_MUTED),
}

_STEP_STATUS_ICON = {
    StepStatus.PENDING: ("○", Lemon.TEXT_MUTED),
    StepStatus.ACTIVE: ("●", Lemon.STATUS_RUNNING),
    StepStatus.DONE: ("●", Lemon.SUCCESS),
    StepStatus.FAILED: ("●", Lemon.ERROR),
    StepStatus.SKIPPED: ("—", Lemon.TEXT_MUTED),
}

_TC_STATUS_ICON = {
    ToolCallStatus.PENDING: ("○", Lemon.TEXT_MUTED),
    ToolCallStatus.RUNNING: ("●", Lemon.STATUS_RUNNING),
    ToolCallStatus.SUCCESS: ("●", Lemon.SUCCESS),
    ToolCallStatus.FAILED: ("●", Lemon.ERROR),
    ToolCallStatus.DENIED: ("●", Lemon.BRAND_ORANGE),
}


def _format_duration(ms: int) -> str:
    if ms <= 0:
        return ""
    if ms < 1000:
        return f"{ms}ms"
    sec = ms / 1000.0
    if sec < 60:
        return f"{sec:.1f}s"
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m}m{s:.0f}s"


class _ToolCallDetailDialog(QDialog):
    def __init__(self, tc: ToolCall, parent=None):
        super().__init__(parent)
        T = Lemon
        self.setWindowTitle(f"ToolCall: {tc.tool_name}")
        self.setMinimumSize(560, 400)
        self.setStyleSheet(f"background: {T.SURFACE}; color: {T.TEXT_PRIMARY};")
        layout = QVBoxLayout(self)

        header = QLabel(f"<b>{tc.tool_name}</b>  {_format_duration(tc.duration_ms)}  [{tc.status.value}]")
        header.setStyleSheet(f"color: {T.TEXT_PRIMARY}; padding: {T.SP_S}px;")
        layout.addWidget(header)

        if tc.args:
            args_label = QLabel("Args:")
            args_label.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: {T.FS_CAPTION}px;")
            layout.addWidget(args_label)
            args_edit = QTextEdit()
            args_edit.setReadOnly(True)
            args_edit.setMaximumHeight(120)
            import json
            args_edit.setPlainText(json.dumps(tc.args, ensure_ascii=False, indent=2))
            args_edit.setStyleSheet(
                f"background: {T.BG}; color: {T.TEXT_SECONDARY}; "
                f"border: 1px solid {T.BORDER}; border-radius: {T.R_S}px; "
                f"font-family: Consolas, monospace; font-size: {T.FS_CAPTION}px;"
            )
            layout.addWidget(args_edit)

        result_label = QLabel("Result:")
        result_label.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: {T.FS_CAPTION}px;")
        layout.addWidget(result_label)
        result_edit = QTextEdit()
        result_edit.setReadOnly(True)
        result_text = tc.result_full or tc.result_summary or "(no result)"
        result_edit.setPlainText(result_text)
        result_edit.setStyleSheet(
            f"background: {T.BG}; color: {T.TEXT_PRIMARY}; "
            f"border: 1px solid {T.BORDER}; border-radius: {T.R_S}px; "
            f"font-family: Consolas, monospace; font-size: {T.FS_BODY}px;"
        )
        layout.addWidget(result_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.button(QDialogButtonBox.Ok).setStyleSheet(
            f"background: {T.BRAND_ORANGE}; color: #fff; border-radius: {T.R_S}px; "
            f"padding: {T.SP_S}px {T.SP_M}px; min-width: 80px;"
        )
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)


class WorkflowTree(QTreeWidget):
    tool_call_double_clicked = pyqtSignal(str, str, str)

    COL_STATUS = 0
    COL_TITLE = 1
    COL_DURATION = 2

    def __init__(self, registry: RunRegistry, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._run_items: Dict[str, QTreeWidgetItem] = {}
        self._step_items: Dict[str, QTreeWidgetItem] = {}
        self._tc_items: Dict[str, QTreeWidgetItem] = {}
        self._init_ui()

    def _init_ui(self):
        T = Lemon
        self.setHeaderLabels(["", "Title", "Time"])
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(self.COL_STATUS, QHeaderView.Fixed)
        self.header().setSectionResizeMode(self.COL_TITLE, QHeaderView.Stretch)
        self.header().setSectionResizeMode(self.COL_DURATION, QHeaderView.Fixed)
        self.setColumnWidth(self.COL_STATUS, 28)
        self.setColumnWidth(self.COL_DURATION, 72)
        self.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.header().setFixedHeight(26)
        self.setIndentation(18)
        self.setAnimated(True)
        self.setExpandsOnDoubleClick(False)
        self.setRootIsDecorated(False)
        self.setVerticalScrollMode(self.ScrollPerPixel)
        self.setItemsExpandable(True)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.setStyleSheet(self._build_stylesheet())

    def _build_stylesheet(self) -> str:
        T = Lemon
        return (
            f"QTreeWidget {{"
            f"  background: {T.BG};"
            f"  color: {T.TEXT_PRIMARY};"
            f"  border: none;"
            f"  outline: none;"
            f"  font-family: '{T.FONT}';"
            f"  font-size: {T.FS_BODY}px;"
            f"}}"
            f"QTreeWidget::item {{"
            f"  padding: 2px 0px;"
            f"  border-bottom: 1px solid {T.BORDER};"
            f"}}"
            f"QTreeWidget::item:selected {{"
            f"  background: {T.DARK_BG_4};"
            f"  color: {T.TEXT_PRIMARY};"
            f"}}"
            f"QTreeWidget::item:hover {{"
            f"  background: {T.DARK_BG_3};"
            f"}}"
            f"QHeaderView::section {{"
            f"  background: {T.SURFACE};"
            f"  color: {T.TEXT_TERTIARY};"
            f"  border: none;"
            f"  border-bottom: 1px solid {T.BORDER};"
            f"  padding: 4px 6px;"
            f"  font-size: {T.FS_CAPTION}px;"
            f"}}"
            f"QScrollBar:vertical {{"
            f"  background: {T.BG};"
            f"  width: 8px;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"  background: {T.SCROLLBAR_THUMB};"
            f"  border-radius: 4px;"
            f"  min-height: 30px;"
            f"}}"
            f"QScrollBar::handle:vertical:hover {{"
            f"  background: {T.SCROLLBAR_THUMB_HOVER};"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{"
            f"  height: 0px;"
            f"}}"
        )

    # ── 增量更新入口 ──

    def add_run_item(self, run: Run) -> None:
        if run.run_id in self._run_items:
            return
        icon_char, color = _RUN_STATUS_ICON.get(run.status, ("?", Lemon.TEXT_MUTED))
        item = QTreeWidgetItem()
        item.setText(self.COL_STATUS, icon_char)
        item.setForeground(self.COL_STATUS, QColor(color))
        title = run.user_prompt[:80] if run.user_prompt else "(untitled)"
        item.setText(self.COL_TITLE, title)
        item.setForeground(self.COL_TITLE, QColor(T.Lemon.TEXT_PRIMARY))
        item.setText(self.COL_DURATION, "")
        item.setData(0, Qt.UserRole, "run")
        item.setData(1, Qt.UserRole, run.run_id)
        item.setExpanded(run.is_expanded)
        font = item.font(self.COL_TITLE)
        font.setBold(True)
        item.setFont(self.COL_TITLE, font)
        self.addTopLevelItem(item)
        self._run_items[run.run_id] = item

    def update_run_item(self, run: Run) -> None:
        item = self._run_items.get(run.run_id)
        if not item:
            return
        icon_char, color = _RUN_STATUS_ICON.get(run.status, ("?", Lemon.TEXT_MUTED))
        item.setText(self.COL_STATUS, icon_char)
        item.setForeground(self.COL_STATUS, QColor(color))
        if run.status == RunStatus.RUNNING:
            item.setForeground(self.COL_TITLE, QColor(Lemon.STATUS_RUNNING))
        elif run.status == RunStatus.COMPLETED:
            item.setForeground(self.COL_TITLE, QColor(Lemon.SUCCESS))
        elif run.status == RunStatus.FAILED:
            item.setForeground(self.COL_TITLE, QColor(Lemon.ERROR))
        else:
            item.setForeground(self.COL_TITLE, QColor(Lemon.TEXT_PRIMARY))
        if run.elapsed_ms:
            item.setText(self.COL_DURATION, _format_duration(run.elapsed_ms))
        elif run.started_at:
            elapsed = int((time.time() - run.started_at) * 1000)
            item.setText(self.COL_DURATION, _format_duration(elapsed))

    def add_step_item(self, run_id: str, step: Step) -> None:
        key = f"{run_id}_{step.step_id}"
        if key in self._step_items:
            return
        run_item = self._run_items.get(run_id)
        if not run_item:
            return
        icon_char, color = _STEP_STATUS_ICON.get(step.status, ("?", Lemon.TEXT_MUTED))
        item = QTreeWidgetItem(run_item)
        item.setText(self.COL_STATUS, icon_char)
        item.setForeground(self.COL_STATUS, QColor(color))
        item.setText(self.COL_TITLE, step.title or "(step)")
        item.setForeground(self.COL_TITLE, QColor(Lemon.TEXT_SECONDARY))
        item.setText(self.COL_DURATION, "")
        item.setData(0, Qt.UserRole, "step")
        item.setData(1, Qt.UserRole, step.step_id)
        item.setData(2, Qt.UserRole, run_id)
        item.setExpanded(True)
        self._step_items[key] = item

    def update_step_item(self, run_id: str, step: Step) -> None:
        key = f"{run_id}_{step.step_id}"
        item = self._step_items.get(key)
        if not item:
            return
        icon_char, color = _STEP_STATUS_ICON.get(step.status, ("?", Lemon.TEXT_MUTED))
        item.setText(self.COL_STATUS, icon_char)
        item.setForeground(self.COL_STATUS, QColor(color))
        if step.status == StepStatus.ACTIVE:
            item.setForeground(self.COL_TITLE, QColor(Lemon.STATUS_RUNNING))
        elif step.status == StepStatus.DONE:
            item.setForeground(self.COL_TITLE, QColor(Lemon.SUCCESS))
        elif step.status == StepStatus.FAILED:
            item.setForeground(self.COL_TITLE, QColor(Lemon.ERROR))
        else:
            item.setForeground(self.COL_TITLE, QColor(Lemon.TEXT_SECONDARY))
        if step.finished_at and step.started_at:
            ms = int((step.finished_at - step.started_at) * 1000)
            item.setText(self.COL_DURATION, _format_duration(ms))

    def add_tool_call_item(self, run_id: str, step: Step, tc: ToolCall) -> None:
        key = tc.call_id
        if key in self._tc_items:
            return
        step_key = f"{run_id}_{step.step_id}"
        step_item = self._step_items.get(step_key)
        if not step_item:
            return
        icon_char, color = _TC_STATUS_ICON.get(tc.status, ("?", Lemon.TEXT_MUTED))
        item = QTreeWidgetItem(step_item)
        item.setText(self.COL_STATUS, icon_char)
        item.setForeground(self.COL_STATUS, QColor(color))
        tc_title = f"{tc.tool_name}"
        if tc.args:
            fp = tc.args.get("filePath", tc.args.get("path", ""))
            if fp:
                import os
                tc_title = f"{tc.tool_name} {os.path.basename(fp)}"
        item.setText(self.COL_TITLE, tc_title)
        item.setForeground(self.COL_TITLE, QColor(Lemon.TEXT_TERTIARY))
        item.setText(self.COL_DURATION, "...")
        item.setData(0, Qt.UserRole, "toolcall")
        item.setData(1, Qt.UserRole, tc.call_id)
        item.setData(2, Qt.UserRole, run_id)
        self._tc_items[key] = item
        self._scroll_to_active(run_id, step, tc)

    def update_tool_call_item(self, run_id: str, step: Step, tc: ToolCall) -> None:
        key = tc.call_id
        item = self._tc_items.get(key)
        if not item:
            return
        icon_char, color = _TC_STATUS_ICON.get(tc.status, ("?", Lemon.TEXT_MUTED))
        item.setText(self.COL_STATUS, icon_char)
        item.setForeground(self.COL_STATUS, QColor(color))
        if tc.status == ToolCallStatus.SUCCESS:
            item.setForeground(self.COL_TITLE, QColor(Lemon.SUCCESS))
        elif tc.status == ToolCallStatus.FAILED:
            item.setForeground(self.COL_TITLE, QColor(Lemon.ERROR))
        elif tc.status == ToolCallStatus.RUNNING:
            item.setForeground(self.COL_TITLE, QColor(Lemon.STATUS_RUNNING))
        else:
            item.setForeground(self.COL_TITLE, QColor(Lemon.TEXT_TERTIARY))
        if tc.duration_ms:
            item.setText(self.COL_DURATION, _format_duration(tc.duration_ms))
        if tc.result_summary and tc.status != ToolCallStatus.RUNNING:
            tip = tc.result_summary[:300]
            item.setToolTip(self.COL_TITLE, tip)

    def _scroll_to_active(self, run_id: str, step: Step, tc: ToolCall) -> None:
        if tc.status != ToolCallStatus.RUNNING:
            return
        item = self._tc_items.get(tc.call_id)
        if not item:
            return
        self.scrollToItem(item, self.EnsureVisible)
        parent = item.parent()
        if parent:
            self.expandItem(parent)
        run_item = self._run_items.get(run_id)
        if run_item:
            self.expandItem(run_item)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        kind = item.data(0, Qt.UserRole)
        if kind != "toolcall":
            if kind == "run" or kind == "step":
                item.setExpanded(not item.isExpanded())
            return
        call_id = item.data(1, Qt.UserRole) or ""
        run_id = item.data(2, Qt.UserRole) or ""
        step_id = ""
        parent = item.parent()
        if parent:
            step_id = parent.data(1, Qt.UserRole) or ""
        run = self._registry.get_run(run_id)
        if not run:
            return
        for step in run.steps:
            if step.step_id != step_id:
                continue
            for tc in step.tool_calls:
                if tc.call_id == call_id:
                    self.tool_call_double_clicked.emit(run_id, step_id, call_id)
                    dlg = _ToolCallDetailDialog(tc, self)
                    dlg.exec_()
                    return

    def collapse_all(self) -> None:
        for item in self._run_items.values():
            item.setExpanded(False)

    def expand_all(self) -> None:
        for item in self._run_items.values():
            item.setExpanded(True)
            child_count = item.childCount()
            for i in range(child_count):
                item.child(i).setExpanded(True)

    def collapse_run(self, run_id: str) -> None:
        item = self._run_items.get(run_id)
        if item:
            item.setExpanded(False)

    def expand_run(self, run_id: str) -> None:
        item = self._run_items.get(run_id)
        if item:
            item.setExpanded(True)

    def clear_tree(self) -> None:
        self.clear()
        self._run_items.clear()
        self._step_items.clear()
        self._tc_items.clear()

    def full_sync(self, registry: RunRegistry) -> None:
        self.clear_tree()
        for run in registry.all_runs():
            self.add_run_item(run)
            for step in run.steps:
                self.add_step_item(run.run_id, step)
                for tc in step.tool_calls:
                    self.add_tool_call_item(run.run_id, step, tc)
                    self.update_tool_call_item(run.run_id, step, tc)
            self.update_run_item(run)

    def highlight_item(self, run_id: str, step_id: str = "",
                       call_id: str = "") -> None:
        """高亮指定树节点（时间轴联动入口）。"""
        target = None
        if call_id:
            target = self._tc_items.get(call_id)
        if not target and step_id:
            target = self._step_items.get(f"{run_id}_{step_id}")
        if not target and run_id:
            target = self._run_items.get(run_id)
        if not target:
            return
        self.scrollToItem(target, self.EnsureVisible)
        self.setCurrentItem(target)
        parent = target.parent()
        while parent:
            self.expandItem(parent)
            parent = parent.parent()
