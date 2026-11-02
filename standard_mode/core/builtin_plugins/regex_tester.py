# -*- coding: utf-8 -*-
"""
Regex Tester 插件
=================
提供正则表达式测试工具：
- regex_test:    测试正则匹配
- regex_replace: 正则替换
- regex_explain: 解释正则表达式

无外部依赖。
"""

import os
import sys
import re

_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from plugin_system import IPlugin, ToolDefinition, HookPoint, SkillDefinition


def _test_regex(pattern: str, text: str, flags: int = 0) -> dict:
    """测试正则匹配"""
    if not pattern:
        return {"ok": False, "error": "空正则表达式"}
    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        return {"ok": False, "error": f"正则编译错误: {e}", "pattern": pattern}
    matches = list(compiled.finditer(text))
    result = {
        "ok": True,
        "pattern": pattern,
        "matched": len(matches) > 0,
        "match_count": len(matches),
        "matches": [],
    }
    for i, m in enumerate(matches):
        result["matches"].append({
            "index": i,
            "start": m.start(),
            "end": m.end(),
            "value": m.group(0),
            "groups": list(m.groups()),
            "named_groups": {k: v for k, v in m.groupdict().items() if v is not None},
        })
        if i >= 99:  # 限制最多100条
            result["truncated"] = True
            break
    return result


def _replace_regex(pattern: str, replacement: str, text: str, count: int = 0) -> dict:
    """正则替换"""
    if not pattern:
        return {"ok": False, "error": "空正则表达式"}
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return {"ok": False, "error": f"正则编译错误: {e}"}
    try:
        result_text, n = compiled.subn(replacement, text, count=count if count > 0 else 0)
    except re.error as e:
        return {"ok": False, "error": f"替换错误: {e}"}
    return {
        "ok": True,
        "result": result_text,
        "replacements": n,
        "original_length": len(text),
        "result_length": len(result_text),
    }


def _explain_regex(pattern: str) -> dict:
    """解释正则表达式（基础版）"""
    if not pattern:
        return {"ok": False, "error": "空正则表达式"}
    tokens = []
    i = 0
    special = {
        ".": "匹配任意单个字符（除换行）",
        "^": "匹配字符串开头",
        "$": "匹配字符串结尾",
        "*": "前一个元素出现 0 次或多次",
        "+": "前一个元素出现 1 次或多次",
        "?": "前一个元素出现 0 次或 1 次",
        "|": "或（交替）",
        "\\": "转义字符",
        "(": "分组开始",
        ")": "分组结束",
        "[": "字符类开始",
        "]": "字符类结束",
        "{": "量词开始",
        "}": "量词结束",
    }
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            next_c = pattern[i + 1]
            shorthand = {
                "d": "数字 [0-9]",
                "D": "非数字",
                "w": "单词字符 [a-zA-Z0-9_]",
                "W": "非单词字符",
                "s": "空白字符",
                "S": "非空白字符",
                "b": "单词边界",
                "B": "非单词边界",
                "n": "换行符",
                "t": "制表符",
                "r": "回车符",
            }
            desc = shorthand.get(next_c, f"转义字符 '{next_c}'")
            tokens.append({"token": f"\\{next_c}", "desc": desc})
            i += 2
            continue
        if c == "[":
            # 字符类
            j = pattern.find("]", i + 1)
            if j == -1:
                tokens.append({"token": c, "desc": special.get(c, c)})
                i += 1
                continue
            cls = pattern[i:j + 1]
            neg = "取反" if cls.startswith("[^") else ""
            tokens.append({"token": cls, "desc": f"字符类{neg}: 匹配其中任意一个字符"})
            i = j + 1
            continue
        if c == "(":
            # 非捕获组
            if pattern[i:i + 3] == "(?:":
                tokens.append({"token": "(?:", "desc": "非捕获分组开始"})
                i += 3
                continue
            if pattern[i:i + 3] == "(?<":
                tokens.append({"token": "(?<", "desc": "命名/断言分组"})
                i += 3
                continue
            tokens.append({"token": c, "desc": special.get(c, c)})
            i += 1
            continue
        if c == "{" :
            j = pattern.find("}", i + 1)
            if j != -1:
                quant = pattern[i:j + 1]
                tokens.append({"token": quant, "desc": f"量词: 重复次数 {quant}"})
                i = j + 1
                continue
        tokens.append({"token": c, "desc": special.get(c, f"字面量 '{c}'")})
        i += 1
    return {"ok": True, "pattern": pattern, "tokens": tokens, "token_count": len(tokens)}


class RegexTesterPlugin(IPlugin):
    """正则表达式测试工具插件"""

    @property
    def name(self) -> str:
        return "regex_tester"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "正则表达式测试、替换、解释工具"

    @property
    def icon(self) -> str:
        return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><path d="M8 11h6"/></svg>'''

    def on_load(self) -> bool:
        return True

    def on_unload(self):
        pass

    def get_tools(self):
        return [
            ToolDefinition(
                name="regex_test",
                description="测试正则表达式匹配",
                parameters=[
                    {"name": "pattern", "type": "string", "description": "正则表达式"},
                    {"name": "text", "type": "string", "description": "待匹配文本"},
                ],
                handler=self._tool_test,
                category="regex",
            ),
            ToolDefinition(
                name="regex_replace",
                description="正则替换",
                parameters=[
                    {"name": "pattern", "type": "string", "description": "正则表达式"},
                    {"name": "replacement", "type": "string", "description": "替换文本"},
                    {"name": "text", "type": "string", "description": "原始文本"},
                    {"name": "count", "type": "integer", "description": "替换次数（0=全部）"},
                ],
                handler=self._tool_replace,
                category="regex",
            ),
            ToolDefinition(
                name="regex_explain",
                description="解释正则表达式的每个 token",
                parameters=[
                    {"name": "pattern", "type": "string", "description": "正则表达式"},
                ],
                handler=self._tool_explain,
                category="regex",
            ),
        ]

    def get_hooks(self):
        return {}

    def get_skills(self):
        return [
            SkillDefinition(
                name="regex_tester",
                description="正则表达式测试技能",
                version="1.0.0",
                author="mimo_agent",
            )
        ]

    # ===== Tool handlers =====
    def _tool_test(self, **kwargs):
        pattern = kwargs.get("pattern", "")
        text = kwargs.get("text", "")
        flags = 0
        if kwargs.get("ignore_case"):
            flags |= re.IGNORECASE
        if kwargs.get("multiline"):
            flags |= re.MULTILINE
        if kwargs.get("dotall"):
            flags |= re.DOTALL
        return _test_regex(pattern, text, flags=flags)

    def _tool_replace(self, **kwargs):
        pattern = kwargs.get("pattern", "")
        replacement = kwargs.get("replacement", "")
        text = kwargs.get("text", "")
        count = kwargs.get("count", 0)
        return _replace_regex(pattern, replacement, text, count=count)

    def _tool_explain(self, **kwargs):
        pattern = kwargs.get("pattern", "")
        return _explain_regex(pattern)
