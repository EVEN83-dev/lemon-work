# -*- coding: utf-8 -*-
"""Skill: batch_renamer — EXIF日期/模板命名+回滚日志+undo"""

import csv
import sys, os, json, re, shutil
from datetime import datetime
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "batch_renamer",
    "description": "批量重命名：支持EXIF日期/序号模板/正则替换，生成CSV回滚日志，支持undo操作。",
    "category": "system",
    "version": "1.1.0",
}


def execute(directory: str = "", pattern: str = "{index:03d}_{name}",
            regex_filter: str = "", dry_run: bool = True,
            execute: bool = False, use_exif_date: bool = False,
            action: str = "rename", undo_log: str = "") -> SkillResult:
    if action == "undo":
        return _undo_rename(undo_log)

    if not directory:
        return SkillResult(success=False, error="directory 参数为空")

    root = os.path.expanduser(directory)
    if not os.path.isdir(root):
        return SkillResult(success=False, error=f"目录不存在: {root}")

    items = sorted(os.listdir(root))
    renames = []
    idx = 0

    for fn in items:
        fp = os.path.join(root, fn)
        if not os.path.isfile(fp):
            continue
        if regex_filter and not re.search(regex_filter, fn):
            continue

        name, ext = os.path.splitext(fn)
        new_name = pattern
        new_name = new_name.replace("{index:03d}", f"{idx:03d}")
        new_name = new_name.replace("{index:04d}", f"{idx:04d}")
        new_name = new_name.replace("{index}", str(idx))
        new_name = new_name.replace("{name}", name)
        new_name = new_name.replace("{ext}", ext)

        if use_exif_date:
            date_str = _get_exif_date(fp)
            if date_str:
                new_name = new_name.replace("{date}", date_str)

        new_name += ext if not new_name.endswith(ext) else ""
        if new_name != fn:
            renames.append((fn, new_name))
        idx += 1

    report = f"批量重命名报告: {root}\n"
    report += f"匹配文件: {idx}, 待重命名: {len(renames)}\n"
    report += f"模式: {'仅报告' if dry_run else '执行'}\n\n"

    for old, new in renames[:50]:
        report += f"  {old} -> {new}\n"

    executed_count = 0
    if execute and not dry_run:
        log_dir = os.path.join(root, ".rename_logs")
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(log_dir, f"rename_{ts}.csv")
        csv_rows = []

        for old, new in renames:
            old_fp = os.path.join(root, old)
            new_fp = os.path.join(root, new)
            try:
                os.rename(old_fp, new_fp)
                csv_rows.append({
                    "old_path": old_fp, "new_path": new_fp,
                    "timestamp": datetime.now().isoformat(),
                })
                executed_count += 1
            except OSError as e:
                report += f"  X rename failed: {old} ({e})\n"

        if csv_rows:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["old_path", "new_path", "timestamp"])
                writer.writeheader()
                writer.writerows(csv_rows)
            report += f"\nrollback CSV: {csv_path}\n"

    report += f"\nexecuted: {executed_count}/{len(renames)}"

    return SkillResult(
        success=True,
        output=report,
        data={"total": idx, "renames": len(renames), "executed": executed_count,
              "dry_run": dry_run, "action": action},
    )


def _undo_rename(log_path: str) -> SkillResult:
    if not log_path:
        return SkillResult(success=False, error="undo需要undo_log参数(CSV路径)")

    log_path = os.path.expanduser(log_path)
    if not os.path.isfile(log_path):
        return SkillResult(success=False, error=f"日志文件不存在: {log_path}")

    restored = 0
    skipped = 0
    errors = []

    with open(log_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for row in reversed(rows):
        current_path = row.get("new_path", "")
        original_path = row.get("old_path", "")
        if not current_path or not original_path:
            skipped += 1
            continue
        if not os.path.exists(current_path):
            skipped += 1
            errors.append(f"skip (not found): {current_path}")
            continue
        if os.path.exists(original_path):
            skipped += 1
            errors.append(f"skip (target exists): {original_path}")
            continue
        try:
            os.rename(current_path, original_path)
            restored += 1
        except OSError as e:
            errors.append(f"error: {current_path} -> {original_path} ({e})")

    report = f"Undo report: {log_path}\n"
    report += f"rows: {len(rows)}, restored: {restored}, skipped: {skipped}\n"
    if errors[:10]:
        report += "details:\n"
        for e in errors[:10]:
            report += f"  {e}\n"

    return SkillResult(
        success=restored > 0,
        output=report,
        data={"restored": restored, "skipped": skipped, "errors": len(errors)},
    )


def _get_exif_date(fp: str) -> str:
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
        img = Image.open(fp)
        exif = img._getexif()
        if exif:
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag == "DateTimeOriginal":
                    return str(value).replace(":", "").replace(" ", "_")[:15]
    except Exception:
        pass
    return ""


def register(registry) -> None:
    registry.register(SkillDef(
        name="batch_renamer",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "目标目录路径"},
                "pattern": {"type": "string", "description": "命名模板({index:03d}/{name}/{date}/{ext})",
                            "default": "{index:03d}_{name}"},
                "regex_filter": {"type": "string", "description": "文件名正则过滤"},
                "dry_run": {"type": "boolean", "description": "仅生成报告不执行", "default": True},
                "execute": {"type": "boolean", "description": "确认执行重命名", "default": False},
                "use_exif_date": {"type": "boolean", "description": "使用EXIF日期替换{date}", "default": False},
                "action": {"type": "string", "enum": ["rename", "undo"],
                           "description": "操作类型", "default": "rename"},
                "undo_log": {"type": "string", "description": "undo操作的CSV日志路径"},
            },
            "required": ["directory"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=True,
        timeout=60,
    ))


def get_metadata():
    return METADATA
