# -*- coding: utf-8 -*-
r"""
Lemon Code Agent — 主窗口
柠檬 x Lemon Code 融合设计
"""
import os, sys, threading, json, re
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QFrame, QPushButton, QToolButton, QStatusBar,
    QTabWidget, QTextEdit, QSizePolicy, QLineEdit, QScrollBar,
    QShortcut, QDialog, QListWidget, QListWidgetItem, QMessageBox, QInputDialog, QApplication,
    QMenu, QAction, QStackedWidget
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QRect, QPoint
from PyQt5.QtGui import QFont, QKeySequence, QTextCursor, QTextDocument

# ★ 确保项目根目录在 sys.path 中（lemon_agent 目录）
# __file__ = ui/main_window.py, dirname(dirname) = lemon_agent/
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

# ★ 确保 lemon_agent 根目录也在 sys.path 中（用于导入新组件）
_lemon_agent_root = os.path.dirname(_root)
if _lemon_agent_root not in sys.path:
    sys.path.insert(0, _lemon_agent_root)
from core.mimo_engine import MIMOEngine
from core.gui_worm_bridge import GUIWormBridge
from shared.bridges.mimo_process_bridge import MIMOProcessBridge
from core.acp_bridge import ACPBridge, ACPEvent
from core.serve_bridge import MIMOServeBridge
from core.git_manager import GitManager
from core.knowledge_base import KnowledgeBase
from core.session_memory import SessionMemory
from standard_mode.compat import OllamaBridge, USE_BRIDGE_ENGINE  # ★ v3.45: compat层 + v3.0 bridge切换
from core.multi_session_manager import MultiSessionManager, SessionState, SessionRole
from core.multi_instance_manager import MultiInstanceManager, InstanceRole, InstanceState as InstanceStateEnum
from core.lsp_manager import LSPServerManager  # v0.7.0 LSP服务器管理（含崩溃恢复+C++支持）
from core.i18n import _t
from ui.multi_instance_grid import MultiInstanceGrid
from ui.completion_popup import CompletionPopup  # v0.6.0 补全弹窗
from core.code_formatter import FormatterManager  # v0.6.0 代码格式化
from core.ai_provider import (
    IAIProvider, ChatRequest, Message, ChatResponse,
    MIMOAdapter, OllamaAdapter, AIRouter, ProviderType, TaskComplexity
)
from core.task_engine import TaskEngine, TaskTree, TaskDecomposer, Task, TaskStatus
from core.plugin_system import PluginManager, HookPoint, Skill, ToolDefinition
from ui.theme import *
from ui.explorer_panel import ExplorerPanel
from ui.diff_editor import DiffEditor, CodeEditor, SideBySideDiffEditor
from ui.foldable_editor import FoldableCodeEditorWidget  # v0.6.0 可折叠编辑器
from ui.mimo_panel import MIMOCodePanel
from ui.session_workspace import SessionWorkspace
from ui.engine_mode_selector import EngineModeSelector  # ★ v3.51: 引擎模式选择器
from ui.agent_status_light import AgentStatusLight  # ★ v3.81: Agent 状态三色灯
from ui.terminal_panel import TerminalPanel
from ui.thinking_process_panel import ThinkingProcessPanel
from ui.trajectory_panel import TrajectoryPanel
from ui.design.tokens import Lemon
from ui.design.theme import ThemeManager





# ============================================================
# Lemon风格标题栏
# ============================================================
class XiaomiTitleBar(QFrame):
    """Lemon风格标题栏 — Mi logo + LEMON CODE + 工具栏 + 窗口控制"""

    command_sent = pyqtSignal(str)
    mode_changed = pyqtSignal(str)
    model_changed = pyqtSignal(str)
    host_action_requested = pyqtSignal(str)
    language_changed = pyqtSignal(str)
    # ★ LemonGaze C3: 陪伴模式开关（正交于 NATIVE/HOST 引擎模式）
    companion_toggled = pyqtSignal(bool)
    # ★ TRAE 同款：AI 面板布局三档切换（right=右侧栏 / bottom=底部 / hidden=收起）
    layout_mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(72)
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background: {BG_ROOT};
                border-bottom: 1px solid {BORDER_SUBTLE};
            }}
        """)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ===== 第一行：Logo + 控制区 =====
        top_row = QWidget()
        top_row.setFixedHeight(48)   # ★ v3.81: 从 40 提到 48，容纳更大字号
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(10, 0, 8, 0)
        top_layout.setSpacing(0)

        # ★ v3.81: Agent 状态三色灯 — 红/黄/绿
        self.agent_status_light = AgentStatusLight()
        # ★ v3.90: 应用持久化的动画配置（模式 + 速度）
        self._apply_agent_light_config()
        top_layout.addWidget(self.agent_status_light)

        top_layout.addSpacing(6)

        # 品牌标识 ★ Lemon Work：仅保留一个词标（原 NINGMENG + LEMON CODE 合并）
        mi_logo = QLabel()
        mi_logo.setAlignment(Qt.AlignCenter)
        mi_logo.setTextFormat(Qt.RichText)
        mi_logo.setText("")
        mi_logo.setStyleSheet("background: transparent; padding: 0;")
        mi_logo.setFixedWidth(0)
        top_layout.addWidget(mi_logo)
        top_layout.addSpacing(2)

        # Lemon Work 词标
        logo = QLabel()
        logo.setTextFormat(Qt.RichText)
        logo.setText(
            f'<span style="color:{MIMO_ORANGE};font-size:20px;font-weight:900;'
            f'font-family:{FONT_CODE_LOGO};letter-spacing:2px;">Lemon</span>'
            f'<span style="color:{TEXT_SECONDARY};font-size:20px;font-weight:600;'
            f'font-family:{FONT_CODE_LOGO};letter-spacing:1px;"> Work</span>'
        )
        logo.setStyleSheet("background: transparent; padding: 0 2px;")
        top_layout.addWidget(logo)
        top_layout.addSpacing(6)

        # AI引擎 标签 ★ v3.91: 字号略提升，与标题比例协调
        ai_tag = QLabel(_t("window.engine"))
        ai_tag.setAlignment(Qt.AlignCenter)
        ai_tag.setStyleSheet(f"""
            QLabel {{
                background: {XIAOMI_ORANGE};
                color: #000;
                font-size: 10px;
                font-weight: 700;
                border-radius: 3px;
                padding: 1px 6px;
            }}
        """)
        top_layout.addWidget(ai_tag)
        top_layout.addSpacing(16)

        top_layout.addStretch()

        # ★ v4.0: 模式选择器（右上角）— 模式 + 模型选择
        self.engine_selector = EngineModeSelector()
        self.engine_selector.mode_changed.connect(self._on_engine_mode_changed)
        self.engine_selector.model_changed.connect(self.model_changed.emit)
        top_layout.addWidget(self.engine_selector)
        top_layout.addSpacing(10)

        # ★ v4.1.14: 顶部只显示模式按钮，隐藏模型按钮 + 状态灯 ——
        # 底部 BottomPanel 已经承担模型入口，避免一个模型名在两处漂移（用户反馈"右上角两个模型灯"）。
        self.engine_selector.set_model_selector_visible(False)

        # ★ LemonGaze C3: "陪伴"开关按钮（EngineModeSelector 右侧，checkable）
        # 自绘小眼图标（对齐 _btn_pin 画法），不碰 theme.py 颜色定义。
        self._btn_companion = QToolButton()
        self._btn_companion.setFixedSize(32, 32)
        self._btn_companion.setCheckable(True)
        self._btn_companion.setCursor(Qt.PointingHandCursor)
        self._btn_companion.setToolTip("柠檬之瞳 · 陪伴模式（正交于引擎模式）")

        def _eye_icon(checked: bool):
            from PyQt5.QtGui import (
                QIcon, QPixmap, QPainter, QColor, QPen, QBrush)
            col = QColor(XIAOMI_ORANGE) if checked else QColor(TEXT_PRIMARY)
            pix = QPixmap(20, 20)
            pix.fill(Qt.transparent)
            pp = QPainter(pix)
            pp.setRenderHint(QPainter.Antialiasing)
            pp.setPen(QPen(col, 1.6))
            pp.setBrush(Qt.NoBrush)
            # 眼眶（杏仁形）+ 瞳孔
            pp.drawArc(2, 5, 16, 10, 0, 180 * 16)
            pp.drawArc(2, 5, 16, 10, 180 * 16, 180 * 16)
            pp.setBrush(QBrush(col))
            pp.drawEllipse(8, 8, 4, 4)
            pp.end()
            return QIcon(pix)

        self._companion_icon_factory = _eye_icon
        self._btn_companion.setIcon(_eye_icon(False))
        self._btn_companion.setIconSize(QSize(20, 20))
        self._btn_companion.toggled.connect(
            lambda on: (self._btn_companion.setIcon(_eye_icon(on)),
                        self.companion_toggled.emit(on)))
        top_layout.addWidget(self._btn_companion)
        top_layout.addSpacing(10)

        # ★ TRAE 同款：AI 面板布局三档切换按钮组（右侧栏 / 底部 / 收起）
        # 自绘图标对齐 _btn_pin 画法；状态经 layout_mode_changed 信号驱动 MIMOWindow
        self._layout_btns = {}

        def _layout_icon(kind: str, checked: bool):
            from PyQt5.QtGui import (
                QIcon, QPixmap, QPainter, QColor, QPen, QBrush)
            col = QColor(XIAOMI_ORANGE) if checked else QColor(TEXT_PRIMARY)
            pix = QPixmap(20, 20)
            pix.fill(Qt.transparent)
            pp = QPainter(pix)
            pp.setRenderHint(QPainter.Antialiasing)
            pen = QPen(col, 1.6)
            pp.setPen(pen)
            pp.setBrush(Qt.NoBrush)
            pp.drawRect(3, 4, 14, 12)
            pp.setBrush(QBrush(col))
            if kind == 'right':      # 右侧栏：右侧 1/3 实心
                pp.drawRect(12, 4, 5, 12)
            elif kind == 'bottom':   # 底部：下 1/3 实心
                pp.drawRect(3, 12, 14, 4)
            else:                    # 收起：仅右侧细条
                pp.drawRect(15, 4, 2, 12)
            pp.end()
            return QIcon(pix)

        self._layout_icon_factory = _layout_icon
        _sw = QWidget()
        _sw.setStyleSheet("background: transparent;")
        _sw_layout = QHBoxLayout(_sw)
        _sw_layout.setContentsMargins(0, 0, 0, 0)
        _sw_layout.setSpacing(2)
        for _mode, _tip in (('right', 'AI 面板停靠右侧栏'),
                            ('bottom', 'AI 面板停靠底部'),
                            ('hidden', '收起 AI 面板')):
            _btn = QToolButton()
            _btn.setFixedSize(30, 28)
            _btn.setCheckable(True)
            _btn.setCursor(Qt.PointingHandCursor)
            _btn.setToolTip(_tip)
            _btn.setIcon(_layout_icon(_mode, False))
            _btn.setIconSize(QSize(18, 18))
            _btn.setStyleSheet(f"""
                QToolButton {{
                    background: transparent;
                    border: none;
                    color: {TEXT_PRIMARY};
                }}
                QToolButton:hover {{ background: {BG_SURFACE}; }}
                QToolButton:checked {{ background: {XIAOMI_ORANGE}; color: #fff; }}
            """)
            _btn.clicked.connect(
                lambda _checked=False, m=_mode: self.layout_mode_changed.emit(m))
            _sw_layout.addWidget(_btn)
            self._layout_btns[_mode] = _btn
        self._layout_btns['right'].setChecked(True)

        top_layout.addWidget(_sw)
        top_layout.addSpacing(6)

        # ★ v4.7.21: 窗口置顶按钮（sparkles 图标，与 min/max/close 同组）
        self._btn_pin = QToolButton()
        self._btn_pin.setFixedSize(32, 32)
        self._btn_pin.setCheckable(True)
        self._btn_pin.setCursor(Qt.PointingHandCursor)
        self._btn_pin.setToolTip("窗口置顶（再次点击取消）")
        from PyQt5.QtGui import QIcon as _QI, QPixmap as _QP, QPainter as _QPt, QColor as _QC, QPen as _QPe
        _pin_pix = _QP(20, 20)
        _pin_pix.fill(Qt.transparent)
        _pp = _QPt(_pin_pix)
        _pp.setRenderHint(_QPt.Antialiasing)
        _pp.setPen(_QPe(_QC(TEXT_PRIMARY), 1.6))
        _pp.setBrush(Qt.NoBrush)
        # 中心菱形
        _pp.drawLine(10, 6, 14, 10)
        _pp.drawLine(14, 10, 10, 14)
        _pp.drawLine(10, 14, 6, 10)
        _pp.drawLine(6, 10, 10, 6)
        # 左上小星
        _pp.drawLine(3, 3, 5, 4)
        _pp.drawLine(5, 4, 4, 6)
        _pp.drawLine(4, 6, 2, 5)
        _pp.drawLine(2, 5, 3, 3)
        # 右下小星
        _pp.drawLine(15, 14, 17, 15)
        _pp.drawLine(17, 15, 16, 17)
        _pp.drawLine(16, 17, 14, 16)
        _pp.drawLine(14, 16, 15, 14)
        _pp.end()
        self._btn_pin.setIcon(_QI(_pin_pix))
        self._btn_pin.setIconSize(QSize(20, 20))
        self._btn_pin.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: none;
                color: {TEXT_PRIMARY};
            }}
            QToolButton:hover {{ background: {BG_SURFACE}; }}
            QToolButton:checked {{ background: {XIAOMI_ORANGE}; color: #fff; }}
        """)
        self._btn_pin.clicked.connect(self._on_pin)

        # 窗口控制
        self._btn_min = QPushButton("─")
        self._btn_min.setFixedSize(32, 32)
        self._btn_min.setToolTip(_t("window.minimize"))
        self._btn_min.setStyleSheet(self._ctrl_btn_style(False))
        self._btn_min.clicked.connect(self._on_minimize)

        self._btn_max = QPushButton("□")
        self._btn_max.setFixedSize(32, 32)
        self._btn_max.setToolTip(_t("window.maximize"))
        self._btn_max.setStyleSheet(self._ctrl_btn_style(False))
        self._btn_max.clicked.connect(self._on_maximize)

        self._btn_close = QPushButton("✕")
        self._btn_close.setFixedSize(32, 32)
        self._btn_close.setToolTip(_t("window.close"))
        self._btn_close.setStyleSheet(self._ctrl_btn_style(True))
        self._btn_close.clicked.connect(self._on_close)

        top_layout.addWidget(self._btn_pin)
        top_layout.addWidget(self._btn_min)
        top_layout.addWidget(self._btn_max)
        top_layout.addWidget(self._btn_close)

        main_layout.addWidget(top_row)

        # ===== 第二行：菜单栏 =====
        menu_row = QWidget()
        menu_row.setFixedHeight(30)
        menu_row.setStyleSheet(f"background: {BG_ROOT};")
        menu_layout = QHBoxLayout(menu_row)
        menu_layout.setContentsMargins(8, 0, 8, 0)
        menu_layout.setSpacing(0)
        # ★ v4.7.18: 暴露 menu_layout 给 MIMOWindow 加入搜索框+积分
        self.menu_layout = menu_layout

        # 菜单项定义
        menu_defs = [
            {
                "label": _t("menu.file_menu"),
                "items": [
                    {"id": "new_file", "label": _t("menu.file.new_file"), "shortcut": "Ctrl+N"},
                    {"id": "open_folder", "label": _t("menu.file.open_folder"), "shortcut": "Ctrl+O"},
                    {"separator": True},
                    {"id": "save", "label": _t("menu.file.save"), "shortcut": "Ctrl+S"},
                    {"id": "save_all", "label": _t("menu.file.save_all"), "shortcut": "Ctrl+Shift+S"},
                    {"separator": True},
                    {"id": "close_editor", "label": _t("menu.file.close_editor"), "shortcut": "Ctrl+W"},
                ],
            },
            {
                "label": _t("menu.edit_menu"),
                "items": [
                    {"id": "undo", "label": _t("menu.edit_undo"), "shortcut": "Ctrl+Z"},
                    {"id": "redo", "label": _t("menu.edit_redo"), "shortcut": "Ctrl+Y"},
                    {"separator": True},
                    {"id": "cut", "label": _t("menu.edit_cut"), "shortcut": "Ctrl+X"},
                    {"id": "copy", "label": _t("menu.edit_copy"), "shortcut": "Ctrl+C"},
                    {"id": "paste", "label": _t("menu.edit_paste"), "shortcut": "Ctrl+V"},
                    {"separator": True},
                    {"id": "find", "label": _t("menu.edit_find"), "shortcut": "Ctrl+F"},
                    {"id": "replace", "label": _t("menu.edit_replace"), "shortcut": "Ctrl+H"},
                ],
            },
            {
                "label": _t("menu.select_menu"),
                "items": [
                    {"id": "select_all", "label": _t("menu.edit_select_all"), "shortcut": "Ctrl+A"},
                    {"id": "select_line", "label": _t("menu.edit_select_line"), "shortcut": "Ctrl+L"},
                    {"id": "expand_selection", "label": _t("menu.edit_extend_selection"), "shortcut": "Shift+Alt+→"},
                ],
            },
            {
                "label": _t("menu.view_menu"),
                "items": [
                    {"id": "toggle_sidebar", "label": _t("menu.view_toggle_sidebar"), "shortcut": "Ctrl+B"},
                    {"id": "toggle_panel", "label": _t("menu.view_toggle_panel"), "shortcut": "Ctrl+J"},
                    {"id": "toggle_terminal", "label": _t("menu.view_toggle_terminal"), "shortcut": "Ctrl+`"},
                    {"separator": True},
                    {"id": "toggle_explorer", "label": _t("menu.view_explorer"), "shortcut": "Ctrl+Shift+E"},
                    {"id": "toggle_search", "label": _t("menu.view_search"), "shortcut": "Ctrl+Shift+F"},
                    {"id": "toggle_git", "label": _t("menu.view_scm"), "shortcut": "Ctrl+Shift+G"},
                    {"separator": True},
                    {"id": "diff_summary", "label": "变更汇总", "shortcut": "Ctrl+Shift+D"},
                ],
            },
            {
                "label": _t("menu.goto_menu"),
                "items": [
                    {"id": "go_to_file", "label": _t("menu.view_goto_file"), "shortcut": "Ctrl+P"},
                    {"id": "go_to_line", "label": _t("menu.view_goto_line"), "shortcut": "Ctrl+G"},
                    {"id": "go_to_symbol", "label": _t("menu.view_goto_symbol"), "shortcut": "Ctrl+Shift+O"},
                    {"id": "go_to_definition", "label": _t("menu.view_goto_definition"), "shortcut": "F12"},
                ],
            },
            {
                "label": _t("menu.run_menu"),
                "items": [
                    {"id": "run", "label": _t("menu.run_run"), "shortcut": "F5"},
                    {"id": "debug", "label": _t("menu.run_debug"), "shortcut": "F5"},
                    {"id": "stop", "label": _t("menu.run_stop"), "shortcut": "Shift+F5"},
                    {"separator": True},
                    {"id": "run_config", "label": _t("menu.run_config"), "shortcut": ""},
                ],
            },
            {
                "label": _t("menu.help_menu"),
                "items": [
                    {"id": "documentation", "label": _t("menu.help_doc"), "shortcut": ""},
                    {"id": "shortcuts", "label": _t("menu.help_shortcuts"), "shortcut": "Ctrl+K Ctrl+S"},
                    {"separator": True},
                    {"id": "about", "label": _t("menu.help_about"), "shortcut": ""},
                ],
            },
        ]

        for menu_def in menu_defs:
            btn = QToolButton()
            btn.setText(menu_def["label"])
            btn.setFixedHeight(28)
            btn.setMinimumWidth(64)
            btn.setArrowType(Qt.NoArrow)  # ★ 移除默认的下拉箭头
            btn.setPopupMode(QToolButton.InstantPopup)
            btn.setFont(QFont("Microsoft YaHei", 10))
            btn.setStyleSheet(f"""
                QToolButton {{
                    background: transparent;
                    color: {TEXT_PRIMARY};
                    border: none;
                    border-radius: {RADIUS_SM};
                    padding: 0 12px;
                    text-align: left;
                }}
                QToolButton:hover {{
                    background: {BG_SURFACE_HOVER};
                    color: {LEMON_ORANGE};
                }}
                QToolButton::menu-indicator {{
                    width: 0px;  /* ★ 隐藏菜单指示器 */
                }}
            """)

            menu = QMenu(self)
            menu.setStyleSheet(f"""
                QMenu {{
                    background: {BG_SECONDARY};
                    border: 1px solid {BORDER_DEFAULT};
                    padding: 4px;
                }}
                QMenu::item {{
                    color: {TEXT_PRIMARY};
                    padding: 6px 20px 6px 12px;
                    border-radius: {RADIUS_SM};
                }}
                QMenu::item:selected {{
                    background: {BG_SURFACE_HOVER};
                    color: {LEMON_ORANGE};
                }}
                QMenu::separator {{
                    height: 1px;
                    background: {BORDER_SUBTLE};
                    margin: 4px 8px;
                }}
            """)
            for item in menu_def["items"]:
                if item.get("separator"):
                    menu.addSeparator()
                else:
                    action = QAction(item["label"], self)
                    if item.get("shortcut"):
                        action.setShortcut(QKeySequence(item["shortcut"]))
                    action.triggered.connect(lambda _, aid=item["id"]: self.command_sent.emit(aid))
                    menu.addAction(action)

            btn.setMenu(menu)
            menu_layout.addWidget(btn)

        menu_layout.addStretch()

        # ===== ★ v4.7.x: 顶部工具栏右侧图标（Trae/Cursor 风格：搜索/Agents/设置） =====
        self._build_top_toolbar_right(menu_layout)

        # ===== ★ v4.1.11: Host Agent 功能栏（扫描/选择/连接/断开） =====
        self._build_host_toolbar(menu_layout)

        main_layout.addWidget(menu_row)

    def _build_host_toolbar(self, menu_layout):
        """★ v4.1.11: 构建 Host Agent 顶部功能栏

        仅在 HOST 模式显示：当前 Agent 名称 + 扫描/选择/连接/断开 四键。
        """
        host_container = QWidget()
        host_layout = QHBoxLayout(host_container)
        host_layout.setContentsMargins(4, 0, 4, 0)
        host_layout.setSpacing(4)

        # 紫色 Host 标签
        host_tag = QLabel("HOST")
        host_tag.setStyleSheet(f"""
            QLabel {{
                background: {Lemon.ACCENT_PURPLE};
                color: #fff;
                font-size: 9px;
                font-weight: 800;
                border-radius: 3px;
                padding: 1px 5px;
            }}
        """)
        host_layout.addWidget(host_tag)

        # 当前 Agent 名称（可点击重新选择）
        self.host_agent_label = QLabel(_t("window.not_selected"))
        self.host_agent_label.setToolTip("当前夺舍的 Agent（点击选择）")
        self.host_agent_label.setStyleSheet(f"""
            QLabel {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {Lemon.ACCENT_PURPLE};
                border-radius: 3px;
                padding: 1px 8px;
                font-size: 11px;
                font-weight: 600;
            }}
        """)
        host_layout.addWidget(self.host_agent_label)

        # 四个操作按钮
        self.host_btns = {}
        for key, icon, tip in [
            ("scan", "↻", "重新扫描本机 Agent"),
            ("select", "⌄", "选择 Agent"),
            ("connect", "▶", "连接夺舍"),
            ("disconnect", "■", "断开夺舍"),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(22, 22)
            btn.setToolTip(tip)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {Lemon.ACCENT_PURPLE};
                    border: 1px solid {Lemon.ACCENT_PURPLE};
                    border-radius: 3px;
                    font-size: 10px;
                    font-weight: 700;
                }}
                QPushButton:hover {{
                    background: {Lemon.ACCENT_PURPLE};
                    color: #fff;
                }}
                QPushButton:disabled {{
                    border-color: #555;
                    color: #666;
                }}
            """)
            btn.clicked.connect(lambda _, k=key: self.host_action_requested.emit(k))
            host_layout.addWidget(btn)
            self.host_btns[key] = btn

        # 默认隐藏（仅 HOST 模式显示）
        host_container.setVisible(False)
        self._host_toolbar = host_container
        menu_layout.addWidget(host_container)

    def set_host_toolbar_visible(self, visible: bool):
        """★ v4.1.11: 控制 Host 功能栏显隐（HOST 模式显示 / NATIVE 隐藏）"""
        if hasattr(self, "_host_toolbar"):
            self._host_toolbar.setVisible(visible)

    def _build_top_toolbar_right(self, menu_layout):
        """★ v4.7.x: 顶部工具栏右侧图标（Trae/Cursor 风格：搜索/Agents/侧栏/设置）

        紧贴 _build_host_toolbar 左侧。图标用 QPainter 绘制简洁线条，
        hover 显示橙色高亮，点击触发对应快捷键。
        """
        try:
            from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen

            def _svg_btn(icon_drawer, tooltip, slot, shortcut_text=""):
                btn = QToolButton()
                btn.setToolTip(f"{tooltip}{('  ' + shortcut_text) if shortcut_text else ''}")
                btn.setFixedSize(28, 28)
                btn.setCursor(Qt.PointingHandCursor)
                pix = QPixmap(20, 20)
                pix.fill(Qt.transparent)
                p = QPainter(pix)
                p.setRenderHint(QPainter.Antialiasing)
                icon_drawer(p)
                p.end()
                btn.setIcon(QIcon(pix))
                btn.setIconSize(QSize(20, 20))
                btn.setStyleSheet(f"""
                    QToolButton {{
                        background: transparent;
                        border: none;
                        border-radius: {RADIUS_SM};
                    }}
                    QToolButton:hover {{
                        background: {BG_SURFACE_HOVER};
                    }}
                """)
                btn.clicked.connect(slot)
                return btn

            def _icon_search(p):
                pen = QPen(QColor(TEXT_TERTIARY), 1.6)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(3, 3, 11, 11)
                p.drawLine(13, 13, 17, 17)

            def _icon_agents(p):
                pen = QPen(QColor(TEXT_TERTIARY), 1.6)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                # 三个圆点 + 连线代表多实例 Agents
                p.drawEllipse(2, 8, 6, 6)
                p.drawEllipse(7, 4, 6, 6)
                p.drawEllipse(12, 8, 6, 6)
                p.drawLine(5, 11, 9, 7)
                p.drawLine(11, 7, 14, 11)

            def _icon_sidebar(p):
                pen = QPen(QColor(TEXT_TERTIARY), 1.6)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(3, 3, 14, 14)
                p.drawLine(8, 3, 8, 17)

            def _icon_settings(p):
                """设置：圆 + 内圆（简化版齿轮）"""
                pen = QPen(QColor(TEXT_TERTIARY), 1.6)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(3, 3, 14, 14)
                p.drawEllipse(7, 7, 6, 6)

            def _on_search_clicked():
                from PyQt5.QtWidgets import QInputDialog
                kw, ok = QInputDialog.getText(self, "全局搜索", "输入文件名/函数名/关键字：")
                if ok and kw.strip():
                    self._open_editor_tab(kw.strip(), "")
                    self.bottom_panel.log_output(f"[搜索] {kw}", INFO)

            def _on_agents_clicked():
                try:
                    info = self.session_workspace.list_sessions_info() if hasattr(self, "session_workspace") else {"ok": True, "items": []}
                except Exception:
                    info = {"ok": True, "items": []}
                items = info.get("items", []) if isinstance(info, dict) else []
                if not items:
                    self.bottom_panel.log_output("[Agents] 当前无活跃会话", INFO)
                    return
                lines = [f"• {it.get('name','?')}  ({it.get('id','?')[:12]}…)  {'忙' if it.get('busy') else '空闲'}" for it in items]
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.information(self, f"Agents ({len(items)})", "\n".join(lines))

            def _on_settings_clicked():
                try:
                    if hasattr(self, "_open_settings"):
                        self._open_settings()
                    else:
                        self.bottom_panel.log_output("[设置] 请使用 Ctrl+, 打开设置", INFO)
                except Exception:
                    pass

            def _on_toggle_sidebar_clicked():
                try:
                    if hasattr(self, "sidebar"):
                        self.sidebar.setVisible(not self.sidebar.isVisible())
                except Exception:
                    pass

            menu_layout.addSpacing(6)

            from standard_mode.core.i18n import get_i18n, _LANGUAGE_NAMES, _SUPPORTED_LANGUAGES
            i18n = get_i18n()
            self._lang_btn = QToolButton()
            current_lang = i18n.get_current_language()
            lang_display = _LANGUAGE_NAMES.get(current_lang, current_lang)
            self._lang_btn.setText(lang_display)
            self._lang_btn.setFixedHeight(22)
            self._lang_btn.setMinimumWidth(56)
            self._lang_btn.setPopupMode(QToolButton.InstantPopup)
            self._lang_btn.setFont(QFont("Microsoft YaHei", 9))
            self._lang_btn.setCursor(Qt.PointingHandCursor)
            self._lang_btn.setStyleSheet(f"""
                QToolButton {{
                    background: {BG_SURFACE};
                    color: {TEXT_SECONDARY};
                    border: 1px solid {BORDER_DEFAULT};
                    border-radius: {RADIUS_SM};
                    padding: 0 8px;
                    text-align: center;
                }}
                QToolButton:hover {{
                    background: {BG_SURFACE_HOVER};
                    color: {LEMON_ORANGE};
                    border-color: {LEMON_ORANGE};
                }}
                QToolButton::menu-indicator {{
                    width: 0px;
                }}
            """)
            lang_menu = QMenu(self)
            lang_menu.setStyleSheet(f"""
                QMenu {{
                    background: {BG_SECONDARY};
                    border: 1px solid {BORDER_DEFAULT};
                    padding: 4px;
                }}
                QMenu::item {{
                    color: {TEXT_PRIMARY};
                    padding: 6px 16px;
                    border-radius: {RADIUS_SM};
                }}
                QMenu::item:selected {{
                    background: {BG_SURFACE_HOVER};
                    color: {LEMON_ORANGE};
                }}
            """)
            for lang_code in _SUPPORTED_LANGUAGES:
                lang_name = _LANGUAGE_NAMES.get(lang_code, lang_code)
                act = QAction(lang_name, self)
                act.setData(lang_code)
                if lang_code == current_lang:
                    font = act.font()
                    font.setBold(True)
                    act.setFont(font)
                act.triggered.connect(lambda _, lc=lang_code: self._on_language_changed(lc))
                lang_menu.addAction(act)
            self._lang_btn.setMenu(lang_menu)
            menu_layout.addWidget(self._lang_btn)
            menu_layout.addSpacing(6)
        except Exception:
            pass

    def set_host_agent_name(self, name: str):
        """★ v4.1.11: 更新当前夺舍 Agent 名称显示"""
        if hasattr(self, "host_agent_label"):
            self.host_agent_label.setText(name or "未选择")

    def set_host_connected(self, connected: bool):
        """★ v4.1.11: 更新连接状态（连接后禁止重复连接/选择）"""
        if not hasattr(self, "host_btns"):
            return
        self.host_btns["connect"].setEnabled(not connected)
        self.host_btns["select"].setEnabled(not connected)
        self.host_btns["disconnect"].setEnabled(connected)

    def set_layout_mode(self, mode: str):
        """★ 布局三档按钮组状态同步（由 MIMOWindow._apply_ai_layout 回写）。"""
        if mode not in ('right', 'bottom', 'hidden'):
            return
        factory = getattr(self, '_layout_icon_factory', None)
        for m, btn in getattr(self, '_layout_btns', {}).items():
            checked = (m == mode)
            btn.setChecked(checked)
            if factory is not None:
                try:
                    btn.setIcon(factory(m, checked))
                except Exception:
                    pass

    def _ctrl_btn_style(self, is_close: bool = False) -> str:
        """窗口控制按钮样式"""
        hover_bg = XIAOMI_ORANGE if is_close else BG_SURFACE
        hover_color = '#fff' if is_close else TEXT_PRIMARY
        return f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: none;
                border-radius: {RADIUS_MD};
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
                color: {hover_color};
            }}
            QPushButton:pressed {{
                background: {LEMON_ORANGE_DARK if is_close else BG_ROOT};
            }}
        """

    def _flash_button(self, btn):
        """按钮点击橙色闪烁动画（0.2秒）"""
        original_style = btn.styleSheet()
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {XIAOMI_ORANGE};
                color: #fff;
                border: none;
                border-radius: {RADIUS_MD};
                font-size: 12px;
            }}
        """)
        QTimer.singleShot(200, lambda: btn.setStyleSheet(original_style))

    def _on_minimize(self):
        """最小化窗口"""
        self._flash_button(self._btn_min)
        win = self.window()
        if win:
            win.showMinimized()

    def _on_maximize(self):
        """最大化/还原窗口"""
        self._flash_button(self._btn_max)
        win = self.window()
        if not win:
            return
        if win.isMaximized():
            win.showNormal()
            self._btn_max.setText("□")
            self._btn_max.setToolTip(_t("window.maximize"))
        else:
            win.showMaximized()
            self._btn_max.setText("❐")
            self._btn_max.setToolTip("还原窗口")

    def _on_close(self):
        """关闭窗口"""
        self._flash_button(self._btn_close)
        win = self.window()
        if win:
            win.close()

    def _on_pin(self):
        """★ v4.7.21: 窗口置顶切换（Qt.WindowStaysOnTopHint）"""
        self._flash_button(self._btn_pin)
        win = self.window()
        if win:
            win.setWindowFlag(Qt.WindowStaysOnTopHint, self._btn_pin.isChecked())
            win.show()  # setWindowFlag 后需重显以应用

    def _on_language_changed(self, lang_code: str):
        from standard_mode.core.i18n import get_i18n, _LANGUAGE_NAMES
        i18n = get_i18n()
        if i18n.set_language(lang_code):
            new_name = _LANGUAGE_NAMES.get(lang_code, lang_code)
            if hasattr(self, '_lang_btn'):
                self._lang_btn.setText(new_name)
                for act in self._lang_btn.menu().actions():
                    f = act.font()
                    f.setBold(act.data() == lang_code)
                    act.setFont(f)
            self.language_changed.emit(lang_code)

    def _apply_agent_light_config(self):
        """★ v3.90: 从 SettingsManager 加载状态灯动画配置并应用"""
        try:
            from core.settings_manager import get_settings_manager
            sm = get_settings_manager()
            cfg = sm.get("appearance.agent_light", {}) or {}
            mode = cfg.get("animation_mode", "flow")
            speed = cfg.get("speed", 60)
            light = self.agent_status_light
            if light is not None:
                if mode in ("flow", "pulse", "blink"):
                    light.set_animation_mode(mode)
                try:
                    light.set_breath_speed(int(speed))
                except (TypeError, ValueError):
                    pass
        except Exception:
            # 配置加载失败时使用默认值，不影响标题栏渲染
            pass

    def _on_engine_mode_changed(self, mode: str):
        """引擎模式按钮点击"""
        # ★ v4.1.9: 闸门 — 若目标模式对应的开关被禁用，则降级到默认模式（native）
        try:
            from core.settings_manager import get_settings_manager
            sm = get_settings_manager()
            switches = sm.get("appearance.mode_switches", {}) or {}
            mode_to_switch = {
                "native": "native_agent_enabled",
                "host": "host_agent_enabled",
            }
            if mode in mode_to_switch and not switches.get(mode_to_switch[mode], True):
                # 目标开关关闭：降级到 native
                fallback = "native"
                print(f"[TitleBar] 模式 {mode} 已被设置禁用，降级到 {fallback}")
                self.buttons[fallback].setChecked(True)
                self._current = fallback
                self._update_style()
                self.mode_changed.emit(fallback)
                return
        except Exception as e:
            print(f"[TitleBar] 模式开关闸门检查失败: {e}")

        print(f"[TitleBar] 引擎模式切换: {mode}")
        self.mode_changed.emit(mode)

    # ★ v4.0: 自定义标题栏拖动 / 双击最大化
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos()
            self._window_start_pos = self.window().pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and getattr(self, '_drag_pos', None) is not None:
            win = self.window()
            if win.isMaximized():
                # 从最大化状态拖动时先还原，并根据鼠标相对位置定位
                ratio = event.pos().x() / max(self.width(), 1)
                win.showNormal()
                new_x = event.globalPos().x() - int(win.width() * ratio)
                new_y = event.globalPos().y() - self._drag_pos.y() + self._window_start_pos.y()
                win.move(new_x, max(new_y, 0))
                self._drag_pos = event.globalPos()
                self._window_start_pos = win.pos()
            else:
                delta = event.globalPos() - self._drag_pos
                win.move(self._window_start_pos + delta)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_maximize()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


# ============================================================
# Lemon 交互终端 — 基于 Serve Bridge 的美化终端
# ============================================================
class MIMOConsoleWidget(QWidget):
    """交互式终端：输出区 + 输入框 + 工具栏，通过 Serve Bridge 通信"""

    command_sent = pyqtSignal(str)
    session_switch = pyqtSignal(str)  # 切换会话
    model_switch = pyqtSignal(str)   # 切换模型
    clear_requested = pyqtSignal()   # 清除输出

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- 工具栏：会话/模型切换 + 操作按钮 ----
        toolbar = QFrame()
        toolbar.setFixedHeight(36)
        toolbar.setStyleSheet(f"background: {BG_SECONDARY}; border-bottom: 1px solid {BORDER_SUBTLE};")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)
        tb_layout.setSpacing(8)

        # 会话选择
        session_label = QLabel(_t("main.session"))
        session_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: {FONT_SIZE_SM};")
        tb_layout.addWidget(session_label)

        self.session_combo = QPushButton("当前会话")
        self.session_combo.setFixedHeight(26)
        self.session_combo.setToolTip("切换会话")
        self.session_combo.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 2px 10px;
                font-size: {FONT_SIZE_SM};
            }}
            QPushButton:hover {{
                border-color: {MIMO_ORANGE};
            }}
        """)
        self.session_combo.clicked.connect(self._on_session_btn)
        tb_layout.addWidget(self.session_combo)

        # 刷新会话按钮
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(26, 26)
        refresh_btn.setToolTip(_t("main.refresh_sessions"))
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: none;
                border-radius: {RADIUS_SM};
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: {BG_SURFACE};
                color: {MIMO_ORANGE};
            }}
        """)
        refresh_btn.clicked.connect(self._on_refresh_sessions)
        tb_layout.addWidget(refresh_btn)

        tb_layout.addSpacing(12)

        # 模型选择
        model_label = QLabel(_t("main.model"))
        model_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: {FONT_SIZE_SM};")
        tb_layout.addWidget(model_label)

        self.model_combo = QPushButton("—")  # ★ v4.1.14: 默认占位"—"，启动后由 set_session_info 注入真实模型名
        self.model_combo.setFixedHeight(26)
        self.model_combo.setToolTip("切换模型")
        self.model_combo.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 2px 10px;
                font-size: {FONT_SIZE_SM};
            }}
            QPushButton:hover {{
                border-color: {MIMO_ORANGE};
            }}
        """)
        self.model_combo.clicked.connect(self._on_model_btn)
        tb_layout.addWidget(self.model_combo)

        tb_layout.addStretch()

        # 新建会话按钮
        new_session_btn = QPushButton("⌂ 新建")
        new_session_btn.setFixedHeight(26)
        new_session_btn.setToolTip("新建会话 (Ctrl+N)")
        new_session_btn.setStyleSheet(f"""
            QPushButton {{
                background: {MIMO_ORANGE};
                color: white;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 2px 10px;
                font-size: {FONT_SIZE_SM};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {XIAOMI_ORANGE};
            }}
        """)
        new_session_btn.clicked.connect(self._on_new_session)
        tb_layout.addWidget(new_session_btn)
        
        # ★ P13 冗余清理: 移除"模式 ▾"按钮（模式切换由Qt标题栏引擎选择器+HTML引擎选择器统一管理）
        # ★ 集群状态指示器（v2.1 新增）
        self._cluster_indicator = QLabel("[=]")
        self._cluster_indicator.setFixedWidth(16)
        self._cluster_indicator.setToolTip("集群状态：未启动")
        self._cluster_indicator.setStyleSheet("background: transparent;")
        tb_layout.addWidget(self._cluster_indicator)

        # 清除按钮
        clear_btn = QPushButton("✕ 清除")
        clear_btn.setFixedHeight(26)
        clear_btn.setToolTip("清除输出内容")
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 2px 8px;
                font-size: {FONT_SIZE_SM};
            }}
            QPushButton:hover {{
                background: {BG_SURFACE};
                color: red;
            }}
        """)
        clear_btn.clicked.connect(self.clear_output)
        tb_layout.addWidget(clear_btn)

        layout.addWidget(toolbar)

        # ---- 输出区域 ----
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_ROOT};
                color: {TEXT_PRIMARY};
                border: none;
                padding: 10px 14px;
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_MD};
                line-height: 1.6;
                selection-background-color: rgba(255,105,0,0.3);
            }}
            QScrollBar:vertical {{
                background: {BG_PRIMARY};
                width: 8px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {BG_SURFACE};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {BORDER_DEFAULT};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)
        layout.addWidget(self.output, 1)

        # ---- 输入栏 ----
        input_bar = QFrame()
        input_bar.setFixedHeight(44)
        input_bar.setStyleSheet(f"background: {BG_SECONDARY}; border-top: 1px solid {BORDER_SUBTLE};")
        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(10, 6, 10, 6)
        input_layout.setSpacing(8)

        prompt_label = QLabel(">")
        prompt_label.setStyleSheet(f"color: {MIMO_ORANGE}; font-family: {FONT_MONO}; font-size: {FONT_SIZE_LG}; font-weight: bold;")
        prompt_label.setFixedWidth(18)
        input_layout.addWidget(prompt_label)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入消息发送给 Lemon Code...")
        # ★ v4.1.7: 记录默认 placeholder，Solo 模式退出后恢复
        self._default_input_placeholder = "输入消息发送给 Lemon Code..."
        self.input_field.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_ROOT};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
                padding: 6px 12px;
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_MD};
            }}
            QLineEdit:focus {{
                border-color: {MIMO_ORANGE};
                border-width: 2px;
            }}
        """)
        self.input_field.returnPressed.connect(self._on_send)
        input_layout.addWidget(self.input_field, 1)

        send_btn = QPushButton("▶ 发送")
        send_btn.setFixedSize(60, 32)
        send_btn.setStyleSheet(button_primary_style('md'))
        send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(send_btn)

        layout.addWidget(input_bar)

        # ---- 状态栏 ----
        status_bar = QFrame()
        status_bar.setFixedHeight(22)
        status_bar.setStyleSheet(f"background: {BG_SECONDARY}; border-top: 1px solid {BORDER_SUBTLE};")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(10, 2, 10, 2)
        status_layout.setSpacing(16)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: {FONT_SIZE_XS};")
        status_layout.addWidget(self.status_label)

        self.session_info = QLabel("")
        self.session_info.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: {FONT_SIZE_XS};")
        status_layout.addWidget(self.session_info)

        status_layout.addStretch()

        self.token_info = QLabel("")
        self.token_info.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: {FONT_SIZE_XS};")
        status_layout.addWidget(self.token_info)

        layout.addWidget(status_bar)

    def _on_send(self):
        text = self.input_field.text().strip()
        if text:
            self.input_field.clear()
            self.append_user_message(text)
            self.command_sent.emit(text)

    def append_user_message(self, text):
        safe = text.replace('<', '&lt;').replace('>', '&gt;')
        # ★ v3.88: 简笔画风格符号，替代 emoji
        # 用细线条的几何符号代替 emoji，与标准模式操控键风格一致
        self.output.append(
            f'<div style="margin:6px 0 6px 2px;">'
            f'<span style="display:inline-block;width:14px;height:14px;border:1.5px solid {XIAOMI_ORANGE};'
            f'border-radius:50%;text-align:center;line-height:11px;font-size:10px;'
            f'color:{XIAOMI_ORANGE};font-weight:700;margin-right:6px;vertical-align:middle;">▸</span>'
            f'<span style="color:{XIAOMI_ORANGE};font-weight:600;vertical-align:middle;">{safe}</span>'
            f'</div>'
        )
        self._scroll_to_bottom()

    def append_html(self, html):
        self.output.append(html)
        self._scroll_to_bottom()

    def append_text_inline(self, text):
        """在同一行内追加文本（不创建新段落，用于 delta 流式输出）"""
        cursor = self.output.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(text)
        self.output.setTextCursor(cursor)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        sb = self.output.verticalScrollBar()
        QTimer.singleShot(10, lambda: sb.setValue(sb.maximum()))

    def clear_output(self):
        self.output.clear()
        self.clear_requested.emit()

    def set_session_info(self, session_id, model_id):
        self.session_info.setText(f"会话: {session_id[:16]}...")
        self.session_combo.setText(session_id[:12] + "...")
        # ★ v4.1.14: 当 model_id 为 None/空/"auto"/"mimo-auto"(硬编码占位符) 时，
        # 不强行写入，按钮维持"—"等待真实模型名注入。
        if model_id and model_id not in ("auto", "mimo-auto"):
            self.model_combo.setText(model_id)
        elif model_id in ("auto",):
            self.model_combo.setText("自动")

    def set_token_info(self, tokens):
        if isinstance(tokens, dict):
            total = tokens.get('total', 0)
            inp = tokens.get('input', 0)
            out = tokens.get('output', 0)
            self.token_info.setText(f"Token: {total} (入{inp}/出{out})")

    def set_status(self, text):
        self.status_label.setText(text)

    def _on_new_session(self):
        self.command_sent.emit("/new")

    def _on_session_btn(self):
        """会话管理按钮 — 弹出会话列表菜单"""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {BG_SECONDARY};
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
                color: {XIAOMI_ORANGE};
            }}
            QMenu::separator {{
                height: 1px;
                background: {BORDER_SUBTLE};
                margin: 4px 8px;
            }}
        """)
        
        new_action = menu.addAction(" 新建会话")
        new_action.triggered.connect(self._on_new_session)
        new_action.setIcon(QApplication.style().standardIcon(QApplication.style().SP_FileDialogNewFolder))
        menu.addSeparator()
        
        sessions = self.serve_bridge.list_sessions()
        if sessions:
            for s in sessions[:10]:
                sid = s.get('id', '')
                title = s.get('title', '无标题')[:30]
                is_current = sid == self.serve_bridge.session_id
                prefix = "● " if is_current else "  "
                action = menu.addAction(f"{prefix}{title}")
                action.setData(sid)
                if is_current:
                    action.setEnabled(False)
                else:
                    action.triggered.connect(lambda checked, s=sid: self._switch_to_session(s))
        else:
            menu.addAction("  (无会话)").setEnabled(False)
        
        menu.addSeparator()
        refresh_action = menu.addAction("🔄 刷新会话列表")
        refresh_action.triggered.connect(lambda: self.command_sent.emit("/sessions"))
        
        # ★ 强制向上弹出：会话按钮同样位于底部工具栏，向下弹出必被截断
        menu.ensurePolished()
        menu.adjustSize()
        sh = menu.size().height()
        if sh <= 0:
            sh = max(menu.actions().__len__(), 1) * 28 + 16
        sbtn_rect = self.session_combo.rect()
        sanchor = self.session_combo.mapToGlobal(sbtn_rect.topLeft())
        sscreen = QApplication.screenAt(self.session_combo.mapToGlobal(sbtn_rect.center()))
        if sscreen is None:
            sscreen = QApplication.primaryScreen()
        sx = sanchor.x()
        sy = sanchor.y() - sh
        if sscreen is not None:
            sg = sscreen.availableGeometry()
            if sy < sg.top():
                sy = sg.top()
            if sx + menu.size().width() > sg.right():
                sx = max(sg.left(), sg.right() - menu.size().width())
        menu.exec_(QPoint(sx, sy))
    
    def _show_status(self, text):
        """显示状态提示（临时）"""
        if hasattr(self, 'output'):
            self.append_html(f'<div style="color:{XIAOMI_ORANGE};margin:4px 0;">> {text}</div>')

    def _on_model_btn(self):
        """模型选择按钮 — 弹出可用模型菜单"""
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {BG_SECONDARY};
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
                color: {XIAOMI_ORANGE};
            }}
            QMenu::separator {{
                height: 1px;
                background: {BORDER_SUBTLE};
                margin: 4px 8px;
            }}
        """)
        
        # 添加"刷新列表"操作
        refresh_action = menu.addAction("🔄 刷新模型列表")
        refresh_action.triggered.connect(lambda: self._refresh_and_show_models())
        menu.addSeparator()
        
        # 获取可用模型列表
        models = self.serve_bridge.list_models()
        if models:
            for m in models:
                mid = m.get('id', '')
                mname = m.get('name', mid)
                action = menu.addAction(f"  {mname}")
                action.setData(mid)
                action.triggered.connect(lambda checked, m=mid: self._do_switch_model(m))
        else:
            no_models = menu.addAction("  (未连接 Lemon Code)")
            no_models.setEnabled(False)
        
        # ★ 强制向上弹出：模型按钮位于底部工具栏，向下弹出必被屏幕底部截断
        # QMenu.sizeHint() 在首次渲染前可能不准确，所以用强制测量（polish + adjustSize + size）
        menu.ensurePolished()
        menu.adjustSize()
        h = menu.size().height()
        if h <= 0:
            # 兜底：按 action 数量估算（每行约 28px）
            h = max(menu.actions().__len__(), 1) * 28 + 16
        btn_rect = self.model_combo.rect()
        anchor = self.model_combo.mapToGlobal(btn_rect.topLeft())
        screen = QApplication.screenAt(self.model_combo.mapToGlobal(btn_rect.center()))
        if screen is None:
            screen = QApplication.primaryScreen()
        # 菜单顶部 y = 按钮顶部 y - 菜单高度；夹紧到屏幕可用区内
        x = anchor.x()
        y = anchor.y() - h
        if screen is not None:
            sg = screen.availableGeometry()
            if y < sg.top():
                y = sg.top()
            if x + menu.size().width() > sg.right():
                x = max(sg.left(), sg.right() - menu.size().width())
        menu.exec_(QPoint(x, y))
    
    def _refresh_and_show_models(self):
        """刷新模型列表"""
        self.bottom_panel.mimo_console.append_html(
            f'<div style="color:{TEXT_TERTIARY};margin:4px 0;">=== 可用模型 ===</div>'
        )
        models = self.serve_bridge.list_models()
        if models:
            for m in models:
                mid = m.get('id', '?')
                mname = m.get('name', mid)
                self.bottom_panel.mimo_console.append_html(
                    f'<div style="color:{TEXT_PRIMARY};margin:2px 0;padding:2px 8px;border-left:2px solid {MIMO_ORANGE};">{mid} — {mname}</div>'
                )
        else:
            self.bottom_panel.mimo_console.append_html(
                f'<div style="color:{TEXT_TERTIARY};">无法获取模型列表</div>'
            )
    
    def _do_switch_model(self, model_id):
        """执行模型切换"""
        self.serve_bridge.switch_model(model_id)
        self.model_combo.setText(model_id)
        self.bottom_panel.mimo_console.append_html(
            f'<div style="color:{Lemon.ACCENT_GREEN};margin:4px 0;">🔄 切换到模型: {model_id}</div>'
        )
        self.bottom_panel.log_output(f"[MIMO] 模型切换 → {model_id}", INFO)

    def _on_refresh_sessions(self):
        self.command_sent.emit("/refresh")


# ============================================================
# 底部 Trae 式面板
# ============================================================
class BottomPanel(QWidget):
    # ★ v4.3.8: 咩咩面板提交的命令 → 主窗口（日志 + 通用命令转发）
    miemie_task_submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # ★ v4.1.11: TerminalHost 抽象（真/假终端统一）
        self._host_native = None      # NativeTerminalHost
        self._host_intercept = None   # InterceptTerminalHost
        self._active_host = None      # 当前激活宿主
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"background: {BG_PRIMARY}; border-top: 1px solid {BORDER_SUBTLE};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标签栏
        bar = QFrame()
        bar.setFixedHeight(34)
        bar.setStyleSheet(f"background: {BG_SECONDARY}; border-bottom: 1px solid {BORDER_SUBTLE};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(4, 2, 4, 2)
        bar_layout.setSpacing(0)
        self._tabbar_layout = bar_layout  # ★ B1: 保存引用供 _refresh_tab_bar 重建

        # ★ v4.1.14: 修正 NATIVE 模式下"Lemon 终端"与"终端"重复显示的问题。
        # "终端"=真终端 (NativeTerminalHost, NATIVE 唯一使用的);
        # "Lemon 终端"=拦截终端 (InterceptTerminalHost, 仅 HOST 夺舍时使用)。
        # 因此 NATIVE 模式只显示"终端"，HOST 模式才同时显示两个。
        # 调试控制台/浏览器当前未真正工作，所有模式下隐藏以提升 IDE 感。
        # ★ W3 图标大一统：顶栏 tab 图标由 ASCII/emoji 改为 theme 极简线条 SVG。
        self._tab_defs = [
            ("终端", "terminal", {"native", "host"}),
            ("Lemon 终端", "terminal", {"host"}),
            ("输出", "list", {"native", "host"}),
            # ★ B3: Lemon Monitor 仅 HOST 模式保留
            ("Lemon Monitor", "activity", {"host"}),
            # ★ v4.2.4 / 补记17: MIEMIE 咩咩独立 Tab（与终端并列，完整的简笔画咩咩 + 风格分析）
            ("咩咩", "sheep", {"native", "host"}),
            ("调试控制台", "debug", set()),
            ("浏览器", "globe", set()),
            ("思考过程", "brain", {"native", "host"}),
            # ★ v5.0 Whitebox: 白盒化状态面板（Run/Step/ToolCall/Approval/Artifact）
            ("白盒", "tool", {"native", "host"}),
            # ★ v5.0 B-3: Git 状态实时同步面板
            ("Git", "git", {"native", "host"}),
        ]
        # B1: 动态 tab 注册（外部 add_bottom_tab 追加）
        self._dynamic_tab_defs = []
        self.tab_btns = {}
        for name, icon, modes in self._tab_defs:
            btn = QPushButton(f"  {name}")
            if icon:
                btn.setIcon(svg_to_qicon(icon, size=16, color=TEXT_TERTIARY))
                btn.setIconSize(QSize(16, 16))
            btn.setFixedHeight(28)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {TEXT_TERTIARY};
                    border: none;
                    border-radius: {RADIUS_SM};
                    padding: 0 10px;
                    font-size: {FONT_SIZE_SM};
                }}
                QPushButton:checked {{
                    background: {BG_SURFACE};
                    color: {TEXT_PRIMARY};
                    border-bottom: 2px solid {XIAOMI_ORANGE};
                }}
                QPushButton:hover:!checked {{
                    color: {TEXT_SECONDARY};
                }}
            """)
            btn.clicked.connect(lambda _, n=name: self._switch_tab(n))
            self.tab_btns[name] = btn
            bar_layout.addWidget(btn)

        bar_layout.addStretch()

        # 操作按钮
        # ★ W3 图标大一统：ASCII/unicode 符号改为 theme 极简线条 SVG。
        self._action_btns = {}
        _action_defs = [
            ("plus", "新建终端", "创建新的终端会话"),
            ("copy", "复制", "复制当前面板内容到剪贴板"),
            ("split", "分屏", "切换左右分屏布局"),
            ("cross", "清除", "清除当前面板输出"),
            ("maximize", "最大化", "最大化/还原底部面板"),
        ]
        for icon, tip, desc in _action_defs:
            btn = QPushButton("")
            btn.setIcon(svg_to_qicon(icon, size=14, color=TEXT_TERTIARY))
            btn.setIconSize(QSize(14, 14))
            btn.setFixedSize(26, 26)
            btn.setToolTip(desc)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {TEXT_TERTIARY};
                    border: none;
                    border-radius: {RADIUS_SM};
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background: {BG_SURFACE};
                    color: {XIAOMI_ORANGE};
                }}
                QPushButton:pressed {{
                    background: {LEMON_ORANGE_DARK};
                    color: #fff;
                }}
            """)
            btn.clicked.connect(lambda _, t=tip: self._on_action(t))
            self._action_btns[tip] = btn
            bar_layout.addWidget(btn)

        layout.addWidget(bar)

        # 内容区
        self.content_tabs = QTabWidget()
        self.content_tabs.tabBar().hide()
        self.content_tabs.setStyleSheet(f"""
            QTabWidget {{
                background: {BG_PRIMARY};
                border: none;
            }}
            QTabWidget::pane {{
                border: none;
                margin: 0;
            }}
        """)

        # ====== Tab 0: Lemon 交互终端（基于 Serve Bridge） ======
        self.mimo_console = MIMOConsoleWidget()
        self.content_tabs.addTab(self.mimo_console, "Lemon 终端")

        # ====== Tab 1: 多终端（支持多个独立会话） ======
        # ★ 使用简化终端（QWebChannel，无 WebSocket）— TerminalPanel 已在模块顶部导入
        
        # ★ 创建终端管理器
        try:
            from ui.terminal_manager import TerminalManager
            self.terminal_manager = TerminalManager(self)
        except ImportError:
            from standard_mode.ui.terminal_manager import TerminalManager
            self.terminal_manager = TerminalManager(self)
        
        # ★ 多终端容器
        self.terminal_tabs = QTabWidget()
        self.terminal_tabs.setTabsClosable(True)
        self.terminal_tabs.setMovable(True)
        self.terminal_tabs.tabCloseRequested.connect(self._close_terminal_tab)
        self.terminal_tabs.currentChanged.connect(self._on_terminal_tab_changed)
        self.terminal_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: {BG_PRIMARY};
            }}
            QTabBar::tab {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: none;
                border-bottom: 2px solid transparent;
                padding: 6px 12px;
                margin-right: 2px;
                font-size: {FONT_SIZE_SM};
            }}
            QTabBar::tab:selected {{
                color: {TEXT_PRIMARY};
                border-bottom: 2px solid {XIAOMI_ORANGE};
            }}
            QTabBar::tab:hover:!selected {{
                color: {TEXT_SECONDARY};
            }}
            QTabBar::close-button {{
                image: none;
                subcontrol-position: right;
                margin-right: 4px;
            }}
            QTabBar::close-button:hover {{
                background: {ERROR};
                border-radius: 2px;
            }}
        """)
        
        # ★ "+" 按钮添加新终端
        self._btn_add_terminal = QToolButton()
        self._btn_add_terminal.setText("+")
        self._btn_add_terminal.setFixedSize(26, 26)
        self._btn_add_terminal.setToolTip("新建终端")
        self._btn_add_terminal.setStyleSheet(f"""
            QToolButton {{
                background: transparent; color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_SUBTLE}; border-radius: 4px;
                font-size: 16px; font-weight: bold;
            }}
            QToolButton:hover {{ color: {XIAOMI_ORANGE}; border-color: {XIAOMI_ORANGE}; }}
        """)
        self._btn_add_terminal.clicked.connect(lambda: self._create_new_terminal())
        self.terminal_tabs.setCornerWidget(self._btn_add_terminal, Qt.TopRightCorner)
        
        # ★ 创建首个终端
        self._create_new_terminal()
        
        # ★ 向后兼容：self.terminal 指向当前激活的终端
        self.terminal = self.terminal_manager.get_active_terminal()
        if self.terminal:
            self.terminal = self.terminal.panel
        
        # 将多终端容器添加到 content_tabs
        self.content_tabs.addTab(self.terminal_tabs, "终端")
        print(f"[MainWindow] 终端 Tab 已添加，index={self.content_tabs.count()-1}", flush=True)

        # ★ B2: "问题" 面板合并入 "输出"，不再单独创建 Tab —— 诊断文本由 log_diagnostic 写入 output_view

        # ====== Tab 3: 输出 ======
        self.output_view = QTextEdit()
        self.output_view.setReadOnly(True)
        self.output_view.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_PRIMARY};
                color: {TEXT_PRIMARY};
                border: none;
                padding: 10px 14px;
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_SM};
            }}
        """)
        self.output_view.setPlaceholderText("等待输出...")
        self.content_tabs.addTab(self.output_view, "输出")

        # ★ B3: mimo_monitor 合并入 output_view——不再单独创建 QTextEdit / addTab

        # ====== Tab 5: 调试控制台 ======
        self.debug_view = QTextEdit()
        self.debug_view.setReadOnly(True)
        self.debug_view.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_PRIMARY};
                color: {TEXT_PRIMARY};
                border: none;
                padding: 10px 14px;
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_SM};
            }}
        """)
        self.debug_view.setPlaceholderText("调试控制台")
        self.content_tabs.addTab(self.debug_view, "调试控制台")

        # ====== Tab 6: 内置浏览器 ======
        from ui.web_browser_panel import WebBrowserPanel
        self.web_browser = WebBrowserPanel()
        self.content_tabs.addTab(self.web_browser, "浏览器")

        # ★ v4.2.4 / 补记17: MIEMIE 咩咩独立 Tab（在浏览器之前的位置）
        # 为了 tab_map 索引稳定，咩咩放在 tab 5（柠檬 Monitor 后），浏览器 tab 6
        try:
            from ui.miemie_panel import MiemiePanel
            self.miemie_panel = MiemiePanel()
            # ★ v4.3.8: 咩咩命令回传主窗口
            self.miemie_panel.taskSubmitted.connect(self.miemie_task_submitted.emit)
            # 注意：先 remove 已添加的浏览器，再以正确顺序重新添加
            # 实际我们把咩咩插入到 mimo_monitor（index 4）和 debug_view（index 5）之间
            self.content_tabs.removeTab(self.content_tabs.indexOf(self.web_browser))
            self.content_tabs.insertTab(5, self.miemie_panel, "咩咩")
            self.content_tabs.addTab(self.web_browser, "浏览器")
        except Exception as e:
            print(f"[BottomPanel] MiemiePanel 初始化失败（不影响其他 Tab）: {e}")
            import traceback
            traceback.print_exc()
            # 占位：空白 widget，避免 tab 索引错位
            from PyQt5.QtWidgets import QWidget as _QW
            placeholder = _QW()
            placeholder.setObjectName("miemiePlaceholder")
            self.content_tabs.insertTab(5, placeholder, "咩咩")

        # ★ Kiwi 几维鸟独立 Tab（仿咩咩，挂末尾避免重构脆弱的 tab 索引）
        try:
            from vizboard.ui.dock_widget import KiwiPanel, VizboardDockSource
            self.kiwi_panel = KiwiPanel()
            self.kiwi_dock = VizboardDockSource()
            self.kiwi_dock.bind_panel(self.kiwi_panel)
            self.content_tabs.addTab(self.kiwi_panel, "几维鸟")
        except Exception as e:
            print(f"[BottomPanel] KiwiPanel 初始化失败（不影响其他 Tab）: {e}")
            import traceback
            traceback.print_exc()
            from PyQt5.QtWidgets import QWidget as _QW
            ph = _QW()
            ph.setObjectName("kiwiPlaceholder")
            self.content_tabs.addTab(ph, "几维鸟")

        # ★ 咩咩任务看板（总指挥派发 + 流式看板，标准模式侧；挂末尾避免重构脆弱的 tab 索引）
        try:
            from ui.miemie_task_board import MiemieTaskBoard
            self.miemie_board = MiemieTaskBoard()
            self.content_tabs.addTab(self.miemie_board, "咩咩任务看板")
        except Exception as e:
            print(f"[BottomPanel] MiemieTaskBoard 初始化失败（不影响其他 Tab）: {e}")
            import traceback
            traceback.print_exc()
            from PyQt5.QtWidgets import QWidget as _QW2
            ph2 = _QW2()
            ph2.setObjectName("miemieBoardPlaceholder")
            self.content_tabs.addTab(ph2, "咩咩任务看板")
            self.miemie_board = ph2

        try:
            self.thinking_panel = ThinkingProcessPanel()
            self.content_tabs.addTab(self.thinking_panel, "思考过程")
        except Exception as e:
            print(f"[BottomPanel] ThinkingProcessPanel 初始化失败: {e}")
            from PyQt5.QtWidgets import QWidget as _QW3
            ph3 = _QW3()
            ph3.setObjectName("thinkingPlaceholder")
            self.content_tabs.addTab(ph3, "思考过程")
            self.thinking_panel = ph3

        # ★ v5.0 Whitebox: 白盒化状态面板 — 复用主窗口已有的 whitebox_panel 实例
        try:
            if hasattr(self, 'whitebox_panel') and self.whitebox_panel:
                self.content_tabs.addTab(self.whitebox_panel, "白盒")
                self.whitebox_panel.show()
            else:
                from PyQt5.QtWidgets import QWidget as _QW4
                ph4 = _QW4()
                ph4.setObjectName("whiteboxPlaceholder")
                self.content_tabs.addTab(ph4, "白盒")
        except Exception as e:
            print(f"[BottomPanel] WhiteboxPanel Tab 添加失败: {e}")

        # ★ v3.0 D-1: TrajectoryPanel 接线 — Agent事件时间线
        try:
            self.trajectory_panel = TrajectoryPanel()
            self.content_tabs.addTab(self.trajectory_panel, "轨迹")
        except Exception as e:
            print("[BottomPanel] TrajectoryPanel 初始化失败: " + str(e))
            from PyQt5.QtWidgets import QWidget as _QW5
            ph5 = _QW5()
            ph5.setObjectName("trajectoryPlaceholder")
            self.content_tabs.addTab(ph5, "轨迹")
            self.trajectory_panel = None

        # ★ v5.0 B-3: Git 状态实时同步面板
        try:
            if hasattr(self, 'git_status_panel') and self.git_status_panel:
                self.content_tabs.addTab(self.git_status_panel, "Git")
                self.git_status_panel.show()
            else:
                from PyQt5.QtWidgets import QWidget as _QW5
                ph5 = _QW5()
                ph5.setObjectName("gitPlaceholder")
                self.content_tabs.addTab(ph5, "Git")
        except Exception as e:
            print(f"[BottomPanel] GitStatusPanel Tab 添加失败: {e}")

        layout.addWidget(self.content_tabs, 1)

        # ★ B1: 为动态面板注册 tab 按钮（几维鸟/咩咩任务看板/轨迹 —— 用户在 _tab_defs 无对应按钮 → 断链）
        self._dynamic_tab_defs = [
            ("几维鸟", "bird", {"native", "host"}),
            ("咩咩任务看板", "activity", {"native", "host"}),
            ("轨迹", "brain", {"native", "host"}),
        ]
        self._refresh_tab_bar()
        self.tab_btns["Lemon 终端"].setChecked(True)

        # ★ v4.1.11: 初始化 TerminalHost（真/假终端抽象）
        try:
            from ui.terminal_host import NativeTerminalHost, InterceptTerminalHost
            self._host_native = NativeTerminalHost(self)
            self._host_intercept = InterceptTerminalHost(self)
            self._active_host = self._host_native
        except Exception as e:
            print(f"[BottomPanel] TerminalHost 初始化失败（回退原生）: {e}")
            self._active_host = None

    # ==================== Tab 切换 ====================

    def _switch_tab(self, name):
        for n, btn in self.tab_btns.items():
            btn.setChecked(n == name)
        # ★ B1: 按 content_tabs.tabText(i) 遍历构建 tab_map，索引变动也不会出错
        #   注：Lemon Monitor 已合并入"输出"(B3)，在 content_tabs 中实际已不存在对应页，
        #   若点击该按钮 → 映射到"输出"index。
        tab_map = {}
        for i in range(self.content_tabs.count()):
            txt = self.content_tabs.tabText(i)
            if txt:
                tab_map[txt] = i
        # B3: "Lemon Monitor" 按钮 → 切到"输出"
        target = name
        if name == "Lemon Monitor":
            target = "输出"
        self.content_tabs.setCurrentIndex(tab_map.get(target, 0))

    def set_mode(self, mode_id: str):
        """按 NATIVE/HOST 模式显示/隐藏底部标签页（含动态 tab）"""
        compat_map = {"lemoncode": "native", "agent": "host", "solo": "host", "code": "native"}
        mode = compat_map.get(mode_id, mode_id)
        # ★ B1: 合并静态 + 动态 tab 定义
        all_defs = self._tab_defs + self._dynamic_tab_defs
        all_order = [t[0] for t in all_defs]
        visible_names = set()
        for name, icon, modes in all_defs:
            btn = self.tab_btns.get(name)
            if not btn:
                continue
            visible = mode in modes
            btn.setVisible(visible)
            if visible:
                visible_names.add(name)
        # 若当前选中 tab 在当前模式下被隐藏，切到第一个可见 tab
        current_name = None
        for n, btn in self.tab_btns.items():
            if btn.isChecked() and n in visible_names:
                current_name = n
                break
        if current_name is None and visible_names:
            first = sorted(visible_names, key=lambda n: all_order.index(n))[0]
            self._switch_tab(first)

    def _on_action(self, action):
        # 按钮橙色闪烁反馈
        btn = self._action_btns.get(action)
        if btn:
            self._flash_action_btn(btn)

        if action == "新建终端":
            """创建新的终端会话"""
            self._create_new_terminal()
            self.log_output("[终端] 已创建新终端", XIAOMI_ORANGE)

        elif action == "清除":
            # B2/B3: 直接用 currentWidget() 而不依赖脆弱的逐索引映射
            w = self.content_tabs.currentWidget()
            if w:
                if hasattr(w, 'clear_output'):
                    w.clear_output()
                elif hasattr(w, 'output'):
                    w.output.clear()
                elif hasattr(w, 'clear_buffer'):
                    w.clear_buffer()
                elif hasattr(w, 'clear'):
                    w.clear()

        elif action == "复制":
            """复制当前面板内容到剪贴板"""
            text = ""
            w = self.content_tabs.currentWidget()
            if w:
                if hasattr(w, 'toPlainText'):
                    text = w.toPlainText()
                elif hasattr(w, 'output') and hasattr(w.output, 'toPlainText'):
                    text = w.output.toPlainText()
                elif hasattr(w, 'get_text'):
                    text = w.get_text()
            if text:
                QApplication.clipboard().setText(text)
                self.log_output("[操作] 已复制到剪贴板", XIAOMI_ORANGE)
            else:
                self.log_output("[操作] 当前面板无文本可复制", TEXT_TERTIARY)

        elif action == "分屏":
            """切换左右分屏布局"""
            win = self.window()
            if not win:
                return
            # 查找水平分割器
            h_splitter = self._find_h_splitter(win)
            if h_splitter:
                sizes = h_splitter.sizes()
                if len(sizes) >= 3:
                    # 切换：编辑器占大部分 vs 三等分
                    total = sum(sizes)
                    if sizes[1] < total * 0.4:
                        # 当前编辑器小 → 放大编辑器
                        h_splitter.setSizes([total // 6, total * 2 // 3, total // 6])
                        self.log_output("[操作] 分屏：编辑器放大", XIAOMI_ORANGE)
                    else:
                        # 当前编辑器大 → 三等分
                        h_splitter.setSizes([total // 3, total // 3, total // 3])
                        self.log_output("[操作] 分屏：三等分布局", XIAOMI_ORANGE)
            else:
                self.log_output("[操作] 未找到分屏分割器", TEXT_TERTIARY)

        elif action == "最大化":
            """最大化/还原底部面板"""
            win = self.window()
            if not win:
                return
            v_splitter = self._find_v_splitter(win)
            if v_splitter:
                sizes = v_splitter.sizes()
                if len(sizes) >= 2:
                    total = sum(sizes)
                    if sizes[1] < total * 0.5:
                        # 当前底部小 → 最大化底部
                        v_splitter.setSizes([total // 5, total * 4 // 5])
                        self.log_output("[操作] 底部面板最大化", XIAOMI_ORANGE)
                    else:
                        # 当前底部大 → 还原
                        v_splitter.setSizes([total * 3 // 5, total * 2 // 5])
                        self.log_output("[操作] 底部面板还原", XIAOMI_ORANGE)
            else:
                self.log_output("[操作] 未找到垂直分割器", TEXT_TERTIARY)

    def _flash_action_btn(self, btn):
        """操作按钮点击橙色闪烁"""
        original = btn.styleSheet()
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {XIAOMI_ORANGE};
                color: #fff;
                border: none;
                border-radius: {RADIUS_SM};
                font-size: 12px;
            }}
        """)
        QTimer.singleShot(200, lambda: btn.setStyleSheet(original))

    def _find_h_splitter(self, root):
        """在窗口中查找水平 QSplitter"""
        from PyQt5.QtWidgets import QSplitter
        for child in root.findChildren(QSplitter):
            if child.orientation() == Qt.Horizontal:
                return child
        return None

    def _find_v_splitter(self, root):
        """在窗口中查找垂直 QSplitter"""
        from PyQt5.QtWidgets import QSplitter
        for child in root.findChildren(QSplitter):
            if child.orientation() == Qt.Vertical:
                return child
        return None

    def log_output(self, text, color=None):
        if color:
            self.output_view.append(f'<span style="color:{color};">{text}</span>')
        else:
            self.output_view.append(text)

    # ★ B2: 诊断面板合并入输出 — 黄色 [诊断] 前缀
    def log_diagnostic(self, text):
        """向 output_view 追加 [诊断] 前缀文本（黄色 #f1c40f）"""
        self.output_view.append(f'<span style="color:#f1c40f;">[诊断] {text}</span>')

    # ★ B1: 刷新底部 tab 按钮栏（移除 _tabbar_layout 所有按钮，按 _tab_defs + _dynamic_tab_defs 重建）
    def _refresh_tab_bar(self):
        layout = self._tabbar_layout
        # 暂存 action 按钮 / stretch，刷新后重新追加
        action_btns = list(self._action_btns.values())
        # 移除布局中所有子项
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None and w not in action_btns:
                w.deleteLater()
        self.tab_btns.clear()
        # 合并定义并重建
        for name, icon, modes in self._tab_defs + self._dynamic_tab_defs:
            btn = QPushButton(f"  {name}")
            if icon:
                btn.setIcon(svg_to_qicon(icon, size=16, color=TEXT_TERTIARY))
                btn.setIconSize(QSize(16, 16))
            btn.setFixedHeight(28)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {TEXT_TERTIARY};
                    border: none;
                    border-radius: {RADIUS_SM};
                    padding: 0 10px;
                    font-size: {FONT_SIZE_SM};
                }}
                QPushButton:checked {{
                    background: {BG_SURFACE};
                    color: {TEXT_PRIMARY};
                    border-bottom: 2px solid {XIAOMI_ORANGE};
                }}
                QPushButton:hover:!checked {{
                    color: {TEXT_SECONDARY};
                }}
            """)
            btn.clicked.connect(lambda _, n=name: self._switch_tab(n))
            self.tab_btns[name] = btn
            layout.addWidget(btn)
        layout.addStretch()
        # 重新挂载 action 按钮
        for ab in action_btns:
            ab.setParent(self)
            layout.addWidget(ab)

    # ★ B1: 供外部调用 — 动态添加一个底部 tab 并刷新按钮栏
    def add_bottom_tab(self, widget, name, icon="list", modes=None):
        """外部调用：content_tabs.addTab + 注册 _dynamic_tab_defs + 刷新按钮栏。

        Args:
            widget: 要嵌入的 QWidget
            name:   tab 文本（必须唯一）
            icon:   按钮 SVG 图标名（theme key），默认 "list"
            modes:  可见模式集合，默认 {"native", "host"}
        """
        if modes is None:
            modes = {"native", "host"}
        self.content_tabs.addTab(widget, name)
        self._dynamic_tab_defs.append((name, icon, modes))
        self._refresh_tab_bar()

    # ================================================================
    # ★ v3.65: 假终端模式（夺舍模式专用）
    # ================================================================
    def set_fake_terminal_mode(self, enabled: bool, agent_name: str = "外部 Agent"):
        """★ v3.65 / ★ v4.1.11: 切换假终端模式（委托 TerminalHost）

        原生 Agent 模式（enabled=False）：
            - "Lemon 终端" tab 显示真终端，用户可输入
            - 状态横幅隐藏
        夺舍模式（enabled=True）：
            - "Lemon 终端" tab 显示拦截的外部 Agent 输出（只读）
            - 终端输入框禁用
            - 显示紫色状态横幅"⚠ 拦截模式:显示 {agent_name} 输出"
            - 自动切换到 "Lemon 终端" tab
        """
        try:
            self._fake_terminal_mode = enabled
            self._intercept_agent_name = agent_name

            # ★ v4.1.11: 委托 TerminalHost（失败则回退旧逻辑）
            if self._active_host is not None:
                if enabled:
                    if self._host_intercept is not None:
                        self._host_intercept.activate(agent_name)
                        self._active_host = self._host_intercept
                        return
                else:
                    if self._host_intercept is not None:
                        self._host_intercept.deactivate()
                        self._active_host = self._host_native
                        return
        except Exception as e:
            print(f"[BottomPanel] TerminalHost 委托失败，回退旧逻辑: {e}")
        self._legacy_set_fake_terminal_mode(enabled, agent_name)

    def _legacy_set_fake_terminal_mode(self, enabled: bool, agent_name: str = "外部 Agent"):
        """旧版假终端切换（TerminalHost 不可用时的回退）"""
        try:
            # 创建/获取拦截横幅
            if not hasattr(self, '_intercept_banner'):
                self._intercept_banner = QLabel()
                self._intercept_banner.setFixedHeight(22)
                self._intercept_banner.setAlignment(Qt.AlignCenter)
                self._intercept_banner.setStyleSheet(f"""
                    background: {Lemon.ACCENT_PURPLE};
                    color: {Lemon.BG};
                    font-size: 11px;
                    font-weight: 600;
                    border: none;
                """)
                # 插入到标签栏和内容区之间
                self.layout().insertWidget(1, self._intercept_banner)

            if enabled:
                self._intercept_banner.setText(
                    f"⚠ 拦截模式：显示 {agent_name} 输出（二次处理已启用）"
                )
                self._intercept_banner.show()
                if "Lemon 终端" in self.tab_btns:
                    self.tab_btns["Lemon 终端"].setText("  L>_  Lemon 终端 (拦截)")
                if hasattr(self.mimo_console, 'input_field'):
                    self.mimo_console.input_field.setPlaceholderText(
                        f"拦截模式：{agent_name} 输出只读"
                    )
                    self.mimo_console.input_field.setReadOnly(True)
                if "终端" in self.tab_btns:
                    self.tab_btns["终端"].setEnabled(False)
                    self.tab_btns["终端"].setToolTip(
                        "夺舍模式下真终端已禁用，请使用 Lemon 终端查看拦截输出"
                    )
                self._switch_tab("Lemon 终端")
                self.log_output(
                    f"[夺舍] 假终端模式已启用，拦截 {agent_name} 输出",
                    Lemon.ACCENT_PURPLE
                )
            else:
                self._intercept_banner.hide()
                if "Lemon 终端" in self.tab_btns:
                    self.tab_btns["Lemon 终端"].setText("  L>_  Lemon 终端")
                if hasattr(self.mimo_console, 'input_field'):
                    self.mimo_console.input_field.setPlaceholderText("输入消息...")
                    self.mimo_console.input_field.setReadOnly(False)
                if "终端" in self.tab_btns:
                    self.tab_btns["终端"].setEnabled(True)
                    self.tab_btns["终端"].setToolTip("")
                self.log_output(
                    "[夺舍] 假终端模式已禁用，恢复真终端",
                    XIAOMI_ORANGE
                )
        except Exception as e:
            print(f"[BottomPanel] _legacy_set_fake_terminal_mode 失败: {e}")

    def is_fake_terminal_mode(self) -> bool:
        """★ v3.65: 是否处于假终端模式"""
        # ★ v4.1.11: 优先用 host 判断
        if self._active_host is not None:
            return self._active_host.get_mode_id() == "intercept"
        return getattr(self, '_fake_terminal_mode', False)

    def append_intercepted_output(self, text: str, source: str = "agent"):
        """★ v3.65 / ★ v4.1.11: 追加拦截的外部 Agent 输出到 Lemon 终端

        Args:
            text: 拦截到的文本
            source: 来源标识（"agent" / "tool" / "thinking" / "status"）
        """
        # ★ v4.1.11: 委托当前宿主
        if self._active_host is not None:
            self._active_host.append_output(text, source)
            return
        # 回退旧逻辑
        try:
            source_styles = {
                "agent": f"color: {Lemon.ACCENT_BLUE};",
                "tool": f"color: {Lemon.BRAND_ORANGE_LIGHT};",
                "thinking": f"color: {Lemon.ACCENT_PURPLE}; font-style: italic;",
                "status": f"color: {Lemon.ACCENT_GREEN};",
            }
            style = source_styles.get(source, f"color: {Lemon.BORDER_HOVER};")
            prefix_map = {
                "agent": "[Agent]",
                "tool": "[Tool]",
                "thinking": "[思考]",
                "status": "[状态]",
            }
            prefix = prefix_map.get(source, "[拦截]")
            html = f'<div style="{style}">{prefix} {text}</div>'
            if hasattr(self.mimo_console, 'append_html'):
                self.mimo_console.append_html(html)
        except Exception as e:
            print(f"[BottomPanel] append_intercepted_output 失败: {e}")

    def update_diagnostics(self, file_path: str, diagnostics: list):
        """★ B2: 诊断信息写入 output_view（取代已移除的问题面板）— 实时显示 LSP 诊断

        Args:
            file_path: 文件路径
            diagnostics: [Diagnostic] 列表
        """
        fname = os.path.basename(file_path)
        errors = sum(1 for d in diagnostics if getattr(d, 'severity', 1) == 1)
        warnings = sum(1 for d in diagnostics if getattr(d, 'severity', 1) == 2)
        # 汇总摘要
        if errors == 0 and warnings == 0:
            self.log_diagnostic(f"{fname}: 无问题")
            return
        # 详细行（纯文本）
        detail_parts = [f"{fname}: {errors} 错误, {warnings} 警告"]
        for diag in diagnostics:
            severity = getattr(diag, 'severity', 1)
            message = getattr(diag, 'message', '')
            line_num = getattr(diag.range.start, 'line', 0) + 1
            col = getattr(diag.range.start, 'character', 0) + 1
            source = getattr(diag, 'source', '') or 'LSP'
            tag = 'E' if severity == 1 else 'W' if severity == 2 else 'I'
            detail_parts.append(f"  L{line_num}:{col} [{source}/{tag}] {message}")
        self.log_diagnostic("\n".join(detail_parts))

    def _create_new_terminal(self, name: str = None, cwd: str = None):
        panel = TerminalPanel()
        if cwd:
            panel.set_cwd(cwd)
        term_id = self.terminal_manager.create_terminal(name=name, cwd=cwd)
        instance = self.terminal_manager.get_terminal(term_id)
        if instance:
            instance.panel = panel
            index = self.terminal_tabs.addTab(panel, instance.name)
            self.terminal_tabs.setCurrentIndex(index)
            self.terminal = panel

    def _close_terminal_tab(self, index: int):
        panel = self.terminal_tabs.widget(index)
        term_id = None
        for tid, instance in self.terminal_manager._terminals.items():
            if instance.panel == panel:
                term_id = tid
                break
        if term_id:
            self.terminal_tabs.removeTab(index)
            self.terminal_manager.close_terminal(term_id)
            if self.terminal_manager.get_terminal_count() == 0:
                self._create_new_terminal()
            active = self.terminal_manager.get_active_terminal()
            self.terminal = active.panel if active else None

    def _on_terminal_tab_changed(self, index: int):
        if index < 0:
            return
        panel = self.terminal_tabs.widget(index)
        for tid, instance in self.terminal_manager._terminals.items():
            if instance.panel == panel:
                self.terminal_manager.switch_terminal(tid)
                self.terminal = panel
                break


# ============================================================
# 命令面板
# ============================================================
class CommandPalette(QDialog):
    """Ctrl+Shift+P 命令面板 — 快速搜索和执行命令"""

    COMMANDS = [
        # (id, label, description, category)
        ("explorer.focus_search", ">_ 聚焦文件搜索", "在左侧资源管理器中搜索文件", "导航"),
        ("explorer.collapse_all", "v 折叠全部文件夹", "折叠资源管理器中的所有文件夹", "导航"),
        ("explorer.recent_files", "[] 最近打开的文件", "显示最近打开的文件列表", "导航"),
        ("explorer.go_to_line", "# 跳转到指定行", "跳转到当前编辑器的指定行号 (Ctrl+G)", "导航"),
        ("terminal.clear", "✕ 清除终端输出", "清除当前终端面板的所有输出", "终端"),
        ("terminal.new_session", "⌂ 新建会话", "创建新的 Lemon Code 会话", "LM"),
        ("terminal.show_usage", "=% 查看用量", "显示当前 Token 用量信息", "LM"),
        ("terminal.show_info", "i 会话信息", "显示当前会话详细信息", "LM"),
        ("terminal.cancel_task", "[] 取消当前任务", "取消正在执行的 Lemon Code 任务", "LM"),
        ("terminal.command_history", "~ 命令历史", "查看最近发送的命令历史", "终端"),
        ("mode.switch_single", "[.] 单窗口模式", "切换到单窗口模式", "模式"),
        ("mode.switch_terminal", "[_] 纯终端模式", "隐藏右侧面板，专注编码", "模式"),
        ("mode.switch_demo", "[=] 演示模式", "隐藏底部终端，可视化展示", "模式"),
        ("mode.switch_hybrid", ">< 混合 AI 模式", "Lemon + Ollama 协同算力", "模式"),
        ("mode.build", "/\\ Build 模式", "切换到 Build Agent 模式", "Agent"),
        ("mode.plan", "|| Plan 模式", "切换到 Plan Agent 模式", "Agent"),
        ("mode.compose", "// Compose 模式", "切换到 Compose Agent 模式", "Agent"),
        ("view.search_global", "? 全局搜索文件", "在所有项目文件中搜索文本", "搜索"),
        ("view.command_palette", ": 命令面板", "打开命令面板", "搜索"),
        ("git.status", "=% Git 状态", "查看当前 Git 仓库状态", "Git"),
        ("git.commit", "* Git Commit", "提交暂存的更改", "Git"),
        ("git.push", "^ Git Push", "推送到远程仓库", "Git"),
        ("git.pull", "v Git Pull", "从远程仓库拉取", "Git"),
        ("git.log", "~ Git Log", "查看最近提交记录", "Git"),
        ("code.review", ">_ 代码审查", "使用本地 Ollama 模型审查当前文件", "代码"),
        ("code.review_selected", "|| 审查当前编辑器文件", "审查当前打开的编辑器文件", "代码"),
        ("cluster.start_full", ">> 启动完整集群 (5实例)", "启动 Director + 4 Workers", "集群"),
        ("cluster.start_minimal", "> 启动最小模式 (2实例)", "启动 Director + 1 Worker", "集群"),
        ("cluster.stop", "[] 停止所有实例", "停止所有运行的 Lemon Code 实例", "集群"),
        ("cluster.toggle_grid", "## 切换网格视图", "显示/隐藏多实例网格面板", "集群"),
        ("cluster.status", "=% 集群状态", "查看当前集群运行状态", "集群"),
        ("help.show_shortcuts", "? 快捷键帮助", "显示所有可用快捷键", "帮助"),
        ("report.distillation", "=% 查看蒸馏报告", "查看 MIMO Code vs Lemon Code 蒸馏对标报告", "报告"),
        ("report.innovation", "* 创新清单", "查看 Lemon Code 独有创新功能清单", "报告"),
        ("report.health", "+ 项目健康仪表盘", "查看依赖状态/错误趋势/Agent负载/质量评分", "报告"),
        ("config.import", "v 导入配置文件", "从 JSON/YAML/TOML/INI 文件导入配置", "配置"),
        ("config.role", " 角色配置", "打开 Agent 角色配置对话框", "配置"),
        ("role.coder", " 切换代码专家", "设置 Agent 角色为代码专家（擅长编码）", "角色"),
        ("role.analyst", " 切换分析师", "设置 Agent 角色为分析师（擅长分析）", "角色"),
        ("role.writer", " 切换写作专家", "设置 Agent 角色为写作专家（擅长文档）", "角色"),
        ("role.assistant", " 切换助手", "设置 Agent 角色为助手（通用助手）", "角色"),
        ("vote.start", "x 发起投票", "发起 Agent 投票决策", "决策"),
        ("vote.history", "|| 投票历史", "查看历史投票记录和结果", "决策"),
        ("skills.browse", "/\\ Skill 浏览", "查看和手动触发已注册 Skill", "工具"),
        ("tools.engine_dispatch", "◇ 引擎智能调度诊断", "查看引擎无关调度器可用引擎与统计（SmartDispatcher）", "工具"),
        ("plugin.market", "[] 插件市场", "浏览、启用/禁用、卸载插件", "工具"),
        ("miemie.analyze", "♡ MIEMIE代码分身分析", "分析当前项目代码风格，生成代码分身配置", "MIEMIE"),
        ("miemie.profile", "♡ MIEMIE分身卡片", "查看已生成的MIEMIE代码分身卡片", "MIEMIE"),
        ("web.browser", " 内置浏览器", "打开内置浏览器，浏览网页/API官网", "工具"),
    ]

    command_triggered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self.setWindowTitle("命令面板")
        self.setMinimumSize(500, 400)
        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_PRIMARY};
                color: {TEXT_PRIMARY};
                font-family: {FONT_SYSTEM};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_XL};
            }}
        """)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 搜索输入框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入命令名称搜索... (↑↓ 选择, Enter 执行, Esc 关闭)")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_ROOT};
                color: {TEXT_PRIMARY};
                border: none;
                border-bottom: 1px solid {BORDER_DEFAULT};
                border-radius: 0;
                padding: 14px 18px;
                font-size: {FONT_SIZE_MD};
                font-family: {FONT_SYSTEM};
            }}
            QLineEdit:focus {{
                border-color: {XIAOMI_ORANGE};
            }}
        """)
        self.search_input.textChanged.connect(self._on_filter)
        self.search_input.returnPressed.connect(self._on_execute)
        layout.addWidget(self.search_input)

        # 命令列表
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {BG_PRIMARY};
                color: {TEXT_PRIMARY};
                border: none;
                font-size: {FONT_SIZE_BASE};
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px 18px;
                border-bottom: 1px solid {BORDER_SUBTLE};
            }}
            QListWidget::item:hover {{
                background: {BG_SURFACE};
            }}
            QListWidget::item:selected {{
                background: {BG_SURFACE_HOVER};
                border-left: 3px solid {XIAOMI_ORANGE};
            }}
        """)
        self.list_widget.itemClicked.connect(self._on_execute)
        self.list_widget.itemDoubleClicked.connect(self._on_execute)
        self.list_widget.itemActivated.connect(self._on_execute)
        layout.addWidget(self.list_widget, 1)

        # 底部提示
        hint = QLabel("↑↓ 选择  |  Enter 执行  |  Esc 关闭")
        hint.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: {FONT_SIZE_XS}; padding: 8px 18px; background: {BG_SECONDARY};")
        layout.addWidget(hint)

        self._populate_list()

    def _populate_list(self, filter_text=""):
        self.list_widget.clear()
        lower = filter_text.lower().strip() if filter_text else ""
        for cmd_id, label, desc, category in self.COMMANDS:
            if lower:
                if lower not in label.lower() and lower not in desc.lower() and lower not in category.lower() and lower not in cmd_id.lower():
                    continue
            item = QListWidgetItem(f"{label}")
            item.setData(Qt.UserRole, cmd_id)
            item.setToolTip(f"{desc} ({category})")
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _on_filter(self, text):
        self._populate_list(text)

    def _on_execute(self, item=None):
        """执行命令 — 支持信号传参和 currentItem 两种方式"""
        if item is None:
            item = self.list_widget.currentItem()
        if item:
            cmd_id = item.data(Qt.UserRole)
            self.command_triggered.emit(cmd_id)
            self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self.search_input.setFocus()
        self.search_input.selectAll()


# ============================================================
# 多会话并行面板 — 多 Lemon Code 窗口协同
# ============================================================
class MultiSessionPanel(QWidget):
    """多会话并行面板 — Tab 式多窗口管理"""
    
    session_selected = pyqtSignal(str)     # 用户选择会话
    session_close_requested = pyqtSignal(str)  # 用户请求关闭会话
    new_session_requested = pyqtSignal()   # 用户请求新建会话
    send_to_session = pyqtSignal(str, str) # (session_id, message)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._session_widgets: dict = {}  # {session_id: QWidget}
        self._init_ui()
    
    def _init_ui(self):
        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 工具栏
        toolbar = QFrame()
        toolbar.setFixedHeight(36)
        toolbar.setStyleSheet(f"background: {BG_SECONDARY}; border-bottom: 1px solid {BORDER_SUBTLE};")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 4, 10, 4)
        tb_layout.setSpacing(8)
        
        title = QLabel(">< 多会话并行")
        title.setStyleSheet(f"color: {MIMO_ORANGE}; font-size: {FONT_SIZE_SM}; font-weight: 700; background: transparent;")
        tb_layout.addWidget(title)
        
        self.session_count_label = QLabel("0 个会话")
        self.session_count_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: {FONT_SIZE_XS}; background: transparent;")
        tb_layout.addWidget(self.session_count_label)
        
        tb_layout.addStretch()
        
        new_btn = QPushButton("+ 新建会话")
        new_btn.setFixedHeight(26)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: {MIMO_ORANGE};
                color: white;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 2px 10px;
                font-size: {FONT_SIZE_XS};
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {XIAOMI_ORANGE}; }}
        """)
        new_btn.clicked.connect(self.new_session_requested.emit)
        tb_layout.addWidget(new_btn)
        
        layout.addWidget(toolbar)
        
        # 会话 Tab 区
        self.session_tabs = QTabWidget()
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.setMovable(True)
        self.session_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background: {BG_ROOT};
                border: none;
            }}
            QTabBar::tab {{
                background: {BG_SECONDARY};
                color: {TEXT_TERTIARY};
                border: none;
                border-radius: 0;
                padding: 6px 16px;
                font-size: {FONT_SIZE_XS};
                min-width: 100px;
                margin-right: 1px;
            }}
            QTabBar::tab:selected {{
                background: {BG_PRIMARY};
                color: {MIMO_ORANGE};
                border-bottom: 2px solid {MIMO_ORANGE};
            }}
            QTabBar::tab:hover {{
                color: {TEXT_PRIMARY};
            }}
        """)
        self.session_tabs.tabCloseRequested.connect(self._on_tab_close)
        self.session_tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.session_tabs, 1)
        
        # 底部状态栏
        status_bar = QFrame()
        status_bar.setFixedHeight(24)
        status_bar.setStyleSheet(f"background: {BG_SECONDARY}; border-top: 1px solid {BORDER_SUBTLE};")
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(10, 2, 10, 2)
        
        self.status_text = QLabel("就绪")
        self.status_text.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: {FONT_SIZE_XS}; background: transparent;")
        sb_layout.addWidget(self.status_text)
        
        sb_layout.addStretch()
        layout.addWidget(status_bar)
    
    def add_session(self, session_id: str, name: str, role: str = "general"):
        """添加会话 Tab"""
        if session_id in self._session_widgets:
            return
        
        # 创建会话内容 widget
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        # 会话输出区
        output = QTextEdit()
        output.setReadOnly(True)
        output.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_ROOT};
                color: {TEXT_PRIMARY};
                border: none;
                padding: 8px 12px;
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_SM};
            }}
        """)
        output.setPlaceholderText(f"会话 {name} — 等待任务...")
        content_layout.addWidget(output, 1)
        
        # 输入栏
        input_bar = QFrame()
        input_bar.setFixedHeight(38)
        input_bar.setStyleSheet(f"background: {BG_SECONDARY}; border-top: 1px solid {BORDER_SUBTLE};")
        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(8, 4, 8, 4)
        input_layout.setSpacing(6)
        
        input_field = QLineEdit()
        input_field.setPlaceholderText(f"向 {name} 发送消息...")
        input_field.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_ROOT};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 4px 10px;
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_SM};
            }}
            QLineEdit:focus {{ border-color: {MIMO_ORANGE}; }}
        """)
        input_field.returnPressed.connect(
            lambda sid=session_id, inp=input_field: self._on_send(sid, inp)
        )
        input_layout.addWidget(input_field, 1)
        
        send_btn = QPushButton("发送")
        send_btn.setFixedSize(50, 28)
        send_btn.setStyleSheet(button_primary_style('sm'))
        send_btn.clicked.connect(
            lambda sid=session_id, inp=input_field: self._on_send(sid, inp)
        )
        input_layout.addWidget(send_btn)
        
        content_layout.addWidget(input_bar)
        
        # 存储 widget 引用
        role_icon = {"build": "/\\", "plan": "||", "compose": "//", "general": "#"}.get(role, "#")
        tab_name = f"{role_icon} {name}"
        idx = self.session_tabs.addTab(content, tab_name)
        self.session_tabs.setCurrentIndex(idx)
        
        self._session_widgets[session_id] = {
            "widget": content,
            "output": output,
            "input": input_field,
            "name": name,
            "role": role,
        }
        
        self._update_count()
    
    def remove_session(self, session_id: str):
        """移除会话 Tab"""
        if session_id not in self._session_widgets:
            return
        
        # 找到对应的 tab 索引
        for i in range(self.session_tabs.count()):
            if self.session_tabs.widget(i) == self._session_widgets[session_id]["widget"]:
                self.session_tabs.removeTab(i)
                break
        
        del self._session_widgets[session_id]
        self._update_count()
    
    def append_output(self, session_id: str, text: str):
        """向指定会话追加输出"""
        if session_id in self._session_widgets:
            output = self._session_widgets[session_id]["output"]
            output.append(text)
            # 滚动到底部
            sb = output.verticalScrollBar()
            QTimer.singleShot(10, lambda: sb.setValue(sb.maximum()))
    
    def set_session_state(self, session_id: str, state: str):
        """更新会话状态显示"""
        if session_id in self._session_widgets:
            info = self._session_widgets[session_id]
            state_icon = {
                "idle": "[]", "busy": "...", "thinking": "?",
                "error": "x", "disconnected": "[]"
            }.get(state, "?")
            
            # 更新 tab 名称
            for i in range(self.session_tabs.count()):
                if self.session_tabs.widget(i) == info["widget"]:
                    role_icon = {"build": "/\\", "plan": "||", "compose": "//", "general": "#"}.get(info["role"], "#")
                    self.session_tabs.setTabText(i, f"{state_icon} {role_icon} {info['name']}")
                    break
    
    def set_active_session(self, session_id: str):
        """设置活动会话"""
        if session_id in self._session_widgets:
            info = self._session_widgets[session_id]
            for i in range(self.session_tabs.count()):
                if self.session_tabs.widget(i) == info["widget"]:
                    self.session_tabs.setCurrentIndex(i)
                    break
    
    def _on_send(self, session_id: str, input_field: QLineEdit):
        """发送消息到指定会话"""
        text = input_field.text().strip()
        if text:
            input_field.clear()
            self.send_to_session.emit(session_id, text)
    
    def _on_tab_close(self, index: int):
        """关闭会话 Tab"""
        widget = self.session_tabs.widget(index)
        for sid, info in list(self._session_widgets.items()):
            if info["widget"] == widget:
                self.session_close_requested.emit(sid)
                break
    
    def _on_tab_changed(self, index: int):
        """切换会话 Tab"""
        if index >= 0:
            widget = self.session_tabs.widget(index)
            for sid, info in self._session_widgets.items():
                if info["widget"] == widget:
                    self.session_selected.emit(sid)
                    break
    
    def _update_count(self):
        """更新会话计数"""
        count = len(self._session_widgets)
        self.session_count_label.setText(f"{count} 个会话")
        self.status_text.setText(f"共 {count} 个并行会话")
    
    def clear_all(self):
        """清除所有会话"""
        self.session_tabs.clear()
        self._session_widgets.clear()
        self._update_count()
    
    # ============================================================
    # ★ 多终端支持
    # ============================================================
    def _create_new_terminal(self, name: str = None, cwd: str = None):
        """创建新终端"""
        # 创建终端面板
        panel = TerminalPanel()
        if cwd:
            panel.set_cwd(cwd)
        
        # 通过管理器创建终端实例
        term_id = self.terminal_manager.create_terminal(name=name, cwd=cwd)
        instance = self.terminal_manager.get_terminal(term_id)
        
        if instance:
            # 绑定面板
            instance.panel = panel
            
            # 添加到 Tab
            index = self.terminal_tabs.addTab(panel, instance.name)
            self.terminal_tabs.setCurrentIndex(index)
            
            # 更新向后兼容引用
            self.terminal = panel
            
            print(f"[BottomPanel] 创建终端: {term_id} ({instance.name})", flush=True)
    
    def _close_terminal_tab(self, index: int):
        """关闭终端 Tab"""
        panel = self.terminal_tabs.widget(index)
        
        # 查找对应的终端 ID
        term_id = None
        for tid, instance in self.terminal_manager._terminals.items():
            if instance.panel == panel:
                term_id = tid
                break
        
        if term_id:
            # 移除 Tab
            self.terminal_tabs.removeTab(index)
            
            # 关闭终端（会清理资源）
            self.terminal_manager.close_terminal(term_id)
            
            # 如果没有终端了，创建一个新的
            if self.terminal_manager.get_terminal_count() == 0:
                self._create_new_terminal()
            
            # 更新向后兼容引用
            active = self.terminal_manager.get_active_terminal()
            self.terminal = active.panel if active else None
            
            print(f"[BottomPanel] 关闭终端: {term_id}", flush=True)
    
    def _on_terminal_tab_changed(self, index: int):
        """终端 Tab 切换"""
        if index < 0:
            return
        
        panel = self.terminal_tabs.widget(index)
        
        # 查找对应的终端 ID
        for tid, instance in self.terminal_manager._terminals.items():
            if instance.panel == panel:
                self.terminal_manager.switch_terminal(tid)
                # 更新向后兼容引用
                self.terminal = panel
                break


# ============================================================
# 主窗口
# ============================================================
class MIMOWindow(QMainWindow):
    # 用于跨线程通知显示窗口的信号
    _request_show = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lemon Work")
        # ★ v5.0 C-1: 全局异常钩子 — 防崩溃与优雅降级
        import sys as _sys
        _orig_excepthook = _sys.excepthook
        def _global_exception_handler(exc_type, exc_value, exc_tb):
            import traceback, os, time
            tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            log_dir = os.path.expanduser("~/.lemoncode/logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "crash.log")
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{'='*60}\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{tb_text}\n")
            except Exception:
                pass
            try:
                print(f"[CRASH] {tb_text}", flush=True)
            except Exception:
                pass  # ★ 376-0: GBK 控制台下 print 本身也可能编码失败，不得二次崩溃
            _orig_excepthook(exc_type, exc_value, exc_tb)
        _sys.excepthook = _global_exception_handler
        # ★ v4.0 修复：使用无边框窗口，避免系统标题栏与自定义标题栏重叠
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setMinimumSize(800, 600)
        self.resize(1400, 900)
        self.setStyleSheet(global_stylesheet())
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

        # ★ v4.0: 无边框窗口边缘调整大小状态
        self._resize_margin = 8
        self._resize_mode = None
        self._resize_start_geom = None
        self._responsive_layout_mode = "full"
        self._resize_start_pos = None

        # 旧版 GUI Worm Bridge — 界面同步虫桥（备用/视觉参考）
        self.gui_bridge = GUIWormBridge(os.getcwd())
        
        # MIMO Process Bridge — 保留作 fallback
        self.proc_bridge = MIMOProcessBridge(os.getcwd())
        
        # ACP Bridge — 保留作可选增强
        self.acp_bridge = ACPBridge(os.getcwd())
        
        # ★ MIMO Serve Bridge — 主通信通道（HTTP API + SSE）
        self.serve_bridge = MIMOServeBridge(os.getcwd())
        
        self.engine = MIMOEngine(os.getcwd())
        self.engine.register_observer(self._on_engine_event)

        # 最近文件列表 + 命令历史
        self._recent_files = []
        self._command_history = []

        # Git 管理器
        self.git_manager = GitManager(os.getcwd())

        # Ollama 本地模型桥接
        self.ollama_bridge = OllamaBridge()

        # ★ v3.0 Bridge 事件适配器 — bridge/agent_loop → Qt 信号
        self._bridge_event_adapter = None
        self._bridge_agent_loop = None
        if USE_BRIDGE_ENGINE:
            try:
                from bridge.event_adapter import EventAdapter, BridgeEngineCompat, get_event_adapter
                self._bridge_event_adapter = get_event_adapter()
                self._bridge_engine_compat = BridgeEngineCompat(parent=self)
                self._connect_bridge_event_signals()
                logger.info("[MIMOWindow] Bridge事件适配器已激活")
            except Exception as _be:
                print("[MIMOWindow] Bridge事件适配器初始化失败(降级到shared): " + str(_be), flush=True)
                self._bridge_event_adapter = None

        # ★ v3.0 Bridge核心后端模块接入(优雅降级)
        self._bridge_context = None
        self._bridge_permission = None
        self._bridge_goap = None
        self._bridge_memory = None
        self._bridge_skill_router = None
        self._bridge_lsp = None
        try:
            from bridge.core.context_manager import ContextManager
            self._bridge_context = ContextManager()
        except Exception:
            pass
        try:
            from bridge.core.permission_gate import PermissionGate, get_permission_gate
            self._bridge_permission = get_permission_gate()
        except Exception:
            pass
        try:
            from bridge.core.goap_planner import GOAPPlanner
            self._bridge_goap = GOAPPlanner()
        except Exception:
            pass
        try:
            from bridge.core.memory_system import MemorySystem
            self._bridge_memory = MemorySystem()
        except Exception:
            pass
        try:
            from bridge.skills.router import SkillRouter
            self._bridge_skill_router = SkillRouter()
        except Exception:
            pass
        try:
            from bridge.services.lsp_bridge import get_lsp_manager
            self._bridge_lsp = get_lsp_manager()
        except Exception:
            pass

        # 多会话管理（旧版简单 dict）
        self._sessions = {}  # {session_id: {"name": str, "history": list}}
        self._active_session_id = None

        # ★ 多会话并行管理器（新版 MultiSessionManager）
        self.multi_session_mgr = MultiSessionManager(self.serve_bridge)
        
        # ★ 多实例编排管理器（v2.0 新增 — 多 Lemon Code 进程协同）
        self.multi_instance_mgr = MultiInstanceManager(project_path=os.path.dirname(os.path.dirname(__file__)))

        # ★ AI 套壳框架 — 统一 AI 接口层
        self.ai_router = AIRouter()
        self.mimo_adapter = MIMOAdapter(self.serve_bridge)
        self.ollama_adapter = OllamaAdapter(self.ollama_bridge)
        self.ai_router.register_provider("mimo", self.mimo_adapter)
        self.ai_router.register_provider("ollama", self.ollama_adapter)

        # ★ 插件系统
        self.plugin_mgr = PluginManager()
        # 先临时连接错误输出，避免 discover_plugins 期间的 plugin_error 信号丢失
        self.plugin_mgr.plugin_error.connect(
            lambda name, err: print(f"[插件错误] {name}: {err}", flush=True)
        )
        self.plugin_mgr.load_builtin_skills()
        # ★ v3.93: 扫描并加载内置插件目录（否则 get_all_plugins() 永远为空，插件市场无内容）
        try:
            self.plugin_mgr.discover_plugins()
        except Exception as e:
            import traceback
            print(f"[MIMOWindow.__init__] discover_plugins 失败: {e}", flush=True)
            traceback.print_exc()

        # ★ 任务分解引擎
        self.task_engine = TaskEngine()

        # ★ 会话记忆系统（v2.0 新增）
        self.session_memory = SessionMemory()
        
        # ★ LSP 服务器管理器（v0.7.0 — 含崩溃恢复 + C++支持 + 健康监控）
        self.lsp_manager = LSPServerManager(os.getcwd())
        self.lsp_manager.completion_received.connect(self._on_lsp_completion)
        self.lsp_manager.definition_received.connect(self._on_lsp_definition)
        self.lsp_manager.references_received.connect(self._on_lsp_references)
        self.lsp_manager.diagnostics_received.connect(self._on_lsp_diagnostics)
        self.lsp_manager.server_ready.connect(self._on_lsp_server_ready)
        # v0.7.0 新增：崩溃恢复信号
        self.lsp_manager.server_crashed.connect(self._on_lsp_server_crashed)
        self.lsp_manager.server_restarted.connect(self._on_lsp_server_restarted)
        self.lsp_manager.server_failed.connect(self._on_lsp_server_failed)
        self.lsp_manager.health_updated.connect(self._on_lsp_health_updated)

        # ★ 补全弹窗（v0.6.0 新增）
        self.completion_popup = CompletionPopup(self)
        self.completion_popup.item_selected.connect(self._on_completion_selected)
        self.completion_popup.cancelled.connect(self._on_completion_cancelled)

        # ★ v0.8.0: Skill 进度桥接 — 浏览器自动化 + Jupyter Notebook
        # 延迟初始化（避免阻塞主窗口启动），在 _init_ui 完成后再注册
        QTimer.singleShot(2000, self._setup_skill_progress_bridge)
        
        # ★ 代码格式化管理器（v0.6.0 新增）
        self.formatter_manager = FormatterManager()
        self.formatter_manager.format_on_save = True  # 默认启用保存时格式化

        self._init_ui()
        print("[MIMOWindow.__init__] _init_ui 完成，开始连接信号...", flush=True)
        self._connect_signals()
        print("[MIMOWindow.__init__] _connect_signals 完成，开始加载项目...", flush=True)
        try:
            self._load_project(self.engine.project_path)
            print("[MIMOWindow.__init__] _load_project 完成", flush=True)
        except Exception as e:
            print(f"[MIMOWindow.__init__] _load_project 失败: {e}", flush=True)
            import traceback
            traceback.print_exc()

        # ★ 注册当前项目为工作区（启动时自动添加）
        print("[MIMOWindow.__init__] 注册工作区...", flush=True)
        try:
            from core.workspace_manager import get_workspace_manager
            get_workspace_manager().ensure_current(self.engine.project_path)
            print("[MIMOWindow.__init__] 工作区注册完成", flush=True)
        except Exception as _e:
            print(f"[Workspace] 启动注册失败: {_e}")
        
        # 先显示窗口
        print("[MIMOWindow.__init__] 调用 self.show()...", flush=True)
        self.show()
        print(f"[MIMOWindow.__init__] self.show() 完成，isVisible={self.isVisible()}", flush=True)

        # ★ v4.7.17+: 启动瞬间强制刷新布局（避免 Qt 布局竞态导致顶部/底部错位）
        # 在 show 后 + 事件循环空转各执行一次 layoutInhibit/centralWidget().layout().invalidate()
        from PyQt5.QtCore import QTimer as _QTimer_init
        def _force_initial_layout():
            try:
                # 1) 强制主窗口 invalidate
                self.layout().invalidate() if self.layout() else None
                # 2) 强制 central widget 重新计算
                cw = self.centralWidget()
                if cw and cw.layout():
                    cw.layout().invalidate()
                    cw.layout().activate()
                # 3) 强制 title bar 和 bottom bar 重新布局
                if hasattr(self, 'title_bar') and self.title_bar:
                    self.title_bar.layout().invalidate() if self.title_bar.layout() else None
                if hasattr(self, 'global_bottom_bar') and self.global_bottom_bar:
                    self.global_bottom_bar.layout().invalidate() if self.global_bottom_bar.layout() else None
                # 4) 强制模式页面布局
                if hasattr(self, 'mode_stack') and self.mode_stack:
                    self.mode_stack.updateGeometry()
                # 5) 触发整体 update
                self.updateGeometry()
                self.centralWidget().updateGeometry()
                self.centralWidget().update()
                print("[MIMOWindow.__init__] 强制初始布局已刷新", flush=True)
            except Exception as _e:
                print(f"[MIMOWindow.__init__] 强制布局刷新异常: {_e}", flush=True)
        # 事件循环下一帧执行（不阻塞当前 __init__）
        _QTimer_init.singleShot(0, _force_initial_layout)
        _QTimer_init.singleShot(100, _force_initial_layout)

        # ★ 若通过环境变量强制指定引擎模式，则在启动后自动切换
        import os as _os
        _forced_mode = _os.environ.get("LEMON_FORCE_ENGINE", "").lower()
        if _forced_mode in ("mimo", "ollama", "deepseek"):
            print(f"[MIMOWindow.__init__] 检测到强制引擎模式: {_forced_mode}", flush=True)
            QTimer.singleShot(500, lambda: self._auto_switch_engine_mode(_forced_mode))

        # 底部交互终端欢迎信息
        # ★ v3.72: 精简欢迎信息，只显示一行
        self.bottom_panel.mimo_console.append_html(
            f'<span style="color:{MIMO_ORANGE};font-weight:600;">Lemon Code</span>'
            f'<span style="color:{TEXT_TERTIARY};"> · 输入消息按 Enter 发送</span>'
        )

        # ★ 启动 MIMO Serve Bridge（主通信通道）
        print("[MIMOWindow.__init__] 启动 serve_bridge...", flush=True)
        self.bottom_panel.log_output("[Serve] 正在启动 Lemon Serve 通信桥...", INFO)
        if self.serve_bridge.start():
            self.bottom_panel.log_output("[Serve] Lemon Serve 通信桥启动中...", SUCCESS)
        else:
            self.bottom_panel.log_output("[Serve] 启动失败", ERROR)
        print("[MIMOWindow.__init__] serve_bridge.start() 完成", flush=True)

        # ★ v3.60: 启动连接监测工具
        self._init_connection_monitor()

        # 插件系统状态
        plugin_summary = self.plugin_mgr.get_summary()
        self.bottom_panel.log_output(
            f"[插件] 已加载 {plugin_summary['skills']['count']} 个Skill, "
            f"{plugin_summary['tools']['count']} 个Tool",
            SUCCESS
        )

        # 连接 MIMO Monitor
        print("[MIMOWindow.__init__] 调用 _show_mimo_monitor()...", flush=True)
        self._show_mimo_monitor()
        # ★ 内存监控 — 定期检查并在内存过高时清理 QWebEngine 缓存
        self._start_memory_monitor()

        # ★ 第281章 A 阶段：运行时引擎接线 + 工具源注册
        self._wire_c281a_runtime()

        print("[MIMOWindow.__init__] 初始化完成！", flush=True)

    def _wire_c281a_runtime(self):
        """★ 第281章 A 阶段：把 5 大功能接线到运行时（标准模式 UI 区，可改）。
        注册 ops/mcp/browser/notebook 工具源，并预热跨引擎运行时。
        """
        try:
            from shared.bridges.engine_runtime import get_runtime_hub
            from ui.skills.ops_skills import register_ops_tools
            from ui.browser_tool import BrowserToolSource
            from ui.notebook_shell import NotebookShell
            from ui.tool_sources.mcp_tool_source import register_mcp_servers

            hub = get_runtime_hub()

            # 1) 运维工具（危险操作走 Qt 确认框）
            ops_count = register_ops_tools(confirm_cb=self._confirm_dangerous_op)
            # 2) 内置浏览器工具源（复用已挂载的 web_browser）
            browser_src = BrowserToolSource(panel=getattr(self, "web_browser", None))
            browser_src.register_to()
            hub.register_tool_source("browser", browser_src)
            # 3) Notebook 渲染/执行工具源
            nb = NotebookShell()
            nb.register_to()
            hub.register_tool_source("notebook", nb)
            # 4) MCP 工具源（按 config/mcp_servers.json；失败静默跳过）
            mcp_servers = self._load_mcp_servers_config()
            mcp_count = register_mcp_servers(mcp_servers) if mcp_servers else 0
            # 5) 预热跨引擎运行时（发现可用引擎）
            # ★ 卡顿修复(第341章): discover_engines 对 ollama/mimocode/deepseek 逐个
            # 同步真实 chat "ping"（DeepSeek API 实测 2.5s + 本地模型推理数秒），
            # 原在主线程执行 = 启动时窗口冻结数秒（"打开要缓冲一会"主因之一）。
            # 移到后台线程，完成后仅记录日志。
            import threading as _th
            def _bg_discover():
                try:
                    found = hub.discover_engines()
                    print(f"[C281A] 跨引擎运行时后台预热完成: {found}", flush=True)
                except Exception as _e:
                    print(f"[C281A] 后台预热失败: {_e}", flush=True)
            _th.Thread(target=_bg_discover, daemon=True, name="engine-discover").start()
            self.bottom_panel.log_output(
                f"[C281A] 工具源就绪 · ops={ops_count} browser notebook mcp={mcp_count} · 跨引擎运行时已接线",
                SUCCESS,
            )
        except Exception as e:
            import traceback as _tb
            _tb.print_exc()
            try:
                self.bottom_panel.log_output(f"[C281A] 接线异常: {e}", ERROR)
            except Exception:
                pass

    def _confirm_dangerous_op(self, description: str) -> bool:
        """危险运维操作确认框（阻塞主线程，等待用户决定）。"""
        from PyQt5.QtWidgets import QMessageBox
        res = QMessageBox.question(
            self, "危险操作确认",
            f"即将执行危险运维操作：\n\n{description}\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
        )
        return res == QMessageBox.Yes

    def _load_mcp_servers_config(self):
        """读取 MCP server 配置（config/mcp_servers.json），缺失返回 []。"""
        import json, os
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "mcp_servers.json")
        try:
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("servers", []) if isinstance(data, dict) else (data or [])
        except Exception as e:
            print(f"[C281A] 读取 MCP 配置失败: {e}")
        return []

    def _init_connection_monitor(self):
        """★ v3.62: 初始化连接监测（进度条 + watchdog 静默模式）"""
        try:
            from core.connection_monitor import ConnectionMonitor
            self._conn_monitor = ConnectionMonitor.instance()
            self._conn_monitor.set_output_callback(
                lambda html: self.bottom_panel.mimo_console.append_html(html)
            )
            # 延迟 3 秒后启动（等 mimo.exe 完全就绪，然后显示进度条连接）
            QTimer.singleShot(3000, self._start_conn_monitor)
            print("[ConnectionMonitor] 已初始化，3s后启动进度条连接", flush=True)
        except Exception as e:
            print(f"[ConnectionMonitor] 初始化失败: {e}", flush=True)
    
    def _start_conn_monitor(self):
        """启动连接监测（进度条 → watchdog）"""
        try:
            if hasattr(self, '_conn_monitor') and self._conn_monitor:
                self._conn_monitor.start()
                print("[ConnectionMonitor] 进度条连接已启动", flush=True)
        except Exception as e:
            print(f"[ConnectionMonitor] 启动失败: {e}", flush=True)
    
    def _init_ui(self):
        print("[MIMOWindow._init_ui] 开始创建UI...", flush=True)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Lemon风格标题栏
        self.title_bar = XiaomiTitleBar()
        # ★ v4.1.11: Host Agent 功能栏动作
        self.title_bar.host_action_requested.connect(self._on_host_toolbar_action)
        layout.addWidget(self.title_bar)

        # ★ v4.7.19: 搜索框 + 积分移到菜单栏中间（菜单按钮之后、stretch 之前）
        from PyQt5.QtWidgets import QLineEdit, QLabel

        # 顶部菜单栏的搜索框：变大做明显（minWidth 360、高度 28），用户视觉上能立刻看到
        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("搜索 消息 / 文件 / 命令... (Ctrl+Shift+F)")
        self.global_search.setMinimumSize(360, 28)
        self.global_search.setMaximumWidth(560)
        self.global_search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.global_search.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_SURFACE};
                border: 1px solid {BORDER_SUBTLE};
                border-radius: 14px;
                padding: 0 14px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
                min-height: 22px;
            }}
            QLineEdit:hover {{ border-color: {BORDER_DEFAULT}; }}
            QLineEdit:focus {{ border-color: {MIMO_ORANGE}; border-width: 1px; }}
        """)
        self.global_search.textChanged.connect(self._on_global_search_input)
        self.global_search.returnPressed.connect(self._on_global_search_exec)
        # 菜单按钮 6 个（运行/帮助紧挨着）→ stretch → 搜索框 + 积分（追加到末尾）→ NATIVE/HOST
        # 不再 insertWidget 中间插入，避免把运行(R)/帮助(H) 撑开
        # 搜索框居中：左侧 addStretch(1) 把菜单按钮推到左，右侧 addStretch(0) 让积分靠右
        self.title_bar.menu_layout.addStretch(1)
        self.title_bar.menu_layout.addWidget(self.global_search)
        self.title_bar.menu_layout.addStretch(0)

        # 顶部菜单栏的积分：变大做明显（18px、加粗 + 橙色星号 + 大数字 + 点击展开用量面板）
        self.global_credits = QLabel("★ 2,000")
        self.global_credits.setCursor(Qt.PointingHandCursor)
        self.global_credits.setStyleSheet(
            f"color: {MIMO_ORANGE}; font-size: 18px; font-weight: 700;"
            f" padding: 2px 12px; border: 1px solid rgba(255,122,47,0.35);"
            f" border-radius: 12px; background: rgba(255,122,47,0.06);"
            f" letter-spacing: 0.5px;")
        self.global_credits.setToolTip("积分与用量统计（点击展开）")
        self.title_bar.menu_layout.addWidget(self.global_credits)



        # ===== 预先创建原始核心组件（供信号连接使用） =====
        print("[MIMOWindow._init_ui] 创建原始核心组件...", flush=True)
        self._create_core_components()

        # ===== ★ 模式切换系统：QStackedWidget 包裹三种模式页面 =====
        self.mode_stack = QStackedWidget()
        self._current_mode = 'original'  # original / single / multi / hybrid

        # --- 页面0: 原始界面（文件树+编辑器+AI面板，含 v4.7.2 多会话 Tab 栏）---
        print("[MIMOWindow._init_ui] 创建原始界面...", flush=True)
        self._original_page = self._create_original_ui()
        self.mode_stack.addWidget(self._original_page)

        # --- 页面1: 混合模式（项目公司化）---
        # ★ v4.7.2: 单AI多窗口 / 多AI协同已移除（参考 CodeBuddy，改为顶部会话 Tab 栏）
        print("[MIMOWindow._init_ui] 创建混合模式页面...", flush=True)
        self._hybrid_page = self._create_hybrid_page()
        self.mode_stack.addWidget(self._hybrid_page)

        layout.addWidget(self.mode_stack, 1)

        # ★ v4.7.17: 全局底部状态栏（Trae/CodeBuddy 风格，横跨整个窗口）
        layout.addWidget(self._build_global_bottom_bar())

        print("[MIMOWindow._init_ui] 创建状态栏...", flush=True)
        self._create_status_bar()

        # ★ LemonGaze C4: 陪伴模式挂载（state + 眼睛 dock + 右下角小点）
        try:
            from ui.companion.companion_dock import mount_companion
            mount_companion(self)
            # C3.3 双向绑定：开关状态与窗口 CompanionState.enabled 同步
            self.title_bar.companion_toggled.connect(
                self.companion_state.set_enabled)
            self.companion_state.enabled_changed.connect(
                self._sync_companion_titlebar)
            self._sync_companion_titlebar(self.companion_state.enabled)
        except Exception as _lz_e:
            print(f"[LemonGaze] 陪伴模式挂载失败(降级): {_lz_e}", flush=True)

        # ===== 全局快捷键 =====
        print("[MIMOWindow._init_ui] 设置快捷键...", flush=True)
        self._setup_shortcuts()
        print("[MIMOWindow._init_ui] UI创建完成", flush=True)

        # ★ v4.1.14: UI 创建完成后，把真实当前模型同步到底部栏（替代硬编码占位符 mimo-auto）
        try:
            self._sync_console_model()
        except Exception:
            pass

    # ================================================================
    # ★ LemonGaze C3.3: 陪伴开关双向绑定（title_bar ←→ CompanionState）
    # ================================================================
    def _sync_companion_titlebar(self, on: bool) -> None:
        """把 CompanionState.enabled 同步到标题栏按钮（阻断信号防回环）。"""
        try:
            btn = getattr(self.title_bar, "_btn_companion", None)
            if btn is None:
                return
            btn.blockSignals(True)
            btn.setChecked(on)
            factory = getattr(self.title_bar, "_companion_icon_factory", None)
            if factory:
                btn.setIcon(factory(on))
            btn.blockSignals(False)
        except Exception as _sync_e:
            print(f"[LemonGaze] 标题栏开关同步失败: {_sync_e}", flush=True)

    # ================================================================
    # ★ v4.7.17: 全局顶栏/底栏（Trae/CodeBuddy 风格，横跨整个窗口）
    # ================================================================
    def _svg_icon_from_string(self, svg_str, color):
        """SVG 字符串 → QIcon（currentColor 替换为目标颜色）"""
        try:
            from PyQt5.QtSvg import QSvgRenderer
            from PyQt5.QtGui import QIcon, QPixmap, QPainter
            from PyQt5.QtCore import QByteArray
            s = svg_str.replace('currentColor', color)
            renderer = QSvgRenderer(QByteArray(s.encode('utf-8')))
            pix = QPixmap(20, 20)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            renderer.render(p)
            p.end()
            return QIcon(pix)
        except Exception as e:
            print(f"[GlobalBar] SVG 渲染失败: {e}")
            return QIcon()

    def _global_bar_btn(self, icon_svg, tooltip, action, shortcut_text=""):
        """顶栏图标按钮：点击转发到当前会话面板的 JS"""
        from PyQt5.QtCore import QSize
        btn = QToolButton()
        btn.setToolTip(f"{tooltip}{('  ' + shortcut_text) if shortcut_text else ''}")
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setIcon(self._svg_icon_from_string(icon_svg, TEXT_TERTIARY))
        btn.setIconSize(QSize(16, 16))
        btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: none;
                border-radius: {RADIUS_SM};
            }}
            QToolButton:hover {{
                background: {BG_SURFACE_HOVER};
            }}
        """)
        btn.clicked.connect(lambda: self._top_action(action))
        return btn

    def _top_action(self, action, *args):
        """把顶栏按钮动作转发到当前激活会话面板的 JS"""
        panel = getattr(self, 'mimo_panel', None)
        if panel is None or not hasattr(panel, 'web_view'):
            return
        try:
            arg_str = ",".join(json.dumps(a) for a in args)
            js = f"{action}({arg_str})"
            panel.web_view.page().runJavaScript(js)
            print(f"[GlobalTopBar] 转发 → {js}")
        except Exception as e:
            print(f"[GlobalTopBar] 转发 {action} 失败: {e}")

    def _on_global_search_input(self, text):
        if text:
            self._top_action('onTopbarSearch', text)

    def _on_global_search_exec(self):
        self._top_action('execTopbarSearch', self.global_search.text())

    def _build_global_top_bar(self):
        """v4.7.17: 全局顶部工具栏（搜索 + 积分 + 工具按钮，横跨整个窗口）"""
        from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QLabel

        bar = QFrame()
        bar.setObjectName("GlobalTopBar")
        bar.setFixedHeight(42)
        bar.setStyleSheet(f"""
            #GlobalTopBar {{ background: {BG_PRIMARY}; border-bottom: 1px solid {BORDER_SUBTLE}; }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(6)

        # 全局搜索框（转发到右侧栏 onTopbarSearch）
        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("搜索 消息 / 文件 / 命令...  (Ctrl+Shift+F)")
        self.global_search.setFixedSize(280, 28)
        self.global_search.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_SURFACE};
                border: 1px solid {BORDER_SUBTLE};
                border-radius: 14px;
                padding: 0 12px;
                color: {TEXT_PRIMARY};
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {MIMO_ORANGE}; }}
        """)
        self.global_search.textChanged.connect(self._on_global_search_input)
        self.global_search.returnPressed.connect(self._on_global_search_exec)
        lay.addWidget(self.global_search)

        # 积分显示（★ + 数字，橙黄色）
        self.global_credits = QLabel("★ 2,000")
        self.global_credits.setStyleSheet(
            f"color: {MIMO_ORANGE}; font-size: 12px; font-weight: 600; padding: 0 6px;")
        self.global_credits.setToolTip("积分与用量统计")
        lay.addWidget(self.global_credits)

        # 分隔线
        sep = QFrame()
        sep.setFixedSize(1, 20)
        sep.setStyleSheet(f"background: {BORDER_SUBTLE};")
        lay.addWidget(sep)

        # 工具图标按钮（Trae/CodeBuddy 风格）
        def _add(svg_key, tip, action, sc=""):
            svg = SVG_ICONS.get(svg_key, SVG_ICONS['tool'])
            lay.addWidget(self._global_bar_btn(svg, tip, action, sc))

        _add('tool',     '面板布局切换',      'cyclePanelLayout',        '')
        _add('palette',  '切换主题',          'toggleThemeQuickMenu',    '')
        _add('user',     '辅助功能',          'toggleAccessibilityMenu', '')
        _add('star',     '账户',              'toggleAccountMenu',       '')
        lay.addSpacing(4)
        _add('clipboard','工作表',            'toggleTodoPanel',         'Ctrl+T')
        _add('build',    'Plan 规划模式',     'togglePlanMode',          'Ctrl+Shift+P')
        _add('terminal', '命令面板',          'toggleCmdPanel',          'Ctrl+P')
        _add('refresh',  '清除输出',          'clearOutput',             'Ctrl+L')
        _add('settings', '设置',              'openSettings',            'Ctrl+,')
        _add('chevron_right', '工具面板',     '_toggleRightPanel',       'Ctrl+B')
        _add('debug',    'Worktree 隔离',     'toggleWorktreePanel',     'Ctrl+Shift+W')
        lay.addStretch()

        self.global_top_bar = bar
        return bar

    def _build_global_bottom_bar(self):
        """v4.7.17+: 全局底部状态栏精简版（仅性能 + 连接状态 + 版本号）

        历史版本曾显示「当前项目/光标位置/文件编码/语言/运行环境」等多余词条，
        现已删除，仅保留对用户有价值的信息（FPS/CPU/MEM/连接状态/版本）。
        """
        from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel

        bar = QFrame()
        bar.setObjectName("GlobalBottomBar")
        bar.setFixedHeight(30)
        bar.setStyleSheet(f"""
            #GlobalBottomBar {{ background: {BG_PRIMARY}; border-top: 1px solid {BORDER_SUBTLE}; }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(14)

        def _st(tip):
            lb = QLabel("")
            lb.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
            lb.setToolTip(tip)
            lay.addWidget(lb)
            return lb

        # ★ v4.7.17+ 精简：仅保留性能指标 + 连接状态 + 版本号
        self.bottom_fps    = _st("渲染帧率")
        self.bottom_cpu    = _st("CPU 使用率")
        self.bottom_mem    = _st("内存使用")
        # ★ v4.7.17: 兼容旧 self.status_label（160+ 处 setText 自动跟随）—— 仅展示版本号
        self.status_label  = QLabel("Lemon Agent v0.3.0")
        self.status_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        lay.addWidget(self.status_label)
        lay.addStretch()
        # ★ v4.7.17: 兼容咩咩人格炼化进度标签（v4.4.2）
        self.persona_status_label = QLabel("")
        self.persona_status_label.setStyleSheet(
            f"color:{Lemon.BRAND_ORANGE}; font-size:11px; font-weight:600; padding:0 6px;")
        lay.addWidget(self.persona_status_label)
        self.bottom_conn   = _st("连接状态")
        self.bottom_ver    = QLabel("v0.5.1")
        self.bottom_ver.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        lay.addWidget(self.bottom_ver)

        # 初始值（后续由状态推送更新）
        self.bottom_conn.setText("● ready")

        # 性能定时器（3s 更新 CPU/MEM/FPS）
        # 诊断开关：LEMON_NO_PERF_TIMER=1 时禁用（排查主线程卡顿）
        if os.environ.get("LEMON_NO_PERF_TIMER") != "1":
            try:
                self._global_perf_timer = QTimer(self)
                self._global_perf_timer.timeout.connect(self._update_global_perf)
                self._global_perf_timer.start(3000)
            except Exception as e:
                print(f"[GlobalBottomBar] 性能定时器启动失败: {e}")

        self.global_bottom_bar = bar
        return bar

    def _update_global_perf(self):
        """底栏性能指标（CPU/MEM/FPS）"""
        try:
            import psutil
            self.bottom_cpu.setText(f"CPU {psutil.cpu_percent(interval=None)}%")
            mem = psutil.virtual_memory()
            self.bottom_mem.setText(f"MEM {mem.used // 1048576}MB")
        except Exception:
            pass
        try:
            import time as _t
            now = _t.time()
            dt = now - getattr(self, '_fps_last', now)
            self._fps_last = now
            if 0 < dt < 1:
                self.bottom_fps.setText(f"FPS {int(1.0 / dt)}")
        except Exception:
            pass

    def _create_core_components(self):
        """创建原始核心组件（供信号连接和功能使用，不直接显示在模式页面中）"""
        # 文件资源管理器
        self.explorer = ExplorerPanel()
        self.explorer.file_selected.connect(self._on_file_selected)
        self.explorer.file_replace_requested.connect(self._on_file_replace)
        self.explorer.git_action_requested.connect(self._on_git_action)
        self.explorer.compare_requested.connect(self._on_compare_file)
        self.explorer.symbol_clicked.connect(self._on_symbol_clicked)
        self.explorer.set_git_manager(self.git_manager)
        self.explorer.hide()  # 默认隐藏，在需要时显示

        # 编辑器区域
        self.editor_area = self._create_editor_area()
        self.editor_area.hide()

        # ★ v4.7.2: CodeBuddy 风格多会话工作区（顶部 Tab 栏 + 会话实例池）
        # 取代旧「单AI多窗口模式 / 多AI协同」：每个 Tab = 完全隔离的面板实例
        self.session_workspace = SessionWorkspace()
        self.session_workspace.set_panel_factory(self._create_session_panel)
        self.session_workspace.new_session_requested.connect(
            self._on_workspace_new_session, Qt.QueuedConnection)
        self.session_workspace.session_switched.connect(
            self._on_workspace_session_switched, Qt.QueuedConnection)
        self.session_workspace.session_closed.connect(
            self._on_workspace_session_closed, Qt.QueuedConnection)
        self.session_workspace.hide()

        # ★ TRAE 同款布局三档：从配置恢复（right/bottom/hidden）
        try:
            from PyQt5.QtCore import QSettings as _QS
            self._ai_layout_mode = str(
                _QS('LemonCode', 'MIMOWindow').value('ai_layout_mode', 'right'))
        except Exception:
            self._ai_layout_mode = 'right'
        if self._ai_layout_mode not in ('right', 'bottom', 'hidden'):
            self._ai_layout_mode = 'right'

        # ★ 当前会话面板引用 —— 始终指向激活 Tab 的 MIMOCodePanel 实例
        # 160+ 处调用点（self.mimo_panel.xxx）自动跟随；首个会话在
        # _create_original_ui 中创建并赋值
        self.mimo_panel = None
        self._shared_engine_manager = None

        # 旧多会话并行面板 / 多实例网格：v4.7.2 起不再展示（类保留防依赖破坏）
        self.multi_session_panel = MultiSessionPanel()
        self.multi_session_panel.hide()

        # 多实例网格面板
        self.multi_instance_grid = MultiInstanceGrid()
        self.multi_instance_grid.hide()

        # 底部面板
        self.bottom_panel = BottomPanel()
        self.bottom_panel.setMinimumHeight(100)
        self.bottom_panel.set_mode("native")  # ★ v4.1.13: 初始化即按 native 精简标签
        self.bottom_panel.hide()

        # ★ v5.0 Whitebox: 白盒化状态面板（Run/Step/ToolCall/Approval/Artifact）
        try:
            from ui.whitebox.whitebox_panel import WhiteboxPanel
            self.whitebox_panel = WhiteboxPanel()
            self.whitebox_panel.hide()
        except Exception as _wb_err:
            print(f"[MIMOWindow] WhiteboxPanel 初始化失败: {_wb_err}", flush=True)
            self.whitebox_panel = None

        # ★ v5.0 B-3: Git 状态实时同步面板
        try:
            from ui.whitebox.git_status_panel import GitStatusPanel
            project_path = ""
            if hasattr(self, 'session_workspace') and self.session_workspace:
                project_path = getattr(self.session_workspace, 'project_path', '')
            self.git_status_panel = GitStatusPanel(project_path)
            self.git_status_panel.revert_requested.connect(self._on_git_revert)
            self.git_status_panel.hide()
        except Exception as _git_err:
            print(f"[MIMOWindow] GitStatusPanel 初始化失败: {_git_err}", flush=True)
            self.git_status_panel = None

    # ================================================================
    # ★ v4.7.2: 多会话（CodeBuddy 风格顶部 Tab 栏）—— 实例工厂与信号绑定
    # ================================================================
    def _create_session_panel(self):
        """会话面板工厂：为每个会话创建完全隔离的 MIMOCodePanel 实例。"""
        try:
            panel = MIMOCodePanel()
        except Exception as e:
            print(f"[会话] MIMOCodePanel 创建失败: {e}", flush=True)
            return None
        if panel is None:
            return None
        panel.hide()
        self._bind_mimo_panel(panel)
        return panel

    def _bind_mimo_panel(self, panel):
        """绑定单个 MIMOCodePanel 实例的信号（panel → window）。

        多会话架构下每个实例都要绑定一次；serve_bridge → panel 的转发
        在 _connect_signals 中统一用 lambda 指向当前激活实例。
        """
        panel.command_sent.connect(
            lambda msg: self._on_user_send(msg, 'right_panel'), Qt.QueuedConnection)
        panel.pybridge.input_sync.connect(self._on_right_panel_input_sync, Qt.QueuedConnection)
        # ★ v3.81: agent 状态转发到三色灯
        panel.pybridge.set_agent_state_signal.connect(self._on_agent_state_signal)
        panel.workspace_switch_requested.connect(self._on_workspace_switch, Qt.QueuedConnection)
        panel.permission_responded.connect(self.serve_bridge.respond_permission, Qt.QueuedConnection)
        panel.mode_switch_requested.connect(self.serve_bridge.set_mode, Qt.QueuedConnection)
        panel.model_switch_requested.connect(self._on_model_switch, Qt.QueuedConnection)
        panel.session_switch_requested.connect(self._on_session_switch)
        panel.fetch_models_requested.connect(self._on_fetch_models_for_panel, Qt.QueuedConnection)
        panel.fetch_sessions_requested.connect(self._on_fetch_sessions_for_panel, Qt.QueuedConnection)
        panel.new_session_requested.connect(self._on_new_session_from_panel, Qt.QueuedConnection)
        panel.service_mode_switch_requested.connect(self._on_service_mode_switch, Qt.QueuedConnection)
        panel.engine_cycle_requested.connect(self._on_cycle_engine, Qt.QueuedConnection)
        panel.settings_open_requested.connect(self._on_open_settings, Qt.QueuedConnection)
        panel.trust_mode_changed.connect(self._on_trust_mode_changed, Qt.QueuedConnection)
        panel.config_applied.connect(self._on_config_applied, Qt.QueuedConnection)
        # ★ 面板错误信号 → 右侧面板显示（不再静默吞没）
        panel.error_occurred.connect(lambda msg: panel.on_output(f"<span style='color:{Lemon.ACCENT_RED};'>{msg}</span>"), Qt.QueuedConnection)
        # ★ Agent 完成输出信号 → 右侧面板显示（output_received 之前未连接，导致 Agent 回复丢失）
        panel.output_received.connect(lambda html: panel.on_output(html), Qt.QueuedConnection)
        # ★ 设置 serve_bridge 引用到 panel（供快照管理调用）
        panel.set_serve_bridge(self.serve_bridge)
        if self._shared_engine_manager is not None:
            panel.set_engine_manager(self._shared_engine_manager)
        elif hasattr(self.mimo_panel, '_engine_manager') and self.mimo_panel._engine_manager:
            self._shared_engine_manager = self.mimo_panel._engine_manager
            panel.set_engine_manager(self._shared_engine_manager)
        if hasattr(self, '_tool_confirm_gate') and hasattr(panel, 'set_tool_confirm_callback'):
            panel.set_tool_confirm_callback(self._tool_confirm_gate.make_callback())

    def _on_workspace_new_session(self):
        """顶部 Tab 栏「+」→ 新建会话（CodeBuddy 风格）。"""
        print("[会话] _on_workspace_new_session 被调用", flush=True)
        self.bottom_panel.log_output("[会话] 新建会话", INFO)
        panel = self.session_workspace.create_session()
        print(f"[会话] create_session 返回: {panel}", flush=True)
        if panel is not None:
            self.mimo_panel = panel
            panel.show()

    def _on_workspace_session_switched(self, session_id):
        """切换会话 Tab —— 更新 self.mimo_panel 引用（160+ 调用点自动跟随）。"""
        panel = self.session_workspace.get_panel(session_id)
        if panel is not None:
            self.mimo_panel = panel
            panel.show()

        # ★ v5.0 Whitebox: 会话切换时保存旧会话、加载新会话状态
        if hasattr(self, 'whitebox_panel') and self.whitebox_panel:
            try:
                import os
                data_dir = os.path.join(self.engine.project_path, ".lemon", "whitebox")
                os.makedirs(data_dir, exist_ok=True)
                old_sid = getattr(self.whitebox_panel.projector, '_current_session_id', '')
                if old_sid:
                    self.whitebox_panel.registry.save_session(
                        old_sid, os.path.join(data_dir, f"{old_sid}.json"))
                self.whitebox_panel.registry.clear()
                load_path = os.path.join(data_dir, f"{session_id}.json")
                if os.path.exists(load_path):
                    self.whitebox_panel.registry.load_session(load_path)
                self.whitebox_panel.projector._current_session_id = session_id
            except Exception as _wb_e:
                print(f"[Whitebox] 会话切换持久化失败: {_wb_e}", flush=True)

    def _on_workspace_session_closed(self, session_id):
        """关闭会话 —— 引用由 Tab 切换自动更新。"""
        self.bottom_panel.log_output(f"[会话] 关闭会话 {str(session_id)[:12]}...", INFO)

    def _create_original_ui(self):
        """创建原始界面 — 左侧栏 + 文件树 + 编辑器 + AI面板（四栏布局）"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ===== 主体区域：左侧栏 + 三栏布局 =====
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧 Activity Bar + Side Panel
        from ui.activity_bar import ActivityBar
        from ui.side_panel import SidePanel
        self.activity_bar = ActivityBar()
        self.side_panel = SidePanel()
        self.activity_bar.activity_changed.connect(self.side_panel.set_activity)
        
        # ★ 注入管理器
        self.side_panel.set_git_manager(self.git_manager)
        self.side_panel.set_plugin_manager(self.plugin_mgr)
        
        # ★ 连接信号
        self.side_panel.search_requested.connect(self._on_side_search)
        self.side_panel.git_commit_requested.connect(self._on_side_git_commit)
        self.side_panel.file_diff_requested.connect(self._on_compare_file)
        self.side_panel.ai_commit_requested.connect(self._on_ai_generate_commit)
        self.side_panel.branch_switch_requested.connect(self._on_branch_switch)
        self.side_panel.branch_create_requested.connect(self._on_branch_create)
        self.side_panel.branch_delete_requested.connect(self._on_branch_delete)
        self.side_panel.stash_requested.connect(self._on_stash)
        self.side_panel.stash_pop_requested.connect(self._on_stash_pop)
        self.side_panel.view_all_diff_requested.connect(self._on_view_all_diff)
        self.side_panel.settings_saved.connect(self._on_settings_saved)
        self.side_panel.stash_apply_requested.connect(self._on_stash_apply)
        self.side_panel.stash_drop_requested.connect(self._on_stash_drop)
        self.side_panel.git_push_requested.connect(self._on_git_push)
        self.side_panel.git_pull_requested.connect(self._on_git_pull)

        # 加载已保存的 AI 提交信息引擎配置
        self._load_ai_commit_settings()

        left_container = QWidget()
        left_layout = QHBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.activity_bar)
        left_layout.addWidget(self.side_panel)

        main_layout.addWidget(left_container)

        # 原有三栏布局
        v_splitter = QSplitter(Qt.Vertical)
        v_splitter.setHandleWidth(6)
        v_splitter.setChildrenCollapsible(False)
        # ★ 用户反馈：使用实时伸缩模式，不显示虚线框
        v_splitter.setOpaqueResize(True)
        v_splitter.setStyleSheet(f"""
            QSplitter::handle {{ background: {Lemon.DARK_BG_4}; border-radius: 2px; }}
            QSplitter::handle:hover {{ background: {Lemon.BRAND_ORANGE}; }}
        """)

        h_splitter = QSplitter(Qt.Horizontal)
        h_splitter.setHandleWidth(4)
        h_splitter.setChildrenCollapsible(False)
        # ★ 用户反馈：使用实时伸缩模式，不显示虚线框
        h_splitter.setOpaqueResize(True)
        # ★ 设置子控件的大小策略，确保编辑器可以缩小并显示滚动条
        self.explorer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.editor_area.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.session_workspace.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        # ★ 允许编辑器区域缩小到很小，让内部滚动条接管
        self.editor_area.setMinimumWidth(50)
        
        self.explorer.show()
        h_splitter.addWidget(self.explorer)
        self.editor_area.show()
        h_splitter.addWidget(self.editor_area)
        # ★ v4.7.2: 右侧改为多会话工作区（顶部 Tab 栏 + 会话实例池，CodeBuddy 风格）
        self.session_workspace.show()
        h_splitter.addWidget(self.session_workspace)
        # 创建首个会话（会话完全隔离：独立 WebEngine 实例）
        self.mimo_panel = self.session_workspace.create_session("会话 1")
        if self.mimo_panel is not None:
            self.mimo_panel.show()
        # ★ v4.7.22: 对标 Trae —— 比例更均衡（文件树 200 / 编辑器 600 / 对话 1060），
        #   编辑器回到主位，避免把代码显示框压得太窄
        h_splitter.setSizes([200, 600, 1060])
        v_splitter.addWidget(h_splitter)

        self.bottom_panel.show()
        v_splitter.addWidget(self.bottom_panel)
        v_splitter.setSizes([780, 300])
        v_splitter.setStretchFactor(0, 0)
        v_splitter.setStretchFactor(1, 1)
        v_splitter.setChildrenCollapsible(True)

        main_layout.addWidget(v_splitter, 1)

        # ★ 布局三档：保存 splitter 引用，并应用持久化的 AI 面板布局
        self._h_splitter = h_splitter
        self._v_splitter = v_splitter
        try:
            self._apply_ai_layout(getattr(self, '_ai_layout_mode', 'right'))
        except Exception as _lay_e:
            print("[布局] 初始 AI 面板布局应用失败:", _lay_e, flush=True)

        layout.addWidget(main_widget, 1)

        print("[_create_original_ui] 四栏布局创建成功（左侧栏+文件树+编辑器+AI面板）", flush=True)
        return page

    def _on_menu_action(self, action_id: str):
        """处理菜单栏动作"""
        print(f"[Menu] 触发动作: {action_id}", flush=True)

        # 文件操作
        if action_id == "new_file":
            # ★ 新建空文件
            self._new_untitled_file()
        elif action_id == "open_folder":
            # ★ 打开文件夹对话框
            from PyQt5.QtWidgets import QFileDialog
            folder = QFileDialog.getExistingDirectory(self, "选择文件夹", self.engine.project_path)
            if folder:
                self._load_project(folder)
        elif action_id == "save":
            # ★ 保存当前文件
            current = self.editor_tabs.currentWidget()
            if isinstance(current, CodeEditor) and current.file_path:
                self._save_file(current.file_path, current.get_content())
            else:
                self.bottom_panel.log_output("[文件] 无文件可保存", WARNING)
        elif action_id == "save_all":
            # ★ 保存所有文件
            for i in range(self.editor_tabs.count()):
                widget = self.editor_tabs.widget(i)
                if isinstance(widget, CodeEditor) and widget.file_path:
                    self._save_file(widget.file_path, widget.get_content())
            self.bottom_panel.log_output("[文件] 已保存所有文件", SUCCESS)
        elif action_id == "close_editor":
            # ★ 关闭当前标签
            self._on_close_current_tab()

        # 编辑操作
        elif action_id == "undo":
            current = self.editor_tabs.currentWidget()
            if isinstance(current, CodeEditor):
                current.undo()
        elif action_id == "redo":
            current = self.editor_tabs.currentWidget()
            if isinstance(current, CodeEditor):
                current.redo()
        elif action_id == "cut":
            current = self.editor_tabs.currentWidget()
            if isinstance(current, CodeEditor):
                current.cut()
        elif action_id == "copy":
            current = self.editor_tabs.currentWidget()
            if isinstance(current, CodeEditor):
                current.copy()
        elif action_id == "paste":
            current = self.editor_tabs.currentWidget()
            if isinstance(current, CodeEditor):
                current.paste()
        elif action_id == "find":
            # ★ 查找对话框
            self._show_find_dialog()
        elif action_id == "replace":
            # ★ 替换对话框
            self._show_replace_dialog()

        # 选择操作
        elif action_id == "select_all":
            current = self.editor_tabs.currentWidget()
            if isinstance(current, CodeEditor):
                current.select_all()
        elif action_id == "select_line":
            current = self.editor_tabs.currentWidget()
            if isinstance(current, CodeEditor):
                cursor = current.editor.textCursor()
                cursor.select(QTextCursor.LineUnderCursor)
        elif action_id == "expand_selection":
            current = self.editor_tabs.currentWidget()
            if isinstance(current, CodeEditor):
                cursor = current.editor.textCursor()
                cursor.select(QTextCursor.WordUnderCursor)

        # 查看操作
        elif action_id == "toggle_sidebar":
            # 切换侧面板可见性（活动栏始终保持可见）
            if self.side_panel.isVisible():
                self.side_panel.hide()
            else:
                self.side_panel.show()
        elif action_id == "toggle_explorer":
            # 切换到资源管理器
            self.activity_bar.set_activity("explorer")
        elif action_id == "toggle_search":
            # 切换到搜索
            self.activity_bar.set_activity("search")
        elif action_id == "toggle_git":
            # 切换到源码管理
            self.activity_bar.set_activity("source_control")
        elif action_id == "diff_summary":
            # ★ v5.0 Whitebox: 变更汇总
            self._show_diff_summary()
        elif action_id == "toggle_panel":
            # 切换底部面板
            if self.bottom_panel.isVisible():
                self.bottom_panel.hide()
            else:
                self.bottom_panel.show()
        elif action_id == "toggle_terminal":
            # 切换到底部终端Tab
            self.bottom_panel.tabs.setCurrentIndex(0)  # Lemon 终端
            if not self.bottom_panel.isVisible():
                self.bottom_panel.show()

        # 转到操作
        elif action_id == "go_to_file":
            # ★ 转到文件
            self._show_go_to_file_dialog()
        elif action_id == "go_to_line":
            # ★ 转到行
            self._show_go_to_line_dialog()
        elif action_id == "go_to_symbol":
            self.bottom_panel.log_output("[转到] 转到符号功能", INFO)
        elif action_id == "go_to_definition":
            self.bottom_panel.log_output("[转到] 转到定义 (F12)", INFO)

        # 运行操作
        elif action_id == "run":
            # ★ 运行当前文件
            self._run_current_file()
        elif action_id == "debug":
            # ★ 调试当前文件
            self._debug_current_file()
        elif action_id == "stop":
            # ★ 停止运行
            self._stop_running()
        elif action_id == "run_config":
            self.bottom_panel.log_output("[运行] 打开运行配置", INFO)

        # 帮助操作
        elif action_id == "about":
            # ★ 关于对话框
            self._show_about_dialog()
        elif action_id == "shortcuts":
            # ★ 快捷键帮助
            self._show_shortcuts_dialog()
        elif action_id == "documentation":
            self.bottom_panel.log_output("[帮助] 打开文档", INFO)

        # ★ v4.7.17: 菜单栏搜索/积分新动作
        elif action_id == "search_submit":
            query = self.menu_bar.get_pending_search_query()
            if query:
                self.bottom_panel.log_output(f"[搜索] {query}", INFO)
                self.activity_bar.set_activity("search")
        elif action_id == "show_credits":
            self._show_credits_panel()

    # ================================================================
    # 查找/替换对话框
    # ================================================================
    def _show_diff_summary(self):
        """★ v5.0 Whitebox: 变更汇总 — 从 RunRegistry 获取 Artifact 并弹出 DiffSummaryDialog"""
        try:
            if not hasattr(self, 'whitebox_panel') or not self.whitebox_panel:
                QMessageBox.information(self, "变更汇总", "白盒面板未初始化")
                return
            from ui.whitebox.state_model import ArtifactKind
            artifacts = self.whitebox_panel.registry.get_all_artifacts()
            file_artifacts = [a for a in artifacts
                              if a.kind in (ArtifactKind.FILE_DIFF, ArtifactKind.FILE_CREATED)]
            if not file_artifacts:
                QMessageBox.information(self, "变更汇总", "当前没有文件变更")
                return
            from ui.whitebox.diff_summary_dialog import DiffSummaryDialog
            dialog = DiffSummaryDialog(file_artifacts, self.whitebox_panel.registry, self)
            dialog.artifact_accepted.connect(
                lambda aid: self.bottom_panel.log_output(f"[白盒] 已接受变更: {aid[:8]}", SUCCESS))
            dialog.artifact_rejected.connect(
                lambda aid: self.bottom_panel.log_output(f"[白盒] 已拒绝变更: {aid[:8]}", WARNING))
            dialog.exec_()
        except Exception as e:
            print(f"[DiffSummary] 错误: {e}", flush=True)
            QMessageBox.warning(self, "变更汇总", f"无法显示变更: {e}")

    def _show_find_dialog(self):
        """显示查找对话框"""
        current = self.editor_tabs.currentWidget()
        if not isinstance(current, CodeEditor):
            QMessageBox.information(self, "查找", "请先打开一个编辑器标签页")
            return
        
        text, ok = QInputDialog.getText(self, "查找", "输入要查找的文本:")
        if ok and text:
            found = current.find_text(text, forward=True)
            if not found:
                # 从开头继续搜索
                cursor = current.editor.textCursor()
                cursor.movePosition(QTextCursor.Start)
                current.editor.setTextCursor(cursor)
                found = current.find_text(text, forward=True)
            if found:
                self.bottom_panel.log_output(f"[查找] 找到: {text}", INFO)
            else:
                self.bottom_panel.log_output(f"[查找] 未找到: {text}", WARNING)

    def _show_replace_dialog(self):
        """显示替换对话框"""
        current = self.editor_tabs.currentWidget()
        if not isinstance(current, CodeEditor):
            QMessageBox.information(self, "替换", "请先打开一个编辑器标签页")
            return
        
        find_text, ok1 = QInputDialog.getText(self, "替换", "查找文本:")
        if ok1 and find_text:
            replace_text, ok2 = QInputDialog.getText(self, "替换", "替换为:")
            if ok2:
                # 询问是否全部替换
                reply = QMessageBox.question(
                    self, "替换", 
                    f"将 '{find_text}' 替换为 '{replace_text}'？\n\n是=替换全部\n否=替换当前\n取消=取消",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
                )
                if reply == QMessageBox.Yes:
                    count = current.replace_text(find_text, replace_text, replace_all=True)
                    self.bottom_panel.log_output(f"[替换] 已替换 {count} 处", SUCCESS)
                elif reply == QMessageBox.No:
                    count = current.replace_text(find_text, replace_text, replace_all=False)
                    self.bottom_panel.log_output(f"[替换] 已替换 {count} 处", SUCCESS)

    # ================================================================
    # 转到对话框
    # ================================================================
    def _show_go_to_file_dialog(self):
        """显示转到文件对话框"""
        files = []
        for i in range(self.editor_tabs.count()):
            widget = self.editor_tabs.widget(i)
            if isinstance(widget, CodeEditor) and widget.file_path:
                files.append(widget.file_path)
        
        if not files:
            QMessageBox.information(self, "转到文件", "没有打开的文件")
            return
        
        from PyQt5.QtWidgets import QInputDialog
        file_name, ok = QInputDialog.getItem(
            self, "转到文件", "选择文件:", files, 0, False
        )
        if ok and file_name:
            # 找到并切换到该文件的标签
            for i in range(self.editor_tabs.count()):
                widget = self.editor_tabs.widget(i)
                if isinstance(widget, CodeEditor) and widget.file_path == file_name:
                    self.editor_tabs.setCurrentIndex(i)
                    self.bottom_panel.log_output(f"[转到] 已切换到: {file_name}", INFO)
                    break

    def _show_go_to_line_dialog(self):
        """显示转到行对话框"""
        current = self.editor_tabs.currentWidget()
        if not isinstance(current, CodeEditor):
            QMessageBox.information(self, "转到行", "请先打开一个编辑器标签页")
            return
        
        text, ok = QInputDialog.getText(self, "转到行", "输入行号:")
        if ok and text:
            try:
                line_num = int(text)
                doc = current.editor.document()
                if 1 <= line_num <= doc.blockCount():
                    cursor = QTextCursor(doc.findBlockByNumber(line_num - 1))
                    current.editor.setTextCursor(cursor)
                    current.editor.centerCursor()
                    self.bottom_panel.log_output(f"[转到] 已跳转到第 {line_num} 行", INFO)
                else:
                    self.bottom_panel.log_output(f"[转到] 行号超出范围 (1-{doc.blockCount()})", WARNING)
            except ValueError:
                QMessageBox.warning(self, "转到行", "请输入有效的数字")

    # ================================================================
    # 运行功能
    # ================================================================
    def _run_current_file(self):
        """运行当前文件"""
        import subprocess
        current = self.editor_tabs.currentWidget()
        if not isinstance(current, CodeEditor) or not current.file_path:
            QMessageBox.information(self, "运行", "请先打开一个文件")
            return
        
        file_path = current.file_path
        ext = os.path.splitext(file_path)[1].lower()
        
        # 切换到终端
        if not self.bottom_panel.isVisible():
            self.bottom_panel.show()
        
        # 根据文件类型运行
        run_commands = {
            '.py': ['python', file_path],
            '.js': ['node', file_path],
            '.go': ['go', 'run', file_path],
            '.sh': ['bash', file_path],
        }
        
        cmd = run_commands.get(ext)
        if cmd:
            self.bottom_panel.log_output(f"[运行] 执行: {' '.join(cmd)}", INFO)
            try:
                # 使用 subprocess 执行命令
                result = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    timeout=30,
                    cwd=os.path.dirname(file_path) or '.'
                )
                if result.stdout:
                    self.bottom_panel.log_output(result.stdout, SUCCESS)
                if result.stderr:
                    self.bottom_panel.log_output(result.stderr, ERROR)
                if result.returncode == 0:
                    self.bottom_panel.log_output(f"[运行] 执行成功", SUCCESS)
                else:
                    self.bottom_panel.log_output(f"[运行] 退出码: {result.returncode}", WARNING)
            except subprocess.TimeoutExpired:
                self.bottom_panel.log_output("[运行] 执行超时", WARNING)
            except Exception as e:
                self.bottom_panel.log_output(f"[运行] 执行失败: {e}", ERROR)
        else:
            self.bottom_panel.log_output(f"[运行] 不支持的文件类型: {ext}", WARNING)
            # 仍然可以在终端中手动运行
            self.bottom_panel.log_output(f"[运行] 请在终端中手动运行此文件", INFO)

    def _debug_current_file(self):
        """调试当前文件"""
        current = self.editor_tabs.currentWidget()
        if not isinstance(current, CodeEditor) or not current.file_path:
            QMessageBox.information(self, "调试", "请先打开一个文件")
            return
        
        file_path = current.file_path
        ext = os.path.splitext(file_path)[1].lower()
        
        debug_commands = {
            '.py': ['python', '-m', 'pdb', file_path],
            '.js': ['node', '--inspect', file_path],
            '.go': ['dlv', 'debug', file_path],
        }
        
        cmd = debug_commands.get(ext)
        if cmd:
            self.bottom_panel.log_output(f"[调试] 启动调试: {' '.join(cmd)}", INFO)
            self.bottom_panel.log_output("[调试] 调试器已启动，请在终端中操作", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[调试] {ext} 文件类型暂无内置调试支持，使用运行代替", WARNING)
            self._run_current_file()

    def _stop_running(self):
        """停止运行"""
        self.bottom_panel.log_output("[停止] 用户请求停止运行", INFO)
        QMessageBox.information(self, "停止", "已发送停止请求（如果程序在终端运行，请在终端中按 Ctrl+C 停止）")

    # ================================================================
    # 帮助对话框
    # ================================================================
    # ★ v4.7.17: 积分用量统计面板（模拟数据）
    def _show_credits_panel(self):
        """弹出积分用量统计面板（CodeBuddy 风格模拟数据）"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar
        dlg = QDialog(self)
        dlg.setWindowTitle("积分用量统计 · Lemon Code")
        dlg.setFixedSize(340, 380)
        dlg.setStyleSheet(f"""
            QDialog {{
                background: {BG_ROOT};
                border: 1px solid {BORDER_SUBTLE};
                border-radius: 14px;
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
                font-family: 'Microsoft YaHei', sans-serif;
            }}
            QProgressBar {{
                border: none; border-radius: 4px;
                background: {BG_SURFACE}; height: 6px;
            }}
            QProgressBar::chunk {{
                background: {Lemon.ACCENT_GOLD}; border-radius: 4px;
            }}
        """)
        from PyQt5.QtCore import Qt as QtCore
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("⭐ 积分用量统计")
        title.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {Lemon.ACCENT_GOLD};")
        title.setAlignment(QtCore.AlignCenter)
        layout.addWidget(title)

        # 模拟数据：总积分 2,010，已用 156，剩余 1,854
        total, used = 2010, 156
        remaining = total - used
        pct = used / total

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(pct * 100))
        layout.addWidget(bar)

        for label, value, color in [
            ("总积分", f"{total:,}", Lemon.ACCENT_GOLD),
            ("已使用", f"{used:,}", Lemon.ERROR),
            ("剩余", f"{remaining:,}", Lemon.ACCENT_GREEN),
        ]:
            row = QLabel(f"<span style='color:{TEXT_TERTIARY};'>{label}</span>"
                         f"  <b style='color:{color};font-size:15px;'>{value}</b>")
            row.setStyleSheet("padding: 2px 0;")
            layout.addWidget(row)

        sep = QLabel("")
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {BORDER_SUBTLE};")
        layout.addWidget(sep)

        for label, value in [
            ("今日 Tokens", "12,450"),
            ("累计 Tokens", "1,248,300"),
            ("总对话数", "847"),
        ]:
            row = QLabel(f"<span style='color:{TEXT_MUTED};'>{label}</span>"
                         f"  <span style='color:{TEXT_PRIMARY};'>{value}</span>")
            row.setStyleSheet("padding: 2px 0;")
            layout.addWidget(row)

        layout.addStretch()
        dlg.exec_()

    def _show_about_dialog(self):
        """显示关于对话框"""
        QMessageBox.about(
            self, "关于 LemonCode",
            "<h3>LemonCode Agent v4.0</h3>"
            "<p>由 Lemon Auto 驱动的扩展 Agent</p>"
            "<p>支持 MIMO Code、Ollama、DeepSeek 等多种 AI 引擎</p>"
            "<p>基于 Trae 开发，遵循二次开发协议，保留原始技术引用说明</p>"
            "<hr>"
            "<p>架构: 容器模式 → 输入 → Agent → Lemon Code → 分发 UI</p>"
        )

    def _show_shortcuts_dialog(self):
        """显示快捷键对话框"""
        shortcuts_text = """
        <h3>键盘快捷键</h3>
        <table>
        <tr><td><b>文件</b></td><td></td></tr>
        <tr><td>新建文件</td><td>Ctrl+N</td></tr>
        <tr><td>打开文件夹</td><td>Ctrl+O</td></tr>
        <tr><td>保存</td><td>Ctrl+S</td></tr>
        <tr><td>全部保存</td><td>Ctrl+Shift+S</td></tr>
        <tr><td>关闭标签</td><td>Ctrl+W</td></tr>
        <tr><td><b>编辑</b></td><td></td></tr>
        <tr><td>撤销</td><td>Ctrl+Z</td></tr>
        <tr><td>重做</td><td>Ctrl+Y</td></tr>
        <tr><td>剪切</td><td>Ctrl+X</td></tr>
        <tr><td>复制</td><td>Ctrl+C</td></tr>
        <tr><td>粘贴</td><td>Ctrl+V</td></tr>
        <tr><td>查找</td><td>Ctrl+F</td></tr>
        <tr><td>替换</td><td>Ctrl+H</td></tr>
        <tr><td>全选</td><td>Ctrl+A</td></tr>
        <tr><td><b>查看</b></td><td></td></tr>
        <tr><td>切换侧边栏</td><td>Ctrl+B</td></tr>
        <tr><td>切换面板</td><td>Ctrl+J</td></tr>
        <tr><td>切换终端</td><td>Ctrl+`</td></tr>
        <tr><td><b>运行</b></td><td></td></tr>
        <tr><td>运行</td><td>F5</td></tr>
        <tr><td>停止</td><td>Shift+F5</td></tr>
        </table>
        """
        msg = QMessageBox(self)
        msg.setWindowTitle("键盘快捷键")
        msg.setText(shortcuts_text)
        msg.setTextFormat(Qt.RichText)
        msg.exec_()

    def _on_side_search(self, query: str):
        """侧面板搜索请求"""
        self.bottom_panel.log_output(f"[搜索] 正在搜索: {query}", INFO)
        # 读取侧面板搜索选项
        case_sensitive = False
        use_regex = False
        try:
            if hasattr(self.side_panel, '_case_check'):
                case_sensitive = self.side_panel._case_check.isChecked()
            if hasattr(self.side_panel, '_regex_check'):
                use_regex = self.side_panel._regex_check.isChecked()
        except Exception:
            pass
        # 使用已有的全局搜索能力（支持结果弹窗、点击跳转、全部替换）
        self._do_global_search(query, case_sensitive=case_sensitive, use_regex=use_regex)
            
    def _on_side_git_commit(self, message: str):
        """侧面板 Git 提交请求"""
        if self.git_manager and self.git_manager.is_git_repo:
            success = self.git_manager.commit_all(message)
            if success:
                self.bottom_panel.log_output(f"[Git] 提交成功: {message}", SUCCESS)
                # 刷新 Git 面板
                self.side_panel._refresh_git()
            else:
                self.bottom_panel.log_output("[Git] 提交失败，请检查配置", ERROR)
        else:
            self.bottom_panel.log_output("[Git] 非 Git 仓库，无法提交", WARNING)

    # ================================================================
    # AI 生成提交信息（本地 Ollama 优先，云端 DeepSeek 自动降级）
    # ================================================================
    _AI_COMMIT_MODEL = "qwen3.5:4b"          # 本地代码专用模型（391: qwen2.5-coder 已清除）
    _AI_COMMIT_OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
    _AI_COMMIT_DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
    _AI_COMMIT_DEEPSEEK_MODEL = "deepseek-chat"

    def _build_commit_prompt(self, full_diff: str) -> str:
        """构造提交信息生成提示词"""
        return (
            "你是一个专业的 Git 提交信息助手。请根据下面的代码变更 diff，"
            "生成一条简洁、规范的中文 Git 提交信息。\n"
            "要求：\n"
            "1. 一句话概括本次变更的核心内容，不超过 50 字\n"
            "2. 如果涉及多个改动，用 '；' 连接\n"
            "3. 只输出提交信息本身，不要多余解释、不要加引号\n"
            "4. 遵循 Conventional Commits 风格（feat/fix/refactor/docs/perf/test 等前缀可选）\n\n"
            "以下是 git diff 内容：\n```\n" + full_diff + "\n```"
        )

    def _clean_commit_text(self, text: str) -> str:
        """清理模型返回的提交信息"""
        text = (text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text.replace("```", "")
        if text.endswith("```"):
            text = text[:-3]
        return text.strip().strip('"').strip("'").strip("\n")

    def _generate_via_ollama(self, prompt: str) -> str:
        """通过本地 Ollama 生成"""
        import requests
        resp = requests.post(
            self._AI_COMMIT_OLLAMA_URL,
            json={"model": self._AI_COMMIT_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama 返回 HTTP {resp.status_code}")
        return self._clean_commit_text(resp.json().get("response", ""))

    def _generate_via_unified(self, prompt: str, engine: str = "ollama",
                               model: str = None, api_key: str = None) -> str:
        """经 EngineManager 统一入口生成（铁律：AI 调用必须走 EngineManager）。

        任一环节异常都抛出，由调用方回退到直连实现，保证不断路。
        engine 取值：'ollama' / 'deepseek'。
        """
        from shared.engine_manager import get_engine_manager
        mgr = get_engine_manager()
        kw = {"engine": engine, "model": model or None}
        if engine == "deepseek" and api_key:
            kw["api_key"] = api_key
        text = mgr.chat(prompt, **kw)
        return self._clean_commit_text(text)

    def _generate_via_deepseek(self, prompt: str) -> str:
        """通过云端 DeepSeek 生成"""
        import requests, os as _os
        # 查找 API Key：优先内存配置（设置界面），其次环境变量，最后 ~/.deepseek_key
        api_key = getattr(self, '_AI_COMMIT_DEEPSEEK_KEY_OVERRIDE', "")
        if not api_key:
            api_key = _os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            try:
                kf = _os.path.expanduser("~/.deepseek_key")
                if _os.path.exists(kf):
                    api_key = open(kf, "r").read().strip()
            except Exception:
                pass
        if not api_key:
            # ★ 兼容项目内 key 文件（standard_mode/.deepseek_key 或 lemon_agent/.deepseek_key）
            for _kf in (
                _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), ".deepseek_key"),
                _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), ".deepseek_key"),
            ):
                try:
                    if _os.path.exists(_kf):
                        api_key = open(_kf, "r").read().strip()
                        if api_key:
                            break
                except Exception:
                    pass
        if not api_key:
            raise RuntimeError("未配置 DeepSeek API Key（设置界面 / DEEPSEEK_API_KEY / ~/.deepseek_key）")
        resp = requests.post(
            self._AI_COMMIT_DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": self._AI_COMMIT_DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=120,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek 返回 HTTP {resp.status_code}: {resp.text[:120]}")
        content = resp.json()["choices"][0]["message"]["content"]
        return self._clean_commit_text(content)

    def _on_ai_generate_commit(self):
        """AI 生成提交信息 — 本地 Ollama 优先，失败自动降级 DeepSeek"""
        if not self.git_manager or not self.git_manager.is_git_repo:
            self.bottom_panel.log_output("[Git] 非 Git 仓库，无法生成提交信息", WARNING)
            self._ai_commit_reset_btn()
            return

        # 取 diff（含未暂存与已暂存）
        diff = self.git_manager.get_diff(staged=False)
        staged_diff = self.git_manager.get_diff(staged=True)
        if not diff and not staged_diff:
            self.bottom_panel.log_output("[Git] 没有变更，无法生成提交信息", WARNING)
            self.side_panel._commit_input.setPlainText("")
            self._ai_commit_reset_btn()
            return

        full_diff = (staged_diff + "\n" + diff).strip()[:6000]
        prompt = self._build_commit_prompt(full_diff)
        forced = getattr(self, '_ai_engine_pref_forced', False)
        pref = getattr(self, '_ai_engine_pref', 'ollama')
        if forced and pref == 'deepseek':
            self.bottom_panel.log_output(f"[Git] 正在用 DeepSeek 生成提交信息...", INFO)
        else:
            self.bottom_panel.log_output(f"[Git] 正在生成提交信息（本地 {self._AI_COMMIT_MODEL}）...", INFO)

        def _worker():
            # 用户显式选择 DeepSeek 时，直接使用云端
            if forced and pref == 'deepseek':
                try:
                    text = self._generate_via_unified(prompt, engine="deepseek",
                                                      model=self._AI_COMMIT_DEEPSEEK_MODEL,
                                                      api_key=getattr(self, '_AI_COMMIT_DEEPSEEK_KEY_OVERRIDE', "") or None)
                    if text:
                        return text, "DeepSeek 云端 (统一入口)"
                    raise RuntimeError("DeepSeek 未返回有效内容")
                except Exception as e:
                    self.bottom_panel.log_output(f"[Git] 统一入口 DeepSeek 失败: {e}，降级直连", WARNING)
                    try:
                        text = self._generate_via_deepseek(prompt)
                        if text:
                            return text, "DeepSeek 云端"
                        raise RuntimeError("DeepSeek 未返回有效内容")
                    except Exception as e2:
                        return None, str(e2)
            # 默认：经统一入口（本地 Ollama 优先），失败降级直连 Ollama → DeepSeek
            try:
                text = self._generate_via_unified(prompt, engine="ollama", model=self._AI_COMMIT_MODEL)
                if text:
                    return text, "本地 Ollama (统一入口)"
            except Exception as e:
                self.bottom_panel.log_output(f"[Git] 统一入口 Ollama 不可用: {e}，降级直连", WARNING)
            try:
                text = self._generate_via_ollama(prompt)
                if text:
                    return text, "本地 Ollama"
            except Exception as e:
                self.bottom_panel.log_output(f"[Git] 本地 Ollama 不可用: {e}，降级到 DeepSeek", WARNING)
            try:
                text = self._generate_via_deepseek(prompt)
                if text:
                    return text, "DeepSeek 云端"
                raise RuntimeError("DeepSeek 未返回有效内容")
            except Exception as e:
                return None, str(e)

        def _done(result):
            msg, source = result
            self._ai_commit_reset_btn()
            if msg is None:
                self.bottom_panel.log_output(f"[Git] AI 生成失败: {source}", ERROR)
                self.side_panel._status_label.setText("AI 生成失败，请检查模型配置")
                return
            self.side_panel._commit_input.setPlainText(msg)
            self.bottom_panel.log_output(f"[Git] AI 提交信息（{source}）: {msg}", SUCCESS)
            self.side_panel._status_label.setText("已生成提交信息")

        threading.Thread(target=lambda: self._ai_run_safe(_worker, _done), daemon=True).start()

    def _ai_run_safe(self, worker, done):
        """在子线程执行并安全回调 UI"""
        try:
            result = worker()
        except Exception as e:
            result = (None, str(e))
        # 通过 QTimer 回到主线程更新 UI
        QTimer.singleShot(0, lambda: done(result))

    def _ai_commit_reset_btn(self):
        """恢复 AI 生成按钮状态"""
        try:
            self.side_panel._ai_commit_btn.setText("AI 生成提交信息")
            self.side_panel._ai_commit_btn.setEnabled(True)
        except Exception:
            pass

    def _on_branch_switch(self, name: str):
        """切换 Git 分支"""
        if not self.git_manager or not self.git_manager.is_git_repo:
            return
        self.bottom_panel.log_output(f"[Git] 切换到分支: {name}", INFO)
        success, msg = self.git_manager.checkout_branch(name)
        if success:
            self.bottom_panel.log_output(f"[Git] {msg}", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[Git] 切换失败: {msg}", ERROR)
        self.side_panel._refresh_git()

    def _on_branch_create(self, name: str):
        """创建 Git 分支"""
        if not self.git_manager or not self.git_manager.is_git_repo:
            return
        self.bottom_panel.log_output(f"[Git] 创建分支: {name}", INFO)
        success, msg = self.git_manager.create_branch(name)
        if success:
            self.bottom_panel.log_output(f"[Git] {msg}", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[Git] 创建失败: {msg}", ERROR)
        self.side_panel._refresh_git()

    def _on_branch_delete(self, name: str):
        """删除 Git 分支"""
        if not self.git_manager or not self.git_manager.is_git_repo:
            return
        self.bottom_panel.log_output(f"[Git] 删除分支: {name}", INFO)
        success, msg = self.git_manager.delete_branch(name)
        if success:
            self.bottom_panel.log_output(f"[Git] {msg}", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[Git] 删除失败: {msg}", ERROR)
        self.side_panel._refresh_git()

    def _on_stash(self, message: str = ""):
        """暂存工作区变更"""
        if not self.git_manager or not self.git_manager.is_git_repo:
            return
        # 解析是否包含未追踪文件
        include_untracked = (message == "INCLUDE_UNTRACKED")
        if include_untracked:
            message = ""
        self.bottom_panel.log_output(
            f"[Git] 暂存工作区变更{'（含未追踪）' if include_untracked else ''}...", INFO)
        success, msg = self.git_manager.stash(message, include_untracked=include_untracked)
        if success:
            self.bottom_panel.log_output(f"[Git] {msg}", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[Git] 暂存失败: {msg}", ERROR)
        self.side_panel._refresh_git()

    def _on_stash_pop(self):
        """恢复最近一次暂存"""
        if not self.git_manager or not self.git_manager.is_git_repo:
            return
        self.bottom_panel.log_output("[Git] 恢复暂存内容...", INFO)
        success, msg = self.git_manager.stash_pop()
        if success:
            self.bottom_panel.log_output(f"[Git] {msg}", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[Git] 恢复失败: {msg}", ERROR)
        self.side_panel._refresh_git()

    def _on_stash_apply(self, stash_ref: str):
        """应用指定 stash（不删除）"""
        if not self.git_manager or not self.git_manager.is_git_repo:
            return
        self.bottom_panel.log_output(f"[Git] 应用 {stash_ref}...", INFO)
        success, msg = self.git_manager.stash_apply(stash_ref)
        if success:
            self.bottom_panel.log_output(f"[Git] {msg}", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[Git] 应用失败: {msg}", ERROR)
        self.side_panel._refresh_git()

    def _on_stash_drop(self, stash_ref: str):
        """丢弃指定 stash"""
        if not self.git_manager or not self.git_manager.is_git_repo:
            return
        self.bottom_panel.log_output(f"[Git] 丢弃 {stash_ref}...", INFO)
        success, msg = self.git_manager.stash_drop(stash_ref)
        if success:
            self.bottom_panel.log_output(f"[Git] {msg}", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[Git] 丢弃失败: {msg}", ERROR)
        self.side_panel._refresh_git()

    def _on_git_push(self):
        """推送当前分支到远程（线程化，避免阻塞 UI）"""
        if not self.git_manager or not self.git_manager.is_git_repo:
            self.bottom_panel.log_output("[Git] 非 Git 仓库", WARNING)
            return
        self.bottom_panel.log_output("[Git] 正在推送...", INFO)

        def _worker():
            return self.git_manager.push()

        def _done(result):
            success, msg = result
            if success:
                self.bottom_panel.log_output(f"[Git] 推送成功: {msg}", SUCCESS)
            else:
                self.bottom_panel.log_output(f"[Git] 推送失败: {msg}", ERROR)
            self.side_panel._refresh_git()

        threading.Thread(target=lambda: self._ai_run_safe(_worker, _done), daemon=True).start()

    def _on_git_pull(self):
        """从远程拉取合并（线程化，避免阻塞 UI）"""
        if not self.git_manager or not self.git_manager.is_git_repo:
            self.bottom_panel.log_output("[Git] 非 Git 仓库", WARNING)
            return
        self.bottom_panel.log_output("[Git] 正在拉取...", INFO)

        def _worker():
            return self.git_manager.pull()

        def _done(result):
            success, msg = result
            if success:
                self.bottom_panel.log_output(f"[Git] 拉取成功: {msg}", SUCCESS)
            else:
                self.bottom_panel.log_output(f"[Git] 拉取失败: {msg}", ERROR)
            self.side_panel._refresh_git()

        threading.Thread(target=lambda: self._ai_run_safe(_worker, _done), daemon=True).start()

    def _on_settings_saved(self, config: dict):
        """应用侧栏设置 — 更新 AI 提交信息生成的引擎配置并持久化"""
        try:
            engine = "deepseek" if config.get("engine") == 1 else "ollama"
            self._ai_engine_pref = engine
            self._ai_engine_pref_forced = True
            if config.get("ollama_model"):
                self._AI_COMMIT_MODEL = config["ollama_model"]
            if config.get("ollama_url"):
                url = config["ollama_url"].rstrip("/")
                self._AI_COMMIT_OLLAMA_URL = url + "/api/generate"
            if config.get("deepseek_model"):
                self._AI_COMMIT_DEEPSEEK_MODEL = config["deepseek_model"]
            if config.get("deepseek_key"):
                # 仅内存中生效，不写入磁盘避免泄露
                self._AI_COMMIT_DEEPSEEK_KEY_OVERRIDE = config["deepseek_key"]
            # 持久化非敏感配置到 SettingsManager
            try:
                from core.settings_manager import get_settings_manager
                sm = get_settings_manager()
                sm.set("ai.git_commit.engine", engine)
                sm.set("ai.git_commit.ollama_model", self._AI_COMMIT_MODEL)
                sm.set("ai.git_commit.ollama_url", config.get("ollama_url") or "http://127.0.0.1:11434")
                sm.set("ai.git_commit.deepseek_model", self._AI_COMMIT_DEEPSEEK_MODEL)
                sm.save()
                self.bottom_panel.log_output("[设置] 已持久化到配置文件", SUCCESS)
            except Exception as e:
                self.bottom_panel.log_output(f"[设置] 持久化失败: {e}", WARNING)
            self.bottom_panel.log_output(
                f"[设置] 提交信息引擎已设为: {engine} (本地模型 {self._AI_COMMIT_MODEL})",
                SUCCESS)
        except Exception as e:
            self.bottom_panel.log_output(f"[设置] 保存失败: {e}", ERROR)

    def _load_ai_commit_settings(self):
        """从 SettingsManager 加载已保存的 AI 提交信息引擎配置"""
        try:
            from core.settings_manager import get_settings_manager
            sm = get_settings_manager()
            gc = sm.get("ai.git_commit", {}) or {}
            engine = gc.get("engine", "ollama")
            if gc.get("ollama_model"):
                self._AI_COMMIT_MODEL = gc["ollama_model"]
            if gc.get("ollama_url"):
                self._AI_COMMIT_OLLAMA_URL = gc["ollama_url"].rstrip("/") + "/api/generate"
            if gc.get("deepseek_model"):
                self._AI_COMMIT_DEEPSEEK_MODEL = gc["deepseek_model"]
            self._ai_engine_pref = engine
            self._ai_engine_pref_forced = True
            self.bottom_panel.log_output(
                f"[设置] 已加载提交信息引擎: {engine} (模型 {self._AI_COMMIT_MODEL})", INFO)
        except Exception as e:
            self.bottom_panel.log_output(f"[设置] 加载失败: {e}", WARNING)

    def _on_view_all_diff(self):
        """查看全部变更文件的 diff（HEAD vs 当前）— 合并到单一视图"""
        import difflib
        if not self.git_manager or not self.git_manager.is_git_repo:
            self.bottom_panel.log_output("[Git] 非 Git 仓库", WARNING)
            return
        status_map = self.git_manager._status_cache
        if not status_map:
            self.bottom_panel.log_output("[Git] 工作区无变更", INFO)
            return

        merged_lines = []
        new_files = []
        for rel_path in sorted(status_map.keys()):
            head_content = self.git_manager.get_file_at_head(rel_path)
            abs_path = os.path.join(self.git_manager.project_path, rel_path)
            current_content = None
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                        current_content = f.read()
                except Exception:
                    current_content = None

            merged_lines.append(f"===== {rel_path} =====")
            if head_content is None and current_content is not None:
                # 未追踪新文件，无法对比 HEAD，单独处理
                new_files.append(rel_path)
                merged_lines.append(f"[新增文件，共 {len(current_content.splitlines())} 行，无 HEAD 版本]")
                continue
            if current_content is None:
                # 已删除文件
                merged_lines.append(f"[已删除文件，原 {len((head_content or '').splitlines())} 行]")
                continue
            # 生成 unified diff
            old_lines = (head_content or "").splitlines()
            new_lines = current_content.splitlines()
            diff_lines = list(difflib.unified_diff(
                old_lines, new_lines, fromfile=f"{rel_path} (HEAD)", tofile=f"{rel_path} (工作区)", lineterm=""))
            if diff_lines:
                merged_lines.extend(diff_lines)
            else:
                merged_lines.append("[无内容差异]")

        merged_content = "\n".join(merged_lines)
        # 打开一个合并 diff 视图
        self._open_diff_tab("全部变更", merged_content, [""], "所有变更文件合并 Diff")

        for nf in new_files:
            abs_path = os.path.join(self.git_manager.project_path, nf)
            self.bottom_panel.log_output(f"[Git] 新增文件（已在下方展示）: {nf}", INFO)
        self.bottom_panel.log_output(f"[Git] 已合并展示 {len(status_map)} 个变更文件的 diff", SUCCESS)

    def _on_agent_state_signal(self, state: str):
        """★ v3.81: agent 状态变化 — 转发到标题栏三色灯"""
        try:
            light = self.title_bar.agent_status_light
            if light is not None:
                light.set_state(state)
        except Exception:
            pass

    def _new_untitled_file(self):
        """新建未命名文件"""
        untitled_count = getattr(self, '_untitled_count', 0) + 1
        self._untitled_count = untitled_count
        rel_path = f"untitled-{untitled_count}.py"
        
        editor = CodeEditor()
        editor.set_code("", file_path=rel_path)
        editor.save_requested.connect(lambda fp, c: self._save_file(fp, c))
        editor.content_changed.connect(lambda: self._on_editor_content_changed(editor))
        
        idx = self.editor_tabs.addTab(editor, rel_path)
        self.editor_tabs.setCurrentIndex(idx)
        self.breadcrumb_label.setText(f"  {self.engine.project_path} > {rel_path}")
        self.bottom_panel.log_output(f"[文件] 新建文件: {rel_path}", INFO)

    def _create_single_ai_page(self):
        """创建单AI多窗口模式页面 — 使用 SingleAIMultiWindowPanel"""
        try:
            from ui.single_ai_multi_window import SingleAIMultiWindowPanel
            self.single_ai_panel = SingleAIMultiWindowPanel()
            self.single_ai_panel.command_sent.connect(self._on_single_ai_command)
            print("[_create_single_ai_page] SingleAIMultiWindowPanel 创建成功", flush=True)
            return self.single_ai_panel
        except ImportError as e:
            print(f"[_create_single_ai_page] 导入失败: {e}，使用降级界面", flush=True)
            page = QWidget()
            label = QLabel("单AI多窗口模式 — 功能开发中")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 16px;")
            layout = QVBoxLayout(page)
            layout.addWidget(label)
            return page

    def _on_single_ai_command(self, task_id: str, command: str):
        """处理单AI多窗口面板发送的命令 — 转发到 serve_bridge"""
        print(f"[单AI多窗口] 任务 {task_id} 发送命令: {command[:50]}...", flush=True)
        # 通过 serve_bridge 发送到 AI 引擎
        if hasattr(self, 'serve_bridge') and self.serve_bridge:
            try:
                self.serve_bridge.send_message(command)
                self.bottom_panel.log_output(f"[单AI-{task_id}] 已发送: {command[:60]}", INFO)
            except Exception as e:
                self.bottom_panel.log_output(f"[单AI-{task_id}] 发送失败: {e}", ERROR)
                if hasattr(self, 'single_ai_panel') and hasattr(self.single_ai_panel, 'append_ai_response'):
                    self.single_ai_panel.append_ai_response(task_id, f"[错误] 发送失败: {e}")
        else:
            # 模拟响应（当 serve_bridge 不可用时）
            if hasattr(self, 'single_ai_panel') and hasattr(self.single_ai_panel, 'append_ai_response'):
                self.single_ai_panel.append_ai_response(
                    task_id, 
                    f"[系统] 收到命令: {command}\n[提示] AI 引擎未连接，请检查 Lemon Code 服务是否运行。"
                )

    def _create_multi_ai_page(self):
        """创建多AI模型模式页面 — 使用新的 MultiAICooperatePanel"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 尝试导入新面板（从本地 ui/ 目录导入）
        try:
            from ui.multi_ai_panel import MultiAICooperatePanel
            self.multi_ai_cooperate_panel = MultiAICooperatePanel()
            layout.addWidget(self.multi_ai_cooperate_panel)
            print("[_create_multi_ai_page] 使用新的 MultiAICooperatePanel", flush=True)
        except ImportError as e:
            print(f"[_create_multi_ai_page] 导入 MultiAICooperatePanel 失败: {e}，使用旧版", flush=True)
            # 降级：使用旧的 WorkGroupPanel
            try:
                from ui.work_group_chat_panel import WorkGroupPanel
                self.work_group_panel = WorkGroupPanel()
                layout.addWidget(self.work_group_panel, 1)
            except Exception as e2:
                # 最终降级：创建一个简化的多AI面板
                header = QLabel(" 多AI模型模式 — 并行执行批量任务")
                header.setStyleSheet(f"""
                    QLabel {{
                        background: {BG_ROOT};
                        color: {XIAOMI_ORANGE};
                        font-size: 16px;
                        font-weight: bold;
                        padding: 12px 20px;
                        border-bottom: 2px solid {XIAOMI_ORANGE};
                    }}
                """)
                layout.addWidget(header)

                placeholder = QLabel("多AI模型模式正在加载...")
                placeholder.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 14px; padding: 20px;")
                placeholder.setAlignment(Qt.AlignCenter)
                layout.addWidget(placeholder)

        return page

    def _create_hybrid_page(self):
        """创建混合模式页面 — 多Agent协同监控系统（Web版）"""
        print("[_create_hybrid_page] 开始创建（Web版）...", flush=True)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        try:
            # ★ 优先使用最新的Web混合模式面板
            from ui.hybrid_mode_web_panel import HybridModeWebPanel
            self.hybrid_mode_panel = HybridModeWebPanel(engine_manager=getattr(self, '_engine_manager', None))
            layout.addWidget(self.hybrid_mode_panel)

            # 连接混合模式面板的信号
            self.hybrid_mode_panel.command_sent.connect(
                lambda cmd: self.bottom_panel.log_output(f"[混合模式] {cmd}", INFO)
            )
            self.hybrid_mode_panel.nav_action.connect(
                lambda action: self.bottom_panel.log_output(f"[混合模式-导航] {action}", INFO)
            )
            self.hybrid_mode_panel.workflow_step.connect(
                lambda step: self.bottom_panel.log_output(f"[混合模式-工作流] {step}", INFO)
            )
            # ★ v3.90: 连接真正会 emit 的 mode_switch_requested（修复绑定错位）
            # Web 面板 JS 请求切换模式 → 转到主窗口的服务模式切换流程
            self.hybrid_mode_panel.mode_switch_requested.connect(
                self._on_service_mode_switch, Qt.QueuedConnection
            )

            print("[_create_hybrid_page] HybridModeWebPanel 创建成功", flush=True)
        except Exception as e:
            print(f"[_create_hybrid_page] Web版创建失败: {e}，回退到原生版", flush=True)
            import traceback
            traceback.print_exc()

            # ★ 回退到原生PyQt5混合模式面板
            try:
                from ui.hybrid_mode_panel import HybridModePanel
                self.hybrid_mode_panel = HybridModePanel(parent=None)
                layout.addWidget(self.hybrid_mode_panel)

                self.hybrid_mode_panel.command_sent.connect(
                    lambda cmd: self.bottom_panel.log_output(f"[混合模式] {cmd}", INFO)
                )
                self.hybrid_mode_panel.nav_action.connect(
                    lambda action: self.bottom_panel.log_output(f"[混合模式-导航] {action}", INFO)
                )
                self.hybrid_mode_panel.workflow_step.connect(
                    lambda step: self.bottom_panel.log_output(f"[混合模式-工作流] {step}", INFO)
                )
                print("[_create_hybrid_page] 回退到原生HybridModePanel成功", flush=True)
            except Exception as e2:
                print(f"[_create_hybrid_page] 原生版也失败: {e2}", flush=True)
                header = QLabel(" 混合模式 — 加载失败")
                header.setStyleSheet(f"QLabel{{background:{BG_ROOT};color:{XIAOMI_ORANGE};font-size:16px;font-weight:bold;padding:12px 20px;border-bottom:2px solid {XIAOMI_ORANGE};}}")
                layout.addWidget(header)
                placeholder = QLabel("混合模式加载失败，请检查依赖")
                placeholder.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 14px; padding: 20px;")
                placeholder.setAlignment(Qt.AlignCenter)
                layout.addWidget(placeholder)

        print("[_create_hybrid_page] 创建完成", flush=True)
        return page

    def _connect_signals(self):
        # ====== ★ MIMO Serve Bridge 信号（主通信通道） ======

        # ★ v4.7.2: 首面板已在 _create_session_panel 中绑定，不再重复调用
        # _bind_mimo_panel 仅在 _create_session_panel 中调用一次

        # ★ v4.7.3: 注册跨会话指挥操作给咩咩引擎（总指挥工具 session_*）
        try:
            from ui.miemie_engine import register_session_ops
            register_session_ops({
                "list": lambda: self.session_workspace.list_sessions_info(),
                "read": lambda sid=None, mc=2000: self.session_workspace.read_session(sid, mc),
                "send": lambda sid, txt: self.session_workspace.send_to_session(sid, txt),
                "busy": lambda sid=None: self.session_workspace.is_session_busy(sid),
            })
        except Exception as e:
            print(f"[MIMOWindow] 注册会话指挥失败: {e}")

        # 标题栏菜单动作 -> 菜单动作处理
        self.title_bar.command_sent.connect(self._on_menu_action, Qt.QueuedConnection)

        # ★ v3.51: 引擎模式选择器 -> mimo_panel 模式管理器
        self.title_bar.mode_changed.connect(self._on_engine_mode_changed, Qt.QueuedConnection)

        # ★ TRAE 同款：布局三档切换按钮 -> MIMOWindow 布局迁移 + 持久化
        self.title_bar.layout_mode_changed.connect(self._set_ai_layout, Qt.QueuedConnection)

        self.title_bar.language_changed.connect(self._on_language_changed, Qt.QueuedConnection)

        # ★ v4.0: 模型选择变化 -> 引擎管理器
        self.title_bar.model_changed.connect(self._on_model_changed, Qt.QueuedConnection)

        # 输入框实时双向同步（底部终端）
        self.bottom_panel.mimo_console.input_field.textChanged.connect(self._on_bottom_console_input_sync)

        # serve 桥输出 -> 当前会话面板 + 底部交互终端
        # ★ v4.7.2: 面板随 Tab 切换，桥信号经 lambda 转发到当前激活面板实例
        # ★ 关键修复：右侧面板不再连接 delta_received（流式由 stream_token 处理）
        # 之前 delta 也走 on_output，导致每个 token 都创建新气泡，内容碎片化
        self.serve_bridge.output_received.connect(lambda *a: self.mimo_panel.on_output(*a), Qt.QueuedConnection)
        self.serve_bridge.thinking_received.connect(lambda *a: self.mimo_panel.on_thinking(*a), Qt.QueuedConnection)
        self.serve_bridge.status_received.connect(lambda *a: self.mimo_panel.on_status(*a), Qt.QueuedConnection)
        self.serve_bridge.tool_output.connect(lambda *a: self.mimo_panel.on_tool_output(*a), Qt.QueuedConnection)
        self.serve_bridge.file_preview.connect(lambda *a: self.mimo_panel.on_file_preview(*a), Qt.QueuedConnection)
        self.serve_bridge.error_occurred.connect(self._on_bridge_error, Qt.QueuedConnection)

        # ★ 流式输出信号 -> 当前会话面板
        self.serve_bridge.stream_started.connect(lambda *a: self.mimo_panel.on_stream_started(*a), Qt.QueuedConnection)
        self.serve_bridge.stream_token.connect(lambda *a: self.mimo_panel.on_stream_token(*a), Qt.QueuedConnection)
        self.serve_bridge.stream_ended.connect(lambda *a: self.mimo_panel.on_stream_ended(*a), Qt.QueuedConnection)
        self.serve_bridge.stream_error.connect(lambda *a: self.mimo_panel.on_stream_error(*a), Qt.QueuedConnection)

        # ★ 403T-4 Fix1: output_view / debug_view 裸 QTextEdit 接单信号
        # output_view 接 serve_bridge.output_received（完整输出 HTML）
        try:
            self.serve_bridge.output_received.connect(self.output_view.append, Qt.QueuedConnection)
        except Exception as _e_out_view:
            print(f"[403T-4] output_view signal connect skipped: {_e_out_view}", flush=True)
        # debug_view 接 serve_log / stream_token，加 [DEBUG] 前缀
        try:
            self.serve_bridge.stream_token.connect(
                lambda chunk: self.debug_view.append("[DEBUG] " + str(chunk)), Qt.QueuedConnection
            )
        except Exception as _e_dbg_view:
            print(f"[403T-4] debug_view signal connect skipped: {_e_dbg_view}", flush=True)

        # ★ v3.81: 工具执行确认门控 — 高风险工具弹对话框
        try:
            from core.tool_confirm_gate import ToolConfirmGate
            self._tool_confirm_gate = ToolConfirmGate(self)
            self.serve_bridge._tool_confirm_callback = self._tool_confirm_gate.make_callback()
        except Exception as _e_tcg:
            print(f"[MIMOWindow] ToolConfirmGate 加载失败（高风险工具将自动执行）: {_e_tcg}")

        # ★ 单AI多窗口面板 -> serve_bridge 输出同步
        if hasattr(self, 'single_ai_panel') and hasattr(self.single_ai_panel, 'append_ai_response'):
            self.serve_bridge.output_received.connect(
                lambda text: self.single_ai_panel.append_ai_response(
                    self.single_ai_panel.current_task_id, text
                ), Qt.QueuedConnection
            )
            print("[_connect_signals] 单AI面板信号已连接", flush=True)

        # ★ v4.7.2: 工作区切换信号已在 _bind_mimo_panel 中按实例绑定

        # serve 桥输出 -> 底部交互终端
        # ★ v3.72: 底部终端只显示 AI 输出内容，不显示 status/thinking 调试信息
        self.serve_bridge.output_received.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)
        self.serve_bridge.delta_received.connect(self.bottom_panel.mimo_console.append_text_inline, Qt.QueuedConnection)
        # ★ 移除：thinking/status/tool_output 不再显示在底部终端
        # self.serve_bridge.thinking_received.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)
        # self.serve_bridge.status_received.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)
        # self.serve_bridge.tool_output.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)

        # 底部终端输入 -> serve 桥
        self.bottom_panel.mimo_console.command_sent.connect(lambda msg: self._on_user_send(msg, 'bottom_console'), Qt.QueuedConnection)

        # ★ v4.3.8: 咩咩面板命令回传主窗口（日志 + 通用命令转发）
        self.bottom_panel.miemie_task_submitted.connect(self._on_miemie_task, Qt.QueuedConnection)
        
        # serve 进程日志 -> 底部 MIMO Monitor
        self.serve_bridge.serve_log.connect(self._on_serve_log, Qt.QueuedConnection)
        
        # serve 交互事件
        self.serve_bridge.permission_requested.connect(self._on_permission_request, Qt.QueuedConnection)
        self.serve_bridge.mode_changed.connect(self._on_mode_changed, Qt.QueuedConnection)
        self.serve_bridge.usage_info.connect(lambda *a: self.mimo_panel.show_usage(*a), Qt.QueuedConnection)
        self.serve_bridge.usage_info.connect(self.bottom_panel.mimo_console.set_token_info, Qt.QueuedConnection)
        
        # serve 连接状态
        self.serve_bridge.connected.connect(self._on_serve_connected, Qt.QueuedConnection)
        self.serve_bridge.disconnected.connect(self._on_serve_disconnected, Qt.QueuedConnection)
        self.serve_bridge.connection_error.connect(
            lambda msg: self.bottom_panel.log_output(f"[Serve 错误] {msg}", ERROR),
            Qt.QueuedConnection
        )
        self.serve_bridge.session_created.connect(
            lambda sid: (
                self.bottom_panel.log_output(f"[Serve] 会话: {sid[:16]}...", SUCCESS),
                # ★ v4.1.14: 注入真实活动模型名（替代硬编码占位符 mimo-auto）
                self._sync_console_model(),
                self.bottom_panel.mimo_console.set_session_info(sid, self._get_active_model_id()),
                self.mimo_panel.set_current_session(sid),
                self._on_session_created_for_multi(sid)
            ),
            Qt.QueuedConnection
        )

        # 文件变更通知
        self.serve_bridge.file_changed.connect(self._on_file_changed, Qt.QueuedConnection)
        
        # serve 任务生命周期
        self._task_start_time = None
        self.serve_bridge.task_started.connect(
            lambda text: (self._on_task_started(), self.mimo_panel.set_agent_state('working')),
            Qt.QueuedConnection
        )
        self.serve_bridge.task_finished.connect(
            lambda ok, summary: (self._on_task_finished(ok, summary), self.mimo_panel.set_agent_state('error' if not ok else 'idle')),
            Qt.QueuedConnection
        )
        
        if hasattr(self.serve_bridge, 'thinking_step_received') and hasattr(self.bottom_panel, 'thinking_panel'):
            self.serve_bridge.thinking_step_received.connect(
                self.bottom_panel.thinking_panel.add_step, Qt.QueuedConnection
            )
            self.serve_bridge.thinking_step_received.connect(
                self._on_thinking_step_to_chat, Qt.QueuedConnection
            )
        
        if hasattr(self.serve_bridge, 'tool_card_received'):
            self.serve_bridge.tool_card_received.connect(
                self._on_tool_card, Qt.QueuedConnection
            )
        
        # ★ v4.7.2: 面板交互/模型/会话/模式/信任信号均已在 _bind_mimo_panel 中
        # 按实例绑定（多会话各自持有），此处不再重复连接避免信号双触发。

        # ====== ★ EngineManager 信号 → 底部终端（ollama 回退路径） ======
        # 当 mimocode 离线回退到 ollama 时，EngineManager 的信号需要同步到底部终端
        # 否则底部终端只显示"执行中..."，看不到 AI 回复
        # ★ v3.24: 延迟连接，确保 engine_manager 已注入
        def _connect_engine_manager_signals():
            if hasattr(self, 'mimo_panel') and self.mimo_panel._engine_manager is not None:
                _em = self.mimo_panel._engine_manager
                _em.message_complete.connect(
                    lambda msg: self.bottom_panel.mimo_console.append_html(
                        f"<span style='color:{Lemon.SURFACE};'>{msg.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')[:200]}</span>"
                    ),
                    Qt.QueuedConnection
                )
                _em.error_occurred.connect(
                    lambda err: self.bottom_panel.log_output(f"[Engine] {err}", ERROR),
                    Qt.QueuedConnection
                )
                _em.thinking_received.connect(
                    lambda text: self.bottom_panel.mimo_console.append_html(
                        f"<span style='color:#888;'>? {text[:100]}</span>"
                    ),
                    Qt.QueuedConnection
                )
                # ★ v4.5.1 启动回灌 API Key（持久化配置 → EngineManager）
                self._restore_api_keys(_em)
                print("[_connect_signals] EngineManager 信号已连接到底部终端", flush=True)
            else:
                print("[_connect_signals] EngineManager 未注入，延迟重试...", flush=True)
                QTimer.singleShot(1000, _connect_engine_manager_signals)
        
        _connect_engine_manager_signals()

        # ====== ★ v5.0 Whitebox: RunRegistry → UI 渲染绑定 ======
        if hasattr(self, 'whitebox_panel') and self.whitebox_panel:
            try:
                reg = self.whitebox_panel.registry
                reg.run_added.connect(
                    lambda rid: self.bottom_panel.log_output(
                        f"[白盒] Run 创建: {rid[:8]}", SUCCESS),
                    Qt.QueuedConnection)
                reg.run_completed.connect(
                    lambda rid: self.bottom_panel.log_output(
                        f"[白盒] Run 完成: {rid[:8]}", SUCCESS),
                    Qt.QueuedConnection)
                reg.run_failed.connect(
                    lambda rid: self.bottom_panel.log_output(
                        f"[白盒] Run 失败: {rid[:8]}", ERROR),
                    Qt.QueuedConnection)
                print("[_connect_signals] Whitebox RunRegistry 信号已绑定", flush=True)
            except Exception as _wb_sig_err:
                print(f"[_connect_signals] Whitebox信号绑定失败: {_wb_sig_err}", flush=True)

        # ====== ★ 多会话并行管理器信号 ======
        self.multi_session_mgr.session_added.connect(self._on_multi_session_added, Qt.QueuedConnection)
        self.multi_session_mgr.session_removed.connect(self._on_multi_session_removed, Qt.QueuedConnection)
        self.multi_session_mgr.session_state_changed.connect(self._on_multi_session_state_changed, Qt.QueuedConnection)
        self.multi_session_mgr.session_output.connect(self._on_multi_session_output, Qt.QueuedConnection)
        self.multi_session_mgr.active_session_changed.connect(self._on_multi_active_changed, Qt.QueuedConnection)
        
        # 多会话面板信号
        self.multi_session_panel.new_session_requested.connect(self._on_multi_new_session, Qt.QueuedConnection)
        self.multi_session_panel.session_close_requested.connect(self._on_multi_close_session, Qt.QueuedConnection)
        self.multi_session_panel.session_selected.connect(self._on_multi_session_selected, Qt.QueuedConnection)
        self.multi_session_panel.send_to_session.connect(self._on_multi_send_to_session, Qt.QueuedConnection)
        
        # ★ 多实例编排管理器信号连接（v2.0 新增）
        self.multi_instance_mgr.instance_added.connect(self._on_instance_added, Qt.QueuedConnection)
        self.multi_instance_mgr.instance_state_changed.connect(self._on_instance_state_changed, Qt.QueuedConnection)
        self.multi_instance_mgr.instance_output.connect(self._on_instance_output, Qt.QueuedConnection)
        self.multi_instance_mgr.director_aggregated.connect(self._on_director_aggregated, Qt.QueuedConnection)
        self.multi_instance_mgr.all_instances_idle.connect(self._on_all_instances_idle, Qt.QueuedConnection)
        self.multi_instance_mgr.worker_result.connect(self._on_worker_result, Qt.QueuedConnection)
        self.multi_instance_mgr.task_dispatched.connect(self._on_task_dispatched, Qt.QueuedConnection)
        self.multi_instance_grid.instance_selected.connect(self._on_grid_instance_selected, Qt.QueuedConnection)
        self.multi_instance_grid.instance_maximized.connect(self._on_grid_instance_maximized, Qt.QueuedConnection)
        
        # ====== AI 路由信号 ======
        self.ai_router.route_decision.connect(
            lambda task, provider, reason: self.bottom_panel.log_output(
                f"[AI路由] → {provider} ({reason})", INFO
            ),
            Qt.QueuedConnection
        )
        
        # ====== 插件系统信号 ======
        self.plugin_mgr.plugin_loaded.connect(
            lambda name: self.bottom_panel.log_output(f"[插件] 已加载: {name}", SUCCESS),
            Qt.QueuedConnection
        )
        self.plugin_mgr.skill_loaded.connect(
            lambda name: self.bottom_panel.log_output(f"[Skill] 已注册: {name}", INFO),
            Qt.QueuedConnection
        )
        self.plugin_mgr.plugin_error.connect(
            lambda name, err: self.bottom_panel.log_output(f"[插件错误] {name}: {err}", ERROR),
            Qt.QueuedConnection
        )
        
        # ====== 任务引擎信号 ======
        self.task_engine.task_added.connect(
            lambda tid, name: self.bottom_panel.log_output(f"[任务] 添加子任务: {name}", INFO),
            Qt.QueuedConnection
        )
        self.task_engine.task_completed.connect(
            lambda tid, result: self.bottom_panel.log_output(f"[任务] 完成: {tid}", SUCCESS),
            Qt.QueuedConnection
        )
        self.task_engine.task_failed.connect(
            lambda tid, err: self.bottom_panel.log_output(f"[任务] 失败: {tid} — {err}", ERROR),
            Qt.QueuedConnection
        )
        
        # ====== ACP Bridge 信号（可选增强） ======
        # ACP 输出 -> 当前会话面板 + 底部终端（同步显示）
        self.acp_bridge.output_received.connect(lambda *a: self.mimo_panel.on_output(*a), Qt.QueuedConnection)
        self.acp_bridge.output_received.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)
        self.acp_bridge.thinking_received.connect(lambda *a: self.mimo_panel.on_thinking(*a), Qt.QueuedConnection)
        # ★ v3.72: thinking/status/tool_output 不再显示在底部终端
        # self.acp_bridge.thinking_received.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)
        self.acp_bridge.status_received.connect(lambda *a: self.mimo_panel.on_status(*a), Qt.QueuedConnection)
        # self.acp_bridge.status_received.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)
        self.acp_bridge.tool_output.connect(lambda *a: self.mimo_panel.on_tool_output(*a), Qt.QueuedConnection)
        # self.acp_bridge.tool_output.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)
        self.acp_bridge.error_occurred.connect(self._on_bridge_error, Qt.QueuedConnection)
        self.acp_bridge.config_options_received.connect(self._on_config_options, Qt.QueuedConnection)
        self.acp_bridge.permission_requested.connect(self._on_permission_request, Qt.QueuedConnection)
        self.acp_bridge.mode_changed.connect(self._on_mode_changed, Qt.QueuedConnection)
        self.acp_bridge.plan_updated.connect(lambda *a: self.mimo_panel.show_plan(*a), Qt.QueuedConnection)
        self.acp_bridge.available_commands.connect(lambda *a: self.mimo_panel.show_commands(*a), Qt.QueuedConnection)
        self.acp_bridge.usage_info.connect(lambda *a: self.mimo_panel.show_usage(*a), Qt.QueuedConnection)
        self.acp_bridge.connected.connect(self._on_acp_connected, Qt.QueuedConnection)
        self.acp_bridge.disconnected.connect(self._on_acp_disconnected, Qt.QueuedConnection)
        self.acp_bridge.connection_error.connect(
            lambda msg: self.bottom_panel.log_output(f"[ACP 错误] {msg}", ERROR),
            Qt.QueuedConnection
        )
        self.acp_bridge.task_started.connect(lambda *a: self.mimo_panel.on_task_started(*a), Qt.QueuedConnection)
        self.acp_bridge.task_finished.connect(
            lambda ok, summary: self.mimo_panel.on_task_finished(0 if ok else -1),
            Qt.QueuedConnection
        )
        self.acp_bridge.acp_event.connect(self._on_acp_event, Qt.QueuedConnection)
        # ★ v4.7.2: config_applied 已在 _bind_mimo_panel 中按实例绑定
        
        # ====== 旧版 MIMO Process Bridge 信号（fallback） ======
        # ★ v3.73: Process 输出只到右侧面板，不显示 raw_output/status 在右侧
        self.proc_bridge.output_received.connect(lambda *a: self.mimo_panel.on_output(*a), Qt.QueuedConnection)
        self.proc_bridge.output_received.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)
        self.proc_bridge.thinking_received.connect(lambda *a: self.mimo_panel.on_thinking(*a), Qt.QueuedConnection)
        # ★ v3.72: thinking/status 不再显示在底部终端
        # self.proc_bridge.thinking_received.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)
        # ★ v3.73: status 不再显示在右侧面板（避免绿色状态文字干扰 AI 输出）
        # self.proc_bridge.status_received.connect(self.mimo_panel.on_status, Qt.QueuedConnection)
        # self.proc_bridge.status_received.connect(self.bottom_panel.mimo_console.append_html, Qt.QueuedConnection)
        self.proc_bridge.error_occurred.connect(self._on_bridge_error, Qt.QueuedConnection)
        # ★ v3.73: raw_output 只显示在底部终端的 MIMO Monitor，不显示在右侧面板
        self.proc_bridge.raw_output.connect(self._on_mimo_raw_output, Qt.QueuedConnection)
        # ★ v3.73: tool_output 连接到右侧面板的可折叠区域
        self.proc_bridge.tool_output.connect(lambda *a: self.mimo_panel.on_tool_output(*a), Qt.QueuedConnection)
        # ★ v3.90: file_preview 连接到右侧面板内嵌预览
        self.proc_bridge.file_preview.connect(lambda *a: self.mimo_panel.on_file_preview(*a), Qt.QueuedConnection)
        # ★ v3.90 修复: 移除 proc_bridge.task_started 直接连接，避免与 serve_bridge.task_started
        # 双重触发导致 "◷任务开始..." 显示两次。serve_bridge 已统一处理 task_started 信号。
        # self.proc_bridge.task_started.connect(
        #     lambda cmd: self.mimo_panel.on_task_started(), Qt.QueuedConnection
        # )
        self.proc_bridge.task_finished.connect(lambda *a: self.mimo_panel.on_task_finished(*a), Qt.QueuedConnection)

        # ====== Ollama 本地模型信号 ======
        self.ollama_bridge.reply_received.connect(
            lambda text: self.bottom_panel.mimo_console.append_html(text),
            Qt.QueuedConnection
        )
        self.ollama_bridge.error_occurred.connect(
            lambda msg: self.bottom_panel.log_output(f"[柠檬助手] {msg}", WARNING),
            Qt.QueuedConnection
        )

    # ★ v3.51: 引擎模式切换处理
    def _auto_switch_engine_mode(self, mode: str):
        """启动时根据环境变量自动切换引擎模式"""
        try:
            if hasattr(self, 'title_bar') and hasattr(self.title_bar, 'engine_selector'):
                buttons = self.title_bar.engine_selector.buttons
                if mode in buttons:
                    buttons[mode].click()
                    print(f"[Engine] 已自动切换至 {mode} 模式", flush=True)
                    return
            # 如果无法点击按钮，直接调用切换逻辑
            self._on_engine_mode_changed(mode)
        except Exception as e:
            print(f"[Engine] 自动切换模式失败: {e}", flush=True)

    def _on_engine_mode_changed(self, mode: str):
        """引擎模式选择器变化处理

        ★ v4.1.9: 模式收敛为两段 (native/host)，加 mode_switches 闸门
        ★ v4.1.7: 加 Solo 段与 mode_switches 闸门
        ★ v4.0: 支持新模式名 "lemoncode" / "code" / "agent"
        ★ v3.63: 兼容新旧两套模式名
        - 新模式名（v4.1.9 UI）: "native" / "host"
        - v4.1.7 兼容模式名: "lemoncode" / "agent" / "solo"
        - v4.0 兼容模式名: "code"
        - 旧模式名（v3.62 UI）: "api" / "local" / "llama" / "auto"
        - 旧模式名（EngineMode 枚举）: "mimo" / "ollama" / "deepseek" / "auto"

        Args:
            mode: "native"/"host"/"lemoncode"/"code"/"agent"/"solo"/"api"/"local"/"llama"/"auto"
        """
        from shared.engine_mode_manager import EngineMode

        # ★ v4.1.9: 闸门 — 设置面板开关校验（防御性二次检查，避免 title_bar 被绕过）
        try:
            from core.settings_manager import get_settings_manager
            sm = get_settings_manager()
            switches = sm.get("appearance.mode_switches", {}) or {}
            if mode == "native" and not switches.get("native_agent_enabled", True):
                # native 禁用：保持当前模式不变
                pass
            elif mode == "host" and not switches.get("host_agent_enabled", True):
                # Host Agent 禁用 → 弹提示并保持当前模式
                try:
                    if hasattr(self, 'bottom_panel') and self.bottom_panel:
                        self.bottom_panel.log_output(
                            "[模式] Host Agent 已在设置中关闭，请先开启再切换 HOST 模式",
                            Lemon.ACCENT_RED
                        )
                except Exception:
                    pass
                return
        except Exception as e:
            print(f"[Engine] mode_switches 闸门检查失败: {e}")

        # ★ v4.1.9: 兼容映射 — 旧模式名收敛到新模式名
        # - "lemoncode" → "native"
        # - "agent" / "solo" / "code" → "host"（按业务意图收敛）
        compat_map = {"lemoncode": "native", "agent": "host", "solo": "host", "code": "native"}
        if mode in compat_map:
            mode = compat_map[mode]

        # ★ v4.0: 新模式名映射
        mode_map = {
            # v4.1.9 新模式名
            "native": EngineMode.AUTO,        # Native Agent — LemonCode 本体 Agent
            "host": EngineMode.AUTO,          # Host Agent — 夺舍外部 Agent
            # v3.62 模式名（向后兼容）
            "api": EngineMode.DEEPSEEK,        # API = 云端 DeepSeek
            "local": EngineMode.OLLAMA,        # 本地 = Ollama 通用模型
            "llama": EngineMode.OLLAMA,        # LLaMA = Ollama 运行 LLaMA 系列模型
            "auto": EngineMode.AUTO,
            # 旧模式名（向后兼容）
            "mimo": EngineMode.MIMO,
            "ollama": EngineMode.OLLAMA,
            "deepseek": EngineMode.DEEPSEEK,
        }
        engine_mode = mode_map.get(mode)
        if engine_mode is None:
            print(f"[Engine] 未知模式: {mode}")
            return

        print(f"[Engine] 模式切换: {mode} → {engine_mode.value}")

        # 设置到 mimo_panel 的模式管理器
        self.mimo_panel._mode_manager.set_mode(engine_mode)

        # ★ v4.0: LemonCode 模式下自动加载模型列表
        if mode == "lemoncode":
            try:
                self._load_models_to_selector()
            except Exception as e:
                print(f"[Engine] 加载模型列表失败: {e}")

        # ★ v3.63: LLaMA 模式下自动切换到 LLaMA 模型
        if mode == "llama":
            try:
                if self.mimo_panel._engine_manager:
                    # 设置默认 LLaMA 模型
                    self.mimo_panel._engine_manager.set_model("ollama", "llama3:8b")
                    print(f"[Engine] LLaMA 模式：已设置默认模型 llama3:8b")
            except Exception as e:
                print(f"[Engine] LLaMA 模型设置失败: {e}")

        # 更新选择器状态灯
        try:
            if self.mimo_panel._engine_manager:
                status = self.mimo_panel._engine_manager.get_status()
                # ★ v3.71 修复：迭代 engines 子字典，而不是 status 顶层
                engines = status.get("engines", {})
                for eng_name, eng_info in engines.items():
                    if isinstance(eng_info, dict):
                        self.title_bar.engine_selector.update_engine_status(
                            eng_name, eng_info.get("available", False)
                        )
        except Exception as e:
            print(f"[Engine] 更新状态灯失败: {e}")

        # ★ v4.1.11: Host Agent 功能栏显隐（host 模式显示 / 其他隐藏）
        try:
            self.title_bar.set_host_toolbar_visible(mode == "host")
        except Exception:
            pass

        # ★ v4.1.13: 按 NATIVE/HOST 精简底部面板标签页
        try:
            if hasattr(self, 'bottom_panel') and self.bottom_panel:
                self.bottom_panel.set_mode(mode)
        except Exception:
            pass

        # 更新 serve_bridge 的行为模式
        # ★ v4.1.9: 两段模式 — native（自研）/ host（夺舍），无 Solo 分支
        # ★ v4.0: 更新 serve_bridge 的行为模式
        if mode == "host":
            # HOST 模式：夺舍路径 — 启用 ACP Bridge 与外部 Agent
            self.serve_bridge._auto_fallback_disabled = False
        elif mode in ("mimo", "code"):
            # MIMO/Code 模式：禁用 Ollama 自动回退
            self.serve_bridge._auto_fallback_disabled = True
        elif mode in ("ollama", "local"):
            # Ollama 模式：强制使用 Ollama
            self.serve_bridge._auto_fallback_disabled = True
        elif mode in ("deepseek", "api"):
            # DeepSeek 模式：强制使用 DeepSeek API
            self.serve_bridge._auto_fallback_disabled = True
        else:
            # 自动模式 / Native Agent 模式：允许回退
            self.serve_bridge._auto_fallback_disabled = False

        # ★ v4.1.9: NATIVE 模式下启用输入框；HOST 模式下保持可用（借由 ACP 输入）
        try:
            if hasattr(self, 'input_field') and self.input_field:
                self.input_field.setEnabled(True)
                if getattr(self, '_default_input_placeholder', None):
                    self.input_field.setPlaceholderText(self._default_input_placeholder)
        except Exception:
            pass

        # ★ v3.65: Agent 模式（夺舍）特殊处理 — ★ v4.1.9 改为 host
        if mode == "host":
            # 夺舍模式：启动 ACP Bridge 连接外部 Agent
            self._activate_hijack_mode()
        else:
            # 非夺舍模式：若之前处于夺舍模式，则恢复
            if getattr(self, '_hijack_mode_active', False):
                self._deactivate_hijack_mode()

        print(f"[Engine] 模式已切换: {mode}, serve_bridge自动回退={'禁用' if mode != 'auto' else '启用'}")

        # ★ P6-4: 切换引擎后更新底部栏
        self._update_status_bar()

    # ============================================================
    # ★ v4.1.11: Host Agent 顶部功能栏动作
    # ============================================================
    def _on_host_toolbar_action(self, action: str):
        """处理 Host Agent 功能栏按钮：scan / select / connect / disconnect

        Args:
            action: "scan"（扫描本机 Agent）/ "select"（选择）/ "connect"（连接）/ "disconnect"（断开）
        """
        try:
            if action == "scan":
                self._scan_agents_and_report()
            elif action == "select":
                self._select_host_agent()
            elif action == "connect":
                self._connect_host_agent()
            elif action == "disconnect":
                if getattr(self, '_hijack_mode_active', False):
                    self._deactivate_hijack_mode()
                    self.title_bar.set_host_connected(False)
                else:
                    self.bottom_panel.log_output(f"[Host] 当前未连接，无需断开", Lemon.ACCENT_PURPLE)
        except Exception as e:
            print(f"[Host] 功能栏动作失败 ({action}): {e}")
            import traceback
            traceback.print_exc()

    def _scan_agents_and_report(self):
        """扫描本机 Agent 并报告结果"""
        from core.agent_registry import AgentRegistry
        self.bottom_panel.log_output(f"[Host] 正在扫描本机 Agent...", Lemon.ACCENT_PURPLE)
        try:
            registry = AgentRegistry()
            installed = registry.scan()
            if installed:
                names = "、".join(a.brand_name for a in installed)
                self.bottom_panel.log_output(
                    f"[Host] ✅ 检测到 {len(installed)} 个已装 Agent: {names}", SUCCESS
                )
                # 自动选中第一个
                first = installed[0]
                self.title_bar.set_host_agent_name(first.brand_name)
                self._host_selected_agent_id = first.id
            else:
                self.bottom_panel.log_output(
                    "[Host] ⚠ 未检测到已装 Agent（可点击“选择”查看安装提示）", WARNING
                )
        except Exception as e:
            self.bottom_panel.log_output(f"[Host] 扫描失败: {e}", ERROR)

    def _select_host_agent(self):
        """弹出 Agent 选择对话框（复用 _show_agent_selection_dialog）"""
        agent_id = self._show_agent_selection_dialog()
        if not agent_id:
            return
        self._host_selected_agent_id = agent_id
        try:
            from core.agent_registry import AgentRegistry
            desc = AgentRegistry().find(agent_id)
            if desc:
                self.title_bar.set_host_agent_name(desc.brand_name)
                self.bottom_panel.log_output(
                    f"[Host] 已选择 Agent: {desc.brand_name}（点击 ▶ 连接）", Lemon.ACCENT_PURPLE
                )
        except Exception as e:
            print(f"[Host] 选择失败: {e}")

    def _connect_host_agent(self):
        """连接所选 Agent（走夺舍流程）"""
        agent_id = getattr(self, '_host_selected_agent_id', None)
        # ★ v4.1.12: 未手动选择时用 HOST 配置的默认 Agent
        if not agent_id:
            try:
                from core.settings_manager import get_settings_manager as _gsm
                agent_id = _gsm().host_default_agent
            except Exception:
                agent_id = "mimo_code"
            self.bottom_panel.log_output(
                f"[Host] 未手动选择，使用默认 Agent: {agent_id}", Lemon.ACCENT_PURPLE
            )
        # 强制进入 HOST 模式并激活夺舍
        try:
            self.title_bar.engine_selector._current = "host"
            self.title_bar.engine_selector.buttons["host"].setChecked(True)
            self.title_bar.engine_selector._update_style()
            self.title_bar.set_host_toolbar_visible(True)
            self.title_bar.set_host_connected(False)
        except Exception:
            pass
        # 复用夺舍激活（_activate_hijack_mode 会弹对话框，这里直接启动连接）
        self._host_selected_agent_id = agent_id
        self._launch_host_connect(agent_id)

    def _launch_host_connect(self, agent_id: str):
        """启动夺舍连接（跳过选择对话框，直接用指定 agent_id）"""
        try:
            self._hijack_agent_name = agent_id
            self._hijack_mode_active = False
            from core.agent_registry import AgentRegistry
            _desc = AgentRegistry().find(agent_id)
            display_name = _desc.brand_name if _desc else agent_id
            self._hijack_agent_brand = display_name
            self.title_bar.set_host_agent_name(display_name)

            # ★ v4.1.12: 读取 HOST 分模式配置（ACP 端口 / 超时）
            from core.settings_manager import get_settings_manager as _gsm
            _sm = _gsm()
            _timeout = _sm.host_connect_timeout
            _port = _sm.host_acp_port

            if not hasattr(self, 'acp_bridge') or self.acp_bridge is None:
                from core.acp_bridge import ACPBridge
                kwargs = {}
                if _port:
                    kwargs["port"] = _port
                self.acp_bridge = ACPBridge(os.getcwd(), **kwargs)
                self._connect_acp_bridge_signals()

            self.bottom_panel.log_output(
                f"[Host] 正在连接 {display_name}...", Lemon.ACCENT_PURPLE
            )
            ok = self.acp_bridge.start()
            if not ok:
                self.bottom_panel.log_output(
                    f"[Host] 连接失败：ACP Bridge 启动失败", ERROR
                )
                self._hijack_mode_active = False
                self.title_bar.set_host_connected(False)
                return

            from PyQt5.QtCore import QTimer as _QTimer
            self._hijack_connect_timeout = _QTimer()
            self._hijack_connect_timeout.setSingleShot(True)
            self._hijack_connect_timeout.timeout.connect(self._on_hijack_connect_timeout)
            self._hijack_connect_timeout.start(_timeout * 1000)
            self.bottom_panel.log_output(
                f"[Host] 等待连接 {display_name}（{_timeout}秒超时）...", Lemon.ACCENT_PURPLE
            )
        except Exception as e:
            print(f"[Host] 连接失败: {e}")
            import traceback
            traceback.print_exc()

    def _on_language_changed(self, lang_code: str):
        """语言切换处理 — 刷新 UI 文本 + 持久化"""
        from standard_mode.core.i18n import get_i18n, _t, _LANGUAGE_NAMES
        i18n = get_i18n()
        lang_name = _LANGUAGE_NAMES.get(lang_code, lang_code)
        try:
            if hasattr(self, 'bottom_panel') and self.bottom_panel:
                self.bottom_panel.log_output(
                    _t('notification.language_changed', language=lang_name), Lemon.ACCENT_GREEN
                )
        except Exception:
            pass
        try:
            if hasattr(self, 'title_bar') and hasattr(self.title_bar, '_btn_min'):
                self.title_bar._btn_min.setToolTip(_t('window.minimize'))
                self.title_bar._btn_max.setToolTip(_t('window.maximize'))
                self.title_bar._btn_close.setToolTip(_t('window.close'))
        except Exception:
            pass
        try:
            import json, os
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'settings.json')
            config_path = os.path.normpath(config_path)
            config = {}
            if os.path.isfile(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            if 'general' not in config or not isinstance(config.get('general'), dict):
                config['general'] = {}
            config['general']['language'] = lang_code
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[i18n] 语言偏好持久化失败: {e}")

    def _on_model_changed(self, model_id: str):
        """模型选择变化处理（v4.0 新增）

        Args:
            model_id: 选中的模型ID，如 "qwen3.5:4b" / "deepseek-chat"
        """
        print(f"[Engine] 模型切换: {model_id}")
        try:
            if self.mimo_panel._engine_manager:
                # 自动判断模型类型并设置
                if model_id in ("auto", "mimo-auto"):
                    self.mimo_panel._engine_manager.set_mode("auto")
                elif ":" in model_id:
                    # 包含 ":" 的通常是 Ollama 本地模型
                    self.mimo_panel._engine_manager.set_model("ollama", model_id)
                else:
                    # 其他视为 API 模型
                    self.mimo_panel._engine_manager.set_model("deepseek", model_id)
        except Exception as e:
            print(f"[Engine] 模型切换失败: {e}")

        # 更新底部栏显示
        self._update_status_bar()
        # ★ v4.1.14: 用户主动切模型后，把新模型同步到 BottomPanel 工具栏按钮
        try:
            if hasattr(self, 'bottom_panel') and self.bottom_panel and hasattr(self.bottom_panel, 'mimo_console'):
                self.bottom_panel.mimo_console.model_combo.setText(model_id)
        except Exception:
            pass

    # ★ v4.1.14: 拿当前真实活动引擎+模型（替代硬编码 mimo-auto 占位符）
    def _get_active_model_id(self) -> str:
        """从 mimo_panel 的 engine_manager 拿当前真实活动模型名。
        拿不到时返回 None，由 set_session_info 维持按钮默认 '—' 显示。"""
        try:
            em = getattr(self.mimo_panel, '_engine_manager', None) if hasattr(self, 'mimo_panel') else None
            if em is None:
                return None
            info = em.get_current_model()
            return info.get('model') or None
        except Exception:
            return None

    def _sync_console_model(self):
        """启动时/模式切换时把真实模型同步到底部栏"""
        mid = self._get_active_model_id()
        if mid and hasattr(self, 'bottom_panel') and self.bottom_panel and hasattr(self.bottom_panel, 'mimo_console'):
            try:
                self.bottom_panel.mimo_console.model_combo.setText(mid)
            except Exception:
                pass

    def _load_models_to_selector(self):
        """加载模型列表到选择器（v4.0 新增）"""
        try:
            local_models = []
            ollama_models = []
            api_models = ["deepseek-chat", "deepseek-coder"]

            # 尝试从 Ollama 获取模型列表
            if self.mimo_panel._engine_manager:
                try:
                    import requests
                    resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
                    if resp.status_code == 200:
                        data = resp.json()
                        for m in data.get("models", []):
                            name = m.get("name", "")
                            ollama_models.append(name)
                except Exception:
                    pass

            # 本地文件夹模型（从配置目录扫描）
            config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "models")
            if os.path.isdir(config_dir):
                for f in os.listdir(config_dir):
                    if f.endswith((".gguf", ".bin", ".safetensors")):
                        local_models.append(f)

            self.title_bar.engine_selector.set_models(local_models, ollama_models, api_models)
        except Exception as e:
            print(f"[Engine] 加载模型列表失败: {e}")

    # ================================================================
    # ★ v3.65: 夺舍模式（Agent 模式）激活/停用
    # ================================================================
    def _activate_hijack_mode(self):
        """★ v3.65: 激活夺舍模式

        流程：
        1. 显示 Agent 选择对话框（选择外部 Agent，默认 MIMO Code）
        2. 启动 ACP Bridge 连接外部 Agent
        3. 等待连接成功信号（connected）
        4. 连接成功后切换 UI：
           - 底栏 → 假终端模式（拦截显示）
           - 右栏 → 显示模式（二次处理）
        5. 连接 ACP 信号到二次处理服务
        """
        try:
            # 步骤1：显示 Agent 选择对话框
            agent_name = self._show_agent_selection_dialog()
            if not agent_name:
                # 用户取消，回退到 LemonCode 模式
                self.title_bar.engine_selector.buttons["native"].setChecked(True)
                self.title_bar.engine_selector._current = "native"
                self.title_bar.engine_selector._update_style()
                return

            self._hijack_agent_name = agent_name
            self._hijack_mode_active = False  # 等待连接成功后才算激活

            # ★ v4.1.11: agent_name 是 agent_id，查 descriptor 拿品牌显示名
            display_name = agent_name
            try:
                from core.agent_registry import AgentRegistry
                _reg = AgentRegistry()
                _desc = _reg.find(agent_name)
                if _desc:
                    display_name = _desc.brand_name
            except Exception:
                pass
            self._hijack_agent_brand = display_name

            # 步骤2：启动 ACP Bridge
            self.bottom_panel.log_output(
                f"[夺舍] 正在连接外部 Agent: {display_name}...", Lemon.ACCENT_PURPLE
            )

            # 先确保 acp_bridge 存在
            if not hasattr(self, 'acp_bridge') or self.acp_bridge is None:
                from core.acp_bridge import ACPBridge, ACPEvent
                self.acp_bridge = ACPBridge(os.getcwd())
                self._connect_acp_bridge_signals()

            # 启动连接
            ok = self.acp_bridge.start()
            if not ok:
                self.bottom_panel.log_output(
                    f"[夺舍] 连接失败：ACP Bridge 启动失败（MIMO EXE 可能不存在）",
                    ERROR
                )
                # 回退到 LemonCode 模式
                self.title_bar.engine_selector.buttons["native"].setChecked(True)
                self.title_bar.engine_selector._current = "native"
                self.title_bar.engine_selector._update_style()
                return

            # 步骤3：等待连接（连接成功后由 _on_acp_connected 处理 UI 切换）
            # ★ v4.1.12: 连接超时读取 HOST 配置
            _timeout = 30
            try:
                from core.settings_manager import get_settings_manager as _gsm
                _timeout = _gsm().host_connect_timeout
            except Exception:
                pass
            from PyQt5.QtCore import QTimer as _QTimer
            self._hijack_connect_timeout = _QTimer()
            self._hijack_connect_timeout.setSingleShot(True)
            self._hijack_connect_timeout.timeout.connect(self._on_hijack_connect_timeout)
            self._hijack_connect_timeout.start(_timeout * 1000)

            self.bottom_panel.log_output(
                f"[夺舍] 等待连接 {agent_name}（{_timeout}秒超时）...",
                Lemon.ACCENT_PURPLE
            )
        except Exception as e:
            print(f"[夺舍] 激活失败: {e}")
            import traceback
            traceback.print_exc()

    def _deactivate_hijack_mode(self):
        """★ v3.65: 停用夺舍模式，恢复正常 UI"""
        try:
            # 停止 ACP Bridge
            if hasattr(self, 'acp_bridge') and self.acp_bridge is not None:
                try:
                    self.acp_bridge.stop()
                except Exception:
                    pass

            # 恢复底栏真终端模式
            self.bottom_panel.set_fake_terminal_mode(False)

            # 恢复右栏正常输出模式
            self.mimo_panel.set_display_only_mode(False)

            # 取消超时定时器
            if hasattr(self, '_hijack_connect_timeout'):
                try:
                    self._hijack_connect_timeout.stop()
                except Exception:
                    pass

            # 更新状态灯
            self.title_bar.engine_selector.update_engine_status("acp", False)

            # ★ v4.1.11: 更新 Host 功能栏
            try:
                self.title_bar.set_host_connected(False)
            except Exception:
                pass

            self._hijack_mode_active = False
            self.bottom_panel.log_output(
                "[夺舍] 已恢复正常 Agent 模式",
                XIAOMI_ORANGE
            )
        except Exception as e:
            print(f"[夺舍] 停用失败: {e}")

    def _on_hijack_connect_timeout(self):
        """★ v3.65: 夺舍模式连接超时"""
        if not getattr(self, '_hijack_mode_active', False):
            self.bottom_panel.log_output(
                f"[夺舍] 连接 {getattr(self, '_hijack_agent_brand', getattr(self, '_hijack_agent_name', '外部 Agent'))} 超时（30秒）",
                ERROR
            )
            # 回退到 LemonCode 模式
            try:
                self.title_bar.engine_selector.buttons["native"].setChecked(True)
                self.title_bar.engine_selector._current = "native"
                self.title_bar.engine_selector._update_style()
            except Exception:
                pass

    def _show_agent_selection_dialog(self) -> str:
        """★ v3.65 / ★ v4.1.11: 显示 Agent 选择对话框（动态扫描本机 Agent）

        用 AgentRegistry 扫描本机已装 Agent（第197章基础设施），
        未安装的 Agent 也列出但禁用（带安装提示），避免硬编码下拉。

        Returns:
            选择的 Agent id（如 "mimo_code"），用户取消则返回空字符串
        """
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton,
            QHBoxLayout, QMessageBox,
        )
        from core.agent_registry import AgentRegistry
        from core.agent_adapter import create_adapter

        # ---- 扫描本机 Agent ----
        try:
            registry = AgentRegistry()
            installed = registry.scan()   # 已装列表
            installed_ids = {a.id for a in installed}
        except Exception:
            installed, installed_ids = [], set()
            print(f"[夺舍] AgentRegistry 扫描失败: {e}")

        dialog = QDialog(self)
        dialog.setWindowTitle("选择外部 Agent（夺舍模式）")
        dialog.setFixedWidth(460)
        dialog.setStyleSheet(f"background: {Lemon.DARK_MID_5}; color: {Lemon.DIVIDER};")

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题
        title = QLabel("⚠ 夺舍模式：选择外部 Agent 作为算力支持")
        title.setStyleSheet(f"color: {Lemon.ACCENT_PURPLE}; font-size: 14px; font-weight: 600;")
        title.setWordWrap(True)
        layout.addWidget(title)

        # 说明（含扫描结果统计）
        desc = QLabel(
            f"本机检测到 {len(installed)} 个已装 Agent。\n"
            "夺舍模式下，Lemon Code 将连接外部 Agent，\n"
            "底栏切换为假终端（拦截显示），右栏切换为显示模式（二次处理）。"
        )
        desc.setStyleSheet(f"color: {Lemon.SECONDARY}; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Agent 选择下拉框（动态填充）
        agent_combo = QComboBox()
        if installed:
            for agent in installed:
                tag = "" if agent.installed else ""
                agent_combo.addItem(f"{agent.brand_name}（已装）{tag}", agent.id)
        else:
            agent_combo.addItem("未检测到已装 Agent（点击连接将使用 ACP 通用模式）", "generic_acp")
        agent_combo.setStyleSheet(f"""
            QComboBox {
                background: {Lemon.DARK_MID_5};
                color: {Lemon.DIVIDER};
                border: 1px solid {Lemon.ACCENT_PURPLE};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }
        """)
        layout.addWidget(agent_combo)

        # 未安装 Agent 提示区（补充说明可安装项）
        uninstalled = [a for a in registry.get_all() if a.id not in installed_ids] if registry else []
        if uninstalled:
            hint_lines = []
            for a in uninstalled[:4]:
                if a.install_hint:
                    hint_lines.append(f"• {a.brand_name}: {a.install_hint}")
            if hint_lines:
                hint = QLabel("未检测到的 Agent（可自行安装）：\n" + "\n".join(hint_lines))
                hint.setStyleSheet("color: #666; font-size: 11px;")
                hint.setWordWrap(True)
                layout.addWidget(hint)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: {Lemon.DARK_MID_5};
                color: {Lemon.SECONDARY};
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px 16px;
            }
            QPushButton:hover { background: {Lemon.DARK_MID_5}; }
        """)
        cancel_btn.clicked.connect(dialog.reject)

        ok_btn = QPushButton("连接")
        ok_btn.setStyleSheet("""
            QPushButton {
                background: {Lemon.ACCENT_PURPLE};
                color: #fff;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: 600;
            }
            QPushButton:hover { background: {Lemon.ACCENT_PURPLE}; }
        """)
        ok_btn.clicked.connect(dialog.accept)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        if dialog.exec_() == dialog.Accepted:
            agent_id = agent_combo.currentData()
            if not agent_id:
                return ""
            return agent_id
        return ""

    def _connect_acp_bridge_signals(self):
        """★ v3.65: 连接 ACP Bridge 信号（用于夺舍模式）"""
        try:
            self.acp_bridge.connected.connect(self._on_acp_connected, Qt.QueuedConnection)
            self.acp_bridge.disconnected.connect(self._on_acp_disconnected, Qt.QueuedConnection)
            self.acp_bridge.output_received.connect(self._on_hijack_output, Qt.QueuedConnection)
            self.acp_bridge.thinking_received.connect(self._on_hijack_thinking, Qt.QueuedConnection)
            self.acp_bridge.tool_output.connect(self._on_hijack_tool_output, Qt.QueuedConnection)
            self.acp_bridge.status_received.connect(self._on_hijack_status, Qt.QueuedConnection)
            self.acp_bridge.error_occurred.connect(self._on_bridge_error, Qt.QueuedConnection)
        except Exception as e:
            print(f"[夺舍] 连接 ACP 信号失败: {e}")

    def _connect_bridge_event_signals(self):
        """★ v3.0: 连接 Bridge 事件适配器信号（bridge/agent_loop → UI）"""
        if self._bridge_event_adapter is None:
            return
        ea = self._bridge_event_adapter
        try:
            ea.stream_delta.connect(
                lambda sid, content: self.mimo_panel.on_output(content),
                Qt.QueuedConnection
            )
            ea.stream_end.connect(
                lambda sid: self.bottom_panel.log_output("[Bridge] 流式输出完成", INFO),
                Qt.QueuedConnection
            )
            ea.tool_call.connect(
                lambda sid, data: self.bottom_panel.log_output(
                    "[Bridge工具] " + data.get("name", "?"), INFO
                ),
                Qt.QueuedConnection
            )
            ea.tool_result.connect(
                lambda sid, content, ok: self.bottom_panel.log_output(
                    "[Bridge结果] " + ("OK" if ok else "FAIL"), SUCCESS if ok else ERROR
                ),
                Qt.QueuedConnection
            )
            ea.done.connect(
                self._on_agent_done,
                Qt.QueuedConnection
            )
            ea.error.connect(
                lambda sid, code, msg: self._on_bridge_error(msg),
                Qt.QueuedConnection
            )
            ea.progress_start.connect(
                lambda sid, step, total, desc: self.bottom_panel.log_output(
                    "[Bridge进度] " + desc, INFO
                ),
                Qt.QueuedConnection
            )
            ea.progress_done.connect(
                lambda sid, step, total, desc: (
                    self.bottom_panel.log_output("[Bridge完成] " + desc, SUCCESS),
                    self.thinking_panel.update_step_status(desc, "success") if hasattr(self, 'thinking_panel') and self.thinking_panel and hasattr(self.thinking_panel, 'update_step_status') else None
                ),
                Qt.QueuedConnection
            )
            ea.permission_request.connect(
                lambda sid, skill, args: self.bottom_panel.log_output(
                    "[Bridge权限] " + skill + " 请求权限", WARNING
                ),
                Qt.QueuedConnection
            )
            # ★ V6.0 3.2: 思考面板 — step_started + step_completed + tool子步骤
            if hasattr(self, 'thinking_panel') and self.thinking_panel and hasattr(self.thinking_panel, 'add_step'):
                ea.thinking_step.connect(
                    lambda sid, stype, desc: self.thinking_panel.add_step(stype, desc, {}, 0.0),
                    Qt.QueuedConnection
                )
                ea.progress_tool.connect(
                    lambda sid, skill, step, total, desc: self.thinking_panel.add_step("tool_call", skill + ": " + desc, {}, 0.0),
                    Qt.QueuedConnection
                )
                ea.progress_summary.connect(
                    lambda sid, step, total, desc: self.thinking_panel.update_step_status(desc, "success"),
                    Qt.QueuedConnection
                )
                # ★ 403T-4 Fix3: 补接 stream_delta / done / error 到思考面板
                ea.stream_delta.connect(
                    lambda sid, chunk: self._forward_to_thinking_panel(sid, chunk),
                    Qt.QueuedConnection
                )
                ea.done.connect(
                    lambda sid, content: self._forward_to_thinking_panel(sid, content),
                    Qt.QueuedConnection
                )
                ea.error.connect(
                    lambda sid, code, msg: self._forward_to_thinking_panel(sid, (code, msg)),
                    Qt.QueuedConnection
                )

            # ★ force_summary 信号 — Agent 分析报告内容（核心修复：确保报告被显示）
            self._force_summary_shown = {}
            ea.force_summary.connect(
                self._on_force_summary,
                Qt.QueuedConnection
            )

            # ★ v3.0 C-2: 权限请求 → UI弹窗
            ea.permission_request.connect(
                lambda sid, skill, args: self._on_bridge_permission_request(sid, skill, args),
                Qt.QueuedConnection
            )

            # ★ v3.0 C-3: GOAP计划 → 确认/拒绝
            ea.plan_proposed.connect(
                lambda sid, plan: self._on_bridge_plan_proposed(sid, plan),
                Qt.QueuedConnection
            )

            # ★ v3.0 D-1: EventAdapter → TrajectoryPanel 事件转发
            if hasattr(self, 'trajectory_panel') and self.trajectory_panel:
                ea.tool_call.connect(
                    lambda sid, data: self.trajectory_panel.set_events(
                        self._collect_trajectory_events("tool_called", data)
                    ),
                    Qt.QueuedConnection
                )
                ea.done.connect(
                    lambda sid, content: self.trajectory_panel.set_events(
                        self._collect_trajectory_events("final_response", {"content_length": len(content)})
                    ),
                    Qt.QueuedConnection
                )
                ea.error.connect(
                    lambda sid, code, msg: self.trajectory_panel.set_events(
                        self._collect_trajectory_events("error_occurred", {"error": msg, "error_type": code})
                    ),
                    Qt.QueuedConnection
                )

            # ★ v5.0 Whitebox: EventAdapter → StateProjector 核心路由
            if hasattr(self, 'whitebox_panel') and self.whitebox_panel:
                try:
                    self.whitebox_panel.projector.connect_event_adapter(ea)
                    print("[MIMOWindow] Whitebox StateProjector 已绑定 EventAdapter", flush=True)
                except Exception as _wb_ea_err:
                    print(f"[MIMOWindow] Whitebox EventAdapter绑定失败: {_wb_ea_err}", flush=True)

            # ★ S2: EventAdapter → EngineRegistry 全局注入
            try:
                from core.agent_engine import EngineRegistry
                EngineRegistry.set_global_event_adapter(ea)
                print("[MIMOWindow] EventAdapter 已注入 EngineRegistry", flush=True)
            except Exception as _s2_err:
                print(f"[MIMOWindow] EngineRegistry注入失败: {_s2_err}", flush=True)

            print("[MIMOWindow] Bridge事件适配器信号已连接", flush=True)
        except Exception as e:
            print("[MIMOWindow] Bridge事件适配器信号连接失败: " + str(e), flush=True)

    def _on_hijack_output(self, text: str):
        """★ v3.65: 拦截外部 Agent 输出 → 二次处理 → 显示"""
        if not getattr(self, '_hijack_mode_active', False):
            return
        # 底栏假终端显示原始拦截内容
        self.bottom_panel.append_intercepted_output(text, source="agent")
        # 右栏显示模式显示二次处理后内容
        self.mimo_panel.append_intercepted_display(text, source="agent")

    def _on_hijack_thinking(self, text: str):
        """★ v3.65: 拦截外部 Agent 思考过程"""
        if not getattr(self, '_hijack_mode_active', False):
            return
        self.bottom_panel.append_intercepted_output(text, source="thinking")
        self.mimo_panel.append_intercepted_display(text, source="thinking")

    def _on_hijack_tool_output(self, text: str):
        """★ v3.65: 拦截外部 Agent 工具调用输出"""
        if not getattr(self, '_hijack_mode_active', False):
            return
        self.bottom_panel.append_intercepted_output(text, source="tool")
        self.mimo_panel.append_intercepted_display(text, source="tool")

    def _on_hijack_status(self, text: str):
        """★ v3.65: 拦截外部 Agent 状态信息"""
        if not getattr(self, '_hijack_mode_active', False):
            return
        self.bottom_panel.append_intercepted_output(text, source="status")
        self.mimo_panel.append_intercepted_display(text, source="status")

    def _on_user_send(self, message, source='unknown'):
        """用户发送消息 — 优先路由到 Serve Bridge，同步显示到两个面板
        
        ★ v3.26: 恢复备份版简约设计
        - _sync_only: 仅同步显示，不发送到 serve_bridge（ollama 路径使用）
        """
        print(f"[SEND] source={source} msg={message[:50]}")
        
        # ★ v4.1.10: 身份类问题本地拦截（修复模型自称 Claude Code / MiMo Code）
        if hasattr(self.mimo_panel, '_try_local_identity_answer'):
            identity_answer = self.mimo_panel._try_local_identity_answer(message)
            if identity_answer:
                # 回显用户消息到底部终端
                self.bottom_panel.mimo_console.append_user_message(message)
                # 底部终端同步显示标准身份回答
                safe = identity_answer.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
                self.bottom_panel.mimo_console.append_html(
                    f"<div style='color:{Lemon.SUCCESS};margin:6px 0;padding:8px 10px;"
                    f"border-left:3px solid {Lemon.SUCCESS};background:{Lemon.SUCCESS_BG_DARK};border-radius:6px;'>"
                    f"🍋 {safe}</div>"
                )
                self.bottom_panel.mimo_console.input_field.clear()
                return
        
        # ★ _sync_only: 仅同步显示，不发送（ollama 路径已通过 EngineManager 发送）
        if hasattr(self.mimo_panel, '_sync_only') and self.mimo_panel._sync_only:
            self.mimo_panel._sync_only = False
            if source == 'right_panel':
                self.bottom_panel.mimo_console.append_user_message(message)
            elif source == 'bottom_console':
                self.mimo_panel.on_user_message(message)
            return
        
        # 记录命令历史
        self._add_command_history(message)

        # 处理特殊命令
        if message.startswith("/"):
            self._handle_special_command(message)
            return
        
        self.bottom_panel.log_output(f"[MIMO] 发送: {message}")
        
        # 如果来自右侧面板，同步显示到底部终端
        if source == 'right_panel':
            print(f"[SEND] 同步到 bottom console")
            self.bottom_panel.mimo_console.append_user_message(message)
            # 清空底部输入框
            self.bottom_panel.mimo_console.input_field.clear()
        # 如果来自底部终端，同步显示到右侧面板
        if source == 'bottom_console':
            print(f"[SEND] 同步到 right panel")
            self.mimo_panel.on_user_message(message)
            # 清空底部输入框
            self.bottom_panel.mimo_console.input_field.clear()
        
        # ★ v3.52: 根据模式决定发送路径
        # ★ v3.63: deepseek/ollama 模式优先使用 agent_chat（真正的 Agent 工具调用循环）
        mode_manager = self.mimo_panel._mode_manager if hasattr(self.mimo_panel, '_mode_manager') else None
        current_mode = mode_manager.mode_name if mode_manager else "auto"

        if current_mode == "mimo":
            # MIMO 模式：使用 serve_bridge（含 Process Bridge 降级链）
            # ★ 修复：不再检查 is_connected，因为 serve_bridge 内部有
            # Process Bridge / ACP Bridge / PTY Bridge 降级链，不依赖 HTTP 连接
            self.bottom_panel.log_output("[MIMO] 使用 Serve Bridge 发送", INFO)
            self.serve_bridge.send_message(message)
        elif current_mode == "ollama":
            # Ollama 模式：★ v3.63 优先使用 agent_chat（工具调用循环）
            self.bottom_panel.log_output("[Ollama] 使用 Agent 工具调用循环发送", INFO)
            self.mimo_panel._send_via_agent_chat(message, engine_id="ollama", use_agent=True)
        elif current_mode == "deepseek":
            # DeepSeek 模式：★ v3.63 优先使用 agent_chat（工具调用循环）
            self.bottom_panel.log_output("[DeepSeek] 使用 Agent 工具调用循环发送", INFO)
            self.mimo_panel._send_via_agent_chat(message, engine_id="deepseek", use_agent=True)
        else:
            # ★ Auto 模式：依次尝试 deepseek → ollama → serve_bridge → 报错
            # 优先使用 shared.engine_manager（与 _send_via_agent_chat 一致）
            try:
                from shared.engine_manager import get_engine_manager as _get_shared_em
                engine_mgr = _get_shared_em()
            except Exception:
                engine_mgr = getattr(self.mimo_panel, '_engine_manager', None)
            active_engine = engine_mgr.get_active_engine_id() if engine_mgr else ""
            if active_engine and active_engine not in ("mimocode",):
                adapter = engine_mgr._engines.get(active_engine) if engine_mgr else None
                if adapter and adapter.is_available():
                    self.bottom_panel.log_output(
                        f"[Auto] 使用用户选择引擎 {active_engine} Agent 工具调用循环发送", INFO
                    )
                    self.mimo_panel._send_via_agent_chat(
                        message, engine_id=active_engine, use_agent=True
                    )
                else:
                    preferred_order = ["deepseek", "ollama"]
                    available_engine = None
                    if engine_mgr:
                        try:
                            status = engine_mgr.get_status()
                            for eng_id in preferred_order:
                                eng_status = status.get(eng_id, {})
                                if eng_status.get("available", False):
                                    available_engine = eng_id
                                    break
                        except Exception:
                            pass
                    # ★ 兜底：直接检测 Ollama 端口（不依赖 engine_manager 状态）
                    if not available_engine:
                        try:
                            import socket
                            _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            _sock.settimeout(1.0)
                            if _sock.connect_ex(('127.0.0.1', 11434)) == 0:
                                available_engine = "ollama"
                            _sock.close()
                        except Exception:
                            pass
                    if available_engine:
                        self.mimo_panel._send_via_agent_chat(
                            message, engine_id=available_engine, use_agent=True
                        )
                    else:
                        if self.serve_bridge.is_connected:
                            self.serve_bridge.send_message(message)
                        else:
                            self.bottom_panel.log_output("[Auto] 所有引擎均不可用", ERROR)
                            self.mimo_panel.on_output(
                                f"<span style='color:{Lemon.ACCENT_RED};'>⚠️ 所有 AI 引擎均不可用。<br>"
                                f"请检查：<br>"
                                f"1) Ollama 是否运行（ollama serve）<br>"
                                f"2) DeepSeek API Key 是否配置<br>"
                                f"3) MIMO Code 服务是否启动（mimo serve --port 4097）</span>"
                            )

    def _on_right_panel_input_sync(self, text):
        """右侧面板输入框内容变化 → 同步到底部终端输入框"""
        print(f"[输入同步] 收到右侧同步信号: '{text[:30]}...'")
        if self.bottom_panel.mimo_console.input_field.text() != text:
            self.bottom_panel.mimo_console.input_field.blockSignals(True)
            self.bottom_panel.mimo_console.input_field.setText(text)
            # 光标移到末尾
            self.bottom_panel.mimo_console.input_field.setCursorPosition(len(text))
            self.bottom_panel.mimo_console.input_field.blockSignals(False)
            print(f"[输入同步] v 已同步到底部输入框")
        else:
            print(f"[输入同步] >> 内容相同，跳过")

    def _on_bottom_console_input_sync(self):
        """底部终端输入框内容变化 → 同步到右侧面板"""
        text = self.bottom_panel.mimo_console.input_field.text()
        js = f"var inp = document.getElementById('inputField'); if(inp && inp.value !== {json.dumps(text)}) {{ inp.value = {json.dumps(text)}; }}"
        self.mimo_panel._safe_run_js(js)

    def _on_miemie_task(self, text):
        """★ v4.3.8: 咩咩面板提交的命令回传主窗口。

        咩咩自身会执行 LLM 意图路由 + 工具链，主窗口只负责：
        1. 记录日志（让主窗口知道咩咩在做什么）
        2. 把主窗口通用命令（/new /usage /info 等）转发给控制台执行；
           咩咩私有命令（help/clear/analyze/search/memory/plan/db）由咩咩自己处理，不转发。
        """
        text = (text or "").strip()
        if not text:
            return
        self.bottom_panel.log_output(f"[咩咩] {text}")
        _MIEMIE_PRIVATE = ("/help", "/clear", "/analyze", "/search", "/memory", "/plan", "/db")
        if text.startswith("/") and not text.startswith(_MIEMIE_PRIVATE) \
                and hasattr(self, "_handle_special_command"):
            self._handle_special_command(text)

    def _handle_special_command(self, cmd):
        """处理底部终端的特殊命令"""
        console = self.bottom_panel.mimo_console
        
        if cmd == "/new":
            self.serve_bridge.create_session()
            self.bottom_panel.log_output("[MIMO] 正在创建新会话...", INFO)
        elif cmd == "/sessions":
            sessions = self.serve_bridge.list_sessions()
            if sessions:
                console.append_html(f'<div style="color:{TEXT_TERTIARY};margin:4px 0;">=== 会话列表 ({len(sessions)}) ===</div>')
                for s in sessions[:10]:
                    sid = s.get('id', '')[:20]
                    title = s.get('title', '无标题')[:40]
                    console.append_html(f'<div style="color:{TEXT_PRIMARY};margin:2px 0;padding:2px 8px;border-left:2px solid {MIMO_ORANGE};">{sid} — {title}</div>')
            else:
                console.append_html(f'<div style="color:{TEXT_TERTIARY};">无法获取会话列表</div>')
        elif cmd == "/models":
            models = self.serve_bridge.list_models()
            if models:
                console.append_html(f'<div style="color:{TEXT_TERTIARY};margin:4px 0;">=== 可用模型 ===</div>')
                for m in models[:10]:
                    mid = m.get('id', '?')
                    mname = m.get('name', mid)
                    console.append_html(f'<div style="color:{TEXT_PRIMARY};margin:2px 0;padding:2px 8px;border-left:2px solid {MIMO_ORANGE};">{mid} — {mname}</div>')
            else:
                console.append_html(f'<div style="color:{TEXT_TERTIARY};">无法获取模型列表</div>')
        elif cmd.startswith("/model "):
            model_id = cmd[7:].strip()
            if model_id:
                self.serve_bridge.switch_model(model_id)
                console.append_html(f'<div style="color:{Lemon.ACCENT_GREEN};margin:4px 0;">🔄 切换到模型: {model_id}</div>')
            else:
                console.append_html(f'<div style="color:red;">用法: /model &lt;模型ID&gt;</div>')
        elif cmd == "/usage":
            usage = self.serve_bridge.get_usage_info()
            if usage:
                inp = usage.get("input_tokens", usage.get("input", 0))
                out = usage.get("output_tokens", usage.get("output", 0))
                total = usage.get("total_tokens", inp + out)
                console.append_html(f'<div style="color:{TEXT_PRIMARY};margin:4px 0;">=== Token 用量 ===</div>')
                console.append_html(f'<div style="color:{TEXT_TERTIARY};margin:2px 0;">输入: {inp} | 输出: {out} | 总计: {total}</div>')
                # 同步到右侧面板
                self.mimo_panel.show_usage(usage)
            else:
                console.append_html(f'<div style="color:{TEXT_TERTIARY};">无法获取用量信息</div>')
        elif cmd == "/info":
            sid = self.serve_bridge.session_id or "无"
            console.append_html(f'<div style="color:{TEXT_PRIMARY};margin:4px 0;">=== 会话信息 ===</div>')
            console.append_html(f'<div style="color:{TEXT_TERTIARY};margin:2px 0;">会话ID: {sid[:32] if len(sid) > 32 else sid}</div>')
            console.append_html(f'<div style="color:{TEXT_TERTIARY};margin:2px 0;">连接状态: {"已连接" if self.serve_bridge.is_connected else "未连接"}</div>')
            console.append_html(f'<div style="color:{TEXT_TERTIARY};margin:2px 0;">端口: {self.serve_bridge.port}</div>')
            # 同时获取用量
            usage = self.serve_bridge.get_usage_info()
            if usage:
                inp = usage.get("input_tokens", usage.get("input", 0))
                out = usage.get("output_tokens", usage.get("output", 0))
                total = usage.get("total_tokens", inp + out)
                console.append_html(f'<div style="color:{TEXT_TERTIARY};margin:2px 0;">Token: {total} (入{inp}/出{out})</div>')
        elif cmd == "/cancel":
            self.serve_bridge.cancel_current_task()
            console.append_html(f'<div style="color:{Lemon.ACCENT_ORANGE};margin:4px 0;">[] 已请求取消当前任务</div>')
            self.bottom_panel.log_output("[MIMO] 取消当前任务", WARNING)
        elif cmd == "/refresh":
            self.serve_bridge.refresh_connection()
            self.bottom_panel.log_output("[MIMO] 已刷新连接", INFO)
        elif cmd == "/clear":
            console.clear_output()
        elif cmd == "/help":
            console.append_html(f"""
                <div style="color:{TEXT_PRIMARY};margin:4px 0;line-height:1.8;">
                <b style="color:{MIMO_ORANGE};">命令列表:</b><br>
                <span style="color:{TEXT_TERTIARY};">/new</span> — 新建会话<br>
                <span style="color:{TEXT_TERTIARY};">/sessions</span> — 列出会话<br>
                <span style="color:{TEXT_TERTIARY};">/models</span> — 列出模型<br>
                <span style="color:{TEXT_TERTIARY};">/model &lt;id&gt;</span> — 切换模型<br>
                <span style="color:{TEXT_TERTIARY};">/usage</span> — 查看Token用量<br>
                <span style="color:{TEXT_TERTIARY};">/info</span> — 查看会话信息<br>
                <span style="color:{TEXT_TERTIARY};">/cancel</span> — 取消当前任务<br>
                <span style="color:{TEXT_TERTIARY};">/refresh</span> — 刷新连接<br>
                <span style="color:{TEXT_TERTIARY};">/clear</span> — 清除输出<br>
                <span style="color:{TEXT_TERTIARY};">/diagnose</span> — 完整诊断报告<br>
                <span style="color:{TEXT_TERTIARY};">/monitor</span> — 即时连接监测<br>
                <span style="color:{TEXT_TERTIARY};">/help</span> — 显示帮助<br>
                <span style="color:{TEXT_TERTIARY};">/cluster start_full</span> — 启动完整集群<br>
                <span style="color:{TEXT_TERTIARY};">/cluster start_minimal</span> — 启动最小模式<br>
                <span style="color:{TEXT_TERTIARY};">/cluster stop</span> — 停止集群<br>
                <span style="color:{TEXT_TERTIARY};">/cluster toggle</span> — 切换网格视图<br>
                <span style="color:{TEXT_TERTIARY};">/hybrid</span> — 进入混合AI模式<br>
                <span style="color:{TEXT_TERTIARY};">/exit</span> — 返回原始界面
                </div>
            """)
        elif cmd.startswith("/cluster "):
            # 集群命令处理
            subcmd = cmd[9:].strip()
            if subcmd == "start_full":
                self._start_cluster(5)
            elif subcmd == "start_minimal":
                self._start_cluster(2)
            elif subcmd == "stop":
                self._stop_cluster()
            elif subcmd == "toggle":
                self._toggle_instance_grid()
            else:
                console.append_html(f'<div style="color:red;">未知集群命令: {subcmd}</div>')
        elif cmd == "/hybrid":
            self._on_service_mode_switch('hybrid')
        elif cmd == "/exit" or cmd == "/original":
            self._on_service_mode_switch('original')
        elif cmd.startswith("/mode "):
            # 服务模式切换
            mode = cmd[6:].strip()
            self._on_service_mode_switch(mode)
        elif cmd.startswith("/agent "):
            # Agent模式切换
            mode = cmd[7:].strip()
            self._on_agent_mode_switch(mode)
        elif cmd == "/diagnose":
            # ★ v3.61: 完整诊断报告
            console.append_html(
                f'<div style="color:{TEXT_TERTIARY};margin:4px 0;">正在生成完整诊断报告...</div>'
            )
            try:
                from core.connection_monitor import ConnectionMonitor
                monitor = ConnectionMonitor.instance()
                if monitor._output_callback is None:
                    monitor.set_output_callback(
                        lambda html: self.bottom_panel.mimo_console.append_html(html)
                    )
                monitor.get_diagnostic_report()
            except Exception as e:
                console.append_html(
                    f'<div style="color:red;">诊断失败: {e}</div>'
                )
        elif cmd == "/monitor":
            # ★ v3.61: 手动触发监测
            console.append_html(
                f'<div style="color:{TEXT_TERTIARY};margin:4px 0;">正在执行即时监测...</div>'
            )
            try:
                from core.connection_monitor import ConnectionMonitor
                monitor = ConnectionMonitor.instance()
                if monitor._output_callback is None:
                    monitor.set_output_callback(
                        lambda html: self.bottom_panel.mimo_console.append_html(html)
                    )
                result = monitor.check_now()
                # 输出即时结果摘要
                all_ok = result.get("all_healthy", False)
                if all_ok:
                    console.append_html(
                        f'<div style="color:{Lemon.ACCENT_GREEN};margin:2px 0;">&#10003; 所有服务正常 (总耗时 {result["total_ms"]}ms)</div>'
                    )
                else:
                    issues = result.get("issues", [])
                    console.append_html(
                        f'<div style="color:{Lemon.ACCENT_RED};margin:2px 0;">&#10007; 发现 {len(issues)} 个问题 (总耗时 {result["total_ms"]}ms)</div>'
                    )
                    for issue in issues:
                        console.append_html(
                            f'<div style="color:{Lemon.ACCENT_ORANGE};margin:1px 0;padding-left:12px;">&#9888; {issue}</div>'
                        )
            except Exception as e:
                console.append_html(
                    f'<div style="color:red;">监测失败: {e}</div>'
                )
        else:
            console.append_html(f'<div style="color:red;">未知命令: {cmd}，输入 /help 查看帮助</div>')

    # ★ B3: 进程/M监视器输出合并入 output_view — [进程] 前缀，紫色区分
    _PROCESS_COLOR = "#9b59b6"

    def _append_process_output(self, text):
        """写入 output_view（[进程] 前缀 + 紫色）并滚动到底部"""
        self.bottom_panel.log_output(f"[进程] {text}", self._PROCESS_COLOR)
        sb = self.bottom_panel.output_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_mimo_raw_output(self, text):
        """★ B3: Lemon Code 原始输出 → output_view（[进程] 紫色前缀）"""
        self._append_process_output(text)

    def _show_mimo_monitor(self):
        """★ B3: 在 output_view 初始信息显示信息横幅（[进程] 前缀）"""
        bp = self.bottom_panel
        c = self._PROCESS_COLOR
        bp.log_output("╔══════════════════════════════════════════╗", c)
        bp.log_output("║       Lemon Code 进程输出监视器          ║", c)
        bp.log_output("╠══════════════════════════════════════════╣", c)
        bp.log_output(f"║  工作目录: {self.engine.project_path}", c)
        bp.log_output(f"║  Lemon EXE: {MIMOProcessBridge._mimo_exe_path()}", c)
        bp.log_output("║  状态: 就绪", c)
        bp.log_output("╚══════════════════════════════════════════╝", c)
        bp.log_output("在右侧面板输入消息后回车发送，输出将实时显示在此处。", c)

    def _start_gui_bridge(self):
        """后台启动 GUI 虫桥"""
        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG

        def log(html):
            QMetaObject.invokeMethod(
                self.bottom_panel.output_view, "append", Qt.QueuedConnection,
                Q_ARG(str, html)
            )

        log(f'<span style="color:{Lemon.ACCENT_BLUE};">[GUI虫桥] 正在启动 Lemon Code GUI...</span>')
        if self.gui_bridge.start_mimo_gui():
            log(f'<span style="color:{Lemon.ACCENT_GREEN};">[GUI虫桥] Lemon Code GUI 已成功启动并连接</span>')
            self.mimo_panel.set_connected(True, "GUI")
        else:
            log(f'<span style="color:{Lemon.BRAND_ORANGE};">[GUI虫桥] 启动失败，请检查 Lemon Code 是否可用</span>')

    def _create_editor_area(self):
        panel = QWidget()
        panel.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        breadcrumb = QFrame()
        breadcrumb.setFixedHeight(32)
        breadcrumb.setStyleSheet(f"background: {BG_SECONDARY}; border-bottom: 1px solid {BORDER_SUBTLE};")
        bc_layout = QHBoxLayout(breadcrumb)
        bc_layout.setContentsMargins(14, 0, 14, 0)
        self.breadcrumb_label = QLabel("LEMONCODE")
        self.breadcrumb_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: {FONT_SIZE_SM}; background: transparent;")
        bc_layout.addWidget(self.breadcrumb_label)
        bc_layout.addStretch()

        layout.addWidget(breadcrumb)

        # 会话 Tab 栏
        self.session_tabs = QTabWidget()
        self.session_tabs.setFixedHeight(32)
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background: {BG_ROOT};
                border: none;
                border-bottom: 1px solid {BORDER_SUBTLE};
            }}
            QTabBar::tab {{
                background: {BG_SECONDARY};
                color: {TEXT_TERTIARY};
                border: none;
                border-radius: 0;
                padding: 4px 14px;
                font-size: {FONT_SIZE_XS};
                min-width: 80px;
                margin-right: 1px;
            }}
            QTabBar::tab:selected {{
                background: {BG_PRIMARY};
                color: {MIMO_ORANGE};
                border-bottom: 2px solid {MIMO_ORANGE};
            }}
            QTabBar::tab:hover {{
                color: {TEXT_PRIMARY};
            }}
            QTabBar::close-button {{
                image: none;
                width: 12px;
                height: 12px;
            }}
        """)
        self.session_tabs.tabCloseRequested.connect(self._close_session_tab)
        self.session_tabs.currentChanged.connect(self._on_session_tab_changed)
        layout.addWidget(self.session_tabs)

        self.editor_tabs = QTabWidget()
        self.editor_tabs.setTabsClosable(True)
        # ★ v4.7.x: 复用 CustomTabBar（自绘 × 按钮 + 双击/右键信号），避免 PyQt5 主题图标 bug
        from ui.tab_bar import CustomTabBar as _EditorTabBar
        self._editor_tab_bar = _EditorTabBar(self)
        self.editor_tabs.setTabBar(self._editor_tab_bar)
        # ★ v4.7.x: 清 PyQt5 native frame 上方/左边白线
        self.editor_tabs.setStyleSheet(f"""
            QTabWidget {{ background: {BG_ROOT}; border: none; padding: 0; margin: 0; }}
            QTabWidget::pane {{ background: {BG_ROOT}; border: none; border-top: 0 solid transparent; top: 0; }}
            QTabBar {{ background: {BG_SECONDARY}; border: none; qproperty-drawBase: 0; outline: 0; }}
            QTabBar::tab {{ background: {BG_SECONDARY}; color: {TEXT_TERTIARY}; border: none;
                padding: 5px 12px; min-width: 80px; outline: 0; }}
            QTabBar::tab:hover {{ background: rgba(255,122,47,0.08); color: {TEXT_PRIMARY}; }}
            QTabBar::tab:selected {{ background: {BG_ROOT}; color: {MIMO_ORANGE};
                border-bottom: 2px solid {MIMO_ORANGE}; font-weight: 600; }}
            QTabBar::close-button {{ width: 0; height: 0; }}
        """)
        self.editor_tabs.tabCloseRequested.connect(self._close_editor_tab)
        # ★ v4.7.x: 编辑器 tab 双击 = 重命名（保存为文件名），右键 = 关闭其他/右侧
        self._editor_tab_bar.tab_double_clicked.connect(self._on_editor_tab_double_clicked)
        self._editor_tab_bar.tab_context_menu_requested.connect(self._on_editor_tab_context_menu)

        welcome = self._create_welcome_tab()
        self.editor_tabs.addTab(welcome, "LEMONCODE")
        layout.addWidget(self.editor_tabs, 1)

        return panel

    def _create_welcome_tab(self):
        widget = QWidget()
        widget.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)

        # NINGMENG logo
        mi = QLabel()
        mi.setAlignment(Qt.AlignCenter)
        mi.setTextFormat(Qt.RichText)
        mi.setText(
            f'<span style="color:{XIAOMI_ORANGE};font-size:20px;font-weight:900;'
            f'font-family:{FONT_BRAND};">NINGMENG</span>'
        )
        mi.setStyleSheet("background: transparent;")
        layout.addWidget(mi)

        # LEMON CODE logo
        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setTextFormat(Qt.RichText)
        logo.setText(
            f'<span style="color:{MIMO_ORANGE};font-size:32px;font-weight:900;'
            f'font-family:{FONT_CODE_LOGO};text-shadow:0 0 20px rgba(230,126,34,0.3);">'
            f'LEMON</span>'
            f'<span style="color:{TEXT_TERTIARY};font-size:32px;font-weight:300;'
            f'font-family:{FONT_CODE_LOGO};margin-left:10px;">CODE</span>'
        )
        logo.setStyleSheet("background: transparent;")
        layout.addWidget(logo)

        # 副标题
        sub = QLabel("由 Lemon Auto 驱动的扩展 Agent")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: {FONT_SIZE_MD}; background: transparent;")
        layout.addWidget(sub)

        # 项目理念说明
        philosophy = QLabel()
        philosophy.setAlignment(Qt.AlignCenter)
        philosophy.setWordWrap(True)
        philosophy.setTextFormat(Qt.RichText)
        philosophy.setText(
            f'<div style="text-align:center;line-height:1.6;max-width:500px;">'
            f'<span style="color:{TEXT_SECONDARY};font-size:12px;">'
            f'<b style="color:{XIAOMI_ORANGE};">LemonCode</b> 是一个支持多引擎的 AI Agent 产品<br>'
            f'支持 MIMO Code、Ollama、DeepSeek 等多种 AI 引擎进行算力支撑<br>'
            f'基于 Trae 开发，遵循二次开发协议，保留原始技术引用说明'
            f'</span></div>'
        )
        philosophy.setStyleSheet("background: transparent; margin: 10px 0;")
        layout.addWidget(philosophy)

        # 架构信息
        info = QLabel()
        info.setAlignment(Qt.AlignCenter)
        info.setTextFormat(Qt.RichText)
        info.setText(
            f'<div style="text-align:center;line-height:1.8;">'
            f'<span style="color:{TEXT_TERTIARY};font-size:11px;">'
            f'后端: Lemon Code (柠檬AI)<br>'
            f'模式: Build · Lemon Auto (Lemon-V2.5)<br>'
            f'架构: 容器模式 — 输入 → Agent → Lemon Code → 分发UI'
            f'</span></div>'
        )
        info.setStyleSheet("background: transparent;")
        layout.addWidget(info)

        return widget

    def _create_status_bar(self):
        # ★ v4.7.17: 状态内容已由全局底栏 _build_global_bottom_bar 提供
        #（self.status_label / self.persona_status_label 已在底栏中）。
        # 此处仅保留 QStatusBar 兼容（隐藏）+ 咩咩人格炼化轮询定时器。
        sb = QStatusBar()
        sb.setFixedHeight(26)
        sb.hide()
        self.setStatusBar(sb)

        if not hasattr(self, 'persona_status_label'):
            self.persona_status_label = QLabel("")
            self.persona_status_label.setStyleSheet(
                f"color:{Lemon.BRAND_ORANGE}; font-size:11px; font-weight:600; padding:0 6px;")
        # 诊断开关：LEMON_NO_PERSONA_TIMER=1 时禁用（排查主线程卡顿）
        if os.environ.get("LEMON_NO_PERSONA_TIMER") != "1":
            self._persona_status_timer = QTimer(self)
            self._persona_status_timer.setInterval(3000)   # 每 3s 轮询
            self._persona_status_timer.timeout.connect(self._poll_persona_status)
            self._persona_status_timer.start()

    def _poll_persona_status(self):
        """轮询咩咩后台炼化队列，更新状态栏（★ v4.4.2）。"""
        try:
            from ui.miemie_engine import tool_persona_status
            st = tool_persona_status(limit=100)
            if not st.get("ok"):
                return
            items = st.get("items", [])
            running = sum(1 for i in items if i.get("state") == "running")
            queued = st.get("queue_len", 0)
            pending = queued + sum(1 for i in items if i.get("state") == "queued")
            if running or pending:
                self.persona_status_label.setText(f"人格炼化中 {running} 个 · 队列 {pending}")
            else:
                self.persona_status_label.setText("")
        except Exception:
            pass

    def _load_project(self, path):
        files = self.engine.scan_project(path)
        self.explorer.load_project(path, files)
        self.mimo_panel.set_project_path(path)
        self.proc_bridge.project_path = path
        self.gui_bridge.project_path = path
        self.bottom_panel.terminal.set_cwd(path)
        self.git_manager = GitManager(path)
        self.git_manager.refresh_status()
        self.explorer.set_git_manager(self.git_manager)
        self._update_status_bar()
        # ★ v4.7.17+ status_label 现在只展示版本号，不再显示项目路径
        # （路径冗余：标题栏已有显示）

    def _on_lemon_robot_clicked(self):
        """柠檬AI小助手点击事件 — 表情变化已在 LemonRobotWidget 内部处理"""
        pass

    def _on_workspace_switch(self, ws_path: str):
        """工作区切换信号处理：更新文件浏览器、Git、终端等工作目录"""
        if not ws_path or not os.path.isdir(ws_path):
            print(f"[Workspace] 路径无效: {ws_path}")
            return
        try:
            print(f"[Workspace] 主窗口切换工作区: {ws_path}")
            # 更新引擎项目路径
            self.engine.project_path = ws_path
            # 更新 serve_bridge 工作目录
            if hasattr(self, 'serve_bridge') and self.serve_bridge:
                self.serve_bridge.project_path = ws_path
            # 重新加载项目（更新 explorer/git/terminal）
            self._load_project(ws_path)
            # 更新面包屑
            if hasattr(self, 'breadcrumb_label'):
                self.breadcrumb_label.setText(f"  {ws_path}")
        except Exception as e:
            print(f"[Workspace] 切换失败: {e}")
            import traceback
            traceback.print_exc()

    def _on_file_selected(self, rel_path):
        content = self.engine.read_file(rel_path)
        self._open_editor_tab(rel_path, content)

    def _open_editor_tab(self, rel_path, content):
        for i in range(self.editor_tabs.count()):
            existing = self.editor_tabs.tabText(i).rstrip(' *')
            if existing == rel_path:
                self.editor_tabs.setCurrentIndex(i)
                return
        editor = CodeEditor()
        editor.set_code(content, file_path=rel_path)
        editor.save_requested.connect(lambda fp, c: self._save_file(fp, c))
        editor.content_changed.connect(lambda: self._on_editor_content_changed(editor))
        # ★ v0.7.0: 连接 LSP 信号
        self._connect_editor_lsp(editor)
        idx = self.editor_tabs.addTab(editor, rel_path)
        self.editor_tabs.setCurrentIndex(idx)
        self.breadcrumb_label.setText(f"  {self.engine.project_path} > {rel_path}")
        self._add_recent_file(rel_path)
        # 更新左侧符号大纲
        self.explorer.update_symbols(rel_path, content)
        # ★ v0.7.0: 通知 LSP 服务器打开文档
        abs_path = os.path.join(self.engine.project_path, rel_path) if not os.path.isabs(rel_path) else rel_path
        self.lsp_manager.open_document(abs_path, content)
    
    def _on_symbol_clicked(self, file_path, line_num):
        """点击符号大纲 — 打开文件并跳转到行"""
        content = self.engine.read_file(file_path)
        if content:
            self._open_editor_tab(file_path, content)
            current = self.editor_tabs.currentWidget()
            if isinstance(current, CodeEditor):
                current.go_to_line(line_num)

    def _connect_editor_lsp(self, editor):
        """★ v0.7.0: 连接 CodeEditor 的 LSP 信号到 LSPServerManager"""
        # 实时补全请求 → LSP completion
        editor.lsp_completion_requested.connect(
            lambda fp, line, char: self.lsp_manager.request_completion(fp, line, char)
        )
        # Ctrl+Click 跳转定义 → LSP definition
        editor.lsp_definition_requested.connect(
            lambda fp, line, char: self.lsp_manager.request_definition(fp, line, char)
        )
        # 文档变更 → LSP didChange
        editor.lsp_didchange.connect(
            lambda fp, content, ver: self.lsp_manager.change_document(fp, content, ver)
        )
    
    def _on_editor_content_changed(self, editor):
        """编辑器内容变化 — 更新tab标题的*标记"""
        for i in range(self.editor_tabs.count()):
            if self.editor_tabs.widget(i) == editor:
                tab_name = self.editor_tabs.tabText(i).rstrip(' *')
                if editor.is_dirty:
                    if not tab_name.startswith('*'):
                        self.editor_tabs.setTabText(i, f"*{tab_name}")
                else:
                    self.editor_tabs.setTabText(i, tab_name)
                break
    
    def _on_save_current_file(self):
        """Ctrl+S — 保存当前文件"""
        current_widget = self.editor_tabs.currentWidget()
        if not isinstance(current_widget, CodeEditor):
            self.bottom_panel.log_output("[保存] 当前标签不是代码编辑器", WARNING)
            return
        content = current_widget.get_content()
        file_path = current_widget.file_path
        if not file_path:
            self.bottom_panel.log_output("[保存] 无文件路径", WARNING)
            return
        self._save_file(file_path, content)
    
    def _save_file(self, file_path, content):
        """保存文件到磁盘"""
        try:
            abs_path = os.path.join(self.engine.project_path, file_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            
            # ★ 保存时自动格式化（v0.6.0 新增）
            if self.formatter_manager.format_on_save:
                success, formatted_content, msg = self.formatter_manager.format_if_enabled(abs_path, content)
                if success and formatted_content != content:
                    content = formatted_content
                    self.bottom_panel.log_output(f"[格式化] 自动格式化完成", SUCCESS)
                elif not success and msg:
                    self.bottom_panel.log_output(f"[格式化] {msg}", WARNING)
            
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(content)
            # 更新编辑器状态
            current_widget = self.editor_tabs.currentWidget()
            if isinstance(current_widget, CodeEditor) and current_widget.file_path == file_path:
                current_widget.mark_saved()
                # 更新tab标题
                for i in range(self.editor_tabs.count()):
                    if self.editor_tabs.widget(i) == current_widget:
                        self.editor_tabs.setTabText(i, file_path)
                        break
            self.bottom_panel.log_output(f"[保存] {file_path}", SUCCESS)
        except Exception as e:
            self.bottom_panel.log_output(f"[保存] 失败: {e}", ERROR)
    
    def _format_current_file(self):
        """Alt+Shift+F — 手动格式化当前文件"""
        current_widget = self.editor_tabs.currentWidget()
        if not isinstance(current_widget, CodeEditor):
            self.bottom_panel.log_output("[格式化] 当前标签不是代码编辑器", WARNING)
            return
        
        file_path = current_widget.file_path
        if not file_path:
            self.bottom_panel.log_output("[格式化] 无文件路径", WARNING)
            return
        
        content = current_widget.get_content()
        abs_path = os.path.join(self.engine.project_path, file_path)
        
        success, formatted_content, msg = self.formatter_manager.format(abs_path, content)
        
        if success and formatted_content != content:
            # 更新编辑器内容
            current_widget.set_content(formatted_content)
            current_widget.mark_dirty()
            self.bottom_panel.log_output(f"[格式化] {file_path} 已格式化", SUCCESS)
        elif success and formatted_content == content:
            self.bottom_panel.log_output(f"[格式化] {file_path} 无需格式化", INFO)
        else:
            self.bottom_panel.log_output(f"[格式化] 失败: {msg}", ERROR)
    
    def _on_close_current_tab(self):
        """Ctrl+W — 关闭当前标签"""
        idx = self.editor_tabs.currentIndex()
        if idx < 0:
            return
        current_widget = self.editor_tabs.widget(idx)
        if isinstance(current_widget, CodeEditor) and current_widget.is_dirty:
            reply = QMessageBox.question(
                self, "未保存的更改",
                f"文件 {current_widget.file_path} 有未保存的更改，是否保存后关闭？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )
            if reply == QMessageBox.Save:
                self._save_file(current_widget.file_path, current_widget.get_content())
            elif reply == QMessageBox.Cancel:
                return
        # ★ 保存关闭的标签信息（用于 Ctrl+Shift+T 恢复）
        if isinstance(current_widget, CodeEditor):
            self._last_closed_tab = {
                "file_path": current_widget.file_path,
                "content": current_widget.get_content(),
            }
        self.editor_tabs.removeTab(idx)

    # ================================================================
    # ★ 新增快捷键处理（v3.46）
    # ================================================================
    def _on_new_session_shortcut(self):
        """Ctrl+N — 新建会话"""
        self.bottom_panel.mimo_console._on_new_session()
        self.bottom_panel.log_output("[快捷键] Ctrl+N — 新建会话", INFO)

    def _on_new_file_shortcut(self):
        """Ctrl+Shift+N — 新建文件"""
        file_path, ok = QInputDialog.getText(self, "新建文件", "输入文件名（含路径）:")
        if ok and file_path.strip():
            full_path = os.path.join(self.engine.project_path, file_path.strip())
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write("")
            self._open_editor_tab(file_path.strip(), "")
            self.bottom_panel.log_output(f"[新建文件] {file_path.strip()}", SUCCESS)

    def _on_next_tab(self):
        """Ctrl+Tab — 切换到下一个标签页"""
        count = self.editor_tabs.count()
        if count > 0:
            next_idx = (self.editor_tabs.currentIndex() + 1) % count
            self.editor_tabs.setCurrentIndex(next_idx)

    def _on_prev_tab(self):
        """Ctrl+Shift+Tab — 切换到上一个标签页"""
        count = self.editor_tabs.count()
        if count > 0:
            prev_idx = (self.editor_tabs.currentIndex() - 1) % count
            self.editor_tabs.setCurrentIndex(prev_idx)

    def _on_toggle_theme(self):
        """v6.0-S B-3: Ctrl+Shift+D — 切换深色/浅色主题(ThemeManager驱动)。"""
        tm = ThemeManager.instance()
        tm.toggle()

    def _on_theme_changed(self, dark: bool):
        """v6.0-S B-3: 主题变更回调 — 重新应用QSS+通知组件。"""
        self.setStyleSheet(global_stylesheet())
        label = "深色" if dark else "浅色"
        self.bottom_panel.log_output("[主题] 已切换至" + label + "模式", INFO)
        theme_mode = "dark" if dark else "light"
        if hasattr(self, 'mimo_panel') and self.mimo_panel is not None:
            self.mimo_panel._safe_run_js("if(typeof onThemeChanged==='function')onThemeChanged('" + theme_mode + "');")

    def _on_restore_closed_tab(self):
        """Ctrl+Shift+T — 恢复最近关闭的标签页"""
        last = getattr(self, '_last_closed_tab', None)
        if last and last.get("file_path"):
            self._open_editor_tab(last["file_path"], last.get("content", ""))
            self.bottom_panel.log_output(f"[恢复] {last['file_path']}", SUCCESS)
            self._last_closed_tab = None
        else:
            self.bottom_panel.log_output("[恢复] 没有可恢复的标签页", WARNING)

    def _on_open_settings(self):
        """Ctrl+, — 打开设置面板（含 API Key 配置）"""
        self.bottom_panel.mimo_console.append_html(
            f'<div style="color:{MIMO_ORANGE};margin:4px 0;">⚙ 设置面板</div>'
        )
        self.bottom_panel.log_output("[设置] 打开设置面板 (Ctrl+,)", INFO)
        # 触发右侧面板加载设置
        if hasattr(self, 'mimo_panel'):
            self.mimo_panel._safe_run_js(
                "if(typeof loadSettingsFromBackend==='function')loadSettingsFromBackend();"
            )
        # ★ v4.5.1 API Key 配置对话框
        self._open_api_config_dialog()

    def _on_cycle_engine(self):
        """★ v4.5.1 Ctrl+Alt+E — 循环切换 AI 引擎（Ollama → DeepSeek → MIMO → …）"""
        em = getattr(getattr(self, 'mimo_panel', None), '_engine_manager', None)
        if em is None:
            self.bottom_panel.log_output("[引擎] EngineManager 不可用，无法切换驱动", WARNING)
            return
        try:
            cycle = ["ollama", "deepseek", "mimocode"]
            status = em.get_status()
            cur = (status or {}).get("active_engine", "") if isinstance(status, dict) else ""
            idx = cycle.index(cur) if cur in cycle else -1
            nxt = cycle[(idx + 1) % len(cycle)]
            em.set_active_engine(nxt)
            names = {"ollama": "Ollama（本地）", "deepseek": "DeepSeek（云端）", "mimocode": "MIMO Code"}
            self.bottom_panel.log_output(f"[引擎] 驱动已切换: {names.get(nxt, nxt)}", SUCCESS)
        except Exception as e:
            self.bottom_panel.log_output(f"[引擎] 驱动切换失败: {e}", ERROR)

    def _open_api_config_dialog(self):
        """★ v4.5.1 API Key 配置对话框（DeepSeek 云端；保存到 ~/.mimo_agent/settings.json 并立即生效）"""
        try:
            from core.settings_manager import get_settings_manager
            sm = get_settings_manager()
            em = getattr(getattr(self, 'mimo_panel', None), '_engine_manager', None)

            dialog = QDialog(self)
            dialog.setWindowTitle("API 配置")
            dialog.setMinimumWidth(400)
            layout = QVBoxLayout(dialog)
            layout.setSpacing(10)

            title = QLabel("AI 引擎 API 配置")
            title.setStyleSheet(f"font-size:15px;font-weight:bold;color:{Lemon.BRAND_ORANGE};")
            layout.addWidget(title)

            tip = QLabel("配置后立即生效，并持久化保存到 ~/.mimo_agent/settings.json。")
            tip.setStyleSheet("color:#888;font-size:11px;")
            tip.setWordWrap(True)
            layout.addWidget(tip)

            layout.addWidget(QLabel("DeepSeek API Key（deepseek-chat / V4 / R1）"))
            ds_input = QLineEdit(sm.get('api_keys.deepseek', ''))
            ds_input.setEchoMode(QLineEdit.Password)
            ds_input.setPlaceholderText("sk-…")
            layout.addWidget(ds_input)

            status_lbl = QLabel()
            status_lbl.setStyleSheet("color:#888;font-size:11px;")
            layout.addWidget(status_lbl)

            def _refresh_status():
                has = bool(sm.get('api_keys.deepseek', ''))
                status_lbl.setText(f"当前状态: {'已配置 DeepSeek Key' if has else '未配置 DeepSeek Key'}")

            _refresh_status()

            btn_row = QHBoxLayout()
            save_btn = QPushButton("保存")
            save_btn.setStyleSheet(f"background:{Lemon.BRAND_ORANGE};color:#000;font-weight:bold;border:none;border-radius:5px;padding:6px 16px;")
            close_btn = QPushButton("关闭")
            close_btn.setStyleSheet("background:#2a2a30;color:#ccc;border:1px solid #3a3a42;border-radius:5px;padding:6px 16px;")
            btn_row.addStretch()
            btn_row.addWidget(save_btn)
            btn_row.addWidget(close_btn)
            layout.addLayout(btn_row)

            def _on_save():
                key = ds_input.text().strip()
                sm.set('api_keys.deepseek', key, auto_save=True)
                if em is not None:
                    try:
                        em.set_api_key('deepseek', key)
                    except Exception as e:
                        print(f"[API] set_api_key 失败: {e}", flush=True)
                self.bottom_panel.log_output("[API] DeepSeek API Key 已保存", SUCCESS)
                _refresh_status()

            save_btn.clicked.connect(_on_save)
            close_btn.clicked.connect(dialog.accept)
            dialog.exec_()
        except Exception as e:
            print(f"[API] 配置对话框异常: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def _restore_api_keys(self, em):
        """★ v4.5.1 启动时从配置恢复 API Key 到 EngineManager"""
        try:
            from core.settings_manager import get_settings_manager
            sm = get_settings_manager()
            key = sm.get('api_keys.deepseek', '')
            if key:
                em.set_api_key('deepseek', key)
                print("[API] 已从配置恢复 DeepSeek API Key", flush=True)
        except Exception as e:
            print(f"[API] 恢复 API Key 失败: {e}", flush=True)

    def _on_toggle_fullscreen(self):
        """F11 — 切换全屏模式"""
        if self.isFullScreen():
            self.showNormal()
            self.bottom_panel.log_output("[全屏] 已退出全屏", INFO)
        else:
            self.showFullScreen()
            self.bottom_panel.log_output("[全屏] 已进入全屏 (F11)", INFO)

    def resizeEvent(self, event):
        """v6.0-S B-2: 响应式布局 — 窗口宽度驱动三栏折叠/展开。"""
        super().resizeEvent(event)
        w = self.width()
        prev_mode = self._responsive_layout_mode
        if w < 800:
            new_mode = "compact"
        elif w < 1200:
            new_mode = "collapsed"
        else:
            new_mode = "full"
        self._responsive_layout_mode = new_mode
        if new_mode != prev_mode:
            self._apply_responsive_layout(new_mode)

    # ==================== ★ TRAE 同款：AI 面板布局三档切换 ====================
    def _set_ai_layout(self, mode: str):
        """切换 AI 聊天面板布局并持久化（right=右侧栏 / bottom=底部 / hidden=收起）。"""
        if mode not in ('right', 'bottom', 'hidden'):
            return
        self._ai_layout_mode = mode
        try:
            from PyQt5.QtCore import QSettings as _QS
            _QS('LemonCode', 'MIMOWindow').setValue('ai_layout_mode', mode)
        except Exception:
            pass
        self._apply_ai_layout(mode)
        try:
            self.bottom_panel.log_output(f"[布局] AI 面板 → {mode}", INFO)
        except Exception:
            pass

    def _apply_ai_layout(self, mode: str):
        """把 session_workspace 在 h/v splitter 间迁移；hidden 仅隐藏宿主。"""
        ws = getattr(self, 'session_workspace', None)
        h = getattr(self, '_h_splitter', None)
        v = getattr(self, '_v_splitter', None)
        if ws is None or h is None or v is None:
            return

        # 1) 前端 body class 同步（hidden 时保留原 class，宿主隐藏即可）
        try:
            if hasattr(ws, 'apply_layout_mode'):
                ws.apply_layout_mode(mode)
        except Exception:
            pass

        # 2) Qt 布局迁移
        if mode == 'bottom':
            if ws.parent() is not v:
                v.insertWidget(1, ws)   # 编辑器(h_splitter)之下、终端面板之上
            ws.show()
            v.setSizes([620, 300, 160]) # 编辑器 / AI 面板 / 终端（相对比例）
        elif mode == 'right':
            if ws.parent() is not h:
                h.addWidget(ws)         # 追加回 h_splitter 末位（恢复三栏）
            ws.show()
            # 复用响应式逻辑恢复三栏比例
            self._apply_responsive_layout(getattr(self, '_responsive_layout_mode', 'full'))
        else:  # hidden
            ws.hide()

        # 3) 标题栏按钮组状态回写
        try:
            if getattr(self, 'title_bar', None) is not None and hasattr(self.title_bar, 'set_layout_mode'):
                self.title_bar.set_layout_mode(mode)
        except Exception:
            pass

    def _apply_responsive_layout(self, mode: str):
        """根据窗口宽度调整三栏布局比例。"""
        # ★ 布局三档：仅右侧栏模式驱动三栏宽度；底部/收起模式不动 splitter
        if getattr(self, '_ai_layout_mode', 'right') != 'right':
            return
        h_splitter = self._find_h_splitter()
        if h_splitter is None:
            return
        if mode == "compact":
            if hasattr(self, 'explorer') and self.explorer.isVisible():
                self.explorer.hide()
            if hasattr(self, 'side_panel') and self.side_panel.isVisible():
                self.side_panel.hide()
            h_splitter.setSizes([0, self.width() - 380, 380])
        elif mode == "collapsed":
            if hasattr(self, 'explorer') and not self.explorer.isVisible():
                self.explorer.show()
            if hasattr(self, 'side_panel') and not self.side_panel.isVisible():
                self.side_panel.show()
            h_splitter.setSizes([150, self.width() - 530, 380])
        else:
            if hasattr(self, 'explorer') and not self.explorer.isVisible():
                self.explorer.show()
            if hasattr(self, 'side_panel') and not self.side_panel.isVisible():
                self.side_panel.show()
            h_splitter.setSizes([200, 600, 1060])

    def _find_h_splitter(self):
        """查找主水平QSplitter。"""
        for child in self.findChildren(QSplitter):
            if child.orientation() == Qt.Horizontal and child.parent() is not None:
                children = child.count()
                if children >= 2:
                    return child
        return None

    def _on_scroll_line_up(self):
        """Alt+Up — 编辑器向上滚动一行"""
        current_widget = self.editor_tabs.currentWidget()
        if isinstance(current_widget, CodeEditor):
            sb = current_widget.verticalScrollBar()
            if sb:
                sb.setValue(sb.value() - 1)

    def _on_scroll_line_down(self):
        """Alt+Down — 编辑器向下滚动一行"""
        current_widget = self.editor_tabs.currentWidget()
        if isinstance(current_widget, CodeEditor):
            sb = current_widget.verticalScrollBar()
            if sb:
                sb.setValue(sb.value() + 1)

    def _open_diff_tab(self, file_path, new_content, diff_lines, reason=""):
        diff_editor = DiffEditor()
        diff_editor.set_diff(file_path, new_content, diff_lines, reason)
        # 连接应用/放弃按钮
        diff_editor.apply_requested.connect(self._on_apply_diff)
        diff_editor.discard_requested.connect(self._on_discard_diff)
        tab_name = f"*{file_path}"
        for i in range(self.editor_tabs.count()):
            if self.editor_tabs.tabText(i) == tab_name:
                self.editor_tabs.removeTab(i)
                break
        idx = self.editor_tabs.addTab(diff_editor, tab_name)
        self.editor_tabs.setCurrentIndex(idx)
        self.breadcrumb_label.setText(f"  {self.engine.project_path} > {rel_path} (diff)")
        self.bottom_panel.log_output(f"[Diff] {file_path} — 变更已高亮显示", SUCCESS)

    def _on_apply_diff(self, file_path, new_content):
        """应用 diff 修改到文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            self.bottom_panel.log_output(f"[Diff] 已应用修改: {file_path}", SUCCESS)
            # 如果文件已在编辑器中打开，刷新内容
            for i in range(self.editor_tabs.count()):
                widget = self.editor_tabs.widget(i)
                if isinstance(widget, CodeEditor) and widget.file_path == file_path:
                    widget.set_code(new_content, file_path)
                    widget.mark_saved()
                    break
            # 关闭 diff tab
            tab_name = f"*{file_path}"
            for i in range(self.editor_tabs.count()):
                if self.editor_tabs.tabText(i) == tab_name:
                    self.editor_tabs.removeTab(i)
                    break
        except Exception as e:
            self.bottom_panel.log_output(f"[Diff] 应用修改失败: {e}", ERROR)

    def _on_discard_diff(self, file_path):
        """放弃 diff 修改"""
        tab_name = f"*{file_path}"
        for i in range(self.editor_tabs.count()):
            if self.editor_tabs.tabText(i) == tab_name:
                self.editor_tabs.removeTab(i)
                break
        self.bottom_panel.log_output(f"[Diff] 已放弃修改: {file_path}", WARNING)

    # ================================================================
    # 多会话管理
    # ================================================================
    def _create_named_session(self):
        """创建命名会话"""
        name, ok = QInputDialog.getText(
            self, "新建会话", "会话名称:",
            text=f"任务 {len(self._sessions) + 1}"
        )
        if not ok or not name.strip():
            return
        self.bottom_panel.log_output(f"[会话] 创建新会话: {name}", INFO)
        self.serve_bridge.create_session()

    def _add_session_tab(self, session_id, name):
        """添加会话 Tab"""
        self._sessions[session_id] = {"name": name, "history": []}
        self._active_session_id = session_id
        self.session_tabs.addTab(QWidget(), f"|| {name}")
        self.session_tabs.setCurrentIndex(self.session_tabs.count() - 1)
        self._update_status_bar()

    def _on_session_tab_changed(self, index):
        """切换会话 Tab"""
        if index < 0:
            return
        # 通过 tab 索引找到 session_id
        keys = list(self._sessions.keys())
        if index < len(keys):
            session_id = keys[index]
            if session_id != self._active_session_id:
                self._switch_to_session(session_id)

    def _switch_to_session(self, session_id):
        """切换到指定会话 — 保存当前会话历史，恢复目标会话历史"""
        if session_id not in self._sessions:
            return
        
        # 保存当前会话的历史（面板内容）
        old_sid = self._active_session_id
        if old_sid and old_sid in self._sessions:
            current_html = self.mimo_panel.get_output_html()
            if current_html:
                self._sessions[old_sid]["history"] = [current_html]
        
        # 切换到新会话
        self._active_session_id = session_id
        self.serve_bridge.switch_session(session_id)
        name = self._sessions[session_id]["name"]
        
        # 恢复目标会话的历史（如果有）
        history = self._sessions[session_id].get("history", [])
        if history:
            self.mimo_panel.clear_output()
            for html in history:
                self.mimo_panel.append_html(html)
        
        self.bottom_panel.log_output(f"[会话] 切换到: {name} ({session_id[:12]}...)", INFO)
        self._update_status_bar()

    def _close_session_tab(self, index):
        """关闭会话 Tab"""
        keys = list(self._sessions.keys())
        if index >= len(keys):
            return
        session_id = keys[index]
        name = self._sessions[session_id]["name"]
        del self._sessions[session_id]
        self.session_tabs.removeTab(index)
        if self._active_session_id == session_id:
            if self._sessions:
                self._switch_to_session(list(self._sessions.keys())[0])
            else:
                self._active_session_id = None
        self.bottom_panel.log_output(f"[会话] 关闭会话: {name}", INFO)
        self._update_status_bar()

    def _on_session_created_for_multi(self, session_id):
        """Serve Bridge 创建会话后的回调"""
        self._active_session_id = session_id
        name = f"任务 {len(self._sessions) + 1}"
        self._add_session_tab(session_id, name)

    def _close_editor_tab(self, idx):
        name = self.editor_tabs.tabText(idx)
        if name != "LEMONCODE":
            self.editor_tabs.removeTab(idx)
            self.breadcrumb_label.setText("LEMONCODE")

    # ------------------------------------------------------------------
    # ★ v4.7.x: 编辑器 Tab 自定义菜单 + 双击重命名
    # ------------------------------------------------------------------
    def _on_editor_tab_double_clicked(self, idx):
        """★ v4.7.x: 双击编辑器 tab → 弹 QInputDialog 让用户重命名（仅在欢迎 tab 不响应）"""
        from PyQt5.QtWidgets import QInputDialog
        if idx < 0 or idx >= self.editor_tabs.count():
            return
        old = self.editor_tabs.tabText(idx).rstrip(" *")
        if old == "LEMONCODE":
            return  # 欢迎页不允许重命名
        new, ok = QInputDialog.getText(
            self, "重命名文件 Tab",
            "新标签名（≤64 字）：",
            text=old,
        )
        if not ok or not new.strip():
            return
        new_name = new.strip()[:64]
        # 检查 CodeEditor 实例的 is_dirty 状态，保留 * 标记
        widget = self.editor_tabs.widget(idx)
        if widget is not None and hasattr(widget, "is_dirty") and widget.is_dirty:
            new_name = "*" + new_name
        self.editor_tabs.setTabText(idx, new_name)

    def _on_editor_tab_context_menu(self, idx, global_pos):
        """★ v4.7.x: 右键编辑器 tab → 菜单：关闭 / 关闭其他 / 关闭右侧 / 重命名"""
        if idx < 0 or idx >= self.editor_tabs.count():
            return
        menu = QMenu(self)
        act_rename = QAction("✎ 重命名", menu)
        act_rename.triggered.connect(lambda: self._on_editor_tab_double_clicked(idx))
        menu.addAction(act_rename)
        menu.addSeparator()
        act_close = QAction("✕ 关闭", menu)
        act_close.triggered.connect(lambda: self.editor_tabs.tabCloseRequested.emit(idx))
        menu.addAction(act_close)
        act_close_others = QAction("关闭其他文件", menu)
        def _close_others():
            for i in range(self.editor_tabs.count() - 1, -1, -1):
                if i != idx and self.editor_tabs.tabText(i) != "LEMONCODE":
                    self.editor_tabs.tabCloseRequested.emit(i)
        act_close_others.triggered.connect(_close_others)
        menu.addAction(act_close_others)
        if idx < self.editor_tabs.count() - 1:
            act_close_right = QAction("关闭右侧文件", menu)
            def _close_right():
                for i in range(self.editor_tabs.count() - 1, idx, -1):
                    if self.editor_tabs.tabText(i) != "LEMONCODE":
                        self.editor_tabs.tabCloseRequested.emit(i)
            act_close_right.triggered.connect(_close_right)
            menu.addAction(act_close_right)
        menu.exec_(global_pos)

    def _on_files_changed(self, changes):
        for c in changes:
            rel_path = c['path']
            full_path = os.path.join(self.engine.project_path, rel_path)
            if os.path.exists(full_path):
                content = self.engine.read_file(rel_path)
                self._open_editor_tab(rel_path, content)
                self.bottom_panel.log_output(f"[变更] {rel_path} ({c['status']})", INFO)

    def _on_file_content_changed(self, rel_path):
        content = self.engine.read_file(rel_path)
        if content:
            self._open_editor_tab(rel_path, content)

    def _on_engine_event(self, event, data):
        if event == "file_written":
            self.bottom_panel.log_output(f"[文件] 已写入 {data['path']}", SUCCESS)

    def _on_bridge_connected(self, port):
        """虫桥连接成功"""
        self.mimo_panel.set_connected(True, port)
        self.status_label.setText(f"  {self.engine.project_path}  |  虫桥:{port}  |  v0.2.0")

    def _on_bridge_disconnected(self):
        """虫桥断开"""
        self.mimo_panel.set_connected(False)
        self.bottom_panel.log_output("[虫桥] 已断开", WARNING)

    def _on_session_created(self, session_id):
        """会话创建成功 — 清空右侧面板和底部终端"""
        self.bottom_panel.log_output(f"[会话] 新会话已创建: {session_id[:15]}...", INFO)
        self.mimo_panel.clear_output()
        self.bottom_panel.mimo_console.clear_output()
        self.mimo_panel.set_current_session(session_id)

    def _forward_to_thinking_panel(self, session_id: str, data: object) -> None:
        """★ 403T-4 Fix3: 把 EventAdapter 的 stream_delta/done/error 转发到思考面板。

        data 类型：stream_delta→str chunk, done→str final_content,
        error→tuple(code, msg)。思考面板用 add_step 展示。
        """
        if not (hasattr(self, 'thinking_panel') and self.thinking_panel):
            return
        try:
            if isinstance(data, tuple) and len(data) == 2:
                # error 分支：(code, msg)
                code, msg = data
                self.thinking_panel.add_step(
                    "tool_result", f"[error] {code}: {msg}", {}, 0.0
                )
                self.thinking_panel.update_step_status(
                    f"[error] {code}: {msg}", "error"
                )
            elif isinstance(data, str) and data:
                # stream_delta chunk 或 done 完成文本
                self.thinking_panel.add_step(
                    "summarizing", data[:120] + ("…" if len(data) > 120 else ""),
                    {}, 0.0
                )
        except Exception as _e_fwd:
            pass

    def _on_bridge_error(self, error_msg):
        """虫桥错误"""
        self.bottom_panel.log_output(f"[虫桥错误] {error_msg}", ERROR)
        self.mimo_panel.set_agent_state('error')
        self.mimo_panel.on_output(f"<span style='color:{Lemon.ACCENT_RED};'>{error_msg}</span>")

    def _on_force_summary(self, sid: str, content: str, status: str):
        """处理 Agent Force Summary 事件 — 显示分析报告（核心修复）"""
        print(f"[前端调试] 收到 FORCE_SUMMARY: sid={sid}, status={status}, len={len(content)}")
        if content and content.strip():
            self._force_summary_shown[sid] = True
            self.mimo_panel.on_output(content)
            self.bottom_panel.log_output(
                f"[Agent] 分析报告已生成 ({len(content)} 字符)", SUCCESS)

    def _on_agent_done(self, sid: str, content: str):
        """处理 Agent 完成事件（含空内容兜底）"""
        print(f"[前端调试] 收到 DONE 消息: sid={sid}, content_len={len(content) if content else 0}")
        # 如果 force_summary 已经显示过报告，跳过重复显示
        if self._force_summary_shown.get(sid, False):
            print("[前端调试] force_summary 已显示报告，跳过 DONE 重复显示")
            self._force_summary_shown.pop(sid, None)
            return
        if not content or not content.strip():
            print("[前端调试] 内容为空，使用 fallback")
            fallback = self._generate_fallback_display(sid)
            self.mimo_panel.on_output(fallback)
            self.bottom_panel.log_output(
                "[Agent] 生成内容为空，已显示工具调用记录", WARNING)
            return
        print(f"[前端调试] 显示内容: {len(content)} 字符")
        self.mimo_panel.on_output(content)

    def _generate_fallback_display(self, sid: str) -> str:
        """生成兜底显示内容"""
        try:
            from bridge.agent_loop import AgentLoop
            loop = AgentLoop.get_instance()
            if loop and hasattr(loop, '_tool_call_records'):
                records = loop._tool_call_records
                results = loop._tool_result_records
                skill_counts = {}
                for r in records:
                    if isinstance(r, dict):
                        sn = r.get('skill_name', 'unknown')
                    else:
                        sn = str(r)
                    skill_counts[sn] = skill_counts.get(sn, 0) + 1
                report = "【Agent 执行报告】\n"
                report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                report += f"📊 统计: 共 {len(records)} 次工具调用\n"
                report += f"🔧 使用的工具: {', '.join(skill_counts.keys())}\n\n"
                report += "📋 工具调用详情:\n"
                for i, (record, result) in enumerate(zip(records[:10], results[:10])):
                    if isinstance(record, dict):
                        skill = record.get('skill_name', '?')
                    else:
                        skill = str(record)
                    result_text = (result or '(无输出)')[:100]
                    report += f"  {i+1}. [{skill}] {result_text}\n"
                if len(records) > 10:
                    report += f"  ... 还有 {len(records) - 10} 次调用\n"
                report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                report += "💡 建议: 请查看以上工具调用结果"
                return report
        except Exception as e:
            self.bottom_panel.log_output(f"[Agent] 兜底报告生成失败: {e}", ERROR)
        return "【Agent 完成】工具调用已执行，但生成的总结为空。请查看上方工具调用记录。"

    def _on_tool_card(self, card_data: dict):
        try:
            call_id = card_data.get("callId", "")
            status = card_data.get("data", {}).get("status", "running")
            tool_name = card_data.get("data", {}).get("toolName", "unknown")
            args = card_data.get("data", {}).get("args", {})
            description = card_data.get("data", {}).get("description", "")
            duration_ms = card_data.get("data", {}).get("durationMs", 0)
            if not hasattr(self, '_tool_cards'):
                self._tool_cards = {}
            chat_flow = getattr(self.bottom_panel.mimo_console, '_chat_flow', None)
            if chat_flow is not None:
                chat_flow.add_tool_card(call_id, tool_name, status, args, description, duration_ms)
            else:
                from ui.tool_card_widget import ToolCardWidget
                if call_id in self._tool_cards:
                    self._tool_cards[call_id].update_status(status, description, duration_ms)
                elif status == "running":
                    widget = ToolCardWidget(call_id, tool_name, status, args)
                    self._tool_cards[call_id] = widget
                    self.bottom_panel.mimo_console._layout.addWidget(widget)
                if status in ("completed", "failed") and call_id in self._tool_cards:
                    QTimer.singleShot(8000, lambda cid=call_id: self._remove_tool_card(cid))
        except Exception:
            pass

    def _remove_tool_card(self, call_id: str):
        if hasattr(self, '_tool_cards') and call_id in self._tool_cards:
            widget = self._tool_cards.pop(call_id)
            widget.setParent(None)
            widget.deleteLater()

    def _on_thinking_step_to_chat(self, step_type: str, description: str, details: dict, duration_ms: float):
        try:
            chat_flow = getattr(self.bottom_panel.mimo_console, '_chat_flow', None)
            if chat_flow is not None:
                chat_flow.add_thinking_step(step_type, description, details, duration_ms)
            # ★ v5.0 B-2: LSP 诊断闭环 — 检测 is_diagnostic 标记弹出卡片
            if details and details.get("is_diagnostic"):
                errors = details.get("errors", [])
                file_path = details.get("file_path", "")
                if errors and hasattr(self, 'whitebox_panel') and self.whitebox_panel:
                    from ui.whitebox.diagnostic_card import DiagnosticCard
                    card = DiagnosticCard(file_path, errors, self.whitebox_panel)
                    card.fix_requested.connect(self._on_diagnostic_fix_requested)
                    card.dismissed.connect(lambda: card.setParent(None))
                    self.whitebox_panel._layout.addWidget(card)
        except Exception:
            pass

    def _on_diagnostic_fix_requested(self, file_path: str, fix_index: int):
        try:
            if hasattr(self, 'bottom_panel') and self.bottom_panel:
                self.bottom_panel.log_output(
                    f"[诊断] 应用修复: {file_path} 修复#{fix_index}", SUCCESS)
        except Exception:
            pass
    # ================================================================
    
    def _on_serve_connected(self):
        """Serve 连接建立"""
        self.mimo_panel.set_connected(True, str(self.serve_bridge.port))
        self.mimo_panel.set_agent_state('connected')
        self.status_label.setText(f"  {self.engine.project_path}  |  Serve 已连接 :{self.serve_bridge.port}  |  v0.2.0")
        self.bottom_panel.log_output(f"[Serve] Lemon Serve 已连接 (:{self.serve_bridge.port})", SUCCESS)
        if hasattr(self, 'bottom_conn'):
            self.bottom_conn.setText("● connected")
            self.bottom_conn.setStyleSheet(f"color: {Lemon.ACCENT_GREEN}; font-size: 11px;")
    
    def _on_serve_disconnected(self):
        """Serve 连接断开"""
        self.mimo_panel.set_connected(False)
        self.mimo_panel.set_agent_state('disconnected')
        self.bottom_panel.log_output("[Serve] Lemon Serve 已断开", WARNING)
        if hasattr(self, 'bottom_conn'):
            self.bottom_conn.setText("● disconnected")
            self.bottom_conn.setStyleSheet(f"color: {Lemon.ACCENT_RED}; font-size: 11px;")
    
    def _on_task_started(self):
        import time
        self._task_start_time = time.time()
        if hasattr(self.bottom_panel, 'thinking_panel') and hasattr(self.bottom_panel.thinking_panel, 'clear_steps'):
            self.bottom_panel.thinking_panel.clear_steps()
        # ★ v3.88: 简笔画风格 - 用细边框方框 + 旋转符号替代 emoji ⏱
        self.bottom_panel.mimo_console.append_html(
            f'<div style="color:{Lemon.ACCENT_ORANGE};margin:4px 0 4px 2px;">'
            f'<span style="display:inline-block;width:14px;height:14px;border:1.5px solid {Lemon.ACCENT_ORANGE};'
            f'border-radius:3px;text-align:center;line-height:10px;font-size:10px;'
            f'color:{Lemon.ACCENT_ORANGE};font-weight:700;margin-right:6px;vertical-align:middle;">◷</span>'
            f'<span style="vertical-align:middle;">任务开始...</span>'
            f'</div>'
        )
        self.mimo_panel.on_task_started()
    
    def _on_task_finished(self, ok, summary):
        """任务完成 — 计算耗时并显示到两个面板"""
        import time
        elapsed = ""
        if self._task_start_time:
            secs = time.time() - self._task_start_time
            if secs < 60:
                elapsed = f"{secs:.1f}秒"
            else:
                elapsed = f"{int(secs//60)}分{int(secs%60)}秒"
            self._task_start_time = None
        
        if elapsed:
            color = Lemon.ACCENT_GREEN if ok else Lemon.ERROR
            status_text = "完成" if ok else "失败"
            # ★ v3.88: 简笔画风格 - 用细边框方框 + 勾选符号替代 emoji ✓
            self.bottom_panel.mimo_console.append_html(
                f'<div style="color:{color};margin:4px 0 4px 2px;">'
                f'<span style="display:inline-block;width:14px;height:14px;border:1.5px solid {color};'
                f'border-radius:3px;text-align:center;line-height:10px;font-size:10px;'
                f'color:{color};font-weight:700;margin-right:6px;vertical-align:middle;">✓</span>'
                f'<span style="vertical-align:middle;">{status_text} — 耗时 {elapsed}</span>'
                f'</div>'
            )
        self.mimo_panel.on_task_finished(0 if ok else -1)

        # ★ v5.0 Whitebox: Run 完成/失败
        if hasattr(self, 'whitebox_panel') and self.whitebox_panel:
            run = self.whitebox_panel.registry.get_current_run()
            if run and run.status.value == "running":
                if ok:
                    self.whitebox_panel.registry.complete_run(run.run_id, summary or "")
                else:
                    self.whitebox_panel.registry.fail_run(run.run_id, summary or "任务失败")

        # ★ v5.0 B-3: Artifact 路径联动高亮 Git 面板
        if hasattr(self, 'git_status_panel') and self.git_status_panel:
            if hasattr(self, 'whitebox_panel') and self.whitebox_panel:
                artifacts = self.whitebox_panel.registry.get_all_artifacts()
                paths = [a.file_path for a in artifacts if a.file_path]
                self.git_status_panel.highlight_artifact_paths(paths)
            self.git_status_panel.refresh()

    def _on_git_revert(self, file_path: str):
        if hasattr(self, 'bottom_panel') and self.bottom_panel:
            self.bottom_panel.log_output(f"[Git] 已丢弃修改: {file_path}", WARNING)
    
    def _on_serve_log(self, line: str):
        """★ B3: Serve 进程日志 → output_view（[进程] 紫色前缀）"""
        self._append_process_output(line)

    # ================================================================
    # ACP 桥事件处理
    # ================================================================
    
    def _on_acp_connected(self):
        """ACP 连接建立"""
        self.mimo_panel.set_connected(True, "ACP")
        self.status_label.setText(f"  {self.engine.project_path}  |  ACP 已连接  |  v0.2.0")
        self.bottom_panel.log_output("[ACP] ACP 通信已建立", SUCCESS)

        # ★ v3.65: 若处于夺舍模式，切换 UI 到假终端 + 显示模式
        if getattr(self, '_hijack_agent_name', None) and not getattr(self, '_hijack_mode_active', False):
            try:
                agent_name = self._hijack_agent_name
                agent_brand = getattr(self, '_hijack_agent_brand', agent_name)
                self._hijack_mode_active = True

                # 取消连接超时定时器
                if hasattr(self, '_hijack_connect_timeout'):
                    try:
                        self._hijack_connect_timeout.stop()
                    except Exception:
                        pass

                # ★ v4.1.12: 读取 HOST 分模式配置（拦截/二次处理开关）
                _sm = None
                _intercept = True
                _reprocess = True
                try:
                    from core.settings_manager import get_settings_manager as _gsm
                    _sm = _gsm()
                    _intercept = _sm.host_intercept_output
                    _reprocess = _sm.host_reprocess_output
                except Exception:
                    pass

                _mode_log = []
                # 拦截开关 → 假终端（默认开）
                if _intercept:
                    self.bottom_panel.set_fake_terminal_mode(True, agent_name=agent_brand)
                    _mode_log.append("底栏→假终端")
                else:
                    _mode_log.append("底栏→原生终端")

                # 二次处理开关 → 右栏显示模式（默认开）
                if _reprocess:
                    self.mimo_panel.set_display_only_mode(True, agent_name=agent_brand)
                    _mode_log.append("右栏→显示模式")
                else:
                    _mode_log.append("右栏→原生")

                # 更新状态灯（紫色已连接）
                self.title_bar.engine_selector.update_engine_status("acp", True)

                # ★ v4.1.11: 更新 Host 功能栏连接状态
                try:
                    self.title_bar.set_host_connected(True)
                except Exception:
                    pass

                self.bottom_panel.log_output(
                    f"[夺舍] ✅ 已连接 {agent_brand}，" + "，".join(_mode_log),
                    SUCCESS
                )
            except Exception as e:
                print(f"[夺舍] UI 切换失败: {e}")

    def _on_acp_disconnected(self):
        """ACP 连接断开"""
        self.mimo_panel.set_connected(False)
        self.bottom_panel.log_output("[ACP] ACP 通信已断开", WARNING)

        # ★ v3.65: 若处于夺舍模式，恢复 UI
        if getattr(self, '_hijack_mode_active', False):
            try:
                self._hijack_mode_active = False
                self.bottom_panel.set_fake_terminal_mode(False)
                self.mimo_panel.set_display_only_mode(False)
                self.title_bar.engine_selector.update_engine_status("acp", False)
                # ★ v4.1.11: 更新 Host 功能栏
                try:
                    self.title_bar.set_host_connected(False)
                except Exception:
                    pass
                self.bottom_panel.log_output(
                    "[夺舍] 连接断开，已恢复正常 Agent 模式",
                    WARNING
                )
            except Exception as e:
                print(f"[夺舍] 恢复 UI 失败: {e}")
    
    def _on_acp_event(self, event_type: str, data: dict):
        """ACP 通用事件日志"""
        # 只记录关键事件
        if event_type in (ACPEvent.SESSION_INFO, ACPEvent.USAGE, ACPEvent.PLAN_UPDATE):
            pass  # 这些事件太频繁，不记录日志
        elif event_type == ACPEvent.CONNECTED:
            sid = data.get('session_id', '')
            if sid:
                self.bottom_panel.log_output(f"[ACP] 会话: {sid[:16]}...", INFO)
    
    def _on_config_options(self, session_id: str, options_list: list):
        """Lemon Code 发送配置选项 — 显示在右侧面板"""
        self.bottom_panel.log_output(f"[ACP] 收到配置选项 ({len(options_list)} 项)", INFO)
        self.mimo_panel.show_config_options(session_id, options_list)
    
    def _on_permission_request(self, session_id: str, tool_info: dict, options_list: list):
        """Lemon Code 请求权限 — 显示权限弹窗"""
        tool_name = tool_info.get('title', tool_info.get('kind', 'unknown'))
        self.bottom_panel.log_output(f"[ACP] 权限请求: {tool_name}", WARNING)
        self.mimo_panel.show_permission(session_id, tool_info, options_list)
    
    def _on_mode_changed(self, mode_id: str):
        """Lemon Code 模式变更 — 同步到 UI"""
        self.bottom_panel.log_output(f"[ACP] 模式切换: {mode_id}", INFO)
        self.mimo_panel.set_mode(mode_id)
    
    def _on_config_applied(self, action: str, session_id: str, changes: list):
        """用户在面板中选择配置选项后 — 发送回 Lemon Code"""
        self.bottom_panel.log_output(f"[ACP] 应用配置变更: {len(changes)} 项", INFO)
        for change in changes:
            config_id = change.get('id', '')
            value = change.get('value', '')
            if config_id:
                self.bottom_panel.log_output(f"[ACP]   → {config_id} = {value}", INFO)
                self.acp_bridge.set_config_option(config_id, value)
    
    def _on_permission_responded(self, session_id: str, choice_id: str):
        """用户在面板中响应权限请求 — 发送回 Lemon Code"""
        self.bottom_panel.log_output("[ACP] 权限响应: " + choice_id, INFO)
        self.acp_bridge.respond_permission(session_id, choice_id)
    
    def _on_bridge_permission_request(self, session_id: str, skill_name: str, args: dict):
        """v3.0 C-2: Bridge权限请求 → UI弹窗"""
        self.bottom_panel.log_output("[Bridge权限] " + skill_name + " 请求权限", WARNING)
        tool_info = {"title": skill_name, "kind": "skill", "args": args}
        options_list = [
            {"id": "allow_once", "title": "允许一次", "description": "仅本次允许"},
            {"id": "allow_always", "title": "始终允许", "description": "记录为可信操作"},
            {"id": "deny", "title": "拒绝", "description": "拒绝本次操作"},
        ]
        self.mimo_panel.show_permission(session_id, tool_info, options_list)

    def _on_bridge_plan_proposed(self, session_id: str, plan_data: dict):
        """v3.0 C-3: Bridge GOAP计划 → 确认弹窗"""
        steps = plan_data.get("steps", [])
        goal = plan_data.get("goal", "")
        desc = "目标: " + goal + " | 步骤: " + str(len(steps))
        self.bottom_panel.log_output("[Bridge计划] " + desc, INFO)
        tool_info = {"title": "执行计划", "kind": "plan", "goal": goal, "steps": steps}
        options_list = [
            {"id": "confirm", "title": "确认执行", "description": desc},
            {"id": "reject", "title": "拒绝计划", "description": "取消本次计划"},
        ]
        self.mimo_panel.show_permission(session_id, tool_info, options_list)

    _trajectory_events = []

    def _collect_trajectory_events(self, event_type: str, data: dict) -> list:
        """v3.0 D-1: 收集轨迹事件供TrajectoryPanel显示。"""
        import time as _time
        self._trajectory_events.append({
            "event_type": event_type,
            "timestamp": _time.time(),
            "data": data,
        })
        if len(self._trajectory_events) > 500:
            self._trajectory_events = self._trajectory_events[-500:]
        return list(self._trajectory_events)
    
    def _on_mode_switch_requested(self, mode_id: str):
        """用户在面板中请求切换模式 — 发送到 Lemon Code"""
        self.bottom_panel.log_output(f"[ACP] 请求切换模式: {mode_id}", INFO)
        self.acp_bridge.set_mode(mode_id)
        self._sync_mode_state("current", mode_id)

    # ================================================================
    # 模型/会话管理处理
    # ================================================================
    
    def _on_model_switch(self, model_id: str):
        """右侧面板请求切换模型"""
        self.bottom_panel.log_output(f"[模型] 切换模型: {model_id}", INFO)
        self.serve_bridge.switch_model(model_id)
        self.bottom_panel.mimo_console.model_combo.setText(model_id)
        self.mimo_panel.set_current_model(model_id)
    
    def _on_session_switch(self, session_id: str):
        """右侧面板请求切换会话 — 清空信号来源面板而非 self.mimo_panel"""
        self.bottom_panel.log_output(f"[会话] 切换会话: {session_id[:16]}...", INFO)
        try:
            source_panel = self.sender()
            if isinstance(source_panel, MIMOCodePanel):
                source_panel.clear_output()
            else:
                self.mimo_panel.clear_output()
            self.bottom_panel.mimo_console.clear_output()
            self.serve_bridge.switch_session(session_id)
            target = source_panel if isinstance(source_panel, MIMOCodePanel) else self.mimo_panel
            target.set_current_session(session_id)
            self.bottom_panel.mimo_console.set_session_info(session_id, self._get_active_model_id())
        except RuntimeError:
            pass
        except Exception as e:
            self.bottom_panel.log_output(f"[会话] 切换异常: {e}", WARNING)

    def _on_file_changed(self, file_path: str, change_type: str, diff_info: dict):
        """文件变更通知 — 在右侧栏显示变更摘要卡片"""
        import os
        file_name = os.path.basename(file_path)
        type_names = {"created": "新建", "modified": "修改", "deleted": "删除", "renamed": "重命名"}
        type_name = type_names.get(change_type, change_type)
        type_colors = {"created": Lemon.STATUS_ONLINE, "modified": Lemon.STATUS_RUNNING, "deleted": Lemon.ERROR, "renamed": Lemon.SYNTAX_VARIABLE}
        color = type_colors.get(change_type, Lemon.STATUS_RUNNING)

        # 构建变更摘要卡片 HTML
        html = f'''
        <div style="
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 8px;
            padding: 12px 16px;
            margin: 8px 0;
        ">
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
                <span style="
                    display: inline-block;
                    width: 6px;
                    height: 6px;
                    border-radius: 50%;
                    background: {color};
                "></span>
                <span style="color: {color}; font-size: 14px; font-weight: 600;">文件{type_name}</span>
                <span style="color: {Lemon.DIVIDER}; font-size: 15px; font-weight: 500;">{file_name}</span>
            </div>
            <div style="color: #888; font-size: 13px; padding-left: 16px;">
                [] {file_path}
            </div>
        </div>
        '''
        self.mimo_panel.on_output(html)
    
    def _on_fetch_models_for_panel(self):
        """右侧面板请求获取模型列表"""
        models = self.serve_bridge.list_models()
        if models:
            self.mimo_panel.show_models(models)
            self.bottom_panel.log_output(f"[模型] 获取到 {len(models)} 个模型", INFO)
        else:
            self.bottom_panel.log_output("[模型] 无法获取模型列表", WARNING)
    
    def _on_fetch_sessions_for_panel(self):
        """右侧面板请求获取会话列表"""
        sessions = self.serve_bridge.list_sessions()
        if sessions:
            self.mimo_panel.show_sessions(sessions)
            self.bottom_panel.log_output(f"[会话] 获取到 {len(sessions)} 个会话", INFO)
        else:
            self.bottom_panel.log_output("[会话] 无法获取会话列表", WARNING)
    
    def _on_new_session_from_panel(self):
        """右侧面板请求新建会话 —— ★ v4.7.2: 新建 CodeBuddy 风格会话 Tab"""
        print("[会话] _on_new_session_from_panel 被调用 (来自 HTML 按钮)", flush=True)
        self.bottom_panel.log_output("[会话] 创建新会话...", INFO)
        self._on_workspace_new_session()

    def _on_trust_mode_changed(self, enabled: bool):
        """信任模式切换"""
        status = "开启" if enabled else "关闭"
        self.bottom_panel.log_output(f"[信任模式] {status}", INFO)
        self.serve_bridge.set_trust_mode(enabled)
    
    def _on_service_mode_switch(self, mode_id: str):
        """右侧面板请求切换服务模式 — 通过 QStackedWidget 切换页面"""
        # 模式隔离检查：切换前检查目标模式状态
        try:
            from core.mode_status import STANDARD_MODE, HYBRID_MODE, ModeStatus
            mode_info_map = {'original': STANDARD_MODE, 'hybrid': HYBRID_MODE}
            target_mode = mode_info_map.get(mode_id)
            if target_mode:
                if target_mode.status == ModeStatus.FROZEN:
                    self.bottom_panel.log_output(
                        f"[模式警告] {target_mode.name} 已锁定，切换可能影响稳定性", WARNING)
                elif target_mode.status == ModeStatus.BROKEN:
                    reply = QMessageBox.warning(self, "模式状态警告",
                        f"{target_mode.name} 状态为已损坏。\n已知问题:\n" +
                        "\n".join(f"  - {iss}" for iss in target_mode.known_issues[:3]) +
                        "\n\n确定要切换吗？",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if reply == QMessageBox.No:
                        self.bottom_panel.log_output(f"[模式] 取消切换到 {target_mode.name}", WARNING)
                        return
                elif target_mode.status == ModeStatus.DEGRADED:
                    self.bottom_panel.log_output(
                        f"[模式提示] {target_mode.name} 功能退化，部分功能可能不可用", WARNING)
        except ImportError:
            pass

        mode_names = {
            'original': 'NINGMENG 经典模式',
            'terminal': '纯终端模式',
            'demo': '演示模式',
            'hybrid': '混合 AI 模式',
        }
        name = mode_names.get(mode_id, mode_id)
        self.bottom_panel.log_output(f"[模式] 切换服务模式: {name}", INFO)
        self.mimo_panel.set_service_mode(mode_id)
        
        # ★ 核心：使用 QStackedWidget 切换模式页面
        # ★ v4.7.2: 单AI多窗口 / 多AI协同已移除（改为顶部会话 Tab 栏）
        mode_map = {
            'original': 0,  # 页面0: NINGMENG经典模式（文件树+编辑器+多会话AI面板）
            'hybrid': 1,    # 页面1: 混合模式
        }
        
        if mode_id in mode_map:
            idx = mode_map[mode_id]
            if hasattr(self, 'mode_stack'):
                self.mode_stack.setCurrentIndex(idx)
                self._current_mode = mode_id

                # ★ 混合模式不再「屏蔽 chrome」 — 标题栏 / 状态栏 / 菜单栏 / 底部
                # 面板全部保留可见，避免用户被锁死在全屏 WebEngine 内出不来。
                # WebEngine 自然只占 QStackedWidget 当前页的位置，所有原生窗口控件
                # （最小化 / 最大化 / 关闭）+ 标题栏 + 状态栏 均正常显示。
                is_hybrid = (mode_id == 'hybrid')

                # ★ 兜底：HTML 内「返回标准模式」按钮事件仍走 mode_switch_requested，
                # 主窗口 chrome 永远可见，给用户永远一条出路。
                if hasattr(self, 'title_bar'):
                    self.title_bar.setVisible(True)
                if hasattr(self, 'bottom_panel'):
                    self.bottom_panel.setVisible(not is_hybrid)  # 底部日志面板仅混合模式隐藏
                if hasattr(self, 'statusBar'):
                    sb = self.statusBar()
                    if sb:
                        sb.setVisible(True)
                if hasattr(self, 'menuBar'):
                    mb = self.menuBar()
                    if mb:
                        mb.setVisible(True)
                
                # ★ 关键修复：从混合模式切换离开时，清理资源防止影响其他模式
                if not is_hybrid and hasattr(self, 'hybrid_mode_panel') and self.hybrid_mode_panel:
                    try:
                        self.hybrid_mode_panel.cleanup()
                        self.bottom_panel.log_output("[模式] 混合模式资源已清理", SUCCESS)
                    except Exception as e:
                        self.bottom_panel.log_output(f"[模式] 清理混合模式资源时出错: {e}", WARNING)
                
                self.bottom_panel.log_output(
                    f"[模式] 已切换到页面 {idx} ({name})", 
                    SUCCESS
                )
            else:
                self.bottom_panel.log_output(f"[模式] 模式栈不存在，无法切换", ERROR)
        else:
            self.bottom_panel.log_output(f"[模式] {name} — 特殊模式处理", INFO)
            if mode_id == 'terminal':
                # ★ v4.7.2: 隐藏右侧多会话工作区（含 Tab 栏）
                self.session_workspace.hide()
                self.multi_session_panel.hide()
            elif mode_id == 'demo':
                self.session_workspace.show()
                self.multi_session_panel.hide()
                self.bottom_panel.setVisible(False)
            else:
                self.session_workspace.show()
                self.multi_session_panel.hide()
                self.bottom_panel.setVisible(True)

    # ================================================================
    # LSP 集成（v0.6.0 新增 / v0.7.0 崩溃恢复增强）
    # ================================================================
    def _on_lsp_server_ready(self, language_id: str):
        """LSP服务器就绪"""
        self.bottom_panel.log_output(f"[LSP] {language_id} 语言服务器已就绪", SUCCESS)

    def _on_lsp_server_crashed(self, language_id: str, crash_count: int):
        """LSP服务器崩溃 — v0.7.0 新增"""
        self.bottom_panel.log_output(
            f"[LSP] ! {language_id} 服务器崩溃（第 {crash_count} 次），准备自动重启...",
            WARNING,
        )

    def _on_lsp_server_restarted(self, language_id: str, restart_count: int):
        """LSP服务器重启成功 — v0.7.0 新增"""
        self.bottom_panel.log_output(
            f"[LSP] v {language_id} 服务器已自动重启（第 {restart_count} 次重启）",
            SUCCESS,
        )

    def _on_lsp_server_failed(self, language_id: str, reason: str):
        """LSP服务器达到崩溃阈值 — v0.7.0 新增"""
        self.bottom_panel.log_output(
            f"[LSP] x {language_id} 服务器放弃重启: {reason}",
            ERROR,
        )

    def _on_lsp_health_updated(self, health: dict):
        """LSP健康状态更新 — v0.7.0 新增（问题面板可消费）"""
        # 只在有异常时输出日志，避免刷屏
        for lang, info in health.items():
            if not info.get("alive") and info.get("crash_count", 0) > 0:
                self.bottom_panel.log_output(
                    f"[LSP] {lang} 健康异常: alive={info['alive']} crashes={info['crash_count']}",
                    WARNING,
                )
    
    def _on_lsp_completion(self, file_path: str, items):
        """LSP补全结果"""
        if items:
            self.completion_popup.set_items(items)
            # 在编辑器位置显示弹窗
            editor = self._get_current_editor()
            if editor:
                cursor_pos = editor.editor.cursorRect().bottomLeft()
                global_pos = editor.editor.mapToGlobal(cursor_pos)
                self.completion_popup.show_at_cursor(global_pos)
    
    def _on_lsp_definition(self, file_path: str, locations):
        """LSP跳转定义结果"""
        if locations:
            loc = locations[0]
            # ★ v0.7.0: 使用公共接口 uri_to_path，不直接访问 _clients
            target_path = self.lsp_manager.uri_to_path(loc.uri)
            self._open_file_at_line(target_path, loc.range.start.line + 1)
            self.bottom_panel.log_output(f"[LSP] 跳转到定义: {os.path.basename(target_path)}:{loc.range.start.line + 1}", INFO)

    def _on_lsp_references(self, file_path: str, locations):
        """LSP查找引用结果"""
        if locations:
            # 在全局搜索面板显示引用列表
            refs = []
            for loc in locations:
                # ★ v0.7.0: 使用公共接口 uri_to_path，不直接访问 _clients
                path = self.lsp_manager.uri_to_path(loc.uri)
                refs.append(f"{path}:{loc.range.start.line + 1}")
            self.bottom_panel.log_output(f"[LSP] 找到 {len(locations)} 个引用:", INFO)
            for ref in refs[:10]:  # 只显示前10个
                self.bottom_panel.log_output(f"  {ref}", TEXT_SECONDARY)
    
    def _on_lsp_diagnostics(self, file_path: str, diagnostics):
        """LSP诊断结果 — v0.7.0 增强问题面板更新"""
        if diagnostics:
            errors = [d for d in diagnostics if d.severity == 1]
            warnings = [d for d in diagnostics if d.severity == 2]
            infos = [d for d in diagnostics if d.severity >= 3]
            if errors or warnings:
                self.bottom_panel.log_output(
                    f"[LSP] {os.path.basename(file_path)}: {len(errors)} 错误, {len(warnings)} 警告",
                    ERROR if errors else WARNING
                )
            # ★ v0.7.0: 更新编辑器诊断标注（波浪线）
            editor = self._get_current_editor()
            if editor and hasattr(editor, 'update_diagnostics'):
                editor.update_diagnostics(file_path, diagnostics)
            # ★ v0.7.0: 更新底部问题面板
            if hasattr(self, 'bottom_panel') and self.bottom_panel:
                self.bottom_panel.update_diagnostics(file_path, diagnostics)
    
    def _on_completion_selected(self, insert_text: str):
        """补全项被选择"""
        editor = self._get_current_editor()
        if editor:
            cursor = editor.editor.textCursor()
            # 删除已输入的部分，插入完整文本
            cursor.insertText(insert_text)
    
    def _on_completion_cancelled(self):
        """补全被取消"""
        pass
    
    def _request_completion(self):
        """请求代码补全"""
        editor = self._get_current_editor()
        if editor and editor.file_path:
            cursor = editor.editor.textCursor()
            line = cursor.blockNumber()
            character = cursor.positionInBlock()
            self.lsp_manager.request_completion(editor.file_path, line, character)
    
    def _request_definition(self):
        """请求跳转定义（F12）"""
        editor = self._get_current_editor()
        if editor and editor.file_path:
            cursor = editor.editor.textCursor()
            line = cursor.blockNumber()
            character = cursor.positionInBlock()
            self.lsp_manager.request_definition(editor.file_path, line, character)
    
    def _request_references(self):
        """请求查找引用（Shift+F12）"""
        editor = self._get_current_editor()
        if editor and editor.file_path:
            cursor = editor.editor.textCursor()
            line = cursor.blockNumber()
            character = cursor.positionInBlock()
            self.lsp_manager.request_references(editor.file_path, line, character)

    # ============================================================
    # v0.8.0 Skill 进度桥接 — 浏览器自动化 + Jupyter Notebook
    # ============================================================

    def _setup_skill_progress_bridge(self):
        """★ v0.8.0: 注册 Skill 进度回调 — 实时显示操作步骤到右侧面板"""
        try:
            from core.skills import browser_automation, jupyter_notebook

            def _on_progress(event: dict):
                # 在主线程中安全更新 UI
                step = event.get("step", "")
                status = event.get("status", "")
                detail = event.get("detail", "")
                icon = {"running": "...", "success": "v", "failed": "x"}.get(status, "•")
                color_map = {"running": INFO, "success": SUCCESS, "failed": ERROR}
                color = color_map.get(status, TEXT_TERTIARY)
                msg = f"[Skill] {icon} {step}"
                if detail:
                    msg += f" — {detail[:120]}"
                # 通过 QueuedConnection 在主线程更新
                QTimer.singleShot(0, lambda: self.bottom_panel.log_output(msg, color))

            browser_automation.set_progress_callback(_on_progress)
            jupyter_notebook.set_progress_callback(_on_progress)
            self.bottom_panel.log_output(
                "[Skill] v0.8.0 进度桥接已建立（browser_automation + jupyter_notebook）",
                INFO,
            )
        except Exception as e:
            self.bottom_panel.log_output(f"[Skill] 进度桥接建立失败: {e}", WARNING)

    def _render_jupyter_inline(self, inline_html: str, title: str = "Jupyter 执行结果"):
        """★ v0.8.0: 在对话中内联展示 Jupyter Notebook 执行结果

        Args:
            inline_html: 已构造好的 HTML 字符串（包含 cell 输出 + base64 图片）
            title: 卡片标题
        """
        try:
            # 优先尝试 mimo_console 的 append_html（如果存在）
            if hasattr(self.bottom_panel, 'mimo_console') and self.bottom_panel.mimo_console:
                console = self.bottom_panel.mimo_console
                if hasattr(console, 'append_html'):
                    card_html = (
                        f'<div style="margin:8px 0;padding:10px;'
                        f'border:1px solid {BORDER_SUBTLE};border-radius:6px;'
                        f'background:{BG_SECONDARY};">'
                        f'<div style="color:{XIAOMI_ORANGE};font-weight:600;'
                        f'font-size:13px;margin-bottom:6px;">📓 {title}</div>'
                        f'{inline_html}'
                        f'</div>'
                    )
                    console.append_html(card_html)
                    return

            # B2: 问题面板已合并入 output_view — 回退写入输出
            self.bottom_panel.log_output(f"[Jupyter] 内联渲染回退: {inline_html[:200]}", WARNING)
        except Exception as e:
            self.bottom_panel.log_output(f"[Jupyter] 内联渲染失败: {e}", WARNING)

    def _render_skill_result_smart(self, skill_name: str, result) -> bool:
        """★ v0.8.0: 智能渲染 Skill 结果 — 根据技能类型选择最佳展示方式

        Returns:
            True 表示已特殊渲染（不再输出纯文本）；False 表示使用默认渲染
        """
        try:
            if not result or not getattr(result, "success", False):
                return False

            data = getattr(result, "data", None) or {}

            # Jupyter execute / get_output — 内联 HTML 展示
            if skill_name == "jupyter_notebook":
                inline_html = data.get("inline_html")
                if inline_html:
                    self._render_jupyter_inline(inline_html, "Jupyter 执行结果")
                    return True

            # 浏览器截图 — 内联展示截图（mimo_console append_html）
            if skill_name == "browser_automation":
                screenshot_path = data.get("path")
                if screenshot_path and os.path.exists(screenshot_path):
                    self._render_screenshot_inline(screenshot_path)
                    return True

            return False
        except Exception:
            return False

    def _render_screenshot_inline(self, image_path: str):
        """★ v0.8.0: 在对话中内联展示浏览器截图"""
        try:
            import base64 as _b64
            with open(image_path, "rb") as f:
                b64 = _b64.b64encode(f.read()).decode("ascii")
            if hasattr(self.bottom_panel, 'mimo_console') and self.bottom_panel.mimo_console:
                console = self.bottom_panel.mimo_console
                if hasattr(console, 'append_html'):
                    html = (
                        f'<div style="margin:8px 0;padding:10px;'
                        f'border:1px solid {BORDER_SUBTLE};border-radius:6px;'
                        f'background:{BG_SECONDARY};">'
                        f'<div style="color:{XIAOMI_ORANGE};font-weight:600;'
                        f'font-size:13px;margin-bottom:6px;">📸 浏览器截图</div>'
                        f'<img src="data:image/png;base64,{b64}" '
                        f'style="max-width:100%;border-radius:4px;" />'
                        f'<div style="color:{TEXT_TERTIARY};font-size:11px;'
                        f'margin-top:4px;">{os.path.basename(image_path)}</div>'
                        f'</div>'
                    )
                    console.append_html(html)
                    return
            self.bottom_panel.log_output(
                f"[Browser] 截图已保存: {image_path}", SUCCESS,
            )
        except Exception as e:
            self.bottom_panel.log_output(f"[Browser] 截图展示失败: {e}", WARNING)

    # ============================================================
    # v0.9.0 Git 危险操作确认对话框 + 任务依赖图渲染
    # ============================================================

    def _confirm_git_dangerous_action(self, action: str, sub_action: str = "", **kwargs) -> bool:
        """★ v0.9.0: Git 危险操作前弹出确认对话框

        危险操作包括：push / merge / branch delete / stash pop

        Args:
            action: Git 操作类型
            sub_action: 子操作（如 branch 的 delete）

        Returns:
            True 表示用户确认，False 表示取消
        """
        try:
            from core.skills.git_skill import is_dangerous_action
            if not is_dangerous_action(action, sub_action):
                return True  # 非危险操作，直接放行
        except Exception:
            return True  # 检测失败，放行

        # 构造确认信息
        action_desc = {
            "push": ("推送代码到远程仓库", f"将本地分支推送到 {kwargs.get('remote', 'origin')}/{kwargs.get('branch_name', '当前分支')}" + ("（强制）" if kwargs.get('force') else "")),
            "merge": ("合并分支", f"将分支 {kwargs.get('branch_name', '?')} 合并到当前分支" + ("（禁用快进）" if kwargs.get('no_ff') else "")),
            "branch:delete": ("删除分支", f"删除分支 {kwargs.get('branch_name', '?')}"),
            "stash:pop": ("恢复并删除 Stash", f"从 stash 恢复并删除 {kwargs.get('stash_id', '最新 stash')}"),
        }.get(
            f"{action}:{sub_action}" if sub_action else action,
            (f"执行 {action}", "此操作可能不可逆，请确认"),
        )

        title, detail = action_desc
        reply = QMessageBox.warning(
            self,
            f"! Git 危险操作确认",
            f"<b>{title}</b><br><br>{detail}<br><br>确认执行此操作吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.bottom_panel.log_output(f"[Git] v 用户确认: {title}", SUCCESS)
            return True
        self.bottom_panel.log_output(f"[Git] x 用户取消: {title}", WARNING)
        return False

    def _render_task_dependency_graph(self, html: str, title: str = "任务依赖图"):
        """★ v0.9.0: 在对话中内联展示任务依赖关系图

        Args:
            html: TaskManager.render_html_graph() 返回的 HTML
            title: 卡片标题
        """
        try:
            if hasattr(self.bottom_panel, 'mimo_console') and self.bottom_panel.mimo_console:
                console = self.bottom_panel.mimo_console
                if hasattr(console, 'append_html'):
                    card_html = (
                        f'<div style="margin:8px 0;padding:10px;'
                        f'border:1px solid {BORDER_SUBTLE};border-radius:6px;'
                        f'background:{BG_SECONDARY};">'
                        f'<div style="color:{XIAOMI_ORANGE};font-weight:600;'
                        f'font-size:13px;margin-bottom:6px;">|| {title}</div>'
                        f'{html}'
                        f'</div>'
                    )
                    console.append_html(card_html)
                    return
            # B2: 问题面板已合并入 output_view — 回退写入输出
            self.bottom_panel.log_output(f"[TaskManager] 依赖图回落文本: {html[:200]}", WARNING)
        except Exception as e:
            self.bottom_panel.log_output(f"[TaskManager] 依赖图渲染失败: {e}", WARNING)

    def _enhance_skill_result_rendering(self, skill_name: str, result) -> bool:
        """★ v0.9.0: 增强 Skill 结果渲染 — 任务依赖图 / Git diff 等特殊渲染

        Returns:
            True 表示已特殊渲染；False 表示使用默认渲染
        """
        try:
            if not result or not getattr(result, "success", False):
                return False

            data = getattr(result, "data", None) or {}

            # task_manager graph 操作 — 内联渲染依赖图
            if skill_name == "task_manager":
                inline_html = data.get("inline_html")
                if inline_html:
                    self._render_task_dependency_graph(inline_html, "任务依赖图")
                    return True

            # miemie_clone_analyze — 渲染MIEMIE分身卡片（★ v1.0.0）
            if skill_name == "miemie_clone_analyze":
                # data 中含完整的 CodeProfile 字段（包括 tags/naming/...）
                # 包装成可渲染的 profile_data
                profile_data = self._build_miemie_profile_data_from_code_profile(data)
                if profile_data:
                    self._render_miemie_profile_card(profile_data)
                    return True

            # git_skill diff — 高亮显示 diff
            if skill_name == "git_skill":
                diff_text = data.get("diff")
                if diff_text:
                    # 简单的 diff 高亮：+ 行绿色，- 行红色
                    lines = diff_text.split("\n")
                    html_lines = []
                    for line in lines[:200]:  # 限制 200 行
                        if line.startswith("+") and not line.startswith("+++"):
                            html_lines.append(f'<div style="color:{Lemon.STATUS_ONLINE};">{self._escape_html(line)}</div>')
                        elif line.startswith("-") and not line.startswith("---"):
                            html_lines.append(f'<div style="color:{Lemon.ERROR};">{self._escape_html(line)}</div>')
                        elif line.startswith("@@"):
                            html_lines.append(f'<div style="color:{Lemon.STATUS_RUNNING};">{self._escape_html(line)}</div>')
                        else:
                            html_lines.append(f'<div style="color:{Lemon.STATUS_OFFLINE};">{self._escape_html(line)}</div>')
                    diff_html = (
                        f'<div style="margin:8px 0;padding:10px;'
                        f'border:1px solid {BORDER_SUBTLE};border-radius:6px;'
                        f'background:{Lemon.DARK_BG_2};font-family:Consolas,monospace;font-size:12px;">'
                        f'<div style="color:{XIAOMI_ORANGE};font-weight:600;margin-bottom:6px;">'
                        f'* Git Diff（{data.get("files_changed", 0)} 个文件）</div>'
                        + "".join(html_lines)
                        + '</div>'
                    )
                    if hasattr(self.bottom_panel, 'mimo_console') and self.bottom_panel.mimo_console:
                        console = self.bottom_panel.mimo_console
                        if hasattr(console, 'append_html'):
                            console.append_html(diff_html)
                            return True
            return False
        except Exception:
            return False

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符"""
        if not text:
            return ""
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    # ================================================================
    # ★ v1.0.0 MIEMIE (MiMi) 代码分身 — 可视化渲染
    # ================================================================

    def _render_miemie_profile_card(self, profile_data: dict):
        """★ v1.0.0: 在对话中内联展示MIEMIE代码分身卡片

        Args:
            profile_data: MiMiProfile.to_dict() 返回的字典
        """
        try:
            import sys as _sys
            import os as _os
            _mimi_dir = _os.path.normpath(_os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                "miemie"
            ))
            if _mimi_dir not in _sys.path:
                _sys.path.insert(0, _mimi_dir)
            from miemie_visualizer import render_profile_card_html
            from miemie_avatar import render_mimi_svg
            # 渲染头像（根据分身的 avatar_expression 字段）
            expression = profile_data.get("avatar_expression", "calm")
            avatar_svg = render_mimi_svg(expression, size=96)
            card_html = render_profile_card_html(profile_data, avatar_svg=avatar_svg)
            if hasattr(self.bottom_panel, 'mimo_console') and self.bottom_panel.mimo_console:
                console = self.bottom_panel.mimo_console
                if hasattr(console, 'append_html'):
                    console.append_html(card_html)
                    return
            # B2: 问题面板已合并入 output_view — 回退写入输出
            self.bottom_panel.log_output(f"[MiMi] 分身卡片回落: {card_html[:200]}", WARNING)
        except Exception as e:
            self.bottom_panel.log_output(f"[MiMi] 分身卡片渲染失败: {e}", WARNING)

    def _render_miemie_analysis_progress(self, step: int, total: int, message: str, status: str = "running"):
        """★ v1.0.0: 渲染MIEMIE分身分析进度条"""
        try:
            import sys as _sys
            import os as _os
            _mimi_dir = _os.path.normpath(_os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                "miemie"
            ))
            if _mimi_dir not in _sys.path:
                _sys.path.insert(0, _mimi_dir)
            from miemie_visualizer import render_progress_html
            progress_html = render_progress_html(step, total, message, status=status)
            if hasattr(self.bottom_panel, 'mimo_console') and self.bottom_panel.mimo_console:
                console = self.bottom_panel.mimo_console
                if hasattr(console, 'append_html'):
                    console.append_html(progress_html)
        except Exception as e:
            self.bottom_panel.log_output(f"[MiMi] 进度渲染失败: {e}", WARNING)

    def _build_miemie_profile_data_from_code_profile(self, code_profile_data: dict) -> dict:
        """★ v1.0.0: 将 CodeProfile 数据包装为可视化卡片所需格式

        CodeProfile 仅含代码风格维度，这里补齐 personality/preferences 等字段，
        让 render_profile_card_html 可以正常渲染。
        """
        if not code_profile_data:
            return {}
        try:
            naming = code_profile_data.get("naming", {})
            indent = code_profile_data.get("indentation", {})
            comments = code_profile_data.get("comments", {})
            fl = code_profile_data.get("function_length", {})
            eh = code_profile_data.get("error_handling", {})
            # 根据代码风格推断 5 维人格（简化版）
            density = comments.get("density", 0)
            short_ratio = fl.get("short_function_ratio", 0)
            long_ratio = fl.get("long_function_ratio", 0)
            eh_style = eh.get("style", "none")
            rational = 0.5
            meticulous = min(0.5 + density * 1.2, 1.0)
            concise = min(0.5 + short_ratio * 0.5, 1.0)
            friendly = 0.5  # 代码风格不直接体现友好
            rigorous = 0.5
            if eh_style == "try-except":
                rigorous = min(rigorous + 0.2, 1.0)
            elif eh_style == "assert":
                rational = min(rational + 0.2, 1.0)
            elif eh_style == "logging":
                meticulous = min(meticulous + 0.1, 1.0)
            if long_ratio > 0.3:
                concise = max(concise - 0.15, 0.0)
            profile_data = {
                "profile_id": "preview",
                "profile_name": code_profile_data.get("source", "").split("/")[-1]
                                or code_profile_data.get("source", "").split("\\")[-1]
                                or "代码分身",
                "created_at": 0,
                "avatar_expression": "calm",
                "personality": {
                    "rational": round(rational, 3),
                    "meticulous": round(meticulous, 3),
                    "concise": round(concise, 3),
                    "friendly": round(friendly, 3),
                    "rigorous": round(rigorous, 3),
                },
                "preferences": {
                    "naming_style": naming.get("dominant", "snake_case")
                                    if "dominant" in naming else "snake_case",
                    "indent_style": indent.get("style", "spaces"),
                    "indent_width": indent.get("width", 4),
                    "comment_density": density,
                    "function_length_preference": (
                        "short" if short_ratio > 0.5
                        else "long" if long_ratio > 0.3
                        else "medium"
                    ),
                    "error_handling_style": eh_style,
                    "code_language_primary": code_profile_data.get("language", "python"),
                },
                "behaviors": {
                    "avg_response_seconds": 0,
                    "emoji_usage_level": "low",
                    "tone": "neutral",
                    "avg_message_length": 0,
                    "communication_tags": [],
                },
                "code_tags": code_profile_data.get("tags", []),
                "social_tags": [],
                "summary": code_profile_data.get("summary", ""),
                "source_files": code_profile_data.get("files_analyzed", 0),
                "source_contacts": 0,
            }
            return profile_data
        except Exception:
            return {}

    def _get_current_editor(self):
        """获取当前活动的编辑器"""
        current_widget = self.editor_tabs.currentWidget()
        if current_widget and isinstance(current_widget, CodeEditor):
            return current_widget
        return None

    # ================================================================
    # 全局快捷键系统
    # ================================================================
    def _setup_shortcuts(self):
        """注册全局快捷键"""
        # Ctrl+F — 聚焦左侧文件搜索
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._on_focus_search)
        # Ctrl+Shift+F — 全局文件内容搜索
        QShortcut(QKeySequence("Ctrl+Shift+F"), self).activated.connect(self._on_global_search)
        # Ctrl+Shift+P — 命令面板
        QShortcut(QKeySequence("Ctrl+Shift+P"), self).activated.connect(self._on_command_palette)
        # Ctrl+R — 历史搜索（底部终端）
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self._on_history_search)
        # Ctrl+L — 清除终端
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(
            lambda: self.bottom_panel.mimo_console.clear_output()
        )
        # Ctrl+` — 切换底部面板可见性
        QShortcut(QKeySequence("Ctrl+`"), self).activated.connect(self._on_toggle_bottom_panel)
        # Escape — 关闭命令面板或清除搜索
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._on_escape)
        # Ctrl+G — 跳转到指定行
        QShortcut(QKeySequence("Ctrl+G"), self).activated.connect(self._on_go_to_line)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._on_save_current_file)
        QShortcut(QKeySequence("Ctrl+W"), self).activated.connect(self._on_close_current_tab)
        # ★ LSP 快捷键（v0.6.0 新增）
        QShortcut(QKeySequence("Ctrl+Space"), self).activated.connect(self._request_completion)  # 补全
        QShortcut(QKeySequence("F12"), self).activated.connect(self._request_definition)  # 跳转定义
        QShortcut(QKeySequence("Shift+F12"), self).activated.connect(self._request_references)  # 查找引用
        # ★ 格式化快捷键（v0.6.0 新增）
        QShortcut(QKeySequence("Alt+Shift+F"), self).activated.connect(self._format_current_file)  # 手动格式化
        # ★ 新增快捷键（v3.46）
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self._on_new_session_shortcut)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self).activated.connect(self._on_new_file_shortcut)
        QShortcut(QKeySequence("Ctrl+Tab"), self).activated.connect(self._on_next_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self).activated.connect(self._on_prev_tab)
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(self._on_toggle_theme)
        QShortcut(QKeySequence("Ctrl+Shift+T"), self).activated.connect(self._on_restore_closed_tab)
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(self._on_open_settings)
        QShortcut(QKeySequence("F11"), self).activated.connect(self._on_toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+Shift+D"), self).activated.connect(self._on_toggle_theme)
        QShortcut(QKeySequence("Alt+Up"), self).activated.connect(self._on_scroll_line_up)
        QShortcut(QKeySequence("Alt+Down"), self).activated.connect(self._on_scroll_line_down)
        # ★ v4.5.1 驱动模式快捷键：一键循环切换 AI 引擎（Ollama → DeepSeek → MIMO）
        QShortcut(QKeySequence("Ctrl+Alt+E"), self).activated.connect(self._on_cycle_engine)

    def _on_focus_search(self):
        """Ctrl+F — 聚焦左侧文件搜索"""
        self.explorer.focus_search()
        self.bottom_panel.log_output("[快捷键] Ctrl+F — 聚焦文件搜索", INFO)

    def _on_global_search(self):
        """Ctrl+Shift+F — 聚焦全局顶栏搜索框（若有），否则退化为全局文件内容搜索"""
        if hasattr(self, 'global_search') and self.global_search is not None:
            self.global_search.setFocus()
            self.global_search.selectAll()
            return
        text, ok = QInputDialog.getText(self, "全局搜索", "在所有文件中搜索文本:")
        if ok and text.strip():
            self._do_global_search(text.strip())

    def _do_global_search(self, query, case_sensitive=False, use_regex=False):
        """执行全局文件内容搜索 — 使用可点击的结果面板

        参数:
            query: 搜索关键字
            case_sensitive: 是否区分大小写
            use_regex: 是否使用正则表达式
        """
        import re as _re
        self.bottom_panel.log_output(f"[全局搜索] 搜索: {query}", INFO)
        # 编译匹配模式
        try:
            if use_regex:
                pattern = _re.compile(query, 0 if case_sensitive else _re.IGNORECASE)
                def _match(line):
                    return pattern.search(line) is not None
            else:
                needle = query if case_sensitive else query.lower()
                def _match(line):
                    return needle in (line if case_sensitive else line.lower())
        except Exception as e:
            self.bottom_panel.log_output(f"[全局搜索] 正则错误: {e}", ERROR)
            return
        results = []
        project_path = self.engine.project_path
        try:
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', 'node_modules', '.git', 'venv', 'env', 'dist', 'build', '__pycache__')]
                for fname in files:
                    if fname.endswith(('.pyc', '.pyo', '.exe', '.dll', '.pyd', '.so', '.o', '.obj')):
                        continue
                    fpath = os.path.join(root, fname)
                    rel_path = os.path.relpath(fpath, project_path)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                            for i, line in enumerate(f, 1):
                                if _match(line):
                                    results.append((rel_path, i, line.strip()[:120]))
                    except Exception:
                        pass
        except Exception as e:
            self.bottom_panel.log_output(f"[全局搜索] 错误: {e}", ERROR)
            return

        if not results:
            self.bottom_panel.log_output(f"[全局搜索] 未找到匹配: {query}", WARNING)
            return

        # 弹窗显示可点击结果
        self._show_search_results_dialog(query, results)
    
    def _show_search_results_dialog(self, query, results):
        """显示搜索结果弹窗（可点击跳转）"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"搜索结果: {query} ({len(results)} 处匹配)")
        dialog.setMinimumSize(800, 500)
        dialog.setStyleSheet(f"""
            QDialog {{
                background: {BG_PRIMARY};
                color: {TEXT_PRIMARY};
                font-family: {FONT_SYSTEM};
            }}
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)
        
        # 搜索/替换栏
        search_bar = QHBoxLayout()
        search_label = QLabel(f"搜索: {query}")
        search_label.setStyleSheet(f"color: {XIAOMI_ORANGE}; font-weight: 600;")
        search_bar.addWidget(search_label)
        
        replace_input = QLineEdit()
        replace_input.setPlaceholderText("替换为...")
        replace_input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_SECONDARY};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_SUBTLE};
                border-radius: {RADIUS_SM};
                padding: 4px 10px;
            }}
        """)
        search_bar.addWidget(replace_input, 1)
        
        replace_btn = QPushButton("全部替换")
        replace_btn.setStyleSheet(button_primary_style())
        replace_btn.clicked.connect(lambda: self._do_global_replace(query, replace_input.text(), results, dialog))
        search_bar.addWidget(replace_btn)
        
        layout.addLayout(search_bar)
        
        # 结果列表
        result_list = QListWidget()
        result_list.setStyleSheet(f"""
            QListWidget {{
                background: {BG_ROOT};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
                font-family: {FONT_MONO};
                font-size: {FONT_SIZE_SM};
            }}
            QListWidget::item {{
                padding: 4px 10px;
                border-bottom: 1px solid {BORDER_SUBTLE};
            }}
            QListWidget::item:hover {{
                background: {BG_SURFACE_HOVER};
            }}
        """)
        
        for rel_path, line_no, line_text in results[:200]:
            item = QListWidgetItem(f"{rel_path}:{line_no}  {line_text}")
            item.setData(Qt.UserRole, (rel_path, line_no))
            result_list.addItem(item)
        
        if len(results) > 200:
            result_list.addItem(f"... 还有 {len(results) - 200} 处匹配未显示")
        
        result_list.itemDoubleClicked.connect(lambda item: self._on_search_result_clicked(item))
        layout.addWidget(result_list, 1)
        
        dialog.exec_()
    
    def _on_search_result_clicked(self, item):
        """点击搜索结果 — 打开文件并跳转到行"""
        data = item.data(Qt.UserRole)
        if not data:
            return
        rel_path, line_no = data
        content = self.engine.read_file(rel_path)
        if content:
            editor = None
            for i in range(self.editor_tabs.count()):
                w = self.editor_tabs.widget(i)
                if isinstance(w, CodeEditor) and w.file_path == rel_path:
                    editor = w
                    self.editor_tabs.setCurrentIndex(i)
                    break
            if not editor:
                editor = CodeEditor()
                editor.set_code(content, file_path=rel_path)
                editor.save_requested.connect(lambda fp, c: self._save_file(fp, c))
                editor.content_changed.connect(lambda: self._on_editor_content_changed(editor))
                # ★ v0.7.0: 连接 LSP 信号
                self._connect_editor_lsp(editor)
                self.editor_tabs.addTab(editor, rel_path)
                self.editor_tabs.setCurrentIndex(self.editor_tabs.count() - 1)
            editor.go_to_line(line_no)
    
    def _do_global_replace(self, query, replacement, results, dialog):
        """执行全局替换"""
        if not replacement:
            return
        count = 0
        for rel_path, _, _ in results:
            content = self.engine.read_file(rel_path)
            if content and query in content:
                new_content = content.replace(query, replacement)
                self.engine.write_file(rel_path, new_content)
                count += 1
        self.bottom_panel.log_output(f"[全局替换] 已将 '{query}' → '{replacement}' 应用于 {count} 个文件", SUCCESS)
        dialog.accept()

    def _on_command_palette(self):
        """Ctrl+Shift+P — 打开命令面板"""
        palette = CommandPalette(self)
        palette.command_triggered.connect(self._on_palette_command)
        palette.exec_()

    def _on_palette_command(self, cmd_id):
        """执行命令面板中的命令"""
        self.bottom_panel.log_output(f"[命令面板] 执行: {cmd_id}", INFO)
        if cmd_id == "explorer.focus_search":
            self.explorer.focus_search()
        elif cmd_id == "explorer.collapse_all":
            self.explorer.tree.collapseAll()
        elif cmd_id == "explorer.recent_files":
            self._show_recent_files()
        elif cmd_id == "explorer.go_to_line":
            self._on_go_to_line()
        elif cmd_id == "terminal.clear":
            self.bottom_panel.mimo_console.clear_output()
        elif cmd_id == "terminal.command_history":
            self._show_command_history()
        elif cmd_id == "terminal.new_session":
            self.serve_bridge.create_session()
        elif cmd_id == "terminal.switch_model":
            models = self.serve_bridge.list_models()
            if models:
                model_ids = [m.get('id', '?') for m in models]
                model_id, ok = QInputDialog.getItem(self, "切换模型", "选择模型:", model_ids, 0, False)
                if ok and model_id:
                    self._on_model_switch(model_id)
        elif cmd_id == "terminal.show_usage":
            self.bottom_panel.mimo_console.command_sent.emit("/usage")
        elif cmd_id == "terminal.show_info":
            self.bottom_panel.mimo_console.command_sent.emit("/info")
        elif cmd_id == "terminal.cancel_task":
            self.serve_bridge.cancel_current_task()
        elif cmd_id.startswith("mode.switch_"):
            mode_id = cmd_id.replace("mode.switch_", "")
            self._on_service_mode_switch(mode_id)
        elif cmd_id == "mode.build":
            self._on_agent_mode_switch("build")
        elif cmd_id == "mode.plan":
            self._on_agent_mode_switch("plan")
        elif cmd_id == "mode.compose":
            self._on_agent_mode_switch("compose")
        elif cmd_id == "view.search_global":
            self._on_global_search()
        elif cmd_id == "view.command_palette":
            self._on_command_palette()
        elif cmd_id == "git.status":
            self._show_git_status()
        elif cmd_id == "git.commit":
            self._git_commit()
        elif cmd_id == "git.push":
            self._git_push()
        elif cmd_id == "git.pull":
            self._git_pull()
        elif cmd_id == "git.log":
            self._show_git_log()
        elif cmd_id == "code.review":
            self._code_review_current_file()
        elif cmd_id == "code.review_selected":
            self._code_review_current_file()
        elif cmd_id == "cluster.start_full":
            self._start_cluster(5)
        elif cmd_id == "cluster.start_minimal":
            self._start_cluster(2)
        elif cmd_id == "cluster.stop":
            self._stop_cluster()
        elif cmd_id == "cluster.toggle_grid":
            self._toggle_instance_grid()
        elif cmd_id == "cluster.status":
            self._show_cluster_status()
        elif cmd_id == "help.show_shortcuts":
            self._show_shortcuts_help()
        elif cmd_id == "report.distillation":
            self._show_distillation_report()
        elif cmd_id == "report.innovation":
            self._show_innovation_report()
        elif cmd_id == "report.health":
            self._show_health_dashboard()
        elif cmd_id == "config.import":
            self._import_config_file()
        elif cmd_id == "vote.start":
            self._start_agent_vote()
        elif cmd_id == "vote.history":
            self._show_vote_history()
        elif cmd_id == "skills.browse":
            self._show_skills_browser()
        elif cmd_id == "tools.engine_dispatch":
            self._show_engine_dispatch_diagnosis()
        elif cmd_id == "plugin.market":
            self._show_plugin_market()
        elif cmd_id == "miemie.analyze":
            self._miemie_analyze_project()
        elif cmd_id == "miemie.profile":
            self._miemie_show_profile()
        elif cmd_id == "web.browser":
            self._open_web_browser()
        elif cmd_id == "config.role":
            self._open_role_config_dialog()
        elif cmd_id == "role.coder":
            self._set_agent_role("coder")
        elif cmd_id == "role.analyst":
            self._set_agent_role("analyst")
        elif cmd_id == "role.writer":
            self._set_agent_role("writer")
        elif cmd_id == "role.assistant":
            self._set_agent_role("assistant")

    def _on_history_search(self):
        """Ctrl+R — 历史命令搜索与复用"""
        if not self._command_history:
            self.bottom_panel.log_output("[历史搜索] 暂无历史命令", WARNING)
            return

        text, ok = QInputDialog.getText(self, "历史搜索", "输入关键词搜索历史命令:")
        if not ok or not text.strip():
            return

        keyword = text.strip().lower()
        matches = [(i, cmd) for i, cmd in enumerate(self._command_history)
                   if keyword in cmd.lower()]

        if not matches:
            self.bottom_panel.log_output(f"[历史搜索] 未找到匹配 '{text.strip()}' 的命令", WARNING)
            return

        self.bottom_panel.log_output(
            f"[历史搜索] 找到 {len(matches)} 条匹配 '{text.strip()}' 的命令:", INFO)
        for idx, (i, cmd) in enumerate(matches[-20:], 1):
            self.bottom_panel.log_output(f"  {idx}. {cmd[:100]}{'...' if len(cmd) > 100 else ''}")

        # 如果只有一条匹配，直接填入输入框
        if len(matches) == 1:
            cmd = matches[0][1]
            self.bottom_panel.log_output(f"[历史搜索] 自动填入: {cmd[:80]}", SUCCESS)
            self._fill_input(cmd)
        elif len(matches) <= 5:
            # 少量匹配时提供选择
            items = [f"{cmd[:80]}" for _, cmd in matches]
            item, ok = QInputDialog.getItem(
                self, "历史搜索", f"选择要复用的命令 (匹配 {len(matches)} 条):",
                items, 0, False
            )
            if ok and item:
                # 找到完整命令
                selected_cmd = matches[items.index(item)][1] if item in items else item
                self.bottom_panel.log_output(f"[历史搜索] 填入: {item[:80]}", SUCCESS)
                self._fill_input(selected_cmd)

    def _fill_input(self, text: str):
        """将文本填入当前活跃的输入框"""
        # 优先填入右侧面板输入框（通过 JS）
        if hasattr(self, 'mimo_panel') and self.mimo_panel:
            try:
                escaped = text.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')
                self.mimo_panel._safe_run_js(
                    f"var el=document.getElementById('inputField');if(el){{el.value='{escaped}';el.focus();}}"
                )
                return
            except Exception:
                pass
        # 回退到底部控制台
        try:
            field = self.bottom_panel.mimo_console.input_field
            field.setText(text)
            field.setFocus()
        except Exception:
            pass

    def _on_toggle_bottom_panel(self):
        """Ctrl+` — 切换底部面板可见性"""
        visible = self.bottom_panel.isVisible()
        self.bottom_panel.setVisible(not visible)
        state = "隐藏" if visible else "显示"
        self.bottom_panel.log_output(f"[快捷键] Ctrl+` — 底部面板已{state}", INFO)

    def _on_escape(self):
        """Escape — 清除搜索或关闭面板/退出混合模式"""
        # 如果在混合模式，按ESC返回原始模式
        if hasattr(self, '_current_mode') and self._current_mode == 'hybrid':
            self._on_service_mode_switch('original')
            return
        
        # 如果搜索框有内容，清除
        if self.explorer.search_bar.get_text():
            self.explorer.search_bar.search_input.clear()

    def _on_go_to_line(self):
        """Ctrl+G — 跳转到指定行"""
        current_widget = self.editor_tabs.currentWidget()
        if not current_widget:
            self.bottom_panel.log_output("[跳转] 没有打开的编辑器标签", WARNING)
            return
        # 获取当前编辑器行数
        if hasattr(current_widget, 'editor'):
            line_count = current_widget.editor.document().blockCount()
        else:
            self.bottom_panel.log_output("[跳转] 当前标签不支持跳转行号", WARNING)
            return
        line_str, ok = QInputDialog.getText(
            self, "跳转到行", f"输入行号 (1-{line_count}):"
        )
        if ok and line_str.strip():
            try:
                line_num = int(line_str.strip())
                if 1 <= line_num <= line_count:
                    cursor = current_widget.editor.textCursor()
                    block = current_widget.editor.document().findBlockByNumber(line_num - 1)
                    cursor.setPosition(block.position())
                    current_widget.editor.setTextCursor(cursor)
                    current_widget.editor.setFocus()
                    self.bottom_panel.log_output(f"[跳转] 已跳转到第 {line_num} 行", SUCCESS)
                else:
                    self.bottom_panel.log_output(f"[跳转] 行号超出范围 (1-{line_count})", WARNING)
            except ValueError:
                self.bottom_panel.log_output(f"[跳转] 无效行号: {line_str}", WARNING)

    def _add_recent_file(self, rel_path):
        """添加文件到最近文件列表"""
        if rel_path in self._recent_files:
            self._recent_files.remove(rel_path)
        self._recent_files.insert(0, rel_path)
        if len(self._recent_files) > 20:
            self._recent_files = self._recent_files[:20]
        # 更新状态栏
        self._update_status_bar()

    def _add_command_history(self, command):
        """添加命令到历史记录"""
        if command and (not self._command_history or self._command_history[-1] != command):
            self._command_history.append(command)
        if len(self._command_history) > 100:
            self._command_history = self._command_history[-100:]

    def _update_status_bar(self):
        """更新状态栏信息"""
        project_path = self.engine.project_path
        file_count = len(self.engine.files)
        recent = f" | 最近: {os.path.basename(self._recent_files[0])}" if self._recent_files else ""
        # Git 分支信息
        git_info = ""
        if self.git_manager.is_git_repo:
            branch = self.git_manager.branch
            summary = self.git_manager.get_summary()
            git_info = f" |  {branch}"
            if summary['total_changes'] > 0:
                parts = []
                if summary['modified']: parts.append(f"M:{summary['modified']}")
                if summary['added']: parts.append(f"A:{summary['added']}")
                if summary['deleted']: parts.append(f"D:{summary['deleted']}")
                if summary['untracked']: parts.append(f"?:{summary['untracked']}")
                git_info += f" [{', '.join(parts)}]"
        session_count = len(self._sessions)
        ses_info = f" | 会话: {session_count}" if session_count > 0 else ""
        # AI 路由状态
        ai_info = ""
        available = self.ai_router.get_available_providers()
        if available:
            ai_info = f" | AI: {','.join(available)}"

        # ★ v4.7: 角色显示
        role_info = ""
        if hasattr(self, 'mimo_panel') and self.mimo_panel:
            if hasattr(self.mimo_panel, 'get_role_display_name'):
                role_name = self.mimo_panel.get_role_display_name()
                role_id = self.mimo_panel.get_current_role()
                role_info = f" | [角色:{role_name}]"

        # ★ P6-4: 引擎/模型实时跟踪
        engine_info = self._get_engine_status_text()

        self.status_label.setText(
            f"  {project_path}  |  {file_count} 个文件{git_info}{ses_info}{ai_info}{role_info}{recent}{engine_info}  |  v0.4.0"
        )

    def _get_engine_status_text(self) -> str:
        """获取当前引擎/模型状态文本
        
        ★ P6 修复: 使用 active_engine 而非 active_model 获取正确的引擎状态
        """
        try:
            # 从 engine_mode_selector 获取当前模式
            if hasattr(self, 'title_bar') and hasattr(self.title_bar, 'engine_selector'):
                mode = self.title_bar.engine_selector._current
            else:
                mode = "auto"

            # 获取当前活动引擎信息
            engine_display = ""
            if hasattr(self, 'mimo_panel') and self.mimo_panel:
                if hasattr(self.mimo_panel, '_engine_manager') and self.mimo_panel._engine_manager:
                    status = self.mimo_panel._engine_manager.get_status()
                    active_engine = status.get("active_engine", "")
                    # 引擎ID → 显示名称映射
                    engine_names = {
                        "mimocode": "MIMO Code",
                        "ollama": "Qwen2.5",
                        "deepseek": "DeepSeek-V3",
                    }
                    if active_engine:
                        engine_display = engine_names.get(active_engine, active_engine)

            # 映射模式到显示名称
            mode_names = {
                "mimo": "MIMO",
                "ollama": "Ollama",
                "deepseek": "DeepSeek",
                "auto": "Auto",
            }
            mode_display = mode_names.get(mode, mode.upper())

            # 构建显示文本
            if engine_display:
                return f" | 引擎: {mode_display} ({engine_display})"
            return f" | 引擎: {mode_display}"
        except Exception:
            return ""

    # ================================================================
    # Agent 模式切换（真实切换 Lemon Code 模式）
    # ================================================================
    def _on_agent_mode_switch(self, mode_id: str):
        """切换 Agent 模式 — 通过 Serve Bridge 发送到 Lemon Code"""
        # 模式状态检查
        try:
            from core.mode_status import generate_mode_status_report
            # Agent 模式切换时记录状态报告（不影响切换，仅日志）
            self.bottom_panel.log_output(f"[Agent] 模式切换请求: {mode_id}", INFO)
        except ImportError:
            pass

        mode_config = {
            'build': {
                'name': 'Build Mode',
                'description': '代码生成与构建优化',
                'system_prompt': '你是一个专业的代码构建助手。专注于：1) 生成高质量、可维护的代码；2) 优化代码结构和性能；3) 确保代码符合最佳实践和规范；4) 提供完整的测试用例。',
                'state': 'working',
                'color': Lemon.ACCENT_GREEN,
            },
            'plan': {
                'name': 'Plan Mode',
                'description': '任务规划与分解',
                'system_prompt': '你是一个专业的任务规划助手。专注于：1) 将复杂任务分解为可执行的子任务；2) 制定清晰的执行计划和时间表；3) 识别潜在风险和依赖关系；4) 提供优先级建议。',
                'state': 'thinking',
                'color': Lemon.ACCENT_ORANGE,
            },
            'compose': {
                'name': 'Compose Mode',
                'description': '创意写作与文档生成',
                'system_prompt': '你是一个专业的创意写作和文档助手。专注于：1) 生成高质量的文档和技术文章；2) 撰写清晰的需求文档和API文档；3) 提供专业的文案润色；4) 保持文档风格一致。',
                'state': 'idle',
                'color': '#00d4ff',
            },
        }
        
        config = mode_config.get(mode_id, mode_config['build'])
        self.bottom_panel.log_output(f"[Agent] 切换 Agent 模式: {config['name']} ({config['description']})", INFO)

        # 通过 Serve Bridge 真实切换 Lemon Code 模式
        if self.serve_bridge.is_connected:
            self.serve_bridge.set_mode(mode_id)
            self.bottom_panel.log_output(f"[Agent] 已发送模式切换请求到 Lemon Code", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[Agent] Serve Bridge 未连接，无法切换模式", WARNING)

        # 更新右侧面板的模式显示
        self.mimo_panel.set_mode(mode_id)

        # 更新机器人状态
        self.mimo_panel.set_agent_state(config['state'])

        # 更新状态栏显示
        if hasattr(self, '_agent_mode_label'):
            self._agent_mode_label.setText(f"[AI] {config['name']}")
            self._agent_mode_label.setStyleSheet(f"color: {config['color']}; font-size: 12px;")
        
        # 显示模式切换提示
        self.bottom_panel.mimo_console.append_html(
            f'<div style="color:{config["color"]};margin:8px 0;padding:8px;border-left:3px solid {config["color"]};background:{BG_SURFACE};border-radius:0 {RADIUS_SM} {RADIUS_SM} 0;">'
            f'<b>[AI] {config["name"]}</b> — {config["description"]}<br>'
            f'<span style="color:{TEXT_TERTIARY};font-size:12px;">系统提示词已更新，AI将专注于当前模式的任务。</span>'
            f'</div>'
        )

    def _show_shortcuts_help(self):
        """显示快捷键帮助"""
        help_text = f"""
        <div style="line-height:2.0;">
        <b style="color:{MIMO_ORANGE};font-size:14px;">: 快捷键列表</b><br><br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+F</span> — 聚焦文件搜索<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+Shift+F</span> — 全局文件内容搜索<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+Shift+P</span> — 命令面板<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+R</span> — 历史命令搜索<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+L</span> — 清除终端输出<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+G</span> — 跳转到指定行<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+`</span> — 切换底部面板<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+N</span> — 新建会话<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+Shift+N</span> — 新建文件<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+T</span> — 切换主题<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+Tab</span> — 下一个标签页<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+Shift+Tab</span> — 上一个标签页<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+S</span> — 保存当前文件<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+W</span> — 关闭当前标签页<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+Shift+T</span> — 恢复关闭的标签页<br>
        <span style="color:{TEXT_TERTIARY};">Ctrl+,</span> — 打开设置<br>
        <span style="color:{TEXT_TERTIARY};">F11</span> — 全屏切换<br>
        <span style="color:{TEXT_TERTIARY};">Alt+Shift+F</span> — 格式化代码<br>
        <span style="color:{TEXT_TERTIARY};">Esc</span> — 清除搜索<br>
        </div>
        """
        self.bottom_panel.mimo_console.append_html(help_text)
        self.bottom_panel.log_output("[快捷键] 显示快捷键帮助", INFO)

    def _show_distillation_report(self):
        """显示蒸馏对标报告"""
        try:
            from core.distillation_analysis import generate_distillation_report
            report = generate_distillation_report()
            # 保存到 data/ 目录
            report_path = os.path.join(self.engine.project_path, "data", "distillation_report.md")
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report)
            # 在终端显示报告
            self.bottom_panel.mimo_console.append_html(
                f'<pre style="color:{TEXT_PRIMARY};font-size:11px;white-space:pre-wrap;">{report[:3000]}</pre>'
            )
            self.bottom_panel.log_output(f"[报告] 蒸馏报告已保存到 {report_path}", MIMO_ORANGE)
        except Exception as e:
            self.bottom_panel.log_output(f"[报告] 蒸馏报告生成失败: {e}", ERROR)

    def _show_innovation_report(self):
        """显示创新清单报告"""
        try:
            from core.innovation_catalog import generate_innovation_report
            report = generate_innovation_report()
            self.bottom_panel.mimo_console.append_html(
                f'<pre style="color:{TEXT_PRIMARY};font-size:11px;white-space:pre-wrap;">{report[:3000]}</pre>'
            )
            self.bottom_panel.log_output("[报告] 创新清单已显示", MIMO_ORANGE)
        except Exception as e:
            self.bottom_panel.log_output(f"[报告] 创新清单生成失败: {e}", ERROR)

    def _show_health_dashboard(self):
        """显示项目健康仪表盘"""
        try:
            from shared.health_dashboard import HealthDashboard
            dashboard = HealthDashboard()
            report = dashboard.generate_report()
            # 人性化设计：根据状态用颜色标识
            summary = dashboard.get_summary()
            status = summary.get("overall_status", "unknown")
            color_map = {"healthy": Lemon.ACCENT_GREEN, "degraded": Lemon.ACCENT_ORANGE, "unhealthy": Lemon.ACCENT_RED}
            status_color = color_map.get(status, TEXT_TERTIARY)
            status_icon = {"healthy": "v", "degraded": "!", "unhealthy": "x"}.get(status, "?")

            html = f"""
            <div style="padding:10px;">
            <h3 style="color:{MIMO_ORANGE};">+ 项目健康仪表盘</h3>
            <p style="color:{status_color};font-size:14px;">{status_icon} 总体状态: {status.upper()}</p>
            <pre style="color:{TEXT_PRIMARY};font-size:11px;white-space:pre-wrap;">{report[:3000]}</pre>
            </div>
            """
            self.bottom_panel.mimo_console.append_html(html)
            self.bottom_panel.log_output(f"[健康] 仪表盘已显示 (状态: {status})", status_color)
        except Exception as e:
            self.bottom_panel.log_output(f"[健康] 仪表盘生成失败: {e}", ERROR)

    def _import_config_file(self):
        """导入配置文件 — 文件选择器 + ConfigImporter 集成"""
        from PyQt5.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
        from core.config_import import ConfigImporter, ConflictStrategy, ConfigFormat

        # 人性化设计：文件选择对话框
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择配置文件", "",
            "配置文件 (*.json *.yaml *.yml *.toml *.ini);;所有文件 (*)"
        )
        if not file_path:
            return

        # 人性化设计：冲突策略选择对话框
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox
        conflict_dlg = QDialog(self)
        conflict_dlg.setWindowTitle("导入配置 — 冲突处理策略")
        conflict_dlg.setMinimumWidth(400)
        clayout = QVBoxLayout(conflict_dlg)
        clayout.addWidget(QLabel(f"文件: {os.path.basename(file_path)}"))
        clayout.addWidget(QLabel("\n选择冲突处理策略:"))
        strategy_combo = QComboBox()
        strategy_combo.addItems([
            "合并 (新配置优先)",
            "覆盖 (完全替换)",
            "跳过 (保留现有配置)",
            "报错 (遇冲突停止)",
        ])
        clayout.addWidget(strategy_combo)

        target_combo = QComboBox()
        target_combo.addItems(["settings", "workspaces", "version", "recovery"])
        clayout.addWidget(QLabel("导入目标:"))
        clayout.addWidget(target_combo)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(conflict_dlg.accept)
        btns.rejected.connect(conflict_dlg.reject)
        clayout.addWidget(btns)

        if conflict_dlg.exec_() != QDialog.Accepted:
            return

        strategy_map = {
            0: ConflictStrategy.MERGE, 1: ConflictStrategy.OVERWRITE,
            2: ConflictStrategy.SKIP, 3: ConflictStrategy.ERROR
        }
        strategy = strategy_map[strategy_combo.currentIndex()]
        target = target_combo.currentText()

        # 人性化设计：进度条
        progress = QProgressDialog("正在导入配置...", "取消", 0, 3, self)
        progress.setWindowTitle("配置导入")
        progress.setFixedWidth(350)
        progress.setValue(1)
        progress.setLabelText("读取文件...")

        try:
            importer = ConfigImporter()
            progress.setValue(2)
            progress.setLabelText("导入并验证...")

            result = importer.import_config(
                file_path=file_path,
                target=target,
                conflict_strategy=strategy,
                format_hint=ConfigFormat.AUTO,
                validate=True
            )

            progress.setValue(3)
            progress.close()

            # 人性化设计：导入结果摘要
            if result.ok:
                summary = f"v 导入成功\n\n"
                summary += f"文件: {os.path.basename(file_path)}\n"
                summary += f"目标: {target}\n"
                summary += f"导入项: {len(result.imported_keys)} 个\n"
                if result.conflict_keys:
                    summary += f"冲突项: {len(result.conflict_keys)} 个 ({', '.join(result.conflict_keys[:5])})\n"
                if result.skipped_keys:
                    summary += f"跳过项: {len(result.skipped_keys)} 个\n"
                if result.warnings:
                    summary += f"警告: {'; '.join(result.warnings[:3])}\n"
                summary += f"\n备份路径: {result.backup_path or '无'}"

                # 回滚选项
                if result.backup_path:
                    reply = QMessageBox.question(self, "导入成功",
                        summary + "\n\n是否保留导入？(可选择回滚)",
                        QMessageBox.Save | QMessageBox.Discard, QMessageBox.Save)
                    if reply == QMessageBox.Discard:
                        ok = importer.rollback(target, result.backup_path)
                        self.bottom_panel.log_output(
                            f"[配置] 已回滚: {'成功' if ok else '失败'}", MIMO_ORANGE)
                        return

                self.bottom_panel.log_output(
                    f"[配置] 导入成功: {len(result.imported_keys)} 项", MIMO_ORANGE)
                self.bottom_panel.mimo_console.append_html(
                    f'<pre style="color:{TEXT_PRIMARY};font-size:11px;">{summary}</pre>')
            else:
                self.bottom_panel.log_output(
                    f"[配置] 导入失败: {result.error}", ERROR)
                QMessageBox.critical(self, "导入失败",
                    f"导入配置失败:\n{result.error}")

        except Exception as e:
            progress.close()
            self.bottom_panel.log_output(f"[配置] 导入异常: {e}", ERROR)
            QMessageBox.critical(self, "导入异常", str(e))

    def _start_agent_vote(self):
        """发起 Agent 投票 — 对话式投票界面"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QLineEdit, QTextEdit, QDialogButtonBox
        try:
            from shared.agent_voting import AgentVoting, VotingStrategy
            voting = AgentVoting()
        except ImportError:
            self.bottom_panel.log_output(f"[投票] agent_voting 模块不可用", Lemon.ACCENT_RED)
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("x 发起 Agent 投票")
        dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("投票主题:"))
        topic_edit = QLineEdit()
        topic_edit.setPlaceholderText("例: 是否重构数据库层")
        layout.addWidget(topic_edit)

        layout.addWidget(QLabel("详细描述:"))
        desc_edit = QTextEdit()
        desc_edit.setMaximumHeight(80)
        desc_edit.setPlaceholderText("描述投票背景和选项...")
        layout.addWidget(desc_edit)

        layout.addWidget(QLabel("投票策略:"))
        strategy_combo = QComboBox()
        strategy_combo.addItems(["多数决 (>50%)", "绝对多数 (>=2/3)", "共识决 (全员一致)", "加权投票"])
        layout.addWidget(strategy_combo)

        layout.addWidget(QLabel("参与者 (逗号分隔 agent_id):"))
        voters_edit = QLineEdit()
        voters_edit.setPlaceholderText("agent_backend, agent_frontend, agent_architect")
        layout.addWidget(voters_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec_() != QDialog.Accepted:
            return

        topic = topic_edit.text().strip()
        if not topic:
            self.bottom_panel.log_output(f"[投票] 主题不能为空", Lemon.ACCENT_ORANGE)
            return

        strategy_map = [VotingStrategy.MAJORITY, VotingStrategy.SUPERMAJORITY, VotingStrategy.CONSENSUS, VotingStrategy.WEIGHTED]
        strategy = strategy_map[strategy_combo.currentIndex()]
        voter_ids = [v.strip() for v in voters_edit.text().split(",") if v.strip()]
        if not voter_ids:
            voter_ids = ["agent_1", "agent_2", "agent_3"]

        session = voting.start_vote(
            topic=topic,
            description=desc_edit.toPlainText(),
            initiator="user",
            voter_ids=voter_ids,
            strategy=strategy,
        )
        html = f"""
        <div style="padding:8px;border:1px solid #444;border-radius:6px;margin:4px;">
        <h4 style="color:{Lemon.BRAND_ORANGE};">x 投票已发起</h4>
        <p><b>主题:</b> {topic}</p>
        <p><b>策略:</b> {strategy.value} | <b>参与者:</b> {len(voter_ids)} 人</p>
        <p><b>投票ID:</b> {session.vote_id}</p>
        <p style="color:{Lemon.STATUS_OFFLINE};font-size:11px;">超时: 5 分钟 | 状态: 进行中</p>
        </div>
        """
        self.bottom_panel.mimo_console.append_html(html)
        self.bottom_panel.log_output(f"[投票] 已发起: {topic} (ID: {session.vote_id})", Lemon.ACCENT_GREEN)

    def _show_vote_history(self):
        """显示投票历史记录"""
        try:
            from shared.agent_voting import AgentVoting
            voting = AgentVoting()
            sessions = voting.list_sessions() if hasattr(voting, 'list_sessions') else {}
            if not sessions:
                self.bottom_panel.log_output(f"[投票] 暂无投票历史", Lemon.STATUS_OFFLINE)
                return
            lines = []
            for vid, s in sessions.items():
                status_icon = {"open": "o", "closed": "v", "expired": "x"}.get(s.status.value if hasattr(s.status, 'value') else str(s.status), "[=]")
                lines.append(f"{status_icon} [{vid}] {s.topic} — {s.strategy.value}")
            html = f"""
            <div style="padding:8px;">
            <h4 style="color:{Lemon.BRAND_ORANGE};">|| 投票历史</h4>
            <pre style="color:{Lemon.SURFACE};font-size:12px;">{chr(10).join(lines)}</pre>
            </div>
            """
            self.bottom_panel.mimo_console.append_html(html)
        except Exception as e:
            self.bottom_panel.log_output(f"[投票] 查询失败: {e}", Lemon.ACCENT_RED)

    # ================================================================
    # ★ v3.71 MIEMIE (MiMi) 代码分身 — 标准模式入口
    # ================================================================

    def _miemie_analyze_project(self):
        """★ v3.71: 分析当前项目代码风格，生成MIEMIE代码分身

        通过命令面板触发，分析当前工作目录的代码风格。
        """
        try:
            project_path = getattr(self, '_current_project_path', None) or os.getcwd()
            self.bottom_panel.log_output(f"[MIEMIE] 开始分析项目: {project_path}", INFO)

            # 显示分析进度
            self._render_miemie_analysis_progress(1, 3, "扫描代码文件...", "running")

            import sys as _sys
            import os as _os
            _mimi_dir = _os.path.normpath(_os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                "miemie"
            ))
            if _mimi_dir not in _sys.path:
                _sys.path.insert(0, _mimi_dir)

            from code_clone import CodeCloneAnalyzer
            analyzer = CodeCloneAnalyzer()

            self._render_miemie_analysis_progress(2, 3, "分析代码风格...", "running")
            profile = analyzer.analyze_path(project_path)

            self._render_miemie_analysis_progress(3, 3, "生成代码分身配置...", "running")
            profile_data = profile.to_dict() if hasattr(profile, 'to_dict') else dict(profile.__dict__)

            # 构建可视化数据并渲染卡片
            card_data = self._build_miemie_profile_data_from_code_profile(profile_data)
            if card_data:
                self._render_miemie_profile_card(card_data)
                self.bottom_panel.log_output("[MIEMIE] ✅ 代码分身分析完成，卡片已渲染", SUCCESS)
            else:
                self.bottom_panel.log_output("[MIEMIE] ⚠️ 分析完成但数据为空", WARNING)

            self._render_miemie_analysis_progress(3, 3, "完成", "done")
            # 保存最后分析结果
            self._last_mimi_profile = card_data

        except Exception as e:
            self.bottom_panel.log_output(f"[MIEMIE] 分析失败: {e}", ERROR)
            self._render_miemie_analysis_progress(3, 3, f"失败: {e}", "error")

    def _miemie_show_profile(self):
        """★ v3.71: 查看已生成的MIEMIE代码分身卡片"""
        try:
            if hasattr(self, '_last_mimi_profile') and self._last_mimi_profile:
                self._render_miemie_profile_card(self._last_mimi_profile)
                self.bottom_panel.log_output("[MIEMIE] 已显示上次生成的分身卡片", INFO)
            else:
                self.bottom_panel.log_output("[MIEMIE] 尚未生成过分身卡片，请先执行'MIEMIE代码分身分析'", WARNING)
                # 自动触发分析
                self._miemie_analyze_project()
        except Exception as e:
            self.bottom_panel.log_output(f"[MIEMIE] 显示卡片失败: {e}", ERROR)

    def _open_web_browser(self):
        """★ v3.72: 打开内置浏览器"""
        if hasattr(self, 'web_browser'):
            self._switch_tab("浏览器")
            self.bottom_panel.log_output("[浏览器] 已打开内置浏览器 - 可直接浏览网页/API官网", INFO)

    def _open_role_config_dialog(self):
        """★ v4.7: 打开角色配置对话框 — 允许用户选择预设 Agent 角色"""
        try:
            from ui.role_config_dialog import RoleConfigDialog, AGENT_ROLE_PRESETS
            dialog = RoleConfigDialog(self)
            dialog.role_selected.connect(self._on_role_config_selected)
            dialog.exec_()
        except ImportError as e:
            self.bottom_panel.log_output(f"[角色] 对话框加载失败: {e}", ERROR)
            self._show_quick_role_selector()

    def _show_quick_role_selector(self):
        """★ v4.7: 快速角色选择器（内联版本，无需 role_config_dialog 模块）"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QDialogButtonBox
        roles = {
            "coder": ("代码专家", "你是一个专业的代码工程师，擅长编写、审查和优化代码。"),
            "analyst": ("分析师", "你是一个数据分析师，擅长分析问题、整理信息、生成报告。"),
            "writer": ("写作专家", "你是一个写作专家，擅长撰写文档、文章、邮件。"),
            "assistant": ("助手", "你是一个智能助手，帮助用户解决各种问题。"),
        }
        dlg = QDialog(self)
        dlg.setWindowTitle("选择 Agent 角色")
        dlg.setMinimumWidth(400)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("选择本次对话的 Agent 角色:"))
        layout.addWidget(QLabel(""))
        for role_id, (name, desc) in roles.items():
            btn = QPushButton(f"{name} — {desc}")
            btn.setStyleSheet("QPushButton { padding: 8px; text-align: left; }")
            btn.clicked.connect(lambda _, r=role_id: (dlg.accept(), self._set_agent_role(r)))
            layout.addWidget(btn)
        btns = QDialogButtonBox(QDialogButtonBox.Cancel)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        dlg.exec_()

    def _set_agent_role(self, role_id: str):
        """★ v4.7: 设置当前 Agent 角色 — 通过 EngineManager 的 chat(role=...) 实现"""
        role_names = {
            "coder": "代码专家",
            "analyst": "分析师",
            "writer": "写作专家",
            "assistant": "助手",
        }
        name = role_names.get(role_id, role_id)
        try:
            # 更新 mimo_panel 的角色
            if hasattr(self, 'mimo_panel') and self.mimo_panel:
                if hasattr(self.mimo_panel, 'set_role'):
                    self.mimo_panel.set_role(role_id)
                else:
                    self.mimo_panel._current_role = role_id
                # 同时设置 engine_manager 的 active_role
                if hasattr(self.mimo_panel, '_engine_manager') and self.mimo_panel._engine_manager:
                    self.mimo_panel._engine_manager._active_role = role_id
            self.bottom_panel.log_output(f"[角色] 已切换到: {name} ({role_id})", SUCCESS)
            # 更新状态栏显示角色
            self._update_status_bar()
        except Exception as e:
            self.bottom_panel.log_output(f"[角色] 切换失败: {e}", ERROR)

    def _on_role_config_selected(self, config: dict):
        """★ v4.7: 角色配置对话框回调"""
        role_id = config.get("role", "coder")
        self._set_agent_role(role_id)

    def _show_skills_browser(self):
        """Skill 浏览面板 — 显示已注册 Skill 列表 + 手动触发"""
        try:
            from core.skills_registry import get_skills_registry
            registry = get_skills_registry()
            manifest = registry.export_manifest()
        except Exception as e:
            self.bottom_panel.log_output(f"[Skill] 加载失败: {e}", Lemon.ACCENT_RED)
            return

        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QLineEdit, QDialogButtonBox, QTextBrowser

        dlg = QDialog(self)
        dlg.setWindowTitle("/\\ Skill 浏览")
        dlg.setMinimumSize(600, 500)
        layout = QVBoxLayout(dlg)

        # 分类过滤
        filter_layout = QVBoxLayout()
        filter_layout.addWidget(QLabel("分类:"))
        cat_combo = QComboBox()
        cat_combo.addItem("全部")
        for cat in sorted(manifest.get("categories", {}).keys()):
            cat_combo.addItem(f"{cat} ({manifest['categories'][cat]})")
        filter_layout.addWidget(cat_combo)
        layout.addLayout(filter_layout)

        # Skill 列表
        info_browser = QTextBrowser()
        info_browser.setOpenExternalLinks(False)

        def _update_list():
            cat_filter = cat_combo.currentText()
            cat_name = cat_filter.split(" (")[0] if " (" in cat_filter else ""
            skills = registry.list_skills(cat_name if cat_name != "全部" else "")
            rows = []
            for s in skills:
                confirm_mark = "!" if s.requires_confirm else ""
                rows.append(f"<tr><td style='padding:3px 8px;'>{confirm_mark}<b>{s.name}</b></td>"
                           f"<td style='padding:3px 8px;color:{Lemon.STATUS_OFFLINE};'>{s.category}</td>"
                           f"<td style='padding:3px 8px;'>{s.description[:60]}</td>"
                           f"<td style='padding:3px 8px;color:{Lemon.ACCENT_ORANGE};'>{s.timeout}s</td></tr>")
            table = (f"<table style='width:100%;border-collapse:collapse;color:{Lemon.SURFACE};font-size:12px;'>"
                    f"<tr style='color:{Lemon.BRAND_ORANGE};'><th>名称</th><th>分类</th><th>描述</th><th>超时</th></tr>"
                    f"{''.join(rows)}</table>")
            info_browser.setHtml(table)

        cat_combo.currentIndexChanged.connect(_update_list)
        layout.addWidget(info_browser)
        _update_list()

        # Skill 执行区
        exec_layout = QVBoxLayout()
        exec_layout.addWidget(QLabel("执行 Skill (输入 name 和 JSON 参数):"))
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("skill_name")
        args_edit = QLineEdit()
        args_edit.setPlaceholderText('{"key": "value"}')
        result_browser = QTextBrowser()
        result_browser.setMaximumHeight(100)

        from PyQt5.QtWidgets import QPushButton
        exec_btn = QPushButton("> 执行")

        def _exec_skill():
            skill_name = name_edit.text().strip()
            if not skill_name:
                return
            try:
                args = json.loads(args_edit.text()) if args_edit.text().strip() else {}
            except json.JSONDecodeError:
                args = {}
            result = registry.execute(skill_name, args)
            result_browser.setHtml(
                f"<p style='color:{Lemon.ACCENT_GREEN if result.success else Lemon.ACCENT_RED};'>"
                f"{'v' if result.success else 'x'} {result.output or result.error}</p>"
            )

        exec_btn.clicked.connect(_exec_skill)
        exec_layout.addWidget(name_edit)
        exec_layout.addWidget(args_edit)
        exec_layout.addWidget(exec_btn)
        exec_layout.addWidget(result_browser)
        layout.addLayout(exec_layout)

        close_btn = QDialogButtonBox(QDialogButtonBox.Close)
        close_btn.rejected.connect(dlg.reject)
        layout.addWidget(close_btn)

        dlg.exec_()

    def _show_engine_dispatch_diagnosis(self):
        """引擎无关调度诊断 — 展示 SmartDispatcher 可用引擎与统计（P2 引擎无关化）"""
        panel = getattr(self, "mimo_panel", None)
        dispatcher = panel.get_smart_dispatcher() if panel is not None else None
        if dispatcher is None:
            self.bottom_panel.log_output(
                "[调度] SmartDispatcher 未就绪（引擎管理器未连接）", ERROR)
            return
        try:
            engines = dispatcher.list_engines()
            avail = [e.name for e in dispatcher.available_engines()]
            stats = dispatcher.get_stats()
            lines = ["[引擎无关调度诊断 (SmartDispatcher)]",
                     f"  已注册引擎: {', '.join(engines) or '无'}",
                     f"  当前可用:   {', '.join(avail) or '无'}"]
            for name in engines:
                s = stats.get(name, {})
                rate = s.get('success_rate', 1.0)
                lines.append(
                    f"  · {name:<10} 成功率 {rate:.0%} "
                    f"(成功{s.get('success_count', 0)}/失败{s.get('fail_count', 0)})")
            self.bottom_panel.log_output("\n".join(lines), MIMO_ORANGE)
        except Exception as e:
            self.bottom_panel.log_output(f"[调度] 诊断失败: {e}", ERROR)

    def _show_plugin_market(self):
        """插件市场面板 — 浏览、启用/禁用、卸载插件"""
        try:
            import importlib.util
            _pm_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin_market.py")
            if os.path.exists(_pm_path):
                spec = importlib.util.spec_from_file_location("plugin_market", _pm_path)
                pm_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(pm_mod)
                PluginMarketPanel = pm_mod.PluginMarketPanel
            else:
                self.bottom_panel.log_output(f"[插件市场] 文件不存在: {_pm_path}", ERROR)
                return
        except Exception as e:
            import traceback
            self.bottom_panel.log_output(f"[插件市场] 加载失败: {e}\n{traceback.format_exc()}", ERROR)
            return

        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle("[] 插件市场")
        dlg.setMinimumSize(800, 600)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建插件市场面板
        market_panel = PluginMarketPanel(plugin_manager=self.plugin_mgr, parent=dlg)
        layout.addWidget(market_panel)

        # 关闭按钮
        close_btn = QDialogButtonBox(QDialogButtonBox.Close)
        close_btn.rejected.connect(dlg.reject)
        layout.addWidget(close_btn)

        self.bottom_panel.log_output("[插件市场] 已打开插件市场面板", SUCCESS)
        dlg.exec_()

    def _show_recent_files(self):
        """显示最近打开的文件列表"""
        if not self._recent_files:
            self.bottom_panel.log_output("[最近文件] 暂无最近打开的文件", WARNING)
            return
        self.bottom_panel.log_output("[最近文件] 最近打开的文件:", INFO)
        for i, f in enumerate(self._recent_files, 1):
            self.bottom_panel.log_output(f"  {i}. {f}")
        self.bottom_panel.log_output("  点击文件名可快速打开", INFO)

    def _show_command_history(self):
        """显示命令历史"""
        if not self._command_history:
            self.bottom_panel.log_output("[命令历史] 暂无历史命令", WARNING)
            return
        self.bottom_panel.log_output(f"[命令历史] 最近 {len(self._command_history)} 条命令:", INFO)
        for i, cmd in enumerate(self._command_history[-20:], 1):
            self.bottom_panel.log_output(f"  {i}. {cmd[:80]}{'...' if len(cmd) > 80 else ''}")

    def _on_file_replace(self, file_path, old_content, new_content):
        """处理文件替换请求"""
        full_path = os.path.join(self.engine.project_path, file_path)
        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            self.bottom_panel.log_output(f"[替换] {file_path} — 已保存替换结果", SUCCESS)
            # 刷新编辑器显示
            self._open_editor_tab(file_path, new_content)
            # 刷新文件树
            files = self.engine.scan_project(self.engine.project_path)
            self.explorer.load_project(self.engine.project_path, files)
        except Exception as e:
            self.bottom_panel.log_output(f"[替换] {file_path} — 保存失败: {e}", ERROR)
            QMessageBox.critical(self, "错误", f"写入文件失败: {e}")

    def _on_compare_file(self, file_path):
        """对比文件 — 与 Git HEAD 版本对比或与另一个文件对比"""
        project_path = self.engine.project_path
        full_path = os.path.join(project_path, file_path)

        # 读取当前文件内容
        try:
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                current_content = f.read()
        except Exception as e:
            self.bottom_panel.log_output(f"[对比] 无法读取文件: {e}", ERROR)
            return

        # 优先尝试 Git diff（与 HEAD 版本对比）
        if self.git_manager.is_git_repo:
            old_content = self.git_manager.get_file_at_head(file_path)
            if old_content is not None and old_content != current_content:
                self._open_side_by_side_diff(
                    f"{file_path} (HEAD)", old_content,
                    f"{file_path} (工作区)", current_content
                )
                self.bottom_panel.log_output(f"[对比] {file_path} — 与 Git HEAD 对比", INFO)
                return

        # 如果没有 Git 或文件未修改，询问用户选择另一个文件对比
        other_file, ok = QInputDialog.getText(
            self, "文件对比", f"对比 {file_path} 与哪个文件？\n(输入相对路径，如 src/main.py):"
        )
        if ok and other_file.strip():
            other_full = os.path.join(project_path, other_file.strip())
            if os.path.exists(other_full):
                try:
                    with open(other_full, 'r', encoding='utf-8', errors='replace') as f:
                        other_content = f.read()
                    self._open_side_by_side_diff(
                        file_path, current_content,
                        other_file.strip(), other_content
                    )
                    self.bottom_panel.log_output(f"[对比] {file_path} ↔ {other_file.strip()}", INFO)
                except Exception as e:
                    self.bottom_panel.log_output(f"[对比] 读取对比文件失败: {e}", ERROR)
            else:
                self.bottom_panel.log_output(f"[对比] 文件不存在: {other_file.strip()}", WARNING)
        else:
            self.bottom_panel.log_output(f"[对比] {file_path} — 无 Git 历史，无法对比", WARNING)

    def _open_side_by_side_diff(self, left_path, left_content, right_path, right_content):
        """打开双栏对比视图"""
        diff_editor = SideBySideDiffEditor()
        diff_editor.set_comparison(left_path, left_content, right_path, right_content)
        tab_name = f"↔ {os.path.basename(left_path)} vs {os.path.basename(right_path)}"
        idx = self.editor_tabs.addTab(diff_editor, tab_name)
        self.editor_tabs.setCurrentIndex(idx)
        self.breadcrumb_label.setText(f"  对比: {left_path} ↔ {right_path}")

    # ================================================================
    # Git 操作
    # ================================================================
    def _on_git_action(self, action, file_path):
        """处理 Git 右键菜单操作"""
        if action == "review":
            # 代码审查：先打开文件再审查
            content = self.engine.read_file(file_path)
            self._open_editor_tab(file_path, content)
            self._code_review_current_file()
            return
        if not self.git_manager.is_git_repo:
            self.bottom_panel.log_output("[Git] 当前项目不是 Git 仓库", WARNING)
            return
        if action == "stage":
            ok, msg = self.git_manager.stage_file(file_path)
            if ok:
                self.bottom_panel.log_output(f"[Git] 已暂存: {file_path}", SUCCESS)
            else:
                self.bottom_panel.log_output(f"[Git] 暂存失败: {msg}", ERROR)
        elif action == "unstage":
            ok, msg = self.git_manager.unstage_file(file_path)
            if ok:
                self.bottom_panel.log_output(f"[Git] 已取消暂存: {file_path}", SUCCESS)
            else:
                self.bottom_panel.log_output(f"[Git] 取消暂存失败: {msg}", ERROR)
        elif action == "diff":
            diff = self.git_manager.get_diff()
            if diff:
                self.bottom_panel.log_output(f"[Git Diff] {file_path}:", INFO)
                # 显示 diff 内容
                for line in diff.split('\n')[:100]:
                    if line.startswith('+'):
                        self.bottom_panel.mimo_console.append_html(
                            f'<span style="color:{Lemon.STATUS_ONLINE};">{line}</span>'
                        )
                    elif line.startswith('-'):
                        self.bottom_panel.mimo_console.append_html(
                            f'<span style="color:{Lemon.ERROR};">{line}</span>'
                        )
                    elif line.startswith('@@'):
                        self.bottom_panel.mimo_console.append_html(
                            f'<span style="color:{Lemon.SYNTAX_FUNCTION};">{line}</span>'
                        )
                    else:
                        self.bottom_panel.mimo_console.append_html(f'<span>{line}</span>')
            else:
                self.bottom_panel.log_output(f"[Git Diff] {file_path} — 无变更", INFO)
        # 刷新状态
        self.git_manager.refresh_status()
        self._update_status_bar()

    def _show_git_status(self):
        """显示 Git 状态摘要"""
        if not self.git_manager.is_git_repo:
            self.bottom_panel.log_output("[Git] 当前项目不是 Git 仓库", WARNING)
            return
        summary = self.git_manager.get_summary()
        self.bottom_panel.log_output(f"[Git] 分支: {summary['branch']}", INFO)
        if summary['total_changes'] == 0:
            self.bottom_panel.log_output("[Git] 工作区干净，无待提交变更", SUCCESS)
            return
        changes = []
        if summary['modified']: changes.append(f"修改: {summary['modified']}")
        if summary['added']: changes.append(f"新增: {summary['added']}")
        if summary['deleted']: changes.append(f"删除: {summary['deleted']}")
        if summary['untracked']: changes.append(f"未跟踪: {summary['untracked']}")
        if summary['conflicts']: changes.append(f"冲突: {summary['conflicts']}")
        self.bottom_panel.log_output(f"[Git] 变更: {', '.join(changes)}", WARNING)
        # 列出具体文件
        for f, status in self.git_manager._status_cache.items():
            self.bottom_panel.log_output(f"  {status}  {f}")

    def _git_commit(self):
        """Git commit 对话框"""
        if not self.git_manager.is_git_repo:
            self.bottom_panel.log_output("[Git] 当前项目不是 Git 仓库", WARNING)
            return
        summary = self.git_manager.get_summary()
        if summary['total_changes'] == 0:
            self.bottom_panel.log_output("[Git] 无变更需要提交", WARNING)
            return
        msg, ok = QInputDialog.getMultiLineText(
            self, "Git Commit", "提交信息:",
            f"feat: update {summary['total_changes']} files"
        )
        if ok and msg.strip():
            ok, result = self.git_manager.commit(msg.strip())
            if ok:
                self.bottom_panel.log_output(f"[Git] 提交成功: {result}", SUCCESS)
            else:
                self.bottom_panel.log_output(f"[Git] 提交失败: {result}", ERROR)
            self.git_manager.refresh_status()
            self._update_status_bar()

    def _git_push(self):
        """Git push"""
        if not self.git_manager.is_git_repo:
            self.bottom_panel.log_output("[Git] 当前项目不是 Git 仓库", WARNING)
            return
        self.bottom_panel.log_output("[Git] 正在推送...", INFO)
        ok, result = self.git_manager.push()
        if ok:
            self.bottom_panel.log_output(f"[Git] 推送成功: {result}", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[Git] 推送失败: {result}", ERROR)

    def _git_pull(self):
        """Git pull"""
        if not self.git_manager.is_git_repo:
            self.bottom_panel.log_output("[Git] 当前项目不是 Git 仓库", WARNING)
            return
        self.bottom_panel.log_output("[Git] 正在拉取...", INFO)
        ok, result = self.git_manager.pull()
        if ok:
            self.bottom_panel.log_output(f"[Git] 拉取成功: {result}", SUCCESS)
        else:
            self.bottom_panel.log_output(f"[Git] 拉取失败: {result}", ERROR)

    def _show_git_log(self):
        """显示 Git log"""
        if not self.git_manager.is_git_repo:
            self.bottom_panel.log_output("[Git] 当前项目不是 Git 仓库", WARNING)
            return
        log = self.git_manager.get_log(10)
        if log:
            self.bottom_panel.log_output("[Git Log] 最近提交:", INFO)
            for line in log.split('\n'):
                if line.strip():
                    self.bottom_panel.log_output(f"  {line}")
        else:
            self.bottom_panel.log_output("[Git] 无提交记录", WARNING)

    # ================================================================
    # Ollama 代码审查
    # ================================================================
    def _code_review_current_file(self):
        """使用本地 Ollama 模型审查当前编辑器文件"""
        current_widget = self.editor_tabs.currentWidget()
        if not current_widget:
            self.bottom_panel.log_output("[审查] 没有打开的编辑器文件", WARNING)
            return

        # 获取当前文件内容
        if hasattr(current_widget, 'editor'):
            code = current_widget.editor.toPlainText()
        else:
            self.bottom_panel.log_output("[审查] 当前标签不支持代码审查", WARNING)
            return

        tab_name = self.editor_tabs.tabText(self.editor_tabs.currentIndex())
        if not code.strip():
            self.bottom_panel.log_output("[审查] 文件内容为空", WARNING)
            return

        # 检查 Ollama 可用性
        if not self.ollama_bridge.is_available():
            self.bottom_panel.log_output("[审查] Ollama 服务未启动，请先启动 Ollama", WARNING)
            return

        self.bottom_panel.log_output(f"[审查] 正在审查 {tab_name} ({len(code)} 字符)...", INFO)
        self.bottom_panel.log_output("[审查] 使用本地 qwen3.5:4b 模型，请稍候...", INFO)
        self.ollama_bridge.review_code(code, file_path=tab_name)

    # ================================================================
    # 多会话并行管理 — 事件处理
    # ================================================================
    def _on_multi_new_session(self):
        """创建新的并行会话"""
        name = f"任务 {self.multi_session_mgr.session_count + 1}"
        sid = self.multi_session_mgr.create_session(name)
        if sid:
            self.bottom_panel.log_output(f"[多会话] 创建并行会话: {name} ({sid[:12]}...)", SUCCESS)
        else:
            self.bottom_panel.log_output("[多会话] 创建会话失败 — Serve Bridge 未就绪", WARNING)
            self.serve_bridge.create_session()
    
    def _on_multi_close_session(self, session_id: str):
        """关闭并行会话"""
        info = self.multi_session_mgr.get_session(session_id)
        name = info.name if info else session_id[:12]
        self.multi_session_mgr.close_session(session_id)
        self.bottom_panel.log_output(f"[多会话] 关闭会话: {name}", INFO)
    
    def _on_multi_session_selected(self, session_id: str):
        """用户在面板中选择会话"""
        self.multi_session_mgr.switch_session(session_id)
        info = self.multi_session_mgr.get_session(session_id)
        if info:
            self.bottom_panel.log_output(f"[多会话] 切换到: {info.name}", INFO)
    
    def _on_multi_send_to_session(self, session_id: str, message: str):
        """向指定会话发送消息"""
        info = self.multi_session_mgr.get_session(session_id)
        if not info:
            return
        
        self.bottom_panel.log_output(f"[多会话] → {info.name}: {message[:50]}", INFO)
        self.multi_session_mgr.switch_session(session_id)
        self.multi_session_mgr.set_session_state(session_id, SessionState.BUSY)
        
        if self.serve_bridge.is_connected:
            self.serve_bridge.send_message(message)
        else:
            self.bottom_panel.log_output("[多会话] Serve Bridge 未连接，无法发送", WARNING)
    
    def _on_multi_session_added(self, session_id: str, name: str):
        """MultiSessionManager 通知：会话已添加"""
        info = self.multi_session_mgr.get_session(session_id)
        role = info.role.value if info else "general"
        self.multi_session_panel.add_session(session_id, name, role)
        self._update_status_bar()
    
    def _on_multi_session_removed(self, session_id: str):
        """MultiSessionManager 通知：会话已移除"""
        self.multi_session_panel.remove_session(session_id)
        self._update_status_bar()
    
    def _on_multi_session_state_changed(self, session_id: str, state: str):
        """MultiSessionManager 通知：会话状态变更"""
        self.multi_session_panel.set_session_state(session_id, state)
    
    def _on_multi_session_output(self, session_id: str, text: str):
        """MultiSessionManager 通知：会话输出"""
        self.multi_session_panel.append_output(session_id, text)
    
    def _on_multi_active_changed(self, session_id: str):
        """MultiSessionManager 通知：活动会话变更"""
        self.multi_session_panel.set_active_session(session_id)

    # ================================================================
    # 多实例集群管理回调（v2.0 新增）
    # ================================================================
    
    def _on_instance_added(self, instance_id, name, port):
        """多实例管理器通知：实例已添加"""
        info = self.multi_instance_mgr._instances.get(instance_id)
        role = info.role.value if info else "general"
        self.multi_instance_grid.add_pane(instance_id, name, role, port)
        self.bottom_panel.log_output(f"[集群] {name} 已启动 (端口 {port})", SUCCESS)
    
    def _on_instance_state_changed(self, instance_id, state):
        """多实例管理器通知：实例状态变化"""
        self.multi_instance_grid.set_instance_status(instance_id, state)
        summary = self.multi_instance_mgr.get_cluster_summary()
        status_text = self.multi_instance_mgr.get_status_text()
        self._instance_status_label.setText(status_text)
        self.multi_instance_grid.update_director_status(
            f"指挥官: {state} | Workers: {summary['active_workers']}/{len(summary['workers'])}"
        )
        self.multi_instance_grid.update_worker_count(
            summary['active_workers'], len(summary['workers'])
        )
    
    def _on_instance_output(self, instance_id, text):
        """多实例管理器通知：实例输出"""
        self.multi_instance_grid.append_output(instance_id, text)
    
    def _on_director_aggregated(self, aggregated):
        """Director 聚合结果"""
        self.multi_instance_grid.update_director_status(f"指挥官: 已聚合结果")
        self.bottom_panel.log_output(f"[导演] 聚合结果:\n{aggregated[:500]}", SUCCESS)
    
    def _on_all_instances_idle(self):
        """所有实例空闲"""
        self._instance_status_label.setStyleSheet(f"color: {Lemon.STATUS_ONLINE}; font-size: 10px;")
        self._instance_status_label.setText("v 全部空闲")
        self.bottom_panel.log_output("[集群] 所有实例空闲", SUCCESS)
    
    def _on_worker_result(self, instance_id, task_id, result):
        """Worker 完成结果"""
        self.multi_instance_grid.append_output(instance_id, f"[{task_id}] {result[:200]}")
    
    def _on_task_dispatched(self, task, from_instance, to_instance):
        """任务分发通知"""
        self.bottom_panel.log_output(
            f"[分发] {from_instance} → {to_instance}: {task[:100]}", INFO
        )
    
    def _on_grid_instance_selected(self, instance_id):
        """网格面板点击实例"""
        self.multi_instance_grid.set_active_instance(instance_id)
        self.bottom_panel.log_output(f"[集群] 选中实例: {instance_id}", INFO)
    
    def _on_grid_instance_maximized(self, instance_id):
        """网格面板最大化实例"""
        self.bottom_panel.log_output(f"[集群] 最大化实例: {instance_id}", INFO)
    
    def _start_cluster(self, count: int):
        """启动 Lemon Code 集群"""
        self._instance_status_label.setText("🔄 启动中...")
        self._instance_status_label.setStyleSheet(f"color: {Lemon.STATUS_RUNNING}; font-size: 10px;")
        self.bottom_panel.log_output(f"[集群] 启动 {count} 个 Lemon Code 实例...", INFO)
        started = self.multi_instance_mgr.start_all(count)
        self.bottom_panel.log_output(f"[集群] 成功启动 {started}/{count} 个实例", SUCCESS if started == count else WARNING)
        self.multi_instance_grid.show()
        self.mimo_panel.hide()
        self.multi_session_panel.hide()
    
    def _stop_cluster(self):
        """停止所有 Lemon Code 实例"""
        self.multi_instance_mgr.stop_all()
        self._instance_status_label.setText("[=] 未启动")
        self._instance_status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        self.multi_instance_grid.clear_all()
        self.multi_instance_grid.hide()
        self.mimo_panel.show()
        self.bottom_panel.log_output("[集群] 所有实例已停止", INFO)
    
    def _toggle_instance_grid(self):
        """切换网格视图"""
        if self.multi_instance_grid.isVisible():
            self.multi_instance_grid.hide()
            self.mimo_panel.show()
        else:
            self.mimo_panel.hide()
            self.multi_session_panel.hide()
            self.multi_instance_grid.show()
    
    def _show_cluster_status(self):
        """显示集群状态"""
        summary = self.multi_instance_mgr.get_cluster_summary()
        msg = f"""集群状态:
- 总实例: {summary['total']}
- 运行中: {summary['running']}
- Director: {summary['director']['state'] if summary['director'] else '未配置'}
- Workers: {summary['active_workers']}/{len(summary['workers'])}
- MIMO路径: {summary['mimo_exe'] or '未找到'}"""
        QMessageBox.information(self, "集群状态", msg)
        self.bottom_panel.log_output(f"[集群] 状态查询完成", INFO)
    
    def _create_separator(self):
        """创建工具栏分隔符"""
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {BORDER_DEFAULT};")
        return sep

    # ================================================================
    # ★ 会话历史 UI Tab（M1）
    # ================================================================

    def _create_session_history_tab(self):
        """创建会话历史 Tab — 显示 agent 会话时间线 + Handoff 预览"""
        from PyQt5.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QTextBrowser, QSplitter
        from PyQt5.QtCore import Qt

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Vertical)

        # 上方: 会话列表
        self._session_list = QListWidget()
        self._session_list.itemClicked.connect(self._on_session_item_clicked)
        splitter.addWidget(self._session_list)

        # 下方: Handoff 文档预览
        self._handoff_preview = QTextBrowser()
        self._handoff_preview.setOpenExternalLinks(False)
        splitter.addWidget(self._handoff_preview)

        splitter.setSizes([300, 200])
        layout.addWidget(splitter)

        # 刷新按钮
        from PyQt5.QtWidgets import QPushButton, QHBoxLayout
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self._refresh_session_history)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return tab

    def _refresh_session_history(self):
        """刷新会话历史列表"""
        self._session_list.clear()
        try:
            from shared.session_continuity import SessionContinuity
            sc = SessionContinuity()
            sessions = sc.get_project_sessions("default_project") if hasattr(sc, 'get_project_sessions') else []
            for s in sessions:
                sid = s.get("session_id", "?") if isinstance(s, dict) else getattr(s, "session_id", "?")
                agent = s.get("agent_id", "?") if isinstance(s, dict) else getattr(s, "agent_id", "?")
                ts = s.get("timestamp", "") if isinstance(s, dict) else getattr(s, "timestamp", "")
                item = QListWidgetItem(f"[{ts[:16]}] {agent} — {sid[:12]}")
                item.setData(100, s)  # 存储完整数据
                self._session_list.addItem(item)
            if not sessions:
                self._session_list.addItem(QListWidgetItem("(暂无会话记录)"))
        except Exception as e:
            self._session_list.addItem(QListWidgetItem(f"加载失败: {e}"))

    def _on_session_item_clicked(self, item):
        """点击会话条目 — 预览 Handoff 文档"""
        data = item.data(100)
        if not data:
            return
        sid = data.get("session_id", "?") if isinstance(data, dict) else getattr(data, "session_id", "?")
        try:
            from shared.session_continuity import SessionContinuity
            sc = SessionContinuity()
            handoff = sc.get_handoff_document(sid) if hasattr(sc, 'get_handoff_document') else None
            if handoff:
                self._handoff_preview.setMarkdown(str(handoff))
            else:
                self._handoff_preview.setHtml(f"<p style='color:{Lemon.STATUS_OFFLINE};'>会话 {sid[:12]} 无 Handoff 文档</p>")
        except Exception as e:
            self._handoff_preview.setHtml(f"<p style='color:{Lemon.ACCENT_RED};'>预览失败: {e}</p>")

    # ================================================================
    # ★ 模式状态同步（M5）
    # ================================================================

    def _sync_mode_state(self, from_mode: str, to_mode: str):
        """同步两个模式间的关键状态"""
        sync_data = {}
        try:
            # 同步引擎状态
            if hasattr(self, 'engine_manager') and self.engine_manager:
                sync_data['current_engine'] = self.engine_manager.current_engine_name if hasattr(self.engine_manager, 'current_engine_name') else ''
            # 同享当前文件
            if hasattr(self, 'code_editor') and self.code_editor:
                sync_data['current_file'] = getattr(self.code_editor, '_current_file', '')
            # 同享 Git 状态
            if hasattr(self, 'git_manager') and self.git_manager:
                sync_data['git_branch'] = self.git_manager.branch
            # 发送到目标模式
            if to_mode == "hybrid" and hasattr(self, 'hybrid_panel'):
                if hasattr(self.hybrid_panel, '_apply_sync_state'):
                    self.hybrid_panel._apply_sync_state(sync_data)
            elif to_mode == "standard":
                # 标准模式从混合模式同步
                if hasattr(self, 'hybrid_panel') and hasattr(self.hybrid_panel, '_get_sync_state'):
                    hybrid_state = self.hybrid_panel._get_sync_state()
                    if 'current_engine' in hybrid_state and hasattr(self, 'engine_manager'):
                        pass  # 引擎切换由用户主动触发
        except Exception as e:
            self.bottom_panel.log_output(f"[同步] 模式状态同步失败: {e}", WARNING)

    # ★ v4.0: 无边框窗口边缘调整大小
    def _get_resize_mode(self, pos):
        """根据鼠标位置返回 resize 模式"""
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        m = self._resize_margin
        left = x < m
        right = x > w - m
        top = y < m
        bottom = y > h - m
        if top and left: return 'tl'
        if top and right: return 'tr'
        if bottom and left: return 'bl'
        if bottom and right: return 'br'
        if top: return 't'
        if bottom: return 'b'
        if left: return 'l'
        if right: return 'r'
        return None

    def _cursor_for_mode(self, mode):
        mapping = {
            'tl': Qt.SizeFDiagCursor, 'br': Qt.SizeFDiagCursor,
            'tr': Qt.SizeBDiagCursor, 'bl': Qt.SizeBDiagCursor,
            't': Qt.SizeVerCursor, 'b': Qt.SizeVerCursor,
            'l': Qt.SizeHorCursor, 'r': Qt.SizeHorCursor,
        }
        return mapping.get(mode, Qt.ArrowCursor)

    def nativeEvent(self, eventType, message):
        """★ v6.1 修复：Windows 原生边缘拖拽（WM_NCHITTEST 命中测试）。

        根因：无边框窗口的边缘 8px 区域被子组件（title_bar / central widget /
        WebEngine）完全覆盖，鼠标事件到不了 QMainWindow 的 mouseMoveEvent，
        导致旧的边缘调整逻辑永远不触发（点击边缘无拖拽伸缩效果）。

        方案：拦截系统 WM_NCHITTEST 消息，在边缘区域返回 HTLEFT/HTRIGHT/
        HTTOP... 命中码，由 Windows 原生处理拖拽缩放 — 无论鼠标位于哪个
        子组件之上都有效（无边框窗口标准做法）。
        """
        if eventType == "windows_generic_MSG":
            try:
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    # lParam: 低16位=屏幕x, 高16位=屏幕y（有符号）
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    pos = self.mapFromGlobal(QPoint(x, y))
                    m = self._resize_margin
                    w, h = self.width(), self.height()
                    left = pos.x() < m
                    right = pos.x() > w - m
                    top = pos.y() < m
                    bottom = pos.y() > h - m
                    if not (left or right or top or bottom):
                        return super().nativeEvent(eventType, message)
                    # 最大化状态下不允许边缘调整
                    if self.isMaximized():
                        return super().nativeEvent(eventType, message)
                    if top and left:     ht = 13  # HTTOPLEFT
                    elif top and right:  ht = 14  # HTTOPRIGHT
                    elif bottom and left: ht = 16  # HTBOTTOMLEFT
                    elif bottom and right: ht = 17  # HTBOTTOMRIGHT
                    elif top:            ht = 12  # HTTOP
                    elif bottom:         ht = 15  # HTBOTTOM
                    elif left:           ht = 10  # HTLEFT
                    else:                ht = 11  # HTRIGHT
                    return True, ht
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            mode = self._get_resize_mode(event.pos())
            if mode:
                self._resize_mode = mode
                self._resize_start_geom = self.geometry()
                self._resize_start_pos = event.globalPos()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_mode and event.buttons() == Qt.LeftButton and self._resize_start_pos:
            gp = event.globalPos()
            delta = gp - self._resize_start_pos
            geom = self._resize_start_geom
            new_geom = QRect(geom)
            mode = self._resize_mode
            if 'r' in mode:
                new_geom.setRight(geom.right() + delta.x())
            if 'l' in mode:
                new_geom.setLeft(geom.left() + delta.x())
            if 'b' in mode:
                new_geom.setBottom(geom.bottom() + delta.y())
            if 't' in mode:
                new_geom.setTop(geom.top() + delta.y())
            # 限制最小尺寸
            if new_geom.width() >= self.minimumWidth() and new_geom.height() >= self.minimumHeight():
                self.setGeometry(new_geom)
            event.accept()
            return
        mode = self._get_resize_mode(event.pos())
        self.setCursor(self._cursor_for_mode(mode) if mode else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resize_mode = None
        self._resize_start_geom = None
        self._resize_start_pos = None
        self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._resize_mode:
            self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def closeEvent(self, event):
        """窗口关闭时清理"""
        # ★ LemonGaze: 释放陪伴层（停动画 + 释放本窗口状态快照）
        try:
            from ui.companion.companion_dock import unmount_companion
            unmount_companion(self)
        except Exception:
            pass
        try:
            self.serve_bridge.stop()
        except Exception:
            pass
        try:
            self.acp_bridge.stop()
        except Exception:
            pass
        try:
            self.gui_bridge.stop()
        except Exception:
            pass
        try:
            self.proc_bridge.stop()
        except Exception:
            pass
        # 清理混合模式面板的后台线程
        try:
            if hasattr(self, 'hybrid_mode_panel') and self.hybrid_mode_panel:
                for t in getattr(self.hybrid_mode_panel, '_background_threads', []):
                    if hasattr(t, 'stop'):
                        t.stop()
                    elif hasattr(t, 'join'):
                        try:
                            t.join(timeout=2)
                        except Exception:
                            pass
                self.hybrid_mode_panel._background_threads.clear()
        except Exception:
            pass
        # ★ 修复: 关闭时停止咩咩后台炼化线程（避免 QThread 残留）
        try:
            from ui.miemie_engine import tool_persona_worker_stop
            tool_persona_worker_stop(timeout_ms=2000)
        except Exception:
            pass
        event.accept()

    def _start_memory_monitor(self):
        """启动内存监控 — 定期检查并在内存过高时清理"""
        from PyQt5.QtCore import QTimer
        self._mem_monitor_timer = QTimer(self)
        self._mem_monitor_timer.timeout.connect(self._check_and_cleanup_memory)
        self._mem_monitor_timer.start(60000)  # 每 60 秒检查一次
        self._mem_peak_mb = 0.0

    def _check_and_cleanup_memory(self):
        """检查内存使用，过高时清理"""
        try:
            import psutil
            process = psutil.Process()
            mem_mb = process.memory_info().rss / 1024 / 1024
            self._mem_peak_mb = max(self._mem_peak_mb, mem_mb)

            # 内存超过 800MB 时主动清理
            if mem_mb > 800:
                self._cleanup_qwebengine_memory()
                self.bottom_panel.log_output(
                    f"[内存] 内存 {mem_mb:.0f}MB 超阈值 800MB，已执行清理",
                    WARNING
                )
            elif mem_mb > 500:
                # 超过 500MB 记录但不清理
                pass
        except ImportError:
            # psutil 不可用时跳过
            pass
        except Exception:
            pass

    def _cleanup_qwebengine_memory(self):
        """清理 QWebEngine 相关内存"""
        try:
            # 清理所有 QWebEngineView 的缓存
            from PyQt5.QtWebEngineWidgets import QWebEngineProfile
            profile = QWebEngineProfile.defaultProfile()
            # 禁用磁盘缓存（避免 QtWebEngine 在 Windows 上反复报 "Unable to move cache"）
            try:
                profile.setHttpCacheType(QWebEngineProfile.NoCache)
            except Exception:
                pass
            profile.clearHttpCache()
            profile.clearAllVisitedLinks()
        except Exception:
            pass
        try:
            import gc
            gc.collect()
        except Exception:
            pass