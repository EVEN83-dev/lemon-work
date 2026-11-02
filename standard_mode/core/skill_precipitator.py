# -*- coding: utf-8 -*-
"""364章 T4.1: 技能自沉淀 — 对话→Skill自动提取与注册"""

import json
import os
import re
import hashlib
from datetime import datetime
from typing import Dict, Optional


class SkillPrecipitator:
    def __init__(self, skills_dir: str = ""):
        if not skills_dir:
            skills_dir = os.path.join(os.getcwd(), "standard_mode", "core", "skills")
        self.skills_dir = os.path.expanduser(skills_dir)
        os.makedirs(self.skills_dir, exist_ok=True)
        self._index_path = os.path.join(self.skills_dir, "_precipitated_index.json")

    def extract_skill(self, conversation: str, skill_name: str = "",
                      category: str = "precipitated") -> Dict:
        if not conversation or len(conversation.strip()) < 50:
            return {"success": False, "error": "对话内容过短，无法提取技能"}

        name = skill_name or self._auto_name(conversation)
        if not re.match(r'^[a-z][a-z0-9_]*$', name):
            return {"success": False, "error": f"无效skill名称: {name}"}

        existing = os.path.join(self.skills_dir, f"{name}.py")
        if os.path.exists(existing):
            return {"success": False, "error": f"skill已存在: {name}.py",
                    "path": existing}

        steps = self._extract_steps(conversation)
        description = self._extract_description(conversation)
        code = self._generate_skill_code(name, description, steps, category)

        path = os.path.join(self.skills_dir, f"{name}.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)

        self._update_index(name, description, category)
        return {"success": True, "path": path, "name": name,
                "steps": len(steps), "description": description}

    def list_precipitated(self) -> list:
        if not os.path.isfile(self._index_path):
            return []
        with open(self._index_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _auto_name(self, text: str) -> str:
        h = hashlib.md5(text[:200].encode()).hexdigest()[:8]
        first_line = text.strip().split("\n")[0][:30]
        clean = re.sub(r'[^a-z0-9]', '_', first_line.lower())
        clean = re.sub(r'_+', '_', clean).strip('_')
        return f"auto_{clean[:15]}_{h}" if clean else f"auto_skill_{h}"

    def _extract_steps(self, text: str) -> list:
        steps = []
        for line in text.split("\n"):
            line = line.strip()
            if re.match(r'^\d+[\.\)]\s', line):
                steps.append(line)
            elif line.startswith("- ") and len(line) > 5:
                steps.append(line)
        return steps[:20]

    def _extract_description(self, text: str) -> str:
        first_lines = text.strip().split("\n")[:3]
        return " ".join(l.strip() for l in first_lines if l.strip())[:200]

    def _generate_skill_code(self, name: str, desc: str, steps: list,
                             category: str) -> str:
        steps_code = json.dumps(steps, ensure_ascii=False, indent=4)
        return f'''# -*- coding: utf-8 -*-
"""Skill: {name} — 自动沉淀技能"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {{
    "name": "{name}",
    "description": "{desc}",
    "category": "{category}",
    "version": "1.0.0",
    "precipitated": True,
}}

STEPS = {steps_code}


def execute(task: str = "", **kwargs) -> SkillResult:
    if not task:
        return SkillResult(success=False, error="task 参数为空")
    output_lines = [f"[{name}] 执行任务: {{task}}"]
    for i, step in enumerate(STEPS, 1):
        output_lines.append(f"  步骤{{i}}: {{step}}")
    return SkillResult(
        success=True,
        output="\\n".join(output_lines),
        data={{"task": task, "steps": len(STEPS)}},
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="{name}",
        description=METADATA["description"],
        parameters={{
            "type": "object",
            "properties": {{
                "task": {{"type": "string", "description": "任务描述"}},
            }},
            "required": ["task"],
        }},
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata():
    return METADATA
'''

    def precipitate_from_tools(self, goal: str, tool_calls: list,
                               result: str, engine: str = "",
                               trace_fh=None) -> Dict:
        """T366.3: 从工具调用序列沉淀经验模板→向量记忆

        替代 engine_manager 内联逻辑；模板提炼/长度压缩/入记忆全部收进类内。
        """
        if not tool_calls or len(tool_calls) < 2:
            return {"success": False, "error": "工具调用数<2，不沉淀"}
        tool_seq = " -> ".join(tc.get("name", "") for tc in tool_calls)
        template = f"Goal: {goal[:100]}\nSteps: {tool_seq}\nResult: {result[:80]}"
        if len(template) > 500:
            template = template[:500]
        try:
            from standard_mode.core.memory_store import get_memory_store
            mstore = get_memory_store()
            mstore.save_conversation_summary(
                f"[skill_template] {goal[:50]}", template, engine)
        except Exception as e:
            return {"success": False, "error": str(e)}
        if trace_fh:
            try:
                trace_fh.write(f"[SKILL_PRECIPITATOR] precipitated 1 template: {tool_seq[:80]}\n")
            except Exception:
                pass
        return {"success": True, "tool_seq": tool_seq, "template_len": len(template)}

    def _update_index(self, name: str, desc: str, category: str):
        index = self.list_precipitated()
        index.append({
            "name": name, "description": desc, "category": category,
            "created_at": datetime.now().isoformat(),
        })
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
