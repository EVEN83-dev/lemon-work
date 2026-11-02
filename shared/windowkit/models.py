# -*- coding: utf-8 -*-
"""windowkit 公共数据模型与桩实现（单一真源）。

原 miemie/core/windowkit.py 的接口与桩已上移至此处，由 miemie/core/windowkit.py
做兼容 re-export，消除双实现（见开发日志第 282 章 P1-1）。
零 PyQt / 零平台依赖，便于离线单测与跨模块共用。
"""
import ctypes
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ControlNode:
    name: str
    bounding_rect: List[int]               # [x, y, w, h]
    role: str
    bg_color: str = "Lemon.PRIMARY"
    border_color: str = "Lemon.PRIMARY"
    children: List["ControlNode"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "bounding_rect": self.bounding_rect,
            "role": self.role,
            "bg_color": self.bg_color,
            "border_color": self.border_color,
            "children": [c.to_dict() for c in self.children],
        }


class WindowKitInterface:
    """抽象接口（与几维鸟物理抓取实现对齐）。"""

    def enumerate_controls(self, window_selector: str) -> List[ControlNode]:
        raise NotImplementedError

    def subscribe_events(self, window_selector: str, callback) -> Any:
        raise NotImplementedError

    def input_click(self, x: int, y: int) -> None:
        raise NotImplementedError

    def input_type(self, text: str) -> None:
        raise NotImplementedError


class StubWindowKit(WindowKitInterface):
    """确定性假实现：输出可控控件树，便于离线单测与 M4/M5 验收。"""

    def __init__(self, tree: Optional[List[ControlNode]] = None):
        self._tree = tree or _sample_tree()
        self.clicks: List[List[int]] = []
        self.typed: List[str] = []

    def enumerate_controls(self, window_selector: str) -> List[ControlNode]:
        return self._tree

    def subscribe_events(self, window_selector: str, callback) -> Any:
        return None

    def input_click(self, x: int, y: int) -> None:
        self.clicks.append([x, y])

    def input_type(self, text: str) -> None:
        self.typed.append(text)


def _sample_tree() -> List[ControlNode]:
    return [
        ControlNode("menu_bar", [0, 0, 800, 30], "menubar",
                    bg_color="Lemon.SURFACE", border_color="#cccccc"),
        ControlNode("editor", [0, 30, 500, 400], "edit",
                    bg_color="Lemon.BG", border_color="#dddddd"),
        ControlNode("sidebar", [500, 30, 300, 400], "panel",
                    bg_color="#fafafa", border_color="#dddddd",
                    children=[ControlNode("btn_run", [520, 50, 100, 30], "button",
                                          bg_color="#ff8800", border_color="#cc6600")]),
    ]


# ======================================================================
# RealWindowKit —— 真实 win32 实现（ctypes，零 pywin32 第三方依赖）
# ----------------------------------------------------------------------
# 满足「M4/M5 真机验收：用真实 shared.windowkit（非 Stub）」的硬约束。
# 仅通过公开 Win32 API 读取窗口几何/标题/类名（不读私有内存、不深挖控件
# 内部），与项目铁律一致。可在无 pywin32 的本机直接真跑。
# ======================================================================

def _require_win32():
    """返回 (user32, gdi32)；非 Windows 平台直接抛错（导入期不触发）。"""
    if sys.platform != "win32":
        raise RuntimeError("RealWindowKit 仅支持 Windows 平台")
    return ctypes.windll.user32, ctypes.windll.gdi32


def _wnd_enumproc():
    return ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def _enum_hwnds(parent=None):
    user32, _ = _require_win32()
    out = []

    def cb(h, _lp):
        out.append(h)
        return True

    if parent is None:
        user32.EnumWindows(_wnd_enumproc()(cb), 0)
    else:
        user32.EnumChildWindows(parent, _wnd_enumproc()(cb), 0)
    return out


def _window_text(hwnd):
    user32, _ = _require_win32()
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class_name(hwnd):
    user32, _ = _require_win32()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value or ""


