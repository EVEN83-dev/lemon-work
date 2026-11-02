# -*- coding: utf-8 -*-
"""★第420章 remote_bank_* 技能包 —— Agent 以 HTTP 服务形态对接独立数字银行
═══════════════════════════════════════════════════════════════════════
架构定位（用户明确要求）：
    用户 → Lemon Agent（对话/卡片） --HTTP API--> 数字银行沙箱（独立服务 :8090）
                              ↑
                    Web 操作台（银行侧实时可见）

· 本技能包的全部数据来自 **HTTP 调用独立数字银行服务**——不是进程内 mock_bank，
  不是硬编码假数据（用户明确拒绝）。
· 银行未启动时返回明确的连接失败信息（含启动指引），**绝不静默回退**到本地模拟。
· 金额单位：对外（LLM/用户）用"元"，对银行 API 用"分"（×100）。
· 服务地址：环境变量 REMOTE_BANK_URL 覆盖，默认 http://127.0.0.1:8090。
"""
from __future__ import annotations

import os

try:
    from standard_mode.core.skills_registry import SkillDef, SkillResult
except ImportError:
    from core.skills_registry import SkillDef, SkillResult  # 兼容两种运行路径

import requests

DEFAULT_URL = os.environ.get("REMOTE_BANK_URL", "http://127.0.0.1:8090")
_TIMEOUT = 10


def _base_url() -> str:
    return os.environ.get("REMOTE_BANK_URL", DEFAULT_URL).rstrip("/")


_NO_PROXY = {"http": None, "https": None}  # ★第432章: 本地服务直连——系统代理（梯子/抓包）会吞掉 127.0.0.1 请求导致挂起


def _call(method: str, path: str, body: dict | None = None) -> SkillResult:
    """统一 HTTP 调用入口：连接失败/HTTP错误/业务失败三层显式暴露。

    ★ success 语义：银行响应带 success 字段按其值；health/menu 等无该字段的
      探测型响应默认视为成功（420 验证修正）。
    ★第432章: trust_env=False + proxies=None——绕过系统代理直连本地银行
      （用户真机"执行中卡死"的最可疑外因：代理吞掉 127.0.0.1 请求）。
    """
    url = _base_url() + path
    try:
        resp = requests.request(method, url, json=body, timeout=_TIMEOUT,
                                headers={"Content-Type": "application/json"},
                                proxies=_NO_PROXY)
    except requests.exceptions.ConnectionError:
        return SkillResult(success=False, error=(
            f"数字银行服务未连接（{_base_url()} 拒绝连接）。"
            f"请先在数字银行目录启动服务：python server.py"))
    except requests.exceptions.Timeout:
        return SkillResult(success=False, error=f"数字银行响应超时（>{_TIMEOUT}s）: {path}")
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", "")
        except Exception:
            detail = resp.text[:120]
        return SkillResult(success=False, error=f"数字银行 HTTP {resp.status_code}: {detail}")
    data = resp.json()
    return SkillResult(success=bool(data.get("success", True)),
                       output=str(data.get("message") or data.get("error") or "已完成"),
                       data=data)


def _yuan_to_fen(x) -> int:
    return int(round(float(x) * 100))


# ---------- handlers（★签名统一 **params：SkillsRegistry.execute 以 kwargs 展开（skills_registry L396 handler(**args)）） ----------

def h_health() -> SkillResult:
    return _call("GET", "/api/health")


def h_accounts() -> SkillResult:
    r = _call("GET", "/api/accounts")
    if r.success and isinstance(r.data, dict):
        r.output = "、".join(f"{a['owner']}({a['account_id']}) 余额 {a['balance_yuan']} 元"
                             for a in r.data.get("items", []))
    return r


def h_balance(**params) -> SkillResult:
    aid = (params.get("account_id") or "").strip()
    return _call("GET", f"/api/accounts/{aid}" if aid else "/api/accounts/ACC001")


def h_transfer(**params) -> SkillResult:
    to = str(params.get("to") or params.get("account_id") or "").strip()
    amount = params.get("amount")
    if not to or amount in (None, ""):
        return SkillResult(success=False,
                           error="转账需要 to（收款账号，可先调 remote_bank_accounts 查户名对应账号）和 amount（元）")
    return _call("POST", "/api/transfer", {
        "to": to, "amount": _yuan_to_fen(amount),
        "note": str(params.get("note", "对话转账")),
        "idem_key": params.get("idem_key"),
    })


def h_reverse(**params) -> SkillResult:
    tx_id = params.get("tx_id")
    if tx_id in (None, ""):
        return SkillResult(success=False,
                           error="冲正需要 tx_id（交易号，可先调 remote_bank_transactions 查询）")
    return _call("POST", "/api/reverse",
                 {"tx_id": int(tx_id), "reason": str(params.get("reason", "对话发起"))})


