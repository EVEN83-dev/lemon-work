import html
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


class TrajectoryEventType:
    CONTEXT_INJECTED = "context_injected"
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    PLAN_GENERATED = "plan_generated"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    TOOL_COMPLETED = "tool_completed"
    FINAL_RESPONSE = "final_response"
    FILE_CHANGED = "file_changed"
    MODEL_RESPONSE = "model_response"
    SUBAGENT_SPAWNED = "subagent_spawned"
    SUBAGENT_COMPLETED = "subagent_completed"
    DECISION_MADE = "decision_made"
    DECISION_BRANCH = "decision_branch"
    ERROR_OCCURRED = "error_occurred"
    APPROVAL_REQUESTED = "approval_requested"
    LOOP_DETECTED = "loop_detected"
    AGENT_COMPLETED = "agent_completed"


@dataclass
class TrajectoryEvent:
    event_id: str
    session_id: str
    event_type: str
    timestamp: float
    data: dict
    parent_event_id: str = ""
    agent_id: str = ""
    agent_name: str = ""

    @staticmethod
    def create(
        session_id: str,
        event_type: str,
        data: dict,
        parent_event_id: str = "",
        agent_id: str = "",
        agent_name: str = "",
    ) -> "TrajectoryEvent":
        return TrajectoryEvent(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            event_type=event_type,
            timestamp=time.time(),
            data=data,
            parent_event_id=parent_event_id,
            agent_id=agent_id,
            agent_name=agent_name,
        )


_MAX_EVENTS_PER_SESSION = 10000


class Tracer:
    def __init__(self) -> None:
        self._events: Dict[str, List[TrajectoryEvent]] = {}
        self._lock = threading.Lock()
        self._agent_hierarchy: Dict[str, str] = {}

    def trace(
        self,
        session_id: str,
        event_type: str,
        data: dict,
        parent_event_id: str = "",
        agent_id: str = "",
        agent_name: str = "",
    ) -> TrajectoryEvent:
        event = TrajectoryEvent.create(
            session_id, event_type, data, parent_event_id, agent_id, agent_name
        )
        with self._lock:
            if session_id not in self._events:
                self._events[session_id] = []
            self._events[session_id].append(event)
            if len(self._events[session_id]) > _MAX_EVENTS_PER_SESSION:
                self._events[session_id] = self._events[session_id][-_MAX_EVENTS_PER_SESSION:]
            if agent_id and event_type == TrajectoryEventType.SUBAGENT_SPAWNED:
                child_id = data.get("child_agent_id", "")
                if child_id:
                    self._agent_hierarchy[child_id] = agent_id
        return event

    def get_session(self, session_id: str) -> List[TrajectoryEvent]:
        with self._lock:
            events = list(self._events.get(session_id, []))
        events.sort(key=lambda e: e.timestamp)
        return events

    def get_event(self, event_id: str) -> Optional[TrajectoryEvent]:
        with self._lock:
            for events in self._events.values():
                for event in events:
                    if event.event_id == event_id:
                        return event
        return None

    def get_recent(self, session_id: str, limit: int = 50) -> List[TrajectoryEvent]:
        with self._lock:
            events = list(self._events.get(session_id, []))
        events.sort(key=lambda e: e.timestamp)
        return events[-limit:]

    def get_agent_children(self, session_id: str, agent_id: str) -> List[TrajectoryEvent]:
        with self._lock:
            events = list(self._events.get(session_id, []))
        return [e for e in events if e.agent_id == agent_id]

    def get_agent_hierarchy(self, session_id: str) -> dict:
        with self._lock:
            events = list(self._events.get(session_id, []))
        spawn_events = [e for e in events if e.event_type == TrajectoryEventType.SUBAGENT_SPAWNED]
        hierarchy: Dict[str, List[str]] = {}
        agent_names: Dict[str, str] = {}
        for e in events:
            if e.agent_id:
                agent_names[e.agent_id] = e.agent_name or e.agent_id
        for sp in spawn_events:
            parent = sp.agent_id or "root"
            child = sp.data.get("child_agent_id", "")
            if child:
                if parent not in hierarchy:
                    hierarchy[parent] = []
                hierarchy[parent].append(child)
                if child not in hierarchy:
                    hierarchy[child] = []
        if hierarchy and "root" not in hierarchy:
            roots = set(hierarchy.keys()) - {c for children in hierarchy.values() for c in children}
            if roots:
                hierarchy["root"] = list(roots)
        return {"hierarchy": hierarchy, "agent_names": agent_names}

    def get_by_agent(self, session_id: str, agent_id: str) -> List[TrajectoryEvent]:
        with self._lock:
            events = list(self._events.get(session_id, []))
        return [e for e in sorted(events, key=lambda e: e.timestamp) if e.agent_id == agent_id]


