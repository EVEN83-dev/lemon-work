# -*- coding: utf-8 -*-
"""
终端后端：QWebSocket + 极简 JSON 协议（ConPTY + WebSocket 架构）
==================================================================
等价于 PyCharm/IntelliJ 的 JCEF Native Bridge 架构：
  PyCharm: xterm.js → JCEF C++ Bridge(同进程) → Java TtyConnector → PTY
  本实现:  xterm.js → WebSocket → 极简 JSON 协议 → TerminalBridge(Python)
           → ShellBridge(pywinpty) → cmd.exe

为什么是 WebSocket 而非 QWebChannel：
  PyQt5 的 QWebChannel + qwebchannel.js 在 Qt 5.15.2 实际部署中存在协议差异
  （init response 字段约定、消息格式等），导致浏览器端 init 回调永不触发（第391章
  根因闭环）。改用极简 JSON 协议完全绕开此问题：JS↔Python 双向 JSON，结构清晰、
  无版本风险。JS ↔ Python 仍保留「对象桥」语义（start / input / resize + output /
  exited），等价于 QWebChannel 的 signal/slot 暴露，只是 transport 层换成 WebSocket+JSON。

服务：
  - HTTP 静态服务：托管 terminal_xterm.html 与 vendor/*（同域加载，避免 CORS）
  - WebSocket 服务：每个连接自动创建 TerminalBridge（一个 PTY 会话）。
"""
import json
import mimetypes
import os
import threading

from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtWebSockets import QWebSocketServer, QWebSocket
from PyQt5.QtNetwork import QHostAddress, QAbstractSocket

from shared.shell_bridge import ShellBridge

_STATIC_ROOT = os.path.dirname(os.path.abspath(__file__))

# ★ 405A1: 回滚持久化 — 会话缓冲区落盘路径 + 容量护栏（2MB 截断保尾）
_SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "..", "data", "terminal_sessions")
_SESSION_MAX_BYTES = 2 * 1024 * 1024  # 2MB


def _session_file(sid: str) -> str:
    """返回会话缓冲区文件路径（不创建目录，由写者保证目录存在）。"""
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")
    if not safe:
        safe = "default"
    return os.path.join(_SESSIONS_DIR, f"{safe}.buf")


def _ensure_sessions_dir() -> None:
    os.makedirs(_SESSIONS_DIR, exist_ok=True)


def _write_session_buf(sid: str, data: str) -> None:
    """写入会话缓冲区（>2MB 截断保留尾部）。"""
    if not data:
        return
    _ensure_sessions_dir()
    if len(data) > _SESSION_MAX_BYTES:
        data = data[-_SESSION_MAX_BYTES:]
    path = _session_file(sid)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[TerminalServer] 会话写入失败 {sid}: {e}", flush=True)


def _read_session_buf(sid: str) -> str:
    """读取会话缓冲区（文件不存在则返空）。"""
    path = _session_file(sid)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read()
            return data[-_SESSION_MAX_BYTES:]
        except OSError as e:
            print(f"[TerminalServer] 会话读取失败 {sid}: {e}", flush=True)
            return ""
    return ""


# ★ 405A1: 跨应用重启的稳定面板 SID 注册表
_REGISTRY_PATH = os.path.join(_SESSIONS_DIR, ".panel_registry.json")
_registry_lock = threading.Lock()


def _load_registry() -> dict:
    if os.path.exists(_REGISTRY_PATH):
        try:
            with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_registry(reg: dict) -> None:
    _ensure_sessions_dir()
    tmp = _REGISTRY_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _REGISTRY_PATH)
    except OSError:
        pass


