# -*- coding: utf-8 -*-
"""
CrossEngineBridge — 跨引擎桥接（P2 引擎无关化 · 终章）
========================================================

在多个 ``BaseEngineAdapter`` 之间提供**跨引擎编排**能力，实现路线图中
CrossEngineBridge 的三个子能力：

- **SessionBridge（会话状态跨引擎保持）**：会话（session）内的消息历史在任意引擎间
  无缝延续——中途 ``switch_engine`` 后，新引擎仍能读到完整上下文；
- **ContextBridge（跨引擎上下文传递）**：``chat_multi_engine`` 把同一任务的中间
  结果（前一个引擎的回复）作为上下文喂给下一个引擎，实现「推理引擎出草稿 →
  生成引擎润色」等多引擎流水线；
- **FormatAdapter（prompt 格式转换）**：``normalize_messages`` / ``format_tool_result``
  把各种输入（字符串 / 混合消息）统一为 OpenAI 风格 ``[{role, content}]``，
  消除不同引擎对 prompt 格式的差异。

与 ``SmartDispatcher`` 互补：Dispatcher 负责单请求的多后端容错路由；本桥负责
多引擎流水线/会话级编排。两者均只面向 ``BaseEngineAdapter`` 统一接口，不感知
具体后端（Ollama / DeepSeek / MimoCode）。

本模块纯编排逻辑，不发起任何网络请求；所有 IO 委托给底层适配器。
"""

import threading
import uuid
from typing import Any, Dict, List, Optional

# ★ P2 引擎无关化：复用统一适配器契约（兼容两种包导入方式）
try:
    from engines.base import BaseEngineAdapter
except ImportError:
    try:
        from shared.engines.base import BaseEngineAdapter
    except ImportError:
        # 兜底占位：理论上 shared/engines/base.py 必然存在
        class BaseEngineAdapter:  # type: ignore
            name = "abstract_engine"

_DEFAULT_ROLES = ("system", "user", "assistant", "tool")


