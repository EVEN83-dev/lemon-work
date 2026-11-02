"""
B-003: Skill Router - unified skill invocation with routing and fallback.

Ported from standard_mode/core/skill_router.py, decoupled from Qt.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .models import SkillDef, SkillResult
from .registry import SkillsRegistry, get_skills_registry

logger = logging.getLogger(__name__)


@dataclass
class SkillCallRecord:
    skill_name: str = ""
    backend: str = "local"
    success: bool = False
    duration_ms: int = 0
    timestamp: str = ""
    error: str = ""
    agent_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skillName": self.skill_name,
            "backend": self.backend,
            "success": self.success,
            "durationMs": self.duration_ms,
            "error": self.error,
        }


@dataclass
class SkillRoutePolicy:
    skill_name: str = ""
    preferred_backend: str = "auto"
    fallback_enabled: bool = True


class SkillRouter:
    def __init__(self, registry: Optional[SkillsRegistry] = None):
        self._registry = registry or get_skills_registry()
        self._policies: Dict[str, SkillRoutePolicy] = {}
        self._call_history: List[SkillCallRecord] = []
        self._max_history = 200
        self._context: Dict[str, Any] = {}
        self._consecutive_counts: Dict[str, int] = {}
        self._max_consecutive = 5
        self._param_call_counts: Dict[str, int] = {}
        self._max_same_params = 3
        self._force_summary_callback: Optional[Any] = None

    def set_context(self, key: str, value: Any) -> None:
        self._context[key] = value

    def set_policy(self, skill_name: str, preferred_backend: str = "auto",
                   fallback_enabled: bool = True) -> None:
        self._policies[skill_name] = SkillRoutePolicy(
            skill_name=skill_name,
            preferred_backend=preferred_backend,
            fallback_enabled=fallback_enabled,
        )

    def invoke(self, skill_name: str, args: Dict[str, Any],
                agent_id: str = "", session_id: str = "") -> SkillResult:
        self._check_consecutive_limit(skill_name, args)
        start = time.time()
        policy = self._policies.get(skill_name)
        record = SkillCallRecord(
            skill_name=skill_name,
            backend="local",
            agent_id=agent_id,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        )

        from .registry import BUILTIN_BATCH_HANDLERS
        if skill_name in BUILTIN_BATCH_HANDLERS:
            try:
                result_dict = BUILTIN_BATCH_HANDLERS[skill_name](args)
                record.success = result_dict.get("success", True)
                record.duration_ms = int((time.time() - start) * 1000)

                import os as _os
                output = result_dict.get("summary", "") or result_dict.get("message", "")
                if not output and result_dict.get("error"):
                    output = "执行失败: " + str(result_dict["error"])
                if result_dict.get("results"):
                    file_summaries = []
                    for fpath, info in result_dict["results"].items():
                        file_summaries.append(
                            _os.path.basename(fpath) + " (" + str(info.get("lines", 0)) + "行): " + str(info.get("preview", ""))[:100]
                        )
                    if file_summaries:
                        output += "\n\n文件摘要:\n" + "\n".join(file_summaries)

                if record.success:
                    result = SkillResult.ok(output, data=result_dict)
                else:
                    result = SkillResult.fail(
                        error=result_dict.get("error", "执行失败"),
                        output=output or "执行失败",
                        data=result_dict,
                    )

                record.error = result_dict.get("error", "")
                self._add_record(record)
                return result
            except Exception as e:
                record.success = False
                record.error = "批量工具执行失败: " + str(e)
                record.duration_ms = int((time.time() - start) * 1000)
                self._add_record(record)
                return SkillResult.fail("批量工具执行失败: " + str(e))

        skill = self._registry.get(skill_name)
        if skill is None:
            record.success = False
            record.error = "Skill not found: " + skill_name
            record.duration_ms = int((time.time() - start) * 1000)
            self._add_record(record)
            fallback_result = self._try_fallback(skill_name, args, agent_id)
            if fallback_result is not None:
                return fallback_result
            return SkillResult.fail("Skill not found: " + skill_name)

        if skill.requires_confirm:
            logger.info(f"Skill {skill_name} requires user confirmation")

        enriched_args = dict(args)
        for key, value in self._context.items():
            if key.startswith("_") and key not in enriched_args:
                enriched_args[key] = value
        if session_id:
            enriched_args["_session_id"] = session_id

        try:
            result = self._registry.execute(skill_name, enriched_args)
            record.success = result.success
            if not result.success and skill.fallback_skill:
                fallback_result = self._try_fallback(skill.fallback_skill, args, agent_id)
                if fallback_result is not None and fallback_result.success:
                    self._add_record(record)
                    return fallback_result
            if not result.success:
                record.error = result.error
            record.duration_ms = int((time.time() - start) * 1000)
            self._add_record(record)
            return result
        except Exception as e:
            record.error = str(e)
            record.duration_ms = int((time.time() - start) * 1000)
            record.success = False
            self._add_record(record)
            fallback_result = self._try_fallback(skill_name, args, agent_id)
            if fallback_result is not None:
                return fallback_result
            return SkillResult.fail("Skill execution failed: " + str(e))

    def invoke_chain(self, chain_name: str, initial_args: Dict[str, Any],
                      steps: Optional[List[Dict[str, Any]]] = None) -> SkillResult:
        if not steps:
            steps = self._load_predefined_chain(chain_name)
            if not steps:
                return SkillResult.fail("No chain steps defined for: " + chain_name)
        current_args = dict(initial_args)
        final_output = ""
        for i, step in enumerate(steps):
            condition = step.get("condition", "")
            if condition:
                if not self._evaluate_condition(condition, current_args):
                    continue
            skill_name = step.get("skill", "")
            args = step.get("args", {})
            merged_args = {**current_args, **args}
            result = self.invoke(skill_name, merged_args)
            if not result.success:
                fallback_skill = step.get("fallback", "")
                if fallback_skill:
                    fb_result = self.invoke(fallback_skill, merged_args)
                    if fb_result.success:
                        if fb_result.data and isinstance(fb_result.data, dict):
                            current_args = fb_result.data
                        final_output = fb_result.output
                        continue
                return SkillResult.fail(
                    "Chain " + chain_name + " failed at step " + str(i + 1) + " (" + skill_name + "): " + result.error)
            if result.data:
                current_args = result.data if isinstance(result.data, dict) else {"_prev": result.data}
            final_output = result.output
        return SkillResult.ok(output=final_output)

    def _load_predefined_chain(self, chain_name: str) -> Optional[List[Dict[str, Any]]]:
        try:
            from shared.skills.skill_chain import get_chain
            chain = get_chain(chain_name)
            if chain is None:
                return None
            steps = []
            for s in chain.steps:
                steps.append({
                    "skill": s.skill_name,
                    "args": s.args,
                    "args_template": s.args_template,
                    "fallback": s.fallback_args if s.on_failure == "fallback" else "",
                    "condition": s.when,
                })
            return steps
        except ImportError:
            return None
        except Exception:
            return None

    def _evaluate_condition(self, condition: str, args: Dict[str, Any]) -> bool:
        if not condition:
            return True
        parts = condition.split("==")
        if len(parts) == 2:
            key = parts[0].strip()
            value = parts[1].strip().strip("'\"")
            actual = str(args.get(key, ""))
            return actual == value
        parts = condition.split("!=")
        if len(parts) == 2:
            key = parts[0].strip()
            value = parts[1].strip().strip("'\"")
            actual = str(args.get(key, ""))
            return actual != value
        if condition.startswith("exists:"):
            key = condition[7:].strip()
            return key in args
        return True

    def route_by_intent(self, user_input: str, args: Dict[str, Any],
                        agent_id: str = "", min_confidence: float = 0.3) -> SkillResult:
        matches = self._registry.find_by_intent(user_input, top_k=3, min_confidence=min_confidence)
        if not matches:
            return SkillResult.fail("No matching skill found for input: " + user_input[:50])
        for skill_name, score in matches:
            if score < min_confidence:
                continue
            result = self.invoke(skill_name, args, agent_id)
            if result.success:
                return result
        return SkillResult.fail("All matched skills failed for: " + user_input[:50])

    def _try_fallback(self, skill_name: str, args: Dict[str, Any],
                       agent_id: str = "") -> Optional[SkillResult]:
        candidates: List[str] = []
        skill = self._registry.get(skill_name)
        if skill and skill.fallback_skill:
            candidates.append(skill.fallback_skill)
        else:
            candidates.append(skill_name)
        matches = self._registry.find_by_intent(skill_name.replace("_", " "), top_k=3)
        for match_name, _ in matches:
            if match_name != skill_name and match_name not in candidates:
                candidates.append(match_name)
            if len(candidates) >= 3:
                break
        for fb_name in candidates[:3]:
            fb_skill = self._registry.get(fb_name)
            if fb_skill:
                logger.info("Falling back from %s to %s", skill_name, fb_name)
                result = self.invoke(fb_name, args, agent_id)
                if result.success:
                    return result
        return None

    def _check_consecutive_limit(self, skill_name: str, args: Dict[str, Any] = None) -> None:
        count = self._consecutive_counts.get(skill_name, 0) + 1
        self._consecutive_counts[skill_name] = count
        if count > self._max_consecutive:
            logger.warning("Skill %s called %d times consecutively, triggering summary", skill_name, count)
            self._consecutive_counts[skill_name] = 0
            if self._force_summary_callback:
                try:
                    self._force_summary_callback(skill_name, count)
                except Exception:
                    pass
        if args:
            param_key = skill_name + ":" + str(sorted(args.items()))
            param_count = self._param_call_counts.get(param_key, 0) + 1
            self._param_call_counts[param_key] = param_count
            if param_count > self._max_same_params:
                logger.warning("Skill %s called %d times with same params, triggering summary", skill_name, param_count)
                self._param_call_counts[param_key] = 0
                if self._force_summary_callback:
                    try:
                        self._force_summary_callback(skill_name, param_count)
                    except Exception:
                        pass

    def set_force_summary_callback(self, callback: Any) -> None:
        self._force_summary_callback = callback

    def get_call_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._call_history[-limit:]]

    def _add_record(self, record: SkillCallRecord) -> None:
        self._call_history.append(record)
        if len(self._call_history) > self._max_history:
            self._call_history = self._call_history[-self._max_history:]

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        tools = self._registry.get_tool_definitions()

        from .registry import BATCH_READ_FILES_DEF, SCAN_PROJECT_DEF, QUICK_ANALYZE_DEF
        batch_tools = [
            {"type": "function", "function": BATCH_READ_FILES_DEF},
            {"type": "function", "function": SCAN_PROJECT_DEF},
            {"type": "function", "function": QUICK_ANALYZE_DEF},
        ]
        tools.extend(batch_tools)
        return tools

    def get_skill_info(self, skill_name: str) -> Optional[Dict[str, Any]]:
        skill = self._registry.get(skill_name)
        if skill is None:
            return None
        return skill.to_api_dict()
