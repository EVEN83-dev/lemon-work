# -*- coding: utf-8 -*-
"""
Config Manager — 配置持久化管理
================================
提供用户设置保存、配置文件管理、默认配置和配置验证功能。

功能：
1. 用户设置 CRUD
2. 配置文件自动保存/加载
3. 默认配置回退
4. 配置验证
5. 配置变更通知
6. 多配置源支持（文件 + 环境变量）

使用方式：
    config = ConfigManager()
    config.set("engine", "ollama")
    engine = config.get("engine", "auto")
    config.save()
"""

import os
import json
import threading
from typing import Any, Dict, Optional, Callable, List, Tuple


class ConfigManager:
    """配置管理器

    架构：
    ┌──────────────────────────────────────┐
    │            ConfigManager              │
    │  ┌────────────┐  ┌────────────────┐  │
    │  │ config.json │  │ 环境变量覆盖    │  │
    │  │ - 用户设置   │  │ LEMON_ENGINE   │  │
    │  │ - 主题      │  │ LEMON_MODEL    │  │
    │  │ - 引擎偏好   │  │ LEMON_PORT     │  │
    │  └────────────┘  └────────────────┘  │
    │  ┌────────────────────────────────┐  │
    │  │ 变更回调                         │  │
    │  │ - config_changed 信号            │  │
    │  └────────────────────────────────┘  │
    └──────────────────────────────────────┘
    """

    VERSION = "1.0.0"

    # 默认配置
    DEFAULT_CONFIG = {
        "version": VERSION,
        "engine": "auto",
        # ★ 385-P0 模型基线锁定（唯一评测基线 = qwen3.5:4b）：
        #   三口径历史：本键原为 qwen2.5:1.5b（第三口径）；评测线 engine_manager
        #   ._configs["ollama"].model=qwen3:4b（378-4 锚定，379-384 评测实际值）；
        #   实战 UI 链路 v3.60 起全线 qwen3.5:4b（ollama_bridge/ai_provider/mimo_page）。
        #   判定：配置漂移（实战有意升级、评测基线未跟随），非评测基线升级。
        #   自 385 章起：唯一评测基线 = qwen3.5:4b（与实战 UI 一致）；
        #   qwen3:4b 数据降级为旧基线对照栏。
        "model": "qwen3.5:4b",
        "theme": "dark",
        "language": "zh-CN",
        "auto_save": True,
        "auto_save_interval": 60,
        "max_history": 20,
        "max_context_tokens": 4000,
        "mimo_port": 4097,
        "ollama_host": "127.0.0.1",
        "ollama_port": 11434,
        "enable_skills": True,
        "enable_visualization": True,
        "enable_auto_complete": True,
        "font_size": 14,
        "window_width": 1280,
        "window_height": 800,
        "log_level": "INFO",
        "check_updates": False,
        "send_error_reports": False,
        "agent.guided_loop_enabled": False,
        # ★ 391A-1: Ollama 上下文窗口（num_ctx）唯一真源。
        #   实测依据（4060 Laptop 8GB / qwen3.5:4b，2026-09-07）：
        #   num_ctx=131072 → 8.6GB 装不下（36% 溢出 CPU）；
        #   num_ctx=32768  → 4.2GB 100% GPU，40.2 tok/s ← 32K 为本机甜点值。
        #   Ollama 默认 4096 是"失忆"根因（超窗静默截断仍返回成功）。
        #   引擎请求构建（engine_manager generate/chat 两路）与 UI 窗口标注
        #   均读本键，禁止散落硬编码窗口值（391A-1）。
        "ollama.num_ctx": 32768,
        # 400V-3: image_poster 外接文生图 API（OpenAI 兼容格式: 智谱/通义万相等）；
        # 空 = 禁用 → image_poster 走纯程序化海报模式（PIL 自绘），不静默。
        "image.api_endpoint": "",
        "image.api_key_env": "LEMON_IMAGE_API_KEY",
        # ★ 405A2: OSC 133 命令块分段（shell integration, 默认启用）。
        #   注入到 PTY stdin 的提示符重写, 不污染 $PROFILE。
        #   前端终端面板读取本键决定是否默认启用（用户可在设置中关闭）。
        "terminal.shell_integration": True,
    }

    # 环境变量映射
    ENV_MAPPING = {
        "LEMON_ENGINE": "engine",
        "LEMON_MODEL": "model",
        "LEMON_THEME": "theme",
        "LEMON_LANGUAGE": "language",
        "LEMON_MIMO_PORT": "mimo_port",
        "LEMON_OLLAMA_HOST": "ollama_host",
        "LEMON_OLLAMA_PORT": "ollama_port",
        "LEMON_LOG_LEVEL": "log_level",
    }

    def __init__(self, config_dir: str = None, config_file: str = None):
        """
        Args:
            config_dir: 配置目录，默认 ~/.lemon_agent/config
            config_file: 配置文件路径，默认 config_dir/config.json
        """
        if config_dir is None:
            config_dir = os.path.join(os.path.expanduser("~"), ".lemon_agent", "config")
        self.config_dir = config_dir
        self.config_file = config_file or os.path.join(config_dir, "config.json")
        os.makedirs(self.config_dir, exist_ok=True)

        # ★ v5.7: 必须用可重入锁 RLock —— set() 持锁期间会调用 save()，
        #   save() 再次抢同一把锁；threading.Lock 不可重入会永久死锁
        #   （任何 set(auto_save=True) 都会冻死调用线程）
        self._lock = threading.RLock()
        self._config: Dict[str, Any] = {}
        self._callbacks: List[Callable] = []

        # 加载配置
        self._load_config()

    # ============================================================
    # 配置 CRUD
    # ============================================================

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项

        Args:
            key: 配置键名
            default: 默认值

        Returns:
            配置值
        """
        with self._lock:
            # 优先从环境变量获取
            env_value = self._get_env_value(key)
            if env_value is not None:
                return self._convert_type(env_value, key)

            # ★ v5.7: 未设置时回落到默认配置（与类文档「默认配置回退」、
            #   get_all() 的行为保持一致；此前返回 None 违背契约）
            return self._config.get(key, self.DEFAULT_CONFIG.get(key, default))

    def set(self, key: str, value: Any, auto_save: bool = True):
        """设置配置项

        Args:
            key: 配置键名
            value: 配置值
            auto_save: 是否自动保存
        """
        with self._lock:
            # ★ v5.7: 旧值回落到默认配置，使变更回调语义为「从默认值 X 改为 Y」
            #   （此前未设置过的键回调 old_value=None，违背文档约定）
            old_value = self._config.get(key, self.DEFAULT_CONFIG.get(key))
            if old_value == value:
                return

            self._config[key] = value

            if auto_save:
                self.save()

            # 通知变更
            self._notify_change(key, old_value, value)

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置（合并默认值）"""
        with self._lock:
            result = dict(self.DEFAULT_CONFIG)
            result.update(self._config)
            return result

    def delete(self, key: str, auto_save: bool = True):
        """删除配置项，恢复默认值

        Args:
            key: 配置键名
            auto_save: 是否自动保存
        """
        with self._lock:
            if key in self._config:
                old_value = self._config.pop(key)
                if auto_save:
                    self.save()
                self._notify_change(key, old_value, self.DEFAULT_CONFIG.get(key))

    def reset(self, auto_save: bool = True):
        """重置所有配置为默认值"""
        with self._lock:
            self._config = {}
            if auto_save:
                self.save()

    # ============================================================
    # 持久化
    # ============================================================

    def save(self):
        """保存配置到文件"""
        with self._lock:
            try:
                data = {
                    "version": self.VERSION,
                    "config": self._config,
                }
                with open(self.config_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[ConfigManager] 保存配置失败: {e}")

    def reload(self):
        """重新加载配置"""
        self._load_config()

    def _load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._config = data.get("config", {})
            else:
                self._config = {}
        except (json.JSONDecodeError, IOError):
            self._config = {}

    # ============================================================
    # 验证
    # ============================================================

    def validate(self, key: str, value: Any) -> Tuple[bool, Optional[str]]:
        """验证配置值

        Args:
            key: 配置键名
            value: 配置值

        Returns:
            (是否有效, 错误消息)
        """
        validators = {
            "engine": lambda v: v in ("auto", "ollama", "mimocode", "deepseek", "lmstudio"),
            "theme": lambda v: v in ("dark", "light"),
            "language": lambda v: v in ("zh-CN", "en-US"),
            "max_history": lambda v: isinstance(v, int) and 1 <= v <= 100,
            "font_size": lambda v: isinstance(v, int) and 8 <= v <= 32,
            "mimo_port": lambda v: isinstance(v, int) and 1024 <= v <= 65535,
            "ollama_port": lambda v: isinstance(v, int) and 1024 <= v <= 65535,
            "log_level": lambda v: v in ("DEBUG", "INFO", "WARNING", "ERROR"),
            # ★ 391A-1: num_ctx 合法域 [2048, 262144]（qwen3.5:4b 原生 262K 上限）
            "ollama.num_ctx": lambda v: isinstance(v, int) and 2048 <= v <= 262144,
        }

        if key in validators:
            if not validators[key](value):
                return False, f"配置项 '{key}' 的值 '{value}' 无效"
        return True, None

    # ============================================================
    # 变更通知
    # ============================================================

    def on_change(self, callback: Callable[[str, Any, Any], None]):
        """注册配置变更回调

        Args:
            callback: 回调函数 (key, old_value, new_value)
        """
        self._callbacks.append(callback)

    def _notify_change(self, key: str, old_value: Any, new_value: Any):
        """通知所有回调"""
        for callback in self._callbacks:
            try:
                callback(key, old_value, new_value)
            except Exception:
                pass

    # ============================================================
    # 环境变量覆盖
    # ============================================================

    def _get_env_value(self, key: str) -> Optional[str]:
        """从环境变量获取配置值"""
        for env_name, config_key in self.ENV_MAPPING.items():
            if config_key == key:
                return os.environ.get(env_name)
        return None

    def _convert_type(self, value: str, key: str) -> Any:
        """将环境变量字符串转换为正确类型"""
        type_map = {
            "mimo_port": int,
            "ollama_port": int,
            "max_history": int,
            "font_size": int,
            "auto_save": lambda v: v.lower() in ("true", "1", "yes"),
        }
        if key in type_map:
            try:
                return type_map[key](value)
            except (ValueError, TypeError):
                pass
        return value

    # ============================================================
    # 便捷方法
    # ============================================================

    def get_engine(self) -> str:
        """获取当前引擎"""
        return self.get("engine", "auto")

    def get_model(self) -> str:
        """获取当前模型"""
        return self.get("model", "qwen3.5:4b")

    def get_theme(self) -> str:
        """获取当前主题"""
        return self.get("theme", "dark")

    def get_mimo_port(self) -> int:
        """获取 MIMO 端口"""
        return self.get("mimo_port", 4097)

    def is_skills_enabled(self) -> bool:
        """Skills 是否启用"""
        return self.get("enable_skills", True)


# ============================================================
# 全局单例
# ============================================================

_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器单例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager