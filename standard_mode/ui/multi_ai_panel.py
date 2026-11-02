# -*- coding: utf-8 -*-
"""
Lemon Code Agent — 多AI协同模式
===================================
设计要点：
- 左栏：文件资源管理器（与主页面一致）
- 中栏：可滚动AI窗口网格（支持任意数量AI窗口）+ 任务统计面板 + AI性能对比图
- 右栏：代码编辑器 + 输出区域
- 底部：统一状态栏 + 命令输入
- 星空背景 + 流星效果（风格统一）
- Lemon Code Logo
- 真实AI连接测试 + 性能追踪 + Token用量统计 + AI排名
"""

from typing import Dict, List, Optional
from datetime import datetime
import os
import sys
import threading
import time
import requests

# ★ v3.48: 统一 AI 调用入口
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.engine_manager import get_engine_manager, chat as engine_chat

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QComboBox, QLineEdit, QSplitter,
    QTextEdit, QProgressBar, QTreeWidget, QTreeWidgetItem,
    QPlainTextEdit, QGridLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy, QToolButton
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush, QLinearGradient

from ui.theme import (
    BG_DARK, BG_PANEL, BG_SURFACE, BG_SURFACE_HOVER,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    LEMON_ORANGE, LEMON_YELLOW, LEMON_GOLD,
    SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR,
    BORDER_RADIUS, FONT_FAMILY, BORDER_DEFAULT, BORDER_STRONG,
    RADIUS_SM, RADIUS_MD, RADIUS_LG,
    FONT_SIZE_SM, FONT_SIZE_MD, FONT_SIZE_LG,
    icon_text_html, svg_to_qicon
)
from ui.single_ai_multi_window import StarryBackground
from ui.design.tokens import Lemon


# ============================================================================
# AI连接状态指示器
# ============================================================================

class AIStatusIndicator(QFrame):
    """AI连接状态指示器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        self.setFixedHeight(24)
        self.setStyleSheet(f"QFrame {{ background: transparent; }}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
        layout.addWidget(self.status_dot)

        self.status_text = QLabel("未连接")
        self.status_text.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
        layout.addWidget(self.status_text)
        layout.addStretch()

    def set_connected(self, connected: bool, model: str = ""):
        if connected:
            self.status_dot.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 10px;")
            self.status_text.setText(f"已连接: {model}")
            self.status_text.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 10px;")
        else:
            self.status_dot.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
            self.status_text.setText("未连接")
            self.status_text.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")


# ============================================================================
# AI性能对比可视化图表
# ============================================================================

class AIComparisonChart(QWidget):
    """AI性能对比可视化图表 —— 水平条形图展示各AI的任务完成数、响应时间、Token用量"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Dict[str, dict] = {}
        self.setMinimumHeight(200)
        self.setMaximumHeight(300)

    def set_data(self, data: Dict[str, dict]):
        self._data = data
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(BG_DARK))

        w = self.width()
        if not self._data:
            painter.setPen(QColor(TEXT_TERTIARY))
            painter.setFont(QFont(FONT_FAMILY, 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无AI性能数据，请先连接AI引擎")
            return

        # 标题
        painter.setPen(QColor(LEMON_ORANGE))
        painter.setFont(QFont(FONT_FAMILY, 12, QFont.Bold))
        painter.drawText(12, 26, "AI 性能对比")

        # 三个指标：任务完成数、响应时间、Token用量
        bar_h = 18
        gap = 6
        section_gap = 28
        start_y = 50
        ai_count = len(self._data)

        # 排序：按任务完成数降序
        sorted_ais = sorted(self._data.items(), key=lambda x: x[1].get("tasks_completed", 0), reverse=True)

        # 计算最大值
        max_tasks = max((d.get("tasks_completed", 0) for _, d in sorted_ais), default=1)
        max_tokens = max((d.get("tokens_used", 0) for _, d in sorted_ais), default=1)
        max_resp = max((d.get("avg_response_time", 0) for _, d in sorted_ais), default=1)

        colors = [LEMON_ORANGE, "{Lemon.SYNTAX_FUNCTION}", "{Lemon.SYNTAX_NUMBER}", "{Lemon.SYNTAX_VARIABLE}", "{Lemon.SYNTAX_TYPE}", "{Lemon.SYNTAX_OPERATOR}", "{Lemon.SYNTAX_SELF}", "{Lemon.SYNTAX_NUMBER_ALT}"]

        for idx, (task_id, info) in enumerate(sorted_ais):
            name = info.get("name", task_id)
            color = colors[idx % len(colors)]
            y = start_y + idx * (bar_h * 3 + gap * 2 + section_gap)
            if y > self.height() - 20:
                break

            # AI名称
            painter.setPen(QColor(TEXT_PRIMARY))
            painter.setFont(QFont(FONT_FAMILY, 10, QFont.Bold))
            connected = info.get("connected", False)
            status_icon = "●" if connected else "○"
            painter.drawText(12, y - 2, f"{status_icon} {name}")

            # 排名标记
            if idx < 3:
                rank_emoji = ["🥇", "🥈", "🥉"][idx]
                painter.drawText(160, y - 2, rank_emoji)

            # 任务完成数
            y1 = y + 14
            painter.setPen(QColor(TEXT_TERTIARY))
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(12, y1 + 8, "任务")

            tasks = info.get("tasks_completed", 0)
            bar_w = max(2, int((w - 80) * tasks / max(max_tasks, 1)))

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(BG_PANEL))
            painter.drawRoundedRect(50, y1, w - 80, bar_h, 3, 3)

            gradient = QLinearGradient(50, 0, 50 + bar_w, 0)
            gradient.setColorAt(0, QColor(color))
            gradient.setColorAt(1, QColor(color).lighter(140))
            painter.setBrush(gradient)
            painter.drawRoundedRect(50, y1, bar_w, bar_h, 3, 3)

            painter.setPen(QColor(TEXT_PRIMARY))
            painter.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
            painter.drawText(50 + bar_w + 4, y1 + bar_h - 4, str(tasks))

            # 响应时间
            y2 = y1 + bar_h + gap
            painter.setPen(QColor(TEXT_TERTIARY))
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(12, y2 + 8, "响应")

            resp_time = info.get("avg_response_time", 0)
            # 响应时间：越短越好，反转比例
            resp_bar = max(2, int((w - 80) * (1 - min(resp_time / max(max_resp, 1), 1))))

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(BG_PANEL))
            painter.drawRoundedRect(50, y2, w - 80, bar_h, 3, 3)

            painter.setBrush(QColor(LEMON_YELLOW))
            painter.drawRoundedRect(50, y2, resp_bar, bar_h, 3, 3)

            painter.setPen(QColor(TEXT_PRIMARY))
            painter.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
            painter.drawText(50 + resp_bar + 4, y2 + bar_h - 4, f"{resp_time:.1f}s")

            # Token用量
            y3 = y2 + bar_h + gap
            painter.setPen(QColor(TEXT_TERTIARY))
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(12, y3 + 8, "Token")

            tokens = info.get("tokens_used", 0)
            tok_bar = max(2, int((w - 80) * tokens / max(max_tokens, 1)))

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(BG_PANEL))
            painter.drawRoundedRect(50, y3, w - 80, bar_h, 3, 3)

            painter.setBrush(QColor("{Lemon.SYNTAX_OPERATOR}"))
            painter.drawRoundedRect(50, y3, tok_bar, bar_h, 3, 3)

            painter.setPen(QColor(TEXT_PRIMARY))
            painter.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
            tok_str = f"{tokens/1000:.1f}K" if tokens >= 1000 else str(tokens)
            painter.drawText(50 + tok_bar + 4, y3 + bar_h - 4, tok_str)


