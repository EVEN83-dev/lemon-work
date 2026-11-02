# -*- coding: utf-8 -*-
"""
Skill: math_solver — 数学难题运算
=================================
支持符号计算（SymPy）：化简、解方程、积分、求导、极限、
矩阵运算、方程组。
"""

import json
import traceback
from typing import Dict, Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

# ---------- 元信息 ----------
METADATA = {
    "name": "math_solver",
    "description": "解数学难题：化简、解方程、积分、求导、极限、矩阵运算、方程组。支持符号计算。",
    "category": "math",
    "version": "1.0.0",
}


def _lazy_import(lib_name: str):
    try:
        mod = __import__(lib_name)
        for part in lib_name.split('.')[1:]:
            mod = getattr(mod, part)
        return mod
    except (ImportError, AttributeError):
        return None


def _lib_missing(lib_name: str) -> SkillResult:
    return SkillResult(
        success=False,
        error=f"依赖库 '{lib_name}' 未安装",
        output=f"请执行: pip install {lib_name}",
    )


# ---------- 核心处理函数 ----------
def execute(
    expression: str = "",
    operation: str = "simplify",
    variable: str = "x",
) -> SkillResult:
    """执行数学运算

    Args:
        expression: 数学表达式，如 'x**2 + 2*x + 1'
        operation: simplify/solve/integrate/diff/limit/matrix/equation
        variable: 运算变量，默认 x
    """
    if not expression:
        return SkillResult(success=False, error="expression 参数为空")

    sympy = _lazy_import('sympy')
    if sympy is None:
        return _lib_missing('sympy')

    try:
        x = sympy.Symbol(variable)
        ops = {
            'simplify':  lambda: sympy.simplify(sympy.sympify(expression)),
            'solve':     lambda: sympy.solve(sympy.sympify(expression), x),
            'integrate': lambda: sympy.integrate(sympy.sympify(expression), x),
            'diff':      lambda: sympy.diff(sympy.sympify(expression), x),
            'limit':     lambda: sympy.limit(sympy.sympify(expression), x, 0),
            'factor':    lambda: sympy.factor(sympy.sympify(expression)),
            'expand':    lambda: sympy.expand(sympy.sympify(expression)),
        }

        if operation == 'matrix':
            mat_data = json.loads(expression)
            M = sympy.Matrix(mat_data)
            return SkillResult(
                success=True,
                output=f"矩阵:\n{M}\n\n行列式: {M.det()}\n逆矩阵: {M.inv()}\n特征值: {M.eigenvals()}",
                data={'shape': list(M.shape), 'det': str(M.det())},
            )

        if operation == 'equation':
            eqs = [sympy.Eq(sympy.sympify(s.split('=')[0]), sympy.sympify(s.split('=')[1]))
                   for s in expression.split(';') if '=' in s]
            sols = sympy.solve(eqs, dict=True)
            return SkillResult(
                success=True,
                output=f"方程组解:\n{sols}",
                data={'solutions': [str(s) for s in sols]},
            )

        if operation not in ops:
            return SkillResult(success=False, error=f"未知操作: {operation}")

        result = ops[operation]()
        return SkillResult(
            success=True,
            output=f"{operation}({expression}, {variable}) =\n{result}",
            data={'result': str(result), 'latex': sympy.latex(result)},
        )

    except Exception as e:
        return SkillResult(success=False, error=f"数学运算失败: {e}", output=traceback.format_exc())


# ---------- 注册函数 ----------
def register(registry) -> None:
    registry.register(SkillDef(
        name="math_solver",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "数学表达式，如 'x**2 + 2*x + 1'"},
                "operation": {
                    "type": "string",
                    "enum": ["simplify", "solve", "integrate", "diff", "limit", "matrix", "equation"],
                    "description": "操作类型",
                },
                "variable": {"type": "string", "description": "运算变量，默认 x", "default": "x"},
            },
            "required": ["expression", "operation"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
