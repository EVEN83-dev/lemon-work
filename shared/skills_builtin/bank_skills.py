# -*- coding: utf-8 -*-
"""★第405章 bank_skills —— AI Banking 业务技能包（六组场景）

双注册设计（第404章 ActionCard 架构的首次实战消费）：
  1) 注册为 SkillsRegistry 技能 → Agent 文字对话直接调用
  2) 注册为 ActionCardRegistry 动作 → Agent 生成操作卡按钮，用户点击执行
两条路都走 MockBank 真实落库，高危动作（转账/申购/取消订阅/挂失）带 confirm 门。

场景覆盖（赛题六项）：智能转账 / 账单分析 / 理财操作 / 卡片管理 / 订阅代扣 / 跨场景联动
（跨场景联动 = v6 Scheduler 定时任务引用本包动作，如"生日前2天订购鲜花"）
"""
from __future__ import annotations

from shared.mock_bank import get_mock_bank

try:
    from standard_mode.core.skills_registry import SkillDef, SkillResult
except ImportError:
    from core.skills_registry import SkillDef, SkillResult

ME = "ACC001"  # 演示主账户（沙盒固定）


def _b(x): return x // 100  # 分→元 显示


# ---------- 六组业务动作（供技能 handler 与 ActionCard handler 共用） ----------
def act_query_balance(params: dict) -> dict:
    r = get_mock_bank().query_balance(params.get("account_id") or ME)
    if r.get("success"):
        r["message"] = f"{r['owner']} 余额 {_b(r['balance'])} 元（冻结 {_b(r['frozen'])} 元）"
    return r


def act_transfer(params: dict) -> dict:
    to = params.get("to") or ""
    # ★第418章: 收款人簿（姓名→账号）——对话里用户说姓名，银行核心要账号。
    # 未知收款人返回明确错误（含可用名单），agent 可据此向用户澄清而非盲目重试。
    payees = {"妈妈": "ACC002", "房东": "ACC003", "李雷": "ACC004", "王芳": "ACC005"}
    acc = payees.get(to, to)
    if not acc:
        return {"success": False, "error": ("收款人不能为空。可用收款人："
                + "、".join(payees) + "，或提供对方账号（ACC00x）")}
    if acc not in payees.values() and not acc.startswith("ACC"):
        return {"success": False, "error": (f"收款人 '{acc}' 不存在。可用收款人："
                + "、".join(payees) + "，或提供对方账号（ACC00x）")}
    r = get_mock_bank().transfer(ME, acc or "", int(params.get("amount", 0)),
                                 note=params.get("note", "对话转账"),
                                 idem_key=params.get("idem_key"))
    if r.get("success"):
        if "amount" in r:  # 新转账路径
            r["message"] = (f"已向 {to or acc} 转账 {_b(r['amount'])} 元，"
                            f"余额 {_b(r.get('balance_after', 0))} 元")
        # 幂等命中路径已有 message（重复请求拦截提示）
    return r


def act_bill_analyze(params: dict) -> dict:
    r = get_mock_bank().bill_analyze(params.get("account_id") or ME)
    if r.get("success"):
        cats = "、".join(f"{k} {_b(v)}元" for k, v in r["by_category"].items())
        r["message"] = (f"共 {r['tx_count']} 笔支出合计 {_b(r['total_expense'])} 元；"
                        f"分类：{cats}；最大头：{r['top_category']}")
    return r


def act_lock_deposit(params: dict) -> dict:
    r = get_mock_bank().lock_deposit(ME, int(params.get("amount", 0)),
                                     params.get("prod_id", "P001"))
    if r.get("success"):
        r["message"] = r.get("message", "申购完成")
    return r


def act_list_products(params: dict) -> dict:
    r = get_mock_bank().list_products()
    if r.get("success"):
        r["message"] = "；".join(f"{i['name']}({i['term']}) {i['annual_rate']}% 风险{i['risk_level']}"
                                 for i in r["items"])
    return r


def act_list_subscriptions(params: dict) -> dict:
    r = get_mock_bank().list_subscriptions(ME)
    if r.get("success"):
        r["message"] = "；".join(f"#{i['sub_id']} {i['merchant']} {_b(i['amount'])}元/{i['cycle']}"
                                 for i in r["items"]) or "无订阅"
    return r


def act_cancel_subscription(params: dict) -> dict:
    return get_mock_bank().cancel_subscription(int(params.get("sub_id", 0)))


def act_card_lost(params: dict) -> dict:
    return get_mock_bank().report_card_lost(params.get("card_no", ""))


# ---------- ★P0 专业层动作（风控/审计/冲正/试算/赎回/报告/订阅识别） ----------
def act_bill_report(params: dict) -> dict:
    r = get_mock_bank().bill_report(params.get("account_id") or ME)
    return r


