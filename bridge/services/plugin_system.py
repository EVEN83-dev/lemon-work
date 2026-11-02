"""
B-P3-005: Plugin System Service

Hook-based plugin architecture with register/emit/unregister.
Built-in logging and usage-stats plugins.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class HookPoint:
    name: str


HOOKS = {
    "before_process": HookPoint("before_process"),
    "after_process": HookPoint("after_process"),
    "on_error": HookPoint("on_error"),
    "on_skill_activate": HookPoint("on_skill_activate"),
    "on_tool_execute": HookPoint("on_tool_execute"),
    "on_message": HookPoint("on_message"),
}


@dataclass
class PluginDef:
    id: str
    name: str
    hooks: List[str]
    handler: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    enabled: bool = True

    def execute(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if self.handler is not None and self.enabled:
            return self.handler(data)
        return data


class PluginSystemService:
    def __init__(self) -> None:
        self._plugins: Dict[str, PluginDef] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        log_plugin = PluginDef(
            id="log",
            name="\u65e5\u5fd7\u8bb0\u5f55",
            hooks=["before_process", "after_process", "on_error"],
            handler=lambda data: self._log_handler(data),
        )
        self._plugins[log_plugin.id] = log_plugin

        stats_plugin = PluginDef(
            id="usage_stats",
            name="\u4f7f\u7528\u7edf\u8ba1",
            hooks=["on_skill_activate", "on_tool_execute"],
        )
        self._plugins[stats_plugin.id] = stats_plugin

    @staticmethod
    def _log_handler(data: Dict[str, Any]) -> Dict[str, Any]:
        import logging
        logger = logging.getLogger("lemon_plugin")
        logger.info(f"[Plugin:Log] {data}")
        return data

    def register(self, plugin: PluginDef) -> str:
        self._plugins[plugin.id] = plugin
        return plugin.id

    def unregister(self, plugin_id: str) -> bool:
        return self._plugins.pop(plugin_id, None) is not None

    def emit(self, hook_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        result = data
        for plugin in self._plugins.values():
            if hook_name in plugin.hooks and plugin.enabled:
                result = plugin.execute(result)
        return result

    def list_plugins(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "hooks": p.hooks,
                "enabled": p.enabled,
            }
            for p in self._plugins.values()
        ]

    def enable(self, plugin_id: str) -> bool:
        p = self._plugins.get(plugin_id)
        if p is None:
            return False
        p.enabled = True
        return True

    def disable(self, plugin_id: str) -> bool:
        p = self._plugins.get(plugin_id)
        if p is None:
            return False
        p.enabled = False
        return True

    def load_from_entry_point(self, group: str = "lemoncode.plugin") -> List[str]:
        loaded: List[str] = []
        eps = importlib.metadata.entry_points()
        try:
            selected = eps.select(group=group)
        except AttributeError:
            selected = eps.get(group, [])
        for ep in selected:
            try:
                mod = ep.load()
                if hasattr(mod, "register"):
                    mod.register(self)
                    loaded.append(ep.name)
            except Exception:
                continue
        return loaded

    def load_from_dir(self, plugins_dir: str) -> List[str]:
        loaded: List[str] = []
        if not os.path.isdir(plugins_dir):
            return loaded
        for entry in sorted(os.listdir(plugins_dir)):
            subdir = os.path.join(plugins_dir, entry)
            plugin_file = os.path.join(subdir, "plugin.py")
            if not os.path.isdir(subdir) or not os.path.isfile(plugin_file):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"{entry}.plugin", plugin_file,
                )
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "PLUGIN") and isinstance(mod.PLUGIN, PluginDef):
                    self.register(mod.PLUGIN)
                    loaded.append(mod.PLUGIN.id)
                elif hasattr(mod, "register"):
                    mod.register(self)
                    loaded.append(entry)
            except Exception:
                continue
        return loaded
