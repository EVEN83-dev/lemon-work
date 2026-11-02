from .models import SkillResult, SkillDef

import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

_PDF_LIB = None
_PDF_LIB_NAME = ""

try:
    from PyPDF2 import PdfReader
    _PDF_LIB = "pypdf2"
    _PDF_LIB_NAME = "PyPDF2"
except ImportError:
    try:
        from pdfminer.high_level import extract_text as pm_extract_text
        from pdfminer.pdfpage import PDFPage
        _PDF_LIB = "pdfminer"
        _PDF_LIB_NAME = "pdfminer"
    except ImportError:
        _PDF_LIB = None
        _PDF_LIB_NAME = ""

METADATA = {
    "name": "pdf_reader",
    "version": "2.0.0",
    "category": "document",
    "description": "Read and extract text, summaries, or tables from PDF files on the local filesystem.",
}


def _parse_page_range(pages: str, total: int) -> List[int]:
    if pages.strip().lower() == "all":
        return list(range(1, total + 1))
    result = []
    for part in pages.split(","):
        part = part.strip()
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                start = max(1, int(bounds[0].strip()))
                end = min(total, int(bounds[1].strip()))
                result.extend(range(start, end + 1))
            except (ValueError, IndexError):
                continue
        else:
            try:
                pn = int(part)
                if 1 <= pn <= total:
                    result.append(pn)
            except ValueError:
                continue
    return sorted(set(result))


def _extract_raw_text(filepath: str) -> Tuple[str, Dict[str, Any]]:
    with open(filepath, "rb") as f:
        raw = f.read()

    meta: Dict[str, Any] = {"extraction_method": "raw_binary", "pdf_library": None}

    version_match = re.search(rb"%PDF-(\d+\.\d+)", raw[:1024])
    if version_match:
        meta["pdf_version"] = version_match.group(1).decode("ascii", errors="replace")

    pages_match = re.search(rb"/Type\s*/Pages\s*/Count\s+(\d+)", raw)
    if not pages_match:
        pages_match = re.search(rb"/Count\s+(\d+)", raw)
    if pages_match:
        try:
            meta["page_count"] = int(pages_match.group(1))
        except (ValueError, IndexError):
            meta["page_count"] = 0
    else:
        page_objects = re.findall(rb"/Type\s*/Page[^s]", raw)
        meta["page_count"] = len(page_objects) if page_objects else 0

    text_parts: List[str] = []
    between_streams = re.split(rb"stream\r?\n|\r?\nendstream", raw)
    for segment in between_streams:
        try:
            decoded = segment.decode("ascii", errors="ignore")
        except Exception:
            decoded = ""
        cleaned = re.sub(r"[^\x20-\x7e\r\n\t]+", " ", decoded)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned and len(cleaned) > 3:
            text_parts.append(cleaned)

    paren_texts: List[str] = []
    for m in re.finditer(rb"\(([^)]{4,})\)", raw):
        try:
            t = m.group(1).decode("latin-1", errors="replace")
            if re.search(r"[a-zA-Z]{3,}", t):
                paren_texts.append(t.strip())
        except Exception:
            continue

    array_texts: List[str] = []
    for m in re.finditer(rb"\[(.*?)\]", raw):
        chunk = m.group(1)
        strings = re.findall(rb"\(([^)]+)\)", chunk)
        parts = []
        for s in strings:
            try:
                parts.append(s.decode("latin-1", errors="replace"))
            except Exception:
                continue
        if parts:
            array_texts.append(" ".join(parts))

    combined = "\n".join(array_texts + paren_texts + text_parts)
    combined = re.sub(r"\n{3,}", "\n\n", combined).strip()

    return combined, meta


