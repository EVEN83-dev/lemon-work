# -*- coding: utf-8 -*-
"""HTTP API service - RESTful interface for HarmonyOS and external clients"""
import json
import time
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum


class APIEndpoint(Enum):
    CHAT = "/api/v1/chat"
    STREAM_CHAT = "/api/v1/chat/stream"
    AGENT_TASK = "/api/v1/agent/task"
    AGENT_PLAN = "/api/v1/agent/plan"
    SKILL_LIST = "/api/v1/skills"
    SKILL_EXECUTE = "/api/v1/skill/execute"
    MEMORY_SEARCH = "/api/v1/memory/search"
    MEMORY_ADD = "/api/v1/memory/add"
    PERMISSION_CHECK = "/api/v1/permission/check"
    HEALTH = "/api/v1/health"
    TRAJECTORY = "/api/v1/trajectory"
    SESSION_CREATE = "/api/v1/session/create"
    SESSION_CLOSE = "/api/v1/session/close"
    KNOWLEDGE_QUERY = "/api/v1/knowledge/query"
    KNOWLEDGE_ADD = "/api/v1/knowledge/add"


@dataclass
class APIRequest:
    endpoint: APIEndpoint
    method: str
    params: Dict[str, Any] = None
    data: Dict[str, Any] = None
    headers: Dict[str, str] = None


@dataclass
class APIResponse:
    success: bool
    data: Any = None
    error: str = None
    timestamp: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'data': self.data,
            'error': self.error,
            'timestamp': self.timestamp or time.time(),
        }


class AgentAPIServer:

    def __init__(self, host: str = '0.0.0.0', port: int = 8900):
        self.host = host
        self.port = port
        self._handlers: Dict[APIEndpoint, Dict[str, Callable]] = {}
        self._running: bool = False
        self._request_log: list = []
        self._max_log_size: int = 1000
        self._register_default_handlers()

    def _register_default_handlers(self):
        self.register_handler(APIEndpoint.HEALTH, 'GET', self._handle_health)
        self.register_handler(APIEndpoint.SKILL_LIST, 'GET', self._handle_skill_list)
        self.register_handler(APIEndpoint.CHAT, 'POST', self._handle_chat)
        self.register_handler(APIEndpoint.AGENT_PLAN, 'POST', self._handle_agent_plan)
        self.register_handler(APIEndpoint.SESSION_CREATE, 'POST', self._handle_session_create)

    def register_handler(self, endpoint: APIEndpoint, method: str, handler: Callable):
        if endpoint not in self._handlers:
            self._handlers[endpoint] = {}
        self._handlers[endpoint][method.upper()] = handler

    async def handle_request(self, request: APIRequest) -> APIResponse:
        self._request_log.append({
            'timestamp': time.time(),
            'endpoint': request.endpoint.value,
            'method': request.method,
        })
        if len(self._request_log) > self._max_log_size:
            self._request_log = self._request_log[-self._max_log_size:]

        handlers = self._handlers.get(request.endpoint, {})
        handler = handlers.get(request.method.upper())

        if handler is None:
            return APIResponse(
                success=False,
                error=f'No handler for {request.method} {request.endpoint.value}',
            )

        try:
            result = await handler(request)
            if isinstance(result, APIResponse):
                return result
            return APIResponse(success=True, data=result)
        except Exception as e:
            return APIResponse(success=False, error=str(e))

    async def _handle_health(self, request: APIRequest) -> APIResponse:
        return APIResponse(
            success=True,
            data={'status': 'healthy', 'version': '1.0.0', 'uptime': time.time()},
        )

    async def _handle_skill_list(self, request: APIRequest) -> APIResponse:
        try:
            from bridge.skills.registry import SkillsRegistry
            registry = SkillsRegistry()
            skills = list(registry._skills.keys()) if hasattr(registry, '_skills') else []
            return APIResponse(success=True, data={'skills': skills})
        except Exception as e:
            return APIResponse(success=True, data={'skills': [], 'error': str(e)})

    async def _handle_chat(self, request: APIRequest) -> APIResponse:
        data = request.data or {}
        return APIResponse(
            success=True,
            data={
                'session_id': data.get('session_id', 'default'),
                'message': data.get('message', ''),
                'status': 'received',
            },
        )

    async def _handle_agent_plan(self, request: APIRequest) -> APIResponse:
        data = request.data or {}
        return APIResponse(
            success=True,
            data={
                'plan_type': data.get('type', 'analysis'),
                'user_request': data.get('request', ''),
                'status': 'plan_generated',
            },
        )

    async def _handle_session_create(self, request: APIRequest) -> APIResponse:
        session_id = f'session_{int(time.time())}'
        return APIResponse(
            success=True,
            data={'session_id': session_id, 'created_at': time.time()},
        )

    def get_request_stats(self) -> Dict:
        return {
            'total_requests': len(self._request_log),
            'endpoints': list(set(r['endpoint'] for r in self._request_log)),
            'recent': self._request_log[-10:] if self._request_log else [],
        }


_server: Optional[AgentAPIServer] = None


def get_api_server() -> AgentAPIServer:
    global _server
    if _server is None:
        _server = AgentAPIServer()
    return _server
