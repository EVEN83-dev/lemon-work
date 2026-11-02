# -*- coding: utf-8 -*-
"""
Lemon Agent 外部依赖管理器
============================
统一管理外部软件依赖的检测、配置、持久化：

1. MIMO Code — 云端 AI 编程工具（可执行文件 mimo.exe）
2. Ollama — 本地 LLM 推理引擎（可执行文件 ollama.exe）
3. DeepSeek — 云端 API（只需 API Key，无需可执行文件）

支持两种接入方式：
- 自动检测：在 PATH 和常见安装路径中搜索
- 手动配置：用户粘贴可执行文件路径（推荐）

配置持久化：保存到 config/dependencies.json

用法：
    from core.dependency_manager import get_dependency_manager
    dm = get_dependency_manager()
    # 自动检测所有依赖
    status = dm.detect_all()
    # 手动设置 MIMO Code 路径
    dm.set_path("mimocode", "C:/Users/test/mimo.exe")
    # 获取依赖状态
    info = dm.get_status("mimocode")
    # 健康检查
    ok = dm.health_check("ollama")
"""

import os
import json
import shutil
import subprocess
import threading
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime


# ============================================================================
# 依赖类型
# ============================================================================

class DependencyType:
    """依赖类型"""
    MIMOCODE = "mimocode"   # MIMO Code 可执行文件
    OLLAMA = "ollama"        # Ollama 可执行文件
    DEEPSEEK = "deepseek"    # DeepSeek API（无需可执行文件）


@dataclass
class DependencyInfo:
    """依赖信息"""
    name: str                                           # 依赖名称
    type: str                                           # 类型 (mimocode/ollama/deepseek)
    installed: bool = False                             # 是否已安装
    path: str = ""                                      # 可执行文件路径
    version: str = ""                                   # 版本号
    running: bool = False                               # 是否运行中
    host: str = ""                                      # API 地址（如有）
    api_key: str = ""                                   # API Key（DeepSeek）
    last_checked: str = ""                              # 最后检测时间
    configured_manually: bool = False                   # 是否用户手动配置
    description: str = ""                               # 描述
    download_url: str = ""                              # 下载地址
    common_paths: List[str] = field(default_factory=list)  # 常见安装路径

    def to_dict(self) -> Dict:
        return asdict(self)


# ============================================================================
# 依赖管理器
# ============================================================================

