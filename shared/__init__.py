# -*- coding: utf-8 -*-
"""
Lemon Agent 共享模块
================================================================
包含：
- AI资源扫描器
- 引擎管理器（统一AI调用入口）
- 桥接模块
- Skill系统
"""
import os
import sys as _sys

# ★ v5.5: 确保 shared/ 在 sys.path，使 `from core.xxx import` 可解析
# （engine_manager 中延迟导入 core.task_classifier 等模块需要此路径）
_SHARED_DIR = os.path.dirname(os.path.abspath(__file__))
if _SHARED_DIR not in _sys.path:
    _sys.path.insert(0, _SHARED_DIR)

from .ai_scanner import AIScanner, AIResource, AIType, scan_ai_resources
from .engine_manager import (
    EngineManager, 
    EngineConfig, 
    EngineType,
    ChatResponse,
    get_engine_manager,
    chat,
    stream_chat,
)

__all__ = [
    # AI扫描
    "AIScanner",
    "AIResource",
    "AIType",
    "scan_ai_resources",
    # 引擎管理
    "EngineManager",
    "EngineConfig",
    "EngineType",
    "ChatResponse",
    "get_engine_manager",
    "chat",
    "stream_chat",
]
