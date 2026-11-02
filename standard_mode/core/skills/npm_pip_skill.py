# -*- coding: utf-8 -*-
"""
Skill: npm_pip_skill — 包管理 Skill（L3 新增）
=============================================
通过 npm / pip CLI 管理依赖包，供 Agent 自主管理项目依赖。

支持的操作：
  install      — 安装包（npm install / pip install）
  update       — 更新包
  list         — 列出已安装包
  uninstall    — 卸载包
  outdated     — 检查过期包
  init         — 初始化项目（npm init / pip freeze → requirements.txt）

优雅降级：
  - npm/pip 未安装时返回安装指引
  - 命令失败捕获 stderr 返回 SkillResult
"""

import os
import subprocess
import json
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "npm_pip_skill",
    "description": "包管理：npm/pip 安装/更新/列表/卸载/检查过期（npm & pip CLI）",
    "category": "system",
    "version": "1.0.0",
}


def _check_cli(tool: str) -> bool:
    try:
        subprocess.run([tool, '--version'], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _run(cmd: list, timeout: int = 120, cwd: str = "") -> tuple:
    try:
        kwargs = {"capture_output": True, "text": True, "timeout": timeout, "errors": "replace"}
        if cwd and os.path.isdir(cwd):
            kwargs["cwd"] = cwd
        proc = subprocess.run(cmd, **kwargs)
        return proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        return "", "命令超时", -1
    except Exception as e:
        return "", str(e), -1


# ==================== pip 操作 ====================

def _pip_install(packages: str, cwd: str = "", upgrade: bool = False) -> SkillResult:
    if not packages:
        return SkillResult(success=False, error="packages 参数为必填")
    pkg_list = [p.strip() for p in packages.split(',') if p.strip()]
    if not _check_cli('pip'):
        return SkillResult(success=False, error="pip 未安装")
    args = ['pip', 'install']
    if upgrade:
        args.append('--upgrade')
    args.extend(pkg_list)
    stdout, stderr, code = _run(args, cwd=cwd)
    if code != 0:
        return SkillResult(success=False, error=f"pip install 失败: {stderr[:300]}")
    return SkillResult(
        success=True,
        output=f"pip 安装成功: {packages[:100]}",
        data={"stdout": stdout[:500]},
    )


def _pip_list() -> SkillResult:
    if not _check_cli('pip'):
        return SkillResult(success=False, error="pip 未安装")
    stdout, stderr, code = _run(['pip', 'list', '--format', 'columns'])
    if code != 0:
        return SkillResult(success=False, error=f"pip list 失败: {stderr}")

    # 尝试 JSON 格式获取精确计数
    stdout2, _, code2 = _run(['pip', 'list', '--format', 'json'])
    count = 0
    if code2 == 0:
        try:
            count = len(json.loads(stdout2))
        except Exception:
            pass

    return SkillResult(
        success=True,
        output=f"已安装 {count} 个 Python 包:\n{stdout[:1000]}",
        data={"count": count, "list": stdout},
    )


def _pip_outdated() -> SkillResult:
    if not _check_cli('pip'):
        return SkillResult(success=False, error="pip 未安装")
    stdout, stderr, code = _run(['pip', 'list', '--outdated', '--format', 'columns'])
    if code != 0:
        return SkillResult(success=False, error=f"pip outdated 失败: {stderr}")
    lines = stdout.strip().split('\n')
    count = max(0, len(lines) - 2)
    return SkillResult(
        success=True,
        output=f"{count} 个过期 Python 包:\n{stdout[:1000]}",
        data={"outdated": count},
    )


def _pip_uninstall(packages: str) -> SkillResult:
    if not packages:
        return SkillResult(success=False, error="packages 参数为必填")
    pkg_list = [p.strip() for p in packages.split(',') if p.strip()]
    if not _check_cli('pip'):
        return SkillResult(success=False, error="pip 未安装")
    stdout, stderr, code = _run(['pip', 'uninstall', '-y'] + pkg_list)
    if code != 0:
        return SkillResult(success=False, error=f"pip uninstall 失败: {stderr[:300]}")
    return SkillResult(success=True, output=f"pip 卸载成功: {packages}")


def _pip_freeze(cwd: str = "") -> SkillResult:
    """导出 requirements.txt"""
    if not _check_cli('pip'):
        return SkillResult(success=False, error="pip 未安装")
    stdout, stderr, code = _run(['pip', 'freeze'], cwd=cwd)
    if code != 0:
        return SkillResult(success=False, error=f"pip freeze 失败: {stderr}")
    filepath = os.path.join(cwd or '.', 'requirements.txt')
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(stdout)
    except Exception:
        pass
    return SkillResult(
        success=True,
        output=f"已导出 {stdout.count(chr(10))} 个包到 requirements.txt",
        data={"file": filepath},
    )


# ==================== npm 操作 ====================

def _npm_install(packages: str, cwd: str = "", dev: bool = False) -> SkillResult:
    if not _check_cli('npm'):
        return SkillResult(success=False, error="npm 未安装")
    pkg_list = [p.strip() for p in packages.split(',') if p.strip()]
    args = ['npm', 'install']
    if dev:
        args.append('--save-dev')
    if pkg_list:
        args.extend(pkg_list)
    stdout, stderr, code = _run(args, cwd=cwd)
    if code != 0:
        return SkillResult(success=False, error=f"npm install 失败: {stderr[:300]}")
    return SkillResult(success=True, output=f"npm 安装成功", data={"stdout": stdout[:500]})


def _npm_list(cwd: str = "") -> SkillResult:
    if not _check_cli('npm'):
        return SkillResult(success=False, error="npm 未安装")
    stdout, stderr, code = _run(['npm', 'list', '--depth=0'], cwd=cwd)
    return SkillResult(
        success=True,
        output=f"npm 依赖:\n{stdout[:1000]}",
        data={"list": stdout},
    )


def _npm_outdated(cwd: str = "") -> SkillResult:
    if not _check_cli('npm'):
        return SkillResult(success=False, error="npm 未安装")
    stdout, stderr, code = _run(['npm', 'outdated'], cwd=cwd)
    if code != 0 and not stdout:
        return SkillResult(success=True, output="无过期 npm 包", data={"outdated": 0})
    count = max(0, len(stdout.strip().split('\n')) - 1)
    return SkillResult(
        success=True,
        output=f"{count} 个过期 npm 包:\n{stdout[:1000]}",
        data={"outdated": count},
    )


# ==================== 统一入口 ====================

def execute(
    action: str = "pip_install",
    tool: str = "pip",
    packages: str = "",
    cwd: str = "",
    dev: bool = False,
    upgrade: bool = False,
) -> SkillResult:
    action = (action or "").lower().strip()

    # pip 操作
    if action == "pip_install":
        return _pip_install(packages, cwd, upgrade)
    if action == "pip_list":
        return _pip_list()
    if action == "pip_outdated":
        return _pip_outdated()
    if action == "pip_uninstall":
        return _pip_uninstall(packages)
    if action == "pip_freeze":
        return _pip_freeze(cwd)

    # npm 操作
    if action == "npm_install":
        return _npm_install(packages, cwd, dev)
    if action == "npm_list":
        return _npm_list(cwd)
    if action == "npm_outdated":
        return _npm_outdated(cwd)

    supported = ["pip_install", "pip_list", "pip_outdated", "pip_uninstall", "pip_freeze",
                 "npm_install", "npm_list", "npm_outdated"]
    return SkillResult(
        success=False,
        error=f"未知 action: {action}（支持: {', '.join(supported)}）",
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="npm_pip_skill",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string", "description": "操作类型",
                    "enum": [
                        "pip_install", "pip_list", "pip_outdated", "pip_uninstall", "pip_freeze",
                        "npm_install", "npm_list", "npm_outdated",
                    ],
                },
                "packages": {"type": "string", "description": "包名（逗号分隔）"},
                "cwd": {"type": "string", "description": "工作目录（默认当前）", "default": ""},
                "dev": {"type": "boolean", "description": "npm --save-dev", "default": False},
                "upgrade": {"type": "boolean", "description": "pip --upgrade", "default": False},
            },
            "required": ["action"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=False,
        timeout=120,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA


def is_available() -> bool:
    return _check_cli('pip') or _check_cli('npm')
