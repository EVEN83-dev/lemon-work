"""shared/windowkit —— 几维鸟物理级外部软件抓取与控制底座。

设计原则（铁律）：
- 绝不 FindWindowEx 深入控件内部；
- 绝不读取私有内存 / 私有 API；
- 所有定位只来自：像素 + 模板匹配 + 视觉模型。

该底座同时被 几维鸟(vizboard) 与 咩咩(miemie) 共用。
所有平台相关依赖（pywin32 / opencv / numpy）均为惰性导入，
在缺失依赖或 Linux/macOS 平台下导入本包不会崩溃，仅对应能力不可用。
"""

from .exceptions import (
    CaptureError,
    InputSimError,
    TemplateMatchError,
    UnsupportedPlatformError,
    WindowKitError,
    WindowNotFoundError,
)
from .models import ControlNode, WindowKitInterface, StubWindowKit, RealWindowKit

__all__ = [
    "CaptureError",
    "InputSimError",
    "TemplateMatchError",
    "UnsupportedPlatformError",
    "WindowKitError",
    "WindowNotFoundError",
    "is_windows",
    "ControlNode",
    "WindowKitInterface",
    "StubWindowKit",
    "RealWindowKit",
]


def is_windows() -> bool:
    """是否运行在 Windows 平台。"""
    import sys

    return sys.platform == "win32"
