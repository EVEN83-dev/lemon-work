# -*- coding: utf-8 -*-
"""H8: 终端xterm fit字体度量标准化 — Python绑定"""
import os

TERM_FIT_JS_PATH = os.path.join(os.path.dirname(__file__), "term_fit_standard.js")


def get_fit_js():
    with open(TERM_FIT_JS_PATH, "r", encoding="utf-8") as f:
        return f.read()


def inject_fit_js(page):
    page.runJavaScript(get_fit_js())


def call_fit(page, terminal_id, container_id):
    js = (
        f"TermFitStandard.fit("
        f"document.getElementById('{terminal_id}'), "
        f"document.getElementById('{container_id}'));"
    )
    page.runJavaScript(js)
