#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lemon Work · 假实现/空连接审计

比对三组契约，找出"前端调了但后端没有"或"后端发了但前端不接"的断点：
  1. 前端 _callPython('Xxx', ...) 调用  vs  PyBridge `elif method == 'Xxx'` 注册
  2. 后端 _safe_run_js 注入的 window.xxx 调用 vs 前端 JS/HTML 定义
  3. 后端 _emit_trace(kind) 事件 vs TraceRenderer case 'kind' 分派
  4. HTML onclick 假按钮
"""
import re
import sys

UI = r"D:\YH-lemon\LemonWork\standard_mode\ui"
PANEL = UI + r"\mimo_panel.py"
APPJS = UI + r"\mimo_app.js"
PAGEHTML = UI + r"\mimo_page.html"

Q = "['\"]"  # 引号类（两种引号都匹配）


def read(p):
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def main():
    panel = read(PANEL)
    appjs = read(APPJS)
    html = read(PAGEHTML)
    # mimo_core.js / svg_icons.js 也是运行时定义源
    import os
    corejs = os.path.join(UI, "mimo_core.js")
    core = read(corejs) if os.path.exists(corejs) else ""
    issues = []

    # ── 1. _callPython 方法名差集 ──
    pat_call = "_callPython\\(\\s*" + Q + "([A-Za-z_]\\w*)" + Q
    js_calls = set(re.findall(pat_call, appjs))
    js_calls |= set(re.findall(pat_call, html))
    # sendMessage 是 PyBridge 基础槽（不走 elif 分派），白名单
    js_calls.discard("sendMessage")
    pat_reg = "elif\\s+method\\s*==\\s*" + Q + "([A-Za-z_]\\w*)" + Q
    py_methods = set(re.findall(pat_reg, panel))
    miss_py = sorted(js_calls - py_methods)
    if miss_py:
        issues.append("[空连接-后端缺] 前端调用但 PyBridge 未注册: %s" % miss_py)
    unused_py = sorted(py_methods - js_calls)
    if unused_py:
        print("[提示-死注册] PyBridge 注册但前端无 _callPython 调用"
              "（可能经 sendMessage/__clear_pending__ 复用）: %s" % unused_py)

    # ── 2. _safe_run_js 注入的 window.xxx 调用差集 ──
    # 定义源 = appjs + html + corejs + panel（panel 的 _safe_run_js 注入字符串
    # 里也有 window.xxx = function 定义，如 __v6p4Render* 卡片）
    js_fns = set(re.findall(r"window\.([A-Za-z_]\w*)\s*=\s*(?:function|\w|\{)", appjs))
    js_fns |= set(re.findall(r"function\s+([A-Za-z_]\w*)\s*\(", appjs))
    js_fns |= set(re.findall(r"function\s+([A-Za-z_]\w*)\s*\(", core))
    # html 内联 <script> 的函数定义
    inline_scripts = "".join(re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>",
                                        html, re.S))
    js_fns |= set(re.findall(r"function\s+([A-Za-z_]\w*)\s*\(", inline_scripts))
    js_fns |= set(re.findall(r"window\.([A-Za-z_]\w*)\s*=\s*(?:function|\w|\{)", panel))
    html_fns = set(re.findall(
        "(?:onclick|onchange|oninput|onload)\\s*=\\s*" + Q + "([A-Za-z_]\\w*)\\(", html))
    raw_calls = set()
    for m in re.finditer(r"_safe_run_js\((.*?)\)\n", panel, re.S):
        seg = m.group(1)
        raw_calls |= set(re.findall(r"window\.([A-Za-z_]\w*)", seg))
    avail = js_fns | html_fns
    miss_fn = sorted(x for x in raw_calls if x not in avail)
    if miss_fn:
        issues.append("[空连接-前端缺] 后端 JS 注入调用但前端未定义: %s" % miss_fn)

    # ── 3. trace 事件差集 ──
    pat_emit = "_emit_trace\\(\\s*" + Q + "([a-z_]+)" + Q
    emits = set(re.findall(pat_emit, panel))
    cases = set(re.findall(Q + "([a-z_]+)" + Q + "\\s*:", appjs))
    miss_case = sorted(e for e in emits if e not in cases)
    if miss_case:
        issues.append("[空连接-事件] 后端 emit 但 TraceRenderer 无 case: %s" % miss_case)

    # ── 4. HTML onclick 假按钮（定义源含 corejs；'if(...)' 守卫式跳过）──
    miss_html = sorted(x for x in html_fns
                       if x not in js_fns and x != "if")
    if miss_html:
        issues.append("[假按钮] HTML onclick 但 JS 无定义: %s" % miss_html)

    print("=" * 62)
    if issues:
        for i in issues:
            print("X " + i)
        print("AUDIT: %d 类断点" % len(issues))
        return 1
    print("AUDIT PASS: 无空连接/假按钮/事件断点")
    return 0


if __name__ == "__main__":
    sys.exit(main())
