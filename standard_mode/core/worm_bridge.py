# -*- coding: utf-8 -*-
"""
MIMO Worm Bridge — 虫桥架构
================================================
核心思路：Agent 作为"信号发射器/接收器"，与真正运行的小米 AI MIMO Code 进行双向同步

架构设计：
┌─────────────────────────────────────────────────────────────┐
│                     MIMO Code Agent                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────────────────┐  │
│  │ 文件树  │  │ 代码区  │  │      MIMO Panel (显示层)     │  │
│  │(本地)   │  │(本地)   │  │  ┌─────────────────────────┐│  │
│  └─────────┘  └─────────┘  │  │  Worm Bridge (虫桥)     ││  │
│                            │  │  ┌───────────────────┐  ││  │
│                            │  │  │ HTTP Client       │  ││  │
│                            │  │  │ ↓ POST /message   │  ││  │
│                            │  │  │ ↑ GET /message    │  ││  │
│                            │  │  │ SSE /event        │  ││  │
│                            │  │  └───────────────────┘  ││  │
│                            │  └─────────────────────────┘│  │
│                            └─────────────────────────────┘  │
└───────────────────────────│───────────────────────────────│─┘
                            │                               │
                            │ HTTP API (localhost:9877)    │
                            ↓                               ↓
┌─────────────────────────────────────────────────────────────┐
│              小米 AI MIMO Code (ACP 服务器)                   │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  mimo acp --port=9877                                   ││
│  │  使用小米AI的XDG环境                                     ││
│  │  - 数据目录: 小米AI/node_global/data/mimocode           ││
│  │  - 配置目录: 小米AI/node_global/config/mimocode         ││
│  │  - 工作目录: 用户指定的项目路径                           ││
│  └─────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  MiMo Auto 引擎                                         ││
│  │  - 处理用户输入                                          ││
│  │  - 调用工具 (文件读写、命令执行等)                        ││
│  │  - 生成回复                                              ││
│  │  - 返回结果                                              ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘

信息同步机制：
1. 用户输入 → Agent 输入框 → Worm Bridge → POST /session/{id}/message → MIMO Code
2. MIMO Code 处理 → SSE event → Worm Bridge → Agent 输出显示
3. 文件变更 → SSE event → Worm Bridge → Agent 文件树/代码区更新

关键配置：
- XDG 目录：使用小米 AI 的 node_global 目录（共享数据）
- 项目目录：用户当前工作的项目路径
- 端口：默认 9877，可配置

启动流程：
1. Agent 启动 → 检查 ACP 是否运行
2. 若未运行 → 启动 mimo acp（使用小米 AI 的 XDG 环境）
3. 创建会话 → 连接 SSE → 等待用户输入
4. 用户输入 → 发送消息 → 接收响应 → 显示
"""

import os, sys, re, json, time, uuid, threading, subprocess, signal, logging
import urllib.request
import urllib.error
from PyQt5.QtCore import QObject, pyqtSignal, QThread, QMutex
from typing import Optional, Dict, List, Callable

# 设置调试日志
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("worm_bridge")

# ============================================================
# 路径配置 — 使用原版小米 AI MIMO Code 批处理文件
# ============================================================
_XIAOMI_AI_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "小米AI")
_MIMO_NODE_GLOBAL = os.path.join(_XIAOMI_AI_ROOT, "node_global")
MIMO_EXE = os.path.join(_MIMO_NODE_GLOBAL, "node_modules", "@mimo-ai", "mimocode-windows-x64", "bin", "mimo.exe")
MIMO_BAT = os.path.join(_MIMO_NODE_GLOBAL, "启动MIMICode.bat")  # 原版启动脚本

# XDG 目录 — 批处理文件会自动设置正确的路径（不含中文）
# 我们只需要确保目录存在
XDG_DIRS = {
    'XDG_CACHE_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'cache'),
    'XDG_DATA_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'data'),
    'XDG_STATE_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'state'),
    'XDG_CONFIG_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'config'),
}

# ============================================================
# ANSI 颜色解析
# ============================================================
ANSI_COLORS = {
    '30': 'Lemon.SYNTAX_COMMENT', '31': 'Lemon.ACCENT_RED', '32': 'Lemon.ACCENT_GREEN', '33': 'Lemon.STATUS_WARNING',
    '34': 'Lemon.ACCENT_BLUE', '35': 'Lemon.ACCENT_PURPLE', '36': 'Lemon.STATUS_RUNNING', '37': 'Lemon.PLACEHOLDER',
    '90': 'Lemon.SECONDARY', '91': 'Lemon.ACCENT_RED', '92': 'Lemon.ACCENT_GREEN', '93': 'Lemon.DARK_YELLOW_LIGHT',
    '94': 'Lemon.ACCENT_BLUE', '95': 'Lemon.ACCENT_PINK', '96': 'Lemon.STATUS_RUNNING', '97': 'Lemon.SURFACE',
}


