# -*- coding: utf-8 -*-
"""
Engine Adapter 统一基类 — 引擎无关化（P2）基础
==============================================

为「主通道」三引擎适配器（Ollama / MimoCode / DeepSeek）提供统一的接口契约，
使 EngineManager 与上层调度（SmartDispatcher / UniversalSkillRouter）可以以
引擎无关（engine-agnostic）的方式调用任意后端，无需关心具体是 Ollama 还是 DeepSeek。

设计目标：
- 定义所有适配器必须实现的统一接口：chat / generate_with_tools / is_available / cleanup
- 提供 list_models 的默认实现（返回 []），子类可按需覆盖
- 提供共享的 HTTP 连接池助手 _make_http_session()，消除各适配器重复的连接池代码
- 不引入任何网络行为变更：子类沿用此方法后请求方式、超时、错误语义保持不变

接口约定（与 engine_manager.py 中三个适配器保持一致）：
- chat(messages, **kwargs) -> str
- generate_with_tools(messages, tools, **kwargs) -> Dict[str, Any]
- is_available() -> bool
- cleanup() -> None
- list_models() -> List[str]          # 可选覆盖
- name: str                            # 引擎标识（子类在 __init__ 中赋值）
- supports_tools: bool                 # 是否支持工具调用（默认 True）
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None


class BaseEngineAdapter(ABC):
    """
    所有主通道引擎适配器的抽象基类。

    子类必须实现：
        - chat()
        - generate_with_tools()
        - is_available()
        - cleanup()

    子类可选覆盖：
        - list_models()

    子类通常在 __init__ 中设置 self.name / self.config / self._session。
    """

    # 引擎标识，子类应在 __init__ 中覆盖为具体名称
    name: str = "abstract_engine"

    def __init__(self, config: Any = None):
        self.config = config

    # ==================== 抽象接口（子类必须实现）====================

    @abstractmethod
    def chat(self, messages: List[Dict], **kwargs) -> str:
        """非流式对话，返回完整回复文本。"""
        raise NotImplementedError

    @abstractmethod
    def generate_with_tools(self, messages: List[Dict], tools: List[Dict],
                            **kwargs) -> Dict[str, Any]:
        """
        带工具调用的生成。

        Returns:
            Dict，至少包含 'content'（文本）与 'tool_calls'（列表）。
        """
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """检查引擎当前是否可达/可用。"""
        raise NotImplementedError

    @abstractmethod
    def cleanup(self) -> None:
        """释放连接池等资源。"""
        raise NotImplementedError

    # ==================== 可选覆盖 ====================

    def list_models(self) -> List[str]:
        """返回可用模型列表（默认空列表，子类按需覆盖）。"""
        return []

    @property
    def supports_tools(self) -> bool:
        """是否支持工具调用（默认 True）。"""
        return True

    # ==================== 共享助手 ====================

    def _make_http_session(self, pool_connections: int = 5,
                           pool_maxsize: int = 10,
                           max_retries: int = 1,
                           scheme: str = "http") -> "requests.Session":
        """
        创建带连接池的 requests.Session（共享实现，消除各适配器重复代码）。

        Args:
            pool_connections: 连接池连接数
            pool_maxsize:     连接池最大连接数
            max_retries:      单连接失败重试次数
            scheme:           挂载协议 'http' 或 'https'

        Returns:
            requests.Session（若 requests 不可用则抛 ImportError）
        """
        if not requests:
            raise ImportError("requests 未安装")

        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=max_retries,
        )
        session.mount(f"{scheme}://", adapter)
        return session
