# -*- coding: utf-8 -*-
"""
Markdown Preview 插件
=====================
提供 Markdown 实时预览工具：
- markdown_to_html: Markdown → HTML 转换
- markdown_validate: Markdown 语法校验

依赖：markdown 库（可选，降级为纯文本）
"""

import os
import sys

# 确保 plugin_system 可导入（独立加载模式下需要）
_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from plugin_system import IPlugin, ToolDefinition, HookPoint, SkillDefinition

try:
    import markdown as _md
    _MARKDOWN_AVAILABLE = True
except ImportError:
    _MARKDOWN_AVAILABLE = False


def _md_to_html(text: str) -> str:
    """将 Markdown 转换为 HTML"""
    if not text:
        return ""
    if _MARKDOWN_AVAILABLE:
        try:
            return _md.markdown(text, extensions=["extra", "codehilite", "tables", "toc"])
        except Exception:
            pass
    # 降级：简单的纯文本转 HTML
    import html as _html
    escaped = _html.escape(text)
    return escaped.replace("\n", "<br>")


def _validate_md(text: str) -> dict:
    """校验 Markdown 语法（基础检查）"""
    if not text:
        return {"valid": True, "warnings": [], "errors": []}
    warnings = []
    errors = []
    lines = text.split("\n")
    # 检查未闭合的代码块
    code_fence_count = sum(1 for l in lines if l.strip().startswith("```"))
    if code_fence_count % 2 != 0:
        errors.append("代码块未闭合：``` 数量为奇数")
    # 检查未闭合的行内代码
    for i, l in enumerate(lines, 1):
        if l.count("`") % 2 != 0:
            warnings.append(f"第 {i} 行：行内代码 ` 未成对")
    # 检查链接语法
    import re
    for i, l in enumerate(lines, 1):
        if re.search(r'\[[^\]]*\]\s*\(', l) and not re.search(r'\[[^\]]*\]\([^)]*\)', l):
            warnings.append(f"第 {i} 行：链接语法可能不完整")
    # 检查标题层级
    prev_level = 0
    for i, l in enumerate(lines, 1):
        m = re.match(r'^(#{1,6})\s', l)
        if m:
            level = len(m.group(1))
            if prev_level > 0 and level > prev_level + 1:
                warnings.append(f"第 {i} 行：标题层级跳跃 H{prev_level} → H{level}")
            prev_level = level
    return {
        "valid": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "stats": {
            "lines": len(lines),
            "chars": len(text),
            "words": len(text.split()),
        },
    }


class MarkdownPreviewPlugin(IPlugin):
    """Markdown 实时预览插件"""

    @property
    def name(self) -> str:
        return "markdown_preview"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Markdown 实时预览：支持 md→html 转换、语法校验"

    @property
    def icon(self) -> str:
        return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>'''

    def on_load(self) -> bool:
        return True

    def on_unload(self):
        pass

    def get_tools(self):
        return [
            ToolDefinition(
                name="markdown_to_html",
                description="将 Markdown 文本转换为 HTML",
                parameters=[
                    {"name": "text", "type": "string", "description": "Markdown 文本"},
                ],
                handler=self._tool_md_to_html,
                category="markdown",
            ),
            ToolDefinition(
                name="markdown_validate",
                description="校验 Markdown 语法",
                parameters=[
                    {"name": "text", "type": "string", "description": "Markdown 文本"},
                ],
                handler=self._tool_md_validate,
                category="markdown",
            ),
        ]

    def get_hooks(self):
        return {
            HookPoint.ON_FILE_SAVE: [self._on_file_save],
        }

    def get_skills(self):
        return [
            SkillDefinition(
                name="markdown_preview",
                description="Markdown 实时预览技能",
                version="1.0.0",
                author="mimo_agent",
            )
        ]

    # ===== Tool handlers =====
    def _tool_md_to_html(self, **kwargs):
        text = kwargs.get("text", "")
        html = _md_to_html(text)
        return {"html": html, "source_length": len(text)}

    def _tool_md_validate(self, **kwargs):
        text = kwargs.get("text", "")
        return _validate_md(text)

    # ===== Hook handlers =====
    def _on_file_save(self, **kwargs):
        path = kwargs.get("path", "")
        if path and path.lower().endswith((".md", ".markdown")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                result = _validate_md(content)
                if result["warnings"]:
                    print(f"[MarkdownPreview] {path} 有 {len(result['warnings'])} 个警告")
            except Exception:
                pass
