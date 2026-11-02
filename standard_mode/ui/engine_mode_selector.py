# -*- coding: utf-8 -*-
"""
模式选择器 — 显示在标题栏右上角

★ v4.1.7: 四段模式 + 英文品牌名
- 模式: LemonCode (Native Agent) / Code (Local Code) / Agent (Host Agent) / Solo (IDE Solo)
- 模型: 点击后弹出大列表，分类显示本地/Ollama/API模型

状态指示灯：
- 绿色：当前模式引擎在线
- 红色：当前模式引擎离线
- 自动模式：任一引擎在线即绿色
- Agent 模式：外部 Agent 连接成功即绿色
"""

import os
import sys
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QMenu, QAction,
    QVBoxLayout, QScrollArea, QFrame, QSizePolicy
)
from PyQt5.QtCore import pyqtSignal, Qt, QTimer, QRect
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont, QIcon

# 导入主题色
sys.path.insert(0, os.path.dirname(__file__))
from theme import (
    LEMON_ORANGE, LEMON_ORANGE_LIGHT,
    BG_SURFACE, BG_SURFACE_HOVER, BG_ROOT, BG_PRIMARY,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_STRONG, BORDER_DEFAULT, RADIUS_MD, RADIUS_SM,
    FONT_SIZE_SM, FONT_SIZE_XS,
)
from ui.design.tokens import Lemon

# 引擎在线状态色
COLOR_GREEN = Lemon.ACCENT_GREEN
COLOR_RED = Lemon.ACCENT_RED
COLOR_GRAY = 'Lemon.SECONDARY'
COLOR_PURPLE = Lemon.ACCENT_PURPLE  # Agent 模式专用色
COLOR_BLUE = Lemon.ACCENT_BLUE    # LemonCode 模式专用色
COLOR_SLATE = '#5d6d7e'   # ★ v4.1.7: Solo 模式专用色（中性灰蓝，纯 IDE）


# ★ v4.1.9: 模式收敛为两段 — Native Agent / Host Agent
# 历史：v4.1.7 时四段（lemoncode/code/agent/solo）造成"IDE Solo" 与 Trae Solo 语义混淆；
#       v4.1.9 按用户决策方案甲，收敛为两段，保留核心算力路径
#   - Native Agent：自研引擎栈（Ollama/DeepSeek/本地模型）
#   - Host Agent：夺舍外部下载到本地的 Agent（MiMo Code / Aider / OpenCode / …）
MODE_TO_ENGINE = {
    "native": "auto",       # Native Agent — LemonCode 本体 Agent
    "host": "acp",          # Host Agent — 夺舍外部 Agent
}

# 模式显示名称（短，按钮上显示 — 英文大写美观）
MODE_LABELS = {
    "native": "NATIVE",
    "host": "HOST",
}

# ★ v4.1.9: 模式英文品牌名（用于 tooltip）
MODE_BRAND = {
    "native": "Native Agent",
    "host": "Host Agent",
}

# ★ v4.1.9: 模式副标题（用于 tooltip）
MODE_SUBTITLE = {
    "native": "LemonCode 本体 Agent · 自研引擎栈",
    "host": "外部 Agent 夺舍 · MiMo Code / Aider / OpenCode / ...",
}