class TrajectoryQuery:
    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    def by_type(self, session_id: str, event_type: str) -> List[TrajectoryEvent]:
        events = self._tracer.get_session(session_id)
        return [e for e in events if e.event_type == event_type]

    def by_time_range(
        self, session_id: str, start: float, end: float
    ) -> List[TrajectoryEvent]:
        events = self._tracer.get_session(session_id)
        return [e for e in events if start <= e.timestamp <= end]

    def by_tool(self, session_id: str, tool_id: str) -> List[TrajectoryEvent]:
        events = self._tracer.get_session(session_id)
        return [
            e
            for e in events
            if e.data.get("tool_id") == tool_id
        ]

    def by_keyword(self, session_id: str, keyword: str) -> List[TrajectoryEvent]:
        events = self._tracer.get_session(session_id)
        keyword_lower = keyword.lower()
        results: List[TrajectoryEvent] = []
        for e in events:
            for value in e.data.values():
                if isinstance(value, str) and keyword_lower in value.lower():
                    results.append(e)
                    break
                text = json.dumps(value, default=str)
                if keyword_lower in text.lower():
                    results.append(e)
                    break
        return results

    def count(self, session_id: str) -> dict:
        events = self._tracer.get_session(session_id)
        counts: Dict[str, int] = {}
        for e in events:
            counts[e.event_type] = counts.get(e.event_type, 0) + 1
        return counts

    def by_agent(self, session_id: str, agent_id: str) -> List[TrajectoryEvent]:
        events = self._tracer.get_session(session_id)
        return [e for e in events if e.agent_id == agent_id]

    def decisions(self, session_id: str) -> List[TrajectoryEvent]:
        events = self._tracer.get_session(session_id)
        return [e for e in events if e.event_type in (
            TrajectoryEventType.DECISION_MADE,
            TrajectoryEventType.DECISION_BRANCH,
        )]


class TrajectoryReplay:
    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    def replay(
        self,
        session_id: str,
        callback: Callable[[TrajectoryEvent, int], None],
    ) -> None:
        events = self._tracer.get_session(session_id)
        for i, event in enumerate(events):
            callback(event, i)

    def step_to(self, session_id: str, step_index: int) -> dict:
        events = self._tracer.get_session(session_id)
        if step_index < 0 or step_index >= len(events):
            return {}
        snapshot: dict = {
            "session_id": session_id,
            "step_index": step_index,
            "total_steps": len(events),
            "events": [],
            "tools_called": [],
            "errors": [],
            "context": [],
        }
        for i in range(step_index + 1):
            event = events[i]
            snapshot["events"].append(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "timestamp": event.timestamp,
                    "data": event.data,
                    "parent_event_id": event.parent_event_id,
                }
            )
            if event.event_type == TrajectoryEventType.TOOL_CALLED:
                snapshot["tools_called"].append(event.data)
            elif event.event_type == TrajectoryEventType.ERROR_OCCURRED:
                snapshot["errors"].append(event.data)
            elif event.event_type == TrajectoryEventType.CONTEXT_INJECTED:
                snapshot["context"].append(event.data)
        return snapshot

    def compare(self, session_id_a: str, session_id_b: str) -> dict:
        events_a = self._tracer.get_session(session_id_a)
        events_b = self._tracer.get_session(session_id_b)

        def _type_distribution(events: List[TrajectoryEvent]) -> Dict[str, int]:
            dist: Dict[str, int] = {}
            for e in events:
                dist[e.event_type] = dist.get(e.event_type, 0) + 1
            return dist

        dist_a = _type_distribution(events_a)
        dist_b = _type_distribution(events_b)

        duration_a = 0.0
        if len(events_a) >= 2:
            duration_a = events_a[-1].timestamp - events_a[0].timestamp
        duration_b = 0.0
        if len(events_b) >= 2:
            duration_b = events_b[-1].timestamp - events_b[0].timestamp

        divergence_points: List[dict] = []
        min_len = min(len(events_a), len(events_b))
        for i in range(min_len):
            if events_a[i].event_type != events_b[i].event_type:
                divergence_points.append(
                    {
                        "step": i,
                        "type_a": events_a[i].event_type,
                        "type_b": events_b[i].event_type,
                    }
                )
        if len(events_a) != len(events_b):
            divergence_points.append(
                {
                    "step": min_len,
                    "type_a": "end" if len(events_a) <= min_len else events_a[min_len].event_type,
                    "type_b": "end" if len(events_b) <= min_len else events_b[min_len].event_type,
                }
            )

        return {
            "session_a": session_id_a,
            "session_b": session_id_b,
            "count_a": len(events_a),
            "count_b": len(events_b),
            "type_distribution_a": dist_a,
            "type_distribution_b": dist_b,
            "duration_a": duration_a,
            "duration_b": duration_b,
            "divergence_points": divergence_points,
        }


