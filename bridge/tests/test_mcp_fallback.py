import unittest
from unittest.mock import MagicMock, patch


class TestMCPFallbackLookup(unittest.TestCase):
    def setUp(self):
        from bridge.agent_loop import AgentLoop
        engine_mgr = MagicMock()
        self.agent_loop = AgentLoop(engine_manager=engine_mgr)

    @patch("bridge.mcp.mcp_tool_adapter.MCPToolAdapter.list_tools")
    def test_fallback_finds_tool(self, mock_list_tools):
        mock_list_tools.return_value = [
            {
                "name": "web_search",
                "description": "Search the web",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
                "server_name": "web",
            },
            {
                "name": "file_read",
                "description": "Read a file",
                "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
                "server_name": "fs",
            },
        ]
        result = self.agent_loop._mcp_fallback_lookup("web_search")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "web_search")
        self.assertEqual(result["category"], "mcp")

    @patch("bridge.mcp.mcp_tool_adapter.MCPToolAdapter.list_tools")
    def test_fallback_returns_none_when_not_found(self, mock_list_tools):
        mock_list_tools.return_value = [
            {
                "name": "file_read",
                "description": "Read a file",
                "inputSchema": {},
                "server_name": "fs",
            },
        ]
        result = self.agent_loop._mcp_fallback_lookup("nonexistent_tool")
        self.assertIsNone(result)

    @patch("bridge.mcp.mcp_tool_adapter.MCPToolAdapter.list_tools")
    def test_fallback_returns_none_on_exception(self, mock_list_tools):
        mock_list_tools.side_effect = Exception("MCP unavailable")
        result = self.agent_loop._mcp_fallback_lookup("any_tool")
        self.assertIsNone(result)

    @patch("bridge.mcp.mcp_tool_adapter.MCPToolAdapter.list_tools")
    def test_fallback_empty_tools_list(self, mock_list_tools):
        mock_list_tools.return_value = []
        result = self.agent_loop._mcp_fallback_lookup("web_search")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
