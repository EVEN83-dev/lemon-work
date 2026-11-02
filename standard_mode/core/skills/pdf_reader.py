# -*- coding: utf-8 -*-
"""
Skill: pdf_reader — PDF 文档读取与解析
========================================
★ v3.71 新增
支持：文字提取 / 表格提取 / 元数据 / 分页读取 / 图片列表

依赖：PyPDF2 或 pdfplumber（优先使用 pdfplumber，表格提取更好）
安装：pip install pdfplumber PyPDF2
"""

import os
import sys
import traceback
from typing import Dict, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "pdf_reader",
    "description": "读取和解析 PDF 文档：提取文字、表格、元数据、分页内容。支持指定页码范围。",
    "category": "file",
    "version": "1.0.0",
}


def _lazy_import(lib_name: str):
    try:
        mod = __import__(lib_name)
        for part in lib_name.split('.')[1:]:
            mod = getattr(mod, part)
        return mod
    except (ImportError, AttributeError):
        return None


def execute(
    file_path: str = "",
    action: str = "extract_text",
    page_start: int = 1,
    page_end: int = 0,
    max_chars: int = 10000,
) -> SkillResult:
    """读取和解析 PDF 文档

    Args:
        file_path: PDF 文件路径
        action: extract_text / extract_tables / metadata / list_pages / full
        page_start: 起始页（从 1 开始）
        page_end: 结束页（0 表示到最后一页）
        max_chars: 最大提取字符数（防止超大 PDF 撑爆上下文）
    """
    if not file_path:
        return SkillResult(success=False, error="file_path 参数为空")
    if not os.path.exists(file_path):
        return SkillResult(success=False, error=f"文件不存在: {file_path}")
    if not file_path.lower().endswith('.pdf'):
        return SkillResult(success=False, error=f"不是 PDF 文件: {file_path}")

    # ★ 优先使用 pdfplumber（表格提取更好），回退到 PyPDF2
    pdfplumber = _lazy_import('pdfplumber')
    PyPDF2 = _lazy_import('PyPDF2')

    if pdfplumber is None and PyPDF2 is None:
        return SkillResult(
            success=False,
            error="pdfplumber 和 PyPDF2 均未安装",
            output="pip install pdfplumber PyPDF2",
        )

    try:
        if pdfplumber:
            return _extract_with_pdfplumber(
                pdfplumber, file_path, action, page_start, page_end, max_chars
            )
        else:
            return _extract_with_pypdf2(
                PyPDF2, file_path, action, page_start, page_end, max_chars
            )
    except Exception as e:
        return SkillResult(
            success=False,
            error=f"PDF 解析失败: {e}",
            output=traceback.format_exc(),
        )


def _extract_with_pdfplumber(pdfplumber, file_path, action, page_start, page_end, max_chars):
    """使用 pdfplumber 提取（推荐，表格支持更好）"""
    with pdfplumber.open(file_path) as pdf:
        total_pages = len(pdf.pages)
        if page_end <= 0 or page_end > total_pages:
            page_end = total_pages
        page_start = max(1, min(page_start, total_pages))

        if action == "metadata":
            meta = pdf.metadata or {}
            return SkillResult(
                success=True,
                output=f"PDF 元数据:\n"
                       f"  标题: {meta.get('Title', '(无)')}\n"
                       f"  作者: {meta.get('Author', '(无)')}\n"
                       f"  主题: {meta.get('Subject', '(无)')}\n"
                       f"  创建者: {meta.get('Creator', '(无)')}\n"
                       f"  生产者: {meta.get('Producer', '(无)')}\n"
                       f"  创建日期: {meta.get('CreationDate', '(无)')}\n"
                       f"  总页数: {total_pages}",
                data={"metadata": dict(meta) if meta else {}, "total_pages": total_pages},
            )

        if action == "list_pages":
            lines = [f"PDF 共 {total_pages} 页:\n"]
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                first_line = text.strip().split('\n')[0][:80] if text.strip() else "(空白页)"
                lines.append(f"  第 {i} 页: {first_line}")
            return SkillResult(
                success=True,
                output='\n'.join(lines),
                data={"total_pages": total_pages},
            )

        if action == "extract_tables":
            all_tables = []
            for i in range(page_start - 1, min(page_end, total_pages)):
                page = pdf.pages[i]
                tables = page.extract_tables()
                for t_idx, table in enumerate(tables):
                    all_tables.append({
                        "page": i + 1,
                        "table_index": t_idx + 1,
                        "rows": len(table),
                        "cols": len(table[0]) if table else 0,
                        "data": table[:50],  # 最多 50 行
                    })
            # 格式化输出
            lines = [f"提取到 {len(all_tables)} 个表格:\n"]
            for t in all_tables:
                lines.append(f"--- 第 {t['page']} 页 表 {t['table_index']} ({t['rows']}行 × {t['cols']}列) ---")
                for row in t['data']:
                    lines.append(' | '.join(str(c or '') for c in row))
                lines.append('')
            return SkillResult(
                success=True,
                output='\n'.join(lines)[:max_chars],
                data={"tables": all_tables, "total_tables": len(all_tables)},
            )

        # action == "extract_text" 或 "full"
        text_parts = []
        total_chars = 0
        for i in range(page_start - 1, min(page_end, total_pages)):
            page = pdf.pages[i]
            page_text = page.extract_text() or ""
            text_parts.append(f"--- 第 {i + 1} 页 ---\n{page_text}")
            total_chars += len(page_text)
            if total_chars >= max_chars:
                text_parts.append(f"\n（已达最大字符限制 {max_chars}，后续页面已截断）")
                break

        full_text = '\n\n'.join(text_parts)[:max_chars]
        return SkillResult(
            success=True,
            output=full_text or "(PDF 无可提取文字，可能是扫描件，需 OCR)",
            data={
                "total_pages": total_pages,
                "extracted_pages": min(page_end, total_pages) - page_start + 1,
                "char_count": len(full_text),
                "truncated": total_chars > max_chars,
            },
        )