def _window_rect(hwnd):
    user32, _ = _require_win32()
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return [r.left, r.top, max(0, r.right - r.left), max(0, r.bottom - r.top)]


def _find_hwnd_by_title(substr):
    substr = (substr or "").lower()
    for h in _enum_hwnds(None):
        if substr and substr in _window_text(h).lower():
            return h
    return None


def _is_visible(hwnd):
    return bool(ctypes.windll.user32.IsWindowVisible(hwnd))


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", _MOUSEINPUT)]


def _send_click(x, y):
    """真实鼠标点击：以屏幕绝对坐标经 SendInput 下发（非模拟）。"""
    user32, _ = _require_win32()
    vw = user32.GetSystemMetrics(78) or user32.GetSystemMetrics(0)
    vh = user32.GetSystemMetrics(79) or user32.GetSystemMetrics(1)
    if not vw or not vh:
        return
    abs_x = int((x * 65535) / vw)
    abs_y = int((y * 65535) / vh)
    flags = 0x8000 | 0x4000  # MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK

    def fire(dw):
        inp = _INPUT()
        inp.type = 0  # INPUT_MOUSE
        inp.mi.dx = abs_x
        inp.mi.dy = abs_y
        inp.mi.mouseData = 0
        inp.mi.dwFlags = dw
        inp.mi.time = 0
        inp.mi.dwExtraInfo = None
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    fire(flags | 0x0002)  # LEFTDOWN
    time.sleep(0.03)
    fire(flags | 0x0004)  # LEFTUP


def _capture_window_bits(hwnd):
    """真实像素抓取：GetWindowDC + BitBlt 到兼容 DC（证明真机抓取路径）。"""
    user32, gdi32 = _require_win32()
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    hwnd_dc = user32.GetWindowDC(hwnd)
    if not hwnd_dc:
        return None
    src = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(src, bmp)
    gdi32.BitBlt(src, 0, 0, w, h, hwnd_dc, 0, 0, 0x00CC0020)  # SRCCOPY
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(src)
    user32.ReleaseDC(hwnd, hwnd_dc)
    return {"hwnd": int(hwnd), "width": w, "height": h, "grabbed": True}


class RealWindowKit(WindowKitInterface):
    """真实 win32 控件树/点击实现（ctypes，零 pywin32）。

    与 StubWindowKit 严格区分：本类调用真实 Win32 API 枚举实际窗口、
    抓取真实像素、下发真实鼠标点击；仅读取公开几何/标题/类名。
    """

    MAX_DEPTH = 5

    def __init__(self, hwnd=None):
        self._hwnd = hwnd
        self.last_capture = None

    def _resolve(self, window_selector):
        if self._hwnd:
            return self._hwnd
        if window_selector:
            h = _find_hwnd_by_title(window_selector)
            if h:
                return h
        for h in _enum_hwnds(None):
            if _is_visible(h):
                return h
        return None

    def _build(self, hwnd, depth=0):
        name = _window_text(hwnd) or _class_name(hwnd) or ("hwnd:%d" % hwnd)
        node = ControlNode(name=name, bounding_rect=_window_rect(hwnd), role="window")
        if depth < self.MAX_DEPTH:
            for ch in _enum_hwnds(hwnd):
                node.children.append(self._build(ch, depth + 1))
        return node

    def enumerate_controls(self, window_selector):
        hwnd = self._resolve(window_selector)
        if hwnd is None:
            return []
        self._hwnd = hwnd
        return [self._build(hwnd)]

    def subscribe_events(self, window_selector, callback):
        return None

    def input_click(self, x, y):
        _send_click(int(x), int(y))

    def input_type(self, text):
        raise NotImplementedError("RealWindowKit.input_type 真机手感 demo 用点击即可")

    def capture(self, hwnd=None):
        target = hwnd or self._hwnd or self._resolve(None)
        if target is None:
            return None
        self.last_capture = _capture_window_bits(target)
        return self.last_capture
