# -*- coding: utf-8 -*-
"""
commander_core.executor — 通用任务执行循环
=========================================
将咩咩 MiemieEngineWorker._execute_plan 和混合模式 WorkAgent.execute_all
的共同执行逻辑抽取为可复用的策略框架。

核心抽象：
  - AbstractExecutionStrategy: 执行策略接口（同步/异步/并行）
  - ToolRegistry: 工具注册表（绑定工具名→函数）
  - PlanExecutor: 计划执行器（接受 Plan + Strategy + Registry）
"""

import json
import time
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple


class ToolRegistry:
    """工具注册表 — 绑定工具名到执行函数。

    咩咩注册 glob/grep/read_file/write_file 等；
    混合模式注册 AI 调用/角色分配等高层工具。
    """

    def __init__(self):
        self._tools: Dict[str, Dict] = {}

    def register(self, name: str, fn: Callable,
                 desc: str = "", risk: str = "low") -> "ToolRegistry":
        """注册一个工具。

        Args:
            name: 工具名
            fn: 执行函数 (**kwargs) -> dict
            desc: 工具描述
            risk: 风险等级 (low/high)
        """
        self._tools[name] = {
            "fn": fn,
            "desc": desc,
            "risk": risk,
        }
        return self

    def unregister(self, name: str) -> "ToolRegistry":
        """注销工具。"""
        self._tools.pop(name, None)
        return self

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Optional[Dict]:
        return self._tools.get(name)

    def call(self, name: str, args: Optional[Dict] = None) -> Tuple[Dict, str]:
        """调用工具，返回 (result_dict, state_str)。

        state: "done" | "error"
        """
        info = self._tools.get(name)
        if info is None:
            return {"ok": False, "error": f"未知工具: {name}"}, "error"

        fn = info["fn"]
        kwargs = args or {}

        try:
            result = fn(**kwargs)
        except TypeError as te:
            # 参数不匹配时降级尝试：位置参数传递
            try:
                vals = list(kwargs.values())
                result = fn(*vals[:1]) if vals else fn()
            except Exception as e:
                return {"ok": False, "error": f"参数错误: {te}"}, "error"
        except Exception as e:
            return {"ok": False, "error": f"执行异常: {e}"}, "error"

        if not isinstance(result, dict):
            result = {"ok": True, "result": result}

        state = "error" if not result.get("ok") else "done"
        return result, state

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def get_definitions(self) -> Dict[str, Dict]:
        """获取工具定义（供 schema 生成）。"""
        return {
            name: {"desc": info["desc"], "risk": info["risk"]}
            for name, info in self._tools.items()
        }


class AbstractExecutionStrategy:
    """执行策略接口。

    子类实现不同的执行模式：
      - SequentialStrategy: 顺序执行（咩咩模式）
      - ParallelStrategy: 并行执行（混合模式）
      - AgenticStrategy: 自主编排执行
    """

    def execute(self, plan, registry: ToolRegistry,
                progress_callback: Optional[Callable] = None,
                cancel_event: Optional[threading.Event] = None) -> List[Dict]:
        """执行计划。

        Args:
            plan: Plan 对象
            registry: 工具注册表
            progress_callback: 进度回调 (item_type, item_data, index, total)
            cancel_event: 取消事件

        Returns:
            执行记录列表
        """
        raise NotImplementedError


class SequentialStrategy(AbstractExecutionStrategy):
    """顺序执行策略 — 逐个执行计划项。

    对应咩咩 MiemieEngineWorker._execute_plan 的逻辑。
    """

    def __init__(self, delay: float = 0.3):
        self.delay = delay

    def execute(self, plan, registry: ToolRegistry,
                progress_callback: Optional[Callable] = None,
                cancel_event: Optional[threading.Event] = None) -> List[Dict]:
        records = []
        items = list(plan.iter_items())
        total = len(items)
        all_ok = True

        for idx, (item_type, item) in enumerate(items):
            if cancel_event and cancel_event.is_set():
                break

            if item_type == "step":
                tool = item.tool
                args = dict(item.args)
                desc = item.desc
            elif item_type == "task":
                tool = "_task_executor"
                args = {"task": item}
                desc = item.title
            else:
                continue

            # 进度回调
            if progress_callback:
                progress_callback("start", {"tool": tool, "args": args,
                                           "desc": desc, "type": item_type},
                                  idx, total)

            result, state = registry.call(tool, args)
            if state == "error":
                all_ok = False

            if progress_callback:
                progress_callback("result", {"tool": tool, "result": result,
                                             "state": state, "type": item_type},
                                  idx, total)

            records.append({
                "item_type": item_type,
                "name": tool,
                "args": args,
                "result": result,
                "state": state,
                "desc": desc,
            })

            if self.delay > 0:
                time.sleep(self.delay)

        return records


class ParallelStrategy(AbstractExecutionStrategy):
    """并行执行策略 — 所有任务同时执行。

    对应混合模式 CommandAgent.execute_all_agents 的逻辑。
    """

    def __init__(self, max_workers: int = 4, timeout: float = 600):
        self.max_workers = max_workers
        self.timeout = timeout

    def execute(self, plan, registry: ToolRegistry,
                progress_callback: Optional[Callable] = None,
                cancel_event: Optional[threading.Event] = None) -> List[Dict]:
        import concurrent.futures

        records = []
        tasks = plan.tasks
        if not tasks:
            # 如果没有 tasks，退回顺序执行 steps
            if plan.steps:
                return SequentialStrategy().execute(plan, registry,
                                                     progress_callback, cancel_event)
            return records

        total = len(tasks)
        results_map = {}
        lock = threading.Lock()

        def _run_task(idx, task):
            if cancel_event and cancel_event.is_set():
                return
            if progress_callback:
                progress_callback("start", {"task": task.title,
                                           "type": "task"}, idx, total)
            result, state = registry.call("_task_executor", {"task": task})
            if progress_callback:
                progress_callback("result", {"task": task.title, "result": result,
                                             "state": state, "type": "task"},
                                  idx, total)
            with lock:
                results_map[idx] = {
                    "item_type": "task",
                    "name": task.title,
                    "args": {"task": task.to_dict()},
                    "result": result,
                    "state": state,
                    "desc": task.detail,
                }

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(self.max_workers, total)) as executor:
            futures = [
                executor.submit(_run_task, i, t)
                for i, t in enumerate(tasks)
            ]
            for f in concurrent.futures.as_completed(futures):
                f.result(timeout=self.timeout)

        # 按顺序组装结果
        for idx in range(total):
            if idx in results_map:
                records.append(results_map[idx])

        return records


