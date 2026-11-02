# -*- coding: utf-8 -*-
"""第438章 permission_tiers —— 银行 Agent 三级权限分级 + 多因子强验证

对标依据（2026 业界实践）：
  · PromptPay Guard 零信任支付：0-30 绿区自动 / 31-70 黄区人工确认 / 71-100 红区拦截
  · Revolut AIR：敏感操作须生物识别批准（Biometric protection）
  · IETF draft-sharif-agent-payment-trust：挑战-响应验证 + 按信任评分分级限额
  · arXiv 2610.04123《Agent Reliability Profiles in Financial Services》：自主性分级 T0-T4

赛题映射（三、核心技术要求 1 权限分级，实现优先级：高）：
  绿色 = 自动执行（纯查询类）
  黄色 = 用户确认（小额转账 ≤1000 元 / 订阅查询取消 / 虚拟卡申请）
  红色 = 强验证（大额转账 >1000 元 / 挂失解挂 / 理财申购 / 改密），须多因子

设计纪律：
  · 不修改既有 ActionCardRegistry / bank_skills（本模块为零侵入叠加层）
  · 分级由「评分 + 硬规则」双轨：硬规则优先（如挂失必红），评分用于转账等金额敏感操作
  · 所有分级决策写入审计表，供答辩展示"决策链路"
  · 验证码一次性、5 分钟有效、3 次失败锁定，绝不明文回显生产环境（演示环境显式标注）
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from typing import Dict, Optional, Tuple

GREEN = "green"
YELLOW = "yellow"
RED = "red"

# ── 操作基础分（0-100）：硬规则优先表 ─────────────────────────
# 说明：查询类 0 分（必绿）；挂失/解挂/冲正属"极高风险"，基础分直接落入红区
BASE_SCORES: Dict[str, int] = {
    # 绿色域：纯查询
    "bank_query_balance": 0,
    "bank_bill_analyze": 0,
    "bank_bill_report": 0,
    "bank_list_products": 0,
    "bank_list_subscriptions": 0,
    "bank_risk_events": 0,
    "bank_audit_log": 0,
    "bank_detect_subs": 0,
    "bank_compound": 5,
    # 黄色域：需确认
    "bank_transfer": 40,          # 金额加权后：≤1000 元仍黄，>1000 元转红
    "bank_cancel_subscription": 35,
    "bank_risk_profile": 10,
    "bank_unlock": 60,            # 赎回，黄偏上
    # 红色域：强验证（基础分已落红区）
    "bank_lock_deposit": 75,      # 理财申购
    "bank_card_lost": 80,         # 挂失
    "bank_reverse": 88,           # 交易冲正（不可逆）
}

# 硬规则：无论评分如何，一律强制级别
FORCE_RED = {"bank_card_lost", "bank_reverse"}
FORCE_GREEN = {
    "bank_query_balance", "bank_bill_analyze", "bank_bill_report",
    "bank_list_products", "bank_list_subscriptions", "bank_risk_events",
    "bank_audit_log", "bank_detect_subs",
}

# 阈值（对齐 PromptPay Guard 三区）
THRESHOLD_GREEN_MAX = 30      # 0-30 绿
THRESHOLD_YELLOW_MAX = 70     # 31-70 黄；>=71 红

# 金额阈值（分）：1000 元 = 100000 分
AMOUNT_YELLOW_LIMIT = 100000
AMOUNT_RED_LIMIT = 500000     # 5000 元

# 多因子参数
MFA_TTL_SECONDS = 300
MFA_MAX_ATTEMPTS = 3


# ═════════════════════════ 分级引擎 ═════════════════════════
def classify(action_id: str, params: Optional[Dict] = None,
             context: Optional[Dict] = None) -> Dict:
    """对一次银行操作做权限分级。

    :param action_id: 动作标识（bank.transfer / bank_query_balance 等，兼容点号与下划线）
    :param params: 操作参数（转账取 amount）
    :param context: 运行上下文 {hour, recent_count_5min, is_new_payee, injection_flag}
    :return: {"level","score","reasons","action_id","params_digest"}
    """
    p = dict(params or {})
    ctx = dict(context or {})
    aid = (action_id or "").replace(".", "_")

    reasons = []
    score = BASE_SCORES.get(aid, 50)   # 未登记动作默认 50 分（黄区，保守）
    if aid not in BASE_SCORES:
        reasons.append("未登记动作，默认黄区")

    # 硬规则优先
    if aid in FORCE_GREEN:
        level = GREEN
        reasons.append("纯查询类：硬规则绿区")
        return _pack(aid, level, 0, reasons, p)

    if aid in FORCE_RED:
        level = RED
        reasons.append("不可逆/极高风险操作：硬规则红区")
        return _pack(aid, level, max(score, 80), reasons, p)

    # 金额加权（转账/申购/赎回）
    amount = int(p.get("amount", 0) or 0)
    if amount > 0 and aid in ("bank_transfer", "bank_lock_deposit", "bank_unlock"):
        if amount > AMOUNT_RED_LIMIT:
            score += 50
            reasons.append("金额 %d 元 > 5000 元大额阈值(+50)" % (amount // 100))
        elif amount > AMOUNT_YELLOW_LIMIT:
            score += 35
            reasons.append("金额 %d 元 > 1000 元(+35)" % (amount // 100))
        else:
            reasons.append("金额 %d 元 ≤ 1000 元（小额）" % (amount // 100))

    # 环境加权
    hour = ctx.get("hour")
    if hour is None:
        hour = int(time.strftime("%H"))
    if (hour >= 23 or hour < 6) and amount > AMOUNT_YELLOW_LIMIT:
        score += 15
        reasons.append("夜间 %d 点大额(+15)" % hour)

    recent = int(ctx.get("recent_count_5min", 0) or 0)
    if recent >= 3:
        score += 20
        reasons.append("5 分钟内 %d 笔高频(+20)" % recent)

    if ctx.get("is_new_payee"):
        score += 10
        reasons.append("首次向该收款人转账(+10)")

    if ctx.get("injection_flag"):
        score += 30
        reasons.append("检测到注入标记(+30)")

    score = min(score, 100)
    if score <= THRESHOLD_GREEN_MAX:
        level = GREEN
    elif score <= THRESHOLD_YELLOW_MAX:
        level = YELLOW
    else:
        level = RED
    return _pack(aid, level, score, reasons, p)


def _pack(aid: str, level: str, score: int, reasons: list, params: Dict) -> Dict:
    return {
        "action_id": aid,
        "level": level,
        "score": score,
        "reasons": reasons,
        "params_digest": _digest(params),
        "policy": {"green_max": THRESHOLD_GREEN_MAX,
                   "yellow_max": THRESHOLD_YELLOW_MAX},
        "decided_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _digest(params: Dict) -> str:
    raw = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ═════════════════════════ 多因子强验证 ═════════════════════════
class MFAVault:
    """内存态挑战库（演示环境；生产应对接短信网关/人脸 SDK/U盾）。

    · 一次性：验证成功即销毁
    · 时效：5 分钟
    · 限次：3 次失败即锁定该挑战
    · 绑定：挑战与 (action_id + 参数摘要) 绑定，换参数即失效 —— 防"换单攻击"
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._items: Dict[str, Dict] = {}
        self._stats = {"issued": 0, "passed": 0, "failed": 0, "locked": 0, "expired": 0}

    def issue(self, action_id: str, params: Dict, channel: str = "sms") -> Dict:
        aid = (action_id or "").replace(".", "_")
        dg = _digest(params)
        cid = secrets.token_hex(8)
        code = "%06d" % secrets.randbelow(1000000)
        with self._lock:
            self._items[cid] = {
                "action_id": aid, "digest": dg, "code": code,
                "channel": channel, "expires_at": time.time() + MFA_TTL_SECONDS,
                "attempts": 0, "used": False,
            }
            self._stats["issued"] += 1
        return {
            "challenge_id": cid,
            "channel": channel,
            "expires_in": MFA_TTL_SECONDS,
            "demo_code": code,   # 演示环境回显；生产须移除并经短信通道下发
            "notice": "演示环境：验证码已回显。生产环境应经短信/人脸/U盾通道下发，不得回显。",
        }

    def verify(self, challenge_id: str, code: str, action_id: str, params: Dict) -> Dict:
        aid = (action_id or "").replace(".", "_")
        dg = _digest(params)
        with self._lock:
            it = self._items.get(challenge_id)
            if not it:
                self._stats["failed"] += 1
                return {"success": False, "error": "挑战不存在或已失效"}
            if it["used"]:
                return {"success": False, "error": "挑战已使用（一次性）"}
            if time.time() > it["expires_at"]:
                self._stats["expired"] += 1
                self._items.pop(challenge_id, None)
                return {"success": False, "error": "挑战已过期（5分钟时效）"}
            if it["action_id"] != aid or it["digest"] != dg:
                self._stats["failed"] += 1
                return {"success": False, "error": "挑战与操作不匹配（参数已变更，防换单攻击）"}
            if it["attempts"] >= MFA_MAX_ATTEMPTS:
                self._stats["locked"] += 1
                self._items.pop(challenge_id, None)
                return {"success": False, "error": "失败次数超限，挑战已锁定"}
            if str(code).strip() != it["code"]:
                it["attempts"] += 1
                self._stats["failed"] += 1
                left = MFA_MAX_ATTEMPTS - it["attempts"]
                if it["attempts"] >= MFA_MAX_ATTEMPTS:
                    self._stats["locked"] += 1
                    self._items.pop(challenge_id, None)
                    return {"success": False, "error": "验证码错误，已达上限，挑战锁定"}
                return {"success": False, "error": "验证码错误，剩余 %d 次" % left}
            it["used"] = True
            self._stats["passed"] += 1
            self._items.pop(challenge_id, None)
        return {"success": True, "channel": it["channel"],
                "verified_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    def stats(self) -> Dict:
        with self._lock:
            return dict(self._stats, active=len(self._items))


_VAULT: Optional[MFAVault] = None
_VLOCK = threading.Lock()


def get_mfa_vault() -> MFAVault:
    global _VAULT
    if _VAULT is None:
        with _VLOCK:
            if _VAULT is None:
                _VAULT = MFAVault()
    return _VAULT


def reset_mfa_vault() -> None:
    """测试专用：清空挑战库"""
    global _VAULT
    with _VLOCK:
        _VAULT = MFAVault()


# ═════════════════════════ 决策审计（结构化链路） ═════════════════════════
_AUDIT_DB: Optional[str] = None


def set_audit_db(path: str) -> None:
    """指定决策审计库（默认落在 data/mock_bank/permission_audit.db）"""
    global _AUDIT_DB
    _AUDIT_DB = path
    _ensure_schema(path)


def _audit_path() -> str:
    if _AUDIT_DB:
        return _AUDIT_DB
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "data", "mock_bank")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "permission_audit.db")


