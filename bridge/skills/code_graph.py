import ast
import os
from .models import SkillResult, SkillDef

METADATA = {
    "name": "code_graph",
    "version": "1.0.0",
    "category": "development",
    "description": "Generate code dependency graph, call tree, or structure visualization as ASCII/text.",
}


def execute(
    code: str = "",
    language: str = "python",
    graph_type: str = "dependency",
    **kwargs,
) -> SkillResult:
    if not code.strip():
        return SkillResult.fail("No code provided for graph generation")

    valid_graph_types = ("dependency", "call_tree", "structure")
    if graph_type not in valid_graph_types:
        return SkillResult.fail(f"Invalid graph_type '{graph_type}'. Must be one of: {valid_graph_types}")

    if language.lower() != "python":
        return _generic_graph(code, language, graph_type)

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return SkillResult.fail(f"Python syntax error at line {e.lineno}: {e.msg}")

    if graph_type == "dependency":
        output = _build_dependency_graph(tree, code)
    elif graph_type == "call_tree":
        output = _build_call_tree(tree, code)
    else:
        output = _build_structure_diagram(tree, code)

    return SkillResult.ok(output=output, data={"needs_llm": False, "language": language, "graph_type": graph_type})


def _build_dependency_graph(tree: ast.Module, code: str) -> str:
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({"module": alias.name, "asname": alias.asname, "line": node.lineno, "type": "stdlib_or_external"})
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports.append({"module": f"{mod}.{alias.name}", "asname": alias.asname, "line": node.lineno, "type": "from_import"})

    stdlib_modules = {
        "os", "sys", "ast", "json", "re", "math", "collections", "itertools",
        "functools", "datetime", "pathlib", "hashlib", "io", "textwrap",
        "typing", "dataclasses", "abc", "copy", "pprint", "logging",
        "unittest", "argparse", "csv", "sqlite3", "http", "urllib",
        "email", "html", "xml", "struct", "threading", "multiprocessing",
        "subprocess", "signal", "socket", "ssl", "tempfile", "shutil",
        "glob", "fnmatch", "random", "string", "operator", "enum",
        "numbers", "decimal", "fractions", "statistics", "time",
    }

    for imp in imports:
        top = imp["module"].split(".")[0]
        if top in stdlib_modules:
            imp["category"] = "stdlib"
        elif top.startswith("_"):
            imp["category"] = "internal"
        else:
            imp["category"] = "external"

    categories = {}
    for imp in imports:
        cat = imp.get("category", "external")
        categories.setdefault(cat, []).append(imp)

    lines = [
        "=== Dependency Graph ===",
        "",
        f"Total imports: {len(imports)}",
        f"  Stdlib: {len(categories.get('stdlib', []))}",
        f"  External: {len(categories.get('external', []))}",
        f"  Internal: {len(categories.get('internal', []))}",
        "",
    ]

    if categories.get("stdlib"):
        lines.append("[stdlib]")
        for imp in categories["stdlib"]:
            alias = f" as {imp['asname']}" if imp["asname"] else ""
            lines.append(f"  +- {imp['module']}{alias} (line {imp['line']})")
        lines.append("")

    if categories.get("external"):
        lines.append("[external]")
        for imp in categories["external"]:
            alias = f" as {imp['asname']}" if imp["asname"] else ""
            lines.append(f"  +- {imp['module']}{alias} (line {imp['line']})")
        lines.append("")

    if categories.get("internal"):
        lines.append("[internal]")
        for imp in categories["internal"]:
            alias = f" as {imp['asname']}" if imp["asname"] else ""
            lines.append(f"  +- {imp['module']}{alias} (line {imp['line']})")
        lines.append("")

    defined = _get_defined_names(tree)
    used_imports = set()
    used_names = _get_used_names(tree)
    for imp in imports:
        local_name = imp["asname"] or imp["module"].split(".")[-1]
        if local_name in used_names:
            used_imports.add(local_name)

    unused = [imp for imp in imports if (imp["asname"] or imp["module"].split(".")[-1]) not in used_names]

    if unused:
        lines.append("[potentially unused imports]")
        for imp in unused:
            lines.append(f"  +- {imp['module']} (line {imp['line']})")
        lines.append("")

    lines.append("Legend:")
    lines.append("  +- = imported module")
    lines.append("  [stdlib] = Python standard library")
    lines.append("  [external] = third-party package")
    lines.append("  [internal] = private/internal module")

    return "\n".join(lines)


