# -*- coding: utf-8 -*-
"""Skill: duplicate_finder — 哈希查重"""

import sys, os, hashlib
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "duplicate_finder",
    "description": "文件查重：基于SHA256哈希检测重复文件，生成重复组报告，默认报告模式。",
    "category": "system",
    "version": "1.0.0",
}


def execute(directory: str = "", min_size: int = 1024, dry_run: bool = True,
            delete_mode: str = "report") -> SkillResult:
    if not directory:
        return SkillResult(success=False, error="directory 参数为空")

    root = os.path.expanduser(directory)
    if not os.path.isdir(root):
        return SkillResult(success=False, error=f"目录不存在: {root}")

    size_map = defaultdict(list)
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                sz = os.path.getsize(fp)
                if sz >= min_size:
                    size_map[sz].append(fp)
            except OSError:
                continue

    hash_map = defaultdict(list)
    checked = 0
    for sz, paths in size_map.items():
        if len(paths) < 2:
            continue
        for fp in paths:
            h = _sha256(fp)
            if h:
                hash_map[h].append(fp)
                checked += 1

    dupes = {h: ps for h, ps in hash_map.items() if len(ps) > 1}
    wasted = sum((len(ps) - 1) * os.path.getsize(ps[0]) for ps in dupes.values())

    report = f"查重报告: {root}\n{'='*50}\n"
    report += f"扫描文件(≥{_fmt_size(min_size)}): {sum(len(v) for v in size_map.values())}\n"
    report += f"哈希校验: {checked}\n"
    report += f"重复组: {len(dupes)}\n"
    report += f"浪费空间: {_fmt_size(wasted)}\n"
    report += f"模式: {delete_mode}\n\n"

    for i, (h, ps) in enumerate(list(dupes.items())[:20], 1):
        report += f"--- 重复组 #{i} ({_fmt_size(os.path.getsize(ps[0]))}) ---\n"
        for p in ps:
            report += f"  {p}\n"

    return SkillResult(
        success=True,
        output=report,
        data={"duplicate_groups": len(dupes), "wasted_bytes": wasted,
              "checked": checked, "dry_run": dry_run},
    )


def _sha256(fp: str) -> str:
    h = hashlib.sha256()
    try:
        with open(fp, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def register(registry) -> None:
    registry.register(SkillDef(
        name="duplicate_finder",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "扫描目录"},
                "min_size": {"type": "integer", "description": "最小文件大小(字节)", "default": 1024},
                "dry_run": {"type": "boolean", "description": "仅报告不删除", "default": True},
                "delete_mode": {"type": "string", "enum": ["report", "soft_delete"],
                                "description": "删除模式", "default": "report"},
            },
            "required": ["directory"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=300,
    ))


def get_metadata():
    return METADATA
