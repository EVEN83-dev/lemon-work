# -*- coding: utf-8 -*-
"""
DeepSeek 云端引擎 — 基于 DeepSeek Cloud API 的 Agent 算力引擎
=============================================================
支持 DeepSeek V4 Flash / V4 Pro / V3 等云端模型。

API 兼容 OpenAI 格式，只需修改 base_url 即可调用。
默认使用免费额度（注册送 100 万 Token）。

API 文档：https://api-docs.deepseek.com/
"""

import json
import os
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


# 默认配置
DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"  # 会自动映射到当前稳定版
REQUEST_TIMEOUT = 120
STREAM_TIMEOUT = 300

# 限流 / 配额类 HTTP 状态 → 轮换 Key
_RATE_LIMIT_STATUSES = frozenset({429, 402})


class DeepSeekKeyRotator:
    """DeepSeek API Key 轮换器（工程安全 D2）。

    - 支持多 Key 池：环境变量（逗号分隔多个 Key）、密钥文件（每行一个 Key，# 注释）。
    - 单 Key 时退化为无轮换直接使用（向后兼容）。
    - 遇限流(429/402)/配额/鉴权失效(401)自动切到下一可用 Key，并对短期失效
      Key 设置冷却时间，避免死循环。
    - 线程安全（引擎可能在多线程中被调用）。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._keys: List[str] = []
        self._index = 0
        self._cooldown_until: Dict[str, float] = {}
        self.reload()

    # ---- Key 来源 ----
    def _collect(self) -> List[str]:
        keys: List[str] = []
        # 1. 环境变量（支持逗号分隔多个 Key），修复原重复变量 bug
        for var in ("DEEPSEEK_API_KEY", "DEEPSEEK_KEY"):
            raw = os.environ.get(var, "")
            for part in raw.split(","):
                k = part.strip()
                if k:
                    keys.append(k)
        # 2. 配置文件 ~/.deepseek_key（保留 B5 权限告警）
        key_file = os.path.expanduser("~/.deepseek_key")
        try:
            if os.path.exists(key_file):
                with open(key_file, "r") as f:
                    for line in f:
                        k = line.strip()
                        if k and not k.startswith("#"):
                            keys.append(k)
                try:
                    import stat
                    file_stat = os.stat(key_file)
                    if file_stat.st_mode & (stat.S_IRGRP | stat.S_IROTH):
                        print(f"[DeepSeek] ⚠️ API Key 文件权限过于宽松: {key_file}")
                        print(f"[DeepSeek] 建议: chmod 600 {key_file}")
                except Exception:
                    pass
        except Exception:
            pass
        # 3. 项目本地配置文件（仅开发调试，不提交版本控制）
        # 候选路径：standard_mode/.deepseek_key、lemon_agent/.deepseek_key
        _this_dir = os.path.dirname(os.path.abspath(__file__))   # standard_mode/core
        _std_mode_dir = os.path.dirname(_this_dir)                # standard_mode
        _project_root = os.path.dirname(_std_mode_dir)            # lemon_agent
        for path in (os.path.join(_std_mode_dir, ".deepseek_key"),
                     os.path.join(_project_root, ".deepseek_key")):
            try:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        for line in f:
                            k = line.strip()
                            if k and not k.startswith("#"):
                                keys.append(k)
            except Exception:
                pass
        # 去重保序
        seen = set()
        dedup = []
        for k in keys:
            if k not in seen:
                seen.add(k)
                dedup.append(k)
        return dedup

    def reload(self) -> int:
        """重新加载 Key 池，返回 Key 数量。"""
        keys = self._collect()
        with self._lock:
            self._keys = keys
            self._index = 0
            self._cooldown_until = {k: 0.0 for k in keys}
        return len(keys)

    # ---- 访问 ----
    @property
    def count(self) -> int:
        return len(self._keys)

    @property
    def has_multiple(self) -> bool:
        return len(self._keys) > 1

    @property
    def current(self) -> str:
        with self._lock:
            if not self._keys:
                return ""
            return self._keys[self._index % len(self._keys)]

    def masked_current(self) -> str:
        k = self.current
        if len(k) <= 8:
            return "****"
        return k[:4] + "****" + k[-4:]

    def mark_failed(self, cooldown: float = 60.0) -> None:
        """标记当前 Key 短期失效并轮换到下一个可用 Key。"""
        with self._lock:
            if not self._keys:
                return
            i = self._index % len(self._keys)
            self._cooldown_until[self._keys[i]] = time.time() + cooldown
            n = len(self._keys)
            for step in range(1, n + 1):
                nxt = (i + step) % n
                if self._cooldown_until.get(self._keys[nxt], 0.0) <= time.time():
                    self._index = nxt
                    break

    def set_single(self, api_key: str) -> None:
        """用单个 Key（通常来自 UI 设置）重置池。"""
        with self._lock:
            self._keys = [api_key]
            self._index = 0
            self._cooldown_until = {api_key: 0.0}


class DeepSeekRequestError(Exception):
    """封装 DeepSeek 请求级错误（含 HTTP 状态与响应体摘要）。"""

    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body


# 预定义模型列表（免费/低成本）
AVAILABLE_MODELS = [
    {
        "id": "deepseek-chat",
        "name": "DeepSeek Chat (V3)",
        "description": "默认模型，免费额度可用",
        "pricing": "免费额度",
        "context_length": 65536,
    },
    {
        "id": "deepseek-reasoner",
        "name": "DeepSeek Reasoner (R1)",
        "description": "推理增强模型",
        "pricing": "按量计费",
        "context_length": 65536,
    },
    {
        "id": "deepseek-reasoner",
        "name": "DeepSeek Reasoner (R1)",
        "description": "深度推理模型，适合复杂问题",
        "pricing": "免费额度",
        "context_length": 65536,
    },
    {
        "id": "deepseek-r1",
        "name": "DeepSeek R1",
        "description": "深度推理模型，适合复杂问题",
        "pricing": "免费额度",
        "context_length": 65536,
    },
    {
        "id": "deepseek-coder",
        "name": "DeepSeek Coder",
        "description": "代码专用模型",
        "pricing": "免费额度",
        "context_length": 32768,
    },
]


class DeepSeekEngine(AgentEngine):
    """
    DeepSeek 云端推理引擎
    
    能力：
    - 流式/非流式生成
    - 工具调用（function calling）
    - 超长上下文（100万 token）
    - 多模态支持（V4 系列）
    - 云端部署，无需本地算力
    """

    def __init__(self, config: Optional[EngineConfig] = None):
        # 确保至少有一个默认模型
        if config is None:
            config = EngineConfig(model=DEFAULT_MODEL)
        elif not config.model:
            config.model = DEFAULT_MODEL

        super().__init__(config)
        self._name = "deepseek"
        self._display_name = "DeepSeek 云端"
        self._capabilities = [
            EngineCapability.STREAMING,
            EngineCapability.TOOL_CALLING,
            EngineCapability.FILE_OPERATIONS,
            EngineCapability.CODE_EXECUTION,
            EngineCapability.LONG_CONTEXT,
            EngineCapability.CLOUD_ONLY,
        ]
        self._api_base = DEEPSEEK_API_BASE
        self._model = config.model
        self._key_rotator = DeepSeekKeyRotator()
        self._api_key = self._key_rotator.current  # 向后兼容只读字段
        # 缓存模型列表
        self._models_cache: List[Dict] = []
        self._models_cache_time = 0
        self._models_cache_ttl = 60  # 秒

    # ==================== 核心方法 ====================

    def _headers(self) -> Dict:
        """构建请求头"""
        return {
            "Authorization": f"Bearer {self._key_rotator.current}",
            "Content-Type": "application/json",
        }

    def _chat_post(self, payload: Dict, *, stream: bool, timeout: int):
        """带 Key 轮换的 chat/completions POST。

        遇限流/配额(429/402)/鉴权失效(401)自动轮换重试，最多尝试全部 Key 一次。
        返回 status==200 的 requests.Response；其它错误抛出 DeepSeekRequestError。
        """
        attempts = self._key_rotator.count if self._key_rotator.has_multiple else 1
        last_err = None
        for _ in range(max(attempts, 1)):
            key = self._key_rotator.current
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            try:
                resp = requests.post(
                    f"{self._api_base}/chat/completions",
                    headers=headers, json=payload,
                    stream=stream, timeout=timeout,
                )
            except requests.exceptions.ConnectionError as e:
                self._key_rotator.mark_failed(cooldown=60)
                last_err = DeepSeekRequestError("DeepSeek 连接失败，请检查网络", body=str(e))
                continue
            except Exception as e:
                raise DeepSeekRequestError(f"DeepSeek 请求异常: {e}", body=str(e))

            if resp.status_code == 200:
                return resp

            body = ""
            try:
                body = resp.text[:300]
            except Exception:
                pass
            lower = body.lower()
            if resp.status_code in _RATE_LIMIT_STATUSES or "quota" in lower or "rate" in lower:
                print(f"[DeepSeek] Key {self._key_rotator.masked_current()} 触发限流(HTTP {resp.status_code})，轮换下一 Key")
                self._key_rotator.mark_failed(cooldown=300)
                last_err = DeepSeekRequestError(
                    f"DeepSeek API 限流/配额: HTTP {resp.status_code} - {body}", resp.status_code, body)
                continue
            if resp.status_code == 401:
                print(f"[DeepSeek] Key {self._key_rotator.masked_current()} 鉴权失败(HTTP 401)，轮换下一 Key")
                self._key_rotator.mark_failed(cooldown=3600)
                last_err = DeepSeekRequestError(f"DeepSeek API Key 无效: HTTP 401", 401, body)
                continue
            # 其它错误（如 400 参数错误）不轮换，直接上抛
            raise DeepSeekRequestError(
                f"DeepSeek API 错误: HTTP {resp.status_code} - {body}", resp.status_code, body)

        raise last_err or DeepSeekRequestError("DeepSeek 所有 Key 均不可用")

    def generate(self, prompt: str, context: Optional[List[Dict]] = None) -> str:
        """非流式生成完整回复"""
        if self._key_rotator.count == 0:
            err = "DeepSeek API Key 未配置。请设置环境变量 DEEPSEEK_API_KEY 或创建 ~/.deepseek_key 文件"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err

        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        try:
            messages = self._build_messages(prompt, context)
            payload = {
                "model": self._model,
                "messages": messages,
                "stream": False,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "top_p": self.config.top_p,
            }
            resp = self._chat_post(payload, stream=False, timeout=self.config.timeout)
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            self._emit_message(content)
            self._set_status(EngineStatus.IDLE)
            return content
        except DeepSeekRequestError as e:
            self._emit_error(e.message)
            self._set_status(EngineStatus.ERROR)
            return e.message
        except Exception as e:
            err = f"DeepSeek 引擎错误: {e}"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err

    def stream(self, prompt: str, context: Optional[List[Dict]] = None) -> Generator[str, None, None]:
        """流式生成，逐个 yield token"""
        if self._key_rotator.count == 0:
            err = "DeepSeek API Key 未配置"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            yield err
            return

        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        try:
            messages = self._build_messages(prompt, context)
            payload = {
                "model": self._model,
                "messages": messages,
                "stream": True,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "top_p": self.config.top_p,
            }
            resp = self._chat_post(payload, stream=True, timeout=STREAM_TIMEOUT)

            full_content = ""
            for line in resp.iter_lines(decode_unicode=True):
                if self._cancel_flag.is_set():
                    break
                if not line:
                    continue
                if line.startswith("data: "):
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
        except DeepSeekRequestError as e:
            self._emit_error(e.message)
            self._set_status(EngineStatus.ERROR)
            yield e.message
        except Exception as e:
            err = f"DeepSeek 流式错误: {e}"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            yield err

    def generate_with_tools(self, prompt: str, tools: List[Dict],
                            context: Optional[List[Dict]] = None) -> str:
        """带工具调用的生成（DeepSeek 原生支持 function calling，使用流式 API）"""
        if self._key_rotator.count == 0:
            err = "DeepSeek API Key 未配置"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err

        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        try:
            messages = self._build_messages(prompt, context)
            payload = {
                "model": self._model,
                "messages": messages,
                "tools": tools,
                "stream": True,  # ★ 使用流式 API
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }
            resp = self._chat_post(payload, stream=True, timeout=self.config.timeout)

            # ★ 从流式响应中累积完整消息
            full_content = ""
            tool_calls = []
            in_tool_call = False

            for line in resp.iter_lines(decode_unicode=True):
                if self._cancel_flag.is_set():
                    break
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]  # Remove "data: " prefix
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content += content
                        # 检查 tool_calls（在 delta 中累积）
                        tc_delta = delta.get("tool_calls", [])
                        if tc_delta:
                            in_tool_call = True
                            for tc in tc_delta:
                                # 累积 tool_calls（合并多个 delta）
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
        except DeepSeekRequestError as e:
            self._emit_error(e.message)
            self._set_status(EngineStatus.ERROR)
            return e.message
        except Exception as e:
            err = f"DeepSeek 工具调用异常: {e}"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            return err

    # ==================== 模型管理 ====================

    def get_models(self) -> List[Dict]:
        """获取可用模型列表（预定义 + API 实时查询）"""
        now = time.time()
        if self._models_cache and (now - self._models_cache_time) < self._models_cache_ttl:
            return self._models_cache

        # 使用预定义模型列表
        models = list(AVAILABLE_MODELS)

        # 尝试从 API 获取实时模型列表
        if self._key_rotator.current:
            try:
                resp = requests.get(
                    f"{self._api_base}/models",
                    headers=self._headers(),
                    timeout=5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    api_models = data.get("data", [])
                    if api_models:
                        # 合并：优先使用 API 返回的模型
                        api_ids = {m["id"] for m in api_models}
                        for m in models:
                            if m["id"] in api_ids:
                                m["available"] = True
                        for m in api_models:
                            if m["id"] not in {x["id"] for x in models}:
                                models.append({
                                    "id": m["id"],
                                    "name": m["id"],
                                    "description": "从 API 获取",
                                    "available": True,
                                })
            except Exception:
                pass

        self._models_cache = models
        self._models_cache_time = now
        return models

    def get_status_info(self) -> Dict:
        """获取引擎状态信息"""
        available = self.is_available()
        models = self.get_models() if available else AVAILABLE_MODELS
        return {
            "name": self._name,
            "display_name": self._display_name,
            "available": available,
            "status": self._status.value,
            "model": self._model,
            "models": models,
            "models_count": len(models),
            "api_base": self._api_base,
            "has_api_key": self._key_rotator.count > 0,
            "api_key_count": self._key_rotator.count,
            "api_key_current": self._key_rotator.masked_current(),
        }

    def is_available(self) -> bool:
        """检查 DeepSeek API 是否可用（有 API Key 且可连通）"""
        if self._key_rotator.count == 0:
            return False
        if requests is None:
            return False
        try:
            resp = requests.get(
                f"{self._api_base}/models",
                headers=self._headers(),
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def set_model(self, model_id: str):
        """切换模型"""
        if model_id:
            self._model = model_id
            self.config.model = model_id
            print(f"[DeepSeekEngine] 模型切换为: {model_id}")

    def set_api_key(self, api_key: str):
        """设置 API Key（UI 注入），重置为单 Key 池。"""
        if api_key:
            self._key_rotator.set_single(api_key)
            self._api_key = api_key  # 向后兼容只读字段
            print(f"[DeepSeekEngine] API Key 已设置（共 {self._key_rotator.count} 个）")


# 注册到引擎注册表
def register():
    from core.agent_engine import EngineRegistry
    EngineRegistry.register("deepseek", DeepSeekEngine)