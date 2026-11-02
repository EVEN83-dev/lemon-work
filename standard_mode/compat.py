# -*- coding: utf-8 -*-
"""
Standard Mode 兼容层 — 桥接旧代码到统一的 EngineManager
===============================================================
作用：
- 让 standard_mode 的旧代码可以使用 shared/engine_manager.py 或 bridge/ 引擎
- 保持向后兼容，不破坏现有功能
- 支持 USE_BRIDGE_ENGINE 环境变量切换到 bridge 层引擎

使用方法：
    # 在 standard_mode 的代码中，把：
    from core.ollama_bridge import OllamaBridge
    # 改为：
    from standard_mode.compat import OllamaBridge
"""

import os
import threading
import logging
from typing import List, Dict, Optional, Callable

from PyQt5.QtCore import QObject, pyqtSignal

from shared.engine_manager import (
    EngineManager as SharedEngineManager,
    ChatResponse,
    get_engine_manager,
    chat as shared_chat,
)

USE_BRIDGE_ENGINE = os.environ.get("LEMON_USE_BRIDGE_ENGINE", "").lower() in ("1", "true", "yes")

logger = logging.getLogger(__name__)


# ==================== FROZEN 标记（已解除，2026-08-08 作者授权） ====================
# 口令校验通过：天津职业技术师范大学。解除后核心改动仍须 CodeLock 留痕，
# 且仅"在现有技术基础上完善，不得破坏架构"。
STANDARD_MODE_FROZEN = False
FREEZE_REASON = "标准模式功能已验证通过，为防止混合模式开发破坏，已锁定（已于 2026-08-08 由作者授权解除）"


# ==================== 兼容层 ====================

