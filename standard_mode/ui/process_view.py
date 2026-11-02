# -*- coding: utf-8 -*-
"""
运行进程监控侧栏
================
显示当前终端中运行的所有子进程信息。
通过 ShellBridge 的 PTY 进程树查询实现。
"""
import os
import subprocess
from typing import List, Dict, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton, QHeaderView,
)
from PyQt5.QtGui import QFont

try:
    from ui.theme import *
except ImportError:
    from standard_mode.ui.theme import *


class ProcessView(QWidget):
    """运行进程侧栏面板"""

    kill_requested = pyqtSignal(int)  # pid

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(3000)
        self._attached_pid: Optional[int] = None

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("运行进程")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold; background: transparent;")
        header.addWidget(title)
        header.addStretch()

        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.setFixedSize(48, 22)
        self._btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 3px; font-size: 10px;
            }}
            QPushButton:hover {{ color: {XIAOMI_ORANGE}; border-color: {XIAOMI_ORANGE}; }}
        """)
        self._btn_refresh.clicked.connect(self._refresh)
        header.addWidget(self._btn_refresh)
        layout.addLayout(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["PID", "名称", "CPU%", "内存"])
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background: {BG_PRIMARY}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 4px;
                font-family: "JetBrains Mono","Consolas",monospace; font-size: 11px;
            }}
            QTreeWidget::item {{
                padding: 3px 4px; border-bottom: 1px solid {BORDER_SUBTLE}22;
            }}
            QTreeWidget::item:selected {{
                background: {XIAOMI_ORANGE}22; color: {XIAOMI_ORANGE};
            }}
            QHeaderView::section {{
                background: {BG_SECONDARY}; color: {TEXT_TERTIARY};
                border: none; padding: 4px 6px; font-size: 10px;
            }}
        """)
        header_view = self._tree.header()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self._tree)

        self._label_count = QLabel("0 个进程")
        self._label_count.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px; background: transparent;")
        layout.addWidget(self._label_count)

    def attach_pid(self, pid: int):
        self._attached_pid = pid
        self._refresh()

    def _refresh(self):
        self._tree.clear()
        procs = self._get_process_list()
        root_pid = self._attached_pid

        items = {}
        for p in procs:
            item = QTreeWidgetItem([
                str(p["pid"]),
                p["name"][:40],
                p.get("cpu", ""),
                p.get("mem", ""),
            ])
            if p["pid"] == root_pid:
                for col in range(4):
                    item.setForeground(col, Qt.red)
            items[p["pid"]] = item

        for p in procs:
            ppid = p.get("ppid", 0)
            if ppid in items and p["pid"] in items and ppid != p["pid"]:
                items[ppid].addChild(items[p["pid"]])
            else:
                self._tree.addTopLevelItem(items[p["pid"]])

        self._tree.expandAll()
        self._label_count.setText(f"{len(procs)} 个进程")

    def _get_process_list(self) -> List[Dict]:
        procs = []
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-NoLogo", "-Command",
                    "Get-Process | Where-Object {$_.SessionId -eq $PID.Split('-')[0] -or $_.Id -eq $PID} | "
                    "Select-Object Id, ProcessName, CPU, WorkingSet64 | "
                    "ConvertTo-Json -Compress"
                ],
                capture_output=True, text=True, timeout=5,
            )
            import json
            if result.stdout.strip():
                data = json.loads(result.stdout.strip())
                if isinstance(data, dict):
                    data = [data]
                for p in data:
                    cpu = p.get("CPU", 0) or 0
                    ws = p.get("WorkingSet64", 0) or 0
                    mem_mb = ws / (1024 * 1024)
                    procs.append({
                        "pid": p.get("Id", 0),
                        "ppid": 0,
                        "name": p.get("ProcessName", "?"),
                        "cpu": f"{cpu:.1f}" if cpu else "",
                        "mem": f"{mem_mb:.0f}MB" if ws else "",
                    })
        except Exception:
            try:
                result = subprocess.run(
                    ["tasklist", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.strip().split("\n"):
                    parts = line.strip().strip('"').split('","')
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                        except ValueError:
                            continue
                        procs.append({
                            "pid": pid, "ppid": 0,
                            "name": parts[0], "cpu": "", "mem": parts[4] if len(parts) > 4 else "",
                        })
            except Exception:
                pass
        return procs[:100]
