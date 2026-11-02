"""屏幕/窗口抓取。

策略（抗版本失效）：
1. 优先 Desktop Duplication API（DXGI）——对桌面/全屏；
2. 窗口内容优先 BitBlt（设备上下文拷贝，最稳）；
3. 回退 PrintWindow（可抓被遮挡/最小化窗口的客户区）。

不读取任何进程私有内存，只从显示输出取像素。
输出统一封装为 CaptureResult，可惰性转为 numpy / PIL / 存盘。
"""

from __future__ import annotations

import os
import sys
import time
import zlib
import struct
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .exceptions import CaptureError, UnsupportedPlatformError
from .window_enum import get_dpi, set_dpi_aware


@dataclass
class CaptureResult:
    """一次抓取结果。像素缓冲惰性解析，避免无依赖时强制报错。"""

    width: int
    height: int
    # 屏幕物理坐标（左上角），逻辑层据此定位
    screen_left: int
    screen_top: int
    dpi: int
    _bits: bytes = b""          # BGRA raw bytes (from win32ui)
    _array: object = None       # numpy BGR array（缓存）
    method: str = "bitblt"

    def numpy(self):
        """返回 numpy BGR 数组（需 numpy）。"""
        if self._array is not None:
            return self._array
        import numpy as np

        arr = np.frombuffer(self._bits, dtype=np.uint8)
        arr = arr.reshape((self.height, self.width, 4))
        # BGRA -> BGR
        self._array = arr[:, :, :3].copy()
        return self._array

    def pil(self):
        """返回 PIL.Image（RGB）。"""
        import numpy as np
        from PIL import Image

        bgr = self.numpy()
        return Image.fromarray(np.ascontiguousarray(bgr[:, :, ::-1]))

    def save(self, path: str, fmt: str = None) -> str:
        """保存到文件。

        fmt 可显式指定扩展名对应的格式（"png"/"webp"/"jpg"）；未指定时按 path 后缀推断。
        WebP 体积通常比 PNG 小 ~60%（D-T01）。

        优先用 OpenCV，其次 Pillow，最后纯 Python PNG（仅 PNG，无第三方依赖时）。
        """
        if fmt is None:
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            fmt = ext or "png"
        try:
            import cv2

            if fmt == "webp":
                # OpenCV 默认 webp 质量为 95；显式编码参数控制体积
                cv2.imwrite(path, self.numpy(), [int(cv2.IMWRITE_WEBP_QUALITY), 90])
            else:
                cv2.imwrite(path, self.numpy())
            return path
        except Exception:
            pass
        try:
            img = self.pil()
            img.save(path, format=fmt.upper() if fmt != "jpg" else "JPEG")
            return path
        except Exception:
            pass
        # 纯 Python 仅支持 PNG 兜底
        if fmt in ("png", "png"):
            return _write_png(path, self.numpy())
        raise CaptureError("无第三方库且目标格式非 PNG：%s" % fmt)

    def save_webp(self, path: str) -> str:
        """直接保存为 WebP（D-T01：体积更小）。"""
        return self.save(path, fmt="webp")

    def save_png(self, path: str) -> str:
        """无论是否安装第三方库，都用纯 Python 写出 RGBA PNG。"""
        return _write_png(path, self.numpy())

    def size(self) -> tuple:
        return (self.width, self.height)


def _require_gdi():
    if sys.platform != "win32":
        raise UnsupportedPlatformError("capture 仅支持 Windows 平台")
    try:
        import win32gui
        import win32ui
        import win32con
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedPlatformError("缺少 pywin32：%s" % exc)
    return win32gui, win32ui, win32con


def capture_window(
    hwnd: int,
    client_only: bool = False,
    method: str = "auto",
) -> CaptureResult:
    """抓取指定窗口像素。

    method:
      - "bitblt"      : 走 BitBlt（默认，窗口可见时最佳）
      - "printwindow" : 走 PrintWindow（可见性不佳/被遮挡时）
      - "auto"        : BitBlt 失败自动回退 PrintWindow
    """
    win32gui, win32ui, win32con = _require_gdi()
    set_dpi_aware()

    if client_only:
        left, top = win32gui.ClientToScreen(hwnd, (0, 0))
        cr = win32gui.GetClientRect(hwnd)
        w, h = cr[2] - cr[0], cr[3] - cr[1]
    else:
        r = win32gui.GetWindowRect(hwnd)
        left, top, right, bottom = r
        w, h = right - left, bottom - top

    if w <= 0 or h <= 0:
        raise CaptureError("窗口尺寸非法：%dx%d" % (w, h))

    bits, used = _grab_bitmap(win32gui, win32ui, win32con, hwnd, w, h, method)
    return CaptureResult(
        width=w,
        height=h,
        screen_left=left,
        screen_top=top,
        dpi=get_dpi(hwnd),
        _bits=bits,
        method=used,
    )


