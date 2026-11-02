# -*- coding: utf-8 -*-
"""
插件系统 — 自定义 Tool + Skill 热加载
=====================================
核心能力：
- 插件注册/发现：自动扫描插件目录
- 自定义 Tool：扩展 Agent 能力（代码格式化、Lint、测试等）
- Skill 热加载：运行时加载/卸载 Skill
- Hook 生命周期：before_task / after_task / on_error
- 插件隔离：每个插件独立运行，异常不影响主程序

架构：
┌─────────────────────────────────────────┐
│           PluginManager                  │
│  ┌───────────┐ ┌───────────┐           │
│  │ Plugin A   │ │ Plugin B   │  ...      │
│  │ - Tool 1   │ │ - Tool 1   │           │
│  │ - Hook 1   │ │ - Skill 1  │           │
│  └───────────┘ └───────────┘           │
│  ┌─────────────────────────────────┐    │
│  │  SkillRegistry                  │    │
│  │  - code_formatter               │    │
│  │  - lint_checker                 │    │
│  │  - test_runner                  │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
"""

import os
import sys
import json
import threading
import importlib
import importlib.util
import traceback
from typing import List, Dict, Optional, Callable, Any, Type
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from PyQt5.QtCore import QObject, pyqtSignal


# ============================================================
# 基础类型定义
# ============================================================

class HookPoint(Enum):
    """Hook 挂载点"""
    BEFORE_TASK = "before_task"       # 任务执行前
    AFTER_TASK = "after_task"         # 任务执行后
    ON_ERROR = "on_error"             # 错误发生时
    ON_STARTUP = "on_startup"         # 系统启动时
    ON_SHUTDOWN = "on_shutdown"       # 系统关闭时
    ON_FILE_OPEN = "on_file_open"     # 文件打开时
    ON_FILE_SAVE = "on_file_save"     # 文件保存时
    ON_MESSAGE_SEND = "on_message_send"  # 消息发送前
    ON_MESSAGE_RECEIVE = "on_message_receive"  # 消息接收后


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    handler: Optional[Callable] = None
    category: str = "general"


@dataclass
class SkillDefinition:
    """Skill 定义"""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# IPlugin — 插件接口
# ============================================================

