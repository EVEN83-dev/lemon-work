"""
H-A1: LSP Diagnose Skill - real-time code diagnostics via LSP.
H-A5: LSP Completion Skill - code completion items via LSP.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from bridge.skills.models import SkillDef, SkillResult, SkillCategory, SkillRiskLevel, SkillMetadata

logger = logging.getLogger(__name__)

LSP_DIAGNOSE_META = SkillMetadata(
    version="1.0.0",
    author="Lemon Agent",
    tags=["lsp", "diagnostics", "errors", "warnings", "code"],
    dependencies=[],
)


def lsp_diagnose(**kwargs) -> SkillResult:
    start = time.time()
    file_path = kwargs.get("file_path", "")
    language = kwargs.get("language", "")

    if not file_path:
        return SkillResult.fail("file_path is required")

    lsp_manager = kwargs.get("_lsp_manager")
    if lsp_manager is None:
        return SkillResult.ok(
            output=_no_lsp_fallback(file_path),
            data={"needs_llm": False, "source": "fallback"},
            duration_ms=(time.time() - start) * 1000,
        )

    try:
        if not language:
            language = _language_from_path(file_path)

        if language and not lsp_manager.is_server_ready(language):
            lsp_manager.start_server(language)
            time.sleep(2)

        if file_path and os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                lsp_manager.open_document(file_path, content)
            except Exception:
                pass

        diagnostics_data = _get_cached_diagnostics(lsp_manager, file_path)
        if diagnostics_data is None:
            diagnostics_data = []

        output = _format_diagnostics(file_path, diagnostics_data)
        return SkillResult.ok(
            output=output,
            data={
                "needs_llm": False,
                "source": "lsp",
                "file_path": file_path,
                "diagnostic_count": len(diagnostics_data),
                "errors": sum(1 for d in diagnostics_data if d.get("severity") == 1),
                "warnings": sum(1 for d in diagnostics_data if d.get("severity") == 2),
            },
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return SkillResult.fail(f"LSP diagnose error: {e}")


def lsp_completion(**kwargs) -> SkillResult:
    start = time.time()
    file_path = kwargs.get("file_path", "")
    line = int(kwargs.get("line", 1))
    character = int(kwargs.get("character", 1))
    language = kwargs.get("language", "")

    if not file_path:
        return SkillResult.fail("file_path is required")

    lsp_manager = kwargs.get("_lsp_manager")
    if lsp_manager is None:
        return SkillResult.ok(
            output="LSP not available. Completion items cannot be retrieved.",
            data={"needs_llm": False, "source": "fallback"},
            duration_ms=(time.time() - start) * 1000,
        )

    try:
        if not language:
            language = _language_from_path(file_path)

        if language and not lsp_manager.is_server_ready(language):
            lsp_manager.start_server(language)
            time.sleep(2)

        lsp_manager.request_completion(file_path, line, character)
        time.sleep(1)

        completions = _get_cached_completions(lsp_manager, file_path)
        output = _format_completions(file_path, line, character, completions)
        return SkillResult.ok(
            output=output,
            data={
                "needs_llm": False,
                "source": "lsp",
                "file_path": file_path,
                "completion_count": len(completions),
            },
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return SkillResult.fail(f"LSP completion error: {e}")


def _language_from_path(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
    }
    return ext_map.get(ext, "")


def _no_lsp_fallback(file_path: str) -> str:
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"
    return (
        f"LSP server not available for {file_path}. "
        f"Diagnostics require a running language server. "
        f"Install pyright (Python), typescript-language-server (JS/TS), or gopls (Go)."
    )


def _get_cached_diagnostics(lsp_manager: Any, file_path: str) -> Optional[List[Dict]]:
    try:
        if hasattr(lsp_manager, "_diagnostics_cache"):
            cache = lsp_manager._diagnostics_cache
            if file_path in cache:
                return cache[file_path]
    except Exception:
        pass
    try:
        if hasattr(lsp_manager, "_clients"):
            for lang, client in lsp_manager._clients.items():
                if hasattr(client, "_diagnostics"):
                    diags = client._diagnostics.get(file_path)
                    if diags is not None:
                        return [d.to_dict() if hasattr(d, "to_dict") else d for d in diags]
    except Exception:
        pass
    return []


def _get_cached_completions(lsp_manager: Any, file_path: str) -> List[Dict]:
    try:
        if hasattr(lsp_manager, "_completion_cache"):
            cache = lsp_manager._completion_cache
            if file_path in cache:
                return cache[file_path]
    except Exception:
        pass
    return []


def _format_diagnostics(file_path: str, diagnostics: List[Dict]) -> str:
    if not diagnostics:
        return f"No diagnostics for {os.path.basename(file_path)}."

    severity_map = {1: "ERROR", 2: "WARNING", 3: "INFO", 4: "HINT"}
    lines: List[str] = [f"Diagnostics for {os.path.basename(file_path)}:"]

    errors = [d for d in diagnostics if d.get("severity") == 1]
    warnings = [d for d in diagnostics if d.get("severity") == 2]
    others = [d for d in diagnostics if d.get("severity") not in (1, 2)]

    if errors:
        lines.append(f"\nErrors ({len(errors)}):")
        for e in errors:
            rng = e.get("range", {})
            start = rng.get("start", {})
            line_num = start.get("line", "?") + 1
            col = start.get("character", "?") + 1
            msg = e.get("message", "")
            code = e.get("code", "")
            code_str = f" [{code}]" if code else ""
            lines.append(f"  L{line_num}:{col} ERROR{code_str}: {msg}")

    if warnings:
        lines.append(f"\nWarnings ({len(warnings)}):")
        for w in warnings[:20]:
            rng = w.get("range", {})
            start = rng.get("start", {})
            line_num = start.get("line", "?") + 1
            col = start.get("character", "?") + 1
            msg = w.get("message", "")
            code = w.get("code", "")
            code_str = f" [{code}]" if code else ""
            lines.append(f"  L{line_num}:{col} WARN{code_str}: {msg}")

    if others:
        lines.append(f"\nInfo/Hints ({len(others)}):")
        for o in others[:10]:
            msg = o.get("message", "")
            lines.append(f"  {msg}")

    return "\n".join(lines)


def _format_completions(file_path: str, line: int, character: int,
                        completions: List[Dict]) -> str:
    if not completions:
        return f"No completions at {os.path.basename(file_path)}:{line}:{character}."

    lines: List[str] = [f"Completions at {os.path.basename(file_path)}:{line}:{character} ({len(completions)} items):"]
    for item in completions[:30]:
        label = item.get("label", "?")
        kind = item.get("kind", 0)
        kind_names = {
            1: "Text", 2: "Method", 3: "Function", 4: "Constructor",
            5: "Field", 6: "Variable", 7: "Class", 8: "Interface",
            9: "Module", 10: "Property", 11: "Unit", 12: "Value",
            13: "Enum", 14: "Keyword", 15: "Snippet", 16: "Color",
            17: "File", 18: "Reference", 19: "Folder", 20: "EnumMember",
            21: "Constant", 22: "Struct", 23: "Event", 24: "Operator",
            25: "TypeParameter",
        }
        kind_str = kind_names.get(kind, f"Type{kind}")
        detail = item.get("detail", "")
        detail_str = f" -- {detail}" if detail else ""
        lines.append(f"  {label} [{kind_str}]{detail_str}")

    return "\n".join(lines)


def register(registry) -> None:
    registry.register(SkillDef(
        name="lsp_diagnose",
        description="Get real-time LSP diagnostics (errors/warnings) for a file. Requires LSP server running.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to diagnose"},
                "language": {"type": "string", "description": "Language ID (python/javascript/typescript/go). Auto-detected if empty."},
            },
            "required": ["file_path"],
        },
        handler=lsp_diagnose,
        category=SkillCategory.CODE,
        risk_level=SkillRiskLevel.SAFE,
        requires_confirm=False,
        timeout=15,
        version="1.0.0",
        examples=[
            "Diagnose errors in main.py",
            "Check for warnings in app.ts",
        ],
        metadata=LSP_DIAGNOSE_META,
    ))

    registry.register(SkillDef(
        name="lsp_completion",
        description="Get LSP completion items at a position in a file. Useful for understanding available symbols.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file"},
                "line": {"type": "integer", "description": "Line number (1-based)"},
                "character": {"type": "integer", "description": "Column number (1-based)"},
                "language": {"type": "string", "description": "Language ID. Auto-detected if empty."},
            },
            "required": ["file_path", "line", "character"],
        },
        handler=lsp_completion,
        category=SkillCategory.CODE,
        risk_level=SkillRiskLevel.SAFE,
        requires_confirm=False,
        timeout=10,
        version="1.0.0",
        examples=[
            "Get completions at line 10, column 5 in main.py",
        ],
    ))
