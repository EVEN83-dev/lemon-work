# -*- coding: utf-8 -*-
"""
插件清单规范与在线仓库接口
===============================
核心能力：
- PluginManifest：标准化的插件元数据/清单描述
- PluginManifestValidator：校验清单合法性（必填字段、semver、分类、标签等）
- PluginRepository：在线仓库接口（远程拉取、搜索、下载）
- BuiltinPluginCatalog：内置插件目录（5 个预置插件）
- 辅助函数：清单文件读写、semver 解析

使用示例：
    >>> from plugin_manifest import PluginManifest, BuiltinPluginCatalog, parse_semver
    >>> cat = BuiltinPluginCatalog()
    >>> m = cat.get_by_name("markdown_preview")
    >>> print(m.display_name)  # "Markdown 预览"
    >>> parse_semver("1.2.3")   # (1, 2, 3)
"""

import os
import re
import json
import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict

import requests

# ============================================================
# 日志
# ============================================================

_logger = logging.getLogger("plugin_manifest")
_logger.addHandler(logging.NullHandler())


# ============================================================
# 常量
# ============================================================

VALID_CATEGORIES = frozenset({
    "tool", "editor", "format", "encoding", "color", "visualization", "utility",
})

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
TAG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

REQUIRED_FIELDS = frozenset({
    "name", "display_name", "version", "author", "description",
    "category", "entry_point",
})

# 远程仓库默认地址
_DEFAULT_REPO_URL = os.getenv(
    "LEMON_PLUGIN_REPO_URL",
    "https://plugins.lemoncode.dev/api/v1",
)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class PluginManifest:
    """插件清单 — 标准化元数据描述

    每个 Lemon Code 插件通过一份清单文件（manifest.json）描述自身信息。
    本 dataclass 是清单的 Python 运行时表示。
    """
    name: str                          # 唯一标识符，如 "markdown_preview"
    display_name: str                  # 人类可读名称，如 "Markdown 预览"
    version: str                       # 语义化版本，如 "1.0.0"
    author: str                        # 作者名
    description: str                   # 功能描述
    category: str                      # 分类：tool/editor/format/encoding/color/visualization/utility
    entry_point: str                   # 模块路径，如 "builtin_plugins.markdown_preview.MarkdownPreviewPlugin"
    icon: str = "📦"                   # 图标（emoji 或 SVG 名称）
    tags: List[str] = field(default_factory=list)          # 标签列表
    min_app_version: str = "1.0.0"     # 最低 Lemon Code 版本
    dependencies: List[str] = field(default_factory=list)  # 依赖插件名列表
    permissions: Dict[str, str] = field(default_factory=dict)  # 权限名 -> 描述
    config_schema: Dict[str, Any] = field(default_factory=dict)  # JSON Schema 配置定义
    repository: str = ""               # 源代码仓库 URL
    license: str = "MIT"               # SPDX 许可证标识符
    homepage: str = ""                 # 插件主页 URL

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        """从字典反序列化"""
        return cls(
            name=data.get("name", ""),
            display_name=data.get("display_name", ""),
            version=data.get("version", "0.0.0"),
            author=data.get("author", ""),
            description=data.get("description", ""),
            category=data.get("category", "utility"),
            entry_point=data.get("entry_point", ""),
            icon=data.get("icon", "📦"),
            tags=data.get("tags", []),
            min_app_version=data.get("min_app_version", "1.0.0"),
            dependencies=data.get("dependencies", []),
            permissions=data.get("permissions", {}),
            config_schema=data.get("config_schema", {}),
            repository=data.get("repository", ""),
            license=data.get("license", "MIT"),
            homepage=data.get("homepage", ""),
        )


# ============================================================
# 清单校验器
# ============================================================

