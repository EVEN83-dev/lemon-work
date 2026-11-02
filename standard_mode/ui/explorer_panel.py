# -*- coding: utf-8 -*-
"""
小米风格资源管理器 — 文件树 + 搜索
- 文件夹图标 + 展开/折叠 + 选中高亮
- 文件类型图标
- 搜索框 + 实时过滤
- 悬停效果
"""

import os
import re
import shutil
import time
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget,
    QTreeWidgetItem, QLabel, QFrame, QPushButton, QHeaderView,
    QLineEdit, QDialog, QDialogButtonBox, QFormLayout, QTextEdit, QMessageBox,
    QApplication, QMenu, QAction, QSplitter, QInputDialog
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QSize, QFileSystemWatcher
from PyQt5.QtGui import QFont, QColor, QBrush, QIcon, QPixmap, QPainter
from PyQt5.QtSvg import QSvgRenderer

from ui.theme import *

# ============================================================
# 资源管理器密度（第352章补记1 / 补记2 / 第355章补记3）
# 补记1：行高 24→30。补记2：用户高分屏实测 30px 行高仍偏小，
# 默认档直接升到 24px 图标 / 40px 行高，并新增 huge 档（28/48）。
# 补记3（第355章）：用户二次反馈 24px 仍偏小 → 默认升 28px 图标 / 46px 行高，
# huge 档升 32px，新增 giant 档（32/52）。SVG 矢量渲染无损放大。
# ============================================================
EXPLORER_ICON_SIZE = 28        # 默认图标 28px（第355章 24→28）
EXPLORER_ROW_HEIGHT = 46       # 默认行高 46px
EXPLORER_FONT_PX = 17          # 树字号
EXPLORER_INDENT = 26           # 层级缩进
_ALLOWED_ICON_SIZES = (14, 16, 18, 20, 22, 24, 28, 32)

# 密度档位：一键切换整套视觉参数（探索器右上角/设置可接）
DENSITY_PRESETS = {
    'compact': {'icon': 16, 'row': 28, 'font': 14, 'indent': 16},   # 紧凑：小屏多文件
    'cozy':    {'icon': 20, 'row': 34, 'font': 15, 'indent': 20},   # 舒适
    'roomy':   {'icon': 28, 'row': 46, 'font': 17, 'indent': 26},   # 宽敞：新默认（第355章 24→28）
    'huge':    {'icon': 32, 'row': 52, 'font': 18, 'indent': 30},   # 巨大：演示/高分屏（第355章 28→32）
}

# 文件类型 → (图标名, 色板色)。
# 数据来源统一到 theme.FILE_TYPE_MAP（VSCode Material-Icon 12 色分类），
# 此处保留旧结构做只读兼容：老代码仍在用 FILE_ICON_MAP[ext] 取图标名。
try:
    from ui.theme import FILE_TYPE_MAP as _THEME_FILE_TYPE_MAP
    from ui.theme import (FILE_C_BLUE, FILE_C_YELLOW, FILE_C_ORANGE, FILE_C_CYAN,
                          FILE_C_GREEN, FILE_C_PURPLE, FILE_C_PINK, FILE_C_RED,
                          FILE_C_BROWN, FILE_C_INDIGO, FILE_C_LIME, FILE_C_GRAY)
    FILE_ICON_MAP = {ext: spec[0] for ext, spec in _THEME_FILE_TYPE_MAP.items()}
except Exception:                        # pragma: no cover - 主题缺失时的兜底
    FILE_ICON_MAP = {
        '.py': 'file_py', '.js': 'file_js', '.ts': 'file_ts', '.json': 'file_json',
        '.md': 'file_md', '.html': 'file_html', '.css': 'file_css', '.txt': 'file_txt',
    }
    # 与 ui/design/tokens.py::Lemon 同值，供右键菜单语义染色使用
    FILE_C_BLUE, FILE_C_YELLOW, FILE_C_ORANGE = '#519ABA', '#F0DB4F', '#E34F26'
    FILE_C_CYAN, FILE_C_GREEN, FILE_C_PURPLE = '#4DD0E1', '#89E051', '#C792EA'
    FILE_C_PINK, FILE_C_RED, FILE_C_BROWN = '#FF80AB', '#F44336', '#DEA584'
    FILE_C_INDIGO, FILE_C_LIME, FILE_C_GRAY = '#7986CB', '#C3E88D', '#9E9E9E'

_svg_icon_cache = {}


def svg_to_icon(svg_name, color=TEXT_SECONDARY, size=EXPLORER_ICON_SIZE):
    """将SVG图标转换为QIcon

    ★ 性能修复：相同 (svg_name, color, size) 只解析渲染一次，之后直接复用 QIcon。
      此前每加载一个文件都执行一次 QSvgRenderer 全量解析渲染，
      项目文件多时会导致主线程长时间阻塞（实测文件树刷新卡 2.7s）。

    ★ 清晰度修复：用 theme.get_svg_icon() 生成 SVG，它会按 size 缩放
      stroke-width（16→1.5 / 18→1.6 / 20→1.75 / 24→2.0），
      解决"SVG 写死 16×16、放大后线条比例失衡糊成一团"的问题。
    """
    key = (svg_name, color, size)
    cached = _svg_icon_cache.get(key)
    if cached is not None:
        return cached
    svg_content = get_svg_icon(svg_name, size=size, color=color)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    renderer = QSvgRenderer(svg_content.encode('utf-8'))
    renderer.render(painter)

    painter.end()
    icon = QIcon(pixmap)
    # 缓存上限保护：超过 512 种清空重建（图标种类有限，正常远小于此）
    if len(_svg_icon_cache) >= 512:
        _svg_icon_cache.clear()
    _svg_icon_cache[key] = icon
    return icon