_EVENT_TYPE_COLORS: Dict[str, str] = {
    TrajectoryEventType.TOOL_CALLED: "Lemon.ACCENT_BLUE",
    TrajectoryEventType.TOOL_RESULT: "Lemon.ACCENT_GREEN",
    TrajectoryEventType.MODEL_RESPONSE: "Lemon.BRAND_ORANGE_LIGHT",
    TrajectoryEventType.ERROR_OCCURRED: "Lemon.ACCENT_RED",
    TrajectoryEventType.CONTEXT_INJECTED: "#9c27b0",
    TrajectoryEventType.SUBAGENT_SPAWNED: "Lemon.ACCENT_BLUE",
    TrajectoryEventType.SUBAGENT_COMPLETED: "#26a69a",
    TrajectoryEventType.DECISION_MADE: "Lemon.ACCENT_PINK",
    TrajectoryEventType.DECISION_BRANCH: "Lemon.ACCENT_PURPLE",
    TrajectoryEventType.APPROVAL_REQUESTED: "#ffeb3b",
}

_EVENT_TYPE_ICONS: Dict[str, str] = {
    TrajectoryEventType.CONTEXT_INJECTED: "&#x1F4CB;",
    TrajectoryEventType.TOOL_CALLED: "&#x1F527;",
    TrajectoryEventType.TOOL_RESULT: "&#x2705;",
    TrajectoryEventType.MODEL_RESPONSE: "&#x1F916;",
    TrajectoryEventType.SUBAGENT_SPAWNED: "&#x1F465;",
    TrajectoryEventType.SUBAGENT_COMPLETED: "&#x2705;",
    TrajectoryEventType.DECISION_MADE: "&#x1F9E9;",
    TrajectoryEventType.DECISION_BRANCH: "&#x1F500;",
    TrajectoryEventType.ERROR_OCCURRED: "&#x26A0;",
    TrajectoryEventType.APPROVAL_REQUESTED: "&#x1F6E1;",
}


