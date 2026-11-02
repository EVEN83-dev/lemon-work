# -*- coding: utf-8 -*-
"""
角色配置对话框
允许用户配置Agent的角色类型、AI引擎和模型
"""

import json
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QGroupBox, QFormLayout, QDialogButtonBox,
    QTabWidget, QWidget, QMessageBox, QTextEdit, QListWidget,
    QListWidgetItem, QAbstractItemView
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.theme import (
    LEMON_ORANGE, BG_PRIMARY, BG_SURFACE, TEXT_PRIMARY,
    TEXT_SECONDARY, BORDER_DEFAULT, SUCCESS, WARNING, ERROR
)
from ui.design.tokens import Lemon

# ★ v4.6 角色预设：role_key 对齐 hybrid_mode.core.work_agent.ROLE_META
# 每项：显示名 / 图标 / 推荐引擎 / 推荐模型 / 角色系统提示词
AGENT_ROLE_PRESETS = {
    'commander': {
        'name': '总指挥', 'icon': '🧠',
        'engine': 'ollama', 'model': 'qwen3.5:4b',
        'prompt': '你是项目总指挥，负责拆解需求、分配任务给各角色 Agent，并验收交付物（DoD）。',
    },
    'manager': {
        'name': '项目经理', 'icon': '📋',
        'engine': 'ollama', 'model': 'qwen3.5:4b',
        'prompt': '你是项目经理，负责按依赖排序任务、跟踪进度、协调各 Agent 的接口契约。',
    },
    'frontend': {
        'name': '前端架构师', 'icon': '🎨',
        'engine': 'ollama', 'model': 'qwen3.5:4b',
        'prompt': '你是前端架构师，负责页面结构、组件拆分、状态管理与样式实现。',
    },
    'backend': {
        'name': '后端架构师', 'icon': '⚙️',
        'engine': 'ollama', 'model': 'qwen3.5:4b',
        'prompt': '你是后端架构师，负责 API 设计、数据模型、业务逻辑与接口契约。',
    },
    'tester': {
        'name': '测试工程师', 'icon': '🔧',
        'engine': 'ollama', 'model': 'qwen3.5:4b',
        'prompt': '你是测试工程师，负责关键路径测试、边界条件校验与回归验证。',
    },
    'devops': {
        'name': '运维工程师', 'icon': '🚀',
        'engine': 'ollama', 'model': 'qwen3.5:4b',
        'prompt': '你是运维工程师，负责 CI/CD、部署、监控与故障恢复。',
    },
    'design': {
        'name': 'UI设计师', 'icon': '🎨',
        'engine': 'ollama', 'model': 'qwen3-vl:4b',
        'prompt': '你是 UI 设计师，负责视觉风格、布局与交互细节，确保品味统一。',
    },
    'document': {
        'name': '文档工程师', 'icon': '📝',
        'engine': 'ollama', 'model': 'qwen3.5:4b',
        'prompt': '你是文档工程师，负责 API 文档、使用说明与变更记录。',
    },
    'worker': {
        'name': '工作Agent', 'icon': '🤖',
        'engine': 'ollama', 'model': 'qwen3.5:4b',
        'prompt': '你是通用工作 Agent，负责执行分配的具体任务。',
    },
}


