"""
Trajectory Tracker Service - wraps Tracer with query/export/replay capabilities.
Provides session trajectory retrieval and Markdown decision report export.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from shared.tracer import Tracer, TrajectoryEventType, TrajectoryQuery, TrajectoryReplay


class TrajectoryTrackerService:
    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer
        self._query = TrajectoryQuery(tracer)
        self._replay = TrajectoryReplay(tracer)

    def get_trajectory(self, session_id: str) -> Dict[str, Any]:
        events = self._tracer.get_session(session_id)
        return {
            "sessionId": session_id,
            "eventCount": len(events),
            "events": [
                {
                    "eventId": e.event_id,
                    "eventType": e.event_type,
                    "timestamp": e.timestamp,
                    "data": e.data,
                    "parentEventId": e.parent_event_id,
                }
                for e in events
            ],
        }

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        event = self._tracer.get_event(event_id)
        if event is None:
            return None
        return {
            "eventId": event.event_id,
            "sessionId": event.session_id,
            "eventType": event.event_type,
            "timestamp": event.timestamp,
            "data": event.data,
            "parentEventId": event.parent_event_id,
        }

    def query_by_type(self, session_id: str, event_type: str) -> List[Dict[str, Any]]:
        events = self._query.by_type(session_id, event_type)
        return [
            {
                "eventId": e.event_id,
                "eventType": e.event_type,
                "timestamp": e.timestamp,
                "data": e.data,
                "parentEventId": e.parent_event_id,
            }
            for e in events
        ]

    def query_by_keyword(self, session_id: str, keyword: str) -> List[Dict[str, Any]]:
        events = self._query.by_keyword(session_id, keyword)
        return [
            {
                "eventId": e.event_id,
                "eventType": e.event_type,
                "timestamp": e.timestamp,
                "data": e.data,
                "parentEventId": e.parent_event_id,
            }
            for e in events
        ]

    def get_stats(self, session_id: str) -> Dict[str, Any]:
        counts = self._query.count(session_id)
        events = self._tracer.get_session(session_id)
        duration = 0.0
        if len(events) >= 2:
            duration = events[-1].timestamp - events[0].timestamp
        return {
            "sessionId": session_id,
            "eventCount": len(events),
            "duration": round(duration, 3),
            "typeCounts": counts,
        }

    def compare_sessions(self, session_a: str, session_b: str) -> Dict[str, Any]:
        return self._replay.compare(session_a, session_b)

    def step_to(self, session_id: str, step_index: int) -> Dict[str, Any]:
        return self._replay.step_to(session_id, step_index)

    def export_markdown(self, session_id: str) -> str:
        events = self._tracer.get_session(session_id)
        if not events:
            return f"# Session {session_id}\n\nNo trajectory events recorded.\n"

        start_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(events[0].timestamp))
        end_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(events[-1].timestamp))
        duration = events[-1].timestamp - events[0].timestamp

        lines: List[str] = [
            f"# Decision Trajectory: {session_id}",
            "",
            f"- **Start**: {start_time}",
            f"- **End**: {end_time}",
            f"- **Duration**: {duration:.2f}s",
            f"- **Events**: {len(events)}",
            "",
            "## Timeline",
            "",
        ]

        type_labels = {
            TrajectoryEventType.CONTEXT_INJECTED: "Context",
            TrajectoryEventType.TOOL_CALLED: "Tool Call",
            TrajectoryEventType.TOOL_RESULT: "Tool Result",
            TrajectoryEventType.MODEL_RESPONSE: "Response",
            TrajectoryEventType.ERROR_OCCURRED: "Error",
            TrajectoryEventType.APPROVAL_REQUESTED: "Approval",
            TrajectoryEventType.SUBAGENT_SPAWNED: "SubAgent",
        }

        for i, event in enumerate(events):
            ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
            ms = f"{event.timestamp % 1:.3f}"[1:]
            label = type_labels.get(event.event_type, event.event_type)
            parent_ref = f" (parent: {event.parent_event_id[:8]}...)" if event.parent_event_id else ""
            lines.append(f"### Step {i + 1}: {label}{parent_ref}")
            lines.append("")
            lines.append(f"- **Time**: {ts}{ms}")
            lines.append(f"- **Event ID**: `{event.event_id}`")
            lines.append(f"- **Type**: `{event.event_type}`")

            if event.event_type == TrajectoryEventType.TOOL_CALLED:
                skill = event.data.get("skill_name", "")
                args = event.data.get("args", {})
                lines.append(f"- **Skill**: {skill}")
                if args:
                    args_str = str(args)
                    if len(args_str) > 200:
                        args_str = args_str[:197] + "..."
                    lines.append(f"- **Args**: `{args_str}`")
            elif event.event_type == TrajectoryEventType.TOOL_RESULT:
                success = event.data.get("success", False)
                preview = event.data.get("output_preview", "")
                lines.append(f"- **Success**: {success}")
                if preview:
                    lines.append(f"- **Result**: {preview}")
            elif event.event_type == TrajectoryEventType.MODEL_RESPONSE:
                length = event.data.get("content_length", 0)
                tool_count = event.data.get("tool_call_count", 0)
                lines.append(f"- **Output Length**: {length} chars")
                lines.append(f"- **Tool Calls**: {tool_count}")
            elif event.event_type == TrajectoryEventType.ERROR_OCCURRED:
                err_type = event.data.get("error_type", "")
                err_msg = event.data.get("error", event.data.get("loop_type", ""))
                lines.append(f"- **Error Type**: {err_type}")
                lines.append(f"- **Detail**: {err_msg}")
            elif event.event_type == TrajectoryEventType.CONTEXT_INJECTED:
                msg_count = event.data.get("message_count", 0)
                model = event.data.get("model", "")
                lines.append(f"- **Messages**: {msg_count}")
                if model:
                    lines.append(f"- **Model**: {model}")
            elif event.event_type == TrajectoryEventType.APPROVAL_REQUESTED:
                skill = event.data.get("skill_name", "")
                reason = event.data.get("reason", "")
                lines.append(f"- **Skill**: {skill}")
                if reason:
                    lines.append(f"- **Reason**: {reason}")

            lines.append("")

        lines.append("---")
        lines.append(f"*Exported at {time.strftime('%Y-%m-%d %H:%M:%S')}*")

        return "\n".join(lines)

    def get_decision_chain(self, session_id: str) -> List[Dict[str, Any]]:
        events = self._tracer.get_session(session_id)
        chain: List[Dict[str, Any]] = []
        for event in events:
            chain.append({
                "eventId": event.event_id,
                "eventType": event.event_type,
                "parentEventId": event.parent_event_id,
                "timestamp": event.timestamp,
                "summary": self._summarize_event(event),
            })
        return chain

    @staticmethod
    def _summarize_event(event: Any) -> str:
        d = event.data
        if event.event_type == TrajectoryEventType.TOOL_CALLED:
            return f"Called {d.get('skill_name', '?')}"
        if event.event_type == TrajectoryEventType.TOOL_RESULT:
            success = d.get("success", False)
            return f"Result: {'OK' if success else 'FAIL'}"
        if event.event_type == TrajectoryEventType.MODEL_RESPONSE:
            return f"Response ({d.get('content_length', 0)} chars)"
        if event.event_type == TrajectoryEventType.ERROR_OCCURRED:
            return f"Error: {d.get('error_type', d.get('loop_type', 'unknown'))}"
        if event.event_type == TrajectoryEventType.CONTEXT_INJECTED:
            return f"Context ({d.get('message_count', 0)} msgs)"
        if event.event_type == TrajectoryEventType.APPROVAL_REQUESTED:
            return f"Approval: {d.get('skill_name', '?')}"
        if event.event_type == TrajectoryEventType.SUBAGENT_SPAWNED:
            return f"SubAgent: {d.get('agent_id', '?')}"
        return str(d)[:80]
