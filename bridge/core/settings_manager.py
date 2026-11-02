﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿"""
B-004: SettingsManager - decoupled from PyQt5.

Pure Python settings management with JSON persistence and observer pattern.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Callable, Dict, List, Optional


class SettingsManager:
    _instance: Optional[SettingsManager] = None
    _lock = threading.Lock()

    def __init__(self, config_dir: str = ""):
        if not config_dir:
            config_dir = os.path.join(os.path.expanduser("~"), ".lemon_bridge")
        self._config_dir = config_dir
        self._config_path = os.path.join(config_dir, "settings.json")
        self._data: Dict[str, Any] = {}
        self._listeners: List[Callable] = []
        self._file_lock = threading.Lock()
        self._defaults: Dict[str, Any] = {
            "general.language": "zh",
            "general.reopen_last_session": True,
            "ai.model": "auto",
            "ai.temperature": 0.7,
            "ai.max_tokens": 4096,
            "ai.system_prompt": "",
            "ai.enable_skills": True,
            "appearance.theme": "cyber",
            "appearance.font_size": 14,
            "appearance.code_font": "Consolas",
            "visualization.chart_style": "neon",
            "visualization.render_quality": "high",
            "visualization.animation": True,
            "bridge.host": "0.0.0.0",
            "bridge.port": 8765,
            "bridge.cors_origins": ["*"],
            "bridge.max_connections": 100,
            "bridge.session_timeout": 3600,
            "engines.ollama.host": "127.0.0.1",
            "engines.ollama.port": 11434,
            "engines.ollama.model": "aleshribou3/deepseek-r1-tool-calling:8b",  # ★2026-09-30验收修复: 默认模型指向本机Ollama实际存在的全名模型(工具调用)
            "engines.deepseek.api_key": "",
            "engines.deepseek.model": "deepseek-chat",
            "engines.deepseek.api_base": "https://api.deepseek.com",
            "engines.lmstudio.host": "127.0.0.1",
            "engines.lmstudio.port": 1234,
            "engines.lmstudio.model": "auto",
            "sandbox.cpu_limit": 2,
            "sandbox.memory_limit_mb": 1024,
            "sandbox.timeout_seconds": 30,
            "files.upload_dir": "",
            "files.max_size_mb": 50,
            "files.cleanup_hours": 24,
        }

    @classmethod
    def instance(cls, config_dir: str = "") -> SettingsManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config_dir)
        return cls._instance

    def load(self) -> Dict[str, Any]:
        os.makedirs(self._config_dir, exist_ok=True)
        if os.path.exists(self._config_path):
            with self._file_lock:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        else:
            self._data = {}
        return self._data

    def save(self) -> bool:
        os.makedirs(self._config_dir, exist_ok=True)
        with self._file_lock:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        self._notify_listeners()
        return True

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return self._data[key]
        if key in self._defaults:
            return self._defaults[key]
        return default

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get_all(self) -> Dict[str, Any]:
        result = dict(self._defaults)
        result.update(self._data)
        return result

    def add_listener(self, callback: Callable) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self) -> None:
        for cb in self._listeners:
            try:
                cb(self._data)
            except Exception:
                pass
