"""
C5: End-to-End Integration Chain

Wires: sandbox → builtin_tools → ToolRegistry → memory_system →
       local_embedder → reflection → tool_history → agent_loop

Provides a single `IntegrationChain` class that initializes all C1-C6
components and connects them to the existing agent_loop.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from bridge.tools.tool_def import ToolRegistry, ToolDef, ToolResult, ToolContext
from bridge.tools.builtin_tools import register_builtin_tools
from bridge.sandbox import CommandSandbox, SandboxPolicy
from bridge.core.memory_system import MemorySystem
from bridge.services.local_embedder import LocalEmbedderService
from bridge.core.reflection import ReflectionLoop
from bridge.core.tool_history import ToolHistory
from bridge.eval import EvalRunner, SAMPLE_TASKS

logger = logging.getLogger(__name__)


class IntegrationChain:
    def __init__(
        self,
        session_id: str = "default",
        user_id: str = "default",
        project_path: str = "",
        sandbox_policy: Optional[SandboxPolicy] = None,
        memory_system: Optional[MemorySystem] = None,
        reflection_output_dir: str = "",
        tool_history_dir: str = "",
        eval_output_dir: str = "",
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.project_path = project_path

        self._sandbox = CommandSandbox(sandbox_policy or SandboxPolicy())
        self._tool_registry = ToolRegistry()
        self._memory_system = memory_system or MemorySystem(
            session_id=session_id,
            user_id=user_id,
            project_path=project_path,
        )
        self._embedder = LocalEmbedderService()
        self._reflection = ReflectionLoop(
            memory_system=self._memory_system,
            output_dir=reflection_output_dir,
        )
        self._tool_history = ToolHistory(snapshot_dir=tool_history_dir)
        self._eval_runner = EvalRunner(output_dir=eval_output_dir)

        self._register_tools()
        logger.info("[IntegrationChain] All C1-C6 components initialized")

    @property
    def sandbox(self) -> CommandSandbox:
        return self._sandbox

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    @property
    def memory_system(self) -> MemorySystem:
        return self._memory_system

    @property
    def embedder(self) -> LocalEmbedderService:
        return self._embedder

    @property
    def reflection(self) -> ReflectionLoop:
        return self._reflection

    @property
    def tool_history(self) -> ToolHistory:
        return self._tool_history

    @property
    def eval_runner(self) -> EvalRunner:
        return self._eval_runner

    def _register_tools(self) -> None:
        n = register_builtin_tools(self._tool_registry)
        logger.info(f"[IntegrationChain] Registered {n} builtin tools")

        self._tool_registry.register(ToolDef(
            id="semantic_search",
            description="Search memory using TF-IDF semantic similarity",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "layer": {"type": "string", "description": "Memory layer: session/user/project/knowledge"},
                    "top_k": {"type": "integer", "description": "Number of results (default 5)"},
                },
                "required": ["query"],
            },
            category="memory",
            execute=self._semantic_search_tool,
            enabled=True,
            requires_confirm=False,
            timeout=10,
        ))

        self._tool_registry.register(ToolDef(
            id="memory_store",
            description="Store a key-value pair in memory",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Memory layer: session/user/project/knowledge"},
                    "key": {"type": "string", "description": "Memory key"},
                    "value": {"type": "string", "description": "Memory value"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                },
                "required": ["layer", "key", "value"],
            },
            category="memory",
            execute=self._memory_store_tool,
            enabled=True,
            requires_confirm=False,
            timeout=5,
        ))

        self._tool_registry.register(ToolDef(
            id="reflection_critique",
            description="Trigger self-reflection on the current task execution",
            parameters={
                "type": "object",
                "properties": {
                    "task_description": {"type": "string", "description": "What the task was about"},
                    "tool_calls_json": {"type": "string", "description": "JSON array of tool call records"},
                    "tool_results_json": {"type": "string", "description": "JSON array of tool result strings"},
                    "final_output": {"type": "string", "description": "Final output of the task"},
                },
                "required": ["task_description"],
            },
            category="reflection",
            execute=self._reflection_tool,
            enabled=True,
            requires_confirm=False,
            timeout=15,
        ))

        self._tool_registry.register(ToolDef(
            id="undo_tool_steps",
            description="Undo the last N file-modifying tool operations by restoring snapshots",
            parameters={
                "type": "object",
                "properties": {
                    "steps": {"type": "integer", "description": "Number of steps to undo (default 1)"},
                },
                "required": [],
            },
            category="tool_history",
            execute=self._undo_tool,
            enabled=True,
            requires_confirm=True,
            timeout=10,
        ))

    def execute_tool(
        self,
        tool_id: str,
        args: Dict[str, Any],
        ctx: Optional[ToolContext] = None,
    ) -> ToolResult:
        if ctx is None:
            ctx = ToolContext(session_id=self.session_id)

        entry_id = ""
        if tool_id in ("write_file", "edit_file", "create_file",
                        "delete_file", "replace_in_file", "apply_edit"):
            entry_id = self._tool_history.before_tool_call(tool_id, args)

        import time as _time
        start = _time.time()
        result = self._tool_registry.execute_tool(tool_id, args, ctx)
        duration_ms = int((_time.time() - start) * 1000)

        if entry_id:
            self._tool_history.after_tool_call(
                entry_id, tool_id, args,
                success=result.success,
                output=result.output[:500],
                duration_ms=duration_ms,
            )

        if tool_id in ("semantic_search", "memory_store", "reflection_critique", "undo_tool_steps"):
            pass
        elif result.success and result.output:
            try:
                self._memory_system.store(
                    layer="session",
                    key=f"tool_result:{tool_id}:{_time.time():.0f}",
                    value=result.output[:1000],
                    metadata={"tags": ["tool_result", tool_id], "importance": 0.3},
                )
            except Exception:
                pass

        return result

    def search_memory(self, query: str, layers: Optional[List[str]] = None, limit: int = 5) -> list:
        raw_results = self._memory_system.search(query, layers, limit)
        if raw_results:
            return raw_results

        candidates: Dict[str, str] = {}
        context = self._memory_system.get_context(max_tokens=8000)
        for layer_name, entry in context:
            if hasattr(entry, 'key') and hasattr(entry, 'value'):
                candidates[f"{layer_name}:{entry.key}"] = str(entry.value)

        if candidates:
            embed_results = self._embedder.search(query, candidates, top_k=limit)
            return [(r.id, r.score, r.content) for r in embed_results]
        return []

    def reflect_on_task(
        self,
        task_description: str,
        tool_calls: List[Dict[str, Any]],
        tool_results: List[str],
        final_output: str,
    ) -> Any:
        result = self._reflection.reflect(
            session_id=self.session_id,
            task_description=task_description,
            tool_calls=tool_calls,
            tool_results=tool_results,
            final_output=final_output,
        )
        return result

    def undo_steps(self, steps: int = 1) -> List[Dict[str, Any]]:
        return self._tool_history.undo(steps)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        defs: List[Dict[str, Any]] = []
        for tool in self._tool_registry.list():
            defs.append({
                "name": tool.id,
                "description": tool.description,
                "parameters": tool.parameters,
                "category": tool.category,
                "requiresConfirm": tool.requires_confirm,
            })
        return defs

    def health_check(self) -> Dict[str, Any]:
        checks: Dict[str, bool] = {}
        try:
            tools = self._tool_registry.list()
            checks["tool_registry"] = len(tools) >= 6
        except Exception:
            checks["tool_registry"] = False

        try:
            stats = self._memory_system.get_stats()
            checks["memory_system"] = isinstance(stats, dict)
        except Exception:
            checks["memory_system"] = False

        try:
            vec = self._embedder.embed("test")
            checks["embedder"] = len(vec.values) > 0
        except Exception:
            checks["embedder"] = False

        try:
            results = self._reflection.get_history(limit=1)
            checks["reflection"] = isinstance(results, list)
        except Exception:
            checks["reflection"] = False

        try:
            stats = self._tool_history.get_stats()
            checks["tool_history"] = isinstance(stats, dict)
        except Exception:
            checks["tool_history"] = False

        try:
            validation = self._eval_runner.dry_run_validate()
            checks["eval_runner"] = validation.get("allValid", False)
        except Exception:
            checks["eval_runner"] = False

        all_ok = all(checks.values())
        return {
            "allHealthy": all_ok,
            "checks": checks,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "projectPath": self.project_path,
        }

    def _semantic_search_tool(self, args: dict, ctx: ToolContext) -> ToolResult:
        query = args.get("query", "")
        layer = args.get("layer", "")
        top_k = args.get("top_k", 5)
        if not query:
            return ToolResult(success=False, error="query is required")

        layers = [layer] if layer else None
        results = self.search_memory(query, layers, top_k)

        if not results:
            return ToolResult(
                success=True,
                output="No results found",
                data={"match_count": 0},
            )

        output_parts: List[str] = []
        for item in results:
            if isinstance(item, tuple):
                if len(item) == 3:
                    output_parts.append(f"[{item[0]}] score={item[1]:.3f}: {str(item[2])[:100]}")
                elif len(item) == 2:
                    output_parts.append(f"[{item[0]}]: {str(item[1])[:100]}")
            else:
                output_parts.append(str(item)[:100])

        return ToolResult(
            success=True,
            output="\n".join(output_parts),
            data={"match_count": len(results), "results": output_parts},
        )

    def _memory_store_tool(self, args: dict, ctx: ToolContext) -> ToolResult:
        layer = args.get("layer", "session")
        key = args.get("key", "")
        value = args.get("value", "")
        tags = args.get("tags", [])
        if not key or not value:
            return ToolResult(success=False, error="key and value are required")

        try:
            entry_id = self._memory_system.store(
                layer=layer,
                key=key,
                value=value,
                metadata={"tags": tags, "importance": 0.5},
            )
            return ToolResult(
                success=True,
                output=f"Stored in {layer} layer: {key} (id={entry_id})",
                data={"entryId": entry_id, "layer": layer},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _reflection_tool(self, args: dict, ctx: ToolContext) -> ToolResult:
        import json as _json
        task_desc = args.get("task_description", "")
        tool_calls_raw = args.get("tool_calls_json", "[]")
        tool_results_raw = args.get("tool_results_json", "[]")
        final_output = args.get("final_output", "")

        try:
            tool_calls = _json.loads(tool_calls_raw) if isinstance(tool_calls_raw, str) else tool_calls_raw
        except Exception:
            tool_calls = []
        try:
            tool_results = _json.loads(tool_results_raw) if isinstance(tool_results_raw, str) else tool_results_raw
        except Exception:
            tool_results = []

        result = self.reflect_on_task(task_desc, tool_calls, tool_results, final_output)
        return ToolResult(
            success=True,
            output=f"Reflection: score={result.overall_score:.2f}, critiques={len(result.critiques)}, strengths={len(result.strengths)}",
            data=result.to_dict(),
        )

    def _undo_tool(self, args: dict, ctx: ToolContext) -> ToolResult:
        steps = args.get("steps", 1)
        results = self.undo_steps(steps)
        if not results:
            return ToolResult(success=True, output="No operations to undo")
        return ToolResult(
            success=True,
            output=f"Undid {len(results)} operation(s)",
            data={"undoResults": results},
        )
