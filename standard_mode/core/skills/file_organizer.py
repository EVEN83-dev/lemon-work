# -*- coding: utf-8 -*-
"""Skill: file_organizer — 按类型/内容分拣，不确定进review/"""

import sys, os, shutil, json
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "file_organizer",
    "description": "文件整理：按类型自动分拣到子目录，不确定文件进review/，默认报告模式不移动。",
    "category": "system",
    "version": "1.0.0",
}

_TYPE_MAP = {
    "文档": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"},
    "图片": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tiff", ".ico"},
    "视频": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"},
    "音频": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
    "代码": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go", ".rs", ".rb", ".php", ".html", ".css", ".json", ".yaml", ".yml", ".toml"},
    "压缩": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "可执行": {".exe", ".msi", ".bat", ".cmd", ".ps1"},
}


def execute(directory: str = "", dry_run: bool = True, execute: bool = False,
            by_content: bool = False) -> SkillResult:
    if not directory:
        return SkillResult(success=False, error="directory 参数为空")

    root = os.path.expanduser(directory)
    if not os.path.isdir(root):
        return SkillResult(success=False, error=f"目录不存在: {root}")

    moves = {"review": []}
    for cat in _TYPE_MAP:
        moves[cat] = []

    for fn in os.listdir(root):
        fp = os.path.join(root, fn)
        if not os.path.isfile(fp):
            continue
        ext = os.path.splitext(fn)[1].lower()
        categorized = False
        for cat, exts in _TYPE_MAP.items():
            if ext in exts:
                moves[cat].append(fn)
                categorized = True
                break
        if not categorized:
            moves["review"].append(fn)

    total = sum(len(v) for v in moves.values())
    report = f"文件整理报告: {root}\n{'='*50}\n"
    report += f"总文件: {total}\n模式: {'仅报告' if dry_run else '执行'}\n\n"

    for cat, files in moves.items():
        if not files:
            continue
        report += f"{cat}/ ({len(files)} 项)\n"
        for fn in files[:20]:
            report += f"  {fn}\n"

    executed_count = 0
    if execute and not dry_run:
        for cat, files in moves.items():
            if not files:
                continue
            dest_dir = os.path.join(root, cat)
            os.makedirs(dest_dir, exist_ok=True)
            for fn in files:
                src = os.path.join(root, fn)
                dst = os.path.join(dest_dir, fn)
                try:
                    shutil.move(src, dst)
                    executed_count += 1
                except OSError:
                    pass
        report += f"\n已移动: {executed_count}/{total}"

    return SkillResult(
        success=True,
        output=report,
        data={"total": total, "categories": {k: len(v) for k, v in moves.items()},
              "executed": executed_count, "dry_run": dry_run},
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="file_organizer",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "待整理目录"},
                "dry_run": {"type": "boolean", "description": "仅生成报告不移动", "default": True},
                "execute": {"type": "boolean", "description": "确认执行移动", "default": False},
                "by_content": {"type": "boolean", "description": "按内容而非扩展名分类", "default": False},
            },
            "required": ["directory"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=True,
        timeout=120,
    ))


def get_metadata():
    return METADATA