def act_compound(params: dict) -> dict:
    return get_mock_bank().compound_interest(
        int(params.get("amount", 0)), float(params.get("rate", 3.0)),
        int(params.get("days", 90)))


def act_reverse(params: dict) -> dict:
    return get_mock_bank().reverse_transfer(int(params.get("tx_id", 0)),
                                            params.get("reason", "用户发起"))


def act_unlock(params: dict) -> dict:
    return get_mock_bank().unlock_deposit(ME, int(params.get("amount", 0)),
                                          params.get("prod_id", "P001"))


def act_risk_profile(params: dict) -> dict:
    return get_mock_bank().set_risk_profile(ME, int(params.get("score", 0)))


def act_risk_events(params: dict) -> dict:
    return get_mock_bank().list_risk_events(ME)


def act_audit_log(params: dict) -> dict:
    return get_mock_bank().get_audit_log(ME)


def act_detect_subs(params: dict) -> dict:
    r = get_mock_bank().detect_subscriptions(ME)
    if r.get("success"):
        r["message"] = "识别到疑似订阅: " + ("；".join(
            f"{i['merchant']}×{i['hits']}" for i in r["items"]) or "暂无重复扣费商户")
    return r


# ---------- 注册入口 ----------
def register_bank_skills(ui_callback=None) -> dict:
    """注册六组技能 + 八个 ActionCard 动作（幂等覆盖式，可重复调用）"""
    reg_ac = __import__("shared.action_cards", fromlist=["get_action_card_registry"]) \
        .get_action_card_registry()

    confirm_actions = {
        "bank.transfer": (act_transfer, True, "向联系人转账"),
        "bank.lock_deposit": (act_lock_deposit, True, "申购/锁定活期理财"),
        "bank.cancel_subscription": (act_cancel_subscription, True, "取消订阅"),
        "bank.card_lost": (act_card_lost, True, "卡片挂失"),
    }
    normal_actions = {
        "bank.query_balance": (act_query_balance, False, "查询账户余额"),
        "bank.bill_analyze": (act_bill_analyze, False, "账单分类统计"),
        "bank.list_products": (act_list_products, False, "理财产品列表"),
        "bank.list_subscriptions": (act_list_subscriptions, False, "订阅/代扣列表"),
        # ★P0 专业层
        "bank.bill_report": (act_bill_report, False, "专业账单报告(环比/预测/建议)"),
        "bank.compound": (act_compound, False, "收益试算(日复利/银行家舍入)"),
        "bank.risk_profile": (act_risk_profile, False, "风险评估问卷(1-5级)与产品匹配"),
        "bank.risk_events": (act_risk_events, False, "风控事件查询"),
        "bank.audit_log": (act_audit_log, False, "操作审计日志"),
        "bank.detect_subs": (act_detect_subs, False, "交易流自动识别订阅商户"),
        "bank.unlock": (act_unlock, True, "理财赎回"),
        "bank.reverse": (act_reverse, True, "交易冲正"),
    }
    for aid, (h, cf, desc) in {**confirm_actions, **normal_actions}.items():
        reg_ac.register_action(aid, h, confirm=cf, description=desc)

    if ui_callback is not None:
        reg_ac.set_ui_callback(ui_callback)

    bank = get_mock_bank()

    def _wrap(fn, schema, desc, example):
        # ★v357 桥接修复: 技能框架以 handler(**model_kwargs) 调用，而本文件
        #   P12 期 handler 签名是 fn(params: dict) 单参 —— 直传导致
        #   "unexpected keyword argument / missing params"（S3 理财 5 连败根因）。
        #   统一签名适配：单 dict 参 handler 自动包一层 kwargs→dict。
        import inspect as _inspect
        h = fn
        try:
            sig = _inspect.signature(fn)
            _has_var_kw = any(p.kind == _inspect.Parameter.VAR_KEYWORD
                              for p in sig.parameters.values())
            _pos = [p for p in sig.parameters.values()
                    if p.kind in (_inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                  _inspect.Parameter.POSITIONAL_ONLY)]
            if not _has_var_kw and len(_pos) == 1:
                h = (lambda f: (lambda **kw: f(kw)))(fn)
        except (TypeError, ValueError):
            pass
        return SkillDef(name=schema["name"], description=desc, parameters=schema,
                        handler=h, category="bank", timeout=10,
                        argcheck_example=example)

    skills_defs = [
        _wrap(act_query_balance,
              {"name": "bank_query_balance", "type": "object",
               "properties": {"account_id": {"type": "string"}},
               "required": []},
              "查询模拟银行账户余额（AI Banking 沙盒）",
              {"account_id": "ACC001"}),
        _wrap(act_transfer,
              {"name": "bank_transfer", "type": "object",
               "properties": {"to": {"type": "string"}, "amount": {"type": "integer"},
                              "note": {"type": "string"}},
               "required": ["to", "amount"]},
              "智能转账（按联系人姓名或账户号，元→分自动换算前请确认单位为分）。高危需确认。",
              {"to": "妈妈", "amount": 50000, "note": "生活费"}),
        _wrap(act_bill_analyze,
              {"name": "bank_bill_analyze", "type": "object", "properties": {}, "required": []},
              "账单分析：消费分类统计与最大头（月度/年度报告数据源）", {}),
        _wrap(act_lock_deposit,
              {"name": "bank_lock_deposit", "type": "object",
               "properties": {"amount": {"type": "integer"}, "prod_id": {"type": "string"}},
               "required": ["amount"]},
              "理财申购：锁定金额至产品（高危需确认）。产品列表用 bank_list_products",
              {"amount": 100000, "prod_id": "P001"}),
        _wrap(act_list_products,
              {"name": "bank_list_products", "type": "object", "properties": {}, "required": []},
              "理财产品对比列表（利率/期限/风险等级）", {}),
        _wrap(act_list_subscriptions,
              {"name": "bank_list_subscriptions", "type": "object", "properties": {}, "required": []},
              "列出全部订阅/代扣项（含续费时间）", {}),
        _wrap(act_cancel_subscription,
              {"name": "bank_cancel_subscription", "type": "object",
               "properties": {"sub_id": {"type": "integer"}}, "required": ["sub_id"]},
              "一键取消订阅（高危需确认）。先用 bank_list_subscriptions 查 sub_id",
              {"sub_id": 1}),
        _wrap(act_card_lost,
              {"name": "bank_card_lost", "type": "object",
               "properties": {"card_no": {"type": "string"}}, "required": ["card_no"]},
              "卡片挂失（高危需确认）", {"card_no": "6222 0000 0001"}),
        # ★P0 专业层八技能
        _wrap(act_bill_report,
              {"name": "bank_bill_report", "type": "object", "properties": {}, "required": []},
              "专业账单报告：分类+本月环比+年化预测+预算建议", {}),
        _wrap(act_compound,
              {"name": "bank_compound", "type": "object",
               "properties": {"amount": {"type": "integer"}, "rate": {"type": "number"},
                              "days": {"type": "integer"}}, "required": ["amount"]},
              "收益试算：日复利+银行家舍入。amount 单位为分", {"amount": 100000, "rate": 3.2, "days": 90}),
        _wrap(act_reverse,
              {"name": "bank_reverse", "type": "object",
               "properties": {"tx_id": {"type": "integer"}, "reason": {"type": "string"}},
               "required": ["tx_id"]},
              "交易冲正（高危）：原交易标记 reversed 并反向双写", {"tx_id": 9, "reason": "转错了"}),
        _wrap(act_unlock,
              {"name": "bank_unlock", "type": "object",
               "properties": {"amount": {"type": "integer"}, "prod_id": {"type": "string"}},
               "required": ["amount"]},
              "理财赎回（高危）：冻结金额转回活期", {"amount": 8000}),
        _wrap(act_risk_profile,
              {"name": "bank_risk_profile", "type": "object",
               "properties": {"score": {"type": "integer"}}, "required": ["score"]},
              "风险评估问卷（1-5级）→ KYC 存档 + 可投产品匹配", {"score": 3}),
        _wrap(act_risk_events,
              {"name": "bank_risk_events", "type": "object", "properties": {}, "required": []},
              "查询风控事件（大额/夜间/高频拦截与留痕记录）", {}),
        _wrap(act_audit_log,
              {"name": "bank_audit_log", "type": "object", "properties": {}, "required": []},
              "查询操作审计日志（金融合规 trail）", {}),
        _wrap(act_detect_subs,
              {"name": "bank_detect_subs", "type": "object", "properties": {}, "required": []},
              "从交易流自动聚合识别订阅商户（自动识别订阅扣费）", {}),
    ]

    try:
        from standard_mode.core.skills_registry import get_skills_registry
    except ImportError:
        from core.skills_registry import get_skills_registry
    skills = get_skills_registry()
    for sd in skills_defs:
        skills.register(sd)

    # 注册后实测可发现（证据先于判断，沿第404章纪律）
    names = set()
    try:
        for d in skills.get_tool_definitions():
            names.add((d.get("function") or {}).get("name") or d.get("name") or "")
    except Exception:
        pass
    expect = [sd.name for sd in skills_defs]
    missing = [n for n in expect if n not in names]

    return {"success": not missing,
            "skills": len(skills_defs),
            "actions": len(confirm_actions) + len(normal_actions),
            "error": "" if not missing else f"schema 未发现: {missing}"}

