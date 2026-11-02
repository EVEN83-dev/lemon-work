"""
H-A2: Git Version Control Skill - status/diff/log/add/commit/checkout.
Commit/push/checkout require user confirmation via PermissionGuard.
Diff output is structured; binary and sensitive files (.env) are pruned.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from bridge.skills.models import SkillDef, SkillResult, SkillCategory, SkillRiskLevel

logger = logging.getLogger(__name__)

_SENSITIVE_PATTERNS = {".env", ".env.local", ".env.production", ".env.staging",
                      ".secret", ".credentials", "id_rsa", "id_ed25519",
                      ".pem", ".key", ".p12", ".pfx"}
_BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
                      ".zip", ".tar", ".gz", ".7z", ".rar", ".whl",
                      ".pyc", ".pyd", ".so", ".dll", ".exe", ".o", ".obj",
                      ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                      ".mp3", ".mp4", ".wav", ".avi", ".mov", ".woff", ".woff2",
                      ".ttf", ".eot", ".db", ".sqlite"}


def git_status(**kwargs) -> SkillResult:
    return _git_cmd(["status", "--porcelain=v1"], "status")


def git_diff(**kwargs) -> SkillResult:
    start = time.time()
    target = kwargs.get("target", "")
    staged = kwargs.get("staged", False)
    cmd = ["diff"]
    if staged:
        cmd.append("--staged")
    if target:
        cmd.append("--")
        cmd.append(target)

    result = _git_cmd(cmd, "diff")
    if not result.success:
        return result

    output = result.output
    pruned = _prune_diff(output)
    stats = _diff_stats(output)

    result.data = {
        "needs_llm": False,
        "files_changed": stats["files_changed"],
        "insertions": stats["insertions"],
        "deletions": stats["deletions"],
        "pruned_files": stats["pruned"],
    }
    result.output = pruned
    return result


def git_log(**kwargs) -> SkillResult:
    count = int(kwargs.get("count", 10))
    oneline = kwargs.get("oneline", True)
    cmd = ["log", f"-{count}"]
    if oneline:
        cmd.extend(["--oneline", "--decorate"])
    else:
        cmd.extend(["--format=%H|%an|%ae|%ai|%s"])
    return _git_cmd(cmd, "log")


def git_add(**kwargs) -> SkillResult:
    paths = kwargs.get("paths", [])
    if isinstance(paths, str):
        paths = [p.strip() for p in paths.split(",") if p.strip()]
    if not paths:
        return SkillResult.fail("No paths specified for git add")
    cmd = ["add"] + paths
    return _git_cmd(cmd, "add")


def git_commit(**kwargs) -> SkillResult:
    message = kwargs.get("message", "")
    if not message:
        return SkillResult.fail("Commit message is required")
    cmd = ["commit", "-m", message]
    return _git_cmd(cmd, "commit")


def git_checkout(**kwargs) -> SkillResult:
    target = kwargs.get("target", "")
    create_branch = kwargs.get("create_branch", False)
    if not target:
        return SkillResult.fail("Target (branch/commit/file) is required")
    cmd = ["checkout"]
    if create_branch:
        cmd.append("-b")
    cmd.append(target)
    return _git_cmd(cmd, "checkout")


def git_push(**kwargs) -> SkillResult:
    remote = kwargs.get("remote", "origin")
    branch = kwargs.get("branch", "")
    cmd = ["push", remote]
    if branch:
        cmd.append(branch)
    return _git_cmd(cmd, "push")


def git_branch(**kwargs) -> SkillResult:
    cmd = ["branch", "-a"]
    return _git_cmd(cmd, "branch")


def git_stash(**kwargs) -> SkillResult:
    action = kwargs.get("action", "push")
    if action == "pop":
        cmd = ["stash", "pop"]
    elif action == "list":
        cmd = ["stash", "list"]
    else:
        cmd = ["stash", "push", "-m", kwargs.get("message", "auto-stash")]
    return _git_cmd(cmd, "stash")


def _git_cmd(args: List[str], subcommand: str) -> SkillResult:
    start = time.time()
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace",
        )
        duration_ms = (time.time() - start) * 1000
        if result.returncode == 0:
            output = result.stdout.strip()
            if not output and subcommand in ("add", "commit", "checkout", "push", "stash"):
                output = f"git {subcommand} completed successfully"
            return SkillResult.ok(output=output, duration_ms=duration_ms)
        else:
            stderr = result.stderr.strip()
            return SkillResult.fail(
                error=stderr or f"git {subcommand} failed with code {result.returncode}",
                output=result.stdout.strip(),
            )
    except FileNotFoundError:
        return SkillResult.fail("git is not installed or not in PATH")
    except subprocess.TimeoutExpired:
        return SkillResult.fail(f"git {subcommand} timed out")
    except Exception as e:
        return SkillResult.fail(f"git {subcommand} error: {e}")


def _prune_diff(diff_output: str) -> str:
    if not diff_output:
        return diff_output
    blocks = diff_output.split("diff --git ")
    kept: List[str] = []
    pruned: List[str] = []
    for block in blocks:
        if not block.strip():
            continue
        first_line = block.split("\n")[0]
        if " b/" in first_line:
            file_path = first_line.split(" b/", 1)[1].strip()
        elif " a/" in first_line:
            file_path = first_line.split(" a/", 1)[1].split()[0].strip()
        else:
            file_path = ""

        basename = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[1].lower()

        if basename in _SENSITIVE_PATTERNS:
            pruned.append(file_path)
            continue
        if ext in _BINARY_EXTENSIONS:
            pruned.append(file_path)
            continue

        kept.append("diff --git " + block)

    result = "\n".join(kept)
    if pruned:
        result += f"\n\n[Pruned {len(pruned)} sensitive/binary files: {', '.join(pruned[:5])}]"
    if len(result) > 50000:
        result = result[:50000] + "\n...[diff truncated]"
    return result


def _diff_stats(diff_output: str) -> Dict[str, Any]:
    files_changed = diff_output.count("diff --git ")
    insertions = diff_output.count("\n+") - diff_output.count("\n+++")
    deletions = diff_output.count("\n-") - diff_output.count("\n---")
    pruned = 0
    for basename in _SENSITIVE_PATTERNS:
        pruned += diff_output.count(basename)
    return {
        "files_changed": files_changed,
        "insertions": max(0, insertions),
        "deletions": max(0, deletions),
        "pruned": pruned,
    }


_HIGH_RISK_SUBCOMMANDS = {"commit", "push", "checkout"}


def git_execute(**kwargs) -> SkillResult:
    subcommand = kwargs.get("subcommand", "status")
    handlers = {
        "status": git_status,
        "diff": git_diff,
        "log": git_log,
        "add": git_add,
        "commit": git_commit,
        "checkout": git_checkout,
        "push": git_push,
        "branch": git_branch,
        "stash": git_stash,
    }
    handler = handlers.get(subcommand)
    if handler is None:
        return SkillResult.fail(f"Unknown git subcommand: {subcommand}. Available: {', '.join(handlers.keys())}")
    result = handler(**kwargs)
    if subcommand in _HIGH_RISK_SUBCOMMANDS and result.success:
        result.data = result.data or {}
        result.data["requires_confirm"] = True
        result.data["confirm_message"] = f"Git {subcommand} executed. This is a high-risk operation."
    return result


def register(registry) -> None:
    registry.register(SkillDef(
        name="git",
        description="Git version control: status, diff, log, add, commit, checkout, push, branch, stash. Commit/push/checkout require user confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "subcommand": {
                    "type": "string",
                    "enum": ["status", "diff", "log", "add", "commit", "checkout", "push", "branch", "stash"],
                    "description": "Git subcommand to execute",
                },
                "target": {"type": "string", "description": "Branch, file, or ref target"},
                "paths": {"type": "string", "description": "Comma-separated file paths (for add)"},
                "message": {"type": "string", "description": "Commit or stash message"},
                "count": {"type": "integer", "description": "Number of log entries (default 10)"},
                "staged": {"type": "boolean", "description": "Show staged diff"},
                "create_branch": {"type": "boolean", "description": "Create new branch on checkout"},
                "remote": {"type": "string", "description": "Remote name for push (default origin)"},
                "branch": {"type": "string", "description": "Branch name for push"},
                "action": {"type": "string", "description": "Stash action: push/pop/list"},
                "oneline": {"type": "boolean", "description": "Log oneline format"},
            },
            "required": ["subcommand"],
        },
        handler=git_execute,
        category=SkillCategory.SYSTEM,
        risk_level=SkillRiskLevel.MEDIUM,
        requires_confirm=True,
        timeout=30,
        version="1.1.0",
        examples=[
            "Check git status",
            "Show recent git log",
            "Stage and commit changes",
        ],
    ))
    registry.register(SkillDef(
        name="git_read",
        description="Read-only git operations: status, diff, log, branch. No confirmation required.",
        parameters={
            "type": "object",
            "properties": {
                "subcommand": {
                    "type": "string",
                    "enum": ["status", "diff", "log", "branch"],
                    "description": "Read-only git subcommand",
                },
                "target": {"type": "string", "description": "File or ref for diff"},
                "count": {"type": "integer", "description": "Number of log entries (default 10)"},
                "staged": {"type": "boolean", "description": "Show staged diff"},
                "oneline": {"type": "boolean", "description": "Log oneline format"},
            },
            "required": ["subcommand"],
        },
        handler=lambda **kw: git_execute(**{**kw, "subcommand": kw.get("subcommand", "status")})
            if kw.get("subcommand") in ("status", "diff", "log", "branch")
            else SkillResult.fail("git_read only supports: status, diff, log, branch"),
        category=SkillCategory.SYSTEM,
        risk_level=SkillRiskLevel.SAFE,
        requires_confirm=False,
        timeout=15,
        version="1.0.0",
        examples=[
            "Check git status",
            "View diff of changes",
            "Show commit history",
        ],
    ))
