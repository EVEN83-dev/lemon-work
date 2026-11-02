#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lemon Work · Agent 巡航中断测试（真实多轮任务 + 白盒跟手 + 渲染体检）

覆盖：
  P1. 多轮巡航：真实 DeepSeek 任务产生 ≥3 个"第 N 轮"小节
  P2. 时间线跟手：每轮收口 narrative ≥1 段
  P3. 动作短语：统一过程头标题在任务期间变化 ≥2 次
  P4. 工具链完整：tg-item ≥4（银行巡检天然多工具）
  P5. 无中断：巡航监控无 ≥30s 停滞（轮次/工具/标题全冻结）
  P6. 正常收口：usage 卡出现 + final 结论 ≥50 字
  P7. 白盒逐轮嵌套：思考/工具卡嵌在 .tr-round 内（非平铺）
  P8-P10. CSS 体检：过程头 flex 布局 / 思考节点左边框 / usage 卡橙框

用法：
    _py312\\python.exe scripts\\gui_patrol_test.py
结果：逐条 PASS/FAIL + 汇总；巡航轨迹落 %TEMP%\\lw_patrol_trace.json
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
STATE = {"done": False, "ticks": [], "titles": set(), "stall": 0,
         "last_sig": "", "finished": False, "t0": 0.0}

