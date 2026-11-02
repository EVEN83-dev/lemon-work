# -*- coding: utf-8 -*-
"""★第408章 web_capture —— 网页抓取与对话内净化显示（Generative UI 姊妹卡）

用户选型：网页在对话消息流内嵌显示（不开右侧网页框）。
方案：抓取 → 正文净化（去 script/style/nav，白名单标签）→ WebPageCard
     （标题+摘要+「在对话中展开」→ iframe srcdoc 沙箱渲染 + 原文外链）。
不直接 iframe 原站：多数站点 X-Frame-Options 拒绝内嵌，且脚本不可控。
"""
from __future__ import annotations

import html as _html
import re
import time
from typing import Dict

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 LemonAgent/1.0")
_ALLOWED_TAGS = re.compile(
    r"</?(?!(?:p|br|div|h[1-6]|ul|ol|li|table|tr|td|th|thead|tbody|strong|b|em|i|u|"
    r"blockquote|pre|code|span|a|img|hr|section|article)\b)[a-zA-Z][^>]*>", re.I)
_MAX_HTML = 60_000   # 净化 HTML 截断（防超大页面撑爆对话流）
_MAX_PREVIEW = 400


def fetch_page(url: str, timeout: int = 15) -> Dict:
    """抓取网页并净化。返回 {success, url, title, preview, clean_html, ...}"""
    if not url or not re.match(r"^https?://", url.strip(), re.I):
        return {"success": False, "error": "URL 必须以 http(s):// 开头"}
    url = url.strip()
    try:
        import requests
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=timeout,
                            allow_redirects=True, verify=True)
        resp.raise_for_status()
        if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1",):
            resp.encoding = resp.apparent_encoding or "utf-8"
        raw = resp.text
    except Exception as e:
        return {"success": False, "error": f"抓取失败: {type(e).__name__}: {e}"}

    # 标题
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    title = _html.unescape(m.group(1)).strip()[:120] if m else url

    # 去噪：script/style/iframe/noscript/header/footer/nav 整块删除
    cleaned = re.sub(r"<(script|style|iframe|noscript|svg|form|button|input|select"
                     r"|header|footer|nav|aside)[^>]*>.*?</\1>", " ", raw,
                     flags=re.I | re.S)
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.S)
    # 白名单外标签剥壳（保内容）
    cleaned = _ALLOWED_TAGS.sub("", cleaned)
    # 属性净化：仅保留 a[href] / img[src] 且剥离事件与协议
    cleaned = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", cleaned, flags=re.I)
    cleaned = re.sub(r"(href|src)\s*=\s*[\"'](javascript|data|vbscript):[^\"']*[\"']",
                     r'\1="#"', cleaned, flags=re.I)
    cleaned = re.sub(r"(target|rel)\s*=\s*[\"'][^\"']*[\"']", "", cleaned, flags=re.I)
    # 压缩空白
    cleaned = re.sub(r"\n\s*\n+", "\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()

    # 纯文本预览
    text = re.sub(r"<[^>]+>", " ", cleaned)
    text = re.sub(r"\s+", " ", text).strip()
    preview = text[:_MAX_PREVIEW] + ("…" if len(text) > _MAX_PREVIEW else "")

    if len(cleaned) > _MAX_HTML:
        cleaned = cleaned[:_MAX_HTML] + "<p>…（内容过长已截断，可打开原文查看全文）</p>"
    if len(text) < 30:
        return {"success": False, "error": "页面无可提取正文（可能为纯脚本页或反爬拦截）",
                "url": url, "title": title}

    return {"success": True, "url": url, "title": title,
            "preview": preview, "clean_html": cleaned,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "html_size": len(cleaned)}
