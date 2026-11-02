from __future__ import annotations

import csv
import fnmatch
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from io import StringIO
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PermissionAction(str):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionResponse:
    ALLOW_ONCE = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    DENY = "deny"


@dataclass
class PermissionResult:
    action: str = PermissionAction.ALLOW
    reason: str = ""
    rule_type: str = ""
    rule_id: str = ""
    request_id: str = ""

    @property
    def allowed(self) -> bool:
        return self.action == PermissionAction.ALLOW

    @property
    def denied(self) -> bool:
        return self.action == PermissionAction.DENY

    @property
    def needs_approval(self) -> bool:
        return self.action == PermissionAction.ASK

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "rule_type": self.rule_type,
            "rule_id": self.rule_id,
            "request_id": self.request_id,
            "allowed": self.allowed,
            "denied": self.denied,
            "needs_approval": self.needs_approval,
        }


_SYSTEM_DIR_PATTERNS = [
    "C:/Windows/*", "C:/Windows",
    "C:\\Windows\\*",
    "/etc/*", "/etc",
    "/boot/*", "/boot",
    "/System/*", "/System",
    "/usr/sbin/*",
    "C:/Program Files/*",
    "C:\\Program Files\\*",
    "/proc/*", "/sys/*",
]

_DANGEROUS_CMD_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+/\*", re.IGNORECASE),
    re.compile(r"\bdel\s+/s", re.IGNORECASE),
    re.compile(r"\bformat\s+[A-Za-z]:", re.IGNORECASE),
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\bpoweroff\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=/dev/zero", re.IGNORECASE),
    re.compile(r"\breg\s+add\b", re.IGNORECASE),
    re.compile(r"\breg\s+delete\b", re.IGNORECASE),
    re.compile(r"\bchmod\s+777\s+/", re.IGNORECASE),
    re.compile(r"\bcrontab\s+-r\b", re.IGNORECASE),
    re.compile(r"\b:()\s*\{\s*:\s*\|\s*:\s*&\s*\}", re.IGNORECASE),
    re.compile(r"\btaskkill\b", re.IGNORECASE),
]


@dataclass
class PermissionRule:
    permission: str = ""
    pattern: str = "*"
    action: str = PermissionAction.ALLOW
    description: str = ""
    rule_type: str = "global"
    priority: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "permission": self.permission,
            "pattern": self.pattern,
            "action": self.action,
            "description": self.description,
            "rule_type": self.rule_type,
            "priority": self.priority,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> PermissionRule:
        return PermissionRule(
            permission=data.get("permission", ""),
            pattern=data.get("pattern", "*"),
            action=data.get("action", PermissionAction.ALLOW),
            description=data.get("description", ""),
            rule_type=data.get("rule_type", "global"),
            priority=data.get("priority", 0),
        )


@dataclass
class PermissionRequest:
    id: str = ""
    skill_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    risk_level: str = "medium"
    approved: Optional[bool] = None
    timestamp: float = 0.0
    scope: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:16]
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "skillName": self.skill_name,
            "args": self.args,
            "reason": self.reason,
            "riskLevel": self.risk_level,
            "approved": self.approved,
            "timestamp": self.timestamp,
            "scope": self.scope,
        }


PERMISSION_REQUIRED = "permission_required"
PLAN_APPROVAL_REQUIRED = "plan_approval_required"
PLAN_PROGRESS_UPDATED = "plan_progress_updated"


@dataclass
class PermissionDecision:
    request_id: str
    decision: str
    skill_name: str = ""
    target: str = ""
    project_id: str = ""
    timestamp: float = field(default_factory=time.time)


