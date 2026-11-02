# -*- coding: utf-8 -*-
"""
Skill: skill_creator — Skill 创建工具（394B-1 全链路改造）
==========================================================
原版只生成代码模板字符串；394B-1 起为"临时 skill 全链路"入口：

    action=create   生成(tmp_ 命名空间) → 落盘 data/tmp_skills/ →
                    三关沙箱(AST编译/schema bind 干跑/子进程安全直调) →
                    全过才 register_temporary()（任一失败拒绝注册，代码保留排查）
    action=revive   从 data/tmp_skills/ 复活临时技能（重过三关）
    action=cleanup  会话清理：注销全部临时技能（代码保留可复活）
    action=list_temp  临时技能清单 + 使用计数
    action=formalize  转正（394C-1，需提名后用户确认）：去 tmp_ 前缀 →
                      正式模块落盘 core/skills/ → 注册正式技能
    action=decline    拒绝转正提名（保留临时态，不再骚扰）

生成代码为自包含模块：本地定义 SkillResult 兼容类（鸭子类型，
registry.execute 按 __class__.__name__ 接收），不依赖导入路径。
"""

import json
import os
import textwrap
import time
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

try:  # 包上下文（core.skills.skill_creator）优先相对导入
    from . import tmp_skill_manager as _tsm
except ImportError:
    from core.skills import tmp_skill_manager as _tsm

METADATA = {
    "name": "skill_creator",
    "description": ("Skill 创建工具：临时技能全链路——生成(tmp_命名空间)→三关沙箱验证"
                    "(AST编译/schema自洽/子进程直调)→临时注册(会话级)；支持复活/清理/转正。"),
    "category": "system",
    "version": "2.0.0",
}


# ============================================================
# 代码生成（B1.1：tmp_ 命名空间 + 自包含模板）
# ============================================================

_CODE_TEMPLATE = '''# -*- coding: utf-8 -*-
"""
Skill: __SKILL_NAME__ — __SKILL_DESC__
由 skill_creator 自动生成（394B-1 临时技能全链路）。
生成时间: __GEN_TIME__
"""

import json
import os
import sys
import time
from typing import Dict, Any


class SkillResult:
    """本地最小 SkillResult（与 skills_registry.SkillResult 鸭子类型兼容：
    registry.execute 按 __class__.__name__ 识别）。"""

    def __init__(self, success: bool, output: str = "", error: str = "", data=None):
        self.success = success
        self.output = output
        self.error = error
        self.data = data if data is not None else {}


PARAMS_SCHEMA = __SCHEMA_JSON__


def execute(__FUNC_PARAMS__) -> SkillResult:
    """执行 __SKILL_NAME__（作用域内可用: json/os/sys/time/SkillResult）"""
__HANDLER_BODY__


def get_metadata() -> Dict[str, Any]:
    return {"name": "__SKILL_NAME__", "description": __DESC_JSON__,
            "category": "__CATEGORY__", "version": "1.0.0", "temporary": True}


if __name__ == "__main__":  # 三关第三关 selftest 入口（子进程直调）
    import json as _json
    try:
        _dummy = json.loads(__DUMMY_JSON__)
        _r = execute(**_dummy)
        print(_json.dumps({"ok": bool(getattr(_r, "success", False)),
                           "error": str(getattr(_r, "error", ""))[:200]},
                          ensure_ascii=False))
    except Exception as _e:
        print(_json.dumps({"ok": False, "error": str(_e)[:200]}, ensure_ascii=False))
'''


