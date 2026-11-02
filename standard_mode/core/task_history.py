import json
import os
import time
import uuid
import logging
import threading

logger = logging.getLogger(__name__)

MAX_ENTRIES = 200
HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".lemoncode")
HISTORY_FILE = os.path.join(HISTORY_DIR, "task_history.json")

_lock = threading.Lock()


def _ensure_dir():
    os.makedirs(HISTORY_DIR, exist_ok=True)


def _load_history():
    _ensure_dir()
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Failed to load task history: %s", e)
        return []


def _save_history(history):
    _ensure_dir()
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("Failed to save task history: %s", e)


def record_task(prompt, engine, duration, tool_calls, success, complexity):
    with _lock:
        history = _load_history()
        task_id = uuid.uuid4().hex[:12]
        entry = {
            "id": task_id,
            "prompt": prompt,
            "engine": engine,
            "timestamp": time.time(),
            "duration": duration,
            "tool_calls": tool_calls,
            "success": success,
            "complexity": complexity,
        }
        history.append(entry)
        if len(history) > MAX_ENTRIES:
            history = history[-MAX_ENTRIES:]
        _save_history(history)
        return task_id


def get_history(limit=20):
    with _lock:
        history = _load_history()
        return history[-limit:]


def search_history(keyword):
    with _lock:
        history = _load_history()
        keyword_lower = keyword.lower()
        return [e for e in history if keyword_lower in e["prompt"].lower()]


def clear_history():
    with _lock:
        _save_history([])
