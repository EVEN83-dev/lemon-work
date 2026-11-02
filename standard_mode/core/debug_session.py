# -*- coding: utf-8 -*-
"""
调试会话管理器（v0.6.0 新增）
================================
功能：
- 调试会话生命周期管理
- 断点管理（添加/删除/启用/禁用）
- 变量监视
- 调用栈管理
- 多线程调试
- 调试状态机

架构：
┌─────────────────────────────────────┐
│      DebugSessionManager             │
│  ┌────────────────────────────────┐ │
│  │ DAPClient                      │ │
│  └────────────────────────────────┘ │
│  ┌────────────────────────────────┐ │
│  │ 断点管理器                      │ │
│  │ 变量监视器                      │ │
│  │ 调用栈追踪器                    │ │
│  └────────────────────────────────┘ │
└─────────────────────────────────────┘
"""

import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from core.dap_client import DAPClient, SourceBreakpoint, Breakpoint, StackFrame, Variable


# ============================================================
# 调试状态
# ============================================================

class DebugState(Enum):
    """调试状态"""
    IDLE = "idle"                    # 空闲
    INITIALIZING = "initializing"   # 初始化中
    RUNNING = "running"             # 运行中
    STOPPED = "stopped"             # 停止（断点/步进）
    PAUSED = "paused"               # 暂停
    TERMINATED = "terminated"       # 终止


# ============================================================
# 断点管理
# ============================================================

@dataclass
class BreakpointInfo:
    """断点信息（扩展）"""
    id: int
    file_path: str
    line: int
    column: Optional[int] = None
    condition: Optional[str] = None
    hit_count: int = 0
    enabled: bool = True
    verified: bool = False
    message: str = ""


class BreakpointManager:
    """断点管理器"""
    
    def __init__(self):
        self._breakpoints: Dict[str, Dict[int, BreakpointInfo]] = {}  # {file_path: {line: breakpoint}}
    
    def add_breakpoint(self, file_path: str, line: int, condition: str = None) -> BreakpointInfo:
        """添加断点"""
        if file_path not in self._breakpoints:
            self._breakpoints[file_path] = {}
        
        # 生成临时ID
        bp_id = hash(f"{file_path}:{line}")
        
        bp = BreakpointInfo(
            id=bp_id,
            file_path=file_path,
            line=line,
            condition=condition,
        )
        
        self._breakpoints[file_path][line] = bp
        return bp
    
    def remove_breakpoint(self, file_path: str, line: int) -> bool:
        """移除断点"""
        if file_path in self._breakpoints:
            if line in self._breakpoints[file_path]:
                del self._breakpoints[file_path][line]
                return True
        
        return False
    
    def toggle_breakpoint(self, file_path: str, line: int) -> bool:
        """切换断点状态"""
        if file_path in self._breakpoints:
            if line in self._breakpoints[file_path]:
                # 移除断点
                return self.remove_breakpoint(file_path, line)
        
        # 添加断点
        self.add_breakpoint(file_path, line)
        return True
    
    def get_breakpoints(self, file_path: str) -> List[BreakpointInfo]:
        """获取文件的所有断点"""
        return list(self._breakpoints.get(file_path, {}).values())
    
    def get_all_breakpoints(self) -> Dict[str, List[BreakpointInfo]]:
        """获取所有断点"""
        return {fp: list(bps.values()) for fp, bps in self._breakpoints.items()}
    
    def update_breakpoint(self, bp_id: int, **kwargs):
        """更新断点属性"""
        for file_path, bps in self._breakpoints.items():
            for line, bp in bps.items():
                if bp.id == bp_id:
                    for key, value in kwargs.items():
                        if hasattr(bp, key):
                            setattr(bp, key, value)
                    return True
        
        return False
    
    def clear_all_breakpoints(self):
        """清除所有断点"""
        self._breakpoints.clear()


# ============================================================
# 变量监视
# ============================================================

