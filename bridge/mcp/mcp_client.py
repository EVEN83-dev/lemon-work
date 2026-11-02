import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .mcp_types import MCPServerConfig, MCPToolSchema, MCPToolCall, MCPToolResult, MCPListToolsResult
from .mcp_transport import StdioTransport, HttpTransport


class MCPClient:
    def __init__(self, server_config: MCPServerConfig):
        self._config = server_config
        self._transport = None
        self._tools: List[MCPToolSchema] = []
        self._connected = False
        self._lock = threading.Lock()

    def connect(self) -> bool:
        if self._config.transport == "stdio":
            self._transport = StdioTransport(self._config)
        elif self._config.transport == "http":
            self._transport = HttpTransport(self._config)
        else:
            return False
        if not self._transport.connect():
            return False
        self._connected = True
        tools = self.list_tools()
        self._tools = tools
        return True

    def disconnect(self) -> None:
        if self._transport:
            self._transport.close()
        self._connected = False
        self._tools = []

    def list_tools(self) -> List[MCPToolSchema]:
        if not self._transport or not self._connected:
            return []
        resp = self._transport.send({"method": "tools/list", "params": {}})
        if "error" in resp:
            return []
        tools_data = resp.get("result", {}).get("tools", [])
        result = []
        for t in tools_data:
            result.append(MCPToolSchema(
                name=t.get("name", ""),
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {}),
            ))
        return result

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> MCPToolResult:
        if not self._transport or not self._connected:
            return MCPToolResult(content=[{"type": "text", "text": "Not connected"}], isError=True)
        resp = self._transport.send({
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        if "error" in resp:
            err = resp["error"]
            return MCPToolResult(
                content=[{"type": "text", "text": err.get("message", str(err))}],
                isError=True,
            )
        result_data = resp.get("result", {})
        return MCPToolResult(
            content=result_data.get("content", []),
            isError=result_data.get("isError", False),
        )

    def health_check(self) -> bool:
        if not self._transport or not self._connected:
            return False
        resp = self._transport.send({"method": "ping", "params": {}})
        return "error" not in resp

    def is_connected(self) -> bool:
        return self._connected and self._transport and self._transport.is_connected()

    def get_tools(self) -> List[MCPToolSchema]:
        return list(self._tools)


class MCPServerManager:
    DEFAULT_CONFIG_PATH = os.path.expanduser("~/.lemoncode/mcp_servers.json")

    def __init__(self):
        self._servers: Dict[str, MCPClient] = {}
        self._configs: Dict[str, MCPServerConfig] = {}
        self._lock = threading.Lock()

    def add_server(self, config: MCPServerConfig) -> bool:
        with self._lock:
            if config.name in self._servers:
                return False
            client = MCPClient(config)
            self._servers[config.name] = client
            self._configs[config.name] = config
            return True

    def remove_server(self, name: str) -> bool:
        with self._lock:
            if name not in self._servers:
                return False
            client = self._servers.pop(name)
            self._configs.pop(name, None)
            try:
                client.disconnect()
            except Exception:
                pass
            return True

    def get_server(self, name: str) -> Optional[MCPClient]:
        with self._lock:
            return self._servers.get(name)

    def list_servers(self) -> List[str]:
        with self._lock:
            return list(self._servers.keys())

    def list_all_tools(self) -> List[Tuple[str, MCPToolSchema]]:
        result = []
        with self._lock:
            for name, client in self._servers.items():
                for tool in client.get_tools():
                    result.append((name, tool))
        return result

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> MCPToolResult:
        with self._lock:
            client = self._servers.get(server_name)
        if not client:
            return MCPToolResult(
                content=[{"type": "text", "text": f"Server not found: {server_name}"}],
                isError=True,
            )
        return client.call_tool(tool_name, arguments)

    def save_config(self, path: str = None) -> bool:
        path = path or self.DEFAULT_CONFIG_PATH
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            data = {}
            with self._lock:
                for name, config in self._configs.items():
                    data[name] = {
                        "name": config.name,
                        "transport": config.transport,
                        "command": config.command,
                        "args": config.args,
                        "url": config.url,
                        "headers": config.headers,
                        "env": config.env,
                        "enabled": config.enabled,
                    }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load_config(self, path: str = None) -> bool:
        path = path or self.DEFAULT_CONFIG_PATH
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name, cfg in data.items():
                config = MCPServerConfig(
                    name=cfg.get("name", name),
                    transport=cfg.get("transport", "stdio"),
                    command=cfg.get("command", ""),
                    args=cfg.get("args", []),
                    url=cfg.get("url", ""),
                    headers=cfg.get("headers", {}),
                    env=cfg.get("env", {}),
                    enabled=cfg.get("enabled", True),
                )
                self.add_server(config)
            return True
        except Exception:
            return False

    def health_check_all(self) -> Dict[str, bool]:
        result = {}
        with self._lock:
            names = list(self._servers.keys())
        for name in names:
            with self._lock:
                client = self._servers.get(name)
            if client:
                result[name] = client.is_connected()
            else:
                result[name] = False
        return result