class TrajectoryView:
    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    def render_timeline(self, session_id: str) -> str:
        events = self._tracer.get_session(session_id)
        if not events:
            return '<div class="tv-timeline"><p style="color:rgba(255,255,255,0.5);text-align:center;">No events found.</p></div>'

        items_html: List[str] = []
        for event in events:
            color = _EVENT_TYPE_COLORS.get(event.event_type, "Lemon.SECONDARY")
            icon = _EVENT_TYPE_ICONS.get(event.event_type, "&#x25CF;")
            ts_str = html.escape(f"{event.timestamp:.3f}")
            type_str = html.escape(event.event_type)
            summary = self._summarize_data(event.data)
            parent_attr = (
                f' data-parent="{html.escape(event.parent_event_id)}"'
                if event.parent_event_id
                else ""
            )
            agent_attr = (
                f' data-agent="{html.escape(event.agent_id)}"'
                if event.agent_id
                else ""
            )
            agent_label = ""
            if event.agent_name:
                agent_label = (
                    f'<span class="tv-agent" style="color:Lemon.ACCENT_BLUE;font-size:10px;'
                    f'background:rgba(0,188,212,0.12);padding:0 4px;border-radius:2px;">'
                    f'{html.escape(event.agent_name)}</span>'
                )
            items_html.append(
                f'<div class="tv-event" data-event-id="{html.escape(event.event_id)}"'
                f' data-type="{type_str}"{parent_attr}{agent_attr}'
                f' style="border-left:3px solid {color};">'
                f'<span class="tv-icon">{icon}</span>'
                f'<span class="tv-time">{ts_str}</span>'
                f'<span class="tv-type" style="color:{color};">{type_str}</span>'
                f'{agent_label}'
                f'<span class="tv-summary">{summary}</span>'
                f"</div>"
            )

        items = "\n".join(items_html)
        return (
            '<div class="tv-timeline">'
            f"{items}"
            "</div>"
        )

    def render_detail(self, event_id: str) -> str:
        event = self._tracer.get_event(event_id)
        if event is None:
            return '<div class="tv-detail"><p style="color:rgba(255,255,255,0.5);">Event not found.</p></div>'

        color = _EVENT_TYPE_COLORS.get(event.event_type, "Lemon.SECONDARY")
        icon = _EVENT_TYPE_ICONS.get(event.event_type, "&#x25CF;")
        data_json = html.escape(json.dumps(event.data, indent=2, default=str))
        parent_html = (
            f'<div class="tv-field"><span class="tv-label">Parent:</span>'
            f'<span class="tv-value">{html.escape(event.parent_event_id)}</span></div>'
            if event.parent_event_id
            else ""
        )

        return (
            '<div class="tv-detail">'
            f'<div class="tv-header" style="border-left:3px solid {color};">'
            f'<span class="tv-icon">{icon}</span>'
            f'<span class="tv-type" style="color:{color};">{html.escape(event.event_type)}</span>'
            f"</div>"
            f'<div class="tv-field"><span class="tv-label">Event ID:</span>'
            f'<span class="tv-value">{html.escape(event.event_id)}</span></div>'
            f'<div class="tv-field"><span class="tv-label">Session:</span>'
            f'<span class="tv-value">{html.escape(event.session_id)}</span></div>'
            f'<div class="tv-field"><span class="tv-label">Timestamp:</span>'
            f'<span class="tv-value">{html.escape(f"{event.timestamp:.6f}")}</span></div>'
            f"{parent_html}"
            f'<div class="tv-field"><span class="tv-label">Data:</span></div>'
            f'<pre class="tv-data-pre">{data_json}</pre>'
            "</div>"
        )

    @staticmethod
    def _summarize_data(data: dict) -> str:
        parts: List[str] = []
        for key in ("tool_id", "model", "error_msg", "message"):
            if key in data:
                val = str(data[key])
                if len(val) > 80:
                    val = val[:77] + "..."
                parts.append(f"{key}={val}")
        if not parts and data:
            first_key = next(iter(data))
            val = str(data[first_key])
            if len(val) > 60:
                val = val[:57] + "..."
            parts.append(f"{first_key}={val}")
        summary = "; ".join(parts)
        return html.escape(summary)


_STYLE_CSS = """
<style>
.tv-timeline,.tv-detail{
    font-family:'SF Mono','Fira Code','Consolas',monospace;
    color:rgba(255,255,255,0.87);
    text-shadow:0 0 8px rgba(100,180,255,0.15);
}
.tv-timeline{
    display:flex;flex-direction:column;gap:4px;
    padding:8px;
    background:rgba(5,5,8,0.15);
    border-radius:6px;
}
.tv-event{
    display:flex;align-items:center;gap:8px;
    padding:6px 10px;
    background:rgba(5,5,8,0.15);
    border-radius:4px;
    pointer-events:auto;
    cursor:pointer;
    transition:background 0.15s;
}
.tv-event:hover{background:rgba(255,255,255,0.06);}
.tv-icon{font-size:14px;flex-shrink:0;}
.tv-time{color:rgba(255,255,255,0.45);font-size:11px;flex-shrink:0;min-width:90px;}
.tv-type{font-size:12px;font-weight:600;flex-shrink:0;min-width:120px;}
.tv-summary{font-size:11px;color:rgba(255,255,255,0.6);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tv-detail{
    padding:12px;
    background:rgba(5,5,8,0.15);
    border-radius:6px;
}
.tv-header{
    display:flex;align-items:center;gap:8px;
    padding:6px 10px;margin-bottom:8px;
    background:rgba(5,5,8,0.15);border-radius:4px;
}
.tv-field{display:flex;gap:6px;padding:3px 0;font-size:12px;}
.tv-label{color:rgba(255,255,255,0.5);min-width:80px;}
.tv-value{color:rgba(255,255,255,0.8);}
.tv-data-pre{
    background:rgba(5,5,8,0.25);
    border:1px solid rgba(255,255,255,0.08);
    border-radius:4px;
    padding:8px;
    font-size:11px;
    color:rgba(255,255,255,0.7);
    overflow-x:auto;
    margin:4px 0 0 0;
    pointer-events:auto;
}
</style>
"""


