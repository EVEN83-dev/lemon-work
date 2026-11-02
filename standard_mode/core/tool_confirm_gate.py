# -*- coding: utf-8 -*-
"""
Tool Confirm Gate — 跨线程工具执行确认门控
===========================================
后台线程（agent_chat 循环）需要用户确认高风险操作时，
通过 Qt 信号把请求转发到主线程弹对话框，阻塞等待结果。

用法（在 EngineManager.agent_chat 中）：
    if confirm_callback:
        approved = confirm_callback(tool_name, tool_args)
        if not approved:
            # 用户拒绝，跳过执行
"""

import json
import os
import threading
import uuid
from typing import Dict, Optional, Callable

_PERMISSION_STORE_PATH = os.path.join(os.path.expanduser("~"), ".lemoncode", "tool_permissions.json")


class PermissionStore:
    """工具权限持久化存储 — 记住用户对特定工具+路径模式的决定"""

    def __init__(self, path: str = ""):
        self._path = path or _PERMISSION_STORE_PATH
        self._data: Dict[str, str] = {}
        self._load()

    def _load(self):
        try:
            if os.path.isfile(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        except Exception:
            self._data = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _make_key(self, tool_name: str, args: Dict) -> str:
        path_hint = args.get("path", args.get("file_path", args.get("directory", "")))
        if path_hint:
            import hashlib
            h = hashlib.md5(path_hint.encode()).hexdigest()[:8]
            return f"{tool_name}:{h}"
        return tool_name

    def get_decision(self, tool_name: str, args: Dict) -> Optional[bool]:
        key = self._make_key(tool_name, args)
        val = self._data.get(key)
        if val == "allow":
            return True
        if val == "deny":
            return False
        return None

    def set_decision(self, tool_name: str, args: Dict, allowed: bool):
        key = self._make_key(tool_name, args)
        self._data[key] = "allow" if allowed else "deny"
        self._save()

    def clear(self):
        self._data = {}
        self._save()

try:
    from PyQt5.QtCore import QObject, pyqtSignal
    _QT_AVAILABLE = True
except ImportError:
    _QT_AVAILABLE = False
    class QObject:
        def __init__(self): pass
    pyqtSignal = lambda *args: property(lambda self: None)

_HIGH_RISK_TOOLS = frozenset({
    "write_file", "edit_file", "multi_edit",
    "run_command", "delete_file", "stop_command",
    "docker_skill", "mcp_bridge", "ssh_skill",
})

_HIGH_RISK_CATEGORIES = frozenset({"system"})


def is_high_risk_tool(name: str, category: str = "") -> bool:
    """判断工具是否为高风险"""
    if name in _HIGH_RISK_TOOLS:
        return True
    if category in _HIGH_RISK_CATEGORIES:
        return True
    return False


class ToolConfirmGate(QObject):
    """跨线程工具确认门控

    后台线程调用 check_confirm() → 发射 confirm_requested 信号 →
    主线程收到信号弹对话框 → 结果写入 _results → 后台线程解除阻塞。
    """
    confirm_requested = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending: Dict[str, threading.Event] = {}
        self._results: Dict[str, bool] = {}
        self._lock = threading.Lock()
        self._auto_approve = False
        self._perm_store = PermissionStore()
        self.confirm_requested.connect(self._on_confirm_requested)

    def set_auto_approve(self, enabled: bool):
        self._auto_approve = enabled

    def make_callback(self) -> Callable[[str, Dict], bool]:
        """生成可传给 agent_chat(confirm_callback=...) 的回调"""
        def _cb(tool_name: str, args: Dict) -> bool:
            if self._auto_approve:
                return True
            if not is_high_risk_tool(tool_name):
                return True
            cached = self._perm_store.get_decision(tool_name, args)
            if cached is not None:
                return cached
            return self.check_confirm(tool_name, args, timeout=120)
        return _cb

    def check_confirm(self, tool_name: str, args: Dict, timeout: int = 120) -> bool:
        """后台线程调用，阻塞等待主线程确认。返回 True=批准，False=拒绝"""
        call_id = str(uuid.uuid4())[:8]
        event = threading.Event()
        with self._lock:
            self._pending[call_id] = event
            self._results[call_id] = False

        args_json = json.dumps(args, ensure_ascii=False)[:300]
        self.confirm_requested.emit(tool_name, args_json, call_id)

        waited = event.wait(timeout=timeout)
        with self._lock:
            result = self._results.pop(call_id, False)
            self._pending.pop(call_id, None)

        if not waited:
            return False
        return result

    def _on_confirm_requested(self, tool_name: str, args_json: str, call_id: str):
        try:
            from PyQt5.QtWidgets import QMessageBox, QApplication, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit
            from PyQt5.QtCore import Qt
            from PyQt5.QtGui import QFont, QColor
        except ImportError:
            self._resolve(call_id, True)
            return

        app = QApplication.instance()
        if app is None:
            self._resolve(call_id, True)
            return

        if tool_name in ("write_file", "edit_file"):
            self._show_diff_confirm(tool_name, args_json, call_id)
            return

        icon_map = {
            "run_command": "{ICON:zap}", "delete_file": "{ICON:file-x}",
            "docker_skill": "{ICON:package}", "mcp_bridge": "{ICON:plug}", "ssh_skill": "{ICON:shield}",
        }
        icon = icon_map.get(tool_name, "{ICON:triangle-alert}")

        msg_text = (
            f"{icon} <b>{tool_name}</b><br/><br/>"
            f"<code style='font-size:11px;color:#aaa;'>{args_json}</code>"
        )

        box = QMessageBox(QMessageBox.Warning, "Tool Confirm", msg_text)
        box.setInformativeText("Allow this operation?")
        yes_btn = box.addButton("Allow", QMessageBox.AcceptRole)
        no_btn = box.addButton("Reject", QMessageBox.RejectRole)
        remember_btn = box.addButton("Remember", QMessageBox.AcceptRole)
        box.setDefaultButton(no_btn)
        box.exec_()

        clicked = box.clickedButton()
        approved = clicked in (yes_btn, remember_btn)
        self._resolve(call_id, approved)
        if clicked == remember_btn:
            try:
                parsed_args = json.loads(args_json) if args_json else {}
            except Exception:
                parsed_args = {}
            self._perm_store.set_decision(tool_name, parsed_args, approved)

    def _show_diff_confirm(self, tool_name: str, args_json: str, call_id: str):
        try:
            from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                                         QLabel, QTextEdit, QCheckBox, QApplication)
            from PyQt5.QtCore import Qt
            from PyQt5.QtGui import QFont, QColor, QTextCharFormat
        except ImportError:
            self._resolve(call_id, True)
            return

        try:
            args = json.loads(args_json) if args_json else {}
        except Exception:
            args = {}

        file_path = args.get("file_path", args.get("path", ""))
        new_content = args.get("content", "")
        old_content = ""
        is_new_file = True

        if file_path:
            import os
            try:
                from standard_mode.core.skills_registry import get_skills_registry
                root = get_skills_registry().get_project_root()
            except Exception:
                root = os.getcwd()
            full_path = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
            if os.path.isfile(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        old_content = f.read()
                    is_new_file = False
                except Exception:
                    old_content = ""

        try:
            from ui.diff_approval_dialog import DiffApprovalDialog
            dlg = DiffApprovalDialog(
                file_path or "unknown", old_content, new_content,
                QApplication.activeWindow(),
            )

            def _on_accept(fp, nc):
                self._resolve(call_id, True)
                dlg.accept()

            def _on_reject(fp):
                self._resolve(call_id, False)
                dlg.reject()

            dlg.accepted.connect(_on_accept)
            dlg.rejected.connect(_on_reject)
            dlg.exec_()
            return
        except Exception:
            pass

        diff_html = self._generate_diff_html(old_content, new_content, file_path, is_new_file)

        dlg = QDialog(QApplication.activeWindow())
        dlg.setWindowTitle(f"File Change: {file_path}")
        dlg.setMinimumSize(680, 480)
        dlg.setStyleSheet("""
            QDialog { background: #2C2C2C; color: #fff; }
            QLabel { color: #fff; }
            QPushButton { padding: 8px 20px; border-radius: 6px; font-size: 12px; font-weight: 600; border: none; cursor: pointer; }
            QTextEdit { background: #0d0d1a; color: #333; border: 1px solid #333; border-radius: 6px; font-family: Consolas, monospace; font-size: 11px; }
            QCheckBox { color: #aaa; font-size: 11px; }
        """)

        layout = QVBoxLayout(dlg)

        header = QLabel("Modify: " + file_path if not is_new_file else "New file: " + file_path)
        header.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        header.setStyleSheet("color: #FF6B00;")
        layout.addWidget(header)

        if not is_new_file:
            stats = self._diff_stats(old_content, new_content)
            stats_label = QLabel("+" + str(stats['added']) + " -" + str(stats['removed']) + " lines changed")
            stats_label.setStyleSheet("color: #aaa; font-size: 11px; margin-bottom: 4px;")
            layout.addWidget(stats_label)

        diff_view = QTextEdit()
        diff_view.setReadOnly(True)
        diff_view.setHtml(diff_html)
        layout.addWidget(diff_view, 1)

        check = QCheckBox("Remember this decision for this file")
        layout.addWidget(check)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        reject_btn = QPushButton("Reject")
        reject_btn.setStyleSheet("background: rgba(244,67,54,0.2); color: #FF5252; border: 1px solid rgba(244,67,54,0.3);")
        reject_btn.clicked.connect(lambda: self._resolve_diff(dlg, call_id, False, check.isChecked(), tool_name, args))
        btn_layout.addWidget(reject_btn)

        approve_btn = QPushButton("Approve")
        approve_btn.setStyleSheet("background: #69F0AE; color: #fff;")
        approve_btn.setDefault(True)
        approve_btn.clicked.connect(lambda: self._resolve_diff(dlg, call_id, True, check.isChecked(), tool_name, args))
        btn_layout.addWidget(approve_btn)

        layout.addLayout(btn_layout)
        dlg.exec_()

    def _resolve_diff(self, dlg, call_id, approved, remember, tool_name, args):
        self._resolve(call_id, approved)
        if remember:
            self._perm_store.set_decision(tool_name, args, approved)
        dlg.accept()

    def _diff_stats(self, old: str, new: str) -> dict:
        import difflib
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = list(difflib.unified_diff(old_lines, new_lines, n=0))
        added = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
        removed = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))
        return {"added": added, "removed": removed}

    def _generate_diff_html(self, old_content: str, new_content: str, file_path: str, is_new_file: bool) -> str:
        import difflib
        import html as html_module

        if is_new_file:
            lines = new_content.splitlines()
            body = ""
            for i, line in enumerate(lines, 1):
                esc = html_module.escape(line)
                body += f'<div class="diff-line added"><span class="diff-line-num">{i}</span><span class="diff-line-content">+{esc}</span></div>'
            return f'<div class="diff-viewer">{body}</div>'

        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=3))

        body = ""
        for line in diff:
            if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
                if line.startswith('@@'):
                    esc = html_module.escape(line)
                    body += f'<div class="diff-line context"><span class="diff-line-num"></span><span class="diff-line-content" style="color:Lemon.STATUS_RUNNING;">{esc}</span></div>'
                continue
            esc = html_module.escape(line[1:] if len(line) > 1 else line)
            if line.startswith('+'):
                body += f'<div class="diff-line added"><span class="diff-line-num"></span><span class="diff-line-content">+{esc}</span></div>'
            elif line.startswith('-'):
                body += f'<div class="diff-line deleted"><span class="diff-line-num"></span><span class="diff-line-content">-{esc}</span></div>'
            else:
                body += f'<div class="diff-line unchanged"><span class="diff-line-num"></span><span class="diff-line-content"> {esc}</span></div>'

        return f'<div class="diff-viewer">{body}</div>'

    def _resolve(self, call_id: str, approved: bool):
        with self._lock:
            self._results[call_id] = approved
            event = self._pending.get(call_id)
        if event:
            event.set()