class IPlugin(ABC):
    """插件抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """插件名称"""
        ...
    
    @property
    @abstractmethod
    def version(self) -> str:
        """插件版本"""
        ...
    
    @property
    def description(self) -> str:
        return ""

    @property
    def icon(self) -> str:
        """插件图标，建议返回内联 SVG 字符串或 SVG 图标名称；空字符串表示无图标。"""
        return ""
    
    def on_load(self) -> bool:
        """插件加载时调用，返回 True 表示加载成功"""
        return True

    def on_unload(self):
        """插件卸载时调用"""
        pass

    def on_enable(self) -> bool:
        """插件启用时调用，返回 True 表示启用成功"""
        return True

    def on_disable(self):
        """插件禁用时调用"""
        pass
    
    def get_tools(self) -> List[ToolDefinition]:
        """返回插件提供的工具列表"""
        return []
    
    def get_hooks(self) -> Dict[HookPoint, List[Callable]]:
        """返回插件注册的 Hook"""
        return {}
    
    def get_skills(self) -> List[SkillDefinition]:
        """返回插件提供的 Skill 列表"""
        return []


# ============================================================
# Skill — 可热加载的技能模块
# ============================================================

class Skill:
    """可热加载的技能模块"""
    
    def __init__(self, name: str, description: str = "", version: str = "1.0.0", icon: str = "skill_default"):
        self.name = name
        self.description = description
        self.version = version
        self.icon = icon  # SVG 图标名称
        self._enabled = True
        self._hooks: Dict[HookPoint, List[Callable]] = {}
        self._tools: List[ToolDefinition] = []
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def enable(self):
        self._enabled = True
    
    def disable(self):
        self._enabled = False
    
    def register_hook(self, point: HookPoint, callback: Callable):
        """注册 Hook"""
        if point not in self._hooks:
            self._hooks[point] = []
        self._hooks[point].append(callback)
    
    def register_tool(self, tool: ToolDefinition):
        """注册工具"""
        tool.handler = tool.handler or (lambda **kwargs: f"Tool '{tool.name}' executed")
        self._tools.append(tool)
    
    def get_tools(self) -> List[ToolDefinition]:
        return self._tools if self._enabled else []
    
    def get_hooks(self) -> Dict[HookPoint, List[Callable]]:
        return self._hooks if self._enabled else {}


# ============================================================
# 内置 Skills
# ============================================================

class CodeFormatterSkill(Skill):
    """代码格式化 Skill"""
    
    def __init__(self):
        super().__init__("code_formatter", "自动代码格式化", "1.0.0", icon="skill_formatter")
        self.register_tool(ToolDefinition(
            name="format_code",
            description="格式化当前代码",
            parameters=[
                {"name": "code", "type": "string", "description": "要格式化的代码"},
                {"name": "language", "type": "string", "description": "编程语言"},
            ],
            category="code",
        ))
        self.register_tool(ToolDefinition(
            name="format_file",
            description="格式化指定文件",
            parameters=[
                {"name": "file_path", "type": "string", "description": "文件路径"},
            ],
            category="code",
        ))


class LintCheckerSkill(Skill):
    """代码检查 Skill"""
    
    def __init__(self):
        super().__init__("lint_checker", "代码质量检查", "1.0.0", icon="skill_lint")
        self.register_tool(ToolDefinition(
            name="lint_check",
            description="检查代码质量",
            parameters=[
                {"name": "code", "type": "string", "description": "要检查的代码"},
                {"name": "language", "type": "string", "description": "编程语言"},
            ],
            category="code",
        ))


class TestRunnerSkill(Skill):
    """测试运行 Skill"""
    
    def __init__(self):
        super().__init__("test_runner", "测试运行器", "1.0.0", icon="skill_test")
        self.register_tool(ToolDefinition(
            name="run_tests",
            description="运行项目测试",
            parameters=[
                {"name": "test_path", "type": "string", "description": "测试文件路径（可选）"},
            ],
            category="test",
        ))


class ProjectScaffoldSkill(Skill):
    """项目脚手架 Skill"""
    
    def __init__(self):
        super().__init__("project_scaffold", "项目脚手架生成", "1.0.0", icon="skill_scaffold")
        self.register_tool(ToolDefinition(
            name="create_project",
            description="创建新项目脚手架",
            parameters=[
                {"name": "project_name", "type": "string", "description": "项目名称"},
                {"name": "template", "type": "string", "description": "模板类型 (python/js/web)"},
            ],
            category="project",
        ))


class GitHelperSkill(Skill):
    """Git 辅助 Skill"""
    
    def __init__(self):
        super().__init__("git_helper", "Git 操作辅助", "1.0.0", icon="skill_git")
        self.register_tool(ToolDefinition(
            name="git_commit_all",
            description="暂存所有变更并提交",
            parameters=[
                {"name": "message", "type": "string", "description": "提交信息"},
            ],
            category="git",
        ))
        self.register_tool(ToolDefinition(
            name="git_create_branch",
            description="创建并切换到新分支",
            parameters=[
                {"name": "branch_name", "type": "string", "description": "分支名称"},
            ],
            category="git",
        ))


# ============================================================
# PluginPermission — 插件权限系统
# ============================================================

@dataclass
class PluginPermission:
    """插件权限声明
    
    权限粒度：
    - file_access: 文件读写权限（"none" / "read" / "write" / "full"）
    - network_access: 网络访问权限（True/False）
    - system_command: 系统命令执行权限（True/False）
    - allowed_paths: 允许访问的文件路径白名单（空列表表示受限于 file_access 策略）
    - allowed_domains: 允许访问的网络域名白名单（空列表表示任意）
    """
    file_access: str = "none"          # none / read / write / full
    network_access: bool = False
    system_command: bool = False
    allowed_paths: List[str] = field(default_factory=list)
    allowed_domains: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_access": self.file_access,
            "network_access": self.network_access,
            "system_command": self.system_command,
            "allowed_paths": self.allowed_paths,
            "allowed_domains": self.allowed_domains,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginPermission":
        return cls(
            file_access=data.get("file_access", "none"),
            network_access=data.get("network_access", False),
            system_command=data.get("system_command", False),
            allowed_paths=data.get("allowed_paths", []),
            allowed_domains=data.get("allowed_domains", []),
        )
    
    @classmethod
    def full(cls) -> "PluginPermission":
        """完全权限（仅用于可信内置插件）"""
        return cls(file_access="full", network_access=True, system_command=True)
    
    @classmethod
    def sandboxed(cls) -> "PluginPermission":
        """沙箱权限（第三方插件默认）"""
        return cls(file_access="none", network_access=False, system_command=False)


class PermissionDeniedError(PermissionError):
    """插件权限不足异常"""
    pass


class PluginPermissionChecker:
    """插件权限检查器：在插件执行 Tool / Hook 时校验权限"""
    
    # 敏感操作的关键字（用于静态扫描 Tool handler 的行为）
    _FILE_WRITE_KEYWORDS = ("open(", "os.remove", "os.rmdir", "shutil.", "os.unlink", "pathlib.Path")
    _NETWORK_KEYWORDS = ("socket", "urllib", "requests", "http.client", "aiohttp", "websocket")
    _SYSTEM_KEYWORDS = ("os.system", "subprocess", "os.popen", "os.exec", "os.spawn")
    
    def __init__(self, permission: PluginPermission):
        self.permission = permission
    
    def check_file_access(self, path: str, mode: str = "read") -> bool:
        """检查文件访问权限"""
        if self.permission.file_access == "full":
            return True
        if mode == "read" and self.permission.file_access in ("read", "write"):
            return True
        if mode == "write" and self.permission.file_access in ("write",):
            return True
        # 白名单检查
        if self.permission.allowed_paths:
            abs_path = os.path.abspath(path)
            for allowed in self.permission.allowed_paths:
                if abs_path.startswith(os.path.abspath(allowed)):
                    return True
        return False
    
    def check_network(self, domain: str = "") -> bool:
        if not self.permission.network_access:
            return False
        if not domain or not self.permission.allowed_domains:
            return True
        return any(d in domain for d in self.permission.allowed_domains)
    
    def check_system_command(self) -> bool:
        return self.permission.system_command
    
    def validate_tool_handler(self, handler: Callable) -> bool:
        """静态扫描 Tool handler 源代码，校验是否使用了越权操作"""
        try:
            import inspect
            src = inspect.getsource(handler)
        except (OSError, TypeError):
            return True  # 无法获取源码，放行（已通过沙箱隔离）
        
        if not self.permission.system_command and any(kw in src for kw in self._SYSTEM_KEYWORDS):
            return False
        if not self.permission.network_access and any(kw in src for kw in self._NETWORK_KEYWORDS):
            return False
        if self.permission.file_access == "none" and any(kw in src for kw in self._FILE_WRITE_KEYWORDS):
            return False
        return True


# ============================================================
# PluginSandbox — 插件沙箱（线程隔离 + 异常捕获）
# ============================================================

class PluginSandbox:
    """插件沙箱：在独立线程中执行插件操作，异常不影响主程序
    
    特性：
    - 每个 Tool / Hook 调用都在工作线程中执行
    - 异常被捕获并通过回调通知主程序
    - 支持超时控制
    - 线程安全的任务队列
    """
    
    def __init__(self, plugin_name: str, permission: PluginPermission, 
                 max_workers: int = 2, default_timeout: float = 30.0):
        self.plugin_name = plugin_name
        self.permission = permission
        self.default_timeout = default_timeout
        self._executor = None  # 延迟创建 ThreadPoolExecutor
        self._lock = threading.Lock()
        self._closed = False
        try:
            from concurrent.futures import ThreadPoolExecutor
            self._executor = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix=f"plugin-{plugin_name}",
            )
        except Exception:
            self._executor = None
    
    def execute(self, func: Callable, *args, timeout: float = None, **kwargs) -> Any:
        """在沙箱中执行函数
        
        - 返回函数的返回值
        - 异常被捕获并重新抛出为 RuntimeError（附带插件名）
        - 超时抛出 TimeoutError
        """
        if self._closed:
            raise RuntimeError(f"沙箱已关闭: {self.plugin_name}")
        if self._executor is None:
            # 降级：直接同步执行（仍带异常隔离）
            try:
                return func(*args, **kwargs)
            except Exception as e:
                raise RuntimeError(f"插件 {self.plugin_name} 执行错误: {e}") from e
        
        from concurrent.futures import TimeoutError as FutureTimeout
        future = self._executor.submit(self._safe_call, func, *args, **kwargs)
        try:
            return future.result(timeout=timeout or self.default_timeout)
        except FutureTimeout:
            raise TimeoutError(f"插件 {self.plugin_name} 执行超时")
        except Exception as e:
            raise RuntimeError(f"插件 {self.plugin_name} 执行错误: {e}") from e
    
    def _safe_call(self, func: Callable, *args, **kwargs):
        """安全调用包装：捕获异常并打印堆栈"""
        try:
            return func(*args, **kwargs)
        except Exception:
            traceback.print_exc()
            raise
    
    def shutdown(self):
        """关闭沙箱，释放线程资源"""
        with self._lock:
            self._closed = True
            if self._executor is not None:
                try:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    try:
                        self._executor.shutdown(wait=False)
                    except Exception:
                        pass
                self._executor = None


# ============================================================
# PluginManager — 插件管理器
# ============================================================

class PluginManager(QObject):
    """
    插件管理器
    
    功能：
    - 插件注册/发现/加载/卸载
    - Skill 热加载/卸载
    - Hook 生命周期管理
    - Tool 注册和调用
    """
    
    # 信号
    plugin_loaded = pyqtSignal(str)      # 插件名称
    plugin_unloaded = pyqtSignal(str)    # 插件名称
    plugin_error = pyqtSignal(str, str)  # (plugin_name, error)
    skill_loaded = pyqtSignal(str)       # skill 名称
    skill_unloaded = pyqtSignal(str)     # skill 名称
    tool_executed = pyqtSignal(str, str) # (tool_name, result_summary)
    hook_triggered = pyqtSignal(str, str) # (hook_point, plugin_name)
    # 新增：插件热加载信号
    plugin_reloaded = pyqtSignal(str)    # 插件重载完成
    permission_denied = pyqtSignal(str, str)  # (plugin_name, operation)

    def __init__(self, plugin_dir: str = "", parent=None):
        super().__init__(parent)
        self._plugins: Dict[str, IPlugin] = {}
        self._skills: Dict[str, Skill] = {}
        self._tools: Dict[str, ToolDefinition] = {}
        self._hooks: Dict[HookPoint, List[tuple]] = {hp: [] for hp in HookPoint}
        self._plugin_dir = plugin_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "plugins"
        )
        # 内置插件目录（与 plugin_system.py 同级的 builtin_plugins/）
        self._builtin_plugins_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "builtin_plugins"
        )
        self._lock = threading.RLock()  # 改为可重入锁，支持嵌套调用
        # 新增：插件元数据（路径、模块、权限、沙箱）
        self._plugin_paths: Dict[str, str] = {}           # name -> 文件/目录路径
        self._plugin_modules: Dict[str, Any] = {}          # name -> 已加载的模块对象
        self._plugin_permissions: Dict[str, PluginPermission] = {}  # name -> 权限
        self._plugin_sandboxes: Dict[str, PluginSandbox] = {}      # name -> 沙箱
        self._plugin_enabled: Dict[str, bool] = {}         # name -> 是否启用
        self._plugin_metadata: Dict[str, Dict[str, Any]] = {}  # name -> 元数据（作者、描述、截图等）
    
    # ================================================================
    # 插件管理
    # ================================================================
    
    def register_plugin(self, plugin: IPlugin, permission: PluginPermission = None,
                       path: str = "", module: Any = None) -> bool:
        """注册插件
        
        参数：
            plugin: IPlugin 实例
            permission: 插件权限（None 表示完全权限，仅用于可信内置插件）
            path: 插件源文件/目录路径（用于后续 reload）
            module: 已加载的模块对象（用于后续 unload 时清理）
        """
        with self._lock:
            if plugin.name in self._plugins:
                return False
            
            # 权限：默认为完全权限（兼容旧代码）
            perm = permission or PluginPermission.full()
            
            # 权限校验：扫描 Tool handler 是否越权
            checker = PluginPermissionChecker(perm)
            for tool in plugin.get_tools():
                if tool.handler and not checker.validate_tool_handler(tool.handler):
                    self.permission_denied.emit(plugin.name, f"tool:{tool.name}")
                    self.plugin_error.emit(plugin.name, f"Tool '{tool.name}' 越权，拒绝加载")
                    return False
            
            # 创建沙箱
            sandbox = PluginSandbox(plugin.name, perm)
            
            try:
                # 在沙箱中执行 on_load
                if not sandbox.execute(plugin.on_load):
                    sandbox.shutdown()
                    return False
            except Exception as e:
                sandbox.shutdown()
                self.plugin_error.emit(plugin.name, str(e))
                return False
            
            self._plugins[plugin.name] = plugin
            self._plugin_permissions[plugin.name] = perm
            self._plugin_sandboxes[plugin.name] = sandbox
            self._plugin_enabled[plugin.name] = True
            if path:
                self._plugin_paths[plugin.name] = path
            if module is not None:
                self._plugin_modules[plugin.name] = module
            
            # 注册工具
            for tool in plugin.get_tools():
                self._tools[tool.name] = tool
            
            # 注册 Hook
            for point, callbacks in plugin.get_hooks().items():
                for cb in callbacks:
                    self._hooks[point].append((plugin.name, cb))
            
            # 注册 Skill
            for skill in plugin.get_skills():
                self._skills[skill.name] = Skill(
                    skill.name, skill.description, skill.version
                )
                self.skill_loaded.emit(skill.name)
        
        self.plugin_loaded.emit(plugin.name)
        return True
    
    def unregister_plugin(self, name: str) -> bool:
        """注销插件"""
        with self._lock:
            if name not in self._plugins:
                return False
            
            plugin = self._plugins.pop(name)
            
            # 在沙箱中执行 on_unload（如果存在）
            sandbox = self._plugin_sandboxes.get(name)
            if sandbox:
                try:
                    sandbox.execute(plugin.on_unload)
                except Exception as e:
                    self.plugin_error.emit(name, str(e))
            else:
                try:
                    plugin.on_unload()
                except Exception as e:
                    self.plugin_error.emit(name, str(e))
            
            # 移除工具
            for tool in plugin.get_tools():
                self._tools.pop(tool.name, None)
            
            # 移除 Hook
            for point in self._hooks:
                self._hooks[point] = [
                    (pn, cb) for pn, cb in self._hooks[point]
                    if pn != name
                ]
            
            # 清理元数据
            self._plugin_paths.pop(name, None)
            self._plugin_modules.pop(name, None)
            self._plugin_permissions.pop(name, None)
            self._plugin_enabled.pop(name, None)
            self._plugin_metadata.pop(name, None)
            
            # 关闭沙箱，释放线程
            if sandbox:
                sandbox.shutdown()
                self._plugin_sandboxes.pop(name, None)
            
            # 清理 sys.modules 中的插件模块
            mod = self._plugin_modules.get(name)
            if mod is not None:
                mod_name = getattr(mod, "__name__", "")
                if mod_name and mod_name in sys.modules:
                    try:
                        del sys.modules[mod_name]
                    except Exception:
                        pass
        
        self.plugin_unloaded.emit(name)
        return True
    
    def get_plugin(self, name: str) -> Optional[IPlugin]:
        return self._plugins.get(name)
    
    def get_all_plugins(self) -> List[IPlugin]:
        return list(self._plugins.values())
    
    def discover_plugins(self):
        """扫描插件目录发现插件（含内置插件目录）"""
        scanned = set()
        # 1. 扫描用户插件目录
        if os.path.isdir(self._plugin_dir):
            for item in os.listdir(self._plugin_dir):
                item_path = os.path.join(self._plugin_dir, item)
                if os.path.isdir(item_path):
                    init_file = os.path.join(item_path, "__init__.py")
                    if os.path.isfile(init_file):
                        self._load_plugin_from_dir(item, item_path)
                        scanned.add(item)
                elif os.path.isfile(item_path) and item.endswith(".py") and item != "__init__.py":
                    self.load_plugin(item_path)
                    scanned.add(item)
        # 2. 扫描内置插件目录
        if os.path.isdir(self._builtin_plugins_dir):
            for item in os.listdir(self._builtin_plugins_dir):
                if item in scanned:
                    continue
                item_path = os.path.join(self._builtin_plugins_dir, item)
                if os.path.isdir(item_path):
                    init_file = os.path.join(item_path, "__init__.py")
                    if os.path.isfile(init_file):
                        self._load_plugin_from_dir(item, item_path, builtin=True)
                elif os.path.isfile(item_path) and item.endswith(".py") and item != "__init__.py":
                    self.load_plugin(item_path, builtin=True)
    
    def _load_plugin_from_dir(self, name: str, path: str, builtin: bool = False):
        """从目录加载插件"""
        try:
            # 将插件目录加入 sys.path
            if path not in sys.path:
                sys.path.insert(0, path)
            
            module = importlib.import_module(name)
            
            # 查找 IPlugin 子类
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, IPlugin) and 
                    attr is not IPlugin):
                    plugin = attr()
                    perm = PluginPermission.full() if builtin else PluginPermission.sandboxed()
                    self.register_plugin(plugin, permission=perm, path=path, module=module)
                    break
        except Exception as e:
            self.plugin_error.emit(name, f"加载失败: {e}")
    
    # ================================================================
    # 热加载 / 卸载 / 重载
    # ================================================================
    
    def _sync_plugin_system_module(self):
        """把主模块（core.plugin_system）注册为 sys.modules 的裸名键。

        解决插件文件 `from plugin_system import IPlugin` 与主程序
        `from core.plugin_system import IPlugin` 双导入导致的类身份不一致。

        ★ 必须无条件覆盖：builtin_skills.py 等文件同样用裸名 `from plugin_system import`
        导入，若已被提前加载会产生一个独立裸模块实例；而 plugin_system.py 与
        core/plugin_system.py 物理上是同一文件，统一指向 core 版本最一致。
        """
        try:
            main_mod = sys.modules.get("core.plugin_system")
            if main_mod is None:
                # 本模块即主模块（当前正以 core.plugin_system 被加载）
                main_mod = sys.modules.get(__name__)
            if main_mod is not None:
                sys.modules["plugin_system"] = main_mod
        except Exception:
            pass

    def load_plugin(self, plugin_path: str, builtin: bool = False) -> bool:
        """从 .py 文件加载插件
        
        参数：
            plugin_path: .py 文件绝对路径
            builtin: 是否为内置可信插件（决定默认权限）
        
        返回：
            True 加载成功，False 失败
        """
        if not os.path.isfile(plugin_path):
            self.plugin_error.emit(plugin_path, "文件不存在")
            return False
        
        try:
            # 用 importlib.util 加载，避免触发 package __init__.py 链
            mod_name = f"_plugin_{os.path.splitext(os.path.basename(plugin_path))[0]}_{id(plugin_path)}"
            spec = importlib.util.spec_from_file_location(mod_name, plugin_path)
            if spec is None or spec.loader is None:
                self.plugin_error.emit(plugin_path, "无法创建模块 spec")
                return False
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            # ★ 修复 v4.4.3（插件双导入导致 IPlugin 身份不一致）：
            # 插件文件用 `from plugin_system import IPlugin`（靠 _parent_dir 进 sys.path），
            # 而主程序用 `from core.plugin_system import IPlugin` —— 两者是**不同模块对象**，
            # 产生两个不同的 IPlugin 类，issubclass(attr, IPlugin) 恒为 False。
            # 方案：exec_module 前，把主模块注册为 sys.modules 的裸名键（'plugin_system'），
            # 使插件内 `from plugin_system import ...` 复用主模块、同一类对象。
            self._sync_plugin_system_module()
            spec.loader.exec_module(module)

            # 查找 IPlugin 子类（兼容两种导入方式：本模块类 或 裸名 plugin_system 类）
            plugin_cls = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and attr is not IPlugin:
                    try:
                        is_sub = issubclass(attr, IPlugin)
                    except TypeError:
                        is_sub = False
                    if is_sub:
                        plugin_cls = attr
                        break
            # 兜底：检查基类链里是否有名为 IPlugin 的抽象基类（防模块名错位）
            if plugin_cls is None:
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if not (isinstance(attr, type) and getattr(attr, "__module__", "").endswith("plugin_system")):
                        continue
                    bases = getattr(attr, "__mro__", ())
                    for b in bases:
                        if b.__name__ == "IPlugin" and getattr(b, "__abstractmethods__", None):
                            plugin_cls = attr
                            break
                    if plugin_cls:
                        break

            if plugin_cls is None:
                self.plugin_error.emit(plugin_path, "未找到 IPlugin 子类")
                return False
            
            plugin = plugin_cls()
            perm = PluginPermission.full() if builtin else PluginPermission.sandboxed()
            return self.register_plugin(plugin, permission=perm, path=plugin_path, module=module)
        except Exception as e:
            self.plugin_error.emit(plugin_path, f"加载失败: {e}\n{traceback.format_exc()}")
            return False
    
    def unload_plugin(self, plugin_name: str) -> bool:
        """卸载插件（清理引用和资源）
        
        - 调用插件 on_unload
        - 移除注册的 Tool / Hook / Skill
        - 关闭沙箱线程池
        - 从 sys.modules 移除插件模块
        """
        return self.unregister_plugin(plugin_name)
    
    def reload_plugin(self, plugin_name: str) -> bool:
        """热重载插件（开发模式下使用）
        
        - 获取插件源路径
        - 卸载旧插件
        - 从源路径重新加载
        """
        with self._lock:
            path = self._plugin_paths.get(plugin_name)
            is_builtin = plugin_name in self._plugin_permissions and \
                         self._plugin_permissions[plugin_name].file_access == "full"
        
        if not path:
            self.plugin_error.emit(plugin_name, "无法重载：未记录插件路径")
            return False
        
        # 卸载
        if not self.unload_plugin(plugin_name):
            self.plugin_error.emit(plugin_name, "重载时卸载失败")
            return False
        
        # 重新加载
        if os.path.isdir(path):
            self._load_plugin_from_dir(plugin_name, path, builtin=is_builtin)
        else:
            ok = self.load_plugin(path, builtin=is_builtin)
            if not ok:
                self.plugin_error.emit(plugin_name, "重载时加载失败")
                return False
        
        self.plugin_reloaded.emit(plugin_name)
        return True
    
    # ================================================================
    # 插件启用 / 禁用 / 配置
    # ================================================================
    
    def enable_plugin(self, name: str) -> bool:
        """启用插件（重新激活其 Tool / Hook）"""
        with self._lock:
            if name not in self._plugins:
                return False
            plugin = self._plugins[name]
            # 调用 on_enable 回调
            try:
                if hasattr(plugin, 'on_enable') and not plugin.on_enable():
                    return False
            except Exception as e:
                print(f"[PluginManager] on_enable 异常: {e}")
                return False
            self._plugin_enabled[name] = True
            # 重新注册工具
            for tool in plugin.get_tools():
                self._tools[tool.name] = tool
            # 重新注册 Hook
            for point, callbacks in plugin.get_hooks().items():
                for cb in callbacks:
                    if (name, cb) not in self._hooks[point]:
                        self._hooks[point].append((name, cb))
        return True

    def disable_plugin(self, name: str) -> bool:
        """禁用插件（移除其 Tool / Hook，但保留实例）"""
        with self._lock:
            if name not in self._plugins:
                return False
            plugin = self._plugins[name]
            # 调用 on_disable 回调
            try:
                if hasattr(plugin, 'on_disable'):
                    plugin.on_disable()
            except Exception as e:
                print(f"[PluginManager] on_disable 异常: {e}")
            self._plugin_enabled[name] = False
            # 移除工具
            for tool in plugin.get_tools():
                self._tools.pop(tool.name, None)
            # 移除 Hook
            for point in self._hooks:
                self._hooks[point] = [
                    (pn, cb) for pn, cb in self._hooks[point] if pn != name
                ]
        return True
    
    def is_plugin_enabled(self, name: str) -> bool:
        return self._plugin_enabled.get(name, False)
    
    def get_plugin_permission(self, name: str) -> Optional[PluginPermission]:
        return self._plugin_permissions.get(name)
    
    def set_plugin_permission(self, name: str, permission: PluginPermission) -> bool:
        """动态调整插件权限"""
        with self._lock:
            if name not in self._plugins:
                return False
            self._plugin_permissions[name] = permission
            # 重建沙箱（权限变化后需要新的沙箱实例）
            old_sandbox = self._plugin_sandboxes.get(name)
            if old_sandbox:
                old_sandbox.shutdown()
            self._plugin_sandboxes[name] = PluginSandbox(name, permission)
        return True
    
    def get_plugin_info(self, name: str) -> Optional[Dict[str, Any]]:
        """获取插件详细信息"""
        with self._lock:
            plugin = self._plugins.get(name)
            if not plugin:
                return None
            perm = self._plugin_permissions.get(name)
            return {
                "name": plugin.name,
                "version": plugin.version,
                "description": plugin.description,
                "path": self._plugin_paths.get(name, ""),
                "enabled": self._plugin_enabled.get(name, False),
                "permission": perm.to_dict() if perm else {},
                "metadata": self._plugin_metadata.get(name, {}),
                "tools": [
                    {"name": t.name, "description": t.description, "category": t.category}
                    for t in plugin.get_tools()
                ],
                "skills": [
                    {"name": s.name, "description": s.description, "version": s.version}
                    for s in plugin.get_skills()
                ],
                "hooks": [hp.value for hp in plugin.get_hooks().keys()],
            }
    
    def list_plugins(self) -> List[Dict[str, Any]]:
        """列出所有已加载插件的信息"""
        return [self.get_plugin_info(name) for name in self._plugins.keys()]
    
    def set_plugin_metadata(self, name: str, metadata: Dict[str, Any]):
        """设置插件元数据（作者、描述、截图等）"""
        with self._lock:
            if name in self._plugins:
                self._plugin_metadata[name] = metadata
    
    # ================================================================
    # Skill 管理
    # ================================================================
    
    def register_skill(self, skill: Skill) -> bool:
        """注册内置 Skill"""
        with self._lock:
            if skill.name in self._skills:
                return False
            self._skills[skill.name] = skill
            
            for tool in skill.get_tools():
                self._tools[tool.name] = tool
        
        self.skill_loaded.emit(skill.name)
        return True
    
    def unregister_skill(self, name: str) -> bool:
        """注销 Skill"""
        with self._lock:
            if name not in self._skills:
                return False
            
            skill = self._skills.pop(name)
            for tool in skill.get_tools():
                self._tools.pop(tool.name, None)
        
        self.skill_unloaded.emit(name)
        return True
    
    def enable_skill(self, name: str) -> bool:
        if name in self._skills:
            self._skills[name].enable()
            return True
        return False
    
    def disable_skill(self, name: str) -> bool:
        if name in self._skills:
            self._skills[name].disable()
            return True
        return False
    
    def get_skill(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)
    
    def get_all_skills(self) -> List[Skill]:
        return list(self._skills.values())
    
    # ================================================================
    # Tool 管理
    # ================================================================
    
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)
    
    def get_all_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())
    
    def get_tools_by_category(self, category: str) -> List[ToolDefinition]:
        return [t for t in self._tools.values() if t.category == category]
    
    def execute_tool(self, name: str, **kwargs) -> Any:
        """执行工具（自动使用所属插件的沙箱）"""
        tool = self._tools.get(name)
        if not tool:
            return f"工具 '{name}' 不存在"
        
        if not tool.handler:
            return f"工具 '{name}' 没有处理器"
        
        # 查找工具所属插件的沙箱
        sandbox = None
        owner_plugin = None
        with self._lock:
            for pname, plugin in self._plugins.items():
                if any(t.name == name for t in plugin.get_tools()):
                    owner_plugin = pname
                    sandbox = self._plugin_sandboxes.get(pname)
                    break
        
        try:
            if sandbox is not None:
                result = sandbox.execute(tool.handler, **kwargs)
            else:
                result = tool.handler(**kwargs)
            result_summary = str(result)[:100]
            self.tool_executed.emit(name, result_summary)
            return result
        except Exception as e:
            self.plugin_error.emit(owner_plugin or name, str(e))
            return f"工具执行错误: {e}"
    
    # ================================================================
    # Hook 管理
    # ================================================================
    
    def trigger_hook(self, point: HookPoint, **kwargs) -> List[Any]:
        """触发指定 Hook 点的所有回调（在各自沙箱中执行）"""
        results = []
        for plugin_name, callback in self._hooks.get(point, []):
            sandbox = self._plugin_sandboxes.get(plugin_name)
            try:
                if sandbox is not None:
                    result = sandbox.execute(callback, **kwargs)
                else:
                    result = callback(**kwargs)
                results.append(result)
                self.hook_triggered.emit(point.value, plugin_name)
            except Exception as e:
                self.plugin_error.emit(plugin_name, f"Hook {point.value} 错误: {e}")
        return results
    
    def register_hook(self, point: HookPoint, callback: Callable, plugin_name: str = "system"):
        """注册系统级 Hook"""
        self._hooks[point].append((plugin_name, callback))
    
    # ================================================================
    # 批量操作
    # ================================================================
    
    def load_builtin_skills(self):
        """加载所有内置 Skill"""
        # ★ 优先加载完整实现的内置 Skill
        builtin_skills = []
        try:
            from builtin_skills import CodeFormatterSkill as FullFormatter, CodeReviewSkill as FullReviewer
            builtin_skills.append(FullFormatter())
            builtin_skills.append(FullReviewer())
        except ImportError:
            # 降级到空壳版本
            builtin_skills.append(CodeFormatterSkill())
            builtin_skills.append(LintCheckerSkill())

        builtin_skills.extend([
            TestRunnerSkill(),
            ProjectScaffoldSkill(),
            GitHelperSkill(),
        ])
        for skill in builtin_skills:
            self.register_skill(skill)
    
    def get_summary(self) -> Dict:
        """获取插件系统摘要"""
        return {
            "plugins": {
                "count": len(self._plugins),
                "names": list(self._plugins.keys()),
                "enabled": sum(1 for n in self._plugins.keys() if self._plugin_enabled.get(n, False)),
            },
            "skills": {
                "count": len(self._skills),
                "enabled": sum(1 for s in self._skills.values() if s.enabled),
                "names": list(self._skills.keys()),
            },
            "tools": {
                "count": len(self._tools),
                "categories": list(set(t.category for t in self._tools.values())),
            },
            "hooks": {
                point.value: len(callbacks)
                for point, callbacks in self._hooks.items()
                if callbacks
            },
        }
    
    def shutdown(self):
        """关闭所有插件，释放资源（应用退出时调用）"""
        names = list(self._plugins.keys())
        for name in names:
            try:
                self.unregister_plugin(name)
            except Exception:
                pass


# ============================================================
# 全局单例
# ============================================================

_global_plugin_manager: Optional[PluginManager] = None
_global_lock = threading.Lock()


def get_plugin_manager(plugin_dir: str = "") -> PluginManager:
    """获取全局 PluginManager 单例"""
    global _global_plugin_manager
    with _global_lock:
        if _global_plugin_manager is None:
            _global_plugin_manager = PluginManager(plugin_dir=plugin_dir)
        return _global_plugin_manager


# ============================================================
# 插件开发文档（注释）
# ============================================================
"""
插件开发指南
============

