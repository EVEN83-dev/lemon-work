# -*- coding: utf-8 -*-
"""Lemon Agent SVG图标加载器
所属窗口: 全局  品牌组件: IconLoader
令牌引用: Lemon.PRIMARY(默认stroke色), BRAND_LEMON
规范: viewBox=0 0 24 24, fill=none, stroke=PRIMARY, stroke-width=1.5,
      stroke-linecap=round, stroke-linejoin=round
尺寸三档: 16px(行内)/20px(列表)/24px(卡片主图标)
"""
import os
from typing import Optional

from PyQt5.QtGui import QIcon, QPixmap, QPainter
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtSvg import QSvgRenderer

from .tokens import Lemon

_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "assets"
)
_ICONS_DIR = os.path.join(_ASSETS_DIR, "icons")
_BRAND_DIR = os.path.join(_ASSETS_DIR, "brand")

_SIZE_MAP = {
    "inline": 16,
    "list": 20,
    "card": 24,
}


def _render_svg(svg_path: str, size: int, stroke_color: Optional[str] = None) -> QPixmap:
    with open(svg_path, "r", encoding="utf-8") as f:
        svg_data = f.read()
    if stroke_color and stroke_color != Lemon.PRIMARY:
        svg_data = svg_data.replace(Lemon.PRIMARY, stroke_color)
    renderer = QSvgRenderer(svg_data.encode("utf-8"))
    if not renderer.isValid():
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        return pixmap
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    result = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return result


def load_icon(name: str, size: str = "card", stroke_color: Optional[str] = None) -> QIcon:
    size_px = _SIZE_MAP.get(size, 24)
    svg_path = os.path.join(_ICONS_DIR, f"{name}.svg")
    if not os.path.exists(svg_path):
        return QIcon()
    pixmap = _render_svg(svg_path, size_px, stroke_color)
    return QIcon(pixmap)


def load_pixmap(name: str, size: str = "card", stroke_color: Optional[str] = None) -> QPixmap:
    size_px = _SIZE_MAP.get(size, 24)
    svg_path = os.path.join(_ICONS_DIR, f"{name}.svg")
    if not os.path.exists(svg_path):
        pixmap = QPixmap(size_px, size_px)
        pixmap.fill(Qt.transparent)
        return pixmap
    return _render_svg(svg_path, size_px, stroke_color)


def load_brand(name: str, size: int = 48, stroke_color: Optional[str] = None) -> QPixmap:
    svg_path = os.path.join(_BRAND_DIR, f"{name}.svg")
    if not os.path.exists(svg_path):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        return pixmap
    return _render_svg(svg_path, size, stroke_color)


ICON_RUNNING = "icon_running"
ICON_SUCCESS = "icon_success"
ICON_FAILED = "icon_failed"
ICON_TIMEOUT = "icon_timeout"
ICON_INTENT = "icon_intent"
ICON_TOOL = "icon_tool"
ICON_GEAR = "icon_gear"
ICON_DOC = "icon_doc"
ICON_STAR = "icon_star"
