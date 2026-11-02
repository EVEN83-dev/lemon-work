import ast
import re
from .models import SkillResult, SkillDef

METADATA = {
    "name": "code_reviewer",
    "version": "1.0.0",
    "category": "development",
    "description": "Code review assistant focusing on security, performance, style, or comprehensive analysis.",
}

_PATTERNS_SECURITY = [
    (r"eval\s*\(", "Use of eval() is a security risk - can execute arbitrary code", "Critical"),
    (r"exec\s*\(", "Use of exec() is a security risk - can execute arbitrary code", "Critical"),
    (r"__import__\s*\(", "Use of __import__() can bypass import controls", "Warning"),
    (r"subprocess\.call\s*\([^)]*shell\s*=\s*True", "subprocess with shell=True is vulnerable to injection", "Critical"),
    (r"os\.system\s*\(", "os.system() is vulnerable to command injection", "Critical"),
    (r"pickle\.load\s*\(", "pickle.load() can execute arbitrary code on deserialization", "Critical"),
    (r"yaml\.load\s*\(", "yaml.load() without Loader is unsafe - use yaml.safe_load()", "Warning"),
    (r"input\s*\(", "input() in Python 2 evaluates input - use raw_input() or validate", "Warning"),
    (r"open\s*\([^)]*[\"']w", "File write operation - verify path is not user-controlled", "Info"),
    (r"\.format\s*\(", "str.format() with user input may allow format string attacks", "Info"),
]

_PATTERNS_PERFORMANCE = [
    (r"\+\s*=\s*['\"]", "String concatenation in loop - consider using list and join()", "Warning"),
    (r"for\s+\w+\s+in\s+range\s*\(\s*len\s*\(", "Use enumerate() instead of range(len(...))", "Info"),
    (r"\.append\s*\([^)]*\)\s*$", "List append in loop - consider list comprehension", "Info"),
    (r"import\s+\*", "Wildcard import may slow startup and pollute namespace", "Warning"),
    (r"time\.sleep\s*\(\s*\d+\s*\)", "Blocking sleep() call - consider async alternative", "Info"),
]

_PATTERNS_STYLE = [
    (r"^([^\s].*)\{", "Line starts with non-space before brace - check formatting", "Info"),
    (r"except\s*:", "Bare except: catches all exceptions including SystemExit/KeyboardInterrupt", "Warning"),
    (r"except\s+Exception\s*:", "Broad exception handler - consider catching specific exceptions", "Info"),
    (r"pass\s*$", "Empty pass statement - consider adding implementation or docstring", "Info"),
]


def execute(
    code: str = "",
    language: str = "python",
    focus: str = "all",
    **kwargs,
) -> SkillResult:
    if not code.strip():
        return SkillResult.fail("No code provided for review")

    valid_focus = ("security", "performance", "style", "all")
    if focus not in valid_focus:
        return SkillResult.fail(f"Invalid focus '{focus}'. Must be one of: {valid_focus}")

    lines = code.split("\n")
    line_count = len(lines)

    if language.lower() == "python":
        findings = _review_python(code, lines, focus)
    else:
        findings = _review_generic(code, lines, focus)

    score = _compute_score(findings, line_count)
    output = _format_report(findings, language, focus, line_count, score)

    return SkillResult.ok(output=output, data={"needs_llm": False, "language": language, "focus": focus, "findings_count": len(findings), "score": score, "deprecated": True})


def _review_python(code: str, lines: list, focus: str) -> list:
    findings = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        findings.append({"severity": "Critical", "line": e.lineno or 0, "category": "syntax", "issue": f"Syntax error: {e.msg}", "fix": "Fix the syntax error before review"})
        return findings

    if focus in ("security", "all"):
        findings.extend(_check_security_ast(tree))
        findings.extend(_check_patterns(code, lines, _PATTERNS_SECURITY, "security"))

    if focus in ("performance", "all"):
        findings.extend(_check_performance_ast(tree))
        findings.extend(_check_patterns(code, lines, _PATTERNS_PERFORMANCE, "performance"))

    if focus in ("style", "all"):
        findings.extend(_check_style_ast(tree, lines))
        findings.extend(_check_patterns(code, lines, _PATTERNS_STYLE, "style"))

    findings.sort(key=lambda f: (0 if f["severity"] == "Critical" else 1 if f["severity"] == "Warning" else 2, f.get("line", 0)))
    return findings


