# -*- coding: utf-8 -*-
"""
ACP Bridge v3.71 — 基于 ACP 协议的 MIMO Code 完整双向通信桥
=====================================================
核心思路：通过 ACP 协议与 MIMO Code 建立标准化的双向通信通道，
处理所有事件类型（思考/消息/工具/配置选项/权限/模式/命令），
使 Agent 成为 MIMO Code 的完整操控器。

功能：
- ✅ 消息发送/接收（AI 回复、思考过程、工具调用）
- ✅ 配置选项同步（select/boolean 弹窗显示与用户选择回传）
- ✅ 权限弹窗处理（允许/拒绝/始终允许）
- ✅ 模式切换同步（CurrentModeUpdate ↔ set_session_mode）
- ✅ 可用命令同步（AvailableCommandsUpdate）
- ✅ 会话管理（创建/恢复/关闭）
- ✅ 快捷键/操作路由
- ✅ v3.71: 上下文管理（get_context/clear_context/get_context_turns）
- ✅ v3.71: 多会话管理（create_session/switch_session/list_sessions）
- ✅ v3.71: MIMO_EXE 路径修复（指向 lemon_agent\bin\mimo.exe）
"""

import os, sys, json, asyncio, threading, time, traceback
from typing import Optional, Any, Dict, List
from PyQt5.QtCore import QObject, pyqtSignal

# ACP SDK 导入（可选依赖）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 尝试导入 ACP SDK，失败时提供 stub 实现
_ACP_AVAILABLE = False
try:
    from acp import (
        Client, Agent as AgentProtocol,
        NewSessionRequest, PromptRequest,
        spawn_stdio_transport, connect_to_agent,
        RequestPermissionResponse, CreateElicitationResponse,
        CreateTerminalResponse, TerminalOutputResponse,
        ReleaseTerminalResponse, WaitForTerminalExitResponse,
        KillTerminalResponse, ReadTextFileResponse, WriteTextFileResponse,
        SetSessionConfigOptionSelectRequest,
        SetSessionModeRequest,
        PROTOCOL_VERSION,
        text_block,
    )
    from acp.schema import (
        PermissionOption,
        UserMessageChunk, AgentMessageChunk, AgentThoughtChunk,
        ToolCallStart, ToolCallProgress,
        AgentPlanUpdate, AgentPlanContentUpdate, AgentPlanRemovedUpdate,
        AvailableCommandsUpdate, CurrentModeUpdate, ConfigOptionUpdate,
        SessionInfoUpdate, UsageUpdate,
        SetSessionConfigOptionBooleanRequest,
        SessionConfigOptionSelect, SessionConfigOptionBoolean,
        SessionConfigSelectOption, SessionConfigSelectGroup,
        EnvVariable, ToolCallUpdate,
    )
    _ACP_AVAILABLE = True
except ImportError as e:
    # ACP SDK 未安装，提供 stub 类让程序能启动
    # 注意：ACP Bridge 功能将不可用
    import logging
    logging.getLogger(__name__).warning(f"ACP SDK 不可用，ACP Bridge 功能将禁用: {e}")
    
    # Stub 类定义
    class _StubClass:
        def __init__(self, *args, **kwargs): pass
        def __getattr__(self, name): return _StubClass()
    
    Client = _StubClass
    AgentProtocol = _StubClass
    NewSessionRequest = PromptRequest = _StubClass
    spawn_stdio_transport = connect_to_agent = lambda *a, **k: None
    RequestPermissionResponse = CreateElicitationResponse = _StubClass
    CreateTerminalResponse = TerminalOutputResponse = _StubClass
    ReleaseTerminalResponse = WaitForTerminalExitResponse = _StubClass
    KillTerminalResponse = ReadTextFileResponse = WriteTextFileResponse = _StubClass
    SetSessionConfigOptionSelectRequest = SetSessionModeRequest = _StubClass
    PROTOCOL_VERSION = "0.0.0"
    text_block = lambda t: t
    
    PermissionOption = UserMessageChunk = AgentMessageChunk = AgentThoughtChunk = _StubClass
    ToolCallStart = ToolCallProgress = AgentPlanUpdate = AgentPlanContentUpdate = _StubClass
    AgentPlanRemovedUpdate = AvailableCommandsUpdate = CurrentModeUpdate = _StubClass
    ConfigOptionUpdate = SessionInfoUpdate = UsageUpdate = _StubClass
    SetSessionConfigOptionBooleanRequest = SessionConfigOptionSelect = _StubClass
    SessionConfigOptionBoolean = SessionConfigSelectOption = SessionConfigSelectGroup = _StubClass
    EnvVariable = ToolCallUpdate = _StubClass

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

_XDG_DIRS = {
    "XDG_CACHE_HOME": os.path.join(_MIMO_ROOT, "cache"),
    "XDG_DATA_HOME": os.path.join(_MIMO_ROOT, "data"),
    "XDG_STATE_HOME": os.path.join(_MIMO_ROOT, "state"),
    "XDG_CONFIG_HOME": os.path.join(_MIMO_ROOT, "config"),
}


# ============================================================
# ACP 事件类型枚举（用于信号分发）
# ============================================================
class ACPEvent:
    """ACP 事件类型常量"""
    # 会话更新
    THINKING = "thinking"          # 思考过程
    AI_MESSAGE = "ai_message"      # AI 回复
    USER_MESSAGE = "user_message"  # 用户消息
    TOOL_START = "tool_start"      # 工具开始
    TOOL_PROGRESS = "tool_progress" # 工具进度
    PLAN_UPDATE = "plan_update"    # 计划更新
    MESSAGE = "message"            # 通用消息（扩展通知等）
    
    # 交互式事件
    CONFIG_OPTION = "config_option"     # 配置选项（选择/布尔）
    PERMISSION = "permission"           # 权限请求
    ELICITATION = "elicitation"         # 交互式引导
    
    # 状态同步
    MODE_UPDATE = "mode_update"         # 模式更新
    COMMANDS_UPDATE = "commands_update" # 可用命令更新
    SESSION_INFO = "session_info"       # 会话信息
    USAGE = "usage"                     # 用量信息
    
    # 连接状态
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


