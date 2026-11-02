# -*- coding: utf-8 -*-
"""
Stream Optimizer — SSE 流式输出优化器
========================================
优化 AI 引擎的流式输出，减少 UI 刷新频率，提升感知性能。

核心功能：
1. StreamOptimizer — 时间/大小/超时三维度节流刷新
2. ChunkMerger — SSE 数据块去重与合并
3. StreamBuffer — 完整响应拼接组装

使用示例：
    optimizer = StreamOptimizer(min_interval_ms=50, max_buffer_chars=200)
    for chunk in engine.stream_generate(prompt):
        text = optimizer.feed(chunk)
        if text is not None:
            ui.update(text)
    final = optimizer.flush()
    if final:
        ui.update(final)
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("lemon.stream_optimizer")


# ==================== StreamOptimizer ====================

class StreamOptimizer:
    """
    流式输出节流优化器

    通过时间间隔、缓冲区大小、超时三个维度控制 UI 刷新频率，
    避免每个 token 都触发一次 UI 重绘。
    """

    def __init__(
        self,
        min_interval_ms: float = 50,
        max_buffer_chars: int = 200,
        flush_timeout_ms: float = 200,
    ):
        """
        Args:
            min_interval_ms: 两次 UI 更新之间的最小间隔（毫秒），默认 50ms ≈ 20fps
            max_buffer_chars: 缓冲区最大字符数，超过后强制刷新
            flush_timeout_ms: 最大等待时间（毫秒），超时后即使缓冲区很小也刷新
        """
        self._min_interval_ms = max(0, min_interval_ms)
        self._max_buffer_chars = max(1, max_buffer_chars)
        self._flush_timeout_ms = max(0, flush_timeout_ms)

        self._buffer: List[str] = []
        self._buffer_len: int = 0
        self._last_flush_time: Optional[float] = None
        self._first_chunk_time: Optional[float] = None

        # 统计信息
        self._total_chunks_received: int = 0
        self._total_flushes: int = 0
        self._total_chars_processed: int = 0
        self._flush_intervals: List[float] = []

    # ---- 公共方法 ----

    def feed(self, chunk: str) -> Optional[str]:
        """
        喂入一个新的文本块。

        Args:
            chunk: 新的文本片段

        Returns:
            当满足刷新条件时返回累积的完整文本，否则返回 None
        """
        if not chunk:
            return None

        self._total_chunks_received += 1
        self._total_chars_processed += len(chunk)

        now = time.monotonic()

        # 记录首个 chunk 到达时间（用于超时判断）
        if self._first_chunk_time is None:
            self._first_chunk_time = now

        self._buffer.append(chunk)
        self._buffer_len += len(chunk)

        # 条件 1：大小超限 → 强制刷新
        if self._buffer_len >= self._max_buffer_chars:
            return self._do_flush(now)

        # 条件 2：时间间隔未到 → 继续缓冲
        if self._last_flush_time is not None:
            elapsed = (now - self._last_flush_time) * 1000.0
            if elapsed < self._min_interval_ms:
                return None

        # 条件 3：超时 → 刷新
        if self._first_chunk_time is not None:
            timeout_elapsed = (now - self._first_chunk_time) * 1000.0
            if timeout_elapsed >= self._flush_timeout_ms:
                return self._do_flush(now)

        # 首次 chunk：不刷新，等待更多内容
        if self._last_flush_time is None:
            return None

        # 满足最小间隔 → 刷新
        return self._do_flush(now)

    def flush(self) -> str:
        """
        强制刷新缓冲区中所有剩余内容，并重置内部状态。

        Returns:
            累积的文本，如果缓冲区为空则返回空字符串
        """
        if not self._buffer:
            return ""

        now = time.monotonic()
        return self._do_flush(now)

    def reset(self) -> None:
        """清空缓冲区并重置计时器，不返回内容。"""
        self._buffer.clear()
        self._buffer_len = 0
        self._last_flush_time = None
        self._first_chunk_time = None

    def get_stats(self) -> Dict[str, Any]:
        """
        获取优化器统计信息。

        Returns:
            包含以下字段的字典：
            - total_chunks_received: 接收到的总块数
            - total_flushes: 总刷新次数
            - total_chars_processed: 处理的总字符数
            - avg_chunk_size: 平均每块大小
            - avg_flush_interval_ms: 平均刷新间隔（毫秒）
            - compression_ratio: 压缩比（chunks / flushes）
        """
        avg_chunk_size = 0.0
        if self._total_chunks_received > 0:
            avg_chunk_size = self._total_chars_processed / self._total_chunks_received

        avg_flush_interval = 0.0
        if len(self._flush_intervals) > 0:
            avg_flush_interval = sum(self._flush_intervals) / len(self._flush_intervals)

        compression_ratio = 0.0
        if self._total_flushes > 0:
            compression_ratio = self._total_chunks_received / self._total_flushes

        return {
            "total_chunks_received": self._total_chunks_received,
            "total_flushes": self._total_flushes,
            "total_chars_processed": self._total_chars_processed,
            "avg_chunk_size": round(avg_chunk_size, 2),
            "avg_flush_interval_ms": round(avg_flush_interval, 2),
            "compression_ratio": round(compression_ratio, 2),
        }

    def is_active(self) -> bool:
        """返回 True 表示缓冲区中有待刷新的内容。"""
        return self._buffer_len > 0

    # ---- 内部方法 ----

    def _do_flush(self, now: float) -> str:
        """执行实际刷新，更新统计信息。"""
        if self._last_flush_time is not None:
            interval = (now - self._last_flush_time) * 1000.0
            self._flush_intervals.append(interval)

        self._last_flush_time = now
        self._first_chunk_time = None
        self._total_flushes += 1

        result = "".join(self._buffer)
        self._buffer.clear()
        self._buffer_len = 0
        return result


# ==================== ChunkMerger ====================

class ChunkMerger:
    """
    SSE 数据块去重与合并器

    处理来自 SSE 流的原始数据块，合并相邻小块、去除重复、
    合并纯标点/空白块到相邻块中。
    """

    def __init__(self, max_merge_size: int = 500):
        """
        Args:
            max_merge_size: 合并后单个块的最大字符数
        """
        self._max_merge_size = max(1, max_merge_size)

    # ---- 公共方法 ----

    def merge(self, chunks: List[str]) -> List[str]:
        """
        合并相邻的小块，去除重复，优化空白/标点。

        Args:
            chunks: 原始文本块列表

        Returns:
            合并后的文本块列表
        """
        if not chunks:
            return []

        # 过滤空字符串
        chunks = [c for c in chunks if c]

        if not chunks:
            return []

        result: List[str] = []
        current = chunks[0]

        for i in range(1, len(chunks)):
            nxt = chunks[i]

            # 去除连续重复块
            if nxt == current:
                continue

            # 如果当前块是纯空白/标点，合并到前一个块
            if self._is_insignificant(current):
                if result:
                    result[-1] = result[-1] + current
                current = nxt
                continue

            # 如果下一个块是纯空白/标点，合并到当前块
            if self._is_insignificant(nxt):
                current = current + nxt
                continue

            # 尝试合并相邻小块
            combined = current + nxt
            if len(combined) <= self._max_merge_size:
                current = combined
            else:
                result.append(current)
                current = nxt

        # 添加最后一个块
        if current:
            result.append(current)

        return result

    def process_sse_line(self, line: str) -> Optional[str]:
        """
        解析 SSE 格式的文本行，提取内容。

        支持的格式：
        - "data: {...}"  JSON 格式
        - "data: text"  纯文本格式
        - 以 "data: " 开头的行

        Args:
            line: SSE 格式的原始文本行

        Returns:
            提取的文本内容，解析失败返回 None
        """
        if not line:
            return None

        line = line.strip()

        # 跳过非数据行（注释、事件类型等）
        if not line.startswith("data:"):
            return None

        payload = line[5:].lstrip()

        # 空数据
        if not payload:
            return None

        # 尝试 JSON 解析
        if payload.startswith("{"):
            try:
                data = json.loads(payload)
                # 常见 SSE 字段名
                for key in ("content", "text", "delta", "message", "choices"):
                    if key in data:
                        val = data[key]
                        if isinstance(val, str):
                            return val
                        if isinstance(val, dict) and "content" in val:
                            return str(val["content"])
                        if isinstance(val, list) and val:
                            first = val[0]
                            if isinstance(first, dict):
                                for sub in ("delta", "message", "text"):
                                    if sub in first and isinstance(first[sub], dict):
                                        content = first[sub].get("content", "")
                                        if content:
                                            return str(content)
                                    if sub in first and isinstance(first[sub], str):
                                        return str(first[sub])
                            return str(first)
                # 没找到已知字段，返回整个 JSON 字符串
                return payload
            except json.JSONDecodeError:
                logger.debug("SSE JSON parse failed: %s", payload[:100])
                # 解析失败，返回原始 payload
                return payload

        # 纯文本 payload
        return payload

    # ---- 内部方法 ----

    @staticmethod
    def _is_insignificant(text: str) -> bool:
        """判断文本是否纯空白或纯标点。"""
        if not text:
            return True
        return all(c.isspace() or c in ".,;:!?，。；：！？…—\"'`()[]{}（）【】" for c in text)


# ==================== StreamBuffer ====================

class StreamBuffer:
    """
    完整响应流式拼接器

    用于在流式输出过程中逐步累积完整响应文本。
    """

    def __init__(self):
        self._parts: List[str] = []
        self._buffer: str = ""

    # ---- 公共方法 ----

    def add(self, chunk: str) -> str:
        """
        添加一个新的文本块到缓冲区。

        Args:
            chunk: 文本片段

        Returns:
            当前累积的完整文本
        """
        if not chunk:
            return self._buffer

        self._parts.append(chunk)
        self._buffer += chunk
        return self._buffer

    def get_full(self) -> str:
        """
        获取当前累积的完整文本。

        Returns:
            所有已添加文本拼接后的完整字符串
        """
        return self._buffer

    def reset(self) -> None:
        """清空缓冲区，重置为初始状态。"""
        self._parts.clear()
        self._buffer = ""