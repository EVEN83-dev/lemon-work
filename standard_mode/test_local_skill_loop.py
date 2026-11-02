# -*- coding: utf-8 -*-
"""
本地模型 Skill 循环调用测试
用途：验证 Ollama 本地模型是否能稳定调用 Lemon Code 风格的 Skill（function calling）
"""
import sys
import os
import json
import time
import traceback

# 确保能导入 standard_mode 下的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.ollama_engine import OllamaEngine
from core.agent_engine import EngineConfig

# 测试用的 mock skill（模拟 Lemon Code skill 的 OpenAI function 格式）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的当前天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，例如 Beijing、Shanghai"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "获取当前时间",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


def execute_tool(call):
    """模拟执行一个 tool_call"""
    name = call.get("function", {}).get("name") or call.get("name")
    args_str = call.get("function", {}).get("arguments") or call.get("arguments", "{}")
    try:
        args = json.loads(args_str) if isinstance(args_str, str) else args_str
    except Exception:
        args = {}

    if name == "get_weather":
        city = args.get("city", "Unknown")
        return {"city": city, "temperature": 25, "condition": "sunny", "wind": "3级"}
    elif name == "get_time":
        return {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "timezone": "Asia/Shanghai"}
    return {"error": f"unknown tool {name}"}


def parse_tool_calls(result_text):
    """从 generate_with_tools 返回结果中提取 tool_calls"""
    try:
        data = json.loads(result_text)
        if isinstance(data, dict) and "tool_calls" in data:
            return data["tool_calls"]
    except Exception:
        pass
    return []


def run_single_turn(model, messages, max_tokens=512):
    """调用一次模型，返回模型输出文本和 tool_calls"""
    engine = OllamaEngine(EngineConfig(model=model, max_tokens=max_tokens, temperature=0.3))
    # 构造 prompt：取最后一条 user 消息
    prompt = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            prompt = m.get("content", "")
            break
    context = [m for m in messages if m.get("role") != "user" or m.get("content") != prompt]
    result = engine.generate_with_tools(prompt, TOOLS, context=context)
    tool_calls = parse_tool_calls(result)
    return result, tool_calls


def test_model(model, prompt, max_loop=5):
    """测试单个模型的多轮 tool calling 能力"""
    print(f"\n{'='*60}")
    print(f"[测试模型] {model}")
    print(f"[测试问题] {prompt}")
    print('='*60)

    messages = [{"role": "system", "content": "你是一个 helpful 助手。如果需要使用工具，请调用工具并等待结果。"}]
    messages.append({"role": "user", "content": prompt})

    loop_count = 0
    total_tool_calls = 0
    final_answer = ""
    start_time = time.time()

    while loop_count < max_loop:
        loop_count += 1
        try:
            result, tool_calls = run_single_turn(model, messages)
        except Exception as e:
            print(f"  [错误] 模型调用异常: {e}")
            traceback.print_exc()
            return {"model": model, "success": False, "error": str(e), "loops": loop_count}

        if tool_calls:
            total_tool_calls += len(tool_calls)
            print(f"  [轮次 {loop_count}] 触发 {len(tool_calls)} 个 tool_call")
            for tc in tool_calls:
                tool_result = execute_tool(tc)
                print(f"    -> {tc.get('function', {}).get('name')}: {tool_result}")
                messages.append({
                    "role": "tool",
                    "name": tc.get("function", {}).get("name"),
                    "content": json.dumps(tool_result, ensure_ascii=False)
                })
            continue
        else:
            final_answer = result
            print(f"  [轮次 {loop_count}] 最终回复: {result[:200]}")
            break
    else:
        print(f"  [警告] 达到最大轮次 {max_loop}，模型仍未给出最终回复")

    elapsed = time.time() - start_time
    success = total_tool_calls > 0 and final_answer != ""
    print(f"  [结果] 成功={success}, 轮次={loop_count}, Tool调用={total_tool_calls}, 耗时={elapsed:.1f}s")
    return {
        "model": model,
        "success": success,
        "loops": loop_count,
        "tool_calls": total_tool_calls,
        "elapsed": elapsed,
        "final_answer": final_answer
    }


def main():
    # 优先测试 tool-calling 能力较强的模型
    models = [
        "qwen3.5:4b",
        "qwen3.5:9b",
        "aleshribar3/deepseek-r1-tool-calling:8b",
        "qwen2.5:7b",
        "qwen2.5-coder:3b",
        "qwen2.5:1.5b",
    ]

    # 只测试本地已安装的模型
    engine = OllamaEngine(EngineConfig())
    available = {m["name"] for m in engine.get_models()}
    models = [m for m in models if m in available]
    print(f"[本地可用模型] {models}")

    if not models:
        print("[错误] 没有可用的本地模型，请先运行: ollama pull qwen3.5:4b")
        return

    # 单步 tool calling 测试
    results_single = []
    for model in models:
        try:
            r = test_model(model, "北京今天天气怎么样？")
            results_single.append(r)
        except Exception as e:
            print(f"[错误] {model} 单步测试失败: {e}")
            results_single.append({"model": model, "success": False, "error": str(e)})

    # 多步 loop 测试
    print("\n" + "#" * 70)
    print("# 多步 Skill Loop 测试：查询北京和上海天气，然后总结")
    print("#" * 70)
    results_loop = []
    for model in models:
        try:
            r = test_model(model, "请查询北京和上海的天气，并给我一句总结。", max_loop=6)
            results_loop.append(r)
        except Exception as e:
            print(f"[错误] {model} 多步测试失败: {e}")
            results_loop.append({"model": model, "success": False, "error": str(e)})

    # 汇总报告
    print("\n" + "=" * 70)
    print("[测试汇总]")
    print("=" * 70)
    print("\n单步 Tool Calling:")
    for r in results_single:
        status = "PASS" if r.get("success") else "FAIL"
        print(f"  {status} {r['model']:45s} tool_calls={r.get('tool_calls', 0)} loops={r.get('loops', 0)}")

    print("\n多步 Skill Loop:")
    for r in results_loop:
        status = "PASS" if r.get("success") else "FAIL"
        print(f"  {status} {r['model']:45s} tool_calls={r.get('tool_calls', 0)} loops={r.get('loops', 0)}")

    # 推荐用于 Lemon Code 的模型
    best = [r["model"] for r in results_loop if r.get("success")]
    print(f"\n[推荐可用于循环 Skill 调用的本地模型]: {best if best else '无，请使用 DeepSeek API 或安装 qwen3.5:4b+'}")


if __name__ == "__main__":
    main()
