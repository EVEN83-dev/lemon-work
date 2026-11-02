# -*- coding: utf-8 -*-
"""
统一 AI 接口抽象层 — AI 套壳框架核心
=====================================
设计目标：
- 抽象统一的 AI 调用接口，屏蔽不同 AI 服务的差异
- 适配器模式：每个 AI 服务一个适配器
- 智能路由：根据任务类型/复杂度/成本自动选择模型
- 支持热切换：运行时动态切换 AI 提供商

架构：
┌──────────────────────────────────────────────┐
│                IAIProvider (ABC)               │
│  chat() / stream_chat() / review_code()       │
│  is_available() / model_name / provider_type  │
├─────────────┬──────────────┬──────────────────┤
│ MIMOAdapter │ OllamaAdapter│ DeepSeekAdapter   │
│ (云端)       │ (本地)        │ (计划)            │
└─────────────┴──────────────┴──────────────────┘
                      │
              ┌───────┴────────┐
              │  AIRouter       │
              │  智能路由/分发   │
              └────────────────┘
"""

import os
import threading
import json
import requests
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Callable, Any
from enum import Enum

from PyQt5.QtCore import QObject, pyqtSignal


# ============================================================
# 类型定义
# ============================================================

class ProviderType(Enum):
    CLOUD = "cloud"       # 云端 AI（MIMO Code, DeepSeek, Claude, GPT）
    LOCAL = "local"       # 本地 AI（Ollama）
    HYBRID = "hybrid"     # 混合模式


class TaskComplexity(Enum):
    SIMPLE = "simple"      # 简单问答/闲聊
    MODERATE = "moderate"  # 中等复杂度（代码解释、文档生成）
    COMPLEX = "complex"    # 高复杂度（代码生成、架构设计、多文件操作）


class Message:
    """统一消息格式"""
    def __init__(self, role: str, content: str):
        self.role = role  # "system" | "user" | "assistant" | "tool"
        self.content = content
    
    def to_dict(self) -> Dict:
        return {"role": self.role, "content": self.content}


class ChatRequest:
    """统一聊天请求"""
    def __init__(self,
                 messages: List[Message],
                 model: str = "",
                 temperature: float = 0.7,
                 max_tokens: int = 4096,
                 stream: bool = False,
                 metadata: Dict = None):
        self.messages = messages
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
        self.metadata = metadata or {}


class ChatResponse:
    """统一聊天响应"""
    def __init__(self,
                 content: str,
                 model: str = "",
                 usage: Dict = None,
                 finish_reason: str = "stop",
                 metadata: Dict = None):
        self.content = content
        self.model = model
        self.usage = usage or {}
        self.finish_reason = finish_reason
        self.metadata = metadata or {}


# ============================================================
# IAIProvider — 抽象 AI 接口
# ============================================================

class IAIProvider(ABC):
    """AI 提供商抽象接口 — 所有 AI 适配器必须实现"""
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """提供商名称"""
        ...
    
    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """提供商类型"""
        ...
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """当前模型名称"""
        ...
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查服务是否可用"""
        ...
    
    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步聊天"""
        ...
    
    @abstractmethod
    def stream_chat(self, request: ChatRequest, on_chunk: Callable[[str], None]) -> ChatResponse:
        """流式聊天"""
        ...
    
    @abstractmethod
    def review_code(self, code: str, file_path: str = "", language: str = "") -> Optional[str]:
        """代码审查"""
        ...
    
    def cancel(self):
        """取消当前请求（可选实现）"""
        pass
    
    def list_models(self) -> List[Dict]:
        """列出可用模型（可选实现）"""
        return []
    
    def switch_model(self, model_id: str) -> bool:
        """切换模型（可选实现）"""
        return False
    
    def __repr__(self):
        return f"<{self.provider_name}:{self.model_name} ({self.provider_type.value})>"


# ============================================================
# MIMOAdapter — MIMO Code 云端适配器
# ============================================================

