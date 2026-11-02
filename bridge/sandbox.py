from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class SandboxPolicy:
    allowed_commands: List[str] = field(default_factory=list)
    denied_commands: List[str] = field(default_factory=list)
    denied_patterns: List[str] = field(default_factory=list)
    timeout_seconds: int = 30
    max_output_bytes: int = 1048576
    max_memory_mb: int = 512
    working_directory: str = ""
    env_vars: Optional[Dict[str, str]] = None
    network_allowed: bool = False


@dataclass
class SandboxResult:
    success: bool
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    blocked: bool = False
    block_reason: str = ""
    duration_seconds: float = 0.0
    command: str = ""
    audit_id: str = ""


_DANGEROUS_COMMANDS: List[str] = [
    "rm -rf /",
    "rm -rf /*",
    "del /s /q C:",
    "del /s /q D:",
    "format C:",
    "format D:",
    "mkfs",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    ":(){ :|:& };:",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "chmod 777 /",
    "chmod -R 777 /",
    "taskkill /F /IM",
    "kill -9 1",
    "net user",
    "net localgroup administrators",
    "reg add",
    "reg delete",
    "crontab -r",
    "sudo rm",
]

_DANGEROUS_PATTERNS: List[str] = [
    r"redirect.*?/etc/",
    r">.*?/etc/",
    r">.*?/boot/",
    r">.*?C:\\Windows\\",
    r">\s*/etc/",
    r">\s*/boot/",
    r"\|\s*(sh|bash|python)\s+-c",
    r"\.\./\.\./etc/passwd",
    r"\.\.[\\/]\.\.[\\/]",
]


class DangerDetector:
    def __init__(self) -> None:
        self._dangerous_commands: List[str] = list(_DANGEROUS_COMMANDS)
        self._dangerous_patterns: List[re.Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in _DANGEROUS_PATTERNS
        ]

    def is_dangerous(self, command: str) -> Tuple[bool, str]:
        command_lower = command.lower().strip()
        for dangerous in self._dangerous_commands:
            if dangerous.lower() in command_lower:
                return True, f"Matches dangerous command: {dangerous}"
        for pattern in self._dangerous_patterns:
            if pattern.search(command):
                return True, f"Matches dangerous pattern: {pattern.pattern}"
        return False, ""


def _default_policy() -> SandboxPolicy:
    return SandboxPolicy(
        denied_commands=[
            "rm -rf /",
            "rm -rf /*",
            "format",
            "mkfs",
            "dd if=/dev/zero",
            "dd if=/dev/random",
            "shutdown",
            "reboot",
            "halt",
            "poweroff",
            ":(){ :|:& };:",
            "chmod 777 /",
            "chmod -R 777 /",
            "taskkill /F /IM",
            "kill -9 1",
            "net user",
            "net localgroup administrators",
            "reg add",
            "reg delete",
            "crontab -r",
            "sudo rm",
        ],
        denied_patterns=[
            r">\s*/etc/",
            r">\s*/boot/",
            r">\s*C:\\Windows\\",
            r"\|\s*(sh|bash)\s+-c.*?(rm|del|format|mkfs)",
            r"\|\s*python\s+-c.*?(os\.system|subprocess)",
            r"\.\.[\\/]\.\.[\\/]",
        ],
    )


_NETWORK_COMMANDS = [
    "curl", "wget", "ping", "traceroute", "nslookup", "dig",
    "ssh", "scp", "rsync", "ftp", "sftp", "nc", "ncat",
    "telnet", "netcat", "httpie", "aria2c",
    "Invoke-WebRequest", "Invoke-RestMethod", "Test-Connection",
    "pip install", "npm install", "gem install", "cargo install",
    "apt-get", "yum", "dnf", "pacman", "brew",
    "git clone", "git pull", "git push", "git fetch",
    "docker pull", "docker push", "docker run",
]

_NETWORK_FLAGS = [
    r"--url\s",
    r"--remote",
    r"http://",
    r"https://",
    r"ftp://",
    r"ssh://",
    r"@\S+:\d+",
    r"\.\.\s+\.\.\s+\d+",
]


