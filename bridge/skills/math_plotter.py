import os
import tempfile

from .models import SkillResult, SkillDef

METADATA = {
    "name": "math_plotter",
    "version": "1.0.0",
    "category": "math",
    "description": "Generates plots from math expressions using matplotlib.",
}


def execute(expression: str, x_range: str = "-10,10", plot_type: str = "line", **kwargs) -> SkillResult:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return SkillResult.fail("matplotlib/numpy is not installed. Install with: pip install matplotlib numpy")

    try:
        parts = x_range.split(",")
        if len(parts) != 2:
            return SkillResult.fail("x_range must be in format 'min,max' (e.g. '-10,10')")
        x_min, x_max = float(parts[0]), float(parts[1])

        x = np.linspace(x_min, x_max, 500)

        allowed_names = {"x": x, "np": np, "sin": np.sin, "cos": np.cos,
                         "tan": np.tan, "exp": np.exp, "log": np.log,
                         "sqrt": np.sqrt, "abs": np.abs, "pi": np.pi}
        y = eval(expression, {"__builtins__": {}}, allowed_names)

        fig, ax = plt.subplots()

        if plot_type == "scatter":
            step = max(1, len(x) // 50)
            ax.scatter(x[::step], y[::step])
        elif plot_type == "bar":
            step = max(1, len(x) // 20)
            ax.bar(x[::step], y[::step], width=(x_max - x_min) / 20)
        else:
            ax.plot(x, y)

        ax.set_xlabel("x")
        ax.set_ylabel("y")
        ax.set_title(f"Plot: {expression}")
        ax.grid(True)

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=tempfile.gettempdir())
        tmp_path = tmp.name
        tmp.close()
        fig.savefig(tmp_path, dpi=100, bbox_inches="tight")
        plt.close(fig)

        return SkillResult.ok(output=tmp_path, data={"file_path": tmp_path, "format": "png"})
    except Exception as e:
        return SkillResult.fail(f"Plotter error: {e}")


def register(registry) -> None:
    registry.register(SkillDef(
        name="math_plotter",
        description="[DEPRECATED] Use business.math_plotter instead. Legacy 3-type plotter (line/scatter/bar).",
        category="math",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Math expression to plot (e.g. 'sin(x)', 'x**2')",
                },
                "x_range": {
                    "type": "string",
                    "description": "X-axis range as 'min,max' (e.g. '-10,10')",
                },
                "plot_type": {
                    "type": "string",
                    "enum": ["line", "scatter", "bar"],
                    "description": "Type of plot to generate",
                },
            },
            "required": ["expression"],
        },
        handler=execute,
        timeout=30,
        deprecated=True,
        deprecation_message="Superseded by business.math_plotter (6 types: function/surface3d/matrix/scatter/bar/pie + sympy lambdify + base64 output).",
    ))
