import importlib.util
import os
import sys
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class SkillPluginManager:

    def __init__(self):
        self._plugin_dir = os.path.join(os.path.expanduser("~"), ".lemoncode", "plugins")
        self._plugins = {}
        discovered = self.discover_plugins()
        for name in discovered:
            self.load_plugin(name)

    def discover_plugins(self) -> list:
        plugin_names = []
        if not os.path.isdir(self._plugin_dir):
            logger.warning("Plugin directory does not exist: %s", self._plugin_dir)
            return plugin_names
        for entry in os.listdir(self._plugin_dir):
            plugin_path = os.path.join(self._plugin_dir, entry)
            skill_file = os.path.join(plugin_path, "skill.py")
            if os.path.isdir(plugin_path) and os.path.isfile(skill_file):
                plugin_names.append(entry)
        return plugin_names

    def load_plugin(self, name: str) -> bool:
        plugin_path = os.path.join(self._plugin_dir, name, "skill.py")
        if not os.path.isfile(plugin_path):
            logger.error("Plugin skill.py not found for: %s", name)
            return False
        try:
            spec = importlib.util.spec_from_file_location(f"lemoncode_plugin_{name}", plugin_path)
            if spec is None or spec.loader is None:
                logger.error("Failed to create spec for plugin: %s", name)
                return False
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            if not self._validate_plugin(module):
                logger.error("Plugin validation failed for: %s", name)
                del sys.modules[spec.name]
                return False
            self._plugins[name] = {
                "name": module.SKILL_NAME,
                "description": module.SKILL_DESCRIPTION,
                "version": module.SKILL_VERSION,
                "category": getattr(module, "SKILL_CATEGORY", ""),
                "module": module,
            }
            logger.info("Loaded plugin: %s v%s", name, module.SKILL_VERSION)
            return True
        except Exception as e:
            logger.error("Failed to load plugin %s: %s", name, e)
            return False

    def unload_plugin(self, name: str) -> None:
        if name in self._plugins:
            module = self._plugins[name]["module"]
            module_name = f"lemoncode_plugin_{name}"
            if module_name in sys.modules:
                del sys.modules[module_name]
            del self._plugins[name]
            logger.info("Unloaded plugin: %s", name)

    def execute_plugin(self, name: str, **kwargs) -> dict:
        if name not in self._plugins:
            logger.error("Plugin not loaded: %s", name)
            return {"success": False, "result": f"Plugin '{name}' not loaded"}
        try:
            result = self._plugins[name]["module"].execute(**kwargs)
            return result
        except Exception as e:
            logger.error("Plugin execution failed for %s: %s", name, e)
            return {"success": False, "result": str(e)}

    def get_plugin_info(self, name: str) -> dict:
        if name not in self._plugins:
            return {}
        info = {
            "name": self._plugins[name]["name"],
            "description": self._plugins[name]["description"],
            "version": self._plugins[name]["version"],
            "category": self._plugins[name]["category"],
        }
        return info

    def list_plugins(self) -> list:
        result = []
        for name, data in self._plugins.items():
            result.append({
                "name": data["name"],
                "description": data["description"],
            })
        return result

    def _validate_plugin(self, module) -> bool:
        required_attrs = ["SKILL_NAME", "SKILL_DESCRIPTION", "SKILL_VERSION", "execute"]
        for attr in required_attrs:
            if not hasattr(module, attr):
                logger.error("Missing required attribute: %s", attr)
                return False
        if not callable(getattr(module, "execute")):
            logger.error("execute is not callable")
            return False
        return True