class NetworkDetector:
    def is_network_command(self, command: str) -> Tuple[bool, str]:
        command_lower = command.lower().strip()
        base = command_lower.split()[0] if command_lower else ""
        base_name = os.path.basename(base)
        for net_cmd in _NETWORK_COMMANDS:
            nc = net_cmd.lower()
            if base_name == nc or command_lower.startswith(nc + " "):
                return True, f"Network command detected: {net_cmd}"
        for pattern_str in _NETWORK_FLAGS:
            try:
                if re.search(pattern_str, command, re.IGNORECASE):
                    return True, f"Network flag detected: {pattern_str}"
            except re.error:
                continue
        return False, ""


class MemoryLimiter:
    def apply_limit(self, proc: subprocess.Popen, max_memory_mb: int) -> None:
        if platform.system().lower() != "windows":
            return
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 0x00002000
            JobObjectExtendedLimitInformation = 9
            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                return
            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32),
                ]
            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_uint64),
                    ("WriteOperationCount", ctypes.c_uint64),
                    ("OtherOperationCount", ctypes.c_uint64),
                    ("ReadTransferCount", ctypes.c_uint64),
                    ("WriteTransferCount", ctypes.c_uint64),
                    ("OtherTransferCount", ctypes.c_uint64),
                ]
            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_JOB_MEMORY
            info.JobMemoryLimit = max_memory_mb * 1024 * 1024
            kernel32.SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            kernel32.AssignProcessToJobObject(handle, proc.pid if isinstance(proc.pid, int) else 0)
        except Exception:
            pass


