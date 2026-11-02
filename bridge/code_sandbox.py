"""
B-006: Code Sandbox - isolated code execution with resource limits.

Docker-first isolation with automatic fallback to subprocess.
Resource audit logging. Dangerous command blacklist. Output truncation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_MEMORY_MB = 1024
DEFAULT_CPU_COUNT = 2
MAX_OUTPUT_CHARS = 100000

_DANGEROUS_PATTERNS = [
    "rm -rf /", "rm -rf /*", "del /s /q C:\\",
    "format C:", "mkfs.", "dd if=",
    ":(){ :|:& };:", "fork bomb",
    "shutdown", "reboot", "halt",
    "os.system('rm", "subprocess.call(['rm",
    "__import__('os').system",
]

_DOCKER_IMAGE = "python:3.12-slim"


class AuditEntry:
    __slots__ = ("timestamp", "mode", "language", "status", "duration",
                 "timeout_hit", "output_chars", "error_chars")

    def __init__(self, mode: str, language: str, status: str, duration: float,
                 timeout_hit: bool, output_chars: int, error_chars: int) -> None:
        self.timestamp = time.time()
        self.mode = mode
        self.language = language
        self.status = status
        self.duration = duration
        self.timeout_hit = timeout_hit
        self.output_chars = output_chars
        self.error_chars = error_chars

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "mode": self.mode,
            "language": self.language,
            "status": self.status,
            "duration": round(self.duration, 3),
            "timeoutHit": self.timeout_hit,
            "outputChars": self.output_chars,
            "errorChars": self.error_chars,
        }


class CodeSandbox:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT,
                 memory_mb: int = DEFAULT_MEMORY_MB,
                 use_docker: bool = False):
        self._timeout = timeout
        self._memory_mb = memory_mb
        self._use_docker = use_docker
        self._docker_available: Optional[bool] = None
        self._audit: List[AuditEntry] = []
        self._audit_lock = threading.Lock()
        self._fallback_warned = False

    def _check_docker(self) -> bool:
        if self._docker_available is not None:
            return self._docker_available
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, timeout=5,
            )
            self._docker_available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            self._docker_available = False
        if self._docker_available:
            logger.info("Docker detected - sandbox will use container isolation")
        else:
            logger.warning("Docker not available - sandbox will use local subprocess (degraded isolation)")
        return self._docker_available

    def _check_blacklist(self, code: str) -> Optional[str]:
        code_lower = code.lower()
        for pattern in _DANGEROUS_PATTERNS:
            if pattern.lower() in code_lower:
                return pattern
        return None

    def _truncate_output(self, text: str) -> str:
        if len(text) <= MAX_OUTPUT_CHARS:
            return text
        return text[:MAX_OUTPUT_CHARS] + f"\n...[truncated, {len(text)} total chars]"

    def _record_audit(self, entry: AuditEntry) -> None:
        with self._audit_lock:
            self._audit.append(entry)
            if len(self._audit) > 1000:
                self._audit = self._audit[-1000:]

    async def execute(self, code: str, language: str = "python",
                      stdin_data: str = "") -> Dict[str, Any]:
        start = time.time()
        if language != "python":
            entry = AuditEntry("none", language, "error", time.time() - start,
                               False, 0, 0)
            self._record_audit(entry)
            return {
                "status": "error",
                "output": "",
                "error": f"Unsupported language: {language}",
                "duration": time.time() - start,
            }

        blacklist_hit = self._check_blacklist(code)
        if blacklist_hit:
            entry = AuditEntry("blocked", language, "blocked", time.time() - start,
                               False, 0, 0)
            self._record_audit(entry)
            return {
                "status": "error",
                "output": "",
                "error": f"Dangerous pattern detected: '{blacklist_hit}'",
                "duration": time.time() - start,
            }

        if self._use_docker and self._check_docker():
            result = await self._execute_docker(code, stdin_data, start)
        elif self._use_docker and not self._check_docker():
            if not self._fallback_warned:
                logger.warning("Docker requested but not available, falling back to subprocess")
                self._fallback_warned = True
            result = await self._execute_subprocess(code, stdin_data, start)
            result["fallback"] = True
            result["fallbackReason"] = "Docker not available"
        else:
            result = await self._execute_subprocess(code, stdin_data, start)

        if "output" in result:
            result["output"] = self._truncate_output(result["output"])
        if "error" in result:
            result["error"] = self._truncate_output(result["error"])

        mode = "docker" if self._use_docker and self._check_docker() else "subprocess"
        entry = AuditEntry(
            mode, language, result.get("status", "error"),
            result.get("duration", time.time() - start),
            result.get("status") == "timeout",
            len(result.get("output", "")),
            len(result.get("error", "")),
        )
        self._record_audit(entry)
        return result

    async def _execute_subprocess(self, code: str, stdin_data: str,
                                  start: float) -> Dict[str, Any]:
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py',
                                             delete=False, encoding='utf-8') as f:
                f.write(code)
                temp_path = f.name
            try:
                env = os.environ.copy()
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, temp_path,
                    stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(input=stdin_data.encode() if stdin_data else None),
                        timeout=self._timeout,
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    duration = time.time() - start
                    return {
                        "status": "timeout",
                        "output": "",
                        "error": f"Execution timed out after {self._timeout}s",
                        "duration": duration,
                    }
                stdout = stdout_bytes.decode('utf-8', errors='replace')
                stderr = stderr_bytes.decode('utf-8', errors='replace')
                duration = time.time() - start
                if proc.returncode == 0:
                    return {
                        "status": "success",
                        "output": stdout,
                        "error": stderr if stderr.strip() else "",
                        "duration": duration,
                    }
                return {
                    "status": "error",
                    "output": stdout,
                    "error": stderr,
                    "duration": duration,
                }
            finally:
                os.unlink(temp_path)
        except Exception as e:
            return {
                "status": "error",
                "output": "",
                "error": str(e),
                "duration": time.time() - start,
            }

    async def _execute_docker(self, code: str, stdin_data: str,
                              start: float) -> Dict[str, Any]:
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py',
                                             delete=False, encoding='utf-8') as f:
                f.write(code)
                temp_path = f.name
            container_code_path = "/tmp/sandbox_code.py"
            cmd = [
                "docker", "run", "--rm",
                "--network", "none",
                "--cpus", str(DEFAULT_CPU_COUNT),
                "--memory", f"{self._memory_mb}m",
                f"--timeout={self._timeout}",
                "-v", f"{temp_path}:{container_code_path}:ro",
                _DOCKER_IMAGE,
                "python", container_code_path,
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=stdin_data.encode() if stdin_data else None),
                    timeout=self._timeout + 15,
                )
                stdout = stdout_bytes.decode('utf-8', errors='replace')
                stderr = stderr_bytes.decode('utf-8', errors='replace')
                duration = time.time() - start
                if proc.returncode == 0:
                    return {"status": "success", "output": stdout, "error": "", "duration": duration}
                return {"status": "error", "output": stdout, "error": stderr, "duration": duration}
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                return {
                    "status": "timeout",
                    "output": "",
                    "error": f"Docker execution timed out after {self._timeout}s (container killed)",
                    "duration": time.time() - start,
                }
            finally:
                os.unlink(temp_path)
        except FileNotFoundError:
            return {
                "status": "error",
                "output": "",
                "error": "Docker not available",
                "duration": time.time() - start,
            }
        except Exception as e:
            return {
                "status": "error",
                "output": "",
                "error": str(e),
                "duration": time.time() - start,
            }

    def set_timeout(self, seconds: int) -> None:
        self._timeout = seconds

    def set_memory_limit(self, mb: int) -> None:
        self._memory_mb = mb

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._audit_lock:
            entries = list(self._audit[-limit:])
        return [e.to_dict() for e in entries]

    def get_docker_status(self) -> Dict[str, Any]:
        available = self._check_docker() if self._docker_available is None else self._docker_available
        return {
            "dockerAvailable": available,
            "dockerRequested": self._use_docker,
            "effectiveMode": "docker" if (self._use_docker and available) else "subprocess",
            "timeout": self._timeout,
            "memoryMb": self._memory_mb,
            "maxOutputChars": MAX_OUTPUT_CHARS,
        }