class MIMOAdapter(IAIProvider):
    """MIMO Code 云端 AI 适配器"""
    
    def __init__(self, serve_bridge=None):
        self._serve_bridge = serve_bridge
        self._model = "mimo-auto"
        self._lock = threading.Lock()
    
    @property
    def provider_name(self) -> str:
        return "MIMO Code"
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.CLOUD
    
    @property
    def model_name(self) -> str:
        return self._model
    
    def is_available(self) -> bool:
        return self._serve_bridge is not None and self._serve_bridge.is_connected
    
    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步聊天 — 通过 Serve Bridge 发送"""
        if not self.is_available():
            return ChatResponse(content="", finish_reason="error",
                               metadata={"error": "MIMO Code 未连接"})
        
        # 构建消息文本
        user_message = ""
        for msg in request.messages:
            if msg.role == "user":
                user_message = msg.content
                break
        
        if not user_message:
            return ChatResponse(content="", finish_reason="error",
                               metadata={"error": "无用户消息"})
        
        # 通过 Serve Bridge 发送
        try:
            self._serve_bridge.send_message(user_message)
            return ChatResponse(
                content="",  # 响应通过 SSE 信号异步返回
                model=self._model,
                finish_reason="sent",
                metadata={"async": True}
            )
        except Exception as e:
            return ChatResponse(content="", finish_reason="error",
                               metadata={"error": str(e)})
    
    def stream_chat(self, request: ChatRequest, on_chunk: Callable[[str], None]) -> ChatResponse:
        """流式聊天 — MIMO Code 通过 SSE 原生支持流式"""
        # MIMO Code 的 SSE 流由 serve_bridge 自动处理
        # 这里直接调用 chat，响应通过信号异步返回
        return self.chat(request)
    
    def review_code(self, code: str, file_path: str = "", language: str = "") -> Optional[str]:
        """代码审查 — 委托给 MIMO Code"""
        if not self.is_available():
            return None
        
        review_prompt = f"""请审查以下代码，找出潜在问题并给出改进建议。
审查要点：代码逻辑错误、性能问题、安全漏洞、代码风格、最佳实践建议。
请用中文简洁回复。

代码：
```
{code[:3000]}
```"""
        self._serve_bridge.send_message(review_prompt)
        return None  # 响应通过 SSE 信号异步返回
    
    def list_models(self) -> List[Dict]:
        if self._serve_bridge:
            return self._serve_bridge.list_models()
        return []
    
    def switch_model(self, model_id: str) -> bool:
        if self._serve_bridge:
            self._serve_bridge.switch_model(model_id)
            self._model = model_id
            return True
        return False


# ============================================================
# OllamaAdapter — Ollama 本地模型适配器
# ============================================================

class OllamaAdapter(IAIProvider):
    """Ollama 本地 AI 适配器"""
    
    def __init__(self, ollama_bridge=None):
        self._bridge = ollama_bridge
        self._model = "qwen3.5:4b"
        self._lock = threading.Lock()
    
    @property
    def provider_name(self) -> str:
        return "Ollama"
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.LOCAL
    
    @property
    def model_name(self) -> str:
        return self._model
    
    def is_available(self) -> bool:
        if self._bridge:
            return self._bridge.is_available()
        return False
    
    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步聊天 — 通过 Ollama Bridge"""
        if not self.is_available():
            return ChatResponse(content="", finish_reason="error",
                               metadata={"error": "Ollama 未连接"})
        
        user_message = ""
        for msg in request.messages:
            if msg.role == "user":
                user_message = msg.content
                break
        
        if not user_message:
            return ChatResponse(content="", finish_reason="error",
                               metadata={"error": "无用户消息"})
        
        # Ollama 通过信号异步返回，这里返回空响应
        try:
            self._bridge.chat(user_message)
            return ChatResponse(
                content="",
                model=self._model,
                finish_reason="sent",
                metadata={"async": True}
            )
        except Exception as e:
            return ChatResponse(content="", finish_reason="error",
                               metadata={"error": str(e)})
    
    def stream_chat(self, request: ChatRequest, on_chunk: Callable[[str], None]) -> ChatResponse:
        return self.chat(request)
    
    def review_code(self, code: str, file_path: str = "", language: str = "") -> Optional[str]:
        if not self.is_available():
            return None
        self._bridge.review_code(code, file_path, language)
        return None  # 响应通过信号异步返回
    
    def switch_model(self, model_id: str) -> bool:
        if self._bridge:
            self._bridge.model = model_id
            self._model = model_id
            return True
        return False


