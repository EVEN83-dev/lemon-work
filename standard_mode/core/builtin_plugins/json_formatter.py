# -*- coding: utf-8 -*-
"""
JSON Formatter 插件
===================
提供 JSON 格式化和校验工具：
- json_format:   JSON 格式化（美化/压缩）
- json_validate: JSON 语法校验
- json_query:    JSONPath 简易查询

无外部依赖，纯标准库实现。
"""

import os
import sys
import json

_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from plugin_system import IPlugin, ToolDefinition, HookPoint, SkillDefinition


def _format_json(text: str, indent: int = 2, compact: bool = False) -> dict:
    """格式化 JSON"""
    if not text or not text.strip():
        return {"ok": False, "error": "空输入"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"JSON 解析错误: {e.msg} (行 {e.lineno}, 列 {e.colno})"}
    try:
        if compact:
            formatted = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        else:
            formatted = json.dumps(data, ensure_ascii=False, indent=indent)
        return {
            "ok": True,
            "formatted": formatted,
            "size": len(formatted),
            "type": type(data).__name__,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _validate_json(text: str) -> dict:
    """校验 JSON"""
    if not text or not text.strip():
        return {"valid": False, "error": "空输入"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "error": e.msg,
            "line": e.lineno,
            "col": e.colno,
            "pos": e.pos,
        }
    # 统计结构
    stats = {"type": type(data).__name__}
    if isinstance(data, dict):
        stats["keys"] = len(data)
        stats["key_names"] = list(data.keys())[:20]
    elif isinstance(data, list):
        stats["length"] = len(data)
        if data:
            stats["item_type"] = type(data[0]).__name__
    return {"valid": True, "stats": stats}


def _query_json(text: str, path: str) -> dict:
    """简易 JSONPath 查询（仅支持点号路径：a.b.c 和数组索引 a[0].b）"""
    if not text or not path:
        return {"ok": False, "error": "缺少参数"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"JSON 解析错误: {e.msg}"}
    # 解析路径
    import re
    tokens = re.findall(r'[^.\[\]]+|\[\d+\]', path)
    current = data
    for tok in tokens:
        tok = tok.strip("[]")
        if tok.isdigit():
            idx = int(tok)
            if isinstance(current, list) and 0 <= idx < len(current):
                current = current[idx]
            else:
                return {"ok": False, "error": f"索引 {idx} 越界或非数组"}
        else:
            if isinstance(current, dict) and tok in current:
                current = current[tok]
            else:
                return {"ok": False, "error": f"键 '{tok}' 不存在"}
    return {
        "ok": True,
        "value": current if not isinstance(current, (dict, list)) else json.dumps(current, ensure_ascii=False),
        "type": type(current).__name__,
    }


class JsonFormatterPlugin(IPlugin):
    """JSON 格式化和校验插件"""

    @property
    def name(self) -> str:
        return "json_formatter"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "JSON 格式化、校验、查询工具"

    @property
    def icon(self) -> str:
        return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 13h6"/><path d="M9 17h6"/></svg>'''

    def on_load(self) -> bool:
        return True

    def on_unload(self):
        pass

    def get_tools(self):
        return [
            ToolDefinition(
                name="json_format",
                description="格式化 JSON 文本（支持美化/压缩）",
                parameters=[
                    {"name": "text", "type": "string", "description": "JSON 文本"},
                    {"name": "indent", "type": "integer", "description": "缩进空格数（默认 2）"},
                    {"name": "compact", "type": "boolean", "description": "是否压缩为单行"},
                ],
                handler=self._tool_format,
                category="json",
            ),
            ToolDefinition(
                name="json_validate",
                description="校验 JSON 语法",
                parameters=[
                    {"name": "text", "type": "string", "description": "JSON 文本"},
                ],
                handler=self._tool_validate,
                category="json",
            ),
            ToolDefinition(
                name="json_query",
                description="JSONPath 简易查询（a.b.c 或 a[0].b）",
                parameters=[
                    {"name": "text", "type": "string", "description": "JSON 文本"},
                    {"name": "path", "type": "string", "description": "查询路径"},
                ],
                handler=self._tool_query,
                category="json",
            ),
        ]

    def get_hooks(self):
        return {
            HookPoint.ON_FILE_SAVE: [self._on_file_save],
        }

    def get_skills(self):
        return [
            SkillDefinition(
                name="json_formatter",
                description="JSON 格式化技能",
                version="1.0.0",
                author="mimo_agent",
            )
        ]

    # ===== Tool handlers =====
    def _tool_format(self, **kwargs):
        text = kwargs.get("text", "")
        indent = kwargs.get("indent", 2)
        compact = kwargs.get("compact", False)
        return _format_json(text, indent=indent, compact=compact)

    def _tool_validate(self, **kwargs):
        text = kwargs.get("text", "")
        return _validate_json(text)

    def _tool_query(self, **kwargs):
        text = kwargs.get("text", "")
        path = kwargs.get("path", "")
        return _query_json(text, path)

    # ===== Hook handlers =====
    def _on_file_save(self, **kwargs):
        path = kwargs.get("path", "")
        if path and path.lower().endswith(".json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                result = _validate_json(content)
                if not result["valid"]:
                    print(f"[JsonFormatter] {path} 校验失败: {result.get('error')}")
            except Exception:
                pass
