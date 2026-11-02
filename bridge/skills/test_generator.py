import ast
import textwrap
from collections import Counter

from .models import SkillResult, SkillDef

METADATA = {
    "name": "test_generator",
    "version": "1.0.0",
    "category": "development",
    "description": "Generate test cases for code using pytest, jest, or junit frameworks.",
}


def execute(
    code: str = "",
    language: str = "python",
    test_framework: str = "pytest",
    coverage_target: int = 80,
    **kwargs,
) -> SkillResult:
    if not code.strip():
        return SkillResult.fail("No code provided for test generation")

    valid_frameworks = ("pytest", "jest", "junit")
    if test_framework not in valid_frameworks:
        return SkillResult.fail("Invalid test_framework '" + test_framework + "'. Must be one of: " + str(valid_frameworks))

    if coverage_target <= 0 or coverage_target > 100:
        return SkillResult.fail("coverage_target must be between 1 and 100")

    analysis = _analyze_code(code, language)
    test_code = _generate_test_code(code, language, test_framework, coverage_target, analysis)

    return SkillResult.ok(
        output=test_code,
        data={
            "needs_llm": False,
            "language": language,
            "test_framework": test_framework,
            "coverage_target": coverage_target,
            "functions_found": analysis.get("functions", []),
            "classes_found": analysis.get("classes", []),
        },
    )


def _analyze_code(code: str, language: str) -> dict:
    result = {"functions": [], "classes": [], "imports": [], "parseable": False}

    if language == "python":
        try:
            tree = ast.parse(code)
            result["parseable"] = True
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    args = [a.arg for a in node.args.args if a.arg != "self"]
                    result["functions"].append({
                        "name": node.name,
                        "args": args,
                        "line": node.lineno,
                        "has_return": any(isinstance(n, ast.Return) for n in ast.walk(node)),
                    })
                elif isinstance(node, ast.ClassDef):
                    methods = []
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            margs = [a.arg for a in item.args.args if a.arg != "self"]
                            methods.append({"name": item.name, "args": margs})
                    result["classes"].append({
                        "name": node.name,
                        "methods": methods,
                        "line": node.lineno,
                    })
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        result["imports"].append(node.module)
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            result["imports"].append(alias.name)
        except SyntaxError:
            result["parseable"] = False
    else:
        lines = code.strip().split("\n")
        for line in lines:
            stripped = line.strip()
            if language == "javascript" or language == "typescript":
                if stripped.startswith("function ") or "function " in stripped:
                    fname = stripped.split("function ")[1].split("(")[0].strip()
                    if fname:
                        result["functions"].append({"name": fname, "args": [], "line": 0})
                elif stripped.startswith("const ") and "=>" in stripped:
                    fname = stripped.split("const ")[1].split("=")[0].strip()
                    if fname:
                        result["functions"].append({"name": fname, "args": [], "line": 0})
                elif stripped.startswith("class "):
                    cname = stripped.split("class ")[1].split("{")[0].split("extends")[0].strip()
                    if cname:
                        result["classes"].append({"name": cname, "methods": [], "line": 0})
            elif language == "java":
                if "public class " in stripped or "class " in stripped:
                    parts = stripped.split("class ")
                    if len(parts) > 1:
                        cname = parts[1].split("{")[0].split("extends")[0].split("implements")[0].strip()
                        if cname:
                            result["classes"].append({"name": cname, "methods": [], "line": 0})

    return result


def _generate_test_code(code: str, language: str, test_framework: str, coverage_target: int, analysis: dict) -> str:
    if test_framework == "pytest":
        return _generate_pytest(code, analysis, coverage_target)
    elif test_framework == "jest":
        return _generate_jest(code, analysis, coverage_target)
    elif test_framework == "junit":
        return _generate_junit(code, analysis, coverage_target)
    return ""


