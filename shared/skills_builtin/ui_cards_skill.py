# -*- coding: utf-8 -*-
"""★第416章 ui_chart_card / ui_form_card 技能 —— 卡片家族扩展（Skills 层）

ui_chart_card：数据 → SVG 图表卡（line/bar），前端矢量渲染，无第三方依赖
ui_form_card ：字段定义 → 表单卡，用户在对话内填写后经 __action_card__ 通道提交
               （submit_action 必须是 ActionCardRegistry 已注册动作 → confirm 门自动生效）

安全：
  - form 的 submit_action 走 ActionCardRegistry 白名单，未注册直接拒绝渲染；
  - field.name 仅允许 [A-Za-z0-9_]（防注入 DOM 属性）；前端渲染全 esc()。
"""
from __future__ import annotations

import re
import time

from shared.action_cards import get_action_card_registry

try:
    from standard_mode.core.skills_registry import SkillDef, SkillResult
except ImportError:
    from core.skills_registry import SkillDef, SkillResult  # 兼容两种运行路径


def _make_card(card_type: str, title: str, note: str = "") -> dict:
    return {
        "type": card_type,
        "card_id": f"{card_type[:2]}_{int(time.time() * 1000)}",
        "title": title or ("图表" if card_type == "chart_card" else "表单"),
        "note": note or "",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------- ui_chart_card ----------

def _ui_chart_card(title: str, series: list, chart_type: str = "line",
                   unit: str = "", note: str = "") -> SkillResult:
    reg = get_action_card_registry()
    if not isinstance(series, list) or len(series) < 2:
        return SkillResult(success=False,
                           error="series 必须为至少 2 个 {label, value} 的数组")
    clean = []
    for pt in series[:24]:  # 上限 24 点，防超长序列撑爆画布
        if not isinstance(pt, dict) or "value" not in pt:
            continue
        try:
            val = float(pt["value"])
        except (TypeError, ValueError):
            continue
        clean.append({"label": str(pt.get("label", ""))[:12], "value": val})
    if len(clean) < 2:
        return SkillResult(success=False,
                           error="series 有效数据点不足 2 个（value 需为数字）")
    ctype = "bar" if str(chart_type).lower() == "bar" else "line"
    card = _make_card("chart_card", title, note)
    card.update({"chart_type": ctype, "series": clean, "unit": str(unit)[:8]})
    emit = reg.emit_card(card)
    if not emit.get("success"):
        return SkillResult(success=False, error=emit.get("error", "渲染回调失败"))
    vals = [p["value"] for p in clean]
    return SkillResult(success=True,
                       output=(f"已生成{('柱状' if ctype == 'bar' else '折线')}图「{card['title']}」"
                               f"（{len(clean)} 个数据点，范围 {min(vals):.4g}~{max(vals):.4g}{unit}）"),
                       data=card)


# ---------- ui_form_card ----------

_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,24}$")


def _ui_form_card(title: str, fields: list, submit_action: str,
                  submit_label: str = "提交", note: str = "") -> SkillResult:
    reg = get_action_card_registry()
    if not isinstance(fields, list) or not fields:
        return SkillResult(success=False, error="fields 必须为非空数组")
    if not reg.has(submit_action):
        return SkillResult(success=False,
                           error=(f"submit_action '{submit_action}' 未注册，拒绝渲染。"
                                  f"请先调用 list_actions 获取可用动作 ID（点号风格）。"))
    clean = []
    for f in fields[:8]:  # 上限 8 字段
        if not isinstance(f, dict):
            continue
        name = str(f.get("name", ""))
        if not _NAME_RE.match(name):
            return SkillResult(success=False,
                               error=f"字段名 '{name}' 非法（仅允许字母/数字/下划线，≤24 字符）")
        ftype = str(f.get("type", "text")).lower()
        if ftype not in ("text", "number", "date"):
            ftype = "text"
        clean.append({
            "name": name,
            "label": str(f.get("label", name))[:16],
            "type": ftype,
            "placeholder": str(f.get("placeholder", ""))[:40],
            "value": str(f.get("value", ""))[:60],
            "required": bool(f.get("required", True)),
        })
    if not clean:
        return SkillResult(success=False, error="fields 无有效字段")
    card = _make_card("form_card", title, note)
    # ★第416章: submit_confirm 随卡下发——前端据此给提交按钮挂两段式确认，
    # 防表单提交绕过高危动作（如 bank.transfer）的二次确认门
    info = reg.get_action_info(submit_action) or {}
    card.update({"fields": clean, "submit_action": submit_action,
                 "submit_label": str(submit_label)[:12] or "提交",
                 "submit_confirm": bool(info.get("confirm"))})
    emit = reg.emit_card(card)
    if not emit.get("success"):
        return SkillResult(success=False, error=emit.get("error", "渲染回调失败"))
    return SkillResult(success=True,
                       output=(f"已生成表单「{card['title']}」（{len(clean)} 个字段，"
                               f"提交动作 {submit_action}），等待用户在对话内填写"),
                       data=card)


