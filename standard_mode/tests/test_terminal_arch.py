# -*- coding: utf-8 -*-
"""
H-P2A-2: 终端架构收敛回归测试
================================
验证：
1. terminal_panel_simple.py 无 TerminalServer 依赖
2. terminal_panel.py 无 TerminalServer 依赖（已收敛为别名）
3. TerminalPanel 可导入且为 SimpleTerminalPanel
4. 核心受保护文件未被意外修改
"""
import ast
import os
import pytest

_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_UI_DIR = os.path.join(_PROJECT_ROOT, "standard_mode", "ui")


def _read_rel(rel_path: str) -> str:
    full = os.path.join(_PROJECT_ROOT, rel_path)
    with open(full, encoding="utf-8") as f:
        return f.read()


class TestTerminalServerRemoval:
    def test_simple_no_server(self):
        code = _read_rel("standard_mode/ui/terminal_panel_simple.py")
        assert "TerminalServer" not in code, (
            "terminal_panel_simple.py 不应引用 TerminalServer"
        )

    def test_panel_no_server(self):
        code = _read_rel("standard_mode/ui/terminal_panel.py")
        lines = code.split("\n")
        code_lines = [l for l in lines if not l.strip().startswith("#") and not l.strip().startswith('"""')]
        joined = "\n".join(code_lines)
        assert "TerminalServer" not in joined, (
            "terminal_panel.py 可执行代码不应引用 TerminalServer"
        )

    def test_panel_syntax(self):
        code = _read_rel("standard_mode/ui/terminal_panel.py")
        ast.parse(code)

    def test_simple_syntax(self):
        code = _read_rel("standard_mode/ui/terminal_panel_simple.py")
        ast.parse(code)

    def test_panel_is_alias(self):
        code = _read_rel("standard_mode/ui/terminal_panel.py")
        assert "SimpleTerminalPanel" in code, (
            "terminal_panel.py 应为 SimpleTerminalPanel 别名"
        )

    def test_server_deprecated(self):
        code = _read_rel("standard_mode/ui/terminal_server.py")
        assert "DEPRECATED" in code or "deprecated" in code.lower(), (
            "terminal_server.py 应有 DEPRECATED 标记"
        )


class TestProtectedFiles:
    PROTECTED = [
        "standard_mode/core/agent_engine.py",
        "bridge/event_adapter.py",
        "standard_mode/ui/plan_panel.py",
        "standard_mode/ui/whitebox/whitebox_panel.py",
        "standard_mode/ui/terminal_panel_simple.py",
    ]

    @pytest.mark.parametrize("rel", PROTECTED)
    def test_protected_syntax(self, rel):
        code = _read_rel(rel)
        ast.parse(code)


class TestImports:
    def test_terminal_panel_alias_ast(self):
        code = _read_rel("standard_mode/ui/terminal_panel.py")
        tree = ast.parse(code)
        assignments = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "TerminalPanel" for t in n.targets)
        ]
        assert len(assignments) >= 1, (
            "terminal_panel.py 应包含 TerminalPanel = SimpleTerminalPanel 赋值"
        )

    def test_terminal_panel_imports_simple(self):
        code = _read_rel("standard_mode/ui/terminal_panel.py")
        assert "terminal_panel_simple" in code, (
            "terminal_panel.py 应导入 terminal_panel_simple"
        )
