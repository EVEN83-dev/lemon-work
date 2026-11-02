import ast
import textwrap
from .models import SkillResult, SkillDef

METADATA = {
    "name": "code_formatter",
    "version": "1.0.0",
    "category": "development",
    "description": "Format code according to specified style guides (google, pep8, standard).",
}


def execute(
    code: str = "",
    language: str = "python",
    style: str = "pep8",
    **kwargs,
) -> SkillResult:
    if not code.strip():
        return SkillResult.fail("No code provided for formatting")

    valid_styles = ("google", "pep8", "standard")
    if style not in valid_styles:
        return SkillResult.fail(f"Invalid style '{style}'. Must be one of: {valid_styles}")

    if language.lower() == "python":
        result = _format_python(code, style)
    else:
        result = _format_generic(code, style, language)

    return SkillResult.ok(output=result["output"], data={"needs_llm": False, "language": language, "style": style, "issues_found": result.get("issues", [])})


def _format_python(code: str, style: str) -> dict:
    issues = []
    lines = code.split("\n")

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        issues.append(f"SyntaxError at line {e.lineno}: {e.msg}")
        return {"output": f"# FORMATTING FAILED - Syntax Error\n# {e.msg} at line {e.lineno}\n\n{code}", "issues": issues}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            if style in ("pep8", "standard") and name != name.lower():
                has_upper = any(c.isupper() for c in name)
                if isinstance(node, ast.ClassDef) and has_upper:
                    pass
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if name != _to_snake_case(name):
                        issues.append(f"Line {node.lineno}: Function '{name}' should use snake_case ({style})")
            if style == "google" and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if name != _to_camel_case(name) and not name.startswith("_"):
                    pass

    indent = "    " if style in ("pep8", "standard") else "  "
    max_line = 79 if style == "pep8" else (80 if style == "google" else 100)

    long_lines = []
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        if len(stripped) > max_line:
            long_lines.append(i)
            issues.append(f"Line {i}: Line too long ({len(stripped)} > {max_line})")

    trailing = [i for i, line in enumerate(lines, 1) if line != line.rstrip()]
    for i in trailing:
        issues.append(f"Line {i}: Trailing whitespace")

    blank_lines = []
    for i in range(1, len(lines)):
        if lines[i].strip() == "" and lines[i - 1].strip() == "":
            if style == "pep8" and i + 1 < len(lines) and lines[i + 1].strip() == "":
                blank_lines.append(i)
    for i in blank_lines:
        issues.append(f"Line {i}: Multiple consecutive blank lines")

    import_issues = _check_imports(tree, style)
    issues.extend(import_issues)

    formatted = _reformat_code(code, tree, style, indent)

    output_parts = [
        f"=== Code Formatting Report ({style}) ===",
        f"",
        f"Style: {style.upper()}",
        f"Issues found: {len(issues)}",
        f"",
    ]
    if issues:
        output_parts.append("Issues:")
        for issue in issues:
            output_parts.append(f"  - {issue}")
        output_parts.append("")
    output_parts.append("--- Formatted Code ---")
    output_parts.append(formatted)

    return {"output": "\n".join(output_parts), "issues": issues}


def _check_imports(tree: ast.Module, style: str) -> list:
    issues = []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)

    for imp in imports:
        if isinstance(imp, ast.Import):
            if len(imp.names) > 1:
                names = ", ".join(a.name for a in imp.names)
                issues.append(f"Line {imp.lineno}: Multiple imports on one line: '{names}' - use separate import statements")
        if isinstance(imp, ast.ImportFrom):
            for alias in imp.names:
                if alias.name == "*" and style in ("pep8", "google"):
                    issues.append(f"Line {imp.lineno}: Wildcard import 'from {imp.module} import *' - use explicit imports")

    return issues


def _reformat_code(code: str, tree: ast.Module, style: str, indent: str) -> str:
    lines = code.split("\n")
    result = []
    prev_blank = False
    in_docstring = False

    for i, line in enumerate(lines):
        stripped = line.rstrip()

        if stripped == "":
            if prev_blank:
                continue
            prev_blank = True
            result.append("")
            continue

        prev_blank = False
        result.append(stripped)

    return "\n".join(result)


def _to_snake_case(name: str) -> str:
    result = []
    for i, c in enumerate(name):
        if c.isupper():
            if i > 0 and name[i - 1].islower():
                result.append("_")
            result.append(c.lower())
        else:
            result.append(c)
    return "".join(result)


def _to_camel_case(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _format_generic(code: str, style: str, language: str) -> dict:
    issues = []
    lines = code.split("\n")

    max_line = 80 if style in ("pep8", "google") else 100
    for i, line in enumerate(lines, 1):
        if len(line.rstrip()) > max_line:
            issues.append(f"Line {i}: Line too long ({len(line.rstrip())} > {max_line})")
        if line != line.rstrip():
            issues.append(f"Line {i}: Trailing whitespace")

    cleaned = []
    prev_blank = False
    for line in lines:
        stripped = line.rstrip()
        if stripped == "":
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        cleaned.append(stripped)

    output_parts = [
        f"=== Code Formatting Report ({style}) ===",
        f"",
        f"Language: {language}",
        f"Style: {style.upper()}",
        f"Issues found: {len(issues)}",
        f"",
    ]
    if issues:
        output_parts.append("Issues:")
        for issue in issues:
            output_parts.append(f"  - {issue}")
        output_parts.append("")
    output_parts.append("--- Formatted Code ---")
    output_parts.append("\n".join(cleaned))

    return {"output": "\n".join(output_parts), "issues": issues}


def register(registry) -> None:
    registry.register(SkillDef(
        name="code_formatter",
        description="Format code according to style guides (google, pep8, standard).",
        category="development",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Source code to format",
                },
                "language": {
                    "type": "string",
                    "description": "Programming language of the code",
                },
                "style": {
                    "type": "string",
                    "enum": ["google", "pep8", "standard"],
                    "description": "Formatting style guide to apply",
                },
            },
            "required": ["code"],
        },
        handler=execute,
        timeout=30,
    ))