class RoleConfigDialog(QDialog):
    """角色配置对话框"""
    
    config_saved = pyqtSignal(dict)  # 配置保存信号
    
    def __init__(self, agent_data=None, parent=None):
        """
        Args:
            agent_data: 当前Agent数据，包含id, name, role等
        """
        super().__init__(parent)
        self.agent_data = agent_data or {}
        # ★ v4.6.1 工具白名单：全部可选 Skill 列表
        self._all_skills = [
            'execute_code', 'read_file', 'write_file', 'search_files',
            'math_solver', 'math_plotter', 'image_processor',
            'info_debater', 'web_researcher', 'office_generator',
        ]
        self.setWindowTitle("角色配置")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self._init_ui()
        self._load_current_config()
    
    def _init_ui(self):
        """初始化UI"""
        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_PRIMARY};
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
                font-size: 14px;
            }}
            QGroupBox {{
                color: {LEMON_ORANGE};
                font-weight: bold;
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
            }}
            QPushButton {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                border-color: {LEMON_ORANGE};
            }}
            QPushButton:pressed {{
                background: {LEMON_ORANGE};
            }}
            QComboBox {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 14px;
                min-width: 200px;
            }}
            QComboBox:hover {{
                border-color: {LEMON_ORANGE};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QSpinBox {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 14px;
            }}
            QSpinBox:hover {{
                border-color: {LEMON_ORANGE};
            }}
            QTabWidget::pane {{
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                background: {BG_PRIMARY};
            }}
            QTabBar::tab {{
                background: {BG_SURFACE};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT};
                padding: 8px 16px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {LEMON_ORANGE};
                color: white;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title_label = QLabel(f"⚙️ 配置 Agent: {self.agent_data.get('name', 'Unknown')}")
        title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {LEMON_ORANGE};")
        layout.addWidget(title_label)
        
        # Tab页
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # 基础配置Tab
        basic_tab = self._create_basic_tab()
        self.tab_widget.addTab(basic_tab, "基础配置")
        
        # AI引擎Tab
        ai_tab = self._create_ai_tab()
        self.tab_widget.addTab(ai_tab, "AI引擎")
        
        # 高级设置Tab
        advanced_tab = self._create_advanced_tab()
        self.tab_widget.addTab(advanced_tab, "高级设置")
        
        # ★ v4.6.1 工具白名单Tab（角色权限）
        skills_tab = self._create_skills_tab()
        self.tab_widget.addTab(skills_tab, "工具白名单")
        
        # 按钮区
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._on_ok)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def _create_basic_tab(self):
        """创建基础配置Tab"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Agent名称
        self.name_label = QLabel(self.agent_data.get('name', 'Agent 01'))
        layout.addRow("Agent名称:", self.name_label)
        
        # 角色类型（★ v4.6 对齐 ROLE_META 的 role_key）
        self.role_combo = QComboBox()
        self._role_keys = list(AGENT_ROLE_PRESETS.keys())
        self.role_combo.addItems(
            [f"{AGENT_ROLE_PRESETS[k]['name']} ({k})" for k in self._role_keys]
        )
        self.role_combo.currentIndexChanged.connect(self._on_role_changed)
        layout.addRow("角色类型:", self.role_combo)

        # 系统提示词（角色预设）
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setReadOnly(True)
        self.prompt_edit.setMaximumHeight(80)
        self.prompt_edit.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_SURFACE};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                font-size: 12px;
            }}
        """)
        layout.addRow("角色设定:", self.prompt_edit)

        # Agent状态
        self.status_label = QLabel(self.agent_data.get('status', 'idle'))
        self.status_label.setStyleSheet(f"color: {SUCCESS};")
        layout.addRow("当前状态:", self.status_label)
        
        # 工作进度
        self.progress_label = QLabel(f"{self.agent_data.get('progress', 0)}%")
        layout.addRow("工作进度:", self.progress_label)
        
        return widget
    
    def _create_ai_tab(self):
        """创建AI引擎配置Tab"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # AI引擎选择
        self.engine_combo = QComboBox()
        self.engine_combo.addItems([
            'ollama',
            'deepseek',
            'mimocode',
            'cloud_api',
        ])
        self.engine_combo.currentTextChanged.connect(self._on_engine_changed)
        layout.addRow("AI引擎:", self.engine_combo)
        
        # AI模型选择
        self.model_combo = QComboBox()
        self.model_combo.addItems([
            'qwen3.5:4b',
            'deepseek-coder',
            'gpt-4',
            'gpt-3.5-turbo',
        ])
        layout.addRow("AI模型:", self.model_combo)
        
        # 引擎状态
        self.engine_status_label = QLabel("就绪")
        self.engine_status_label.setStyleSheet(f"color: {SUCCESS}; font-weight: bold;")
        layout.addRow("引擎状态:", self.engine_status_label)
        
        # Token消耗
        self.token_label = QLabel("0 / 32000")
        layout.addRow("Token消耗:", self.token_label)
        
        return widget
    
    def _create_advanced_tab(self):
        """创建高级设置Tab"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 算力分配
        self.compute_spin = QSpinBox()
        self.compute_spin.setRange(1, 100)
        self.compute_spin.setValue(50)
        self.compute_spin.setSuffix("%")
        layout.addRow("算力分配:", self.compute_spin)
        
        # 超时设置
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 300)
        self.timeout_spin.setValue(60)
        self.timeout_spin.setSuffix("秒")
        layout.addRow("请求超时:", self.timeout_spin)
        
        # 重试次数
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 10)
        self.retry_spin.setValue(3)
        layout.addRow("重试次数:", self.retry_spin)
        
        # 温度参数
        self.temp_spin = QSpinBox()
        self.temp_spin.setRange(0, 100)
        self.temp_spin.setValue(70)
        self.temp_spin.setSuffix("%")
        layout.addRow("温度参数:", self.temp_spin)
        
        return widget
    
    def _create_skills_tab(self):
        """★ v4.6.1 工具白名单（角色权限）：勾选该角色可使用的 Skill"""
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.setSpacing(10)
        
        tip = QLabel("按角色预设勾选可用工具；取消勾选将禁止该 Agent 调用对应 Skill。")
        tip.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        tip.setWordWrap(True)
        outer.addWidget(tip)
        
        self.skills_list = QListWidget()
        self.skills_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.skills_list.setStyleSheet(f"""
            QListWidget {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
            }}
            QListWidget::item {{ padding: 5px 8px; }}
            QListWidget::item:selected {{ background: {LEMON_ORANGE}; color: #000; }}
        """)
        outer.addWidget(self.skills_list)
        self.skills_list.itemChanged.connect(lambda *_: setattr(self, '_skills_dirty', True))
        return widget
    
    def _refresh_skills_list(self, checked_set):
        """刷新白名单勾选列表"""
        self.skills_list.clear()
        for skill in self._all_skills:
            item = QListWidgetItem(skill)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if skill in checked_set else Qt.Unchecked)
            self.skills_list.addItem(item)
    
    def _load_current_config(self):
        """加载当前配置"""
        # 设置角色（role 字段是 role_key，如 'frontend'）
        role = self.agent_data.get('role', 'frontend')
        if role in self._role_keys:
            idx = self._role_keys.index(role)
            self.role_combo.setCurrentIndex(idx)
            self._update_prompt(idx)

        # 设置引擎和模型
        engine = self.agent_data.get('ai_engine', 'ollama')
        model = self.agent_data.get('ai_model', 'qwen3.5:4b')
        
        index = self.engine_combo.findText(engine)
        if index >= 0:
            self.engine_combo.setCurrentIndex(index)
        
        index = self.model_combo.findText(model)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)

        # ★ v4.6.1 工具白名单：已保存的覆盖默认，否则用角色预设
        saved = self.agent_data.get('allowed_skills') or ROLE_SKILLS_MAP.get(role, [])
        self._refresh_skills_list(set(saved))
    
    def _on_role_changed(self, index):
        """角色切换时更新系统提示词展示 + 白名单预设"""
        self._update_prompt(index)
        # 自动套用该角色的推荐引擎/模型
        if 0 <= index < len(self._role_keys):
            preset = AGENT_ROLE_PRESETS[self._role_keys[index]]
            ei = self.engine_combo.findText(preset['engine'])
            if ei >= 0:
                self.engine_combo.setCurrentIndex(ei)
            mi = self.model_combo.findText(preset['model'])
            if mi >= 0:
                self.model_combo.setCurrentIndex(mi)
            # ★ v4.6.1 切角色时自动套用该角色默认白名单（除非用户已手动改过）
            if not getattr(self, '_skills_dirty', False):
                rk = self._role_keys[index]
                self._refresh_skills_list(set(ROLE_SKILLS_MAP.get(rk, [])))
    
    def _update_prompt(self, index):
        """更新角色系统提示词文本"""
        if 0 <= index < len(self._role_keys):
            preset = AGENT_ROLE_PRESETS[self._role_keys[index]]
            self.prompt_edit.setPlainText(preset.get('prompt', ''))
    
    def _on_engine_changed(self, engine_name):
        """引擎改变时更新模型列表"""
        models = {
            'ollama': ['qwen3.5:4b', 'qwen3.5:9b'],
            'deepseek': ['deepseek-coder', 'deepseek-chat'],
            'mimocode': ['default'],
            'cloud_api': ['gpt-4', 'gpt-3.5-turbo', 'claude-3'],
        }
        
        self.model_combo.clear()
        self.model_combo.addItems(models.get(engine_name, ['default']))
    
    def _on_ok(self):
        """确认保存"""
        role_idx = self.role_combo.currentIndex()
        role_key = self._role_keys[role_idx] if 0 <= role_idx < len(self._role_keys) else 'worker'
        # ★ v4.6.1 收集白名单
        checked = []
        for i in range(self.skills_list.count()):
            it = self.skills_list.item(i)
            if it.checkState() == Qt.Checked:
                checked.append(it.text())
        config = {
            'agent_id': self.agent_data.get('id'),
            'name': self.name_label.text(),
            'role': role_key,                       # ★ v4.6 存 role_key，而非中文显示名
            'role_display': AGENT_ROLE_PRESETS[role_key]['name'],
            'ai_engine': self.engine_combo.currentText(),
            'ai_model': self.model_combo.currentText(),
            'compute_ratio': self.compute_spin.value(),
            'timeout': self.timeout_spin.value(),
            'max_retries': self.retry_spin.value(),
            'temperature': self.temp_spin.value() / 100.0,
            'system_prompt': AGENT_ROLE_PRESETS[role_key].get('prompt', ''),
            'allowed_skills': checked,            # ★ v4.6.1 工具白名单
        }
        
        self.config_saved.emit(config)
        self.accept()
    
    def get_config(self):
        """获取配置"""
        role_idx = self.role_combo.currentIndex()
        role_key = self._role_keys[role_idx] if 0 <= role_idx < len(self._role_keys) else 'worker'
        checked = []
        for i in range(self.skills_list.count()):
            it = self.skills_list.item(i)
            if it.checkState() == Qt.Checked:
                checked.append(it.text())
        return {
            'agent_id': self.agent_data.get('id'),
            'role': role_key,
            'ai_engine': self.engine_combo.currentText(),
            'ai_model': self.model_combo.currentText(),
            'compute_ratio': self.compute_spin.value(),
            'timeout': self.timeout_spin.value(),
            'max_retries': self.retry_spin.value(),
            'temperature': self.temp_spin.value() / 100.0,
            'allowed_skills': checked,
        }