class CommandSandbox:
    def __init__(self, policy: Optional[SandboxPolicy] = None) -> None:
        self._policy: SandboxPolicy = policy if policy is not None else _default_policy()
        self._detector: DangerDetector = DangerDetector()
        self._network_detector: NetworkDetector = NetworkDetector()
        self._memory_limiter: MemoryLimiter = MemoryLimiter()
        self._lock: threading.Lock = threading.Lock()

    def _check_policy(self, command: str) -> Tuple[bool, str]:
        is_dangerous, reason = self._detector.is_dangerous(command)
        if is_dangerous:
            return True, reason

        command_lower = command.lower().strip()
        command_base = command_lower.split()[0] if command_lower else ""

        for denied in self._policy.denied_commands:
            if denied.lower() in command_lower:
                return True, f"Denied by policy command blacklist: {denied}"

        if self._policy.allowed_commands:
            allowed = False
            for allowed_cmd in self._policy.allowed_commands:
                if command_lower.startswith(allowed_cmd.lower()) or command_base == allowed_cmd.lower():
                    allowed = True
                    break
            if not allowed:
                return True, f"Command not in allowed list: {command_base}"

        for pattern_str in self._policy.denied_patterns:
            try:
                if re.search(pattern_str, command, re.IGNORECASE):
                    return True, f"Denied by policy pattern: {pattern_str}"
            except re.error:
                continue

        if not self._policy.network_allowed:
            is_net, net_reason = self._network_detector.is_network_command(command)
            if is_net:
                return True, f"Network access denied: {net_reason}"

        return False, ""

    def _truncate_output(self, output: str, max_bytes: int) -> str:
        encoded = output.encode("utf-8", errors="replace")
        if len(encoded) <= max_bytes:
            return output
        truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
        return truncated + f"\n... [truncated, exceeded {max_bytes} bytes]"

    def execute(
        self,
        command: str,
        args: Optional[List[str]] = None,
        stdin_data: Optional[str] = None,
    ) -> SandboxResult:
        audit_id = str(uuid.uuid4())
        full_command = command
        if args:
            full_command = command + " " + " ".join(args)

        blocked, reason = self._check_policy(full_command)
        if blocked:
            return SandboxResult(
                success=False,
                blocked=True,
                block_reason=reason,
                command=full_command,
                audit_id=audit_id,
            )

        cmd_parts: List[str] = [command]
        if args:
            cmd_parts = [command] + list(args)

        use_shell = False
        if not args and " " in command:
            use_shell = True
            cmd_parts = [command]

        env = os.environ.copy()
        if self._policy.env_vars:
            env.update(self._policy.env_vars)

        cwd = self._policy.working_directory if self._policy.working_directory else None

        start_time = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd_parts,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                shell=use_shell,
                stdin=subprocess.PIPE if stdin_data else None,
            )
            if self._policy.max_memory_mb > 0:
                self._memory_limiter.apply_limit(proc, self._policy.max_memory_mb)
            try:
                stdout_bytes, stderr_bytes = proc.communicate(
                    input=stdin_data.encode("utf-8") if stdin_data else None,
                    timeout=self._policy.timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
                duration = time.monotonic() - start_time
                return SandboxResult(
                    success=False,
                    timed_out=True,
                    duration_seconds=round(duration, 4),
                    command=full_command,
                    audit_id=audit_id,
                )
            duration = time.monotonic() - start_time
            stdout = self._truncate_output(
                stdout_bytes.decode("utf-8", errors="replace"),
                self._policy.max_output_bytes,
            )
            stderr = self._truncate_output(
                stderr_bytes.decode("utf-8", errors="replace"),
                self._policy.max_output_bytes,
            )
            return SandboxResult(
                success=proc.returncode == 0,
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=round(duration, 4),
                command=full_command,
                audit_id=audit_id,
            )
        except FileNotFoundError:
            duration = time.monotonic() - start_time
            return SandboxResult(
                success=False,
                exit_code=-1,
                stderr=f"Command not found: {command}",
                duration_seconds=round(duration, 4),
                command=full_command,
                audit_id=audit_id,
            )
        except Exception as exc:
            duration = time.monotonic() - start_time
            return SandboxResult(
                success=False,
                exit_code=-1,
                stderr=str(exc),
                duration_seconds=round(duration, 4),
                command=full_command,
                audit_id=audit_id,
            )

    def execute_batch(self, commands: List[str]) -> List[SandboxResult]:
        results: List[SandboxResult] = []
        for cmd in commands:
            result = self.execute(cmd)
            results.append(result)
        return results


class SandboxAudit:
    _MAX_ENTRIES = 1000

    def __init__(self) -> None:
        self._entries: List[SandboxResult] = []
        self._lock: threading.Lock = threading.Lock()

    def log(self, result: SandboxResult) -> None:
        with self._lock:
            self._entries.append(result)
            if len(self._entries) > self._MAX_ENTRIES:
                self._entries = self._entries[-self._MAX_ENTRIES:]

    def query(
        self,
        command: Optional[str] = None,
        blocked_only: bool = False,
        limit: int = 100,
    ) -> List[SandboxResult]:
        with self._lock:
            results = list(self._entries)
        if command is not None:
            results = [r for r in results if command.lower() in r.command.lower()]
        if blocked_only:
            results = [r for r in results if r.blocked]
        return results[-limit:]

    def export(self, format: str = "json") -> str:
        with self._lock:
            entries = list(self._entries)
        if format.lower() == "json":
            data = []
            for entry in entries:
                data.append({
                    "success": entry.success,
                    "exit_code": entry.exit_code,
                    "stdout": entry.stdout,
                    "stderr": entry.stderr,
                    "timed_out": entry.timed_out,
                    "blocked": entry.blocked,
                    "block_reason": entry.block_reason,
                    "duration_seconds": entry.duration_seconds,
                    "command": entry.command,
                    "audit_id": entry.audit_id,
                })
            return json.dumps(data, indent=2, ensure_ascii=False)
        raise ValueError(f"Unsupported export format: {format}")


class WindowsSandbox(CommandSandbox):
    _DANGEROUS_EXTENSIONS = {".bat", ".cmd", ".ps1"}
    _DANGEROUS_DRIVE_CMDS = ["format", "del /s", "rd /s", "rmdir /s"]

    def _check_windows_policy(self, command: str, args: Optional[List[str]]) -> Tuple[bool, str]:
        command_lower = command.lower().strip()
        _, ext = os.path.splitext(command_lower)
        if ext in self._DANGEROUS_EXTENSIONS:
            return True, f"Script execution blocked (extension): {ext}"

        for drive in "abcdefghijklmnopqrstuvwxyz":
            if f"{drive}:\\windows" in command_lower:
                return True, f"Access to Windows directory blocked on drive {drive.upper()}:"

        full = command_lower
        if args:
            full = command_lower + " " + " ".join(a.lower() for a in args)
        for dangerous in self._DANGEROUS_DRIVE_CMDS:
            if dangerous in full:
                return True, f"Windows dangerous command: {dangerous}"

        return False, ""

    def execute(
        self,
        command: str,
        args: Optional[List[str]] = None,
        stdin_data: Optional[str] = None,
    ) -> SandboxResult:
        audit_id = str(uuid.uuid4())
        full_command = command
        if args:
            full_command = command + " " + " ".join(args)

        blocked, reason = self._check_policy(full_command)
        if blocked:
            return SandboxResult(
                success=False,
                blocked=True,
                block_reason=reason,
                command=full_command,
                audit_id=audit_id,
            )

        blocked, reason = self._check_windows_policy(command, args)
        if blocked:
            return SandboxResult(
                success=False,
                blocked=True,
                block_reason=reason,
                command=full_command,
                audit_id=audit_id,
            )

        needs_cmd_wrapper = False
        if not args and " " in command:
            needs_cmd_wrapper = True

        if needs_cmd_wrapper:
            cmd_parts = ["cmd.exe", "/C", command]
            use_shell = False
        else:
            cmd_parts = [command]
            if args:
                cmd_parts = [command] + list(args)
            use_shell = False

        env = os.environ.copy()
        if self._policy.env_vars:
            env.update(self._policy.env_vars)

        cwd = self._policy.working_directory if self._policy.working_directory else None

        start_time = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd_parts,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                shell=use_shell,
                stdin=subprocess.PIPE if stdin_data else None,
            )
            if self._policy.max_memory_mb > 0:
                self._memory_limiter.apply_limit(proc, self._policy.max_memory_mb)
            try:
                stdout_bytes, stderr_bytes = proc.communicate(
                    input=stdin_data.encode("utf-8") if stdin_data else None,
                    timeout=self._policy.timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
                duration = time.monotonic() - start_time
                return SandboxResult(
                    success=False,
                    timed_out=True,
                    duration_seconds=round(duration, 4),
                    command=full_command,
                    audit_id=audit_id,
                )
            duration = time.monotonic() - start_time
            stdout = self._truncate_output(
                stdout_bytes.decode("utf-8", errors="replace"),
                self._policy.max_output_bytes,
            )
            stderr = self._truncate_output(
                stderr_bytes.decode("utf-8", errors="replace"),
                self._policy.max_output_bytes,
            )
            return SandboxResult(
                success=proc.returncode == 0,
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=round(duration, 4),
                command=full_command,
                audit_id=audit_id,
            )
        except FileNotFoundError:
            duration = time.monotonic() - start_time
            return SandboxResult(
                success=False,
                exit_code=-1,
                stderr=f"Command not found: {command}",
                duration_seconds=round(duration, 4),
                command=full_command,
                audit_id=audit_id,
            )
        except Exception as exc:
            duration = time.monotonic() - start_time
            return SandboxResult(
                success=False,
                exit_code=-1,
                stderr=str(exc),
                duration_seconds=round(duration, 4),
                command=full_command,
                audit_id=audit_id,
            )


class LinuxSandbox(CommandSandbox):
    def _build_unshare_command(self, command: str, args: Optional[List[str]] = None) -> List[str]:
        unshare_parts = ["unshare", "--mount", "--pid", "--net", "--fork", "--propagation", "slave"]
        if self._policy.max_memory_mb > 0:
            unshare_parts.append(f"--map-root-user")
        cmd_parts = unshare_parts + ["--"]
        cmd_parts.append(command)
        if args:
            cmd_parts.extend(args)
        return cmd_parts

    def _build_cgroup_command(self, command: str, args: Optional[List[str]] = None) -> List[str]:
        parts = []
        if self._policy.max_memory_mb > 0:
            parts = [
                "cgcreate", "-g", f"memory:lemon_sandbox",
                "&&",
                f"cgset", "-r", f"memory.limit_in_bytes={self._policy.max_memory_mb * 1024 * 1024}", "lemon_sandbox",
                "&&",
                "cgexec", "-g", "memory:lemon_sandbox",
            ]
        parts.append(command)
        if args:
            parts.extend(args)
        return parts

    def create_namespace(self, namespace_type: str) -> Optional[int]:
        if platform.system().lower() != "linux":
            return None
        try:
            ns_flags = {
                "mount": "--mount",
                "pid": "--pid",
                "net": "--net",
                "user": "--user",
                "uts": "--uts",
                "ipc": "--ipc",
                "cgroup": "--cgroup",
            }
            flag = ns_flags.get(namespace_type)
            if not flag:
                return None
            result = subprocess.run(
                ["unshare", flag, "--fork", "echo", "ok"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                return 0
            return None
        except Exception:
            return None

    def apply_seccomp(self, profile: str) -> bool:
        if platform.system().lower() != "linux":
            return False
        try:
            seccomp_profiles = {
                "strict": ["seccomp-tools", "dump", "--profile=strict"],
                "default": ["seccomp-tools", "dump", "--profile=default"],
                "relaxed": ["seccomp-tools", "dump", "--profile=relaxed"],
            }
            if profile not in seccomp_profiles:
                return False
            result = subprocess.run(
                seccomp_profiles[profile],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def set_cgroup(self, cgroup_path: str, limit_mb: int = 0) -> bool:
        if platform.system().lower() != "linux":
            return False
        try:
            limit = limit_mb or self._policy.max_memory_mb
            if limit <= 0:
                return True
            subprocess.run(
                ["cgcreate", "-g", f"memory:{cgroup_path}"],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                ["cgset", "-r", f"memory.limit_in_bytes={limit * 1024 * 1024}", cgroup_path],
                capture_output=True, timeout=5,
            )
            return True
        except Exception:
            return False

    def execute(
        self,
        command: str,
        args: Optional[List[str]] = None,
        stdin_data: Optional[str] = None,
    ) -> SandboxResult:
        if platform.system().lower() != "linux":
            return super().execute(command, args, stdin_data)

        audit_id = str(uuid.uuid4())
        full_command = command
        if args:
            full_command = command + " " + " ".join(args)

        blocked, reason = self._check_policy(full_command)
        if blocked:
            return SandboxResult(
                success=False,
                blocked=True,
                block_reason=reason,
                command=full_command,
                audit_id=audit_id,
            )

        use_isolation = os.path.exists("/usr/bin/unshare")
        if use_isolation:
            cmd_parts = self._build_unshare_command(command, args)
            use_shell = False
        else:
            cmd_parts = [command]
            if args:
                cmd_parts = [command] + list(args)
            use_shell = False

        env = os.environ.copy()
        if self._policy.env_vars:
            env.update(self._policy.env_vars)

        cwd = self._policy.working_directory if self._policy.working_directory else None

        start_time = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd_parts,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                shell=use_shell,
                stdin=subprocess.PIPE if stdin_data else None,
            )
            try:
                stdout_bytes, stderr_bytes = proc.communicate(
                    input=stdin_data.encode("utf-8") if stdin_data else None,
                    timeout=self._policy.timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
                duration = time.monotonic() - start_time
                return SandboxResult(
                    success=False,
                    timed_out=True,
                    duration_seconds=round(duration, 4),
                    command=full_command,
                    audit_id=audit_id,
                )
            duration = time.monotonic() - start_time
            stdout = self._truncate_output(
                stdout_bytes.decode("utf-8", errors="replace"),
                self._policy.max_output_bytes,
            )
            stderr = self._truncate_output(
                stderr_bytes.decode("utf-8", errors="replace"),
                self._policy.max_output_bytes,
            )
            isolation_note = " (isolated: namespace)" if use_isolation else ""
            return SandboxResult(
                success=proc.returncode == 0,
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=round(duration, 4),
                command=full_command + isolation_note,
                audit_id=audit_id,
            )
        except FileNotFoundError:
            duration = time.monotonic() - start_time
            return SandboxResult(
                success=False,
                exit_code=-1,
                stderr=f"Command not found: {command}",
                duration_seconds=round(duration, 4),
                command=full_command,
                audit_id=audit_id,
            )
        except Exception as exc:
            duration = time.monotonic() - start_time
            return SandboxResult(
                success=False,
                exit_code=-1,
                stderr=str(exc),
                duration_seconds=round(duration, 4),
                command=full_command,
                audit_id=audit_id,
            )


def create_sandbox(policy: Optional[SandboxPolicy] = None) -> CommandSandbox:
    current_os = platform.system().lower()
    if current_os == "windows":
        return WindowsSandbox(policy)
    return LinuxSandbox(policy)
