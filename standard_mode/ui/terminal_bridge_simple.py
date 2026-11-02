# -*- coding: utf-8 -*-
"""
[DEPRECATED — 第391章 A 战区]
简化终端桥接 — QWebChannel 直接暴露 (fallback only, 不再被 SimpleTerminalPanel 使用)
================================================================
架构：xterm.js → QWebChannel → TerminalBridge → ShellBridge → PTY

本地终端已迁 ConPTY + WebSocket 后端 (terminal_server.py / terminal_xterm.html)。
本文件仅作历史参考与 QWebChannel fallback；QWebChannel 链路存在 init-response
协议差异导致 bridge 永不就绪（第391章根因），勿恢复为主力。
"""
import os
import threading
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtWebChannel import QWebChannel

try:
    from shared.shell_bridge import ShellBridge
except ImportError:
    from standard_mode.shared.shell_bridge import ShellBridge


def _append_history(tail: str, chunk: str, max_bytes: int = 102400) -> str:
    """[358章] 拼接输出历史并裁剪到末尾 max_bytes 字节，防止内存膨胀。
    按 UTF-8 字节近似裁剪：从尾部保留，超限从头部丢弃整行。"""
    merged = tail + chunk
    if len(merged.encode('utf-8', 'ignore')) <= max_bytes:
        return merged
    lines = merged.split('\n')
    while lines and len('\n'.join(lines).encode('utf-8', 'ignore')) > max_bytes:
        lines.pop(0)
    if not lines:
        truncated = merged
        while len(truncated.encode('utf-8', 'ignore')) > max_bytes and truncated:
            truncated = truncated[len(truncated) // 4:]
        return truncated
    return '\n'.join(lines)


class TerminalBridge(QObject):
    """
    终端桥接对象，直接暴露给 xterm.js
    
    终端状态机(v3.0):
        IDLE → STARTING → RUNNING → STOPPING → IDLE
        restart()幂等: 仅IDLE/STOPPING可启动, RUNNING先stop再start
    异步启动:
        start()在后台线程中调用ShellBridge.start(), 不阻塞UI
    输出缓冲:
        高频输出合并(8帧/32KB/5ms), 低频直发
    """
    
    output_received = pyqtSignal(str)
    process_started = pyqtSignal()
    process_exited = pyqtSignal(int)
    error_occurred = pyqtSignal(str)
    navigate_requested = pyqtSignal(str, int)
    
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    
    def __init__(self, cwd: Optional[str] = None, parent=None):
        super().__init__(parent)
        
        self._cwd = os.path.abspath(cwd or os.getcwd())
        self._bridge: Optional[ShellBridge] = None
        self._started = False
        self._state = self.IDLE
        self._default_cols = 120
        self._default_rows = 30
        self._high_freq_buf = []
        self._high_freq_timer = QTimer(self)
        self._high_freq_timer.setSingleShot(True)
        self._high_freq_timer.timeout.connect(self._flush_high_freq)
        self._start_lock = threading.Lock()
        self._history_tail = ""
    
    # ============================================================
    # JS 可调用的槽函数
    # ============================================================
    @pyqtSlot()
    def start(self):
        """启动 PTY 进程(异步, 不阻塞UI)。"""
        if self._state != self.IDLE:
            return
        self._state = self.STARTING
        t = threading.Thread(target=self._do_start_async, args=(self._default_cols, self._default_rows), daemon=True)
        t.start()

    @pyqtSlot(int, int)
    def start_sized(self, cols: int, rows: int):
        """带尺寸启动 PTY 进程(异步)。"""
        if self._state != self.IDLE:
            return
        self._state = self.STARTING
        t = threading.Thread(target=self._do_start_async, args=(max(40, cols), max(10, rows)), daemon=True)
        t.start()

    def _do_start_async(self, cols: int, rows: int):
        """后台线程执行启动。"""
        with self._start_lock:
            try:
                self._bridge = ShellBridge(cwd=self._cwd, cols=cols, rows=rows)
                self._bridge.raw_output.connect(self._on_output)
                self._bridge.error_occurred.connect(self.error_occurred.emit)
                self._bridge.process_started.connect(self._on_started)
                self._bridge.process_stopped.connect(self._on_stopped)
                ok = self._bridge.start()
                if ok:
                    self._started = True
                else:
                    self._state = self.IDLE
                    self.error_occurred.emit("PTY启动失败(ConPTY和subprocess均不可用)")
            except ImportError as e:
                self._state = self.IDLE
                self.error_occurred.emit("依赖缺失: " + str(e))
            except Exception as e:
                self._state = self.IDLE
                self.error_occurred.emit("启动异常: " + str(e))

    def _do_start(self, cols: int, rows: int):
        """同步启动(兼容旧调用)。"""
        self._do_start_async(cols, rows)
    
    @pyqtSlot(str)
    def send_input(self, data: str):
        """发送输入到 PTY"""
        if self._bridge and self._started:
            self._bridge.send(data)
    
    @pyqtSlot(int, int)
    def resize(self, cols: int, rows: int):
        """调整终端大小"""
        if self._bridge and self._started:
            self._bridge.resize(cols, rows)
    
    @pyqtSlot()
    def interrupt(self):
        """发送 Ctrl+C"""
        if self._bridge and self._started:
            self._bridge.ctrl_c()

    @pyqtSlot(str, result="QVariant")
    def complete_path(self, partial: str):
        """路径补全：给定 partial 路径前缀，返回候选项列表"""
        import json
        results = []
        try:
            base = partial.rstrip("/\\")
            head, tail = os.path.split(base)
            search_dir = os.path.join(self._cwd, head) if head else self._cwd
            if not os.path.isdir(search_dir):
                return {"candidates": results}
            lower_tail = tail.lower()
            for entry in os.listdir(search_dir):
                if tail and not entry.lower().startswith(lower_tail):
                    continue
                full = os.path.join(search_dir, entry)
                is_dir = os.path.isdir(full)
                results.append({
                    "text": entry,
                    "is_dir": is_dir,
                    "completion": entry + ("/" if is_dir else ""),
                })
            if len(results) > 50:
                results = results[:50]
        except Exception:
            pass
        return {"candidates": results}

    @pyqtSlot(str, int)
    def navigate_to_file(self, file_path: str, line: int):
        """JS端堆栈行号点击时发射跳转信号"""
        self.navigate_requested.emit(file_path, line)

    @pyqtSlot()
    def stop(self):
        """停止 PTY(幂等, 状态机保护)。"""
        if self._state == self.STOPPING or self._state == self.IDLE:
            return
        self._state = self.STOPPING
        if self._bridge:
            self._bridge.stop()
            self._bridge = None
        self._started = False
        self._history_tail = ""

    @pyqtSlot()
    def restart(self):
        """停止并重新启动 PTY(幂等)。"""
        self.stop()
        self._state = self.IDLE
        self.start()

    @pyqtSlot(result="QVariant")
    def get_history(self):
        """[358章] JS 连接后回放启动期丢失的输出（尾部≤100KB）。"""
        return self._history_tail

    @pyqtSlot(result="QVariant")
    def get_run_status(self):
        """v6.0-S: 返回当前Run状态(JSON供JS调用)。"""
        import json
        status = {
            "busy": getattr(self, '_run_busy', False),
            "run_id": getattr(self, '_run_id', ''),
            "cwd": self._cwd,
            "started": self._started,
            "state": self._state,
        }
        return json.dumps(status)

    @pyqtSlot(str)
    def inject_to_agent(self, text: str):
        """v6.0-S: 将终端选中文本注入Agent。"""
        try:
            parent = self.parent()
            while parent:
                if hasattr(parent, '_on_inject_to_agent'):
                    parent._on_inject_to_agent(text)
                    return
                if hasattr(parent, 'mimo_panel') and hasattr(parent.mimo_panel, 'send_message'):
                    parent.mimo_panel.send_message(text)
                    return
                parent = parent.parent()
        except Exception:
            pass
    
    # ============================================================
    # 内部回调
    # ============================================================
    def _on_output(self, data: str):
        self._high_freq_buf.append(data)
        if not self._high_freq_timer.isActive():
            self._high_freq_timer.start(100)

    def _flush_high_freq(self):
        if not self._high_freq_buf:
            return
        merged = "".join(self._high_freq_buf)
        self._high_freq_buf.clear()
        self.output_received.emit(merged)
        self._history_tail = _append_history(self._history_tail, merged)
    
    def _on_started(self):
        """PTY 启动回调"""
        self._state = self.RUNNING
        self.process_started.emit()
    
    def _on_stopped(self, code: int):
        self._flush_high_freq()
        self._state = self.IDLE
        self.process_exited.emit(code)
        self._started = False
    
    # ============================================================
    # 属性
    # ============================================================
    @property
    def cwd(self) -> str:
        return self._cwd
    
    @property
    def is_running(self) -> bool:
        return self._started and self._bridge is not None


class TerminalChannel:
    """
    QWebChannel 管理器
    
    使用方式：
        channel_manager = TerminalChannel()
        bridge = channel_manager.create_bridge(cwd="D:/project")
        webview.page().setWebChannel(channel_manager.channel)
    """
    
    def __init__(self):
        self._channel = QWebChannel()
        self._bridges = {}  # term_id -> bridge
    
    @property
    def channel(self) -> QWebChannel:
        return self._channel
    
    def create_bridge(self, term_id: str = "terminal", cwd: Optional[str] = None) -> TerminalBridge:
        """创建并注册 bridge"""
        bridge = TerminalBridge(cwd=cwd)
        self._channel.registerObject(term_id, bridge)
        self._bridges[term_id] = bridge
        return bridge
    
    def get_bridge(self, term_id: str = "terminal") -> Optional[TerminalBridge]:
        """获取 bridge"""
        return self._bridges.get(term_id)
    
    def remove_bridge(self, term_id: str):
        """移除并停止 bridge"""
        bridge = self._bridges.get(term_id)
        if bridge:
            bridge.stop()
            # QWebChannel 没有 unregister 方法，只能置空
            self._bridges[term_id] = None
            del self._bridges[term_id]
