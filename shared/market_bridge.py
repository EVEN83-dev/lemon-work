# -*- coding: utf-8 -*-
"""
shared/market_bridge.py — 技能市场下载闭环（第362章 · 子任务2）
================================================================
职责：从技能市场（shared/skills/skill_market.py · SkillMarket）下载一个技能，
自动重跑三关验证，通过则注册为正式技能；未通过则保留落盘文件 + 显式返回失败详情。

铁律：禁止改动 skill_market.py（冻结区 skill_market 市场后端）；
      禁止直接 requests.post；一切 AI 调用走既有 engine 接口。

公开 API：
    download_and_register(skill_meta, registry=None, target_dir=None) -> dict
        skill_meta: 至少包含 name（字符串）。可含 author/category/version/description。
        registry:   SkillsRegistry（省略则取单例）
        target_dir: 落盘目录（省略则用 skills/user_built/）
        Returns:    {"success": bool, "error": str, "data": {...}}

    list_market_skills() -> dict        （市场清单，透传给 SkillMarket 搜索）
    market_skill_info(name: str) -> dict
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

# 项目根 = 本文件向上两级（shared → lemon_agent）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_BUILT_DIR = os.path.join(_REPO_ROOT, "skills", "user_built")


# ----------------------------------------------------------------
# 内部：延迟解析冻结区 / 共享 API
# ----------------------------------------------------------------
def _resolve_tmp_manager():
    try:
        from standard_mode.core.skills import tmp_skill_manager as _tsm
        return _tsm
    except ImportError:
        pass
    try:
        from core.skills import tmp_skill_manager as _tsm
        return _tsm
    except ImportError:
        pass
    return None


def _resolve_skill_market():
    """加载技能市场后端（shared/skills/skill_market.py；不是冻结区的 core/skill_market.py）。"""
    try:
        from shared.skills.skill_market import SkillMarket, SkillMeta
        return SkillMarket, SkillMeta
    except ImportError:
        pass
    try:
        # 顶层也可能有（同共享技能路由）
        from shared.skills.skill_market import SkillMarket, SkillMeta
        return SkillMarket, SkillMeta
    except ImportError:
        pass
    # 回退：手动定位
    sm_path = os.path.join(_REPO_ROOT, "shared", "skills", "skill_market.py")
    if not os.path.isfile(sm_path):
        raise ImportError(f"skill_market 不可用: {sm_path}")
    spec = importlib.util.spec_from_file_location("_skill_market_frozen", sm_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SkillMarket, mod.SkillMeta


def _resolve_registry(registry=None):
    if registry is not None:
        return registry
    try:
        from standard_mode.core.skills_registry import get_skills_registry
        return get_skills_registry()
    except ImportError:
        pass
    try:
        from core.skills_registry import get_skills_registry
        return get_skills_registry()
    except ImportError:
        return None


def _load_handler_from_file(file_path: str) -> Optional[Callable]:
    try:
        base = os.path.splitext(os.path.basename(file_path))[0]
        mod_name = f"market_built_{base}_{int(time.time() * 1000) % 100000}"
        spec = importlib.util.spec_from_file_location(mod_name, file_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, "execute", None)
        return fn if callable(fn) else None
    except Exception as e:
        traceback.print_exc()
        return None


def _extract_schema_from_code(code: str) -> Dict:
    try:
        import ast as _ast
        tree = _ast.parse(code)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Assign):
                for t in node.targets:
                    if getattr(t, "id", "") == "PARAMS_SCHEMA":
                        return _ast.literal_eval(node.value)
    except Exception:
        pass
    return {"type": "object", "properties": {}}


# ----------------------------------------------------------------
# 公开 API
# ----------------------------------------------------------------
def download_and_register(skill_meta: Dict[str, Any],
                          registry=None,
                          target_dir: Optional[str] = None,
                          market=None) -> Dict[str, Any]:
    """市场下载 → 自动三关 → 通过则注册正式技能；不通过则保留文件 + 显式三关失败详情。

    Args:
        skill_meta: {"name": 必要, "author": ?, "category": ?, "version": ?,
                     "description": ?, "tags": ?}
        registry:   省略则取单例
        target_dir: 落盘目录（默认 skills/user_built/）

    Returns: {
        "success": bool,
        "error": str or None,
        "data": {
            "name": str,
            "source": "file_copy" | "source_code" | "generated",
            "file": "skills/user_built/xxx.py",
            "gates": {gate1_ast: {pass, msg}, ...},
            "registered": True | False,
            "gate_failure": None | {"failed_gate": ..., "detail": ...},
            "meta": {...},
        }
    }
    """
    if not isinstance(skill_meta, dict) or not skill_meta.get("name"):
        return {"success": False, "error": "skill_meta 缺少 name 字段", "data": None}
    name = str(skill_meta["name"]).strip()

    SkillMarket, SkillMeta = _resolve_skill_market()
    if market is None:
        market = SkillMarket()
    target_dir = target_dir or USER_BUILT_DIR
    reg = _resolve_registry(registry)
    if reg is None:
        return {"success": False, "error": "注册表单例不可用", "data": {"name": name}}

    # 1) 下载（调用 skill_market 公开 download API；不动它本身）
    dl = market.download_skill(name, target_dir)
    if not dl.get("success"):
        return {"success": False,
                "error": f"市场下载失败 [{name}]: {dl.get('error', '未知')}",
                "data": {"name": name, "download": dl}}

    file_path = dl.get("target_path", "")
    if not file_path:
        file_path = os.path.join(target_dir, name + ".py")
    if not os.path.isfile(file_path):
        # _generate_skill_module 生成的文件名也可能不一致 → 再扫一次
        for f in os.listdir(target_dir):
            if f.startswith(name) and f.endswith(".py"):
                file_path = os.path.join(target_dir, f)
                break
    if not os.path.isfile(file_path):
        return {"success": False,
                "error": f"下载成功但落盘文件找不到: name={name}, expected={file_path}",
                "data": {"name": name, "download": dl}}
    # 2) 读取真实代码
    try:
        code = open(file_path, "r", encoding="utf-8").read()
    except Exception as e:
        # 清理脏文件并上报
        try:
            os.remove(file_path)
        except Exception:
            pass
        return {"success": False,
                "error": f"读取下载产物失败: {e}", "data": {"file": file_path}}
    if not code.strip():
        try:
            os.remove(file_path)
        except Exception:
            pass
        return {"success": False,
                "error": f"下载产物为空文件: {file_path}", "data": {"file": file_path}}

    # 3) 三关验证（调用 tmp_skill_manager 公开 API）
    schema = _extract_schema_from_code(code)
    tsm = _resolve_tmp_manager()
    if tsm is None:
        return {"success": False, "error": "tmp_skill_manager 不可用（冻结区未定位）",
                "data": {"name": name, "file": file_path}}
    all_ok, gate_report = tsm.run_three_gates(name, code, schema)
    failed_gate = next((k for k, v in gate_report.items()
                        if not v.get("pass")), None)
    if not all_ok:
        # 保留文件 + 显式失败详情（含是哪一关失败）
        detail = "; ".join(f"{k}: {v.get('msg', '')}"
                           for k, v in gate_report.items() if not v.get("pass"))
        try:
            _persist_gate_failure(name, file_path, gate_report, dl.get("skill"))
        except Exception:
            pass
        return {
            "success": False,
            "error": f"三关验证未通过 [{name}]: {detail}",
            "data": {
                "name": name, "file": file_path, "gates": gate_report,
                "registered": False,
                "gate_failure": {"failed_gate": failed_gate, "detail": detail},
                "meta": dl.get("skill"),
            },
        }
    # 4) 三关通过 → 装载 + 注册正式技能
    handler = _load_handler_from_file(file_path)
    if handler is None:
        return {"success": False,
                "error": f"三关已通过但 handler 装载失败 [{name}]: {file_path}",
                "data": {"name": name, "file": file_path, "gates": gate_report}}
    try:
        from standard_mode.core.skills_registry import SkillDef
    except ImportError:
        from core.skills_registry import SkillDef
    skill_def = SkillDef(
        name=name,
        description=(dl.get("skill", {}).get("description",
                                             skill_meta.get("description", name))
                    if isinstance(dl.get("skill"), dict) else (skill_meta.get("description") or name)),
        parameters=schema, handler=handler,
        category=(dl.get("skill", {}).get("category", "general")
                  if isinstance(dl.get("skill"), dict) else "general"),
        timeout=30,
    )
    reg.register(skill_def)
    return {
        "success": True,
        "error": None,
        "data": {
            "name": name,
            "file": file_path,
            "gates": gate_report,
            "registered": True,
            "gate_failure": None,
            "meta": dl.get("skill"),
        },
    }


def _persist_gate_failure(name: str, file_path: str, gate_report: Dict,
                          market_meta: Any = None):
    """写入失败凭据到 data/v6_runs/market_bridge_gate_failures.jsonl；
    供 UI / 复跑验证追溯，不静默吞。"""
    try:
        log = os.path.join(_REPO_ROOT, "data", "v6_runs",
                           "market_bridge_gate_failures.jsonl")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "name": name,
            "file": file_path,
            "gates": gate_report,
            "market_meta": market_meta,
        }
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def list_market_skills(category: str = "") -> Dict[str, Any]:
    """透传市场搜索；搜索失败显式返回。"""
    try:
        SkillMarket, _ = _resolve_skill_market()
        m = SkillMarket()
        skills = m.search_skills(category) if category else m.search_skills()
        # 规范化：兼容返回 list[SkillMeta] 或 list[dict]
        items = []
        for s in (skills or []):
            if hasattr(s, "to_dict"):
                items.append(s.to_dict())
            elif isinstance(s, dict):
                items.append(s)
        return {"success": True, "count": len(items), "items": items}
    except Exception as e:
        return {"success": False, "error": f"市场搜索失败: {e}", "count": 0, "items": []}


def market_skill_info(name: str) -> Dict[str, Any]:
    """单技能详情。"""
    try:
        SkillMarket, _ = _resolve_skill_market()
        m = SkillMarket()
        info = m.get_skill(name)
        if info is None:
            return {"success": False, "error": f"市场未找到: {name}"}
        if hasattr(info, "to_dict"):
            info = info.to_dict()
        return {"success": True, "info": info}
    except Exception as e:
        return {"success": False, "error": f"市场查询失败: {e}"}
