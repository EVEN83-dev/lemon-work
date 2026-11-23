# -*- coding: utf-8 -*-
"""CompanyService — 公司运行态服务（集群B·A9 · 任务书第 2/11/12/13/14/15/16 条）。

规范 API（第 2 条）：create_run / assign / approve / reject / complete / state
兼容保留：start(=create_run 别名) / stop / pause / resume / send_back / outputs /
stats / current_run_summary（窗口3 公司看板 company_board.html 与 HybridBridge
12 方法依赖的既有口径，行为不变）。

真实链路（禁 mock）：
  · 组织：shared.company.org —— role_system 真名册 × 9 工位编制；
  · 执行：SubAgentOrchestrator.submit_task+assign_task →
    EngineManager.spawn_subagent（白名单/预算/超时统一链），完成监视线程
    轮询 get_subagent_result 拿真实回执（tokens/耗时真值）；
  · DAG：brief 拆解产生任务树（parent/depends_on），assign 前真实核对
    deps_done；依赖未满足的任务如实排队（pending），不假装执行；
  · 审批：approval_request/response；scope 级判定经 org.can_approve
    （owner/manager 双闸），不可逆操作 scope=owner 仅人类可批；
  · 会话/消息：shared.company.bus 复用 session_mesh 真信件 + session_acl
    真判定；越权 403 + audit_denied 事件落库；
  · 文件交接：shared.agent_container.compute_diff 真差异 → artifact(patch)
    版本链（版本/来源/审批人如实登记）。
"""

import json
import logging
import os
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from shared.company import org
from shared.company.bus import BusError, CompanyBus
from shared.company.store import CompanyStore

logger = logging.getLogger(__name__)

# 任务终态词表：监视线程/收口函数据此做幂等判定（避免二次回写覆盖真实结果）
_TERMINAL_TASK = ("done", "failed", "skipped", "cancelled", "rejected")
# 引擎子代理成功态（engine_manager 实发 completed，历史口径 done/success 一并兼容）
_OK_SUBAGENT_STATUS = ("completed", "done", "success")


def _pid_alive(pid: int) -> bool:
    """跨平台进程存活探测（psutil 优先；Windows 用 OpenProcess，POSIX 用 signal 0）。"""
    if int(pid or 0) <= 0:
        return False
    try:
        import psutil  # type: ignore
        return bool(psutil.pid_exists(int(pid)))
    except Exception:
        logger.debug("suppressed exception")
    if os.name == "nt":
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _owner_lock_path(db_path: str) -> str:
    """账本归属锁按 DB 路径区分 —— 临时库/测试库不会与线上库抢同一把锁。"""
    import hashlib
    h = hashlib.sha1(os.path.abspath(str(db_path)).encode("utf-8")).hexdigest()[:10]
    return os.path.join(os.path.dirname(os.path.abspath(str(db_path))),
                        f".ledger_owner_{h}.json")


def _now() -> float:
    return time.time()


def _now_ms() -> int:
    return int(time.time() * 1000)


