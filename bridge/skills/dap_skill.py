"""
H-A4: DAP Debugger Skill - breakpoints, stepping, variable watch.
Requires user confirmation before starting debug session.
Graceful fallback when no DAP adapter is available.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from bridge.skills.models import SkillDef, SkillResult, SkillCategory, SkillRiskLevel

logger = logging.getLogger(__name__)


def dap_start_debug(**kwargs) -> SkillResult:
    start = time.time()
    program = kwargs.get("program", "")
    args = kwargs.get("args", [])
    cwd = kwargs.get("working_dir", "")

    if not program:
        return SkillResult.fail("program path is required")

    if not os.path.isfile(program):
        return SkillResult.fail(f"Program not found: {program}")

    dap_client = kwargs.get("_dap_client")
    if dap_client is None:
        return SkillResult.ok(
            output=_no_dap_fallback(program),
            data={"needs_llm": False, "source": "fallback"},
            duration_ms=(time.time() - start) * 1000,
        )

    try:
        success = dap_client.start_debug(program, args=args, cwd=cwd)
        if success:
            return SkillResult.ok(
                output=f"Debug session started for {os.path.basename(program)} (stopOnEntry=True)",
                data={
                    "needs_llm": False,
                    "source": "dap",
                    "program": program,
                    "status": "running",
                },
                duration_ms=(time.time() - start) * 1000,
            )
        else:
            return SkillResult.fail("Failed to start debug session. Check debugpy installation.")
    except Exception as e:
        return SkillResult.fail(f"DAP start error: {e}")


def dap_set_breakpoint(**kwargs) -> SkillResult:
    start = time.time()
    file_path = kwargs.get("file_path", "")
    lines = kwargs.get("lines", [])

    if not file_path:
        return SkillResult.fail("file_path is required")

    if isinstance(lines, str):
        try:
            lines = [int(x.strip()) for x in lines.split(",") if x.strip()]
        except ValueError:
            return SkillResult.fail("lines must be comma-separated integers")

    if not lines:
        line = int(kwargs.get("line", 0))
        if line > 0:
            lines = [line]
        else:
            return SkillResult.fail("At least one line number is required")

    dap_client = kwargs.get("_dap_client")
    if dap_client is None:
        return SkillResult.ok(
            output=f"Breakpoint request noted for {os.path.basename(file_path)} at lines {lines} (DAP not available)",
            data={"needs_llm": False, "source": "fallback"},
            duration_ms=(time.time() - start) * 1000,
        )

    try:
        result = dap_client.set_breakpoints_simple(file_path, lines)
        verified = [bp for bp in result if bp.verified] if result else []
        output = f"Set {len(verified)}/{len(lines)} breakpoints in {os.path.basename(file_path)}"
        if verified:
            locs = ", ".join(f"L{bp.line}" for bp in verified)
            output += f" at {locs}"
        return SkillResult.ok(
            output=output,
            data={
                "needs_llm": False,
                "source": "dap",
                "file_path": file_path,
                "breakpoints_set": len(verified),
                "breakpoints_requested": len(lines),
            },
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return SkillResult.fail(f"DAP breakpoint error: {e}")


def dap_step(**kwargs) -> SkillResult:
    start = time.time()
    action = kwargs.get("action", "over")
    dap_client = kwargs.get("_dap_client")

    if dap_client is None:
        return SkillResult.ok(
            output=f"Step {action} not available (DAP not connected)",
            data={"needs_llm": False, "source": "fallback"},
            duration_ms=(time.time() - start) * 1000,
        )

    try:
        if action == "over":
            success = dap_client.step_over()
        elif action == "into":
            success = dap_client.step_into()
        elif action == "out":
            success = dap_client.step_out()
        elif action == "continue":
            success = dap_client.continue_execution()
        else:
            return SkillResult.fail(f"Unknown step action: {action}. Use: over, into, out, continue")

        if success:
            stack = dap_client.get_stack_trace()
            frame_info = ""
            if stack:
                top = stack[0]
                fname = os.path.basename(top.get("file", "?"))
                frame_info = f" at {fname}:{top.get('line', '?')}"
            return SkillResult.ok(
                output=f"Step {action} executed{frame_info}",
                data={
                    "needs_llm": False,
                    "source": "dap",
                    "action": action,
                    "stack": stack[:5],
                },
                duration_ms=(time.time() - start) * 1000,
            )
        else:
            return SkillResult.fail(f"Step {action} failed. Debugger may not be paused.")
    except Exception as e:
        return SkillResult.fail(f"DAP step error: {e}")


def dap_get_variables(**kwargs) -> SkillResult:
    start = time.time()
    scope = kwargs.get("scope", "local")
    dap_client = kwargs.get("_dap_client")

    if dap_client is None:
        return SkillResult.ok(
            output="Variables not available (DAP not connected)",
            data={"needs_llm": False, "source": "fallback"},
            duration_ms=(time.time() - start) * 1000,
        )

    try:
        variables = dap_client.get_variables(scope=scope)
        if not variables:
            return SkillResult.ok(
                output=f"No {scope} variables available at current frame",
                data={"needs_llm": False, "source": "dap", "variables": []},
                duration_ms=(time.time() - start) * 1000,
            )

        lines = [f"{scope.capitalize()} variables ({len(variables)}):"]
        for v in variables[:30]:
            name = v.get("name", "?")
            value = v.get("value", "?")
            vtype = v.get("type", "")
            type_str = f" [{vtype}]" if vtype else ""
            val_display = value[:80] if len(value) > 80 else value
            lines.append(f"  {name}{type_str} = {val_display}")

        return SkillResult.ok(
            output="\n".join(lines),
            data={
                "needs_llm": False,
                "source": "dap",
                "scope": scope,
                "variable_count": len(variables),
                "variables": variables[:50],
            },
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return SkillResult.fail(f"DAP variables error: {e}")


def dap_evaluate(**kwargs) -> SkillResult:
    start = time.time()
    expression = kwargs.get("expression", "")
    dap_client = kwargs.get("_dap_client")

    if not expression:
        return SkillResult.fail("expression is required")

    if dap_client is None:
        return SkillResult.ok(
            output=f"Evaluation of '{expression}' not available (DAP not connected)",
            data={"needs_llm": False, "source": "fallback"},
            duration_ms=(time.time() - start) * 1000,
        )

    try:
        result = dap_client.evaluate_expression(expression)
        if result is not None:
            return SkillResult.ok(
                output=f"{expression} = {result}",
                data={"needs_llm": False, "source": "dap", "expression": expression, "result": result},
                duration_ms=(time.time() - start) * 1000,
            )
        else:
            return SkillResult.fail(f"Could not evaluate: {expression}")
    except Exception as e:
        return SkillResult.fail(f"DAP evaluate error: {e}")


def dap_get_stack(**kwargs) -> SkillResult:
    start = time.time()
    dap_client = kwargs.get("_dap_client")

    if dap_client is None:
        return SkillResult.ok(
            output="Stack trace not available (DAP not connected)",
            data={"needs_llm": False, "source": "fallback"},
            duration_ms=(time.time() - start) * 1000,
        )

    try:
        stack = dap_client.get_stack_trace()
        if not stack:
            return SkillResult.ok(
                output="No stack trace available (debugger may not be paused)",
                data={"needs_llm": False, "source": "dap", "stack": []},
                duration_ms=(time.time() - start) * 1000,
            )

        lines = [f"Call stack ({len(stack)} frames):"]
        for i, frame in enumerate(stack[:15]):
            name = frame.get("name", "?")
            fname = os.path.basename(frame.get("file", "?"))
            line = frame.get("line", "?")
            lines.append(f"  {i}. {name} at {fname}:{line}")

        return SkillResult.ok(
            output="\n".join(lines),
            data={"needs_llm": False, "source": "dap", "stack": stack},
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return SkillResult.fail(f"DAP stack error: {e}")


def dap_stop_debug(**kwargs) -> SkillResult:
    start = time.time()
    dap_client = kwargs.get("_dap_client")

    if dap_client is None:
        return SkillResult.ok(
            output="Debug session not running (DAP not connected)",
            data={"needs_llm": False, "source": "fallback"},
            duration_ms=(time.time() - start) * 1000,
        )

    try:
        success = dap_client.stop_debug()
        return SkillResult.ok(
            output="Debug session stopped",
            data={"needs_llm": False, "source": "dap", "status": "stopped"},
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return SkillResult.fail(f"DAP stop error: {e}")


def dap_execute(**kwargs) -> SkillResult:
    subcommand = kwargs.get("subcommand", "start")
    handlers = {
        "start": dap_start_debug,
        "breakpoint": dap_set_breakpoint,
        "step": dap_step,
        "variables": dap_get_variables,
        "evaluate": dap_evaluate,
        "stack": dap_get_stack,
        "stop": dap_stop_debug,
    }
    handler = handlers.get(subcommand)
    if handler is None:
        return SkillResult.fail(f"Unknown DAP subcommand: {subcommand}. Available: {', '.join(handlers.keys())}")
    return handler(**kwargs)


def _no_dap_fallback(program: str) -> str:
    return (
        f"DAP debugger not available for {os.path.basename(program)}. "
        f"Debugging requires debugpy (Python) or node --inspect (JS). "
        f"Install with: pip install debugpy"
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="dap_debug",
        description="DAP debugger: start/stop debug sessions, set breakpoints, step through code, inspect variables. Starting debug requires user confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "subcommand": {
                    "type": "string",
                    "enum": ["start", "breakpoint", "step", "variables", "evaluate", "stack", "stop"],
                    "description": "DAP operation to perform",
                },
                "program": {"type": "string", "description": "Program path to debug (for start)"},
                "file_path": {"type": "string", "description": "File path for breakpoints"},
                "lines": {"type": "string", "description": "Comma-separated breakpoint line numbers"},
                "line": {"type": "integer", "description": "Single breakpoint line"},
                "action": {"type": "string", "enum": ["over", "into", "out", "continue"], "description": "Step action (default: over)"},
                "scope": {"type": "string", "enum": ["local", "global"], "description": "Variable scope (default: local)"},
                "expression": {"type": "string", "description": "Expression to evaluate"},
                "args": {"type": "array", "description": "Program arguments"},
                "working_dir": {"type": "string", "description": "Working directory for debug session"},
            },
            "required": ["subcommand"],
        },
        handler=dap_execute,
        category=SkillCategory.CODE,
        risk_level=SkillRiskLevel.MEDIUM,
        requires_confirm=True,
        timeout=60,
        version="1.0.0",
        examples=[
            "Start debugging a Python file",
            "Set breakpoint at line 25",
            "Step over and inspect variables",
        ],
    ))
