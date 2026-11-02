# -*- coding: utf-8 -*-
"""
内置插件包
==========

本包内每个 .py 文件都是一个独立的 IPlugin 实现。
PluginManager.discover_plugins() 会自动扫描本目录并加载所有插件。

注意：每个插件文件使用绝对导入 (from plugin_system import ...)，
因为它们既可能作为包成员被导入，也可能被 load_plugin() 作为独立模块加载。

可用插件：
- markdown_preview: Markdown 实时预览
- json_formatter:   JSON 格式化和校验
- color_picker:     颜色选择器工具
- regex_tester:     正则表达式测试工具
- base64_tool:      Base64 编解码
"""

# 包级别导出（仅在作为包导入时生效，独立加载时不执行）
__all__ = [
    "MarkdownPreviewPlugin",
    "JsonFormatterPlugin",
    "ColorPickerPlugin",
    "RegexTesterPlugin",
    "Base64ToolPlugin",
]

try:
    from .markdown_preview import MarkdownPreviewPlugin  # noqa: F401
    from .json_formatter import JsonFormatterPlugin      # noqa: F401
    from .color_picker import ColorPickerPlugin          # noqa: F401
    from .regex_tester import RegexTesterPlugin          # noqa: F401
    from .base64_tool import Base64ToolPlugin            # noqa: F401
except ImportError:
    # 独立模块加载模式下，相对导入不可用，此处忽略
    pass