def h_transactions(**params) -> SkillResult:
    aid = (params.get("account_id") or "").strip()
    limit = int(params.get("limit", 20))
    q = f"?limit={limit}" + (f"&account={aid}" if aid else "")
    r = _call("GET", f"/api/transactions{q}")
    # ★第434章: 条目组装进 output（此前只有"已完成"——条目在 data 里被
    #   _format_skill_result 忽略，agent/用户都看不到流水内容，413 章同款坑）
    if r.success and isinstance(r.data, dict):
        items = r.data.get("items", [])
        r.output = f"交易流水 {len(items)} 条（最新在前）：" + \
                   "；".join(f"#{t['tx_id']} {t.get('ts', '')} "
                             f"{t['from_acc']}→{t['to_acc']} "
                             f"{t.get('amount_yuan', '?')}元 "
                             f"[{t.get('status', '')}] {t.get('note', '')}"
                             for t in items)
    return r


def h_audit(**params) -> SkillResult:
    r = _call("GET", f"/api/audit?limit={int(params.get('limit', 30))}")
    # ★第434章: 同上——审计条目组装进 output（含操作/参数/结果，可追溯）
    if r.success and isinstance(r.data, dict):
        items = r.data.get("items", [])
        r.output = f"审计日志 {len(items)} 条（最新在前）：" + \
                   "；".join(f"#{a['id']} {a.get('ts', '')} "
                             f"[{a.get('account_id', '')}] {a.get('action', '')} "
                             f"{str(a.get('params', ''))[:40]} → {a.get('result', '')}"
                             for a in items)
    return r


def h_risk_events(**params) -> SkillResult:
    return _call("GET", f"/api/risk-events?limit={int(params.get('limit', 30))}")


def h_reconcile() -> SkillResult:
    return _call("POST", "/api/reconcile", {})


def h_compound(**params) -> SkillResult:
    return _call("POST", "/api/compound", {
        "principal": float(params.get("principal", 0)),
        "annual_rate": float(params.get("annual_rate", 0)),
        "days": int(params.get("days", 0))})


def h_products() -> SkillResult:
    return _call("GET", "/api/products")


def h_subscriptions(**params) -> SkillResult:
    aid = (params.get("account_id") or "ACC001").strip()
    return _call("GET", f"/api/subscriptions?account={aid}")


def h_menu() -> SkillResult:
    """服务发现：抓取数字银行支持的全部可选操作（开放银行能力清单）。"""
    r = _call("GET", "/api/menu")
    if r.success and isinstance(r.data, dict):
        r.output = "数字银行支持 " + str(len(r.data.get("items", []))) + " 项操作：" + \
                   "；".join(o["name"] + "(" + o["method"] + " " + o["path"] + ")"
                             for o in r.data.get("items", []))
    return r


# ---------- ★第421章 贷款融资 / 基金 / 股票 ----------

def h_loan_list(**params) -> SkillResult:
    return _call("GET", "/api/loans")


def h_loan_apply(**params) -> SkillResult:
    amount = params.get("amount")
    if amount in (None, ""):
        return SkillResult(success=False, error="贷款申请需要 amount（元）")
    return _call("POST", "/api/loans/apply", {
        "amount": float(amount),
        "term_months": int(params.get("term_months", 12))})


def h_loan_repay(**params) -> SkillResult:
    if not params.get("loan_id"):
        return SkillResult(success=False, error="还款需要 loan_id（可先调 remote_loan_list 查询）")
    return _call("POST", f"/api/loans/{int(params['loan_id'])}/repay",
                 {"amount": float(params.get("amount", 0))})


def h_fund_list(**params) -> SkillResult:
    r = _call("GET", "/api/funds")
    if r.success and isinstance(r.data, dict):
        r.output = "基金超市 " + str(len(r.data.get("items", []))) + " 只：" + \
                   "；".join(f"{f['name']}({f['code']}) {f['type']} 净值 {f['nav']}"
                             f" 近7日{f['week_pct']:+}%"
                             for f in r.data.get("items", []))
    return r


def h_fund_buy(**params) -> SkillResult:
    code = str(params.get("code") or "").strip()
    amount = params.get("amount")
    if not code or amount in (None, ""):
        return SkillResult(success=False,
                           error="基金申购需要 code（基金代码，可先调 remote_fund_list 查询）和 amount（元）")
    return _call("POST", f"/api/funds/{code}/buy", {"amount": float(amount)})


def h_stock_list(**params) -> SkillResult:
    r = _call("GET", "/api/stocks")
    if r.success and isinstance(r.data, dict):
        r.output = "行情 " + str(len(r.data.get("items", []))) + " 只：" + \
                   "；".join(f"{s['name']}({s['code']}) {s['price']} 元 "
                             f"{'+' if s['change_pct'] >= 0 else ''}{s['change_pct']}%"
                             for s in r.data.get("items", []))
    return r


