"""窗口枚举与 DPI 感知。

仅依赖 pywin32（win32gui / win32process / win32api）。缺失时导入不崩，
调用对应函数会抛出 UnsupportedPlatformError / ImportError 友好提示。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import List, Optional

from .exceptions import UnsupportedPlatformError, WindowNotFoundError


@dataclass
class WindowInfo:
    """单个窗口的轻量描述，全部来自公开 API。"""

    hwnd: int
    title: str = ""
    class_name: str = ""
    pid: int = 0
    exe_path: str = ""
    # 物理像素坐标（设备坐标），由 GetWindowRect 给出
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    visible: bool = False
    dpi: int = 96

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def rect(self) -> tuple:
        return (self.left, self.top, self.right, self.bottom)

    def to_dict(self) -> dict:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "class_name": self.class_name,
            "pid": self.pid,
            "exe_path": self.exe_path,
            "rect": list(self.rect),
            "width": self.width,
            "height": self.height,
            "visible": self.visible,
            "dpi": self.dpi,
        }


def _require_win32():
    """惰性导入 win32 模块；非 Windows 或缺失时抛友好异常。"""
    if sys.platform != "win32":
        raise UnsupportedPlatformError("window_enum 仅支持 Windows 平台")
    try:
        import win32api  # noqa: F401
        import win32gui  # noqa: F401
        import win32process  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise UnsupportedPlatformError(
            "缺少 pywin32，请 pip install pywin32：%s" % exc
        )
    return win32gui, win32process, win32api


def set_dpi_aware() -> bool:
    """开启进程 DPI 感知，使 GetWindowRect 返回物理像素。

    返回是否成功设置（多次调用幂等）。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        try:
            # Windows 8.1+：每 monitor DPI 感知
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            # 旧系统：系统级 DPI 感知
            ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:  # pragma: no cover
        return False


def get_dpi(hwnd: Optional[int] = None) -> int:
    """获取窗口 DPI；失败回退 96。"""
    if sys.platform != "win32":
        return 96
    try:
        import ctypes

        if hwnd:
            return ctypes.windll.user32.GetDpiForWindow(hwnd) or 96
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi or 96
    except Exception:  # pragma: no cover
        return 96


def enumerate_windows(visible_only: bool = True) -> List[WindowInfo]:
    """枚举桌面顶层窗口，返回 WindowInfo 列表。"""
    win32gui, win32process, win32api = _require_win32()
    results: List[WindowInfo] = []

    def _callback(hwnd, _):
        if visible_only and not win32gui.IsWindowVisible(hwnd):
            return
        # 跳过无标题的零尺寸工具窗口，减少噪声
        if visible_only:
            if not win32gui.GetWindowText(hwnd).strip():
                return
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right - left <= 0 or bottom - top <= 0:
                return
        info = WindowInfo(
            hwnd=hwnd,
            title=win32gui.GetWindowText(hwnd),
            class_name=win32gui.GetClassName(hwnd),
            visible=win32gui.IsWindowVisible(hwnd),
        )
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            info.left, info.top, info.right, info.bottom = left, top, right, bottom
        except Exception:  # pragma: no cover
            pass
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            info.pid = pid
            handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)  # PROCESS_QUERY_LIMITED/READ
            info.exe_path = win32process.GetModuleFileNameEx(handle, 0)
            import os

            info._proc_name = os.path.basename(info.exe_path)  # type: ignore[attr-defined]
            win32api.CloseHandle(handle)
        except Exception:  # pragma: no cover - 权限/跨会话
            info._proc_name = ""  # type: ignore[attr-defined]
        info.dpi = get_dpi(hwnd)
        results.append(info)

    set_dpi_aware()
    win32gui.EnumWindows(_callback, None)
    return results


def _match_one(info: WindowInfo, title, class_name, process_name, exe_path) -> bool:
    if title is not None and title.lower() not in (info.title or "").lower():
        return False
    if class_name is not None and class_name.lower() != (info.class_name or "").lower():
        return False
    proc = getattr(info, "_proc_name", "") or ""
    if process_name is not None and process_name.lower() not in proc.lower():
        return False
    if exe_path is not None and info.exe_path and exe_path.lower() not in info.exe_path.lower():
        return False
    return True


def find_window(
    title: Optional[str] = None,
    class_name: Optional[str] = None,
    process_name: Optional[str] = None,
    exe_path: Optional[str] = None,
    visible_only: bool = True,
) -> int:
    """按 标题 / 类名 / 进程名 / 路径 模糊匹配，返回首个命中 HWND。

    匹配规则：提供的字段全部满足（AND）。找不到抛 WindowNotFoundError。
    """
    candidates = enumerate_windows(visible_only=visible_only)
    for info in candidates:
        if _match_one(info, title, class_name, process_name, exe_path):
            return info.hwnd
    raise WindowNotFoundError(
        "未找到窗口 title=%r class=%r proc=%r exe=%r"
        % (title, class_name, process_name, exe_path)
    )


def find_windows(
    title: Optional[str] = None,
    class_name: Optional[str] = None,
    process_name: Optional[str] = None,
    exe_path: Optional[str] = None,
    visible_only: bool = True,
) -> List[int]:
    """同 find_window 但返回全部匹配 HWND 列表。"""
    candidates = enumerate_windows(visible_only=visible_only)
    return [
        info.hwnd
        for info in candidates
        if _match_one(info, title, class_name, process_name, exe_path)
    ]