class ModelListPopup(QWidget):
    """模型选择弹出面板 — 大列表展示本地/Ollama/API模型"""

    model_selected = pyqtSignal(str)  # 模型ID

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self._models = {
            "local": [],    # 本地文件夹模型
            "ollama": [],   # Ollama 模型
            "api": [],      # API 模型
        }
        self._init_ui()

    def _init_ui(self):
        self.setFixedSize(320, 400)
        self.setStyleSheet(f"""
            QWidget {{
                background: {BG_PRIMARY};
                border: 1px solid {BORDER_STRONG};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{
                background: {BG_SURFACE};
                border-bottom: 1px solid {BORDER_STRONG};
                border-radius: 8px 8px 0 0;
            }}
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)

        title = QLabel("模型选择")
        title.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setToolTip("刷新模型列表")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: {BG_SURFACE_HOVER};
                color: {LEMON_ORANGE};
            }}
        """)
        refresh_btn.clicked.connect(self._on_refresh)
        header_layout.addWidget(refresh_btn)

        layout.addWidget(header)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {BG_ROOT};
                border: none;
            }}
            QScrollBar:vertical {{
                background: {BG_SURFACE};
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {BORDER_STRONG};
                border-radius: 3px;
                min-height: 20px;
            }}
        """)

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.setSpacing(12)

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # 加载模型
        self._refresh_models()

    def _refresh_models(self):
        """刷新模型列表"""
        # 清空现有内容
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 本地模型
        self._add_section(f" 本地模型", self._models["local"], "{Lemon.ACCENT_GREEN}")

        # Ollama 模型
        self._add_section(f"🦙 Ollama 模型", self._models["ollama"], "{Lemon.ACCENT_ORANGE}")

        # API 模型
        self._add_section(f"️ API 模型", self._models["api"], "{Lemon.ACCENT_BLUE}")

    def _add_section(self, title: str, models: list, color: str):
        """添加模型分类"""
        # 分类标题
        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        title_label.setStyleSheet(f"""
            color: {color};
            background: transparent;
            padding: 4px 0;
        """)
        self._content_layout.addWidget(title_label)

        if not models:
            empty_label = QLabel("  暂无模型")
            empty_label.setFont(QFont("Microsoft YaHei", 9))
            empty_label.setStyleSheet(f"color: {TEXT_TERTIARY}; background: transparent;")
            self._content_layout.addWidget(empty_label)
        else:
            for model_id in models:
                btn = QPushButton(model_id)
                btn.setFont(QFont("Microsoft YaHei", 9))
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {BG_SURFACE};
                        color: {TEXT_PRIMARY};
                        border: 1px solid {BORDER_DEFAULT};
                        border-radius: 4px;
                        padding: 6px 12px;
                        text-align: left;
                    }}
                    QPushButton:hover {{
                        background: {BG_SURFACE_HOVER};
                        border-color: {LEMON_ORANGE};
                        color: {LEMON_ORANGE};
                    }}
                """)
                btn.clicked.connect(lambda _, m=model_id: self._on_model_selected(m))
                self._content_layout.addWidget(btn)

        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet(f"background: {BORDER_STRONG}; max-height: 1px;")
        self._content_layout.addWidget(separator)

    def _on_model_selected(self, model_id: str):
        """模型选择"""
        self.model_selected.emit(model_id)
        self.close()

    def _on_refresh(self):
        """刷新按钮"""
        self._refresh_models()

    def set_models(self, local: list, ollama: list, api: list):
        """设置模型列表"""
        self._models["local"] = local
        self._models["ollama"] = ollama
        self._models["api"] = api
        self._refresh_models()

    def show_at(self, pos, anchor_rect=None):
        """在指定位置显示

        ★ v4.7.x: 模型选择弹窗改为固定向上延伸，
        弹窗底部对齐按钮顶部，避免底部被截断导致无法选择模型。
        若上方空间不足，则顶部贴紧屏幕可用区上边缘。
        """
        popup_h = self.height() or 400
        popup_w = self.width() or 320

        x = pos.x()
        y = pos.y()

        if anchor_rect is not None:
            screen = QApplication.screenAt(anchor_rect.center())
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen is not None:
                screen_rect = screen.availableGeometry()

                # 强制向上：弹窗底部贴在按钮顶部，列表向上展开
                y = anchor_rect.top() - popup_h
                # 上方超出屏幕则贴顶部，至少保证可见
                if y < screen_rect.top():
                    y = screen_rect.top()

                # 水平方向以按钮中心为基准，再夹紧到屏幕内
                center_x = anchor_rect.center().x() - popup_w // 2
                x = max(screen_rect.left(), min(center_x, screen_rect.right() - popup_w))

        self.move(x, y)
        self.show()