def h_stock_kline(**params) -> SkillResult:
    code = str(params.get("code") or "").strip()
    if not code:
        return SkillResult(success=False, error="K线查询需要 code（股票代码，可先调 remote_stock_list）")
    return _call("GET", f"/api/stocks/{code}/kline?bars={int(params.get('bars', 60))}")


def h_stock_trade(**params) -> SkillResult:
    code = str(params.get("code") or "").strip()
    side = str(params.get("side") or "buy").lower()
    shares = int(params.get("shares", 0))
    if not code or shares <= 0:
        return SkillResult(success=False,
                           error="股票委托需要 code（股票代码）与 shares（股数，100 整数倍）；side 取 buy/sell")
    return _call("POST", f"/api/stocks/{code}/{side}", {"shares": shares})


def h_holdings(**params) -> SkillResult:
    return _call("GET", "/api/holdings")


def h_bank_events(**params) -> SkillResult:
    """★第436章 银行动态事件流 + 时钟状态：日切/利息/到期兑付/自动扣费实时留痕。"""
    r = _call("GET", f"/api/bank-events?limit={int(params.get('limit', 12))}")
    sim = _call("GET", "/api/sim")
    if r.success and isinstance(r.data, dict):
        items = r.data.get("items", [])
        head = (f"银行日第 {sim.data.get('sim_day')} 天（{sim.data.get('mode')}，"
                f"每 {sim.data.get('seconds_per_day')} 秒切一日）｜" if sim.success else "")
        r.output = head + f"动态事件 {len(items)} 条（最新在前）：" + \
                   "；".join(f"[{e['kind']}] {e['detail']}" for e in items)
    return r


def h_deposits(**params) -> SkillResult:
    """★第436章 定期存款清单（含到期倒计时）。"""
    aid = (params.get("account_id") or "").strip()
    q = f"?account={aid}" if aid else ""
    r = _call("GET", f"/api/deposits{q}")
    if r.success and isinstance(r.data, dict):
        items = r.data.get("items", [])
        r.output = (f"银行日第 {r.data.get('sim_day')} 天｜定期存款 {len(items)} 笔：" +
                    "；".join(f"#{d['deposit_id']} {d['account_id']} {d.get('amount_yuan')} 元 "
                              f"年化{d['rate']}% {d['term_days']}天 "
                              f"{d['status']}" + (f"（剩 {d['days_left']} 日到期）"
                                                  if d.get('days_left') is not None else "")
                              for d in items))
    return r


def h_social(**params) -> SkillResult:
    """★第437章 社会服务总览：工资/个税/社保/公积金/公共事业/收单/房租七口径累计
    + 对公机构主体 + 近期社会资金事件——回答'社会层面发生了什么'。"""
    r = _call("GET", "/api/social")
    corp = _call("GET", "/api/corp-accounts")
    if r.success and isinstance(r.data, dict) and isinstance(r.data.get("stats"), dict):
        s = r.data["stats"]
        y = lambda fen: f"{fen / 100:.2f}"
        head = "社会服务累计｜" + "；".join(f"{k} {y(v)} 元" for k, v in s.items())
        if corp.success and isinstance(corp.data, dict):
            head += "｜对公/机构 " + "；".join(
                f"{c['owner']}({c['account_id']},{c['acc_type']}) 余额 {c['balance_yuan']} 元"
                for c in corp.data.get("items", []))
        recent = r.data.get("recent", [])[:4]
        if recent:
            head += "｜近期：" + "；".join(f"[{e['kind']}]{e['detail'][:40]}" for e in recent)
        r.output = head
    return r


# ---------- ★第438章 AI Banking 六场景技能 ----------

def h_find_account(**params) -> SkillResult:
    r = _call("GET", f"/api/accounts/find?q={params.get('query', '')}")
    if r.success and isinstance(r.data, dict):
        items = r.data.get("items", [])
        r.output = (f"{r.data.get('message')}：" +
                    "；".join(f"{i['owner']}({i['account_id']}，{i.get('phone', '')})"
                              for i in items) if items else r.data.get("message"))
    return r


def h_schedule_transfer(**params) -> SkillResult:
    to = str(params.get("to") or "").strip()
    amount = params.get("amount")
    after = params.get("after_days", 1)
    if not to or amount in (None, ""):
        return SkillResult(success=False,
                           error="定时转账需要 to（收款账号）和 amount（元）、after_days（几个银行日后执行）")
    return _call("POST", "/api/transfers/schedule", {
        "to": to, "amount": _yuan_to_fen(amount),
        "after_days": int(after), "note": str(params.get("note", "定时转账"))})


