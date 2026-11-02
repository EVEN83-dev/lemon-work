# -*- coding: utf-8 -*-
"""
TerminalPanel — 终端面板统一入口
==================================
第391章 (A 专区 bridge 死亡根治)：架构统一回归 ConPTY + WebSocket。

新架构：
  xterm.js → WebSocket → TerminalServer → TerminalBridge(ShellBridge) → ConPTY

旧架构（QWebChannel）已降级为 deprecated fallback，保留在 terminal_simple.html 与
terminal_bridge_simple.py 中，但 SimpleTerminalPanel 不再使用。

TerminalPanel 现为 SimpleTerminalPanel 的别名，保持 main_window.py 等调用方兼容。
"""
import importlib
import os
import sys

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_mod = importlib.import_module("ui.terminal_panel_simple")
TerminalPanel = _mod.SimpleTerminalPanel
