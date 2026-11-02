# -*- coding: utf-8 -*-
"""第440章 bank_gateway_server —— 银行 Agent 多渠道接入网关（零依赖）

赛题依据（二、赛题任务）：
  "用户可通过 **APP、IM 等渠道** 与 Agent 联通"

设计取舍：
  · 不依赖 FastAPI（便携运行时缺 fastapi，bridge_server 无法启动）
  · 仅用标准库 http.server，保证评委机器零安装即可跑
  · 与 Kitty 无关：可在小程序/H5/IM webhook/鸿蒙端通过 HTTP 调用同一套 Banking Agent

端点：
  GET  /health                 服务存活 + 渠道列表
  GET  /api/bank/policy        三级权限策略矩阵（供前端渲染）
  POST /api/bank/execute       执行银行动作（携带 channel 标识）
  GET  /api/bank/pending       人工待审队列（HITL）
  POST /api/bank/approve       人工审批通过/拒绝
  GET  /api/bank/decisions     分级决策审计（最近 N 条）

HITL（Human-in-the-Loop）：
  当 risk score ≥ 阈值（默认 90）或 渠道为 im/miniapp 且动作为红区时，
  不直接执行，而是进入待审队列，由人工在审核台批准后才放行——
  对标 PromptPay Guard 的 "Amber 区推送人工审核台" 做法。
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared import permission_tiers as PT
from shared.fintech_guard import get_gateway

# ── 渠道注册表（记录每个渠道的接入情况，答辩可展示"多端在线"）──
CHANNELS: dict = {
    "pc": {"name": "PC 桌面端", "desc": "PyQt5 主界面"},
    "miniapp": {"name": "微信小程序", "desc": "移动端轻入口"},
    "harmony": {"name": "鸿蒙端 HM-lemon", "desc": "ArkTS 原生"},
    "im": {"name": "IM 机器人", "desc": "企业微信/飞书 webhook"},
}
_channel_stats: dict = {k: {"calls": 0, "last_seen": None} for k in CHANNELS}

# ── HITL 待审队列 ──
HITL_SCORE_THRESHOLD = 90          # 分值 ≥ 此值需人工复核
HITL_CHANNELS = {"im", "miniapp"}  # 这两个渠道的红区动作一律转人工
_pending: dict = {}
_plock = threading.RLock()


def _new_ticket(action_id: str, params: dict, decision: dict, channel: str) -> dict:
    tid = "TK" + secrets.token_hex(6).upper()
    with _plock:
        _pending[tid] = {
            "ticket_id": tid,
            "action_id": action_id,
            "params": params,
            "channel": channel,
            "level": decision["level"],
            "score": decision["score"],
            "reasons": decision["reasons"],
            "status": "pending",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    PT.log_decision(decision, "hitl_pending", "ACC001",
                    {"challenge_id": None, "channel": channel})
    return {"success": False, "pending_review": True, "ticket_id": tid,
            "permission": {"level": decision["level"], "score": decision["score"],
                           "reasons": decision["reasons"], "outcome": "hitl_pending"},
            "message": "该操作已提交人工复核，工单号 %s；审核通过后方可执行" % tid}


def execute_with_channel(payload: dict) -> dict:
    """带渠道标识的执行业务：分级 → MFA → HITL → 执行"""
    action = payload.get("action") or ""
    params = payload.get("params") or {}
    channel = (payload.get("channel") or "pc").lower()
    confirmed = bool(payload.get("confirmed"))
    cid = payload.get("challenge_id")
    code = payload.get("code")

    _channel_stats.setdefault(channel, {"calls": 0, "last_seen": None})
    _channel_stats[channel]["calls"] += 1
    _channel_stats[channel]["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")

    decision = PT.classify(action, params)

    need_hitl = (decision["level"] == PT.RED and
                 (decision["score"] >= HITL_SCORE_THRESHOLD or channel in HITL_CHANNELS))
    # 已在强验证流程中（带 challenge_id）时不重复转人工，避免二次拦截
    if need_hitl and not payload.get("ticket_id") and not cid:
        return _new_ticket(action, params, decision, channel)

    gw = get_gateway("ACC001")
    r = gw.execute(action, params, confirmed=confirmed, challenge_id=cid, code=code)
    r.setdefault("channel", channel)
    return r


def approve(ticket_id: str, approved: bool, operator: str = "reviewer") -> dict:
    with _plock:
        t = _pending.get(ticket_id)
        if not t:
            return {"success": False, "error": "工单不存在"}
        if t["status"] != "pending":
            return {"success": False, "error": "工单已处理：%s" % t["status"]}
        t["status"] = "approved" if approved else "rejected"
        t["operator"] = operator
        t["handled_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if not approved:
        return {"success": True, "ticket_id": ticket_id, "result": "rejected",
                "message": "人工已拒绝该操作"}
    # 通过后走 MFA（红区仍需强验证）
    gw = get_gateway("ACC001")
    r = gw.execute(t["action_id"], t["params"])
    r["ticket_id"] = ticket_id
    r["approved_by"] = operator
    return r


def pending_list() -> list:
    with _plock:
        return sorted(_pending.values(), key=lambda x: x["created_at"], reverse=True)


# ── 自然语言入口：意图消歧 → 分级 → 执行（Lemon Work 前端主通道）──
_session_ctx: dict = {}   # session_id -> {last_payee, last_amount, last_subscription}


def chat(payload: dict) -> dict:
    """一句话办业务：解析意图 → 追问或执行，并维护会话上下文"""
    from shared import intent_disambiguator as ID

    text = (payload.get("text") or "").strip()
    sid = payload.get("session_id") or "default"
    channel = (payload.get("channel") or "pc").lower()
    ctx = _session_ctx.setdefault(sid, {})

    parsed = ID.parse(text, ctx)
    if parsed["need_clarify"] or not parsed["safe_to_execute"]:
        return {"success": False, "kind": "clarify", "reply": parsed["question"],
                "intent": parsed["intent"], "rule": parsed["rule"],
                "missing": parsed["missing"], "channel": channel}

    action = parsed["intent"]
    params = parsed["slots"]

    # 记录上下文，供"上次那个/老样子"复用
    if action == "bank_transfer":
        if params.get("to"):
            ctx["last_payee"] = params["to"]
        if params.get("amount"):
            ctx["last_amount"] = params["amount"]
    if action == "bank_cancel_subscription" and params.get("sub_id"):
        ctx["last_subscription"] = params["sub_id"]

    # 复用同一套分级/MFA/HITL 链路
    r = execute_with_channel({"action": action, "params": params,
                              "channel": channel, "confirmed": payload.get("confirmed", False),
                              "challenge_id": payload.get("challenge_id"),
                              "code": payload.get("code")})
    r["kind"] = "result"
    r["intent"] = action
    r["reply"] = _compose_reply(action, params, r)
    return r


def _compose_reply(action: str, params: dict, r: dict) -> str:
    """把结构化结果组织成一句人话，供前端气泡展示"""
    p = r.get("permission") or {}
    lvl = {"green": "低风险", "yellow": "需确认", "red": "高风险"}.get(p.get("level"), "")
    if r.get("pending_review"):
        return "这笔操作风险较高（%s），已转人工复核，工单号 %s。" % (lvl, r.get("ticket_id"))
    if r.get("confirm_required"):
        return "该操作需您确认后再执行（%s）。" % lvl
    if r.get("mfa_required"):
        return "这是高风险操作（%s），需要短信验证码验证。" % lvl
    if r.get("mfa_failed"):
        return "验证未通过：%s" % r.get("error")
    if r.get("success"):
        amt = params.get("amount")
        if action == "bank_transfer" and amt:
            return "已向 %s 转账 %.2f 元。" % (params.get("to"), amt / 100)
        return r.get("message") or "操作已完成。"
    return r.get("error") or r.get("message") or "操作未完成。"


# ── HTTP 层 ──
class _Handler(BaseHTTPRequestHandler):
    server_version = "LemonBankGateway/1.0"

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")   # 演示用；生产应收窄
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # 小程序/H5 跨域预检
        self._send(204, {})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {
                "ok": True, "service": "Lemon Bank Agent Gateway",
                "channels": {k: dict(v, **(_channel_stats.get(k) or {})) for k, v in CHANNELS.items()},
                "hitl": {"pending": len([t for t in pending_list() if t["status"] == "pending"]),
                         "threshold": HITL_SCORE_THRESHOLD},
                "policy": PT.policy_matrix(),
            })
        if path == "/api/bank/policy":
            return self._send(200, {"success": True, "policy": PT.policy_matrix()})
        if path == "/api/bank/pending":
            return self._send(200, {"success": True, "items": pending_list()})
        if path == "/api/bank/decisions":
            return self._send(200, {"success": True, "items": PT.list_decisions(20)})
        return self._send(404, {"success": False, "error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return self._send(400, {"success": False, "error": "invalid json"})
        if path == "/api/bank/execute":
            return self._send(200, execute_with_channel(payload))
        if path == "/api/bank/chat":
            return self._send(200, chat(payload))
        if path == "/api/bank/approve":
            return self._send(200, approve(payload.get("ticket_id", ""),
                                           bool(payload.get("approved")),
                                           payload.get("operator", "reviewer")))
        return self._send(404, {"success": False, "error": "not found"})

    def log_message(self, fmt, *args):
        pass  # 静默，避免刷屏


def start_server(port: int = 8091, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import tempfile
    from shared.mock_bank import MockBank, set_mock_bank

    tmp = os.path.join(tempfile.gettempdir(), "gw_demo_%d.db" % time.time())
    set_mock_bank(MockBank(db_path=tmp))
    PT.set_audit_db(tmp + ".audit.db")
    PT.reset_mfa_vault()
    from shared.mock_bank import get_mock_bank as _g
    _g()._db.execute("UPDATE accounts SET balance=1000000 WHERE account_id='ACC001'")
    _g()._db.commit()
    from shared.skills_builtin.bank_skills import register_bank_skills
    register_bank_skills()

    srv = start_server(8091)
    print("=" * 60)
    print("  多渠道银行 Agent 网关已启动: http://127.0.0.1:8091")
    print("  渠道:", ", ".join(CHANNELS.keys()))
    print("=" * 60)

    # 进程内自测（无需外部客户端）
    import urllib.request

    def call(method, path, body=None):
        req = urllib.request.Request("http://127.0.0.1:8091" + path, method=method)
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode() if body else None
        with urllib.request.urlopen(req, data=data, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    print("\n[1] 健康检查（多端在线）")
    h = call("GET", "/health")
    print("    ok=%s 渠道=%d 待审=%d" % (h["ok"], len(h["channels"]), h["hitl"]["pending"]))

    print("\n[2] 小程序渠道查余额（应绿区自动）")
    r = call("POST", "/api/bank/execute", {"action": "bank.query_balance", "channel": "miniapp"})
    print("    level=%s outcome=%s channel=%s" % (
        r["permission"]["level"], r["permission"]["outcome"], r.get("channel")))

    print("\n[3] IM 渠道转账 2000 元（红区 → 转人工复核）")
    r = call("POST", "/api/bank/execute",
             {"action": "bank.transfer", "params": {"to": "妈妈", "amount": 200000}, "channel": "im"})
    print("    待审=%s 工单=%s" % (r.get("pending_review"), r.get("ticket_id")))
    pend = call("GET", "/api/bank/pending")
    print("    待审队列: %d 条" % len(pend["items"]))

    print("\n[4] 人工审批通过 → 进入强验证")
    ap = call("POST", "/api/bank/approve", {"ticket_id": r.get("ticket_id"), "approved": True})
    print("    level=%s 需强验证=%s" % (ap["permission"]["level"], ap.get("mfa_required")))
    if ap.get("challenge"):
        v = call("POST", "/api/bank/execute",
                 {"action": "bank.transfer", "params": {"to": "妈妈", "amount": 200000},
                  "channel": "im", "challenge_id": ap["challenge"]["challenge_id"],
                  "code": ap.get("demo_code")})
        print("    验证通过执行 success=%s" % v.get("success"))

    print("\n[5] 决策审计（最近3条）")
    for d in call("GET", "/api/bank/decisions")["items"][:3]:
        print("    %s %-18s %-6s %-3s → %s" % (
            d["ts"][-8:], d["action_id"], d["level"], d["score"], d["outcome"]))

    srv.shutdown()
    print("\n网关已关闭。")
