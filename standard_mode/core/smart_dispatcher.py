# -*- coding: utf-8 -*-
"""
SmartDispatcher — 引擎无关智能调度器（P2 / P1）
================================================

在多个 ``BaseEngineAdapter`` 实例之上提供**智能路由 / 故障转移**能力，是
P2 引擎无关化的核心调度层：

- 完全基于 ``BaseEngineAdapter`` 统一接口（chat / generate_with_tools /
  is_available / cleanup），不感知底层是 Ollama / DeepSeek 还是 MimoCode；
- 按 ``preferred_order`` 优先级 + 实时成功率择优选择引擎；
- 主引擎调用失败时自动 fallback 到下一个可用引擎（故障转移）；
- 记录每引擎成功率 / 失败信息，供「smart」择优与可观测性。

本模块为纯调度逻辑，**不发起任何网络请求**；所有 IO 都委托给底层适配器。
上层（EngineManager / SuperBrain / UniversalSkillRouter）可面向本调度器编程，
以引擎无关方式获得多后端容错能力。

示例：
    from standard_mode.core.smart_dispatcher import SmartDispatcher
    from shared.engine_manager import EngineManager

    em = EngineManager(...)                       # 主通道（已持有 BaseEngineAdapter）
    dispatcher = SmartDispatcher(
        engines=[em.get_engine("ollama"),
                 em.get_engine("deepseek"),
                 em.get_engine("mimocode")],
        preferred_order=["deepseek", "ollama", "mimocode"],
    )
    reply = dispatcher.dispatch_chat([{"role": "user", "content": "hi"}])
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ★ 引擎无关化：复用 P2 基座的统一适配器契约（兼容两种包导入方式）
try:
    from engines.base import BaseEngineAdapter
except ImportError:
    try:
        from shared.engines.base import BaseEngineAdapter
    except ImportError:
        # 兜底占位：理论上 shared/engines/base.py 必然存在
        class BaseEngineAdapter:  # type: ignore
            name = "abstract_engine"


@dataclass
class EngineScore:
    """单引擎调度评分（累计统计，用于 smart 择优与可观测性）。"""
    name: str
    available: bool = False
    success_count: int = 0
    fail_count: int = 0
    last_error: str = ""
    last_latency_ms: float = 0.0

    @property
    def total(self) -> int:
        return self.success_count + self.fail_count

    @property
    def success_rate(self) -> float:
        """成功率（无样本时为 1.0，表示不惩罚未知引擎）。"""
        return self.success_count / self.total if self.total else 1.0


class SmartDispatcher:
    """
    引擎无关智能调度器。

    线程安全；所有公共方法可在多线程环境下调用（内部以 ``_lock`` 保护统计与注册）。
    """

    def __init__(self,
                 engines: Optional[List[BaseEngineAdapter]] = None,
                 preferred_order: Optional[List[str]] = None):
        self._engines: List[BaseEngineAdapter] = list(engines or [])
        self._preferred_order: List[str] = list(preferred_order or [])
        self._scores: Dict[str, EngineScore] = {}
        self._lock = threading.Lock()
        for e in self._engines:
            self._scores.setdefault(e.name, EngineScore(name=e.name))

    # ==================== 注册 / 查询 ====================

    def register(self, engine: BaseEngineAdapter) -> None:
        """注册一个引擎适配器（按 name 去重）。"""
        with self._lock:
            if not any(e.name == engine.name for e in self._engines):
                self._engines.append(engine)
            self._scores.setdefault(engine.name, EngineScore(name=engine.name))

    @classmethod
    def from_engine_provider(cls, provider, names: Optional[List[str]] = None,
                             preferred_order: Optional[List[str]] = None) -> "SmartDispatcher":
        """
        从任意「引擎提供者」（鸭子类型，需提供 ``get_engine(name)``）构建调度器，
        便于与 EngineManager 等主通道集成，且不涉及跨层直接 import。

        示例：
            dispatcher = SmartDispatcher.from_engine_provider(
                engine_manager,                     # 提供 get_engine(name)
                names=["deepseek", "ollama", "mimocode"],
                preferred_order=["deepseek", "ollama", "mimocode"],
            )
        """
        names = names or ["deepseek", "ollama", "mimocode"]
        engines = []
        for n in names:
            eng = provider.get_engine(n) if hasattr(provider, "get_engine") else None
            if eng is not None:
                engines.append(eng)
        return cls(engines=engines, preferred_order=preferred_order or names)

    def list_engines(self) -> List[str]:
        """返回所有已注册引擎名。"""
        return [e.name for e in self._engines]

    def get_engine(self, name: str) -> Optional[BaseEngineAdapter]:
        """按名获取引擎适配器（不存在返回 None）。"""
        for e in self._engines:
            if e.name == name:
                return e
        return None

    def available_engines(self) -> List[BaseEngineAdapter]:
        """
        返回当前可用引擎（按 preferred_order + 成功率排序）。
        注意：会调用各适配器的 is_available()，可能触发轻量探测。
        """
        return [e for e in self._select() if e.is_available()]

    # ==================== 智能择优 ====================

    def _ordered_engines(self) -> List[BaseEngineAdapter]:
        """按 preferred_order 排序（未列出的排最后，保持原相对顺序）。"""
        if not self._preferred_order:
            return list(self._engines)
        order = {n: i for i, n in enumerate(self._preferred_order)}
        return sorted(self._engines,
                      key=lambda e: order.get(e.name, len(order)))

    def _select(self) -> List[BaseEngineAdapter]:
        """
        计算候选顺序：先按 preferred_order，再在可用引擎中按成功率降序。
        返回已排序的全部引擎（调用方自测可用性）。
        """
        ordered = self._ordered_engines()
        # 以成功率做 smart 微调：可用引擎中成功率高者优先
        return sorted(
            ordered,
            key=lambda e: (
                # preferred_order 权重（越小越优先）
                self._preferred_rank(e.name),
                # 成功率（高者优先）
                -self._scores.get(e.name, EngineScore(e.name)).success_rate,
            ),
        )

    def _preferred_rank(self, name: str) -> int:
        if not self._preferred_order:
            return 0
        return self._preferred_order.index(name) if name in self._preferred_order else len(self._preferred_order)

    # ==================== 调度入口 ====================

    def dispatch_chat(self, messages: List[Dict], **kwargs) -> str:
        """
        引擎无关对话调度：逐候选调用 chat，成功即返回，失败 fallback 到下一可用引擎。

        Raises:
            RuntimeError: 所有引擎均不可用或调用失败。
        """
        candidates = self._select()
        if not candidates:
            raise RuntimeError("SmartDispatcher: 未注册任何引擎")
        last_error: Optional[Exception] = None
        for eng in candidates:
            if not eng.is_available():
                self._mark(eng.name, available=False)
                continue
            self._mark(eng.name, available=True)
            try:
                result = eng.chat(messages, **kwargs)
            except Exception as ex:  # 故障转移
                last_error = ex
                self._record(eng.name, success=False, error=str(ex))
                continue
            self._record(eng.name, success=True)
            return result
        raise RuntimeError(
            f"SmartDispatcher: 所有引擎调用失败或未可用，最后错误: {last_error}"
        )

    def dispatch_with_tools(self, messages: List[Dict], tools: List[Dict],
                            **kwargs) -> Dict[str, Any]:
        """
        引擎无关工具调用调度：逐候选调用 generate_with_tools，成功即返回，失败 fallback。

        Raises:
            RuntimeError: 所有引擎均不可用或调用失败。
        """
        candidates = self._select()
        if not candidates:
            raise RuntimeError("SmartDispatcher: 未注册任何引擎")
        last_error: Optional[Exception] = None
        for eng in candidates:
            if not eng.is_available():
                self._mark(eng.name, available=False)
                continue
            self._mark(eng.name, available=True)
            try:
                result = eng.generate_with_tools(messages, tools, **kwargs)
            except Exception as ex:  # 故障转移
                last_error = ex
                self._record(eng.name, success=False, error=str(ex))
                continue
            self._record(eng.name, success=True)
            return result
        raise RuntimeError(
            f"SmartDispatcher: 所有引擎工具调用失败或未可用，最后错误: {last_error}"
        )

    # ==================== 统计 ====================

    def _mark(self, name: str, available: bool) -> None:
        with self._lock:
            sc = self._scores.setdefault(name, EngineScore(name=name))
            sc.available = available

    def _record(self, name: str, success: bool, error: str = "") -> None:
        with self._lock:
            sc = self._scores.setdefault(name, EngineScore(name=name))
            if success:
                sc.success_count += 1
                sc.last_error = ""
            else:
                sc.fail_count += 1
                sc.last_error = error

    def get_stats(self) -> Dict[str, Any]:
        """返回各引擎调度统计（成功率 / 成败计数 / 最近错误 / 可用性标记）。"""
        with self._lock:
            return {
                name: {
                    "available": sc.available,
                    "success_count": sc.success_count,
                    "fail_count": sc.fail_count,
                    "success_rate": sc.success_rate,
                    "last_error": sc.last_error,
                }
                for name, sc in self._scores.items()
            }

    def cleanup(self) -> None:
        """释放所有底层引擎资源。"""
        for e in self._engines:
            try:
                e.cleanup()
            except Exception:
                # 清理失败不应阻断其余引擎
                pass


if __name__ == "__main__":
    # 简易自测（无网络，使用内存桩适配器）
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    class _Stub(BaseEngineAdapter):
        def __init__(self, name, ok=True):
            super().__init__(None)
            self.name = name
            self.ok = ok

        def chat(self, messages, **kwargs):
            if not self.ok:
                raise RuntimeError(f"{self.name} down")
            return f"ok:{self.name}"

        def generate_with_tools(self, messages, tools, **kwargs):
            if not self.ok:
                raise RuntimeError(f"{self.name} down")
            return {"content": f"ok:{self.name}", "tool_calls": []}

        def is_available(self):
            return self.ok

        def cleanup(self):
            pass

    d = SmartDispatcher(engines=[_Stub("a", ok=False), _Stub("b", ok=True)],
                        preferred_order=["a", "b"])
    print("dispatch_chat:", d.dispatch_chat([]))          # fallback 到 b
    print("dispatch_with_tools:", d.dispatch_with_tools([], []))
    print("stats:", d.get_stats())
