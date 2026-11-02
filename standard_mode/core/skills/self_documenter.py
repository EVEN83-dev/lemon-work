# -*- coding: utf-8 -*-
"""
Skill: self_documenter — 自文档化（蒸馏自 MiMo Code）
======================================================
自动生成项目 README 和结构文档。支持 Markdown/JSON/HTML 格式。
"""

import json
import os
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "self_documenter",
    "description": "自动生成项目文档：README.md / 结构化 JSON / HTML 页面。包含项目结构树、文件类型分布、架构图。蒸馏自 MiMo Code self-documentation。",
    "category": "documentation",
    "version": "1.0.0",
}


def _generate_tree(root_path: str, ignore_dirs: set, prefix: str = "", max_depth: int = 3, current_depth: int = 0) -> str:
    if current_depth >= max_depth:
        return ""
    try:
        items = sorted(os.listdir(root_path))
    except PermissionError:
        return ""
    lines = []
    dirs = [d for d in items if os.path.isdir(os.path.join(root_path, d)) and d not in ignore_dirs and not d.startswith('.')]
    files = [f for f in items if os.path.isfile(os.path.join(root_path, f)) and not f.startswith('.')]
    total = dirs + files
    for i, item in enumerate(total[:50]):
        is_last = i == len(total) - 1
        connector = "└── " if is_last else "├── "
        full_path = os.path.join(root_path, item)
        if os.path.isdir(full_path):
            lines.append(f"{prefix}{connector}{item}/")
            if current_depth + 1 < max_depth:
                ext_prefix = "    " if is_last else "│   "
                subtree = _generate_tree(full_path, ignore_dirs, prefix + ext_prefix, max_depth, current_depth + 1)
                if subtree:
                    lines.append(subtree)
        else:
            lines.append(f"{prefix}{connector}{item}")
    if len(total) > 50:
        lines.append(f"{prefix}└── ... ({len(total) - 50} more items)")
    return "\n".join(lines)


def _generate_mermaid_diagram(dirs_list: list, files_by_type: dict) -> str:
    lines = ["graph TD"]
    main_parts = []
    for ext, files in sorted(files_by_type.items(), key=lambda x: -len(x[1]))[:8]:
        label = ext.replace('.', '') if ext else 'nofile'
        main_parts.append(f'    {label}[{ext} ({len(files)}文件)]')
    lines.extend(main_parts)
    for i in range(len(main_parts) - 1):
        p1 = main_parts[i].split('[')[0].strip()
        p2 = main_parts[i + 1].split('[')[0].strip()
        lines.append(f"    {p1} --> {p2}")
    return "\n".join(lines)


