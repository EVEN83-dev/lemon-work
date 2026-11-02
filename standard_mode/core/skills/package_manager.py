# -*- coding: utf-8 -*-
"""
Skill: package_manager — 包管理 Skill（v0.9.0 新增）
=====================================================
统一封装 pip / npm 包管理操作：

  pip:
    - install    安装 Python 包
    - uninstall  卸载 Python 包
    - list       列出已安装的 Python 包
    - check      检测包是否已安装

  npm:
    - install    安装 npm 包
    - list       列出已安装的 npm 包
    - check      检测包是否已安装

特性：
  - 自动选择正确的包管理器（基于 ecosystem 参数或文件类型）
  - 优雅降级：pip/npm 未安装时返回提示信息
  - 安装超时保护（默认 120 秒）
"""

import os
import subprocess
import shutil
from typing import Dict, Any, List, Optional

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "package_manager",
    "description": "包管理 Skill：支持 pip install/uninstall/list、npm install/list、自动选择包管理器",
    "category": "tooling",
    "version": "1.0.0",
}


# ============================================================
# 包管理器检测
# ============================================================

def _detect_pip() -> Optional[str]:
    """检测 pip 可执行文件路径"""
    # 优先使用当前 Python 的 pip
    pip_path = os.path.join(os.path.dirname(sys.executable), "pip")
    if os.path.exists(pip_path):
        return pip_path
    pip_exe = shutil.which("pip") or shutil.which("pip3")
    return pip_exe


def _detect_npm() -> Optional[str]:
    """检测 npm 可执行文件路径"""
    return shutil.which("npm")