def _build_code(skill_name: str, description: str, category: str,
                params_schema: Dict, params_list: list, handler_logic: str) -> str:
    """按模板生成自包含临时技能代码。"""
    func_params = ", ".join(
        f'{p.get("name", "param")}: str = ""' for p in params_list)
    # 前置校验后 handler_logic 必非空（_do_create 已把关）
    body = textwrap.indent(handler_logic.rstrip(), "    ")
    dummy = _tsm.build_dummy_args(params_schema)
    code = (_CODE_TEMPLATE
            .replace("__SKILL_NAME__", skill_name)
            .replace("__SKILL_DESC__", description.replace('"""', "'''"))
            .replace("__GEN_TIME__", time.strftime("%Y-%m-%d %H:%M:%S"))
            .replace("__SCHEMA_JSON__", json.dumps(params_schema, ensure_ascii=False, indent=4))
            .replace("__FUNC_PARAMS__", func_params)
            .replace("__HANDLER_BODY__", body)
            .replace("__CATEGORY__", category)
            .replace("__DESC_JSON__", json.dumps(description, ensure_ascii=False))
            .replace("__DUMMY_JSON__", json.dumps(json.dumps(dummy, ensure_ascii=False))))
    return code


def _parse_params(parameters) -> list:
    if isinstance(parameters, str):
        try:
            parsed = json.loads(parameters or "[]")
        except Exception:
            return []
    else:
        parsed = parameters or []
    return parsed if isinstance(parsed, list) else []


def _params_list_to_schema(params_list: list) -> Dict:
    """与旧版兼容的参数列表 → JSON Schema。"""
    properties, required = {}, []
    for p in params_list:
        name = p.get("name", "param")
        ptype = p.get("type", "string")
        prop = {"type": ptype, "description": p.get("description", name)}
        if ptype == "string" and p.get("enum"):
            prop["enum"] = p["enum"]
        if p.get("default") is not None:
            prop["default"] = p["default"]
        properties[name] = prop
        if p.get("required", False):
            required.append(name)
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


# ============================================================
# 动作实现
# ============================================================

def _do_create(skill_name, description, category, parameters, handler_logic,
               registry) -> SkillResult:
    if not (handler_logic or "").strip():
        return SkillResult(
            success=False,
            error="handler_logic 为空——394B-1 要求真实业务逻辑（Python 函数体，"
                  "作用域含 json/os/sys/time/SkillResult，须 return SkillResult(...)）；"
                  "空壳模板不再生成（394C-1 增补：防呆从 gate3 语义前移到创建前置校验）")
    norm, err = _tsm.normalize_tmp_name(skill_name)
    if not norm:
        return SkillResult(success=False, error=err)
    params_list = _parse_params(parameters)
    params_schema = _params_list_to_schema(params_list)
    code = _build_code(norm, description or norm, category or "general",
                       params_schema, params_list, handler_logic)

    all_ok, report = _tsm.run_three_gates(norm, code, params_schema)
    if not all_ok:
        # 拒绝注册；代码不落正式文件，仅保留逐关报告供排查
        failed = [k for k, v in report.items() if not v["pass"]]
        detail = "; ".join(f"{k}: {v['msg']}" for k, v in report.items())
        return SkillResult(
            success=False,
            error=f"[394B-1 三关沙箱] {norm} 验证失败({'/'.join(failed)})，已拒绝注册。{detail}",
            data={"gates": report, "registered": False},
        )

    file_path = _tsm.save_skill_file(norm, code, report)
    skill = SkillDef(
        name=norm,
        description=description or norm,
        parameters=params_schema,
        handler=None,  # 占位，下一行立即装载真实 handler
        category="temporary",
        timeout=30,
    )
    skill.handler = _load_handler_from_file(file_path, norm)
    if skill.handler is None:
        return SkillResult(success=False,
                           error=f"临时技能模块装载失败: {file_path}",
                           data={"gates": report})
    ok, msg = registry.register_temporary(skill)
    if not ok:
        return SkillResult(success=False, error=msg, data={"gates": report})
    return SkillResult(
        success=True,
        output=(f"临时技能 {norm} 全链路完成：三关全过 → 已临时注册。\n"
                f"  文件: {file_path}\n"
                f"  三关: " + "; ".join(f"{k}={v['msg']}" for k, v in report.items()) +
                f"\n  生命周期: 会话结束注销（代码保留可复活）；成功≥3次触发转正提名。"),
        data={"gates": report, "registered": True, "name": norm,
              "file": file_path, "schema": params_schema},
    )


