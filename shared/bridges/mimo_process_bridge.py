# -*- coding: utf-8 -*-
"""
MIMO Process Bridge v9 — 纯 subprocess，零 serve，零 HTTP
==========================================================
架构：
  mimo run --session <id> --format json "message"
  → 子进程独立运行，不依赖 mimo serve
  → 首次自动创建 session（从 step_start 提取 sessionID）
  → 后续复用 --session 维持上下文

已验证：
  MSG1: mimo run --format json "你好" → 自动创建 session ses_xxx
  MSG2: mimo run --session ses_xxx --format json "我刚才问了什么？"
    → 正确回答 "你好，请用一句话介绍你自己"
  ✓ 上下文记忆成功，全程零 HTTP，零 serve
"""

import os
import sys
import json
import time
import queue
import subprocess
import threading
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

from PyQt5.QtCore import QObject, pyqtSignal, QThread

# ★ v3.72: 共享 Markdown 转换工具
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'utils'))
try:
    from markdown_utils import markdown_to_html
    print(f"[ProcessBridge] markdown_utils 导入成功, markdown_to_html={markdown_to_html}", flush=True)
except ImportError as e:
    markdown_to_html = None
    print(f"[ProcessBridge] markdown_utils 导入失败: {e}", flush=True)


# MIMO Code 可执行文件路径 — 优先使用 lemon_agent\bin\mimo.exe
_MIMO_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "lemon_agent"
)
MIMO_EXE = os.path.join(_MIMO_ROOT, "bin", "mimo.exe")

# 回退路径
if not os.path.exists(MIMO_EXE):
    MIMO_EXE = os.path.expanduser(r"~\AppData\Local\Programs\@mimo-ai\mimocode-windows-x64\bin\mimo.exe")

_STDIO_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "mimo-gui", "electron-stdio.js"),
    os.path.join(os.getcwd(), "mimo-gui", "electron-stdio.js"),
    os.path.expanduser("~/小米AI/mimo-gui/electron-stdio.js"),
]
_STDIO_BRIDGE_JS = next((p for p in _STDIO_CANDIDATES if os.path.exists(p)), None)
if _STDIO_BRIDGE_JS is None:
    logger.error("[ProcessBridge] STDIO 桥脚本未找到，候选: %s；将禁用 STDIO 模式回退本地引擎", _STDIO_CANDIDATES)

SUBPROCESS_TIMEOUT = 120  # 单次 run 超时（秒）


class _RunWorker(QThread):
    """subprocess 工作线程 — 带超时保护的 stdout 读取"""

    line_received = pyqtSignal(str)
    run_finished = pyqtSignal(int)
    run_error = pyqtSignal(str)
    run_timeout = pyqtSignal()

    def __init__(self, args: list, env: dict, cwd: str, timeout: int = SUBPROCESS_TIMEOUT, parent=None):
        super().__init__(parent)
        self._args = args
        self._env = env
        self._cwd = cwd
        self._timeout = timeout
        self._proc: Optional[subprocess.Popen] = None
        self._stopped = False

    def run(self):
        try:
            self._proc = subprocess.Popen(
                self._args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=self._cwd,
                env=self._env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )

            print(f"[RunWorker] 进程已启动 PID={self._proc.pid}", flush=True)

            output_queue = queue.Queue()

            def _reader():
                try:
                    for line in self._proc.stdout:
                        if self._stopped:
                            break
                        output_queue.put(line.rstrip('\n\r'))
                except Exception as e:
                    print(f"[RunWorker] reader 异常: {e}", flush=True)
                output_queue.put(None)

            reader_thread = threading.Thread(target=_reader, daemon=True)
            reader_thread.start()

            start_time = time.time()
            while True:
                try:
                    line = output_queue.get(timeout=1.0)
                    if line is None:
                        break
                    if line:
                        self.line_received.emit(line)
                except queue.Empty:
                    elapsed = time.time() - start_time
                    if elapsed > self._timeout:
                        print(f"[RunWorker] 超时 ({self._timeout}s)", flush=True)
                        self._stopped = True
                        if self._proc and self._proc.poll() is None:
                            self._proc.kill()
                        self.run_timeout.emit()
                        return

            reader_thread.join(timeout=3)
            self._proc.wait()
            print(f"[RunWorker] 进程退出 code={self._proc.returncode}", flush=True)
            if not self._stopped:
                self.run_finished.emit(self._proc.returncode)

        except Exception as e:
            print(f"[RunWorker] 启动异常: {e}", flush=True)
            self.run_error.emit(str(e))
            self.run_finished.emit(-1)

    def stop(self):
        self._stopped = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:
                pass


