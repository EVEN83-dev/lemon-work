# -*- coding: utf-8 -*-
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.ollama_engine import OllamaEngine
from core.agent_engine import EngineConfig

engine = OllamaEngine(EngineConfig(
    model="qwen3.5:4b",
    max_tokens=512,
    temperature=0.3,
    system_prompt="你是一个 helpful 助手。如果需要使用工具，请调用工具并等待结果。"
))

tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "获取指定城市的当前天气",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名称"}},
            "required": ["city"]
        }
    }
}]

result = engine.generate_with_tools("北京今天天气怎么样？", tools)
print("=" * 60)
print("RAW RESULT:")
print(repr(result))
print("=" * 60)
print("PARSED JSON ATTEMPT:")
try:
    print(json.dumps(json.loads(result), indent=2, ensure_ascii=False))
except Exception as e:
    print(f"Not JSON: {e}")