def _load_handler_from_file(file_path: str, mod_name: str):
    """从落盘文件装载 execute handler（进程内直调用）。"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"tmp_skill_{mod_name}", file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, "execute", None)
        return fn if callable(fn) else None
    except Exception:
        return None


def _do_revive(skill_name, registry) -> SkillResult:
    norm, err = _tsm.normalize_tmp_name(skill_name)
    if not norm:
        return SkillResult(success=False, error=err)
    path = _tsm.get_skill_file(norm)
    if not path:
        return SkillResult(success=False,
                           error=f"data/tmp_skills/ 无 {norm}.py，无法复活")
    code = open(path, "r", encoding="utf-8").read()
    old_meta = {}
    try:
        old_meta = (json.load(open(_tsm.INDEX_FILE, encoding="utf-8"))
                    .get(norm, {}) or {})
    except Exception:
        pass
    schema = old_meta.get("schema") or _extract_schema_from_code(code)
    all_ok, report = _tsm.run_three_gates(norm, code, schema)
    if not all_ok:
        return SkillResult(success=False,
                           error=f"[复活验证] 三关未全过，拒绝复活: {report}",
                           data={"gates": report})
    skill = SkillDef(name=norm, description=old_meta.get("description", norm),
                     parameters=schema, handler=None,
                     category="temporary", timeout=30)
    skill.handler = _load_handler_from_file(path, norm)
    ok, msg = registry.register_temporary(skill)
    return SkillResult(success=ok, output=msg if ok else msg,
                       error=None if ok else msg,
                       data={"gates": report, "revived": ok})


def _extract_schema_from_code(code: str) -> Dict:
    """复活兜底：从代码里取 PARAMS_SCHEMA 常量。"""
    import ast as _ast
    try:
        tree = _ast.parse(code)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Assign):
                for t in node.targets:
                    if getattr(t, "id", "") == "PARAMS_SCHEMA":
                        return _ast.literal_eval(node.value)
    except Exception:
        pass
    return {"type": "object", "properties": {}}


def _do_formalize(skill_name, registry) -> SkillResult:
    """394C-1: 转正（本动作即"用户确认"落地入口，agent 代为调用）。"""
    norm, err = _tsm.normalize_tmp_name(skill_name)
    if not norm:
        return SkillResult(success=False, error=err)
    usage = _tsm.get_usage(norm)
    if not usage.get("promoted") and not usage.get("nominated") \
            and int(usage.get("success", 0)) < _tsm.PROMOTION_THRESHOLD:
        return SkillResult(
            success=False,
            error=(f"{norm} 未达转正条件（成功 {usage.get('success', 0)} 次 < "
                   f"{_tsm.PROMOTION_THRESHOLD} 且无提名），请先用够再确认转正。"))
    path = _tsm.get_skill_file(norm)
    if not path:
        return SkillResult(success=False, error=f"源码缺失: {norm}.py")
    formal_name = norm[len("tmp_"):]
    if registry.get(formal_name) is not None:
        return SkillResult(success=False,
                           error=f"正式技能 '{formal_name}' 已存在，转正冲突")
    code = open(path, "r", encoding="utf-8").read()
    schema = _extract_schema_from_code(code)
    formal_code = _build_formal_module(norm, formal_name, code)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            f"{formal_name}.py")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(formal_code)
    # 追加进 SKILL_MODULES（锚点注释行之后，重启后自动注册）
    _append_to_skill_modules(formal_name)
    skill = SkillDef(name=formal_name,
                     description=f"{_first_line_doc(formal_code)}（394C-1 自 {norm} 转正）",
                     parameters=schema, handler=None,
                     category="general", timeout=30)
    skill.handler = _load_handler_from_file(out_path, formal_name)
    # 394C-1 schema 补全：386B-4 惯例——补 argcheck_example（dummy 参数示例，模型可见）
    try:
        from core.skills import tmp_skill_manager as _tsm2
        skill.argcheck_example = _tsm2.build_dummy_args(schema)
    except Exception:
        pass
    registry.register(skill)
    # 转正闭环：临时态注销（正式技能接管；代码与 usage 记录保留审计）
    registry.unregister_temporary(norm)
    _tsm.mark_promoted(norm, formal_name)
    # 394C-1: 进评测候选池登记（15 题评测候选池的消费清单）
    try:
        with open(os.path.join(_tsm.TMP_DIR, "promotion_log.jsonl"),
                  "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "tmp_name": norm, "formal_name": formal_name,
                "success_count": int(usage.get("success", 0)),
                "eval_pool": "15题评测候选池", "status": "promoted",
            }, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[skill_creator] 评测候选池登记失败(忽略): {e}")
    return SkillResult(
        success=True,
        output=(f"临时技能 {norm} 已转正为正式技能 '{formal_name}'："
                f"模块落盘 {out_path}，SKILL_MODULES 已追加，正式注册完成。"
                f"评测候选池登记见 data/tmp_skills/promotion_log.jsonl。"),
        data={"formal_name": formal_name, "file": out_path})


def _build_formal_module(old_name: str, formal_name: str, code: str) -> str:
    header = (
        f"# -*- coding: utf-8 -*-\n"
        f'"""\nSkill: {formal_name} — 由临时技能 {old_name} 转正（394C-1）。\n'
        f"转正时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f'"""\n\n'
        f"import json, os, sys, time\nfrom typing import Dict, Any\n\n"
        f"import sys as _sys\n"
        f"_sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))\n"
        f"from skills_registry import SkillDef, SkillResult\n\n"
    )
    body = code
    # 去掉生成头的本地 SkillResult 类定义与 selftest 主块，换成正式导入
    start = body.find("class SkillResult:")
    if start >= 0:
        end = body.find("PARAMS_SCHEMA", start)
        body = body[end:] if end > start else body
    main_idx = body.find('if __name__ == "__main__":')
    if main_idx > 0:
        body = body[:main_idx]
    # 生成版的 get_metadata 一并裁掉（下方追加正式版，防重复定义）
    meta_idx = body.find("\ndef get_metadata")
    if meta_idx > 0:
        body = body[:meta_idx]
    meta_fn = (
        f"\n\ndef get_metadata() -> Dict[str, Any]:\n"
        f'    return {{"name": "{formal_name}", "category": "general", '
        f'"version": "1.0.0", "origin": "{old_name}"}}\n\n\n'
        f"def register(registry) -> None:\n"
        f"    registry.register(SkillDef(\n"
        f'        name="{formal_name}",\n'
        f'        description="{formal_name}（394C-1 自 {old_name} 转正）",\n'
        f"        parameters=__SCHEMA__,\n"
        f"        handler=execute,\n"
        f'        category="general",\n    ))\n'
    ).replace("__SCHEMA__", _extract_schema_literal(code))
    return header + body.rstrip() + meta_fn