def _ensure_schema(path: str) -> None:
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS permission_decisions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL, account_id TEXT, action_id TEXT NOT NULL,
          level TEXT NOT NULL, score INTEGER NOT NULL,
          reasons TEXT, params_digest TEXT, outcome TEXT,
          challenge_id TEXT, channel TEXT, evidence TEXT);
        """)
        conn.commit()
    finally:
        conn.close()


def log_decision(decision: Dict, outcome: str, account_id: str = "ACC001",
                 challenge: Optional[Dict] = None) -> None:
    """写一条分级决策审计（含决策链路与结果），失败不阻断主链路"""
    path = _audit_path()
    try:
        _ensure_schema(path)
        conn = sqlite3.connect(path, timeout=10)
        try:
            conn.execute(
                "INSERT INTO permission_decisions(ts,account_id,action_id,level,score,"
                "reasons,params_digest,outcome,challenge_id,channel,evidence) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (decision.get("decided_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
                 account_id, decision.get("action_id"), decision.get("level"),
                 int(decision.get("score", 0)),
                 " | ".join(decision.get("reasons") or []),
                 decision.get("params_digest"), outcome,
                 (challenge or {}).get("challenge_id"),
                 (challenge or {}).get("channel"),
                 json.dumps(decision, ensure_ascii=False)[:400]))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def list_decisions(limit: int = 30) -> list:
    path = _audit_path()
    try:
        _ensure_schema(path)
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM permission_decisions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        return []


# ═════════════════════════ 三级载荷矩阵（供答辩展示） ═════════════════════════
POLICY_MATRIX = {
    GREEN: {
        "label": "绿 · 自动执行",
        "score_range": "0-30",
        "rule": "Agent 确认意图后直接执行，无需二次确认",
        "actions": ["余额查询", "交易记录查询", "账单分析", "理财收益查询",
                    "产品列表", "订阅列表", "风控事件查询", "审计日志查询"],
        "mfa": None,
    },
    YELLOW: {
        "label": "黄 · 用户确认",
        "score_range": "31-70",
        "rule": "执行前展示操作详情并获得明确确认",
        "actions": ["小额转账（≤1000 元）", "订阅取消", "风险评估问卷",
                    "理财赎回（小额）", "虚拟卡申请"],
        "mfa": None,
    },
    RED: {
        "label": "红 · 强验证",
        "score_range": "71-100",
        "rule": "须通过多因子认证（短信验证码 / 人脸识别 / U 盾）后方可执行",
        "actions": ["大额转账（>1000 元）", "卡片挂失", "解除挂失",
                    "理财产品申购", "交易冲正", "密码修改"],
        "mfa": ["sms", "face", "ukey"],
    },
}


def policy_matrix() -> Dict:
    return POLICY_MATRIX


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("  三级权限分级自检")
    print("=" * 60)
    cases = [
        ("bank_query_balance", {}, "查询余额"),
        ("bank.bill_analyze", {}, "账单分析"),
        ("bank.transfer", {"to": "妈妈", "amount": 5000}, "转账 50 元"),
        ("bank.transfer", {"to": "妈妈", "amount": 200000}, "转账 2000 元"),
        ("bank.transfer", {"to": "妈妈", "amount": 600000}, "转账 6000 元"),
        ("bank.cancel_subscription", {"sub_id": 1}, "取消订阅"),
        ("bank.lock_deposit", {"amount": 8000}, "理财申购"),
        ("bank.card_lost", {"card_no": "6222"}, "卡片挂失"),
    ]
    for aid, p, desc in cases:
        d = classify(aid, p)
        print("[%s] %-6s 分=%-3d %-14s | %s" % (
            d["level"].upper()[:1], d["level"], d["score"], desc,
            "；".join(d["reasons"])[:60]))
    v = get_mfa_vault()
    r = v.issue("bank.transfer", {"to": "妈妈", "amount": 200000})
    print("\nMFA 挑战:", r["challenge_id"], "演示码:", r["demo_code"])
    ok = v.verify(r["challenge_id"], r["demo_code"], "bank.transfer", {"to": "妈妈", "amount": 200000})
    print("验证:", ok)
    bad = v.issue("bank.transfer", {"to": "妈妈", "amount": 200000})
    print("换参攻击测试:", v.verify(bad["challenge_id"], bad["demo_code"],
                                  "bank.transfer", {"to": "妈妈", "amount": 600000}))