class _StdioBridgeWorker(QThread):
    """
    STDIO Bridge 持久化工作线程 — v8 新增
    ======================================
    使用 node electron-stdio.js --stdio 作为持久化子进程，
    通过 stdin/stdout JSON 行协议通信，支持：
    - 持久连接（无需每次消息启动新进程）
    - Skill 注入（通过 skill_invoke 消息类型）
    - 心跳检测（ping/pong）
    - 多会话管理
    """

    response_received = pyqtSignal(str)  # 完整 JSON 响应行
    worker_error = pyqtSignal(str)
    worker_ready = pyqtSignal()
    worker_closed = pyqtSignal(int)

    def __init__(self, node_exe: str, bridge_js: str, parent=None):
        super().__init__(parent)
        self._node_exe = node_exe
        self._bridge_js = bridge_js
        self._proc: Optional[subprocess.Popen] = None
        self._stopped = False
        self._ready = False

    def run(self):
        try:
            # 查找 node.exe
            node_exe = self._node_exe
            # ★ v3.72: 使用 shutil.which 查找 PATH 中的 node，避免 os.path.exists("node") 失败
            import shutil
            if not os.path.exists(node_exe):
                resolved = shutil.which(node_exe) or shutil.which("node")
                if resolved:
                    node_exe = resolved
            if not os.path.exists(node_exe):
                # 尝试常见路径（★ 保留 D:\小米AI\node.exe —— 本机实测 node 真实位置，勿删）
                for p in [r"D:\小米AI\node.exe",
                          r"C:\Program Files\nodejs\node.exe",
                          r"C:\Program Files (x86)\nodejs\node.exe"]:
                    if os.path.exists(p):
                        node_exe = p
                        break

            if not os.path.exists(node_exe):
                self.worker_error.emit(f"Node.js 不可用: {node_exe}")
                return

            if not os.path.exists(self._bridge_js):
                self.worker_error.emit(f"STDIO Bridge 脚本不存在: {self._bridge_js}")
                return

            self._proc = subprocess.Popen(
                [node_exe, self._bridge_js, "--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )

            print(f"[StdioBridge] 进程已启动 PID={self._proc.pid}", flush=True)

            # 启动 stderr 读取线程
            def _read_stderr():
                try:
                    for line in self._proc.stderr:
                        if self._stopped:
                            break
                        if line.strip():
                            print(f"[StdioBridge/stderr] {line.rstrip()}", flush=True)
                except Exception:
                    pass

            stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
            stderr_thread.start()

            # 读取 stdout 行
            for line in self._proc.stdout:
                if self._stopped:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                    if not self._ready and parsed.get("type") == "status" and parsed.get("status") == "ready":
                        self._ready = True
                        self.worker_ready.emit()
                    self.response_received.emit(line)
                except json.JSONDecodeError:
                    # 非 JSON 行，记录
                    print(f"[StdioBridge] 非JSON: {line[:100]}", flush=True)

            self._proc.wait()
            print(f"[StdioBridge] 进程退出 code={self._proc.returncode}", flush=True)
            if not self._stopped:
                self.worker_closed.emit(self._proc.returncode)

        except Exception as e:
            print(f"[StdioBridge] 异常: {e}", flush=True)
            self.worker_error.emit(str(e))

    def send_line(self, line: str):
        """发送一行 JSON 消息到子进程 stdin"""
        if self._proc and self._proc.stdin and not self._stopped:
            try:
                self._proc.stdin.write(line.strip() + "\n")
                self._proc.stdin.flush()
                return True
            except Exception as e:
                print(f"[StdioBridge] 发送失败: {e}", flush=True)
                self.worker_error.emit(f"发送失败: {e}")
        return False

    def is_ready(self) -> bool:
        return self._ready and not self._stopped

    def stop(self):
        self._stopped = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:
                pass


class MIMOProcessBridge(QObject):
    """
    MIMO Process Bridge v9 — 纯 subprocess，零 serve，零 HTTP
    ========================================================
    
    支持两种模式：
    1. 直接模式（默认）：mimo run --format json "message"（每次新建进程）
    2. STDIO 桥接模式：node electron-stdio.js --stdio（持久化进程，支持 Skill 注入）

    工作流程：
    1. start() → 检查 mimo.exe 是否存在，可选启动 STDIO 桥接
    2. send_message("msg1") → 根据模式路由到 _send_via_run 或 _send_via_stdio
       → 自动创建 session，从 step_start 提取 sessionID
    3. send_message("msg2") → 复用 session，上下文记忆

    v9 新增：
    - _send_via_run() 方法：提取直接模式逻辑，消除死代码
    - _send_via_stdio() 方法：JSON 行协议通信，支持上下文传递
    - send_skill_invoke() 方法：通过 STDIO 桥接注入 Skill 调用
    - _on_message_complete() 方法：STDIO 模式消息完成处理
    - stream 事件处理：流式输出，追加到上下文
    - 多会话管理：create_session / switch_session / list_sessions
    """

    # 输出信号
    output_received = pyqtSignal(str)
    thinking_received = pyqtSignal(str)
    status_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    task_started = pyqtSignal(str)
    task_finished = pyqtSignal(int)
    raw_output = pyqtSignal(str)
    session_created = pyqtSignal(str)
    skill_result = pyqtSignal(str)  # v8: Skill 执行结果
    tool_output = pyqtSignal(str)  # v3.73: 工具调用输出（可折叠区域）
    file_preview = pyqtSignal(str)  # v3.90: 文件预览（HTML iframe/图像/代码内嵌）

    def __init__(self, project_path: str = None, use_stdio_bridge: bool = False):
        super().__init__()
        self.project_path = os.path.abspath(project_path or os.getcwd())
        self._run_worker: Optional[_RunWorker] = None
        self._stdio_worker: Optional[_StdioBridgeWorker] = None
        self._running = False
        self._session_id: Optional[str] = None
        self._context: List[Dict] = []
        self._message_count = 0
        self._failure_count = 0
        self._run_busy = False
        self._run_output_buffer = ""
        self._use_stdio_bridge = use_stdio_bridge
        self._stdio_ready = False
        self._pending_skills: List[str] = []
        self._saved_contexts: Dict[str, List[Dict]] = {}  # v9: 多会话上下文存储

    @staticmethod
    def _mimo_exe_path() -> str:
        """返回 MIMO Code 可执行文件的完整路径（兼容旧代码调用）"""
        return MIMO_EXE

    # ==================== 生命周期 ====================

    def is_running(self) -> bool:
        return self._running

    @property
    def is_busy(self) -> bool:
        return self._run_busy

    @property
    def has_session(self) -> bool:
        return self._session_id is not None

    def clear_context(self):
        self._context.clear()

    def get_context(self, n: int = None) -> List[Dict]:
        if n:
            return self._context[-n:]
        return self._context.copy()

    def get_context_turns(self) -> int:
        return len(self._context) // 2

    # ==================== 多会话管理（v9） ====================

    def create_session(self, name: str = None) -> str:
        """
        创建新会话 — 保存当前上下文，新建空白会话

        返回新会话的 session_id（MIMO 真实 ID 在首次通信后自动获取）
        """
        # 保存当前会话上下文
        if self._session_id and self._context:
            self._saved_contexts[self._session_id] = self._context.copy()

        # 创建新会话
        self._session_id = None
        self._context = []
        self._message_count = 0
        self._failure_count = 0
        self._run_busy = False

        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_BLUE;'>[MIMO] 新会话已创建"
            + (f" ({name})" if name else "")
            + "</span>"
        )
        self.raw_output.emit(f"--- 新会话" + (f": {name}" if name else "") + " ---\n")
        return ""

    def switch_session(self, session_id: str) -> bool:
        """
        切换到指定会话 — 保存当前上下文，加载目标会话上下文

        session_id: MIMO 真实 session ID（ses_ 开头）或已保存的会话 ID
        """
        if not session_id:
            return False

        # 保存当前会话上下文
        if self._session_id and self._context:
            self._saved_contexts[self._session_id] = self._context.copy()

        # 加载目标会话
        if session_id in self._saved_contexts:
            self._context = self._saved_contexts[session_id].copy()
            self._session_id = session_id
            self._message_count = len([c for c in self._context if c.get("role") == "user"])
            self.status_received.emit(
                f"<span style='color:Lemon.ACCENT_GREEN;'>[MIMO] 切换到会话: {session_id[:16]}..."
                f" ({self._message_count} 轮对话)</span>"
            )
            self.raw_output.emit(f"--- 切换到会话: {session_id[:16]}... ---\n")
            return True
        else:
            self.error_occurred.emit(
                f"<span style='color:Lemon.ACCENT_RED;'>会话不存在: {session_id[:16]}...</span>"
            )
            return False

    def list_sessions(self) -> List[Dict]:
        """列出所有已保存的会话"""
        sessions = []
        # 当前会话
        if self._session_id:
            sessions.append({
                "session_id": self._session_id,
                "turns": len(self._context) // 2,
                "active": True,
            })
        # 已保存的会话
        for sid, ctx in self._saved_contexts.items():
            if sid != self._session_id:
                sessions.append({
                    "session_id": sid,
                    "turns": len(ctx) // 2,
                    "active": False,
                })
        return sessions

    def get_status(self) -> Dict:
        return {
            "running": self._running,
            "session_id": self._session_id,
            "message_count": self._message_count,
            "context_turns": len(self._context) // 2,
            "saved_sessions": len(self._saved_contexts),
            "failure_count": self._failure_count,
            "exe_exists": os.path.exists(MIMO_EXE),
            "run_busy": self._run_busy,
            "stdio_ready": self._stdio_ready,
            "use_stdio": self._use_stdio_bridge,
        }

    def _get_env(self) -> Dict:
        return {
            "XDG_CACHE_HOME": os.path.join(_MIMO_ROOT, "cache"),
            "XDG_DATA_HOME": os.path.join(_MIMO_ROOT, "data"),
            "XDG_STATE_HOME": os.path.join(_MIMO_ROOT, "state"),
            "XDG_CONFIG_HOME": os.path.join(_MIMO_ROOT, "config"),
        }

    def start(self) -> bool:
        """初始化 Bridge — 检查 mimo.exe 是否存在，可选启动 STDIO 桥接"""
        if self._running:
            self.status_received.emit(
                "<span style='color:Lemon.ACCENT_BLUE;'>[MIMO] Bridge 已在运行中</span>"
            )
            return True

        if not os.path.exists(MIMO_EXE):
            err = f"MIMO Code 可执行文件不存在: {MIMO_EXE}"
            self.error_occurred.emit(f"<span style='color:Lemon.ACCENT_RED;'>\u274c {err}</span>")
            return False

        self._running = True

        if self._use_stdio_bridge:
            return self._start_stdio_mode()
        else:
            self.status_received.emit(
                "<span style='color:Lemon.ACCENT_GREEN;'>[MIMO] Process Bridge v8 就绪（纯 subprocess，零 serve）</span>"
            )
            self.raw_output.emit("MIMO Process Bridge v8 (纯 subprocess) 启动成功\n")
            return True

    def _start_stdio_mode(self) -> bool:
        """启动 STDIO 桥接模式 — 持久化 node electron-stdio.js 进程"""
        if not _STDIO_BRIDGE_JS or not os.path.exists(_STDIO_BRIDGE_JS):
            self.raw_output.emit("<span style='color:#f55;'>✗ STDIO 桥脚本缺失，已回退本地引擎</span>")
            self._running = False
            return False

        # 查找 node.exe（★ 保留 D:\小米AI\node.exe —— 本机实测 node 真实位置，勿删）
        import shutil
        node_exe = shutil.which("node") or "node"
        for p in [r"D:\小米AI\node.exe",
                  r"C:\Program Files\nodejs\node.exe",
                  r"C:\Program Files (x86)\nodejs\node.exe"]:
            if os.path.exists(p):
                node_exe = p
                break

        self._stdio_worker = _StdioBridgeWorker(node_exe, _STDIO_BRIDGE_JS)
        self._stdio_worker.response_received.connect(self._on_stdio_response)
        self._stdio_worker.worker_error.connect(self._on_stdio_error)
        self._stdio_worker.worker_ready.connect(self._on_stdio_ready)
        self._stdio_worker.worker_closed.connect(self._on_stdio_closed)
        self._stdio_worker.start()

        self.status_received.emit(
            "<span style='color:Lemon.ACCENT_BLUE;'>[MIMO] STDIO Bridge v8 启动中...</span>"
        )
        self.raw_output.emit("MIMO STDIO Bridge v8 (持久化进程) 启动中...\n")
        return True

    def _on_stdio_ready(self):
        """STDIO 桥接就绪"""
        self._stdio_ready = True
        self.status_received.emit(
            "<span style='color:Lemon.ACCENT_GREEN;'>[MIMO] STDIO Bridge v8 就绪（持久化进程 + Skill 注入）</span>"
        )
        self.raw_output.emit("STDIO Bridge 就绪\n")

    def _on_stdio_response(self, line: str):
        """处理 STDIO 桥接的 JSON 响应"""
        self._parse_json_line(line)

    def _on_stdio_error(self, error: str):
        """STDIO 桥接错误"""
        self.error_occurred.emit(
            f"<span style='color:Lemon.ACCENT_RED;'>\u274c [STDIO] {error}</span>"
        )

    def _on_stdio_closed(self, code: int):
        """STDIO 桥接关闭"""
        self._stdio_ready = False
        self.status_received.emit(
            f"<span style='color:#888;'>[MIMO] STDIO Bridge 已关闭 (code={code})</span>"
        )
        if self._running:
            self._running = False

    def stop(self):
        """停止所有资源"""
        if self._run_worker and self._run_worker.isRunning():
            self._run_worker.stop()
            self._run_worker.wait(5000)
        self._run_worker = None

        if self._stdio_worker and self._stdio_worker.isRunning():
            self._stdio_worker.stop()
            self._stdio_worker.wait(5000)
        self._stdio_worker = None

        self._run_busy = False
        self._stdio_ready = False
        self._running = False
        self._session_id = None
        self._context.clear()
        self._saved_contexts.clear()
        self._message_count = 0
        self._failure_count = 0

        self.status_received.emit(
            "<span style='color:#888;'>[MIMO] Bridge 已停止</span>"
        )

    # ==================== 消息发送 ====================

    def send_message(self, message: str, skills: List[str] = None) -> bool:
        """
        发送消息到 MIMO Code（纯 subprocess，零 serve）

        直接模式: mimo run --format json "msg" → 每次新建进程
        持久模式: STDIO bridge → 持久化进程，支持 Skill 注入
        """
        if not self._running:
            self.error_occurred.emit(
                "<span style='color:Lemon.ACCENT_RED;'>\u274c Bridge 未就绪</span>"
            )
            return False

        if self._run_busy:
            self.error_occurred.emit(
                "<span style='color:Lemon.ACCENT_RED;'>\u274c 上一个消息仍在处理中</span>"
            )
            return False

        # 路由到对应通信模式
        if self._use_stdio_bridge and self._stdio_ready:
            return self._send_via_stdio(message, skills or [])
        else:
            return self._send_via_run(message, skills or [])

    def _send_via_run(self, message: str, skills: List[str] = None) -> bool:
        """
        直接模式发送 — mimo run --format json "msg"（每次新建进程）

        工作流程：
        1. 递增消息计数，标记 busy
        2. 发射 task_started / status_received / raw_output 信号
        3. 添加用户消息到上下文
        4. 构建 mimo run 命令并启动子进程
        """
        self._message_count += 1
        self._run_busy = True
        self._run_output_buffer = ""
        self.task_started.emit(message)

        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_BLUE;'>[MIMO] #{self._message_count}: "
            f"{message[:60]}...</span>"
        )
        self.raw_output.emit(f"\n--- 消息 #{self._message_count} ---\n> {message}\n")
        self._context.append({"role": "user", "content": message})

        # 构建 mimo run 命令（零 serve，纯子进程）
        args = [MIMO_EXE, "run"]
        if self._session_id:
            args.extend(["--session", self._session_id])
        args.extend([
            "--format", "json",
            "--dangerously-skip-permissions",
            message,
        ])

        session_info = f"--session {self._session_id[:16]}..." if self._session_id else "(自动创建)"
        self.raw_output.emit(
            f"$ mimo run {session_info} --format json \"{message[:50]}...\"\n"
        )

        subprocess_env = os.environ.copy()
        for key, val in self._get_env().items():
            subprocess_env[key] = val

        # ★ 关键修复：cwd 必须是 mimo.exe 所在目录（bin/），而非用户项目目录
        # mimo.exe 需要从自己的 bin/ 目录启动才能找到内部资源（Node.js 运行时等）
        mimo_dir = os.path.dirname(MIMO_EXE)
        self._run_worker = _RunWorker(args, subprocess_env, mimo_dir)
        self._run_worker.line_received.connect(self._on_run_line)
        self._run_worker.run_finished.connect(self._on_run_finished)
        self._run_worker.run_error.connect(self._on_run_error)
        self._run_worker.run_timeout.connect(self._on_run_timeout)
        self._run_worker.start()

        return True

    def _send_via_stdio(self, message: str, skills: List[str] = None) -> bool:
        """
        STDIO 持久化模式发送 — 通过 node electron-stdio.js --stdio 进程通信

        使用自定义 JSON 协议（而非 --format json）：
        - 支持持久连接（无需每次消息启动新进程）
        - 支持 Skill 注入（通过 skill_invoke 消息类型）
        - 支持上下文传递（携带完整 conversation history）

        协议格式：
        {"type":"chat","session_id":"xxx","message":"...","context":[...],"skills":[...]}
        """
        if not self._stdio_worker or not self._stdio_worker.is_ready():
            self.error_occurred.emit(
                "<span style='color:Lemon.ACCENT_RED;'>\u274c STDIO Bridge 未就绪</span>"
            )
            return False

        self._message_count += 1
        self._run_busy = True
        self._run_output_buffer = ""
        self.task_started.emit(message)

        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_BLUE;'>[MIMO/STDIO] #{self._message_count}: "
            f"{message[:60]}...</span>"
        )
        self.raw_output.emit(f"\n--- 消息 #{self._message_count} (STDIO) ---\n> {message}\n")
        self._context.append({"role": "user", "content": message})

        # 构建自定义 JSON 协议消息
        payload = {
            "type": "chat",
            "session_id": self._session_id or "",
            "message": message,
            "context": self._context[-10:],  # 携带最近10轮上下文
            "skills": skills or [],
        }

        json_line = json.dumps(payload, ensure_ascii=False)
        self.raw_output.emit(f"[STDIO] send: {json_line[:200]}...\n")

        if self._stdio_worker.send_line(json_line):
            return True
        else:
            self._run_busy = False
            self.error_occurred.emit(
                "<span style='color:Lemon.ACCENT_RED;'>\u274c STDIO 发送失败</span>"
            )
            return False

    def send_skill_invoke(self, skill_id: str, params: Dict = None) -> bool:
        """
        v8: 通过 STDIO 桥接注入 Skill 调用

        协议：
        {"type":"skill_invoke","session_id":"xxx","skill_id":"xxx","params":{...}}
        """
        if not self._use_stdio_bridge or not self._stdio_ready:
            self.error_occurred.emit(
                "<span style='color:Lemon.ACCENT_RED;'>\u274c Skill 注入需要 STDIO 桥接模式</span>"
            )
            return False

        if not self._stdio_worker or not self._stdio_worker.is_ready():
            self.error_occurred.emit(
                "<span style='color:Lemon.ACCENT_RED;'>\u274c STDIO Bridge 未就绪</span>"
            )
            return False

        payload = {
            "type": "skill_invoke",
            "session_id": self._session_id or "",
            "skill_id": skill_id,
            "params": params or {},
        }

        json_line = json.dumps(payload, ensure_ascii=False)
        self.raw_output.emit(f"[STDIO] skill_invoke: {skill_id}\n")
        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_ORANGE;'>[Skill] 调用: {skill_id}</span>"
        )

        return self._stdio_worker.send_line(json_line)

    # ==================== subprocess 输出处理 ====================

    def _on_run_line(self, line: str):
        self._run_output_buffer += line + "\n"
        # ★ v3.72 修复: JSON 行由 _parse_json_line 解析后通过专用信号发出，
        # 不再同时作为 raw_output 重复输出，避免终端显示乱码
        stripped = line.strip()
        if not stripped.startswith('{'):
            # 非 JSON 行（工具调用输出等）才作为 raw_output 输出
            self.raw_output.emit(line + "\n")
        self._parse_json_line(line)

    def _parse_json_line(self, line: str):
        line = line.strip()
        if not line.startswith('{'):
            return

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        try:
            self._process_json_event(event)
        except Exception as e:
            print(f"[ProcessBridge] _parse_json_line 异常: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def _process_json_event(self, event: dict):
        """★ v3.90: 独立的事件处理方法，带异常保护"""
        event_type = event.get('type', '')
        part = event.get('part', {})
        props = event.get('properties', {})  # ★ v3.93: message.part.updated 事件格式

        # ★ v3.93: 处理 message.part.updated 事件（MIMO Code v0.1.4+ 新格式）
        if event_type == 'message.part.updated':
            inner_part = props.get('part', {})
            delta = props.get('delta', '')
            part_type = inner_part.get('type', '')
            part_text = inner_part.get('text', '')
            part_id = inner_part.get('id', '')

            # 流式文本 delta
            if delta:
                if markdown_to_html:
                    html = markdown_to_html(delta)
                else:
                    safe = self._escape_html(delta)
                    html = f"<span style='color:Lemon.PLACEHOLDER;'>{safe}</span>"
                self.output_received.emit(html)
                if self._context and self._context[-1].get("role") == "assistant":
                    self._context[-1]["content"] += delta
                else:
                    self._context.append({"role": "assistant", "content": delta})
                return

            # 完整文本 part
            if part_type == 'text' and part_text:
                content = part_text.strip()
                if content:
                    if self._context and self._context[-1].get('role') == 'user':
                        user_msg = self._context[-1].get('content', '').strip()
                        if content.strip() == user_msg:
                            print(f"[ProcessBridge] 跳过回显: {content[:80]}", flush=True)
                            return
                    if markdown_to_html:
                        html = markdown_to_html(content)
                    else:
                        safe = self._escape_html(content)
                        html = f"<span style='color:Lemon.PLACEHOLDER;'>{safe}</span>"
                    self.output_received.emit(html)
                    self._context.append({"role": "assistant", "content": content})
                return

            # 工具调用 part
            if part_type == 'tool':
                tool_name = inner_part.get('tool', 'unknown')
                state = inner_part.get('state', {})
                status = state.get('status', '')
                tool_input = state.get('input', {})
                if status == 'error':
                    err = state.get('error', '未知错误')
                    self.error_occurred.emit(
                        f"<span style='color:Lemon.ACCENT_RED;'>[{self._escape_html(tool_name)}]: "
                        f"{self._escape_html(str(err))}</span>"
                    )
                elif status == 'completed':
                    self.raw_output.emit(f"[{tool_name}] 完成\n")
                elif status == 'running':
                    self.raw_output.emit(f"[{tool_name}]\n")
                return

            # 推理 part
            if part_type == 'reasoning':
                reasoning_text = inner_part.get('text', '')
                if reasoning_text:
                    safe = self._escape_html(reasoning_text)
                    self.thinking_received.emit(
                        f"<span style='color:#888;font-style:italic;'>{safe}</span>"
                    )
                return

            # step_start / step_finish parts
            if part_type == 'step-start':
                if not self._session_id:
                    sid = inner_part.get('sessionID', '')
                    if sid:
                        self._session_id = sid
                        self.session_created.emit(sid)
                        self.status_received.emit(
                            f"<span style='color:Lemon.ACCENT_GREEN;'>Session: {sid[:16]}...</span>"
                        )
                        self.raw_output.emit(f"Session ID: {sid}\n")
                return

            if part_type == 'step-finish':
                self.raw_output.emit("步骤完成\n")
                if self._use_stdio_bridge:
                    self._on_message_complete(0)
                return

            return

        # 首次 step_start 事件自动提取 sessionID（旧格式兼容）
        if not self._session_id and event_type == 'step_start':
            sid = event.get('sessionID', '')
            if sid:
                self._session_id = sid
                self.session_created.emit(sid)
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_GREEN;'>Session: {sid[:16]}...</span>"
                )
                self.raw_output.emit(f"Session ID: {sid}\n")

        if event_type == 'step_start':
            # ★ v3.73: 只在底部 MIMO Monitor 显示，不显示在右侧面板
            self.raw_output.emit("MIMO Code 执行中...\n")

        elif event_type == 'text':
            content = part.get('text', '').strip()
            if content:
                # ★ v3.88 修复: 回显检测更精确，只过滤完全相同的回显（不过滤前缀匹配）
                # 之前 content.startswith(user_msg[:50]) 过于激进，导致"你好"→"你好！..."被误过滤
                if self._context and self._context[-1].get('role') == 'user':
                    user_msg = self._context[-1].get('content', '').strip()
                    if content.strip() == user_msg:
                        print(f"[ProcessBridge] 跳过回显: {content[:80]}", flush=True)
                        return  # 只跳过完全相同的回显
                # ★ v3.72: 使用 markdown_to_html 转换，支持表格/公式/代码块
                if markdown_to_html:
                    html = markdown_to_html(content)
                else:
                    safe = self._escape_html(content)
                    html = f"<span style='color:Lemon.PLACEHOLDER;'>{safe}</span>"
                self.output_received.emit(html)
                self._context.append({"role": "assistant", "content": content})

        elif event_type == 'stream':
            # v9: 流式输出 — 逐字符/逐块输出，模拟实时打字效果
            content = part.get('text', event.get('content', ''))
            if not content:
                return
            # ★ v3.72: 使用 markdown_to_html 转换
            if markdown_to_html:
                html = markdown_to_html(content)
            else:
                safe = self._escape_html(content)
                html = f"<span style='color:Lemon.PLACEHOLDER;'>{safe}</span>"
            self.output_received.emit(html)
            # 流式内容追加到上下文（而非覆盖）
            if self._context and self._context[-1].get("role") == "assistant":
                self._context[-1]["content"] += content
            else:
                self._context.append({"role": "assistant", "content": content})

        elif event_type == 'reasoning':
            content = part.get('text', '').strip()
            if content:
                safe = self._escape_html(content)
                self.thinking_received.emit(
                    f"<span style='color:#888;font-style:italic;'>{safe}</span>"
                )

        elif event_type == 'tool_use':
            tool_name = part.get('tool', 'unknown')
            state = part.get('state', {})
            status = state.get('status', '')
            tool_input = state.get('input', {})

            if status == 'error':
                err = state.get('error', '未知错误')
                self.error_occurred.emit(
                    f"<span style='color:Lemon.ACCENT_RED;'>[{self._escape_html(tool_name)}]: "
                    f"{self._escape_html(str(err))}</span>"
                )
            elif status == 'running':
                cmd = tool_input.get('command', '')
                desc = tool_input.get('description', '')
                detail = f" ({desc})" if desc else ""
                # ★ v3.73: 工具状态只发到底部 MIMO Monitor
                self.raw_output.emit(f"[{tool_name}]{detail}\n")
                # ★ v3.72: 工具调用可视化（简笔风格 SVG 图标）→ 右侧可折叠区域
                self._emit_tool_indicator(tool_name, 'running', desc)
                if cmd:
                    self.tool_output.emit(
                        f"<span style='color:#b0b0b0;font-style:italic;font-size:11px;'>"
                        f"$ {self._escape_html(str(cmd))}</span>"
                    )
            elif status == 'completed':
                output = state.get('output', '')
                # ★ v3.73: 工具完成状态只发到底部 MIMO Monitor
                self.raw_output.emit(f"[{tool_name}] 完成\n")
                # ★ v3.72: 文件修改 diff 显示
                if tool_name in ('edit', 'write', 'write_file', 'notebook_edit'):
                    file_path = tool_input.get('file_path', tool_input.get('path', ''))
                    old_content = tool_input.get('old_str', '')
                    new_content = tool_input.get('new_str', tool_input.get('content', ''))
                    if file_path:
                        self._emit_file_diff(file_path, old_content, new_content, tool_name)
                elif output:
                    # ★ v3.87 修复: 工具输出不通过 output_received 发出（避免泄漏到右侧面板和底部栏）
                    # 只通过 raw_output 和 tool_output 发出（可折叠区域）
                    safe_result = self._escape_html(str(output).strip())
                    max_len = 800
                    if len(safe_result) > max_len:
                        safe_result = safe_result[:max_len] + "...\n[输出已截断]"
                    self.tool_output.emit(
                        f"<pre style='color:Lemon.SUCCESS;font-size:11px;line-height:1.4;"
                        f"margin:2px 0 4px 0;padding:4px 8px;background:rgba(0,0,0,0.3);"
                        f"border-left:2px solid Lemon.ACCENT_GREEN;border-radius:2px;"
                        f"white-space:pre-wrap;font-family:Courier New,monospace;'>"
                        f"{safe_result}</pre>"
                    )

        elif event_type == 'step_finish':
            tokens = part.get('tokens', {})
            total_tokens = tokens.get('total', '?')
            reason = part.get('reason', '')
            # ★ v3.73: 只在底部 MIMO Monitor 显示，不显示在右侧面板
            self.raw_output.emit(f"步骤完成 (tokens: {total_tokens}, reason: {reason})\n")
            # STDIO 模式下重置 busy 状态
            if self._use_stdio_bridge:
                self._on_message_complete(0)

        elif event_type == 'error':
            msg = part.get('text', part.get('message', '未知错误'))
            self.error_occurred.emit(
                f"<span style='color:Lemon.ACCENT_RED;'>{self._escape_html(str(msg))}</span>"
            )
            # STDIO 模式下重置 busy 状态
            if self._use_stdio_bridge:
                self._failure_count += 1
                self._on_message_complete(-1)

    def _on_run_finished(self, exit_code: int):
        self._run_busy = False

        if exit_code == 0:
            # ★ v3.93: 检查是否有实际 AI 输出（text/stream + message.part.updated 事件）
            has_ai_output = any(
                line.strip().startswith('{"type":"text"') or
                line.strip().startswith('{"type":"stream"') or
                line.strip().startswith('{"type":"message.part.updated"')
                for line in self._run_output_buffer.split('\n')
            )
            if not has_ai_output:
                self._failure_count += 1
                self.raw_output.emit(
                    f"[DEBUG] subprocess 退出 code=0 但无 AI 输出\n"
                )
                self.error_occurred.emit(
                    "<span style='color:Lemon.BRAND_ORANGE_LIGHT;'>mimo run 无 AI 输出（可能无 AI Provider 配置）</span>"
                )
                self.task_finished.emit(-1)
                self._run_worker = None
                return

            self._failure_count = 0
            self.status_received.emit(
                f"<span style='color:#6bd16b;'>消息 #{self._message_count} 完成</span>"
            )
        else:
            self._failure_count += 1
            error_text = f"mimo run 退出 (exit_code={exit_code})"
            if self._run_output_buffer:
                lines = self._run_output_buffer.strip().split('\n')
                error_lines = [l for l in lines if 'error' in l.lower() or 'Error' in l]
                if error_lines:
                    error_text = error_lines[-1][:200]
            self.error_occurred.emit(
                f"<span style='color:Lemon.BRAND_ORANGE_LIGHT;'>{error_text}</span>"
            )

        self.task_finished.emit(exit_code)
        self._run_worker = None

    def _on_run_error(self, error_msg: str):
        self._run_busy = False
        self._failure_count += 1
        self.error_occurred.emit(
            f"<span style='color:Lemon.ACCENT_RED;'>mimo run 异常: {self._escape_html(error_msg)}</span>"
        )
        self.task_finished.emit(-1)
        self._run_worker = None

    def _on_run_timeout(self):
        self._run_busy = False
        self._failure_count += 1
        self.error_occurred.emit(
            f"<span style='color:Lemon.BRAND_ORANGE_LIGHT;'>mimo run 超时 ({SUBPROCESS_TIMEOUT}s)</span>"
        )
        if self._run_worker:
            self._run_worker.stop()
            self._run_worker.wait(3000)
        self._run_worker = None
        self.task_finished.emit(-1)

    def _on_message_complete(self, exit_code: int):
        """
        STDIO 模式消息完成处理 — 重置 busy 状态，发射完成信号

        与 _on_run_finished 不同，此方法不检查 subprocess 输出缓冲区，
        因为 STDIO 模式的输出已经通过 _on_stdio_response 逐行处理。
        """
        self._run_busy = False

        if exit_code == 0:
            self._failure_count = 0
            self.status_received.emit(
                f"<span style='color:#6bd16b;'>[STDIO] 消息 #{self._message_count} 完成</span>"
            )
        else:
            self.status_received.emit(
                f"<span style='color:Lemon.BRAND_ORANGE_LIGHT;'>[STDIO] 消息 #{self._message_count} 异常</span>"
            )

        self.task_finished.emit(exit_code)

    # ==================== 工具方法 ====================

    @staticmethod
    def _escape_html(text: str) -> str:
        return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))

    def _emit_file_diff(self, file_path: str, old_content: str, new_content: str, tool_name: str):
        """★ v3.72: 发射文件修改 diff 显示"""
        import os
        basename = os.path.basename(file_path)
        ext = os.path.splitext(basename)[1].lower()  # v3.90: 提取扩展名供文件预览判断

        # 统计行数变化
        old_lines = old_content.count('\n') + 1 if old_content else 0
        new_lines = new_content.count('\n') + 1 if new_content else 0
        added = max(0, new_lines - old_lines) if tool_name == 'edit' else new_lines
        removed = max(0, old_lines - new_lines) if tool_name == 'edit' else 0

        # 构建 diff HTML
        icon = '📝' if tool_name == 'edit' else '➕'
        diff_html = (
            f'<div class="file-diff" style="margin:4px 0;padding:6px 10px;'
            f'background:rgba(20,20,30,0.6);border-radius:4px;'
            f'border-left:3px solid Lemon.BRAND_ORANGE_LIGHT;font-size:12px;">'
            f'<div style="color:Lemon.BRAND_ORANGE_LIGHT;margin-bottom:4px;">'
            f'{icon} <b>{self._escape_html(basename)}</b>'
            f' <span style="color:Lemon.ACCENT_GREEN;">+{added}</span>'
            f' <span style="color:Lemon.ACCENT_RED;">-{removed}</span>'
            f' <span style="color:#666;font-size:10px;">{self._escape_html(file_path)}</span>'
            f'</div>'
        )

        # 显示新增内容（截断过长内容）
        if new_content and len(new_content) < 2000:
            safe_new = self._escape_html(new_content)
            diff_html += (
                f'<pre style="color:Lemon.ACCENT_GREEN;margin:2px 0;padding:4px 8px;'
                f'background:rgba(0,0,0,0.2);border-radius:2px;'
                f'font-size:11px;white-space:pre-wrap;'
                f'font-family:Courier New,monospace;max-height:200px;overflow-y:auto;">'
                f'{safe_new}</pre>'
            )
        diff_html += '</div>'

        self.tool_output.emit(diff_html)

        # ★ v3.90: 同时发射文件预览（HTML/图像/代码内嵌到右侧栏）
        # 带异常保护，防止预览生成失败导致整个消息处理中断
        if new_content and ext in ('.html', '.htm', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg',
                                    '.py', '.js', '.ts', '.css', '.java', '.cpp', '.c', '.go', '.rs', '.rb', '.sh', '.bat'):
            try:
                self._emit_file_preview(file_path, new_content, tool_name)
            except Exception as e:
                print(f"[ProcessBridge] _emit_file_preview 异常: {e}", flush=True)
                import traceback
                traceback.print_exc()

    # ★ v3.90: 文件预览 — HTML iframe / 图像内嵌 / 代码可折叠
    def _emit_file_preview(self, file_path: str, new_content: str, tool_name: str):
        """
        拦截文件写入，将 HTML/图像/代码 内嵌到右侧栏显示。
        - HTML 文件：iframe 沙箱预览
        - 图像文件：内嵌 img 标签
        - 代码文件：可折叠代码块 + 运行按钮
        """
        import os
        import base64
        basename = os.path.basename(file_path)
        ext = os.path.splitext(basename)[1].lower()
        if ext in ('.html', '.htm'):
            # 将文件内容编码为 data URI，内嵌到 iframe
            import base64
            encoded = base64.b64encode(new_content.encode('utf-8')).decode('ascii')
            data_uri = f"data:text/html;base64,{encoded}"
            preview_html = (
                f'<div class="file-preview" style="margin:6px 0;padding:8px 10px;'
                f'background:rgba(20,20,30,0.6);border-radius:6px;'
                f'border-left:3px solid Lemon.ACCENT_BLUE;font-size:12px;">'
                f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">'
                f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.ACCENT_BLUE" stroke-width="2">'
                f'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>'
                f'<span style="color:Lemon.ACCENT_BLUE;font-weight:600;">HTML 预览</span>'
                f'<span style="color:#888;font-size:10px;margin-left:auto;">{self._escape_html(basename)}</span>'
                f'</div>'
                f'<iframe src="{data_uri}" sandbox="allow-scripts allow-same-origin" '
                f'style="width:100%;min-height:280px;max-height:500px;border:1px solid rgba(255,255,255,0.1);'
                f'border-radius:4px;background:#fff;"></iframe>'
                f'</div>'
            )
            self.file_preview.emit(preview_html)

        # ★ 图像文件 → 内嵌显示
        elif ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'):
            if ext == '.svg':
                # SVG 可以直接内嵌
                preview_html = (
                    f'<div class="file-preview" style="margin:6px 0;padding:8px 10px;'
                    f'background:rgba(20,20,30,0.6);border-radius:6px;'
                    f'border-left:3px solid Lemon.BRAND_ORANGE_LIGHT;font-size:12px;">'
                    f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">'
                    f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.BRAND_ORANGE_LIGHT" stroke-width="2">'
                    f'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>'
                    f'<path d="M21 15l-5-5L5 21"/></svg>'
                    f'<span style="color:Lemon.BRAND_ORANGE_LIGHT;font-weight:600;">图像预览</span>'
                    f'<span style="color:#888;font-size:10px;margin-left:auto;">{self._escape_html(basename)}</span>'
                    f'</div>'
                    f'<div style="text-align:center;padding:8px;background:rgba(0,0,0,0.3);border-radius:4px;">'
                    f'{new_content}</div>'
                    f'</div>'
                )
            else:
                # 二进制图像：尝试读取文件并 base64 编码
                try:
                    if os.path.exists(file_path):
                        with open(file_path, 'rb') as f:
                            img_data = base64.b64encode(f.read()).decode('ascii')
                        mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                                'gif': 'image/gif', 'webp': 'image/webp'}.get(ext[1:], 'image/png')
                        preview_html = (
                            f'<div class="file-preview" style="margin:6px 0;padding:8px 10px;'
                            f'background:rgba(20,20,30,0.6);border-radius:6px;'
                            f'border-left:3px solid Lemon.BRAND_ORANGE_LIGHT;font-size:12px;">'
                            f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">'
                            f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.BRAND_ORANGE_LIGHT" stroke-width="2">'
                            f'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>'
                            f'<path d="M21 15l-5-5L5 21"/></svg>'
                            f'<span style="color:Lemon.BRAND_ORANGE_LIGHT;font-weight:600;">图像预览</span>'
                            f'<span style="color:#888;font-size:10px;margin-left:auto;">{self._escape_html(basename)}</span>'
                            f'</div>'
                            f'<div style="text-align:center;padding:8px;background:rgba(0,0,0,0.3);border-radius:4px;">'
                            f'<img src="data:{mime};base64,{img_data}" style="max-width:100%;max-height:400px;'
                            f'border-radius:4px;" /></div>'
                            f'</div>'
                        )
                    else:
                        return
                except Exception:
                    return
            self.file_preview.emit(preview_html)

        # ★ 代码文件 → 可折叠代码块 + 运行按钮
        elif ext in ('.py', '.js', '.ts', '.html', '.css', '.java', '.cpp', '.c', '.go', '.rs', '.rb', '.sh', '.bat'):
            lang_map = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.html': 'html',
                        '.css': 'css', '.java': 'java', '.cpp': 'cpp', '.c': 'c', '.go': 'go',
                        '.rs': 'rust', '.rb': 'ruby', '.sh': 'bash', '.bat': 'batch'}
            lang = lang_map.get(ext, 'text')
            safe_code = self._escape_html(new_content)
            preview_html = (
                f'<div class="file-preview code-block-preview" style="margin:6px 0;padding:8px 10px;'
                f'background:rgba(20,20,30,0.6);border-radius:6px;'
                f'border-left:3px solid Lemon.ACCENT_PURPLE;font-size:12px;">'
                f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">'
                f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.ACCENT_PURPLE" stroke-width="2">'
                f'<path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/></svg>'
                f'<span style="color:Lemon.ACCENT_PURPLE;font-weight:600;">{lang.upper()} 代码</span>'
                f'<span style="color:#888;font-size:10px;margin-left:auto;">{self._escape_html(basename)}</span>'
                f'<button class="run-code-btn" data-lang="{lang}" data-code="{self._escape_html(new_content)}" '
                f'style="margin-left:8px;padding:2px 10px;background:Lemon.ACCENT_GREEN;color:#fff;border:none;'
                f'border-radius:3px;font-size:11px;cursor:pointer;">▶ 运行</button>'
                f'</div>'
                f'<pre style="color:Lemon.DIVIDER;margin:0;padding:8px;background:rgba(0,0,0,0.3);'
                f'border-radius:4px;font-size:11px;white-space:pre-wrap;overflow-x:auto;'
                f'font-family:Courier New,monospace;max-height:300px;overflow-y:auto;">'
                f'{safe_code}</pre>'
                f'</div>'
            )
            self.file_preview.emit(preview_html)

    # ★ v3.72: 工具简笔 SVG 图标映射
    _TOOL_ICONS = {
        'read':      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.ACCENT_BLUE" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
        'write':     '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.ACCENT_GREEN" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
        'edit':      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.BRAND_ORANGE_LIGHT" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4z"/></svg>',
        'bash':      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.BRAND_ORANGE_LIGHT" stroke-width="2"><path d="M4 17l6-6-6-6"/><path d="M12 19h8"/></svg>',
        'glob':      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.ACCENT_BLUE" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 0 20M12 2a15.3 15.3 0 0 0 0 20"/></svg>',
        'grep':      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.ACCENT_BLUE" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.3-4.3"/></svg>',
        'skill':     '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.BRAND_ORANGE_LIGHT" stroke-width="2"><path d="M12 2l3 7h7l-5.5 4 2 7L12 16l-6.5 4 2-7L2 9h7z"/></svg>',
        'webfetch':  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.ACCENT_BLUE" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 0 20"/></svg>',
        'websearch': '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.ACCENT_BLUE" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.3-4.3"/></svg>',
        'memory':    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.ACCENT_PURPLE" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6v6H9z"/></svg>',
        'task':      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="Lemon.ACCENT_GREEN" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
        'default':   '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#888" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v6M12 17v6M4.2 4.2l4.3 4.3M15.5 15.5l4.3 4.3M1 12h6M17 12h6M4.2 19.8l4.3-4.3M15.5 8.5l4.3-4.3"/></svg>',
    }

    def _emit_tool_indicator(self, tool_name: str, status: str, desc: str = ''):
        """★ v3.72: 发射工具调用可视化指示器"""
        icon_svg = self._TOOL_ICONS.get(tool_name, self._TOOL_ICONS['default'])
        status_color = 'Lemon.BRAND_ORANGE_LIGHT' if status == 'running' else 'Lemon.ACCENT_GREEN'
        status_text = '执行中' if status == 'running' else '完成'
        safe_desc = self._escape_html(desc) if desc else ''
        safe_tool = self._escape_html(tool_name)

        html = (
            f'<div class="tool-indicator" style="display:flex;align-items:center;gap:6px;'
            f'margin:3px 0;padding:4px 8px;background:rgba(20,20,30,0.5);'
            f'border-radius:3px;font-size:11px;">'
            f'{icon_svg}'
            f'<span style="color:Lemon.DIVIDER;font-weight:500;">{safe_tool}</span>'
            f'<span style="color:{status_color};">{status_text}</span>'
            + (f'<span style="color:#888;">{safe_desc}</span>' if safe_desc else '')
            + '</div>'
        )
        self.tool_output.emit(html)
