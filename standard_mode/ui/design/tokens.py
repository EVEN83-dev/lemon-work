# -*- coding: utf-8 -*-
"""Lemon Agent design token system - brand foundation
All UI code must reference tokens from this file only.
"""


class Lemon:
    PRIMARY = "#2D2D2D"
    SECONDARY = "#b0b0b0"
    BG = "#0d0d0d"
    SURFACE = "#161616"
    BORDER = "#252525"
    BORDER_HOVER = "#333333"
    SUCCESS = "#4caf50"
    ERROR = "#ff5252"
    BRAND_LEMON = "#ffd700"
    BRAND_ORANGE = "#ff6900"
    BRAND_ORANGE_LIGHT = "#ff8c42"
    BRAND_ORANGE_DARK = "#cc5400"
    ACCENT_GOLD = "#d4a574"
    ACCENT_RED = "#ff5252"
    ACCENT_GREEN = "#4caf50"
    ACCENT_PURPLE = "#c678dd"
    ACCENT_BLUE = "#448aff"
    ACCENT_PINK = "#ff80ab"
    ACCENT_ORANGE = "#ffab40"
    STATUS_RUNNING = "#448aff"
    STATUS_ONLINE = "#4caf50"
    STATUS_OFFLINE = "#808080"
    STATUS_WARNING = "#ffab40"
    DARK_BG_1 = "#080808"
    DARK_BG_2 = "#161616"
    DARK_BG_3 = "#1c1c1c"
    DARK_BG_4 = "#252525"
    DARK_TEXT_1 = "#ffffff"
    DARK_TEXT_2 = "#b0b0b0"
    DARK_TEXT_3 = "#808080"
    SYNTAX_KEYWORD = "#ff6a00"
    SYNTAX_STRING = "#98c379"
    SYNTAX_COMMENT = "#5c6370"
    SYNTAX_FUNCTION = "#61afef"
    SYNTAX_VARIABLE = "#eeffff"
    SYNTAX_NUMBER = "#d19a66"
    SYNTAX_TYPE = "#e5c07b"
    SYNTAX_OPERATOR = "#abb2bf"
    # ---- 语法高亮扩展 token（第351章后补：解决装饰器/内置/TODO 无染色）----
    SYNTAX_BUILTIN = "#56b6c2"     # 内置函数（青）
    SYNTAX_CONSTANT = "#e06c75"    # self/this/常量（红）
    SYNTAX_TAG = "#e06c75"         # HTML 标签（红）
    SYNTAX_ATTR = "#d19a66"        # HTML 属性（橙黄）
    SYNTAX_TODO = "#ffab40"        # TODO/FIXME 注释（警告橙）

    # ---- 文件类型色板（VSCode Material-Icon 12 色分类，暗色底适配）----
    FILE_C_BLUE = "#519ABA"        # 主流语言 py/ts/cpp/c#
    FILE_C_YELLOW = "#F0DB4F"      # 脚本 js/json/yaml
    FILE_C_ORANGE = "#E34F26"      # 标记语言 html/xml/vue
    FILE_C_CYAN = "#4DD0E1"        # 样式 css/scss/less
    FILE_C_GREEN = "#89E051"       # shell/可执行/构建
    FILE_C_PURPLE = "#C792EA"      # 数据 sql/db
    FILE_C_PINK = "#FF80AB"        # 媒体 图片/音视频
    FILE_C_RED = "#F44336"         # pdf/归档
    FILE_C_BROWN = "#DEA584"       # rust/编译产物
    FILE_C_INDIGO = "#7986CB"      # 文档 doc/md
    FILE_C_LIME = "#C3E88D"        # 配置 toml/ini/env
    FILE_C_GRAY = "#9E9E9E"        # 兜底/未知类型
    SCROLLBAR_THUMB = "#444444"
    SCROLLBAR_THUMB_HOVER = "#555555"
    DIVIDER = "#333333"
    PLACEHOLDER = "#555555"
    DARK_MID_1 = "#080808"
    DARK_MID_2 = "#111111"
    DARK_MID_3 = "#161616"
    DARK_MID_4 = "#1c1c1c"
    DARK_MID_5 = "#252525"
    DARK_MIMO_ORANGE = "#cc5400"
    DARK_GOLD_ALT = "#d4a574"
    DARK_YELLOW_LIGHT = "#ffe066"
    TEXT_PRIMARY = "#FFFFFF"
    TEXT_SECONDARY = "#B0B0B0"
    TEXT_TERTIARY = "#808080"
    TEXT_MUTED = "#555555"
    TEXT_DISABLED = "#3a3a3a"
    TEXT_PLACEHOLDER_DARK = "#4a4a4a"

    SUCCESS_BG_DARK = "#0a2a0e"
    SUCCESS_BORDER_DARK = "#2d6a30"
    ERROR_BG_DARK = "#2a0a0a"
    ERROR_BORDER_DARK = "#6a2d2d"
    WARNING_BG_DARK = "#2a1a0a"
    WARNING_BORDER_DARK = "#6a4d2d"
    INFO_BG_DARK = "#0a1a2a"
    INFO_BORDER_DARK = "#2d4d6a"

    DIFF_ADD_LINE_BG = "#122d1e"
    DIFF_REMOVE_LINE_BG = "#3d151a"

    SYNTAX_NUMBER_ALT = "#d19a66"
    SYNTAX_SELF = "#e06c75"
    SYNTAX_OPERATOR_ALT = "#abb2bf"

    SP_XS = 4
    SP_S = 8
    SP_M = 16
    SP_L = 24
    SP_XL = 32

    R_S = 6
    R_M = 10
    R_L = 16

    FONT = "HarmonyOS Sans"
    FS_CAPTION = 11
    FS_BODY = 13
    FS_SUB = 14
    FS_TITLE = 16
    FS_H = 20

    DUR_FAST = 120
    DUR_NORMAL = 200
    DUR_SLOW = 320
    DUR_TYPING = 20
    DUR_BOUNCE = 250
    MAX_CONCURRENT_ANIMATIONS = 15

    LINE_HEIGHT_BODY = 1.6

    @classmethod
    def font(cls, size: int, bold: bool = False) -> str:
        w = "Bold" if bold else "Regular"
        return f"{cls.FONT},{size},{w}"

    @classmethod
    def font_css(cls, size: int, bold: bool = False) -> str:
        w = "bold" if bold else "normal"
        return f'font-family: "{cls.FONT}"; font-size: {size}px; font-weight: {w};'


