# -*- coding: utf-8 -*-
"""
PTY Bridge v3.71 — 伪终端 MIMO Code 通信桥
=============================================
通过 pywinpty 创建 Windows 伪终端（ConPTY），运行 mimo.exe，
实现底层可靠的终端级交互。

作为通信降级链的第三备选（Process Bridge → ACP Bridge → PTY Bridge），
提供与 Process Bridge 和 ACP Bridge 一致的接口。

功能：
- ✅ 启动 MIMO Code 终端进程（PTY）
- ✅ 异步读取输出并过滤 ANSI 转义码
- ✅ send_message 写入用户输入到终端
- ✅ 上下文管理（get_context/clear_context/get_context_turns）
- ✅ 多会话管理（create_session/switch_session/list_sessions）
- ✅ is_busy 状态追踪
- ✅ get_status 完整状态信息
- ✅ 信号驱动 UI 更新

使用方式：
    bridge = PTYBridge(project_path="/path/to/project")
    bridge.output_received.connect(self._on_output)
    bridge.start()
    bridge.send_message("你好")
"""

import os
import re
import sys
import json
import threading
import time
from typing import Optional, List, Dict

from PyQt5.QtCore import QObject, pyqtSignal


# MIMO Code 可执行文件路径 — 优先使用 lemon_agent\bin\mimo.exe
_MIMO_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "lemon_agent"
)
MIMO_EXE = os.path.join(_MIMO_ROOT, "bin", "mimo.exe")

# 回退路径
if not os.path.exists(MIMO_EXE):
    _MIMO_ROOT = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "小米AI", "node_global"
    )
    MIMO_EXE = os.path.join(
        _MIMO_ROOT, "node_modules",
        "@mimo-ai", "mimocode-windows-x64", "bin", "mimo.exe"
    )
if not os.path.exists(MIMO_EXE):
    MIMO_EXE = os.path.expanduser(r"~\AppData\Local\Programs\@mimo-ai\mimocode-windows-x64\bin\mimo.exe")


