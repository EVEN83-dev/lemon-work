# -*- coding: utf-8 -*-
"""shared/skills_builtin/scheduler_skills.py — 调度器四个内置技能

每个技能 = SkillDef(description 中文 + JSON Schema)，参数示例以 description/enum 内联承载
由 register_scheduler_skills() 调用 SkillsRegistry.register() 公开 API 注册到冻结区
注册表，绝不改冻结区文件。引擎通过 SchedulerEngine.instance() 单例获取，
Qt 耦合留给 main.py 启动编排区（attach_commander）。
"""
from datetime import datetime
from typing import Dict, Any
import json
import sys as _sys

# SkillDef 导入：直接走规范定义（冻结区只读 import，不写文件）
# bridge.skills.models.SkillDef 早已分叉（字段完全不同），主仓实现为准
if 'standard_mode' not in _sys.modules and 'D:\\xiaomi_temp\\lemon_agent\\standard_mode' not in _sys.path:
    import os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from standard_mode.core.skills_registry import SkillDef, SkillResult


def _engine():
    """获取调度器单例；不可用时返回 None（由处理器显式报错，不假返回值）。"""
    try:
        return __import__("shared.scheduler", fromlist=["SchedulerEngine"]).SchedulerEngine.instance()
    except Exception as e:
        return None


def _run_create(args: Dict[str, Any]) -> SkillResult:
    eng = _engine()
    if eng is None:
        return SkillResult(success=False, error="调度引擎未就绪（SchedulerEngine 单例初始化失败或尚未挂载）")
    ok = "trigger" in args and "action" in args
    if not ok:
        return SkillResult(success=False,
                           error="缺少必填参数：trigger（触发表达式）与 action（{'skill':..,'args':..} 或 {'command':..,'mode':..}）")
    rs = eng.create_job(
        trigger=args["trigger"], action=args["action"],
        name=args.get("name"), max_retry=int(args.get("max_retry", 2)),
        enabled=bool(args.get("enabled", True)),
    )
    if not rs["success"]:
        return SkillResult(success=False, error=rs["error"])
    return SkillResult(success=True, output=f"已创建任务: {rs['job']['job_id']} ({rs['job']['name']})",
                       data=rs["job"])


def _run_list(args: Dict[str, Any]) -> SkillResult:
    eng = _engine()
    if eng is None:
        return SkillResult(success=False, error="调度引擎未就绪")
    rs = eng.list_jobs()
    jobs = rs["jobs"]
    if not jobs:
        return SkillResult(success=True, output="当前无任务，可用 scheduler_create 创建", data=[])
    out_lines = [f"共 {rs['count']} 个任务：\n"]
    for j in jobs:
        status_icon = {"idle": "○", "running": "▶", "retrying": "⟲",
                       "failed": "✗", "cancelled": "⊘", "queued": "⏳"}.get(j["state"], "?")
        nr = j.get("next_run") or "已停用"
        out_lines.append(
            f"  {status_icon} {j['job_id']} | {j['name']} | {j['trigger']} | "
            f"状态={j['state']} | 延迟={j.get('trigger_parsed')} | 下次={nr} | 已执行={j['run_count']}\n"
        )
    return SkillResult(success=True, output="".join(out_lines).rstrip(), data=jobs)


def _run_cancel(args: Dict[str, Any]) -> SkillResult:
    eng = _engine()
    if eng is None:
        return SkillResult(success=False, error="调度引擎未就绪")
    job_id = (args.get("job_id") or "").strip()
    if not job_id:
        return SkillResult(success=False, error="缺少必填参数 job_id")
    rs = eng.cancel_job(job_id)
    if not rs["success"]:
        return SkillResult(success=False, error=rs["error"])
    return SkillResult(success=True, output=f"已取消任务: {job_id} (state=cancelled)", data=rs)


def _run_run_now(args: Dict[str, Any]) -> SkillResult:
    eng = _engine()
    if eng is None:
        return SkillResult(success=False, error="调度引擎未就绪")
    job_id = (args.get("job_id") or "").strip()
    if not job_id:
        return SkillResult(success=False, error="缺少必填参数 job_id")
    rs = eng.run_now(job_id)
    if not rs["success"]:
        return SkillResult(success=False, error=rs["error"])
    note = rs.get("note") if rs.get("queued") else f"已触发（耗时 {rs.get('elapsed_sec')}s）"
    return SkillResult(success=True, output=f"立即触发: {job_id} - {note}", data=rs)


_SCHEDULER_CREATE = SkillDef(
    name="scheduler_create",
    description="创建定时调度任务（interval/daily/once 三种触发，skill 或 command 两种动作）。",
    parameters={
        "type": "object",
        "properties": {
            "trigger": {"type": "string", "description": "触发表达式：interval '30s'/'10m'/'2h'、daily '09:30'、once '2026-09-30 10:00' 或 ISO 8601。非法表达式拒绝而非猜默认值。"},
            "action": {"type": "object", "describe": "动作：{'skill': 已注册技能名, 'args': {参数}} 或 {'command': '自然语言指令', 'mode': 'auto'|'manual'}。二选一。"},
            "name": {"type": "string", "description": "任务可读名称（为空则自动生成）。"},
            "max_retry": {"type": "integer", "description": "失败重试次数（默认 2，指数退避），0=不重试。"},
            "enabled": {"type": "boolean", "description": "创建后是否立即启用（默认 true）。"},
        },
        "required": ["trigger", "action"],
    },
    handler=_run_create,
    category="scheduler",
    timeout=30,
    skip_reason="",
)

_SCHEDULER_LIST = SkillDef(
    name="scheduler_list",
    description="列出全部调度任务（含状态、触发方式、下次执行时间、已执行次数）。",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_run_list,
    category="scheduler",
    timeout=15,
    skip_reason="",
)

_SCHEDULER_CANCEL = SkillDef(
    name="scheduler_cancel",
    description="取消（禁用）指定任务并落盘，取消后不再触发。",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "要取消的任务 ID（scheduler_create 返回的 job_id）。"},
        },
        "required": ["job_id"],
    },
    handler=_run_cancel,
    category="scheduler",
    timeout=15,
    skip_reason="",
)

_SCHEDULER_RUN_NOW = SkillDef(
    name="scheduler_run_now",
    description="立即手动触发一次指定任务（不改下次计划时间；引擎忙时入等待队列 state=queued）。",
    parameters={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "要立即触发的任务 ID。"},
        },
        "required": ["job_id"],
    },
    handler=_run_run_now,
    category="scheduler",
    timeout=30,
    skip_reason="",
)


def register_scheduler_skills() -> dict:
    """公开运行时注册 API，由 main.py 启动编排区调用。返回 {'success': bool, 'registered': [...], 'errors': [...]}"""
    from standard_mode.core.skills_registry import get_skills_registry
    registry = get_skills_registry()
    errs, done = [], []
    for skill in (_SCHEDULER_CREATE, _SCHEDULER_LIST, _SCHEDULER_CANCEL, _SCHEDULER_RUN_NOW):
        try:
            registry.register(skill)
            done.append(skill.name)
        except Exception as e:
            errs.append(f"{skill.name}: {e}")
    return {"success": not errs, "registered": done,
            "errors": errs, "at": datetime.now().isoformat(timespec="seconds")}
