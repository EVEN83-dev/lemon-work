# -*- coding: utf-8 -*-
"""
C1 — 第一方工具集
=================
≥6 个 ToolDef 注入 ToolRegistry:
read_file / write_file / edit_file / run_shell / git_status / grep_search
"""

import os
import re
import shutil
import subprocess
import threading
import time
from typing import Dict, List, Optional

from bridge.tools.tool_def import ToolDef, ToolResult, ToolContext
from bridge.sandbox import CommandSandbox, SandboxPolicy


# ==============================================================================
# 工具本地撤销 (C6) — tool_history 快照管理器
# ==============================================================================

_TOOL_HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "tool_history",
)
_TOOL_HISTORY_LOCK = threading.Lock()
_MAX_HISTORY_ENTRIES = 200


def _ensure_history_dir() -> str:
    os.makedirs(_TOOL_HISTORY_DIR, exist_ok=True)
    return _TOOL_HISTORY_DIR


def _snapshot_before_write(path: str) -> Optional[str]:
    """在 write/edit 改动文件前做快照，返回快照相对标识；文件不存在则记 None。"""
    try:
        hist_dir = _ensure_history_dir()
        ts = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
        base = os.path.basename(path) or "unknown"
        snap_name = f"{ts}__{base}"
        snap_path = os.path.join(hist_dir, snap_name)
        existed = os.path.exists(path)
        if existed:
            shutil.copy2(path, snap_path)
        # 记录元数据，便于 undo 时定位还原目标
        meta_path = snap_path + ".meta"
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(path + "\n")
            f.write("EXISTED" if existed else "CREATED\n")
        return snap_name
    except Exception:
        return None


def _list_snapshots() -> List[dict]:
    hist_dir = _ensure_history_dir()
    snaps = []
    for fn in os.listdir(hist_dir):
        if fn.endswith(".meta"):
            try:
                with open(os.path.join(hist_dir, fn), "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
                target = lines[0] if lines else "?"
                state = lines[1] if len(lines) > 1 else "?"
                snaps.append({
                    "snapshot": fn[:-5],  # 去掉 .meta
                    "target": target,
                    "state": state,
                })
            except Exception:
                continue
    snaps.sort(key=lambda x: x["snapshot"], reverse=True)
    return snaps


def undo_last(n: int = 1) -> ToolResult:
    """撤销最近 n 次文件写/改操作。每次还原一个快照并删除该快照。"""
    with _TOOL_HISTORY_LOCK:
        snaps = _list_snapshots()
        if not snaps:
            return ToolResult(success=False, error="No tool history to undo")
        n = max(1, min(n, len(snaps)))
        restored = []
        for snap in snaps[:n]:
            snap_base = snap["snapshot"]
            hist_dir = _TOOL_HISTORY_DIR
            snap_file = os.path.join(hist_dir, snap_base)
            meta_file = snap_file + ".meta"
            target = snap["target"]
            try:
                if snap["state"] == "CREATED":
                    # 原文件是本次操作新建的 → 撤销即删除
                    if os.path.exists(target):
                        os.remove(target)
                    action = f"removed created file {target}"
                else:
                    if os.path.exists(snap_file):
                        shutil.copy2(snap_file, target)
                        action = f"restored {target}"
                    else:
                        action = f"snapshot missing for {target}, skipped"
                # 清理快照
                for p in (snap_file, meta_file):
                    if os.path.exists(p):
                        os.remove(p)
                restored.append(action)
            except Exception as e:
                restored.append(f"FAILED undo {target}: {e}")
        return ToolResult(
            success=True,
            output="\n".join(restored),
            data={"undone": len(restored)},
        )


_SANDBOX: Optional[CommandSandbox] = None


def _get_sandbox() -> CommandSandbox:
    global _SANDBOX
    if _SANDBOX is None:
        policy = SandboxPolicy(
            allowed_commands=["git", "python", "pip", "node", "npm", "ls", "cat",
                              "echo", "dir", "type", "find", "grep", "rg", "wc",
                              "head", "tail", "sort", "uniq", "diff", "mkdir",
                              "cp", "mv"],
            denied_commands=["rm -rf /", "format", "del /s", "rmdir /s"],
            denied_patterns=[r"rm\s+-rf\s+/", r"format\s+[A-Z]:"],
            timeout_seconds=30,
            max_memory_mb=512,
            network_allowed=False,
        )
        _SANDBOX = CommandSandbox(policy)
    return _SANDBOX


# ==============================================================================
# read_file
# ==============================================================================

_READ_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path to read"},
        "start_line": {"type": "integer", "description": "Start line (1-based, optional)", "minimum": 1},
        "end_line": {"type": "integer", "description": "End line (inclusive, optional)", "minimum": 1},
        "encoding": {"type": "string", "description": "File encoding (default utf-8)"},
    },
    "required": ["path"],
}


