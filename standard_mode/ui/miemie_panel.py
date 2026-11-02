# -*- coding: utf-8 -*-
"""
miemie_panel.py
===============
柠檬码 (Lemon Code) 底栏「咩咩」Agent 工作面板。

定位（v4.3.2 明确）：
    · MIEMIE 不是纯聊天机器人，也不是传统操作面板。
    · 它是一个 Agent 工作者：用自然语言接收指令，通过工具链完成具体工作。
    · 交互范式 = 「半对话 · 半操作」：
        - 输入端是对话式的（一句话下达任务）
        - 输出端是操作式的（工具调用链、文件读写、结果摘要）
    · 视觉参考：Claude Code / Cursor Composer——干净、专业、让工具链自己说话。

布局：
    - 顶栏：标识 + 状态 + 固定像素头像（右侧，80×80，可交互）
    - 中部：滚动输出流（用户指令 / 工具调用 / 结果 / 摘要）
    - 底栏：命令输入

v4.3.2 重点：
    - 像素头像放大到 80×80，更高清网格 + 柔和光晕
    - 新增丰富动画：呼吸、眨眼、hover 放大、点击弹跳、思考点头、分析摇摆、
      写入抖动、成功旋转、错误震颤、庆祝跳跃
    - 面板整体改为简约优雅风：新色板、更克制边框、更干净消息块
"""

import os
import sys
import math
import json
import logging
import random

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPointF, QObject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QSplitter, QFrame, QSizePolicy, QLineEdit, QScrollArea,
    QDialog, QProgressBar
)
from PyQt5.QtGui import (
    QPixmap, QPainter, QColor, QIcon, QPen
)

# ★ v4.3.3: 真实工具引擎（glob/grep/read/write/edit/bash/web/analyze/memory/sql/plan）
# 数据：SQLite data/miemie/miemie.db + 记忆 data/miemie/miemie_memory.json
from .miemie_engine import (
    MiemieEngineWorker,
    TOOL_DEFS,
    _PERSONA_PATH,
    _BIG5_LABELS,
    _load_persona,
    tool_persona_calibrate,
    tool_persona_enqueue,
    tool_persona_status,
)
from standard_mode.ui.design.tokens import Lemon

# ★ v4.7.0: 人格工作区（三栏，替代 460px 小弹窗；延迟 import 防循环）
def _persona_workspace_cls():
    from .miemie_persona_workspace import PersonaWorkspace
    return PersonaWorkspace

# ★ v4.3.6: 全站统一 SVG 线条图标（theme.SVG_ICONS，禁用 emoji）
try:
    from .theme import get_svg_icon as _get_svg_icon
except ImportError:
    try:
        from ui.theme import get_svg_icon as _get_svg_icon
    except ImportError:
        _get_svg_icon = None

# ★ v4.7.x: 国际化（语言切换自动生效；key 见 core/i18n.py 的 miemie.* 区块）
try:
    from core.i18n import _t
except ImportError:
    try:
        from standard_mode.core.i18n import _t
    except ImportError:
        def _t(key, **kwargs):
            return key

LOG = logging.getLogger("miemie_panel")


# ==================== QWebChannel 真流式桥接 ====================
class MiemieBridge(QObject):
    """QWebChannel 桥接对象：暴露给 mimo_page.html，实现真流式 token 推送。

    面板侧 attach / detach → 引擎 worker token_event → 本桥接 token_received
    → JS miemieTypewriter 逐字追加，不再用 setTimeout 模拟。
    """
    token_received = pyqtSignal(str)
    stream_done = pyqtSignal(str)      # 流式结束（ok=1 / 0）
    stream_started = pyqtSignal(str)   # 流式开始（JSON: {task_id,model,...}）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_element_selector = None  # 当前打字机目标元素（js 侧标记）

    def attach(self, selector: str = ""):
        """JS 侧调用或 Python 侧同步：标记当前打字机目标元素（CSS selector）。"""
        self._active_element_selector = selector

    def detach(self):
        """清空打字机目标。"""
        self._active_element_selector = None


# 模块级单例：mimo_panel.py 注册到 QWebChannel；miemie_panel.py 连接 worker
_miemie_bridge = None

def get_miemie_bridge() -> MiemieBridge:
    """获取/创建 MiemieBridge 单例（模块级，跨面板共享）。"""
    global _miemie_bridge
    if _miemie_bridge is None:
        try:
            # 必须在 QApplication 创建后调用
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            parent = app.activeWindow() if app else None
        except Exception:
            parent = None
        _miemie_bridge = MiemieBridge(parent)
    return _miemie_bridge


# 设计系统：暗色优雅风，低饱和、高可读、橙色仅作点睛
COLORS = {
    "bg": "{Lemon.DARK_BG_1}",
    "surface": "Lemon.DARK_BG_2",
    "surface_hi": "{Lemon.DARK_BG_3}",
    "text": "{Lemon.DARK_TEXT_1}",
    "text_sec": "{Lemon.DARK_TEXT_2}",
    "text_ter": "{Lemon.DARK_TEXT_3}",
    "primary": "{Lemon.BRAND_ORANGE}",
    "primary_hi": "{Lemon.BRAND_ORANGE_LIGHT}",
    "accent": "#5c9dff",
    "success": "Lemon.ACCENT_GREEN",
    "warning": "{Lemon.ACCENT_GOLD}",
    "error": "{Lemon.ERROR}",
    "border": "rgba(255,255,255,0.08)",
    "border_hi": "rgba(255,122,47,0.45)",
    "glow": "rgba(255,122,47,0.18)",
}


MOOD_COLORS = {
    "idle": COLORS["text"],
    "thinking": COLORS["warning"],
    "analyzing": COLORS["accent"],
    "writing": COLORS["success"],
    "success": COLORS["success"],
    "error": COLORS["error"],
    "celebrating": "#e78ac3",
}





# ==================== 咩咩形象数据源（图片提取的 0/1 像素矩阵）====================
# 数据源：D:\xiaomi_temp\MIEMIE\MIEMIE OC\49194f3816de1a091d0312e00f836f4f.jpg
# 提取方式：亮度阈值 < 200 → 0/1 矩阵（脚本：tools/extract_miemie_pixel.py）
# 数据副本存放在：data/miemie/miemie_pixel_map.json
# 注：用户拍板的咩咩形象。绝不再用 SVG 手绘或 24×24 ASCII 字符点阵。
_MIEMIE_PIXEL_MAP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "miemie", "miemie_pixel_map.json",
)

# ★ v4.4.4: 咩咩形象风格（像素 / 粒子）持久化
_MIEMIE_AVATAR_STYLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "miemie", "avatar_style.json",
)


