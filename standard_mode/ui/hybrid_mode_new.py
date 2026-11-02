# -*- coding: utf-8 -*-
"""
Lemon Code Agent — 混合模式（公司化多角色协作）
====================================
设计要点：
- 左栏：角色任务管理（6个角色，带算力/AI配置/工作状态）
- 中栏：超级大脑面板 + 算力分配仪表盘 + 项目管理计划
- 右栏：分Tab（对话/文件管理/历史记录），带星空背景
- 统一星空背景（与主页面一致）
- 每个角色可独立配置AI引擎（本地/云端）
- 算力可视化分配
"""

from typing import Dict, Optional
from datetime import datetime
import random
import threading
import requests

try:
    from shared.engine_manager import chat as engine_chat
except ImportError:
    engine_chat = None
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QLineEdit, QSplitter, QTextEdit,
    QProgressBar, QSizePolicy, QTabWidget, QComboBox,
    QTreeWidget, QTreeWidgetItem, QSlider, QPlainTextEdit,
    QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush, QLinearGradient

from ui.theme import (
    BG_DARK, BG_PANEL, BG_SURFACE, BG_SURFACE_HOVER,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    LEMON_ORANGE, LEMON_YELLOW, LEMON_GOLD,
    SU_COLOR, WARNING_COLOR, ERROR_COLOR,
    BORDER_RADIUS, FONT_FAMILY, BORDER_DEFAULT, BORDER_STRONG,
    RADIUS_SM, RADIUS_MD, RADIUS_LG,
)
from ui.single_ai_multi_window import StarryBackground
from ui.design.tokens import Lemon


# ============================================================================
# 算力仪表盘组件
# ============================================================================

class ComputePowerWidget(QWidget):
    """算力分配仪表盘 —— 可视化显示各角色算力占比"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Dict[str, tuple] = {}  # role_id -> (name, percent, color, working)
        self._total = 100
        self.setMinimumHeight(200)
        self.setMaximumHeight(280)

    def set_data(self, data: Dict[str, tuple]):
        self._data = data
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 背景
        painter.fillRect(self.rect(), QColor(BG_DARK))

        w = self.width()
        h = self.height()
        bar_h = 28
        gap = 8
        start_y = 40

        # 标题
        painter.setPen(QColor(LEMON_ORANGE))
        painter.setFont(QFont(FONT_FAMILY, 12, QFont.Bold))
        painter.drawText(12, 26, "⚡ 算力分配")

        painter.setPen(QColor(TEXT_TERTIARY))
        painter.setFont(QFont(FONT_FAMILY, 9))
        painter.drawText(12, start_y - 10, f"总算力: 100% | 已分配: {sum(v[1] for v in self._data.values())}%")

        if not self._data:
            painter.setPen(QColor(TEXT_TERTIARY))
            painter.setFont(QFont(FONT_FAMILY, 11))
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无算力分配数据")
            return

        y = start_y
        for role_id, (name, percent, color, working) in sorted(self._data.items(), key=lambda x: -x[1][1]):
            # 进度条背景
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(BG_PANEL))
            painter.drawRoundedRect(12, y, w - 90, bar_h, 4, 4)

            # 实际进度
            fill_w = max(0, int((w - 90) * percent / 100))
            if fill_w > 0:
                gradient = QLinearGradient(12, 0, 12 + fill_w, 0)
                gradient.setColorAt(0, QColor(color))
                gradient.setColorAt(1, QColor(color).lighter(130))
                painter.setBrush(gradient)
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(12, y, fill_w, bar_h, 4, 4)

            # 工作状态闪烁
            if working:
                painter.setPen(QPen(QColor(LEMON_ORANGE), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(10, y - 2, w - 86, bar_h + 4, 6, 6)

            # 角色名 + 百分比
            painter.setPen(QColor(TEXT_PRIMARY))
            painter.setFont(QFont(FONT_FAMILY, 10, QFont.Bold))
            painter.drawText(20, y + bar_h - 9, name)

            painter.setPen(QColor(TEXT_SECONDARY))
            painter.setFont(QFont(FONT_FAMILY, 10))
            painter.drawText(w - 80, y + bar_h - 9, f"{percent}%")

            # 状态标签
            status = "工作中" if working else "空闲"
            status_color = LEMON_ORANGE if working else TEXT_TERTIARY
            painter.setPen(QColor(status_color))
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(w - 80, y + 12, status)

            y += bar_h + gap


# ============================================================================
# 超级大脑面板
# ============================================================================

class SuperBrainPanel(QFrame):
    """超级大脑 —— 项目总控中心"""

    assign_to_role = pyqtSignal(str, str)  # role_id, task

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"""
            SuperBrainPanel {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # 标题
        header = QHBoxLayout()
        title = QLabel("🧠 超级大脑")
        title.setFont(QFont(FONT_FAMILY, 14, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_YELLOW};")
        header.addWidget(title)

        status = QLabel("● 运行中")
        status.setStyleSheet(f"color: {SU_COLOR}; font-size: 10px;")
        header.addWidget(status)
        header.addStretch()
        layout.addLayout(header)

        # 描述
        desc = QLabel("智能分析项目需求，自动分配任务给最优角色，协调团队高效运作")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px; line-height: 1.5;")
        layout.addWidget(desc)

        # 能力列表
        abilities = [
            ("📊", "智能任务分解", "将复杂需求拆分为可执行子任务"),
            ("🎯", "最优角色匹配", "根据角色能力自动分配任务"),
            ("⚡", "算力动态调配", "实时监控并调整算力分配"),
            ("🔍", "代码质量审查", "自动检查代码规范与安全隐患"),
        ]
        for icon, name, detail in abilities:
            row = QHBoxLayout()
            row.setSpacing(8)
            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet("font-size: 16px;")
            icon_lbl.setFixedWidth(30)
            row.addWidget(icon_lbl)

            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11px; font-weight: bold;")
            name_lbl.setFixedWidth(100)
            row.addWidget(name_lbl)

            detail_lbl = QLabel(detail)
            detail_lbl.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
            detail_lbl.setWordWrap(True)
            row.addWidget(detail_lbl, stretch=1)
            layout.addLayout(row)

        # 快速分析按钮
        self.analyze_input = QLineEdit()
        self.analyze_input.setPlaceholderText("输入项目需求，超级大脑自动分析...")
        self.analyze_input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 6px 12px;
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border-color: {LEMON_YELLOW};
            }}
        """)
        self.analyze_input.returnPressed.connect(self._on_analyze)
        layout.addWidget(self.analyze_input)

        analyze_btn = QPushButton("🧠 智能分析并分配")
        analyze_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_YELLOW};
                color: #000;
                border: none;
                border-radius: {RADIUS_SM};
                padding: 7px 16px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {LEMON_GOLD};
            }}
        """)
        analyze_btn.clicked.connect(self._on_analyze)
        layout.addWidget(analyze_btn)

    def _on_analyze(self):
        text = self.analyze_input.text().strip()
        if not text:
            return
        self.analyze_input.clear()
        # 智能分析：根据关键词分配
        task_lower = text.lower()
        if any(w in task_lower for w in ['前端', 'ui', '页面', '界面', 'html', 'css', 'react']):
            self.assign_to_role.emit("frontend", text)
        elif any(w in task_lower for w in ['后端', 'api', '数据库', 'server', '接口', 'python']):
            self.assign_to_role.emit("backend", text)
        elif any(w in task_lower for w in ['测试', 'test', '用例', 'bug']):
            self.assign_to_role.emit("tester", text)
        elif any(w in task_lower for w in ['审查', 'review', '代码', '安全']):
            self.assign_to_role.emit("reviewer", text)
        elif any(w in task_lower for w in ['文档', '记录', '整理', '笔记']):
            self.assign_to_role.emit("secretary", text)
        else:
            self.assign_to_role.emit("director", text)


