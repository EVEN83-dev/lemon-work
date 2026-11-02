import json
import subprocess
import threading
import logging
from typing import Dict, Any, Optional

from .mcp_types import MCPServerConfig

logger = logging.getLogger(__name__)


class StdioTransport:
    def __init__(self, command: str, args: Optional[list] = None, env: Optional[Dict[str, str]] = None):
        self._command = command
        self._args = args or []
        self._env = env
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._connected = False

    def connect(self) -> bool:
        try:
            import os
            env = dict(os.environ)
            if self._env:
                env.update(self._env)
            self._process = subprocess.Popen(
                [self._command] + self._args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                bufsize=0,
            )
            self._connected = True
            logger.info("[StdioTransport] Connected to %s", self._command)
            return True
        except Exception as e:
            logger.warning("[StdioTransport] Connect failed: %s", e)
            self._connected = False
            return False

    def send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._connected or not self._process:
            return {"jsonrpc": "2.0", "error": {"code": -1, "message": "Not connected"}}
        with self._lock:
            self._request_id += 1
            request: Dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params or {},
            }
            try:
                payload = json.dumps(request) + "\n"
                self._process.stdin.write(payload.encode("utf-8"))
                self._process.stdin.flush()
                return self.read_response()
            except Exception as e:
                logger.warning("[StdioTransport] send_request failed: %s", e)
                return {"jsonrpc": "2.0", "error": {"code": -3, "message": str(e)}}

    def read_response(self) -> Dict[str, Any]:
        if not self._process or not self._connected:
            return {"jsonrpc": "2.0", "error": {"code": -1, "message": "Not connected"}}
        try:
            line = self._process.stdout.readline()
            if not line:
                return {"jsonrpc": "2.0", "error": {"code": -2, "message": "Empty response"}}
            return json.loads(line.decode("utf-8"))
        except Exception as e:
            logger.warning("[StdioTransport] read_response failed: %s", e)
            return {"jsonrpc": "2.0", "error": {"code": -3, "message": str(e)}}

    def close(self) -> None:
        self._connected = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    def is_connected(self) -> bool:
        if not self._connected or not self._process:
            return False
        return self._process.poll() is None
