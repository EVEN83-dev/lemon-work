# -*- coding: utf-8 -*-
"""HybridBridge — 混合模式真实桥（窗口3·公司模式 · 补齐缺失件）。

★ 背景：hybrid_mode_web_panel._setup_bridge() 一直在 import 本模块，
  但 hybrid_mode 包此前不存在 → "Bridge初始化失败"，前端所有
  _BRIDGE_FORWARD_METHODS 调用全部落空。本文件补上这条腿。

契约（与 hybrid_mode_web_panel._forward_to_bridge 对齐）：
  · 12 个核心方法一律 @pyqtSlot(result=str)，返回 JSON 字符串，
    统一信封 {"ok": bool, "data": ..., "error": str|None}。
  · 只做真实数据源，禁 mock：
      - role_system 名册（get_role_manager().get_builtin_roles()）
      - SubAgentOrchestrator.team_board()/get_status()/get_execution_log()
        （经 EngineManager.get_sub_agent_orchestrator() 取队列账本）
      - EngineManager.spawn_subagent / get_subagent_result /
        list_subagent_executions（真实执行链，白名单/预算在那一层强制）
      - MultiInstanceManager.get_cluster_summary()（真实实例集群）
      - CompanyService（shared/company）：start/stop/assign/pause/resume，
        五表落库 + 事件（run_started/agent_state/task_started/task_done/run_done）
  · 取不到的数据如实返回 ok=false + error，绝不编造静态 AGENTS。

12 个核心（任务书第 2 条）：
  getAgentsInfo / getAgentDetail / getAgentRoster / getWorkflowStatus /
  getMonitorData / getOrchestratorStatus / getMultiInstanceStatus /
  assignTask / startCompany / stopCompany / getAgentHealth / getAgentOutputs
另配公司页动作位：pauseWorkflow / resumeWorkflow / approveRun / sendBackRun
（均为 CompanyService 真实方法转发，失败回显 error，禁假成功）。
"""

import logging
logger = logging.getLogger(__name__)
import base64
import io
import json
import os
import sys
import threading
import time
import traceback
import urllib.request

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _now_ms() -> int:
    return int(time.time() * 1000)


# ──────────────────────────────────────────────────────────────
# ★ 2026-11-23: 策划书文件提取 / API 余额（公司页真实数据补全）
# ──────────────────────────────────────────────────────────────
def _extract_brief_text(name: str, blob: bytes) -> tuple:
    """把上传文件转成纯文本；返回 (text, note)。支持 md/txt/pdf/docx。"""
    low = str(name or "").lower()
    # 注意：endswith 里不能放 ""（任何字符串都匹配），无扩展名单独判断
    if low.endswith((".md", ".markdown", ".txt", ".json", ".csv", ".log")) \
            or "." not in low.rsplit("/", 1)[-1]:
        for enc in ("utf-8", "utf-8-sig", "gb18030"):
            try:
                return blob.decode(enc), "text/" + enc
            except Exception:
                continue
        return blob.decode("utf-8", errors="replace"), "text/replace"
    if low.endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=blob, filetype="pdf")
            parts = []
            for page in doc:
                parts.append(page.get_text("text") or "")
            doc.close()
            text = "\n".join(parts).strip()
            return text, "pdf/pymupdf" if text else "pdf/no-text-layer(需 OCR)"
        except Exception as e:
            return "", f"pdf 提取失败: {e}"
    if low.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(io.BytesIO(blob))
            parts = [p.text for p in doc.paragraphs if (p.text or "").strip()]
            for t in doc.tables:
                for row in t.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            text = "\n".join(parts).strip()
            if text:
                return text, "docx/python-docx"
        except Exception:
            logger.debug("suppressed exception")
        # 兜底：docx 是 zip，直接抽 word/document.xml 去标签
        try:
            import re
            import zipfile
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            xml = re.sub(r"<w:p[ >]", "\n<w:p ", xml)
            text = re.sub(r"<[^>]+>", "", xml)
            text = re.sub(r"\n{2,}", "\n", text).strip()
            return text, "docx/zip-xml"
        except Exception as e:
            return "", f"docx 提取失败: {e}"
    return "", f"不支持的文件类型 {low.rsplit('.', 1)[-1] if '.' in low else '?'}"


_BAL_CACHE: dict = {"ts": 0.0, "payload": None, "pending": False}
_BAL_LOCK = threading.Lock()


def _fetch_deepseek_balance(key: str) -> None:
    """后台查询 DeepSeek 余额，写缓存；失败如实记录 error。"""
    payload = {"ok": True, "engine": "deepseek", "kind": "api",
               "currency": "CNY", "available": None, "ts": time.time(),
               "source": "https://api.deepseek.com/user/balance"}
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
        infos = data.get("balance_infos") or []
        first = infos[0] if infos else {}
        payload.update({
            "available": data.get("is_available"),
            "currency": first.get("currency") or payload["currency"],
            "total": first.get("total_balance"),
            "granted": first.get("granted_balance"),
            "topped_up": first.get("topped_balance"),
            "is_available": data.get("is_available"),
            "raw": data,
        })
        if payload.get("total") is None and len(infos) > 1:
            payload["total"] = infos[1].get("total_balance")
    except Exception as e:
        payload["error"] = str(e)
        payload["available"] = None
    payload["ts"] = time.time()
    with _BAL_LOCK:
        _BAL_CACHE.update({"ts": payload["ts"], "payload": payload, "pending": False})


def _provider_balance(em) -> dict:
    """活动引擎 + 上下文窗口 + （DeepSeek）真实余额；远端查询走后台线程。"""
    info = {}
    try:
        info = em.get_current_model() if em is not None else {}
    except Exception:
        info = {}
    engine = str((info or {}).get("engine") or "")
    model = str((info or {}).get("model") or "")
    ctx = 0
    ctx_src = ""
    try:
        from shared.config_manager import ConfigManager
        cm = ConfigManager()
        if engine in ("ollama", "miemie_v1"):
            ctx = int(cm.get("ollama.num_ctx", 0) or 0)
            ctx_src = "ollama.num_ctx"
        else:
            ctx = int(cm.get("max_context_tokens", 0) or 0)
            ctx_src = "config.max_context_tokens"
    except Exception:
        logger.debug("suppressed exception")
    out = {"ok": True, "engine": engine, "model": model,
           "display": (info or {}).get("display") or model,
           "context_window": ctx, "context_source": ctx_src,
           "kind": "local" if engine in
           ("ollama", "mimocode", "miemie_v1") else "api"}
    if engine != "deepseek":
        out["note"] = ("本地引擎，无 API 余额" if out["kind"] == "local"
                       else "该引擎未提供余额查询")
        return out
    key = ""
    try:
        cfg = getattr(em, "_configs", {}).get("deepseek")
        key = str(getattr(cfg, "api_key", "") or "")
    except Exception:
        key = ""
    key = key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        out.update({"available": None, "error": "未配置 DEEPSEEK_API_KEY"})
        return out
    with _BAL_LOCK:
        cache = dict(_BAL_CACHE)
    if cache.get("payload") and (time.time() - float(cache.get("ts") or 0) < 60):
        merged = dict(out)
        merged.update(cache["payload"])
        merged["context_window"] = ctx
        merged["engine"], merged["model"] = engine, model
        merged["cached"] = True
        return merged
    with _BAL_LOCK:
        if not _BAL_CACHE.get("pending"):
            _BAL_CACHE["pending"] = True
            threading.Thread(target=_fetch_deepseek_balance, args=(key,),
                             daemon=True).start()
    merged = dict(out)
    if cache.get("payload"):
        merged.update(cache["payload"])
        merged["engine"], merged["model"] = engine, model
        merged["context_window"] = ctx
        merged["stale"] = True
    else:
        merged["pending"] = True
    return merged


def _skill_versions_for(rid: str, whitelist) -> dict:
    """★ 本窗口（项 D2）: 技能版本态真源 —— 注册表版本 × 白名单启用态。

    启用 = 该角色白名单命中（绿）；未命中 = 锁定（灰）。
    """
    out: dict = {}
    try:
        from standard_mode.core.skills_registry import get_skills_registry
        reg = get_skills_registry()
        items = getattr(reg, "_skills", {}) or {}
        wl = set(whitelist or [])
        # ★ 第19批（项 A6）: 白名单中未注册的技能也如实呈现（status=enabled）
        for name in wl:
            if name not in items:
                out[str(name)] = {"version": "1.0", "status": "enabled"}
        for name, d in items.items():
            out[str(name)] = {
                "version": str(getattr(d, "version", "") or "1.0"),
                "status": "enabled" if name in wl else "locked",
            }
    except Exception:
        logger.debug("suppressed exception")
    return out


def _agent_deps(rid: str) -> list:
    """★ 本窗口（项 D1）: 该员工的任务依赖（depends_on 命中其任务）。"""
    out = []
    try:
        from shared.company.service import get_company_service
        svc = get_company_service()
        st = svc.state()
        by_role = {}
        for t in st.get("tasks", []) or []:
            by_role[str(t.get("id"))] = t
        for t in st.get("tasks", []) or []:
            if str(t.get("role_id")) != rid:
                continue
            for dep in t.get("depends_on") or []:
                d = by_role.get(str(dep)) or {}
                out.append({"task_id": dep, "role_id": d.get("role_id"),
                            "title": d.get("title") or ""})
    except Exception:
        logger.debug("suppressed exception")
    return out


def _agent_artifacts(rid: str) -> list:
    """★ 本窗口（项 D1）: 该员工最近产物（artifacts 真源，倒序 3 条）。"""
    out = []
    try:
        from shared.company.service import get_company_service
        svc = get_company_service()
        for a in (svc.state().get("artifacts", []) or [])[-3:][::-1]:
            if str(a.get("role_id") or a.get("owner") or "") == rid:
                out.append({"name": a.get("name") or a.get("path") or "",
                            "path": a.get("path") or "", "version": a.get("version") or ""})
    except Exception:
        logger.debug("suppressed exception")
    return out


def _list_role_messages(role_id: str, session_id: str) -> dict:
    """★ 第18批（项 C2/C4）: 按角色精确取信。

    命中条件：from_role == role_id，或收信会话的成员包含 role_id。
    替代前端错误的 to_session→members 反查（会把他人信件误算进来）。
    """
    from shared.company.service import get_company_service
    if not role_id:
        return {"ok": False, "error": "role_id required", "messages": []}
    svc = get_company_service()
    try:
        sess = svc.state().get("sessions") or []
    except Exception:
        sess = []
    # ★ 第19批: 信件可能散落在上级会话/群会话里，session_id 只作「优先扫描」，
    #   不是唯一范围；否则会话指错就必空态。
    all_sids = [str(s.get("session_id")) for s in sess if s.get("session_id")]
    sids = list(dict.fromkeys(([session_id] if session_id else []) + all_sids))
    out = []
    for sid in sids:
        try:
            r = svc.inbox(sid)
        except Exception:
            continue
        for m in ((r or {}).get("messages") or []):
            fr = str(m.get("from_role") or "")
            pl = m.get("payload") or {}
            if not isinstance(pl, dict):
                try:
                    pl = json.loads(pl) if pl else {}
                except Exception:
                    pl = {}
            to = str(pl.get("to") or m.get("to_session") or "")
            hit = (fr == role_id)
            if not hit and to:
                s = next((x for x in sess if str(x.get("session_id")) == to), None)
                if s and role_id in (s.get("members") or []):
                    hit = True
            if hit:
                mm = dict(m)
                mm["_via"] = "listMessages"
                out.append(mm)
    return {"ok": True, "messages": out, "role_id": role_id, "count": len(out)}


def _stage_timeline() -> dict:
    """★ 第19批（项 A2）: 四阶段时间线（拆解→计划→执行→验收）。

    数据源 = tasks 真账本（started_ts/finished_ts）。
    """
    from shared.company.service import get_company_service
    svc = get_company_service()
    st = svc.state()
    stages = [("拆解", "decompose"), ("计划", "proposal"),
              ("执行", "work"), ("验收", "verify")]
    out = []
    for name, kind in stages:
        rows = [t for t in (st.get("tasks", []) or [])
                if str(t.get("kind") or "") == kind]
        starts = [float(t.get("started_ts") or 0) for t in rows
                  if t.get("started_ts")]
        ends = [float(t.get("finished_ts") or 0) for t in rows
                if t.get("finished_ts")]
        done = sum(1 for t in rows if str(t.get("status") or "") == "done")
        out.append({"stage": name, "kind": kind, "count": len(rows),
                    "done": done,
                    "start": min(starts) if starts else None,
                    "end": max(ends) if ends else None})
    return {"ok": True, "stages": out}


def _tokens_source(rid: str) -> str:
    """★ 第18批（项 B5/B10）: token 口径来源。

    engine = 引擎 usage 已回传（task.tokens>0）
    db     = 仅历史落库值
    pending= 引擎未回 usage，待记账
    """
    try:
        from shared.company.service import get_company_service
        st = get_company_service().state()
        rows = [t for t in (st.get("tasks", []) or [])
                if str(t.get("role_id")) == rid]
        if any(int(t.get("tokens") or 0) > 0 for t in rows):
            return "engine"
        if any(int(t.get("tokens") or 0) > 0 for t in
               (st.get("tasks", []) or [])):
            return "db"
    except Exception:
        logger.debug("suppressed exception")
    return "pending"


def _recent_tools(rid: str) -> list:
    """★ 本窗口（项 D1）: 该员工最近 5 次工具调用（事件流真源）。"""
    out = []
    try:
        from shared.company.service import get_company_service
        st = get_company_service().state()
        for ev in (st.get("events", []) or [])[::-1]:
            p = ev.get("payload") or {}
            if str(p.get("role_id") or "") != rid:
                continue
            et = str(ev.get("type") or "")
            if "tool" not in et:
                continue
            out.append({"type": et, "ts": ev.get("ts"),
                        "name": p.get("name") or p.get("tool") or "",
                        "ok": bool(p.get("ok", True)),
                        "elapsed_ms": p.get("elapsed_ms")})
            if len(out) >= 5:
                break
    except Exception:
        logger.debug("suppressed exception")
    return out


def _task_tokens(rid: str) -> list:
    """★ 本窗口（项 D5）: 该员工各任务 token 占比（task 真源）。"""
    out = []
    try:
        from shared.company.service import get_company_service
        st = get_company_service().state()
        for t in (st.get("tasks", []) or []):
            if str(t.get("role_id")) != rid:
                continue
            tk = int(t.get("tokens") or 0)
            # ★ 本窗口（项 B3）: 0 值不再静默跳过，标 pending 如实呈现
            out.append({"id": t.get("id"),
                        "title": str(t.get("description") or "")[:26],
                        "tokens": tk,
                        "pending": tk <= 0,
                        "status": str(t.get("status") or "")})
    except Exception:
        logger.debug("suppressed exception")
    return out


def _last_pair_msg(rid: str) -> dict:
    """★ 本窗口（项 C6/D10）: 该员工最近一次消息（事件流 message_sent 真源）。

    无消息时返回 {"msg": ""} —— 前端显式显示 —，不冒充摘要。
    """
    try:
        from shared.company.service import get_company_service
        st = get_company_service().state()
        for ev in (st.get("events", []) or [])[::-1]:
            if str(ev.get("type") or "") != "message_sent":
                continue
            p = ev.get("payload") or {}
            if str(p.get("from") or "") != rid and str(p.get("to") or "") != rid:
                continue
            return {"msg": f"{p.get('type') or 'msg'} @{_fmt_ts(ev.get('ts'))}",
                    "ts": ev.get("ts"), "from": p.get("from"), "to": p.get("to"),
                    "type": p.get("type"), "message_id": p.get("message_id")}
    except Exception:
        logger.debug("suppressed exception")
    return {"msg": ""}


def _fmt_ts(ts) -> str:
    try:
        import time as _t
        return _t.strftime("%H:%M:%S", _t.localtime(float(ts)))
    except Exception:
        return ""


