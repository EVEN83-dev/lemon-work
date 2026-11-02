# -*- coding: utf-8 -*-
"""
内置 Skill 实现 — 代码格式化 + 代码审查
========================================
CodeFormatterSkill:
  - Python (autopep8)
  - JavaScript (内置缩进规则)
  - HTML/CSS (内置缩进规则)
  - 格式化前后 diff 对比

CodeReviewSkill:
  - 未使用的变量和导入
  - 潜在的空指针/None 异常
  - SQL 注入风险
  - 硬编码密码/密钥
  - 函数复杂度过高（圈复杂度 > 15）
  - 文件过长（> 500 行）
"""

import os
import re
import ast
import difflib
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

# 导入插件系统基类
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plugin_system import Skill, ToolDefinition, HookPoint


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Issue:
    """代码审查问题"""
    line: int              # 行号（1-based）
    col: int = 0           # 列号（0-based）
    severity: str = "info"  # info / warning / error
    category: str = ""     # 分类
    description: str = ""   # 问题描述
    suggestion: str = ""    # 修复建议
    code_snippet: str = ""  # 相关代码片段

    def to_dict(self) -> dict:
        return {
            "line": self.line,
            "col": self.col,
            "severity": self.severity,
            "category": self.category,
            "description": self.description,
            "suggestion": self.suggestion,
            "code_snippet": self.code_snippet,
        }


@dataclass
class FormatResult:
    """格式化结果"""
    original: str
    formatted: str
    changed: bool
    diff: str
    language: str

    def to_dict(self) -> dict:
        return {
            "original": self.original[:500],
            "formatted": self.formatted[:500],
            "changed": self.changed,
            "diff": self.diff,
            "language": self.language,
        }


# ============================================================
# CodeFormatterSkill — 代码格式化
# ============================================================