def h_aa_collect(**params) -> SkillResult:
    members = params.get("members") or []
    amount_each = params.get("amount_each")
    if not members or amount_each in (None, ""):
        return SkillResult(success=False,
                           error="AA 收款需要 members（参与人账号列表，如 ['ACC004','ACC005']）"
                                 "和 amount_each（每人金额·元）")
    return _call("POST", "/api/transfer/aa", {
        "members": members, "amount_each": _yuan_to_fen(amount_each),
        "note": str(params.get("note", ""))})


def h_bill_analysis(**params) -> SkillResult:
    aid = (params.get("account_id") or "ACC001").strip()
    s = _call("GET", f"/api/bill/summary?account={aid}")
    a = _call("GET", f"/api/bill/anomalies?account={aid}")
    if not s.success:
        return s
    d = s.data or {}
    cats = "；".join(f"{c['kind']} {c['net'] / 100:+.2f} 元"
                     for c in d.get("categories", [])[:8])
    out = (f"账单分析（{aid}）：{s.data.get('message')}｜分类：{cats}")
    if a.success and isinstance(a.data, dict):
        out += f"｜异常识别：{a.data.get('message')}"
        for x in a.data.get("items", [])[:3]:
            out += f"；#{x['tx_id']} {'/'.join(x['flags'])}"
    return SkillResult(success=True, output=out, data={"summary": d})


def h_wealth_advisor(**params) -> SkillResult:
    """风险评估+产品推荐二合一：带 answers 先评估，无 answers 直接按已存等级推荐。"""
    aid = (params.get("account_id") or "ACC001").strip()
    answers = params.get("answers")
    head = ""
    if answers:
        ra = _call("POST", "/api/risk-assess", {"from": aid, "answers": answers})
        head = (ra.data.get("risk_level", "") + "｜") if ra.success and ra.data else ""
        if not ra.success:
            return ra
    r = _call("GET", f"/api/products/recommend?account={aid}")
    if r.success and isinstance(r.data, dict):
        items = r.data.get("items", [])
        head += f"{r.data.get('message')}："
        head += "；".join(f"{p['name']}({p['prod_id']}) 年化{p['annual_rate']}% "
                          f"风险R{p['risk_level']} 万元90天收益约 "
                          f"{p.get('yuan_1w_90d_interest', 0)} 元"
                          for p in items)
        r.output = head
    return r


def h_card_manage(**params) -> SkillResult:
    """卡片管理六合一：list/apply/limit/restrict/unrestrict/loss。"""
    action = str(params.get("action") or "list").lower()
    if action == "list":
        r = _call("GET", "/api/cards")
        if r.success and isinstance(r.data, dict):
            items = r.data.get("items", [])
            r.output = (f"名下 {len(items)} 张卡：" +
                        "；".join(f"{c['card_no']} [{c['status']}] 额度 "
                                  f"{int(c['limit_amount']) / 100:.2f} 元" for c in items))
        return r
    if action == "apply":
        return _call("POST", "/api/cards/apply", {})
    card_no = str(params.get("card_no") or "").strip()
    if not card_no:
        return SkillResult(success=False,
                           error="请提供 card_no（可先 action=list 查询名下卡号）")
    value = params.get("value")
    body = {"action": action}
    if value not in (None, ""):
        body["value"] = _yuan_to_fen(value) if action == "limit" else value
    return _call("POST", f"/api/cards/{card_no}", body)


def h_subscription_cancel(**params) -> SkillResult:
    sid = params.get("sub_id")
    if sid in (None, ""):
        lst = _call("GET", "/api/subscriptions")
        if lst.success and isinstance(lst.data, dict):
            items = [x for x in lst.data.get("items", []) if x.get("status", "active") == "active"]
            lst.output = ("当前有效订阅：" + "；".join(
                f"#{x['id']} {x['merchant']} {int(x['amount']) / 100:.2f} 元/期"
                for x in items)
                + "（说『取消订阅 #编号』即可退订）") if items else "当前无有效订阅"
        return lst
    return _call("POST", f"/api/subscriptions/{int(sid)}/cancel", {})


def h_mall(**params) -> SkillResult:
    item_id = str(params.get("item_id") or "").strip()
    if not item_id:
        r = _call("GET", "/api/mall/items")
        if r.success and isinstance(r.data, dict):
            r.output = ("商城商品：" + "；".join(
                f"{i['item_id']} {i['name']} {i['price_yuan']} 元" for i in r.data.get("items", []))
                + "（说『订购 M001』即可下单）")
        return r
    return _call("POST", "/api/mall/order", {"item_id": item_id,
                                             "note": str(params.get("note", ""))})


