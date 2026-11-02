# -*- coding: utf-8 -*-
"""
Format Convert 插件
===================
格式转换工具（纯标准库）：
- csv_convert:    TSV/Tab 分隔 -> CSV
- base_convert:   数字进制转换（2/8/10/16）
- xml_pretty:     XML 简单缩进美化
- word_count:     字数统计（总字符/单词/行）
"""

import os
import sys
import csv
import io
import re

_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from plugin_system import IPlugin, ToolDefinition


def _csv_convert(text: str, delimiter: str = "\t") -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    try:
        rows = [r for r in csv.reader(text.splitlines(), delimiter=delimiter)]
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerows(rows)
        return {"ok": True, "result": out.getvalue().strip(), "rows": len(rows)}
    except Exception as e:
        return {"ok": False, "error": f"转换失败: {e}"}


def _base_convert(value: str, source_base: int = 10, target_base: int = 16) -> dict:
    if not value:
        return {"ok": False, "error": "空输入"}
    try:
        decimal = int(str(value), int(source_base))
        digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if int(target_base) < 2 or int(target_base) > 36:
            return {"ok": False, "error": "进制需在 2-36 之间"}
        if decimal == 0:
            return {"ok": True, "result": "0", "decimal": 0}
        neg = decimal < 0
        decimal = abs(decimal)
        result = ""
        base = int(target_base)
        while decimal > 0:
            result = digits[decimal % base] + result
            decimal //= base
        if neg:
            result = "-" + result
        return {"ok": True, "result": result, "decimal": int(str(value), int(source_base))}
    except (ValueError, TypeError):
        return {"ok": False, "error": "无效输入或进制"}


def _xml_pretty(text: str) -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    try:
        # 简单实现：为每层 > 元素添加缩进
        text = re.sub(r">\s+<", "><", text.strip())
        depth = 0
        pretty = ""
        i = 0
        while i < len(text):
            ch = text[i]
            if text.startswith("</", i):
                depth -= 1
                pretty += "\n" + "  " * max(0, depth) + "</"
                i += 2
                while i < len(text) and text[i] != ">":
                    pretty += text[i]; i += 1
                if i < len(text):
                    pretty += text[i]; i += 1
            elif text.startswith("<?", i) or text.startswith("<!", i):
                while i < len(text) and text[i] != ">":
                    pretty += text[i]; i += 1
                if i < len(text):
                    pretty += text[i]; i += 1
                pretty += "\n"
            elif text.startswith("</", i) is False and text[i] == "<" and not text.startswith("<![CDATA[", i):
                # 开始标签（可能自闭合）
                if text.startswith("<![CDATA[", i):
                    pretty += text[i]; i += 1
                    continue
                pretty += "\n" + "  " * depth + "<"
                i += 1
                self_closing = False
                while i < len(text) and text[i] != ">":
                    if text[i] == "/" and i + 1 < len(text) and text[i + 1] == ">":
                        self_closing = True
                    pretty += text[i]; i += 1
                if i < len(text):
                    pretty += text[i]; i += 1
                if not self_closing and not text[max(0, i - 1):i].startswith("/"):
                    depth += 1
            else:
                pretty += ch
                i += 1
        return {"ok": True, "result": pretty}
    except Exception as e:
        return {"ok": False, "error": f"XML 格式化失败: {e}"}


def _word_count(text: str) -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    words = re.findall(r"\S+", text)
    return {
        "ok": True,
        "chars": len(text),
        "words": len(words),
        "lines": len(text.splitlines()),
        "non_space_chars": len(re.sub(r"\s", "", text)),
    }


class FormatConvertPlugin(IPlugin):
    """格式转换工具集合"""

    @property
    def name(self) -> str:
        return "format_convert"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "格式转换：CSV/进制/XML美化/字数统计"

    @property
    def icon(self) -> str:
        return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3h4v4h-4z"/><path d="M3 17h4v4H3z"/><path d="M7 19l5-5 3 3 5-5"/></svg>'''

    def on_load(self) -> bool:
        return True

    def on_unload(self):
        pass

    def get_tools(self):
        return [
            ToolDefinition(
                name="csv_convert",
                description="将分隔文本转为 CSV",
                parameters=[
                    {"name": "text", "type": "string", "description": "文本"},
                    {"name": "delimiter", "type": "string", "description": "源分隔符（默认Tab）"},
                ],
                handler=self._t_csv, category="format",
            ),
            ToolDefinition(
                name="base_convert",
                description="数字进制转换（2/8/10/16等）",
                parameters=[
                    {"name": "value", "type": "string", "description": "数值字符串"},
                    {"name": "source_base", "type": "integer", "description": "源进制"},
                    {"name": "target_base", "type": "integer", "description": "目标进制"},
                ],
                handler=self._t_base, category="format",
            ),
            ToolDefinition(
                name="xml_pretty",
                description="XML 简单缩进美化",
                parameters=[{"name": "text", "type": "string", "description": "XML 文本"}],
                handler=self._t_xml, category="format",
            ),
            ToolDefinition(
                name="word_count",
                description="统计字数（字符/单词/行）",
                parameters=[{"name": "text", "type": "string", "description": "文本"}],
                handler=self._t_wc, category="format",
            ),
        ]

    def _t_csv(self, **kw): return _csv_convert(kw.get("text", ""), kw.get("delimiter", "\t"))
    def _t_base(self, **kw): return _base_convert(kw.get("value", ""), kw.get("source_base", 10), kw.get("target_base", 16))
    def _t_xml(self, **kw): return _xml_pretty(kw.get("text", ""))
    def _t_wc(self, **kw): return _word_count(kw.get("text", ""))
