# -*- coding: utf-8 -*-
"""
Skill: math_plotter — 数学图像生成
===================================
2D 函数图 / 3D 曲面图 / 矩阵热图 / 散点图 / 柱状图 / 饼图。
输出 PNG + base64。

400V-1 修复（线程安全）:
  - 模块顶强制 matplotlib.use("Agg", force=True): 禁用 TkAgg GUI 后端，
    避免非 main 线程调用 plt.subplots() 触发
    "Starting a Matplotlib GUI outside of the main thread" 及
    Tcl_AsyncDelete / main thread is not in main loop 崩溃（exit 3）。
  - 默认输出改为 data/charts/ 落到版本化目录（非 tempfile 临时目录）。
  - dpi/图尺寸写入 SkillResult.data（下游渲染元信息复用）。
"""

import json
import os
import base64
import time
import traceback
from typing import Dict, Any

# 400V-1: 必须在首次 import pyplot 前设置后端为 Agg（无头），强制覆盖用户 rc。
# TkAgg 在 Qt worker 线程 initialize 时会创建 Tk root 引发 thread 崩溃。
import matplotlib
matplotlib.use("Agg", force=True)
# 下面才是 pyplot 导入（此时后端已锁定 Agg）
import matplotlib.pyplot as plt

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "math_plotter",
    "description": "生成数学图像：2D 函数图 / 3D 曲面图 / 矩阵热图 / 散点图 / 柱状图 / 饼图。输出 PNG + base64。",
    "category": "visual",
    "version": "1.0.0",
}

# 默认输出目录（相对于项目根），落到 charts 目录便于版本化与审查
_DEFAULT_CHARTS_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'data', 'charts'
)
try:
    os.makedirs(_DEFAULT_CHARTS_DIR, exist_ok=True)
except OSError:
    pass


def _lazy_import(lib_name: str):
    try:
        mod = __import__(lib_name)
        for part in lib_name.split('.')[1:]:
            mod = getattr(mod, part)
        return mod
    except (ImportError, AttributeError):
        return None


def _lib_missing(lib_name: str) -> SkillResult:
    return SkillResult(success=False, error=f"依赖库 '{lib_name}' 未安装", output=f"pip install {lib_name}")


