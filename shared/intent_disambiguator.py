# -*- coding: utf-8 -*-
"""第441章 intent_disambiguator —— 银行指令的模糊表达 / 省略 / 隐含意图消歧

赛题依据（三、3 意图理解与任务规划）：
  "支持模糊表达、省略上下文、隐含意图的识别；复杂任务需拆解为有序子任务 DAG"

设计原则：
  · 规则优先、可解释：每条判定给出命中的规则名与理由，便于答辩逐条说明
  · 不猜测危险动作：缺金额/缺收款人时一律追问，绝不"猜一个数就去转"
  · 上下文补全：从会话记忆（上次收款人/上次金额/最近订阅）补齐省略信息
  · 疑问句不执行：'能不能转' 属可行性咨询，返回 inquire 而非转账

输出契约：
  {"intent","slots","need_clarify","question","missing","rule","confidence","safe_to_execute"}
"""
from __future__ import annotations

import re

# 隐含意图映射（命中即映射到具体动作，但仍受权限分级约束）
IMPLICIT_RULES = [
    (r"(这个月|本月|上个月).*(花|消费|支出|开销)", "bank_bill_analyze", "账单分析"),
    (r"(年|年度).*(账单|消费|支出)", "bank_bill_report", "年度账单报告"),
    (r"(余额|还有多少钱|剩多少)", "bank_query_balance", "余额查询"),
    (r"(理财|基金|存款).*(有什么|推荐|哪个好|对比)", "bank_list_products", "理财产品列表"),
    (r"(订阅|会员|自动续费).*(哪些|多少|列表|查)", "bank_list_subscriptions", "订阅列表"),
    (r"(收益|利息).*(算|试算|多少)", "bank_compound", "收益试算"),
    (r"(风控|风险).*(事件|记录|拦截)", "bank_risk_events", "风控事件"),
    (r"(审计|操作记录|日志)", "bank_audit_log", "审计日志"),
]

# 疑问句 / 可行性咨询（不执行）
INQUIRY_RULES = [
    r"(能不能|可不可以|可以吗|能转吗|可以转)",
    r"(额度|限额).*(是多少|多少)",
    r"(安全吗|有风险吗)",
]

# 模糊金额表达
VAGUE_AMOUNT = r"(一点|一些|点钱|打点|转点|随便|适量|多少都|看着给)"

# 模糊收款人 / 指代
VAGUE_PAYEE = r"(他|她|上次那个|老地方|还是那个|原来那个|同一个人)"

# 全量表达（高危）
VAGUE_ALL = r"(全部|全转|都转|清空|所有钱)"

PAYEES = {
    "妈妈": "ACC002", "房东": "ACC003", "李雷": "ACC004", "王芳": "ACC005",
}


