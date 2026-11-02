# -*- coding: utf-8 -*-
"""
★ 第281章 A 阶段 · 运维专用 Skill 包 (ops_skills)
================================================
SSH / Docker / Git / NPM / Pip 五大运维场景的命令封装，作为可调 Skill 源接入
UniversalSkillRouter（经 get_skills_registry().register）。

设计要点：
- 所有命令用 shlex.split + subprocess.run(shell=False)，不做 shell 拼接，防注入。
- DANGEROUS 命令（force push / reset --hard / docker rm -f / pip uninstall 等）
  必须经 confirm_cb(description) -> bool 二次确认，未确认直接中断。
- 与冻结区标准：本文件位于 standard_mode/ui/skills/，不触碰 standard_mode/core/。
- 返回结构兼容 SkillsRegistry：{"success": bool, "output": str}。

UI 接入：main_window 调 register_ops_tools() 即把全部工具注册进全局路由表；
危险操作经 confirm_cb 弹 Qt 确认框（见 main_window 接线）。
"""
from __future__ import annotations

import json
import shlex
import subprocess
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_log_prefix = "[OpsSkills]"


@dataclass
class OpTool:
    name: str
    category: str          # ssh / docker / git / npm / pip
    description: str
    params: Dict[str, Any]  # JSON-Schema 风格
    dangerous: bool = False
    builder: Callable[[Dict[str, Any]], List[str]] = lambda a: []  # (args) -> argv


# ------------------------------------------------------- 命令构造器 ----------
def _git_commit(a: Dict[str, Any]) -> List[str]:
    msg = a.get("message", "")
    return ["git", "commit", "-m", msg] + (["-a"] if a.get("all") else [])


def _git_push(a: Dict[str, Any]) -> List[str]:
    remote = a.get("remote", "origin")
    branch = a.get("branch")
    cmd = ["git", "push", remote]
    if branch:
        cmd.append(branch)
    if a.get("force"):
        cmd.append("--force")
    if a.get("tags"):
        cmd.append("--tags")
    return cmd


def _git_reset(a: Dict[str, Any]) -> List[str]:
    cmd = ["git", "reset"]
    if a.get("hard"):
        cmd.append("--hard")
    cmd.append(a.get("target", "HEAD"))
    return cmd


def _docker_rm(a: Dict[str, Any]) -> List[str]:
    cmd = ["docker", "rm"]
    if a.get("force"):
        cmd.append("-f")
    if a.get("volumes"):
        cmd.append("-v")
    cmd.append(a.get("container", ""))
    return cmd


def _docker_run(a: Dict[str, Any]) -> List[str]:
    cmd = ["docker", "run"]
    if a.get("detach"):
        cmd.append("-d")
    if a.get("rm"):
        cmd.append("--rm")
    for p in a.get("ports", []):
        cmd += ["-p", p]
    if a.get("name"):
        cmd += ["--name", a.get("name")]
    cmd.append(a.get("image", ""))
    if a.get("command"):
        cmd += shlex.split(a.get("command"))
    return cmd


def _pip_install(a: Dict[str, Any]) -> List[str]:
    cmd = ["pip", "install"]
    if a.get("user"):
        cmd.append("--user")
    if a.get("upgrade"):
        cmd.append("--upgrade")
    cmd += a.get("packages", [])
    return cmd


def _pip_uninstall(a: Dict[str, Any]) -> List[str]:
    cmd = ["pip", "uninstall", "-y"] + a.get("packages", [])
    return cmd


def _npm_publish(a: Dict[str, Any]) -> List[str]:
    cmd = ["npm", "publish"]
    if a.get("tag"):
        cmd += ["--tag", a.get("tag")]
    if a.get("access"):
        cmd += ["--access", a.get("access")]
    return cmd


def _ssh_exec(a: Dict[str, Any]) -> List[str]:
    cmd = ["ssh"]
    if a.get("port"):
        cmd += ["-p", str(a.get("port"))]
    cmd.append(a.get("host", ""))
    cmd += shlex.split(a.get("command", ""))
    return cmd


