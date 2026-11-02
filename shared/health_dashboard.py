# -*- coding: utf-8 -*-
"""
项目健康仪表盘（v0.7.0 新增）
==============================
综合展示项目运行状态、错误统计、依赖健康、Agent 负载等信息。

功能：
1. 依赖健康状态（MIMO Code / Ollama / DeepSeek）
2. 错误统计趋势（24h/7d）
3. Agent 负载和工作量
4. 反馈质量评分
5. 会话统计
6. 系统资源使用

架构：
┌────────────────────────────────────┐
│       HealthDashboard              │
│  ┌──────────┐ ┌──────────┐        │
│  │依赖状态  │ │错误统计  │        │
│  └──────────┘ └──────────┘        │
│  ┌──────────┐ ┌──────────┐        │
│  │Agent负载 │ │质量评分  │        │
│  └──────────┘ └──────────┘        │
│  ┌──────────┐ ┌──────────┐        │
│  │会话统计  │ │系统资源  │        │
│  └──────────┘ └──────────┘        │
└────────────────────────────────────┘

使用方式：
    dashboard = HealthDashboard()
    report = dashboard.generate_report()
    summary = dashboard.get_summary()
"""

import os
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class DependencyStatus:
    """依赖状态"""
    name: str
    installed: bool = False
    running: bool = False
    version: str = ""
    host: str = ""
    error: str = ""


@dataclass
class ErrorTrend:
    """错误趋势"""
    last_24h: int = 0
    last_7d: int = 0
    by_category: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)
    recent_errors: List[Dict] = field(default_factory=list)


@dataclass
class AgentLoad:
    """Agent 负载信息"""
    agent_id: str
    status: str = "idle"  # idle / busy / error
    tasks_completed: int = 0
    tasks_failed: int = 0
    current_task: str = ""


@dataclass
class QualityScore:
    """质量评分"""
    overall: float = 0.0
    response_quality: float = 0.0
    user_satisfaction: float = 0.0
    error_rate: float = 0.0
    samples: int = 0


@dataclass
class SessionStats:
    """会话统计"""
    total_sessions: int = 0
    active_sessions: int = 0
    total_messages: int = 0
    avg_session_length: float = 0.0
    agents_used: List[str] = field(default_factory=list)


@dataclass
class SystemResources:
    """系统资源"""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    disk_percent: float = 0.0
    uptime_seconds: float = 0.0


@dataclass
class HealthReport:
    """健康报告"""
    timestamp: str = ""
    overall_status: str = "unknown"  # healthy / degraded / unhealthy
    overall_score: float = 0.0  # 0-100
    dependencies: Dict[str, DependencyStatus] = field(default_factory=dict)
    error_trend: ErrorTrend = field(default_factory=ErrorTrend)
    agent_loads: List[AgentLoad] = field(default_factory=list)
    quality: QualityScore = field(default_factory=QualityScore)
    sessions: SessionStats = field(default_factory=SessionStats)
    resources: SystemResources = field(default_factory=SystemResources)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


