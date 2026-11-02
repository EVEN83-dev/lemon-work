# -*- coding: utf-8 -*-
"""
工作区管理器 — 多项目管理与切换
=================================
功能：
- 管理多个项目工作区（添加/移除/切换/列表）
- 持久化到 ~/.mimo_agent/workspaces.json
- 每个工作区保存：路径、名称、最后打开时间、关联的会话ID
- 切换工作区时保存当前会话状态，加载目标工作区

配置结构：
{
    "current": "ws_xxxx",           # 当前工作区 ID
    "workspaces": [
        {
            "id": "ws_xxxx",
            "path": "D:\\projects\\my_app",
            "name": "我的应用",
            "last_opened": "2026-07-12T10:00:00",
            "session_id": "abc123",
            "mimo_session_id": "ses_xxx"   # 关联的 MIMO Code 会话
        }
    ]
}
"""

import os
import json
import uuid
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


# ============================================================
# 默认配置
# ============================================================

def _default_workspace_entry(path: str, name: str = "") -> Dict[str, Any]:
    """创建默认的工作区条目"""
    if not name:
        name = os.path.basename(os.path.abspath(path)) or "未命名项目"
    return {
        "id": f"ws_{uuid.uuid4().hex[:8]}",
        "path": os.path.abspath(path),
        "name": name,
        "last_opened": datetime.now().isoformat(timespec="seconds"),
        "session_id": "",
        "mimo_session_id": "",
    }