class LemonDark:
    PRIMARY = "#EAEAEA"
    SECONDARY = "#9A9A9A"
    BG = "#1A1A1A"
    SURFACE = "#242424"
    BORDER = "#3A3A3A"
    BORDER_HOVER = "#4A4A4A"
    SUCCESS = "#6BBF7B"
    ERROR = "#D47272"
    BRAND_LEMON = "#E8B931"

    BRAND_ORANGE = "#FF8C42"
    BRAND_ORANGE_LIGHT = "#FFA866"
    BRAND_ORANGE_DARK = "#CC5400"

    ACCENT_GOLD = "#FFD700"
    ACCENT_RED = "#F87171"
    ACCENT_GREEN = "#6BBF7B"
    ACCENT_PURPLE = "#A78BFA"
    ACCENT_BLUE = "#58A6FF"
    ACCENT_PINK = "#F472B6"
    ACCENT_ORANGE = "#FB923C"

    STATUS_RUNNING = "#58A6FF"
    STATUS_ONLINE = "#3FB950"
    STATUS_OFFLINE = "#8B949E"
    STATUS_WARNING = "#FCD34D"

    DARK_BG_1 = "#0A0A0B"
    DARK_BG_2 = "#121214"
    DARK_BG_3 = "#1A1A1C"
    DARK_BG_4 = "#222226"
    DARK_TEXT_1 = "#E8E8E8"
    DARK_TEXT_2 = "#8F8F93"
    DARK_TEXT_3 = "#5C5C61"

    SYNTAX_KEYWORD = "#FF7B72"
    SYNTAX_STRING = "#A5D6FF"
    SYNTAX_COMMENT = "#6E7681"
    SYNTAX_FUNCTION = "#79C0FF"
    SYNTAX_VARIABLE = "#D2A8FF"
    SYNTAX_NUMBER = "#98C379"
    SYNTAX_TYPE = "#E5C07B"
    SYNTAX_OPERATOR = "#56B6C2"

    SCROLLBAR_THUMB = "#3A3A3A"
    SCROLLBAR_THUMB_HOVER = "#555555"
    DIVIDER = "#3A3A3A"
    PLACEHOLDER = "#8A8A8A"

    DARK_MID_1 = "#0D0D0D"
    DARK_MID_2 = "#111111"
    DARK_MID_3 = "#1C1C1C"
    DARK_MID_4 = "#252525"
    DARK_MID_5 = "#1A1A2A"
    DARK_MIMO_ORANGE = "#E67E22"
    DARK_GOLD_ALT = "#D4A574"
    DARK_YELLOW_LIGHT = "#FFE066"

    TEXT_TERTIARY = "#808080"
    TEXT_MUTED = "#555555"
    TEXT_DISABLED = "#3A3A3A"
    TEXT_PLACEHOLDER_DARK = "#4A4A4A"

    SUCCESS_BG_DARK = "#0A2A0E"
    SUCCESS_BORDER_DARK = "#2D6A30"
    ERROR_BG_DARK = "#2A0A0A"
    ERROR_BORDER_DARK = "#6A2D2D"
    WARNING_BG_DARK = "#2A1A0A"
    WARNING_BORDER_DARK = "#6A4D2D"
    INFO_BG_DARK = "#0A1A2A"
    INFO_BORDER_DARK = "#2D4D6A"

    DIFF_ADD_LINE_BG = "#122D1E"
    DIFF_REMOVE_LINE_BG = "#3D151A"

    SYNTAX_NUMBER_ALT = "#D19A66"
    SYNTAX_SELF = "#E06C75"
    SYNTAX_OPERATOR_ALT = "#ABB2BF"

    SP_XS = Lemon.SP_XS
    SP_S = Lemon.SP_S
    SP_M = Lemon.SP_M
    SP_L = Lemon.SP_L
    SP_XL = Lemon.SP_XL

    R_S = Lemon.R_S
    R_M = Lemon.R_M
    R_L = Lemon.R_L

    FONT = Lemon.FONT
    FS_CAPTION = Lemon.FS_CAPTION
    FS_BODY = Lemon.FS_BODY
    FS_SUB = Lemon.FS_SUB
    FS_TITLE = Lemon.FS_TITLE
    FS_H = Lemon.FS_H

    DUR_FAST = Lemon.DUR_FAST
    DUR_NORMAL = Lemon.DUR_NORMAL
    DUR_SLOW = Lemon.DUR_SLOW

    LINE_HEIGHT_BODY = Lemon.LINE_HEIGHT_BODY

    @classmethod
    def font(cls, size: int, bold: bool = False) -> str:
        return Lemon.font(size, bold)

    @classmethod
    def font_css(cls, size: int, bold: bool = False) -> str:
        return Lemon.font_css(size, bold)


_active_tokens = Lemon


class AnimationLimiter:
    """v6.0-S: 全局动画并发限制器。超过MAX_CONCURRENT时延迟执行，非活跃窗口暂停。"""
    _instance = None
    _active_count = 0
    _pending = []

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def can_start(self) -> bool:
        return self._active_count < Lemon.MAX_CONCURRENT_ANIMATIONS

    def register(self) -> None:
        self._active_count += 1

    def unregister(self) -> None:
        self._active_count = max(0, self._active_count - 1)
        if self._pending:
            callback = self._pending.pop(0)
            try:
                callback()
            except Exception:
                pass

    def schedule(self, callback) -> None:
        if self.can_start():
            self.register()
            try:
                callback()
            except Exception:
                self.unregister()
        else:
            self._pending.append(callback)


def set_theme(dark: bool = False):
    global _active_tokens
    _active_tokens = LemonDark if dark else Lemon


def tokens() -> type:
    return _active_tokens


def is_dark_theme() -> bool:
    return _active_tokens is LemonDark
