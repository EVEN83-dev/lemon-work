from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem
    from PyQt5.QtCore import pyqtSignal, Qt
    HAS_PYQT = True
except ImportError:
    try:
        from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
        from PyQt6.QtCore import pyqtSignal, Qt
        HAS_PYQT = True
    except ImportError:
        HAS_PYQT = False

if HAS_PYQT:
    class WorkflowTreeWidget(QTreeWidget):
        toolcall_double_clicked = pyqtSignal(str)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setHeaderLabels(["Status", "Title", "Duration"])
            self.setColumnCount(3)
            self._run_items: Dict[str, QTreeWidgetItem] = {}
            self._step_items: Dict[str, QTreeWidgetItem] = {}
            self.itemDoubleClicked.connect(self._on_double_click)
            self.setStyleSheet("""
                QTreeWidget { font-family: 'Segoe UI', sans-serif; font-size: 13px; }
                QTreeWidgetItem { padding: 2px; }
            """)

        def add_run(self, run: Any) -> None:
            run_id = getattr(run, 'run_id', getattr(run, 'id', str(id(run))))
            title = getattr(run, 'title', getattr(run, 'name', f"Run {run_id[:8]}"))
            status = getattr(run, 'status', 'pending')
            duration = getattr(run, 'duration_ms', 0)
            status_icon = self._status_icon(status)
            item = QTreeWidgetItem([status_icon, title, f"{duration}ms"])
            item.setData(0, Qt.UserRole, {"type": "run", "id": run_id})
            self.addTopLevelItem(item)
            self._run_items[run_id] = item

        def add_step(self, run_id: str, step: Any) -> None:
            step_id = getattr(step, 'step_id', getattr(step, 'id', str(id(step))))
            title = getattr(step, 'title', getattr(step, 'name', f"Step {step_id[:8]}"))
            status = getattr(step, 'status', 'pending')
            duration = getattr(step, 'duration_ms', 0)
            status_icon = self._status_icon(status)
            parent = self._run_items.get(run_id)
            item = QTreeWidgetItem([status_icon, title, f"{duration}ms"])
            item.setData(0, Qt.UserRole, {"type": "step", "id": step_id})
            if parent:
                parent.addChild(item)
                parent.setExpanded(True)
            else:
                self.addTopLevelItem(item)
            self._step_items[step_id] = item

        def add_toolcall(self, step_id: str, toolcall: Any) -> None:
            tc_id = getattr(toolcall, 'toolcall_id', getattr(toolcall, 'id', str(id(toolcall))))
            title = getattr(toolcall, 'tool_name', getattr(toolcall, 'name', f"Tool {tc_id[:8]}"))
            status = getattr(toolcall, 'status', 'pending')
            duration = getattr(toolcall, 'duration_ms', 0)
            status_icon = self._status_icon(status)
            parent = self._step_items.get(step_id)
            item = QTreeWidgetItem([status_icon, title, f"{duration}ms"])
            item.setData(0, Qt.UserRole, {"type": "toolcall", "id": tc_id})
            if parent:
                parent.addChild(item)
                parent.setExpanded(True)
            else:
                self.addTopLevelItem(item)

        def _on_double_click(self, item, column):
            data = item.data(0, Qt.UserRole)
            if data and data.get("type") == "toolcall":
                self.toolcall_double_clicked.emit(data["id"])

        def _status_icon(self, status: str) -> str:
            icons = {"completed": "[OK]", "success": "[OK]", "running": "[..]", "pending": "[  ]",
                     "failed": "[!!]", "error": "[!!]"}
            return icons.get(status, "[  ]")
else:
    class WorkflowTreeWidget:
        def __init__(self, *args, **kwargs):
            logger.warning("PyQt not available, WorkflowTreeWidget is a no-op stub")
        def add_run(self, run): pass
        def add_step(self, run_id, step): pass
        def add_toolcall(self, step_id, toolcall): pass
