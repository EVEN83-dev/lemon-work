# -*- coding: utf-8 -*-
"""383A-2: 技能执行审计流

统一的技能/工具调用审计入口：
* 落盘 ``data/audit/skill_audit_YYYYMM.jsonl``（按月滚动，单行 JSON）
* 单文件超过 5MB 自动轮转为 ``.1``（保留一份历史）
* 参数**脱敏**：敏感键打码 + 值截断，避免密钥/口令进入审计文件
* 兼容 382B 预留的 MCP 审计标记 ``_audit_tag``（mcp_call / mcp_blocked / mcp_error，
  定义于 ``shared/mcp_server_skills.py``，B 战区文件——本模块只接收字段、不修改该文件），
  使 MCP 端调用与 Agent 端调用并入同一审计流。

零新增依赖（纯标准库）。
"""

import json
import os
import threading
import time
from typing import Any, Dict, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_DIR = os.path.join(_PROJECT_ROOT, "data", "audit")

_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB 滚动阈值
_MAX_ARG_CHARS = 300               # 参数摘要截断长度

_LOCK = threading.Lock()

# 敏感键：值一律打码，不落盘原文
_SENSITIVE_KEYS = {
    "password", "passwd", "pwd", "token", "api_key", "apikey",
    "secret", "access_key", "secret_key", "authorization", "cookie",
    "private_key", "credential",
}


def _ensure_dir() -> str:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    return AUDIT_DIR


def _mask_args(args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """参数脱敏：敏感键打码，长值截断。"""
    if not isinstance(args, dict) or not args:
        return {}
    masked: Dict[str, Any] = {}
    for k, v in list(args.items())[:20]:  # 最多记录 20 个键
        k_lower = str(k).lower()
        is_sensitive = any(s in k_lower for s in _SENSITIVE_KEYS)
        if is_sensitive:
            masked[k] = "***"
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            s = str(v)
            masked[k] = s if len(s) <= 200 else s[:200] + "..."
        else:
            s = str(v)
            masked[k] = s[:_MAX_ARG_CHARS] + ("..." if len(s) > _MAX_ARG_CHARS else "")
    return masked


def _rotate_if_needed(path: str) -> None:
    """超过 5MB 轮转为 .1（只保留一份历史，避免磁盘膨胀）。"""
    try:
        if os.path.exists(path) and os.path.getsize(path) > _MAX_FILE_BYTES:
            backup = f"{path}.1"
            if os.path.exists(backup):
                os.remove(backup)
            os.replace(path, backup)
    except Exception:
        pass


def record_skill_audit(tool_name: str, args: Optional[Dict[str, Any]] = None,
                       elapsed: float = 0.0, success: bool = True,
                       error: str = "", source: str = "agent_chat",
                       audit_tag: str = "", session_id: str = "") -> Optional[Dict[str, Any]]:
    """记录一次技能/工具调用。

    参数
    ----
    tool_name  技能名
    args       原始参数（内部脱敏后落盘）
    elapsed    耗时（秒）
    success    是否成功
    error      错误信息（截断）
    source     调用来源：agent_chat / mcp / ...
    audit_tag  382B 预留的 MCP 审计标记（mcp_call/mcp_blocked/mcp_error），
               MCP 端调用时传入以并入同一审计流
    """
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ts_epoch": round(time.time(), 3),
        "tool": tool_name,
        "args": _mask_args(args),
        "elapsed": round(float(elapsed or 0.0), 3),
        "success": bool(success),
        "error": (error or "")[:300],
        "source": source,
        "audit_tag": audit_tag,
        "session_id": session_id,
    }
    try:
        _ensure_dir()
        path = os.path.join(AUDIT_DIR, f"skill_audit_{time.strftime('%Y%m')}.jsonl")
        with _LOCK:
            _rotate_if_needed(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # 审计失败绝不能阻断主流程
        pass
    return entry


def read_recent_audits(limit: int = 50, month: str = "") -> list:
    """读取最近审计记录（供验收与排查用）。"""
    path = os.path.join(AUDIT_DIR, f"skill_audit_{month or time.strftime('%Y%m')}.jsonl")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        out = []
        for ln in lines[-limit:]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out
    except Exception:
        return []
