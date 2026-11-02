from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from bridge.protocol import MessageType  # ★验收修复2026-09-30: L613/L655 使用但未导入, 触发NameError 500

from bridge.engines.engine_manager import EngineManager
from bridge.skills.router import SkillRouter
from bridge.skills.models import SkillResult
from bridge.core.context_manager import ContextManager
from bridge.core.session_memory import SessionMemory
from bridge.core.loop_detector import LoopDetector, LOOP_BREAK_PROMPT
from bridge.core.progress_tracker import ProgressTracker
from bridge.core.result_validator import ResultValidator
from bridge.core.permission import PermissionManager, PermissionAction, PermissionGuardAdapter
from bridge.core.compaction import ContextCompactor
from bridge.core.reflection import ReflectionLoop
from bridge.core.goap_planner import (
    GOAPPlanner, PlanGenerator, PlanExecutor, PlanStatus,
    GOAPAgentLoopIntegration, get_goap_integration,
    LLMActionDecomposer, AdaptiveReplanner, ExponentialBackoffRetry,
)
from bridge.protocol import (
    make_stream_start, make_stream_delta, make_stream_end,
    make_tool_call, make_tool_result, make_done, make_error,
    make_progress_start, make_progress_tool, make_progress_summary,
    make_progress_done, make_intermediate_finding, make_force_summary,
    make_permission_request, make_thinking_step, make_tool_execution_card,
    ErrorCode, BridgeMessage,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Lemon Agent, a professional code analysis assistant.

## Your Capabilities
You have access to file reading, code execution, and analysis tools. Use them strategically.
You have a powerful semantic code search tool `search_code_semantic`. When users ask "where is", "how is X implemented", you MUST use this tool first instead of iterating through all files. It returns the most relevant code snippets based on natural language semantics.

## Project Analysis Strategy (MUST follow this order):
1. FIRST: Use `search_code_semantic` to find relevant code for the user's question
2. THEN: Scan project structure (list top-level files and directories) to understand the project layout
3. THEN: Read key files (README, main entry points, configuration files) to understand the project purpose
4. SELECTIVE READING: Only read files that are relevant to the user's question. Do NOT read every file blindly.
5. SYNTHESIZE: After collecting sufficient information, STOP calling tools and provide a structured analysis.

## Early Stop Conditions (STOP calling tools when):
- You have read 8-10 files and have a clear understanding of the project
- The user's question has been answered with the information you have
- Further file reads would be redundant

## Output Format
When you have gathered enough information, respond with:
1. A brief summary of the project's purpose and tech stack
2. Key architecture observations
3. Strengths and weaknesses
4. Specific recommendations

## Important
- Always respond in the user's language (Chinese or English)
- Prefer reading fewer files with deeper analysis over reading many files superficially
- After each tool call, evaluate whether you have enough information to answer the user's question"""

MAX_TOOL_ROUNDS = 15
FINDING_INTERVAL = 5

_REPORT_TEMPLATE = """## 分析报告

**状态**: {status}
**工具调用**: {tool_call_count} 次
**覆盖工具**: {tools_covered}
**耗时**: {elapsed:.1f}s

### 核心发现
{core_findings}

### 详细分析
{detailed_analysis}

### 结论
{conclusion}
"""


class AgentLoop:
    def __init__(self, engine_manager: EngineManager,
                 skill_router: Optional[SkillRouter] = None,
                 session_memory: Optional[SessionMemory] = None,
                 context_manager: Optional[ContextManager] = None,
                 permission_guard: Optional[Any] = None,
                 memory_distiller: Optional[Any] = None,
                 session_checkpoint: Optional[Any] = None,
                 plugin_system: Optional[Any] = None,
                 tracer: Optional[Any] = None,
                 lsp_manager: Optional[Any] = None):
        self._engine_manager = engine_manager
        self._skill_router = skill_router or SkillRouter()
        self._session_memory = session_memory or SessionMemory()
        self._context_manager = context_manager or ContextManager()
        self._on_message: Optional[Callable[[BridgeMessage], None]] = None
        self._loop_detector = LoopDetector(max_total_calls=MAX_TOOL_ROUNDS)
        self._progress_tracker = ProgressTracker()
        self._result_validator = ResultValidator()

        if permission_guard is not None:
            if isinstance(permission_guard, PermissionGuardAdapter):
                self._permission_manager = permission_guard
            else:
                self._permission_manager = PermissionGuardAdapter(permission_guard)
        else:
            self._permission_manager = PermissionManager()

        self._memory_distiller = memory_distiller
        self._session_checkpoint = session_checkpoint
        self._plugin_system = plugin_system
        self._compactor: Optional[ContextCompactor] = None
        self._reflection_loop: Optional[ReflectionLoop] = None
        self._tracer = tracer
        self._trajectory_recorder = None
        self._lsp_manager = lsp_manager
        self._plan_mode: bool = False
        self._plan_confirmed: Optional[asyncio.Event] = None
        self._plan_accepted: bool = False
        self._plan_data: Optional[dict] = None
        self._last_event_id: Dict[str, str] = {}
        self._tool_call_records: List[Dict[str, Any]] = []
        self._tool_result_records: List[str] = []
        self._session_msg_counts: Dict[str, int] = {}
        self._current_cwd: str = os.getcwd()
        self._terminal_callback: Optional[Callable[[str], None]] = None
        self._goap_integration: Optional[GOAPAgentLoopIntegration] = None
        self._backoff_retry = ExponentialBackoffRetry()
        self._replanner = AdaptiveReplanner()
        self._step_budget: int = 0
        self._step_budget_limit: int = 50
        self._token_budget: int = 0
        self._token_budget_limit: int = 200000
        self._context_truncate_threshold: float = 0.85

        if hasattr(self._skill_router, '_registry') and self._skill_router._registry:
            discovered = self._skill_router._registry.auto_discover()
            logger.info(f"[AgentLoop] 自动发现 {discovered} 个技能模块")

    def set_message_callback(self, callback: Callable[[BridgeMessage], None]) -> None:
        self._on_message = callback

    def set_progress_callback(self, callback: Callable, finding_callback: Callable = None) -> None:
        self._progress_tracker.set_callback(callback)
        if finding_callback:
            self._progress_tracker.set_finding_callback(finding_callback)

    def set_compactor(self, compactor: ContextCompactor) -> None:
        self._compactor = compactor
        self._context_manager.set_compactor(compactor)

    def set_reflection_loop(self, reflection_loop: ReflectionLoop) -> None:
        self._reflection_loop = reflection_loop

    def set_trajectory_recorder(self, recorder: Any) -> None:
        self._trajectory_recorder = recorder

    def set_plan_mode(self, enabled: bool) -> None:
        self._plan_mode = enabled

    def confirm_plan(self, accepted: bool, modified_plan: Optional[dict] = None) -> None:
        self._plan_accepted = accepted
        if modified_plan:
            self._plan_data = modified_plan
        if self._plan_confirmed is not None:
            self._plan_confirmed.set()

    def notify_cwd_change(self, path: str) -> None:
        """Agent切换目录时调用, 更新内部cwd并通知外部。"""
        if path and os.path.isdir(path):
            self._current_cwd = os.path.normpath(path)
            self._emit(make_tool_result("cwd → " + self._current_cwd, session_id=""))

    def execute_in_terminal(self, command: str) -> None:
        """Agent命令路由到绑定的终端Tab。"""
        if self._terminal_callback:
            self._terminal_callback(command)
        else:
            logger.warning("execute_in_terminal: 无终端回调绑定")

    def set_terminal_callback(self, callback: Callable[[str], None]) -> None:
        """绑定终端回调, Agent命令将路由到此终端。"""
        self._terminal_callback = callback

    def _trace(self, session_id: str, event_type: str, data: dict,
               agent_id: str = "", agent_name: str = "") -> None:
        if self._tracer is None:
            return
        parent_id = self._last_event_id.get(session_id, "")
        event = self._tracer.trace(
            session_id, event_type, data, parent_id,
            agent_id=agent_id, agent_name=agent_name,
        )
        self._last_event_id[session_id] = event.event_id
        if self._trajectory_recorder is not None:
            try:
                self._trajectory_recorder.record(event)
            except Exception:
                pass

    def _emit(self, msg: BridgeMessage) -> None:
        if self._on_message:
            self._on_message(msg)

    def _emit_progress(self, event_type: str, description: str, **kwargs: Any) -> None:
        session_id = kwargs.get("session_id", "")
        skill_name = kwargs.get("skill_name", "")
        step = kwargs.get("step", 0)
        total = kwargs.get("total_steps", 0)
        if event_type == "progress_start":
            self._emit(make_progress_start(session_id, step, total, description))
        elif event_type == "progress_tool":
            self._emit(make_progress_tool(session_id, skill_name, step, total, description))
        elif event_type == "progress_summary":
            self._emit(make_progress_summary(session_id, step, total, description))
        elif event_type == "progress_done":
            self._emit(make_progress_done(session_id, step, total, description))

    def _emit_finding(self, session_id: str, content: str, source_skill: str = "",
                      importance: str = "normal", files_analyzed: int = 0) -> None:
        self._emit(make_intermediate_finding(
            session_id, content, source_skill, importance, files_analyzed))

    def _collect_stream(self, messages: List[Dict], engine_name: Optional[str] = None,
                        **kwargs) -> List[str]:
        tokens = []
        for token in self._engine_manager.chat_stream(messages, engine_name=engine_name, **kwargs):
            tokens.append(token)
        return tokens

    def _eval_harness(self, session_id: str) -> None:
        try:
            from bridge.eval.agent_bench import AgentBench
            bench = AgentBench()
            report = bench.run()
            pass_rate = report.get("pass_rate", 0.0)
            self._session_memory.add_message(
                session_id, "system",
                json.dumps({"harness_pass_rate": pass_rate, "report": report}),
            )
            logger.info("[AgentLoop] _eval_harness: session=%s pass_rate=%.2f", session_id, pass_rate)
        except Exception as e:
            logger.error("[AgentLoop] _eval_harness error: %s", e)

    async def run(self, session_id: str, user_message: str,
                   skill_hint: str = "", files: Optional[List[str]] = None,
                   engine_name: Optional[str] = None) -> str:
        self._session_memory.add_message(session_id, "user", user_message)
        self._context_manager.append(session_id, "user", user_message)
        self._trace(session_id, "turn_started", {
            "user_message": user_message[:200], "skill_hint": skill_hint,
        })

        if self._plugin_system:
            try:
                self._plugin_system.emit("on_message", {
                    "session_id": session_id, "role": "user", "content": user_message,
                })
            except Exception:
                pass

        if self._compactor:
            context = self._context_manager.smart_truncate(session_id)
            if hasattr(self._context_manager, '_last_compress_info'):
                info = self._context_manager._last_compress_info
                if isinstance(info, dict):
                    self._progress_tracker.context_compressed(
                        info.get("original_tokens", 0),
                        info.get("compressed_tokens", 0),
                    )
        else:
            context = self._context_manager.truncate(session_id)

        system_msg = {"role": "system", "content": SYSTEM_PROMPT}
        messages: List[Dict[str, Any]] = [system_msg] + context
        if skill_hint:
            messages.append({
                "role": "system",
                "content": f"The user wants to use the '{skill_hint}' skill. Prioritize this skill if relevant.",
            })
        if files:
            files_desc = ", ".join(files)
            messages.append({
                "role": "system",
                "content": f"The user has uploaded files: {files_desc}. Reference them when using file-related skills.",
            })
        tools = self._skill_router.get_tool_definitions()
        engine = self._engine_manager.get_engine(engine_name)
        self._trace(session_id, "context_injected", {
            "message_count": len(messages), "skill_hint": skill_hint,
            "files": files or [], "model": engine.get_model_name() if engine else "",
        })
        self._emit(make_thinking_step(
            session_id, "context_inject",
            f"注入上下文: {len(messages)}条消息, 技能提示: {skill_hint or '无'}",
            {"messageCount": len(messages), "skillHint": skill_hint},
        ))

        if self._lsp_manager and any(kw in user_message for kw in ("代码", "错误", "诊断", "文件", "bug", "error", "code", "debug")):
            try:
                diagnostics = self._lsp_manager.get_diagnostics()
                if diagnostics:
                    diag_context = "\n[当前文件 LSP 诊断]\n"
                    for d in diagnostics[:10]:
                        sev = d.get("severity", "info")
                        msg = d.get("message", "")
                        line = d.get("range", {}).get("start", {}).get("line", "?")
                        fp = d.get("file", "")
                        diag_context += f"- [{sev}] {msg} (行 {line}, {fp})\n"
                    messages.append({"role": "system", "content": diag_context})
                    self._trace(session_id, "context_injected", {
                        "source": "lsp_diagnostics",
                        "diagnostic_count": len(diagnostics),
                    })
            except Exception as e:
                logger.warning(f"[AgentLoop] LSP 诊断失败: {e}")

        final_content = ""
        if engine is None:
            err = make_error(ErrorCode.ENGINE_UNAVAILABLE, "No AI engine available")
            self._emit(err)
            return "Error: No AI engine available"
        model_name = engine.get_model_name()
        self._emit(make_stream_start(session_id=session_id, model=model_name))

        self._loop_detector.reset()
        self._tool_call_records.clear()
        self._tool_result_records.clear()

        # 运行前确保技能已注册
        if hasattr(self._skill_router, '_registry') and self._skill_router._registry:
            if self._skill_router._registry.count() == 0:
                discovered = self._skill_router._registry.auto_discover()
                logger.info(f"[AgentLoop] 运行前发现 {discovered} 个技能")

        if self._plugin_system:
            try:
                self._plugin_system.emit("before_process", {
                    "session_id": session_id, "user_message": user_message,
                })
            except Exception:
                pass

        self._progress_tracker.start(session_id, total_steps=MAX_TOOL_ROUNDS)
        self._emit_progress("progress_start", "开始执行任务...", session_id=session_id)

        if self._plan_mode and self._plan_data is None:
            plan = await self._generate_plan(session_id, user_message, messages, engine, tools)
            if plan:
                self._plan_data = plan
                self._trace(session_id, "plan_generated", {
                    "steps": plan.get("steps", []),
                    "rationale": plan.get("rationale", ""),
                    "step_budget": self._step_budget,
                })
                self._emit(BridgeMessage(
                    type="plan_proposed", sessionId=session_id,
                    payload={"plan": plan},
                ))
                self._plan_confirmed = asyncio.Event()
                self._plan_accepted = False
                try:
                    await asyncio.wait_for(self._plan_confirmed.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    self._plan_accepted = False
                    self._emit(make_thinking_step(
                        session_id, "plan_timeout",
                        "计划审批超时(30s)，转人工拒绝",
                        {"timeout": 30.0},
                    ))
                if not self._plan_accepted:
                    self._emit(make_error(ErrorCode.TASK_CANCELLED, "User rejected the plan"))
                    self._trace(session_id, "agent_completed", {
                        "session_id": session_id, "reason": "plan_rejected",
                        "step_budget": self._step_budget,
                    })
                    return "Task cancelled: plan rejected by user"

        total_tool_calls = 0
        loop_broken = False

        for round_num in range(MAX_TOOL_ROUNDS):
            self._step_budget += 1
            if self._step_budget >= self._step_budget_limit:
                logger.warning("[AgentLoop] step budget硬截止: %d >= %d",
                              self._step_budget, self._step_budget_limit)
                self._trace(session_id, "step_budget_exceeded", {
                    "step_budget": self._step_budget,
                    "limit": self._step_budget_limit,
                    "tool_calls": total_tool_calls,
                })
                self._emit(make_error(ErrorCode.TASK_CANCELLED,
                    f"Step budget exceeded ({self._step_budget}/{self._step_budget_limit})", session_id))
                self._emit(make_done("Step budget exceeded — 强制终止", session_id))
                return "Step budget exceeded"

            est_tokens = sum(len(m.get("content", "")) for m in messages if isinstance(m.get("content"), str))
            if est_tokens > self._token_budget_limit * self._context_truncate_threshold:
                logger.info("[AgentLoop] 上下文接近token上限，触发截断 (est=%d, limit=%d)",
                           est_tokens, self._token_budget_limit)
                try:
                    if self._compactor:
                        messages = await asyncio.to_thread(self._compactor.compact, messages)
                    else:
                        if len(messages) > 6:
                            system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
                            kept = messages[-4:]
                            messages = ([system_msg] + kept) if system_msg else kept
                except Exception as compact_err:
                    logger.warning("[AgentLoop] 上下文截断失败: %s", compact_err)
                self._trace(session_id, "context_truncated", {
                    "original_est_tokens": est_tokens,
                    "truncated_len": len(messages),
                    "step_budget": self._step_budget,
                })

            try:
                if tools and engine.supports_tools:
                    kwargs_with_engine: Dict[str, Any] = {"engine_name": engine_name}
                    result = await asyncio.to_thread(
                        self._engine_manager.chat_with_tools,
                        messages, tools, **kwargs_with_engine,
                    )
                    if round_num == 0 and result.get("content"):
                        self._emit(make_stream_delta(result["content"], session_id))
                else:
                    if round_num == 0:
                        tokens = await asyncio.to_thread(
                            self._collect_stream, messages, engine_name, **{},
                        )
                        for token in tokens:
                            self._emit(make_stream_delta(token, session_id))
                        content = "".join(tokens)
                        result = {"content": content, "tool_calls": []}
                    else:
                        kwargs_with_engine = {"engine_name": engine_name}
                        content = await asyncio.to_thread(
                            self._engine_manager.chat, messages, **kwargs_with_engine,
                        )
                        result = {"content": content, "tool_calls": []}
            except Exception as e:
                self._emit(make_error(ErrorCode.INTERNAL, str(e), session_id))
                self._trace(session_id, "error_occurred", {
                    "error_type": "execution_error", "error": str(e),
                })
                if self._plugin_system:
                    try:
                        self._plugin_system.emit("on_error", {
                            "session_id": session_id, "error": str(e),
                        })
                    except Exception:
                        pass
                # ★ H3修复: 400/API错误仍须发送 make_done，否则前端永远收不到完成信号
                fallback_content = f"执行出错: {str(e)}"
                if self._tool_call_records:
                    fallback_content = self._build_fallback_summary(user_message)
                self._emit(make_done(fallback_content, session_id))
                return f"Error: {e}"

            content = result.get("content", "")
            tool_calls = result.get("tool_calls", [])

            invalid_calls = []
            for tc in tool_calls:
                func = tc.get("function", tc)
                if not func.get("name"):
                    invalid_calls.append(tc)

            if invalid_calls:
                logger.error(
                    f"[AgentLoop] 检测到 {len(invalid_calls)} 个无效工具调用，强制中断！")
                final_content = content or "检测到无效的工具调用格式，已强制中断执行。"
                loop_broken = True
                self._trace(session_id, "error_occurred", {
                    "error_type": "invalid_tool_call",
                    "invalid_count": len(invalid_calls),
                })
                break

            if not tool_calls:
                final_content = content
                break

            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

            for tc in tool_calls:
                func = tc.get("function", tc)
                skill_name = func.get("name", "")
                try:
                    args = func.get("arguments", func.get("args", {}))
                    if isinstance(args, str):
                        args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                call_id = tc.get("id", "")

                loop_result = self._loop_detector.record(skill_name, args)
                total_tool_calls += 1

                self._tool_call_records.append({
                    "skill_name": skill_name,
                    "args": args,
                    "call_id": call_id,
                    "round": round_num,
                })

                self._progress_tracker.tool_call(skill_name, args)
                self._emit_progress("progress_tool",
                    self._progress_tracker._describe_tool_call(
                        skill_name, args, total_tool_calls, MAX_TOOL_ROUNDS),
                    session_id=session_id, skill_name=skill_name,
                    step=total_tool_calls, total_steps=MAX_TOOL_ROUNDS)

                if loop_result.is_loop:
                    break_prompt = self._loop_detector.get_break_prompt(loop_result.loop_type)
                    messages.append({
                        "role": "system",
                        "content": break_prompt,
                    })
                    loop_broken = True
                    self._trace(session_id, "error_occurred", {
                        "error_type": "loop_detected",
                        "loop_type": loop_result.loop_type,
                        "loop_skill": loop_result.loop_skill,
                        "consecutive_same": loop_result.consecutive_same,
                    })
                    self._trace(session_id, "loop_detected", {
                        "loop_type": loop_result.loop_type,
                        "loop_skill": loop_result.loop_skill,
                        "consecutive_same": loop_result.consecutive_same,
                    })
                    logger.warning(
                        f"Loop detected: type={loop_result.loop_type} "
                        f"skill={loop_result.loop_skill} "
                        f"consecutive_same={loop_result.consecutive_same} "
                        f"total={loop_result.total_calls}"
                    )
                    break

                should_proceed, routing_reason = self._smart_tool_routing(skill_name, args)
                if not should_proceed:
                    messages.append({
                        "role": "system",
                        "content": "[智能路由] " + routing_reason,
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": "[跳过] " + routing_reason,
                    })
                    logger.info(f"Smart routing skipped: {skill_name} — {routing_reason}")
                    continue

                perm_action = self._permission_manager.check(skill_name, args)
                if perm_action == PermissionAction.DENY:
                    denied_msg = f"操作被权限规则禁止：{skill_name} {args}"
                    self._emit(make_error(ErrorCode.PERMISSION_REQUEST, denied_msg, session_id))
                    messages.append({
                        "role": "tool",
                        "content": f"[权限拒绝] {denied_msg}",
                        "tool_call_id": call_id,
                    })
                    continue

                if perm_action == PermissionAction.ASK:
                    approval_req = self._permission_manager.request_approval(
                        skill_name, args,
                        reason=f"Skill '{skill_name}' 需要用户审批",
                    )
                    self._emit(make_permission_request(
                        session_id, skill_name, args, approval_req.id))
                    self._trace(session_id, "approval_requested", {
                        "skill_name": skill_name, "request_id": approval_req.id,
                        "reason": approval_req.reason,
                    })
                    approved = await asyncio.to_thread(
                        self._permission_manager.wait_for_approval,
                        approval_req.id, 30.0,
                    )
                    if not approved:
                        messages.append({
                            "role": "tool",
                            "content": f"[用户拒绝] {skill_name} 未被授权执行",
                            "tool_call_id": call_id,
                        })
                        continue

                self._emit(make_tool_call(skill_name, args, session_id, call_id))
                self._trace(session_id, "tool_called", {
                    "skill_name": skill_name, "args": args, "call_id": call_id,
                    "round": round_num, "tool_call_num": total_tool_calls,
                    "step_budget": self._step_budget,
                })
                self._emit(make_thinking_step(
                    session_id, "tool_call",
                    f"调用 {skill_name}",
                    {"skill": skill_name, "args": args, "round": round_num},
                ))
                call_start_time = time.time()
                running_card = make_tool_execution_card(
                    tool_name=skill_name, status="running", args=args,
                    description=f"正在调用 {skill_name}...", call_id=call_id,
                )
                self._emit(BridgeMessage(
                    type=MessageType.TOOL_EXECUTE, sessionId=session_id,
                    payload={"card": running_card.to_dict(), "callId": call_id},
                ))

                if self._plugin_system:
                    try:
                        self._plugin_system.emit("on_tool_execute", {
                            "session_id": session_id, "skill_name": skill_name, "args": args,
                        })
                    except Exception:
                        pass

                skill_result = await asyncio.to_thread(self._skill_router.invoke, skill_name, args)
                result_content = skill_result.output if skill_result.success else f"Error: {skill_result.error}"

                self._tool_result_records.append(result_content)
                self._emit(make_tool_result(
                    result_content, call_id, session_id, skill_result.success))
                self._trace(session_id, "tool_result", {
                    "skill_name": skill_name, "success": skill_result.success,
                    "output_preview": result_content[:200],
                    "call_id": call_id,
                    "step_budget": self._step_budget,
                })
                self._emit(make_thinking_step(
                    session_id, "tool_result",
                    f"{skill_name} {'成功' if skill_result.success else '失败'}",
                    {"skill": skill_name, "success": skill_result.success,
                     "preview": result_content[:100]},
                ))
                elapsed_ms = int((time.time() - call_start_time) * 1000)
                done_status = "completed" if skill_result.success else "failed"
                result_preview = (
                    f"成功: {result_content[:100]}" if skill_result.success
                    else f"失败: {skill_result.error[:100] if hasattr(skill_result, 'error') else result_content[:100]}"
                )
                done_card = make_tool_execution_card(
                    tool_name=skill_name, status=done_status, args=args,
                    description=result_preview, duration_ms=elapsed_ms,
                    call_id=call_id,
                )
                self._emit(BridgeMessage(
                    type=MessageType.TOOL_EXECUTE_RESULT, sessionId=session_id,
                    payload={"card": done_card.to_dict(), "callId": call_id},
                ))
                self._progress_tracker.tool_result_received(
                    skill_name, skill_result.success, result_content[:80])
                self._loop_detector.record_result(skill_result.success)

                if not skill_result.success:
                    if self._backoff_retry.should_retry(skill_name):
                        delay = self._backoff_retry.record_failure(skill_name)
                        logger.info(
                            f"[AgentLoop] {skill_name} 失败，指数退避重试(延迟{delay:.1f}s, 上限3次)")
                        self._trace(session_id, "tool_retry", {
                            "skill_name": skill_name, "delay": delay,
                            "attempt": self._backoff_retry.get_stats(skill_name).get("attempts", 0),
                        })
                        await asyncio.sleep(delay)
                        try:
                            retry_result = await asyncio.to_thread(self._skill_router.invoke, skill_name, args)
                            if retry_result.success:
                                result_content = retry_result.output
                                self._backoff_retry.record_success(skill_name)
                                self._trace(session_id, "tool_retry_success", {
                                    "skill_name": skill_name,
                                    "output_preview": result_content[:200],
                                })
                                skill_result = retry_result
                        except Exception as retry_err:
                            logger.warning(f"[AgentLoop] 重试{skill_name}也失败: {retry_err}")
                    else:
                        self._backoff_retry.reset(skill_name)
                        if self._goap_integration and self._goap_integration.is_goap_mode:
                            completed = [
                                r["skill_name"] for r in self._tool_call_records
                                if r.get("round", 0) < round_num
                            ]
                            try:
                                new_plan = self._replanner.replan_from_failure(
                                    user_request=user_message,
                                    failed_action=skill_name,
                                    failure_reason=skill_result.error or result_content[:200],
                                    completed_actions=completed,
                                    current_state=self._build_current_world_state(),
                                )
                                if new_plan:
                                    self._emit(make_thinking_step(
                                        session_id, "goap_replan",
                                        f"GOAP重规划: 跳过{skill_name}, 新计划{len(new_plan.steps)}步",
                                        {"failed": skill_name, "new_steps": len(new_plan.steps)},
                                    ))
                            except Exception as e:
                                logger.warning(f"[AgentLoop] GOAP重规划失败: {e}")
                else:
                    self._backoff_retry.record_success(skill_name)

                # ★ v5.0 B-2: 文件写入后自动触发 LSP 诊断
                if skill_result.success and skill_name in (
                    "write_file", "edit_file", "apply_edit",
                    "create_file", "replace_in_file",
                ):
                    file_path = args.get("file_path", args.get("path", ""))
                    if file_path:
                        try:
                            from bridge.skills.lsp_skill import lsp_diagnose
                            diag_result = lsp_diagnose(
                                file_path=file_path, _lsp_manager=None)
                            if diag_result.success and diag_result.data:
                                errors = diag_result.data.get("errors", [])
                                if errors:
                                    self._emit(make_thinking_step(
                                        session_id, "lsp_diagnostic",
                                        f"LSP 诊断: {file_path} 发现 {len(errors)} 个问题",
                                        {"file_path": file_path, "errors": errors,
                                         "is_diagnostic": True},
                                    ))
                        except Exception as _lsp_err:
                            print(f"[AgentLoop] LSP诊断自动触发失败: {_lsp_err}", flush=True)

                if skill_name in ("file_edit", "file_write", "file_read", "file_delete", "file_create"):
                    self._trace(session_id, "file_changed", {
                        "skill": skill_name,
                        "path": args.get("path", args.get("file_path", args.get("filename", ""))),
                        "success": skill_result.success,
                        "output_preview": result_content[:100],
                    })

                self._check_intermediate_findings(
                    session_id, skill_name, skill_result, total_tool_calls)

                if skill_result.data and isinstance(skill_result.data, dict):
                    if skill_result.data.get("needs_llm"):
                        messages.append({
                            "role": "tool",
                            "content": skill_result.output,
                            "tool_call_id": call_id,
                        })
                        continue
                messages.append({
                    "role": "tool",
                    "content": result_content,
                    "tool_call_id": call_id,
                })

            if loop_broken:
                break
        else:
            if not final_content:
                final_content = content or "Agent loop reached maximum iterations."

        self._progress_tracker.summarizing()
        self._emit_progress("progress_summary", "正在生成总结...", session_id=session_id)
        self._emit(make_thinking_step(
            session_id, "summarizing",
            f"生成分析报告 (共{len(self._tool_call_records)}次工具调用)",
            {"toolCount": len(self._tool_call_records)},
        ))

        if self._tool_call_records:
            final_content = await self._force_summarize_async(
                session_id, user_message, messages, loop_broken, final_content,
                engine_name=engine_name)
            logger.info(f"[AgentLoop] 总结生成完成: len={len(final_content)}, preview={final_content[:100]}")
        elif not final_content or loop_broken:
            final_content = self._force_summarize(
                session_id, user_message, messages, loop_broken)

        final_content = self._validate_and_fix(
            session_id, user_message, final_content)
        logger.info(f"[AgentLoop] 验证修复完成: len={len(final_content)}, preview={final_content[:100]}")

        self._progress_tracker.done()
        self._emit_progress("progress_done", "任务完成", session_id=session_id)

        self._emit(make_thinking_step(
            session_id, "done",
            f"任务完成, 报告长度{len(final_content)}字符",
            {"toolCallCount": len(self._tool_call_records),
             "reportLength": len(final_content)},
        ))

        self._emit(make_stream_end(session_id))

        if not final_content or not final_content.strip():
            logger.warning("[AgentLoop] final_content 为空！生成紧急兜底报告")
            final_content = self._build_fallback_summary(user_message)
            self._trace(session_id, "fallback_triggered", {
                "reason": "empty_final_content",
                "tool_calls": len(self._tool_call_records),
            })
            self._emit(make_force_summary(session_id, final_content, status="fallback"))

        logger.info(f"[AgentLoop] 发送最终结果: len={len(final_content)}")
        self._emit(make_done(final_content, session_id))
        self._trace(session_id, "final_response", {
            "content_length": len(final_content),
            "tool_call_count": len(self._tool_call_records),
            "loop_broken": loop_broken,
        })
        self._trace(session_id, "model_response", {
            "content_length": len(final_content),
            "tool_call_count": len(self._tool_call_records),
            "loop_broken": loop_broken,
        })
        self._trace(session_id, "turn_completed", {
            "user_message": user_message[:100],
            "response_length": len(final_content),
            "tool_calls": len(self._tool_call_records),
        })
        self._trace(session_id, "agent_completed", {
            "session_id": session_id,
            "total_tool_calls": len(self._tool_call_records),
            "loop_broken": loop_broken,
            "step_budget": self._step_budget,
            "step_budget_limit": self._step_budget_limit,
        })
        try:
            self._eval_harness(session_id)
        except Exception as _harness_err:
            logger.error("[AgentLoop] _eval_harness failed: %s", _harness_err)
        self._session_memory.add_message(session_id, "assistant", final_content,
                                          model=model_name)
        self._context_manager.append(session_id, "assistant", final_content)

        if self._plugin_system:
            try:
                self._plugin_system.emit("on_message", {
                    "session_id": session_id, "role": "assistant", "content": final_content,
                })
            except Exception:
                pass
            try:
                self._plugin_system.emit("after_process", {
                    "session_id": session_id, "tool_count": len(self._tool_call_records),
                })
            except Exception:
                pass

        if self._session_checkpoint:
            try:
                msg_count = self._session_msg_counts.get(session_id, 0) + 2
                self._session_msg_counts[session_id] = msg_count
                if self._session_checkpoint.should_auto_save(msg_count):
                    self._session_checkpoint.save(
                        session_id, msg_count,
                        summary=final_content[:200] if final_content else "",
                    )
            except Exception:
                pass

        if self._memory_distiller:
            try:
                if self._memory_distiller.should_distill():
                    await asyncio.to_thread(self._memory_distiller.auto_distill)
            except Exception:
                pass

        if self._reflection_loop is None:
            try:
                self._reflection_loop = ReflectionLoop()
            except Exception:
                pass

        if self._reflection_loop is not None:
            try:
                await asyncio.to_thread(
                    self._reflection_loop.reflect,
                    session_id,
                    user_message,
                    self._tool_call_records,
                    self._tool_result_records,
                    final_content,
                )
            except Exception:
                pass

        return final_content

    async def run_stream(self, session_id: str, user_message: str,
                         skill_hint: str = "", files: Optional[List[str]] = None,
                         engine_name: Optional[str] = None):
        self._session_memory.add_message(session_id, "user", user_message)
        self._context_manager.append(session_id, "user", user_message)

        if self._plugin_system:
            try:
                self._plugin_system.emit("on_message", {
                    "session_id": session_id, "role": "user", "content": user_message,
                })
            except Exception:
                pass

        if self._compactor:
            context = self._context_manager.smart_truncate(session_id)
        else:
            context = self._context_manager.truncate(session_id)

        system_msg = {"role": "system", "content": SYSTEM_PROMPT}
        messages = [system_msg] + context
        if skill_hint:
            messages.append({"role": "system",
                             "content": f"Use the '{skill_hint}' skill if relevant."})
        self._trace(session_id, "context_injected", {
            "message_count": len(messages), "skill_hint": skill_hint or "",
            "stream_mode": True,
        })
        engine = self._engine_manager.get_engine(engine_name)
        if engine is None:
            err = make_error(ErrorCode.ENGINE_UNAVAILABLE, "No AI engine available")
            self._emit(err)
            return
        model_name = engine.get_model_name()
        self._emit(make_stream_start(session_id=session_id, model=model_name))
        full_content = ""
        try:
            tokens = await asyncio.to_thread(
                self._collect_stream, messages, engine_name, **{},
            )
            for token in tokens:
                full_content += token
                self._emit(make_stream_delta(token, session_id))
        except Exception as e:
            self._emit(make_error(ErrorCode.INTERNAL, str(e), session_id))
            return
        self._emit(make_stream_end(session_id))
        self._emit(make_done(full_content, session_id))
        self._trace(session_id, "model_response", {
            "content_length": len(full_content), "stream_mode": True,
        })
        self._session_memory.add_message(session_id, "assistant", full_content,
                                          model=model_name)
        self._context_manager.append(session_id, "assistant", full_content)

    def cancel(self, session_id: str) -> None:
        engine = self._engine_manager.get_engine()
        if engine:
            engine.cancel()

    async def _generate_plan(self, session_id: str, user_message: str,
                              messages: List[Dict[str, Any]],
                              engine: Any, tools: list) -> Optional[dict]:
        if self._goap_integration is None:
            self._goap_integration = get_goap_integration()
            self._goap_integration.enable_goap_mode()
        try:
            goap_plan = self._goap_integration.process_request(user_message)
            if goap_plan and goap_plan.steps:
                steps = []
                for s in goap_plan.steps:
                    steps.append({
                        "skill": s.tool_suggestion or "auto",
                        "description": s.description,
                        "goap_action": s.goap_action,
                    })
                return {
                    "steps": steps,
                    "rationale": f"GOAP规划: {goap_plan.plan_id}, 目标={list(goap_plan.goal_state.facts.keys()) if goap_plan.goal_state else []}",
                    "plan_id": goap_plan.plan_id,
                }
        except Exception as e:
            logger.warning(f"[AgentLoop] GOAP规划失败，回退LLM规划: {e}")
        plan_prompt = {
            "role": "system",
            "content": (
                "Based on the user's request and available tools, generate an execution plan. "
                "Return a JSON object with 'steps' (array of {skill, args, description}) "
                "and 'rationale' (string). Only include steps that are necessary. "
                "Respond with ONLY the JSON, no other text."
            ),
        }
        plan_messages = messages[:6] + [plan_prompt]
        try:
            result = await asyncio.to_thread(
                self._engine_manager.chat_with_tools,
                plan_messages, tools,
            )
            content = result.get("content", "")
            if not content and result.get("tool_calls"):
                content = str(result["tool_calls"])
            if content:
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    plan = json.loads(json_match.group())
                    if "steps" in plan:
                        return plan
        except Exception as e:
            logger.warning(f"Plan generation failed: {e}")
        return {"steps": [{"skill": "auto", "description": "Execute automatically"}], "rationale": "Auto-generated plan"}

    def _mcp_fallback_lookup(self, tool_name: str) -> Optional[Dict]:
        try:
            from bridge.mcp.mcp_tool_adapter import MCPToolAdapter
            adapter = MCPToolAdapter()
            tools = adapter.list_tools()
            for tool in tools:
                if tool.get("name") == tool_name:
                    return {
                        "id": f"mcp_{tool.get('server_name', '')}_{tool_name}",
                        "name": tool_name,
                        "description": tool.get("description", ""),
                        "parameters": tool.get("inputSchema", {}),
                        "category": "mcp",
                    }
            return None
        except Exception as e:
            logger.warning("[AgentLoop] _mcp_fallback_lookup failed for '%s': %s", tool_name, e)
            return None

    def _smart_tool_routing(self, skill_name: str, args: dict) -> tuple:
        """智能工具路由 - 减少无效调用"""
        from bridge.core.loop_detector import _FILE_READ_SKILLS

        if skill_name in _FILE_READ_SKILLS:
            file_path = args.get("file_path", args.get("path", ""))
            if file_path:
                last_reads = [
                    r for r in self._loop_detector._history[-5:]
                    if r.skill_name in _FILE_READ_SKILLS
                    and r.args.get("file_path", r.args.get("path")) == file_path
                ]
                if last_reads:
                    return False, "文件 " + str(file_path) + " 已在最近读取过，无需重复读取"

        if skill_name in _FILE_READ_SKILLS:
            pending_reads = []
            for r in self._loop_detector._history[-3:]:
                if r.skill_name in _FILE_READ_SKILLS:
                    path = r.args.get("file_path", r.args.get("path", ""))
                    if path and path not in pending_reads:
                        pending_reads.append(path)
            if len(pending_reads) >= 3:
                return False, "已批量读取 " + str(len(pending_reads)) + " 个文件，应开始分析而不是继续读取"

        total_files_read = sum(
            1 for r in self._loop_detector._history
            if r.skill_name in _FILE_READ_SKILLS
        )
        if total_files_read >= 10:
            return False, "已读取足够多的文件，请基于已有信息回答"

        return True, ""

    def _generate_forced_summary(self, session_id: str, messages: List[Dict[str, Any]]) -> str:
        """生成结构化强制总结"""
        tool_calls = self._loop_detector._history
        total_calls = len(tool_calls)
        skill_counts: Dict[str, int] = {}
        for call in tool_calls:
            skill_counts[call.skill_name] = skill_counts.get(call.skill_name, 0) + 1

        files_read = [
            r.args.get("file_path", r.args.get("path", ""))
            for r in tool_calls
            if r.skill_name in ("file_read", "read_file", "cat_file", "get_file_content")
            and r.args.get("file_path", r.args.get("path"))
        ]

        summary_parts = [
            "[Agent Execution Summary]",
            "=" * 40,
            "Statistics:",
            "  - Total calls: " + str(total_calls),
            "  - Tools used: " + str(len(skill_counts)),
            "",
            "Tool usage:",
        ]
        for skill, count in sorted(skill_counts.items(), key=lambda x: -x[1]):
            summary_parts.append("  - " + skill + ": " + str(count) + " times")

        if files_read:
            summary_parts.append("")
            summary_parts.append("Files read:")
            for f in files_read[:15]:
                summary_parts.append("  - " + str(f))

        summary_parts.append("")
        summary_parts.append("Suggestion: Based on the above information, answer the user question directly.")
        summary_parts.append("If information is insufficient, clearly state what is missing.")
        summary_parts.append("=" * 40)

        summary = "\n".join(summary_parts)

        messages.append({
            "role": "system",
            "content": summary,
        })

        self._emit(make_force_summary(session_id, summary, status="partial"))
        return summary

    async def _force_summarize_async(self, session_id: str, user_message: str,
                                      messages: List[Dict[str, Any]],
                                      loop_broken: bool,
                                      existing_content: str = "",
                                      engine_name: Optional[str] = "") -> str:
        """增强版异步总结生成 - 永远返回有效内容
        
        核心改进：
        1. 使用精简的上下文（仅工具结果）而非完整对话历史，避免上下文过长导致总结失败
        2. 使用更明确的 prompt 要求生成详细分析
        3. 增加重试机制：首次总结过短时自动重试
        4. 确保无论如何都返回有意义的内容
        """

        logger.info(f"[AgentLoop] _force_summarize_async 开始: tool_calls={len(self._tool_call_records)}, loop_broken={loop_broken}, engine={engine_name}")

        if loop_broken or not self._tool_call_records:
            template = self._force_summarize(session_id, user_message, messages, loop_broken)
            logger.info(f"[AgentLoop] 返回模板总结: len={len(template)}")
            return template

        # ★ 关键改进 1: 构建更丰富的工具结果文本
        tool_results_text = ""
        for i, record in enumerate(self._tool_call_records[:25]):
            skill_name = record.get("skill_name", "unknown")
            args_str = json.dumps(record.get("args", {}), ensure_ascii=False)[:120]
            result_text = (self._tool_result_records[i] if i < len(self._tool_result_records) else "(无输出)")
            result_text = result_text[:600] if result_text else "(无输出)"
            tool_results_text += f"\n### 工具{i+1}: {skill_name}\n参数: {args_str}\n结果: {result_text}\n"

        # ★ 关键改进 2: 构建更明确、要求更高的分析 prompt
        summary_prompt = (
            f"请仔细分析以下项目信息，并撰写一份详尽的分析报告。\n\n"
            f"【用户问题】\n{user_message}\n\n"
            f"【执行的工具调用和结果】\n{tool_results_text}\n\n"
            f"【报告要求 - 必须严格遵守】\n"
            f"请用中文撰写一份详细的分析报告，至少 300 字，必须包含以下章节：\n\n"
            f"1. **项目概述**：这个项目是做什么的？主要功能、目标和应用场景是什么？\n"
            f"2. **技术分析**：使用了哪些技术栈、框架和工具？架构设计有什么特点？\n"
            f"3. **市场对比**：市面上是否有类似定位的项目？这个项目与它们有何不同？核心差异是什么？\n"
            f"4. **创新亮点**：具体有哪些技术创新点或独特之处？请逐一说明。\n"
            f"5. **总结与价值**：综合评价这个项目的价值、潜力和改进方向。\n\n"
            f"【重要提示】\n"
            f"- 必须基于上面的工具结果进行分析，引用具体文件名、类名、函数名\n"
            f"- 每个章节至少 50 字，全文不少于 300 字\n"
            f"- 如果工具结果中信息不足，请基于已有信息做合理推断，并注明\"待验证\"\n"
            f"- 不要写\"信息不足\"之类的废话，尽可能多地输出分析内容"
        )

        # ★ 关键改进 3: 使用更强的系统 prompt
        summary_messages = [
            {"role": "system", "content": (
                "你是一位资深的软件项目分析师和技术顾问。"
                "你的任务是根据提供的工具调用结果，撰写一份详尽、专业、有深度的分析报告。"
                "报告必须用中文撰写，内容要具体、有据可依，长度至少 300 字。"
                "不要偷懒，不要只写几句话就结束。"
                "每个章节都要有实质内容，引用具体的技术细节。"
            )},
            {"role": "user", "content": summary_prompt},
        ]

        try:
            logger.info(f"[AgentLoop] 尝试 LLM 增强总结... (精简上下文, 仅 {len(summary_messages)} 条消息)")
            llm_response = await asyncio.to_thread(
                self._engine_manager.chat,
                summary_messages,
                engine_name=engine_name or None,
            )

            llm_summary = self._extract_llm_text(llm_response)
            logger.info(f"[AgentLoop] LLM 响应: len={len(llm_summary)}, preview={llm_summary[:150]}")

            # ★ 关键改进 4: 提高最低长度要求到 150 字
            if llm_summary and len(llm_summary.strip()) > 150:
                summary = self._build_enhanced_summary(llm_summary, user_message, session_id)
                logger.info(f"[AgentLoop] 返回增强报告: len={len(summary)}")
                return summary

            # 第一次总结过短 - 用更直接的 prompt 重试
            logger.warning(f"[AgentLoop] 首次总结过短: len={len(llm_summary)}, 尝试重试...")
            retry_prompt = (
                f"请用中文详细回答以下问题，至少写 200 字：\n\n"
                f"问题: {user_message}\n\n"
                f"已知信息（工具调用结果）:\n{tool_results_text[:4000]}\n\n"
                f"请详细分析：\n"
                f"1. 这个项目是什么，有什么用\n"
                f"2. 使用了哪些技术和框架\n"
                f"3. 与市场上类似项目的对比\n"
                f"4. 有哪些创新和亮点\n"
                f"请务必写够字数，内容要具体详细。"
            )
            retry_messages = [
                {"role": "system", "content": "你是资深分析师，必须用中文详细回答，至少200字。不要偷懒。"},
                {"role": "user", "content": retry_prompt},
            ]
            retry_response = await asyncio.to_thread(
                self._engine_manager.chat,
                retry_messages,
                engine_name=engine_name or None,
            )
            retry_summary = self._extract_llm_text(retry_response)
            logger.info(f"[AgentLoop] 重试 LLM 响应: len={len(retry_summary)}, preview={retry_summary[:100]}")

            if retry_summary and len(retry_summary.strip()) > 150:
                summary = self._build_enhanced_summary(retry_summary, user_message, session_id)
                logger.info(f"[AgentLoop] 返回重试报告: len={len(summary)}")
                return summary

            logger.warning(f"[AgentLoop] 重试总结仍然过短: len={len(retry_summary)}，使用 fallback")
            final_llm_text = llm_summary or retry_summary or ""

        except Exception as e:
            logger.error(f"[AgentLoop] LLM 增强总结异常: {e}")
            self._trace(session_id, "summarize_failed", {"error": str(e)})
            final_llm_text = ""

        # ★ 关键改进 5: Fallback 也包含实际分析内容
        if final_llm_text and len(final_llm_text.strip()) > 10:
            summary = self._build_enhanced_summary(final_llm_text, user_message, session_id)
            logger.info(f"[AgentLoop] 使用部分 LLM 内容生成报告: len={len(summary)}")
            return summary

        fallback = self._build_fallback_summary(user_message)
        logger.info(f"[AgentLoop] 返回 fallback 报告: len={len(fallback)}")
        self._emit(make_force_summary(session_id, fallback, status="partial"))
        return fallback

    def _extract_llm_text(self, response: Any) -> str:
        """从各种 LLM 响应格式中提取文本"""
        if not response:
            return ""
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            return (
                response.get("content", "") or
                response.get("message", {}).get("content", "") or
                str(response)
            )
        if hasattr(response, "choices") and response.choices:
            return response.choices[0].message.content or ""
        return str(response)

    def _build_enhanced_summary(self, llm_summary: str, user_message: str,
                                 session_id: str = "") -> str:
        """构建增强版总结报告 - 使用中文标题"""
        tool_count = len(self._tool_call_records)
        skill_names = list({r["skill_name"] for r in self._tool_call_records})
        all_results_text = "\n".join(self._tool_result_records[-10:]) if self._tool_result_records else ""
        core_findings = self._extract_core_findings(
            [{"role": "tool", "content": all_results_text}] if all_results_text else [])

        findings_text = "\n".join(f"- {f}" for f in core_findings[:10]) if core_findings else "暂无明确发现"

        detail_parts: List[str] = []
        for i, record in enumerate(self._tool_call_records):
            result = self._tool_result_records[i] if i < len(self._tool_result_records) else ""
            result_text = (result or "(无输出)")[:150].strip()
            args_preview = json.dumps(record.get("args", {}), ensure_ascii=False)[:80]
            detail_parts.append(f"{i + 1}. [{record['skill_name']}] {args_preview} -> {result_text}")

        if detail_parts:
            detailed = "\n".join(detail_parts[:15])
        elif self._tool_call_records:
            parts = []
            for i, record in enumerate(self._tool_call_records[:15]):
                parts.append(f"{i + 1}. [{record['skill_name']}] (结果未记录)")
            detailed = "\n".join(parts)
        else:
            detailed = "无工具调用记录"
        elapsed = self._progress_tracker.get_elapsed_seconds()

        summary = (
            "## Agent 分析报告\n"
            "---\n"
            f"**任务状态**: 分析完成\n"
            f"**工具调用**: {tool_count} 次\n"
            f"**使用工具**: {', '.join(skill_names)}\n"
            f"**耗时**: {elapsed:.1f}秒\n"
            "\n### LLM 分析\n"
            + llm_summary + "\n"
            "\n### 关键发现\n"
            + findings_text + "\n"
            "\n### 工具调用摘要\n"
            + detailed + "\n"
            "---\n"
            "*本报告由 Lemon Agent 自动生成*"
        )

        self._emit(make_force_summary(session_id, summary, status="complete"))
        return summary

    def _build_current_world_state(self) -> "WorldState":
        from bridge.core.goap_planner import WorldState
        facts: Dict[str, Any] = {}
        called_skills = {r["skill_name"] for r in self._tool_call_records}
        skill_to_fact = {
            "scan_project": "project_scanned",
            "batch_read_files": "files_read",
            "file_read": "file_read",
            "read_file": "file_read",
            "file_search": "files_searched",
            "code_search": "code_searched",
            "edit_file": "file_edited",
            "write_file": "file_created",
            "execute_code": "code_executed",
            "search_web": "web_searched",
            "fetch_url": "url_fetched",
        }
        for skill_name in called_skills:
            fact_key = skill_to_fact.get(skill_name)
            if fact_key:
                facts[fact_key] = True
        for i, rec in enumerate(self._tool_call_records):
            if i < len(self._tool_result_records):
                if self._tool_result_records[i] and len(self._tool_result_records[i]) > 10:
                    facts[f"_tool_{rec['skill_name']}_has_result"] = True
        return WorldState(facts=facts)

    def _build_fallback_summary(self, user_message: str) -> str:
        """构建兜底总结（不依赖 LLM）- 包含实际工具结果分析"""
        tool_count = len(self._tool_call_records)
        skill_names = list({r["skill_name"] for r in self._tool_call_records})
        elapsed = self._progress_tracker.get_elapsed_seconds()

        # 构建工具详情
        tool_details = []
        for i, record in enumerate(self._tool_call_records[:15]):
            skill = record.get("skill_name", "unknown")
            args_str = json.dumps(record.get("args", {}), ensure_ascii=False)[:80]
            result_preview = ""
            if i < len(self._tool_result_records):
                result_preview = (self._tool_result_records[i] or "(无输出)")[:80]
            tool_details.append(f"  {i+1}. [{skill}] {args_str} → {result_preview}")
        tool_records_str = "\n".join(tool_details) if tool_details else "  无工具调用记录"

        # 提取关键信息片段
        key_info_fragments = []
        for result in self._tool_result_records[:15]:
            if result:
                lines = result.split('\n')
                for line in lines[:3]:
                    line = line.strip()
                    if len(line) > 20 and len(line) < 300:
                        key_info_fragments.append(line)
                        if len(key_info_fragments) >= 8:
                            break
                if len(key_info_fragments) >= 8:
                    break

        key_info_str = "\n".join(f"  • {f}" for f in key_info_fragments) if key_info_fragments else "  未能提取到关键信息"

        return (
            "## Agent 执行报告（自动生成）\n"
            "========================================\n"
            f"**状态**: 分析完成\n"
            f"**工具调用**: {tool_count} 次\n"
            f"**使用工具**: {', '.join(skill_names) if skill_names else '无'}\n"
            f"**耗时**: {elapsed:.1f}s\n"
            "\n### 关键信息提取\n"
            + key_info_str + "\n"
            "\n### 工具调用详情\n"
            + tool_records_str + "\n"
            "\n### 说明\n"
            "本报告由 Agent 自动生成，基于工具调用结果的摘要。\n"
            "如需更详细的分析内容，请查看上方工具调用记录。\n"
            "========================================"
        )

    def _force_summarize(self, session_id: str, user_message: str,
                         messages: List[Dict[str, Any]], loop_broken: bool) -> str:
        status = "部分完成" if loop_broken else "分析完成"
        tool_count = len(self._tool_call_records)
        skill_names = list({r["skill_name"] for r in self._tool_call_records})
        core_findings = self._extract_core_findings(messages)
        elapsed = self._progress_tracker.get_elapsed_seconds()

        if core_findings:
            findings_text = "\n".join(f"- {f}" for f in core_findings)
        else:
            findings_text = "暂无明确发现"

        detail_parts: List[str] = []
        for i, (record, result) in enumerate(
                zip(self._tool_call_records, self._tool_result_records)):
            detail_parts.append(
                f"{i + 1}. [{record['skill_name']}] {result[:150].strip()}"
            )
        detailed = "\n".join(detail_parts) if detail_parts else "无详细工具调用记录"

        if not core_findings and not detail_parts and tool_count > 0:
            logger.warning("[AgentLoop] 工具调用结果为空，生成基础兜底报告。")
            skill_list = list({r["skill_name"] for r in self._tool_call_records})
            basic_report = (
                f"## 分析报告\n\n"
                f"**状态**: {status}\n"
                f"**工具调用**: {tool_count} 次\n"
                f"**覆盖工具**: {', '.join(skill_list) if skill_list else '无'}\n"
                f"**耗时**: {elapsed:.1f}s\n\n"
                f"### 执行记录\n"
            )
            for i, record in enumerate(self._tool_call_records[:20]):
                args_str = json.dumps(record.get("args", {}), ensure_ascii=False)[:80]
                basic_report += f"  {i + 1}. {record['skill_name']}({args_str})\n"
            basic_report += (
                f"\n### 结论\n"
                f"已调用 {tool_count} 次工具，但未获得有效结果。"
                f"{'任务被中断（循环检测）。' if loop_broken else '建议检查工具配置或重试。'}\n"
            )
            self._emit(make_force_summary(session_id, basic_report, status="partial"))
            return basic_report

        conclusion = "已根据已收集信息生成初步结论。" if loop_broken else "分析已完成。"

        summary = _REPORT_TEMPLATE.format(
            status=status,
            tool_call_count=tool_count,
            tools_covered=", ".join(skill_names) if skill_names else "无",
            elapsed=elapsed,
            core_findings=findings_text,
            detailed_analysis=detailed,
            conclusion=conclusion,
        )

        self._emit(make_force_summary(session_id, summary, status="partial" if loop_broken else "complete"))

        return summary

    def _validate_and_fix(self, session_id: str, user_question: str,
                          summary: str) -> str:
        validation = self._result_validator.validate(
            summary, user_question,
            self._tool_call_records, self._tool_result_records,
        )
        if validation.score >= 4:
            return summary
        if self._result_validator.should_retry(validation):
            fallback = self._result_validator.generate_fallback_summary(
                self._tool_call_records, self._tool_result_records, user_question,
            )
            return fallback
        return summary

    def _check_intermediate_findings(self, session_id: str, skill_name: str,
                                     skill_result: SkillResult,
                                     total_calls: int) -> None:
        if not skill_result.success or not skill_result.output:
            return
        output = skill_result.output
        findings: List[str] = []

        important_patterns = [
            (r'(?:发现|检测到|找到|识别)[：:]?\s*(.+?)(?:\n|$)', "high"),
            (r'(?:核心|关键|重要)[：:]?\s*(.+?)(?:\n|$)', "high"),
            (r'(?:包含|由|使用|基于)[：:]?\s*(.+?)(?:\n|$)', "normal"),
        ]
        for pattern, importance in important_patterns:
            for match in re.finditer(pattern, output):
                text = match.group(1).strip()[:200]
                if text:
                    findings.append(text)
                    self._progress_tracker.add_finding(
                        content=text, source_skill=skill_name,
                        importance=importance, files_analyzed=total_calls,
                    )
                    self._emit_finding(
                        session_id, text, skill_name, importance, total_calls)

        finding_summary = self._progress_tracker.generate_finding_summary(
            interval=FINDING_INTERVAL)
        if finding_summary:
            self._emit_finding(session_id, finding_summary, skill_name,
                               importance="high", files_analyzed=total_calls)

    @staticmethod
    def _extract_core_findings(messages: List[Dict[str, Any]]) -> List[str]:
        findings: List[str] = []
        seen: set = set()

        cn_patterns = [
            r'(?:发现|检测到|找到|识别|包含|由|使用|基于|采用|实现)[：:]?\s*(.+?)(?:\n|$)',
            r'(?:核心|关键|重要|主要|核心架构|技术栈|功能)[：:]?\s*(.+?)(?:\n|$)',
            r'(?:这是|该|此|这个)[一 ]?(?:项目|代码|文件|模块)[：:]?\s*(.+?)(?:\n|$)',
        ]
        en_patterns = [
            r'(?:found|detected|identified|contains|includes)[：:]?\s*(.+?)(?:\n|$)',
            r'(?:core|key|main|important|primary)[：:]?\s*(.+?)(?:\n|$)',
            r'(?:this|the)[：:]?\s*(?:project|code|file|module)[：:]?\s*(.+?)(?:\n|$)',
            r'(?:built|created|implemented|developed)[：:]?\s*(.+?)(?:\n|$)',
            r'(?:uses|employs|leverages)[：:]?\s*(.+?)(?:\n|$)',
        ]

        for msg in messages:
            content = msg.get("content", "")
            if not content or msg.get("role") == "system":
                continue
            patterns = cn_patterns + en_patterns
            for pattern in patterns:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    text = match.group(1).strip()[:200]
                    if text and text not in seen:
                        seen.add(text)
                        findings.append(text)
                    if len(findings) >= 15:
                        return findings

        if not findings:
            for msg in messages:
                content = msg.get("content", "")
                if msg.get("role") == "tool" and content:
                    for line in content.split('\n')[:5]:
                        line = line.strip()[:150]
                        if line and len(line) > 10:
                            findings.append(line)
                    if len(findings) >= 5:
                        break

        return findings[:10]
