# -*- coding: utf-8 -*-
"""
LemonGaze C2 · 陪伴状态类 CompanionState（每窗口隔离）
======================================================
- 状态挂在窗口实例：每个标准模式窗口各自 new 一个 CompanionState，
  禁止模块级单例保存"当前陪伴态"。
- persist()/restore()：存内存字典（键=窗口 instance_id），不落全局单例；
  窗口重建时按自己的 instance_id 还原。
- transition(expr)：校验目标表情合法 → 发 expression_changed → 记录日志。
- 不进 standard_mode/core（冻结区零触碰）。
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

try:  # 兼容包内/脚本两种导入方式
    from .companion_eye_view import EyeExpression, DEFAULT_EYE_COLOR
except ImportError:  # pragma: no cover
    from standard_mode.ui.companion.companion_eye_view import (
        EyeExpression, DEFAULT_EYE_COLOR,
    )

logger = logging.getLogger("lemon_gaze.state")

_VALID_EXPRESSIONS = {e.value for e in EyeExpression}

# ── 内存快照注册表：键=窗口 instance_id（不是全局"当前陪伴态"单例）──
_STATE_STORE: Dict[int, dict] = {}


class _CompanionSignals(QObject):
    """信号承载基类（dataclass 与 QObject 混写的标准做法）。"""

    expression_changed = pyqtSignal(str)
    camera_changed = pyqtSignal(bool)
    mic_changed = pyqtSignal(bool)
    enabled_changed = pyqtSignal(bool)


@dataclass
class CompanionState(_CompanionSignals):
    """单个标准模式窗口的陪伴模式状态（多窗口基石）。"""

    enabled: bool = False            # ★ 用户定稿：默认关，点击标题栏眼睛/右下角小点才启动（camera/mic 仍默认关）
    current_expression: str = "focus"  # ★ 默认锐利半月态（对齐参考图标准照）
    eye_color: str = field(default=DEFAULT_EYE_COLOR)
    camera_on: bool = False          # ★ 隐私铁律：默认关，绝不伪造已授权
    mic_on: bool = False             # ★ 隐私铁律：默认关，绝不伪造已授权
    last_interaction_ts: float = field(default_factory=time.time)
    summon_played: bool = False

    def __post_init__(self):
        super().__init__()

    # ───────────────────────── 表情 ─────────────────────────
    def transition(self, expr: str) -> bool:
        """切换表情：校验合法 → 更新 → 发信号 → 记日志。返回是否成功。"""
        if expr not in _VALID_EXPRESSIONS:
            logger.warning("LemonGaze 非法表情被拒绝: %r", expr)
            return False
        if expr == self.current_expression:
            return False
        self.current_expression = expr
        self.last_interaction_ts = time.time()
        self.expression_changed.emit(expr)
        logger.info("LemonGaze 表情切换 → %s", expr)
        return True

    # ───────────────────────── 开关 ─────────────────────────
    def set_enabled(self, on: bool) -> None:
        if on != self.enabled:
            self.enabled = on
            if on:
                self.last_interaction_ts = time.time()
            self.enabled_changed.emit(on)

    # ───────────────────────── 隐私（C6 底座）─────────────────────────
    def set_camera(self, on: bool) -> None:
        """摄像头开关——只能由显式授权弹窗确认后调用，绝不静默置 True。"""
        if on != self.camera_on:
            self.camera_on = on
            self.camera_changed.emit(on)
            logger.info("LemonGaze 摄像头 → %s（仅本地处理，数据不出机）", on)

    def set_mic(self, on: bool) -> None:
        """麦克风开关——同上，显式授权才可开。"""
        if on != self.mic_on:
            self.mic_on = on
            self.mic_changed.emit(on)
            logger.info("LemonGaze 麦克风 → %s（仅本地处理，数据不出机）", on)

    # ───────────────────── 持久化（内存字典）─────────────────────────
    def snapshot(self) -> dict:
        return {
            "enabled": self.enabled,
            "current_expression": self.current_expression,
            "eye_color": self.eye_color,
            "camera_on": self.camera_on,
            "mic_on": self.mic_on,
            "last_interaction_ts": self.last_interaction_ts,
            "summon_played": self.summon_played,
        }

    def persist(self, instance_id: int) -> None:
        """按窗口 instance_id 存内存快照（不落盘、不全局单例）。"""
        _STATE_STORE[instance_id] = self.snapshot()

    def restore(self, instance_id: int) -> bool:
        """按窗口 instance_id 还原快照；不存在返回 False（保持默认值）。"""
        snap = _STATE_STORE.get(instance_id)
        if not snap:
            return False
        self.enabled = snap.get("enabled", False)
        self.current_expression = snap.get("current_expression", "idle")
        _legacy = snap.get("eye_color", DEFAULT_EYE_COLOR)
        # ★ 视觉改版迁移：旧默认红涂鸦色升级为霓虹橙（用户定稿风格）
        self.eye_color = (DEFAULT_EYE_COLOR if _legacy == "#ff3333" else _legacy)
        self.camera_on = snap.get("camera_on", False)
        self.mic_on = snap.get("mic_on", False)
        self.last_interaction_ts = snap.get("last_interaction_ts", time.time())
        self.summon_played = snap.get("summon_played", False)
        return True

    @staticmethod
    def drop(instance_id: int) -> None:
        """窗口关闭时释放其快照，防泄漏（STEP-S2 多窗口验收项）。"""
        _STATE_STORE.pop(instance_id, None)

    @staticmethod
    def store_size() -> int:
        return len(_STATE_STORE)

    # 最近表情历史（诊断用，环形最多 32 条）
    _history: List[str] = field(default_factory=list, repr=False,
                                compare=False)

    def record_history(self, entry: str) -> None:
        self._history.append(entry)
        if len(self._history) > 32:
            del self._history[:-32]

    def last_history(self, n: int = 1) -> Optional[str]:
        return self._history[-n] if self._history else None
