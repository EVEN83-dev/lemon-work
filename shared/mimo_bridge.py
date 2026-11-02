# -*- coding: utf-8 -*-
"""
MIMO Bridge v3 — HTTP API 连接桥
- 启动 mimo acp 作为持久 HTTP 服务器
- 通过 REST API 创建会话、发送消息
- 通过 SSE 实时接收响应事件
- 信号收发器：Agent ↔ MIMO Code
"""

import os, sys, re, json, time, uuid, threading, subprocess
import urllib.request
import urllib.error
from PyQt5.QtCore import QObject, pyqtSignal

# ============================================================
# 路径配置
# ============================================================
_XIAOMI_AI = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "小米AI")
_MIMO_NODE_GLOBAL = os.path.join(_XIAOMI_AI, "node_global")
MIMO_EXE = os.path.join(_MIMO_NODE_GLOBAL, "node_modules", "@mimo-ai", "mimocode-windows-x64", "bin", "mimo.exe")

XDG_DIRS = {
    'XDG_CACHE_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'cache'),
    'XDG_DATA_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'data'),
    'XDG_STATE_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'state'),
    'XDG_CONFIG_HOME': os.path.join(_MIMO_NODE_GLOBAL, 'config'),
}

# ============================================================
# ANSI 解析
# ============================================================
ANSI_COLORS = {
    '30': 'Lemon.SYNTAX_COMMENT', '31': 'Lemon.ACCENT_RED', '32': 'Lemon.ACCENT_GREEN', '33': 'Lemon.STATUS_WARNING',
    '34': 'Lemon.ACCENT_BLUE', '35': 'Lemon.ACCENT_PURPLE', '36': 'Lemon.STATUS_RUNNING', '37': 'Lemon.PLACEHOLDER',
    '90': 'Lemon.SECONDARY', '91': 'Lemon.ACCENT_RED', '92': 'Lemon.ACCENT_GREEN', '93': 'Lemon.DARK_YELLOW_LIGHT',
    '94': 'Lemon.ACCENT_BLUE', '95': 'Lemon.ACCENT_PINK', '96': 'Lemon.STATUS_RUNNING', '97': 'Lemon.SURFACE',
}


def parse_ansi_to_html(text):
    """将 ANSI 转义字符转换为 HTML 样式"""
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