def _generate_pytest(code: str, analysis: dict, coverage_target: int) -> str:
    lines = []
    lines.append("import pytest")

    top_imports = analysis.get("imports", [])
    if top_imports:
        for mod in top_imports[:5]:
            lines.append("import " + mod)

    lines.append("")
    lines.append("")

    for cls_info in analysis.get("classes", []):
        cname = cls_info["name"]
        lines.append("class Test" + cname + ":")
        lines.append("")
        lines.append("    @pytest.fixture")
        lines.append("    def instance(self):")
        lines.append("        return " + cname + "()")
        lines.append("")

        for method in cls_info.get("methods", []):
            if method["name"].startswith("_"):
                continue
            mname = method["name"]
            args = method["args"]

            lines.append("    def test_" + mname + "_normal(self, instance):")
            if args:
                lines.append("        result = instance." + mname + "(" + ", ".join(["None"] * len(args)) + ")")
            else:
                lines.append("        result = instance." + mname + "()")
            lines.append("        assert result is not None")
            lines.append("")

            lines.append("    def test_" + mname + "_edge_case(self, instance):")
            if args:
                edge_args = []
                for a in args:
                    edge_args.append("None")
                lines.append("        with pytest.raises((TypeError, ValueError, AttributeError)):")
                lines.append("            instance." + mname + "(" + ", ".join(edge_args) + ")")
            else:
                lines.append("        result = instance." + mname + "()")
                lines.append("        assert result is not None")
            lines.append("")

    for func_info in analysis.get("functions", []):
        fname = func_info["name"]
        if fname.startswith("_"):
            continue
        args = func_info["args"]

        lines.append("def test_" + fname + "_normal():")
        if args:
            lines.append("    result = " + fname + "(" + ", ".join(["None"] * len(args)) + ")")
        else:
            lines.append("    result = " + fname + "()")
        lines.append("    assert result is not None")
        lines.append("")

        lines.append("def test_" + fname + "_with_invalid_input():")
        lines.append("    with pytest.raises((TypeError, ValueError)):")
        if args:
            lines.append("        " + fname + "(" + ", ".join(["None"] * len(args)) + ")")
        else:
            lines.append("        " + fname + "()")
        lines.append("")

        if func_info.get("has_return"):
            lines.append("def test_" + fname + "_return_type():")
            if args:
                lines.append("    result = " + fname + "(" + ", ".join(["None"] * len(args)) + ")")
            else:
                lines.append("    result = " + fname + "()")
            lines.append("    assert result is not None")
            lines.append("")

    if not analysis.get("classes") and not analysis.get("functions"):
        lines.append("def test_module_imports():")
        lines.append("    pass")
        lines.append("")
        lines.append("def test_module_basic():")
        lines.append("    assert True")
        lines.append("")

    lines.append("# Coverage target: " + str(coverage_target) + "%")
    lines.append("# Run: pytest test_module.py --cov --cov-report=term-missing")

    return "\n".join(lines)


def _generate_jest(code: str, analysis: dict, coverage_target: int) -> str:
    lines = []
    lines.append("// Jest test suite")
    lines.append("// Coverage target: " + str(coverage_target) + "%")
    lines.append("")

    for cls_info in analysis.get("classes", []):
        cname = cls_info["name"]
        lines.append("describe('" + cname + "', () => {")
        lines.append("  let instance;")
        lines.append("  beforeEach(() => {")
        lines.append("    instance = new " + cname + "();")
        lines.append("  });")
        lines.append("")

        for method in cls_info.get("methods", []):
            if method["name"].startswith("_"):
                continue
            mname = method["name"]
            lines.append("  describe('" + mname + "', () => {")
            lines.append("    it('should work with normal input', () => {")
            lines.append("      const result = instance." + mname + "();")
            lines.append("      expect(result).toBeDefined();")
            lines.append("    });")
            lines.append("")
            lines.append("    it('should handle edge cases', () => {")
            lines.append("      expect(() => instance." + mname + "(null)).toThrow();")
            lines.append("    });")
            lines.append("  });")
            lines.append("")

        lines.append("});")
        lines.append("")

    for func_info in analysis.get("functions", []):
        fname = func_info["name"]
        if fname.startswith("_"):
            continue
        lines.append("describe('" + fname + "', () => {")
        lines.append("  it('should work with normal input', () => {")
        lines.append("    const result = " + fname + "();")
        lines.append("    expect(result).toBeDefined();")
        lines.append("  });")
        lines.append("")
        lines.append("  it('should handle invalid input', () => {")
        lines.append("    expect(() => " + fname + "(null)).toThrow();")
        lines.append("  });")
        lines.append("});")
        lines.append("")

    if not analysis.get("classes") and not analysis.get("functions"):
        lines.append("describe('module', () => {")
        lines.append("  it('should be importable', () => {")
        lines.append("    expect(true).toBe(true);")
        lines.append("  });")
        lines.append("});")
        lines.append("")

    lines.append("// Run: npx jest --coverage --coverageThreshold='{\"global\":{\"branches\":" + str(coverage_target) + ",\"functions\":" + str(coverage_target) + ",\"lines\":" + str(coverage_target) + "}}'")

    return "\n".join(lines)


