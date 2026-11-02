# -*- coding: utf-8 -*-
"""Skill: system_report — CPU/内存/磁盘/启动项体检报告"""

import sys, os, platform, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "system_report",
    "description": "系统体检报告：CPU/内存/磁盘/网络/启动项/进程Top，纯只读。",
    "category": "system",
    "version": "1.0.0",
}


def execute(report_type: str = "full", top_n: int = 10) -> SkillResult:
    sections = []
    sections.append(_os_info())
    sections.append(_cpu_info())
    sections.append(_memory_info())
    sections.append(_disk_info())
    sections.append(_top_processes(top_n))

    if report_type == "full":
        sections.append(_startup_items())
        sections.append(_network_info())

    report = "系统体检报告\n" + "=" * 50 + "\n\n"
    report += "\n\n".join(sections)

    return SkillResult(
        success=True,
        output=report,
        data={"report_type": report_type, "os": platform.system(),
              "python": platform.python_version()},
    )


def _os_info() -> str:
    return f"[系统信息]\n  OS: {platform.system()} {platform.release()}\n  版本: {platform.version()}\n  架构: {platform.machine()}\n  Python: {platform.python_version()}"


def _cpu_info() -> str:
    lines = [f"[CPU]"]
    try:
        import psutil
        lines.append(f"  物理核心: {psutil.cpu_count(logical=False)}")
        lines.append(f"  逻辑核心: {psutil.cpu_count(logical=True)}")
        lines.append(f"  使用率: {psutil.cpu_percent(interval=1)}%")
    except ImportError:
        lines.append(f"  核心数: {os.cpu_count()}")
        lines.append("  [psutil未安装，详细数据不可用]")
    return "\n".join(lines)


def _memory_info() -> str:
    lines = ["[内存]"]
    try:
        import psutil
        mem = psutil.virtual_memory()
        lines.append(f"  总量: {mem.total // (1024**3)} GB")
        lines.append(f"  已用: {mem.used // (1024**3)} GB ({mem.percent}%)")
        lines.append(f"  可用: {mem.available // (1024**3)} GB")
    except ImportError:
        lines.append("  [psutil未安装]")
    return "\n".join(lines)


def _disk_info() -> str:
    lines = ["[磁盘]"]
    try:
        import psutil
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(f"  {part.mountpoint}: {usage.used//(1024**3)}/{usage.total//(1024**3)} GB ({usage.percent}%) [{part.fstype}]")
            except PermissionError:
                pass
    except ImportError:
        lines.append("  [psutil未安装]")
    return "\n".join(lines)


def _top_processes(n: int) -> str:
    lines = [f"[Top {n} 进程]"]
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_percent']):
            try:
                procs.append((p.info['memory_percent'] or 0, p.info['name'], p.info['pid']))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(reverse=True)
        for mem, name, pid in procs[:n]:
            lines.append(f"  {mem:6.1f}%  {name} (PID:{pid})")
    except ImportError:
        lines.append("  [psutil未安装]")
    return "\n".join(lines)


def _startup_items() -> str:
    lines = ["[启动项]"]
    try:
        result = subprocess.run(
            ["wmic", "startup", "get", "Caption,Command", "/format:list"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)
        for ln in result.stdout.strip().split("\n"):
            ln = ln.strip()
            if ln:
                lines.append(f"  {ln}")
    except Exception:
        lines.append("  [查询失败]")
    return "\n".join(lines)


def _network_info() -> str:
    lines = ["[网络]"]
    try:
        import psutil
        net = psutil.net_io_counters()
        lines.append(f"  发送: {net.bytes_sent // (1024**2)} MB")
        lines.append(f"  接收: {net.bytes_recv // (1024**2)} MB")
    except ImportError:
        lines.append("  [psutil未安装]")
    return "\n".join(lines)


def register(registry) -> None:
    registry.register(SkillDef(
        name="system_report",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "report_type": {"type": "string", "enum": ["full", "quick"],
                                "description": "报告类型", "default": "full"},
                "top_n": {"type": "integer", "description": "Top进程数量", "default": 10},
            },
            "required": [],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata():
    return METADATA