def _build_call_tree(tree: ast.Module, code: str) -> str:
    functions = {}
    classes = {}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls = _extract_calls(node)
            functions[node.name] = {"line": node.lineno, "calls": calls, "decorators": [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list]}
        elif isinstance(node, ast.ClassDef):
            methods = {}
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    calls = _extract_calls(item)
                    methods[item.name] = {"line": item.lineno, "calls": calls}
            classes[node.name] = {"line": node.lineno, "methods": methods, "bases": [b.id if isinstance(b, ast.Name) else str(b) for b in node.bases]}

    all_callees = set()
    for fn_info in functions.values():
        all_callees.update(fn_info["calls"])
    for cls_info in classes.values():
        for meth_info in cls_info["methods"].values():
            all_callees.update(meth_info["calls"])

    entry_points = []
    leaf_functions = []
    for name, info in functions.items():
        if not info["calls"]:
            leaf_functions.append(name)
        if name not in all_callees:
            entry_points.append(name)

    lines = [
        "=== Call Tree ===",
        "",
        f"Top-level functions: {len(functions)}",
        f"Classes: {len(classes)}",
        f"Entry points (not called by others): {len(entry_points)}",
        f"Leaf functions (no calls): {len(leaf_functions)}",
        "",
    ]

    if entry_points:
        lines.append("[Entry Points]")
        for ep in entry_points:
            lines.append(f"  -> {ep} (line {functions[ep]['line']})")
        lines.append("")

    lines.append("[Function Call Tree]")
    for name, info in functions.items():
        dec = f" @{','.join(info['decorators'])}" if info["decorators"] else ""
        lines.append(f"{name}{dec} (line {info['line']})")
        if info["calls"]:
            for ci, call in enumerate(sorted(info["calls"])):
                prefix = "`-" if ci == len(info["calls"]) - 1 else "|-"
                lines.append(f"  {prefix} {call}")
        else:
            lines.append(f"  `- (leaf)")
        lines.append("")

    for cls_name, cls_info in classes.items():
        bases = f"({', '.join(cls_info['bases'])})" if cls_info["bases"] else ""
        lines.append(f"{cls_name}{bases} (line {cls_info['line']})")
        for meth_name, meth_info in cls_info["methods"].items():
            lines.append(f"  +- {meth_name} (line {meth_info['line']})")
            if meth_info["calls"]:
                for ci, call in enumerate(sorted(meth_info["calls"])):
                    prefix = "     `-" if ci == len(meth_info["calls"]) - 1 else "     |-"
                    lines.append(f"  {prefix} {call}")
            else:
                lines.append(f"     `- (leaf)")
        lines.append("")

    if leaf_functions:
        lines.append("[Leaf Functions]")
        for lf in leaf_functions:
            lines.append(f"  * {lf}")
        lines.append("")

    lines.append("Legend:")
    lines.append("  -> = entry point")
    lines.append("  |- = call branch")
    lines.append("  `- = last call / leaf")
    lines.append("  * = leaf function (makes no calls)")

    return "\n".join(lines)


def _build_structure_diagram(tree: ast.Module, code: str) -> str:
    lines = [
        "=== Code Structure ===",
        "",
    ]

    global_vars = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    global_vars.append({"name": target.id, "line": node.lineno, "private": target.id.startswith("_")})
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            global_vars.append({"name": node.target.id, "line": node.lineno, "private": node.target.id.startswith("_")})

    classes = []
    functions = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            cls = _analyze_class(node)
            classes.append(cls)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = _analyze_function(node)
            functions.append(fn)

    if global_vars:
        lines.append("[Module-level Variables]")
        for v in global_vars:
            vis = "private" if v["private"] else "public"
            lines.append(f"  +- {v['name']} ({vis}, line {v['line']})")
        lines.append("")

    if classes:
        lines.append("[Classes]")
        for cls in classes:
            bases = f" -> {', '.join(cls['bases'])}" if cls["bases"] else ""
            lines.append(f"{cls['name']}{bases} (line {cls['line']})")
            for attr in cls["attributes"]:
                vis = "private" if attr["private"] else "public"
                lines.append(f"  +- {attr['name']} ({vis} attribute)")
            for meth in cls["methods"]:
                vis = "private" if meth["private"] else "public"
                args = meth["args"]
                dec = f" @{','.join(meth['decorators'])}" if meth["decorators"] else ""
                lines.append(f"  +- {meth['name']}({args}) {vis}{dec}")
            if cls.get("inheritance_chain"):
                lines.append(f"  Inheritance: {' -> '.join(cls['inheritance_chain'])}")
            lines.append("")

    if functions:
        lines.append("[Functions]")
        for fn in functions:
            vis = "private" if fn["private"] else "public"
            args = fn["args"]
            dec = f" @{','.join(fn['decorators'])}" if fn["decorators"] else ""
            lines.append(f"  +- {fn['name']}({args}) ({vis}, line {fn['line']}){dec}")
        lines.append("")

    summary = {
        "classes": len(classes),
        "functions": len(functions),
        "total_methods": sum(len(c["methods"]) for c in classes),
        "total_attributes": sum(len(c["attributes"]) for c in classes),
        "global_vars": len(global_vars),
        "public_functions": sum(1 for f in functions if not f["private"]),
        "private_functions": sum(1 for f in functions if f["private"]),
    }

    lines.append("[Summary]")
    lines.append(f"  Classes: {summary['classes']}")
    lines.append(f"  Functions: {summary['functions']} ({summary['public_functions']} public, {summary['private_functions']} private)")
    lines.append(f"  Methods: {summary['total_methods']}")
    lines.append(f"  Attributes: {summary['total_attributes']}")
    lines.append(f"  Global variables: {summary['global_vars']}")
    lines.append("")
    lines.append("Legend:")
    lines.append("  +- = member")
    lines.append("  -> = inheritance/extends")

    return "\n".join(lines)


