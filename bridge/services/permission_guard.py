"""
B-P3-006: Permission Guard Service

Capability-based permission checks with audit logging.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


CAPABILITIES = [
    "FILE_READ",
    "FILE_WRITE",
    "NETWORK",
    "SYSTEM_CMD",
    "PERSONAL_DATA",
]

DEFAULT_POLICY: Dict[str, bool] = {
    "FILE_READ": True,
    "FILE_WRITE": False,
    "NETWORK": True,
    "SYSTEM_CMD": False,
    "PERSONAL_DATA": False,
}


@dataclass
class PermissionAuditEntry:
    tool_id: str
    capability: str
    allowed: bool
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "toolId": self.tool_id,
            "capability": self.capability,
            "allowed": self.allowed,
            "timestamp": self.timestamp,
        }


@dataclass
class PermissionRule:
    tool_id: str
    capability: str
    allowed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "toolId": self.tool_id,
            "capability": self.capability,
            "allowed": self.allowed,
        }


class PermissionGuardService:
    MAX_AUDIT = 1000

    def __init__(self, data_dir: str = "") -> None:
        if not data_dir:
            data_dir = str(Path(__file__).parent.parent / "data")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._policy: Dict[str, bool] = dict(DEFAULT_POLICY)
        self._rules: List[PermissionRule] = []
        self._audit: List[PermissionAuditEntry] = []
        self._load_rules()

    def _load_rules(self) -> None:
        path = self._data_dir / "permission_rules.json"
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for r in data:
                self._rules.append(PermissionRule(
                    tool_id=r.get("toolId", ""),
                    capability=r.get("capability", ""),
                    allowed=r.get("allowed", False),
                ))
        except Exception:
            pass

    def _save_rules(self) -> None:
        path = self._data_dir / "permission_rules.json"
        data = [r.to_dict() for r in self._rules]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def check(self, tool_id: str, capability: str) -> bool:
        for rule in self._rules:
            if rule.tool_id == tool_id and rule.capability == capability:
                allowed = rule.allowed
                self._audit.append(PermissionAuditEntry(tool_id, capability, allowed, time.time()))
                self._trim_audit()
                return allowed

        allowed = self._policy.get(capability, False)
        self._audit.append(PermissionAuditEntry(tool_id, capability, allowed, time.time()))
        self._trim_audit()
        return allowed

    def grant(self, tool_id: str, capability: str) -> None:
        self._rules.append(PermissionRule(tool_id, capability, True))
        self._save_rules()

    def deny(self, tool_id: str, capability: str) -> None:
        self._rules.append(PermissionRule(tool_id, capability, False))
        self._save_rules()

    def is_path_safe(self, path: str) -> bool:
        if ".." in path:
            return False
        if "/system/" in path or "\\system\\" in path:
            return False
        if "/data/local/" in path or "\\data\\local\\" in path:
            return False
        return True

    def is_url_allowed(self, url: str) -> bool:
        return url.startswith("http://") or url.startswith("https://")

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        entries = self._audit[-limit:]
        return [e.to_dict() for e in entries]

    def list_rules(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._rules]

    def get_default_policy(self) -> Dict[str, bool]:
        return dict(self._policy)

    def set_default_capability(self, capability: str, allowed: bool) -> None:
        if capability in CAPABILITIES:
            self._policy[capability] = allowed

    def _trim_audit(self) -> None:
        if len(self._audit) > self.MAX_AUDIT:
            self._audit = self._audit[-self.MAX_AUDIT:]
