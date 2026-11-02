# -*- coding: utf-8 -*-
"""
Color Picker 插件
=================
提供颜色选择和转换工具：
- color_convert: HEX ↔ RGB ↔ HSL 互转
- color_palette: 从基础色生成调色板

无外部依赖。
"""

import os
import sys
import colorsys
import re

_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from plugin_system import IPlugin, ToolDefinition, HookPoint, SkillDefinition


def _hex_to_rgb(hex_str: str):
    """HEX → (r, g, b) 0-255"""
    hex_str = hex_str.lstrip("#").strip()
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)
    if len(hex_str) != 6:
        raise ValueError(f"无效的 HEX 颜色: #{hex_str}")
    try:
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
    except ValueError:
        raise ValueError(f"无效的 HEX 颜色: #{hex_str}")
    return (r, g, b)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """(r, g, b) 0-255 → #rrggbb"""
    for v in (r, g, b):
        if not 0 <= v <= 255:
            raise ValueError(f"RGB 值超出范围: {v}")
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb_to_hsl(r: int, g: int, b: int):
    """RGB 0-255 → HSL (h: 0-360, s: 0-1, l: 0-1)"""
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    return (round(h * 360, 1), round(s, 3), round(l, 3))


def _hsl_to_rgb(h: float, s: float, l: float):
    """HSL → RGB 0-255"""
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return (round(r * 255), round(g * 255), round(b * 255))


def _parse_color(text: str):
    """自动识别颜色格式：HEX / rgb(r,g,b) / hsl(h,s%,l%)"""
    text = text.strip()
    if text.startswith("#") or re.match(r'^[0-9a-fA-F]{3,6}$', text):
        return ("hex", _hex_to_rgb(text))
    m = re.match(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', text)
    if m:
        return ("rgb", (int(m.group(1)), int(m.group(2)), int(m.group(3))))
    m = re.match(r'hsl\(\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*\)', text)
    if m:
        h, s, l = float(m.group(1)), float(m.group(2)) / 100, float(m.group(3)) / 100
        return ("hsl", _hsl_to_rgb(h, s, l))
    raise ValueError(f"无法识别颜色格式: {text}")


def _convert_color(text: str) -> dict:
    """颜色格式互转"""
    fmt, (r, g, b) = _parse_color(text)
    h, s, l = _rgb_to_hsl(r, g, b)
    return {
        "input_format": fmt,
        "hex": _rgb_to_hex(r, g, b),
        "rgb": f"rgb({r}, {g}, {b})",
        "rgb_values": [r, g, b],
        "hsl": f"hsl({h}, {s * 100:.1f}%, {l * 100:.1f}%)",
        "hsl_values": [h, s, l],
    }


def _generate_palette(base_hex: str, count: int = 5) -> list:
    """从基础色生成调色板（类似色方案）"""
    r, g, b = _hex_to_rgb(base_hex)
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    palette = []
    for i in range(count):
        # 在色环上偏移 ±30°/count
        offset = (i - count / 2) * (30.0 / max(count - 1, 1)) / 360.0
        new_h = (h + offset) % 1.0
        # 亮度变化
        new_l = max(0.15, min(0.85, l + (i - count / 2) * 0.08))
        nr, ng, nb = colorsys.hls_to_rgb(new_h, new_l, s)
        palette.append({
            "hex": _rgb_to_hex(round(nr * 255), round(ng * 255), round(nb * 255)),
            "rgb": f"rgb({round(nr * 255)}, {round(ng * 255)}, {round(nb * 255)})",
        })
    return palette


class ColorPickerPlugin(IPlugin):
    """颜色选择器工具插件"""

    @property
    def name(self) -> str:
        return "color_picker"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "颜色选择器：HEX/RGB/HSL 互转 + 调色板生成"

    @property
    def icon(self) -> str:
        return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 0 20 10 10 0 0 1 0-20" fill="currentColor" opacity=".2"/><path d="M12 12v-8"/><path d="M12 12l5-3"/></svg>'''

    def on_load(self) -> bool:
        return True

    def on_unload(self):
        pass

    def get_tools(self):
        return [
            ToolDefinition(
                name="color_convert",
                description="颜色格式转换（HEX/RGB/HSL 互转）",
                parameters=[
                    {"name": "color", "type": "string", "description": "颜色值（#hex / rgb(r,g,b) / hsl(h,s%,l%)）"},
                ],
                handler=self._tool_convert,
                category="color",
            ),
            ToolDefinition(
                name="color_palette",
                description="从基础色生成调色板",
                parameters=[
                    {"name": "base", "type": "string", "description": "基础 HEX 颜色（如 Lemon.ACCENT_BLUE）"},
                    {"name": "count", "type": "integer", "description": "调色板颜色数（默认 5）"},
                ],
                handler=self._tool_palette,
                category="color",
            ),
        ]

    def get_hooks(self):
        return {}

    def get_skills(self):
        return [
            SkillDefinition(
                name="color_picker",
                description="颜色选择与转换技能",
                version="1.0.0",
                author="mimo_agent",
            )
        ]

    # ===== Tool handlers =====
    def _tool_convert(self, **kwargs):
        color = kwargs.get("color", "")
        try:
            return _convert_color(color)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _tool_palette(self, **kwargs):
        base = kwargs.get("base", "Lemon.ACCENT_BLUE")
        count = kwargs.get("count", 5)
        try:
            palette = _generate_palette(base, count=count)
            return {"ok": True, "base": base, "palette": palette}
        except Exception as e:
            return {"ok": False, "error": str(e)}
