# -*- coding: utf-8 -*-
"""
ShellBridge v3.72 — 通用 ConPTY Shell 桥（真终端底座）
=========================================================
在 Windows 上通过 pywinpty(ConPTY) 启动一个持久 shell（默认 PowerShell），
实现可与 Trae / CodeBuddy / VSCode 内置终端媲美的真终端：

- 单进程常驻 → `cd dir` 后 `ls` 保持在同一 shell 会话
- 交互式 REPL（python / node / ipython）可正常进入并交互
- 长跑服务（npm run dev / python app.py）可实时看日志
- ANSI 转义码过滤，保留可读文本（原始流也可拿）
- Ctrl+C 中断当前前台命令

与 shared/pty_bridge.py 的关系：
- pty_bridge.py 是「MIMO Code 专用」的通信桥（跑 mimo.exe + 会话上下文）
- shell_bridge.py 是「通用 shell」底座（跑 powershell.exe 等），供 UI 终端面板使用
- 两者并存，互不影响。

信号系统（双模式）：
- 若 PyQt5 可用 → 用 pyqtSignal（UI 侧原生连接）
- 否则 → 降级为普通回调属性（.on_output/.on_error/.on_started/.on_stopped），
  便于无 PyQt 环境的单元测试。

使用方式：
    bridge = ShellBridge(cwd="D:/my/project")
    bridge.on_output = lambda text: print(text, end="")
    bridge.start()
    bridge.send_line("cd src")
    bridge.send_line("python -m http.server 8000")
    bridge.ctrl_c()          # 中断当前命令
    bridge.stop()

依赖：
    pip install pywinpty
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
from typing import Callable, List, Optional

try:  # PyQt5 可用时走信号（UI 侧）
    from PyQt5.QtCore import QObject, pyqtSignal
    _HAS_QT = True
except Exception:  # noqa: BLE001 无 PyQt → 降级回调模式
    _HAS_QT = False


class _BridgeBase(QObject if _HAS_QT else object):
    """PyQt 可用时继承 QObject（信号可用）；否则普通 object（回调模式）。"""


def _default_shell() -> List[str]:
    r"""返回当前平台的默认 shell 命令（可覆盖）。

    Windows：默认用 PowerShell（支持 ANSI 颜色、UTF-8、语法高亮）。
    若 PowerShell 不可用则降级到 cmd.exe。
    用户可传 shell=["cmd.exe", "/k", "prompt $P$G"] 自行切换。
    """
    if sys.platform == "win32":
        pwsh = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if pwsh:
            # ★ 终端修复(P0): 加 -ExecutionPolicy Bypass(解决 SecurityError)。
            #   注意：不能加 -Command + 脚本, 否则会与 -NoExit 语义冲突(脚本执行完就退出)。
            #   UTF-8/PSReadLine 设置改在 _start_conpty 后通过 send_line 注入。
            return [pwsh, "-NoLogo", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass"]
        return ["cmd.exe", "/k", "chcp 65001 >nul", "prompt $P$G"]
    return [os.environ.get("SHELL", "/bin/bash")]


# ★ 安全：允许的 shell 白名单
_ALLOWED_SHELLS = {
    "cmd.exe": None,
    "powershell.exe": ["powershell.exe", "-NoLogo", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass"],
    "pwsh.exe": ["pwsh.exe", "-NoLogo", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass"],
    "bash": ["/bin/bash"],
    "zsh": ["/bin/zsh"],
    "sh": ["/bin/sh"],
}


def _validate_shell(shell: Optional[List[str]]) -> List[str]:
    """验证 shell 是否在白名单中，防止命令注入。"""
    if not shell:
        return _default_shell()
    shell_name = os.path.basename(shell[0]).lower()
    if shell_name in _ALLOWED_SHELLS:
        allowed = _ALLOWED_SHELLS[shell_name]
        if allowed is None:
            return list(shell)
        return allowed
    print(f"[ShellBridge] 警告: shell '{shell_name}' 不在白名单中，使用默认 shell", flush=True)
    return _default_shell()


class ShellBridge(_BridgeBase):
    """通用 ConPTY Shell 桥。

    终端状态机:
        IDLE → STARTING → RUNNING → STOPPING → IDLE
    三级中断:
        L1: Ctrl+C (\x03) — 优雅中断前台命令
        L2: Ctrl+Break (\x06) — 强制中断(Windows)
        L3: ForceKill — terminate进程树
    依赖降级:
        pywinpty → subprocess.Popen + 管道(无ConPTY特性但保证可用)
    """

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"

    if _HAS_QT:
        output_received = pyqtSignal(str)   # 已过滤 ANSI 的纯文本输出
        raw_output = pyqtSignal(str)        # 原始输出（含 ANSI 码）
        error_occurred = pyqtSignal(str)    # 错误消息
        process_started = pyqtSignal()      # 进程启动
        process_stopped = pyqtSignal(int)   # 进程退出（exit code）

    def __init__(
        self,
        cwd: Optional[str] = None,
        shell: Optional[List[str]] = None,
        env: Optional[dict] = None,
        cols: int = 120,
        rows: int = 30,
        encoding: str = "auto",
        history_file: Optional[str] = None,
    ):
        super().__init__()
        self.cwd = os.path.abspath(cwd or os.getcwd())
        self.shell = _validate_shell(shell)
        self.env = env
        self.cols = cols
        self.rows = rows
        self.encoding = encoding
        # ★ 405A2: OSC 133 shell integration（默认启用，零污染 $PROFILE）
        #   404 热修: 原实现 kwargs.pop(...) 但签名无 **kwargs → NameError，
        #   在 Qt 信号回调内未捕获 → PyQt5 abort() → 0xC0000409 整个终端服务原生崩溃。
        self.shell_integration = True

        self._process = None
        self._subprocess = None
        self._running = False
        self._state = self.IDLE
        self._read_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._busy = False
        self._use_conpty = True

        self._ansi_pattern = re.compile(
            r"\x1b\[[0-9;?]*[a-zA-Z]"
            r"|\x1b\].*?(?:\x1b\\|\x07)"
            r"|\x1b[^\[].",
            re.VERBOSE,
        )

        self.on_output: Optional[Callable[[str], None]] = None
        self.on_raw: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_started: Optional[Callable[[], None]] = None
        self.on_stopped: Optional[Callable[[int], None]] = None

        self.history: List[str] = []
        self._history_idx = 0
        self._history_lock = threading.Lock()
        # ★ v5.7: 支持注入历史文件路径（默认仍为用户目录的持久化文件）。
        #   测试必须注入临时路径，否则会把测试命令写入用户真实终端历史
        self._history_file = history_file or os.path.join(
            os.path.expanduser("~"), ".lemoncode", "data", "ui_trace", "terminal_history.jsonl"
        )
        self._load_persistent_history()

    # ============================================================
    # 状态
    # ============================================================
    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_busy(self) -> bool:
        return self._busy

    def _emit(self, sig_name: str, *args):
        """统一发射：Qt信号 + 回调属性双通道。"""
        cb_map = {
            "output_received": self.on_output,
            "raw_output": self.on_raw,
            "error_occurred": self.on_error,
            "process_started": self.on_started,
            "process_stopped": self.on_stopped,
        }
        if _HAS_QT:
            sig = getattr(self, sig_name, None)
            if sig is not None:
                try:
                    sig.emit(*args)
                except Exception:  # noqa: BLE001
                    pass
        cb = cb_map.get(sig_name)
        if cb:
            try:
                cb(*args)
            except Exception:  # noqa: BLE001
                pass

    # ============================================================
    # 启动 / 停止
    # ============================================================
    def start(self, cols: Optional[int] = None, rows: Optional[int] = None) -> bool:
        """启动 shell 进程。优先 ConPTY，降级到 subprocess.Popen。"""
        if self._state != self.IDLE:
            return self._running
        self._state = self.STARTING
        cols = cols or self.cols
        rows = rows or self.rows

        ok = self._start_conpty(cols, rows)
        if not ok:
            ok = self._start_subprocess(cols, rows)
        if not ok:
            self._state = self.IDLE
            return False
        return True

    def _start_conpty(self, cols: int, rows: int) -> bool:
        try:
            from winpty import PtyProcess
            from winpty.enums import Backend
        except ImportError:
            try:
                from pywinpty import PtyProcess
                Backend = None
            except ImportError:
                self._use_conpty = False
                return False

        backend = os.environ.get("LEMON_TERM_BACKEND", "conpty").lower()
        try:
            env_dict = os.environ.copy()
            if self.env:
                env_dict.update(self.env)
            env_dict.setdefault("PYTHONIOENCODING", "utf-8")
            # ★ 402T-2: 移除 PYTHONUTF8=1 — 它是 utf-8 mode 触发器，会启动 python -c 探测时
            #   让 CPython 向 stderr 打印"模块已禁用: UTF-8 导入 hook"绿字，与 PSReadLine 白字同行叠印。
            #   PYTHONIOENCODING=utf-8 + CHCP=65001 已足够保证 UTF-8 输出。
            if self.encoding == "auto" or self.encoding == "utf-8":
                env_dict.setdefault("CHCP", "65001")
            if self.encoding == "gbk":
                env_dict["CHCP"] = "936"
                env_dict.pop("PYTHONUTF8", None)

            spawn_kwargs = {
                "cwd": self.cwd,
                "env": env_dict,
                "dimensions": (rows, cols),
            }
            if Backend is not None:
                if backend == "conpty":
                    spawn_kwargs["backend"] = Backend.ConPTY
                else:
                    spawn_kwargs["backend"] = Backend.WinPTY

            self._process = PtyProcess.spawn(self.shell, **spawn_kwargs)
            self._running = True
            self._use_conpty = True
            self._state = self.RUNNING
            self._emit("process_started")
            self._emit("output_received", "[ShellBridge] ConPTY已启动: " + " ".join(self.shell) + "\r\n")
            # ★ 终端修复(P1): PowerShell 启动后注入 UTF-8/PSReadLine 设置(避免与 -NoExit 冲突, 不能用 -Command)。
            shell_name = os.path.basename(self.shell[0]).lower()
            if shell_name in ("powershell.exe", "pwsh.exe"):
                try:
                    self._process.write(
                        "[Console]::InputEncoding=[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\r\n"
                    )
                    # ★ P0-C 修复: PSReadLine 2.1+ 才支持 -PredictionSource, 2.0/1.x 必须条件守护
                    #   否则用户会看到 NamedParameterNotFound 报错
                    self._process.write(
                        "if ((Get-Module PSReadLine | Select-Object -First 1 | ForEach-Object { $_.Version }) "
                        "-ge ([Version]'2.1.0')) "
                        "{ Set-PSReadLineOption -PredictionSource History -PredictionViewStyle ListView }\r\n"
                    )
                except Exception:
                    pass
            # ★ 405A2: 注入 OSC 133 提示符重写（shell integration）
            if getattr(self, "shell_integration", False):
                try:
                    from shared.shell_integration import generate_prompt_source
                    snippet = generate_prompt_source(True)
                    if snippet and self._process:
                        self._process.write(snippet.encode("utf-8", errors="replace"))
                        print(f"[ShellBridge] OSC133 shell integration 已注入", flush=True)
                except Exception as e:
                    print(f"[ShellBridge] OSC133 注入失败（跳过）: {e}", flush=True)
            self._read_thread = threading.Thread(target=self._read_loop_conpty, daemon=True)
            self._read_thread.start()
            return True
        except Exception as e:
            self._emit("error_occurred", "ConPTY启动失败(降级到subprocess): " + str(e))
            self._use_conpty = False
            return False

    def _start_subprocess(self, cols: int, rows: int) -> bool:
        """subprocess.Popen 降级 — 无 ConPTY 特性但保证基本可用。"""
        import subprocess
        try:
            env_dict = os.environ.copy()
            if self.env:
                env_dict.update(self.env)
            env_dict.setdefault("PYTHONIOENCODING", "utf-8")
            # ★ 402T-2: 同 conpty 分支, 移除 PYTHONUTF8=1 避免 utf-8 mode 触发 stderr 绿字。
            self._subprocess = subprocess.Popen(
                self.shell,
                cwd=self.cwd,
                env=env_dict,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            self._running = True
            self._use_conpty = False
            self._state = self.RUNNING
            self._emit("process_started")
            self._emit("output_received", "[ShellBridge] subprocess降级模式已启动\r\n")
            self._read_thread = threading.Thread(target=self._read_loop_subprocess, daemon=True)
            self._read_thread.start()
            return True
        except Exception as e:
            self._emit("error_occurred", "subprocess降级启动也失败: " + str(e))
            return False

    def stop(self):
        """停止进程并清理资源（幂等，状态机保护）。"""
        if self._state == self.STOPPING or self._state == self.IDLE:
            return
        self._state = self.STOPPING
        self._running = False

        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=2.0)
            if self._read_thread.is_alive():
                print("[ShellBridge] 警告: 读取线程未能在2秒内结束", flush=True)

        if self._use_conpty and self._process:
            try:
                self._process.close()
            except Exception:
                try:
                    self._process.terminate()
                except Exception:
                    pass
            try:
                if hasattr(self._process, 'isalive') and self._process.isalive():
                    for _ in range(10):
                        time.sleep(0.1)
                        if not self._process.isalive():
                            break
            except Exception:
                pass
            self._process = None

        if self._subprocess:
            try:
                self._subprocess.stdin.close()
            except Exception:
                pass
            try:
                self._subprocess.terminate()
                self._subprocess.wait(timeout=3)
            except Exception:
                try:
                    self._subprocess.kill()
                except Exception:
                    pass
            self._subprocess = None

        self._state = self.IDLE
        self._emit("process_stopped", -1)

    # ============================================================
    # 写入
    # ============================================================
    def send(self, text: str):
        """写入原始文本。ConPTY走write，subprocess走stdin。"""
        if not self._running:
            self._emit("error_occurred", "Shell 未就绪")
            return
        with self._lock:
            try:
                if self._use_conpty and self._process:
                    self._process.write(text)
                elif self._subprocess and self._subprocess.stdin:
                    self._subprocess.stdin.write(text.encode("utf-8", errors="replace"))
                    self._subprocess.stdin.flush()
                else:
                    self._emit("error_occurred", "Shell 无可用写入通道")
            except Exception as e:
                self._emit("error_occurred", "写入失败: " + str(e))

    def send_line(self, text: str):
        """写入一行命令（自动加换行），并记录历史。"""
        if text and text.strip():
            with self._history_lock:
                if not self.history or self.history[-1] != text:
                    self.history.append(text)
                self._history_idx = len(self.history)
                self._append_persistent_history(text)
            self._emit_terminal_tool_call(text.strip())
        self.send(text + "\r\n")

    def _emit_terminal_tool_call(self, command: str):
        try:
            from bridge.event_adapter import get_event_adapter
            adapter = get_event_adapter()
            adapter.tool_call.emit("terminal", {
                "name": "Terminal: " + command.split()[0] if command else "Terminal",
                "args": {"command": command},
                "callId": f"term_{id(self)}_{int(time.time()*1000)}",
            })
        except Exception:
            pass

    def ctrl_c(self):
        """L1中断: 发送 Ctrl+C (\\x03)。"""
        self.send("\x03")

    def ctrl_break(self):
        """L2中断: 发送 Ctrl+Break (\\x06) — Windows特有强制中断。"""
        self.send("\x06")

    def force_kill(self):
        """L3中断: 强制终止进程树。"""
        if self._use_conpty and self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
        if self._subprocess:
            try:
                self._subprocess.kill()
            except Exception:
                pass
        self._running = False

    def resize(self, cols: int, rows: int):
        """调整 PTY 窗口尺寸（subprocess模式忽略）。"""
        if self._use_conpty and self._process and self._running:
            try:
                self._process.setwinsize(rows, cols)
            except Exception:
                pass
        self.cols, self.rows = cols, rows

    # ============================================================
    # 历史导航（供 UI 上下键）
    # ============================================================
    def history_up(self) -> str:
        """向上取历史命令；无则返回空串。"""
        if not self.history:
            return ""
        self._history_idx = max(0, self._history_idx - 1)
        return self.history[self._history_idx]

    def history_down(self) -> str:
        """向下取历史命令；到底返回空串。"""
        if not self.history:
            return ""
        self._history_idx = min(len(self.history), self._history_idx + 1)
        if self._history_idx >= len(self.history):
            return ""
        return self.history[self._history_idx]

    # ============================================================
    # 读取循环
    # ============================================================
    def _read_loop_conpty(self):
        """ConPTY读取循环。"""
        consecutive_errors = 0
        while self._running and self._process:
            try:
                data = self._process.read(size=4096)
                consecutive_errors = 0
                if not data:
                    if self._process.isalive():
                        time.sleep(0.05)
                        continue
                    break
                self._emit("raw_output", data)
                clean = self._strip_ansi(data)
                if clean:
                    self._emit("output_received", clean)
            except EOFError:
                break
            except Exception as e:
                consecutive_errors += 1
                if self._running:
                    self._emit("error_occurred", "读取PTY错误(" + str(consecutive_errors) + "): " + str(e))
                if consecutive_errors >= 3:
                    break
        self._running = False
        exit_code = -1
        if self._process:
            try:
                raw = getattr(self._process, "exitstatus", -1)
                exit_code = raw() if callable(raw) else (raw if isinstance(raw, int) else -1)
            except Exception:
                pass
        if self._state != self.STOPPING:
            self._state = self.IDLE
            self._emit("process_stopped", exit_code)

    def _read_loop_subprocess(self):
        """subprocess降级读取循环。"""
        if not self._subprocess or not self._subprocess.stdout:
            return
        try:
            for raw_line in iter(self._subprocess.stdout.readline, b""):
                if not self._running:
                    break
                try:
                    data = raw_line.decode("utf-8", errors="replace")
                except Exception:
                    data = raw_line.decode("gbk", errors="replace")
                self._emit("raw_output", data)
                clean = self._strip_ansi(data)
                if clean:
                    self._emit("output_received", clean)
        except Exception as e:
            if self._running:
                self._emit("error_occurred", "subprocess读取错误: " + str(e))
        self._running = False
        exit_code = -1
        if self._subprocess:
            try:
                exit_code = self._subprocess.poll()
                if exit_code is None:
                    exit_code = -1
            except Exception:
                pass
        if self._state != self.STOPPING:
            self._state = self.IDLE
            self._emit("process_stopped", exit_code if isinstance(exit_code, int) else -1)

    # ============================================================
    # ANSI 过滤
    # ============================================================
    def _strip_ansi(self, text: str) -> str:
        """过滤 ANSI 转义码，保留可读文本。

        ★ v5.7 修复死循环：旧实现
              while "\b" in text: text = re.sub(r".\b", "", text, count=1)
          中正则的 \b 是「单词边界」（零宽断言）而非退格符 \x08，导致退格符
          永远无法被该正则删除，循环永不退出 —— 终端输出进度条（含退格）会
          冻结 UI 线程。退格符由下方控制字符正则（\x00-\x08）统一剔除，
          语义为「丢弃退格、保留已显示文本」。
        """
        text = self._ansi_pattern.sub("", text)
        # 剔除退格等控制字符（\x00-\x08 含 \x08 退格，见 v5.7 注释）
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        # ★ 403T-2: 把 \r 回车归一化——PSReadLine 多行输出 + 提示同框时,
        #   "\r" 被原实现整体删除, 多段文本失去回车锚点而在 xterm.js 同一行叠印。
        #   改进: 先归一 "\r\n" → "\n", 再把孤 "\r" → "\n" (后续由 xterm.js 解析 CR).
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text

    # ============================================================
    # ANSI → HTML（供 UI 富文本渲染）
    # ============================================================
    @staticmethod
    def ansi_to_html(text: str) -> str:
        """把含 ANSI 转义码的文本转成 HTML（QTextEdit 富文本渲染用）。

        保留 SGR 颜色（基础 16 色 + 加粗），其余 CSI / OSC / 单字符 ESC
        序列一律丢弃，避免光标定位、清屏、窗口标题等转义码泄露到 UI。
        """
        if not text:
            return ""
        # 常见 SGR 颜色映射（前/背景）
        _FG = {
            "30": "#3f3f3f", "31": "#e05561", "32": "#8cc265", "33": "#d18f52",
            "34": "#4aa5f0", "35": "#c162de", "36": "#42b3c2", "37": "#d4d4d4",
            "90": "#9e9e9e", "91": "Lemon.ACCENT_RED", "92": "#98e06a", "93": "#ffb86c",
            "94": "#74b9ff", "95": "#e17bff", "96": "#6ef0ff", "97": "Lemon.BG",
        }
        _BG = {
            "40": "#3f3f3f", "41": "#e05561", "42": "#8cc265", "43": "#d18f52",
            "44": "#4aa5f0", "45": "#c162de", "46": "#42b3c2", "47": "#d4d4d4",
        }
        out = []
        color_fg, color_bg, bold = None, None, False
        i = 0
        n = len(text)
        buf = []

        def _flush():
            if buf:
                seg = "".join(buf).replace("\r\n", "\n").replace("\r", "\n")
                if seg:
                    out.append(ShellBridge._escaped_seg(seg, color_fg, color_bg, bold))
                buf.clear()

        while i < n:
            ch = text[i]
            # CSI 序列：\x1b[...X
            if ch == "\x1b" and i + 1 < n and text[i + 1] == "[":
                j = i + 2
                while j < n and not text[j].isalpha():
                    j += 1
                if j < n:
                    _flush()
                    end_char = text[j]
                    if end_char == "m":
                        codes = text[i + 2:j].split(";")
                        for c in codes:
                            if not c:
                                continue
                            if c == "0":
                                color_fg = color_bg = None
                                bold = False
                            elif c == "1":
                                bold = True
                            elif c == "22":
                                bold = False
                            elif c in _FG:
                                color_fg = _FG[c]
                            elif c in _BG:
                                color_bg = _BG[c]
                    # 非 m 的 CSI（H/J/K/l/h 等）直接丢弃
                    i = j + 1
                    continue
                # 未闭合，按普通文本兜底
                buf.append(ch)
                i += 1
                continue
            # OSC 序列：\x1b]...\x07 或 \x1b]...\x1b\\
            if ch == "\x1b" and i + 1 < n and text[i + 1] == "]":
                _flush()
                j = i + 2
                while j < n:
                    if text[j] == "\x07":
                        j += 1
                        break
                    if text[j] == "\x1b" and j + 1 < n and text[j + 1] == "\\":
                        j += 2
                        break
                    j += 1
                i = j
                continue
            # 单字符 ESC 序列：\x1bX（非 [ 非 ]）
            if ch == "\x1b" and i + 1 < n:
                _flush()
                i += 2
                continue
            # 回车单独吞掉（避免 \r\n 双换行）
            if ch == "\r":
                i += 1
                continue
            buf.append(ch)
            i += 1
        _flush()
        return "".join(out)

    @staticmethod
    def _escaped_seg(seg: str, color_fg, color_bg, bold) -> str:
        """对文本段做 HTML 转义，并按当前颜色包裹 span。"""
        seg = seg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        style = []
        if color_fg:
            style.append(f"color:{color_fg}")
        if color_bg:
            style.append(f"background:{color_bg}")
        if bold:
            style.append("font-weight:bold")
        if style:
            return f"<span style='{' ; '.join(style)}'>{seg}</span>"
        return seg

    # ============================================================
    # 历史持久化（JSONL，跨会话/跨重启共享）
    # ============================================================
    _MAX_PERSISTENT_HISTORY = 5000

    def _load_persistent_history(self):
        try:
            if not os.path.isfile(self._history_file):
                return
            with open(self._history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            with self._history_lock:
                self.history = [l.rstrip("\n") for l in lines[-self._MAX_PERSISTENT_HISTORY:] if l.strip()]
                self._history_idx = len(self.history)
        except Exception:
            pass

    def _append_persistent_history(self, cmd: str):
        try:
            os.makedirs(os.path.dirname(self._history_file), exist_ok=True)
            with open(self._history_file, "a", encoding="utf-8") as f:
                f.write(cmd + "\n")
            if len(self.history) > self._MAX_PERSISTENT_HISTORY:
                with self._history_lock:
                    self.history = self.history[-self._MAX_PERSISTENT_HISTORY:]
        except Exception:
            pass

    def history_search(self, query: str) -> List[str]:
        """模糊搜索历史命令（Ctrl+R 用）。"""
        if not query:
            return []
        q = query.lower()
        with self._history_lock:
            return [h for h in reversed(self.history) if q in h.lower()][:20]
