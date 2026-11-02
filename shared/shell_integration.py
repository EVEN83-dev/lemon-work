# -*- coding: utf-8 -*-
"""shared/shell_integration.py — OSC 133 命令块分段。

OSC 133 命令边界协议（兼容 FinalTerm / iTerm2 / VSCode）：
    OSC 133 ; A        — 提示符开始 (prompt)
    OSC 133 ; B        — 命令输入开始
    OSC 133 ; D [;exit] — 命令结束（可选退出码）
    OSC 133 ; E [;cmd]  — 命令文本

注入方式：通过 ShellBridge._process.write() 写入 PTY stdin, 子进程看到序列；
用户 $PROFILE 不变, 重启后消失。
"""
from __future__ import annotations

ESC = b"\x1b"
OSC133_HEADER = ESC + b"]133;"
ST = ESC + b"\\"


def seq(marker: str) -> bytes:
    return OSC133_HEADER + marker.encode("utf-8", errors="replace") + ST


def prompt_start_seq() -> bytes: return seq("A")
def prompt_end_seq() -> bytes: return seq("B")
def command_start_seq() -> bytes: return seq("C")
def command_done_seq(exit_code: int | None = None) -> bytes:
    return seq("D") if exit_code is None else seq(f"D;{int(exit_code)}")
def command_text_seq(cmdline: str) -> bytes:
    safe = (cmdline or "").replace("\x1b", "").replace("\r", "").replace("\n", " ")
    return seq(f"E;{safe}")
def parse_done_value(value: str) -> int | None:
    s = (value or "").strip()
    if not s: return None
    try: return int(s)
    except (TypeError, ValueError): return None


# PowerShell ESC 字面 "`e"
_ESC = "`e"
_A = f"{_ESC}]133;A{_ESC}\\"
_B = f"{_ESC}]133;B{_ESC}\\"


def generate_prompt_source(enable: bool) -> str:
    """生成 prompt 重写源码——渲染 PS 提示符前发射 OSC 133 边界。"""
    if not enable:
        return ""
    src = [
        "$GLOBAL:__li_prev = 0",
        "$GLOBAL:__li_inited = $false",
        "function prompt {",
        "  if ($GLOBAL:__li_inited) {",
        f"    Write-Host -NoNewline ('{_ESC}]133;D;' + $GLOBAL:__li_prev + '{_ESC}\\\\')",
        "  }",
        "  $GLOBAL:__li_inited = $true",
        "  $GLOBAL:__li_prev = $LASTEXITCODE",
        f"  Write-Host -NoNewline '{_A}'",
        "  $loc = $executionContext.SessionState.Path.CurrentLocation",
        "  $lvl = $nestedPromptLevel + 1",
        "  Write-Host -NoNewline ('PS ' + $loc + ('>' * $lvl) + ' ')",
        f"  Write-Host -NoNewline '{_B}'",
        '  ""',
        "}",
    ]
    return "\n".join(src) + "\n"


def generate_disable_source() -> str:
    """生成还原默认提示的 source（禁 shell integration 时用）。"""
    return (
        "function prompt {"
        " \"PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) \" "
        "}\n"
    )
