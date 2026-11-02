# -*- coding: utf-8 -*-
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.ollama_engine import OllamaEngine
from core.agent_engine import EngineConfig

engine = OllamaEngine(EngineConfig(model="qwen3.5:4b", max_tokens=512, temperature=0.3))

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

# 直接复现 generate_with_tools 的逻辑并打印每一步
import requests
messages = [
    {"role": "system", "content": "你是一个 helpful 助手。如果需要使用工具，请调用工具并等待结果。"},
    {"role": "user", "content": "北京今天天气怎么样？"}
]
payload = {
    "model": "qwen3.5:4b",
    "messages": messages,
    "stream": True,
    "tools": tools,
    "options": {"temperature": 0.3, "num_predict": 512}
}

print("Payload:", json.dumps(payload, ensure_ascii=False, indent=2))
resp = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=120, stream=True)
print(f"Status: {resp.status_code}")

full_content = ""
tool_calls = []
in_tool_call = False
chunk_count = 0
for line in resp.iter_lines(decode_unicode=True):
    chunk_count += 1
    if not line:
        continue
    try:
        chunk = json.loads(line)
    except Exception as e:
        print(f"  chunk {chunk_count} JSON parse error: {e}")
        continue
    msg = chunk.get("message", {})
    content = msg.get("content", "")
    if content:
        full_content += content
    if msg.get("tool_calls"):
        print(f"  chunk {chunk_count} HAS tool_calls: {msg.get('tool_calls')}")
        tool_calls = msg.get("tool_calls")
        in_tool_call = True
    if chunk_count <= 5 or chunk.get("done"):
        print(f"  chunk {chunk_count} done={chunk.get('done')} msg_keys={list(msg.keys())}")

print(f"\nTotal chunks: {chunk_count}")
print(f"in_tool_call: {in_tool_call}")
print(f"tool_calls: {tool_calls}")
print(f"full_content: {repr(full_content)}")
