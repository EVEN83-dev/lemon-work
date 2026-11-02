# -*- coding: utf-8 -*-
"""
引擎模式管理器 — 尊重用户选择，不自动切换

核心原则：
1. 用户选择MIMO就用MIMO，失败报错不自动切换
2. 用户选择Ollama就用Ollama
3. 只有"自动"模式才允许回退
"""

from enum import Enum
from typing import Callable, List, Optional
import logging

logger = logging.getLogger(__name__)


class EngineMode(Enum):
    """引擎模式"""
    MIMO = "mimo"           # 强制MIMO，失败报错
    OLLAMA = "ollama"       # 强制Ollama
    DEEPSEEK = "deepseek"   # 强制DeepSeek API
    AUTO = "auto"           # 自动选择，允许回退


class EngineModeManager:
    """引擎模式管理器

    管理 MIMO / Ollama / DeepSeek / 自动 四种模式。
    - MIMO 模式：强制使用 mimocode 引擎，失败时直接报错
    - Ollama 模式：强制使用 ollama 引擎，失败时直接报错
    - DeepSeek 模式：强制使用 deepseek API 引擎，失败时直接报错
    - 自动模式：按优先级尝试可用引擎，允许回退
    """

    def __init__(self, engine_manager=None):
        self._engine_manager = engine_manager
        self._mode = EngineMode.AUTO
        self._callbacks: List[Callable[[EngineMode], None]] = []
        self._last_engine_used: Optional[str] = None
        self._last_error: Optional[str] = None

    @property
    def mode(self) -> EngineMode:
        return self._mode

    @property
    def mode_name(self) -> str:
        return self._mode.value

    @property
    def last_engine_used(self) -> Optional[str]:
        return self._last_engine_used

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def set_engine_manager(self, engine_manager):
        """设置 EngineManager 实例"""
        self._engine_manager = engine_manager

    def set_mode(self, mode: EngineMode):
        """设置引擎模式"""
        old = self._mode
        if isinstance(mode, str):
            mode = EngineMode(mode)
        self._mode = mode
        logger.info(f"引擎模式切换: {old.value} -> {mode.value}")
        for cb in self._callbacks:
            try:
                cb(mode)
            except Exception as e:
                logger.error(f"模式变化回调异常: {e}")

    def set_mode_by_name(self, mode_name: str):
        """通过名称设置模式（供UI调用）"""
        mode_map = {
            "mimo": EngineMode.MIMO,
            "ollama": EngineMode.OLLAMA,
            "deepseek": EngineMode.DEEPSEEK,
            "auto": EngineMode.AUTO,
        }
        if mode_name in mode_map:
            self.set_mode(mode_map[mode_name])

    def on_mode_changed(self, callback: Callable[[EngineMode], None]):
        """注册模式变化回调"""
        self._callbacks.append(callback)

    def get_target_engine(self) -> str:
        """获取当前模式应使用的引擎ID

        Returns:
            引擎ID: "mimocode" / "ollama" / "deepseek"

        ★ v4.8: auto 模式优先 Ollama/DeepSeek，MIMO 降级为兜底
        """
        if self._mode == EngineMode.MIMO:
            return "mimocode"
        elif self._mode == EngineMode.OLLAMA:
            return "ollama"
        elif self._mode == EngineMode.DEEPSEEK:
            return "deepseek"
        else:
            # 自动模式：优先 Ollama → DeepSeek → MIMO
            if self._engine_manager:
                status = self._engine_manager.get_status()
                for name in ["ollama", "deepseek", "mimocode"]:
                    eng = status.get(name)
                    if eng and eng.get("available"):
                        return name
            return "ollama"  # 默认回退

    def send(self, prompt: str, **kwargs):
        """发送消息 — 根据当前模式路由

        固定模式（MIMO/Ollama）：直接调用指定引擎，失败报错
        自动模式：按优先级尝试，允许回退
        """
        self._last_error = None

        if self._mode == EngineMode.AUTO:
            return self._send_auto(prompt, **kwargs)
        else:
            return self._send_fixed(prompt, **kwargs)

    def _send_fixed(self, prompt: str, **kwargs):
        """固定模式 — 不自动切换，失败直接报错"""
        engine_name = self._mode.value
        # MIMO 模式映射到 mimocode 引擎
        if engine_name == "mimo":
            engine_name = "mimocode"
        elif engine_name == "deepseek":
            engine_name = "deepseek"

        try:
            if self._engine_manager is None:
                raise RuntimeError("EngineManager 未初始化")

            result = self._engine_manager.chat(prompt, engine=engine_name, **kwargs)
            self._last_engine_used = engine_name
            logger.info(f"[{self._mode.value}] 引擎 {engine_name} 调用成功")
            return result
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"[{self._mode.value}] 引擎 {engine_name} 不可用: {e}")
            raise RuntimeError(f"{self._mode.value.upper()} 引擎不可用: {e}")

    def _send_auto(self, prompt: str, **kwargs):
        """自动模式 — 允许回退

        ★ v4.8: 优先 Ollama → DeepSeek → MIMO（MIMO 降级为兜底）
        """
        if self._engine_manager is None:
            raise RuntimeError("EngineManager 未初始化")

        # ★ v4.8: Ollama/DeepSeek 优先，MIMO 兜底
        engine_order = ["ollama", "deepseek", "mimocode"]
        last_error = None

        for name in engine_order:
            try:
                result = self._engine_manager.chat(prompt, engine=name, **kwargs)
                self._last_engine_used = name
                logger.info(f"[auto] 引擎 {name} 调用成功")
                return result
            except Exception as e:
                last_error = e
                logger.warning(f"[auto] 引擎 {name} 失败，尝试下一个: {e}")
                continue

        self._last_error = str(last_error) if last_error else "所有引擎不可用"
        raise RuntimeError(f"所有引擎都不可用 (最后错误: {self._last_error})")

    def get_status(self) -> dict:
        """获取当前状态信息"""
        return {
            "mode": self._mode.value,
            "target_engine": self.get_target_engine(),
            "last_engine_used": self._last_engine_used,
            "last_error": self._last_error,
            "engine_manager_available": self._engine_manager is not None,
        }
