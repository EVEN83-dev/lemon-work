import logging
from typing import Dict, Any, List, Optional, Tuple

from .mcp_types import MCPToolSchema, MCPToolResult
from .mcp_client import MCPServerManager

logger = logging.getLogger(__name__)


class MCPToolAdapter:
    def __init__(self, manager: Optional[MCPServerManager] = None):
        self._manager = manager or MCPServerManager()

    def list_tools(self) -> List[Dict[str, Any]]:
        result = []
        try:
            all_tools = self._manager.list_all_tools()
            for server_name, mcp_tool in all_tools:
                result.append({
                    "name": mcp_tool.name,
                    "description": mcp_tool.description,
                    "inputSchema": mcp_tool.inputSchema,
                    "server_name": server_name,
                })
        except Exception as e:
            logger.warning("[MCPToolAdapter] list_tools failed: %s", e)
        return result

    def invoke_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            all_tools = self._manager.list_all_tools()
            target_server = None
            for server_name, mcp_tool in all_tools:
                if mcp_tool.name == name:
                    target_server = server_name
                    break
            if target_server is None:
                return {"success": False, "error": f"Tool not found: {name}"}
            result = self._manager.call_tool(target_server, name, args)
            if result.isError:
                error_text = ""
                for c in result.content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        error_text += c.get("text", "")
                return {"success": False, "error": error_text or "MCP tool error"}
            output_text = ""
            for c in result.content:
                if isinstance(c, dict) and c.get("type") == "text":
                    output_text += c.get("text", "")
            return {"success": True, "output": output_text, "data": {"mcp_server": target_server, "mcp_tool": name}}
        except Exception as e:
            logger.warning("[MCPToolAdapter] invoke_tool failed: %s", e)
            return {"success": False, "error": str(e)}

    @staticmethod
    def convert_to_tool_def(mcp_tool_schema: MCPToolSchema, server_name: str = "") -> Dict[str, Any]:
        tool_id = f"mcp_{server_name}_{mcp_tool_schema.name}" if server_name else f"mcp_{mcp_tool_schema.name}"
        return {
            "id": tool_id,
            "name": mcp_tool_schema.name,
            "description": mcp_tool_schema.description,
            "parameters": mcp_tool_schema.inputSchema,
            "category": "mcp",
            "enabled": True,
            "requires_confirm": False,
            "timeout": 30,
        }

    def to_tool_def(self, server_name: str, mcp_tool: MCPToolSchema) -> Dict[str, Any]:
        tool_id = f"mcp_{server_name}_{mcp_tool.name}"
        mgr = self._manager

        def _execute(args: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
            result = mgr.call_tool(server_name, mcp_tool.name, args)
            if result.isError:
                error_text = ""
                for c in result.content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        error_text += c.get("text", "")
                return {"success": False, "error": error_text or "MCP tool error"}
            output_text = ""
            for c in result.content:
                if isinstance(c, dict) and c.get("type") == "text":
                    output_text += c.get("text", "")
            return {"success": True, "output": output_text, "data": {"mcp_server": server_name, "mcp_tool": mcp_tool.name}}

        return {
            "id": tool_id,
            "description": mcp_tool.description,
            "parameters": mcp_tool.inputSchema,
            "category": "mcp",
            "enabled": True,
            "requires_confirm": False,
            "timeout": 30,
            "execute": _execute,
        }

    def adapt_all(self) -> List[Dict[str, Any]]:
        result = []
        all_tools = self._manager.list_all_tools()
        for server_name, mcp_tool in all_tools:
            try:
                tool_def = self.to_tool_def(server_name, mcp_tool)
                result.append(tool_def)
            except Exception:
                pass
        return result