def parse_ansi_to_html(text: str) -> str:
    """将 ANSI 转义字符转换为 HTML 样式"""
    if not text:
        return ""
    parts = re.split(r'\033\[(\d+(?:;\d+)*)m', text)
    result = []
    i = 0
    while i < len(parts):
        if i + 1 < len(parts) and parts[i + 1]:
            codes = parts[i + 1].split(';')
            color = 'Lemon.PLACEHOLDER'
            bold = False
            for code in codes:
                if code == '0':
                    color = 'Lemon.PLACEHOLDER'; bold = False
                elif code in ANSI_COLORS:
                    color = ANSI_COLORS[code]
                elif code == '1':
                    bold = True
            escaped = parts[i].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            style = f'color:{color};'
            if bold:
                style += 'font-weight:bold;'
            result.append(f'<span style="{style}">{escaped}</span>')
            i += 2
        else:
            escaped = parts[i].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            result.append(escaped)
            i += 1
    return ''.join(result)


def escape_html(text: str) -> str:
    """转义 HTML 特殊字符"""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ============================================================
# SSE 事件监听线程
# ============================================================
class SSEListener(QThread):
    """SSE 事件监听器 — 实时接收 MIMO Code 的响应"""

    event_received = pyqtSignal(str, str)    # 收到事件 (event_type, json_data)
    error_occurred = pyqtSignal(str)         # 错误

    def __init__(self, base_url: str, project_path: str, stop_event: threading.Event):
        super().__init__()
        self.base_url = base_url
        self.project_path = project_path
        self._stop_event = stop_event

    def run(self):
        url = f"{self.base_url}/event?directory={urllib.request.quote(self.project_path)}"
        log.debug(f"[SSE] 开始监听: {url}")
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})

        while not self._stop_event.is_set():
            log.debug("[SSE] 尝试连接...")
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    log.info("[SSE] 连接成功，开始读取事件")
                    buffer = ""
                    event_type = "message"
                    for line_bytes in resp:
                        if self._stop_event.is_set():
                            log.debug("[SSE] 收到停止信号，退出")
                            break
                        try:
                            line = line_bytes.decode('utf-8').rstrip()
                        except Exception as e:
                            log.warning(f"[SSE] 解码失败: {e}")
                            continue

                        if line == "":
                            # 空行表示事件结束
                            if buffer:
                                log.debug(f"[SSE] 收到事件: {event_type} | data: {buffer[:100]}...")
                                self._process_event(event_type, buffer)
                                buffer = ""
                                event_type = "message"
                        elif line.startswith("event:"):
                            event_type = line[6:].strip()
                        elif line.startswith("data:"):
                            buffer += line[5:].strip()

            except urllib.error.URLError as e:
                if not self._stop_event.is_set():
                    log.error(f"[SSE] 连接错误: {e}")
                    self.error_occurred.emit(f"SSE 连接错误: {e}")
                    time.sleep(2)  # 等待后重连
            except Exception as e:
                if not self._stop_event.is_set():
                    log.error(f"[SSE] 异常: {e}")
                    self.error_occurred.emit(f"SSE 异常: {e}")
                    time.sleep(2)
        log.info("[SSE] 监听线程结束")

    def _process_event(self, event_type: str, data: str):
        """处理 SSE 事件，发送字符串信号"""
        self.event_received.emit(event_type, data)


