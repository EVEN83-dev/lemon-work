# -*- coding: utf-8 -*-
"""v6.0-H 混合模式前端组件包
★ 第454章：原目录名 hybrid_mode 与仓库根 hybrid_mode 包同名冲突——ui 目录
被多处裸插入 sys.path，顶层 `import hybrid_mode` 永远先命中本目录（无 core
子模块），导致 HybridModeWebPanel 桥初始化 ModuleNotFoundError。改名让位。
"""

from ui.hybrid_mode_widgets_legacy.agent_card import AgentCard, StatusDot
from ui.hybrid_mode_widgets_legacy.agent_grid import AgentGrid
from ui.hybrid_mode_widgets_legacy.add_agent_dialog import AddAgentDialog, TerminateConfirmDialog
from ui.hybrid_mode_widgets_legacy.task_flow_timeline import TaskFlowTimeline, DependencyGraphView, GanttChartView
from ui.hybrid_mode_widgets_legacy.agent_chat_stream import AgentChatStream, MessageBubble