def _check_security_ast(tree: ast.Module) -> list:
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = _get_call_name(node)
            if func_name == "eval":
                findings.append({"severity": "Critical", "line": node.lineno, "category": "security", "issue": "eval() executes arbitrary code", "fix": "Use ast.literal_eval() for safe evaluation of literals"})
            elif func_name == "exec":
                findings.append({"severity": "Critical", "line": node.lineno, "category": "security", "issue": "exec() executes arbitrary code", "fix": "Avoid exec(); refactor to use functions or config files"})
            elif func_name == "__import__":
                findings.append({"severity": "Warning", "line": node.lineno, "category": "security", "issue": "__import__() bypasses normal import mechanism", "fix": "Use importlib.import_module() instead"})
            elif func_name == "pickle.load" or func_name == "pickle.loads":
                findings.append({"severity": "Critical", "line": node.lineno, "category": "security", "issue": "pickle deserialization can execute arbitrary code", "fix": "Use json or a safe serialization format"})
            elif func_name == "os.system":
                findings.append({"severity": "Critical", "line": node.lineno, "category": "security", "issue": "os.system() is vulnerable to command injection", "fix": "Use subprocess.run() with shell=False and argument list"})
            elif func_name == "subprocess.call" or func_name == "subprocess.Popen":
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        findings.append({"severity": "Critical", "line": node.lineno, "category": "security", "issue": "subprocess with shell=True enables injection", "fix": "Use shell=False and pass arguments as a list"})
    return findings


def _check_performance_ast(tree: ast.Module) -> list:
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_str = ast.dump(node)
            if "List" in body_str and "append" in body_str:
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        name = _get_call_name(child)
                        if name and name.endswith(".append"):
                            if _is_in_loop(child, node):
                                findings.append({"severity": "Info", "line": child.lineno, "category": "performance", "issue": "list.append() in loop - consider list comprehension", "fix": "Use [expr for item in iterable] instead"})
                                break
    return findings


def _is_in_loop(target_node: ast.AST, parent: ast.AST) -> bool:
    for node in ast.walk(parent):
        if isinstance(node, (ast.For, ast.While)):
            for child in ast.walk(node):
                if child is target_node:
                    return True
    return False


def _check_style_ast(tree: ast.Module, lines: list) -> list:
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.body:
                continue
            first = node.body[0]
            has_docstring = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
            if not has_docstring:
                findings.append({"severity": "Info", "line": node.lineno, "category": "style", "issue": f"Function '{node.name}' lacks docstring", "fix": "Add a docstring describing the function's purpose"})

        if isinstance(node, ast.ClassDef):
            if node.body:
                first = node.body[0]
                has_docstring = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
                if not has_docstring:
                    findings.append({"severity": "Info", "line": node.lineno, "category": "style", "issue": f"Class '{node.name}' lacks docstring", "fix": "Add a class docstring"})

        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                findings.append({"severity": "Warning", "line": node.lineno, "category": "style", "issue": "Bare except: catches all exceptions including SystemExit", "fix": "Use 'except Exception:' or a more specific exception type"})

    for i, line in enumerate(lines, 1):
        if len(line) > 100:
            findings.append({"severity": "Info", "line": i, "category": "style", "issue": f"Line too long ({len(line)} chars)", "fix": "Break into multiple lines or use line continuation"})
        if line != line.rstrip():
            findings.append({"severity": "Info", "line": i, "category": "style", "issue": "Trailing whitespace", "fix": "Remove trailing spaces"})

    return findings


def _check_patterns(code: str, lines: list, patterns: list, category: str) -> list:
    findings = []
    for pattern, description, severity in patterns:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line):
                findings.append({"severity": severity, "line": i, "category": category, "issue": description, "fix": "See best practices for this pattern"})
    return findings