def _read_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = args.get("path", "")
    if not path:
        return ToolResult(success=False, error="path is required")
    if not os.path.exists(path):
        return ToolResult(success=False, error=f"File not found: {path}")
    if os.path.isdir(path):
        return ToolResult(success=False, error=f"Path is a directory: {path}")
    try:
        enc = args.get("encoding", "utf-8")
        with open(path, "r", encoding=enc, errors="replace") as f:
            lines = f.readlines()
        total = len(lines)
        start = args.get("start_line", 1)
        end = args.get("end_line", total)
        start = max(1, start)
        end = min(total, end)
        selected = lines[start - 1:end]
        numbered = []
        for i, line in enumerate(selected, start=start):
            numbered.append(f"{i:>4} | {line.rstrip()}")
        output = "\n".join(numbered)
        return ToolResult(
            success=True,
            output=output,
            data={"path": path, "total_lines": total, "start": start, "end": end},
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


# ==============================================================================
# write_file
# ==============================================================================

_WRITE_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path to write"},
        "content": {"type": "string", "description": "Content to write"},
        "mode": {"type": "string", "enum": ["overwrite", "append"], "description": "Write mode"},
        "encoding": {"type": "string", "description": "File encoding (default utf-8)"},
    },
    "required": ["path", "content"],
}


def _write_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return ToolResult(success=False, error="path is required")
    try:
        enc = args.get("encoding", "utf-8")
        mode = args.get("mode", "overwrite")
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        open_mode = "a" if mode == "append" else "w"
        if open_mode == "w":
            _snapshot_before_write(path)  # C6: overwrite 前快照
        with open(path, open_mode, encoding=enc) as f:
            f.write(content)
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        return ToolResult(
            success=True,
            output=f"Wrote {len(content)} chars ({line_count} lines) to {path} [{mode}]",
            data={"path": path, "bytes": len(content.encode(enc)), "mode": mode},
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


# ==============================================================================
# edit_file — 字符串 + 行号两套定位
# ==============================================================================

_EDIT_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path to edit"},
        "old_string": {"type": "string", "description": "Exact string to replace (string mode)"},
        "new_string": {"type": "string", "description": "Replacement string (string mode)"},
        "line_start": {"type": "integer", "description": "Start line for line mode (1-based)"},
        "line_end": {"type": "integer", "description": "End line for line mode (inclusive)"},
        "replacement": {"type": "string", "description": "Replacement lines for line mode"},
        "mode": {"type": "string", "enum": ["string", "line"], "description": "Edit mode"},
    },
    "required": ["path", "mode"],
}


