from __future__ import annotations

import json
import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple


@dataclass
class CheckpointMetadata:
    checkpoint_id: str
    session_id: str
    timestamp: float
    trigger_reason: str
    label: str = ""
    message_count: int = 0
    tool_state_hash: str = ""


@dataclass
class SessionSnapshot:
    messages: List[dict] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    tool_states: dict = field(default_factory=dict)
    memory_state: Optional[dict] = None


class CheckpointStore:
    MAX_PER_SESSION = 50

    def __init__(self, directory: str | None = None) -> None:
        if directory is None:
            directory = os.path.join(os.path.expanduser("~"), ".lemoncode", "checkpoints")
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _snapshot_path(self, checkpoint_id: str) -> Path:
        return self._dir / f"{checkpoint_id}_snapshot.json"

    def _meta_path(self, checkpoint_id: str) -> Path:
        return self._dir / f"{checkpoint_id}_meta.json"

    def _load_meta_raw(self, checkpoint_id: str) -> Optional[CheckpointMetadata]:
        p = self._meta_path(checkpoint_id)
        if not p.exists():
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CheckpointMetadata(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def _session_checkpoints(self, session_id: str) -> List[CheckpointMetadata]:
        results: List[CheckpointMetadata] = []
        for p in self._dir.glob("*_meta.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = CheckpointMetadata(**data)
                if session_id is None or meta.session_id == session_id:
                    results.append(meta)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        results.sort(key=lambda m: m.timestamp)
        return results

    def _enforce_limit(self, session_id: str) -> None:
        existing = self._session_checkpoints(session_id)
        while len(existing) > self.MAX_PER_SESSION:
            oldest = existing.pop(0)
            self._delete_files(oldest.checkpoint_id)

    def _delete_files(self, checkpoint_id: str) -> bool:
        sp = self._snapshot_path(checkpoint_id)
        mp = self._meta_path(checkpoint_id)
        ok = False
        for fp in (sp, mp):
            try:
                if fp.exists():
                    fp.unlink()
                    ok = True
            except OSError:
                continue
        return ok

    def save(self, checkpoint_id: str, snapshot: SessionSnapshot, metadata: CheckpointMetadata) -> bool:
        with self._lock:
            try:
                snapshot_data = asdict(snapshot)
                meta_data = asdict(metadata)

                with open(self._snapshot_path(checkpoint_id), "w", encoding="utf-8") as f:
                    json.dump(snapshot_data, f, ensure_ascii=False, indent=2)

                with open(self._meta_path(checkpoint_id), "w", encoding="utf-8") as f:
                    json.dump(meta_data, f, ensure_ascii=False, indent=2)

                self._enforce_limit(metadata.session_id)
                return True
            except (OSError, TypeError, ValueError):
                return False

    def load(self, checkpoint_id: str) -> Optional[Tuple[SessionSnapshot, CheckpointMetadata]]:
        with self._lock:
            sp = self._snapshot_path(checkpoint_id)
            mp = self._meta_path(checkpoint_id)
            if not sp.exists() or not mp.exists():
                return None
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    snap_data = json.load(f)
                with open(mp, "r", encoding="utf-8") as f:
                    meta_data = json.load(f)
                snapshot = SessionSnapshot(**snap_data)
                metadata = CheckpointMetadata(**meta_data)
                return (snapshot, metadata)
            except (json.JSONDecodeError, TypeError, ValueError):
                return None

    def list_checkpoints(self, session_id: str | None = None) -> List[CheckpointMetadata]:
        with self._lock:
            return self._session_checkpoints(session_id)

    def delete(self, checkpoint_id: str) -> bool:
        with self._lock:
            return self._delete_files(checkpoint_id)

    def get_latest(self, session_id: str) -> Optional[CheckpointMetadata]:
        with self._lock:
            all_meta = self._session_checkpoints(session_id)
            return all_meta[-1] if all_meta else None


def _compute_tool_state_hash(tool_states: dict) -> str:
    raw = json.dumps(tool_states, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class CheckpointManager:
    def __init__(
        self,
        store: CheckpointStore,
        auto_interval: int = 10,
        auto_after_tool: bool = True,
        auto_before_error: bool = True,
    ) -> None:
        self._store = store
        self._auto_interval = auto_interval
        self._auto_after_tool = auto_after_tool
        self._auto_before_error = auto_before_error
        self._message_counter: Dict[str, int] = {}
        self._last_was_tool_call: Dict[str, bool] = {}

    def create_checkpoint(
        self,
        session_id: str,
        messages: List[dict],
        context: dict,
        tool_states: dict,
        reason: str = "manual",
        label: str = "",
    ) -> CheckpointMetadata:
        cp_id = str(uuid.uuid4())
        snapshot = SessionSnapshot(
            messages=list(messages),
            context=dict(context),
            tool_states=dict(tool_states),
        )
        metadata = CheckpointMetadata(
            checkpoint_id=cp_id,
            session_id=session_id,
            timestamp=time.time(),
            trigger_reason=reason,
            label=label,
            message_count=len(messages),
            tool_state_hash=_compute_tool_state_hash(tool_states),
        )
        self._store.save(cp_id, snapshot, metadata)
        return metadata

    def restore_checkpoint(self, checkpoint_id: str) -> Optional[SessionSnapshot]:
        result = self._store.load(checkpoint_id)
        if result is None:
            return None
        return result[0]

    def should_auto_checkpoint(self, message_count: int, last_tool_call: bool, error_occurred: bool) -> bool:
        if error_occurred and self._auto_before_error:
            return True
        if last_tool_call and self._auto_after_tool:
            return True
        if message_count > 0 and message_count % self._auto_interval == 0:
            return True
        return False

    def auto_checkpoint(
        self,
        session_id: str,
        messages: List[dict],
        context: dict,
        tool_states: dict,
        reason: str,
    ) -> Optional[CheckpointMetadata]:
        if reason not in ("auto_interval", "after_tool", "before_error"):
            return None
        return self.create_checkpoint(session_id, messages, context, tool_states, reason=reason)

    def list_checkpoints(self, session_id: str) -> List[CheckpointMetadata]:
        return self._store.list_checkpoints(session_id)

    def label_checkpoint(self, checkpoint_id: str, label: str) -> bool:
        result = self._store.load(checkpoint_id)
        if result is None:
            return False
        snapshot, metadata = result
        metadata.label = label
        return self._store.save(checkpoint_id, snapshot, metadata)

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        return self._store.delete(checkpoint_id)


class SessionRecovery:
    def __init__(self, store: CheckpointStore) -> None:
        self._store = store

    def recover_to(self, session_id: str, checkpoint_id: str) -> Optional[SessionSnapshot]:
        result = self._store.load(checkpoint_id)
        if result is None:
            return None
        metadata = result[1]
        if metadata.session_id != session_id:
            return None
        return result[0]

    def recover_to_latest(self, session_id: str) -> Optional[SessionSnapshot]:
        latest = self._store.get_latest(session_id)
        if latest is None:
            return None
        result = self._store.load(latest.checkpoint_id)
        if result is None:
            return None
        return result[0]

    def validate_snapshot(self, snapshot: SessionSnapshot) -> dict:
        warnings: list[str] = []
        if not snapshot.messages:
            warnings.append("empty_messages")
        has_system_prompt = False
        if snapshot.context:
            sp = snapshot.context.get("system_prompt")
            if sp is not None and str(sp).strip():
                has_system_prompt = True
        if not has_system_prompt:
            warnings.append("missing_system_prompt")
        if snapshot.tool_states:
            for tool_name, state in snapshot.tool_states.items():
                if state is None:
                    warnings.append(f"tool_state_null:{tool_name}")
                elif isinstance(state, dict):
                    if "status" in state and state["status"] not in ("active", "idle", "stopped", "error"):
                        warnings.append(f"tool_state_inconsistent:{tool_name}:status={state['status']}")
        return {"valid": len(warnings) == 0, "warnings": warnings}
