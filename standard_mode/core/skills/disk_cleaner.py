# -*- coding: utf-8 -*-
"""Skill: disk_cleaner — 磁盘垃圾三档分类：可删/需审查/勿动"""

import sys, os, hashlib, tempfile, shutil
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "disk_cleaner",
    "description": "磁盘垃圾扫描与分类：三档（可安全删除/需审查/勿动），默认报告模式不删除，破坏性操作需execute=True。",
    "category": "system",
    "version": "1.0.0",
}

_SAFE_EXTENSIONS = frozenset([
    ".tmp", ".temp", ".log", ".cache", ".bak", ".old",
    ".gid", ".chk", ".dmp", ".err", ".~",
])

_SAFE_DIRS = frozenset([
    "__pycache__", ".pytest_cache", "node_modules/.cache",
    ".mypy_cache", ".ruff_cache",
])

_REVIEW_EXTENSIONS = frozenset([
    ".pyc", ".pyo", ".class", ".obj", ".pdb", ".ilk",
])

_NEVER_EXTENSIONS = frozenset([
    ".exe", ".dll", ".sys", ".drv", ".msi",
    ".reg", ".ini", ".cfg", ".conf",
])


def execute(scan_path: str = "", dry_run: bool = True, execute: bool = False,
            category_filter: str = "all") -> SkillResult:
    if not scan_path:
        scan_path = tempfile.gettempdir()

    root = os.path.expanduser(scan_path)
    if not os.path.isdir(root):
        return SkillResult(success=False, error=f"路径不存在: {root}")

    safe_items = []
    review_items = []
    never_items = []

    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(fp)
            except OSError:
                continue
            ext = os.path.splitext(fn)[1].lower()
            dn = os.path.basename(dirpath)

            if ext in _NEVER_EXTENSIONS or fn in _NEVER_EXTENSIONS:
                never_items.append((fp, size))
            elif dn in _SAFE_DIRS or ext in _SAFE_EXTENSIONS:
                safe_items.append((fp, size))
            elif ext in _REVIEW_EXTENSIONS:
                review_items.append((fp, size))

        for dn in list(dirnames):
            dp = os.path.join(dirpath, dn)
            if dn in _SAFE_DIRS:
                try:
                    total = sum(os.path.getsize(os.path.join(dp, f))
                                for f in os.listdir(dp)
                                if os.path.isfile(os.path.join(dp, f)))
                    safe_items.append((dp, total))
                except OSError:
                    pass

    safe_size = sum(s for _, s in safe_items)
    review_size = sum(s for _, s in review_items)

    report = f"磁盘扫描报告: {root}\n"
    report += f"{'='*50}\n"
    report += f"🟢 可安全删除: {len(safe_items)} 项, {_fmt_size(safe_size)}\n"
    report += f"🟡 需审查: {len(review_items)} 项, {_fmt_size(review_size)}\n"
    report += f"🔴 勿动: {len(never_items)} 项\n"
    report += f"模式: {'仅报告' if dry_run else '执行'}\n\n"

    if category_filter in ("all", "safe") and safe_items[:20]:
        report += "--- 可安全删除 (前20项) ---\n"
        for fp, sz in safe_items[:20]:
            report += f"  {_fmt_size(sz):>10}  {fp}\n"

    if category_filter in ("all", "review") and review_items[:10]:
        report += "\n--- 需审查 (前10项) ---\n"
        for fp, sz in review_items[:10]:
            report += f"  {_fmt_size(sz):>10}  {fp}\n"

    deleted_count = 0
    freed_size = 0
    if execute and not dry_run:
        for fp, sz in safe_items:
            try:
                trash_dir = os.path.join(os.path.dirname(fp), ".trash")
                os.makedirs(trash_dir, exist_ok=True)
                dest = os.path.join(trash_dir, os.path.basename(fp))
                shutil.move(fp, dest)
                deleted_count += 1
                freed_size += sz
            except OSError:
                pass
        report += f"\n已软删除到 .trash/: {deleted_count} 项, 释放 {_fmt_size(freed_size)}\n"

    return SkillResult(
        success=True,
        output=report,
        data={"safe_count": len(safe_items), "safe_size": safe_size,
              "review_count": len(review_items), "review_size": review_size,
              "never_count": len(never_items), "deleted": deleted_count,
              "freed": freed_size, "dry_run": dry_run},
    )


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def register(registry) -> None:
    registry.register(SkillDef(
        name="disk_cleaner",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "scan_path": {"type": "string", "description": "扫描路径，默认系统临时目录"},
                "dry_run": {"type": "boolean", "description": "仅生成报告不删除", "default": True},
                "execute": {"type": "boolean", "description": "确认执行删除（破坏性操作）", "default": False},
                "category_filter": {"type": "string", "enum": ["all", "safe", "review"], "default": "all"},
            },
            "required": [],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=True,
        timeout=120,
    ))


def get_metadata():
    return METADATA
