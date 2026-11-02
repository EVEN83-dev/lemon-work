# -*- coding: utf-8 -*-
"""
LemonGaze C1 · 陪伴眼睛视觉组件（霓虹发光风 + 12态表情状态机）
==============================================================
视觉基准（用户定稿）：
  - 霓虹发光橙眼：弯月眼形（上缘浅拱 / 下缘深弧 / 两角尖），
    实心渐变（上亮暖黄 → 主橙 → 深橙）+ 多层光晕（bloom）+ 亮白光斑瞳孔，
    黑底面板上呈现"贾维斯式"发光眼神。
  - ★ 弃用早期"红涂鸦排线+抖动描边"风格（用户反馈恐怖），不再使用。
  - 眼睛只出现在右边栏黑底 dock 面板中（companion_dock.py，300×220），
    绝不挤占标题栏；标题栏仅保留一个 20×20 简洁线条眼开关图标。

表情：EyeExpression 12态 × EyeShapeParams 参数化预设（几何不变），
切换 lerp 200~400ms；alert 一大一小 / silly 大圆 / wise 眯弯月。
L0 鼠标跟随（光斑限幅在眼内）；L1 预留 set_gaze() 覆盖。
默认色 #ff6900（霓虹橙）；set_eye_color() 可切，theme.py 零改动。
仅 PyQt5 原生绘制，零 QtWebEngine。
"""
import math
import random
import sys
from dataclasses import dataclass, replace
from enum import Enum

from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor, QCursor, QPainter, QPainterPath, QPen, QBrush, QRadialGradient,
    QLinearGradient,
)
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel

# ★ 视觉改版：默认霓虹橙（对齐参考发光眼图）；旧红仅作备选色
DEFAULT_EYE_COLOR = "#ff6900"
ALT_EYE_COLOR = "#ff3333"


class EyeExpression(Enum):
    """陪伴眼睛 12 态（覆盖表情语义 + 状态机需要的全部表情）。"""
    WISE = "wise"            # 睿智尖眯弯月
    SILLY = "silly"          # 装傻大圆眼
    ALERT = "alert"          # 接任务一大一小
    FOCUS = "focus"          # 专注（睁大跟随输入）
    LISTENING = "listening"  # 倾听（L2 语音预留）
    THINKING = "thinking"    # 思考（半闭眼珠缓转上）
    BUSY = "busy"            # 忙碌（眼珠左右快扫）
    HAPPY = "happy"          # 开心（笑眼弯弯）
    CONFUSED = "confused"    # 困惑
    IDLE = "idle"            # 待机（半闭微光）
    AWAY = "away"            # 离开（闭眼熄光）
    SUMMON = "summon"        # 召唤（闭合→睁开→快眨）


@dataclass(frozen=True)
class EyeShapeParams:
    """单态眼睛形状参数（视觉表）——驱动 paintEvent 的全部几何。"""
    openness: float = 1.0     # 睁开度 0(闭)~1(全睁)
    tilt: float = 0.0         # 眼角上扬 -1(垂)~1(扬)，作用于外眼角
    roundness: float = 0.9    # 0 锐利弯月 ~ 1 正圆
    pupil_scale: float = 0.35 # 光斑瞳孔半径 / 眼宽半径
    glow: float = 0.5         # 发光明暗 0~1（22:00~06:00 由 brain 自动调低）
    asymmetry: float = 0.0    # 左右眼差 0~1（alert 一大一小）
    blink_amp: float = 0.95   # 眨眼幅度（alert/busy 极少眨→幅度小）
    blink_every: float = 4.5  # 平均眨眼间隔 s（alert/busy 拉长）
    blink_dur: float = 0.18   # 单次眨眼时长 s（silly 慢眨→拉长）
    pupil_freeze: bool = False  # 光斑定住（alert 接任务瞬间）


