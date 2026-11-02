# -*- coding: utf-8 -*-
"""
Agent Engine 抽象基类 — 统一所有算力引擎接口
=============================================
所有引擎（LemonCode / Ollama / DeepSeek）都继承此基类，
提供统一的 generate() / stream() / tool_call() 接口。

设计思路：
- 前端不关心后端用的是什么引擎
- 引擎切换只需更换 EngineManager 中的 active_engine
- 所有引擎输出通过同一套 PyBridge 信号发往前端
"""

import json
import threading
import time
from typing import Optional, List, Dict, Callable, Generator, Any
from abc import ABC, abstractmethod
from enum import Enum


class EngineStatus(Enum):
    """引擎运行状态"""
    IDLE = "idle"
    GENERATING = "generating"
    THINKING = "thinking"
    USING_TOOL = "using_tool"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class EngineCapability(Enum):
    """引擎能力标记"""
    STREAMING = "streaming"           # 支持流式输出
    TOOL_CALLING = "tool_calling"     # 支持工具调用（function calling）
    FILE_OPERATIONS = "file_ops"      # 支持文件操作
    CODE_EXECUTION = "code_exec"      # 支持代码执行
    WEB_SEARCH = "web_search"         # 支持网络搜索
    LONG_CONTEXT = "long_context"     # 支持长上下文（>32K）
    MULTI_MODAL = "multi_modal"       # 支持多模态（图片等）
    LOCAL_ONLY = "local_only"         # 仅本地运行
    CLOUD_ONLY = "cloud_only"         # 仅云端运行


class EngineConfig:
    """引擎配置基类"""
    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "")
        self.temperature = kwargs.get("temperature", 0.7)
        self.max_tokens = kwargs.get("max_tokens", 4096)
        self.top_p = kwargs.get("top_p", 0.9)
        self.timeout = kwargs.get("timeout", 60)
        self.system_prompt = kwargs.get("system_prompt", "")
        self.enable_skills = kwargs.get("enable_skills", True)


class AgentEngine(ABC):
    """
    所有算力引擎的抽象基类
    
    子类必须实现：
    - generate()       : 非流式生成
    - stream()         : 流式生成（yield）
    - get_models()     : 获取可用模型列表
    - get_status()     : 获取引擎状态
    
    子类可选实现：
    - generate_with_tools()  : 带工具调用的生成
    - cancel()               : 取消当前生成
    """

    def __init__(self, config: Optional[EngineConfig] = None):
        self.config = config or EngineConfig()
        self._status = EngineStatus.IDLE
        self._capabilities: List[EngineCapability] = []
        self._name = "abstract_engine"
        self._display_name = "抽象引擎"
        self._lock = threading.Lock()
        self._cancel_flag = threading.Event()
        self._event_adapter: Optional[Any] = None
        # 回调注册
        self._on_token: Optional[Callable[[str], None]] = None      # 每个token
        self._on_message: Optional[Callable[[str], None]] = None    # 完整消息
        self._on_thinking: Optional[Callable[[str], None]] = None   # 思考过程
        self._on_tool_call: Optional[Callable[[dict], None]] = None # 工具调用
        self._on_error: Optional[Callable[[str], None]] = None      # 错误
        self._on_status_change: Optional[Callable[[EngineStatus], None]] = None

    # ==================== 属性 ====================
    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def status(self) -> EngineStatus:
        return self._status

    @property
    def capabilities(self) -> List[EngineCapability]:
        return list(self._capabilities)

    def has_capability(self, cap: EngineCapability) -> bool:
        return cap in self._capabilities

    # ==================== 回调注册 ====================
    def on_token(self, callback: Callable[[str], None]):
        self._on_token = callback

    def on_message(self, callback: Callable[[str], None]):
        self._on_message = callback

    def on_thinking(self, callback: Callable[[str], None]):
        self._on_thinking = callback

    def on_tool_call(self, callback: Callable[[dict], None]):
        self._on_tool_call = callback

    def on_error(self, callback: Callable[[str], None]):
        self._on_error = callback

    def on_status_change(self, callback: Callable[[EngineStatus], None]):
        self._on_status_change = callback

    def set_event_adapter(self, adapter: Any) -> None:
        """注入 EventAdapter 单例，使 _emit_* 方法双写到 bridge 信号。"""
        self._event_adapter = adapter

    # ==================== 状态管理 ====================
    def _set_status(self, status: EngineStatus):
        old = self._status
        self._status = status
        if old != status and self._on_status_change:
            try:
                self._on_status_change(status)
            except Exception:
                pass

    # ==================== 抽象方法 ====================
    @abstractmethod
    def generate(self, prompt: str, context: Optional[List[Dict]] = None) -> str:
        """非流式生成完整回复"""
        pass

    @abstractmethod
    def stream(self, prompt: str, context: Optional[List[Dict]] = None) -> Generator[str, None, None]:
        """流式生成，逐个 yield token"""
        pass

    @abstractmethod
    def get_models(self) -> List[Dict]:
        """获取可用模型列表
        返回: [{"id": "model_name", "name": "显示名称", "size": "大小", ...}]
        """
        pass

    @abstractmethod
    def get_status_info(self) -> Dict:
        """获取引擎状态信息"""
        pass

    # ==================== 可选方法 ====================
    def generate_with_tools(self, prompt: str, tools: List[Dict],
                            context: Optional[List[Dict]] = None) -> str:
        """带工具调用的生成（默认回退到普通 generate）"""
        return self.generate(prompt, context)

    def cancel(self):
        """取消当前生成"""
        self._cancel_flag.set()

    def reset_cancel(self):
        """重置取消标志"""
        self._cancel_flag.clear()

    def is_available(self) -> bool:
        """检查引擎是否可用"""
        return True

    # ==================== 工具方法 ====================
    def _build_messages(self, prompt: str, context: Optional[List[Dict]] = None) -> List[Dict]:
        """构建消息列表"""
        messages = []
        if self.config.system_prompt:
            messages.append({"role": "system", "content": self.config.system_prompt})
        if context:
            messages.extend(context)
        messages.append({"role": "user", "content": prompt})
        return messages

    def _emit_token(self, token: str):
        if self._on_token:
            try:
                self._on_token(token)
            except Exception:
                pass

    def _emit_message(self, msg: str):
        if self._on_message:
            try:
                self._on_message(msg)
            except Exception:
                pass
        if self._event_adapter:
            try:
                self._event_adapter.stream_delta.emit("", msg)
            except Exception:
                pass

    def _emit_thinking(self, text: str):
        if self._on_thinking:
            try:
                self._on_thinking(text)
            except Exception:
                pass
        if self._event_adapter:
            try:
                self._event_adapter.thinking_step.emit("", "thinking", text)
            except Exception:
                pass

    def _emit_tool_call(self, tool_info: dict):
        if self._on_tool_call:
            try:
                self._on_tool_call(tool_info)
            except Exception:
                pass
        if self._event_adapter:
            try:
                self._event_adapter.tool_call.emit("", tool_info)
            except Exception:
                pass

    def _emit_error(self, err: str):
        if self._on_error:
            try:
                self._on_error(err)
            except Exception:
                pass
        if self._event_adapter:
            try:
                self._event_adapter.error.emit("", "engine_error", err)
            except Exception:
                pass


