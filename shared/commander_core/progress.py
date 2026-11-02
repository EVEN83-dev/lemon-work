# -*- coding: utf-8 -*-
"""
commander_core.progress — 进度追踪与执行记录
==============================================
统一咩咩和混合模式的进度/状态追踪：

咩咩需要：MiemieEngineWorker._record_step() → 步骤记录
混合模式需要：WorkAgent._emit_progress() → 百分比进度

ProgressTracker 提供：
  - 步骤级别的执行记录（工具名/参数/结果/耗时）
  - 百分比进度计算
  - 摘要生成（供任务后 LLM 总结）
"""

import time
from typing import Any, Dict, List, Optional


class ExecutionRecord:
    """单条执行记录。"""

    def __init__(self, name: str, args: Optional[Dict] = None,
                 result: Optional[Dict] = None, state: str = "pending",
                 item_type: str = "step",
                 start_time: Optional[float] = None,
                 end_time: Optional[float] = None):
        self.name = name
        self.args = args or {}
        self.result = result or {}
        self.state = state  # pending / running / done / error
        self.item_type = item_type
        self.start_time = start_time or time.time()
        self.end_time = end_time

    @property
    def duration(self) -> float:
        """执行耗时（秒）。"""
        end = self.end_time or time.time()
        return max(0.0, end - self.start_time)

    def finish(self, state: str = "done", result: Optional[Dict] = None):
        """标记完成。"""
        self.state = state
        self.end_time = time.time()
        if result is not None:
            self.result = result

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "args": self.args,
            "result": self.result,
            "state": self.state,
            "item_type": self.item_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
        }

    def brief(self) -> str:
        """生成简要描述（供 LLM 总结）。"""
        status = "✓" if self.state == "done" else "✗"
        result_brief = ""
        if self.result:
            r = self.result
            if r.get("ok"):
                result_brief = str(r.get("result", r.get("reply", "")))[:100]
            else:
                result_brief = f"失败: {r.get('error', '未知错误')}"
        return f"{status} {self.name}({self.args}) → {result_brief}"


class ProgressTracker:
    """进度追踪器。

    Usage:
        tracker = ProgressTracker(total=10)
        tracker.start_item("glob")
        tracker.finish_item("done", {"files": 5})
        summary = tracker.summarize()
    """

    def __init__(self, total: int = 0):
        self._total = total
        self._current = 0
        self._records: List[ExecutionRecord] = []
        self._start_time = time.time()
        self._lock = None  # 可选 threading.Lock 用于并发

    @property
    def total(self) -> int:
        return self._total

    @total.setter
    def total(self, value: int):
        self._total = max(0, value)

    @property
    def current(self) -> int:
        return self._current

    @property
    def percent(self) -> float:
        """当前百分比 (0-100)。"""
        if self._total == 0:
            return 0.0
        return min(100.0, (self._current / self._total) * 100.0)

    @property
    def elapsed(self) -> float:
        """已用时间（秒）。"""
        return time.time() - self._start_time

    @property
    def is_complete(self) -> bool:
        return self._current >= self._total > 0

    def start_item(self, name: str, args: Optional[Dict] = None,
                   item_type: str = "step") -> ExecutionRecord:
        """开始一个新项。"""
        record = ExecutionRecord(
            name=name, args=args, state="running",
            item_type=item_type,
        )
        self._records.append(record)
        return record

    def finish_item(self, state: str = "done",
                    result: Optional[Dict] = None) -> Optional[ExecutionRecord]:
        """完成最近一项。"""
        if not self._records:
            return None
        record = self._records[-1]
        record.finish(state, result)
        if state in ("done", "error"):
            self._current += 1
        return record

    def complete_item(self, name: str, result: Optional[Dict] = None,
                      state: str = "done", args: Optional[Dict] = None,
                      item_type: str = "step") -> ExecutionRecord:
        """原子操作：开始并完成一项。"""
        record = self.start_item(name, args, item_type)
        record.finish(state, result)
        if state in ("done", "error"):
            self._current += 1
        return record

    def reset(self, total: int = 0):
        """重置追踪器。"""
        self._total = total
        self._current = 0
        self._records.clear()
        self._start_time = time.time()

    def get_records(self) -> List[ExecutionRecord]:
        """获取所有执行记录。"""
        return list(self._records)

    def get_last(self) -> Optional[ExecutionRecord]:
        """获取最后一条记录。"""
        return self._records[-1] if self._records else None

    def get_failed(self) -> List[ExecutionRecord]:
        """获取所有失败记录。"""
        return [r for r in self._records if r.state == "error"]

    def summarize(self) -> Dict[str, Any]:
        """生成执行摘要。

        Returns:
            包含统计信息的字典，供 LLM 总结使用。
        """
        records = self._records
        total_items = len(records)
        done_count = sum(1 for r in records if r.state == "done")
        error_count = sum(1 for r in records if r.state == "error")
        skipped_count = sum(1 for r in records if r.state == "pending")

        # 生成简要描述列表
        briefs = [r.brief() for r in records]

        return {
            "total_items": total_items,
            "done": done_count,
            "errors": error_count,
            "skipped": skipped_count,
            "success_rate": (done_count / max(1, total_items)) * 100,
            "elapsed_seconds": self.elapsed,
            "records": briefs,
            "all_ok": error_count == 0 and skipped_count == 0,
        }

    def generate_summary_text(self) -> str:
        """生成可读的摘要文本（供 LLM 总结输入）。"""
        s = self.summarize()
        lines = [
            f"执行摘要: {s['total_items']} 项, "
            f"成功 {s['done']}, 失败 {s['errors']}, "
            f"耗时 {s['elapsed_seconds']:.1f}s",
            "",
        ]
        lines.extend(s["records"])
        return "\n".join(lines)
