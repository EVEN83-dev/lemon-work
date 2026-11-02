from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class MCPToolSchema:
    name: str
    description: str
    inputSchema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPToolCall:
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPToolResult:
    content: List[Dict[str, Any]] = field(default_factory=list)
    isError: bool = False


@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: List[str] = field(default_factory=list)
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class MCPInitializeParams:
    protocolVersion: str = "2024-11-05"
    capabilities: Dict[str, Any] = field(default_factory=dict)
    clientInfo: Dict[str, str] = field(default_factory=lambda: {"name": "lemon-agent", "version": "1.0.0"})


@dataclass
class MCPListToolsResult:
    tools: List[MCPToolSchema] = field(default_factory=list)
