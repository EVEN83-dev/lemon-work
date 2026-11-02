#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lemon Work · 银行业务端到端驱动验证（DeepSeek 实跑）

覆盖用户三大验证点：
  E1-E3. DeepSeek 驱动虚拟银行办理赛题核心场景（转账/账单分析/理财）——
         工具全部成功、结论规范表达（结构化 markdown，无源码裸奔）
  E4.    页面跟随联动：业务办理后银行操作台 UI 状态总线被自动驱动
         （v356：业务工具 → panel 映射 → /api/ui/state → 页面跳动）
  E5.    任务卡真拆解（语义步骤，非流水账）
  E6.    白盒完整（轮次/思考/叙述渲染）

用法：
    _py312\\python.exe scripts\\gui_bank_e2e_test.py
结果：逐条 PASS/FAIL + 汇总；截图 %TEMP%\\lw_e2e_test.png
"""
from __future__ import annotations

import importlib.util
import json
import os
import runpy
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

spec = importlib.util.spec_from_file_location(
    "yh_main_boot", os.path.join(ROOT, "yh_main.py"))
yh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(yh)
yh._ensure_bank_server()
yh._install_patch()

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from ui.main_window import MIMOWindow

RESULTS: list[tuple[str, bool, str]] = []
STATE = {"done": False, "idx": 0, "t0": 0.0, "wait_final": False}

# 赛题核心场景指令（覆盖 01 智能转账 / 02 账单分析 / 03 理财操作）
TASKS = [
    ("E1_智能转账", "用数字银行帮我从主账户给 ACC002 转账 100 元，备注 e2e联动测试，办完把界面切到转账页让我看清这笔流水。"),
    ("E2_账单分析", "分析一下我的账单消费情况，看看有没有异常消费，然后把银行界面切到个人中心给我展示。"),
    ("E3_理财操作", "查一下可买的理财产品并给我推荐一个，然后把银行界面切到基金页。"),
]

SNAP_JS = (
    "(function(){var runs=document.querySelectorAll('.agent-run');"
    "var run=runs[runs.length-1];if(!run)return '{}';"
    "var r={rounds:run.querySelectorAll('.tr-round').length,"
    "items:run.querySelectorAll('.tg-item').length,"
    "fail:run.querySelectorAll('.tg-item.fail').length,"
    "final:run.querySelector('.trace-final')?1:0,final_len:0,"
    "final_html:'',steps:0,steps_text:''};"
    "var fb=run.querySelector('.trace-final .tf-body');"
    "if(fb){r.final_len=(fb.textContent||'').length;r.final_html=(fb.innerHTML||'').slice(0,600);}"
    "var dock=document.getElementById('agentTaskPanel');"
    "if(dock&&dock._lastTasks){r.steps=dock._lastTasks.length;"
    "r.steps_text=JSON.stringify(dock._lastTasks).slice(0,200);}"
    "return JSON.stringify(r);})()")


def report(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, ok, detail))
    print("[%s] %s %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)


def main() -> int:
    orig_show = MIMOWindow.show

    def show(self):
        orig_show(self)

        def panel():
            try:
                sw = getattr(self, "session_workspace", None)
                return sw.current_panel() if sw is not None else None
            except Exception:
                return None

        def step_start():
            import requests
            try:
                r = requests.get("http://127.0.0.1:8090/api/health",
                                 timeout=3, proxies={"http": None, "https": None})
                report("E0_银行在线", r.status_code == 200,
                       str(r.json().get("version", "")))
            except Exception as e:
                report("E0_银行在线", False, str(e)[:80])
            STATE["t0"] = time.time()
            run_task()

        def run_task():
            """串行执行 3 条赛题场景（每条等收口再发下一条）。"""
            if STATE["idx"] >= len(TASKS):
                verify_follow()
                return
            p = panel()
            if p is None:
                QTimer.singleShot(2000, run_task)
                return
            label, prompt = TASKS[STATE["idx"]]
            STATE["wait_final"] = False
            try:
                p._send_via_agent_chat(prompt, engine_id="deepseek")
                print("[E2E] 发送任务 %d: %s" % (STATE["idx"] + 1, label), flush=True)
            except Exception as e:
                report(label, False, "注入失败: " + str(e)[:60])
                STATE["idx"] += 1
                run_task()
                return
            QTimer.singleShot(3000, lambda: wait_final(label))

        def wait_final(label):
            """轮询等 final 出现（最长 90s/条）。"""
            if STATE["done"]:
                return
            p = panel()
            if p is None:
                QTimer.singleShot(4000, lambda: wait_final(label))
                return
            p.web_view.page().runJavaScript(SNAP_JS, lambda res: on_snap(label, res))

        def on_snap(label, res):
            if STATE["done"]:
                return
            try:
                d = json.loads(res) if isinstance(res, str) and res else {}
            except Exception:
                d = {}
            elapsed = time.time() - STATE["t0"]
            if d.get("final") and int(d.get("final_len") or 0) > 30:
                check_task(label, d)
                STATE["idx"] += 1
                STATE["t0"] = time.time()
                QTimer.singleShot(2500, run_task)
                return
            if elapsed > 90:
                report(label, False, "超时 90s 未收口（rounds=%s items=%s）"
                       % (d.get("rounds"), d.get("items")))
                STATE["idx"] += 1
                STATE["t0"] = time.time()
                QTimer.singleShot(1500, run_task)
                return
            QTimer.singleShot(4000, lambda: wait_final(label))

        def check_task(label, d):
            """单条任务断言：工具成功 + 规范表达 + 拆解 + 白盒。"""
            # ① 工具全部成功（转账/分析类任务至少 1 个工具）
            report(label + "·工具执行", int(d.get("fail") or 0) == 0
                   and int(d.get("items") or 0) >= 1,
                   "items=%s fail=%s" % (d.get("items"), d.get("fail")))
            # ② 规范表达：结论结构化且无 markdown 源码裸奔
            fh = str(d.get("final_html") or "")
            bare = "**" in fh or "\n##" in fh or "|----" in fh
            structured = ("<table" in fh or "<h2" in fh or "<h3" in fh
                          or "<li" in fh or "<b>" in fh or "<ol" in fh)
            report(label + "·规范表达", int(d.get("final_len") or 0) >= 50
                   and not bare and structured,
                   "len=%s bare=%s structured=%s" % (d.get("final_len"), bare, structured))
            # ③ 白盒完整
            report(label + "·白盒完整", int(d.get("rounds") or 0) >= 1,
                   "rounds=%s" % d.get("rounds"))
            # ④ 任务卡真拆解（最后一条时验证）
            if label.startswith("E3"):
                st = str(d.get("steps_text") or "")
                report("E5_任务卡真拆解", int(d.get("steps") or 0) >= 3
                       and "理解请求并拆解任务" in st,
                       "steps=%s" % d.get("steps"))

        def verify_follow():
            """★ E4: 页面跟随联动 —— 业务办理后 UI 状态总线被自动驱动。"""
            import requests
            try:
                r = requests.get("http://127.0.0.1:8090/api/ui/state", timeout=3,
                                 proxies={"http": None, "https": None})
                s = (r.json() or {}).get("state") or {}
                driven = bool(s.get("ts")) and float(s.get("ts") or 0) > (STATE.get("t_start", 0))
                report("E4_页面跟随联动", driven and bool(s.get("view")),
                       "view=%s highlight=%s msg=%s" % (s.get("view"), s.get("highlight"), s.get("msg")))
            except Exception as e:
                report("E4_页面跟随联动", False, str(e)[:80])
            finish()

        def finish():
            if STATE["done"]:
                return
            STATE["done"] = True
            try:
                p = panel()
                if p is not None:
                    self.grab().save(os.path.join(
                        os.environ.get("TEMP", "."), "lw_e2e_test.png"))
            except Exception:
                pass
            passed = sum(1 for _, ok, _ in RESULTS if ok)
            print("SUMMARY %d/%d PASS" % (passed, len(RESULTS)), flush=True)
            QApplication.instance().quit()

        STATE["t_start"] = time.time()
        QTimer.singleShot(5000, step_start)

    MIMOWindow.show = show
    runpy.run_path(os.path.join(ROOT, "standard_mode", "main.py"),
                   run_name="__main__")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    return 0 if RESULTS and passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
