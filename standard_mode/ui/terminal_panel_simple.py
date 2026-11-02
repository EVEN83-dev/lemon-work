# -*- coding: utf-8 -*-
"""
简化终端面板 — ConPTY + WebSocket (参考 PyCharm JediTerm / VS Code Terminal)
============================================================================
架构：xterm.js → WebSocket → TerminalServer → ShellBridge → ConPTY

第391章 (A 战区 bridge 死亡根治)：
  原本地进程内 WebChannel 桥传输层（PyQt5 5.15.2 与 qwebchannel.js 的 init
  response 协议差异导致 init 回调永不触发 → bridge keys=[] 耗尽重试）已降级为
  deprecated fallback，默认走 WebSocket。

每 SimpleTerminalPanel 实例持有独立的 TerminalServer (独立 ws_port)，支持
TerminalManager 多实例隔离（每实例独立 PTY+WebSocket 路径）。对外接口 set_cwd /
实例名不变。
"""
import os
import uuid
from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QMenu
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings

try:
    from ui.theme import *
except ImportError:
    from standard_mode.ui.theme import *
try:
    from ui.terminal_server import TerminalServer, assign_panel_sid
except ImportError:
    from standard_mode.ui.terminal_server import TerminalServer, assign_panel_sid


class SimpleTerminalPanel(QWidget):
    output_ready = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cwd = os.getcwd()
        self._server: TerminalServer | None = None
        self._webview: QWebEngineView | None = None
        self._started = False
        self._pending_first_show = True
        self._user_requested_stop = False
        self._reconnect_attempts = 0
        self._max_reconnect = 5
        self._obj_name = f"terminal_{uuid.uuid4().hex[:8]}"
        self._log_file = None
        self._log_enabled = False
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QFrame()
        bar.setFixedHeight(32)
        bar.setStyleSheet(f"background: {BG_SECONDARY}; border-bottom: 1px solid {BORDER_SUBTLE};")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(12, 0, 10, 0)
        bar_l.setSpacing(8)

        self.status_label = QLabel("● 启动中")
        self.status_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px; background: transparent;")
        bar_l.addWidget(self.status_label)

        self.cwd_label = QLabel(os.path.basename(self._cwd) or self._cwd)
        self.cwd_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; background: transparent;")
        bar_l.addWidget(self.cwd_label)

        bar_l.addStretch()

        self.btn_interrupt = QPushButton("Ctrl+C")
        self.btn_interrupt.setFixedHeight(24)
        self.btn_interrupt.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 4px; padding: 2px 8px;
            }}
            QPushButton:hover {{ color: {ERROR}; border-color: {ERROR}; }}
        """)
        self.btn_interrupt.clicked.connect(self.interrupt)
        bar_l.addWidget(self.btn_interrupt)

        self.btn_restart = QPushButton("重启")
        self.btn_restart.setFixedHeight(24)
        self.btn_restart.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 4px; padding: 2px 8px;
            }}
            QPushButton:hover {{ color: {XIAOMI_ORANGE}; border-color: {XIAOMI_ORANGE}; }}
        """)
        self.btn_restart.clicked.connect(self.restart)
        bar_l.addWidget(self.btn_restart)

        self.btn_settings = QPushButton("...")
        self.btn_settings.setFixedSize(24, 24)
        self.btn_settings.setToolTip("终端设置")
        self.btn_settings.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 4px; font-size: 12px;
            }}
            QPushButton:hover {{ color: {XIAOMI_ORANGE}; border-color: {XIAOMI_ORANGE}; }}
        """)
        self.btn_settings.clicked.connect(self._show_settings_menu)
        bar_l.addWidget(self.btn_settings)

        layout.addWidget(bar)

        self._webview = QWebEngineView()
        self._webview.setStyleSheet(f"background: {BG_ROOT}; border: none;")
        settings = self._webview.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanPaste, True)
        layout.addWidget(self._webview, 1)

        self.setAcceptDrops(True)

    # ============================================================
    # 服务启动（延迟到首次 show）
    # ============================================================
    def _start_service(self):
        if self._server is not None:
            return

        try:
            self._server = TerminalServer(parent=self)
            http_port, ws_port, auth_token = self._server.start()
            self._server.default_cwd = self._cwd
            # ★ 405A1: 分配跨应用重启稳定的会话 SID
            self._session_id = assign_panel_sid(self._cwd, getattr(self, '_session_id', None))
            print(f"[SimpleTerminal] session_id={self._session_id}", flush=True)
        except Exception as e:
            print(f"[SimpleTerminal] TerminalServer 启动失败: {e}", flush=True)
            self.status_label.setText(f"● 服务失败: {e}")
            self.status_label.setStyleSheet(f"color: {ERROR}; font-size: 11px; background: transparent;")
            return

        # xterm.js 通过 WebSocket 连接 — 配置通过 URL query 传入避免 runJavaScript 时序竞争
        url = (f"http://127.0.0.1:{http_port}/terminal_xterm.html"
               f"?ws={ws_port}&token={auth_token}&sid={self._session_id}")
        self._webview.load(QUrl(url))
        self._webview.loadFinished.connect(self._on_page_loaded)
        self.status_label.setText("● 连接中...")
        print(f"[SimpleTerminal] HTTP={http_port} WS={ws_port} sid={self._session_id}", flush=True)

    def _on_page_loaded(self, ok: bool):
        if not ok:
            self.status_label.setText("● 页面加载失败")
            self.status_label.setStyleSheet(f"color: {ERROR}; font-size: 11px; background: transparent;")
            return
        print("[SimpleTerminal] terminal_xterm.html 加载完成, xterm.js 将通过 WebSocket 连接", flush=True)
        self._started = True
        self.status_label.setText("● 运行中")
        self.status_label.setToolTip(f"WebSocket · {self._obj_name}")
        self.status_label.setStyleSheet(f"color: #4caf50; font-size: 11px; background: transparent;")

    # ============================================================
    # 日志
    # ============================================================
    def _enable_logging(self, log_path: str = None):
        if not log_path:
            log_dir = os.path.join(os.path.expanduser("~"), ".mimo_agent", "terminal_logs")
            os.makedirs(log_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = os.path.join(log_dir, f"terminal_{timestamp}.log")
        try:
            self._log_file = open(log_path, "w", encoding="utf-8")
            self._log_enabled = True
            self.status_label.setText("● 日志记录中")
            self.status_label.setStyleSheet(f"color: #4caf50; font-size: 11px; background: transparent;")
        except Exception as e:
            self.status_label.setText(f"● 日志失败: {e}")
            self.status_label.setStyleSheet(f"color: {ERROR}; font-size: 11px; background: transparent;")

    def _disable_logging(self):
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        self._log_enabled = False
        if self._started:
            self.status_label.setText("● 运行中")
            self.status_label.setStyleSheet(f"color: #4caf50; font-size: 11px; background: transparent;")

    def _open_log_dir(self):
        log_dir = os.path.join(os.path.expanduser("~"), ".mimo_agent", "terminal_logs")
        os.makedirs(log_dir, exist_ok=True)
        import subprocess
        try:
            subprocess.Popen(["explorer", log_dir])
        except Exception:
            pass

    # ============================================================
    # 设置菜单
    # ============================================================
    def _show_settings_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {BG_SECONDARY}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_SUBTLE}; padding: 4px;
            }}
            QMenu::item:selected {{ background: {XIAOMI_ORANGE}22; color: {XIAOMI_ORANGE}; }}
        """)
        action_shortcuts = menu.addAction("快捷键设置...")
        action_log = menu.addAction("启用日志记录")
        action_log_dir = menu.addAction("打开日志目录")
        menu.addSeparator()
        action_no_log = menu.addAction("关闭日志记录")
        action = menu.exec_(self.btn_settings.mapToGlobal(self.btn_settings.rect().bottomLeft()))
        if action == action_shortcuts:
            self._open_shortcuts_panel()
        elif action == action_log:
            self._enable_logging()
        elif action == action_log_dir:
            self._open_log_dir()
        elif action == action_no_log:
            self._disable_logging()

    def _open_shortcuts_panel(self):
        try:
            from ui.terminal_shortcuts_panel import ShortcutEditPanel
        except ImportError:
            from standard_mode.ui.terminal_shortcuts_panel import ShortcutEditPanel
        panel = ShortcutEditPanel(self)
        panel.shortcuts_changed.connect(self._on_shortcuts_changed)
        panel.exec_()

    def _on_shortcuts_changed(self, shortcuts: dict):
        # 快捷键设置在 xterm.html 端 attachCustomKeyEventHandler 内联处理；
        # 仅持久化配置文件供下次加载。
        try:
            from ui.terminal_config import save_shortcuts
            save_shortcuts(shortcuts)
        except Exception:
            pass

    # ============================================================
    # 公共 API (与旧 WebChannel 桥版签名相同)
    # ============================================================
    def set_cwd(self, path: str):
        self._cwd = os.path.abspath(path)
        self.cwd_label.setText(os.path.basename(self._cwd) or self._cwd)
        if self._server is not None:
            self._server.default_cwd = self._cwd

    def start(self):
        if self._started:
            return
        if self._server is None:
            self._start_service()

    def restart(self):
        """重启终端 — 重建 TerminalServer 以获得独立 ws_port。"""
        self._user_requested_stop = True
        self._reconnect_attempts = 0
        self.shutdown()
        self._user_requested_stop = False
        self._started = False
        self.status_label.setText("● 重启中...")
        self.status_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px; background: transparent;")
        QTimer.singleShot(100, self._start_service)

    def interrupt(self):
        """发送 Ctrl+C (\\x03) 到活跃 PTY。"""
        if self._server is not None:
            self._server.interrupt_current()

    def clear_output(self):
        if self._webview:
            self._webview.page().runJavaScript("if(window.term){term.clear();}")

    def shutdown(self):
        self._user_requested_stop = True
        self._disable_logging()
        if self._server is not None:
            try:
                self._server.stop()
            except Exception as e:
                print(f"[SimpleTerminal] server.stop 失败: {e}", flush=True)
            self._server = None

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, '_pending_first_show', False):
            self._pending_first_show = False
            self._start_service()
            return
        if not self._started:
            self.start()
            return

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # xterm.js 端 ResizeObserver 已处理 fit；发一条 JS 触发 resize
        if self._webview:
            self._webview.page().runJavaScript("if(window._termFit){window._termFit();}")
