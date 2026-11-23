# -*- coding: utf-8 -*-
"""CompanyStore — 公司模式七表持久层（SQLite WAL · 集群B·A9）。

七表（任务书第 1 条）：
  company_run  公司轮次：brief/status/phase/started_ts/finished_ts/summary/config_json
  agent        工位（组织席位）：org 字段 + state/current_task/tokens/runs/…
  task         任务（DAG）：parent_task_id/depends_on/tokens + 真实耗时
  event        事件流水：run/agent/task/approval/artifact/message/audit_* 带 ts
  approval     审批：approval_request/response；scope(manager|owner)/状态/审批人
  artifact     产物（版本化）：kind(brief/proposal/patch/…)、version、来源、审批人
  session      会话台账：kind(dm|group|approval)、topic、成员；消息正文本体在
               session_mesh（bus.py 复用 session_mesh.store.add_message 真落盘）

口径：
  · WAL 模式 + 每线程独立连接（busy_timeout 5s），跨线程并发写安全。
  · 一律真实时间戳（time.time() epoch 秒），耗时用 elapsed_ms 真值。
  · 不做任何演示数据 —— 测试与验证脚本自己写入真实记录。
兼容：A9 前的 output 表口径由 artifact 承接（add_output/get_outputs 为别名）。
"""

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS company_run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    brief       TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'running',   -- running|paused|stopped|completed
    phase       TEXT    NOT NULL DEFAULT 'start',     -- start|assign|execute|verify|done
    started_ts  REAL    NOT NULL,
    finished_ts REAL,
    summary     TEXT    NOT NULL DEFAULT '',
    config_json TEXT    NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS agent (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL,
    role_id       TEXT    NOT NULL,
    name          TEXT    NOT NULL DEFAULT '',
    station       TEXT    NOT NULL DEFAULT '',
    dept          TEXT    NOT NULL DEFAULT '',
    level         INTEGER NOT NULL DEFAULT 9,
    reports_to    TEXT    NOT NULL DEFAULT '',
    state         TEXT    NOT NULL DEFAULT 'idle',    -- idle|working|paused|error|done
    current_task  TEXT    NOT NULL DEFAULT '',
    tokens        INTEGER NOT NULL DEFAULT 0,
    runs          INTEGER NOT NULL DEFAULT 0,
    completed     INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    whitelist     INTEGER NOT NULL DEFAULT 0,           -- 白名单技能数
    caps_json     TEXT    NOT NULL DEFAULT '{}',
    updated_ts    REAL    NOT NULL,
    UNIQUE(run_id, role_id)
);
CREATE TABLE IF NOT EXISTS task (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL,
    role_id          TEXT    NOT NULL DEFAULT '',
    description      TEXT    NOT NULL DEFAULT '',
    status           TEXT    NOT NULL DEFAULT 'pending', -- pending|assigned|running|done|failed|rejected
    parent_task_id   INTEGER,
    depends_on       TEXT    NOT NULL DEFAULT '[]',      -- JSON [task_id,...]
    depth            INTEGER NOT NULL DEFAULT 0,
    kind             TEXT    NOT NULL DEFAULT 'work',    -- work|decompose|proposal|verify
    result           TEXT    NOT NULL DEFAULT '',
    error            TEXT    NOT NULL DEFAULT '',
    tokens           INTEGER NOT NULL DEFAULT 0,
    subagent_task_id TEXT    NOT NULL DEFAULT '',
    orch_task_id     TEXT    NOT NULL DEFAULT '',   -- 编排账本侧任务号（收束回执用）
    started_ts       REAL,
    finished_ts      REAL,
    elapsed_ms       INTEGER,
    created_ts       REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS event (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   INTEGER,
    type     TEXT    NOT NULL,   -- run_started|agent_state|task_started|task_done|run_done|
                         -- approval_requested|approval_response|artifact_created|
                         -- message_sent|audit_denied|rule_denied
    ts       REAL    NOT NULL,
    payload  TEXT    NOT NULL DEFAULT '{}'  -- JSON
);
CREATE TABLE IF NOT EXISTS approval (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER,
    kind         TEXT    NOT NULL DEFAULT 'plan',   -- plan|artifact|config|irreversible
    scope        TEXT    NOT NULL DEFAULT 'manager',-- manager|owner（不可逆=owner）
    status       TEXT    NOT NULL DEFAULT 'pending',-- pending|approved|rejected
    requested_by TEXT    NOT NULL DEFAULT '',
    approver     TEXT    NOT NULL DEFAULT '',
    reason       TEXT    NOT NULL DEFAULT '',
    dept         TEXT    NOT NULL DEFAULT '',
    payload      TEXT    NOT NULL DEFAULT '{}',     -- JSON
    requested_ts REAL    NOT NULL,
    responded_ts REAL
);
CREATE TABLE IF NOT EXISTS artifact (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER,
    task_id     INTEGER,
    role_id     TEXT    NOT NULL DEFAULT '',
    kind        TEXT    NOT NULL DEFAULT 'report',  -- brief|plan|proposal|patch|report|log
    name        TEXT    NOT NULL DEFAULT '',        -- 同名自增 version
    version     INTEGER NOT NULL DEFAULT 1,
    source      TEXT    NOT NULL DEFAULT '',        -- 产物来源（上传者/产出工位/diff）
    approver    TEXT    NOT NULL DEFAULT '',        -- 批准人（artifact 审批通过后回填）
    content     TEXT    NOT NULL DEFAULT '',
    ts          REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS session (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER,
    session_id TEXT    NOT NULL UNIQUE,               -- 与 session_mesh chat_session 同 id
    kind       TEXT    NOT NULL DEFAULT 'dm',         -- dm|group|approval
    topic      TEXT    NOT NULL DEFAULT '',
    members    TEXT    NOT NULL DEFAULT '[]',         -- JSON [role_id,...]
    created_by TEXT    NOT NULL DEFAULT 'owner',
    created_ts REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_run  ON task(run_id);
CREATE INDEX IF NOT EXISTS idx_task_parent ON task(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_event_run ON event(run_id);
CREATE INDEX IF NOT EXISTS idx_artifact_run ON artifact(run_id);
CREATE INDEX IF NOT EXISTS idx_agent_run ON agent(run_id);
CREATE INDEX IF NOT EXISTS idx_approval_run ON approval(run_id);
"""

_EVENT_TYPES = ("run_started", "agent_state", "task_started", "task_done",
                "run_done", "rule_denied", "approval_requested",
                "approval_response", "artifact_created", "artifact_approved",
                "message_sent", "audit_denied", "config_updated",
                # ★ 第17批（项 C1）: 引擎工具调用留痕
                "tool_call",
                # ★ 第19批（项 A7）: 文件写冲突仲裁
                "arbitration_resolved",
                # ★ 2026-11-23: 仲裁通知投递被拒（不再静默丢弃）
                "arbitration_notice_denied",
                # ★ 2026-11-23: 开机对账收口（进程重启后遗留账本清理）
                "reconcile_orphans")


class CompanyStore:
    """七表 SQLite 存储。db_path 缺省 data/company/company.db。"""

    def __init__(self, db_path: str = ""):
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "company", "company.db")
        # :memory: 等无目录路径跳过建目录（否则 makedirs('') 崩溃）
        _dir = os.path.dirname(self.db_path)
        if _dir and self.db_path != ":memory:":
            os.makedirs(_dir, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_schema()

    # ── 连接管理：每线程一条连接，WAL 允许读写并发 ──
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # :memory: 用共享内存 URI，保证多线程看到同一份库
            if self.db_path == ":memory:":
                conn = sqlite3.connect("file:company_mem?mode=memory&cache=shared",
                                       uri=True, timeout=5.0)
            else:
                conn = sqlite3.connect(self.db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        with self._write_lock:
            self._conn().executescript(_SCHEMA)
            # ★ 迁移：A9 前建的库补 orch_task_id 列（缺列 ALTER，已有则跳过）
            cols = {r["name"] for r in self._conn().execute("PRAGMA table_info(task)")}
            if "orch_task_id" not in cols:
                self._conn().execute("ALTER TABLE task ADD COLUMN orch_task_id TEXT NOT NULL DEFAULT ''")
            self._conn().commit()

    @staticmethod
    def _row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        return dict(row) if row is not None else None

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ============================================================
    # company_run
    # ============================================================
    def create_run(self, brief: str = "", started_ts: Optional[float] = None,
                   config: Optional[Dict[str, Any]] = None) -> int:
        with self._write_lock:
            cur = self._conn().execute(
                "INSERT INTO company_run(brief, status, phase, started_ts, config_json) "
                "VALUES(?, 'running', 'start', ?, ?)",
                (str(brief or ""), float(started_ts if started_ts is not None else time.time()),
                 json.dumps(config or {}, ensure_ascii=False, default=str)))
            self._conn().commit()
            return int(cur.lastrowid)

    def update_run(self, run_id: int, status: str = "", phase: str = "",
                   summary: str = "", config: Optional[Dict[str, Any]] = None) -> bool:
        sets, args = [], []
        if status:
            sets.append("status=?"); args.append(str(status))
        if phase:
            sets.append("phase=?"); args.append(str(phase))
        if summary:
            sets.append("summary=?"); args.append(str(summary))
        if config is not None:
            sets.append("config_json=?")
            args.append(json.dumps(config, ensure_ascii=False, default=str))
        if not sets:
            return False
        args.append(int(run_id))
        with self._write_lock:
            cur = self._conn().execute(
                f"UPDATE company_run SET {', '.join(sets)} WHERE id=?", args)
            self._conn().commit()
            return cur.rowcount > 0

    def finish_run(self, run_id: int, status: str = "stopped", summary: str = "",
                   finished_ts: Optional[float] = None) -> bool:
        with self._write_lock:
            cur = self._conn().execute(
                "UPDATE company_run SET status=?, summary=?, finished_ts=? WHERE id=?",
                (str(status), str(summary or ""),
                 float(finished_ts if finished_ts is not None else time.time()),
                 int(run_id)))
            self._conn().commit()
            return cur.rowcount > 0

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        row = self._conn().execute(
            "SELECT * FROM company_run WHERE id=?", (int(run_id),)).fetchone()
        run = self._row(row)
        if run:
            try:
                run["config"] = json.loads(run.pop("config_json") or "{}")
            except Exception:
                run["config"] = {}
                run.pop("config_json", None)
        return run

    def latest_run(self) -> Optional[Dict[str, Any]]:
        row = self._conn().execute(
            "SELECT id FROM company_run ORDER BY id DESC LIMIT 1").fetchone()
        return self.get_run(row["id"]) if row else None

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT id FROM company_run ORDER BY id DESC LIMIT ?",
            (max(1, int(limit)),)).fetchall()
        return [self.get_run(r["id"]) for r in rows]

    # ============================================================
    # agent（组织工位）
    # ============================================================
    def upsert_agent(self, run_id: int, role_id: str, name: str = "",
                     state: str = "idle", whitelist: int = 0,
                     station: str = "", dept: str = "", level: int = 9,
                     reports_to: str = "", caps: Optional[Dict[str, int]] = None,
                     updated_ts: Optional[float] = None) -> None:
        with self._write_lock:
            self._conn().execute(
                "INSERT INTO agent(run_id, role_id, name, state, whitelist, station,"
                " dept, level, reports_to, caps_json, updated_ts) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(run_id, role_id) DO UPDATE SET "
                "name=excluded.name, whitelist=excluded.whitelist,"
                " station=excluded.station, dept=excluded.dept,"
                " level=excluded.level, reports_to=excluded.reports_to,"
                " caps_json=excluded.caps_json, updated_ts=excluded.updated_ts",
                (int(run_id), str(role_id), str(name or ""), str(state),
                 int(whitelist or 0), str(station or ""), str(dept or ""),
                 int(level), str(reports_to or ""),
                 json.dumps(caps or {}, ensure_ascii=False),
                 float(updated_ts if updated_ts is not None else time.time())))
            self._conn().commit()

    def update_agent_state(self, run_id: int, role_id: str, state: str,
                           current_task: str = "",
                           tokens_delta: int = 0, runs_delta: int = 0,
                           completed_delta: int = 0, failed_delta: int = 0) -> bool:
        """更新席位状态；计数列只做真实增量（禁覆盖造数）。"""
        with self._write_lock:
            cur = self._conn().execute(
                "UPDATE agent SET state=?, current_task=?, updated_ts=?, "
                "tokens=tokens+?, runs=runs+?, completed=completed+?, failed=failed+? "
                "WHERE run_id=? AND role_id=?",
                (str(state), str(current_task or ""), time.time(),
                 int(tokens_delta or 0), int(runs_delta or 0),
                 int(completed_delta or 0), int(failed_delta or 0),
                 int(run_id), str(role_id)))
            self._conn().commit()
            return cur.rowcount > 0

    def get_agents(self, run_id: int) -> List[Dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM agent WHERE run_id=? ORDER BY level, role_id",
            (int(run_id),)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["caps"] = json.loads(d.pop("caps_json") or "{}")
            except Exception:
                d["caps"] = {}
            out.append(d)
        return out

    # ============================================================
    # task（DAG）
    # ============================================================
    def create_task(self, run_id: int, role_id: str = "", description: str = "",
                    parent_task_id: Optional[int] = None,
                    depends_on: Optional[List[int]] = None, depth: int = 0,
                    kind: str = "work", created_ts: Optional[float] = None) -> int:
        with self._write_lock:
            cur = self._conn().execute(
                "INSERT INTO task(run_id, role_id, description, status,"
                " parent_task_id, depends_on, depth, kind, created_ts) "
                "VALUES(?,?,?, 'pending', ?, ?, ?, ?, ?)",
                (int(run_id), str(role_id or ""), str(description or ""),
                 int(parent_task_id) if parent_task_id else None,
                 json.dumps([int(t) for t in (depends_on or [])]),
                 int(depth), str(kind or "work"),
                 float(created_ts if created_ts is not None else time.time())))
            self._conn().commit()
            return int(cur.lastrowid)

    def update_task(self, task_id: int, status: str = "", result: str = "",
                    error: str = "", subagent_task_id: str = "",
                    orch_task_id: str = "",
                    tokens: Optional[int] = None,
                    started_ts: Optional[float] = None,
                    finished_ts: Optional[float] = None,
                    elapsed_ms: Optional[int] = None) -> bool:
        sets, args = [], []
        if status:
            sets.append("status=?"); args.append(str(status))
        if result:
            sets.append("result=?"); args.append(str(result))
        if error:
            sets.append("error=?"); args.append(str(error))
        if subagent_task_id:
            sets.append("subagent_task_id=?"); args.append(str(subagent_task_id))
        if orch_task_id:
            sets.append("orch_task_id=?"); args.append(str(orch_task_id))
        if tokens is not None:
            sets.append("tokens=?"); args.append(int(tokens))
        if started_ts is not None:
            sets.append("started_ts=?"); args.append(float(started_ts))
        if finished_ts is not None:
            sets.append("finished_ts=?"); args.append(float(finished_ts))
        if elapsed_ms is not None:
            sets.append("elapsed_ms=?"); args.append(int(elapsed_ms))
        if not sets:
            return False
        args.append(int(task_id))
        with self._write_lock:
            cur = self._conn().execute(
                f"UPDATE task SET {', '.join(sets)} WHERE id=?", args)
            self._conn().commit()
            return cur.rowcount > 0

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        row = self._conn().execute(
            "SELECT * FROM task WHERE id=?", (int(task_id),)).fetchone()
        return self._task_row(row)

    def get_tasks(self, run_id: int, status: str = "") -> List[Dict[str, Any]]:
        if status:
            rows = self._conn().execute(
                "SELECT * FROM task WHERE run_id=? AND status=? ORDER BY id",
                (int(run_id), str(status))).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM task WHERE run_id=? ORDER BY id",
                (int(run_id),)).fetchall()
        return [self._task_row(r) for r in rows]

    @staticmethod
    def _task_row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        d = dict(row)
        try:
            d["depends_on"] = json.loads(d.get("depends_on") or "[]")
        except Exception:
            d["depends_on"] = []
        return d

    def deps_done(self, task_id: int) -> bool:
        """DAG 依赖是否全部满足（真实查询，逐条核对）。"""
        t = self.get_task(task_id)
        if not t:
            return False
        for dep in (t.get("depends_on") or []):
            dep_row = self.get_task(int(dep))
            if not dep_row or dep_row["status"] not in ("done",):
                return False
        return True

    # ============================================================
    # event
    # ============================================================
    def add_event(self, run_id: Optional[int], etype: str, payload: Dict[str, Any],
                  ts: Optional[float] = None) -> int:
        if etype not in _EVENT_TYPES:
            raise ValueError(f"未知事件类型 {etype!r}；合法: {_EVENT_TYPES}")
        with self._write_lock:
            cur = self._conn().execute(
                "INSERT INTO event(run_id, type, ts, payload) VALUES(?,?,?,?)",
                (int(run_id) if run_id else None, str(etype),
                 float(ts if ts is not None else time.time()),
                 json.dumps(payload or {}, ensure_ascii=False, default=str)))
            self._conn().commit()
            return int(cur.lastrowid)

    def get_events(self, run_id: Optional[int] = None,
                   limit: int = 200) -> List[Dict[str, Any]]:
        if run_id is not None:
            rows = self._conn().execute(
                "SELECT * FROM event WHERE run_id=? ORDER BY id DESC LIMIT ?",
                (int(run_id), max(1, int(limit)))).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM event ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),)).fetchall()
        out = []
        for r in reversed(rows):  # 升序返回（时间序）
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except Exception:
                d["payload"] = {}
            out.append(d)
        return out

    # ============================================================
    # approval（审批）
    # ============================================================
    def create_approval(self, run_id: Optional[int], kind: str, scope: str,
                        requested_by: str, dept: str = "",
                        payload: Optional[Dict[str, Any]] = None,
                        reason: str = "",
                        requested_ts: Optional[float] = None) -> int:
        with self._write_lock:
            cur = self._conn().execute(
                "INSERT INTO approval(run_id, kind, scope, status, requested_by,"
                " dept, payload, reason, requested_ts) "
                "VALUES(?,?,?, 'pending', ?,?,?,?,?)",
                (int(run_id) if run_id else None, str(kind or "plan"),
                 str(scope or "manager"), str(requested_by or ""),
                 str(dept or ""),
                 json.dumps(payload or {}, ensure_ascii=False, default=str),
                 str(reason or ""),
                 float(requested_ts if requested_ts is not None else time.time())))
            self._conn().commit()
            return int(cur.lastrowid)

    def respond_approval(self, approval_id: int, status: str, approver: str,
                         reason: str = "",
                         responded_ts: Optional[float] = None) -> bool:
        if status not in ("approved", "rejected"):
            raise ValueError(f"审批结果非法: {status!r}（合法：approved/rejected）")
        with self._write_lock:
            cur = self._conn().execute(
                "UPDATE approval SET status=?, approver=?, reason=?, responded_ts=? "
                "WHERE id=? AND status='pending'",
                (str(status), str(approver or ""), str(reason or ""),
                 float(responded_ts if responded_ts is not None else time.time()),
                 int(approval_id)))
            self._conn().commit()
            return cur.rowcount > 0

    def get_approval(self, approval_id: int) -> Optional[Dict[str, Any]]:
        row = self._conn().execute(
            "SELECT * FROM approval WHERE id=?", (int(approval_id),)).fetchone()
        return self._approval_row(row)

    def get_approvals(self, run_id: Optional[int] = None,
                      status: str = "") -> List[Dict[str, Any]]:
        if run_id is not None and status:
            rows = self._conn().execute(
                "SELECT * FROM approval WHERE run_id=? AND status=? ORDER BY id",
                (int(run_id), str(status))).fetchall()
        elif run_id is not None:
            rows = self._conn().execute(
                "SELECT * FROM approval WHERE run_id=? ORDER BY id",
                (int(run_id),)).fetchall()
        elif status:
            rows = self._conn().execute(
                "SELECT * FROM approval WHERE status=? ORDER BY id",
                (str(status),)).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM approval ORDER BY id").fetchall()
        return [self._approval_row(r) for r in rows]

    @staticmethod
    def _approval_row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        d = dict(row)
        try:
            d["payload"] = json.loads(d.get("payload") or "{}")
        except Exception:
            d["payload"] = {}
        return d

    # ============================================================
    # artifact（版本化产物）
    # ============================================================
    def add_artifact(self, run_id: Optional[int], task_id: Optional[int],
                     role_id: str, kind: str, name: str, content: str,
                     source: str = "", approver: str = "",
                     ts: Optional[float] = None) -> Dict[str, Any]:
        """同名产物自动 version+1（真实版本链；来源/审批人如实登记）。"""
        with self._write_lock:
            row = self._conn().execute(
                "SELECT MAX(version) AS v FROM artifact "
                "WHERE run_id IS ? AND name=?", (run_id, str(name or ""))).fetchone()
            version = int((row["v"] or 0)) + 1
            cur = self._conn().execute(
                "INSERT INTO artifact(run_id, task_id, role_id, kind, name, version,"
                " source, approver, content, ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (int(run_id) if run_id is not None else None,
                 int(task_id) if task_id else None,
                 str(role_id or ""), str(kind or "report"), str(name or ""),
                 version, str(source or ""), str(approver or ""),
                 str(content or ""),
                 float(ts if ts is not None else time.time())))
            self._conn().commit()
            return self.get_artifact(cur.lastrowid) or {}

    def update_artifact_approver(self, artifact_id: int, approver: str) -> bool:
        with self._write_lock:
            cur = self._conn().execute(
                "UPDATE artifact SET approver=? WHERE id=?",
                (str(approver or ""), int(artifact_id)))
            self._conn().commit()
            return cur.rowcount > 0

    def get_artifact(self, artifact_id: int) -> Optional[Dict[str, Any]]:
        row = self._conn().execute(
            "SELECT * FROM artifact WHERE id=?", (int(artifact_id),)).fetchone()
        return self._row(row)

    def get_artifacts(self, run_id: Optional[int] = None, role_id: str = "",
                      kind: str = "", name: str = "",
                      limit: int = 50) -> List[Dict[str, Any]]:
        sql, args = "SELECT * FROM artifact WHERE 1=1", []
        if run_id is not None:
            sql += " AND run_id=?"; args.append(int(run_id))
        if role_id:
            sql += " AND role_id=?"; args.append(str(role_id))
        if kind:
            sql += " AND kind=?"; args.append(str(kind))
        if name:
            sql += " AND name=?"; args.append(str(name))
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, int(limit)))
        rows = self._conn().execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    # ============================================================
    # session（会话台账；消息正文本体在 session_mesh）
    # ============================================================
    def create_session(self, run_id: Optional[int], session_id: str, kind: str,
                       topic: str = "", members: Optional[List[str]] = None,
                       created_by: str = "owner",
                       created_ts: Optional[float] = None) -> int:
        with self._write_lock:
            cur = self._conn().execute(
                "INSERT INTO session(run_id, session_id, kind, topic, members,"
                " created_by, created_ts) VALUES(?,?,?,?,?,?,?)",
                (int(run_id) if run_id else None, str(session_id),
                 str(kind or "dm"), str(topic or ""),
                 json.dumps([str(m) for m in (members or [])], ensure_ascii=False),
                 str(created_by or "owner"),
                 float(created_ts if created_ts is not None else time.time())))
            self._conn().commit()
            return int(cur.lastrowid)

    def get_sessions(self, run_id: Optional[int] = None,
                     kind: str = "") -> List[Dict[str, Any]]:
        if run_id is not None and kind:
            rows = self._conn().execute(
                "SELECT * FROM session WHERE run_id=? AND kind=? ORDER BY id",
                (int(run_id), str(kind))).fetchall()
        elif run_id is not None:
            rows = self._conn().execute(
                "SELECT * FROM session WHERE run_id=? ORDER BY id",
                (int(run_id),)).fetchall()
        elif kind:
            rows = self._conn().execute(
                "SELECT * FROM session WHERE kind=? ORDER BY id",
                (str(kind),)).fetchall()
        else:
            rows = self._conn().execute("SELECT * FROM session ORDER BY id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["members"] = json.loads(d.get("members") or "[]")
            except Exception:
                d["members"] = []
            out.append(d)
        return out

    def count_sessions(self) -> int:
        """会话台账总行数（历史会话管理页显示 N / total）。"""
        return int(self._conn().execute("SELECT COUNT(*) FROM session").fetchone()[0])

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn().execute(
            "SELECT * FROM session WHERE session_id=?", (str(session_id),)).fetchone()
        if row is None:
            return None
        d = dict(row)
        try:
            d["members"] = json.loads(d.get("members") or "[]")
        except Exception:
            d["members"] = []
        return d

    # ============================================================
    # stats（真实聚合，供 KPI 面板）
    # ============================================================
    def stats(self, run_id: Optional[int] = None) -> Dict[str, Any]:
        """units/agents/rejected/rules/broken 全部来自七表真值。

        ★ 2026-11-23: 补吞吐量口径（近 60s token/事件/收束数），
          供公司页 KPI 显示实时 info throughput；全部 SQL 聚合，无估算。
        """
        rid = int(run_id) if run_id else None
        q = lambda sql, *a: self._conn().execute(sql, a).fetchone()[0]
        cutoff = time.time() - 60.0
        if rid:
            units = q("SELECT COUNT(*) FROM task WHERE run_id=? AND status='done'", rid)
            rejected = q("SELECT COUNT(*) FROM task WHERE run_id=? AND status='rejected'", rid)
            broken = q("SELECT COUNT(*) FROM task WHERE run_id=? AND status='failed'", rid)
            agents = q("SELECT COUNT(*) FROM agent WHERE run_id=?", rid)
            rules = q("SELECT COUNT(*) FROM event WHERE run_id=? AND type='rule_denied'", rid)
            outputs = q("SELECT COUNT(*) FROM artifact WHERE run_id=?", rid)
            approvals = q("SELECT COUNT(*) FROM approval WHERE run_id=?", rid)
            audit = q("SELECT COUNT(*) FROM event WHERE run_id=? AND type='audit_denied'", rid)
            tok_total = q("SELECT COALESCE(SUM(tokens),0) FROM task WHERE run_id=? AND status='done'", rid)
            tok_min = q("SELECT COALESCE(SUM(tokens),0) FROM task WHERE run_id=? AND status='done'"
                        " AND finished_ts>=?", rid, cutoff)
            done_min = q("SELECT COUNT(*) FROM task WHERE run_id=? AND status='done'"
                         " AND finished_ts>=?", rid, cutoff)
            ev_min = q("SELECT COUNT(*) FROM event WHERE run_id=? AND ts>=?", rid, cutoff)
            active = q("SELECT COUNT(*) FROM agent WHERE run_id=? AND state='working'", rid)
        else:
            units = q("SELECT COUNT(*) FROM task WHERE status='done'")
            rejected = q("SELECT COUNT(*) FROM task WHERE status='rejected'")
            broken = q("SELECT COUNT(*) FROM task WHERE status='failed'")
            agents = q("SELECT COUNT(*) FROM agent")
            rules = q("SELECT COUNT(*) FROM event WHERE type='rule_denied'")
            outputs = q("SELECT COUNT(*) FROM artifact")
            approvals = q("SELECT COUNT(*) FROM approval")
            audit = q("SELECT COUNT(*) FROM event WHERE type='audit_denied'")
            tok_total = q("SELECT COALESCE(SUM(tokens),0) FROM task WHERE status='done'")
            tok_min = q("SELECT COALESCE(SUM(tokens),0) FROM task WHERE status='done'"
                        " AND finished_ts>=?", cutoff)
            done_min = q("SELECT COUNT(*) FROM task WHERE status='done'"
                         " AND finished_ts>=?", cutoff)
            ev_min = q("SELECT COUNT(*) FROM event WHERE ts>=?", cutoff)
            active = q("SELECT COUNT(*) FROM agent WHERE state='working'")
        return {"units": int(units), "agents": int(agents),
                "rejected": int(rejected), "rules": int(rules),
                "broken": int(broken), "outputs": int(outputs),
                "approvals": int(approvals), "audit_denied": int(audit),
                "tok_total": int(tok_total),
                "tok_per_s": round(float(tok_min) / 60.0, 2),
                "tasks_per_min": round(float(done_min), 2),
                "events_per_min": int(ev_min),
                "active_agents": int(active),
                "window_s": 60}

    # ============================================================
    # 兼容别名（A9 前 output 表口径 → artifact 承接）
    # ============================================================
    def add_output(self, run_id: Optional[int], task_id: Optional[int],
                   role_id: str, kind: str, content: str,
                   ts: Optional[float] = None) -> int:
        art = self.add_artifact(run_id, task_id, role_id, kind=kind or "report",
                                name=f"{role_id or 'agent'}-output", content=content,
                                source=role_id or "", ts=ts)
        return int(art["id"])

    def get_outputs(self, run_id: Optional[int] = None, role_id: str = "",
                    limit: int = 50) -> List[Dict[str, Any]]:
        return self.get_artifacts(run_id=run_id, role_id=role_id, limit=limit)