def _extract_with_pypdf2(PyPDF2, file_path, action, page_start, page_end, max_chars):
    """使用 PyPDF2 提取（回退方案，不支持表格）"""
    with open(file_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        total_pages = len(reader.pages)
        if page_end <= 0 or page_end > total_pages:
            page_end = total_pages
        page_start = max(1, min(page_start, total_pages))

        if action == "metadata":
            meta = reader.metadata or {}
            return SkillResult(
                success=True,
                output=f"PDF 元数据:\n"
                       f"  标题: {getattr(meta, 'title', '(无)')}\n"
                       f"  作者: {getattr(meta, 'author', '(无)')}\n"
                       f"  总页数: {total_pages}",
                data={"total_pages": total_pages},
            )

        if action == "list_pages":
            lines = [f"PDF 共 {total_pages} 页:\n"]
            for i in range(total_pages):
                text = reader.pages[i].extract_text() or ""
                first_line = text.strip().split('\n')[0][:80] if text.strip() else "(空白页)"
                lines.append(f"  第 {i + 1} 页: {first_line}")
            return SkillResult(
                success=True,
                output='\n'.join(lines),
                data={"total_pages": total_pages},
            )

        if action == "extract_tables":
            return SkillResult(
                success=False,
                error="PyPDF2 不支持表格提取，请安装 pdfplumber: pip install pdfplumber",
            )

        # action == "extract_text" 或 "full"
        text_parts = []
        total_chars = 0
        for i in range(page_start - 1, min(page_end, total_pages)):
            page_text = reader.pages[i].extract_text() or ""
            text_parts.append(f"--- 第 {i + 1} 页 ---\n{page_text}")
            total_chars += len(page_text)
            if total_chars >= max_chars:
                text_parts.append(f"\n（已达最大字符限制 {max_chars}，后续页面已截断）")
                break

        full_text = '\n\n'.join(text_parts)[:max_chars]
        return SkillResult(
            success=True,
            output=full_text or "(PDF 无可提取文字，可能是扫描件，需 OCR)",
            data={
                "total_pages": total_pages,
                "extracted_pages": min(page_end, total_pages) - page_start + 1,
                "char_count": len(full_text),
                "truncated": total_chars > max_chars,
            },
        )


def register(registry) -> None:
    registry.register(SkillDef(
        name="pdf_reader",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "PDF 文件路径"},
                "action": {
                    "type": "string",
                    "enum": ["extract_text", "extract_tables", "metadata", "list_pages", "full"],
                    "description": "操作类型",
                    "default": "extract_text",
                },
                "page_start": {"type": "integer", "description": "起始页（从1开始）", "default": 1},
                "page_end": {"type": "integer", "description": "结束页（0表示到最后一页）", "default": 0},
                "max_chars": {"type": "integer", "description": "最大提取字符数", "default": 10000},
            },
            "required": ["file_path"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