def execute(
    project_path: str = "",
    output_format: str = "markdown",
    include_diagram: bool = True,
) -> SkillResult:
    """自文档化"""
    if not project_path:
        project_path = os.getcwd()
    if not os.path.isdir(project_path):
        return SkillResult(success=False, error=f"路径不存在: {project_path}")

    try:
        ignore_dirs = {'.git', '__pycache__', '.venv', 'venv', 'node_modules',
                       '.idea', '.vscode', 'dist', 'build', '.next', 'target'}
        ignore_files = {'.pyc', '.pyo', '.class', '.o', '.so', '.dll', '.exe', '.DS_Store'}

        dirs_list = []
        files_by_type = {}
        total_files = 0

        for root, dlist, flist in os.walk(project_path):
            dlist[:] = [d for d in dlist if d not in ignore_dirs and not d.startswith('.')]
            rel_root = os.path.relpath(root, project_path)
            if rel_root == '.':
                rel_root = ''
            for d in dlist:
                dirs_list.append(os.path.join(rel_root, d).replace('\\', '/'))
            for f in flist:
                ext = os.path.splitext(f)[1].lower()
                if ext in ignore_files:
                    continue
                total_files += 1
                if ext not in files_by_type:
                    files_by_type[ext] = []
                files_by_type[ext].append(os.path.join(rel_root, f).replace('\\', '/'))

        # 检测项目类型
        project_type = "通用项目"
        type_indicators = {
            'package.json': ('Node.js/前端项目', 'JavaScript/TypeScript'),
            'requirements.txt': ('Python 项目', 'Python'),
            'pyproject.toml': ('Python 项目', 'Python'),
            'Cargo.toml': ('Rust 项目', 'Rust'),
            'go.mod': ('Go 项目', 'Go'),
            'Dockerfile': ('容器化项目', 'Docker'),
        }
        languages = set()
        for indicator, (ptype, lang) in type_indicators.items():
            if os.path.exists(os.path.join(project_path, indicator)):
                project_type = ptype
                languages.add(lang)

        project_name = os.path.basename(os.path.abspath(project_path))
        file_type_summary = "\n".join(
            [f"| {ext if ext else '(无后缀)'} | {len(files)} |"
             for ext, files in sorted(files_by_type.items(), key=lambda x: -len(x[1]))[:15]])

        if output_format == 'markdown':
            doc = f"""# {project_name}

## 项目概述
自动生成的 {project_type} 项目文档。

- **项目类型**: {project_type}
- **语言**: {', '.join(languages) if languages else '未检测'}
- **文件总数**: {total_files}
- **目录数**: {len(dirs_list)}

## 文件类型分布
| 类型 | 文件数 |
|------|--------|
{file_type_summary}

## 项目结构
```
{_generate_tree(project_path, ignore_dirs, max_depth=3)}
```

## 主要目录
{chr(10).join([f'- `{d}/`' for d in sorted(dirs_list)[:30]])}

---
*由 Lemon Code self_documenter 自动生成*
"""
            if include_diagram:
                mermaid = _generate_mermaid_diagram(dirs_list, files_by_type)
                doc += f"\n\n## 架构图\n\n```mermaid\n{mermaid}\n```\n"

        elif output_format == 'json':
            doc = json.dumps({
                'project_name': project_name, 'project_type': project_type,
                'languages': list(languages), 'total_files': total_files,
                'total_dirs': len(dirs_list),
                'file_types': {k: len(v) for k, v in files_by_type.items()},
                'directories': dirs_list,
            }, ensure_ascii=False, indent=2)

        elif output_format == 'html':
            doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{project_name}</title>
<style>
body{{font-family:'Segoe UI',sans-serif;max-width:900px;margin:40px auto;padding:20px;background:Lemon.DARK_MID_5;color:Lemon.DIVIDER}}
h1{{color:Lemon.BRAND_ORANGE_LIGHT;border-bottom:2px solid Lemon.BRAND_ORANGE_LIGHT}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #333;padding:8px 12px}}th{{background:Lemon.DARK_BG_4}}pre{{background:#0f0f23;padding:16px;border-radius:8px}}
</style></head><body><h1>{project_name}</h1>
<p><strong>项目类型:</strong> {project_type} | <strong>语言:</strong> {', '.join(languages) if languages else '未检测'} | <strong>文件:</strong> {total_files}</p>
<h2>项目结构</h2><pre>{_generate_tree(project_path, ignore_dirs, max_depth=3)}</pre>
<p><em>由 Lemon Code self_documenter 自动生成</em></p></body></html>"""
        else:
            return SkillResult(success=False, error=f"不支持的格式: {output_format}")

        return SkillResult(
            success=True,
            output=f"项目文档已生成 ({project_name})\n类型: {project_type}\n文件: {total_files}\n格式: {output_format}",
            data={'project_name': project_name, 'project_type': project_type, 'total_files': total_files, 'document': doc},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"自文档化失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="self_documenter",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "项目根目录路径"},
                "output_format": {"type": "string", "enum": ["markdown", "json", "html"], "description": "输出格式"},
                "include_diagram": {"type": "boolean", "description": "是否包含 Mermaid 架构图", "default": True},
            },
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