class WatchManager:
    """变量监视器"""
    
    def __init__(self):
        self._watch_expressions: List[str] = []
        self._watch_values: Dict[str, str] = {}
    
    def add_watch(self, expression: str):
        """添加监视表达式"""
        if expression not in self._watch_expressions:
            self._watch_expressions.append(expression)
    
    def remove_watch(self, expression: str):
        """移除监视表达式"""
        if expression in self._watch_expressions:
            self._watch_expressions.remove(expression)
            self._watch_values.pop(expression, None)
    
    def update_watch_value(self, expression: str, value: str):
        """更新监视值"""
        self._watch_values[expression] = value
    
    def get_watches(self) -> List[Dict]:
        """获取所有监视表达式和值"""
        return [
            {
                "expression": exp,
                "value": self._watch_values.get(exp, "<not evaluated>"),
            }
            for exp in self._watch_expressions
        ]


# ============================================================
# 调试会话管理器
# ============================================================

class DebugSessionManager(QObject):
    """
    调试会话管理器
    
    功能：
    - 管理调试会话生命周期
    - 断点管理
    - 变量监视
    - 调用栈追踪
    - 调试控制（启动/停止/暂停/继续）
    """
    
    # 信号
    state_changed = pyqtSignal(str)  # (state)
    breakpoint_added = pyqtSignal(str, int)  # (file_path, line)
    breakpoint_removed = pyqtSignal(str, int)  # (file_path, line)
    breakpoint_hit = pyqtSignal(str, int)  # (file_path, line)
    output_received = pyqtSignal(str, str)  # (category, text)
    call_stack_updated = pyqtSignal(list)  # (frames)
    variables_updated = pyqtSignal(list)  # (variables)
    error_occurred = pyqtSignal(str)  # (error_message)
    
    def __init__(self):
        super().__init__()
        
        # DAP 客户端
        self.dap_client = DAPClient()
        
        # 断点管理器
        self.bp_manager = BreakpointManager()
        
        # 变量监视器
        self.watch_manager = WatchManager()
        
        # 当前状态
        self._state = DebugState.IDLE
        
        # 当前线程ID
        self._current_thread_id = 0
        
        # 当前调用栈
        self._current_frames: List[StackFrame] = []
        
        # 当前变量
        self._current_variables: List[Variable] = []
        
        # 调试程序信息
        self._program: str = ""
        self._cwd: str = ""
        
        # 连接 DAP 客户端信号
        self._connect_signals()
    
    @property
    def state(self) -> DebugState:
        return self._state
    
    @property
    def current_thread_id(self) -> int:
        return self._current_thread_id
    
    @property
    def current_frames(self) -> List[StackFrame]:
        return self._current_frames
    
    @property
    def current_variables(self) -> List[Variable]:
        return self._current_variables
    
    def _connect_signals(self):
        """连接 DAP 客户端信号"""
        self.dap_client.initialized.connect(self._on_initialized)
        self.dap_client.stopped.connect(self._on_stopped)
        self.dap_client.continued.connect(self._on_continued)
        self.dap_client.breakpoint_changed.connect(self._on_breakpoint_changed)
        self.dap_client.output_received.connect(self._on_output_received)
        self.dap_client.terminated.connect(self._on_terminated)
        self.dap_client.error_occurred.connect(self._on_error)
    
    def _set_state(self, new_state: DebugState):
        """设置调试状态"""
        if self._state != new_state:
            self._state = new_state
            self.state_changed.emit(new_state.value)
    
    # ============================================================
    # 调试控制
    # ============================================================
    
    def start_debugging(self, program: str, cwd: str = "", adapter_type: str = "python") -> bool:
        """
        启动调试
        
        Args:
            program: 程序路径
            cwd: 工作目录
            adapter_type: 调试器类型（python/node）
        
        Returns:
            是否启动成功
        """
        self._program = program
        self._cwd = cwd or os.path.dirname(program)
        
        self._set_state(DebugState.INITIALIZING)
        
        # 启动调试器进程
        if not self.dap_client.start_debugger(adapter_type, self._cwd):
            self._set_state(DebugState.IDLE)
            return False
        
        # 等待初始化（异步）
        # 实际初始化在 _on_initialized 回调中完成
        return True
    
    def _on_initialized(self):
        """调试器初始化完成"""
        # 发送初始化请求
        if not self.dap_client.initialize():
            self.error_occurred.emit("调试器初始化失败")
            self.stop_debugging()
            return
        
        # 设置断点
        all_breakpoints = self.bp_manager.get_all_breakpoints()
        for file_path, breakpoints in all_breakpoints.items():
            source_bps = [
                SourceBreakpoint(
                    line=bp.line,
                    condition=bp.condition,
                )
                for bp in breakpoints if bp.enabled
            ]
            
            if source_bps:
                self.dap_client.set_breakpoints(file_path, source_bps)
        
        # 启动程序
        if not self.dap_client.launch(self._program):
            self.error_occurred.emit("启动程序失败")
            self.stop_debugging()
            return
        
        # 配置完成
        self.dap_client.configuration_done()
        
        self._set_state(DebugState.RUNNING)
    
    def stop_debugging(self):
        """停止调试"""
        if self._state == DebugState.IDLE:
            return
        
        self.dap_client.disconnect()
        self.dap_client.stop_debugger()
        
        self._set_state(DebugState.IDLE)
        self._current_thread_id = 0
        self._current_frames.clear()
        self._current_variables.clear()
    
    def restart_debugging(self) -> bool:
        """重启调试"""
        self.stop_debugging()
        # 等待一小段时间
        QTimer.singleShot(500, lambda: self.start_debugging(self._program, self._cwd))
    
    def continue_execution(self) -> bool:
        """继续执行"""
        if self._state != DebugState.STOPPED:
            return False
        
        success = self.dap_client.continue_execution(self._current_thread_id)
        if success:
            self._set_state(DebugState.RUNNING)
        
        return success
    
    def pause_execution(self) -> bool:
        """暂停执行"""
        if self._state != DebugState.RUNNING:
            return False
        
        success = self.dap_client.pause(self._current_thread_id)
        if success:
            self._set_state(DebugState.PAUSED)
        
        return success
    
    def step_over(self) -> bool:
        """单步跳过"""
        if self._state != DebugState.STOPPED:
            return False
        
        return self.dap_client.step_over(self._current_thread_id)
    
    def step_into(self) -> bool:
        """单步进入"""
        if self._state != DebugState.STOPPED:
            return False
        
        return self.dap_client.step_into(self._current_thread_id)
    
    def step_out(self) -> bool:
        """单步退出"""
        if self._state != DebugState.STOPPED:
            return False
        
        return self.dap_client.step_out(self._current_thread_id)
    
    # ============================================================
    # 断点管理
    # ============================================================
    
    def add_breakpoint(self, file_path: str, line: int, condition: str = None) -> BreakpointInfo:
        """添加断点"""
        bp = self.bp_manager.add_breakpoint(file_path, line, condition)
        self.breakpoint_added.emit(file_path, line)
        
        # 如果正在调试，动态添加断点
        if self._state in [DebugState.RUNNING, DebugState.STOPPED, DebugState.PAUSED]:
            source_bp = SourceBreakpoint(line=line, condition=condition)
            self.dap_client.set_breakpoints(file_path, [source_bp])
        
        return bp
    
    def remove_breakpoint(self, file_path: str, line: int) -> bool:
        """移除断点"""
        success = self.bp_manager.remove_breakpoint(file_path, line)
        if success:
            self.breakpoint_removed.emit(file_path, line)
            
            # 如果正在调试，动态移除断点
            if self._state in [DebugState.RUNNING, DebugState.STOPPED, DebugState.PAUSED]:
                # 重新设置该文件的所有断点（DAP协议不支持单独删除）
                bps = self.bp_manager.get_breakpoints(file_path)
                source_bps = [SourceBreakpoint(line=bp.line, condition=bp.condition) for bp in bps]
                self.dap_client.set_breakpoints(file_path, source_bps)
        
        return success
    
    def toggle_breakpoint(self, file_path: str, line: int) -> bool:
        """切换断点"""
        if file_path in self.bp_manager._breakpoints:
            if line in self.bp_manager._breakpoints[file_path]:
                return self.remove_breakpoint(file_path, line)
        
        self.add_breakpoint(file_path, line)
        return True
    
    def get_breakpoints(self, file_path: str) -> List[BreakpointInfo]:
        """获取文件的断点列表"""
        return self.bp_manager.get_breakpoints(file_path)
    
    def get_all_breakpoints(self) -> Dict[str, List[BreakpointInfo]]:
        """获取所有断点"""
        return self.bp_manager.get_all_breakpoints()
    
    # ============================================================
    # 变量监视
    # ============================================================
    
    def add_watch(self, expression: str):
        """添加监视表达式"""
        self.watch_manager.add_watch(expression)
        self._update_watches()
    
    def remove_watch(self, expression: str):
        """移除监视表达式"""
        self.watch_manager.remove_watch(expression)
    
    def get_watches(self) -> List[Dict]:
        """获取所有监视表达式"""
        return self.watch_manager.get_watches()
    
    def _update_watches(self):
        """更新监视表达式的值"""
        if self._state != DebugState.STOPPED:
            return
        
        for exp in self.watch_manager._watch_expressions:
            value = self.dap_client.evaluate(exp)
            if value:
                self.watch_manager.update_watch_value(exp, value)
    
    # ============================================================
    # 回调处理
    # ============================================================
    
    def _on_stopped(self, reason: str, threadId: int, message: str):
        """调试器停止"""
        self._current_thread_id = threadId
        self._set_state(DebugState.STOPPED)
        
        # 更新调用栈
        frames = self.dap_client.stack_trace(threadId)
        self._current_frames = frames
        self.call_stack_updated.emit(frames)
        
        # 更新变量
        if frames:
            scopes = self.dap_client.scopes(frames[0].id)
            if scopes:
                variables = self.dap_client.variables(scopes[0].variablesReference)
                self._current_variables = variables
                self.variables_updated.emit(variables)
        
        # 更新监视表达式
        self._update_watches()
        
        # 如果是断点命中
        if reason == "breakpoint":
            # 找到当前断点位置
            if frames and frames[0].source:
                file_path = frames[0].source.path
                line = frames[0].line
                self.breakpoint_hit.emit(file_path, line)
    
    def _on_continued(self, threadId: int):
        """调试器继续执行"""
        self._set_state(DebugState.RUNNING)
    
    def _on_breakpoint_changed(self, breakpoint: Dict):
        """断点状态变化"""
        bp_id = breakpoint.get("id")
        verified = breakpoint.get("verified", False)
        message = breakpoint.get("message", "")
        
        # 更新断点状态
        self.bp_manager.update_breakpoint(bp_id, verified=verified, message=message)
    
    def _on_output_received(self, category: str, output: str):
        """接收输出"""
        self.output_received.emit(category, output)
    
    def _on_terminated(self):
        """调试器终止"""
        self._set_state(DebugState.TERMINATED)
        # ★ 调用终止回调
        if hasattr(self, '_on_terminated_cb') and self._on_terminated_cb:
            try:
                self._on_terminated_cb(self)
            except Exception as e:
                print(f"[Debug] terminated 回调异常: {e}")

    def _on_error(self, error: str):
        """错误发生"""
        self.error_occurred.emit(error)

    # ============================================================
    # ★ 事件回调注册（v0.6.1 新增）
    # ============================================================

    def on_breakpoint_hit(self, callback):
        """注册断点命中回调 callback(session, file_path, line)"""
        self._on_bp_hit_cb = callback

    def on_exception(self, callback):
        """注册异常回调 callback(session, exception_info)"""
        self._on_exception_cb = callback

    def on_terminated(self, callback):
        """注册终止回调 callback(session)"""
        self._on_terminated_cb = callback

    def on_state_changed(self, callback):
        """注册状态变更回调 callback(session, new_state)"""
        self._on_state_cb = callback

    def on_output(self, callback):
        """注册输出回调 callback(session, category, text)"""
        self._on_output_cb = callback


