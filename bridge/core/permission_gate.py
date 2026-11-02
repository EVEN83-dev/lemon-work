# -*- coding: utf-8 -*-
"""Permission gate system - prevent Agent misoperations"""
from dataclasses import dataclass
from typing import Dict, Optional, Callable, List
from enum import Enum
import re


class PermissionLevel(Enum):
    ALLOW = 'allow'
    ASK = 'ask'
    DENY = 'deny'


@dataclass
class PermissionRule:
    tool_name: str
    level: PermissionLevel
    pattern: Optional[str] = None
    description: str = ''


class PermissionGate:

    def __init__(self):
        self._rules: Dict[str, PermissionRule] = {}
        self._custom_confirmations: Dict[str, Callable] = {}
        self._init_default_rules()

    def _init_default_rules(self):
        dangerous_tools = [
            PermissionRule('file_delete', PermissionLevel.ASK, description='File deletion requires confirmation'),
            PermissionRule('file_overwrite', PermissionLevel.ASK, description='File overwrite requires confirmation'),
            PermissionRule('file_rename', PermissionLevel.ASK, description='File rename requires confirmation'),
            PermissionRule('execute_code', PermissionLevel.ASK, description='Code execution requires confirmation'),
            PermissionRule('shell_command', PermissionLevel.ASK, description='Shell command requires confirmation'),
            PermissionRule('network_request', PermissionLevel.ASK, description='Network request requires confirmation'),
            PermissionRule('file_download', PermissionLevel.ASK, description='File download requires confirmation'),
        ]
        safe_tools = [
            PermissionRule('file_read', PermissionLevel.ALLOW, description='File read allowed'),
            PermissionRule('file_search', PermissionLevel.ALLOW, description='File search allowed'),
            PermissionRule('code_analysis', PermissionLevel.ALLOW, description='Code analysis allowed'),
            PermissionRule('git_status', PermissionLevel.ALLOW, description='Git status query allowed'),
            PermissionRule('git_log', PermissionLevel.ALLOW, description='Git log query allowed'),
        ]
        for rule in dangerous_tools + safe_tools:
            self._rules[rule.tool_name] = rule

    def check_permission(self, tool_name: str, args: Dict = None) -> PermissionLevel:
        rule = self._rules.get(tool_name)
        if rule is None:
            if any(kw in tool_name for kw in ['read', 'search', 'query', 'list', 'get']):
                return PermissionLevel.ALLOW
            elif any(kw in tool_name for kw in ['delete', 'overwrite', 'execute', 'run']):
                return PermissionLevel.ASK
            else:
                return PermissionLevel.ASK
        if rule.pattern and args:
            args_str = str(args)
            if re.search(rule.pattern, args_str):
                return rule.level
        return rule.level

    def require_confirmation(self, tool_name: str, args: Dict = None) -> bool:
        return self.check_permission(tool_name, args) == PermissionLevel.ASK

    def is_allowed(self, tool_name: str, args: Dict = None) -> bool:
        return self.check_permission(tool_name, args) != PermissionLevel.DENY

    def add_rule(self, rule: PermissionRule):
        self._rules[rule.tool_name] = rule

    def set_tool_level(self, tool_name: str, level: PermissionLevel):
        if tool_name in self._rules:
            self._rules[tool_name].level = level
        else:
            self._rules[tool_name] = PermissionRule(tool_name, level)

    def get_rules_summary(self) -> List[Dict]:
        return [
            {'tool': name, 'level': rule.level.value, 'description': rule.description}
            for name, rule in sorted(self._rules.items())
        ]


_gate: Optional[PermissionGate] = None


def get_permission_gate() -> PermissionGate:
    global _gate
    if _gate is None:
        _gate = PermissionGate()
    return _gate
