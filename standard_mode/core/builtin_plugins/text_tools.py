# -*- coding: utf-8 -*-
"""
Text Tools 插件
===============
提供常用文本处理工具（纯标准库，无外部依赖）：
- text_case:     大小写转换（upper/lower/title/camel/snake/kebab）
- text_trim:     去除首尾空白 / 多余空行
- text_lines:    行号标注 / 去重 / 排序 / 倒序
- uuid_gen:      生成 UUID（v4 或 v4-uppercase）
- unix_ts:       时间戳 ↔ 日期时间互转
- url_encode:    URL 编解码
- base64_wrap:   Base64 编码/解码（文件大小限制）
- hash_sum:      计算字符串哈希（md5/sha1/sha256）
"""

import os
import sys
import json
import time
import uuid
import hashlib
import base64
import urllib.parse

_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from plugin_system import IPlugin, ToolDefinition


# ============================================================
# 纯函数实现
# ============================================================

def _convert_case(text: str, mode: str = "upper") -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    import re
    if mode == "upper":
        return {"ok": True, "result": text.upper()}
    if mode == "lower":
        return {"ok": True, "result": text.lower()}
    if mode == "title":
        return {"ok": True, "result": text.title()}
    if mode == "camel":
        parts = re.split(r"[\s_\-]+", text.strip().lower())
        return {"ok": True, "result": parts[0] + "".join(p.capitalize() for p in parts[1:])}
    if mode == "snake":
        s = re.sub(r"[-\s]+", "_", text.strip().lower())
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
        return {"ok": True, "result": s.lower()}
    if mode == "kebab":
        s = re.sub(r"[\s_]+", "-", text.strip().lower())
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s)
        return {"ok": True, "result": s.lower()}
    return {"ok": False, "error": f"未知模式: {mode}"}


def _process_lines(text: str, action: str = "numbered", reverse: bool = False) -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    lines = text.splitlines()
    if action == "numbered":
        result = "\n".join(f"{i+1:>4}  {l}" for i, l in enumerate(lines))
    elif action == "dedupe":
        seen, result_lines = set(), []
        for l in lines:
            if l not in seen:
                seen.add(l)
                result_lines.append(l)
        result = "\n".join(result_lines)
    elif action == "sort":
        result = "\n".join(sorted(lines, reverse=reverse))
    elif action == "reverse":
        result = "\n".join(reversed(lines))
    elif action == "trim_blank":
        result = "\n".join(l for l in lines if l.strip())
    else:
        return {"ok": False, "error": f"未知操作: {action}"}
    return {"ok": True, "result": result, "lines": len(lines)}


def _gen_uuid(n: int = 1, upper: bool = False) -> dict:
    n = max(1, min(int(n), 100))
    result = []
    for _ in range(n):
        u = str(uuid.uuid4())
        if upper:
            u = u.upper()
        result.append(u)
    return {"ok": True, "uuids": result, "count": n}


def _ts_convert(value: str = "", to: str = "iso") -> dict:
    """时间戳 ↔ ISO/本地时间互转。to=iso: 时间戳->ISO; to=ts: 时间->时间戳"""
    import datetime
    if to == "iso":
        try:
            ts = float(value) if value else time.time()
            dt = datetime.datetime.fromtimestamp(ts)
            return {"ok": True, "iso": dt.isoformat(), "local": dt.strftime("%Y-%m-%d %H:%M:%S"), "ts": int(ts)}
        except (ValueError, OSError):
            return {"ok": False, "error": "无效时间戳"}
    if to == "ts":
        try:
            if value:
                dt = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            else:
                dt = datetime.datetime.now()
            return {"ok": True, "ts": int(dt.timestamp()), "iso": dt.isoformat()}
        except ValueError:
            return {"ok": False, "error": "无效时间格式（应为 YYYY-MM-DD HH:MM:SS）"}
    return {"ok": False, "error": f"未知转换: {to}"}


def _url_convert(text: str, mode: str = "encode") -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    if mode == "encode":
        return {"ok": True, "result": urllib.parse.quote(text, safe="")}
    if mode == "decode":
        return {"ok": True, "result": urllib.parse.unquote(text)}
    return {"ok": False, "error": f"未知模式: {mode}"}


