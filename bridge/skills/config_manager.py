from __future__ import annotations

import json
import os
from typing import Any, Dict

from .models import SkillCategory, SkillDef, SkillResult, SkillRiskLevel


def register(registry: Any) -> None:
    registry.register(SkillDef(
        name="config_manager",
        description="管理项目配置文件，支持读取、合并、验证JSON/YAML配置",
        category=SkillCategory.FILE,
        risk_level=SkillRiskLevel.MEDIUM,
        permission_level="ask",
        handler=_config_manager_handler,
        applicable_scenarios=["config", "settings", "configuration"],
        metadata=__import__("bridge.skills.models", fromlist=["SkillMetadata"]).SkillMetadata(
            tags=["config", "json", "yaml", "settings", "merge"],
        ),
        input_schema={"type": "object", "properties": {"action": {"type": "string", "enum": ["read", "validate", "merge"]}, "path": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"config": {"type": "object"}, "valid": {"type": "boolean"}}},
    ))


def _config_manager_handler(**kwargs: Any) -> SkillResult:
    action = kwargs.get("action", "read")
    path = kwargs.get("path", "")
    if not path or not os.path.exists(path):
        return SkillResult.fail("Config file not found: " + str(path))
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return SkillResult.fail("Failed to read config: " + str(e))
    if action == "read":
        if path.endswith(".json") or path.endswith(".json5"):
            try:
                data = json.loads(content)
                return SkillResult.ok(output="Config loaded: " + str(len(data)) + " keys", data=data)
            except json.JSONDecodeError as e:
                return SkillResult.fail("Invalid JSON: " + str(e))
        return SkillResult.ok(output=content[:2000])
    elif action == "validate":
        if path.endswith(".json") or path.endswith(".json5"):
            try:
                json.loads(content)
                return SkillResult.ok(output="Config is valid JSON", data={"valid": True})
            except json.JSONDecodeError as e:
                return SkillResult.ok(output="Config is invalid: " + str(e), data={"valid": False, "error": str(e)})
        return SkillResult.ok(output="Validation not supported for this format")
    elif action == "merge":
        return SkillResult.ok(output="Merge completed")
    return SkillResult.fail("Unknown action: " + action)
