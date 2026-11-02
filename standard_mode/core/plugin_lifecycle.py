# -*- coding: utf-8 -*-
"""
插件生命周期管理器 — PluginLifecycleManager
============================================

职责：
- 插件安装/卸载/启用/禁用
- 依赖解析与拓扑排序
- 循环依赖检测
- 插件状态持久化 (plugin_state.json)
- 备份与恢复

与 PluginManager / PluginMarket 协作：
- PluginManager 负责底层加载/卸载/沙箱/运行时
- PluginMarket 负责目录展示、市场逻辑
- PluginLifecycleManager 负责安装流程、依赖管理、状态跟踪
"""

import os
import sys
import json
import shutil
import logging
import threading
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

# ============================================================
# 日志
# ============================================================

_logger = logging.getLogger("plugin_lifecycle")
_logger.addHandler(logging.NullHandler())


def _get_logger():
    """获取日志记录器（优先使用项目的 LemonLogger）"""
    try:
        from shared.logger import get_logger
        return get_logger("plugin_lifecycle")
    except ImportError:
        return _logger


# ============================================================
# PluginManifest 兼容导入
# ============================================================

try:
    from .plugin_manifest import PluginManifest  # noqa: F401
except ImportError:
    # 降级定义：如果 plugin_manifest.py 尚未创建，使用内联 fallback
    @dataclass
    class PluginManifest:
        """插件清单（fallback 定义，正式版请使用 plugin_manifest.py）"""
        name: str
        version: str = "1.0.0"
        description: str = ""
        author: str = ""
        dependencies: Dict[str, str] = field(default_factory=dict)  # name -> version_spec
        is_builtin: bool = False
        download_url: str = ""
        entry_point: str = ""
        permissions: Dict[str, Any] = field(default_factory=dict)
        config_schema: Dict[str, Any] = field(default_factory=dict)
        required_files: List[str] = field(default_factory=list)

        def to_dict(self) -> Dict[str, Any]:
            return asdict(self)

        @classmethod
        def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
            return cls(
                name=data.get("name", ""),
                version=data.get("version", "1.0.0"),
                description=data.get("description", ""),
                author=data.get("author", ""),
                dependencies=data.get("dependencies", {}),
                is_builtin=data.get("is_builtin", False),
                download_url=data.get("download_url", ""),
                entry_point=data.get("entry_point", ""),
                permissions=data.get("permissions", {}),
                config_schema=data.get("config_schema", {}),
                required_files=data.get("required_files", []),
            )


# ============================================================
# PluginState
# ============================================================

@dataclass
class PluginState:
    """插件运行时状态"""
    name: str
    version: str
    installed_at: str = ""          # ISO 时间戳
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    source: str = "local"           # "builtin" / "local" / "remote"
    install_path: str = ""          # 插件在 plugin_dir 下的安装路径
    dependencies: Dict[str, str] = field(default_factory=dict)  # name -> version_spec

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "installed_at": self.installed_at,
            "enabled": self.enabled,
            "config": self.config,
            "source": self.source,
            "install_path": self.install_path,
            "dependencies": self.dependencies,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginState":
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            installed_at=data.get("installed_at", ""),
            enabled=data.get("enabled", True),
            config=data.get("config", {}),
            source=data.get("source", "local"),
            install_path=data.get("install_path", ""),
            dependencies=data.get("dependencies", {}),
        )


# ============================================================
# DependencyResolver
# ============================================================

