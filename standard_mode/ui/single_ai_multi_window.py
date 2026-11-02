# -*- coding: utf-8 -*-
"""
Lemon Code Agent — 单AI多窗口模式
===================================
设计要点：
- 4-5个任务窗口（资源管理器+代码编辑器合一）
- 滑轨可扩展更多窗口
- 下边栏连接当前选中的任务
- 同一AI驱动，任务相互隔离
- 星空背景+流星效果（风格统一）
- 右侧输出面板显示AI响应
- Lemon Code Logo
"""

from typing import Dict, List, Optional
from datetime import datetime
import threading
import random
import requests
import os
import sys

# ★ v3.48: 统一 AI 调用入口
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.engine_manager import get_engine_manager, chat as engine_chat

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QStackedWidget, QTextEdit, QLineEdit,
    QSplitter, QSizePolicy, QSpacerItem, QFileDialog, QTreeWidget,
    QTreeWidgetItem, QTabWidget, QPlainTextEdit, QComboBox,
    QProgressBar
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush, QLinearGradient, QIcon

from ui.theme import (
    BG_DARK, BG_PANEL, BG_SURFACE, BG_SURFACE_HOVER,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    LEMON_ORANGE, LEMON_YELLOW, LEMON_GOLD,
    SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR,
    BORDER_RADIUS, FONT_FAMILY, BORDER_DEFAULT, BORDER_FOCUS, BORDER_STRONG,
    RADIUS_SM, RADIUS_MD, RADIUS_LG
)
import os as _os
from ui.design.tokens import Lemon


# ============================================================================
# 星空背景组件（复用于所有模式）
# ============================================================================