class AgenticStrategy(AbstractExecutionStrategy):
    """自主编排策略 — 模型自主决定工具链。

    对应咩咩 MiemieEngineWorker._run_agentic_loop 的逻辑。
    """

    def __init__(self, max_rounds: int = 10, llm_fn: Optional[Callable] = None):
        self.max_rounds = max_rounds
        self.llm_fn = llm_fn

    def execute(self, plan, registry: ToolRegistry,
                progress_callback: Optional[Callable] = None,
                cancel_event: Optional[threading.Event] = None) -> List[Dict]:
        if self.llm_fn is None:
            # 降级为顺序执行
            return SequentialStrategy().execute(plan, registry,
                                                   progress_callback, cancel_event)

        records = []
        tools_schema = registry.get_definitions()
        messages = [
            {"role": "system", "content": _build_agentic_prompt(tools_schema)},
            {"role": "user", "content": plan.goal},
        ]
        last_reply = ""

        for round_idx in range(self.max_rounds):
            if cancel_event and cancel_event.is_set():
                break

            if progress_callback:
                progress_callback("start", {"tool": "llm",
                                           "desc": "自主规划中...",
                                           "round": round_idx}, round_idx, self.max_rounds)

            try:
                msg = self.llm_fn(messages, tools=list(tools_schema.keys()))
            except Exception as e:
                if progress_callback:
                    progress_callback("result", {"tool": "llm",
                                                 "result": {"ok": False, "error": str(e)},
                                                 "state": "error"}, round_idx, self.max_rounds)
                break

            if isinstance(msg, dict):
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls", [])
            else:
                content = str(msg)
                tool_calls = []

            messages.append({"role": "assistant", "content": content})

            if not tool_calls:
                last_reply = content
                if progress_callback:
                    progress_callback("result", {"tool": "llm",
                                                 "result": {"ok": True, "reply": content},
                                                 "state": "done"}, round_idx, self.max_rounds)
                break

            # 执行工具调用
            for tc in tool_calls:
                if cancel_event and cancel_event.is_set():
                    break

                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    raw_args = fn.get("arguments", "{}")
                else:
                    name = getattr(tc, "function", {}).name if hasattr(tc, "function") else ""
                    raw_args = getattr(tc, "function", {}).arguments if hasattr(tc, "function") else "{}"

                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except Exception:
                    args = {}

                if progress_callback:
                    progress_callback("start", {"tool": name, "args": args,
                                               "desc": tools_schema.get(name, {}).get("desc", name)},
                                      round_idx, self.max_rounds)

                result, state = registry.call(name, args)
                records.append({
                    "item_type": "step",
                    "name": name,
                    "args": args,
                    "result": result,
                    "state": state,
                })

                if progress_callback:
                    progress_callback("result", {"tool": name, "result": result,
                                                 "state": state}, round_idx, self.max_rounds)

                res_txt = json.dumps(result, ensure_ascii=False, default=str)[:2000]
                messages.append({"role": "tool", "content": res_txt, "tool_name": name})

        return records


def _build_agentic_prompt(tools_schema: Dict) -> str:
    """构建自主编排系统提示词。"""
    tool_list = "\n".join(
        f"- {name}: {info.get('desc', '无描述')} (风险: {info.get('risk', 'low')})"
        for name, info in tools_schema.items()
    )
    return f"""你是一个自主编排 Agent。根据用户目标，自主决定调用哪些工具、什么顺序。

可用工具：
{tool_list}

规则：
1. 每次调用一个工具，等待结果后再决定下一步
2. 高风险工具需在回复中说明原因
3. 完成所有步骤后给出最终回答
4. 如果不需要工具，直接回答即可"""


class PlanExecutor:
    """计划执行器 — 接受 Plan + Strategy + Registry 执行。

    Usage:
        executor = PlanExecutor(registry, strategy=SequentialStrategy())
        records = executor.execute(plan, on_progress=my_callback)
    """

    def __init__(self, registry: ToolRegistry,
                 strategy: Optional[AbstractExecutionStrategy] = None):
        self.registry = registry
        self.strategy = strategy or SequentialStrategy()
        self._cancel_event = threading.Event()

    def execute(self, plan,
                on_progress: Optional[Callable] = None) -> List[Dict]:
        """执行计划。

        Args:
            plan: Plan 对象
            on_progress: 进度回调 (event_type, data, index, total)
                        event_type: "start" | "result"

        Returns:
            执行记录列表
        """
        self._cancel_event.clear()
        return self.strategy.execute(
            plan, self.registry,
            progress_callback=on_progress,
            cancel_event=self._cancel_event,
        )

    def cancel(self):
        """取消执行。"""
        self._cancel_event.set()

    def set_strategy(self, strategy: AbstractExecutionStrategy):
        """切换执行策略。"""
        self.strategy = strategy