def _extract_with_pypdf2(filepath: str, page_numbers: Optional[List[int]] = None) -> Tuple[str, Dict[str, Any]]:
    reader = PdfReader(filepath)
    total = len(reader.pages)
    meta: Dict[str, Any] = {
        "extraction_method": "pypdf2",
        "pdf_library": "PyPDF2",
        "page_count": total,
    }

    doc_meta = reader.metadata
    if doc_meta:
        for key in ("title", "author", "subject", "creator", "producer"):
            val = getattr(doc_meta, key, None)
            if val:
                meta[key] = val

    if page_numbers is None:
        pages_to_read = list(range(total))
    else:
        pages_to_read = [p - 1 for p in page_numbers if 1 <= p <= total]

    texts: List[str] = []
    for idx in pages_to_read:
        try:
            page_text = reader.pages[idx].extract_text() or ""
            texts.append(page_text)
        except Exception:
            texts.append("")

    return "\n\n".join(texts), meta


def _extract_with_pdfminer(filepath: str, page_numbers: Optional[List[int]] = None) -> Tuple[str, Dict[str, Any]]:
    from pdfminer.pdfpage import PDFPage as PMPage
    from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
    from pdfminer.converter import TextConverter
    from pdfminer.layout import LAParams
    import io

    meta: Dict[str, Any] = {"extraction_method": "pdfminer", "pdf_library": "pdfminer"}

    with open(filepath, "rb") as f:
        all_pages = list(PMPage.get_pages(f))

    meta["page_count"] = len(all_pages)

    if page_numbers is None:
        target_indices = list(range(len(all_pages)))
    else:
        target_indices = [p - 1 for p in page_numbers if 1 <= p <= len(all_pages)]

    texts: List[str] = []
    for idx in target_indices:
        try:
            rsrcmgr = PDFResourceManager()
            sio = io.StringIO()
            device = TextConverter(rsrcmgr, sio, laparams=LAParams())
            interpreter = PDFPageInterpreter(rsrcmgr, device)
            with open(filepath, "rb") as f:
                pages = list(PMPage.get_pages(f))
                if idx < len(pages):
                    interpreter.process_page(pages[idx])
            texts.append(sio.getvalue())
            device.close()
        except Exception:
            texts.append("")

    return "\n\n".join(texts), meta


def _compute_summary(text: str) -> Dict[str, Any]:
    words = text.split()
    word_count = len(words)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    paragraph_count = len(paragraphs)
    freq = Counter(w.lower() for w in words if len(w) > 4 and w.isalpha())
    top_terms = freq.most_common(15)
    return {
        "word_count": word_count,
        "paragraph_count": paragraph_count,
        "key_terms": [{"term": t, "count": c} for t, c in top_terms],
    }


