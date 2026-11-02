# -*- coding: utf-8 -*-
"""
Side Panel — 左侧面板内容区

根据 Activity Bar 的选择，显示不同的面板内容。
注意：资源管理器使用原有的 explorer_panel，不重复创建。

信号:
    panel_action(str): 面板内动作触发
"""

import os
import sys
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QTextEdit, QHBoxLayout, QComboBox, QCheckBox,
    QListWidget, QListWidgetItem, QSizePolicy,
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont, QPixmap, QPainter, QColor
from PyQt5.QtSvg import QSvgRenderer

sys.path.insert(0, os.path.dirname(__file__))
from theme import (
    BG_ROOT, BG_SURFACE, BG_SURFACE_HOVER, BG_PRIMARY,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_SUBTLE, BORDER_DEFAULT,
    LEMON_ORANGE, RADIUS_SM,
    FONT_SIZE_SM, FONT_MONO, icon_text_html,
)
from ui.design.tokens import Lemon


class SidePanel(QWidget):
    """左侧面板内容区

    信号:
        panel_action(str): 面板动作 ID
        search_requested(str): 搜索请求
        git_commit_requested(str): Git 提交请求
    """

    panel_action = pyqtSignal(str)
    search_requested = pyqtSignal(str)
    git_commit_requested = pyqtSignal(str)
    file_diff_requested = pyqtSignal(str)
    ai_commit_requested = pyqtSignal()
    branch_switch_requested = pyqtSignal(str)
    branch_create_requested = pyqtSignal(str)
    branch_delete_requested = pyqtSignal(str)
    stash_requested = pyqtSignal(str)
    stash_pop_requested = pyqtSignal()
    view_all_diff_requested = pyqtSignal()
    settings_saved = pyqtSignal(dict)
    stash_apply_requested = pyqtSignal(str)
    stash_drop_requested = pyqtSignal(str)
    git_push_requested = pyqtSignal()
    git_pull_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = "explorer"
        self._panels = {}
        self._git_manager = None
        self._plugin_manager = None
        self._init_ui()

    def _init_ui(self):
        self.setFixedWidth(300)
        self.setStyleSheet(f"""
            QWidget {{
                background: {BG_PRIMARY};
                border-right: 1px solid {BORDER_SUBTLE};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 面板标题栏
        self._title_bar = QFrame()
        self._title_bar.setFixedHeight(36)
        self._title_bar.setStyleSheet(f"""
            QFrame {{
                background: {BG_ROOT};
                border-bottom: 1px solid {BORDER_SUBTLE};
            }}
        """)
        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)

        self._title_label = QLabel("搜索")
        self._title_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {TEXT_PRIMARY};
                background: transparent;
            }}
        """)
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()
        layout.addWidget(self._title_bar)

        # 内容区域
        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        # 创建各面板（不包括资源管理器，因为已有 explorer_panel）
        self._panels["search"] = self._create_search_panel()
        self._panels["source_control"] = self._create_git_panel()
        self._panels["run_debug"] = self._create_run_debug_panel()
        self._panels["testing"] = self._create_testing_panel()
        self._panels["extensions"] = self._create_extensions_panel()
        self._panels["settings"] = self._create_settings_panel()

        # 默认活动是 explorer，侧面板应隐藏（由 explorer_panel 处理）
        self._show_panel("search")  # 预加载搜索面板
        self.hide()  # 初始隐藏，因为默认活动是 explorer

        layout.addWidget(self._content_widget, 1)

    def _create_search_panel(self):
        """搜索面板 - 集成编辑器查找功能"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索文件内容 (Ctrl+Shift+F)...")
        self._search_input.setStyleSheet(self._input_style())
        self._search_input.returnPressed.connect(self._on_search)
        layout.addWidget(self._search_input)

        self._replace_input = QLineEdit()
        self._replace_input.setPlaceholderText("替换为... (可选)")
        self._replace_input.setStyleSheet(self._input_style())
        layout.addWidget(self._replace_input)

        opts_layout = QHBoxLayout()
        self._case_check = QCheckBox("区分大小写")
        self._case_check.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self._regex_check = QCheckBox("使用正则")
        self._regex_check.setStyleSheet(f"color: {TEXT_SECONDARY};")
        opts_layout.addWidget(self._case_check)
        opts_layout.addWidget(self._regex_check)
        opts_layout.addStretch()
        layout.addLayout(opts_layout)

        search_btn = QPushButton("在工作区搜索")
        search_btn.setStyleSheet(self._primary_btn_style())
        search_btn.clicked.connect(self._on_search)
        layout.addWidget(search_btn)

        self._results_list = QTextEdit()
        self._results_list.setReadOnly(True)
        self._results_list.setPlaceholderText("搜索结果将显示在这里...")
        self._results_list.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_SURFACE};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                font-size: {FONT_SIZE_SM};
            }}
        """)
        layout.addWidget(self._results_list, 1)

        return widget

    def _on_search(self):
        """执行搜索"""
        query = self._search_input.text()
        if query:
            self.search_requested.emit(query)
            self._results_list.clear()
            self._results_list.append(f"搜索: '{query}' ... (正在搜索所有文件)")
            self._results_list.append("提示: 结果将显示在此处，同时支持在编辑器中查找 (Ctrl+F)")

    def _create_git_panel(self):
        """源码管理面板 - 集成 Git 管理器"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 分支信息
        self._branch_label = QLabel("当前分支: 未知")
        self._branch_label.setStyleSheet(f"color: {LEMON_ORANGE}; font-weight: bold;")
        layout.addWidget(self._branch_label)

        # 分支选择与切换
        branch_row = QHBoxLayout()
        self._branch_combo = QComboBox()
        self._branch_combo.setToolTip("选择分支并切换")
        self._branch_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 5px;
            }}
        """)
        self._branch_combo.activated.connect(self._on_branch_switched)
        self._branch_combo.setContextMenuPolicy(Qt.CustomContextMenu)
        self._branch_combo.customContextMenuRequested.connect(self._on_branch_context_menu)
        branch_row.addWidget(self._branch_combo, 1)

        branch_refresh_btn = QPushButton("刷新分支")
        branch_refresh_btn.setStyleSheet(self._secondary_btn_style())
        branch_refresh_btn.clicked.connect(self._refresh_branches)
        branch_row.addWidget(branch_refresh_btn)
        layout.addLayout(branch_row)

        # 新建分支
        create_row = QHBoxLayout()
        self._new_branch_input = QLineEdit()
        self._new_branch_input.setPlaceholderText("新分支名...")
        self._new_branch_input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 5px;
            }}
        """)
        create_row.addWidget(self._new_branch_input, 1)
        create_btn = QPushButton("创建")
        create_btn.setStyleSheet(self._primary_btn_style())
        create_btn.clicked.connect(self._on_branch_create)
        create_row.addWidget(create_btn)
        layout.addLayout(create_row)

        # 状态摘要
        self._status_label = QLabel("未初始化 Git")
        self._status_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(self._status_label)

        # 提交信息
        self._commit_input = QTextEdit()
        self._commit_input.setPlaceholderText("提交信息...")
        self._commit_input.setMaximumHeight(60)
        self._commit_input.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                font-size: {FONT_SIZE_SM};
            }}
        """)
        layout.addWidget(self._commit_input)

        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet(self._secondary_btn_style())
        refresh_btn.clicked.connect(self._refresh_git)
        btn_layout.addWidget(refresh_btn)

        commit_btn = QPushButton("提交")
        commit_btn.setStyleSheet(self._primary_btn_style())
        commit_btn.clicked.connect(self._on_commit)
        btn_layout.addWidget(commit_btn)
        layout.addLayout(btn_layout)

        # AI 生成提交信息按钮
        self._ai_commit_btn = QPushButton("AI 生成提交信息")
        self._ai_commit_btn.setToolTip("使用本地 Ollama 模型根据 diff 生成提交信息")
        self._ai_commit_btn.setStyleSheet(self._ai_btn_style())
        self._ai_commit_btn.clicked.connect(self._on_ai_commit)
        layout.addWidget(self._ai_commit_btn)

        # Stash 操作
        stash_layout = QHBoxLayout()
        self._stash_btn = QPushButton("暂存变更")
        self._stash_btn.setToolTip("git stash 暂存当前工作区变更")
        self._stash_btn.setStyleSheet(self._secondary_btn_style())
        self._stash_btn.clicked.connect(self._on_stash)
        stash_layout.addWidget(self._stash_btn)

        self._stash_pop_btn = QPushButton("恢复暂存")
        self._stash_pop_btn.setToolTip("git stash pop 恢复最近一次暂存")
        self._stash_pop_btn.setStyleSheet(self._secondary_btn_style())
        self._stash_pop_btn.clicked.connect(self._on_stash_pop)
        stash_layout.addWidget(self._stash_pop_btn)
        layout.addLayout(stash_layout)

        self._stash_untracked_check = QCheckBox("包含未追踪文件 (-u)")
        self._stash_untracked_check.setToolTip("暂存时一并保存未追踪的新文件")
        self._stash_untracked_check.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(self._stash_untracked_check)

        # 远程操作
        remote_layout = QHBoxLayout()
        self._push_btn = QPushButton("推送")
        self._push_btn.setToolTip("git push 推送当前分支到远程")
        self._push_btn.setStyleSheet(self._secondary_btn_style())
        self._push_btn.clicked.connect(lambda: self.git_push_requested.emit())
        remote_layout.addWidget(self._push_btn)

        self._pull_btn = QPushButton("拉取")
        self._pull_btn.setToolTip("git pull 从远程拉取合并")
        self._pull_btn.setStyleSheet(self._secondary_btn_style())
        self._pull_btn.clicked.connect(lambda: self.git_pull_requested.emit())
        remote_layout.addWidget(self._pull_btn)
        layout.addLayout(remote_layout)

        # 查看全部 Diff 按钮
        self._view_all_diff_btn = QPushButton("查看全部 Diff")
        self._view_all_diff_btn.setToolTip("对每个变更文件打开 HEAD vs 当前的对比视图")
        self._view_all_diff_btn.setStyleSheet(self._secondary_btn_style())
        self._view_all_diff_btn.clicked.connect(lambda: self.view_all_diff_requested.emit())
        layout.addWidget(self._view_all_diff_btn)

        # 更改列表（可点击查看 diff）
        changes_label = QLabel("更改列表 (双击查看 Diff)")
        changes_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        changes_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
        layout.addWidget(changes_label)

        from PyQt5.QtWidgets import QListWidget, QListWidgetItem
        self._changes_list = QListWidget()
        self._changes_list.setToolTip("双击变更文件查看 Diff")
        self._changes_list.setStyleSheet(f"""
            QListWidget {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                font-family: {FONT_MONO};
                font-size: 12px;
            }}
            QListWidget::item {{
                padding: 4px 8px;
                border-bottom: 1px solid {BORDER_SUBTLE};
            }}
            QListWidget::item:hover {{
                background: {BG_SURFACE_HOVER};
            }}
        """)
        self._changes_list.itemDoubleClicked.connect(self._on_change_clicked)
        layout.addWidget(self._changes_list, 1)

        # Stash 列表
        stash_label = QLabel("Stash 列表")
        stash_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        stash_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
        layout.addWidget(stash_label)

        self._stash_list = QListWidget()
        self._stash_list.setToolTip("git stash 暂存列表（双击应用，右键丢弃）")
        self._stash_list.setStyleSheet(f"""
            QListWidget {{
                background: {BG_SURFACE};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                font-family: {FONT_MONO};
                font-size: 11px;
                max-height: 90px;
            }}
            QListWidget::item {{
                padding: 3px 8px;
            }}
            QListWidget::item:hover {{
                background: {BG_SURFACE_HOVER};
            }}
        """)
        self._stash_list.itemDoubleClicked.connect(self._on_stash_double_clicked)
        self._stash_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._stash_list.customContextMenuRequested.connect(self._on_stash_context_menu)
        layout.addWidget(self._stash_list)

        return widget

    def _refresh_git(self):
        """刷新 Git 状态"""
        if self._git_manager:
            self._git_manager.refresh_status()
            branch = self._git_manager.branch or "未知"
            self._branch_label.setText(f"当前分支: {branch}")
            self._refresh_branches()
            
            summary = self._git_manager.get_summary()
            if summary:
                self._status_label.setText(
                    f"已修改: {summary.get('modified', 0)} | "
                    f"已新增: {summary.get('added', 0)} | "
                    f"未追踪: {summary.get('untracked', 0)} | "
                    f"冲突: {summary.get('conflicts', 0)}"
                )
            
            # 显示变更文件列表（可点击查看 diff）
            self._changes_list.clear()
            from PyQt5.QtWidgets import QListWidgetItem
            if summary and summary.get('is_repo'):
                status_map = self._git_manager._status_cache
                if not status_map:
                    self._changes_list.addItem("工作区干净，无变更")
                else:
                    for fpath, status in status_map.items():
                        icon = self._git_manager.get_status_icon(fpath)
                        item = QListWidgetItem(f"{icon}  {fpath}")
                        item.setToolTip(f"状态: {status or '已修改'}")
                        self._changes_list.addItem(item)
            else:
                self._changes_list.addItem("暂无变更")

            # 刷新 stash 列表
            self._refresh_stash_list()
        else:
            self._branch_label.setText("当前分支: (未初始化)")
            self._status_label.setText("请在项目目录中初始化 Git 仓库")
            if hasattr(self, '_stash_list'):
                self._stash_list.clear()

    def _refresh_stash_list(self):
        """刷新 stash 列表"""
        if not hasattr(self, '_stash_list'):
            return
        from PyQt5.QtWidgets import QListWidgetItem
        self._stash_list.clear()
        try:
            stashes = self._git_manager.stash_list() if self._git_manager else []
        except Exception:
            stashes = []
        if not stashes:
            self._stash_list.addItem("(无暂存)")
            return
        for s in stashes:
            item = QListWidgetItem(s[:60])
            item.setToolTip(s)
            # 解析 stash 引用 id 存入 item 数据
            stash_ref = self._git_manager._stash_ref(s) if self._git_manager else ""
            item.setData(Qt.UserRole, stash_ref)
            self._stash_list.addItem(item)

    def _on_stash_double_clicked(self, item):
        """双击 stash — 应用该 stash"""
        stash_ref = item.data(Qt.UserRole) if item else ""
        if stash_ref:
            self.stash_apply_requested.emit(stash_ref)

    def _on_stash_context_menu(self, pos):
        """stash 右键菜单 — 应用 / 丢弃"""
        from PyQt5.QtWidgets import QMenu
        item = self._stash_list.itemAt(pos)
        if not item:
            return
        stash_ref = item.data(Qt.UserRole) or ""
        if not stash_ref:
            return
        menu = QMenu(self._stash_list)
        apply_action = menu.addAction("应用该 stash")
        drop_action = menu.addAction("丢弃该 stash")
        chosen = menu.exec_(self._stash_list.mapToGlobal(pos))
        if chosen == apply_action:
            self.stash_apply_requested.emit(stash_ref)
        elif chosen == drop_action:
            self.stash_drop_requested.emit(stash_ref)

    def _on_change_clicked(self, item):
        """双击变更文件 — 请求查看 Diff"""
        if self._git_manager and self._git_manager.is_git_repo:
            # item 文本形如 "✎  src/main.py"，去掉状态图标
            text = item.text()
            if '  ' in text:
                rel_path = text.split('  ', 1)[1].strip()
            else:
                rel_path = text.strip()
            if rel_path and not rel_path.startswith(('工作区干净', '暂无')):
                self.file_diff_requested.emit(rel_path)

    def _on_commit(self):
        """执行提交"""
        msg = self._commit_input.toPlainText().strip()
        if msg:
            self.git_commit_requested.emit(msg)
            self._commit_input.clear()
        else:
            self._commit_input.setPlaceholderText("请输入提交信息...")

    def _on_ai_commit(self):
        """AI 生成提交信息 — 请求 main_window 调用本地模型"""
        if self._git_manager and self._git_manager.is_git_repo:
            self._ai_commit_btn.setText("生成中...")
            self._ai_commit_btn.setEnabled(False)
            self.ai_commit_requested.emit()
        else:
            self._ai_commit_btn.setText("AI 生成提交信息")
            self._ai_commit_btn.setEnabled(True)
            self._status_label.setText("请先在项目目录初始化 Git 仓库")

    def _refresh_branches(self):
        """刷新分支下拉框"""
        if not self._git_manager or not self._git_manager.is_git_repo:
            self._branch_combo.clear()
            return
        current = self._git_manager.branch
        branches = self._git_manager.list_branches()
        self._branch_combo.blockSignals(True)
        self._branch_combo.clear()
        self._branch_combo.addItems(branches)
        if current:
            idx = self._branch_combo.findText(current)
            if idx >= 0:
                self._branch_combo.setCurrentIndex(idx)
        self._branch_combo.blockSignals(False)

    def _on_branch_switched(self, index):
        """切换分支"""
        if not self._git_manager or not self._git_manager.is_git_repo:
            return
        name = self._branch_combo.itemText(index)
        current = self._git_manager.branch
        if name and name != current:
            self.branch_switch_requested.emit(name)

    def _on_branch_create(self):
        """创建新分支"""
        name = self._new_branch_input.text().strip()
        if not name:
            self._status_label.setText("请输入新分支名")
            return
        self._new_branch_input.clear()
        self.branch_create_requested.emit(name)

    def _on_branch_context_menu(self, pos):
        """分支下拉框右键菜单 — 删除非当前分支"""
        if not self._git_manager or not self._git_manager.is_git_repo:
            return
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self._branch_combo)
        del_action = menu.addAction("删除该分支")
        chosen = menu.exec_(self._branch_combo.mapToGlobal(pos))
        if chosen == del_action:
            name = self._branch_combo.currentText()
            if not name:
                return
            if name == self._git_manager.branch:
                self._status_label.setText("不能删除当前分支")
                return
            self.branch_delete_requested.emit(name)

    def _on_stash(self):
        """暂存工作区变更"""
        if self._git_manager and self._git_manager.is_git_repo:
            include_untracked = self._stash_untracked_check.isChecked() if hasattr(self, '_stash_untracked_check') else False
            self.stash_requested.emit("INCLUDE_UNTRACKED" if include_untracked else "")
        else:
            self._status_label.setText("请先初始化 Git 仓库")

    def _on_stash_pop(self):
        """恢复最近一次暂存"""
        if self._git_manager and self._git_manager.is_git_repo:
            self.stash_pop_requested.emit()
        else:
            self._status_label.setText("请先初始化 Git 仓库")

    def _create_run_debug_panel(self):
        """运行和调试面板"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        config_label = QLabel("运行配置")
        config_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        config_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
        layout.addWidget(config_label)

        config_combo = QComboBox()
        config_combo.addItems(["Python: main.py", "Python: test.py", "Node: server.js"])
        config_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 6px;
            }}
        """)
        layout.addWidget(config_combo)

        run_btn = QPushButton("运行")
        run_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Lemon.ACCENT_GREEN};
                color: #fff;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 10px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: {Lemon.ACCENT_GREEN};
            }}
        """)
        layout.addWidget(run_btn)

        debug_btn = QPushButton("调试")
        debug_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Lemon.ACCENT_BLUE};
                color: #fff;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 10px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: {Lemon.ACCENT_BLUE};
            }}
        """)
        layout.addWidget(debug_btn)

        vars_label = QLabel("变量")
        vars_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        vars_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
        layout.addWidget(vars_label)

        vars_list = QTextEdit()
        vars_list.setReadOnly(True)
        vars_list.setPlaceholderText("调试时显示变量")
        vars_list.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
            }}
        """)
        layout.addWidget(vars_list, 1)

        return widget

    def _create_testing_panel(self):
        """测试面板"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        run_tests_btn = QPushButton("运行所有测试")
        run_tests_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE};
                color: #000;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 10px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(run_tests_btn)

        results_label = QLabel("测试结果")
        results_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        results_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
        layout.addWidget(results_label)

        results = QTextEdit()
        results.setReadOnly(True)
        results.setPlaceholderText("运行测试以查看结果")
        results.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
            }}
        """)
        layout.addWidget(results, 1)

        return widget

    def _create_extensions_panel(self):
        """★ v3.92: 扩展面板 — 真正可用，展示已加载工具/技能 + 入口完整市场"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 顶部按钮行：刷新 + 打开完整市场
        top_btn_row = QHBoxLayout()
        top_btn_row.setSpacing(6)

        refresh_btn = QPushButton("刷新列表")
        refresh_btn.setStyleSheet(self._secondary_btn_style())
        refresh_btn.clicked.connect(self._refresh_extensions)
        top_btn_row.addWidget(refresh_btn)

        market_btn = QPushButton("📦 打开插件市场")
        market_btn.setStyleSheet(self._primary_btn_style())
        market_btn.setToolTip("打开完整插件市场（浏览/安装/卸载/启用禁用）")
        market_btn.clicked.connect(self._open_plugin_market_dialog)
        top_btn_row.addWidget(market_btn)
        layout.addLayout(top_btn_row)

        # 搜索框
        search = QLineEdit()
        search.setPlaceholderText("过滤已加载的工具 / 技能…")
        search.setStyleSheet(self._input_style())
        search.textChanged.connect(self._filter_extensions)
        self._extensions_search = search
        layout.addWidget(search)

        # 已加载 — 工具
        tools_label = QLabel("🛠 已加载工具 (Tools)")
        tools_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        tools_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
        layout.addWidget(tools_label)

        self._tools_list = QListWidget()
        self._tools_list.setSpacing(4)
        self._tools_list.setStyleSheet(f"""
            QListWidget {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                outline: none;
                padding: 4px;
            }}
            QListWidget::item {{
                background: transparent;
                border-radius: {RADIUS_SM};
            }}
            QListWidget::item:hover {{
                background: {BG_SURFACE_HOVER};
            }}
        """)
        self._tools_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self._tools_list, 1)

        # 已加载 — 技能
        skills_label = QLabel(icon_text_html("target", "已加载技能 (Skills)", color=TEXT_PRIMARY))
        skills_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        skills_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
        layout.addWidget(skills_label)

        self._skills_list = QTextEdit()
        self._skills_list.setReadOnly(True)
        self._skills_list.setStyleSheet(self._list_style())
        layout.addWidget(self._skills_list, 1)

        # 状态计数
        self._extensions_status = QLabel("")
        self._extensions_status.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        layout.addWidget(self._extensions_status)

        return widget

    def _list_style(self):
        """列表控件统一样式"""
        return f"""
            QTextEdit {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                font-size: {FONT_SIZE_SM};
                padding: 4px;
            }}
        """

    def _refresh_extensions(self):
        """★ v3.93: 刷新扩展列表 — 用 PluginManager.get_all_plugins() 渲染已加载插件 + 技能"""
        self._tools_list.clear()
        if not self._plugin_manager:
            item = QListWidgetItem("⚠️ 插件管理器未初始化")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self._tools_list.addItem(item)
            self._skills_list.setText("⚠️ 插件管理器未初始化")
            self._extensions_status.setText("")
            return
        plugins = []
        summary = ""
        try:
            # 真实方法：get_all_plugins() 返回 IPlugin 列表
            if hasattr(self._plugin_manager, "get_all_plugins"):
                plugins = self._plugin_manager.get_all_plugins() or []
        except Exception as e:
            self._tools_list.clear()
            item = QListWidgetItem(f"⚠️ 加载失败：{e}")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self._tools_list.addItem(item)
            return

        # 把插件转成 dict 列表方便渲染
        self._all_tools = []
        for p in plugins:
            try:
                self._all_tools.append({
                    "name": getattr(p, "name", str(p)),
                    "description": getattr(p, "description", "") or "",
                    "version": getattr(p, "version", "1.0"),
                    "icon": getattr(p, "icon", "") or "",
                })
            except Exception:
                pass

        # 技能从 summary 拿（如果可用）
        skills_count = 0
        try:
            if hasattr(self._plugin_manager, "get_summary"):
                skills_count = self._plugin_manager.get_summary().get("skills", {}).get("count", 0)
        except Exception:
            pass

        self._all_skills = [{"name": f"已注册技能 ({skills_count} 个)", "description": "由 load_builtin_skills() 注册"}]
        self._render_tools()
        self._render_skills()
        self._extensions_status.setText(f"共 {len(self._all_tools)} 个插件，{skills_count} 个技能 — 点上方按钮打开完整插件市场")

    def _render_tools(self):
        q = (self._extensions_search.text() if hasattr(self, "_extensions_search") else "").strip().lower()
        self._tools_list.clear()
        if not self._all_tools:
            item = QListWidgetItem("(暂无已加载插件 — 点击「打开插件市场」浏览内置/远程插件)")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self._tools_list.addItem(item)
            return
        for t in self._all_tools:
            name = t.get("name", "")
            desc = t.get("description", "")[:60]
            if q and q not in name.lower() and q not in desc.lower():
                continue
            widget = self._create_plugin_item_widget(t)
            item = QListWidgetItem(self._tools_list)
            item.setSizeHint(widget.sizeHint())
            self._tools_list.addItem(item)
            self._tools_list.setItemWidget(item, widget)

    def _create_plugin_item_widget(self, tool):
        """单个插件卡片：图标 + 名称/版本 + 描述"""
        name = tool.get("name", "")
        desc = tool.get("description", "")[:60]
        version = tool.get("version", "")
        icon_svg = tool.get("icon", "")

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(34, 34)
        icon_lbl.setScaledContents(True)
        pm = self._render_plugin_icon(icon_svg, name, 34)
        if pm:
            icon_lbl.setPixmap(pm)
        h.addWidget(icon_lbl)

        info = QVBoxLayout()
        info.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        name_lbl.setStyleSheet(f"color: {TEXT_PRIMARY};")
        title_row.addWidget(name_lbl)
        if version:
            ver_lbl = QLabel(f"v{version}")
            ver_lbl.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
            title_row.addWidget(ver_lbl)
        title_row.addStretch()
        info.addLayout(title_row)

        if desc:
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
            info.addWidget(desc_lbl)
        h.addLayout(info, 1)

        return row

    def _render_plugin_icon(self, svg_text, name, size=34):
        """把插件返回的 SVG 渲染成 QPixmap；没有 SVG 时用名称首字母兜底。"""
        color = LEMON_ORANGE
        if svg_text and isinstance(svg_text, str) and "<svg" in svg_text:
            try:
                renderer = QSvgRenderer(bytearray(svg_text.encode("utf-8")))
                pm = QPixmap(size, size)
                pm.fill(Qt.transparent)
                painter = QPainter(pm)
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setPen(QColor(color))
                renderer.render(painter)
                painter.end()
                if pm.width() > 0 and pm.height() > 0:
                    return pm
            except Exception:
                pass
        # 兜底：首字母圆形图标
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, size, size)
        painter.setPen(QColor("#000"))
        font = QFont("Microsoft YaHei", 12, QFont.Bold)
        painter.setFont(font)
        initial = (name[0] if name else "?").upper()
        painter.drawText(pm.rect(), Qt.AlignCenter, initial)
        painter.end()
        return pm

    def _render_skills(self):
        # 技能不再做复杂渲染（PluginManager 没有 list_skills）；显示一行摘要
        q = (self._extensions_search.text() if hasattr(self, "_extensions_search") else "").strip().lower()
        lines = []
        for s in self._all_skills:
            name = s.get("name", "")
            desc = s.get("description", "")
            if q and q not in name.lower():
                continue
            lines.append(f"  • {name} — {desc}")
        self._skills_list.setText("\n".join(lines))

    def _filter_extensions(self, _text):
        """搜索框过滤"""
        if hasattr(self, "_all_tools"):
            self._render_tools()
            self._render_skills()

    def _open_plugin_market_dialog(self):
        """★ v3.95: 弹起 Trae 式插件市场浏览器（卡片流 + 分类 + 搜索 + 一键安装）"""
        try:
            from standard_mode.ui.plugin_market_browser import PluginMarketBrowser
            from PyQt5.QtWidgets import QDialog, QVBoxLayout
            from shared.plugin_market import PluginMarket

            dlg = QDialog(self)
            dlg.setWindowTitle("🧩 Lemon Code 插件市场")
            dlg.resize(980, 700)
            v = QVBoxLayout(dlg)
            v.setContentsMargins(0, 0, 0, 0)
            # 传入独立 PluginMarket（含内置 + 远程 + 离线兜底 24+ 插件）
            market = PluginMarket()
            panel = PluginMarketBrowser(market=market, plugin_manager=self._plugin_manager, parent=dlg)
            panel.plugin_installed.connect(self._refresh_extensions)
            panel.plugin_uninstalled.connect(self._refresh_extensions)
            v.addWidget(panel)
            dlg.exec_()
        except Exception as e:
            # fallback: 在控制台 / 输出区提示
            if hasattr(self, "_extensions_status"):
                self._extensions_status.setText(f"⚠️ 无法打开插件市场：{e}")

    def _create_settings_panel(self):
        """设置面板 — AI 引擎与提交信息配置"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("设置")
        title.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        title.setStyleSheet(f"color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        def section_label(text):
            lb = QLabel(text)
            lb.setStyleSheet(f"color: {LEMON_ORANGE}; font-weight: bold; margin-top: 4px;")
            return lb

        def make_combo(items, tooltip):
            cb = QComboBox()
            cb.addItems(items)
            cb.setToolTip(tooltip)
            cb.setStyleSheet(f"""
                QComboBox {{
                    background: {BG_SURFACE};
                    color: {TEXT_PRIMARY};
                    border: 1px solid {BORDER_DEFAULT};
                    border-radius: {RADIUS_SM};
                    padding: 5px;
                }}
            """)
            return cb

        def make_input(placeholder, tooltip):
            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setToolTip(tooltip)
            inp.setStyleSheet(f"""
                QLineEdit {{
                    background: {BG_SURFACE};
                    color: {TEXT_PRIMARY};
                    border: 1px solid {BORDER_DEFAULT};
                    border-radius: {RADIUS_SM};
                    padding: 5px;
                }}
            """)
            return inp

        # ---- AI 引擎设置 ----
        layout.addWidget(section_label("AI 引擎"))

        layout.addWidget(QLabel("提交信息生成引擎"))
        self._settings_engine_combo = make_combo(
            ["本地 Ollama", "DeepSeek 云端"],
            "AI 生成提交信息使用的后端")
        layout.addWidget(self._settings_engine_combo)

        layout.addWidget(QLabel("本地 Ollama 模型"))
        self._settings_ollama_model = make_input(
            "qwen3.5:4b",
            "本地 Ollama 模型名称")
        self._settings_ollama_model.setText("qwen3.5:4b")
        layout.addWidget(self._settings_ollama_model)

        layout.addWidget(QLabel("Ollama 地址"))
        self._settings_ollama_url = make_input(
            "http://127.0.0.1:11434",
            "Ollama 服务地址")
        self._settings_ollama_url.setText("http://127.0.0.1:11434")
        layout.addWidget(self._settings_ollama_url)

        layout.addWidget(QLabel("DeepSeek API Key"))
        self._settings_deepseek_key = make_input(
            "sk-... 或留空读取 ~/.deepseek_key",
            "DeepSeek 密钥（留空则读取 ~/.deepseek_key）")
        layout.addWidget(self._settings_deepseek_key)

        layout.addWidget(QLabel("DeepSeek 模型"))
        self._settings_deepseek_model = make_input(
            "deepseek-chat",
            "DeepSeek 模型名称")
        self._settings_deepseek_model.setText("deepseek-chat")
        layout.addWidget(self._settings_deepseek_model)

        # ---- 保存按钮 ----
        save_btn = QPushButton("保存设置")
        save_btn.setStyleSheet(self._primary_btn_style())
        save_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(save_btn)

        self._settings_status = QLabel("")
        self._settings_status.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(self._settings_status)

        layout.addStretch()
        return widget

    def _on_save_settings(self):
        """保存设置 — 发送设置到 main_window"""
        from PyQt5.QtWidgets import QMessageBox
        config = {
            "engine": self._settings_engine_combo.currentIndex(),  # 0=ollama, 1=deepseek
            "ollama_model": self._settings_ollama_model.text().strip(),
            "ollama_url": self._settings_ollama_url.text().strip(),
            "deepseek_key": self._settings_deepseek_key.text().strip(),
            "deepseek_model": self._settings_deepseek_model.text().strip(),
        }
        self.settings_saved.emit(config)
        self._settings_status.setText("设置已保存 ✓")
        # 可考虑用 QTimer 清空提示，这里保留简单实现

    def _load_settings_from_manager(self):
        """从 SettingsManager 回填设置面板当前值"""
        try:
            from core.settings_manager import get_settings_manager
            sm = get_settings_manager()
            gc = sm.get("ai.git_commit", {}) or {}
            engine = gc.get("engine", "ollama")
            # 引擎下拉框
            if hasattr(self, '_settings_engine_combo'):
                idx = 0 if engine == "ollama" else 1
                self._settings_engine_combo.setCurrentIndex(idx)
            # 模型 / URL / deepseek 模型
            if hasattr(self, '_settings_ollama_model') and gc.get("ollama_model"):
                self._settings_ollama_model.setText(gc["ollama_model"])
            if hasattr(self, '_settings_ollama_url') and gc.get("ollama_url"):
                self._settings_ollama_url.setText(gc["ollama_url"])
            if hasattr(self, '_settings_deepseek_model') and gc.get("deepseek_model"):
                self._settings_deepseek_model.setText(gc["deepseek_model"])
            self._settings_status.setText("已加载当前配置")
        except Exception:
            # 无法访问 SettingsManager 时静默忽略，保留默认值
            pass

    def _show_panel(self, panel_id):
        """显示指定面板"""
        # 清空当前内容
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().hide()

        # 显示设置面板时回填当前已保存的值
        if panel_id == "settings":
            self._load_settings_from_manager()

        # 显示新面板
        panel = self._panels.get(panel_id)
        if panel:
            self._content_layout.addWidget(panel)
            panel.show()

        # 更新标题
        titles = {
            "search": "搜索",
            "source_control": "源码管理",
            "run_debug": "运行和调试",
            "testing": "测试",
            "extensions": "扩展",
            "settings": "设置",
        }
        self._title_label.setText(titles.get(panel_id, panel_id))

    def set_activity(self, activity_id):
        """切换活动"""
        # 如果是资源管理器，不显示侧面板（由 explorer_panel 处理）
        if activity_id == "explorer":
            self.hide()
            return

        self.show()
        self._current = activity_id
        self._show_panel(activity_id)

        # 自动刷新对应面板数据
        if activity_id == "source_control":
            self._refresh_git()
        elif activity_id == "extensions":
            self._refresh_extensions()

    def set_git_manager(self, manager):
        """注入 Git 管理器"""
        self._git_manager = manager

    def set_plugin_manager(self, manager):
        """注入插件管理器"""
        self._plugin_manager = manager

    # ============ 样式辅助方法 ============
    def _input_style(self):
        return f"""
            QLineEdit {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 6px 10px;
            }}
        """

    def _primary_btn_style(self):
        return f"""
            QPushButton {{
                background: {LEMON_ORANGE};
                color: #000;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 8px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Lemon.BRAND_ORANGE};
            }}
        """

    def _secondary_btn_style(self):
        return f"""
            QPushButton {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 8px;
            }}
            QPushButton:hover {{
                background: {BG_SURFACE_HOVER};
                border-color: {LEMON_ORANGE};
            }}
        """

    def _ai_btn_style(self):
        return f"""
            QPushButton {{
                background: #2d6a4f;
                color: #fff;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 8px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #1b4332;
            }}
            QPushButton:disabled {{
                background: #495057;
                color: #adb5bd;
            }}
        """