def _edit_file(args: dict, ctx: ToolContext) -> ToolResult:
    path = args.get("path", "")
    if not path:
        return ToolResult(success=False, error="path is required")
    if not os.path.exists(path):
        return ToolResult(success=False, error=f"File not found: {path}")
    mode = args.get("mode", "string")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if mode == "string":
            old_s = args.get("old_string", "")
            new_s = args.get("new_string", "")
            if not old_s:
                return ToolResult(success=False, error="old_string is required in string mode")
            count = content.count(old_s)
            if count == 0:
                return ToolResult(success=False, error="old_string not found in file")
            if count > 1:
                lines_with_match = []
                for i, line in enumerate(content.split("\n"), 1):
                    if old_s in line:
                        lines_with_match.append(i)
                return ToolResult(
                    success=False,
                    error=f"old_string found {count} times (lines {lines_with_match[:5]}...). "
                          f"Provide more context to make it unique.",
                )
            new_content = content.replace(old_s, new_s, 1)
        elif mode == "line":
            line_start = args.get("line_start", 0)
            line_end = args.get("line_end", 0)
            replacement = args.get("replacement", "")
            if line_start < 1:
                return ToolResult(success=False, error="line_start must be >= 1")
            if line_end < line_start:
                return ToolResult(success=False, error="line_end must be >= line_start")
            lines = content.split("\n")
            total = len(lines)
            if line_start > total:
                return ToolResult(success=False, error=f"line_start {line_start} > total lines {total}")
            effective_end = min(line_end, total)
            removed = lines[line_start - 1:effective_end]
            repl_lines = replacement.split("\n") if replacement else []
            lines[line_start - 1:effective_end] = repl_lines
            new_content = "\n".join(lines)
        else:
            return ToolResult(success=False, error=f"Unknown mode: {mode}")
        _snapshot_before_write(path)  # C6: edit 前快照
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return ToolResult(
            success=True,
            output=f"Edited {path} (mode={mode})",
            data={"path": path, "mode": mode},
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


# ==============================================================================
# run_shell — 走 CommandSandbox
# ==============================================================================

_RUN_SHELL_PARAMS = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Shell command to run"},
        "args": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Command arguments",
        },
        "stdin_data": {"type": "string", "description": "Stdin input (optional)"},
        "timeout": {"type": "integer", "description": "Timeout seconds (default 30)"},
        "working_dir": {"type": "string", "description": "Working directory (optional)"},
    },
    "required": ["command"],
}


def _run_shell(args: dict, ctx: ToolContext) -> ToolResult:
    command = args.get("command", "")
    if not command:
        return ToolResult(success=False, error="command is required")
    sandbox = _get_sandbox()
    if args.get("working_dir"):
        sandbox._policy.working_directory = args["working_dir"]
    if args.get("timeout"):
        sandbox._policy.timeout_seconds = args["timeout"]
    result = sandbox.execute(
        command=command,
        args=args.get("args"),
        stdin_data=args.get("stdin_data"),
    )
    output_parts = []
    if result.stdout:
        output_parts.append(result.stdout)
    if result.stderr:
        output_parts.append(f"[STDERR] {result.stderr}")
    if result.timed_out:
        output_parts.append("[TIMEOUT] Command timed out")
    if result.blocked:
        output_parts.append(f"[BLOCKED] {result.block_reason}")
    return ToolResult(
        success=result.success,
        output="\n".join(output_parts),
        error=result.stderr if not result.success else "",
        data={
            "exit_code": result.exit_code,
            "duration": result.duration_seconds,
            "audit_id": result.audit_id,
            "timed_out": result.timed_out,
            "blocked": result.blocked,
        },
    )


# ==============================================================================
# git_status
# ==============================================================================

_GIT_STATUS_PARAMS = {
    "type": "object",
    "properties": {
        "repo_path": {"type": "string", "description": "Repository path (default .)"},
        "short": {"type": "boolean", "description": "Short format (--short)"},
    },
    "required": [],
}


def _git_status(args: dict, ctx: ToolContext) -> ToolResult:
    repo_path = args.get("repo_path", ".")
    short = args.get("short", True)
    try:
        cmd = ["git", "-C", repo_path, "status"]
        if short:
            cmd.append("--short")
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return ToolResult(success=False, error=proc.stderr.strip())
        return ToolResult(
            success=True,
            output=proc.stdout.strip(),
            data={"repo_path": repo_path, "returncode": proc.returncode},
        )
    except FileNotFoundError:
        return ToolResult(success=False, error="git not found on PATH")
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, error="git status timed out")
    except Exception as e:
        return ToolResult(success=False, error=str(e))


# ==============================================================================
# grep_search
# ==============================================================================

_GREP_SEARCH_PARAMS = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Regex pattern to search"},
        "path": {"type": "string", "description": "File or directory to search"},
        "file_pattern": {"type": "string", "description": "Glob pattern for file names (e.g. *.py)"},
        "case_insensitive": {"type": "boolean", "description": "Case insensitive search"},
        "max_results": {"type": "integer", "description": "Maximum results (default 50)", "minimum": 1},
        "context_lines": {"type": "integer", "description": "Lines of context (default 2)", "minimum": 0},
    },
    "required": ["pattern", "path"],
}


