# -*- coding: utf-8 -*-
"""
内存优化模块 — MemoryOptimizer
===============================
提供对象池、弱引用缓存、循环引用检测等内存优化工具。

功能：
1. ObjectPool — 通用对象池，减少频繁创建/销毁开销
2. WeakRefCache — 弱引用缓存，自动释放未使用对象
3. CircularRefDetector — 循环引用检测与清理
4. MemoryMonitor — 内存使用监控与告警
"""

import gc
import logging
import threading
import time
import weakref
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Type, TypeVar

logger = logging.getLogger("lemon.memory_optimizer")

T = TypeVar("T")


# ============================================================
# ObjectPool
# ============================================================

class ObjectPool:
    """通用对象池

    预分配一组对象，减少频繁创建/销毁的开销。
    特别适合短生命周期、高频创建的对象（如消息缓冲区、临时字典）。

    使用方式：
        pool = ObjectPool(lambda: {"data": []}, max_size=100)
        obj = pool.acquire()
        # ... 使用 obj ...
        pool.release(obj)
    """

    def __init__(
        self,
        factory: Callable[[], T],
        max_size: int = 100,
        pre_allocate: int = 0,
        name: str = "default",
    ):
        """
        Args:
            factory: 对象工厂函数，无参数，返回新对象
            max_size: 池最大容量
            pre_allocate: 预分配对象数量
            name: 池名称（用于日志和统计）
        """
        self._factory = factory
        self._max_size = max(1, max_size)
        self._name = name
        self._pool: deque = deque()
        self._lock = threading.Lock()
        self._stats = {
            "created": 0,
            "reused": 0,
            "released": 0,
            "pool_size": 0,
        }

        # 预分配
        for _ in range(min(pre_allocate, max_size)):
            self._pool.append(factory())
            self._stats["created"] += 1
            self._stats["pool_size"] += 1

        logger.debug(
            "ObjectPool[%s] 初始化 (max=%d, pre=%d)",
            name, max_size, pre_allocate,
        )

    def acquire(self) -> T:
        """从池中获取一个对象"""
        with self._lock:
            if self._pool:
                self._stats["reused"] += 1
                self._stats["pool_size"] -= 1
                return self._pool.pop()

            self._stats["created"] += 1
            return self._factory()

    def release(self, obj: T) -> None:
        """将对象归还到池中"""
        if obj is None:
            return
        with self._lock:
            if len(self._pool) < self._max_size:
                self._pool.append(obj)
                self._stats["pool_size"] += 1
                self._stats["released"] += 1

    def clear(self) -> None:
        """清空池中所有对象"""
        with self._lock:
            count = len(self._pool)
            self._pool.clear()
            self._stats["pool_size"] = 0
            logger.debug("ObjectPool[%s] 清空 %d 个对象", self._name, count)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            stats = dict(self._stats)
            stats["reuse_rate"] = (
                round(stats["reused"] / max(stats["reused"] + stats["created"], 1), 4)
            )
            return stats

    def size(self) -> int:
        """当前池中对象数"""
        with self._lock:
            return len(self._pool)


# ============================================================
# WeakRefCache
# ============================================================

class WeakRefCache:
    """弱引用缓存

    使用 weakref 存储缓存值，当对象不再被其他引用持有时自动释放。
    适合缓存大对象，避免内存泄漏。

    使用方式：
        cache = WeakRefCache()
        cache.set("key", large_object)
        obj = cache.get("key")  # 返回对象或 None（已释放）
    """

    def __init__(self, max_size: int = 1000):
        self._max_size = max(1, max_size)
        self._cache: Dict[str, weakref.ref] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def set(self, key: str, value: Any) -> None:
        """设置缓存值"""
        with self._lock:
            # 淘汰最旧的条目
            if len(self._cache) >= self._max_size:
                dead_keys = [k for k, v in self._cache.items() if v() is None]
                for k in dead_keys[:max(1, len(dead_keys) // 4)]:
                    del self._cache[k]
                if len(self._cache) >= self._max_size:
                    # 如果仍然满了，删除第一个
                    first_key = next(iter(self._cache))
                    del self._cache[first_key]

            self._cache[key] = weakref.ref(value)

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            ref = self._cache.get(key)
            if ref is None:
                self._misses += 1
                return None

            value = ref()
            if value is None:
                del self._cache[key]
                self._misses += 1
                return None

            self._hits += 1
            return value

    def remove(self, key: str) -> None:
        """移除缓存条目"""
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """当前缓存条目数"""
        with self._lock:
            return len(self._cache)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(total, 1), 4),
                "size": len(self._cache),
                "max_size": self._max_size,
            }


