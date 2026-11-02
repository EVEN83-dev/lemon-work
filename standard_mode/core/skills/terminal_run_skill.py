# -*- coding: utf-8 -*-
"""
terminal_run skill — Agent 可通过 ShellBridge 执行终端命令
========================================================
注册到 SkillsRegistry 后，大模型可通过 function calling
直接在终端中执行命令，获取输出结果。

用法：
  from standard_mode.core.skills.terminal_run_skill import register_terminal_run_skill
  register_terminal_run_skill(registry, shell_bridge)
"""
import os
import time
from typing import Dict, Optional

try:
    from standard_mode.core.skills_registry import SkillDef, SkillResult
except ImportError:
    from core.skills_registry import SkillDef, SkillResult


_active_bridge = None


def _run_command(command: str, cwd: str = "", timeout: int = 30) -> SkillResult:
    bridge = _active_bridge
    if bridge is None:
        return SkillResult(success=False, error="终端未启动，请先打开终端面板")

    if cwd and os.path.isdir(cwd):
        bridge.send(f"cd '{cwd}'\r\n")
        time.sleep(0.3)

    output_parts = []
    collected = [False]

    def on_output(data: str):
        output_parts.append(data)

    old_cb = getattr(bridge, "on_raw", None)
    bridge.on_raw = on_output

    bridge.send_line(command)
    time.sleep(0.1)

    elapsed = 0.0
    interval = 0.2
    while elapsed < timeout:
        time.sleep(interval)
        elapsed += interval
        if output_parts and not collected[0]:
            last_len = sum(len(p) for p in output_parts)
            time.sleep(0.5)
            new_len = sum(len(p) for p in output_parts)
            if new_len == last_len:
                collected[0] = True
                break

    bridge.on_raw = old_cb

    raw = "".join(output_parts)
    import re
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw)
    clean = re.sub(r'\r\n', '\n', clean).strip()

    if len(clean) > 8000:
        clean = clean[:8000] + f"\n... (截断，共{len(clean)}字符)"

    return SkillResult(success=True, output=clean)


def register_terminal_run_skill(registry, shell_bridge=None):
    global _active_bridge
    if shell_bridge is not None:
        _active_bridge = shell_bridge

    skill = SkillDef(
        name="terminal_run",
        description="在终端中执行命令并获取输出结果。支持 shell 命令、脚本、管道等。",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的命令",
                },
                "cwd": {
                    "type": "string",
                    "description": "工作目录（可选）",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数（默认30）",
                },
            },
            "required": ["command"],
        },
        handler=_run_command,
        category="terminal",
        requires_confirm=False,
        timeout=60,
    )
    registry.register(skill)
    return skill


def set_active_bridge(shell_bridge):
    global _active_bridge
    _active_bridge = shell_bridge
