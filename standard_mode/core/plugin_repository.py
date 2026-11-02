# -*- coding: utf-8 -*-
"""
插件在线仓库 — PluginRepository
================================

职责：
- 插件市场在线仓库管理
- 插件搜索 / 浏览 / 分类
- 远程插件元数据缓存
- 插件下载与安装协调
- 版本兼容性检查

与 PluginManager / PluginLifecycleManager 协作：
- PluginRepository 负责远程仓库交互（搜索、获取元数据、下载）
- PluginLifecycleManager 负责本地安装/卸载/启用/禁用
- PluginManager 负责运行时加载/卸载/沙箱
"""

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

logger = logging.getLogger("plugin_repository")
logger.addHandler(logging.NullHandler())


def _get_logger():
    try:
        from shared.logger import get_logger
        return get_logger("plugin_repository")
    except ImportError:
        return logger


# ============================================================
# RepositoryPluginEntry
# ============================================================

@dataclass
class RepositoryPluginEntry:
    """仓库中的插件条目"""
    name: str
    version: str
    description: str = ""
    author: str = ""
    category: str = "other"
    tags: List[str] = field(default_factory=list)
    downloads: int = 0
    rating: float = 0.0
    updated_at: str = ""
    homepage: str = ""
    repository_url: str = ""
    download_url: str = ""
    manifest_url: str = ""
    icon_url: str = ""
    license: str = "MIT"
    min_lemon_version: str = "3.0.0"
    dependencies: Dict[str, str] = field(default_factory=dict)
    screenshots: List[str] = field(default_factory=list)
    is_verified: bool = False
    is_official: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryPluginEntry":
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            category=data.get("category", "other"),
            tags=data.get("tags", []),
            downloads=data.get("downloads", 0),
            rating=data.get("rating", 0.0),
            updated_at=data.get("updated_at", ""),
            homepage=data.get("homepage", ""),
            repository_url=data.get("repository_url", ""),
            download_url=data.get("download_url", ""),
            manifest_url=data.get("manifest_url", ""),
            icon_url=data.get("icon_url", ""),
            license=data.get("license", "MIT"),
            min_lemon_version=data.get("min_lemon_version", "3.0.0"),
            dependencies=data.get("dependencies", {}),
            screenshots=data.get("screenshots", []),
            is_verified=data.get("is_verified", False),
            is_official=data.get("is_official", False),
        )


# ============================================================
# SearchQuery
# ============================================================

@dataclass
class SearchQuery:
    """插件搜索查询"""
    keyword: str = ""
    category: str = ""
    tags: List[str] = field(default_factory=list)
    author: str = ""
    sort_by: str = "downloads"  # downloads | rating | updated | name
    sort_order: str = "desc"   # asc | desc
    page: int = 1
    page_size: int = 20
    min_rating: float = 0.0
    verified_only: bool = False

    def to_params(self) -> Dict[str, Any]:
        params = {}
        if self.keyword:
            params["q"] = self.keyword
        if self.category:
            params["category"] = self.category
        if self.tags:
            params["tags"] = ",".join(self.tags)
        if self.author:
            params["author"] = self.author
        params["sort"] = self.sort_by
        params["order"] = self.sort_order
        params["page"] = self.page
        params["per_page"] = self.page_size
        if self.min_rating > 0:
            params["min_rating"] = self.min_rating
        if self.verified_only:
            params["verified"] = "true"
        return params


# ============================================================
# CacheEntry
# ============================================================

@dataclass
class _CacheEntry:
    data: Any
    expires_at: float


# ============================================================
# PluginRepository
# ============================================================

