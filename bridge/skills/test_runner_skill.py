"""
H-A3: Test Runner Skill - run pytest/unittest, parse results, card display.
Timeout enforcement, result caching, reuses CodeSandbox resource limits.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

from bridge.skills.models import SkillDef, SkillResult, SkillCategory, SkillRiskLevel

logger = logging.getLogger(__name__)

_RESULT_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 300
_MAX_OUTPUT = 100000
_DEFAULT_TIMEOUT = 120


def test_runner(**kwargs) -> SkillResult:
    start = time.time()
    test_path = kwargs.get("test_path", "")
    framework = kwargs.get("framework", "auto")
    extra_args = kwargs.get("extra_args", "")
    working_dir = kwargs.get("working_dir", "")

    if not test_path:
        test_path = "."

    if not working_dir:
        working_dir = os.getcwd()

    cache_key = f"{working_dir}:{test_path}:{framework}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return SkillResult.ok(
            output=cached["output"],
            data=cached["data"],
            duration_ms=0,
        )

    if framework == "auto":
        framework = _detect_framework(test_path, working_dir)

    if framework == "pytest":
        result_data = _run_pytest(test_path, working_dir, extra_args)
    elif framework == "unittest":
        result_data = _run_unittest(test_path, working_dir, extra_args)
    else:
        return SkillResult.fail(f"Unknown test framework: {framework}. Supported: pytest, unittest, auto")

    output = _format_result(result_data)
    duration_ms = (time.time() - start) * 1000

    data = {
        "needs_llm": False,
        "framework": framework,
        "test_path": test_path,
        **result_data,
    }

    _set_cached(cache_key, {"output": output, "data": data})

    return SkillResult.ok(output=output, data=data, duration_ms=duration_ms)


def _detect_framework(test_path: str, working_dir: str) -> str:
    try:
        conftest = os.path.join(working_dir, "conftest.py")
        pytest_ini = os.path.join(working_dir, "pytest.ini")
        pyproject = os.path.join(working_dir, "pyproject.toml")
        setup_cfg = os.path.join(working_dir, "setup.cfg")

        if os.path.isfile(conftest) or os.path.isfile(pytest_ini):
            return "pytest"

        if os.path.isfile(pyproject):
            try:
                with open(pyproject, "r", encoding="utf-8") as f:
                    content = f.read()
                if "pytest" in content:
                    return "pytest"
            except Exception:
                pass

        if os.path.isfile(setup_cfg):
            try:
                with open(setup_cfg, "r", encoding="utf-8") as f:
                    content = f.read()
                if "pytest" in content:
                    return "pytest"
            except Exception:
                pass

        try:
            result = subprocess.run(
                [sys_executable(), "-c", "import pytest"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                return "pytest"
        except Exception:
            pass

    except Exception:
        pass

    return "unittest"


def sys_executable() -> str:
    import sys
    return sys.executable


def _run_pytest(test_path: str, working_dir: str, extra_args: str) -> Dict[str, Any]:
    cmd = [sys_executable(), "-m", "pytest", test_path, "-v", "--tb=short"]
    if extra_args:
        cmd.extend(extra_args.split())

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=_DEFAULT_TIMEOUT, cwd=working_dir,
            encoding="utf-8", errors="replace",
        )
        return _parse_pytest_output(result.stdout, result.stderr, result.returncode)
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "total": 0, "passed": 0, "failed": 0,
            "errors": 0, "skipped": 0,
            "failures": [],
            "raw_output": f"Test execution timed out after {_DEFAULT_TIMEOUT}s",
        }
    except Exception as e:
        return {
            "status": "error",
            "total": 0, "passed": 0, "failed": 0,
            "errors": 0, "skipped": 0,
            "failures": [],
            "raw_output": str(e),
        }


def _run_unittest(test_path: str, working_dir: str, extra_args: str) -> Dict[str, Any]:
    cmd = [sys_executable(), "-m", "unittest", test_path, "-v"]
    if extra_args:
        cmd.extend(extra_args.split())

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=_DEFAULT_TIMEOUT, cwd=working_dir,
            encoding="utf-8", errors="replace",
        )
        return _parse_unittest_output(result.stdout, result.stderr, result.returncode)
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "total": 0, "passed": 0, "failed": 0,
            "errors": 0, "skipped": 0,
            "failures": [],
            "raw_output": f"Test execution timed out after {_DEFAULT_TIMEOUT}s",
        }
    except Exception as e:
        return {
            "status": "error",
            "total": 0, "passed": 0, "failed": 0,
            "errors": 0, "skipped": 0,
            "failures": [],
            "raw_output": str(e),
        }


def _parse_pytest_output(stdout: str, stderr: str, returncode: int) -> Dict[str, Any]:
    total = passed = failed = errors = skipped = 0
    failures: List[Dict[str, str]] = []

    summary_pat = re.compile(r"(\d+) passed")
    fail_pat = re.compile(r"(\d+) failed")
    error_pat = re.compile(r"(\d+) error")
    skip_pat = re.compile(r"(\d+) skipped")

    combined = stdout + stderr

    m = summary_pat.search(combined)
    if m:
        passed = int(m.group(1))
    m = fail_pat.search(combined)
    if m:
        failed = int(m.group(1))
    m = error_pat.search(combined)
    if m:
        errors = int(m.group(1))
    m = skip_pat.search(combined)
    if m:
        skipped = int(m.group(1))

    total = passed + failed + errors + skipped

    fail_block_pat = re.compile(r"FAILED (.*?) - (.*?)(?:\n|$)")
    for m in fail_block_pat.finditer(stdout):
        failures.append({
            "test": m.group(1).strip(),
            "detail": m.group(2).strip()[:200],
        })

    if not failures and failed > 0:
        lines = stdout.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("FAILED"):
                test_name = line.replace("FAILED", "").strip()
                if test_name:
                    failures.append({"test": test_name, "detail": ""})

    status = "passed" if returncode == 0 else ("failed" if failed > 0 else "error")

    raw = (stdout + stderr)[:_MAX_OUTPUT]

    return {
        "status": status,
        "total": total, "passed": passed, "failed": failed,
        "errors": errors, "skipped": skipped,
        "failures": failures[:20],
        "raw_output": raw,
    }


def _parse_unittest_output(stdout: str, stderr: str, returncode: int) -> Dict[str, Any]:
    total = passed = failed = errors = skipped = 0
    failures: List[Dict[str, str]] = []

    test_pat = re.compile(r"^(test_\S+)\s+\((\S+)\)\s*\.\.\.\s+(\w+)", re.MULTILINE)
    for m in test_pat.finditer(stdout):
        total += 1
        outcome = m.group(3).lower()
        if outcome == "ok":
            passed += 1
        elif outcome == "fail":
            failed += 1
            failures.append({"test": f"{m.group(2)}.{m.group(1)}", "detail": ""})
        elif outcome == "error":
            errors += 1
        elif outcome in ("skip", "skipped"):
            skipped += 1

    ran_pat = re.compile(r"Ran (\d+) test")
    m = ran_pat.search(stdout)
    if m and total == 0:
        total = int(m.group(1))

    status = "passed" if returncode == 0 else ("failed" if failed > 0 else "error")

    raw = (stdout + stderr)[:_MAX_OUTPUT]

    return {
        "status": status,
        "total": total, "passed": passed, "failed": failed,
        "errors": errors, "skipped": skipped,
        "failures": failures[:20],
        "raw_output": raw,
    }


def _format_result(data: Dict[str, Any]) -> str:
    status = data.get("status", "unknown")
    total = data.get("total", 0)
    passed = data.get("passed", 0)
    failed = data.get("failed", 0)
    errors = data.get("errors", 0)
    skipped = data.get("skipped", 0)
    failures = data.get("failures", [])

    status_icon = {
        "passed": "PASS",
        "failed": "FAIL",
        "error": "ERROR",
        "timeout": "TIMEOUT",
    }.get(status, status.upper())

    lines: List[str] = [
        f"[{status_icon}] Test Results: {total} total | {passed} passed | {failed} failed | {errors} errors | {skipped} skipped",
    ]

    if failures:
        lines.append(f"\nFailed tests ({len(failures)}):")
        for f in failures:
            test = f.get("test", "?")
            detail = f.get("detail", "")
            if detail:
                lines.append(f"  - {test}: {detail[:150]}")
            else:
                lines.append(f"  - {test}")

    if status == "timeout":
        lines.append(f"\nExecution timed out after {_DEFAULT_TIMEOUT}s")

    return "\n".join(lines)


def _get_cached(key: str) -> Optional[Dict[str, Any]]:
    entry = _RESULT_CACHE.get(key)
    if entry is None:
        return None
    if time.time() - entry.get("_ts", 0) > _CACHE_TTL:
        _RESULT_CACHE.pop(key, None)
        return None
    return entry


def _set_cached(key: str, value: Dict[str, Any]) -> None:
    value["_ts"] = time.time()
    _RESULT_CACHE[key] = value
    if len(_RESULT_CACHE) > 100:
        oldest = min(_RESULT_CACHE.items(), key=lambda x: x[1].get("_ts", 0))
        _RESULT_CACHE.pop(oldest[0], None)


def register(registry) -> None:
    registry.register(SkillDef(
        name="test_runner",
        description="Run tests (pytest/unittest) and return structured results with pass/fail counts and failure details.",
        parameters={
            "type": "object",
            "properties": {
                "test_path": {"type": "string", "description": "Test file or directory path (default: current directory)"},
                "framework": {"type": "string", "enum": ["auto", "pytest", "unittest"], "description": "Test framework (default: auto-detect)"},
                "extra_args": {"type": "string", "description": "Additional arguments to pass to test runner"},
                "working_dir": {"type": "string", "description": "Working directory for test execution"},
            },
            "required": [],
        },
        handler=test_runner,
        category=SkillCategory.CODE,
        risk_level=SkillRiskLevel.LOW,
        requires_confirm=False,
        timeout=_DEFAULT_TIMEOUT,
        version="1.0.0",
        examples=[
            "Run all tests in the current directory",
            "Run pytest on tests/ folder",
            "Run a specific test file",
        ],
    ))