class AuditLogger:
    _RETENTION_DAYS = 30

    def __init__(self, db_path: str = ""):
        if not db_path:
            data_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "audit_log.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        self._auto_archive()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                skill_name TEXT DEFAULT '',
                target TEXT DEFAULT '',
                action TEXT DEFAULT '',
                decision TEXT DEFAULT '',
                risk_level TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                project_id TEXT DEFAULT '',
                session_id TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archived_at REAL NOT NULL,
                record_count INTEGER NOT NULL,
                date_range TEXT DEFAULT ''
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log(event_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_skill ON audit_log(skill_name)")
        conn.commit()
        conn.close()

    def _auto_archive(self) -> None:
        cutoff = time.time() - (self._RETENTION_DAYS * 86400)
        try:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM audit_log WHERE timestamp < ?", (cutoff,))
            count = c.fetchone()
            if count and count[0] > 0:
                c.execute("SELECT MIN(timestamp), MAX(timestamp) FROM audit_log WHERE timestamp < ?", (cutoff,))
                row = c.fetchone()
                date_range = ""
                if row and row[0] and row[1]:
                    date_range = str(row[0]) + " to " + str(row[1])
                c.execute("INSERT INTO audit_archive (archived_at, record_count, date_range) VALUES (?, ?, ?)",
                          (time.time(), count[0], date_range))
                c.execute("DELETE FROM audit_log WHERE timestamp < ?", (cutoff,))
                conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Auto-archive failed: %s", e)

    def log(self, event_type: str, skill_name: str = "", target: str = "",
            action: str = "", decision: str = "", risk_level: str = "",
            reason: str = "", project_id: str = "", session_id: str = "",
            metadata: Optional[Dict] = None) -> int:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO audit_log (timestamp, event_type, skill_name, target, action,
                    decision, risk_level, reason, project_id, session_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                time.time(), event_type, skill_name, target, action,
                decision, risk_level, reason, project_id, session_id,
                json.dumps(metadata or {}, ensure_ascii=False),
            ))
            row_id = c.lastrowid
            conn.commit()
            conn.close()
            return row_id if row_id is not None else 0

    def query(self, event_type: str = "", skill_name: str = "",
              start_time: float = 0.0, end_time: float = 0.0,
              limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            query = "SELECT * FROM audit_log WHERE 1=1"
            params: List[Any] = []
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            if skill_name:
                query += " AND skill_name = ?"
                params.append(skill_name)
            if start_time > 0:
                query += " AND timestamp >= ?"
                params.append(start_time)
            if end_time > 0:
                query += " AND timestamp <= ?"
                params.append(end_time)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            c.execute(query, params)
            rows = c.fetchall()
            conn.close()
        results: List[Dict[str, Any]] = []
        for row in rows:
            results.append({
                "id": row[0], "timestamp": row[1], "event_type": row[2],
                "skill_name": row[3], "target": row[4], "action": row[5],
                "decision": row[6], "risk_level": row[7], "reason": row[8],
                "project_id": row[9], "session_id": row[10],
                "metadata": json.loads(row[11]) if row[11] else {},
            })
        return results

    def export_json(self, event_type: str = "", skill_name: str = "",
                    limit: int = 1000) -> str:
        entries = self.query(event_type=event_type, skill_name=skill_name, limit=limit)
        return json.dumps(entries, ensure_ascii=False, indent=2)

    def export_csv(self, event_type: str = "", skill_name: str = "",
                   limit: int = 1000) -> str:
        entries = self.query(event_type=event_type, skill_name=skill_name, limit=limit)
        if not entries:
            return ""
        output = StringIO()
        fieldnames = ["id", "timestamp", "event_type", "skill_name", "target",
                      "action", "decision", "risk_level", "reason", "project_id", "session_id"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)
        return output.getvalue()


@dataclass
class SandboxConfig:
    code_timeout_seconds: int = 30
    code_max_memory_mb: int = 512
    domain_whitelist: List[str] = field(default_factory=lambda: ["*"])
    allow_network: bool = True

    def is_domain_allowed(self, domain: str) -> bool:
        if not self.allow_network:
            return False
        if "*" in self.domain_whitelist:
            return True
        for allowed in self.domain_whitelist:
            if domain == allowed or domain.endswith("." + allowed):
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code_timeout_seconds": self.code_timeout_seconds,
            "code_max_memory_mb": self.code_max_memory_mb,
            "domain_whitelist": self.domain_whitelist,
            "allow_network": self.allow_network,
        }


