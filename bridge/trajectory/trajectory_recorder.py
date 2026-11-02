# -*- coding: utf-8 -*-
"""Lemon Agent 轨迹记录器 — Append-Only双写(内存+文件)
所属窗口: bridge.trajectory  品牌组件: TrajectoryRecorder
功能: 追加式记录/JSON导出/Markdown导出/文件持久化
"""
import json
import os
import threading
import time
from typing import Dict, List, Optional

from shared.tracer import TrajectoryEvent, TrajectoryEventType


class TrajectoryRecorder:
    def __init__(self, storage_path: Optional[str] = None, memory_system=None):
        self._events: List[TrajectoryEvent] = []
        self._storage_path = storage_path
        self._memory_system = memory_system
        self._lock = threading.Lock()
        if storage_path:
            os.makedirs(os.path.dirname(storage_path), exist_ok=True)

    def set_memory_system(self, memory_system) -> None:
        self._memory_system = memory_system

    def record(self, event: TrajectoryEvent) -> None:
        with self._lock:
            self._events.append(event)
        if self._memory_system:
            try:
                event_dict = {
                    "event_id": event.event_id,
                    "session_id": event.session_id,
                    "event_type": event.event_type,
                    "timestamp": event.timestamp,
                    "data": event.data,
                    "parent_event_id": event.parent_event_id,
                    "agent_id": event.agent_id,
                    "agent_name": event.agent_name,
                }
                metadata = {
                    "event_type": str(event.event_type),
                    "session_id": event.session_id,
                    "agent_id": event.agent_id,
                }
                self._memory_system.store(
                    "project",
                    f"trajectory:{event.session_id}:{event.event_id}",
                    event_dict,
                    metadata,
                )
            except Exception:
                pass
        if self._storage_path:
            try:
                line = json.dumps({
                    "event_id": event.event_id,
                    "session_id": event.session_id,
                    "event_type": event.event_type,
                    "timestamp": event.timestamp,
                    "data": event.data,
                    "parent_event_id": event.parent_event_id,
                    "agent_id": event.agent_id,
                    "agent_name": event.agent_name,
                }, default=str, ensure_ascii=False) + "\n"
                with open(self._storage_path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

    def get_trajectory(self, session_id: str) -> List[Dict[str, any]]:
        with self._lock:
            return [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "timestamp": e.timestamp,
                    "data": e.data,
                    "parent_event_id": e.parent_event_id,
                    "agent_id": e.agent_id,
                    "agent_name": e.agent_name,
                }
                for e in self._events
                if e.session_id == session_id
            ]

    def export_as_json(self, session_id: str) -> str:
        traj = self.get_trajectory(session_id)
        return json.dumps(traj, indent=2, ensure_ascii=False, default=str)

    def export_as_markdown(self, session_id: str) -> str:
        traj = self.get_trajectory(session_id)
        if not traj:
            return f"# Agent 决策轨迹 (Session: {session_id})\n\nNo events recorded.\n"

        first_ts = traj[0]["timestamp"]
        last_ts = traj[-1]["timestamp"]
        duration = last_ts - first_ts
        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(first_ts))

        _TYPE_LABELS = {
            TrajectoryEventType.CONTEXT_INJECTED: "Context",
            TrajectoryEventType.TURN_STARTED: "Turn Start",
            TrajectoryEventType.TURN_COMPLETED: "Turn End",
            TrajectoryEventType.PLAN_GENERATED: "Plan",
            TrajectoryEventType.TOOL_CALLED: "Tool Call",
            TrajectoryEventType.TOOL_COMPLETED: "Tool Done",
            TrajectoryEventType.TOOL_RESULT: "Result",
            TrajectoryEventType.FINAL_RESPONSE: "Response",
            TrajectoryEventType.FILE_CHANGED: "File Change",
            TrajectoryEventType.MODEL_RESPONSE: "Model",
            TrajectoryEventType.ERROR_OCCURRED: "Error",
            TrajectoryEventType.LOOP_DETECTED: "Loop",
            TrajectoryEventType.AGENT_COMPLETED: "Agent End",
            TrajectoryEventType.APPROVAL_REQUESTED: "Approval",
            TrajectoryEventType.SUBAGENT_SPAWNED: "SubAgent",
            TrajectoryEventType.DECISION_MADE: "Decision",
        }

        md = f"# Agent 决策轨迹 (Session: {session_id})\n\n"
        md += f"- **开始**: {start_str}\n"
        md += f"- **持续时间**: {duration:.2f}s\n"
        md += f"- **事件数**: {len(traj)}\n\n"
        md += "## 时间线\n\n"

        for i, e in enumerate(traj):
            ts = time.strftime("%H:%M:%S", time.localtime(e["timestamp"]))
            label = _TYPE_LABELS.get(e["event_type"], e["event_type"])
            data_str = json.dumps(e["data"], ensure_ascii=False, default=str)
            if len(data_str) > 100:
                data_str = data_str[:97] + "..."
            md += f"### Step {i + 1}: {label}\n\n"
            md += f"- **Time**: {ts}\n"
            md += f"- **Type**: `{e['event_type']}`\n"
            if e.get("agent_name"):
                md += f"- **Agent**: {e['agent_name']}\n"
            md += f"- **Data**: `{data_str}`\n\n"

        md += "---\n"
        md += f"*导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n"
        return md

    def get_file_changes(self, session_id: str) -> List[Dict[str, any]]:
        with self._lock:
            return [
                e.data for e in self._events
                if e.session_id == session_id
                and e.event_type == TrajectoryEventType.FILE_CHANGED
            ]

    def get_plans(self, session_id: str) -> List[Dict[str, any]]:
        with self._lock:
            return [
                e.data for e in self._events
                if e.session_id == session_id
                and e.event_type == TrajectoryEventType.PLAN_GENERATED
            ]

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            self._events = [e for e in self._events if e.session_id != session_id]
