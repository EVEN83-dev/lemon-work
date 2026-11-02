# -*- coding: utf-8 -*-
"""
LM Studio 本地引擎 — 基于 LM Studio 本地推理服务器的 Agent 算力引擎
===================================================================
LM Studio 在 localhost:1234 提供 OpenAI 兼容 API，支持加载 .gguf 模型。

用法：
    1. 打开 LM Studio，加载一个模型（如 Llama、Qwen、Mistral 等）
    2. 在 LM Studio 中启动本地推理服务器（Local Server tab）
    3. Lemon Agent 即可通过此引擎调用本地 LLAMA 模型

与 Ollama 的区别：
- LM Studio 支持更多模型格式（GGUF），模型管理更灵活
- 提供 OpenAI 兼容 API，无需额外适配
- 支持 GPU 加速（Metal/CUDA）
"""

import json
import threading
import time
from typing import Optional, List, Dict, Generator

from core.agent_engine import (
    AgentEngine, EngineConfig, EngineStatus, EngineCapability
)

try:
    import requests
except ImportError:
    requests = None


# 默认配置
LMSTUDIO_HOST = "http://localhost:1234"
DEFAULT_MODEL = "auto"  # LM Studio 自动使用当前加载的模型
REQUEST_TIMEOUT = 120
STREAM_TIMEOUT = 300