class PTYBridge(QObject):
    """
    PTY Bridge v3.71 — 伪终端 MIMO Code 通信桥

    通过 Windows 伪终端 (pywinpty/ConPTY) 运行 MIMO Code，
    实现可靠的终端级交互。
    """

    # ==================== 输出信号 ====================
    output_received = pyqtSignal(str)      # 已过滤 ANSI 的纯文本输出
    raw_output = pyqtSignal(str)           # 原始输出（含 ANSI 码）
    screen_cleared = pyqtSignal()          # 终端清屏信号
    error_occurred = pyqtSignal(str)       # 错误消息

    # ==================== 状态信号 ====================
    process_started = pyqtSignal()         # 进程启动
    process_stopped = pyqtSignal(int)      # 进程退出（exit code）
    connection_error = pyqtSignal(str)     # 连接错误

    # ==================== v3.71 新增信号（与 Process Bridge / ACP Bridge 一致） ====================
    thinking_received = pyqtSignal(str)    # 思考过程
    status_received = pyqtSignal(str)      # 状态消息
    task_started = pyqtSignal(str)         # 任务开始
    task_finished = pyqtSignal(int)        # 任务完成 (exit_code)
    session_created = pyqtSignal(str)      # 会话创建

    def __init__(self, project_path: str = None, parent=None):
        super().__init__(parent)
        self.project_path = os.path.abspath(project_path or os.getcwd())

        # PTY 进程
        self._process = None
        self._running = False
        self._read_thread = None
        self._lock = threading.Lock()

        # ANSI 转义码正则
        self._ansi_pattern = re.compile(r'''
            \x1b\[[0-9;]*[a-zA-Z]      # CSI 序列
            |\x1b\].*?(?:\x1b\\|\x07)  # OSC 序列
            |\x1b[^\[].                # 单字符 ESC 序列
            |\r                         # 回车符
        ''', re.VERBOSE)

        # v3.71: 上下文管理
        self._context: List[Dict] = []
        self._session_id: Optional[str] = None
        self._message_count = 0
        self._failure_count = 0
        self._busy = False

        # v3.71: 多会话管理
        self._saved_contexts: Dict[str, List[Dict]] = {}

        # 输出缓冲区
        self._output_buffer = ""

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def has_session(self) -> bool:
        return self._session_id is not None

    # ================================================================
    # 启动/停止
    # ================================================================

    def start(self, cols: int = 120, rows: int = 30) -> bool:
        """启动 MIMO Code 终端进程"""
        if self._running:
            return True

        if not os.path.exists(MIMO_EXE):
            self.connection_error.emit(f"MIMO EXE 不存在: {MIMO_EXE}")
            return False

        try:
            from winpty import PtyProcess
        except ImportError:
            try:
                from pywinpty import PtyProcess
            except ImportError:
                self.connection_error.emit("需要 pywinpty/winpty 库: pip install pywinpty")
                return False

        try:
            self._process = PtyProcess.spawn(
                [MIMO_EXE],
                cwd=os.path.dirname(MIMO_EXE),  # ★ cwd 为 mimo.exe 所在目录
                dimensions=(rows, cols)
            )
            self._running = True
            self.process_started.emit()

            self.status_received.emit(
                "<span style='color:Lemon.ACCENT_GREEN;'>[PTY] PTY Bridge v3.71 就绪（伪终端模式）</span>"
            )
            self.raw_output.emit("PTY Bridge v3.71 (ConPTY) 启动成功\n")

            # 启动读取线程
            self._read_thread = threading.Thread(
                target=self._read_loop, daemon=True
            )
            self._read_thread.start()

            return True

        except Exception as e:
            self.connection_error.emit(f"启动 PTY 失败: {e}")
            return False

    def stop(self):
        """停止进程"""
        self._running = False
        if self._process:
            try:
                self._process.close()
            except Exception:
                try:
                    self._process.terminate()
                except Exception:
                    pass
            self._process = None

        self._context.clear()
        self._saved_contexts.clear()
        self._session_id = None
        self._message_count = 0
        self._failure_count = 0
        self._busy = False

        self.process_stopped.emit(-1)

    # ================================================================
    # 消息发送（v3.71）
    # ================================================================

    def send_message(self, message: str, skills: List[str] = None) -> bool:
        """
        发送消息到 MIMO Code 终端

        PTY 模式下，消息通过终端标准输入写入，启动 MIMO 交互式会话。
        """
        if not self._running:
            self.error_occurred.emit(
                "<span style='color:Lemon.ACCENT_RED;'>\u274c PTY Bridge 未就绪</span>"
            )
            return False

        if self._busy:
            self.error_occurred.emit(
                "<span style='color:Lemon.ACCENT_RED;'>\u274c 上一个消息仍在处理中</span>"
            )
            return False

        self._message_count += 1
        self._busy = True
        self._output_buffer = ""
        self.task_started.emit(message)

        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_BLUE;'>[PTY] #{self._message_count}: "
            f"{message[:60]}...</span>"
        )
        self.raw_output.emit(f"\n--- 消息 #{self._message_count} (PTY) ---\n> {message}\n")
        self._context.append({"role": "user", "content": message})

        # 通过终端写入
        self.write_line(message)
        return True

    # ================================================================
    # 写入
    # ================================================================

    def write(self, text: str):
        """向终端写入文本（不自动换行）"""
        if not self._process or not self._running:
            return
        with self._lock:
            try:
                self._process.write(text)
            except Exception as e:
                self.error_occurred.emit(f"写入失败: {e}")

    def write_line(self, text: str):
        """向终端写入一行文本（自动添加回车）"""
        if not self._process or not self._running:
            return
        with self._lock:
            try:
                self._process.write(text + '\r')
            except Exception as e:
                self.error_occurred.emit(f"写入失败: {e}")

    # ================================================================
    # 读取循环
    # ================================================================

    def _read_loop(self):
        """后台线程：持续读取 PTY 输出"""
        while self._running and self._process:
            try:
                data = self._process.read(size=4096)

                if not data:
                    break

                # 发射原始输出
                self.raw_output.emit(data)

                # 检测清屏序列
                if '\x1b[2J' in data or '\x1b[3J' in data or '\x1b[H\x1b[2J' in data:
                    self.screen_cleared.emit()

                # 过滤 ANSI 并发射
                clean = self._strip_ansi(data)
                if clean:
                    self.output_received.emit(clean)
                    self._output_buffer += clean
                    # 检测响应结束（MIMO 通常以空行或提示符结束）
                    self._detect_message_end(clean)

            except EOFError:
                break

            except Exception as e:
                if self._running:
                    self.error_occurred.emit(f"读取 PTY 错误: {e}")
                break

        # 进程退出处理
        self._running = False
        exit_code = -1
        if self._process:
            try:
                exit_code = self._process.exitstatus()
            except Exception:
                pass
        self.process_stopped.emit(exit_code)

    def _detect_message_end(self, clean_text: str):
        """
        检测消息是否结束 — PTY 模式下通过启发式检测

        启发式规则：
        - 检测到 MIMO 提示符（如 "> " 或 "mimo> "）
        - 输出缓冲区在 2 秒内无新数据
        """
        # 记录最后输出时间
        if not hasattr(self, '_last_output_time'):
            self._last_output_time = 0
        self._last_output_time = time.time()

        # 启动一个定时器来检测空闲
        if not hasattr(self, '_end_timer'):
            self._end_timer = threading.Thread(target=self._idle_check, daemon=True)
            self._end_timer.start()

    def _idle_check(self):
        """空闲检测线程 — 2 秒无输出判定消息结束"""
        while self._running and self._busy:
            time.sleep(0.5)
            if hasattr(self, '_last_output_time'):
                elapsed = time.time() - self._last_output_time
                if elapsed >= 2.0:
                    # 记录 AI 回复到上下文
                    if self._output_buffer.strip():
                        # 只记录最新输出部分
                        recent = self._output_buffer.strip()[-500:]
                        # 避免重复记录
                        if not self._context or self._context[-1].get("content") != recent:
                            self._context.append({"role": "assistant", "content": recent})
                    self._failure_count = 0
                    self._busy = False
                    self.status_received.emit(
                        f"<span style='color:#6bd16b;'>[PTY] 消息 #{self._message_count} 完成</span>"
                    )
                    self.task_finished.emit(0)
                    break

    # ================================================================
    # ANSI 过滤
    # ================================================================

    def _strip_ansi(self, text: str) -> str:
        """过滤 ANSI 转义码，保留可读文本

        ★ v5.7 修复死循环：旧实现 `while '\\b' in text: re.sub(r'.\\b', ...)`
          中正则 \b 是「单词边界」而非退格符 \x08，退格符永远删不掉，
          循环永不退出（终端进度条输出会冻结读取线程）。
          退格符由下方控制字符正则统一剔除。
        """
        text = self._ansi_pattern.sub('', text)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        return text

    # ================================================================
    # v3.71: 上下文管理
    # ================================================================

    def get_context(self, n: int = None) -> List[Dict]:
        """获取对话上下文"""
        if n:
            return self._context[-n:]
        return self._context.copy()

    def clear_context(self):
        """清空对话上下文"""
        self._context.clear()

    def get_context_turns(self) -> int:
        """获取对话轮数"""
        return len(self._context) // 2

    # ================================================================
    # v3.71: 多会话管理
    # ================================================================

    def create_session(self, name: str = None) -> str:
        """创建新会话"""
        if self._session_id and self._context:
            self._saved_contexts[self._session_id] = self._context.copy()
        self._session_id = None
        self._context = []
        self._message_count = 0
        self._failure_count = 0
        self._output_buffer = ""
        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_BLUE;'>[PTY] 新会话已创建"
            + (f" ({name})" if name else "")
            + "</span>"
        )
        return ""

    def switch_session(self, session_id: str) -> bool:
        """切换到指定会话"""
        if not session_id:
            return False
        if self._session_id and self._context:
            self._saved_contexts[self._session_id] = self._context.copy()
        if session_id in self._saved_contexts:
            self._context = self._saved_contexts[session_id].copy()
            self._session_id = session_id
            self._message_count = len([c for c in self._context if c.get("role") == "user"])
            self.status_received.emit(
                f"<span style='color:Lemon.ACCENT_GREEN;'>[PTY] 切换到会话: {session_id[:16]}..."
                f" ({self._message_count} 轮)</span>"
            )
            return True
        return False

    def list_sessions(self) -> List[Dict]:
        """列出所有已保存的会话"""
        sessions = []
        if self._session_id:
            sessions.append({
                "session_id": self._session_id,
                "turns": len(self._context) // 2,
                "active": True,
            })
        for sid, ctx in self._saved_contexts.items():
            if sid != self._session_id:
                sessions.append({
                    "session_id": sid,
                    "turns": len(ctx) // 2,
                    "active": False,
                })
        return sessions

    def get_status(self) -> Dict:
        """获取完整状态信息"""
        return {
            "running": self._running,
            "busy": self._busy,
            "session_id": self._session_id,
            "message_count": self._message_count,
            "context_turns": len(self._context) // 2,
            "saved_sessions": len(self._saved_contexts),
            "failure_count": self._failure_count,
            "exe_exists": os.path.exists(MIMO_EXE),
            "pty_available": self._check_pywinpty(),
        }

    def _check_pywinpty(self) -> bool:
        """检查 pywinpty 是否可用"""
        try:
            from winpty import PtyProcess
            return True
        except ImportError:
            try:
                from pywinpty import PtyProcess
                return True
            except ImportError:
                return False

    # ================================================================
    # 工具方法
    # ================================================================

    def resize(self, cols: int, rows: int):
        """调整终端大小"""
        if self._process:
            try:
                self._process.setwinsize(rows, cols)
            except Exception:
                pass

    def is_alive(self) -> bool:
        """检查进程是否存活"""
        if self._process:
            try:
                return self._process.isalive()
            except Exception:
                return False
        return False