# ==================== 引擎注册表 ====================

class EngineRegistry:
    """引擎注册表 — 管理所有可用引擎"""

    _engines: Dict[str, type] = {}
    _instances: Dict[str, AgentEngine] = {}
    _global_event_adapter: Optional[Any] = None

    @classmethod
    def set_global_event_adapter(cls, adapter: Any) -> None:
        """设置全局 EventAdapter 单例，新创建的引擎自动注入。"""
        cls._global_event_adapter = adapter
        for engine in cls._instances.values():
            engine.set_event_adapter(adapter)

    @classmethod
    def register(cls, name: str, engine_class: type):
        """注册引擎类"""
        cls._engines[name] = engine_class

    @classmethod
    def create(cls, name: str, config: Optional[EngineConfig] = None) -> Optional[AgentEngine]:
        """创建引擎实例"""
        engine_class = cls._engines.get(name)
        if engine_class is None:
            return None
        try:
            return engine_class(config)
        except Exception as e:
            print(f"[EngineRegistry] 创建引擎 {name} 失败: {e}")
            return None

    @classmethod
    def get_instance(cls, name: str, config: Optional[EngineConfig] = None) -> Optional[AgentEngine]:
        """获取或创建引擎实例（单例模式）"""
        if name not in cls._instances:
            cls._instances[name] = cls.create(name, config)
        engine = cls._instances.get(name)
        if engine and cls._global_event_adapter and not engine._event_adapter:
            engine.set_event_adapter(cls._global_event_adapter)
        return engine

    @classmethod
    def list_engines(cls) -> List[Dict]:
        """列出所有已注册引擎及其能力"""
        result = []
        for name, engine_class in cls._engines.items():
            # 创建临时实例获取能力
            try:
                temp = engine_class()
                result.append({
                    "id": name,
                    "name": temp.display_name,
                    "capabilities": [c.value for c in temp.capabilities],
                })
            except Exception:
                result.append({"id": name, "name": name, "capabilities": []})
        return result

    @classmethod
    def get_available_engines(cls) -> List[str]:
        """获取当前可用的引擎名称列表"""
        available = []
        for name, engine_class in cls._engines.items():
            try:
                temp = engine_class()
                if temp.is_available():
                    available.append(name)
            except Exception:
                pass
        return available