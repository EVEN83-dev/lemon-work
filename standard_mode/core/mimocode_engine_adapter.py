# -*- coding: utf-8 -*-
"""
MIMO Code 引擎适配器 — 将 serve_bridge 包装为 AgentEngine 接口
===============================================================
使 EngineManager 能够统一管理 MIMO Code、Ollama、DeepSeek 三个引擎。

工作机制：
- MIMO Code 通过 serve_bridge（HTTP API + SSE）通信
- 本适配器将 serve_bridge 的信号转换为 AgentEngine 的回调
- stream() 通过轮询 _current_response 实现伪流式输出
"""

import re
import threading
import time
from typing import Optional, List, Dict, Generator

from agent_engine import (
    AgentEngine, EngineConfig, EngineStatus, EngineCapability
)


class MIMOCodEngineAdapter(AgentEngine):
    """
    MIMO Code 引擎适配器
    
    将 serve_bridge 包装为标准 AgentEngine 接口，
    使 EngineManager 可以统一管理三个引擎的切换。
    """

    def __init__(self, serve_bridge, config: Optional[EngineConfig] = None):
        super().__init__(config or EngineConfig(model="mimo-auto"))
        self._serve_bridge = serve_bridge
        self._name = "mimocode"
        self._display_name = "Lemon Code (MIMO)"
        self._capabilities = [
            EngineCapability.STREAMING,
            EngineCapability.TOOL_CALLING,
            EngineCapability.FILE_OPERATIONS,
            EngineCapability.CODE_EXECUTION,
            EngineCapability.CLOUD_ONLY,
        ]

        # 内部状态
        self._current_response = ""
        self._response_lock = threading.Lock()
        self._message_complete = threading.Event()
        self._streaming = False

        # 连接 serve_bridge 信号
        # ★ v3.26: 同时连接 stream_token（流式）和 output_received（完整），确保实时输出
        serve_bridge.stream_token.connect(self._handle_stream_token)
        serve_bridge.output_received.connect(self._handle_output)
        serve_bridge.thinking_received.connect(self._handle_thinking)
        serve_bridge.error_occurred.connect(self._handle_error)
        # 任务完成信号（idle状态时触发）
        if hasattr(serve_bridge, 'task_finished'):
            serve_bridge.task_finished.connect(self._handle_task_finished)

    # ==================== AgentEngine 接口 ====================

    def generate(self, prompt: str, context: Optional[List[Dict]] = None) -> str:
        """非流式生成 — 发送消息并等待完整回复"""
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        with self._response_lock:
            self._current_response = ""
        self._message_complete.clear()

        try:
            self._serve_bridge.send_message(prompt)
            # 等待消息完成（最多 120 秒）
            self._message_complete.wait(timeout=120)
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            return f"MIMO Code 错误: {e}"

        with self._response_lock:
            result = self._current_response

        self._set_status(EngineStatus.IDLE)
        return result

    def stream(self, prompt: str, context: Optional[List[Dict]] = None) -> Generator[str, None, None]:
        """流式生成 — 通过轮询 serve_bridge 的 SSE 输出实现"""
        self._set_status(EngineStatus.GENERATING)
        self.reset_cancel()

        with self._response_lock:
            self._current_response = ""
            self._prev_len = 0
        self._message_complete.clear()
        self._streaming = True

        try:
            self._serve_bridge.send_message(prompt)

            # 轮询等待消息完成，期间不断 yield 新增内容
            while not self._message_complete.is_set() and not self._is_cancelled():
                with self._response_lock:
                    response = self._current_response
                    prev = self._prev_len

                if len(response) > prev:
                    new_content = response[prev:]
                    with self._response_lock:
                        self._prev_len = len(response)

                    for char in new_content:
                        if self._is_cancelled():
                            return
                        self._emit_token(char)
                        yield char

                time.sleep(0.05)

            # 最后一次检查，确保所有内容都已 yield
            with self._response_lock:
                response = self._current_response
                prev = self._prev_len

            if len(response) > prev:
                new_content = response[prev:]
                for char in new_content:
                    self._emit_token(char)
                    yield char

            self._emit_message(response)
            self._set_status(EngineStatus.IDLE)

        except Exception as e:
            err = f"MIMO Code 流式错误: {e}"
            self._emit_error(err)
            self._set_status(EngineStatus.ERROR)
            yield err
        finally:
            self._streaming = False

    def get_models(self) -> List[Dict]:
        """获取可用模型列表"""
        return [
            {"id": "mimo-auto", "name": "MIMO Auto (默认)", "description": "自动选择最优模型"},
            {"id": "mimo-v4", "name": "MIMO V4", "description": "最新版本"},
            {"id": "mimo-v3", "name": "MIMO V3", "description": "稳定版本"},
        ]

    def get_status_info(self) -> Dict:
        """获取引擎状态信息"""
        return {
            "name": self._name,
            "display_name": self._display_name,
            "available": self._serve_bridge.is_running,
            "status": self._status.value,
            "model": self.config.model,
            "models": self.get_models(),
        }

    def is_available(self) -> bool:
        """检查 MIMO Code 服务是否运行"""
        return self._serve_bridge.is_running

    def cancel(self):
        """取消当前生成"""
        # 调用父类的 cancel() 方法设置取消标志
        super().cancel()
        try:
            self._serve_bridge.cancel()
        except Exception:
            pass
        self._message_complete.set()

    # ==================== serve_bridge 信号处理 ====================

    def _handle_stream_token(self, token: str):
        """流式 token → 实时累积到 _current_response（关键修复）"""
        with self._response_lock:
            self._current_response += token

    def _handle_output(self, html: str):
        """serve_bridge 完整输出 → 提取纯文本并累积"""
        text = re.sub(r'<[^>]+>', '', html).strip()
        with self._response_lock:
            self._current_response = text

    def _handle_thinking(self, html: str):
        """思考过程 → 转发到 thinking 回调"""
        text = re.sub(r'<[^>]+>', '', html).strip()
        if text:
            self._emit_thinking(text)

    def _handle_error(self, msg: str):
        """错误 → 转发到 error 回调"""
        self._emit_error(msg)
        self._message_complete.set()

    def _handle_task_finished(self, success: bool, message: str = ""):
        """任务完成 → 设置完成标志"""
        self._message_complete.set()

    def _is_cancelled(self) -> bool:
        return self._cancel_flag.is_set()
