# -*- coding: utf-8 -*-
"""
Lemon Agent 混合模式界面
========================
实现项目公司化的可视化界面：
- 超级大脑控制台
- 工作群聊天区
- 执行AI状态卡片
- 秘书工作日志

布局：
┌─────────────────────────────────────────┐
│          超级大脑控制台（顶部）           │
├─────────────────────────────────────────┤
│          工作群（AI沟通区）               │
├─────────────────────────────────────────┤
│  执行AI卡片1  │  执行AI卡片2  │  执行AI卡片3│
├─────────────────────────────────────────┤
│          秘书工作日志（底部）             │
└─────────────────────────────────────────┘
"""

import sys
import os
import json
from datetime import datetime
from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QScrollArea, QFrame, QSplitter, QGroupBox,
    QListWidget, QListWidgetItem, QProgressBar, QTabWidget,
    QSizePolicy, QComboBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor, QPalette
from ui.design.tokens import Lemon

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ★ v4.1.23: Worktree Actor 合并模式持久化（经典面板写 JSON config，记忆上次选择）
def _load_wt_merge_mode() -> str:
    try:
        cfg = os.path.join(os.path.dirname(PROJECT_ROOT), "data", "worktree_actor_config.json")
        with open(cfg, "r", encoding="utf-8") as f:
            return str(json.load(f).get("merge_mode", "auto"))
    except Exception:
        return "auto"