# ============================================================
# OpenAICompatibleAdapter — 通用 OpenAI 兼容 API 适配器
# ============================================================

class OpenAICompatibleAdapter(IAIProvider):
    """通用 OpenAI 兼容 API 适配器（基类）
    
    支持任何 OpenAI API 兼容的服务：
    - DeepSeek (api.deepseek.com)
    - 硅基流动 (api.siliconflow.cn)
    - 通义千问 (dashscope.aliyuncs.com/compatible-mode)
    - 自定义 OpenAI 兼容端点
    """
    
    def __init__(self, 
                 api_base: str = "",
                 api_key: str = "",
                 model: str = "",
                 provider_name: str = "OpenAI Compatible",
                 provider_type: ProviderType = ProviderType.CLOUD):
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._name = provider_name
        self._type = provider_type
        self._lock = threading.Lock()
        self._available = False
        self._check_availability()
    
    @property
    def provider_name(self) -> str:
        return self._name
    
    @property
    def provider_type(self) -> ProviderType:
        return self._type
    
    @property
    def model_name(self) -> str:
        return self._model
    
    def _check_availability(self):
        """检查 API 可用性"""
        if not self._api_base or not self._api_key:
            self._available = False
            return
        try:
            resp = requests.get(
                f"{self._api_base}/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=5
            )
            self._available = resp.status_code == 200
        except Exception:
            self._available = False
    
    def is_available(self) -> bool:
        return self._available and bool(self._api_key)
    
    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步聊天"""
        if not self.is_available():
            return ChatResponse(content="", finish_reason="error",
                               metadata={"error": f"{self._name} 不可用"})
        
        messages = [msg.to_dict() for msg in request.messages]
        
        try:
            resp = requests.post(
                f"{self._api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens,
                    "stream": False,
                },
                timeout=120
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return ChatResponse(
                    content=content,
                    model=data.get("model", self._model),
                    usage=usage,
                    finish_reason=data["choices"][0].get("finish_reason", "stop"),
                )
            else:
                return ChatResponse(content="", finish_reason="error",
                                   metadata={"error": f"API {resp.status_code}: {resp.text[:200]}"})
        except Exception as e:
            return ChatResponse(content="", finish_reason="error",
                               metadata={"error": str(e)})
    
    def stream_chat(self, request: ChatRequest, on_chunk: Callable[[str], None]) -> ChatResponse:
        """流式聊天"""
        if not self.is_available():
            return ChatResponse(content="", finish_reason="error",
                               metadata={"error": f"{self._name} 不可用"})
        
        messages = [msg.to_dict() for msg in request.messages]
        full_content = ""
        
        try:
            resp = requests.post(
                f"{self._api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens,
                    "stream": True,
                },
                stream=True,
                timeout=120
            )
            
            if resp.status_code != 200:
                return ChatResponse(content="", finish_reason="error",
                                   metadata={"error": f"API {resp.status_code}"})
            
            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content += content
                            on_chunk(content)
                    except json.JSONDecodeError:
                        continue
            
            return ChatResponse(
                content=full_content,
                model=self._model,
                finish_reason="stop",
            )
        except Exception as e:
            return ChatResponse(content=full_content, finish_reason="error",
                               metadata={"error": str(e)})
    
    def review_code(self, code: str, file_path: str = "", language: str = "") -> Optional[str]:
        """代码审查"""
        if not self.is_available():
            return None
        
        review_prompt = f"""请审查以下{language or ''}代码，找出潜在问题并给出改进建议。