1. 创建插件文件
----------------
在 `builtin_plugins/` 目录下创建 `.py` 文件，例如 `my_plugin.py`：

    # -*- coding: utf-8 -*-
    from plugin_system import IPlugin, ToolDefinition, HookPoint, SkillDefinition
    
    class MyPlugin(IPlugin):
        @property
        def name(self) -> str:
            return "my_plugin"
        
        @property
        def version(self) -> str:
            return "1.0.0"
        
        @property
        def description(self) -> str:
            return "我的自定义插件"
        
        def on_load(self) -> bool:
            print("MyPlugin 加载成功")
            return True
        
        def on_unload(self):
            print("MyPlugin 卸载")
        
        def get_tools(self):
            return [
                ToolDefinition(
                    name="hello",
                    description="打招呼",
                    parameters=[
                        {"name": "name", "type": "string", "description": "名字"}
                    ],
                    handler=self._hello_handler,
                    category="demo",
                )
            ]
        
        def get_hooks(self):
            return {
                HookPoint.AFTER_TASK: [self._on_after_task]
            }
        
        def _hello_handler(self, **kwargs):
            name = kwargs.get("name", "World")
            return f"Hello, {name}!"
        
        def _on_after_task(self, **kwargs):
            print("任务完成")

2. 权限声明
-----------
第三方插件默认使用沙箱权限（无文件/网络/系统命令访问）。
如需提升权限，请在插件加载时传入 PluginPermission：

    from plugin_system import PluginPermission
    perm = PluginPermission(
        file_access="read",               # none/read/write/full
        network_access=True,
        system_command=False,
        allowed_paths=["/tmp/my_plugin"], # 文件白名单
        allowed_domains=["api.example.com"],
    )
    manager.register_plugin(my_plugin, permission=perm)

3. 热加载 / 卸载 / 重载
----------------------
    # 加载 .py 文件
    manager.load_plugin("/path/to/my_plugin.py")
    
    # 卸载
    manager.unload_plugin("my_plugin")
    
    # 热重载（开发模式）
    manager.reload_plugin("my_plugin")

4. 沙箱机制
-----------
- 每个插件在独立的 ThreadPoolExecutor 中执行 Tool / Hook
- 异常被捕获，不会影响主程序
- 超时默认 30 秒，可通过 PluginSandbox(default_timeout=...) 调整

5. 目录结构
-----------
    builtin_plugins/
    ├── __init__.py
    ├── markdown_preview.py
    ├── json_formatter.py
    ├── color_picker.py
    ├── regex_tester.py
    └── base64_tool.py
"""