def _grep_search(args: dict, ctx: ToolContext) -> ToolResult:
    pattern = args.get("pattern", "")
    search_path = args.get("path", ".")
    if not pattern:
        return ToolResult(success=False, error="pattern is required")
    try:
        flags = re.IGNORECASE if args.get("case_insensitive", False) else 0
        regex = re.compile(pattern, flags)
    except re.error as e:
        return ToolResult(success=False, error=f"Invalid regex: {e}")
    file_pattern = args.get("file_pattern", "")
    max_results = args.get("max_results", 50)
    context = args.get("context_lines", 2)
    matches = []
    try:
        if os.path.isfile(search_path):
            targets = [search_path]
        elif os.path.isdir(search_path):
            targets = []
            for root, dirs, files in os.walk(search_path):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "build")]
                for fname in files:
                    if file_pattern:
                        import fnmatch
                        if not fnmatch.fnmatch(fname, file_pattern):
                            continue
                    targets.append(os.path.join(root, fname))
                    if len(targets) > 500:
                        break
        else:
            return ToolResult(success=False, error=f"Path not found: {search_path}")
        for fpath in targets:
            if len(matches) >= max_results:
                break
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                continue
            for i, line in enumerate(lines):
                if len(matches) >= max_results:
                    break
                if regex.search(line):
                    start_ctx = max(0, i - context)
                    end_ctx = min(len(lines), i + context + 1)
                    ctx_lines = []
                    for j in range(start_ctx, end_ctx):
                        marker = ">" if j == i else " "
                        ctx_lines.append(f"  {marker}{j + 1:>4} | {lines[j].rstrip()}")
                    rel_path = os.path.relpath(fpath, search_path) if os.path.isdir(search_path) else fpath
                    matches.append(f"{rel_path}:{i + 1}\n" + "\n".join(ctx_lines))
        output = "\n\n".join(matches) if matches else "No matches found"
        return ToolResult(
            success=True,
            output=output,
            data={"match_count": len(matches), "pattern": pattern, "path": search_path},
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


# ==============================================================================
# undo_tool — 撤销最近的文件写/改 (C6)
# ==============================================================================

_UNDO_PARAMS = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "integer",
            "description": "Number of recent write/edit operations to undo (default 1, max history)",
            "minimum": 1,
        },
    },
    "required": [],
}


def _undo_tool(args: dict, ctx: ToolContext) -> ToolResult:
    steps = args.get("steps", 1)
    return undo_last(n=steps)


# ==============================================================================
# 注册函数
# ==============================================================================

def register_builtin_tools(registry) -> int:
    """将所有第一方工具注册到 ToolRegistry，返回注册数量。"""
    tools = [
        ToolDef(
            id="read_file",
            description="Read file content with optional line range",
            parameters=_READ_FILE_PARAMS,
            category="file",
            execute=_read_file,
            requires_confirm=False,
            timeout=10,
        ),
        ToolDef(
            id="write_file",
            description="Write or append content to a file",
            parameters=_WRITE_FILE_PARAMS,
            category="file",
            execute=_write_file,
            requires_confirm=True,
            timeout=10,
        ),
        ToolDef(
            id="edit_file",
            description="Edit file by string replacement or line range (dual定位模式)",
            parameters=_EDIT_FILE_PARAMS,
            category="file",
            execute=_edit_file,
            requires_confirm=True,
            timeout=10,
        ),
        ToolDef(
            id="run_shell",
            description="Execute shell command via CommandSandbox (policy-enforced)",
            parameters=_RUN_SHELL_PARAMS,
            category="shell",
            execute=_run_shell,
            requires_confirm=True,
            timeout=30,
        ),
        ToolDef(
            id="git_status",
            description="Get git repository status",
            parameters=_GIT_STATUS_PARAMS,
            category="vcs",
            execute=_git_status,
            requires_confirm=False,
            timeout=10,
        ),
        ToolDef(
            id="grep_search",
            description="Search files by regex pattern with context lines",
            parameters=_GREP_SEARCH_PARAMS,
            category="search",
            execute=_grep_search,
            requires_confirm=False,
            timeout=30,
        ),
        ToolDef(
            id="undo_tool",
            description="Undo the last N file write/edit operations (C6 local tool history)",
            parameters=_UNDO_PARAMS,
            category="file",
            execute=_undo_tool,
            requires_confirm=True,
            timeout=10,
        ),
    ]
    count = 0
    for tool in tools:
        if registry.register(tool):
            count += 1
    return count