# ============================================================================
# 项目管理计划面板
# ============================================================================

class ProjectPlanPanel(QFrame):
    """项目管理计划 —— 显示各角色当前任务和进度"""

    task_updated = pyqtSignal(str, dict)  # role_id, task_info

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roles_data: Dict[str, dict] = {}
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"""
            ProjectPlanPanel {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # 标题
        header = QHBoxLayout()
        title = QLabel("📋 项目管理计划")
        title.setFont(QFont(FONT_FAMILY, 14, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE};")
        header.addWidget(title)
        header.addStretch()

        # 自动刷新
        self.auto_btn = QPushButton("自动刷新: 开")
        self.auto_btn.setCheckable(True)
        self.auto_btn.setChecked(True)
        self.auto_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE};
                color: {SU_COLOR};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 3px 10px;
                font-size: 10px;
            }}
            QPushButton:checked {{
                color: {SU_COLOR};
            }}
            QPushButton:!checked {{
                color: {TEXT_TERTIARY};
            }}
        """)
        self.auto_btn.toggled.connect(lambda v: self.auto_btn.setText(
            f"自动刷新: {'开' if v else '关'}"
        ))
        header.addWidget(self.auto_btn)
        layout.addLayout(header)

        # 计划列表滚动区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: {BG_DARK};
                width: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {LEMON_ORANGE};
                border-radius: 2px;
            }}
        """)
        self.plan_container = QWidget()
        self.plan_container.setStyleSheet("background: transparent;")
        self.plan_layout = QVBoxLayout(self.plan_container)
        self.plan_layout.setContentsMargins(0, 0, 0, 0)
        self.plan_layout.setSpacing(6)
        self.scroll.setWidget(self.plan_container)
        layout.addWidget(self.scroll, stretch=1)

    def update_role_task(self, role_id: str, role_name: str, task: str, 
                         status: str = "进行中", progress: int = 0, 
                         accent: str = "{Lemon.BRAND_ORANGE}"):
        """更新角色任务"""
        self._roles_data[role_id] = {
            "name": role_name, "task": task, "status": status,
            "progress": progress, "accent": accent
        }
        self._refresh_display()

    def _refresh_display(self):
        """刷新计划显示"""
        # 清空
        for i in reversed(range(self.plan_layout.count())):
            item = self.plan_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()

        for role_id, data in self._roles_data.items():
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background: {BG_DARK};
                    border: 1px solid {BORDER_DEFAULT};
                    border-radius: {RADIUS_SM};
                    padding: 8px;
                }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(4)

            # 角色名 + 状态
            top = QHBoxLayout()
            name_lbl = QLabel(f"{data['name']}")
            name_lbl.setStyleSheet(f"color: {data['accent']}; font-size: 11px; font-weight: bold;")
            top.addWidget(name_lbl)

            status_lbl = QLabel(data['status'])
            status_color = LEMON_ORANGE if data['status'] == "进行中" else SU_COLOR
            status_lbl.setStyleSheet(f"color: {status_color}; font-size: 9px;")
            top.addWidget(status_lbl)
            top.addStretch()
            card_layout.addLayout(top)

            # 任务
            task_lbl = QLabel(data['task'][:60])
            task_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
            task_lbl.setWordWrap(True)
            card_layout.addWidget(task_lbl)

            # 进度条
            if data['progress'] > 0:
                pbar = QProgressBar()
                pbar.setFixedHeight(4)
                pbar.setMaximum(100)
                pbar.setValue(data['progress'])
                pbar.setStyleSheet(f"""
                    QProgressBar {{
                        background: {BG_PANEL};
                        border: none;
                        border-radius: 2px;
                    }}
                    QProgressBar::chunk {{
                        background: {data['accent']};
                        border-radius: 2px;
                    }}
                """)
                card_layout.addWidget(pbar)

            self.plan_layout.addWidget(card)

        self.plan_layout.addStretch()


# ============================================================================
# 增强版角色任务卡片（带AI配置）
# ============================================================================

class EnhancedRoleCard(QFrame):
    """增强版角色卡片 —— 带AI引擎配置和工作状态"""

    clicked = pyqtSignal(str)
    config_changed = pyqtSignal(str, str, str)  # role_id, engine, model

    ROLE_COLORS = {
        "director": "{Lemon.BRAND_ORANGE}", "frontend": "{Lemon.SYNTAX_FUNCTION}",
        "backend": "{Lemon.SYNTAX_NUMBER}", "reviewer": "{Lemon.SYNTAX_VARIABLE}",
        "tester": "{Lemon.SYNTAX_TYPE}", "secretary": "{Lemon.SYNTAX_OPERATOR}",
    }

    AI_ENGINES = [
        ("ollama", "Ollama 本地", ["qwen3.5:4b", "qwen3.5:9b", "deepseek-r1:8b"]),
        ("deepseek", "DeepSeek 云端", ["deepseek-chat", "deepseek-coder"]),
        ("mimocode", "Lemon Code", ["mimo-v1"]),
        ("lmstudio", "LM Studio", ["custom"]),
    ]

    def __init__(self, role_id: str, role_name: str, role_icon: str, role_desc: str, parent=None):
        super().__init__(parent)
        self.role_id = role_id
        self.role_name = role_name
        self.role_icon = role_icon
        self.role_desc = role_desc
        self.is_selected = False
        self._task_count = 0
        self._progress = 0
        self._compute_power = 0  # 算力占比
        self._working = False
        self._init_ui()

    def _init_ui(self):
        self.setMinimumWidth(200)
        self.setMinimumHeight(175)
        self.setCursor(Qt.PointingHandCursor)
        accent = self.ROLE_COLORS.get(self.role_id, LEMON_ORANGE)
        self.setStyleSheet(f"""
            EnhancedRoleCard {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
            EnhancedRoleCard:hover {{
                background-color: {BG_SURFACE};
                border-color: {accent};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)

        # 头部：图标 + 名称 + 工作状态
        header = QHBoxLayout()
        icon_label = QLabel(self.role_icon)
        icon_label.setStyleSheet("font-size: 24px;")
        icon_label.setFixedWidth(32)
        header.addWidget(icon_label)

        name_label = QLabel(self.role_name)
        name_label.setFont(QFont(FONT_FAMILY, 12, QFont.Bold))
        name_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
        header.addWidget(name_label)
        header.addStretch()

        self.work_dot = QLabel("●")
        self.work_dot.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
        header.addWidget(self.work_dot)
        layout.addLayout(header)

        # AI引擎选择
        engine_layout = QHBoxLayout()
        engine_label = QLabel("引擎:")
        engine_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 9px;")
        engine_label.setFixedWidth(30)
        engine_layout.addWidget(engine_label)

        self.engine_combo = QComboBox()
        for eid, ename, _ in self.AI_ENGINES:
            self.engine_combo.addItem(ename, eid)
        self.engine_combo.setCurrentIndex(0)  # 默认Ollama
        self.engine_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 2px 4px;
                font-size: 9px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                selection-background-color: {BG_SURFACE};
            }}
        """)
        engine_layout.addWidget(self.engine_combo, stretch=1)
        # 引擎切换时更新模型列表并发射配置变更信号
        self.engine_combo.currentIndexChanged.connect(self._on_engine_combo_changed)
        # Connect engine/model combo changes to role config update
        if hasattr(self, 'engine_combo'):
            self.engine_combo.currentTextChanged.connect(self._on_engine_changed)
        layout.addLayout(engine_layout)

        # 模型选择
        model_layout = QHBoxLayout()
        model_label = QLabel("模型:")
        model_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 9px;")
        model_label.setFixedWidth(30)
        model_layout.addWidget(model_label)

        self.model_combo = QComboBox()
        self._update_models()
        # 模型切换时发射配置变更信号
        self.model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        if hasattr(self, 'model_combo'):
            self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.model_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 2px 4px;
                font-size: 9px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {BG_DARK};
                color: {TEXT_PRIMARY};
            }}
        """)
        model_layout.addWidget(self.model_combo, stretch=1)
        layout.addLayout(model_layout)

        # 底部：任务数 + 算力占比 + 详情
        bottom = QHBoxLayout()
        self.task_count_lbl = QLabel("任务: 0")
        self.task_count_lbl.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 9px;")
        bottom.addWidget(self.task_count_lbl)

        self.power_lbl = QLabel("算力: 0%")
        self.power_lbl.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 9px;")
        bottom.addWidget(self.power_lbl)

        bottom.addStretch()

        detail_btn = QPushButton("详情")
        detail_btn.setFixedSize(44, 22)
        detail_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_SM};
                padding: 1px 6px;
                font-size: 9px;
            }}
            QPushButton:hover {{
                border-color: {accent}; color: {accent};
            }}
        """)
        detail_btn.clicked.connect(lambda: self.clicked.emit(self.role_id))
        bottom.addWidget(detail_btn)
        layout.addLayout(bottom)

    def _update_models(self):
        self.model_combo.clear()
        eid = self.engine_combo.currentData()
        for engine_id, _, models in self.AI_ENGINES:
            if engine_id == eid:
                for m in models:
                    self.model_combo.addItem(m)
                break

    def _on_engine_combo_changed(self):
        """引擎切换 → 更新模型列表 + 发射配置变更信号"""
        self._update_models()
        self.config_changed.emit(
            self.role_id,
            self.engine_combo.currentData() or "",
            self.model_combo.currentText() or ""
        )

    def _on_model_combo_changed(self):
        """模型切换 → 发射配置变更信号"""
        self.config_changed.emit(
            self.role_id,
            self.engine_combo.currentData() or "",
            self.model_combo.currentText() or ""
        )

    def _on_engine_changed(self, engine_name):
        """引擎变更 → 更新角色配置"""
        try:
            if hasattr(self, '_current_config') and self._current_config:
                self._current_config['engine'] = engine_name
            if hasattr(self, 'model_combo') and self.model_combo:
                # 更新模型列表
                self.model_combo.clear()
                model_map = {
                    'ollama': ['qwen3.5:4b', 'qwen3.5:9b'],
                    'deepseek': ['deepseek-chat', 'deepseek-coder'],
                    'mimocode': ['mimo-default'],
                }
                models = model_map.get(engine_name, ['default'])
                self.model_combo.addItems(models)
            self.log_output(f"[配置] 引擎已切换: {engine_name}")
        except Exception as e:
            self.log_output(f"[配置] 引擎切换失败: {e}")

    def _on_model_changed(self, model_name):
        """模型变更 → 更新角色配置"""
        try:
            if hasattr(self, '_current_config') and self._current_config:
                self._current_config['model'] = model_name
            engine = self.engine_combo.currentText() if hasattr(self, 'engine_combo') and self.engine_combo else '?'
            self.log_output(f"[配置] 模型已切换: {engine}/{model_name}")
        except Exception as e:
            self.log_output(f"[配置] 模型切换失败: {e}")

    def mousePressEvent(self, event):
        self.clicked.emit(self.role_id)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool):
        self.is_selected = selected
        accent = self.ROLE_COLORS.get(self.role_id, LEMON_ORANGE)
        self.setStyleSheet(f"""
            EnhancedRoleCard {{
                background-color: {BG_SURFACE if selected else BG_PANEL};
                border: {'2px' if selected else '1px'} solid {accent if selected else BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
        """)

    def set_work_status(self, working: bool, compute_power: int = 0):
        self._working = working
        self._compute_power = compute_power
        self.work_dot.setStyleSheet(
            f"color: {LEMON_ORANGE if working else TEXT_TERTIARY}; font-size: 10px;"
        )
        self.power_lbl.setText(f"算力: {compute_power}%")

    def set_task_count(self, count: int):
        self._task_count = count
        self.task_count_lbl.setText(f"任务: {count}")

    def get_config(self) -> dict:
        return {
            "engine": self.engine_combo.currentData(),
            "model": self.model_combo.currentText(),
        }


# ============================================================================
# 右侧混合面板（对话 + 文件 + 历史）
# ============================================================================

class HybridRightPanel(QFrame):
    """右侧面板 —— 分Tab：对话 / 角色详情 / 文件管理 / 历史记录"""

    message_sent = pyqtSignal(str)
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.messages: list = []
        self._role_detail_widget = None
        self._init_ui()

    def _init_ui(self):
        self.setMinimumWidth(320)
        self.setMaximumWidth(450)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        title_bar = QFrame()
        title_bar.setStyleSheet(f"background: {BG_PANEL}; border-bottom: 1px solid {BORDER_DEFAULT};")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(14, 10, 14, 10)
        title = QLabel("💬 团队协作")
        title.setFont(QFont(FONT_FAMILY, 14, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE};")
        title_layout.addWidget(title)
        self.online_count = QLabel("6人在线")
        self.online_count.setStyleSheet(f"color: {SU_COLOR}; font-size: 10px;")
        title_layout.addWidget(self.online_count)
        title_layout.addStretch()
        layout.addWidget(title_bar)

        # Tab切换
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: transparent;
            }}
            QTabBar::tab {{
                background: {BG_PANEL};
                color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_DEFAULT};
                padding: 6px 14px;
                font-size: 10px;
                min-width: 60px;
            }}
            QTabBar::tab:selected {{
                background: {BG_DARK};
                color: {LEMON_ORANGE};
                border-bottom: 2px solid {LEMON_ORANGE};
                font-weight: bold;
            }}
            QTabBar::tab:hover {{
                color: {TEXT_PRIMARY};
            }}
        """)

        # Tab 1: 对话
        self.chat_tab = self._create_chat_tab()
        self.tabs.addTab(self.chat_tab, "💬 对话")

        # Tab 2: 角色详情
        self.role_detail_tab = self._create_role_detail_tab()
        self.tabs.addTab(self.role_detail_tab, "👤 角色详情")

        # Tab 3: 文件管理
        self.file_tab = self._create_file_tab()
        self.tabs.addTab(self.file_tab, "📁 文件")

        # Tab 4: 历史记录
        self.history_tab = self._create_history_tab()
        self.tabs.addTab(self.history_tab, "📜 历史")

        layout.addWidget(self.tabs, stretch=1)

    def _create_chat_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 星空背景下的消息区
        bg = StarryBackground()
        bg_layout = QVBoxLayout(bg)
        bg_layout.setContentsMargins(6, 6, 6, 6)

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 4px; }}
            QScrollBar::handle:vertical {{ background: {LEMON_ORANGE}; border-radius: 2px; }}
        """)

        self.chat_container = QWidget()
        self.chat_container.setStyleSheet("background: transparent;")
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(6)
        self.chat_layout.addStretch()

        self.chat_scroll.setWidget(self.chat_container)
        bg_layout.addWidget(self.chat_scroll)
        layout.addWidget(bg, stretch=1)

        # 输入区
        input_bar = QFrame()
        input_bar.setStyleSheet(f"background: {BG_PANEL}; border-top: 1px solid {BORDER_DEFAULT};")
        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(8, 6, 8, 6)
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("发送消息给团队...")
        self.chat_input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_DARK}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: 14px;
                padding: 6px 12px; font-size: 11px;
            }}
            QLineEdit:focus {{ border-color: {LEMON_ORANGE}; }}
        """)
        self.chat_input.returnPressed.connect(self._on_chat_send)
        input_layout.addWidget(self.chat_input, stretch=1)

        send_btn = QPushButton("发送")
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE}; color: #000; border: none;
                border-radius: 14px; padding: 6px 16px; font-size: 11px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {LEMON_YELLOW}; }}
        """)
        send_btn.clicked.connect(self._on_chat_send)
        input_layout.addWidget(send_btn)
        layout.addWidget(input_bar)

        return tab

    def _create_role_detail_tab(self):
        """角色详情Tab —— 显示选中角色的详细信息"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 角色基本信息区
        self.role_info_header = QFrame()
        self.role_info_header.setStyleSheet(f"""
            QFrame {{
                background: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
        """)
        header_layout = QVBoxLayout(self.role_info_header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(4)

        self.role_name_label = QLabel("选择一个角色查看详情")
        self.role_name_label.setFont(QFont(FONT_FAMILY, 14, QFont.Bold))
        self.role_name_label.setStyleSheet(f"color: {LEMON_ORANGE};")
        header_layout.addWidget(self.role_name_label)

        self.role_desc_label = QLabel("")
        self.role_desc_label.setWordWrap(True)
        self.role_desc_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        header_layout.addWidget(self.role_desc_label)

        layout.addWidget(self.role_info_header)

        # AI配置信息
        self.role_ai_frame = QFrame()
        self.role_ai_frame.setStyleSheet(f"""
            QFrame {{
                background: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
        """)
        ai_layout = QVBoxLayout(self.role_ai_frame)
        ai_layout.setContentsMargins(12, 10, 12, 10)
        ai_layout.setSpacing(4)

        ai_title = QLabel("🤖 AI 连接配置")
        ai_title.setFont(QFont(FONT_FAMILY, 11, QFont.Bold))
        ai_title.setStyleSheet(f"color: {LEMON_YELLOW};")
        ai_layout.addWidget(ai_title)

        self.role_engine_label = QLabel("引擎: -")
        self.role_engine_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        ai_layout.addWidget(self.role_engine_label)

        self.role_model_label = QLabel("模型: -")
        self.role_model_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        ai_layout.addWidget(self.role_model_label)

        layout.addWidget(self.role_ai_frame)

        # 工作状态
        self.role_status_frame = QFrame()
        self.role_status_frame.setStyleSheet(f"""
            QFrame {{
                background: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
        """)
        status_layout = QVBoxLayout(self.role_status_frame)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(4)

        status_title = QLabel("📊 工作状态")
        status_title.setFont(QFont(FONT_FAMILY, 11, QFont.Bold))
        status_title.setStyleSheet(f"color: {LEMON_ORANGE};")
        status_layout.addWidget(status_title)

        self.role_working_label = QLabel("状态: 空闲")
        self.role_working_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        status_layout.addWidget(self.role_working_label)

        self.role_tasks_label = QLabel("任务数: 0")
        self.role_tasks_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        status_layout.addWidget(self.role_tasks_label)

        self.role_power_label = QLabel("算力占比: 0%")
        self.role_power_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        status_layout.addWidget(self.role_power_label)

        # 进度条
        self.role_progress = QProgressBar()
        self.role_progress.setFixedHeight(6)
        self.role_progress.setMaximum(100)
        self.role_progress.setValue(0)
        self.role_progress.setStyleSheet(f"""
            QProgressBar {{
                background: {BG_DARK};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {LEMON_ORANGE};
                border-radius: 3px;
            }}
        """)
        self.role_progress.setVisible(False)
        status_layout.addWidget(self.role_progress)

        layout.addWidget(self.role_status_frame)

        # 当前任务
        self.role_task_frame = QFrame()
        self.role_task_frame.setStyleSheet(f"""
            QFrame {{
                background: {BG_PANEL};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
        """)
        task_layout = QVBoxLayout(self.role_task_frame)
        task_layout.setContentsMargins(12, 10, 12, 10)
        task_layout.setSpacing(4)

        task_title = QLabel("📋 当前任务")
        task_title.setFont(QFont(FONT_FAMILY, 11, QFont.Bold))
        task_title.setStyleSheet(f"color: {LEMON_ORANGE};")
        task_layout.addWidget(task_title)

        self.role_current_task = QLabel("无任务")
        self.role_current_task.setWordWrap(True)
        self.role_current_task.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
        task_layout.addWidget(self.role_current_task)

        layout.addWidget(self.role_task_frame)

        layout.addStretch()
        return tab

    def show_role_detail(self, role_id: str, role_name: str, role_desc: str,
                         engine: str, model: str, working: bool,
                         task_count: int, compute_power: int, current_task: str = ""):
        """显示角色详情"""
        self.role_name_label.setText(f"{role_name}")
        self.role_desc_label.setText(role_desc)
        self.role_engine_label.setText(f"引擎: {engine}")
        self.role_model_label.setText(f"模型: {model}")
        self.role_working_label.setText(f"状态: {'⚡ 工作中' if working else '○ 空闲'}")
        self.role_working_label.setStyleSheet(
            f"color: {LEMON_ORANGE if working else TEXT_TERTIARY}; font-size: 10px;"
        )
        self.role_tasks_label.setText(f"任务数: {task_count}")
        self.role_power_label.setText(f"算力占比: {compute_power}%")
        self.role_current_task.setText(current_task or "无任务")
        self.role_current_task.setStyleSheet(
            f"color: {TEXT_SECONDARY if current_task else TEXT_TERTIARY}; font-size: 10px;"
        )
        # 切换到角色详情Tab
        self.tabs.setCurrentIndex(1)

    def _create_file_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 工具栏
        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("↻ 刷新")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: {BG_SURFACE}; color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_SM};
                padding: 4px 10px; font-size: 10px;
            }}
            QPushButton:hover {{ border-color: {LEMON_ORANGE}; color: {LEMON_ORANGE}; }}
        """)
        refresh_btn.clicked.connect(self._refresh_file_tree)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setIndentation(14)
        self.file_tree.setStyleSheet(f"""
            QTreeWidget {{
                background: {BG_DARK}; color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_SM};
                font-size: 10px;
            }}
            QTreeWidget::item {{ padding: 3px 6px; }}
            QTreeWidget::item:selected {{ background: {BG_SURFACE}; color: {LEMON_ORANGE}; }}
            QTreeWidget::item:hover {{ background: {BG_SURFACE_HOVER}; }}
        """)
        self.file_tree.itemClicked.connect(self._on_file_clicked)
        self._refresh_file_tree()
        layout.addWidget(self.file_tree, stretch=1)

        return tab

    def _create_history_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel("📜 操作历史")
        title.setFont(QFont(FONT_FAMILY, 12, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE};")
        layout.addWidget(title)

        self.history_output = QTextEdit()
        self.history_output.setReadOnly(True)
        self.history_output.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_DARK}; color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_SM};
                padding: 8px; font-family: {FONT_FAMILY}; font-size: 10px;
            }}
        """)
        layout.addWidget(self.history_output, stretch=1)

        return tab

    def _on_chat_send(self):
        text = self.chat_input.text().strip()
        if text:
            self.add_chat_message(f"我", text, "{Lemon.ACCENT_BLUE}")
            self.message_sent.emit(text)
            self.chat_input.clear()

    def _on_file_clicked(self, item, col):
        data = item.data(0, Qt.UserRole)
        if data and os.path.isfile(str(data)):
            self.file_selected.emit(data)

    def _refresh_file_tree(self):
        # 人性化设计：刷新时显示 loading 状态
        self.file_tree.clear()
        loading_item = QTreeWidgetItem(self.file_tree)
        loading_item.setText(0, "⏳ 正在扫描文件...")
        self.file_tree.repaint()

        # 延迟执行实际扫描，让 loading 先渲染
        QTimer.singleShot(50, self._do_refresh_file_tree)

    def _do_refresh_file_tree(self):
        """实际执行文件树扫描"""
        self.file_tree.clear()
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ignore_dirs = {'.venv', '.git', '__pycache__', 'node_modules', 'competition_archive'}
        ignore_ext = {'.pyc', '.pyo', '.pyd'}

        def _add_dir(parent, dir_path, dir_name, depth=0):
            if depth > 2 or dir_name in ignore_dirs:
                return
            folder = QTreeWidgetItem(parent)
            folder.setText(0, f"📁 {dir_name}")
            folder.setData(0, Qt.UserRole, os.path.join(dir_path, dir_name))
            try:
                for entry in sorted(os.listdir(os.path.join(dir_path, dir_name))):
                    fp = os.path.join(dir_path, dir_name, entry)
                    if os.path.isdir(fp) and not entry.startswith('.') and entry not in ignore_dirs:
                        _add_dir(folder, os.path.join(dir_path, dir_name), entry, depth + 1)
                    elif os.path.isfile(fp) and not entry.startswith('.'):
                        _, ext = os.path.splitext(entry)
                        if ext not in ignore_ext:
                            fi = QTreeWidgetItem(folder)
                            fi.setText(0, f"📄 {entry}")
                            fi.setData(0, Qt.UserRole, fp)
            except PermissionError:
                pass

        root = QTreeWidgetItem(self.file_tree)
        root.setText(0, f"📁 {os.path.basename(project_root)}")
        try:
            for entry in sorted(os.listdir(project_root)):
                if entry.startswith('.') or entry in ignore_dirs:
                    continue
                fp = os.path.join(project_root, entry)
                if os.path.isdir(fp):
                    _add_dir(root, project_root, entry, 1)
                elif os.path.isfile(fp):
                    _, ext = os.path.splitext(entry)
                    if ext not in ignore_ext:
                        fi = QTreeWidgetItem(root)
                        fi.setText(0, f"📄 {entry}")
                        fi.setData(0, Qt.UserRole, fp)
        except PermissionError:
            pass
        self.file_tree.expandAll()

    def add_chat_message(self, sender: str, content: str, accent: str = "{Lemon.BRAND_ORANGE}"):
        self.chat_layout.takeAt(self.chat_layout.count() - 1)

        bubble = QFrame()
        bubble.setStyleSheet(f"""
            QFrame {{
                background: {BG_SURFACE};
                border-radius: {RADIUS_LG};
                border: 1px solid {BORDER_DEFAULT};
            }}
        """)
        bl = QVBoxLayout(bubble)
        bl.setContentsMargins(10, 6, 10, 6)
        bl.setSpacing(3)

        sl = QLabel(sender)
        sl.setStyleSheet(f"color: {accent}; font-size: 10px; font-weight: bold;")
        bl.addWidget(sl)

        cl = QLabel(content)
        cl.setWordWrap(True)
        cl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11px;")
        bl.addWidget(cl)

        tl = QLabel(datetime.now().strftime("%H:%M"))
        tl.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 8px;")
        tl.setAlignment(Qt.AlignRight)
        bl.addWidget(tl)

        self.chat_layout.addWidget(bubble)
        self.chat_layout.addStretch()
        self.messages.append({"sender": sender, "content": content})

        QTimer.singleShot(50, lambda: self.chat_scroll.verticalScrollBar().setValue(
            self.chat_scroll.verticalScrollBar().maximum()
        ))

    def add_history(self, entry: str):
        self.history_output.append(f"[{datetime.now().strftime('%H:%M:%S')}] {entry}")


