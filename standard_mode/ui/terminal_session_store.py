# -*- coding: utf-8 -*-
"""
Terminal session persistence — cwd/shell/layout/command history save + restore
==============================================================================
Config file: ~/.mimo_agent/terminal_sessions.json

Saved content:
  - Per terminal tab: cwd, shell, tab_name, split_layout, command_history
  - Last active tab index
  - Window geometry

Restore timing:
  - main_window.__init__ end calls restore_sessions()
"""
import json
import os
import time
from typing import List, Dict, Any, Optional

_SESSION_FILE = os.path.join(os.path.expanduser("~"), ".mimo_agent", "terminal_sessions.json")
_HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".mimo_agent", "terminal_command_history.jsonl")

_MAX_SESSIONS = 10
_MAX_HISTORY = 5000


def save_sessions(sessions: List[Dict[str, Any]], active_index: int = 0, geometry: str = ""):
    try:
        os.makedirs(os.path.dirname(_SESSION_FILE), exist_ok=True)
        data = {
            "version": 2,
            "timestamp": time.time(),
            "active_index": active_index,
            "geometry": geometry,
            "sessions": sessions[:_MAX_SESSIONS],
        }
        with open(_SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_sessions() -> Dict[str, Any]:
    try:
        if not os.path.isfile(_SESSION_FILE):
            return {"sessions": [], "active_index": 0, "geometry": ""}
        with open(_SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        sessions = data.get("sessions", [])
        if len(sessions) > _MAX_SESSIONS:
            sessions = sessions[:_MAX_SESSIONS]
        return {
            "sessions": sessions,
            "active_index": data.get("active_index", 0),
            "geometry": data.get("geometry", ""),
        }
    except Exception:
        return {"sessions": [], "active_index": 0, "geometry": ""}


def clear_sessions():
    try:
        if os.path.isfile(_SESSION_FILE):
            os.remove(_SESSION_FILE)
    except Exception:
        pass


def session_from_bridge(bridge) -> Dict[str, Any]:
    if bridge is None:
        return {}
    sb = getattr(bridge, "_bridge", None)
    return {
        "cwd": getattr(bridge, "_cwd", ""),
        "shell": list(getattr(sb, "shell", [])) if sb else [],
        "encoding": getattr(sb, "encoding", "auto") if sb else "auto",
        "cols": getattr(sb, "cols", 120) if sb else 120,
        "rows": getattr(sb, "rows", 30) if sb else 30,
        "running": getattr(bridge, "is_running", False),
    }


def restore_session_to_bridge(session: Dict[str, Any], bridge) -> bool:
    if not session or not bridge:
        return False
    cwd = session.get("cwd", "")
    if cwd and os.path.isdir(cwd):
        bridge._cwd = cwd
    return True


def save_command(command: str, session_id: str = "") -> None:
    if not command.strip():
        return
    try:
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        entry = {
            "ts": time.time(),
            "cmd": command.strip(),
            "session": session_id,
        }
        with open(_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_command_history(limit: int = _MAX_HISTORY) -> List[Dict[str, Any]]:
    try:
        if not os.path.isfile(_HISTORY_FILE):
            return []
        entries: List[Dict[str, Any]] = []
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
        return entries[-limit:]
    except Exception:
        return []


def search_command_history(query: str, limit: int = 50) -> List[str]:
    if not query.strip():
        return []
    entries = load_command_history()
    query_lower = query.lower()
    results: List[str] = []
    seen = set()
    for entry in reversed(entries):
        cmd = entry.get("cmd", "")
        if query_lower in cmd.lower() and cmd not in seen:
            results.append(cmd)
            seen.add(cmd)
            if len(results) >= limit:
                break
    return results
