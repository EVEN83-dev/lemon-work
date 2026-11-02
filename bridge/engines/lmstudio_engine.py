"""
B-002: LM Studio Engine Adapter - connects to local LM Studio server.

Ported from standard_mode/core/lmstudio_engine.py, decoupled from Qt.
Compatible with OpenAI API format served by LM Studio.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Generator, List, Optional

from .base import BaseEngineAdapter, EngineCapability, EngineConfig, EngineStatus

logger = logging.getLogger(__name__)


class LMStudioAdapter(BaseEngineAdapter):
    name = "lmstudio"
    display_name = "LM Studio"

    def __init__(self, config: Optional[EngineConfig] = None):
        super().__init__(config)
        self._capabilities = [
            EngineCapability.STREAMING,
            EngineCapability.TOOL_CALLING,
            EngineCapability.LOCAL_ONLY,
        ]

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def _resolve_model(self, **kwargs) -> str:
        model = kwargs.get("model", self._config.model)
        if model in ("auto", ""):
            models = self.list_models()
            model = models[0] if models else "default"
        return model

    def chat(self, messages: List[Dict], **kwargs) -> str:
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()
        try:
            session = self._make_http_session()
            url = f"{self._config.base_url}/v1/chat/completions"
            payload = {
                "model": self._resolve_model(**kwargs),
                "messages": messages,
                "temperature": kwargs.get("temperature", self._config.temperature),
                "max_tokens": kwargs.get("max_tokens", self._config.max_tokens),
                "stream": False,
            }
            resp = session.post(url, json=payload, headers=self._get_headers(),
                                timeout=self._config.timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
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
            url = f"{self._config.base_url}/v1/chat/completions"
            payload = {
                "model": self._resolve_model(**kwargs),
                "messages": messages,
                "temperature": kwargs.get("temperature", self._config.temperature),
                "max_tokens": kwargs.get("max_tokens", self._config.max_tokens),
                "tools": tools,
                "stream": False,
            }
            resp = session.post(url, json=payload, headers=self._get_headers(),
                                timeout=self._config.timeout)
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            result: Dict[str, Any] = {
                "content": msg.get("content", "") or "",
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
            url = f"{self._config.base_url}/v1/chat/completions"
            payload = {
                "model": self._resolve_model(**kwargs),
                "messages": messages,
                "temperature": kwargs.get("temperature", self._config.temperature),
                "max_tokens": kwargs.get("max_tokens", self._config.max_tokens),
                "stream": True,
            }
            resp = session.post(url, json=payload, headers=self._get_headers(),
                                timeout=self._config.timeout, stream=True)
            resp.raise_for_status()
            full_content = ""
            for line in resp.iter_lines():
                if self._cancelled:
                    break
                if not line or not line.startswith(b"data: "):
                    continue
                data_str = line[6:]
                if data_str == b"[DONE]":
                    break
                chunk = json.loads(data_str)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full_content += content
                    self._emit_token(content)
                    yield content
            self._emit_message(full_content)
            self._set_status(EngineStatus.IDLE)
        except Exception as e:
            self._emit_error(str(e))
            self._set_status(EngineStatus.ERROR)
            raise

    def list_models(self) -> List[str]:
        try:
            session = self._make_http_session()
            resp = session.get(f"{self._config.base_url}/v1/models", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return [m.get("id", "") for m in data.get("data", [])]
        except Exception:
            return []

    def is_available(self) -> bool:
        try:
            import requests as _req
            resp = _req.get(f"{self._config.base_url}/v1/models", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def cleanup(self) -> None:
        self._set_status(EngineStatus.DISCONNECTED)