# ============================================================================
# 混合模式面板（主面板）
# ============================================================================

class HybridModeNewPanel(QWidget):
    """
    混合模式面板（公司化多角色协作）- 全面重构版

    布局：
    - 左侧：增强版角色卡片（6个角色，带AI引擎/模型/算力配置）
    - 中间：超级大脑 + 算力仪表盘 + 项目管理计划
    - 右侧：分Tab面板（对话 / 文件管理 / 历史记录）
    """

    ROLES = [
        ("director", "指挥官", "🎖️", "项目决策与任务分配，协调团队工作"),
        ("frontend", "前端开发", "🎨", "UI设计、前端实现与交互逻辑"),
        ("backend", "后端开发", "⚙️", "API开发、数据处理与服务架构"),
        ("reviewer", "代码审查", "🔍", "代码检查与安全审查"),
        ("tester", "测试", "🧪", "测试用例编写与自动化测试"),
        ("secretary", "秘书", "📋", "文档整理与项目进度跟踪"),
    ]

    task_assigned = pyqtSignal(str, str, str)
    file_opened = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.role_cards: Dict[str, EnhancedRoleCard] = {}
        self.current_role = "director"
        self._compute_data: Dict[str, tuple] = {}
        self._background_threads: list = []
        self._panel_visible = True
        self._init_ui()
        self._create_role_cards()
        self._init_compute_data()

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

        logo = QLabel("🍋 Lemon Code")
        logo.setFont(QFont(FONT_FAMILY, 16, QFont.Bold))
        logo.setStyleSheet(f"color: {LEMON_ORANGE};")
        title_layout.addWidget(logo)

        mode_label = QLabel("混合模式 · 团队协作")
        mode_label.setFont(QFont(FONT_FAMILY, 11))
        mode_label.setStyleSheet(f"color: {TEXT_TERTIARY};")
        title_layout.addWidget(mode_label)

        title_layout.addStretch()

        quick_assign = QPushButton("⚡ 快速分配")
        quick_assign.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE}; color: #000; border: none;
                border-radius: {RADIUS_SM}; padding: 5px 14px;
                font-size: 11px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {LEMON_YELLOW}; }}
        """)
        quick_assign.clicked.connect(self._quick_assign)
        title_layout.addWidget(quick_assign)

        vote_btn = QPushButton("🗳 发起投票")
        vote_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {LEMON_ORANGE};
                border: 1px solid {LEMON_ORANGE}; border-radius: {RADIUS_SM};
                padding: 5px 14px; font-size: 11px;
            }}
            QPushButton:hover {{ background: {LEMON_ORANGE}; color: #000; }}
        """)
        vote_btn.clicked.connect(self._start_vote)
        title_layout.addWidget(vote_btn)

        connect_all = QPushButton("🔗 全部连接")
        connect_all.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {LEMON_ORANGE};
                border: 1px solid {LEMON_ORANGE}; border-radius: {RADIUS_SM};
                padding: 5px 14px; font-size: 11px;
            }}
            QPushButton:hover {{ background: {LEMON_ORANGE}; color: #000; }}
        """)
        connect_all.clicked.connect(self._connect_all_roles)
        title_layout.addWidget(connect_all)

        bg_layout.addWidget(title_bar)

        # ========== 主内容区：三栏布局 ==========
        content_splitter = QSplitter(Qt.Horizontal)
        content_splitter.setHandleWidth(1)
        content_splitter.setStyleSheet(f"""
            QSplitter::handle {{ background: {BORDER_DEFAULT}; }}
            QSplitter::handle:hover {{ background: {LEMON_ORANGE}; }}
        """)

        # --- 左栏：角色卡片 ---
        left_panel = self._create_left_panel()
        content_splitter.addWidget(left_panel)

        # --- 中栏：超级大脑 + 算力 + 项目计划 ---
        center_panel = self._create_center_panel()
        content_splitter.addWidget(center_panel)

        # --- 右栏：对话/文件/历史 ---
        self.right_panel = HybridRightPanel()
        self.right_panel.message_sent.connect(self._on_chat_message)
        self.right_panel.file_selected.connect(self._on_file_selected)
        content_splitter.addWidget(self.right_panel)

        content_splitter.setSizes([280, 450, 370])
        bg_layout.addWidget(content_splitter, stretch=1)

        layout.addWidget(bg, stretch=1)

    def _create_left_panel(self):
        panel = QFrame()
        panel.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("🏢 角色管理")
        title.setFont(QFont(FONT_FAMILY, 13, QFont.Bold))
        title.setStyleSheet(f"color: {LEMON_ORANGE};")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{ background: {BG_DARK}; width: 5px; }}
            QScrollBar::handle:vertical {{ background: {LEMON_ORANGE}; border-radius: 2px; }}
        """)

        self.cards_container = QWidget()
        self.cards_container.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        scroll.setWidget(self.cards_container)
        layout.addWidget(scroll, stretch=1)

        # 任务模式切换 + 任务模板列表
        mode_frame = QFrame()
        mode_frame.setStyleSheet(f"""
            QFrame {{
                background: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD}; padding: 4px;
            }}
        """)
        mode_layout = QVBoxLayout(mode_frame)
        mode_layout.setContentsMargins(8, 4, 8, 4)
        mode_layout.setSpacing(4)

        mode_label = QLabel("任务模式:")
        mode_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 9px;")
        mode_layout.addWidget(mode_label)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["coding", "analysis", "testing", "docs"])
        self.mode_combo.setStyleSheet(f"""
            QComboBox {{
                background: {BG_DARK}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_SM};
                padding: 2px 4px; font-size: 9px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {BG_DARK}; color: {TEXT_PRIMARY};
                selection-background-color: {BG_SURFACE};
            }}
        """)
        mode_layout.addWidget(self.mode_combo)

        self.task_list = QListWidget()
        self.task_list.setMaximumHeight(100)
        self.task_list.setStyleSheet(f"""
            QListWidget {{
                background: {BG_DARK}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_SM};
                font-size: 9px;
            }}
            QListWidget::item {{ padding: 2px 4px; }}
            QListWidget::item:selected {{ background: {BG_SURFACE}; color: {LEMON_ORANGE}; }}
        """)
        mode_layout.addWidget(self.task_list)

        layout.addWidget(mode_frame)

        # Connect mode switch to task display update
        if hasattr(self, 'mode_combo'):
            self.mode_combo.currentTextChanged.connect(self._on_task_mode_changed)

        # 底部任务分配
        bottom_bar = QFrame()
        bottom_bar.setFixedHeight(56)
        bottom_bar.setStyleSheet(f"""
            QFrame {{
                background: {BG_PANEL}; border: 1px solid {BORDER_DEFAULT};
                border-radius: {RADIUS_MD};
            }}
        """)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(10, 6, 10, 6)

        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("分配任务给当前角色...")
        self.task_input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_DARK}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: {RADIUS_SM};
                padding: 6px 12px; font-size: 11px;
            }}
            QLineEdit:focus {{ border-color: {LEMON_ORANGE}; }}
        """)
        self.task_input.returnPressed.connect(self._on_assign_task)
        bottom_layout.addWidget(self.task_input, stretch=1)

        assign_btn = QPushButton("分配")
        assign_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE}; color: #000; border: none;
                border-radius: {RADIUS_SM}; padding: 6px 16px;
                font-weight: bold; font-size: 11px;
            }}
            QPushButton:hover {{ background: {LEMON_YELLOW}; }}
        """)
        assign_btn.clicked.connect(self._on_assign_task)
        bottom_layout.addWidget(assign_btn)
        layout.addWidget(bottom_bar)

        return panel

    def _create_center_panel(self):
        panel = QFrame()
        panel.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # 超级大脑
        self.brain_panel = SuperBrainPanel()
        self.brain_panel.assign_to_role.connect(self._on_brain_assign)
        layout.addWidget(self.brain_panel)

        # 算力仪表盘
        self.compute_widget = ComputePowerWidget()
        layout.addWidget(self.compute_widget)

        # 项目管理计划
        self.plan_panel = ProjectPlanPanel()
        layout.addWidget(self.plan_panel, stretch=1)

        return panel

    def _create_role_cards(self):
        for role_id, role_name, role_icon, role_desc in self.ROLES:
            card = EnhancedRoleCard(role_id, role_name, role_icon, role_desc)
            card.clicked.connect(self._select_role)
            self.cards_layout.addWidget(card)
            self.role_cards[role_id] = card

        self._select_role("director")
        self.right_panel.add_chat_message(f"系统", "欢迎使用混合模式！6个角色已就位，可以开始分配任务了！", "{Lemon.BRAND_ORANGE}")

        QTimer.singleShot(600, lambda: self.right_panel.add_chat_message(
            "指挥官", "团队就绪！请分配任务或输入需求，超级大脑会自动分析。", "{Lemon.BRAND_ORANGE}"
        ))

    def _init_compute_data(self):
        """初始化算力数据"""
        defaults = {
            "director": ("指挥官", 15, "{Lemon.BRAND_ORANGE}", False),
            "frontend": ("前端", 20, "{Lemon.SYNTAX_FUNCTION}", False),
            "backend": ("后端", 25, "{Lemon.SYNTAX_NUMBER}", False),
            "reviewer": ("审查", 10, "{Lemon.SYNTAX_VARIABLE}", False),
            "tester": ("测试", 15, "{Lemon.SYNTAX_TYPE}", False),
            "secretary": ("秘书", 5, "{Lemon.SYNTAX_OPERATOR}", False),
        }
        self._compute_data = defaults
        self.compute_widget.set_data(defaults)

    def _select_role(self, role_id: str):
        for rid, card in self.role_cards.items():
            card.set_selected(rid == role_id)
        self.current_role = role_id
        if role_id in self.role_cards:
            card = self.role_cards[role_id]
            self.task_input.setPlaceholderText(f"分配任务给 {card.role_name}...")
            # 显示角色详情在右侧面板
            config = card.get_config()
            self.right_panel.show_role_detail(
                role_id=role_id,
                role_name=card.role_name,
                role_desc=card.role_desc,
                engine=config.get("engine", "N/A"),
                model=config.get("model", "N/A"),
                working=card._working,
                task_count=card._task_count,
                compute_power=card._compute_power,
            )

    def _on_assign_task(self):
        task = self.task_input.text().strip()
        if not task:
            return
        role_id = self.current_role
        card = self.role_cards.get(role_id)
        if not card:
            return

        card.set_task_count(card._task_count + 1)
        card.set_work_status(True, min(30, card._compute_power + 5))
        accent = EnhancedRoleCard.ROLE_COLORS.get(role_id, "{Lemon.BRAND_ORANGE}")

        # 更新算力
        self._update_compute_data(role_id, True)

        self.right_panel.add_chat_message("指挥官", f"分配任务给 {card.role_name}：{task}", "{Lemon.BRAND_ORANGE}")
        self.right_panel.add_history(f"分配任务 → {card.role_name}: {task[:50]}")

        self.plan_panel.update_role_task(role_id, card.role_name, task, "进行中", 30, accent)
        self.task_assigned.emit(role_id, task, card.role_name)
        self.task_input.clear()

        # 真实调用 AI：让被分配角色对任务产出真实结果（替换原有定时假完成）
        self.right_panel.add_chat_message(card.role_name, f"收到任务：{task[:40]}...", accent)
        self.right_panel.add_history(f"{card.role_name} 开始处理任务")
        self.plan_panel.update_role_task(role_id, card.role_name, task, "进行中", 60, accent)
        threading.Thread(
            target=self._run_role_task,
            args=(role_id, card, task, accent),
            daemon=True,
        ).start()

    def _run_role_task(self, role_id, card, task, accent):
        """真实执行角色任务：调用 AI 生成该角色对任务的真实产出，回填面板。"""
        system_prompt = (
            f"你是 Lemon Code 团队中的「{card.role_name}」，职责：{card.role_desc}。"
            f"针对以下任务，以你的专业视角给出简洁可执行的产出要点（不超过120字，不要寒暄）。\n"
            f"任务：{task}"
        )
        try:
            if engine_chat:
                result = engine_chat(
                    f"系统: {system_prompt}\n回复:",
                    engine="ollama",
                    model="qwen3.5:4b",
                ) or ""
                result = result.strip()
            else:
                import requests
                resp = requests.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={
                        "model": "qwen3.5:4b",
                        "prompt": f"系统: {system_prompt}\n回复:",
                        "stream": False,
                        "options": {"temperature": 0.7, "num_predict": 400},
                    },
                    timeout=180,
                )
                result = ""
                if resp.status_code == 200:
                    result = (resp.json().get("response", "") or "").strip()

            if result:
                self._complete_task(role_id, card, task, accent, result)
            else:
                self._complete_task(role_id, card, task, accent, "（AI 未返回内容，请检查 Ollama 是否运行）")
        except Exception:
            self._complete_task(role_id, card, task, accent, "（AI 服务暂时不可用，检查 Ollama 是否运行）")

    def _complete_task(self, role_id, card, task, accent, result_text=""):
        """完成任务（★ v4.2.3: 线程安全——UI 更新经 QTimer.singleShot 调度回主线程，防止后台线程直操 QWidget）"""
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._complete_task_ui(role_id, card, task, accent, result_text))

    def _complete_task_ui(self, role_id, card, task, accent, result_text=""):
        """任务完成的 UI 更新体（仅在主线程执行）"""
        card.set_work_status(False, max(0, card._compute_power - 5))
        self._update_compute_data(role_id, False)
        if result_text:
            self.right_panel.add_chat_message(card.role_name, f"任务完成 ✅\n{result_text}", accent)
        else:
            self.right_panel.add_chat_message(card.role_name, f"任务完成！✅", accent)
        self.right_panel.add_history(f"{card.role_name} 完成任务: {task[:50]}")
        self.plan_panel.update_role_task(role_id, card.role_name, task, "已完成", 100, accent)

    def _update_compute_data(self, role_id: str, working: bool):
        name, pct, color, _ = self._compute_data.get(role_id, ("", 0, "#666", False))
        self._compute_data[role_id] = (name, pct, color, working)
        self.compute_widget.set_data(self._compute_data)

    def _on_brain_assign(self, role_id: str, task: str):
        card = self.role_cards.get(role_id)
        if card:
            self.current_role = role_id
            self._select_role(role_id)
            self.task_input.setText(task)
            self._on_assign_task()

    def _on_chat_message(self, message: str):
        self.right_panel.add_history(f"用户消息: {message[:50]}")
        role_context = self._build_role_context()
        system_prompt = (
            f"你是Lemon Code团队指挥官，协调角色：{role_context}。"
            f"简短回复用户消息（不超过50字）。回复格式：@角色名 简短回复"
        )
        threading.Thread(target=self._call_ai_chat, args=(message, system_prompt), daemon=True).start()

    def _build_role_context(self) -> str:
        parts = []
        for role_id, card in self.role_cards.items():
            parts.append(f"{card.role_name}({card.role_desc})")
        return "; ".join(parts)

    def _call_ai_chat(self, message: str, system_prompt: str):
        try:
            ai_response = ""
            if engine_chat:
                # 优先使用 engine_manager 统一调用
                full_prompt = f"系统: {system_prompt}\n用户: {message}\n回复:"
                ai_response = engine_chat(full_prompt, engine="ollama", model="qwen3.5:4b") or ""
                ai_response = ai_response.strip()
            else:
                # 回退到直接 requests 调用
                resp = requests.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={
                        "model": "qwen3.5:4b",
                        "prompt": f"系统: {system_prompt}\n用户: {message}\n回复:",
                        "stream": False,
                        "options": {"temperature": 0.7, "num_predict": 1500}
                    },
                    timeout=180
                )
                if resp.status_code == 200:
                    data = resp.json()
                    ai_response = (data.get("response", "") or data.get("thinking", "")).strip()

            # ★ v4.2.3: AI 调用留在后台线程，UI 更新经 QTimer.singleShot 调度回主线程
            from PyQt5.QtCore import QTimer
            if ai_response:
                resp = ai_response
                QTimer.singleShot(0, lambda: self._parse_and_route_ai_response(resp))
            else:
                QTimer.singleShot(0, lambda: self.right_panel.add_chat_message("指挥官", "收到消息，正在分析中...", "{Lemon.BRAND_ORANGE}"))
        except Exception:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.right_panel.add_chat_message("指挥官", "AI服务暂时不可用，检查Ollama是否运行", "{Lemon.BRAND_ORANGE}"))

    def _parse_and_route_ai_response(self, response: str):
        import re
        role_map = {card.role_name: role_id for role_id, card in self.role_cards.items()}
        role_map.update({
            "指挥官": "director", "前端": "frontend", "后端": "backend",
            "审查": "reviewer", "测试": "tester", "秘书": "secretary",
            "前端开发": "frontend", "后端开发": "backend",
            "代码审查": "reviewer",
        })
        match = re.match(r'@(\S+)\s*(.*)', response)
        if match:
            role_name, content = match.group(1), match.group(2).strip()
            role_id = role_map.get(role_name, "director")
            accent = EnhancedRoleCard.ROLE_COLORS.get(role_id, "{Lemon.BRAND_ORANGE}")
            display_name = self.role_cards.get(role_id, EnhancedRoleCard("director", "指挥官", "", "")).role_name
            self.right_panel.add_chat_message(display_name, content or response, accent)
        else:
            self.right_panel.add_chat_message(f"指挥官", response, "{Lemon.BRAND_ORANGE}")

    def _on_file_selected(self, file_path: str):
        self.right_panel.add_history(f"打开文件: {os.path.basename(file_path)}")
        self.file_opened.emit(file_path)

    def _connect_all_roles(self):
        """连接所有角色到 AI 引擎 — ★ v4.2.3: 真实检测引擎连接，失败给出具体错误，不再只改 UI 就提示"已连接" """
        engine_ok = False
        engine_error = ""
        # 1. 优先经 engine_manager 健康监控判断（若已注册 ollama）
        try:
            from shared.engine_manager import get_engine_manager
            mgr = get_engine_manager()
            health = getattr(mgr, 'health_monitor', None) or getattr(mgr, '_health_monitor', None)
            if health is not None:
                h = health.get_health("ollama")
                if h is not None:
                    engine_ok = bool(h.is_available)
                    engine_error = f"引擎状态: {h.status}"
        except Exception:
            pass
        # 2. 回退：直接探测 Ollama API（本地服务，2s 超时）
        if not engine_ok:
            try:
                resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
                engine_ok = resp.status_code == 200
                if not engine_ok:
                    engine_error = f"Ollama 返回 HTTP {resp.status_code}"
            except Exception as e:
                engine_error = f"Ollama 不可达: {e}"

        if engine_ok:
            for role_id, card in self.role_cards.items():
                card.set_work_status(True, card._compute_power)
                self._update_compute_data(role_id, True)
            self.right_panel.add_chat_message(f"系统", "所有角色已连接AI引擎！", "{Lemon.BRAND_ORANGE}")
            self.right_panel.add_history("全部角色连接AI引擎")
        else:
            for role_id, card in self.role_cards.items():
                card.set_work_status(False, card._compute_power)
                self._update_compute_data(role_id, False)
            self.right_panel.add_chat_message("系统", f"AI引擎连接失败: {engine_error}", "#ff3b30")
            self.right_panel.add_history(f"AI引擎连接失败: {engine_error}")

    def _start_vote(self):
        """发起 Agent 投票"""
        try:
            from shared.agent_voting import AgentVoting, VotingStrategy
            if not hasattr(self, '_voting'):
                self._voting = AgentVoting()

            # 弹出投票主题输入对话框
            from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QSpinBox, QDialogButtonBox
            dlg = QDialog(self)
            dlg.setWindowTitle("发起 Agent 投票")
            dlg.setMinimumWidth(400)
            dlg_layout = QVBoxLayout(dlg)

            dlg_layout.addWidget(QLabel("投票主题:"))
            topic_edit = QLineEdit()
            topic_edit.setPlaceholderText("如: 是否采用方案A？")
            dlg_layout.addWidget(topic_edit)

            dlg_layout.addWidget(QLabel("描述:"))
            desc_edit = QLineEdit()
            desc_edit.setPlaceholderText("详细描述投票内容...")
            dlg_layout.addWidget(desc_edit)

            dlg_layout.addWidget(QLabel("投票策略:"))
            strategy_combo = QComboBox()
            strategy_combo.addItems(["多数决 (MAJORITY)", "绝对多数 (SUPERMAJORITY)", "共识决 (CONSENSUS)", "加权 (WEIGHTED)"])
            dlg_layout.addWidget(strategy_combo)

            dlg_layout.addWidget(QLabel("超时(秒):"))
            timeout_spin = QSpinBox()
            timeout_spin.setRange(10, 600)
            timeout_spin.setValue(60)
            dlg_layout.addWidget(timeout_spin)

            btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            dlg_layout.addWidget(btns)

            if dlg.exec_() == QDialog.Accepted:
                topic = topic_edit.text().strip() or "未命名投票"
                desc = desc_edit.text().strip() or "请投票"
                strategy_map = {
                    0: VotingStrategy.MAJORITY, 1: VotingStrategy.SUPERMAJORITY,
                    2: VotingStrategy.CONSENSUS, 3: VotingStrategy.WEIGHTED
                }
                strategy = strategy_map[strategy_combo.currentIndex()]
                voter_ids = list(self.role_cards.keys())

                session = self._voting.start_vote(
                    topic=topic, description=desc, initiator="director",
                    voter_ids=voter_ids, strategy=strategy, timeout=timeout_spin.value()
                )

                self.right_panel.add_chat_message("系统", f"投票已发起: {topic} (ID: {session.vote_id[:8]})", "{Lemon.BRAND_ORANGE}")
                self.right_panel.add_chat_message("系统", f"策略: {strategy.name} | 超时: {timeout_spin.value()}s | 参与者: {len(voter_ids)}人", "#888")

                # 模拟各角色自动投票 — ★ v4.2.3: demo 标记。真实投票应基于各角色真实上下文决策（222 章阶段3），随机投票仅演示。
                import random
                for role_id in voter_ids:
                    choice = random.choice(["agree", "disagree", "abstain"])
                    self._voting.cast_vote(session.vote_id, role_id, choice)
                    role_name = self.role_cards[role_id].role_name
                    choice_label = {"agree": "赞成", "disagree": "反对", "abstain": "弃权"}.get(choice, "?")
                    self.right_panel.add_chat_message(role_name, f"投票: {choice_label}（模拟）", "{Lemon.ACCENT_GREEN}" if choice == "agree" else "{Lemon.ACCENT_RED}" if choice == "disagree" else "#888")

                # 关闭投票并显示结果
                result = self._voting.close_vote(session.vote_id)
                if result:
                    self.right_panel.add_chat_message("系统", f"投票结束: {result.result.value} | 赞成:{result.agree_count} 反对:{result.disagree_count} 弃权:{result.abstain_count}", "{Lemon.BRAND_ORANGE}")
        except ImportError:
            self.right_panel.add_chat_message(f"系统", "投票模块未安装", "{Lemon.ACCENT_RED}")
        except Exception as e:
            self.right_panel.add_chat_message("系统", f"投票失败: {e}", "{Lemon.ACCENT_RED}")

    def _quick_assign(self):
        # ★ v4.2.3: 以下为示例任务（演示用）。真实任务应由计划书/指挥 Agent 动态生成，替换本硬编码列表。
        tasks = [
            ("director", "制定项目开发计划"),
            ("frontend", "设计用户界面原型"),
            ("backend", "搭建后端API框架"),
            ("reviewer", "审查现有代码质量"),
            ("tester", "编写单元测试用例"),
            ("secretary", "整理项目文档"),
        ]
        # 尝试接入 superbrain 编排
        superbrain = getattr(self, 'superbrain', None)
        for role_id, task in tasks:
            card = self.role_cards.get(role_id)
            if card:
                card.set_task_count(card._task_count + 1)
                card.set_work_status(True, card._compute_power)
                self._update_compute_data(role_id, True)
                accent = EnhancedRoleCard.ROLE_COLORS.get(role_id, "{Lemon.BRAND_ORANGE}")
                self.right_panel.add_chat_message("指挥官", f"分配: {card.role_name} → {task}", "{Lemon.BRAND_ORANGE}")
                self.plan_panel.update_role_task(role_id, card.role_name, task, "进行中", 50, accent)

                # 优先使用 superbrain 真实编排，回退到模拟
                if superbrain and hasattr(superbrain, 'orchestrate_and_execute'):
                    def _superbrain_task(card=card, role_id=role_id, accent=accent, task=task):
                        try:
                            superbrain.orchestrate_and_execute(task, role_hint=role_id)
                        except Exception:
                            pass
                        # ★ v4.2.3: UI 更新经主线程调度（复用 _complete_task_ui），不再后台线程直操 QWidget
                        self._complete_task(role_id, card, task, accent)
                    threading.Thread(target=_superbrain_task, daemon=True).start()
                else:
                    # 无 superbrain 时，回退到真实 AI 角色产出（替代原定时假完成）
                    self.right_panel.add_chat_message(card.role_name, f"收到任务：{task[:40]}...", accent)
                    self.plan_panel.update_role_task(role_id, card.role_name, task, "进行中", 60, accent)
                    threading.Thread(
                        target=self._run_role_task,
                        args=(role_id, card, task, accent),
                        daemon=True,
                    ).start()

    def _on_task_mode_changed(self, mode_name):
        """任务模式变更 → 刷新任务显示"""
        try:
            if hasattr(self, 'task_list') and self.task_list:
                self.task_list.clear()
            mode_tasks = {
                'coding': ['代码审查', 'Bug修复', '功能开发', '重构'],
                'analysis': ['需求分析', '架构设计', '性能评估', '安全审计'],
                'testing': ['单元测试', '集成测试', 'E2E测试', '压力测试'],
                'docs': ['API文档', '用户手册', '变更日志', '架构文档'],
            }
            tasks = mode_tasks.get(mode_name, ['通用任务'])
            if hasattr(self, 'task_list') and self.task_list:
                for t in tasks:
                    self.task_list.addItem(QListWidgetItem(t))
            if hasattr(self, 'log_output'):
                self.log_output(f"[任务] 模式已切换: {mode_name} ({len(tasks)} 个任务模板)")
        except Exception as e:
            if hasattr(self, 'log_output'):
                self.log_output(f"[任务] 模式切换失败: {e}")

    def get_role_status(self) -> dict:
        status = {}
        for role_id, card in self.role_cards.items():
            status[role_id] = {
                "name": card.role_name, "tasks": card._task_count,
                "working": card._working, "compute_power": card._compute_power,
                "config": card.get_config(),
            }
        return status

    def hideEvent(self, event):
        """面板隐藏时 — 暂停后台线程，防止空指针崩溃"""
        super().hideEvent(event)
        self._panel_visible = False
        for t in self._background_threads:
            if hasattr(t, 'pause') and callable(t.pause):
                try:
                    t.pause()
                except Exception:
                    pass
            elif hasattr(t, '_pause_event') and hasattr(t._pause_event, 'clear'):
                t._pause_event.clear()

    def showEvent(self, event):
        """面板显示时 — 恢复后台线程"""
        super().showEvent(event)
        self._panel_visible = True
        for t in self._background_threads:
            if hasattr(t, 'resume') and callable(t.resume):
                try:
                    t.resume()
                except Exception:
                    pass
            elif hasattr(t, '_pause_event') and hasattr(t._pause_event, 'set'):
                t._pause_event.set()


__all__ = ['HybridModeNewPanel', 'StarryBackground']