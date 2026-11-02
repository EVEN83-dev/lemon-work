"""DXGI Desktop Duplication 直采（真机硬件路径）。

通过 ctypes 直接调用 DXGI / D3D11 COM 接口抓取整屏，
相比 BitBlt 不依赖窗口 DC、不受遮挡影响、对桌面合成更稳。
任何一步失败都上抛，由 capture.capture_screen 回退 BitBlt。

仅依赖系统 d3d11.dll / dxgi.dll（Windows 自带），无需第三方库。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from ctypes import (
    POINTER,
    byref,
    c_int,
    c_uint,
    c_ulong,
    c_ushort,
    c_void_p,
    c_uint64,
    c_longlong,
    c_uint8,
    c_ubyte,
    CFUNCTYPE,
    Structure,
    windll,
    cast,
    pointer,
)

from .exceptions import CaptureError, UnsupportedPlatformError


# ---------- GUID ----------
class GUID(Structure):
    _fields_ = [
        ("Data1", c_uint),
        ("Data2", c_ushort),
        ("Data3", c_ushort),
        ("Data4", c_ubyte * 8),
    ]

    def __init__(self, d1=0, d2=0, d3=0, d4=(0, 0, 0, 0, 0, 0, 0, 0)):
        super().__init__()
        self.Data1 = d1
        self.Data2 = d2
        self.Data3 = d3
        for i, v in enumerate(d4):
            self.Data4[i] = v


IID_IDXGIFactory1 = GUID(0x770AAE78, 0xF26F, 0x4DBA,
                         (0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
IID_IDXGIAdapter1 = GUID(0x29038F61, 0x3839, 0x4626,
                         (0x91, 0xFD, 0x08, 0x68, 0x79, 0x01, 0x1A, 0x05))
IID_IDXGIOutput = GUID(0xAE02EEDB, 0xC735, 0x4690,
                       (0x8D, 0x53, 0x97, 0x94, 0x21, 0x3F, 0x8A, 0xFA))
IID_ID3D11Device = GUID(0xDB6F6DDB, 0xAC9D, 0x4D3B,
                        (0xB6, 0x49, 0x2A, 0x1C, 0xF4, 0x21, 0xF5, 0x2C))
IID_ID3D11DeviceContext = GUID(0xC0BFA96C, 0xE089, 0x44FB,
                               (0x8C, 0xAC, 0xDA, 0xE3, 0x5C, 0x9A, 0x8D, 0xB1))
IID_ID3D11Texture2D = GUID(0x6F15AAF2, 0xD208, 0x4E89,
                           (0x9A, 0xB4, 0x48, 0x95, 0x35, 0xD3, 0x4F, 0x9C))
IID_IDXGIResource = GUID(0x035F3AB4, 0x482E, 0x4E50,
                         (0xB4, 0x1F, 0x8A, 0x7F, 0x8B, 0xDF, 0x1E, 0x21))
IID_IDXGISurface = GUID(0xCAFCB56C, 0x6AC3, 0x4889,
                        (0xBF, 0x47, 0x9E, 0x23, 0xA9, 0xA8, 0x58, 0x97))
IID_IDXGIOutputDuplication = GUID(0x191CFAC3, 0x0DCA, 0x4727,
                                  (0xAB, 0xA3, 0x86, 0x83, 0x9D, 0x72, 0x1E, 0x3B))


# ---------- 常量 ----------
D3D_DRIVER_TYPE_UNKNOWN = 0
D3D_DRIVER_TYPE_HARDWARE = 1
D3D_FEATURE_LEVEL_11_0 = 0xB000
D3D_FEATURE_LEVEL_11_1 = 0xB100
D3D11_CREATE_DEVICE_BGRA_SUPPORT = 0x20
D3D11_CREATE_DEVICE_SINGLETHREADED = 0x1
DXGI_MAP_READ = 1
DXGI_FORMAT_B8G8R8A8_UNORM = 87


# ---------- HRESULT 判定 ----------
def _SUCCEEDED(hr: int) -> bool:
    return (hr & 0x80000000) == 0


class DXGI_OUTDUPL_FRAME_INFO(Structure):
    _fields_ = [
        ("LastPresentTime", c_longlong),
        ("LastMouseUpdateTime", c_longlong),
        ("AccumulatedFrames", c_uint),
        ("RectsCoalesced", c_int),
        ("ProtectedContentMaskedOut", c_int),
    ]


class DXGI_MAPPED_RECT(Structure):
    _fields_ = [("Pitch", c_int), ("pBits", c_void_p)]


class D3D11_TEXTURE2D_DESC(Structure):
    _fields_ = [
        ("Width", c_uint),
        ("Height", c_uint),
        ("MipLevels", c_uint),
        ("ArraySize", c_uint),
        ("Format", c_uint),
        ("SampleDesc_Count", c_uint),
        ("SampleDesc_Quality", c_uint),
        ("Usage", c_uint),
        ("BindFlags", c_uint),
        ("CPUAccessFlags", c_uint),
        ("MiscFlags", c_uint),
    ]


def _vcall(obj, index, restype, argtypes, *args):
    """调用 COM 对象第 index 个虚表方法。obj 为 COM 指针（c_void_p）。"""
    vtable = cast(obj, POINTER(POINTER(c_void_p)))[0]
    func = cast(vtable[index], CFUNCTYPE(restype, c_void_p, *argtypes))
    return func(obj, *args)


def _query_interface(obj, iid: GUID) -> c_void_p:
    out = c_void_p()
    hr = _vcall(obj, 0, c_int,
                [POINTER(GUID), POINTER(c_void_p)],
                byref(iid), byref(out))
    if not _SUCCEEDED(hr):
        raise CaptureError("QueryInterface 失败 hr=0x%08X" % hr)
    return out


def capture_desktop_dxgi(monitor_index: int = 0) -> dict:
    """用 DXGI Desktop Duplication 抓取整屏。

    返回 dict：{width, height, bits(BGRA bytes), screen_left, screen_top, dpi}
    失败抛 CaptureError，由调用方回退。
    """
    if wt is None:
        raise UnsupportedPlatformError("仅支持 Windows")

    try:
        dxgi = windll.dxgi
        d3d11 = windll.d3d11
        ole32 = windll.ole32
    except Exception as exc:
        raise CaptureError("无法加载 dxgi/d3d11/ole32：%s" % exc)

    # 1) CoInitialize
    ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED

    factory = c_void_p()
    hr = dxgi.CreateDXGIFactory1(byref(IID_IDXGIFactory1), byref(factory))
    if not _SUCCEEDED(hr):
        raise CaptureError("CreateDXGIFactory1 失败 hr=0x%08X" % hr)

    # 2) 枚举适配器 / 输出
    adapter = c_void_p()
    output = None
    ai = 0
    while True:
        hr = _vcall(factory, 9, c_int, [c_uint, POINTER(c_void_p)], ai, byref(adapter))
        if not _SUCCEEDED(hr) or not adapter:
            break
        oi = 0
        while True:
            out = c_void_p()
            hr = _vcall(adapter, 7, c_int, [c_uint, POINTER(c_void_p)], oi, byref(out))
            if not _SUCCEEDED(hr) or not out:
                break
            if oi == monitor_index:
                output = out
                break
            _vcall(out, 2, None, [])  # Release
            oi += 1
        if output is not None:
            break
        _vcall(adapter, 2, None, [])
        ai += 1

    if output is None:
        raise CaptureError("未找到显示器输出 monitor_index=%d" % monitor_index)

    # 3) 创建 D3D11 设备
    driver_type = c_int(D3D_DRIVER_TYPE_UNKNOWN)
    flags = c_uint(D3D11_CREATE_DEVICE_BGRA_SUPPORT)
    feature_levels = (c_uint * 2)(D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0)
    fl_out = c_uint()
    device = c_void_p()
    ctx = c_void_p()
    hr = d3d11.D3D11CreateDevice(
        adapter, driver_type, None, flags,
        feature_levels, 2, 7,  # SDK version 7 (Win8+)
        byref(device), byref(fl_out), byref(ctx),
    )
    if not _SUCCEEDED(hr) or not device:
        raise CaptureError("D3D11CreateDevice 失败 hr=0x%08X" % hr)

    # 4) DuplicateOutput
    dup = c_void_p()
    hr = _vcall(output, 22, c_int, [c_void_p, POINTER(c_void_p)],
                device, byref(dup))
    if not _SUCCEEDED(hr) or not dup:
        raise CaptureError("DuplicateOutput 失败 hr=0x%08X（可能不支持或已被占用）" % hr)

    # 5) AcquireNextFrame
    frame_info = DXGI_OUTDUPL_FRAME_INFO()
    res = c_void_p()
    hr = _vcall(dup, 8, c_int,
                [c_uint, POINTER(DXGI_OUTDUPL_FRAME_INFO), POINTER(c_void_p)],
                500, byref(frame_info), byref(res))
    if not _SUCCEEDED(hr) or not res:
        raise CaptureError("AcquireNextFrame 失败 hr=0x%08X" % hr)

    # 6) 取纹理并 Map
    tex = _query_interface(res, IID_IDXGISurface)
    mapped = DXGI_MAPPED_RECT()
    hr = _vcall(tex, 8, c_int, [c_int, POINTER(DXGI_MAPPED_RECT)],
                DXGI_MAP_READ, byref(mapped))
    if not _SUCCEEDED(hr):
        raise CaptureError("IDXGISurface::Map 失败 hr=0x%08X" % hr)

    # 7) 读取纹理描述（宽高）
    desc = D3D11_TEXTURE2D_DESC()
    # ID3D11Resource::GetDesc 在索引 8（ID3D11DeviceChild 0-6, GetDevice7, GetDesc8）
    _vcall(res, 8, None, [POINTER(D3D11_TEXTURE2D_DESC)], byref(desc))
    w = int(desc.Width)
    h = int(desc.Height)

    pitch = mapped.Pitch
    bits_ptr = mapped.pBits
    # BGRA：每行 pitch 字节，取前 w*4
    row_bytes = w * 4
    buf = bytearray(row_bytes * h)
    for y in range(h):
        src = (ctypes.c_byte * row_bytes).from_address(bits_ptr + y * pitch)
        buf[y * row_bytes:(y + 1) * row_bytes] = bytes(src)

    # 8) 释放
    _vcall(tex, 9, c_int, [])  # Unmap
    _vcall(dup, 14, c_int, [])  # ReleaseFrame
    for p in (res, tex, dup, output, adapter, factory, device, ctx):
        if p:
            try:
                _vcall(p, 2, None, [])  # Release
            except Exception:
                pass
    ole32.CoUninitialize()

    return {
        "width": w,
        "height": h,
        "bits": bytes(buf),
        "screen_left": 0,
        "screen_top": 0,
        "dpi": 96,
        "method": "dxgi",
    }
