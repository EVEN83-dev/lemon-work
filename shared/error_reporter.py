# -*- coding: utf-8 -*-
"""
Error Reporter — 错误报告系统
==============================
自动收集错误信息、生成结构化报告、支持本地存储和查询。

功能：
1. 自动收集错误信息（类型、消息、堆栈、上下文）
2. 生成结构化错误报告（JSON 格式）
3. 保存到本地文件系统
4. 错误报告查询和统计
5. 错误分类和聚合
6. 报告导出

使用方式：
    reporter = ErrorReporter()
    reporter.report_error("ConnectionError", "连接超时", context={"port": 4097})
    reports = reporter.get_recent_reports(10)
    stats = reporter.get_statistics()
"""

import os
import json
import threading
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List


class ErrorCategory:
    """错误分类"""
    NETWORK = "network"
    ENGINE = "engine"
    VALIDATION = "validation"
    SYSTEM = "system"
    USER = "user"
    UNKNOWN = "unknown"


class ErrorSeverity:
    """错误严重级别"""
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ErrorReporter:
    """错误报告管理器

    收集、存储、查询错误报告，支持统计和导出。
    """

    VERSION = "1.0.0"
    MAX_REPORTS = 500  # 最大报告数量

    def __init__(self, report_dir: str = None):
        """
        Args:
            report_dir: 报告存储目录，默认 ~/.lemon_agent/reports
        """
        if report_dir is None:
            report_dir = os.path.join(os.path.expanduser("~"), ".lemon_agent", "reports")
        self.report_dir = report_dir
        os.makedirs(self.report_dir, exist_ok=True)

        self._lock = threading.Lock()
        self._report_count = 0
        self._on_report: Optional[callable] = None

    # ============================================================
    # 错误报告
    # ============================================================

    def report_error(self, error_type: str, error_msg: str,
                     category: str = ErrorCategory.UNKNOWN,
                     severity: str = ErrorSeverity.ERROR,
                     context: Dict[str, Any] = None,
                     include_traceback: bool = True) -> str:
        """报告错误并生成报告文件

        Args:
            error_type: 错误类型（如 ConnectionError）
            error_msg: 错误消息
            category: 错误分类
            severity: 严重级别
            context: 上下文信息
            include_traceback: 是否包含堆栈跟踪

        Returns:
            报告文件路径
        """
        with self._lock:
            self._report_count += 1

            report = {
                "report_id": self._report_count,
                "timestamp": datetime.now().isoformat(),
                "error_type": error_type,
                "error_message": error_msg,
                "category": category,
                "severity": severity,
                "context": context or {},
                "version": self.VERSION,
            }

            # 添加堆栈跟踪
            if include_traceback:
                report["traceback"] = traceback.format_exc()

            # 保存报告
            filename = f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._report_count:04d}.json"
            filepath = os.path.join(self.report_dir, filename)

            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            # 清理旧报告
            self._cleanup_old_reports()

            # 回调通知
            if self._on_report:
                try:
                    self._on_report(report)
                except Exception:
                    pass

            return filepath

    def report_exception(self, exc: Exception, category: str = ErrorCategory.UNKNOWN,
                         severity: str = ErrorSeverity.ERROR,
                         context: Dict[str, Any] = None) -> str:
        """报告异常

        Args:
            exc: 异常对象
            category: 错误分类
            severity: 严重级别
            context: 上下文信息

        Returns:
            报告文件路径
        """
        return self.report_error(
            error_type=type(exc).__name__,
            error_msg=str(exc),
            category=category,
            severity=severity,
            context=context,
            include_traceback=True,
        )

    def report_network_error(self, error_msg: str, context: Dict[str, Any] = None) -> str:
        """报告网络错误"""
        return self.report_error(
            "NetworkError", error_msg,
            category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.ERROR,
            context=context,
        )

    def report_engine_error(self, engine_name: str, error_msg: str,
                            context: Dict[str, Any] = None) -> str:
        """报告引擎错误"""
        ctx = context or {}
        ctx["engine"] = engine_name
        return self.report_error(
            "EngineError", error_msg,
            category=ErrorCategory.ENGINE,
            severity=ErrorSeverity.ERROR,
            context=ctx,
        )

    def report_warning(self, warning_type: str, warning_msg: str,
                       context: Dict[str, Any] = None) -> str:
        """报告警告"""
        return self.report_error(
            warning_type, warning_msg,
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.WARNING,
            context=context,
            include_traceback=False,
        )

    # ============================================================
    # 报告查询
    # ============================================================

    def get_recent_reports(self, limit: int = 10,
                           category: str = None,
                           severity: str = None) -> List[Dict[str, Any]]:
        """获取最近的错误报告

        Args:
            limit: 最大返回数量
            category: 按分类过滤
            severity: 按严重级别过滤

        Returns:
            报告列表（按时间倒序）
        """
        reports = []
        try:
            files = sorted(os.listdir(self.report_dir), reverse=True)
            for filename in files:
                if not filename.startswith("error_") or not filename.endswith(".json"):
                    continue
                filepath = os.path.join(self.report_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        report = json.load(f)
                except Exception:
                    continue

                # 过滤
                if category and report.get("category") != category:
                    continue
                if severity and report.get("severity") != severity:
                    continue

                reports.append(report)
                if len(reports) >= limit:
                    break
        except Exception:
            pass
        return reports

    def get_report_by_id(self, report_id: int) -> Optional[Dict[str, Any]]:
        """按 ID 获取报告

        Args:
            report_id: 报告 ID

        Returns:
            报告字典，未找到则返回 None
        """
        reports = self.get_recent_reports(limit=self.MAX_REPORTS)
        for report in reports:
            if report.get("report_id") == report_id:
                return report
        return None

    # ============================================================
    # 统计
    # ============================================================

    def get_statistics(self) -> Dict[str, Any]:
        """获取错误统计

        Returns:
            统计信息字典
        """
        stats = {
            "total_reports": 0,
            "by_category": {},
            "by_severity": {},
            "by_error_type": {},
            "recent_errors": 0,
            "last_24h": 0,
            "last_7d": 0,
        }

        now = datetime.now()
        cutoff_24h = now.replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_7d = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # 7天前
        from datetime import timedelta
        cutoff_7d = cutoff_7d - timedelta(days=7)

        try:
            for filename in os.listdir(self.report_dir):
                if not filename.startswith("error_") or not filename.endswith(".json"):
                    continue
                filepath = os.path.join(self.report_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        report = json.load(f)
                except Exception:
                    continue

                stats["total_reports"] += 1

                # 分类统计
                category = report.get("category", "unknown")
                stats["by_category"][category] = stats["by_category"].get(category, 0) + 1

                # 严重级别统计
                severity = report.get("severity", "info")
                stats["by_severity"][severity] = stats["by_severity"].get(severity, 0) + 1

                # 错误类型统计
                error_type = report.get("error_type", "Unknown")
                stats["by_error_type"][error_type] = stats["by_error_type"].get(error_type, 0) + 1

                # 时间范围统计
                try:
                    report_time = datetime.fromisoformat(report.get("timestamp", ""))
                    if report_time >= cutoff_24h:
                        stats["last_24h"] += 1
                    if report_time >= cutoff_7d:
                        stats["last_7d"] += 1
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass

        return stats

    # ============================================================
    # 清理
    # ============================================================

    def clear_reports(self):
        """清除所有错误报告"""
        try:
            for filename in os.listdir(self.report_dir):
                if filename.startswith("error_") and filename.endswith(".json"):
                    filepath = os.path.join(self.report_dir, filename)
                    os.remove(filepath)
        except Exception:
            pass

    def _cleanup_old_reports(self):
        """清理超出限制的旧报告"""
        try:
            files = sorted(
                [f for f in os.listdir(self.report_dir)
                 if f.startswith("error_") and f.endswith(".json")],
                reverse=True,
            )
            for filename in files[self.MAX_REPORTS:]:
                filepath = os.path.join(self.report_dir, filename)
                os.remove(filepath)
        except Exception:
            pass

    # ============================================================
    # 回调
    # ============================================================

    def on_report(self, callback: callable):
        """设置报告回调"""
        self._on_report = callback


# ============================================================
# 全局单例
# ============================================================

_error_reporter: Optional[ErrorReporter] = None


def get_error_reporter() -> ErrorReporter:
    """获取全局错误报告器单例"""
    global _error_reporter
    if _error_reporter is None:
        _error_reporter = ErrorReporter()
    return _error_reporter