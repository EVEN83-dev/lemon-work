# -*- coding: utf-8 -*-
"""
终端主题/字号/字体族配置 — 即时热生效
======================================
配置文件：~/.mimo_agent/terminal_config.json

支持的主题：dark (默认), dracula, solarized_dark, one_dark, monokai
"""
import json
import os
from typing import Dict, Any
try:
    from ui.design.tokens import Lemon
except ImportError:
    from standard_mode.ui.design.tokens import Lemon

_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".mimo_agent", "terminal_config.json")

THEMES = {
    "dark": {
        "background": Lemon.DARK_BG_1, "foreground": Lemon.DARK_TEXT_1,
        "cursor": Lemon.BRAND_ORANGE, "selectionBackground": "#ff6b3544",
        "black": Lemon.DARK_BG_2, "red": Lemon.ERROR, "green": "#8cc265",
        "yellow": "#d18f52", "blue": "#4aa5f0", "magenta": "#c162de",
        "cyan": "#42b3c2", "white": Lemon.DARK_TEXT_1,
        "brightBlack": Lemon.SYNTAX_COMMENT, "brightRed": Lemon.ERROR,
        "brightGreen": "#98e06a", "brightYellow": "#ffb86c",
        "brightBlue": "#74b9ff", "brightMagenta": "#e17bff",
        "brightCyan": "#6ef0ff", "brightWhite": Lemon.BG,
    },
    "dracula": {
        "background": "#282a36", "foreground": Lemon.BG,
        "cursor": "#ff79c6", "selectionBackground": "#44475a",
        "black": "#21222c", "red": "#ff5555", "green": "#50fa7b",
        "yellow": "#f1fa8c", "blue": "#bd93f9", "magenta": "#ff79c6",
        "cyan": "#8be9fd", "white": Lemon.BG,
        "brightBlack": "#6272a4", "brightRed": "#ff6e6e",
        "brightGreen": "#69ff94", "brightYellow": "#ffffa5",
        "brightBlue": "#d6acff", "brightMagenta": "#ff92df",
        "brightCyan": "#a4ffff", "brightWhite": Lemon.BG,
    },
    "solarized_dark": {
        "background": "#002b36", "foreground": "#839496",
        "cursor": "#93a1a1", "selectionBackground": "#073642",
        "black": "#073642", "red": "#dc322f", "green": "#859900",
        "yellow": "#b58900", "blue": "#268bd2", "magenta": "#d33682",
        "cyan": "#2aa198", "white": "#eee8d5",
        "brightBlack": "#002b36", "brightRed": "#cb4b16",
        "brightGreen": "#586e75", "brightYellow": "#657b83",
        "brightBlue": "#839496", "brightMagenta": "#6c71c4",
        "brightCyan": "#93a1a1", "brightWhite": "#fdf6e3",
    },
    "one_dark": {
        "background": "#282c34", "foreground": Lemon.SYNTAX_OPERATOR_ALT,
        "cursor": "#528bff", "selectionBackground": "#3e4451",
        "black": "#282c34", "red": Lemon.SYNTAX_SELF, "green": Lemon.SYNTAX_NUMBER,
        "yellow": Lemon.SYNTAX_TYPE, "blue": Lemon.SYNTAX_FUNCTION, "magenta": Lemon.SYNTAX_VARIABLE,
        "cyan": Lemon.SYNTAX_OPERATOR, "white": Lemon.SYNTAX_OPERATOR_ALT,
        "brightBlack": Lemon.SYNTAX_COMMENT, "brightRed": Lemon.SYNTAX_SELF,
        "brightGreen": Lemon.SYNTAX_NUMBER, "brightYellow": Lemon.SYNTAX_TYPE,
        "brightBlue": Lemon.SYNTAX_FUNCTION, "brightMagenta": Lemon.SYNTAX_VARIABLE,
        "brightCyan": Lemon.SYNTAX_OPERATOR, "brightWhite": Lemon.BG,
    },
    "monokai": {
        "background": "#272822", "foreground": Lemon.BG,
        "cursor": "#f8f8f0", "selectionBackground": "#49483e",
        "black": "#272822", "red": "#f92672", "green": "#a6e22e",
        "yellow": "#f4bf75", "blue": "#66d9ef", "magenta": "#ae81ff",
        "cyan": "#a1efe4", "white": Lemon.BG,
        "brightBlack": "#75715e", "brightRed": "#f92672",
        "brightGreen": "#a6e22e", "brightYellow": "#f4bf75",
        "brightBlue": "#66d9ef", "brightMagenta": "#ae81ff",
        "brightCyan": "#a1efe4", "brightWhite": "#f9f8f5",
    },
}

