from __future__ import annotations

import os
from typing import Any, Dict

from .models import SkillCategory, SkillDef, SkillResult, SkillRiskLevel


def register(registry: Any) -> None:
    registry.register(SkillDef(
        name="env_checker",
        description="检查当前运行环境信息，包括Python版本、操作系统、已安装包等",
        category=SkillCategory.SYSTEM,
        risk_level=SkillRiskLevel.SAFE,
        permission_level="allow",
        handler=_env_checker_handler,
        applicable_scenarios=["environment", "debug", "setup"],
        metadata=__import__("bridge.skills.models", fromlist=["SkillMetadata"]).SkillMetadata(
            tags=["environment", "python", "system", "debug"],
        ),
        input_schema={"type": "object", "properties": {"check_packages": {"type": "boolean", "default": True}}},
        output_schema={"type": "object", "properties": {"python_version": {"type": "string"}, "platform": {"type": "string"}}},
    ))


def _env_checker_handler(**kwargs: Any) -> SkillResult:
    import sys
    info = {
        "python_version": sys.version,
        "platform": sys.platform,
        "cwd": os.getcwd(),
    }
    if kwargs.get("check_packages", True):
        try:
            import pkg_resources
            installed = [str(d) for d in pkg_resources.working_set]
            info["installed_packages"] = len(installed)
            info["top_packages"] = installed[:20]
        except Exception:
            info["installed_packages"] = "unknown"
    return SkillResult.ok(output=str(info), data=info)