class EngineModeSelector(QWidget):
    """模式选择器 — 模式按钮 + 模型选择 + 状态指示灯

    ★ v4.0: 重构为 LemonCode / Code / Agent 三种模式
    ★ v4.1.7: 扩展为四段 — 新增 Solo 段（IDE Solo，纯编辑无任何 Agent）
    ★ v4.1.9: 收敛为两段 — NATIVE / HOST（用户决策方案甲，去掉语义混淆的 Solo）
    ★ v4.0: 集成模型选择弹出面板

    信号:
        mode_changed(str): 模式变化，值为 "native"/"host"
        model_changed(str): 模型变化，值为模型ID
    """

    mode_changed = pyqtSignal(str)
    model_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = "native"   # ★ v4.1.10: 收敛默认模式（原 "lemoncode"）
        self._current_model = "auto"
        self._engine_status = {}  # {engine_name: bool}
        self._model_popup = None
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 标签
        label = QLabel("模式")
        label.setFont(QFont("Microsoft YaHei", 10))
        label.setStyleSheet(f"color: {TEXT_TERTIARY}; background: transparent; border: none;")
        layout.addWidget(label)

        # 模式按钮（两按钮）★ v4.1.9: 收敛为 NATIVE / HOST 两段
        # ★ v3.81: 字号 9 -> 11，高度 26 -> 30，按钮更显眼
        # ★ v4.1.9: 英文大写（与设置面板 NATIVE/HOST 滑动开关对齐）
        self.buttons = {}
        for mode_id, text in [
            ("native", "NATIVE"),
            ("host", "HOST"),
        ]:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setMinimumWidth(86)   # ★ 略宽一点，容纳英文大写
            btn.setFont(QFont("Microsoft YaHei", 11, QFont.DemiBold))
            btn.setCursor(Qt.PointingHandCursor)

            # ★ v4.1.9: tooltip 携带品牌名
            tooltips = {
                "native": "NATIVE 模式 · Native Agent\nLemonCode 本体 Agent：自研引擎栈（Ollama/DeepSeek/本地模型）",
                "host": "HOST 模式 · Host Agent\n外部 Agent 夺舍：连接外部 Agent（MiMo Code / Aider / OpenCode / ...）作为算力",
            }
            btn.setToolTip(tooltips.get(mode_id, ""))

            btn.clicked.connect(lambda checked, m=mode_id: self._on_click(m))
            self.buttons[mode_id] = btn
            layout.addWidget(btn)

        # 分隔符
        sep = QLabel("|")
        sep.setStyleSheet(f"color: {BORDER_STRONG}; background: transparent; border: none;")
        sep.setFixedWidth(10)
        sep.setAlignment(Qt.AlignCenter)
        layout.addWidget(sep)

        # 模型选择按钮
        self.model_btn = QPushButton("模型: 自动")
        self.model_btn.setFixedHeight(26)
        self.model_btn.setMinimumWidth(80)
        self.model_btn.setFont(QFont("Microsoft YaHei", 9))
        self.model_btn.setCursor(Qt.PointingHandCursor)
        self.model_btn.setToolTip("点击选择模型")
        self.model_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
                padding: 0 10px;
            }}
            QPushButton:hover {{
                background: {BG_SURFACE_HOVER};
                border-color: {LEMON_ORANGE};
                color: {LEMON_ORANGE};
            }}
        """)
        self.model_btn.clicked.connect(self._on_model_btn_click)
        layout.addWidget(self.model_btn)

        # 状态指示灯
        self.status_label = QLabel("●")
        self.status_label.setFixedSize(16, 16)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setToolTip("引擎状态")
        layout.addWidget(self.status_label)

        # 默认选中 NATIVE（★ v4.1.10: 原 "lemoncode" 键已收敛为 "native"）
        self.buttons["native"].setChecked(True)
        self._update_style()

        # ★ v4.1.14: 顶部"模型按钮 + 状态灯"冗余入口 — 提供隐藏接口，
        # 让 main_window 决定显示与否。底部 BottomPanel 已经承担模型选择职责，
        # 避免一个模型名在两个 UI 入口里漂移。
        self._model_selector_widgets = [self.model_btn, sep, self.status_label]

    def set_model_selector_visible(self, visible: bool):
        """控制"模型按钮 + 状态灯"的可见性。
        默认 False（顶部只显示模式按钮），底部栏已承担模型入口。"""
        for w in self._model_selector_widgets:
            try:
                w.setVisible(visible)
            except Exception:
                pass

    def _on_click(self, mode: str):
        """按钮点击"""
        self._current = mode
        for m, btn in self.buttons.items():
            btn.setChecked(m == mode)
        self._update_style()
        self.mode_changed.emit(mode)

    def _on_model_btn_click(self):
        """模型选择按钮点击"""
        if self._model_popup is None:
            self._model_popup = ModelListPopup(self)
            self._model_popup.model_selected.connect(self._on_model_selected)

        # 计算弹出位置（在按钮下方；空间不足时 show_at 自动向上翻转）
        btn_rect = self.model_btn.rect()
        anchor_rect = self.model_btn.mapToGlobal(btn_rect.topLeft())
        anchor_rect = QRect(
            anchor_rect.x(), anchor_rect.y(),
            btn_rect.width(), btn_rect.height()
        )
        pos = self.model_btn.mapToGlobal(self.model_btn.rect().bottomLeft())
        self._model_popup.show_at(pos, anchor_rect)

    def _on_model_selected(self, model_id: str):
        """模型选择"""
        self._current_model = model_id
        self.model_btn.setText(f"模型: {model_id}")
        self.model_changed.emit(model_id)

    def _update_style(self):
        """更新按钮样式"""
        for mode_id, btn in self.buttons.items():
            if mode_id == self._current:
                # 不同模式用不同颜色（★ v4.1.10: 收敛为 native/host 两段）
                if mode_id == "native":
                    accent = COLOR_BLUE
                elif mode_id == "host":
                    accent = COLOR_PURPLE
                else:
                    accent = LEMON_ORANGE

                # ★ v3.81: NATIVE 选中状态更显眼（加重、加 box-shadow 边框、加底色光晕）
                if mode_id == "native":
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {COLOR_BLUE}, stop:1 #2980b9);
                            color: {Lemon.BG};
                            border: 1px solid #5dade2;
                            border-radius: {RADIUS_MD};
                            padding: 0 14px;
                            font-weight: 800;
                            font-size: 12px;
                        }}
                    """)
                else:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background: {accent};
                            color: {Lemon.BG};
                            border: none;
                            border-radius: {RADIUS_MD};
                            padding: 0 10px;
                            font-weight: 600;
                        }}
                    """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {BG_SURFACE};
                        color: {TEXT_TERTIARY};
                        border: 1px solid {BORDER_STRONG};
                        border-radius: {RADIUS_MD};
                        padding: 0 10px;
                    }}
                    QPushButton:hover {{
                        background: {BG_SURFACE_HOVER};
                        color: {TEXT_PRIMARY};
                        border-color: {LEMON_ORANGE};
                    }}
                    QPushButton:checked {{
                        background: {BG_SURFACE_HOVER};
                    }}
                """)

    def update_engine_status(self, engine_name: str, available: bool):
        """更新引擎在线状态

        Args:
            engine_name: "deepseek" / "ollama" / "mimocode" / "acp" / "auto"
            available: 是否可用
        """
        self._engine_status[engine_name] = available
        self._update_status_light()

    def _update_status_light(self):
        """根据当前模式更新状态灯颜色"""
        target = MODE_TO_ENGINE.get(self._current)

        if target:
            # 固定模式：看指定引擎
            available = self._engine_status.get(target, False)
            # ★ v4.1.10: 收敛为 native/host 两段
            if self._current == "native":
                color = COLOR_BLUE if available else COLOR_RED
            elif self._current == "host":
                color = COLOR_PURPLE if available else COLOR_RED
            else:
                color = COLOR_GREEN if available else COLOR_RED

            tooltip = f"{MODE_LABELS.get(self._current, self._current)} · {MODE_BRAND.get(self._current, '')}: {'在线' if available else '离线'}"
        else:
            # 自动模式：有任一引擎在线即可
            any_online = any(self._engine_status.values())
            color = COLOR_GREEN if any_online else COLOR_RED
            online_engines = [k for k, v in self._engine_status.items() if v]
            tooltip = f"自动模式: {'/'.join(online_engines) if online_engines else '全部离线'}"

        self.status_label.setStyleSheet(
            f"color: {color}; font-size: 14px; background: transparent; border: none;"
        )
        self.status_label.setToolTip(tooltip)

    def get_current_mode(self) -> str:
        """获取当前模式"""
        return self._current

    def get_current_model(self) -> str:
        """获取当前模型"""
        return self._current_model

    def get_engine_name(self) -> str:
        """获取当前模式对应的内部引擎名"""
        return MODE_TO_ENGINE.get(self._current, "auto")

    def set_models(self, local: list, ollama: list, api: list):
        """设置模型列表（供外部调用）"""
        if self._model_popup is None:
            self._model_popup = ModelListPopup(self)
            self._model_popup.model_selected.connect(self._on_model_selected)
        self._model_popup.set_models(local, ollama, api)