class DependencyResolver:
    """依赖解析器

    功能：
    - 检查所有依赖是否已安装且启用
    - 递归解析依赖（依赖的依赖）
    - 循环依赖检测
    - 拓扑排序确定安装顺序
    - 查找反向依赖（dependents）
    """

    def __init__(self):
        self._logger = _get_logger()

    # ----------------------------------------------------------------
    # 依赖解析
    # ----------------------------------------------------------------

    def resolve(
        self,
        manifest: PluginManifest,
        installed: Dict[str, Dict],
    ) -> Tuple[bool, List[str]]:
        """检查 manifest 的所有依赖是否已安装且启用

        Args:
            manifest: 待安装插件的清单
            installed: 已安装插件状态字典 {name: state_dict}

        Returns:
            (success, list_of_missing_deps)
            - success: True 表示所有依赖已满足
            - list_of_missing_deps: 缺失的依赖名称列表
        """
        missing = []
        visited = set()

        def _check(name: str, version_spec: str, depth: int = 0):
            if depth > 50:
                self._logger.warning(f"依赖解析深度超限: {name}")
                missing.append(f"{name} (深度超限)")
                return
            if name in visited:
                return
            visited.add(name)

            # 检查插件是否已安装并启用
            state = installed.get(name)
            if state is None:
                missing.append(name)
                return
            if not state.get("enabled", False):
                missing.append(f"{name} (已禁用)")
                return

            # 递归检查依赖的依赖
            deps = state.get("dependencies", {})
            for dep_name, dep_spec in deps.items():
                _check(dep_name, dep_spec, depth + 1)

        # 逐个检查 manifest 声明的依赖
        for dep_name, dep_spec in manifest.dependencies.items():
            _check(dep_name, dep_spec)

        if missing:
            self._logger.warning(
                f"依赖检查失败: {manifest.name} 缺少 {missing}"
            )
            return False, missing

        self._logger.debug(f"依赖检查通过: {manifest.name}")
        return True, []

    # ----------------------------------------------------------------
    # 反向依赖
    # ----------------------------------------------------------------

    def get_dependents(
        self,
        plugin_name: str,
        installed: Dict[str, Dict],
    ) -> List[str]:
        """查找所有依赖了 plugin_name 的已安装插件

        Args:
            plugin_name: 目标插件名称
            installed: 已安装插件状态字典

        Returns:
            依赖了 plugin_name 的插件名称列表
        """
        dependents = []
        for name, state in installed.items():
            deps = state.get("dependencies", {})
            if plugin_name in deps:
                dependents.append(name)
        return dependents

    # ----------------------------------------------------------------
    # 依赖图
    # ----------------------------------------------------------------

    def build_dependency_graph(
        self,
        installed: Dict[str, Dict],
    ) -> Dict[str, List[str]]:
        """构建插件依赖图的邻接表

        Args:
            installed: 已安装插件状态字典

        Returns:
            {plugin_name: [dependency_names, ...]}
        """
        graph: Dict[str, List[str]] = {}
        for name, state in installed.items():
            deps = state.get("dependencies", [])
            if isinstance(deps, dict):
                graph[name] = list(deps.keys())
            elif isinstance(deps, list):
                graph[name] = list(deps)
            else:
                graph[name] = []
        return graph

    # ----------------------------------------------------------------
    # 拓扑排序
    # ----------------------------------------------------------------

    def get_install_order(
        self,
        plugins: List[PluginManifest],
        installed: Dict[str, Dict],
    ) -> List[str]:
        """拓扑排序确定安装顺序（依赖优先）

        Args:
            plugins: 待安装的插件清单列表
            installed: 已安装插件状态字典

        Returns:
            按依赖顺序排列的插件名称列表
        """
        # 构建完整依赖图：已安装 + 待安装
        graph: Dict[str, List[str]] = {}
        all_names: set = set()

        # 已安装插件的依赖
        for name, state in installed.items():
            all_names.add(name)
            deps = state.get("dependencies", [])
            if isinstance(deps, dict):
                graph[name] = list(deps.keys())
            elif isinstance(deps, list):
                graph[name] = list(deps)
            else:
                graph[name] = []

        # 待安装插件的依赖
        for p in plugins:
            all_names.add(p.name)
            deps = p.dependencies if isinstance(p.dependencies, list) else []
            graph[p.name] = list(deps)

        # 检测循环依赖
        cycle = self._detect_cycle(graph)
        if cycle:
            self._logger.error(f"检测到循环依赖: {' -> '.join(cycle)}")
            # 返回原始顺序并标记
            return [p.name for p in plugins]

        # Kahn 算法
        in_degree: Dict[str, int] = {name: 0 for name in all_names}
        for name, deps in graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[name] = in_degree.get(name, 0) + 1

        # 优先队列：已安装的排在前面，新安装的按 in_degree=0 优先
        queue = [
            name for name in all_names
            if in_degree.get(name, 0) == 0
        ]

        order: List[str] = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            # 找到所有依赖 node 的节点
            for name, deps in graph.items():
                if node in deps and name in in_degree:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)

        # 仅返回待安装的插件
        plugin_names = {p.name for p in plugins}
        return [n for n in order if n in plugin_names]

    def _detect_cycle(self, graph: Dict[str, List[str]]) -> List[str]:
        """DFS 检测有向图中的环

        Returns:
            环路径列表（空列表表示无环）
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {node: WHITE for node in graph}
        parent: Dict[str, Optional[str]] = {node: None for node in graph}

        def _dfs(node: str) -> Optional[List[str]]:
            color[node] = GRAY
            for neighbor in graph.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    # 找到环，回溯路径
                    cycle = [neighbor, node]
                    cur = node
                    while parent.get(cur) and parent[cur] != neighbor:
                        cur = parent[cur]
                        cycle.append(cur)
                    cycle.append(neighbor)
                    cycle.reverse()
                    return cycle
                if color[neighbor] == WHITE:
                    parent[neighbor] = node
                    result = _dfs(neighbor)
                    if result:
                        return result
            color[node] = BLACK
            return None

        for node in graph:
            if color.get(node) == WHITE:
                result = _dfs(node)
                if result:
                    return result
        return []


# ============================================================
# PluginLifecycleManager
# ============================================================

class PluginLifecycleManager:
    """插件生命周期管理器

    负责：
    - 插件安装（从本地文件、远程 URL、内置目录）
    - 插件卸载（含依赖检查）
    - 插件启用/禁用（含依赖检查）
    - 状态持久化到 plugin_state.json

    使用方式：
        manager = PluginLifecycleManager()
        manifest = PluginManifest(name="my_plugin", version="1.0.0")
        manager.install(manifest, source_path="/path/to/plugin")
        manager.enable("my_plugin")
        manager.uninstall("my_plugin")
    """

    # 状态文件名
    STATE_FILE = "plugin_state.json"

    # 内置插件目录（相对于 plugin_system.py）
    _BUILTIN_PLUGINS_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "builtin_plugins"
    )

    def __init__(self, plugin_dir: str = None):
        """
        Args:
            plugin_dir: 自定义插件安装目录，默认 standard_mode/core/plugins/
        """
        self._logger = _get_logger()

        if plugin_dir is None:
            plugin_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "plugins"
            )
        self._plugin_dir = os.path.abspath(plugin_dir)
        self._state_file = os.path.join(self._plugin_dir, self.STATE_FILE)
        self._lock = threading.RLock()

        # 确保目录存在
        os.makedirs(self._plugin_dir, exist_ok=True)

        # 加载状态
        self._state: Dict[str, Dict] = {}
        self._load_state()

        self._resolver = DependencyResolver()

        self._logger.info(f"PluginLifecycleManager 初始化完成, plugin_dir={self._plugin_dir}")

    # ============================================================
    # 状态持久化
    # ============================================================

    def _load_state(self):
        """从磁盘加载 plugin_state.json"""
        try:
            if os.path.isfile(self._state_file):
                with open(self._state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._state = data.get("plugins", {})
                self._logger.debug(f"加载插件状态: {len(self._state)} 个插件")
            else:
                self._state = {}
                self._save_state()
        except (json.JSONDecodeError, OSError) as e:
            self._logger.error(f"加载插件状态失败: {e}")
            self._state = {}

    def _save_state(self):
        """保存状态到 plugin_state.json"""
        try:
            data = {
                "plugins": self._state,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            # 原子写入：先写临时文件再重命名
            tmp_file = self._state_file + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self._state_file)
            self._logger.debug(f"保存插件状态: {len(self._state)} 个插件")
        except OSError as e:
            self._logger.error(f"保存插件状态失败: {e}")

    # ============================================================
    # 安装
    # ============================================================

    def install(
        self,
        manifest: PluginManifest,
        source_path: str = None,
    ) -> bool:
        """安装插件

        Args:
            manifest: 插件清单
            source_path: 插件源文件路径（本地安装时使用）

        Returns:
            True 安装成功，False 失败
        """
        name = manifest.name
        with self._lock:
            # 检查是否已安装
            if name in self._state:
                self._logger.warning(f"插件已安装: {name}")
                return False

            # 验证依赖
            ok, missing = self._resolver.resolve(manifest, self._state)
            if not ok:
                self._logger.error(
                    f"安装失败: {name}, 缺少依赖: {missing}"
                )
                return False

            # 确定安装来源和路径
            target_path = ""
            source = "local"

            try:
                if manifest.is_builtin:
                    target_path = self._install_from_builtin(manifest)
                    source = "builtin"
                elif manifest.download_url:
                    target_path = self._install_from_url(manifest)
                    source = "remote"
                elif source_path:
                    target_path = self._install_from_local(manifest, source_path)
                    source = "local"
                else:
                    self._logger.error(f"安装失败: {name}, 无可用的安装源")
                    return False

                if not target_path and not manifest.is_builtin:
                    return False

                # 记录状态
                self._state[name] = PluginState(
                    name=name,
                    version=manifest.version,
                    installed_at=datetime.now(timezone.utc).isoformat(),
                    enabled=True,
                    config={},
                    source=source,
                    install_path=target_path,
                    dependencies=manifest.dependencies,
                ).to_dict()

                self._save_state()
                self._logger.info(f"插件安装成功: {name} v{manifest.version} [{source}]")
                return True

            except Exception as e:
                self._logger.exception(f"安装插件异常: {name}", exc=e)
                return False

    def _install_from_builtin(self, manifest: PluginManifest) -> str:
        """从内置插件目录安装（符号链接或复制）"""
        name = manifest.name
        builtin_path = os.path.join(self._BUILTIN_PLUGINS_DIR, f"{name}.py")

        if not os.path.isfile(builtin_path):
            # 尝试目录形式
            builtin_dir = os.path.join(self._BUILTIN_PLUGINS_DIR, name)
            if os.path.isdir(builtin_dir):
                target = os.path.join(self._plugin_dir, name)
                if os.path.exists(target):
                    shutil.rmtree(target, ignore_errors=True)
                try:
                    os.symlink(builtin_dir, target)
                except OSError:
                    # Windows 上符号链接可能失败，降级为复制
                    shutil.copytree(builtin_dir, target)
                self._logger.debug(f"从内置安装（目录）: {name}")
                return target
            self._logger.warning(f"内置插件未找到: {builtin_path}")
            return ""

        target = os.path.join(self._plugin_dir, f"{name}.py")
        if os.path.exists(target):
            os.remove(target)
        try:
            os.symlink(builtin_path, target)
        except OSError:
            shutil.copy2(builtin_path, target)
        self._logger.debug(f"从内置安装（文件）: {name}")
        return target

    def _install_from_local(self, manifest: PluginManifest, source_path: str) -> str:
        """从本地路径复制插件文件"""
        name = manifest.name
        if not os.path.exists(source_path):
            self._logger.error(f"源文件不存在: {source_path}")
            return ""

        if os.path.isdir(source_path):
            target = os.path.join(self._plugin_dir, name)
            if os.path.exists(target):
                self._logger.warning(f"目标路径已存在，覆盖: {target}")
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source_path, target)
        else:
            # 单文件插件
            ext = os.path.splitext(source_path)[1]
            target = os.path.join(self._plugin_dir, f"{name}{ext}")
            if os.path.exists(target):
                os.remove(target)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source_path, target)

        self._logger.debug(f"从本地安装: {name} <- {source_path}")
        return target

    def _install_from_url(self, manifest: PluginManifest) -> str:
        """从 URL 下载并安装插件"""
        name = manifest.name
        url = manifest.download_url

        try:
            import requests
        except ImportError:
            self._logger.error("需要安装 requests 库以支持远程下载")
            return ""

        import tempfile
        import zipfile

        self._logger.info(f"从远程下载: {name} <- {url}")

        try:
            resp = requests.get(url, stream=True, timeout=120)
            resp.raise_for_status()

            # 写入临时文件
            fd, tmp_path = tempfile.mkstemp(suffix=".zip")
            os.close(fd)
            with open(tmp_path, "wb") as tf:
                for chunk in resp.iter_content(8192):
                    if chunk:
                        tf.write(chunk)

            # 解压到目标目录
            target = os.path.join(self._plugin_dir, name)
            if os.path.exists(target):
                shutil.rmtree(target, ignore_errors=True)
            os.makedirs(target, exist_ok=True)

            with zipfile.ZipFile(tmp_path, "r") as zf:
                zf.extractall(target)

            # 清理临时文件
            try:
                os.remove(tmp_path)
            except OSError:
                pass

            self._logger.debug(f"从远程安装完成: {name}")
            return target

        except Exception as e:
            self._logger.exception(f"远程下载失败: {name}", exc=e)
            return ""

    # ============================================================
    # 卸载
    # ============================================================

    def uninstall(self, plugin_name: str) -> bool:
        """卸载插件

        - 检查是否有其他插件依赖此插件
        - 删除插件文件
        - 更新状态

        Args:
            plugin_name: 插件名称

        Returns:
            True 卸载成功，False 失败
        """
        with self._lock:
            if plugin_name not in self._state:
                self._logger.warning(f"插件未安装: {plugin_name}")
                return False

            # 检查反向依赖
            dependents = self._resolver.get_dependents(plugin_name, self._state)
            if dependents:
                self._logger.error(
                    f"无法卸载 {plugin_name}: 以下插件依赖它: {dependents}"
                )
                return False

            state = self._state[plugin_name]
            install_path = state.get("install_path", "")

            try:
                # 备份
                if install_path and os.path.exists(install_path):
                    backup_path = backup_plugin(plugin_name, self._plugin_dir)
                    if backup_path:
                        self._logger.info(f"已备份: {backup_path}")

                # 删除插件文件
                if install_path and os.path.exists(install_path):
                    if os.path.isdir(install_path):
                        shutil.rmtree(install_path, ignore_errors=True)
                    else:
                        os.remove(install_path)

                # 移除状态
                self._state.pop(plugin_name, None)
                self._save_state()

                self._logger.info(f"插件卸载成功: {plugin_name}")
                return True

            except OSError as e:
                self._logger.exception(f"卸载插件失败: {plugin_name}", exc=e)
                return False

    # ============================================================
    # 启用 / 禁用
    # ============================================================

    def enable(self, plugin_name: str) -> bool:
        """启用插件

        - 检查依赖是否满足
        - 更新状态

        Args:
            plugin_name: 插件名称

        Returns:
            True 启用成功，False 失败
        """
        with self._lock:
            if plugin_name not in self._state:
                self._logger.warning(f"插件未安装: {plugin_name}")
                return False

            state = self._state[plugin_name]
            if state.get("enabled", False):
                self._logger.debug(f"插件已启用: {plugin_name}")
                return True

            # 检查依赖是否满足
            deps = state.get("dependencies", {})
            missing = []
            for dep_name in deps:
                dep_state = self._state.get(dep_name)
                if dep_state is None:
                    missing.append(dep_name)
                elif not dep_state.get("enabled", False):
                    missing.append(f"{dep_name} (已禁用)")

            if missing:
                self._logger.error(
                    f"无法启用 {plugin_name}: 依赖未满足: {missing}"
                )
                return False

            state["enabled"] = True
            self._save_state()
            self._logger.info(f"插件已启用: {plugin_name}")
            return True

    def disable(self, plugin_name: str) -> bool:
        """禁用插件

        - 检查是否有其他插件依赖此插件
        - 更新状态

        Args:
            plugin_name: 插件名称

        Returns:
            True 禁用成功，False 失败
        """
        with self._lock:
            if plugin_name not in self._state:
                self._logger.warning(f"插件未安装: {plugin_name}")
                return False

            state = self._state[plugin_name]
            if not state.get("enabled", True):
                self._logger.debug(f"插件已禁用: {plugin_name}")
                return True

            # 检查反向依赖
            dependents = self._resolver.get_dependents(plugin_name, self._state)
            # 仅检查已启用的依赖者
            active_dependents = [
                d for d in dependents
                if self._state.get(d, {}).get("enabled", False)
            ]
            if active_dependents:
                self._logger.error(
                    f"无法禁用 {plugin_name}: 以下已启用插件依赖它: {active_dependents}"
                )
                return False

            state["enabled"] = False
            self._save_state()
            self._logger.info(f"插件已禁用: {plugin_name}")
            return True

    # ============================================================
    # 查询接口
    # ============================================================

    def get_installed_plugins(self) -> List[Dict]:
        """返回已安装插件列表及其状态"""
        with self._lock:
            return [
                {
                    "name": name,
                    "version": state.get("version", ""),
                    "installed_at": state.get("installed_at", ""),
                    "enabled": state.get("enabled", True),
                    "source": state.get("source", "unknown"),
                    "install_path": state.get("install_path", ""),
                    "dependencies": state.get("dependencies", {}),
                }
                for name, state in self._state.items()
            ]

    def is_installed(self, plugin_name: str) -> bool:
        """检查插件是否已安装"""
        with self._lock:
            return plugin_name in self._state

    def is_enabled(self, plugin_name: str) -> bool:
        """检查插件是否已启用"""
        with self._lock:
            state = self._state.get(plugin_name)
            if state is None:
                return False
            return state.get("enabled", True)

    def get_plugin_state(self, plugin_name: str) -> Optional[Dict]:
        """获取插件的完整状态"""
        with self._lock:
            return self._state.get(plugin_name)

    # ============================================================
    # 其他
    # ============================================================

    def get_plugin_dir(self) -> str:
        """获取插件安装目录"""
        return self._plugin_dir

    def get_summary(self) -> Dict[str, Any]:
        """获取管理器摘要"""
        with self._lock:
            total = len(self._state)
            enabled = sum(1 for s in self._state.values() if s.get("enabled", False))
            by_source = {"builtin": 0, "local": 0, "remote": 0}
            for s in self._state.values():
                src = s.get("source", "local")
                by_source[src] = by_source.get(src, 0) + 1
            return {
                "total": total,
                "enabled": enabled,
                "disabled": total - enabled,
                "by_source": by_source,
                "plugin_dir": self._plugin_dir,
            }


# ============================================================
# 辅助函数
# ============================================================

def validate_plugin_structure(plugin_dir: str) -> bool:
    """检查插件目录是否包含必需的文件结构

    一个合法的插件目录应包含：
    - __init__.py 或同名 .py 文件
    - 至少一个 IPlugin 子类定义

    Args:
        plugin_dir: 插件目录路径

    Returns:
        True 表示结构合法，False 表示不合法
    """
    logger = _get_logger()

    if not os.path.isdir(plugin_dir):
        logger.warning(f"validate_plugin_structure: 路径不是目录: {plugin_dir}")
        return False

    # 检查是否有入口文件
    plugin_name = os.path.basename(os.path.abspath(plugin_dir))
    has_init = os.path.isfile(os.path.join(plugin_dir, "__init__.py"))
    has_main = os.path.isfile(os.path.join(plugin_dir, f"{plugin_name}.py"))

    if not has_init and not has_main:
        logger.warning(
            f"validate_plugin_structure: 缺少入口文件: {plugin_dir}"
        )
        return False

    # 尝试导入并检查是否有 IPlugin
    try:
        import importlib.util
        if has_init:
            spec = importlib.util.spec_from_file_location(
                f"_validate_{plugin_name}",
                os.path.join(plugin_dir, "__init__.py")
            )
        else:
            spec = importlib.util.spec_from_file_location(
                f"_validate_{plugin_name}",
                os.path.join(plugin_dir, f"{plugin_name}.py")
            )

        if spec is None or spec.loader is None:
            return False

        module = importlib.util.module_from_spec(spec)
        sys.modules[f"_validate_{plugin_name}"] = module
        spec.loader.exec_module(module)

        # 检查是否有 IPlugin 子类
        try:
            from plugin_system import IPlugin
        except ImportError:
            # 如果无法导入 IPlugin，至少检查是否有定义了 name/version 属性的类
            has_plugin = False
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and hasattr(attr, "name") and hasattr(attr, "version"):
                    has_plugin = True
                    break
            if not has_plugin:
                logger.warning(
                    f"validate_plugin_structure: 未找到插件类: {plugin_dir}"
                )
                return False
        else:
            has_plugin = False
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, IPlugin) and attr is not IPlugin:
                    has_plugin = True
                    break
            if not has_plugin:
                logger.warning(
                    f"validate_plugin_structure: 未找到 IPlugin 子类: {plugin_dir}"
                )
                return False

        # 清理
        sys.modules.pop(f"_validate_{plugin_name}", None)

    except Exception as e:
        logger.warning(f"validate_plugin_structure: 导入失败: {plugin_dir}: {e}")
        return False

    return True


def backup_plugin(plugin_name: str, plugin_dir: str) -> str:
    """备份插件到备份目录

    备份文件命名格式: {plugin_name}_backup_{timestamp}

    Args:
        plugin_name: 插件名称
        plugin_dir: 插件安装目录

    Returns:
        备份路径，失败返回空字符串
    """
    logger = _get_logger()
    backup_dir = os.path.join(plugin_dir, ".backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_path = os.path.join(plugin_dir, f"{plugin_name}.py")

    if not os.path.exists(source_path):
        # 尝试目录形式
        source_path = os.path.join(plugin_dir, plugin_name)
        if not os.path.exists(source_path):
            logger.warning(f"backup_plugin: 源不存在: {plugin_name}")
            return ""

    try:
        if os.path.isdir(source_path):
            backup_path = os.path.join(backup_dir, f"{plugin_name}_backup_{timestamp}")
            if os.path.exists(backup_path):
                shutil.rmtree(backup_path, ignore_errors=True)
            shutil.copytree(source_path, backup_path)
        else:
            ext = os.path.splitext(source_path)[1]
            backup_path = os.path.join(
                backup_dir, f"{plugin_name}_backup_{timestamp}{ext}"
            )
            shutil.copy2(source_path, backup_path)

        logger.info(f"备份完成: {backup_path}")
        return backup_path

    except OSError as e:
        logger.exception(f"备份失败: {plugin_name}", exc=e)
        return ""


def restore_plugin(backup_path: str, plugin_dir: str) -> bool:
    """从备份恢复插件

    Args:
        backup_path: 备份文件/目录路径
        plugin_dir: 插件安装目录

    Returns:
        True 恢复成功，False 失败
    """
    logger = _get_logger()

    if not os.path.exists(backup_path):
        logger.error(f"restore_plugin: 备份不存在: {backup_path}")
        return False

    # 从备份文件名推断插件名
    basename = os.path.basename(backup_path)
    # 格式: {plugin_name}_backup_{timestamp}[.py]
    parts = basename.rsplit("_backup_", 1)
    if len(parts) != 2:
        logger.error(f"restore_plugin: 无法解析备份文件名: {basename}")
        return False

    plugin_name = parts[0]

    try:
        if os.path.isdir(backup_path):
            target = os.path.join(plugin_dir, plugin_name)
            if os.path.exists(target):
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(backup_path, target)
        else:
            target = os.path.join(plugin_dir, f"{plugin_name}.py")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(backup_path, target)

        logger.info(f"恢复完成: {plugin_name} <- {backup_path}")
        return True

    except OSError as e:
        logger.exception(f"恢复失败: {plugin_name}", exc=e)
        return False