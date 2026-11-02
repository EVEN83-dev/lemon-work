# -*- coding: utf-8 -*-
"""★第405章 Mock Bank 沙盒 —— FinTechathon AI Banking 业务层（模拟银行账本）

定位：比赛不给真银行 API，所有队伍都需自建 mock 账本。本模块是
Lemon Code 平台上的银行域模型（SQLite 持久化、原子转账、余额守恒），
供 bank_skills 六组技能消费，并经 ActionCardRegistry 暴露为对话内按钮。

设计纪律：
- 真实现：一切写操作真实落库 data/mock_bank/bank.db，可重复运行可审计
- 余额守恒：转账以单事务（BEGIN IMMEDIATE）完成扣/入双写，失败回滚
- 幂等键：transfer 支持 idempotency_key，重复提交返回首笔结果
- confirm 门由 bank_skills 层标记（高风险动作 ActionCard 二次确认）
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "mock_bank")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(
  account_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
  balance INTEGER NOT NULL DEFAULT 0, frozen INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS transactions(
  tx_id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  from_acc TEXT, to_acc TEXT, amount INTEGER NOT NULL,
  kind TEXT NOT NULL, note TEXT DEFAULT '', idem_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS cards(
  card_no TEXT PRIMARY KEY, account_id TEXT NOT NULL, status TEXT NOT NULL,
  limit_daily INTEGER NOT NULL DEFAULT 5000);
CREATE TABLE IF NOT EXISTS subscriptions(
  sub_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL,
  merchant TEXT NOT NULL, amount INTEGER NOT NULL, cycle TEXT NOT NULL,
  next_charge TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(
  prod_id TEXT PRIMARY KEY, name TEXT NOT NULL, annual_rate REAL NOT NULL,
  risk_level INTEGER NOT NULL, term TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS risk_events(
  re_id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  account_id TEXT NOT NULL, rule TEXT NOT NULL, severity TEXT NOT NULL,
  detail TEXT DEFAULT '', tx_id INTEGER);
CREATE TABLE IF NOT EXISTS audit_log(
  al_id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  account_id TEXT NOT NULL, action TEXT NOT NULL,
  payload TEXT DEFAULT '', result TEXT DEFAULT '');
"""

# 旧库兼容：增量列（已存在则忽略）
_ALTERS = [
    "ALTER TABLE transactions ADD COLUMN status TEXT NOT NULL DEFAULT 'success'",
    "ALTER TABLE transactions ADD COLUMN reversed_by INTEGER",
]