class CodeFormatterSkill(Skill):
    """代码格式化 Skill — 支持 Python / JS / HTML / CSS"""

    def __init__(self):
        super().__init__(
            "code_formatter",
            "自动代码格式化（Python/JS/HTML/CSS）",
            "1.0.0",
            icon="skill_formatter",
        )
        # 注册工具
        self.register_tool(ToolDefinition(
            name="format_code",
            description="格式化代码字符串",
            parameters=[
                {"name": "code", "type": "string", "description": "要格式化的代码"},
                {"name": "language", "type": "string", "description": "编程语言"},
            ],
            category="code",
            handler=self._tool_format_code,
        ))
        self.register_tool(ToolDefinition(
            name="format_file",
            description="格式化指定文件",
            parameters=[
                {"name": "file_path", "type": "string", "description": "文件路径"},
            ],
            category="code",
            handler=self._tool_format_file,
        ))
        # 注册 Hook: 任务完成后自动格式化
        self.register_hook(HookPoint.AFTER_TASK, self._hook_after_task)

    # ---- 核心格式化方法 ----

    def format_code(self, code: str, language: str = "python") -> FormatResult:
        """格式化代码

        Args:
            code: 源代码
            language: python / javascript / html / css

        Returns:
            FormatResult
        """
        language = language.lower().strip()
        if language in ("py", "python"):
            formatted = self._format_python(code)
        elif language in ("js", "javascript", "ts", "typescript"):
            formatted = self._format_js(code)
        elif language in ("html", "htm", "xml"):
            formatted = self._format_html(code)
        elif language in ("css", "scss", "less"):
            formatted = self._format_css(code)
        else:
            # 默认通用缩进整理
            formatted = self._format_generic(code)

        changed = formatted != code
        diff = ""
        if changed:
            diff = "\n".join(difflib.unified_diff(
                code.splitlines(keepends=True),
                formatted.splitlines(keepends=True),
                fromfile="original",
                tofile="formatted",
                n=2,
            ))

        return FormatResult(
            original=code,
            formatted=formatted,
            changed=changed,
            diff=diff,
            language=language,
        )

    # ---- Python 格式化 ----

    def _format_python(self, code: str) -> str:
        """使用 autopep8 格式化 Python"""
        try:
            import autopep8
            return autopep8.fix_code(code, options={"aggressive": 1})
        except ImportError:
            # autopep8 不可用时用基础缩进整理
            return self._format_generic(code)
        except Exception:
            return code

    # ---- JavaScript 格式化 ----

    def _format_js(self, code: str) -> str:
        """JavaScript 格式化（纯 Python 实现）"""
        result = []
        indent = 0
        in_string = False
        string_char = ""
        in_comment = False
        in_line_comment = False
        i = 0

        while i < len(code):
            ch = code[i]
            next_ch = code[i + 1] if i + 1 < len(code) else ""

            # 处理注释
            if not in_string and not in_comment and not in_line_comment:
                if ch == '/' and next_ch == '*':
                    in_comment = True
                elif ch == '/' and next_ch == '/':
                    in_line_comment = True

            if in_comment:
                result.append(ch)
                if ch == '*' and next_ch == '/':
                    result.append(next_ch)
                    in_comment = False
                    i += 2
                    continue
                if ch == '\n':
                    in_comment = False
                i += 1
                continue

            if in_line_comment:
                result.append(ch)
                if ch == '\n':
                    in_line_comment = False
                i += 1
                continue

            # 处理字符串
            if not in_string and ch in ('"', "'", '`'):
                in_string = True
                string_char = ch
                result.append(ch)
                i += 1
                continue
            if in_string:
                result.append(ch)
                if ch == '\\' and next_ch:
                    result.append(next_ch)
                    i += 2
                    continue
                if ch == string_char:
                    in_string = False
                i += 1
                continue

            # 处理缩进
            if ch == '{' or ch == '[' or ch == '(':
                result.append(ch)
                indent += 1
                # 如果下一个不是换行，添加换行
                if next_ch and next_ch not in ('\n', '\r', ' ', '\t'):
                    result.append('\n' + '  ' * indent)
                i += 1
                continue
            elif ch == '}' or ch == ']' or ch == ')':
                indent = max(0, indent - 1)
                # 去掉末尾空格
                while result and result[-1] in (' ', '\t'):
                    result.pop()
                if result and result[-1] != '\n':
                    result.append('\n')
                result.append('  ' * indent + ch)
                i += 1
                continue
            elif ch == ';':
                result.append(ch)
                # 分号后换行
                if next_ch and next_ch not in ('\n', '\r', ' ', '\t'):
                    result.append('\n' + '  ' * indent)
                i += 1
                continue
            elif ch == '\n':
                # 去掉行尾空格
                while result and result[-1] in (' ', '\t'):
                    result.pop()
                result.append(ch)
                # 下一行缩进
                if next_ch and next_ch not in ('}', ']', ')', '\n', '\r'):
                    result.append('  ' * indent)
                else:
                    result.append('  ' * max(0, indent - 1 if next_ch in ('}', ']', ')') else indent))
                i += 1
                continue
            else:
                result.append(ch)
                i += 1

        formatted = ''.join(result)
        # 清理多余空行
        formatted = re.sub(r'\n{3,}', '\n\n', formatted)
        return formatted.strip() + '\n'

    # ---- HTML 格式化 ----

    def _format_html(self, code: str) -> str:
        """HTML 格式化"""
        result = []
        indent = 0
        # 简单的 HTML 标签匹配
        tokens = re.split(r'(<[^>]+>)', code)
        void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                     'link', 'meta', 'param', 'source', 'track', 'wbr'}

        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if token.startswith('</'):
                indent = max(0, indent - 1)
                result.append('  ' * indent + token)
            elif token.startswith('<') and not token.startswith('<!'):
                tag_name = re.match(r'<(\w+)', token)
                if tag_name:
                    tname = tag_name.group(1).lower()
                    result.append('  ' * indent + token)
                    if tname not in void_tags and not token.endswith('/>'):
                        indent += 1
                else:
                    result.append('  ' * indent + token)
            else:
                result.append('  ' * indent + token)

        return '\n'.join(result) + '\n'

    # ---- CSS 格式化 ----

    def _format_css(self, code: str) -> str:
        """CSS 格式化"""
        # 在 { } ; 后添加换行和缩进
        formatted = code
        formatted = re.sub(r'\s*\{\s*', ' {\n  ', formatted)
        formatted = re.sub(r'\s*;\s*', ';\n  ', formatted)
        formatted = re.sub(r'\s*\}\s*', '\n}\n', formatted)
        # 清理多余空行
        formatted = re.sub(r'\n{3,}', '\n\n', formatted)
        formatted = re.sub(r'  \n', '\n', formatted)
        return formatted.strip() + '\n'

    # ---- 通用格式化 ----

    def _format_generic(self, code: str) -> str:
        """通用代码整理（去除行尾空格、统一换行）"""
        lines = code.splitlines()
        result = [line.rstrip() for line in lines]
        # 去除多余空行
        cleaned = []
        prev_blank = False
        for line in result:
            if not line.strip():
                if not prev_blank:
                    cleaned.append('')
                prev_blank = True
            else:
                cleaned.append(line)
                prev_blank = False
        return '\n'.join(cleaned) + '\n'

    # ---- Tool Handler ----

    def _tool_format_code(self, **kwargs) -> str:
        code = kwargs.get("code", "")
        language = kwargs.get("language", "python")
        result = self.format_code(code, language)
        if result.changed:
            return f"代码已格式化（{language}），变更如下：\n{result.diff}"
        return f"代码已经是规范格式，无需修改。"

    def _tool_format_file(self, **kwargs) -> str:
        file_path = kwargs.get("file_path", "")
        if not os.path.exists(file_path):
            return f"文件不存在: {file_path}"
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            code = f.read()
        ext = os.path.splitext(file_path)[1].lower()
        lang_map = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript',
                    '.html': 'html', '.css': 'css', '.json': 'json'}
        language = lang_map.get(ext, 'generic')
        result = self.format_code(code, language)
        if result.changed:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(result.formatted)
            return f"文件已格式化并保存: {file_path}"
        return f"文件格式已规范: {file_path}"

    # ---- Hook: 任务完成后自动格式化 ----

    def _hook_after_task(self, **kwargs) -> dict:
        """AFTER_TASK Hook — 检测刚写入的文件并格式化"""
        file_path = kwargs.get("file_path", "")
        if not file_path or not os.path.exists(file_path):
            return {}

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ('.py', '.js', '.ts', '.html', '.css'):
            return {}

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                code = f.read()
            lang_map = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript',
                        '.html': 'html', '.css': 'css'}
            result = self.format_code(code, lang_map.get(ext, 'generic'))
            if result.changed:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(result.formatted)
                return {
                    "formatted": True,
                    "file": file_path,
                    "diff": result.diff[:500],
                }
        except Exception:
            pass
        return {}


