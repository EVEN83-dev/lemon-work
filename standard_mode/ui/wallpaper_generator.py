# -*- coding: utf-8 -*-
"""
Lemon Code 「专注时刻」原创壁纸生成器 (v7.0)
=========================================
主题：专注时刻（Focus Moment）

场景构图：暗房角落的深木书桌上的复古打字机
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

房间关着灯，近乎全黑。唯一光源是书桌上一盏台灯，
若隐若现的暖黄光晕照在斜放的打字机上。
光线只照亮桌面中央区域，墙壁、地板、桌沿以外完全没入黑暗。

视觉层次（从远到近）：
1. 暗房 — 深色墙壁隐约可见（只有被台灯微弱照亮的部分）
2. 深木书桌 — 角落位置，只看到桌面被照亮的部分
3. 台灯 — 右侧偏后，灯罩+支架+底座，黄晕光源
4. 打字机 — 斜放约25°，在光锥中，完整机械结构
5. 纸张 — 从滚筒顶部绕出，被光照亮

打字机机械结构（斜放视角，从上到下）：
1. 纸张 — 从滚筒顶部绕过向前垂出
2. 滚筒/Platen — 圆柱橡胶辊，两端大旋钮
3. 色带盖板 — 滚筒前方的弧形金属盖板+色带窗口
4. 纸张压条 — 压住纸张的细横条
5. 换行扳手 — 右侧金属扳手
6. 按键区 — QWERTY弧形排列+错行偏移
7. 空格键+修饰键
8. 机身底座

★ v7.0 vs v6.0
- 恢复完整房间场景：暗房+墙壁+深木书桌（v6是纯黑虚空）
- 恢复台灯本体：灯罩+支架+底座，但调为"若隐若现"的黄晕
- 打字机缩小约30%，是桌上的物件而非占满画面
- 打字机斜放约25°（applyRotation），更真实自然
- 光照模型：台灯光锥照亮桌面→打字机被光照亮→边缘衰减入暗
- 墙壁隐约可见（被台灯间接照亮的一小片区域）
"""

import math
import random
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import (
    QPainter, QPainterPath, QPen, QBrush, QColor, QFont,
    QImage, QLinearGradient, QRadialGradient, QPolygonF,
    QTransform,
)
from PyQt5.QtWidgets import QApplication
from ui.design.tokens import Lemon


BG_VOID = QColor(Lemon.DARK_BG_1)
WALL_COLOR = QColor(Lemon.DARK_BG_1)
WALL_LIT = QColor(Lemon.DARK_BG_3)
DESK_DARK = QColor(Lemon.DARK_BG_1)
DESK_LIT = QColor(Lemon.DARK_BG_3)
DESK_GRAIN = QColor("#2a1c0e")
DESK_GRAIN_DARK = QColor("#100a04")

METAL_BODY = QColor("#2a1f15")
METAL_HIGHLIGHT = QColor("#7a5d3f")
METAL_EDGE = QColor("#b89060")
METAL_EDGE_BRIGHT = QColor("#d4a943")
BRASS_RING = QColor("#b8860b")
BRASS_LIGHT = QColor("#d4a943")
KEY_BLACK = QColor("#0a0606")

PAPER = QColor("#f5e6c8")
PAPER_LIGHT = QColor("#faf0d8")
PAPER_DARK = QColor("#c8b690")
INK_BROWN = QColor("#3d2814")
INK_FAINT = QColor("#8a6a4a")


def _rounded_rect_path(x, y, w, h, r):
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