# ============================================================
# MIMO Bridge v3 — HTTP API
# ============================================================
class MIMOBridge(QObject):
    """MIMO Code 连接桥 — HTTP API 信号收发器"""

    # 信号
    connected = pyqtSignal(int)            # ACP 连接成功 (port)
    disconnected = pyqtSignal()
    output_received = pyqtSignal(str)       # 普通输出 (HTML)
    thinking_received = pyqtSignal(str)     # 思考过程 (HTML)
    tool_output_received = pyqtSignal(str)  # 工具输出 (HTML)
    error_occurred = pyqtSignal(str)        # 错误
    task_started = pyqtSignal(str)          # 任务开始
    task_finished = pyqtSignal(int)         # 任务完成 (exit_code)
    files_changed = pyqtSignal(list)        # 文件变更列表

    def __init__(self, project_path=None):
        super().__init__()
        self.project_path = os.path.abspath(project_path or os.getcwd())
        self._acp_process = None
        self._acp_port = 9877
        self._session_id = None
        self._running = False
        self._event_thread = None
        self._stop_event = threading.Event()
        self._base_url = f"http://127.0.0.1:{self._acp_port}"

    # ================================================================
    # ACP 服务器生命周期
    # ================================================================
    def start_acp(self, port=9877):
        """启动 ACP 服务器，等待就绪"""
        self._acp_port = port
        self._base_url = f"http://127.0.0.1:{port}"

        env = os.environ.copy()
        for key, val in XDG_DIRS.items():
            env[key] = val
            os.makedirs(os.path.join(val, 'mimocode'), exist_ok=True)

        try:
            self._acp_process = subprocess.Popen(
                [MIMO_EXE, "acp", f"--port={port}"],
                cwd=self.project_path,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        except Exception as e:
            self.error_occurred.emit(f"ACP 启动失败: {e}")
            return False

        # 等待服务器就绪
        if not self._wait_for_server(timeout=30):
            self.error_occurred.emit("ACP 服务器启动超时")
            return False

        # 启动 SSE 事件监听
        self._stop_event.clear()
        self._event_thread = threading.Thread(target=self._listen_events, daemon=True)
        self._event_thread.start()

        # 创建会话
        self._create_session()

        self.connected.emit(port)
        return True

    def _wait_for_server(self, timeout=30):
        """轮询 /global/health 等待服务器就绪"""
        start = time.time()
        while time.time() - start < timeout:
            if self._acp_process and self._acp_process.poll() is not None:
                return False
            try:
                req = urllib.request.Request(
                    f"{self._base_url}/global/health",
                    headers={"Accept": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                time.sleep(0.5)
        return False

    def stop_acp(self):
        """停止 ACP 服务器"""
        self._stop_event.set()
        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=3)

        if self._acp_process:
            try:
                self._acp_process.terminate()
                self._acp_process.wait(timeout=5)
            except Exception:
                try:
                    self._acp_process.kill()
                except Exception:
                    pass
            self._acp_process = None
            self._session_id = None
            self.disconnected.emit()

    # ================================================================
    # HTTP API 辅助方法
    # ================================================================
    def _api_request(self, method, path, body=None):
        """发送 HTTP 请求到 ACP 服务器"""
        url = f"{self._base_url}{path}"
        params = f"?directory={urllib.request.quote(self.project_path)}"

        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')

        req = urllib.request.Request(
            url + params,
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
            self.error_occurred.emit(f"HTTP {e.code}: {err_body[:200]}")
            return None
        except Exception as e:
            self.error_occurred.emit(f"请求失败: {e}")
            return None

    # ================================================================
    # 会话管理
    # ================================================================
    def _create_session(self):
        """创建新会话"""
        result = self._api_request("POST", "/session", {
            "title": "MIMO Agent Session",
        })
        if result:
            sid = result.get("sessionID") or result.get("id")
            if sid:
                self._session_id = sid
                return True
        # 尝试从 list 获取
        sessions = self._api_request("GET", "/session")
        if sessions and isinstance(sessions, list) and len(sessions) > 0:
            self._session_id = sessions[0].get("sessionID") or sessions[0].get("id")
            return True
        return False

    # ================================================================
    # 发送消息
    # ================================================================
    def execute(self, command):
        """发送命令到 MIMO Code"""
        if not self._session_id:
            self.error_occurred.emit("未连接到 ACP 服务器，请等待初始化完成")
            return

        self._running = True
        self.task_started.emit(command)

        # 在后台线程发送
        thread = threading.Thread(target=self._send_message, args=(command,), daemon=True)
        thread.start()

    def _send_message(self, command):
        """发送消息（POST 触发，SSE 接收响应）"""
        message_id = "msg_" + uuid.uuid4().hex
        body = {
            "messageID": message_id,
            "parts": [
                {"type": "text", "text": command}
            ],
        }

        # POST 发送消息（触发处理）
        result = self._api_request("POST", f"/session/{self._session_id}/message", body)
        if result is None:
            self._running = False
            self.task_finished.emit(-1)
            return

        # 轮询消息状态直到完成
        self._poll_message(message_id)

    def _poll_message(self, message_id, timeout=300):
        """轮询消息状态直到完成"""
        start = time.time()
        seen_parts = set()

        while time.time() - start < timeout:
            if self._stop_event.is_set():
                break

            time.sleep(0.5)

            # 获取消息
            result = self._api_request("GET", f"/session/{self._session_id}/message/{message_id}")
            if result is None:
                continue

            # 检查消息的 parts
            parts = result.get("parts", [])
            for part in parts:
                part_id = part.get("id", "")
                if part_id in seen_parts:
                    continue
                seen_parts.add(part_id)

                part_type = part.get("type", "")
                text = part.get("text", "")

                if part_type == "reasoning":
                    # 思考过程
                    if text.strip():
                        html = parse_ansi_to_html(text)
                        self.thinking_received.emit(html)
                elif part_type == "text":
                    # 正式回复
                    if text.strip():
                        html = parse_ansi_to_html(text)
                        self.output_received.emit(html)
                elif part_type == "tool-call" or part_type == "tool":
                    # 工具调用
                    tool_text = json.dumps(part, ensure_ascii=False, indent=2)
                    self.tool_output_received.emit(f"<pre>{tool_text}</pre>")
                elif part_type == "step-finish":
                    # 步骤完成
                    reason = part.get("reason", "")
                    if reason == "stop":
                        break

            # 检查状态
            status = result.get("status", "")
            if status in ("completed", "done", "error", "stopped"):
                break

            # 检查是否有 step-finish
            has_finish = any(p.get("type") == "step-finish" for p in parts)
            if has_finish:
                break

        self._running = False
        self.task_finished.emit(0)

    def _emit_content(self, text):
        """解析并分发内容"""
        text = text.strip()
        if not text:
            return

        html = parse_ansi_to_html(text)

        # 简单分类
        lower = text.lower()
        if any(kw in lower for kw in ['thinking', 'thought', '思考', '分析', '🤔', '💭']):
            self.thinking_received.emit(html)
        elif any(kw in lower for kw in ['tool', 'call', '🔧', 'execute', 'running']):
            self.tool_output_received.emit(html)
        elif any(kw in lower for kw in ['error', '错误', 'failed', '❌']):
            self.error_occurred.emit(text)
        else:
            self.output_received.emit(html)

    # ================================================================
    # SSE 事件监听
    # ================================================================
    def _listen_events(self):
        """监听 SSE 事件流"""
        url = f"{self._base_url}/event?directory={urllib.request.quote(self.project_path)}"
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})

        while not self._stop_event.is_set():
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    buffer = ""
                    for line_bytes in resp:
                        if self._stop_event.is_set():
                            break
                        try:
                            line = line_bytes.decode('utf-8').rstrip()
                        except Exception:
                            continue

                        if line == "":
                            # 空行表示事件结束
                            if buffer:
                                self._process_sse_event(buffer)
                                buffer = ""
                        elif line.startswith("data:"):
                            buffer += line[5:].strip()
                        elif line.startswith("event:"):
                            buffer += f"\n__event__:{line[6:].strip()}"
            except Exception as e:
                if not self._stop_event.is_set():
                    time.sleep(2)

    def _process_sse_event(self, data):
        """处理 SSE 事件"""
        try:
            parts = data.split("\n__event__:")
            event_type = parts[1] if len(parts) > 1 else "unknown"
            json_str = parts[0]

            event_data = json.loads(json_str)

            if event_type == "message.part.updated":
                part = event_data.get("part", {})
                content = part.get("content", "")
                if content and content.strip():
                    self._emit_content(content)

            elif event_type == "session.diff":
                changes = event_data.get("changes", [])
                if changes:
                    self.files_changed.emit(changes)

            elif event_type == "session.updated":
                pass  # 会话状态更新

        except json.JSONDecodeError:
            pass
        except Exception:
            pass

    # ================================================================
    # 获取 Diff
    # ================================================================
    def get_diff(self):
        """获取当前会话的文件变更"""
        if not self._session_id:
            return None
        return self._api_request("GET", f"/session/{self._session_id}/diff")

    # ================================================================
    # 控制
    # ================================================================
    def cancel(self):
        """取消当前任务"""
        self._stop_event.set()
        self._running = False
        if self._session_id:
            threading.Thread(
                target=lambda: self._api_request("POST", f"/session/{self._session_id}/abort"),
                daemon=True
            ).start()

    def is_running(self):
        return self._running

    def cleanup(self):
        """清理所有资源"""
        self.cancel()
        self.stop_acp()