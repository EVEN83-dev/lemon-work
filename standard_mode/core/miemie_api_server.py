# -*- coding: utf-8 -*-
"""
咩咩独立后端 REST API — miemie/core 独立化（Phase 1 P1）
==========================================================
基于 Python 标准库 `http.server` 的轻量 REST API 服务，把咩咩引擎能力
（LLM 对话 / 工具执行 / 模型发现）暴露为**独立 HTTP 后端**，与 PyQt5 前端
解耦，可独立进程运行、可被任意客户端（含 web 前端 fetch）调用。

端点：
    GET  /api/health       → 服务存活 + 引擎可用性
    GET  /api/models       → Ollama 可用模型列表
    POST /api/chat         → 非流式对话（JSON: {messages, model?}）
    POST /api/chat/stream  → SSE 流式对话（逐 token 推送）
    POST /api/tools/exec   → 执行咩咩工具（JSON: {tool, args?}）
    GET  /api/status       → 引擎 / 数据库 / 记忆 状态摘要

设计要点：
- **仅依赖标准库**（http.server / json / threading / argparse）；对
  `miemie_engine`（`standard_mode/ui/`）采用**惰性导入**——请求处理层可
  在不安装 PyQt5 / 不启动服务时离线测试。
- **核心逻辑抽为纯方法**（`MiemieApiCore`）：`parse_payload` / `handle`
  / `handle_health` 等不依赖 socket，支持注入假后端（fake backend）做
  离线单测；HTTP 层（`MiemieApiServer`）只是薄封装。
- 线程安全：`ThreadingHTTPServer` 每请求一线程；后端调用互不影响。

用法：
    python -m standard_mode.core.miemie_api_server --port 8765
    或在 Python 中： server = MiemieApiServer(host, port).start()
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List, Optional, Tuple

# =====================================================================
# 核心逻辑（纯，可离线测试）
# =====================================================================


class MiemieApiCore:
    """
    咩咩 REST API 核心逻辑。

    通过 `backend` 注入依赖（默认为空 dict，惰性从 miemie_engine 构建）：
        backend["list_models"] -> () -> List[str]
        backend["chat"]        -> (messages, model?) -> str
        backend["chat_stream"] -> (messages, model?) -> Iterator[(token, full)]
        backend["tools"]       -> {name: (args: dict) -> Any}
        backend["status"]      -> () -> Dict
    """

    def __init__(self, backend: Optional[Dict[str, Any]] = None):
        self._backend: Dict[str, Any] = backend or {}
        self._engine = None  # 惰性加载 miemie_engine
        self._lock = threading.Lock()

    # ---------- 惰性后端 ----------

    def _ensure_backend(self) -> Dict[str, Any]:
        """构建/复用完整后端（懒加载 miemie_engine 工具与 LLM 入口）。"""
        if self._backend:
            return self._backend
        with self._lock:
            if self._backend:
                return self._backend
            engine = self._load_engine()
            tools = {}
            for name in ("glob", "grep", "read_file", "write_file", "edit_file",
                         "bash", "web_fetch", "analyze_style", "memory_search",
                         "sql_query", "plan", "persona_extract", "vision_analyze"):
                fn = getattr(engine, f"tool_{name}", None)
                if callable(fn):
                    tools[name] = fn
            self._backend = {
                "list_models": engine._ollama_models,
                "chat": self._make_chat(engine),
                "chat_stream": engine._ollama_chat_stream,
                "tools": tools,
                "status": lambda: {
                    "db": engine._DB_PATH,
                    "memory": engine._MEMORY_PATH,
                    "ignored_dirs": sorted(engine._IGNORE_DIRS),
                },
            }
            return self._backend

    @staticmethod
    def _load_engine():
        """惰性导入 miemie_engine（兼容 ui 包 / standard_mode.ui 两种路径）。"""
        try:
            import miemie_engine as eng  # type: ignore
        except ImportError:
            try:
                from standard_mode.ui import miemie_engine as eng  # type: ignore
            except ImportError:
                from ui import miemie_engine as eng  # type: ignore
        return eng

    @staticmethod
    def _make_chat(engine):
        def _chat(messages, model=""):
            return engine._ollama_chat(messages, model=model)
        return _chat

    # ---------- 请求解析 ----------

    def parse_payload(self, body: bytes) -> Tuple[Optional[Dict], Optional[str]]:
        """把请求体解析为 JSON dict；失败返回 (None, 错误信息)。"""
        if not body:
            return {}, None
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception as e:
            return None, f"body 解码失败: {e}"
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            return None, f"JSON 解析失败: {e}"
        if not isinstance(data, dict):
            return None, "请求体必须是 JSON 对象"
        return data, None

    # ---------- 路由（纯） ----------

    def handle(self, method: str, path: str, body: bytes) -> Tuple[int, Dict[str, Any]]:
        """
        纯路由：根据 method + path 分派，返回 (http_status, json_body)。

        不依赖 socket / 服务运行，可注入假后端离线测试。
        """
        if method == "GET" and path.rstrip("/") == "/api/health":
            return 200, self.handle_health()
        if method == "GET" and path.rstrip("/") == "/api/models":
            return 200, self.handle_models()
        if method == "GET" and path.rstrip("/") == "/api/status":
            return 200, self.handle_status()
        if method == "POST" and path.rstrip("/") == "/api/chat":
            data, err = self.parse_payload(body)
            if err:
                return 400, {"error": err}
            return self.handle_chat(data)
        if method == "POST" and path.rstrip("/") == "/api/tools/exec":
            data, err = self.parse_payload(body)
            if err:
                return 400, {"error": err}
            return self.handle_tools_exec(data)
        if path.rstrip("/") == "/api/chat/stream":
            # 流式端点由 HTTP 层特判（SSE），此处仅做载荷校验
            data, err = self.parse_payload(body)
            if err:
                return 400, {"error": err}
            return 200, {"_stream": True, "data": data}
        return 404, {"error": f"未找到端点: {method} {path}"}

    # ---------- 各端点处理器（纯） ----------

    def handle_health(self) -> Dict[str, Any]:
        backend = self._ensure_backend()
        try:
            models = backend["list_models"]() if callable(backend.get("list_models")) else []
            engine_available = isinstance(models, list) and len(models) > 0
        except Exception as e:
            engine_available = False
        return {"status": "ok", "engine_available": engine_available}

    def handle_models(self) -> Dict[str, Any]:
        backend = self._ensure_backend()
        try:
            models = backend["list_models"]() if callable(backend.get("list_models")) else []
        except Exception as e:
            return {"models": [], "error": str(e)}
        return {"models": models if isinstance(models, list) else []}

    def handle_status(self) -> Dict[str, Any]:
        backend = self._ensure_backend()
        try:
            status = backend["status"]() if callable(backend.get("status")) else {}
        except Exception as e:
            status = {"error": str(e)}
        return {"status": status}

    def handle_chat(self, data: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            return 400, {"error": "messages 必须是非空列表"}
        model = data.get("model", "")
        backend = self._ensure_backend()
        chat_fn = backend.get("chat")
        if not callable(chat_fn):
            return 503, {"error": "聊天后端不可用（未注入 chat）"}
        try:
            reply = chat_fn(messages, model)
        except Exception as e:
            return 500, {"error": f"对话失败: {e}"}
        return 200, {"reply": reply, "model": model}

    def handle_tools_exec(self, data: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        tool = data.get("tool")
        args = data.get("args") or {}
        if not isinstance(tool, str) or not tool:
            return 400, {"error": "tool 必须是非空字符串"}
        if not isinstance(args, dict):
            return 400, {"error": "args 必须是对象"}
        backend = self._ensure_backend()
        tools = backend.get("tools") or {}
        fn = tools.get(tool)
        if not callable(fn):
            return 404, {"error": f"未知工具: {tool}"}
        try:
            result = fn(**args) if isinstance(args, dict) else fn()
        except TypeError as e:
            return 400, {"error": f"工具参数错误: {e}"}
        except Exception as e:
            return 500, {"error": f"工具执行失败: {e}"}
        return 200, {"tool": tool, "result": result}

    # ---------- SSE 流式 ----------

    def iter_stream(self, data: Dict[str, Any]) -> Iterator[str]:
        """把后端 chat_stream 的 (token, full) 迭代器转换为 SSE 文本事件流。"""
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            yield self._sse_event({"error": "messages 必须是非空列表"})
            yield self._sse_done()
            return
        backend = self._ensure_backend()
        stream_fn = backend.get("chat_stream")
        if not callable(stream_fn):
            yield self._sse_event({"error": "流式后端不可用"})
            yield self._sse_done()
            return
        try:
            for token, _full in stream_fn(messages, data.get("model", "")):
                yield self._sse_event({"token": token})
        except Exception as e:
            yield self._sse_event({"error": str(e)})
        finally:
            yield self._sse_done()

    @staticmethod
    def _sse_event(obj: Dict[str, Any]) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    @staticmethod
    def _sse_done() -> str:
        return "data: [DONE]\n\n"


# =====================================================================
# HTTP 层（薄封装）
# =====================================================================


class MiemieApiHandler(BaseHTTPRequestHandler):
    """把 HTTP 请求委托给 MiemieApiCore（流式端点走 SSE 特判）。"""

    core = None  # 类级共享实例（由 MiemieApiServer 注入）

    # 关闭日志噪音
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status: int, payload: Dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_request(self):
        core = self.core or MiemieApiCore()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else b""

        if self.path.rstrip("/") == "/api/chat/stream" and self.command == "POST":
            data, err = core.parse_payload(body)
            if err:
                self._send_json(400, {"error": err})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in core.iter_stream(data):
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
            return

        status, payload = core.handle(self.command, self.path, body)
        self._send_json(status, payload)

    def do_GET(self):
        self._handle_request()

    def do_POST(self):
        self._handle_request()


class MiemieApiServer:
    """咩咩独立后端 REST API 服务（可独立进程 / 线程运行）。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765,
                 core: Optional[MiemieApiCore] = None):
        self.host = host
        self.port = port
        self.core = core or MiemieApiCore()
        MiemieApiHandler.core = self.core
        self._httpd = None
        self._thread = None

    def start(self) -> "MiemieApiServer":
        """启动服务（阻塞于独立线程）。"""
        self._httpd = ThreadingHTTPServer((self.host, self.port), MiemieApiHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self

    @property
    def address(self) -> Tuple[str, int]:
        return (self.host, self.port)

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


# =====================================================================
# CLI 入口
# =====================================================================


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="咩咩独立后端 REST API")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    args = parser.parse_args(argv)

    server = MiemieApiServer(host=args.host, port=args.port).start()
    print(f"[miemie-api] 已启动: http://{args.host}:{args.port} "
          f"(Ctrl+C 停止)", flush=True)
    try:
        threading.Event().wait()  # 主线程挂起
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