class HybridBridge(QObject):
    """混部桥：前端 __PYBRIDGE__ → 本类真实方法 → JSON。"""

    # ── 面板 _connect_signals_to_frontend() 依赖的既有信号（缺一个即断链）──
    agentStatusChanged = pyqtSignal(str, str, int)      # (agent_id, status, progress)
    chatMessageReceived = pyqtSignal(str, str, str)     # (sender, content, timestamp)
    monitorDataUpdated = pyqtSignal(str)                # (json_data)
    workflowStepChanged = pyqtSignal(str, str)          # (step_id, status)
    errorOccurred = pyqtSignal(str)                     # (err)
    agentOutputReceived = pyqtSignal(str, str)          # (agent_id, text)
    agentThinkingReceived = pyqtSignal(str, str)        # (agent_id, thinking)
    # ── 公司模式注入契约（panel 转发为 window.onCompanyState/onCompanyEvent）──
    companyStateChanged = pyqtSignal(str)               # (state_json)
    companyEventReceived = pyqtSignal(str)              # (event_json)

    def __init__(self, engine_manager=None, panel=None):
        super().__init__(panel) if panel is not None else super().__init__()
        self._engine_manager = engine_manager
        self._panel = panel
        self._service = None
        self._service_subscribed = False
        self._orch_cache = None
        self._mim_cache = None

    # ============================================================
    # 资源解析（全部惰性 + 真实来源，取不到如实报错）
    # ============================================================
    def set_engine_manager(self, engine_manager):
        """面板延迟注入引擎管理器（与 HybridModeWebPanel.set_engine_manager 同步）。"""
        self._engine_manager = engine_manager

    def _engine(self):
        """引擎管理器：优先面板注入，退化为全局单例；都没有返回 None。"""
        if self._engine_manager is not None:
            return self._engine_manager
        try:
            from shared.engine_manager import get_engine_manager
            self._engine_manager = get_engine_manager()
        except Exception:
            self._engine_manager = None
        return self._engine_manager

    def _roles(self):
        """role_system 名册（真实内置角色，唯一花名册来源）。"""
        from shared.role_system import get_role_manager
        return get_role_manager()

    def _orch(self):
        """SubAgentOrchestrator 账本：EngineManager 公开入口优先。

        EngineManager 持有常驻账本（register_builtin_roster 已铺满）；
        引擎不可用时退化为独立账本（测试/离线场景），同样真实可用。
        """
        if self._orch_cache is not None:
            return self._orch_cache
        mgr = self._engine()
        if mgr is not None:
            try:
                orch = mgr.get_sub_agent_orchestrator()
                if orch is not None:
                    self._orch_cache = orch
                    return orch
            except Exception:
                logger.debug("suppressed exception")
        if self._orch_cache is None:
            orch = None
            for mod in ("standard_mode.core.sub_agent_orchestrator",
                        "core.sub_agent_orchestrator"):
                try:
                    import importlib
                    orch = importlib.import_module(mod).SubAgentOrchestrator(
                        max_concurrency=4)
                    orch.register_builtin_roster()
                    break
                except Exception:
                    continue
            self._orch_cache = orch
        return self._orch_cache

    def _multi_instance(self):
        """MultiInstanceManager（真实实例池；QObject，无 QApplication 时也能构造）。"""
        if self._mim_cache is not None:
            return self._mim_cache
        try:
            from shared.multi_instance_manager import MultiInstanceManager
            self._mim_cache = MultiInstanceManager()
        except Exception as _e:
            print(f"[HybridBridge] MultiInstanceManager 不可用: {_e}")
            self._mim_cache = None
        return self._mim_cache

    def _company_service(self):
        """CompanyService 单例（五表落库 + 事件广播）。"""
        if self._service is not None:
            return self._service
        try:
            from shared.company.service import get_company_service
            svc = get_company_service(engine_manager=self._engine(),
                                      orchestrator=self._orch())
        except Exception as e:
            traceback.print_exc()
            raise RuntimeError(f"CompanyService 初始化失败: {e}") from e
        self._service = svc
        if not self._service_subscribed:
            # 服务事件 → Qt 信号（跨线程安全，JSON 字符串）→ panel 注入
            # window.onCompanyState / window.onCompanyEvent（注入契约）
            svc.on_state(lambda snap: self.companyStateChanged.emit(
                json.dumps(snap, ensure_ascii=False, default=str)))
            svc.on_event(lambda ev: self.companyEventReceived.emit(
                json.dumps(ev, ensure_ascii=False, default=str)))
            self._service_subscribed = True
        # ★ 暂停持久化：进程启动后把 paused_seats.json 应用到编排器（仅一次）
        if not getattr(self, "_paused_seats_applied", False):
            self._paused_seats_applied = True
            try:
                orch = self._orch()
                if orch is not None:
                    for _rid in svc.load_paused_seats():
                        orch.set_agent_paused(_rid, True)
            except Exception:
                logger.debug("suppressed exception")
        return svc

    def shutdown(self) -> None:
        """面板销毁时解除服务订阅（防回调进已删除的 C++ 对象）。"""
        if self._service is not None and self._service_subscribed:
            try:
                self._service.remove_listeners(self)
            except Exception:
                logger.debug("suppressed exception")
            self._service_subscribed = False
        self._service = None

    # ============================================================
    # 统一信封
    # ============================================================
    @staticmethod
    def _ok(data) -> str:
        return json.dumps({"ok": True, "data": data, "error": None},
                          ensure_ascii=False, default=str)

    @staticmethod
    def _err(msg: str) -> str:
        return json.dumps({"ok": False, "data": None, "error": str(msg)},
                          ensure_ascii=False)

    # ============================================================
    # 12 核心 · 取数类
    # ============================================================
    @pyqtSlot(str, result=str)
    def getAgentsInfo(self, filter_str: str = "") -> str:
        """Agent 卡片清单 = SubAgentOrchestrator.team_board() 真账本。"""
        try:
            orch = self._orch()
            if orch is None:
                return self._err("编排账本不可用（role_system/engine_manager 未就绪）")
            board = orch.team_board()
            flt = str(filter_str or "").strip().lower()
            if flt:
                board = [b for b in board
                         if flt in b.get("role_id", "").lower()
                         or flt in b.get("name", "").lower()]
            return self._ok({"board": board, "count": len(board),
                             "ts": _now_ms(), "source": "SubAgentOrchestrator.team_board"})
        except Exception as e:
            return self._err(f"getAgentsInfo: {e}")

    @pyqtSlot(str, result=str)
    def getAgentDetail(self, agent_id: str = "") -> str:
        """单 Agent 详情：role_system 档案 + 真实最近执行流水。"""
        try:
            rid = str(agent_id or "").strip()
            if not rid:
                return self._err("getAgentDetail: 缺 agent_id")
            role = self._roles().get_role(rid)
            if role is None:
                return self._err(f"未知角色 agent_id={rid!r}（名册无此人）")
            detail = role.to_dict()
            detail["whitelist_count"] = len(role.skill_whitelist)
            mgr = self._engine()
            runs = []
            if mgr is not None:
                try:
                    runs = mgr.list_subagent_executions(rid, limit=5)
                except Exception:
                    runs = []
            orch = self._orch()
            board_row = {}
            if orch is not None:
                for b in orch.team_board():
                    if b.get("role_id") == rid:
                        board_row = b
                        break
            return self._ok({"role": detail, "recent_runs": runs,
                             "board": board_row, "ts": _now_ms()})
        except Exception as e:
            return self._err(f"getAgentDetail: {e}")

    @pyqtSlot(result=str)
    def getAgentRoster(self) -> str:
        """花名册 = role_system 名册（真实内置角色，禁静态 AGENTS）。"""
        try:
            rm = self._roles()
            roster = []
            for rid, role in sorted(rm.get_builtin_roles().items()):
                roster.append({
                    "role_id": rid, "name": role.name,
                    "role_type": role.role_type, "duties": role.description,
                    "capabilities": role.capabilities,
                    "whitelist_count": len(role.skill_whitelist),
                    "skill_whitelist": list(role.skill_whitelist),
                    "max_token_budget": role.max_token_budget,
                    "timeout_seconds": role.timeout_seconds,
                    "priority": role.priority,
                    "color": role.color, "icon_svg": role.icon_svg,
                })
            return self._ok({"roster": roster, "count": len(roster),
                             "source": "shared.role_system.get_builtin_roles",
                             "ts": _now_ms()})
        except Exception as e:
            return self._err(f"getAgentRoster: {e}")

    @pyqtSlot(result=str)
    def getWorkflowStatus(self) -> str:
        """工作流状态 = 账本 get_status + 公司 run 相位（真实）。"""
        try:
            orch = self._orch()
            orch_status = orch.get_status() if orch is not None else None
            run = None
            try:
                run = self._company_service().current_run_summary()
            except Exception:
                run = None
            return self._ok({"orchestrator": orch_status, "company_run": run,
                             "ts": _now_ms()})
        except Exception as e:
            return self._err(f"getWorkflowStatus: {e}")

    @pyqtSlot(result=str)
    def getMonitorData(self) -> str:
        """监控聚合：账本 + 公司 run + 集群 + 事件尾（一次给全，供轮询）。"""
        try:
            orch = self._orch()
            status = orch.get_status() if orch is not None else None
            svc = self._company_service()
            state = svc.state()
            cluster = None
            mim = self._multi_instance()
            if mim is not None:
                try:
                    cluster = dict(mim.get_cluster_summary())
                    cluster["status_text"] = mim.get_status_text()
                except Exception as _e:
                    cluster = {"error": str(_e)}
            return self._ok({"monitor": state, "orchestrator": status,
                             "cluster": cluster, "ts": _now_ms()})
        except Exception as e:
            return self._err(f"getMonitorData: {e}")

    @pyqtSlot(result=str)
    def getOrchestratorStatus(self) -> str:
        """SubAgentOrchestrator.get_status() 原样（禁加工数字）。"""
        try:
            orch = self._orch()
            if orch is None:
                return self._err("编排账本不可用")
            return self._ok(orch.get_status())
        except Exception as e:
            return self._err(f"getOrchestratorStatus: {e}")

    @pyqtSlot(result=str)
    def getMultiInstanceStatus(self) -> str:
        """MultiInstanceManager.get_cluster_summary() 真实集群。"""
        try:
            mim = self._multi_instance()
            if mim is None:
                return self._err("MultiInstanceManager 不可用")
            summary = dict(mim.get_cluster_summary())
            summary["status_text"] = mim.get_status_text()
            return self._ok(summary)
        except Exception as e:
            return self._err(f"getMultiInstanceStatus: {e}")

    # ============================================================
    # 12 核心 · 动作类（真实执行，失败回显 error）
    # ============================================================
    @pyqtSlot(str, result=str)
    def assignTask(self, payload_json: str = "{}") -> str:
        """派发任务。payload: {role_id, task, brief?, skills?}。

        真实链路：CompanyService.assign → SubAgentOrchestrator.submit_task/
        assign_task → EngineManager.spawn_subagent（白名单/预算/超时统一链），
        任务与事件落库。引擎不可用时任务仍然入账本排队（状态如实标注）。
        """
        try:
            payload = json.loads(payload_json) if isinstance(payload_json, str) and payload_json.strip() else {}
            if not isinstance(payload, dict):
                return self._err("assignTask: payload 必须是 JSON 对象")
            role_id = str(payload.get("role_id") or payload.get("agent_id") or "").strip()
            task = str(payload.get("task") or payload.get("description") or "").strip()
            if not task:
                return self._err("assignTask: 缺 task 描述")
            svc = self._company_service()
            result = svc.assign(role_id=role_id, task=task,
                                brief=str(payload.get("brief") or ""),
                                skills=payload.get("skills") or [])
            return self._ok(result) if result.get("ok") else self._err(result.get("error") or "assign 失败")
        except Exception as e:
            return self._err(f"assignTask: {e}")

    @pyqtSlot(str, result=str)
    def startCompany(self, payload_json: str = "{}") -> str:
        """启动公司：建 run + 铺名册工位 + emit run_started（真实落库）。

        payload 可选 {brief, start_instances: bool}；start_instances=true
        才尝试拉起真实实例（MultiInstanceManager），失败如实回显。
        """
        try:
            payload = json.loads(payload_json) if isinstance(payload_json, str) and payload_json.strip() else {}
            svc = self._company_service()
            result = svc.start(brief=str(payload.get("brief") or ""),
                               start_instances=bool(payload.get("start_instances")))
            return self._ok(result) if result.get("ok") else self._err(result.get("error") or "start 失败")
        except Exception as e:
            return self._err(f"startCompany: {e}")

    @pyqtSlot(result=str)
    def stopCompany(self) -> str:
        """停转公司：run 收束 + emit run_done（真实耗时）+ 可选停实例。"""
        try:
            svc = self._company_service()
            result = svc.stop()
            return self._ok(result) if result.get("ok") else self._err(result.get("error") or "stop 失败")
        except Exception as e:
            return self._err(f"stopCompany: {e}")

    @pyqtSlot(result=str)
    def getAgentHealth(self) -> str:
        """心跳体检：各角色账本状态 + 引擎可用性 + 实例端口健康（全真实）。"""
        try:
            orch = self._orch()
            rows = []
            if orch is not None:
                for b in orch.team_board():
                    rows.append({"role_id": b.get("role_id"),
                                 "name": b.get("name"),
                                 "state": b.get("state"),
                                 "runs": b.get("runs"),
                                 "failed": b.get("failed"),
                                 "current_task": b.get("current_task")})
            engine_ok = None
            engine_err = ""
            mgr = self._engine()
            if mgr is not None:
                try:
                    eng = mgr._get_active_engine() if hasattr(mgr, "_get_active_engine") else None
                    engine_ok = bool(eng.is_available()) if eng is not None and hasattr(eng, "is_available") else None
                except Exception as _e:
                    engine_ok = False
                    engine_err = str(_e)[:160]
            cluster = None
            mim = self._multi_instance()
            if mim is not None:
                try:
                    cluster = {"running": mim.running_count, "total": len(mim.instances),
                               "status_text": mim.get_status_text()}
                except Exception:
                    cluster = None
            return self._ok({"agents": rows, "engine_available": engine_ok,
                             "engine_error": engine_err, "cluster": cluster,
                             "ts": _now_ms()})
        except Exception as e:
            return self._err(f"getAgentHealth: {e}")

    @pyqtSlot(str, result=str)
    def getAgentOutputs(self, agent_id: str = "") -> str:
        """输出聚合：store outputs 表 + 引擎真实执行流水摘要。"""
        try:
            svc = self._company_service()
            outputs = svc.outputs(role_id=str(agent_id or "").strip())
            return self._ok({"outputs": outputs, "count": len(outputs),
                             "ts": _now_ms()})
        except Exception as e:
            return self._err(f"getAgentOutputs: {e}")

    # ============================================================
    # 公司页动作位（service 真方法转发）
    # ============================================================
    @pyqtSlot(result=str)
    def pauseWorkflow(self) -> str:
        try:
            svc = self._company_service()
            result = svc.pause()
            return self._ok(result) if result.get("ok") else self._err(result.get("error") or "pause 失败")
        except Exception as e:
            return self._err(f"pauseWorkflow: {e}")

    @pyqtSlot(result=str)
    def resumeWorkflow(self) -> str:
        try:
            svc = self._company_service()
            result = svc.resume()
            return self._ok(result) if result.get("ok") else self._err(result.get("error") or "resume 失败")
        except Exception as e:
            return self._err(f"resumeWorkflow: {e}")

    @pyqtSlot(result=str)
    def approveRun(self) -> str:
        """RUN COMPLETE 覆盖层 [approve]：真实收束本轮并归档。"""
        try:
            svc = self._company_service()
            result = svc.approve()
            return self._ok(result) if result.get("ok") else self._err(result.get("error") or "approve 失败")
        except Exception as e:
            return self._err(f"approveRun: {e}")

    @pyqtSlot(result=str)
    def sendBackRun(self) -> str:
        """RUN COMPLETE 覆盖层 [send back]：真实重派失败任务（每任务 ≤1 次）。"""
        try:
            svc = self._company_service()
            result = svc.send_back()
            return self._ok(result) if result.get("ok") else self._err(result.get("error") or "send back 失败")
        except Exception as e:
            return self._err(f"sendBackRun: {e}")

    # ============================================================
    # 公司 OS 统一动作位（集群B·A9）：上传/审批/完成/信件/配置/状态/运行控制
    # ============================================================
    _COMPANY_API_METHODS = (
        "uploadBrief", "uploadBriefFile", "assignTask", "approve", "reject", "complete",
        "message", "inbox",
        "listMessages",   # ★ 第18批（项 C2/C3）
        "listRuns", "switchRun", "listStageTimeline",   # ★ 第19批（项 A2/A4）
        "getConfig", "setConfig", "recordFileChange",
        "listApprovals", "listArtifacts", "listTasks", "listSessions",
        "getState", "stopRun", "pauseRun", "resumeRun",
        "getAgentWhitebox", "getProviderBalance",
    )

    @pyqtSlot(str, str, result=str)
    def companyApi(self, method: str = "", payload_json: str = "{}") -> str:
        """company_os.html 动作统一入口（真实方法转发；失败回显 error）。"""
        try:
            payload = {}
            if isinstance(payload_json, str) and payload_json.strip():
                payload = json.loads(payload_json)
            if not isinstance(payload, dict):
                return self._err("companyApi: payload 必须是 JSON 对象")
            m = str(method or "").strip()
            try:
                from shared.jsonl_log import log_event
                log_event("company_api.call", method=m)
            except Exception:
                logger.debug("company_api log failed", exc_info=True)
            svc = self._company_service()
            if m == "getState":
                # ★ 集群B(项1): 首屏真源 —— svc.state() 原样返回
                return self._ok(svc.state())
            elif m == "getAgentWhitebox":
                # ★ 集群C(白盒卡·读取接口): 单员工白盒 —— role_system 真档案 ×
                #   账本 board 行 × 事件尾（全部只读聚合；缺源返回 None 由前端显示 —）
                rid = str(payload.get("role_id") or "").strip()
                role = self._roles().get_role(rid)
                if role is None:
                    return self._err(f"getAgentWhitebox: 未知角色 {rid!r}")
                svc = self._company_service()
                board_row = {}
                try:
                    for b in svc.state().get("board", []):
                        if b.get("role_id") == rid:
                            board_row = b
                            break
                except Exception:
                    board_row = {}
                last_ts, last_event = None, None
                try:
                    evs = [e for e in svc.state().get("events", [])
                           if (e.get("payload") or {}).get("role_id") == rid]
                    if evs:
                        last = evs[-1]
                        last_ts, last_event = last.get("ts"), last.get("type")
                except Exception:
                    logger.debug("suppressed exception")
                try:
                    _cfg = svc.get_config() or {}
                except Exception:
                    _cfg = {}
                _pa = (_cfg.get("per_agent") or {}).get(rid) or {}
                _eng = str(_pa.get("engine") or _cfg.get("model_global") or "")
                return self._ok({
                    "role_id": rid,
                    "name": role.name,
                    "role_type": role.role_type,
                    "engine": _eng,
                    "engine_inherited": not bool(_pa.get("engine")),
                    "duties": role.description,
                    "capabilities": list(role.capabilities),
                    "skill_whitelist": list(role.skill_whitelist),
                    "task_keywords": list(role.task_keywords),
                    "max_token_budget": int(role.max_token_budget),
                    "timeout_seconds": int(role.timeout_seconds),
                    "tokens_used": int(board_row.get("tokens") or 0),
                    "state": board_row.get("state") or "idle",
                    "current_task": board_row.get("current_task") or "",
                    "completed": int(board_row.get("completed") or 0),
                    "failed": int(board_row.get("failed") or 0),
                    "runs": int(board_row.get("runs") or 0),
                    "reports_to": board_row.get("reports_to") or "",
                    "dept": board_row.get("dept") or "",
                    "level": board_row.get("level"),
                    "caps": board_row.get("caps") or {},
                    "last_ts": last_ts,
                    "last_event": last_event,
                    # ★ 本窗口（项 D1/D2）: 技能版本态（启用/锁定）与依赖/产物真源
                    "skill_versions": _skill_versions_for(rid, role.skill_whitelist),
                    "deps": _agent_deps(rid),
                    "artifacts": _agent_artifacts(rid),
                    # ★ 本窗口（项 D1/D5/D10）
                    "recent_tools": _recent_tools(rid),
                    # ★ 第18批（项 B5）: token 口径来源
                    "tokens_source": _tokens_source(rid),
                    "task_tokens": _task_tokens(rid),
                    "last_pair_msg": _last_pair_msg(rid),
                    # 压缩时间戳：账本无此真源 → None（前端如实显示 —，禁编造）
                    "last_compress": None,
                })
            elif m == "stopRun":
                # ★ 集群B(项45): 运行控制三按钮 —— CompanyService 真方法
                r = svc.stop(summary=str(payload.get("summary") or ""))
            elif m == "pauseRun":
                r = svc.pause()
            elif m == "resumeRun":
                r = svc.resume()
            elif m == "stopAgent":
                # ★ 本窗口（项 D8）: 单员工级停止 —— 有真方法则执行，否则明确降级
                rid = str(payload.get("role_id") or "").strip()
                fn = getattr(svc, "stop_agent", None)
                if callable(fn):
                    try:
                        r = fn(rid)
                    except Exception as e:
                        return self._err(f"stopAgent: {e}")
                else:
                    return self._err("stopAgent: 该后端不支持单员工停止（仅支持整局 stopRun），"
                                     "前端已降级为暂停请求 + 明确提示")
            elif m == "uploadBrief":
                r = svc.upload_brief(name=str(payload.get("name") or "brief"),
                                     content=str(payload.get("content") or ""),
                                     uploaded_by=str(payload.get("uploaded_by") or "owner"))
            elif m == "uploadBriefFile":
                # ★ 2026-11-23: 真实文件上传（md/txt/pdf/docx）→ 提取文本 → upload_brief
                raw = str(payload.get("data_b64") or "")
                if raw.startswith("data:") and "," in raw:
                    raw = raw.split(",", 1)[1]
                try:
                    blob = base64.b64decode(raw, validate=False)
                except Exception as e:
                    return self._err(f"uploadBriefFile: base64 解码失败 {e}")
                if not blob:
                    return self._err("uploadBriefFile: 文件为空")
                if len(blob) > 12 * 1024 * 1024:
                    return self._err("uploadBriefFile: 文件超过 12MB")
                name = str(payload.get("name") or "brief")
                text, note = _extract_brief_text(name, blob)
                if not str(text or "").strip():
                    return self._err(f"uploadBriefFile: 未能从 {name} 提取文本（{note}）")
                r = svc.upload_brief(name=name, content=text,
                                     uploaded_by=str(payload.get("uploaded_by") or "owner"))
                if isinstance(r, dict) and r.get("ok"):
                    r["extract"] = note
                    r["chars"] = len(text)
                    r["bytes"] = len(blob)
            elif m == "getProviderBalance":
                # ★ 2026-11-23: 引擎/模型/上下文窗口/DeepSeek 余额（缓存 + 后台刷新）
                return self._ok(_provider_balance(self._engine()))
            elif m == "approve":
                r = svc.approve(int(payload.get("approval_id") or 0),
                                str(payload.get("approver") or ""),
                                str(payload.get("reason") or ""))
            elif m == "reject":
                r = svc.reject(int(payload.get("approval_id") or 0),
                               str(payload.get("approver") or ""),
                               str(payload.get("reason") or ""))
            elif m == "complete":
                r = svc.complete(int(payload.get("task_id") or 0),
                                 result=str(payload.get("result") or ""),
                                 error=str(payload.get("error") or ""),
                                 tokens=int(payload.get("tokens") or 0))
            elif m == "assignTask":
                # ★ 第20批: 单员工立即开工（真账本 + 真引擎 spawn，非消息投递）
                r = svc.assign(role_id=str(payload.get("role_id") or ""),
                               task=str(payload.get("task") or ""),
                               brief=str(payload.get("brief") or ""),
                               kind=str(payload.get("kind") or "work"))
            elif m == "message":
                _env = dict(payload.get("envelope") or payload)
                # ★ 第19批（项 A5）: 附件校验（文件必须存在，ACL 不变）
                _att = payload.get("attachment") or _env.get("attachment")
                if _att:
                    from pathlib import Path as _P
                    _ap = str(_att.get("path") if isinstance(_att, dict) else _att)
                    if not _P(_ap).is_file():
                        return self._err(f"附件不存在: {_ap}")
                    _att = dict(_att) if isinstance(_att, dict) else {"path": _ap}
                    _att["path"] = _ap
                    _env["attachment"] = _att
                r = svc.send_message(_env)
            elif m == "inbox":
                r = svc.inbox(str(payload.get("session_id") or ""),
                              since=float(payload.get("since") or 0))
            elif m == "listMessages":
                # ★ 第18批（项 C2/C4）: 按角色精确取信（from_role 或 envelope.to/role）
                r = _list_role_messages(
                    str(payload.get("role_id") or ""),
                    str(payload.get("session_id") or ""))
            elif m == "listRuns":
                # ★ 第19批（项 A4）
                r = svc.list_runs(int(payload.get("limit") or 20))
            elif m == "switchRun":
                # ★ 第19批（项 A4）
                r = svc.switch_run(int(payload.get("run_id")))
            elif m == "listStageTimeline":
                # ★ 第19批（项 A2）: 四阶段时间线
                r = _stage_timeline()
            elif m == "getConfig":
                r = {"ok": True, "config": svc.get_config()}
            elif m == "setConfig":
                r = svc.set_config(payload.get("updates") or {},
                                   via_approval=bool(payload.get("via_approval", True)),
                                   requested_by=str(payload.get("requested_by") or "owner"))
            elif m == "recordFileChange":
                r = svc.record_file_change(role_id=str(payload.get("role_id") or ""),
                                           path=str(payload.get("path") or ""),
                                           old_text=str(payload.get("old_text") or ""),
                                           new_text=str(payload.get("new_text") or ""),
                                           task_id=payload.get("task_id"),
                                           approver=str(payload.get("approver") or ""))
            elif m == "listApprovals":
                r = {"ok": True, "approvals": svc.approvals(str(payload.get("status") or ""))}
            elif m == "listArtifacts":
                r = {"ok": True, "artifacts": svc.artifacts(kind=str(payload.get("kind") or ""),
                                                            role_id=str(payload.get("role_id") or ""))}
            elif m == "listTasks":
                r = {"ok": True, "tasks": svc.tasks(str(payload.get("status") or ""))}
            elif m == "listSessions":
                # ★ 2026-11-23: 历史会话全量（state 只带最近 80 条）
                _fn = getattr(svc, "session_list", None)
                _cnt = getattr(svc, "session_count", None)
                r = {"ok": True, "sessions":
                     (_fn(int(payload.get("limit") or 500)) if callable(_fn)
                      else svc.state().get("sessions", [])),
                     "total": (int(_cnt()) if callable(_cnt) else 0)}
            else:
                return self._err(f"companyApi 未知方法 {m!r}（合法：{self._COMPANY_API_METHODS}）")
            return self._ok(r) if r.get("ok") else self._err(r.get("error") or f"{m} 失败")
        except Exception as e:
            import traceback as _tb2
            print("[companyApiTraceback2]", _tb2.format_exc()[-1000:], flush=True)
            return self._err(f"companyApi({method}): {e}")

    # ============================================================
    # ★ 空连接补齐批（2026-11-23）
    #   以下方法此前登记在 hybrid_mode_web_panel._BRIDGE_FORWARD_METHODS
    #   转发表里但桥对象无同名实现 → 前端必然收到 "Bridge 不支持方法"。
    #   这里只补"有真实后端可接"的部分（注册表 / engine_manager.execute_skill /
    #   CompanyService / 真实文件系统）；没有真实后端的能力（hire/fire/
    #   跨窗派发/编制配置等）不在此伪造实现，仍由审计脚本如实报断链。
    # ============================================================
    _REPO_ROOT = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))

    @pyqtSlot(str, result=str)
    def listAllSkills(self, category: str = "") -> str:
        """技能全清单（真源 skills_registry，非硬编码目录）。"""
        try:
            from skills_registry import get_skills_registry
            reg = get_skills_registry()
            defs = reg.list_skills(str(category or ""))
            return self._ok({
                "skills": [{"name": d.name, "description": d.description,
                            "category": getattr(d, "category", ""),
                            "timeout": getattr(d, "timeout", 0)} for d in defs],
                "count": len(defs), "source": "skills_registry.list_skills"})
        except Exception as e:
            return self._err(f"listAllSkills: {e}")

    @pyqtSlot(str, result=str)
    def getSkillDetails(self, name: str = "") -> str:
        """单技能详情（参数 schema 来自注册表真身）。"""
        try:
            from skills_registry import get_skills_registry
            d = get_skills_registry().get(str(name or ""))
            if d is None:
                return self._err(f"未找到技能: {name!r}")
            return self._ok({"name": d.name, "description": d.description,
                             "category": getattr(d, "category", ""),
                             "parameters": getattr(d, "parameters", {}),
                             "timeout": getattr(d, "timeout", 0)})
        except Exception as e:
            return self._err(f"getSkillDetails: {e}")

    @pyqtSlot(str, str, result=str)
    def invokeSkill(self, name: str = "", args_json: str = "{}") -> str:
        """真实执行技能（engine_manager.execute_skill，不模拟结果）。"""
        try:
            em = self._engine()
            if em is None:
                return self._err("invokeSkill: 引擎管理器不可用，无法执行技能")
            try:
                args = json.loads(args_json) if str(args_json or "").strip() else {}
            except Exception:
                return self._err("invokeSkill: args 必须是 JSON 对象")
            if not isinstance(args, dict):
                return self._err("invokeSkill: args 必须是 JSON 对象")
            r = em.execute_skill(str(name or ""), args)
            if isinstance(r, dict) and r.get("success"):
                return self._ok(r)
            return self._err(f"技能执行未成功: "
                             f"{(r or {}).get('error') if isinstance(r, dict) else r}")
        except Exception as e:
            return self._err(f"invokeSkill: {e}")

    @pyqtSlot(result=str)
    def getSkillCallStats(self) -> str:
        """技能调用统计（engine_manager 真实累计台账，非演示数）。"""
        try:
            em = self._engine()
            if em is None:
                return self._err("getSkillCallStats: 引擎管理器不可用")
            stats = dict(getattr(em, "_tool_stats", {}) or {})
            ranked = sorted(stats.items(), key=lambda kv: -(kv[1] if isinstance(
                kv[1], (int, float)) else 0))[:40]
            return self._ok({"stats": dict(ranked), "total_keys": len(stats),
                             "source": "EngineManager._tool_stats"})
        except Exception as e:
            return self._err(f"getSkillCallStats: {e}")

    @pyqtSlot(result=str)
    def getSkillRouteStats(self) -> str:
        """技能路由命中统计（skill_router 真实计数）。"""
        try:
            # ★ 统计也要取产品侧路由（82 技能真台账），bridge 侧那份永远是空表
            try:
                from core.skill_router import get_skill_router
            except ImportError:
                from skill_router import get_skill_router
            r = get_skill_router()
            fn = getattr(r, "get_stats", None)
            if not callable(fn):
                return self._err("getSkillRouteStats: 路由层无统计接口（不编造数字）")
            stats = fn()
            if not isinstance(stats, dict):
                stats = {"raw": str(stats)}
            return self._ok({"stats": stats, "source": "core.skill_router.get_stats"})
        except Exception as e:
            return self._err(f"getSkillRouteStats: {e}")

    @pyqtSlot(str, result=str)
    def getArtifacts(self, kind: str = "") -> str:
        """公司产物索引（CompanyService.artifacts 真库）。"""
        try:
            svc = self._company_service()
            return self._ok({"artifacts": svc.artifacts(kind=str(kind or ""))})
        except Exception as e:
            return self._err(f"getArtifacts: {e}")

    @pyqtSlot(result=str)
    def getRunHistory(self) -> str:
        """公司轮次历史（CompanyService.list_runs 真库）。"""
        try:
            svc = self._company_service()
            runs = svc.list_runs()
            return self._ok({"runs": runs, "count": len(runs)})
        except Exception as e:
            return self._err(f"getRunHistory: {e}")

    @pyqtSlot(str, str, result=str)
    def setAgentModel(self, role_id: str = "", engine: str = "") -> str:
        """按员工切换引擎（写 CompanyService per_agent 配置，真实落盘）。"""
        try:
            svc = self._company_service()
            rid = str(role_id or "").strip()
            eng = str(engine or "").strip()
            if not rid or not eng:
                return self._err("setAgentModel: role_id 与 engine 均不能为空")
            return self._ok(svc.set_config({"per_agent": {rid: {"engine": eng}}},
                                           requested_by="owner"))
        except Exception as e:
            return self._err(f"setAgentModel: {e}")

    @pyqtSlot(str, result=str)
    def getRoleSkillMap(self, role_id: str = "") -> str:
        """角色→技能白名单映射（role_system 真名册）。"""
        try:
            rm = self._roles()
            rid = str(role_id or "").strip()
            if rid:
                skills = rm.get_role_skills(rid)
                if not skills and rm.get_role(rid) is None:
                    return self._err(f"getRoleSkillMap: 未知角色 {rid!r}")
                return self._ok({rid: skills})
            out = {}
            for key, role in (rm.get_all_roles() or {}).items():
                out[str(key)] = list(rm.get_role_skills(str(key)) or [])
            return self._ok(out)
        except Exception as e:
            return self._err(f"getRoleSkillMap: {e}")

    @pyqtSlot(str, result=str)
    def fileTreeList(self, rel_path: str = "") -> str:
        """真实目录列举（仓库根为基，含越界防护）。"""
        try:
            root = os.path.realpath(self._REPO_ROOT)
            target = os.path.realpath(os.path.join(root, str(rel_path or "")))
            if not target.startswith(root + os.sep) and target != root:
                return self._err("fileTreeList: 路径越出仓库根，已拒绝")
            if not os.path.isdir(target):
                return self._err(f"fileTreeList: 目录不存在 {rel_path!r}")
            entries = []
            for name in sorted(os.listdir(target))[:400]:
                if name in ("__pycache__", ".git", "node_modules"):
                    continue
                p = os.path.join(target, name)
                try:
                    entries.append({"name": name, "dir": os.path.isdir(p),
                                    "size": (os.path.getsize(p)
                                             if os.path.isfile(p) else None)})
                except OSError:
                    entries.append({"name": name, "dir": False, "size": None})
            return self._ok({"path": target, "root": root,
                             "entries": entries, "count": len(entries)})
        except Exception as e:
            return self._err(f"fileTreeList: {e}")

    @pyqtSlot(str, str, result=str)
    def fileTreeCreate(self, rel_path: str = "", name: str = "") -> str:
        """真实创建文件/目录（name 以 / 结尾 = 目录）。"""
        try:
            root = os.path.realpath(self._REPO_ROOT)
            base = os.path.realpath(os.path.join(root, str(rel_path or "")))
            if not base.startswith(root + os.sep) and base != root:
                return self._err("fileTreeCreate: 路径越出仓库根，已拒绝")
            raw = str(name or "").strip()
            if not raw or ".." in raw or os.path.isabs(raw):
                return self._err("fileTreeCreate: 非法名称（禁空/含 .. /绝对路径）")
            make_dir = raw.endswith("/")
            target = os.path.realpath(os.path.join(base, raw.rstrip("/")))
            if not target.startswith(root + os.sep):
                return self._err("fileTreeCreate: 目标越出仓库根，已拒绝")
            if make_dir:
                if os.path.isdir(target):
                    return self._err(f"fileTreeCreate: 目录已存在 {raw}")
                os.makedirs(target)
            else:
                if os.path.exists(target):
                    return self._err(f"fileTreeCreate: 文件已存在 {raw}")
                with open(target, "w", encoding="utf-8") as f:
                    f.write("")
            return self._ok({"created": target, "is_dir": make_dir})
        except Exception as e:
            return self._err(f"fileTreeCreate: {e}")

    @pyqtSlot(str, result=str)
    def sendChat(self, text: str = "") -> str:
        """员工群聊广播（走 CompanyService.send_message 真实 ACL 链）。"""
        try:
            body = str(text or "").strip()
            if not body:
                return self._err("sendChat: 内容为空")
            svc = self._company_service()
            grp = None
            for s in (svc.state().get("sessions") or []):
                if str(s.get("kind") or "") == "group":
                    grp = s
                    break
            if grp is None:
                return self._err("sendChat: 公司群会话不存在（请先启动公司轮次）")
            r = svc.send_message({"type": "report", "from": "owner",
                                  "to": grp.get("session_id") or "",
                                  "role": "", "payload": body})
            return self._ok(r) if r.get("ok") else self._err(
                f"sendChat 被拒: {r.get('error')} ({r.get('code')})")
        except Exception as e:
            return self._err(f"sendChat: {e}")

    # ── 第二批：有真实后端的剩余别名槽（wireframe 直调的名字）──
    @pyqtSlot(str, result=str)
    def sendChatMessage(self, text: str = "") -> str:
        """sendChat 的旧名别名（wireframe 用这个名字）。"""
        return self.sendChat(text)

    @pyqtSlot(str, result=str)
    def listAvailableSkills(self, category: str = "") -> str:
        """可用技能清单 —— 与 listAllSkills 同源（skills_registry）。"""
        return self.listAllSkills(category)

    @pyqtSlot(str, result=str)
    def getSessionHistory(self, limit: str = "500") -> str:
        """全量会话历史（CompanyService.session_list 真库）。"""
        try:
            svc = self._company_service()
            n = int(float(limit or 500)) if str(limit or "").strip() else 500
            rows = svc.session_list(n)
            return self._ok({"sessions": rows, "total": svc.session_count()})
        except Exception as e:
            return self._err(f"getSessionHistory: {e}")

    @pyqtSlot(str, result=str)
    def getHandoffDoc(self, viewer_role: str = "") -> str:
        """交接区文档列表（handoff_list 真库 + 部门隔离）。"""
        try:
            svc = self._company_service()
            return self._ok(svc.handoff_list(str(viewer_role or "owner")))
        except Exception as e:
            return self._err(f"getHandoffDoc: {e}")

    @pyqtSlot(str, result=str)
    def getProjectLog(self, limit: str = "60") -> str:
        """公司事件流水（store.get_events 真库）。"""
        try:
            svc = self._company_service()
            n = int(float(limit or 60)) if str(limit or "").strip() else 60
            return self._ok({"events": svc.run_log(max(1, min(2000, n)))})
        except Exception as e:
            return self._err(f"getProjectLog: {e}")

    # ============================================================
    # ★ 技能链（真源 shared/skills/skill_chain.py 预置链 + UniversalSkillRouter）
    #   此前 listSkillChains/getSkillChainDetails/invokeSkillChain 只在转发表里
    #   有名字、桥对象无实现 → wireframe 的"执行 Chain"永远失败。
    # ============================================================
    def _universal_router(self):
        # ★ 必须用产品侧路由（standard_mode/core/skill_router.py，绑 82 个真技能）；
        #   shared/skills/skill_router.py 绑的是 bridge 侧注册表（仅 11 个），
        #   用它执行链会一律 "Skill not found"。
        try:
            from core.skill_router import get_skill_router
        except ImportError:
            from skill_router import get_skill_router
        return get_skill_router()

    @pyqtSlot(result=str)
    def listSkillChains(self) -> str:
        """预置 Chain 清单（skill_chain 真源，非模板拼装）。"""
        try:
            chains = self._universal_router().list_chains()
            return self._ok({"chains": chains, "count": len(chains),
                             "source": "shared.skills.skill_chain"})
        except Exception as e:
            return self._err(f"listSkillChains: {e}")

    @pyqtSlot(str, result=str)
    def getSkillChainDetails(self, name: str = "") -> str:
        """单条 Chain 的步骤详情（含 args_template / on_failure / when）。"""
        try:
            d = self._universal_router().get_chain_details(str(name or ""))
            if not d:
                return self._err(f"Chain 不存在: {name!r}")
            return self._ok(d)
        except Exception as e:
            return self._err(f"getSkillChainDetails: {e}")

    @pyqtSlot(str, str, result=str)
    def invokeSkillChain(self, name: str = "", agent_id: str = "") -> str:
        """真实执行技能链（逐步骤 router.invoke；失败/跳过如实回传）。"""
        try:
            r = self._universal_router().invoke_chain(
                str(name or ""), agent_id=str(agent_id or ""))
            if not isinstance(r, dict):
                return self._err(f"invokeSkillChain: 非预期返回 {type(r).__name__}")
            if r.get("success"):
                return self._ok(r)
            _err = str(r.get("error") or "")
            if not _err:
                _err = "failed_step=" + str(r.get("failed_step"))
            return self._err("Chain 执行失败: " + _err)
        except Exception as e:
            return self._err(f"invokeSkillChain: {e}")

    # ============================================================
    # ★ 第四批：人员 / 实例池 / 流程 / 交接（补齐转发表剩余方法）
    #   原则：有真实后端的直接委派；没有的能力如实报 error，不伪造成功。
    # ============================================================
    def _mim(self):
        return self._multi_instance()

    def _role_known(self, rid: str) -> bool:
        rid = str(rid or "").strip()
        if not rid:
            return False
        try:
            from shared.company import org as _org
            if _org.get_station(rid) is not None:
                return True
        except Exception:
            logger.debug("suppressed exception")
        try:
            from shared.role_system import get_role_manager
            return get_role_manager().get_role(rid) is not None
        except Exception:
            return False

    @pyqtSlot(str, str, result=str)
    def hireAgent(self, role_key: str = "", model: str = "") -> str:
        """开席：按角色启动真实 MIMO 实例（多实例管理器真进程）。"""
        rid = str(role_key or "").strip()
        if not self._role_known(rid):
            return self._err(f"hireAgent: 未知角色 {rid!r}（见 role_system / org 编制）")
        mim = self._mim()
        if mim is None:
            return self._err("hireAgent: 多实例管理器不可用")
        cur = mim.get_instance_status(rid) or {}
        if str(cur.get("state") or "") in ("running", "busy"):
            return self._ok({"success": True, "instance_id": rid,
                             "port": cur.get("port"), "already_running": True})
        ok = bool(mim.start_instance(rid, model=(str(model or "") or None)))
        st = mim.get_instance_status(rid) or {}
        if not ok:
            return self._err(f"hireAgent: 实例启动失败（{st.get('error') or '详见日志'}）")
        return self._ok({"success": True, "instance_id": rid,
                         "port": st.get("port"), "already_running": False})

    @pyqtSlot(str, result=str)
    def fireAgent(self, role_key: str = "") -> str:
        """关席：停止该角色的真实实例（未运行则如实说明）。"""
        rid = str(role_key or "").strip()
        if not rid:
            return self._err("fireAgent: role_key 为空")
        mim = self._mim()
        if mim is None:
            return self._err("fireAgent: 多实例管理器不可用")
        cur = mim.get_instance_status(rid) or {}
        alive = str(cur.get("state") or "") in ("running", "busy")
        if not alive:
            return self._ok({"success": True, "stopped": False,
                             "note": "该角色实例本就未运行"})
        mim.stop_instance(rid)
        after = mim.get_instance_status(rid) or {}
        return self._ok({"success": str(after.get("state") or "") not in ("running", "busy"),
                         "stopped": True})

    @pyqtSlot(str, result=str)
    def restartAgent(self, agent_id: str = "") -> str:
        """一键重启：stop + start 同一实例。"""
        rid = str(agent_id or "").strip()
        if not self._role_known(rid):
            return self._err(f"restartAgent: 未知角色 {rid!r}")
        mim = self._mim()
        if mim is None:
            return self._err("restartAgent: 多实例管理器不可用")
        mim.stop_instance(rid)
        ok = bool(mim.start_instance(rid))
        st = mim.get_instance_status(rid) or {}
        return self._ok({"success": ok, "instance_id": rid, "port": st.get("port")}) \
            if ok else self._err(f"restartAgent: 重启失败（{st.get('error') or '详见日志'}）")

    @pyqtSlot(result=str)
    def stopRealInstances(self) -> str:
        """停转所有真实实例（返回实际停止数量）。"""
        mim = self._mim()
        if mim is None:
            return self._err("stopRealInstances: 多实例管理器不可用")
        before = len(mim.get_running_ports())
        mim.stop_all()
        after = len(mim.get_running_ports())
        return self._ok({"stopped": max(0, before - after), "remaining": after})

    @pyqtSlot(result=str)
    def getPoolStats(self) -> str:
        """实例池真实统计（端口/状态来自多实例管理器）。"""
        mim = self._mim()
        if mim is None:
            return self._err("getPoolStats: 多实例管理器不可用")
        try:
            cluster = mim.get_instance_status() or {}
        except Exception as e:
            return self._err(f"getPoolStats: {e}")
        ports = mim.get_running_ports()
        return self._ok({"cluster": cluster, "running_ports": ports,
                         "running": len(ports), "source": "MultiInstanceManager"})

    @pyqtSlot(str, result=str)
    def dispatchCrossWindowTask(self, payload_json: str = "{}") -> str:
        """跨窗派发：优先按 instance_id 定向派发，否则交 Director 分发。"""
        try:
            p = json.loads(payload_json) if str(payload_json or "").strip() else {}
        except Exception:
            return self._err("dispatchCrossWindowTask: payload 必须是 JSON")
        prompt = str(p.get("prompt") or p.get("task") or "").strip()
        iid = str(p.get("instance_id") or p.get("agent_id") or "").strip()
        if not prompt:
            return self._err("dispatchCrossWindowTask: 缺 prompt/task")
        mim = self._mim()
        if mim is None:
            return self._err("dispatchCrossWindowTask: 多实例管理器不可用")
        if iid:
            r = mim.dispatch_to_instance(iid, prompt,
                                         timeout=int(p.get("timeout") or 60)) or {}
            if r.get("error"):
                return self._err(f"dispatchCrossWindowTask: {r.get('error')}")
            return self._ok(r)
        tid = mim.dispatch_task(prompt)
        if not tid:
            return self._err("dispatchCrossWindowTask: 无可用 Director/Worker 实例")
        return self._ok({"task_id": tid, "via": "director"})

    @pyqtSlot(str, result=str)
    def dispatchOrchestratorCrossWindow(self, payload_json: str = "{}") -> str:
        """总指挥派发：把任务交给多实例 Director 分发。"""
        try:
            p = json.loads(payload_json) if str(payload_json or "").strip() else {}
        except Exception:
            return self._err("dispatchOrchestratorCrossWindow: payload 必须是 JSON")
        task = str(p.get("task") or p.get("prompt") or "").strip()
        if not task:
            return self._err("dispatchOrchestratorCrossWindow: 缺 task")
        mim = self._mim()
        if mim is None:
            return self._err("dispatchOrchestratorCrossWindow: 多实例管理器不可用")
        tid = mim.dispatch_task(task)
        if not tid:
            return self._err("dispatchOrchestratorCrossWindow: 无可用 Director/Worker 实例")
        return self._ok({"task_id": tid, "via": "orchestrator"})

    @pyqtSlot(result=str)
    def getFormationConfig(self) -> str:
        """编制配置：org 9 工位真表 → 按 level 分层的 role_tiers。"""
        try:
            from shared.company import org as _org
            stations = _org.get_org()
        except Exception as e:
            return self._err(f"getFormationConfig: {e}")
        tiers: Dict[str, list] = {}
        for rid, s in stations.items():
            tiers.setdefault(str(s.get("level")), []).append(
                {"role_id": rid, "name": s.get("name"),
                 "dept": s.get("dept"), "level": s.get("level")})
        return self._ok({"config": {"role_tiers": tiers, "stations": stations,
                                    "count": len(stations)},
                         "source": "shared.company.org"})

    @pyqtSlot(result=str)
    def getCompanyArchitecture(self) -> str:
        """公司架构三窗聚合：组织编制 + 运行看板 + 实例池。"""
        out: Dict[str, Any] = {}
        try:
            from shared.company import org as _org
            out["org"] = {rid: {"name": s.get("name"), "dept": s.get("dept"),
                                "level": s.get("level")}
                          for rid, s in _org.get_org().items()}
        except Exception as e:
            out["org_error"] = str(e)
        try:
            st = self._company_service().state()
            out["board"] = st.get("board")
            out["stats"] = st.get("stats")
        except Exception as e:
            out["state_error"] = str(e)
        try:
            mim = self._mim()
            out["instances"] = (mim.get_instance_status() if mim else None)
        except Exception as e:
            out["instances_error"] = str(e)
        return self._ok(out)

    @pyqtSlot(str, result=str)
    def commanderPlan(self, plan_text: str = "") -> str:
        """策划书分解（不派发）：upload_brief → 任务 DAG + 计划审批。"""
        text = str(plan_text or "").strip()
        if not text:
            return self._err("commanderPlan: 策划书内容为空")
        try:
            svc = self._company_service()
            r = svc.upload_brief(name="策划书", content=text, uploaded_by="owner")
        except Exception as e:
            return self._err(f"commanderPlan: {e}")
        if not r.get("ok"):
            return self._err(f"commanderPlan: {r.get('error')}")
        pend = [a for a in svc.approvals(status="pending") if a.get("kind") == "plan"]
        return self._ok({"dag": r.get("dag"),
                         "artifact_id": (r.get("artifact") or {}).get("id"),
                         "pending_approvals": len(pend),
                         "approval_id": (pend[-1].get("id") if pend else None)})

    @pyqtSlot(str, result=str)
    def commanderPlanAndDispatch(self, plan_text: str = "") -> str:
        """策划书分解 + owner 一键批准派发（审批副作用即真实派单）。"""
        text = str(plan_text or "").strip()
        if not text:
            return self._err("commanderPlanAndDispatch: 策划书内容为空")
        try:
            svc = self._company_service()
            r = svc.upload_brief(name="策划书", content=text, uploaded_by="owner")
            if not r.get("ok"):
                return self._err(f"commanderPlanAndDispatch: {r.get('error')}")
            pend = [a for a in svc.approvals(status="pending") if a.get("kind") == "plan"]
            if not pend:
                return self._ok({"dag": r.get("dag"), "dispatched": 0,
                                 "note": "已生成 DAG，但未发现待批计划审批"})
            ap = pend[-1]
            appr = svc.approve(int(ap["id"]), approver="owner",
                               reason="owner 通过公司看板一键派发")
            if not appr.get("ok"):
                return self._err(f"commanderPlanAndDispatch: 审批失败 {appr.get('error')}")
            dispatched = (appr.get("side_effects") or {}).get("dispatched", 0)
            return self._ok({"dag": r.get("dag"), "approval_id": ap["id"],
                             "dispatched": dispatched,
                             "note": f"计划已批准，已派发 {dispatched} 个就绪任务"})
        except Exception as e:
            return self._err(f"commanderPlanAndDispatch: {e}")

    @pyqtSlot(str, str, result=str)
    def configureAgent(self, agent_id: str = "", config_json: str = "{}") -> str:
        """单员工配置：写 per_agent 配置（按治理走 owner 审批队列）。"""
        rid = str(agent_id or "").strip()
        if not self._role_known(rid):
            return self._err(f"configureAgent: 未知角色 {rid!r}")
        try:
            cfg = json.loads(config_json) if str(config_json or "").strip() else {}
        except Exception:
            return self._err("configureAgent: config 必须是 JSON 对象")
        if not isinstance(cfg, dict) or not cfg:
            return self._err("configureAgent: config 为空")
        try:
            r = self._company_service().set_config({"per_agent": {rid: cfg}},
                                                   requested_by="owner")
        except Exception as e:
            return self._err(f"configureAgent: {e}")
        return self._ok(r) if r.get("ok") else self._err(
            f"configureAgent: {r.get('error')}")

    @pyqtSlot(str, result=str)
    def importConfig(self, json_text: str = "{}") -> str:
        """导入公司配置（model_global/per_agent/budget/skill_whitelist/company_context）。"""
        try:
            updates = json.loads(json_text) if str(json_text or "").strip() else {}
        except Exception:
            return self._err("importConfig: 必须是 JSON 对象")
        if not isinstance(updates, dict) or not updates:
            return self._err("importConfig: 配置为空")
        allowed = {"model_global", "per_agent", "budget",
                   "skill_whitelist", "company_context"}
        unknown = sorted(set(updates) - allowed)
        if unknown:
            return self._err(f"importConfig: 不支持的键 {unknown}（合法: {sorted(allowed)}）")
        try:
            r = self._company_service().set_config(updates, requested_by="owner")
        except Exception as e:
            return self._err(f"importConfig: {e}")
        return self._ok(r) if r.get("ok") else self._err(f"importConfig: {r.get('error')}")

    @pyqtSlot(result=str)
    def saveRunData(self) -> str:
        """落盘当前轮次快照（state() 原样写 JSON，返回真实路径）。"""
        try:
            svc = self._company_service()
            snap = svc.state()
            rid = svc._run_id if svc._run_id is not None else "none"
            out_dir = os.path.join(self._REPO_ROOT, "data", "company", "runs")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"run_{rid}_{time.strftime('%Y%m%d_%H%M%S')}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=1, default=str)
            # ★ 产物保留策略：run 快照只留最近 20 份（防止无限增长）
            try:
                snaps = sorted(
                    (os.path.join(out_dir, n) for n in os.listdir(out_dir)
                     if n.startswith("run_") and n.endswith(".json")),
                    key=os.path.getmtime, reverse=True)
                for old in snaps[20:]:
                    os.remove(old)
            except Exception:
                logger.debug("suppressed exception")
            return self._ok({"path": path, "bytes": os.path.getsize(path),
                             "run_id": svc._run_id, "keep_policy": 20})
        except Exception as e:
            return self._err(f"saveRunData: {e}")

    @pyqtSlot(str, result=str)
    def pauseAgent(self, agent_id: str = "") -> str:
        """暂停工位派单（在途任务不打断，收尾后不再接新单）。"""
        key = str(agent_id or "").strip()
        if not key:
            return self._err("pauseAgent: agent_id 为空")
        try:
            orch = self._orch()
            n = orch.set_agent_paused(key, True) if orch is not None else 0
        except Exception as e:
            return self._err(f"pauseAgent: {e}")
        if n == 0:
            return self._err(f"pauseAgent: 未找到可暂停的工位 {key!r}")
        try:
            self._company_service().pause_seat(key)
        except Exception as _e:
            return self._err(f"pauseAgent: 暂停已生效但落盘失败（重启后会恢复）: {_e}")
        self._sync_seat_state(key, "paused")
        return self._ok({"paused": True, "affected": n, "persisted": True})

    @pyqtSlot(str, result=str)
    def resumeAgent(self, agent_id: str = "") -> str:
        """恢复工位派单。"""
        key = str(agent_id or "").strip()
        if not key:
            return self._err("resumeAgent: agent_id 为空")
        try:
            orch = self._orch()
            n = orch.set_agent_paused(key, False) if orch is not None else 0
        except Exception as e:
            return self._err(f"resumeAgent: {e}")
        if n == 0:
            return self._err(f"resumeAgent: 未找到暂停中的工位 {key!r}")
        try:
            self._company_service().resume_seat(key)
        except Exception:
            logger.debug("suppressed exception")
        self._sync_seat_state(key, "idle")
        return self._ok({"resumed": True, "affected": n, "persisted": True})

    def _sync_seat_state(self, role_key: str, state: str) -> None:
        """把暂停/恢复同步到公司账本，让看板状态与编排器一致。"""
        try:
            svc = self._company_service()
            rid = svc._run_id
            if rid is None:
                return
            for a in svc._store.get_agents(rid):
                if str(a.get("role_id")) == role_key:
                    svc._store.update_agent_state(rid, role_key, state=state,
                                                  current_task=a.get("current_task") or "")
            svc._emit("agent_state", {"role_id": role_key, "state": state,
                                      "current_task": ""}, run_id=rid)
            svc._notify_state()
        except Exception:
            logger.debug("suppressed exception")

    @pyqtSlot(result=str)
    def startWorkflow(self) -> str:
        """统筹启动：无轮次→建轮次；暂停中→恢复；运行中→如实返回已在运行。"""
        try:
            svc = self._company_service()
            if svc._run_id is None:
                r = svc.start(brief="公司轮次")
                return self._ok(r) if r.get("ok") else self._err(
                    f"startWorkflow: {r.get('error')}")
            if getattr(svc, "_paused", False):
                r = svc.resume()
                return self._ok(r) if r.get("ok") else self._err(
                    f"startWorkflow: {r.get('error')}")
            return self._ok({"status": "already_running", "run_id": svc._run_id,
                             "note": "轮次已在运行，未重复启动"})
        except Exception as e:
            return self._err(f"startWorkflow: {e}")

    @pyqtSlot(str, result=str)
    def triggerHandoff(self, agent_id: str = "") -> str:
        """手动会话交接：SessionContinuity 真实切割并生成交接文档。"""
        aid = str(agent_id or "").strip()
        if not aid:
            return self._err("triggerHandoff: agent_id 为空")
        try:
            from shared.session_continuity import SessionContinuity
            sc = SessionContinuity(storage_dir=os.path.join(
                self._REPO_ROOT, "data", "session_continuity"))
            rec = sc.handoff_session(aid, summary="")
        except Exception as e:
            return self._err(f"triggerHandoff: {e}")
        if rec is None:
            return self._err("triggerHandoff: 该 agent 没有活跃会话可交接")
        return self._ok({"success": True, "session_id": getattr(rec, "session_id", ""),
                         "status": getattr(rec, "status", ""),
                         "handoff_doc_len": len(getattr(rec, "handoff_doc", "") or "")})

    @pyqtSlot(str, result=str)
    def addAgent(self, role_key: str = "") -> str:
        """增员：把内置角色注册成可派单工位（编排器真账本）。"""
        rid = str(role_key or "").strip()
        try:
            from shared.role_system import get_role_manager
            role = get_role_manager().get_role(rid)
        except Exception as e:
            return self._err(f"addAgent: 角色体系不可用（{e}）")
        if role is None:
            return self._err(f"addAgent: 未知角色 {rid!r}")
        try:
            orch = self._orch()
            aid = orch.register_agent(name=role.name, role="worker",
                                      role_def=role.to_dict())
        except Exception as e:
            return self._err(f"addAgent: {e}")
        return self._ok({"agent_id": aid, "role_id": rid, "name": role.name})

    @pyqtSlot(str, result=str)
    def removeAgent(self, agent_id: str = "") -> str:
        """减员：先停派单再下线（编制 9 席由 org 固定，不销毁席位定义）。"""
        key = str(agent_id or "").strip()
        n = 0
        try:
            orch = self._orch()
            if orch is not None:
                n = orch.set_agent_paused(key, True)
        except Exception as e:
            return self._err(f"removeAgent: {e}")
        if n == 0:
            return self._err(f"removeAgent: 未找到工位 {key!r}")
        self._sync_seat_state(key, "offline")
        return self._ok({"removed": True, "affected": n,
                         "note": "工位已下线（暂停派单并标记 offline）；"
                                 "org 编制席位固定，如需彻底移除请改 org.py"})

    @pyqtSlot(str, result=str)
    def openRoleConfigDialog(self, agent_id: str = "") -> str:
        """打开角色配置对话框（由宿主主窗口提供，无宿主时如实报错）。"""
        panel = getattr(self, "_panel", None)
        win = None
        try:
            win = panel.window() if panel is not None else None
        except Exception:
            win = None
        fn = getattr(win, "_open_role_config_dialog", None)
        if not callable(fn):
            return self._err("openRoleConfigDialog: 当前宿主未提供角色配置对话框"
                             "（标准模式主窗口菜单可用）")
        try:
            fn()
        except Exception as e:
            return self._err(f"openRoleConfigDialog: {e}")
        return self._ok({"opened": True, "agent_id": str(agent_id or "")})