class WorkspaceManager:
    """工作区管理器 — 多项目管理与切换"""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_dir = os.path.join(os.path.expanduser("~"), ".mimo_agent")
            os.makedirs(config_dir, exist_ok=True)
            config_path = os.path.join(config_dir, "workspaces.json")
        self._config_path = config_path
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {"current": "", "workspaces": []}
        self._listeners: List[callable] = []
        self.load()

    # ============================================================
    # 持久化
    # ============================================================
    def load(self) -> None:
        """从磁盘加载工作区配置"""
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._data["current"] = data.get("current", "")
                ws_list = data.get("workspaces", [])
                if isinstance(ws_list, list):
                    # 过滤无效条目（路径不存在的不删除，但标记）
                    self._data["workspaces"] = [
                        w for w in ws_list
                        if isinstance(w, dict) and w.get("path")
                    ]
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {"current": "", "workspaces": []}

    def save(self) -> bool:
        """保存工作区配置到磁盘"""
        try:
            with self._lock:
                tmp = os.path.join(os.path.dirname(self._config_path), ".workspaces.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self._config_path)
            return True
        except Exception as e:
            print(f"[WorkspaceManager] 保存失败: {e}")
            return False

    # ============================================================
    # 工作区 CRUD
    # ============================================================
    def list_workspaces(self) -> List[Dict[str, Any]]:
        """返回所有工作区列表（按最后打开时间倒序）"""
        with self._lock:
            ws = list(self._data["workspaces"])
        ws.sort(key=lambda w: w.get("last_opened", ""), reverse=True)
        return ws

    def add_workspace(self, path: str, name: str = "") -> Dict[str, Any]:
        """添加工作区。如果路径已存在则更新名称，返回工作区条目"""
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            raise FileNotFoundError(f"路径不存在或不是目录: {path}")

        with self._lock:
            # 检查是否已存在（按路径去重）
            for w in self._data["workspaces"]:
                if os.path.normpath(w.get("path", "")) == os.path.normpath(path):
                    if name:
                        w["name"] = name
                    w["last_opened"] = datetime.now().isoformat(timespec="seconds")
                    self.save()
                    self._notify("added", w)
                    return w
            # 新建
            entry = _default_workspace_entry(path, name)
            self._data["workspaces"].append(entry)
            self.save()
        self._notify("added", entry)
        return entry

    def remove_workspace(self, ws_id: str) -> bool:
        """移除工作区（按 ID）。如果是当前工作区，清除 current 引用"""
        with self._lock:
            before = len(self._data["workspaces"])
            self._data["workspaces"] = [
                w for w in self._data["workspaces"] if w.get("id") != ws_id
            ]
            removed = len(self._data["workspaces"]) < before
            if removed and self._data["current"] == ws_id:
                self._data["current"] = ""
            if removed:
                self.save()
        if removed:
            self._notify("removed", {"id": ws_id})
        return removed

    def get_workspace(self, ws_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 获取工作区"""
        with self._lock:
            for w in self._data["workspaces"]:
                if w.get("id") == ws_id:
                    return dict(w)
        return None

    def get_current_workspace(self) -> Optional[Dict[str, Any]]:
        """获取当前工作区"""
        current_id = self._data.get("current", "")
        if not current_id:
            return None
        return self.get_workspace(current_id)

    def get_current_path(self) -> str:
        """获取当前工作区路径，无则返回空字符串"""
        ws = self.get_current_workspace()
        return ws.get("path", "") if ws else ""

    # ============================================================
    # 切换工作区
    # ============================================================
    def switch_workspace(self, ws_id: str) -> Dict[str, Any]:
        """切换当前工作区。
        返回 {"workspace": {...}, "prev_session_id": "...", "new_session_id": "..."}
        调用方负责：保存当前会话状态、加载目标会话历史、更新文件浏览器、更新 Git。
        """
        target = self.get_workspace(ws_id)
        if not target:
            raise ValueError(f"工作区不存在: {ws_id}")

        prev = self.get_current_workspace()
        prev_session_id = prev.get("session_id", "") if prev else ""

        with self._lock:
            self._data["current"] = ws_id
            # 更新最后打开时间
            for w in self._data["workspaces"]:
                if w.get("id") == ws_id:
                    w["last_opened"] = datetime.now().isoformat(timespec="seconds")
                    break
            self.save()

        result = {
            "workspace": dict(target),
            "prev_session_id": prev_session_id,
            "new_session_id": target.get("session_id", ""),
        }
        self._notify("switched", result)
        return result

    def set_current_session_id(self, session_id: str) -> None:
        """更新当前工作区关联的会话 ID（用于切换前保存）"""
        current_id = self._data.get("current", "")
        if not current_id:
            return
        with self._lock:
            for w in self._data["workspaces"]:
                if w.get("id") == current_id:
                    w["session_id"] = session_id
                    break
            self.save()

    def set_current_mimo_session(self, mimo_session_id: str) -> None:
        """更新当前工作区关联的 MIMO Code 会话 ID"""
        current_id = self._data.get("current", "")
        if not current_id:
            return
        with self._lock:
            for w in self._data["workspaces"]:
                if w.get("id") == current_id:
                    w["mimo_session_id"] = mimo_session_id
                    break
            self.save()

    # ============================================================
    # 自动添加当前目录
    # ============================================================
    def ensure_current(self, path: str, name: str = "") -> Dict[str, Any]:
        """确保指定路径在列表中并设为当前工作区（启动时调用）"""
        path = os.path.abspath(path)
        # 查找或添加
        existing = None
        with self._lock:
            for w in self._data["workspaces"]:
                if os.path.normpath(w.get("path", "")) == os.path.normpath(path):
                    existing = w
                    break
        if existing:
            if name:
                existing["name"] = name
            self.switch_workspace(existing["id"])
            return existing
        else:
            entry = self.add_workspace(path, name)
            self.switch_workspace(entry["id"])
            return entry

    # ============================================================
    # 观察者
    # ============================================================
    def add_listener(self, callback: callable) -> None:
        """添加工作区变更监听器 callback(event_type, data)"""
        self._listeners.append(callback)

    def remove_listener(self, callback: callable) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _notify(self, event: str, data: Any):
        for cb in self._listeners:
            try:
                cb(event, data)
            except Exception as e:
                print(f"[WorkspaceManager] 监听器异常: {e}")
        # ★ 同步发布到 EventBus（延迟导入避免循环依赖）
        try:
            from event_bus import EventBus, EventType
            if event == "switched":
                EventBus.instance().publish(EventType.WORKSPACE_CHANGED, data)
        except Exception:
            pass

    # ============================================================
    # 便捷
    # ============================================================
    def to_dict(self) -> Dict[str, Any]:
        """返回完整数据（用于序列化）"""
        with self._lock:
            return json.loads(json.dumps(self._data))


# ============================================================
# 模块级单例
# ============================================================
_workspace_manager: Optional[WorkspaceManager] = None


def get_workspace_manager() -> WorkspaceManager:
    global _workspace_manager
    if _workspace_manager is None:
        _workspace_manager = WorkspaceManager()
    return _workspace_manager
