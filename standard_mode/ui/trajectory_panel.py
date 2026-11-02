# -*- coding: utf-8 -*-
"""Lemon Agent 轨迹查看面板
所属窗口: BottomPanel  品牌组件: TrajectoryPanel
令牌引用: Lemon.PRIMARY/SECONDARY/BG/SURFACE/BORDER/SUCCESS/ERROR/BRAND_LEMON
           Lemon.SP_*/R_*/FS_*/FONT
功能: 事件时间线+搜索过滤+导出JSON/Markdown+SVG图标
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.design.tokens import Lemon
from ui.design.icons import (
    ICON_DOC, ICON_FAILED, ICON_GEAR, ICON_INTENT, ICON_RUNNING,
    ICON_STAR, ICON_SUCCESS, ICON_TOOL, load_pixmap,
)

_EVENT_ICONS = {
    "context_injected": ICON_GEAR,
    "turn_started": ICON_STAR,
    "turn_completed": ICON_STAR,
    "plan_generated": ICON_DOC,
    "tool_called": ICON_TOOL,
    "tool_completed": ICON_SUCCESS,
    "tool_result": ICON_SUCCESS,
    "final_response": ICON_DOC,
    "file_changed": ICON_DOC,
    "model_response": ICON_DOC,
    "error_occurred": ICON_FAILED,
    "loop_detected": ICON_FAILED,
    "agent_completed": ICON_STAR,
    "approval_requested": ICON_INTENT,
    "subagent_spawned": ICON_GEAR,
    "decision_made": ICON_INTENT,
}

_EVENT_COLORS = {
    "context_injected": Lemon.SECONDARY,
    "turn_started": Lemon.PRIMARY,
    "turn_completed": Lemon.PRIMARY,
    "plan_generated": Lemon.BRAND_LEMON,
    "tool_called": Lemon.PRIMARY,
    "tool_completed": Lemon.SUCCESS,
    "tool_result": Lemon.SUCCESS,
    "final_response": Lemon.PRIMARY,
    "file_changed": Lemon.BRAND_LEMON,
    "model_response": Lemon.SECONDARY,
    "error_occurred": Lemon.ERROR,
    "loop_detected": Lemon.ERROR,
    "agent_completed": Lemon.SUCCESS,
    "approval_requested": Lemon.BRAND_LEMON,
    "subagent_spawned": Lemon.SECONDARY,
    "decision_made": Lemon.BRAND_LEMON,
}


class _EventRow(QWidget):
    event_clicked = pyqtSignal(str, str, str)

    def __init__(self, event_data: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._event_data = event_data
        T = Lemon
        event_type = event_data.get("event_type", "unknown")
        icon_name = _EVENT_ICONS.get(event_type, ICON_GEAR)
        stroke = _EVENT_COLORS.get(event_type, T.SECONDARY)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.SP_M, 2, T.SP_M, 2)
        layout.setSpacing(T.SP_S)

        line = QWidget()
        line.setFixedWidth(2)
        line.setStyleSheet(f"background: {stroke}; border: none;")
        layout.addWidget(line)

        icon_label = QLabel()
        pm = load_pixmap(icon_name, "inline", stroke_color=stroke)
        icon_label.setPixmap(pm)
        icon_label.setFixedSize(16, 16)
        layout.addWidget(icon_label)

        ts = event_data.get("timestamp", 0)
        ts_str = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else ""
        time_label = QLabel(ts_str)
        time_label.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        time_label.setFixedWidth(64)
        layout.addWidget(time_label)

        type_label = QLabel(event_type)
        type_label.setStyleSheet(
            f"color: {stroke}; font-size: {T.FS_CAPTION}px; font-weight: 600; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        type_label.setFixedWidth(120)
        layout.addWidget(type_label)

        data = event_data.get("data", {})
        summary = self._summarize(event_type, data)
        desc_label = QLabel(summary)
        desc_label.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {T.FS_CAPTION}px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none;"
        )
        desc_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(desc_label)

        if event_data.get("agent_name"):
            agent_label = QLabel(event_data["agent_name"])
            agent_label.setStyleSheet(
                f"color: {T.BRAND_LEMON}; font-size: {T.FS_CAPTION}px; "
                f"background: transparent; border: none;"
            )
            layout.addWidget(agent_label)

    @staticmethod
    def _summarize(event_type: str, data: dict) -> str:
        if event_type == "tool_called":
            return f"Called {data.get('skill_name', '?')}"
        if event_type in ("tool_completed", "tool_result"):
            s = "OK" if data.get("success") else "FAIL"
            return f"Result: {s}"
        if event_type == "file_changed":
            return f"{data.get('skill', '?')}: {data.get('path', '?')}"
        if event_type == "plan_generated":
            steps = data.get("steps", [])
            return f"Plan: {len(steps)} steps"
        if event_type == "loop_detected":
            return f"Loop: {data.get('loop_type', '?')} on {data.get('loop_skill', '?')}"
        if event_type == "error_occurred":
            return data.get("error_type", data.get("error", "unknown"))
        if event_type == "context_injected":
            return f"{data.get('message_count', 0)} messages"
        if event_type == "final_response":
            return f"{data.get('content_length', 0)} chars"
        s = json.dumps(data, ensure_ascii=False, default=str)
        return s[:80]

    def mousePressEvent(self, event):
        data = self._event_data.get("data", {})
        call_id = data.get("call_id", "")
        step_id = data.get("step_id", "")
        run_id = data.get("run_id", "")
        if call_id or step_id:
            self.event_clicked.emit(run_id, step_id, call_id)
        super().mousePressEvent(event)


class TrajectoryPanel(QWidget):
    export_requested = pyqtSignal(str, str)
    event_clicked = pyqtSignal(str, str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._events: List[dict] = []
        self._filtered: List[dict] = []
        self._init_ui()

    def _init_ui(self):
        T = Lemon
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QWidget()
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(T.SP_M, T.SP_S, T.SP_M, T.SP_S)
        tb_layout.setSpacing(T.SP_S)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索事件...")
        self._search.setObjectName("lemonSearch")
        self._search.textChanged.connect(self._on_search)
        tb_layout.addWidget(self._search, 1)

        self._type_filter = QComboBox()
        self._type_filter.addItem("全部类型")
        for t in sorted(set(_EVENT_ICONS.keys())):
            self._type_filter.addItem(t)
        self._type_filter.currentTextChanged.connect(self._on_filter)
        tb_layout.addWidget(self._type_filter)

        export_json_btn = QPushButton("导出 JSON")
        export_json_btn.setObjectName("ghostBtn")
        export_json_btn.setCursor(Qt.PointingHandCursor)
        export_json_btn.clicked.connect(lambda: self.export_requested.emit("json", ""))
        tb_layout.addWidget(export_json_btn)

        export_md_btn = QPushButton("导出 Markdown")
        export_md_btn.setObjectName("ghostBtn")
        export_md_btn.setCursor(Qt.PointingHandCursor)
        export_md_btn.clicked.connect(lambda: self.export_requested.emit("markdown", ""))
        tb_layout.addWidget(export_md_btn)

        self._count_label = QLabel("0 events")
        self._count_label.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_CAPTION}px; "
            f"background: transparent; border: none;"
        )
        tb_layout.addWidget(self._count_label)

        layout.addWidget(toolbar)

        # ★ 403T-3 空态引导：无事件时显示说明，避免"0 / 0 events"让用户分不清断链/无数据
        from PyQt5.QtCore import Qt as _Qt
        self._empty_hint = QLabel(
            "📊 轨迹 = Agent 决策时间线\n\n"
            "   记录每次工具调用 / 思考 / 状态变化；可搜索、过滤、导出 JSON/Markdown。\n"
            "   发起一次 Agent 任务后此处将出现事件。"
        )
        self._empty_hint.setObjectName("trajectory_empty")
        self._empty_hint.setAlignment(_Qt.AlignCenter)
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet(
            f"color: {T.SECONDARY}; font-size: {T.FS_BODY}px; "
            f"padding: 48px {T.SP_M}px; background: transparent; border: none;"
        )
        layout.addWidget(self._empty_hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {T.BG}; }}"
        )
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self._content_layout.addStretch()
        scroll.setWidget(self._content)
        layout.addWidget(scroll, 1)

    def set_events(self, events: List[dict]) -> None:
        self._events = events
        self._apply_filter()

    def _apply_filter(self) -> None:
        search = self._search.text().strip().lower()
        type_filter = self._type_filter.currentText()
        self._filtered = []
        for e in self._events:
            if type_filter != "全部类型" and e.get("event_type") != type_filter:
                continue
            if search:
                text = json.dumps(e, ensure_ascii=False, default=str).lower()
                if search not in text:
                    continue
            self._filtered.append(e)
        self._render()

    def _render(self) -> None:
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for e in self._filtered:
            row = _EventRow(e)
            row.event_clicked.connect(self.event_clicked.emit)
            self._content_layout.insertWidget(self._content_layout.count() - 1, row)
        self._count_label.setText(f"{len(self._filtered)} / {len(self._events)} events")
        # ★ 403T-3 空态切换
        if hasattr(self, '_empty_hint') and self._empty_hint is not None:
            empty = len(self._filtered) == 0
            self._empty_hint.setVisible(empty)

    def _on_search(self, text: str) -> None:
        self._apply_filter()

    def _on_filter(self, text: str) -> None:
        self._apply_filter()

    # ★ 403T-3 导出（父窗口可接管 export_requested 信号；否则落到 data/trajectory_export.<ext>）
    def export_json(self, path: str = "") -> str:
        return self._do_export("json", path)

    def export_markdown(self, path: str = "") -> str:
        return self._do_export("markdown", path)

    def _do_export(self, fmt: str, path: str = "") -> str:
        import time as _t
        if not path:
            stamp = _t.strftime("%Y%m%d_%H%M%S", _t.localtime())
            path = str(Path(__file__).resolve().parent.parent.parent / "data" / "exports"
                       / f"trajectory_{stamp}.{fmt}")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            Path(path).write_text(
                json.dumps(self._events, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8")
        else:
            lines = ["# Trajectory Events", "", f"- generated: {_t.strftime('%Y-%m-%d %H:%M:%S')}",
                     f"- total events: {len(self._events)}", ""]
            for e in self._events:
                ts = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(e.get("timestamp", 0)))
                lines.append(f"## {e.get('event_type', '?')} · {ts}")
                lines.append("```json")
                lines.append(json.dumps(e.get("data", {}), ensure_ascii=False, indent=2, default=str))
                lines.append("```\n")
            Path(path).write_text("\n".join(lines), encoding="utf-8")
        return path

    def clear(self) -> None:
        self._events.clear()
        self._filtered.clear()
        self._render()