def execute(
    expression: str = "",
    plot_type: str = "function",
    x_range: str = "-5,5",
    y_range: str = "",
    output_path: str = "",
    title: str = "",
) -> SkillResult:
    """生成数学图像（400V-1 后默认落到 data/charts/，无头后端）"""
    if not expression:
        return SkillResult(success=False, error="expression 参数为空")

    # matplotlib 已在模块顶 import（后端锁定 Agg），此处直接使用
    numpy = _lazy_import('numpy')
    if numpy is None:
        return _lib_missing('numpy')

    sympy = _lazy_import('sympy')

    try:
        x_min, x_max = [float(v) for v in x_range.split(',')]
        y_min, y_max = ([float(v) for v in y_range.split(',')] if y_range else (None, None))

        if not output_path:
            output_path = os.path.join(_DEFAULT_CHARTS_DIR, f"plot_{plot_type}_{int(time.time())}.png")

        try:
            plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
        except Exception:
            pass

        # 400V-1 记录图尺寸/dpi 用于 SkillResult.data
        PLOT_FIGSIZE = (8, 6)
        PLOT_DPI = 100

        fig, ax = plt.subplots(figsize=PLOT_FIGSIZE, dpi=PLOT_DPI)

        if plot_type == 'function':
            x = numpy.linspace(x_min, x_max, 400)
            if sympy:
                sym_expr = sympy.sympify(expression)
                f = sympy.lambdify('x', sym_expr, 'numpy')
                y = f(x)
            else:
                # 用 AST 白名单求值，替代裸 eval()（禁止任意代码执行）
                from safe_expr import safe_math_eval
                y = numpy.array([
                    safe_math_eval(expression, {'x': v, 'sin': numpy.sin, 'cos': numpy.cos,
                                                'exp': numpy.exp, 'log': numpy.log,
                                                'sqrt': numpy.sqrt, 'pi': numpy.pi, 'e': numpy.e})
                    for v in x
                ])
            ax.plot(x, y, 'b-', linewidth=2, label=expression)
            ax.set_xlabel('x'); ax.set_ylabel('y'); ax.grid(True, alpha=0.3); ax.legend()

        elif plot_type == 'surface3d':
            from mpl_toolkits.mplot3d import Axes3D
            fig = plt.figure(figsize=(10, 8), dpi=PLOT_DPI)
            ax = fig.add_subplot(111, projection='3d')
            x = numpy.linspace(x_min, x_max, 50)
            y = numpy.linspace(x_min, x_max, 50)
            X, Y = numpy.meshgrid(x, y)
            if sympy:
                sym_expr = sympy.sympify(expression)
                f = sympy.lambdify(('x', 'y'), sym_expr, 'numpy')
                Z = f(X, Y)
            else:
                from safe_expr import safe_math_eval
                _w, _h = X.shape
                Z = numpy.empty_like(X, dtype=float)
                for _i in range(_w):
                    for _j in range(_h):
                        Z[_i, _j] = safe_math_eval(
                            expression,
                            {'x': X[_i, _j], 'y': Y[_i, _j],
                             'sin': numpy.sin, 'cos': numpy.cos,
                             'sqrt': numpy.sqrt, 'pi': numpy.pi, 'e': numpy.e})
            ax.plot_surface(X, Y, Z, cmap='viridis', alpha=0.8)

        elif plot_type == 'matrix':
            mat = json.loads(expression)
            M = numpy.array(mat)
            im = ax.imshow(M, cmap='RdBu_r', aspect='auto')
            plt.colorbar(im, ax=ax)
            for i in range(M.shape[0]):
                for j in range(M.shape[1]):
                    ax.text(j, i, f"{M[i,j]:.2f}", ha='center', va='center')

        elif plot_type == 'scatter':
            points = json.loads(expression)
            xs = [p.get('x', 0) for p in points]
            ys = [p.get('y', 0) for p in points]
            ax.scatter(xs, ys, c='red', s=50, alpha=0.6)
            ax.grid(True, alpha=0.3)

        elif plot_type == 'bar':
            data = json.loads(expression)
            labels = list(data.keys()) if isinstance(data, dict) else [f'#{i}' for i in range(len(data))]
            values = list(data.values()) if isinstance(data, dict) else data
            ax.bar(labels, values, color='orange', alpha=0.7)

        elif plot_type == 'pie':
            data = json.loads(expression)
            labels = list(data.keys()) if isinstance(data, dict) else [f'#{i}' for i in range(len(data))]
            values = list(data.values()) if isinstance(data, dict) else data
            ax.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)

        else:
            return SkillResult(success=False, error=f"未知 plot_type: {plot_type}")

        if title:
            ax.set_title(title)
        plt.tight_layout()
        plt.savefig(output_path, dpi=PLOT_DPI, bbox_inches='tight')
        plt.close()

        with open(output_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')

        return SkillResult(
            success=True,
            output=f"图像已生成: {output_path}\n类型: {plot_type}\n表达式: {expression}",
            data={
                'path': output_path,
                'base64_full': b64,
                'plot_type': plot_type,
                # 400V-1: 图表元信息，下游渲染复用
                'dpi': PLOT_DPI,
                'figsize': list(PLOT_FIGSIZE),
            },
        )
    except Exception as e:
        return SkillResult(success=False, error=f"绘图失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="math_plotter",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "表达式或 JSON 数据"},
                "plot_type": {
                    "type": "string",
                    "enum": ["function", "surface3d", "matrix", "scatter", "bar", "pie"],
                    "description": "图像类型",
                },
                "x_range": {"type": "string", "description": "x 轴范围 min,max", "default": "-5,5"},
                "y_range": {"type": "string", "description": "y 轴范围（可选）"},
                "output_path": {"type": "string", "description": "输出 PNG 路径（默认 data/charts/）"},
                "title": {"type": "string", "description": "图标题"},
            },
            "required": ["expression", "plot_type"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
