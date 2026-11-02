# -*- coding: utf-8 -*-
"""
AgentRegistry — 本地已装 Agent 扫描与注册（夺舍模式基础设施）
================================================================

★ v4.1.8: 夺舍模式基础设施
- 不修改任何外部 Agent 的开源/闭源代码
- 扫描本机已装 Agent（exe / npm 全局包 / pipx 包）
- 注册到统一注册表，供 Host Agent 模式选择

扫描策略（按优先级）：
1. 已知路径（MiMo Code 在 lemon_agent/bin/mimo.exe）
2. 全局可执行文件（PATH 中的 <name>.exe）
3. npm 全局包（npm root -g 输出解析）
4. pipx 包（pipx list 解析）
5. 用户自定义路径（~/.lemon_agent/agents.json）

设计原则：
- 纯静态数据 + 轻量扫描（约 1-2s 完成）
- 扫描结果缓存到 ~/.lemon_agent/agent_registry.json
- 失败不致命：任何 Agent 扫不到，进程继续；只是从列表中缺失
"""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Dict, Any


# ============================================================
# Agent 描述符
# ============================================================

@dataclass
class AgentDescriptor:
    """单个 Agent 的描述符

    Attributes:
        id: 唯一标识（如 "mimo_code" / "claude_code" / "aider"）
        display_name: 中文显示名
        brand_name: 英文品牌名（刻在 Host Agent 功能栏）
        executable: 可执行文件路径（绝对或 PATH 名）
        launcher: 启动方式 "acp" / "stdio" / "cli"
        args: 启动参数列表（如 ["acp", "--print-logs"]）
        protocol: 通信协议 "acp" / "jsonrpc" / "plain"
        license: "MIT" / "Apache-2.0" / "Proprietary" / "..."
        homepage: 项目主页
        detection_paths: 额外检测路径列表（覆盖默认扫描）
        installed: 是否本机已检测到
        install_hint: 未安装时的安装提示
    """
    id: str
    display_name: str
    brand_name: str
    executable: str = ""
    launcher: str = "cli"  # acp / stdio / cli
    args: List[str] = field(default_factory=list)
    protocol: str = "plain"  # acp / jsonrpc / plain
    license: str = "Unknown"
    homepage: str = ""
    detection_paths: List[str] = field(default_factory=list)
    installed: bool = False
    install_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# 内置 Agent 知识库（不依赖网络）
# ============================================================

