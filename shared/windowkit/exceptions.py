"""几维鸟物理级抓取基建：公共异常。

本模块零本地依赖，任何层级都可安全导入。
"""


class WindowKitError(Exception):
    """windowkit 基础异常。"""


class WindowNotFoundError(WindowKitError):
    """未找到匹配窗口。"""


class CaptureError(WindowKitError):
    """抓取失败。"""


class InputSimError(WindowKitError):
    """输入模拟失败。"""


class TemplateMatchError(WindowKitError):
    """模板匹配失败。"""


class WindowInvalidError(WindowKitError):
    """目标窗口句柄无效 / 不可见 / 被遮挡（经 _validate_window 检查未通过）。"""


class UnsupportedPlatformError(WindowKitError):
    """当前平台不支持该物理操作（仅 Windows 支持 win32 抓取/控制）。"""
