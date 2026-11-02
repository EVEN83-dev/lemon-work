# -*- coding: utf-8 -*-
"""
Base64 Tool 插件
================
提供 Base64 编解码工具：
- base64_encode: 编码（文本或二进制）
- base64_decode: 解码
- base64_file:   文件 Base64 编码

无外部依赖。
"""

import os
import sys
import base64

_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from plugin_system import IPlugin, ToolDefinition, HookPoint, SkillDefinition


def _b64_encode(text: str, encoding: str = "utf-8") -> dict:
    """Base64 编码"""
    if text is None:
        return {"ok": False, "error": "空输入"}
    try:
        data = text.encode(encoding)
        encoded = base64.b64encode(data).decode("ascii")
        return {
            "ok": True,
            "encoded": encoded,
            "original_size": len(data),
            "encoded_size": len(encoded),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _b64_decode(b64_str: str, encoding: str = "utf-8") -> dict:
    """Base64 解码"""
    if not b64_str:
        return {"ok": False, "error": "空输入"}
    # 清理空白和换行
    cleaned = b64_str.replace("\n", "").replace("\r", "").replace(" ", "").strip()
    try:
        data = base64.b64decode(cleaned, validate=True)
    except Exception:
        # 宽松模式：自动填充 padding
        try:
            padding = 4 - len(cleaned) % 4
            if padding != 4:
                cleaned += "=" * padding
            data = base64.b64decode(cleaned)
        except Exception as e:
            return {"ok": False, "error": f"Base64 解码失败: {e}"}
    # 尝试以指定编码解码为文本
    try:
        text = data.decode(encoding)
        return {
            "ok": True,
            "decoded": text,
            "is_text": True,
            "original_size": len(data),
        }
    except UnicodeDecodeError:
        # 二进制数据
        return {
            "ok": True,
            "decoded_hex": data.hex(),
            "is_text": False,
            "original_size": len(data),
        }


def _b64_encode_file(file_path: str) -> dict:
    """文件 Base64 编码"""
    if not file_path or not os.path.isfile(file_path):
        return {"ok": False, "error": f"文件不存在: {file_path}"}
    try:
        file_size = os.path.getsize(file_path)
        # 限制 10MB
        if file_size > 10 * 1024 * 1024:
            return {"ok": False, "error": "文件过大（>10MB），拒绝编码"}
        with open(file_path, "rb") as f:
            data = f.read()
        encoded = base64.b64encode(data).decode("ascii")
        return {
            "ok": True,
            "encoded": encoded,
            "file_path": file_path,
            "file_size": file_size,
            "encoded_size": len(encoded),
            "mime_guess": _guess_mime(file_path),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _guess_mime(file_path: str) -> str:
    """简单的 MIME 类型猜测"""
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".txt": "text/plain", ".md": "text/markdown",
        ".json": "application/json", ".xml": "application/xml",
        ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".svg": "image/svg+xml",
        ".pdf": "application/pdf", ".zip": "application/zip",
        ".py": "text/x-python", ".java": "text/x-java",
    }
    return mime_map.get(ext, "application/octet-stream")


class Base64ToolPlugin(IPlugin):
    """Base64 编解码插件"""

    @property
    def name(self) -> str:
        return "base64_tool"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Base64 编解码工具（支持文本和文件）"

    @property
    def icon(self) -> str:
        return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'''

    def on_load(self) -> bool:
        return True

    def on_unload(self):
        pass

    def get_tools(self):
        return [
            ToolDefinition(
                name="base64_encode",
                description="Base64 编码文本",
                parameters=[
                    {"name": "text", "type": "string", "description": "待编码文本"},
                    {"name": "encoding", "type": "string", "description": "文本编码（默认 utf-8）"},
                ],
                handler=self._tool_encode,
                category="encoding",
            ),
            ToolDefinition(
                name="base64_decode",
                description="Base64 解码",
                parameters=[
                    {"name": "b64", "type": "string", "description": "Base64 字符串"},
                    {"name": "encoding", "type": "string", "description": "文本编码（默认 utf-8）"},
                ],
                handler=self._tool_decode,
                category="encoding",
            ),
            ToolDefinition(
                name="base64_encode_file",
                description="将文件编码为 Base64",
                parameters=[
                    {"name": "file_path", "type": "string", "description": "文件路径"},
                ],
                handler=self._tool_encode_file,
                category="encoding",
            ),
        ]

    def get_hooks(self):
        return {}

    def get_skills(self):
        return [
            SkillDefinition(
                name="base64_tool",
                description="Base64 编解码技能",
                version="1.0.0",
                author="mimo_agent",
            )
        ]

    # ===== Tool handlers =====
    def _tool_encode(self, **kwargs):
        text = kwargs.get("text", "")
        encoding = kwargs.get("encoding", "utf-8")
        return _b64_encode(text, encoding=encoding)

    def _tool_decode(self, **kwargs):
        b64 = kwargs.get("b64", "")
        encoding = kwargs.get("encoding", "utf-8")
        return _b64_decode(b64, encoding=encoding)

    def _tool_encode_file(self, **kwargs):
        file_path = kwargs.get("file_path", "")
        return _b64_encode_file(file_path)