BUILTIN_AGENTS: List[AgentDescriptor] = [
    AgentDescriptor(
        id="mimo_code",
        display_name="MiMo Code",
        brand_name="MiMo Code",
        executable="mimo.exe",
        launcher="acp",
        args=["acp", "--print-logs"],
        protocol="acp",
        license="MIT",
        homepage="https://github.com/XiaomiMiMo/MiMo-Code",
        detection_paths=[
            # ★ 优先 lemon_agent 内置 MiMo
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bin", "mimo.exe"),
            # 小米官方安装路径
            os.path.expanduser(r"~\AppData\Local\Programs\@mimo-ai\mimocode-windows-x64\bin\mimo.exe"),
        ],
        install_hint="从 https://mimo.xiaomi.com/coder 下载或执行 pip install mimocode",
    ),
    AgentDescriptor(
        id="claude_code",
        display_name="Claude Code",
        brand_name="Claude Code",
        executable="claude",
        launcher="stdio",
        args=[],
        protocol="plain",
        license="Proprietary",
        homepage="https://www.anthropic.com/claude-code",
        detection_paths=[
            os.path.expanduser(r"~\AppData\Roaming\npm\claude.cmd"),
            os.path.expanduser(r"~\.local\bin\claude"),
        ],
        install_hint="npm install -g @anthropic-ai/claude-code",
    ),
    AgentDescriptor(
        id="openai_codex_cli",
        display_name="OpenAI Codex CLI",
        brand_name="Codex CLI",
        executable="codex",
        launcher="stdio",
        args=[],
        protocol="plain",
        license="Apache-2.0",
        homepage="https://github.com/openai/codex",
        detection_paths=[
            os.path.expanduser(r"~\AppData\Roaming\npm\codex.cmd"),
        ],
        install_hint="npm install -g @openai/codex",
    ),
    AgentDescriptor(
        id="aider",
        display_name="Aider",
        brand_name="Aider",
        executable="aider",
        launcher="stdio",
        args=[],
        protocol="plain",
        license="Apache-2.0",
        homepage="https://aider.chat",
        detection_paths=[
            os.path.expanduser(r"~\.local\bin\aider"),
        ],
        install_hint="pipx install aider-chat",
    ),
    AgentDescriptor(
        id="opencode",
        display_name="OpenCode",
        brand_name="OpenCode",
        executable="opencode",
        launcher="stdio",
        args=[],
        protocol="plain",
        license="MIT",
        homepage="https://opencode.ai",
        detection_paths=[
            os.path.expanduser(r"~\AppData\Roaming\npm\opencode.cmd"),
        ],
        install_hint="npm install -g opencode-ai",
    ),
    AgentDescriptor(
        id="cline",
        display_name="Cline",
        brand_name="Cline",
        executable="cline",
        launcher="stdio",
        args=[],
        protocol="plain",
        license="Apache-2.0",
        homepage="https://cline.bot",
        detection_paths=[
            os.path.expanduser(r"~\AppData\Roaming\npm\cline.cmd"),
        ],
        install_hint="npm install -g cline",
    ),
    AgentDescriptor(
        id="qwen_code",
        display_name="Qwen Code",
        brand_name="Qwen Code",
        executable="qwen",
        launcher="stdio",
        args=[],
        protocol="plain",
        license="Apache-2.0",
        homepage="https://github.com/QwenLM/qwen-code",
        detection_paths=[
            os.path.expanduser(r"~\AppData\Roaming\npm\qwen.cmd"),
        ],
        install_hint="npm install -g @qwen-code/qwen-code@latest",
    ),
    AgentDescriptor(
        id="continue_cli",
        display_name="Continue CLI",
        brand_name="Continue",
        executable="cn",
        launcher="stdio",
        args=[],
        protocol="plain",
        license="Apache-2.0",
        homepage="https://continue.dev",
        detection_paths=[
            os.path.expanduser(r"~\AppData\Roaming\npm\cn.cmd"),
        ],
        install_hint="npm install -g @continuedev/cli",
    ),
    AgentDescriptor(
        id="goose",
        display_name="Goose",
        brand_name="Goose",
        executable="goose",
        launcher="stdio",
        args=[],
        protocol="plain",
        license="Apache-2.0",
        homepage="https://block.github.io/goose",
        detection_paths=[
            os.path.expanduser(r"~\.local\bin\goose"),
        ],
        install_hint="curl -fsSL https://goose-docs.ai/install.sh | bash",
    ),
    AgentDescriptor(
        id="openhands",
        display_name="OpenHands",
        brand_name="OpenHands",
        executable="openhands",
        launcher="stdio",
        args=[],
        protocol="plain",
        license="MIT",
        homepage="https://github.com/All-Hands-AI/OpenHands",
        detection_paths=[],
        install_hint="pipx install openhands 或 uvx openhands",
    ),
]


# ============================================================
# Agent Registry
# ============================================================