# ============================================================
# CircularRefDetector
# ============================================================

class CircularRefDetector:
    """循环引用检测器

    检测 Python 对象之间的循环引用，帮助发现内存泄漏。

    使用方式：
        detector = CircularRefDetector()
        cycles = detector.detect(obj)
        if cycles:
            detector.report(cycles)
    """

    def __init__(self):
        self._logger = logger

    def detect(self, obj: Any, max_depth: int = 20) -> List[List[str]]:
        """检测对象图中的循环引用

        Args:
            obj: 要检测的根对象
            max_depth: 最大检测深度

        Returns:
            循环引用路径列表，每条路径是属性名列表
        """
        visited: Set[int] = set()
        path: List[str] = []
        cycles: List[List[str]] = []

        def _dfs(current: Any, depth: int):
            if depth > max_depth:
                return

            obj_id = id(current)
            if obj_id in visited:
                # 找到环
                cycle_start = path.index(str(obj_id)) if str(obj_id) in path else -1
                if cycle_start >= 0:
                    cycles.append(list(path[cycle_start:]))
                return

            visited.add(obj_id)
            path.append(str(obj_id))

            # 遍历子对象
            if isinstance(current, dict):
                for k, v in list(current.items())[:20]:
                    path.append(f"dict[{k}]")
                    _dfs(v, depth + 1)
                    path.pop()
            elif isinstance(current, (list, tuple, set)):
                for i, v in enumerate(list(current)[:20]):
                    path.append(f"[{i}]")
                    _dfs(v, depth + 1)
                    path.pop()
            elif hasattr(current, "__dict__"):
                for attr_name in list(current.__dict__.keys())[:20]:
                    try:
                        attr_val = getattr(current, attr_name)
                    except Exception:
                        continue
                    if isinstance(attr_val, (str, int, float, bool, type(None))):
                        continue
                    path.append(attr_name)
                    _dfs(attr_val, depth + 1)
                    path.pop()

            visited.remove(obj_id)
            path.pop()

        _dfs(obj, 0)
        return cycles

    def report(self, cycles: List[List[str]]) -> str:
        """生成循环引用报告"""
        if not cycles:
            return "未检测到循环引用"

        lines = [f"检测到 {len(cycles)} 个循环引用:"]
        for i, cycle in enumerate(cycles[:10], 1):
            path_str = " -> ".join(cycle[:15])
            if len(cycle) > 15:
                path_str += " -> ..."
            lines.append(f"  #{i}: {path_str}")

        return "\n".join(lines)


# ============================================================
# MemoryMonitor
# ============================================================

@dataclass
class MemorySnapshot:
    """内存快照"""
    timestamp: float = 0.0
    rss_mb: float = 0.0
    vms_mb: float = 0.0
    gc_count: int = 0
    gc_objects: int = 0
    thread_count: int = 0


