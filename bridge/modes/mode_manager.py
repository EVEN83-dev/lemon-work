from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .mode_base import BaseMode, CreatorMode, CustomMode, MinimalMode, StandardMode


class ModeManager:
    DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".lemoncode", "mode_config.json")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._modes: Dict[str, BaseMode] = {}
        self._active_mode_name: str = "standard"

        self.register_mode(StandardMode())
        self.register_mode(MinimalMode())
        self.register_mode(CreatorMode())

    def register_mode(self, mode: BaseMode) -> bool:
        with self._lock:
            if not mode.name:
                return False
            self._modes[mode.name] = mode
            return True

    def get_mode(self, name: str) -> Optional[BaseMode]:
        with self._lock:
            return self._modes.get(name)

    def get_active_mode(self) -> BaseMode:
        with self._lock:
            mode = self._modes.get(self._active_mode_name)
            if mode is None:
                mode = self._modes.get("standard")
            if mode is None:
                raise RuntimeError("No modes registered")
            return mode

    def switch_mode(self, name: str) -> bool:
        with self._lock:
            if name not in self._modes:
                return False
            self._active_mode_name = name
            self.save_config()
            return True

    def list_modes(self) -> List[dict]:
        with self._lock:
            result = []
            for mode in self._modes.values():
                result.append({
                    "name": mode.name,
                    "display_name": mode.display_name,
                    "description": mode.description,
                    "permission_level": mode.permission_level,
                })
            return result

    def is_tool_allowed(self, tool_id: str) -> bool:
        with self._lock:
            return self.get_active_mode().is_tool_allowed(tool_id)

    def get_system_prompt(self) -> str:
        with self._lock:
            return self.get_active_mode().get_system_prompt()

    def save_config(self, path: str | None = None) -> bool:
        save_path = path or self.DEFAULT_CONFIG_PATH
        try:
            with self._lock:
                config: dict = {
                    "active_mode": self._active_mode_name,
                    "custom_modes": {},
                }
                for name, mode in self._modes.items():
                    if isinstance(mode, CustomMode):
                        config["custom_modes"][name] = mode.get_config()

                config_dir = os.path.dirname(save_path)
                if config_dir:
                    Path(config_dir).mkdir(parents=True, exist_ok=True)

                with open(save_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                return True
        except (OSError, json.JSONEncodeError):
            return False

    def load_config(self, path: str | None = None) -> bool:
        load_path = path or self.DEFAULT_CONFIG_PATH
        try:
            with self._lock:
                if not os.path.isfile(load_path):
                    return False

                with open(load_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

                active_mode = config.get("active_mode", "standard")
                custom_modes = config.get("custom_modes", {})

                for name, mode_config in custom_modes.items():
                    custom = CustomMode.from_config(name, mode_config)
                    self.register_mode(custom)

                if active_mode in self._modes:
                    self._active_mode_name = active_mode

                return True
        except (OSError, json.JSONDecodeError, KeyError):
            return False

    def create_custom_mode(self, name: str, config: dict) -> BaseMode:
        with self._lock:
            custom = CustomMode.from_config(name, config)
            self.register_mode(custom)
            return custom
