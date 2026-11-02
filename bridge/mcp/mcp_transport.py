import json
import subprocess
import threading
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

from .mcp_types import MCPServerConfig


class StdioTransport:
    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._connected = False
        self._read_timeout = 30

    def connect(self) -> bool:
        try:
            env = None
            if self._config.env:
                import os
                env = dict(os.environ)
                env.update(self._config.env)
            self._process = subprocess.Popen(
                [self._config.command] + self._config.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                bufsize=0,
            )
            self._connected = True
            return True
        except Exception:
            self._connected = False
            return False

    def send(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not self._connected or not self._process:
            return {"jsonrpc": "2.0", "error": {"code": -1, "message": "Not connected"}}
        with self._lock:
            self._request_id += 1
            request["id"] = self._request_id
            request["jsonrpc"] = "2.0"
            try:
                payload = json.dumps(request) + "\n"
                self._process.stdin.write(payload.encode("utf-8"))
                self._process.stdin.flush()
                line = self._process.stdout.readline()
                if not line:
                    return {"jsonrpc": "2.0", "error": {"code": -2, "message": "Empty response"}}
                return json.loads(line.decode("utf-8"))
            except Exception as e:
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


class HttpTransport:
    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._request_id = 0
        self._lock = threading.Lock()
        self._connected = False

    def connect(self) -> bool:
        try:
            resp = self._send_request({
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "lemon-agent", "version": "1.0.0"},
                },
            })
            if "error" not in resp:
                self._connected = True
                return True
            return False
        except Exception:
            return False

    def send(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not self._connected and request.get("method") != "initialize":
            return {"jsonrpc": "2.0", "error": {"code": -1, "message": "Not connected"}}
        with self._lock:
            self._request_id += 1
            request["id"] = self._request_id
            request["jsonrpc"] = "2.0"
            return self._send_request(request)

    def _send_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        try:
            data = json.dumps(request).encode("utf-8")
            req = urllib.request.Request(
                self._config.url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    **self._config.headers,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8")
                return json.loads(body)
            except Exception:
                return {"jsonrpc": "2.0", "error": {"code": e.code, "message": str(e)}}
        except Exception as e:
            return {"jsonrpc": "2.0", "error": {"code": -3, "message": str(e)}}

    def close(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected
