# -*- coding: utf-8 -*-
"""Lemon Work —— 银行智能助手客户端（单列对话 + 卡片操作 + 合规审计抽屉）

架构：
  前端 ui/index.html（自制单列界面，无第三方框架）
        ↕ HTTP (127.0.0.1:8091)
  后端 shared/bank_gateway_server.py（分级/MFA/HITL/审计）
        ↕
  银行技能 shared/skills_builtin/bank_skills.py + MockBank 沙盒

说明：
  · 界面只保留"对话 + 卡片 + 抽屉"，隐藏文件树/终端/代码面板（聚焦模式）
  · 后端复用标准模式全部核心能力（EngineManager / SkillRegistry / 风控 / 审计）
  · 零第三方 Web 依赖；Qt 环境自举，避免中文路径导致的 WebEngine 崩溃
"""
from __future__ import annotations

import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "standard_mode", "core"))
os.environ["PYTHONPATH"] = ROOT

# ── Qt 环境自举（与 launcher.py 同策略）──
SP = os.path.join(ROOT, "_py312", "Lib", "site-packages")
QT5BIN = os.path.join(SP, "PyQt5", "Qt5", "bin")
QT_PLUGIN = os.path.join(SP, "PyQt5", "Qt5", "plugins")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(QT_PLUGIN, "platforms")
os.environ["QT_PLUGIN_PATH"] = QT_PLUGIN
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
_qp = os.path.join(QT5BIN, "QtWebEngineProcess.exe")
if os.path.exists(_qp):
    os.environ["QTWEBENGINEPROCESS_PATH"] = _qp
_res = os.path.join(SP, "PyQt5", "Qt5", "resources")
if os.path.isdir(_res):
    os.environ["QTWEBENGINE_RESOURCES_PATH"] = _res
if os.path.isdir(QT5BIN):
    os.environ["PATH"] = QT5BIN + os.pathsep + ROOT + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(QT5BIN)
    except Exception:
        pass

# pythonw 下 stdout 为 None → 重定向，避免崩溃
try:
    if sys.stdout is None:
        sys.stdout = open(os.path.join(ROOT, "运行日志.txt"), "w", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = open(os.path.join(ROOT, "运行日志.err.txt"), "w", encoding="utf-8", buffering=1)
except Exception:
    pass

APP_NAME = "Lemon Work"
PORT = 8091
ICON = os.path.join(ROOT, "..", "icon", "lemonwork.ico")


def boot_backend():
    """初始化沙盒账户 + 注册银行技能 + 启动 HTTP 网关（后台线程）"""
    from shared.mock_bank import MockBank, set_mock_bank, get_mock_bank
    from shared import permission_tiers as PT
    from shared import bank_gateway_server as GW

    db = os.path.join(ROOT, "data", "lw_bank.db")
    os.makedirs(os.path.dirname(db), exist_ok=True)
    set_mock_bank(MockBank(db_path=db))
    PT.set_audit_db(os.path.join(ROOT, "data", "lw_permission.db"))
    PT.reset_mfa_vault()

    # 演示账户充值到 10000 元（种子仅 250 元，无法演示红区大额转账）
    mb = get_mock_bank()
    try:
        mb._db.execute("UPDATE accounts SET balance=MAX(balance, 1000000) WHERE account_id='ACC001'")
        mb._db.commit()
    except Exception:
        pass

    from shared.skills_builtin.bank_skills import register_bank_skills
    r = register_bank_skills()
    print("[LemonWork] 银行技能注册:", r)

    srv = GW.start_server(PORT)
    print("[LemonWork] 网关已启动 http://127.0.0.1:%d" % PORT)
    return srv


def main():
    srv = boot_backend()

    from PyQt5.QtCore import Qt, QUrl
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QApplication, QMainWindow
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    win = QMainWindow()
    win.setWindowTitle(APP_NAME + " · 银行智能助手")
    win.resize(1200, 820)
    win.setMinimumSize(900, 640)
    if os.path.exists(ICON):
        win.setWindowIcon(QIcon(ICON))

    view = QWebEngineView()
    s = view.settings()
    for attr in ("LocalContentCanAccessRemoteUrls", "LocalContentCanAccessFileUrls",
                 "JavascriptEnabled", "LocalStorageEnabled"):
        try:
            s.setAttribute(getattr(QWebEngineSettings, attr), True)
        except Exception:
            pass
    view.load(QUrl.fromLocalFile(os.path.join(ROOT, "ui", "index.html")))
    win.setCentralWidget(view)
    win.show()

    code = app.exec_()
    try:
        srv.shutdown()
    except Exception:
        pass
    sys.exit(code)


if __name__ == "__main__":
    main()
