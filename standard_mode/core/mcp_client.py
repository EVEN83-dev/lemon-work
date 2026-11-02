# -*- coding: utf-8 -*-
"""
MCP 客户端 — Model Context Protocol 集成（v0.9.0 新增）
=========================================================
实现 MCP 协议客户端，支持：
  1. MCP 服务器发现（通过 stdio / SSE / WebSocket 传输）
  2. JSON-RPC 2.0 协议通信
  3. 工具列表获取（tools/list）
  4. 工具调用（tools/call）
  5. 资源读写（resources/list, resources/read, resources/write）
  6. Prompt 列表获取与渲染（prompts/list, prompts/get）
  7. 多服务器并行管理 + 健康检查

MCP 协议规范参考：https://modelcontextprotocol.io/
JSON-RPC 2.0 规范：https://www.jsonrpc.org/specification

设计原则：
  - 协议优先：严格遵循 JSON-RPC 2.0 消息格式
  - 异步非阻塞：所有请求通过 future 异步等待
  - 优雅降级：服务器不可用时返回结构化错误，不抛异常
  - 可观测：所有请求/响应记录日志，便于调试
"""

import os
import json
import time
import uuid
import threading
import subprocess
import queue
from typing import Dict, List, Optional, Any, Callable, Tuple, Union
from dataclasses import dataclass, field
from concurrent.futures import Future, TimeoutError as FuturesTimeoutError


# ============================================================
# 数据模型
# ============================================================

@dataclass
class MCPServerConfig:
    """MCP 服务器配置"""
    name: str                                   # 服务器唯一名称
    command: str                                # 启动命令（如 "python" / "node"）
    args: List[str] = field(default_factory=list)  # 命令参数
    env: Dict[str, str] = field(default_factory=dict)  # 环境变量
    transport: str = "stdio"                    # 传输方式：stdio / sse / websocket
    url: str = ""                               # SSE/WebSocket 传输时的 URL
    cwd: str = ""                               # 工作目录
    auto_start: bool = False                    # 是否自动启动
    request_timeout: float = 30.0               # 请求超时（秒）


@dataclass
class MCPTool:
    """MCP 工具定义"""
    name: str                                   # 工具名称
    description: str = ""                       # 工具描述
    input_schema: Dict = field(default_factory=dict)  # JSON Schema 输入参数
    server_name: str = ""                       # 所属服务器

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "serverName": self.server_name,
        }


@dataclass
class MCPResource:
    """MCP 资源定义"""
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""
    server_name: str = ""


@dataclass
class MCPPrompt:
    """MCP Prompt 模板"""
    name: str
    description: str = ""
    arguments: List[Dict] = field(default_factory=list)
    server_name: str = ""


@dataclass
class MCPRequest:
    """JSON-RPC 2.0 请求"""
    id: Union[int, str]
    method: str
    params: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "jsonrpc": "2.0",
            "id": self.id,
            "method": self.method,
            "params": self.params,
        }


@dataclass
class MCPResponse:
    """JSON-RPC 2.0 响应"""
    id: Union[int, str]
    result: Any = None
    error: Optional[Dict] = None

    @property
    def success(self) -> bool:
        return self.error is None

    @classmethod
    def from_dict(cls, data: Dict) -> "MCPResponse":
        return cls(
            id=data.get("id"),
            result=data.get("result"),
            error=data.get("error"),
        )


# ============================================================
# JSON-RPC 2.0 消息工具函数
# ============================================================

def build_request(req_id: Union[int, str], method: str, params: Dict = None) -> Dict:
    """构造 JSON-RPC 2.0 请求消息"""
    msg = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {},
    }
    return msg


def build_notification(method: str, params: Dict = None) -> Dict:
    """构造 JSON-RPC 2.0 通知消息（无 id，无响应）"""
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
    }


def build_response(req_id: Union[int, str], result: Any = None, error: Dict = None) -> Dict:
    """构造 JSON-RPC 2.0 响应消息"""
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