# ============================================================
# Worm Bridge — 虫桥核心
# ============================================================
class WormBridge(QObject):
    """
    MIMO Worm Bridge — 虫桥

    负责连接 Agent 和小米 AI MIMO Code，实现双向信息同步：
    - 启动/管理 ACP 服务器进程
    - 创建/管理会话
    - 发送用户消息
    - 接收 MIMO Code 响应（通过 SSE）
    - 处理文件变更通知
    """

    # PyQt 信号
    connected = pyqtSignal(int)            # 连接成功 (port)
    disconnected = pyqtSignal()            # 连接断开
    server_started = pyqtSignal()          # ACP 服务器启动
    session_created = pyqtSignal(str)      # 会话创建 (session_id)

    output_received = pyqtSignal(str)      # 收到普通输出 (HTML)
    thinking_received = pyqtSignal(str)    # 收到思考过程 (HTML)
    tool_output_received = pyqtSignal(str) # 收到工具输出 (HTML)
    error_received = pyqtSignal(str)       # 收到错误信息 (纯文本)

    files_changed = pyqtSignal(list)       # 文件变更列表
    task_started = pyqtSignal(str)         # 任务开始
    task_finished = pyqtSignal(int)        # 任务完成 (exit_code)

    def __init__(self, project_path: str = None, port: int = 9877):
        super().__init__()
        self.project_path = os.path.abspath(project_path or os.getcwd())
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"

        self._acp_process: Optional[subprocess.Popen] = None
        self._session_id: Optional[str] = None
        self._sse_thread: Optional[SSEListener] = None
        self._stop_event = threading.Event()
        self._running = False
        self._mutex = QMutex()

        # 确保目录存在
        for key, path in XDG_DIRS.items():
            os.makedirs(os.path.join(path, 'mimocode'), exist_ok=True)

    # ================================================================
    # ACP 服务器管理
    # ================================================================
    def start_acp_server(self) -> bool:
        """启动 ACP 服务器（使用小米 AI 的 XDG 环境）"""
        log.info(f"[虫桥] 启动 ACP 服务器, port={self.port}, project={self.project_path}")

        # 先检查是否已经有 ACP 服务器在运行
        if self._check_server_health():
            log.info("[虫桥] ACP 服务器已在运行，直接连接")
            # 启动小米 AI 的 MIMO Code GUI（后台运行）
            self._launch_xiaomi_ai_background()
            self._start_sse_listener()
            if not self._create_session():
                log.error("[虫桥] 会话创建失败")
                self.error_received.emit("会话创建失败")
                return False
            self.server_started.emit()
            self.connected.emit(self.port)
            return True

        # 清理可能存在的旧进程（避免端口冲突）—— 但只在确定没有服务运行时
        self._cleanup_old_mimo_processes()

        # 启动小米 AI 的 MIMO Code GUI（后台运行）
        self._launch_xiaomi_ai_background()

        # 构建环境变量
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'  # 确保 Python 输出编码
        env['LANG'] = 'en_US.UTF-8'  # 设置系统语言环境
        for key, path in XDG_DIRS.items():
            # 确保路径正确，避免编码问题
            abs_path = os.path.abspath(path)
            env[key] = abs_path
            os.makedirs(abs_path, exist_ok=True)
            os.makedirs(os.path.join(abs_path, 'mimocode'), exist_ok=True)
            log.debug(f"[虫桥] XDG: {key}={abs_path}")

        # 启动进程
        try:
            # 使用 CREATE_NO_WINDOW 标志，避免弹出命令行窗口
            CREATE_NO_WINDOW = 0x08000000

            # 使用原版批处理文件启动 ACP（批处理文件会设置正确的 XDG 目录）
            if os.path.exists(MIMO_BAT):
                log.debug(f"[虫桥] 启动命令: {MIMO_BAT} acp --port={self.port}")
                self._acp_process = subprocess.Popen(
                    ["cmd.exe", "/c", MIMO_BAT, "acp", f"--port={self.port}"],
                    cwd=self.project_path,
                    creationflags=CREATE_NO_WINDOW,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                )
            else:
                # 后备方案：直接启动 mimo.exe
                log.warning(f"[虫桥] 批处理文件不存在: {MIMO_BAT}")
                log.debug(f"[虫桥] 启动命令: {MIMO_EXE} acp --port={self.port}")
                self._acp_process = subprocess.Popen(
                    [MIMO_EXE, "acp", f"--port={self.port}"],
                    cwd=self.project_path,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    creationflags=CREATE_NO_WINDOW,
                )
            log.info(f"[虫桥] 进程已启动, PID={self._acp_process.pid}")
        except Exception as e:
            log.error(f"[虫桥] ACP 启动失败: {e}")
            self.error_received.emit(f"ACP 启动失败: {e}")
            return False

        # 等待服务器就绪
        log.debug("[虫桥] 等待服务器就绪...")
        if not self._wait_for_server(timeout=60):  # 增加超时时间到 60 秒
            log.error("[虫桥] ACP 服务器启动超时")
            self.error_received.emit("ACP 服务器启动超时")
            self._cleanup_process()
            return False
        log.info("[虫桥] ACP 服务器已就绪")

        # 启动 SSE 监听
        log.debug("[虫桥] 启动 SSE 监听...")
        self._start_sse_listener()

        # 创建会话
        log.debug("[虫桥] 创建会话...")
        if not self._create_session():
            log.error("[虫桥] 会话创建失败")
            self.error_received.emit("会话创建失败")
            self.stop_acp_server()
            return False
        log.info(f"[虫桥] 会话已创建: {self._session_id}")

        self.server_started.emit()
        self.connected.emit(self.port)
        log.info("[虫桥] 启动完成")
        return True

    def _cleanup_old_mimo_processes(self):
        """清理可能存在的旧 mimo 进程，避免端口冲突"""
        try:
            # 在 Windows 上查找并终止 mimo 进程
            import signal
            result = subprocess.run(
                ["taskkill", "/F", "/IM", "mimo.exe"],
                capture_output=True,
                text=True,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                log.info("[虫桥] 已清理旧的 mimo 进程")
                time.sleep(2)  # 等待进程完全退出
        except Exception as e:
            log.warning(f"[虫桥] 清理进程时出错: {e}")

    def _launch_xiaomi_ai_background(self):
        """启动小米 AI MIMO Code GUI（前台可见窗口）— 模拟双击启动"""
        if os.path.exists(MIMO_BAT):
            try:
                # 使用 os.startfile 模拟双击启动（最接近用户手动双击的效果）
                # 这会启动批处理文件，MIMO Code GUI 会作为独立窗口显示
                os.startfile(MIMO_BAT)
                log.info(f"[虫桥] 小米 AI MIMO Code GUI 已启动（模拟双击）: {MIMO_BAT}")
                # 等待 GUI 启动
                time.sleep(3)
            except Exception as e:
                log.warning(f"[虫桥] 启动小米 AI GUI 失败: {e}")
                # 后备方案：使用 subprocess
                try:
                    subprocess.Popen(
                        ["cmd.exe", "/c", MIMO_BAT],
                        cwd=_MIMO_NODE_GLOBAL,
                    )
                    log.info(f"[虫桥] 小米 AI MIMO Code GUI 已启动（后备方案）")
                    time.sleep(3)
                except Exception as e2:
                    log.warning(f"[虫桥] 后备启动也失败: {e2}")
        else:
            log.warning(f"[虫桥] 批处理文件不存在: {MIMO_BAT}")

    def _check_server_health(self) -> bool:
        """检查服务器是否运行"""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/global/health",
                headers={"Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _wait_for_server(self, timeout: int = 30) -> bool:
        """等待服务器就绪"""
        start = time.time()
        while time.time() - start < timeout:
            if self._acp_process and self._acp_process.poll() is not None:
                return False
            if self._check_server_health():
                return True
            time.sleep(0.5)
        return False

    def stop_acp_server(self):
        """停止 ACP 服务器"""
        self._stop_event.set()

        if self._sse_thread and self._sse_thread.isRunning():
            self._sse_thread.quit()
            self._sse_thread.wait(3000)

        self._cleanup_process()

        self._session_id = None
        self.disconnected.emit()

    def _cleanup_process(self):
        """清理进程"""
        if self._acp_process:
            try:
                # Windows 下尝试优雅终止
                self._acp_process.terminate()
                self._acp_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    self._acp_process.kill()
                except Exception:
                    pass
            except Exception:
                pass
            self._acp_process = None

    # ================================================================
    # SSE 监听
    # ================================================================
    def _start_sse_listener(self):
        """启动 SSE 监听线程"""
        self._stop_event.clear()
        self._sse_thread = SSEListener(self.base_url, self.project_path, self._stop_event)

        # 连接信号
        self._sse_thread.event_received.connect(self._on_event_received)
        self._sse_thread.error_occurred.connect(self.error_received)

        self._sse_thread.start()

    def _on_event_received(self, event_type: str, json_data: str):
        """处理收到的 SSE 事件"""
        log.debug(f"[虫桥] 收到事件: {event_type}")
        try:
            event_data = json.loads(json_data)

            if event_type == "message.part.updated":
                part = event_data.get("part", {})
                part_type = part.get("type", "")
                text = part.get("text", "")

                if not text:
                    return

                log.debug(f"[虫桥] part.updated: type={part_type}, text={text[:50]}...")
                html = parse_ansi_to_html(text)

                if part_type == "reasoning":
                    log.debug("[虫桥] 发送思考信号")
                    self.thinking_received.emit(html)
                elif part_type == "text":
                    log.debug("[虫桥] 发送输出信号")
                    self.output_received.emit(html)
                elif part_type in ("tool-call", "tool"):
                    tool_json = json.dumps(part, ensure_ascii=False, indent=2)
                    self.tool_output_received.emit(f"<pre style='font-size:11px;color:Lemon.ACCENT_BLUE;'>{escape_html(tool_json)}</pre>")

            elif event_type == "session.diff":
                changes = event_data.get("changes", [])
                log.debug(f"[虫桥] session.diff: {len(changes)} 个变更")
                if changes:
                    self.files_changed.emit(changes)

            elif event_type == "message.updated":
                log.debug("[虫桥] message.updated")
                pass  # 消息状态更新

        except json.JSONDecodeError as e:
            log.warning(f"[虫桥] JSON 解析失败: {e}")
        except Exception as e:
            log.error(f"[虫桥] 事件处理错误: {e}")
            self.error_received.emit(f"事件解析错误: {e}")

    # ================================================================
    # 会话管理
    # ================================================================
    def _create_session(self) -> bool:
        """创建新会话"""
        result = self._api_request("POST", "/session", {"title": "MIMO Agent Session"})
        if result:
            self._session_id = result.get("id") or result.get("sessionID")
            if self._session_id:
                self.session_created.emit(self._session_id)
                return True

        # 尝试获取现有会话
        sessions = self._api_request("GET", "/session")
        if sessions and isinstance(sessions, list) and len(sessions) > 0:
            self._session_id = sessions[0].get("id") or sessions[0].get("sessionID")
            if self._session_id:
                self.session_created.emit(self._session_id)
                return True

        return False

    def get_session_id(self) -> Optional[str]:
        """获取当前会话 ID"""
        return self._session_id

    # ================================================================
    # HTTP API 请求
    # ================================================================
    def _api_request(self, method: str, path: str, body: dict = None) -> Optional[dict]:
        """发送 HTTP API 请求"""
        url = f"{self.base_url}{path}?directory={urllib.request.quote(self.project_path)}"

        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')

        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_data = resp.read().decode('utf-8')
                if resp_data:
                    return json.loads(resp_data)
                return {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')
            self.error_received.emit(f"HTTP {e.code}: {err_body[:200]}")
            return None
        except Exception as e:
            self.error_received.emit(f"请求失败: {e}")
            return None

    # ================================================================
    # 发送消息
    # ================================================================
    def send_message(self, text: str) -> bool:
        """发送消息到 MIMO Code"""
        log.info(f"[虫桥] 发送消息: {text[:50]}...")
        if not self._session_id:
            log.error("[虫桥] 未连接到 MIMO Code")
            self.error_received.emit("未连接到 MIMO Code")
            return False

        self._running = True
        self.task_started.emit(text)

        # 在后台线程发送
        threading.Thread(target=self._send_message_thread, args=(text,), daemon=True).start()
        return True

    def _send_message_thread(self, text: str):
        """发送消息的后台线程"""
        message_id = "msg_" + uuid.uuid4().hex
        log.debug(f"[虫桥] message_id: {message_id}")

        body = {
            "messageID": message_id,
            "parts": [{"type": "text", "text": text}]
        }

        log.debug(f"[虫桥] POST /session/{self._session_id}/message")
        result = self._api_request("POST", f"/session/{self._session_id}/message", body)

        if result is None:
            log.error("[虫桥] 发送失败")
            self._running = False
            self.task_finished.emit(-1)
            return

        log.info(f"[虫桥] 发送成功, 响应: {str(result)[:100]}...")
        # 轮询等待消息完成
        self._poll_message_completion(message_id)

    def _poll_message_completion(self, message_id: str, timeout: int = 300):
        """轮询消息直到完成"""
        log.debug(f"[虫桥] 开始轮询: {message_id}")
        start = time.time()

        while time.time() - start < timeout:
            if self._stop_event.is_set():
                log.debug("[虫桥] 轮询被中断")
                break

            time.sleep(0.5)

            result = self._api_request("GET", f"/session/{self._session_id}/message/{message_id}")
            if result is None:
                continue

            parts = result.get("parts", [])
            # 检查是否有 step-finish（表示完成）
            has_finish = any(p.get("type") == "step-finish" for p in parts)
            if has_finish:
                break

        self._running = False
        self.task_finished.emit(0)

    # ================================================================
    # 状态查询
    # ================================================================
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._session_id is not None and self._check_server_health()

    def is_running(self) -> bool:
        """是否有任务运行"""
        return self._running

    def cancel(self):
        """取消当前任务"""
        self._stop_event.set()
        self._running = False
        if self._session_id:
            threading.Thread(
                target=lambda: self._api_request("POST", f"/session/{self._session_id}/abort"),
                daemon=True
            ).start()

    def cleanup(self):
        """清理所有资源"""
        self.cancel()
        self.stop_acp_server()