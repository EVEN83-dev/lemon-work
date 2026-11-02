# -*- coding: utf-8 -*-
"""
Ollama 本地引擎 — 基于 Ollama HTTP API 的 Agent 算力引擎
========================================================
提供完整的流式输出、工具调用（Skills）、模型列表查询等能力。

与 ollama_bridge.py 的区别：
- ollama_bridge.py: 仅用于小机器人的简单对话（qwen3.5:4b）
- ollama_engine.py: 完整的 Agent 算力引擎，支持流式+工具调用

兼容 OpenAI API 格式（Ollama 0.3+ 支持 /v1/chat/completions）
"""

import json
import threading
import time
from typing import Optional, List, Dict, Generator

from agent_engine import (
    AgentEngine, EngineConfig, EngineStatus, EngineCapability
)

try:
    import requests
except ImportError:
    requests = None


def _extract_reply_from_thinking(thinking_text: str) -> str:
    """从 thinking 模型的思考链中提取实际回复。

    thinking 模型（如 qwen3.5）在 /thinking 模式下可能将回复内容
    全部放在 thinking 字段而 content 为空。此函数尝试从思考链末尾
    提取用户可见的回复部分。

    策略（按优先级）：
    1. 若末尾有 `` 或 ``` 回复块，提取之
    2. 若末尾有 "回复:" / "答案:" 等标记，提取其后内容
    3. 返回完整 thinking（兜底，总比返回空好）
    """
    text = thinking_text.strip()
    if not text:
        return ""

    import re
    m = re.search(r'```(?:reply|answer|回复|答案)\s*\n(.*?)```', text, re.DOTALL)
    if m:
        return m.group(1).strip()

    m = re.search(r'(?:回复|答案|回答|结论|总结)[：:]\s*(.+)$', text, re.DOTALL)
    if m:
        return m.group(1).strip()

    return text


# 默认配置
OLLAMA_HOST = "http://127.0.0.1:11434"  # ★ v3.25: 修复 IPv6 解析问题，与 ollama_bridge.py 保持一致
DEFAULT_MODEL = "qwen2.5:1.5b"  # ★ v3.20: qwen3.5:9b太慢，改用快速模型
REQUEST_TIMEOUT = 120
STREAM_TIMEOUT = 300


