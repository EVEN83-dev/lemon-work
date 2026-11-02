# -*- coding: utf-8 -*-
"""
AgentAdapter — 夺舍模式统一适配层
================================

★ v4.1.8: 夺舍模式基础设施
- 不修改任何外部 Agent 的开源/闭源代码（路线 A+B 混合）
- 把不同 Agent 的不同启动方式（ACP / stdio / CLI）抽象为统一接口
- 让 Host Agent 功能栏/选择对话框只跟适配器打交道

启动策略（每种 Agent 注册一个 Adapter）：
- ACP 适配器：spawn_stdio_transport(exe, "acp", ...) — 走 ACP 协议（MiMo Code）
- stdio 适配器：subprocess.Popen(exe, stdin=PIPE, stdout=PIPE) — 直接 stdio 通信
- CLI 适配器：subprocess.Popen(exe + args) — 命令行包装，仅支持单向输入

设计原则：
- 适配器是无状态的工厂，根据 AgentDescriptor 创建具体启动器
- 启动器返回 (process, reader, writer) — 与现有 ACPBridge 对齐
- 失败抛出明确异常，调用方捕获并提示
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple, Any

from core.agent_registry import AgentDescriptor, get_agent_registry


# ============================================================
# 启动结果（与 ACPBridge 接口对齐）
# ============================================================

@dataclass
class AgentProcess:
    """适配器启动后的进程句柄

    Attributes:
        process: subprocess.Popen 实例
        stdin: 标准输入流（None 表示不可写）
        stdout: 标准输出流（None 表示不可读）
        stderr: 标准错误流
        protocol: 实际使用的协议 "acp" / "stdio" / "cli"
        agent_id: AgentDescriptor.id
    """
    process: subprocess.Popen
    stdin: Any  # Optional[IO[bytes]]
    stdout: Any  # Optional[IO[bytes]]
    stderr: Any  # Optional[IO[bytes]]
    protocol: str
    agent_id: str

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def write(self, data: bytes) -> None:
        if self.stdin:
            try:
                self.stdin.write(data)
                self.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def kill(self) -> None:
        try:
            if self.process.poll() is None:
                self.process.kill()
        except Exception:
            pass


# ============================================================
# 适配器基类
# ============================================================

class BaseAdapter:
    """所有适配器的基类

    子类必须实现 launch() 方法，返回 AgentProcess
    """

    def __init__(self, descriptor: AgentDescriptor):
        self.descriptor = descriptor

    def launch(self, cwd: Optional[str] = None,
               env: Optional[dict] = None) -> AgentProcess:
        raise NotImplementedError

    def _prepare_env(self, extra: Optional[dict] = None) -> dict:
        """合并环境变量"""
        merged = os.environ.copy()
        if extra:
            merged.update(extra)
        return merged


# ============================================================
# ACP 适配器（用于 MiMo Code 等支持 ACP 的 Agent）
# ============================================================

class ACPAdapter(BaseAdapter):
    """通过 ACP 协议启动 Agent

    启动方式：spawn_stdio_transport(exe, "acp", "--print-logs", ...)
    """

    def launch(self, cwd: Optional[str] = None,
               env: Optional[dict] = None) -> AgentProcess:
        """启动 ACP 进程

        Returns:
            AgentProcess: 进程句柄，调用方负责后续 asyncio 协议握手

        Raises:
            FileNotFoundError: 可执行文件不存在
            RuntimeError: 进程启动失败
        """
        exe = self.descriptor.executable
        if not exe or not os.path.isfile(exe):
            raise FileNotFoundError(
                f"Agent {self.descriptor.brand_name} 可执行文件不存在: {exe}"
            )

        full_env = self._prepare_env(env)
        full_cwd = cwd or os.getcwd()

        try:
            proc = subprocess.Popen(
                [exe] + self.descriptor.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=full_cwd,
                env=full_env,
                bufsize=0,
            )
        except OSError as e:
            raise RuntimeError(
                f"启动 {self.descriptor.brand_name} 失败: {e}"
            ) from e

        return AgentProcess(
            process=proc,
            stdin=proc.stdin,
            stdout=proc.stdout,
            stderr=proc.stderr,
            protocol="acp",
            agent_id=self.descriptor.id,
        )


# ============================================================
# stdio 适配器（用于直接走 stdin/stdout 的 Agent）
# ============================================================

class StdioAdapter(BaseAdapter):
    """通过 stdio 与 Agent 通信

    启动方式：subprocess.Popen(exe, stdin=PIPE, stdout=PIPE)
    通信协议：plain（JSON 行 / 自定义格式，由调用方解析）
    """

    def launch(self, cwd: Optional[str] = None,
               env: Optional[dict] = None) -> AgentProcess:
        exe = self.descriptor.executable
        if not exe or not os.path.isfile(exe):
            # 尝试通过 PATH 找
            which = shutil.which(exe)
            if which:
                exe = which
                self.descriptor.executable = which
            else:
                raise FileNotFoundError(
                    f"Agent {self.descriptor.brand_name} 不在 PATH: {exe}"
                )

        full_env = self._prepare_env(env)
        full_cwd = cwd or os.getcwd()

        try:
            proc = subprocess.Popen(
                [exe] + self.descriptor.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=full_cwd,
                env=full_env,
                bufsize=0,
            )
        except OSError as e:
            raise RuntimeError(
                f"启动 {self.descriptor.brand_name} 失败: {e}"
            ) from e

        return AgentProcess(
            process=proc,
            stdin=proc.stdin,
            stdout=proc.stdout,
            stderr=proc.stderr,
            protocol="stdio",
            agent_id=self.descriptor.id,
        )


# ============================================================
# CLI 适配器（用于纯命令行 Agent，仅支持单向输入）
# ============================================================

class CLIAdapter(BaseAdapter):
    """以命令行方式启动 Agent

    启动方式：subprocess.Popen(exe, args, stdout=PIPE)
    通信协议：plain（只能向 stdin 写入，stdout 拦截读取）
    """

    def launch(self, cwd: Optional[str] = None,
               env: Optional[dict] = None) -> AgentProcess:
        exe = self.descriptor.executable
        if not exe or not os.path.isfile(exe):
            which = shutil.which(exe)
            if which:
                exe = which
                self.descriptor.executable = which
            else:
                raise FileNotFoundError(
                    f"Agent {self.descriptor.brand_name} 不在 PATH: {exe}"
                )

        full_env = self._prepare_env(env)
        full_cwd = cwd or os.getcwd()

        try:
            proc = subprocess.Popen(
                [exe] + self.descriptor.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # 合并到 stdout
                cwd=full_cwd,
                env=full_env,
                bufsize=0,
            )
        except OSError as e:
            raise RuntimeError(
                f"启动 {self.descriptor.brand_name} 失败: {e}"
            ) from e

        return AgentProcess(
            process=proc,
            stdin=proc.stdin,
            stdout=proc.stdout,
            stderr=proc.stderr,
            protocol="cli",
            agent_id=self.descriptor.id,
        )


# ============================================================
# 适配器工厂
# ============================================================

_ADAPTER_MAP = {
    "acp": ACPAdapter,
    "stdio": StdioAdapter,
    "cli": CLIAdapter,
}


def create_adapter(descriptor: AgentDescriptor) -> BaseAdapter:
    """根据 AgentDescriptor 创建对应的适配器"""
    launcher = descriptor.launcher or "cli"
    cls = _ADAPTER_MAP.get(launcher, CLIAdapter)
    return cls(descriptor)


def launch_agent(agent_id: str, cwd: Optional[str] = None,
                 env: Optional[dict] = None) -> AgentProcess:
    """便捷入口：按 agent_id 创建适配器并启动

    Args:
        agent_id: AgentDescriptor.id
        cwd: 工作目录
        env: 额外环境变量

    Returns:
        AgentProcess

    Raises:
        ValueError: agent_id 不存在或未安装
        FileNotFoundError: 可执行文件不存在
        RuntimeError: 启动失败
    """
    reg = get_agent_registry()
    descriptor = reg.find(agent_id)
    if descriptor is None:
        raise ValueError(f"未知 Agent: {agent_id}")
    if not descriptor.installed:
        # 再次扫描一次（可能在 UI 上刚扫描）
        reg.scan()
        if not descriptor.installed:
            raise ValueError(
                f"Agent {descriptor.brand_name} 未安装。"
                f"安装提示: {descriptor.install_hint}"
            )

    adapter = create_adapter(descriptor)
    return adapter.launch(cwd=cwd, env=env)


# ============================================================
# CLI 入口（手动调试用）
# ============================================================

if __name__ == "__main__":
    import json as _json

    reg = get_agent_registry()
    installed = reg.scan()
    print(f"已装 Agent: {len(installed)} 个")
    for a in installed:
        print(f"  - {a.brand_name} ({a.executable})")

    if installed:
        first = installed[0]
        print(f"\n试启动 {first.brand_name} ...")
        try:
            ap = launch_agent(first.id)
            print(f"  ✓ 进程已启动 PID={ap.process.pid}, protocol={ap.protocol}")
            ap.kill()
            print(f"  ✓ 已关闭")
        except Exception as e:
            print(f"  ✗ 启动失败: {e}")