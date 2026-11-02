# -*- coding: utf-8 -*-
"""
Skill: security_auditor — 安全审计
====================================
漏洞扫描 + 依赖安全检查，检测 SQL 注入/XSS/命令注入/
硬编码密钥/弱加密等 25+ 规则。
"""

import ast
import json
import os
import re
import traceback
from typing import Dict, Any, List

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "security_auditor",
    "description": "安全审计：漏洞扫描 + 依赖安全检查，检测 SQL 注入/XSS/命令注入/硬编码密钥/弱加密等 25+ 规则",
    "category": "code",
    "version": "1.0.0",
}

# 安全规则
SECURITY_RULES = [
    # 硬编码密钥
    (r'password\s*=\s*["\'][^"\']{4,}["\']', 'HARDCODED_PASSWORD', '硬编码密码', 'critical'),
    (r'passwd\s*=\s*["\'][^"\']{4,}["\']', 'HARDCODED_PASSWD', '硬编码密码', 'critical'),
    (r'api_key\s*=\s*["\'][^"\']{8,}["\']', 'HARDCODED_API_KEY', '硬编码 API Key', 'critical'),
    (r'secret\s*=\s*["\'][^"\']{8,}["\']', 'HARDCODED_SECRET', '硬编码密钥', 'critical'),
    (r'token\s*=\s*["\'][^"\']{8,}["\']', 'HARDCODED_TOKEN', '硬编码 Token', 'critical'),
    (r'private_key\s*=\s*["\'][^"\']+["\']', 'HARDCODED_PRIVATE_KEY', '硬编码私钥', 'critical'),
    # SQL 注入
    (r'execute\s*\(\s*f["\'].*SELECT|INSERT|UPDATE|DELETE', 'SQL_INJECTION_FSTRING', 'SQL f-string 注入', 'critical'),
    (r'execute\s*\(\s*["\'].*%s.*["\']\s*%', 'SQL_INJECTION_FORMAT', 'SQL format 注入', 'critical'),
    (r'cursor\.execute\s*\(\s*["\'].*\+.*["\']', 'SQL_INJECTION_CONCAT', 'SQL 字符串拼接注入', 'critical'),
    # 命令注入
    (r'subprocess\.\w+\s*\([^)]*shell\s*=\s*True', 'COMMAND_INJECTION', 'shell=True 命令注入', 'high'),
    (r'os\.system\s*\(', 'OS_SYSTEM', 'os.system 命令执行', 'high'),
    (r'os\.popen\s*\(', 'OS_POPEN', 'os.popen 命令执行', 'high'),
    # 代码执行
    (r'eval\s*\(', 'EVAL_USAGE', 'eval 使用风险', 'high'),
    (r'exec\s*\(', 'EXEC_USAGE', 'exec 使用风险', 'high'),
    (r'__import__\s*\(', 'DYNAMIC_IMPORT', '动态导入风险', 'medium'),
    # 反序列化
    (r'pickle\.loads?\s*\(', 'PICKLE_USAGE', 'pickle 反序列化风险', 'high'),
    (r'yaml\.load\s*\([^)]*\)(?!.*Loader)', 'YAML_UNSAFE_LOAD', 'yaml 不安全加载', 'high'),
    # 弱加密
    (r'hashlib\.md5\s*\(', 'WEAK_HASH_MD5', 'MD5 弱哈希', 'medium'),
    (r'hashlib\.sha1\s*\(', 'WEAK_HASH_SHA1', 'SHA1 弱哈希', 'medium'),
    (r'DES\s*\(', 'WEAK_CRYPTO_DES', 'DES 弱加密', 'high'),
    (r'RC4\s*\(', 'WEAK_CRYPTO_RC4', 'RC4 弱加密', 'high'),
    # 不安全的网络
    (r'requests\.get\s*\(\s*["\']http://', 'HTTP_NOT_HTTPS', 'HTTP 明文传输', 'medium'),
    (r'urllib\.request\.urlopen\s*\(\s*["\']http://', 'HTTP_NOT_HTTPS_URLLIB', 'HTTP 明文传输', 'medium'),
    # CORS / XSS
    (r'Access-Control-Allow-Origin.*\*', 'CORS_WILDCARD', 'CORS 通配符', 'medium'),
    (r'markup_safe\s*=\s*False|autoescape\s*=\s*False', 'XSS_AUTOESCAPE_OFF', 'XSS 自动转义关闭', 'high'),
    # 调试
    (r'DEBUG\s*=\s*True', 'DEBUG_ENABLED', '调试模式开启', 'low'),
]


