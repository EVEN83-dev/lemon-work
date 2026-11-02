# -*- coding: utf-8 -*-
"""
381B-2: 两阶段工具路由 — 治"选错工具"
======================================
问题：4B 小模型一次从完整 schema（含多参数）中选工具+填参，经常选错/漏参。
解法：
  Stage-1（选名）：模型只从 ≤8 个工具名+一句话描述中选择工具名，强约束 format。
  Stage-2（填参）：确认工具名后，才带完整 schema 让模型生成参数。
接口：
  route_tool_2stage(engine_obj, messages, tools, **kwargs) -> Dict
    返回与 generate_with_tools 一致的 {content, tool_calls} 格式。
"""

import json
import logging
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("tool_router_2stage")

_STAGE1_SYSTEM_TEMPLATE = (
    "你是工具选择器。从以下工具中选一个最合适的，只输出工具名。\n"
    "可用工具:\n{tool_list}\n"
    "铁律：只输出一个工具名，不要输出其他任何内容。"
)

_STAGE2_SYSTEM_TEMPLATE = (
    "你是参数填写器。用户已选定工具 '{tool_name}'，请根据用户需求填写参数。\n"
    "工具 schema:\n{schema}\n"
    "铁律：只输出 JSON 参数对象，不要输出其他内容。"
)


def _build_stage1_tool_list(tools: List[Dict]) -> str:
    lines = []
    for t in tools:
        fn = t.get("function", {})
        name = fn.get("name", "")
        desc = fn.get("description", "").split("\n")[0][:60]
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


def _extract_tool_name(raw: str, tool_names: List[str]) -> Optional[str]:
    text = raw.strip().strip("`").strip('"').strip("'")
    for name in tool_names:
        if name.lower() == text.lower():
            return name
    for name in tool_names:
        if name.lower() in text.lower():
            return name
    return None


def _extract_json_args(raw: str) -> Dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if len(lines) > 2 else lines[1:])
    text = text.strip().strip("`")
    try:
        return json.loads(text)
    except Exception:
        pass
    import re
    m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {}


def _find_tool_by_name(tools: List[Dict], name: str) -> Optional[Dict]:
    for t in tools:
        fn = t.get("function", {})
        if fn.get("name", "") == name:
            return t
    return None


def route_tool_2stage(engine_obj, messages: List[Dict], tools: List[Dict],
                       **kwargs) -> Dict[str, Any]:
    """两阶段工具路由主入口。

    Args:
        engine_obj: 引擎适配器（需有 generate_with_tools 或 chat 方法）
        messages: 对话消息列表
        tools: 完整工具定义列表（OpenAI function 格式）
        **kwargs: 透传参数（model 等）

    Returns:
        {"content": str, "tool_calls": [Dict]} — 与 generate_with_tools 返回格式一致
    """
    if not tools:
        return {"content": "", "tool_calls": []}

    tool_names = [t.get("function", {}).get("name", "") for t in tools if t.get("function", {}).get("name")]

    user_content = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_content = msg.get("content", "")
            break

    # ── Stage 1: 选工具名 ──
    _logger.info(f"[381B-2] Stage-1: 从 {len(tool_names)} 工具中选名")
    stage1_system = _STAGE1_SYSTEM_TEMPLATE.format(tool_list=_build_stage1_tool_list(tools))
    stage1_messages = [
        {"role": "system", "content": stage1_system},
        {"role": "user", "content": user_content[:500]},
    ]

    stage1_result = _call_engine_simple(engine_obj, stage1_messages, **kwargs)
    stage1_content = stage1_result.get("content", "")
    if not stage1_content and stage1_result.get("tool_calls"):
        tc0 = stage1_result["tool_calls"][0]
        stage1_content = tc0.get("function", {}).get("name", "")

    selected_name = _extract_tool_name(stage1_content, tool_names)
    _logger.info(f"[381B-2] Stage-1 raw='{stage1_content[:80]}', selected='{selected_name}'")

    if not selected_name:
        _logger.warning("[381B-2] Stage-1 未选中工具名，回退一步到位")
        return _fallback_one_shot(engine_obj, messages, tools, **kwargs)

    # ── Stage 2: 填参数 ──
    selected_tool = _find_tool_by_name(tools, selected_name)
    if not selected_tool:
        _logger.warning(f"[381B-2] 选中工具 '{selected_name}' 不在列表中，回退")
        return _fallback_one_shot(engine_obj, messages, tools, **kwargs)

    _logger.info(f"[381B-2] Stage-2: 为 '{selected_name}' 生成参数")
    schema_str = json.dumps(selected_tool.get("function", {}), ensure_ascii=False, indent=2)
    stage2_system = _STAGE2_SYSTEM_TEMPLATE.format(tool_name=selected_name, schema=schema_str)
    stage2_messages = [
        {"role": "system", "content": stage2_system},
        {"role": "user", "content": user_content[:500]},
    ]

    stage2_result = _call_engine_simple(engine_obj, stage2_messages, **kwargs)
    stage2_content = stage2_result.get("content", "")

    args = _extract_json_args(stage2_content)
    _logger.info(f"[381B-2] Stage-2 raw='{stage2_content[:80]}', args={json.dumps(args, ensure_ascii=False)[:200]}")

    tool_call = {
        "id": f"tc_2stage_{selected_name}",
        "type": "function",
        "function": {
            "name": selected_name,
            "arguments": args if isinstance(args, dict) else {},
        }
    }

    return {
        "content": "",
        "tool_calls": [tool_call],
    }


def _call_engine_simple(engine_obj, messages: List[Dict], **kwargs) -> Dict[str, Any]:
    """简单调用引擎（不带工具 schema，仅纯对话）。"""
    try:
        if hasattr(engine_obj, "generate_with_tools"):
            try:
                result = engine_obj.generate_with_tools(messages, [], **kwargs)
                if isinstance(result, dict):
                    return result
                if isinstance(result, str):
                    return {"content": result, "tool_calls": []}
            except TypeError:
                pass

        if hasattr(engine_obj, "chat"):
            try:
                result = engine_obj.chat(
                    messages[-1].get("content", "") if messages else "",
                    context=messages,
                )
                if isinstance(result, str):
                    return {"content": result, "tool_calls": []}
                if isinstance(result, dict):
                    return result
            except Exception:
                pass

        if hasattr(engine_obj, "generate"):
            try:
                prompt = messages[-1].get("content", "") if messages else ""
                result = engine_obj.generate(prompt)
                return {"content": str(result), "tool_calls": []}
            except Exception:
                pass

    except Exception as e:
        _logger.warning(f"[381B-2] 引擎调用异常: {e}")

    return {"content": "", "tool_calls": []}


def _fallback_one_shot(engine_obj, messages: List[Dict], tools: List[Dict],
                        **kwargs) -> Dict[str, Any]:
    """回退：一步到位（原有 generate_with_tools 路径）。"""
    try:
        if hasattr(engine_obj, "generate_with_tools"):
            result = engine_obj.generate_with_tools(messages, tools, **kwargs)
            if isinstance(result, dict):
                return result
            if isinstance(result, str):
                return {"content": result, "tool_calls": []}
    except Exception as e:
        _logger.warning(f"[381B-2] 回退一步调用异常: {e}")
    return {"content": "", "tool_calls": []}
