from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any


@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    data: Optional[dict] = None
    metadata: Optional[dict] = None


@dataclass
class ToolContext:
    session_id: str = ""
    message_id: str = ""
    user_id: str = ""
    cancelled: bool = False
    progress_callback: Optional[Callable] = None
    permission_callback: Optional[Callable] = None

    def check_cancelled(self) -> bool:
        return self.cancelled

    def report_progress(self, step: str, detail: str = "") -> None:
        if self.progress_callback is not None:
            self.progress_callback(step, detail)


@dataclass
class ToolDef:
    id: str
    description: str
    parameters: dict
    category: str
    execute: Callable[[dict, ToolContext], ToolResult]
    enabled: bool = True
    requires_confirm: bool = False
    timeout: int = 30


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)


_TYPE_CHECKERS: Dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


class ParameterValidator:
    def validate(self, args: dict, schema: dict) -> ValidationResult:
        errors: List[str] = []
        self._validate_object(args, schema, errors, path="$")
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def _validate_object(self, obj: dict, schema: dict, errors: List[str], path: str) -> None:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if key not in obj:
                errors.append(f"{path}.{key}: required field missing")
        for key, value in obj.items():
            prop_schema = properties.get(key)
            if prop_schema is not None:
                self._validate_value(value, prop_schema, errors, f"{path}.{key}")
            elif properties:
                pass

    def _validate_value(self, value: Any, schema: dict, errors: List[str], path: str) -> None:
        expected_type = schema.get("type")
        if expected_type is not None:
            checker = _TYPE_CHECKERS.get(expected_type)
            if checker is not None and not checker(value):
                errors.append(f"{path}: expected type '{expected_type}', got '{type(value).__name__}'")
                return

        if value is None:
            return

        if expected_type == "string":
            self._validate_string(value, schema, errors, path)
        elif expected_type in ("number", "integer"):
            self._validate_number(value, schema, errors, path)
        elif expected_type == "array":
            self._validate_array(value, schema, errors, path)
        elif expected_type == "object":
            self._validate_object(value, schema, errors, path)

        enum_values = schema.get("enum")
        if enum_values is not None and value not in enum_values:
            errors.append(f"{path}: value must be one of {enum_values}")

    def _validate_string(self, value: str, schema: dict, errors: List[str], path: str) -> None:
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            errors.append(f"{path}: string length {len(value)} < minLength {min_length}")
        max_length = schema.get("maxLength")
        if max_length is not None and len(value) > max_length:
            errors.append(f"{path}: string length {len(value)} > maxLength {max_length}")

    def _validate_number(self, value: Any, schema: dict, errors: List[str], path: str) -> None:
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: value {value} < minimum {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            errors.append(f"{path}: value {value} > maximum {maximum}")

    def _validate_array(self, value: list, schema: dict, errors: List[str], path: str) -> None:
        items_schema = schema.get("items")
        if items_schema is not None:
            for i, item in enumerate(value):
                self._validate_value(item, items_schema, errors, f"{path}[{i}]")


class ToolRegistry:
    def __init__(self, auto_register_first_party: bool = True) -> None:
        self._tools: Dict[str, ToolDef] = {}
        self._validator: ParameterValidator = ParameterValidator()
        self._lock: threading.Lock = threading.Lock()
        if auto_register_first_party:
            self._auto_register_first_party()

    def _auto_register_first_party(self) -> None:
        try:
            from bridge.tools.first_party_tools import batch_register
            batch_register(self)
        except Exception:
            pass

    def register(self, tool: ToolDef) -> bool:
        with self._lock:
            if tool.id in self._tools:
                return False
            self._tools[tool.id] = tool
            return True

    def unregister(self, tool_id: str) -> bool:
        with self._lock:
            return self._tools.pop(tool_id, None) is not None

    def get(self, tool_id: str) -> Optional[ToolDef]:
        with self._lock:
            return self._tools.get(tool_id)

    def list(self, category: Optional[str] = None, enabled_only: bool = False) -> List[ToolDef]:
        with self._lock:
            tools = list(self._tools.values())
        result: List[ToolDef] = []
        for t in tools:
            if category is not None and t.category != category:
                continue
            if enabled_only and not t.enabled:
                continue
            result.append(t)
        return result

    def query(self, keyword: str) -> List[ToolDef]:
        keyword_lower = keyword.lower()
        with self._lock:
            tools = list(self._tools.values())
        return [
            t for t in tools
            if keyword_lower in t.id.lower() or keyword_lower in t.description.lower()
        ]

    def enable(self, tool_id: str) -> bool:
        with self._lock:
            tool = self._tools.get(tool_id)
            if tool is None:
                return False
            tool.enabled = True
            return True

    def disable(self, tool_id: str) -> bool:
        with self._lock:
            tool = self._tools.get(tool_id)
            if tool is None:
                return False
            tool.enabled = False
            return True

    def categories(self) -> List[str]:
        with self._lock:
            cats = {t.category for t in self._tools.values()}
        return sorted(cats)

    def undo_last(self, n: int = 1) -> list:
        try:
            from bridge.tools.first_party_tools import undo_last as _undo
            return _undo(n)
        except Exception:
            return []

    def execute_tool(
        self, tool_id: str, args: dict, ctx: Optional[ToolContext] = None
    ) -> ToolResult:
        if ctx is None:
            ctx = ToolContext()

        with self._lock:
            tool = self._tools.get(tool_id)
        if tool is None:
            return ToolResult(success=False, error=f"Tool '{tool_id}' not found")

        if not tool.enabled:
            return ToolResult(success=False, error=f"Tool '{tool_id}' is disabled")

        validation = self._validator.validate(args, tool.parameters)
        if not validation.valid:
            return ToolResult(success=False, error="; ".join(validation.errors))

        if ctx.check_cancelled():
            return ToolResult(success=False, error="Execution cancelled before start")

        if tool.requires_confirm and ctx.permission_callback is not None:
            try:
                approved = ctx.permission_callback(tool_id, args)
                if not approved:
                    return ToolResult(success=False, error="Permission denied by user")
            except Exception as e:
                return ToolResult(success=False, error=f"Permission check failed: {e}")

        try:
            result = tool.execute(args, ctx)
            return result
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class SkillToToolAdapter:
    @staticmethod
    def skill_to_tool(skill_def: Any, handler: Callable[[dict, ToolContext], ToolResult]) -> ToolDef:
        name = getattr(skill_def, "name", None) or (skill_def.get("name") if isinstance(skill_def, dict) else "")
        description = getattr(skill_def, "description", None) or (skill_def.get("description") if isinstance(skill_def, dict) else "")
        parameters = getattr(skill_def, "parameters", None) or (skill_def.get("parameters") if isinstance(skill_def, dict) else {})
        category = getattr(skill_def, "category", None) or (skill_def.get("category") if isinstance(skill_def, dict) else "skill")
        requires_confirm = getattr(skill_def, "requires_confirm", None) or (skill_def.get("requires_confirm") if isinstance(skill_def, dict) else False)
        timeout = getattr(skill_def, "timeout", None) or (skill_def.get("timeout") if isinstance(skill_def, dict) else 30)

        return ToolDef(
            id=name,
            description=description,
            parameters=parameters,
            category=category,
            execute=handler,
            requires_confirm=bool(requires_confirm),
            timeout=int(timeout),
        )

    @staticmethod
    def batch_register_skills(tool_registry: 'ToolRegistry', skills_registry: Any) -> int:
        count = 0
        for skill in skills_registry.list_skills():
            if skill.handler is None:
                continue
            if skill.deprecated:
                continue

            def _make_handler(s):
                def _handler(args: dict, ctx: ToolContext) -> ToolResult:
                    try:
                        result = skills_registry.execute(s.name, args)
                        if isinstance(result, object) and hasattr(result, 'success'):
                            return ToolResult(
                                success=result.success,
                                output=getattr(result, 'output', ''),
                                error=getattr(result, 'error', ''),
                                data=getattr(result, 'data', None),
                            )
                        return ToolResult(success=True, output=str(result))
                    except Exception as e:
                        return ToolResult(success=False, error=str(e))
                return _handler

            handler = _make_handler(skill)
            tool = SkillToToolAdapter.skill_to_tool(skill, handler)
            if tool_registry.register(tool):
                count += 1
        return count

    @staticmethod
    def register_meta_tools(tool_registry: 'ToolRegistry', skills_registry: Any) -> int:
        count = 0

        def _query_skill_handler(args: dict, ctx: ToolContext) -> ToolResult:
            query = args.get("query", "")
            category = args.get("category", "")
            results = []
            for skill in skills_registry.list_skills(category=category if category else ""):
                if skill.deprecated:
                    continue
                sd = {
                    "name": skill.name,
                    "description": skill.description,
                    "category": skill.category,
                    "has_handler": skill.handler is not None,
                }
                if query and query.lower() not in skill.name.lower() and query.lower() not in skill.description.lower():
                    continue
                results.append(sd)
            return ToolResult(success=True, output=str(len(results)) + " skills found", data={"skills": results})

        query_tool = ToolDef(
            id="query_skill",
            description="Query available skills by keyword or category. Returns list of matching skills.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword"},
                    "category": {"type": "string", "description": "Filter by category"},
                },
            },
            category="meta",
            execute=_query_skill_handler,
        )
        if tool_registry.register(query_tool):
            count += 1

        def _call_skill_handler(args: dict, ctx: ToolContext) -> ToolResult:
            skill_name = args.get("skill_name", "")
            skill_args = args.get("args", {})
            if not skill_name:
                return ToolResult(success=False, error="skill_name is required")
            result = skills_registry.execute(skill_name, skill_args)
            if isinstance(result, object) and hasattr(result, 'success'):
                return ToolResult(
                    success=result.success,
                    output=getattr(result, 'output', ''),
                    error=getattr(result, 'error', ''),
                    data=getattr(result, 'data', None),
                )
            return ToolResult(success=True, output=str(result))

        call_tool = ToolDef(
            id="call_skill",
            description="Execute a skill by name with given arguments.",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string", "description": "Name of the skill to invoke"},
                    "args": {"type": "object", "description": "Arguments to pass to the skill"},
                },
                "required": ["skill_name"],
            },
            category="meta",
            execute=_call_skill_handler,
        )
        if tool_registry.register(call_tool):
            count += 1

        return count