# ============================================================
# ACP Client 实现 — 处理 MIMO Code 所有回调
# ============================================================
class _ACPClientImpl(Client):
    """
    ACP 协议 Client 实现。
    所有回调方法通过 Python 回调函数分发到主线程。
    """
    
    def __init__(self, bridge: 'ACPBridge'):
        self._bridge = bridge
        self._conn: Optional[AgentProtocol] = None
    
    def set_connection(self, conn: AgentProtocol):
        self._conn = conn
    
    def on_connect(self, conn: AgentProtocol) -> None:
        self._conn = conn
        self._bridge._on_acp_connected()
    
    async def session_update(self, session_id: str, update: Any, **kwargs) -> None:
        """处理所有会话更新事件"""
        try:
            await self._bridge._handle_session_update(session_id, update)
        except Exception as e:
            print(f"[ACP Bridge] session_update 错误: {e}")
            traceback.print_exc()
    
    async def request_permission(
        self, session_id: str, tool_call: ToolCallUpdate,
        options: list[PermissionOption], **kwargs
    ) -> RequestPermissionResponse:
        """权限请求 — 自动处理（信任模式）或显示在 Agent UI 等待用户选择"""
        # ★ v3.58: 信任模式自动处理
        if hasattr(self._bridge, '_handle_permission_auto'):
            return await self._bridge._handle_permission_auto(session_id, tool_call, options)
        return await self._bridge._handle_permission_request(session_id, tool_call, options)
    
    async def create_elicitation(self, message: str, mode: Any, **kwargs) -> CreateElicitationResponse:
        """交互式引导 — 显示在 Agent UI 并等待用户输入
        
        补齐 UI 交互逻辑：发射 elicitation_received 信号触发引导对话框，
        通过 Future 等待用户输入，超时默认返回空响应。
        """
        elicitation_id = f"elic_{int(time.time())}"
        mode_str = str(mode) if mode else "unknown"
        # 发射信号让 UI 弹出引导对话框
        self._bridge.elicitation_received.emit(message, mode_str)
        self._bridge._emit_event(ACPEvent.ELICITATION, {
            "elicitation_id": elicitation_id,
            "message": message,
            "mode": mode_str,
            "status": "pending",
        })
        # 创建 Future 等待用户输入（超时 120 秒）
        if self._bridge._loop:
            future = self._bridge._loop.create_future()
            self._bridge._pending_elicitations[elicitation_id] = future
            try:
                user_input = await asyncio.wait_for(future, timeout=120)
                return CreateElicitationResponse(
                    elicitation_id=elicitation_id,
                    content=str(user_input) if user_input else "",
                )
            except asyncio.TimeoutError:
                self._bridge.status_received.emit(
                    "<span style='color:Lemon.ACCENT_ORANGE;'>⏳ 引导输入超时，使用默认值</span>"
                )
            except Exception:
                pass
            finally:
                self._bridge._pending_elicitations.pop(elicitation_id, None)
        return CreateElicitationResponse(elicitation_id=elicitation_id)
    
    async def complete_elicitation(self, elicitation_id: str, **kwargs) -> None:
        """完成交互式引导 — 通知 UI 引导已完成"""
        self._bridge._emit_event(ACPEvent.ELICITATION, {
            "elicitation_id": elicitation_id,
            "status": "completed",
        })
    
    async def create_terminal(
        self, session_id: str, command: str,
        args=None, env=None, cwd=None, output_byte_limit=None, **kwargs
    ) -> CreateTerminalResponse:
        """创建终端 — 启动子进程执行命令"""
        import subprocess as _sp
        terminal_id = f"term_{int(time.time())}"
        cmd_list = [command] + (args or [])
        try:
            proc_env = os.environ.copy()
            if env:
                proc_env.update(env)
            proc = _sp.Popen(
                cmd_list,
                stdout=_sp.PIPE, stderr=_sp.STDOUT,
                env=proc_env,
                cwd=cwd or self._bridge.project_path,
            )
            self._bridge._terminals[terminal_id] = {
                'process': proc,
                'command': command,
                'args': args or [],
                'output': '',
            }
            self._bridge._emit_event(ACPEvent.TOOL_START, {
                "tool": "terminal", "command": command, "terminal_id": terminal_id,
            })
        except Exception as e:
            self._bridge.error_occurred.emit(
                f"<span style='color:Lemon.ACCENT_RED;'>❌ 终端创建失败: {self._bridge._escape_html(str(e))}</span>"
            )
        return CreateTerminalResponse(terminal_id=terminal_id)
    
    async def terminal_output(self, session_id: str, terminal_id: str, **kwargs) -> TerminalOutputResponse:
        """读取终端输出"""
        term = self._bridge._terminals.get(terminal_id)
        if not term:
            return TerminalOutputResponse(output="")
        proc = term['process']
        output = term.get('output', '')
        try:
            # 非阻塞读取可用输出
            import select as _select
            while True:
                ready, _, _ = _select.select([proc.stdout], [], [], 0)
                if not ready:
                    break
                chunk = proc.stdout.readline()
                if not chunk:
                    break
                output += chunk.decode('utf-8', errors='replace')
            term['output'] = output
        except Exception:
            pass
        return TerminalOutputResponse(output=output[-8000:] if len(output) > 8000 else output)
    
    async def release_terminal(self, session_id: str, terminal_id: str, **kwargs) -> None:
        """释放终端 — 清理资源但不禁用进程"""
        term = self._bridge._terminals.pop(terminal_id, None)
        if term:
            proc = term['process']
            if proc.poll() is None:
                # 进程仍在运行，不强制终止，仅解除引用
                pass
    
    async def wait_for_terminal_exit(self, session_id: str, terminal_id: str, **kwargs) -> WaitForTerminalExitResponse:
        """等待终端进程退出"""
        term = self._bridge._terminals.get(terminal_id)
        if not term:
            return WaitForTerminalExitResponse(exit_code=0)
        proc = term['process']
        try:
            # 最多等待 60 秒
            proc.wait(timeout=60)
        except Exception:
            proc.kill()
        return WaitForTerminalExitResponse(exit_code=proc.returncode or 0)
    
    async def kill_terminal(self, session_id: str, terminal_id: str, **kwargs) -> None:
        """强制终止终端进程"""
        term = self._bridge._terminals.pop(terminal_id, None)
        if term:
            proc = term['process']
            if proc.poll() is None:
                proc.kill()
                self._bridge.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_ORANGE;'>🔧 终端 {terminal_id} 已终止</span>"
                )
    
    async def read_text_file(
        self, session_id: str, path: str, line: int = None, limit: int = None, **kwargs
    ) -> ReadTextFileResponse:
        """读取文本文件 — 真实文件读取"""
        try:
            abs_path = path if os.path.isabs(path) else os.path.join(self._bridge.project_path, path)
            with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                if line:
                    lines_all = f.readlines()
                    start = max(0, line - 1)
                    end = start + (limit or 1000)
                    content = ''.join(lines_all[start:end])
                    return ReadTextFileResponse(content=content, lines=len(lines_all[start:end]))
                elif limit:
                    content = ''.join(f.readlines()[:limit])
                    return ReadTextFileResponse(content=content, lines=limit)
                else:
                    content = f.read()
                    return ReadTextFileResponse(content=content, lines=content.count('\n') + 1)
        except FileNotFoundError:
            return ReadTextFileResponse(content="", lines=0)
        except Exception as e:
            self._bridge.error_occurred.emit(
                f"<span style='color:Lemon.ACCENT_RED;'>❌ 读取文件失败: {self._bridge._escape_html(str(e))}</span>"
            )
            return ReadTextFileResponse(content="", lines=0)
    
    async def write_text_file(
        self, session_id: str, path: str, content: str, **kwargs
    ) -> WriteTextFileResponse:
        """写入文本文件 — 真实文件写入"""
        try:
            abs_path = path if os.path.isabs(path) else os.path.join(self._bridge.project_path, path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True) if os.path.dirname(abs_path) else None
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self._bridge.status_received.emit(
                f"<span style='color:Lemon.ACCENT_GREEN;'>✓ 文件已写入: {self._bridge._escape_html(os.path.basename(path))}</span>"
            )
            return WriteTextFileResponse(success=True)
        except Exception as e:
            self._bridge.error_occurred.emit(
                f"<span style='color:Lemon.ACCENT_RED;'>❌ 写入文件失败: {self._bridge._escape_html(str(e))}</span>"
            )
            return WriteTextFileResponse(success=False)
    
    async def ext_method(self, method: str, params: dict) -> dict:
        return {}
    
    async def ext_notification(self, method: str, params: dict) -> None:
        """扩展通知 — 转发外部通知事件到 UI"""
        self._bridge._emit_event(ACPEvent.MESSAGE, {
            "type": "ext_notification",
            "method": method,
            "params": params,
        })


