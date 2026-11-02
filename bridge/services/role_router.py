# -*- coding: utf-8 -*-
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


_ROLE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "coordinator": {
        "name": "协调者",
        "system_prompt": "你是任务协调者。负责拆分任务、分配给合适的角色、汇总结果、仲裁冲突。不直接编码，只统筹。",
        "capabilities": ["task_decomposition", "result_aggregation", "conflict_resolution", "role_assignment"],
        "task_keywords": ["协调", "分配", "管理", "汇总", "仲裁", "coordinate", "manage", "assign", "aggregate"],
    },
    "researcher": {
        "name": "研究员",
        "system_prompt": "你是研究员。负责信息搜集、资料分析、方案调研。提供详实的技术调研报告。",
        "capabilities": ["information_search", "document_analysis", "solution_research", "api_retrieval"],
        "task_keywords": ["调研", "搜索", "查找", "资料", "研究", "文档", "research", "search", "investigate", "document"],
    },
    "coder": {
        "name": "编码者",
        "system_prompt": "你是编码者。负责代码编写、重构、bug修复。产出高质量、可运行的代码。",
        "capabilities": ["code_writing", "code_refactoring", "bug_fixing", "implementation"],
        "task_keywords": ["编写", "实现", "编码", "开发", "代码", "重构", "修复", "code", "implement", "develop", "fix", "write"],
    },
    "reviewer": {
        "name": "审查者",
        "system_prompt": "你是审查者。负责代码审查、质量把关、安全检查。给出具体的改进建议和评分。",
        "capabilities": ["code_review", "quality_check", "security_audit", "best_practices"],
        "task_keywords": ["审查", "检查", "评审", "质量", "安全", "review", "audit", "check", "quality"],
    },
    "tester": {
        "name": "测试者",
        "system_prompt": "你是测试者。负责测试用例设计、执行、结果验证。确保代码正确性和覆盖率。",
        "capabilities": ["test_design", "test_execution", "result_verification", "coverage_analysis"],
        "task_keywords": ["测试", "验证", "用例", "跑通", "test", "verify", "coverage", "assert"],
    },
    "documenter": {
        "name": "文档者",
        "system_prompt": "你是文档者。负责文档编写、注释补充、README维护。产出清晰、完整的技术文档。",
        "capabilities": ["documentation", "comment_writing", "readme_maintenance", "api_documentation"],
        "task_keywords": ["文档", "注释", "README", "说明", "document", "comment", "readme", "describe"],
    },
}


@dataclass
class RoleAssignment:
    agent_id: str
    role_id: str
    previous_role: str = ""
    assigned_at: float = field(default_factory=time.time)
    assigned_by: str = ""


