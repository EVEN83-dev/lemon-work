# -*- coding: utf-8 -*-
"""
启动加速模块 — StartupOptimizer
================================
通过懒加载、预编译、并行初始化等手段加速应用启动。

功能：
1. LazyLoader — 延迟导入，按需加载模块
2. StartupProfiler — 启动耗时分析
3. PreloadCache — 预加载缓存，加速常用模块加载
4. ParallelInitializer — 并行初始化非关键组件
"""

import importlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("lemon.startup_optimizer")


# ============================================================
# LazyLoader
# ============================================================

class LazyLoader:
    """延迟加载器

    将模块导入延迟到实际使用时，减少启动时间。

    使用方式：
        lazy_mod = LazyLoader("standard_mode.core.plugin_repository")
        # 模块在首次访问时才会实际导入
        repo = lazy_mod.get_plugin_repository()

    或作为属性代理：
        class MyClass:
            plugin_repo = LazyLoader("standard_mode.core.plugin_repository")
            # 访问 self.plugin_repo 时自动加载模块
    """

    def __init__(self, module_path: str, attr_name: str = None):
        """
        Args:
            module_path: 模块路径（如 "standard_mode.core.plugin_repository"）
            attr_name: 要获取的属性名，None 则返回模块本身
        """
        self._module_path = module_path
        self._attr_name = attr_name
        self._module: Optional[Any] = None
        self._loaded = False
        self._lock = threading.Lock()
        self._load_time: float = 0.0

    def __get__(self, obj, objtype=None):
        """描述符协议：支持作为类属性使用"""
        if obj is None:
            return self
        return self.load()

    def load(self) -> Any:
        """加载模块并返回"""
        if self._loaded:
            return self._get_target()

        with self._lock:
            if self._loaded:
                return self._get_target()

            start = time.monotonic()
            try:
                self._module = importlib.import_module(self._module_path)
            except ImportError as e:
                logger.warning(
                    "LazyLoader 加载失败: %s (%s)",
                    self._module_path, e,
                )
                self._module = None
                self._loaded = True
                return None

            self._load_time = (time.monotonic() - start) * 1000
            self._loaded = True
            logger.debug(
                "LazyLoader 加载 %s (%.1fms)",
                self._module_path, self._load_time,
            )
            return self._get_target()

    def _get_target(self) -> Any:
        """获取目标对象"""
        if self._module is None:
            return None
        if self._attr_name:
            return getattr(self._module, self._attr_name, None)
        return self._module

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def load_time_ms(self) -> float:
        return self._load_time


# ============================================================
# StartupProfiler
# ============================================================

@dataclass
class ProfileEntry:
    """启动耗时条目"""
    name: str
    duration_ms: float = 0.0
    start_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class StartupProfiler:
    """启动耗时分析器

    使用方式：
        profiler = StartupProfiler()
        with profiler.measure("load_plugins"):
            load_all_plugins()
        profiler.report()
    """

    def __init__(self):
        self._entries: List[ProfileEntry] = []
        self._start_time: float = time.monotonic()
        self._lock = threading.Lock()

    def measure(self, name: str, **metadata):
        """上下文管理器：测量代码块耗时"""
        return _ProfileContext(self, name, metadata)

    def add_entry(self, name: str, duration_ms: float, **metadata):
        """手动添加耗时条目"""
        with self._lock:
            self._entries.append(ProfileEntry(
                name=name,
                duration_ms=duration_ms,
                start_time=time.monotonic(),
                metadata=metadata,
            ))

    def get_total_ms(self) -> float:
        """总启动耗时（毫秒）"""
        return (time.monotonic() - self._start_time) * 1000

    def report(self) -> str:
        """生成启动耗时报告"""
        total = self.get_total_ms()
        lines = [
            "=" * 50,
            f"  启动耗时报告 (总计: {total:.0f}ms)",
            "=" * 50,
        ]

        # 按耗时降序排列
        sorted_entries = sorted(self._entries, key=lambda e: e.duration_ms, reverse=True)

        for entry in sorted_entries:
            pct = (entry.duration_ms / max(total, 0.01)) * 100
            bar = "█" * min(int(pct / 2), 25)
            lines.append(
                f"  {entry.name:<30s} {entry.duration_ms:>7.1f}ms  "
                f"{bar} ({pct:.0f}%)"
            )

        lines.append("=" * 50)
        return "\n".join(lines)

    def get_slowest(self, top_n: int = 5) -> List[ProfileEntry]:
        """获取最慢的 N 个条目"""
        return sorted(self._entries, key=lambda e: e.duration_ms, reverse=True)[:top_n]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_ms": self.get_total_ms(),
            "entries": [
                {
                    "name": e.name,
                    "duration_ms": round(e.duration_ms, 2),
                    "metadata": e.metadata,
                }
                for e in self._entries
            ],
        }


class _ProfileContext:
    """测量上下文管理器"""

    def __init__(self, profiler: StartupProfiler, name: str, metadata: dict):
        self._profiler = profiler
        self._name = name
        self._metadata = metadata
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *args):
        duration = (time.monotonic() - self._start) * 1000
        self._profiler.add_entry(self._name, duration, **self._metadata)


