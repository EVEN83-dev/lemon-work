# -*- coding: utf-8 -*-
"""第439章 fintech_guard —— 银行 Agent 三级权限网关（零侵入叠加层）

职责：把 permission_tiers 的分级/MFA/审计能力，接到既有 ActionCardRegistry 之上，
形成"唯一执行入口"，供 UI、测试与答辩演示统一调用。

调用协议（三步式，与赛题"绿/黄/红"一一对应）：
  1) execute(action_id, params)                       → 绿区直接执行；黄区返回 confirm_required；红区返回 mfa_required
  2) execute(action_id, params, confirmed=True)       → 黄区凭确认执行
  3) execute(action_id, params, challenge_id, code)   → 红区凭强验证执行

纪律：
  · 不修改 action_cards.py / bank_skills.py
  · 每次决策（含拒绝）都写 permission_decisions 审计表
  · 红区在未通过验证前绝不触达真实银行 handler
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared import permission_tiers as PT
from shared.action_cards import get_action_card_registry


class GuardedBankGateway:
    """银行动作安全网关"""

    def __init__(self, registry=None, account_id: str = "ACC001"):
        self._reg = registry or get_action_card_registry()
        self._account = account_id
        self._vault = PT.get_mfa_vault()

    # ── 对外唯一入口 ──────────────────────────────────
    def _resolve(self, action_id: str) -> str:
        """动作 id 归一化：意图层用 bank_query_balance，注册表用 bank.query_balance"""
        aid = action_id or ""
        candidates = [aid]
        if "." not in aid and "_" in aid:
            candidates.append(aid.replace("_", ".", 1))
        if "_" in aid and "." in aid:
            candidates.append(aid.replace(".", "_", 1))
        for c in candidates:
            try:
                if self._reg.has(c):
                    return c
            except Exception:
                pass
        return aid

    def execute(self, action_id: str, params: Optional[Dict] = None,
                confirmed: bool = False,
                challenge_id: Optional[str] = None,
                code: Optional[str] = None,
                context: Optional[Dict] = None) -> Dict:
        p = dict(params or {})
        decision = PT.classify(action_id, p, context)
        level = decision["level"]
        rid = self._resolve(action_id)

        # ① 绿区：自动执行
        if level == PT.GREEN:
            r = self._reg.dispatch(rid, p, confirmed=True)
            PT.log_decision(decision, "auto_executed", self._account)
            return self._wrap(r, decision, "auto_executed")

        # ② 黄区：需用户确认
        if level == PT.YELLOW:
            if not confirmed:
                PT.log_decision(decision, "confirm_required", self._account)
                return self._wrap(
                    {"success": False, "confirm_required": True,
                     "message": "该操作需您确认后执行：%s" % "；".join(decision["reasons"])},
                    decision, "confirm_required")
            r = self._reg.dispatch(rid, p, confirmed=True)
            PT.log_decision(decision, "user_confirmed", self._account)
            return self._wrap(r, decision, "user_confirmed")

        # ③ 红区：强验证
        if challenge_id is None:
            ch = self._vault.issue(action_id, p, channel="sms")
            PT.log_decision(decision, "mfa_issued", self._account, ch)
            return self._wrap(
                {"success": False, "mfa_required": True,
                 "challenge": {k: ch[k] for k in ("challenge_id", "channel", "expires_in", "notice")},
                 "demo_code": ch.get("demo_code"),
                 "message": "高风险操作，需强验证：%s" % "；".join(decision["reasons"])},
                decision, "mfa_issued", ch)

        ver = self._vault.verify(challenge_id, code or "", action_id, p)
        if not ver.get("success"):
            PT.log_decision(decision, "mfa_failed", self._account,
                            {"challenge_id": challenge_id, "channel": "sms"})
            return self._wrap({"success": False, "mfa_failed": True,
                               "error": ver.get("error")}, decision, "mfa_failed",
                              {"challenge_id": challenge_id, "channel": "sms"})

        r = self._reg.dispatch(rid, p, confirmed=True)
        PT.log_decision(decision, "mfa_verified", self._account,
                        {"challenge_id": challenge_id, "channel": ver.get("channel")})
        return self._wrap(r, decision, "mfa_verified",
                          {"challenge_id": challenge_id, "channel": ver.get("channel")})

    # ── 便捷方法（演示脚本用） ─────────────────────────
    def query_balance(self, **kw) -> Dict:
        return self.execute("bank.query_balance", {}, **kw)

    def transfer(self, to: str, amount_fen: int, **kw) -> Dict:
        return self.execute("bank.transfer", {"to": to, "amount": amount_fen}, **kw)

    def lock_deposit(self, amount_fen: int, prod_id: str = "P001", **kw) -> Dict:
        return self.execute("bank.lock_deposit",
                            {"amount": amount_fen, "prod_id": prod_id}, **kw)

    def card_lost(self, card_no: str, **kw) -> Dict:
        return self.execute("bank.card_lost", {"card_no": card_no}, **kw)

    def cancel_subscription(self, sub_id: int, **kw) -> Dict:
        return self.execute("bank.cancel_subscription", {"sub_id": sub_id}, **kw)

    def bill_analyze(self, **kw) -> Dict:
        return self.execute("bank.bill_analyze", {}, **kw)

    # ── 内部 ──────────────────────────────────────────
    @staticmethod
    def _wrap(result: Dict, decision: Dict, outcome: str, challenge=None) -> Dict:
        out = dict(result) if isinstance(result, dict) else {"success": False, "error": str(result)}
        out["permission"] = {
            "level": decision["level"],
            "score": decision["score"],
            "reasons": decision["reasons"],
            "policy": decision["policy"],
            "outcome": outcome,
        }
        if challenge:
            out["permission"]["challenge_id"] = challenge.get("challenge_id")
        return out

    # 审计查询（答辩演示"决策链路"）
    def decisions(self, limit: int = 20) -> list:
        return PT.list_decisions(limit)


def get_gateway(account_id: str = "ACC001") -> GuardedBankGateway:
    return GuardedBankGateway(account_id=account_id)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import tempfile, os, time
    from shared.mock_bank import MockBank, set_mock_bank

    tmp = os.path.join(tempfile.gettempdir(), "gateway_demo_%d.db" % time.time())
    set_mock_bank(MockBank(db_path=tmp))
    PT.set_audit_db(tmp + ".audit.db")
    PT.reset_mfa_vault()

    # 演示用充值：种子账户仅 250 元，无法演示 >1000 元的红区转账，先充值到 10000 元
    from shared.mock_bank import get_mock_bank
    _mb = get_mock_bank()
    _mb._db.execute("UPDATE accounts SET balance=1000000 WHERE account_id='ACC001'")
    _mb._db.commit()

    from shared.skills_builtin.bank_skills import register_bank_skills
    register_bank_skills()

    gw = get_gateway()
    print("=" * 62)
    print("  三级权限网关演示（账户余额已充值至 10000 元用于红区演示）")
    print("=" * 62)

    r = gw.query_balance()
    print("\n[1] 查余额（应绿区自动） level=%s outcome=%s" % (
        r["permission"]["level"], r["permission"]["outcome"]))

    r = gw.transfer("妈妈", 5000)   # 50 元
    print("\n[2] 转账 50 元（应黄区待确认） level=%s 待确认=%s" % (
        r["permission"]["level"], r.get("confirm_required")))

    r = gw.transfer("妈妈", 5000, confirmed=True)
    print("    确认后执行 success=%s outcome=%s" % (
        r.get("success"), r["permission"]["outcome"]))

    r = gw.transfer("妈妈", 200000)   # 2000 元
    print("\n[3] 转账 2000 元（应红区强验证） level=%s score=%s 需强验证=%s" % (
        r["permission"]["level"], r["permission"]["score"], r.get("mfa_required")))
    ch = r["challenge"]["challenge_id"]
    print("    模拟短信验证码: %s" % r.get("demo_code"))
    r2 = gw.transfer("妈妈", 200000, challenge_id=ch, code=r.get("demo_code"))
    print("    验证通过后执行 success=%s outcome=%s" % (
        r2.get("success"), r2["permission"]["outcome"]))

    r3 = gw.transfer("妈妈", 600000)  # 换参数复用旧挑战
    print("\n[4] 换参攻击（6000元） level=%s 需新挑战=%s" % (
        r3["permission"]["level"], r3.get("mfa_required")))

    print("\n[5] 决策审计（最近6条）")
    for d in gw.decisions(6):
        print("    %s %-22s %-6s %-3s → %s" % (
            d["ts"][-8:], d["action_id"], d["level"], d["score"], d["outcome"]))
    print("\nMFA 统计:", PT.get_mfa_vault().stats())
