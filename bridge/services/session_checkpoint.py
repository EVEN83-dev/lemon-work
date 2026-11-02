"""
B-P3-004: Session Checkpoint Service

Save/restore/compress session state for recovery
and long-session management.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Checkpoint:
    id: str
    session_id: str
    timestamp: float
    message_count: int
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "timestamp": self.timestamp,
            "messageCount": self.message_count,
            "summary": self.summary,
        }


class SessionCheckpointService:
    AUTO_SAVE_INTERVAL: int = 10
    COMPRESS_THRESHOLD: int = 50

    def __init__(self, data_dir: str = "") -> None:
        if not data_dir:
            data_dir = str(Path(__file__).parent.parent / "data" / "checkpoints")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._checkpoints: Dict[str, Checkpoint] = {}
        self._load_all()

    def _load_all(self) -> None:
        for f in self._data_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                cp = Checkpoint(
                    id=data["id"],
                    session_id=data["sessionId"],
                    timestamp=data["timestamp"],
                    message_count=data["messageCount"],
                    summary=data.get("summary", ""),
                    data=data.get("data", {}),
                )
                self._checkpoints[cp.id] = cp
            except Exception:
                pass

    def _save(self, cp: Checkpoint) -> None:
        path = self._data_dir / f"{cp.id}.json"
        data = {
            "id": cp.id,
            "sessionId": cp.session_id,
            "timestamp": cp.timestamp,
            "messageCount": cp.message_count,
            "summary": cp.summary,
            "data": cp.data,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save(self, session_id: str, message_count: int, summary: str = "",
             data: Optional[Dict[str, Any]] = None) -> Checkpoint:
        cp_id = f"cp-{int(time.time() * 1000)}"
        cp = Checkpoint(
            id=cp_id,
            session_id=session_id,
            timestamp=time.time(),
            message_count=message_count,
            summary=summary,
            data=data or {},
        )
        self._checkpoints[cp.id] = cp
        self._save(cp)
        return cp

    def restore(self, checkpoint_id: str) -> Optional[Checkpoint]:
        return self._checkpoints.get(checkpoint_id)

    def list_checkpoints(self, session_id: str = "") -> List[Dict[str, Any]]:
        cps = list(self._checkpoints.values())
        if session_id:
            cps = [c for c in cps if c.session_id == session_id]
        cps.sort(key=lambda c: c.timestamp, reverse=True)
        return [c.to_dict() for c in cps]

    def should_auto_save(self, message_count: int) -> bool:
        return message_count > 0 and message_count % self.AUTO_SAVE_INTERVAL == 0

    def should_compress(self, message_count: int) -> bool:
        return message_count >= self.COMPRESS_THRESHOLD

    def compress(self, session_id: str, message_count: int) -> Checkpoint:
        summary = f"\u4f1a\u8bdd\u5df2\u538b\u7f29 ({message_count} \u6761\u6d88\u606f)"
        return self.save(session_id, message_count, summary)

    def delete(self, checkpoint_id: str) -> bool:
        cp = self._checkpoints.pop(checkpoint_id, None)
        if cp is None:
            return False
        path = self._data_dir / f"{cp.id}.json"
        if path.exists():
            path.unlink()
        return True