class PluginManifestValidator:
    """插件清单校验器

    校验清单数据是否合法，包括：
    - 必填字段检查
    - semver 格式校验
    - category 合法性
    - tag 格式校验
    - 依赖可用性检查
    """

    # ---- 公开 API ----

    @staticmethod
    def validate(manifest_dict: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """校验清单字典，返回 (valid, errors)

        用法：
            valid, errors = PluginManifestValidator.validate(some_dict)
            if not valid:
                for e in errors:
                    print(e)
        """
        errors: List[str] = []

        # 1. 必填字段检查
        for field in REQUIRED_FIELDS:
            value = manifest_dict.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"缺少必填字段: {field}")

        # 如果缺少 name 或 version，后续校验无法继续
        if errors:
            return False, errors

        name = manifest_dict.get("name", "")
        version = manifest_dict.get("version", "")
        category = manifest_dict.get("category", "")
        tags = manifest_dict.get("tags", [])
        dependencies = manifest_dict.get("dependencies", [])
        min_app_version = manifest_dict.get("min_app_version", "1.0.0")

        # 2. name 格式校验
        if not NAME_RE.match(name):
            errors.append(
                f"name 格式非法: '{name}' — 必须以小写字母开头，"
                f"仅含小写字母、数字和下划线"
            )

        # 3. version semver 校验
        if not SEMVER_RE.match(version):
            errors.append(
                f"version 格式非法: '{version}' — 必须符合 semver 格式 (如 1.2.3)"
            )

        # 4. category 合法性
        if category and category not in VALID_CATEGORIES:
            errors.append(
                f"category 非法: '{category}' — "
                f"允许值: {', '.join(sorted(VALID_CATEGORIES))}"
            )

        # 5. tags 格式校验
        if isinstance(tags, list):
            for tag in tags:
                if not isinstance(tag, str):
                    errors.append(f"tag 类型错误: 期望 str，实际 {type(tag).__name__}")
                elif not TAG_RE.match(tag):
                    errors.append(
                        f"tag 格式非法: '{tag}' — "
                        f"必须以小写字母开头，仅含小写字母、数字和下划线"
                    )
        else:
            errors.append("tags 必须是列表类型")

        # 6. dependencies 格式
        if not isinstance(dependencies, list):
            errors.append("dependencies 必须是列表类型")

        # 7. min_app_version semver 校验（可选，但有值就校验）
        if min_app_version and not SEMVER_RE.match(min_app_version):
            errors.append(
                f"min_app_version 格式非法: '{min_app_version}' — 必须符合 semver 格式"
            )

        # 8. permissions 格式
        perms = manifest_dict.get("permissions", {})
        if not isinstance(perms, dict):
            errors.append("permissions 必须是字典类型")

        return (len(errors) == 0, errors)

    @staticmethod
    def validate_dependencies(
        manifest: PluginManifest,
        installed_plugins: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """校验清单依赖是否满足

        参数：
            manifest: 待校验的插件清单
            installed_plugins: 已安装的插件名 -> 版本号 映射

        返回：
            (all_satisfied, missing_plugins)
        """
        missing: List[str] = []
        for dep in manifest.dependencies:
            if dep not in installed_plugins:
                missing.append(dep)
        return (len(missing) == 0, missing)


# ============================================================
# 在线仓库接口
# ============================================================

class PluginRepository:
    """在线插件仓库接口

    提供从远程仓库拉取插件列表、搜索、下载等能力。
    当远程不可用时，自动降级为内置插件目录。

    特性：
    - 使用 requests.Session 保持连接复用
    - 请求超时保护（默认 15 秒）
    - 本地 fallback：远程失败时使用 BuiltinPluginCatalog
    """

    def __init__(self, repo_url: str = "", timeout: float = 15.0):
        """
        参数：
            repo_url: 远程仓库 API 根地址，留空则使用默认地址
            timeout:  HTTP 请求超时（秒）
        """
        self._repo_url = (repo_url or _DEFAULT_REPO_URL).rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "LemonCode-PluginRepository/1.0",
            "Accept": "application/json",
        })
        self._catalog = BuiltinPluginCatalog()
        self._remote_available = False

    # ---- 公开 API ----

    def fetch_index(self, repo_url: str = "") -> List[PluginManifest]:
        """从远程仓库拉取插件索引

        参数：
            repo_url: 可选，覆盖构造时设置的仓库地址

        返回：
            插件清单列表；远程不可用时返回内置插件列表
        """
        url = (repo_url or self._repo_url).rstrip("/")
        index_url = f"{url}/plugins"

        try:
            resp = self._session.get(index_url, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            plugins = self._parse_plugin_list(data)
            self._remote_available = True
            _logger.info("远程插件索引拉取成功，共 %d 个插件", len(plugins))
            return plugins
        except requests.RequestException as e:
            _logger.warning("远程插件索引拉取失败: %s，降级为内置目录", e)
            self._remote_available = False
            return self._catalog.get_all()
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            _logger.warning("远程插件索引解析失败: %s，降级为内置目录", e)
            self._remote_available = False
            return self._catalog.get_all()

    def search(
        self,
        query: str = "",
        category: str = "",
        tags: Optional[List[str]] = None,
    ) -> List[PluginManifest]:
        """搜索插件

        参数：
            query:    关键词（匹配 name/display_name/description）
            category: 按分类过滤
            tags:     按标签过滤（至少匹配一个即命中）

        返回：
            匹配的插件清单列表
        """
        plugins = self.fetch_index()

        results: List[PluginManifest] = []
        q = query.lower().strip() if query else ""
        tag_set = set(tags) if tags else set()

        for p in plugins:
            # 分类过滤
            if category and p.category != category:
                continue

            # 标签过滤（至少一个匹配）
            if tag_set and not tag_set.intersection(p.tags):
                continue

            # 关键词搜索
            if q:
                if not (
                    q in p.name.lower()
                    or q in p.display_name.lower()
                    or q in p.description.lower()
                    or any(q in t.lower() for t in p.tags)
                ):
                    continue

            results.append(p)

        return results

    def get_plugin_info(self, name: str) -> Optional[PluginManifest]:
        """获取单个插件详情

        优先从远程获取，远程不可用时从内置目录查找。

        参数：
            name: 插件唯一标识符

        返回：
            PluginManifest 或 None
        """
        # 先尝试远程
        detail_url = f"{self._repo_url}/plugins/{name}"
        try:
            resp = self._session.get(detail_url, timeout=self._timeout)
            if resp.status_code == 200:
                data = resp.json()
                return PluginManifest.from_dict(data)
        except requests.RequestException:
            pass

        # 降级为内置目录
        return self._catalog.get_by_name(name)

    def download_plugin(self, name: str, dest_dir: str) -> bool:
        """下载插件包到本地目录

        流程：
        1. 从远程仓库获取下载链接
        2. 下载 .zip 插件包
        3. 解压到 dest_dir/<name>/

        参数：
            name:     插件名称
            dest_dir: 目标目录

        返回：
            True 表示下载成功，False 表示失败
        """
        import zipfile
        import io
        import shutil

        if not os.path.isdir(dest_dir):
            try:
                os.makedirs(dest_dir, exist_ok=True)
            except OSError as e:
                _logger.error("无法创建目标目录 %s: %s", dest_dir, e)
                return False

        download_url = f"{self._repo_url}/plugins/{name}/download"
        try:
            resp = self._session.get(download_url, timeout=120.0, stream=True)
            resp.raise_for_status()
        except requests.RequestException as e:
            _logger.error("下载插件 %s 失败: %s", name, e)
            return False

        content_type = resp.headers.get("Content-Type", "")

        try:
            if "zip" in content_type or name.endswith(".zip"):
                # 下载并解压 zip 包
                raw = io.BytesIO()
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        raw.write(chunk)
                raw.seek(0)

                extract_dir = os.path.join(dest_dir, name)
                if os.path.exists(extract_dir):
                    shutil.rmtree(extract_dir)
                os.makedirs(extract_dir, exist_ok=True)

                with zipfile.ZipFile(raw, "r") as zf:
                    zf.extractall(extract_dir)
                _logger.info("插件 %s 下载并解压到 %s", name, extract_dir)
            else:
                # 直接保存为文件
                filepath = os.path.join(dest_dir, f"{name}.zip")
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                _logger.info("插件 %s 下载到 %s", name, filepath)

            return True
        except (zipfile.BadZipFile, OSError, IOError) as e:
            _logger.error("插件 %s 解压/写入失败: %s", name, e)
            return False

    @property
    def is_remote_available(self) -> bool:
        """远程仓库是否可用（基于最近一次 fetch_index 调用结果）"""
        return self._remote_available

    def close(self):
        """关闭 HTTP 会话"""
        try:
            self._session.close()
        except Exception:
            pass

    # ---- 内部方法 ----

    def _parse_plugin_list(self, data: Any) -> List[PluginManifest]:
        """解析远程返回的插件列表数据"""
        items: List[Dict[str, Any]] = []

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # 兼容 { "plugins": [...], "total": N } 格式
            items = data.get("plugins", [])
            if not items:
                items = data.get("data", [])

        return [PluginManifest.from_dict(item) for item in items]


# ============================================================
# 内置插件目录
# ============================================================

class BuiltinPluginCatalog:
    """内置插件目录

    预置 5 个开箱即用的插件，每个插件都有完整的清单数据。
    在远程仓库不可用时作为本地 fallback。
    """

    def __init__(self):
        self._plugins: Dict[str, PluginManifest] = {}
        self._load_builtins()

    # ---- 公开 API ----

    def get_all(self) -> List[PluginManifest]:
        """获取所有内置插件清单"""
        return list(self._plugins.values())

    def get_by_name(self, name: str) -> Optional[PluginManifest]:
        """按名称获取单个插件清单"""
        return self._plugins.get(name)

    def list_names(self) -> List[str]:
        """列出所有内置插件名称"""
        return list(self._plugins.keys())

    # ---- 内部 ----

    def _load_builtins(self):
        """加载内置插件"""
        self._plugins = {
            "markdown_preview": PluginManifest(
                name="markdown_preview",
                display_name="Markdown 预览",
                version="1.0.0",
                author="Lemon Code Team",
                description="Markdown 实时预览：支持 md→html 转换、语法校验、代码高亮",
                category="editor",
                icon="📝",
                tags=["markdown", "preview", "html", "render"],
                min_app_version="1.0.0",
                dependencies=[],
                permissions={
                    "file_access": "读取当前编辑的文件内容",
                    "network_access": "加载远程图片资源",
                },
                entry_point="builtin_plugins.markdown_preview.MarkdownPreviewPlugin",
                config_schema={
                    "type": "object",
                    "properties": {
                        "auto_preview": {
                            "type": "boolean",
                            "title": "自动预览",
                            "description": "编辑时自动刷新预览",
                            "default": True,
                        },
                        "extensions": {
                            "type": "array",
                            "title": "支持的文件扩展名",
                            "items": {"type": "string"},
                            "default": [".md", ".markdown"],
                        },
                        "theme": {
                            "type": "string",
                            "title": "预览主题",
                            "enum": ["light", "dark", "auto"],
                            "default": "auto",
                        },
                    },
                },
                repository="https://github.com/lemoncode/builtin-markdown-preview",
                license="MIT",
                homepage="https://lemoncode.dev/plugins/markdown_preview",
            ),
            "json_formatter": PluginManifest(
                name="json_formatter",
                display_name="JSON 格式化",
                version="1.0.0",
                author="Lemon Code Team",
                description="JSON 格式化、校验、JSONPath 查询与压缩工具",
                category="format",
                icon="🔧",
                tags=["json", "format", "validate", "jsonpath"],
                min_app_version="1.0.0",
                dependencies=[],
                permissions={
                    "file_access": "读取/写入 JSON 文件",
                },
                entry_point="builtin_plugins.json_formatter.JsonFormatterPlugin",
                config_schema={
                    "type": "object",
                    "properties": {
                        "indent": {
                            "type": "integer",
                            "title": "缩进空格数",
                            "minimum": 0,
                            "maximum": 8,
                            "default": 2,
                        },
                        "ensure_ascii": {
                            "type": "boolean",
                            "title": "ASCII 转义",
                            "description": "是否将非 ASCII 字符转义为 \\uXXXX",
                            "default": False,
                        },
                        "sort_keys": {
                            "type": "boolean",
                            "title": "键排序",
                            "default": False,
                        },
                    },
                },
                repository="https://github.com/lemoncode/builtin-json-formatter",
                license="MIT",
                homepage="https://lemoncode.dev/plugins/json_formatter",
            ),
            "color_picker": PluginManifest(
                name="color_picker",
                display_name="颜色选择器",
                version="1.0.0",
                author="Lemon Code Team",
                description="HEX/RGB/HSL 颜色互转、调色板生成与色彩对比度计算",
                category="color",
                icon="🎨",
                tags=["color", "design", "palette", "hex", "rgb", "hsl"],
                min_app_version="1.0.0",
                dependencies=[],
                permissions={},
                entry_point="builtin_plugins.color_picker.ColorPickerPlugin",
                config_schema={
                    "type": "object",
                    "properties": {
                        "default_count": {
                            "type": "integer",
                            "title": "默认调色板数量",
                            "minimum": 3,
                            "maximum": 12,
                            "default": 5,
                        },
                        "default_format": {
                            "type": "string",
                            "title": "默认颜色格式",
                            "enum": ["hex", "rgb", "hsl"],
                            "default": "hex",
                        },
                    },
                },
                repository="https://github.com/lemoncode/builtin-color-picker",
                license="MIT",
                homepage="https://lemoncode.dev/plugins/color_picker",
            ),
            "regex_tester": PluginManifest(
                name="regex_tester",
                display_name="正则测试器",
                version="1.0.0",
                author="Lemon Code Team",
                description="正则表达式匹配测试、替换预览与反向引用说明",
                category="tool",
                icon="🔍",
                tags=["regex", "test", "pattern", "replace"],
                min_app_version="1.0.0",
                dependencies=[],
                permissions={},
                entry_point="builtin_plugins.regex_tester.RegexTesterPlugin",
                config_schema={
                    "type": "object",
                    "properties": {
                        "max_matches": {
                            "type": "integer",
                            "title": "最大匹配数",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100,
                        },
                        "default_flags": {
                            "type": "string",
                            "title": "默认标志",
                            "description": "如 'gi' 表示全局+忽略大小写",
                            "default": "g",
                        },
                    },
                },
                repository="https://github.com/lemoncode/builtin-regex-tester",
                license="MIT",
                homepage="https://lemoncode.dev/plugins/regex_tester",
            ),
            "base64_tool": PluginManifest(
                name="base64_tool",
                display_name="Base64 编解码",
                version="1.0.0",
                author="Lemon Code Team",
                description="Base64 编码/解码/文件编码，支持标准与 URL 安全变体",
                category="encoding",
                icon="🔐",
                tags=["base64", "encode", "decode", "file"],
                min_app_version="1.0.0",
                dependencies=[],
                permissions={
                    "file_access": "读取用户选择的文件进行编码",
                },
                entry_point="builtin_plugins.base64_tool.Base64ToolPlugin",
                config_schema={
                    "type": "object",
                    "properties": {
                        "max_file_size": {
                            "type": "integer",
                            "title": "最大文件大小 (MB)",
                            "minimum": 1,
                            "maximum": 50,
                            "default": 10,
                        },
                        "url_safe": {
                            "type": "boolean",
                            "title": "URL 安全模式",
                            "description": "使用 URL 安全的 Base64 变体 (RFC 4648 §5)",
                            "default": False,
                        },
                    },
                },
                repository="https://github.com/lemoncode/builtin-base64-tool",
                license="MIT",
                homepage="https://lemoncode.dev/plugins/base64_tool",
            ),
        }


# ============================================================
# 辅助函数
# ============================================================

def parse_semver(version_str: str) -> Tuple[int, int, int]:
    """解析语义化版本字符串为 (major, minor, patch) 三元组

    参数：
        version_str: 版本字符串，如 "1.2.3"

    返回：
        (major, minor, patch)

    异常：
        ValueError: 版本格式不合法
    """
    m = SEMVER_RE.match(version_str.strip())
    if not m:
        raise ValueError(
            f"非法 semver 版本: '{version_str}' — 期望格式如 '1.2.3'"
        )
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def load_manifest_from_file(filepath: str) -> PluginManifest:
    """从 JSON 文件加载清单

    参数：
        filepath: manifest.json 文件路径

    返回：
        PluginManifest 实例

    异常：
        FileNotFoundError: 文件不存在
        json.JSONDecodeError: JSON 格式错误
        ValueError: 校验失败
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"清单文件不存在: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 校验
    valid, errors = PluginManifestValidator.validate(data)
    if not valid:
        raise ValueError(
            f"清单校验失败 ({filepath}):\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return PluginManifest.from_dict(data)


def save_manifest_to_file(manifest: PluginManifest, filepath: str) -> bool:
    """将清单保存为 JSON 文件

    参数：
        manifest: PluginManifest 实例
        filepath: 目标文件路径

    返回：
        True 表示写入成功
    """
    try:
        parent = os.path.dirname(os.path.abspath(filepath))
        if parent:
            os.makedirs(parent, exist_ok=True)

        data = manifest.to_dict()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except (OSError, IOError, TypeError) as e:
        _logger.error("保存清单到 %s 失败: %s", filepath, e)
        return False


# ============================================================
# 便捷构造
# ============================================================

def create_minimal_manifest(
    name: str,
    display_name: str,
    version: str,
    author: str,
    description: str,
    category: str,
    entry_point: str,
) -> PluginManifest:
    """快速构造一个最小合法的 PluginManifest

    参数：
        name:         唯一标识符
        display_name: 展示名称
        version:      版本号
        author:       作者
        description:  描述
        category:     分类
        entry_point:  入口模块路径

    返回：
        PluginManifest 实例
    """
    return PluginManifest(
        name=name,
        display_name=display_name,
        version=version,
        author=author,
        description=description,
        category=category,
        entry_point=entry_point,
    )