# ============================================================
# ★ 多会话调试管理器（v0.6.1 新增）
# ============================================================

class MultiSessionDebugManager(QObject):
    """多会话调试管理器 — 同时调试多个程序

    管理多个 DebugSessionManager 实例，每个对应一个调试目标。
    """

    # 信号
    session_started = pyqtSignal(str)   # (session_id)
    session_stopped = pyqtSignal(str)   # (session_id)
    session_switched = pyqtSignal(str)  # (session_id)
    state_changed = pyqtSignal(str, str)  # (session_id, state)
    breakpoint_hit = pyqtSignal(str, str, int)  # (session_id, file, line)
    output_received = pyqtSignal(str, str, str)  # (session_id, category, text)
    error_occurred = pyqtSignal(str, str)  # (session_id, error)

    def __init__(self):
        super().__init__()
        self._sessions: Dict[str, DebugSessionManager] = {}
        self._active_session_id: str = ""
        self._counter = 0

    @property
    def active_session(self) -> Optional[DebugSessionManager]:
        if self._active_session_id and self._active_session_id in self._sessions:
            return self._sessions[self._active_session_id]
        return None

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def list_sessions(self) -> list:
        """列出所有调试会话"""
        result = []
        for sid, s in self._sessions.items():
            result.append({
                "id": sid,
                "program": s._program,
                "state": s.state.value,
                "active": sid == self._active_session_id,
            })
        return result

    def create_session(self, program: str, cwd: str = "") -> str:
        """创建新的调试会话（不启动）

        Args:
            program: 要调试的程序路径
            cwd: 工作目录

        Returns:
            会话 ID
        """
        self._counter += 1
        session_id = f"debug_{self._counter}"

        session = DebugSessionManager()

        # 注册回调
        def _bp_cb(s, file_path, line):
            self.breakpoint_hit.emit(session_id, file_path, line)

        def _term_cb(s):
            self.session_stopped.emit(session_id)

        def _state_cb(s, state):
            self.state_changed.emit(session_id, state)

        def _out_cb(s, category, text):
            self.output_received.emit(session_id, category, text)

        def _err_cb(error):
            self.error_occurred.emit(session_id, error)

        session.on_breakpoint_hit(lambda fp, l: self.breakpoint_hit.emit(session_id, fp, l))
        session.on_terminated(lambda: self.session_stopped.emit(session_id))
        session.state_changed.connect(lambda state: self.state_changed.emit(session_id, state))
        session.breakpoint_hit.connect(lambda fp, l: self._on_bp_hit(session_id, fp, l))
        session.output_received.connect(lambda cat, txt: self.output_received.emit(session_id, cat, txt))
        session.error_occurred.connect(lambda err: self.error_occurred.emit(session_id, err))

        session._program = program
        session._cwd = cwd or os.path.dirname(program)

        self._sessions[session_id] = session
        self._active_session_id = session_id
        self.session_started.emit(session_id)
        self.session_switched.emit(session_id)

        return session_id

    def _on_bp_hit(self, session_id: str, file_path: str, line: int):
        """断点命中内部处理"""
        self.breakpoint_hit.emit(session_id, file_path, line)
        # ★ 发布断点命中事件
        try:
            from event_bus import EventBus, EventType
            EventBus.instance().publish(EventType.BREAKPOINT_HIT, {
                "session_id": session_id,
                "file": file_path,
                "line": line,
            })
        except Exception:
            pass

    def start_session(self, session_id: str, program: str = "", args: list = None, cwd: str = "") -> bool:
        """启动指定会话的调试"""
        session = self._sessions.get(session_id)
        if not session:
            return False

        prog = program or session._program
        work_dir = cwd or session._cwd

        # 使用 DAPClient 的便捷方法
        try:
            # 启动调试器进程并初始化
            if not session.dap_client.start_debug(prog, args or [], work_dir):
                return False
            session._set_state(DebugState.RUNNING)
            # ★ 发布调试启动事件
            try:
                from event_bus import EventBus, EventType
                EventBus.instance().publish(EventType.DEBUG_STARTED, {
                    "session_id": session_id,
                    "program": prog,
                    "cwd": work_dir,
                })
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[Debug] 启动会话失败: {e}")
            self.error_occurred.emit(session_id, str(e))
            return False

    def stop_session(self, session_id: str) -> bool:
        """停止指定会话"""
        session = self._sessions.get(session_id)
        if not session:
            return False
        try:
            session.dap_client.stop_debug()
            session._set_state(DebugState.TERMINATED)
            self.session_stopped.emit(session_id)
            # ★ 发布调试停止事件
            try:
                from event_bus import EventBus, EventType
                EventBus.instance().publish(EventType.DEBUG_STOPPED, {
                    "session_id": session_id,
                })
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[Debug] 停止会话失败: {e}")
            return False

    def remove_session(self, session_id: str) -> bool:
        """移除会话"""
        if session_id not in self._sessions:
            return False
        self.stop_session(session_id)
        del self._sessions[session_id]
        if self._active_session_id == session_id:
            # 切换到第一个可用会话
            self._active_session_id = next(iter(self._sessions), "")
            if self._active_session_id:
                self.session_switched.emit(self._active_session_id)
        return True

    def switch_session(self, session_id: str) -> bool:
        """切换活动会话"""
        if session_id not in self._sessions:
            return False
        self._active_session_id = session_id
        self.session_switched.emit(session_id)
        return True

    def get_active_session(self) -> Optional[DebugSessionManager]:
        return self.active_session

    # ============================================================
    # 便捷方法 — 代理到活动会话
    # ============================================================

    def start_debug(self, program: str, args: list = None, cwd: str = "") -> dict:
        """启动调试（创建 + 启动）

        Returns:
            {"session_id": "...", "success": bool}
        """
        session_id = self.create_session(program, cwd)
        ok = self.start_session(session_id, program, args, cwd)
        return {"session_id": session_id, "success": ok}

    def set_breakpoints(self, file: str, lines: list) -> list:
        """设置断点（活动会话）"""
        s = self.active_session
        if not s:
            return []
        return s.dap_client.set_breakpoints_simple(file, lines)

    def toggle_breakpoint(self, file: str, line: int) -> bool:
        """切换断点（活动会话）"""
        s = self.active_session
        if not s:
            # 无活动会话时仅记录到断点管理器
            return False
        return s.toggle_breakpoint(file, line)

    def continue_execution(self) -> bool:
        """继续执行（活动会话）"""
        s = self.active_session
        if not s:
            return False
        return s.dap_client.continue_execution()

    def step_over(self) -> bool:
        s = self.active_session
        return s.dap_client.step_over() if s else False

    def step_into(self) -> bool:
        s = self.active_session
        return s.dap_client.step_into() if s else False

    def step_out(self) -> bool:
        s = self.active_session
        return s.dap_client.step_out() if s else False

    def pause_execution(self) -> bool:
        s = self.active_session
        if not s:
            return False
        if s.state != DebugState.RUNNING:
            return False
        return s.dap_client.pause(s.current_thread_id)

    def stop_debug(self) -> bool:
        """停止当前活动会话"""
        s = self.active_session
        if not s:
            return False
        return self.stop_session(self._active_session_id)

    def get_variables(self, scope: str = "local") -> list:
        """获取变量（活动会话）"""
        s = self.active_session
        if not s:
            return []
        return s.dap_client.get_variables(scope)

    def get_stack_trace(self) -> list:
        """获取调用栈（活动会话）"""
        s = self.active_session
        if not s:
            return []
        return s.dap_client.get_stack_trace()

    def evaluate_expression(self, expr: str) -> str:
        """表达式求值（活动会话）"""
        s = self.active_session
        if not s:
            return ""
        return s.dap_client.evaluate_expression(expr)

    def get_all_breakpoints(self) -> list:
        """获取所有断点（活动会话）"""
        s = self.active_session
        if not s:
            # 从断点管理器获取
            return []
        result = []
        all_bps = s.bp_manager.get_all_breakpoints()
        for file_path, bps in all_bps.items():
            for bp in bps:
                result.append({
                    "file": file_path,
                    "line": bp.line,
                    "enabled": bp.enabled,
                    "condition": bp.condition or "",
                })
        return result

    def remove_breakpoint(self, file: str, line: int) -> bool:
        """移除断点（活动会话）"""
        s = self.active_session
        if not s:
            return False
        return s.remove_breakpoint(file, line)

    def get_state(self) -> str:
        """获取活动会话状态"""
        s = self.active_session
        return s.state.value if s else "idle"


# ============================================================
# 模块级单例
# ============================================================
_debug_manager: Optional[MultiSessionDebugManager] = None


def get_debug_manager() -> MultiSessionDebugManager:
    global _debug_manager
    if _debug_manager is None:
        _debug_manager = MultiSessionDebugManager()
    return _debug_manager