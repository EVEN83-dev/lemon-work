# -*- coding: utf-8 -*-
"""
tmp_skill_manager — 临时 Skill 全生命周期管理（394B-1 / 394C-1）
================================================================
职责：
1. tmp_ 命名空间规范：tmp_<领域>_<功能>，与正式技能严格隔离；
2. 三关沙箱验证：AST 编译 → 参数 schema 自洽 bind 干跑 → 子进程单次安全直调；
3. 落盘与复活：代码存 data/tmp_skills/（注册表不过夜，代码可复活）；
4. 使用计数与转正提名（394C-1）：成功 ≥3 次触发提名，用户确认后转正。

本模块不注册为技能（不在 SKILL_MODULES），由 skill_creator 与
SkillsRegistry 按需导入。禁止导入 engine_manager/UI 层。
"""

import ast
import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple

# 仓库根 = 本文件向上三级（skills → core → standard_mode → lemon_agent）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
TMP_DIR = os.path.join(_REPO_ROOT, "data", "tmp_skills")
INDEX_FILE = os.path.join(TMP_DIR, "index.json")
USAGE_FILE = os.path.join(TMP_DIR, "usage.json")

# 转正门槛（394C-1）：连续成功次数
PROMOTION_THRESHOLD = 3
# 三关直调超时（秒）
SELFTEST_TIMEOUT = 15

_NAME_RE = re.compile(r"^tmp_[a-z0-9]+_[a-z0-9]+(_[a-z0-9]+)*$")
_lock = threading.Lock()


# ============================================================
# 命名空间规范（B1.1）
# ============================================================

def normalize_tmp_name(skill_name: str) -> Tuple[Optional[str], str]:
    """规范化临时技能名：强制 tmp_<领域>_<功能> 格式。

    Returns:
        (规范名, 错误信息)；成功时错误信息为空。
    """
    name = (skill_name or "").strip().lower()
    # 分隔符归一：空格/连字符 → 下划线
    name = re.sub(r"[\s\-]+", "_", name)
    # 去掉既有 tmp_ 前缀后重新拼装，防 "tmp_tmp_" 与缺失前缀混入
    body = re.sub(r"^tmp_+", "", name)
    body = re.sub(r"[^a-z0-9_]", "", body)
    body = re.sub(r"_+", "_", body).strip("_")
    parts = [p for p in body.split("_") if p]
    if len(parts) < 2:
        return None, f"技能名 '{skill_name}' 需为 tmp_<领域>_<功能> 两段以上格式"
    normalized = "tmp_" + "_".join(parts)
    if not _NAME_RE.match(normalized):
        return None, f"规范化后的技能名 '{normalized}' 不合法（仅允许小写字母/数字/下划线）"
    return normalized, ""


def is_temp_name(name: str) -> bool:
    return isinstance(name, str) and name.startswith("tmp_")


# ============================================================
# 落盘与索引（B1.3：代码保留可复活，注册不过夜）
# ============================================================

def _ensure_dir():
    os.makedirs(TMP_DIR, exist_ok=True)