def _grab_bitmap(win32gui, win32ui, win32con, hwnd, w, h, method):
    """核心抓取：BitBlt / PrintWindow。返回 (bytes, 实际方法)。"""
    last_err: Optional[Exception] = None

    def _bitblt():
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)
        bits = bmp.GetBitmapBits(True)
        # 释放
        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return bits

    def _printwindow():
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        hdc = save_dc.GetSafeHdc()
        # pywin32 的 win32gui.PrintWindow 在部分构建不存在，用 ctypes 直接调 user32
        if hasattr(win32gui, "PrintWindow"):
            win32gui.PrintWindow(hwnd, hdc, 0x2)  # PW_RENDERFULLCONTENT
        else:
            import ctypes
            PW_RENDERFULLCONTENT = 0x2
            if not ctypes.windll.user32.PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT):
                raise CaptureError("PrintWindow 返回 0")
        bits = bmp.GetBitmapBits(True)
        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return bits

    def _is_black(bits: bytes) -> bool:
        if not bits:
            return True
        import numpy as np
        arr = np.frombuffer(bits, dtype=np.uint8)
        return int(arr.sum()) == 0 or np.max(arr) < 8

    bits, used = None, None
    if method in ("auto", "bitblt"):
        try:
            bits, used = _bitblt(), "bitblt"
        except Exception as exc:  # pragma: no cover - 运行时回退
            last_err = exc
    # auto 模式下 BitBlt 返回纯黑（UWP/合成层常见），尝试 PrintWindow
    if method in ("auto", "printwindow"):
        if method == "printwindow" or bits is None or _is_black(bits):
            try:
                bits, used = _printwindow(), "printwindow"
            except Exception as exc:  # pragma: no cover
                last_err = exc
    if bits is not None:
        return bits, used
    raise CaptureError("抓取失败：%s" % last_err)


def capture_screen(monitor_index: int = 0, screen_id: int = 0, scale: float = 1.0) -> CaptureResult:
    """抓取整屏（按显示器索引 / screen_id）。

    优先级：DXGI Desktop Duplication（硬件直采）→ 全屏 BitBlt 兜底。
    scale（D-T01，DPI 缩放适配）：仅对兜底 BitBlt 路径生效，1.0=物理像素，
    2.0=取 2 倍尺寸（高 DPI 屏上抓更清晰）；DXGI 路径忽略该参数（硬件已按物理像素）。
    """
    idx = monitor_index if monitor_index else screen_id
    try:
        from .dxgi_capture import capture_desktop_dxgi
        return capture_desktop_dxgi(idx)
    except Exception as dxgi_err:
        return _desktop_bitblt(idx, dxgi_err, scale=scale)


def enumerate_screens() -> List[dict]:
    """枚举所有显示器（D-T01，多显示器支持）。

    返回每个显示器的描述 dict：
      {"screen_id": 0, "left": int, "top": int,
       "width": int, "height": int, "dpi": int,
       "is_primary": bool}

    screen_id 与 capture_screen(screen_id=N) 的索引对齐。非 Windows 平台返回空列表。
    """
    if sys.platform != "win32":
        return []
    import ctypes

    try:
        MONITORINFOF_PRIMARY = 0x1

        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class _MONITORINFOEX(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong),
                        ("rcMonitor", _RECT), ("rcWork", _RECT),
                        ("dwFlags", ctypes.c_ulong),
                        ("szDevice", ctypes.c_wchar * 32)]

        screens: List[dict] = []
        sid = [0]

        def _cb(hmon, hdc, rect, lparam):
            info = _MONITORINFOEX()
            info.cbSize = ctypes.sizeof(_MONITORINFOEX)
            ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))
            r = info.rcMonitor
            dpi = get_dpi_for_monitor(hmon)
            screens.append({
                "screen_id": sid[0],
                "left": r.left,
                "top": r.top,
                "width": r.right - r.left,
                "height": r.bottom - r.top,
                "dpi": dpi,
                "is_primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
            })
            sid[0] += 1
            return 1

        _MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(_RECT), ctypes.c_double)
        ctypes.windll.user32.EnumDisplayMonitors(0, 0, _MonitorEnumProc(_cb), 0)
        return screens
    except Exception:  # noqa: BLE001 - 枚举失败兜底空列表
        return []


def get_dpi_for_monitor(hmon) -> int:
    """按显示器句柄取 DPI（Win8.1+）；失败回退 96。"""
    try:
        import ctypes

        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        MDT_EFFECTIVE_DPI = 0
        res = ctypes.windll.shcore.GetDpiForMonitor(hmon, MDT_EFFECTIVE_DPI,
                                                    ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        if res == 0:
            return int(dpi_x.value) or 96
    except Exception:  # noqa: BLE001
        pass
    return 96


def _desktop_bitblt(monitor_index: int = 0, dxgi_err: Exception = None, scale: float = 1.0) -> CaptureResult:
    """全屏 BitBlt 兜底（DXGI 不可用时的回退路径）。

    scale>1.0 时对抓取尺寸做整数倍放大（高 DPI 屏清晰化，D-T01）。
    """
    if dxgi_err is not None:
        pass  # 仅用于日志/调试，此处保留链路
    win32gui, win32ui, win32con = _require_gdi()
    set_dpi_aware()
    import ctypes

    sm_xvirt = 76
    sm_yvirt = 77
    w = ctypes.windll.user32.GetSystemMetrics(sm_xvirt)
    h = ctypes.windll.user32.GetSystemMetrics(sm_yvirt)
    if scale and scale != 1.0:
        w = max(1, int(w * scale))
        h = max(1, int(h * scale))
    return _grab_full(win32ui, win32con, w, h)


def _grab_full(win32ui, win32con, w, h) -> CaptureResult:
    hwnd = 0
    import win32gui

    hdesktop = win32gui.GetDesktopWindow()
    hwnd_dc = win32gui.GetWindowDC(hdesktop)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bmp)
    save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)
    bits = bmp.GetBitmapBits(True)
    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hdesktop, hwnd_dc)
    return CaptureResult(
        width=w,
        height=h,
        screen_left=0,
        screen_top=0,
        dpi=96,
        _bits=bits,
        method="desktop_bitblt",
    )


