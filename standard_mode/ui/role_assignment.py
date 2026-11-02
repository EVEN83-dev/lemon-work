# -*- coding: utf-8 -*-
"""
Lemon Agent 角色分配面板
==========================
实现多窗口角色分配系统：
1. 指挥官（Director）— 任务分配、进度聚合
2. 前端开发（Frontend）— UI 实现
3. 后端开发（Backend）— API 实现
4. 代码审查（Reviewer）— 质量检查
5. 测试验证（Tester）— 功能验证

支持：
- 角色切换（Tab 式）
- 任务分发（基于任务类型自动分配）
- 进度聚合（Director 汇总所有角色进度）
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QFrame, QScrollArea, QGridLayout, QProgressBar,
    QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor

from ui.theme import get_theme_colors
from ui.worksheet_panel import AgentRole, ROLE_CONFIG, TaskStatus
from ui.design.tokens import Lemon


# ============================================================================
# 角色面板
# ============================================================================

class RolePanel(QWidget):
    """单个角色的工作面板"""

    task_updated = pyqtSignal(str, str, dict)  # role, task_id, task_data

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self._role = role
        self._tasks: Dict[str, Dict] = {}
        self._init_ui()

    def _init_ui(self):
        config = ROLE_CONFIG.get(self._role, {})
        colors = get_theme_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ===== 头部：角色信息 =====
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {config.get('color', '#333')};
                border-radius: 8px;
                padding: 10px;
            }}
            QLabel {{
                color: white;
            }}
        """)
        header_layout = QHBoxLayout(header)

        icon_label = QLabel(config.get('icon', '👤'))
        icon_label.setFont(QFont("", 24))
        header_layout.addWidget(icon_label)

        name_label = QLabel(config.get('name', self._role))
        name_label.setFont(QFont("", 14, QFont.Bold))
        header_layout.addWidget(name_label)

        header_layout.addStretch()

        # 任务计数
        self._task_count_label = QLabel("0 任务")
        header_layout.addWidget(self._task_count_label)

        layout.addWidget(header)

        # ===== 进度条 =====
        progress_frame = QFrame()
        progress_layout = QHBoxLayout(progress_frame)
        progress_layout.setContentsMargins(0, 0, 0, 0)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFormat("%v/%m (%p%)")
        progress_layout.addWidget(self._progress_bar)

        layout.addWidget(progress_frame)

        # ===== 任务列表（滚动区域） =====
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self._task_container = QWidget()
        self._task_layout = QVBoxLayout(self._task_container)
        self._task_layout.setSpacing(4)
        self._task_layout.addStretch()

        scroll.setWidget(self._task_container)
        layout.addWidget(scroll)

        self.setLayout(layout)

    def add_task(self, task_id: str, task_data: Dict):
        """添加任务"""
        self._tasks[task_id] = task_data
        self._refresh()

    def remove_task(self, task_id: str):
        """移除任务"""
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._refresh()

    def update_task(self, task_id: str, task_data: Dict):
        """更新任务"""
        if task_id in self._tasks:
            self._tasks[task_id] = task_data
            self._refresh()

    def _refresh(self):
        """刷新显示"""
        # 更新计数
        self._task_count_label.setText(f"{len(self._tasks)} 任务")

        # 更新进度
        total = len(self._tasks)
        completed = sum(1 for t in self._tasks.values() if t.get("status") == TaskStatus.COMPLETED)
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(completed)

        # 清空并重建任务列表
        # （简化实现，实际应用中应增量更新）
        while self._task_layout.count() > 1:
            item = self._task_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for task_id, task in self._tasks.items():
            task_widget = self._create_task_widget(task_id, task)
            self._task_layout.insertWidget(self._task_layout.count() - 1, task_widget)

    def _create_task_widget(self, task_id: str, task: Dict) -> QFrame:
        """创建任务小部件"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: {Lemon.DARK_MID_4};
                border-radius: 4px;
                padding: 8px;
            }
        """)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)

        # 任务名称
        name_label = QLabel(task.get("name", ""))
        layout.addWidget(name_label)

        layout.addStretch()

        # 状态图标
        status = task.get("status", TaskStatus.PENDING)
        status_icons = {
            TaskStatus.PENDING: "⏳",
            TaskStatus.RUNNING: "▶️",
            TaskStatus.COMPLETED: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.SKIPPED: "⏭️",
        }
        status_label = QLabel(status_icons.get(status, "⏳"))
        layout.addWidget(status_label)

        return frame

    def get_progress(self) -> Dict:
        """获取进度信息"""
        total = len(self._tasks)
        completed = sum(1 for t in self._tasks.values() if t.get("status") == TaskStatus.COMPLETED)
        running = sum(1 for t in self._tasks.values() if t.get("status") == TaskStatus.RUNNING)
        failed = sum(1 for t in self._tasks.values() if t.get("status") == TaskStatus.FAILED)

        return {
            "role": self._role,
            "total": total,
            "completed": completed,
            "running": running,
            "failed": failed,
            "progress": completed / total if total > 0 else 0,
        }


