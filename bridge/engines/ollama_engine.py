"""
B-002: Ollama Engine Adapter - connects to local Ollama server.

Ported from standard_mode/core/ollama_engine.py, decoupled from Qt.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Generator, List, Optional

from .base import BaseEngineAdapter, EngineCapability, EngineConfig, EngineStatus

logger = logging.getLogger(__name__)

OLLAMA_SYSTEM_PROMPT = """You are Lemon Agent, an intelligent AI assistant. You can use tools to help users accomplish tasks.
When you need to use a tool, output a tool_call block. Otherwise, respond naturally and helpfully."""


class OllamaAdapter(BaseEngineAdapter):
    name = "ollama"
    display_name = "Ollama"

    def __init__(self, config: Optional[EngineConfig] = None):
        super().__init__(config)
        self._capabilities = [
            EngineCapability.STREAMING,
            EngineCapability.TOOL_CALLING,
            EngineCapability.LOCAL_ONLY,
            EngineCapability.LONG_CONTEXT,
        ]

    def chat(self, messages: List[Dict], **kwargs) -> str:
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()
        try:
            session = self._make_http_session()
            url = f"{self._config.base_url}/api/chat"
            payload = {
                "model": kwargs.get("model", self._config.model),
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": kwargs.get("temperature", self._config.temperature),
                    "num_predict": kwargs.get("max_tokens", self._config.max_tokens),
                    "top_p": kwargs.get("top_p", self._config.top_p),
                },
            }
            resp = session.post(url, json=payload, timeout=self._config.timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            self._emit_message(content)
            self._set_status(EngineStatus.IDLE)
            return content
        except Exception as e:
            self._emit_error(str(e))
            self._set_status(EngineStatus.ERROR)
            raise

    def generate_with_tools(self, messages: List[Dict],
                            tools: List[Dict], **kwargs) -> Dict[str, Any]:
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()
        try:
            session = self._make_http_session()
            url = f"{self._config.base_url}/api/chat"
            payload = {
                "model": kwargs.get("model", self._config.model),
                "messages": messages,
                "stream": False,
                "tools": tools,
                "options": {
                    "temperature": kwargs.get("temperature", self._config.temperature),
                    "num_predict": kwargs.get("max_tokens", self._config.max_tokens),
                },
            }
            resp = session.post(url, json=payload, timeout=self._config.timeout)
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message", {})
            result: Dict[str, Any] = {
                "content": msg.get("content", ""),
                "tool_calls": msg.get("tool_calls", []),
            }
            if result["tool_calls"]:
                self._set_status(EngineStatus.USING_TOOL)
                for tc in result["tool_calls"]:
                    self._emit_tool_call(tc)
            else:
                self._emit_message(result["content"])
            self._set_status(EngineStatus.IDLE)
            return result
        except Exception as e:
            self._emit_error(str(e))
            self._set_status(EngineStatus.ERROR)
            raise

    def stream(self, messages: List[Dict], **kwargs) -> Generator[str, None, None]:
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()
        try:
            session = self._make_http_session()
            url = f"{self._config.base_url}/api/chat"
            payload = {
                "model": kwargs.get("model", self._config.model),
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": kwargs.get("temperature", self._config.temperature),
                    "num_predict": kwargs.get("max_tokens", self._config.max_tokens),
                },
            }
            resp = session.post(url, json=payload, timeout=self._config.timeout,
                                stream=True)
            resp.raise_for_status()
            full_content = ""
            for line in resp.iter_lines():
                if self._cancelled:
                    break
                if not line:
                    continue
                chunk = json.loads(line)
                content = chunk.get("message", {}).get("content", "")
                if content:
                    full_content += content
                    self._emit_token(content)
                    yield content
                if chunk.get("done", False):
                    break
            self._emit_message(full_content)
            self._set_status(EngineStatus.IDLE)
        except Exception as e:
            self._emit_error(str(e))
            self._set_status(EngineStatus.ERROR)
            raise

    def list_models(self) -> List[str]:
        try:
            session = self._make_http_session()
            resp = session.get(f"{self._config.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    def is_available(self) -> bool:
        try:
            import requests as _req
            resp = _req.get(f"{self._config.base_url}/api/tags", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def cleanup(self) -> None:
        self._set_status(EngineStatus.DISCONNECTED)