# ------------------------------------------------------- 工具清单 ----------
OPS_TOOLS: List[OpTool] = [
    # ---------------- Git ----------------
    OpTool("git.status", "git", "查看仓库状态", {"type": "object", "properties": {}},
           builder=lambda a: ["git", "status", "--short", "--branch"]),
    OpTool("git.commit", "git", "提交变更", {
        "type": "object", "properties": {
            "message": {"type": "string"}, "all": {"type": "boolean"}}},
           builder=_git_commit),
    OpTool("git.push", "git", "推送到远程（force 为危险操作）", {
        "type": "object", "properties": {
            "remote": {"type": "string"}, "branch": {"type": "string"},
            "force": {"type": "boolean"}, "tags": {"type": "boolean"}}},
           dangerous=True, builder=_git_push),
    OpTool("git.pull", "git", "拉取远程", {
        "type": "object", "properties": {
            "remote": {"type": "string"}, "branch": {"type": "string"},
            "rebase": {"type": "boolean"}}},
           builder=lambda a: (["git", "pull"] + ([a["remote"]] if a.get("remote") else []) +
                              ([a["branch"]] if a.get("branch") else []) +
                              (["--rebase"] if a.get("rebase") else []))),
    OpTool("git.clone", "git", "克隆仓库", {
        "type": "object", "properties": {
            "url": {"type": "string"}, "dest": {"type": "string"}}},
           builder=lambda a: ["git", "clone", a.get("url", "")] + ([a["dest"]] if a.get("dest") else [])),
    OpTool("git.reset", "git", "重置（--hard 为危险操作）", {
        "type": "object", "properties": {
            "target": {"type": "string"}, "hard": {"type": "boolean"}}},
           dangerous=True, builder=_git_reset),
    OpTool("git.branch", "git", "列出/创建分支", {
        "type": "object", "properties": {
            "name": {"type": "string"}, "delete": {"type": "boolean"}}},
           dangerous=True,
           builder=lambda a: (["git", "branch", "-D", a["name"]] if a.get("delete")
                              else (["git", "branch", a["name"]] if a.get("name") else ["git", "branch", "-a"]))),
    # ---------------- Docker ----------------
    OpTool("docker.ps", "docker", "列出容器", {
        "type": "object", "properties": {"all": {"type": "boolean"}}},
           builder=lambda a: ["docker", "ps", "-a"] if a.get("all") else ["docker", "ps"]),
    OpTool("docker.images", "docker", "列出镜像", {
        "type": "object", "properties": {}},
           builder=lambda a: ["docker", "images"]),
    OpTool("docker.build", "docker", "构建镜像", {
        "type": "object", "properties": {
            "tag": {"type": "string"}, "path": {"type": "string"}}},
           builder=lambda a: ["docker", "build", "-t", a.get("tag", "app:latest"), a.get("path", ".")]),
    OpTool("docker.run", "docker", "运行容器", {
        "type": "object", "properties": {
            "image": {"type": "string"}, "command": {"type": "string"},
            "detach": {"type": "boolean"}, "rm": {"type": "boolean"},
            "ports": {"type": "array"}, "name": {"type": "string"}}},
           builder=_docker_run),
    OpTool("docker.stop", "docker", "停止容器", {
        "type": "object", "properties": {"container": {"type": "string"}}},
           builder=lambda a: ["docker", "stop", a.get("container", "")]),
    OpTool("docker.rm", "docker", "删除容器（force 为危险操作）", {
        "type": "object", "properties": {
            "container": {"type": "string"}, "force": {"type": "boolean"},
            "volumes": {"type": "boolean"}}},
           dangerous=True, builder=_docker_rm),
    # ---------------- NPM ----------------
    OpTool("npm.install", "npm", "安装依赖", {
        "type": "object", "properties": {
            "packages": {"type": "array"}, "dev": {"type": "boolean"}}},
           builder=lambda a: ["npm", "install"] + (["--save-dev"] if a.get("dev") else []) + a.get("packages", [])),
    OpTool("npm.run", "npm", "运行脚本", {
        "type": "object", "properties": {"script": {"type": "string"}}},
           builder=lambda a: ["npm", "run", a.get("script", "")]),
    OpTool("npm.publish", "npm", "发布包（危险操作）", {
        "type": "object", "properties": {
            "tag": {"type": "string"}, "access": {"type": "string"}}},
           dangerous=True, builder=_npm_publish),
    # ---------------- Pip ----------------
    OpTool("pip.install", "pip", "安装 Python 包", {
        "type": "object", "properties": {
            "packages": {"type": "array"}, "user": {"type": "boolean"},
            "upgrade": {"type": "boolean"}}},
           builder=_pip_install),
    OpTool("pip.uninstall", "pip", "卸载 Python 包（危险操作）", {
        "type": "object", "properties": {"packages": {"type": "array"}}},
           dangerous=True, builder=_pip_uninstall),
    # ---------------- SSH ----------------
    OpTool("ssh.exec", "ssh", "远程执行命令（危险操作）", {
        "type": "object", "properties": {
            "host": {"type": "string"}, "command": {"type": "string"},
            "port": {"type": "integer"}}},
           dangerous=True, builder=_ssh_exec),
    OpTool("ssh.tunnel", "ssh", "建立端口转发", {
        "type": "object", "properties": {
            "host": {"type": "string"}, "local": {"type": "string"},
            "remote": {"type": "string"}}},
           builder=lambda a: ["ssh", "-L",
                              f"{a.get('local','')}:{a.get('remote','')}", a.get("host", "")]),
]


