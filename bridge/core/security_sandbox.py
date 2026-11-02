# -*- coding: utf-8 -*-
"""Security sandbox - restrict Agent operation permissions"""
import os
import subprocess
import tempfile
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum


class SandboxMode(Enum):
    STRICT = 'strict'
    STANDARD = 'standard'
    PERMISSIVE = 'permissive'


@dataclass
class FilePermission:
    read: bool = True
    write: bool = False
    execute: bool = False


@dataclass
class SandboxConfig:
    mode: SandboxMode = SandboxMode.STANDARD
    allowed_paths: List[str] = field(default_factory=list)
    blocked_paths: List[str] = field(default_factory=list)
    allowed_commands: List[str] = field(default_factory=list)
    blocked_commands: List[str] = field(default_factory=list)
    max_execution_time: int = 30
    max_file_size: int = 10 * 1024 * 1024

    def is_path_allowed(self, path: str) -> bool:
        for blocked in self.blocked_paths:
            if path.startswith(blocked):
                return False
        if self.allowed_paths:
            for allowed in self.allowed_paths:
                if path.startswith(allowed):
                    return True
            return False
        return True

    def is_command_allowed(self, command: str) -> bool:
        for blocked in self.blocked_commands:
            if blocked in command:
                return False
        if self.allowed_commands:
            for allowed in self.allowed_commands:
                if allowed in command:
                    return True
            return False
        dangerous = ['rm -rf', 'format', 'del /s', 'shutdown', 'poweroff']
        for kw in dangerous:
            if kw in command.lower():
                return False
        return True


class SecuritySandbox:

    def __init__(self, config: SandboxConfig = None):
        self.config = config or SandboxConfig()
        self._violations: List[Dict] = []
        self._temp_dir: Optional[str] = None

    def check_file_operation(self, path: str, operation: str) -> Dict:
        if not self.config.is_path_allowed(path):
            self._log_violation('file_access', path, f'Path blocked: {path}')
            return {'allowed': False, 'reason': f'Path not allowed: {path}'}
        permissions = self._get_path_permissions(path)
        if operation == 'read' and not permissions.read:
            return {'allowed': False, 'reason': 'Read permission denied'}
        elif operation == 'write' and not permissions.write:
            return {'allowed': False, 'reason': 'Write permission denied'}
        elif operation == 'execute' and not permissions.execute:
            return {'allowed': False, 'reason': 'Execute permission denied'}
        return {'allowed': True}

    def check_command(self, command: str) -> Dict:
        if not self.config.is_command_allowed(command):
            self._log_violation('command_blocked', command, f'Command blocked: {command}')
            return {'allowed': False, 'reason': f'Command not allowed: {command}'}
        return {'allowed': True}

    def execute_in_sandbox(self, command: str, cwd: str = None) -> Dict:
        check = self.check_command(command)
        if not check['allowed']:
            return check
        try:
            temp_dir = self._ensure_temp_dir()
            result = subprocess.run(
                command, shell=True, cwd=cwd or temp_dir,
                capture_output=True, text=True,
                timeout=self.config.max_execution_time,
            )
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Execution timed out'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _get_path_permissions(self, path: str) -> FilePermission:
        if self.config.mode == SandboxMode.STRICT:
            return FilePermission(read=True, write=False, execute=False)
        elif self.config.mode == SandboxMode.PERMISSIVE:
            return FilePermission(read=True, write=True, execute=True)
        else:
            if path.endswith(('.py', '.js', '.ts', '.md', '.txt')):
                return FilePermission(read=True, write=True, execute=False)
            return FilePermission(read=True, write=False, execute=False)

    def _ensure_temp_dir(self) -> str:
        if self._temp_dir is None or not os.path.exists(self._temp_dir):
            self._temp_dir = tempfile.mkdtemp(prefix='lemon_sandbox_')
        return self._temp_dir

    def _log_violation(self, violation_type: str, target: str, reason: str):
        import time as _time
        self._violations.append({
            'type': violation_type, 'target': target,
            'reason': reason, 'timestamp': _time.time(),
        })

    def get_violations(self) -> List[Dict]:
        return self._violations

    def get_config_summary(self) -> Dict:
        return {
            'mode': self.config.mode.value,
            'allowed_paths_count': len(self.config.allowed_paths),
            'blocked_paths_count': len(self.config.blocked_paths),
            'allowed_commands_count': len(self.config.allowed_commands),
            'blocked_commands_count': len(self.config.blocked_commands),
            'max_execution_time': self.config.max_execution_time,
            'violations_count': len(self._violations),
        }


_sandbox: Optional[SecuritySandbox] = None


def get_security_sandbox(config: SandboxConfig = None) -> SecuritySandbox:
    global _sandbox
    if _sandbox is None:
        _sandbox = SecuritySandbox(config)
    return _sandbox
