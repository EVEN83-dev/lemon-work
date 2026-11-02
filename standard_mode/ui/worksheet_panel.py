# -*- coding: utf-8 -*-
"""
Lemon Agent WorksheetPanel — 全局工作表面板
===============================================
实现功能：
1. 任务列表显示（树形结构）
2. 任务状态管理（pending/running/completed/failed）
3. 引擎切换（MIMO/Ollama/DeepSeek）
4. 模式切换（Build/Plan/Compose）
5. 进度统计
6. 与 TaskEngine 集成
7. 任务完成自动划去（Build 模式）
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QComboBox, QProgressBar,
    QFrame, QSplitter, QMenu, QAction, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QIcon, QColor, QFont

# 项目内导入
from ui.theme import get_theme_colors, svg_to_qicon
from core.task_engine import TaskEngine, TaskTree, TaskDecomposer
from core.agent_guard import get_agent_guard, AgentGuard
from ui.design.tokens import Lemon


# ============================================================================
# 任务状态
# ============================================================================

class TaskStatus:
    """任务状态"""
    PENDING = "pending"      # 等待中
    RUNNING = "running"      # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败
    SKIPPED = "skipped"      # 跳过


# ============================================================================
# 工作模式
# ============================================================================

class WorkMode:
    """工作模式"""
    BUILD = "build"    # 构建模式 — 任务完成自动划去
    PLAN = "plan"      # 规划模式 — 5 步标准流程
    COMPOSE = "compose"  # 编辑模式 — 自由编辑


# ============================================================================
# 角色定义
# ============================================================================

class AgentRole:
    """Agent 角色（多窗口模式）"""
    DIRECTOR = "director"      # 指挥官 — 任务分配、进度聚合
    FRONTEND = "frontend"      # 前端开发
    BACKEND = "backend"        # 后端开发
    REVIEWER = "reviewer"      # 代码审查
    TESTER = "tester"          # 测试验证


ROLE_CONFIG = {
    AgentRole.DIRECTOR: {"name": "指挥官", "color": "{Lemon.ACCENT_GOLD}", "icon": "target"},
    AgentRole.FRONTEND: {"name": "前端开发", "color": "{Lemon.ACCENT_BLUE}", "icon": "palette"},
    AgentRole.BACKEND: {"name": "后端开发", "color": "{Lemon.ACCENT_GREEN}", "icon": "settings"},
    AgentRole.REVIEWER: {"name": "代码审查", "color": "{Lemon.ACCENT_PURPLE}", "icon": "search"},
    AgentRole.TESTER: {"name": "测试验证", "color": "{Lemon.DARK_MIMO_ORANGE}", "icon": "check"},
}


# ============================================================================
# WorksheetPanel
# ============================================================================

class WorksheetPanel(QWidget):
    """全局工作表面板"""

    # 信号
    task_status_changed = pyqtSignal(str, str)  # task_id, status
    engine_changed = pyqtSignal(str)  # engine_id
    mode_changed = pyqtSignal(str)  # mode

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: Dict[str, Dict] = {}  # task_id -> task_data
        self._task_order: List[str] = []  # 任务顺序
        self._current_engine = "ollama"
        self._current_mode = WorkMode.BUILD
        self._current_role = AgentRole.DIRECTOR

        self._init_ui()
        self._init_connections()
        self._load_persisted()

    # ==================== UI 初始化 ====================

    def _init_ui(self):
        """初始化 UI"""
        colors = get_theme_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ===== 头部：引擎/模式切换 + 进度 =====
        header_frame = QFrame()
        header_frame.setObjectName("worksheet_header")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # 引擎切换
        self._engine_combo = QComboBox()
        self._engine_combo.addItems(["mimocode", "ollama", "deepseek"])
        self._engine_combo.setCurrentText(self._current_engine)
        self._engine_combo.setFixedWidth(100)
        header_layout.addWidget(QLabel("引擎:"))
        header_layout.addWidget(self._engine_combo)

        header_layout.addSpacing(10)

        # 模式切换
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Build", "Plan", "Compose"])
        self._mode_combo.setCurrentText("Build")
        self._mode_combo.setFixedWidth(80)
        header_layout.addWidget(QLabel("模式:"))
        header_layout.addWidget(self._mode_combo)

        header_layout.addSpacing(10)

        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(120)
        self._progress_bar.setFixedHeight(20)
        self._progress_bar.setFormat("%v/%m (%p%)")
        header_layout.addWidget(self._progress_bar)

        header_layout.addStretch()

        # 统计标签
        self._stats_label = QLabel("0 完成 / 0 总数")
        header_layout.addWidget(self._stats_label)

        layout.addWidget(header_frame)

        # ===== 任务树 =====
        self._task_tree = QTreeWidget()
        self._task_tree.setHeaderLabels(["任务", "状态", "引擎", "角色"])
        self._task_tree.setColumnWidth(0, 300)
        self._task_tree.setColumnWidth(1, 80)
        self._task_tree.setColumnWidth(2, 80)
        self._task_tree.setColumnWidth(3, 80)
        self._task_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._task_tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._task_tree)

        # ===== 底部：快捷操作 =====
        footer_frame = QFrame()
        footer_layout = QHBoxLayout(footer_frame)
        footer_layout.setContentsMargins(0, 0, 0, 0)

        self._btn_add = QPushButton("新建")
        self._btn_add.setIcon(svg_to_qicon("plus", size=14))
        self._btn_add.setFixedWidth(80)
        footer_layout.addWidget(self._btn_add)

        self._btn_decompose = QPushButton("分解")
        self._btn_decompose.setIcon(svg_to_qicon("search", size=14))
        self._btn_decompose.setFixedWidth(80)
        footer_layout.addWidget(self._btn_decompose)

        self._btn_run = QPushButton("执行")
        self._btn_run.setIcon(svg_to_qicon("run", size=14))
        self._btn_run.setFixedWidth(80)
        footer_layout.addWidget(self._btn_run)

        self._btn_clear = QPushButton("清空")
        self._btn_clear.setIcon(svg_to_qicon("trash", size=14))
        self._btn_clear.setFixedWidth(80)
        footer_layout.addWidget(self._btn_clear)

        footer_layout.addStretch()

        # Plan 模式快捷按钮
        self._btn_plan_template = QPushButton("📋 Plan 模板")
        self._btn_plan_template.setFixedWidth(100)
        self._btn_plan_template.setToolTip("应用 5 步标准流程模板")
        footer_layout.addWidget(self._btn_plan_template)

        layout.addWidget(footer_frame)

        self.setLayout(layout)

    def _init_connections(self):
        """初始化信号连接"""
        self._engine_combo.currentTextChanged.connect(self._on_engine_changed)
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        self._btn_add.clicked.connect(self._on_add_task)
        self._btn_decompose.clicked.connect(self._on_decompose)
        self._btn_run.clicked.connect(self._on_run_selected)
        self._btn_clear.clicked.connect(self._on_clear)
        self._btn_plan_template.clicked.connect(self._apply_plan_template)

        # 双击任务切换状态
        self._task_tree.itemDoubleClicked.connect(self._on_task_double_clicked)

    # ==================== 任务管理 ====================

    def add_task(self, name: str, description: str = "",
                 engine: str = None, role: str = None,
                 dependencies: List[str] = None) -> str:
        """添加任务"""
        import uuid
        task_id = str(uuid.uuid4())[:8]

        task_data = {
            "id": task_id,
            "name": name,
            "description": description,
            "status": TaskStatus.PENDING,
            "engine": engine or self._current_engine,
            "role": role or self._current_role,
            "dependencies": dependencies or [],
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
        }

        self._tasks[task_id] = task_data
        self._task_order.append(task_id)

        self._refresh_task_tree()
        self._persist()

        return task_id

    def update_task_status(self, task_id: str, status: str):
        """更新任务状态"""
        if task_id not in self._tasks:
            return

        self._tasks[task_id]["status"] = status

        if status == TaskStatus.COMPLETED:
            self._tasks[task_id]["completed_at"] = datetime.now().isoformat()

            # Build 模式：任务完成自动划去（视觉上变灰）
            if self._current_mode == WorkMode.BUILD:
                self._mark_task_completed_visual(task_id)

        self._refresh_task_tree()
        self._update_progress()
        self._persist()

        self.task_status_changed.emit(task_id, status)

    def _mark_task_completed_visual(self, task_id: str):
        """视觉上标记任务为已完成（Build 模式）"""
        for i in range(self._task_tree.topLevelItemCount()):
            item = self._task_tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == task_id:
                # 设置灰色字体
                font = item.font(0)
                font.setStrikeOut(True)
                item.setFont(0, font)
                item.setForeground(0, QColor("Lemon.SECONDARY"))
                break

    def remove_task(self, task_id: str):
        """移除任务"""
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._task_order.remove(task_id)
            self._refresh_task_tree()
            self._persist()

    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务"""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[Dict]:
        """获取所有任务"""
        return [self._tasks[tid] for tid in self._task_order if tid in self._tasks]

    def get_pending_tasks(self) -> List[Dict]:
        """获取待执行任务"""
        return [t for t in self.get_all_tasks() if t["status"] == TaskStatus.PENDING]

    # ==================== 任务树刷新 ====================

    def _refresh_task_tree(self):
        """刷新任务树"""
        self._task_tree.clear()

        for task_id in self._task_order:
            task = self._tasks.get(task_id)
            if not task:
                continue

            item = QTreeWidgetItem()
            item.setText(0, task["name"])
            item.setText(1, self._status_to_text(task["status"]))
            item.setText(2, task["engine"])
            role_cfg = ROLE_CONFIG.get(task["role"], {})
            item.setIcon(3, svg_to_qicon(role_cfg.get("icon", "user"), size=16, color=role_cfg.get("color")))
            item.setText(3, role_cfg.get("name", ""))

            # 状态颜色
            color = self._status_to_color(task["status"])
            item.setForeground(1, QColor(color))

            # 存储 task_id
            item.setData(0, Qt.UserRole, task_id)

            # 已完成任务在 Build 模式下变灰
            if self._current_mode == WorkMode.BUILD and task["status"] == TaskStatus.COMPLETED:
                font = item.font(0)
                font.setStrikeOut(True)
                item.setFont(0, font)
                item.setForeground(0, QColor("Lemon.SECONDARY"))

            self._task_tree.addTopLevelItem(item)

        self._update_progress()

    def _status_to_text(self, status: str) -> str:
        """状态转文本"""
        mapping = {
            TaskStatus.PENDING: "等待",
            TaskStatus.RUNNING: "执行",
            TaskStatus.COMPLETED: "完成",
            TaskStatus.FAILED: "失败",
            TaskStatus.SKIPPED: "跳过",
        }
        return mapping.get(status, status)

    def _status_to_color(self, status: str) -> str:
        """状态转颜色"""
        mapping = {
            TaskStatus.PENDING: "Lemon.SECONDARY",
            TaskStatus.RUNNING: "{Lemon.ACCENT_BLUE}",
            TaskStatus.COMPLETED: "{Lemon.ACCENT_GREEN}",
            TaskStatus.FAILED: "Lemon.ACCENT_RED",
            TaskStatus.SKIPPED: "#95A5A6",
        }
        return mapping.get(status, "Lemon.SECONDARY")

    def _update_progress(self):
        """更新进度"""
        total = len(self._tasks)
        completed = sum(1 for t in self._tasks.values() if t["status"] == TaskStatus.COMPLETED)

        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(completed)
        self._stats_label.setText(f"{completed} 完成 / {total} 总数")

    # ==================== 模式相关 ====================

    def _apply_plan_template(self):
        """应用 Plan 模板（5 步标准流程）"""
        if self._current_mode != WorkMode.PLAN:
            QMessageBox.information(self, "提示", "请先切换到 Plan 模式")
            return

        # 清空现有任务
        self._tasks.clear()
        self._task_order.clear()

        # 添加标准 5 步
        template = [
            ("需求分析", "分析需求文档、提取关键点、识别风险"),
            ("代码调研", "搜索相关代码、分析依赖、评估可行性"),
            ("方案设计", "设计架构、确定技术栈、编写设计文档"),
            ("实施变更", "编码、测试、调试"),
            ("交付验收", "运行验证脚本、生成报告、用户确认"),
        ]

        for name, desc in template:
            self.add_task(name, desc)

        QMessageBox.information(self, "Plan 模板", "已应用 5 步标准流程模板")

    # ==================== 事件处理 ====================

    def _on_engine_changed(self, engine: str):
        """引擎切换"""
        self._current_engine = engine.lower()
        self.engine_changed.emit(self._current_engine)
        self._persist()

    def _on_mode_changed(self, mode: str):
        """模式切换"""
        mode_map = {"Build": WorkMode.BUILD, "Plan": WorkMode.PLAN, "Compose": WorkMode.COMPOSE}
        self._current_mode = mode_map.get(mode, WorkMode.BUILD)
        self.mode_changed.emit(self._current_mode)
        self._refresh_task_tree()  # 刷新以应用模式视觉效果
        self._update_progress()   # 更新进度显示
        self._persist()
        # 人性化设计：模式切换时更新标题
        mode_names = {WorkMode.BUILD: "构建模式", WorkMode.PLAN: "计划模式", WorkMode.COMPOSE: "组合模式"}
        if hasattr(self, '_header_label'):
            self._header_label.setText(f"任务工作表 — {mode_names.get(self._current_mode, '构建模式')}")

    def _on_add_task(self):
        """添加任务"""
        # 简单输入对话框
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "新建任务", "任务名称:")
        if ok and name:
            self.add_task(name)

    def _on_decompose(self):
        """分解选中任务"""
        item = self._task_tree.currentItem()
        if not item:
            return

        task_id = item.data(0, Qt.UserRole)
        task = self.get_task(task_id)
        if not task:
            return

        # 使用 TaskDecomposer 分解
        subtasks = TaskDecomposer.decompose(task["name"])
        if subtasks:
            for subtask in subtasks:
                name = subtask.get("name", subtask.get("description", ""))
                self.add_task(name, dependencies=[task_id])

            QMessageBox.information(self, "分解完成", f"已分解为 {len(subtasks)} 个子任务")

    def _on_run_selected(self):
        """执行选中任务"""
        item = self._task_tree.currentItem()
        if not item:
            return

        task_id = item.data(0, Qt.UserRole)
        self.update_task_status(task_id, TaskStatus.RUNNING)

        # 模拟执行（实际应调用 EngineManager）
        QTimer.singleShot(2000, lambda: self.update_task_status(task_id, TaskStatus.COMPLETED))

    def _on_clear(self):
        """清空任务"""
        reply = QMessageBox.question(self, "确认", "确定要清空所有任务吗？")
        if reply == QMessageBox.Yes:
            self._tasks.clear()
            self._task_order.clear()
            self._refresh_task_tree()
            self._persist()

    def _on_task_double_clicked(self, item: QTreeWidgetItem, column: int):
        """双击任务切换状态"""
        task_id = item.data(0, Qt.UserRole)
        task = self.get_task(task_id)
        if not task:
            return

        # 循环切换状态
        status_order = [TaskStatus.PENDING, TaskStatus.COMPLETED, TaskStatus.SKIPPED]
        current_idx = status_order.index(task["status"]) if task["status"] in status_order else 0
        next_status = status_order[(current_idx + 1) % len(status_order)]

        self.update_task_status(task_id, next_status)

    def _show_context_menu(self, pos):
        """显示右键菜单"""
        item = self._task_tree.itemAt(pos)
        if not item:
            return

        task_id = item.data(0, Qt.UserRole)

        menu = QMenu(self)
        action_run = menu.addAction("执行")
        action_run.setIcon(svg_to_qicon("run", size=14))
        action_complete = menu.addAction("标记完成")
        action_complete.setIcon(svg_to_qicon("check", size=14))
        action_skip = menu.addAction("跳过")
        action_skip.setIcon(svg_to_qicon("chevron_right", size=14))
        menu.addSeparator()
        action_delete = menu.addAction("删除")
        action_delete.setIcon(svg_to_qicon("trash", size=14))

        action = menu.exec_(self._task_tree.mapToGlobal(pos))

        if action == action_run:
            self.update_task_status(task_id, TaskStatus.RUNNING)
        elif action == action_complete:
            self.update_task_status(task_id, TaskStatus.COMPLETED)
        elif action == action_skip:
            self.update_task_status(task_id, TaskStatus.SKIPPED)
        elif action == action_delete:
            self.remove_task(task_id)

    # ==================== 持久化 ====================

    def _persist(self):
        """持久化到文件"""
        try:
            data = {
                "tasks": self._tasks,
                "task_order": self._task_order,
                "engine": self._current_engine,
                "mode": self._current_mode,
                "role": self._current_role,
                "updated_at": datetime.now().isoformat(),
            }
            path = os.path.join(os.path.dirname(__file__), "..", "config", "worksheet.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Worksheet] 持久化失败: {e}")

    def _load_persisted(self):
        """从文件加载"""
        try:
            path = os.path.join(os.path.dirname(__file__), "..", "config", "worksheet.json")
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._tasks = data.get("tasks", {})
            self._task_order = data.get("task_order", [])
            self._current_engine = data.get("engine", "ollama")
            self._current_mode = data.get("mode", WorkMode.BUILD)
            self._current_role = data.get("role", AgentRole.DIRECTOR)

            self._engine_combo.setCurrentText(self._current_engine)
            self._mode_combo.setCurrentText(self._current_mode.capitalize())

            self._refresh_task_tree()
        except Exception as e:
            print(f"[Worksheet] 加载失败: {e}")