def _save_wt_merge_mode(mode: str) -> None:
    try:
        d = os.path.join(os.path.dirname(PROJECT_ROOT), "data")
        os.makedirs(d, exist_ok=True)
        cfg = os.path.join(d, "worktree_actor_config.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"merge_mode": mode}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

from ui.theme import (
    BG_DARK, BG_PANEL, BG_SURFACE, BG_SURFACE_HOVER,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    LEMON_ORANGE, LEMON_YELLOW, LEMON_ORANGE_LIGHT,
    SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR,
    BORDER_RADIUS, FONT_FAMILY, BORDER_DEFAULT,
    icon_text_html, svg_to_qicon
)
# ★ v3.90: 本文件 5 处引用 ACCENT_COLOR 但此前未导入，导致实例化即 NameError 崩溃
ACCENT_COLOR = LEMON_ORANGE
from core.work_group import get_workgroup, Message
from core.superbrain import get_superbrain, SubTask
from core.role_system import get_role_manager


# ============================================================================
# 超级大脑控制台
# ============================================================================

class SuperbrainConsole(QWidget):
    """超级大脑控制台 — 显示决策和思考过程"""

    # 信号
    decision_made = pyqtSignal(str, dict)  # task_id, decision

    def __init__(self, parent=None):
        super().__init__(parent)
        # ★ 延迟初始化，避免在构造时触发工作群消息处理
        self._superbrain = None
        self._workgroup = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 标题
        title = QLabel("★ 超级大脑控制台")
        title.setFont(QFont(FONT_FAMILY, 14, QFont.Bold))
        title.setStyleSheet(f"color: {ACCENT_COLOR};")
        layout.addWidget(title)

        # 当前状态
        status_layout = QHBoxLayout()
        self.status_label = QLabel("状态: 空闲")
        self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        status_layout.addWidget(self.status_label)

        self.task_count_label = QLabel("任务: 0/0")
        self.task_count_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        status_layout.addWidget(self.task_count_label)

        status_layout.addStretch()
        layout.addLayout(status_layout)

        # 思考过程显示
        self.thinking_area = QTextEdit()
        self.thinking_area.setReadOnly(True)
        self.thinking_area.setMaximumHeight(100)
        self.thinking_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid #444;
                border-radius: {BORDER_RADIUS};
                padding: 8px;
                font-family: {FONT_FAMILY};
            }}
        """)
        self.thinking_area.setPlaceholderText("超级大脑思考过程...")
        layout.addWidget(self.thinking_area)

        # 控制按钮
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ 启动项目")
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {SUCCESS_COLOR};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS};
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {Lemon.ACCENT_GREEN};
            }}
        """)
        btn_layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("⏸ 暂停")
        self.pause_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {WARNING_COLOR};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS};
                padding: 8px 16px;
            }}
        """)
        btn_layout.addWidget(self.pause_btn)

        # ★ v4.1.17: Actor 并行执行按钮（蒸馏 MiMo-Code actor/，多 Agent 并行）
        self.actor_btn = QPushButton("⚡ Actor 并行")
        self.actor_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Lemon.ACCENT_PURPLE};
                color: white;
                border: none;
                border-radius: {BORDER_RADIUS};
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {Lemon.ACCENT_PURPLE};
            }}
        """)
        self.actor_btn.clicked.connect(self._on_actor_parallel_click)
        btn_layout.addWidget(self.actor_btn)

        # ★ v4.1.19: Worktree × Actor 隔离并行按钮（peer 绑独立 worktree 目录）
        self.wt_actor_btn = QPushButton("⛓ Worktree Actor")
        self.wt_actor_btn.setToolTip(
            "每个子 Agent 在独立 Git worktree 隔离目录并行（peer + cwd 隔离），完成后合并回主分支"
        )
        self.wt_actor_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Lemon.ACCENT_PURPLE};
                color: {Lemon.ACCENT_PURPLE};
                border: 1px solid Lemon.ACCENT_PURPLE;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #4a3f6a;
            }}
        """)
        btn_layout.addWidget(self.wt_actor_btn)

        # ★ v4.1.22: 合并模式下拉框 — auto 自动合并 / keep 保留供人工审阅（与右栏对齐）
        self.wt_merge_mode = QComboBox()
        self.wt_merge_mode.setToolTip("合并模式：跑完是否自动合并回主分支")
        self.wt_merge_mode.addItem("自动合并回主", "auto")
        self.wt_merge_mode.addItem("保留供审阅", "keep")
        self.wt_merge_mode.setStyleSheet(f"""
            QComboBox {{
                background-color: #2a2240;
                color: {Lemon.ACCENT_PURPLE};
                border: 1px solid Lemon.ACCENT_PURPLE;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QComboBox:hover {{ background-color: {Lemon.ACCENT_PURPLE}; }}
        """)
        btn_layout.addWidget(self.wt_merge_mode)

        # ★ v4.1.23: 读取上次持久化的合并模式，作为默认选中项
        _saved = _load_wt_merge_mode()
        _idx = self.wt_merge_mode.findData(_saved)
        self.wt_merge_mode.setCurrentIndex(_idx if _idx >= 0 else 0)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # ★ v4.1.24: Worktree 隔离区列表 — keep 模式保留的 worktree 可在此手动「合并回主」，
        # 形成「隔离 → 审阅 → 合并」闭环（与右栏 Worktree 列表对齐）
        wt_group = QGroupBox("⛓ Worktree 隔离区（保留 / 合并回主）")
        wt_group.setStyleSheet(f"""
            QGroupBox {{
                color: {ACCENT_COLOR};
                border: 1px solid Lemon.ACCENT_PURPLE;
                border-radius: {BORDER_RADIUS};
                margin-top: 8px;
                padding-top: 6px;
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}
        """)
        wt_layout = QVBoxLayout(wt_group)
        wt_layout.setSpacing(6)

        self.wt_list = QListWidget()
        self.wt_list.setMaximumHeight(120)
        self.wt_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {BG_DARK};
                color: {TEXT_PRIMARY};
                border: 1px solid #444;
                border-radius: {BORDER_RADIUS};
                font-size: 12px;
            }}
        """)
        wt_layout.addWidget(self.wt_list)

        wt_btn_layout = QHBoxLayout()
        self.wt_refresh_btn = QPushButton("刷新")
        self.wt_refresh_btn.setIcon(svg_to_qicon("refresh", size=14))
        self.wt_merge_btn = QPushButton("合并回主")
        self.wt_merge_btn.setIcon(svg_to_qicon("check", size=14))
        self.wt_remove_btn = QPushButton("清理")
        self.wt_remove_btn.setIcon(svg_to_qicon("trash", size=14))
        for _b in (self.wt_refresh_btn, self.wt_merge_btn, self.wt_remove_btn):
            _b.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Lemon.ACCENT_PURPLE};
                    color: {Lemon.ACCENT_PURPLE};
                    border: 1px solid Lemon.ACCENT_PURPLE;
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-size: 12px;
                }}
                QPushButton:hover {{ background-color: #4a3f6a; }}
            """)
            wt_btn_layout.addWidget(_b)
        wt_btn_layout.addStretch()
        wt_layout.addLayout(wt_btn_layout)
        layout.addWidget(wt_group)

        # 设置背景
        self.setStyleSheet(f"""
            SuperbrainConsole {{
                background-color: {BG_PANEL};
                border: 1px solid #555;
                border-radius: {BORDER_RADIUS};
            }}
        """)

    @property
    def superbrain(self):
        """延迟获取超级大脑实例"""
        if self._superbrain is None:
            self._superbrain = get_superbrain()
        return self._superbrain

    @property
    def workgroup(self):
        """延迟获取工作群实例"""
        if self._workgroup is None:
            self._workgroup = get_workgroup()
        return self._workgroup

    def append_thinking(self, text: str):
        """添加思考内容"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.thinking_area.append(f"[{timestamp}] {text}")

    def append_timeline(self, text: str):
        """★ v4.1.26: 追加一条紫色隔离/合并轨迹事件（对齐右栏 Timeline 的视觉反馈）"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.thinking_area.append(
            f'<span style="color:#c39bd3;">⛓ [{timestamp}] {text}</span>'
        )

    def update_status(self, status: str, completed: int = 0, total: int = 0):
        """更新状态"""
        self.status_label.setText(f"状态: {status}")
        self.task_count_label.setText(f"任务: {completed}/{total}")


# ============================================================================
# 工作群聊天区
# ============================================================================

class WorkGroupChat(QWidget):
    """工作群聊天区 — 博客式任务汇报界面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # ★ 延迟初始化
        self._workgroup = None
        self._role_manager = None
        self._messages: List[Message] = []
        self._handler_connected = False
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 标题栏
        title_layout = QHBoxLayout()
        title = QLabel(icon_text_html("message", "工作群", color=LEMON_ORANGE))
        title.setFont(QFont(FONT_FAMILY, 13, QFont.Bold))
        title.setStyleSheet(f"color: {TEXT_PRIMARY};")
        title_layout.addWidget(title)

        self.online_count = QLabel("在线: 0")
        self.online_count.setStyleSheet(f"color: {LEMON_ORANGE}; font-size: 12px;")
        title_layout.addWidget(self.online_count)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # 消息滚动区（博客式卡片布局）
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {BORDER_RADIUS};
                background-color: {BG_DARK};
            }}
            QScrollBar:vertical {{
                background: {BG_DARK};
                width: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {LEMON_ORANGE};
                border-radius: 3px;
                min-height: 30px;
            }}
        """)

        self.message_container = QWidget()
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(8, 8, 8, 8)
        self.message_layout.setSpacing(10)
        self.message_layout.addStretch()

        self.scroll_area.setWidget(self.message_container)
        layout.addWidget(self.scroll_area, stretch=1)

        # 成员状态栏
        member_layout = QHBoxLayout()
        self.member_labels = {}
        for role_id in ["director", "frontend", "backend", "reviewer", "tester", "secretary"]:
            rm = get_role_manager()
            role_def = rm.get_role(role_id)
            icon = role_def.icon if role_def else "🤖"
            name = role_def.name if role_def else role_id
            label = QLabel(f"{icon} {name.split('（')[0]}: 空闲")
            label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
            member_layout.addWidget(label)
            self.member_labels[role_id] = label
        layout.addLayout(member_layout)

    @property
    def workgroup(self):
        """延迟获取工作群实例"""
        if self._workgroup is None:
            self._workgroup = get_workgroup()
            if not self._handler_connected:
                self._workgroup.add_handler(self._on_message)
                self._handler_connected = True
        return self._workgroup

    @property
    def role_manager(self):
        """延迟获取角色管理器"""
        if self._role_manager is None:
            self._role_manager = get_role_manager()
        return self._role_manager

    def showEvent(self, event):
        super().showEvent(event)
        _ = self.workgroup
        _ = self.role_manager

    def _get_sender_color(self, from_ai: str) -> str:
        """根据发送者获取角色颜色"""
        rm = self.role_manager
        # 尝试从工作群成员中查找角色
        member = self.workgroup.get_member(from_ai)
        if member:
            role_name = member.get("role", "")
            for role_id, role_def in rm.get_all_roles().items():
                if role_def.name in role_name or role_id in role_name.lower():
                    return role_def.color
        # 默认颜色
        color_map = {
            "superbrain": LEMON_ORANGE,
            "system": TEXT_TERTIARY,
        }
        return color_map.get(from_ai, TEXT_PRIMARY)

    def _create_message_card(self, message: Message) -> QWidget:
        """创建博客式消息卡片"""
        card = QWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(4)

        sender_color = self._get_sender_color(message.from_ai)

        # 头部：发送者 + 时间
        header_layout = QHBoxLayout()
        sender_label = QLabel(f" {message.from_ai}")
        sender_label.setFont(QFont(FONT_FAMILY, 11, QFont.Bold))
        sender_label.setStyleSheet(f"color: {sender_color};")
        header_layout.addWidget(sender_label)

        timestamp = datetime.fromtimestamp(message.timestamp).strftime("%H:%M:%S")
        time_label = QLabel(timestamp)
        time_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px;")
        header_layout.addWidget(time_label)

        # 消息类型标签
        type_colors = {
            "text": TEXT_SECONDARY,
            "command": LEMON_YELLOW,
            "result": SUCCESS_COLOR,
            "error": ERROR_COLOR,
            "status": "#4488ff",
        }
        type_label = QLabel(f" [{message.msg_type}]")
        type_label.setStyleSheet(f"color: {type_colors.get(message.msg_type, TEXT_TERTIARY)}; font-size: 10px;")
        header_layout.addWidget(type_label)
        header_layout.addStretch()
        card_layout.addLayout(header_layout)

        # 内容
        content_label = QLabel(message.content)
        content_label.setWordWrap(True)
        content_label.setStyleSheet(f"""
            color: {TEXT_PRIMARY};
            font-size: 12px;
            padding: 4px 0;
        """)
        card_layout.addWidget(content_label)

        # 卡片样式
        card.setStyleSheet(f"""
            QWidget {{
                background-color: {BG_SURFACE};
                border: 1px solid {BORDER_DEFAULT};
                border-left: 3px solid {sender_color};
                border-radius: 6px;
            }}
            QWidget:hover {{
                background-color: {BG_SURFACE_HOVER};
            }}
        """)

        return card

    def _on_message(self, message: Message):
        """处理新消息 — 插入博客式卡片"""
        self._messages.append(message)

        # 移除底部的 stretch
        self.message_layout.takeAt(self.message_layout.count() - 1)

        # 创建并添加卡片
        card = self._create_message_card(message)
        self.message_layout.addWidget(card)

        # 重新添加 stretch
        self.message_layout.addStretch()

        # 自动滚动到底部
        QTimer.singleShot(100, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def add_message(self, from_ai: str, to_ai: str, content: str, msg_type: str = "text"):
        """手动添加消息"""
        self.workgroup.send_message(from_ai, to_ai, content, msg_type)


# ============================================================================
# 执行AI卡片
# ============================================================================

class ExecutorCard(QWidget):
    """执行AI卡片 — 显示单个执行者的状态"""

    def __init__(self, ai_id: str, role: str, model: str, parent=None):
        super().__init__(parent)
        self.ai_id = ai_id
        self.role = role
        self.model = model
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # 标题：AI名称和角色
        title_layout = QHBoxLayout()
        name_label = QLabel(f"{self.ai_id}")
        name_label.setFont(QFont(FONT_FAMILY, 11, QFont.Bold))
        name_label.setStyleSheet(f"color: {ACCENT_COLOR};")
        title_layout.addWidget(name_label)

        role_label = QLabel(f"({self.role})")
        role_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        title_layout.addWidget(role_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # 模型
        model_label = QLabel(f"模型: {self.model}")
        model_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        layout.addWidget(model_label)

        # 状态
        self.status_label = QLabel("状态: 空闲")
        self.status_label.setStyleSheet(f"color: {SUCCESS_COLOR};")
        layout.addWidget(self.status_label)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximumHeight(8)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {BG_DARK};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {ACCENT_COLOR};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self.progress_bar)

        # 当前任务
        self.task_label = QLabel("当前任务: 无")
        self.task_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self.task_label.setWordWrap(True)
        layout.addWidget(self.task_label)

        # 查看详情按钮
        self.detail_btn = QPushButton("查看详情")
        self.detail_btn.setMaximumWidth(80)
        self.detail_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {ACCENT_COLOR};
                border: 1px solid {ACCENT_COLOR};
                border-radius: {BORDER_RADIUS};
                padding: 4px 8px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {ACCENT_COLOR};
                color: white;
            }}
        """)
        layout.addWidget(self.detail_btn, alignment=Qt.AlignRight)

        # 设置卡片样式
        self.setStyleSheet(f"""
            ExecutorCard {{
                background-color: {BG_PANEL};
                border: 1px solid #555;
                border-radius: {BORDER_RADIUS};
            }}
        """)
        self.setMinimumWidth(200)

    def update_status(self, status: str, task: str = "", progress: int = 0):
        """更新状态"""
        self.status_label.setText(f"状态: {status}")
        self.task_label.setText(f"当前任务: {task}" if task else "当前任务: 无")
        self.progress_bar.setValue(progress)

        # 根据状态设置颜色
        if status == "运行中":
            self.status_label.setStyleSheet(f"color: {WARNING_COLOR};")
        elif status == "完成":
            self.status_label.setStyleSheet(f"color: {SUCCESS_COLOR};")
        elif status == "错误":
            self.status_label.setStyleSheet(f"color: {ERROR_COLOR};")
        else:
            self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY};")


