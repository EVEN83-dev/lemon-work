# -*- coding: utf-8 -*-
"""364章 T3.3: Docker沙箱 — 容器化安全执行环境"""

import json
import os
import subprocess
import tempfile
from typing import Dict, Optional


class DockerSandbox:
    _seq = 0

    def __init__(self, image: str = "python:3.12-slim", timeout: int = 30,
                 memory_limit: str = "1g", network: str = "none"):
        self.image = image
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.network = network
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._available = False
        return self._available

    def execute(self, code: str, language: str = "python",
                stdin: str = "") -> Dict:
        if not self.is_available():
            return {"success": False, "error": "Docker未安装或未启动",
                    "output": "请安装Docker Desktop并确保docker命令可用"}

        ext_map = {"python": ".py", "javascript": ".js", "bash": ".sh"}
        ext = ext_map.get(language, ".txt")

        with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False,
                                          encoding="utf-8") as f:
            f.write(code)
            host_path = f.name

        DockerSandbox._seq += 1
        container_name = f"lemon_sandbox_{os.getpid()}_{DockerSandbox._seq}"
        host_dir = os.path.dirname(host_path)
        script_name = os.path.basename(host_path)

        cmd_map = {
            "python": ["python3", script_name],
            "javascript": ["node", script_name],
            "bash": ["bash", script_name],
        }
        cmd_parts = cmd_map.get(language, ["cat", script_name])

        docker_cmd = [
            "docker", "run", "--rm",
            f"--name={container_name}",
            f"--memory={self.memory_limit}",
            f"--network={self.network}",
            f"--cpus=2",
            f"-v", f"{host_dir}:/workspace",
            "-w", "/workspace",
            self.image,
        ] + cmd_parts

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True, text=True,
                timeout=self.timeout,
                input=stdin,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
                "returncode": result.returncode,
                "container": container_name,
            }
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["docker", "kill", container_name],
                capture_output=True, timeout=5,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return {"success": False, "error": f"执行超时({self.timeout}s)",
                    "output": "", "container": container_name}
        except Exception as e:
            return {"success": False, "error": str(e), "output": ""}
        finally:
            try:
                os.remove(host_path)
            except OSError:
                pass

    def list_images(self) -> list:
        if not self.is_available():
            return []
        try:
            result = subprocess.run(
                ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return [img.strip() for img in result.stdout.strip().split("\n") if img.strip()]
        except Exception:
            return []