def _extract_schema_literal(code: str) -> str:
    schema = _extract_schema_from_code(code)
    return json.dumps(schema, ensure_ascii=False, indent=8)


def _first_line_doc(code: str) -> str:
    for line in code.splitlines():
        line = line.strip().strip('"')
        if line.startswith("Skill:") and "—" in line:
            return line.split("—", 1)[1].strip()
    return "临时技能转正"


def _append_to_skill_modules(formal_name: str):
    """在 skills/__init__.py 的转正追加区插入模块名（重启后自动注册）。"""
    init_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "__init__.py")
    try:
        with open(init_path, "r", encoding="utf-8") as f:
            content = f.read()
        anchor = "# 394C-1 转正技能追加区"
        if anchor not in content:
            print("[skill_creator] 警告: __init__.py 无转正追加区锚点，跳过清单更新")
            return
        if f'"{formal_name}"' in content:
            return
        content = content.replace(
            anchor,
            anchor + f'\n    "{formal_name}",  # 394C-1 转正 {time.strftime("%Y-%m-%d")}',
            1)
        with open(init_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[skill_creator] SKILL_MODULES 追加失败(忽略): {e}")


def _do_list_temp(registry) -> SkillResult:
    names = registry.list_temporary()
    persisted = _tsm.list_persisted()
    usage = _tsm.get_usage()
    lines = [f"注册中临时技能({len(names)}): {', '.join(names) or '无'}",
             f"落盘可复活({len(persisted)}): {', '.join(persisted) or '无'}"]
    for n in names:
        u = usage.get(n, {})
        lines.append(f"  {n}: 成功{u.get('success', 0)} 失败{u.get('fail', 0)}"
                     f"{' [已提名]' if u.get('nominated') else ''}")
    return SkillResult(success=True, output="\n".join(lines),
                       data={"registered": names, "persisted": persisted})


# ============================================================
# 注册入口
# ============================================================

def _get_canonical_registry():
    """★394B-1: 取引擎同源注册表单例。

    引擎侧（engine_manager L4941）走 standard_mode.core.skills_registry
    包路径单例；本模块顶层 `from skills_registry import ...` 是同文件的
    顶层模块副本（本仓既有的双模块名加载模式）。若直接用顶层单例会把
    临时技能注册进引擎看不见的第二个 registry——必须规范路径优先。
    """
    try:
        from standard_mode.core.skills_registry import get_skills_registry
        return get_skills_registry()
    except ImportError:
        try:
            from core.skills_registry import get_skills_registry
            return get_skills_registry()
        except ImportError:
            from skills_registry import get_skills_registry
            return get_skills_registry()


def execute(action: str = "create", skill_name: str = "", description: str = "",
            category: str = "general", parameters: str = "[]",
            handler_logic: str = "") -> SkillResult:
    """skill_creator 主入口（394B-1 多动作）"""
    registry = _get_canonical_registry()

    action = (action or "create").strip().lower()
    try:
        if action == "create":
            if not skill_name:
                return SkillResult(success=False, error="skill_name 参数为空")
            return _do_create(skill_name, description, category, parameters,
                              handler_logic, registry)
        if action == "revive":
            return _do_revive(skill_name, registry)
        if action == "cleanup":
            cleaned = registry.cleanup_temporary()
            return SkillResult(success=True,
                               output=f"会话清理完成，注销 {len(cleaned)} 个临时技能: "
                                      f"{', '.join(cleaned) or '无'}"
                                      f"（代码保留 data/tmp_skills/ 可复活）",
                               data={"cleaned": cleaned})
        if action == "list_temp":
            return _do_list_temp(registry)
        if action == "formalize":
            return _do_formalize(skill_name, registry)
        if action == "decline":
            _tsm.mark_declined(skill_name)
            return SkillResult(success=True,
                               output=f"{skill_name} 已标记拒绝转正：保留临时态，不再提名。")
        return SkillResult(success=False,
                           error=f"未知 action='{action}'（支持 create/revive/cleanup/"
                                 f"list_temp/formalize/decline）")
    except Exception as e:
        return SkillResult(success=False, error=f"skill_creator 异常: {e}",
                           output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="skill_creator",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "description": "动作: create(默认)/revive/cleanup/list_temp/formalize/decline",
                           "enum": ["create", "revive", "cleanup", "list_temp",
                                    "formalize", "decline"],
                           "default": "create"},
                "skill_name": {"type": "string",
                               "description": "技能名（create 自动规范化为 tmp_<领域>_<功能>）"},
                "description": {"type": "string", "description": "技能描述"},
                "category": {"type": "string", "description": "分类", "default": "general"},
                "parameters": {"type": "string",
                               "description": 'JSON 参数列表 [{"name":"x","type":"string","description":"参数x","required":true}]',
                               "default": "[]"},
                "handler_logic": {"type": "string",
                                  "description": "handler Python 逻辑源码（函数体缩进由工具处理；"
                                                 "作用域含 json/os/sys/time/SkillResult，必须 return SkillResult(...)）"},
            },
            "required": ["skill_name"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=60,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
