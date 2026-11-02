from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class SkillCategory:
    FILE = "file"
    CODE = "code"
    SYSTEM = "system"
    NETWORK = "network"
    ANALYSIS = "analysis"
    COMMUNICATION = "communication"
    UTILITY = "utility"
    CUSTOM = "custom"


class SkillRiskLevel:
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SkillMetadata:
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    min_engine_version: str = ""
    platforms: List[str] = field(default_factory=lambda: ["pc", "mobile"])
    usage_count: int = 0
    success_rate: float = 1.0
    avg_execution_time_ms: float = 0.0
    last_updated: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "dependencies": self.dependencies,
            "minEngineVersion": self.min_engine_version,
            "platforms": self.platforms,
            "usageCount": self.usage_count,
            "successRate": self.success_rate,
            "avgExecutionTimeMs": self.avg_execution_time_ms,
            "lastUpdated": self.last_updated,
        }


@dataclass
class SkillResult:
    success: bool = False
    output: str = ""
    error: str = ""
    data: Any = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "success": self.success,
            "output": self.output,
            "durationMs": self.duration_ms,
        }
        if self.error:
            result["error"] = self.error
        if self.data is not None:
            result["data"] = self.data
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @staticmethod
    def ok(output: str, data: Any = None, duration_ms: float = 0.0,
           metadata: Optional[Dict[str, Any]] = None) -> SkillResult:
        return SkillResult(success=True, output=output, data=data,
                           duration_ms=duration_ms, metadata=metadata or {})

    @staticmethod
    def fail(error: str, output: str = "", data: Any = None,
             metadata: Optional[Dict[str, Any]] = None) -> SkillResult:
        return SkillResult(success=False, error=error, output=output,
                           data=data, metadata=metadata or {})


@dataclass
class SkillInvocation:
    params: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "params": self.params,
            "context": self.context,
            "sessionId": self.session_id,
        }


@dataclass
class SkillDef:
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    handler: Optional[Callable] = None
    category: str = SkillCategory.UTILITY
    risk_level: str = SkillRiskLevel.LOW
    requires_confirm: bool = False
    timeout: int = 30
    version: str = "1.0.0"
    min_framework_version: str = ""
    deprecated: bool = False
    deprecation_message: str = ""
    examples: List[str] = field(default_factory=list)
    metadata: SkillMetadata = field(default_factory=SkillMetadata)
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    permission_level: str = "ask"
    applicable_scenarios: List[str] = field(default_factory=list)
    fallback_skill: str = ""
    chain_skills: List[str] = field(default_factory=list)

    def to_tool_definition(self) -> Dict[str, Any]:
        # 修复: DeepSeek/OpenAI API 要求 parameters 必须是 type:object 的 JSON Schema
        # 空 dict 或缺失 type 字段会导致 400 Bad Request
        params = self.parameters
        if not params or not isinstance(params, dict) or not params.get("type"):
            params = {"type": "object", "properties": params if isinstance(params, dict) else {}}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "riskLevel": self.risk_level,
            "requiresConfirm": self.requires_confirm,
            "timeout": self.timeout,
            "version": self.version,
            "deprecated": self.deprecated,
            "deprecationMessage": self.deprecation_message,
            "parameters": self.parameters,
            "examples": self.examples,
            "metadata": self.metadata.to_dict(),
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "permissionLevel": self.permission_level,
            "applicableScenarios": self.applicable_scenarios,
            "fallbackSkill": self.fallback_skill,
            "chainSkills": self.chain_skills,
        }

    def get_full_description(self) -> str:
        risk_label = {
            SkillRiskLevel.SAFE: "[安全]",
            SkillRiskLevel.LOW: "[低风险]",
            SkillRiskLevel.MEDIUM: "[中风险]",
            SkillRiskLevel.HIGH: "[高风险]",
            SkillRiskLevel.CRITICAL: "[极高风险]",
        }
        label = risk_label.get(self.risk_level, "[未知]")
        return f"{self.description} {label}"

    def update_stats(self, execution_time_ms: float, success: bool) -> None:
        m = self.metadata
        m.usage_count += 1
        m.avg_execution_time_ms = (
            m.avg_execution_time_ms * 0.9 + execution_time_ms * 0.1
        )
        if success:
            m.success_rate = min(1.0, m.success_rate + 0.01)
        else:
            m.success_rate = max(0.0, m.success_rate - 0.05)
        m.last_updated = time.time()


_VALID_CATEGORIES = {
    "file", "code", "system", "network", "analysis",
    "communication", "utility", "custom", "math", "research",
    "finance", "vision", "automation", "office", "debate",
    "image", "productivity", "development", "deployment",
    "document", "general",
}

