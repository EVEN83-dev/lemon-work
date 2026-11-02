# -*- coding: utf-8 -*-
"""
终端错误分析器 — 错误关键字 → Agent 分析 → 修复建议卡片
=====================================================
监听终端输出，匹配已知错误模式，生成修复建议卡片
推送到标准模式右侧栏展示。

错误模式：
  - Python: ImportError, ModuleNotFoundError, SyntaxError, etc.
  - Node: ENOENT, EACCES, MODULE_NOT_FOUND
  - Git: not a git repository, merge conflict
  - Docker: permission denied, image not found
  - 通用: command not found, permission denied, No such file
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Callable


@dataclass
class ErrorMatch:
    pattern: str
    category: str
    severity: str  # error, warning, info
    title: str
    fix_hint: str
    fix_command: Optional[str] = None
    doc_url: Optional[str] = None


@dataclass
class ErrorCard:
    title: str
    category: str
    severity: str
    message: str
    fix_hint: str
    fix_command: Optional[str] = None
    doc_url: Optional[str] = None
    raw_line: str = ""


_ERROR_PATTERNS: List[ErrorMatch] = [
    ErrorMatch(
        pattern=r"ModuleNotFoundError:\s+No module named '(\w+)'",
        category="python", severity="error",
        title="Python 模块未安装",
        fix_hint="安装缺失模块",
        fix_command="pip install {0}",
    ),
    ErrorMatch(
        pattern=r"ImportError:\s+(.+)",
        category="python", severity="error",
        title="Python 导入错误",
        fix_hint="检查依赖或重新安装",
    ),
    ErrorMatch(
        pattern=r"SyntaxError:\s+(.+)",
        category="python", severity="error",
        title="Python 语法错误",
        fix_hint="检查代码语法，常见问题：缩进、括号不匹配、缺少冒号",
    ),
    ErrorMatch(
        pattern=r"([\w.]+Error):\s+(.+)",
        category="python", severity="error",
        title="Python 运行时错误",
        fix_hint="检查异常类型和堆栈信息",
    ),
    ErrorMatch(
        pattern=r"ENOENT:\s+no such file or directory.*'(.+)'",
        category="node", severity="error",
        title="Node 文件不存在",
        fix_hint="检查文件路径是否正确",
    ),
    ErrorMatch(
        pattern=r"EACCES:\s+permission denied",
        category="node", severity="error",
        title="Node 权限不足",
        fix_hint="尝试使用管理员权限或修改文件权限",
    ),
    ErrorMatch(
        pattern=r"command not found:\s+(\S+)",
        category="shell", severity="error",
        title="命令未找到",
        fix_hint="检查是否已安装 {0}，或是否在 PATH 中",
        fix_command="where {0}",
    ),
    ErrorMatch(
        pattern=r"'(\S+)' is not recognized as an internal or external command",
        category="shell", severity="error",
        title="命令未找到 (Windows)",
        fix_hint="{0} 未安装或不在 PATH 中",
        fix_command="where {0}",
    ),
    ErrorMatch(
        pattern=r"Permission denied",
        category="shell", severity="error",
        title="权限不足",
        fix_hint="尝试使用管理员权限运行",
    ),
    ErrorMatch(
        pattern=r"No such file or directory",
        category="shell", severity="error",
        title="文件或目录不存在",
        fix_hint="检查路径是否正确",
    ),
    ErrorMatch(
        pattern=r"not a git repository",
        category="git", severity="error",
        title="非 Git 仓库",
        fix_hint="初始化 Git 仓库或进入正确的项目目录",
        fix_command="git init",
    ),
    ErrorMatch(
        pattern=r"CONFLICT.*Merge conflict",
        category="git", severity="warning",
        title="Git 合并冲突",
        fix_hint="手动解决冲突后执行 git add + git commit",
    ),
    ErrorMatch(
        pattern=r"Cannot connect to the Docker daemon",
        category="docker", severity="error",
        title="Docker 未运行",
        fix_hint="启动 Docker Desktop",
    ),
    ErrorMatch(
        pattern=r"No such image:\s+(\S+)",
        category="docker", severity="error",
        title="Docker 镜像不存在",
        fix_hint="先拉取镜像",
        fix_command="docker pull {0}",
    ),
    ErrorMatch(
        pattern=r"error:\s+(\w+):\s+(.+)",
        category="general", severity="error",
        title="命令执行错误",
        fix_hint="查看错误详情，检查命令参数",
    ),
    ErrorMatch(
        pattern=r"WARNING:\s+(.+)",
        category="general", severity="warning",
        title="警告",
        fix_hint="可忽略或根据提示调整",
    ),
]

_COMPILED = [(re.compile(m.pattern, re.IGNORECASE), m) for m in _ERROR_PATTERNS]


class TerminalErrorAnalyzer:
    """终端错误分析器"""

    def __init__(self):
        self._cards: List[ErrorCard] = []
        self._on_card: Optional[Callable[[ErrorCard], None]] = None
        self._last_lines: List[str] = []

    def set_card_callback(self, cb: Callable[[ErrorCard], None]):
        self._on_card = cb

    def analyze_output(self, text: str):
        lines = text.split("\n")
        self._last_lines = lines[-50:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            card = self._match_line(line)
            if card:
                self._cards.append(card)
                if self._on_card:
                    self._on_card(card)

    def _match_line(self, line: str) -> Optional[ErrorCard]:
        for regex, match in _COMPILED:
            m = regex.search(line)
            if m:
                groups = m.groups() or ()
                fix_hint = match.fix_hint
                fix_cmd = match.fix_command
                for i, g in enumerate(groups):
                    if g:
                        fix_hint = fix_hint.replace("{" + str(i) + "}", g)
                        if fix_cmd:
                            fix_cmd = fix_cmd.replace("{" + str(i) + "}", g)
                return ErrorCard(
                    title=match.title,
                    category=match.category,
                    severity=match.severity,
                    message=line[:200],
                    fix_hint=fix_hint,
                    fix_command=fix_cmd,
                    raw_line=line[:500],
                )
        return None

    def get_cards(self, limit: int = 20) -> List[ErrorCard]:
        return self._cards[-limit:]

    def clear_cards(self):
        self._cards.clear()

    def get_recent_errors(self, count: int = 5) -> List[ErrorCard]:
        return [c for c in self._cards if c.severity == "error"][-count:]
