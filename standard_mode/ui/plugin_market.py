# -*- coding: utf-8 -*-
"""
PluginMarket — 插件市场 UI 面板
=================================
提供插件浏览、安装、启用/禁用、卸载等操作界面。

功能：
- 插件列表展示（名称、版本、作者、描述、状态）
- 启用/禁用插件
- 安装/卸载插件
- 搜索过滤
- 插件详情预览

技术：
- PyQt5 QTableWidget 展示列表
- 与 PluginManager 信号连接
"""

import os
from typing import Optional, List, Dict, Any

from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QMessageBox, QSplitter, QTextBrowser, QProgressBar, QFrame
)
from PyQt5.QtGui import QColor, QFont

from standard_mode.core.i18n import _t

# ★ v3.93: 颜色定义 — Lemon Code 品牌主题（橙黄）而非 VSCode 蓝
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(__file__))
from theme import (
    LEMON_ORANGE as _LEMON, LEMON_YELLOW as _LEMON_LIGHT,
    BG_ROOT, BG_SURFACE, BG_SURFACE_HOVER, BG_SURFACE_ACTIVE, BG_PANEL,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY, TEXT_MUTED,
    BORDER_DEFAULT, BORDER_SUBTLE, RADIUS_MD, RADIUS_SM,
    SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR,
    CARD_RADIUS, CARD_BG, svg_to_qicon,
)
from ui.design.tokens import Lemon
_COLOR_BG = BG_ROOT
_COLOR_SURFACE = BG_SURFACE
_COLOR_BORDER = BORDER_DEFAULT
_COLOR_ACCENT = _LEMON
_COLOR_ACCENT_LIGHT = _LEMON_LIGHT
_COLOR_SUCCESS = SUCCESS_COLOR
_COLOR_WARNING = WARNING_COLOR
_COLOR_ERROR = ERROR_COLOR


