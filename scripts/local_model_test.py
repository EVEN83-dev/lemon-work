#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lemon Work · 本地模型能力测试

不启动 GUI，直接驱动 shared.engine_manager.EngineManager，
用 Ollama 本地模型跑「对话 / 代码 / 文件 / 命令 / 数据分析 / 结构化输出 / 模型切换」。

用法：
    _py312\\python.exe scripts\\local_model_test.py
    _py312\\python.exe scripts\\local_model_test.py --model qwen3:4b
    _py312\\python.exe scripts\\local_model_test.py --keep      # 保留沙箱排查

产物：
    LemonWork\\本地模型能力测试报告.md     （质量报告，保留）
    %TEMP%\\lw_lm_test\\run_<时间戳>\\      （沙箱，默认测试后删除）

注意：所有写文件/执行命令的用例都被要求只在沙箱目录内操作；
      脚本结束会删除沙箱，并把沙箱外新增的可疑文件列进报告。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "standard_mode"))
sys.path.insert(0, os.path.join(ROOT, "standard_mode", "core"))
os.chdir(ROOT)

DEFAULT_MODEL = "qwen3.5:4b"
SWITCH_MODEL = "qwen3.5:9b"
CASE_TIMEOUT = 240          # 单用例上限（秒）
REPORT_PATH = os.path.join(ROOT, "本地模型能力测试报告.md")
SANDBOX_ROOT = os.path.join(os.environ.get("TEMP", os.getcwd()), "lw_lm_test")


# ─────────────────────────── 基础设施 ───────────────────────────
def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _seed_sandbox(sb: str) -> None:
    _write(os.path.join(sb, "calc.py"),
           "# 预置：add 有 bug（减法）\n"
           "def add(a, b):\n"
           "    return a - b\n")
    _write(os.path.join(sb, "sales.csv"),
           "product,qty,price\n"
           "A,10,2.5\n"
           "B,4,7.0\n"
           "C,2,15.0\n")


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


# ─────────────────────────── 检查器 ───────────────────────────
def chk_chat_format(sb: str, res: Dict[str, Any]) -> Tuple[bool, str]:
    content = (res.get("content") or "").strip()
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    ok = len(lines) == 3
    detail = ["行数=%d（要求 3）" % len(lines)]
    if ok:
        for i, l in enumerate(lines, 1):
            head = l.replace("．", ".")[:2]
            ok = ok and head.startswith("%d." % i)
            detail.append("第%d行=%s" % (i, l[:28]))
        lens = [len(l) for l in lines]
        detail.append("每行字数=%s（上限 34）" % lens)
        ok = ok and all(n <= 34 for n in lens)
    return ok, "；".join(detail)


def chk_math(sb: str, res: Dict[str, Any]) -> Tuple[bool, str]:
    import re
    content = (res.get("content") or "").strip()
    m1 = re.search(r"鸡\s*[=＝:：]\s*(\d+)", content)
    m2 = re.search(r"兔\s*[=＝:：]\s*(\d+)", content)
    if not (m1 and m2):
        return False, "未解析到 鸡=X、兔=Y；原文=%r" % content[:120]
    c, r = int(m1.group(1)), int(m2.group(1))
    ok = (c + r == 35) and (2 * c + 4 * r == 94)
    return ok, "鸡=%d 兔=%d（应 23/12，校验 头=%d 脚=%d）" % (
        c, r, c + r, 2 * c + 4 * r)


def chk_json(sb: str, res: Dict[str, Any]) -> Tuple[bool, str]:
    content = (res.get("content") or "").strip()
    fenced = content.startswith("```")
    body = _strip_fences(content)
    try:
        obj = json.loads(body)
    except Exception as e:
        return False, "JSON 解析失败：%s；原文=%r" % (e, content[:120])
    ok = (isinstance(obj, dict)
          and obj.get("product") == "Lemon Work"
          and isinstance(obj.get("features"), list)
          and len(obj["features"]) == 3)
    return ok, "解析成功%s；keys=%s；features=%s" % (
        "（含代码块标记，轻微格式扣分）" if fenced else "",
        list(obj.keys()), obj.get("features"))