def _load_avatar_style():
    """读取咩咩形象风格：'pixel'（默认）或 'particle'。"""
    try:
        if os.path.exists(_MIEMIE_AVATAR_STYLE_PATH):
            with open(_MIEMIE_AVATAR_STYLE_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                s = d.get("style")
                if s in ("pixel", "particle"):
                    return s
    except Exception:
        pass
    return "pixel"


def _save_avatar_style(style):
    """持久化咩咩形象风格到 avatar_style.json。"""
    try:
        os.makedirs(os.path.dirname(_MIEMIE_AVATAR_STYLE_PATH), exist_ok=True)
        with open(_MIEMIE_AVATAR_STYLE_PATH, "w", encoding="utf-8") as f:
            json.dump({"style": style}, f, ensure_ascii=False)
    except Exception as e:
        LOG.warning("保存咩咩形象风格失败: %s", e)


def _load_miemie_pixel_map():
    """加载咩咩 0/1 像素矩阵。失败返回 None。"""
    if not os.path.exists(_MIEMIE_PIXEL_MAP_PATH):
        LOG.warning("咩咩像素矩阵未找到: %s", _MIEMIE_PIXEL_MAP_PATH)
        return None
    try:
        with open(_MIEMIE_PIXEL_MAP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        pixels = data.get("pixels")
        if not pixels:
            return None
        return {
            "cols": data.get("grid_cols", len(pixels[0]) if pixels else 0),
            "rows": data.get("grid_rows", len(pixels)),
            "pixels": pixels,
            "features": data.get("features", {}),
        }
    except Exception as e:
        LOG.warning("加载咩咩像素矩阵失败: %s", e)
        return None


# 启动时加载一次（咩咩形象静态数据）
_MIEMIE_PIXEL_MAP = _load_miemie_pixel_map()


def _miemie_pixel_points():
    """返回咩咩所有 1 像素的 (x, y) 列表。"""
    if not _MIEMIE_PIXEL_MAP:
        return []
    return [
        (x, y)
        for y, row in enumerate(_MIEMIE_PIXEL_MAP["pixels"])
        for x, v in enumerate(row) if v == 1
    ]


class _MiemieV1RadarWidget(QWidget):
    """C-T06: MIEMIE.V1 代码评审 5 维雷达图（QPainter 自绘，零依赖）。

    维度顺序固定：rational / meticulous / concise / friendly / rigorous。
    set_scores(dict) 更新并触发重绘；空 dict 时显示虚线提示。
    """

    DIMS = ["rational", "meticulous", "concise", "friendly", "rigorous"]
    LABELS = ["理性", "严谨", "简洁", "友好", "严密"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scores = {}
        self.setStyleSheet("background: transparent;")

    def set_scores(self, scores: dict):
        self._scores = scores or {}
        self.update()

    def clear(self):
        self._scores = {}
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 26
        if r <= 0:
            return
        n = len(self.DIMS)
        # 网格圈
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        for ring in (0.25, 0.5, 0.75, 1.0):
            pts = []
            for i in range(n):
                ang = -math.pi / 2 + 2 * math.pi * i / n
                pts.append(QPointF(cx + r * ring * math.cos(ang),
                                   cy + r * ring * math.sin(ang)))
            for j in range(n):
                a, b = pts[j], pts[(j + 1) % n]
                painter.drawLine(a, b)
        # 轴线 + 标签
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        for i in range(n):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            ex, ey = cx + r * math.cos(ang), cy + r * math.sin(ang)
            painter.drawLine(QPointF(cx, cy), QPointF(ex, ey))
            lx, ly = cx + (r + 14) * math.cos(ang), cy + (r + 14) * math.sin(ang)
            painter.setPen(QPen(QColor(200, 205, 210), 1))
            painter.drawText(int(lx - 12), int(ly + 4), self.LABELS[i])
            painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        # 数据多边形
        if self._scores:
            fill = QColor(255, 122, 47, 90)
            pen = QPen(QColor(255, 122, 47), 2)
            data_pts = []
            for i in range(n):
                ang = -math.pi / 2 + 2 * math.pi * i / n
                v = max(0.0, min(1.0, float(self._scores.get(self.DIMS[i], 0.0))))
                data_pts.append(QPointF(cx + r * v * math.cos(ang),
                                        cy + r * v * math.sin(ang)))
            from PyQt5.QtGui import QPolygonF
            poly = QPolygonF(data_pts)
            painter.setBrush(fill)
            painter.setPen(pen)
            painter.drawPolygon(poly)
            painter.setBrush(Qt.NoBrush)


class _MiemieAvatarWidget(QWidget):
    """咩咩像素头像：从咩咩 OC 图片提取的 0/1 矩阵驱动。

    视觉：
        - 80×80 区域，按 80×74 咩咩原始像素比例居中绘制
        - 每像素整数倍放大，边缘锐利（pixelated 效果）
        - 心情色替换默认白（idle=white, success=绿, error=红, thinking=橙 等）
    动画：
        - 呼吸 / 思考点头 / 分析摇摆 / 写入抖动 / 成功庆祝 / 出错震颤
        - 鼠标悬停放大并发光
        - 点击随机反应
    数据源：data/miemie/miemie_pixel_map.json（与 HTML 端共享同一份）
    """

    ANIM_DURATIONS = {
        "blink": 200, "wink": 240, "bounce": 520,
        "spin": 620, "shake": 420, "celebrate": 1100,
        }

    def __init__(self, size=80, parent=None):
        super().__init__(parent)
        self.setObjectName("miemieAvatarWidget")
        self._size = size
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

        self._mood = "idle"
        self._anim = "breathe"
        self._anim_t = 0
        self._hover = False
        self._glow_color = QColor(COLORS["primary"])

        self._img_label = QLabel(self)
        self._img_label.setAlignment(Qt.AlignCenter)
        self._img_label.setStyleSheet("background: transparent;")
        self._img_label.setGeometry(0, 0, size, size)

        # 像素矩阵数据
        self._grid_cols = (_MIEMIE_PIXEL_MAP or {}).get("cols", 80)
        self._grid_rows = (_MIEMIE_PIXEL_MAP or {}).get("rows", 74)
        self._pixels = _miemie_pixel_points()

        self._base_pix = self._render_base_pixmap(size, size)
        self._img_label.setPixmap(self._base_pix)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)  # 25fps

        # 随机眨眼（整体淡入淡出模拟）
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._do_blink)
        self._blink_timer.start(random.randint(2500, 4500))

        # ★ v4.4.4: 形象风格（像素 / 粒子）
        self._style = _load_avatar_style()
        self._dt = 0
        self._particles = []
        self._particle_r = 2.0
        self._particle_amp = 2.0
        self._init_particles()
        if self._style == "particle":
            self._img_label.hide()

    def setMood(self, mood):
        if mood not in MOOD_COLORS:
            mood = "idle"
        self._mood = mood
        self._glow_color = QColor(MOOD_COLORS.get(mood, COLORS["primary"]))
        self._base_pix = self._render_base_pixmap(self._size, self._size)
        mood_anim = {
            "thinking": "bob", "analyzing": "sway", "writing": "jitter",
            "success": "celebrate", "error": "shake", "celebrating": "celebrate",
        }.get(mood, "breathe")
        self._anim = mood_anim
        self._anim_t = 0

    def trigger_anim(self, name):
        if name not in self.ANIM_DURATIONS:
            return
        self._anim = name
        self._anim_t = 0
        dur = self.ANIM_DURATIONS[name]
        if dur > 0:
            QTimer.singleShot(dur, lambda: setattr(self, "_anim", "breathe"))

    def enterEvent(self, event):
        self._hover = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        choice = random.choice(["bounce", "spin", "wink"])
        self.trigger_anim(choice)
        super().mousePressEvent(event)

    def _do_blink(self):
        if self._anim not in ("breathe", "bob", "sway"):
            return
        self.trigger_anim(random.choice(["blink", "wink"]))
        self._blink_timer.setInterval(random.randint(4000, 8000))

    def _render_base_pixmap(self, W, H):
        """把咩咩像素矩阵渲染成 W×H 的 QPixmap，居中保留原图比例。"""
        out = QPixmap(W, H)
        out.fill(Qt.transparent)
        if not self._pixels:
            return out
        pt = QPainter(out)
        pt.setRenderHint(QPainter.Antialiasing, False)

        # 咩咩原图 cols × rows，按比例适配到 W×H 框（留 6% 内边距）
        gw, gh = self._grid_cols, self._grid_rows
        pad = 0.06
        cell_w = (W * (1 - pad * 2)) / gw
        cell_h = (H * (1 - pad * 2)) / gh
        # 整数倍放大，保证 pixelated 锐利
        cell = max(1, int(min(cell_w, cell_h)))
        # 重新居中
        draw_w = gw * cell
        draw_h = gh * cell
        offset_x = (W - draw_w) / 2
        offset_y = (H - draw_h) / 2

        color = QColor(MOOD_COLORS.get(self._mood, "#f5e6d3"))
        for (gx, gy) in self._pixels:
            px = int(offset_x + gx * cell)
            py = int(offset_y + gy * cell)
            pt.fillRect(px, py, cell, cell, color)
        pt.end()
        return out

    def _tick(self):
        self._anim_t += 1
        self._dt = self._anim_t * 0.05
        if self._style == "particle":
            self._update_particles()
            self.update()
            return
        if self._base_pix is None:
            return
        dt = self._anim_t * 0.05

        sx = sy = 1.0
        rot = 0.0
        tx = ty = 0.0

        anim = self._anim
        if anim == "breathe":
            s = 1.0 + math.sin(dt * 1.2) * 0.035
            sx, sy = s, s
        elif anim == "bob":
            ty = math.sin(dt * 2.2) * 2.5
            s = 1.0 + math.sin(dt * 1.4) * 0.025
            sx, sy = s, s
        elif anim == "sway":
            rot = math.sin(dt * 1.6) * 4.5
        elif anim == "jitter":
            tx = math.sin(dt * 14) * 1.2
            rot = math.sin(dt * 11) * 2.0
        elif anim == "shake":
            tx = math.sin(dt * 18) * 2.5
            rot = math.sin(dt * 22) * 5.5
        elif anim == "bounce":
            t = min(self._anim_t * 0.035, math.pi)
            sy = 1.0 + math.sin(t) * 0.20 * (1 - t / math.pi)
            sx = 1.0 - (sy - 1.0) * 0.45
        elif anim == "spin":
            t = min(self._anim_t * 0.03, 1.0)
            rot = (1 - (1 - t) ** 3) * 360
        elif anim == "celebrate":
            rot = math.sin(dt * 3.0) * 12
            ty = -abs(math.sin(dt * 4.0)) * 6
            s = 1.0 + abs(math.sin(dt * 4.0)) * 0.08
            sx, sy = s, s
        elif anim == "blink":
            # 温和眨眼：稍压扁但图片仍在，不消失
            sy = 0.72
        elif anim == "wink":
            # 单侧眯眼：轻度压扁+微倾，无 shear 撕裂
            sx = 1.0
            sy = 0.70
            rot = 2

        glow_alpha = 0
        if self._hover:
            sx *= 1.10
            sy *= 1.10
            glow_alpha = 50
        if self._mood in ("thinking", "celebrating"):
            glow_alpha = max(glow_alpha, 25)

        out = QPixmap(self._size, self._size)
        out.fill(Qt.transparent)
        pt = QPainter(out)
        pt.setRenderHint(QPainter.Antialiasing, True)

        if glow_alpha > 0:
            gc = QColor(self._glow_color)
            gc.setAlpha(glow_alpha)
            pt.setBrush(gc)
            pt.setPen(Qt.NoPen)
            cx = self._size / 2
            r = self._size * 0.62
            pt.drawEllipse(int(cx - r / 2), int(cx - r / 2), int(r), int(r))

        pt.translate(self._size / 2 + tx, self._size / 2 + ty)
        pt.scale(sx, sy)
        pt.rotate(rot)
        pt.translate(-self._base_pix.width() / 2, -self._base_pix.height() / 2)
        pt.drawPixmap(0, 0, self._base_pix)
        pt.end()
        self._img_label.setPixmap(out)

    # ==================== ★ v4.4.4 粒子风格 ====================
    def _init_particles(self):
        """基于像素矩阵生成粒子锚点（目标位置），并随机散布初始位置。"""
        self._particles = []
        if not self._pixels:
            return
        gw, gh = self._grid_cols, self._grid_rows
        pad = 0.06
        cell = max(1, int(min((self._size * (1 - 2 * pad)) / gw,
                              (self._size * (1 - 2 * pad)) / gh)))
        draw_w = gw * cell
        draw_h = gh * cell
        off_x = (self._size - draw_w) / 2
        off_y = (self._size - draw_h) / 2
        self._particle_cell = cell
        self._particle_r = max(0.9, cell * 0.42)
        self._particle_amp = max(1.5, cell * 0.35)
        for (gx, gy) in self._pixels:
            self._particles.append({
                "tx": off_x + (gx + 0.5) * cell,
                "ty": off_y + (gy + 0.5) * cell,
                "x": random.uniform(0, self._size),
                "y": random.uniform(0, self._size),
                "ph": random.uniform(0, 6.283),
            })

    def _anim_transform(self):
        """返回当前动画变换 (sx, sy, rot, tx, ty, glow_alpha)，供粒子绘制复用。"""
        sx = sy = 1.0
        rot = 0.0
        tx = ty = 0.0
        anim = self._anim
        dt = self._anim_t * 0.05
        if anim == "breathe":
            s = 1.0 + math.sin(dt * 1.2) * 0.035
            sx, sy = s, s
        elif anim == "bob":
            ty = math.sin(dt * 2.2) * 2.5
            s = 1.0 + math.sin(dt * 1.4) * 0.025
            sx, sy = s, s
        elif anim == "sway":
            rot = math.sin(dt * 1.6) * 4.5
        elif anim == "jitter":
            tx = math.sin(dt * 14) * 1.2
            rot = math.sin(dt * 11) * 2.0
        elif anim == "shake":
            tx = math.sin(dt * 18) * 2.5
            rot = math.sin(dt * 22) * 5.5
        elif anim == "bounce":
            t = min(self._anim_t * 0.035, math.pi)
            sy = 1.0 + math.sin(t) * 0.20 * (1 - t / math.pi)
            sx = 1.0 - (sy - 1.0) * 0.45
        elif anim == "spin":
            t = min(self._anim_t * 0.03, 1.0)
            rot = (1 - (1 - t) ** 3) * 360
        elif anim == "celebrate":
            rot = math.sin(dt * 3.0) * 12
            ty = -abs(math.sin(dt * 4.0)) * 6
            s = 1.0 + abs(math.sin(dt * 4.0)) * 0.08
            sx, sy = s, s
        elif anim == "blink":
            sy = 0.72
        elif anim == "wink":
            sx = 1.0
            sy = 0.70
            rot = 2
        glow_alpha = 0
        if self._hover:
            sx *= 1.10
            sy *= 1.10
            glow_alpha = 50
        if self._mood in ("thinking", "celebrating"):
            glow_alpha = max(glow_alpha, 25)
        return sx, sy, rot, tx, ty, glow_alpha

    def _update_particles(self):
        for p in self._particles:
            p["x"] += (p["tx"] - p["x"]) * 0.10
            p["y"] += (p["ty"] - p["y"]) * 0.10

    def paintEvent(self, event):
        if self._style != "particle":
            super().paintEvent(event)
            return
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            sx, sy, rot, tx, ty, glow_alpha = self._anim_transform()
            if glow_alpha > 0:
                gc = QColor(self._glow_color)
                gc.setAlpha(glow_alpha)
                painter.setBrush(gc)
                painter.setPen(Qt.NoPen)
                r = self._size * 0.62
                painter.drawEllipse(int(self._size / 2 - r / 2),
                                   int(self._size / 2 - r / 2),
                                   int(r), int(r))
            painter.translate(self._size / 2 + tx, self._size / 2 + ty)
            painter.scale(sx, sy)
            painter.rotate(rot)
            color = QColor(MOOD_COLORS.get(self._mood, "#f5e6d3"))
            r = self._particle_r
            amp = self._particle_amp
            dt = self._dt
            for p in self._particles:
                fx = math.sin(dt * 1.5 + p["ph"]) * amp
                fy = math.cos(dt * 1.3 + p["ph"]) * amp
                x, y = p["x"] + fx, p["y"] + fy
                gc = QColor(color)
                gc.setAlpha(38)
                painter.setBrush(gc)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(x, y), r * 2.2, r * 2.2)
                painter.setBrush(color)
                painter.drawEllipse(QPointF(x, y), r, r)
            self._draw_particle_features(painter)
            painter.end()
        except Exception as e:
            # 粒子绘制异常时自动回退像素，避免拖垮整个窗口
            LOG.warning("咩咩粒子绘制异常，回退像素风格: %s", e)
            self._style = "pixel"
            self._img_label.show()
            self._base_pix = self._render_base_pixmap(self._size, self._size)
            self._img_label.setPixmap(self._base_pix)
            super().paintEvent(event)

    def _draw_particle_features(self, painter):
        feats = (_MIEMIE_PIXEL_MAP or {}).get("features") or {}
        gw, gh = self._grid_cols, self._grid_rows
        pad = 0.06
        cell = max(1, int(min((self._size * (1 - 2 * pad)) / gw,
                              (self._size * (1 - 2 * pad)) / gh)))
        draw_w = gw * cell
        draw_h = gh * cell
        off_x = (self._size - draw_w) / 2
        off_y = (self._size - draw_h) / 2
        eye_color = QColor("{Lemon.DARK_BG_3}")
        for key in ("eye_left", "eye_right", "mouth"):
            pos = feats.get(key)
            if not pos or len(pos) < 2:
                continue
            ex = off_x + (pos[0] + 0.5) * cell
            ey = off_y + (pos[1] + 0.5) * cell
            best = None
            bestd = 1e9
            for p in self._particles:
                d = (p["tx"] - ex) ** 2 + (p["ty"] - ey) ** 2
                if d < bestd:
                    bestd = d
                    best = p
            if not best:
                continue
            fx = math.sin(self._dt * 1.5 + best["ph"]) * self._particle_amp
            fy = math.cos(self._dt * 1.3 + best["ph"]) * self._particle_amp
            painter.setBrush(eye_color)
            painter.setPen(Qt.NoPen)
            er = max(1.4, cell * 0.7)
            painter.drawEllipse(QPointF(best["x"] + fx, best["y"] + fy), er, er)

    def setStyle(self, style):
        """运行时切换形象风格：'pixel' 或 'particle'。"""
        if style not in ("pixel", "particle"):
            return
        self._style = style
        if style == "particle":
            if not self._particles:
                self._init_particles()
            self._img_label.hide()
        else:
            self._img_label.show()
            self._base_pix = self._render_base_pixmap(self._size, self._size)
            self._img_label.setPixmap(self._base_pix)
        self.update()

    def style(self):
        return self._style


