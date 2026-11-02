# -*- coding: utf-8 -*-
"""
Lemon Agent 工作群聊天界面（星空主题）
=====================================
实现AI协作的可视化聊天界面：
- 星空动画背景
- AI气泡消息
- 角色头像
- 时间戳和状态显示
- 打字动画效果

特色：
- 符合 Lemon Code 的星空主题
- 区分不同角色的气泡样式
- 流畅的动画效果
"""

import sys
import os
import math
from datetime import datetime
from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QSpacerItem, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize, QRect, QPointF, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QColor, QPalette, QLinearGradient, QBrush, QPainter, QPen, QPolygonF, QBrush

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ui.theme import (
    BG_DARK, BG_PANEL, TEXT_PRIMARY, TEXT_SECONDARY,
    ACCENT_COLOR, SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR,
    BORDER_RADIUS, FONT_FAMILY, icon_text_html
)
from ui.design.tokens import Lemon


# ============================================================================
# 角色颜色配置
# ============================================================================

ROLE_COLORS = {
    "项目经理": {"bg": "{Lemon.ACCENT_BLUE}", "text": "{Lemon.BG}", "icon": "crown"},
    "前端开发": {"bg": "{Lemon.ACCENT_GREEN}", "text": "{Lemon.BG}", "icon": "palette"},
    "后端开发": {"bg": "{Lemon.ACCENT_PURPLE}", "text": "{Lemon.BG}", "icon": "settings"},
    "代码审查": {"bg": "#f59e0b", "text": "Lemon.PRIMARY", "icon": "search"},
    "测试验证": {"bg": "Lemon.ACCENT_RED", "text": "{Lemon.BG}", "icon": "check"},
    "system": {"bg": "Lemon.TEXT_DISABLED", "text": "#aaaaaa", "icon": "info"},
}


# ============================================================================
# 星空背景动画
# ============================================================================

class StarryBackground(QWidget):
    """星空动画背景"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 星星数据
        self.stars: List[Dict] = []
        self._init_stars(100)

        # 流星数据
        self.meteors: List[Dict] = []

        # 动画定时器
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_animation)
        self._timer.start(50)  # 20 FPS

    def _init_stars(self, count: int):
        """初始化星星"""
        import random
        self.stars = []
        for _ in range(count):
            self.stars.append({
                "x": random.random(),
                "y": random.random(),
                "size": random.uniform(1, 3),
                "alpha": random.uniform(0.3, 1.0),
                "speed": random.uniform(0.0001, 0.0005),
                "phase": random.random() * 2 * math.pi
            })

    def _update_animation(self):
        """更新动画"""
        # 更新星星闪烁
        for star in self.stars:
            star["phase"] += star["speed"] * 10
            if star["phase"] > 2 * math.pi:
                star["phase"] -= 2 * math.pi

        # 添加流星
        import random
        if random.random() < 0.02:  # 2% 概率添加流星
            self.meteors.append({
                "x": random.random(),
                "y": random.random() * 0.3,
                "length": random.uniform(0.05, 0.15),
                "speed": random.uniform(0.02, 0.04),
                "alpha": 1.0
            })

        # 更新流星
        new_meteors = []
        for meteor in self.meteors:
            meteor["y"] += meteor["speed"]
            meteor["x"] += meteor["speed"] * 0.3
            meteor["alpha"] -= 0.02
            if meteor["alpha"] > 0 and meteor["y"] < 1.0:
                new_meteors.append(meteor)
        self.meteors = new_meteors

        self.update()

    def paintEvent(self, event):
        """绘制星空背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()

        # 绘制深空背景
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0, QColor("#0a0a1a"))
        gradient.setColorAt(0.5, QColor("#0f0f2a"))
        gradient.setColorAt(1, QColor("#0a0a1a"))
        painter.fillRect(rect, gradient)

        # 绘制星星
        for star in self.stars:
            x = int(star["x"] * rect.width())
            y = int(star["y"] * rect.height())
            size = star["size"]
            alpha = (math.sin(star["phase"]) * 0.5 + 0.5) * star["alpha"]

            color = QColor(255, 255, 255, int(alpha * 255))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPointF(x, y), size, size)

        # 绘制流星
        for meteor in self.meteors:
            x1 = int(meteor["x"] * rect.width())
            y1 = int(meteor["y"] * rect.height())
            x2 = int((meteor["x"] - meteor["length"]) * rect.width())
            y2 = int((meteor["y"] - meteor["length"] * 0.5) * rect.height())

            pen = QPen(QColor(255, 255, 255, int(meteor["alpha"] * 200)))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(x1, y1, x2, y2)

            # 流星头部光晕
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, int(meteor["alpha"] * 150))))
            painter.drawEllipse(QPointF(x1, y1), 3, 3)


