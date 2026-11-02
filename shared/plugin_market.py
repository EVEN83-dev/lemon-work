# -*- coding: utf-8 -*-
"""
插件市场 — PluginMarket
========================
功能：
- 内置插件目录（markdown_preview / json_formatter / color_picker / regex_tester / base64_tool）
- 可下载插件目录（预留接口，当前为本地清单）
- 插件详情：描述、作者、版本、截图、权限
- 安装/卸载/启用/禁用 操作
- 插件配置面板（持久化到 ~/.mimo_agent/plugin_configs.json）

与 PluginManager 协作：
- PluginManager 负责底层加载/卸载/沙箱
- PluginMarket 负责目录展示、安装流程、配置管理
"""

import os
import sys
import json
import shutil
import threading
import zipfile
import tempfile
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


# ============================================================
# 数据模型
# ============================================================

@dataclass
class MarketPluginInfo:
    """市场中的插件信息"""
    name: str                              # 插件唯一标识
    display_name: str                      # 展示名称
    description: str                       # 描述
    version: str = "1.0.0"
    author: str = ""
    category: str = "general"              # 分类：tool / editor / format / encoding / color / ...
    icon: str = "📦"                       # 图标（emoji 或 SVG 名称）
    tags: List[str] = field(default_factory=list)
    rating: float = 4.5                    # 用户评级 0.0~5.0
    downloads: int = 0                     # 下载量
    badge: str = ""                        # 徽章："" / "NEW" / "HOT" / "推荐" / "官方精选"
    featured: bool = False                 # 是否官方精选（Featured）
    screenshots: List[str] = field(default_factory=list)  # 截图 URL 或 base64
    is_builtin: bool = True                # 是否为内置插件
    is_installed: bool = False             # 是否已安装
    is_enabled: bool = True                # 是否已启用
    download_url: str = ""                 # 下载地址（第三方插件）
    source_path: str = ""                  # 源文件路径（内置插件）
    config_schema: Dict[str, Any] = field(default_factory=dict)  # 配置项 schema
    default_config: Dict[str, Any] = field(default_factory=dict)  # 默认配置
    permissions: Dict[str, Any] = field(default_factory=dict)     # 权限声明
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ============================================================
# 内置插件清单
# ============================================================

def _builtin_dir() -> str:
    """获取 builtin_plugins 目录

    ★ v3.94: 修正指向 —— 内置插件实际存放在
    standard_mode/core/builtin_plugins/（plugin_system.py 同级），
    而非 shared/builtin_plugins/（该目录不存在，导致 source_path 悬空）。
    """
    _here = os.path.dirname(os.path.abspath(__file__))          # shared/
    _std = os.path.join(os.path.dirname(_here), "standard_mode")  # ../
    _cand = os.path.join(_std, "core", "builtin_plugins")
    if os.path.isdir(_cand):
        return _cand
    return os.path.join(_here, "builtin_plugins")


