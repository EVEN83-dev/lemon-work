# -*- coding: utf-8 -*-
"""
Lemon Agent - Standard Mode Core Package

标准模式核心模块包

★ v3.46: 导入改为 try/except 保护，防止单个模块缺失导致整个包不可用
"""

# ★ v3.46: 使用 try/except 保护每个导入，避免依赖缺失导致整个 core 包崩溃
try:
    from .serve_bridge import MIMOServeBridge
except ImportError:
    MIMOServeBridge = None

try:
    from .engine_manager import get_engine_manager, EngineManager
except ImportError:
    get_engine_manager = None
    EngineManager = None

try:
    from .ollama_engine import OllamaEngine
except ImportError:
    OllamaEngine = None

try:
    from .llama_engine import LLAMAEngine
except ImportError:
    LLAMAEngine = None

__all__ = [
    'MIMOServeBridge',
    'get_engine_manager',
    'EngineManager',
    'OllamaEngine',
    'LLAMAEngine',
]