_VALID_RISK_LEVELS = {"safe", "low", "medium", "high", "critical"}

_REQUIRED_DECLARATION_FIELDS = {"name", "description", "category"}

_RECOMMENDED_DECLARATION_FIELDS = {"version", "risk_level", "timeout", "dependencies"}


@dataclass
class SkillDeclaration:
    name: str = ""
    description: str = ""
    category: str = ""
    version: str = "1.0.0"
    risk_level: str = "low"
    timeout: int = 30
    dependencies: List[str] = field(default_factory=list)
    applicable_scenarios: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    fallback_skill: str = ""
    deprecated: bool = False
    deprecation_message: str = ""
    permission_level: str = "ask"
    namespace: str = ""
    source_file: str = ""
    inputs: str = ""
    outputs: str = ""
    capabilities: List[str] = field(default_factory=list)

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.name:
            errors.append("name is required")
        elif not re.match(r'^[a-z][a-z0-9_]*$', self.name):
            errors.append("name must be lowercase_snake_case, got: " + self.name)
        if not self.description:
            errors.append("description is required for '" + self.name + "'")
        elif len(self.description) < 10:
            errors.append("description too short (<10 chars) for '" + self.name + "'")
        if self.category and self.category not in _VALID_CATEGORIES:
            errors.append("invalid category '" + self.category + "' for '" + self.name + "'")
        if self.risk_level and self.risk_level not in _VALID_RISK_LEVELS:
            errors.append("invalid risk_level '" + self.risk_level + "' for '" + self.name + "'")
        if self.timeout <= 0:
            errors.append("timeout must be > 0 for '" + self.name + "'")
        return errors

    def to_skill_def(self, handler: Optional[Callable] = None) -> SkillDef:
        return SkillDef(
            name=self.name,
            description=self.description,
            category=self.category or SkillCategory.UTILITY,
            risk_level=self.risk_level,
            timeout=self.timeout,
            version=self.version,
            deprecated=self.deprecated,
            deprecation_message=self.deprecation_message,
            examples=self.examples,
            applicable_scenarios=self.applicable_scenarios,
            fallback_skill=self.fallback_skill,
            permission_level=self.permission_level,
            metadata=SkillMetadata(
                version=self.version,
                tags=self.tags,
                dependencies=self.dependencies,
            ),
            handler=handler,
        )

    @staticmethod
    def from_yaml_frontmatter(text: str, source_file: str = "") -> "SkillDeclaration":
        decl = SkillDeclaration(source_file=source_file)
        if not text:
            return decl
        lines = text.strip().split('\n')
        for line in lines:
            if ':' not in line:
                continue
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip()
            if key == 'name':
                decl.name = value
            elif key == 'description':
                decl.description = value
            elif key == 'category':
                decl.category = value
            elif key == 'version':
                decl.version = value
            elif key == 'risk_level':
                decl.risk_level = value
            elif key == 'timeout':
                try:
                    decl.timeout = int(value)
                except ValueError:
                    pass
            elif key == 'dependencies':
                decl.dependencies = [v.strip() for v in value.split(',') if v.strip()]
            elif key == 'applicable_scenarios':
                decl.applicable_scenarios = [v.strip() for v in value.split(',') if v.strip()]
            elif key == 'tags':
                decl.tags = [v.strip() for v in value.split(',') if v.strip()]
            elif key == 'fallback_skill':
                decl.fallback_skill = value
            elif key == 'deprecated':
                decl.deprecated = value.lower() in ('true', 'yes', '1')
            elif key == 'deprecation_message':
                decl.deprecation_message = value
            elif key == 'permission_level':
                decl.permission_level = value
            elif key == 'namespace':
                decl.namespace = value
            elif key == 'inputs':
                decl.inputs = value
            elif key == 'outputs':
                decl.outputs = value
            elif key == 'capabilities':
                decl.capabilities = [v.strip() for v in value.split(',') if v.strip()]
            elif key == 'examples':
                decl.examples = [v.strip() for v in value.split('|') if v.strip()]
        return decl


def parse_skill_md(filepath: str) -> Optional[SkillDeclaration]:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        logger.warning("Failed to read SKILL.md at %s: %s", filepath, e)
        return None

    if not content.startswith('---'):
        return None

    end_marker = content.find('---', 3)
    if end_marker == -1:
        return None

    frontmatter = content[3:end_marker].strip()
    decl = SkillDeclaration.from_yaml_frontmatter(frontmatter, source_file=filepath)

    errors = decl.validate()
    if errors:
        logger.warning("SKILL.md validation errors at %s: %s", filepath, errors)

    return decl
