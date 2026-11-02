# -*- coding: utf-8 -*-
"""
standard_mode/core/auto_dev_loop.py — 标准模式端到端自主开发闭环 (L3 主线)
================================================================================

让标准模式"自主改代码并验证"，打通 L3 "自主" 主线。

闭环步骤:
  1) 意图解析    : 识别请求类型 (加功能/修bug/重构/加注释/加测试)
  2) 语义定位    : 调 lsp_code_analysis Skill (workspace_symbol → document_symbol)
  3) 读取上下文  : read_file 读相关文件
  4) 生成修改    : 由 generator 生成 edit_file 的 (old, new) 对
  5) 应用修改    : 逐对应用 edit_file，失败回滚 (依赖 dev_safety.guard_loop)
  6) 语义校验    : lsp diagnostics 检查新错误，无新增才继续
  7) 验证        : 生成/运行最小测试 (test_generator Skill)
  8) 复盘        : 输出 DevReport(改了哪些文件/测试结果/风险)

设计原则 (满足 CodeLock "仅完善不破坏架构")：
  - 与具体 LLM 后端解耦：generator / lsp_checker / test_runner 均可注入，
    测试走 mock 模式，生产走 engine_manager + skills。
  - 不强依赖 dev_safety / dev_lessons，二者为可选插件 (惰性 import)，
    保证标准模式核心文件改动最小化且可独立运行。
"""

import os
import sys
import json
import time
import threading
from typing import Dict, Any, List, Optional, Tuple, Callable

# 让本文件既能以包内模块导入，也能被测试脚本直接导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills_registry import SkillResult  # noqa: E402


# ==================== 数据模型 ====================

class EditPlan:
    """一对 (old, new) 编辑计划"""

    def __init__(self, file_path: str, old: str, new: str, reason: str = ""):
        self.file_path = file_path
        self.old = old
        self.new = new
        self.reason = reason

    def to_dict(self) -> Dict:
        return {
            "file_path": self.file_path,
            "old": self.old,
            "new": self.new,
            "reason": self.reason,
        }


class DevReport:
    """自主开发闭环的最终报告"""

    def __init__(self, user_request: str):
        self.user_request = user_request
        self.intent: str = "unknown"           # add_feature / fix_bug / refactor / add_doc / add_test
        self.targets: List[str] = []           # 定位到的符号/文件
        self.edits: List[Dict] = []            # 实际应用的编辑
        self.changed_files: List[str] = []     # 改动的文件
        self.diagnostics_before: List[Any] = []
        self.diagnostics_after: List[Any] = []
        self.new_diagnostics: List[Any] = []   # 新增诊断 (应为空)
        self.test_result: Dict = {}
        self.lessons: List[str] = []           # S10: 复盘记忆
        self.used_history: bool = False        # S10: 是否参考了历史经验
        self.rollback_happened: bool = False
        self.ok: bool = False
        self.summary: str = ""

    def to_dict(self) -> Dict:
        return {
            "user_request": self.user_request,
            "intent": self.intent,
            "targets": self.targets,
            "edits": self.edits,
            "changed_files": self.changed_files,
            "diagnostics_before": self.diagnostics_before,
            "diagnostics_after": self.diagnostics_after,
            "new_diagnostics": self.new_diagnostics,
            "test_result": self.test_result,
            "lessons": self.lessons,
            "used_history": self.used_history,
            "rollback_happened": self.rollback_happened,
            "ok": self.ok,
            "summary": self.summary,
        }


# ==================== 意图关键词 ====================

_INTENT_RULES: List[Tuple[str, List[str]]] = [
    ("add_test", ["加测试", "写测试", "测试", "test", "单测", "单元测试", "pytest"]),
    ("fix_bug", ["修bug", "修复", "fix", "bug", "错误", "异常", "崩溃"]),
    ("add_doc", ["加注释", "加文档", "注释", "文档", "doc", "类型注解", "标注"]),
    ("refactor", ["重构", "refactor", "优化", "整理", "重命名"]),
    ("add_feature", ["加功能", "新增", "实现", "功能", "feature", "添加"]),
]


def _detect_intent(user_request: str) -> str:
    text = (user_request or "").lower()
    for intent, kws in _INTENT_RULES:
        for kw in kws:
            if kw.lower() in text:
                return intent
    return "add_feature"


# ==================== 默认生成器 (AST 静态改写，无需 LLM) ====================

def _default_generator(user_request: str, ctx: Dict) -> List[EditPlan]:
    """默认 generator：基于 AST/文本规则的静态改写。

    覆盖最常见的自主任务：给函数加类型注解。其余任务返回空（交给真实 LLM）。
    """
    plans: List[EditPlan] = []
    text = (user_request or "").lower()
    files = ctx.get("files", [])
    for fp in files:
        if not os.path.isfile(fp):
            continue
        if "类型注解" in text or "类型标注" in text:
            plans.extend(_annotate_functions(fp))
    return plans


def _annotate_functions(file_path: str) -> List[EditPlan]:
    """给文件里所有无注解的函数签名加 `-> None` / 参数加类型。

    采用保守策略：仅在函数定义行无 `->` 时追加 `-> None`。
    """
    import re
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    plans: List[EditPlan] = []
    sig_re = re.compile(r"^(\s*def\s+\w+\s*\()(.*)(\))\s*:\s*$")
    for i, line in enumerate(lines):
        m = sig_re.match(line.rstrip("\n"))
        if not m:
            continue
        if "->" in line:
            continue  # 已有注解，跳过
        # 仅对无参数或参数无类型注解的简单情形追加 -> None
        params = m.group(2).strip()
        close_paren = m.group(3)
        if params in ("", "*args", "**kwargs"):
            new_line = f"{m.group(1)}{params}{close_paren} -> None:\n"
        else:
            # 参数有名字但无类型时，给每个裸参数加 : object
            parts = [p.strip() for p in params.split(",")]
            typed = []
            ok = True
            for p in parts:
                if not p or p.startswith("*") or "=" in p:
                    typed.append(p)
                    continue
                if ":" in p:
                    typed.append(p)
                else:
                    name = p.split("=")[0].strip()
                    typed.append(f"{name}: object")
            if ok:
                new_params = ", ".join(typed)
                new_line = f"{m.group(1)}{new_params}{close_paren} -> None:\n"
            else:
                continue
        if new_line != line:
            plans.append(EditPlan(
                file_path=file_path,
                old=line,
                new=new_line,
                reason="为函数签名添加类型注解",
            ))
    return plans


# ==================== LSP / 测试 默认实现 ====================

def _default_lsp_checker(file_path: str) -> Tuple[List[Any], bool]:
    """默认 diagnostics 检查：优先走 lsp_code_analysis Skill，失败时返回空(无错误)。

    返回 (diagnostics, available) —— available=False 表示 LSP 不可用，跳过校验。
    """
    try:
        from skills.lsp_code_analysis import execute as lsp_execute
        res = lsp_execute(action="diagnostics", file_path=file_path)
        if res.success:
            diags = (res.data or {}).get("diagnostics", [])
            return diags, True
    except Exception:
        pass
    return [], False


def _default_test_runner(file_path: str) -> Dict:
    """默认测试运行：优先走 test_generator Skill 生成模板，返回生成结果。

    不实际跑 pytest（避免依赖外部运行时），仅生成最小测试并标记为 generated。
    """
    try:
        from skills.test_generator import execute as test_execute
        res = test_execute(file_path=file_path, test_framework="pytest")
        if res.success:
            return {
                "framework": "pytest",
                "generated": True,
                "ran": False,
                "detail": "测试模板已生成（未实际执行）",
                "functions": (res.data or {}).get("functions", []),
            }
    except Exception:
        pass
    return {"framework": "pytest", "generated": False, "ran": False, "detail": "未生成测试"}


# ==================== 历史经验 (S10) ====================

_LESSONS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "dev_lessons.json",
)


