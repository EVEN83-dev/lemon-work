from .models import SkillResult, SkillDef

METADATA = {
    "name": "math_solver",
    "version": "1.0.0",
    "category": "math",
    "description": "Solves math expressions using sympy (simplify, solve, derive, integrate).",
}


def execute(expression: str, operation: str = "simplify", **kwargs) -> SkillResult:
    try:
        import sympy
    except ImportError:
        return SkillResult.fail("sympy is not installed. Install with: pip install sympy")

    valid_ops = ("simplify", "solve", "derive", "integrate")
    if operation not in valid_ops:
        return SkillResult.fail(f"Invalid operation '{operation}'. Must be one of: {valid_ops}")

    try:
        x = sympy.Symbol("x")
        expr = sympy.sympify(expression)

        if operation == "simplify":
            result = sympy.simplify(expr)
        elif operation == "solve":
            result = sympy.solve(expr, x)
        elif operation == "derive":
            result = sympy.diff(expr, x)
        elif operation == "integrate":
            result = sympy.integrate(expr, x)

        return SkillResult.ok(output=str(result))
    except Exception as e:
        return SkillResult.fail(f"Math solver error: {e}")


def register(registry) -> None:
    registry.register(SkillDef(
        name="math_solver",
        description="[DEPRECATED] Use business.math_solver instead. Legacy 4-op solver (simplify/solve/derive/integrate).",
        category="math",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Math expression to evaluate (e.g. 'x**2 + 2*x + 1')",
                },
                "operation": {
                    "type": "string",
                    "enum": ["simplify", "solve", "derive", "integrate"],
                    "description": "Operation to perform on the expression",
                },
            },
            "required": ["expression"],
        },
        handler=execute,
        timeout=30,
        deprecated=True,
        deprecation_message="Superseded by business.math_solver (7 ops: simplify/solve/integrate/diff/limit/matrix/equation + LaTeX output).",
    ))