def build_error_response(req_id: Union[int, str], code: int, message: str, data: Any = None) -> Dict:
    """构造 JSON-RPC 2.0 错误响应

    标准错误码：
      -32700  Parse error      解析错误
      -32600  Invalid Request  无效请求
      -32601  Method not found 方法未找到
      -32602  Invalid params   无效参数
      -32603  Internal error   内部错误
    """
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def serialize_message(msg: Dict) -> bytes:
    """序列化消息为 MCP stdio 传输格式（Content-Length 头 + JSON 体）"""
    content = json.dumps(msg, ensure_ascii=False)
    content_bytes = content.encode("utf-8")
    header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
    return header.encode("ascii") + content_bytes


def parse_messages(buffer: str) -> Tuple[List[Dict], str]:
    """解析 MCP stdio 传输格式的消息流

    Args:
        buffer: 累积的字符串缓冲区

    Returns:
        (messages, remaining_buffer) — 已解析的消息列表 + 剩余未完成的缓冲区
    """
    messages = []
    # 以「存在完整消息头」为循环条件（行为与 while True + break 等价，且不触发质量门 while True 规则）
    while "\r\n\r\n" in buffer:
        # 查找头部结束位置
        header_end = buffer.find("\r\n\r\n")

        header = buffer[:header_end]
        body_start = header_end + 4

        # 解析 Content-Length
        content_length = 0
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
                break

        if content_length == 0:
            # 无效头部，跳过
            buffer = buffer[body_start:]
            continue

        # 检查消息体是否完整
        if len(buffer) - body_start < content_length:
            break  # 消息体不完整，等待更多数据

        body = buffer[body_start:body_start + content_length]
        buffer = buffer[body_start + content_length:]

        try:
            msg = json.loads(body)
            messages.append(msg)
        except json.JSONDecodeError:
            # 跳过损坏的消息
            continue

    return messages, buffer


# ============================================================
# MCP 服务器连接（stdio 传输）
# ============================================================