class LMStudioEngine(AgentEngine):
    """
    LM Studio 本地推理引擎

    能力：
    - 流式/非流式生成
    - 工具调用（function calling）— 需模型支持
    - 本地模型列表查询
    - 本地部署，零网络依赖
    - GPU 加速（通过 LM Studio 配置）
    """

    def __init__(self, config: Optional[EngineConfig] = None):
        if config is None:
            config = EngineConfig(model=DEFAULT_MODEL)
        elif not config.model:
            config.model = DEFAULT_MODEL

        super().__init__(config)
        self._name = "lmstudio"
        self._display_name = "LM Studio 本地"
        self._capabilities = [
            EngineCapability.STREAMING,
            EngineCapability.TOOL_CALLING,
            EngineCapability.LOCAL_ONLY,
        ]
        self._host = LMSTUDIO_HOST
        self._model = config.model
        # 缓存
        self._models_cache: List[Dict] = []
        self._models_cache_time = 0
        self._models_cache_ttl = 30

    # ==================== 核心方法 ====================

    def _build_openai_messages(self, prompt: str,
                                context: Optional[List[Dict]] = None) -> List[Dict]:
        """构建 OpenAI 兼容的消息列表"""
        messages = []

        if self.config.system_prompt:
            messages.append({"role": "system", "content": self.config.system_prompt})

        # 对话历史（context）
        if context:
            for msg in context:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("system", "user", "assistant", "tool"):
                    messages.append({"role": role, "content": content})

        # 当前消息
        messages.append({"role": "user", "content": prompt})
        return messages

    def generate(self, prompt: str, context: Optional[List[Dict]] = None) -> str:
        """非流式生成完整回复"""
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        try:
            messages = self._build_openai_messages(prompt, context)
            payload = {
                "model": self._model,
                "messages": messages,
                "stream": False,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "top_p": self.config.top_p,
            }

            resp = requests.post(
                f"{self._host}/v1/chat/completions",
                json=payload,
                timeout=self.config.timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    self._emit_message(content)
                    self._set_status(EngineStatus.IDLE)
                    return content
                else:
                    err = "LM Studio 返回空响应"
                    self._emit_error(err)
                    self._set_status(EngineStatus.ERROR)
                    return err
            else:
                err = f"LM Studio 返回错误: HTTP {resp.status_code}"
                try:
                    detail = resp.json().get("error", {}).get("message", "")
                    if detail:
                        err += f" - {detail}"
                except Exception:
                    pass
                self._emit_error(err)
                self._set_status(EngineStatus.ERROR)
                return err

        except requests.exceptions.ConnectionError:
            err = "LM Studio 连接失败，请确认 LM Studio 已启动本地服务器 (localhost:1234)"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err
        except requests.exceptions.Timeout:
            err = "LM Studio 响应超时"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err
        except Exception as e:
            err = f"LM Studio 引擎错误: {e}"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err

    def stream(self, prompt: str, context: Optional[List[Dict]] = None) -> Generator[str, None, None]:
        """流式生成，逐个 yield token"""
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        try:
            messages = self._build_openai_messages(prompt, context)
            payload = {
                "model": self._model,
                "messages": messages,
                "stream": True,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "top_p": self.config.top_p,
            }

            resp = requests.post(
                f"{self._host}/v1/chat/completions",
                json=payload,
                stream=True,
                timeout=STREAM_TIMEOUT,
            )

            if resp.status_code != 200:
                err = f"LM Studio 流式错误: HTTP {resp.status_code}"
                self._emit_error(err)
                self._set_status(EngineStatus.ERROR)
                yield err
                return

            full_content = ""
            for line in resp.iter_lines(decode_unicode=True):
                if self._cancel_flag.is_set():
                    break
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        full_content += delta
                        self._emit_token(delta)
                        yield delta
                except json.JSONDecodeError:
                    continue

            self._emit_message(full_content)
            self._set_status(EngineStatus.IDLE)

        except requests.exceptions.ConnectionError:
            err = "LM Studio 连接失败"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            yield err
        except Exception as e:
            err = f"LM Studio 流式错误: {e}"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            yield err

    def generate_with_tools(self, prompt: str, tools: List[Dict],
                            context: Optional[List[Dict]] = None) -> str:
        """带工具调用的生成（需模型自身支持 function calling）"""
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        try:
            messages = self._build_openai_messages(prompt, context)
            payload = {
                "model": self._model,
                "messages": messages,
                "stream": True,
                "tools": tools,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }

            resp = requests.post(
                f"{self._host}/v1/chat/completions",
                json=payload,
                timeout=self.config.timeout,
                stream=True,
            )

            if resp.status_code != 200:
                err = f"LM Studio 工具调用错误: HTTP {resp.status_code}"
                self._emit_error(err)
                self._set_status(EngineStatus.ERROR)
                return err

            full_content = ""
            tool_calls = []
            in_tool_call = False

            for line in resp.iter_lines(decode_unicode=True):
                if self._cancel_flag.is_set():
                    break
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content += content
                        tc_delta = delta.get("tool_calls", [])
                        if tc_delta:
                            in_tool_call = True
                            for tc in tc_delta:
                                idx = tc.get("index", 0)
                                while len(tool_calls) <= idx:
                                    tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
                                if tc.get("id"):
                                    tool_calls[idx]["id"] = tc["id"]
                                func = tc.get("function", {})
                                if func.get("name"):
                                    tool_calls[idx]["function"]["name"] = func["name"]
                                if func.get("arguments"):
                                    tool_calls[idx]["function"]["arguments"] += func["arguments"]
                except json.JSONDecodeError:
                    continue

            if in_tool_call and tool_calls:
                self._set_status(EngineStatus.USING_TOOL)
                for tc in tool_calls:
                    self._emit_tool_call(tc)
                result = json.dumps({"tool_calls": tool_calls}, ensure_ascii=False)
                self._emit_message(result)
                self._set_status(EngineStatus.IDLE)
                return result

            content = full_content.strip()
            self._emit_message(content)
            self._set_status(EngineStatus.IDLE)
            return content

        except Exception as e:
            err = f"LM Studio 工具调用异常: {e}"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err

    # ==================== 模型管理 ====================

    def get_models(self) -> List[Dict]:
        """获取 LM Studio 已加载的模型列表"""
        now = time.time()
        if self._models_cache and (now - self._models_cache_time) < self._models_cache_ttl:
            return self._models_cache

        if requests is None:
            return []

        try:
            resp = requests.get(f"{self._host}/v1/models", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = []
                for m in data.get("data", []):
                    model_id = m.get("id", "unknown")
                    models.append({
                        "id": model_id,
                        "name": model_id,
                        "owned_by": m.get("owned_by", "lmstudio"),
                        "created": m.get("created", 0),
                    })
                # 如果没有返回模型，添加一个默认条目
                if not models:
                    models = [{"id": "auto", "name": "当前加载的模型", "owned_by": "lmstudio"}]
                self._models_cache = models
                self._models_cache_time = now
                return models
            return [{"id": "auto", "name": "当前加载的模型", "owned_by": "lmstudio"}]
        except Exception:
            return [{"id": "auto", "name": "当前加载的模型", "owned_by": "lmstudio"}]

    def get_status_info(self) -> Dict:
        """获取引擎状态信息"""
        available = self.is_available()
        models = self.get_models() if available else []
        return {
            "name": self._name,
            "display_name": self._display_name,
            "available": available,
            "status": self._status.value,
            "model": self._model,
            "models": models,
            "models_count": len(models),
            "host": self._host,
        }

    def is_available(self) -> bool:
        """检查 LM Studio 服务是否运行"""
        if requests is None:
            return False
        try:
            resp = requests.get(f"{self._host}/v1/models", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def set_model(self, model_id: str):
        """切换模型"""
        if model_id:
            self._model = model_id
            self.config.model = model_id
            print(f"[LMStudioEngine] 模型切换为: {model_id}")


# 注册到引擎注册表
def register():
    from core.agent_engine import EngineRegistry
    EngineRegistry.register("lmstudio", LMStudioEngine)