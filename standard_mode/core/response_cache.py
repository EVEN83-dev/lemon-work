# -*- coding: utf-8 -*-
"""
Response Cache — 引擎响应 LRU 缓存层
=====================================
为所有 AI 引擎（MiMoCode / Ollama / DeepSeek 等）提供统一的响应缓存，
避免重复的 prompt 多次调用引擎，节省算力和时间。

核心功能：
1. LRU 淘汰策略：超过最大容量时淘汰最久未使用的条目
2. TTL 过期机制：条目超过指定时间后自动失效
3. 线程安全：所有操作使用 threading.Lock 保护
4. 缓存键：基于 (engine_name, model_name, prompt_hash) 三元组
5. Prompt 标准化：去空白、小写、哈希，避免相似 prompt 重复缓存
6. 全局单例 + 统计信息

使用示例：
    cache = get_response_cache()
    response = cache.get_or_compute(
        engine="ollama", model="qwen2.5:1.5b", prompt="你好",
        compute_fn=lambda: engine.generate("你好"),
    )
"""

import hashlib
import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("lemon.response_cache")


# ==================== 缓存统计 ====================

@dataclass
class CacheStats:
    """缓存统计信息"""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0
    max_size: int = 0

    @property
    def hit_rate(self) -> float:
        """命中率（0.0 ~ 1.0）"""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "size": self.size,
            "max_size": self.max_size,
            "hit_rate": round(self.hit_rate, 4),
        }


# ==================== 缓存条目 ====================

@dataclass
class _CacheEntry:
    """内部缓存条目"""

    response: Any
    created_at: float   # time.monotonic() 时间戳
    ttl: float          # 秒
    engine: str = ""    # 引擎名称，供 invalidate 匹配
    model: str = ""     # 模型名称，供 invalidate 匹配
    key_display: str = ""  # 用于日志的可读键

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl


# ==================== 响应缓存 ====================


