# -*- coding: utf-8 -*-
import requests, json

payload = {
    "model": "qwen3.5:4b",
    "messages": [
        {"role": "system", "content": "你是一个 helpful 助手。如果需要使用工具，请调用工具并等待结果。"},
        {"role": "user", "content": "北京今天天气怎么样？"}
    ],
    "stream": True,
    "tools": [{
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
    }],
    "options": {"temperature": 0.3, "num_predict": 512}
}

print("Sending streaming request to Ollama /api/chat ...")
resp = requests.post("http://127.0.0.1:11434/api/chat", json=payload, stream=True, timeout=120)
print(f"Status: {resp.status_code}")
for i, line in enumerate(resp.iter_lines(decode_unicode=True)):
    if not line:
        continue
    try:
        chunk = json.loads(line)
        print(f"chunk {i}: {json.dumps(chunk, ensure_ascii=False)[:500]}")
    except Exception as e:
        print(f"chunk {i} (raw): {line[:200]}  error: {e}")
