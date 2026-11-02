# -*- coding: utf-8 -*-
"""
Agent 状态三色灯 — 大方块，高饱和荧光红黄绿
- 红 / 黄 / 绿 三块大方块（带小圆角）
- OFF 态：极暗但保留色相的底版
- 工作时动画（多种模式可选）：
    1. "flow"    流水呼吸 — 三块从左到右依次"暗→荧光亮→暗"，像二进制一格一格推进
    2. "pulse"   同步脉冲 — 三块同时呼吸（整体一起亮暗）
    3. "blink"   二进制闪烁 — 三块依次硬切亮/灭，像二进制
- 待命：黄块常亮（荧光黄）
- 需确认：红块常亮（荧光红）
- 灯大小、配色、动画速度、动画模式均可自定义
"""

import os
import sys
import math
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, QTimer

sys.path.insert(0, os.path.dirname(__file__))

# LED 灯使用独立荧光色，不依赖 tokens.py（荧光色更饱和、更醒目）
COLOR_GREEN = "#00ff66"
COLOR_YELLOW = "#ffed00"
COLOR_RED = "#ff3333"

COLOR_GREEN_OFF = "#1a4d26"
COLOR_YELLOW_OFF = "#5c4d00"
COLOR_RED_OFF = "#5c1a1a"

# 动画模式常量
MODE_FLOW = "flow"          # 流水呼吸（默认，像二进制一格一格推进）
MODE_PULSE = "pulse"        # 同步脉冲（三块一起呼吸）
MODE_BLINK = "blink"        # 二进制闪烁（硬切亮/灭）

# 状态描述（i18n key）
STATE_TOOLTIP_KEYS = {
    "working": "agent_status.working",
    "thinking": "agent_status.thinking",
    "executing": "agent_status.executing",
    "idle": "agent_status.idle",
    "ready": "agent_status.ready",
    "connected": "agent_status.connected",
    "standby": "agent_status.standby",
    "confirm": "agent_status.confirm",
    "permission": "agent_status.permission",
    "waiting": "agent_status.waiting",
    "error": "agent_status.error",
    "failed": "agent_status.failed",
}


def _hex_to_rgba(hex_color, alpha):
    """#rrggbb -> rgba(r,g,b,a)"""
    try:
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    except Exception:
        return hex_color