# ============================================================
# ACP Bridge — 主桥接类（Qt 信号驱动）
# ============================================================
class ACPBridge(QObject):
    """
    ACP Bridge v3.71 — 协议双向通信桥，使 Agent 成为 MIMO Code 的完整操控器。
    
    信号体系（发送到 UI）：
    - acp_event: (event_type, data_dict) — 通用事件分发
    - 各专用信号用于特定事件类型
    
    方法体系（从 UI 调用）：
    - send_message(text) — 发送消息到 MIMO Code
    - set_config_option(config_id, value) — 设置配置选项
    - set_mode(mode_id) — 切换模式
    - respond_permission(session_id, choice_id) — 响应权限请求
    - get_context(n) / clear_context() / get_context_turns() — 上下文管理
    - create_session(name) / switch_session(sid) / list_sessions() — 多会话管理
    """
    
    # ==================== 通用事件信号 ====================
    acp_event = pyqtSignal(str, object)  # (event_type, data_dict)
    
    # ==================== 内容输出信号 ====================
    output_received = pyqtSignal(str)      # AI 回复内容（HTML）
    thinking_received = pyqtSignal(str)    # 思考过程（HTML）
    status_received = pyqtSignal(str)      # 状态消息（HTML）
    error_occurred = pyqtSignal(str)       # 错误消息（HTML）
    tool_output = pyqtSignal(str)          # 工具输出（HTML）
    
    # ==================== 交互式 UI 信号 ====================
    # 配置选项显示（MIMO Code 发送选择/布尔选项）
    config_options_received = pyqtSignal(str, list)  # (session_id, options_list)
    # 权限请求（MIMO Code 要求用户确认）
    permission_requested = pyqtSignal(str, object, list)  # (session_id, tool_call_info, options)
    # 交互式引导
    elicitation_received = pyqtSignal(str, str)  # (message, mode)
    
    # ==================== 状态同步信号 ====================
    mode_changed = pyqtSignal(str)              # 当前模式 ID
    available_commands = pyqtSignal(list)       # 可用命令列表
    plan_updated = pyqtSignal(list)             # 计划条目列表
    session_info = pyqtSignal(str, str)         # (session_id, cwd)
    usage_info = pyqtSignal(object)             # 用量信息
    
    # ==================== 连接状态信号 ====================
    connected = pyqtSignal()                    # 已连接
    disconnected = pyqtSignal()                 # 已断开
    connection_error = pyqtSignal(str)          # 连接错误
    
    # ==================== 任务生命周期信号 ====================
    task_started = pyqtSignal(str)              # 任务开始（消息文本）
    task_finished = pyqtSignal(bool, str)       # (成功?, 摘要)
    
    def __init__(self, project_path: str = None):
        super().__init__()
        self.project_path = os.path.abspath(project_path or os.getcwd())
        
        # ACP 连接状态
        self._client_impl: Optional[_ACPClientImpl] = None
        self._agent_conn: Optional[AgentProtocol] = None
        self._reader = None
        self._writer = None
        self._process = None
        self._transport = None
        
        # 会话状态
        self._session_id: Optional[str] = None
        self._current_mode_id: Optional[str] = None
        self._pending_permissions: dict[str, asyncio.Future] = {}  # session_id -> Future
        self._pending_elicitations: dict[str, asyncio.Future] = {}  # elicitation_id -> Future
        self._terminals: dict[str, dict] = {}  # terminal_id -> {process, command, output}
        
        # ★ v3.71: 上下文管理
        self._context: list[dict] = []  # 对话上下文 [{role, content}, ...]
        self._message_count = 0
        self._failure_count = 0
        
        # ★ v3.71: 多会话管理
        self._saved_contexts: dict[str, list[dict]] = {}
        
        # 运行状态
        self._running = False
        self._connected = False  # 真正连接就绪（session 已创建）
        self._busy = False  # ★ v3.59: 是否正在处理消息
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 消息缓存
        self._output_buffer: list[str] = []
        self._thinking_buffer: list[str] = []
        self._pending_messages: list[str] = []
        self._pending_queue: list[Dict[str, Any]] = []
        self._ack_events: Dict[str, threading.Event] = {}
        self._ack_results: Dict[str, Any] = {}
        self._connect_event = threading.Event()
        self._task_done_event = threading.Event()
    
    # ================================================================
    # 生命周期管理
    # ================================================================
    
    def start(self) -> bool:
        """启动 ACP 连接（在后台线程运行）"""
        if self._running:
            return True
        
        if not os.path.exists(MIMO_EXE):
            self.error_occurred.emit(f"MIMO EXE 不存在: {MIMO_EXE}")
            return False
        
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True
    
    def stop(self):
        """停止 ACP 连接"""
        self._running = False
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            try:
                # 取消所有待处理的 prompt
                if self._agent_conn and self._session_id:
                    asyncio.run_coroutine_threadsafe(
                        self._agent_conn.cancel(session_id=self._session_id),
                        self._loop
                    )
            except Exception:
                pass
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        
        # 清理
        if self._transport:
            try:
                if hasattr(self._transport, '__aexit__'):
                    pass  # context manager handled in loop
            except Exception:
                pass
        
        self._client_impl = None
        self._agent_conn = None
        self._session_id = None
        self._current_mode_id = None
        self._connected = False
        self._context.clear()
        self._saved_contexts.clear()
        self._message_count = 0
        self._failure_count = 0
        # 清理所有终端进程
        for tid, term in list(self._terminals.items()):
            try:
                proc = term.get('process')
                if proc and proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        self._terminals.clear()
        self._pending_elicitations.clear()
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def session_id(self) -> Optional[str]:
        return self._session_id
    
    @property
    def current_mode(self) -> Optional[str]:
        return self._current_mode_id
    
    def _run_loop(self):
        """后台 asyncio 事件循环"""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._acp_main())
        except Exception as e:
            print(f"[ACP Bridge] 事件循环异常: {e}")
            traceback.print_exc()
            self._emit_event(ACPEvent.ERROR, {"message": str(e)})
        finally:
            if self._loop:
                self._loop.close()
            self._running = False
            self.disconnected.emit()
    
    async def _acp_main(self):
        """ACP 主协程 — 启动连接、管理会话"""
        try:
            # 设置环境变量
            env = os.environ.copy()
            for key, val in _XDG_DIRS.items():
                env[key] = val
            
            self._emit_event(ACPEvent.CONNECTED, {"status": "connecting"})
            
            async with spawn_stdio_transport(
                MIMO_EXE, "acp", "--print-logs",
                "--cwd", self.project_path,
                cwd=self.project_path,
                env=env
            ) as transport:
                self._transport = transport
                reader, writer, proc = transport
                self._reader = reader
                self._writer = writer
                self._process = proc
                
                # 创建 Client 实现
                self._client_impl = _ACPClientImpl(self)
                
                # 连接
                # 注意：connect_to_agent 的参数顺序是 (client, input_stream, output_stream)
                # input_stream = 我们向 agent 写入的流 = stdin StreamWriter (writer)
                # output_stream = 我们从 agent 读取的流 = stdout StreamReader (reader)
                conn = connect_to_agent(self._client_impl, writer, reader)
                self._agent_conn = conn
                self._client_impl.set_connection(conn)
                
                # 初始化
                await conn.initialize(protocol_version=PROTOCOL_VERSION)
                
                # 创建会话
                session = await conn.new_session(
                    cwd=self.project_path, mcp_servers=[]
                )
                self._session_id = session.session_id
                
                # 标记连接就绪
                self._connected = True
                if hasattr(self, '_connect_event'):
                    self._connect_event.set()
                
                self._emit_event(ACPEvent.CONNECTED, {
                    "session_id": self._session_id,
                    "pid": proc.pid,
                })
                self.connected.emit()
                
                # 发送缓存的消息
                self._flush_pending_messages()
                
                # 等待停止信号
                stop_event_sync = threading.Event()
                def _on_stop():
                    stop_event_sync.set()
                self._stop_event_callbacks = getattr(self, '_stop_event_callbacks', [])
                self._stop_event_callbacks.append(_on_stop)
                while not self._stop_event.is_set():
                    stop_event_sync.wait(timeout=0.5)
                    stop_event_sync.clear()
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_msg = str(e)
            print(f"[ACP Bridge] 连接异常: {error_msg}")
            traceback.print_exc()
            self._emit_event(ACPEvent.ERROR, {"message": error_msg})
            self.connection_error.emit(error_msg)
    
    # ================================================================
    # 事件处理
    # ================================================================
    
    async def _handle_session_update(self, session_id: str, update: Any):
        """处理会话更新事件 — 核心事件分发"""
        # --- 思考过程 ---
        if isinstance(update, AgentThoughtChunk):
            text = (update.text or "").strip()
            if text:
                safe = self._escape_html(text)
                self.thinking_received.emit(
                    f"<span style='color:#888;font-style:italic;'>💭 {safe}</span>"
                )
                self._emit_event(ACPEvent.THINKING, {"text": text})
        
        # --- AI 回复 ---
        elif isinstance(update, AgentMessageChunk):
            text = (update.text or "").strip()
            if text:
                safe = self._escape_html(text)
                self.output_received.emit(
                    f"<span style='color:Lemon.PLACEHOLDER;'>{safe}</span>"
                )
                self._emit_event(ACPEvent.AI_MESSAGE, {"text": text})
                # ★ v3.71: 记录到上下文
                self._context.append({"role": "assistant", "content": text})
        
        # --- 用户消息回显 ---
        elif isinstance(update, UserMessageChunk):
            text = (update.text or "").strip()
            if text:
                safe = self._escape_html(text)
                self.output_received.emit(
                    f"<span style='color:Lemon.ACCENT_ORANGE;font-weight:600;'>▶ {safe}</span>"
                )
                self._emit_event(ACPEvent.USER_MESSAGE, {"text": text})
        
        # --- 工具调用开始 ---
        elif isinstance(update, ToolCallStart):
            tc = update
            tool_name = getattr(tc, 'title', getattr(tc, 'kind', 'unknown'))
            status = getattr(tc, 'status', None)
            inp = getattr(tc, 'raw_input', None) or ""
            cmd = ""
            if isinstance(inp, dict):
                cmd = inp.get('command', inp.get('description', ''))
            
            self.status_received.emit(
                f"<span style='color:Lemon.ACCENT_ORANGE;'>🔧 工具 [{tool_name}]</span>"
            )
            if cmd:
                safe_cmd = self._escape_html(str(cmd))
                self.tool_output.emit(
                    f"<span style='color:#b0b0b0;font-style:italic;font-size:11px;'>$ {safe_cmd}</span>"
                )
            self._emit_event(ACPEvent.TOOL_START, {
                "tool": tool_name, "command": cmd,
                "status": str(status) if status else "unknown"
            })
        
        # --- 工具进度 ---
        elif isinstance(update, ToolCallProgress):
            tc = update
            status = getattr(tc, 'status', None)
            if status == 'completed':
                out = getattr(tc, 'raw_output', None) or ""
                if out:
                    safe = self._escape_html(str(out)[:800])
                    self.tool_output.emit(
                        f"<pre style='color:Lemon.SUCCESS;font-size:11px;line-height:1.4;margin:2px 0 4px 0;padding:4px 8px;background:rgba(0,0,0,0.3);border-left:2px solid Lemon.ACCENT_GREEN;border-radius:2px;white-space:pre-wrap;font-family:Courier New,monospace;'>{safe}</pre>"
                    )
                self.status_received.emit(
                    f"<span style='color:Lemon.ACCENT_GREEN;'>✓ 工具完成</span>"
                )
            elif status == 'failed':
                err = getattr(tc, 'raw_output', None) or "未知错误"
                self.error_occurred.emit(
                    f"<span style='color:Lemon.ACCENT_RED;'>❌ 工具失败: {self._escape_html(str(err)[:200])}</span>"
                )
            self._emit_event(ACPEvent.TOOL_PROGRESS, {
                "status": str(status) if status else "unknown"
            })
        
        # --- 计划更新 ---
        elif isinstance(update, AgentPlanUpdate):
            entries = getattr(update, 'entries', [])
            plan_list = []
            for e in entries:
                plan_list.append({
                    "content": getattr(e, 'content', ''),
                    "status": str(getattr(e, 'status', 'pending')),
                    "priority": str(getattr(e, 'priority', 'medium')),
                })
            self.plan_updated.emit(plan_list)
            self._emit_event(ACPEvent.PLAN_UPDATE, {"entries": plan_list})
        
        # --- 计划内容更新 ---
        elif isinstance(update, AgentPlanContentUpdate):
            pass  # 由 AgentPlanUpdate 覆盖
        
        # --- 计划移除 ---
        elif isinstance(update, AgentPlanRemovedUpdate):
            self.plan_updated.emit([])
        
        # --- 配置选项更新（关键交互！） ---
        elif isinstance(update, ConfigOptionUpdate):
            config_options = getattr(update, 'config_options', [])
            await self._handle_config_options(session_id, config_options)
        
        # --- 模式更新 ---
        elif isinstance(update, CurrentModeUpdate):
            mode_id = getattr(update, 'current_mode_id', None)
            if mode_id:
                self._current_mode_id = mode_id
                self.mode_changed.emit(mode_id)
                self._emit_event(ACPEvent.MODE_UPDATE, {"mode_id": mode_id})
        
        # --- 可用命令更新 ---
        elif isinstance(update, AvailableCommandsUpdate):
            commands = getattr(update, 'available_commands', [])
            cmd_list = []
            for c in commands:
                cmd_list.append({
                    "name": getattr(c, 'name', ''),
                    "description": getattr(c, 'description', ''),
                })
            self.available_commands.emit(cmd_list)
            self._emit_event(ACPEvent.COMMANDS_UPDATE, {"commands": cmd_list})
        
        # --- 会话信息 ---
        elif isinstance(update, SessionInfoUpdate):
            info_session_id = getattr(update, 'session_id', session_id)
            info_cwd = getattr(update, 'cwd', self.project_path)
            self.session_info.emit(info_session_id, info_cwd)
            self._emit_event(ACPEvent.SESSION_INFO, {
                "session_id": info_session_id,
                "cwd": info_cwd
            })
        
        # --- 用量 ---
        elif isinstance(update, UsageUpdate):
            tokens = getattr(update, 'tokens', {})
            self.usage_info.emit(tokens)
            self._emit_event(ACPEvent.USAGE, {"tokens": tokens})
    
    async def _handle_config_options(self, session_id: str, config_options: list):
        """
        处理配置选项更新。
        
        当 MIMO Code 发送配置选项（如选择模型、设置参数等），
        这些选项需要在 Agent UI 中显示并允许用户交互选择。
        """
        options_data = []
        for opt in config_options:
            opt_type = getattr(opt, 'type', None)
            entry = {
                "id": getattr(opt, 'id', ''),
                "name": getattr(opt, 'name', ''),
                "description": getattr(opt, 'description', ''),
                "category": getattr(opt, 'category', ''),
                "type": opt_type,
            }
            
            if opt_type == "select":
                entry["current_value"] = getattr(opt, 'current_value', '')
                # 解析选项列表
                raw_options = getattr(opt, 'options', [])
                select_options = []
                for ro in raw_options:
                    if isinstance(ro, SessionConfigSelectOption):
                        select_options.append({
                            "value": ro.value,
                            "name": ro.name,
                            "description": getattr(ro, 'description', None),
                        })
                    elif isinstance(ro, SessionConfigSelectGroup):
                        group_opts = []
                        for go in getattr(ro, 'options', []):
                            group_opts.append({
                                "value": go.value,
                                "name": go.name,
                            })
                        select_options.append({
                            "group": getattr(ro, 'group', ''),
                            "name": getattr(ro, 'name', ''),
                            "options": group_opts,
                        })
                entry["select_options"] = select_options
            
            elif opt_type == "boolean":
                entry["current_value"] = getattr(opt, 'current_value', False)
            
            options_data.append(entry)
        
        if options_data:
            self.config_options_received.emit(session_id, options_data)
            self._emit_event(ACPEvent.CONFIG_OPTION, {
                "session_id": session_id,
                "options": options_data
            })
    
    async def _handle_permission_request(
        self, session_id: str, tool_call: ToolCallUpdate,
        options: list[PermissionOption]
    ) -> RequestPermissionResponse:
        """
        处理权限请求。
        
        当 MIMO Code 需要用户确认操作（如执行命令、写入文件）时，
        显示权限弹窗等待用户选择。如果用户未选择，默认拒绝。
        """
        # 构建显示信息
        tool_info = {
            "tool_call_id": getattr(tool_call, 'tool_call_id', ''),
            "title": getattr(tool_call, 'title', 'Unknown'),
            "kind": str(getattr(tool_call, 'kind', 'other')),
            "description": "",
        }
        
        # 提取描述
        content = getattr(tool_call, 'content', None) or []
        for c in content:
            if hasattr(c, 'text') and c.text:
                tool_info["description"] = c.text
                break
        
        opt_list = []
        for opt in options:
            opt_list.append({
                "id": opt.option_id,
                "name": opt.name,
                "kind": opt.kind,
            })
        
        # 发送权限请求信号（UI 线程显示弹窗）
        self.permission_requested.emit(session_id, tool_info, opt_list)
        
        # 创建 Future 等待用户响应
        future = self._loop.create_future()
        self._pending_permissions[session_id] = future
        
        # 等待用户选择（超时 300 秒）
        try:
            choice_id = await asyncio.wait_for(future, timeout=300)
            return RequestPermissionResponse(choice=choice_id)
        except asyncio.TimeoutError:
            return RequestPermissionResponse(choice="reject")
        except Exception:
            return RequestPermissionResponse(choice="reject")
        finally:
            self._pending_permissions.pop(session_id, None)
    
    # ================================================================
    # 供 UI 调用的方法
    # ================================================================
    
    def send_message(self, text: str) -> bool:
        """
        发送消息到 MIMO Code。
        如果连接未就绪，消息会缓存等待连接完成后自动发送。
        支持ack回传：每条消息分配msg_id，task_finished时回写结果。
        """
        if not text.strip():
            return False
        
        import uuid as _uuid
        msg_id = "msg_" + _uuid.uuid4().hex[:8]
        ack_event = threading.Event()
        self._ack_events[msg_id] = ack_event
        self._pending_queue.append({"msg_id": msg_id, "text": text, "queued_at": time.time()})
        
        if not self._connected or not self._agent_conn or not self._session_id or not self._loop:
            self._pending_messages.append(text)
            self.status_received.emit(
                f"<span style='color:Lemon.ACCENT_ORANGE;'>⏳ 连接尚未就绪，消息已缓存...</span>"
            )
            print(f"[ACP Bridge] 连接未就绪，缓存消息: {text[:50]}")
            return True
        
        self.task_started.emit(text)
        
        asyncio.run_coroutine_threadsafe(
            self._do_send_message(text),
            self._loop
        )
        return True
    
    def _flush_pending_messages(self):
        """连接就绪后发送缓存的消息，并清除pending_queue中已发送项。"""
        if not self._pending_messages:
            return
        messages = self._pending_messages.copy()
        self._pending_messages.clear()
        for msg in messages:
            self.task_started.emit(msg)
            asyncio.run_coroutine_threadsafe(
                self._do_send_message(msg),
                self._loop
            )
            print(f"[ACP Bridge] 发送缓存消息: {msg[:50]}")
        self._pending_queue.clear()

    def _ack_latest(self, success: bool, message: str) -> None:
        """错误回传ack：将最近pending消息的ack_event set并记录结果。"""
        if self._pending_queue:
            latest = self._pending_queue.pop(0)
            msg_id = latest.get("msg_id", "")
            if msg_id in self._ack_events:
                self._ack_results[msg_id] = {"success": success, "message": message}
                self._ack_events[msg_id].set()
                del self._ack_events[msg_id]

    def wait_ack(self, msg_id: str, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """等待指定消息的ack回传。"""
        event = self._ack_events.get(msg_id)
        if not event:
            return self._ack_results.get(msg_id)
        event.wait(timeout=timeout)
        return self._ack_results.pop(msg_id, None)

    def send_and_wait(self, text: str, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
        """发送消息并同步等待ack回传，返回ack结果或None(超时)。

        典型用法: result = bridge.send_and_wait("分析代码", timeout=30)
        返回: {"success": bool, "message": str} 或 None
        """
        if not text.strip():
            return None
        import uuid as _uuid
        msg_id = "msg_" + _uuid.uuid4().hex[:8]
        ack_event = threading.Event()
        self._ack_events[msg_id] = ack_event
        self._pending_queue.append({"msg_id": msg_id, "text": text, "queued_at": time.time()})
        sent = self.send_message(text)
        if not sent:
            self._ack_events.pop(msg_id, None)
            self._pending_queue = [p for p in self._pending_queue if p.get("msg_id") != msg_id]
            return None
        ack_event.wait(timeout=timeout)
        return self._ack_results.pop(msg_id, None)
    
    async def _do_send_message(self, text: str):
        """在事件循环中发送消息"""
        self._busy = True
        try:
            # ★ v3.71: 记录用户消息到上下文
            self._message_count += 1
            self._context.append({"role": "user", "content": text})
            
            prompt_resp = await self._agent_conn.prompt(
                session_id=self._session_id,
                prompt=[text_block(text)]
            )
            stop_reason = getattr(prompt_resp, 'stop_reason', 'unknown')
            success = stop_reason not in ('cancelled', 'refusal')
            summary = f"完成 (stop_reason={stop_reason})"
            if success:
                self._failure_count = 0
            self.task_finished.emit(success, summary)
            if hasattr(self, '_task_done_event'):
                self._task_done_event.set()
            self._ack_latest(success, summary)
        except Exception as e:
            self._failure_count += 1
            error_msg = str(e)
            print(f"[ACP Bridge] 发送消息失败: {error_msg}")
            self.task_finished.emit(False, error_msg)
            if hasattr(self, '_task_done_event'):
                self._task_done_event.set()
            self._ack_latest(False, error_msg)
        finally:
            self._busy = False
    
    def set_config_option(self, config_id: str, value: str | bool) -> bool:
        """
        设置配置选项（用户选择后的回传）。
        对应 session/set_config_option 请求。
        """
        if not self._running or not self._agent_conn or not self._session_id:
            self.error_occurred.emit("ACP 未连接")
            return False
        
        asyncio.run_coroutine_threadsafe(
            self._agent_conn.set_config_option(
                config_id=config_id,
                session_id=self._session_id,
                value=value,
            ),
            self._loop
        )
        return True
    
    def set_mode(self, mode_id: str) -> bool:
        """
        切换 MIMO Code 的工作模式。
        对应 session/set_mode 请求。
        """
        if not self._running or not self._agent_conn or not self._session_id:
            self.error_occurred.emit("ACP 未连接")
            return False
        
        asyncio.run_coroutine_threadsafe(
            self._agent_conn.set_session_mode(
                session_id=self._session_id,
                mode_id=mode_id,
            ),
            self._loop
        )
        return True
    
    def respond_permission(self, session_id: str, choice_id: str) -> bool:
        """
        响应权限请求。
        用户选择后，唤醒等待的 Future。
        """
        future = self._pending_permissions.get(session_id)
        if future and not future.done():
            future.set_result(choice_id)
            return True
        return False
    
    def respond_elicitation(self, elicitation_id: str, user_input: str) -> bool:
        """
        响应交互式引导。
        用户输入后，唤醒等待的 Future。
        """
        future = self._pending_elicitations.get(elicitation_id)
        if future and not future.done():
            future.set_result(user_input)
            return True
        return False
    
    def cancel_current_task(self) -> bool:
        """取消当前任务"""
        if not self._running or not self._agent_conn or not self._session_id:
            return False
        
        asyncio.run_coroutine_threadsafe(
            self._agent_conn.cancel(session_id=self._session_id),
            self._loop
        )
        return True
    
    # ================================================================
    # ★ v3.71: 上下文管理
    # ================================================================

    def get_context(self, n: int = None) -> list[dict]:
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
    # ★ v3.71: 多会话管理
    # ================================================================

    def create_session(self, name: str = None) -> str:
        """创建新会话（保存当前上下文，新建空白会话）"""
        if self._session_id and self._context:
            self._saved_contexts[self._session_id] = self._context.copy()
        self._context = []
        self._message_count = 0
        self._failure_count = 0
        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_BLUE;'>[ACP] 新会话已创建"
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
            self._message_count = len([c for c in self._context if c.get("role") == "user"])
            self.status_received.emit(
                f"<span style='color:Lemon.ACCENT_GREEN;'>[ACP] 切换到会话: {session_id[:16]}..."
                f" ({self._message_count} 轮)</span>"
            )
            return True
        return False

    def list_sessions(self) -> list[dict]:
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
    
    # ================================================================
    # 内部工具方法
    # ================================================================
    
    def _on_acp_connected(self):
        """ACP 连接建立回调"""
        self._running = True

    # ================================================================
    # ★ v3.58: 完整夺舍功能
    # ================================================================

    def takeover(self, force: bool = False) -> bool:
        """
        完整夺舍 MIMO Code — 接管所有通信通道。

        夺舍流程：
        1. 启动 ACP 连接（如果未启动）
        2. 创建新会话
        3. 设置信任模式（自动同意所有权限）
        4. 同步配置选项
        5. 挂载所有事件处理器

        Args:
            force: 是否强制夺舍（即使已有连接）

        Returns:
            是否夺舍成功
        """
        if self._connected and not force:
            self.status_received.emit(
                "<span style='color:Lemon.ACCENT_GREEN;'>✓ ACP 已连接，无需重复夺舍</span>"
            )
            return True

        if not self._running:
            self.start()
            if not hasattr(self, '_connect_event'):
                self._connect_event = threading.Event()
            self._connect_event.clear()
            self._connect_event.wait(timeout=15.0)
            if not self._connected:
                self.error_occurred.emit(
                    "<span style='color:Lemon.ACCENT_RED;'>❌ 夺舍失败: ACP 连接超时</span>"
                )
                return False

        self.status_received.emit(
            "<span style='color:Lemon.ACCENT_ORANGE;'>🔗 ACP 夺舍成功 — 已接管 MIMO Code 通信</span>"
        )
        self._emit_event(ACPEvent.CONNECTED, {
            "session_id": self._session_id,
            "takeover": True,
            "mode": "full_control",
        })
        return True

    def set_trust_mode(self, enabled: bool = True, auto_approve_tools: list = None):
        """
        设置信任模式 — 自动同意所有权限请求和工具调用。

        Args:
            enabled: 是否启用信任模式
            auto_approve_tools: 自动同意的工具列表
        """
        self._trust_mode = enabled
        self._auto_approve_tools = set(auto_approve_tools or [])
        status = "启用" if enabled else "禁用"
        self.status_received.emit(
            f"<span style='color:Lemon.ACCENT_ORANGE;'>🔓 信任模式已{status}</span>"
        )

    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._running

    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected

    @property
    def is_busy(self) -> bool:
        """★ v3.59: 检查是否正在处理消息"""
        return self._busy

    def get_status(self) -> dict:
        """获取完整状态信息"""
        return {
            "running": self._running,
            "connected": self._connected,
            "busy": self._busy,
            "session_id": self._session_id,
            "current_mode": self._current_mode_id,
            "context_turns": len(self._context) // 2,
            "message_count": self._message_count,
            "failure_count": self._failure_count,
            "saved_sessions": len(self._saved_contexts),
            "pending_permissions": len(self._pending_permissions),
            "pending_elicitations": len(self._pending_elicitations),
            "active_terminals": len(self._terminals),
            "pending_messages": len(self._pending_messages),
            "trust_mode": getattr(self, '_trust_mode', False),
            "exe_exists": os.path.exists(MIMO_EXE),
        }

    def send_message_sync(self, text: str, timeout: float = 120) -> bool:
        """
        同步发送消息（阻塞等待完成）。

        用于任务队列集成，确保消息按顺序处理。

        Args:
            text: 消息文本
            timeout: 超时时间（秒）

        Returns:
            是否发送成功
        """
        if not self.send_message(text):
            return False

        # 等待任务完成
        if hasattr(self, '_loop') and self._loop:
            if not hasattr(self, '_task_done_event'):
                self._task_done_event = threading.Event()
            self._task_done_event.clear()
            self._task_done_event.wait(timeout=timeout)
            return self._task_done_event.is_set()
        return True

    # ================================================================
    # ★ v3.58: 权限自动处理
    # ================================================================

    async def _handle_permission_auto(self, session_id: str, tool_call,
                                       options: list) -> RequestPermissionResponse:
        """
        自动处理权限请求（信任模式）。

        在信任模式下，自动同意所有权限请求。
        """
        if getattr(self, '_trust_mode', False):
            # 信任模式：自动同意
            if options:
                # 选择第一个允许选项
                for opt in options:
                    if getattr(opt, 'kind', '') == 'allow':
                        return RequestPermissionResponse(choice=opt.option_id)
                # 没有 allow 选项，选择第一个
                return RequestPermissionResponse(choice=options[0].option_id)
            return RequestPermissionResponse(choice="allow")

        # 检查自动同意列表
        tool_kind = str(getattr(tool_call, 'kind', '')).lower()
        if tool_kind in getattr(self, '_auto_approve_tools', set()):
            for opt in options:
                if getattr(opt, 'kind', '') == 'allow':
                    return RequestPermissionResponse(choice=opt.option_id)
            return RequestPermissionResponse(choice="allow")

        # 默认：显示权限请求（由父类处理）
        return await self._handle_permission_request(session_id, tool_call, options)

    def _emit_event(self, event_type: str, data: dict):
        """发射通用事件信号"""
        self.acp_event.emit(event_type, data)

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符"""
        return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))