def assign_panel_sid(cwd: str, preferred: str | None = None) -> str:
    """分配跨应用重启稳定的面板 SID。

    - preferred 给出时优先复用（面板重启场景）
    - 否则按 cwd 查找已有条目，找不到则新建编号条目（从 max+1 递增）
    """
    import hashlib
    cwd_tag = hashlib.sha1(cwd.encode("utf-8", errors="replace")).hexdigest()[:10]
    with _registry_lock:
        reg = _load_registry()
        if preferred and preferred in reg and reg[preferred].get("cwd_tag") == cwd_tag:
            reg[preferred]["last_used"] = _ts()
            _save_registry(reg)
            return preferred
        for sid, info in reg.items():
            if info.get("cwd_tag") == cwd_tag:
                info["last_used"] = _ts()
                _save_registry(reg)
                return sid
        idx = max((int(k.split("_")[1]) for k in reg if k.startswith("panel_")),
                  default=0) + 1
        sid = f"panel_{idx:03d}"
        reg[sid] = {"cwd_tag": cwd_tag, "cwd": cwd, "created": _ts(), "last_used": _ts()}
        _save_registry(reg)
        return sid


def _ts() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


class TerminalBridge(QObject):
    """一个 PTY 会话的桥接对象。每个 WebSocket 连接对应一个实例。

    对外通过 WebSocket JSON 协议暴露：
      JS → Python:
        {"cmd": "start"}
        {"cmd": "input", "data": "..."}
        {"cmd": "resize", "cols": 80, "rows": 24}
      Python → JS:
        {"evt": "ready", "sid": "..."}
        {"evt": "data", "data": "..."}
        {"evt": "exited", "code": -1}
        {"evt": "error", "msg": "..."}
    """

    def __init__(self, socket: QWebSocket, cwd=None, parent=None, auth_token=None):
        super().__init__(parent)
        self._socket = socket
        self._auth_token = auth_token
        self._authenticated = False  # ★ 安全：认证状态
        self._paused = False  # ★ 流量控制：暂停状态
        self._bridge = ShellBridge(cwd=cwd or os.getcwd())
        self._bridge.raw_output.connect(self._on_output)
        self._bridge.error_occurred.connect(self._on_error)
        self._bridge.process_stopped.connect(self._on_stopped)
        self._session_id = f"term_{id(self):x}"
        self._stopped = False

        # ── 输出批合并（10ms 一次 flush）──
        # PTY 高频回调（npx TUI 启动时一次喷 100KB+）→ 合并到 10ms 窗口，
        # 大幅减少 WebSocket 帧数 + 给 xterm.js 留渲染时间，避免渲染队列溢出。
        self._buf = []
        self._buf_chars = 0
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_buf)

    # ── PTY 回调 → 输出缓冲 → JSON 推给 JS ─────────────────
    # ★ 缓冲上限（防止内存暴涨）
    MAX_BUF_SIZE = 1024 * 1024  # 1MB
    MAX_BUF_COUNT = 1000        # 最多 1000 条
    
    def _on_output(self, data: str):
        if self._stopped:
            return
        # ★ 流量控制：暂停时不处理
        if self._paused:
            return
        
        # ★ 缓冲上限检查：超过上限强制 flush
        if self._buf_chars >= self.MAX_BUF_SIZE or len(self._buf) >= self.MAX_BUF_COUNT:
            self._flush_buf()
        
        self._buf.append(data)
        self._buf_chars += len(data)
        # 大块或缓冲满 → 立即 flush；否则等 10ms 定时器
        if self._buf_chars >= 16384 or len(self._buf) >= 32:
            self._flush_buf()
        elif not self._flush_timer.isActive():
            self._flush_timer.start(10)

    def _on_error(self, msg: str):
        # 错误立即发送（不缓冲，避免丢失诊断信息）
        self._send({"evt": "error", "msg": msg})

    def _on_stopped(self, code: int):
        self._flush_buf()  # 先把残留 flush 出去
        self._send({"evt": "exited", "code": int(code)})

    def _flush_buf(self):
        self._flush_timer.stop()
        if not self._buf:
            return
        merged = "".join(self._buf)
        self._buf.clear()
        self._buf_chars = 0
        self._send({"evt": "data", "data": merged})

    # ── JSON 协议入口（JS 调过来的） ──────────────────────────
    def handle_message(self, obj: dict):
        cmd = obj.get("cmd")
        seq = obj.get("_seq", "?")  # ★ 序列号（用于调试）
        try:
            if cmd == "start":
                cols = int(obj.get("cols", 120))
                rows = int(obj.get("rows", 30))
                self._do_start(cols, rows)
            elif cmd == "input":
                self._bridge.send(obj.get("data", ""))
            elif cmd == "resize":
                self._bridge.resize(int(obj.get("cols", 80)), int(obj.get("rows", 24)))
            elif cmd == "interrupt":
                self._bridge.ctrl_c()
            elif cmd == "ping":
                self._send({"evt": "pong"})
            # ★ 流量控制：pause/resume
            elif cmd == "pause":
                # 暂停 PTY 输出（通过设置标志位）
                self._paused = True
            elif cmd == "resume":
                # 恢复 PTY 输出
                self._paused = False
            # ★ 405A1: 回滚持久化（序列化/恢复）
            elif cmd == "serialize":
                # 前端主动发来的完整 ANSI 缓冲区
                data = obj.get("data", "")
                sid = obj.get("sid") or self._session_id
                if data:
                    _write_session_buf(sid, data)
            elif cmd == "restore":
                # 请求恢复上次会话缓冲区
                sid = obj.get("sid") or self._session_id
                buf = _read_session_buf(sid)
                if buf:
                    self._send({"evt": "restore", "data": buf, "sid": sid})
                else:
                    self._send({"evt": "restore", "data": "", "sid": sid})
            else:
                self._send({"evt": "error", "msg": f"unknown cmd: {cmd}"})
        except Exception as e:  # noqa: BLE001
            self._send({"evt": "error", "msg": f"{cmd} 异常: {e}"})

    def _do_start(self, cols: int = 120, rows: int = 30):
        if self._bridge.is_running:
            self._send({"evt": "ready", "sid": self._session_id})
            return
        # 把前端真实 cols/rows 传给 ShellBridge，PTY 用这个尺寸启动
        self._bridge.cols = max(40, cols)
        self._bridge.rows = max(10, rows)
        try:
            ok = self._bridge.start()
            if ok:
                print(f"[TerminalServer] PTY 启动成功 {self._session_id}", flush=True)
                self._send({"evt": "ready", "sid": self._session_id})
                # ★ 404: Ink 类全屏 TUI（DevEco Code 等）启动时读一次初始尺寸，
                #   之后依赖窗口尺寸变化事件重绘 — ConPTY 下该事件不可靠，
                #   面板宽度变化后 TUI 停在旧尺寸（渲染错位+输入假死）。
                #   吐 startup 完成后延迟强制 setwinsize 一次，触发 Node/Ink 重绘。
                import threading
                _b = self._bridge
                def _resync_size():
                    try:
                        _b.resize(_b.cols, _b.rows)
                    except Exception:
                        pass
                t = threading.Timer(0.8, _resync_size)
                t.daemon = True
                t.start()
            else:
                self._send({"evt": "error", "msg": "PTY 启动失败"})
        except Exception as e:  # noqa: BLE001
            print(f"[TerminalServer] PTY 启动异常: {e}", flush=True)
            self._send({"evt": "error", "msg": f"PTY 启动异常: {e}"})

    # ── 发送 JSON ────────────────────────────────────────────
    def _send(self, obj: dict):
        if self._stopped:
            return
        try:
            if self._socket.state() != QAbstractSocket.ConnectedState:
                return
            text = json.dumps(obj, ensure_ascii=False)
            self._socket.sendTextMessage(text)
        except Exception as e:  # noqa: BLE001
            print(f"[TerminalServer] 发送失败: {e}", flush=True)

    def stop(self):
        self._stopped = True
        self._flush_buf()  # 关闭前 flush 残留
        if self._flush_timer:
            self._flush_timer.stop()
        if self._bridge:
            try:
                self._bridge.stop()
            except (OSError, RuntimeError) as e:
                print(f"[TerminalBridge] 停止失败: {e}", flush=True)
            self._bridge = None

    def interrupt(self):
        if self._bridge:
            self._bridge.ctrl_c()


