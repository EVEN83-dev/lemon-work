#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lemon Work · 深圳金融科技大赛「银行 AI 智能体」六场景合规测试（DeepSeek 实跑）

赛题要求：至少覆盖 3 个核心场景，鼓励完整覆盖全部场景。本脚本全覆盖：
  S1 智能转账      —— 按人名查找收款人 + 转账 + 定时转账
  S2 账单分析      —— 消费分类统计 + 异常交易识别
  S3 理财操作      —— 产品推荐与对比（风险评估）+ 一键申购
  S4 卡片管理      —— 额度调整 + 卡片状态
  S5 订阅/代扣管理 —— 自动识别订阅扣费 + 一键取消订阅
  S6 跨场景联动    —— 识别生日需求 → 商城订花 → 订单呈现

每场景断言：
  ① 工具执行成功（fail=0 且命中该场景的期望工具族）
  ② 规范表达（结论结构化 markdown，无源码裸奔）
  ③ 白盒完整（轮次渲染）
  F. 页面跟随联动（ui/state 总线被业务驱动）

用法：
    _py312\\python.exe scripts\\gui_competition_test.py
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
STATE = {"done": False, "idx": 0, "t0": 0.0}

# 六场景指令（每条含"切到 xx 页"顺带验证页面联动）
# expect_kw 用【中文工具名】匹配（v351 起白盒 ti-text 显示中文名）
TASKS = [
    ("S1_智能转账", "转账|收款人|定时",
     "用数字银行查一下陈奕汐的收款账号，并从主账户给她转 66 元，备注比赛测试；"
     "如果支持定时转账，再预约明天给 ACC003 转 200 元。办完把界面切到转账页。"),
    ("S2_账单分析", "账单",
     "分析我的账单消费情况：统计消费分类，并识别有没有异常交易，"
     "结论做成表格。然后切到个人中心展示。"),
    ("S3_理财操作", "理财|基金|产品",
     "给我推荐理财产品并对比一下风险等级，选最稳健的一款申购 500 元。"
     "完成后把银行界面切到基金页。"),
    ("S4_卡片管理", "银行卡|卡片",
     "帮我管理一下银行卡：把主账户卡设置单笔交易限额 5000 元，"
     "并告诉我当前卡片状态。办完切到个人中心。"),
    ("S5_订阅代扣", "订阅",
     "查一下我名下有哪些订阅扣费，把最贵的一个一键取消订阅，"
     "然后把界面切到个人中心给我看办事单。"),
    ("S6_跨场景联动", "商城|权益",
     "我朋友陈奕汐生日快到了：在银行商城订一束鲜花（下单即可不用真送），"
     "然后把界面切到个人中心让我看到这笔订单。"),
]