class ResponseCache:
    """
    引擎响应 LRU 缓存

    Parameters
    ----------
    max_size : int
        最大缓存条目数（默认 100）
    default_ttl : float
        默认过期时间，秒（默认 300）
    """

    def __init__(self, max_size: int = 100, default_ttl: float = 300.0):
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        if default_ttl <= 0:
            raise ValueError("default_ttl must be > 0")

        self._max_size = max_size
        self._default_ttl = default_ttl
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

        # 统计
        self._hits = 0
        self._misses = 0
        self._evictions = 0

        logger.info(
            "ResponseCache 初始化完成 (max_size=%d, ttl=%.0fs)",
            max_size, default_ttl,
        )

    # ==================== 键生成 ====================

    def make_key(self, engine: str, model: str, prompt: str) -> str:
        """
        生成缓存键

        基于 (engine, model, normalized_prompt) 三元组计算 SHA256 哈希，
        确保相同引擎+模型+相似 prompt 命中同一缓存条目。

        Parameters
        ----------
        engine : str
            引擎名称（如 "ollama", "deepseek", "mimocode"）
        model : str
            模型名称（如 "qwen2.5:1.5b", "deepseek-chat"）
        prompt : str
            用户输入的原始 prompt

        Returns
        -------
        str
            SHA256 十六进制哈希字符串
        """
        normalized = self._normalize_prompt(prompt)
        raw = f"{engine}::{model}::{normalized}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_prompt(prompt: str) -> str:
        """标准化 prompt：去首尾空白 + 小写"""
        if not prompt:
            return ""
        return prompt.strip().lower()

    # ==================== 缓存操作 ====================

    def get(self, key: str) -> Optional[Any]:
        """
        从缓存中获取响应

        如果条目已过期，自动删除并返回 None。

        Parameters
        ----------
        key : str
            由 make_key() 生成的缓存键

        Returns
        -------
        Any or None
            缓存的响应，或 None（未命中/已过期）
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None

            if entry.is_expired:
                del self._store[key]
                self._misses += 1
                logger.debug("缓存过期: %s", entry.key_display)
                return None

            # LRU: 移到末尾（最近使用）
            self._store.move_to_end(key)
            self._hits += 1
            logger.debug("缓存命中: %s", entry.key_display)
            return entry.response

    def put(
        self, key: str, response: Any,
        engine: str = "", model: str = "",
        ttl: Optional[float] = None,
    ) -> None:
        """
        将响应写入缓存

        Parameters
        ----------
        key : str
            由 make_key() 生成的缓存键
        response : Any
            需要缓存的响应对象
        engine : str
            引擎名称，供 invalidate 模式匹配
        model : str
            模型名称，供 invalidate 模式匹配
        ttl : float or None
            过期时间（秒），None 则使用默认 TTL
        """
        if response is None:
            return

        effective_ttl = ttl if ttl is not None else self._default_ttl
        if effective_ttl <= 0:
            return

        with self._lock:
            # 如果 key 已存在，先移除旧条目（避免 eviction 计数错误）
            if key in self._store:
                del self._store[key]

            # 淘汰最久未使用的条目
            while len(self._store) >= self._max_size:
                evicted_key, evicted_entry = self._store.popitem(last=False)
                self._evictions += 1
                logger.debug(
                    "LRU 淘汰: %s (created %.0fs ago)",
                    evicted_entry.key_display,
                    time.monotonic() - evicted_entry.created_at,
                )

            entry = _CacheEntry(
                response=response,
                created_at=time.monotonic(),
                ttl=effective_ttl,
                engine=engine,
                model=model,
                key_display=self._make_key_display(key, response),
            )
            self._store[key] = entry

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        engine: str = "",
        model: str = "",
        force_refresh: bool = False,
        ttl: Optional[float] = None,
    ) -> Any:
        """
        从缓存获取，未命中则计算并存入缓存

        Parameters
        ----------
        key : str
            缓存键
        compute_fn : callable
            当缓存未命中时调用的计算函数，无参数
        engine : str
            引擎名称，供 invalidate 模式匹配
        model : str
            模型名称，供 invalidate 模式匹配
        force_refresh : bool
            为 True 时强制跳过缓存，重新计算
        ttl : float or None
            自定义 TTL（秒），None 则使用默认值

        Returns
        -------
        Any
            缓存的响应或 compute_fn 的计算结果
        """
        if force_refresh:
            self._misses += 1
            logger.debug("强制刷新，跳过缓存")
        else:
            cached = self.get(key)
            if cached is not None:
                return cached

        try:
            response = compute_fn()
        except Exception:
            logger.exception("compute_fn 执行失败")
            raise

        self.put(key, response, engine=engine, model=model, ttl=ttl)
        return response

    def invalidate(self, pattern: str) -> int:
        """
        按模式匹配删除缓存条目

        检查每个条目的 engine、model 和 key_display 字段，
        如果任一字段包含 pattern 子串则删除。
        支持正则表达式（以 / 开头和结尾的 pattern 视为正则）。

        Parameters
        ----------
        pattern : str
            匹配模式（普通子串或 /regex/ 格式的正则表达式）

        Returns
        -------
        int
            删除的条目数
        """
        is_regex = len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/")
        if is_regex:
            try:
                compiled = re.compile(pattern[1:-1], re.IGNORECASE)
            except re.error as e:
                logger.warning("无效的正则表达式: %s (%s)", pattern, e)
                return 0
        else:
            compiled = None
            pattern_lower = pattern.lower()

        def _matches(entry: _CacheEntry) -> bool:
            if compiled is not None:
                return bool(
                    compiled.search(entry.engine)
                    or compiled.search(entry.model)
                    or compiled.search(entry.key_display)
                )
            else:
                return (
                    pattern_lower in entry.engine.lower()
                    or pattern_lower in entry.model.lower()
                    or pattern_lower in entry.key_display.lower()
                )

        with self._lock:
            keys_to_remove = [k for k, e in self._store.items() if _matches(e)]
            for k in keys_to_remove:
                del self._store[k]

        count = len(keys_to_remove)
        if count > 0:
            logger.info("已删除 %d 条缓存 (pattern=%s)", count, pattern)
        return count

    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            count = len(self._store)
            self._store.clear()
        logger.info("缓存已清空 (%d 条)", count)

    def get_stats(self) -> CacheStats:
        """获取缓存统计信息"""
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                size=len(self._store),
                max_size=self._max_size,
            )

    def size(self) -> int:
        """当前缓存条目数"""
        with self._lock:
            return len(self._store)

    def reset_stats(self) -> None:
        """重置统计计数器（不清除缓存）"""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    # ==================== 内部方法 ====================

    def _make_key_display(self, key: str, response: Any) -> str:
        """生成可读的键展示字符串（用于日志）"""
        # 截取 key 前 16 位 + 响应类型
        short_key = key[:16]
        resp_type = type(response).__name__
        resp_preview = ""
        if isinstance(response, str):
            resp_preview = response[:80].replace("\n", " ")
        return f"[{short_key}...|{resp_type}] {resp_preview}"


# ==================== 全局单例 ====================

_global_response_cache: Optional[ResponseCache] = None
_cache_lock = threading.Lock()


def get_response_cache(max_size: int = 100, default_ttl: float = 300.0) -> ResponseCache:
    """
    获取全局响应缓存单例

    首次调用时创建，后续调用返回同一实例。
    参数仅在首次创建时生效。

    Parameters
    ----------
    max_size : int
        最大缓存条目数
    default_ttl : float
        默认过期时间（秒）

    Returns
    -------
    ResponseCache
    """
    global _global_response_cache
    if _global_response_cache is None:
        with _cache_lock:
            if _global_response_cache is None:
                _global_response_cache = ResponseCache(
                    max_size=max_size,
                    default_ttl=default_ttl,
                )
    return _global_response_cache


def reset_response_cache() -> None:
    """重置全局缓存单例（主要用于测试）"""
    global _global_response_cache
    with _cache_lock:
        if _global_response_cache is not None:
            _global_response_cache.clear()
        _global_response_cache = None