def file_icon_for(name_or_ext: str, is_dir: bool = False, size: int = EXPLORER_ICON_SIZE):
    """按扩展名/目录名取带 12 色分类的 QIcon。

    - 文件：`.py` → ('file_py', 蓝)
    - 目录：`src` → ('folder_src', 蓝)；未命中目录名 → ('folder', 蓝)
    """
    try:
        from ui.theme import get_file_icon_spec
        icon_name, color = get_file_icon_spec(name_or_ext, is_dir=is_dir)
    except Exception:                    # pragma: no cover
        icon_name = FILE_ICON_MAP.get((name_or_ext or '').lower(), 'file_default')
        color = TEXT_SECONDARY
    return svg_to_icon(icon_name, color, size)


class FileSearchBar(QWidget):
    """文件搜索栏 — 实时过滤文件树"""
    search_requested = pyqtSignal(str)  # 搜索文本变化
    regex_toggled = pyqtSignal(bool)    # 正则模式切换

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        self.setFixedHeight(32)
        self.setStyleSheet(f"background: {BG_ROOT}; border-bottom: 1px solid {BORDER_SUBTLE};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(4)

        # 搜索图标（SVG）
        icon_label = QLabel()
        icon_label.setFixedWidth(20)
        icon_label.setStyleSheet("background: transparent;")
        icon_label.setTextFormat(Qt.RichText)
        icon_label.setText(get_svg_icon('search', 16, TEXT_TERTIARY))
        layout.addWidget(icon_label)

        # 搜索输入框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索文件... (Ctrl+F)")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_SECONDARY};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_SUBTLE};
                border-radius: {RADIUS_SM};
                padding: 2px 8px;
                font-size: {FONT_SIZE_SM};
                font-family: {FONT_SYSTEM};
            }}
            QLineEdit:focus {{
                border-color: {XIAOMI_ORANGE};
            }}
        """)
        self.search_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.search_input, 1)

        # 正则按钮
        self.regex_btn = QPushButton(".*")
        self.regex_btn.setFixedSize(28, 22)
        self.regex_btn.setToolTip("正则表达式模式")
        self.regex_btn.setCheckable(True)
        self.regex_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: 1px solid transparent;
                border-radius: {RADIUS_SM};
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton:checked {{
                background: {BG_SURFACE};
                color: {XIAOMI_ORANGE};
                border-color: {XIAOMI_ORANGE};
            }}
            QPushButton:hover {{
                color: {TEXT_PRIMARY};
            }}
        """)
        self.regex_btn.clicked.connect(lambda: self.regex_toggled.emit(self.regex_btn.isChecked()))
        layout.addWidget(self.regex_btn)

        # 清除按钮
        self.clear_btn = QPushButton("✕")
        self.clear_btn.setFixedSize(22, 22)
        self.clear_btn.setToolTip("清除搜索")
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: none;
                border-radius: {RADIUS_SM};
                font-size: 10px;
            }}
            QPushButton:hover {{
                background: {BG_SURFACE};
                color: {ERROR};
            }}
        """)
        self.clear_btn.clicked.connect(self.search_input.clear)
        self.clear_btn.hide()
        layout.addWidget(self.clear_btn)

    def _on_text_changed(self, text):
        self.clear_btn.setVisible(bool(text))
        self.search_requested.emit(text)

    def get_text(self):
        return self.search_input.text()

    def set_focus(self):
        self.search_input.setFocus()
        self.search_input.selectAll()


class ReplaceDialog(QDialog):
    """文件内替换对话框"""
    def __init__(self, file_path, content, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.original_content = content
        self._init_ui()
        self.setWindowTitle(f"替换 — {os.path.basename(file_path)}")
        self.setMinimumSize(600, 480)
        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_PRIMARY};
                color: {TEXT_PRIMARY};
                font-family: {FONT_SYSTEM};
            }}
        """)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 文件路径标签
        path_label = QLabel(f"📄 {self.file_path}")
        path_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: {FONT_SIZE_SM};")
        layout.addWidget(path_label)

        # 搜索/替换表单
        form = QFormLayout()
        form.setSpacing(6)

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("查找文本...")
        self.find_input.setStyleSheet(input_style())
        form.addRow("查找:", self.find_input)

        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("替换为...")
        self.replace_input.setStyleSheet(input_style())
        form.addRow("替换:", self.replace_input)

        layout.addLayout(form)

        # 预览区
        preview_label = QLabel("预览:")
        preview_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {FONT_SIZE_SM}; font-weight: 600;")
        layout.addWidget(preview_label)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Cascadia Code", 10))
        self.preview.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_ROOT};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
                padding: 10px;
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_SM};
            }}
        """)
        self.preview.setPlainText(self.original_content)
        layout.addWidget(self.preview, 1)

        # 实时预览更新
        self.find_input.textChanged.connect(self._update_preview)
        self.replace_input.textChanged.connect(self._update_preview)

        # 按钮
        btn_box = QDialogButtonBox()
        preview_btn = QPushButton("🔍 预览替换")
        preview_btn.setStyleSheet(button_style())
        preview_btn.clicked.connect(self._update_preview)
        btn_box.addButton(preview_btn, QDialogButtonBox.ActionRole)

        apply_btn = QPushButton("✅ 全部替换")
        apply_btn.setStyleSheet(button_primary_style())
        apply_btn.clicked.connect(self._apply_replace)
        btn_box.addButton(apply_btn, QDialogButtonBox.AcceptRole)

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(button_style())
        cancel_btn.clicked.connect(self.reject)
        btn_box.addButton(cancel_btn, QDialogButtonBox.RejectRole)

        layout.addWidget(btn_box)

    def _update_preview(self):
        find_text = self.find_input.text()
        replace_text = self.replace_input.text()
        if not find_text:
            self.preview.setPlainText(self.original_content)
            return
        result = self.original_content.replace(find_text, replace_text)
        self.preview.setPlainText(result)

    def _apply_replace(self):
        find_text = self.find_input.text()
        if not find_text:
            return
        count = self.original_content.count(find_text)
        if count == 0:
            QMessageBox.information(self, "提示", "未找到匹配文本")
            return
        reply = QMessageBox.question(
            self, "确认替换",
            f"将替换 {count} 处匹配，确定继续？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.accept()

    def get_result(self):
        find_text = self.find_input.text()
        replace_text = self.replace_input.text()
        return self.original_content.replace(find_text, replace_text)


class ExplorerPanel(QWidget):
    file_selected = pyqtSignal(str)
    file_replace_requested = pyqtSignal(str, str, str)
    git_action_requested = pyqtSignal(str, str)
    compare_requested = pyqtSignal(str)
    open_in_terminal = pyqtSignal(str)

    _IGNORED_DIRS = frozenset([
        '.git', '__pycache__', 'node_modules', '.venv', 'venv',
        'dist', 'build', '.mypy_cache', '.pytest_cache', '.tox',
        'egg-info', '.eggs', '__pypcache__', '.idea', '.vs',
        'target',  # Rust 构建产物（deepseek_agent 等，可达数万文件）
    ])

    # ★ 卡顿修复(第342章): 监听器专用噪音目录黑名单 — 应用自身每秒都在
    # 这些目录写文件（health快照/会话库/交互日志/黑匣子），监听它们 =
    # 永动刷新循环的燃料。不监听 ≠ 不显示，文件树仍正常展示。
    _WATCH_IGNORED_DIRS = frozenset([
        'data', 'logs', 'log', 'state', 'snapshots', 'cache', 'caches',
        'interaction_logs', '_internal', '.ruff_cache', 'htmlcov', 'cover',
    ])
    _WATCHER_MAX_DIRS = 300  # 监听目录数上限（Win32 句柄 + 事件风暴保护）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_path = ""
        # 密度三参数（见 set_density() / DENSITY_PRESETS）
        self._icon_size = EXPLORER_ICON_SIZE
        self._row_height = EXPLORER_ROW_HEIGHT
        self._font_px = EXPLORER_FONT_PX
        self._indent = EXPLORER_INDENT
        self._all_items = []
        self._search_text = ""
        self._use_regex = False
        self._git_manager = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(200)
        self._refresh_timer.timeout.connect(self._do_refresh)
        self._pending_refresh_dirs = set()
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"background: {BG_SECONDARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        header = QFrame()
        header.setFixedHeight(40)
        header.setStyleSheet(f"background: {BG_ROOT}; border-bottom: 1px solid {BORDER_SUBTLE};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 0, 8, 0)
        h_layout.setSpacing(6)

        title = QLabel("资源管理器")
        title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {FONT_SIZE_MD}; font-weight: 600; background: transparent;")
        h_layout.addWidget(title)
        h_layout.addStretch()

        self._header_btns = []
        for icon_name, tip in [("plus", "新建文件夹"), ("refresh", "刷新"), ("chevron_down", "折叠全部")]:
            btn = QPushButton()
            btn.setFixedSize(self._icon_size + 12, self._icon_size + 12)   # 随密度档联动
            btn.setToolTip(tip)
            self._header_btns.append(btn)
            btn.setIcon(svg_to_icon(icon_name, TEXT_TERTIARY, self._icon_size))
            btn.setIconSize(QSize(self._icon_size, self._icon_size))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {TEXT_TERTIARY};
                    border: none;
                    border-radius: {RADIUS_SM};
                }}
                QPushButton:hover {{
                    background: {BG_SURFACE};
                    color: {TEXT_PRIMARY};
                }}
            """)
            btn.clicked.connect(lambda _, t=tip: self._on_header_action(t))
            h_layout.addWidget(btn)

        layout.addWidget(header)

        # 项目名称
        self.project_label = QLabel()
        self.project_label.setTextFormat(Qt.RichText)
        self.project_label.setFixedHeight(28)
        self.project_label.setStyleSheet(
            f"background: {BG_ROOT}; color: {TEXT_SECONDARY}; font-size: {FONT_SIZE_SM}; font-weight: 600; border-bottom: 1px solid {BORDER_SUBTLE};")
        layout.addWidget(self.project_label)

        # ★ 搜索栏
        self.search_bar = FileSearchBar()
        self.search_bar.search_requested.connect(self._on_search)
        self.search_bar.regex_toggled.connect(self._on_regex_toggle)
        layout.addWidget(self.search_bar)

        # 文件树
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.setIndentation(self._indent)
        self.tree.setStyleSheet(self._tree_qss())
        self.tree.setIconSize(QSize(self._icon_size, self._icon_size))
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree, 1)
        
        # ★ 代码符号大纲（v2.0 新增）
        self._symbol_splitter = QSplitter(Qt.Vertical)
        self._symbol_splitter.setHandleWidth(2)
        self._symbol_splitter.setStyleSheet(f"""
            QSplitter::handle {{ background: {BORDER_SUBTLE}; }}
        """)
        
        # 符号标题
        symbol_header = QFrame()
        symbol_header.setFixedHeight(28)
        symbol_header.setStyleSheet(f"background: {BG_ROOT}; border-top: 1px solid {BORDER_SUBTLE}; border-bottom: 1px solid {BORDER_SUBTLE};")
        sh_layout = QHBoxLayout(symbol_header)
        sh_layout.setContentsMargins(12, 0, 8, 0)
        symbol_title = QLabel()
        symbol_title.setTextFormat(Qt.RichText)
        symbol_title.setText(f'{get_svg_icon("build", 14, TEXT_TERTIARY)}&nbsp;&nbsp;代码大纲')
        symbol_title.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 13px; font-weight: 600; background: transparent;")
        sh_layout.addWidget(symbol_title)
        sh_layout.addStretch()
        self._symbol_file_label = QLabel("")
        self._symbol_file_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
        sh_layout.addWidget(self._symbol_file_label)
        
        self.symbol_tree = QTreeWidget()
        self.symbol_tree.setHeaderHidden(True)
        self.symbol_tree.setIndentation(12)
        self.symbol_tree.setStyleSheet(f"""
            QTreeWidget {{
                background: {BG_SECONDARY};
                color: {TEXT_TERTIARY};
                border: none;
                font-size: 13px;
                font-family: {FONT_SYSTEM};
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 2px 8px;
                border-radius: 2px;
                margin: 0px 4px;
            }}
            QTreeWidget::item:hover {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
            }}
            QTreeWidget::item:selected {{
                background: {BG_SURFACE_HOVER};
                color: {XIAOMI_ORANGE};
            }}
        """)
        self.symbol_tree.itemDoubleClicked.connect(self._on_symbol_clicked)
        
        layout.addWidget(symbol_header)
        layout.addWidget(self.symbol_tree)
        self.symbol_tree.hide()
        symbol_header.hide()

    def set_git_manager(self, git_manager):
        """设置 Git 管理器引用"""
        self._git_manager = git_manager

    # ================================================================
    # 密度体系（第352章补记1）：行高 / 字号 / 缩进 / 图标 一键切换
    # ================================================================
    def _tree_qss(self) -> str:
        """文件树样式表 —— 字号随密度档动态生成。

        ★ show-decoration-selected: 1 —— Windows 原生风格下，选中行的
          branch/图标区域默认用系统高亮蓝（palette Highlight），与 QSS 的
          深灰 item 背景拼成"半蓝半灰"的割裂行。此开关让选中背景覆盖
          整行（含 branch 区），再配合 branch:selected 透明兜底。
        """
        pad_v = max(3, (self._row_height - self._font_px - 6) // 2)
        return f"""
            QTreeWidget {{
                background: {BG_SECONDARY};
                color: {TEXT_SECONDARY};
                border: none;
                font-size: {self._font_px}px;
                font-family: {FONT_SYSTEM};
                outline: none;
                show-decoration-selected: 1;
            }}
            QTreeWidget::item {{
                padding: {pad_v}px 10px;
                border-radius: {RADIUS_SM};
                margin: 1px 4px;
            }}
            QTreeWidget::item:hover {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
            }}
            QTreeWidget::item:selected {{
                background: {BG_SURFACE_HOVER};
                color: {TEXT_PRIMARY};
                border-left: 2px solid {XIAOMI_ORANGE};
            }}
            QTreeWidget::branch {{
                background: transparent;
            }}
            QTreeWidget::branch:selected {{
                background: {BG_SURFACE_HOVER};
            }}
            QTreeWidget::branch:hover {{
                background: {BG_SURFACE};
            }}
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                border-image: none;
            }}
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {{
                border-image: none;
            }}
        """

    def _apply_density(self) -> None:
        """把当前密度参数应用到树控件与头部工具按钮。

        行高由 item 的 setSizeHint 在 load_project 时逐行设置。
        """
        self.tree.setIndentation(self._indent)
        self.tree.setStyleSheet(self._tree_qss())
        self.tree.setIconSize(QSize(self._icon_size, self._icon_size))
        # 头部工具按钮（+/刷新/折叠）随档位联动尺寸与图标
        for btn in getattr(self, '_header_btns', []):
            btn.setFixedSize(self._icon_size + 12, self._icon_size + 12)
            btn.setIconSize(QSize(self._icon_size, self._icon_size))

    def set_density(self, name: str) -> None:
        """切换密度档位：'compact' 紧凑 / 'cozy' 舒适(默认) / 'roomy' 宽松。

        一档改四个参数：图标尺寸、行高、字号、层级缩进。
        仅暴露接口、不接 main_window wiring —— 持久化由上层在
        data/settings.json 存 `explorer_density` 再调本方法。
        """
        preset = DENSITY_PRESETS.get(str(name).lower())
        if not preset:
            return
        self._icon_size = preset['icon']
        self._row_height = preset['row']
        self._font_px = preset['font']
        self._indent = preset['indent']
        self._apply_density()
        if self.project_path and os.path.isdir(self.project_path):
            self._on_header_action("刷新")

    def set_icon_size(self, px: int) -> None:
        """切换资源管理器图标档位（14/16/18/20/22/24）。

        兼容旧接口：行高与字号按图标尺寸联动推导
        （row = clamp(icon+10, 24, 36)，font 随 icon 同步缩放）。
        换档后若已加载项目，会自动重建一次文件树以刷新图标。
        """
        px = int(px)
        if px not in _ALLOWED_ICON_SIZES:
            return
        if px == self._icon_size:
            return
        self._icon_size = px
        self._row_height = max(28, min(56, px + 18))   # 第355章上限 48→56，兼容 32px 巨型档
        self._font_px = max(14, min(18, px - 7))
        self._apply_density()
        if self.project_path and os.path.isdir(self.project_path):
            self._on_header_action("刷新")

    def load_project(self, path, files):
        self.project_path = path
        folder_svg = get_svg_icon('folder', 14, TEXT_SECONDARY)
        self.project_label.setText(f'&nbsp;&nbsp;{folder_svg}&nbsp;&nbsp;{os.path.basename(path)}')
        self.tree.clear()
        self._all_items.clear()

        if self._git_manager:
            self._git_manager.refresh_status()

        root_map = {}
        for f in sorted(files):
            parts = f.replace('\\', '/').split('/')
            current_path = ""
            for i, part in enumerate(parts):
                parent_path = current_path
                current_path = os.path.join(current_path, part).replace('\\', '/')
                if i == len(parts) - 1:
                    # 先按完整文件名匹配（.gitignore / Dockerfile / Makefile 等无扩展名文件），
                    # 再按扩展名匹配；命中 theme.FILE_TYPE_MAP 即带上 12 色分类色。
                    lower_name = part.lower()
                    icon = file_icon_for(lower_name, is_dir=False, size=self._icon_size)
                    if lower_name not in FILE_ICON_MAP:
                        ext = os.path.splitext(part)[1].lower()
                        icon = file_icon_for(ext, is_dir=False, size=self._icon_size)
                    git_color = None
                    if self._git_manager and self._git_manager.is_git_repo:
                        gc = self._git_manager.get_status_color(f)
                        if gc:
                            git_color = gc
                    item = QTreeWidgetItem()
                    item.setIcon(0, icon)
                    item.setText(0, f"  {part}")
                    # 行高显式锁定（QSS padding 对 QTreeWidget 行高不可靠）
                    item.setSizeHint(0, QSize(0, self._row_height))
                    item.setData(0, Qt.UserRole, f)
                    item.setData(0, Qt.UserRole + 1, f)
                    if git_color:
                        item.setForeground(0, QBrush(QColor(git_color)))
                    parent_key = '/'.join(parts[:i])
                    if parent_key in root_map:
                        root_map[parent_key].addChild(item)
                    else:
                        self.tree.addTopLevelItem(item)
                    root_map[current_path] = item
                    self._all_items.append(item)
                else:
                    if current_path not in root_map:
                        item = QTreeWidgetItem()
                        # 目录名命中 FOLDER_TYPE_MAP 时用专属分层图标（src/docs/assets/tests/build/.git）
                        item.setIcon(0, file_icon_for(part, is_dir=True, size=self._icon_size))
                        item.setText(0, f"  {part}")
                        item.setSizeHint(0, QSize(0, self._row_height))
                        item.setData(0, Qt.UserRole, None)
                        item.setData(0, Qt.UserRole + 1, current_path)
                        item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
                        parent_key = '/'.join(parts[:i])
                        if parent_key in root_map:
                            root_map[parent_key].addChild(item)
                        else:
                            self.tree.addTopLevelItem(item)
                        root_map[current_path] = item
                        self._all_items.append(item)

        self.tree.expandAll()
        if self._search_text:
            self._apply_filter()

        self._setup_watcher(path)

    def _setup_watcher(self, path: str) -> None:
        """V6.0: 设置文件系统监听器。

        ★ 卡顿修复(第342章) — 本方法是周期性卡顿的元凶：
        原实现 os.walk 整个项目树并为每个子目录 addPath（数万目录 =
        数千 Win32 watch 句柄 + 每次重建 ~9.4 秒全树重扫，lag_log.csv 实测）。
        而应用自身每秒都在 data/state/logs 写文件（health快照、session_memory、
        黑匣子），每次写入都触发 _on_dir_changed → _do_refresh → 又全树
        os.walk → 刷新期间的新写入再次触发 → 自持 10 秒周期冻结循环。
        修复：只监听根 + 一级子目录（深度2），跳过运行时噪音目录，上限 300。
        文件树显示不受影响（显示走 scan_project，不走 watcher）。
        """
        if not path or not os.path.isdir(path):
            return
        try:
            self._watcher.removePaths(self._watcher.directories())
        except Exception:
            pass
        self._watcher.addPath(path)
        added = 1
        try:
            for entry in os.scandir(path):
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                name = entry.name
                if name in self._IGNORED_DIRS or name in self._WATCH_IGNORED_DIRS:
                    continue
                if added >= self._WATCHER_MAX_DIRS:
                    break
                self._watcher.addPath(entry.path)
                added += 1
        except Exception:
            pass

    def _on_dir_changed(self, dir_path: str) -> None:
        """V6.0: 目录变更 → 防抖刷新。"""
        self._pending_refresh_dirs.add(dir_path)
        self._refresh_timer.start()

    def _on_file_changed(self, file_path: str) -> None:
        """V6.0: 文件变更 → 防抖刷新。"""
        parent = os.path.dirname(file_path)
        self._pending_refresh_dirs.add(parent)
        self._refresh_timer.start()

    def _do_refresh(self) -> None:
        """V6.0: 执行防抖后的刷新 — 重新扫描变更目录。

        ★ 卡顿修复(第342章):
        1) 不再全树重建 watcher（深度2监听已覆盖新增一级目录），
           只对变更到的一级目录补挂监听。
        2) 冷却期 15s：上次刷新完成后 15s 内的新事件直接丢弃，
           斩断"刷新期间的新写入 → 再刷新"自持循环
           （lag_log.csv 实测每 10s 一次 9.4s 冻结即此循环）。
        """
        if not self.project_path:
            return
        now = time.time()
        if now - getattr(self, '_last_refresh_done', 0.0) < 15.0:
            self._pending_refresh_dirs.clear()
            return
        t0 = time.time()
        self._on_header_action("刷新")
        self._last_refresh_done = time.time()
        # 变更到的一级目录补挂监听（覆盖运行期新建目录）
        try:
            changed = set(self._pending_refresh_dirs)
            self._pending_refresh_dirs.clear()
            watched = set(self._watcher.directories())
            root = os.path.abspath(self.project_path)
            for d in changed:
                try:
                    if not d or d in watched or not os.path.isdir(d):
                        continue
                    if os.path.dirname(os.path.abspath(d)) == root:
                        name = os.path.basename(d)
                        if name not in self._IGNORED_DIRS and \
                                name not in self._WATCH_IGNORED_DIRS and \
                                len(watched) < self._WATCHER_MAX_DIRS:
                            self._watcher.addPath(d)
                            watched.add(d)
                except OSError:
                    continue
        except Exception:
            pass
        # 刷新耗时自观察（写黑匣子，不打控制台）
        try:
            dur = time.time() - t0
            if dur > 2.0:
                self._append_perf(f"{time.strftime('%H:%M:%S')},refresh,{dur*1000:.0f}\n")
        except Exception:
            pass

    def _append_perf(self, line: str) -> None:
        """刷新耗时落盘（供黑匣子分析，零控制台输出）"""
        try:
            perf_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))), "data", "perf")
            os.makedirs(perf_dir, exist_ok=True)
            with open(os.path.join(perf_dir, "refresh_log.csv"),
                      "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def _on_search(self, text):
        self._search_text = text
        self._apply_filter()

    def _on_regex_toggle(self, enabled):
        self._use_regex = enabled
        if self._search_text:
            self._apply_filter()

    def _apply_filter(self):
        """根据搜索文本过滤文件树"""
        if not self._search_text:
            # 显示所有项
            for item in self._all_items:
                item.setHidden(False)
            return

        # 收集匹配项路径
        import re
        try:
            if self._use_regex:
                pattern = re.compile(self._search_text, re.IGNORECASE)
            else:
                pattern = self._search_text.lower()
        except re.error:
            return

        matching_paths = set()
        for item in self._all_items:
            path = item.data(0, Qt.UserRole + 1) or ""
            if self._use_regex:
                if pattern.search(path):
                    matching_paths.add(path)
            else:
                if pattern in path.lower():
                    matching_paths.add(path)

        # 显示/隐藏：匹配项及其所有祖先都显示
        for item in self._all_items:
            path = item.data(0, Qt.UserRole + 1) or ""
            # 检查该项或其任何后代是否匹配
            should_show = False
            if path in matching_paths:
                should_show = True
            else:
                # 检查子项
                for i in range(item.childCount()):
                    child_path = item.child(i).data(0, Qt.UserRole + 1) or ""
                    if child_path in matching_paths:
                        should_show = True
                        break
                # 也检查该项路径是否匹配
                if self._use_regex:
                    if pattern.search(path):
                        should_show = True
                else:
                    if pattern in path.lower():
                        should_show = True
            item.setHidden(not should_show)
            if should_show and item.childCount() > 0:
                item.setExpanded(True)

    def focus_search(self):
        """聚焦搜索框（快捷键 Ctrl+F 调用）"""
        self.search_bar.set_focus()
    
    # ================================================================
    # 代码符号大纲（v2.0 新增）
    # ================================================================
    
    symbol_clicked = pyqtSignal(str, int)  # (file_path, line_number)
    
    def update_symbols(self, file_path: str, content: str):
        """解析文件内容并更新符号大纲"""
        if not content:
            self.symbol_tree.hide()
            return
        
        self.symbol_tree.clear()
        self._symbol_file_label.setText(os.path.basename(file_path))
        
        symbols = self._parse_symbols(content, file_path)
        if not symbols:
            self.symbol_tree.hide()
            return
        
        self.symbol_tree.show()
        
        # 构建符号树
        sym_icon_map = {
            "class": "file_default", "function": "run", "method": "tool",
            "variable": "info", "import": "plus", "decorator": "tool",
        }
        for sym in symbols:
            item = QTreeWidgetItem()
            icon_name = sym_icon_map.get(sym["type"], "file_default")
            item.setIcon(0, svg_to_icon(icon_name, TEXT_TERTIARY, 14))
            item.setText(0, f"  {sym['name']}")
            item.setData(0, Qt.UserRole, (file_path, sym["line"]))
            item.setToolTip(0, f"第 {sym['line']} 行 — {sym['type']}")
            
            # 方法的类下缩进
            if sym["type"] in ("method",):
                indent = QTreeWidgetItem()
                indent.setText(0, "")
                self.symbol_tree.addTopLevelItem(indent)
            
            self.symbol_tree.addTopLevelItem(item)
    
    def _parse_symbols(self, content: str, file_path: str) -> list:
        """解析代码符号（支持 Python/JS/TS/Go）"""
        symbols = []
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == '.py':
            symbols = self._parse_python_symbols(content)
        elif ext in ('.js', '.ts', '.jsx', '.tsx'):
            symbols = self._parse_js_symbols(content)
        elif ext == '.go':
            symbols = self._parse_go_symbols(content)
        elif ext in ('.html', '.css', '.json', '.yaml', '.yml', '.md'):
            pass  # 这些文件类型不需要符号解析
        
        return symbols
    
    def _parse_python_symbols(self, content: str) -> list:
        """解析 Python 符号"""
        symbols = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            # 类定义
            if stripped.startswith('class ') and ':' in stripped:
                name = stripped.split('class ')[1].split('(')[0].split(':')[0].strip()
                symbols.append({"name": name, "line": i, "type": "class"})
            # 函数定义
            elif stripped.startswith('def ') and ':' in stripped:
                name = stripped.split('def ')[1].split('(')[0].strip()
                indent = len(line) - len(line.lstrip())
                sym_type = "method" if indent > 0 else "function"
                symbols.append({"name": name, "line": i, "type": sym_type})
            # 装饰器
            elif stripped.startswith('@'):
                name = stripped[1:].split('(')[0].strip()
                symbols.append({"name": f"@{name}", "line": i, "type": "decorator"})
        return symbols
    
    def _parse_js_symbols(self, content: str) -> list:
        """解析 JavaScript/TypeScript 符号"""
        symbols = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            # 函数定义
            if re.match(r'(async\s+)?function\s+\w+', stripped):
                name = re.search(r'function\s+(\w+)', stripped)
                if name:
                    symbols.append({"name": name.group(1), "line": i, "type": "function"})
            # 类定义
            elif stripped.startswith('class ') and '{' in stripped:
                name = stripped.split('class ')[1].split('{')[0].split('extends')[0].strip()
                symbols.append({"name": name, "line": i, "type": "class"})
            # 箭头函数
            elif re.match(r'(const|let|var)\s+\w+\s*=\s*(async\s*)?\(', stripped):
                name = re.search(r'(const|let|var)\s+(\w+)', stripped)
                if name:
                    symbols.append({"name": name.group(2), "line": i, "type": "function"})
            # export
            elif stripped.startswith('export ') and 'function' in stripped:
                name = re.search(r'function\s+(\w+)', stripped)
                if name:
                    symbols.append({"name": name.group(1), "line": i, "type": "function"})
        return symbols
    
    def _parse_go_symbols(self, content: str) -> list:
        """解析 Go 符号"""
        symbols = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('func '):
                name = stripped.split('func ')[1].split('(')[0].strip()
                symbols.append({"name": name, "line": i, "type": "function"})
            elif stripped.startswith('type ') and 'struct' in stripped:
                name = stripped.split('type ')[1].split(' ')[0].strip()
                symbols.append({"name": name, "line": i, "type": "class"})
        return symbols
    
    def _on_symbol_clicked(self, item, col):
        """点击符号 — 跳转到对应行"""
        data = item.data(0, Qt.UserRole)
        if data:
            self.symbol_clicked.emit(data[0], data[1])

    def _on_item_clicked(self, item, col):
        file_path = item.data(0, Qt.UserRole)
        if file_path:
            self.file_selected.emit(file_path)

    def _on_item_double_clicked(self, item, col):
        self._on_item_clicked(item, col)

    def _on_context_menu(self, pos):
        """右键菜单"""
        item = self.tree.itemAt(pos)
        if not item:
            return
        file_path = item.data(0, Qt.UserRole)
        if not file_path:
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 20px;
                border-radius: {RADIUS_SM};
            }}
            QMenu::item:selected {{
                background: {BG_SURFACE_HOVER};
            }}
        """)

        # ★ 右键菜单图标：按「文件类型色 + 动作语义色」染色。
        #   此前全部固定 16px 灰，且 'edit' 键在 SVG_ICONS 中并不存在，
        #   静默 fallback 成 file_default（重命名显示成文件图标）。
        _ext = os.path.splitext(file_path)[1].lower()
        _MENU_SIZE = 16

        open_action = QAction("  打开文件", menu)
        open_action.setIcon(file_icon_for(_ext, is_dir=False, size=_MENU_SIZE))
        open_action.triggered.connect(lambda: self.file_selected.emit(file_path))
        menu.addAction(open_action)

        replace_action = QAction("  查找替换...", menu)
        replace_action.setIcon(svg_to_icon('search', FILE_C_BLUE, _MENU_SIZE))
        replace_action.triggered.connect(lambda: self._on_replace_request(file_path))
        menu.addAction(replace_action)

        compare_action = QAction("  对比文件...", menu)
        compare_action.setIcon(svg_to_icon('tool', FILE_C_PURPLE, _MENU_SIZE))
        compare_action.triggered.connect(lambda: self.compare_requested.emit(file_path))
        menu.addAction(compare_action)

        # 代码审查（通过信号转发到主窗口）
        review_action = QAction("  代码审查", menu)
        review_action.setIcon(svg_to_icon('eye', FILE_C_CYAN, _MENU_SIZE))
        review_action.triggered.connect(lambda: self.git_action_requested.emit("review", file_path))
        menu.addAction(review_action)

        # Git 操作
        if self._git_manager and self._git_manager.is_git_repo:
            menu.addSeparator()
            git_status = self._git_manager.get_file_status(file_path)
            if git_status:
                stage_action = QAction("  Git Add", menu)
                stage_action.setIcon(svg_to_icon('plus', FILE_C_GREEN, _MENU_SIZE))
                stage_action.triggered.connect(lambda: self.git_action_requested.emit("stage", file_path))
                menu.addAction(stage_action)
                if 'M' in git_status or 'A' in git_status:
                    unstage_action = QAction("  Git Unstage", menu)
                    unstage_action.setIcon(svg_to_icon('minus', FILE_C_ORANGE, _MENU_SIZE))
                    unstage_action.triggered.connect(lambda: self.git_action_requested.emit("unstage", file_path))
                    menu.addAction(unstage_action)
                diff_action = QAction("  Git Diff", menu)
                diff_action.setIcon(svg_to_icon('git', FILE_C_ORANGE, _MENU_SIZE))
                diff_action.triggered.connect(lambda: self.git_action_requested.emit("diff", file_path))
                menu.addAction(diff_action)
            else:
                stage_action = QAction("  Git Add", menu)
                stage_action.setIcon(svg_to_icon('plus', FILE_C_GREEN, _MENU_SIZE))
                stage_action.triggered.connect(lambda: self.git_action_requested.emit("stage", file_path))
                menu.addAction(stage_action)

        menu.addSeparator()

        rename_action = QAction("  重命名", menu)
        rename_action.setIcon(svg_to_icon('pencil', FILE_C_YELLOW, _MENU_SIZE))
        rename_action.triggered.connect(lambda: self._do_rename(file_path))
        menu.addAction(rename_action)

        delete_action = QAction("  删除", menu)
        delete_action.setIcon(svg_to_icon('close', FILE_C_RED, _MENU_SIZE))
        delete_action.triggered.connect(lambda: self._do_delete(file_path))
        menu.addAction(delete_action)

        terminal_action = QAction("  在终端中打开", menu)
        terminal_action.setIcon(svg_to_icon('terminal', FILE_C_LIME, _MENU_SIZE))
        terminal_action.triggered.connect(lambda: self.open_in_terminal.emit(file_path))
        menu.addAction(terminal_action)

        menu.addSeparator()

        copy_path_action = QAction("  复制路径", menu)
        copy_path_action.setIcon(svg_to_icon('clipboard', FILE_C_INDIGO, _MENU_SIZE))
        full_path = os.path.join(self.project_path, file_path)
        copy_path_action.triggered.connect(
            lambda: QApplication.clipboard().setText(full_path)
        )
        menu.addAction(copy_path_action)

        menu.exec_(self.tree.mapToGlobal(pos))

    def _do_rename(self, rel_path: str) -> None:
        """V6.0: 重命名文件/目录。"""
        name = os.path.basename(rel_path)
        new_name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=name)
        if not ok or not new_name or new_name == name:
            return
        old_full = os.path.join(self.project_path, rel_path)
        parent_dir = os.path.dirname(old_full)
        new_full = os.path.join(parent_dir, new_name)
        try:
            os.rename(old_full, new_full)
        except Exception as e:
            QMessageBox.warning(self, "重命名失败", str(e))

    def _do_delete(self, rel_path: str) -> None:
        """V6.0: 删除文件/目录。"""
        full_path = os.path.join(self.project_path, rel_path)
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除 " + rel_path + " 吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            if os.path.isdir(full_path):
                shutil.rmtree(full_path)
            else:
                os.remove(full_path)
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))

    def _on_replace_request(self, file_path):
        """打开替换对话框"""
        full_path = os.path.join(self.project_path, file_path)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法读取文件: {e}")
            return

        dialog = ReplaceDialog(file_path, content, self)
        if dialog.exec_() == QDialog.Accepted:
            new_content = dialog.get_result()
            self.file_replace_requested.emit(file_path, content, new_content)

    def _on_header_action(self, action):
        if action == "刷新":
            if self.project_path and os.path.isdir(self.project_path):
                files = []
                for root, dirs, fnames in os.walk(self.project_path):
                    dirs[:] = [d for d in dirs if d not in self._IGNORED_DIRS]
                    for fn in fnames:
                        rel = os.path.relpath(os.path.join(root, fn), self.project_path).replace('\\', '/')
                        files.append(rel)
                self.load_project(self.project_path, files)
        elif action == "折叠全部":
            self.tree.collapseAll()