def _extract_calls(node: ast.AST) -> list:
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _call_name(child)
            if name and name not in calls:
                calls.append(name)
    return calls


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        parts = []
        current = call.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        parts.reverse()
        return ".".join(parts)
    return ""


def _get_defined_names(tree: ast.Module) -> dict:
    names = {"functions": [], "classes": [], "variables": []}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names["functions"].append(node.name)
        elif isinstance(node, ast.ClassDef):
            names["classes"].append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names["variables"].append(target.id)
    return names


def _get_used_names(tree: ast.Module) -> set:
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)
    return used


def _analyze_class(node: ast.ClassDef) -> dict:
    methods = []
    attributes = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_analyze_function(item))
        elif isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    attributes.append({"name": target.id, "private": target.id.startswith("_")})

    return {
        "name": node.name,
        "line": node.lineno,
        "bases": [b.id if isinstance(b, ast.Name) else str(b) for b in node.bases],
        "methods": methods,
        "attributes": attributes,
        "inheritance_chain": [node.name] + [b.id if isinstance(b, ast.Name) else str(b) for b in node.bases],
    }


def _analyze_function(node) -> dict:
    args = [a.arg for a in node.args.args if a.arg != "self"]
    return {
        "name": node.name,
        "line": node.lineno,
        "args": ", ".join(args),
        "private": node.name.startswith("_"),
        "decorators": [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list],
    }


def _generic_graph(code: str, language: str, graph_type: str) -> SkillResult:
    lines = code.split("\n")
    output_parts = [
        f"=== Code Graph ({graph_type}) ===",
        "",
        f"Language: {language}",
        f"Lines of code: {len(lines)}",
        "",
    ]

    if graph_type == "dependency":
        import_lines = [l for l in lines if l.strip().startswith(("import ", "from ", "#include", "require", "using "))]
        output_parts.append("[Detected Import/Dependency Lines]")
        for i, line in enumerate(lines, 1):
            if line.strip().startswith(("import ", "from ", "#include", "require", "using ")):
                output_parts.append(f"  line {i}: {line.strip()}")
        output_parts.append(f"Total detected dependencies: {len(import_lines)}")

    elif graph_type == "call_tree":
        func_lines = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if ("def " in stripped or "function " in stripped or
                    "func " in stripped or "fn " in stripped or
                    "class " in stripped or "struct " in stripped or
                    "interface " in stripped or "void " in stripped or
                    "public " in stripped or "private " in stripped):
                if not stripped.startswith("//") and not stripped.startswith("#"):
                    func_lines.append((i, stripped))
        output_parts.append("[Detected Function/Class Definitions]")
        for line_no, content in func_lines:
            output_parts.append(f"  line {line_no}: {content}")
        output_parts.append(f"Total detected definitions: {len(func_lines)}")

    else:
        brace_depth = 0
        max_depth = 0
        for line in lines:
            brace_depth += line.count("{") - line.count("}")
            max_depth = max(max_depth, brace_depth)
        non_blank = sum(1 for l in lines if l.strip())
        output_parts.append(f"Non-blank lines: {non_blank}")
        output_parts.append(f"Max nesting depth: {max_depth}")

    output_parts.append("")
    output_parts.append("Note: Full AST analysis only available for Python. Generic analysis provided.")

    return SkillResult.ok(output="\n".join(output_parts), data={"needs_llm": False, "language": language, "graph_type": graph_type})


def register(registry) -> None:
    registry.register(SkillDef(
        name="code_graph",
        description="Generate code dependency graph, call tree, or structure visualization as ASCII/text.",
        category="development",
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
                "graph_type": {
                    "type": "string",
                    "enum": ["dependency", "call_tree", "structure"],
                    "description": "Type of graph to generate",
                },
            },
            "required": ["code"],
        },
        handler=execute,
        timeout=60,
    ))