class MemoryMonitor:
    """内存使用监控器

    定期采集内存快照，检测异常增长，触发告警。

    使用方式：
        monitor = MemoryMonitor(interval_sec=30, warning_threshold_mb=500)
        monitor.start()
        # ... 应用运行 ...
        stats = monitor.get_stats()
        monitor.stop()
    """

    def __init__(
        self,
        interval_sec: float = 30.0,
        warning_threshold_mb: float = 500.0,
        critical_threshold_mb: float = 1000.0,
    ):
        self._interval = max(1.0, interval_sec)
        self._warning_threshold = warning_threshold_mb
        self._critical_threshold = critical_threshold_mb
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._snapshots: List[MemorySnapshot] = []
        self._max_snapshots = 100
        self._callbacks: Dict[str, List[Callable]] = {
            "warning": [],
            "critical": [],
            "snapshot": [],
        }
        self._logger = logger

    def start(self) -> None:
        """启动监控"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="MemoryMonitor",
            daemon=True,
        )
        self._thread.start()
        self._logger.info(
            "MemoryMonitor 启动 (interval=%.0fs, warning=%.0fMB, critical=%.0fMB)",
            self._interval, self._warning_threshold, self._critical_threshold,
        )

    def stop(self) -> None:
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._logger.info("MemoryMonitor 已停止")

    def snapshot(self) -> MemorySnapshot:
        """获取当前内存快照"""
        import os
        import threading

        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem = process.memory_info()
            rss_mb = mem.rss / (1024 * 1024)
            vms_mb = mem.vms / (1024 * 1024)
        except ImportError:
            rss_mb = 0.0
            vms_mb = 0.0

        gc_count = gc.get_count()
        gc_objects = len(gc.get_objects())
        thread_count = threading.active_count()

        return MemorySnapshot(
            timestamp=time.monotonic(),
            rss_mb=rss_mb,
            vms_mb=vms_mb,
            gc_count=sum(gc_count),
            gc_objects=gc_objects,
            thread_count=thread_count,
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取监控统计"""
        with self._lock:
            if not self._snapshots:
                return {"snapshots": 0, "current": None}

            current = self._snapshots[-1]
            stats = {
                "snapshots": len(self._snapshots),
                "current": {
                    "rss_mb": current.rss_mb,
                    "vms_mb": current.vms_mb,
                    "gc_objects": current.gc_objects,
                    "thread_count": current.thread_count,
                },
            }

            if len(self._snapshots) >= 2:
                first = self._snapshots[0]
                growth = current.rss_mb - first.rss_mb
                stats["growth_mb"] = round(growth, 2)
                stats["growth_rate_mb_per_hour"] = round(
                    growth / max((current.timestamp - first.timestamp) / 3600, 0.01), 2
                )

            return stats

    def on(self, event: str, callback: Callable) -> None:
        """注册事件回调"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    # ----------------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------------

    def _monitor_loop(self) -> None:
        """监控循环"""
        while self._running:
            try:
                snap = self.snapshot()
                with self._lock:
                    self._snapshots.append(snap)
                    if len(self._snapshots) > self._max_snapshots:
                        self._snapshots = self._snapshots[-self._max_snapshots:]

                # 触发回调
                for cb in self._callbacks["snapshot"]:
                    try:
                        cb(snap)
                    except Exception:
                        pass

                # 检查阈值
                if snap.rss_mb >= self._critical_threshold:
                    self._logger.critical(
                        "内存使用达到临界值: %.1fMB (阈值: %.0fMB)",
                        snap.rss_mb, self._critical_threshold,
                    )
                    for cb in self._callbacks["critical"]:
                        try:
                            cb(snap)
                        except Exception:
                            pass
                elif snap.rss_mb >= self._warning_threshold:
                    self._logger.warning(
                        "内存使用超过警告阈值: %.1fMB (阈值: %.0fMB)",
                        snap.rss_mb, self._warning_threshold,
                    )
                    for cb in self._callbacks["warning"]:
                        try:
                            cb(snap)
                        except Exception:
                            pass

            except Exception as e:
                self._logger.debug("MemoryMonitor 采集异常: %s", e)

            time.sleep(self._interval)


# ============================================================
# 全局工具函数
# ============================================================

def force_gc_collect() -> int:
    """强制垃圾回收并返回回收的对象数"""
    gc.collect(0)
    gc.collect(1)
    return gc.collect(2)


def cleanup_circular_refs(obj: Any) -> int:
    """清理对象的循环引用

    递归查找并清理 __self__ 等常见循环引用模式。
    返回清理的引用数。
    """
    cleaned = 0

    def _cleanup(o, visited: Set[int]):
        nonlocal cleaned
        obj_id = id(o)
        if obj_id in visited:
            return
        visited.add(obj_id)

        if isinstance(o, dict):
            for key in list(o.keys()):
                if key in ("self", "__self__", "_self", "parent") and o[key] is o:
                    del o[key]
                    cleaned += 1

        if isinstance(o, (list, tuple)):
            for item in o:
                _cleanup(item, visited)

        if hasattr(o, "__dict__"):
            for attr in list(o.__dict__.keys()):
                if attr in ("self", "__self__", "_self"):
                    val = getattr(o, attr, None)
                    if val is o:
                        try:
                            delattr(o, attr)
                            cleaned += 1
                        except Exception:
                            pass
                try:
                    val = getattr(o, attr, None)
                    if isinstance(val, (dict, list, tuple)) or hasattr(val, "__dict__"):
                        _cleanup(val, visited)
                except Exception:
                    pass

    _cleanup(obj, set())
    gc.collect()
    return cleaned


# ============================================================
# 全局单例
# ============================================================

_global_memory_monitor: Optional[MemoryMonitor] = None
_monitor_lock = threading.Lock()


def get_memory_monitor(
    interval_sec: float = 30.0,
    warning_threshold_mb: float = 500.0,
) -> MemoryMonitor:
    """获取全局内存监控器单例"""
    global _global_memory_monitor
    if _global_memory_monitor is None:
        with _monitor_lock:
            if _global_memory_monitor is None:
                _global_memory_monitor = MemoryMonitor(
                    interval_sec=interval_sec,
                    warning_threshold_mb=warning_threshold_mb,
                )
    return _global_memory_monitor