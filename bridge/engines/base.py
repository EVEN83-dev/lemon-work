"""
B-002: Base Engine Adapter - abstract interface for all AI engines.

Ported from shared/engines/base.py, decoupled from Qt.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Dict, Generator, List, Optional


class EngineStatus(str, Enum):
    IDLE = "idle"
    GENERATING = "generating"
    THINKING = "thinking"
    USING_TOOL = "using_tool"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class EngineCapability(str, Enum):
    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"
    FILE_OPERATIONS = "file_operations"
    CODE_EXECUTION = "code_execution"
    WEB_SEARCH = "web_search"
    LONG_CONTEXT = "long_context"
    MULTI_MODAL = "multi_modal"
    LOCAL_ONLY = "local_only"
    CLOUD_ONLY = "cloud_only"


class EngineConfig:
    def __init__(self, **kwargs):
        self.model: str = kwargs.get("model", "")
        self.temperature: float = kwargs.get("temperature", 0.7)
        self.max_tokens: int = kwargs.get("max_tokens", 4096)
        self.top_p: float = kwargs.get("top_p", 0.9)
        self.timeout: int = kwargs.get("timeout", 60)
        self.system_prompt: str = kwargs.get("system_prompt", "")
        self.enable_skills: bool = kwargs.get("enable_skills", True)
        self.host: str = kwargs.get("host", "127.0.0.1")
        self.port: int = kwargs.get("port", 11434)
        self.api_key: str = kwargs.get("api_key", "")
        self.api_base: str = kwargs.get("api_base", "")

    @property
    def base_url(self) -> str:
        if self.api_base:
            return self.api_base.rstrip("/")
        return f"http://{self.host}:{self.port}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "maxTokens": self.max_tokens,
            "topP": self.top_p,
            "host": self.host,
            "port": self.port,
            "baseUrl": self.base_url,
        }


class BaseEngineAdapter(ABC):
    name: str = "abstract_engine"
    display_name: str = "Abstract Engine"

    def __init__(self, config: Optional[EngineConfig] = None):
        self._config = config or EngineConfig()
        self._status = EngineStatus.IDLE
        self._capabilities: List[EngineCapability] = []
        self._on_token: Optional[Callable[[str], None]] = None
        self._on_message: Optional[Callable[[str], None]] = None
        self._on_thinking: Optional[Callable[[str], None]] = None
        self._on_tool_call: Optional[Callable[[dict], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_status_change: Optional[Callable[[EngineStatus], None]] = None
        self._cancelled = False

    @property
    def status(self) -> EngineStatus:
        return self._status

    @property
    def capabilities(self) -> List[EngineCapability]:
        return self._capabilities

    def has_capability(self, cap: EngineCapability) -> bool:
        return cap in self._capabilities

    def on_token(self, callback: Callable[[str], None]) -> None:
        self._on_token = callback

    def on_message(self, callback: Callable[[str], None]) -> None:
        self._on_message = callback

    def on_thinking(self, callback: Callable[[str], None]) -> None:
        self._on_thinking = callback

    def on_tool_call(self, callback: Callable[[dict], None]) -> None:
        self._on_tool_call = callback

    def on_error(self, callback: Callable[[str], None]) -> None:
        self._on_error = callback

    def on_status_change(self, callback: Callable[[EngineStatus], None]) -> None:
        self._on_status_change = callback

    def _emit_token(self, token: str) -> None:
        if self._on_token:
            self._on_token(token)

    def _emit_message(self, msg: str) -> None:
        if self._on_message:
            self._on_message(msg)

    def _emit_thinking(self, text: str) -> None:
        if self._on_thinking:
            self._on_thinking(text)

    def _emit_tool_call(self, tc: dict) -> None:
        if self._on_tool_call:
            self._on_tool_call(tc)

    def _emit_error(self, err: str) -> None:
        if self._on_error:
            self._on_error(err)

    def _set_status(self, status: EngineStatus) -> None:
        self._status = status
        if self._on_status_change:
            self._on_status_change(status)

    @abstractmethod
    def chat(self, messages: List[Dict], **kwargs) -> str:
        pass

    @abstractmethod
    def generate_with_tools(self, messages: List[Dict],
                            tools: List[Dict], **kwargs) -> Dict[str, Any]:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def cleanup(self) -> None:
        pass

    def stream(self, messages: List[Dict], **kwargs) -> Generator[str, None, None]:
        result = self.chat(messages, **kwargs)
        chunk_size = max(1, len(result) // 10)
        for i in range(0, len(result), chunk_size):
            if self._cancelled:
                break
            yield result[i:i + chunk_size]

    def list_models(self) -> List[str]:
        return []

    @property
    def supports_tools(self) -> bool:
        return EngineCapability.TOOL_CALLING in self._capabilities

    def get_model_name(self) -> str:
        return self._config.model or self.name

    def cancel(self) -> None:
        self._cancelled = True

    def reset_cancel(self) -> None:
        self._cancelled = False

    def get_status_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "displayName": self.display_name,
            "status": self.status.value,
            "available": self.is_available(),
            "capabilities": [c.value for c in self._capabilities],
            "config": self._config.to_dict(),
        }

    def _make_http_session(self, pool_connections: int = 5,
                           pool_maxsize: int = 10, retry: int = 3) -> Any:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry as UrllibRetry
        session = requests.Session()
        retry_strategy = UrllibRetry(total=retry, backoff_factor=0.5,
                                     status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(pool_connections=pool_connections,
                              pool_maxsize=pool_maxsize, max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
