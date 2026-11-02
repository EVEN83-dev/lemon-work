"""
C6: Tool History — snapshot before/after each tool call + diff → tool_history/ + undo N steps.

Every tool call gets a before/after snapshot + diff.
Supports undo of last N steps by restoring from snapshots.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FileSnapshot:
    path: str
    content_hash: str
    content: str = ""
    exists: bool = True
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "contentHash": self.content_hash,
            "exists": self.exists,
            "timestamp": self.timestamp,
        }


@dataclass
class DiffResult:
    path: str
    added_lines: int = 0
    removed_lines: int = 0
    unified_diff: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "addedLines": self.added_lines,
            "removedLines": self.removed_lines,
            "unifiedDiff": self.unified_diff[:2000],
        }


@dataclass
class ToolHistoryEntry:
    entry_id: str
    tool_name: str
    args: Dict[str, Any]
    before_snapshots: List[FileSnapshot] = field(default_factory=list)
    after_snapshots: List[FileSnapshot] = field(default_factory=list)
    diffs: List[DiffResult] = field(default_factory=list)
    success: bool = False
    output_preview: str = ""
    timestamp: float = 0.0
    duration_ms: int = 0

    def __post_init__(self):
        if not self.entry_id:
            self.entry_id = uuid.uuid4().hex[:12]
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entryId": self.entry_id,
            "toolName": self.tool_name,
            "args": self.args,
            "beforeSnapshots": [s.to_dict() for s in self.before_snapshots],
            "afterSnapshots": [s.to_dict() for s in self.after_snapshots],
            "diffs": [d.to_dict() for d in self.diffs],
            "success": self.success,
            "outputPreview": self.output_preview[:200],
            "timestamp": self.timestamp,
            "durationMs": self.duration_ms,
        }


_FILE_TOOLS = frozenset({
    "write_file", "edit_file", "file_write", "file_edit",
    "create_file", "file_create", "delete_file", "file_delete",
    "replace_in_file", "apply_edit",
})


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _take_snapshot(file_path: str) -> FileSnapshot:
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return FileSnapshot(
                path=file_path,
                content_hash=_content_hash(content),
                content=content,
                exists=True,
            )
        else:
            return FileSnapshot(
                path=file_path,
                content_hash="",
                content="",
                exists=False,
            )
    except Exception:
        return FileSnapshot(
            path=file_path,
            content_hash="",
            content="",
            exists=False,
        )


def _compute_diff(before: FileSnapshot, after: FileSnapshot) -> DiffResult:
    before_lines = before.content.splitlines(keepends=True) if before.exists else []
    after_lines = after.content.splitlines(keepends=True) if after.exists else []
    diff_lines = list(difflib.unified_diff(
        before_lines, after_lines,
        fromfile=before.path, tofile=after.path,
    ))
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    return DiffResult(
        path=before.path or after.path,
        added_lines=added,
        removed_lines=removed,
        unified_diff="".join(diff_lines[:200]),
    )


class ToolHistory:
    def __init__(self, max_entries: int = 500, snapshot_dir: str = ""):
        self._max_entries = max_entries
        if not snapshot_dir:
            snapshot_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "tool_history")
        self._snapshot_dir = snapshot_dir
        self._entries: List[ToolHistoryEntry] = []
        self._lock = Lock()
        os.makedirs(self._snapshot_dir, exist_ok=True)

    def before_tool_call(self, tool_name: str, args: Dict[str, Any]) -> str:
        entry_id = uuid.uuid4().hex[:12]
        if tool_name not in _FILE_TOOLS:
            return entry_id

        affected_paths = self._extract_paths(tool_name, args)
        before_snapshots: List[FileSnapshot] = []
        for fp in affected_paths:
            snap = _take_snapshot(fp)
            before_snapshots.append(snap)
            self._save_snapshot_file(entry_id, "before", snap)

        entry = ToolHistoryEntry(
            entry_id=entry_id,
            tool_name=tool_name,
            args=args,
            before_snapshots=before_snapshots,
        )
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]
        return entry_id

    def after_tool_call(
        self,
        entry_id: str,
        tool_name: str,
        args: Dict[str, Any],
        success: bool,
        output: str = "",
        duration_ms: int = 0,
    ) -> Optional[ToolHistoryEntry]:
        with self._lock:
            entry = None
            for e in reversed(self._entries):
                if e.entry_id == entry_id:
                    entry = e
                    break

        if entry is None:
            entry = ToolHistoryEntry(
                entry_id=entry_id,
                tool_name=tool_name,
                args=args,
            )
            with self._lock:
                self._entries.append(entry)

        entry.success = success
        entry.output_preview = output[:500]
        entry.duration_ms = duration_ms

        if tool_name in _FILE_TOOLS:
            affected_paths = self._extract_paths(tool_name, args)
            after_snapshots: List[FileSnapshot] = []
            diffs: List[DiffResult] = []
            for fp in affected_paths:
                snap = _take_snapshot(fp)
                after_snapshots.append(snap)
                self._save_snapshot_file(entry_id, "after", snap)
                before_snap = None
                for bs in entry.before_snapshots:
                    if bs.path == fp:
                        before_snap = bs
                        break
                if before_snap is not None:
                    diff = _compute_diff(before_snap, snap)
                    diffs.append(diff)
            entry.after_snapshots = after_snapshots
            entry.diffs = diffs

        return entry

    def undo(self, steps: int = 1) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        with self._lock:
            file_entries = [
                e for e in self._entries
                if e.tool_name in _FILE_TOOLS and e.before_snapshots
            ]
            to_undo = file_entries[-steps:] if steps <= len(file_entries) else file_entries[:]

        for entry in reversed(to_undo):
            for before_snap in entry.before_snapshots:
                try:
                    if before_snap.exists and before_snap.content:
                        os.makedirs(os.path.dirname(before_snap.path), exist_ok=True)
                        with open(before_snap.path, "w", encoding="utf-8") as f:
                            f.write(before_snap.content)
                        results.append({
                            "path": before_snap.path,
                            "action": "restored",
                            "entryId": entry.entry_id,
                        })
                    elif not before_snap.exists:
                        if os.path.exists(before_snap.path):
                            os.remove(before_snap.path)
                        results.append({
                            "path": before_snap.path,
                            "action": "deleted",
                            "entryId": entry.entry_id,
                        })
                except Exception as e:
                    results.append({
                        "path": before_snap.path,
                        "action": "failed",
                        "error": str(e),
                        "entryId": entry.entry_id,
                    })

        with self._lock:
            ids_to_remove = {e.entry_id for e in to_undo}
            self._entries = [e for e in self._entries if e.entry_id not in ids_to_remove]

        return results

    def get_history(
        self,
        tool_name: str = "",
        limit: int = 50,
        session_id: str = "",
    ) -> List[Dict[str, Any]]:
        with self._lock:
            entries = self._entries
            if tool_name:
                entries = [e for e in entries if e.tool_name == tool_name]
            return [e.to_dict() for e in entries[-limit:]]

    def get_diffs(self, entry_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            for e in self._entries:
                if e.entry_id == entry_id:
                    return [d.to_dict() for d in e.diffs]
        return []

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._entries)
            file_ops = sum(1 for e in self._entries if e.tool_name in _FILE_TOOLS)
            success = sum(1 for e in self._entries if e.success)
            total_added = sum(d.added_lines for e in self._entries for d in e.diffs)
            total_removed = sum(d.removed_lines for e in self._entries for d in e.diffs)
        return {
            "totalCalls": total,
            "fileOperations": file_ops,
            "successRate": success / total if total else 0.0,
            "totalLinesAdded": total_added,
            "totalLinesRemoved": total_removed,
            "undoableSteps": file_ops,
        }

    def _extract_paths(self, tool_name: str, args: Dict[str, Any]) -> List[str]:
        paths: List[str] = []
        for key in ("path", "file_path", "filename", "target"):
            val = args.get(key, "")
            if val and isinstance(val, str):
                paths.append(val)
        if tool_name in ("delete_file", "file_delete") and not paths:
            for key in ("dir", "directory", "folder"):
                val = args.get(key, "")
                if val and isinstance(val, str):
                    paths.append(val)
        return paths

    def _save_snapshot_file(self, entry_id: str, phase: str, snapshot: FileSnapshot) -> None:
        snap_dir = os.path.join(self._snapshot_dir, entry_id)
        os.makedirs(snap_dir, exist_ok=True)
        fname = hashlib.md5(snapshot.path.encode("utf-8")).hexdigest()[:8]
        file_path = os.path.join(snap_dir, f"{phase}_{fname}.json")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({
                    "path": snapshot.path,
                    "contentHash": snapshot.content_hash,
                    "content": snapshot.content,
                    "exists": snapshot.exists,
                    "timestamp": snapshot.timestamp,
                }, f, ensure_ascii=False)
        except Exception:
            pass