# ============================================================================
# 单个AI任务窗口
# ============================================================================

class MultiAIWindow(QFrame):
    """单个AI任务窗口 — 完整的AI交互窗口"""

    clicked = pyqtSignal(str)
    message_sent = pyqtSignal(str, str)
    ai_connected = pyqtSignal(str, bool)  # task_id, connected

    AI_PROVIDERS = [
        ("ollama", "Ollama 本地", ["qwen3.5:4b", "qwen3.5:9b", "deepseek-r1:8b"]),
        ("mimocode", "Lemon Code", ["mimo-v1", "mimo-v2"]),
        ("deepseek", "DeepSeek", ["deepseek-chat", "deepseek-coder"]),
        ("lmstudio", "LM Studio", ["custom"]),
    ]

    def __init__(self, task_id: str, task_name: str, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.task_name = task_name
        self.is_selected = False
        self._connected = False
        self._tokens_used = 0
        self._response_times = []  # 记录每次响应时间
        self._collapsed = False
        self._init_ui()

    def _init_ui(self):
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            MultiAIWindow {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
            MultiAIWindow:hover {{
                border-color: {LEMON_ORANGE};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # 标题行
        header_layout = QHBoxLayout()
        title = QLabel(icon_text_html("bot", self.task_name, color=TEXT_PRIMARY))
        title.setFont(QFont(FONT_FAMILY, 12, QFont.Bold))
        title.setStyleSheet(f"color: {TEXT_PRIMARY};")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # 折叠/展开按钮
        self.collapse_btn = QPushButton("▼")
        self.collapse_btn.setFixedSize(22, 22)
        self.collapse_btn.setToolTip("折叠/展开窗口")
        self.collapse_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE}; color: {TEXT_SECONDARY};
                border: none; border-radius: {RADIUS_SM}; font-size: 10px;
            }}
            QPushButton:hover {{ color: {LEMON_ORANGE}; }}
        """)
        self.collapse_btn.clicked.connect(self._toggle_collapse)
        header_layout.addWidget(self.collapse_btn)

        # 删除按钮
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: none;
                font-size: 12px;
            }}
            QPushButton:hover {{
                color: {ERROR_COLOR};
            }}
        """)
        close_btn.clicked.connect(lambda: self.hide())
        header_layout.addWidget(close_btn)
        layout.addLayout(header_layout)

        # 状态指示器
        self.status = AIStatusIndicator()
        layout.addWidget(self.status)

        # === 可折叠内容区 ===
        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(self._content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        # AI提供商选择
        provider_layout = QHBoxLayout()
        provider_label = QLabel("引擎:")
        provider_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
        provider_layout.addWidget(provider_label)

        self.provider_combo = QComboBox()
        for pid, pname, _ in self.AI_PROVIDERS:
            self.provider_combo.addItem(pname, pid)
        self.provider_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 3px 6px;
                font-size: 11px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                selection-background-color: {BG_SURFACE};
            }}
        """)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_layout.addWidget(self.provider_combo, stretch=1)
        content_layout.addLayout(provider_layout)

        # 模型选择
        model_layout = QHBoxLayout()
        model_label = QLabel("模型:")
        model_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
        model_layout.addWidget(model_label)

        self.model_combo = QComboBox()
        self._update_models()
        self.model_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 3px 6px;
                font-size: 11px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                selection-background-color: {BG_SURFACE};
            }}
        """)
        model_layout.addWidget(self.model_combo, stretch=1)
        content_layout.addLayout(model_layout)

        # 连接/测试按钮
        btn_layout = QHBoxLayout()
        self.connect_btn = QPushButton("🔗 连接测试")
        self.connect_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE};
                color: #000;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 5px 14px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {LEMON_YELLOW};
            }}
            QPushButton:disabled {{
                background: {BORDER_DEFAULT};
                color: {TEXT_TERTIARY};
            }}
        """)
        self.connect_btn.clicked.connect(self._on_connect_test)
        btn_layout.addWidget(self.connect_btn)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 5px 10px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                border-color: {WARNING_COLOR};
                color: {WARNING_COLOR};
            }}
        """)
        self.clear_btn.clicked.connect(lambda: self.output_area.clear())
        btn_layout.addWidget(self.clear_btn)
        content_layout.addLayout(btn_layout)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setFixedHeight(4)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background: {BG_DARK};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {LEMON_ORANGE};
                border-radius: 2px;
            }}
        """)
        self.progress.setVisible(False)
        content_layout.addWidget(self.progress)

        # 输出区域
        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_DARK};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 8px;
                font-family: {FONT_FAMILY};
                font-size: 11px;
            }}
        """)
        self.output_area.setMinimumHeight(100)
        self.output_area.setPlaceholderText(f"[{self.task_name}] 等待AI连接...")
        content_layout.addWidget(self.output_area, stretch=1)

        # 输入区
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入命令...")
        self.input_field.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 5px 10px;
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border-color: {LEMON_ORANGE};
            }}
        """)
        self.input_field.returnPressed.connect(self._on_send)
        input_layout.addWidget(self.input_field, stretch=1)

        self.send_btn = QPushButton("发送")
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE};
                color: #000;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 5px 12px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {LEMON_YELLOW};
            }}
            QPushButton:disabled {{
                background: {BG_SURFACE};
                color: {TEXT_TERTIARY};
            }}
        """)
        self.send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(self.send_btn)
        content_layout.addLayout(input_layout)

        layout.addWidget(self._content_widget)

    def _on_provider_changed(self, index):
        self._update_models()

    def _toggle_collapse(self):
        """折叠/展开AI窗口"""
        self._collapsed = not self._collapsed
        self._content_widget.setVisible(not self._collapsed)
        self.collapse_btn.setText("▶" if self._collapsed else "▼")
        if self._collapsed:
            self.setMaximumHeight(80)
        else:
            self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX

    def _update_models(self):
        self.model_combo.clear()
        pid = self.provider_combo.currentData()
        for provider_id, _, models in self.AI_PROVIDERS:
            if provider_id == pid:
                for model in models:
                    self.model_combo.addItem(model)
                break

    def _on_connect_test(self):
        """真实测试AI连接"""
        provider = self.provider_combo.currentData()
        model = self.model_combo.currentText()

        self.connect_btn.setText("测试中...")
        self.connect_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.output_area.append(f"[系统] 正在测试连接: {provider} / {model}...")

        if provider == "ollama":
            threading.Thread(target=self._test_ollama_connection, args=(model,), daemon=True).start()
        elif provider == "deepseek":
            threading.Thread(target=self._test_deepseek_connection, daemon=True).start()
        elif provider == "mimocode":
            threading.Thread(target=self._test_mimocode_connection, daemon=True).start()
        elif provider == "lmstudio":
            threading.Thread(target=self._test_lmstudio_connection, daemon=True).start()
        else:
            QTimer.singleShot(1000, self._on_connection_failed)

    def _test_ollama_connection(self, model: str):
        """测试Ollama连接（使用 EngineManager）"""
        try:
            engine = get_engine_manager()
            if not engine._engines.get("ollama"):
                engine.initialize()
            ollama = engine._engines.get("ollama")
            if ollama and ollama.is_available():
                models = ollama.list_models()
                if any(model in m for m in models):
                    self._on_connection_success(model)
                else:
                    self.output_area.append(f"[警告] 模型 {model} 未找到，可用模型: {', '.join(models[:5])}")
                    self._on_connection_failed()
            else:
                self._on_connection_failed()
        except Exception as e:
            self.output_area.append(f"[错误] Ollama连接失败: {e}")
            self._on_connection_failed()

    def _test_deepseek_connection(self):
        """测试DeepSeek连接"""
        try:
            import os
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if not api_key:
                self.output_area.append("[错误] 未设置 DEEPSEEK_API_KEY 环境变量")
                self._on_connection_failed()
                return
            resp = requests.get("https://api.deepseek.com/v1/models", 
                              headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
            if resp.status_code == 200:
                self._on_connection_success("deepseek-chat")
            else:
                self._on_connection_failed()
        except Exception as e:
            self.output_area.append(f"[错误] DeepSeek连接失败: {e}")
            self._on_connection_failed()

    def _test_mimocode_connection(self):
        """测试Lemon Code连接"""
        try:
            resp = requests.get("http://localhost:4097/api/status", timeout=3)
            if resp.status_code == 200:
                self._on_connection_success("mimo-v1")
            else:
                self._on_connection_failed()
        except Exception:
            try:
                resp = requests.get("http://localhost:4097/", timeout=2)
                if resp.status_code < 500:
                    self._on_connection_success("mimo-v1")
                else:
                    self._on_connection_failed()
            except Exception as e:
                self.output_area.append(f"[错误] Lemon Code 服务未运行: {e}")
                self._on_connection_failed()

    def _test_lmstudio_connection(self):
        """测试LM Studio连接"""
        try:
            resp = requests.get("http://localhost:1234/v1/models", timeout=5)
            if resp.status_code == 200:
                self._on_connection_success("custom")
            else:
                self._on_connection_failed()
        except Exception as e:
            self.output_area.append(f"[错误] LM Studio连接失败: {e}")
            self._on_connection_failed()

    def _on_connection_success(self, model: str):
        self._connected = True
        self.connect_btn.setText("✓ 已连接")
        self.connect_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.set_connected(True, model)
        self.output_area.append(f"[系统] ✓ 连接成功: {model}")
        self.ai_connected.emit(self.task_id, True)

    def _on_connection_failed(self):
        self._connected = False
        self.connect_btn.setText("🔗 重试连接")
        self.connect_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.set_connected(False)
        self.output_area.append("[系统] ✗ 连接失败，请检查服务是否运行")
        self.ai_connected.emit(self.task_id, False)

    def _on_send(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.output_area.append(f"[用户] {datetime.now().strftime('%H:%M:%S')}")
        self.output_area.append(f"  {text}")
        self.message_sent.emit(self.task_id, text)
        self.input_field.clear()

        if self._connected:
            # 人性化设计：禁用发送按钮，显示"思考中..."
            self.send_btn.setEnabled(False)
            self.send_btn.setText("思考中...")
            self.input_field.setEnabled(False)
            self.output_area.append(f"[AI] 处理中...")
            provider = self.provider_combo.currentData()
            model = self.model_combo.currentText()
            threading.Thread(target=self._call_ai_api, args=(text, provider, model), daemon=True).start()
        else:
            self.output_area.append(f"[AI] 未连接AI引擎，请先点击连接测试")

    def _call_ai_api(self, prompt: str, provider: str, model: str):
        """真实调用AI API"""
        try:
            if provider == "ollama":
                self._call_ollama_api(prompt, model)
            elif provider == "deepseek":
                self._call_deepseek_api(prompt)
            elif provider == "mimocode":
                self._call_mimocode_api(prompt)
            elif provider == "lmstudio":
                self._call_lmstudio_api(prompt, model)
        except Exception as e:
            self.append_response(f"[错误] API调用失败: {e}")

    def _call_ollama_api(self, prompt: str, model: str):
        """调用Ollama API生成回复（使用 EngineManager）"""
        start_time = time.time()
        try:
            result = engine_chat(prompt, engine="ollama", model=model)
            elapsed = time.time() - start_time
            self._response_times.append(elapsed)
            if result:
                self.append_response(result)
            else:
                self.append_response("[警告] 模型返回空内容")
        except Exception as e:
            self._response_times.append(time.time() - start_time)
            error_msg = str(e)
            if "Connection" in error_msg or "connect" in error_msg.lower():
                self.append_response("[错误] 无法连接到Ollama服务，请确保Ollama正在运行")
            elif "Timeout" in error_msg or "timeout" in error_msg.lower():
                self.append_response("[错误] 请求超时，请检查模型是否正常运行")
            else:
                self.append_response(f"[错误] Ollama调用异常: {e}")

    def _call_deepseek_api(self, prompt: str):
        """调用DeepSeek API"""
        try:
            import os
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if not api_key:
                self.append_response("[错误] 未设置 DEEPSEEK_API_KEY")
                return
            resp = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "stream": False},
                timeout=120
            )
            if resp.status_code == 200:
                data = resp.json()
                response = data["choices"][0]["message"]["content"]
                self.append_response(response)
            else:
                self.append_response(f"[错误] DeepSeek API返回: {resp.status_code}")
        except Exception as e:
            self.append_response(f"[错误] DeepSeek调用异常: {e}")

    def _call_mimocode_api(self, prompt: str):
        """调用MIMO Code API"""
        try:
            resp = requests.post(
                "http://localhost:4097/api/chat",
                json={"message": prompt},
                timeout=60
            )
            if resp.status_code == 200:
                data = resp.json()
                response = data.get("response", data.get("content", str(data)))
                self.append_response(str(response))
            else:
                self.append_response(f"[提示] MIMO Code服务未就绪 (状态码: {resp.status_code})")
        except Exception:
            self.append_response("[提示] MIMO Code服务未运行，请启动Lemon Code")

    def _call_lmstudio_api(self, prompt: str, model: str):
        """调用LM Studio API生成回复"""
        start_time = time.time()
        try:
            resp = requests.post(
                "http://localhost:1234/v1/chat/completions",
                json={
                    "model": model or "auto",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "temperature": 0.7,
                    "max_tokens": 512,
                },
                timeout=120
            )
            elapsed = time.time() - start_time
            self._response_times.append(elapsed)

            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    response = choices[0].get("message", {}).get("content", "")
                    usage = data.get("usage", {})
                    self._tokens_used += usage.get("total_tokens", 0)
                    if response:
                        self.append_response(response)
                    else:
                        self.append_response("[警告] LM Studio 返回空内容")
                else:
                    self.append_response("[警告] LM Studio 返回空choices")
            else:
                self.append_response(f"[错误] LM Studio 返回状态码: {resp.status_code}")
        except requests.exceptions.Timeout:
            self._response_times.append(time.time() - start_time)
            self.append_response("[错误] LM Studio 请求超时，请检查LM Studio是否正常运行")
        except requests.exceptions.ConnectionError:
            self._response_times.append(time.time() - start_time)
            self.append_response("[错误] 无法连接LM Studio (localhost:1234)，请确认LM Studio已启动本地服务器")
        except Exception as e:
            self._response_times.append(time.time() - start_time)
            self.append_response(f"[错误] LM Studio调用异常: {e}")

    def mousePressEvent(self, event):
        self.clicked.emit(self.task_id)
        super().mousePressEvent(event)

    def send_to_ai(self, message: str):
        """外部调用发送消息到AI"""
        if not self._connected:
            self.append_response("[错误] 未连接AI引擎")
            return
        provider = self.provider_combo.currentData()
        model = self.model_combo.currentText()
        self.output_area.append(f"[外部] {datetime.now().strftime('%H:%M:%S')}")
        self.output_area.append(f"  {message}")
        threading.Thread(target=self._call_ai_api, args=(message, provider, model), daemon=True).start()

    def append_response(self, response: str):
        """追加AI响应到输出区域"""
        self.output_area.append(f"[AI] {datetime.now().strftime('%H:%M:%S')}")
        self.output_area.append(f"  {response}")
        # 滚动到底部
        scrollbar = self.output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        # 人性化设计：恢复发送按钮状态
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        self.input_field.setEnabled(True)
        self.input_field.setFocus()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        if selected:
            self.setStyleSheet(f"""
                MultiAIWindow {{
                    background-color: {BG_SURFACE};
                    border: 2px solid {LEMON_ORANGE};
                    border-radius: {RADIUS_MD};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                MultiAIWindow {{
                    background-color: {BG_PANEL};
                    border: 1px solid {BORDER_DEFAULT};
                    border-radius: {RADIUS_MD};
                }}
            """)

    def get_config(self) -> dict:
        avg_time = sum(self._response_times) / len(self._response_times) if self._response_times else 0
        return {
            "provider": self.provider_combo.currentData(),
            "model": self.model_combo.currentText(),
            "connected": self._connected,
            "tokens_used": self._tokens_used,
            "avg_response_time": avg_time,
            "response_times": self._response_times,
        }


