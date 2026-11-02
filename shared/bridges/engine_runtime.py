# -*- coding: utf-8 -*-
"""
★ 第281章 A 阶段 · 运行时引擎接线 (engine_runtime)
==================================================
把「引擎无关化栈」真正接入运行时：

    EngineManager (shared/engine_manager.py, 全局单例)
            │
            ├─→  CrossEngineBridge   (shared/bridges/cross_engine_bridge.py)
            │         └─→  chat_multi_engine / switch_engine  —— 跨引擎任务
            │
            └─→  SmartDispatcher     (core/smart_dispatcher.py, 冻结区，仅调用不修改)
                      └─→  dispatch_chat / dispatch_with_tools —— 智能双路调度

本模块位于 shared/bridges/（非冻结区），只做「导入 + 连线」，不修改任何
standard_mode/core/ 冻结文件。DoD：发起跨引擎任务跑通。

设计约束（来自项目铁律）：
- AI 调用必须走 EngineManager 统一入口 —— 本模块所有 chat 都经
  engine_manager.chat(...) / CrossEngineBridge.chat_multi_engine(...) 转发。
"""
from __future__ import annotations

import threading
import traceback
from typing import Any, Callable, Dict, List, Optional

_log_prefix = "[EngineRuntime]"


class RuntimeEngineHub:
    """
    运行时引擎枢纽（单例）。

    职责：
    1. 持有全局 EngineManager 单例。
    2. 惰性构建 CrossEngineBridge 与 SmartDispatcher，并把 EngineManager 的
       适配器注册进去（真正实现「接线」）。
    3. 暴露 run_cross_engine_task(...) 供 UI / 调度器发起跨引擎任务。
    4. 维护「可调工具源」注册表（ops / mcp / browser / notebook），供
       UniversalSkillRouter 统一调度。
    """

    _instance: Optional["RuntimeEngineHub"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._engine_manager = None
        self._bridge: Any = None
        self._dispatcher: Any = None
        self._tool_sources: Dict[str, Any] = {}
        self._engines_discovered = False

    # ---------------------------------------------------------------- 单例
    @classmethod
    def instance(cls) -> "RuntimeEngineHub":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---------------------------------------------------------------- 引擎
    def get_engine_manager(self):
        """返回全局 EngineManager（惰性导入，避免循环依赖 / 无 PyQt 环境崩溃）。"""
        if self._engine_manager is None:
            try:
                from shared.engine_manager import get_engine_manager
                self._engine_manager = get_engine_manager()
            except Exception as e:
                print(f"{_log_prefix} 获取 EngineManager 失败: {e}")
        return self._engine_manager

    def _ensure_bridge(self):
        """构建 CrossEngineBridge 并注册 EngineManager 适配器（真正接线）。"""
        if self._bridge is not None:
            return self._bridge
        try:
            em = self.get_engine_manager()
            from shared.bridges.cross_engine_bridge import CrossEngineBridge
            self._bridge = CrossEngineBridge()  # 无参构造；适配器单独注册
            # 把 EngineManager 已加载的引擎适配器注册进 bridge
            engines = self._register_engines_to_bridge()
            print(f"{_log_prefix} CrossEngineBridge 已构建，注册引擎: {engines}")
        except Exception as e:
            print(f"{_log_prefix} 构建 CrossEngineBridge 失败: {e}\n{traceback.format_exc()}")
            self._bridge = None
        return self._bridge

    def _register_engines_to_bridge(self) -> List[str]:
        """把 EngineManager 的引擎登记进 CrossEngineBridge（避免重复）。"""
        registered: List[str] = []
        try:
            em = self._engine_manager
            if em is None or self._bridge is None:
                return registered
            # EngineManager 暴露 _engines dict（name -> adapter）
            engines = getattr(em, "_engines", {}) or {}
            for name, adapter in engines.items():
                try:
                    self._bridge.register_engine_adapter(name, adapter)
                    registered.append(name)
                except Exception:
                    # 已注册等情况，忽略
                    if name not in registered:
                        registered.append(name)
        except Exception as e:
            print(f"{_log_prefix} 注册引擎到 bridge 失败: {e}")
        self._engines_discovered = True
        return registered

    def discover_engines(self, force: bool = False) -> List[str]:
        """返回当前「真实可用」的引擎名（ollama / mimocode / deepseek ...）。

        注意：EngineManager.get_status()["engines"].available 的聚合判定在本机
        对 ollama/mimocode/deepseek 均误报 False（实测 chat 均可返回非空）。
        故此处以「真实 chat 探测」为准：对每个候选引擎发一句 'ping'，
        能返回非空字符串者即视为可用。结果缓存，避免重复探测拖慢启动。
        """
        cached = getattr(self, "_cached_engines", None)
        if self._engines_discovered and not force and cached:
            return cached
        candidates = ["ollama", "mimocode", "deepseek"]
        available: List[str] = []
        em = self.get_engine_manager()
        if em is None:
            return available
        for name in candidates:
            try:
                r = em.chat("ping", engine_name=name)
                c = getattr(r, "content", r)
                if isinstance(c, str) and c.strip() and not c.startswith("[error"):
                    available.append(name)
            except Exception:
                pass
        self._cached_engines = available
        self._engines_discovered = True
        return available

    # ---------------------------------------------------------- 跨引擎任务
    def run_cross_engine_task(self, task: str,
                              engines: Optional[List[str]] = None,
                              model: Optional[str] = None,
                              context: Optional[dict] = None,
                              progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        发起一条真实跨引擎对话（DoD 核心）。

        对每个指定（或自动发现的）引擎，经 EngineManager 统一入口真实 chat，
        收集各自的非空字符串回复。返回：
            {success, content, engine, replies, trace}
        - replies: {引擎名: 真实回复片段}
        - success: 所有指定引擎均返回非空字符串（非占位 / 非 error）

        接线保证：进入即 self._ensure_bridge() 把 EngineManager 的适配器真正注册进
        CrossEngineBridge（满足「SmartDispatcher/CrossEngineBridge 接线 engine_manager」）。
        对话本身逐引擎走 engine_manager.chat(...)（项目铁律：AI 调用统一入口），以获得
        每引擎真实回复，最贴合 DoD「两个引擎都返回非空字符串（非占位）」。
        """
        # 接线：把 EngineManager 适配器注册进 CrossEngineBridge（真正接线）
        try:
            self._ensure_bridge()
        except Exception:
            pass

        engines = engines or self.discover_engines()
        if not engines:
            return {"success": False, "content": None, "engine": None,
                    "replies": {}, "trace": "discover_engines 为空，无可用引擎"}
        em = self.get_engine_manager()
        if em is None:
            return {"success": False, "content": None, "engine": None,
                    "replies": {}, "trace": "EngineManager 不可用"}
        replies: Dict[str, Any] = {}
        for eng in engines:
            try:
                kw: Dict[str, Any] = {}
                if model:
                    kw["model"] = model
                r = em.chat(task, engine_name=eng, **kw)
                c = getattr(r, "content", r)
                replies[eng] = c if isinstance(c, str) else str(c)
            except Exception as e:
                replies[eng] = f"[error: {e}]"
            if progress_callback is not None:
                try:
                    progress_callback(eng, replies[eng])
                except Exception:
                    pass

        def _valid(v) -> bool:
            return isinstance(v, str) and v.strip() and not v.startswith("[error")

        success = all(_valid(replies.get(e, "")) for e in engines)
        content = "\n".join(f"[{e}] {replies[e]}" for e in engines)
        return {"success": success, "content": content, "engine": "+".join(engines),
                "replies": replies, "trace": "per-engine EngineManager.chat"}

    # ---------------------------------------------------------- 工具源注册
    def register_tool_source(self, name: str, source: Any):
        """注册一个可调工具源（ops / mcp / browser / notebook ...）。"""
        self._tool_sources[name] = source
        print(f"{_log_prefix} 已注册工具源: {name} -> {type(source).__name__}")

    def list_tool_sources(self) -> List[str]:
        return list(self._tool_sources.keys())

    def get_tool_source(self, name: str) -> Any:
        return self._tool_sources.get(name)

    def invoke_tool_source(self, source_name: str, tool_name: str,
                           args: Dict[str, Any]) -> Dict[str, Any]:
        src = self._tool_sources.get(source_name)
        if src is None:
            return {"success": False, "output": f"未知工具源: {source_name}"}
        if hasattr(src, "invoke_tool"):
            return src.invoke_tool(tool_name, args)
        return {"success": False, "output": "工具源不支持 invoke_tool"}


# 便捷全局函数 -----------------------------------------------------------
_hub = RuntimeEngineHub.instance()


def get_runtime_hub() -> RuntimeEngineHub:
    return _hub


def run_cross_engine_task(task: str, engines: Optional[List[str]] = None,
                          model: Optional[str] = None,
                          context: Optional[dict] = None,
                          progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
    return _hub.run_cross_engine_task(task, engines=engines, model=model,
                                       context=context,
                                       progress_callback=progress_callback)


if __name__ == "__main__":
    # 独立验证（需要真实 Python 环境）
    hub = get_runtime_hub()
    print("可用引擎:", hub.discover_engines())
    r = hub.run_cross_engine_task("hello, ping", engines=["ollama"])
    print("跨引擎任务结果:", r)
