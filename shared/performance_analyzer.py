# -*- coding: utf-8 -*-
"""
Performance Analyzer — 性能分析器
==================================
提供响应时间统计、资源使用监控、性能报告生成功能。

功能：
1. 请求响应时间统计（平均/最小/最大/百分位）
2. 吞吐量统计
3. 资源使用监控（CPU/内存）
4. 性能报告生成
5. 性能趋势分析
6. 慢请求追踪

使用方式：
    analyzer = PerformanceAnalyzer()
    analyzer.record_request(0.5, engine="ollama")
    analyzer.record_request(1.2, engine="mimocode")
    report = analyzer.get_report()
    analyzer.reset()
"""

import time
import threading
import statistics
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from collections import defaultdict


class PerformanceAnalyzer:
    """性能分析器

    记录和分析 AI 请求的性能指标，支持多引擎对比。
    """

    def __init__(self, max_history: int = 1000):
        """
        Args:
            max_history: 最大历史记录数
        """
        self._lock = threading.Lock()
        self._max_history = max_history

        # 全局指标
        self._request_count = 0
        self._total_time = 0.0
        self._response_times: List[float] = []
        self._start_time = time.time()

        # 按引擎分组的指标
        self._engine_metrics: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "total_time": 0.0, "response_times": []}
        )

        # 按模型分组的指标
        self._model_metrics: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "total_time": 0.0, "response_times": []}
        )

        # 吞吐量
        self._throughput_samples: List[Tuple[float, int]] = []  # (timestamp, count)

        # 错误计数
        self._error_count = 0
        self._errors_by_engine: Dict[str, int] = defaultdict(int)

        # 慢请求追踪（超过阈值的请求）
        self._slow_requests: List[Dict[str, Any]] = []
        self._slow_threshold = 5.0  # 秒

        # 资源使用
        self._resource_samples: List[Dict[str, Any]] = []

    # ============================================================
    # 记录
    # ============================================================

    def record_request(self, response_time: float, engine: str = "unknown",
                       model: str = "unknown", tokens: int = 0,
                       success: bool = True):
        """记录一次请求

        Args:
            response_time: 响应时间（秒）
            engine: 使用的引擎
            model: 使用的模型
            tokens: Token 数量
            success: 是否成功
        """
        with self._lock:
            self._request_count += 1
            self._total_time += response_time
            self._response_times.append(response_time)

            # 引擎指标
            em = self._engine_metrics[engine]
            em["count"] += 1
            em["total_time"] += response_time
            em["response_times"].append(response_time)

            # 模型指标
            mm = self._model_metrics[model]
            mm["count"] += 1
            mm["total_time"] += response_time
            mm["response_times"].append(response_time)

            # 错误计数
            if not success:
                self._error_count += 1
                self._errors_by_engine[engine] += 1

            # 慢请求追踪
            if response_time > self._slow_threshold:
                self._slow_requests.append({
                    "timestamp": datetime.now().isoformat(),
                    "response_time": response_time,
                    "engine": engine,
                    "model": model,
                    "tokens": tokens,
                })
                if len(self._slow_requests) > 100:
                    self._slow_requests = self._slow_requests[-100:]

            # 限制历史记录
            if len(self._response_times) > self._max_history:
                self._response_times = self._response_times[-self._max_history:]

    def record_error(self, engine: str = "unknown", error_type: str = ""):
        """记录一次错误

        Args:
            engine: 引擎名称
            error_type: 错误类型
        """
        with self._lock:
            self._error_count += 1
            self._errors_by_engine[engine] += 1

    def record_throughput(self):
        """记录当前吞吐量采样"""
        with self._lock:
            self._throughput_samples.append((time.time(), self._request_count))
            if len(self._throughput_samples) > 100:
                self._throughput_samples = self._throughput_samples[-100:]

    def record_resource_usage(self, cpu_percent: float = 0.0,
                              memory_mb: float = 0.0):
        """记录资源使用情况"""
        with self._lock:
            self._resource_samples.append({
                "timestamp": datetime.now().isoformat(),
                "cpu_percent": cpu_percent,
                "memory_mb": memory_mb,
            })
            if len(self._resource_samples) > 100:
                self._resource_samples = self._resource_samples[-100:]

    # ============================================================
    # 报告
    # ============================================================

    def get_report(self) -> Dict[str, Any]:
        """获取性能报告

        Returns:
            完整的性能报告字典
        """
        with self._lock:
            elapsed = time.time() - self._start_time
            avg_time = self._total_time / self._request_count if self._request_count > 0 else 0

            report = {
                "timestamp": datetime.now().isoformat(),
                "uptime": elapsed,
                "overall": {
                    "request_count": self._request_count,
                    "total_time": round(self._total_time, 3),
                    "avg_response_time": round(avg_time, 3),
                    "min_response_time": round(min(self._response_times), 3) if self._response_times else 0,
                    "max_response_time": round(max(self._response_times), 3) if self._response_times else 0,
                    "median_response_time": round(statistics.median(self._response_times), 3) if self._response_times else 0,
                    "p95_response_time": self._percentile(95),
                    "p99_response_time": self._percentile(99),
                    "throughput_per_min": self._request_count / (elapsed / 60) if elapsed > 0 else 0,
                    "error_rate": self._error_count / self._request_count if self._request_count > 0 else 0,
                },
                "by_engine": {},
                "by_model": {},
                "errors": {
                    "total": self._error_count,
                    "by_engine": dict(self._errors_by_engine),
                },
                "slow_requests": self._slow_requests[-10:],
                "resources": self._resource_samples[-5:] if self._resource_samples else [],
            }

            # 引擎指标
            for engine, metrics in self._engine_metrics.items():
                count = metrics["count"]
                report["by_engine"][engine] = {
                    "count": count,
                    "total_time": round(metrics["total_time"], 3),
                    "avg_time": round(metrics["total_time"] / count, 3) if count > 0 else 0,
                    "min_time": round(min(metrics["response_times"]), 3) if metrics["response_times"] else 0,
                    "max_time": round(max(metrics["response_times"]), 3) if metrics["response_times"] else 0,
                    "error_count": self._errors_by_engine.get(engine, 0),
                }

            # 模型指标
            for model, metrics in self._model_metrics.items():
                count = metrics["count"]
                report["by_model"][model] = {
                    "count": count,
                    "total_time": round(metrics["total_time"], 3),
                    "avg_time": round(metrics["total_time"] / count, 3) if count > 0 else 0,
                }

            return report

    def get_summary(self) -> Dict[str, Any]:
        """获取简要性能摘要"""
        with self._lock:
            if self._request_count == 0:
                return {"status": "no_data", "request_count": 0}

            avg_time = self._total_time / self._request_count
            return {
                "request_count": self._request_count,
                "avg_response_time": round(avg_time, 3),
                "p95_response_time": self._percentile(95),
                "error_rate": round(self._error_count / self._request_count * 100, 1) if self._request_count > 0 else 0,
                "uptime": round(time.time() - self._start_time, 1),
            }

    def get_engine_comparison(self) -> Dict[str, Dict[str, Any]]:
        """获取引擎性能对比"""
        with self._lock:
            comparison = {}
            for engine, metrics in self._engine_metrics.items():
                count = metrics["count"]
                if count == 0:
                    continue
                comparison[engine] = {
                    "count": count,
                    "avg_time": round(metrics["total_time"] / count, 3),
                    "min_time": round(min(metrics["response_times"]), 3) if metrics["response_times"] else 0,
                    "max_time": round(max(metrics["response_times"]), 3) if metrics["response_times"] else 0,
                    "error_count": self._errors_by_engine.get(engine, 0),
                }
            return comparison

    def get_slow_requests(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取慢请求列表

        Args:
            limit: 最大返回数量

        Returns:
            慢请求列表（按响应时间倒序）
        """
        with self._lock:
            sorted_requests = sorted(
                self._slow_requests,
                key=lambda x: x["response_time"],
                reverse=True,
            )
            return sorted_requests[:limit]

    # ============================================================
    # 控制
    # ============================================================

    def reset(self):
        """重置所有统计数据"""
        with self._lock:
            self._request_count = 0
            self._total_time = 0.0
            self._response_times.clear()
            self._start_time = time.time()
            self._engine_metrics.clear()
            self._model_metrics.clear()
            self._throughput_samples.clear()
            self._error_count = 0
            self._errors_by_engine.clear()
            self._slow_requests.clear()
            self._resource_samples.clear()

    def set_slow_threshold(self, seconds: float):
        """设置慢请求阈值

        Args:
            seconds: 慢请求阈值（秒）
        """
        self._slow_threshold = seconds

    def set_max_history(self, max_history: int):
        """设置最大历史记录数"""
        self._max_history = max_history

    # ============================================================
    # 内部方法
    # ============================================================

    def _percentile(self, p: float) -> float:
        """计算百分位数

        Args:
            p: 百分位（0-100）

        Returns:
            百分位数值
        """
        if not self._response_times:
            return 0.0
        sorted_times = sorted(self._response_times)
        index = int(len(sorted_times) * p / 100)
        index = min(index, len(sorted_times) - 1)
        return round(sorted_times[index], 3)


# ============================================================
# 全局单例
# ============================================================

_performance_analyzer: Optional[PerformanceAnalyzer] = None


def get_performance_analyzer() -> PerformanceAnalyzer:
    """获取全局性能分析器单例"""
    global _performance_analyzer
    if _performance_analyzer is None:
        _performance_analyzer = PerformanceAnalyzer()
    return _performance_analyzer