def _builtin_catalog() -> List[MarketPluginInfo]:
    """内置插件目录清单"""
    bd = _builtin_dir()
    return [
        MarketPluginInfo(
            name="markdown_preview",
            display_name="Markdown 预览",
            description="Markdown 实时预览：支持 md→html 转换、语法校验、代码高亮",
            version="1.0.0",
            author="mimo_agent",
            category="editor",
            icon="📝",
            tags=["markdown", "preview", "html"],
            rating=4.9, downloads=12846,
            badge="HOT", featured=True,
            is_builtin=True,
            source_path=os.path.join(bd, "markdown_preview.py"),
            config_schema={
                "auto_preview": {"type": "boolean", "label": "自动预览", "default": True},
                "extensions": {"type": "list", "label": "支持的扩展名", "default": [".md", ".markdown"]},
            },
            default_config={"auto_preview": True, "extensions": [".md", ".markdown"]},
            permissions={"file_access": "read", "network_access": False, "system_command": False},
        ),
        MarketPluginInfo(
            name="json_formatter",
            display_name="JSON 格式化",
            description="JSON 格式化、校验、JSONPath 查询工具",
            version="1.0.0",
            author="mimo_agent",
            category="format",
            icon="🔧",
            tags=["json", "format", "validate"],
            rating=4.8, downloads=11230,
            badge="NEW",
            is_builtin=True,
            source_path=os.path.join(bd, "json_formatter.py"),
            config_schema={
                "indent": {"type": "integer", "label": "缩进空格数", "default": 2, "min": 0, "max": 8},
                "ensure_ascii": {"type": "boolean", "label": "ASCII 转义", "default": False},
            },
            default_config={"indent": 2, "ensure_ascii": False},
            permissions={"file_access": "read", "network_access": False, "system_command": False},
        ),
        MarketPluginInfo(
            name="color_picker",
            display_name="颜色选择器",
            description="HEX/RGB/HSL 颜色互转 + 调色板生成",
            version="1.0.0",
            author="mimo_agent",
            category="color",
            icon="🎨",
            tags=["color", "design", "palette"],
            rating=4.7, downloads=9352,
            badge="推荐",
            is_builtin=True,
            source_path=os.path.join(bd, "color_picker.py"),
            config_schema={
                "default_count": {"type": "integer", "label": "默认调色板数量", "default": 5, "min": 3, "max": 12},
            },
            default_config={"default_count": 5},
            permissions={"file_access": "none", "network_access": False, "system_command": False},
        ),
        MarketPluginInfo(
            name="regex_tester",
            display_name="正则测试器",
            description="正则表达式匹配测试、替换、token 解释",
            version="1.0.0",
            author="mimo_agent",
            category="tool",
            icon="🔍",
            tags=["regex", "test", "pattern"],
            rating=4.6, downloads=7815,
            is_builtin=True,
            source_path=os.path.join(bd, "regex_tester.py"),
            config_schema={
                "max_matches": {"type": "integer", "label": "最大匹配数", "default": 100, "min": 1, "max": 1000},
                "default_flags": {"type": "string", "label": "默认标志", "default": ""},
            },
            default_config={"max_matches": 100, "default_flags": ""},
            permissions={"file_access": "none", "network_access": False, "system_command": False},
        ),
        MarketPluginInfo(
            name="base64_tool",
            display_name="Base64 编解码",
            description="Base64 编码/解码/文件编码工具",
            version="1.0.0",
            author="mimo_agent",
            category="encoding",
            icon="🔐",
            tags=["base64", "encode", "decode"],
            rating=4.5, downloads=6542,
            is_builtin=True,
            source_path=os.path.join(bd, "base64_tool.py"),
            config_schema={
                "max_file_size": {"type": "integer", "label": "最大文件大小(MB)", "default": 10, "min": 1, "max": 50},
            },
            default_config={"max_file_size": 10},
            permissions={"file_access": "read", "network_access": False, "system_command": False},
        ),
        # ★ v3.94: 新内置插件 — 文本工具
        MarketPluginInfo(
            name="text_tools",
            display_name="文本工具箱",
            description="大小写转换/行处理/UUID/时间戳/URL/Base64/哈希，7 个常用文本工具",
            version="1.0.0",
            author="mimo_agent",
            category="text",
            icon="📝",
            tags=["text", "uuid", "timestamp", "hash"],
            rating=4.8, downloads=8430,
            badge="NEW",
            is_builtin=True,
            source_path=os.path.join(bd, "text_tools.py"),
            default_config={},
            permissions={"file_access": "none", "network_access": False, "system_command": False},
        ),
        # ★ v3.94: 新内置插件 — 代码工具
        MarketPluginInfo(
            name="code_tools",
            display_name="代码工具箱",
            description="代码统计/缩进空格与Tab互转/注释清理/字符替换",
            version="1.0.0",
            author="mimo_agent",
            category="code",
            icon="🧑‍💻",
            tags=["code", "indent", "comment", "stat"],
            rating=4.7, downloads=7290,
            is_builtin=True,
            source_path=os.path.join(bd, "code_tools.py"),
            default_config={},
            permissions={"file_access": "read", "network_access": False, "system_command": False},
        ),
        # ★ v3.94: 新内置插件 — 格式转换
        MarketPluginInfo(
            name="format_convert",
            display_name="格式转换器",
            description="CSV/进制/XML美化/字数统计，格式转换工具集合",
            version="1.0.0",
            author="mimo_agent",
            category="format",
            icon="🔁",
            tags=["format", "csv", "xml", "base"],
            rating=4.6, downloads=6180,
            is_builtin=True,
            source_path=os.path.join(bd, "format_convert.py"),
            default_config={},
            permissions={"file_access": "read", "network_access": False, "system_command": False},
        ),
    ]


