# -*- coding: utf-8 -*-
"""364章 T4.5: MCP Server — Model Context Protocol本地服务器"""

import json
import os
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional


class MCPServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0,
                 name: str = "lemon-mcp", version: str = "1.0.0"):
        self.host = host
        self.port = port
        self.name = name
        self.version = version
        self._tools: Dict[str, Dict] = {}
        self._tool_handlers: Dict[str, Callable] = {}
        self._server_socket = None
        self._running = False
        self._thread = None

    def register_tool(self, name: str, description: str, parameters: Dict,
                      handler: Callable):
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": parameters,
        }
        self._tool_handlers[name] = handler

    def start(self) -> int:
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self.port = self._server_socket.getsockname()[1]
        self._server_socket.listen(5)
        self._server_socket.settimeout(1.0)
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self.port

    def stop(self):
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3)

    def list_tools(self) -> List[Dict]:
        return list(self._tools.values())

    def call_tool(self, name: str, arguments: Dict) -> Dict:
        handler = self._tool_handlers.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        try:
            result = handler(**arguments)
            # T366.7: SkillResult对象转可序列化dict
            if hasattr(result, 'success'):
                return {
                    "success": result.success,
                    "output": getattr(result, 'output', ''),
                    "error": getattr(result, 'error', ''),
                }
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
                threading.Thread(target=self._handle_conn,
                                 args=(conn,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_conn(self, conn: socket.socket):
        try:
            data = b""
            while self._running:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            if not data:
                conn.close()
                return

            request = json.loads(data.decode("utf-8").strip())
            method = request.get("method", "")
            params = request.get("params", {})
            req_id = request.get("id")

            if method == "tools/list":
                response = {"jsonrpc": "2.0", "id": req_id,
                            "result": {"tools": self.list_tools()}}
            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                result = self.call_tool(tool_name, arguments)
                response = {"jsonrpc": "2.0", "id": req_id, "result": result}
            elif method == "initialize":
                response = {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": self.name, "version": self.version},
                    },
                }
            else:
                response = {"jsonrpc": "2.0", "id": req_id,
                            "error": {"code": -32601, "message": f"Method not found: {method}"}}

            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except Exception:
            pass
        finally:
            conn.close()


def main():
    """T365.14: MCP Server CLI入口 --list/--serve"""
    import sys
    import importlib

    # T366.7: serve模式下尽早重定向stdout→stderr，防止skill注册print污染JSON-RPC
    _is_serve = len(sys.argv) > 1 and sys.argv[1] == "--serve"
    _real_stdout = sys.stdout
    if _is_serve:
        sys.stdout = sys.stderr
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    if len(sys.argv) < 2 or sys.argv[1] == "--help":
        sys.stdout = _real_stdout
        print("Usage: python -m core.mcp_server [--list|--serve]")
        print("  --list   List registered tools from SkillsRegistry")
        print("  --serve  Start MCP server on stdio (JSON-RPC over stdin/stdout)")
        sys.exit(0)

    server = MCPServer()

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from skills_registry import SkillsRegistry, _register_builtin_skills
        registry = SkillsRegistry()
        _register_builtin_skills(registry)

        for name, skill in registry._skills.items():
            server.register_tool(name, skill.description, skill.parameters,
                                 skill.handler)
    except Exception as e:
        print(f"Warning: could not load skills: {e}", file=sys.stderr)

    if sys.argv[1] == "--list":
        sys.stdout = _real_stdout
        tools = server.list_tools()
        for t in tools:
            print(f"  {t['name']}: {t['description'][:60]}")
        print(f"\n共 {len(tools)} 个工具")
        sys.exit(0)

    if _is_serve:
        import json as _json
        # 恢复 stdout 为真实 stdout（供JSON-RPC输出），确保UTF-8
        sys.stdout = _real_stdout
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stdin.reconfigure(encoding='utf-8')
        except Exception:
            pass
        print(f"MCP Server running on stdio (pid={os.getpid()})", file=sys.stderr)
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = _json.loads(line)
            except _json.JSONDecodeError:
                continue

            method = request.get("method", "")
            params = request.get("params", {})
            req_id = request.get("id")

            if method == "tools/list":
                response = {"jsonrpc": "2.0", "id": req_id,
                            "result": {"tools": server.list_tools()}}
            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                result = server.call_tool(tool_name, arguments)
                response = {"jsonrpc": "2.0", "id": req_id, "result": result}
            elif method == "initialize":
                response = {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": server.name, "version": server.version},
                    },
                }
            else:
                response = {"jsonrpc": "2.0", "id": req_id,
                            "error": {"code": -32601, "message": f"Method not found: {method}"}}

            sys.stdout.write(_json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
