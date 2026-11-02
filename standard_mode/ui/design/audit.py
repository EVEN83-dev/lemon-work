# -*- coding: utf-8 -*-
"""Lemon Agent 样式审计工具
扫描 setStyleSheet 中的硬编码十六进制色值, 对照 Lemon 令牌建议替换
用法: python -m standard_mode.ui.design.audit
"""
import os
import re
from typing import List, Tuple

_HEX_PAT = re.compile(r'#[0-9A-Fa-f]{6}\b')
_DESIGN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
_TOKEN_MAP = {
    "Lemon.PRIMARY": "Lemon.PRIMARY",
    "Lemon.SECONDARY": "Lemon.SECONDARY",
    "Lemon.BG": "Lemon.BG",
    "Lemon.SURFACE": "Lemon.SURFACE",
    "Lemon.BORDER": "Lemon.BORDER",
    "Lemon.BORDER_HOVER": "Lemon.BORDER_HOVER",
    "Lemon.SUCCESS": "Lemon.SUCCESS",
    "Lemon.ERROR": "Lemon.ERROR",
    "Lemon.BRAND_LEMON": "Lemon.BRAND_LEMON",
    "Lemon.BRAND_ORANGE": "LEMON_ORANGE(legacy)",
    "Lemon.DARK_MIMO_ORANGE": "LEMON_ORANGE(legacy)",
    "Lemon.SCROLLBAR_THUMB": "scrollbar-thumb",
    "#BFBFBF": "scrollbar-thumb-hover",
}


def audit_file(filepath: str) -> List[Tuple[int, str, str]]:
    results = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    for i, line in enumerate(lines, 1):
        for match in _HEX_PAT.finditer(line):
            hex_val = match.group()
            suggestion = _TOKEN_MAP.get(hex_val, "(no mapping)")
            results.append((i, hex_val, suggestion))
    return results


def audit_directory(dir_path: str, exclude_design: bool = True) -> dict:
    report = {}
    for root, dirs, fnames in os.walk(dir_path):
        if exclude_design and "design" in root:
            continue
        for fn in fnames:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(root, fn)
            hits = audit_file(fp)
            if hits:
                report[fp] = hits
    return report


def print_report(report: dict):
    total = sum(len(v) for v in report.values())
    print(f"Total hardcoded hex colors: {total}")
    for fp, hits in sorted(report.items(), key=lambda x: -len(x[1])):
        print(f"\n  {os.path.basename(fp)}: {len(hits)} hits")
        for line_no, hex_val, suggestion in hits[:5]:
            print(f"    L{line_no}: {hex_val} -> {suggestion}")
        if len(hits) > 5:
            print(f"    ... and {len(hits) - 5} more")


if __name__ == "__main__":
    ui_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))),
        "standard_mode", "ui"
    )
    report = audit_directory(ui_dir)
    print_report(report)
