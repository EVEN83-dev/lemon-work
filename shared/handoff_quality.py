# -*- coding: utf-8 -*-
"""
Handoff 质量评估器 — HandoffQualityEvaluator
============================================
评估 SessionContinuity 的 handoff 文档完整性，必要时补充关键信息。

功能：
1. 评估 handoff 文档质量（完整度评分 0-100）
2. 检查必要字段是否存在
3. 检查关键信息是否充分（任务清单、已完成项、待办项、技术决策）
4. 自动补充缺失信息
5. 生成质量报告
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field


# ============================================================
# 数据结构
# ============================================================

@dataclass
class HandoffQualityReport:
    """Handoff 文档质量评估报告"""
    score: int  # 0-100
    level: str  # "excellent" / "good" / "acceptable" / "poor" / "critical"
    missing_fields: List[str] = field(default_factory=list)
    weak_areas: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    enriched_doc: Optional[dict] = None

    # 评分等级阈值
    _THRESHOLDS = {
        "excellent": 90,
        "good": 75,
        "acceptable": 60,
        "poor": 40,
    }

    @classmethod
    def level_from_score(cls, score: int) -> str:
        """根据评分确定等级"""
        if score >= cls._THRESHOLDS["excellent"]:
            return "excellent"
        elif score >= cls._THRESHOLDS["good"]:
            return "good"
        elif score >= cls._THRESHOLDS["acceptable"]:
            return "acceptable"
        elif score >= cls._THRESHOLDS["poor"]:
            return "poor"
        else:
            return "critical"


# ============================================================
# Handoff 质量评估器
# ============================================================

class HandoffQualityEvaluator:
    """
    Handoff 文档质量评估器
    =====================
    评估 SessionContinuity 的 handoff 文档完整性，
    必要时自动补充关键信息。

    评估维度（各占权重）：
    - 必要字段完整性：30 分（agent_id, session_id, summary, timestamp）
    - 任务信息充分性：25 分（tasks, completed, pending）
    - 上下文信息充分性：20 分（technical_decisions, file_changes, api_usage）
    - 对话历史深度：15 分（recent_messages 轮数）
    - 接班指引清晰度：10 分（next_steps）
    """

    # 必要字段定义
    REQUIRED_FIELDS = ["agent_id", "session_id", "summary", "timestamp"]

    # 任务信息字段
    TASK_FIELDS = ["tasks", "completed", "pending"]

    # 上下文信息字段
    CONTEXT_FIELDS = ["technical_decisions", "file_changes", "api_usage"]

    def evaluate(self, handoff_doc: dict) -> HandoffQualityReport:
        """
        评估 handoff 文档质量

        Args:
            handoff_doc: 结构化的 handoff 文档字典

        Returns:
            HandoffQualityReport 评估报告
        """
        if not handoff_doc or not isinstance(handoff_doc, dict):
            return HandoffQualityReport(
                score=0,
                level="critical",
                missing_fields=list(self.REQUIRED_FIELDS),
                weak_areas=["文档为空或格式错误"],
                suggestions=["请提供有效的 handoff 文档"],
            )

        missing_fields: List[str] = []
        weak_areas: List[str] = []
        suggestions: List[str] = []

        # ---- 1. 必要字段完整性（30 分）----
        required_score = 0
        for f in self.REQUIRED_FIELDS:
            if f in handoff_doc and handoff_doc[f]:
                required_score += 30 // len(self.REQUIRED_FIELDS)
            else:
                missing_fields.append(f)
        required_score = min(required_score, 30)

        if missing_fields:
            weak_areas.append(f"缺少必要字段: {', '.join(missing_fields)}")
            suggestions.append(f"请补充缺失的必要字段: {', '.join(missing_fields)}")

        # ---- 2. 任务信息充分性（25 分）----
        task_score = 0
        task_present = 0
        for f in self.TASK_FIELDS:
            if f in handoff_doc and handoff_doc[f]:
                task_present += 1

        if task_present == len(self.TASK_FIELDS):
            task_score = 25
        elif task_present >= 2:
            task_score = 18
        elif task_present >= 1:
            task_score = 10
            weak_areas.append("任务信息不完整，缺少部分任务字段")
            missing_task = [f for f in self.TASK_FIELDS if f not in handoff_doc or not handoff_doc[f]]
            suggestions.append(f"建议补充任务字段: {', '.join(missing_task)}")
        else:
            task_score = 0
            weak_areas.append("缺少所有任务信息")
            suggestions.append("请添加 tasks、completed、pending 字段以描述任务状态")

        # ---- 3. 上下文信息充分性（20 分）----
        context_score = 0
        context_present = 0
        for f in self.CONTEXT_FIELDS:
            if f in handoff_doc and handoff_doc[f]:
                context_present += 1

        if context_present == len(self.CONTEXT_FIELDS):
            context_score = 20
        elif context_present >= 2:
            context_score = 14
        elif context_present >= 1:
            context_score = 8
            weak_areas.append("上下文信息不够充分")
        else:
            context_score = 0
            weak_areas.append("缺少上下文信息（技术决策、文件变更、API 使用）")
            suggestions.append("建议记录技术决策、文件变更和 API 使用情况")

        # ---- 4. 对话历史深度（15 分）----
        history_score = 0
        recent_messages = handoff_doc.get("recent_messages", [])
        msg_count = len(recent_messages) if isinstance(recent_messages, list) else 0

        if msg_count >= 6:
            history_score = 15
        elif msg_count >= 4:
            history_score = 11
        elif msg_count >= 2:
            history_score = 7
            weak_areas.append("对话历史偏少，接班 agent 可能缺少足够上下文")
        elif msg_count >= 1:
            history_score = 3
            weak_areas.append("对话历史严重不足")
            suggestions.append("建议保留至少 4 轮最近对话记录")
        else:
            history_score = 0
            weak_areas.append("无对话历史记录")
            suggestions.append("强烈建议包含最近对话记录以保持上下文连续性")

        # ---- 5. 接班指引清晰度（10 分）----
        guidance_score = 0
        next_steps = handoff_doc.get("next_steps", [])
        if isinstance(next_steps, list) and len(next_steps) >= 3:
            guidance_score = 10
        elif isinstance(next_steps, list) and len(next_steps) >= 1:
            guidance_score = 6
            weak_areas.append("接班指引不够详细")
            suggestions.append("建议提供更具体的 next_steps 列表（至少 3 项）")
        elif isinstance(next_steps, str) and next_steps.strip():
            guidance_score = 5
        else:
            guidance_score = 0
            weak_areas.append("缺少接班指引（next_steps）")
            suggestions.append("请添加 next_steps 字段，指明接班 agent 应优先处理的事项")

        # ---- 汇总 ----
        total_score = required_score + task_score + context_score + history_score + guidance_score
        total_score = max(0, min(100, total_score))

        return HandoffQualityReport(
            score=total_score,
            level=HandoffQualityReport.level_from_score(total_score),
            missing_fields=missing_fields,
            weak_areas=weak_areas,
            suggestions=suggestions,
        )

    def auto_enrich(self, handoff_doc: dict, session_data: dict = None) -> dict:
        """
        自动补充缺失信息

        Args:
            handoff_doc: 原始 handoff 文档
            session_data: 可选的会话数据，用于提取补充信息

        Returns:
            补充后的 handoff 文档（新字典，不修改原始文档）
        """
        if not handoff_doc or not isinstance(handoff_doc, dict):
            return dict(handoff_doc or {})

        enriched = dict(handoff_doc)
        session_data = session_data or {}

        # 缺少 tasks → 从 session_data 提取
        if not enriched.get("tasks"):
            tasks = session_data.get("tasks", [])
            if tasks:
                enriched["tasks"] = tasks
            else:
                enriched["tasks"] = ["（未记录具体任务）"]

        # 缺少 completed → 从任务状态推断
        if not enriched.get("completed"):
            tasks = session_data.get("tasks", [])
            completed = [t for t in tasks if isinstance(t, dict) and t.get("status") == "completed"]
            if completed:
                enriched["completed"] = completed
            elif tasks:
                enriched["completed"] = []
            else:
                enriched["completed"] = ["（未记录已完成项）"]

        # 缺少 pending → 从任务状态推断
        if not enriched.get("pending"):
            tasks = session_data.get("tasks", [])
            pending = [t for t in tasks if isinstance(t, dict) and t.get("status") != "completed"]
            if pending:
                enriched["pending"] = pending
            elif tasks:
                enriched["pending"] = []
            else:
                enriched["pending"] = ["（未记录待办项）"]

        # 缺少 next_steps → 根据 pending 任务生成
        if not enriched.get("next_steps"):
            pending_items = enriched.get("pending", [])
            if pending_items and pending_items != ["（未记录待办项）"]:
                enriched["next_steps"] = [
                    f"继续处理: {item}" if isinstance(item, str) else f"继续处理: {item.get('name', '未知任务')}"
                    for item in pending_items[:5]
                ]
            else:
                enriched["next_steps"] = [
                    "继续上一会话未完成的任务",
                    "保持上下文一致性",
                    "引用移交文档中的关键信息",
                ]

        # 缺少 technical_decisions → 标记为"未记录"
        if not enriched.get("technical_decisions"):
            decisions = session_data.get("technical_decisions", [])
            if decisions:
                enriched["technical_decisions"] = decisions
            else:
                enriched["technical_decisions"] = ["未记录"]

        # 缺少 file_changes → 从 session_data 提取
        if not enriched.get("file_changes"):
            file_changes = session_data.get("file_changes", [])
            if file_changes:
                enriched["file_changes"] = file_changes

        # 缺少 api_usage → 从 session_data 提取
        if not enriched.get("api_usage"):
            api_usage = session_data.get("api_usage", [])
            if api_usage:
                enriched["api_usage"] = api_usage

        # 缺少 recent_messages → 从 session_data 提取最近对话
        if not enriched.get("recent_messages"):
            messages = session_data.get("messages", [])
            if messages:
                enriched["recent_messages"] = messages[-12:]  # 最近 6 轮（每轮 user+assistant）

        return enriched

    def generate_report(self, handoff_doc: dict) -> str:
        """
        生成可读的质量评估报告

        Args:
            handoff_doc: 结构化的 handoff 文档字典

        Returns:
            Markdown 格式的质量评估报告
        """
        report = self.evaluate(handoff_doc)

        level_labels = {
            "excellent": "优秀",
            "good": "良好",
            "acceptable": "合格",
            "poor": "较差",
            "critical": "严重不足",
        }
        level_emoji = {
            "excellent": "🟢",
            "good": "🔵",
            "acceptable": "🟡",
            "poor": "🟠",
            "critical": "🔴",
        }

        lines = [
            "# Handoff 文档质量评估报告",
            "",
            f"**评估时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**评分**: {report.score} / 100",
            f"**等级**: {level_emoji.get(report.level, '⚪')} {level_labels.get(report.level, report.level)}",
            "",
        ]

        # 评分条
        bar_filled = "█" * (report.score // 5)
        bar_empty = "░" * (20 - report.score // 5)
        lines.append(f"**评分条**: [{bar_filled}{bar_empty}] {report.score}%")
        lines.append("")

        # 缺失字段
        if report.missing_fields:
            lines.append("## ❌ 缺失字段")
            lines.append("")
            for f in report.missing_fields:
                lines.append(f"- `{f}`")
            lines.append("")

        # 薄弱环节
        if report.weak_areas:
            lines.append("## ⚠ 薄弱环节")
            lines.append("")
            for area in report.weak_areas:
                lines.append(f"- {area}")
            lines.append("")

        # 改进建议
        if report.suggestions:
            lines.append("## 💡 改进建议")
            lines.append("")
            for i, s in enumerate(report.suggestions, 1):
                lines.append(f"{i}. {s}")
            lines.append("")

        # 各维度评分明细
        lines.append("## 📊 各维度评分明细")
        lines.append("")

        if handoff_doc and isinstance(handoff_doc, dict):
            # 必要字段
            req_present = sum(1 for f in self.REQUIRED_FIELDS if f in handoff_doc and handoff_doc[f])
            lines.append(f"| 维度 | 权重 | 状态 |")
            lines.append(f"|------|------|------|")
            lines.append(f"| 必要字段完整性 | 30分 | {req_present}/{len(self.REQUIRED_FIELDS)} 字段已填 |")

            # 任务信息
            task_present = sum(1 for f in self.TASK_FIELDS if f in handoff_doc and handoff_doc[f])
            lines.append(f"| 任务信息充分性 | 25分 | {task_present}/{len(self.TASK_FIELDS)} 字段已填 |")

            # 上下文信息
            ctx_present = sum(1 for f in self.CONTEXT_FIELDS if f in handoff_doc and handoff_doc[f])
            lines.append(f"| 上下文信息充分性 | 20分 | {ctx_present}/{len(self.CONTEXT_FIELDS)} 字段已填 |")

            # 对话历史
            msg_count = len(handoff_doc.get("recent_messages", [])) if isinstance(handoff_doc.get("recent_messages"), list) else 0
            lines.append(f"| 对话历史深度 | 15分 | {msg_count} 条消息 |")

            # 接班指引
            next_steps = handoff_doc.get("next_steps", [])
            ns_count = len(next_steps) if isinstance(next_steps, list) else (1 if isinstance(next_steps, str) and next_steps.strip() else 0)
            lines.append(f"| 接班指引清晰度 | 10分 | {ns_count} 条指引 |")

            lines.append("")

        lines.extend([
            "---",
            f"*本报告由 HandoffQualityEvaluator 自动生成于 {datetime.now().isoformat()}*",
        ])

        return "\n".join(lines)