# ============================================================================
# AI气泡消息
# ============================================================================

class MessageBubble(QFrame):
    """AI消息气泡"""

    def __init__(self, from_ai: str, role: str, content: str,
                 timestamp: float, msg_type: str = "text", parent=None):
        super().__init__(parent)
        self.from_ai = from_ai
        self.role = role
        self.content = content
        self.timestamp = timestamp
        self.msg_type = msg_type

        self._init_ui()

    def _init_ui(self):
        # 获取角色颜色
        colors = ROLE_COLORS.get(self.role, ROLE_COLORS["system"])

        self.setStyleSheet(f"""
            MessageBubble {{
                background-color: transparent;
                border: none;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # 顶部：角色 + 时间
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        # 角色图标和名称
        icon = colors.get("icon", "bot")
        role_label = QLabel(icon_text_html(icon, self.from_ai, color=colors['bg']))
        role_label.setFont(QFont(FONT_FAMILY, 10, QFont.Bold))
        role_label.setStyleSheet(f"color: {colors['bg']};")
        header_layout.addWidget(role_label)

        # 角色
        role_badge = QLabel(f"[{self.role}]")
        role_badge.setFont(QFont(FONT_FAMILY, 9))
        role_badge.setStyleSheet(f"""
            color: {colors['text']};
            background-color: {colors['bg']};
            border-radius: 4px;
            padding: 2px 6px;
        """)
        header_layout.addWidget(role_badge)

        header_layout.addStretch()

        # 时间戳
        time_str = datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S")
        time_label = QLabel(time_str)
        time_label.setFont(QFont(FONT_FAMILY, 9))
        time_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        header_layout.addWidget(time_label)

        layout.addLayout(header_layout)

        # 消息内容（气泡）
        content_frame = QFrame()
        content_frame.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(50, 50, 70, 0.8);
                border-radius: 12px;
                padding: 12px;
            }}
        """)

        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(12, 8, 12, 8)

        # 消息类型图标
        type_icons = {
            "text": "",
            "command": "⚡ ",
            "result": "✓ ",
            "error": "✗ ",
            "status": "● "
        }

        # 内容文本
        content_text = f"{type_icons.get(self.msg_type, '')}{self.content}"
        content_label = QLabel(content_text)
        content_label.setFont(QFont(FONT_FAMILY, 11))
        content_label.setStyleSheet(f"color: {TEXT_PRIMARY};")
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content_layout.addWidget(content_label)

        layout.addWidget(content_frame)

        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

        self.setMaximumWidth(600)


# ============================================================================
# 工作群聊天区域
# ============================================================================