# ============================================================
# PreloadCache
# ============================================================

class PreloadCache:
    """预加载缓存

    缓存常用模块和对象，减少重复导入开销。

    使用方式：
        cache = PreloadCache()
        cache.register("config", load_config)
        cache.preload_all()  # 后台线程加载
        config = cache.get("config")  # 立即返回
    """

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._loaders: Dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._loading: Dict[str, threading.Event] = {}
        self._thread: Optional[threading.Thread] = None

    def register(self, key: str, loader: Callable) -> None:
        """注册预加载项"""
        with self._lock:
            self._loaders[key] = loader
            self._loading[key] = threading.Event()

    def preload(self, key: str) -> bool:
        """立即加载指定项"""
        loader = self._loaders.get(key)
        if loader is None:
            return False

        with self._lock:
            if key in self._cache:
                return True

        try:
            value = loader()
            with self._lock:
                self._cache[key] = value
                if key in self._loading:
                    self._loading[key].set()
            return True
        except Exception as e:
            logger.warning("预加载失败: %s (%s)", key, e)
            return False

    def preload_all(self, background: bool = True) -> None:
        """预加载所有注册项

        Args:
            background: 是否在后台线程加载
        """
        if background:
            self._thread = threading.Thread(
                target=self._preload_all_worker,
                name="PreloadCache",
                daemon=True,
            )
            self._thread.start()
        else:
            self._preload_all_worker()

    def get(self, key: str, timeout: float = 5.0) -> Optional[Any]:
        """获取缓存值（阻塞等待加载完成）"""
        with self._lock:
            if key in self._cache:
                return self._cache[key]

        event = self._loading.get(key)
        if event is None:
            # 未注册，尝试立即加载
            self.preload(key)
            with self._lock:
                return self._cache.get(key)

        # 等待加载完成
        if event.wait(timeout):
            with self._lock:
                return self._cache.get(key)

        return None

    def is_loaded(self, key: str) -> bool:
        with self._lock:
            return key in self._cache

    def _preload_all_worker(self) -> None:
        """后台预加载工作线程"""
        keys = list(self._loaders.keys())
        for key in keys:
            self.preload(key)


# ============================================================
# ParallelInitializer
# ============================================================

class ParallelInitializer:
    """并行初始化器

    并行初始化多个非关键组件，减少总启动时间。

    使用方式：
        init = ParallelInitializer()
        init.add("load_plugins", load_plugins)
        init.add("load_skills", register_skills)
        init.run_all()
        # 等待所有完成
        init.wait_all()
    """

    def __init__(self, max_workers: int = 4):
        self._max_workers = max_workers
        self._tasks: List[Tuple[str, Callable]] = []
        self._results: Dict[str, Any] = {}
        self._errors: Dict[str, Exception] = {}
        self._events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def add(self, name: str, task: Callable) -> None:
        """添加初始化任务"""
        self._tasks.append((name, task))
        self._events[name] = threading.Event()

    def run_all(self, background: bool = True) -> None:
        """执行所有任务

        Args:
            background: True 在后台线程执行，False 阻塞当前线程
        """
        if background:
            thread = threading.Thread(
                target=self._run_all_worker,
                name="ParallelInit",
                daemon=True,
            )
            thread.start()
        else:
            self._run_all_worker()

    def wait_all(self, timeout: float = 30.0) -> bool:
        """等待所有任务完成

        Returns:
            True 所有任务完成，False 超时
        """
        for name, event in self._events.items():
            if not event.wait(timeout):
                return False
        return True

    def is_done(self) -> bool:
        return all(e.is_set() for e in self._events.values())

    def get_results(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._results)

    def get_errors(self) -> Dict[str, Exception]:
        with self._lock:
            return dict(self._errors)

    def _run_all_worker(self) -> None:
        """工作线程"""
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._max_workers
        ) as executor:
            futures = {}
            for name, task in self._tasks:
                futures[executor.submit(self._run_one, name, task)] = name

            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass

    def _run_one(self, name: str, task: Callable) -> None:
        """执行单个任务"""
        try:
            result = task()
            with self._lock:
                self._results[name] = result
        except Exception as e:
            with self._lock:
                self._errors[name] = e
            logger.warning("并行初始化失败: %s (%s)", name, e)
        finally:
            self._events[name].set()


# ============================================================
# 全局工具函数
# ============================================================

_global_startup_profiler: Optional[StartupProfiler] = None


def get_startup_profiler() -> StartupProfiler:
    """获取全局启动分析器"""
    global _global_startup_profiler
    if _global_startup_profiler is None:
        _global_startup_profiler = StartupProfiler()
    return _global_startup_profiler


def optimize_imports():
    """优化常用模块导入

    在应用启动后调用，触发 Python 字节码缓存。
    """
    import os
    import sys

    # 触发 __pycache__ 目录创建
    if hasattr(sys, "dont_write_bytecode"):
        return

    # 预编译常用模块
    try:
        import compileall

        core_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".."
        )
        compileall.compile_dir(
            core_dir,
            maxlevels=2,
            quiet=1,
            workers=4,
        )
        logger.debug("字节码预编译完成")
    except Exception as e:
        logger.debug("字节码预编译跳过: %s", e)