class PluginMarketPanel(QWidget):
    """插件市场面板"""

    # 信号
    plugin_install_requested = pyqtSignal(str)    # 插件名称（请求安装）
    plugin_uninstall_requested = pyqtSignal(str)  # 插件名称（请求卸载）
    plugin_enable_requested = pyqtSignal(str)     # 插件名称（请求启用）
    plugin_disable_requested = pyqtSignal(str)    # 插件名称（请求禁用）
    plugin_reload_requested = pyqtSignal(str)     # 插件名称（请求重载）

    def __init__(self, plugin_manager=None, parent=None):
        """
        Args:
            plugin_manager: PluginManager 实例（可选，可后续通过 set_manager 设置）
        """
        super().__init__(parent)
        self._manager = plugin_manager
        self._plugins_data: List[Dict[str, Any]] = []
        self._current_plugin_name: Optional[str] = None

        self._init_ui()
        self._connect_signals()

        # 加载插件列表
        if self._manager:
            self.refresh_plugins()

    def set_manager(self, manager):
        """设置 PluginManager 实例"""
        self._manager = manager
        self._connect_manager_signals()
        self.refresh_plugins()

    # ============================================================
    # UI 初始化
    # ============================================================

    def _init_ui(self):
        """初始化 UI 布局 — v3.97 高级简约版"""
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {_COLOR_BG};
                color: {TEXT_PRIMARY};
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            }}
            QLineEdit {{
                background-color: {_COLOR_SURFACE};
                border: 1px solid {_COLOR_BORDER};
                border-radius: {RADIUS_MD};
                padding: 7px 12px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
            }}
            QLineEdit:focus {{ border: 1px solid {_COLOR_ACCENT}; }}
            QPushButton {{
                background-color: {_COLOR_SURFACE};
                border: 1px solid {_COLOR_BORDER};
                border-radius: {RADIUS_MD};
                padding: 6px 14px;
                color: {TEXT_PRIMARY};
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {BG_SURFACE_HOVER};
                border-color: {_COLOR_ACCENT};
            }}
            QPushButton:pressed {{ background-color: {_COLOR_ACCENT}; color: #111; }}
            QPushButton:disabled {{ background-color: {BG_SURFACE_ACTIVE}; color: {TEXT_MUTED}; }}
            QTableWidget {{
                background-color: {_COLOR_SURFACE};
                border: 1px solid {_COLOR_BORDER};
                border-radius: {RADIUS_MD};
                gridline-color: {BORDER_SUBTLE};
            }}
            QTableWidget::item {{ padding: 6px 8px; }}
            QTableWidget::item:selected {{
                background-color: {_COLOR_ACCENT};
                color: #111;
            }}
            QHeaderView::section {{
                background-color: {BG_PANEL};
                border: none;
                border-bottom: 1px solid {_COLOR_BORDER};
                padding: 7px 8px;
                font-weight: 700;
                font-size: 12px;
            }}
            QTextBrowser {{
                background-color: {_COLOR_SURFACE};
                border: 1px solid {_COLOR_BORDER};
                border-radius: {RADIUS_MD};
                padding: 8px;
            }}
            QProgressBar {{
                background-color: {_COLOR_SURFACE};
                border: 1px solid {_COLOR_BORDER};
                border-radius: {RADIUS_MD};
                text-align: center;
                height: 8px;
            }}
            QProgressBar::chunk {{
                background-color: {_COLOR_ACCENT};
                border-radius: {RADIUS_MD};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 顶部工具栏
        toolbar = QHBoxLayout()

        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_t("plugin.market.search_placeholder"))
        self.search_input.textChanged.connect(self._on_search)
        toolbar.addWidget(self.search_input, 1)

        # 刷新按钮
        self.refresh_btn = QPushButton("🔄 " + _t("plugin.market.refresh"))
        self.refresh_btn.setFixedWidth(80)
        self.refresh_btn.clicked.connect(self._on_refresh)
        toolbar.addWidget(self.refresh_btn)

        layout.addLayout(toolbar)

        # 分割器：上列表 + 下详情
        splitter = QSplitter(Qt.Vertical)

        # 上部：插件列表表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            _t("plugin.market.col_name"), _t("plugin.market.col_version"),
            _t("plugin.market.col_author"), _t("plugin.market.col_status"),
            _t("plugin.market.col_action")
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 120)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table)

        # 下部：插件详情
        details_frame = QFrame()
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(0, 0, 0, 0)

        # 详情标题
        self.detail_title = QLabel(_t("plugin.market.detail_title"))
        self.detail_title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        details_layout.addWidget(self.detail_title)

        # 详情内容
        self.detail_browser = QTextBrowser()
        self.detail_browser.setOpenExternalLinks(False)
        self.detail_browser.setPlaceholderText(_t("plugin.market.detail_placeholder"))
        details_layout.addWidget(self.detail_browser)

        # 操作按钮区
        btn_layout = QHBoxLayout()

        self.enable_btn = QPushButton(_t("plugin.market.enable"))
        self.enable_btn.setIcon(svg_to_qicon("check", size=14))
        self.enable_btn.setFixedWidth(80)
        self.enable_btn.clicked.connect(self._on_enable)
        btn_layout.addWidget(self.enable_btn)

        self.disable_btn = QPushButton(_t("plugin.market.disable"))
        self.disable_btn.setIcon(svg_to_qicon("ban", size=14))
        self.disable_btn.setFixedWidth(80)
        self.disable_btn.clicked.connect(self._on_disable)
        btn_layout.addWidget(self.disable_btn)

        self.reload_btn = QPushButton(_t("plugin.market.reload"))
        self.reload_btn.setIcon(svg_to_qicon("refresh", size=14))
        self.reload_btn.setFixedWidth(80)
        self.reload_btn.clicked.connect(self._on_reload)
        btn_layout.addWidget(self.reload_btn)

        self.uninstall_btn = QPushButton(_t("plugin.market.uninstall"))
        self.uninstall_btn.setIcon(svg_to_qicon("trash", size=14))
        self.uninstall_btn.setFixedWidth(80)
        self.uninstall_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Lemon.ERROR_BG_DARK};
                border: 1px solid {Lemon.ERROR_BG_DARK};
            }}
            QPushButton:hover {{
                background-color: {Lemon.ERROR_BG_DARK};
            }}
        """)
        self.uninstall_btn.clicked.connect(self._on_uninstall)
        btn_layout.addWidget(self.uninstall_btn)

        btn_layout.addStretch()
        details_layout.addLayout(btn_layout)

        splitter.addWidget(details_frame)
        splitter.setSizes([300, 200])

        layout.addWidget(splitter)

        # 底部状态栏
        self.status_label = QLabel(_t("plugin.market.status_ready"))
        self.status_label.setStyleSheet(f"color: {_COLOR_SUCCESS};")
        layout.addWidget(self.status_label)

    def _connect_signals(self):
        """连接内部信号"""
        pass  # 信号连接在按钮的 clicked 中已完成

    def _connect_manager_signals(self):
        """连接 PluginManager 信号"""
        if not self._manager:
            return

        self._manager.plugin_loaded.connect(self._on_plugin_loaded)
        self._manager.plugin_unloaded.connect(self._on_plugin_unloaded)
        self._manager.plugin_error.connect(self._on_plugin_error)
        self._manager.plugin_reloaded.connect(self._on_plugin_reloaded)

    # ============================================================
    # 插件列表刷新
    # ============================================================

    def refresh_plugins(self):
        """刷新插件列表"""
        if not self._manager:
            self._update_status("⚠️ PluginManager 未设置", "warning")
            return

        self._plugins_data = []

        # 获取所有插件
        plugins = self._manager.get_all_plugins()
        for plugin in plugins:
            name = plugin.name
            version = plugin.version
            # 尝试从 metadata 或属性获取作者和描述
            meta = getattr(self._manager, "_plugin_metadata", {}).get(name, {})
            author = meta.get("author", getattr(plugin, "author", "未知"))
            description = meta.get("description", getattr(plugin, "description", ""))
            enabled = self._manager._plugin_enabled.get(name, True)

            self._plugins_data.append({
                "name": name,
                "version": version,
                "author": author,
                "description": description,
                "enabled": enabled,
                "plugin": plugin,
            })

        self._update_table()
        self._update_status(f"已加载 {len(plugins)} 个插件", "success")

    def _update_table(self):
        """更新表格显示"""
        self.table.setRowCount(0)

        for row, plugin_data in enumerate(self._plugins_data):
            self.table.insertRow(row)

            # 名称
            name_item = QTableWidgetItem(plugin_data["name"])
            name_item.setData(Qt.UserRole, plugin_data["name"])
            self.table.setItem(row, 0, name_item)

            # 版本
            version_item = QTableWidgetItem(plugin_data["version"])
            version_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, version_item)

            # 作者
            author_item = QTableWidgetItem(plugin_data["author"])
            self.table.setItem(row, 2, author_item)

            # 状态
            status = _t("plugin.market.status_enabled") if plugin_data["enabled"] else _t("plugin.market.status_disabled")
            status_item = QTableWidgetItem(status)
            status_item.setForeground(QColor(_COLOR_SUCCESS if plugin_data["enabled"] else _COLOR_WARNING))
            status_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, status_item)

            # 操作按钮（使用文本替代）
            op_text = "启用/禁用"
            op_item = QTableWidgetItem(op_text)
            op_item.setForeground(QColor(_COLOR_ACCENT))
            op_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, op_item)

        # 选中第一行
        if self._plugins_data:
            self.table.selectRow(0)

    # ============================================================
    # 事件处理
    # ============================================================

    def _on_search(self, text: str):
        """搜索过滤"""
        keyword = text.lower().strip()
        if not keyword:
            self._update_table()
            return

        self.table.setRowCount(0)
        for plugin_data in self._plugins_data:
            if (keyword in plugin_data["name"].lower() or
                keyword in plugin_data["author"].lower() or
                keyword in plugin_data["description"].lower()):
                row = self.table.rowCount()
                self.table.insertRow(row)

                name_item = QTableWidgetItem(plugin_data["name"])
                name_item.setData(Qt.UserRole, plugin_data["name"])
                self.table.setItem(row, 0, name_item)

                version_item = QTableWidgetItem(plugin_data["version"])
                version_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, 1, version_item)

                author_item = QTableWidgetItem(plugin_data["author"])
                self.table.setItem(row, 2, author_item)

                status = _t("plugin.market.status_enabled") if plugin_data["enabled"] else _t("plugin.market.status_disabled")
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor(_COLOR_SUCCESS if plugin_data["enabled"] else _COLOR_WARNING))
                status_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, 3, status_item)

                op_item = QTableWidgetItem("启用/禁用")
                op_item.setForeground(QColor(_COLOR_ACCENT))
                op_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, 4, op_item)

    def _on_refresh(self):
        """刷新按钮点击"""
        self.refresh_plugins()

    def _on_selection_changed(self):
        """选择行变化"""
        selected = self.table.selectedItems()
        if not selected:
            self._current_plugin_name = None
            self._update_detail(None)
            return

        row = selected[0].row()
        name_item = self.table.item(row, 0)
        if name_item:
            self._current_plugin_name = name_item.data(Qt.UserRole)
            # 找到对应插件数据
            plugin_data = next(
                (p for p in self._plugins_data if p["name"] == self._current_plugin_name),
                None
            )
            self._update_detail(plugin_data)
            self._update_buttons(plugin_data)

    def _update_detail(self, plugin_data: Optional[Dict]):
        """更新详情显示"""
        if not plugin_data:
            self.detail_browser.setHtml(f"<p style='color: {Lemon.SECONDARY};'>{_t('plugin.market.detail_placeholder')}</p>")
            self.detail_title.setText(_t("plugin.market.detail_title"))
            return

        name = plugin_data.get("name", "未知")
        version = plugin_data.get("version", "?")
        author = plugin_data.get("author", "未知")
        description = plugin_data.get("description", "暂无描述")
        enabled = plugin_data.get("enabled", True)
        plugin = plugin_data.get("plugin")

        self.detail_title.setText(f"{_t('plugin.market.detail_title')} — {name}")

        # 获取 Tool 和 Skill 数量
        tools_count = 0
        skills_count = 0
        hooks_count = 0
        if plugin:
            tools_count = len(plugin.get_tools() if hasattr(plugin, "get_tools") else [])
            skills_count = len(plugin.get_skills() if hasattr(plugin, "get_skills") else [])
            hooks_count = len(plugin.get_hooks() if hasattr(plugin, "get_hooks") else [])

        html = f"""
        <style>
            body {{ color: {TEXT_PRIMARY}; font-family: 'Microsoft YaHei UI', sans-serif; }}
            .label {{ color: {_COLOR_ACCENT}; font-weight: bold; }}
            .value {{ color: {TEXT_PRIMARY}; }}
            .status-enabled {{ color: {_COLOR_SUCCESS}; }}
            .status-disabled {{ color: {_COLOR_WARNING}; }}
        </style>
        <h3>{name}</h3>
        <p><span class='label'>版本:</span> <span class='value'>{version}</span></p>
        <p><span class='label'>作者:</span> <span class='value'>{author}</span></p>
        <p><span class='label'>状态:</span> 
            <span class='{"status-enabled" if enabled else "status-disabled"}'>
                {"已启用" if enabled else "已禁用"}
            </span>
        </p>
        <hr style='border-color: {_COLOR_BORDER};'/>
        <h4>描述</h4>
        <p>{description or "暂无描述"}</p>
        <hr style='border-color: {_COLOR_BORDER};'/>
        <h4>功能</h4>
        <ul>
            <li><span class='label'>Tools:</span> {tools_count} 个</li>
            <li><span class='label'>Skills:</span> {skills_count} 个</li>
            <li><span class='label'>Hooks:</span> {hooks_count} 个</li>
        </ul>
        """
        self.detail_browser.setHtml(html)

    def _update_buttons(self, plugin_data: Optional[Dict]):
        """更新按钮状态"""
        if not plugin_data:
            self.enable_btn.setEnabled(False)
            self.disable_btn.setEnabled(False)
            self.reload_btn.setEnabled(False)
            self.uninstall_btn.setEnabled(False)
            return

        enabled = plugin_data.get("enabled", True)
        self.enable_btn.setEnabled(not enabled)
        self.disable_btn.setEnabled(enabled)
        self.reload_btn.setEnabled(True)
        self.uninstall_btn.setEnabled(True)

    def _on_enable(self):
        """启用插件"""
        if not self._current_plugin_name:
            return
        self.plugin_enable_requested.emit(self._current_plugin_name)
        if self._manager:
            self._manager._plugin_enabled[self._current_plugin_name] = True
            self.refresh_plugins()

    def _on_disable(self):
        """禁用插件"""
        if not self._current_plugin_name:
            return
        self.plugin_disable_requested.emit(self._current_plugin_name)
        if self._manager:
            self._manager._plugin_enabled[self._current_plugin_name] = False
            self.refresh_plugins()

    def _on_reload(self):
        """重载插件"""
        if not self._current_plugin_name:
            return
        self.plugin_reload_requested.emit(self._current_plugin_name)
        if self._manager:
            path = self._manager._plugin_paths.get(self._current_plugin_name)
            if path:
                self._manager.reload_plugin(self._current_plugin_name)
                self.refresh_plugins()

    def _on_uninstall(self):
        """卸载插件"""
        if not self._current_plugin_name:
            return

        reply = QMessageBox.warning(
            self,
            "确认卸载",
            f"确定要卸载插件 '{self._current_plugin_name}' 吗？\n\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.plugin_uninstall_requested.emit(self._current_plugin_name)
            if self._manager:
                self._manager.unregister_plugin(self._current_plugin_name)
                self.refresh_plugins()

    # ============================================================
    # PluginManager 信号回调
    # ============================================================

    def _on_plugin_loaded(self, name: str):
        """插件加载完成"""
        self._update_status(f"插件 '{name}' 加载成功", "success")
        self.refresh_plugins()

    def _on_plugin_unloaded(self, name: str):
        """插件卸载完成"""
        self._update_status(f"插件 '{name}' 已卸载", "success")
        self.refresh_plugins()

    def _on_plugin_error(self, name: str, error: str):
        """插件错误"""
        self._update_status(f"插件 '{name}' 错误: {error}", "error")

    def _on_plugin_reloaded(self, name: str):
        """插件重载完成"""
        self._update_status(f"🔄 插件 '{name}' 已重载", "success")
        self.refresh_plugins()

    def _update_status(self, text: str, level: str = "info"):
        """更新状态栏"""
        color_map = {
            "success": _COLOR_SUCCESS,
            "warning": _COLOR_WARNING,
            "error": _COLOR_ERROR,
            "info": TEXT_PRIMARY,
        }
        color = color_map.get(level, TEXT_PRIMARY)
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(text)