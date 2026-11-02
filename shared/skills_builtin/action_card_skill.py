# -*- coding: utf-8 -*-
"""★第404章 ui_action_card 技能 —— Agent 生成动态操作卡的入口（Skills 层）

用法（Agent 在对话中调用）：
    ui_action_card(
        title="理财助手",
        buttons=[
            {"label": "转账 500 元", "action": "bank.transfer", "params": {"to": "妈妈", "amount": 500}},
            {"label": "锁定 1000 活期", "action": "bank.lock_deposit", "params": {"amount": 1000}}
        ],
        note="点击按钮即可执行，高危操作需二次确认")

安全：buttons 里未注册的 action 直接剔除并在结果中说明（防伪造）；
      若全部无效则返回失败，不渲染空卡。
"""
from __future__ import annotations

from shared.action_cards import get_action_card_registry

try:
    from standard_mode.core.skills_registry import SkillDef, SkillResult
except ImportError:
    from core.skills_registry import SkillDef, SkillResult  # 兼容两种运行路径


def _ui_action_card(title: str, buttons: list, note: str = "") -> SkillResult:
    reg = get_action_card_registry()
    if not isinstance(buttons, list) or not buttons:
        return SkillResult(success=False, error="buttons 必须为非空数组")
    valid, dropped = [], []
    for b in buttons:
        if not isinstance(b, dict) or not b.get("action"):
            dropped.append(str(b)[:40])
            continue
        if not reg.has(b["action"]):
            dropped.append(b["action"])
            continue
        valid.append({"label": str(b.get("label") or b["action"])[:24],
                      "action": b["action"],
                      "params": b.get("params") if isinstance(b.get("params"), dict) else {}})
    if not valid:
        return SkillResult(success=False, error=(
            f"全部按钮的 action 均未注册，已拒绝渲染。无效项: {dropped}。"
            f"可用动作请调用 list_actions 查询（或提示用户先注册动作）"))
    card = reg.build_card(title, valid, note)
    emit = reg.emit_card(card)
    if not emit.get("success"):
        return SkillResult(success=False, error=emit.get("error", "渲染回调失败"))
    dropped_note = f"（已剔除未注册动作: {dropped}）" if dropped else ""
    return SkillResult(success=True,
                       output=f"已生成操作卡「{card['title']}」，含 {len(valid)} 个按钮{dropped_note}",
                       data=card)


def register_action_card_skill(ui_callback=None) -> dict:
    """注册技能到 SkillsRegistry，并可选注入 UI 渲染回调（幂等，覆盖式注册安全）"""
    reg = get_action_card_registry()
    if ui_callback is not None:
        reg.set_ui_callback(ui_callback)

    try:
        from standard_mode.core.skills_registry import get_skills_registry
    except ImportError:
        from core.skills_registry import get_skills_registry
    skills = get_skills_registry()

    skill = SkillDef(
        name="ui_action_card",
        description=("在对话中生成动态操作按钮卡（Generative UI）。用户只需说需求，"
                     "你把可执行操作渲染成按钮。buttons 中每个 action 必须逐字使用 "
                     "list_actions 返回的 action_id（点号风格，如 bank.query_balance），"
                     "不要用技能名（下划线风格）。未知 action 会被拒绝。高危动作自动带二次确认。"),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "卡片标题"},
                "buttons": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "按钮文字"},
                        "action": {"type": "string", "description": "已注册的动作ID"},
                        "params": {"type": "object", "description": "动作参数"}},
                    "required": ["label", "action"]},
                    "description": "按钮数组"},
                "note": {"type": "string", "description": "卡片说明文字（可选）"}},
            "required": ["title", "buttons"]},
        handler=_ui_action_card,
        category="ui",
        timeout=10,
        argcheck_example={"title": "理财助手",
                          "buttons": [{"label": "查询余额", "action": "bank.query_balance",
                                       "params": {}}]},
    )
    def _list_actions() -> SkillResult:
        acts = get_action_card_registry().list_actions()
        # ★第413章: 动作清单必须写进 output —— 此前清单只在 data 里，而引擎
        # _format_skill_result 对 list_actions 不展开 data → 模型回执只有一句
        # "当前已注册 N 个动作"，看不到任何 ID，只能拿技能名（下划线）盲猜
        # 动作 ID（点号）→ ui_action_card 白名单全拒 → 卡片 MISS（用户实测实锤）。
        lines = []
        for a in acts:
            if isinstance(a, dict):
                aid = a.get("action_id") or a.get("id") or ""
                desc = a.get("description") or ""
                cf = "需确认" if a.get("confirm") else "无需确认"
                lines.append(f"- {aid}（{desc}，{cf}）" if desc else f"- {aid}（{cf}）")
            else:
                lines.append(f"- {a}")
        listing = "\n".join(lines) if lines else "（无已注册动作）"
        return SkillResult(success=True,
                           output=(f"当前已注册 {len(acts)} 个动作。"
                                   f"生成卡片时 action 字段必须逐字使用以下 ID（含点号，勿用下划线）：\n{listing}"),
                           data={"actions": acts})

    helper = SkillDef(
        name="list_actions",
        description="列出当前所有可生成到操作卡上的已注册动作（action_id/是否需确认/说明）",
        parameters={"type": "object", "properties": {}},
        handler=_list_actions, category="ui", timeout=5)

    skills.register(skill)
    skills.register(helper)

    # 不信任 register 返回值——注册后实测可发现才算成功（证据先于判断）
    names = set()
    try:
        for d in skills.get_tool_definitions():
            names.add((d.get("function") or {}).get("name") or d.get("name") or "")
    except Exception:
        pass
    ok = "ui_action_card" in names and "list_actions" in names
    return {"success": ok,
            "skills": ["ui_action_card", "list_actions"],
            "error": "" if ok else "注册后 schema 发现失败"}