def h_console(**params) -> SkillResult:
    """★第424/428章: 在对话内实时呈现数字银行操作台（live 活页嵌入卡）。

    双向互动形态：iframe 直连银行服务——页面自带 JS 照常运行（3s 轮询实时刷新），
    用户可在界面里手动操作，Agent 通过 remote_bank_* 技能执行的操作也会
    实时反映在界面上（余额/流水/风控同步变动）。
    宿主 LocalContentCanAccessRemoteUrls=True 已开启（mimo_panel L1298），
    live iframe 的加载依赖该设置。
    """
    r = _call("GET", "/api/health")
    print(f"[Agent-DIAG] console: health ok={r.success}", flush=True)  # ★第433章 分段取证
    if not r.success:
        return r  # 银行离线时透传明确错误
    import time as _t
    from shared.action_cards import get_action_card_registry  # 局部导入（与 register 同模式）
    card = {
        "type": "web_page_card",
        "card_id": f"live_{int(_t.time() * 1000)}",
        "title": "数字银行操作台（实时互动）",
        "url": _base_url() + "/",
        "live": True,
        "note": ("上屏为银行实时界面（双向互动）：你可以直接在界面里点按钮操作；"
                 "也可以让我代你操作（转账/贷款/基金/股票），界面会实时刷新。"
                 "若界面空白请告知我，我会改用快照方式呈现。"),
        "ts": _t.strftime("%Y-%m-%d %H:%M:%S"),
    }
    reg_ac = get_action_card_registry()
    emit = reg_ac.emit_card(card)
    print(f"[Agent-DIAG] console: emit ok={emit.get('success')} card_id={card['card_id']}", flush=True)
    if not emit.get("success"):
        return SkillResult(success=False, error=emit.get("error", "渲染回调失败"))
    acc = h_accounts()  # ★走增强版 handler（output 含户名/余额摘要）
    acc_text = acc.output if acc.success else ""
    return SkillResult(success=True,
                       output=(f"已在对话中呈现数字银行实时操作台（双向互动：界面手动可操作，"
                               f"我的操作也会实时反映到界面）。当前账户：{acc_text}"),
                       data={"type": "web_page_card", "url": card["url"], "live": True})


def h_navigate(**params) -> SkillResult:
    """★v356: 主动指挥银行操作台页面跳动（切页/滚动/高亮/提示）。

    Agent 在"向用户演示"场景下调用：如办完转账后主动把界面切到转账页、
    滚到流水表并高亮。视图与 panel 自动映射共用同一 /api/ui/state 总线。"""
    view = str(params.get("view") or "").strip()
    highlight = str(params.get("highlight") or "").strip()
    msg = str(params.get("msg") or "").strip()
    if not view:
        return SkillResult(success=False,
                           error="view 不能为空（可选: home/bank/mine/fund/stock/loan/ops/social）")
    try:
        import requests as _rq
        r = _rq.post(_base_url() + "/api/ui/state",
                     json={"view": view, "highlight": highlight, "msg": msg},
                     timeout=4, proxies={"http": None, "https": None})
        if r.status_code != 200:
            return SkillResult(success=False, error=f"HTTP {r.status_code}")
        return SkillResult(
            success=True,
            output=(f"已指挥银行操作台跳转：视图={view}"
                    + (f"，高亮={highlight}" if highlight else "")
                    + (f"，提示「{msg}」" if msg else "")
                    + "（页面将在 1.5 秒内自动切换并滚动到位）"),
            data={"view": view, "highlight": highlight})
    except Exception as e:
        return SkillResult(success=False, error=str(e)[:120])


# ---------- 注册 ----------