class CompanyService:
    """公司运行态服务。单例经 get_company_service() 获取。"""

    def __init__(self, engine_manager=None, orchestrator=None,
                 store: Optional[CompanyStore] = None, db_path: str = ""):
        self._engine_manager = engine_manager
        self._orchestrator = orchestrator
        self._store = store or CompanyStore(db_path=db_path)
        self._bus = CompanyBus(self._store, audit=self._audit_denied)
        self._lock = threading.RLock()
        self._run_id: Optional[int] = None
        self._started_perf: float = 0.0
        self._paused = False
        self._stopped = False
        self._state_cbs: List[Callable] = []
        self._event_cbs: List[Callable] = []
        self._watchers: List[threading.Thread] = []
        self._config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "company", "config.json")
        self._transport: Dict[str, Any] = {"sse_available": False,
                                           "port": None, "token": None}
        # ★ 回执监视线程超时可配置（env > config > 默认 600s）
        self._watch_timeout_seconds = 600
        try:
            _env_wt = os.environ.get("LEMON_COMPANY_WATCH_TIMEOUT", "").strip()
            if _env_wt:
                self._watch_timeout_seconds = max(30, int(float(_env_wt)))
            else:
                from shared.config_manager import ConfigManager
                self._watch_timeout_seconds = max(30, int(
                    ConfigManager().get("company.watch_timeout_seconds", 600)))
        except Exception:
            logger.debug("suppressed exception")
        self._reconcile_orphans()

    # ============================================================
    # 开机对账（收口上一进程遗留账本）
    # ============================================================
    # ============================================================
    # 暂停席位持久化（跨重启）
    # ============================================================
    def _paused_seats_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(self._store.db_path)),
                            "paused_seats.json")

    def load_paused_seats(self) -> List[str]:
        try:
            with open(self._paused_seats_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return [str(x) for x in (data or []) if str(x).strip()]
        except Exception:
            return []

    def save_paused_seats(self, seats) -> None:
        try:
            os.makedirs(os.path.dirname(self._paused_seats_path()), exist_ok=True)
            with open(self._paused_seats_path(), "w", encoding="utf-8") as f:
                json.dump(sorted({str(s) for s in (seats or []) if str(s).strip()}),
                          f, ensure_ascii=False, indent=1)
        except Exception as e:
            logger.warning("[CompanyService] 暂停席位落盘失败: %s", e)

    def pause_seat(self, role_id: str) -> List[str]:
        seats = set(self.load_paused_seats())
        seats.add(str(role_id))
        self.save_paused_seats(list(seats))
        return sorted(seats)

    def resume_seat(self, role_id: str) -> List[str]:
        seats = set(self.load_paused_seats())
        seats.discard(str(role_id))
        self.save_paused_seats(list(seats))
        return sorted(seats)

    def _reconcile_orphans(self) -> Dict[str, int]:
        """进程重启后，本进程没有任何活跃子代理/watcher（都是内存线程），
        上一进程遗留的 running run/task 不可能再收到回执。

        此前不做对账：company.db 实测 111 个 running run、45 个 running task
        永久挂账，工位账本一直显示忙，看板失真且 DAG 后继任务饿死。

        ★ 进程守卫（防误杀）：对账只会发生在"账本归属者"进程。若同一台机器上
        已有存活进程持有本库的归属锁（应用正在跑），则跳过 —— 否则跑一次
        scripts/verify_*.py 或开第二个实例，就会把正在执行的公司任务全部判失败。
        逃生口：LEMON_FORCE_RECONCILE=1 强制对账；LEMON_SKIP_RECONCILE=1 强制跳过。
        """
        def _env_on(name: str) -> bool:
            return str(os.environ.get(name, "")).strip().lower() in ("1", "true", "yes", "on")

        if _env_on("LEMON_SKIP_RECONCILE"):
            logger.info("[CompanyService] 跳过开机对账（LEMON_SKIP_RECONCILE=1）")
            return {"skipped": "env", "runs": 0, "tasks": 0, "seats": 0}
        try:
            lock_path = _owner_lock_path(self._store.db_path)
            owner: Dict[str, Any] = {}
            if os.path.isfile(lock_path):
                with open(lock_path, "r", encoding="utf-8") as f:
                    owner = json.load(f) or {}
            owner_pid = int(owner.get("pid") or 0)
            if (not _env_on("LEMON_FORCE_RECONCILE")
                    and owner_pid and owner_pid != os.getpid()
                    and _pid_alive(owner_pid)):
                logger.warning(
                    "[CompanyService] 跳过开机对账：账本由存活进程 pid=%s 持有"
                    "（防止把正在执行的任务判失败）。强制对账请设 "
                    "LEMON_FORCE_RECONCILE=1", owner_pid)
                return {"skipped": "other_process", "owner_pid": owner_pid,
                        "runs": 0, "tasks": 0, "seats": 0}
            with open(lock_path, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "ts": _now(),
                           "db": self._store.db_path}, f)
        except Exception as _lock_err:
            logger.warning("[CompanyService] 归属锁读写失败（继续执行对账）: %s", _lock_err)

        n_run = n_task = n_seat = 0
        _paused_seats = set(self.load_paused_seats())
        try:
            for r in self._store.list_runs(limit=300):
                rid = int(r["id"])
                run_status = str(r.get("status") or "")
                # ① 遗留 running 任务：无论所属 run 是什么状态都要收口
                #    （实测：run 已被 stop、任务却永久 running —— 只查 running run
                #     会漏掉这类僵尸，旧版对账后仍残留 40 条）
                for t in self._store.get_tasks(rid, status="running"):
                    self._store.update_task(
                        int(t["id"]), status="failed",
                        error="进程重启，回执监视线程已丢失（开机对账）",
                        finished_ts=_now())
                    n_task += 1
                # ② 忙状态工位一律释放（账本是内存态，重启后不可能还有在执行的分身）
                #    ★ 暂停席位持久化：paused_seats.json 里的角色重启后仍保持 paused，
                #      否则"暂停"只在本次运行有效，重开就自动恢复接单。
                _paused = _paused_seats
                for a in self._store.get_agents(rid):
                    _role = str(a.get("role_id") or "")
                    _st = str(a.get("state") or "")
                    if _role in _paused:
                        if _st in ("paused", "offline"):
                            continue
                        self._store.update_agent_state(
                            rid, _role, state="paused", current_task="")
                        n_seat += 1
                        continue
                    if _st in ("idle", "error", "offline"):
                        continue
                    self._store.update_agent_state(
                        rid, _role, state="idle", current_task="")
                    n_seat += 1
                # ③ 仅 status=running 的轮次需要关闭
                if run_status == "running":
                    self._store.finish_run(
                        rid, status="stopped",
                        summary="开机对账：上一进程遗留轮次已收口（无活跃 watcher）")
                    n_run += 1
        except Exception:
            traceback.print_exc()
        if n_run or n_task or n_seat:
            self._emit("reconcile_orphans",
                       {"runs_closed": n_run, "tasks_failed": n_task,
                        "seats_released": n_seat})
        return {"runs": n_run, "tasks": n_task, "seats": n_seat}

    # ============================================================
    # 订阅与传输
    # ============================================================
    def on_state(self, cb: Callable) -> None:
        self._state_cbs.append(cb)

    def on_event(self, cb: Callable) -> None:
        self._event_cbs.append(cb)

    def set_transport(self, port: Optional[int], token: Optional[str]) -> None:
        self._transport = {"sse_available": port is not None,
                           "port": port, "token": token}

    def transport(self) -> Dict[str, Any]:
        return dict(self._transport)

    # ============================================================
    # 资源解析（真实来源）
    # ============================================================
    def _engine(self):
        if self._engine_manager is not None:
            return self._engine_manager
        try:
            from shared.engine_manager import get_engine_manager
            self._engine_manager = get_engine_manager()
        except Exception:
            self._engine_manager = None
        return self._engine_manager

    def _orch(self):
        if self._orchestrator is not None:
            return self._orchestrator
        mgr = self._engine()
        if mgr is not None:
            try:
                self._orchestrator = mgr.get_sub_agent_orchestrator()
            except Exception:
                self._orchestrator = None
        if self._orchestrator is None:
            try:
                import importlib
                _m = None
                for mod in ("standard_mode.core.sub_agent_orchestrator",
                            "core.sub_agent_orchestrator"):
                    try:
                        _m = importlib.import_module(mod)
                        break
                    except Exception:
                        continue
                if _m is not None:
                    self._orchestrator = _m.SubAgentOrchestrator(max_concurrency=4)
                    self._orchestrator.register_builtin_roster()
            except Exception:
                self._orchestrator = None
        return self._orchestrator

    def _roles(self):
        from shared.role_system import get_role_manager
        return get_role_manager()

    # ============================================================
    # 事件（落库 + 回调 + 广播，真实 ts）
    # ============================================================
    def _emit(self, etype: str, payload: Dict[str, Any],
              run_id: Optional[int] = None, ts: Optional[float] = None) -> Dict[str, Any]:
        event = {"type": etype, "ts": float(ts if ts is not None else _now()),
                 "run_id": run_id if run_id is not None else self._run_id,
                 "payload": payload or {}}
        try:
            self._store.add_event(event["run_id"], etype, payload, ts=event["ts"])
        except Exception as e:
            print(f"[CompanyService] 事件落库失败({etype}): {e}")
        # ★ 结构化事件日志（JSONL，可检索；失败静默不影响主流程）
        try:
            from shared.jsonl_log import log_event
            log_event("company." + str(etype), run_id=event["run_id"],
                      payload=payload or {})
        except Exception:
            logger.debug("suppressed exception")
        for cb in list(self._event_cbs):
            try:
                cb(event)
            except Exception:
                traceback.print_exc()
        return event

    def _audit_denied(self, record: Dict[str, Any]) -> None:
        """bus 越权审计：audit_denied 事件必达（任务书第 18 条）。"""
        try:
            self._emit("audit_denied", record, run_id=self._run_id)
        except Exception:
            traceback.print_exc()

    def _notify_state(self) -> None:
        try:
            snapshot = self.state()
        except Exception:
            traceback.print_exc()
            return
        for cb in list(self._state_cbs):
            try:
                cb(snapshot)
            except Exception:
                traceback.print_exc()

    # ============================================================
    # create_run（规范 API）—— 开张：run + 9 工位 + 会话 + 授权
    # ============================================================
    def create_run(self, brief: str = "", config: Optional[Dict[str, Any]] = None,
                   start_instances: bool = False) -> Dict[str, Any]:
        with self._lock:
            # ★ 第19批（项 A4）: 允许多公司（run）并存 —— 不再因已有 running 而拒绝。
            #   如需串行，由调用方自行 stop；并存时各自任务/消息互不串。
            orch = self._orch()
            if orch is None:
                return {"ok": False, "error": "编排账本不可用（role_system/engine_manager 未就绪），无法开张"}
            stations = org.get_org()
            if len(stations) < 5:
                return {"ok": False, "error": f"role_system 名册不足（9 工位只生成 {len(stations)}），拒绝开张"}
            run_id = self._store.create_run(brief=brief, config=config)
            self._run_id = run_id
            self._started_perf = _now()
            self._paused = False
            self._stopped = False
            orch.register_builtin_roster()
            # 工位席 + 会话 + 授权（真实 mesh 会话 + session_acl 行）
            owner_sess = f"co_owner_r{run_id}"
            chief_sess = f"co_chief_r{run_id}"
            self._bus.register_session(owner_sess, title="owner（人类主体）", role="master")
            self._bus.register_session(chief_sess, title="CHIEF 总指挥",
                                       role="child", parent_id=owner_sess)
            self._bus.grant_link(owner_sess, chief_sess,
                                 {"can_peer_message": 0, "can_command": 1,
                                  "can_approve": 1, "can_handoff": 1})
            # ★ 第19批: owner 是人类主体，前端信封 from='owner'（角色名而非会话 ID），
            #   必须自带一条 (owner → 目标会话) 授权行，否则 command 闸 ACL_ROW_MISSING，
            #   派活不落库 → 消息页永远空态。
            self._bus.grant_link("owner", chief_sess,
                                 {"can_peer_message": 0, "can_command": 1,
                                  "can_approve": 1, "can_handoff": 1})
            self._store.create_session(run_id, owner_sess, kind="dm",
                                       topic="owner 控制台", members=["owner"])
            self._store.create_session(run_id, chief_sess, kind="dm",
                                       topic="CHIEF 总指挥", members=["orchestrator"])
            for rid, st in stations.items():
                self._store.upsert_agent(
                    run_id, rid, name=st["name"], whitelist=len(st["whitelist"]),
                    station=st["station"], dept=st["dept"], level=st["level"],
                    reports_to=st["reports_to"], caps=st["caps"])
                sess_id = f"co_agent_{rid}_r{run_id}"
                self._bus.register_session(sess_id, title=f"{st['title']} {st['name']}",
                                           role="child", parent_id=chief_sess)
                caps = dict(st["caps"])
                caps["can_command"] = 1   # 上级（CHIEF）对本工位有指令权
                self._bus.grant_link(chief_sess, sess_id, caps)
                # ★ 第20批: 工位间指令走角色名（信封 from 是 'orchestrator'），
                #   ACL 行 master 必须同时有角色名，否则总线 command 闸恒 ACL_ROW_MISSING。
                self._bus.grant_link("orchestrator", sess_id, caps)
                self._bus.grant_link("owner", sess_id,
                                     {"can_peer_message": 0, "can_command": 1,
                                      "can_approve": 0, "can_handoff": 0})
                self._store.create_session(run_id, sess_id, kind="dm",
                                           topic=st["title"], members=[rid, "owner"])
            # 部门主管 → 本部工位：指令权下放（真实 ACL 行）
            for rid, st in stations.items():
                if int(st["level"]) != 1:
                    continue
                mgr_sess = f"co_agent_{rid}_r{run_id}"
                for sub_rid, sub in stations.items():
                    if sub["reports_to"] == rid:
                        sub_sess = f"co_agent_{sub_rid}_r{run_id}"
                        self._bus.grant_link(mgr_sess, sub_sess,
                                             {"can_peer_message": 0, "can_command": 1,
                                              "can_approve": 0, "can_handoff": 0})
                        # ★ 第20批: 主管以角色名下指令同样要有 ACL 行
                        self._bus.grant_link(rid, sub_sess,
                                             {"can_peer_message": 0, "can_command": 1,
                                              "can_approve": 0, "can_handoff": 0})
            # 群聊 + 审批会话
            group_sess = f"co_group_r{run_id}"
            self._bus.register_session(group_sess, title="公司大群", role="master")
            self._store.create_session(run_id, group_sess, kind="group",
                                       topic="公司大群（manager 广播 / worker 汇报）",
                                       members=list(stations.keys()) + ["owner"])
            appr_sess = f"co_approvals_r{run_id}"
            self._bus.register_session(appr_sess, title="审批台", role="master")
            self._store.create_session(run_id, appr_sess, kind="approval",
                                       topic="审批台（owner/manager）",
                                       members=["owner"] + org.manager_ids())
            seat_err = ""
            if start_instances:
                seat_err = self._start_real_instances()
            event = self._emit("run_started", {
                "brief": brief, "stations": len(stations),
                "instances_note": seat_err or ("instances started" if start_instances
                                               else "instances not requested")})
            self._notify_state()
            return {"ok": True, "run_id": run_id, "event": event,
                    "stations": len(stations), "instances_note": seat_err,
                    "sessions": self._store.get_sessions(run_id=run_id)}

    def _start_real_instances(self) -> str:
        """真实拉起实例池（仅在明确要求时）；失败如实返回原因，不假装成功。"""
        try:
            from shared.multi_instance_manager import MultiInstanceManager
            mim = MultiInstanceManager()
            if not getattr(mim, "_mimo_exe_path", ""):
                return "mimo 可执行文件不存在，实例未拉起（席位用账本工位照常派发）"
            started = mim.start_all()
            return f"real instances started={started}"
        except Exception as e:
            return f"start_instances 失败: {e}"

    # ============================================================
    # brief 上传 → CHIEF 拆解 DAG（任务书第 11 条）
    # ============================================================
    def upload_brief(self, name: str, content: str,
                     uploaded_by: str = org.OWNER_ID) -> Dict[str, Any]:
        """上传策划书 → artifact(kind=brief) → CHIEF 拆解 → task DAG + 计划审批。"""
        with self._lock:
            if self._run_id is None:
                r = self.create_run(brief=str(name or "公司轮次"))
                if not r.get("ok"):
                    return r
            run_id = self._run_id
            art = self._store.add_artifact(
                run_id=run_id, task_id=None,
                role_id=str(uploaded_by or org.OWNER_ID), kind="brief",
                name=str(name or "brief"), content=str(content or ""),
                source=f"upload:{uploaded_by or org.OWNER_ID}")
            self._emit("artifact_created", {"artifact_id": art["id"],
                                            "kind": "brief", "name": art["name"],
                                            "version": art["version"],
                                            "source": art["source"]})
            dag = self._decompose(art)
            self._notify_state()
            return {"ok": True, "artifact": art, "dag": dag}

    def _decompose(self, brief_artifact: Dict[str, Any]) -> Dict[str, Any]:
        """CHIEF 拆解：RoleMatcher 真选角 → 任务树 → 计划审批（scope=manager）。

        拆解器本体是真实代码路径（角色匹配来自 role_system RoleMatcher，
        结构为 CHIEF 编排职责的确定性实现）；根任务的执行仍走真实引擎链。
        """
        run_id = self._run_id
        brief_text = str(brief_artifact.get("content") or "")
        root_id = self._store.create_task(
            run_id, role_id="orchestrator", kind="decompose", depth=0,
            parent_task_id=None, depends_on=[],
            description=f"[CHIEF 拆解] {brief_artifact.get('name')}："
                        f"{brief_text[:80]}")
        try:
            matched = self._roles().match_roles(brief_text, top_k=6)
        except Exception:
            matched = []
        # ★ 第19批（项 A1）: 工程关键词命中 → 纳入对应 L1 工位并排在 L2 之前
        _ENG = [
            (("前端", "页面", "界面", "UI", "vue", "react"), "frontend"),
            (("后端", "接口", "api", "服务端", "部署", "工程", "编码",
              "开发", "实现"), "backend"),
        ]
        _low = str(brief_text or "").lower()
        eng_hits = []
        for _kws, _rid in _ENG:
            if any(str(k).lower() in _low for k in _kws):
                if _rid not in eng_hits:
                    eng_hits.append(_rid)
        workers = []
        # 工程类：L1 主管先行
        for rid in eng_hits:
            if rid not in workers:
                workers.append(rid)
        # L2 执行岗
        for rid, _score in matched:
            st = org.get_station(rid)
            if st and int(st["level"]) >= 2 and rid not in workers:
                workers.append(rid)
        if not workers:                       # 匹配不出也如实给最小真实执行链
            workers = ["researcher"]
        work_ids = []
        for i, rid in enumerate(workers):
            tid = self._store.create_task(
                run_id, role_id=rid, kind="work", depth=1,
                parent_task_id=root_id, depends_on=[root_id],
                description=f"[拆解#{i+1}] {brief_text[:120]}")
            work_ids.append(tid)
        writer_id = self._store.create_task(
            run_id, role_id="writer", kind="proposal", depth=2,
            parent_task_id=root_id, depends_on=work_ids,
            description=f"[proposal] 依据 {len(work_ids)} 项拆解产出策划提案")
        verify_id = self._store.create_task(
            run_id, role_id="reviewer", kind="verify", depth=3,
            parent_task_id=writer_id, depends_on=[writer_id],
            description=f"[verify] 审查提案 artifact（不可发布未经审批）")
        # 计划审批先入账（scope=manager，执行前必过 manager 闸 —— 任务书第 12 条），
        # 再收束根任务：root 收束会触发 DAG 调度，此时 pending 审批会锁住派发。
        approval_id = self._store.create_approval(
            run_id, kind="plan", scope="manager", dept="product",
            requested_by="orchestrator",
            payload={"root": root_id, "work": work_ids,
                     "proposal": writer_id, "verify": verify_id,
                     "brief_artifact": brief_artifact["id"]},
            reason="CHIEF 拆解计划待产品主管批准后执行")
        # 根任务：拆解计划由本函数真实生成，立即按真实结果收束
        # ★ 本窗口（项 B2）: 不再写死 tokens=0，取任务行实参
        plan_text = (f"CHIEF 拆解 {brief_artifact.get('name')} → "
                     f"work:{workers} → proposal(writer) → verify(reviewer)")
        _root_row = self._store.get_task(root_id) or {}
        self._finalize_task_row(_root_row,
                                content=plan_text, error="",
                                tokens=int(_root_row.get("tokens") or 0))
        self._emit("approval_requested", {"approval_id": approval_id,
                                          "kind": "plan", "scope": "manager",
                                          "dept": "product",
                                          "requested_by": "orchestrator"})
        return {"root": root_id, "work": work_ids, "proposal": writer_id,
                "verify": verify_id, "approval_id": approval_id,
                "workers": workers}

    # ============================================================
    # assign（真实派发链 + DAG 闸）
    # ============================================================
    def assign(self, role_id: str, task: str, brief: str = "",
               skills: Optional[List[str]] = None,
               parent_task_id: Optional[int] = None,
               depends_on: Optional[List[int]] = None,
               kind: str = "work", task_row_id: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            if self._paused:
                return {"ok": False, "error": "公司已暂停（resume 后再派发）"}
            if not str(task or "").strip():
                return {"ok": False, "error": "任务描述为空"}
            orch = self._orch()
            if orch is None:
                return {"ok": False, "error": "编排账本不可用，无法派发"}
            if self._run_id is None and task_row_id is None:
                r = self.create_run(brief=brief or str(task)[:60])
                if not r.get("ok"):
                    return r
            run_id = self._run_id
            rm = self._roles()
            role = rm.get_role(str(role_id or ""))
            if task_row_id is None:
                task_row_id = self._store.create_task(
                    run_id, role_id=str(role_id or ""), description=str(task),
                    parent_task_id=parent_task_id, depends_on=depends_on,
                    kind=kind)
            if role is None:
                self._store.update_task(task_row_id, status="rejected",
                                        error=f"未知角色 role_id={role_id!r}",
                                        finished_ts=_now())
                self._emit("task_done", {"task_id": task_row_id, "role_id": role_id,
                                         "status": "rejected",
                                         "error": f"未知角色 role_id={role_id!r}",
                                         "elapsed_ms": 0})
                self._notify_state()
                return {"ok": False, "error": f"未知角色 role_id={role_id!r}（名册无此人）",
                        "task_id": task_row_id}
            # DAG 闸：依赖未满足 → 如实排队（pending），不假装执行
            if not self._store.deps_done(task_row_id):
                self._store.update_task(task_row_id, status="pending")
                return {"ok": True, "queued": True, "task_id": task_row_id,
                        "note": "DAG 依赖未满足，任务排队等待前置完成"}
            # 白名单闸门（真实判定 → rule_denied 事件）
            denied = []
            for sk in (skills or []):
                check = rm.check_skill(role.id, str(sk))
                if not check.get("allowed"):
                    denied.append(str(sk))
                    self._emit("rule_denied", {"role_id": role.id, "skill": str(sk),
                                               "reason": check.get("reason", "")})
            # 先确认有空闲工位再入账本（避免提交后绑不上的孤儿账本任务）；
            # 全忙 → 任务保持 pending，工位释放后由完成链自动重派
            seat = None
            if hasattr(orch, "_idle_agent_for_role"):
                seat = orch._idle_agent_for_role(role.id)
            if seat is None:
                self._store.update_task(task_row_id, status="pending")
                self._notify_state()
                return {"ok": True, "queued": True, "task_id": task_row_id,
                        "note": f"角色 {role.name} 工位全忙，任务排队（工位释放后自动重派）",
                        "denied_skills": denied}
            try:
                orch_tid = orch.submit_task(str(task), agent_id=role.id)
            except ValueError as e:
                self._store.update_task(task_row_id, status="rejected",
                                        error=str(e), finished_ts=_now())
                self._notify_state()
                return {"ok": False, "error": str(e), "task_id": task_row_id}
            bound = orch.assign_task(orch_tid)
            if bound is None:
                self._store.update_task(task_row_id, status="pending")
                self._notify_state()
                return {"ok": True, "queued": True,
                        "note": f"角色 {role.name} 工位全忙，任务排队（工位释放后自动重派）",
                        "orch_task_id": orch_tid, "task_id": task_row_id,
                        "role_id": role.id, "denied_skills": denied}
            # 引擎链：每员工模型/白名单覆盖（任务书第 14 条，真实传参）
            cfg = self.get_config()
            ov = (cfg.get("per_agent") or {}).get(role.id) or {}
            engine_name = str(ov.get("engine") or cfg.get("model_global") or "")
            wl_override = ov.get("skill_whitelist") or \
                (cfg.get("skill_whitelist") or {}).get(role.id) or []
            subagent_task_id = ""
            engine_note = ""
            # ★ 2026-11-23: 公司上下文真实注入 —— owner 维护的跨轮次上下文随 DoD 下发
            _company_ctx = str(cfg.get("company_context") or "").strip()
            _dod = brief
            if _company_ctx:
                _dod = (str(brief or "") + "\n\n[公司上下文]\n" + _company_ctx)[:6000]
            mgr = self._engine()
            if mgr is not None:
                try:
                    subagent_task_id = mgr.spawn_subagent(
                        name=role.name, task_description=str(task),
                        agent_id=role.id, dod=_dod,
                        engine_name=engine_name or "",
                        skill_whitelist=[str(s) for s in wl_override] or None,
                    ) or ""
                except Exception as e:
                    engine_note = f"spawn_subagent 异常: {e}"
                    subagent_task_id = ""
                if not subagent_task_id:
                    engine_note = engine_note or (
                        "引擎并发已满或引擎不可用，任务保留在账本工位（state=working），"
                        "真实执行回执将继续经完成监视链回写")
            if subagent_task_id:
                orch.mark_running(orch_tid, subagent_task_id)
            # ★ 收口 32: spawn 被拒（并发满）→ 任务回队 pending，
            #   由完成监视链在工位释放后自动重派 —— 旧行为把任务行标 running
            #   却不挂监视，造成「永远 running」卡死。
            #   ★ 引擎不可用（mgr=None）不同：账本工位真实占用、状态如实 working
            #   （真实执行待引擎接入回执），不回队（回队会死循环无触发源）。
            if not subagent_task_id and mgr is not None:
                # 释放已绑工位（bound=assign_task 返回的工位内部 id），
                # 否则工位永远占用 → 补派时 _idle_agent_for_role=None 饿死
                try:
                    if bound:
                        orch.release_agent(bound)
                except Exception as _re:
                    print(f"[CompanyService] 工位释放失败: {_re}")
                self._store.update_task(task_row_id, status="pending",
                                        error=engine_note or "",
                                        started_ts=None)
                self._notify_state()
                return {"ok": True, "queued": True, "task_id": task_row_id,
                        "orch_task_id": orch_tid, "role_id": role.id,
                        "note": "引擎并发已满，任务回队（工位释放后自动重派）",
                        "denied_skills": denied}
            started_ts = _now()
            self._store.update_task(task_row_id, status="running",
                                    subagent_task_id=subagent_task_id,
                                    orch_task_id=orch_tid,
                                    started_ts=started_ts)
            self._store.update_agent_state(run_id, role.id, state="working",
                                           current_task=str(task)[:120],
                                           runs_delta=1)
            self._emit("task_started", {
                "task_id": task_row_id, "orch_task_id": orch_tid,
                "subagent_task_id": subagent_task_id, "role_id": role.id,
                "description": str(task)[:200],
                "engine_note": engine_note, "denied_skills": denied},
                run_id=run_id)
            self._emit("agent_state", {"role_id": role.id, "state": "working",
                                       "current_task": str(task)[:120]},
                       run_id=run_id)
            if subagent_task_id:
                self._spawn_completion_watcher(task_row_id, orch_tid, role.id,
                                               subagent_task_id, started_ts)
            self._notify_state()
            return {"ok": True, "task_id": task_row_id, "orch_task_id": orch_tid,
                    "subagent_task_id": subagent_task_id, "role_id": role.id,
                    "engine_note": engine_note, "denied_skills": denied}

    def _spawn_completion_watcher(self, task_row_id: int, orch_task_id: str,
                                  role_id: str, subagent_task_id: str,
                                  started_ts: float) -> None:
        """真实回执监视：轮询 get_subagent_result 拿真实结果/耗时/tokens，回写七表。

        ★ 收口铁律：任何退出路径都必须落到终态。此前 mgr=None / 取不到回执 / 到点
          三处直接 return，任务永久停在 running（实测 company.db 45 条僵尸任务、
          111 个 running run），工位账本也不释放，后继 DAG 任务饿死。
        """
        def _watch():
            mgr = self._engine()
            deadline = started_ts + self._watch_timeout_seconds
            result = None
            while _now() < deadline:
                if mgr is None:
                    self._finalize_abandoned(
                        task_row_id,
                        "引擎管理器不可用（EngineManager 未接入），子代理从未执行")
                    return
                try:
                    result = mgr.get_subagent_result(subagent_task_id)
                except Exception:
                    result = None
                if result and result.get("status") not in ("running",):
                    break
                time.sleep(0.5)
                if self._run_id is None and self._stopped:
                    self._finalize_abandoned(
                        task_row_id, "公司轮次已停止，回执监视提前退出")
                    return
            if not result:
                self._finalize_abandoned(
                    task_row_id,
                    f"回执监视超时 {max(0, int(_now() - started_ts))}s"
                    f"（上限 {self._watch_timeout_seconds}s），"
                    f"子代理 {subagent_task_id} 始终无最终结果")
                return
            with self._lock:
                row = self._store.get_task(task_row_id)
                if row is None or str(row.get("status") or "") in _TERMINAL_TASK:
                    return           # 已被其它路径收口：幂等退出，绝不二次回写
                content = str(result.get("content") or "")
                error = str(result.get("error") or "")
                tokens = int(result.get("tokens") or 0)
                elapsed_ms = int((_now() - started_ts) * 1000)
                self._finalize_task_row(row, content=content, error=error,
                                        tokens=tokens, elapsed_ms=elapsed_ms,
                                        subagent_task_id=subagent_task_id,
                                        status=str(result.get("status") or ""),
                                        tools=result.get("tools") or [])
        t = threading.Thread(target=_watch, daemon=True,
                             name=f"company_watch_{task_row_id}")
        t.start()
        self._watchers.append(t)

    def _finalize_abandoned(self, task_row_id: int, reason: str) -> None:
        """监视线程无法取回执时的兜底收口：真实写 failed + 释放工位 + 继续调度。"""
        with self._lock:
            row = self._store.get_task(task_row_id)
            if row is None or str(row.get("status") or "") in _TERMINAL_TASK:
                return
            self._finalize_task_row(row, content="", error=reason, tokens=0,
                                    elapsed_ms=None, status="abandoned")


    def _finalize_task_row(self, row: Dict[str, Any], content: str, error: str,
                           tokens: int, elapsed_ms: Optional[int] = None,
                           subagent_task_id: str = "",
                           status: str = "",
                           tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """任务收束（watcher/complete/内部共用）：七表真写 + 依赖调度。

        ★ 成败判定：此前仅 `failed = bool(error)`，而引擎超时只写 content 不写
          error（engine_manager.get_subagent_result 的 timeout 分支）→ 超时被上报
          done。现在以引擎真实 status 为准，error 为辅。
        """
        task_id = int(row["id"])
        role_id = str(row["role_id"] or "")
        finished_ts = _now()
        if elapsed_ms is None:
            started = row.get("started_ts") or row.get("created_ts") or finished_ts
            elapsed_ms = max(0, int((finished_ts - started) * 1000))
        failed = bool(error) or (bool(status) and status not in _OK_SUBAGENT_STATUS)
        if not error and failed:
            error = f"引擎返回非成功态 status={status}"
        self._store.update_task(task_id,
                                status="failed" if failed else "done",
                                result="" if failed else content[:4000],
                                error=error, tokens=int(tokens or 0),
                                finished_ts=finished_ts, elapsed_ms=elapsed_ms,
                                subagent_task_id=subagent_task_id or row.get("subagent_task_id") or "")
        run_id = self._run_id
        if run_id is not None and role_id:
            # ★ 第18批（项 B2）: tokens>0 才计入 board.tokens；0 值标 pending，不静默
            self._store.update_agent_state(
                run_id, role_id,
                state="error" if failed else "idle", current_task="",
                tokens_delta=int(tokens or 0) if int(tokens or 0) > 0 else 0,
                completed_delta=0 if failed else 1,
                failed_delta=1 if failed else 0)
        # ★ 第18批（项 B1）: 父任务 tokens 回写为子任务之和（root 拆解任务同理）
        try:
            _parent = row.get("parent_task_id")
            if _parent:
                _sibs = [t for t in self._store.list_tasks(run_id)
                         if _parent in (t.get("depends_on") or [])]
                _psum = sum(int(t.get("tokens") or 0) for t in _sibs)
                _prow = self._store.get_task(_parent)
                if _prow is not None and _psum > int(_prow.get("tokens") or 0):
                    self._store.update_task(_parent, tokens=_psum)
        except Exception:
            logger.debug("suppressed exception")
        if content and not failed:
            art = self._store.add_artifact(
                run_id=run_id, task_id=task_id, role_id=role_id,
                kind=str(row.get("kind") or "work") if row.get("kind") != "work"
                else "report",
                name=f"{role_id or 'agent'}-{row.get('kind') or 'work'}-{task_id}",
                content=content[:8000], source=role_id or "task")
            self._emit("artifact_created", {"artifact_id": art["id"],
                                            "kind": art["kind"],
                                            "name": art["name"],
                                            "version": art["version"],
                                            "source": art["source"],
                                            "task_id": task_id})
        self._emit("task_done", {"task_id": task_id, "role_id": role_id,
                                 "status": "failed" if failed else "done",
                                 "error": error, "tokens": int(tokens or 0),
                                 "elapsed_ms": elapsed_ms,
                                 "subagent_task_id": subagent_task_id or row.get("subagent_task_id") or ""},
                   run_id=run_id)
        # ★ 伪 trace 修复：tool_call 事件用引擎回传的真实工具名与成败。
        #   此前用任务 kind 冒充工具名（writer/reviewer…），看板"工具留痕"全是假的。
        _tools = [t for t in (tools or []) if isinstance(t, dict) and t.get("name")]
        if _tools:
            for _t in _tools:
                self._emit("tool_call", {"role_id": role_id,
                                         "name": str(_t.get("name")),
                                         "ok": bool(_t.get("ok")),
                                         "elapsed_ms": elapsed_ms,
                                         "task_id": task_id,
                                         "tokens": int(tokens or 0),
                                         "inferred": False})
        else:
            # 引擎未回传工具清单（旧结果/纯文本回答）：如实标注推断，不冒充真实工具
            self._emit("tool_call", {"role_id": role_id,
                                     "name": str(row.get("kind") or "task"),
                                     "ok": not failed, "elapsed_ms": elapsed_ms,
                                     "task_id": task_id,
                                     "tokens": int(tokens or 0),
                                     "inferred": True})
        self._emit("agent_state", {"role_id": role_id,
                                   "state": "error" if failed else "idle",
                                   "current_task": ""}, run_id=run_id)
        # ★ 账本回执：释放工位（否则 _idle_agent_for_role 永远忙，DAG 后继任务饿死）
        orch_task_id = str(row.get("orch_task_id") or "")
        if orch_task_id:
            try:
                orch = self._orch()
                if orch is not None:
                    orch.complete_task(orch_task_id,
                                       result=(content[:200] or None) if not failed else None,
                                       error=error,
                                       tokens=int(tokens or 0))
            except Exception:
                traceback.print_exc()
        self._dispatch_ready_tasks()
        self._notify_state()
        return {"task_id": task_id, "status": "failed" if failed else "done",
                "elapsed_ms": elapsed_ms, "tokens": int(tokens or 0)}

    def _dispatch_ready_tasks(self) -> None:
        """DAG 调度：依赖已满足的 pending 任务真实派发（本轮次内）。

        闸门：存在 pending 的 plan 审批时整锁执行（拆解计划未经批准，一格都不动）。
        """
        if self._run_id is None:
            return
        for ap in self._store.get_approvals(run_id=self._run_id, status="pending"):
            if ap.get("kind") == "plan":
                return                     # 计划审批未决：执行整体锁定（任务书第 12 条）
        for t in self._store.get_tasks(self._run_id, status="pending"):
            if not self._store.deps_done(t["id"]):
                continue
            r = self.assign(role_id=t["role_id"], task=t["description"],
                            task_row_id=t["id"], kind=t.get("kind") or "work")
            if not r.get("ok"):
                print(f"[CompanyService] DAG 调度失败 task#{t['id']}: {r.get('error')}")

    # ============================================================
    # approve / reject（审批双闸：org 权限 + 审批行状态）
    # ============================================================
    def approve(self, approval_id: int, approver: str, reason: str = "") -> Dict[str, Any]:
        return self._respond(approval_id, "approved", approver, reason)

    def reject(self, approval_id: int, approver: str, reason: str = "") -> Dict[str, Any]:
        return self._respond(approval_id, "rejected", approver, reason)

    def _respond(self, approval_id: int, status: str, approver: str,
                 reason: str) -> Dict[str, Any]:
        with self._lock:
            ap = self._store.get_approval(int(approval_id))
            if ap is None:
                return {"ok": False, "error": f"审批单 #{approval_id} 不存在"}
            if ap["status"] != "pending":
                return {"ok": False, "error": f"审批单 #{approval_id} 已处理（{ap['status']}）"}
            ok, why = org.can_approve(str(approver or ""), ap["scope"], ap["dept"])
            if not ok:
                self._audit_denied({"code": "ACL_APPROVE_DENIED",
                                    "from": str(approver), "to": f"approval#{approval_id}",
                                    "type": "approval", "reason": why})
                return {"ok": False, "error": why, "code": "ACL_APPROVE_DENIED"}
            if not self._store.respond_approval(int(approval_id), status,
                                                str(approver), reason):
                return {"ok": False, "error": "审批单状态已变化（并发处理）"}
            self._emit("approval_response", {"approval_id": int(approval_id),
                                             "status": status,
                                             "approver": str(approver),
                                             "scope": ap["scope"],
                                             "reason": reason})
            side = self._approval_side_effects(ap, status, str(approver))
            self._notify_state()
            return {"ok": True, "approval_id": int(approval_id), "status": status,
                    "approver": str(approver), "side_effects": side}

    def _approval_side_effects(self, ap: Dict[str, Any], status: str,
                               approver: str) -> Dict[str, Any]:
        """审批后的真实副作用（按 kind 分派；全部真实执行）。"""
        if status != "approved":
            return {"note": "rejected —— 计划/产物不生效"}
        kind = ap.get("kind")
        payload = ap.get("payload") or {}
        if kind == "plan":
            self._store.update_run(self._run_id, phase="execute")
            before = len(self._store.get_tasks(self._run_id, status="pending"))
            self._dispatch_ready_tasks()
            after = len(self._store.get_tasks(self._run_id, status="pending"))
            return {"dispatched": before - after}
        if kind == "artifact":
            art_id = int(payload.get("artifact_id") or 0)
            ok = self._store.update_artifact_approver(art_id, approver)
            if ok:
                self._emit("artifact_approved", {"artifact_id": art_id,
                                                 "approver": approver})
            return {"artifact_finalized": ok}
        if kind == "config":
            return {"config_applied": self._apply_config(payload)}
        if kind == "irreversible":
            action = str(payload.get("action") or "")
            if action == "stop_company":
                r = self.stop(summary=f"owner 批准停转（approval#{ap['id']}）")
                return {"stopped": r.get("ok")}
            return {"note": f"未注册的不可逆操作 {action!r}，未执行"}
        return {"note": f"kind={kind} 无副作用"}

    # ============================================================
    # complete（规范 API）—— 任务人工/外部收束入口
    # ============================================================
    def complete(self, task_id: int, result: str = "", error: str = "",
                 tokens: int = 0) -> Dict[str, Any]:
        with self._lock:
            row = self._store.get_task(int(task_id))
            if row is None:
                return {"ok": False, "error": f"任务 #{task_id} 不存在"}
            if row["status"] in ("done", "failed"):
                return {"ok": False, "error": f"任务 #{task_id} 已收束（{row['status']}）"}
            if not self._store.deps_done(task_id) and not error:
                return {"ok": False, "error": "DAG 依赖未满足，不能提前收束"}
            out = self._finalize_task_row(row, content=str(result or ""),
                                          error=str(error or ""),
                                          tokens=int(tokens or 0))
            return {"ok": True, **out}

    # ============================================================
    # stop / pause / resume / send_back（兼容既有口径）
    # ============================================================
    def list_runs(self, limit: int = 20) -> Dict[str, Any]:
        """★ 第19批（项 A4）: 列出全部公司轮次（并存）。"""
        try:
            rows = self._store.list_runs(limit=limit)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "runs": rows,
                "active_run_id": self._run_id,
                "count": len(rows)}

    def switch_run(self, run_id: int) -> Dict[str, Any]:
        """★ 第19批（项 A4）: 切换到指定公司轮次（全量刷新）。"""
        with self._lock:
            run = self._store.get_run(int(run_id))
            if run is None:
                return {"ok": False, "error": f"run#{run_id} 不存在"}
            self._run_id = int(run_id)
            self._started_perf = _now()
            self._paused = False
            self._stopped = False
            # 重建该 run 的会话链路（消息/任务按 run 隔离）
            try:
                self._bus.register_session(f"co_owner_r{run_id}",
                                           title="owner（人类主体）", role="master")
                self._bus.register_session(f"co_chief_r{run_id}",
                                           title="CHIEF 总指挥",
                                           role="child",
                                           parent_id=f"co_owner_r{run_id}")
                self._bus.grant_link(f"co_owner_r{run_id}", f"co_chief_r{run_id}",
                                     {"can_peer_message": 0, "can_command": 1,
                                      "can_approve": 1, "can_handoff": 1})
            except Exception:
                logger.debug("suppressed exception")
            self._notify_state()
            return {"ok": True, "run_id": int(run_id),
                    "status": run.get("status"),
                    "brief": run.get("brief") or ""}

    def stop(self, summary: str = "") -> Dict[str, Any]:
        with self._lock:
            if self._run_id is None:
                return {"ok": False, "error": "没有进行中的公司轮次（先 create_run）"}
            st = self.stats()
            dur_ms = int((_now() - self._started_perf) * 1000)
            real_summary = summary or (
                f"units={st['units']} failed={st['broken']} rejected={st['rejected']} "
                f"rules={st['rules']} outputs={st['outputs']} 耗时{dur_ms}ms")
            self._store.finish_run(self._run_id, status="stopped",
                                   summary=real_summary)
            run_id = self._run_id
            self._run_id = None
            self._paused = False
            self._stopped = True
            event = self._emit("run_done", {"status": "stopped",
                                            "summary": real_summary,
                                            "duration_ms": dur_ms, "stats": st},
                               run_id=run_id)
            self._notify_state()
            return {"ok": True, "run_id": run_id, "duration_ms": dur_ms,
                    "stats": st, "event": event}

    def pause(self) -> Dict[str, Any]:
        with self._lock:
            if self._run_id is None:
                return {"ok": False, "error": "没有进行中的公司轮次"}
            if self._paused:
                return {"ok": False, "error": "已处于暂停状态"}
            self._paused = True
            self._store.update_run(self._run_id, status="paused")
            run_id = self._run_id
            for a in self._store.get_agents(run_id):
                self._store.update_agent_state(run_id, a["role_id"],
                                               state="paused",
                                               current_task=a["current_task"])
                self._emit("agent_state", {"role_id": a["role_id"],
                                           "state": "paused",
                                           "current_task": a["current_task"]},
                           run_id=run_id)
            self._notify_state()
            return {"ok": True, "run_id": run_id, "paused": True}

    def resume(self) -> Dict[str, Any]:
        with self._lock:
            if self._run_id is None:
                return {"ok": False, "error": "没有进行中的公司轮次"}
            if not self._paused:
                return {"ok": False, "error": "当前不在暂停状态"}
            self._paused = False
            self._store.update_run(self._run_id, status="running")
            run_id = self._run_id
            for a in self._store.get_agents(run_id):
                state = "working" if a["current_task"] else "idle"
                self._store.update_agent_state(run_id, a["role_id"], state=state,
                                               current_task=a["current_task"])
                self._emit("agent_state", {"role_id": a["role_id"], "state": state,
                                           "current_task": a["current_task"]},
                           run_id=run_id)
            self._notify_state()
            return {"ok": True, "run_id": run_id, "paused": False}

    def send_back(self) -> Dict[str, Any]:
        with self._lock:
            if self._run_id is None:
                return {"ok": False, "error": "没有进行中的公司轮次"}
            failed = self._store.get_tasks(self._run_id, status="failed")
            requeued = []
            for t in failed:
                reason = t.get("error") or "未说明"
                r = self.assign(role_id=t["role_id"],
                                task=f"{t['description']}\n[send back] 上次失败原因: {reason}\n"
                                     "[DOD 收窄] 只完成核心交付物。",
                                brief="")
                if r.get("ok"):
                    requeued.append(r.get("task_id"))
            self._notify_state()
            return {"ok": True, "requeued": len(requeued), "tasks": requeued}

    # 兼容别名：start == create_run（窗口3 看板口径）
    def start(self, brief: str = "", start_instances: bool = False) -> Dict[str, Any]:
        return self.create_run(brief=brief, start_instances=start_instances)

    # ============================================================
    # 文件交接（任务书第 13 条）：agent_container diff → artifact(patch)
    # ============================================================
    def _arbitrate(self, first_role: str, second_role: str,
                   path: str) -> tuple:
        """★ 第19批（项 A7）: 文件写冲突裁决。

        规则：role level 越小越优先（L1 主管 > L2 执行）；同级按写入时间先后。
        返回 (胜者, 败者, 理由)。
        """
        def _lvl(rid):
            st = org.get_station(rid)
            try:
                return int(st.get("level", 9))
            except Exception:
                return 9
        a, b = _lvl(first_role), _lvl(second_role)
        if a < b:
            return first_role, second_role, f"role level {a} < {b}（先级）"
        if b < a:
            return second_role, first_role, f"role level {b} < {a}（先级）"
        # 同级：先写者胜
        prev = getattr(self, "_file_change_log", {}).get(str(path)) or {}
        return (first_role, second_role, "同级按时间：先写者优先") \
            if str(prev.get("role_id")) == str(first_role) \
            else (second_role, first_role, "同级按时间：先写者优先")

    def record_file_change(self, role_id: str, path: str, old_text: str,
                           new_text: str, task_id: Optional[int] = None,
                           approver: str = "") -> Dict[str, Any]:
        """工位文件变更 → agent_container.compute_diff 真差异 → 版本化 patch 产物。

        compute_diff 返回 [(type, line)]（same/remove/add）—— 此处渲染为
        统一 diff 文本（'  '/'- '/'+ ' 前缀）落库，人可读、可审计。
        """
        from shared.agent_container import compute_diff
        with self._lock:
            # ★ 第19批（项 A7）: 文件写冲突仲裁
            #   同一 path 在 90s 内被另一工位写入 → orchestrator 按 role level
            #   （越小越优先；同级按时间）裁决，败方收 peer_message，落 ledger。
            _path = str(path or "")
            _prev = getattr(self, "_file_change_log", {}).get(_path)
            if _prev and _prev.get("role_id") != str(role_id or "") \
                    and time.time() - float(_prev.get("ts") or 0) < 90:
                _win, _lose, _reason = self._arbitrate(
                    str(_prev.get("role_id")), str(role_id or ""), _path)
                # ★ 空连接修复：此前调 self._store.add_message（CompanyStore 无此方法）
                #   + 裸调 _session_of_role（漏 self.，NameError），整段被 except pass 吞掉
                #   → 仲裁结论从未送达败方。改走总线真实投递，失败也不再静默。
                _notice = self.send_message({
                    "type": "task",
                    "from": self._session_of_role("orchestrator"),
                    "to": self._session_of_role(_lose),
                    "role": "orchestrator",
                    "task_id": str(task_id or ""),
                    "authorization": "command",
                    "authorized_by": self._session_of_role(_win),
                    "requires_approval": False,
                    "payload": (f"[仲裁] 文件 {os.path.basename(_path)} 写冲突，"
                                f"裁决胜方: {_win}（{_reason}）"),
                })
                if not _notice.get("ok"):
                    # 投递被 ACL 拒（例如同级不在上链）：显式记事件，不再静默丢弃
                    self._emit("arbitration_notice_denied", {
                        "file": os.path.basename(_path), "path": _path,
                        "winner": _win, "loser": _lose,
                        "code": _notice.get("code"), "error": _notice.get("error"),
                        "ts": time.time()})
                self._emit("arbitration_resolved", {
                    "file": os.path.basename(_path), "path": _path,
                    "winner": _win, "loser": _lose,
                    "parties": [_prev.get("role_id"), str(role_id or "")],
                    "reason": _reason, "ts": time.time()})
            pairs = compute_diff(str(old_text or ""), str(new_text or ""))
            lines = []
            for typ, line in pairs:
                prefix = {"same": "  ", "remove": "- ", "add": "+ "}.get(typ, "  ")
                lines.append(prefix + str(line))
            diff_text = "\n".join(lines)
            if not diff_text.strip():
                return {"ok": False, "error": "diff 为空（无真实变更），不落产物"}
            art = self._store.add_artifact(
                run_id=self._run_id, task_id=task_id, role_id=str(role_id or ""),
                kind="patch", name=os.path.basename(str(path or "file")),
                content=diff_text[:16000],
                source=f"file_change:{role_id}:{path}")
            self._emit("artifact_created", {"artifact_id": art["id"],
                                            "kind": "patch", "name": art["name"],
                                            "version": art["version"],
                                            "source": art["source"],
                                            "approver": art["approver"]})
            # ★ 第19批（项 A7）: 记录最近一次写，供冲突仲裁比对
            if not hasattr(self, "_file_change_log"):
                self._file_change_log = {}
            self._file_change_log[_path] = {"role_id": str(role_id or ""),
                                            "ts": time.time(),
                                            "artifact_id": art["id"]}
            self._notify_state()
            return {"ok": True, "artifact": art,
                    "note": "patch 产物待审批（artifact 审批通过才回填 approver）"}

    # ============================================================
    # ★ 收口项 21: 文件交接区 —— 跨会话可见，权限按部门隔离
    #   写入闸 = session_acl can_handoff（viewer 的真实授权行，fail-closed）；
    #   可见性 = 工位部门（org.dept_of）隔离：chief/owner 全部、部门主管按
    #   approvable_depts、同部门工位只看本部门。所有数据真实落 artifact 表
    #   （kind='handoff'），禁 mock。
    # ============================================================
    def _session_of_role(self, role_id: str) -> str:
        """工位/总指挥/owner → 真实 mesh 会话 id（ACL 行的 viewer 主体）。"""
        rid = str(role_id or "")
        if rid == "owner":
            return f"co_owner_r{self._run_id}"
        if rid == "orchestrator":
            return f"co_chief_r{self._run_id}"
        return f"co_agent_{rid}_r{self._run_id}"

    def handoff_file(self, role_id: str, name: str, content: str) -> Dict[str, Any]:
        """向交接区投递文件（can_handoff ACL 闸；部门随工位真实登记）。"""
        from shared.session_acl import check, deny_message
        with self._lock:
            sess = self._session_of_role(role_id)
            ok, code = check("handoff", sess)
            if not ok:
                self._audit_denied({"code": code, "from": sess, "to": "handoff",
                                    "type": "handoff", "reason": deny_message(code)})
                return {"ok": False, "error": deny_message(code), "code": code,
                        "http_status": 403}
            dept = org.dept_of(role_id) if org.get_station(role_id) else "command"
            art = self._store.add_artifact(
                run_id=self._run_id, task_id=None, role_id=str(role_id or ""),
                kind="handoff", name=str(name or "file"), content=str(content or "")[:16000],
                source=f"handoff:{dept}")
            self._emit("artifact_created", {"artifact_id": art["id"],
                                            "kind": "handoff",
                                            "name": art["name"], "dept": dept,
                                            "role_id": role_id})
            self._notify_state()
            return {"ok": True, "artifact": art, "dept": dept}

    def handoff_list(self, viewer_role: str = "") -> Dict[str, Any]:
        """交接区列表（跨会话可见；按部门隔离，越部门一律过滤 + 审计）。"""
        with self._lock:
            arts = self._store.get_artifacts(run_id=self._run_id, kind="handoff",
                                             limit=100)
            vr = str(viewer_role or "owner")
            if vr == "owner":
                allowed = "*"          # 人类主体：全部门可见（交接区审计口径）
                viewer_dept = "command"
            else:
                viewer_dept = org.dept_of(vr) if org.get_station(vr) else "command"
                lvl = org.level_of(vr) if org.get_station(vr) else 2
                if lvl == 0:
                    allowed = "*"      # chief：approvable_depts=["*"]
                elif lvl == 1:
                    st = org.get_station(vr) or {}
                    allowed = set(st.get("approvable_depts") or []) | {viewer_dept}
                else:
                    allowed = {viewer_dept}   # 工位：仅本部门
            out = []
            for a in arts:
                a_dept = (org.dept_of(a["role_id"])
                          if org.get_station(a["role_id"]) else "command")
                if allowed != "*" and a_dept not in allowed:
                    continue           # ★ 部门隔离：越部门交接件不可见
                row = dict(a)
                row["dept"] = a_dept
                out.append(row)
            return {"ok": True, "files": out, "viewer_dept": viewer_dept}

    # ============================================================
    # 配置（任务书第 14 条）：全局模型 + 每员工覆盖 + 白名单 + 矩阵 + 预算
    # ============================================================
    def get_config(self) -> Dict[str, Any]:
        cfg: Dict[str, Any] = {"model_global": "", "per_agent": {},
                               "budget": {"global_tokens": 0}}
        stored: Dict[str, Any] = {}
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                cfg.update(stored)
            else:
                stored = {}
        except Exception:
            stored = {}
        # 真源补全：白名单/预算默认来自 role_system + org（不落盘的口径实时取）
        whitelist, budgets = {}, {}
        for rid, st in org.get_org().items():
            whitelist[rid] = list(st["whitelist"])
            budgets[rid] = int(st["max_token_budget"])
        cfg.setdefault("skill_whitelist", whitelist)
        cfg.setdefault("budget", {})
        cfg["budget"].setdefault("per_agent_tokens", budgets)
        cfg["permission_matrix"] = org.permission_matrix()
        # ★ 集群B(项8): constraints 四键 —— 全部从真实组织/权限/任务推导，
        #   存盘覆盖优先（tests_first 可在 config.json 显式配置），无值如实 off。
        pm = cfg["permission_matrix"]
        peer_allowed = any(
            (m.get("caps") or {}).get("can_peer_message")
            for m in pm.values()) if pm else False
        tests_first = bool(stored.get("tests_first")) if isinstance(stored, dict) else False
        if not tests_first and self._run_id is not None:
            try:
                for t in self._store.get_tasks(self._run_id):
                    if str(t.get("kind") or "") in ("verify", "test"):
                        tests_first = True
                        break
            except Exception:
                logger.debug("suppressed exception")
        review_gate = "human" if any(
            (s.get("approval_scope") or []) for s in org.get_org().values()) else "manager"
        cfg["constraints"] = {
            "whitelist": "on" if any(whitelist.values()) else "off",
            "tests_first": "on" if tests_first else "off",
            "peer_msg": "allow" if peer_allowed else "deny",
            "review_gate": review_gate,
        }
        cfg.setdefault("mode", str(stored.get("mode") or "auto")
                       if isinstance(stored, dict) else "auto")
        # ★ 2026-11-23: 公司上下文库 —— 跨轮次共享的 owner 级上下文（可编辑、落盘）
        cfg.setdefault("company_context", str(stored.get("company_context") or "")
                       if isinstance(stored, dict) else "")
        return cfg

    def set_config(self, updates: Dict[str, Any],
                   via_approval: bool = True,
                   requested_by: str = org.OWNER_ID) -> Dict[str, Any]:
        """配置变更：默认走 owner 审批（不可逆动作）；direct 仅 owner 直改。"""
        if not isinstance(updates, dict) or not updates:
            return {"ok": False, "error": "配置更新为空"}
        if via_approval:
            approval_id = self._store.create_approval(
                self._run_id, kind="config", scope="owner",
                requested_by=str(requested_by), payload=updates,
                reason="配置变更需 owner 批准（全局模型/覆盖/预算）")
            self._emit("approval_requested", {"approval_id": approval_id,
                                              "kind": "config", "scope": "owner",
                                              "requested_by": requested_by})
            self._notify_state()
            return {"ok": True, "approval_id": approval_id,
                    "note": "配置变更已进入 owner 审批队列"}
        if str(requested_by) != org.OWNER_ID:
            return {"ok": False, "error": "直改配置仅限 owner 主体", "code": "ACL_APPROVE_DENIED"}
        return {"ok": True, "applied": self._apply_config(updates)}

    def _apply_config(self, updates: Dict[str, Any]) -> bool:
        cfg = {}
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        cfg.update({k: v for k, v in (updates or {}).items()
                    if k in ("model_global", "per_agent", "budget",
                             "skill_whitelist", "company_context")})
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        self._emit("config_updated", {"keys": sorted(updates.keys())})
        return True

    # ============================================================
    # 会话/消息（任务书第 15 条）：单聊/群聊/审批
    # ============================================================
    def send_message(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        try:
            r = self._bus.send(envelope)
        except BusError as e:
            return {"ok": False, "error": e.message, "code": e.code,
                    "http_status": e.http_status}
        if r.get("ok"):
            # ★ 第19批: 事件同时带角色口径 —— 图谱边以「角色对」为 key，
            #   而信封 from/to 可能是 owner 或会话 ID，直接配对永远错位（last 恒 —）。
            _from = str(envelope.get("from") or "")
            _to = str(envelope.get("to") or "")
            _from_role = _from if org.get_station(_from) else str(envelope.get("role") or "")
            _to_role = ""
            try:
                _sess = self._store.get_session(_to) or {}
                for _m in (_sess.get("members") or []):
                    if org.get_station(_m) is not None:
                        _to_role = str(_m)
                        break
            except Exception:
                logger.debug("suppressed exception")
            self._emit("message_sent", {"message_id": r.get("message_id"),
                                        "from": _from, "to": _to,
                                        "from_role": _from_role,
                                        "to_role": _to_role,
                                        "type": envelope.get("type")})
            self._notify_state()
        return r

    def inbox(self, session_id: str, since: float = 0.0) -> Dict[str, Any]:
        sess = self._store.get_session(session_id)
        if sess is None:
            return {"ok": False, "error": f"会话 {session_id!r} 不在台账", "http_status": 404}
        return {"ok": True, "session": sess,
                "messages": self._bus.inbox(session_id, since=since)}

    # ============================================================
    # state / stats / outputs（UI 快照 · 全真实）
    # ============================================================
    def current_run_summary(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self._run_id is None:
                return None
            return self._store.get_run(self._run_id)

    def _board(self) -> List[Dict[str, Any]]:
        """9 工位卡：org（真实档案）× 账本 team_board（真实状态）× agent 表。"""
        stations = org.get_org()
        orch = self._orch()
        board = {}
        if orch is not None:
            try:
                board = {b["role_id"]: b for b in orch.team_board()}
            except Exception:
                board = {}
        store_rows = {}
        if self._run_id is not None:
            try:
                store_rows = {a["role_id"]: a for a in self._store.get_agents(self._run_id)}
            except Exception:
                store_rows = {}
        cards = []
        for rid, st in stations.items():
            b = board.get(rid) or {}
            s = store_rows.get(rid) or {}
            cards.append({
                "role_id": rid,
                "name": st["name"],
                "station": st["station"],
                "title": st["title"],
                "dept": st["dept"],
                "level": st["level"],
                "reports_to": st["reports_to"],
                "caps": dict(st["caps"]),
                "duties": st["duties"],
                "color": st["color"],
                "icon_svg": st["icon_svg"],
                "state": b.get("state") or s.get("state") or "idle",
                "current_task": b.get("current_task") or s.get("current_task") or "",
                "tokens": int(b.get("tokens_used") or 0),
                "runs": int(b.get("runs") or 0),
                "completed": int(b.get("completed") or 0),
                "failed": int(b.get("failed") or 0),
                "whitelist": len(st["whitelist"]),
                "max_token_budget": st["max_token_budget"],
                "timeout_seconds": st["timeout_seconds"],
            })
        return cards

    def state(self) -> Dict[str, Any]:
        with self._lock:
            run = self.current_run_summary()
            run_id = self._run_id
            tasks = self._store.get_tasks(run_id) if run_id else []
            events = self._store.get_events(limit=60)
            # ★ 2026-11-23: 无当前轮次 → KPI 归零（不再把全库历史当本轮统计）
            st = self.stats(run_id) if run_id else self._store.stats(-1)
            orchestrator = None
            orch = self._orch()
            if orch is not None:
                try:
                    orchestrator = orch.get_status()
                except Exception:
                    orchestrator = None
            approvals = self._store.get_approvals(run_id=run_id)
            artifacts = self._store.get_artifacts(run_id=run_id, limit=30)
            sessions = self._store.get_sessions(run_id=run_id)
            # ★ 2026-11-23: 无当前轮次时只带最近 80 条会话（全量历史走 listSessions），
            #   否则 2000+ 会话把 state 撑到 ~580KB，QWebChannel 每 1.2s 推送会卡。
            if run_id is None and len(sessions) > 80:
                sessions = sessions[-80:]
            # ★ 集群B(项10): prior runs 的真实决策数（Σ 各轮 approval 行数）
            prior_runs = self._store.list_runs(limit=6)
            prior_decisions = 0
            for pr in prior_runs:
                try:
                    prior_decisions += len(self._store.get_approvals(run_id=pr["id"]))
                except Exception:
                    continue
            # 各会话最近一条真实信件（session_mesh）
            session_tails = {}
            for s in sessions[-24:]:
                try:
                    tail = self._bus.inbox(s["session_id"], limit=1)
                    session_tails[s["session_id"]] = tail[-1] if tail else None
                except Exception:
                    session_tails[s["session_id"]] = None
            return {
                "ts": _now_ms(),
                "run": run,
                "phase": (run or {}).get("phase", "start"),
                "paused": self._paused,
                "board": self._board(),
                "org": org.permission_matrix(),
                "stations_count": len(org.get_org()),
                "tasks": tasks[-40:],
                "dag": [t for t in tasks if t.get("parent_task_id") or t.get("kind") != "work"],
                "approvals": approvals,
                "artifacts": artifacts,
                "sessions": sessions,
                "session_tails": session_tails,
                "events": [{"id": e["id"], "type": e["type"], "ts": e["ts"],
                            "payload": e.get("payload", {})} for e in events],
                "stats": st,
                "orchestrator": orchestrator,
                "transport": self.transport(),
                "prior_runs": prior_runs,
                "prior_decisions": int(prior_decisions),
                "latest_outputs": self._store.get_artifacts(run_id=run_id, limit=12),
                "config": {k: v for k, v in self.get_config().items()
                           if k in ("model_global", "per_agent", "budget",
                                    "skill_whitelist", "permission_matrix",
                                    "constraints", "mode", "company_context")},
            }

    def stats(self, run_id: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            rid = run_id if run_id is not None else self._run_id
            return self._store.stats(rid)

    def outputs(self, role_id: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return self._store.get_artifacts(run_id=self._run_id,
                                             role_id=str(role_id or ""),
                                             limit=limit)

    def run_log(self, limit: int = 60) -> List[Dict[str, Any]]:
        with self._lock:
            return self._store.get_events(limit=limit)

    def approvals(self, status: str = "") -> List[Dict[str, Any]]:
        with self._lock:
            return self._store.get_approvals(run_id=self._run_id, status=status)

    def artifacts(self, kind: str = "", role_id: str = "") -> List[Dict[str, Any]]:
        with self._lock:
            return self._store.get_artifacts(run_id=self._run_id, kind=kind,
                                             role_id=role_id, limit=100)

    def tasks(self, status: str = "") -> List[Dict[str, Any]]:
        with self._lock:
            rid = self._run_id
            return self._store.get_tasks(rid, status=status) if rid else []

    def session_list(self, limit: int = 500) -> List[Dict[str, Any]]:
        """全量历史会话（倒序截断），供公司页「历史会话管理」使用。"""
        with self._lock:
            rows = self._store.get_sessions()
            try:
                n = int(limit or 0)
            except Exception:
                n = 500
            return rows[-n:] if n > 0 and len(rows) > n else rows

    def session_count(self) -> int:
        with self._lock:
            return int(self._store.count_sessions())


# ── 单例 ──────────────────────────────────────────────────────
_global_service: Optional[CompanyService] = None
_service_lock = threading.Lock()


def get_company_service(engine_manager=None, orchestrator=None,
                        db_path: str = "") -> CompanyService:
    global _global_service
    if _global_service is None:
        with _service_lock:
            if _global_service is None:
                _global_service = CompanyService(engine_manager=engine_manager,
                                                 orchestrator=orchestrator,
                                                 db_path=db_path)
    if engine_manager is not None and _global_service._engine_manager is None:
        _global_service._engine_manager = engine_manager
    if orchestrator is not None and _global_service._orchestrator is None:
        _global_service._orchestrator = orchestrator
    return _global_service
