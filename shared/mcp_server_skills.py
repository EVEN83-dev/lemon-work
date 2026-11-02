# -*- coding: utf-8 -*-
"""
382B-4: MCP Server Skills — 技能生态接口（战略核心）
=====================================================
SkillsRegistry 只读暴露为本地 stdio MCP server。
工具清单动态生成（name/desc/参数schema 自动映射）。

安全边界：
  - terminal_run / execute_code / write_file / edit_file / run_command 不进 MCP 清单
  - MCP 调用打独立日志标记（审计钩子预留接口字段 _audit_tag）

一次开发全平台复用：本 server 可被 Cursor / Cline / CherryStudio 等任意
支持 MCP stdio 的客户端直接挂载——零适配成本。

用法：
    python -m shared.mcp_server_skills --serve     # stdio JSON-RPC
    python -m shared.mcp_server_skills --list       # 列出可用工具
"""

import json
import os
import sys
import time
import threading
from typing import Any, Callable, Dict, List, Optional

_BLOCKED_SKILLS = frozenset([
    "terminal_run", "execute_code", "write_file", "edit_file",
    "run_command", "delete_file", "multi_edit",
])

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_mcp_logger = None
try:
    import logging
    _mcp_logger = logging.getLogger("mcp_server_skills")
except Exception:
    pass


def _log_info(msg: str):
    if _mcp_logger:
        _mcp_logger.info(msg)


def _load_registry():
    """加载 SkillsRegistry 并注册所有内置技能。"""
    try:
        sys.path.insert(0, os.path.join(_PROJECT_ROOT, "standard_mode", "core"))
        from skills_registry import SkillsRegistry, _register_builtin_skills
        registry = SkillsRegistry()
        _register_builtin_skills(registry)
        return registry
    except Exception as e:
        if _mcp_logger:
            _mcp_logger.warning(f"MCP: 加载注册表失败: {e}")
        return None


def build_safe_tool_list(registry) -> List[Dict]:
    """从 SkillsRegistry 构建安全工具清单（排除危险技能）。

    Returns:
        List[Dict] — MCP tools/list 格式
    """
    tools = []
    if not registry:
        return tools
    try:
        for skill in registry.list_skills():
            name = skill.name
            if name in _BLOCKED_SKILLS:
                continue
            tools.append({
                "name": name,
                "description": skill.description[:200],
                "inputSchema": skill.parameters if isinstance(skill.parameters, dict) else {"type": "object", "properties": {}},
            })
    except Exception as e:
        if _mcp_logger:
            _mcp_logger.warning(f"MCP: 构建工具清单失败: {e}")
    return tools


def handle_tool_call(registry, tool_name: str, arguments: Dict) -> Dict:
    """执行 MCP 工具调用（只读安全边界 + 审计预留）。

    Returns:
        Dict — MCP tools/call 结果
    """
    if tool_name in _BLOCKED_SKILLS:
        return {
            "content": [{"type": "text", "text": f"技能 '{tool_name}' 在 MCP 接口中已禁用（安全边界）"}],
            "isError": True,
            "_audit_tag": "mcp_blocked",
        }
    try:
        result = registry.execute(tool_name, arguments)
        if hasattr(result, 'success'):
            text = result.output if result.success else f"错误: {result.error}"
            return {
                "content": [{"type": "text", "text": text}],
                "isError": not result.success,
                "_audit_tag": "mcp_call",
                "_tool": tool_name,
                "_ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        return {
            "content": [{"type": "text", "text": str(result)}],
            "isError": False,
            "_audit_tag": "mcp_call",
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"执行异常: {e}"}],
            "isError": True,
            "_audit_tag": "mcp_error",
        }


def run_stdio_server():
    """MCP stdio server 主循环（JSON-RPC over stdin/stdout）。"""
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    registry = _load_registry()
    if not registry:
        print("MCP: 无法加载技能注册表，退出", file=sys.stderr)
        sys.exit(1)

    tool_list = build_safe_tool_list(registry)
    print(f"MCP Server (skills) running on stdio, {len(tool_list)} safe tools (pid={os.getpid()})", file=sys.stderr)

    sys.stdout = _real_stdout
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdin.reconfigure(encoding='utf-8')
    except Exception:
        pass

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        if method == "initialize":
            response = {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "lemon-skills-mcp", "version": "1.0.0"},
                },
            }
        elif method == "tools/list":
            tool_list = build_safe_tool_list(registry)
            response = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tool_list}}
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = handle_tool_call(registry, tool_name, arguments)
            response = {"jsonrpc": "2.0", "id": req_id, "result": result}
        elif method == "notifications/initialized":
            continue
        else:
            response = {"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32601, "message": f"Method not found: {method}"}}

        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "--help":
        print("Usage: python -m shared.mcp_server_skills [--list|--serve]")
        print("  --list   List safe MCP tools from SkillsRegistry")
        print("  --serve  Start MCP stdio server (JSON-RPC)")
        sys.exit(0)

    if sys.argv[1] == "--list":
        registry = _load_registry()
        if registry:
            tools = build_safe_tool_list(registry)
            for t in tools:
                print(f"  {t['name']}: {t['description'][:60]}")
            print(f"\n共 {len(tools)} 个安全工具 (已排除: {', '.join(sorted(_BLOCKED_SKILLS))})")
        sys.exit(0)

    if sys.argv[1] == "--serve":
        run_stdio_server()
        sys.exit(0)


if __name__ == "__main__":
    main()
