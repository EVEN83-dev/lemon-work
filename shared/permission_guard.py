from __future__ import annotations

import fnmatch
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Optional


class Capability(StrEnum):
    FILE_READ = "FILE_READ"
    FILE_WRITE = "FILE_WRITE"
    FILE_DELETE = "FILE_DELETE"
    SHELL_EXEC = "SHELL_EXEC"
    NETWORK_ACCESS = "NETWORK_ACCESS"
    PERSONAL_DATA_ACCESS = "PERSONAL_DATA_ACCESS"
    SYSTEM_MODIFY = "SYSTEM_MODIFY"


class PermissionDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"


@dataclass
class PermissionRule:
    id: str
    capability: str
    decision: str
    path_pattern: str = ""
    tool_pattern: str = ""
    priority: int = 0
    description: str = ""


@dataclass
class AuditEntry:
    timestamp: float
    event_type: str
    capability: str
    decision: str
    detail: str = ""
    tool: str = ""
    path: str = ""
    session_id: str = ""


_DEFAULT_RULES = [
    PermissionRule(id="default_file_read", capability=Capability.FILE_READ, decision=PermissionDecision.ALLOW, priority=0),
    PermissionRule(id="default_file_write", capability=Capability.FILE_WRITE, decision=PermissionDecision.REQUIRE_CONFIRMATION, priority=0),
    PermissionRule(id="default_file_delete", capability=Capability.FILE_DELETE, decision=PermissionDecision.REQUIRE_CONFIRMATION, priority=0),
    PermissionRule(id="default_shell_exec", capability=Capability.SHELL_EXEC, decision=PermissionDecision.REQUIRE_CONFIRMATION, priority=0),
    PermissionRule(id="default_network_access", capability=Capability.NETWORK_ACCESS, decision=PermissionDecision.ALLOW, priority=0),
    PermissionRule(id="default_personal_data", capability=Capability.PERSONAL_DATA_ACCESS, decision=PermissionDecision.REQUIRE_CONFIRMATION, priority=0),
    PermissionRule(id="default_system_modify", capability=Capability.SYSTEM_MODIFY, decision=PermissionDecision.DENY, priority=0),
]

_DANGEROUS_COMMANDS = [
    "rm -rf /",
    "rm -rf /*",
    "del /s /q C:",
    "format",
    "mkfs",
    "dd if=",
    ":(){ :|:& };:",
    "shutdown",
    "reboot",
]


class PolicyEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rules: dict[str, PermissionRule] = {}
        for rule in _DEFAULT_RULES:
            self._rules[rule.id] = rule

    def add_rule(self, rule: PermissionRule) -> None:
        with self._lock:
            self._rules[rule.id] = rule

    def remove_rule(self, rule_id: str) -> None:
        with self._lock:
            self._rules.pop(rule_id, None)

    def evaluate(self, capability: str, path: str = "", tool: str = "") -> str:
        with self._lock:
            sorted_rules = sorted(self._rules.values(), key=lambda r: r.priority, reverse=True)
        for rule in sorted_rules:
            if rule.capability != capability:
                continue
            if rule.path_pattern and path and not fnmatch.fnmatch(path, rule.path_pattern):
                continue
            if rule.tool_pattern and tool and not fnmatch.fnmatch(tool, rule.tool_pattern):
                continue
            return rule.decision
        return PermissionDecision.DENY


class SecurityCheckpoint:
    def __init__(self, engine: PolicyEngine) -> None:
        self._engine = engine

    def check_tool_execution(self, tool_id: str, capability: str, ctx: dict | None = None) -> str:
        decision = self._engine.evaluate(capability, tool=tool_id)
        return decision

    def check_file_operation(self, path: str, capability: str) -> str:
        decision = self._engine.evaluate(capability, path=path)
        return decision

    def check_shell_command(self, command: str) -> str:
        lowered = command.strip().lower()
        for dangerous in _DANGEROUS_COMMANDS:
            if dangerous.lower() in lowered:
                return PermissionDecision.DENY
        return self._engine.evaluate(Capability.SHELL_EXEC)


