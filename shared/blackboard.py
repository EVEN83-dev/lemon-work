# -*- coding: utf-8 -*-
"""383A-1: 全局状态黑板（主从式多智能体协同）

设计要点
--------
* 单一权威状态源：主会话（协调器）与 worker 之间**只经黑板交换**；
  worker 之间禁止直接对话（防上下文膨胀、防相互污染）。
* JSON 落盘 ``data/audit/blackboard_<task_id>.json``，便于审计、断点续跑与复盘。
* 线程安全：``threading.Lock`` 保护，worker 并发写互不覆盖。

字段
----
task_id        任务唯一标识
goal           主任务目标
plan_steps     协调器拆解的计划步骤
dod            Definition of Done 清单（注入给每个 worker 的验收标准）
dependencies   步骤/产物之间的依赖关系
worker_outputs worker_id -> {status, summary, finished_at, meta}

零新增依赖（纯标准库）。
"""

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

# data/audit/ —— 与 383A-2 审计流同目录（A 战区）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_DIR = os.path.join(_PROJECT_ROOT, "data", "audit")

_LOCK = threading.Lock()


def _ensure_dir() -> str:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    return AUDIT_DIR


class Blackboard:
    """任务级共享状态黑板。"""

    def __init__(self, task_id: str, goal: str = "",
                 plan_steps: Optional[List[Any]] = None,
                 dod: Optional[List[str]] = None,
                 dependencies: Optional[Dict[str, Any]] = None):
        self.task_id = task_id
        self.goal = goal
        self.plan_steps: List[Any] = plan_steps or []
        self.dod: List[str] = dod or []
        self.dependencies: Dict[str, Any] = dependencies or {}
        self.worker_outputs: Dict[str, Dict[str, Any]] = {}
        # ★389M-6: 依赖链状态 + 共享键（冲突仲裁）+ 重派审计
        self.dependency_status: Dict[str, Dict[str, Any]] = {}
        self.shared_keys: Dict[str, Dict[str, Any]] = {}
        self.redispatches: List[Dict[str, Any]] = []
        self.created_at = time.time()
        self.updated_at = self.created_at

    # ---------------- 序列化 / 落盘 ----------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "plan_steps": self.plan_steps,
            "dod": self.dod,
            "dependencies": self.dependencies,
            "worker_outputs": self.worker_outputs,
            "dependency_status": self.dependency_status,
            "shared_keys": self.shared_keys,
            "redispatches": self.redispatches,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def save(self) -> str:
        """落盘到 data/audit/blackboard_<task_id>.json，返回路径。"""
        _ensure_dir()
        path = os.path.join(AUDIT_DIR, f"blackboard_{self.task_id}.json")
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            # 落盘失败不阻断主流程
            pass
        return path

    # ---------------- worker 产出 ----------------

    def write_output(self, worker_id: str, summary: str,
                     status: str = "completed", meta: Optional[Dict] = None) -> None:
        """worker 写回产出（只追加自己的槽位，不覆盖他人）。

        ★ 383A-1 并发修复：每个 worker 持有的是**独立内存实例**（spawn 时各自 load）。
        若直接把自身 to_dict() 全量落盘，后完成的 worker 会整体覆盖先完成者的产出
        （实测：2 个 worker 均 completed，黑板却只剩 1 份）。
        故写入前先 reload 磁盘最新状态做 read-modify-write 合并，保证并发安全。
        """
        with _LOCK:
            fresh = Blackboard.load(self.task_id)
            if fresh is not None:
                self.worker_outputs = dict(fresh.worker_outputs or {})
                if fresh.goal:
                    self.goal = fresh.goal
                if fresh.plan_steps:
                    self.plan_steps = fresh.plan_steps
                if fresh.dod:
                    self.dod = fresh.dod
                if fresh.dependency_status:
                    self.dependency_status = dict(fresh.dependency_status)
                if fresh.shared_keys:
                    self.shared_keys = dict(fresh.shared_keys)
                if fresh.redispatches:
                    self.redispatches = list(fresh.redispatches)
            self.worker_outputs[worker_id] = {
                "status": status,
                "summary": summary,
                "finished_at": time.time(),
                "meta": meta or {},
            }
            self.updated_at = time.time()
            self._save_locked()

    def _save_locked(self) -> None:
        # 调用方已持有 _LOCK
        # ★389M-6: 原子写（tmp + os.replace）—— 轮询方 load 读到半截 JSON 会
        # json.load 失败返回 None（实测复现：主 Agent 轮询 vs worker 写回竞态）
        _ensure_dir()
        path = os.path.join(AUDIT_DIR, f"blackboard_{self.task_id}.json")
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            pass

    # ---------------- 快照（注入给 worker 的只读视图） ----------------

    def snapshot(self) -> Dict[str, Any]:
        with _LOCK:
            return json.loads(json.dumps(self.to_dict(), ensure_ascii=False))

    def snapshot_text(self, max_chars: int = 1200) -> str:
        """生成注入给 worker 的黑板快照文本（只读、截断）。"""
        with _LOCK:
            lines: List[str] = []
            if self.goal:
                lines.append(f"主任务目标: {self.goal}")
            if self.plan_steps:
                lines.append("计划步骤:")
                for i, st in enumerate(self.plan_steps, 1):
                    lines.append(f"  {i}. {st}")
            if self.worker_outputs:
                lines.append("已有 worker 产出（他人结果，仅供参考，不要与其对话）:")
                for wid, out in self.worker_outputs.items():
                    lines.append(f"  - [{wid}][{out.get('status')}] {out.get('summary', '')[:300]}")
            else:
                lines.append("已有 worker 产出: （暂无）")
            text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...(快照已截断)"
        return text

    # ---------------- 汇总 ----------------

    def deps_satisfied(self, worker_name: str, depends_on: List[str],
                       reload_disk: bool = True) -> tuple:
        """389M-6: 依赖链判定 —— depends_on 中所有 worker 均已 completed 才可启动。

        Returns:
            (satisfied: bool, unmet: List[str])
        """
        with _LOCK:
            if reload_disk:
                fresh = Blackboard.load(self.task_id)
                if fresh is not None:
                    self.worker_outputs = dict(fresh.worker_outputs or {})
            completed_prefixes = [
                wid.split("#")[0] for wid, v in self.worker_outputs.items()
                if v.get("status") == "completed"
            ]
            unmet = [d for d in (depends_on or []) if d not in completed_prefixes]
            return (not unmet), unmet

    def mark_dependency(self, worker_name: str, depends_on: List[str],
                        blocked: bool, note: str = "") -> None:
        """389M-6: 依赖状态写黑板（排队/放行均留痕，供主 Agent 审计）。"""
        with _LOCK:
            fresh = Blackboard.load(self.task_id)
            if fresh is not None and fresh.dependency_status:
                self.dependency_status = dict(fresh.dependency_status)
            self.dependency_status[worker_name] = {
                "depends_on": list(depends_on or []),
                "blocked": bool(blocked),
                "note": note[:200],
                "ts": time.time(),
            }
            self.updated_at = time.time()
            self._save_locked()

    def mark_redispatch(self, worker_name: str, attempt: int, note: str) -> None:
        """389M-6: 失败重派留痕（最多 1 次的纪律由调用方保证，黑板只记账）。"""
        with _LOCK:
            fresh = Blackboard.load(self.task_id)
            if fresh is not None and fresh.redispatches:
                self.redispatches = list(fresh.redispatches)
            self.redispatches.append({
                "worker": worker_name, "attempt": attempt,
                "note": note[:300], "ts": time.time(),
            })
            self.updated_at = time.time()
            self._save_locked()

    def claim_key(self, worker_id: str, key: str, value: Any) -> tuple:
        """389M-6: 共享键写入 —— 后写者拒绝并要求主 Agent 仲裁（不做自动合并）。

        Returns:
            (accepted: bool, message: str)
        """
        with _LOCK:
            fresh = Blackboard.load(self.task_id)
            if fresh is not None and fresh.shared_keys:
                self.shared_keys = dict(fresh.shared_keys)
            owner_rec = self.shared_keys.get(key)
            if owner_rec and owner_rec.get("owner") != worker_id:
                return False, (f"键 '{key}' 已被 {owner_rec.get('owner')} 写入，"
                               f"后写者 {worker_id} 拒绝 —— 需主 Agent 仲裁")
            self.shared_keys[key] = {
                "owner": worker_id, "value": value, "ts": time.time(),
            }
            self.updated_at = time.time()
            self._save_locked()
            return True, ""

    def finalize(self) -> Dict[str, Any]:
        """协调器汇总：返回结构化总览 + DOD 覆盖情况。"""
        with _LOCK:
            total = len(self.worker_outputs)
            done = sum(1 for v in self.worker_outputs.values() if v.get("status") == "completed")
            failed = [k for k, v in self.worker_outputs.items()
                      if v.get("status") in ("failed", "timeout")]
            merged = "\n".join(
                f"- [{k}][{v.get('status')}] {v.get('summary', '')}"
                for k, v in self.worker_outputs.items()
            )
            summary = {
                "task_id": self.task_id,
                "goal": self.goal,
                "dod": self.dod,
                "total_workers": total,
                "completed": done,
                "failed": failed,
                "merged_output": merged,
                "finalized_at": time.time(),
            }
            self.updated_at = time.time()
            self._save_locked()
        return summary

    # ---------------- 加载 ----------------

    @classmethod
    def load(cls, task_id: str) -> Optional["Blackboard"]:
        path = os.path.join(AUDIT_DIR, f"blackboard_{task_id}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            bb = cls(task_id=d.get("task_id", task_id), goal=d.get("goal", ""),
                     plan_steps=d.get("plan_steps"), dod=d.get("dod"),
                     dependencies=d.get("dependencies"))
            bb.worker_outputs = d.get("worker_outputs", {}) or {}
            bb.dependency_status = d.get("dependency_status", {}) or {}
            bb.shared_keys = d.get("shared_keys", {}) or {}
            bb.redispatches = d.get("redispatches", []) or []
            bb.created_at = d.get("created_at", time.time())
            bb.updated_at = d.get("updated_at", bb.created_at)
            return bb
        except Exception:
            return None


def create_blackboard(goal: str = "", plan_steps: Optional[List[Any]] = None,
                      dod: Optional[List[str]] = None,
                      dependencies: Optional[Dict[str, Any]] = None,
                      task_id: str = "") -> Blackboard:
    """协调器创建黑板并落盘。"""
    tid = task_id or f"bb_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    bb = Blackboard(task_id=tid, goal=goal, plan_steps=plan_steps,
                    dod=dod, dependencies=dependencies)
    bb.save()
    return bb


def get_blackboard(task_id: str) -> Optional[Blackboard]:
    return Blackboard.load(task_id)
