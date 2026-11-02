# -*- coding: utf-8 -*-
"""[DEPRECATED] 本模块已删除空壳实现，所有功能已迁移至：
  - shared.orchestration_engine.OrchestrationEngine  (编排内核)
  - bridge.core.multi_agent_orchestrator.MultiAgentOrchestrator (多Agent调度)

本文件仅保留兼容重导出，防止 import 崩溃。
"""
import warnings

from shared.orchestration_engine import (
    OrchestrationMode,
    OrchestrationStep,
    OrchestrationPlan,
    OrchestrationEngine,
    get_orchestration_engine,
    _DEPRECATED_SERVICE_COMPAT,
)

warnings.warn(
    "[DEPRECATED] bridge.services.agent_orchestrator 已废弃, "
    "请使用 shared.orchestration_engine 或 bridge.core.multi_agent_orchestrator",
    DeprecationWarning,
    stacklevel=2,
)

AgentOrchestratorService = _DEPRECATED_SERVICE_COMPAT["AgentOrchestratorService"]
