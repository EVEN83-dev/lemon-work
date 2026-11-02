# -*- coding: utf-8 -*-
"""
shared/commander_core — 跨模式编排核心
======================================
抽取咩咩引擎 (MiemieEngine) 与混合模式 (Hybrid Director) 共用的编排逻辑：
  1. Plan/Task 数据结构与分解
  2. 通用任务执行循环 (strategy pattern)
  3. 跨会话/Agent 消息总线
  4. 进度追踪与报告

设计原则：
  - 纯数据 + 策略注入，不依赖 PyQt（可选信号支持由上层包装）
  - 咩咩和混合模式各自保留 UI 信号层，core 只做逻辑
  - 所有引擎调用通过 EngineManager 抽象层，不直接绑定 Ollama/MIMO
"""

from .plan import Plan, Step, Task, decompose_goal, parse_llm_tasks
from .executor import PlanExecutor, AbstractExecutionStrategy, ToolRegistry
from .session_bus import SessionBus, SessionMessage
from .progress import ProgressTracker, ExecutionRecord

__all__ = [
    "Plan", "Step", "Task",
    "decompose_goal", "parse_llm_tasks",
    "PlanExecutor", "AbstractExecutionStrategy", "ToolRegistry",
    "SessionBus", "SessionMessage",
    "ProgressTracker", "ExecutionRecord",
]
