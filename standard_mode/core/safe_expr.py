# -*- coding: utf-8 -*-
"""
safe_expr.py — 安全的数学表达式求值
====================================
替换 math_plotter / business_skills 中的裸 eval()：

问题：eval(expr, {'x': x, 'sin': numpy.sin, ...}) 会把 __builtins__ 自动带入 globals，
      攻击者可构造 "__import__('os').system('...')" 执行任意代码。

方案：AST 白名单校验，只允许：
  - 数字/字符串/名字/二元运算/一元运算/比较/逻辑/三元/下标/属性/调用
  - 可调用目标仅限白名单内的函数（sin/cos/sqrt/pow/abs/pi/e ...）
  - 名字仅限白名单内的变量（x/y 等）
禁止任何属性访问链（__class__ / __import__ / os.system 等）。

用法：
    from safe_expr import safe_math_eval
    y = safe_math_eval(expr, {"x": x, "sin": numpy.sin, "cos": numpy.cos})

失败时抛出 ValueError（含原因），调用方自行降级。
"""

import ast
import math
import numpy

# 允许的内置数学函数（白名单）
_ALLOWED_FUNCS = {
    "sin": numpy.sin, "cos": numpy.cos, "tan": numpy.tan,
    "arcsin": numpy.arcsin, "arccos": numpy.arccos, "arctan": numpy.arctan,
    "exp": numpy.exp, "log": numpy.log, "log10": numpy.log10, "log2": numpy.log2,
    "sqrt": numpy.sqrt, "abs": abs, "pow": pow,
    "floor": math.floor, "ceil": math.ceil, "round": round,
    "min": min, "max": max, "sum": sum,
    "degrees": math.degrees, "radians": math.radians,
    "sinh": numpy.sinh, "cosh": numpy.cosh, "tanh": numpy.tanh,
}

# 允许的常量
_ALLOWED_CONSTS = {
    "pi": math.pi, "e": math.e, "tau": math.tau,
    "inf": math.inf, "nan": math.nan,
}


def _verify(node, var_names, func_names):
    """递归校验 AST 节点，只允许白名单结构。"""
    if isinstance(node, ast.Expression):
        return _verify(node.body, var_names, func_names)

    if isinstance(node, ast.Constant):
        # 只允许数字与布尔（禁止字符串常量，避免 "__import__" 注入）
        if isinstance(node.value, bool):
            return
        if isinstance(node.value, (int, float, complex)):
            return
        raise ValueError(f"不允许的常量类型: {type(node.value).__name__}")

    if isinstance(node, ast.Name):
        # 仅允许白名单变量/常量，禁掉任何其他名字
        if node.id in var_names or node.id in _ALLOWED_CONSTS:
            return
        raise ValueError(f"不允许的变量: {node.id}")

    if isinstance(node, ast.BinOp):
        _verify(node.left, var_names, func_names)
        _verify(node.right, var_names, func_names)
        if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div,
                                ast.Pow, ast.Mod, ast.FloorDiv)):
            return
        raise ValueError(f"不允许的二元运算: {type(node.op).__name__}")

    if isinstance(node, ast.UnaryOp):
        _verify(node.operand, var_names, func_names)
        if isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            return
        raise ValueError(f"不允许的一元运算: {type(node.op).__name__}")

    if isinstance(node, (ast.Compare,)):
        for c in node.comparators:
            _verify(c, var_names, func_names)
        return

    if isinstance(node, ast.BoolOp):
        for v in node.values:
            _verify(v, var_names, func_names)
        return

    if isinstance(node, ast.IfExp):
        _verify(node.test, var_names, func_names)
        _verify(node.body, var_names, func_names)
        _verify(node.orelse, var_names, func_names)
        return

    if isinstance(node, ast.Call):
        # 函数名必须在白名单内，且不能是属性链调用（如 __import__、os.system）
        if not isinstance(node.func, ast.Name):
            raise ValueError("不允许的属性调用（禁止任意代码执行）")
        if node.func.id not in func_names and node.func.id not in _ALLOWED_FUNCS:
            raise ValueError(f"不允许的函数: {node.func.id}")
        for a in node.args:
            _verify(a, var_names, func_names)
        if node.keywords:
            raise ValueError("不允许的关键字参数")
        return

    if isinstance(node, ast.Subscript):
        # 仅允许对白名单变量做下标访问（如 x[0]），slice 本身也需通过校验
        _verify(node.value, var_names, func_names)
        sl = getattr(node, "slice", None)
        if sl is not None:
            if isinstance(sl, ast.Slice):
                for part in (sl.lower, sl.upper, sl.step):
                    if part is not None:
                        _verify(part, var_names, func_names)
            else:
                _verify(sl, var_names, func_names)
        return

    raise ValueError(f"不允许的表达式元素: {type(node).__name__}")


def safe_math_eval(expr, variables=None):
    """安全求值数学表达式。

    Args:
        expr: 表达式字符串（如 "sin(x) + x**2"）
        variables: 允许引用的变量名 → 值（如 {"x": 3.0}）

    Returns:
        数值结果

    Raises:
        ValueError: 表达式含白名单之外的语法/函数/变量
    """
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("表达式为空")

    variables = dict(variables or {})
    var_names = set(variables.keys())
    func_names = set(_ALLOWED_FUNCS.keys())

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"表达式语法错误: {e}") from e

    _verify(tree, var_names, func_names)

    # 合并命名空间，显式禁用 builtins
    namespace = {"__builtins__": {}}
    namespace.update(_ALLOWED_CONSTS)
    namespace.update(_ALLOWED_FUNCS)
    namespace.update(variables)

    return eval(compile(tree, "<safe_expr>", "eval"), namespace, {})
