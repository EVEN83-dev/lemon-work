# -*- coding: utf-8 -*-
"""364章 T3.2: 断点续跑 — 长任务检查点保存/恢复"""

import json
import os
import time
from typing import Any, Dict, Optional
from pathlib import Path


class CheckpointManager:
    def __init__(self, checkpoint_dir: str = "", max_checkpoints: int = 10):
        if not checkpoint_dir:
            checkpoint_dir = os.path.join(os.getcwd(), ".checkpoints")
        self.checkpoint_dir = os.path.expanduser(checkpoint_dir)
        self.max_checkpoints = max_checkpoints
        os.makedirs(self.checkpoint_dir, exist_ok=True)

    def save(self, task_id: str, step: int, state: Dict,
             metadata: Optional[Dict] = None) -> str:
        cp = {
            "task_id": task_id,
            "step": step,
            "state": state,
            "metadata": metadata or {},
            "timestamp": time.time(),
        }
        path = os.path.join(self.checkpoint_dir, f"{task_id}_{step:04d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cp, f, ensure_ascii=False, indent=2)
        self._cleanup(task_id)
        return path

    def load_latest(self, task_id: str) -> Optional[Dict]:
        cp_files = sorted(
            [f for f in os.listdir(self.checkpoint_dir) if f.startswith(task_id)],
            reverse=True,
        )
        if not cp_files:
            return None
        path = os.path.join(self.checkpoint_dir, cp_files[0])
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_at_step(self, task_id: str, step: int) -> Optional[Dict]:
        fname = f"{task_id}_{step:04d}.json"
        path = os.path.join(self.checkpoint_dir, fname)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_checkpoints(self, task_id: str = "") -> list:
        result = []
        for f in sorted(os.listdir(self.checkpoint_dir)):
            if not f.endswith(".json"):
                continue
            if task_id and not f.startswith(task_id):
                continue
            path = os.path.join(self.checkpoint_dir, f)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    cp = json.load(fh)
                    result.append({"file": f, "step": cp.get("step"),
                                   "timestamp": cp.get("timestamp")})
            except (json.JSONDecodeError, OSError):
                pass
        return result

    def delete(self, task_id: str) -> int:
        removed = 0
        for f in os.listdir(self.checkpoint_dir):
            if f.startswith(task_id) and f.endswith(".json"):
                os.remove(os.path.join(self.checkpoint_dir, f))
                removed += 1
        return removed

    def _cleanup(self, task_id: str):
        files = sorted(f for f in os.listdir(self.checkpoint_dir)
                       if f.startswith(task_id) and f.endswith(".json"))
        while len(files) > self.max_checkpoints:
            os.remove(os.path.join(self.checkpoint_dir, files.pop(0)))