class OllamaEngine(AgentEngine):
    """
    Ollama 本地推理引擎
    
    能力：
    - 流式/非流式生成
    - 工具调用（function calling）— 需模型支持
    - 本地模型列表查询
    - 本地部署，零网络依赖
    """

    def __init__(self, config: Optional[EngineConfig] = None):
        # 确保至少有一个默认模型
        if config is None:
            config = EngineConfig(model=DEFAULT_MODEL)
        elif not config.model:
            config.model = DEFAULT_MODEL

        super().__init__(config)
        self._name = "ollama"
        self._display_name = "Ollama 本地"
        self._capabilities = [
            EngineCapability.STREAMING,
            # ★ v3.55: 重新启用 TOOL_CALLING — qwen2.5 通过 prompt engineering 支持工具调用
            # generate_with_tools 使用 Ollama 原生 tools API，兼容 qwen3.5 系列
            # 对 qwen2.5 等旧模型，Agent 循环会优雅降级到普通流式模式
            EngineCapability.TOOL_CALLING,
            EngineCapability.FILE_OPERATIONS,
            EngineCapability.CODE_EXECUTION,
            EngineCapability.LOCAL_ONLY,
        ]
        self._host = OLLAMA_HOST
        self._model = config.model
        # 缓存模型列表
        self._models_cache: List[Dict] = []
        self._models_cache_time = 0
        self._models_cache_ttl = 30  # 秒

    # ==================== 核心方法 ====================

    def generate(self, prompt: str, context: Optional[List[Dict]] = None) -> str:
        """非流式生成完整回复"""
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        try:
            messages = self._build_messages(prompt, context)
            payload = {
                "model": self._model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": self.config.temperature,
                    "num_predict": self.config.max_tokens,
                    "top_p": self.config.top_p,
                },
            }

            resp = requests.post(
                f"{self._host}/api/chat",
                json=payload,
                timeout=self.config.timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("message", {})
                content = (msg.get("content", "") or "").strip()
                if not content:
                    thinking = (msg.get("thinking", "") or "").strip()
                    if thinking:
                        content = _extract_reply_from_thinking(thinking)
                self._emit_message(content)
                self._set_status(EngineStatus.IDLE)
                return content
            else:
                err = f"Ollama 返回错误: HTTP {resp.status_code}"
                self._emit_error(err)
                self._set_status(EngineStatus.ERROR)
                return err

        except requests.exceptions.ConnectionError:
            err = "Ollama 连接失败，请确认服务已启动 (localhost:11434)"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err
        except requests.exceptions.Timeout:
            err = "Ollama 响应超时"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err
        except Exception as e:
            err = f"Ollama 引擎错误: {e}"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err

    def stream(self, prompt: str, context: Optional[List[Dict]] = None) -> Generator[str, None, None]:
        """流式生成，逐个 yield token"""
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        try:
            messages = self._build_messages(prompt, context)
            payload = {
                "model": self._model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": self.config.temperature,
                    "num_predict": self.config.max_tokens,
                    "top_p": self.config.top_p,
                },
            }

            resp = requests.post(
                f"{self._host}/api/chat",
                json=payload,
                stream=True,
                timeout=STREAM_TIMEOUT,
            )

            if resp.status_code != 200:
                err = f"Ollama 流式返回错误: HTTP {resp.status_code}"
                self._emit_error(err)
                self._set_status(EngineStatus.ERROR)
                yield err
                return

            full_content = ""
            full_thinking = ""
            for line in resp.iter_lines(decode_unicode=True):
                if self._cancel_flag.is_set():
                    break
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    thinking_delta = chunk.get("message", {}).get("thinking", "")
                    if thinking_delta:
                        full_thinking += thinking_delta
                    if delta:
                        full_content += delta
                        self._emit_token(delta)
                        yield delta
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue

            if not full_content and full_thinking:
                full_content = _extract_reply_from_thinking(full_thinking)
                self._emit_token(full_content)
                yield full_content

            self._emit_message(full_content)
            self._set_status(EngineStatus.IDLE)

        except requests.exceptions.ConnectionError:
            err = "Ollama 连接失败"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            yield err
        except Exception as e:
            err = f"Ollama 流式错误: {e}"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            yield err

    def generate_with_tools(self, prompt: str, tools: List[Dict],
                            context: Optional[List[Dict]] = None) -> str:
        """
        带工具调用的生成（支持流式 + 非流式）
        
        Ollama 0.5+ 支持工具调用，需模型本身支持（如 qwen3.5 系列）
        使用 stream=True 以获得更好的兼容性和速度
        """
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        try:
            messages = self._build_messages(prompt, context)
            payload = {
                "model": self._model,
                "messages": messages,
                "stream": True,  # ★ 使用流式 API 提高兼容性
                "tools": tools,
                "options": {
                    "temperature": self.config.temperature,
                    "num_predict": self.config.max_tokens,
                },
            }

            resp = requests.post(
                f"{self._host}/api/chat",
                json=payload,
                timeout=self.config.timeout,
                stream=True,  # ★ 流式请求
            )

            if resp.status_code != 200:
                err = f"Ollama 工具调用错误: HTTP {resp.status_code}"
                try:
                    detail = resp.json().get("error", "")
                    if detail:
                        err += f" - {detail}"
                except Exception:
                    pass
                self._emit_error(err)
                self._set_status(EngineStatus.ERROR)
                return err

            # ★ 从流式响应中提取完整消息（包括 tool_calls）
            full_content = ""
            full_thinking = ""
            tool_calls = []
            in_tool_call = False
            chunk_count = 0

            for line in resp.iter_lines(decode_unicode=True):
                chunk_count += 1
                if self._cancel_flag.is_set():
                    break
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    msg = chunk.get("message", {})

                    content = msg.get("content", "")
                    thinking_delta = msg.get("thinking", "")
                    if thinking_delta:
                        full_thinking += thinking_delta
                    if content:
                        full_content += content

                    if msg.get("tool_calls"):
                        tool_calls = msg.get("tool_calls")
                        in_tool_call = True
                except json.JSONDecodeError:
                    continue

            print(f"[OLLAMA_TOOLS_DEBUG] chunks={chunk_count}, in_tool_call={in_tool_call}, tool_calls={tool_calls}, full_content={repr(full_content[:100])}")

            if in_tool_call and tool_calls:
                self._set_status(EngineStatus.USING_TOOL)
                for tc in tool_calls:
                    self._emit_tool_call(tc)
                result = json.dumps({"tool_calls": tool_calls}, ensure_ascii=False)
                self._emit_message(result)
                self._set_status(EngineStatus.IDLE)
                return result

            content = full_content.strip()
            if not content and full_thinking.strip():
                content = _extract_reply_from_thinking(full_thinking)
            self._emit_message(content)
            self._set_status(EngineStatus.IDLE)
            return content

        except Exception as e:
            err = f"Ollama 工具调用异常: {e}"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err

    # ==================== 模型管理 ====================

    def get_models(self) -> List[Dict]:
        """获取本地 Ollama 已安装的模型列表"""
        now = time.time()
        if self._models_cache and (now - self._models_cache_time) < self._models_cache_ttl:
            return self._models_cache

        if requests is None:
            return []

        try:
            resp = requests.get(f"{self._host}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = []
                for m in data.get("models", []):
                    name = m.get("name", "unknown")
                    # 去除 :latest 后缀
                    clean_name = name.replace(":latest", "")
                    models.append({
                        "id": clean_name,
                        "name": clean_name,
                        "size": m.get("size", 0),
                        "details": m.get("details", {}),
                        "modified_at": m.get("modified_at", ""),
                    })
                self._models_cache = models
                self._models_cache_time = now
                return models
            return []
        except Exception:
            return []

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
        """检查 Ollama 服务是否运行"""
        if requests is None:
            return False
        try:
            resp = requests.get(f"{self._host}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def set_model(self, model_id: str):
        """切换模型"""
        if model_id:
            self._model = model_id
            self.config.model = model_id
            print(f"[OllamaEngine] 模型切换为: {model_id}")


# 注册到引擎注册表
def register():
    from core.agent_engine import EngineRegistry
    EngineRegistry.register("ollama", OllamaEngine)