# -*- coding: utf-8 -*-
"""
Skill: test_generator — 自动生成单元测试
==========================================
基于代码结构（AST）生成 unittest/pytest 测试模板。
"""

import ast
import os
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "test_generator",
    "description": "自动生成单元测试：基于代码结构（AST）生成 unittest/pytest 测试模板",
    "category": "code",
    "version": "1.0.0",
}


def execute(
    code: str = "",
    file_path: str = "",
    framework: str = "pytest",
    output_path: str = "",
) -> SkillResult:
    """生成单元测试模板

    Args:
        code: 源代码
        file_path: 源文件路径
        framework: pytest/unittest
        output_path: 输出测试文件路径
    """
    if not code and not file_path:
        return SkillResult(success=False, error="code 或 file_path 必须有一个")

    try:
        if file_path and not code:
            if not os.path.exists(file_path):
                return SkillResult(success=False, error=f"文件不存在: {file_path}")
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                code = f.read()

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return SkillResult(success=False, error=f"代码语法错误: {e}")

        # 提取函数和类
        functions = []
        classes = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
                args = [a.arg for a in node.args.args if a.arg != 'self']
                functions.append({'name': node.name, 'args': args, 'line': node.lineno})
            elif isinstance(node, ast.ClassDef):
                methods = []
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and not item.name.startswith('_'):
                        args = [a.arg for a in item.args.args if a.arg != 'self']
                        methods.append({'name': item.name, 'args': args})
                classes.append({'name': node.name, 'methods': methods})

        # 模块名
        module_name = os.path.splitext(os.path.basename(file_path))[0] if file_path else 'module'

        # 生成测试代码
        if framework == 'pytest':
            test_code = _generate_pytest(module_name, functions, classes)
        else:
            test_code = _generate_unittest(module_name, functions, classes)

        if output_path:
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(test_code)

        return SkillResult(
            success=True,
            output=f"测试模板已生成: {len(functions)} 个函数, {len(classes)} 个类\n框架: {framework}",
            data={'test_code': test_code, 'functions': functions, 'classes': classes, 'framework': framework},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"测试生成失败: {e}", output=traceback.format_exc())


def _generate_pytest(module_name: str, functions: list, classes: list) -> str:
    lines = [f'# -*- coding: utf-8 -*-', f'"""自动生成的 pytest 测试 — {module_name}"""', '', f'import pytest', f'from {module_name} import *', '']

    for func in functions:
        lines.append(f'def test_{func["name"]}():')
        lines.append(f'    """测试 {func["name"]}"""')
        args_str = ', '.join([f'# {a}=TODO' for a in func['args']]) if func['args'] else ''
        lines.append(f'    # TODO: 设置测试参数')
        lines.append(f'    # result = {func["name"]}(...)')
        lines.append(f'    # assert result == expected')
        lines.append('')

    for cls in classes:
        lines.append(f'class Test{cls["name"]}:')
        lines.append(f'    """测试 {cls["name"]} 类"""')
        lines.append('')
        lines.append(f'    @pytest.fixture')
        lines.append(f'    def instance(self):')
        lines.append(f'        return {cls["name"]}()')
        lines.append('')
        for method in cls['methods']:
            lines.append(f'    def test_{method["name"]}(self, instance):')
            lines.append(f'        """测试 {method["name"]}"""')
            lines.append(f'        # result = instance.{method["name"]}(...)')
            lines.append(f'        # assert result == expected')
            lines.append('')
        if not cls['methods']:
            lines.append(f'    def test_instantiation(self):')
            lines.append(f'        obj = {cls["name"]}()')
            lines.append(f'        assert obj is not None')
            lines.append('')

    return '\n'.join(lines)


def _generate_unittest(module_name: str, functions: list, classes: list) -> str:
    lines = [f'# -*- coding: utf-8 -*-', f'"""自动生成的 unittest 测试 — {module_name}"""', '',
             f'import unittest', f'from {module_name} import *', '',
             f'class Test{module_name.title().replace("_", "")}(unittest.TestCase):', '']

    for func in functions:
        lines.append(f'    def test_{func["name"]}(self):')
        lines.append(f'        """测试 {func["name"]}"""')
        lines.append(f'        # result = {func["name"]}(...)')
        lines.append(f'        # self.assertEqual(result, expected)')
        lines.append('')

    for cls in classes:
        lines.append(f'    def test_{cls["name"].lower()}_creation(self):')
        lines.append(f'        """测试 {cls["name"]} 实例化"""')
        lines.append(f'        obj = {cls["name"]}()')
        lines.append(f'        self.assertIsNotNone(obj)')
        lines.append('')
        for method in cls['methods']:
            lines.append(f'    def test_{cls["name"].lower()}_{method["name"]}(self):')
            lines.append(f'        """测试 {cls["name"]}.{method["name"]}"""')
            lines.append(f'        obj = {cls["name"]}()')
            lines.append(f'        # result = obj.{method["name"]}(...)')
            lines.append(f'        # self.assertEqual(result, expected)')
            lines.append('')

    lines.append(f'if __name__ == "__main__":')
    lines.append(f'    unittest.main()')

    return '\n'.join(lines)


def register(registry) -> None:
    registry.register(SkillDef(
        name="test_generator",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "源代码"},
                "file_path": {"type": "string", "description": "源文件路径"},
                "framework": {"type": "string", "enum": ["pytest", "unittest"], "description": "测试框架", "default": "pytest"},
                "output_path": {"type": "string", "description": "输出测试文件路径"},
            },
        },
        handler=execute,
        category=METADATA["category"],
        timeout=15,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