def _generate_junit(code: str, analysis: dict, coverage_target: int) -> str:
    lines = []
    lines.append("import org.junit.jupiter.api.*;")
    lines.append("import static org.junit.jupiter.api.Assertions.*;")
    lines.append("")

    test_class = "GeneratedTest"
    if analysis.get("classes"):
        test_class = analysis["classes"][0]["name"] + "Test"

    lines.append("@DisplayName(\"Generated tests - coverage target: " + str(coverage_target) + "%\")")
    lines.append("class " + test_class + " {")
    lines.append("")

    for cls_info in analysis.get("classes", []):
        for method in cls_info.get("methods", []):
            if method["name"].startswith("_"):
                continue
            mname = method["name"]
            lines.append("    @Test")
            lines.append("    @DisplayName(\"Test " + mname + " with normal input\")")
            lines.append("    void test" + mname[0].upper() + mname[1:] + "Normal() {")
            lines.append("        // TODO: Initialize instance and call " + mname)
            lines.append("        assertDoesNotThrow(() -> {")
            lines.append("            // instance." + mname + "();")
            lines.append("        });")
            lines.append("    }")
            lines.append("")
            lines.append("    @Test")
            lines.append("    @DisplayName(\"Test " + mname + " with invalid input\")")
            lines.append("    void test" + mname[0].upper() + mname[1:] + "InvalidInput() {")
            lines.append("        assertThrows(IllegalArgumentException.class, () -> {")
            lines.append("            // instance." + mname + "(null);")
            lines.append("        });")
            lines.append("    }")
            lines.append("")

    for func_info in analysis.get("functions", []):
        fname = func_info["name"]
        if fname.startswith("_"):
            continue
        lines.append("    @Test")
        lines.append("    @DisplayName(\"Test " + fname + " with normal input\")")
        lines.append("    void test" + fname[0].upper() + fname[1:] + "Normal() {")
        lines.append("        assertDoesNotThrow(() -> {")
        lines.append("            // " + fname + "();")
        lines.append("        });")
        lines.append("    }")
        lines.append("")

    if not analysis.get("classes") and not analysis.get("functions"):
        lines.append("    @Test")
        lines.append("    @DisplayName(\"Basic module test\")")
        lines.append("    void testModuleImport() {")
        lines.append("        assertTrue(true);")
        lines.append("    }")
        lines.append("")

    lines.append("}")
    lines.append("")
    lines.append("// Run: mvn test -Djacoco.threshold=" + str(coverage_target))

    return "\n".join(lines)


def register(registry) -> None:
    registry.register(SkillDef(
        name="test_generator",
        description="[DEPRECATED] Use business.test_generator instead. Legacy AST-based test generator.",
        category="development",
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Source code to generate tests for",
                },
                "language": {
                    "type": "string",
                    "description": "Programming language of the code",
                },
                "test_framework": {
                    "type": "string",
                    "enum": ["pytest", "jest", "junit"],
                    "description": "Testing framework to use",
                },
                "coverage_target": {
                    "type": "integer",
                    "description": "Target code coverage percentage (1-100)",
                },
            },
            "required": ["code"],
        },
        handler=execute,
        timeout=60,
        deprecated=True,
        deprecation_message="Superseded by business.test_generator (AST-based test generation with real code output).",
    ))