def execute(
    code: str = "",
    file_path: str = "",
    project_path: str = "",
    severity_threshold: str = "low",
) -> SkillResult:
    """安全审计

    Args:
        code: 代码内容
        file_path: 单文件路径
        project_path: 项目路径（扫描所有文件）
        severity_threshold: 严重级别阈值 low/medium/high/critical
    """
    if not code and not file_path and not project_path:
        return SkillResult(success=False, error="code, file_path 或 project_path 必须有一个")

    try:
        severity_order = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
        min_severity = severity_order.get(severity_threshold, 0)

        # 收集要扫描的代码
        files_to_scan = {}
        if project_path:
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'venv', '.venv', 'node_modules'}]
                for f in files:
                    if f.endswith('.py'):
                        fpath = os.path.join(root, f)
                        try:
                            with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                                files_to_scan[fpath] = fh.read()
                        except Exception:
                            pass
        elif file_path:
            if not os.path.exists(file_path):
                return SkillResult(success=False, error=f"文件不存在: {file_path}")
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                files_to_scan[file_path] = f.read()
        elif code:
            files_to_scan['<inline>'] = code

        # 扫描
        vulnerabilities = []
        for fpath, source in files_to_scan.items():
            lines = source.splitlines()
            for i, line in enumerate(lines, 1):
                for pattern, rule_id, desc, severity in SECURITY_RULES:
                    if severity_order.get(severity, 0) < min_severity:
                        continue
                    if re.search(pattern, line, re.IGNORECASE):
                        vulnerabilities.append({
                            'file': fpath, 'line': i, 'rule_id': rule_id,
                            'severity': severity, 'description': desc,
                            'code': line.strip()[:80],
                        })

        # 统计
        stats = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
        for v in vulnerabilities:
            stats[v['severity']] = stats.get(v['severity'], 0) + 1

        # 生成报告
        if not vulnerabilities:
            output = "✅ 安全审计通过，未发现漏洞。"
        else:
            icon_map = {'critical': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🔵'}
            output = f"🔒 安全审计报告\n扫描文件: {len(files_to_scan)}\n发现漏洞: {len(vulnerabilities)}\n"
            output += f"🔴 严重: {stats.get('critical',0)} | 🟠 高危: {stats.get('high',0)} | 🟡 中危: {stats.get('medium',0)} | 🔵 低危: {stats.get('low',0)}\n\n"
            for i, v in enumerate(vulnerabilities[:30], 1):
                icon = icon_map.get(v['severity'], '⚪')
                fname = os.path.basename(v['file'])
                output += f"{i}. {icon} [{v['rule_id']}] L{v['line']} {v['description']}\n"
                output += f"   文件: {fname} | {v['code']}\n"

        return SkillResult(
            success=True,
            output=output,
            data={'vulnerabilities': vulnerabilities, 'stats': stats, 'files_scanned': len(files_to_scan)},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"安全审计失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="security_auditor",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "代码内容"},
                "file_path": {"type": "string", "description": "单文件路径"},
                "project_path": {"type": "string", "description": "项目路径（扫描所有文件）"},
                "severity_threshold": {"type": "string", "enum": ["low", "medium", "high", "critical"], "description": "严重级别阈值", "default": "low"},
            },
        },
        handler=execute,
        category=METADATA["category"],
        timeout=60,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
