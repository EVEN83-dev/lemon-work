# -*- coding: utf-8 -*-
"""
V6-P2 · MCP 双向接线 — 客户端一级工具源网关 (shared/mcp_gateway.py)
================================================================
把 bridge/mcp 既有 MCPClient + MCPServerManager "提升复用" 到 shared/
（一级公民，可被 EngineManager 直接调用）。bridge/ 旧文件保留不动。

对外承诺：
  - 工具命名空间：mcp__<server名>__<工具名>（防与本地 23 个业务技能撞名；撞名时本地优先 + WARN）
  - 配置驱动：运行时读取 data/mcp_servers.json，禁止任何 server 地址硬编码
  - 健康探测：online / offline / not_configured 三态；离线 server 工具不注入
  - 失败显式：success:false + 含 server 名与原始错误
  - 安全：MCP 工具 requires_confirm 可由调用方传入（沿用 _HIGH_RISK_TOOLS 惯例）

EngineManager 接入：默认 mcp_enabled=False（行为零变化）；True 时合并进工具菜单。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 项目根目录（shared/ 上一级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 默认配置文件路径（运行时读取，可覆盖）
DEFAULT_MCP_SERVERS_CONFIG = os.path.join(_PROJECT_ROOT, "data", "mcp_servers.json")


def _load_bridge_mcp() -> Tuple[Any, Any, Any]:
    """惰性加载 bridge/mcp 既有实现；返回 (MCPServerConfig, MCPClient, MCPServerManager)。
    若 bridge 路径不可用，向上抛 ImportError 由调用方处理。
    """
    # 把项目根加入 sys.path（bridge 是平级包）
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    from bridge.mcp.mcp_types import MCPServerConfig
    from bridge.mcp.mcp_client import MCPClient, MCPServerManager
    return MCPServerConfig, MCPClient, MCPServerManager


class MCPGateway:
    """客户端 MCP 网关 — EngineManager 的一级工具源。"""

    def __init__(
        self,
        config_path: Optional[str] = None,
        high_risk_tools: Optional[Set[str]] = None,
        auto_connect: bool = True,
    ):
        self._config_path = config_path or DEFAULT_MCP_SERVERS_CONFIG
        self._high_risk = high_risk_tools or set()
        self._MCPServerConfig, self._MCPClient, self._MCPServerManager = _load_bridge_mcp()

        self._manager: Optional[Any] = None  # MCPServerManager（refresh 时惰性构造）
        self._health: Dict[str, str] = {}    # server → online|offline|not_configured
        self._local_tool_names: Set[str] = set()  # 当前本地注册表技能名（用于撞名检测）
        self._tools_cache: List[Dict] = []        # 上次 list_tool_defs 结果缓存
        self._last_refresh: float = 0.0

    # ------------------------------------------------------------------ 配置读取
    def _read_config(self) -> List[Dict]:
        """运行时读取 data/mcp_servers.json — 字段 name/command/args/env/enabled/timeout。
        文件不存在或解析失败返回空（不崩溃）。
        """
        if not os.path.exists(self._config_path):
            logger.info("[MCP] 配置文件不存在: %s（跳过 MCP 工具注入）", self._config_path)
            return []
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("[MCP] 配置文件读取失败: %s: %s", self._config_path, e)
            return []
        if not isinstance(data, list):
            logger.warning("[MCP] 配置根应为 JSON 数组，实际=%s，跳过", type(data).__name__)
            return []
        valid: List[Dict] = []
        for idx, entry in enumerate(data):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                logger.warning("[MCP] 第 %d 项缺 name 字段，跳过", idx)
                continue
            if not entry.get("enabled", True):
                logger.info("[MCP] server %s 已禁用（enabled=false），跳过", name)
                continue
            entry.setdefault("command", "")
            entry.setdefault("args", [])
            entry.setdefault("env", {})
            entry.setdefault("transport", "stdio")
            entry.setdefault("timeout", 30)
            valid.append(entry)
        return valid

    # ------------------------------------------------------------------ 连接管理
    def refresh(self) -> Dict[str, str]:
        """重新加载配置 + 连接 + 发现工具。返回 {server: health}。"""
        cfg_list = self._read_config()
        self._manager = self._MCPServerManager()
        self._health = {}
        discovered_count = 0
        for cfg in cfg_list:
            name = cfg["name"]
            transport = cfg.get("transport", "stdio")
            try:
                server_cfg = self._MCPServerConfig(
                    name=name,
                    transport=transport,
                    command=cfg.get("command", ""),
                    args=cfg.get("args", []),
                    url=cfg.get("url", ""),
                    headers=cfg.get("headers", {}),
                    env=cfg.get("env", {}),
                    enabled=True,
                )
                if not self._manager.add_server(server_cfg):
                    logger.warning("[MCP] server %s 重复注册，跳过", name)
                    self._health[name] = "duplicate"
                    continue
                client = self._manager.get_server(name)
                if client is None:
                    self._health[name] = "not_configured"
                    continue
                if client.connect():
                    tool_count = len(client.get_tools() or [])
                    self._health[name] = "online"
                    discovered_count += tool_count
                    logger.info("[MCP] server %s online → %d 个工具", name, tool_count)
                else:
                    self._health[name] = "offline"
                    logger.warning("[MCP] server %s 连接失败 → offline", name)
            except Exception as e:
                self._health[name] = "offline"
                logger.warning("[MCP] server %s 异常: %s", name, e)
        self._last_refresh = time.time()
        logger.info("[MCP] 健康探测完成: %d server / 发现 %d 个工具 → %s",
                     len(cfg_list), discovered_count, self._health)
        return dict(self._health)

    # ------------------------------------------------------------------ 工具发现
    def set_local_tool_names(self, names: Set[str]) -> None:
        """注入本地注册表技能名，用于撞名检测。"""
        self._local_tool_names = set(names or [])

    def list_tool_defs(self) -> List[Dict]:
        """返回 MCP 工具列表（OpenAI function-calling 兼容格式 + mcp 路由元数据）。

        命名空间：mcp__<server名>__<工具名>。撞名（本地工具同名）跳过 + WARN。
        仅 online server 的工具注入。
        """
        if self._manager is None:
            self.refresh()
        result: List[Dict] = []
        seen_names: Set[str] = set()
        try:
            all_tools = self._manager.list_all_tools() if self._manager else []
        except Exception as e:
            logger.warning("[MCP] list_all_tools 失败: %s", e)
            all_tools = []

        for server_name, mcp_tool in all_tools:
            raw_name = mcp_tool.name
            namespaced = f"mcp__{server_name}__{raw_name}"

            # 撞名检测：本地优先
            if raw_name in self._local_tool_names:
                logger.warning(
                    "[MCP] 撞名: server=%s 工具=%s 与本地技能同名 → 跳过注入（本地优先）",
                    server_name, raw_name,
                )
                continue
            if namespaced in seen_names:
                logger.warning("[MCP] 命名重复: %s → 跳过", namespaced)
                continue
            seen_names.add(namespaced)

            # 安全：是否在 high_risk 列表 → requires_confirm
            requires_confirm = namespaced in self._high_risk or raw_name in self._high_risk

            result.append({
                "id": namespaced,
                "name": namespaced,
                "description": f"[MCP:{server_name}] {mcp_tool.description}",
                "parameters": mcp_tool.inputSchema if isinstance(mcp_tool.inputSchema, dict) else {"type": "object", "properties": {}},
                "category": "mcp",
                "enabled": True,
                "requires_confirm": requires_confirm,
                "timeout": 30,
                # ---- 路由元数据（供 EngineManager 反解析）----
                "_mcp_route": {"server": server_name, "tool": raw_name},
            })
        self._tools_cache = result
        return result

    # ------------------------------------------------------------------ 执行路由
    @staticmethod
    def parse_route(namespaced_name: str) -> Optional[Tuple[str, str]]:
        """反解析命名空间 → (server_name, tool_name)。非 mcp__ 前缀返回 None。"""
        if not namespaced_name.startswith("mcp__"):
            return None
        rest = namespaced_name[5:]
        if "__" not in rest:
            return None
        sep = rest.index("__")
        server = rest[:sep]
        tool = rest[sep + 2:]
        if not server or not tool:
            return None
        return server, tool

    def call_tool(self, namespaced_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行 MCP 工具；返回 {"success": bool, "output"/"error": str, "data": {...}}。

        失败时显式 success:false，error 含 server 名与原始错误（铁律 #4 真实现）。
        """
        route = self.parse_route(namespaced_name)
        if route is None:
            return {"success": False, "error": f"非法 MCP 命名空间: {namespaced_name}",
                    "data": {"namespaced": namespaced_name}}
        server_name, tool_name = route
        if self._manager is None:
            return {"success": False, "error": "MCP gateway 未初始化",
                    "data": {"server": server_name, "tool": tool_name}}

        # 三态判定
        health = self._health.get(server_name, "not_configured")
        if health == "not_configured":
            return {"success": False,
                    "error": f"MCP server '{server_name}' 未配置",
                    "data": {"server": server_name, "tool": tool_name}}
        if health == "offline":
            return {"success": False,
                    "error": f"MCP server '{server_name}' 离线（连接失败）",
                    "data": {"server": server_name, "tool": tool_name}}

        client = self._manager.get_server(server_name)
        if client is None:
            return {"success": False,
                    "error": f"MCP server '{server_name}' 客户端不存在",
                    "data": {"server": server_name, "tool": tool_name}}

        if not client.is_connected():
            return {"success": False,
                    "error": f"MCP server '{server_name}' 已断开",
                    "data": {"server": server_name, "tool": tool_name}}

        try:
            result = client.call_tool(tool_name, arguments)
        except Exception as e:
            logger.warning("[MCP] call_tool 异常: server=%s tool=%s → %s", server_name, tool_name, e)
            return {"success": False,
                    "error": f"执行异常: {e}",
                    "data": {"server": server_name, "tool": tool_name}}

        if result.isError:
            err_text = ""
            for c in result.content:
                if isinstance(c, dict) and c.get("type") == "text":
                    err_text += c.get("text", "")
            return {"success": False,
                    "error": err_text or "MCP tool error",
                    "data": {"server": server_name, "tool": tool_name}}

        output_text = ""
        for c in result.content:
            if isinstance(c, dict) and c.get("type") == "text":
                output_text += c.get("text", "")
        return {"success": True,
                "output": output_text,
                "data": {"server": server_name, "tool": tool_name}}

    # ------------------------------------------------------------------ 状态
    def health_status(self) -> Dict[str, str]:
        """返回 {server: online|offline|not_configured|duplicate} 三态。"""
        return dict(self._health)

    def is_server_online(self, name: str) -> bool:
        return self._health.get(name) == "online"

    def namespaced_tool_count(self) -> int:
        return len(self._tools_cache)


# ---------------------------------------------------------------------- 便捷工厂
_gateway_singleton: Optional[MCPGateway] = None


def get_mcp_gateway(
    config_path: Optional[str] = None,
    high_risk_tools: Optional[Set[str]] = None,
    force_reload: bool = False,
) -> MCPGateway:
    """进程级 MCPGateway 单例。"""
    global _gateway_singleton
    if _gateway_singleton is None or force_reload:
        _gateway_singleton = MCPGateway(
            config_path=config_path,
            high_risk_tools=high_risk_tools,
            auto_connect=True,
        )
        try:
            _gateway_singleton.refresh()
        except Exception as e:
            logger.warning("[MCP] gateway 初始化 refresh 失败: %s", e)
    return _gateway_singleton
