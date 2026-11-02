#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lemon Work · 六大比赛场景「演示模式」（DeepSeek 实跑 · 慢节奏供截图/录屏）

与 gui_competition_test.py 同源，但：
  · 不做断言、不退出 —— 六个场景依序自动执行，每个场景完成后停留 12 秒供截图
  · 控制台打印进度横幅（含 GitHub 仓库链接）

覆盖赛题六场景：
  S1 智能转账 / S2 账单分析 / S3 理财操作 / S4 卡片管理 / S5 订阅代扣 / S6 跨场景联动

用法：双击 D:\\YH-lemon\\演示六大场景.bat
"""
from __future__ import annotations

import importlib.util
import os
import runpy
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BANNER = r"""
================================================================
   Lemon Work · 六大比赛场景演示（DeepSeek 驱动）
   仓库: https://github.com/EVEN83-dev/lemon-work
   节奏: 每场景完成后停留 12 秒 —— 请抓紧截图 / 录屏
================================================================
"""

spec = importlib.util.spec_from_file_location(
    "yh_main_boot", os.path.join(ROOT, "yh_main.py"))
yh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(yh)
yh._ensure_bank_server()
yh._install_patch()

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from ui.main_window import MIMOWindow

STATE = {"idx": 0, "t0": 0.0}

# 与合规测试同源的六场景指令（含"切到 xx 页"验证页面跟随联动）
TASKS = [
    ("S1 智能转账",
     "用数字银行查一下李雷的收款账号，并从主账户 ACC001 给他转 66 元，备注比赛测试；"
     "如果支持定时转账，再预约明天给 ACC003 转 200 元。办完把界面切到转账页。"),
    ("S2 账单分析",
     "分析我的账单消费情况：统计消费分类，并识别有没有异常交易，"
     "结论做成表格。然后切到个人中心展示。"),
    ("S3 理财操作",
     "给我推荐理财产品并对比一下风险等级，选最稳健的一款申购 500 元。"
     "完成后把银行界面切到基金页。"),
    ("S4 卡片管理",
     "帮我管理一下银行卡：把主账户卡设置单笔交易限额 5000 元，"
     "并告诉我当前卡片状态。办完切到个人中心。"),
    ("S5 订阅代扣",
     "查一下我名下有哪些订阅扣费，把最贵的一个一键取消订阅，"
     "然后把界面切到个人中心给我看办事单。"),
    ("S6 跨场景联动",
     "我朋友陈奕汐生日快到了：在银行商城订一束鲜花（下单即可不用真送），"
     "然后把界面切到个人中心让我看到这笔订单。"),
]

SNAP_JS = (
    "(function(){var runs=document.querySelectorAll('.agent-run');"
    "var run=runs[runs.length-1];if(!run)return '{}';"
    "var r={final:run.querySelector('.trace-final')?1:0,final_len:0};"
    "var fb=run.querySelector('.trace-final .tf-body');"
    "if(fb){r.final_len=(fb.textContent||'').length;}"
    "return JSON.stringify(r);})()")


def log(msg: str):
    print("[DEMO] " + msg, flush=True)


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
            log("数字银行健康检查 http://127.0.0.1:8090/api/health ...")
            import requests
            try:
                r = requests.get("http://127.0.0.1:8090/api/health",
                                 timeout=3, proxies={"http": None, "https": None})
                log("银行在线 version=%s" % r.json().get("version", "?"))
            except Exception as e:
                log("银行健康检查异常（看门狗会自愈）: %s" % str(e)[:60])
            run_task()

        def run_task():
            if STATE["idx"] >= len(TASKS):
                finish()
                return
            label, prompt = TASKS[STATE["idx"]]
            STATE["label"] = label
            STATE["t0"] = time.time()
            p = panel()
            if p is None:
                QTimer.singleShot(2000, run_task)
                return
            log("=" * 64)
            log("场景 %d/6 开始：%s" % (STATE["idx"] + 1, label))
            log("=" * 64)
            try:
                p._send_via_agent_chat(prompt, engine_id="deepseek")
            except Exception as e:
                log("注入失败，跳过: %s" % str(e)[:60])
                STATE["idx"] += 1
                QTimer.singleShot(1500, run_task)
                return
            QTimer.singleShot(4000, lambda: wait_final())

        def wait_final():
            p = panel()
            if p is None:
                QTimer.singleShot(4000, wait_final)
                return
            p.web_view.page().runJavaScript(SNAP_JS, lambda res: on_snap(res))

        def on_snap(res):
            try:
                d = {}
                if isinstance(res, str) and res:
                    import json as _json
                    d = _json.loads(res)
            except Exception:
                d = {}
            if d.get("final") and int(d.get("final_len") or 0) > 30:
                label = STATE.get("label", "?")
                # 自动留证：窗口截图存到 D:\YH-lemon\素材\（供技术文档/答辩使用）
                try:
                    shot_dir = os.path.join(os.path.dirname(ROOT), "素材")
                    os.makedirs(shot_dir, exist_ok=True)
                    fn = os.path.join(shot_dir, "auto_S%d.png" % (STATE["idx"] + 1))
                    self.grab().save(fn)
                    log("已保存截图: " + fn)
                except Exception as e:
                    log("截图失败: %s" % str(e)[:50])
                log("场景完成【%s】耗时 %ds —— 停留 12 秒供截图/录屏"
                    % (label, int(time.time() - STATE["t0"])))
                STATE["idx"] += 1
                QTimer.singleShot(12000, run_task)
                return
            if time.time() - STATE["t0"] > 150:
                log("场景超时（150s），继续下一个")
                STATE["idx"] += 1
                QTimer.singleShot(1500, run_task)
                return
            QTimer.singleShot(4000, wait_final)

        def finish():
            log("=" * 64)
            log("六大场景演示全部完成！")
            log("仓库: https://github.com/EVEN83-dev/lemon-work")
            log("窗口保持打开 —— 可继续手动体验 / 截图 / 录屏")
            log("=" * 64)

        QTimer.singleShot(8000, step_start)

    MIMOWindow.show = show
    log(BANNER)
    runpy.run_path(os.path.join(ROOT, "standard_mode", "main.py"),
                   run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