class MockBank:
    """模拟银行（进程级单例经 get_mock_bank 获取；SQLite 落盘 data/mock_bank/bank.db）"""

    def __init__(self, db_path: Optional[str] = None):
        os.makedirs(_DB_DIR, exist_ok=True)
        self._path = db_path or os.path.join(_DB_DIR, "bank.db")
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self._path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        for stmt in _ALTERS:  # 旧库增量列，重复列报错忽略
            try:
                self._db.execute(stmt)
            except sqlite3.OperationalError:
                pass
        self._db.commit()
        self._seed_if_empty()
        # ★第418章: 收款人簿迁移（旧库幂等补齐——必须晚于 _seed_if_empty：
        #   若在种子前执行，新空库 COUNT!=0 会跳过全部首启种子）
        try:
            self._db.execute("INSERT OR IGNORE INTO accounts VALUES('ACC004','李雷',2000,0)")
            self._db.execute("INSERT OR IGNORE INTO accounts VALUES('ACC005','王芳',3000,0)")
            self._db.commit()
        except sqlite3.OperationalError:
            pass

    # ---------- 种子数据（首启一次；演示账户/卡片/订阅/理财） ----------
    def _seed_if_empty(self):
        if self._db.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"]:
            return
        cur = self._db.cursor()
        cur.execute("INSERT INTO accounts VALUES('ACC001','陈奕汶',25000,0)")
        cur.execute("INSERT INTO accounts VALUES('ACC002','妈妈',10000,0)")
        cur.execute("INSERT INTO accounts VALUES('ACC003','房东',500,0)")
        # ★第418章: 收款人簿演示账户——服务流剧本（给李雷/王芳转账）需要真实存在的收款人
        cur.execute("INSERT INTO accounts VALUES('ACC004','李雷',2000,0)")
        cur.execute("INSERT INTO accounts VALUES('ACC005','王芳',3000,0)")
        cur.execute("INSERT INTO cards VALUES('6222 0000 0001','ACC001','正常',500000)")
        cur.execute("INSERT INTO cards VALUES('6222 0000 0002','ACC001','正常',300000)")
        today = time.strftime("%Y-%m-%d")
        for m, amt, cyc in (("视频会员", 25, "每月"), ("云存储", 15, "每月"), ("健身App", 199, "每年")):
            cur.execute("INSERT INTO subscriptions(account_id,merchant,amount,cycle,next_charge)"
                        " VALUES('ACC001',?,?,?,?)", (m, amt, cyc, today))
        for pid, n, r, rk, t in (("P001", "活期宝", 1.8, 1, "活期"),
                                 ("P002", "90天稳健", 3.2, 2, "90天"),
                                 ("P003", "成长优选", 5.6, 4, "365天")):
            cur.execute("INSERT INTO products VALUES(?,?,?,?,?)", (pid, n, r, rk, t))
        # 近月消费种子（账单分析演示，单位分）：餐饮21400 交通4800 娱乐8500 学习8900 = 43600分
        demo = [("美团-午餐", 2800, "餐饮"), ("地铁", 600, "交通"), ("视频会员", 2500, "娱乐"),
                ("书店", 8900, "学习"), ("火锅", 16800, "餐饮"), ("打车", 4200, "交通"),
                ("奶茶", 1800, "餐饮"), ("电影票", 6000, "娱乐")]
        for note, amt, cat in demo:
            cur.execute("INSERT INTO transactions(ts,from_acc,to_acc,amount,kind,note,idem_key)"
                        " VALUES(?,'ACC001','MERCHANT',?,'支出',?,?)",
                        (today + " 12:00:00", amt, f"消费|{cat}", f"seed_{note}_{amt}"))
        self._db.commit()

    # ---------- 查询 ----------
    def query_balance(self, account_id: str = "ACC001") -> Dict:
        row = self._db.execute("SELECT * FROM accounts WHERE account_id=?",
                               (account_id,)).fetchone()
        if not row:
            return {"success": False, "error": f"账户不存在: {account_id}"}
        return {"success": True, "account_id": row["account_id"], "owner": row["owner"],
                "balance": row["balance"], "frozen": row["frozen"]}

    def list_subscriptions(self, account_id: str = "ACC001") -> Dict:
        rows = self._db.execute(
            "SELECT * FROM subscriptions WHERE account_id=?", (account_id,)).fetchall()
        return {"success": True, "items": [dict(r) for r in rows]}

    def list_products(self) -> Dict:
        rows = self._db.execute("SELECT * FROM products ORDER BY risk_level").fetchall()
        return {"success": True, "items": [dict(r) for r in rows]}

    # ---------- 核心写操作：原子转账（风控→日限额→守恒→幂等→审计） ----------
    def transfer(self, from_acc: str, to_acc: str, amount: int,
                 note: str = "", idem_key: Optional[str] = None) -> Dict:
        if amount <= 0:
            return {"success": False, "error": "金额必须为正整数（分）"}
        if from_acc == to_acc:
            return {"success": False, "error": "不可向自己转账"}
        with self._lock:
            if idem_key:
                dup = self._db.execute(
                    "SELECT tx_id,ts FROM transactions WHERE idem_key=?",
                    (idem_key,)).fetchone()
                if dup:
                    return {"success": True, "tx_id": dup["tx_id"], "ts": dup["ts"],
                            "message": "重复请求已幂等拦截，返回首笔结果"}
            # ★P0 风控规则引擎：HIGH 拒绝 / MEDIUM 放行留痕
            for rule, sev, detail in self._risk_scan(from_acc, amount):
                self._log_risk(from_acc, rule, sev, detail)
                if sev == "HIGH":
                    self._audit(from_acc, "transfer.rejected",
                                {"amount": amount, "rule": rule}, detail)
                    return {"success": False, "error": f"风控拦截({rule}): {detail}"}
            # ★P0 日限额执行（卡片 limit_daily 真源，此前从未执行——405章坦白项）
            spent = self._db.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE from_acc=?"
                " AND kind='转账' AND status='success' AND ts LIKE ?",
                (from_acc, time.strftime("%Y-%m-%d") + "%")).fetchone()["s"]
            limit = self._db.execute(
                "SELECT MIN(limit_daily) lim FROM cards WHERE account_id=? AND status='正常'",
                (from_acc,)).fetchone()["lim"]
            if limit is not None and spent + amount > limit:
                self._audit(from_acc, "transfer.rejected",
                            {"amount": amount, "spent": spent, "limit": limit}, "日限额")
                return {"success": False,
                        "error": f"超出当日转账限额：已转 {spent // 100} 元 + 本笔超限额 {limit // 100} 元"}
            try:
                self._db.execute("BEGIN IMMEDIATE")
                src = self._db.execute("SELECT balance FROM accounts WHERE account_id=?",
                                       (from_acc,)).fetchone()
                if not src or src["balance"] < amount:
                    self._db.rollback()
                    return {"success": False, "error": "余额不足或账户不存在"}
                dst = self._db.execute("SELECT account_id FROM accounts WHERE account_id=?",
                                       (to_acc,)).fetchone()
                if not dst:
                    self._db.rollback()
                    return {"success": False, "error": f"收款账户不存在: {to_acc}"}
                self._db.execute("UPDATE accounts SET balance=balance-? WHERE account_id=?",
                                 (amount, from_acc))
                self._db.execute("UPDATE accounts SET balance=balance+? WHERE account_id=?",
                                 (amount, to_acc))
                cur = self._db.execute(
                    "INSERT INTO transactions(ts,from_acc,to_acc,amount,kind,note,idem_key,status)"
                    " VALUES(?,?,?,?,?,?,?,'success')",
                    (time.strftime("%Y-%m-%d %H:%M:%S"), from_acc, to_acc, amount,
                     "转账", note, idem_key or f"tx_{time.time_ns()}"))
                self._db.commit()
                self._audit(from_acc, "transfer",
                            {"to": to_acc, "amount": amount}, f"tx={cur.lastrowid}")
                return {"success": True, "tx_id": cur.lastrowid,
                        "from": from_acc, "to": to_acc, "amount": amount,
                        "status": "success",
                        "balance_after": self.query_balance(from_acc)["balance"]}
            except Exception as e:
                self._db.rollback()
                return {"success": False, "error": f"转账失败已回滚: {e}"}

    # ---------- 账单分析（消费分类统计，供 ActionCard/报告） ----------
    def bill_analyze(self, account_id: str = "ACC001") -> Dict:
        rows = self._db.execute(
            "SELECT note,amount FROM transactions WHERE from_acc=? AND kind LIKE '支出%'",
            (account_id,)).fetchall()
        stat: Dict[str, int] = {}
        total = 0
        for r in rows:
            cat = r["note"].split("|")[1] if "|" in (r["note"] or "") else "其他"
            stat[cat] = stat.get(cat, 0) + r["amount"]
            total += r["amount"]
        top = sorted(stat.items(), key=lambda x: -x[1])
        return {"success": True, "total_expense": total,
                "by_category": stat, "top_category": top[0][0] if top else "无",
                "tx_count": len(rows)}

    # ---------- ★P0 专业层：风控/审计/冲正/对账/试算/风险匹配/赎回/订阅识别/报告 ----------
    def _risk_scan(self, account_id: str, amount: int):
        """风控规则引擎：返回 [(rule, severity, detail)]。HIGH 拒绝，MEDIUM 留痕放行。"""
        out = []
        hour = int(time.strftime("%H"))
        if amount > 500000:  # 单笔 >5000 元
            out.append(("large_amount", "HIGH", f"单笔 {amount // 100} 元超 5000 元大额阈值"))
        elif amount > 100000:
            out.append(("large_amount", "MEDIUM", f"单笔 {amount // 100} 元超 1000 元关注阈值"))
        if 23 <= hour or hour < 6:  # 夜间大额
            if amount > 100000:
                out.append(("night_large", "MEDIUM", f"夜间({hour}点)转账 {amount // 100} 元"))
        recent = self._db.execute(
            "SELECT COUNT(*) c FROM transactions WHERE from_acc=? AND kind='转账'"
            " AND ts >= datetime('now','-5 minutes')",
            (account_id,)).fetchone()["c"]
        if recent >= 3:  # 5 分钟内 ≥3 笔高频
            out.append(("high_frequency", "HIGH" if recent >= 5 else "MEDIUM",
                        f"5 分钟内已发起 {recent} 笔转账"))
        return out

    def _log_risk(self, account_id: str, rule: str, severity: str, detail: str):
        self._db.execute(
            "INSERT INTO risk_events(ts,account_id,rule,severity,detail) VALUES(?,?,?,?,?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), account_id, rule, severity, detail))
        self._db.commit()

    def _audit(self, account_id: str, action: str, payload, result: str = ""):
        """金融审计 trail：所有写操作留痕（谁/何时/何操作/何结果）"""
        try:
            self._db.execute(
                "INSERT INTO audit_log(ts,account_id,action,payload,result) VALUES(?,?,?,?,?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"), account_id, action,
                 json.dumps(payload, ensure_ascii=False), str(result)[:120]))
            self._db.commit()
        except Exception:
            pass  # 审计失败不阻断主链路，但主链路自身已落 transactions

    def list_risk_events(self, account_id: str = "", limit: int = 20) -> Dict:
        q = ("SELECT * FROM risk_events" +
             (" WHERE account_id=?" if account_id else "") +
             " ORDER BY re_id DESC LIMIT ?")
        rows = (self._db.execute(q, (account_id, limit)).fetchall() if account_id
                else self._db.execute(q, (limit,)).fetchall())
        return {"success": True, "items": [dict(r) for r in rows]}

    def get_audit_log(self, account_id: str = "", limit: int = 30) -> Dict:
        q = ("SELECT * FROM audit_log" +
             (" WHERE account_id=?" if account_id else "") +
             " ORDER BY al_id DESC LIMIT ?")
        rows = (self._db.execute(q, (account_id, limit)).fetchall() if account_id
                else self._db.execute(q, (limit,)).fetchall())
        return {"success": True, "items": [dict(r) for r in rows]}

    def reverse_transfer(self, tx_id: int, reason: str = "") -> Dict:
        """冲正：按原 tx 反向双写并标记原交易 reversed（状态机 success→reversed）"""
        with self._lock:
            tx = self._db.execute(
                "SELECT * FROM transactions WHERE tx_id=? AND kind='转账' AND status='success'",
                (tx_id,)).fetchone()
            if not tx:
                return {"success": False, "error": "原交易不存在/不可冲正"}
            try:
                self._db.execute("BEGIN IMMEDIATE")
                for acc, sign in ((tx["from_acc"], +1), (tx["to_acc"], -1)):
                    if acc and not acc.startswith(("MERCHANT", "PROD_")):
                        self._db.execute(
                            "UPDATE accounts SET balance=balance+? WHERE account_id=?",
                            (sign * tx["amount"], acc))
                self._db.execute(
                    "INSERT INTO transactions(ts,from_acc,to_acc,amount,kind,note,idem_key,status)"
                    " VALUES(?,?,?,?,?,?,?,'success')",
                    (time.strftime("%Y-%m-%d %H:%M:%S"), tx["to_acc"], tx["from_acc"],
                     tx["amount"], "冲正", f"冲正#{tx_id}:{reason}", f"rev_{tx_id}"))
                self._db.execute("UPDATE transactions SET status='reversed',reversed_by=? "
                                 "WHERE tx_id=?", (self._db.execute(
                                     "SELECT last_insert_rowid() lid").fetchone()["lid"], tx_id))
                self._db.commit()
                self._audit(tx["from_acc"], "reverse", {"tx_id": tx_id}, reason)
                return {"success": True, "message": f"交易 #{tx_id} 已冲正"}
            except Exception as e:
                self._db.rollback()
                return {"success": False, "error": f"冲正失败: {e}"}

    def ledger_audit(self) -> Dict:
        """对账：balance ≡ 种子初值 + 原始净额。
        规则：冲正tx与被冲正tx成对排除（互相抵消，均不计净额）；种子交易排除
        （种子 balance 已是现值，再计 seed tx 会双重计账）。"""
        seed = {"ACC001": 25000, "ACC002": 10000, "ACC003": 500,
                "ACC004": 2000, "ACC005": 3000}
        bad = []
        for acc in self._db.execute("SELECT * FROM accounts").fetchall():
            aid = acc["account_id"]
            inflow = self._db.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE to_acc=?"
                " AND status='success' AND kind!='冲正'", (aid,)).fetchone()["s"]
            outflow = self._db.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE from_acc=?"
                " AND status='success' AND kind!='冲正' AND idem_key NOT LIKE 'seed_%'",
                (aid,)).fetchone()["s"]
            expected = seed.get(aid, 0) + inflow - outflow
            if expected != acc["balance"]:
                bad.append({"account": aid, "expected": expected, "actual": acc["balance"]})
        return {"success": not bad, "consistent": not bad,
                "message": "全部账户对账平衡" if not bad else f"发现 {len(bad)} 处不平"}

    @staticmethod
    def compound_interest(principal_fen: int, annual_rate: float, days: int) -> Dict:
        """收益试算：日复利，银行家舍入到分（Decimal 防浮点漂移）"""
        from decimal import Decimal, ROUND_HALF_EVEN
        p = Decimal(principal_fen)
        daily = Decimal(str(annual_rate)) / Decimal(100) / Decimal(365)
        value = (p * (Decimal(1) + daily) ** days).quantize(Decimal("1"), ROUND_HALF_EVEN)
        return {"success": True, "principal": principal_fen,
                "value": int(value), "profit": int(value) - principal_fen,
                "days": days, "annual_rate": annual_rate,
                "message": f"{principal_fen // 100} 元 · {annual_rate}% 年化 · {days} 天 → "
                           f"本息 {int(value) // 100} 元（收益 {int(value - p) // 100} 元）"}

    def set_risk_profile(self, account_id: str, score: int) -> Dict:
        """风险评估问卷落档（1-5 级），并返回可投产品集合"""
        if not 1 <= score <= 5:
            return {"success": False, "error": "风险评分须在 1-5"}
        self._db.execute(
            "INSERT INTO audit_log(ts,account_id,action,payload,result) VALUES(?,?,?,?,?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), account_id, "risk_profile",
             json.dumps({"score": score}), "KYC 存档"))
        self._db.commit()
        fit = self._db.execute(
            "SELECT * FROM products WHERE risk_level<=? ORDER BY risk_level", (score,)).fetchall()
        return {"success": True, "score": score,
                "message": f"风险等级 {score} 级，可投 {len(fit)} 款产品",
                "eligible": [dict(r) for r in fit]}

    def unlock_deposit(self, account_id: str, amount: int, prod_id: str = "P001") -> Dict:
        """赎回：frozen 与 balance 反向（405章'有进无出'漏洞修复）"""
        if amount <= 0:
            return {"success": False, "error": "金额必须为正整数（分）"}
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute("SELECT frozen FROM accounts WHERE account_id=?",
                                       (account_id,)).fetchone()
                if not row or row["frozen"] < amount:
                    self._db.rollback()
                    return {"success": False, "error": "冻结金额不足或账户不存在"}
                self._db.execute("UPDATE accounts SET frozen=frozen-?, balance=balance+? "
                                 "WHERE account_id=?", (amount, amount, account_id))
                self._db.execute(
                    "INSERT INTO transactions(ts,from_acc,to_acc,amount,kind,note,idem_key,status)"
                    " VALUES(?,?,?,?,?,?,?,'success')",
                    (time.strftime("%Y-%m-%d %H:%M:%S"), f"PROD_{prod_id}", account_id,
                     amount, "赎回", f"赎回|理财", f"unlock_{account_id}_{amount}_{prod_id}_{time.time_ns()}"))
                self._db.commit()
                self._audit(account_id, "unlock", {"amount": amount, "prod": prod_id}, "赎回")
                return {"success": True, "message": f"已赎回 {amount // 100} 元至活期",
                        "balance_after": self.query_balance(account_id)["balance"]}
            except Exception as e:
                self._db.rollback()
                return {"success": False, "error": f"赎回失败已回滚: {e}"}

    def detect_subscriptions(self, account_id: str = "ACC001", min_hits: int = 2) -> Dict:
        """从交易流自动聚合识别订阅商户（赛题：自动识别订阅扣费）"""
        rows = self._db.execute(
            "SELECT note, COUNT(*) c, SUM(amount) s FROM transactions"
            " WHERE from_acc=? AND to_acc='MERCHANT' GROUP BY note"
            " HAVING c >= ? ORDER BY s DESC", (account_id, min_hits)).fetchall()
        return {"success": True, "items": [
            {"merchant": r["note"].split("|")[-1], "hits": r["c"], "total": r["s"]}
            for r in rows]}

    def bill_report(self, account_id: str = "ACC001") -> Dict:
        """专业账单报告：分类统计 + 环比 + 年化预测 + 预算建议"""
        base = self.bill_analyze(account_id)
        if not base.get("success"):
            return base
        month = time.strftime("%Y-%m")
        this_month = self._db.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE from_acc=?"
            " AND status='success' AND kind LIKE '支出%' AND ts LIKE ?",
            (account_id, month + "%")).fetchone()["s"]
        daily_avg = this_month / max(time.strftime("%d") and int(time.strftime("%d")), 1)
        forecast = int(daily_avg * 30)
        top = base["top_category"]
        advice = (f"最大开销「{top}」，建议月预算 {base['total_expense'] // 200} 元；"
                  f"按当前节奏年支出约 {forecast * 12 // 100} 元")
        base.update({"month": month, "month_expense": this_month,
                     "daily_avg": int(daily_avg), "year_forecast": forecast * 12,
                     "advice": advice,
                     "message": f"本月 {this_month // 100} 元 · 日均 {int(daily_avg) // 100} 元 · "
                                f"年预测 {forecast * 12 // 100} 元 | {advice}"})
        return base


    def lock_deposit(self, account_id: str, amount: int, prod_id: str = "P001") -> Dict:
        if amount <= 0:
            return {"success": False, "error": "金额必须为正整数（分）"}
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                src = self._db.execute("SELECT balance FROM accounts WHERE account_id=?",
                                       (account_id,)).fetchone()
                if not src or src["balance"] < amount:
                    self._db.rollback()
                    return {"success": False, "error": "余额不足或账户不存在"}
                self._db.execute("UPDATE accounts SET balance=balance-?, frozen=frozen+? "
                                 "WHERE account_id=?", (amount, amount, account_id))
                self._db.execute(
                    "INSERT INTO transactions(ts,from_acc,to_acc,amount,kind,note,idem_key)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (time.strftime("%Y-%m-%d %H:%M:%S"), account_id, f"PROD_{prod_id}",
                     amount, "申购", f"锁定|理财", f"lock_{account_id}_{amount}_{prod_id}"))
                self._db.commit()
                return {"success": True, "amount": amount, "prod_id": prod_id,
                        "message": f"已锁定 {amount // 100} 元至产品 {prod_id}（活期可随时赎回）",
                        "balance_after": self.query_balance(account_id)["balance"]}
            except Exception as e:
                self._db.rollback()
                return {"success": False, "error": f"申购失败已回滚: {e}"}

    def cancel_subscription(self, sub_id: int) -> Dict:
        cur = self._db.execute("DELETE FROM subscriptions WHERE sub_id=?", (sub_id,))
        self._db.commit()
        return {"success": cur.rowcount > 0,
                "message": f"已取消订阅 #{sub_id}" if cur.rowcount else "订阅不存在"}

    def report_card_lost(self, card_no: str) -> Dict:
        cur = self._db.execute("UPDATE cards SET status='已挂失' WHERE card_no=?", (card_no,))
        self._db.commit()
        return {"success": cur.rowcount > 0,
                "message": f"卡片 {card_no} 已挂失" if cur.rowcount else "卡片不存在"}


# ---- 进程级单例 ----
_global: Optional[MockBank] = None
_glock = threading.Lock()


def get_mock_bank() -> MockBank:
    global _global
    if _global is None:
        with _glock:
            if _global is None:
                _global = MockBank()
    return _global


def set_mock_bank(instance: MockBank) -> None:
    """测试专用：注入独立实例（如临时库），保证技能/动作全链路打同一库。生产勿用。"""
    global _global
    with _glock:
        _global = instance

