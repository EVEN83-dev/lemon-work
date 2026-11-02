# -*- coding: utf-8 -*-
"""
Stdio Bridge — 基于 JSON stdin/stdout 的通信桥
===============================================
在 Python 端通过子进程管道与 MIMO Code 通信，
绕过 HTTP 线程池瓶颈，实现稳定连接和上下文记忆。

功能：
1. JSON 格式的 stdin/stdout 通信
2. 会话管理（session_id）
3. 上下文传递（context）
4. 流式输出支持
5. 心跳检测
6. 错误处理与重连

使用方式：
    bridge = StdioBridge(project_path="/path/to/project")
    bridge.start()
    bridge.send_message("你好世界")
    response = bridge.receive()
    bridge.stop()
"""

import os
import json
import time
import threading
import subprocess
from typing import Optional, Dict, List, Any, Callable


# ============================================================
# 消息类型
# ============================================================

class MessageType:
    CHAT = "chat"
    RESPONSE = "response"
    STREAM = "stream"
    ERROR = "error"
    STATUS = "status"
    SKILL_INVOKE = "skill_invoke"
    SKILL_RESULT = "skill_result"
    PING = "ping"
    PONG = "pong"
    ABORT = "abort"


# ============================================================
# StdioBridge 类
# ============================================================

