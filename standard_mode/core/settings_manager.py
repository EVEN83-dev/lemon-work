# -*- coding: utf-8 -*-
"""
设置管理器 — 持久化用户配置
=================================
功能：
- 加载/保存配置到 ~/.mimo_agent/settings.json
- 提供 get/set 接口访问配置项
- 默认配置：主题=cyber, 字体大小=14, 模型=auto, 温度=0.7
- 支持运行时修改并实时通知（观察者模式）

配置结构：
{
    "general": {
        "language": "zh",           # zh / en
        "reopen_last_session": true
    },
    "ai": {
        "model": "auto",            # auto / ollama / mimo
        "temperature": 0.7,
        "max_tokens": 4096
    },
    "appearance": {
        "theme": "cyber",           # cyber / dark / light
        "font_size": 14,
        "code_font": "Consolas"
    },
    "visualization": {
        "chart_style": "neon",      # neon / plain
        "render_quality": "high",   # high / medium / low
        "animation": true
    },
    "shortcuts": {
        "send": "Ctrl+Enter",
        "new_session": "Ctrl+N",
        "switch_session": "Ctrl+Tab",
        "settings": "Ctrl+,"
    },
    "modes": {
        "native": {  # NATIVE — LemonCode 本体 Agent
            "enabled": true,
            "tool_file_write": true,
            "tool_terminal": true,
            "tool_web_search": false,
            "tool_code_review": false,
            "session_memory": true,
            "show_system_prompt": false
        },
        "host": {  # HOST — 外部 Agent 夺舍
            "enabled": true,
            "default_agent": "mimo_code",
            "acp_port": 0,
            "connect_timeout": 30,
            "intercept_output": true,
            "reprocess_output": true,
            "show_source_prefix": true,
            "color_output": true
        }
    }
}
"""

import os
import json
import threading
from typing import Any, Dict, Optional


# ============================================================
# 默认配置
# ============================================================

DEFAULT_SETTINGS = {
    "general": {
        "language": "zh",
        "reopen_last_session": True,
    },
    "ai": {
        "model": "auto",            # auto / ollama / mimo
        "temperature": 0.7,
        "max_tokens": 4096,
        "git_commit": {
            "engine": "ollama",      # ollama / deepseek
            "ollama_model": "qwen2.5-coder:3b",
            "ollama_url": "http://127.0.0.1:11434",
            "deepseek_model": "deepseek-chat",
            # 注意: API key 不落盘保存（安全），始终从 ~/.deepseek_key 或环境变量读取
        },
    },
    "appearance": {
        "theme": "cyber",           # cyber / dark / light
        "font_size": 14,
        "code_font": "Consolas",
        # ★ v3.90: Agent 状态灯动画配置（flow / pulse / blink；speed 为每帧 ms）
        "agent_light": {
            "animation_mode": "flow",
            "speed": 60,
        },
        # ★ v4.1.9: 模式收敛为两段 — NATIVE / HOST 滑动开关
        "mode_switches": {
            "native_agent_enabled": True,   # NATIVE — LemonCode 本体 Agent
            "host_agent_enabled": True,     # HOST — 外部 Agent 夺舍
        },
    },
    # ★ v4.1.12: 分模式差异化配置（NATIVE 本体 vs HOST 夺舍）
    "modes": {
        "native": {
            "enabled": True,
            # 工具权限（NATIVE 自研 Agent 的工具开关）
            "tool_file_write": True,     # 允许写文件
            "tool_terminal": True,       # 允许执行终端命令
            "tool_web_search": False,    # 允许联网搜索
            "tool_code_review": False,   # 自动代码审查
            "session_memory": True,      # 会话记忆/摘要持久化
            "show_system_prompt": False, # 调试时显示系统提示词
        },
        "host": {
            "enabled": True,
            "default_agent": "mimo_code",  # 夺舍默认 Agent id
            "acp_port": 0,                 # 0=自动选择
            "connect_timeout": 30,         # 连接超时（秒）
            "intercept_output": True,      # 拦截外部 Agent 输出（假终端）
            "reprocess_output": True,      # 二次处理（右栏显示模式）
            "show_source_prefix": True,    # 显示 [Agent]/[Tool]/[思考] 来源前缀
            "color_output": True,          # 按来源分色显示
        },
    },
    "visualization": {
        "chart_style": "neon",      # neon / plain
        "render_quality": "high",   # high / medium / low
        "animation": True,
    },
    "shortcuts": {
        "send": "Ctrl+Enter",
        "new_session": "Ctrl+N",
        "switch_session": "Ctrl+Tab",
        "settings": "Ctrl+,",
    },
}


