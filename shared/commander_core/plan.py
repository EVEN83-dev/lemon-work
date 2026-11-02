# -*- coding: utf-8 -*-
"""
commander_core.plan — 计划/任务数据模型与分解逻辑
================================================
统一咩咩和混合模式的计划数据结构，支持：
  - 固定步骤计划（咩咩 MIEMIE_PLANS 风格）
  - LLM 生成的动态任务列表（混合模式 CommandAgent 风格）
  - 自主编排计划（agentic loop 风格）
"""

import json
import re
from typing import Any, Callable, Dict, List, Optional


class Step:
    """计划步骤（对应咩咩 MIEMIE_PLANS 中的 step 定义）"""

    def __init__(self, tool: str, args: Optional[Dict] = None,
                 desc: str = "", optional: bool = False):
        self.tool = tool
        self.args = args or {}
        self.desc = desc
        self.optional = optional

    def to_dict(self) -> Dict:
        return {
            "tool": self.tool,
            "args": self.args,
            "desc": self.desc,
            "optional": self.optional,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Step":
        return cls(
            tool=data.get("tool", ""),
            args=data.get("args", {}),
            desc=data.get("desc", ""),
            optional=data.get("optional", False),
        )


class Task:
    """任务（对应混合模式 CommandAgent 分解的子任务）"""

    def __init__(self, title: str, detail: str = "", role: str = "worker",
                 task_id: Optional[str] = None, cwd: Optional[str] = None):
        self.task_id = task_id or f"task_{id(self):x}"
        self.title = title
        self.detail = detail
        self.role = role
        self.cwd = cwd
        self.status = "pending"  # pending / working / done / error
        self.result = ""
        self.error = ""

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "detail": self.detail,
            "role": self.role,
            "cwd": self.cwd,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        task = cls(
            title=data.get("title", ""),
            detail=data.get("detail", ""),
            role=data.get("role", "worker"),
            task_id=data.get("task_id"),
            cwd=data.get("cwd"),
        )
        task.status = data.get("status", "pending")
        task.result = data.get("result", "")
        task.error = data.get("error", "")
        return task


class Plan:
    """计划 — 由多个 Step 组成的有序执行序列"""

    def __init__(self, name: str = "", goal: str = "",
                 steps: Optional[List[Step]] = None,
                 tasks: Optional[List[Task]] = None):
        self.name = name
        self.goal = goal
        self.steps = steps or []
        self.tasks = tasks or []

    def add_step(self, step: Step) -> "Plan":
        self.steps.append(step)
        return self

    def add_task(self, task: Task) -> "Plan":
        self.tasks.append(task)
        return self

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "tasks": [t.to_dict() for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Plan":
        plan = cls(
            name=data.get("name", ""),
            goal=data.get("goal", ""),
        )
        plan.steps = [Step.from_dict(s) for s in data.get("steps", [])]
        plan.tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        return plan

    def __len__(self):
        return len(self.steps) + len(self.tasks)

    def iter_items(self):
        """统一迭代 steps 和 tasks（按 steps 优先顺序）"""
        for step in self.steps:
            yield ("step", step)
        for task in self.tasks:
            yield ("task", task)


# =====================================================================
# 计划分解
# =====================================================================

def decompose_goal(goal: str, llm_fn: Optional[Callable] = None,
                    project_context: Optional[Dict] = None) -> Plan:
    """将自然语言目标分解为 Plan。

    Args:
        goal: 用户自然语言描述
        llm_fn: 可选 LLM 调用函数 (prompt) -> str
        project_context: 可选项目上下文（文件数/模块等）

    Returns:
        Plan 对象
    """
    context = project_context or {}

    if llm_fn is not None:
        try:
            prompt = _build_decompose_prompt(goal, context)
            raw = llm_fn(prompt)
            tasks = parse_llm_tasks(raw)
            if tasks:
                plan = Plan(name="llm_decomposed", goal=goal, tasks=tasks)
                return plan
        except Exception:
            pass

    # 默认分解：基于关键词路由
    steps = _keyword_route_plan(goal)
    return Plan(name="keyword_routed", goal=goal, steps=steps)


def _build_decompose_prompt(goal: str, context: Dict) -> str:
    """构建 LLM 分解提示词。"""
    ctx_parts = []
    for k, v in context.items():
        ctx_parts.append(f"- {k}: {v}")
    ctx_str = "\n".join(ctx_parts) if ctx_parts else "- 无"

    return f"""请将以下开发需求分解为具体的子任务。
每个子任务指定负责的角色（frontend/backend/tester/document/devops/worker）。

项目上下文:
{ctx_str}

需求: {goal}

请以JSON数组格式输出:
[
  {{"role": "role_key", "title": "任务标题", "detail": "任务详情"}}
]

只输出JSON，不要其他内容。"""


def parse_llm_tasks(raw: str) -> List[Task]:
    """从 LLM 输出中解析任务列表。

    支持格式：
    1. 纯 JSON 数组
    2. 被 markdown 代码块包裹的 JSON
    3. 混合文本中的 JSON 片段
    """
    if not raw:
        return []

    # 尝试直接 JSON 解析
    try:
        data = json.loads(raw.strip())
        if isinstance(data, list):
            return [Task.from_dict({"title": t.get("title", ""),
                                    "detail": t.get("detail", ""),
                                    "role": t.get("role", "worker")})
                    if isinstance(t, dict) else Task(title=str(t))
                    for t in data]
    except json.JSONDecodeError:
        pass

    # 尝试提取 markdown 代码块中的 JSON
    code_blocks = re.findall(r'```(?:json)?\s*\n?(.*?)```', raw, re.DOTALL)
    for block in code_blocks:
        try:
            data = json.loads(block.strip())
            if isinstance(data, list):
                return [Task.from_dict({"title": t.get("title", ""),
                                        "detail": t.get("detail", ""),
                                        "role": t.get("role", "worker")})
                        if isinstance(t, dict) else Task(title=str(t))
                        for t in data]
        except json.JSONDecodeError:
            continue

    # 尝试从文本中提取 JSON 数组
    array_match = re.search(r'\[.*?\]', raw, re.DOTALL)
    if array_match:
        try:
            data = json.loads(array_match.group())
            if isinstance(data, list):
                return [Task.from_dict({"title": t.get("title", ""),
                                        "detail": t.get("detail", ""),
                                        "role": t.get("role", "worker")})
                        if isinstance(t, dict) else Task(title=str(t))
                        for t in data]
        except json.JSONDecodeError:
            pass

    # 回退：将整个文本作为单个任务
    return [Task(title=raw[:80], detail=raw)]


# =====================================================================
# 关键词路由（降级方案）
# =====================================================================

_KEYWORD_STEP_MAP = [
    # 分析/调研类
    (["分析", "调研", "查看", "检查", "review", "analyze", "check"], [
        Step("glob", {"pattern": "**/*.py"}, "扫描项目文件"),
        Step("grep", {"pattern": "TODO|FIXME|HACK"}, "查找遗留标记"),
        Step("read_file", {"path": "README.md"}, "读取项目文档", optional=True),
    ]),
    # 编码/实现类
    (["实现", "开发", "编码", "创建", "写", "implement", "develop", "create"], [
        Step("glob", {"pattern": "**/*.py"}, "了解项目结构"),
        Step("grep", {"pattern": "class |def "}, "查找相关代码"),
        Step("write_file", {}, "创建/修改代码"),
        Step("bash", {"command": "python -m pytest"}, "运行测试", optional=True),
    ]),
    # 测试/验证类
    (["测试", "验证", "test", "verify"], [
        Step("bash", {"command": "python -m pytest -v"}, "运行测试套件"),
        Step("grep", {"pattern": "assert|raise"}, "检查断言覆盖"),
    ]),
    # 重构/优化类
    (["重构", "优化", "refactor", "optimize", "clean"], [
        Step("grep", {"pattern": "def |class "}, "分析代码结构"),
        Step("glob", {"pattern": "**/*.py"}, "定位目标文件"),
        Step("edit_file", {}, "执行重构"),
        Step("bash", {"command": "python -m pytest"}, "回归测试", optional=True),
    ]),
    # 文档类
    (["文档", "说明", "doc", "readme"], [
        Step("read_file", {"path": "README.md"}, "读取现有文档"),
        Step("glob", {"pattern": "**/*.py"}, "扫描模块结构"),
        Step("write_file", {}, "更新文档"),
    ]),
]

# 默认计划
_DEFAULT_STEPS = [
    Step("glob", {"pattern": "**/*.py"}, "扫描项目文件"),
    Step("grep", {"pattern": "TODO|FIXME"}, "查找待办标记"),
    Step("bash", {"command": "python -m pytest"}, "运行测试", optional=True),
]


def _keyword_route_plan(goal: str) -> List[Step]:
    """基于关键词生成降级计划。"""
    lower = goal.lower()
    for keywords, steps in _KEYWORD_STEP_MAP:
        if any(kw.lower() in lower for kw in keywords):
            return steps
    return list(_DEFAULT_STEPS)
