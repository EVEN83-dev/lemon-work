# -*- coding: utf-8 -*-
"""
LemonGaze C5 · 陪伴表情自动切换（L0 基础态：鼠标/输入/时间驱动）
================================================================
- 事件驱动：活动经事件过滤器只读观察（返回 False 永不拦截），不 30fps 轮询；
  仅一个 5s 低频 QTimer 做静默检查，CPU 占用可忽略；不读文件/不调网络。
- 状态机：
    输入/鼠标活动 → focus（睁大跟随）
    回车发命令    → alert（接任务）→(1.5s)→ thinking（半闭眼珠缓转）
    工具调用      → busy；完成 → happy；失败 → confused
    30s 静默      → idle（半闭微光）；5min 静默 → away（闭眼熄光）
    活动回归      → focus
- 节律调皮：每 3~5min 随机切 wise/silly 一次（仅 focus/idle 时，不打扰操作）。
- 时间感知：22:00~06:00 自动降 glow（夜间低活跃），经 eye.set_glow_scale。
- 表情统一走 CompanionState.transition（状态源唯一、带日志）。
"""
import random
import time
from datetime import datetime

from PyQt5.QtCore import QEvent, QObject, QTimer

# 静默阈值（s）
IDLE_AFTER = 30.0
AWAY_AFTER = 300.0
CHECK_INTERVAL_MS = 5000          # 唯一的周期定时器：静默检查
NIGHT_DIM_START, NIGHT_DIM_END = 22, 6
NIGHT_GLOW_SCALE = 0.45
COMMAND_THINKING_DELAY_MS = 1500  # alert → thinking
FOCUS_ACTIVITY_THROTTLE = 2.0     # 活动通知节流（s），避免信号风暴

_MOOD_BURST = ("wise", "silly")   # 节律调皮可切换的表情


class CompanionBrain(QObject):
    """每窗口一个的 L0 表情大脑（事件驱动，无 LLM）。"""

    def __init__(self, window, state, eye):
        super().__init__(window)
        self._state = state
        self._eye = eye
        self._base_expr = "focus"        # 调皮切换后要回的基础态
        self._last_activity = time.time()
        self._last_focus_emit = 0.0
        self._mood_until = 0.0           # 调皮表情恢复时间

        # ── 唯一低频定时器：静默/夜间/调皮恢复检查 ──
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check)
        self._check_timer.start(CHECK_INTERVAL_MS)

        # ── 只读事件过滤器：挂 MIMOWindow，看键盘/鼠标/输入焦点 ──
        window.installEventFilter(self)

        # ── 调皮调度（singleShot 链，非轮询）──
        self._schedule_mood()

    # ───────────────────── 事件（只读，不拦截）─────────────────────
    def eventFilter(self, obj, ev):
        et = ev.type()
        if et in (QEvent.KeyPress, QEvent.MouseButtonPress,
                  QEvent.MouseMove, QEvent.Wheel, QEvent.InputMethod):
            self.on_activity()
        elif et == QEvent.FocusIn:
            self.on_activity()
        return False  # ★ 只读：永远不消费事件

    # ───────────────────── 活动入口 ─────────────────────
    def on_activity(self) -> None:
        self._last_activity = time.time()
        if not self._state.enabled:
            return
        now = time.time()
        # 活动回归 → focus（节流防信号风暴；任务书：活动回归→focus）
        if now - self._last_focus_emit < FOCUS_ACTIVITY_THROTTLE:
            return
        self._last_focus_emit = now
        self._set_base("focus")

    def on_command_sent(self, *_args) -> None:
        """回车发命令 → alert（接任务）→ 延时 thinking。"""
        if not self._state.enabled:
            return
        self._last_activity = time.time()
        self._set_base("alert")
        QTimer.singleShot(
            COMMAND_THINKING_DELAY_MS, self._enter_thinking_if_busy)

    def _enter_thinking_if_busy(self) -> None:
        # 若期间没有新活动且还在 alert，则进入 thinking
        if self._state.enabled and self._state.current_expression == "alert":
            self._set_base("thinking")

    def on_tool_call(self, *_args) -> None:
        if self._state.enabled:
            self._set_base("busy")

    def on_done(self, *_args) -> None:
        if self._state.enabled:
            self._set_base("happy")

    def on_error(self, *_args) -> None:
        if self._state.enabled:
            self._set_base("confused")

    # ───────────────────── 周期检查（5s）─────────────────────
    def _check(self) -> None:
        now = time.time()
        # 夜间降 glow（时间感知 C5.4）
        hour = datetime.now().hour
        night = hour >= NIGHT_DIM_START or hour < NIGHT_DIM_END
        self._eye.set_glow_scale(NIGHT_GLOW_SCALE if night else 1.0)

        if not self._state.enabled:
            return
        # 调皮表情到期回基础态
        if self._mood_until and now >= self._mood_until:
            self._mood_until = 0.0
            self._apply_base()
            return
        silent = now - self._last_activity
        cur = self._state.current_expression
        if silent >= AWAY_AFTER and cur != "away":
            self._state.transition("away")
        elif IDLE_AFTER <= silent < AWAY_AFTER and cur not in ("idle", "away"):
            # 正在执行的 alert/thinking/busy 不被静默打断（agent 还在工作）
            if cur not in ("alert", "thinking", "busy"):
                self._state.transition("idle")

    # ───────────────────── 节律调皮 ─────────────────────
    def _schedule_mood(self) -> None:
        delay_ms = random.randint(180, 300) * 1000  # 3~5min
        QTimer.singleShot(delay_ms, self._mood_burst)

    def _mood_burst(self) -> None:
        try:
            if self._state.enabled and not self._mood_until:
                cur = self._state.current_expression
                if cur in ("focus", "idle"):
                    mood = random.choice(_MOOD_BURST)
                    self._state.transition(mood)
                    self._mood_until = time.time() + random.uniform(20, 40)
        finally:
            self._schedule_mood()  # 链式续排，常驻节律

    # ───────────────────── 内部 ─────────────────────
    def _set_base(self, expr: str) -> None:
        self._base_expr = expr
        self._mood_until = 0.0  # 真实事件覆盖调皮表情
        self._apply_base()

    def _apply_base(self) -> None:
        if self._state.enabled:
            self._state.transition(self._base_expr)

    def stop(self) -> None:
        try:
            self._check_timer.stop()
        except RuntimeError:
            pass  # 底层 C++ 对象已随窗口销毁，无需再停
