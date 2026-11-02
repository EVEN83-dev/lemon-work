from __future__ import annotations

import ast
import re
import math
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from .models import SkillResult, SkillDef

METADATA = {
    "name": "code_psychologist",
    "version": "2.0.0",
    "category": "analysis",
    "description": "Analyze code quality, patterns, and provide psychological insights about code.",
}

_RE_SINGLE_LETTER = re.compile(r'^[a-z]$')
_RE_SNAKE_CASE = re.compile(r'^[a-z][a-z0-9_]*$')
_RE_CAMEL_CASE = re.compile(r'^[a-z][a-zA-Z0-9]*$')
_RE_UPPER_CAMEL = re.compile(r'^[A-Z][a-zA-Z0-9]*$')
_RE_MAGIC_NUM = re.compile(r'\b(?<![#\w])(\d+\.?\d*)\b')

_MAGIC_EXEMPT = {0, 1, -1, 2, 10, 100, 1000, 0.0, 1.0, 0.5, 2.0, 360, 256, 1024}

_PYTHON_STRING_PREFIXES = (
    "f\"", "f'", "r\"", "r'", "b\"", "b'",
    "rf\"", "rf'", "fr\"", "fr'", "rb\"", "rb'", "br\"", "br'",
    "\"", "'",
    "\"\"\"", "'''",
)


def _strip_string_literals(code: str) -> str:
    result = []
    i = 0
    n = len(code)
    while i < n:
        if code[i] == '#':
            while i < n and code[i] != '\n':
                i += 1
            continue
        matched = False
        for prefix in _PYTHON_STRING_PREFIXES:
            if code[i:i+len(prefix)] == prefix:
                quote_char = prefix[-1]
                triple = (i + len(prefix) + 2 < n and
                          code[i+len(prefix)] == quote_char and
                          code[i+len(prefix)+1] == quote_char)
                start = i + len(prefix)
                if triple:
                    start = i
                    quote_char = code[i]
                    end_marker = quote_char * 3
                    end = code.find(end_marker, i + 3)
                    if end == -1:
                        i = n
                    else:
                        i = end + 3
                else:
                    esc = False
                    while start < n:
                        if esc:
                            esc = False
                            start += 1
                            continue
                        if code[start] == '\\':
                            esc = True
                            start += 1
                            continue
                        if code[start] == quote_char:
                            break
                        start += 1
                    i = start + 1 if start < n else n
                result.append(' ')
                matched = True
                break
        if not matched:
            result.append(code[i])
            i += 1
    return ''.join(result)


def _count_python_comments(code: str) -> int:
    count = 0
    in_triple = False
    triple_char = ''
    i = 0
    n = len(code)
    while i < n:
        if in_triple:
            end = code.find(triple_char * 3, i)
            if end == -1:
                break
            i = end + 3
            in_triple = False
            continue
        if code[i:i+3] in ('"""', "'''"):
            in_triple = True
            triple_char = code[i]
            i += 3
            continue
        if code[i] in ('"', "'"):
            q = code[i]
            i += 1
            while i < n and code[i] != q:
                if code[i] == '\\':
                    i += 1
                i += 1
            i += 1
            continue
        if code[i] == '#':
            count += 1
            while i < n and code[i] != '\n':
                i += 1
            continue
        i += 1
    return count


def _count_generic_comments(code: str, language: str) -> int:
    stripped = _strip_string_literals(code)
    count = 0
    for line in stripped.split('\n'):
        trimmed = line.strip()
        if not trimmed:
            continue
        if trimmed.startswith('//'):
            count += 1
        elif trimmed.startswith('#'):
            count += 1
        elif trimmed.startswith('/*') or trimmed.startswith('*'):
            count += 1
    return count