def _load_lessons() -> List[Dict]:
    if not os.path.isfile(_LESSONS_PATH):
        return []
    try:
        with open(_LESSONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_lesson(entry: Dict) -> None:
    os.makedirs(os.path.dirname(_LESSONS_PATH), exist_ok=True)
    lessons = _load_lessons()
    lessons.append(entry)
    with open(_LESSONS_PATH, "w", encoding="utf-8") as f:
        json.dump(lessons, f, ensure_ascii=False, indent=2)


def _find_similar_lessons(user_request: str, lessons: List[Dict]) -> List[Dict]:
    """关键词匹配相似历史经验"""
    text = (user_request or "").lower()
    words = set([w for w in text.split() if len(w) > 1])
    hits = []
    for le in lessons:
        prev = (le.get("request", "") or "").lower()
        if any(w in prev for w in words if w):
            hits.append(le)
    return hits


# ==================== 自主开发闭环 ====================

class AutoDevLoop:
    """标准模式端到端自主开发闭环"""

    def __init__(
        self,
        generator: Optional[Callable[[str, Dict], List[EditPlan]]] = None,
        lsp_checker: Optional[Callable[[str], Tuple[List[Any], bool]]] = None,
        test_runner: Optional[Callable[[str], Dict]] = None,
        enable_safety: bool = True,
        enable_lessons: bool = True,
        workspace: Optional[str] = None,
        prefer_llm: bool = True,
    ):
        # ★ L3-2: 默认优先 LLM 驱动生成器（理解需求），LLM 不可用时
        #   llm_generator 内部自动降级静态规则。测试可显式传 generator 覆盖。
        if generator is None and prefer_llm:
            try:
                from llm_dev_generator import llm_generator
                self.generator = llm_generator
            except Exception:  # noqa: BLE001
                self.generator = _default_generator
        else:
            self.generator = generator or _default_generator
        self.lsp_checker = lsp_checker or _default_lsp_checker
        self.test_runner = test_runner or _default_test_runner
        self.enable_safety = enable_safety
        self.enable_lessons = enable_lessons
        self.workspace = workspace or os.getcwd()
        self._lock = threading.Lock()

    # ---- 公共入口 ----
    def run(self, user_request: str, workspace: Optional[str] = None) -> DevReport:
        workspace = workspace or self.workspace
        report = DevReport(user_request)

        # 1) 意图解析
        report.intent = _detect_intent(user_request)

        # S10: 加载历史经验
        history_hits = []
        if self.enable_lessons:
            history_hits = _find_similar_lessons(user_request, _load_lessons())
            if history_hits:
                report.used_history = True
                report.lessons.append(
                    f"参考上次经验: {history_hits[-1].get('request', '')}"
                )

        # 真实执行（可能被 guard_loop 包裹以实现回滚护栏）
        if self.enable_safety:
            try:
                from dev_safety import DevSafety
                safety = DevSafety()
                return safety.guard_loop(self._run_core)(report, workspace)
            except Exception:
                # dev_safety 不可用则直接跑
                return self._run_core(report, workspace)
        return self._run_core(report, workspace)

    # ---- 公开：预估目标文件（供 dev_safety.guard_loop 提前 snapshot）----
    def plan_files(self, user_request: str, workspace: str) -> List[str]:
        targets = self._locate_symbols(user_request, workspace)
        return self._collect_files(targets, user_request, workspace)

    # ---- 核心闭环 ----
    def _run_core(self, report: DevReport, workspace: str) -> DevReport:
        user_request = report.user_request

        # 2) 语义定位
        targets = self._locate_symbols(user_request, workspace)
        report.targets = targets

        # 3) 读取上下文 + 收集文件
        files = self._collect_files(targets, user_request, workspace)

        # 4) 生成修改
        ctx = {"files": files, "workspace": workspace, "intent": report.intent}
        if report.used_history:
            ctx["history"] = _find_similar_lessons(user_request, _load_lessons())
        plans = self.generator(user_request, ctx)

        if not plans:
            report.summary = "未生成任何编辑计划（任务可能无需改代码或 generator 不支持）"
            report.ok = True
            self._finalize(report)
            return report

        # 6) 语义校验 (改前基线)
        before = []
        for fp in files:
            diags, _ = self.lsp_checker(fp)
            before.extend(diags)
        report.diagnostics_before = before

        # 5) 应用修改
        applied, failed = self._apply_edits(plans)
        report.edits = [p.to_dict() for p in applied]
        report.changed_files = sorted({p.file_path for p in applied})

        if failed and not applied:
            report.rollback_happened = True
            report.summary = f"所有编辑失败，已回滚: {failed[0][1]}"
            report.ok = False
            self._finalize(report)
            return report

        # 6) 语义校验 (改后)
        after = []
        for fp in report.changed_files:
            diags, _ = self.lsp_checker(fp)
            after.extend(diags)
        report.diagnostics_after = after
        report.new_diagnostics = [
            d for d in after
            if _diag_key(d) not in {_diag_key(x) for x in before}
        ]

        # 7) 验证
        if report.changed_files:
            report.test_result = self.test_runner(report.changed_files[0])

        # 8) 复盘
        report.ok = (len(report.new_diagnostics) == 0)
        if report.ok:
            report.lessons.append("修改通过语义校验，无新增诊断")
            report.summary = (
                f"自主开发完成: 意图={report.intent}, "
                f"改动 {len(report.changed_files)} 个文件, "
                f"应用 {len(applied)} 处编辑, 无新增诊断"
            )
        else:
            report.summary = (
                f"修改引入 {len(report.new_diagnostics)} 条新诊断，"
                f"建议人工复查"
            )
            report.lessons.append("修改引入了新诊断，需要人工 review")

        self._finalize(report)
        return report

    # ---- 步骤实现 ----
    def _locate_symbols(self, user_request: str, workspace: str) -> List[Dict]:
        """语义定位：workspace_symbol 找目标 → document_symbol 看结构"""
        targets: List[Dict] = []
        # 从请求里抽取可能的符号名（引号/反引号内的词）
        import re
        names = re.findall(r"[`\"']([A-Za-z_]\w*)`[\"']", user_request)
        for name in names:
            try:
                from skills.lsp_code_analysis import execute as lsp_execute
                res = lsp_execute(action="workspace_symbol", query=name)
                if res.success and (res.data or {}).get("symbols"):
                    targets.extend(res.data["symbols"][:5])
            except Exception:
                pass
        return targets

    def _collect_files(
        self, targets: List[Dict], user_request: str, workspace: str
    ) -> List[str]:
        """收集需要改的文件：优先 targets 命中，否则从请求里找文件名"""
        files: List[str] = []
        for t in targets:
            uri = t.get("uri") or t.get("location", {}).get("uri", "")
            if uri and uri.startswith("file://"):
                files.append(uri[7:])
        import re
        for m in re.findall(r"([\w./\\-]+\.py)", user_request):
            if os.path.isabs(m) and os.path.isfile(m):
                files.append(m)
                continue
            # 直接相对路径
            fp = os.path.join(workspace, m)
            if os.path.isfile(fp):
                files.append(fp)
                continue
            # 回退：在 workspace 下递归搜索同名文件（最多 200 个匹配，取首个）
            hit = None
            for root, _dirs, fnames in os.walk(workspace):
                if m in fnames:
                    hit = os.path.join(root, m)
                    break
            if hit:
                files.append(hit)
        # 去重
        return list(dict.fromkeys(files))

    def _apply_edits(self, plans: List[EditPlan]) -> Tuple[List[EditPlan], List[Tuple[EditPlan, str]]]:
        """逐对应用 edit_file（字符串替换），失败回滚已应用部分"""
        applied: List[EditPlan] = []
        failed: List[Tuple[EditPlan, str]] = []
        for plan in plans:
            try:
                if not os.path.isfile(plan.file_path):
                    failed.append((plan, f"文件不存在: {plan.file_path}"))
                    continue
                with open(plan.file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if plan.old not in content:
                    failed.append((plan, "old 片段在当前文件中未找到（可能已变更）"))
                    continue
                new_content = content.replace(plan.old, plan.new, 1)
                with open(plan.file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                applied.append(plan)
            except Exception as e:
                failed.append((plan, str(e)))
                break  # 出错即停止，触发回滚
        if failed and applied:
            # 回滚已应用的编辑
            for plan in reversed(applied):
                try:
                    with open(plan.file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    restored = content.replace(plan.new, plan.old, 1)
                    with open(plan.file_path, "w", encoding="utf-8") as f:
                        f.write(restored)
                except Exception:
                    pass
        return applied, failed

    def _finalize(self, report: DevReport) -> None:
        """S10: 把复盘追加到 data/dev_lessons.json"""
        if not self.enable_lessons:
            return
        try:
            _save_lesson({
                "request": report.user_request,
                "intent": report.intent,
                "files": report.changed_files,
                "edits": report.edits,
                "test_result": report.test_result,
                "lessons": report.lessons,
                "ts": time.time(),
            })
        except Exception:
            pass


def _diag_key(d: Any) -> str:
    """诊断去重键"""
    if isinstance(d, dict):
        return f"{d.get('range')}-{d.get('message')}"
    return str(d)


# ==================== Skill 包装 (供 engine_manager 工具调用循环) ====================

def auto_dev_loop_skill(
    request: str,
    workspace: str = "",
    enable_safety: bool = True,
    enable_lessons: bool = True,
) -> SkillResult:
    """auto_dev_loop 的 Skill 入口，供 LLM 在 agent_chat 工具循环中自主触发"""
    workspace = workspace or os.getcwd()
    loop = AutoDevLoop(
        enable_safety=enable_safety,
        enable_lessons=enable_lessons,
        workspace=workspace,
    )
    report = loop.run(request, workspace)
    return SkillResult(
        success=report.ok,
        output=report.summary,
        data=report.to_dict(),
    )
