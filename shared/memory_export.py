# -*- coding: utf-8 -*-
"""
shared/memory_export.py — 记忆可视化导出（第362章 · 子任务3）
============================================================
职责（只读导出，禁止本模块"导入回写"——写明留给后续版本）：
    1) 汇总 shared/knowledge_base.py（KnowledgeBase + SessionMemory）
       与 shared/user_memory.py 的公开读取接口；
    2) 生成人类可读 Markdown 到 data/memory_export/YYYY-MM-DD.md；
       分节：用户画像事实（含时间衰减权重）/ 会话摘要 / 项目记忆 / 知识条目计数。
    3) 提供 memory_export 技能运行时注册（register_as_skill）。

铁律：
    - 只读导出（禁止本模块实现"导入回写"，留给后续版本）；
    - 文件路径：_REPO_ROOT = 本文件向上两级 → data/memory_export/YYYY-MM-DD.md；
    - 失败显式 success:false + 中文原因；禁止 mock TODO 桩；
    - 注册表引用走 get_skills_registry() 单例，禁止自实例化 SkillsRegistry。

公开 API：
    export_snapshot(output_dir: Optional[str] = None, ts: Optional[str] = None) -> dict
    get_last_snapshot_path() -> Optional[str]
    register_as_skill(registry=None) -> dict    # 运行时注册为正式技能
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any, Dict, List, Optional

# 项目根 = 本文件向上两级（shared → lemon_agent）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT_DIR = os.path.join(_REPO_ROOT, "data", "memory_export")


# ----------------------------------------------------------------
# 内部：延迟解析公开 API
# ----------------------------------------------------------------
def _resolve_kb():
    try:
        from shared.knowledge_base import KnowledgeBase, SessionMemory
        return KnowledgeBase, SessionMemory
    except ImportError:
        pass
    try:
        from knowledge_base import KnowledgeBase, SessionMemory
        return KnowledgeBase, SessionMemory
    except ImportError:
        pass
    return None, None


def _resolve_user_memory():
    try:
        import shared.user_memory as um
        return um
    except ImportError:
        pass
    try:
        import user_memory as um
        return um
    except ImportError:
        pass
    return None


def _resolve_registry(registry=None):
    if registry is not None:
        return registry
    try:
        from standard_mode.core.skills_registry import get_skills_registry
        return get_skills_registry()
    except ImportError:
        pass
    try:
        from core.skills_registry import get_skills_registry
        return get_skills_registry()
    except ImportError:
        return None


# ----------------------------------------------------------------
# 公开 API：export_snapshot
# ----------------------------------------------------------------
def export_snapshot(output_dir: Optional[str] = None,
                    ts: Optional[str] = None) -> Dict[str, Any]:
    """只读导出：知识库 + 会话记忆 + 用户画像 → 人类可读 Markdown。

    Returns: {"success": bool, "error": str, "data": {"path": ..., "sections_found": [...]}}
    """
    out_dir = output_dir or EXPORT_DIR
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        return {"success": False, "error": f"创建导出目录失败: {e}", "data": None}
    now = ts or _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = (ts or _dt.date.today().isoformat())
    # 真查询集合
    sections_found: List[str] = []
    errors: List[str] = []

    # ── 节 1：用户画像事实（含时间衰减权重）──
    profile_block, profile_err = _collect_user_profile()
    if profile_err:
        errors.append(profile_err)
    if profile_block is not None:
        sections_found.append("user_profile")

    # ── 节 2：会话摘要 ──
    sessions_block, sessions_err = _collect_session_summaries()
    if sessions_err:
        errors.append(sessions_err)
    if sessions_block is not None:
        sections_found.append("session_summaries")

    # ── 节 3：项目记忆 ──
    proj_block, proj_err = _collect_project_memories()
    if proj_err:
        errors.append(proj_err)
    if proj_block is not None:
        sections_found.append("project_memories")

    # ── 节 4：知识条目计数 ──
    counts_block, counts_err = _collect_knowledge_counts()
    if counts_err:
        errors.append(counts_err)
    if counts_block is not None:
        sections_found.append("knowledge_counts")

    md = _render_markdown(now, today, profile_block, sessions_block,
                          proj_block, counts_block)
    out_path = os.path.join(out_dir, f"{today}.md")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
    except Exception as e:
        return {"success": False, "error": f"写入 Markdown 失败: {e}",
                "data": {"path": out_path, "sections_found": sections_found}}
    # 验收：写入后必须可读（含 4 个节标题）
    try:
        written = open(out_path, "r", encoding="utf-8").read()
        required = ["用户画像事实", "会话摘要", "项目记忆", "知识条目计数"]
        missing = [h for h in required if h not in written]
        if missing:
            return {"success": False,
                    "error": f"写入后缺少节标题: {missing}",
                    "data": {"path": out_path, "sections_found": sections_found}}
    except Exception as e:
        return {"success": False,
                "error": f"写入后读回校验失败: {e}",
                "data": {"path": out_path, "sections_found": sections_found}}
    return {"success": True, "error": None,
            "data": {"path": out_path, "sections_found": sections_found,
                     "warnings": errors or None}}


# ----------------------------------------------------------------
# 收集器（只读）
# ----------------------------------------------------------------
def _collect_user_profile() -> tuple:
    """返回 (markdown_str_or_None, error_str_or_None)。"""
    um = _resolve_user_memory()
    if um is None:
        return None, "user_memory 模块不可用"
    lines: List[str] = ["## 一、用户画像事实（含时间衰减权重）", ""]
    try:
        profile = um.recall_user_profile(top_k=20)
    except Exception as e:
        return ("## 一、用户画像事实（含时间衰减权重）\n\n"
                f"> 调用 recall_user_profile 失败：{e}\n"), str(e)
    if not profile:
        lines.append("> （暂无用户画像事实 — 让 Agent 多聊几句后自动生成）")
        lines.append("")
        return "\n".join(lines), None
    for i, entry in enumerate(profile):
        if not isinstance(entry, dict):
            continue
        # 权重计算优先取 entry 已存 weight；否则显式调用 _decay_weight
        weight = entry.get("weight")
        ts_str = entry.get("ts", entry.get("timestamp", ""))
        if weight is None and ts_str and hasattr(um, "_decay_weight"):
            try:
                weight = um._decay_weight(ts_str)
            except Exception:
                weight = None
        lines.append(f"### {i + 1}. {entry.get('type', 'unknown')} "
                     f"— {entry.get('value', '')}")
        lines.append(f"- **出现次数**: {entry.get('count', 1)}")
        lines.append(f"- **权重**: {weight if weight is not None else 'N/A'}"
                     f"  （90 天时间衰减）")
        if ts_str:
            lines.append(f"- **最近记录**: {ts_str}")
        if entry.get("source"):
            lines.append(f"- **来源**: {entry['source']}")
        lines.append("")
    return "\n".join(lines), None


def _collect_session_summaries() -> tuple:
    """SessionMemory.get_session_summaries() 只读读取。"""
    _, SessionMemory = _resolve_kb()
    if SessionMemory is None:
        return None, "SessionMemory 不可用（knowledge_base）"
    lines: List[str] = ["## 二、会话摘要", ""]
    try:
        sm = SessionMemory(memory_dir=os.path.join(_REPO_ROOT, "data",
                                                   "session_memory"))
        summaries = sm.get_session_summaries(limit=20)
    except Exception as e:
        return ("## 二、会话摘要\n\n> 读取失败：{e}\n"), str(e)
    if not summaries:
        lines.append("> （暂无会话摘要）")
        lines.append("")
        return "\n".join(lines), None
    for i, s in enumerate(summaries):
        if not isinstance(s, dict):
            continue
        lines.append(f"### 会话 {s.get('session_id', i + 1)}")
        lines.append(f"- **摘要**: {s.get('summary', '(无)')[:300]}")
        lines.append(f"- **时间**: {s.get('ts', s.get('updated_at', ''))}")
        if s.get("tool_calls"):
            lines.append(f"- **工具调用**: {s['tool_calls']}")
        lines.append("")
    return "\n".join(lines), None


def _collect_project_memories() -> tuple:
    """SessionMemory.get_project_memories() 只读读取。"""
    _, SessionMemory = _resolve_kb()
    if SessionMemory is None:
        return None, "SessionMemory 不可用"
    lines: List[str] = ["## 三、项目记忆", ""]
    try:
        sm = SessionMemory(memory_dir=os.path.join(_REPO_ROOT, "data",
                                                   "session_memory"))
        mems = sm.get_project_memories(limit=30)
    except Exception as e:
        return ("## 三、项目记忆\n\n> 读取失败：{e}\n"), str(e)
    if not mems:
        lines.append("> （暂无项目记忆）")
        lines.append("")
        return "\n".join(lines), None
    categories: Dict[str, int] = {}
    for m in mems:
        if not isinstance(m, dict):
            continue
        cat = m.get("category", "general")
        categories[cat] = categories.get(cat, 0) + 1
        lines.append(f"- **[{cat}]** {m.get('content', '')[:200]}")
    lines.insert(1, f"（共 {len(mems)} 条；分类统计: "
                   f"{json.dumps(categories, ensure_ascii=False)}）")
    lines.append("")
    return "\n".join(lines), None


def _collect_knowledge_counts() -> tuple:
    """KnowledgeBase / SessionMemory 计数汇总。"""
    KnowledgeBase, SessionMemory = _resolve_kb()
    um = _resolve_user_memory()
    lines: List[str] = ["## 四、知识条目计数", ""]
    counts: Dict[str, Any] = {}
    if KnowledgeBase is not None:
        try:
            kb = KnowledgeBase()
            kb.load()
            counts["knowledge_base_scenes"] = kb.scene_count()
            kb_summary = kb.get_stats() if hasattr(kb, "get_stats") else {}
            counts["knowledge_stats"] = kb_summary
        except Exception as e:
            counts["knowledge_base_error"] = str(e)
    if SessionMemory is not None:
        try:
            sm = SessionMemory(memory_dir=os.path.join(_REPO_ROOT, "data",
                                                       "session_memory"))
            sm_summary = sm.get_summary() if hasattr(sm, "get_summary") else {}
            counts["session_summary"] = sm_summary
        except Exception as e:
            counts["session_memory_error"] = str(e)
    if um is not None and hasattr(um, "get_memory_stats"):
        try:
            counts["user_memory_stats"] = um.get_memory_stats()
        except Exception as e:
            counts["user_memory_error"] = str(e)
    for k, v in counts.items():
        lines.append(f"- **{k}**: {json.dumps(v, ensure_ascii=False, default=str)}")
    lines.append("")
    return "\n".join(lines), None


# ----------------------------------------------------------------
# Markdown 渲染
# ----------------------------------------------------------------
def _render_markdown(now: str, today: str, profile: Optional[str],
                     sessions: Optional[str], project: Optional[str],
                     counts: Optional[str]) -> str:
    parts = [
        f"# 记忆导出 · {today}",
        "",
        f"> 生成时间: {now}",
        "> 数据来源: shared/knowledge_base.py (KnowledgeBase + SessionMemory) "
        "+ shared/user_memory.py（全部只读；导入回写留给后续版本）",
        "",
    ]
    for section in (profile, sessions, project, counts):
        if section is not None:
            parts.append(section)
    parts.append("---")
    parts.append("")
    parts.append("> （本文件由 memory_export.export_snapshot() 生成，只读导出；"
                 "任何修改都会被下一次快照覆盖。）")
    parts.append("")
    return "\n".join(parts)


# ----------------------------------------------------------------
# 运行时技能注册
# ----------------------------------------------------------------
def register_as_skill(registry=None) -> Dict[str, Any]:
    """以正式技能注册 memory_export。

    Skill 名称: memory_export
    描述: 只读导出会话/项目/知识库/用户画像到 data/memory_export/YYYY-MM-DD.md
    参数: {"output_dir": {"type": "string", "description": "可选, 默认 data/memory_export"},
           "ts": {"type": "string", "description": "可选, 固定时间戳, 便于自动化测试"}}
    执行: export_snapshot(output_dir, ts) → 返回 JSON 文本
    """
    reg = _resolve_registry(registry)
    if reg is None:
        return {"success": False, "error": "注册表不可用"}
    try:
        from standard_mode.core.skills_registry import SkillDef, SkillResult
    except ImportError:
        from core.skills_registry import SkillDef, SkillResult

    def _handler(output_dir: str = "", ts: str = "") -> SkillResult:
        out = {"output_dir": output_dir or None, "ts": ts or None}
        r = export_snapshot(**out)
        if r["success"]:
            return SkillResult(success=True,
                               output="记忆导出完成: %s" % r["data"]["path"],
                               data=r["data"])
        return SkillResult(success=False, error=r.get("error", "未知"),
                           data=r.get("data"))

    skill = SkillDef(
        name="memory_export",
        description=("只读导出会话/项目/知识库/用户画像到 data/memory_export/YYYY-MM-DD.md"
                    "（分节：用户画像事实/会话摘要/项目记忆/知识条目计数）；"
                    "不含导入回写（留给后续版本）。"),
        parameters={
            "type": "object",
            "properties": {
                "output_dir": {"type": "string",
                               "description": "输出目录, 默认 data/memory_export"},
                "ts": {"type": "string",
                       "description": "可选时间戳, 便于测试"},
            },
            "required": [],
        },
        handler=_handler,
        category="memory",
        timeout=30,
    )
    reg.register(skill)
    return {"success": True, "data": {"name": "memory_export"}}


# ----------------------------------------------------------------
# 运行时助手
# ----------------------------------------------------------------
def get_last_snapshot_path(output_dir: Optional[str] = None) -> Optional[str]:
    """返回最近一次快照路径（按修改时间倒序）。"""
    d = output_dir or EXPORT_DIR
    if not os.path.isdir(d):
        return None
    best, best_ts = None, 0.0
    for name in os.listdir(d):
        if not name.endswith(".md"):
            continue
        p = os.path.join(d, name)
        try:
            mt = os.path.getmtime(p)
        except Exception:
            continue
        if mt > best_ts:
            best_ts, best = mt, p
    return best