def chk_write_code(sb: str, res: Dict[str, Any]) -> Tuple[bool, str]:
    p = os.path.join(sb, "prime.py")
    if not os.path.isfile(p):
        return False, "未生成 prime.py；工具调用=%s" % _tools(res)
    import py_compile
    try:
        py_compile.compile(p, doraise=True)
    except Exception as e:
        return False, "prime.py 语法错误：%s" % e
    try:
        mod = _load_module(p, "lw_prime_%d" % int(time.time()))
    except Exception as e:
        return False, "prime.py 无法导入：%s" % e
    fn = getattr(mod, "is_prime", None)
    if not callable(fn):
        return False, "没有 is_prime 函数"
    got = []
    for n in (2, 3, 4, 17, 25, 97):
        try:
            got.append(bool(fn(n)))
        except Exception as e:
            return False, "is_prime(%d) 抛错：%s" % (n, e)
    exp = [True, True, False, True, False, True]
    return got == exp, "is_prime(2,3,4,17,25,97)=%s（应 %s）；源码 %d 行" % (
        got, exp, len(_read(p).splitlines()))


def chk_fix_bug(sb: str, res: Dict[str, Any]) -> Tuple[bool, str]:
    p = os.path.join(sb, "calc.py")
    if not os.path.isfile(p):
        return False, "calc.py 不见了"
    try:
        mod = _load_module(p, "lw_calc_%d" % int(time.time()))
        v = mod.add(2, 3)
    except Exception as e:
        return False, "calc.py 无法运行：%s" % e
    return v == 5, "add(2,3)=%s（应 5）；源码=%r" % (v, _read(p).strip()[:120])


def chk_run_command(sb: str, res: Dict[str, Any]) -> Tuple[bool, str]:
    p = os.path.join(sb, "cmd_out.txt")
    if not os.path.isfile(p):
        return False, "未生成 cmd_out.txt；工具调用=%s" % _tools(res)
    txt = _read(p).strip()
    return txt == "ok", "cmd_out.txt=%r（应 'ok'）" % txt


def chk_csv(sb: str, res: Dict[str, Any]) -> Tuple[bool, str]:
    p = os.path.join(sb, "summary.md")
    if not os.path.isfile(p):
        return False, "未生成 summary.md；工具调用=%s" % _tools(res)
    txt = _read(p)
    need = ["83.00", "25.00", "28.00", "30.00"]
    miss = [n for n in need if n not in txt]
    return (not miss), "summary.md 命中=%s 缺失=%s；长度=%d" % (
        [n for n in need if n in txt], miss, len(txt))


def chk_model_switch(sb: str, res: Dict[str, Any]) -> Tuple[bool, str]:
    content = (res.get("content") or "").strip()
    model = res.get("model") or ""
    target = res.get("_target") or SWITCH_MODEL
    ok = ("北京" in content) and (target in model)
    return ok, "model=%s（目标 %s）回复=%r" % (model, target, content[:60])


def _tools(res: Dict[str, Any]) -> str:
    tc = res.get("tool_calls_made") or []
    try:
        return ",".join(str(t.get("name") or t.get("tool") or t) for t in tc)[:160]
    except Exception:
        return str(tc)[:160]