class SettingsManager:
    """
    设置管理器（单例）

    使用方式：
        sm = SettingsManager()
        sm.load()
        theme = sm.get("appearance.theme", "cyber")
        sm.set("appearance.theme", "dark")
        sm.save()
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_dir: str = ""):
        if hasattr(self, '_initialized') and self._initialized:
            return
        if not config_dir:
            config_dir = os.path.join(os.path.expanduser("~"), ".mimo_agent")
        self._config_dir = config_dir
        self._config_file = os.path.join(config_dir, "settings.json")
        self._settings: Dict[str, Any] = {}
        self._listeners = []  # 配置变更回调列表
        self._file_lock = threading.Lock()
        self._initialized = False
        self.load()

    # ============================================================
    # 加载 / 保存
    # ============================================================

    def load(self) -> Dict[str, Any]:
        """从磁盘加载配置，合并默认值"""
        with self._file_lock:
            self._settings = self._deep_copy(DEFAULT_SETTINGS)
            try:
                if os.path.isfile(self._config_file):
                    with open(self._config_file, 'r', encoding='utf-8') as f:
                        saved = json.load(f)
                    if isinstance(saved, dict):
                        self._merge_settings(self._settings, saved)
            except (json.JSONDecodeError, OSError, IOError) as e:
                print(f"[SettingsManager] 加载配置失败，使用默认值: {e}")
            self._initialized = True
            return self._deep_copy(self._settings)

    def save(self) -> bool:
        """保存配置到磁盘"""
        with self._file_lock:
            try:
                os.makedirs(self._config_dir, exist_ok=True)
                with open(self._config_file, 'w', encoding='utf-8') as f:
                    json.dump(self._settings, f, ensure_ascii=False, indent=2)
                self._notify_listeners("__saved__", None)
                # ★ 发布设置变更事件（延迟导入避免循环依赖）
                try:
                    from event_bus import EventBus, EventType
                    EventBus.instance().publish(EventType.SETTINGS_CHANGED, self.get_all())
                except Exception:
                    pass
                return True
            except (OSError, IOError) as e:
                print(f"[SettingsManager] 保存配置失败: {e}")
                return False

    # ============================================================
    # 读取 / 设置
    # ============================================================

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项，支持点号路径：get('appearance.theme')"""
        parts = key.split('.')
        current = self._settings
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def set(self, key: str, value: Any, auto_save: bool = False):
        """设置配置项，支持点号路径：set('appearance.theme', 'dark')"""
        parts = key.split('.')
        current = self._settings
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        old_value = current.get(parts[-1])
        current[parts[-1]] = value
        self._notify_listeners(key, value)
        if auto_save:
            self.save()

    def get_all(self) -> Dict[str, Any]:
        """获取全部配置（深拷贝）"""
        return self._deep_copy(self._settings)

    def set_all(self, settings: Dict[str, Any], auto_save: bool = False):
        """批量设置配置"""
        self._settings = self._deep_copy(DEFAULT_SETTINGS)
        self._merge_settings(self._settings, settings)
        self._notify_listeners("__all__", self._settings)
        if auto_save:
            self.save()

    def reset_to_defaults(self, auto_save: bool = False):
        """重置为默认配置"""
        self._settings = self._deep_copy(DEFAULT_SETTINGS)
        self._notify_listeners("__all__", self._settings)
        if auto_save:
            self.save()

    # ============================================================
    # 观察者模式
    # ============================================================

    def add_listener(self, callback):
        """添加配置变更回调：callback(key, value)"""
        if callable(callback) and callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback):
        """移除配置变更回调"""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self, key: str, value: Any):
        for cb in self._listeners:
            try:
                cb(key, value)
            except Exception as e:
                print(f"[SettingsManager] 监听器回调异常: {e}")

    # ============================================================
    # 便捷方法
    # ============================================================

    @property
    def theme(self) -> str:
        return self.get("appearance.theme", "cyber")

    @theme.setter
    def theme(self, value: str):
        self.set("appearance.theme", value)

    @property
    def font_size(self) -> int:
        return self.get("appearance.font_size", 14)

    @property
    def ai_model(self) -> str:
        return self.get("ai.model", "auto")

    @property
    def ai_temperature(self) -> float:
        return self.get("ai.temperature", 0.7)

    @property
    def ai_max_tokens(self) -> int:
        return self.get("ai.max_tokens", 4096)

    @property
    def language(self) -> str:
        return self.get("general.language", "zh")

    @property
    def animation_enabled(self) -> bool:
        return self.get("visualization.animation", True)

    # ============================================================
    # ★ v4.1.12: 分模式便捷访问（NATIVE / HOST）
    # ============================================================

    def mode_enabled(self, mode: str) -> bool:
        """指定模式是否启用"""
        return bool(self.get(f"modes.{mode}.enabled", True))

    def get_mode(self, mode: str, key: str, default: Any = None) -> Any:
        """读取指定模式的配置项"""
        return self.get(f"modes.{mode}.{key}", default)

    def set_mode(self, mode: str, key: str, value: Any, auto_save: bool = False):
        """设置指定模式的配置项"""
        self.set(f"modes.{mode}.{key}", value, auto_save=auto_save)

    # ---- NATIVE 专属 ----
    @property
    def native_tool_file_write(self) -> bool:
        return bool(self.get("modes.native.tool_file_write", True))

    @property
    def native_tool_terminal(self) -> bool:
        return bool(self.get("modes.native.tool_terminal", True))

    @property
    def native_tool_web_search(self) -> bool:
        return bool(self.get("modes.native.tool_web_search", False))

    @property
    def native_tool_code_review(self) -> bool:
        return bool(self.get("modes.native.tool_code_review", False))

    @property
    def native_session_memory(self) -> bool:
        return bool(self.get("modes.native.session_memory", True))

    # ---- HOST 专属 ----
    @property
    def host_default_agent(self) -> str:
        return str(self.get("modes.host.default_agent", "mimo_code"))

    @property
    def host_connect_timeout(self) -> int:
        return int(self.get("modes.host.connect_timeout", 30))

    @property
    def host_acp_port(self) -> int:
        return int(self.get("modes.host.acp_port", 0))

    @property
    def host_intercept_output(self) -> bool:
        return bool(self.get("modes.host.intercept_output", True))

    @property
    def host_reprocess_output(self) -> bool:
        return bool(self.get("modes.host.reprocess_output", True))

    @property
    def host_show_source_prefix(self) -> bool:
        return bool(self.get("modes.host.show_source_prefix", True))

    @property
    def host_color_output(self) -> bool:
        return bool(self.get("modes.host.color_output", True))

    # ============================================================
    # 工具方法
    # ============================================================

    @staticmethod
    def _deep_copy(obj):
        """深拷贝（不依赖 copy 模块）"""
        if isinstance(obj, dict):
            return {k: SettingsManager._deep_copy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [SettingsManager._deep_copy(v) for v in obj]
        else:
            return obj

    @staticmethod
    def _merge_settings(base: dict, override: dict):
        """递归合并：override 的值覆盖 base"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                SettingsManager._merge_settings(base[key], value)
            else:
                base[key] = value

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self._settings, ensure_ascii=False, indent=2)


# ============================================================
# 模块级单例
# ============================================================

_settings_manager: Optional[SettingsManager] = None


def get_settings_manager() -> SettingsManager:
    """获取全局 SettingsManager 单例"""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager


if __name__ == '__main__':
    # 自测
    sm = SettingsManager()
    print(f"主题: {sm.theme}")
    print(f"字体大小: {sm.font_size}")
    print(f"AI模型: {sm.ai_model}")
    print(f"温度: {sm.ai_temperature}")
    print(f"全部配置:\n{sm.to_json()}")
    print("-" * 40)
    sm.set("appearance.theme", "dark")
    print(f"切换后主题: {sm.theme}")
    sm.save()
    print("已保存到 ~/.mimo_agent/settings.json")