# ============================================================
# PluginMarket — 插件市场
# ============================================================

class PluginMarket:
    """插件市场
    
    职责：
    1. 维护可安装的插件目录（内置 + 可下载）
    2. 安装/卸载/启用/禁用 插件（委托 PluginManager 执行）
    3. 持久化插件配置
    4. 提供插件详情查询
    
    使用方式：
        market = PluginMarket(plugin_manager)
        market.install("json_formatter")
        market.enable("json_formatter")
        config = market.get_config("json_formatter")
    """
    
    # 配置文件路径
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".mimo_agent")
    CONFIG_FILE = os.path.join(CONFIG_DIR, "plugin_market.json")
    
    def __init__(self, plugin_manager=None):
        # 延迟导入避免循环依赖
        self._plugin_manager = plugin_manager
        self._lock = threading.RLock()
        self._catalog: Dict[str, MarketPluginInfo] = {}  # name -> 市场信息
        self._installed: Dict[str, Dict] = {}             # name -> 安装信息（时间、版本、配置）
        self._configs: Dict[str, Dict[str, Any]] = {}     # name -> 用户配置
        # 初始化
        self._load_catalog()
        self._load_state()
    
    def sync_with_manager(self):
        """将已安装的插件同步加载到 PluginManager
        
        应用启动时调用：从持久化的安装记录中恢复插件到运行时。
        """
        pm = self._get_plugin_manager()
        if pm is None:
            return
        with self._lock:
            installed_names = list(self._installed.keys())
        for name in installed_names:
            # 检查 PluginManager 中是否已加载
            if pm.get_plugin(name) is None:
                info = self._catalog.get(name)
                if info and info.source_path and os.path.isfile(info.source_path):
                    ok = pm.load_plugin(info.source_path, builtin=info.is_builtin)
                    if ok:
                        # 恢复启用/禁用状态
                        enabled = self._installed[name].get("enabled", True)
                        if not enabled:
                            pm.disable_plugin(name)
                        print(f"[PluginMarket] 恢复插件: {name} (enabled={enabled})")
                    else:
                        print(f"[PluginMarket] 恢复失败: {name}")
                else:
                    # 源文件不存在，从安装记录中移除
                    with self._lock:
                        self._installed.pop(name, None)
                        self._configs.pop(name, None)
                        self._save_state()
                    print(f"[PluginMarket] 源不存在，移除: {name}")
    
    def _get_plugin_manager(self):
        """延迟获取 PluginManager"""
        if self._plugin_manager is not None:
            return self._plugin_manager
        try:
            from plugin_system import get_plugin_manager
            self._plugin_manager = get_plugin_manager()
        except Exception:
            self._plugin_manager = None
        return self._plugin_manager

    def sync_from_manager(self):
        """把 plugin_manager 中实际已加载的插件同步为 Market 的已安装记录。

        修复"假能用"：之前 market 与主程序 plugin_manager 不是同一个实例时，
        plugin_manager 已经 discover_plugins 加载了内置插件，但 market._installed
        为空，导致市场里显示"未安装"而左侧扩展面板其实已有。本方法以
        plugin_manager 为准对齐 _installed。
        """
        pm = self._get_plugin_manager()
        if pm is None:
            return
        try:
            loaded = [p for p in pm.get_all_plugins()] if hasattr(pm, "get_all_plugins") else []
        except Exception:
            return
        with self._lock:
            if not loaded:
                # plugin_manager 为空时不擅自清空（可能还没 discover），保持原状
                return
            for p in loaded:
                name = getattr(p, "name", "") or ""
                if not name:
                    continue
                info = self._catalog.get(name)
                if name not in self._installed:
                    self._installed[name] = {
                        "version": getattr(p, "version", "") or (info.version if info else "1.0.0"),
                        "installed_at": datetime.now().isoformat(),
                        "enabled": True,
                        "source": "builtin" if (info and info.is_builtin) else "local",
                    }
            self._save_state()
    
    # ============================================================
    # 目录加载
    # ============================================================
    
    def _load_catalog(self):
        """加载插件目录"""
        with self._lock:
            self._catalog.clear()
            # 内置插件
            for info in _builtin_catalog():
                self._catalog[info.name] = info
            # ★ 从远程 API 加载可下载的第三方插件目录
            self._fetch_remote_catalog()
    
    def reload_catalog(self):
        """重新加载目录（刷新可安装插件列表）"""
        self._load_catalog()
    
    # ============================================================
    # 状态持久化
    # ============================================================
    
    def _load_state(self):
        """从磁盘加载已安装插件状态和配置"""
        try:
            if os.path.isfile(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._installed = data.get("installed", {})
                self._configs = data.get("configs", {})
        except Exception as e:
            print(f"[PluginMarket] 加载状态失败: {e}")
            self._installed = {}
            self._configs = {}
    
    def _save_state(self):
        """保存状态到磁盘"""
        try:
            os.makedirs(self.CONFIG_DIR, exist_ok=True)
            data = {
                "installed": self._installed,
                "configs": self._configs,
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[PluginMarket] 保存状态失败: {e}")
    
    # ============================================================
    # 查询接口
    # ============================================================
    
    def list_plugins(self, category: str = "") -> List[Dict[str, Any]]:
        """列出市场所有插件"""
        with self._lock:
            result = []
            for info in self._catalog.values():
                if category and info.category != category:
                    continue
                d = info.to_dict()
                # 合并安装状态
                installed_info = self._installed.get(info.name, {})
                d["is_installed"] = info.name in self._installed
                d["is_enabled"] = installed_info.get("enabled", info.is_enabled)
                d["installed_version"] = installed_info.get("version", "")
                d["installed_at"] = installed_info.get("installed_at", "")
                d["current_config"] = self._configs.get(info.name, info.default_config)
                result.append(d)
            return result
    
    def get_plugin_detail(self, name: str) -> Optional[Dict[str, Any]]:
        """获取插件详情"""
        with self._lock:
            info = self._catalog.get(name)
            if not info:
                # 可能在 PluginManager 中已加载但不在市场目录
                pm = self._get_plugin_manager()
                if pm:
                    plugin_info = pm.get_plugin_info(name)
                    if plugin_info:
                        return plugin_info
                return None
            d = info.to_dict()
            installed_info = self._installed.get(name, {})
            d["is_installed"] = name in self._installed
            d["is_enabled"] = installed_info.get("enabled", info.is_enabled)
            d["installed_version"] = installed_info.get("version", "")
            d["installed_at"] = installed_info.get("installed_at", "")
            d["current_config"] = self._configs.get(name, info.default_config)
            # 合并 PluginManager 中的实时信息
            pm = self._get_plugin_manager()
            if pm:
                runtime_info = pm.get_plugin_info(name)
                if runtime_info:
                    d["runtime"] = runtime_info
            return d
    
    def list_categories(self) -> List[Dict[str, str]]:
        """获取所有分类"""
        with self._lock:
            cats = {}
            for info in self._catalog.values():
                if info.category not in cats:
                    cats[info.category] = {"id": info.category, "name": info.category, "count": 0}
                cats[info.category]["count"] += 1
            return list(cats.values())
    
    def list_installed(self) -> List[Dict[str, Any]]:
        """列出已安装的插件"""
        with self._lock:
            result = []
            for name in self._installed.keys():
                info = self._catalog.get(name)
                if info:
                    d = info.to_dict()
                    d["is_installed"] = True
                    d["is_enabled"] = self._installed[name].get("enabled", True)
                    d["installed_at"] = self._installed[name].get("installed_at", "")
                    d["current_config"] = self._configs.get(name, info.default_config)
                    result.append(d)
            return result
    
    # ============================================================
    # 安装 / 卸载
    # ============================================================
    
    def install(self, name: str) -> Dict[str, Any]:
        """安装插件
        
        对于内置插件：直接从 source_path 加载到 PluginManager
        对于第三方插件：从 download_url 下载后加载（预留）
        """
        with self._lock:
            info = self._catalog.get(name)
            if not info:
                return {"ok": False, "error": f"市场中未找到插件: {name}"}
            if name in self._installed:
                return {"ok": False, "error": f"插件已安装: {name}"}
        
        pm = self._get_plugin_manager()
        if pm is None:
            return {"ok": False, "error": "PluginManager 未初始化"}
        
        # 执行安装（加载插件）
        ok = False
        if info.is_builtin and info.source_path and os.path.isfile(info.source_path):
            ok = pm.load_plugin(info.source_path, builtin=True)
        elif info.download_url:
            # ★ 下载第三方插件
            return self._install_from_remote(info)
        else:
            return {"ok": False, "error": "无可用的插件源"}
        
        if not ok:
            return {"ok": False, "error": "插件加载失败"}
        
        # 记录安装信息
        with self._lock:
            self._installed[name] = {
                "version": info.version,
                "installed_at": datetime.now().isoformat(),
                "enabled": True,
                "source": "builtin" if info.is_builtin else "remote",
            }
            # 初始化默认配置
            if name not in self._configs:
                self._configs[name] = dict(info.default_config)
            self._save_state()
        
        return {"ok": True, "name": name, "version": info.version}
    
    def uninstall(self, name: str) -> Dict[str, Any]:
        """卸载插件"""
        with self._lock:
            if name not in self._installed:
                return {"ok": False, "error": f"插件未安装: {name}"}
        
        pm = self._get_plugin_manager()
        if pm is None:
            return {"ok": False, "error": "PluginManager 未初始化"}
        
        # 从 PluginManager 卸载
        ok = pm.unload_plugin(name)
        if not ok:
            return {"ok": False, "error": "插件卸载失败"}
        
        with self._lock:
            self._installed.pop(name, None)
            self._configs.pop(name, None)
            self._save_state()
        
        return {"ok": True, "name": name}
    
    # ============================================================
    # 启用 / 禁用
    # ============================================================
    
    def enable(self, name: str) -> Dict[str, Any]:
        """启用插件"""
        with self._lock:
            if name not in self._installed:
                return {"ok": False, "error": f"插件未安装: {name}"}
        
        pm = self._get_plugin_manager()
        if pm is None:
            return {"ok": False, "error": "PluginManager 未初始化"}
        
        ok = pm.enable_plugin(name)
        if not ok:
            return {"ok": False, "error": "启用失败：插件未加载"}
        
        with self._lock:
            if name in self._installed:
                self._installed[name]["enabled"] = True
                self._save_state()
        
        return {"ok": True, "name": name}
    
    def disable(self, name: str) -> Dict[str, Any]:
        """禁用插件"""
        with self._lock:
            if name not in self._installed:
                return {"ok": False, "error": f"插件未安装: {name}"}
        
        pm = self._get_plugin_manager()
        if pm is None:
            return {"ok": False, "error": "PluginManager 未初始化"}
        
        ok = pm.disable_plugin(name)
        if not ok:
            return {"ok": False, "error": "禁用失败：插件未加载"}
        
        with self._lock:
            if name in self._installed:
                self._installed[name]["enabled"] = False
                self._save_state()
        
        return {"ok": True, "name": name}
    
    # ============================================================
    # 本地插件创建（v4.8: 无需远程服务器）
    # ============================================================

    # 插件模板 — 用户可在本地创建自己的插件骨架
    _PLUGIN_TEMPLATE = '''# -*- coding: utf-8 -*-
"""
{display_name} — Lemon Code Agent 插件
{description}
"""

from standard_mode.core.plugin_system import IPlugin, ToolDefinition, HookPoint


class {class_name}(IPlugin):
    """{display_name}"""

    @property
    def name(self) -> str:
        return "{name}"

    @property
    def version(self) -> str:
        return "{version}"

    @property
    def description(self) -> str:
        return "{description}"

    def get_tools(self):
        return [
            ToolDefinition(
                name="{name}_tool",
                description="{display_name} 工具",
                handler=self._execute,
            )
        ]

    def get_hooks(self):
        return []

    def _execute(self, **kwargs):
        """执行插件主逻辑"""
        return {{"ok": True, "message": "{display_name} 执行成功"}}
'''

    def create_local_plugin(self, name: str, display_name: str = "",
                           description: str = "", category: str = "tool",
                           icon: str = "🧩") -> Dict[str, Any]:
        """★ v4.8: 从模板创建本地插件，无需远程服务器。

        Args:
            name: 插件唯一标识（英文，小写+下划线）
            display_name: 展示名称
            description: 插件描述
            category: 分类
            icon: 图标 emoji

        Returns:
            {"ok": True, "path": "..."} 或 {"ok": False, "error": "..."}
        """
        if not name or not name.replace("_", "").isalnum():
            return {"ok": False, "error": "插件名仅支持小写字母、数字和下划线"}
        if name in self._catalog:
            return {"ok": False, "error": f"插件名已存在: {name}"}

        display_name = display_name or name
        description = description or f"{display_name} 插件"
        class_name = "".join(p.capitalize() for p in name.split("_"))

        # 创建插件目录
        plugin_dir = os.path.join(
            os.path.expanduser("~"), ".mimo_agent", "plugins", name
        )
        os.makedirs(plugin_dir, exist_ok=True)

        # 生成插件代码
        code = self._PLUGIN_TEMPLATE.format(
            name=name,
            display_name=display_name,
            description=description,
            class_name=class_name,
            version="1.0.0",
        )
        init_path = os.path.join(plugin_dir, "__init__.py")
        with open(init_path, "w", encoding="utf-8") as f:
            f.write(code)

        # 注册到目录
        info = MarketPluginInfo(
            name=name, display_name=display_name,
            description=description, version="1.0.0",
            author="local_user", category=category,
            icon=icon, tags=["local", "custom"],
            is_builtin=False, source_path=init_path,
        )
        with self._lock:
            self._catalog[name] = info

        # 自动安装到 PluginManager
        pm = self._get_plugin_manager()
        if pm and pm.load_plugin(init_path, builtin=False):
            with self._lock:
                self._installed[name] = {
                    "version": "1.0.0",
                    "installed_at": datetime.now().isoformat(),
                    "enabled": True,
                }
                self._save_state()
            return {"ok": True, "path": plugin_dir, "name": name}

        return {"ok": True, "path": plugin_dir, "name": name,
                "warning": "插件已创建但未自动加载，请重启应用或手动刷新"}

    def list_local_plugins(self) -> List[Dict[str, Any]]:
        """列出所有本地创建的插件"""
        result = []
        local_dir = os.path.join(os.path.expanduser("~"), ".mimo_agent", "plugins")
        if os.path.isdir(local_dir):
            for item in os.listdir(local_dir):
                item_path = os.path.join(local_dir, item)
                init_file = os.path.join(item_path, "__init__.py")
                if os.path.isfile(init_file):
                    result.append({"name": item, "path": item_path})
        return result

    # ============================================================
    # 配置管理
    # ============================================================
    
    def get_config(self, name: str) -> Dict[str, Any]:
        """获取插件配置"""
        with self._lock:
            info = self._catalog.get(name)
            default = info.default_config if info else {}
            user_config = self._configs.get(name, {})
            # 合并：用户配置覆盖默认
            merged = dict(default)
            merged.update(user_config)
            return merged
    
    def set_config(self, name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """设置插件配置"""
        with self._lock:
            info = self._catalog.get(name)
            if not info:
                return {"ok": False, "error": f"未知插件: {name}"}
            # 校验配置项
            validated = {}
            for key, value in config.items():
                schema = info.config_schema.get(key)
                if schema is None:
                    # 未知配置项，允许但警告
                    validated[key] = value
                    continue
                # 类型校验
                vtype = schema.get("type", "")
                if vtype == "integer":
                    try:
                        v = int(value)
                        if "min" in schema and v < schema["min"]:
                            v = schema["min"]
                        if "max" in schema and v > schema["max"]:
                            v = schema["max"]
                        validated[key] = v
                    except (TypeError, ValueError):
                        validated[key] = schema.get("default")
                elif vtype == "boolean":
                    validated[key] = bool(value)
                elif vtype == "list":
                    if isinstance(value, list):
                        validated[key] = value
                    elif isinstance(value, str):
                        validated[key] = [s.strip() for s in value.split(",")]
                    else:
                        validated[key] = schema.get("default", [])
                else:
                    validated[key] = value
            self._configs[name] = validated
            self._save_state()
        return {"ok": True, "name": name, "config": validated}
    
    def reset_config(self, name: str) -> Dict[str, Any]:
        """重置插件配置为默认"""
        with self._lock:
            info = self._catalog.get(name)
            if not info:
                return {"ok": False, "error": f"未知插件: {name}"}
            self._configs[name] = dict(info.default_config)
            self._save_state()
        return {"ok": True, "name": name, "config": self._configs[name]}
    
    def get_config_schema(self, name: str) -> Dict[str, Any]:
        """获取插件配置 schema（供前端渲染配置面板）"""
        with self._lock:
            info = self._catalog.get(name)
            if not info:
                return {}
            return {
                "schema": info.config_schema,
                "default": info.default_config,
                "current": self.get_config(name),
            }
    
    # ============================================================
    # 热重载
    # ============================================================
    
    def reload(self, name: str) -> Dict[str, Any]:
        """热重载插件（开发模式）"""
        with self._lock:
            if name not in self._installed:
                return {"ok": False, "error": f"插件未安装: {name}"}
        
        pm = self._get_plugin_manager()
        if pm is None:
            return {"ok": False, "error": "PluginManager 未初始化"}
        
        ok = pm.reload_plugin(name)
        if not ok:
            return {"ok": False, "error": "热重载失败"}
        
        return {"ok": True, "name": name}
    
    # ============================================================
    # 搜索
    # ============================================================
    
    def search(self, query: str) -> List[Dict[str, Any]]:
        """搜索插件"""
        if not query:
            return self.list_plugins()
        q = query.lower()
        with self._lock:
            result = []
            for info in self._catalog.values():
                if (q in info.name.lower() or 
                    q in info.display_name.lower() or 
                    q in info.description.lower() or
                    any(q in t.lower() for t in info.tags)):
                    d = info.to_dict()
                    d["is_installed"] = info.name in self._installed
                    result.append(d)
            return result
    
    # ============================================================
    # 初始化：自动安装内置插件
    # ============================================================
    
    def auto_install_builtin(self):
        """自动安装所有内置插件（首次启动时调用）"""
        with self._lock:
            builtin_names = [n for n, info in self._catalog.items() if info.is_builtin]
        
        for name in builtin_names:
            if name not in self._installed:
                result = self.install(name)
                if result.get("ok"):
                    print(f"[PluginMarket] 自动安装: {name}")
                else:
                    print(f"[PluginMarket] 安装失败 {name}: {result.get('error')}")
    
    # ============================================================
    # 远程插件目录 API
    # ============================================================

    # ★ v4.8: 远程目录源默认关闭（无需后端服务器）
    # 用户可通过环境变量 MIMO_PLUGIN_CATALOG_URLS 启用远程源
    _REMOTE_CATALOG_URLS = [
        u for u in os.getenv(
            "MIMO_PLUGIN_CATALOG_URLS",
            "",
        ).split(",") if u.strip()
    ]
    _REMOTE_TIMEOUT = float(os.getenv("MIMO_PLUGIN_TIMEOUT", "8"))
    # v4.8: 本地优先 — 始终加载本地兜底目录作为主数据源
    _LOCAL_FALLBACK = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "catalog_fallback.json"
    )

    def _fetch_remote_catalog(self):
        """★ v4.8: 本地优先的插件目录加载。

        1. 始终加载本地 catalog_fallback.json 作为主数据源（离线可用）
        2. 仅当配置了 MIMO_PLUGIN_CATALOG_URLS 环境变量时才尝试远程源
        3. 多源插件去重合并，本地优先
        """
        merged_count = 0
        # 1) 本地兜底 JSON — 始终加载作为基础
        if os.path.isfile(self._LOCAL_FALLBACK):
            try:
                import json as _json
                with open(self._LOCAL_FALLBACK, "r", encoding="utf-8") as f:
                    plugins = _json.load(f).get("plugins", [])
                merged_count += self._merge_remote_plugins(plugins, "local-fallback")
            except Exception as e:
                print(f"[PluginMarket] 本地兜底目录加载失败: {e}")
        # 2) 远程源 — 仅当用户配置了环境变量时才启用
        if self._REMOTE_CATALOG_URLS and REQUESTS_AVAILABLE:
            for url in self._REMOTE_CATALOG_URLS:
                try:
                    resp = requests.get(url, timeout=self._REMOTE_TIMEOUT)
                    if resp.status_code == 200:
                        data = resp.json()
                        plugins = data.get("plugins", [])
                        merged_count += self._merge_remote_plugins(plugins, url)
                except Exception as e:
                    print(f"[PluginMarket] 远程源 {url} 加载失败: {e}")
        if merged_count:
            print(f"[PluginMarket] 已加载 {merged_count} 个插件（本地目录）")

    def _merge_remote_plugins(self, plugins, source: str) -> int:
        """把一批插件定义并入目录（按 name 去重），返回新增数量"""
        count = 0
        for p in plugins:
            name = p.get("name", "")
            if not name or name in self._catalog:
                continue
            self._catalog[name] = MarketPluginInfo(
                name=name, display_name=p.get("display_name", name),
                description=p.get("description", ""),
                version=p.get("version", "1.0.0"),
                author=p.get("author", ""),
                category=p.get("category", "general"),
                icon=p.get("icon", "🧩"),
                tags=p.get("tags", []),
                is_builtin=False, download_url=p.get("download_url", ""),
            )
            count += 1
        return count

    def _install_from_remote(self, info: MarketPluginInfo) -> Dict[str, Any]:
        """下载并安装第三方插件（zip 流式下载 + 解压）"""
        if not REQUESTS_AVAILABLE:
            return {"ok": False, "error": "需要安装 requests 库"}
        pm = self._get_plugin_manager()
        if pm is None:
            return {"ok": False, "error": "PluginManager 未初始化"}
        try:
            resp = requests.get(info.download_url, stream=True, timeout=120)
            resp.raise_for_status()
            fd, tmp = tempfile.mkstemp(suffix=".zip")
            os.close(fd)
            with open(tmp, "wb") as tf:
                for c in resp.iter_content(8192):
                    if c: tf.write(c)
            extract = tempfile.mkdtemp()
            with zipfile.ZipFile(tmp, "r") as zf:
                zf.extractall(extract)
            for root, _, files in os.walk(extract):
                for fn in files:
                    if fn.endswith(".py"):
                        pm.load_plugin(os.path.join(root, fn), builtin=False)
            with self._lock:
                self._installed[info.name] = {
                    "version": info.version,
                    "installed_at": datetime.now().isoformat(),
                    "enabled": True, "source": "remote",
                }
                self._save_state()
            return {"ok": True, "name": info.name}
        except Exception as e:
            return {"ok": False, "error": f"远程安装失败: {e}"}

    # ============================================================
    # 统计
    # ============================================================
    
    def get_summary(self) -> Dict[str, Any]:
        """获取市场摘要"""
        with self._lock:
            total = len(self._catalog)
            installed = len(self._installed)
            enabled = sum(1 for v in self._installed.values() if v.get("enabled", False))
            categories = {}
            for info in self._catalog.values():
                categories[info.category] = categories.get(info.category, 0) + 1
            return {
                "total_plugins": total,
                "installed": installed,
                "enabled": enabled,
                "categories": categories,
                "builtin_count": sum(1 for i in self._catalog.values() if i.is_builtin),
            }


# ============================================================
# 全局单例
# ============================================================

_global_market: Optional[PluginMarket] = None
_market_lock = threading.Lock()


def get_plugin_market(plugin_manager=None) -> PluginMarket:
    """获取全局 PluginMarket 单例"""
    global _global_market
    with _market_lock:
        if _global_market is None:
            _global_market = PluginMarket(plugin_manager=plugin_manager)
        return _global_market
