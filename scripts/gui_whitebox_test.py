#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lemon Work · 白盒自动化测试（GUI 断言式，替代人工截图检查）

覆盖：
  A. 数字银行守护：启动时 :8090 自动在线
  B. 多层白盒：真实 agent 运行产生 ≥1 个"第 N 轮"小节，工具卡内嵌轮次
  C. 任务卡默认停靠：agentTaskPanel 位于 .input-area 内
  D. 排队列表：入队→列表可见→单条撤销→计数减少
  E. 连接测试：模型面板 testEngineLatency 返回真实延迟
  F. 无空过程层：DOM 中不存在"空的过程层横幅"

用法：
    _py312\\python.exe scripts\\gui_whitebox_test.py
结果：逐条 PASS/FAIL + 汇总；截图存 %TEMP%\\lw_gui_test.png
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
yh._ensure_bank_server()   # ★ 显式调用（import 方式不触发 __main__ 守卫）
yh._install_patch()

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from ui.main_window import MIMOWindow

RESULTS: list[tuple[str, bool, str]] = []
STATE = {"phase": 0, "done": False}


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

        def step_a():
            # A. 银行守护
            import requests
            try:
                r = requests.get("http://127.0.0.1:8090/api/health",
                                 timeout=3, proxies={"http": None, "https": None})
                report("A_银行守护在线", r.status_code == 200,
                       str(r.json().get("version", "")))
            except Exception as e:
                report("A_银行守护在线", False, str(e)[:80])

            # A2. 行情引擎真的在跳（用户截图里 6 只全 0.0% —— 开盘未 tick）
            #     开盘后 1 个 tick(3s) 内可能正好是 0，故最多轮询 4 次 / 每次隔 4s。
            def _quote(tries=4):
                def _once(n):
                    try:
                        q = requests.get("http://127.0.0.1:8090/api/quote", timeout=3,
                                         proxies={"http": None, "https": None}).json()
                        items = q.get("items") or []
                        nz = [x for x in items if abs(float(x.get("change_pct") or 0)) > 0.01]
                    except Exception as e:
                        report("A2_行情跳动", False, str(e)[:80])
                        return
                    if len(nz) >= 1:
                        report("A2_行情跳动", True,
                               "非零 %d/%d" % (len(nz), len(items)))
                        return
                    if n <= 1:
                        report("A2_行情跳动", False,
                               "非零 0/%d（多次轮询仍静止）" % len(items))
                        return
                    QTimer.singleShot(4000, lambda: _once(n - 1))
                _once(tries)

            QTimer.singleShot(6000, _quote)

        def step_b_send():
            p = panel()
            if p is None:
                QTimer.singleShot(2000, step_b_send)
                return
            try:
                # ★ 用真实发送链路（inject_user_message 不走 agent 循环）
                p._send_via_agent_chat("去数字银行帮我看一下现在的股票行情怎么样",
                                       engine_id="deepseek")
                report("B0_指令注入", True, "经 _send_via_agent_chat")
            except Exception as e:
                report("B0_指令注入", False, str(e)[:80])
            QTimer.singleShot(45000, step_c_check)

        def step_c_check():
            if STATE.get("c_checked"):
                return
            STATE["c_checked"] = True
            p = panel()
            if p is None:
                return
            js = ("(function(){var r={};"
                  "r.rounds=document.querySelectorAll('.tr-round').length;"
                  "var tools=document.querySelectorAll('.trace-group');"
                  "r.tool_groups=tools.length;"
                  "r.tool_fail=document.querySelectorAll('.tg-item.fail').length;"
                  "var dock=document.getElementById('agentTaskPanel');"
                  "r.task_docked = dock && dock.closest('.input-area') ? true : false;"
                  "r.task_steps = dock && dock._lastTasks ? dock._lastTasks.length : 0;"
                  "r.task_text = dock && dock._lastTasks ? "
                  "JSON.stringify(dock._lastTasks).slice(0,300) : '';"
                  "var ib=document.querySelector('.input-area .input-box');"
                  "r.dock_gap = (dock && ib) ? Math.round("
                  "ib.getBoundingClientRect().top-dock.getBoundingClientRect().bottom) : -1;"
                  "var empty=0;"
                  "document.querySelectorAll('.run-process').forEach(function(p){"
                  "  if(!p.querySelector('.trace-text,.trace-group,.trace-status,"
                  "     .trace-think,.ti-brief,.trace-bg-task,.tr-round')) empty++;});"
                  "r.empty_process=empty;"
                  "var runs=document.querySelectorAll('.agent-run');"
                  "var run=runs[runs.length-1];"
                  "var ff=run?run.querySelector('.trace-final .tf-body'):null;"
                  "r.final_font = ff ? parseFloat(getComputedStyle(ff).fontSize) : 0;"
                  "var pf=run?run.querySelector('.trace-text'):null;"
                  "r.process_font = pf ? parseFloat(getComputedStyle(pf).fontSize) : 0;"
                  "var td=run?run.querySelector('.tf-body td'):null;"
                  "r.td_font = td ? parseFloat(getComputedStyle(td).fontSize) : 0;"
                  "return JSON.stringify(r);})()")
            p._safe_run_js  # noqa: B018  (确认存在)
            p.web_view.page().runJavaScript(
                js, lambda res: _after_c(res))

        def _after_c(res):
            try:
                d = json.loads(res) if isinstance(res, str) else (res or {})
            except Exception:
                d = {}
            report("B_多层轮次渲染", int(d.get("rounds", 0)) >= 1,
                   "rounds=%s" % d.get("rounds"))
            report("B_工具卡存在", int(d.get("tool_groups", 0)) >= 1,
                   "groups=%s" % d.get("tool_groups"))
            report("C_任务卡停靠底部", bool(d.get("task_docked")),
                   "agentTaskPanel 在 .input-area 内")
            # ★ v352: 任务卡必须是"语义拆解"而非执行流水账 ——
            #   首步=理解请求并拆解任务，且不再出现"执行工具调用（共 N 次）"固定文案
            _tt = str(d.get("task_text", ""))
            report("C2_任务卡真拆解",
                   int(d.get("task_steps", 0)) >= 3
                   and "理解请求并拆解任务" in _tt
                   and "执行工具调用（共" not in _tt,
                   "steps=%s text=%s" % (d.get("task_steps"), _tt[:90]))
            report("F_无空过程层", int(d.get("empty_process", 1)) == 0,
                   "empty=%s" % d.get("empty_process"))
            g = float(d.get("dock_gap", -1))
            report("J_任务条紧贴输入框", 0 <= g <= 8, "gap=%spx" % g)
            ff = float(d.get("final_font", 0) or 0)
            pf = float(d.get("process_font", 0) or 0)
            tf = float(d.get("td_font", 0) or 0)
            report("I_输入输出字号一致",
                   ff > 0 and pf > 0 and abs(ff - pf) <= 1.0 and tf <= 14.5,
                   "final=%s process=%s td=%s" % (ff, pf, tf))
            report("L_工具无失败项", int(d.get("tool_fail", 1)) == 0,
                   "fail=%s" % d.get("tool_fail"))
            step_d_queue()

        def step_d_queue():
            p = panel()
            if p is None:
                return
            try:
                p._enqueue_pending_message("测试排队一", "deepseek", "")
                p._enqueue_pending_message("测试排队二", "deepseek", "")
            except Exception as e:
                report("D_入队", False, str(e)[:80])
                step_e_conn()
                return

            def check1():
                p.web_view.page().runJavaScript(
                    "(function(){var l=document.querySelectorAll('.pq-item').length;"
                    "return l;})()",
                    lambda n: _after_d1(n))

            def _after_d1(n):
                report("D_排队列表可见", int(n or 0) == 2, "pq-item=%s" % n)
                p._remove_pending_message(0)

                def check2():
                    p.web_view.page().runJavaScript(
                        "(function(){return document.querySelectorAll('.pq-item').length;})()",
                        lambda n2: _after_d2(n2))

                QTimer.singleShot(1200, check2)

            def _after_d2(n2):
                report("D_单条撤销", int(n2 or 0) == 1, "剩余 pq-item=%s" % n2)
                try:
                    p._clear_pending_queue()
                except Exception:
                    pass
                step_e_conn()

            QTimer.singleShot(1500, check1)

        def step_e_conn():
            p = panel()
            if p is None:
                return
            p._safe_run_js("if(window.testEngineLatency)window.testEngineLatency();"
                   "else window.__connErr='no-fn';")

            def check():
                p.web_view.page().runJavaScript(
                    "(function(){var el=document.getElementById('mpConnResult');"
                    "return el?el.textContent:'';})()",
                    lambda t: _after_e(t))

            QTimer.singleShot(9000, check)

        def _after_e(text):
            t = str(text or "")
            report("E_连接测试", "ms" in t, t[:80])
            step_g_thinking()

        def step_g_thinking():
            """合成两轮 trace：验证 思考按轮隔离 / 保持展开 / 字体对比 / 单过程层。

            ★ v350: 同一合成流扩展 —— 分节点思考（\\n\\n 两段）/ narrative 时间线 /
            同名×3 聚合条 / usage 卡 / 全量浮层 / 35-run 渲染窗口 / 队列挂起。"""
            p = panel()
            if p is None:
                finish()
                return
            p._safe_run_js(
                "(function(){if(!window.TraceRenderer)return;"
                "TraceRenderer.consume({kind:'run_start',engine:'selftest'});"
                "TraceRenderer.consume({kind:'round',idx:1,engine:'selftest',max_rounds:12});"
                "TraceRenderer.consume({kind:'thinking',content:'第一轮思考：先查账户余额，确认资金是否充足。\\n\\n补充：同时核对最近一笔流水的到账状态。',delta:true});"
                "TraceRenderer.consume({kind:'round',idx:2,engine:'selftest',max_rounds:12});"
                "TraceRenderer.consume({kind:'thinking',content:'## 执行计划\\n\\n**重点**：余额充足，执行一笔定时转账。\\n\\n| 项目 | 金额 |\\n|----|----|\\n| 转出 | 500 元 |',delta:true});"
                "TraceRenderer.consume({kind:'narrative',text:'第 1 轮执行完成，共调用 2 次工具',tools:[{name:'remote_bank_query_balance',ok:true,ms:210},{name:'remote_bank_transactions',ok:true,ms:180}]});"
                "for(var i=0;i<3;i++)TraceRenderer.consume({kind:'tool_start',name:'remote_bank_query_balance',ttype:'read',arg:'ACC00'+(i+1)});"
                "for(var i=0;i<3;i++)TraceRenderer.consume({kind:'tool_end',name:'remote_bank_query_balance',ttype:'read',arg:'ACC00'+(i+1),ok:true,ms:120+i,result:'余额 1234.56 元'});"
                "TraceRenderer.consume({kind:'tool_start',name:'remote_find_account',ttype:'search',arg:'张三'});"
                "TraceRenderer.consume({kind:'tool_end',name:'remote_find_account',ttype:'search',arg:'张三',ok:true,ms:95,result:'收款人已找到'});"
                "TraceRenderer.consume({kind:'text_delta',text:'## 汇总\\n\\n**转账执行中**，进度如下：\\n\\n| 步骤 | 状态 |\\n|----|----|\\n| 出账 | 成功 |\\n| 到账 | 处理中 |'});"
                "TraceRenderer.consume({kind:'final',content:'自检结论：两轮白盒节点各自独立。'});"
                "TraceRenderer.consume({kind:'meta',engine:'selftest',model:'v350',iterations:2,tools:4,total_time:3.2,input_tokens:1500,output_tokens:800,cost:0.0021,success:true});"
                "TraceRenderer.consume({kind:'run_end',ok:true});"
                "TraceRenderer.consume({kind:'full_result',title:'自检全量',text:'全量结果内容——这是一个用于验证浮层的长文本。'});"
                "})()")

            def check():
                js = ("(function(){var runs=document.querySelectorAll('.agent-run');"
                      "var run=null;for(var i=runs.length-1;i>=0;i--){"
                      "if(runs[i].querySelector('.usage-card')){run=runs[i];break;}}"
                      "if(!run)return '';"
                      "var r={};"
                      "var ths=run.querySelectorAll('.trace-think');"
                      "var rds=run.querySelectorAll('.tr-round');"
                      "var inner=run.querySelectorAll('.tr-round .trace-think');"
                      "var th=ths[ths.length-1];var tb=th?th.querySelector('.th-body'):null;"
                      "r.think_n=ths.length;r.open_n=run.querySelectorAll('.trace-think.open').length;"
                      "r.round_n=rds.length;r.think_rounds=inner.length;"
                      "r.len1=ths[0]?(ths[0].querySelector('.th-body').textContent||'').length:0;"
                      "r.len2=ths[1]?(ths[1].querySelector('.th-body').textContent||'').length:0;"
                      "r.font=tb?parseFloat(getComputedStyle(tb).fontSize):0;r.light=0;"
                      "if(tb){var c=getComputedStyle(tb).color;"
                      "var m=c.match(/rgba?\\((\\d+)\\D+(\\d+)\\D+(\\d+)/);"
                      "if(m)r.light=Math.min(+m[1],+m[2],+m[3]);}"
                      "r.process_n=run.querySelectorAll('.run-process').length;r.proc_empty=0;"
                      "run.querySelectorAll('.run-process').forEach(function(p){"
                      "if(!p.querySelector('.trace-text,.trace-group,.trace-status,"
                      ".trace-think,.trace-bg-task,.tr-round,.narr-wrap'))r.proc_empty++;});"
                      "r.node_n=run.querySelectorAll('.think-node').length;"
                      "r.narr_n=run.querySelectorAll('.narr-item').length;"
                      "r.agg_n=run.querySelectorAll('.agg-bar').length;"
                      "r.usage_n=run.querySelectorAll('.usage-card').length;"
                      "var ph=run.querySelector('.proc-head');"
                      "r.head=ph?ph.textContent:'';"
                      "r.badge=run.querySelector('.tr-round-badge')?"
                      "run.querySelector('.tr-round-badge').textContent:'';"
                      "r.runs_total=document.querySelectorAll('.agent-run').length;"
                      "r.mask=document.getElementById('lwFullResultMask')?1:0;"
                      "var tt=run.querySelector('.trace-text');"
                      "r.md_html=tt?tt.innerHTML:'';"
                      "var ths2=run.querySelectorAll('.trace-think .th-body');"
                      "var thh=ths2[ths2.length-1];"
                      "r.th_html=thh?thh.innerHTML:'';"
                      "return JSON.stringify(r);})()")
                p.web_view.page().runJavaScript(js, lambda res: _after_g(res))

            def _after_g(res):
                try:
                    d = json.loads(res) if isinstance(res, str) and res else {}
                except Exception:
                    d = {}
                report("G_思考按轮隔离",
                       int(d.get("think_n", 0)) >= 2 and int(d.get("think_rounds", 0)) >= 2
                       and int(d.get("len1", 0)) > 0 and int(d.get("len2", 0)) > 0,
                       "think=%s 轮内=%s len=%s/%s" % (
                           d.get("think_n"), d.get("think_rounds"),
                           d.get("len1"), d.get("len2")))
                report("G2_思考保持展开",
                       int(d.get("open_n", 0)) >= 2
                       and int(d.get("open_n", 0)) == int(d.get("think_n", -1)),
                       "open=%s/%s" % (d.get("open_n"), d.get("think_n")))
                report("H_思考清晰可读",
                       float(d.get("font", 0)) >= 13.0 and int(d.get("light", 0)) >= 180,
                       "font=%s minRGB=%s" % (d.get("font"), d.get("light")))
                report("M_单过程层",
                       int(d.get("process_n", 0)) == 1 and int(d.get("proc_empty", 1)) == 0,
                       "process=%s empty=%s" % (d.get("process_n"), d.get("proc_empty")))
                # ── v350 新断言 ──
                report("N_统一过程头",
                       "已深度思考与执行" in str(d.get("head", "")),
                       str(d.get("head", ""))[:60])
                report("N2_思考分节点",
                       int(d.get("node_n", 0)) >= 2,
                       "node=%s" % d.get("node_n"))
                report("N3_过程时间线",
                       int(d.get("narr_n", 0)) >= 1,
                       "narr=%s" % d.get("narr_n"))
                report("N4_工具聚合条",
                       int(d.get("agg_n", 0)) >= 1,
                       "agg=%s" % d.get("agg_n"))
                report("N5_usage卡",
                       int(d.get("usage_n", 0)) == 1,
                       "usage=%s" % d.get("usage_n"))
                report("N6_轮次上限",
                       "/12" in str(d.get("badge", "")),
                       str(d.get("badge", "")))
                report("N8_全量浮层",
                       int(d.get("mask", 0)) == 1,
                       "mask=%s" % d.get("mask"))
                # ★ v353: markdown 乱码根治 —— 合成叙述/思考含 **粗体**/##/表格，
                #   渲染后 innerHTML 不得残留字面 ** 源码，且应有真实渲染产物
                #   （<b>/<h2>/<table>/lite-md 任一）
                _md = str(d.get("md_html", ""))
                _th = str(d.get("th_html", ""))
                _md_rendered = ("<b>" in _md or "<h2" in _md or "<table" in _md
                                or "lite-md" in _md)
                report("R_叙述不裸奔",
                       _md and "**" not in _md and _md_rendered,
                       "len=%s rendered=%s head=%s" % (
                           len(_md), _md_rendered, _md[:60]))
                _th_rendered = ("<b>" in _th or "<h2" in _th or "<table" in _th
                                or "lite-md" in _th)
                report("R2_思考不裸奔",
                       _th and "**" not in _th and _th_rendered,
                       "len=%s rendered=%s head=%s" % (
                           len(_th), _th_rendered, _th[:60]))
                step_g2_filler()

            def step_g2_filler():
                """★ v350: 渲染窗口 —— 灌 35 个 run 后应只剩 30。"""
                p3 = panel()
                if p3 is None:
                    step_h_queue_ops()
                    return
                p3._safe_run_js(
                    "(function(){if(!window.TraceRenderer)return;"
                    "for(var k=0;k<35;k++){"
                    "TraceRenderer.consume({kind:'run_start',engine:'filler'+k});"
                    "TraceRenderer.consume({kind:'run_end',ok:true});}})()")

                def check3():
                    p3.web_view.page().runJavaScript(
                        "(function(){return document.querySelectorAll('.agent-run').length;})()",
                        lambda n: _after_g2(n))

                def _after_g2(n):
                    report("N7_渲染窗口", int(n or 999) <= 30, "runs=%s" % n)
                    step_h_queue_ops()

                QTimer.singleShot(900, check3)

            def step_h_queue_ops():
                """★ v350: 队列挂起态 + 单条操作按钮。"""
                p2 = panel()
                if p2 is None:
                    finish()
                    return
                p2._update_pending_ui()
                p2._safe_run_js(
                    "if(window.setPendingQueue)window.setPendingQueue(2,'',"
                    "[{i:0,preview:'排队甲消息预览',full:'排队甲消息全文'},{i:1,preview:'排队乙消息预览',full:'排队乙消息全文'}],true);")

                def check2():
                    js2 = ("(function(){var r={};"
                           "r.paused_row=document.querySelector('.pq-paused-row')?1:0;"
                           "r.ops=document.querySelectorAll('.pq-item .pq-op').length;"
                           "r.pause_btn=document.querySelector('#pendingQueueBar .pq-pause')?1:0;"
                           "r.items=document.querySelectorAll('.pq-item').length;"
                           "return JSON.stringify(r);})()")
                    p2.web_view.page().runJavaScript(js2, lambda res2: _after_h(res2))

                def _after_h(res2):
                    try:
                        d2 = json.loads(res2) if isinstance(res2, str) and res2 else {}
                    except Exception:
                        d2 = {}
                    report("Q_队列挂起态", int(d2.get("paused_row", 0)) == 1,
                           "paused_row=%s" % d2.get("paused_row"))
                    report("Q2_单条操作列",
                           int(d2.get("ops", 0)) >= 6 and int(d2.get("items", 0)) >= 2,
                           "ops=%s items=%s" % (d2.get("ops"), d2.get("items")))
                    # 收尾：复位挂起态 + 清队列，避免污染后续人工测试
                    p2._toggle_pending_pause(False)
                    p2._clear_pending_queue()
                    finish()

                QTimer.singleShot(1500, check2)

            QTimer.singleShot(2500, check)
            QTimer.singleShot(4200, step_h_queue_ops)

        def finish():
            if STATE["done"]:
                return
            STATE["done"] = True
            try:
                p = panel()
                if p is not None:
                    pm = self.grab()
                    pm.save(os.path.join(
                        os.environ.get("TEMP", "."), "lw_gui_test.png"))
            except Exception:
                pass
            passed = sum(1 for _, ok, _ in RESULTS if ok)
            print("SUMMARY %d/%d PASS" % (passed, len(RESULTS)), flush=True)
            QApplication.instance().quit()

        QTimer.singleShot(4000, step_a)
        QTimer.singleShot(6000, step_b_send)
        QTimer.singleShot(60000, lambda: (not STATE["done"]) and step_c_check())

    MIMOWindow.show = show
    runpy.run_path(os.path.join(ROOT, "standard_mode", "main.py"),
                   run_name="__main__")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    return 0 if RESULTS and passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