def _analyze_indent(code: str) -> Dict[str, Any]:
    indent_types: Dict[str, int] = Counter()
    max_depth = 0
    for line in code.split('\n'):
        stripped = line.lstrip()
        if not stripped:
            continue
        leading = line[:len(line) - len(stripped)]
        if not leading:
            continue
        depth = 0
        if '\t' in leading and ' ' not in leading:
            indent_types['tab'] += 1
            depth = len(leading)
        elif leading == ' ' * len(leading):
            spaces = len(leading)
            if spaces == 0:
                continue
            if all(s % 4 == 0 for s in [spaces]):
                indent_types['4-space'] += 1
                depth = spaces // 4
            elif all(s % 2 == 0 for s in [spaces]):
                indent_types['2-space'] += 1
                depth = spaces // 2
            else:
                indent_types['mixed'] += 1
                depth = spaces
        else:
            indent_types['mixed'] += 1
            depth = len(leading)
        if depth > max_depth:
            max_depth = depth
    if not indent_types:
        return {"style": "none", "max_depth": 0, "consistent": True}
    dominant = indent_types.most_common(1)[0][0]
    consistent = len(indent_types) == 1
    return {"style": dominant, "max_depth": max_depth, "consistent": consistent}


def _analyze_python(code: str) -> Dict[str, Any]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return _analyze_generic(code, "python", syntax_error=str(e))

    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    branches = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.If, ast.IfExp)))
    loops = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.For, ast.AsyncFor, ast.While)))
    tries = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.Try, ast.TryStar)))

    names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.append(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            names.append(node.name)

    single_letter = [n for n in names if _RE_SINGLE_LETTER.match(n) and n != '_']
    snake_names = sum(1 for n in names if _RE_SNAKE_CASE.match(n))
    camel_names = sum(1 for n in names if _RE_CAMEL_CASE.match(n) and not _RE_SNAKE_CASE.match(n))

    comment_count = _count_python_comments(code)
    lines = code.split('\n')
    non_empty = sum(1 for l in lines if l.strip())
    comment_ratio = comment_count / max(non_empty, 1)

    stripped_code = _strip_string_literals(code)
    magic_nums: List[str] = []
    for match in _RE_MAGIC_NUM.finditer(stripped_code):
        val = float(match.group(1))
        if val not in _MAGIC_EXEMPT and not (val.is_integer() and int(val) in _MAGIC_EXEMPT):
            magic_nums.append(match.group(1))

    long_lines = sum(1 for l in lines if len(l) > 120)

    max_nesting = 0
    for node in ast.walk(tree):
        depth = 0
        parent = getattr(node, '_parent', None)
        while parent is not None:
            if isinstance(parent, (ast.If, ast.For, ast.While, ast.With, ast.Try,
                                   ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                depth += 1
            parent = getattr(parent, '_parent', None)
        if depth > max_nesting:
            max_nesting = depth

    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._parent = node
    max_nesting = 0
    for node in ast.walk(tree):
        depth = 0
        parent = getattr(node, '_parent', None)
        while parent is not None:
            if isinstance(parent, (ast.If, ast.For, ast.While, ast.With, ast.Try,
                                   ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                depth += 1
            parent = getattr(parent, '_parent', None)
        if depth > max_nesting:
            max_nesting = depth

    line_counts: Dict[str, int] = Counter()
    for l in lines:
        trimmed = l.strip()
        if trimmed:
            line_counts[trimmed] += 1
    duplicate_lines = sum(c - 1 for c in line_counts.values() if c > 1)

    indent_info = _analyze_indent(code)

    naming_convention = "snake_case" if snake_names >= camel_names else "camelCase"
    naming_score = max(snake_names, camel_names) / max(len(names), 1)

    return {
        "functions": len(funcs),
        "classes": len(classes),
        "branches": branches,
        "loops": loops,
        "try_blocks": tries,
        "total_names": len(names),
        "single_letter_vars": len(single_letter),
        "single_letter_examples": single_letter[:10],
        "naming_convention": naming_convention,
        "naming_consistency": round(naming_score, 2),
        "snake_case_count": snake_names,
        "camel_case_count": camel_names,
        "comment_count": comment_count,
        "comment_ratio": round(comment_ratio, 3),
        "magic_numbers": magic_nums[:20],
        "magic_number_count": len(magic_nums),
        "long_lines": long_lines,
        "max_nesting": max_nesting,
        "duplicate_lines": duplicate_lines,
        "indent": indent_info,
    }


def _analyze_generic(code: str, language: str, syntax_error: Optional[str] = None) -> Dict[str, Any]:
    lines = code.split('\n')
    non_empty = sum(1 for l in lines if l.strip())

    func_pattern = re.compile(r'\b(function|def|func|fn|sub|procedure)\b', re.IGNORECASE)
    class_pattern = re.compile(r'\b(class|struct|interface|trait|type|enum)\b', re.IGNORECASE)
    branch_pattern = re.compile(r'\b(if|else|elif|elsif|elseif|switch|match|case|when|guard)\b', re.IGNORECASE)
    loop_pattern = re.compile(r'\b(for|while|do|loop|repeat|each|foreach)\b', re.IGNORECASE)

    func_count = len(func_pattern.findall(code))
    class_count = len(class_pattern.findall(code))
    branch_count = len(branch_pattern.findall(code))
    loop_count = len(loop_pattern.findall(code))

    comment_count = _count_generic_comments(code, language)
    comment_ratio = comment_count / max(non_empty, 1)

    var_pattern = re.compile(r'\b(?:var|let|const|int|float|double|string|bool|char)\s+([a-zA-Z_]\w*)', re.IGNORECASE)
    assign_pattern = re.compile(r'([a-zA-Z_]\w*)\s*=\s*')
    names = [m.group(1) for m in var_pattern.finditer(code)]
    names.extend(m.group(1) for m in assign_pattern.finditer(code))

    single_letter = [n for n in names if _RE_SINGLE_LETTER.match(n) and n != '_']
    snake_names = sum(1 for n in names if _RE_SNAKE_CASE.match(n))
    camel_names = sum(1 for n in names if _RE_CAMEL_CASE.match(n) and not _RE_SNAKE_CASE.match(n))

    naming_convention = "snake_case" if snake_names >= camel_names else "camelCase"
    naming_score = max(snake_names, camel_names) / max(len(names), 1)

    stripped_code = _strip_string_literals(code)
    magic_nums: List[str] = []
    for match in _RE_MAGIC_NUM.finditer(stripped_code):
        val = float(match.group(1))
        if val not in _MAGIC_EXEMPT and not (val.is_integer() and int(val) in _MAGIC_EXEMPT):
            magic_nums.append(match.group(1))

    long_lines = sum(1 for l in lines if len(l) > 120)

    line_counts: Dict[str, int] = Counter()
    for l in lines:
        trimmed = l.strip()
        if trimmed:
            line_counts[trimmed] += 1
    duplicate_lines = sum(c - 1 for c in line_counts.values() if c > 1)

    indent_info = _analyze_indent(code)

    max_nesting = 0
    current_nesting = 0
    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            continue
        open_count = stripped.count('{') + stripped.count('(')
        close_count = stripped.count('}') + stripped.count(')')
        current_nesting += open_count - close_count
        if current_nesting < 0:
            current_nesting = 0
        if current_nesting > max_nesting:
            max_nesting = current_nesting

    result = {
        "functions": func_count,
        "classes": class_count,
        "branches": branch_count,
        "loops": loop_count,
        "total_names": len(names),
        "single_letter_vars": len(single_letter),
        "single_letter_examples": single_letter[:10],
        "naming_convention": naming_convention,
        "naming_consistency": round(naming_score, 2),
        "snake_case_count": snake_names,
        "camel_case_count": camel_names,
        "comment_count": comment_count,
        "comment_ratio": round(comment_ratio, 3),
        "magic_numbers": magic_nums[:20],
        "magic_number_count": len(magic_nums),
        "long_lines": long_lines,
        "max_nesting": max_nesting,
        "duplicate_lines": duplicate_lines,
        "indent": indent_info,
    }
    if syntax_error:
        result["syntax_error"] = syntax_error
    return result


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _build_report(analysis: Dict[str, Any], language: str, line_count: int, non_empty: int,
                  avg_line_length: float) -> str:
    sections: List[str] = []

    sections.append("=" * 60)
    sections.append("CODE PSYCHOLOGY REPORT")
    sections.append("=" * 60)
    sections.append(f"Language: {language}")
    sections.append(f"Total lines: {line_count} ({non_empty} non-empty)")
    sections.append(f"Average line length: {avg_line_length:.1f} chars")

    sections.append("")
    sections.append("--- STRUCTURE ---")
    sections.append(f"Functions: {analysis.get('functions', 0)}")
    sections.append(f"Classes: {analysis.get('classes', 0)}")
    sections.append(f"Branches (if/switch): {analysis.get('branches', 0)}")
    sections.append(f"Loops (for/while): {analysis.get('loops', 0)}")
    if 'try_blocks' in analysis:
        sections.append(f"Try blocks: {analysis['try_blocks']}")
    sections.append(f"Max nesting depth: {analysis.get('max_nesting', 0)}")

    indent = analysis.get('indent', {})
    indent_style = indent.get('style', 'unknown')
    indent_consistent = indent.get('consistent', True)
    indent_depth = indent.get('max_depth', 0)
    sections.append(f"Indentation: {indent_style} (consistent: {indent_consistent}, max depth: {indent_depth})")
    if not indent_consistent:
        sections.append("  WARNING: Mixed indentation detected")

    sections.append("")
    sections.append("--- NAMING ---")
    sections.append(f"Dominant convention: {analysis.get('naming_convention', 'N/A')}")
    sections.append(f"Consistency score: {analysis.get('naming_consistency', 0):.0%}")
    sections.append(f"snake_case names: {analysis.get('snake_case_count', 0)}")
    sections.append(f"camelCase names: {analysis.get('camel_case_count', 0)}")
    single_count = analysis.get('single_letter_vars', 0)
    single_examples = analysis.get('single_letter_examples', [])
    if single_count > 0:
        sections.append(f"Single-letter names: {single_count} ({', '.join(single_examples)})")

    sections.append("")
    sections.append("--- COMMENTS ---")
    sections.append(f"Comment lines: {analysis.get('comment_count', 0)}")
    sections.append(f"Comment ratio: {analysis.get('comment_ratio', 0):.1%}")
    ratio = analysis.get('comment_ratio', 0)
    if ratio < 0.05:
        sections.append("  WARNING: Very low comment ratio. Code may be hard to understand.")
    elif ratio > 0.5:
        sections.append("  NOTE: High comment ratio. Ensure comments add value, not noise.")
    elif ratio >= 0.1:
        sections.append("  OK: Reasonable comment coverage.")

    sections.append("")
    sections.append("--- COMPLEXITY ---")
    branches = analysis.get('branches', 0)
    loops = analysis.get('loops', 0)
    funcs = analysis.get('functions', 1)
    nesting = analysis.get('max_nesting', 0)
    complexity_score = max(0, 100 - (branches * 2) - (loops * 2) - (nesting * 5) - (single_count * 3))
    sections.append(f"Branches: {branches}, Loops: {loops}")
    sections.append(f"Single-letter vars: {single_count}")
    if nesting > 4:
        sections.append(f"  WARNING: Deep nesting ({nesting} levels). Consider refactoring.")

    sections.append("")
    sections.append("--- CODE HYGIENE ---")
    magic = analysis.get('magic_numbers', [])
    magic_count = analysis.get('magic_number_count', 0)
    long = analysis.get('long_lines', 0)
    dups = analysis.get('duplicate_lines', 0)
    sections.append(f"Magic numbers: {magic_count}" + (f" ({', '.join(magic[:8])})" if magic else ""))
    sections.append(f"Long lines (>120 chars): {long}")
    sections.append(f"Duplicate lines: {dups}")
    if magic_count > 3:
        sections.append("  WARNING: Many magic numbers. Extract to named constants.")
    if long > 0:
        sections.append(f"  NOTE: {long} line(s) exceed 120 characters.")
    if dups > 3:
        sections.append("  WARNING: Duplicate lines suggest potential for extraction.")

    if analysis.get('syntax_error'):
        sections.append("")
        sections.append("--- SYNTAX ---")
        sections.append(f"Parse error: {analysis['syntax_error']}")
        sections.append("  Analysis is regex-based due to syntax error.")

    sections.append("")
    sections.append("--- OVERALL SCORES ---")

    structure_score = max(0, min(100, 100 - (nesting * 8) - (5 if not indent_consistent else 0) - (max(0, branches - funcs * 2) * 3)))
    naming_score_val = analysis.get('naming_consistency', 0) * 100
    naming_deduction = min(30, single_count * 5)
    naming_score_val = max(0, naming_score_val - naming_deduction)
    comment_score = min(100, ratio * 300) if ratio < 0.4 else max(0, 150 - ratio * 100)
    hygiene_score = max(0, 100 - (magic_count * 4) - (long * 2) - (dups * 3))

    overall = structure_score * 0.3 + naming_score_val * 0.25 + comment_score * 0.2 + hygiene_score * 0.25

    sections.append(f"  Structure:    {_score_to_grade(structure_score)} ({structure_score:.0f}/100)")
    sections.append(f"  Naming:       {_score_to_grade(naming_score_val)} ({naming_score_val:.0f}/100)")
    sections.append(f"  Comments:     {_score_to_grade(comment_score)} ({comment_score:.0f}/100)")
    sections.append(f"  Hygiene:      {_score_to_grade(hygiene_score)} ({hygiene_score:.0f}/100)")
    sections.append(f"  OVERALL:      {_score_to_grade(overall)} ({overall:.0f}/100)")

    sections.append("")
    sections.append("--- PERSONALITY ---")
    personality_traits: List[str] = []
    if indent_consistent and naming_score_val > 70:
        personality_traits.append("Meticulous")
    elif not indent_consistent or naming_score_val < 40:
        personality_traits.append("Rushed")
    else:
        personality_traits.append("Pragmatic")
    if nesting > 3 or branches > funcs * 2:
        personality_traits.append("Complex thinker")
    if ratio < 0.03:
        personality_traits.append("Self-documenting believer")
    elif ratio > 0.3:
        personality_traits.append("Thorough documenter")
    if magic_count == 0 and long == 0 and dups == 0:
        personality_traits.append("Clean coder")
    if single_count > 5:
        personality_traits.append("Mathematician at heart")
    if funcs > 10:
        personality_traits.append("Modularist")
    if overall > 80:
        personality_traits.append("Experienced")
    elif overall < 40:
        personality_traits.append("Learning")

    sections.append(f"  {', '.join(personality_traits)}")
    sections.append("")
    sections.append("=" * 60)

    return '\n'.join(sections)


def execute(code: str, language: str = "python", **kwargs) -> SkillResult:
    if not code.strip():
        return SkillResult.fail("No code provided for analysis")

    lines = code.split('\n')
    line_count = len(lines)
    non_empty = sum(1 for l in lines if l.strip())
    avg_line_length = sum(len(l) for l in lines) / max(line_count, 1)

    if language.lower() in ("python", "py"):
        analysis = _analyze_python(code)
    else:
        analysis = _analyze_generic(code, language)

    report = _build_report(analysis, language, line_count, non_empty, avg_line_length)

    return SkillResult.ok(
        output=report,
        data={"needs_llm": False, "analysis": analysis},
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="code_psychologist",
        description="Analyzes code quality, patterns, and provides insights about the code and developer.",
        category="analysis",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Source code to analyze",
                },
                "language": {
                    "type": "string",
                    "description": "Programming language of the code",
                },
            },
            "required": ["code"],
        },
        handler=execute,
        timeout=30,
    ))