# (name, handler, description, params, category, timeout)
_DEFS = [
    ("remote_bank_health", h_health,
     "探测数字银行服务是否在线（对接健康检查）。",
     {}, "connect", 5),
    ("remote_bank_accounts", h_accounts,
     "获取数字银行全部账户及余额（含户名与账号对照——转账前先调它确定收款账号）。",
     {}, "bank", 10),
    ("remote_bank_query_balance", h_balance,
     "查询数字银行指定账户余额（不填默认主账户 ACC001）。",
     {"type": "object", "properties": {
         "account_id": {"type": "string", "description": "账户 ID，如 ACC001"}},
      "required": []}, "bank", 10),
    ("remote_bank_transfer", h_transfer,
     "通过数字银行 HTTP API 发起转账。to 必须是账号（如 ACC002，可先调 remote_bank_accounts 查户名对照）；"
     "amount 单位为元。风控/余额校验在银行服务端执行，失败会返回具体原因。",
     {"type": "object", "properties": {
         "to": {"type": "string", "description": "收款账号 ACC00x"},
         "amount": {"type": "number", "description": "金额（元）"},
         "note": {"type": "string", "description": "备注"},
         "idem_key": {"type": "string", "description": "幂等键（可选）"}},
      "required": ["to", "amount"]}, "bank", 15),
    ("remote_bank_reverse", h_reverse,
     "冲正撤销数字银行的一笔已成功交易（双向回滚），需要 tx_id 交易号。",
     {"type": "object", "properties": {
         "tx_id": {"type": "integer", "description": "交易号"},
         "reason": {"type": "string", "description": "冲正原因"}},
      "required": ["tx_id"]}, "bank", 15),
    ("remote_bank_transactions", h_transactions,
     "获取数字银行交易流水（可按账户过滤）。",
     {"type": "object", "properties": {
         "account_id": {"type": "string"}, "limit": {"type": "integer"}},
      "required": []}, "bank", 10),
    ("remote_bank_audit", h_audit,
     "获取数字银行操作审计日志（每笔操作留痕，合规可追溯）。",
     {"type": "object", "properties": {"limit": {"type": "integer"}},"required": []}, "bank", 10),
    ("remote_bank_risk_events", h_risk_events,
     "获取数字银行风控事件（拦截记录/风险等级/规则详情）。",
     {"type": "object", "properties": {"limit": {"type": "integer"}},"required": []}, "bank", 10),
    ("remote_bank_reconcile", h_reconcile,
     "触发数字银行对账：校验全部账户 账面余额 ≡ 种子初值+净额（守恒证明）。",
     {}, "bank", 10),
    ("remote_bank_compound", h_compound,
     "调用数字银行复利试算（Decimal 日复利·银行家舍入）：principal 元 / annual_rate % / days 天。",
     {"type": "object", "properties": {
         "principal": {"type": "number", "description": "本金（元）"},
         "annual_rate": {"type": "number", "description": "年利率（%）"},
         "days": {"type": "integer", "description": "存款天数"}},
      "required": ["principal", "annual_rate", "days"]}, "bank", 10),
    ("remote_bank_products", h_products,
     "获取数字银行理财产品列表（年化/风险等级/期限）。",
     {}, "bank", 10),
    ("remote_bank_subscriptions", h_subscriptions,
     "获取数字银行订阅/自动扣费列表。",
     {"type": "object", "properties": {"account_id": {"type": "string"}},"required": []}, "bank", 10),
    ("remote_bank_menu", h_menu,
     "抓取数字银行服务菜单（开放银行能力清单——本行支持的全部可选操作及其参数）。",
     {}, "bank", 10),
    # ---- ★第421章 贷款融资 / 基金 / 股票 ----
    ("remote_loan_list", h_loan_list,
     "查询数字银行贷款记录（本金/利率/剩余本金/状态）。",
     {}, "bank", 10),
    ("remote_loan_apply", h_loan_apply,
     "申请贷款（融资）。银行按账户余额×3+流水活跃度综合授信；通过即放款入账。"
     "授信不足会被拒绝并返回评估额度。",
     {"type": "object", "properties": {
         "amount": {"type": "number", "description": "申请金额（元）"},
         "term_months": {"type": "integer", "description": "期限（月，默认12）"}},
      "required": ["amount"]}, "bank", 15),
    ("remote_loan_repay", h_loan_repay,
     "归还数字银行贷款本息（需要 loan_id，可先调 remote_loan_list）。",
     {"type": "object", "properties": {
         "loan_id": {"type": "integer"}, "amount": {"type": "number", "description": "还款金额（元）"}},
      "required": ["loan_id", "amount"]}, "bank", 10),
    ("remote_fund_list", h_fund_list,
     "获取数字银行基金超市（货币/债券/混合/股票/指数型，最新净值与近7日涨跌）。",
     {}, "bank", 10),
    ("remote_fund_buy", h_fund_buy,
     "申购数字银行基金（按最新净值折算份额）。code 可先调 remote_fund_list 查询。",
     {"type": "object", "properties": {
         "code": {"type": "string", "description": "基金代码，如 NF0003"},
         "amount": {"type": "number", "description": "申购金额（元）"}},
      "required": ["code", "amount"]}, "bank", 10),
    ("remote_stock_list", h_stock_list,
     "获取数字银行虚拟股市行情快照（现价/涨跌幅/今开/最高/最低/成交量）。",
     {}, "bank", 10),
    ("remote_stock_kline", h_stock_kline,
     "获取数字银行虚拟股票日 K 线 OHLCV 序列（确定性可复现，近 bars 个交易日）。",
     {"type": "object", "properties": {
         "code": {"type": "string", "description": "股票代码，如 LM600001"},
         "bars": {"type": "integer", "description": "K 线根数（默认60）"}},
      "required": ["code"]}, "bank", 10),
    ("remote_stock_trade", h_stock_trade,
     "数字银行虚拟股票市价委托（side=buy/sell；须 100 股整数倍；按最新收盘价成交）。",
     {"type": "object", "properties": {
         "code": {"type": "string"}, "shares": {"type": "integer"},
         "side": {"type": "string", "enum": ["buy", "sell"]}},
      "required": ["code", "shares"]}, "bank", 10),
    ("remote_bank_holdings", h_holdings,
     "查询数字银行综合持仓（基金份额 + 股票持仓及成本）。",
     {}, "bank", 10),
    # ---- ★第436章 动态银行 ----
    ("remote_bank_events", h_bank_events,
     "获取数字银行动态事件流与银行日时钟（日切/活期利息入账/定期到期兑付/订阅自动扣费/"
     "贷款计息——银行后台实时运转的留痕）。查询'银行最近发生了什么/有没有利息/到期了吗'时调用。",
     {"type": "object", "properties": {"limit": {"type": "integer"}},"required": []}, "bank", 10),
    ("remote_bank_deposits", h_deposits,
     "查询数字银行定期存款清单（本金/年化/期限/状态/到期倒计时——银行日节奏自动兑付）。",
     {"type": "object", "properties": {"account_id": {"type": "string"}},"required": []}, "bank", 10),
    ("remote_bank_social", h_social,
     "社会服务总览：代发工资/个税入库/社保/公积金/水电气代收/商户收单/房租七口径累计，"
     "含对公企业（柠檬科技/柚子商贸）与政府机构（税务/社保/公积金中心等）账户状态——"
     "回答'社会上发生了什么/工资发了没/税交了多少'时调用。",
     {}, "bank", 10),
    # ---- ★第438章 AI Banking 六场景 ----
    ("remote_find_account", h_find_account,
     "收款人检索：按人名/手机号/账号模糊定位（智能转账第一步——先检索确认收款人再转账）。",
     {"type": "object", "properties": {
         "query": {"type": "string", "description": "人名/手机号/账号关键词"}},
      "required": ["query"]}, "bank", 10),
    ("remote_transfer_schedule", h_schedule_transfer,
     "定时转账预约：N 个银行日后自动执行（日切引擎到期扣款）。",
     {"type": "object", "properties": {
         "to": {"type": "string"}, "amount": {"type": "number", "description": "元"},
         "after_days": {"type": "integer", "description": "几个银行日后（默认1）"},
         "note": {"type": "string"}},
      "required": ["to", "amount"]}, "bank", 10),
    ("remote_transfer_aa", h_aa_collect,
     "拆分AA收款：向多名成员各收一笔等额款项（聚餐/拼单分摊）。",
     {"type": "object", "properties": {
         "members": {"type": "array", "items": {"type": "string"},
                      "description": "参与人账号列表"},
         "amount_each": {"type": "number", "description": "每人金额（元）"},
         "note": {"type": "string"}},
      "required": ["members", "amount_each"]}, "bank", 15),
    ("remote_bill_analysis", h_bill_analysis,
     "账单分析：收支分类统计 + 异常交易识别（大额偏离/单日高频/风控命中）——"
     "用户要'看账单/分析消费/有没有异常'时调用。",
     {"type": "object", "properties": {
         "account_id": {"type": "string"}}, "required": []}, "bank", 10),
    ("remote_wealth_advisor", h_wealth_advisor,
     "理财顾问：风险评估（answers 为 1-5 分答案数组，可选）+ 按风险等级产品推荐"
     "（含万元 90 天复利预期收益对比）。",
     {"type": "object", "properties": {
         "answers": {"type": "array", "items": {"type": "integer"},
                      "description": "1-5 分风险问卷答案（可选，提供则先评估）"},
         "account_id": {"type": "string"}},
      "required": []}, "bank", 10),
    ("remote_card_manage", h_card_manage,
     "卡片管理：action=list 查卡/apply 申请新卡/limit 调额(需 value 元)/"
     "restrict 限制交易/unrestrict 解锁/loss 挂失。",
     {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "apply", "limit",
                                                "restrict", "unrestrict", "loss"]},
         "card_no": {"type": "string"}, "value": {"type": "number"}},
      "required": ["action"]}, "bank", 10),
    ("remote_subscription_cancel", h_subscription_cancel,
     "订阅管理：不带 sub_id 列出有效订阅；带 sub_id 一键取消（下期起不再扣费）。",
     {"type": "object", "properties": {
         "sub_id": {"type": "integer", "description": "订阅编号（可选）"}},
      "required": []}, "bank", 10),
    ("remote_mall", h_mall,
     "商城服务：不带 item_id 列出商品（鲜花/蛋糕/贺卡）；带 item_id 下单订购"
     "（生日前订鲜花蛋糕——跨场景联动的执行器）。",
     {"type": "object", "properties": {
         "item_id": {"type": "string", "description": "商品编号（可选，缺省=列表）"},
         "note": {"type": "string"}},
      "required": []}, "bank", 10),
    ("remote_bank_console", h_console,
     "在对话中实时呈现数字银行操作台（LIVE 活页卡：余额/流水随操作实时刷新）。"
     "用户想'看看银行界面/打开银行/连接银行'时调用本技能。",
     {}, "connect", 10),
    ("remote_bank_navigate", h_navigate,
     "指挥银行操作台页面跳动：切到指定页签并滚动高亮（home总览/bank转账与流水/"
     "mine个人中心/fund基金/stock股票/loan贷款/ops运营）。"
     "想在演示时让用户看清某个页面时调用。",
     {"type": "object", "properties": {
         "view": {"type": "string", "description": "目标页签: home/bank/mine/fund/stock/loan/ops/social"},
         "highlight": {"type": "string", "description": "要高亮滚动的区块元素 id（可选，如 bTx 流水表）"},
         "msg": {"type": "string", "description": "页面右上角浮动提示文案（可选）"}},
      "required": ["view"]}, "bank", 6),
]