class PluginRepository:
    """插件在线仓库

    功能：
    - 搜索插件（关键词、分类、标签、评分）
    - 浏览热门/最新插件
    - 获取插件详情和元数据
    - 下载插件到本地
    - 缓存仓库索引以提升性能

    使用方式：
        repo = PluginRepository()
        results = repo.search("code review")
        entry = repo.get_plugin("code_reviewer")
        repo.install_plugin("code_reviewer", lifecycle_manager)
    """

    # 默认官方仓库 URL
    DEFAULT_REPO_URL = "https://plugins.lemon-code.dev/api/v1"
    # 缓存文件路径
    DEFAULT_CACHE_FILE = "repo_cache.json"
    # 索引缓存 TTL（秒）
    DEFAULT_INDEX_TTL = 3600  # 1 小时
    # 详情缓存 TTL（秒）
    DEFAULT_DETAIL_TTL = 86400  # 24 小时

    def __init__(
        self,
        repo_url: str = None,
        cache_dir: str = None,
        index_ttl: float = None,
        detail_ttl: float = None,
    ):
        self._logger = _get_logger()
        self._repo_url = (repo_url or self.DEFAULT_REPO_URL).rstrip("/")
        self._index_ttl = index_ttl or self.DEFAULT_INDEX_TTL
        self._detail_ttl = detail_ttl or self.DEFAULT_DETAIL_TTL
        self._lock = threading.RLock()

        # 缓存目录
        if cache_dir is None:
            cache_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                ".plugin_cache"
            )
        self._cache_dir = os.path.abspath(cache_dir)
        self._cache_file = os.path.join(self._cache_dir, self.DEFAULT_CACHE_FILE)
        os.makedirs(self._cache_dir, exist_ok=True)

        # 内存缓存
        self._index_cache: Optional[List[RepositoryPluginEntry]] = None
        self._index_cache_time: float = 0.0
        self._detail_cache: Dict[str, _CacheEntry] = {}
        self._stats = {"searches": 0, "cache_hits": 0, "installs": 0}

        self._logger.info(
            "PluginRepository 初始化完成 (repo=%s, cache=%s)",
            self._repo_url, self._cache_dir,
        )

    # ================================================================
    # 搜索 / 浏览
    # ================================================================

    def search(self, query: SearchQuery = None) -> List[RepositoryPluginEntry]:
        """搜索插件

        Args:
            query: 搜索查询参数，None 则返回所有插件

        Returns:
            匹配的插件条目列表
        """
        query = query or SearchQuery()
        self._stats["searches"] += 1

        # 获取索引
        index = self._get_index()
        if not index:
            return []

        # 本地过滤（因为远程 API 可能不可用）
        results = self._filter_local(index, query)
        self._logger.debug(
            "搜索 '%s' 返回 %d 条结果 (总数 %d)",
            query.keyword, len(results), len(index),
        )
        return results

    def browse_by_category(self, category: str) -> List[RepositoryPluginEntry]:
        """按分类浏览插件"""
        index = self._get_index()
        if not index:
            return []
        return [p for p in index if p.category == category]

    def browse_popular(self, limit: int = 20) -> List[RepositoryPluginEntry]:
        """热门插件"""
        index = self._get_index()
        if not index:
            return []
        sorted_plugins = sorted(index, key=lambda p: p.downloads, reverse=True)
        return sorted_plugins[:limit]

    def browse_newest(self, limit: int = 20) -> List[RepositoryPluginEntry]:
        """最新插件"""
        index = self._get_index()
        if not index:
            return []
        sorted_plugins = sorted(index, key=lambda p: p.updated_at, reverse=True)
        return sorted_plugins[:limit]

    def get_plugin(self, name: str) -> Optional[RepositoryPluginEntry]:
        """获取插件详情

        Args:
            name: 插件名称

        Returns:
            插件条目，未找到返回 None
        """
        # 先查缓存
        with self._lock:
            cached = self._detail_cache.get(name)
            if cached and time.monotonic() < cached.expires_at:
                self._stats["cache_hits"] += 1
                return cached.data

        # 从索引中查找
        index = self._get_index()
        if not index:
            return None

        for plugin in index:
            if plugin.name == name:
                # 缓存详情
                with self._lock:
                    self._detail_cache[name] = _CacheEntry(
                        data=plugin,
                        expires_at=time.monotonic() + self._detail_ttl,
                    )
                return plugin

        return None

    def get_categories(self) -> List[Dict[str, Any]]:
        """获取所有分类及每个分类的插件数量"""
        index = self._get_index()
        if not index:
            return []

        category_counts: Dict[str, int] = {}
        for plugin in index:
            cat = plugin.category or "other"
            category_counts[cat] = category_counts.get(cat, 0) + 1

        return [
            {"name": cat, "count": count}
            for cat, count in sorted(category_counts.items())
        ]

    # ================================================================
    # 安装
    # ================================================================

    def install_plugin(
        self,
        plugin_name: str,
        lifecycle_manager=None,
        force: bool = False,
    ) -> Tuple[bool, str]:
        """安装插件

        Args:
            plugin_name: 插件名称
            lifecycle_manager: PluginLifecycleManager 实例
            force: 是否强制重新安装

        Returns:
            (success, message)
        """
        entry = self.get_plugin(plugin_name)
        if entry is None:
            return False, f"插件 '{plugin_name}' 在仓库中未找到"

        if lifecycle_manager is None:
            return False, "需要提供 PluginLifecycleManager 实例"

        # 检查是否已安装
        installed = lifecycle_manager.get_installed()
        if plugin_name in installed and not force:
            return False, f"插件 '{plugin_name}' 已安装（使用 force=True 强制重装）"

        # 下载插件
        success, local_path = self._download_plugin(entry)
        if not success:
            return False, f"下载失败: {local_path}"

        # 使用生命周期管理器安装
        try:
            from .plugin_manifest import PluginManifest

            manifest = PluginManifest(
                name=entry.name,
                version=entry.version,
                description=entry.description,
                author=entry.author,
                dependencies=entry.dependencies,
                is_builtin=False,
                download_url=entry.download_url,
                entry_point="",
            )
            installed_ok = lifecycle_manager.install(manifest, source_path=local_path)
            if installed_ok:
                self._stats["installs"] += 1
                return True, f"插件 '{plugin_name}' v{entry.version} 安装成功"
            else:
                return False, f"插件 '{plugin_name}' 安装失败"
        except ImportError:
            return False, "PluginManifest 不可用，无法安装"
        except Exception as e:
            self._logger.exception("安装插件失败: %s", plugin_name)
            return False, f"安装异常: {e}"

    # ================================================================
    # 统计
    # ================================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取仓库统计信息"""
        index = self._get_index()
        return {
            "total_plugins": len(index) if index else 0,
            "searches": self._stats["searches"],
            "cache_hits": self._stats["cache_hits"],
            "installs": self._stats["installs"],
            "cache_age_s": time.monotonic() - self._index_cache_time if self._index_cache_time else 0,
        }

    def clear_cache(self) -> None:
        """清除所有缓存"""
        with self._lock:
            self._index_cache = None
            self._index_cache_time = 0.0
            self._detail_cache.clear()
        self._logger.info("插件仓库缓存已清除")

    # ================================================================
    # 内部方法
    # ================================================================

    def _get_index(self) -> List[RepositoryPluginEntry]:
        """获取插件索引（优先缓存）"""
        with self._lock:
            if self._index_cache is not None:
                age = time.monotonic() - self._index_cache_time
                if age < self._index_ttl:
                    self._stats["cache_hits"] += 1
                    return self._index_cache

        # 尝试从远程获取
        remote_index = self._fetch_remote_index()
        if remote_index:
            with self._lock:
                self._index_cache = remote_index
                self._index_cache_time = time.monotonic()
            self._save_cache(remote_index)
            return remote_index

        # 降级：从本地缓存加载
        cached = self._load_cache()
        if cached:
            self._logger.warning("远程仓库不可用，使用本地缓存")
            with self._lock:
                self._index_cache = cached
                self._index_cache_time = time.monotonic()
            return cached

        # 最后降级：内置示例插件
        fallback = self._get_builtin_plugins()
        self._logger.warning("无可用缓存，使用内置示例插件列表")
        return fallback

    def _fetch_remote_index(self) -> Optional[List[RepositoryPluginEntry]]:
        """从远程仓库获取插件索引"""
        try:
            import requests
            url = f"{self._repo_url}/plugins/index.json"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                plugins = data.get("plugins", data) if isinstance(data, dict) else data
                return [
                    RepositoryPluginEntry.from_dict(p)
                    for p in plugins
                    if isinstance(p, dict)
                ]
            self._logger.warning("远程仓库返回 %d: %s", resp.status_code, url)
        except requests.exceptions.Timeout:
            self._logger.warning("远程仓库请求超时")
        except requests.exceptions.ConnectionError:
            self._logger.debug("远程仓库连接失败（可能离线）")
        except Exception as e:
            self._logger.debug("获取远程索引失败: %s", e)

        return None

    def _download_plugin(self, entry: RepositoryPluginEntry) -> Tuple[bool, str]:
        """下载插件到本地缓存目录

        Returns:
            (success, local_path_or_error)
        """
        if not entry.download_url:
            return False, "插件无下载链接"

        download_dir = os.path.join(self._cache_dir, "downloads")
        os.makedirs(download_dir, exist_ok=True)

        plugin_dir = os.path.join(download_dir, f"{entry.name}-{entry.version}")
        if os.path.exists(plugin_dir):
            return True, plugin_dir

        try:
            import requests
            import zipfile
            import io
            import tempfile

            resp = requests.get(entry.download_url, timeout=30)
            if resp.status_code != 200:
                return False, f"下载失败 HTTP {resp.status_code}"

            # 尝试解压 zip
            try:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    zf.extractall(plugin_dir)
            except zipfile.BadZipFile:
                # 不是 zip，当作单文件处理
                os.makedirs(plugin_dir, exist_ok=True)
                ext = entry.name.split(".")[-1] if "." in entry.name else "py"
                filename = f"{entry.name}.{ext}"
                filepath = os.path.join(plugin_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(resp.content)

            return True, plugin_dir

        except Exception as e:
            self._logger.exception("下载插件失败: %s", entry.name)
            return False, str(e)

    def _filter_local(
        self,
        index: List[RepositoryPluginEntry],
        query: SearchQuery,
    ) -> List[RepositoryPluginEntry]:
        """本地过滤插件索引"""
        results = index

        # 关键词过滤
        if query.keyword:
            kw = query.keyword.lower()
            results = [
                p for p in results
                if kw in p.name.lower()
                or kw in p.description.lower()
                or any(kw in t.lower() for t in p.tags)
            ]

        # 分类过滤
        if query.category:
            results = [p for p in results if p.category == query.category]

        # 标签过滤
        if query.tags:
            results = [
                p for p in results
                if any(t in p.tags for t in query.tags)
            ]

        # 作者过滤
        if query.author:
            results = [p for p in results if query.author.lower() in p.author.lower()]

        # 评分过滤
        if query.min_rating > 0:
            results = [p for p in results if p.rating >= query.min_rating]

        # 仅认证
        if query.verified_only:
            results = [p for p in results if p.is_verified]

        # 排序
        if query.sort_by == "downloads":
            results = sorted(results, key=lambda p: p.downloads, reverse=(query.sort_order == "desc"))
        elif query.sort_by == "rating":
            results = sorted(results, key=lambda p: p.rating, reverse=(query.sort_order == "desc"))
        elif query.sort_by == "updated":
            results = sorted(results, key=lambda p: p.updated_at, reverse=(query.sort_order == "desc"))
        elif query.sort_by == "name":
            results = sorted(results, key=lambda p: p.name.lower(), reverse=(query.sort_order == "desc"))

        # 分页
        start = (query.page - 1) * query.page_size
        end = start + query.page_size
        return results[start:end]

    def _save_cache(self, plugins: List[RepositoryPluginEntry]) -> None:
        """保存索引到本地缓存文件"""
        try:
            data = {
                "cached_at": time.time(),
                "plugins": [p.to_dict() for p in plugins],
            }
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._logger.debug("保存缓存失败: %s", e)

    def _load_cache(self) -> Optional[List[RepositoryPluginEntry]]:
        """从本地缓存文件加载索引"""
        try:
            if not os.path.exists(self._cache_file):
                return None
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            plugins = [
                RepositoryPluginEntry.from_dict(p)
                for p in data.get("plugins", [])
            ]
            cache_age = time.time() - data.get("cached_at", 0)
            self._logger.debug(
                "从本地缓存加载 %d 个插件 (缓存年龄: %.0fs)",
                len(plugins), cache_age,
            )
            return plugins
        except Exception as e:
            self._logger.debug("加载缓存失败: %s", e)
            return None

    def _get_builtin_plugins(self) -> List[RepositoryPluginEntry]:
        """内置示例插件列表（离线降级）"""
        return [
            RepositoryPluginEntry(
                name="code_reviewer",
                version="1.0.0",
                description="代码审查助手 — 自动检测代码质量问题、安全漏洞和最佳实践违规",
                author="Lemon Code Team",
                category="code",
                tags=["code-review", "quality", "security"],
                downloads=1250,
                rating=4.7,
                is_verified=True,
                is_official=True,
            ),
            RepositoryPluginEntry(
                name="test_generator",
                version="1.0.0",
                description="测试生成器 — 自动生成单元测试、集成测试和端到端测试",
                author="Lemon Code Team",
                category="code",
                tags=["testing", "unit-test", "coverage"],
                downloads=980,
                rating=4.5,
                is_verified=True,
                is_official=True,
            ),
            RepositoryPluginEntry(
                name="deep_researcher",
                version="1.0.0",
                description="深度研究器 — 多轮搜索、信息交叉验证、结构化报告生成",
                author="Lemon Code Team",
                category="research",
                tags=["research", "search", "analysis"],
                downloads=750,
                rating=4.3,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="security_auditor",
                version="1.0.0",
                description="安全审计员 — 扫描代码安全漏洞、依赖风险、敏感信息泄露",
                author="Lemon Code Team",
                category="security",
                tags=["security", "audit", "vulnerability"],
                downloads=680,
                rating=4.8,
                is_verified=True,
                is_official=True,
            ),
            RepositoryPluginEntry(
                name="math_solver",
                version="1.0.0",
                description="数学求解器 — 解方程、微积分、线性代数、概率统计",
                author="Lemon Code Team",
                category="math",
                tags=["math", "equation", "calculus"],
                downloads=890,
                rating=4.6,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="web_researcher",
                version="1.0.0",
                description="网络研究员 — 实时搜索、网页抓取、信息提取",
                author="Lemon Code Team",
                category="research",
                tags=["web", "search", "scraping"],
                downloads=620,
                rating=4.2,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="math_plotter",
                version="1.0.0",
                description="数学绘图器 — 函数图像、3D图形、统计图表",
                author="Lemon Code Team",
                category="visual",
                tags=["plot", "math", "visualization"],
                downloads=540,
                rating=4.4,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="office_generator",
                version="1.0.0",
                description="办公文档生成器 — Word/Excel/PPT 自动生成",
                author="Lemon Code Team",
                category="office",
                tags=["office", "document", "report"],
                downloads=430,
                rating=4.1,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="image_processor",
                version="1.0.0",
                description="图像处理器 — 格式转换、压缩、裁剪、滤镜",
                author="Lemon Code Team",
                category="image",
                tags=["image", "convert", "edit"],
                downloads=380,
                rating=4.0,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="fact_checker",
                version="1.0.0",
                description="事实核查器 — 交叉验证信息真伪，引用来源对比",
                author="Lemon Code Team",
                category="research",
                tags=["fact-check", "verify", "truth"],
                downloads=320,
                rating=4.3,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="html_to_video",
                version="1.0.0",
                description="HTML 转视频 — 将网页内容渲染为视频文件",
                author="Lemon Code Team",
                category="media",
                tags=["html", "video", "convert"],
                downloads=290,
                rating=3.9,
            ),
            RepositoryPluginEntry(
                name="deploy_helper",
                version="1.0.0",
                description="部署助手 — 一键部署到 Docker/K8s/云平台",
                author="Lemon Code Team",
                category="devops",
                tags=["deploy", "docker", "cloud"],
                downloads=260,
                rating=4.0,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="code_psychologist",
                version="1.0.0",
                description="代码心理学家 — 分析代码风格判断开发者心理状态",
                author="Lemon Code Team",
                category="fun",
                tags=["psychology", "fun", "analysis"],
                downloads=450,
                rating=4.5,
            ),
            RepositoryPluginEntry(
                name="multi_model_debater",
                version="1.0.0",
                description="多模型辩论家 — 调用多个 AI 模型进行辩论达成共识",
                author="Lemon Code Team",
                category="ai",
                tags=["ai", "debate", "multi-model"],
                downloads=350,
                rating=4.4,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="self_documenter",
                version="1.0.0",
                description="自文档化 — 自动生成代码文档、API 参考、架构图",
                author="Lemon Code Team",
                category="documentation",
                tags=["docs", "api", "auto-doc"],
                downloads=410,
                rating=4.2,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="arxiv_researcher",
                version="1.0.0",
                description="arXiv 研究员 — 搜索学术论文、生成文献综述",
                author="Lemon Code Team",
                category="research",
                tags=["arxiv", "paper", "academic"],
                downloads=310,
                rating=4.1,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="academic_writer",
                version="1.0.0",
                description="学术写作助手 — LaTeX/Word 论文写作、参考文献管理",
                author="Lemon Code Team",
                category="documentation",
                tags=["academic", "latex", "thesis"],
                downloads=240,
                rating=4.0,
            ),
            RepositoryPluginEntry(
                name="skill_creator",
                version="1.0.0",
                description="Skill 创建器 — 快速创建自定义 Skill 模板",
                author="Lemon Code Team",
                category="system",
                tags=["skill", "template", "create"],
                downloads=180,
                rating=3.8,
                is_verified=True,
            ),
            RepositoryPluginEntry(
                name="frontend_designer",
                version="1.0.0",
                description="前端设计师 — 生成 HTML/CSS/JSX 组件代码",
                author="Lemon Code Team",
                category="visual",
                tags=["frontend", "html", "css", "design"],
                downloads=220,
                rating=3.9,
            ),
            RepositoryPluginEntry(
                name="physics_experiment",
                version="1.0.0",
                description="物理实验模拟 — 力学/电磁学/光学实验可视化",
                author="Lemon Code Team",
                category="visual",
                tags=["physics", "simulation", "experiment"],
                downloads=190,
                rating=4.0,
            ),
        ]


# ============================================================
# 全局单例
# ============================================================

_global_repository: Optional[PluginRepository] = None
_repo_lock = threading.Lock()


def get_plugin_repository(
    repo_url: str = None,
    cache_dir: str = None,
) -> PluginRepository:
    """获取全局插件仓库单例"""
    global _global_repository
    if _global_repository is None:
        with _repo_lock:
            if _global_repository is None:
                _global_repository = PluginRepository(
                    repo_url=repo_url,
                    cache_dir=cache_dir,
                )
    return _global_repository


def reset_plugin_repository() -> None:
    """重置全局仓库单例（用于测试）"""
    global _global_repository
    with _repo_lock:
        _global_repository = None