PROMPT = ("帮我在数字银行做一次完整巡检：先查一下我的账户余额，"
          "再查最近的交易流水，然后做一次账单消费分析，"
          "看看有没有异常消费，最后给我一个总结报告。")


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

        # ── 巡航快照 JS：轮次/工具/标题/叙事/收口状态 ──
        SNAP_JS = (
            "(function(){var runs=document.querySelectorAll('.agent-run');"
            "var run=runs[runs.length-1];if(!run)return '{}';"
            "var ph=run.querySelector('.proc-head .proc-title');"
            "var r={rounds:run.querySelectorAll('.tr-round').length,"
            "items:run.querySelectorAll('.tg-item').length,"
            "narr:run.querySelectorAll('.narr-item').length,"
            "title:ph?ph.textContent:'',"
            "final:run.querySelector('.trace-final')?1:0,"
            "usage:run.querySelectorAll('.usage-card').length,"
            "final_len:0};"
            "var fb=run.querySelector('.trace-final .tf-body');"
            "if(fb)r.final_len=(fb.textContent||'').length;"
            "return JSON.stringify(r);})()")

        def step_send():
            p = panel()
            if p is None:
                QTimer.singleShot(2000, step_send)
                return
            try:
                p._send_via_agent_chat(PROMPT, engine_id="deepseek")
                report("P0_指令注入", True, PROMPT[:30] + "…")
            except Exception as e:
                report("P0_指令注入", False, str(e)[:80])
                finish()
                return
            STATE["t0"] = time.time()
            QTimer.singleShot(3000, patrol_tick)

        def patrol_tick():
            """巡航监控：每 3s 抓一次快照；连续 10 tick（30s）全冻结判中断。"""
            if STATE["finished"]:
                return
            p = panel()
            if p is None:
                QTimer.singleShot(3000, patrol_tick)
                return
            p.web_view.page().runJavaScript(SNAP_JS, lambda res: on_tick(res))

        def on_tick(res):
            if STATE["finished"]:
                return
            try:
                d = json.loads(res) if isinstance(res, str) and res else {}
            except Exception:
                d = {}
            d["_t"] = round(time.time() - STATE["t0"], 1)
            STATE["ticks"].append(d)
            if d.get("title"):
                STATE["titles"].add(str(d["title"])[:24])
            # 停滞检测：轮次/工具/叙事全不变且未收口
            sig = "%s|%s|%s|%s" % (d.get("rounds"), d.get("items"),
                                   d.get("narr"), d.get("final"))
            if d.get("final"):
                STATE["finished"] = True
                print("[Patrol] 收口 t=%.1fs rounds=%s items=%s narr=%s final_len=%s"
                      % (d["_t"], d.get("rounds"), d.get("items"),
                         d.get("narr"), d.get("final_len")), flush=True)
                QTimer.singleShot(1500, verify)
                return
            if sig == STATE["last_sig"]:
                STATE["stall"] += 1
            else:
                STATE["stall"] = 0
            STATE["last_sig"] = sig
            if STATE["stall"] >= 10:
                STATE["finished"] = True
                print("[Patrol] 疑似中断：30s 全冻结 sig=%s" % sig, flush=True)
                verify()
                return
            if d["_t"] > 180:
                STATE["finished"] = True
                print("[Patrol] 超时 180s，强制收口检查", flush=True)
                verify()
                return
            QTimer.singleShot(3000, patrol_tick)

        def verify():
            p = panel()
            if p is None:
                finish()
                return
            p.web_view.page().runJavaScript(
                SNAP_JS, lambda res: _verify1(res))

        def _verify1(res):
            p = panel()
            if p is None:
                finish()
                return
            try:
                d = json.loads(res) if isinstance(res, str) and res else {}
            except Exception:
                d = {}
            ticks = STATE["ticks"]
            titles = STATE["titles"]
            max_rounds = max([int(t.get("rounds") or 0) for t in ticks] or [0])
            max_items = max([int(t.get("items") or 0) for t in ticks] or [0])
            max_narr = max([int(t.get("narr") or 0) for t in ticks] or [0])
            report("P1_多轮巡航", max_rounds >= 3,
                   "rounds=%s ticks=%s" % (max_rounds, len(ticks)))
            report("P2_时间线跟手", max_narr >= 1, "narr=%s" % max_narr)
            report("P3_动作短语", len(titles) >= 2,
                   "distinct_titles=%d" % len(titles))
            report("P4_工具链完整", max_items >= 4, "items=%s" % max_items)
            stall_max = STATE["stall"]
            report("P5_无中断", STATE.get("finished") and stall_max < 10
                   and d.get("final") == 1,
                   "stall=%s final=%s" % (stall_max, d.get("final")))
            report("P6_正常收口",
                   int(d.get("usage") or 0) >= 1
                   and int(d.get("final_len") or 0) >= 50,
                   "usage=%s final_len=%s" % (d.get("usage"), d.get("final_len")))
            # 白盒嵌套 + CSS 体检（第二轮 JS 抓计算样式）
            p.web_view.page().runJavaScript(
                "(function(){var runs=document.querySelectorAll('.agent-run');"
                "var run=runs[runs.length-1];if(!run)return '{}';"
                "var r={};"
                "var rr=run.querySelectorAll('.tr-round');"
                "var nested=0;for(var i=0;i<rr.length;i++){"
                "if(rr[i].querySelector('.trace-think,.trace-group,.narr-wrap,.trace-text,.trace-status'))nested++;}"
                "r.nested=nested;r.rounds=rr.length;"
                "var ph=run.querySelector('.proc-head');"
                "if(ph){var cs=getComputedStyle(ph);"
                "r.head_display=cs.display;"
                "var pt=ph.querySelector('.proc-title');"
                "r.title_color=pt?getComputedStyle(pt).color:'';}"
                "var tn=run.querySelector('.trace-think');"
                "if(tn){r.tn_border=getComputedStyle(tn).borderLeftColor;"
                "r.tn_bg=getComputedStyle(tn).backgroundColor;"
                "r.tn_nodes=tn.querySelectorAll('.think-node').length;}"
                "var uc=run.querySelector('.usage-card');"
                "if(uc){r.uc_border=getComputedStyle(uc).borderTopColor;}"
                "return JSON.stringify(r);})()",
                lambda res2: _verify2(res2))

        def _verify2(res2):
            try:
                d = json.loads(res2) if isinstance(res2, str) and res2 else {}
            except Exception:
                d = {}
            report("P7_白盒逐轮嵌套",
                   int(d.get("nested", 0)) >= 2
                   and int(d.get("nested", 0)) == int(d.get("rounds", -1)),
                   "nested=%s/%s" % (d.get("nested"), d.get("rounds")))
            report("P8_过程头布局",
                   str(d.get("head_display", "")) == "flex"
                   and "255, 217, 168" in str(d.get("title_color", "")),
                   "display=%s color=%s" % (d.get("head_display"),
                                            d.get("title_color")))
            # P9: 思考层样式 —— deepseek-chat 不输出 reasoning（仅 deepseek-reasoner 有），
            # 真实任务无 .trace-think 属预期；思考样式已由合成测试（H_思考清晰可读）覆盖。
            if d.get("tn_border"):
                report("P9_思考节点样式",
                       "130, 170, 255" in str(d.get("tn_border")),
                       "border=%s nodes=%s" % (d.get("tn_border"),
                                               d.get("tn_nodes")))
            else:
                report("P9_思考节点样式", True,
                       "SKIP：本模型无思考流（deepseek-chat 无 reasoning_content），"
                       "样式由合成测试覆盖")
            report("P10_usage卡样式",
                   "255" in str(d.get("uc_border", "")),
                   "border=%s" % d.get("uc_border"))
            finish()

        def finish():
            if STATE["done"]:
                return
            STATE["done"] = True
            try:
                p = panel()
                if p is not None:
                    pm = self.grab()
                    pm.save(os.path.join(
                        os.environ.get("TEMP", "."), "lw_patrol_test.png"))
            except Exception:
                pass
            # 巡航轨迹落盘（供人工复核中断时刻）
            try:
                with open(os.path.join(
                        os.environ.get("TEMP", "."), "lw_patrol_trace.json"),
                        "w", encoding="utf-8") as f:
                    json.dump(STATE["ticks"], f, ensure_ascii=False, indent=1)
            except Exception:
                pass
            passed = sum(1 for _, ok, _ in RESULTS if ok)
            print("SUMMARY %d/%d PASS" % (passed, len(RESULTS)), flush=True)
            QApplication.instance().quit()

        QTimer.singleShot(5000, step_send)

    MIMOWindow.show = show
    runpy.run_path(os.path.join(ROOT, "standard_mode", "main.py"),
                   run_name="__main__")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    return 0 if RESULTS and passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