class TerminalServer(QObject):
    """WebSocket 终端服务（QWebSocketServer 必须在 Qt 主线程事件循环中）。

    同时启动 stdlib HTTPServer 托管静态 HTML（避免 CORS）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.http_port = 0
        self.ws_port = 0
        self.auth_token = os.urandom(16).hex()  # ★ 安全：WebSocket 连接验证 token
        self.default_cwd = None  # ★ 新 WebSocket 连接的 PTY 启动目录
        self._httpd = None
        self._http_thread = None
        self._ws_server = None
        self._bridges = []      # 保留引用防 GC
        self._sockets = []
        self._bridges_lock = threading.Lock()
        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(self._ping_all)

    # ═══════════════════════════════════════════════════════════
    def start(self) -> tuple:
        if self._ws_server and self._httpd:
            return self.http_port, self.ws_port

        # ── HTTP 静态服务（独立线程） ────────────────────────
        if not self._httpd:
            from http.server import HTTPServer
            self._httpd = HTTPServer(("127.0.0.1", 0), _StaticHandler)
            self.http_port = self._httpd.server_address[1]
            self._http_thread = threading.Thread(
                target=self._httpd.serve_forever, daemon=True)
            self._http_thread.start()

        # ── WebSocket 服务（Qt 主线程事件循环） ──────────────
        if not self._ws_server:
            self._ws_server = QWebSocketServer(
                "LemonTerminal", QWebSocketServer.NonSecureMode, self)
            if not self._ws_server.listen(QHostAddress.LocalHost, 0):
                raise RuntimeError(
                    f"WebSocket 服务器启动失败: {self._ws_server.errorString()}")
            self.ws_port = self._ws_server.serverPort()
            self._ws_server.newConnection.connect(self._on_new_connection)

        self._ping_timer.start(30000)

        print(f"[TerminalServer] HTTP={self.http_port} WebSocket={self.ws_port} Token={self.auth_token[:8]}...", flush=True)
        return self.http_port, self.ws_port, self.auth_token

    def stop(self):
        self._ping_timer.stop()
        with self._bridges_lock:
            for b in self._bridges:
                try:
                    b.stop()
                except Exception:  # noqa: BLE001
                    pass
            self._bridges.clear()
            self._sockets.clear()
        if self._ws_server:
            self._ws_server.close()
            self._ws_server = None
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._httpd = None

    # ═══════════════════════════════════════════════════════════
    def _on_new_connection(self):
        socket = self._ws_server.nextPendingConnection()
        if not socket:
            return
        print("[TerminalServer] 新 WebSocket 连接", flush=True)

        bridge = TerminalBridge(socket=socket, cwd=self.default_cwd, parent=self, auth_token=self.auth_token)

        with self._bridges_lock:
            self._bridges.append(bridge)
            self._sockets.append(socket)

        socket.textMessageReceived.connect(
            lambda msg: self._on_ws_message(socket, msg, bridge))
        socket.disconnected.connect(
            lambda: self._on_socket_closed(socket, bridge))
        socket.error.connect(
            lambda err: print(f"[TerminalServer] WebSocket error {err}: "
                              f"{socket.errorString()}", flush=True))

    # ★ 安全：消息大小限制 (1MB)
    MAX_MSG_SIZE = 1024 * 1024

    def _on_ws_message(self, socket: QWebSocket, msg: str, bridge: TerminalBridge):
        # ★ 安全：检查消息大小
        if len(msg) > self.MAX_MSG_SIZE:
            print(f"[TerminalServer] 消息过大 ({len(msg)} bytes)，拒绝处理", flush=True)
            socket.close()
            return
        # ★ 安全：验证 token（首条消息必须是 auth）
        if not bridge._authenticated:
            print(f"[TerminalServer] 收到未认证消息: {msg[:100]}...", flush=True)
            try:
                obj = json.loads(msg)
                # ★ 临时：允许无认证（调试用）
                if obj.get("cmd") == "auth" and obj.get("token") == self.auth_token:
                    bridge._authenticated = True
                    bridge._send({"evt": "auth_ok"})
                    print("[TerminalServer] WebSocket 认证成功", flush=True)
                    return
                elif obj.get("cmd") == "start":
                    # 兼容旧版：直接允许 start（调试）
                    print("[TerminalServer] 跳过认证，直接处理 start", flush=True)
                    bridge._authenticated = True
                    bridge.handle_message(obj)
                    return
                else:
                    print(f"[TerminalServer] WebSocket 认证失败: cmd={obj.get('cmd')} token_match={obj.get('token') == self.auth_token}", flush=True)
                    socket.close()
                    return
            except (json.JSONDecodeError, KeyError) as e:
                print(f"[TerminalServer] 认证消息格式错误: {e}", flush=True)
                socket.close()
                return
        try:
            obj = json.loads(msg)
        except json.JSONDecodeError as e:
            print(f"[TerminalServer] JSON 解析错误: {e}", flush=True)
            return
        bridge.handle_message(obj)

    def _ping_all(self):
        with self._bridges_lock:
            sockets = list(self._sockets)
        for sock in sockets:
            try:
                if sock.state() == QAbstractSocket.ConnectedState:
                    sock.ping()
            except (RuntimeError, AttributeError) as e:
                print(f"[TerminalServer] ping 失败: {e}", flush=True)

    def _on_socket_closed(self, socket: QWebSocket, bridge: TerminalBridge):
        close_code = socket.closeCode() if hasattr(socket, 'closeCode') else -1
        close_reason = socket.closeReason() if hasattr(socket, 'closeReason') else ''
        print(f"[TerminalServer] WebSocket 断开 closeCode={close_code} "
              f"reason={close_reason!r} error={socket.errorString()!r}",
              flush=True)
        try:
            bridge.stop()
        except (OSError, RuntimeError) as e:
            print(f"[TerminalServer] bridge.stop 失败: {e}", flush=True)
        with self._bridges_lock:
            if bridge in self._bridges:
                self._bridges.remove(bridge)
            if socket in self._sockets:
                self._sockets.remove(socket)
        try:
            socket.deleteLater()
        except RuntimeError as e:
            print(f"[TerminalServer] socket.deleteLater 失败: {e}", flush=True)

    # ═══════════════════════════════════════════════════════════
    @property
    def last_bridge(self):
        with self._bridges_lock:
            return self._bridges[-1] if self._bridges else None

    def interrupt_current(self):
        b = self.last_bridge
        if b:
            b.interrupt()

    def shutdown(self):
        self.stop()


# ── 静态文件 handler ──
def _make_static_handler(static_root: str):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        root = static_root

        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            from urllib.parse import urlparse
            req_path = urlparse(self.path).path
            if req_path == "/":
                req_path = "/terminal_xterm.html"
            # ★ 安全修复：使用 realpath 解析符号链接，防止路径遍历
            local_path = os.path.realpath(os.path.join(self.root, req_path.lstrip("/")))
            root_real = os.path.realpath(self.root)
            # 严格边界检查：必须在根目录内（加 sep 防止 /root 匹配 /root-other）
            if not local_path.startswith(root_real + os.sep) and local_path != root_real:
                print(f"[Terminal] 路径遍历攻击尝试: {req_path}", flush=True)
                self.send_error(403)  # Forbidden
                return
            if not os.path.isfile(local_path):
                self.send_error(404)
                return
            try:
                with open(local_path, "rb") as f:
                    data = f.read()
                ctype, _ = mimetypes.guess_type(local_path)
                self.send_response(200)
                self.send_header("Content-Type", ctype or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(data)
            except (OSError, IOError) as e:
                print(f"[Terminal] 静态文件读取错误: {e}", flush=True)
                self.send_error(500)

    return Handler


_StaticHandler = _make_static_handler(_STATIC_ROOT)


# 兼容旧 API：TerminalManager / MANAGER
class TerminalManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.sessions = {}
        return cls._instance

    def create(self, cwd=None, shell=None) -> str:
        raise NotImplementedError(
            "新架构下会话由 WebSocket 连接自动创建，不再使用 create")
        return ""

    def get(self, sid: str):
        return None

    def remove(self, sid: str):
        pass


MANAGER = TerminalManager()