class StatusBlock(QLabel):
    """单个状态块 — 大方块带小圆角，呼吸闪烁"""

    def __init__(self, size=22, parent=None):
        super().__init__(parent)
        self._color = COLOR_GREEN_OFF
        self._active = False
        self._alpha = 255
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        # 确保 QLabel 确实用 QSS 绘制背景，而不是保持透明
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(self._style())

    def _style(self):
        s = self._size
        r = max(2, int(s * 0.18))   # 小圆角方块
        color = self._color
        alpha = self._alpha
        if alpha < 255:
            color = _hex_to_rgba(color, alpha)
        if self._active:
            # 激活态：纯色方块 + 白色高亮边框（荧光感）
            glow = _hex_to_rgba("#ffffff", max(160, alpha // 2))
            return (
                "background-color: " + color + ";"
                "border: 2px solid " + glow + ";"
                "border-radius: " + str(r) + "px;"
                "min-width: " + str(s) + "px; max-width: " + str(s) + "px;"
                "min-height: " + str(s) + "px; max-height: " + str(s) + "px;"
            )
        # OFF 态：暗色方块 + 细暗边框（保留色相）
        return (
            "background-color: " + color + ";"
            "border: 1px solid " + _hex_to_rgba("#0D0D0D", max(30, alpha // 10)) + ";"
            "border-radius: " + str(r) + "px;"
            "min-width: " + str(s) + "px; max-width: " + str(s) + "px;"
            "min-height: " + str(s) + "px; max-height: " + str(s) + "px;"
        )

    def set_color(self, color, alpha=255, active=False):
        self._color = color
        self._alpha = alpha
        self._active = active
        self.setStyleSheet(self._style())

    def set_size(self, size):
        self._size = size
        self.setFixedSize(size, size)
        self.setStyleSheet(self._style())


class AgentStatusLight(QWidget):
    """Agent 状态三色灯 — 大方块，动画模式与速度可调"""

    # 动画参数
    _BREATH_STEPS_PER_BLOCK = 12        # 单块一次呼吸的帧数
    _BLINK_FRAMES = 6                   # 二进制闪烁：每块亮/灭各 6 帧
    _ALPHA_MIN = 80                     # 最暗透明度（确保始终可见）
    _ALPHA_MAX = 255                    # 最亮透明度（荧光）

    # 速度等级（每帧间隔 ms）：越快数值越小
    SPEED_SLOW = 90
    SPEED_NORMAL = 60
    SPEED_FAST = 35

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_state = "idle"
        self._dot_size = 22              # 大方块，与标题栏匹配
        self._mode = MODE_FLOW           # 默认流水呼吸
        self._speed = self.SPEED_NORMAL  # 默认中速
        self._colors = {
            "green": COLOR_GREEN,
            "yellow": COLOR_YELLOW,
            "red": COLOR_RED,
            "green_off": COLOR_GREEN_OFF,
            "yellow_off": COLOR_YELLOW_OFF,
            "red_off": COLOR_RED_OFF,
        }

        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(self._speed)
        self._breath_timer.timeout.connect(self._on_breath_tick)
        self._breath_frame = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 8, 0)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        # 顺序：红 / 黄 / 绿（从左到右）
        self._red = StatusBlock(self._dot_size)
        self._yellow = StatusBlock(self._dot_size)
        self._green = StatusBlock(self._dot_size)
        layout.addWidget(self._red)
        layout.addWidget(self._yellow)
        layout.addWidget(self._green)

        self.set_state("idle")

    # ------------------------------------------------------------------
    # 自定义 API
    # ------------------------------------------------------------------
    def set_dot_size(self, size: int):
        self._dot_size = max(10, int(size))
        for dot in (self._red, self._yellow, self._green):
            dot.set_size(self._dot_size)

    def set_colors(self, green=None, yellow=None, red=None):
        if green:
            self._colors["green"] = green
            self._colors["green_off"] = self._make_off_color(green)
        if yellow:
            self._colors["yellow"] = yellow
            self._colors["yellow_off"] = self._make_off_color(yellow)
        if red:
            self._colors["red"] = red
            self._colors["red_off"] = self._make_off_color(red)
        self.set_state(self._current_state, keep_animation=True)

    def _make_off_color(self, hex_color):
        try:
            hex_color = hex_color.lstrip('#')
            r = int(hex_color[0:2], 16) // 4
            g = int(hex_color[2:4], 16) // 4
            b = int(hex_color[4:6], 16) // 4
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def set_breath_speed(self, interval_ms: int):
        """设置动画速度。interval_ms：每帧间隔毫秒，越小越快。
        推荐使用 SPEED_SLOW / SPEED_NORMAL / SPEED_FAST。"""
        self._speed = max(10, int(interval_ms))
        self._breath_timer.setInterval(self._speed)

    def set_animation_mode(self, mode: str):
        """设置工作动画模式：MODE_FLOW / MODE_PULSE / MODE_BLINK"""
        if mode not in (MODE_FLOW, MODE_PULSE, MODE_BLINK):
            mode = MODE_FLOW
        self._mode = mode
        # 若正在工作动画，立即按新模式重启动画
        if self._current_state in ("working", "thinking", "executing"):
            self._start_breath()

    def get_animation_mode(self) -> str:
        return self._mode

    # ------------------------------------------------------------------
    # 状态设置
    # ------------------------------------------------------------------
    def set_state(self, state: str, keep_animation=False):
        self._current_state = state

        if not keep_animation:
            self._stop_breath()

        # 默认三个块 OFF 态（暗版，保留色相）
        self._red.set_color(self._colors["red_off"], alpha=255, active=False)
        self._yellow.set_color(self._colors["yellow_off"], alpha=255, active=False)
        self._green.set_color(self._colors["green_off"], alpha=255, active=False)

        if state in ("working", "thinking", "executing"):
            # 工作时：按当前动画模式启动
            self._start_breath()
        elif state in ("idle", "ready", "connected", "standby"):
            # 待命：黄块常亮（荧光黄）
            self._yellow.set_color(self._colors["yellow"], alpha=255, active=True)
        elif state in ("confirm", "permission", "waiting", "error", "failed"):
            # 需确认：红块常亮（荧光红）
            self._red.set_color(self._colors["red"], alpha=255, active=True)
        else:
            self._yellow.set_color(self._colors["yellow"], alpha=255, active=True)

        from core.i18n import _t
        tooltip = _t(STATE_TOOLTIP_KEYS.get(state, "agent_status.unknown"))
        self.setToolTip(tooltip)

    def get_state(self) -> str:
        return self._current_state

    # ------------------------------------------------------------------
    # 动画控制
    # ------------------------------------------------------------------
    def _start_breath(self):
        self._breath_frame = 0
        if not self._breath_timer.isActive():
            self._breath_timer.start()

    def _stop_breath(self):
        if self._breath_timer.isActive():
            self._breath_timer.stop()
        if self._current_state in ("working", "thinking", "executing"):
            # 停止时三块回 OFF 暗版
            self._red.set_color(self._colors["red_off"], alpha=255, active=False)
            self._yellow.set_color(self._colors["yellow_off"], alpha=255, active=False)
            self._green.set_color(self._colors["green_off"], alpha=255, active=False)

    def _ease_in_out(self, t):
        """0->1 缓入缓出（cosine ease）"""
        return 0.5 * (1.0 - math.cos(t * math.pi))

    def _on_breath_tick(self):
        if self._mode == MODE_PULSE:
            self._tick_pulse()
        elif self._mode == MODE_BLINK:
            self._tick_blink()
        else:
            self._tick_flow()
        self._breath_frame += 1

    # ------------------------------------------------------------------
    # 动画模式 1：流水呼吸（flow）
    # 三块从左到右依次"暗→荧光亮→暗"，像二进制一格一格推进
    # ------------------------------------------------------------------
    def _tick_flow(self):
        steps = self._BREATH_STEPS_PER_BLOCK
        cycle = steps * 3
        f = self._breath_frame % cycle

        blocks = [self._red, self._yellow, self._green]
        colors = [self._colors["red"], self._colors["yellow"], self._colors["green"]]
        offs = [self._colors["red_off"], self._colors["yellow_off"], self._colors["green_off"]]

        for i, (block, color, off) in enumerate(zip(blocks, colors, offs)):
            block_frame = f - i * steps
            if 0 <= block_frame < steps:
                half = steps / 2.0
                if block_frame < half:
                    # 前半段：暗 → 最亮（吸气）
                    t = block_frame / half
                    alpha = int(self._ALPHA_MIN + (self._ALPHA_MAX - self._ALPHA_MIN) * self._ease_in_out(t))
                else:
                    # 后半段：最亮 → 暗（呼气）
                    t = (block_frame - half) / half
                    alpha = int(self._ALPHA_MAX - (self._ALPHA_MAX - self._ALPHA_MIN) * self._ease_in_out(t))
                # 呼吸全程都用荧光色，只改变透明度；active=True 才会带高亮边框
                block.set_color(color, alpha=alpha, active=True)
            else:
                # 其他块：OFF 暗版（不透明，否则会和父背景混色）
                block.set_color(off, alpha=255, active=False)

    # ------------------------------------------------------------------
    # 动画模式 2：同步脉冲（pulse）
    # 三块同时"暗→亮→暗"，像一颗心跳
    # ------------------------------------------------------------------
    def _tick_pulse(self):
        steps = self._BREATH_STEPS_PER_BLOCK
        f = self._breath_frame % steps
        half = steps / 2.0
        if f < half:
            t = f / half
            alpha = int(self._ALPHA_MIN + (self._ALPHA_MAX - self._ALPHA_MIN) * self._ease_in_out(t))
        else:
            t = (f - half) / half
            alpha = int(self._ALPHA_MAX - (self._ALPHA_MAX - self._ALPHA_MIN) * self._ease_in_out(t))

        blocks = [self._red, self._yellow, self._green]
        colors = [self._colors["red"], self._colors["yellow"], self._colors["green"]]
        for block, color in zip(blocks, colors):
            block.set_color(color, alpha=alpha, active=True)

    # ------------------------------------------------------------------
    # 动画模式 3：二进制闪烁（blink）
    # 三块依次硬切"亮→灭"，无渐变，像二进制推进
    # ------------------------------------------------------------------
    def _tick_blink(self):
        frames = self._BLINK_FRAMES
        cycle = frames * 3
        f = self._breath_frame % cycle

        blocks = [self._red, self._yellow, self._green]
        colors = [self._colors["red"], self._colors["yellow"], self._colors["green"]]
        offs = [self._colors["red_off"], self._colors["yellow_off"], self._colors["green_off"]]

        for i, (block, color, off) in enumerate(zip(blocks, colors, offs)):
            block_frame = f - i * frames
            if 0 <= block_frame < frames:
                # 本块处于"点亮"窗口内：硬切到全亮（前一半亮、后一半灭形成闪烁）
                if block_frame < frames // 2:
                    block.set_color(color, alpha=255, active=True)
                else:
                    block.set_color(off, alpha=255, active=False)
            else:
                block.set_color(off, alpha=255, active=False)

    def stop(self):
        self._stop_breath()