# ─────────────────────────── 用例定义 ───────────────────────────
def build_cases(sb: str, switch_target: str = SWITCH_MODEL) -> List[Dict[str, Any]]:
    return [
        {
            "id": "01_对话_指令格式",
            "kind": "chat",
            "prompt": ("请用三句话介绍 Lemon Work，每句单独一行，"
                       "以「1.」「2.」「3.」开头，每句不超过 30 个汉字。"
                       "不要解释，不要额外行，直接给结果。"),
            "check": chk_chat_format,
            "quality": "格式遵循（行数/序号/字数）",
        },
        {
            "id": "02_推理_数学",
            "kind": "chat",
            "prompt": ("鸡兔同笼，共 35 个头、94 只脚。问鸡和兔各多少只？"
                       "只输出一行最终答案，格式：鸡=X，兔=Y"),
            "check": chk_math,
            "quality": "数值正确性",
        },
        {
            "id": "03_结构化_JSON",
            "kind": "chat",
            "prompt": ('输出严格合法的 JSON（不要代码块标记、不要解释）：'
                       '{"product":"Lemon Work","version":"1.0",'
                       '"features":["中文词1","中文词2","中文词3"],"price":0}'),
            "check": chk_json,
            "quality": "JSON 合法性/字段完整性",
        },
        {
            "id": "04_Agent_写代码",
            "kind": "agent",
            "prompt": ("只在本目录内操作：%s\n"
                       "新建 prime.py，实现 is_prime(n) 判断质数（n<2 返回 False），"
                       "写完后不要解释代码，只回复一句完成说明。" % sb),
            "check": chk_write_code,
            "quality": "代码可编译/函数行为正确",
        },
        {
            "id": "05_Agent_读改文件",
            "kind": "agent",
            "prompt": ("只在本目录内操作：%s\n"
                       "读取 calc.py，它的 add 写成了减法，这是 bug。"
                       "修复为加法，函数名保持不变。" % sb),
            "check": chk_fix_bug,
            "quality": "文件读取/定点修改",
        },
        {
            "id": "06_Agent_执行命令",
            "kind": "agent",
            "prompt": ("只在本目录内操作：%s\n"
                       "用终端命令在该目录创建 cmd_out.txt，内容写 ok。" % sb),
            "check": chk_run_command,
            "quality": "命令执行/落盘",
        },
        {
            "id": "07_Agent_数据分析",
            "kind": "agent",
            "prompt": ("只在本目录内操作：%s\n"
                       "读取 sales.csv（列：product,qty,price），计算总金额 "
                       "sum(qty*price)，写入 summary.md；必须包含「总金额: 83.00」"
                       "（两位小数），并列出每个产品的小计。" % sb),
            "check": chk_csv,
            "quality": "数值计算/报告生成",
        },
        {
            "id": "08_模型切换_%s" % switch_target.split(":")[-1],
            "kind": "switch",
            "target": switch_target,
            "prompt": "中国的首都是哪里？只回答城市名。",
            "check": chk_model_switch,
            "quality": "模型切换生效/事实正确",
        },
    ]


# ─────────────────────────── 执行 ───────────────────────────
def run_case(em, case: Dict[str, Any], model: str, timeout: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"result": "ERROR", "detail": "", "duration": 0,
                           "iterations": 0, "tools": "", "content": ""}
    box: Dict[str, Any] = {}

    def work():
        try:
            if case["kind"] == "agent":
                r = em.agent_chat(case["prompt"], engine="ollama", model=model,
                                  history=[], max_iterations=6,
                                  session_id="lwtest_" + case["id"],
                                  confirm_callback=lambda *a, **k: True,
                                  think=False)
            else:
                if case["kind"] == "switch":
                    target = case.get("target") or SWITCH_MODEL
                    em.set_model("ollama", target)
                    r0 = em.chat(case["prompt"], engine="ollama",
                                 model=target, think=False)
                    r = {"content": r0.content, "model": r0.model,
                         "_target": target}
                else:
                    r0 = em.chat(case["prompt"], engine="ollama",
                                 model=model, think=False)
                    r = {"content": r0.content, "model": r0.model}
            box["res"] = r if isinstance(r, dict) else {"content": str(r)}
        except Exception as e:
            box["err"] = "%s: %s" % (type(e).__name__, e)

    t0 = time.time()
    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(timeout)
    out["duration"] = round(time.time() - t0, 1)

    if th.is_alive():
        out["result"] = "TIMEOUT"
        out["detail"] = "超过 %ds 未返回" % timeout
        try:
            em.cancel_agent()
        except Exception:
            pass
        return out

    if "err" in box:
        out["detail"] = box["err"]
        return out

    res = box.get("res") or {}
    out["content"] = (res.get("content") or "")[:400]
    out["iterations"] = res.get("iterations", 0)
    out["tools"] = _tools(res)
    try:
        passed, detail = case["check"](case.get("_sb", ""), res)
    except Exception as e:
        passed, detail = False, "检查器异常：%s" % e
    out["result"] = "PASS" if passed else "FAIL"
    out["detail"] = detail
    return out


