from __future__ import annotations

import os
from typing import Any, Dict

from .models import SkillCategory, SkillDef, SkillResult, SkillRiskLevel


def register(registry: Any) -> None:
    registry.register(SkillDef(
        name="log_analyzer",
        description="分析日志文件，提取错误模式、警告统计和关键事件",
        category=SkillCategory.ANALYSIS,
        risk_level=SkillRiskLevel.LOW,
        permission_level="allow",
        handler=_log_analyzer_handler,
        applicable_scenarios=["logs", "debug", "analysis", "monitoring"],
        metadata=__import__("bridge.skills.models", fromlist=["SkillMetadata"]).SkillMetadata(
            tags=["logs", "debug", "analysis", "errors", "monitoring"],
        ),
        input_schema={"type": "object", "properties": {"path": {"type": "string"}, "max_lines": {"type": "integer", "default": 1000}}},
        output_schema={"type": "object", "properties": {"error_count": {"type": "integer"}, "warning_count": {"type": "integer"}}},
    ))


def _log_analyzer_handler(**kwargs: Any) -> SkillResult:
    path = kwargs.get("path", "")
    max_lines = kwargs.get("max_lines", 1000)
    if not path or not os.path.exists(path):
        return SkillResult.fail("Log file not found: " + str(path))
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[:max_lines]
    except Exception as e:
        return SkillResult.fail("Failed to read log: " + str(e))
    error_count = 0
    warning_count = 0
    info_count = 0
    error_patterns = []
    for line in lines:
        lower = line.lower()
        if "error" in lower or "exception" in lower or "traceback" in lower:
            error_count += 1
            if len(error_patterns) < 10:
                error_patterns.append(line.strip()[:200])
        elif "warn" in lower:
            warning_count += 1
        elif "info" in lower:
            info_count += 1
    summary = "Errors: " + str(error_count) + ", Warnings: " + str(warning_count) + ", Info: " + str(info_count) + ", Lines: " + str(len(lines))
    return SkillResult.ok(output=summary, data={
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "total_lines": len(lines),
        "error_patterns": error_patterns,
    })