class AgentRegistry:
    """本地 Agent 注册表 — 扫描 + 缓存 + 查询

    用法：
        reg = AgentRegistry()
        reg.scan()                           # 扫描本机（约 1s）
        installed = reg.get_installed()      # 拿到所有已装的 Agent
        agent = reg.find("mimo_code")        # 按 id 查单个
    """

    CACHE_FILE = os.path.join(
        os.path.expanduser("~"), ".lemon_agent", "agent_registry.json"
    )

    def __init__(self):
        self._agents: Dict[str, AgentDescriptor] = {
            a.id: a for a in BUILTIN_AGENTS
        }

    # --------------------------------------------------------
    # 扫描
    # --------------------------------------------------------

    def scan(self) -> List[AgentDescriptor]:
        """扫描本机已装 Agent，更新 installed 字段

        Returns:
            所有已装 Agent 列表（AgentDescriptor.installed == True）
        """
        for agent in self._agents.values():
            agent.installed = self._detect(agent)
        installed = self.get_installed()
        self._save_cache()
        return installed

    def _detect(self, agent: AgentDescriptor) -> bool:
        """检测单个 Agent 是否已装"""
        # 1. 先查 detection_paths
        for p in agent.detection_paths:
            if p and os.path.isfile(p):
                agent.executable = p
                return True

        # 2. 在 PATH 中查找
        which_path = shutil.which(agent.executable)
        if which_path:
            agent.executable = which_path
            return True

        # 3. Windows 上额外检查 .cmd / .bat（npm 全局包常见）
        if sys.platform == "win32":
            for ext in (".cmd", ".bat", ".exe"):
                base, _ = os.path.splitext(agent.executable)
                candidate = shutil.which(base + ext)
                if candidate:
                    agent.executable = candidate
                    return True

        # 4. 检查 npm 全局包（仅当 executable 是 npm 包名）
        if agent.executable in ("claude", "codex", "opencode", "cline", "qwen", "cn"):
            npm_path = self._resolve_npm_global(agent.executable)
            if npm_path:
                agent.executable = npm_path
                return True

        # 5. 检查 pipx 包
        pipx_path = self._resolve_pipx(agent.executable)
        if pipx_path:
            agent.executable = pipx_path
            return True

        return False

    def _resolve_npm_global(self, name: str) -> Optional[str]:
        """从 npm root -g 输出解析 <name>.cmd 路径"""
        try:
            out = subprocess.run(
                ["npm", "root", "-g"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode != 0:
                return None
            root = out.stdout.strip()
            # npm 全局包 bin 在 <root>/../bin/<name>.cmd
            bin_dir = os.path.join(os.path.dirname(root), "bin")
            for ext in (".cmd", ".bat", ".exe", ""):
                candidate = os.path.join(bin_dir, name + ext)
                if os.path.isfile(candidate):
                    return candidate
        except Exception:
            return None
        return None

    def _resolve_pipx(self, name: str) -> Optional[str]:
        """从 pipx list 输出解析可执行路径"""
        try:
            out = subprocess.run(
                ["pipx", "list", "--short"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode != 0:
                return None
            # 解析 pipx list --short 输出，匹配 "package name"
            for line in out.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == name:
                    # pipx 安装目录 <pipx_root>/venvs/<name>/bin/<name>(.exe)
                    pipx_root = os.environ.get("PIPX_HOME") or os.path.expanduser("~/.local/pipx")
                    for ext in (".exe", ""):
                        candidate = os.path.join(pipx_root, "venvs", name, "bin", name + ext)
                        if os.path.isfile(candidate):
                            return candidate
        except Exception:
            return None
        return None

    # --------------------------------------------------------
    # 查询
    # --------------------------------------------------------

    def get_all(self) -> List[AgentDescriptor]:
        return list(self._agents.values())

    def get_installed(self) -> List[AgentDescriptor]:
        return [a for a in self._agents.values() if a.installed]

    def find(self, agent_id: str) -> Optional[AgentDescriptor]:
        return self._agents.get(agent_id)

    def register_user_agent(self, agent: AgentDescriptor) -> None:
        """注册用户自定义 Agent（来自 ~/.lemon_agent/agents.json）"""
        self._agents[agent.id] = agent

    # --------------------------------------------------------
    # 缓存
    # --------------------------------------------------------

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            data = {a.id: a.to_dict() for a in self._agents.values()}
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_cache(self) -> bool:
        if not os.path.isfile(self.CACHE_FILE):
            return False
        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for agent_id, agent_data in data.items():
                if agent_id in self._agents:
                    # 只更新 installed 和 executable，不覆盖知识库元信息
                    self._agents[agent_id].installed = bool(agent_data.get("installed", False))
                    if agent_data.get("executable"):
                        self._agents[agent_id].executable = agent_data["executable"]
            return True
        except Exception:
            return False


# ============================================================
# 单例
# ============================================================

_registry: Optional[AgentRegistry] = None


def get_agent_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
        _registry.load_cache()
    return _registry


# ============================================================
# CLI 入口（手动调试用）
# ============================================================

if __name__ == "__main__":
    reg = get_agent_registry()
    print("Scanning local agents...")
    installed = reg.scan()
    print(f"\n✓ Found {len(installed)} installed agents:")
    for a in installed:
        print(f"  - {a.brand_name:20s} {a.license:15s} {a.executable}")
    print(f"\n✗ {len(reg.get_all()) - len(installed)} not installed (see install_hint):")
    for a in reg.get_all():
        if not a.installed:
            print(f"  - {a.brand_name:20s} {a.install_hint}")