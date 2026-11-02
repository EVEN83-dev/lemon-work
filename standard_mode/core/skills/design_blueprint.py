# -*- coding: utf-8 -*-
"""
Skill: design_blueprint — 架构图生成（蒸馏自 MiMo Code）
=========================================================
生成 Mermaid.js 架构图：系统架构图/流程图/时序图/类图/ER图/状态图。
"""

import json
import os
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "design_blueprint",
    "description": "生成 Mermaid.js 架构图：系统架构图/流程图/时序图/类图/ER图/状态图。蒸馏自 MiMo Code design-blueprint。",
    "category": "visual",
    "version": "1.0.0",
}


def execute(
    diagram_type: str = "architecture",
    description: str = "",
    components: str = "[]",
    style: str = "default",
) -> SkillResult:
    """生成 Mermaid.js 架构图

    Args:
        diagram_type: architecture/flowchart/sequence/class/er/state
        description: 图表描述（自然语言）
        components: JSON 组件列表
        style: 样式
    """
    if not description and components == "[]":
        return SkillResult(success=False, error="description 或 components 必须有一个")

    try:
        comps = json.loads(components) if isinstance(components, str) else components
    except json.JSONDecodeError:
        comps = []

    try:
        # ===== 系统架构图 =====
        if diagram_type == 'architecture':
            lines = ["graph TD"]
            if comps:
                for c in comps[:15]:
                    name = c.get('name', 'Component') if isinstance(c, dict) else str(c)
                    ctype = c.get('type', 'service') if isinstance(c, dict) else 'service'
                    icon_map = {'service': '🔧', 'database': '🗄️', 'queue': '📬', 'api': '🌐', 'ui': '🖥️'}
                    icon = icon_map.get(ctype, '📦')
                    safe_name = name.replace(' ', '_').replace('-', '_')
                    lines.append(f"    {safe_name}[{icon} {name}]")
                # 连线
                for i in range(len(comps) - 1):
                    n1 = (comps[i].get('name', 'C') if isinstance(comps[i], dict) else str(comps[i])).replace(' ', '_').replace('-', '_')
                    n2 = (comps[i+1].get('name', 'C') if isinstance(comps[i+1], dict) else str(comps[i+1])).replace(' ', '_').replace('-', '_')
                    lines.append(f"    {n1} --> {n2}")
            else:
                lines.append("    Client[客户端] --> Gateway[API 网关]")
                lines.append("    Gateway --> Service[业务服务]")
                lines.append("    Service --> DB[(数据库)]")
                lines.append("    Service --> Cache[(缓存)]")

        # ===== 流程图 =====
        elif diagram_type == 'flowchart':
            lines = ["graph TD"]
            if comps:
                for i, c in enumerate(comps[:10]):
                    step = c.get('name', c) if isinstance(c, dict) else str(c)
                    safe = f"S{i}"
                    lines.append(f"    {safe}[{step}]")
                for i in range(len(comps[:10]) - 1):
                    lines.append(f"    S{i} --> S{i+1}")
            else:
                lines.append("    A[开始] --> B{判断}")
                lines.append("    B -->|是| C[执行]")
                lines.append("    B -->|否| D[跳过]")
                lines.append("    C --> E[结束]")
                lines.append("    D --> E")

        # ===== 时序图 =====
        elif diagram_type == 'sequence':
            lines = ["sequenceDiagram"]
            actors = set()
            if comps:
                for c in comps[:8]:
                    if isinstance(c, dict):
                        a1 = c.get('from', 'A')
                        a2 = c.get('to', 'B')
                        msg = c.get('message', '')
                        actors.add(a1)
                        actors.add(a2)
                        lines.append(f"    {a1}->>{a2}: {msg}")
            else:
                lines.append("    participant Client")
                lines.append("    participant Server")
                lines.append("    participant DB")
                lines.append("    Client->>Server: 请求")
                lines.append("    Server->>DB: 查询")
                lines.append("    DB-->>Server: 数据")
                lines.append("    Server-->>Client: 响应")

        # ===== 类图 =====
        elif diagram_type == 'class':
            lines = ["classDiagram"]
            if comps:
                for c in comps[:8]:
                    if isinstance(c, dict):
                        cls_name = c.get('name', 'Class')
                        attrs = c.get('attributes', [])
                        methods = c.get('methods', [])
                        lines.append(f"    class {cls_name} {{")
                        for a in attrs[:5]:
                            lines.append(f"        {a}")
                        for m in methods[:5]:
                            lines.append(f"        {m}")
                        lines.append("    }")
            else:
                lines.append("    class Animal {")
                lines.append("        +String name")
                lines.append("        +speak()")
                lines.append("    }")
                lines.append("    class Dog {")
                lines.append("        +fetch()")
                lines.append("    }")
                lines.append("    Animal <|-- Dog")

        # ===== ER 图 =====
        elif diagram_type == 'er':
            lines = ["erDiagram"]
            if comps:
                for c in comps[:8]:
                    if isinstance(c, dict):
                        entity = c.get('entity', 'TABLE')
                        fields = c.get('fields', [])
                        lines.append(f"    {entity} {{")
                        for f in fields[:6]:
                            lines.append(f"        {f}")
                        lines.append("    }")
            else:
                lines.append("    USER {")
                lines.append("        int id PK")
                lines.append("        string name")
                lines.append("        string email")
                lines.append("    }")
                lines.append("    ORDER {")
                lines.append("        int id PK")
                lines.append("        int user_id FK")
                lines.append("        float amount")
                lines.append("    }")
                lines.append("    USER ||--o{ ORDER : has")

        # ===== 状态图 =====
        elif diagram_type == 'state':
            lines = ["stateDiagram-v2"]
            if comps:
                for i, c in enumerate(comps[:10]):
                    state = c.get('name', c) if isinstance(c, dict) else str(c)
                    lines.append(f"    {state}")
                for i in range(len(comps[:10]) - 1):
                    s1 = comps[i].get('name', str(comps[i])) if isinstance(comps[i], dict) else str(comps[i])
                    s2 = comps[i+1].get('name', str(comps[i+1])) if isinstance(comps[i+1], dict) else str(comps[i+1])
                    lines.append(f"    {s1} --> {s2}")
            else:
                lines.append("    [*] --> Idle")
                lines.append("    Idle --> Processing : start")
                lines.append("    Processing --> Done : complete")
                lines.append("    Processing --> Error : fail")
                lines.append("    Error --> Idle : retry")
                lines.append("    Done --> [*]")

        else:
            return SkillResult(success=False, error=f"未知 diagram_type: {diagram_type}")

        mermaid_code = "\n".join(lines)
        return SkillResult(
            success=True,
            output=f"Mermaid 图已生成（{diagram_type}）:\n```mermaid\n{mermaid_code}\n```",
            data={'mermaid': mermaid_code, 'diagram_type': diagram_type},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"架构图生成失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="design_blueprint",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "diagram_type": {"type": "string", "enum": ["architecture", "flowchart", "sequence", "class", "er", "state"], "description": "图表类型"},
                "description": {"type": "string", "description": "图表描述"},
                "components": {"type": "string", "description": "JSON 组件列表", "default": "[]"},
                "style": {"type": "string", "description": "样式", "default": "default"},
            },
            "required": ["diagram_type"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=15,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