def _desktop_duplication(monitor_index: int = 0) -> CaptureResult:
    """Desktop Duplication API（DXGI）—— 委托给 dxgi_capture 模块。

    新代码请直接用 capture_screen()，已内置 DXGI 优先 + BitBlt 回退。
    此函数保留仅为向后兼容。
    """
    from .dxgi_capture import capture_desktop_dxgi
    raw = capture_desktop_dxgi(monitor_index)
    return CaptureResult(
        width=raw["width"],
        height=raw["height"],
        screen_left=raw.get("screen_left", 0),
        screen_top=raw.get("screen_top", 0),
        dpi=raw.get("dpi", 96),
        _bits=raw["bits"],
        method=raw.get("method", "dxgi"),
    )


def _write_png(path: str, arr) -> str:
    """纯 Python 写出 RGB PNG（不依赖 Pillow / OpenCV）。

    arr 为 numpy BGR 数组，或任意可 reshape 的 bytes/bytearray。
    """
    import numpy as np

    arr = np.asarray(arr)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        # BGR -> RGB
        h, w = arr.shape[:2]
        rgb = arr[:, :, ::-1].astype(np.uint8)
    else:
        h, w = arr.shape[:2]
        rgb = np.asarray(arr, dtype=np.uint8).reshape((h, w))

    raw = bytearray()
    for y in range(h):
        raw.append(0)  # 每行 filter type 0（无过滤）
        raw.extend(rgb[y].tobytes())

    compressed = zlib.compress(bytes(raw), 9)

    def _chunk(typ: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit, RGB
    with open(path, "wb") as f:
        f.write(sig)
        f.write(_chunk(b"IHDR", ihdr))
        f.write(_chunk(b"IDAT", compressed))
        f.write(_chunk(b"IEND", b""))
    return path


def capture_windows(hwnds: List[int], client_only: bool = False,
                   max_workers: int = 4, retries: int = 1) -> List["CaptureResult"]:
    """并行抓取多个窗口（D-T02）。

    线程池并行截图（max_workers=4），单个失败重试一次，仍失败则该位置返回 None。
    返回的列表与输入 hwnds 一一对应，便于调用方按索引回查。

    多窗口场景（如跨窗协调 / 多显示器对照）用此接口可显著缩短总抓取耗时。
    """
    from concurrent.futures import ThreadPoolExecutor

    def _one(hwnd: int) -> Optional["CaptureResult"]:
        last_exc: Optional[Exception] = None
        for attempt in range(max(1, retries + 1)):
            try:
                return capture_window(hwnd, client_only=client_only)
            except Exception as exc:  # noqa: BLE001 - 重试
                last_exc = exc
                time.sleep(0.1)
        if last_exc is not None:
            _logger_wrap("capture_windows 窗口 %s 抓取失败：%s" % (hwnd, last_exc))
        return None

    results: List[Optional["CaptureResult"]] = [None] * len(hwnds)
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(hwnds) or 1))) as ex:
        fut_map = {ex.submit(_one, h): i for i, h in enumerate(hwnds)}
        for fut in fut_map:
            i = fut_map[fut]
            try:
                results[i] = fut.result()
            except Exception:  # noqa: BLE001 - 理论上 _one 已吞异常
                results[i] = None
    return results


def _logger_wrap(msg: str) -> None:
    try:
        logging.getLogger("windowkit.capture").warning(msg)
    except Exception:
        pass


def capture_region(left: int, top: int, width: int, height: int) -> CaptureResult:
    """抓取屏幕指定矩形区域（物理像素）。"""
    win32gui, win32ui, win32con = _require_gdi()
    set_dpi_aware()
    hdesktop = win32gui.GetDesktopWindow()
    hwnd_dc = win32gui.GetWindowDC(hdesktop)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bmp)
    save_dc.BitBlt((0, 0), (width, height), mfc_dc, (left, top), win32con.SRCCOPY)
    bits = bmp.GetBitmapBits(True)
    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hdesktop, hwnd_dc)
    return CaptureResult(
        width=width,
        height=height,
        screen_left=left,
        screen_top=top,
        dpi=96,
        _bits=bits,
        method="region_bitblt",
    )
