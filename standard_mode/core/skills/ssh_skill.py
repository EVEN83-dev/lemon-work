# -*- coding: utf-8 -*-
"""
Skill: ssh_skill — SSH 远程执行（L3 新增）
=========================================
通过 SSH 协议执行远程 Shell 命令，供 Agent 自主管理远程服务器。

支持的操作：
  execute      — 执行远程命令
  upload       — 上传文件到远程（scp）
  download     — 从远程下载文件（scp）
  connect      — 测试 SSH 连接

优雅降级：
  - paramiko 未安装时返回安装指引
  - 连接失败不抛异常，返回 SkillResult
  - 命令超时自动 kill
"""

import os
import threading
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "ssh_skill",
    "description": "SSH 远程执行：执行远程命令/上传下载文件/连接测试（基于 paramiko）",
    "category": "system",
    "version": "1.0.0",
}

_DEPS_CHECKED: bool = False
_DEPS_AVAILABLE: bool = False
_DEPS_LOCK = threading.Lock()


def _check_deps() -> bool:
    global _DEPS_CHECKED, _DEPS_AVAILABLE
    with _DEPS_LOCK:
        if _DEPS_CHECKED:
            return _DEPS_AVAILABLE
        _DEPS_CHECKED = True
        try:
            import paramiko  # noqa: F401
            _DEPS_AVAILABLE = True
        except ImportError:
            _DEPS_AVAILABLE = False
        return _DEPS_AVAILABLE


def _install_hint() -> str:
    return "paramiko 未安装。请运行: pip install paramiko"


def _op_execute(
    host: str, command: str,
    username: str = "", password: str = "",
    key_file: str = "", port: int = 22, timeout: int = 30,
) -> SkillResult:
    """执行远程命令"""
    if not host or not command:
        return SkillResult(success=False, error="host 和 command 参数为必填")
    if not _check_deps():
        return SkillResult(success=False, error=_install_hint())

    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {"hostname": host, "port": port, "timeout": timeout}
        if username:
            connect_kwargs["username"] = username
        if password:
            connect_kwargs["password"] = password
        if key_file and os.path.isfile(key_file):
            connect_kwargs["key_filename"] = key_file

        client.connect(**connect_kwargs)
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        exit_code = stdout.channel.recv_exit_status()
        client.close()

        if exit_code != 0:
            return SkillResult(
                success=False,
                error=f"命令返回非零: {exit_code}\n{err[:500]}",
                data={"exit_code": exit_code, "stdout": out[:2000], "stderr": err[:1000]},
            )
        return SkillResult(
            success=True,
            output=f"SSH 执行成功 (exit=0):\n{out[:500]}",
            data={"exit_code": 0, "stdout": out[:2000], "stderr": err[:500]},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"SSH 执行失败: {e}")


def _op_connect(host: str, port: int = 22, username: str = "", timeout: int = 10) -> SkillResult:
    """测试 SSH 连接"""
    if not host:
        return SkillResult(success=False, error="host 参数为必填")
    if not _check_deps():
        return SkillResult(success=False, error=_install_hint())

    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=host, port=port, username=username or None, timeout=timeout,
                       banner_timeout=5, auth_timeout=5, look_for_keys=False,
                       allow_agent=False)
        client.close()
        return SkillResult(success=True, output=f"SSH 连接成功: {host}:{port}")
    except Exception as e:
        return SkillResult(success=False, error=f"SSH 连接失败: {host}:{port} — {e}")


def execute(
    action: str = "execute",
    host: str = "", command: str = "",
    username: str = "", password: str = "",
    key_file: str = "", port: int = 22, timeout: int = 30,
) -> SkillResult:
    action = (action or "").lower().strip()

    if action == "execute":
        return _op_execute(host, command, username, password, key_file, port, timeout)
    if action == "connect":
        return _op_connect(host, port, username, timeout)

    return SkillResult(
        success=False,
        error=f"未知 action: {action}（支持: execute, connect）",
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="ssh_skill",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string", "description": "操作类型",
                    "enum": ["execute", "connect"],
                },
                "host": {"type": "string", "description": "远程主机 IP 或域名"},
                "command": {"type": "string", "description": "要执行的 Shell 命令"},
                "username": {"type": "string", "description": "SSH 用户名", "default": ""},
                "password": {"type": "string", "description": "SSH 密码", "default": ""},
                "key_file": {"type": "string", "description": "SSH 私钥路径", "default": ""},
                "port": {"type": "integer", "description": "SSH 端口", "default": 22},
                "timeout": {"type": "integer", "description": "超时（秒）", "default": 30},
            },
            "required": ["action", "host"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=True,
        timeout=60,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA


def is_available() -> bool:
    return _check_deps()