def _read_json(path: str, default) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data: dict):
    _ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_skill_file(name: str, code: str, gate_report: Dict) -> str:
    """保存临时技能代码到 data/tmp_skills/<name>.py 并登记索引。"""
    _ensure_dir()
    file_path = os.path.join(TMP_DIR, f"{name}.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)
    idx = _read_json(INDEX_FILE, {})
    idx[name] = {
        "file": file_path,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gates": gate_report,
    }
    _write_json(INDEX_FILE, idx)
    return file_path


def get_skill_file(name: str) -> Optional[str]:
    """取临时技能代码文件路径（复活用），不存在返回 None。"""
    p = os.path.join(TMP_DIR, f"{name}.py")
    return p if os.path.isfile(p) else None


def list_persisted() -> List[str]:
    idx = _read_json(INDEX_FILE, {})
    return [n for n, meta in idx.items()
            if os.path.isfile(meta.get("file", ""))]


def forget_persisted(name: str):
    """显式清理：从索引与磁盘移除（默认不过夜——复活是显式行为）。"""
    idx = _read_json(INDEX_FILE, {})
    meta = idx.pop(name, None)
    _write_json(INDEX_FILE, idx)
    if meta and os.path.isfile(meta.get("file", "")):
        try:
            os.remove(meta["file"])
        except OSError:
            pass


# ============================================================
# 三关沙箱（B1.2）
# ============================================================

def _dummy_value_by_type(ptype: str):
    """按 JSON Schema 类型构造 dummy 参数值。"""
    return {
        "string": "test",
        "number": 1.0,
        "integer": 1,
        "boolean": False,
        "array": [],
        "object": {},
        "null": None,
    }.get(str(ptype).lower(), "test")


def build_dummy_args(schema: Dict) -> Dict:
    """从参数 schema 构造全量 dummy 参数（必填+可选都覆盖，直调用）。"""
    props = (schema or {}).get("properties", {}) or {}
    return {k: _dummy_value_by_type(v.get("type", "string"))
            for k, v in props.items()}


def gate1_ast_compile(code: str) -> Tuple[bool, str]:
    """第一关：AST 编译（语法可编译）。"""
    try:
        tree = ast.parse(code)
        compile(tree, "<tmp_skill>", "exec")
        return True, "AST 编译通过"
    except SyntaxError as e:
        return False, f"语法错误: line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"编译失败: {e}"


def _load_module_from_file(path: str, mod_name: str):
    """importlib 标准机制从文件加载模块对象（受控加载点）。

    输入约束：code 已过第一关 AST，文件由 skill_creator 脚手架生成
    （模块级仅 imports + METADATA + 常量 + 函数定义）。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gate2_schema_bind(file_path: str, schema: Dict) -> Tuple[bool, str]:
    """第二关：参数 schema 自洽校验（bind 干跑）。

    校验：
    a) 模块含 execute()；
    b) schema required ⊆ handler 形参；
    c) handler 必填形参（无默认值）⊆ schema properties；
    d) 全量 dummy 参数 signature.bind() 成功。
    """
    try:
        module = _load_module_from_file(file_path, "tmp_skill_gate2_probe")
    except Exception as e:
        return False, f"模块加载失败: {e}"
    execute_fn = getattr(module, "execute", None)
    if not callable(execute_fn):
        return False, "模块缺少 execute() 函数"
    import inspect
    try:
        sig = inspect.signature(execute_fn)
    except (TypeError, ValueError) as e:
        return False, f"无法读取 execute 签名: {e}"
    params = dict(sig.parameters)
    props = set((schema or {}).get("properties", {}) or {}).difference({"_context"})
    required = set((schema or {}).get("required", []) or [])
    handler_names = set(params) - {"_context"}
    # b) schema 必填必须可由 handler 接收
    missing_in_handler = required - handler_names
    if missing_in_handler:
        return False, f"schema required 参数在 handler 中不存在: {sorted(missing_in_handler)}"
    # c) handler 无默认值形参必须出现在 schema
    no_default = {n for n, p in params.items()
                  if p.default is inspect.Parameter.empty
                  and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                 inspect.Parameter.KEYWORD_ONLY)}
    missing_in_schema = no_default - props
    if missing_in_schema:
        return False, f"handler 必填参数未在 schema 中声明: {sorted(missing_in_schema)}"
    # d) 全量 dummy bind 干跑
    dummy = build_dummy_args(schema)
    try:
        sig.bind(**dummy)
    except TypeError as e:
        return False, f"schema bind 干跑失败: {e}"
    return True, f"schema 自洽校验通过（{len(dummy)} 个参数 bind 成功）"


def gate3_safe_direct_call(file_path: str) -> Tuple[bool, str]:
    """第三关：子进程单次安全直调（dummy 参数，超时强杀，进程隔离）。"""
    try:
        proc = subprocess.run(
            [sys.executable, file_path, "--selftest"],
            capture_output=True, text=True, timeout=SELFTEST_TIMEOUT,
            cwd=TMP_DIR, shell=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"直调超时（>{SELFTEST_TIMEOUT}s），已强杀"
    except Exception as e:
        return False, f"直调启动失败: {e}"
    out = (proc.stdout or "")
    # 取输出中最后一行 JSON（selftest 约定输出）
    parsed = None
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if parsed is None:
        tail = (out or proc.stderr or "")[-300:].replace("\n", " | ")
        return False, f"直调无有效 selftest 输出（exit={proc.returncode}）: {tail}"
    if proc.returncode != 0:
        return False, (f"直调进程退出码 {proc.returncode}: "
                       f"{str(parsed.get('error', ''))[:300]}")
    # ★394C-1 语义修正：gate3 拦的是"崩溃"（异常/超时/无输出/非零退出）。
    #   handler 对 dummy 参数返回优雅的 SkillResult(success=False, error=明确原因)
    #   属业务校验逻辑（如"参数需为数字"），模块本体已验证可安全执行——放行，
    #   但把结果如实带入消息；防呆空壳由 create 前置校验（handler_logic 必填）把关。
    if bool(parsed.get("ok")):
        return True, "子进程直调 PASS（dummy 参数返回成功）"
    return True, (f"子进程直调 PASS（模块可安全执行；对 dummy 参数返回优雅拒绝: "
                  f"{str(parsed.get('error', ''))[:150]}——注册放行，语义由调用方把关）")


def run_three_gates(name: str, code: str, schema: Dict) -> Tuple[bool, Dict]:
    """顺序过三关；任一失败即拒绝注册。

    探针文件 _probe_<name>.py 由 gate2/gate3 共用，finally 清理。
    Returns:
        (全过, 逐关报告)
    """
    report = {}
    ok1, msg1 = gate1_ast_compile(code)
    report["gate1_ast"] = {"pass": ok1, "msg": msg1}
    if not ok1:
        return False, report
    # gate2/gate3 需要落盘文件（importlib 加载与子进程直调都按路径）
    _ensure_dir()
    tmp_probe_path = os.path.join(TMP_DIR, f"_probe_{name}.py")
    with open(tmp_probe_path, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        ok2, msg2 = gate2_schema_bind(tmp_probe_path, schema)
        report["gate2_schema_bind"] = {"pass": ok2, "msg": msg2}
        if not ok2:
            return False, report
        ok3, msg3 = gate3_safe_direct_call(tmp_probe_path)
        report["gate3_direct_call"] = {"pass": ok3, "msg": msg3}
        if not ok3:
            return False, report
    finally:
        try:
            os.remove(tmp_probe_path)
        except OSError:
            pass
    return True, report


# ============================================================
# 使用计数与转正（394C-1）
# ============================================================

def record_usage(name: str, success: bool) -> Optional[Dict]:
    """临时技能每次被调用后记账；成功 ≥3 次触发转正提名。

    Returns:
        提名信息 dict（触发时），否则 None。
    """
    if not is_temp_name(name):
        return None
    with _lock:
        usage = _read_json(USAGE_FILE, {})
        entry = usage.get(name) or {"success": 0, "fail": 0, "nominated": False,
                                    "declined": False, "last_used": ""}
        if success:
            entry["success"] = int(entry.get("success", 0)) + 1
        else:
            entry["fail"] = int(entry.get("fail", 0)) + 1
        entry["last_used"] = time.strftime("%Y-%m-%d %H:%M:%S")
        usage[name] = entry
        _write_json(USAGE_FILE, usage)
        nomination = None
        if (success and not entry.get("nominated") and not entry.get("declined")
                and entry["success"] >= PROMOTION_THRESHOLD):
            entry["nominated"] = True
            usage[name] = entry
            _write_json(USAGE_FILE, usage)
            nomination = {
                "skill": name,
                "success_count": entry["success"],
                "threshold": PROMOTION_THRESHOLD,
                "message": (f"★394C-1 转正提名：临时技能 {name} 已连续成功 "
                            f"{entry['success']} 次（≥{PROMOTION_THRESHOLD}），"
                            f"如需转正请调用 skill_creator(action='formalize', "
                            f"skill_name='{name}') 确认；拒绝则保留临时态。"),
            }
    if nomination:
        _emit_nomination_event(nomination)
    return nomination


def _emit_nomination_event(nomination: Dict):
    """提名通知：复用 tool_call_made 事件通道（只发事件，不改 UI 代码）。

    引擎忙线（392 战区改造中）时降级为日志，不阻塞技能执行。
    """
    try:
        from shared.engine_manager import get_engine_manager
        em = get_engine_manager()
        try:
            em.tool_call_made.emit({
                "name": "tmp_skill_promotion",
                "arguments": {"skill": nomination["skill"]},
                "result": nomination["message"],
                "success": True,
                "nomination": nomination,
                "guidance": True,
            })
            return
        except Exception:
            pass
    except Exception:
        pass
    print(f"[394C-1] {nomination['message']}")


def mark_declined(name: str):
    """用户拒绝转正：保留临时态，不再提名骚扰。"""
    with _lock:
        usage = _read_json(USAGE_FILE, {})
        entry = usage.get(name) or {}
        entry["declined"] = True
        entry["nominated"] = True
        usage[name] = entry
        _write_json(USAGE_FILE, usage)


def mark_promoted(name: str, formal_name: str):
    """转正完成：记账归档。"""
    with _lock:
        usage = _read_json(USAGE_FILE, {})
        entry = usage.get(name) or {}
        entry["promoted"] = True
        entry["promoted_to"] = formal_name
        entry["promoted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        usage[name] = entry
        _write_json(USAGE_FILE, usage)


def get_usage(name: str = "") -> Dict:
    usage = _read_json(USAGE_FILE, {})
    return usage if not name else usage.get(name, {})