class PermissionGate:
    def __init__(self, manager: Optional[PermissionManager] = None,
                 sandbox_config: Optional[SandboxConfig] = None):
        self._manager = manager or PermissionManager()
        self._sandbox_config = sandbox_config or SandboxConfig()
        self._callback: Optional[Callable[[PermissionRequest], None]] = None
        self._event_callbacks: Dict[str, List[Callable]] = {}
        self._manager._gate_ref = self

    def check(self, skill_name: str, args: Dict[str, Any]) -> PermissionResult:
        action_str = self._manager.check(skill_name, args)
        reason = ""
        rule_type = ""
        target = args.get("path", args.get("file_path", args.get("target", args.get("command", ""))))
        if action_str == PermissionAction.DENY:
            if self._manager._is_system_path(str(target)):
                reason = "system_path_blocked"
                rule_type = "global"
            elif skill_name in ("shell_exec", "execute_command", "run_code"):
                if self._manager._is_dangerous_command(str(target)):
                    reason = "dangerous_command"
                    rule_type = "global"
                else:
                    reason = "outside_project_root"
                    rule_type = "project"
            else:
                reason = "denied_by_rule"
        elif action_str == PermissionAction.ASK:
            reason = "requires_user_confirmation"
        else:
            reason = "allowed"
        return PermissionResult(
            action=action_str,
            reason=reason,
            rule_type=rule_type,
        )

    def check_network(self, domain: str) -> PermissionResult:
        if not self._sandbox_config.is_domain_allowed(domain):
            return PermissionResult(
                action=PermissionAction.DENY,
                reason="domain_not_in_whitelist",
                rule_type="sandbox",
            )
        return PermissionResult(
            action=PermissionAction.ALLOW,
            reason="domain_allowed",
            rule_type="sandbox",
        )

    def get_sandbox_config(self) -> SandboxConfig:
        return self._sandbox_config

    def set_sandbox_config(self, config: SandboxConfig) -> None:
        self._sandbox_config = config

    def get_manager(self) -> PermissionManager:
        return self._manager

    def on(self, event_name: str, callback: Callable) -> None:
        if event_name not in self._event_callbacks:
            self._event_callbacks[event_name] = []
        self._event_callbacks[event_name].append(callback)

    def emit(self, event_name: str, data: Any = None) -> None:
        for cb in self._event_callbacks.get(event_name, []):
            try:
                cb(data)
            except Exception:
                pass