审查要点：代码逻辑错误、性能问题、安全漏洞、代码风格、最佳实践建议。
请用中文简洁回复。

代码文件：{file_path or '未命名'}
```{language or ''}
{code[:4000]}
```"""
        request = ChatRequest(
            messages=[Message("user", review_prompt)],
            temperature=0.3,
            max_tokens=2048,
        )
        response = self.chat(request)
        return response.content if response.finish_reason == "stop" else None
    
    def switch_model(self, model_id: str) -> bool:
        self._model = model_id
        return True
    
    def update_config(self, api_base: str = "", api_key: str = "", model: str = ""):
        """更新配置"""
        if api_base:
            self._api_base = api_base.rstrip("/")
        if api_key:
            self._api_key = api_key
        if model:
            self._model = model
        self._check_availability()


# ============================================================
# DeepSeekAdapter — DeepSeek 专用适配器
# ============================================================

class DeepSeekAdapter(OpenAICompatibleAdapter):
    """DeepSeek API 适配器（预配置）"""
    
    def __init__(self, api_key: str = ""):
        super().__init__(
            api_base="https://api.deepseek.com",
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY", ""),
            model="deepseek-chat",
            provider_name="DeepSeek",
            provider_type=ProviderType.CLOUD,
        )


# ============================================================
# AIRouter — 智能路由引擎（v2.0 多模型协同）
# ============================================================

class AIRouter(QObject):
    """
    智能 AI 路由引擎（v2.0 — 多模型协同）
    
    路由策略：
    1. 简单任务 → 本地 Ollama（快速、免费、隐私）
    2. 中等任务 → 本地优先，不可用时用云端
    3. 复杂任务 → 云端 MIMO Code（强算力、文件操作）
    4. 代码审查 → 本地 Ollama（隐私、免费）
    5. 文件操作 → 云端 MIMO Code（必需）
    
    多模型协同模式：
    - chain: 链式调用，前一个模型的输出作为后一个的输入
    - parallel: 并行调用多个模型，聚合结果
    - vote: 多模型投票，选择最优结果
    - fallback: 主模型失败时自动切换到备用模型
    """
    
    # 信号
    route_decision = pyqtSignal(str, str, str)  # (task, provider, reason)
    provider_changed = pyqtSignal(str)  # provider_name
    
    # 简单任务关键词
    SIMPLE_KEYWORDS = [
        '你好', '谢谢', '帮助', '是什么', '解释', '什么意思',
        'hello', 'hi', 'help', 'what is', 'how to',
        '?', '？', '怎么样', '好不好',
    ]
    
    # 复杂任务关键词
    COMPLEX_KEYWORDS = [
        '创建', '生成', '构建', '重构', '优化', '实现',
        'create', 'generate', 'build', 'refactor', 'implement',
        '文件', '项目', '架构', '部署', '测试',
        'file', 'project', 'architecture', 'deploy', 'test',
        '帮我写', '帮我做', '修改', '添加功能',
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._providers: Dict[str, IAIProvider] = {}
        self._default_provider = "mimo"
    
    def register_provider(self, name: str, provider: IAIProvider):
        """注册 AI 提供商"""
        self._providers[name] = provider
    
    def unregister_provider(self, name: str):
        """注销 AI 提供商"""
        self._providers.pop(name, None)
    
    def get_provider(self, name: str) -> Optional[IAIProvider]:
        return self._providers.get(name)
    
    @property
    def providers(self) -> Dict[str, IAIProvider]:
        return dict(self._providers)
    
    def classify_task(self, message: str) -> TaskComplexity:
        """根据消息内容分类任务复杂度"""
        msg_lower = message.lower()
        
        # 检查复杂任务关键词
        for kw in self.COMPLEX_KEYWORDS:
            if kw in msg_lower:
                return TaskComplexity.COMPLEX
        
        # 检查简单任务关键词
        for kw in self.SIMPLE_KEYWORDS:
            if kw in msg_lower:
                return TaskComplexity.SIMPLE
        
        # 基于消息长度判断
        if len(message) < 20:
            return TaskComplexity.SIMPLE
        elif len(message) < 100:
            return TaskComplexity.MODERATE
        else:
            return TaskComplexity.COMPLEX
    
    def route(self, message: str, preferred: str = None) -> Optional[IAIProvider]:
        """
        智能路由：根据任务类型选择最佳 AI 提供商
        
        返回最优的 IAIProvider，或 None
        """
        # 如果指定了优先提供商且可用
        if preferred and preferred in self._providers:
            provider = self._providers[preferred]
            if provider.is_available():
                self.route_decision.emit(message, preferred, "用户指定")
                return provider
        
        complexity = self.classify_task(message)
        
        # 简单任务 → 本地 Ollama
        if complexity == TaskComplexity.SIMPLE:
            ollama = self._providers.get("ollama")
            if ollama and ollama.is_available():
                self.route_decision.emit(message, "ollama", "简单任务→本地")
                return ollama
        
        # 复杂任务 → 云端 MIMO Code
        if complexity == TaskComplexity.COMPLEX:
            mimo = self._providers.get("mimo")
            if mimo and mimo.is_available():
                self.route_decision.emit(message, "mimo", "复杂任务→云端")
                return mimo
        
        # 中等任务 → 本地优先
        if complexity == TaskComplexity.MODERATE:
            ollama = self._providers.get("ollama")
            if ollama and ollama.is_available():
                self.route_decision.emit(message, "ollama", "中等任务→本地优先")
                return ollama
        
        # 回退：任意可用提供商
        for name, provider in self._providers.items():
            if provider.is_available():
                self.route_decision.emit(message, name, "回退")
                return provider
        
        return None
    
    def route_code_review(self, code: str, file_path: str = "") -> Optional[IAIProvider]:
        """代码审查专用路由 — 优先本地"""
        ollama = self._providers.get("ollama")
        if ollama and ollama.is_available():
            return ollama
        
        mimo = self._providers.get("mimo")
        if mimo and mimo.is_available():
            return mimo
        
        return None
    
    def get_available_providers(self) -> List[str]:
        """获取所有可用的提供商名称"""
        return [name for name, p in self._providers.items() if p.is_available()]
    
    def get_summary(self) -> Dict:
        """获取路由状态摘要"""
        providers_info = {}
        for name, p in self._providers.items():
            providers_info[name] = {
                "name": p.provider_name,
                "type": p.provider_type.value,
                "model": p.model_name,
                "available": p.is_available(),
            }
        return {
            "total": len(self._providers),
            "available": len(self.get_available_providers()),
            "providers": providers_info,
        }
    
    # ================================================================
    # 多模型协同（v2.0 新增）
    # ================================================================
    
    def collaborate_chain(self, message: str, provider_names: List[str]) -> Optional[str]:
        """
        链式协同：按顺序调用多个模型，前一个输出作为后一个输入
        
        适用场景：
        - 复杂任务分解：先让一个模型分析，另一个模型执行
        - 代码生成+审查：先生成代码，再审查优化
        """
        current_input = message
        final_output = ""
        
        for i, name in enumerate(provider_names):
            provider = self._providers.get(name)
            if not provider or not provider.is_available():
                continue
            
            request = ChatRequest(
                messages=[Message("user", current_input)],
                temperature=0.7 if i == 0 else 0.3,
            )
            response = provider.chat(request)
            
            if response.finish_reason == "stop":
                final_output = response.content
                current_input = response.content  # 传递给下一个模型
            else:
                break
        
        return final_output
    
    def collaborate_parallel(self, message: str, provider_names: List[str]) -> Dict[str, str]:
        """
        并行协同：同时调用多个模型，聚合所有结果
        
        适用场景：
        - 多角度分析：不同模型给出不同视角
        - 创意发散：多模型头脑风暴
        """
        results = {}
        threads = []
        
        def _call_provider(name: str, msg: str):
            provider = self._providers.get(name)
            if provider and provider.is_available():
                request = ChatRequest(messages=[Message("user", msg)])
                response = provider.chat(request)
                if response.finish_reason == "stop":
                    results[name] = response.content
                else:
                    results[name] = f"[错误] {response.metadata.get('error', '未知')}"
        
        for name in provider_names:
            t = threading.Thread(target=_call_provider, args=(name, message))
            t.start()
            threads.append(t)
        
        for t in threads:
            t.join(timeout=120)
        
        return results
    
    def collaborate_vote(self, message: str, provider_names: List[str],
                         judge_provider: str = None) -> Dict:
        """
        投票协同：多模型并行输出，用评判模型选出最优结果
        
        适用场景：
        - 关键决策：需要多个模型验证
        - 代码生成：多个模型生成代码，选最优方案
        """
        # 并行获取所有模型输出
        results = self.collaborate_parallel(message, provider_names)
        
        if len(results) < 2:
            return {"winner": list(results.keys())[0] if results else None,
                    "results": results, "reason": "不足2个可用模型"}
        
        # 用评判模型选择最优
        judge = provider_names[0]  # 默认用第一个
        if judge_provider and judge_provider in self._providers:
            judge = judge_provider
        
        judge_prompt = f"""请从以下{len(results)}个AI模型的回答中选出最优的一个。