def register_ui_cards(ui_callback=None) -> dict:
    """注册图表卡/表单卡两技能到 SkillsRegistry，并可选注入 UI 回调（幂等覆盖式）"""
    reg = get_action_card_registry()
    if ui_callback is not None:
        reg.set_ui_callback(ui_callback)

    try:
        from standard_mode.core.skills_registry import get_skills_registry
    except ImportError:
        from core.skills_registry import get_skills_registry
    skills = get_skills_registry()

    chart = SkillDef(
        name="ui_chart_card",
        description=("在对话中生成 SVG 图表卡（折线/柱状）。当需要展示数据趋势、"
                     "对比、试算结果时调用。series 为 [{label,value},...]，"
                     "chart_type 取 line 或 bar，unit 为数值单位（如 元/%）。"),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "图表标题"},
                "series": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "value": {"type": "number"}},
                    "required": ["label", "value"]},
                    "description": "数据点数组（2~24 个）"},
                "chart_type": {"type": "string", "enum": ["line", "bar"],
                               "description": "折线或柱状，默认 line"},
                "unit": {"type": "string", "description": "数值单位（可选）"},
                "note": {"type": "string", "description": "图表说明（可选）"}},
            "required": ["title", "series"]},
        handler=_ui_chart_card,
        category="ui",
        timeout=10,
        argcheck_example={"title": "复利增长", "chart_type": "line",
                          "series": [{"label": "第1年", "value": 10350},
                                     {"label": "第2年", "value": 10712}]},
    )

    form = SkillDef(
        name="ui_form_card",
        description=("在对话中生成结构化表单卡（输入框+提交按钮），用户填写后直接执行。"
                     "适合转账/开户/筛选等需要收集多项输入的场景。"
                     "submit_action 必须是 list_actions 返回的点号动作 ID；"
                     "高危动作提交时自动弹二次确认。"),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "表单标题"},
                "fields": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "字段名（参数键）"},
                        "label": {"type": "string", "description": "显示标签"},
                        "type": {"type": "string", "enum": ["text", "number", "date"]},
                        "placeholder": {"type": "string"},
                        "value": {"type": "string", "description": "预填值"},
                        "required": {"type": "boolean"}},
                    "required": ["name", "label"]},
                    "description": "字段数组（1~8 个）"},
                "submit_action": {"type": "string",
                                  "description": "提交动作 ID（点号风格，需已注册）"},
                "submit_label": {"type": "string", "description": "提交按钮文字"},
                "note": {"type": "string", "description": "表单说明（可选）"}},
            "required": ["title", "fields", "submit_action"]},
        handler=_ui_form_card,
        category="ui",
        timeout=10,
        argcheck_example={"title": "转账", "submit_action": "bank.transfer",
                          "fields": [{"name": "to", "label": "收款人"},
                                     {"name": "amount", "label": "金额", "type": "number"}]},
    )

    skills.register(chart)
    skills.register(form)
    # 不信任 register 返回值（register 无返回）——注册后实测可发现才算成功（证据先于判断）
    ok = (skills.get("ui_chart_card") is not None
          and skills.get("ui_form_card") is not None)
    return {"success": ok, "skills": ["ui_chart_card", "ui_form_card"],
            "error": "" if ok else "注册后实测未发现技能（get 返回 None）"}