class WorkGroupChatArea(QWidget):
    """工作群聊天区域（星空背景）"""

    # 信号
    message_sent = pyqtSignal(str)  # message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: List[MessageBubble] = []
        self._init_ui()

    def _init_ui(self):
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 星空背景
        self.starry_bg = StarryBackground(self)
        self.starry_bg.setGeometry(0, 0, self.width(), self.height())

        # 内容容器（透明）
        content = QWidget()
        content.setAttribute(Qt.WA_TranslucentBackground)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(15)

        # 标题栏
        header = self._create_header()
        content_layout.addWidget(header)

        # 消息滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(30, 30, 50, 0.5);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 150, 50, 0.5);
                border-radius: 4px;
            }
        """)

        # 消息容器
        self.message_container = QWidget()
        self.message_container.setAttribute(Qt.WA_TranslucentBackground)
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(10, 10, 10, 10)
        self.message_layout.setSpacing(12)
        self.message_layout.addStretch()

        scroll.setWidget(self.message_container)
        content_layout.addWidget(scroll, stretch=1)

        # 成员状态栏
        members_bar = self._create_members_bar()
        content_layout.addWidget(members_bar)

        main_layout.addWidget(content)

        # 欢迎消息
        self._add_welcome_messages()

    def _create_header(self) -> QWidget:
        """创建标题栏"""
        header = QWidget()
        header.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(30, 30, 50, 0.8),
                    stop:0.5 rgba(50, 50, 80, 0.8),
                    stop:1 rgba(30, 30, 50, 0.8));
                border-radius: {BORDER_RADIUS};
            }}
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(15, 10, 15, 10)

        # 标题
        title = QLabel("💬 工作群 · AI协作空间")
        title.setFont(QFont(FONT_FAMILY, 14, QFont.Bold))
        title.setStyleSheet(f"color: {ACCENT_COLOR};")
        layout.addWidget(title)

        layout.addStretch()

        # 在线成员数
        online_label = QLabel("🟢 5 AI 在线")
        online_label.setFont(QFont(FONT_FAMILY, 11))
        online_label.setStyleSheet(f"color: {SUCCESS_COLOR};")
        layout.addWidget(online_label)

        return header

    def _create_members_bar(self) -> QWidget:
        """创建成员状态栏"""
        bar = QWidget()
        bar.setStyleSheet(f"""
            QWidget {{
                background: rgba(30, 30, 50, 0.6);
                border-radius: {BORDER_RADIUS};
            }}
        """)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(15, 8, 15, 8)
        layout.setSpacing(15)

        # 显示各成员状态
        members = [
            ("项目经理", "crown", "空闲"),
            ("前端开发", "palette", "运行中"),
            ("后端开发", "settings", "空闲"),
            ("代码审查", "search", "空闲"),
            ("测试验证", "check", "空闲"),
        ]

        for role, icon, status in members:
            colors = ROLE_COLORS.get(role, ROLE_COLORS["system"])
            status_color = SUCCESS_COLOR if status == "空闲" else WARNING_COLOR

            member_label = QLabel(icon_text_html(icon, role, color=colors['bg']))
            member_label.setFont(QFont(FONT_FAMILY, 10))
            member_label.setStyleSheet(f"color: {colors['bg']};")
            layout.addWidget(member_label)

            status_indicator = QLabel("●")
            status_indicator.setStyleSheet(f"color: {status_color};")
            layout.addWidget(status_indicator)

        layout.addStretch()

        return bar

    def _add_welcome_messages(self):
        """添加欢迎消息"""
        import time

        # 系统欢迎
        self.add_message(
            "系统", "system",
            "欢迎来到工作群！这是一个AI协作空间，项目经理将在这里协调各AI完成任务。",
            time.time(), "status"
        )

        # 项目经理消息
        self.add_message(
            "超级大脑", "项目经理",
            "各位同事，项目即将启动。我将负责任务分解和协调，请大家准备好接收任务。",
            time.time() + 0.5, "text"
        )

    def add_message(self, from_ai: str, role: str, content: str,
                    timestamp: float, msg_type: str = "text"):
        """添加消息"""
        bubble = MessageBubble(from_ai, role, content, timestamp, msg_type)

        # 在stretch之前插入
        self.message_layout.insertWidget(
            self.message_layout.count() - 1,
            bubble,
            0,
            Qt.AlignLeft
        )

        self._messages.append(bubble)

        # 滚动到底部
        QTimer.singleShot(100, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        """滚动到底部"""
        scroll = self.message_container.parent().parent()
        if isinstance(scroll, QScrollArea):
            vbar = scroll.verticalScrollBar()
            vbar.setValue(vbar.maximum())

    def resizeEvent(self, event):
        """窗口大小改变"""
        super().resizeEvent(event)
        self.starry_bg.setGeometry(0, 0, self.width(), self.height())


# ============================================================================
# 完整的工作群面板
# ============================================================================

class WorkGroupPanel(QWidget):
    """完整的工作群面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 聊天区域
        self.chat_area = WorkGroupChatArea()
        layout.addWidget(self.chat_area, stretch=1)

        # 设置背景
        self.setStyleSheet(f"background-color: {BG_DARK};")

    def add_message(self, from_ai: str, role: str, content: str,
                    msg_type: str = "text"):
        """添加消息"""
        import time
        self.chat_area.add_message(from_ai, role, content, time.time(), msg_type)