def render_full_timeline(tracer: Tracer, session_id: str) -> str:
    view = TrajectoryView(tracer)
    body = view.render_timeline(session_id)
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'>{_STYLE_CSS}</head><body style='background:#0a0a0f;'>{body}</body></html>"


def render_full_detail(tracer: Tracer, event_id: str) -> str:
    view = TrajectoryView(tracer)
    body = view.render_detail(event_id)
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'>{_STYLE_CSS}</head><body style='background:#0a0a0f;'>{body}</body></html>"


class DecisionTreeView:
    _AGENT_COLORS = [
        "Lemon.ACCENT_BLUE", "Lemon.ACCENT_PINK", "Lemon.ACCENT_GREEN", "Lemon.BRAND_ORANGE_LIGHT", "#9c27b0",
        "Lemon.ACCENT_BLUE", "#ffeb3b", "#26a69a", "Lemon.ACCENT_RED", "Lemon.ACCENT_PURPLE",
    ]

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    def render_tree(self, session_id: str) -> str:
        hierarchy = self._tracer.get_agent_hierarchy(session_id)
        events = self._tracer.get_session(session_id)
        if not events:
            return '<div class="dt-tree"><p style="color:rgba(255,255,255,0.5);text-align:center;">No events for decision tree.</p></div>'

        h = hierarchy.get("hierarchy", {})
        names = hierarchy.get("agent_names", {})

        tree_html = self._render_agent_node("root", h, names, events, 0)
        return f'<div class="dt-tree">{tree_html}</div>'

    def _render_agent_node(
        self, agent_id: str, hierarchy: Dict[str, List[str]],
        names: Dict[str, str], all_events: List[TrajectoryEvent], depth: int,
    ) -> str:
        color_idx = hash(agent_id) % len(self._AGENT_COLORS)
        color = self._AGENT_COLORS[color_idx]
        indent = depth * 24

        display_name = names.get(agent_id, agent_id)
        agent_events = [e for e in all_events if e.agent_id == agent_id] if agent_id != "root" else []

        header_html = (
            f'<div class="dt-agent" style="margin-left:{indent}px;">'
            f'<div class="dt-agent-header" style="border-left:3px solid {color};">'
            f'<span class="dt-agent-icon" style="color:{color};">&#x1F465;</span>'
            f'<span class="dt-agent-name" style="color:{color};">{html.escape(display_name)}</span>'
            f'<span class="dt-agent-count">{len(agent_events)} events</span>'
            f"</div>"
        )

        events_html = ""
        for event in agent_events[:20]:
            evt_color = _EVENT_TYPE_COLORS.get(event.event_type, "Lemon.SECONDARY")
            evt_icon = _EVENT_TYPE_ICONS.get(event.event_type, "&#x25CF;")
            summary = TrajectoryView._summarize_data(event.data)
            events_html += (
                f'<div class="dt-event" style="border-left:2px solid {evt_color};margin-left:{indent + 12}px;">'
                f'<span class="dt-event-icon">{evt_icon}</span>'
                f'<span class="dt-event-type" style="color:{evt_color};">{html.escape(event.event_type)}</span>'
                f'<span class="dt-event-summary">{summary}</span>'
                f"</div>"
            )

        children = hierarchy.get(agent_id, [])
        children_html = ""
        for child_id in children:
            children_html += self._render_agent_node(
                child_id, hierarchy, names, all_events, depth + 1
            )

        return f"{header_html}{events_html}{children_html}</div>"

    def render_decision_paths(self, session_id: str) -> str:
        events = self._tracer.get_session(session_id)
        decisions = [e for e in events if e.event_type == TrajectoryEventType.DECISION_MADE]
        branches = [e for e in events if e.event_type == TrajectoryEventType.DECISION_BRANCH]

        if not decisions and not branches:
            return '<div class="dt-paths"><p style="color:rgba(255,255,255,0.5);text-align:center;">No decisions recorded.</p></div>'

        items_html: List[str] = []
        for d in decisions:
            agent_label = html.escape(d.agent_name) if d.agent_name else ""
            choice = html.escape(d.data.get("choice", "?"))
            rationale = html.escape(d.data.get("rationale", ""))
            items_html.append(
                f'<div class="dt-decision">'
                f'<span class="dt-decision-icon" style="color:Lemon.ACCENT_PINK;">&#x1F9E9;</span>'
                f'<span class="dt-decision-agent">{agent_label}</span>'
                f'<span class="dt-decision-choice" style="color:Lemon.ACCENT_PINK;">{choice}</span>'
                f'<span class="dt-decision-rationale">{rationale}</span>'
                f"</div>"
            )

        for b in branches:
            branch_path = html.escape(b.data.get("path", ""))
            agent_label = html.escape(b.agent_name) if b.agent_name else ""
            items_html.append(
                f'<div class="dt-branch">'
                f'<span class="dt-branch-icon" style="color:Lemon.ACCENT_PURPLE;">&#x1F500;</span>'
                f'<span class="dt-branch-agent">{agent_label}</span>'
                f'<span class="dt-branch-path" style="color:Lemon.ACCENT_PURPLE;">{branch_path}</span>'
                f"</div>"
            )

        return f'<div class="dt-paths">{"".join(items_html)}</div>'