def _svg_pixmap(name, size, color):
    """把 theme.SVG_ICONS 的线条图标渲染为 QPixmap；失败返回 None。"""
    if _get_svg_icon is None:
        return None
    try:
        from PyQt5.QtSvg import QSvgRenderer
        from PyQt5.QtCore import QByteArray
        svg = _get_svg_icon(name, size=size, color=color)
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        pt = QPainter(pm)
        renderer.render(pt)
        pt.end()
        return pm
    except Exception:
        return None


def _svg_qlabel(name, size, color):
    """生成带 SVG 图标的 QLabel；失败返回纯文本图标名。"""
    lbl = QLabel()
    lbl.setStyleSheet("background: transparent;")
    pm = _svg_pixmap(name, size, color)
    if pm is not None and pm.width() > 0:
        lbl.setPixmap(pm)
    else:
        lbl.setText(name)
        lbl.setStyleSheet(f"color:{color}; font-size:10px; background: transparent;")
    return lbl


def _format_tool_result(res):
    """把工具结果 dict 格式化成可读文本。"""
    if not isinstance(res, dict):
        return str(res)
    if res.get("ok") is False:
        return _t("miemie.tool.failed", err=res.get('error', _t("miemie.tool.exec_failed")))
    # grep
    if "matches" in res and isinstance(res["matches"], list) and res["matches"]:
        lines = []
        first = res["matches"][0]
        if isinstance(first, dict) and "line" in first:
            for m in res["matches"][:40]:
                lines.append(f"{m.get('file','?')}:{m.get('line','?')}  {m.get('text','')}")
        else:
            for m in res["matches"][:40]:
                lines.append(str(m))
        if res.get("count", 0) > len(lines):
            lines.append(_t("miemie.tool.result_truncated", count=res['count']))
        return "\n".join(lines) if lines else _t("miemie.tool.no_match")
    # read_file
    if "content" in res and "path" in res:
        head = _t("miemie.tool.file_head", path=res['path'], lines=res.get('lines', '?'), chars=res.get('chars', '?'))
        body = res["content"]
        if res.get("truncated"):
            body += _t("miemie.tool.content_truncated")
        return head + "\n" + body
    # bash
    if "stdout" in res or "stderr" in res:
        out = []
        if res.get("stdout"):
            out.append(f"$ {res.get('command','')}\n{res['stdout']}")
        if res.get("stderr"):
            out.append(f"[stderr]\n{res['stderr']}")
        out.append(f"exit_code = {res.get('exit_code', '?')}")
        return "\n".join(out)
    # web_fetch
    if "text" in res:
        return _t("miemie.tool.url_head", url=res.get('url',''), chars=res.get('chars','?')) + "\n" + res['text']
    # analyze_style
    if "naming_style" in res:
        return (
            _t("miemie.tool.style_target", target=res.get('target','')) + "\n"
            + _t("miemie.tool.style_analyzed", count=res.get('files_analyzed', '?'), total=res.get('total_lines','?')) + "\n"
            + _t("miemie.tool.style_naming", style=res.get('naming_style','?'), indent=res.get('indent_style','?'), width=res.get('indent_width','?')) + "\n"
            + _t("miemie.tool.style_avg", avg=res.get('avg_function_length','?'), ratio=res.get('long_function_ratio','?')) + "\n"
            + (_t("miemie.tool.style_tags", tags=' · '.join(res.get('tags', []))) + "\n" if res.get("tags") else "")
            + _t("miemie.tool.style_summary", summary=res.get('summary',''))
        )
    # memory
    if "entries" in res and isinstance(res["entries"], list):
        if not res["entries"]:
            return _t("miemie.tool.memory_empty")
        return "\n".join(
            f"· {e.get('topic','')}：{e.get('detail','')}" for e in res["entries"]
        )
    # sql
    if "columns" in res:
        cols = res.get("columns", [])
        rows = res.get("rows", [])
        head = "  ".join(cols)
        body = "\n".join("  ".join(str(c) for c in row) for row in rows)
        return f"{head}\n{body}" if rows else f"{head}\n" + _t("miemie.tool.sql_empty", count=res.get('row_count',0))
    # plan
    if "steps" in res and isinstance(res["steps"], list):
        return (
            _t("miemie.tool.sql_goal", goal=res.get('goal',''), py_files=res.get('py_files','?')) + "\n"
            + "\n".join(f"{s.get('n','?')}. {s.get('action','')}  →  {', '.join(s.get('tools',[]))}" for s in res["steps"])
        )
    # write/edit
    if "path" in res and "replaced" in res:
        return _t("miemie.tool.replaced", path=res['path'], count=res['replaced'])
    if "path" in res and "chars" in res:
        return _t("miemie.tool.written", path=res['path'], chars=res['chars'])
    # llm 聊天回复
    if "reply" in res:
        return res["reply"]
    # llm_route 意图识别
    if "intent" in res:
        out = _t("miemie.tool.intent", intent=res['intent'])
        if res.get("reason"):
            out += "\n" + _t("miemie.tool.reason", reason=res['reason'])
        return out
    # 兜底
    return json.dumps(res, ensure_ascii=False, indent=2)


# =====================================================================
# ★ v4.4.1 人格分身可视化对话框（校准入口 + 画像可视化 + 异步喂料）
# =====================================================================

_BIG5_CN = {
    "openness": "开放性",
    "conscientiousness": "尽责性",
    "extraversion": "外向性",
    "agreeableness": "宜人性",
    "neuroticism": "神经质",
}


