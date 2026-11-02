# -*- coding: utf-8 -*-
"""
standard_mode/core/dev_safety.py — 自主闭环的失败回滚与安全护栏 (S9, P1)
=========================================================================

自主改代码不能把项目改坏——必须有回滚护栏。

  class DevSafety:
    .snapshot(files)          -> 改前内容快照 (内存 + data/dev_snapshots/)
    .rollback(snapshot_id)    -> 恢复到快照
    .validate_edit(old, new)  -> 静态检查 (缩进/引号/BOM/大小)
    .confirm_high_risk(edit)  -> 命中 _HIGH_RISK 模式 (bash/删除) 时要求确认
    .guard_loop(loop_run)     -> 装饰器: 每轮自动 snapshot，
                                 失败自动回滚 + 记录教训到 data/dev_lessons.json

设计原则 (满足 CodeLock "仅完善不破坏架构")：
  - 独立模块，dev_safety 不反向 import auto_dev_loop（避免循环依赖）。
  - 磁盘快照落 data/dev_snapshots/，内存快照用于快速回滚。
  - confirm_high_risk 默认在交互环境外自动放行（非交互测试/演示），
    通过 confirm_callback 注入真实确认逻辑。
"""

import os
import sys
import json
import time
import uuid
import shutil
import functools
from typing import Dict, Any, List, Optional, Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SNAPSHOT_DIR = os.path.join(_ROOT, "data", "dev_snapshots")
_LESSONS_PATH = os.path.join(_ROOT, "data", "dev_lessons.json")

# 高风险编辑模式：命中需要确认
_HIGH_RISK = [
    ("rm ", "删除命令"),
    ("rmdir", "删除目录"),
    ("shutil.rmtree", "Python 删除目录"),
    ("os.remove", "Python 删除文件"),
    ("os.system", "系统命令执行"),
    ("subprocess", "子进程执行"),
    ("DROP TABLE", "SQL 删表"),
    ("format(", "磁盘格式化"),
    ("git reset --hard", "Git 强制重置"),
]


class DevSafety:
    """开发安全护栏 — 快照 / 回滚 / 静态校验 / 高风险确认"""

    def __init__(self, snapshot_dir: Optional[str] = None):
        self.snapshot_dir = snapshot_dir or _SNAPSHOT_DIR
        os.makedirs(self.snapshot_dir, exist_ok=True)
        self._mem: Dict[str, Dict[str, str]] = {}  # snapshot_id -> {file: content}
        self._lock = __import__("threading").Lock()

    # ---- 快照 ----
    def snapshot(self, files: List[str]) -> str:
        """对文件列表拍快照（内存 + 磁盘）"""
        sid = uuid.uuid4().hex[:12]
        contents: Dict[str, str] = {}
        for fp in files:
            try:
                if os.path.isfile(fp):
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        contents[fp] = f.read()
            except Exception:
                contents[fp] = ""
        with self._lock:
            self._mem[sid] = contents
        # 落盘
        try:
            dest = os.path.join(self.snapshot_dir, sid)
            os.makedirs(dest, exist_ok=True)
            for fp, content in contents.items():
                rel = fp.replace(":", "_").replace(os.sep, "_")
                with open(os.path.join(dest, rel), "w", encoding="utf-8") as f:
                    f.write(content)
        except Exception:
            pass
        return sid

    # ---- 回滚 ----
    def rollback(self, snapshot_id: str) -> bool:
        """恢复到指定快照"""
        with self._lock:
            contents = self._mem.get(snapshot_id)
        if contents is None:
            return False
        for fp, content in contents.items():
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception:
                return False
        return True

    def clear_snapshot(self, snapshot_id: str) -> None:
        with self._lock:
            self._mem.pop(snapshot_id, None)
        try:
            shutil.rmtree(os.path.join(self.snapshot_dir, snapshot_id), ignore_errors=True)
        except Exception:
            pass

    # ---- 静态校验 ----
    def validate_edit(self, old: str, new: str) -> List[str]:
        """静态检查 (缩进/引号/BOM/大小)，返回问题列表（空=通过）"""
        problems: List[str] = []
        if old == new:
            problems.append("old 与 new 相同，编辑无效")
        if not old.strip():
            problems.append("old 为空，可能误删整个内容")
        # 缩进一致性：首行缩进对比
        old_indent = len(old) - len(old.lstrip(" "))
        new_indent = len(new) - len(new.lstrip(" "))
        if old_indent != new_indent:
            problems.append(f"缩进变化: old={old_indent} 空格 → new={new_indent} 空格")
        # 引号平衡
        for q in ('"', "'"):
            if old.count(q) % 2 != new.count(q) % 2:
                problems.append(f"{q} 引号数量不平衡，可能语法错误")
        # BOM
        if "\ufeff" in new and "\ufeff" not in old:
            problems.append("新增了 BOM 头，可能破坏文件")
        # 大小骤增（>10x 且 >50KB）
        if old and len(new) > len(old) * 10 and len(new) > 50 * 1024:
            problems.append("文件大小异常增长，疑似错误粘贴")
        return problems

    # ---- 高风险确认 ----
    def confirm_high_risk(
        self, edit: str, confirm_callback: Optional[Callable[[str], bool]] = None
    ) -> bool:
        """命中高风险模式时要求确认。

        confirm_callback 返回 True 表示允许；未注入时默认放行（非交互环境）。
        """
        for pattern, desc in _HIGH_RISK:
            if pattern.lower() in edit.lower():
                if confirm_callback is not None:
                    return confirm_callback(f"高风险操作 [{desc}]: {edit[:80]}")
                return True  # 非交互环境默认放行，由 guard_loop 兜底
        return True

    # ---- 护栏装饰器 ----
    def guard_loop(self, loop_run: Callable) -> Callable:
        """装饰器：每轮自动 snapshot，失败自动回滚 + 记录教训"""

        @functools.wraps(loop_run)
        def _wrapped(report, workspace, *args, **kwargs):
            # snapshot 涉及的所有目标文件
            files = []
            try:
                from auto_dev_loop import AutoDevLoop
                files = AutoDevLoop(workspace=workspace).plan_files(
                    report.user_request, workspace
                )
            except Exception:
                files = []
            sid = self.snapshot(files) if files else ""
            try:
                result = loop_run(report, workspace, *args, **kwargs)
                # 标记是否回滚
                if getattr(result, "rollback_happened", False):
                    self.rollback(sid)
                    self._record_lesson(report, "编辑失败，已自动回滚")
                else:
                    if sid:
                        self.clear_snapshot(sid)
                return result
            except Exception as e:
                if sid:
                    self.rollback(sid)
                self._record_lesson(report, f"闭环异常，已自动回滚: {e}")
                report.rollback_happened = True
                report.ok = False
                report.summary = f"闭环异常，已自动回滚: {e}"
                return report

        return _wrapped

    # ---- 内部 ----
    def _record_lesson(self, report, msg: str) -> None:
        try:
            os.makedirs(os.path.dirname(_LESSONS_PATH), exist_ok=True)
            lessons = []
            if os.path.isfile(_LESSONS_PATH):
                with open(_LESSONS_PATH, "r", encoding="utf-8") as f:
                    lessons = json.load(f)
            report.lessons.append(msg)
            lessons.append({
                "request": getattr(report, "user_request", ""),
                "lessons": [msg],
                "ts": time.time(),
                "auto_rollback": True,
            })
            with open(_LESSONS_PATH, "w", encoding="utf-8") as f:
                json.dump(lessons, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