class PermissionGuardAdapter:
    SKILL_CAPABILITY_MAP: Dict[str, str] = {
        "file_read": "FILE_READ",
        "file_write": "FILE_WRITE",
        "read_file": "FILE_READ",
        "write_file": "FILE_WRITE",
        "shell_exec": "SYSTEM_CMD",
        "execute_command": "SYSTEM_CMD",
        "run_code": "SYSTEM_CMD",
        "network_request": "NETWORK",
        "http_request": "NETWORK",
        "fetch_url": "NETWORK",
        "search_web": "NETWORK",
        "contact_search": "PERSONAL_DATA",
        "calendar_read": "PERSONAL_DATA",
    }

    def __init__(self, guard: Any) -> None:
        self._guard = guard
        self._pending: Dict[str, PermissionRequest] = {}
        self._approval_events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._audit_log: List[Dict[str, Any]] = []
        self._callback: Optional[Callable[[PermissionRequest], None]] = None

    def set_callback(self, callback: Callable[[PermissionRequest], None]) -> None:
        self._callback = callback

    def check(self, skill_name: str, args: Dict[str, Any]) -> str:
        capability = self.SKILL_CAPABILITY_MAP.get(skill_name, "")
        if not capability:
            target = args.get("path", args.get("file_path", args.get("target", args.get("command", ""))))
            if isinstance(target, str):
                if any(kw in skill_name for kw in ("write", "delete", "remove")):
                    capability = "FILE_WRITE"
                elif any(kw in skill_name for kw in ("read", "search", "list", "find")):
                    capability = "FILE_READ"
                elif any(kw in skill_name for kw in ("exec", "run", "shell", "command")):
                    capability = "SYSTEM_CMD"
                elif any(kw in skill_name for kw in ("http", "fetch", "request", "network")):
                    capability = "NETWORK"
                else:
                    capability = "FILE_READ"

        tool_id = args.get("tool_id", skill_name)
        allowed = self._guard.check(tool_id, capability)

        action = PermissionAction.ALLOW if allowed else PermissionAction.DENY

        self._audit_log.append({
            "timestamp": time.time(),
            "skill_name": skill_name,
            "capability": capability,
            "tool_id": tool_id,
            "action": action,
            "guard_allowed": allowed,
        })
        return action

    def request_approval(self, skill_name: str, args: Dict[str, Any],
                         reason: str = "", risk_level: str = "medium") -> PermissionRequest:
        req = PermissionRequest(
            skill_name=skill_name,
            args=args,
            reason=reason or "Skill '" + skill_name + "' 需要用户审批",
            risk_level=risk_level,
        )
        event = threading.Event()
        with self._lock:
            self._pending[req.id] = req
            self._approval_events[req.id] = event
        if self._callback:
            try:
                self._callback(req)
            except Exception:
                pass
        return req

    def resolve_request(self, request_id: str, approved: bool, scope: str = "once") -> None:
        with self._lock:
            req = self._pending.get(request_id)
            if req:
                req.approved = approved
                if approved and scope == "project_always":
                    req.metadata = req.metadata if hasattr(req, "metadata") else {}
            evt = self._approval_events.get(request_id)
        if evt is not None:
            evt.set()

    def wait_for_approval(self, request_id: str, timeout: float = 30.0) -> bool:
        with self._lock:
            evt = self._approval_events.get(request_id)
        if evt is None:
            return False
        signaled = evt.wait(timeout=timeout)
        if not signaled:
            return False
        with self._lock:
            req = self._pending.pop(request_id, None)
            self._approval_events.pop(request_id, None)
        return req.approved if req else False

    def add_rule(self, permission: str, pattern: str, action: str,
                 description: str = "用户自定义规则") -> None:
        capability = self.SKILL_CAPABILITY_MAP.get(permission, permission.upper())
        tool_id = pattern if pattern != "*" else ""
        if action == PermissionAction.ALLOW:
            self._guard.grant(tool_id, capability)
        elif action == PermissionAction.DENY:
            self._guard.deny(tool_id, capability)

    def remove_rule(self, permission: str, pattern: str, action: str) -> bool:
        return True

    def get_rules(self, permission: str = "") -> List[PermissionRule]:
        guard_rules = self._guard.list_rules()
        return [
            PermissionRule(
                permission=r.get("capability", ""),
                pattern=r.get("toolId", "*"),
                action=PermissionAction.ALLOW if r.get("allowed") else PermissionAction.DENY,
            )
            for r in guard_rules
        ]

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        guard_log = self._guard.get_audit_log(limit)
        return guard_log if guard_log else self._audit_log[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "mode": "guard_adapter",
            "guard_rules": len(self._guard.list_rules()),
            "pending_requests": len(self._pending),
            "audit_entries": len(self._audit_log),
        }