DEFAULT_CONFIG = {
    "theme": "dark",
    "fontSize": 13,
    "fontFamily": '"JetBrains Mono", "Cascadia Code", "Consolas", monospace',
    "scrollback": 10000,
    "cursorBlink": True,
    "cursorStyle": "bar",
}

DEFAULT_SHORTCUTS = {
    "copy": "Ctrl+Shift+C",
    "paste": "Ctrl+Shift+V",
    "search": "Ctrl+F",
    "clear": "Ctrl+L",
    "new_tab": "Ctrl+Shift+T",
    "close_tab": "Ctrl+Shift+W",
    "split_horizontal": "Ctrl+Shift+H",
    "split_vertical": "Ctrl+Shift+V",
    "zoom_in": "Ctrl+=",
    "zoom_out": "Ctrl+-",
    "reset_zoom": "Ctrl+0",
    "interrupt": "Ctrl+C",
    "select_all": "Ctrl+A",
    "eof": "Ctrl+D",
}

_SHORTCUTS_FILE = os.path.join(os.path.expanduser("~"), ".mimo_agent", "terminal_shortcuts.json")


def load_config() -> Dict[str, Any]:
    try:
        if os.path.isfile(_CONFIG_FILE):
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg = dict(DEFAULT_CONFIG)
            cfg.update(saved)
            return cfg
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: Dict[str, Any]):
    try:
        os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_theme_colors(theme_name: str) -> Dict[str, str]:
    return THEMES.get(theme_name, THEMES["dark"])


def build_xterm_options(cfg: Dict[str, Any] = None) -> Dict[str, Any]:
    if cfg is None:
        cfg = load_config()
    theme_name = cfg.get("theme", "dark")
    colors = get_theme_colors(theme_name)
    return {
        "cursorBlink": cfg.get("cursorBlink", True),
        "cursorStyle": cfg.get("cursorStyle", "bar"),
        "fontSize": cfg.get("fontSize", 13),
        "fontFamily": cfg.get("fontFamily", DEFAULT_CONFIG["fontFamily"]),
        "scrollback": cfg.get("scrollback", 10000),
        "theme": colors,
        "allowTransparency": True,
        "windowsMode": True,
        "fastScrollModifier": "alt",
        "fastScrollSensitivity": 5,
        "scrollSensitivity": 1,
    }


def load_shortcuts() -> Dict[str, str]:
    try:
        if os.path.isfile(_SHORTCUTS_FILE):
            with open(_SHORTCUTS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg = dict(DEFAULT_SHORTCUTS)
            cfg.update(saved)
            return cfg
    except Exception:
        pass
    return dict(DEFAULT_SHORTCUTS)


def save_shortcuts(shortcuts: Dict[str, str]):
    try:
        os.makedirs(os.path.dirname(_SHORTCUTS_FILE), exist_ok=True)
        with open(_SHORTCUTS_FILE, "w", encoding="utf-8") as f:
            json.dump(shortcuts, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


SHORTCUT_LABELS = {
    "copy": "复制",
    "paste": "粘贴",
    "search": "搜索",
    "clear": "清屏",
    "new_tab": "新建标签",
    "close_tab": "关闭标签",
    "split_horizontal": "水平分屏",
    "split_vertical": "垂直分屏",
    "zoom_in": "放大字体",
    "zoom_out": "缩小字体",
    "reset_zoom": "重置字体",
    "interrupt": "中断(Ctrl+C)",
    "select_all": "全选",
    "eof": "发送EOF(Ctrl+D)",
}