# ============================================================================
# AI任务统计面板
# ============================================================================

class AITaskStatsPanel(QFrame):
    """AI任务统计面板 —— 显示每个AI的任务完成情况、响应时间、Token消耗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stats: Dict[str, dict] = {}
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"""
            AITaskStatsPanel {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel(icon_text_html("chart", "AI 任务统计", color=LEMON_ORANGE))
        title.setFont(QFont(FONT_FAMILY, 12, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE};")
        header.addWidget(title)
        header.addStretch()

        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE}; color: {TEXT_SECONDARY};
                border: none; border-radius: {RADIUS_SM}; font-size: 12px;
            }}
            QPushButton:hover {{ background: {BG_SURFACE_HOVER}; color: {LEMON_ORANGE}; }}
        """)
        refresh_btn.clicked.connect(self._refresh_table)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["排名", "AI名称", "引擎", "模型", "完成任务", "响应时间", "Token", "状态"])
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background: {BG_DARK};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                font-size: 10px;
                gridline-color: {BORDER_DEFAULT};
            }}
            QTableWidget::item {{ padding: 4px 8px; }}
            QTableWidget::item:selected {{ background: {BG_SURFACE}; color: {LEMON_ORANGE}; }}
            QHeaderView::section {{
                background: {BG_PANEL};
                color: {TEXT_TERTIARY};
                border: none;
                border-bottom: 1px solid {BORDER_STRONG};
                padding: 4px 8px;
                font-size: 9px;
                font-weight: bold;
            }}
        """)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMaximumHeight(200)
        layout.addWidget(self.table)

    def update_stats(self, stats: Dict[str, dict]):
        self._stats = stats
        self._refresh_table()

    def _refresh_table(self):
        self.table.setRowCount(len(self._stats))
        # 按任务完成数降序排序
        sorted_stats = sorted(self._stats.items(), key=lambda x: x[1].get("tasks_completed", 0), reverse=True)
        rank_icons = ["🥇", "🥈", "🥉"]

        for i, (task_id, info) in enumerate(sorted_stats):
            rank = f"{rank_icons[i]}" if i < 3 else str(i + 1)
            self.table.setItem(i, 0, QTableWidgetItem(rank))
            self.table.setItem(i, 1, QTableWidgetItem(info.get("name", task_id)))
            self.table.setItem(i, 2, QTableWidgetItem(info.get("engine", "N/A")))
            self.table.setItem(i, 3, QTableWidgetItem(info.get("model", "N/A")))
            self.table.setItem(i, 4, QTableWidgetItem(str(info.get("tasks_completed", 0))))
            resp_time = info.get("avg_response_time", 0)
            self.table.setItem(i, 5, QTableWidgetItem(f"{resp_time:.1f}s" if resp_time else "N/A"))
            tokens = info.get("tokens_used", 0)
            tok_str = f"{tokens/1000:.1f}K" if tokens >= 1000 else str(tokens)
            self.table.setItem(i, 6, QTableWidgetItem(tok_str))
            status_item = QTableWidgetItem("✓ 已连接" if info.get("connected") else "未连接")
            if info.get("connected"):
                status_item.setForeground(QColor(SUCCESS_COLOR))
            else:
                status_item.setForeground(QColor(TEXT_TERTIARY))
            self.table.setItem(i, 7, status_item)