class StdioBridge:
    """基于 JSON 行的 stdio 通信桥

    通过 subprocess 启动 MIMO 进程，使用 stdin/stdout 管道
    进行 JSON 行协议通信。
    """

    def __init__(self, project_path: str = "", max_context: int = 20):
        """
        Args:
            project_path: 项目工作目录
            max_context: 最大上下文消息数
        """
        self.project_path = project_path or os.getcwd()
        self.max_context = max_context

        # 进程管理
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._running = False
        self._session_id: Optional[str] = None

        # 上下文
        self._context: List[Dict[str, str]] = []

        # 消息计数
        self._message_count = 0
        self._failure_count = 0

        # 回调
        self._on_output: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._on_status: Optional[Callable] = None

        # 心跳
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_interval = 30

        # 读取线程
        self._reader_thread: Optional[threading.Thread] = None

    # ============================================================
    # 进程管理
    # ============================================================

    def start(self, mimo_exe: str = None, session_id: str = None) -> bool:
        """启动 MIMO 进程并建立 stdio 通信

        Args:
            mimo_exe: mimo.exe 路径，None 则自动查找
            session_id: 会话 ID，None 则自动生成

        Returns:
            是否启动成功
        """
        with self._lock:
            if self._running:
                return True

            # 查找 mimo.exe
            if mimo_exe is None:
                mimo_exe = self._find_mimo_exe()
            if not mimo_exe or not os.path.exists(mimo_exe):
                self._emit_error("mimo.exe 未找到", "EXE_NOT_FOUND")
                return False

            # 生成会话 ID
            self._session_id = session_id or f"ses_{int(time.time())}"

            try:
                self._process = subprocess.Popen(
                    [mimo_exe, "run", "--format", "json"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.project_path,
                    text=False,  # 使用二进制模式
                )
                self._running = True
                self._message_count = 0
                self._failure_count = 0

                # 启动读取线程
                self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
                self._reader_thread.start()

                # 启动心跳
                self._start_heartbeat()

                self._emit_status("connected")
                return True

            except Exception as e:
                self._emit_error(f"启动进程失败: {e}", "PROCESS_START_FAILED")
                return False

    def stop(self):
        """停止进程并清理资源"""
        with self._lock:
            self._running = False
            self._stop_heartbeat()

            if self._process:
                try:
                    # 发送中止信号
                    self._send_raw({"type": MessageType.ABORT, "session_id": self._session_id})
                    self._process.stdin.close()
                    self._process.stdout.close()
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None

            self._emit_status("disconnected")

    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._running and self._process is not None and self._process.poll() is None

    # ============================================================
    # 消息发送/接收
    # ============================================================

    def send_message(self, message: str, context: List[Dict[str, str]] = None,
                     skills: List[str] = None) -> bool:
        """发送聊天消息

        Args:
            message: 消息内容
            context: 额外的上下文消息
            skills: 要调用的 Skill 列表

        Returns:
            是否发送成功
        """
        if not self.is_running():
            self._emit_error("进程未运行", "NOT_RUNNING")
            return False

        with self._lock:
            # 构建完整上下文
            full_context = self._context[-self.max_context:] if self._context else []
            if context:
                full_context = full_context + context

            payload = {
                "type": MessageType.CHAT,
                "session_id": self._session_id,
                "message": message,
                "context": full_context,
            }
            if skills:
                payload["skills"] = skills

            try:
                self._send_raw(payload)
                self._message_count += 1
                return True
            except Exception as e:
                self._failure_count += 1
                self._emit_error(f"发送失败: {e}", "SEND_FAILED")
                return False

    def send_skill_invoke(self, skill_id: str, params: Dict[str, Any]) -> bool:
        """发送 Skill 调用

        Args:
            skill_id: Skill 标识符
            params: Skill 参数

        Returns:
            是否发送成功
        """
        if not self.is_running():
            return False

        payload = {
            "type": MessageType.SKILL_INVOKE,
            "skill_id": skill_id,
            "params": params,
            "session_id": self._session_id,
        }

        try:
            self._send_raw(payload)
            return True
        except Exception as e:
            self._emit_error(f"Skill 调用失败: {e}", "SKILL_SEND_FAILED")
            return False

    def abort(self):
        """中止当前请求"""
        if self.is_running():
            self._send_raw({"type": MessageType.ABORT, "session_id": self._session_id})

    def receive(self, timeout: float = 60) -> Optional[Dict[str, Any]]:
        """同步接收一条响应

        Args:
            timeout: 超时时间（秒）

        Returns:
            解析后的响应消息，超时返回 None
        """
        if not self.is_running():
            return None

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self._process.stdout.readline()
                if line:
                    data = json.loads(line.decode("utf-8"))
                    self._handle_message(data)
                    return data
            except json.JSONDecodeError:
                continue
            except Exception:
                break
            time.sleep(0.01)
        return None

    def _send_raw(self, data: dict):
        """发送原始 JSON 数据"""
        line = json.dumps(data, ensure_ascii=False) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        self._process.stdin.flush()

    def _read_loop(self):
        """后台读取循环"""
        buffer = ""
        while self._running and self._process and self._process.poll() is None:
            try:
                chunk = self._process.stdout.read1(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

                # 按行分割
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        try:
                            data = json.loads(line)
                            self._handle_message(data)
                        except json.JSONDecodeError:
                            pass
            except Exception:
                break

        # 进程退出
        if self._running:
            self._emit_status("disconnected")
            self._running = False

    def _handle_message(self, data: dict):
        """处理接收到的消息"""
        msg_type = data.get("type", "")

        if msg_type == MessageType.RESPONSE:
            # 添加到上下文
            content = data.get("content", "")
            self._context.append({"role": "assistant", "content": content})
            if self._on_output:
                self._on_output(data)

        elif msg_type == MessageType.STREAM:
            if self._on_output:
                self._on_output(data)

        elif msg_type == MessageType.ERROR:
            self._failure_count += 1
            if self._on_error:
                self._on_error(data)

        elif msg_type == MessageType.STATUS:
            if self._on_status:
                self._on_status(data)

        elif msg_type == MessageType.PONG:
            pass  # 心跳响应

        elif msg_type == MessageType.SKILL_RESULT:
            if self._on_output:
                self._on_output(data)

    # ============================================================
    # 上下文管理
    # ============================================================

    def add_context(self, role: str, content: str):
        """添加上下文消息"""
        self._context.append({"role": role, "content": content})
        if len(self._context) > self.max_context * 2:
            self._context = self._context[-self.max_context * 2:]

    def clear_context(self):
        """清空上下文"""
        self._context.clear()

    def get_context(self, n: int = None) -> List[Dict[str, str]]:
        """获取上下文

        Args:
            n: 获取最近 n 条，None 则获取全部
        """
        if n:
            return self._context[-n:]
        return self._context.copy()

    def get_context_turns(self) -> int:
        """获取对话轮数"""
        return len(self._context) // 2

    # ============================================================
    # 回调设置
    # ============================================================

    def on_output(self, callback: Callable):
        """设置输出回调"""
        self._on_output = callback

    def on_error(self, callback: Callable):
        """设置错误回调"""
        self._on_error = callback

    def on_status(self, callback: Callable):
        """设置状态回调"""
        self._on_status = callback

    def _emit_error(self, message: str, code: str = "UNKNOWN"):
        """触发错误回调"""
        data = {"type": MessageType.ERROR, "error": message, "code": code}
        if self._on_error:
            self._on_error(data)

    def _emit_status(self, status: str):
        """触发状态回调"""
        data = {"type": MessageType.STATUS, "status": status, "session_id": self._session_id}
        if self._on_status:
            self._on_status(data)

    # ============================================================
    # 心跳检测
    # ============================================================

    def _start_heartbeat(self):
        """启动心跳"""
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self):
        """停止心跳"""
        self._heartbeat_interval = 0  # 信号停止

    def _heartbeat_loop(self):
        """心跳循环"""
        while self._heartbeat_interval > 0 and self._running:
            time.sleep(self._heartbeat_interval)
            if self.is_running():
                try:
                    self._send_raw({"type": MessageType.PING, "timestamp": time.time()})
                except Exception:
                    break

    # ============================================================
    # 状态查询
    # ============================================================

    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "running": self.is_running(),
            "session_id": self._session_id,
            "message_count": self._message_count,
            "context_turns": self.get_context_turns(),
            "failure_count": self._failure_count,
            "exe_exists": bool(self._find_mimo_exe()),
        }

    # ============================================================
    # mimo.exe 查找
    # ============================================================

    @staticmethod
    def _find_mimo_exe() -> Optional[str]:
        """查找 mimo.exe 路径"""
        search_paths = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "mimo", "mimo.exe"),
            os.path.join(os.environ.get("APPDATA", ""), "mimo", "mimo.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\@mimo-ai\mimocode-windows-x64\bin\mimo.exe"),
        ]
        for path in search_paths:
            if os.path.exists(path):
                return path
        return None


# ============================================================
# 便捷函数
# ============================================================

def create_stdio_bridge(project_path: str = "") -> StdioBridge:
    """创建 StdioBridge 实例"""
    return StdioBridge(project_path=project_path)