class RoleRouter:
    def __init__(self, bus=None):
        self._assignments: Dict[str, RoleAssignment] = {}
        self._multi_role: Dict[str, Set[str]] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()
        self._bus = bus
        self._keyword_index: Dict[str, List[str]] = {}
        self._build_keyword_index()

    def _build_keyword_index(self) -> None:
        self._keyword_index = {}
        for role_id, template in _ROLE_TEMPLATES.items():
            for kw in template.get("task_keywords", []):
                kw_lower = kw.lower()
                if kw_lower not in self._keyword_index:
                    self._keyword_index[kw_lower] = []
                self._keyword_index[kw_lower].append(role_id)

    def route_task(self, task_description: str, top_k: int = 3) -> List[str]:
        task_lower = task_description.lower()
        scores: Dict[str, float] = {}
        for role_id, template in _ROLE_TEMPLATES.items():
            score = 0.0
            for kw in template.get("task_keywords", []):
                if kw.lower() in task_lower:
                    score += 1.0
            for cap in template.get("capabilities", []):
                cap_words = cap.replace("_", " ").split()
                for w in cap_words:
                    if w.lower() in task_lower:
                        score += 0.3
            if score > 0:
                scores[role_id] = score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [r[0] for r in ranked[:top_k]]

    def route_best(self, task_description: str) -> Optional[str]:
        results = self.route_task(task_description, top_k=1)
        return results[0] if results else None

    def assign_role(self, agent_id: str, role_id: str, assigned_by: str = "system") -> bool:
        if role_id not in _ROLE_TEMPLATES:
            logger.warning("[RoleRouter] Unknown role: %s", role_id)
            return False
        with self._lock:
            prev = ""
            if agent_id in self._assignments:
                prev = self._assignments[agent_id].role_id
            self._assignments[agent_id] = RoleAssignment(
                agent_id=agent_id,
                role_id=role_id,
                previous_role=prev,
                assigned_by=assigned_by,
            )
        self._emit("role_assigned", {
            "agent_id": agent_id,
            "role_id": role_id,
            "previous_role": prev,
            "assigned_by": assigned_by,
        })
        self._notify_role_change(agent_id, role_id, prev)
        logger.info("[RoleRouter] %s assigned role %s (was %s)", agent_id, role_id, prev or "none")
        return True

    def assign_multi_role(self, agent_id: str, role_ids: List[str]) -> bool:
        with self._lock:
            self._multi_role[agent_id] = set(role_ids)
            if role_ids:
                primary = role_ids[0]
                prev = ""
                if agent_id in self._assignments:
                    prev = self._assignments[agent_id].role_id
                self._assignments[agent_id] = RoleAssignment(
                    agent_id=agent_id, role_id=primary, previous_role=prev,
                )
        for rid in role_ids:
            self._emit("role_assigned", {
                "agent_id": agent_id, "role_id": rid, "assigned_by": "system",
            })
        return True

    def get_role(self, agent_id: str) -> Optional[str]:
        with self._lock:
            if agent_id in self._assignments:
                return self._assignments[agent_id].role_id
        return None

    def get_all_roles(self, agent_id: str) -> List[str]:
        with self._lock:
            if agent_id in self._multi_role:
                return list(self._multi_role[agent_id])
            if agent_id in self._assignments:
                return [self._assignments[agent_id].role_id]
        return []

    def get_system_prompt(self, role_id: str) -> str:
        template = _ROLE_TEMPLATES.get(role_id, {})
        return template.get("system_prompt", "")

    def get_capabilities(self, role_id: str) -> List[str]:
        template = _ROLE_TEMPLATES.get(role_id, {})
        return template.get("capabilities", [])

    def get_role_template(self, role_id: str) -> Optional[Dict[str, Any]]:
        return _ROLE_TEMPLATES.get(role_id)

    def list_templates(self) -> Dict[str, Dict[str, Any]]:
        return dict(_ROLE_TEMPLATES)

    def request_role_change(self, agent_id: str, new_role: str, reason: str = "") -> bool:
        current = self.get_role(agent_id)
        if current == new_role:
            return True
        self._emit("role_change_requested", {
            "agent_id": agent_id,
            "current_role": current,
            "requested_role": new_role,
            "reason": reason,
        })
        return self.assign_role(agent_id, new_role, assigned_by=agent_id)

    def force_assign_role(self, agent_id: str, new_role: str, coordinator_id: str = "coordinator") -> bool:
        return self.assign_role(agent_id, new_role, assigned_by=coordinator_id)

    def get_agents_by_role(self, role_id: str) -> List[str]:
        agents = []
        with self._lock:
            for aid, assignment in self._assignments.items():
                if assignment.role_id == role_id:
                    agents.append(aid)
                elif aid in self._multi_role and role_id in self._multi_role[aid]:
                    agents.append(aid)
        return agents

    def get_all_assignments(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            result = {}
            for aid, assignment in self._assignments.items():
                result[aid] = {
                    "role_id": assignment.role_id,
                    "previous_role": assignment.previous_role,
                    "assigned_at": assignment.assigned_at,
                    "assigned_by": assignment.assigned_by,
                    "multi_roles": list(self._multi_role.get(aid, set())),
                }
            return result

    def on(self, event: str, callback: Callable) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _notify_role_change(self, agent_id: str, new_role: str, old_role: str) -> None:
        if not self._bus:
            return
        try:
            from bridge.services.agent_bus import AgentCommMessage, get_agent_comm_bus
            bus = self._bus or get_agent_comm_bus()
            bus.broadcast(AgentCommMessage(
                sender_id="role_router",
                message_type="role_changed",
                payload={
                    "agent_id": agent_id,
                    "new_role": new_role,
                    "old_role": old_role,
                },
                priority=2,
            ))
        except Exception:
            pass

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass


_global_role_router: Optional[RoleRouter] = None
_router_lock = threading.Lock()


def get_role_router() -> RoleRouter:
    global _global_role_router
    if _global_role_router is None:
        with _router_lock:
            if _global_role_router is None:
                _global_role_router = RoleRouter()
    return _global_role_router