def _extract_tables(text: str) -> List[Dict[str, Any]]:
    tables: List[Dict[str, Any]] = []
    lines = text.split("\n")
    current_rows: List[List[str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if len(current_rows) >= 2:
                tables.append({"rows": current_rows, "columns": len(current_rows[0]) if current_rows else 0})
            current_rows = []
            continue
        pipe_cols = [c.strip() for c in stripped.split("|") if c.strip()]
        if len(pipe_cols) >= 2:
            current_rows.append(pipe_cols)
            continue
        tab_cols = [c.strip() for c in stripped.split("\t") if c.strip()]
        if len(tab_cols) >= 2:
            current_rows.append(tab_cols)
            continue
        space_cols = re.split(r"\s{2,}", stripped)
        if len(space_cols) >= 3:
            current_rows.append(space_cols)
            continue
        if current_rows:
            if len(current_rows) >= 2:
                tables.append({"rows": current_rows, "columns": len(current_rows[0]) if current_rows else 0})
            current_rows = []
    if len(current_rows) >= 2:
        tables.append({"rows": current_rows, "columns": len(current_rows[0]) if current_rows else 0})
    return tables


def _resolve_filepath(file_id: str = "", path: str = "") -> str:
    if path and os.path.isfile(path):
        return path
    if file_id and os.path.isfile(file_id):
        return file_id
    if path:
        return path
    return file_id


def execute(
    file_id: str = "",
    path: str = "",
    pages: str = "all",
    extract_type: str = "text",
    **kwargs,
) -> SkillResult:
    valid_extract_types = ("text", "summary", "tables")
    if extract_type not in valid_extract_types:
        return SkillResult.fail(f"Invalid extract_type '{extract_type}'. Must be one of: {valid_extract_types}")

    filepath = _resolve_filepath(file_id, path)

    if not filepath:
        return SkillResult.fail("file_id or path is required")

    if not os.path.isfile(filepath):
        return SkillResult.fail(f"File not found: {filepath}")

    if not filepath.lower().endswith(".pdf"):
        try:
            with open(filepath, "rb") as f:
                header = f.read(5)
            if header != b"%PDF-":
                return SkillResult.fail(f"Not a PDF file: {filepath}")
        except Exception as e:
            return SkillResult.fail(f"Cannot read file: {filepath} ({e})")

    try:
        if _PDF_LIB == "pypdf2":
            reader = PdfReader(filepath)
            total_pages = len(reader.pages)
            page_numbers = _parse_page_range(pages, total_pages)
            text, meta = _extract_with_pypdf2(filepath, page_numbers)
        elif _PDF_LIB == "pdfminer":
            from pdfminer.pdfpage import PDFPage as PMPage
            with open(filepath, "rb") as f:
                total_pages = len(list(PMPage.get_pages(f)))
            page_numbers = _parse_page_range(pages, total_pages)
            text, meta = _extract_with_pdfminer(filepath, page_numbers)
        else:
            text, meta = _extract_raw_text(filepath)
            total_pages = meta.get("page_count", 0)
            page_numbers = _parse_page_range(pages, total_pages) if total_pages else []
            meta["page_numbers_requested"] = page_numbers
    except Exception as e:
        return SkillResult.fail(f"PDF extraction failed: {e}")

    if not text.strip():
        text = "(No extractable text found in this PDF. It may be a scanned/image-based document.)"

    meta["needs_file"] = False
    meta["file_id"] = file_id
    meta["path"] = filepath
    meta["pages_requested"] = pages
    meta["extract_type"] = extract_type

    if _PDF_LIB is None:
        meta["note"] = (
            "Extracted using raw binary fallback. Install PyPDF2 or pdfminer.six for better results: "
            "pip install PyPDF2  OR  pip install pdfminer.six"
        )

    if extract_type == "text":
        output = text
    elif extract_type == "summary":
        summary = _compute_summary(text)
        meta.update(summary)
        output_parts = [
            text,
            "",
            "--- Summary ---",
            f"Word count: {summary['word_count']}",
            f"Paragraph count: {summary['paragraph_count']}",
            "Key terms: " + ", ".join(f"{t['term']}({t['count']})" for t in summary["key_terms"][:10]),
        ]
        output = "\n".join(output_parts)
    elif extract_type == "tables":
        tables = _extract_tables(text)
        meta["tables_found"] = len(tables)
        if not tables:
            output = text + "\n\n--- Tables ---\nNo tabular structures detected in the extracted text."
        else:
            table_parts = [text, "", "--- Tables ---"]
            for i, tbl in enumerate(tables):
                table_parts.append(f"\nTable {i + 1} ({tbl['columns']} columns):")
                for row in tbl["rows"]:
                    table_parts.append("| " + " | ".join(row) + " |")
            output = "\n".join(table_parts)
    else:
        output = text

    return SkillResult.ok(output=output, data=meta)


def register(registry) -> None:
    registry.register(SkillDef(
        name="pdf_reader",
        description="Read and extract text, summaries, or tables from PDF files on the local filesystem.",
        category="document",
        parameters={
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "File path or uploaded file reference ID for the PDF",
                },
                "path": {
                    "type": "string",
                    "description": "Direct filesystem path to the PDF file",
                },
                "pages": {
                    "type": "string",
                    "description": "Page range to extract, e.g. '1-5' or 'all'",
                },
                "extract_type": {
                    "type": "string",
                    "enum": ["text", "summary", "tables"],
                    "description": "Type of extraction: full text, summary, or tables",
                },
            },
            "required": [],
        },
        handler=execute,
        timeout=60,
    ))
