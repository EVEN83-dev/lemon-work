# -*- coding: utf-8 -*-
"""
Code Tools 插件
===============
提供代码相关的纯函数工具（无外部依赖）：
- code_stat:    统计代码（行数/注释/空行）
- indent_conv:  缩进 空格<->Tab 转换
- strip_comment: 移除行首/行尾注释（简单实现）
- char_rep:     查找替换字符
"""

import os
import sys
import re

_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from plugin_system import IPlugin, ToolDefinition


def _code_stat(text: str) -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    lines = text.splitlines()
    total = len(lines)
    blank = sum(1 for l in lines if not l.strip())
    comment = sum(1 for l in lines if l.strip().startswith(("#", "//", "/*", "*", "--")))
    code = total - blank - comment
    return {"ok": True, "total": total, "blank": blank, "comment": comment, "code": code}


def _indent_conv(text: str, to: str = "spaces", spaces: int = 4) -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    if to == "spaces":
        result = "\n".join(l.replace("\t", " " * max(1, int(spaces))) for l in text.splitlines())
    elif to == "tabs":
        result = "\n".join(l.replace(" " * max(1, int(spaces)), "\t") for l in text.splitlines())
    else:
        return {"ok": False, "error": f"未知方向: {to}"}
    return {"ok": True, "result": result}


def _strip_comment(text: str, mode: str = "strip_leading") -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    lines = text.splitlines()
    if mode == "strip_leading":
        out = [l for l in lines if not l.strip().startswith(("#", "//", "/*", "*", "--"))]
        return {"ok": True, "result": "\n".join(out)}
    if mode == "blank_only":
        return {"ok": True, "result": "\n".join(l for l in lines if l.strip())}
    return {"ok": False, "error": f"未知模式: {mode}"}


def _char_rep(text: str, old: str, new: str) -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    if not old:
        return {"ok": False, "error": "缺少被替换字符"}
    result = text.replace(old, new)
    return {"ok": True, "result": result, "count": text.count(old)}


class CodeToolsPlugin(IPlugin):
    """代码处理工具集合"""

    @property
    def name(self) -> str:
        return "code_tools"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "代码统计/缩进转换/注释清理/字符替换工具"

    @property
    def icon(self) -> str:
        return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>'''

    def on_load(self) -> bool:
        return True

    def on_unload(self):
        pass

    def get_tools(self):
        return [
            ToolDefinition(
                name="code_stat",
                description="统计代码行数（总行/空行/注释/代码）",
                parameters=[{"name": "text", "type": "string", "description": "代码文本"}],
                handler=self._t_stat, category="code",
            ),
            ToolDefinition(
                name="indent_conv",
                description="缩进空格与Tab互转",
                parameters=[
                    {"name": "text", "type": "string", "description": "代码文本"},
                    {"name": "to", "type": "string", "description": "spaces/tabs"},
                    {"name": "spaces", "type": "integer", "description": "每级空格数"},
                ],
                handler=self._t_indent, category="code",
            ),
            ToolDefinition(
                name="strip_comment",
                description="移除注释行或空行",
                parameters=[
                    {"name": "text", "type": "string", "description": "代码文本"},
                    {"name": "mode", "type": "string", "description": "strip_leading/blank_only"},
                ],
                handler=self._t_strip, category="code",
            ),
            ToolDefinition(
                name="char_rep",
                description="批量字符替换",
                parameters=[
                    {"name": "text", "type": "string", "description": "文本"},
                    {"name": "old", "type": "string", "description": "旧字符"},
                    {"name": "new", "type": "string", "description": "新字符"},
                ],
                handler=self._t_rep, category="code",
            ),
        ]

    def _t_stat(self, **kw): return _code_stat(kw.get("text", ""))
    def _t_indent(self, **kw): return _indent_conv(kw.get("text", ""), kw.get("to", "spaces"), kw.get("spaces", 4))
    def _t_strip(self, **kw): return _strip_comment(kw.get("text", ""), kw.get("mode", "strip_leading"))
    def _t_rep(self, **kw): return _char_rep(kw.get("text", ""), kw.get("old", ""), kw.get("new", ""))
