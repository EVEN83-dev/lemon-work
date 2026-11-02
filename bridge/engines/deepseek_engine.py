"""
B-002: DeepSeek Engine Adapter - connects to DeepSeek API.

Ported from standard_mode/core/deepseek_engine.py, decoupled from Qt.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Generator, List, Optional

from .base import BaseEngineAdapter, EngineCapability, EngineConfig, EngineStatus

logger = logging.getLogger(__name__)

DEEPSEEK_SYSTEM_PROMPT = """You are Lemon Agent, an intelligent AI assistant powered by DeepSeek.
You can use tools to help users accomplish tasks. When you need to use a tool, output a tool_call.
Otherwise, respond naturally and helpfully."""


class DeepSeekAdapter(BaseEngineAdapter):
    name = "deepseek"
    display_name = "DeepSeek"

    def __init__(self, config: Optional[EngineConfig] = None):
        super().__init__(config)
        self._capabilities = [
            EngineCapability.STREAMING,
            EngineCapability.TOOL_CALLING,
            EngineCapability.CLOUD_ONLY,
            EngineCapability.LONG_CONTEXT,
            EngineCapability.MULTI_MODAL,
        ]

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, messages: List[Dict], **kwargs) -> str:
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()
        try:
            session = self._make_http_session()
            url = f"{self._config.base_url}/chat/completions"
            payload = {
                "model": kwargs.get("model", self._config.model),
                "messages": messages,
                "temperature": kwargs.get("temperature", self._config.temperature),
                "max_tokens": kwargs.get("max_tokens", self._config.max_tokens),
                "top_p": kwargs.get("top_p", self._config.top_p),
                "stream": False,
            }
            resp = session.post(url, json=payload, headers=self._get_headers(),
                                timeout=self._config.timeout)
            if resp.status_code != 200:
                # ★ 诊断：打印 400/非200 的真实响应体
                print(f"[DeepSeekAdapter-DIAG] HTTP {resp.status_code} url={url} "
                      f"model={payload.get('model')} body={resp.text[:800]}", flush=True)
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
            url = f"{self._config.base_url}/chat/completions"
            payload = {
                "model": kwargs.get("model", self._config.model),
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
            url = f"{self._config.base_url}/chat/completions"
            payload = {
                "model": kwargs.get("model", self._config.model),
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
            resp = session.get(f"{self._config.base_url}/models",
                               headers=self._get_headers(), timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return [m.get("id", "") for m in data.get("data", [])]
        except Exception:
            return ["deepseek-chat", "deepseek-reasoner"]

    def is_available(self) -> bool:
        return bool(self._config.api_key)

    def cleanup(self) -> None:
        self._set_status(EngineStatus.DISCONNECTED)
