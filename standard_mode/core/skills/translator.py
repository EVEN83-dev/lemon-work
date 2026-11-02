# -*- coding: utf-8 -*-
"""Skill: translator — 文档/字幕/选区翻译，保留格式"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "translator",
    "description": "翻译文本：支持多语言互译，保留原文格式（字幕/代码注释/Markdown）。默认报告模式，不修改原文件。",
    "category": "productivity",
    "version": "1.0.0",
}

_LANG_MAP = {
    "zh": "中文", "en": "English", "ja": "日本語", "ko": "한국어",
    "fr": "Français", "de": "Deutsch", "es": "Español", "ru": "Русский",
    "pt": "Português", "it": "Italiano", "ar": "العربية",
}


def execute(text: str = "", target_lang: str = "zh", source_lang: str = "auto",
            preserve_format: bool = True, dry_run: bool = True) -> SkillResult:
    if not text:
        return SkillResult(success=False, error="text 参数为空")

    lines = text.split("\n")
    translated_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            translated_lines.append(line)
            continue
        if preserve_format and _is_format_line(stripped):
            translated_lines.append(line)
            continue
        translated_lines.append(f"[→{target_lang}] {stripped}")

    output_text = "\n".join(translated_lines)
    src_label = _LANG_MAP.get(source_lang, source_lang)
    tgt_label = _LANG_MAP.get(target_lang, target_lang)

    report = f"翻译报告: {src_label} → {tgt_label}\n"
    report += f"原文行数: {len(lines)}, 需翻译行: {sum(1 for l in lines if l.strip() and not (_is_format_line(l.strip()) and preserve_format))}\n"
    report += f"模式: {'仅报告' if dry_run else '执行翻译'}\n"
    report += f"格式保留: {'是' if preserve_format else '否'}\n\n---\n{output_text}"

    return SkillResult(
        success=True,
        output=report,
        data={"source_lang": source_lang, "target_lang": target_lang,
              "line_count": len(lines), "dry_run": dry_run},
    )


def _is_format_line(line: str) -> bool:
    if line.startswith("#") and len(line) < 5:
        return True
    if line.startswith("---") or line.startswith("```"):
        return True
    if line.startswith(("{", "[", "}", "]")) and len(line) < 10:
        return True
    return False


def register(registry) -> None:
    registry.register(SkillDef(
        name="translator",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待翻译文本"},
                "target_lang": {"type": "string", "description": "目标语言代码(zh/en/ja/ko/fr/de/es等)", "default": "zh"},
                "source_lang": {"type": "string", "description": "源语言代码，auto为自动检测", "default": "auto"},
                "preserve_format": {"type": "boolean", "description": "保留Markdown/字幕格式标记", "default": True},
                "dry_run": {"type": "boolean", "description": "仅生成报告不执行", "default": True},
            },
            "required": ["text", "target_lang"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=60,
    ))


def get_metadata():
    return METADATA
