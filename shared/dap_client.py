# -*- coding: utf-8 -*-
"""
调试适配器协议（DAP）客户端（v0.6.0 新增）
============================================
功能：
- DAP协议实现（基于 JSON-RPC）
- 与调试器通信（Python debugger、Node debugger）
- 断点管理
- 变量监视
- 调用栈追踪
- 步进控制（step over/into/out）

架构：
┌─────────────────────────────────────┐
│         DAPClient                    │
│  ┌────────────────────────────────┐ │
│  │ JSON-RPC 通信层                │ │
│  │ - send_request()               │ │
│  │ - receive_response()           │ │
│  └────────────────────────────────┘ │
│  ┌────────────────────────────────┐ │
│  │ 调试适配器进程管理              │ │
│  │ - Python: debugpy              │ │
│  │ - Node: node --inspect         │ │
│  └────────────────────────────────┘ │
└─────────────────────────────────────┘
"""

import os
import json
import uuid
import threading
import subprocess
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from queue import Queue, Empty

from PyQt5.QtCore import QObject, pyqtSignal, QProcess, QTimer


# ============================================================
# DAP 数据类型
# ============================================================

class DAPEventType(Enum):
    """DAP 事件类型"""
    INITIALIZED = "initialized"
    STOPPED = "stopped"
    CONTINUED = "continued"
    BREAKPOINT = "breakpoint"
    OUTPUT = "output"
    TERMINATED = "terminated"
    EXCLUDED_CALLERS = "excludedCallers"


@dataclass
class Source:
    """源码位置"""
    name: str
    path: str
    sourceReference: int = 0


@dataclass
class SourceBreakpoint:
    """源码断点"""
    line: int
    column: Optional[int] = None
    condition: Optional[str] = None
    hitCondition: Optional[str] = None
    logMessage: Optional[str] = None


@dataclass
class Breakpoint:
    """断点信息"""
    id: int
    verified: bool
    message: str = ""
    source: Optional[Source] = None
    line: int = 0
    column: int = 0
    endLine: Optional[int] = None
    endColumn: Optional[int] = None


@dataclass
class StackFrame:
    """调用栈帧"""
    id: int
    name: str
    source: Optional[Source]
    line: int
    column: int
    endLine: Optional[int] = None
    endColumn: Optional[int] = None
    moduleId: Optional[int] = None


@dataclass
class Variable:
    """变量"""
    name: str
    value: str
    type: str = ""
    evaluateName: Optional[str] = None
    variablesReference: int = 0


@dataclass
class Scope:
    """作用域"""
    name: str
    variablesReference: int
    expensive: bool = False


# ============================================================
# DAP 客户端
# ============================================================