def _review_generic(code: str, lines: list, focus: str) -> list:
    findings = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if focus in ("security", "all"):
            if any(kw in stripped.lower() for kw in ("password", "secret", "api_key", "apikey", "token")):
                if "=" in stripped and not stripped.startswith(("//", "#", "/*")):
                    findings.append({"severity": "Warning", "line": i, "category": "security", "issue": "Possible hardcoded credential/secret", "fix": "Use environment variables or a secrets manager"})
            if "eval(" in stripped or "exec(" in stripped:
                findings.append({"severity": "Critical", "line": i, "category": "security", "issue": "eval/exec usage detected", "fix": "Avoid dynamic code execution"})
            if "SQL" in stripped or "sql" in stripped.lower():
                if "+" in stripped and ("SELECT" in stripped.upper() or "INSERT" in stripped.upper()):
                    findings.append({"severity": "Critical", "line": i, "category": "security", "issue": "Possible SQL injection via string concatenation", "fix": "Use parameterized queries"})
        if focus in ("style", "all"):
            if len(line) > 120:
                findings.append({"severity": "Info", "line": i, "category": "style", "issue": f"Line too long ({len(line)} chars)", "fix": "Break into multiple lines"})
        if focus in ("performance", "all"):
            if "sleep(" in stripped or "Sleep(" in stripped:
                findings.append({"severity": "Info", "line": i, "category": "performance", "issue": "Blocking sleep detected", "fix": "Consider async alternatives"})
    return findings


def _get_call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        parts = []
        current = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        parts.reverse()
        return ".".join(parts)
    return ""


def _compute_score(findings: list, line_count: int) -> int:
    if line_count == 0:
        return 10
    weights = {"Critical": 3, "Warning": 1, "Info": 0.2}
    penalty = sum(weights.get(f["severity"], 0) for f in findings)
    max_penalty = line_count * 0.5
    normalized = min(penalty / max(max_penalty, 1), 1.0)
    score = max(1, round(10 - normalized * 9))
    return score


def _format_report(findings: list, language: str, focus: str, line_count: int, score: int) -> str:
    parts = [
        "=== Code Review Report ===",
        "",
        f"Language: {language}",
        f"Lines of code: {line_count}",
        f"Focus: {focus}",
        f"Quality Score: {score}/10",
        f"Total findings: {len(findings)}",
        "",
    ]

    critical = [f for f in findings if f["severity"] == "Critical"]
    warnings = [f for f in findings if f["severity"] == "Warning"]
    info = [f for f in findings if f["severity"] == "Info"]

    parts.append(f"  Critical: {len(critical)}")
    parts.append(f"  Warning:  {len(warnings)}")
    parts.append(f"  Info:     {len(info)}")
    parts.append("")

    if critical:
        parts.append("[Critical]")
        for f in critical:
            parts.append(f"  Line {f.get('line', '?')}: {f['issue']}")
            parts.append(f"    Fix: {f['fix']}")
        parts.append("")

    if warnings:
        parts.append("[Warning]")
        for f in warnings:
            parts.append(f"  Line {f.get('line', '?')}: {f['issue']}")
            parts.append(f"    Fix: {f['fix']}")
        parts.append("")

    if info:
        parts.append("[Info]")
        for f in info:
            parts.append(f"  Line {f.get('line', '?')}: {f['issue']}")
        parts.append("")

    if not findings:
        parts.append("No issues found.")
        parts.append("")

    top_priorities = critical[:3] if critical else warnings[:3] if warnings else []
    if top_priorities:
        parts.append("[Top Priorities]")
        for i, f in enumerate(top_priorities, 1):
            parts.append(f"  {i}. {f['issue']} (line {f.get('line', '?')})")
        parts.append("")

    parts.append(f"Overall Quality Score: {score}/10")

    return "\n".join(parts)


def register(registry) -> None:
    registry.register(SkillDef(
        name="code_reviewer",
        description="[DEPRECATED] Use business.code_reviewer instead. Legacy code reviewer with static analysis.",
        category="development",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Source code to review",
                },
                "language": {
                    "type": "string",
                    "description": "Programming language of the code",
                },
                "focus": {
                    "type": "string",
                    "enum": ["security", "performance", "style", "all"],
                    "description": "Review focus area",
                },
            },
            "required": ["code"],
        },
        handler=execute,
        timeout=60,
        deprecated=True,
        deprecation_message="Superseded by business.code_reviewer (static analysis with AST/re, scoring system).",
    ))
