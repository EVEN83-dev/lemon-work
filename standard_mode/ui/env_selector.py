# -*- coding: utf-8 -*-
"""
环境管理助手 — 自动探测 venv/conda 并注入激活命令
================================================
接入终端工具栏下拉，选择后给 shell 注入对应 activate 命令。

用法：
  selector = EnvSelector()
  selector.env_activated.connect(lambda cmd: bridge.send_input(cmd + "\n"))
  selector.refresh()
"""
import os
import json
from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QWidget, QHBoxLayout, QLabel, QFileDialog, QPushButton,
)
from PyQt5.QtGui import QFont

try:
    from ui.theme import *
except ImportError:
    from standard_mode.ui.theme import *

_ENV_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".mimo_agent", "env_history.json")


class EnvSelector(QWidget):
    """环境选择下拉组件"""

    env_activated = pyqtSignal(str)  # activate command string

    def __init__(self, project_root: str = "", parent=None):
        super().__init__(parent)
        self._project_root = project_root or os.getcwd()
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label = QLabel("ENV")
        label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px; background: transparent;")
        layout.addWidget(label)

        self._combo = QComboBox()
        self._combo.setFixedHeight(22)
        self._combo.setMinimumWidth(120)
        self._combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_PRIMARY}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 3px;
                padding: 2px 6px; font-size: 11px;
            }}
            QComboBox:hover {{ border-color: {XIAOMI_ORANGE}; }}
            QComboBox::drop-down {{ border: none; width: 16px; }}
            QComboBox QAbstractItemView {{
                background: {BG_SECONDARY}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_SUBTLE}; selection-background-color: {XIAOMI_ORANGE}33;
            }}
        """)
        self._combo.currentIndexChanged.connect(self._on_selected)
        layout.addWidget(self._combo)

        self._btn_browse = QPushButton("...")
        self._btn_browse.setFixedSize(22, 22)
        self._btn_browse.setToolTip("手动选择解释器")
        self._btn_browse.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 3px;
                font-size: 10px;
            }}
            QPushButton:hover {{ color: {XIAOMI_ORANGE}; border-color: {XIAOMI_ORANGE}; }}
        """)
        self._btn_browse.clicked.connect(self._browse_interp)
        layout.addWidget(self._btn_browse)

    def refresh(self, project_root: str = ""):
        if project_root:
            self._project_root = project_root
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem("System", "")

        envs = self._scan_environments()
        saved = self._load_saved_envs()
        all_envs = envs + [e for e in saved if e not in envs]

        for env in all_envs:
            self._combo.addItem(env["label"], env["activate"])

        self._combo.blockSignals(False)

    def _scan_environments(self) -> List[dict]:
        results = []
        root = self._project_root

        venv_dir = os.path.join(root, ".venv")
        if os.path.isdir(venv_dir):
            activate = os.path.join(venv_dir, "Scripts", "activate")
            if os.path.isfile(activate + ".bat") or os.path.isfile(activate + ".ps1"):
                py_exe = os.path.join(venv_dir, "Scripts", "python.exe")
                label = f".venv ({self._py_version(py_exe)})"
                results.append({"label": label, "activate": f". .venv/Scripts/activate", "path": venv_dir})

        venv_dir2 = os.path.join(root, "venv")
        if os.path.isdir(venv_dir2) and venv_dir2 != venv_dir:
            activate = os.path.join(venv_dir2, "Scripts", "activate")
            if os.path.isfile(activate + ".bat") or os.path.isfile(activate + ".ps1"):
                py_exe = os.path.join(venv_dir2, "Scripts", "python.exe")
                label = f"venv ({self._py_version(py_exe)})"
                results.append({"label": label, "activate": f". venv/Scripts/activate", "path": venv_dir2})

        conda_meta = os.path.join(root, ".conda")
        if os.path.isdir(conda_meta):
            results.append({"label": "Conda (project)", "activate": "conda activate .", "path": root})

        return results

    def _py_version(self, exe_path: str) -> str:
        if not os.path.isfile(exe_path):
            return "?"
        import subprocess
        try:
            out = subprocess.run(
                [exe_path, "--version"], capture_output=True, text=True, timeout=5
            )
            return (out.stdout or out.stderr or "").strip().split()[-1] or "?"
        except Exception:
            return "?"

    def _on_selected(self, idx):
        if idx < 0:
            return
        activate_cmd = self._combo.itemData(idx)
        if activate_cmd:
            self.env_activated.emit(activate_cmd)
            self._save_last_env(activate_cmd)

    def _browse_interp(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Python 解释器", "",
            "Python (*.exe);;All Files (*)"
        )
        if path:
            parent = os.path.dirname(path)
            activate_ps1 = os.path.join(parent, "Activate.ps1")
            activate_bat = os.path.join(parent, "activate.bat")
            if os.path.isfile(activate_ps1) or os.path.isfile(activate_bat):
                label = f"Custom ({os.path.basename(os.path.dirname(parent))})"
                activate = f". '{parent.replace(os.sep, '/')}/Activate'"
                self._combo.addItem(label, activate)
                self._combo.setCurrentIndex(self._combo.count() - 1)
            else:
                self.env_activated.emit(f"& '{path.replace(os.sep, '/')}'")

    def _load_saved_envs(self) -> List[dict]:
        try:
            if os.path.isfile(_ENV_CONFIG_FILE):
                with open(_ENV_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("envs", [])
        except Exception:
            pass
        return []

    def _save_last_env(self, activate_cmd: str):
        try:
            os.makedirs(os.path.dirname(_ENV_CONFIG_FILE), exist_ok=True)
            data = {"last": activate_cmd}
            if os.path.isfile(_ENV_CONFIG_FILE):
                with open(_ENV_CONFIG_FILE, "r", encoding="utf-8") as f:
                    old = json.load(f)
                data.update(old)
            data["last"] = activate_cmd
            with open(_ENV_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