def _detect_pip_in_venv() -> Optional[str]:
    """检测虚拟环境中的 pip"""
    # 检查 .venv / venv
    candidates = [
        os.path.join(os.getcwd(), ".venv", "Scripts", "pip.exe"),
        os.path.join(os.getcwd(), ".venv", "bin", "pip"),
        os.path.join(os.getcwd(), "venv", "Scripts", "pip.exe"),
        os.path.join(os.getcwd(), "venv", "bin", "pip"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


# ============================================================
# 命令执行
# ============================================================

def _run_command(
    cmd: List[str],
    cwd: str = "",
    timeout: int = 120,
) -> Dict[str, Any]:
    """执行命令并返回结构化结果"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"命令超时（{timeout}s）",
            "success": False,
        }
    except FileNotFoundError:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "命令未找到",
            "success": False,
        }
    except Exception as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "success": False,
        }


# ============================================================
# pip 操作
# ============================================================

def _pip_install(
    packages: List[str],
    upgrade: bool = False,
    user: bool = False,
    requirements_file: str = "",
    cwd: str = "",
    timeout: int = 180,
) -> SkillResult:
    """pip install"""
    pip = _detect_pip_in_venv() or _detect_pip()
    if not pip:
        return SkillResult(
            success=False,
            error="pip 未安装。请确保已安装 Python 并配置 pip。",
        )

    cmd = [pip, "install"]
    if upgrade:
        cmd.append("-U")
    if user:
        cmd.append("--user")
    if requirements_file:
        cmd.extend(["-r", requirements_file])
    else:
        if not packages:
            return SkillResult(success=False, error="pip install 需要 packages 或 requirements_file 参数")
        cmd.extend(packages)

    r = _run_command(cmd, cwd=cwd, timeout=timeout)
    if not r["success"]:
        return SkillResult(success=False, error=r["stderr"] or r["stdout"])

    installed = [p for p in packages] if packages else ["(from requirements)"]
    return SkillResult(
        success=True,
        output=f"✅ pip install 成功: {', '.join(installed)}\n{r['stdout'][-1500:]}",
        data={
            "packages": installed,
            "upgrade": upgrade,
            "user": user,
            "output": r["stdout"],
        },
    )


def _pip_uninstall(packages: List[str], cwd: str = "", timeout: int = 60) -> SkillResult:
    """pip uninstall"""
    if not packages:
        return SkillResult(success=False, error="pip uninstall 需要 packages 参数")
    pip = _detect_pip_in_venv() or _detect_pip()
    if not pip:
        return SkillResult(success=False, error="pip 未安装")
    cmd = [pip, "uninstall", "-y"] + packages
    r = _run_command(cmd, cwd=cwd, timeout=timeout)
    if not r["success"]:
        return SkillResult(success=False, error=r["stderr"] or r["stdout"])
    return SkillResult(
        success=True,
        output=f"✅ pip uninstall 成功: {', '.join(packages)}\n{r['stdout'][-1000:]}",
        data={"packages": packages, "output": r["stdout"]},
    )


def _pip_list(cwd: str = "", outdated: bool = False) -> SkillResult:
    """pip list"""
    pip = _detect_pip_in_venv() or _detect_pip()
    if not pip:
        return SkillResult(success=False, error="pip 未安装")
    cmd = [pip, "list"]
    if outdated:
        cmd.append("--outdated")
    r = _run_command(cmd, cwd=cwd, timeout=30)
    if not r["success"]:
        return SkillResult(success=False, error=r["stderr"])
    # 解析包列表
    lines = r["stdout"].strip().split("\n")
    packages = []
    for line in lines[2:]:  # 跳过表头
        parts = line.split()
        if len(parts) >= 2:
            packages.append({"name": parts[0], "version": parts[1]})
    return SkillResult(
        success=True,
        output=f"✅ 已安装 {len(packages)} 个 Python 包:\n{r['stdout'][:2000]}",
        data={"packages": packages, "count": len(packages), "outdated": outdated},
    )


def _pip_check(package: str) -> SkillResult:
    """检测包是否已安装"""
    if not package:
        return SkillResult(success=False, error="check 需要 package 参数")
    pip = _detect_pip_in_venv() or _detect_pip()
    if not pip:
        return SkillResult(success=False, error="pip 未安装")
    # 使用 pip show 检测
    r = _run_command([pip, "show", package], timeout=10)
    if r["success"]:
        # 解析包信息
        info = {}
        for line in r["stdout"].split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                info[key.strip().lower().replace(" ", "_")] = value.strip()
        return SkillResult(
            success=True,
            output=f"✅ {package} 已安装: {info.get('version', '?')}",
            data={
                "installed": True,
                "name": package,
                "version": info.get("version", ""),
                "location": info.get("location", ""),
                "summary": info.get("summary", ""),
            },
        )
    return SkillResult(
        success=True,
        output=f"ℹ {package} 未安装",
        data={"installed": False, "name": package},
    )


# ============================================================
# npm 操作
# ============================================================

def _npm_install(
    packages: List[str],
    save_dev: bool = False,
    global_install: bool = False,
    cwd: str = "",
    timeout: int = 180,
) -> SkillResult:
    """npm install"""
    npm = _detect_npm()
    if not npm:
        return SkillResult(
            success=False,
            error="npm 未安装。请安装 Node.js: https://nodejs.org/",
        )
    cmd = [npm, "install"]
    if save_dev:
        cmd.append("--save-dev")
    if global_install:
        cmd.append("-g")
    if packages:
        cmd.extend(packages)

    r = _run_command(cmd, cwd=cwd, timeout=timeout)
    if not r["success"]:
        return SkillResult(success=False, error=r["stderr"] or r["stdout"])
    installed = packages if packages else ["(from package.json)"]
    return SkillResult(
        success=True,
        output=f"✅ npm install 成功: {', '.join(installed)}\n{r['stdout'][-1500:]}",
        data={
            "packages": installed,
            "save_dev": save_dev,
            "global": global_install,
            "output": r["stdout"],
        },
    )


def _npm_list(global_list: bool = False, cwd: str = "", depth: int = 0) -> SkillResult:
    """npm list"""
    npm = _detect_npm()
    if not npm:
        return SkillResult(success=False, error="npm 未安装")
    cmd = [npm, "list", f"--depth={depth}"]
    if global_list:
        cmd.append("-g")
    r = _run_command(cmd, cwd=cwd, timeout=30)
    if not r["success"]:
        # npm list 在某些情况下返回非 0 但仍有输出
        if not r["stdout"]:
            return SkillResult(success=False, error=r["stderr"])
    return SkillResult(
        success=True,
        output=f"✅ npm 包列表:\n{r['stdout'][:2000]}",
        data={"output": r["stdout"], "global": global_list, "depth": depth},
    )


def _npm_check(package: str) -> SkillResult:
    """检测 npm 包是否已安装（本地）"""
    if not package:
        return SkillResult(success=False, error="check 需要 package 参数")
    npm = _detect_npm()
    if not npm:
        return SkillResult(success=False, error="npm 未安装")
    # npm list <package> --depth=0
    r = _run_command([npm, "list", package, "--depth=0"], timeout=10)
    if r["success"] and package in r["stdout"] and "(empty)" not in r["stdout"]:
        # 尝试提取版本
        version = ""
        for line in r["stdout"].split("\n"):
            if package in line and "@" in line:
                # 格式: └── package@1.0.0
                parts = line.split("@")
                if len(parts) >= 2:
                    version = parts[-1].strip()
        return SkillResult(
            success=True,
            output=f"✅ {package} 已安装: {version or '?'}",
            data={"installed": True, "name": package, "version": version},
        )
    return SkillResult(
        success=True,
        output=f"ℹ {package} 未安装",
        data={"installed": False, "name": package},
    )


# ============================================================
# 自动选择包管理器
# ============================================================

def _auto_detect_ecosystem(package_name: str) -> str:
    """根据包名自动推断生态系统"""
    # 常见的 Python 包名特征
    python_indicators = [
        "py", "django", "flask", "numpy", "pandas", "scipy",
        "matplotlib", "tensorflow", "torch", "transformers",
        "pyqt", "pyramid", "fastapi", "uvicorn", "gunicorn",
    ]
    # 常见的 npm 包名特征
    npm_indicators = [
        "react", "vue", "angular", "next", "nuxt", "express",
        "webpack", "vite", "rollup", "typescript", "eslint",
        "prettier", "babel", "jest", "playwright",
    ]
    pkg_lower = package_name.lower()
    for ind in python_indicators:
        if ind in pkg_lower:
            return "pip"
    for ind in npm_indicators:
        if ind in pkg_lower:
            return "npm"
    # 默认根据作用域判断
    if pkg_lower.startswith("@"):
        return "npm"
    return "pip"  # 默认 pip


# ============================================================
# 统一入口
# ============================================================

def execute(
    action: str = "install",
    ecosystem: str = "auto",
    packages: str = "",
    package: str = "",
    upgrade: bool = False,
    user: bool = False,
    save_dev: bool = False,
    global_install: bool = False,
    requirements_file: str = "",
    outdated: bool = False,
    depth: int = 0,
    cwd: str = "",
    timeout: int = 180,
) -> SkillResult:
    """包管理 Skill 统一入口

    Args:
        action: 操作类型 install/uninstall/list/check
        ecosystem: 生态系统 auto/pip/npm
        packages: 逗号分隔的包名列表（install/uninstall 使用）
        package: 单个包名（check 使用）
        upgrade: pip install 是否升级
        user: pip install 是否安装到用户目录
        save_dev: npm install 是否保存到 devDependencies
        global_install: npm install 是否全局安装
        requirements_file: pip install 的 requirements.txt 路径
        outdated: pip list 是否只看过期包
        depth: npm list 的深度
        cwd: 工作目录
        timeout: 超时（秒）
    """
    action = (action or "").lower().strip()

    # 解析包列表
    pkg_list = [p.strip() for p in packages.split(",") if p.strip()] if packages else []
    single_pkg = package or (pkg_list[0] if pkg_list else "")

    # 自动检测生态系统
    if ecosystem == "auto":
        if action == "check":
            eco = _auto_detect_ecosystem(single_pkg)
        elif pkg_list:
            eco = _auto_detect_ecosystem(pkg_list[0])
        else:
            eco = "pip"  # 默认
    else:
        eco = ecosystem

    # 分发到具体实现
    if action == "install":
        if eco == "pip":
            return _pip_install(pkg_list, upgrade=upgrade, user=user, requirements_file=requirements_file, cwd=cwd, timeout=timeout)
        if eco == "npm":
            return _npm_install(pkg_list, save_dev=save_dev, global_install=global_install, cwd=cwd, timeout=timeout)
        return SkillResult(success=False, error=f"不支持的生态系统: {eco}")

    if action == "uninstall":
        if eco == "pip":
            return _pip_uninstall(pkg_list, cwd=cwd, timeout=timeout)
        if eco == "npm":
            # npm uninstall
            npm = _detect_npm()
            if not npm:
                return SkillResult(success=False, error="npm 未安装")
            cmd = [npm, "uninstall"]
            if global_install:
                cmd.append("-g")
            cmd.extend(pkg_list)
            r = _run_command(cmd, cwd=cwd, timeout=timeout)
            if not r["success"]:
                return SkillResult(success=False, error=r["stderr"] or r["stdout"])
            return SkillResult(
                success=True,
                output=f"✅ npm uninstall 成功: {', '.join(pkg_list)}",
                data={"packages": pkg_list},
            )
        return SkillResult(success=False, error=f"不支持的生态系统: {eco}")

    if action == "list":
        if eco == "pip":
            return _pip_list(cwd=cwd, outdated=outdated)
        if eco == "npm":
            return _npm_list(global_list=global_install, cwd=cwd, depth=depth)
        return SkillResult(success=False, error=f"不支持的生态系统: {eco}")

    if action == "check":
        if eco == "pip":
            return _pip_check(single_pkg)
        if eco == "npm":
            return _npm_check(single_pkg)
        return SkillResult(success=False, error=f"不支持的生态系统: {eco}")

    return SkillResult(
        success=False,
        error=f"未知 action: {action}（支持: install/uninstall/list/check）",
    )


def register(registry) -> None:
    """向 SkillsRegistry 注册 package_manager Skill"""
    registry.register(SkillDef(
        name="package_manager",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型",
                    "enum": ["install", "uninstall", "list", "check"],
                },
                "ecosystem": {
                    "type": "string",
                    "description": "包管理系统",
                    "enum": ["auto", "pip", "npm"],
                    "default": "auto",
                },
                "packages": {
                    "type": "string",
                    "description": "逗号分隔的包名列表（install/uninstall 使用）",
                },
                "package": {"type": "string", "description": "单个包名（check 使用）"},
                "upgrade": {"type": "boolean", "description": "pip install 是否升级", "default": False},
                "user": {"type": "boolean", "description": "pip install 是否安装到用户目录", "default": False},
                "save_dev": {"type": "boolean", "description": "npm install 是否保存到 devDependencies", "default": False},
                "global_install": {"type": "boolean", "description": "npm install/list 是否全局", "default": False},
                "requirements_file": {"type": "string", "description": "pip install 的 requirements.txt 路径"},
                "outdated": {"type": "boolean", "description": "pip list 是否只看过期包", "default": False},
                "depth": {"type": "integer", "description": "npm list 的深度", "default": 0},
                "cwd": {"type": "string", "description": "工作目录"},
                "timeout": {"type": "integer", "description": "超时（秒）", "default": 180},
            },
            "required": ["action"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=False,
        timeout=180,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA


def is_available(ecosystem: str = "auto") -> Dict[str, bool]:
    """检测包管理器可用性"""
    return {
        "pip": _detect_pip() is not None,
        "npm": _detect_npm() is not None,
    }