def register_remote_bank_skills(ui_callback=None) -> dict:
    """注册 remote_bank_* 技能包到 SkillsRegistry（幂等覆盖式）。

    ui_callback 可选注入（与其它 builtin 包一致）；未注入时沿用
    ActionCardRegistry 里已有的回调（生产由 register_action_card_skill 先行注入）。
    """
    try:
        from standard_mode.core.skills_registry import get_skills_registry
    except ImportError:
        from core.skills_registry import get_skills_registry
    skills = get_skills_registry()
    if ui_callback is not None:
        from shared.action_cards import get_action_card_registry
        get_action_card_registry().set_ui_callback(ui_callback)
    try:
        from standard_mode.core.skills_registry import get_skills_registry
    except ImportError:
        from core.skills_registry import get_skills_registry
    skills = get_skills_registry()

    for name, handler, desc, params, cat, timeout in _DEFS:
        # ★第431章: parameters 必须为合法 JSON Schema（type: object）——
        #   空 dict {} 无 type 键，DeepSeek 严格校验直接 400 拒绝整个请求
        #   （Invalid schema ... got 'type: null'，真机复现实锤）。
        safe_params = params if isinstance(params, dict) and params.get("type") else {
            "type": "object", "properties": {}}
        skills.register(SkillDef(
            name=name, description=desc, parameters=safe_params,
            handler=handler, category=cat, timeout=timeout,
            argcheck_example=({"to": "ACC002", "amount": 500} if name == "remote_bank_transfer"
                              else {"principal": 10000, "annual_rate": 3.5, "days": 365}
                              if name == "remote_bank_compound" else None)))

    # 不信任 register 返回值——注册后实测发现（证据先于判断）
    names = set()
    for d in skills.get_tool_definitions():
        names.add((d.get("function") or {}).get("name") or "")
    ok = all(n in names for n, *_ in _DEFS)

    # ★第420章: 覆盖 ActionCardRegistry 核心动作 → HTTP handler
    #   （操作卡按钮点击也走 HTTP 真连银行，不再落进程内 mock——服务流全链一致）
    from shared.action_cards import get_action_card_registry
    reg_ac = get_action_card_registry()

    def _ac(handler, **kwargs):
        def _wrap(params: dict) -> dict:
            sr = handler(**(params or {}))  # ★与 SkillsRegistry 一致：kwargs 展开调用
            out = {"success": bool(sr.success), "action_id": kwargs.get("aid", "")}
            if sr.success:
                out["message"] = sr.output
                if isinstance(sr.data, dict):
                    out["result_data"] = sr.data
            else:
                out["error"] = sr.error
                if isinstance(sr.data, dict) and sr.data.get("confirm_required"):
                    out["confirm_required"] = True
                    out["message"] = sr.error
            return out
        return _wrap

    for aid, handler, confirm, desc in (
            ("bank.query_balance", h_balance, False, "查询余额(HTTP·数字银行)"),
            ("bank.transfer", h_transfer, True, "转账(HTTP·数字银行)"),
            ("bank.reverse", h_reverse, True, "冲正(HTTP·数字银行)"),
            ("bank.reconcile", h_reconcile, False, "对账(HTTP·数字银行)")):
        reg_ac.register_action(aid, _ac(handler, aid=aid), confirm=confirm, description=desc)

    return {"success": ok, "skills": [n for n, *_ in _DEFS],
            "error": "" if ok else "注册后实测未全部发现",
            "actions_overridden": ["bank.query_balance", "bank.transfer",
                                   "bank.reverse", "bank.reconcile"],
            "bank_url": _base_url()}
