# -*- coding: utf-8 -*-
"""★第404章 ActionCard 动态操作卡 —— 平台级动作注册表与分派器

四层架构（详见开发日志第404章）：
  ①生成入口 ui_action_card 技能（skills 层）
  ②卡片协议 action_card JSON（消息层，本文件定义结构）
  ③界面渲染 onActionCard（mimo_app.js 前端）
  ④点击执行 ActionCardRegistry.dispatch（本文件，桥接路由层）

设计纪律：
- 按钮定义是数据不是代码：Agent 按上下文实时生成卡片
- 白名单安全：按钮 action 必须预先注册，未注册一律拒绝（防提示注入伪造）
- confirm 门：注册时标记 confirm=True 的动作，首次点击返回 confirm_required，
  前端二次确认后携带 confirmed=True 重发才真正执行
- 历史有效：按钮绑定无状态 action_id（进程内注册表常驻），
  卡片 DOM 随消息流持久化 + 前端事件委托 → 滑回历史会话按钮依然可用
- 线程安全：技能在工作线程调 emit_card → ui_callback(_safe_run_js) 走
  面板 _js_call_queue 队列，天然线程安全
"""
from __future__ import annotations

import json
import threading
import time
from typing import Callable, Dict, List, Optional


class ActionCardRegistry:
    """ActionCard 动作注册表（进程级单例，经 get_action_card_registry 获取）"""

    def __init__(self):
        self._lock = threading.RLock()
        self._actions: Dict[str, Dict] = {}   # action_id -> {handler, confirm, description, ts}
        self._ui_callback: Optional[Callable[[str], None]] = None  # 注入 panel._safe_run_js
        self._cards_emitted = 0               # 计数（验证用）

    # ---------- 动作注册（白名单真源） ----------
    def register_action(self, action_id: str, handler: Callable,
                        confirm: bool = False, description: str = "") -> dict:
        if not action_id or not isinstance(action_id, str):
            return {"success": False, "error": "action_id 必须为非空字符串"}
        if not callable(handler):
            return {"success": False, "error": "handler 必须可调用"}
        with self._lock:
            self._actions[action_id] = {
                "handler": handler, "confirm": bool(confirm),
                "description": description or action_id,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        return {"success": True, "action_id": action_id}

    def has(self, action_id: str) -> bool:
        with self._lock:
            return action_id in self._actions

    def get_action_info(self, action_id: str) -> Optional[Dict]:
        """★第416章: 查询动作元信息（confirm 位）——表单卡提交按钮需据此决定两段式确认"""
        with self._lock:
            info = self._actions.get(action_id)
        if info is None:
            return None
        return {"confirm": bool(info.get("confirm")),
                "description": info.get("description", "")}

    def list_actions(self) -> List[Dict]:
        with self._lock:
            return [{"action_id": k, "confirm": v["confirm"],
                     "description": v["description"]} for k, v in self._actions.items()]

    # ---------- UI 渲染回调（由面板注入） ----------
    def set_ui_callback(self, cb: Callable[[str], None]) -> dict:
        if not callable(cb):
            return {"success": False, "error": "ui_callback 必须可调用"}
        self._ui_callback = cb
        return {"success": True}

    def emit_card(self, card: Dict) -> dict:
        """把卡片 JSON 推送到前端渲染（线程安全，失败显式）"""
        if self._ui_callback is None:
            return {"success": False, "error": "UI 回调未注入（面板未就绪）"}
        try:
            js = "if(window.onActionCard)window.onActionCard(%s);" % (
                json.dumps(card, ensure_ascii=False),)
            self._ui_callback(js)
            with self._lock:
                self._cards_emitted += 1
            return {"success": True, "card_id": card.get("card_id", "")}
        except Exception as e:
            return {"success": False, "error": f"卡片推送失败: {e}"}

    # ---------- 点击分派（前端按钮 → 这里） ----------
    def dispatch(self, action_id: str, params: Optional[Dict] = None,
                 confirmed: bool = False) -> dict:
        with self._lock:
            info = self._actions.get(action_id)
        if info is None:
            return {"success": False, "error": f"动作未注册或已失效: {action_id}"}
        if info["confirm"] and not confirmed:
            return {"success": False, "confirm_required": True,
                    "message": f"该操作需要二次确认: {info['description']}"}
        try:
            result = info["handler"](dict(params or {}))
            if not isinstance(result, dict):
                result = {"success": True, "result": str(result)}
            result.setdefault("action_id", action_id)
            return result
        except Exception as e:
            return {"success": False, "action_id": action_id,
                    "error": f"动作执行异常: {e}"}

    # ---------- 卡片结构构建 ----------
    @staticmethod
    def build_card(title: str, buttons: List[Dict], note: str = "") -> Dict:
        return {
            "type": "action_card",
            "card_id": f"ac_{int(time.time() * 1000)}",
            "title": title or "操作面板",
            "buttons": buttons,
            "note": note or "",
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }


# ---- 进程级单例 ----
_global_registry: Optional[ActionCardRegistry] = None
_global_lock = threading.Lock()


def get_action_card_registry() -> ActionCardRegistry:
    global _global_registry
    if _global_registry is None:
        with _global_lock:
            if _global_registry is None:
                _global_registry = ActionCardRegistry()
    return _global_registry