class StarryBackground(QWidget):
    """星空背景 + 流星效果（与主页面一致的3D星空效果）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stars = []
        self.meteors = []
        self._generate_stars()
        self._start_animations()

    def _generate_stars(self):
        for _ in range(150):
            x = random.randint(0, 1000)
            y = random.randint(0, 800)
            size = random.uniform(0.5, 2.5)
            brightness = random.uniform(0.2, 1.0)
            self.stars.append((x, y, size, brightness))

    def _start_animations(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_meteors)
        self.timer.start(50)

    def _update_meteors(self):
        if len(self.meteors) < 3 and random.random() < 0.04:
            x = random.randint(0, 500)
            y = random.randint(0, 100)
            speed = random.uniform(4, 10)
            length = random.randint(40, 100)
            self.meteors.append([x, y, speed, length])

        new_meteors = []
        for m in self.meteors:
            m[0] += m[2]
            m[1] += m[2]
            if m[0] < 1000 and m[1] < 800:
                new_meteors.append(m)
        self.meteors = new_meteors
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor("#0a0a1a"))
        gradient.setColorAt(0.5, QColor("{Lemon.DARK_MID_1}"))
        gradient.setColorAt(1, QColor("{Lemon.DARK_BG_1}"))
        painter.fillRect(self.rect(), gradient)

        for x, y, size, brightness in self.stars:
            sx = int(x * self.width() / 1000)
            sy = int(y * self.height() / 800)
            alpha = int(brightness * 255)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, alpha)))
            r = max(1, int(size * 2))
            painter.drawEllipse(sx, sy, r, r)

        for x, y, speed, length in self.meteors:
            sx = int(x * self.width() / 1000)
            sy = int(y * self.height() / 800)
            for i in range(length):
                alpha = 200 - int(i * 200 / length)
                if alpha <= 0:
                    continue
                pen = QPen(QColor(255, 255, 255, alpha), 1)
                painter.setPen(pen)
                painter.drawLine(sx - i, sy - i, sx - i - 1, sy - i - 1)


# ============================================================================
# 单AI多窗口面板（主面板）
# ============================================================================

class SingleAIMultiWindowPanel(QWidget):
    """
    单AI多窗口模式面板
    
    布局：
    - 左侧：任务窗口区（4-5个可切换的任务窗口，支持后台运行）
    - 右侧：AI输出面板（显示当前任务的AI响应）
    - 底部：任务输入栏 + 后台任务队列指示
    - 星空背景全覆盖
    
    关键功能：切换任务时，前一个任务的AI自动转到后台继续运行
    """

    # 信号
    task_changed = pyqtSignal(str, str)  # task_id, task_name
    command_sent = pyqtSignal(str, str)  # task_id, command

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tasks: Dict[str, dict] = {}
        self.current_task_id = "task-1"
        self._task_counter = 0
        self._background_queue: List[dict] = []  # 后台任务队列
        self._background_timer = None
        self._init_ui()
        self._create_default_tasks()
        self._start_background_processor()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ========== 星空背景容器 ==========
        bg = StarryBackground()
        bg_layout = QVBoxLayout(bg)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        bg_layout.setSpacing(0)

        # ========== 标题栏 + Logo ==========
        title_bar = QFrame()
        title_bar.setFixedHeight(52)
        title_bar.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {BG_DARK}, stop:0.5 {BG_SURFACE}, stop:1 {BG_DARK});
                border-bottom: 1px solid {BORDER_DEFAULT};
            }}
        """)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(16, 6, 16, 6)
        title_layout.setSpacing(12)

        # Logo
        logo_label = QLabel("🍋 Lemon Code")
        logo_label.setFont(QFont(FONT_FAMILY, 16, QFont.Bold))
        logo_label.setStyleSheet(f"color: {LEMON_ORANGE};")
        title_layout.addWidget(logo_label)

        # 模式标签
        mode_label = QLabel("单AI多窗口模式")
        mode_label.setFont(QFont(FONT_FAMILY, 11))
        mode_label.setStyleSheet(f"color: {TEXT_TERTIARY};")
        title_layout.addWidget(mode_label)

        title_layout.addStretch()

        # 功能按钮
        for name, icon in [("新建任务", "+"), ("清空全部", "✕"), ("导入文件", "📂")]:
            btn = QPushButton(f"{icon} {name}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {BG_SURFACE};
                    color: {TEXT_SECONDARY};
                    border: 1px solid {BORDER_DEFAULT};
                    border-radius: {RADIUS_SM};
                    padding: 5px 12px;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    border-color: {LEMON_ORANGE};
                    color: {LEMON_ORANGE};
                }}
            """)
            if name == "新建任务":
                btn.clicked.connect(self._add_new_task)
            elif name == "清空全部":
                btn.clicked.connect(self._clear_all_tasks)
            else:
                btn.clicked.connect(self._import_file)
            title_layout.addWidget(btn)

        bg_layout.addWidget(title_bar)

        # ========== 主内容区：文件资源管理器 + 任务区 + 输出面板 ==========
        content_splitter = QSplitter(Qt.Horizontal)
        content_splitter.setHandleWidth(1)
        content_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {BORDER_DEFAULT};
            }}
            QSplitter::handle:hover {{
                background: {LEMON_ORANGE};
            }}
        """)

        # --- 最左侧：文件资源管理器 ---
        self.file_explorer = self._create_file_explorer()
        content_splitter.addWidget(self.file_explorer)

        # --- 左侧：任务窗口区 ---
        left_panel = self._create_left_panel()
        content_splitter.addWidget(left_panel)

        # --- 右侧：AI输出面板 ---
        right_panel = self._create_right_panel()
        content_splitter.addWidget(right_panel)

        content_splitter.setSizes([220, 450, 400])
        bg_layout.addWidget(content_splitter, stretch=1)

        # ========== 底部：任务输入栏 ==========
        self.input_bar = self._create_input_bar()
        bg_layout.addWidget(self.input_bar)

        layout.addWidget(bg, stretch=1)

    def _create_left_panel(self):
        """创建左侧任务窗口区"""
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border-right: 1px solid {BORDER_DEFAULT};
            }}
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 任务标签页
        self.task_tabs = QTabWidget()
        self.task_tabs.setTabsClosable(True)
        self.task_tabs.setMovable(True)
        self.task_tabs.tabCloseRequested.connect(self._close_task)
        self.task_tabs.currentChanged.connect(self._on_tab_changed)
        self.task_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
                background: {BG_DARK};
            }}
            QTabBar::tab {{
                background: {BG_PANEL};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT};
                border-bottom: none;
                border-top-left-radius: {RADIUS_SM};
                border-top-right-radius: {RADIUS_SM};
                padding: 6px 14px;
                margin-right: 2px;
                font-size: 11px;
                min-width: 80px;
            }}
            QTabBar::tab:selected {{
                background: {BG_DARK};
                color: {LEMON_ORANGE};
                border-bottom: 2px solid {LEMON_ORANGE};
                font-weight: bold;
            }}
            QTabBar::tab:hover {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
            }}
            QTabBar::close-button {{
                image: none;
                background: transparent;
                border-radius: 8px;
            }}
            QTabBar::close-button:hover {{
                background: {ERROR_COLOR};
            }}
        """)
        layout.addWidget(self.task_tabs, stretch=1)

        return panel

    def _create_file_explorer(self):
        """创建文件资源管理器面板"""
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background: rgba(0, 0, 0, 0.5);
                border-right: 1px solid {BORDER_DEFAULT};
            }}
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题
        header = QFrame()
        header.setStyleSheet(f"background: {BG_PANEL};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)

        title = QLabel("📁 项目文件")
        title.setFont(QFont(FONT_FAMILY, 12, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE};")
        header_layout.addWidget(title)
        header_layout.addStretch()

        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(22, 22)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE}; color: {TEXT_SECONDARY};
                border: none; border-radius: {RADIUS_SM}; font-size: 11px;
            }}
            QPushButton:hover {{ background: {BG_SURFACE_HOVER}; color: {LEMON_ORANGE}; }}
        """)
        refresh_btn.clicked.connect(self._refresh_file_explorer)
        header_layout.addWidget(refresh_btn)
        layout.addWidget(header)

        # 文件树
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setIndentation(14)
        self.file_tree.setStyleSheet(f"""
            QTreeWidget {{
                background: transparent;
                color: {TEXT_SECONDARY};
                border: none;
                font-size: 10px;
            }}
            QTreeWidget::item {{
                padding: 3px 6px;
            }}
            QTreeWidget::item:selected {{
                background: {BG_SURFACE};
                color: {LEMON_ORANGE};
            }}
            QTreeWidget::item:hover {{
                background: {BG_SURFACE_HOVER};
            }}
        """)
        self.file_tree.itemClicked.connect(self._on_file_tree_item_clicked)
        self._refresh_file_explorer()
        layout.addWidget(self.file_tree, stretch=1)

        return panel

    def _refresh_file_explorer(self):
        """刷新文件资源管理器"""
        self.file_tree.clear()
        project_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        ignore_dirs = {'.venv', '.git', '__pycache__', 'node_modules', '.mimo_snapshots',
                       'competition_archive', '.mimo', 'dist', 'build'}
        ignore_ext = {'.pyc', '.pyo', '.pyd'}

        def _add_dir(parent, dir_path, dir_name, depth=0):
            if depth > 2 or dir_name in ignore_dirs:
                return
            folder = QTreeWidgetItem(parent)
            folder.setText(0, f"📁 {dir_name}")
            folder.setData(0, Qt.UserRole, _os.path.join(dir_path, dir_name))
            try:
                for entry in sorted(_os.listdir(_os.path.join(dir_path, dir_name))):
                    fp = _os.path.join(dir_path, dir_name, entry)
                    if _os.path.isdir(fp) and not entry.startswith('.') and entry not in ignore_dirs:
                        _add_dir(folder, _os.path.join(dir_path, dir_name), entry, depth + 1)
                    elif _os.path.isfile(fp) and not entry.startswith('.'):
                        _, ext = _os.path.splitext(entry)
                        if ext not in ignore_ext:
                            fi = QTreeWidgetItem(folder)
                            fi.setText(0, f"📄 {entry}")
                            fi.setData(0, Qt.UserRole, fp)
            except PermissionError:
                pass

        root = QTreeWidgetItem(self.file_tree)
        root.setText(0, f"📁 {_os.path.basename(project_root)}")
        root.setData(0, Qt.UserRole, project_root)
        try:
            for entry in sorted(_os.listdir(project_root)):
                if entry.startswith('.') or entry in ignore_dirs:
                    continue
                fp = _os.path.join(project_root, entry)
                if _os.path.isdir(fp):
                    _add_dir(root, project_root, entry, 1)
                elif _os.path.isfile(fp):
                    _, ext = _os.path.splitext(entry)
                    if ext not in ignore_ext:
                        fi = QTreeWidgetItem(root)
                        fi.setText(0, f"📄 {entry}")
                        fi.setData(0, Qt.UserRole, fp)
        except PermissionError:
            pass
        self.file_tree.expandAll()

    def _on_file_tree_item_clicked(self, item, col):
        data = item.data(0, Qt.UserRole)
        if data and _os.path.isfile(str(data)):
            # 在当前任务中打开文件
            task_id = self.current_task_id
            task = self.tasks.get(task_id)
            if task:
                try:
                    with open(data, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    task["page"]._code_editor.setPlainText(content)
                    file_name = _os.path.basename(data)
                    # 添加到文件列表
                    exists = False
                    for i in range(task["page"]._file_tree.topLevelItemCount()):
                        if task["page"]._file_tree.topLevelItem(i).text(0) == file_name:
                            exists = True
                            break
                    if not exists:
                        item = QTreeWidgetItem(task["page"]._file_tree)
                        item.setText(0, file_name)
                        item.setText(1, f"{_os.path.getsize(data) / 1024:.1f} KB")
                        item.setText(2, "已打开")
                    self.output_area.append(f"[系统] 已打开文件: {file_name}")
                except Exception as e:
                    self.output_area.append(f"[系统] 无法读取文件: {e}")

    def _create_right_panel(self):
        """创建右侧AI输出面板"""
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background: transparent;
            }}
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 标题
        header = QHBoxLayout()
        title = QLabel("📡 AI 输出")
        title.setFont(QFont(FONT_FAMILY, 13, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE};")
        header.addWidget(title)
        header.addStretch()

        self.output_status = QLabel("就绪")
        self.output_status.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 10px;")
        header.addWidget(self.output_status)
        layout.addLayout(header)

        # 输出区域（带星空背景）
        output_bg = StarryBackground()
        output_bg_layout = QVBoxLayout(output_bg)
        output_bg_layout.setContentsMargins(4, 4, 4, 4)

        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(0, 0, 0, 0.6);
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
                padding: 10px;
                font-family: {FONT_FAMILY};
                font-size: 12px;
                line-height: 1.5;
            }}
        """)
        self.output_area.setPlaceholderText("选择左侧任务窗口，输入命令后AI响应将显示在这里...")
        output_bg_layout.addWidget(self.output_area)
        layout.addWidget(output_bg, stretch=1)

        return panel

    def _create_input_bar(self):
        """创建底部输入栏"""
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"""
            QFrame {{
                background: {BG_PANEL};
                border-top: 1px solid {BORDER_DEFAULT};
            }}
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        # 当前任务显示
        self.task_label = QLabel("当前任务: 任务1")
        self.task_label.setFont(QFont(FONT_FAMILY, 11, QFont.Bold))
        self.task_label.setStyleSheet(f"color: {LEMON_ORANGE}; min-width: 120px;")
        layout.addWidget(self.task_label)

        # 后台任务指示器
        self.bg_indicator = QLabel("")
        self.bg_indicator.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px; min-width: 120px;")
        layout.addWidget(self.bg_indicator)

        # 后台任务进度条
        self.bg_progress = QProgressBar()
        self.bg_progress.setFixedHeight(3)
        self.bg_progress.setMaximumWidth(100)
        self.bg_progress.setMaximum(100)
        self.bg_progress.setValue(0)
        self.bg_progress.setVisible(False)
        self.bg_progress.setStyleSheet(f"""
            QProgressBar {{
                background: {BG_DARK};
                border: none;
                border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background: {LEMON_YELLOW};
                border-radius: 1px;
            }}
        """)
        layout.addWidget(self.bg_progress)

        # 模型选择
        self.model_combo = QComboBox()
        self.model_combo.addItems(["qwen3.5:4b", "qwen3.5:9b", "deepseek-r1:8b"])
        self.model_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 4px 8px;
                font-size: 10px;
                min-width: 110px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                selection-background-color: {BG_SURFACE};
            }}
        """)
        layout.addWidget(self.model_combo)

        # 输入框
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入命令到当前任务（支持自然语言）...")
        self.input_field.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
                padding: 8px 14px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {LEMON_ORANGE};
            }}
        """)
        self.input_field.returnPressed.connect(self._on_send)
        layout.addWidget(self.input_field, stretch=1)

        # 发送按钮
        send_btn = QPushButton("发送")
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE};
                color: #000;
                border: none;
                border-radius: {RADIUS_MD};
                padding: 8px 20px;
                font-weight: bold;
                font-size: 13px;
                min-width: 70px;
            }}
            QPushButton:hover {{
                background: {LEMON_YELLOW};
            }}
        """)
        send_btn.clicked.connect(self._on_send)
        layout.addWidget(send_btn)

        return bar

    def _create_task_page(self, task_id: str, task_name: str) -> QWidget:
        """创建单个任务页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 任务信息栏
        info_bar = QHBoxLayout()
        status_dot = QLabel("●")
        status_dot.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 10px;")
        info_bar.addWidget(status_dot)

        status_text = QLabel("空闲")
        status_text.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        info_bar.addWidget(status_text)
        info_bar.addStretch()

        # 文件树
        add_file_btn = QPushButton("+ 添加文件")
        add_file_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {LEMON_ORANGE};
                border: 1px solid {LEMON_ORANGE};
                border-radius: {RADIUS_SM};
                padding: 3px 8px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background: {LEMON_ORANGE};
                color: #000;
            }}
        """)
        add_file_btn.clicked.connect(lambda: self._add_file_to_task(task_id))
        info_bar.addWidget(add_file_btn)
        layout.addLayout(info_bar)

        # 文件列表
        file_tree = QTreeWidget()
        file_tree.setHeaderLabels(["文件", "大小", "状态"])
        file_tree.setColumnWidth(0, 200)
        file_tree.setColumnWidth(1, 80)
        file_tree.setColumnWidth(2, 80)
        file_tree.setStyleSheet(f"""
            QTreeWidget {{
                background: {BG_DARK};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                font-size: 11px;
            }}
            QTreeWidget::item {{
                padding: 4px 6px;
            }}
            QTreeWidget::item:selected {{
                background: {BG_SURFACE};
                color: {LEMON_ORANGE};
            }}
            QTreeWidget::item:hover {{
                background: {BG_SURFACE_HOVER};
            }}
            QHeaderView::section {{
                background: {BG_PANEL};
                color: {TEXT_TERTIARY};
                border: none;
                border-bottom: 1px solid {BORDER_DEFAULT};
                padding: 4px 6px;
                font-size: 10px;
            }}
        """)
        file_tree.setMaximumHeight(150)
        layout.addWidget(file_tree)

        # 代码编辑器
        code_label = QLabel("📝 代码编辑器")
        code_label.setStyleSheet(f"color: {LEMON_ORANGE}; font-size: 11px; font-weight: bold;")
        layout.addWidget(code_label)

        code_editor = QPlainTextEdit()
        code_editor.setPlaceholderText(f"# {task_name} - 在此输入或查看代码...")
        code_editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 10px;
                font-family: "Consolas", "Cascadia Code", monospace;
                font-size: 12px;
                line-height: 1.5;
            }}
        """)
        layout.addWidget(code_editor, stretch=1)

        # 保存引用
        page._status_dot = status_dot
        page._status_text = status_text
        page._file_tree = file_tree
        page._code_editor = code_editor

        return page

    def _create_default_tasks(self):
        """创建默认任务"""
        default_tasks = [
            ("task-1", "主任务", ["main.py", "config.py", "utils.py"]),
            ("task-2", "数据分析", ["data_analysis.py", "report.md"]),
            ("task-3", "API开发", ["api_server.py", "models.py", "routes.py"]),
            ("task-4", "前端界面", ["index.html", "style.css", "app.js"]),
        ]
        for task_id, task_name, files in default_tasks:
            self._add_task(task_id, task_name, files)

        self.task_tabs.setCurrentIndex(0)

    def _add_task(self, task_id: str, task_name: str, files: list = None):
        """添加任务"""
        page = self._create_task_page(task_id, task_name)
        self.task_tabs.addTab(page, f"  {task_name}  ")

        # 添加默认文件
        if files:
            for f in files:
                item = QTreeWidgetItem(page._file_tree)
                item.setText(0, f)
                item.setText(1, "1.2 KB")
                item.setText(2, "就绪")

        self.tasks[task_id] = {
            "name": task_name,
            "page": page,
            "files": files or [],
            "status": "空闲",
            "history": []
        }

    def _add_new_task(self):
        """添加新任务"""
        self._task_counter += 1
        task_id = f"task-{len(self.tasks) + self._task_counter + 1}"
        task_name = f"新任务{len(self.tasks) + 1}"
        self._add_task(task_id, task_name)
        self.task_tabs.setCurrentIndex(self.task_tabs.count() - 1)

    def _close_task(self, index):
        """关闭任务"""
        if self.task_tabs.count() <= 1:
            return
        task_id = list(self.tasks.keys())[index]
        self.task_tabs.removeTab(index)
        del self.tasks[task_id]

    def _on_tab_changed(self, index):
        """切换任务标签页 — 前一个任务AI转到后台继续运行"""
        if index < 0 or index >= len(self.tasks):
            return

        old_task_id = self.current_task_id
        task_id = list(self.tasks.keys())[index]

        # 旧任务如果正在运行，转为后台运行
        if old_task_id != task_id:
            old_task = self.tasks.get(old_task_id)
            if old_task and old_task.get("status") == "运行中":
                old_task["status"] = "后台运行中"
                old_task["page"]._status_dot.setStyleSheet(f"color: {LEMON_YELLOW}; font-size: 10px;")
                old_task["page"]._status_text.setText("后台运行中")
                old_task["page"]._status_text.setStyleSheet(f"color: {LEMON_YELLOW}; font-size: 11px;")
                self._output_to_task_log(old_task_id, f"[系统] 任务已转到后台继续运行...")

        self.current_task_id = task_id
        task = self.tasks[task_id]
        self.task_label.setText(f"当前任务: {task['name']}")
        self.input_field.setPlaceholderText(f"输入命令到 {task['name']}...")
        self._update_background_indicator()
        self.task_changed.emit(task_id, task['name'])

    def _start_background_processor(self):
        """启动后台任务处理器"""
        self._background_timer = QTimer(self)
        self._background_timer.timeout.connect(self._process_background_queue)
        self._background_timer.start(1000)  # 每秒检查一次

    def _process_background_queue(self):
        """处理后台任务队列"""
        if not self._background_queue:
            return

        # 处理队列中的第一个任务
        item = self._background_queue[0]
        task_id = item["task_id"]
        task = self.tasks.get(task_id)
        if not task:
            self._background_queue.pop(0)
            return

        if task["status"] == "后台运行中":
            # 模拟后台AI处理
            if "bg_progress" not in item:
                item["bg_progress"] = 0
            item["bg_progress"] += 10

            if item["bg_progress"] >= 100:
                # 后台任务完成
                task["status"] = "完成"
                task["page"]._status_dot.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 10px;")
                task["page"]._status_text.setText("完成")
                task["page"]._status_text.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 11px;")
                self._output_to_task_log(task_id, f"[系统] 后台任务处理完成！")
                self._background_queue.pop(0)
                self._update_background_indicator()
            else:
                self._output_to_task_log(task_id, f"[后台] 处理进度: {item['bg_progress']}%")

        self._update_background_indicator()

    def _output_to_task_log(self, task_id: str, message: str):
        """输出到指定任务的日志"""
        task = self.tasks.get(task_id)
        if task and task_id == self.current_task_id:
            self.output_area.append(f"  {message}")

    def _update_background_indicator(self):
        """更新后台任务队列指示器"""
        bg_count = len(self._background_queue)
        if bg_count > 0:
            self.bg_indicator.setText(f"后台: {bg_count}个任务运行中")
            self.bg_indicator.setStyleSheet(f"color: {LEMON_YELLOW}; font-size: 10px;")
            self.bg_progress.setVisible(True)
            if bg_count > 0 and "bg_progress" in self._background_queue[0]:
                self.bg_progress.setValue(self._background_queue[0]["bg_progress"])
        else:
            self.bg_indicator.setText("")
            self.bg_indicator.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
            self.bg_progress.setVisible(False)

    def _on_send(self):
        """发送命令"""
        command = self.input_field.text().strip()
        if not command:
            return

        task_id = self.current_task_id
        task = self.tasks.get(task_id)
        if not task:
            return

        # 更新状态
        task["status"] = "运行中"
        task["page"]._status_dot.setStyleSheet(f"color: {LEMON_ORANGE}; font-size: 10px;")
        task["page"]._status_text.setText("运行中")
        task["page"]._status_text.setStyleSheet(f"color: {LEMON_ORANGE}; font-size: 11px;")
        self.output_status.setText("处理中...")
        self.output_status.setStyleSheet(f"color: {LEMON_ORANGE}; font-size: 10px;")

        # 显示用户输入
        self.output_area.append(f"\n{'='*50}")
        self.output_area.append(f"[用户] {task['name']} | {datetime.now().strftime('%H:%M:%S')}")
        self.output_area.append(f"  {command}")

        # 发送信号（主窗口可连接serve_bridge处理）
        self.command_sent.emit(task_id, command)
        self.input_field.clear()

        task["history"].append({"role": "user", "content": command})

        # 添加到后台任务队列
        self._background_queue.append({"task_id": task_id, "command": command})
        self._update_background_indicator()

        # 尝试直接调用Ollama作为fallback
        threading.Thread(target=self._call_ollama_fallback, args=(task_id, command), daemon=True).start()

    def _call_ollama_fallback(self, task_id: str, command: str):
        """尝试调用Ollama获取AI响应（使用 EngineManager fallback）"""
        try:
            engine = get_engine_manager()
            if not engine._engines.get("ollama"):
                engine.initialize()
            ollama = engine._engines.get("ollama")
            if not ollama or not ollama.is_available():
                return
            # 使用选中的模型
            model = self.model_combo.currentText()
            if not model:
                models = ollama.list_models()
                if not models:
                    return
                model = "qwen3.5:4b"

            result = engine_chat(command, engine="ollama", model=model)
            if result:
                self.terminal_output.append(f"[AI] {result}")
                self._update_task_status(task_id, "completed")
        except Exception as e:
            self.terminal_output.append(f"[回退] Ollama调用失败: {e}")

    def append_ai_response(self, task_id: str, response: str):
        """追加AI响应到输出面板"""
        task = self.tasks.get(task_id)
        if task:
            task["status"] = "完成"
            task["page"]._status_dot.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 10px;")
            task["page"]._status_text.setText("完成")
            task["page"]._status_text.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 11px;")
            task["history"].append({"role": "assistant", "content": response})

        self.output_area.append(f"\n[AI] {datetime.now().strftime('%H:%M:%S')}")
        self.output_area.append(f"  {response}")
        self.output_status.setText("就绪")
        self.output_status.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 10px;")

        # 滚动到底部
        scrollbar = self.output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_task_status(self, task_id: str, status: str):
        """设置任务状态"""
        task = self.tasks.get(task_id)
        if not task:
            return
        task["status"] = status
        if status == "运行中":
            task["page"]._status_dot.setStyleSheet(f"color: {LEMON_ORANGE}; font-size: 10px;")
            task["page"]._status_text.setStyleSheet(f"color: {LEMON_ORANGE}; font-size: 11px;")
        elif status == "完成":
            task["page"]._status_dot.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 10px;")
            task["page"]._status_text.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 11px;")
        elif status == "错误":
            task["page"]._status_dot.setStyleSheet(f"color: {ERROR_COLOR}; font-size: 10px;")
            task["page"]._status_text.setStyleSheet(f"color: {ERROR_COLOR}; font-size: 11px;")
        else:
            task["page"]._status_dot.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
            task["page"]._status_text.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        task["page"]._status_text.setText(status)

    def _clear_all_tasks(self):
        """清空所有任务"""
        while self.task_tabs.count() > 1:
            self.task_tabs.removeTab(1)
        keys = list(self.tasks.keys())
        for k in keys[1:]:
            del self.tasks[k]
        self.output_area.clear()
        self.output_area.setPlaceholderText("选择左侧任务窗口，输入命令后AI响应将显示在这里...")

    def _import_file(self):
        """导入文件到当前任务"""
        task_id = self.current_task_id
        task = self.tasks.get(task_id)
        if not task:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "导入文件", "", "所有文件 (*.*)")
        if file_path:
            import os
            file_name = os.path.basename(file_path)
            item = QTreeWidgetItem(task["page"]._file_tree)
            item.setText(0, file_name)
            item.setText(1, f"{os.path.getsize(file_path) / 1024:.1f} KB")
            item.setText(2, "已导入")

    def _add_file_to_task(self, task_id: str):
        """添加文件到指定任务"""
        task = self.tasks.get(task_id)
        if not task:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "添加文件", "", "所有文件 (*.*)")
        if file_path:
            import os
            file_name = os.path.basename(file_path)
            item = QTreeWidgetItem(task["page"]._file_tree)
            item.setText(0, file_name)
            item.setText(1, f"{os.path.getsize(file_path) / 1024:.1f} KB")
            item.setText(2, "已添加")

    def get_current_task(self) -> dict:
        """获取当前任务信息"""
        return self.tasks.get(self.current_task_id, {})


# ============================================================================
# 导出
# ============================================================================

__all__ = ['SingleAIMultiWindowPanel', 'StarryBackground']