# -*- coding: utf-8 -*-
"""MCP (Model Context Protocol) server implementation"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from enum import Enum
import json
import time


class MCPMessageType(Enum):
    TOOL_CALL = 'tool_call'
    TOOL_RESULT = 'tool_result'
    RESOURCE_QUERY = 'resource_query'
    RESOURCE_RESULT = 'resource_result'
    PROMPT_REQUEST = 'prompt_request'
    PROMPT_RESULT = 'prompt_result'
    HEARTBEAT = 'heartbeat'
    ERROR = 'error'


@dataclass
class MCPTool:
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    handler: Optional[Callable] = None
    enabled: bool = True


@dataclass
class MCPResource:
    uri: str
    name: str
    description: str
    data: Any = None


@dataclass
class MCPPrompt:
    name: str
    description: str
    template: str
    variables: List[str] = field(default_factory=list)


class MCPServer:

    def __init__(self, server_name: str = 'lemon_agent', version: str = '1.0.0'):
        self.server_name = server_name
        self.version = version
        self._tools: Dict[str, MCPTool] = {}
        self._resources: Dict[str, MCPResource] = {}
        self._prompts: Dict[str, MCPPrompt] = {}
        self._message_history: List[Dict] = []
        self._capabilities: List[str] = ['tools', 'resources', 'prompts', 'streaming']
        self._register_builtin_tools()

    def _register_builtin_tools(self):
        for tool in [
            MCPTool('file_read', 'Read file content', {'path': 'string', 'start_line': 'int', 'end_line': 'int'}),
            MCPTool('file_write', 'Write file', {'path': 'string', 'content': 'string'}),
            MCPTool('file_search', 'Search files', {'pattern': 'string', 'path': 'string'}),
            MCPTool('code_execute', 'Execute code', {'language': 'string', 'code': 'string'}),
            MCPTool('terminal_command', 'Execute terminal command', {'command': 'string'}),
        ]:
            self.register_tool(tool)

    def register_tool(self, tool: MCPTool):
        self._tools[tool.name] = tool

    def register_resource(self, resource: MCPResource):
        self._resources[resource.uri] = resource

    def register_prompt(self, prompt: MCPPrompt):
        self._prompts[prompt.name] = prompt

    async def handle_message(self, message: Dict) -> Dict:
        msg_type = message.get('type', '')
        payload = message.get('payload', {})

        self._message_history.append({
            'timestamp': time.time(),
            'type': msg_type,
            'payload_size': len(json.dumps(payload)),
        })

        try:
            if msg_type == MCPMessageType.TOOL_CALL.value:
                return await self._handle_tool_call(payload)
            elif msg_type == MCPMessageType.RESOURCE_QUERY.value:
                return await self._handle_resource_query(payload)
            elif msg_type == MCPMessageType.PROMPT_REQUEST.value:
                return await self._handle_prompt_request(payload)
            elif msg_type == MCPMessageType.HEARTBEAT.value:
                return {'status': 'ok', 'timestamp': time.time()}
            else:
                return {'error': f'Unknown message type: {msg_type}'}
        except Exception as e:
            return {'error': str(e), 'type': MCPMessageType.ERROR.value}

    async def _handle_tool_call(self, payload: Dict) -> Dict:
        tool_name = payload.get('name', '')
        arguments = payload.get('arguments', {})
        tool = self._tools.get(tool_name)
        if tool is None:
            return {'error': f'Tool not found: {tool_name}'}
        if not tool.enabled:
            return {'error': f'Tool disabled: {tool_name}'}
        if tool.handler:
            result = await tool.handler(arguments)
            return {'result': result, 'tool': tool_name}
        return {'result': f'Tool {tool_name} executed (no custom handler)', 'tool': tool_name}

    async def _handle_resource_query(self, payload: Dict) -> Dict:
        uri = payload.get('uri', '')
        resource = self._resources.get(uri)
        if resource is None:
            return {'error': f'Resource not found: {uri}'}
        return {'resource': resource.data, 'uri': uri}

    async def _handle_prompt_request(self, payload: Dict) -> Dict:
        prompt_name = payload.get('name', '')
        variables = payload.get('variables', {})
        prompt = self._prompts.get(prompt_name)
        if prompt is None:
            return {'error': f'Prompt not found: {prompt_name}'}
        template = prompt.template
        for key, value in variables.items():
            template = template.replace(f'{{{{{key}}}}}', str(value))
        return {'prompt': template, 'name': prompt_name}

    def get_capabilities(self) -> Dict:
        return {
            'name': self.server_name,
            'version': self.version,
            'capabilities': self._capabilities,
            'tools': list(self._tools.keys()),
            'resources': list(self._resources.keys()),
            'prompts': list(self._prompts.keys()),
        }

    def get_stats(self) -> Dict:
        return {
            'total_messages': len(self._message_history),
            'tools_count': len(self._tools),
            'resources_count': len(self._resources),
            'prompts_count': len(self._prompts),
        }


_mcp_server: Optional[MCPServer] = None


def get_mcp_server() -> MCPServer:
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPServer()
    return _mcp_server