# ============================================================================
# 角色分配管理器
# ============================================================================

class RoleAssignmentManager(QWidget):
    """角色分配管理器 — Tab 式多角色面板"""

    # 信号
    role_changed = pyqtSignal(str)  # role

    def __init__(self, parent=None):
        super().__init__(parent)
        self._role_panels: Dict[str, RolePanel] = {}
        self._current_role = AgentRole.DIRECTOR
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ===== Tab 切换 =====
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabPosition(QTabWidget.North)
        self._tab_widget.setDocumentMode(True)

        # 为每个角色创建面板
        for role, config in ROLE_CONFIG.items():
            panel = RolePanel(role)
            self._role_panels[role] = panel

            # 添加 Tab
            self._tab_widget.addTab(panel, f"{config['icon']} {config['name']}")

        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self._tab_widget)

        self.setLayout(layout)

    def _on_tab_changed(self, index: int):
        """Tab 切换"""
        roles = list(ROLE_CONFIG.keys())
        if 0 <= index < len(roles):
            self._current_role = roles[index]
            self.role_changed.emit(self._current_role)

    def assign_task(self, task_id: str, task_data: Dict, role: str = None):
        """分配任务到角色"""
        if role is None:
            role = self._infer_role(task_data)

        if role in self._role_panels:
            self._role_panels[role].add_task(task_id, task_data)

    def _infer_role(self, task_data: Dict) -> str:
        """根据任务内容推断角色"""
        name = task_data.get("name", "").lower()
        desc = task_data.get("description", "").lower()
        text = name + " " + desc

        # 关键词匹配
        if any(kw in text for kw in ["前端", "ui", "界面", "css", "html", "vue", "react", "frontend"]):
            return AgentRole.FRONTEND
        elif any(kw in text for kw in ["后端", "api", "数据库", "服务", "backend", "api", "database"]):
            return AgentRole.BACKEND
        elif any(kw in text for kw in ["审查", "review", "检查", "代码质量", "lint"]):
            return AgentRole.REVIEWER
        elif any(kw in text for kw in ["测试", "test", "验证", "验收"]):
            return AgentRole.TESTER
        else:
            return AgentRole.DIRECTOR

    def update_task_status(self, role: str, task_id: str, status: str):
        """更新任务状态"""
        if role in self._role_panels:
            panel = self._role_panels[role]
            if task_id in panel._tasks:
                panel._tasks[task_id]["status"] = status
                panel._refresh()

    def get_aggregated_progress(self) -> Dict:
        """获取聚合进度（Director 用）"""
        progress = {}
        for role, panel in self._role_panels.items():
            progress[role] = panel.get_progress()
        return progress

    def get_role_panel(self, role: str) -> Optional[RolePanel]:
        """获取角色面板"""
        return self._role_panels.get(role)


# ============================================================================
# 多窗口网格布局
# ============================================================================

class MultiRoleGrid(QWidget):
    """多角色网格布局 — 支持切换单窗口/多窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._role_manager = RoleAssignmentManager()
        self._layout_mode = "single"  # single | multi
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 切换按钮
        btn_frame = QFrame()
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(8, 4, 8, 4)

        self._btn_single = QPushButton("单窗口")
        self._btn_single.setCheckable(True)
        self._btn_single.setChecked(True)
        self._btn_single.clicked.connect(lambda: self._switch_layout("single"))
        btn_layout.addWidget(self._btn_single)

        self._btn_multi = QPushButton("多窗口")
        self._btn_multi.setCheckable(True)
        self._btn_multi.clicked.connect(lambda: self._switch_layout("multi"))
        btn_layout.addWidget(self._btn_multi)

        btn_layout.addStretch()
        layout.addWidget(btn_frame)

        # 内容区域
        self._content_frame = QFrame()
        self._content_layout = QHBoxLayout(self._content_frame)
        self._content_layout.setContentsMargins(0, 0, 0, 0)

        self._content_layout.addWidget(self._role_manager)
        layout.addWidget(self._content_frame)

        self.setLayout(layout)

    def _switch_layout(self, mode: str):
        """切换布局"""
        self._layout_mode = mode

        if mode == "single":
            self._btn_single.setChecked(True)
            self._btn_multi.setChecked(False)
            # Tab 式显示
            self._role_manager._tab_widget.tabBar().show()
        else:
            self._btn_single.setChecked(False)
            self._btn_multi.setChecked(True)
            # 多窗口显示（简化：仍用 Tab，但可以扩展为真正的多窗口）
            self._role_manager._tab_widget.tabBar().show()

    def get_role_manager(self) -> RoleAssignmentManager:
        """获取角色管理器"""
        return self._role_manager