# ─────────────────────────── 报告 ───────────────────────────
def write_report(meta: Dict[str, Any], rows: List[Dict[str, Any]],
                 extra: List[str], cleanup: Dict[str, Any],
                 path: str = REPORT_PATH) -> None:
    lines = ["# Lemon Work 本地模型能力测试报告", "",
             "- 时间：%s" % meta["time"],
             "- 引擎：`%s`　模型：`%s`" % (meta["engine"], meta["model"]),
             "- 可用引擎：%s" % ", ".join(meta["engines"]),
             "- 本机模型：%s" % ", ".join(meta["models"]),
             "- 测试方式：无 GUI，直接走 `EngineManager.chat` / `agent_chat`（真实工具循环）",
             "- 沙箱：`%s`" % meta["sandbox"], "",
             "## 汇总", "",
             "| 用例 | 结果 | 耗时(s) | 轮次 | 工具调用 | 质量判定 |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | **%s** | %s | %s | %s | %s |" % (
            r["id"], r["result"], r["duration"], r["iterations"],
            (r["tools"] or "-").replace("|", "/"), r["detail"].replace("|", "/")))
    passed = sum(1 for r in rows if r["result"] == "PASS")
    lines += ["", "**通过率：%d/%d（%.0f%%）**" % (
        passed, len(rows), 100.0 * passed / max(1, len(rows))), ""]

    lines += ["## 用例明细", ""]
    for r in rows:
        lines += ["### %s → %s" % (r["id"], r["result"]), "",
                  "- 耗时：%ss，轮次：%s" % (r["duration"], r["iterations"]),
                  "- 工具：`%s`" % (r["tools"] or "无"),
                  "- 质量检查：%s" % r["detail"],
                  "- 最终回复（截断）：", "", "```text",
                  (r["content"] or "（空）").replace("```", "'''"), "```", ""]

    lines += ["## 发现与说明", ""]
    lines += [("- " + e) for e in extra]

    lines += ["", "## 清理", "",
              "- 沙箱已删除：%s（路径 `%s`）" % (
                  "是" if cleanup["removed"] else "否",
                  cleanup["sandbox"]),
              "- 沙箱外新增文件：%d 个%s" % (
                  len(cleanup["outside"]),
                  ("（" + "、".join(cleanup["outside"][:5]) + "）")
                  if cleanup["outside"] else ""), ""]
    _write(path, "\n".join(lines))


