# -*- coding: utf-8 -*-
"""
Skill: modern_python_toolchain — Python 工具链（蒸馏自 MiMo Code）
==================================================================
初始化 Python 项目，生成 pyproject.toml/Makefile/.gitignore，
支持 venv/uv/poetry。
"""

import json
import os
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "modern_python_toolchain",
    "description": "Python 工具链：初始化 Python 项目，生成 pyproject.toml/Makefile/.gitignore，支持 venv/uv/poetry。蒸馏自 MiMo Code。",
    "category": "system",
    "version": "1.0.0",
}


def execute(
    project_name: str = "",
    output_dir: str = "",
    python_version: str = "3.11",
    tool_manager: str = "uv",
    description: str = "",
    dependencies: str = "[]",
    dev_dependencies: str = "[]",
) -> SkillResult:
    """初始化 Python 项目

    Args:
        project_name: 项目名称
        output_dir: 输出目录
        python_version: Python 版本
        tool_manager: uv/poetry/pip
        description: 项目描述
        dependencies: JSON 依赖列表 ["requests", "flask"]
        dev_dependencies: JSON 开发依赖列表 ["pytest", "black"]
    """
    if not project_name:
        return SkillResult(success=False, error="project_name 参数为空")

    try:
        deps = json.loads(dependencies) if isinstance(dependencies, str) else dependencies
        dev_deps = json.loads(dev_dependencies) if isinstance(dev_dependencies, str) else dev_dependencies
    except json.JSONDecodeError:
        deps, dev_deps = [], []

    try:
        if not output_dir:
            output_dir = os.path.join(os.getcwd(), project_name)

        os.makedirs(output_dir, exist_ok=True)
        desc = description or f"{project_name} - Python project"
        files_created = []

        # 1. pyproject.toml
        if tool_manager == 'uv':
            pyproject = f"""[project]
name = "{project_name}"
version = "0.1.0"
description = "{desc}"
requires-python = ">={python_version}"
dependencies = {json.dumps(deps)}

[project.optional-dependencies]
dev = {json.dumps(dev_deps)}

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = {json.dumps(dev_deps)}

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
"""
        elif tool_manager == 'poetry':
            pyproject = f"""[tool.poetry]
name = "{project_name}"
version = "0.1.0"
description = "{desc}"
authors = []

[tool.poetry.dependencies]
python = "^{python_version}"
{''.join(f'{d} = "*"' + chr(10) for d in deps)}

[tool.poetry.group.dev.dependencies]
{''.join(f'{d} = "*"' + chr(10) for d in dev_deps)}

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
"""
        else:
            pyproject = f"""[project]
name = "{project_name}"
version = "0.1.0"
description = "{desc}"
requires-python = ">={python_version}"
dependencies = {json.dumps(deps)}

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"
"""

        path = os.path.join(output_dir, 'pyproject.toml')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(pyproject)
        files_created.append('pyproject.toml')

        # 2. Makefile
        makefile = f""".PHONY: install test lint format clean

install:
\t{tool_manager} sync

test:
\tpython -m pytest tests/ -v

lint:
\truff check src/

format:
\truff format src/

clean:
\trm -rf __pycache__ .pytest_cache .ruff_cache dist *.egg-info
"""
        path = os.path.join(output_dir, 'Makefile')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(makefile)
        files_created.append('Makefile')

        # 3. .gitignore
        gitignore = """__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/
.venv/
venv/
.env
.ruff_cache/
.pytest_cache/
.mypy_cache/
*.egg
"""
        path = os.path.join(output_dir, '.gitignore')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(gitignore)
        files_created.append('.gitignore')

        # 4. src/{project_name}/__init__.py
        src_dir = os.path.join(output_dir, 'src', project_name.replace('-', '_'))
        os.makedirs(src_dir, exist_ok=True)
        path = os.path.join(src_dir, '__init__.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f'"""{desc}"""\n\n__version__ = "0.1.0"\n')
        files_created.append(f'src/{project_name.replace("-", "_")}/__init__.py')

        # 5. tests/__init__.py
        tests_dir = os.path.join(output_dir, 'tests')
        os.makedirs(tests_dir, exist_ok=True)
        path = os.path.join(tests_dir, '__init__.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('')
        files_created.append('tests/__init__.py')

        return SkillResult(
            success=True,
            output=f"Python 项目已初始化: {project_name}\n目录: {output_dir}\n工具: {tool_manager}\n创建文件: {', '.join(files_created)}",
            data={'output_dir': output_dir, 'files': files_created, 'tool_manager': tool_manager},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"项目初始化失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="modern_python_toolchain",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "output_dir": {"type": "string", "description": "输出目录"},
                "python_version": {"type": "string", "description": "Python 版本", "default": "3.11"},
                "tool_manager": {"type": "string", "enum": ["uv", "poetry", "pip"], "description": "包管理工具", "default": "uv"},
                "description": {"type": "string", "description": "项目描述"},
                "dependencies": {"type": "string", "description": "JSON 依赖列表", "default": "[]"},
                "dev_dependencies": {"type": "string", "description": "JSON 开发依赖列表", "default": "[]"},
            },
            "required": ["project_name"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=15,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