def _extract_amount(text: str):
    """抽取金额：支持 '500元' / '500块' / '五百'（数字形式）/ '50'"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|块钱|rmb|RMB)?", text)
    if m:
        try:
            return int(float(m.group(1)) * 100)   # 元 → 分
        except Exception:
            return None
    return None


def _extract_payee(text: str):
    for name in PAYEES:
        if name in text:
            return name, PAYEES[name]
    m = re.search(r"(ACC\d+)", text, re.I)
    if m:
        return m.group(1), m.group(1).upper()
    return None, None


def parse(text: str, context: dict | None = None) -> dict:
    """解析一句银行指令，返回意图、槽位与是否需要追问。

    context 可用键：
      last_payee（上次收款人姓名）、last_amount_fen（上次金额，分）、
      last_subscription（上次订阅商户名）
    """
    ctx = dict(context or {})
    raw = (text or "").strip()
    out = {
        "raw": raw, "intent": None, "slots": {}, "need_clarify": False,
        "question": None, "missing": [], "rule": None,
        "confidence": 0.0, "safe_to_execute": False,
    }

    if not raw:
        out.update(need_clarify=True, question="请说明您想办理什么业务", rule="empty_input")
        return out

    # ① 可行性咨询优先：疑问句不执行
    for pat in INQUIRY_RULES:
        if re.search(pat, raw):
            out.update(intent="inquire", rule="inquiry", confidence=0.8,
                       safe_to_execute=False,
                       question="这是一次可行性咨询。若确认办理，请给出金额与收款人，我将按权限等级执行。")
            return out

    # ② 转账意图识别（含模糊表达）
    is_transfer = bool(re.search(r"(转账|转给|转点|打(?:点)?钱|汇款|转一下|"
                                r"给.{1,8}转|转\s*[\d一二两三四五六七八九十百千万])", raw))
    if is_transfer:
        out["intent"] = "bank_transfer"

        # 全量表达 → 高危追问
        if re.search(VAGUE_ALL, raw):
            out.update(rule="vague_all_amount", confidence=0.5,
                       question="“全部转出”属高风险操作，请明确具体金额（单笔超过 1000 元需强验证）。")
            out["need_clarify"] = True
            out["missing"].append("amount")
            return out

        # 收款人
        name, acc = _extract_payee(raw)
        if not acc and re.search(VAGUE_PAYEE, raw):
            last = ctx.get("last_payee")
            if last and last in PAYEES:
                name, acc = last, PAYEES[last]
                out["rule"] = "resolve_by_context"
            else:
                out["need_clarify"] = True
                out["missing"].append("payee")
                out.update(rule="vague_payee_no_context",
                           question="您说的“他/上次那个”是指谁？可用收款人：" + "、".join(PAYEES))
                return out
        if not acc:
            out["need_clarify"] = True
            out["missing"].append("payee")
            out.update(rule="missing_payee",
                       question="请告诉我要转给谁。可用收款人：" + "、".join(PAYEES) +
                                "，或提供账号（ACC00x）")
            return out

        # 金额
        amt = _extract_amount(raw.replace(name or "", ""))
        if amt is None and re.search(VAGUE_AMOUNT, raw):
            out["need_clarify"] = True
            out["missing"].append("amount")
            out.update(rule="vague_amount",
                       question="您要转多少元？请给出具体金额（例如“转 50 元”）。")
            return out
        if amt is None:
            last_amt = ctx.get("last_amount_fen")
            if isinstance(last_amt, int) and last_amt > 0 and re.search(r"(还是|和上次|老样子)", raw):
                amt = last_amt
                out["rule"] = "resolve_amount_by_context"
            else:
                out["need_clarify"] = True
                out["missing"].append("amount")
                out.update(rule="missing_amount", question="请告诉我要转多少元？")
                return out

        out["slots"] = {"to": name or acc, "account_id": acc, "amount": amt}
        out["confidence"] = 0.9
        out["safe_to_execute"] = True
        out["rule"] = out["rule"] or "explicit_transfer"
        return out

    # ③ 订阅取消（含指代）
    if re.search(r"(取消|退订|关掉).*(会员|订阅|自动续费)", raw):
        out["intent"] = "bank_cancel_subscription"
        m = re.search(r"#?(\d+)", raw)
        if m:
            out["slots"] = {"sub_id": int(m.group(1))}
            out["safe_to_execute"] = True
            out["confidence"] = 0.85
            out["rule"] = "explicit_sub_id"
        else:
            last = ctx.get("last_subscription")
            out["need_clarify"] = True
            out["missing"].append("sub_id")
            out.update(rule="vague_subscription",
                       question=("要取消哪一个？" +
                                 ("上次提到的是「%s」。" % last if last else
                                  "请先查询订阅列表（“我的订阅有哪些”）再指定编号。")))
        return out

    # ④ 挂失
    if re.search(r"((挂失|丢了|找不到).*(卡|银行卡)|(卡|银行卡).*(丢了|找不到|挂失))", raw):
        out.update(intent="bank_card_lost", rule="card_lost", confidence=0.8,
                   slots={}, need_clarify=True, missing=["card_no"],
                   question="请提供要挂失的卡号（如 6222 0000 0001）。挂失需强验证后执行。")
        return out

    # ⑤ 隐含意图（账单/理财/订阅/余额等）
    for pat, action, label in IMPLICIT_RULES:
        if re.search(pat, raw):
            out.update(intent=action, rule="implicit:" + label, confidence=0.75,
                       safe_to_execute=True, slots={})
            return out

    # ⑥ 兜底
    out.update(rule="unrecognized", need_clarify=True,
               question="没能理解您的意图。我可以帮您：查余额、转账、看账单、查理财、管订阅、挂失卡片。")
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    cases = [
        ("给妈妈转500元", {}, "明确转账"),
        ("给妈妈转点钱", {}, "模糊金额"),
        ("转500元", {}, "缺收款人"),
        ("还是转给上次那个，老样子", {"last_payee": "房东", "last_amount_fen": 150000}, "上下文补全"),
        ("全转给他", {}, "全量高危"),
        ("能不能转2000元给房东", {}, "可行性咨询"),
        ("这个月钱都花哪了", {}, "隐含-账单"),
        ("理财有什么推荐的", {}, "隐含-产品"),
        ("帮我取消那个会员", {}, "订阅指代"),
        ("我的卡丢了", {}, "挂失缺卡号"),
        ("帮我看看余额", {}, "隐含-余额"),
        ("", {}, "空输入"),
    ]
    print("=" * 74)
    print("  意图消歧自检")
    print("=" * 74)
    for text, ctx, label in cases:
        r = parse(text, ctx)
        flag = "追问" if r["need_clarify"] else ("可执行" if r["safe_to_execute"] else "不执行")
        print("%-28s [%-4s] intent=%-24s %s" % (
            (text or "(空)")[:26], flag, r["intent"] or "-", r["rule"]))
        if r["question"]:
            print("      追问: %s" % r["question"][:60])
        if r["slots"]:
            print("      槽位: %s" % r["slots"])
    print("\n共 %d 例，全部按规则给出可解释判定。" % len(cases))