class WallpaperGenerator:

    QWERTY_ROWS = [
        list("QWERTYUIOP"),
        list("ASDFGHJKL"),
        list("ZXCVBNM"),
    ]

    def __init__(self, width=1920, height=1080, scale=0.6):
        self._w = width
        self._h = height
        self._scale = max(0.3, min(3.0, scale))
        self._img = QImage(width, height, QImage.Format_ARGB32)

        self._desk_cx = width * 0.48
        self._desk_cy = height * 0.58
        self._desk_w = width * 0.72
        self._desk_h = height * 0.42

        self._tw_cx = width * 0.44
        self._tw_cy = height * 0.52
        self._tw_s = height * 0.20 * self._scale
        self._tw_angle = 22.0

        self._lamp_x = width * 0.62
        self._lamp_y = height * 0.28

    def set_scale(self, scale: float):
        self._scale = max(0.3, min(3.0, scale))
        self._tw_s = self._h * 0.20 * self._scale

    def get_scale(self) -> float:
        return self._scale

    def generate(self) -> QImage:
        self._img.fill(BG_VOID)
        p = QPainter(self._img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        self._draw_dark_room(p)
        self._draw_wall_lit_patch(p)
        self._draw_desk(p)
        self._draw_desk_items_hint(p)
        self._draw_lamp_light_cone(p)
        self._draw_desktop_spotlight(p)
        self._draw_shadow_under_typewriter(p)
        self._draw_dust_particles(p)

        p.save()
        p.translate(self._tw_cx, self._tw_cy)
        p.rotate(self._tw_angle)
        p.translate(-self._tw_cx, -self._tw_cy)

        self._draw_paper_with_text(p)
        self._draw_typewriter(p)

        p.restore()

        self._draw_lamp(p)

        p.end()
        return self._img

    def _draw_dark_room(self, p: QPainter):
        grad = QLinearGradient(0, 0, 0, self._h)
        grad.setColorAt(0, QColor(10, 8, 6))
        grad.setColorAt(0.3, QColor(6, 5, 4))
        grad.setColorAt(0.6, QColor(4, 3, 3))
        grad.setColorAt(1, QColor(2, 2, 2))
        p.fillRect(self._img.rect(), QBrush(grad))

        floor_y = self._h * 0.78
        floor_grad = QLinearGradient(0, floor_y, 0, self._h)
        floor_grad.setColorAt(0, QColor(8, 6, 4))
        floor_grad.setColorAt(1, QColor(3, 2, 2))
        p.fillRect(0, int(floor_y), self._w, int(self._h - floor_y), QBrush(floor_grad))

    def _draw_wall_lit_patch(self, p: QPainter):
        cx = self._lamp_x
        cy = self._h * 0.15
        r = self._w * 0.18
        grad = QRadialGradient(QPointF(cx, cy), r)
        grad.setColorAt(0, QColor(25, 20, 12, 35))
        grad.setColorAt(0.3, QColor(18, 14, 8, 20))
        grad.setColorAt(0.7, QColor(10, 8, 5, 8))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), int(r), int(r * 0.7))

    def _draw_desk(self, p: QPainter):
        dx = self._desk_cx - self._desk_w / 2
        dy = self._desk_cy - self._desk_h * 0.3
        dw = self._desk_w
        dh = self._desk_h

        desk_path = QPainterPath()
        desk_path.addRoundedRect(QRectF(dx, dy, dw, dh), 4, 4)
        grad = QLinearGradient(dx, dy, dx, dy + dh)
        grad.setColorAt(0, QColor(22, 16, 8, 180))
        grad.setColorAt(0.15, QColor(16, 11, 5, 200))
        grad.setColorAt(0.5, QColor(10, 7, 3, 160))
        grad.setColorAt(1, QColor(6, 4, 2, 120))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawPath(desk_path)

        random.seed(17)
        for i in range(25):
            gx = dx + random.uniform(0, dw)
            gy = dy + random.uniform(0, dh * 0.4)
            gw = random.uniform(dw * 0.1, dw * 0.4)
            alpha = random.randint(4, 14)
            p.setPen(QPen(QColor(40, 28, 14, alpha), random.uniform(0.3, 0.8)))
            p.drawLine(int(gx), int(gy), int(gx + gw), int(gy))

        edge_y = dy
        p.setPen(QPen(QColor(80, 55, 28, 25), 1.5))
        p.drawLine(int(dx), int(edge_y), int(dx + dw), int(edge_y))

        front_edge_y = dy + dh
        p.setPen(QPen(QColor(5, 3, 2, 80), 3))
        p.drawLine(int(dx + 5), int(front_edge_y), int(dx + dw - 5), int(front_edge_y))

    def _draw_desk_items_hint(self, p: QPainter):
        random.seed(33)

        ink_x = self._desk_cx + self._desk_w * 0.22
        ink_y = self._desk_cy + self._desk_h * 0.15
        ink_grad = QRadialGradient(QPointF(ink_x, ink_y), 12)
        ink_grad.setColorAt(0, QColor(20, 15, 8, 50))
        ink_grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(ink_grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(ink_x, ink_y), 10, 10)
        p.setBrush(QBrush(QColor(15, 10, 5, 40)))
        p.drawRoundedRect(QRectF(ink_x - 6, ink_y - 4, 12, 8), 3, 3)

        cup_x = self._desk_cx - self._desk_w * 0.25
        cup_y = self._desk_cy + self._desk_h * 0.10
        cup_grad = QRadialGradient(QPointF(cup_x, cup_y), 14)
        cup_grad.setColorAt(0, QColor(25, 18, 10, 35))
        cup_grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(cup_grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cup_x, cup_y), 12, 10)

    def _draw_lamp_light_cone(self, p: QPainter):
        lx = self._lamp_x
        ly = self._lamp_y + self._h * 0.12

        cone = QPainterPath()
        cone.moveTo(lx - 20, ly)
        cone.lineTo(self._tw_cx - self._tw_s * 1.2, self._tw_cy + self._tw_s * 0.5)
        cone.lineTo(self._tw_cx + self._tw_s * 1.0, self._tw_cy + self._tw_s * 0.3)
        cone.lineTo(lx + 20, ly)
        cone.closeSubpath()

        grad = QLinearGradient(0, ly, 0, self._tw_cy + self._tw_s * 0.4)
        grad.setColorAt(0, QColor(255, 215, 140, 16))
        grad.setColorAt(0.2, QColor(255, 200, 120, 10))
        grad.setColorAt(0.6, QColor(255, 180, 100, 5))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillPath(cone, QBrush(grad))

    def _draw_desktop_spotlight(self, p: QPainter):
        cx = self._tw_cx
        cy = self._tw_cy + self._tw_s * 0.15
        rx = self._tw_s * 1.8
        ry = self._tw_s * 0.8

        grad = QRadialGradient(QPointF(cx, cy), max(rx, ry))
        grad.setColorAt(0, QColor(255, 200, 120, 28))
        grad.setColorAt(0.2, QColor(255, 185, 105, 16))
        grad.setColorAt(0.5, QColor(255, 160, 85, 7))
        grad.setColorAt(0.8, QColor(200, 130, 60, 2))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), int(rx), int(ry))

    def _draw_shadow_under_typewriter(self, p: QPainter):
        cx = self._tw_cx
        cy = self._tw_cy + self._tw_s * 0.25
        rx = self._tw_s * 0.9
        ry = self._tw_s * 0.08

        grad = QRadialGradient(QPointF(cx, cy), max(rx, ry))
        grad.setColorAt(0, QColor(0, 0, 0, 120))
        grad.setColorAt(0.5, QColor(0, 0, 0, 50))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), int(rx), int(ry))

    def _draw_dust_particles(self, p: QPainter):
        random.seed(55)
        lx = self._lamp_x
        ly = self._lamp_y + self._h * 0.06
        for _ in range(18):
            t = random.uniform(0.1, 0.9)
            x = lx + (self._tw_cx - lx) * t + random.uniform(-30, 30)
            y = ly + (self._tw_cy - ly) * t + random.uniform(-20, 20)
            r = random.uniform(0.3, 0.8)
            alpha = random.randint(6, 22)
            dist = abs(t - 0.5) * 2
            alpha = int(alpha * (1 - dist * 0.6))
            if alpha > 2:
                p.setBrush(QBrush(QColor(255, 220, 160, max(2, alpha))))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(x, y), r, r)

    def _draw_paper_with_text(self, p: QPainter):
        cx = self._tw_cx
        cy = self._tw_cy
        s = self._tw_s

        roller_top = cy - s * 0.38
        roller_front = cy - s * 0.30

        paper = QPainterPath()
        paper.moveTo(cx - s * 0.38, roller_front)
        paper.cubicTo(
            cx - s * 0.40, roller_top + s * 0.02,
            cx - s * 0.44, roller_top,
            cx - s * 0.46, roller_top - s * 0.02,
        )
        paper.lineTo(cx - s * 0.52, cy - s * 0.72)
        paper.lineTo(cx + s * 0.36, cy - s * 0.68)
        paper.lineTo(cx + s * 0.46, roller_top - s * 0.02)
        paper.cubicTo(
            cx + s * 0.44, roller_top,
            cx + s * 0.40, roller_top + s * 0.02,
            cx + s * 0.38, roller_front,
        )
        paper.closeSubpath()

        grad = QLinearGradient(cx - s * 0.5, cy - s * 0.72, cx + s * 0.4, roller_front)
        grad.setColorAt(0, QColor(245, 230, 200, 170))
        grad.setColorAt(0.3, QColor(245, 230, 200, 200))
        grad.setColorAt(0.7, PAPER)
        grad.setColorAt(1, PAPER_DARK)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(100, 75, 40, 60), 0.8))
        p.drawPath(paper)

        text_cx = cx - s * 0.04
        text_top = cy - s * 0.66

        fs_title = max(4, int(s * 0.058))
        p.setFont(QFont("Georgia", fs_title, QFont.Bold))
        p.setPen(QPen(QColor(55, 38, 20, 150), 0.8))
        p.drawText(
            QRectF(text_cx - s * 0.30, text_top, s * 0.60, s * 0.08),
            Qt.AlignCenter, "Lemon Code",
        )

        fs_sub = max(3, int(s * 0.034))
        p.setFont(QFont("Georgia", fs_sub, QFont.StyleItalic))
        p.setPen(QPen(QColor(90, 65, 40, 120), 0.6))
        p.drawText(
            QRectF(text_cx - s * 0.25, text_top + s * 0.07, s * 0.50, s * 0.04),
            Qt.AlignCenter, "Focus Moment",
        )

        lines = [
            "> Build . Think . Ship",
            "> AI Agent Platform",
        ]
        fs_code = max(3, int(s * 0.024))
        p.setFont(QFont("Consolas", fs_code))
        for i, line in enumerate(lines):
            y_off = text_top + s * 0.13 + i * s * 0.035
            alpha = 110 - i * 25
            p.setPen(QPen(QColor(90, 65, 40, max(30, alpha)), 0.6))
            p.drawText(
                QRectF(text_cx - s * 0.28, y_off, s * 0.56, s * 0.035),
                Qt.AlignCenter, line,
            )

        hl = QPainterPath()
        hl.moveTo(cx + s * 0.08, cy - s * 0.66)
        hl.lineTo(cx + s * 0.34, cy - s * 0.65)
        hl.lineTo(cx + s * 0.36, roller_front)
        hl.lineTo(cx + s * 0.10, roller_front)
        hl.closeSubpath()
        hl_grad = QLinearGradient(cx + s * 0.08, cy - s * 0.66, cx + s * 0.36, roller_front)
        hl_grad.setColorAt(0, QColor(255, 215, 140, 25))
        hl_grad.setColorAt(1, QColor(255, 200, 130, 0))
        p.fillPath(hl, QBrush(hl_grad))

    def _draw_typewriter(self, p: QPainter):
        cx = self._tw_cx
        cy = self._tw_cy
        s = self._tw_s

        self._draw_tw_base(p, cx, cy, s)
        self._draw_tw_body(p, cx, cy, s)
        self._draw_tw_ribbon_cover(p, cx, cy, s)
        self._draw_tw_roller(p, cx, cy, s)
        self._draw_tw_paper_guide(p, cx, cy, s)
        self._draw_tw_carriage_lever(p, cx, cy, s)
        self._draw_tw_keys(p, cx, cy, s)
        self._draw_tw_nameplate(p, cx, cy, s)
        self._draw_tw_body_highlight(p, cx, cy, s)

    def _draw_tw_base(self, p, cx, cy, s):
        base = _rounded_rect_path(
            cx - s * 0.62, cy + s * 0.18, s * 1.24, s * 0.055, s * 0.018
        )
        grad = QLinearGradient(cx, cy + s * 0.18, cx, cy + s * 0.24)
        grad.setColorAt(0, QColor(18, 12, 6, 160))
        grad.setColorAt(1, QColor(8, 5, 2, 120))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawPath(base)

        for side in [-1, 1]:
            fx = cx + side * s * 0.55
            fy = cy + s * 0.22
            p.setBrush(QBrush(QColor(12, 8, 4, 120)))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(fx - s * 0.025, fy - s * 0.01, s * 0.05, s * 0.02), 2, 2)

    def _draw_tw_body(self, p, cx, cy, s):
        body = _rounded_rect_path(
            cx - s * 0.58, cy - s * 0.18, s * 1.16, s * 0.38, s * 0.035
        )
        grad = QLinearGradient(cx, cy - s * 0.18, cx, cy + s * 0.20)
        grad.setColorAt(0, QColor(40, 30, 20, 170))
        grad.setColorAt(0.25, QColor(32, 24, 15, 160))
        grad.setColorAt(0.6, QColor(22, 16, 9, 140))
        grad.setColorAt(1, QColor(12, 8, 4, 110))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(160, 120, 65, 45), s * 0.008))
        p.drawPath(body)

        p.setPen(QPen(QColor(80, 58, 30, 30), s * 0.005))
        p.drawLine(
            int(cx - s * 0.54), int(cy + s * 0.19),
            int(cx + s * 0.54), int(cy + s * 0.19),
        )

    def _draw_tw_ribbon_cover(self, p, cx, cy, s):
        cover = QPainterPath()
        cover.moveTo(cx - s * 0.50, cy - s * 0.12)
        cover.cubicTo(
            cx - s * 0.50, cy - s * 0.17,
            cx + s * 0.50, cy - s * 0.17,
            cx + s * 0.50, cy - s * 0.12,
        )
        cover.lineTo(cx + s * 0.50, cy - s * 0.10)
        cover.cubicTo(
            cx + s * 0.50, cy - s * 0.15,
            cx - s * 0.50, cy - s * 0.15,
            cx - s * 0.50, cy - s * 0.10,
        )
        cover.closeSubpath()

        grad = QLinearGradient(cx - s * 0.45, cy - s * 0.17, cx + s * 0.45, cy - s * 0.12)
        grad.setColorAt(0, QColor(45, 34, 22, 160))
        grad.setColorAt(0.55, QColor(55, 40, 26, 175))
        grad.setColorAt(1, QColor(40, 30, 18, 140))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(140, 105, 55, 60), s * 0.005))
        p.drawPath(cover)

        win_cx = cx
        win_cy = cy - s * 0.135
        win_rx = s * 0.10
        win_ry = s * 0.02
        p.setBrush(QBrush(QColor(18, 12, 7, 180)))
        p.setPen(QPen(QColor(120, 90, 45, 70), s * 0.004))
        p.drawEllipse(QPointF(win_cx, win_cy), win_rx, win_ry)

        p.setPen(QPen(QColor(100, 20, 15, 110), s * 0.005))
        p.drawLine(
            int(win_cx - win_rx * 0.75), int(win_cy),
            int(win_cx + win_rx * 0.75), int(win_cy),
        )

    def _draw_tw_roller(self, p, cx, cy, s):
        roller = _rounded_rect_path(
            cx - s * 0.55, cy - s * 0.34, s * 1.10, s * 0.10, s * 0.03
        )
        grad = QLinearGradient(cx, cy - s * 0.34, cx, cy - s * 0.24)
        grad.setColorAt(0, QColor(48, 36, 22, 160))
        grad.setColorAt(0.4, QColor(36, 27, 16, 140))
        grad.setColorAt(1, QColor(22, 16, 9, 110))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(160, 120, 65, 50), s * 0.007))
        p.drawPath(roller)

        for i in range(8):
            ly = cy - s * 0.32 + i * s * 0.009
            p.setPen(QPen(QColor(100, 75, 42, 18), 0.5))
            p.drawLine(int(cx - s * 0.50), int(ly), int(cx + s * 0.50), int(ly))

        for side in [-1, 1]:
            kx = cx + side * s * 0.57
            ky = cy - s * 0.29
            kr = s * 0.04

            knob_grad = QRadialGradient(
                QPointF(kx - kr * 0.15, ky - kr * 0.15), kr * 1.2,
            )
            knob_grad.setColorAt(0, QColor(150, 112, 50, 170))
            knob_grad.setColorAt(0.5, QColor(110, 80, 35, 145))
            knob_grad.setColorAt(1, QColor(60, 42, 18, 110))
            p.setBrush(QBrush(knob_grad))
            p.setPen(QPen(QColor(180, 140, 70, 70), s * 0.004))
            p.drawEllipse(QPointF(kx, ky), kr, kr)

            p.setBrush(QBrush(QColor(160, 120, 55, 140)))
            p.setPen(QPen(QColor(90, 65, 28, 80), s * 0.003))
            p.drawEllipse(QPointF(kx, ky), kr * 0.45, kr * 0.45)

            for spoke in range(4):
                angle = spoke * math.pi / 2
                dx = math.cos(angle) * kr * 0.35
                dy = math.sin(angle) * kr * 0.35
                p.setPen(QPen(QColor(120, 88, 42, 70), s * 0.003))
                p.drawLine(int(kx), int(ky), int(kx + dx), int(ky + dy))

    def _draw_tw_paper_guide(self, p, cx, cy, s):
        gy = cy - s * 0.24
        bar = _rounded_rect_path(
            cx - s * 0.48, gy, s * 0.96, s * 0.014, s * 0.006
        )
        grad = QLinearGradient(cx, gy, cx, gy + s * 0.014)
        grad.setColorAt(0, QColor(160, 120, 60, 90))
        grad.setColorAt(1, QColor(100, 72, 35, 55))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawPath(bar)

    def _draw_tw_carriage_lever(self, p, cx, cy, s):
        lx = cx + s * 0.60
        base_y = cy - s * 0.24
        top_y = cy - s * 0.38

        p.setPen(QPen(QColor(120, 88, 42, 90), s * 0.008))
        p.drawLine(int(lx), int(base_y), int(lx), int(top_y))

        handle = QPainterPath()
        handle.moveTo(lx, top_y)
        handle.lineTo(lx + s * 0.035, top_y - s * 0.015)
        handle.lineTo(lx + s * 0.035, top_y + s * 0.008)
        handle.lineTo(lx, top_y + s * 0.008)
        handle.closeSubpath()
        p.setBrush(QBrush(QColor(140, 105, 48, 100)))
        p.setPen(QPen(QColor(160, 120, 55, 65), s * 0.003))
        p.drawPath(handle)

        p.setBrush(QBrush(QColor(170, 130, 60, 110)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(lx + s * 0.018, top_y - s * 0.008), s * 0.01, s * 0.01)

    def _draw_tw_keys(self, p, cx, cy, s):
        kr = s * 0.024
        h_sp = s * 0.052
        v_sp = s * 0.055

        offsets = [0.0, 0.30, 0.70]

        for row_idx, (chars, off) in enumerate(zip(self.QWERTY_ROWS, offsets)):
            n = len(chars)
            row_w = (n - 1) * h_sp
            sx = cx - row_w / 2 + off * h_sp
            ky = cy - s * 0.03 + row_idx * v_sp
            arc_off = -row_idx * s * 0.006

            for ci, ch in enumerate(chars):
                kx = sx + ci * h_sp
                aky = ky + arc_off

                bg = QRadialGradient(
                    QPointF(kx + kr * 0.18, aky + kr * 0.18), kr * 1.05,
                )
                bg.setColorAt(0, QColor(160, 120, 48, 120))
                bg.setColorAt(0.6, QColor(120, 85, 30, 100))
                bg.setColorAt(1, QColor(65, 45, 16, 70))
                p.setBrush(QBrush(bg))
                p.setPen(QPen(QColor(100, 72, 30, 50), 0.4))
                p.drawEllipse(QPointF(kx, aky), kr, kr)

                fg = QRadialGradient(
                    QPointF(kx + kr * 0.12, aky + kr * 0.12), kr * 0.75,
                )
                fg.setColorAt(0, QColor(35, 25, 15, 170))
                fg.setColorAt(0.5, QColor(15, 10, 6, 190))
                fg.setColorAt(1, QColor(5, 3, 2, 200))
                p.setBrush(QBrush(fg))
                p.setPen(QPen(QColor(40, 28, 14, 70), 0.3))
                p.drawEllipse(QPointF(kx, aky), kr * 0.78, kr * 0.78)

                fs = max(3, int(kr * 0.52))
                p.setFont(QFont("Georgia", fs, QFont.Bold))
                p.setPen(QPen(QColor(130, 110, 75, 130), 0.3))
                p.drawText(
                    QRectF(kx - kr * 0.55, aky - kr * 0.55, kr * 1.1, kr * 1.1),
                    Qt.AlignCenter, ch,
                )

                p.setBrush(QBrush(QColor(255, 215, 160, 35)))
                p.setPen(Qt.NoPen)
                p.drawEllipse(
                    QPointF(kx - kr * 0.18, aky - kr * 0.18),
                    kr * 0.09, kr * 0.09,
                )

        sp_w = s * 0.30
        sp_h = s * 0.028
        sp_x = cx - sp_w / 2
        sp_y = cy - s * 0.03 + 3 * v_sp + s * 0.008

        sp_grad = QLinearGradient(0, sp_y, 0, sp_y + sp_h)
        sp_grad.setColorAt(0, QColor(140, 100, 42, 100))
        sp_grad.setColorAt(0.5, QColor(100, 70, 28, 85))
        sp_grad.setColorAt(1, QColor(60, 40, 15, 60))
        p.setBrush(QBrush(sp_grad))
        p.setPen(QPen(QColor(110, 80, 32, 50), 0.5))
        p.drawRoundedRect(QRectF(sp_x, sp_y, sp_w, sp_h), sp_h / 2, sp_h / 2)

        p.setBrush(QBrush(QColor(18, 12, 6, 180)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(
            QRectF(sp_x + 2, sp_y + 2, sp_w - 4, sp_h - 4),
            (sp_h - 4) / 2, (sp_h - 4) / 2,
        )

        for side in [-1, 1]:
            shx = cx + side * (sp_w / 2 + s * 0.025)
            shy = sp_y - v_sp * 0.1
            shw = s * 0.042
            sh_grad = QRadialGradient(
                QPointF(shx, shy + sp_h / 2), shw,
            )
            sh_grad.setColorAt(0, QColor(130, 92, 35, 80))
            sh_grad.setColorAt(1, QColor(55, 38, 14, 40))
            p.setBrush(QBrush(sh_grad))
            p.setPen(QPen(QColor(80, 55, 22, 35), 0.3))
            p.drawRoundedRect(QRectF(shx - shw / 2, shy, shw, sp_h), sp_h / 2, sp_h / 2)

    def _draw_tw_nameplate(self, p, cx, cy, s):
        pw = s * 0.20
        ph = s * 0.04
        py = cy + s * 0.05
        plate = _rounded_rect_path(cx - pw / 2, py, pw, ph, s * 0.008)
        grad = QLinearGradient(cx, py, cx, py + ph)
        grad.setColorAt(0, QColor(160, 120, 48, 100))
        grad.setColorAt(0.5, QColor(120, 85, 32, 85))
        grad.setColorAt(1, QColor(70, 48, 18, 60))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(130, 95, 40, 50), 0.4))
        p.drawPath(plate)

        fs = max(3, int(s * 0.024))
        p.setFont(QFont("Georgia", fs, QFont.Bold))
        p.setPen(QPen(QColor(18, 10, 4, 130), 0.4))
        p.drawText(QRectF(cx - pw / 2, py, pw, ph), Qt.AlignCenter, "LEMON CODE")

    def _draw_tw_body_highlight(self, p, cx, cy, s):
        hl = QPainterPath()
        hl.moveTo(cx - s * 0.53, cy - s * 0.17)
        hl.cubicTo(cx - s * 0.18, cy - s * 0.19, cx + s * 0.18, cy - s * 0.19, cx + s * 0.53, cy - s * 0.17)
        hl.lineTo(cx + s * 0.50, cy - s * 0.15)
        hl.cubicTo(cx + s * 0.14, cy - s * 0.17, cx - s * 0.14, cy - s * 0.17, cx - s * 0.50, cy - s * 0.15)
        hl.closeSubpath()
        grad = QLinearGradient(cx - s * 0.45, cy - s * 0.19, cx + s * 0.45, cy - s * 0.16)
        grad.setColorAt(0, QColor(255, 200, 130, 5))
        grad.setColorAt(0.6, QColor(255, 210, 140, 15))
        grad.setColorAt(1, QColor(255, 200, 130, 5))
        p.fillPath(hl, QBrush(grad))

    def _draw_lamp(self, p: QPainter):
        lx = self._lamp_x
        ly = self._lamp_y
        ls = self._h * 0.035 * self._scale

        glow_r = ls * 8
        glow = QRadialGradient(QPointF(lx, ly + ls * 2), glow_r)
        glow.setColorAt(0, QColor(255, 215, 140, 55))
        glow.setColorAt(0.15, QColor(255, 200, 120, 30))
        glow.setColorAt(0.4, QColor(255, 180, 100, 10))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(lx, ly + ls * 2), int(glow_r), int(glow_r))

        base_w = ls * 2.5
        base_h = ls * 0.8
        base_grad = QLinearGradient(lx - base_w / 2, ly + ls * 7, lx + base_w / 2, ly + ls * 7)
        base_grad.setColorAt(0, QColor(30, 22, 12, 100))
        base_grad.setColorAt(0.5, QColor(45, 32, 18, 120))
        base_grad.setColorAt(1, QColor(25, 18, 10, 90))
        p.setBrush(QBrush(base_grad))
        p.setPen(QPen(QColor(100, 72, 35, 40), 1))
        p.drawRoundedRect(
            QRectF(lx - base_w / 2, ly + ls * 6.5, base_w, base_h),
            base_h / 2, base_h / 2,
        )

        arm_thick = ls * 0.3
        arm_top = QPointF(lx, ly + ls * 1.5)
        arm_mid = QPointF(lx - ls * 0.5, ly + ls * 3.5)
        arm_bot = QPointF(lx - ls * 0.2, ly + ls * 6.5)

        arm_grad = QLinearGradient(arm_top, arm_bot)
        arm_grad.setColorAt(0, QColor(100, 72, 35, 120))
        arm_grad.setColorAt(1, QColor(40, 28, 14, 90))
        p.setPen(QPen(QBrush(arm_grad), arm_thick))
        p.drawLine(int(arm_top.x()), int(arm_top.y()), int(arm_mid.x()), int(arm_mid.y()))
        p.drawLine(int(arm_mid.x()), int(arm_mid.y()), int(arm_bot.x()), int(arm_bot.y()))

        shade_tw = ls * 1.8
        shade_bw = ls * 2.8
        shade_h = ls * 2.2
        shade_top_y = ly - shade_h * 0.1

        shade = QPolygonF([
            QPointF(lx - shade_tw, shade_top_y),
            QPointF(lx + shade_tw, shade_top_y),
            QPointF(lx + shade_bw, shade_top_y + shade_h),
            QPointF(lx - shade_bw, shade_top_y + shade_h),
        ])
        shade_grad = QLinearGradient(lx - shade_bw, shade_top_y, lx + shade_bw, shade_top_y)
        shade_grad.setColorAt(0, QColor(28, 20, 12, 140))
        shade_grad.setColorAt(0.4, QColor(50, 35, 20, 160))
        shade_grad.setColorAt(0.7, QColor(65, 45, 25, 150))
        shade_grad.setColorAt(1, QColor(35, 24, 14, 120))
        p.setBrush(QBrush(shade_grad))
        p.setPen(QPen(QColor(120, 88, 40, 60), 1.5))
        p.drawPolygon(shade)

        bulb_bottom = shade_top_y + shade_h
        bottom = QPolygonF([
            QPointF(lx - shade_bw + 4, bulb_bottom),
            QPointF(lx + shade_bw - 4, bulb_bottom),
            QPointF(lx + shade_bw * 0.65, bulb_bottom + ls * 0.25),
            QPointF(lx - shade_bw * 0.65, bulb_bottom + ls * 0.25),
        ])
        bulb_grad = QRadialGradient(QPointF(lx, bulb_bottom), shade_bw)
        bulb_grad.setColorAt(0, QColor(255, 245, 210, 160))
        bulb_grad.setColorAt(0.3, QColor(255, 215, 140, 100))
        bulb_grad.setColorAt(0.7, QColor(255, 185, 100, 40))
        bulb_grad.setColorAt(1, QColor(255, 160, 80, 0))
        p.setBrush(QBrush(bulb_grad))
        p.setPen(Qt.NoPen)
        p.drawPolygon(bottom)

        inner_glow = QRadialGradient(QPointF(lx, bulb_bottom - shade_h * 0.3), ls * 0.8)
        inner_glow.setColorAt(0, QColor(255, 240, 200, 140))
        inner_glow.setColorAt(0.5, QColor(255, 220, 160, 80))
        inner_glow.setColorAt(1, QColor(255, 200, 130, 0))
        p.setBrush(QBrush(inner_glow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(lx, bulb_bottom - shade_h * 0.3), ls * 0.5, ls * 0.5)

        p.setBrush(QBrush(QColor(90, 65, 30, 100)))
        p.setPen(QPen(QColor(130, 95, 40, 60), 1))
        p.drawEllipse(QPointF(lx, shade_top_y - ls * 0.1), ls * 0.4, ls * 0.25)

    def set_scale(self, scale: float):
        self._scale = max(0.3, min(3.0, scale))
        self._tw_s = self._h * 0.20 * self._scale


def generate_wallpaper(width=1920, height=1080, save_path=None, scale=0.6):
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    gen = WallpaperGenerator(width, height, scale=scale)
    img = gen.generate()
    if save_path:
        img.save(save_path, "PNG")
    return img


if __name__ == "__main__":
    import os
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "..", "..", "data")
    dpi_specs = [
        ("lemon_wallpaper.png",      1920, 1080),
        ("lemon_wallpaper_50.png",   960,  540),
        ("lemon_wallpaper_100.png",  1920, 1080),
        ("lemon_wallpaper_150.png",  2880, 1620),
    ]
    for name, w, h in dpi_specs:
        out = os.path.join(base_dir, name)
        generate_wallpaper(w, h, out, scale=0.6)
        print(f"专注时刻壁纸已保存到: {out}")
