# -*- coding: utf-8 -*-
"""
WebBrowserPanel — 内置轻量浏览器
====================================
在 Lemon Agent 中直接浏览网页，无需切换外部浏览器。
适用于查看 API 官网、文档、Token 管理等场景。

用法：
    from ui.web_browser_panel import WebBrowserPanel
    panel = WebBrowserPanel()
    panel.navigate("https://platform.deepseek.com")
"""

import os
import sys

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QProgressBar, QFrame, QSplitter
)
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEngineSettings

# 主题样式（与主窗口一致）
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)
from ui.theme import *


class WebBrowserPanel(QWidget):
    """内置轻量浏览器面板"""

    url_changed = pyqtSignal(str)  # 当前 URL 变化时发出
    title_changed = pyqtSignal(str)  # 页面标题变化时发出

    # 预设常用网站
    PRESET_SITES = {
        "DeepSeek API": "https://platform.deepseek.com",
        "Ollama": "https://ollama.com",
        "OpenAI API": "https://platform.openai.com",
        "GitHub": "https://github.com",
        "PyPI": "https://pypi.org",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_url = ""
        self._history = []  # 浏览历史
        self._history_pos = -1
        self._init_ui()

    def _init_ui(self):
        """初始化界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- 顶部导航栏 --
        nav_bar = QWidget()
        nav_bar.setStyleSheet(f"""
            QWidget {{
                background: {BG_SURFACE};
                border-bottom: 1px solid {BORDER_DEFAULT};
            }}
        """)
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(8, 6, 8, 6)
        nav_layout.setSpacing(4)

        # 后退按钮
        self.back_btn = QPushButton("◀")
        self.back_btn.setToolTip("后退")
        self.back_btn.setFixedSize(32, 28)
        self.back_btn.setEnabled(False)
        self.back_btn.clicked.connect(self._go_back)
        nav_layout.addWidget(self.back_btn)

        # 前进按钮
        self.forward_btn = QPushButton("▶")
        self.forward_btn.setToolTip("前进")
        self.forward_btn.setFixedSize(32, 28)
        self.forward_btn.setEnabled(False)
        self.forward_btn.clicked.connect(self._go_forward)
        nav_layout.addWidget(self.forward_btn)

        # 刷新按钮
        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setToolTip("刷新")
        self.refresh_btn.setFixedSize(32, 28)
        self.refresh_btn.clicked.connect(self._refresh)
        nav_layout.addWidget(self.refresh_btn)

        # 主页按钮
        self.home_btn = QPushButton("⌂")
        self.home_btn.setToolTip("主页")
        self.home_btn.setFixedSize(32, 28)
        self.home_btn.clicked.connect(self._go_home)
        nav_layout.addWidget(self.home_btn)

        # URL 地址栏
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("输入网址后按 Enter 访问...")
        self.url_bar.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_ROOT};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                padding: 4px 10px;
                font-size: {FONT_SIZE_SM};
                font-family: {FONT_MONO};
            }}
            QLineEdit:focus {{
                border-color: {XIAOMI_ORANGE};
            }}
        """)
        self.url_bar.returnPressed.connect(self._on_url_entered)
        nav_layout.addWidget(self.url_bar, 1)

        # 预设站点快捷按钮
        self.preset_btn = QPushButton("▼")
        self.preset_btn.setToolTip("快速访问")
        self.preset_btn.setFixedSize(32, 28)
        self.preset_btn.clicked.connect(self._show_preset_menu)
        nav_layout.addWidget(self.preset_btn)

        # 设置导航按钮样式
        _nav_btn_style = f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: 1px solid transparent;
                border-radius: 4px;
                font-size: 14px;
                padding: 2px;
            }}
            QPushButton:hover {{
                background: {BG_SURFACE_HOVER};
                color: {TEXT_PRIMARY};
                border-color: {BORDER_DEFAULT};
            }}
            QPushButton:pressed {{
                background: {BG_SURFACE_ACTIVE};
            }}
            QPushButton:disabled {{
                color: #333;
            }}
        """
        for btn in [self.back_btn, self.forward_btn, self.refresh_btn,
                     self.home_btn, self.preset_btn]:
            btn.setStyleSheet(_nav_btn_style)

        layout.addWidget(nav_bar)

        # -- 加载进度条 --
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(3)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: transparent;
                border: none;
            }}
            QProgressBar::chunk {{
                background: {XIAOMI_ORANGE};
                border-radius: 1px;
            }}
        """)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # -- WebEngine 视图 --
        self._webview = QWebEngineView()
        self._webview.setStyleSheet(f"""
            QWebEngineView {{
                background: {BG_ROOT};
            }}
        """)

        # WebEngine 设置
        settings = self._webview.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, False)

        # 信号连接
        self._webview.urlChanged.connect(self._on_url_changed)
        self._webview.titleChanged.connect(self._on_title_changed)
        self._webview.loadStarted.connect(self._on_load_started)
        self._webview.loadProgress.connect(self._on_load_progress)
        self._webview.loadFinished.connect(self._on_load_finished)

        layout.addWidget(self._webview, 1)

        # 加载默认主页
        QTimer.singleShot(100, self._go_home)

    # ==================== 导航 ====================

    def navigate(self, url: str):
        """导航到指定 URL"""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._webview.setUrl(QUrl(url))

    def _on_url_entered(self):
        """地址栏回车"""
        url = self.url_bar.text().strip()
        if url:
            self.navigate(url)

    def _go_back(self):
        """后退"""
        if self._history_pos > 0:
            self._history_pos -= 1
            self._webview.setUrl(QUrl(self._history[self._history_pos]))
        self._update_nav_buttons()

    def _go_forward(self):
        """前进"""
        if self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            self._webview.setUrl(QUrl(self._history[self._history_pos]))
        self._update_nav_buttons()

    def _refresh(self):
        """刷新"""
        self._webview.reload()

    def _go_home(self):
        """主页"""
        self.navigate("https://www.google.com")

    # ==================== 信号处理 ====================

    def _on_url_changed(self, url: QUrl):
        """URL 变化"""
        url_str = url.toString()
        self._current_url = url_str
        self.url_bar.setText(url_str)
        self.url_changed.emit(url_str)

        # 更新历史
        if not self._history or self._history[-1] != url_str:
            # 如果在历史中间位置导航，截断后续历史
            if self._history_pos < len(self._history) - 1:
                self._history = self._history[:self._history_pos + 1]
            self._history.append(url_str)
            self._history_pos = len(self._history) - 1
        self._update_nav_buttons()

    def _on_title_changed(self, title: str):
        """页面标题变化"""
        self.title_changed.emit(title)

    def _on_load_started(self):
        """加载开始"""
        self.progress_bar.setValue(0)
        self.progress_bar.show()

    def _on_load_progress(self, progress: int):
        """加载进度"""
        self.progress_bar.setValue(progress)

    def _on_load_finished(self, ok: bool):
        """加载完成"""
        self.progress_bar.hide()
        self.progress_bar.setValue(0)
        self._update_nav_buttons()

    def _update_nav_buttons(self):
        """更新导航按钮状态"""
        self.back_btn.setEnabled(self._history_pos > 0)
        self.forward_btn.setEnabled(self._history_pos < len(self._history) - 1)

    def _show_preset_menu(self):
        """显示预设站点菜单"""
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 24px;
                font-size: {FONT_SIZE_SM};
            }}
            QMenu::item:selected {{
                background: {XIAOMI_ORANGE};
                color: #fff;
                border-radius: 4px;
            }}
        """)

        for name, url in self.PRESET_SITES.items():
            action = menu.addAction(f"  {name}")
            action.setData(url)
            action.triggered.connect(lambda checked, u=url: self.navigate(u))

        menu.addSeparator()

        # 手动输入
        custom = menu.addAction("  输入自定义网址...")
        custom.triggered.connect(self._on_manual_url)

        menu.exec_(self.preset_btn.mapToGlobal(
            self.preset_btn.rect().bottomLeft()
        ))

    def _on_manual_url(self):
        """手动输入自定义网址"""
        from PyQt5.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(
            self, "打开网址", "输入网址:",
            text=self.url_bar.text()
        )
        if ok and url.strip():
            self.navigate(url.strip())

    # ==================== 快捷操作 ====================

    def copy_url(self):
        """复制当前 URL"""
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(self._current_url)

    def reload_ignore_cache(self):
        """强制刷新（忽略缓存）"""
        self._webview.triggerPageAction(QWebEngineView.WebAction.ReloadAndBypassCache)

    # ==================== 清理 ====================

    def cleanup(self):
        """释放资源"""
        if self._webview:
            self._webview.stop()
            self._webview.page().deleteLater()
            self._webview = None