class _PersonaDialog(QDialog):
    """咩咩分身面板：Big Five 画像可视化 + 校准 + 喂料入队。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("咩咩分身 · 人格画像")
        self.setMinimumWidth(460)
        self._build_ui()
        self.refresh()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(18, 16, 18, 16)

        tip = QLabel("这里是咩咩对你的理解（Layer 1 人格档案，全程本地）。\n"
                     "校准后咩咩会按你的品味行事；喂料用于炼化新素材。")
        tip.setStyleSheet("color:{Lemon.STATUS_OFFLINE}; font-size:12px;")
        tip.setWordWrap(True)
        root.addWidget(tip)

        # 画像区（滚动）
        self._profile_box = QWidget()
        self._profile_lay = QVBoxLayout(self._profile_box)
        self._profile_lay.setContentsMargins(0, 0, 0, 0)
        self._profile_lay.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self._profile_box)
        scroll.setMaximumHeight(300)
        root.addWidget(scroll)

        # —— 校准对话（多轮，★ v4.4.2）——
        calib_box = QWidget()
        calib_box.setStyleSheet("background:#1e2126; border:1px solid Lemon.DARK_BG_4; border-radius:8px;")
        calib_lay = QVBoxLayout(calib_box)
        calib_lay.setContentsMargins(10, 8, 10, 8)
        calib_lay.setSpacing(6)
        calib_title = QLabel("校准对话（多轮，越聊咩咩越懂你）")
        calib_title.setStyleSheet("color:{Lemon.STATUS_OFFLINE}; font-size:11px; font-weight:700;")
        calib_lay.addWidget(calib_title)
        self._calib_history = QScrollArea()
        self._calib_history.setWidgetResizable(True)
        self._calib_history.setFrameShape(QFrame.NoFrame)
        self._calib_history.setMaximumHeight(140)
        self._calib_history_box = QWidget()
        self._calib_history_lay = QVBoxLayout(self._calib_history_box)
        self._calib_history_lay.setContentsMargins(0, 0, 0, 0)
        self._calib_history_lay.setSpacing(4)
        self._calib_history.setWidget(self._calib_history_box)
        calib_lay.addWidget(self._calib_history)
        # 输入行
        calib_row = QHBoxLayout()
        calib_row.setSpacing(6)
        self._calib_input = QLineEdit()
        self._calib_input.setPlaceholderText("校准：例如「我其实很外向，爱和人交流」")
        self._calib_input.returnPressed.connect(self._do_calibrate)
        calib_row.addWidget(self._calib_input, 1)
        self._btn_calib = QPushButton("发送")
        self._btn_calib.setStyleSheet(
            "QPushButton{background:{Lemon.BRAND_ORANGE};color:#fff;border:none;border-radius:6px;"
            "padding:6px 14px;font-weight:600;}"
            "QPushButton:hover{background:#ff8f4d;}")
        self._btn_calib.clicked.connect(self._do_calibrate)
        calib_row.addWidget(self._btn_calib)
        calib_lay.addLayout(calib_row)
        root.addWidget(calib_box)

        # 喂料输入
        self._feed_input = QTextEdit()
        self._feed_input.setPlaceholderText(
            "喂料：粘贴聊天记录/朋友圈文字（可选），可在下方附图片路径（逗号分隔）")
        self._feed_input.setMaximumHeight(90)
        root.addWidget(self._feed_input)
        self._img_input = QLineEdit()
        self._img_input.setPlaceholderText("图片路径（可选，逗号分隔多个）")
        root.addWidget(self._img_input)
        self._btn_feed = QPushButton("异步喂料炼化（后台执行）")
        self._btn_feed.clicked.connect(self._do_feed)
        root.addWidget(self._btn_feed)

        # —— 朋友圈批量导入向导（★ v4.4.2）——
        import_row = QHBoxLayout()
        import_row.setSpacing(6)
        self._btn_batch = QPushButton("朋友圈批量导入")
        self._btn_batch.setStyleSheet(
            "QPushButton{background:Lemon.DARK_BG_4;color:#bdc1c6;border:1px solid #3a3d42;"
            "border-radius:6px;padding:6px 12px;}"
            "QPushButton:hover{background:#33363b;color:#e8eaed;border-color:{Lemon.BRAND_ORANGE};}")
        self._btn_batch.clicked.connect(self._do_batch_import)
        import_row.addWidget(self._btn_batch)
        self._batch_info = QLabel("选择文件夹后自动扫描图片批量炼化（后台）")
        self._batch_info.setStyleSheet(f"color:{Lemon.STATUS_OFFLINE}; font-size:11px;")
        import_row.addWidget(self._batch_info, 1)
        root.addLayout(import_row)

        # 状态提示
        self._status = QLabel("")
        self._status.setStyleSheet("color:#5dd39e; font-size:12px;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._btn_refresh = QPushButton("刷新画像")
        self._btn_refresh.clicked.connect(self.refresh)
        btn_row.addWidget(self._btn_refresh)
        self._btn_close = QPushButton("关闭")
        self._btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

    # ---------- 渲染画像 ----------
    def refresh(self):
        # 清空画像区
        while self._profile_lay.count():
            item = self._profile_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        p = _load_persona()
        if not p:
            self._profile_lay.addWidget(QLabel("（尚无画像。用「分析我的风格」或喂料炼化后生成。）"))
            return
        big5 = p.get("big5") or {}
        # 整体画像
        if p.get("portrait"):
            l = QLabel("画像：" + str(p["portrait"]))
            l.setWordWrap(True)
            l.setStyleSheet("font-weight:700; font-size:13px; color:#e8eaed;")
            self._profile_lay.addWidget(l)
        # 五维进度条
        for k, label in _BIG5_CN.items():
            v = big5.get(k) or {}
            score = float(v.get("score", 50) or 50)
            conf = float(v.get("confidence", 0) or 0)
            row = QHBoxLayout()
            name = QLabel(f"{label}  {score:.0f}/100")
            name.setFixedWidth(130)
            row.addWidget(name)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(score))
            bar.setFixedHeight(10)
            bar.setTextVisible(False)
            bar.setStyleSheet(
                "QProgressBar{background:Lemon.DARK_BG_4;border:none;border-radius:5px;}"
                "QProgressBar::chunk{background:{Lemon.BRAND_ORANGE};border-radius:5px;}"
            )
            row.addWidget(bar, 1)
            conf_l = QLabel(f"信{conf:.1f}")
            conf_l.setFixedWidth(40)
            conf_l.setStyleSheet("color:{Lemon.STATUS_OFFLINE}; font-size:11px;")
            row.addWidget(conf_l)
            self._profile_lay.addLayout(row)
            if v.get("evidence"):
                ev = QLabel("    " + str(v["evidence"])[:80])
                ev.setWordWrap(True)
                ev.setStyleSheet("color:{Lemon.STATUS_OFFLINE}; font-size:11px;")
                self._profile_lay.addWidget(ev)
        # 沟通/审美
        if p.get("communication"):
            l = QLabel("沟通风格：" + str(p["communication"]))
            l.setWordWrap(True)
            l.setStyleSheet("color:#bdc1c6; font-size:12px;")
            self._profile_lay.addWidget(l)
        if p.get("aesthetic"):
            l = QLabel("审美偏好：" + str(p["aesthetic"]))
            l.setWordWrap(True)
            l.setStyleSheet("color:#bdc1c6; font-size:12px;")
            self._profile_lay.addWidget(l)
        self._profile_lay.addStretch(1)

    # ---------- 动作 ----------
    def _add_calib_history(self, who, text, color):
        """向校准对话区追加一行（who: 你/咩咩）。"""
        l = QLabel(f"{who}：{text}")
        l.setWordWrap(True)
        l.setStyleSheet(f"color:{color}; font-size:12px;")
        self._calib_history_lay.addWidget(l)
        # 自动滚动到底
        from PyQt5.QtCore import QTimer as _QTimer
        _QTimer.singleShot(0, lambda: self._calib_history.verticalScrollBar().setValue(
            self._calib_history.verticalScrollBar().maximum()))

    def _do_calibrate(self):
        text = self._calib_input.text().strip()
        if not text:
            self._status.setText("请先输入校准反馈")
            return
        self._add_calib_history("你", text, "#8ab4f8")
        self._calib_input.clear()
        self._status.setText("校准中…（本机 LLM 处理，约几秒）")
        self._btn_calib.setEnabled(False)
        # 异步执行，避免卡 UI
        def _work():
            return tool_persona_calibrate(text)
        th = _CalibThread(_work)
        th.result_ready.connect(self._on_calib_done)
        th.start()

    def _on_calib_done(self, res):
        self._btn_calib.setEnabled(True)
        if res.get("ok"):
            # 摘要含换行 → 取第一行主结论，附维度修正
            summary = (res.get("summary") or "校准完成").replace("\n", "；")
            self._add_calib_history("咩咩", summary, "#5dd39e")
            self._status.setText("[完成] " + summary)
            self.refresh()
        else:
            self._add_calib_history("咩咩", res.get("error") or "校准失败", "#f28b82")
            self._status.setText("[失败] " + (res.get("error") or "校准失败"))

    def _do_feed(self):
        text = self._feed_input.toPlainText().strip()
        imgs = self._img_input.text().strip()
        if not text and not imgs:
            self._status.setText("请先输入喂料文本或图片路径")
            return
        r = tool_persona_enqueue(text=text, image_paths=imgs)
        if r.get("ok"):
            self._status.setText(f"[已入队] 任务 #{r['id']}，队列 {r['queue_len']} 项，后台炼化中…")
            self._feed_input.clear()
            self._img_input.clear()
        else:
            self._status.setText("[失败] " + (r.get("error") or "入队失败"))

    def _do_batch_import(self):
        """朋友圈批量导入向导：选目录 → 扫描图片 → 逐张异步入队（★ v4.4.2）。"""
        from PyQt5.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "选择朋友圈导出目录", "")
        if not folder:
            return
        exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
        imgs = []
        for base, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__")]
            for fn in sorted(files):
                if fn.lower().endswith(exts):
                    imgs.append(os.path.join(base, fn))
        if not imgs:
            self._batch_info.setText("目录中未找到图片")
            return
        # 批量入队（每张图片一个任务，后台逐张视觉解读 + 炼化）
        ok_count = 0
        for p in imgs[:50]:   # 单次最多 50 张，防爆队列
            r = tool_persona_enqueue(text="", image_paths=p, image_caption="")
            if r.get("ok"):
                ok_count += 1
        self._batch_info.setText(f"已入队 {ok_count}/{len(imgs)} 张图片，后台炼化中…")
        self._status.setText(f"[批量导入] {ok_count} 张图片已进入炼化队列")


from PyQt5.QtCore import QThread as _QThread


class _CalibThread(_QThread):
    """后台线程：执行一次校准调用，避免阻塞 UI。"""

    result_ready = pyqtSignal(dict)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.result_ready.emit(self._fn() or {"ok": False, "error": "空结果"})
        except Exception as e:
            self.result_ready.emit({"ok": False, "error": str(e)})


class MiemiePanel(QWidget):
    """底栏「咩咩」Agent 工作面板。

    输入是对话，输出是工具链。界面参考 Claude Code：干净、专业、低饱和。
    """

    analyzeRequested = pyqtSignal(str)
    taskSubmitted = pyqtSignal(str)

    def _toggle_avatar_style(self):
        """形象管理：在 像素 / 粒子 两种风格间切换并持久化。"""
        cur = self.avatar.style() if hasattr(self, "avatar") else "pixel"
        nxt = "particle" if cur == "pixel" else "pixel"
        self.avatar.setStyle(nxt)
        _save_avatar_style(nxt)
        if hasattr(self, "btn_svc_avatar"):
            self.btn_svc_avatar.setToolTip(
                "形象风格：" + ("粒子" if nxt == "particle" else "像素"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("miemiePanel")
        self._current_mood = "idle"
        self._injected_context = ""

        self.setStyleSheet(f"""
            QWidget#miemiePanel {{
                background: {COLORS["bg"]};
                color: {COLORS["text"]};
            }}
            QLabel {{
                color: {COLORS["text"]};
                background: transparent;
            }}
            /* —— 顶部品牌（17px 大字 + 13px 副标题）—— */
            QLabel#miemieTitle {{
                color: {COLORS["text"]};
                font-size: 17px;
                font-weight: 700;
                letter-spacing: 0.3px;
            }}
            QLabel#miemieTitle span {{
                color: {COLORS["primary"]};
            }}
            QLabel#miemieSub {{
                color: {COLORS["text_sec"]};
                font-size: 13px;
                margin-top: 3px;
            }}
            /* —— 状态 pill（11px，圆角胶囊） —— */
            QLabel#miemieMoodPill {{
                color: {COLORS["text"]};
                font-size: 11px;
                padding: 4px 12px;
                border: 1px solid {COLORS["border"]};
                border-radius: 999px;
                background: {COLORS["surface"]};
                font-weight: 600;
            }}
            /* —— 服务功能按钮（顶部右侧 4 个） —— */
            QPushButton#miemieSvcBtn {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 6px;
                min-width: 32px; max-width: 32px;
                min-height: 32px; max-height: 32px;
                color: {COLORS["text_sec"]};
            }}
            QPushButton#miemieSvcBtn:hover {{
                background: {COLORS["surface_hi"]};
                border: 1px solid {COLORS["border"]};
                color: {COLORS["primary_hi"]};
            }}
            /* —— 空状态文案 —— */
            QLabel#miemieHint {{
                color: {COLORS["text_ter"]};
                font-size: 14px;
                line-height: 1.8;
                padding: 8px 4px;
            }}
            /* —— 发送按钮 —— */
            QPushButton#miemieSendBtn {{
                background: {COLORS["primary"]};
                color: {Lemon.BG};
                border: 1px solid {COLORS["primary_hi"]};
                border-radius: 10px;
                padding: 6px;
                min-width: 44px; max-width: 44px;
                min-height: 44px; max-height: 44px;
            }}
            QPushButton#miemieSendBtn:hover {{
                background: {COLORS["primary_hi"]};
                border-color: {COLORS["primary_hi"]};
            }}
            /* —— 快捷任务胶囊 —— */
            QPushButton#miemieQuickBtn {{
                background: {COLORS["surface"]};
                color: {COLORS["text_sec"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 999px;
                padding: 5px 14px;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton#miemieQuickBtn:hover {{
                background: {COLORS["surface_hi"]};
                color: {COLORS["text"]};
                border-color: {COLORS["primary"]};
            }}
            /* ★ v4.7.0 P2: 权限分层开关（自动/确认/调试，橙色高亮） */
            QPushButton#miemiePermBtn {{
                background: {COLORS["surface"]};
                color: {COLORS["primary_hi"]};
                border: 1px solid rgba(255,122,47,0.4);
                border-radius: 999px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#miemiePermBtn:hover {{
                background: rgba(255,122,47,0.12);
                border-color: {COLORS["primary"]};
            }}
            /* —— 工具调用块（左侧 3px 橙边） —— */
            QFrame#miemieToolCall {{
                background: {COLORS["surface"]};
                border: 1px solid {COLORS["border"]};
                border-left: 3px solid {COLORS["primary"]};
                border-radius: 8px;
                padding: 10px 12px;
                margin-top: 6px;
            }}
            /* —— 工具结果块（左侧 3px 蓝边） —— */
            QFrame#miemieToolResult {{
                background: {COLORS["surface"]};
                border: 1px solid {COLORS["border"]};
                border-left: 3px solid {COLORS["accent"]};
                border-radius: 8px;
                padding: 10px 12px;
                margin-top: 6px;
            }}
            /* —— 用户消息（左侧 3px 绿边） —— */
            QLabel#miemieUserMsg {{
                color: {COLORS["text"]};
                background: {COLORS["surface_hi"]};
                border: 1px solid {COLORS["border"]};
                border-left: 3px solid #5dd39e;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 14px;
                line-height: 1.6;
            }}
            /* —— LLM 打字机回复（左侧 3px 橙光晕） —— */
            QLabel#miemieLLMReply {{
                color: {COLORS["text"]};
                background: rgba(255,122,47,0.05);
                border: 1px solid rgba(255,122,47,0.20);
                border-left: 3px solid {COLORS["primary"]};
                border-radius: 8px;
                padding: 12px 14px;
                font-size: 15px;
                line-height: 1.7;
            }}
            /* —— 工具结果文本（13px，等宽） —— */
            QLabel#miemieResultBody, QFrame#miemieToolResult QTextEdit {{
                color: {COLORS["text"]};
                background: transparent;
                font-size: 13px;
                line-height: 1.6;
                font-family: "Cascadia Code", "Consolas", monospace;
            }}
            QFrame#miemieToolResult QTextEdit {{
                border: none;
            }}
            /* —— 工具块标题/描述 —— */
            QLabel#miemieToolTitle {{
                color: {COLORS["primary_hi"]};
                font-size: 13px;
                font-weight: 700;
                background: transparent;
            }}
            QLabel#miemieToolDesc {{
                color: {COLORS["text_ter"]};
                font-size: 12px;
                background: transparent;
            }}
            QLabel#miemieToolArgs {{
                color: {COLORS["text_sec"]};
                font-size: 12px;
                background: transparent;
                font-family: "Cascadia Code", "Consolas", monospace;
            }}
            /* —— 状态 pill（执行中/已完成/失败） —— */
            QLabel#miemieToolState {{
                color: {COLORS["warning"]};
                font-size: 11px;
                padding: 2px 10px;
                border: 1px solid rgba(229,168,75,0.45);
                border-radius: 999px;
                background: rgba(229,168,75,0.10);
                font-weight: 600;
                background-color: transparent;
            }}
            /* —— 摘要（绿色已完成 / 红色失败） —— */
            QLabel#miemieSummary {{
                color: {COLORS["success"]};
                font-size: 13px;
                padding: 10px 14px;
                margin-top: 6px;
                border: 1px solid rgba(93,211,158,0.35);
                border-left: 3px solid {COLORS["success"]};
                border-radius: 8px;
                background: rgba(93,211,158,0.06);
                font-weight: 600;
            }}
            /* —— 输入框（圆角 10，大字号 14） —— */
            QLineEdit#miemieInput {{
                background: {COLORS["surface"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 10px;
                padding: 10px 14px;
                color: {COLORS["text"]};
                font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 14px;
            }}
            QLineEdit#miemieInput:focus {{
                border: 1px solid {COLORS["border_hi"]};
                background: {COLORS["surface_hi"]};
            }}
            /* —— 滚动区 —— */
            QScrollArea#miemieWorkScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#miemieWorkScroll QScrollBar:vertical {{
                background: transparent;
                width: 5px;
                margin: 0px;
            }}
            QScrollArea#miemieWorkScroll QScrollBar::handle:vertical {{
                background: rgba(255,255,255,0.12);
                border-radius: 2px;
                min-height: 40px;
            }}
            QScrollArea#miemieWorkScroll QScrollBar::handle:vertical:hover {{
                background: rgba(255,255,255,0.20);
            }}
            QScrollArea#miemieWorkScroll QScrollBar::add-line:vertical,
            QScrollArea#miemieWorkScroll QScrollBar::sub-line:vertical {{
                background: transparent;
                height: 0px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 12)
        root.setSpacing(0)

        # ========== 顶栏：品牌 + 状态 pill + 服务按钮 + 像素头像 ==========
        header = QWidget()
        header.setFixedHeight(72)
        header.setStyleSheet(
            "background: transparent; border-bottom: 1px solid rgba(255,255,255,0.06);"
        )
        head_l = QHBoxLayout(header)
        head_l.setContentsMargins(0, 0, 0, 8)
        head_l.setSpacing(10)

        info = QVBoxLayout()
        info.setSpacing(2)
        title = QLabel(_t("miemie.title_svg"))
        title.setObjectName("miemieTitle")
        self.sub_label = QLabel(_t("miemie.sub_idle"))
        self.sub_label.setObjectName("miemieSub")
        info.addWidget(title)
        info.addWidget(self.sub_label)
        head_l.addLayout(info)

        head_l.addStretch(1)

        # 服务功能按钮（4 个：导出 / 历史 / 帮助 / 清空）
        self.btn_svc_export = self._make_svc_btn("download", _t("miemie.btn.export"))
        self.btn_svc_export.clicked.connect(self._export_transcript)
        head_l.addWidget(self.btn_svc_export)
        self.btn_svc_history = self._make_svc_btn("history", _t("miemie.btn.history"))
        self.btn_svc_history.setEnabled(False)
        head_l.addWidget(self.btn_svc_history)
        self.btn_svc_help = self._make_svc_btn("help", _t("miemie.btn.help"))
        self.btn_svc_help.clicked.connect(self._show_help)
        head_l.addWidget(self.btn_svc_help)
        self.btn_svc_trash = self._make_svc_btn("trash", _t("miemie.btn.clear"))
        self.btn_svc_trash.clicked.connect(self.clearWorkSteps)
        head_l.addWidget(self.btn_svc_trash)
        init_style = _load_avatar_style()
        self.btn_svc_avatar = self._make_svc_btn(
            "sparkles", _t("miemie.btn.avatar_style", style="粒子" if init_style == "particle" else "像素"))
        self.btn_svc_avatar.clicked.connect(self._toggle_avatar_style)
        head_l.addWidget(self.btn_svc_avatar)
        # ★ v4.7.0: 人格工作区入口（独立大面板）
        self.btn_svc_persona = self._make_svc_btn("user", _t("miemie.btn.persona"))
        self.btn_svc_persona.clicked.connect(self._open_persona_workspace)
        head_l.addWidget(self.btn_svc_persona)

        self.status_label = QLabel("idle")
        self.status_label.setObjectName("miemieMoodPill")
        head_l.addWidget(self.status_label, alignment=Qt.AlignVCenter)

        # ★ v4.7.0 P2: 权限分层开关（自动 / 确认 / 调试）
        self.btn_perm = QPushButton()
        self.btn_perm.setObjectName("miemiePermBtn")
        self.btn_perm.setCursor(Qt.PointingHandCursor)
        self.btn_perm.clicked.connect(self._cycle_permission_mode)
        self._permission_mode = self._load_permission_mode()
        self._update_perm_btn()
        head_l.addWidget(self.btn_perm, alignment=Qt.AlignVCenter)

        # 72×72 像素头像（与 header 同高），固定右侧
        self.avatar = _MiemieAvatarWidget(size=64)
        head_l.addWidget(self.avatar, alignment=Qt.AlignVCenter)

        root.addWidget(header)

        # ========== 中部：可滚动输出流 ==========
        work_scroll = QScrollArea()
        work_scroll.setObjectName("miemieWorkScroll")
        work_scroll.setWidgetResizable(True)
        work_scroll.setFrameShape(QFrame.NoFrame)
        work_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        work_container = QWidget()
        work_container.setStyleSheet("background: transparent;")
        work_l = QVBoxLayout(work_container)
        work_l.setContentsMargins(0, 12, 0, 12)
        work_l.setSpacing(10)

        # 快捷任务：指令 chips（点选填入输入框，由用户确认后执行；人格 → 独立工作区）
        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        for label, hint in [
            ("分析", "分析我的风格"),
            ("搜索", "搜 TODO"),
            ("记忆", "查记忆"),
            ("规划", "规划任务"),
            ("数据库", "查数据库"),
        ]:
            b = QPushButton(label)
            b.setObjectName("miemieQuickBtn")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _, h=hint: self._fill_cmd(h))
            quick_row.addWidget(b)
        b_persona = QPushButton("人格")
        b_persona.setObjectName("miemieQuickBtn")
        b_persona.setCursor(Qt.PointingHandCursor)
        b_persona.clicked.connect(self._open_persona_workspace)
        quick_row.addWidget(b_persona)
        quick_row.addStretch(1)
        work_l.addLayout(quick_row)

        # 空状态：简约文案
        self.work_empty = QLabel(
            "咩咩已就绪。\n"
            "选择快捷任务，或输入自然语言指令，例如：\n"
            "  分析项目 / 搜 TODO / 查记忆 / 规划任务 / 查数据库\n\n"
            "真实工具：glob · grep · read_file · write_file · edit_file ·\n"
            "          bash · web_fetch · analyze_style · memory_search ·\n"
            "          sql_query · plan"
        )
        self.work_empty.setObjectName("miemieHint")
        self.work_empty.setWordWrap(True)
        work_l.addWidget(self.work_empty)

        self.work_steps_box = QWidget()
        self.work_steps_box.setStyleSheet("background: transparent;")
        self.work_steps_layout = QVBoxLayout(self.work_steps_box)
        self.work_steps_layout.setContentsMargins(0, 0, 0, 0)
        self.work_steps_layout.setSpacing(8)
        self.work_steps_box.hide()
        work_l.addWidget(self.work_steps_box)

        work_l.addStretch(1)
        work_scroll.setWidget(work_container)
        root.addWidget(work_scroll, 1)

        # ========== 底栏：命令输入 ==========
        footer = QWidget()
        footer.setFixedHeight(48)
        footer.setStyleSheet("background: transparent; border-top: 1px solid rgba(255,255,255,0.06);")
        foot_l = QHBoxLayout(footer)
        foot_l.setContentsMargins(0, 10, 0, 0)
        foot_l.setSpacing(8)

        self.cmd_input = QLineEdit()
        self.cmd_input.setObjectName("miemieInput")
        self.cmd_input.setPlaceholderText("输入任务，例如：分析项目结构、/search TODO、/help")
        self.cmd_input.returnPressed.connect(self._on_cmd_submit)
        foot_l.addWidget(self.cmd_input, 1)

        self.btn_cmd_send = QPushButton()
        self.btn_cmd_send.setObjectName("miemieSendBtn")
        self.btn_cmd_send.setFixedWidth(44)
        _send_pm = _svg_pixmap("send", 15, COLORS["primary_hi"])
        if _send_pm is not None and _send_pm.width() > 0:
            self.btn_cmd_send.setIcon(QIcon(_send_pm))
            self.btn_cmd_send.setIconSize(_send_pm.size())
        else:
            self.btn_cmd_send.setText(_t("miemie.btn.send"))
        self.btn_cmd_send.setCursor(Qt.PointingHandCursor)
        self.btn_cmd_send.clicked.connect(self._on_cmd_submit)
        foot_l.addWidget(self.btn_cmd_send)

        # —— C-T06: MIEMIE.V1 代码评审入口（风格分析 / 质量评审）——
        self.btn_style = QPushButton("代码风格")
        self.btn_style.setObjectName("miemieQuickBtn")
        self.btn_style.setCursor(Qt.PointingHandCursor)
        self.btn_style.clicked.connect(lambda: self._on_code_review("style_review"))
        foot_l.addWidget(self.btn_style)
        self.btn_quality = QPushButton("代码质量")
        self.btn_quality.setObjectName("miemieQuickBtn")
        self.btn_quality.setCursor(Qt.PointingHandCursor)
        self.btn_quality.clicked.connect(lambda: self._on_code_review("quality_review"))
        foot_l.addWidget(self.btn_quality)

        root.addWidget(footer)

        # —— C-T06: 5 维雷达图（QPainter 自绘，零依赖）——
        self._radar = _MiemieV1RadarWidget(self)
        self._radar.setFixedHeight(180)
        root.addWidget(self._radar)
        self._review_status = QLabel("")
        self._review_status.setObjectName("miemieResultBody")
        root.addWidget(self._review_status)

        self._pending_steps = []
        self._worker = None      # 当前运行中的任务线程
        self._step_widgets = {}  # tool -> (frame, state_label)
        self._llm_reply_label = None  # LLM 打字机回复块

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def setMood(self, mood):
        if mood not in MOOD_COLORS:
            mood = "idle"
        self._current_mood = mood
        self.status_label.setText(mood)
        color = MOOD_COLORS[mood]
        bg = self._alpha(color, 0.10)
        border = self._alpha(color, 0.45)
        self.status_label.setStyleSheet(
            f"color: {color}; font-size: 10px; padding: 3px 10px; "
            f"border: 1px solid {border}; border-radius: 999px; "
            f"background: {bg}; font-weight: 600; text-transform: uppercase;"
        )
        if hasattr(self.avatar, "setMood"):
            self.avatar.setMood(mood)

    def _alpha(self, hex_color, a):
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{a})"

    def _make_svc_btn(self, svg_name, tooltip):
        """顶部服务功能按钮（小图标方块）。"""
        b = QPushButton()
        b.setObjectName("miemieSvcBtn")
        b.setToolTip(tooltip)
        b.setCursor(Qt.PointingHandCursor)
        pm = _svg_pixmap(svg_name, 15, COLORS["text_sec"])
        if pm is not None and pm.width() > 0:
            b.setIcon(QIcon(pm))
            b.setIconSize(pm.size())
        return b

    def _show_help(self):
        """点击 help 按钮：在对话流里插入帮助摘要。"""
        self.work_empty.hide()
        self.work_steps_box.show()
        self.setWorkSteps([
            {"type": "user", "text": "/help"},
            {"type": "summary", "text": (
                "命令帮助\n"
                "/help         显示帮助\n"
                "/clear        清空任务流\n"
                "/analyze      分析项目风格（或输入「分析」）\n"
                "/search       搜索代码（TODO/FIXME/类定义）\n"
                "/memory       查询咩咩记忆库\n"
                "/plan         规划任务\n"
                "/db           查询数据库\n"
                "\n自然语言指令：咩咩会用本机 Ollama 理解，自动选任务；纯聊天会直接回复。\n"
                "Ollama 未启动时自动降级关键词匹配。\n"
                "\n工具能力：glob · grep · read_file · write_file · edit_file · "
                "bash · web_fetch · analyze_style · memory_search · sql_query · plan"
            )},
        ])

    def _export_transcript(self):
        """导出对话为纯文本。"""
        from PyQt5.QtWidgets import QFileDialog
        if self.work_steps_layout.count() == 0:
            self.setMood("idle")
            return
        lines = []
        for i in range(self.work_steps_layout.count()):
            w = self.work_steps_layout.itemAt(i).widget()
            if not w:
                continue
            obj = w.objectName()
            if obj == "miemieUserMsg":
                lines.append(f"用户：{w.text()}")
            elif obj == "miemieSummary":
                lines.append(f"[摘要] {w.text()}")
            elif obj in ("miemieToolCall", "miemieToolResult", "miemieLLMReply"):
                for c in w.findChildren(QLabel):
                    t = c.text().strip()
                    if t:
                        lines.append(t)
        if not lines:
            return
        from datetime import datetime
        default = f"miemie_transcript_{datetime.now():%Y%m%d_%H%M}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出对话", default, "文本文件 (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n\n".join(lines))
            except Exception as e:
                LOG.warning("导出失败: %s", e)

    def setInjectedContext(self, text):
        """接收上层注入的上下文摘要，显示在副标题。"""
        self._injected_context = text or ""
        self.sub_label.setText(self._injected_context or "空闲 · 等待任务")

    def clearWorkSteps(self):
        # 若任务仍在跑，先请求取消
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker = None
        self._step_widgets.clear()
        while self.work_steps_layout.count():
            item = self.work_steps_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.work_steps_box.hide()
        self.work_empty.show()
        self.setMood("idle")

    def setResult(self, text):
        """旧接口：作为一次工具结果块追加到输出流。"""
        self.setWorkSteps([
            {"type": "tool_result", "title": "结果", "content": text or ""}
        ])

    def setWorkSteps(self, steps):
        """Agent 工具链渲染：用户 → 工具调用 → 工具结果 → 摘要。"""
        if not steps:
            return
        self.work_empty.hide()
        self.work_steps_box.show()

        for s in steps:
            if isinstance(s, str):
                self._append_step_row(s)
                continue
            t = s.get("type", "tool_call")
            if t == "user":
                self._append_user_msg(s.get("text", ""))
            elif t == "tool_call":
                self._append_tool_call_inline(s)
            elif t == "tool_result":
                self._append_tool_result_inline(s)
            elif t == "summary":
                self._append_summary_inline(s.get("text", ""))
            else:
                self._append_step_row(str(s))

        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        area = self.findChild(QScrollArea, "miemieWorkScroll")
        if area:
            vsb = area.verticalScrollBar()
            if vsb:
                vsb.setValue(vsb.maximum())

    def _append_user_msg(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("miemieUserMsg")
        lbl.setWordWrap(True)
        self.work_steps_layout.addWidget(lbl)

    def _append_tool_call_inline(self, step):
        """渲染工具调用块；返回 (frame, state_label) 供后续更新状态。"""
        tool = step.get("tool", "tool")
        args = step.get("args", {})
        desc = step.get("desc", "")
        defn = TOOL_DEFS.get(tool, {})
        icon = defn.get("icon", "file_default")
        frame = QFrame()
        frame.setObjectName("miemieToolCall")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        icon_lbl = _svg_qlabel(icon, 14, COLORS["primary_hi"])
        head.addWidget(icon_lbl)
        title = QLabel(tool)
        title.setObjectName("miemieToolTitle")
        head.addWidget(title)
        head.addStretch(1)
        state_label = QLabel(_t("miemie.state.running"))
        state_label.setObjectName("miemieToolState")
        head.addWidget(state_label)
        layout.addLayout(head)

        if desc:
            dlabel = QLabel(desc)
            dlabel.setObjectName("miemieToolDesc")
            layout.addWidget(dlabel)
        if args:
            # ★ v4.7.0 P1: 参数详情默认折叠（渐进式披露）
            args_text = json.dumps(args, ensure_ascii=False, indent=2)
            body = QLabel(args_text)
            body.setObjectName("miemieToolArgs")
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body.setVisible(False)
            layout.addWidget(body)
            toggle = QPushButton(_t("miemie.toggle.params_close"))
            toggle.setObjectName("miemieToggleBtn")
            toggle.setCursor(Qt.PointingHandCursor)
            toggle.setStyleSheet(
                "QPushButton{background:transparent;color:{Lemon.DARK_TEXT_2};border:none;font-size:10px;"
                "text-decoration:underline;padding:0;}")
            toggle.clicked.connect(
                lambda: (body.setVisible(not body.isVisible()),
                         toggle.setText(_t("miemie.toggle.params_open") if body.isVisible() else _t("miemie.toggle.params_close"))))
            layout.addWidget(toggle, alignment=Qt.AlignRight)
        self.work_steps_layout.addWidget(frame)
        return frame, state_label

    def _set_tool_call_state(self, state_label, state):
        """工具调用块状态 pill：running/done/error（pill 背景+边框）。"""
        if state_label is None:
            return
        m = {
            "running": (_t("miemie.state.running"), COLORS["warning"]),
            "done": (_t("miemie.state.done"), COLORS["success"]),
            "error": (_t("miemie.state.error"), COLORS["error"]),
        }
        text, color = m.get(state, ("", COLORS["text_ter"]))
        state_label.setText(text)
        state_label.setStyleSheet(
            f"color:{color}; font-size:11px; padding:2px 10px;"
            f"border:1px solid {self._alpha(color, 0.45)}; border-radius:999px;"
            f"background:{self._alpha(color, 0.10)}; font-weight:600;"
        )

    def _append_tool_result_inline(self, step):
        title = step.get("title", "结果")
        content = step.get("content", "")
        frame = QFrame()
        frame.setObjectName("miemieToolResult")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        # ★ v4.7.0 P1: 结果可收起（长结果折叠，渐进式披露）
        head = QHBoxLayout()
        hl = QLabel(title)
        hl.setObjectName("miemieToolTitle")
        head.addWidget(hl)
        head.addStretch(1)
        toggle = QPushButton("收起 ▾")
        toggle.setObjectName("miemieToggleBtn")
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setStyleSheet(
            "QPushButton{background:transparent;color:{Lemon.DARK_TEXT_2};border:none;font-size:10px;"
            "text-decoration:underline;padding:0;}")
        head.addWidget(toggle)
        layout.addLayout(head)
        if content:
            body = QTextEdit()
            body.setReadOnly(True)
            body.setObjectName("miemieResultBody")
            body.setPlainText(content)
            body.setMaximumHeight(180)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(body)

            def _toggle_body():
                vis = not body.isVisible()
                body.setVisible(vis)
                toggle.setText("收起 ▾" if vis else "展开 ▸")
            toggle.clicked.connect(_toggle_body)
        else:
            toggle.hide()
        self.work_steps_layout.addWidget(frame)

    def _append_summary_inline(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("miemieSummary")
        lbl.setWordWrap(True)
        self.work_steps_layout.addWidget(lbl)

    def _append_step_row(self, text):
        lbl = QLabel(str(text))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {COLORS['text_sec']}; font-size: 11px; padding: 4px 0; background: transparent;")
        self.work_steps_layout.addWidget(lbl)

    # ------------------------------------------------------------------
    # 命令输入 / 快捷任务
    # ------------------------------------------------------------------
    _PLAN_LABELS = {
        "analyze": "分析项目风格",
        "search": "搜索代码",
        "memory": "查询咩咩记忆库",
        "plan": "规划任务",
        "db": "查询数据库",
        "chat": "陪你聊天",
        "llm": "处理指令",
    }

    # ------------------------------------------------------------------
    # C-T06: MIEMIE.V1 代码评审入口
    # ------------------------------------------------------------------
    def _on_code_review(self, intent: str):
        """代码风格/质量评审：取 cmd_input 文本为代码，调 MIEMIE.V1。"""
        code = self.cmd_input.text().strip()
        if not code:
            self._review_status.setText("请先在输入框粘贴代码，再点「代码风格」/「代码质量」。")
            self._radar.clear()
            return
        label = "风格分析" if intent == "style_review" else "质量评审"
        self._review_status.setText(f"⏳ MIEMIE.V1 {label}中…（加载态）")
        self._radar.clear()
        # 异步执行，避免阻塞 UI 线程
        QTimer.singleShot(0, lambda: self._run_code_review(code, intent, label))

    def _run_code_review(self, code: str, intent: str, label: str):
        try:
            from miemie.miemie_engine import MiemieEngine
            eng = MiemieEngine()
            if intent == "style_review":
                rep = eng.analyze_code_style(code, intent)
            else:
                rep = eng.review_code_quality(code, intent)
            self._radar.set_scores(rep.scores)
            lines = [f"MIEMIE.V1 {label}完成（5 维评分）："]
            for d, v in rep.scores.items():
                lines.append(f"  · {d}: {v:.2f}")
            if rep.suggestions:
                lines.append("改进建议：")
                lines.extend(f"  - {s}" for s in rep.suggestions)
            if getattr(rep, "risks", None):
                lines.append("风险点：")
                lines.extend(f"  ! {s}" for s in rep.risks)
            self._review_status.setText("\n".join(lines))
        except Exception as e:  # noqa: BLE001
            self._review_status.setText(f"MIEMIE.V1 {label}失败：{e}")

    def _on_cmd_submit(self):
        text = self.cmd_input.text().strip()
        if not text:
            return
        self.cmd_input.clear()
        self.taskSubmitted.emit(text)

        lower = text.lower()
        if lower == "/help" or lower == "help":
            self.setMood("idle")
            self.setWorkSteps([
                {"type": "user", "text": text},
                {"type": "summary", "text": (
                    "命令帮助\n"
                    "/help         显示帮助\n"
                    "/clear        清空任务流\n"
                    "/analyze      分析项目风格（或输入“分析”）\n"
                    "/search       搜索代码（TODO/FIXME/类定义）\n"
                    "/memory       查询咩咩记忆库\n"
                    "/plan         规划任务\n"
                    "/db           查询数据库\n"
                    "\n"
                    "自然语言指令：咩咩会用本机 Ollama 理解你的话，自动选择任务；\n"
                    "纯聊天会直接回复你。Ollama 未启动时自动降级关键词匹配。\n"
                    "\n"
                    "工具能力：glob · grep · read_file · write_file · edit_file ·\n"
                    "          bash · web_fetch · analyze_style · memory_search · sql_query · plan"
                )},
            ])
            return
        if lower == "/clear" or lower == "清空":
            self.clearWorkSteps()
            return

        # ★ v4.7.0: 人格分析指令 → 打开人格工作区（三栏大面板）
        if any(k in lower for k in ("人格", "分身", "荣格", "分析我", "人格分析")):
            self.setWorkSteps([{"type": "user", "text": text}])
            self._open_persona_workspace()
            return

        # 自然语言 → LLM 意图路由（Ollama 不可用时自动降级关键词）
        self.setWorkSteps([{"type": "user", "text": text}])
        self._run_plan("llm", user_text=text)

    def _open_persona_dialog(self):
        """打开分身面板：人格画像可视化 + 校准 + 异步喂料（★ v4.4.1）。"""
        dlg = _PersonaDialog(self)
        dlg.exec_()

    def _open_persona_workspace(self):
        """★ v4.7.0: 打开人格工作区（三栏大面板，非模态；复用后端异步队列）。"""
        if getattr(self, "_persona_workspace", None) is not None:
            try:
                self._persona_workspace.raise_()
                self._persona_workspace.activateWindow()
                return
            except Exception:
                pass
        cls = _persona_workspace_cls()
        self._persona_workspace = cls(self)
        self._persona_workspace.show()

    # ------------------------------------------------------------------
    # ★ v4.7.0 P1/P2: 指令 chips + 权限分层 + HITL 确认卡
    # ------------------------------------------------------------------
    def _fill_cmd(self, text):
        """指令 chip 点击：填入输入框（执行权交给用户）。"""
        self.cmd_input.setText(text)
        self.cmd_input.setFocus()
        self.cmd_input.selectAll()

    def _perm_cfg_path(self):
        return os.path.join(os.path.dirname(_PERSONA_PATH), "miemie_config.json")

    def _load_permission_mode(self):
        try:
            with open(self._perm_cfg_path(), "r", encoding="utf-8") as f:
                m = json.load(f).get("permission_mode")
            return m if m in ("auto", "confirm", "debug") else "auto"
        except Exception:
            return "auto"

    def _save_permission_mode(self):
        try:
            cfg = self._perm_cfg_path()
            d = {}
            try:
                with open(cfg, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                pass
            d["permission_mode"] = self._permission_mode
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    _PERM_LABEL = {"auto": "自动", "confirm": "确认", "debug": "调试"}
    _PERM_TIP = {
        "auto": "低风险自动跑，高风险(bash/写/改/网络)弹确认",
        "confirm": "咩咩先展示工具计划，确认后才执行",
        "debug": "逐步执行，每一步都确认",
    }

    def _update_perm_btn(self):
        m = self._permission_mode
        self.btn_perm.setText(_t("miemie.perm.prefix", label=self._PERM_LABEL[m]))
        self.btn_perm.setToolTip(self._PERM_TIP[m])

    def _cycle_permission_mode(self):
        seq = ["auto", "confirm", "debug"]
        self._permission_mode = seq[(seq.index(self._permission_mode) + 1) % 3]
        self._update_perm_btn()
        self._save_permission_mode()
        self._append_step_row(f"权限模式 → {self._PERM_LABEL[self._permission_mode]}"
                              f"（{self._PERM_TIP[self._permission_mode]}）")

    def _on_confirm_requested(self, info):
        """worker 请求确认：插入确认卡（执行 / 拒绝 / 始终允许）。"""
        self._append_confirm_card(info)
        self.setMood("thinking")
        QTimer.singleShot(30, self._scroll_to_bottom)

    def _append_confirm_card(self, info):
        tool = info.get("tool", "tool")
        args = info.get("args", {})
        desc = info.get("desc", "")
        risk = info.get("risk", "low")
        defn = TOOL_DEFS.get(tool, {})
        icon = defn.get("icon", "file_default")
        frame = QFrame()
        frame.setObjectName("miemieConfirmCard")
        frame.setStyleSheet(
            "QFrame#miemieConfirmCard{background:#141414; border:1px solid rgba(245,197,66,0.4);"
            " border-left:3px solid {Lemon.ACCENT_GOLD}; border-radius:8px; margin-top:6px;}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        ic = _svg_qlabel(icon, 14, COLORS["warning"])
        head.addWidget(ic)
        t = QLabel(_t("miemie.wait_confirm"))
        t.setStyleSheet("color:{Lemon.ACCENT_GOLD}; font-weight:700; font-size:12px;")
        head.addWidget(t)
        risk_lbl = QLabel(_t("miemie.risk.high") if risk == "high" else _t("miemie.risk.confirm"))
        risk_lbl.setStyleSheet(
            f"color:{Lemon.ACCENT_GOLD}; font-size:10px; padding:2px 8px;"
            f" border:1px solid rgba(245,197,66,0.4); border-radius:999px;"
            f" background:rgba(245,197,66,0.10);")
        head.addWidget(risk_lbl)
        head.addStretch(1)
        lay.addLayout(head)

        name = QLabel(f"<b>{tool}</b> · {desc}")
        name.setTextFormat(Qt.RichText)
        name.setStyleSheet("color:{Lemon.DARK_TEXT_1}; font-size:12px;")
        lay.addWidget(name)
        if args:
            at = QLabel(json.dumps(args, ensure_ascii=False, indent=2))
            at.setStyleSheet("color:{Lemon.DARK_TEXT_2}; font-size:11px; font-family:'Consolas',monospace;")
            at.setWordWrap(True)
            lay.addWidget(at)

        row = QHBoxLayout()
        btn_ok = QPushButton("执行")
        btn_ok.setStyleSheet(
            "QPushButton{background:{Lemon.BRAND_ORANGE};color:#fff;border:none;border-radius:6px;"
            "padding:5px 16px;font-weight:600;font-size:12px;}"
            "QPushButton:hover{background:#ff8f4d;}")
        btn_ok.clicked.connect(lambda: self._worker.set_confirm(True))
        row.addWidget(btn_ok)
        btn_no = QPushButton("拒绝")
        btn_no.setStyleSheet(
            "QPushButton{background:{Lemon.DARK_BG_3};color:{Lemon.ERROR};border:1px solid rgba(255,90,90,0.4);"
            "border-radius:6px;padding:5px 14px;font-size:12px;}"
            "QPushButton:hover{background:Lemon.DARK_BG_4;}")
        btn_no.clicked.connect(lambda: self._worker.set_confirm(False))
        row.addWidget(btn_no)
        btn_alw = QPushButton("始终允许")
        btn_alw.setStyleSheet(
            "QPushButton{background:transparent;color:{Lemon.DARK_TEXT_2};border:none;font-size:11px;"
            "text-decoration:underline;}")
        btn_alw.clicked.connect(lambda: self._worker.set_confirm(True, always=True))
        row.addWidget(btn_alw)
        row.addStretch(1)
        lay.addLayout(row)

        self.work_steps_layout.addWidget(frame)

    def _run_plan(self, plan_name, user_text=None):
        """启动真实引擎线程，逐条流式渲染工具链。

        plan_name == "llm" 时：用本机 Ollama 判断自然语言意图，
        可归类→执行对应计划，纯聊天→直接 LLM 回复。
        """
        if self._worker is not None and self._worker.isRunning():
            self._append_step_row("⚠ 咩咩正忙，请等待当前任务完成。")
            return
        # 清空上一轮输出（保留刚追加的用户指令）
        self.work_empty.hide()
        self.work_steps_box.show()

        self._step_widgets.clear()
        self.setMood("thinking")  # thinking → bob 点头动画

        self._worker = MiemieEngineWorker(plan_name, user_text=user_text, parent=self)
        self._worker.step_event.connect(self._on_worker_step)
        self._worker.result_event.connect(self._on_worker_result)
        self._worker.summary_event.connect(self._on_worker_summary)
        self._worker.done_event.connect(self._on_worker_done)
        self._worker.token_event.connect(self._on_worker_token)
        # ★ v4.7.0 P2: HITL —— 接入权限模式与确认请求
        self._worker.set_confirm_mode(self._permission_mode)
        self._worker.confirm_requested.connect(self._on_confirm_requested)
        self._worker.start()

    # ---------------- worker 信号槽（流式渲染） ----------------

    def _on_worker_step(self, info):
        """工具调用块出现（running 状态）。"""
        tool = info.get("tool", "tool")
        if tool == "llm":
            # LLM：创建打字机回复块
            self._append_llm_reply_block(info.get("desc", _t("miemie.thinking")))
            self.setMood("thinking")
            self.avatar.trigger_anim("bob")
            QTimer.singleShot(30, self._scroll_to_bottom)
            return
        frame, state_label = self._append_tool_call_inline(info)
        self._step_widgets[tool] = (frame, state_label)
        self._set_tool_call_state(state_label, "running")
        self.setMood("analyzing")  # analyzing → sway 摇摆动画
        QTimer.singleShot(30, self._scroll_to_bottom)

    def _append_llm_reply_block(self, hint=""):
        """创建咩咩 LLM 打字机回复块。"""
        self._llm_reply_label = QLabel("")
        self._llm_reply_label.setWordWrap(True)
        self._llm_reply_label.setObjectName("miemieLLMReply")
        self._llm_reply_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if hint:
            self._llm_reply_label.setText(hint)
        self.work_steps_layout.addWidget(self._llm_reply_label)

    def _on_worker_token(self, token):
        """LLM 流式 token → 打字机追加 + QWebChannel 真流式桥接。"""
        lbl = self._llm_reply_label
        if lbl is None:
            self._append_llm_reply_block()
            lbl = self._llm_reply_label
        # 首个 token 清掉占位提示
        if lbl.text().startswith("<span"):
            lbl.setText("")
        lbl.setText(lbl.text() + token)
        QTimer.singleShot(0, self._scroll_to_bottom)
        # QWebChannel 真流式桥接：推送 token 到 mimo_page.html
        try:
            b = get_miemie_bridge()
            b.token_received.emit(token)
        except Exception:
            pass

    def _on_worker_result(self, info):
        """工具结果到达：更新状态 + 渲染结果块。"""
        tool = info.get("tool", "tool")
        state = info.get("state", "done")
        res = info.get("result", {})
        if tool == "llm":
            # LLM：打字机已流式显示；仅失败/无流式时兜底显示
            lbl_txt = self._llm_reply_label.text() if self._llm_reply_label else ""
            is_placeholder = not lbl_txt or lbl_txt.startswith("<span")
            if res.get("ok") is False and is_placeholder:
                self._append_tool_result_inline({"title": _t("miemie.title"), "content": res.get("error", _t("miemie.state.error"))})
            self._llm_reply_label = None
            if state == "done":
                self.avatar.trigger_anim("bounce")
            else:
                self.avatar.trigger_anim("shake")
                self.setMood("error")
            QTimer.singleShot(30, self._scroll_to_bottom)
            return
        pair = self._step_widgets.get(tool)
        if pair:
            self._set_tool_call_state(pair[1], state)
        if state == "done":
            self.avatar.trigger_anim("bounce")
        else:
            self.avatar.trigger_anim("shake")
            self.setMood("error")
        self._append_tool_result_inline({
            "title": f"{tool} 结果",
            "content": _format_tool_result(res),
        })
        QTimer.singleShot(30, self._scroll_to_bottom)

    def _on_worker_summary(self, info):
        self._append_summary_inline(info.get("text", ""))

    def _on_worker_done(self, info):
        ok = info.get("ok", True)
        self.setMood("success" if ok else "error")
        self.avatar.trigger_anim("celebrate" if ok else "shake")
        self._worker = None

    def _on_analyze_click(self):
        """兼容旧版「分析当前项目」按钮。"""
        self._run_plan("analyze")
        self.analyzeRequested.emit("analyze")

    def onAnalyzeFinished(self, result_text):
        """兼容旧版分析完成回调。"""
        self._append_tool_result_inline({"title": "分析结果", "content": result_text or ""})
        self._append_summary_inline("分析完成。")
        self.setMood("success")

    def _extract_context(self, text):
        """（占位）从输入中提取项目路径等上下文。"""
        return text

    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# 简单自检
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = MiemiePanel()
    w.resize(960, 540)
    w.setMood("idle")
    w.show()
    QTimer.singleShot(500, lambda: w.setWorkSteps([
        {"type": "user", "text": "分析当前项目"},
        {"type": "tool_call", "tool": "glob", "args": {"pattern": "**/*.py"}},
        {"type": "tool_result", "title": "项目画像", "content": "命名风格：snake_case\n缩进：4 空格\n平均函数长度：18 行"},
        {"type": "summary", "text": "分析完成。"},
    ]))
    sys.exit(app.exec_())
