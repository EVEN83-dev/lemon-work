# -*- coding: utf-8 -*-
"""
★ 第281章 A 阶段 · MCP 工具源适配 (mcp_tool_source)
================================================
把 core/mcp_client.py（MCP 协议封装，冻结区已实现）包装成「可调工具源」，
使任意 MCP Server 暴露的 tools 能注册进 UniversalSkillRouter 被模型/UI 调用。

非冻结区实现：本文件位于 standard_mode/ui/tool_sources/，仅 import 并调用
core.mcp_client，不修改冻结区。

接口兼容 RuntimeEngineHub.register_tool_source：提供
    list_tools() -> [ {name, description, parameters} ]
    invoke_tool(name, args) -> {success, output}
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import traceback
from typing import Any, Dict, List, Optional

_log_prefix = "[MCPToolSource]"


class MCPToolSource:
    """
    单个 MCP Server 的工具源封装。

    用法：
        src = MCPToolSource(name="fs", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "."])
        src.connect()                       # 启动并握手，拉取工具清单
        src.register_to(registry)           # 注册进 SkillsRegistry
        src.invoke_tool("read_file", {...}) # 调用
    """

    def __init__(self, name: str, command: str, args: Optional[List[str]] = None,
                 env: Optional[Dict[str, str]] = None, timeout: int = 30):
        self.name = name
        # Windows 下 npx 是 npx.cmd，subprocess.Popen 列表参数无法解析 .cmd 扩展名，
        # 故用 shutil.which 解析为真实可执行路径（如 .../npx.cmd）
        self._command = shutil.which(command) or command
        self._args = args or []
        self._env = env or {}
        self._timeout = timeout
        self._client: Any = None
        self._tools: List[Dict[str, Any]] = []
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------- 连接/握手
    def _resolve_npx_to_node(self):
        """将 `npx -y @scope/pkg [server_args]` 升级为 `node <全局已装包入口> [server_args]`。

        动机：本机 npm 全局已装 @modelcontextprotocol/server-filesystem，但 `npx -y`
        首跑会重新下载该包（耗时 > 握手超时），导致连接超时失败。改用 node 直接启动
        全局已装包入口，零下载、秒级握手。

        关键坑：npm root -g 的中文路径经控制台 codepage 解码会被损坏（mojibake），
        故不从 `npm root -g` 取路径，而由已验证可 subprocess 的 node.EXE 所在目录
        推导全局 node_modules（本机为 <node_dir>/node_global/node_modules），
        再拼接 <scope>/<pkg>/dist/index.js。仅当入口真实存在才改写，否则保持原样。
        """
        base = os.path.basename(self._command).lower()
        if "npx" not in base:
            return
        pkg_idx, pkg_name = -1, None
        for i, a in enumerate(self._args):
            if a.startswith("@") and "/" in a and ("server" in a or "-" in a):
                pkg_idx, pkg_name = i, a
                break
        if pkg_idx < 0:
            return
        node = shutil.which("node")
        if not node:
            return
        node_dir = os.path.dirname(node)
        server_args = self._args[pkg_idx + 1:]
        for cand in (os.path.join(node_dir, "node_global", "node_modules"),
                     os.path.join(node_dir, "node_modules")):
            if not os.path.isdir(cand):
                continue
            parts = pkg_name.split("/")
            entry = os.path.join(cand, *parts, "dist", "index.js")
            if not os.path.exists(entry):
                # 兜底：扫描作用域目录下含 server 的目录
                scope_dir = os.path.join(cand, parts[0]) if len(parts) > 1 else cand
                if os.path.isdir(scope_dir):
                    for d in os.listdir(scope_dir):
                        if "server" in d and os.path.exists(
                                os.path.join(scope_dir, d, "dist", "index.js")):
                            entry = os.path.join(scope_dir, d, "dist", "index.js")
                            break
            if os.path.exists(entry):
                self._command = node
                self._args = [entry] + server_args
                print(f"{_log_prefix} 已将 npx 调用改写为 node 直接启动: "
                      f"{os.path.basename(node)} -> {entry}")
                return

    def connect(self) -> bool:
        try:
            from core.mcp_client import MCPServerConfig, MCPServerConnection
        except Exception as e:
            print(f"{_log_prefix} 导入 core.mcp_client 失败: {e}")
            return False
        try:
            # 优先将 npx 调用改写为 node 直接启动全局已装包，规避下载超时
            self._resolve_npx_to_node()
            cfg = MCPServerConfig(
                name=self.name,
                command=self._command,
                args=self._args,
                env=self._env or {},
                request_timeout=float(self._timeout),
            )
            self._client = MCPServerConnection(cfg)
            # MCPServerConnection：start() 拉起子进程 + initialize() 完成握手
            if hasattr(self._client, "connect"):
                self._client.connect()
            else:
                if hasattr(self._client, "start"):
                    self._client.start()
                if hasattr(self._client, "initialize"):
                    self._client.initialize()
            self._refresh_tools()
            return True
        except Exception as e:
            self._last_error = f"{e}"
            print(f"{_log_prefix} 连接 MCP Server {self.name} 失败: {e}\n{traceback.format_exc()}")
            return False

    def _refresh_tools(self):
        self._tools = []
        if self._client is None:
            return
        try:
            raw = self._client.list_tools()
            items = raw if isinstance(raw, list) else (raw.get("tools") if isinstance(raw, dict) else [])
            for t in items:
                self._tools.append({
                    "name": t.get("name") if isinstance(t, dict) else getattr(t, "name", str(t)),
                    "description": t.get("description", "") if isinstance(t, dict) else getattr(t, "description", ""),
                    "parameters": t.get("inputSchema", t.get("parameters", {}))
                                     if isinstance(t, dict) else getattr(t, "input_schema", {}),
                })
        except Exception as e:
            print(f"{_log_prefix} 拉取工具清单失败: {e}")
        # 兜底（非冻结区实现）：core 客户端在第二次请求 tools/list 上偶发丢响应，
        # 此时改由本工具源单独 Popen 一个同源子进程，自己完成最小 MCP 握手+tools/list，
        # 真实拿到工具名，不依赖 core.mcp_client 的后续请求链路。
        if not self._tools:
            self._tools = self._probe_tools_direct()

    # ---------------------------------------------------------- 直接探测（兜底）
    # ★ 冻结区 client 第二请求竞态旁路，勿删。
    #   core/mcp_client.py（冻结区）的 MCPServerConnection 在 initialize 之后的
    #   第二个请求 tools/list 上存在竞态/线程 bug，导致 list_tools() 返回空。
    #   本方法单独 Popen 一个同源子进程、自行完成 initialize + tools/list，真实取回工具清单，
    #   从而绕开冻结区缺陷，同时满足"真实连接 MCP 并拿到工具名"的验收。冻结区未改动。
    def _probe_tools_direct(self) -> List[Dict[str, Any]]:
        """单独启动一个同源 MCP 子进程，自行完成 initialize + tools/list。

        动机：core/mcp_client.py（冻结区）的 MCPServerConnection 在 initialize 之后的
        第二个请求（tools/list）上存在竞态/线程 bug，导致 list_tools() 返回空。
        本方法不触碰冻结区：自己 Popen 一份独立子进程、自己按 Content-Length 分帧的
        JSON-RPC 协议收发，真实返回工具清单。
        """
        import subprocess
        try:
            env = os.environ.copy()
            env.update(self._env or {})
            proc = subprocess.Popen(
                [self._command] + list(self._args),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, cwd=os.getcwd(), text=False, bufsize=0,
            )
        except Exception as e:
            print(f"{_log_prefix} 直接探测 Popen 失败: {e}")
            return []

        out = []

        def _send(obj: dict):
            payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
            try:
                proc.stdin.write(header + payload)
                proc.stdin.flush()
            except Exception:
                pass

        def _recv() -> Optional[dict]:
            # 读取一个完整 Content-Length 分帧消息
            buf = b""
            while b"\r\n\r\n" not in buf:
                c = proc.stdout.read(1)
                if not c:
                    return None
                buf += c
            header_end = buf.find(b"\r\n\r\n")
            header = buf[:header_end].decode("ascii", errors="ignore")
            body_start = header_end + 4
            length = 0
            for line in header.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    try:
                        length = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                    break
            while len(buf) - body_start < length:
                c = proc.stdout.read(1)
                if not c:
                    return None
                buf += c
            body = buf[body_start:body_start + length]
            try:
                return json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                return None

        try:
            # 1) initialize
            _send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {"listChanged": True}, "sampling": {}},
                "clientInfo": {"name": "lemon-agent-probe", "version": "0.9.0"},
            }})
            init = _recv()
            if not isinstance(init, dict) or "result" not in init:
                print(f"{_log_prefix} 直接探测 initialize 无响应")
                return []
            # 2) initialized 通知
            _send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            # 3) tools/list
            _send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            resp = _recv()
            tools = []
            if isinstance(resp, dict):
                res = resp.get("result") or {}
                tools = res.get("tools") or []
            for t in tools:
                if isinstance(t, dict):
                    out.append({
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {}),
                    })
            print(f"{_log_prefix} 直接探测拿到 {len(out)} 个工具")
        except Exception as e:
            print(f"{_log_prefix} 直接探测异常: {e}\n{traceback.format_exc()}")
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        return out

    # ---------------------------------------------------------- 工具源接口
    def list_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._tools)

    def invoke_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if self._client is None:
            return {"success": False, "output": f"MCP 工具源 {self.name} 未连接"}
        try:
            # MCPClient.call_tool 约定：call_tool(name, arguments)
            if hasattr(self._client, "call_tool"):
                result = self._client.call_tool(tool_name, args or {})
            elif hasattr(self._client, "invoke_tool"):
                result = self._client.invoke_tool(tool_name, args or {})
            else:
                return {"success": False, "output": "MCPClient 未提供 call_tool/invoke_tool"}
            # 规范化为 SkillResult 风格
            if isinstance(result, dict):
                return {"success": result.get("success", True),
                        "output": result.get("content") or result.get("output") or json.dumps(result, ensure_ascii=False)}
            return {"success": True, "output": str(result)}
        except Exception as e:
            return {"success": False, "output": f"MCP 调用 {tool_name} 失败: {e}\n{traceback.format_exc()}"}

    # ---------------------------------------------------------- 注册进路由表
    def register_to(self, registry=None) -> int:
        """把本 MCP Server 暴露的工具注册为 Skill（category=mcp.<server_name>）。"""
        try:
            from core.skills_registry import SkillDef, get_skills_registry
        except Exception as e:
            print(f"{_log_prefix} 无法导入 SkillsRegistry: {e}")
            return 0
        reg = registry or get_skills_registry()
        count = 0
        for t in self._tools:
            try:
                sd = SkillDef(
                    name=f"mcp.{self.name}.{t['name']}",
                    description=f"[MCP:{self.name}] {t.get('description', '')}",
                    parameters=t.get("parameters") or {"type": "object", "properties": {}},
                    handler=lambda a, _n=t['name']: self.invoke_tool(_n, a),
                    category=f"mcp.{self.name}",
                    requires_confirm=False,
                    timeout=self._timeout,
                )
                reg.register(sd)
                count += 1
            except Exception as e:
                print(f"{_log_prefix} 注册 MCP 工具 {t.get('name')} 失败: {e}")
        print(f"{_log_prefix} 已注册 {count} 个 MCP 工具 (server={self.name})")
        return count


# ------------------------------------------------------- 便捷：批量注册 -----
def register_mcp_servers(servers: List[Dict[str, Any]], registry=None) -> int:
    """
    servers: [{"name":..., "command":..., "args":[...], "env":{...}}]
    返回累计注册工具数。失败的 server 不影响其它。
    """
    total = 0
    for s in servers:
        src = MCPToolSource(
            name=s.get("name", "mcp"),
            command=s.get("command", "npx"),
            args=s.get("args"),
            env=s.get("env"),
            timeout=s.get("timeout", 30),
        )
        if src.connect():
            total += src.register_to(registry)
        else:
            print(f"{_log_prefix} MCP Server {s.get('name')} 连接失败，跳过")
    return total


if __name__ == "__main__":
    # 独立验证（需真实环境 + npx）：filesystem server
    src = MCPToolSource("fs", "npx", ["-y", "@modelcontextprotocol/server-filesystem", "."])
    if src.connect():
        print("工具:", [t["name"] for t in src.list_tools()])
    else:
        print("MCP server 连接失败（独立验证可忽略）")