class DAPClient(QObject):
    """
    调试适配器协议客户端
    
    功能：
    - 启动调试器进程
    - 发送/接收 DAP 消息（JSON-RPC）
    - 断点管理
    - 变量监视
    - 调用栈追踪
    """
    
    # 信号
    initialized = pyqtSignal()
    stopped = pyqtSignal(str, int, str)  # (reason, threadId, message)
    continued = pyqtSignal(int)  # (threadId)
    breakpoint_changed = pyqtSignal(dict)  # (breakpoint)
    output_received = pyqtSignal(str, str)  # (category, output)
    terminated = pyqtSignal()
    error_occurred = pyqtSignal(str)  # (error_message)
    
    def __init__(self):
        super().__init__()
        
        # 调试器进程
        self.process: Optional[QProcess] = None
        
        # 消息序列号
        self._seq = 0
        
        # 请求队列
        self._pending_requests: Dict[int, Queue] = {}
        
        # 断点列表
        self._breakpoints: Dict[str, List[Breakpoint]] = {}
        
        # 调用栈
        self._call_stack: Dict[int, List[StackFrame]] = {}
        
        # 变量
        self._variables: Dict[int, List[Variable]] = {}
        
        # 作用域
        self._scopes: Dict[int, List[Scope]] = {}
        
        # 线程列表
        self._threads: List[int] = []
        
        # 初始化状态
        self._is_initialized = False
        self._is_running = False
        
        # ★ 消息接收缓冲区（DAP 消息可能分多次到达）
        self._recv_buffer = b""
        
        # ★ 当前线程 ID（便捷方法使用）
        self._current_thread_id = 0
        
        # ★ 当前栈帧 ID
        self._current_frame_id = 0
        
        # ★ 当前作用域引用（局部/全局变量）
        self._scope_refs: Dict[str, int] = {}  # {"Locals": ref, "Globals": ref}
    
    @property
    def is_initialized(self) -> bool:
        return self._is_initialized
    
    @property
    def is_running(self) -> bool:
        return self._is_running
    
    def start_debugger(self, adapter_type: str = "python", cwd: str = "") -> bool:
        """
        启动调试器进程
        
        Args:
            adapter_type: 调试器类型（python/node）
            cwd: 工作目录
        
        Returns:
            是否启动成功
        """
        if self.process and self.process.state() == QProcess.Running:
            self.error_occurred.emit("调试器已在运行")
            return False
        
        # 创建进程
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        
        # 设置工作目录
        if cwd:
            self.process.setWorkingDirectory(cwd)
        
        # 连接信号
        self.process.readyReadStandardOutput.connect(self._on_stdout_ready)
        self.process.readyReadStandardError.connect(self._on_stderr_ready)
        self.process.errorOccurred.connect(self._on_process_error)
        self.process.finished.connect(self._on_process_finished)
        
        # 启动调试器
        if adapter_type == "python":
            # 使用 debugpy
            adapter_path = self._find_python_adapter()
            if not adapter_path:
                self.error_occurred.emit("未找到 Python 调试适配器（debugpy）")
                return False
            
            self.process.start("python", [adapter_path])
        
        elif adapter_type == "node":
            # 使用 Node.js 调试器
            self.process.start("node", ["--inspect-brk"])
        
        else:
            self.error_occurred.emit(f"不支持的调试器类型: {adapter_type}")
            return False
        
        # 等待启动
        if not self.process.waitForStarted(5000):
            self.error_occurred.emit("调试器启动超时")
            return False
        
        return True
    
    def _find_python_adapter(self) -> Optional[str]:
        """查找 Python 调试适配器"""
        # 尝试查找 debugpy 适配器
        try:
            import debugpy
            adapter_path = os.path.join(
                os.path.dirname(debugpy.__file__),
                "adapter"
            )
            if os.path.exists(adapter_path):
                return adapter_path
        except ImportError:
            pass
        
        return None
    
    def stop_debugger(self):
        """停止调试器进程"""
        if self.process:
            self.process.kill()
            self.process.waitForFinished(3000)
            self.process = None
        
        self._is_initialized = False
        self._is_running = False
        self._breakpoints.clear()
        self._call_stack.clear()
        self._variables.clear()
    
    def _send_request(self, command: str, arguments: Dict = None, timeout: int = 10) -> Optional[Dict]:
        """
        发送 DAP 请求
        
        Args:
            command: 命令名称
            arguments: 命令参数
            timeout: 超时时间（秒）
        
        Returns:
            响应结果（成功）或 None（失败）
        """
        if not self.process:
            return None
        
        # 构造请求
        self._seq += 1
        request = {
            "seq": self._seq,
            "type": "request",
            "command": command,
            "arguments": arguments or {},
        }
        
        # 序列化为 JSON
        content = json.dumps(request)
        message = f"Content-Length: {len(content)}\r\n\r\n{content}"
        
        # 发送
        self.process.write(message.encode('utf-8'))
        
        # 等待响应
        response_queue = Queue()
        self._pending_requests[self._seq] = response_queue
        
        try:
            response = response_queue.get(timeout=timeout)
            return response
        except Empty:
            return None
        finally:
            del self._pending_requests[self._seq]
    
    def _parse_message(self, data: bytes) -> Optional[Dict]:
        """解析 DAP 消息"""
        try:
            # 解析消息头
            text = data.decode('utf-8')
            
            # 查找 Content-Length
            header_end = text.find('\r\n\r\n')
            if header_end == -1:
                return None
            
            header = text[:header_end]
            content_start = header_end + 4
            content = text[content_start:]
            
            # 解析 JSON
            return json.loads(content)
        
        except Exception as e:
            print(f"[DAP] 解析消息错误: {e}")
            return None
    
    def _on_stdout_ready(self):
        """标准输出就绪 — 使用缓冲区处理 DAP 帧协议"""
        if not self.process:
            return

        data = self.process.readAllStandardOutput().data()
        self._recv_buffer += data

        # DAP 消息格式: Content-Length: N\r\n\r\n{json_body}
        # 循环处理缓冲区中的所有完整消息
        while True:
            # 查找消息头结束标记
            header_end = self._recv_buffer.find(b"\r\n\r\n")
            if header_end == -1:
                break  # 头部不完整，等待更多数据

            # 解析 Content-Length
            header = self._recv_buffer[:header_end].decode("ascii", errors="ignore")
            content_length = 0
            for line in header.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    try:
                        content_length = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                    break

            if content_length == 0:
                # 无效头部，丢弃
                self._recv_buffer = self._recv_buffer[header_end + 4:]
                continue

            body_start = header_end + 4
            body_end = body_start + content_length

            if len(self._recv_buffer) < body_end:
                break  # 消息体不完整，等待更多数据

            # 提取完整消息体
            body = self._recv_buffer[body_start:body_end]
            self._recv_buffer = self._recv_buffer[body_end:]

            # 解析 JSON
            try:
                message = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as e:
                print(f"[DAP] JSON 解析错误: {e}")
                continue

            msg_type = message.get("type")

            if msg_type == "response":
                request_seq = message.get("request_seq")
                if request_seq in self._pending_requests:
                    self._pending_requests[request_seq].put(message)

            elif msg_type == "event":
                self._handle_event(message)
    
    def _on_stderr_ready(self):
        """标准错误就绪"""
        if not self.process:
            return
        
        error = self.process.readAllStandardError().data().decode('utf-8')
        self.error_occurred.emit(error)
    
    def _on_process_error(self, error):
        """进程错误"""
        self.error_occurred.emit(f"调试器进程错误: {error}")
    
    def _on_process_finished(self, exit_code, exit_status):
        """进程结束"""
        self._is_initialized = False
        self._is_running = False
        self.terminated.emit()
    
    def _handle_event(self, event: Dict):
        """处理事件"""
        event_type = event.get("event")
        body = event.get("body", {})
        
        if event_type == "initialized":
            self._is_initialized = True
            self.initialized.emit()
        
        elif event_type == "stopped":
            reason = body.get("reason", "")
            threadId = body.get("threadId", 0)
            message = body.get("text", "")
            self._is_running = False
            self._current_thread_id = threadId  # ★ 保存当前线程
            self.stopped.emit(reason, threadId, message)
        
        elif event_type == "continued":
            threadId = body.get("threadId", 0)
            self._is_running = True
            self.continued.emit(threadId)
        
        elif event_type == "breakpoint":
            breakpoint = body.get("breakpoint", {})
            self.breakpoint_changed.emit(breakpoint)
        
        elif event_type == "output":
            category = body.get("category", "console")
            output = body.get("output", "")
            self.output_received.emit(category, output)
        
        elif event_type == "terminated":
            self._is_initialized = False
            self._is_running = False
            self.terminated.emit()
    
    # ============================================================
    # DAP 命令
    # ============================================================
    
    def initialize(self) -> bool:
        """初始化调试器"""
        response = self._send_request("initialize", {
            "clientID": "mimo-code-agent",
            "clientName": "MiMoCode Agent",
            "adapterID": "python",
            "pathFormat": "path",
            "linesStartAt1": True,
            "columnsStartAt1": True,
            "supportsVariableType": True,
            "supportsVariablePaging": True,
            "supportsRunInTerminalRequest": True,
        })
        
        return response and response.get("success", False)
    
    def launch(self, program: str, args: List[str] = None, env: Dict = None) -> bool:
        """
        启动调试
        
        Args:
            program: 程序路径
            args: 程序参数
            env: 环境变量
        """
        arguments = {
            "program": program,
            "noDebug": False,
            "stopOnEntry": True,
            "args": args or [],
            "env": env or {},
        }
        
        response = self._send_request("launch", arguments)
        if response and response.get("success", False):
            self._is_running = True
            return True
        
        return False
    
    def attach(self, processId: int) -> bool:
        """附加到进程"""
        response = self._send_request("attach", {
            "processId": processId,
        })
        
        return response and response.get("success", False)
    
    def disconnect(self) -> bool:
        """断开连接"""
        response = self._send_request("disconnect", {
            "restart": False,
        })
        
        return response and response.get("success", False)
    
    def set_breakpoints(self, file_path: str, breakpoints: List[SourceBreakpoint]) -> List[Breakpoint]:
        """
        设置断点
        
        Args:
            file_path: 文件路径
            breakpoints: 断点列表
        
        Returns:
            设置的断点列表
        """
        # 构造断点参数
        bp_args = []
        for bp in breakpoints:
            bp_arg = {"line": bp.line}
            if bp.column:
                bp_arg["column"] = bp.column
            if bp.condition:
                bp_arg["condition"] = bp.condition
            if bp.hitCondition:
                bp_arg["hitCondition"] = bp.hitCondition
            if bp.logMessage:
                bp_arg["logMessage"] = bp.logMessage
            bp_args.append(bp_arg)
        
        # 发送请求
        response = self._send_request("setBreakpoints", {
            "source": {
                "path": file_path,
            },
            "breakpoints": bp_args,
        })
        
        if response and response.get("success", False):
            # 解析返回的断点
            body = response.get("body", {})
            breakpoints_result = []
            
            for bp_data in body.get("breakpoints", []):
                bp = Breakpoint(
                    id=bp_data.get("id", 0),
                    verified=bp_data.get("verified", False),
                    message=bp_data.get("message", ""),
                    line=bp_data.get("line", 0),
                    column=bp_data.get("column", 0),
                )
                breakpoints_result.append(bp)
            
            self._breakpoints[file_path] = breakpoints_result
            return breakpoints_result
        
        return []
    
    def configuration_done(self) -> bool:
        """配置完成"""
        response = self._send_request("configurationDone")
        return response and response.get("success", False)
    
    def continue_execution(self, threadId: int = 0) -> bool:
        """继续执行"""
        response = self._send_request("continue", {
            "threadId": threadId,
        })
        return response and response.get("success", False)
    
    def pause(self, threadId: int = 0) -> bool:
        """暂停执行"""
        response = self._send_request("pause", {
            "threadId": threadId,
        })
        return response and response.get("success", False)
    
    def step_over(self, threadId: int) -> bool:
        """单步跳过"""
        response = self._send_request("next", {
            "threadId": threadId,
        })
        return response and response.get("success", False)
    
    def step_into(self, threadId: int) -> bool:
        """单步进入"""
        response = self._send_request("stepIn", {
            "threadId": threadId,
        })
        return response and response.get("success", False)
    
    def step_out(self, threadId: int) -> bool:
        """单步退出"""
        response = self._send_request("stepOut", {
            "threadId": threadId,
        })
        return response and response.get("success", False)
    
    def stack_trace(self, threadId: int) -> List[StackFrame]:
        """获取调用栈"""
        response = self._send_request("stackTrace", {
            "threadId": threadId,
        })
        
        if response and response.get("success", False):
            body = response.get("body", {})
            frames = []
            
            for frame_data in body.get("stackFrames", []):
                source = None
                if frame_data.get("source"):
                    src_data = frame_data["source"]
                    source = Source(
                        name=src_data.get("name", ""),
                        path=src_data.get("path", ""),
                        sourceReference=src_data.get("sourceReference", 0),
                    )
                
                frame = StackFrame(
                    id=frame_data.get("id", 0),
                    name=frame_data.get("name", ""),
                    source=source,
                    line=frame_data.get("line", 0),
                    column=frame_data.get("column", 0),
                )
                frames.append(frame)
            
            self._call_stack[threadId] = frames
            return frames
        
        return []
    
    def scopes(self, frameId: int) -> List[Scope]:
        """获取作用域"""
        response = self._send_request("scopes", {
            "frameId": frameId,
        })
        
        if response and response.get("success", False):
            body = response.get("body", {})
            scopes = []
            
            for scope_data in body.get("scopes", []):
                scope = Scope(
                    name=scope_data.get("name", ""),
                    variablesReference=scope_data.get("variablesReference", 0),
                    expensive=scope_data.get("expensive", False),
                )
                scopes.append(scope)
            
            self._scopes[frameId] = scopes
            return scopes
        
        return []
    
    def variables(self, variablesReference: int) -> List[Variable]:
        """获取变量"""
        response = self._send_request("variables", {
            "variablesReference": variablesReference,
        })
        
        if response and response.get("success", False):
            body = response.get("body", {})
            variables = []
            
            for var_data in body.get("variables", []):
                var = Variable(
                    name=var_data.get("name", ""),
                    value=var_data.get("value", ""),
                    type=var_data.get("type", ""),
                    evaluateName=var_data.get("evaluateName"),
                    variablesReference=var_data.get("variablesReference", 0),
                )
                variables.append(var)
            
            self._variables[variablesReference] = variables
            return variables
        
        return []
    
    def threads(self) -> List[int]:
        """获取线程列表"""
        response = self._send_request("threads")
        
        if response and response.get("success", False):
            body = response.get("body", {})
            threads = []
            
            for thread_data in body.get("threads", []):
                threads.append(thread_data.get("id", 0))
            
            self._threads = threads
            return threads
        
        return []
    
    def evaluate(self, expression: str, frameId: int = None) -> Optional[str]:
        """评估表达式"""
        arguments = {"expression": expression}
        if frameId:
            arguments["frameId"] = frameId
        
        response = self._send_request("evaluate", arguments)
        
        if response and response.get("success", False):
            body = response.get("body", {})
            return body.get("result", "")

        return None

    # ============================================================
    # ★ 便捷方法（v0.6.1 新增 — 符合用户 API 要求）
    # ============================================================

    def start_debug(self, program: str, args: list = None, cwd: str = "") -> bool:
        """启动调试会话（高级封装：启动适配器 → 初始化 → 启动程序 → 配置完成）

        Args:
            program: 要调试的 Python 文件路径
            args: 程序参数列表
            cwd: 工作目录

        Returns:
            是否成功启动
        """
        import sys as _sys
        # 1. 启动 debugpy 适配器进程
        if not self.start_debugger("python", cwd):
            return False

        # 2. 初始化 DAP 会话
        if not self.initialize():
            self.error_occurred.emit("DAP initialize 失败")
            self.stop_debugger()
            return False

        # 3. 设置已注册的断点
        all_bps = dict(self._breakpoints)
        for file_path, bps in all_bps.items():
            source_bps = [
                SourceBreakpoint(line=bp.line, condition=None)
                for bp in bps if bp.verified or True  # 尝试设置所有断点
            ]
            if source_bps:
                self.set_breakpoints(file_path, source_bps)

        # 4. 启动目标程序
        launch_args = {
            "program": program,
            "noDebug": False,
            "stopOnEntry": True,
            "args": args or [],
            "env": dict(os.environ),
            "python": _sys.executable,  # 使用当前 Python 解释器
        }
        if cwd:
            launch_args["cwd"] = cwd

        response = self._send_request("launch", launch_args, timeout=15)
        if not response or not response.get("success", False):
            self.error_occurred.emit("DAP launch 失败")
            self.stop_debugger()
            return False

        self._is_running = True

        # 5. 通知适配器配置完成
        self.configuration_done()

        return True

    def set_breakpoints_simple(self, file: str, lines: list) -> list:
        """简化版设置断点（只需文件路径和行号列表）

        Args:
            file: 文件路径
            lines: 断点行号列表，如 [10, 25, 42]

        Returns:
            设置成功的断点列表
        """
        source_bps = [SourceBreakpoint(line=line) for line in lines]
        return self.set_breakpoints(file, source_bps)

    def continue_execution(self) -> bool:
        """继续执行（使用当前线程）"""
        if self._current_thread_id == 0:
            threads = self.threads()
            if threads:
                self._current_thread_id = threads[0]
        return self._send_request_bool("continue", {"threadId": self._current_thread_id})

    def step_over(self) -> bool:
        """单步跳过（使用当前线程）"""
        return self._send_request_bool("next", {"threadId": self._current_thread_id})

    def step_into(self) -> bool:
        """单步进入（使用当前线程）"""
        return self._send_request_bool("stepIn", {"threadId": self._current_thread_id})

    def step_out(self) -> bool:
        """单步跳出（使用当前线程）"""
        return self._send_request_bool("stepOut", {"threadId": self._current_thread_id})

    def get_stack_trace(self) -> list:
        """获取调用栈（使用当前线程）

        Returns:
            调用栈帧列表，每帧为 dict: {id, name, file, line, column}
        """
        if self._current_thread_id == 0:
            threads = self.threads()
            if threads:
                self._current_thread_id = threads[0]
            else:
                return []

        frames = self.stack_trace(self._current_thread_id)
        # 转为可序列化的 dict 列表
        result = []
        for f in frames:
            result.append({
                "id": f.id,
                "name": f.name,
                "file": f.source.path if f.source else "",
                "line": f.line,
                "column": f.column,
            })
        # ★ 保存当前栈帧 ID
        if result:
            self._current_frame_id = result[0]["id"]
        return result

    def get_variables(self, scope: str = "local") -> list:
        """获取变量列表

        Args:
            scope: "local"（局部变量）/ "global"（全局变量）/ "watch"（监视）

        Returns:
            变量列表，每个变量为 dict: {name, value, type}
        """
        if self._current_frame_id == 0:
            # 尝试获取调用栈以得到 frameId
            self.get_stack_trace()
            if self._current_frame_id == 0:
                return []

        # 获取作用域
        scope_list = self.scopes(self._current_frame_id)
        if not scope_list:
            return []

        # 更新作用域引用映射
        for s in scope_list:
            self._scope_refs[s.name.lower()] = s.variablesReference

        # 选择目标作用域
        scope_lower = scope.lower()
        target_ref = 0
        if scope_lower in ("local", "locals"):
            # 查找 "Locals" 作用域
            target_ref = self._scope_refs.get("locals", 0)
        elif scope_lower in ("global", "globals"):
            target_ref = self._scope_refs.get("globals", 0)
        else:
            # 默认取第一个作用域
            target_ref = scope_list[0].variablesReference

        if target_ref == 0:
            return []

        vars_list = self.variables(target_ref)
        # 转为可序列化的 dict 列表
        return [
            {
                "name": v.name,
                "value": v.value,
                "type": v.type,
                "evaluateName": v.evaluateName or v.name,
            }
            for v in vars_list
        ]

    def evaluate_expression(self, expr: str) -> str:
        """表达式求值

        Args:
            expr: 表达式字符串

        Returns:
            求值结果字符串，失败返回空字符串
        """
        result = self.evaluate(expr, self._current_frame_id if self._current_frame_id else None)
        return result if result else ""

    def stop_debug(self) -> bool:
        """停止调试会话"""
        try:
            self.disconnect()
        except Exception:
            pass
        self.stop_debugger()
        return True

    def _send_request_bool(self, command: str, arguments: dict = None) -> bool:
        """发送请求并返回布尔结果"""
        response = self._send_request(command, arguments)
        return response is not None and response.get("success", False)

    def get_all_breakpoints(self) -> list:
        """获取所有断点（可序列化格式）

        Returns:
            断点列表: [{file, line, verified, message}]
        """
        result = []
        for file_path, bps in self._breakpoints.items():
            for bp in bps:
                result.append({
                    "file": file_path,
                    "line": bp.line,
                    "verified": bp.verified,
                    "message": bp.message,
                })
        return result

    def clear_breakpoints(self, file_path: str = None) -> bool:
        """清除断点

        Args:
            file_path: 指定文件路径，None 则清除所有

        Returns:
            是否成功
        """
        if file_path:
            # 清除指定文件的断点（发送空断点列表）
            response = self._send_request("setBreakpoints", {
                "source": {"path": file_path},
                "breakpoints": [],
            })
            self._breakpoints.pop(file_path, None)
            return response is not None and response.get("success", False)
        else:
            # 清除所有断点
            for fp in list(self._breakpoints.keys()):
                self._send_request("setBreakpoints", {
                    "source": {"path": fp},
                    "breakpoints": [],
                })
            self._breakpoints.clear()
            return True