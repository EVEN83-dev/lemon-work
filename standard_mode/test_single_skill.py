# -*- coding: utf-8 -*-
"""
快速单模型 Skill 调用验证
==========================
用于确认 Ollama 本地模型能否正确触发 Lemon Code 风格的 tool calling。
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.ollama_engine import OllamaEngine
from core.agent_engine import EngineConfig

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的当前天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称"}
                },
                "required": ["city"]
            }
        }
    }
]


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen3.5:4b"
    print(f"[测试模型] {model}")
    engine = OllamaEngine(EngineConfig(model=model, max_tokens=512, temperature=0.3))
    result = engine.generate_with_tools("北京今天天气怎么样？", TOOLS)
    try:
        data = json.loads(result)
        if "tool_calls" in data:
            print("[结果] 成功触发 tool_call")
            for tc in data["tool_calls"]:
                print(f"  -> {tc}")
            return
    except Exception:
        pass
    print("[结果] 未触发 tool_call，模型直接回复:")
    print(f"  {result[:200]}")


if __name__ == "__main__":
    main()
