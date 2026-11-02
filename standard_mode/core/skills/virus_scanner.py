# -*- coding: utf-8 -*-
"""Skill: virus_scanner — Windows Defender MpCmdRun封装"""

import sys, os, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "virus_scanner",
    "description": "病毒扫描：封装Windows Defender MpCmdRun，支持快速/全盘/自定义扫描，默认报告模式。",
    "category": "system",
    "version": "1.0.0",
}

_MPCMDRUN_PATHS = [
    r"C:\ProgramData\Microsoft\Windows Defender\platform\*\MpCmdRun.exe",
    r"C:\Program Files\Windows Defender\MpCmdRun.exe",
]


def _find_mpcmdrun() -> str:
    import glob
    for pattern in _MPCMDRUN_PATHS:
        matches = glob.glob(pattern)
        if matches:
            return max(matches)
    return ""


def execute(scan_type: str = "quick", scan_path: str = "", dry_run: bool = True) -> SkillResult:
    mpcmdrun = _find_mpcmdrun()
    if not mpcmdrun:
        return SkillResult(
            success=False,
            error="未找到MpCmdRun.exe",
            output="Windows Defender命令行工具不可用。请确认Windows Defender已启用。",
        )

    if scan_type not in ("quick", "full", "custom"):
        return SkillResult(success=False, error=f"无效扫描类型: {scan_type}")

    cmd = [mpcmdrun, "-Scan", f"-ScanType", {"quick": "1", "full": "2", "custom": "3"}[scan_type]]
    if scan_type == "custom" and scan_path:
        cmd.extend(["-File", os.path.expanduser(scan_path)])

    if dry_run:
        report = f"病毒扫描计划 (报告模式)\n"
        report += f"扫描类型: {scan_type}\n"
        report += f"命令: {' '.join(cmd)}\n"
        report += f"引擎: {os.path.basename(mpcmdrun)}\n"
        return SkillResult(success=True, output=report,
                           data={"scan_type": scan_type, "dry_run": True, "cmd": " ".join(cmd)})

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        output = result.stdout or result.stderr
        return SkillResult(
            success=result.returncode == 0,
            output=f"扫描完成:\n{output}",
            data={"returncode": result.returncode, "scan_type": scan_type},
        )
    except subprocess.TimeoutExpired:
        return SkillResult(success=False, error="扫描超时(600s)")
    except Exception as e:
        return SkillResult(success=False, error=f"扫描失败: {e}")


def register(registry) -> None:
    registry.register(SkillDef(
        name="virus_scanner",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "scan_type": {"type": "string", "enum": ["quick", "full", "custom"],
                              "description": "扫描类型", "default": "quick"},
                "scan_path": {"type": "string", "description": "自定义扫描路径(scan_type=custom时)"},
                "dry_run": {"type": "boolean", "description": "仅生成报告不执行扫描", "default": True},
            },
            "required": [],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=True,
        timeout=600,
    ))


def get_metadata():
    return METADATA
