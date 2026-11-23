# -*- coding: utf-8 -*-
"""CompanyBus — 公司消息总线（集群B·A9 · 任务书第 5/6/18 条）。

真实复用：
  · 消息正文本体走 session_mesh.store.add_message/list_messages（chat.db 真落盘，
    会话档案经 upsert_session 真登记）；
  · 越权判定走 shared.session_acl.check（公司工位能力位新动作：
    peer_message / command / approve / handoff），deny 必产生 ACL 审计。

信封（任务书第 6 条）：
  {type, from, to, role, task_id, authorization, requires_approval, payload}
  type ∈ task | result | report | approval | handoff

路由铁律（fail-closed，全部真实判定，禁 mock）：
  · type=task（指令）：仅"上级→下级"且授权行 can_command=1 才放行；
    同级互发 task 一律 403（同级消息只作 request）——audit_denied 事件必达；
  · peer_message：工位互传看授权行 can_peer_message（公司默认 0）——
    消息不等于授权；
  · report：下级→上级汇报链（reports_to 链）与群广播里的汇报永远放行；
  · 群聊广播：仅 manager 级（L≤1）可发；worker 在群里只能 report；
  · handoff：看授权行 can_handoff；
  · approval：审批请求按 scope 路由（manager→主管链；owner→人类主体），
    审批响应校验 org.can_approve + ACL can_approve 双闸。
"""

import logging
logger = logging.getLogger(__name__)
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

from shared.company import org
from shared.company.store import CompanyStore

MSG_TYPES = ("task", "result", "report", "approval", "handoff")


