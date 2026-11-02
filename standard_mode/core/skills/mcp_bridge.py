# -*- coding: utf-8 -*-
"""
Skill: mcp_bridge — MCP 工具桥接（L3 新增）
===========================================
将 MCP Client 管理的所有外部工具暴露为 Skill，供 Agent 自主调用。

提供 3 个核心操作：
  mcp_list_tools     — 列出所有 MCP 服务器提供的工具
  mcp_call_tool      — 调用指定 MCP 工具（自动路由到对应服务器）
  mcp_health         — MCP 服务器健康状态

优雅降级：
  - MCP 客户端未初始化时自动启动（注册内置 filesystem/git/fetch/memory 服务器）
  - MCP 服务器启动失败不阻塞整体流程
  - 返回结构化 SkillResult 而非异常

内置服务器（通过 MCPClient.register_builtin_servers）：
  - filesystem: 文件系统操作（读/写/列表）
  - git: Git 仓库操作
  - fetch: HTTP 请求
  - memory: 知识图谱存储
"""

import os
import threading
from typing import Dict, Any, List

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "mcp_bridge",
    "description": "MCP 工具桥接：列出/调用 MCP 外部工具服务器（filesystem/git/fetch/memory）",
    "category": "system",
    "version": "1.0.0",
}


# ==================== MCP Client 单例 ====================

_mcp_client = None
_mcp_lock = threading.Lock()


def _get_mcp_client():
    """获取 MCPClient 单例（惰性初始化 + 自动注册内置服务器）"""
    global _mcp_client
    with _mcp_lock:
        if _mcp_client is not None:
            return _mcp_client
        try:
            from mcp_client import get_mcp_client, register_builtin_servers
            _mcp_client = get_mcp_client()
            # 注册内置服务器配置（不立即启动，首次调用时 auto_start）
            register_builtin_servers(_mcp_client)
            # 启动所有 auto_start 服务器
            _mcp_client.start_all()
        except Exception:
            _mcp_client = None
        return _mcp_client


# ==================== 操作实现 ====================

def _op_list_tools(server_name: str = "") -> SkillResult:
    """列出所有 MCP 工具"""
    client = _get_mcp_client()
    if client is None:
        return SkillResult(success=False, error="MCP 客户端未初始化")

    try:
        tools = client.list_tools(server_name or None)
        if not tools:
            return SkillResult(success=True, output="无可用 MCP 工具", data={"tools": []})

        lines = []
        for t in tools[:30]:
            name = getattr(t, 'name', '') or t.get('name', '') if isinstance(t, dict) else str(t)
            desc = (getattr(t, 'description', '') or t.get('description', '') if isinstance(t, dict) else '')[:60]
            server = (getattr(t, 'server_name', '') or t.get('server_name', '') if isinstance(t, dict) else '')
            lines.append(f"  [{server}] {name}: {desc}")

        return SkillResult(
            success=True,
            output=f"共 {len(tools)} 个 MCP 工具:\n" + "\n".join(lines),
            data={"tools": [_tool_to_dict(t) for t in tools]},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"列出 MCP 工具失败: {e}")


def _op_call_tool(tool_name: str, arguments: str = "{}") -> SkillResult:
    """调用 MCP 工具（自动路由到对应服务器）"""
    if not tool_name:
        return SkillResult(success=False, error="缺少 tool_name 参数")
    client = _get_mcp_client()
    if client is None:
        return SkillResult(success=False, error="MCP 客户端未初始化")

    # 解析参数 JSON
    try:
        import json
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
    except Exception:
        return SkillResult(success=False, error=f"arguments 参数不是合法 JSON: {arguments}")

    try:
        # call_tool_auto 自动根据工具名路由到正确服务器
        result = client.call_tool_auto(tool_name, args)
        # result 可能是 MCPResponse 或字符串
        if hasattr(result, 'success') and not result.success:
            return SkillResult(success=False, error=result.error or "MCP 工具执行失败")
        output = str(result) if not hasattr(result, 'result') else str(result.result)
        return SkillResult(
            success=True,
            output=f"MCP 工具 '{tool_name}' 执行成功:\n{output[:500]}",
            data={"tool": tool_name, "result": output[:2000]},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"MCP 工具调用失败: {e}")


def _op_health() -> SkillResult:
    """MCP 服务器健康检查"""
    client = _get_mcp_client()
    if client is None:
        return SkillResult(success=False, error="MCP 客户端未初始化")

    try:
        servers = client.list_servers()
        alive = sum(1 for s in servers if getattr(s, 'alive', True))
        total = len(servers)
        status_lines = [f"  [{s.get('name', '?')}]: {'在线' if s.get('alive', True) else '离线'}"
                        for s in servers]
        return SkillResult(
            success=True,
            output=f"MCP 状态: {alive}/{total} 服务器在线\n" + "\n".join(status_lines),
            data={"servers": servers},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"MCP 健康检查失败: {e}")


def _tool_to_dict(tool) -> Dict:
    """将 MCPTool 或 dict 转为字典"""
    if isinstance(tool, dict):
        return tool
    return {
        "name": getattr(tool, 'name', ''),
        "description": getattr(tool, 'description', ''),
        "server_name": getattr(tool, 'server_name', ''),
        "input_schema": getattr(tool, 'input_schema', {}),
    }


# ==================== 统一入口 ====================

def execute(
    action: str = "mcp_list_tools",
    tool_name: str = "",
    server_name: str = "",
    arguments: str = "{}",
) -> SkillResult:
    """MCP 工具桥接统一入口"""
    action = (action or "").lower().strip()

    if action == "mcp_list_tools":
        return _op_list_tools(server_name)
    if action == "mcp_call_tool":
        return _op_call_tool(tool_name, arguments)
    if action == "mcp_health":
        return _op_health()

    supported = ["mcp_list_tools", "mcp_call_tool", "mcp_health"]
    return SkillResult(
        success=False,
        error=f"未知 action: {action}（支持: {', '.join(supported)}）",
    )


def register(registry) -> None:
    """向 SkillsRegistry 注册 mcp_bridge Skill"""
    registry.register(SkillDef(
        name="mcp_bridge",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "MCP 操作类型",
                    "enum": ["mcp_list_tools", "mcp_call_tool", "mcp_health"],
                },
                "tool_name": {
                    "type": "string",
                    "description": "mcp_call_tool 时要调用的工具名",
                },
                "server_name": {
                    "type": "string",
                    "description": "mcp_list_tools 时可选指定服务器名",
                },
                "arguments": {
                    "type": "string",
                    "description": "mcp_call_tool 时传入的参数 JSON 字符串",
                    "default": "{}",
                },
            },
            "required": ["action"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=True,  # MCP 工具可能导致副作用，需确认
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA


def is_available() -> bool:
    return _get_mcp_client() is not None