# ============================================================
# CodeReviewSkill — 代码审查
# ============================================================

class CodeReviewSkill(Skill):
    """代码审查 Skill — 静态分析 + 安全检查"""

    # 硬编码密码/密钥模式
    SECRET_PATTERNS = [
        (r'password\s*=\s*["\'][^"\']+["\']', "硬编码密码", "error"),
        (r'passwd\s*=\s*["\'][^"\']+["\']', "硬编码密码", "error"),
        (r'secret\s*=\s*["\'][^"\']+["\']', "硬编码密钥", "error"),
        (r'api_key\s*=\s*["\'][^"\']+["\']', "硬编码 API Key", "error"),
        (r'apikey\s*=\s*["\'][^"\']+["\']', "硬编码 API Key", "error"),
        (r'token\s*=\s*["\'][^"\']+["\']', "硬编码 Token", "error"),
        (r'private_key\s*=\s*["\'][^"\']+["\']', "硬编码私钥", "error"),
        (r'AWS_SECRET_ACCESS_KEY\s*=\s*["\'][^"\']+["\']', "硬编码 AWS 密钥", "error"),
    ]

    # SQL 注入风险模式
    SQL_INJECTION_PATTERNS = [
        (r'execute\s*\(\s*["\'].*%s.*["\']\s*%', "SQL 字符串拼接（可能注入）", "error"),
        (r'execute\s*\(\s*f["\']', "SQL f-string（可能注入）", "error"),
        (r'execute\s*\(\s*["\'].*\+.*["\']', "SQL 字符串拼接（可能注入）", "error"),
        (r'cursor\.execute\s*\(\s*["\'].*\{.*\}.*["\'].*\.format', "SQL format（可能注入）", "error"),
    ]

    def __init__(self):
        super().__init__(
            "code_review",
            "代码审查（安全 + 质量 + 规范）",
            "1.0.0",
            icon="skill_review",
        )
        self.register_tool(ToolDefinition(
            name="review_code",
            description="审查代码质量",
            parameters=[
                {"name": "code", "type": "string", "description": "要审查的代码"},
                {"name": "language", "type": "string", "description": "编程语言"},
            ],
            category="code",
            handler=self._tool_review_code,
        ))
        self.register_tool(ToolDefinition(
            name="review_file",
            description="审查指定文件",
            parameters=[
                {"name": "file_path", "type": "string", "description": "文件路径"},
            ],
            category="code",
            handler=self._tool_review_file,
        ))
        self.register_hook(HookPoint.AFTER_TASK, self._hook_after_task)

    # ---- 核心审查方法 ----

    def review_code(self, code: str, language: str = "python") -> List[Issue]:
        """审查代码

        Args:
            code: 源代码
            language: 编程语言

        Returns:
            问题列表
        """
        issues: List[Issue] = []
        language = language.lower().strip()

        # 通用检查（所有语言）
        issues.extend(self._check_secrets(code))
        issues.extend(self._check_sql_injection(code))
        issues.extend(self._check_long_file(code))

        # Python 专用检查
        if language in ("py", "python"):
            issues.extend(self._check_python_unused(code))
            issues.extend(self._check_python_none_safety(code))
            issues.extend(self._check_python_complexity(code))

        # 按行号排序
        issues.sort(key=lambda x: (x.line, x.col))
        return issues

    # ---- 硬编码密码/密钥检查 ----

    def _check_secrets(self, code: str) -> List[Issue]:
        """检查硬编码的密码和密钥"""
        issues = []
        lines = code.splitlines()
        for i, line in enumerate(lines, 1):
            for pattern, desc, severity in self.SECRET_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append(Issue(
                        line=i,
                        col=0,
                        severity=severity,
                        category="security",
                        description=desc,
                        suggestion="使用环境变量或配置文件管理敏感信息，如 os.environ.get('PASSWORD')",
                        code_snippet=line.strip()[:80],
                    ))
        return issues

    # ---- SQL 注入检查 ----

    def _check_sql_injection(self, code: str) -> List[Issue]:
        """检查 SQL 注入风险"""
        issues = []
        lines = code.splitlines()
        for i, line in enumerate(lines, 1):
            for pattern, desc, severity in self.SQL_INJECTION_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append(Issue(
                        line=i,
                        col=0,
                        severity=severity,
                        category="security",
                        description=desc,
                        suggestion="使用参数化查询：cursor.execute('SELECT * FROM users WHERE id=?', (user_id,))",
                        code_snippet=line.strip()[:80],
                    ))
        return issues

    # ---- 文件过长检查 ----

    def _check_long_file(self, code: str) -> List[Issue]:
        """检查文件是否过长"""
        lines = code.splitlines()
        if len(lines) > 500:
            return [Issue(
                line=1,
                col=0,
                severity="warning",
                category="maintainability",
                description=f"文件过长（{len(lines)} 行，建议 < 500 行）",
                suggestion="考虑拆分为多个模块，按功能职责分离",
                code_snippet="",
            )]
        return []

    # ---- Python: 未使用的变量和导入 ----

    def _check_python_unused(self, code: str) -> List[Issue]:
        """检查未使用的变量和导入（基于 AST）"""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        # 收集所有定义的名称
        defined_names = {}  # name -> (line, col)
        used_names = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    defined_names[name] = (node.lineno, node.col_offset)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    defined_names[name] = (node.lineno, node.col_offset)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id not in defined_names:
                            defined_names[target.id] = (node.lineno, node.col_offset)
            elif isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    used_names.add(node.value.id)

        # 找出未使用的
        for name, (line, col) in defined_names.items():
            if name.startswith('_'):
                continue
            if name not in used_names:
                # 获取代码片段
                lines = code.splitlines()
                snippet = lines[line - 1].strip()[:80] if line <= len(lines) else ""
                issues.append(Issue(
                    line=line,
                    col=col,
                    severity="warning",
                    category="unused",
                    description=f"未使用的变量/导入: {name}",
                    suggestion=f"移除未使用的 '{name}'，或添加前缀 _ 表示有意保留",
                    code_snippet=snippet,
                ))

        return issues

    # ---- Python: None 安全检查 ----

    def _check_python_none_safety(self, code: str) -> List[Issue]:
        """检查潜在的 None/空指针异常"""
        issues = []
        lines = code.splitlines()

        # 模式: 变量可能为 None 时直接调用方法
        none_patterns = [
            (r'(\w+)\.(\w+)\s*\(', "potential_none_call"),
        ]

        for i, line in enumerate(lines, 1):
            # 检查: x = func(); x.method() 没有判断 None
            # 简化检测：如果上一行是赋值来自函数调用，当前行直接调用方法
            if i > 1:
                prev = lines[i - 2].strip() if i >= 2 else ""
                curr = line.strip()
                # 检测 x = something()  下一行 x.method()
                match_prev = re.match(r'(\w+)\s*=\s*\w+\(', prev)
                if match_prev:
                    var_name = match_prev.group(1)
                    if re.match(rf'{var_name}\.\w+\(', curr) and 'if' not in prev:
                        issues.append(Issue(
                            line=i,
                            col=0,
                            severity="warning",
                            category="none_safety",
                            description=f"变量 '{var_name}' 可能为 None，未检查就调用方法",
                            suggestion=f"添加 None 检查: if {var_name} is not None: ...",
                            code_snippet=curr[:80],
                        ))

        return issues

    # ---- Python: 圈复杂度检查 ----

    def _check_python_complexity(self, code: str) -> List[Issue]:
        """检查函数圈复杂度"""
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = self._calc_complexity(node)
                if complexity > 15:
                    issues.append(Issue(
                        line=node.lineno,
                        col=node.col_offset,
                        severity="warning" if complexity <= 25 else "error",
                        category="complexity",
                        description=f"函数 '{node.name}' 圈复杂度过高 ({complexity})",
                        suggestion="拆分函数为更小的子函数，减少条件分支嵌套",
                        code_snippet=f"def {node.name}(...):  # complexity={complexity}",
                    ))
        return issues

    def _calc_complexity(self, func_node) -> int:
        """计算函数的圈复杂度"""
        complexity = 1
        for node in ast.walk(func_node):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
            elif isinstance(node, (ast.ExceptHandler,)):
                complexity += 1
            elif isinstance(node, ast.comprehension):
                complexity += 1
        return complexity

    # ---- 生成审查报告 ----

    def generate_report(self, issues: List[Issue], file_name: str = "") -> str:
        """生成格式化的审查报告"""
        if not issues:
            return f"✅ 代码审查通过，未发现问题。{f' ({file_name})' if file_name else ''}"

        # 按严重级别统计
        stats = {"error": 0, "warning": 0, "info": 0}
        for issue in issues:
            stats[issue.severity] = stats.get(issue.severity, 0) + 1

        lines = []
        lines.append(f"📋 代码审查报告{f' — {file_name}' if file_name else ''}")
        lines.append(f"   发现 {len(issues)} 个问题: 🔴{stats['error']} 错误 / 🟡{stats['warning']} 警告 / 🔵{stats['info']} 提示")
        lines.append("")

        for i, issue in enumerate(issues, 1):
            icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(issue.severity, "⚪")
            lines.append(f"{i}. {icon} [L{issue.line}] {issue.description}")
            if issue.code_snippet:
                lines.append(f"   代码: {issue.code_snippet}")
            if issue.suggestion:
                lines.append(f"   建议: {issue.suggestion}")
            lines.append("")

        return "\n".join(lines)

    # ---- Tool Handler ----

    def _tool_review_code(self, **kwargs) -> str:
        code = kwargs.get("code", "")
        language = kwargs.get("language", "python")
        issues = self.review_code(code, language)
        return self.generate_report(issues)

    def _tool_review_file(self, **kwargs) -> str:
        file_path = kwargs.get("file_path", "")
        if not os.path.exists(file_path):
            return f"文件不存在: {file_path}"
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            code = f.read()
        ext = os.path.splitext(file_path)[1].lower()
        lang_map = {'.py': 'python', '.js': 'javascript'}
        language = lang_map.get(ext, 'generic')
        issues = self.review_code(code, language)
        return self.generate_report(issues, os.path.basename(file_path))

    # ---- Hook: 任务完成后自动审查 ----

    def _hook_after_task(self, **kwargs) -> dict:
        """AFTER_TASK Hook — 自动审查刚写入的文件"""
        file_path = kwargs.get("file_path", "")
        if not file_path or not os.path.exists(file_path):
            return {}

        ext = os.path.splitext(file_path)[1].lower()
        if ext != '.py':
            return {}

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                code = f.read()
            issues = self.review_code(code, 'python')
            if issues:
                errors = sum(1 for i in issues if i.severity == "error")
                warnings = sum(1 for i in issues if i.severity == "warning")
                return {
                    "reviewed": True,
                    "file": file_path,
                    "issues": [i.to_dict() for i in issues],
                    "error_count": errors,
                    "warning_count": warnings,
                }
        except Exception:
            pass
        return {}


# ============================================================
# 便捷函数
# ============================================================

def format_code(code: str, language: str = "python") -> FormatResult:
    """快捷格式化"""
    skill = CodeFormatterSkill()
    return skill.format_code(code, language)


def review_code(code: str, language: str = "python") -> List[Issue]:
    """快捷审查"""
    skill = CodeReviewSkill()
    return skill.review_code(code, language)
