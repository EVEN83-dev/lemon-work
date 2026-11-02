# -*- coding: utf-8 -*-
"""★第408章 web_skills —— 网页预览卡（对话内显示，用户选型：不开侧栏）

Agent 调用 web_preview(url) → 抓取+净化 → WebPageCard 推送到消息流：
  标题 + 摘要 + [在对话中展开] 按钮 → iframe srcdoc 沙箱渲染净化 HTML
  + [打开原文] 外链。与 ActionCard/文件卡同族（第404章卡片家族）。
"""
from __future__ import annotations

try:
    from standard_mode.core.skills_registry import SkillDef, SkillResult
except ImportError:
    from core.skills_registry import SkillDef, SkillResult


def _web_preview(url: str) -> SkillResult:
    from shared.web_capture import fetch_page
    from shared.action_cards import get_action_card_registry
    r = fetch_page(url)
    if not r.get("success"):
        return SkillResult(success=False, error=r.get("error", "抓取失败"))
    card = {
        "type": "web_page_card",
        "card_id": f"wp_{int(time.time() * 1000)}",
        "url": r["url"], "title": r["title"], "preview": r["preview"],
        "clean_html": r["clean_html"], "fetched_at": r["fetched_at"],
    }
    emit = get_action_card_registry().emit_card(card)
    if not emit.get("success"):
        return SkillResult(success=False, error=emit.get("error", "渲染回调失败"))
    return SkillResult(success=True,
                       output=f"已抓取「{r['title']}」并生成对话内网页卡（摘要 {len(r['preview'])} 字，"
                              f"净化 HTML {r['html_size'] // 1024}KB，可在对话中展开阅读）",
                       data={"url": r["url"], "title": r["title"]})


import time  # noqa: E402  （卡片时间戳用）


def register_web_skills(ui_callback=None) -> dict:
    """注册 web_preview 技能；UI 回调复用 ActionCardRegistry 通道"""
    reg = __import__("shared.action_cards", fromlist=["get_action_card_registry"]) \
        .get_action_card_registry()
    if ui_callback is not None:
        reg.set_ui_callback(ui_callback)

    try:
        from standard_mode.core.skills_registry import get_skills_registry
    except ImportError:
        from core.skills_registry import get_skills_registry
    skills = get_skills_registry()

    skills.register(SkillDef(
        name="web_preview",
        description=("抓取网页并在对话中生成可展开阅读的网页卡（正文净化版，无需离开对话）。"
                     "用户说'打开/看看这个网页'时调用。失败会显式说明原因（反爬/超时等）。"),
        parameters={"type": "object",
                    "properties": {"url": {"type": "string", "description": "完整 URL"}},
                    "required": ["url"]},
        handler=_web_preview, category="web", timeout=20,
        argcheck_example={"url": "https://example.com"}))

    # 注册后实测可发现
    names = set()
    try:
        for d in skills.get_tool_definitions():
            names.add((d.get("function") or {}).get("name") or d.get("name") or "")
    except Exception:
        pass
    ok = "web_preview" in names
    return {"success": ok, "skills": ["web_preview"],
            "error": "" if ok else "注册后 schema 发现失败"}