def list_ops_tools() -> List[OpTool]:
    return OPS_TOOLS


def _default_confirm(description: str) -> bool:
    """无 UI 时的默认确认：打印并拒绝所有危险操作（安全兜底）。"""
    print(f"{_log_prefix} [需确认] {description} —— 默认拒绝（请接入 UI 确认）")
    return False


def invoke_ops_tool(name: str, args: Dict[str, Any],
                    confirm_cb: Optional[Callable[[str], bool]] = None,
                    cwd: Optional[str] = None) -> Dict[str, Any]:
    """
    执行一个运维工具。

    :param confirm_cb: (description:str)->bool，危险操作二次确认。为 None 时用
                       _default_confirm（拒绝危险操作）。
    :param cwd: 工作目录（git/docker 等命令的上下文）。
    """
    tool = next((t for t in OPS_TOOLS if t.name == name), None)
    if tool is None:
        return {"success": False, "output": f"未知运维工具: {name}"}
    try:
        argv = tool.builder(args or {})
        if not argv:
            return {"success": False, "output": "命令构造为空"}
        if tool.dangerous:
            desc = f"{tool.name}  →  {' '.join(shlex.quote(x) for x in argv)}"
            ok = (confirm_cb or _default_confirm)(desc)
            if not ok:
                return {"success": False, "output": f"用户取消危险操作: {tool.name}"}
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                              timeout=300, shell=False)
        out = proc.stdout or ""
        if proc.stderr:
            out += ("\n[stderr]\n" + proc.stderr)
        if proc.returncode != 0:
            return {"success": False, "output": out or f"退出码 {proc.returncode}"}
        return {"success": True, "output": out or "(无输出)"}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": f"{tool.name} 超时(300s)"}
    except Exception as e:
        return {"success": False, "output": f"{tool.name} 异常: {e}\n{traceback.format_exc()}"}


# ------------------------------------------------------- 注册进路由表 --------
def register_ops_tools(confirm_cb: Optional[Callable[[str], bool]] = None,
                       registry=None) -> int:
    """
    把全部运维工具注册进 UniversalSkillRouter 的全局注册表，使其可被模型/UI 调用。

    :param confirm_cb: 危险操作确认回调（来自 main_window 的 Qt 确认框）。
    :param registry: 传入 SkillsRegistry 实例；默认用 get_skills_registry()。
    :return: 注册成功的工具数。
    """
    try:
        from core.skills_registry import SkillDef, get_skills_registry
    except Exception as e:
        print(f"{_log_prefix} 无法导入 SkillsRegistry: {e}")
        return 0

    reg = registry or get_skills_registry()
    # 闭包捕获 confirm_cb
    _confirm = confirm_cb

    def _make_handler(tool: OpTool):
        def _handler(args: Dict[str, Any]) -> Dict[str, Any]:
            return invoke_ops_tool(tool.name, args, confirm_cb=_confirm)
        return _handler

    count = 0
    for tool in OPS_TOOLS:
        try:
            sd = SkillDef(
                name=tool.name,
                description=tool.description + (" [危险操作需确认]" if tool.dangerous else ""),
                parameters=tool.params,
                handler=_make_handler(tool),
                category=f"ops.{tool.category}",
                requires_confirm=tool.dangerous,
                timeout=300,
            )
            reg.register(sd)
            count += 1
        except Exception as e:
            print(f"{_log_prefix} 注册 {tool.name} 失败: {e}")
    print(f"{_log_prefix} 已注册 {count} 个运维工具到 SkillsRegistry")
    return count


if __name__ == "__main__":
    # 独立验证（无需 PyQt）：执行一个非危险 git status
    r = invoke_ops_tool("git.status", {})
    print("git.status =>", json.dumps(r, ensure_ascii=False)[:200])
    # 危险操作默认应被拒绝
    r2 = invoke_ops_tool("git.push", {"force": True})
    print("git.push(force) =>", r2["success"], r2["output"][:60])