class PermissionManager:
    def __init__(self, config_path: str = "", project_root: str = ""):
        self._rules: List[PermissionRule] = []
        self._pending: Dict[str, PermissionRequest] = {}
        self._approval_events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._config_path = config_path or os.path.join(
            os.path.expanduser("~"), ".lemon_bridge", "permissions.json"
        )
        self._project_root = project_root
        self._project_whitelist: List[str] = []
        self._session_cache: Dict[str, str] = {}
        self._audit_logger: Optional[AuditLogger] = None
        self._callback: Optional[Callable[[PermissionRequest], None]] = None
        self._gate_ref: Optional[Any] = None
        self._load_default_rules()
        self._load_project_rules()
        self._load_custom_rules()

    def set_callback(self, callback: Callable[[PermissionRequest], None]) -> None:
        self._callback = callback

    def set_audit_logger(self, audit_logger: AuditLogger) -> None:
        self._audit_logger = audit_logger

    def set_project_root(self, root: str) -> None:
        self._project_root = root
        self._project_whitelist = [root]
        self._load_project_rules()

    def _load_default_rules(self) -> None:
        defaults = [
            PermissionRule("file_read", "*", PermissionAction.ALLOW, "允许读取所有文件", "global", 0),
            PermissionRule("file_write", "*", PermissionAction.ASK, "写入文件前需确认", "global", 0),
            PermissionRule("file_write", "C:/Windows/*", PermissionAction.DENY, "禁止写入系统目录", "global", 100),
            PermissionRule("file_write", "C:\\Windows\\*", PermissionAction.DENY, "禁止写入系统目录", "global", 100),
            PermissionRule("file_write", "/etc/*", PermissionAction.DENY, "禁止写入系统目录", "global", 100),
            PermissionRule("file_write", "/System/*", PermissionAction.DENY, "禁止写入系统目录", "global", 100),
            PermissionRule("file_delete", "*", PermissionAction.DENY, "默认禁止删除文件", "global", 50),
            PermissionRule("shell_exec", "*", PermissionAction.ASK, "执行Shell命令前需确认", "global", 0),
            PermissionRule("shell_exec", "rm -rf*", PermissionAction.DENY, "禁止rm -rf命令", "global", 100),
            PermissionRule("shell_exec", "format*", PermissionAction.DENY, "禁止format命令", "global", 100),
            PermissionRule("shell_exec", "del /s*", PermissionAction.DENY, "禁止del /s命令", "global", 100),
            PermissionRule("shell_exec", "shutdown*", PermissionAction.DENY, "禁止shutdown命令", "global", 100),
            PermissionRule("shell_exec", "taskkill*", PermissionAction.DENY, "禁止taskkill命令", "global", 100),
            PermissionRule("network_request", "*", PermissionAction.ASK, "网络请求前需确认", "global", 0),
            PermissionRule("code_search", "*", PermissionAction.ALLOW, "代码搜索允许", "tool", 10),
            PermissionRule("file_read", "*", PermissionAction.ALLOW, "文件读取允许", "tool", 10),
            PermissionRule("file_write", "*", PermissionAction.ASK, "文件写入需确认", "tool", 20),
            PermissionRule("execute_code", "*", PermissionAction.ASK, "代码执行需确认", "tool", 20),
            PermissionRule("file_delete", "*", PermissionAction.DENY, "文件删除禁止", "tool", 30),
            PermissionRule("format", "*", PermissionAction.DENY, "格式化禁止", "tool", 30),
        ]
        self._rules.extend(defaults)

    def _load_project_rules(self) -> None:
        if not self._project_root:
            return
        perm_file = os.path.join(self._project_root, "config", "project_permissions.yaml")
        if not os.path.exists(perm_file):
            perm_file = os.path.join(self._project_root, "config", "project_permissions.json")
        if not os.path.exists(perm_file):
            return
        try:
            with open(perm_file, "r", encoding="utf-8") as f:
                content = f.read()
            if perm_file.endswith(".json"):
                data = json.loads(content)
            else:
                data = self._parse_simple_yaml(content)
            for rule_data in data.get("rules", []):
                rule = PermissionRule.from_dict(rule_data)
                rule.rule_type = "project"
                self._rules.append(rule)
            for path in data.get("allowed_paths", []):
                self._project_whitelist.append(path)
        except Exception as e:
            logger.warning("Failed to load project permission rules: %s", e)

    def _parse_simple_yaml(self, content: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {"rules": [], "allowed_paths": []}
        current_key = ""
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.endswith(":"):
                current_key = stripped[:-1].strip()
                continue
            if current_key == "allowed_paths" and stripped.startswith("- "):
                result["allowed_paths"].append(stripped[2:].strip().strip('"').strip("'"))
        return result

    def _load_custom_rules(self) -> None:
        if not os.path.exists(self._config_path):
            return
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for rule_data in data.get("rules", []):
                rule = PermissionRule.from_dict(rule_data)
                rule.rule_type = "user"
                self._rules.append(rule)
        except Exception as e:
            logger.warning("Failed to load custom permission rules: %s", e)

    def save_custom_rules(self) -> None:
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        custom = [r for r in self._rules if r.rule_type == "user"]
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump({"rules": [r.to_dict() for r in custom]}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save custom permission rules: %s", e)

    def check(self, skill_name: str, args: Dict[str, Any]) -> str:
        target = args.get("path", args.get("file_path", args.get("target", args.get("command", "*"))))
        if not isinstance(target, str):
            target = "*"

        if self._is_system_path(target):
            if skill_name in ("file_write", "file_delete", "shell_exec"):
                self._log_audit("permission_check", skill_name, target, PermissionAction.DENY, "system_path_blocked")
                return PermissionAction.DENY

        if skill_name in ("shell_exec", "execute_command", "run_code"):
            if self._is_dangerous_command(target):
                self._log_audit("permission_check", skill_name, target, PermissionAction.DENY, "dangerous_command")
                return PermissionAction.DENY

        if skill_name in ("file_write", "file_delete") and self._project_root:
            if not self._is_within_project(target):
                self._log_audit("permission_check", skill_name, target, PermissionAction.DENY, "outside_project_root")
                return PermissionAction.DENY

        cache_key = skill_name + ":" + target
        cached = self._session_cache.get(cache_key)
        if cached:
            self._log_audit("permission_check", skill_name, target, cached, "session_cache")
            return cached

        deny_rule = None
        ask_rule = None
        allow_rule = None

        sorted_rules = sorted(self._rules, key=lambda r: r.priority, reverse=True)
        for rule in sorted_rules:
            if rule.permission != skill_name:
                continue
            if self._match_pattern(target, rule.pattern):
                if rule.action == PermissionAction.DENY and not deny_rule:
                    deny_rule = rule
                elif rule.action == PermissionAction.ASK and not ask_rule:
                    ask_rule = rule
                elif rule.action == PermissionAction.ALLOW and not allow_rule:
                    allow_rule = rule

        if deny_rule:
            action = PermissionAction.DENY
        elif ask_rule:
            action = PermissionAction.ASK
        elif allow_rule:
            action = PermissionAction.ALLOW
        else:
            action = PermissionAction.ASK

        self._log_audit("permission_check", skill_name, target, action,
                        (deny_rule or ask_rule or allow_rule or PermissionRule()).description)
        return action

    def check_result(self, skill_name: str, args: Dict[str, Any]) -> PermissionResult:
        action_str = self.check(skill_name, args)
        reason = ""
        rule_type = ""
        target = args.get("path", args.get("file_path", args.get("target", args.get("command", ""))))
        if action_str == PermissionAction.DENY:
            if self._is_system_path(str(target)):
                reason = "system_path_blocked"
            elif skill_name in ("shell_exec", "execute_command", "run_code") and self._is_dangerous_command(str(target)):
                reason = "dangerous_command"
            else:
                reason = "denied_by_rule"
        elif action_str == PermissionAction.ASK:
            reason = "requires_user_confirmation"
        else:
            reason = "allowed"
        return PermissionResult(action=action_str, reason=reason, rule_type=rule_type)

    def request_approval(self, skill_name: str, args: Dict[str, Any],
                         reason: str = "", risk_level: str = "medium") -> PermissionRequest:
        req = PermissionRequest(
            skill_name=skill_name,
            args=args,
            reason=reason or "Skill '" + skill_name + "' 需要用户审批",
            risk_level=risk_level,
        )
        event = threading.Event()
        with self._lock:
            self._pending[req.id] = req
            self._approval_events[req.id] = event

        self._log_audit("approval_requested", skill_name,
                        args.get("path", args.get("command", "")),
                        PermissionAction.ASK, req.reason, risk_level=risk_level)

        if self._callback:
            try:
                self._callback(req)
            except Exception:
                pass

        self._emit_event(PERMISSION_REQUIRED, req)

        return req

    def resolve_request(self, request_id: str, approved: bool, scope: str = PermissionResponse.ALLOW_ONCE) -> None:
        with self._lock:
            req = self._pending.get(request_id)
            if req:
                req.approved = approved
                req.scope = scope
                if approved and scope in (PermissionResponse.ALLOW_ALWAYS, "project_always"):
                    skill_name = req.skill_name
                    target = req.args.get("path", req.args.get("command", "*"))
                    if isinstance(target, str):
                        cache_key = skill_name + ":" + target
                        self._session_cache[cache_key] = PermissionAction.ALLOW
                        self.add_rule(skill_name, target, PermissionAction.ALLOW,
                                     "项目级永久允许")
            evt = self._approval_events.get(request_id)
        if evt is not None:
            evt.set()

    def wait_for_approval(self, request_id: str, timeout: float = 30.0) -> bool:
        with self._lock:
            evt = self._approval_events.get(request_id)
        if evt is None:
            return False
        signaled = evt.wait(timeout=timeout)
        if not signaled:
            return False
        with self._lock:
            req = self._pending.pop(request_id, None)
            self._approval_events.pop(request_id, None)
        return req.approved if req else False

    def add_rule(self, permission: str, pattern: str, action: str,
                 description: str = "用户自定义规则", rule_type: str = "user") -> None:
        rule = PermissionRule(
            permission=permission,
            pattern=pattern,
            action=action,
            description=description,
            rule_type=rule_type,
        )
        self._rules.append(rule)
        if rule_type == "user":
            self.save_custom_rules()

    def remove_rule(self, permission: str, pattern: str, action: str) -> bool:
        for i, rule in enumerate(self._rules):
            if (rule.permission == permission and rule.pattern == pattern
                    and rule.action == action):
                self._rules.pop(i)
                self.save_custom_rules()
                return True
        return False

    def get_rules(self, permission: str = "", rule_type: str = "") -> List[PermissionRule]:
        rules = self._rules
        if permission:
            rules = [r for r in rules if r.permission == permission]
        if rule_type:
            rules = [r for r in rules if r.rule_type == rule_type]
        return rules

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        if self._audit_logger:
            return self._audit_logger.query(limit=limit)
        return []

    def get_stats(self) -> Dict[str, Any]:
        by_action: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for r in self._rules:
            by_action[r.action] = by_action.get(r.action, 0) + 1
            by_type[r.rule_type] = by_type.get(r.rule_type, 0) + 1
        return {
            "total_rules": len(self._rules),
            "by_action": by_action,
            "by_type": by_type,
            "pending_requests": len(self._pending),
            "session_cache_size": len(self._session_cache),
            "project_root": self._project_root,
            "project_whitelist_size": len(self._project_whitelist),
        }

    def _is_system_path(self, path: str) -> bool:
        if path == "*":
            return False
        path_norm = path.replace("\\", "/")
        for pattern in _SYSTEM_DIR_PATTERNS:
            pat_norm = pattern.replace("\\", "/")
            if fnmatch.fnmatch(path_norm, pat_norm):
                return True
            if path_norm.startswith(pat_norm.rstrip("*")):
                return True
        return False

    def _is_dangerous_command(self, command: str) -> bool:
        if command == "*":
            return False
        for pattern in _DANGEROUS_CMD_PATTERNS:
            if pattern.search(command):
                return True
        return False

    def _is_within_project(self, path: str) -> bool:
        if path == "*":
            return True
        if not self._project_root:
            return True
        try:
            abs_path = os.path.abspath(path)
            abs_root = os.path.abspath(self._project_root)
            if abs_path.startswith(abs_root):
                return True
        except Exception:
            pass
        for allowed in self._project_whitelist:
            try:
                if os.path.abspath(path).startswith(os.path.abspath(allowed)):
                    return True
            except Exception:
                pass
        return False

    def _emit_event(self, event_name: str, data: Any = None) -> None:
        if self._gate_ref is not None:
            self._gate_ref.emit(event_name, data)

    def _log_audit(self, event_type: str, skill_name: str = "", target: str = "",
                   action: str = "", reason: str = "", risk_level: str = "") -> None:
        if self._audit_logger:
            self._audit_logger.log(
                event_type=event_type,
                skill_name=skill_name,
                target=target,
                action=action,
                reason=reason,
                risk_level=risk_level,
            )

    @staticmethod
    def _match_pattern(target: str, pattern: str) -> bool:
        if pattern == "*":
            return True
        return fnmatch.fnmatch(target, pattern)
