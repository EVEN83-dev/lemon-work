# -*- coding: utf-8 -*-
"""
Skill: code_reviewer — 代码审查
=================================
AST 静态分析 + 常见问题模式检测，支持样式/Bug/安全三类检查。
"""

import ast
import os
import re
import traceback
from typing import Dict, Any, List

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "code_reviewer",
    "description": "代码审查：AST 静态分析 + 常见问题模式检测，支持样式/Bug/安全三类检查",
    "category": "code",
    "version": "1.0.0",
}

# 安全模式
SECURITY_PATTERNS = [
    (r'password\s*=\s*["\'][^"\']+["\']', "硬编码密码", "error"),
    (r'api_key\s*=\s*["\'][^"\']+["\']', "硬编码 API Key", "error"),
    (r'secret\s*=\s*["\'][^"\']+["\']', "硬编码密钥", "error"),
    (r'execute\s*\(\s*f["\']', "SQL f-string（可能注入）", "error"),
    (r'execute\s*\(\s*["\'].*%s.*["\']\s*%', "SQL 字符串拼接（可能注入）", "error"),
    (r'subprocess\.call\s*\(\s*.*shell\s*=\s*True', "shell=True 命令注入风险", "warning"),
    (r'eval\s*\(', "eval 使用风险", "warning"),
    (r'pickle\.loads?\s*\(', "pickle 反序列化风险", "warning"),
]

# 样式模式
STYLE_PATTERNS = [
    (r'^\s*except\s*:', "裸 except（应指定异常类型）", "warning"),
    (r'^\s*except\s+Exception\s*:', "捕获 Exception（建议更具体）", "info"),
    (r'print\s*\(', "print 调试语句", "info"),
    (r'todo|fixme|hack', "TODO/FIXME/HACK 注释", "info"),
]


def execute(
    code: str = "",
    file_path: str = "",
    check_types: str = "style,bug,security",
    language: str = "python",
) -> SkillResult:
    """代码审查

    Args:
        code: 代码内容（与 file_path 二选一）
        file_path: 文件路径
        check_types: 检查类型（逗号分隔）
        language: 编程语言
    """
    if not code and not file_path:
        return SkillResult(success=False, error="code 或 file_path 必须有一个")

    try:
        if file_path and not code:
            if not os.path.exists(file_path):
                return SkillResult(success=False, error=f"文件不存在: {file_path}")
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                code = f.read()

        checks = [c.strip() for c in check_types.split(',')]
        issues = []

        # 样式检查
        if 'style' in checks:
            lines = code.splitlines()
            for i, line in enumerate(lines, 1):
                for pattern, desc, severity in STYLE_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        issues.append({
                            'line': i, 'severity': severity, 'category': 'style',
                            'description': desc, 'code': line.strip()[:80],
                        })

        # Bug 检查（Python AST）
        if 'bug' in checks and language in ('python', 'py'):
            try:
                tree = ast.parse(code)
                # 未使用的导入
                defined = {}
                used = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            name = alias.asname or alias.name
                            defined[name] = node.lineno
                    elif isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            name = alias.asname or alias.name
                            defined[name] = node.lineno
                    elif isinstance(node, ast.Name):
                        used.add(node.id)

                for name, line in defined.items():
                    if name.startswith('_'):
                        continue
                    if name not in used:
                        issues.append({
                            'line': line, 'severity': 'warning', 'category': 'bug',
                            'description': f"未使用的导入: {name}", 'code': '',
                        })

                # 圈复杂度
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        complexity = 1
                        for child in ast.walk(node):
                            if isinstance(child, (ast.If, ast.While, ast.For)):
                                complexity += 1
                            elif isinstance(child, ast.BoolOp):
                                complexity += len(child.values) - 1
                        if complexity > 15:
                            issues.append({
                                'line': node.lineno, 'severity': 'warning', 'category': 'bug',
                                'description': f"函数 '{node.name}' 圈复杂度过高 ({complexity})",
                                'code': f"def {node.name}(...)",
                            })
            except SyntaxError:
                issues.append({'line': 0, 'severity': 'error', 'category': 'bug', 'description': '代码有语法错误', 'code': ''})

        # 安全检查
        if 'security' in checks:
            lines = code.splitlines()
            for i, line in enumerate(lines, 1):
                for pattern, desc, severity in SECURITY_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        issues.append({
                            'line': i, 'severity': severity, 'category': 'security',
                            'description': desc, 'code': line.strip()[:80],
                        })

        # 生成报告
        stats = {'error': 0, 'warning': 0, 'info': 0}
        for issue in issues:
            stats[issue['severity']] = stats.get(issue['severity'], 0) + 1

        if not issues:
            output = "✅ 代码审查通过，未发现问题。"
        else:
            icon_map = {'error': '🔴', 'warning': '🟡', 'info': '🔵'}
            output = f"📋 代码审查报告\n发现 {len(issues)} 个问题: 🔴{stats.get('error',0)} 🟡{stats.get('warning',0)} 🔵{stats.get('info',0)}\n\n"
            for i, issue in enumerate(issues, 1):
                icon = icon_map.get(issue['severity'], '⚪')
                output += f"{i}. {icon} [L{issue['line']}] [{issue['category']}] {issue['description']}\n"
                if issue.get('code'):
                    output += f"   代码: {issue['code']}\n"

        return SkillResult(
            success=True,
            output=output,
            data={'issues': issues, 'stats': stats, 'total': len(issues)},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"代码审查失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="code_reviewer",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "代码内容"},
                "file_path": {"type": "string", "description": "文件路径"},
                "check_types": {"type": "string", "description": "检查类型(style,bug,security)", "default": "style,bug,security"},
                "language": {"type": "string", "description": "编程语言", "default": "python"},
            },
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
