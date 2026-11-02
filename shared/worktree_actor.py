# -*- coding: utf-8 -*-
"""
Worktree × Actor 协调器（蒸馏 MiMo-Code worktree/ + actor/）
=============================================================

把 Git Worktree 的目录隔离与 Actor 的并行执行打通：
  - 每个子任务创建一个独立 worktree 分支（WorktreeManager.create_for_agent）
  - Actor 以 peer 模式运行，其 cwd 绑定到该 worktree 目录（目录级隔离）
  - 全部完成后可统一 merge_back 回主分支

这样多个子 Agent 并行工作，各自在隔离目录里改代码，互不污染主工作区，
最后再选择性合并。蒸馏自 MiMo-Code 的 worktree 隔离理念 + actor 并行编排。
"""
import os
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("lemon.actor.worktree")

from shared.actor_system import ActorSystem, WaitResult


class WorktreeActorCoordinator:
    """协调 Worktree 隔离与 Actor 并行执行的编排器。"""

    def __init__(self, project_root: str = None, actor_system: ActorSystem = None):
        self._root = project_root or os.getcwd()
        self._system = actor_system or ActorSystem()
        self._wt_mgr = None  # 惰性初始化

    def _worktree_manager(self):
        if self._wt_mgr is None:
            from standard_mode.core.worktree_manager import WorktreeManager
            self._wt_mgr = WorktreeManager(self._root)
        return self._wt_mgr

    def run(self, jobs: List[Dict[str, Any]], use_worktree: bool = True,
            timeout_ms: int = 600000) -> Tuple[List[WaitResult], List[Dict[str, Any]]]:
        """并行执行 jobs；use_worktree=True 时为每个 job 绑定独立 worktree。

        jobs 元素字段：
          - agent_type / task / task_fn / description / session_id / task_kwargs
          - title / detail（可选，用于 worktree 分支命名）

        返回 (results, worktrees)：
          - results: List[WaitResult]，每个子 Agent 的执行结果
          - worktrees: List[Dict]，被创建的 worktree 信息 {path, branch}
        """
        worktrees: List[Dict[str, Any]] = []
        prepared: List[Dict[str, Any]] = []
        wt_mgr = self._worktree_manager() if use_worktree else None

        for i, job in enumerate(jobs):
            cwd = None
            if use_worktree and wt_mgr is not None:
                title = job.get("title") or job.get("task") or f"task-{i + 1}"
                try:
                    ok, info = wt_mgr.create_for_agent(title)
                    if ok:
                        cwd = info.get("path")
                        worktrees.append({"path": info.get("path"), "branch": info.get("branch")})
                        logger.info("WorktreeActor: 任务[%s] 绑定 worktree %s", title, cwd)
                    else:
                        logger.warning("WorktreeActor: 任务[%s] worktree 创建失败: %s", title, info)
                except Exception as e:  # noqa: BLE001
                    logger.warning("WorktreeActor: 任务[%s] worktree 异常: %s", title, e)
            prepared.append({
                "agent_type": job.get("agent_type", "worker"),
                "task": job.get("task", job.get("title", f"task-{i + 1}")),
                "task_fn": job.get("task_fn"),
                "description": job.get("description", job.get("title", "")),
                "mode": "peer" if cwd else "subagent",
                "cwd": cwd,
                "session_id": job.get("session_id", "default"),
                "task_kwargs": job.get("task_kwargs", {}),
            })

        results = self._system.spawn_many_wait_all(prepared, timeout_ms=timeout_ms)
        return results, worktrees

    def merge_all_back(self, worktrees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """把全部 worktree 的变更合并回主分支。"""
        wt_mgr = self._worktree_manager()
        report: List[Dict[str, Any]] = []
        for wt in worktrees:
            try:
                ok, msg = wt_mgr.merge_back(wt["path"])
                report.append({"path": wt["path"], "branch": wt["branch"], "ok": ok, "msg": msg})
            except Exception as e:  # noqa: BLE001
                report.append({"path": wt["path"], "branch": wt["branch"], "ok": False, "msg": str(e)})
        return report

    def cleanup(self, worktrees: List[Dict[str, Any]]) -> None:
        """清理全部 worktree 目录（force 丢弃未提交变更）。"""
        wt_mgr = self._worktree_manager()
        for wt in worktrees:
            try:
                wt_mgr.remove(wt["path"], force=True)
            except Exception:  # noqa: BLE001
                pass
