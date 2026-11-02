"""
B-002: Engine Manager - manages multiple AI engine adapters.

Ported from shared/engine_manager.py (4576 lines), stripped to essentials.
No Qt dependency. Pure Python with callback-based event system.
"""
from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Any, Callable, Dict, Generator, List, Optional

from .base import BaseEngineAdapter, EngineConfig, EngineStatus
from .ollama_engine import OllamaAdapter
from .deepseek_engine import DeepSeekAdapter
from .lmstudio_engine import LMStudioAdapter

logger = logging.getLogger(__name__)


class EngineType(str, Enum):
    OLLAMA = "ollama"
    DEEPSEEK = "deepseek"
    LMSTUDIO = "lmstudio"
    OPENAI_COMPAT = "openai_compat"


ENGINE_CLASS_MAP: Dict[str, type] = {
    EngineType.OLLAMA: OllamaAdapter,
    EngineType.DEEPSEEK: DeepSeekAdapter,
    EngineType.LMSTUDIO: LMStudioAdapter,
    EngineType.OPENAI_COMPAT: OllamaAdapter,
}


class EngineManager:
    def __init__(self):
        self._engines: Dict[str, BaseEngineAdapter] = {}
        self._primary: str = ""
        self._lock = threading.Lock()

    def register_engine(self, engine_type: str, config: EngineConfig,
                        name: Optional[str] = None) -> str:
        cls = ENGINE_CLASS_MAP.get(engine_type)
        if cls is None:
            raise ValueError(f"Unknown engine type: {engine_type}")
        engine_name = name or engine_type
        adapter = cls(config)
        with self._lock:
            self._engines[engine_name] = adapter
            if not self._primary:
                self._primary = engine_name
        logger.info(f"Registered engine: {engine_name} ({engine_type})")
        return engine_name

    def unregister_engine(self, name: str) -> bool:
        with self._lock:
            if name in self._engines:
                self._engines[name].cleanup()
                del self._engines[name]
                if self._primary == name:
                    self._primary = next(iter(self._engines), "")
                return True
        return False

    def get_engine(self, name: Optional[str] = None) -> Optional[BaseEngineAdapter]:
        with self._lock:
            if name:
                return self._engines.get(name)
            return self._engines.get(self._primary)

    def set_primary(self, name: str) -> bool:
        with self._lock:
            if name in self._engines:
                self._primary = name
                return True
        return False

    def get_primary_name(self) -> str:
        return self._primary

    def list_engines(self) -> List[Dict[str, Any]]:
        with self._lock:
            result = []
            for name, engine in self._engines.items():
                info = engine.get_status_info()
                info["primary"] = name == self._primary
                result.append(info)
            return result

    def list_available_engines(self) -> List[str]:
        with self._lock:
            return [n for n, e in self._engines.items() if e.is_available()]

    def auto_select(self) -> Optional[str]:
        available = self.list_available_engines()
        if not available:
            return None
        preferred_order = ["deepseek", "ollama", "lmstudio"]
        for pref in preferred_order:
            if pref in available:
                self.set_primary(pref)
                return pref
        self.set_primary(available[0])
        return available[0]

    def chat(self, messages: List[Dict], engine_name: Optional[str] = None,
             **kwargs) -> str:
        engine = self.get_engine(engine_name)
        if engine is None:
            raise RuntimeError(f"No engine available (requested: {engine_name})")
        if not engine.is_available():
            fallback = self._find_fallback(engine_name)
            if fallback:
                engine = fallback
            else:
                raise RuntimeError(f"Engine not available: {engine_name or self._primary}")
        return engine.chat(messages, **kwargs)

    def chat_stream(self, messages: List[Dict], engine_name: Optional[str] = None,
                    **kwargs) -> Generator[str, None, None]:
        engine = self.get_engine(engine_name)
        if engine is None:
            raise RuntimeError(f"No engine available")
        if not engine.is_available():
            fallback = self._find_fallback(engine_name)
            if fallback:
                engine = fallback
            else:
                raise RuntimeError("No available engine")
        yield from engine.stream(messages, **kwargs)

    def chat_with_tools(self, messages: List[Dict], tools: List[Dict],
                        engine_name: Optional[str] = None,
                        **kwargs) -> Dict[str, Any]:
        engine = self.get_engine(engine_name)
        if engine is None:
            raise RuntimeError("No engine available")
        if not engine.is_available():
            fallback = self._find_fallback(engine_name)
            if fallback:
                engine = fallback
            else:
                raise RuntimeError("No available engine")
        if not engine.supports_tools:
            content = engine.chat(messages, **kwargs)
            return {"content": content, "tool_calls": []}
        return engine.generate_with_tools(messages, tools, **kwargs)

    def _find_fallback(self, exclude: Optional[str] = None) -> Optional[BaseEngineAdapter]:
        for name in ["deepseek", "ollama", "lmstudio"]:
            if name == exclude:
                continue
            engine = self._engines.get(name)
            if engine and engine.is_available():
                logger.info(f"Using fallback engine: {name}")
                return engine
        return None

    def setup_callbacks(self, on_token: Optional[Callable] = None,
                        on_message: Optional[Callable] = None,
                        on_tool_call: Optional[Callable] = None,
                        on_error: Optional[Callable] = None) -> None:
        for engine in self._engines.values():
            if on_token:
                engine.on_token(on_token)
            if on_message:
                engine.on_message(on_message)
            if on_tool_call:
                engine.on_tool_call(on_tool_call)
            if on_error:
                engine.on_error(on_error)

    def health_check(self) -> Dict[str, bool]:
        with self._lock:
            return {name: engine.is_available() for name, engine in self._engines.items()}

    def cleanup(self) -> None:
        with self._lock:
            for engine in self._engines.values():
                engine.cleanup()
            self._engines.clear()