# ============================================================================
# 秘书工作日志
# ============================================================================

class SecretaryLog(QWidget):
    """秘书工作日志 — 自动记录项目进度和事件"""

    # 日志级别
    LOG_INFO = "info"
    LOG_SUCCESS = "success"
    LOG_WARNING = "warning"
    LOG_ERROR = "error"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._log_entries: List[Dict] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 标题栏
        title_layout = QHBoxLayout()
        title = QLabel(icon_text_html("doc", "秘书工作日志", color=LEMON_ORANGE))
        title.setFont(QFont(FONT_FAMILY, 12, QFont.Bold))
        title.setStyleSheet(f"color: {TEXT_PRIMARY};")
        title_layout.addWidget(title)

        self.log_count_label = QLabel("0 条记录")
        self.log_count_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px;")
        title_layout.addWidget(self.log_count_label)
        title_layout.addStretch()

        self.clear_btn = QPushButton("🗑 清空")
        self.clear_btn.setMaximumWidth(70)
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_TERTIARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                color: {ERROR_COLOR};
                border-color: {ERROR_COLOR};
            }}
        """)
        self.clear_btn.clicked.connect(self._clear_logs)
        title_layout.addWidget(self.clear_btn)
        layout.addLayout(title_layout)

        # 日志列表（博客式卡片）
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setMaximumHeight(130)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {BORDER_DEFAULT};
                border-radius: {BORDER_RADIUS};
                background-color: {BG_DARK};
            }}
            QScrollBar:vertical {{
                background: {BG_DARK};
                width: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {LEMON_ORANGE};
                border-radius: 3px;
                min-height: 20px;
            }}
        """)

        self.log_container = QWidget()
        self.log_layout = QVBoxLayout(self.log_container)
        self.log_layout.setContentsMargins(6, 6, 6, 6)
        self.log_layout.setSpacing(4)
        self.log_layout.addStretch()

        self.scroll_area.setWidget(self.log_container)
        layout.addWidget(self.scroll_area)

    def _create_log_entry_widget(self, entry: Dict) -> QWidget:
        """创建单条日志卡片"""
        card = QWidget()
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(8, 4, 8, 4)
        card_layout.setSpacing(8)

        level = entry.get("level", self.LOG_INFO)
        level_icons = {
            self.LOG_INFO: "📋",
            self.LOG_SUCCESS: "✅",
            self.LOG_WARNING: "⚠️",
            self.LOG_ERROR: "❌",
        }
        level_colors = {
            self.LOG_INFO: TEXT_SECONDARY,
            self.LOG_SUCCESS: SUCCESS_COLOR,
            self.LOG_WARNING: WARNING_COLOR,
            self.LOG_ERROR: ERROR_COLOR,
        }

        icon_label = QLabel(level_icons.get(level, "📋"))
        icon_label.setStyleSheet("font-size: 12px;")
        card_layout.addWidget(icon_label)

        time_label = QLabel(entry.get("timestamp", ""))
        time_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 10px; min-width: 70px;")
        card_layout.addWidget(time_label)

        content_label = QLabel(entry.get("content", ""))
        content_label.setWordWrap(True)
        content_label.setStyleSheet(f"""
            color: {level_colors.get(level, TEXT_PRIMARY)};
            font-size: 11px;
        """)
        card_layout.addWidget(content_label, stretch=1)

        card.setStyleSheet(f"""
            QWidget {{
                background-color: {BG_SURFACE};
                border-radius: 4px;
            }}
            QWidget:hover {{
                background-color: {BG_SURFACE_HOVER};
            }}
        """)

        return card

    def add_log(self, content: str, level: str = None):
        """添加日志"""
        if level is None:
            level = self.LOG_INFO

        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = {
            "timestamp": timestamp,
            "content": content,
            "level": level,
        }
        self._log_entries.append(entry)

        # 更新 UI
        self.log_layout.takeAt(self.log_layout.count() - 1)
        card = self._create_log_entry_widget(entry)
        self.log_layout.addWidget(card)
        self.log_layout.addStretch()

        self.log_count_label.setText(f"{len(self._log_entries)} 条记录")

        # 自动滚动
        QTimer.singleShot(50, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def add_info(self, content: str):
        self.add_log(content, self.LOG_INFO)

    def add_success(self, content: str):
        self.add_log(content, self.LOG_SUCCESS)

    def add_warning(self, content: str):
        self.add_log(content, self.LOG_WARNING)

    def add_error(self, content: str):
        self.add_log(content, self.LOG_ERROR)

    def _clear_logs(self):
        """清空日志"""
        self._log_entries.clear()
        # 清除所有卡片
        while self.log_layout.count() > 1:
            item = self.log_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.log_count_label.setText("0 条记录")

    def get_logs(self) -> List[Dict]:
        """获取所有日志"""
        return self._log_entries.copy()

    def export_logs(self) -> str:
        """导出日志为文本"""
        lines = []
        for entry in self._log_entries:
            lines.append(f"[{entry['timestamp']}] [{entry['level'].upper()}] {entry['content']}")
        return "\n".join(lines)


# ============================================================================
# 混合模式面板（主面板）
# ============================================================================

class HybridModePanel(QWidget):
    """混合模式面板 — 项目公司化主界面"""

    # ★ v4.1.24: 后台线程跑完 Worktree Actor 后，跨线程安全地刷新隔离区列表（主线程执行）
    refresh_wt_list = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # ★ 延迟初始化，避免构造时崩溃
        self._superbrain = None
        self._workgroup = None
        self._cards_setup = False
        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部：超级大脑控制台
        self.console = SuperbrainConsole()
        self.console.setMaximumHeight(200)
        layout.addWidget(self.console)

        # 中部：工作群 + 执行AI卡片
        middle_splitter = QSplitter(Qt.Horizontal)

        # 左侧：工作群
        self.workgroup_chat = WorkGroupChat()
        self.workgroup_chat.setMinimumWidth(300)
        middle_splitter.addWidget(self.workgroup_chat)

        # 右侧：执行AI卡片
        self.executor_area = QWidget()
        self.executor_layout = QHBoxLayout(self.executor_area)
        self.executor_layout.setContentsMargins(10, 10, 10, 10)
        self.executor_layout.setSpacing(10)
        self.executor_cards: Dict[str, ExecutorCard] = {}
        middle_splitter.addWidget(self.executor_area)

        middle_splitter.setSizes([400, 600])
        layout.addWidget(middle_splitter, stretch=1)

        # 底部：秘书工作日志
        self.secretary_log = SecretaryLog()
        self.secretary_log.setMaximumHeight(150)
        layout.addWidget(self.secretary_log)

        # 设置背景
        self.setStyleSheet(f"background-color: {BG_DARK};")

    @property
    def superbrain(self):
        """延迟获取超级大脑实例"""
        if self._superbrain is None:
            self._superbrain = get_superbrain()
        return self._superbrain

    @property
    def workgroup(self):
        """延迟获取工作群实例"""
        if self._workgroup is None:
            self._workgroup = get_workgroup()
        return self._workgroup

    def showEvent(self, event):
        """重写showEvent，在第一次显示时初始化执行者卡片"""
        super().showEvent(event)
        if not self._cards_setup:
            self._setup_executor_cards()
            self._cards_setup = True

    def _setup_executor_cards(self):
        """设置执行AI卡片"""
        # 注册执行者
        executors = [
            ("执行AI-1", "前端开发", "qwen3.5:4b"),
            ("执行AI-2", "后端开发", "qwen3.5:4b"),
            ("执行AI-3", "代码审查", "qwen3.5:9b"),
            ("执行AI-4", "测试验证", "qwen3.5:4b")
        ]

        for ai_id, role, model in executors:
            # 添加到工作群
            self.workgroup.add_member(ai_id, role)

            # 创建卡片
            card = ExecutorCard(ai_id, role, model)
            self.executor_cards[ai_id] = card
            self.executor_layout.addWidget(card)

            # ★ v3.91: 查看详情按钮 — 显示该 AI 的详细信息
            card.detail_btn.clicked.connect(
                lambda checked=False, cid=ai_id, r=role, m=model: self._show_executor_detail(cid, r, m)
            )

            # 注册到调度器
            self.superbrain.scheduler.register_executor(ai_id, role, model)

        self.executor_layout.addStretch()

    def _connect_signals(self):
        """连接信号"""
        # 启动项目按钮
        self.console.start_btn.clicked.connect(self._start_demo_project)
        # ★ v3.90: 暂停按钮 — 暂停/继续演示执行
        self.console.pause_btn.clicked.connect(self._on_pause)
        # ★ v4.1.17: Actor 并行执行按钮 — 蒸馏 MiMo-Code actor/ 的多 Agent 并行
        self.console.actor_btn.clicked.connect(self._on_actor_parallel)
        # ★ v4.1.19: Worktree × Actor 隔离并行按钮
        self.console.wt_actor_btn.clicked.connect(self._on_worktree_actor_parallel)
        # ★ v4.1.24: Worktree 隔离区列表按钮（手动合并回主 / 清理，完成 keep 模式闭环）
        self.console.wt_refresh_btn.clicked.connect(self._on_wt_refresh)
        self.console.wt_merge_btn.clicked.connect(self._on_wt_merge_back)
        self.console.wt_remove_btn.clicked.connect(self._on_wt_remove)
        self.refresh_wt_list.connect(self._refresh_worktree_list)

    def _show_executor_detail(self, ai_id: str, role: str, model: str):
        """★ v3.91: 显示执行 AI 的详细信息"""
        lines = [
            f"🤖 {ai_id} 详细信息",
            f"角色：{role}",
            f"模型：{model}",
            f"状态：{'运行中' if hasattr(self, '_paused') and not self._paused else '待命中'}",
        ]
        self.console.append_thinking("\n".join(lines))
        self.secretary_log.add_log(f"查看 {ai_id} 详情 — {role} ({model})")

    def _start_demo_project(self):
        """启动演示项目 — ★ v4.2.3: demo_only（演示专用）。仅供 UI 走查演示，非真实项目执行入口；真实执行请走 bridge 真实后端。"""
        from core.superbrain import ProjectContext

        # 添加日志
        self.secretary_log.add_log("项目启动: 博客系统开发")

        # 创建上下文
        context = ProjectContext(
            project_name="博客系统",
            root_path=os.path.expanduser("~/projects/blog"),
            tech_stack=["frontend", "backend", "database"],
            constraints={}
        )

        # 启动项目
        project_id = self.superbrain.start_project(
            "博客系统",
            "开发一个简单的博客系统，支持用户注册、登录、发布文章和评论",
            context
        )

        # 更新控制台
        self.console.append_thinking(f"项目 {project_id} 已启动")
        self.console.update_status("运行中", 0, 5)

        # 添加工作群消息
        self.workgroup_chat.add_message(
            "superbrain", "all",
            f"项目启动，共5个子任务，开始分配"
        )

        # 模拟执行过程
        self._simulate_execution()

    def _simulate_execution(self):
        """模拟执行过程 — ★ v4.2.3: demo_only（演示专用）。随机进度仅用于演示，真实进度由 bridge 监控数据推送，本函数不得在生产路径默认触发。"""
        import random
        print("[HybridModePanel] [警告] _simulate_execution 为演示模式代码（随机模拟进度），仅用于界面演示")

        # 模拟进度更新
        progress = [0]

        def update_progress():
            for ai_id, card in self.executor_cards.items():
                if random.random() > 0.5:
                    old_progress = progress[0]
                    new_progress = min(old_progress + random.randint(10, 30), 100)
                    progress[0] = new_progress

                    card.update_status("运行中", "正在执行任务...", new_progress)

                    if new_progress >= 100:
                        card.update_status("完成", "任务已完成", 100)
                        self.secretary_log.add_log(f"{ai_id} 任务完成")

        # 使用定时器模拟
        self._timer = QTimer()
        self._timer.timeout.connect(update_progress)
        self._timer.start(2000)  # 每2秒更新一次
        self._paused = False

    def _on_pause(self):
        """★ v3.90: 暂停/继续演示执行"""
        if not hasattr(self, "_timer") or self._timer is None:
            self.console.append_thinking("当前没有正在执行的项目")
            return
        self._paused = not self._paused
        if self._paused:
            self._timer.stop()
            self.console.pause_btn.setText("▶ 继续")
            self.console.update_status("已暂停")
            self.secretary_log.add_log("执行已暂停")
        else:
            self._timer.start(2000)
            self.console.pause_btn.setText("⏸ 暂停")
            self.console.update_status("运行中", 0, 5)
            self.secretary_log.add_log("执行已继续")

    def _on_actor_parallel(self):
        """★ v4.1.17/v4.1.19: Actor 并行执行 — 用 ActorSystem 并行跑 3 个子任务（真实引擎调用）"""
        self.console.append_thinking("⚡ Actor 并行执行启动：3 个子任务同时分发（真实引擎调用）...")
        self.secretary_log.add_log("Actor 并行执行: 分发 3 个子任务（真实引擎）")
        self.console.update_status("Actor 并行中", 1, 5)

        try:
            from shared.actor_system import ActorSystem
        except Exception as e:
            self.console.append_thinking(f"❌ Actor 系统加载失败: {e}")
            self.console.update_status("失败")
            return

        system = ActorSystem()
        self._actor_system = system

        # ★ v4.1.19: 演示 task_fn 换真实引擎调用（get_engine_manager → ollama.generate）
        tasks = [
            ("架构师", "请分析一个 Python Agent 系统的模块划分原则，不超过80字"),
            ("审查员", "请列出代码审查中最常见的5个风险点，不超过80字"),
            ("写手", "请用一句话总结为什么 Agent 需要并行执行能力，不超过60字"),
        ]
        jobs = []
        for i, (role, prompt) in enumerate(tasks):
            jobs.append({
                "agent_type": role,
                "task": f"task-{i + 1}",
                "description": f"{role}：{prompt[:30]}...",
                "task_fn": self._make_real_task_fn(role, prompt),
            })

        import threading
        threading.Thread(target=self._actor_worker, args=(system, jobs), daemon=True).start()

    def _make_real_task_fn(self, role, prompt):
        """★ v4.1.19: 真实引擎调用 task_fn（替代占位睡眠）"""
        def _run():
            try:
                from shared.engine_manager import get_engine_manager
                em = get_engine_manager()
                engine = em.get_engine("ollama") if em else None
                if engine is None:
                    return f"[模拟] {role}: {prompt[:40]}..."
                result = engine.generate(prompt)
                return f"[{role}] {result}"
            except Exception as e:  # noqa: BLE001
                return f"[引擎错误] {role}: {e}"
        return _run

    def _on_worktree_actor_parallel(self):
        """★ v4.1.19: Worktree × Actor 打通 — 每个子 Agent 在独立 worktree 隔离目录并行
        ★ v4.1.22: 合并模式可选（auto 自动合并 / keep 保留供人工审阅），与右栏对齐"""
        merge_mode = self.wt_merge_mode.currentData() or "auto"
        mode_label = "自动合并回主分支" if merge_mode == "auto" else "保留隔离目录（不合并，供人工审阅）"
        _save_wt_merge_mode(merge_mode)  # ★ v4.1.23: 持久化本次选择，下次默认沿用
        self.console.append_thinking(
            f"⛓ Worktree Actor 启动：为 3 个子 Agent 创建独立隔离 worktree...（合并模式：{mode_label}）"
        )
        self.secretary_log.add_log("Worktree Actor: 创建独立 worktree 并隔离并行")
        self.console.update_status("Worktree 并行中", 1, 5)

        try:
            from shared.actor_system import ActorSystem
            from shared.worktree_actor import WorktreeActorCoordinator
        except Exception as e:
            self.console.append_thinking(f"❌ Worktree Actor 加载失败: {e}")
            self.console.update_status("失败")
            return

        system = ActorSystem()
        coord = WorktreeActorCoordinator(project_root=os.getcwd(), actor_system=system)
        tasks = [
            ("架构师", "请分析一个 Python Agent 系统的模块划分原则，不超过80字"),
            ("审查员", "请列出代码审查中最常见的5个风险点，不超过80字"),
            ("写手", "请用一句话总结为什么 Agent 需要并行执行能力，不超过60字"),
        ]
        jobs = []
        for i, (role, prompt) in enumerate(tasks):
            jobs.append({
                "agent_type": role,
                "task": f"task-{i + 1}",
                "title": f"wt-{role}",
                "detail": prompt,
                "description": f"{role}：{prompt[:30]}...",
                "task_fn": self._make_real_task_fn(role, prompt),
            })

        # worktree 创建 + 合并为重 IO，放后台线程
        def _bg():
            try:
                results, worktrees = coord.run(jobs, use_worktree=True, timeout_ms=120000)
                lines = ["⛓ Worktree 隔离并行结果:"]
                for r in results:
                    state = "✅ 成功" if r.outcome == "success" else ("⏰ 超时" if r.timed_out else f"❌ {r.error}")
                    lines.append(f"  → {r.task} [{r.actor_id}]: {state} | {r.result}")
                if worktrees:
                    lines.append(f"⛓ 已创建 {len(worktrees)} 个隔离 worktree:")
                    for w in worktrees:
                        lines.append(f"    • {w['branch']} @ {w['path']}")
                    # ★ v4.1.22: 仅 auto 模式自动合并；keep 模式保留 worktree 供人工审阅
                    if merge_mode == "auto":
                        report = coord.merge_all_back(worktrees)
                        for rep in report:
                            tag = "✅" if rep.get("ok") else "⚠️"
                            lines.append(f"    {tag} merge {rep['branch']}: {rep['msg']}")
                        lines.append("⛓ 已合并回主分支（worktree 隔离演示完成）")
                    else:
                        lines.append("⛓ 保留隔离目录，未合并（可在上方「Worktree 隔离区」列表手动合并回主）")
                    # ★ v4.1.24: keep 模式跑完后自动刷新隔离区列表，用户即可手动「合并回主」
                    self.refresh_wt_list.emit()
                self.console.append_thinking("\n".join(lines))
                self.secretary_log.add_log(f"Worktree Actor 完成: {len(worktrees)} 个隔离目录")
                self.console.update_status("全部完成", 5, 5)
            except Exception as e:  # noqa: BLE001
                self.console.append_thinking(f"❌ Worktree Actor 失败: {e}")
                self.console.update_status("失败")

        import threading
        threading.Thread(target=_bg, daemon=True).start()

    # ==================== ★ v4.1.24: Worktree 隔离区列表（手动「合并回主」闭环） ====================

    def _get_worktree_mgr(self):
        """惰性构造 WorktreeManager（项目根 = 当前工作目录）"""
        from standard_mode.core.worktree_manager import WorktreeManager
        if getattr(self, '_wt_mgr', None) is None:
            self._wt_mgr = WorktreeManager(os.getcwd())
        return self._wt_mgr

    def _refresh_worktree_list(self):
        """刷新隔离区列表（由主线程执行，可经信号从后台线程触发）"""
        try:
            mgr = self._get_worktree_mgr()
            wts = mgr.list()
        except Exception as e:
            self.console.append_thinking(f"❌ 读取 Worktree 列表失败: {e}")
            return
        lst = self.console.wt_list
        lst.clear()
        if not wts:
            lst.addItem("（暂无隔离 worktree）")
            return
        for w in wts:
            branch = w.get("branch", "") or "detached"
            path = w.get("path", "")
            head = w.get("head", "")
            item = QListWidgetItem(f"{branch}  @ {path}  [{head}]")
            item.setData(Qt.UserRole, path)
            lst.addItem(item)

    def _selected_wt_path(self):
        """取当前选中项的 worktree 路径"""
        item = self.console.wt_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _on_wt_refresh(self):
        self._refresh_worktree_list()

    def _on_wt_merge_back(self):
        """手动合并选中的 worktree 回主分支（完成 keep 模式的「审阅 → 合并」）"""
        path = self._selected_wt_path()
        if not path:
            self.console.append_thinking("⚠ 请先在隔离区列表中选择一个 worktree")
            return
        try:
            mgr = self._get_worktree_mgr()
            ok, msg = mgr.merge_back(path)
        except Exception as e:
            self.console.append_thinking(f"❌ 合并回主失败: {e}")
            return
        self.console.append_thinking(f"{'✅' if ok else '⚠️'} {msg}（{path}）")
        if ok:
            self.console.append_timeline(f"合并回主 {path}（{msg}）")
        self.secretary_log.add_log(f"Worktree 合并回主: {msg}")
        self._refresh_worktree_list()

    def _on_wt_remove(self):
        """清理选中的 worktree（★ v4.1.26: 默认拒绝丢弃未提交/未合并变更）

        不再默认 force=True：git 会拒绝清理有未提交变更的 worktree，
        给用户提示先「合并回主」或确认后再手动处理，避免误删改动（对齐右栏非 force 语义）。
        """
        path = self._selected_wt_path()
        if not path:
            self.console.append_thinking("⚠ 请先在隔离区列表中选择一个 worktree")
            return
        try:
            mgr = self._get_worktree_mgr()
            ok, msg = mgr.remove(path, force=False)
        except Exception as e:
            self.console.append_thinking(f"❌ 清理 worktree 失败: {e}")
            return
        if not ok:
            self.console.append_thinking(
                f"⚠️ 清理被拒绝：{msg}\n"
                f"   → 该 worktree 可能有未提交/未合并变更。建议先点「✅ 合并回主」"
                f"（需先在工作区内 commit）；确需丢弃请到资源管理器手动删除目录。"
            )
            self.secretary_log.add_log(f"Worktree 清理被拒绝（有未提交变更）: {path}")
            return
        self.console.append_thinking(f"✅ {msg}（{path}）")
        self.console.append_timeline(f"清理隔离区 {path}（{msg}）")
        self.secretary_log.add_log(f"Worktree 清理: {msg}")
        self._refresh_worktree_list()

    def _actor_worker(self, system, jobs):
        """后台线程：并行执行所有子任务并展示结果"""
        try:
            self.console.append_thinking(f"⛓ 创建 {len(jobs)} 个子 Agent（Actor 并行）...")
            results = system.spawn_many_wait_all(jobs, timeout_ms=30000)
            for i, r in enumerate(results):
                state = "✅ 成功" if r.outcome == "success" else ("⏰ 超时" if r.timed_out else f"❌ {r.error}")
                self.console.append_thinking(f"  → {jobs[i]['description']} [{r.actor_id}]: {state} | {r.result}")
                self.secretary_log.add_log(f"Actor {r.actor_id}: {state}")
            self.console.update_status("全部完成", 5, 5)
            self.console.append_thinking("✅ Actor 并行执行全部完成")
        except Exception as e:
            self.console.append_thinking(f"❌ Actor 并行执行失败: {e}")
            self.console.update_status("失败")

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "superbrain_stats": self.superbrain.get_stats(),
            "workgroup_stats": self.workgroup.get_stats()
        }