class DependencyManager:
    """外部依赖管理器 — 统一检测、配置、持久化"""

    # 配置文件路径
    CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
    CONFIG_FILE = os.path.join(CONFIG_DIR, "dependencies.json")

    # 各依赖的常见安装路径
    COMMON_PATHS = {
        DependencyType.MIMOCODE: [
            # 项目目录
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "mimo.exe"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mimo.exe"),
            # Windows 常见路径
            r"C:\Program Files\MIMO Code\mimo.exe",
            r"C:\Program Files (x86)\MIMO Code\mimo.exe",
            r"C:\Users\{}\AppData\Local\Programs\MIMO Code\mimo.exe",
            # Linux/Mac
            "/usr/local/bin/mimo",
            "/usr/bin/mimo",
        ],
        DependencyType.OLLAMA: [
            # Windows
            r"C:\Users\{}\AppData\Local\Programs\Ollama\ollama.exe",
            r"C:\Program Files\Ollama\ollama.exe",
            r"C:\Program Files (x86)\Ollama\ollama.exe",
            # Linux/Mac
            "/usr/local/bin/ollama",
            "/usr/bin/ollama",
            "/opt/ollama/ollama",
        ],
    }

    # 下载地址
    DOWNLOAD_URLS = {
        DependencyType.MIMOCODE: "https://code.xiaomi.com/download",
        DependencyType.OLLAMA: "https://ollama.com/download",
        DependencyType.DEEPSEEK: "https://platform.deepseek.com",
    }

    # 描述
    DESCRIPTIONS = {
        DependencyType.MIMOCODE: "小米 MIMO Code 云端 AI 编程工具 — 提供复杂工程任务处理能力",
        DependencyType.OLLAMA: "本地 LLM 推理引擎 — 免费运行 qwen3.5 等本地模型",
        DependencyType.DEEPSEEK: "DeepSeek 云端 API — 需要 API Key，无需下载可执行文件",
    }

    # API 地址
    API_HOSTS = {
        DependencyType.MIMOCODE: "http://localhost:4097",
        DependencyType.OLLAMA: "http://127.0.0.1:11434",  # ★ v3.14 改用127.0.0.1
        DependencyType.DEEPSEEK: "https://api.deepseek.com",
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._dependencies: Dict[str, DependencyInfo] = {}
        self._init_dependencies()
        self._load_config()

    def _init_dependencies(self):
        """初始化依赖信息"""
        for dep_type in [DependencyType.MIMOCODE, DependencyType.OLLAMA, DependencyType.DEEPSEEK]:
            # 展开 Windows 用户目录路径
            common_paths = []
            for path in self.COMMON_PATHS.get(dep_type, []):
                if "{}" in path:
                    try:
                        username = os.environ.get("USERNAME") or os.environ.get("USER", "")
                        if username:
                            common_paths.append(path.replace("{}", username))
                    except Exception:
                        pass
                else:
                    common_paths.append(path)

            self._dependencies[dep_type] = DependencyInfo(
                name=dep_type,
                type=dep_type,
                description=self.DESCRIPTIONS.get(dep_type, ""),
                download_url=self.DOWNLOAD_URLS.get(dep_type, ""),
                common_paths=common_paths,
                host=self.API_HOSTS.get(dep_type, ""),
            )

    # ==================== 自动检测 ====================

    def detect_all(self) -> Dict[str, DependencyInfo]:
        """检测所有依赖"""
        for dep_type in self._dependencies:
            self._detect_single(dep_type)
        self._save_config()
        return self._dependencies

    def _detect_single(self, dep_type: str):
        """检测单个依赖"""
        info = self._dependencies[dep_type]

        if dep_type == DependencyType.DEEPSEEK:
            # DeepSeek 只需要 API Key，不需要可执行文件
            info.installed = bool(info.api_key)
            info.last_checked = datetime.now().isoformat()
            return

        # 如果用户已手动配置路径，优先使用
        if info.configured_manually and info.path:
            if os.path.isfile(info.path):
                info.installed = True
                self._get_version(dep_type, info)
                self._check_running(dep_type, info)
                info.last_checked = datetime.now().isoformat()
                return
            else:
                # 手动配置的路径失效
                info.configured_manually = False
                info.path = ""

        # 1. 在 PATH 中查找
        exe_name = self._get_exe_name(dep_type)
        found = shutil.which(exe_name)
        if found:
            info.path = found
            info.installed = True
            self._get_version(dep_type, info)
            self._check_running(dep_type, info)
            info.last_checked = datetime.now().isoformat()
            return

        # 2. 在常见路径中查找
        for common_path in info.common_paths:
            if os.path.isfile(common_path):
                info.path = common_path
                info.installed = True
                self._get_version(dep_type, info)
                self._check_running(dep_type, info)
                info.last_checked = datetime.now().isoformat()
                return

        # 未找到
        info.installed = False
        info.running = False
        info.last_checked = datetime.now().isoformat()

    def _get_exe_name(self, dep_type: str) -> str:
        """获取可执行文件名"""
        if dep_type == DependencyType.MIMOCODE:
            return "mimo.exe" if os.name == "nt" else "mimo"
        elif dep_type == DependencyType.OLLAMA:
            return "ollama.exe" if os.name == "nt" else "ollama"
        return ""

    def _get_version(self, dep_type: str, info: DependencyInfo):
        """获取版本号"""
        if not info.path:
            return
        try:
            if dep_type == DependencyType.MIMOCODE:
                # MIMO Code 是 GUI 程序，不支持 --version 命令
                # 通过文件属性获取版本
                try:
                    info.version = "installed"
                except Exception:
                    pass
            elif dep_type == DependencyType.OLLAMA:
                result = subprocess.run(
                    [info.path, "--version"],
                    capture_output=True, text=True, timeout=3,
                    encoding='utf-8', errors='replace'
                )
                if result.returncode == 0:
                    info.version = result.stdout.strip()[:100]
        except subprocess.TimeoutExpired:
            # 版本检测超时不算致命错误
            pass
        except Exception:
            pass

    def _check_running(self, dep_type: str, info: DependencyInfo):
        """检查服务是否运行中"""
        try:
            import requests
            host = info.host
            if dep_type == DependencyType.MIMOCODE:
                # 使用 (连接超时, 读取超时) 元组，避免卡死
                resp = requests.get(f"{host}/health", timeout=(2, 3))
                info.running = resp.status_code == 200
            elif dep_type == DependencyType.OLLAMA:
                resp = requests.get(f"{host}/api/tags", timeout=(2, 3))
                info.running = resp.status_code == 200
            elif dep_type == DependencyType.DEEPSEEK:
                # DeepSeek 不需要检查运行状态
                info.running = bool(info.api_key)
        except requests.exceptions.ConnectionError:
            # 服务未运行，正常情况
            info.running = False
        except requests.exceptions.Timeout:
            info.running = False
        except Exception:
            info.running = False

    # ==================== 手动配置 ====================

    def set_path(self, dep_type: str, path: str) -> Tuple[bool, str]:
        """手动设置依赖路径（用户粘贴路径）

        Args:
            dep_type: 依赖类型
            path: 可执行文件路径

        Returns:
            (success, message)
        """
        if dep_type == DependencyType.DEEPSEEK:
            return False, "DeepSeek 不需要可执行文件路径，请使用 set_api_key()"

        if not path:
            return False, "路径不能为空"

        # 标准化路径
        path = os.path.abspath(path.replace('"', '').replace("'", ""))

        # 验证路径
        if not os.path.isfile(path):
            return False, f"文件不存在: {path}"

        # 验证是可执行文件
        if not self._is_executable(path):
            return False, f"不是有效的可执行文件: {path}"

        # 设置路径
        with self._lock:
            info = self._dependencies[dep_type]
            info.path = path
            info.configured_manually = True
            info.installed = True
            self._get_version(dep_type, info)
            self._check_running(dep_type, info)
            info.last_checked = datetime.now().isoformat()

        self._save_config()

        return True, f"已设置 {dep_type} 路径: {path}"

    def set_api_key(self, dep_type: str, api_key: str) -> Tuple[bool, str]:
        """设置 API Key（DeepSeek）"""
        if dep_type != DependencyType.DEEPSEEK:
            return False, "只有 DeepSeek 需要 API Key"

        if not api_key:
            return False, "API Key 不能为空"

        with self._lock:
            info = self._dependencies[dep_type]
            info.api_key = api_key
            info.installed = True
            info.configured_manually = True
            info.last_checked = datetime.now().isoformat()

        self._save_config()
        return True, "DeepSeek API Key 已设置"

    def _is_executable(self, path: str) -> bool:
        """检查是否是可执行文件"""
        if os.name == "nt":
            # Windows: 检查扩展名
            return path.lower().endswith((".exe", ".bat", ".cmd"))
        else:
            # Linux/Mac: 检查可执行权限
            return os.access(path, os.X_OK)

    def clear_path(self, dep_type: str):
        """清除手动配置的路径"""
        with self._lock:
            info = self._dependencies[dep_type]
            info.path = ""
            info.configured_manually = False
            info.installed = False
            info.running = False
        self._save_config()

    # ==================== 健康检查 ====================

    def health_check(self, dep_type: str) -> Tuple[bool, str]:
        """健康检查 — 验证依赖是否可用"""
        info = self._dependencies.get(dep_type)
        if not info:
            return False, f"未知依赖: {dep_type}"

        # 重新检测
        self._detect_single(dep_type)
        self._save_config()

        if not info.installed:
            return False, f"{dep_type} 未安装 — 请设置路径或安装软件"

        if dep_type == DependencyType.DEEPSEEK:
            if not info.api_key:
                return False, "DeepSeek API Key 未设置"
            return True, "DeepSeek API Key 已配置"

        # 检查路径
        if not os.path.isfile(info.path):
            return False, f"路径无效: {info.path}"

        # 检查运行状态
        if not info.running:
            return False, f"{dep_type} 已安装但未运行 (host: {info.host})"

        return True, f"{dep_type} 运行正常 (v{info.version})"

    def health_check_all(self) -> Dict[str, Tuple[bool, str]]:
        """所有依赖健康检查"""
        results = {}
        for dep_type in self._dependencies:
            results[dep_type] = self.health_check(dep_type)
        return results

    # ==================== 状态查询 ====================

    def get_status(self, dep_type: str) -> Optional[DependencyInfo]:
        """获取单个依赖状态"""
        return self._dependencies.get(dep_type)

    def get_all_status(self) -> Dict[str, DependencyInfo]:
        """获取所有依赖状态"""
        return self._dependencies

    def get_available_engines(self) -> List[str]:
        """获取可用引擎列表"""
        available = []
        for dep_type, info in self._dependencies.items():
            if info.installed and info.running:
                available.append(dep_type)
        return available

    def get_recommended_engine(self) -> str:
        """获取推荐引擎（优先级: mimocode > ollama > deepseek）"""
        for dep_type in [DependencyType.MIMOCODE, DependencyType.OLLAMA, DependencyType.DEEPSEEK]:
            info = self._dependencies.get(dep_type)
            if info and info.installed and info.running:
                return dep_type
        return ""

    # ==================== 配置持久化 ====================

    def _save_config(self):
        """保存配置到文件"""
        try:
            os.makedirs(self.CONFIG_DIR, exist_ok=True)
            config = {
                "version": "1.0",
                "last_updated": datetime.now().isoformat(),
                "dependencies": {
                    dep_type: info.to_dict()
                    for dep_type, info in self._dependencies.items()
                }
            }
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[DependencyManager] 保存配置失败: {e}")

    def _load_config(self):
        """从文件加载配置"""
        try:
            if not os.path.exists(self.CONFIG_FILE):
                return
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            deps = config.get("dependencies", {})
            for dep_type, data in deps.items():
                if dep_type in self._dependencies:
                    info = self._dependencies[dep_type]
                    info.path = data.get("path", "")
                    info.api_key = data.get("api_key", "")
                    info.configured_manually = data.get("configured_manually", False)
                    if info.path or info.api_key:
                        info.installed = True
        except Exception as e:
            print(f"[DependencyManager] 加载配置失败: {e}")

    # ==================== 引导信息 ====================

    def get_setup_guide(self, dep_type: str) -> Dict:
        """获取安装引导信息"""
        info = self._dependencies.get(dep_type)
        if not info:
            return {}

        return {
            "type": dep_type,
            "description": info.description,
            "download_url": info.download_url,
            "common_paths": info.common_paths,
            "current_status": {
                "installed": info.installed,
                "running": info.running,
                "path": info.path,
                "version": info.version,
                "configured_manually": info.configured_manually,
            },
            "instructions": self._get_instructions(dep_type),
        }

    def _get_instructions(self, dep_type: str) -> List[str]:
        """获取安装步骤"""
        if dep_type == DependencyType.MIMOCODE:
            return [
                "1. 从 https://code.xiaomi.com/download 下载 MIMO Code",
                "2. 安装到默认路径或自定义路径",
                "3. 复制 mimo.exe 的完整路径（如 C:\\Program Files\\MIMO Code\\mimo.exe）",
                "4. 粘贴路径到设置中，或添加到系统 PATH 环境变量",
                "5. 启动 MIMO Code 后运行 'mimo serve --port 4097'",
            ]
        elif dep_type == DependencyType.OLLAMA:
            return [
                "1. 从 https://ollama.com/download 下载 Ollama",
                "2. 安装到默认路径",
                "3. 复制 ollama.exe 的完整路径（如 C:\\Users\\用户名\\AppData\\Local\\Programs\\Ollama\\ollama.exe）",
                "4. 粘贴路径到设置中，或添加到系统 PATH",
                "5. 启动 Ollama 服务: 'ollama serve'",
                "6. 下载模型: 'ollama pull qwen3.5:4b'",
            ]
        elif dep_type == DependencyType.DEEPSEEK:
            return [
                "1. 访问 https://platform.deepseek.com 注册账号",
                "2. 创建 API Key",
                "3. 复制 API Key 粘贴到设置中",
                "4. 无需下载可执行文件",
            ]
        return []


# ============================================================================
# 全局单例
# ============================================================================

_global_manager: Optional[DependencyManager] = None


def get_dependency_manager() -> DependencyManager:
    """获取全局 DependencyManager 单例"""
    global _global_manager
    if _global_manager is None:
        _global_manager = DependencyManager()
    return _global_manager