_DECISION_TREE_CSS = """
<style>
.dt-tree,.dt-paths{
    font-family:'SF Mono','Fira Code','Consolas',monospace;
    color:rgba(255,255,255,0.87);
    text-shadow:0 0 8px rgba(100,180,255,0.15);
}
.dt-tree{
    display:flex;flex-direction:column;gap:2px;
    padding:8px;
    background:rgba(5,5,8,0.15);
    border-radius:6px;
}
.dt-agent-header{
    display:flex;align-items:center;gap:6px;
    padding:4px 8px;
    background:rgba(5,5,8,0.15);
    border-radius:3px;
}
.dt-agent-icon{font-size:13px;}
.dt-agent-name{font-size:12px;font-weight:600;}
.dt-agent-count{font-size:10px;color:rgba(255,255,255,0.4);}
.dt-event{
    display:flex;align-items:center;gap:6px;
    padding:3px 8px;
    background:rgba(5,5,8,0.1);
    border-radius:2px;
}
.dt-event-icon{font-size:12px;}
.dt-event-type{font-size:11px;font-weight:600;min-width:100px;}
.dt-event-summary{font-size:10px;color:rgba(255,255,255,0.5);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dt-paths{
    display:flex;flex-direction:column;gap:4px;
    padding:8px;
    background:rgba(5,5,8,0.15);
    border-radius:6px;
}
.dt-decision,.dt-branch{
    display:flex;align-items:center;gap:6px;
    padding:4px 8px;
    background:rgba(5,5,8,0.1);
    border-radius:3px;
}
.dt-decision-icon,.dt-branch-icon{font-size:13px;}
.dt-decision-agent,.dt-branch-agent{font-size:11px;color:Lemon.ACCENT_BLUE;padding:0 4px;}
.dt-decision-choice{font-size:12px;font-weight:600;}
.dt-decision-rationale{font-size:10px;color:rgba(255,255,255,0.5);}
.dt-branch-path{font-size:12px;font-weight:500;}
.tv-agent{margin-right:4px;}
</style>
"""


def render_decision_tree(tracer: Tracer, session_id: str) -> str:
    view = DecisionTreeView(tracer)
    tree_body = view.render_tree(session_id)
    paths_body = view.render_decision_paths(session_id)
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"{_STYLE_CSS}{_DECISION_TREE_CSS}</head>"
        f"<body style='background:#0a0a0f;'>"
        f"{tree_body}{paths_body}</body></html>"
    )