# ── 12 态视觉预设表 ──────────────────────────────────────────────
EXPRESSION_PRESETS = {
    EyeExpression.WISE: EyeShapeParams(
        openness=0.42, tilt=0.85, roundness=0.22, pupil_scale=0.16,
        glow=0.55, asymmetry=0.0, blink_amp=0.95, blink_every=4.5,
        blink_dur=0.16,
    ),
    EyeExpression.SILLY: EyeShapeParams(
        openness=1.0, tilt=0.0, roundness=1.0, pupil_scale=0.58,
        glow=0.45, asymmetry=0.0, blink_amp=0.98, blink_every=4.0,
        blink_dur=0.45,  # 慢眨
    ),
    EyeExpression.ALERT: EyeShapeParams(
        openness=1.0, tilt=0.30, roundness=0.62, pupil_scale=0.28,
        glow=0.95, asymmetry=0.38, blink_amp=0.35, blink_every=9.0,
        blink_dur=0.14, pupil_freeze=True,  # 极少眨 + 光斑定住
    ),
    EyeExpression.FOCUS: EyeShapeParams(
        openness=0.88, tilt=0.35, roundness=0.55, pupil_scale=0.26,
        glow=0.80, asymmetry=0.0, blink_amp=0.85, blink_every=5.0,
    ),
    EyeExpression.LISTENING: EyeShapeParams(
        openness=0.92, tilt=0.15, roundness=0.85, pupil_scale=0.40,
        glow=0.70, asymmetry=0.0, blink_amp=0.9, blink_every=4.5,
    ),
    EyeExpression.THINKING: EyeShapeParams(
        openness=0.52, tilt=0.45, roundness=0.40, pupil_scale=0.20,
        glow=0.50, asymmetry=0.08, blink_amp=0.7, blink_every=6.0,
    ),
    EyeExpression.BUSY: EyeShapeParams(
        openness=0.80, tilt=0.20, roundness=0.60, pupil_scale=0.26,
        glow=0.85, asymmetry=0.0, blink_amp=0.30, blink_every=8.0,
    ),
    EyeExpression.HAPPY: EyeShapeParams(
        openness=0.55, tilt=-0.55, roundness=0.70, pupil_scale=0.22,
        glow=0.75, asymmetry=0.0, blink_amp=0.9, blink_every=4.0,
    ),
    EyeExpression.CONFUSED: EyeShapeParams(
        openness=0.72, tilt=0.05, roundness=0.85, pupil_scale=0.34,
        glow=0.55, asymmetry=0.22, blink_amp=0.9, blink_every=4.5,
    ),
    EyeExpression.IDLE: EyeShapeParams(
        openness=0.35, tilt=0.0, roundness=0.9, pupil_scale=0.28,
        glow=0.20, asymmetry=0.0, blink_amp=0.9, blink_every=6.0,
        blink_dur=0.30,
    ),
    EyeExpression.AWAY: EyeShapeParams(
        openness=0.04, tilt=0.0, roundness=1.0, pupil_scale=0.2,
        glow=0.0, asymmetry=0.0, blink_amp=0.0, blink_every=60.0,
        blink_dur=0.6,
    ),
    EyeExpression.SUMMON: EyeShapeParams(
        openness=1.0, tilt=0.25, roundness=0.7, pupil_scale=0.34,
        glow=0.95, asymmetry=0.0, blink_amp=0.95, blink_every=4.0,
    ),
}


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _smoothstep(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return p * p * (3.0 - 2.0 * p)


class CompanionEyeView(QWidget):
    """右边栏黑底面板中的霓虹发光陪伴眼睛。

    L0：鼠标跟随 + 呼吸 + 随机眨眼（纯本地绘制，零隐私）。
    L1 预留：set_gaze(dx,dy) 由摄像头覆盖视线；set_emotion() 由状态机驱动。
    """

    # 状态变化时发出（如 summon 完成后回 focus），供 companion_brain 消费
    state_changed = pyqtSignal(str)

    def __init__(self, parent=None, eye_size: int = 64):
        super().__init__(parent)
        self.eye_size = eye_size
        self.setMinimumSize(eye_size * 3, eye_size * 2 + 20)
        self.setMouseTracking(True)

        # 背景透明（发光眼叠在 dock 黑底面板上）
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)

        # ── 颜色 ──
        self._eye_color = DEFAULT_EYE_COLOR
        self._glow_scale = 1.0  # 夜间降亮系数（companion_brain 调低）

        # ── 表情状态机：当前形状 + 目标形状 + lerp 过渡 ──
        self._expr = EyeExpression.IDLE
        self._shape = replace(EXPRESSION_PRESETS[self._expr])
        self._shape_from = replace(self._shape)
        self._shape_to = replace(self._shape)
        self._anim_t0 = 0.0
        self._anim_dur = 0.30  # 200~400ms lerp 过渡

        # ── 动画状态 ──
        self._t = 0.0
        self._pupil = QPointF(0.0, 0.0)       # 当前光斑偏移 (-1..1)
        self._pupil_target = QPointF(0.0, 0.0)
        self._breath_phase = 0.0
        self._blink = 0.0                      # 0=睁 1=闭
        self._blink_phase = None
        self._blink_dur = 0.18
        self._next_blink = random.uniform(3.0, 6.0)

        # ── 切换瞬间微动画 ──
        self._pupil_frozen_until = -1.0        # alert: 光斑定住
        self._scan_until = -1.0                # busy: 眼珠左右快扫
        self._think_until = -1.0               # thinking: 眼珠缓转上
        self._summon_blink_at = -1.0           # summon: 睁开后快眨一次

        # ── L1/L2 覆盖（默认 None，由摄像头/状态机写入）──
        self._gaze_override = None
        self._emotion = "neutral"

        # ── 动画定时器（渲染专用 ~30fps；brain 层是事件驱动）──
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # ───────────────────────── 公共 API ─────────────────────────
    def set_expression(self, expr) -> None:
        """切换表情（str 或 EyeExpression），lerp 200~400ms 过渡 + 微动画。"""
        if isinstance(expr, str):
            try:
                expr = EyeExpression(expr)
            except ValueError:
                return
        if not isinstance(expr, EyeExpression) or expr == self._expr:
            return
        was_closed = self._shape.openness < 0.12
        self._expr = expr
        self._shape_from = replace(self._shape)
        self._shape_to = replace(EXPRESSION_PRESETS[expr])
        self._anim_t0 = self._t
        self._anim_dur = random.uniform(0.20, 0.40)

        now = self._t
        if expr is EyeExpression.ALERT:
            self._pupil_frozen_until = now + 1.2   # 接任务瞬间光斑定住
        elif expr is EyeExpression.BUSY:
            self._scan_until = now + 1.5           # 眼珠左右快扫
        elif expr is EyeExpression.THINKING:
            self._think_until = now + 2.0          # 眼珠缓转上
        elif expr is EyeExpression.SUMMON:
            if was_closed:
                self._summon_blink_at = now + self._anim_dur + 0.15
        self.state_changed.emit(expr.value)

    def current_expression(self) -> str:
        return self._expr.value

    def set_eye_color(self, color: str) -> None:
        """眼睛颜色注入（CompanionState.eye_color → 此处），不改 theme.py。"""
        if color and isinstance(color, str) and color != self._eye_color:
            self._eye_color = color

    def get_eye_color(self) -> str:
        return self._eye_color

    def set_glow_scale(self, scale: float) -> None:
        """光晕全局亮度系数（0~1），夜间模式由 brain 自动调低。"""
        self._glow_scale = max(0.0, min(1.0, float(scale)))

    # ───────── L1/L2 接口（当前 L0 不调用，保留）─────────────────
    def set_gaze(self, dx: float, dy: float):
        """L1 摄像头：写入归一化视线 (-1..1)，覆盖鼠标跟随。"""
        self._gaze_override = (dx, dy)

    def clear_gaze(self):
        """L1 关闭摄像头：回到 L0 鼠标跟随。"""
        self._gaze_override = None

    def set_emotion(self, emotion: str):
        """L2 状态机：neutral / smile / frown（预留）。"""
        self._emotion = emotion

    def stop(self):
        self._timer.stop()

    # ───────────────────────── 动画主循环 ─────────────────────────
    def _tick(self):
        self._t += 0.033

        # 形状 lerp 过渡
        p = _smoothstep((self._t - self._anim_t0) / max(1e-6, self._anim_dur))
        f, o = self._shape_from, self._shape_to
        self._shape = EyeShapeParams(
            openness=_lerp(f.openness, o.openness, p),
            tilt=_lerp(f.tilt, o.tilt, p),
            roundness=_lerp(f.roundness, o.roundness, p),
            pupil_scale=_lerp(f.pupil_scale, o.pupil_scale, p),
            glow=_lerp(f.glow, o.glow, p),
            asymmetry=_lerp(f.asymmetry, o.asymmetry, p),
            blink_amp=_lerp(f.blink_amp, o.blink_amp, p),
            blink_every=_lerp(f.blink_every, o.blink_every, p),
            blink_dur=_lerp(f.blink_dur, o.blink_dur, p),
            pupil_freeze=o.pupil_freeze if p > 0.5 else f.pupil_freeze,
        )
        # summon：睁开完成后快眨一次
        if self._summon_blink_at > 0 and self._t >= self._summon_blink_at:
            self._summon_blink_at = -1.0
            self._blink_phase = 0.0

        # 呼吸（away 极慢）
        breath_speed = 0.4 if self._expr is EyeExpression.AWAY else 1.2
        self._breath_phase = (math.sin(self._t * breath_speed) + 1.0) / 2.0

        # 眨眼状态机（间隔/时长/幅度均由 EyeShapeParams 控制）
        if self._blink_phase is None and self._shape.blink_amp > 0.05 \
                and self._t >= self._next_blink:
            self._blink_phase = 0.0
            self._blink_dur = max(0.08, self._shape.blink_dur)
        if self._blink_phase is not None:
            self._blink_phase += 0.033
            bp = self._blink_phase / max(1e-6, self._blink_dur)
            if bp >= 1.0:
                self._blink = 0.0
                self._blink_phase = None
                interval = self._shape.blink_every
                self._next_blink = self._t + random.uniform(
                    interval * 0.66, interval * 1.33)
            else:
                self._blink = math.sin(bp * math.pi) * self._shape.blink_amp

        self._update_pupil_target()
        self._pupil += (self._pupil_target - self._pupil) * 0.15
        self.update()

    def _update_pupil_target(self):
        now = self._t
        # 切换微动画优先
        if self._pupil_frozen_until > now or self._shape.pupil_freeze:
            return  # alert：光斑定住
        if self._scan_until > now:
            self._pupil_target = QPointF(math.sin(now * 10.0) * 0.8, 0.05)
            return
        if self._think_until > now:
            self._pupil_target = QPointF(
                0.25 * math.sin(now * 0.8), -0.6 + 0.08 * math.sin(now * 1.5))
            return

        if self._gaze_override is not None:
            dx, dy = self._gaze_override
            self._pupil_target = QPointF(
                max(-1.0, min(1.0, dx)), max(-1.0, min(1.0, dy * 0.7)))
            return
        # L0：跟随全局鼠标
        gp = QCursor.pos()
        lp = self.mapFromGlobal(gp)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        dx = (lp.x() - cx) / (self.width() / 2.0)
        dy = (lp.y() - cy) / (self.height() / 2.0)
        dx = max(-1.0, min(1.0, dx))
        dy = max(-1.0, min(1.0, dy * 0.7))
        # 鼠标在窗外：发呆微浮动
        inside = 0.0 <= lp.x() <= self.width() and 0.0 <= lp.y() <= self.height()
        if not inside:
            dx += 0.06 * math.sin(self._t * 0.7)
            dy += 0.04 * math.cos(self._t * 0.5)
        self._pupil_target = QPointF(dx, dy)

    # ───────────────────────── 镰刀形发光眼 ─────────────────────────
    def _eye_path(self, ex, ey, rx, ry, tilt, roundness, side) -> QPainterPath:
        """镰刀形发光眼（完全对齐参考图）：

        内角低而尖、外角高而尖；上缘自内角向外角近直斜线微拱，
        下缘深弧下垂形成镰刀弯。roundness > 0.72 退化为正圆
        （silly 大圆眼）；openness 经 ry 缩放（闭眼 = 弯月压扁）。
        """
        path = QPainterPath()
        r = max(0.0, min(1.0, roundness))
        if r > 0.72:
            path.addEllipse(QPointF(ex, ey), rx, ry)
            return path
        t = max(-1.0, min(1.0, tilt))
        # 内角（靠鼻侧）低而尖；外角高而尖（tilt 越大高差越大）
        inner = QPointF(ex - side * rx, ey + ry * (0.30 + 0.35 * t))
        outer = QPointF(ex + side * rx, ey - ry * (0.25 + 0.55 * t))
        # 上缘：内角 → 外角，近直线微上拱
        mid_top = QPointF((inner.x() + outer.x()) / 2.0,
                          (inner.y() + outer.y()) / 2.0 - ry * 0.10)
        path.moveTo(inner)
        path.quadTo(mid_top, outer)
        # 下缘：外角 → 内角，深弧镰刀（happy 负 tilt 时成笑弧）
        if t >= 0:
            depth = ry * (1.05 - 0.15 * t)
        else:
            depth = ry * (1.05 + 0.35 * (-t))
        c1 = QPointF(ex + side * rx * 0.45, ey + depth * 1.05)
        c2 = QPointF(ex - side * rx * 0.25, ey + depth * 0.72)
        path.cubicTo(c1, c2, inner)
        path.closeSubpath()
        return path

    # ───────────────────────── 绘制（霓虹发光风）─────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        eye_r = self.eye_size / 2.0
        gap = self.eye_size * 1.08
        cx = w / 2.0
        breath_y = math.sin(self._breath_phase * math.pi) * 2.0
        cy = h / 2.0 + breath_y - 4
        sh = self._shape
        open_factor = sh.openness * (1.0 - self._blink)
        col = QColor(self._eye_color)
        glow_val = max(0.0, min(1.0, sh.glow * self._glow_scale))
        # 同色系渐变两端：亮端（上）/ 深端（下）
        bright = QColor(min(255, col.red() + 75), min(255, col.green() + 55),
                        min(255, col.blue() + 90))
        deep = QColor(max(0, col.red() - 45), max(0, col.green() - 85),
                      max(0, col.blue() - 15))
        # ★ 无瞳孔设计：整眼朝视线方向轻微平移表达"看着你"（参考图无瞳孔）
        par_x = max(-1.0, min(1.0, self._pupil.x())) * eye_r * 0.10
        par_y = max(-1.0, min(1.0, self._pupil.y())) * eye_r * 0.14

        for side in (-1, 1):
            if open_factor <= 0.02 and glow_val <= 0.01:
                continue
            # asymmetry：右眼大且略高（alert 一大一小）
            if side > 0:
                rx = eye_r * 0.88 * (1.0 + sh.asymmetry * 0.45)
                ey_off = -sh.asymmetry * eye_r * 0.25
            else:
                rx = eye_r * 0.88 * (1.0 - sh.asymmetry * 0.30)
                ey_off = sh.asymmetry * eye_r * 0.10
            ey = cy + ey_off + par_y
            ry = max(0.6, rx * open_factor)
            ex_c = cx + side * gap / 2.0 + par_x

            path = self._eye_path(ex_c, ey, rx, ry, sh.tilt, sh.roundness, side)

            # ① 霓虹光晕（bloom）：多层宽描边，随 glow 由内向外衰减
            for layer in range(4):
                width = (15 - layer * 4.0) * (0.45 + 0.8 * glow_val)
                alpha = int(255 * max(0.0, 0.26 - layer * 0.06) * glow_val)
                if alpha <= 0 or width <= 0:
                    continue
                painter.setPen(QPen(
                    QColor(col.red(), col.green(), col.blue(), alpha), width))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)

            # ② 实心渐变填充（上亮暖橙 → 主色 → 下深橙红，发光体质感）
            grad = QLinearGradient(ex_c, ey - ry, ex_c, ey + ry)
            grad.setColorAt(0.0, bright)
            grad.setColorAt(0.5, col)
            grad.setColorAt(1.0, deep)
            painter.setPen(QPen(
                QColor(bright.red(), bright.green(), bright.blue(),
                       int(255 * max(0.4, glow_val))), 2.2))
            painter.setBrush(QBrush(grad))
            painter.drawPath(path)

        # ③ 霓虹鼻：竖向发光短条（光晕 + 渐变圆头）
        if open_factor > 0.08:
            ny0 = cy + eye_r * 0.86 + breath_y + par_y * 0.5
            nlen = max(4.0, eye_r * 0.26)
            glow_a = int(255 * 0.35 * max(0.2, glow_val))
            painter.setPen(QPen(QColor(col.red(), col.green(), col.blue(),
                                       glow_a), 11))
            painter.drawLine(QPointF(cx, ny0), QPointF(cx, ny0 + nlen))
            ngrad = QLinearGradient(cx, ny0, cx, ny0 + nlen)
            ngrad.setColorAt(0.0, bright)
            ngrad.setColorAt(1.0, QColor(col.red(), col.green(),
                                         col.blue(), 230))
            painter.setPen(QPen(QBrush(ngrad), 5.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(cx, ny0), QPointF(cx, ny0 + nlen))

        painter.end()

    # 兼容旧调用
    def rect_f(self) -> QRectF:
        return QRectF(0, 0, self.width(), self.height())


if __name__ == "__main__":  # pragma: no cover - 独立 demo
    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowTitle("LemonGaze · 霓虹发光眼（1=wise 2=silly 3=alert 0=idle A=away）")
    win.setStyleSheet("background:#050505;")
    layout = QVBoxLayout(win)
    eye = CompanionEyeView(eye_size=88)
    layout.addWidget(eye, alignment=Qt.AlignCenter)
    hint = QLabel("移动鼠标 → 光斑跟随；按键切换表情（H=happy T=thinking B=busy F=focus）")
    hint.setStyleSheet("color:#666; font-size:12px;")
    hint.setAlignment(Qt.AlignCenter)
    layout.addWidget(hint)

    def _key(ev):
        k = ev.text().lower()
        m = {"1": "wise", "2": "silly", "3": "alert", "0": "idle",
             "a": "away", "s": "summon", "i": "idle", "b": "busy",
             "t": "thinking", "h": "happy", "f": "focus", "c": "confused"}
        if k in m:
            eye.set_expression(m[k])
    win.keyPressEvent = _key

    win.resize(340, 240)
    eye.set_expression("wise")
    win.show()
    sys.exit(app.exec_())