def _b64_convert(text: str = "", mode: str = "encode") -> dict:
    if mode == "encode":
        return {"ok": True, "result": base64.b64encode(text.encode("utf-8")).decode("ascii")}
    if mode == "decode":
        try:
            return {"ok": True, "result": base64.b64decode(text).decode("utf-8")}
        except Exception as e:
            return {"ok": False, "error": f"解码失败: {e}"}
    return {"ok": False, "error": f"未知模式: {mode}"}


def _hash_sum(text: str, algorithm: str = "md5") -> dict:
    if not text:
        return {"ok": False, "error": "空输入"}
    data = text.encode("utf-8")
    if algorithm == "md5":
        return {"ok": True, "result": hashlib.md5(data).hexdigest()}
    if algorithm == "sha1":
        return {"ok": True, "result": hashlib.sha1(data).hexdigest()}
    if algorithm == "sha256":
        return {"ok": True, "result": hashlib.sha256(data).hexdigest()}
    return {"ok": False, "error": f"未知算法: {algorithm}"}


# ============================================================
# 插件主类
# ============================================================

class TextToolsPlugin(IPlugin):
    """常用文本处理工具集合"""

    @property
    def name(self) -> str:
        return "text_tools"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "常用文本工具：大小写/行处理/UUID/时间戳/URL/Base64/哈希"

    @property
    def icon(self) -> str:
        return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/></svg>'''

    def on_load(self) -> bool:
        return True

    def on_unload(self):
        pass

    def get_tools(self):
        return [
            ToolDefinition(
                name="text_case",
                description="文本大小写转换（upper/lower/title/camel/snake/kebab）",
                parameters=[
                    {"name": "text", "type": "string", "description": "要转换的文本"},
                    {"name": "mode", "type": "string", "description": "转换模式"},
                ],
                handler=self._t_case, category="text",
            ),
            ToolDefinition(
                name="text_lines",
                description="行处理：编号/去重/排序/倒序/去空行",
                parameters=[
                    {"name": "text", "type": "string", "description": "多行文本"},
                    {"name": "action", "type": "string", "description": "numbered/dedupe/sort/reverse/trim_blank"},
                ],
                handler=self._t_lines, category="text",
            ),
            ToolDefinition(
                name="uuid_gen",
                description="生成 UUID（v4）",
                parameters=[
                    {"name": "n", "type": "integer", "description": "生成数量（默认1）"},
                    {"name": "upper", "type": "boolean", "description": "是否大写"},
                ],
                handler=self._t_uuid, category="text",
            ),
            ToolDefinition(
                name="unix_ts",
                description="时间戳与日期时间互转",
                parameters=[
                    {"name": "value", "type": "string", "description": "时间戳或时间字符串"},
                    {"name": "to", "type": "string", "description": "iso(时间戳->时间) / ts(时间->时间戳)"},
                ],
                handler=self._t_ts, category="text",
            ),
            ToolDefinition(
                name="url_convert",
                description="URL 编码/解码",
                parameters=[
                    {"name": "text", "type": "string", "description": "文本"},
                    {"name": "mode", "type": "string", "description": "encode/decode"},
                ],
                handler=self._t_url, category="text",
            ),
            ToolDefinition(
                name="b64_tool",
                description="Base64 编码/解码",
                parameters=[
                    {"name": "text", "type": "string", "description": "文本"},
                    {"name": "mode", "type": "string", "description": "encode/decode"},
                ],
                handler=self._t_b64, category="text",
            ),
            ToolDefinition(
                name="hash_sum",
                description="计算文本哈希（md5/sha1/sha256）",
                parameters=[
                    {"name": "text", "type": "string", "description": "文本"},
                    {"name": "algorithm", "type": "string", "description": "md5/sha1/sha256"},
                ],
                handler=self._t_hash, category="text",
            ),
        ]

    def _t_case(self, **kw): return _convert_case(kw.get("text", ""), kw.get("mode", "upper"))
    def _t_lines(self, **kw): return _process_lines(kw.get("text", ""), kw.get("action", "numbered"), bool(kw.get("reverse", False)))
    def _t_uuid(self, **kw): return _gen_uuid(kw.get("n", 1), bool(kw.get("upper", False)))
    def _t_ts(self, **kw): return _ts_convert(kw.get("value", ""), kw.get("to", "iso"))
    def _t_url(self, **kw): return _url_convert(kw.get("text", ""), kw.get("mode", "encode"))
    def _t_b64(self, **kw): return _b64_convert(kw.get("text", ""), kw.get("mode", "encode"))
    def _t_hash(self, **kw): return _hash_sum(kw.get("text", ""), kw.get("algorithm", "md5"))