SNAP_JS = (
    "(function(){var runs=document.querySelectorAll('.agent-run');"
    "var run=runs[runs.length-1];if(!run)return '{}';"
    "var r={rounds:run.querySelectorAll('.tr-round').length,"
    "items:run.querySelectorAll('.tg-item').length,"
    "fail:run.querySelectorAll('.tg-item.fail').length,"
    "final:run.querySelector('.trace-final')?1:0,final_len:0,"
    "final_html:'',tools:''};"
    "var fb=run.querySelector('.trace-final .tf-body');"
    "if(fb){r.final_len=(fb.textContent||'').length;r.final_html=(fb.innerHTML||'').slice(0,500);}"
    "var names={};run.querySelectorAll('.tg-item .ti-text').forEach(function(t){"
    "var k=(t.textContent||'').split(' · ')[0];if(k)names[k]=1;});"
    "r.tools=Object.keys(names).join(',').slice(0,300);"
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
                report("F0_银行在线", r.status_code == 200,
                       str(r.json().get("version", "")))
            except Exception as e:
                report("F0_银行在线", False, str(e)[:80])
            STATE["t0"] = time.time()
            run_task()

        def run_task():
            if STATE["done"] or STATE["idx"] >= len(TASKS):
                verify_follow()
                return
            p = panel()
            if p is None:
                QTimer.singleShot(2000, run_task)
                return
            label, expect_kw, prompt = TASKS[STATE["idx"]]
            STATE["expect"] = expect_kw
            try:
                p._send_via_agent_chat(prompt, engine_id="deepseek")
                print("[COMP] 场景 %d/6: %s" % (STATE["idx"] + 1, label), flush=True)
            except Exception as e:
                report(label, False, "注入失败: " + str(e)[:60])
                STATE["idx"] += 1
                run_task()
                return
            QTimer.singleShot(3000, lambda: wait_final(label))

        def wait_final(label):
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
                check_task(label, STATE.get("expect", ""), d)
                STATE["idx"] += 1
                STATE["t0"] = time.time()
                QTimer.singleShot(2500, run_task)
                return
            if elapsed > 120:
                report(label, False, "超时 120s 未收口（rounds=%s items=%s）"
                       % (d.get("rounds"), d.get("items")))
                STATE["idx"] += 1
                STATE["t0"] = time.time()
                QTimer.singleShot(1500, run_task)
                return
            QTimer.singleShot(4000, lambda: wait_final(label))

        def check_task(label, expect_tools, d):
            # ① 工具执行成功
            report(label + "·工具执行", int(d.get("fail") or 0) == 0
                   and int(d.get("items") or 0) >= 1,
                   "items=%s fail=%s" % (d.get("items"), d.get("fail")))
            # ② 期望工具族命中（DeepSeek 选对了该场景的技能）
            import re as _re
            tools = str(d.get("tools") or "")
            hit = _re.search(expect_tools, tools) is not None
            report(label + "·工具命中", hit,
                   "expect=/%s/ got=%s" % (expect_tools, tools[:80]))
            # ③ 规范表达
            fh = str(d.get("final_html") or "")
            bare = "**" in fh or "\n##" in fh or "|----" in fh
            structured = ("<table" in fh or "<h2" in fh or "<h3" in fh
                          or "<li" in fh or "<b>" in fh or "<ol" in fh)
            report(label + "·规范表达", int(d.get("final_len") or 0) >= 50
                   and not bare and structured,
                   "len=%s bare=%s structured=%s" % (d.get("final_len"), bare, structured))
            # ④ 白盒完整
            report(label + "·白盒完整", int(d.get("rounds") or 0) >= 1,
                   "rounds=%s" % d.get("rounds"))

        def verify_follow():
            import requests
            try:
                r = requests.get("http://127.0.0.1:8090/api/ui/state", timeout=3,
                                 proxies={"http": None, "https": None})
                s = (r.json() or {}).get("state") or {}
                report("F_页面跟随联动", bool(s.get("view")) and bool(s.get("ts")),
                       "view=%s highlight=%s msg=%s" % (s.get("view"), s.get("highlight"), s.get("msg")))
            except Exception as e:
                report("F_页面跟随联动", False, str(e)[:80])
            finish()

        def finish():
            if STATE["done"]:
                return
            STATE["done"] = True
            try:
                p = panel()
                if p is not None:
                    self.grab().save(os.path.join(
                        os.environ.get("TEMP", "."), "lw_competition_test.png"))
            except Exception:
                pass
            passed = sum(1 for _, ok, _ in RESULTS if ok)
            # 赛题门槛：至少覆盖 3 个核心场景（按"工具执行+工具命中"双绿计）
            scenes_ok = sum(1 for name, ok, _ in RESULTS
                            if ok and ("·工具执行" in name or "·工具命中" in name))
            print("SCENE_COVERAGE %d/6 场景双指标通过" % (scenes_ok // 2), flush=True)
            print("SUMMARY %d/%d PASS" % (passed, len(RESULTS)), flush=True)
            QApplication.instance().quit()

        QTimer.singleShot(5000, step_start)

    MIMOWindow.show = show
    runpy.run_path(os.path.join(ROOT, "standard_mode", "main.py"),
                   run_name="__main__")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    return 0 if RESULTS and passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