class BusError(Exception):
    """总线拒绝。code 供 HTTP 层映射 403/400；文案供 UI 直接展示。"""

    def __init__(self, code: str, message: str, http_status: int = 403):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class CompanyBus:
    """公司消息总线。audit 回调收到 {code, from, to, type, reason} 必达。"""

    def __init__(self, store: CompanyStore,
                 audit: Optional[Callable[[Dict[str, Any]], None]] = None):
        self._store = store
        self._audit_cb = audit

    # ── 真实存储层（session_mesh） ──
    def _mesh_store(self):
        from session_mesh import store as mesh_store
        return mesh_store

    def register_session(self, session_id: str, title: str = "",
                         role: str = "master", parent_id: str = "") -> Dict[str, Any]:
        """会话档案真登记（chat_session；公司 session 台账由 service 维护）。"""
        return self._mesh_store().upsert_session(session_id, title=title,
                                                 role=role, parent_id=parent_id)

    def grant_link(self, master: str, child: str, caps: Dict[str, int]) -> Dict[str, Any]:
        """主管→工位授权行（真实 session_acl 行；缺省位全 0）。"""
        from shared.session_acl import set_acl
        return set_acl(master, child,
                       can_read=1, can_write=1,
                       child_can_read_master=1, child_can_write_master=1,
                       can_peer_message=int(caps.get("can_peer_message", 0)),
                       can_command=int(caps.get("can_command", 0)),
                       can_approve=int(caps.get("can_approve", 0)),
                       can_handoff=int(caps.get("can_handoff", 0)))

    # ────────────────────────────────────────────────────────────
    # 发送（唯一入口）
    # ────────────────────────────────────────────────────────────
    def send(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        mtype = str(envelope.get("type") or "").strip()
        sender = str(envelope.get("from") or "").strip()
        recv = str(envelope.get("to") or "").strip()
        role_id = str(envelope.get("role") or "").strip()
        try:
            payload = envelope.get("payload")
            if isinstance(payload, str):
                payload = json.loads(payload) if payload.strip() else {}
        except Exception:
            payload = {"raw": str(envelope.get("payload"))[:200]}

        if mtype not in MSG_TYPES:
            raise BusError("BUS_BAD_TYPE", f"未知消息类型 {mtype!r}（合法：{MSG_TYPES}）", 400)
        if not sender or not recv:
            raise BusError("BUS_BAD_ENVELOPE", "信封缺 from/to", 400)
        if sender == recv:
            raise BusError("BUS_SELF_LOOP", "消息不能发给自己", 400)
        # ★ 第19批（项 A5）: 附件（路径 + 类型）——合并进 payload，随信封落库
        _att = envelope.get("attachment")
        if _att:
            envelope = dict(envelope)
            if isinstance(_att, str):
                _att = {"path": _att}
            _att = dict(_att or {})
            envelope["attachment"] = {
                "path": str(_att.get("path") or ""),
                "type": str(_att.get("type") or
                            ("image" if str(_att.get("path", "")).lower().endswith(
                                (".png", ".jpg", ".jpeg", ".gif", ".webp")) else "file")),
                "name": str(_att.get("name") or os.path.basename(
                    str(_att.get("path") or ""))),
            }
        sess = self._store.get_session(recv)
        if sess is None:
            raise BusError("BUS_NO_SESSION", f"收件会话 {recv!r} 不在该公司会话台账", 400)
        sender_station = org.get_station(role_id) if role_id else None
        if role_id and sender_station is None:
            raise BusError("BUS_UNKNOWN_ROLE", f"发送方角色 {role_id!r} 不在 9 工位编制内", 403)

        recv_role = self._session_role(recv)

        # ① 指令（task）：上级→下级 + can_command 双闸；同级一律 403（只作 request）
        #    群聊例外：manager 级广播即授权（任务书第 15 条），worker 仍被 ⑤ 拦
        if mtype == "task":
            if sess.get("kind") == "group":
                if sender_station is None or int(sender_station["level"]) > 1:
                    self._deny("BUS_GROUP_WORKER_BROADCAST", sender, recv, mtype,
                               "群聊仅 manager 可下发，执行层只能汇报（report）")
            else:
                self._guard_task(sender, recv, role_id, recv_role, envelope)

        # ② 工位互传（同级任意类型）：can_peer_message 闸（默认 0）
        if sender != "owner" and recv_role and sender_station \
                and org.peer_level(role_id, recv_role) and mtype != "report":
            allowed, code = self._acl("peer_message", sender, recv)
            if not allowed:
                self._deny(code, sender, recv, mtype,
                           "同级互传未授权（消息不等于授权）")
        if sender != "owner" and recv_role and sender_station \
                and org.peer_level(role_id, recv_role) and mtype == "task":
            # 同级消息只作 request：即便授权互传，task 也不是指令 —— 强制降级
            envelope = dict(envelope)
            envelope["authorization"] = "peer_request"
            envelope["requires_approval"] = True

        # ③ handoff：can_handoff 闸
        if mtype == "handoff":
            allowed, code = self._acl("handoff", sender)
            if not allowed:
                self._deny(code, sender, recv, mtype, "交接权未授权")

        # ④ approval 响应：can_approve + org 双闸
        if mtype == "approval" and str(envelope.get("authorization")) == "response":
            self._guard_approval(envelope, role_id, recv_role)

        # ⑤ 群聊广播：仅 manager 级可发；worker 在群里只能 report
        if sess.get("kind") == "group" and sender_station \
                and int(sender_station["level"]) >= 2 and mtype != "report":
            self._deny("BUS_GROUP_WORKER_BROADCAST",
                       sender, recv, mtype,
                       "群聊仅 manager 可广播，执行层只能汇报（report）")

        # ⑥ 汇报链（report）：worker 只能沿 reports_to 链向上或群发
        if mtype == "report" and sender_station and recv_role:
            if not self._is_upchain(role_id, recv_role) and sess.get("kind") != "group":
                self._deny("BUS_REPORT_OFFCHAIN",
                           sender, recv, mtype,
                           "汇报只能沿 reports_to 链向上（越级汇报按审计处理）")

        # 真投递：session_mesh.add_message（chat.db）+ 事件
        msg = self._mesh_store().add_message(
            session_id=recv, from_role=sender, kind=mtype,
            payload=self._envelope_json(envelope), to_session=recv)
        return {"ok": True, "message_id": msg["msg_id"],
                "from": sender, "to": recv, "type": mtype,
                "ts": msg["created_at"]}

    # ────────────────────────────────────────────────────────────
    def inbox(self, session_id: str, since: float = 0.0,
              limit: int = 100) -> List[Dict[str, Any]]:
        """读收件箱（session_mesh 真信件）。"""
        return self._mesh_store().list_messages(session_id, since=since,
                                                limit=limit)

    def send_group_report(self, role_id: str, sender: str, body: Any,
                          run_id: Optional[int] = None) -> Dict[str, Any]:
        """worker 在群聊里汇报的唯一合法动作（type=report → group session）。"""
        group = self._find_group(run_id)
        if group is None:
            raise BusError("BUS_NO_GROUP", "公司群会话不存在", 400)
        return self.send({"type": "report", "from": sender, "to": group["session_id"],
                          "role": role_id, "task_id": "", "authorization": "report",
                          "requires_approval": False, "payload": body})

    # ────────────────────────────────────────────────────────────
    # 内部闸门
    # ────────────────────────────────────────────────────────────
    def _acl(self, action: str, viewer: str, target: str = ""):
        from shared.session_acl import check
        return check(action, viewer, target)

    def _guard_task(self, sender: str, recv: str, role_id: str, recv_role: str,
                    envelope: Optional[Dict[str, Any]] = None):
        s = org.get_station(role_id) if role_id else None
        r = org.get_station(recv_role) if recv_role else None
        if s is None:
            self._deny("BUS_UNKNOWN_ROLE", sender, recv, "task",
                       f"发送方角色 {role_id!r} 不在编制内，禁发指令")
        if r is None:
            self._deny("BUS_UNKNOWN_ROLE", sender, recv, "task",
                       f"收件方 {recv_role or recv!r} 不在 9 工位编制内")
        # ★ 第19批: owner 是人类主体（不在 9 工位编制），天然具备最高指令权，
        #   不参与「同级/自上而下」工位层级判定，只校验 can_command 行与授权链。
        if sender != "owner":
            same_level = org.peer_level(role_id, recv_role)
            upward = int(s["level"]) < int(r["level"])
            if same_level:
                self._deny("ACL_PEER_MESSAGE_DENIED", sender, recv, "task",
                           "同级消息只作 request，不得互发指令（消息不等于授权）")
            if not upward:
                self._deny("ACL_COMMAND_DENIED", sender, recv, "task",
                           "指令只能自上而下（上级→下级）")
        allowed, code = self._acl("command", sender, recv)
        if not allowed:
            self._deny(code, sender, recv, "task", "指令权未授权（can_command=0）")
        # ★ 收口项 18：消息≠授权 —— command 必须携带 authorized_by 授权链
        #   （owner / 发送方上链角色 / 已批准审批单 approval:N 三种真实引用），
        #   缺链或引用非法一律拒绝并审计。send_message（非指令类）不受此闸。
        self._guard_authorized_by(envelope or {}, sender, recv, role_id)

    def _guard_authorized_by(self, envelope: Dict[str, Any], sender: str,
                             recv: str, role_id: str):
        """★ 收口项 18：authorized_by 授权链校验（缺链拒绝 + 审计）。

        合法引用（真实可解析，禁拍脑袋）：
          · "owner"                        —— 人类主体显式授权
          · 发送方上链角色 id（reports_to 链）—— 该上级的授权
          · "approval:N"                   —— 已批准审批单引用
        """
        auth_by = str(envelope.get("authorized_by") or "").strip()
        if not auth_by:
            self._deny("BUS_MISSING_AUTHORIZATION", sender, recv, "task",
                       "指令缺少 authorized_by 授权链（消息≠授权，须注明授权来源）")
        if auth_by.lower() == "owner":
            return
        m = auth_by.lower().startswith("approval:")
        if m:
            ap_id = auth_by.split(":", 1)[1].strip()
            ap = self._store.get_approval(ap_id) if ap_id.isdigit() else None
            if ap is None or str(ap.get("status") or "") != "approved":
                self._deny("BUS_MISSING_AUTHORIZATION", sender, recv, "task",
                           f"authorized_by 引用的审批单 {auth_by!r} 不存在或未批准")
            return
        # 上链角色引用：authorized_by 必须在发送方 reports_to 链上
        cur, hops = role_id, 0
        while cur and hops < 4:
            st = org.get_station(cur)
            cur = (st or {}).get("reports_to") or ""
            if cur and cur == auth_by:
                return
            hops += 1
        self._deny("BUS_MISSING_AUTHORIZATION", sender, recv, "task",
                   f"authorized_by={auth_by!r} 不在发送方授权链上（消息≠授权）")

    def _guard_approval(self, envelope: Dict[str, Any], role_id: str,
                        recv_role: str):
        payload = envelope.get("payload") or {}
        scope = str(payload.get("scope") or "manager")
        dept = str(payload.get("dept") or "")
        approver = role_id or ""
        ok, why = org.can_approve(approver, scope, dept)
        if not ok:
            self._deny("ACL_APPROVE_DENIED", approver,
                       str(envelope.get("to") or ""), "approval", why)
        allowed, code = self._acl("approve", str(envelope.get("from") or ""))
        if not allowed:
            self._deny(code, str(envelope.get("from") or ""),
                       str(envelope.get("to") or ""), "approval",
                       "审批位未授权（can_approve=0）")

    def _deny(self, code: str, sender: str, recv: str, mtype: str,
              reason: str):
        record = {"code": code, "from": sender, "to": recv, "type": mtype,
                  "reason": reason, "ts": time.time()}
        if self._audit_cb is not None:
            try:
                self._audit_cb(record)
            except Exception:
                logger.debug("suppressed exception")
        raise BusError(code, reason, 403)

    # ── 辅助 ──
    def _session_role(self, session_id: str) -> str:
        """从公司会话台账反查该会话所属工位（dm 会话名约定 co_agent_{role}_{run}）。"""
        sess = self._store.get_session(session_id)
        if sess is None:
            return ""
        members = sess.get("members") or []
        for m in members:
            if org.get_station(m) is not None:
                return m
        return ""

    def _is_upchain(self, sender_role: str, recv_role: str) -> bool:
        """recv 是否在 sender 的 reports_to 链上（真实沿链走，最多 3 层）。"""
        cur, hops = sender_role, 0
        while cur and hops < 4:
            cur = org.dept_of(cur) and org.get_station(cur)["reports_to"]
            if cur == recv_role:
                return True
            hops += 1
        return False

    def _find_group(self, run_id: Optional[int]) -> Optional[Dict[str, Any]]:
        for s in self._store.get_sessions(run_id=run_id, kind="group"):
            return s
        for s in self._store.get_sessions(kind="group"):   # 全局兜底（最新群）
            return s
        return None

    @staticmethod
    def _envelope_json(envelope: Dict[str, Any]) -> Dict[str, Any]:
        """信封统一字段（from/to/role/task_id/authorization/requires_approval）。"""
        return {
            "type": envelope.get("type"),
            "from": envelope.get("from"),
            "to": envelope.get("to"),
            "role": envelope.get("role"),
            "task_id": envelope.get("task_id") or "",
            "authorization": envelope.get("authorization") or "",
            "authorized_by": envelope.get("authorized_by") or "",  # ★ 收口项 18
            "requires_approval": bool(envelope.get("requires_approval")),
            "payload": envelope.get("payload") if isinstance(envelope.get("payload"), (dict, list)) else str(envelope.get("payload"))[:4000],
        }