class CrossEngineBridge:
    """
    跨引擎桥接：会话级多引擎编排（线程安全）。
    """

    def __init__(self, adapters: Optional[List[BaseEngineAdapter]] = None):
        self._adapters: Dict[str, BaseEngineAdapter] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._stats: Dict[str, Dict[str, int]] = {}
        self._lock = threading.Lock()
        for a in adapters or []:
            self.register(a)

    # ==================== 引擎注册 / 查询 ====================

    def register(self, adapter: BaseEngineAdapter) -> None:
        """注册引擎适配器（按 name 覆盖）。"""
        with self._lock:
            self._adapters[adapter.name] = adapter
            self._stats.setdefault(adapter.name, {"calls": 0, "errors": 0})

    def list_engines(self) -> List[str]:
        """返回全部已注册引擎名。"""
        return list(self._adapters)

    def get_engine(self, name: str) -> Optional[BaseEngineAdapter]:
        """按名获取引擎适配器。"""
        return self._adapters.get(name)

    # ==================== FormatAdapter：格式统一 ====================

    @staticmethod
    def normalize_messages(messages: Any) -> List[Dict]:
        """
        把各种消息输入统一为 OpenAI 风格 ``[{"role", "content"}, ...]``。

        - 传入字符串 → 转为单条 user 消息；
        - 传入 dict → 按 role/content 校验后转为单条；
        - 传入 list → 逐条归一化（缺 role 的字符串视为 user，缺 content 的置空串）。
        """
        if isinstance(messages, str):
            return [{"role": "user", "content": messages}]
        if isinstance(messages, dict):
            return [CrossEngineBridge._normalize_one(messages)]
        if not isinstance(messages, list):
            raise TypeError(f"无法识别的消息类型: {type(messages).__name__}")
        return [CrossEngineBridge._normalize_one(m) for m in messages]

    @staticmethod
    def _normalize_one(msg: Any) -> Dict:
        if isinstance(msg, str):
            return {"role": "user", "content": msg}
        if not isinstance(msg, dict):
            raise TypeError(f"消息项必须是 str 或 dict，收到 {type(msg).__name__}")
        role = str(msg.get("role", "user"))
        if role not in _DEFAULT_ROLES:
            role = "user"
        content = msg.get("content")
        return {"role": role, "content": "" if content is None else str(content)}

    @staticmethod
    def format_tool_result(tool_name: str, result: Any) -> Dict:
        """把工具执行结果格式化为 tool 消息（供适配器工具链路使用）。"""
        return {
            "role": "tool",
            "name": str(tool_name),
            "content": str(result),
        }

    # ==================== SessionBridge：会话管理 ====================

    def create_session(self, engine_name: Optional[str] = None,
                       system_prompt: Optional[str] = None,
                       session_id: Optional[str] = None) -> str:
        """
        创建跨引擎会话。

        Args:
            engine_name: 初始绑定的引擎（None 表示延迟到首次 send 时指定）
            system_prompt: 系统提示词（作为首条 system 消息）
            session_id: 显式会话 ID（None 则自动生成 UUID）
        """
        if engine_name is not None and engine_name not in self._adapters:
            raise KeyError(f"未注册引擎: {engine_name}")
        sid = session_id or uuid.uuid4().hex[:12]
        messages: List[Dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        with self._lock:
            self._sessions[sid] = {
                "messages": messages,
                "engine": engine_name,
            }
        return sid

    def get_history(self, session_id: str) -> List[Dict]:
        """返回会话完整消息历史（副本，防外部篡改）。"""
        with self._lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError(f"会话不存在: {session_id}")
        return list(sess["messages"])

    def get_session_engine(self, session_id: str) -> Optional[str]:
        """返回会话当前绑定的引擎名。"""
        with self._lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError(f"会话不存在: {session_id}")
        return sess["engine"]

    def switch_engine(self, session_id: str, engine_name: str) -> None:
        """切换会话绑定的引擎（历史上下文原样保留）。"""
        if engine_name not in self._adapters:
            raise KeyError(f"未注册引擎: {engine_name}")
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                raise KeyError(f"会话不存在: {session_id}")
            sess["engine"] = engine_name

    def clear_session(self, session_id: str) -> None:
        """删除会话。"""
        with self._lock:
            self._sessions.pop(session_id, None)

    def list_sessions(self) -> List[str]:
        """列出全部会话 ID。"""
        with self._lock:
            return list(self._sessions)

    # ==================== ContextBridge：跨引擎对话 ====================

    def send(self, session_id: str, user_text: str,
             engine_name: Optional[str] = None, **kwargs) -> str:
        """
        向当前（或指定）引擎发送消息并返回回复，上下文自动续写。

        Args:
            session_id: 会话 ID
            user_text: 用户消息
            engine_name: 指定引擎（None 则用会话当前绑定引擎）
        """
        with self._lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError(f"会话不存在: {session_id}")
        engine = engine_name or sess["engine"]
        if engine is None:
            raise ValueError("会话未绑定引擎，请通过 engine_name 或 create_session 指定")
        adapter = self._adapters.get(engine)
        if adapter is None:
            raise KeyError(f"未注册引擎: {engine}")

        # 读取历史 + 追加本次 user 消息
        messages = self.get_history(session_id)
        messages = messages + [{"role": "user", "content": user_text}]

        try:
            reply = adapter.chat(messages, **kwargs)
            error = None
        except Exception as ex:
            reply = ""
            error = str(ex)

        # 写入上下文（无论成败都追加，便于追溯）
        with self._lock:
            sess2 = self._sessions[session_id]
            sess2["messages"] = messages + [{"role": "assistant", "content": reply}]
            self._bump_stat(engine, error is not None)

        if error:
            raise RuntimeError(f"[{engine}] 调用失败: {error}")
        return reply

    def chat_multi_engine(self, session_id: str, user_text: str,
                          engine_sequence: List[str], **kwargs) -> List[Dict]:
        """
        跨引擎流水线：把同一任务的用户消息依次送给 sequence 中的每个引擎，
        前一个引擎的回复作为上下文传给下一个引擎（跨引擎结果传递）。

        Returns:
            List[Dict]，每个元素 ``{"engine", "output"}``。
        """
        messages = self.get_history(session_id) + [{"role": "user", "content": user_text}]
        steps: List[Dict] = []
        for name in engine_sequence:
            adapter = self._adapters.get(name)
            if adapter is None:
                raise KeyError(f"未注册引擎: {name}")
            try:
                reply = adapter.chat(messages, **kwargs)
                err = None
            except Exception as ex:
                reply = ""
                err = str(ex)
            steps.append({"engine": name, "output": reply})
            messages = messages + [{"role": "assistant", "content": reply}]
            with self._lock:
                self._bump_stat(name, err is not None)
            if err:
                raise RuntimeError(f"[{name}] 调用失败: {err}")
        # 流水线结果并入会话历史
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is not None:
                sess["messages"] = messages
        return steps

    def _bump_stat(self, engine: str, is_error: bool) -> None:
        st = self._stats.setdefault(engine, {"calls": 0, "errors": 0})
        st["calls"] += 1
        if is_error:
            st["errors"] += 1

    # ==================== 统计 / 资源 ====================

    def get_stats(self) -> Dict[str, Any]:
        """返回各引擎调用统计。"""
        with self._lock:
            return {name: dict(st) for name, st in self._stats.items()}

    def cleanup(self) -> None:
        """释放全部底层引擎资源。"""
        for a in self._adapters.values():
            try:
                a.cleanup()
            except Exception:
                pass


if __name__ == "__main__":
    # 简易自测（无网络，内存桩适配器）
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    class _Stub(BaseEngineAdapter):
        def __init__(self, name):
            super().__init__(None)
            self.name = name

        def chat(self, messages, **kwargs):
            return f"<{self.name}@{len(messages)}条上下文>"

        def generate_with_tools(self, messages, tools, **kwargs):
            return {"content": f"<{self.name}>", "tool_calls": []}

        def is_available(self):
            return True

        def cleanup(self):
            pass

    br = CrossEngineBridge(adapters=[_Stub("reasoner"), _Stub("writer")])
    sid = br.create_session(engine_name="reasoner", system_prompt="你是推理引擎")
    print("reply1:", br.send(sid, "分析问题"))
    br.switch_engine(sid, "writer")
    print("reply2(切换引擎):", br.send(sid, "写成文章"))
    print("steps:", br.chat_multi_engine(sid, "再来一次", ["reasoner", "writer"]))
    print("stats:", br.get_stats())