class ModeSwitchDialog(QDialog):
    """模式切换对话框"""
    
    mode_changed = pyqtSignal(str)  # 模式切换信号
    
    def __init__(self, current_mode='normal', parent=None):
        super().__init__(parent)
        self.current_mode = current_mode
        self.setWindowTitle("切换模式")
        self.setMinimumWidth(400)
        self._init_ui()
    
    def _init_ui(self):
        """初始化UI"""
        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_PRIMARY};
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
                font-size: 14px;
            }}
            QPushButton {{
                background: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 2px solid {BORDER_DEFAULT};
                border-radius: 8px;
                padding: 15px;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border-color: {LEMON_ORANGE};
                background: rgba(255, 105, 0, 0.1);
            }}
            QPushButton:checked {{
                border-color: {LEMON_ORANGE};
                background: {LEMON_ORANGE};
                color: white;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 标题
        title = QLabel("🔄 切换工作模式")
        title.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {LEMON_ORANGE};")
        layout.addWidget(title)
        
        # 当前模式
        current_label = QLabel(f"当前模式: {self.current_mode}")
        current_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(current_label)
        
        # 模式按钮
        modes = [
            ('normal', '📱 普通模式', '单AI助手模式'),
            ('hybrid', '🔀 混合模式', '多Agent协作模式'),
            ('multi_instance', '👥 多实例模式', '多MIMO实例模式'),
        ]
        
        self.mode_buttons = {}
        
        for mode_id, mode_name, mode_desc in modes:
            btn = QPushButton(f"{mode_name}\n{mode_desc}")
            btn.setCheckable(True)
            btn.setChecked(mode_id == self.current_mode)
            btn.clicked.connect(lambda checked, m=mode_id: self._on_mode_clicked(m))
            layout.addWidget(btn)
            self.mode_buttons[mode_id] = btn
        
        # 确认按钮
        confirm_btn = QPushButton("✓ 确认切换")
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background: {LEMON_ORANGE};
                color: white;
                border: none;
                padding: 12px;
            }}
            QPushButton:hover {{
                background: {Lemon.BRAND_ORANGE_LIGHT};
            }}
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        layout.addWidget(confirm_btn)
        
        # 取消按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)
    
    def _on_mode_clicked(self, mode_id):
        """模式按钮点击"""
        for mid, btn in self.mode_buttons.items():
            btn.setChecked(mid == mode_id)
        self.selected_mode = mode_id
    
    def _on_confirm(self):
        """确认切换"""
        if hasattr(self, 'selected_mode'):
            self.mode_changed.emit(self.selected_mode)
        self.accept()
    
    def get_selected_mode(self):
        """获取选中的模式"""
        return getattr(self, 'selected_mode', self.current_mode)