# ============================================================================
# 文件资源管理器面板
# ============================================================================

class FileExplorerPanel(QFrame):
    """文件资源管理器面板（与主页面风格一致）"""

    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self.setStyleSheet(f"""
            FileExplorerPanel {{
                background-color: rgba(0, 0, 0, 0.5);
                border-right: 1px solid {BORDER_DEFAULT};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题
        header = QFrame()
        header.setStyleSheet(f"background: {BG_PANEL};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)

        title = QLabel(icon_text_html("folder", "文件资源", color=LEMON_ORANGE))
        title.setFont(QFont(FONT_FAMILY, 13, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE};")
        header_layout.addWidget(title)
        header_layout.addStretch()

        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE};
                color: {TEXT_SECONDARY};
                border: none;
                border-radius: {RADIUS_SM};
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: {BG_SURFACE_HOVER};
                color: {LEMON_ORANGE};
            }}
        """)
        refresh_btn.clicked.connect(self._refresh_tree)
        header_layout.addWidget(refresh_btn)
        layout.addWidget(header)

        # 文件树
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: {BG_DARK};
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {BORDER_STRONG};
                border-radius: 3px;
            }}
        """)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background: transparent;
                color: {TEXT_SECONDARY};
                border: none;
                font-size: 11px;
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
        self.tree.itemClicked.connect(self._on_item_clicked)

        self._refresh_tree()
        self.scroll.setWidget(self.tree)
        layout.addWidget(self.scroll, stretch=1)

    def _refresh_tree(self):
        """刷新文件树 — 扫描真实项目文件系统"""
        self.tree.clear()
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._project_root = project_root

        # 扫描项目目录结构
        ignore_dirs = {'.venv', '.git', '__pycache__', '.mimo_snapshots', 'node_modules',
                       'competition_archive', '.mimo', 'dist', 'build', '.mimo_user_data'}
        ignore_ext = {'.pyc', '.pyo', '.pyd', '.egg-info'}

        def _add_directory(parent_item, dir_path, dir_name, depth=0):
            """递归添加目录"""
            if depth > 3 or dir_name in ignore_dirs:
                return
            folder_item = QTreeWidgetItem(parent_item)
            folder_item.setText(0, dir_name)
            folder_item.setIcon(0, svg_to_qicon("folder", size=16, color=TEXT_SECONDARY))
            folder_item.setData(0, Qt.UserRole, os.path.join(dir_path, dir_name))
            folder_item.setToolTip(0, os.path.join(dir_path, dir_name))

            try:
                full_path = os.path.join(dir_path, dir_name)
                entries = sorted(os.listdir(full_path))
                # 先添加子目录
                for entry in entries:
                    entry_path = os.path.join(full_path, entry)
                    if os.path.isdir(entry_path) and not entry.startswith('.') and entry not in ignore_dirs:
                        _add_directory(folder_item, full_path, entry, depth + 1)
                # 再添加文件
                for entry in entries:
                    entry_path = os.path.join(full_path, entry)
                    if os.path.isfile(entry_path) and not entry.startswith('.'):
                        _, ext = os.path.splitext(entry)
                        if ext not in ignore_ext:
                            file_item = QTreeWidgetItem(folder_item)
                            file_item.setText(0, entry)
                            file_item.setIcon(0, svg_to_qicon("file_default", size=16, color=TEXT_TERTIARY))
                            file_item.setData(0, Qt.UserRole, os.path.join(full_path, entry))
                            file_item.setToolTip(0, os.path.join(full_path, entry))
            except PermissionError:
                pass

        # 添加项目根目录
        root_item = QTreeWidgetItem(self.tree)
        root_name = os.path.basename(project_root)
        root_item.setText(0, root_name)
        root_item.setIcon(0, svg_to_qicon("folder_open", size=16, color=TEXT_SECONDARY))
        root_item.setData(0, Qt.UserRole, project_root)

        try:
            entries = sorted(os.listdir(project_root))
            for entry in entries:
                if entry.startswith('.') or entry in ignore_dirs:
                    continue
                full_path = os.path.join(project_root, entry)
                if os.path.isdir(full_path):
                    _add_directory(root_item, project_root, entry, 1)
                elif os.path.isfile(full_path):
                    _, ext = os.path.splitext(entry)
                    if ext not in ignore_ext:
                        file_item = QTreeWidgetItem(root_item)
                        file_item.setText(0, f"📄 {entry}")
                        file_item.setData(0, Qt.UserRole, full_path)
        except PermissionError:
            pass

        self.tree.expandAll()

    def _on_item_clicked(self, item, column):
        data = item.data(0, Qt.UserRole)
        if data and os.path.isfile(str(data)):
            self.file_selected.emit(data)


# ============================================================================
# 代码编辑器面板
# ============================================================================

class CodeEditorPanel(QFrame):
    """代码编辑器面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_file = None
        self._init_ui()

    def _init_ui(self):
        self.setMinimumWidth(300)
        self.setStyleSheet(f"""
            CodeEditorPanel {{
                background-color: rgba(0, 0, 0, 0.5);
                border-left: 1px solid {BORDER_DEFAULT};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        header = QFrame()
        header.setStyleSheet(f"background: {BG_PANEL};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)

        title = QLabel(icon_text_html("doc", "代码编辑器", color=LEMON_ORANGE))
        title.setFont(QFont(FONT_FAMILY, 13, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE};")
        header_layout.addWidget(title)

        self.file_name = QLabel("未选择文件")
        self.file_name.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        header_layout.addWidget(self.file_name)
        header_layout.addStretch()

        # 操作按钮
        for action in ["保存", "运行", "格式化"]:
            btn = QPushButton(action)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {BG_SURFACE};
                    color: {TEXT_SECONDARY};
                    border: 1px solid {BORDER_DEFAULT};
                    border-radius: {RADIUS_SM};
                    padding: 3px 8px;
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    border-color: {LEMON_ORANGE};
                    color: {LEMON_ORANGE};
                }}
            """)
            if action == "保存":
                btn.clicked.connect(self._save_file)
            elif action == "运行":
                btn.clicked.connect(self._run_code)
            else:
                btn.clicked.connect(self._format_code)
            header_layout.addWidget(btn)
        layout.addWidget(header)

        # 编辑器
        self.editor = QPlainTextEdit()
        self.editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: none;
                padding: 12px;
                font-family: "Consolas", "Cascadia Code", monospace;
                font-size: 12px;
                line-height: 1.6;
            }}
        """)
        self.editor.setPlaceholderText("选择左侧文件开始编辑...")
        layout.addWidget(self.editor, stretch=1)

        # 输出区域
        output_header = QFrame()
        output_header.setStyleSheet(f"background: {BG_PANEL}; border-top: 1px solid {BORDER_DEFAULT};")
        output_header_layout = QHBoxLayout(output_header)
        output_header_layout.setContentsMargins(12, 6, 12, 6)
        output_title = QLabel("📡 输出")
        output_title.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        output_header_layout.addWidget(output_title)
        output_header_layout.addStretch()
        layout.addWidget(output_header)

        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setMaximumHeight(120)
        self.output_area.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_DARK};
                color: {TEXT_SECONDARY};
                border: none;
                padding: 8px;
                font-family: "Consolas", monospace;
                font-size: 10px;
            }}
        """)
        layout.addWidget(self.output_area)

    def _save_file(self):
        """保存文件"""
        if not self._current_file:
            self.output_area.append("[系统] 请先选择文件")
            return
        try:
            content = self.editor.toPlainText()
            with open(self._current_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.output_area.append(f"[系统] 已保存: {os.path.basename(self._current_file)}")
        except Exception as e:
            self.output_area.append(f"[系统] 保存失败: {e}")

    def _run_code(self):
        """运行代码"""
        if not self._current_file:
            self.output_area.append("[系统] 请先选择文件")
            return
        self.output_area.append(f"[系统] 运行: {os.path.basename(self._current_file)}...")
        try:
            import subprocess
            result = subprocess.run(
                [r".\.venv\Scripts\python.exe", self._current_file],
                capture_output=True, text=True, timeout=30,
                cwd=os.path.dirname(os.path.abspath(__file__)) + "/.."
            )
            if result.stdout:
                self.output_area.append(f"[输出]\n{result.stdout}")
            if result.stderr:
                self.output_area.append(f"[错误]\n{result.stderr}")
            if result.returncode == 0:
                self.output_area.append("[系统] 运行成功")
            else:
                self.output_area.append(f"[系统] 运行失败 (退出码: {result.returncode})")
        except subprocess.TimeoutExpired:
            self.output_area.append("[系统] 运行超时（30秒）")
        except Exception as e:
            self.output_area.append(f"[系统] 运行异常: {e}")

    def _format_code(self):
        """格式化代码"""
        try:
            import autopep8
            content = self.editor.toPlainText()
            formatted = autopep8.fix_code(content)
            self.editor.setPlainText(formatted)
            self.output_area.append("[系统] 代码已格式化")
        except ImportError:
            self.output_area.append("[系统] 未安装autopep8，使用简易格式化")
            # 简易格式化：去除多余空行
            content = self.editor.toPlainText()
            lines = content.split('\n')
            # 去除连续空行
            result = []
            prev_empty = False
            for line in lines:
                if line.strip() == '':
                    if not prev_empty:
                        result.append(line)
                    prev_empty = True
                else:
                    result.append(line)
                    prev_empty = False
            self.editor.setPlainText('\n'.join(result))
            self.output_area.append("[系统] 简易格式化完成")


# ============================================================================
# 底部状态栏
# ============================================================================

class MultiAIStatusBar(QFrame):
    """底部状态栏"""

    command_sent = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        self.setFixedHeight(48)
        self.setStyleSheet(f"""
            MultiAIStatusBar {{
                background-color: {BG_PANEL};
                border-top: 1px solid {BORDER_DEFAULT};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)

        self.status_label = QLabel("✓ 系统就绪")
        self.status_label.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 11px;")
        layout.addWidget(self.status_label)

        self.ai_count = QLabel("AI: 0/4 已连接")
        self.ai_count.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        layout.addWidget(self.ai_count)

        layout.addStretch()

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("全局命令（发送到所有已连接的AI）...")
        self.input_field.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 4px 12px;
                font-size: 11px;
                min-width: 300px;
            }}
            QLineEdit:focus {{
                border-color: {LEMON_ORANGE};
            }}
        """)
        self.input_field.returnPressed.connect(self._on_send)
        layout.addWidget(self.input_field, stretch=1)

        send_btn = QPushButton("广播")
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE};
                color: #000;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 4px 16px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {LEMON_YELLOW};
            }}
        """)
        send_btn.clicked.connect(self._on_send)
        layout.addWidget(send_btn)

    def _on_send(self):
        cmd = self.input_field.text().strip()
        if cmd:
            self.command_sent.emit(cmd)
            self.input_field.clear()

    def update_ai_count(self, count: int, total: int):
        self.ai_count.setText(f"AI: {count}/{total} 已连接")
        if count > 0:
            self.status_label.setText(f"✓ {count}个AI已连接")
            self.status_label.setStyleSheet(f"color: {SUCCESS_COLOR}; font-size: 11px;")


# ============================================================================
# 多AI协同面板（主面板）
# ============================================================================

class MultiAICooperatePanel(QWidget):
    """
    多AI协同模式面板
    
    布局：
    - 左栏：文件资源管理器
    - 中栏：可滚动AI窗口网格 + 任务统计面板
    - 右栏：代码编辑器 + 输出
    - 底部：状态栏 + 全局命令
    - 星空背景全覆盖
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ai_windows: Dict[str, MultiAIWindow] = {}
        self.current_task_id = "ai-1"
        self.serve_bridge = None
        self._task_completed_count: Dict[str, int] = {}
        self._response_times: Dict[str, list] = {}
        self._init_ui()
        self._create_ai_windows()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bg = StarryBackground()
        bg_layout = QVBoxLayout(bg)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        bg_layout.setSpacing(0)

        # ========== 标题栏 ==========
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
        logo = QLabel("🍋 Lemon Code")
        logo.setFont(QFont(FONT_FAMILY, 16, QFont.Bold))
        logo.setStyleSheet(f"color: {LEMON_ORANGE};")
        title_layout.addWidget(logo)

        mode_label = QLabel("多AI协同模式")
        mode_label.setFont(QFont(FONT_FAMILY, 11))
        mode_label.setStyleSheet(f"color: {TEXT_TERTIARY};")
        title_layout.addWidget(mode_label)

        title_layout.addStretch()

        # 按钮
        add_btn = QPushButton("+ 添加AI")
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {LEMON_ORANGE};
                border: 1px solid {LEMON_ORANGE};
                border-radius: {RADIUS_SM};
                padding: 5px 14px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {LEMON_ORANGE};
                color: #000;
            }}
        """)
        add_btn.clicked.connect(self._add_ai_window)
        title_layout.addWidget(add_btn)

        connect_all_btn = QPushButton("⚡ 全部连接")
        connect_all_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE};
                color: #000;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 5px 14px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {LEMON_YELLOW};
            }}
        """)
        connect_all_btn.clicked.connect(self._connect_all)
        title_layout.addWidget(connect_all_btn)

        bg_layout.addWidget(title_bar)

        # ========== 主内容区 ==========
        h_splitter = QSplitter(Qt.Horizontal)
        h_splitter.setHandleWidth(1)
        h_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {BORDER_DEFAULT};
            }}
            QSplitter::handle:hover {{
                background: {LEMON_ORANGE};
            }}
        """)

        # 左栏：文件资源管理器
        self.explorer = FileExplorerPanel()
        self.explorer.file_selected.connect(self._on_file_selected)
        h_splitter.addWidget(self.explorer)

        # 中栏：AI窗口网格（可滚动）+ 统计面板
        center = QWidget()
        center.setStyleSheet("background: transparent;")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(8, 8, 8, 8)
        center_layout.setSpacing(6)

        # 标题栏
        center_header = QHBoxLayout()
        center_title = QLabel(icon_text_html("bot", "AI 任务窗口", color=LEMON_ORANGE))
        center_title.setFont(QFont(FONT_FAMILY, 12, QFont.Bold))
        center_title.setStyleSheet(f"color: {LEMON_ORANGE};")
        center_header.addWidget(center_title)

        self.ai_count_label = QLabel("0/4 已连接")
        self.ai_count_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
        center_header.addWidget(self.ai_count_label)
        center_header.addStretch()

        add_btn = QPushButton("+ 添加AI")
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {LEMON_ORANGE};
                border: 1px solid {LEMON_ORANGE}; border-radius: {RADIUS_SM};
                padding: 3px 10px; font-size: 10px;
            }}
            QPushButton:hover {{ background: {LEMON_ORANGE}; color: #000; }}
        """)
        add_btn.clicked.connect(self._add_ai_window)
        center_header.addWidget(add_btn)
        center_layout.addLayout(center_header)

        # AI窗口滚动区
        self.ai_scroll = QScrollArea()
        self.ai_scroll.setWidgetResizable(True)
        self.ai_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.ai_scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                background: {BG_DARK}; width: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {LEMON_ORANGE}; border-radius: 2px;
            }}
        """)

        self.ai_grid_container = QWidget()
        self.ai_grid_container.setStyleSheet("background: transparent;")
        self.ai_grid_layout = QVBoxLayout(self.ai_grid_container)
        self.ai_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.ai_grid_layout.setSpacing(6)

        self.ai_scroll.setWidget(self.ai_grid_container)
        center_layout.addWidget(self.ai_scroll, stretch=2)

        # 统计面板
        self.stats_panel = AITaskStatsPanel()
        center_layout.addWidget(self.stats_panel, stretch=1)

        # AI性能对比图
        self.comparison_chart = AIComparisonChart()
        center_layout.addWidget(self.comparison_chart, stretch=1)

        h_splitter.addWidget(center)

        # 右栏：代码编辑器
        self.editor = CodeEditorPanel()
        h_splitter.addWidget(self.editor)

        h_splitter.setSizes([250, 500, 400])
        bg_layout.addWidget(h_splitter, stretch=1)

        # ========== 底部状态栏 ==========
        self.status_bar = MultiAIStatusBar()
        self.status_bar.command_sent.connect(self._on_global_command)
        bg_layout.addWidget(self.status_bar)

        layout.addWidget(bg, stretch=1)

    def _create_ai_windows(self):
        """创建4个AI窗口"""
        roles = [
            ("ai-1", "AI 助手 1", "qwen3.5:4b"),
            ("ai-2", "AI 助手 2", "qwen3.5:9b"),
            ("ai-3", "AI 审查", "deepseek-r1:8b"),
            ("ai-4", "AI 测试", "qwen3.5:4b"),
        ]
        # 使用2列网格布局
        row_widget = None
        for i, (task_id, task_name, default_model) in enumerate(roles):
            window = MultiAIWindow(task_id, task_name)
            window.clicked.connect(self._select_window)
            window.message_sent.connect(self._on_message)
            window.ai_connected.connect(self._on_ai_connected)

            if i % 2 == 0:
                row_widget = QWidget()
                row_widget.setStyleSheet("background: transparent;")
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)
                self.ai_grid_layout.addWidget(row_widget)

            row_layout.addWidget(window, stretch=1)
            self.ai_windows[task_id] = window
            self._task_completed_count[task_id] = 0
            self._response_times[task_id] = []

        self._select_window("ai-1")

    def _add_ai_window(self):
        """添加新AI窗口"""
        task_num = len(self.ai_windows) + 1
        task_id = f"ai-{task_num}"
        task_name = f"AI 助手 {task_num}"

        window = MultiAIWindow(task_id, task_name)
        window.clicked.connect(self._select_window)
        window.message_sent.connect(self._on_message)
        window.ai_connected.connect(self._on_ai_connected)

        self.ai_windows[task_id] = window
        self._task_completed_count[task_id] = 0
        self._response_times[task_id] = []

        # 按2列布局添加
        count = len(self.ai_windows)
        if count % 2 == 1:
            # 奇数：创建新行
            row_widget = QWidget()
            row_widget.setStyleSheet("background: transparent;")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            row_layout.addWidget(window, stretch=1)
            self.ai_grid_layout.addWidget(row_widget)
        else:
            # 偶数：添加到当前最后一行
            last_item = self.ai_grid_layout.itemAt(self.ai_grid_layout.count() - 1)
            if last_item and last_item.widget():
                last_row = last_item.widget().layout()
                if last_row:
                    last_row.addWidget(window, stretch=1)

        self.update_status()

    def _select_window(self, task_id: str):
        for tid, window in self.ai_windows.items():
            window.set_selected(tid == task_id)
        self.current_task_id = task_id
    def _on_message(self, task_id: str, message: str):
        print(f"[AI] {task_id}: {message}")
        self.editor.output_area.append(f"[{task_id}] : {message}")
        if self.serve_bridge:
            try:
                self.serve_bridge.send_message(message)
                self.editor.output_area.append(f"[{task_id}] AI")
            except Exception as e:
                self.editor.output_area.append(f"[{task_id}] : {e}")
        else:
            self.editor.output_area.append(f"[{task_id}] AI")
            window = self.ai_windows.get(task_id)
            if window:
                window.append_response(f"[] {message[:80]}...")

    def _on_ai_connected(self, task_id: str, connected: bool):
        """AI连接状态更新"""
        self.update_status()

    def _on_file_selected(self, file_path: str):
        """文件选择处理 — 真实读取文件内容"""
        import os
        file_name = os.path.basename(file_path)
        self.editor.file_name.setText(file_name)
        self.editor._current_file = file_path

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            self.editor.editor.setPlainText(content)
            self.editor.output_area.append(f"[系统] 已加载: {file_name} ({len(content)} 字符)")
        except Exception as e:
            self.editor.output_area.append(f"[系统] 无法读取文件: {e}")
            self.editor.editor.setPlainText(f"# 无法读取: {file_path}\n# 错误: {e}")

    def _on_global_command(self, command: str):
        """全局命令广播"""
        for task_id, window in self.ai_windows.items():
            if window.get_config()["connected"]:
                window.output_area.append(f"[全局命令] {command}")
                window.append_response(f"收到全局命令: {command}")

    def _connect_all(self):
        """全部连接"""
        for window in self.ai_windows.values():
            if not window.get_config()["connected"]:
                window._on_connect_test()
    def set_serve_bridge(self, bridge):
        self.serve_bridge = bridge

    def update_status(self):
        connected_count = sum(1 for w in self.ai_windows.values() if w.get_config()["connected"])
        total = len(self.ai_windows)
        self.status_bar.update_ai_count(connected_count, total)
        self.ai_count_label.setText(f"{connected_count}/{total} 已连接")
        self._update_stats_panel()

    def _update_stats_panel(self):
        """更新统计面板和对比图"""
        stats = {}
        for task_id, window in self.ai_windows.items():
            config = window.get_config()
            times = self._response_times.get(task_id, [])
            avg_time = sum(times) / len(times) if times else 0
            stats[task_id] = {
                "name": window.task_name,
                "engine": config.get("provider", "N/A"),
                "model": config.get("model", "N/A"),
                "tasks_completed": self._task_completed_count.get(task_id, 0),
                "avg_response_time": avg_time,
                "tokens_used": config.get("tokens_used", 0),
                "connected": config.get("connected", False),
            }
        self.stats_panel.update_stats(stats)
        self.comparison_chart.set_data(stats)


# ============================================================================
# 导出
# ============================================================================

__all__ = ['MultiAICooperatePanel', 'StarryBackground']