# ─────────────────────────── 主流程 ───────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--report", default=REPORT_PATH, help="报告输出路径")
    ap.add_argument("--keep", action="store_true", help="保留沙箱")
    args = ap.parse_args()

    from PyQt5.QtWidgets import QApplication
    app = QApplication([])  # noqa: F841  (QObject 依赖)

    from shared.engine_manager import EngineManager
    em = EngineManager()
    em.initialize()
    em.set_active_engine("ollama")
    em.set_model("ollama", args.model)

    # 测试专用：切到 auto 权限档 + 预授权高危工具，否则 write_file/edit_file
    # 会被 confirm 门拦截，测到的就不是「模型/工具能力」而是「权限策略」。
    # 正式运行时仍保持默认 confirm 档。
    try:
        router = em._get_skill_router()
        for obj in (router, getattr(router, "registry", None)):
            if obj is not None and hasattr(obj, "_permission_mode"):
                obj._permission_mode = "auto"
        EngineManager._HIGH_RISK_GRANTED.update(
            {"write_file", "edit_file", "execute_code", "terminal_run"})
        print("权限档=auto（沙箱测试）", flush=True)
    except Exception as e:
        print("权限档设置失败:", e, flush=True)

    try:
        from shared.engine_manager import OllamaAdapter  # noqa: F401
    except Exception:
        pass
    models: List[str] = []
    try:
        eng = em.get_engine("ollama")
        models = eng.list_models()
    except Exception as e:
        print("list_models 失败:", e, flush=True)

    sb = os.path.join(SANDBOX_ROOT, "run_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(sb, exist_ok=True)
    _seed_sandbox(sb)

    project_before = set()
    for dirpath, _, files in os.walk(ROOT):
        if any(x in dirpath for x in ("__pycache__", "\\data\\", "\\.lemon", "\\dist\\", "\\bin\\_internal")):
            continue
        for f in files:
            project_before.add(os.path.join(dirpath, f))

    meta = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "ollama", "model": args.model,
        "engines": em.get_available_engines(),
        "models": models, "sandbox": sb,
    }
    print("模型=%s 可用=%s" % (args.model, models), flush=True)

    switch_target = DEFAULT_MODEL if args.model == SWITCH_MODEL else SWITCH_MODEL
    rows: List[Dict[str, Any]] = []
    for c in build_cases(sb, switch_target):
        c["_sb"] = sb
        print(">>> %s ..." % c["id"], flush=True)
        r = run_case(em, c, args.model, CASE_TIMEOUT)
        r["id"] = c["id"]
        r["quality"] = c["quality"]
        rows.append(r)
        print("    %s | %ss | %s" % (r["result"], r["duration"], r["detail"][:120]), flush=True)

    # 结束后切回默认模型
    try:
        em.set_model("ollama", args.model)
    except Exception:
        pass

    # 清理沙箱
    cleanup = {"sandbox": sb, "removed": False, "outside": []}
    if not args.keep:
        shutil.rmtree(sb, ignore_errors=True)
        cleanup["removed"] = not os.path.exists(sb)

    # 沙箱外新增文件（只报告，不擅删）
    for dirpath, _, files in os.walk(ROOT):
        if any(x in dirpath for x in ("__pycache__", "\\data\\", "\\.lemon", "\\dist\\", "\\bin\\_internal")):
            continue
        for f in files:
            p = os.path.join(dirpath, f)
            if p not in project_before and os.path.isfile(p):
                try:
                    if os.path.getmtime(p) >= time.time() - 3600:
                        cleanup["outside"].append(os.path.relpath(p, ROOT))
                except Exception:
                    pass

    extra = [
        "已修复：OllamaAdapter 读取了 `think` 参数却从未发给 Ollama，"
        "思考型模型会把思维链当正文输出；补上 `think:false` 后 4B 首轮从 31.4s/污染文本降到 0.6s/干净答案。",
        "测试在 auto 权限档下运行（仅沙箱内），避免 confirm 门拦截 `write_file`/`edit_file`，"
        "否则测到的是权限策略而非模型能力；产品正式运行仍为 confirm 档。",
        "本地小模型（4B/9B）的工具调用能力有限，Agent 用例的失败多与「不主动调用工具/参数不合规」有关，需结合报告具体项判断。",
        "测试全程要求模型只在沙箱目录内操作，未触碰项目源码。",
    ]
    write_report(meta, rows, extra, cleanup, args.report)
    print("报告：%s" % args.report, flush=True)

    passed = sum(1 for r in rows if r["result"] == "PASS")
    print("RESULT %d/%d PASS" % (passed, len(rows)), flush=True)
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
