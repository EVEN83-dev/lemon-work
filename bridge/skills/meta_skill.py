from __future__ import annotations

import os
import json
import re
import time
from typing import Any, Dict, List, Optional

from .models import SkillDef, SkillResult, SkillDeclaration

_DECL_DIR = os.path.join(os.path.dirname(__file__), "declarations")


def execute(
    task_description: str,
    skill_name: str = "",
    category: str = "utility",
    capabilities: str = "",
    approve: bool = False,
    **kwargs,
) -> SkillResult:
    if not task_description.strip():
        return SkillResult.fail("task_description is required")

    skill_name = skill_name or _infer_skill_name(task_description)
    if not re.match(r'^[a-z][a-z0-9_]*$', skill_name):
        return SkillResult.fail("Invalid skill_name '" + skill_name + "'. Must be lowercase_snake_case.")

    caps = [c.strip() for c in capabilities.split(",") if c.strip()] if capabilities else _infer_capabilities(task_description)
    description = task_description[:200]

    code = _generate_skill_code(skill_name, description, category, caps)
    md_content = _generate_skill_md(skill_name, description, category, caps)

    if approve:
        md_path = os.path.join(_DECL_DIR, skill_name + ".md")
        draft_dir = os.path.join(_DECL_DIR, "drafts")
        os.makedirs(draft_dir, exist_ok=True)
        draft_path = os.path.join(draft_dir, skill_name + ".py")
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        with open(draft_path, 'w', encoding='utf-8') as f:
            f.write(code)
        return SkillResult.ok(
            output="Skill '" + skill_name + "' saved as draft. Awaiting human approval to register.",
            data={
                "skill_name": skill_name,
                "status": "draft",
                "declaration_path": md_path,
                "code_path": draft_path,
                "needs_approval": True,
            },
        )

    return SkillResult.ok(
        output="Skill '" + skill_name + "' generated (not saved - set approve=True to save).",
        data={
            "skill_name": skill_name,
            "status": "preview",
            "generated_code": code,
            "generated_md": md_content,
            "capabilities": caps,
        },
    )


def _infer_skill_name(description: str) -> str:
    words = re.findall(r'[a-zA-Z]+', description.lower())
    if not words:
        return "custom_skill"
    return "_".join(words[:3])


def _infer_capabilities(description: str) -> List[str]:
    keywords = {
        "search": ["search", "find", "lookup"],
        "analyze": ["analyze", "review", "assess", "evaluate"],
        "generate": ["generate", "create", "build", "produce"],
        "transform": ["transform", "convert", "format", "refactor"],
        "validate": ["validate", "check", "verify", "test"],
        "report": ["report", "summarize", "document"],
    }
    caps = []
    desc_lower = description.lower()
    for cap, triggers in keywords.items():
        if any(t in desc_lower for t in triggers):
            caps.append(cap)
    if not caps:
        caps = ["process"]
    return caps


def _generate_skill_code(name: str, description: str, category: str, capabilities: List[str]) -> str:
    cap_args = ", ".join(c + ": str = ''" for c in capabilities[:5])
    cap_checks = "\n    ".join(
        "if " + c + ":\n      results['" + c + "'] = _process_" + c + "(" + c + ")"
        for c in capabilities[:5]
    )
    result_parts = ", ".join("'" + c + ": ' + str(results.get('" + c + "', 'N/A'))" for c in capabilities[:5])

    lines = [
        "from bridge.skills.models import SkillResult, SkillDef",
        "",
        "",
        "def execute(task: str = '', " + cap_args + ", **kwargs) -> SkillResult:",
        "    if not task.strip():",
        "        return SkillResult.fail('task is required')",
        "    results = {}",
        "    " + cap_checks,
        "    output = '" + name + " result: ' + ', '.join([" + result_parts + "])",
        "    return SkillResult.ok(output=output, data=results)",
        "",
    ]
    for c in capabilities[:5]:
        lines.append("")
        lines.append("def _process_" + c + "(input_str: str) -> str:")
        lines.append("    if not input_str:")
        lines.append("        return 'no input'")
        lines.append("    return 'processed: ' + input_str[:100]")

    lines.append("")
    lines.append("")
    lines.append("def register(registry) -> None:")
    lines.append("    registry.register(SkillDef(")
    lines.append("        name='" + name + "',")
    lines.append("        description='" + description.replace("'", "\\\\'") + "',")
    lines.append("        category='" + category + "',")
    lines.append("        handler=execute,")
    lines.append("        parameters={'type': 'object', 'properties': {")
    lines.append("            'task': {'type': 'string', 'description': 'Task to perform'},")
    for c in capabilities[:5]:
        lines.append("            '" + c + "': {'type': 'string', 'description': '" + c.capitalize() + " input'},")
    lines.append("        }, 'required': ['task']},")
    lines.append("    ))")
    lines.append("")

    return "\n".join(lines)


def _generate_skill_md(name: str, description: str, category: str, capabilities: List[str]) -> str:
    lines = [
        "---",
        "name: " + name,
        "description: " + description,
        "category: " + category,
        "version: 0.1.0",
        "risk_level: low",
        "timeout: 30",
        "dependencies: ",
        "needs_llm: false",
        "inputs: task: str",
        "outputs: results: dict",
        "capabilities: " + ", ".join(capabilities),
        "namespace: bridge",
        "tags: " + ", ".join(capabilities),
        "status: draft",
        "---",
        "",
        "# " + name,
        "",
        description + ".",
        "",
        "## Capabilities",
    ]
    for c in capabilities:
        lines.append("- " + c)
    lines.append("")
    return "\n".join(lines)


def register(registry) -> None:
    registry.register(SkillDef(
        name="meta_skill",
        description="Generate new skill drafts from task descriptions. Set approve=True to save as draft for human approval.",
        category="system",
        parameters={
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Description of the task the new skill should handle",
                },
                "skill_name": {
                    "type": "string",
                    "description": "Optional name for the skill (auto-inferred if empty)",
                },
                "category": {
                    "type": "string",
                    "description": "Skill category",
                },
                "capabilities": {
                    "type": "string",
                    "description": "Comma-separated capability list",
                },
                "approve": {
                    "type": "boolean",
                    "description": "If true, save draft to declarations/ for human review",
                },
            },
            "required": ["task_description"],
        },
        handler=execute,
        timeout=30,
    ))