class HealthDashboard:
    """项目健康仪表盘 — 综合状态监控和报告"""

    VERSION = "1.0.0"

    def __init__(self):
        self._lock = threading.Lock()
        self._last_report: Optional[HealthReport] = None
        self._start_time = time.time()

    # ============================================================
    # 报告生成
    # ============================================================

    def generate_report(
        self,
        dependency_manager=None,
        error_reporter=None,
        orchestrator=None,
        feedback_loop=None,
        session_continuity=None,
    ) -> HealthReport:
        """生成综合健康报告

        Args:
            dependency_manager: DependencyManager 实例
            error_reporter: ErrorReporter 实例
            orchestrator: AgentOrchestrator 实例
            feedback_loop: FeedbackLoop 实例
            session_continuity: SessionContinuity 实例

        Returns:
            HealthReport 完整健康报告
        """
        with self._lock:
            report = HealthReport(timestamp=datetime.now().isoformat())

            # 1. 依赖状态
            report.dependencies = self._check_dependencies(dependency_manager)

            # 2. 错误趋势
            report.error_trend = self._check_errors(error_reporter)

            # 3. Agent 负载
            report.agent_loads = self._check_agent_loads(orchestrator)

            # 4. 质量评分
            report.quality = self._check_quality(feedback_loop)

            # 5. 会话统计
            report.sessions = self._check_sessions(session_continuity)

            # 6. 系统资源
            report.resources = self._check_resources()

            # 7. 计算综合评分
            report.overall_score = self._calculate_overall_score(report)
            report.overall_status = self._determine_status(report.overall_score)

            # 8. 生成警告和建议
            report.warnings = self._generate_warnings(report)
            report.suggestions = self._generate_suggestions(report)

            self._last_report = report
            return report

    def _check_dependencies(self, dep_manager) -> Dict[str, DependencyStatus]:
        """检查依赖健康状态"""
        result = {}
        if dep_manager is None:
            return result

        try:
            all_status = dep_manager.get_all_status()
            for name, info in all_status.items():
                error = ""
                if not info.installed:
                    error = "未安装"
                elif not info.running:
                    error = "已安装但未运行"
                result[name] = DependencyStatus(
                    name=name,
                    installed=info.installed,
                    running=info.running,
                    version=info.version,
                    host=info.host,
                    error=error,
                )
        except Exception as e:
            result["_error"] = DependencyStatus(
                name="_error", error=f"依赖检查失败: {e}"
            )
        return result

    def _check_errors(self, error_reporter) -> ErrorTrend:
        """检查错误趋势"""
        trend = ErrorTrend()
        if error_reporter is None:
            return trend

        try:
            stats = error_reporter.get_statistics()
            trend.last_24h = stats.get("last_24h", 0)
            trend.last_7d = stats.get("last_7d", 0)
            trend.by_category = stats.get("by_category", {})
            trend.by_severity = stats.get("by_severity", {})

            # 最近的错误
            recent = error_reporter.get_recent_reports(limit=5)
            trend.recent_errors = [
                {
                    "type": r.get("error_type", ""),
                    "message": r.get("error_message", "")[:100],
                    "time": r.get("timestamp", ""),
                    "severity": r.get("severity", ""),
                }
                for r in recent
            ]
        except Exception:
            pass
        return trend

    def _check_agent_loads(self, orchestrator) -> List[AgentLoad]:
        """检查 Agent 负载"""
        loads = []
        if orchestrator is None:
            return loads

        try:
            report = orchestrator.get_workload_report()
            for agent_id, info in report.get("agents", {}).items():
                loads.append(AgentLoad(
                    agent_id=agent_id,
                    status=info.get("status", "unknown"),
                    tasks_completed=info.get("tasks_completed", 0),
                    tasks_failed=info.get("tasks_failed", 0),
                    current_task=info.get("current_task", ""),
                ))
        except Exception:
            pass
        return loads

    def _check_quality(self, feedback_loop) -> QualityScore:
        """检查质量评分"""
        score = QualityScore()
        if feedback_loop is None:
            return score

        try:
            dashboard_data = feedback_loop.get_quality_dashboard_data()
            score.overall = dashboard_data.get("overall_score", 0.0)
            score.response_quality = dashboard_data.get("avg_auto_score", 0.0)
            score.user_satisfaction = dashboard_data.get("user_satisfaction", 0.0)
            score.error_rate = dashboard_data.get("error_rate", 0.0)
            score.samples = dashboard_data.get("total_interactions", 0)
        except Exception:
            pass
        return score

    def _check_sessions(self, session_continuity) -> SessionStats:
        """检查会话统计"""
        stats = SessionStats()
        if session_continuity is None:
            return stats

        try:
            session_stats = session_continuity.get_session_statistics()
            stats.total_sessions = session_stats.get("total_sessions", 0)
            stats.active_sessions = session_stats.get("active_sessions", 0)
            stats.total_messages = session_stats.get("total_messages", 0)
            stats.avg_session_length = session_stats.get("avg_messages_per_session", 0.0)
            stats.agents_used = session_stats.get("agents", [])
        except Exception:
            pass
        return stats

    def _check_resources(self) -> SystemResources:
        """检查系统资源"""
        res = SystemResources()
        try:
            import psutil
            res.cpu_percent = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            res.memory_percent = mem.percent
            res.memory_used_mb = mem.used / (1024 * 1024)
            res.memory_total_mb = mem.total / (1024 * 1024)
            res.disk_percent = psutil.disk_usage("/").percent
        except ImportError:
            # psutil 未安装，使用基本估算
            pass
        except Exception:
            pass

        res.uptime_seconds = time.time() - self._start_time
        return res

    # ============================================================
    # 评分计算
    # ============================================================

    def _calculate_overall_score(self, report: HealthReport) -> float:
        """计算综合健康评分 (0-100)"""
        score = 100.0

        # 依赖状态扣分（每个未安装 -15，未运行 -8）
        for dep in report.dependencies.values():
            if not dep.installed:
                score -= 15
            elif not dep.running:
                score -= 8

        # 错误趋势扣分
        if report.error_trend.last_24h > 10:
            score -= 15
        elif report.error_trend.last_24h > 5:
            score -= 8
        elif report.error_trend.last_24h > 0:
            score -= 3

        # 质量评分加权
        if report.quality.samples > 0:
            quality_bonus = report.quality.overall * 10  # 0-10 加分
            score += quality_bonus

        # Agent 负载（全部空闲不扣分，有失败扣分）
        for load in report.agent_loads:
            if load.tasks_failed > 0:
                fail_rate = load.tasks_failed / max(load.tasks_completed + load.tasks_failed, 1)
                score -= fail_rate * 10

        return max(0.0, min(100.0, score))

    def _determine_status(self, score: float) -> str:
        """根据评分确定状态"""
        if score >= 80:
            return "healthy"
        elif score >= 50:
            return "degraded"
        else:
            return "unhealthy"

    # ============================================================
    # 警告和建议
    # ============================================================

    def _generate_warnings(self, report: HealthReport) -> List[str]:
        """生成警告列表"""
        warnings = []

        # 依赖警告
        for dep in report.dependencies.values():
            if not dep.installed:
                warnings.append(f"⚠️ {dep.name} 未安装")
            elif not dep.running:
                warnings.append(f"⚠️ {dep.name} 已安装但未运行")

        # 错误警告
        if report.error_trend.last_24h > 10:
            warnings.append(f"⚠️ 过去24小时错误数过多: {report.error_trend.last_24h}")

        critical = report.error_trend.by_severity.get("critical", 0)
        if critical > 0:
            warnings.append(f"🔴 存在 {critical} 个严重错误")

        # 资源警告
        if report.resources.memory_percent > 90:
            warnings.append(f"⚠️ 内存使用过高: {report.resources.memory_percent:.1f}%")
        if report.resources.cpu_percent > 90:
            warnings.append(f"⚠️ CPU 使用过高: {report.resources.cpu_percent:.1f}%")

        return warnings

    def _generate_suggestions(self, report: HealthReport) -> List[str]:
        """生成改进建议"""
        suggestions = []

        # 依赖建议
        uninstalled = [d.name for d in report.dependencies.values() if not d.installed]
        if uninstalled:
            suggestions.append(f"建议安装缺失依赖: {', '.join(uninstalled)}")

        not_running = [d.name for d in report.dependencies.values() if d.installed and not d.running]
        if not_running:
            suggestions.append(f"建议启动服务: {', '.join(not_running)}")

        # 错误建议
        if report.error_trend.last_24h > 5:
            top_category = max(
                report.error_trend.by_category.items(),
                key=lambda x: x[1],
                default=("unknown", 0),
            )
            if top_category[1] > 0:
                suggestions.append(f"高频错误类别: {top_category[0]} ({top_category[1]}次)，建议优先修复")

        # 质量建议
        if report.quality.samples > 0 and report.quality.overall < 0.6:
            suggestions.append("质量评分偏低，建议检查反馈循环和AI响应质量")

        # Agent 建议
        for load in report.agent_loads:
            if load.tasks_failed > load.tasks_completed:
                suggestions.append(f"Agent {load.agent_id} 失败率过高，建议检查配置")

        return suggestions

    # ============================================================
    # 便捷方法
    # ============================================================

    def get_summary(self) -> Dict[str, Any]:
        """获取简要摘要（用于 UI 展示）"""
        report = self._last_report
        if report is None:
            return {"status": "no_data", "message": "尚未生成报告，请先调用 generate_report()"}

        return {
            "status": report.overall_status,
            "score": round(report.overall_score, 1),
            "timestamp": report.timestamp,
            "dependencies": {
                name: {"installed": dep.installed, "running": dep.running}
                for name, dep in report.dependencies.items()
            },
            "errors_24h": report.error_trend.last_24h,
            "quality": round(report.quality.overall, 2),
            "active_agents": len([l for l in report.agent_loads if l.status == "busy"]),
            "warnings_count": len(report.warnings),
            "uptime": round(report.resources.uptime_seconds, 0),
        }

    def get_last_report(self) -> Optional[HealthReport]:
        """获取最近一次报告"""
        return self._last_report

    def format_report_text(self, report: HealthReport = None) -> str:
        """格式化报告为可读文本"""
        r = report or self._last_report
        if r is None:
            return "暂无健康报告"

        status_icon = {"healthy": "✅", "degraded": "⚠️", "unhealthy": "🔴"}.get(r.overall_status, "❓")

        lines = [
            f"{'='*50}",
            f"  Lemon Agent 健康报告",
            f"{'='*50}",
            f"时间: {r.timestamp}",
            f"综合状态: {status_icon} {r.overall_status.upper()} (评分: {r.overall_score:.1f}/100)",
            "",
        ]

        # 依赖状态
        lines.append("── 依赖状态 ──")
        for dep in r.dependencies.values():
            icon = "✅" if dep.installed and dep.running else ("⚠️" if dep.installed else "❌")
            lines.append(f"  {icon} {dep.name}: {'运行中' if dep.running else dep.error}")
        lines.append("")

        # 错误趋势
        lines.append("── 错误趋势 ──")
        lines.append(f"  24h: {r.error_trend.last_24h} | 7d: {r.error_trend.last_7d}")
        if r.error_trend.by_severity:
            sev = r.error_trend.by_severity
            lines.append(f"  严重: {sev.get('critical',0)} | 高: {sev.get('error',0)} | 中: {sev.get('warning',0)}")
        lines.append("")

        # 质量评分
        if r.quality.samples > 0:
            lines.append("── 质量评分 ──")
            lines.append(f"  综合: {r.quality.overall:.2f} | 样本: {r.quality.samples}")
            lines.append("")

        # 系统资源
        if r.resources.memory_total_mb > 0:
            lines.append("── 系统资源 ──")
            lines.append(f"  CPU: {r.resources.cpu_percent:.1f}% | 内存: {r.resources.memory_percent:.1f}%")
            uptime_h = r.resources.uptime_seconds / 3600
            lines.append(f"  运行时间: {uptime_h:.1f}h")
            lines.append("")

        # 警告
        if r.warnings:
            lines.append("── 警告 ──")
            for w in r.warnings:
                lines.append(f"  {w}")
            lines.append("")

        # 建议
        if r.suggestions:
            lines.append("── 建议 ──")
            for s in r.suggestions:
                lines.append(f"  💡 {s}")

        return "\n".join(lines)