class OllamaBridgeCompat(QObject):
    """
    OllamaBridge 兼容层 — 与原 OllamaBridge 接口完全兼容

    保持与原 OllamaBridge 相同的接口（pyqtSignal + 异步chat），
    但内部使用 shared EngineManager 统一调用 AI。

    信号：
    - reply_received(str): 收到回复
    - error_occurred(str): 发生错误
    """

    reply_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, host: str = "http://127.0.0.1:11434", model: str = "qwen3.5:4b", parent=None):
        super().__init__(parent)
        self.host = host.rstrip("/")
        self.model = model
        self._engine = get_engine_manager()
        self._history: List[Dict[str, str]] = []
        self._max_history_turns = 6
        self._lock = threading.Lock()
        self._busy = False

    def is_available(self) -> bool:
        """检查 Ollama 服务是否在运行"""
        return self._engine.get_status().get("ollama", {}).get("available", False)

    def is_busy(self) -> bool:
        return self._busy

    def chat(self, prompt: str, context: Optional[List[Dict[str, str]]] = None) -> None:
        """
        异步调用 AI 对话（与原 OllamaBridge.chat 签名兼容）

        参数：
            prompt: 用户输入
            context: 外部上下文消息（可选）
        """
        with self._lock:
            self._busy = True

        t = threading.Thread(
            target=self._do_chat,
            args=(prompt, context),
            daemon=True
        )
        t.start()

    def _do_chat(self, user_prompt: str, context=None) -> None:
        """子线程执行：通过 EngineManager 调用 AI"""
        content = ""
        try:
            # 构建消息列表
            messages = []
            # 添加上下文
            if context:
                for m in context:
                    if isinstance(m, dict) and "role" in m and "content" in m:
                        messages.append(m)

            # 使用 EngineManager 统一调用
            response = self._engine.chat(
                user_prompt,
                engine="ollama",
                model=self.model,
                history=messages,
            )
            content = response.content

            # 截断过长回复（与原逻辑一致）
            if len(content) > 80:
                for i, ch in enumerate(content):
                    if ch in '。！？!?' and i > 15:
                        content = content[:i + 1]
                        break
                else:
                    content = content[:60] + "..."

            # 更新历史
            with self._lock:
                self._history.append({"role": "user", "content": user_prompt})
                self._history.append({"role": "assistant", "content": content})
                max_keep = self._max_history_turns * 2
                if len(self._history) > max_keep:
                    self._history = self._history[-max_keep:]

            self.reply_received.emit(content)

        except Exception as e:
            logger.exception("OllamaBridgeCompat 调用异常")
            self.error_occurred.emit(f"柠檬小助手出错了: {e}")
        finally:
            with self._lock:
                self._busy = False

    def clear_history(self) -> None:
        """清空对话历史"""
        with self._lock:
            self._history.clear()

    # ============================================================
    # 代码审查模式（兼容原接口）
    # ============================================================
    def review_code(self, code: str, file_path: str = "", language: str = "") -> None:
        """异步代码审查 — 使用 EngineManager 统一调用"""
        ext = os.path.splitext(file_path)[1].lower() if file_path else language
        lang_name = {
            '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
            '.html': 'HTML', '.css': 'CSS', '.json': 'JSON',
        }.get(ext, language or '代码')

        review_prompt = f"""请审查以下{lang_name}代码，找出潜在问题并给出改进建议。

审查要点：
1. 代码逻辑错误或潜在 bug
2. 性能问题和优化建议
3. 安全漏洞（如 SQL 注入、XSS 等）
4. 代码风格和可读性问题
5. 最佳实践建议

请用中文回复，每个问题1-2句话。如果没有明显问题就回复'代码质量良好，无明显问题'。

代码：
```{ext.lstrip('.')}
{code[:3000]}
```"""

        with self._lock:
            self._busy = True

        t = threading.Thread(
            target=self._do_review,
            args=(review_prompt, file_path),
            daemon=True
        )
        t.start()

    def _do_review(self, review_prompt: str, file_path: str) -> None:
        """执行代码审查（子线程）"""
        content = ""
        try:
            response = self._engine.chat(
                review_prompt,
                engine="ollama",
                model=self.model,
            )
            content = response.content

            if not content:
                content = "代码审查未返回结果，请重试"

            logger.info(f"代码审查完成: {file_path} ({len(content)} 字符)")
            self.reply_received.emit(f"[审查] {file_path}\n{content}")

        except Exception as e:
            logger.exception("代码审查异常")
            self.error_occurred.emit(f"代码审查出错: {e}")
        finally:
            with self._lock:
                self._busy = False

    # ============================================================
    # 流式对话（兼容原接口）
    # ============================================================
    def stream_chat(self, prompt: str, context: Optional[List[Dict[str, str]]] = None,
                    on_delta: Optional[Callable] = None,
                    on_complete: Optional[Callable] = None,
                    on_error: Optional[Callable] = None) -> None:
        """异步流式对话 — 通过 EngineManager 流式输出"""
        with self._lock:
            self._busy = True

        t = threading.Thread(
            target=self._do_stream_chat,
            args=(prompt, context, on_delta, on_complete, on_error),
            daemon=True
        )
        t.start()

    def _do_stream_chat(self, prompt: str, context, on_delta, on_complete, on_error) -> None:
        """执行流式请求（子线程）"""
        full_text = ""
        try:
            for token in self._engine.stream_chat(prompt, engine="ollama", model=self.model):
                full_text += token
                if on_delta:
                    on_delta(token)

            if on_complete:
                on_complete(full_text)

            self.reply_received.emit(full_text)

        except Exception as e:
            logger.exception("流式对话异常")
            msg = f"流式对话出错: {e}"
            if on_error:
                on_error(msg)
            self.error_occurred.emit(msg)
        finally:
            with self._lock:
                self._busy = False


# ==================== Bridge 引擎兼容 ====================

def _get_bridge_engine_compat():
    from bridge.event_adapter import BridgeEngineCompat, get_bridge_engine_compat
    return get_bridge_engine_compat()


def get_engine():
    if USE_BRIDGE_ENGINE:
        return _get_bridge_engine_compat()
    return get_engine_manager()


# ==================== 便捷函数 ====================

def chat(prompt: str, model: str = "qwen3.5:4b") -> str:
    if USE_BRIDGE_ENGINE:
        compat = _get_bridge_engine_compat()
        resp = compat.chat(prompt, engine="ollama", model=model)
        return resp.content
    return shared_chat(prompt, engine="ollama", model=model)


def get_bridge() -> OllamaBridgeCompat:
    if not hasattr(get_bridge, '_instance'):
        get_bridge._instance = OllamaBridgeCompat()
    return get_bridge._instance


# ==================== 导出 ====================

OllamaBridge = OllamaBridgeCompat

__all__ = [
    "OllamaBridge",
    "OllamaBridgeCompat",
    "chat",
    "get_bridge",
    "get_engine",
    "USE_BRIDGE_ENGINE",
    "STANDARD_MODE_FROZEN",
    "FREEZE_REASON",
]