class ApprovalFlow:
    def __init__(self, ui_callback: Callable | None = None) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, threading.Event] = {}
        self._results: dict[str, bool] = {}
        self._ui_callback = ui_callback
        self._auto_approve = ui_callback is None
        self._approval_log: list[dict] = []

    def set_ui_callback(self, callback: Callable) -> None:
        self._ui_callback = callback
        self._auto_approve = False

    def set_auto_approve(self, enabled: bool) -> None:
        self._auto_approve = enabled

    def request_approval(self, capability: str, detail: str, timeout: int = 60) -> bool:
        approval_id = str(uuid.uuid4())
        event = threading.Event()
        with self._lock:
            self._pending[approval_id] = event

        log_entry = {
            "approval_id": approval_id,
            "capability": capability,
            "detail": detail,
            "timestamp": time.time(),
            "status": "pending",
        }
        self._approval_log.append(log_entry)

        if self._auto_approve:
            self._auto_confirm(approval_id)
        elif self._ui_callback is not None:
            try:
                self._ui_callback(approval_id, capability, detail)
            except Exception:
                self._auto_confirm(approval_id)
        else:
            self._auto_confirm(approval_id)

        signaled = event.wait(timeout=timeout)
        with self._lock:
            self._pending.pop(approval_id, None)
            result = self._results.pop(approval_id, False)

        if not signaled:
            log_entry["status"] = "timeout"
            return False
        log_entry["status"] = "approved" if result else "denied"
        return result

    def batch_approve(self, capabilities: list, detail: str) -> dict:
        results: dict[str, bool] = {}
        for cap in capabilities:
            results[cap] = self.request_approval(cap, detail)
        return results

    def _auto_confirm(self, approval_id: str) -> None:
        def _confirm() -> None:
            time.sleep(0.01)
            self.confirm(approval_id, True)
        t = threading.Thread(target=_confirm, daemon=True)
        t.start()

    def confirm(self, approval_id: str, approved: bool) -> None:
        with self._lock:
            self._results[approval_id] = approved
            evt = self._pending.get(approval_id)
        if evt is not None:
            evt.set()

    def deny(self, approval_id: str) -> None:
        self.confirm(approval_id, False)

    def get_pending(self) -> list[str]:
        with self._lock:
            return list(self._pending.keys())

    def get_approval_log(self, limit: int = 100) -> list[dict]:
        return self._approval_log[-limit:]


class AuditLogger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[AuditEntry] = []

    def log(
        self,
        event_type: str,
        capability: str,
        decision: str,
        detail: str = "",
        tool: str = "",
        path: str = "",
        session_id: str = "",
    ) -> None:
        entry = AuditEntry(
            timestamp=time.time(),
            event_type=event_type,
            capability=capability,
            decision=decision,
            detail=detail,
            tool=tool,
            path=path,
            session_id=session_id,
        )
        with self._lock:
            self._entries.append(entry)

    def query(
        self,
        session_id: str | None = None,
        tool: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        with self._lock:
            snapshot = list(self._entries)
        filtered: list[AuditEntry] = []
        for entry in snapshot:
            if session_id is not None and entry.session_id != session_id:
                continue
            if tool is not None and entry.tool != tool:
                continue
            if event_type is not None and entry.event_type != event_type:
                continue
            filtered.append(entry)
        return filtered[-limit:]

    def export(self, format: str = "json") -> str:
        with self._lock:
            snapshot = list(self._entries)
        if format == "json":
            data = []
            for e in snapshot:
                data.append({
                    "timestamp": e.timestamp,
                    "event_type": e.event_type,
                    "capability": e.capability,
                    "decision": e.decision,
                    "detail": e.detail,
                    "tool": e.tool,
                    "path": e.path,
                    "session_id": e.session_id,
                })
            return json.dumps(data, indent=2)
        raise ValueError(f"Unsupported export format: {format}")


class PermissionGuard:
    def __init__(self) -> None:
        self.engine = PolicyEngine()
        self.checkpoint = SecurityCheckpoint(self.engine)
        self.approval = ApprovalFlow()
        self.audit = AuditLogger()
        self._session_id = str(uuid.uuid4())

    def check(
        self,
        capability: str,
        path: str = "",
        tool: str = "",
        auto_approve: bool = False,
    ) -> bool:
        if capability == Capability.SHELL_EXEC and path:
            decision = self.checkpoint.check_shell_command(path)
        elif path and capability in (Capability.FILE_READ, Capability.FILE_WRITE, Capability.FILE_DELETE):
            decision = self.checkpoint.check_file_operation(path, capability)
        elif tool:
            decision = self.checkpoint.check_tool_execution(tool, capability)
        else:
            decision = self.engine.evaluate(capability, path=path, tool=tool)

        if decision == PermissionDecision.ALLOW:
            self.audit.log(
                event_type="permission_check",
                capability=capability,
                decision=decision,
                path=path,
                tool=tool,
                session_id=self._session_id,
            )
            return True

        if decision == PermissionDecision.DENY:
            self.audit.log(
                event_type="permission_check",
                capability=capability,
                decision=decision,
                detail="Denied by policy",
                path=path,
                tool=tool,
                session_id=self._session_id,
            )
            return False

        if decision == PermissionDecision.REQUIRE_CONFIRMATION:
            if auto_approve:
                self.audit.log(
                    event_type="permission_check",
                    capability=capability,
                    decision=PermissionDecision.ALLOW,
                    detail="Auto-approved",
                    path=path,
                    tool=tool,
                    session_id=self._session_id,
                )
                return True
            detail = f"capability={capability}"
            if path:
                detail += f" path={path}"
            if tool:
                detail += f" tool={tool}"
            approved = self.approval.request_approval(capability, detail)
            final_decision = PermissionDecision.ALLOW if approved else PermissionDecision.DENY
            self.audit.log(
                event_type="permission_check",
                capability=capability,
                decision=final_decision,
                detail="User confirmed" if approved else "User denied",
                path=path,
                tool=tool,
                session_id=self._session_id,
            )
            return approved

        self.audit.log(
            event_type="permission_check",
            capability=capability,
            decision=PermissionDecision.DENY,
            detail="Unknown decision",
            path=path,
            tool=tool,
            session_id=self._session_id,
        )
        return False
