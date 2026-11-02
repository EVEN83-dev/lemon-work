# -*- coding: utf-8 -*-
"""
LLAMA 本地引擎

功能：
- 不依赖 mimo.exe，直接使用 Ollama API
- 支持链式思考调用（多次调用）
- Skill 调用接口
- 与标准模式右侧栏无缝集成

使用方式：
    from core.llama_engine import LLAMAEngine

    engine = LLAMAEngine(model="llama3.1:8b")
    result = engine.chat("计算 2+2")
    # result = {"reply": "2+2=4", "turns": 1, "thoughts": []}

    # 链式思考
    result = engine.chat("解释量子力学", max_turns=3)
"""

import json
import time
import requests
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass


@dataclass
class ThoughtTurn:
    """单次思考记录"""
    turn: int
    thought: str
    action: Optional[str] = None
    result: Optional[str] = None


class LLAMAEngine:
    """
    LLAMA 本地引擎

    特点：
    - 完全脱离 MIMO Code 依赖
    - 使用 Ollama 作为推理后端
    - 支持多次链式思考
    - 内置 Skill 调用能力
    """

    DEFAULT_MODEL = "llama3.1:8b"
    OLLAMA_BASE_URL = "http://127.0.0.1:11434"

    def __init__(self, model: str = None, base_url: str = None):
        """
        初始化 LLAMA 引擎

        参数：
            model: 模型名称，默认 llama3.1:8b
            base_url: Ollama API 地址，默认 http://127.0.0.1:11434
        """
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url or self.OLLAMA_BASE_URL
        self._available = None
        self._skills: Dict[str, Callable] = {}

        # 思考链配置
        self.max_tokens_per_turn = 512
        self.thought_end_marker = "[THOUGHT_END]"

        print(f"[LLAMAEngine] 初始化完成: model={self.model}, base_url={self.base_url}")

    # ============================================================
    # 核心方法
    # ============================================================

    def chat(self, prompt: str, max_turns: int = 1, context: List[Dict] = None) -> Dict:
        """
        对话接口（支持链式思考）

        参数：
            prompt: 用户输入
            max_turns: 最大思考次数
            context: 上下文历史

        返回：
            {
                "reply": "最终回复",
                "turns": 实际调用次数,
                "thoughts": [ThoughtTurn, ...],
                "elapsed_ms": 耗时毫秒
            }
        """
        start_time = time.time()
        thoughts: List[ThoughtTurn] = []
        context = context or []

        current_prompt = prompt
        final_reply = ""

        for turn in range(1, max_turns + 1):
            # 调用 Ollama
            response = self._call_ollama(current_prompt, context)

            if not response.get("success"):
                return {
                    "reply": f"Ollama 调用失败: {response.get('error')}",
                    "turns": turn,
                    "thoughts": thoughts,
                    "elapsed_ms": int((time.time() - start_time) * 1000)
                }

            reply_text = response.get("text", "")

            # 记录思考
            thought = ThoughtTurn(
                turn=turn,
                thought=reply_text[:200] + "..." if len(reply_text) > 200 else reply_text
            )

            # 检查是否需要继续思考
            if self._is_final_reply(reply_text) or turn == max_turns:
                final_reply = reply_text
                thoughts.append(thought)
                break
            else:
                # 继续思考
                thoughts.append(thought)
                current_prompt = f"继续思考：{reply_text}"
                context.append({"role": "assistant", "content": reply_text})

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "reply": final_reply,
            "turns": len(thoughts),
            "thoughts": thoughts,
            "elapsed_ms": elapsed_ms
        }

    def _call_ollama(self, prompt: str, context: List[Dict] = None) -> Dict:
        """
        调用 Ollama API

        返回：
            {"success": bool, "text": str, "error": str}
        """
        try:
            messages = []
            if context:
                messages.extend(context)
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": self.max_tokens_per_turn,
                    "temperature": 0.7
                }
            }

            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                data = response.json()
                text = data.get("message", {}).get("content", "")
                return {"success": True, "text": text}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _is_final_reply(self, text: str) -> bool:
        """判断是否是最终回复（不需要继续思考）"""
        # 简单规则：包含明确答案的标记
        final_markers = [
            self.thought_end_marker,
            "最终答案：",
            "答案是：",
            "总结：",
        ]
        return any(marker in text for marker in final_markers)

    # ============================================================
    # 流式接口（兼容标准模式）
    # ============================================================

    def stream(self, prompt: str, context: List[Dict] = None):
        """
        流式生成（兼容标准模式的 stream() 接口）

        Yields:
            文本片段
        """
        try:
            messages = []
            if context:
                messages.extend(context)
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "options": {
                    "num_predict": self.max_tokens_per_turn,
                    "temperature": 0.7
                }
            }

            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=60
            )

            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line.decode('utf-8'))
                            if 'message' in data and 'content' in data['message']:
                                yield data['message']['content']
                        except json.JSONDecodeError:
                            continue
            else:
                yield f"[Error] HTTP {response.status_code}"

        except Exception as e:
            yield f"[Error] {e}"

    # ============================================================
    # Skill 接口
    # ============================================================

    def register_skill(self, name: str, handler: Callable):
        """注册 Skill"""
        self._skills[name] = handler
        print(f"[LLAMAEngine] Skill 已注册: {name}")

    def call_skill(self, name: str, params: Dict) -> Dict:
        """调用 Skill"""
        if name not in self._skills:
            return {"success": False, "error": f"Skill '{name}' 未注册"}

        try:
            result = self._skills[name](**params)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_skills(self) -> List[str]:
        """列出已注册的 Skill"""
        return list(self._skills.keys())

    # ============================================================
    # 状态接口
    # ============================================================

    def is_available(self) -> bool:
        """检查引擎是否可用"""
        if self._available is not None:
            return self._available

        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=3)
            self._available = response.status_code == 200

            if self._available:
                # 检查模型是否存在
                models = response.json().get("models", [])
                model_names = [m.get("name") for m in models]
                if self.model not in model_names:
                    print(f"[LLAMAEngine] 警告: 模型 {self.model} 未安装，可用模型: {model_names}")

            return self._available
        except Exception as e:
            print(f"[LLAMAEngine] Ollama 连接失败: {e}")
            self._available = False
            return False

    def get_status_info(self) -> Dict:
        """获取状态信息（兼容标准模式）"""
        return {
            "name": "llama",
            "display_name": "LLAMA 本地引擎",
            "model": self.model,
            "available": self.is_available(),
            "status": "online" if self.is_available() else "offline",
            "skills": self.list_skills()
        }

    def get_models(self) -> List[Dict]:
        """获取可用模型列表"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=3)
            if response.status_code == 200:
                models = response.json().get("models", [])
                return [{"id": m["name"], "name": m["name"]} for m in models]
        except Exception:
            pass
        return []


# ============================================================
# 测试
# ============================================================

if __name__ == '__main__':
    engine = LLAMAEngine()

    print(f"\n引擎状态: {engine.is_available()}")
    print(f"可用模型: {engine.get_models()}")

    if engine.is_available():
        print("\n测试简单对话...")
        result = engine.chat("你好，请自我介绍")
        print(f"回复: {result['reply']}")
        print(f"调用次数: {result['turns']}")
        print(f"耗时: {result['elapsed_ms']}ms")