# -*- coding: utf-8 -*-
"""
Skill: docker_skill — Docker 容器管理（L3 新增）
===============================================
通过 docker CLI 管理容器，供 Agent 自主部署与运维。

支持的操作：
  ps           — 列出容器
  run          — 启动容器
  stop         — 停止容器
  logs         — 查看日志
  build        — 构建镜像
  images       — 列出镜像
  exec         — 在运行容器中执行命令

优雅降级：
  - docker 命令未安装时返回安装指引
  - 命令失败捕获 stderr 返回 SkillResult
"""

import os
import subprocess
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "docker_skill",
    "description": "Docker 容器管理：启动/停止/列表/日志/构建镜像/执行命令（docker CLI）",
    "category": "system",
    "version": "1.0.0",
}


def _check_docker() -> bool:
    """检查 docker CLI 是否可用"""
    try:
        subprocess.run(['docker', '--version'], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _install_hint() -> str:
    return "Docker 未安装或未添加到 PATH。请安装 Docker Desktop: https://www.docker.com/products/docker-desktop"


def _run_docker(args: list, timeout: int = 60, capture: bool = True) -> tuple:
    """执行 docker 命令并返回 (stdout, stderr, exit_code)"""
    try:
        proc = subprocess.run(
            ['docker'] + args,
            capture_output=capture, text=True, timeout=timeout,
            errors='replace',
        )
        return proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        return "", "命令超时", -1
    except Exception as e:
        return "", str(e), -1


def _op_ps(all_containers: bool = False) -> SkillResult:
    """列出容器"""
    if not _check_docker():
        return SkillResult(success=False, error=_install_hint())
    args = ['ps']
    if all_containers:
        args.append('-a')
    args.append('--format')
    args.append('table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}')
    stdout, stderr, code = _run_docker(args)
    if code != 0:
        return SkillResult(success=False, error=f"docker ps 失败: {stderr}")
    count = len(stdout.strip().split('\n')) - 1  # 减去表头
    return SkillResult(
        success=True,
        output=f"Docker 容器 ({count} 个):\n{stdout[:1000]}",
        data={"containers": stdout},
    )


def _op_run(image: str, name: str = "", ports: str = "", env: str = "",
            detach: bool = True) -> SkillResult:
    """启动容器"""
    if not image:
        return SkillResult(success=False, error="image 参数为必填")
    if not _check_docker():
        return SkillResult(success=False, error=_install_hint())
    args = ['run']
    if detach:
        args.append('-d')
    if name:
        args.extend(['--name', name])
    if ports:
        args.extend(['-p', ports])
    if env:
        for e in env.split(','):
            args.extend(['-e', e.strip()])
    args.append(image)
    stdout, stderr, code = _run_docker(args)
    if code != 0:
        return SkillResult(success=False, error=f"docker run 失败: {stderr}")
    return SkillResult(
        success=True,
        output=f"容器已启动: {stdout.strip()[:20]}",
        data={"container_id": stdout.strip()},
    )


def _op_stop(container: str) -> SkillResult:
    """停止容器"""
    if not container:
        return SkillResult(success=False, error="container 参数为必填")
    if not _check_docker():
        return SkillResult(success=False, error=_install_hint())
    stdout, stderr, code = _run_docker(['stop', container])
    if code != 0:
        return SkillResult(success=False, error=f"docker stop 失败: {stderr}")
    return SkillResult(success=True, output=f"容器已停止: {container}")


def _op_logs(container: str, tail: int = 50) -> SkillResult:
    """查看日志"""
    if not container:
        return SkillResult(success=False, error="container 参数为必填")
    if not _check_docker():
        return SkillResult(success=False, error=_install_hint())
    stdout, stderr, code = _run_docker(['logs', '--tail', str(tail), container])
    if code != 0:
        return SkillResult(success=False, error=f"docker logs 失败: {stderr}")
    return SkillResult(
        success=True,
        output=f"容器 {container} 日志 (最后 {tail} 行):\n{stdout[:1000]}",
        data={"logs": stdout},
    )


def _op_images() -> SkillResult:
    """列出镜像"""
    if not _check_docker():
        return SkillResult(success=False, error=_install_hint())
    stdout, stderr, code = _run_docker(
        ['images', '--format', 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}']
    )
    if code != 0:
        return SkillResult(success=False, error=f"docker images 失败: {stderr}")
    count = max(0, len(stdout.strip().split('\n')) - 1)
    return SkillResult(
        success=True,
        output=f"Docker 镜像 ({count} 个):\n{stdout[:1000]}",
        data={"images": stdout},
    )


def _op_exec(container: str, command: str) -> SkillResult:
    """在容器中执行命令"""
    if not container or not command:
        return SkillResult(success=False, error="container 和 command 参数为必填")
    if not _check_docker():
        return SkillResult(success=False, error=_install_hint())
    stdout, stderr, code = _run_docker(['exec', container] + command.split())
    if code != 0:
        return SkillResult(success=False, error=f"docker exec 失败: {stderr}")
    return SkillResult(
        success=True,
        output=f"执行成功:\n{stdout[:500]}",
        data={"output": stdout},
    )


def execute(
    action: str = "ps",
    image: str = "", name: str = "",
    container: str = "", ports: str = "",
    env: str = "", command: str = "",
    tail: int = 50, detach: bool = True,
    all_containers: bool = False,
) -> SkillResult:
    action = (action or "").lower().strip()

    if action == "ps":
        return _op_ps(all_containers)
    if action == "run":
        return _op_run(image, name, ports, env, detach)
    if action == "stop":
        return _op_stop(container)
    if action == "logs":
        return _op_logs(container, tail)
    if action == "images":
        return _op_images()
    if action == "exec":
        return _op_exec(container, command)

    return SkillResult(
        success=False,
        error=f"未知 action: {action}（支持: ps, run, stop, logs, images, exec）",
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="docker_skill",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string", "description": "操作类型",
                    "enum": ["ps", "run", "stop", "logs", "images", "exec"],
                },
                "image": {"type": "string", "description": "镜像名（run 操作）"},
                "name": {"type": "string", "description": "容器名（run 操作）", "default": ""},
                "container": {"type": "string", "description": "容器名/ID（stop/logs/exec 操作）"},
                "ports": {"type": "string", "description": "端口映射（如 8080:80）", "default": ""},
                "env": {"type": "string", "description": "环境变量（逗号分隔，如 KEY=V）", "default": ""},
                "command": {"type": "string", "description": "要执行命令（exec 操作）"},
                "tail": {"type": "integer", "description": "日志行数（logs 操作）", "default": 50},
                "detach": {"type": "boolean", "description": "后台运行", "default": True},
                "all_containers": {"type": "boolean", "description": "显示全部容器", "default": False},
            },
            "required": ["action"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=True,
        timeout=120,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA


def is_available() -> bool:
    return _check_docker()
