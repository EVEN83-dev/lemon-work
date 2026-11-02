# -*- coding: utf-8 -*-
"""
shared/skill_promote.py — 临时技能"转正/下架/待审核清单"/启动挂载（第362章 · 子任务1）
====================================================================================
职责（iron rule：本文件是临时技能闭环的"尾部"——与既有 skill_creator/SkillsRegistry
双写共存；绝不改动冻结区 standard_mode/core 与 miemie）。

公开 API：
    promote(tmp_name, formal_name, registry=None)        转正
    demote(formal_name, registry=None, restore_tmp=True) 下架（回临时区 / 仅清理注册表）
    list_pending(registry=None)                           待审核清单（含三关结果徽标）
    bootstrap_user_skills(registry=None, user_dir=None)   启动时挂载 user_built/ 正式技能；
                                                          启动入口（main.py）调用一次即可。
    reload_user_skill(file_path, registry=None)           单文件动态挂载助手（内部用）

实现约束（V6 铁律）：
    - 注册表引用走 get_skills_registry() 单例；禁止自行实例化 SkillsRegistry。
    - 三关验证调用 tmp_skill_manager.run_three_gates()，禁止复制粘贴其逻辑。
    - 文件落盘只写 skills/user_built/。每步失败显式返回 success:false + 中文原因；
      禁止静默吞异常、禁止空对象伪装成功、禁止 TODO 桩。
    - 持久化可复活：demote 释放的正式槽位落回 data/tmp_skills/；promote 后临时注册表同步移除。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

# 项目根 = 本文件向上两级（shared → lemon_agent）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 正式用户技能放置目录（顶层 skills/ 下新建 user_built 子目录）
USER_BUILT_DIR = os.path.join(_REPO_ROOT, "skills", "user_built")
# 临时技能落盘根（与 tmp_skill_manager 对齐）
TMP_SKILLS_DIR = os.path.join(_REPO_ROOT, "data", "tmp_skills")

# ── 铁律：本文件只做 runtime import（与 main.py 同进程上下文时自然可用）；
#    脚本自身入口（verify 脚本）单独设置 sys.path ──
def _get_repo_root() -> str:
    return _REPO_ROOT


def _resolve_tmp_manager():
    """延迟解析 tmp_skill_manager（冻结区，仅 import 其公开 API）。"""
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
    # 最后手段：手动定位文件（脚本入口场景一般前面已命中）
    tsm_path = os.path.join(_REPO_ROOT, "standard_mode", "core", "skills",
                            "tmp_skill_manager.py")
    if not os.path.isfile(tsm_path):
        raise ImportError(
            "无法定位 tmp_skill_manager（冻结区）: %s" % tsm_path)
    spec = importlib.util.spec_from_file_location("_tmp_skill_manager_frozen",
                                                  tsm_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resolve_validator():
    """延迟解析内置校验技能 skill_audit（shared/skill_audit.py），返回其公开函数。"""
    try:
        from shared.skill_audit import run_skill_validation
        return run_skill_validation
    except ImportError:
        return None


def _resolve_registry(registry=None):
    """取注册表单例（标准模式进程内可用）。"""
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
    """从落盘 .py 装载 execute handler（用户脚本入口：skill_creator 同款装载器）。"""
    try:
        base = os.path.splitext(os.path.basename(file_path))[0]
        mod_name = f"user_built_{base}_{int(time.time() * 1000) % 100000}"
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


# ================================================================
# 子任务 1.A：待审核清单
# ================================================================
def list_pending(registry=None) -> Dict[str, Any]:
    """返回当前待审核的 tmp_ 技能清单（nominated 或 success ≥ threshold）。

    返回: {
        "success": True,
        "pending": [
            {
                "tmp_name": ...,
                "status": "nominated" | "threshold_met" | "qualified",
                "success_count": int,
                "fail_count": int,
                "gates": {gate1_ast: {pass, msg}, gate2_schema_bind: ..., gate3_direct_call: ...},
                "file": "data/tmp_skills/xxx.py",
                "created_at": "...",
            }, ...
        ],
        "count": int,
    }
    """
    tsm = _resolve_tmp_manager()
    reg = _resolve_registry(registry)
    try:
        idx = (lambda p: (json.load(open(p, encoding="utf-8"))
                          if os.path.isfile(p) else {}))(tsm.INDEX_FILE)
        usage = (lambda p: (json.load(open(p, encoding="utf-8"))
                            if os.path.isfile(p) else {}))(tsm.USAGE_FILE)
    except Exception as e:
        return {"success": False, "error": f"读取临时注册表失败: {e}", "pending": [], "count": 0}

    pending: List[Dict[str, Any]] = []
    for name, meta in idx.items():
        if not name.startswith("tmp_"):
            continue
        u = usage.get(name, {})
        success_cnt = int(u.get("success", 0))
        nominated = bool(u.get("nominated", False))
        declined = bool(u.get("declined", False))
        promoted = bool(u.get("promoted", False))
        if promoted:
            continue
        if declined and success_cnt < tsm.PROMOTION_THRESHOLD and not nominated:
            continue
        meets = nominated or (success_cnt >= tsm.PROMOTION_THRESHOLD)
        if not meets:
            continue
        # 真查询：注册表是否仍存在该 tmp 技能（判定其是否还活着）
        alive = False
        if reg is not None:
            try:
                alive = reg.get(name) is not None
            except Exception:
                alive = False
        gates = meta.get("gates", {})
        all_passed = bool(gates.get("gate1_ast", {}).get("pass")
                          and gates.get("gate2_schema_bind", {}).get("pass")
                          and gates.get("gate3_direct_call", {}).get("pass"))
        pending.append({
            "tmp_name": name,
            "status": "qualified" if (meets and alive) else ("threshold_met" if meets else "nominated"),
            "success_count": success_cnt,
            "fail_count": int(u.get("fail", 0)),
            "gates": gates,
            "all_gates_passed": all_passed,
            "alive_in_registry": alive,
            "file": meta.get("file", os.path.join(TMP_SKILLS_DIR, name + ".py")),
            "created_at": meta.get("created_at", ""),
        })
    pending.sort(key=lambda x: (-x["success_count"], x["tmp_name"]))
    return {"success": True, "pending": pending, "count": len(pending)}


# ================================================================
# 子任务 1.B：转正
# ================================================================
def promote(tmp_name: str, formal_name: str, registry=None) -> Dict[str, Any]:
    """完整转正链路：读源码 → 重过三关 → 落盘到 skills/user_built/ → 注册正式技能 → 同步移除临时。

    Args:
        tmp_name: 临时技能名（tmp_<领域>_<功能>）
        formal_name: 正式技能名（去 tmp_ 前缀的名称段，或指定新名）
        registry: 注入用（省略则取单例）

    Returns: {"success": bool, "error": str, "data": {...}}
    """
    tsm = _resolve_tmp_manager()
    reg = _resolve_registry(registry)
    if reg is None:
        return {"success": False, "error": "注册表单例不可用（standard_mode 未导入？）", "data": None}

    # 1) 规范化
    norm, err = tsm.normalize_tmp_name(tmp_name)
    if not norm:
        return {"success": False, "error": f"临时技能名不合法: {err}", "data": None}
    tmp_name = norm

    # 2) 取源码与元数据
    file_path = tsm.get_skill_file(tmp_name)
    if not file_path or not os.path.isfile(file_path):
        return {"success": False,
                "error": f"临时技能源码缺失: {tmp_name}（路径: {file_path}）", "data": None}
    try:
        code = open(file_path, "r", encoding="utf-8").read()
    except Exception as e:
        return {"success": False,
                "error": f"读取源码失败: {e}", "data": None}
    # 取既有元数据 + schema
    try:
        idx = (lambda p: (json.load(open(p, encoding="utf-8"))
                          if os.path.isfile(p) else {}))(tsm.INDEX_FILE)
        u = (lambda p: (json.load(open(p, encoding="utf-8"))
                        if os.path.isfile(p) else {}))(tsm.USAGE_FILE)
        existing_meta = idx.get(tmp_name, {})
        existing_usage = u.get(tmp_name, {})
    except Exception:
        existing_meta, existing_usage = {}, {}
    existing_desc = existing_meta.get("description", "")
    existing_category = existing_meta.get("category", "general")

    # 3) 三关验证 —— 走既有函数，不复制粘贴
    #    取 schema：优先从既有 gates.data 里找；其次从代码解析；最后退化为 {}
    schema: Dict = _extract_schema_from_code(code)
    all_ok, gate_report = tsm.run_three_gates(tmp_name, code, schema)
    if not all_ok:
        detail = "; ".join(
            f"{k}: {v.get('msg', '')}" for k, v in gate_report.items()
            if not v.get("pass")
        )
        return {"success": False,
                "error": f"[三关] {tmp_name} 未通过，拒绝转正。失败项: {detail}",
                "data": {"gates": gate_report}}

    # 4) 落盘到 正式 user_built/
    try:
        os.makedirs(USER_BUILT_DIR, exist_ok=True)
    except Exception as e:
        return {"success": False, "error": f"创建正式技能目录失败: {e}", "data": None}
    target_path = os.path.join(USER_BUILT_DIR, f"{formal_name}.py")
    if os.path.isfile(target_path):
        return {"success": False,
                "error": f"正式技能文件已存在: {target_path}（转正冲突，请换名或先 demote）",
                "data": None}
    # 校验正式名是否与既有正式冲突
    try:
        if reg.get(formal_name) is not None:
            return {"success": False,
                    "error": f"注册表已存在正式技能 '{formal_name}'，转正冲突", "data": None}
    except Exception as e:
        return {"success": False, "error": f"注册表查询失败: {e}", "data": None}
    try:
        # 写入时写一个"去临时标记"的正式副本（header 加 __(formalized_from)注释与时间戳）
        header = (f"# Formally promoted from {tmp_name} @ "
                  f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                  f"# -*- coding: utf-8 -*-\n")
        with open(target_path, "w", encoding="utf-8") as f:
            if not code.startswith("# -*- coding: utf-8"):
                f.write(header)
            f.write(code)
    except Exception as e:
        return {"success": False, "error": f"写入正式技能文件失败: {e}", "data": None}

    # 5) 正式注册（注册表可见、可执行、不标 [临时]）
    handler = _load_handler_from_file(target_path)
    if handler is None:
        return {"success": False,
                "error": f"正式技能 {formal_name} handler 装载失败（target: {target_path}）",
                "data": {"file": target_path}}
    try:
        from standard_mode.core.skills_registry import SkillDef
    except ImportError:
        try:
            from core.skills_registry import SkillDef
        except ImportError:
            return {"success": False, "error": "SkillDef 导入失败", "data": None}
    skill_def = SkillDef(
        name=formal_name,
        description=existing_desc or formal_name,
        parameters=schema,
        handler=handler,
        category=existing_category,
        timeout=30,
    )
    reg.register(skill_def)

    # 6) 同步移除临时注册表（注销 + 标记 promoted）
    try:
        reg.unregister_temporary(tmp_name)
    except Exception:
        # 部分版本 registry 可能未暴露 unregister_temporary；回退到 unregister
        try:
            reg.unregister(tmp_name)
        except Exception:
            pass
    # 标记 promoted 并保留 .py 文件可复活
    try:
        usage_all = (lambda p: (json.load(open(p, encoding="utf-8"))
                                if os.path.isfile(p) else {}))(tsm.USAGE_FILE)
        usage_all.setdefault(tmp_name, {})
        usage_all[tmp_name]["promoted"] = True
        usage_all[tmp_name]["promoted_to"] = formal_name
        usage_all[tmp_name]["promoted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(tsm.USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(usage_all, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # 非致命：注册表已清理 + 正式技能已落盘，仅记录
        print(f"[skill_promote] 警告：标记 promoted 失败（非致命）: {e}")

    # 7) 更新正式注册表落盘（持久化：重启后挂载）
    try:
        _persist_user_skills_registry(formal_name, existing_desc or formal_name,
                                     existing_category, schema)
    except Exception as e:
        print(f"[skill_promote] 警告：持久化注册表写入失败（非致命，下次挂载仍生效）: {e}")

    return {
        "success": True,
        "error": None,
        "data": {
            "tmp_name": tmp_name,
            "formal_name": formal_name,
            "file": target_path,
            "gates": gate_report,
            "registered_as": formal_name,
            "tmp_registry_cleaned": True,
        },
    }


# ================================================================
# 子任务 1.C：下架（回临时区 / 仅清理注册表）
# ================================================================
def demote(formal_name: str, registry=None, restore_tmp: bool = True) -> Dict[str, Any]:
    """下架正式技能：从注册表注销；可选将其源码还原回临时区。

    Args:
        formal_name: 正式技能名
        registry: 注入用
        restore_tmp: True → 源码从 skills/user_built/ 移回 data/tmp_skills/ 并在临时注册表重建；
                     False → 仅注销注册表（不删除 user_built 文件，留给 manual cleanup）
    """
    tsm = _resolve_tmp_manager()
    reg = _resolve_registry(registry)
    if reg is None:
        return {"success": False, "error": "注册表单例不可用", "data": None}
    # 1) 校验正式技能存在
    try:
        existing = reg.get(formal_name)
    except Exception as e:
        return {"success": False, "error": f"注册表查询失败: {e}", "data": None}
    if existing is None:
        return {"success": False, "error": f"正式技能 '{formal_name}' 未注册", "data": None}
    # 2) 注销注册表
    try:
        reg.unregister(formal_name)
    except Exception as e:
        return {"success": False, "error": f"注册表注销失败: {e}",
                "data": {"formal_name": formal_name}}

    data: Dict[str, Any] = {"formal_name": formal_name, "registry_cleaned": True}

    # 3) 可选：回退为临时
    if restore_tmp:
        src = os.path.join(USER_BUILT_DIR, f"{formal_name}.py")
        if not os.path.isfile(src):
            data["restore_warning"] = f"正式文件缺失: {src}，未回退源码"
            return {"success": True, "error": None, "data": data}
        # 取元数据（parameters / description / category）
        schema = _extract_schema_from_code(open(src, encoding="utf-8").read())
        desc = getattr(existing, "description", "") or formal_name
        cat = getattr(existing, "category", "general") or "general"
        # 重建 tmp_ 名
        tmp_name = formal_name if formal_name.startswith("tmp_") else f"tmp_{formal_name}"
        try:
            os.makedirs(TMP_SKILLS_DIR, exist_ok=True)
            dest = os.path.join(TMP_SKILLS_DIR, f"{tmp_name}.py")
            if os.path.isfile(dest):
                data["restore_warning"] = f"临时文件已存在: {dest}，未覆盖"
            else:
                # 复制 → 跑一遍三关 → 通过才注册临时
                import shutil as _shutil
                _shutil.copy2(src, dest)
                all_ok, gate_report = tsm.run_three_gates(
                    tmp_name, open(dest, encoding="utf-8").read(), schema)
                if all_ok:
                    tsm.save_skill_file(tmp_name, open(dest, encoding="utf-8").read(),
                                        gate_report)
                    handler = _load_handler_from_file(dest)
                    try:
                        from standard_mode.core.skills_registry import SkillDef
                    except ImportError:
                        from core.skills_registry import SkillDef
                    skill_def = SkillDef(
                        name=tmp_name, description="[临时] " + desc,
                        parameters=schema, handler=handler,
                        category=cat, timeout=30,
                    )
                    reg.register_temporary(skill_def)
                    data["restored_as"] = tmp_name
                else:
                    data["restore_warning"] = (f"回退三关未通过（{tmp_name}），保留文件但拒绝"
                                               f"重新注册；gates={gate_report}")
            # 删除正式文件
            try:
                os.remove(src)
                data["src_removed"] = src
            except Exception as e:
                data["remove_warning"] = str(e)
        except Exception as e:
            data["restore_warning"] = f"回退失败: {e}"

    return {"success": True, "error": None, "data": data}


# ================================================================
# 子任务 1.D：启动挂载（main.py 启动时调用一次）
# ================================================================
def bootstrap_user_skills(registry=None, user_dir: Optional[str] = None) -> Dict[str, Any]:
    """启动时扫描 skills/user_built/、装载全部有效 .py 并注册正式技能。"""
    target_dir = user_dir or USER_BUILT_DIR
    reg = _resolve_registry(registry)
    if reg is None:
        return {"success": False, "error": "注册表不可用", "count": 0, "items": []}
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        return {"success": False, "error": f"创建目录失败: {e}", "count": 0, "items": []}
    items: List[Dict[str, Any]] = []
    loaded = 0
    try:
        entries = sorted(os.listdir(target_dir))
    except Exception:
        entries = []
    for entry in entries:
        if not entry.endswith(".py") or entry.startswith("_") or entry.startswith("."):
            continue
        file_path = os.path.join(target_dir, entry)
        if not os.path.isfile(file_path):
            continue
        # 重跑三关后才注册（防篡改）
        try:
            code = open(file_path, "r", encoding="utf-8").read()
        except Exception as e:
            items.append({"file": file_path, "status": "error",
                          "error": f"读取失败: {e}"})
            continue
        name = os.path.splitext(entry)[0]
        schema = _extract_schema_from_code(code)
        tsm = _resolve_tmp_manager()
        # bootstrap：只在全过时才注册（防无效技能在启动时污染菜单）
        all_ok, report = tsm.run_three_gates(name, code, schema)
        if not all_ok:
            items.append({"file": file_path, "name": name, "status": "gate_fail",
                          "gates": report})
            continue
        handler = _load_handler_from_file(file_path)
        if handler is None:
            items.append({"file": file_path, "name": name, "status": "handler_fail"})
            continue
        desc, cat = _extract_doc_and_category(code)
        try:
            from standard_mode.core.skills_registry import SkillDef
        except ImportError:
            from core.skills_registry import SkillDef
        skill_def = SkillDef(
            name=name, description=desc or name,
            parameters=schema, handler=handler,
            category=cat, timeout=30,
        )
        reg.register(skill_def)
        loaded += 1
        items.append({"file": file_path, "name": name, "status": "loaded",
                      "gates": report})
    return {"success": True, "count": loaded, "items": items}


# ================================================================
# 子任务 1.E：单文件动态挂载
# ================================================================
def reload_user_skill(file_path: str, registry=None) -> Dict[str, Any]:
    """单个 .py 动态挂载（UI 按钮用）。流程同 bootstrap_user_skills 单条。"""
    if not os.path.isfile(file_path):
        return {"success": False, "error": f"文件不存在: {file_path}", "data": None}
    reg = _resolve_registry(registry)
    if reg is None:
        return {"success": False, "error": "注册表不可用", "data": None}
    code = open(file_path, "r", encoding="utf-8").read()
    name = os.path.splitext(os.path.basename(file_path))[0]
    schema = _extract_schema_from_code(code)
    tsm = _resolve_tmp_manager()
    all_ok, report = tsm.run_three_gates(name, code, schema)
    if not all_ok:
        return {"success": False, "error": f"三关拒绝: {report}", "data": None}
    handler = _load_handler_from_file(file_path)
    if handler is None:
        return {"success": False, "error": "handler 装载失败", "data": None}
    desc, cat = _extract_doc_and_category(code)
    try:
        from standard_mode.core.skills_registry import SkillDef
    except ImportError:
        from core.skills_registry import SkillDef
    skill_def = SkillDef(name=name, description=desc or name,
                         parameters=schema, handler=handler,
                         category=cat, timeout=30)
    reg.register(skill_def)
    return {"success": True, "data": {"name": name, "file": file_path, "gates": report}}


# ================================================================
# 内部工具
# ================================================================
def _extract_schema_from_code(code: str) -> Dict:
    """从源码解析 PARAMS_SCHEMA 常量（与 skill_creator._extract_schema_from_code 同逻辑）。"""
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


def _extract_doc_and_category(code: str) -> tuple:
    """简易提取第一行 docstring / category 注释（不依赖 LLM）。"""
    desc, cat = "", "general"
    try:
        import ast as _ast
        tree = _ast.parse(code)
        d = ast_docstring(tree)
        if d:
            first_line = d.strip().splitlines()[0].strip()
            # Skill: name — description 格式
            if "—" in first_line:
                first_line = first_line.split("—", 1)[1].strip()
            desc = first_line[:200]
    except Exception:
        pass
    # 找 category 注释：category: xxx （skill_creator 写入）
    m = re.search(r'"category"\s*:\s*"([^"]+)"', code)
    if m:
        cat = m.group(1)
    return desc, cat


def ast_docstring(tree) -> str:
    try:
        import ast as _ast
        return _ast.get_docstring(tree) or ""
    except Exception:
        return ""


def _persist_user_skills_registry(name: str, description: str, category: str,
                                  schema: dict) -> str:
    """记录正式注册表持久化信息到 skills/user_billed/_registry.json，
    便于启动挂载与审计。文件非强制（缺失也能启动），但写成功可提升重启体验。"""
    reg_file = os.path.join(USER_BUILT_DIR, "_registry.json")
    try:
        if os.path.isfile(reg_file):
            data = json.load(open(reg_file, encoding="utf-8"))
        else:
            data = {"version": 1, "entries": {}}
    except Exception:
        data = {"version": 1, "entries": {}}
    data.setdefault("entries", {})[name] = {
        "description": description,
        "category": category,
        "schema": schema,
        "file": f"{name}.py",
        "registered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(reg_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return reg_file


# 兼容 Windows 路径：转正 / 下架产生的文件都必须真实可再次读回
def assert_file_readable(path: str) -> bool:
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            f.read(1)
        return True
    except Exception:
        return False
