import json
import os
import logging

logger = logging.getLogger(__name__)

_LEMON_DIR = os.path.join(os.path.expanduser("~"), ".lemoncode")
_STATE_FILE = os.path.join(_LEMON_DIR, "onboarding_state.json")
_COMPLETED_FILE = os.path.join(_LEMON_DIR, ".first_run_completed")

_ONBOARDING_STEPS = [
    {"step": 1, "key": "welcome", "title": "欢迎使用 Lemon Work", "description": "Lemon Work 是你的智能工作助手"},
    {"step": 2, "key": "engine_setup", "title": "配置 AI 引擎", "description": "选择默认 AI 引擎（Ollama/DeepSeek/MimoCode）"},
    {"step": 3, "key": "skill_overview", "title": "技能概览", "description": "了解 Lemon Work 的核心技能"},
    {"step": 4, "key": "memory_setup", "title": "记忆设置", "description": "配置持久化记忆和上下文管理"},
    {"step": 5, "key": "security", "title": "安全须知", "description": "了解安全限制和隐私保护"},
    {"step": 6, "key": "done", "title": "设置完成", "description": "一切就绪，开始使用 Lemon Work！"},
]


def _ensure_dir():
    os.makedirs(_LEMON_DIR, exist_ok=True)


def is_first_run() -> bool:
    return not os.path.exists(_COMPLETED_FILE)


def get_onboarding_state() -> dict:
    if not os.path.exists(_STATE_FILE):
        return {"step": 0, "data": {}}
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load onboarding state: %s", e)
        return {"step": 0, "data": {}}


def save_onboarding_state(step: int, data: dict) -> None:
    _ensure_dir()
    state = {"step": step, "data": data}
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("Failed to save onboarding state: %s", e)


def complete_onboarding() -> None:
    _ensure_dir()
    try:
        with open(_COMPLETED_FILE, "w", encoding="utf-8") as f:
            pass
    except OSError as e:
        logger.error("Failed to create completion flag: %s", e)
    save_onboarding_state(6, {"completed": True})


def get_onboarding_steps() -> list:
    return list(_ONBOARDING_STEPS)