只输出模型名称（如"model_1"），不要解释。

原始问题：{message[:200]}

"""
        for i, (name, content) in enumerate(results.items(), 1):
            judge_prompt += f"--- model_{i} ({name}) ---\n{content[:500]}\n\n"
        
        judge_prompt += f"\n最优模型是: model_"
        
        provider = self._providers.get(judge)
        if provider and provider.is_available():
            request = ChatRequest(
                messages=[Message("user", judge_prompt)],
                temperature=0.1,
                max_tokens=10,
            )
            response = provider.chat(request)
            winner_idx = response.content.strip() if response.finish_reason == "stop" else "1"
        else:
            winner_idx = "1"
        
        # 解析胜出者
        try:
            idx = int(''.join(c for c in winner_idx if c.isdigit()) or "1")
            winner = list(results.keys())[min(idx - 1, len(results) - 1)]
        except (ValueError, IndexError):
            winner = list(results.keys())[0]
        
        return {
            "winner": winner,
            "winner_content": results.get(winner, ""),
            "results": results,
            "reason": f"评判模型 {judge} 选择 model_{winner_idx}",
        }
    
    def collaborate_fallback(self, message: str, 
                             primary: str, fallbacks: List[str]) -> ChatResponse:
        """
        回退协同：主模型优先，失败时自动切换到备用模型
        
        适用场景：
        - 高可用需求：确保任务始终能完成
        - 成本控制：优先用便宜的，不可用时用贵的
        """
        # 尝试主模型
        provider = self._providers.get(primary)
        if provider and provider.is_available():
            request = ChatRequest(messages=[Message("user", message)])
            response = provider.chat(request)
            if response.finish_reason == "stop":
                return response
        
        # 回退到备用模型
        for name in fallbacks:
            provider = self._providers.get(name)
            if provider and provider.is_available():
                request = ChatRequest(messages=[Message("user", message)])
                response = provider.chat(request)
                if response.finish_reason == "stop":
                    response.metadata["fallback_from"] = primary
                    return response
        
        return ChatResponse(content="", finish_reason="error",
                           metadata={"error": "所有模型不可用"})