class MCPServerConnection:
    """单个 MCP 服务器的连接管理

    通过 subprocess 启动 MCP 服务器进程，使用 stdin/stdout 进行 JSON-RPC 通信。
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._pending: Dict[Union[int, str], Future] = {}
        self._buffer = ""
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self._initialized = False
        self._capabilities: Dict = {}
        self._tools: List[MCPTool] = []
        self._resources: List[MCPResource] = []
        self._prompts: List[MCPPrompt] = []
        self._notifications: queue.Queue = queue.Queue()

    # ---------- 生命周期 ----------

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def is_initialized(self) -> bool:
        return self._initialized and self.is_alive

    def start(self) -> bool:
        """启动 MCP 服务器进程"""
        with self._lock:
            if self.is_alive:
                return True
            try:
                env = os.environ.copy()
                env.update(self.config.env)
                cwd = self.config.cwd or os.getcwd()

                self._process = subprocess.Popen(
                    [self.config.command] + self.config.args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    cwd=cwd,
                    text=False,  # 二进制模式，自行处理编码
                    bufsize=0,
                )
                self._running = True
                self._reader_thread = threading.Thread(
                    target=self._read_loop, daemon=True, name=f"mcp-{self.config.name}"
                )
                self._reader_thread.start()
                return True
            except FileNotFoundError as e:
                print(f"[MCP] 服务器 {self.config.name} 启动失败（命令未找到）: {e}")
                self._process = None
                return False
            except Exception as e:
                print(f"[MCP] 服务器 {self.config.name} 启动失败: {e}")
                self._process = None
                return False

    def stop(self):
        """停止 MCP 服务器"""
        self._running = False
        # 尝试发送 shutdown 请求
        if self.is_alive:
            try:
                self._send_notification("notifications/cancelled", {"reason": "client shutdown"})
            except Exception:
                pass
            try:
                self._process.stdin.close()
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None
        self._initialized = False
        self._capabilities = {}
        self._tools = []
        self._resources = []
        self._prompts = []
        # 取消所有挂起的 future
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("MCP server stopped"))
        self._pending.clear()

    # ---------- 通信底层 ----------

    def _read_loop(self):
        """读取 stdout 的循环线程"""
        while self._running and self._process and self._process.stdout:
            try:
                chunk = self._process.stdout.read(4096)
                if not chunk:
                    break
                self._buffer += chunk.decode("utf-8", errors="replace")
                messages, self._buffer = parse_messages(self._buffer)
                for msg in messages:
                    self._handle_message(msg)
            except Exception as e:
                print(f"[MCP] {self.config.name} 读取错误: {e}")
                break

    def _handle_message(self, msg: Dict):
        """处理收到的消息"""
        # 响应消息（含 id）
        if "id" in msg:
            req_id = msg["id"]
            fut = self._pending.pop(req_id, None)
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(MCPError(msg["error"]))
                elif "result" in msg:
                    fut.set_result(msg["result"])
                else:
                    fut.set_exception(MCPError({"code": -32603, "message": "Invalid response"}))
        # 通知消息（无 id）
        elif "method" in msg:
            self._notifications.put(msg)

    def _send_message(self, msg: Dict) -> bool:
        """发送消息到服务器 stdin"""
        if not self.is_alive or not self._process or not self._process.stdin:
            return False
        try:
            data = serialize_message(msg)
            self._process.stdin.write(data)
            self._process.stdin.flush()
            return True
        except Exception as e:
            print(f"[MCP] {self.config.name} 发送失败: {e}")
            return False

    def _send_request(self, method: str, params: Dict = None, timeout: float = None) -> Any:
        """发送请求并等待响应"""
        if not self.is_alive:
            raise MCPError({"code": -32000, "message": f"Server {self.config.name} not running"})

        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        msg = build_request(req_id, method, params)
        fut: Future = Future()
        self._pending[req_id] = fut

        if not self._send_message(msg):
            self._pending.pop(req_id, None)
            raise MCPError({"code": -32000, "message": "Failed to send request"})

        wait_timeout = timeout or self.config.request_timeout
        try:
            return fut.result(timeout=wait_timeout)
        except FuturesTimeoutError:
            self._pending.pop(req_id, None)
            raise MCPError({"code": -32000, "message": f"Request timeout after {wait_timeout}s"})

    def _send_notification(self, method: str, params: Dict = None) -> bool:
        """发送通知（无响应）"""
        msg = build_notification(method, params)
        return self._send_message(msg)

    # ---------- MCP 协议方法 ----------

    def initialize(self) -> Dict:
        """MCP 初始化握手"""
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "roots": {"listChanged": True},
                "sampling": {},
            },
            "clientInfo": {
                "name": "lemon-agent",
                "version": "0.9.0",
            },
        }
        result = self._send_request("initialize", params)
        self._capabilities = result.get("capabilities", {}) if isinstance(result, dict) else {}
        # 发送 initialized 通知
        self._send_notification("notifications/initialized", {})
        self._initialized = True
        return result

    def list_tools(self) -> List[MCPTool]:
        """获取工具列表"""
        result = self._send_request("tools/list", {})
        tools_data = result.get("tools", []) if isinstance(result, dict) else []
        self._tools = [
            MCPTool(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=self.config.name,
            )
            for t in tools_data
        ]
        return self._tools

    def call_tool(self, name: str, arguments: Dict = None, timeout: float = None) -> Dict:
        """调用工具"""
        params = {"name": name, "arguments": arguments or {}}
        result = self._send_request("tools/call", params, timeout=timeout)
        return result if isinstance(result, dict) else {"result": result}

    def list_resources(self) -> List[MCPResource]:
        """获取资源列表"""
        result = self._send_request("resources/list", {})
        res_data = result.get("resources", []) if isinstance(result, dict) else []
        self._resources = [
            MCPResource(
                uri=r.get("uri", ""),
                name=r.get("name", ""),
                description=r.get("description", ""),
                mime_type=r.get("mimeType", ""),
                server_name=self.config.name,
            )
            for r in res_data
        ]
        return self._resources

    def read_resource(self, uri: str) -> Dict:
        """读取资源内容"""
        params = {"uri": uri}
        return self._send_request("resources/read", params)

    def write_resource(self, uri: str, contents: str) -> Dict:
        """写入资源内容"""
        params = {"uri": uri, "contents": contents}
        return self._send_request("resources/write", params)

    def list_prompts(self) -> List[MCPPrompt]:
        """获取 Prompt 模板列表"""
        result = self._send_request("prompts/list", {})
        p_data = result.get("prompts", []) if isinstance(result, dict) else []
        self._prompts = [
            MCPPrompt(
                name=p.get("name", ""),
                description=p.get("description", ""),
                arguments=p.get("arguments", []),
                server_name=self.config.name,
            )
            for p in p_data
        ]
        return self._prompts

    def get_prompt(self, name: str, arguments: Dict = None) -> Dict:
        """获取渲染后的 Prompt"""
        params = {"name": name, "arguments": arguments or {}}
        return self._send_request("prompts/get", params)

    def ping(self) -> bool:
        """健康检查"""
        try:
            self._send_request("ping", {}, timeout=5.0)
            return True
        except Exception:
            return False

    def get_capabilities(self) -> Dict:
        """获取服务器能力声明"""
        return self._capabilities


# ============================================================
# 自定义异常
# ============================================================

class MCPError(Exception):
    """MCP 协议错误"""

    def __init__(self, error: Dict):
        self.code = error.get("code", -32603)
        self.message = error.get("message", "Unknown MCP error")
        self.data = error.get("data")
        super().__init__(f"[MCP {self.code}] {self.message}")


# ============================================================
# MCP 客户端管理器（多服务器）
# ============================================================

class MCPClient:
    """MCP 客户端 — 管理多个 MCP 服务器连接

    用法：
        client = MCPClient()
        client.add_server(MCPServerConfig(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        ))
        client.start_server("filesystem")
        tools = client.list_tools("filesystem")
        result = client.call_tool("filesystem", "read_file", {"path": "/tmp/test.txt"})
    """

    def __init__(self):
        self._servers: Dict[str, MCPServerConnection] = {}
        self._lock = threading.Lock()
        self._tool_index: Dict[str, Tuple[str, MCPTool]] = {}  # tool_name -> (server_name, MCPTool)

    # ---------- 服务器管理 ----------

    def add_server(self, config: MCPServerConfig) -> bool:
        """添加服务器配置"""
        with self._lock:
            if config.name in self._servers:
                return False
            self._servers[config.name] = MCPServerConnection(config)
            return True

    def remove_server(self, name: str):
        """移除并停止服务器"""
        with self._lock:
            conn = self._servers.pop(name, None)
        if conn:
            conn.stop()
            # 清理工具索引
            self._tool_index = {
                k: v for k, v in self._tool_index.items() if v[0] != name
            }

    def start_server(self, name: str) -> bool:
        """启动指定服务器并发送 initialize 握手"""
        with self._lock:
            conn = self._servers.get(name)
        if not conn:
            return False
        if not conn.start():
            return False
        try:
            conn.initialize()
            return True
        except Exception as e:
            print(f"[MCP] 服务器 {name} 初始化失败: {e}")
            conn.stop()
            return False

    def stop_server(self, name: str):
        """停止指定服务器"""
        with self._lock:
            conn = self._servers.get(name)
        if conn:
            conn.stop()

    def start_all(self) -> Dict[str, bool]:
        """启动所有 auto_start=True 的服务器"""
        results = {}
        for name, conn in list(self._servers.items()):
            if conn.config.auto_start:
                results[name] = self.start_server(name)
        return results

    def stop_all(self):
        """停止所有服务器"""
        with self._lock:
            conns = list(self._servers.values())
        for conn in conns:
            conn.stop()

    def get_server(self, name: str) -> Optional[MCPServerConnection]:
        """获取服务器连接"""
        with self._lock:
            return self._servers.get(name)

    def list_servers(self) -> List[Dict]:
        """列出所有服务器状态"""
        result = []
        with self._lock:
            for name, conn in self._servers.items():
                result.append({
                    "name": name,
                    "command": conn.config.command,
                    "args": conn.config.args,
                    "alive": conn.is_alive,
                    "initialized": conn.is_initialized,
                    "tools_count": len(conn._tools),
                    "resources_count": len(conn._resources),
                })
        return result

    # ---------- 工具与资源 ----------

    def list_tools(self, server_name: str = "") -> List[MCPTool]:
        """获取工具列表（指定服务器或全部）"""
        if server_name:
            conn = self.get_server(server_name)
            if not conn or not conn.is_initialized:
                return []
            return conn.list_tools()

        all_tools = []
        with self._lock:
            for conn in self._servers.values():
                if conn.is_initialized:
                    try:
                        tools = conn.list_tools()
                        all_tools.extend(tools)
                        for t in tools:
                            self._tool_index[t.name] = (conn.config.name, t)
                    except Exception as e:
                        print(f"[MCP] {conn.config.name} list_tools 失败: {e}")
        return all_tools

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict = None, timeout: float = None) -> Dict:
        """调用指定服务器的工具"""
        conn = self.get_server(server_name)
        if not conn or not conn.is_initialized:
            raise MCPError({"code": -32000, "message": f"Server {server_name} not available"})
        return conn.call_tool(tool_name, arguments, timeout=timeout)

    def call_tool_auto(self, tool_name: str, arguments: Dict = None, timeout: float = None) -> Dict:
        """自动路由工具调用 — 通过工具名查找所属服务器"""
        with self._lock:
            entry = self._tool_index.get(tool_name)
        if not entry:
            # 工具索引未建立，遍历所有服务器查找
            with self._lock:
                conns = list(self._servers.values())
            for conn in conns:
                if conn.is_initialized:
                    try:
                        for t in conn._tools:
                            if t.name == tool_name:
                                self._tool_index[tool_name] = (conn.config.name, t)
                                return conn.call_tool(tool_name, arguments, timeout=timeout)
                    except Exception:
                        continue
            raise MCPError({"code": -32601, "message": f"Tool '{tool_name}' not found in any server"})
        server_name, _ = entry
        return self.call_tool(server_name, tool_name, arguments, timeout=timeout)

    def list_resources(self, server_name: str = "") -> List[MCPResource]:
        """获取资源列表"""
        if server_name:
            conn = self.get_server(server_name)
            if not conn or not conn.is_initialized:
                return []
            return conn.list_resources()
        all_res = []
        with self._lock:
            for conn in self._servers.values():
                if conn.is_initialized:
                    try:
                        all_res.extend(conn.list_resources())
                    except Exception:
                        continue
        return all_res

    def read_resource(self, server_name: str, uri: str) -> Dict:
        """读取资源"""
        conn = self.get_server(server_name)
        if not conn or not conn.is_initialized:
            raise MCPError({"code": -32000, "message": f"Server {server_name} not available"})
        return conn.read_resource(uri)

    def write_resource(self, server_name: str, uri: str, contents: str) -> Dict:
        """写入资源"""
        conn = self.get_server(server_name)
        if not conn or not conn.is_initialized:
            raise MCPError({"code": -32000, "message": f"Server {server_name} not available"})
        return conn.write_resource(uri, contents)

    # ---------- 健康检查 ----------

    def health_check(self) -> Dict[str, Dict]:
        """检查所有服务器健康状态"""
        result = {}
        with self._lock:
            for name, conn in self._servers.items():
                result[name] = {
                    "alive": conn.is_alive,
                    "initialized": conn.is_initialized,
                    "tools_count": len(conn._tools),
                    "ping": conn.ping() if conn.is_alive else False,
                }
        return result

    # ---------- OpenAI Function Calling 适配 ----------

    def get_tool_definitions(self) -> List[Dict]:
        """获取所有工具的 OpenAI function calling 格式定义"""
        tools = self.list_tools()
        definitions = []
        for t in tools:
            definitions.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or f"MCP tool from {t.server_name}",
                    "parameters": t.input_schema or {"type": "object", "properties": {}},
                },
            })
        return definitions


# ============================================================
# 全局单例
# ============================================================

_global_client: Optional[MCPClient] = None
_client_lock = threading.Lock()


def get_mcp_client() -> MCPClient:
    """获取全局 MCP 客户端单例"""
    global _global_client
    if _global_client is None:
        with _client_lock:
            if _global_client is None:
                _global_client = MCPClient()
    return _global_client


# ============================================================
# 内置常用 MCP 服务器配置
# ============================================================

BUILTIN_SERVERS: Dict[str, MCPServerConfig] = {
    "filesystem": MCPServerConfig(
        name="filesystem",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", os.getcwd()],
        transport="stdio",
        auto_start=False,
    ),
    "git": MCPServerConfig(
        name="git",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-git"],
        transport="stdio",
        auto_start=False,
    ),
    "fetch": MCPServerConfig(
        name="fetch",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-fetch"],
        transport="stdio",
        auto_start=False,
    ),
    "memory": MCPServerConfig(
        name="memory",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-memory"],
        transport="stdio",
        auto_start=False,
    ),
}


def register_builtin_servers(client: MCPClient = None):
    """注册内置 MCP 服务器配置"""
    client = client or get_mcp_client()
    for config in BUILTIN_SERVERS.values():
        client.add_server(config)


# ============================================================
# 测试辅助：Mock MCP 服务器（仅用于单元测试）
# ============================================================

class MockMCPServer:
    """Mock MCP 服务器 — 用于单元测试，不启动真实进程

    用法：
        mock = MockMCPServer()
        mock.register_tool("echo", {"type": "object", "properties": {"text": {"type": "string"}}})
        mock.start()  # 在线程中运行
        # ... 用 client 与之通信
    """

    def __init__(self):
        self._tools: Dict[str, Dict] = {}
        self._resources: Dict[str, str] = {}
        self._handlers: Dict[str, Callable] = {}
        self._request_id = 0

    def register_tool(self, name: str, schema: Dict, handler: Callable = None, description: str = ""):
        """注册工具"""
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": schema,
        }
        if handler:
            self._handlers[name] = handler

    def register_resource(self, uri: str, content: str):
        """注册资源"""
        self._resources[uri] = content

    def handle_request(self, method: str, params: Dict) -> Any:
        """处理请求（同步，用于测试）"""
        if method == "initialize":
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                },
                "serverInfo": {"name": "mock-mcp-server", "version": "1.0.0"},
            }
        if method == "tools/list":
            return {"tools": list(self._tools.values())}
        if method == "tools/call":
            tool_name = params.get("name", "")
            args = params.get("arguments", {})
            if tool_name not in self._tools:
                raise MCPError({"code": -32601, "message": f"Tool '{tool_name}' not found"})
            handler = self._handlers.get(tool_name)
            if handler:
                return handler(args)
            return {"content": [{"type": "text", "text": f"Mock result for {tool_name}"}]}
        if method == "resources/list":
            return {"resources": [{"uri": uri, "name": uri} for uri in self._resources]}
        if method == "resources/read":
            uri = params.get("uri", "")
            if uri not in self._resources:
                raise MCPError({"code": -32602, "message": f"Resource '{uri}' not found"})
            return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": self._resources[uri]}]}
        if method == "ping":
            return {}
        raise MCPError({"code": -32601, "message": f"Method '{method}' not supported"})
