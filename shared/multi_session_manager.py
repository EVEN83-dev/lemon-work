# -*- coding: utf-8 -*-
"""
多会话并行管理器 — 多 MIMO Code 窗口协同核心
==============================================
核心思路：
- 管理多个 MIMO Serve Bridge 会话，每个会话独立运行
- 支持会话创建/切换/关闭/并行执行
- 任务路由：根据任务类型和会话负载智能分发
- 每个会话维护独立的输出缓冲区和状态

架构：
┌─────────────────────────────────────────┐
│         MultiSessionManager              │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │ Session1│ │ Session2│ │ Session3│   │
│  │ (build) │ │ (plan)  │ │ (idle)  │   │
│  └────┬────┘ └────┬────┘ └────┬────┘   │
│       │           │           │         │
│  ┌────┴───────────┴───────────┴────┐   │
│  │       Serve Bridge (HTTP/SSE)    │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
"""

import threading
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

from PyQt5.QtCore import QObject, pyqtSignal


class SessionState(Enum):
    IDLE = "idle"
    BUSY = "busy"
    THINKING = "thinking"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class SessionRole(Enum):
    BUILD = "build"       # 代码构建/生成
    PLAN = "plan"         # 任务规划/分析
    COMPOSE = "compose"   # 组合/编辑
    GENERAL = "general"   # 通用任务


@dataclass
class SessionInfo:
    """会话元信息"""
    session_id: str
    name: str
    role: SessionRole = SessionRole.GENERAL
    state: SessionState = SessionState.IDLE
    created_at: float = field(default_factory=time.time)
    output_buffer: List[str] = field(default_factory=list)
    task_count: int = 0
    total_tokens: int = 0
    model: str = "mimo-auto"


class MultiSessionManager(QObject):
    """
    多会话并行管理器
    
    功能：
    - 创建/销毁/切换多个 MIMO Code 会话
    - 会话状态跟踪（空闲/忙碌/思考/错误）
    - 智能任务路由（基于角色 + 负载均衡）
    - 会话输出缓冲区和事件通知
    """
    
    # ==================== 信号 ====================
    session_added = pyqtSignal(str, str)        # (session_id, name)
    session_removed = pyqtSignal(str)            # (session_id)
    session_state_changed = pyqtSignal(str, str) # (session_id, state)
    session_output = pyqtSignal(str, str)        # (session_id, text)
    active_session_changed = pyqtSignal(str)     # (session_id)
    task_routed = pyqtSignal(str, str, str)      # (task, from_session, to_session)
    all_sessions_idle = pyqtSignal()             # 所有会话空闲
    
    def __init__(self, serve_bridge=None, parent=None):
        super().__init__(parent)
        self._serve_bridge = serve_bridge
        self._sessions: Dict[str, SessionInfo] = {}
        self._active_session_id: Optional[str] = None
        self._session_order: List[str] = []  # 保持创建顺序
        self._lock = threading.Lock()
        self._task_queue: List[tuple] = []   # (task, callback)
        self._auto_route = True
    
    # ================================================================
    # 会话管理 API
    # ================================================================
    
    @property
    def active_session_id(self) -> Optional[str]:
        return self._active_session_id
    
    @property
    def session_count(self) -> int:
        return len(self._sessions)
    
    @property
    def sessions(self) -> Dict[str, SessionInfo]:
        return dict(self._sessions)
    
    def create_session(self, name: str = "", role: SessionRole = SessionRole.GENERAL) -> Optional[str]:
        """创建新会话 — 通过 Serve Bridge 创建并注册"""
        if not self._serve_bridge or not self._serve_bridge.is_connected:
            return None
        
        try:
            # 通过 Serve Bridge 创建会话
            self._serve_bridge.create_session()
            # 等待 session_created 信号回调设置 session_id
            # 这里使用临时方案：直接调用 serve bridge 的内部方法
            sid = self._serve_bridge.session_id
            if not sid:
                return None
            
            with self._lock:
                info = SessionInfo(
                    session_id=sid,
                    name=name or f"任务 {len(self._sessions) + 1}",
                    role=role,
                )
                self._sessions[sid] = info
                self._session_order.append(sid)
                
                if self._active_session_id is None:
                    self._active_session_id = sid
            
            self.session_added.emit(sid, info.name)
            return sid
            
        except Exception as e:
            return None
    
    def register_session(self, session_id: str, name: str = "", role: SessionRole = SessionRole.GENERAL):
        """注册已有会话（由 serve_bridge 回调触发）"""
        with self._lock:
            if session_id in self._sessions:
                return
            
            info = SessionInfo(
                session_id=session_id,
                name=name or f"任务 {len(self._sessions) + 1}",
                role=role,
            )
            self._sessions[session_id] = info
            self._session_order.append(session_id)
            
            if self._active_session_id is None:
                self._active_session_id = session_id
        
        self.session_added.emit(session_id, info.name)
    
    def switch_session(self, session_id: str) -> bool:
        """切换到指定会话"""
        if session_id not in self._sessions:
            return False
        
        with self._lock:
            self._active_session_id = session_id
        
        # 通知 Serve Bridge 切换
        if self._serve_bridge and self._serve_bridge.is_connected:
            self._serve_bridge.switch_session(session_id)
        
        self.active_session_changed.emit(session_id)
        return True
    
    def close_session(self, session_id: str) -> bool:
        """关闭会话"""
        if session_id not in self._sessions:
            return False
        
        with self._lock:
            info = self._sessions.pop(session_id)
            if session_id in self._session_order:
                self._session_order.remove(session_id)
            
            # 如果关闭的是活动会话，切换到下一个
            if self._active_session_id == session_id:
                if self._session_order:
                    self._active_session_id = self._session_order[0]
                    self.active_session_changed.emit(self._active_session_id)
                else:
                    self._active_session_id = None
        
        self.session_removed.emit(session_id)
        return True
    
    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        return self._sessions.get(session_id)
    
    def get_active_session(self) -> Optional[SessionInfo]:
        if self._active_session_id:
            return self._sessions.get(self._active_session_id)
        return None
    
    # ================================================================
    # 状态管理
    # ================================================================
    
    def set_session_state(self, session_id: str, state: SessionState):
        """更新会话状态"""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].state = state
        
        self.session_state_changed.emit(session_id, state.value)
        
        # 检查是否所有会话空闲
        if all(s.state == SessionState.IDLE for s in self._sessions.values()):
            self.all_sessions_idle.emit()
    
    def set_session_role(self, session_id: str, role: SessionRole):
        """设置会话角色"""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].role = role
    
    def append_output(self, session_id: str, text: str):
        """追加会话输出"""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].output_buffer.append(text)
                # 限制缓冲区大小
                if len(self._sessions[session_id].output_buffer) > 1000:
                    self._sessions[session_id].output_buffer = \
                        self._sessions[session_id].output_buffer[-500:]
        
        self.session_output.emit(session_id, text)
    
    def increment_task_count(self, session_id: str):
        """增加任务计数"""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].task_count += 1
    
    # ================================================================
    # 智能任务路由
    # ================================================================
    
    def route_task(self, task: str, preferred_role: SessionRole = None) -> Optional[str]:
        """
        智能路由任务到最合适的会话
        
        策略：
        1. 如果有指定角色的空闲会话，优先使用
        2. 如果有任何空闲会话，使用之
        3. 如果有指定角色的会话（即使忙碌），排队等待
        4. 创建新会话
        """
        with self._lock:
            # 1. 查找匹配角色的空闲会话
            for sid in self._session_order:
                info = self._sessions.get(sid)
                if info and info.state == SessionState.IDLE:
                    if preferred_role and info.role == preferred_role:
                        return sid
            
            # 2. 查找任何空闲会话
            for sid in self._session_order:
                info = self._sessions.get(sid)
                if info and info.state == SessionState.IDLE:
                    return sid
            
            # 3. 所有会话都忙碌，返回活动会话（排队）
            if self._active_session_id:
                return self._active_session_id
            
            # 4. 没有会话，返回 None
            return None
    
    def get_idle_sessions(self) -> List[str]:
        """获取所有空闲会话"""
        with self._lock:
            return [
                sid for sid in self._session_order
                if self._sessions.get(sid) and self._sessions[sid].state == SessionState.IDLE
            ]
    
    def get_busy_sessions(self) -> List[str]:
        """获取所有忙碌会话"""
        with self._lock:
            return [
                sid for sid in self._session_order
                if self._sessions.get(sid) and self._sessions[sid].state == SessionState.BUSY
            ]
    
    # ================================================================
    # 会话摘要
    # ================================================================
    
    def get_summary(self) -> Dict:
        """获取所有会话的摘要信息"""
        with self._lock:
            sessions_info = {}
            for sid, info in self._sessions.items():
                sessions_info[sid] = {
                    "name": info.name,
                    "role": info.role.value,
                    "state": info.state.value,
                    "task_count": info.task_count,
                    "total_tokens": info.total_tokens,
                    "model": info.model,
                    "is_active": sid == self._active_session_id,
                }
            return {
                "total": len(self._sessions),
                "idle": len(self.get_idle_sessions()),
                "busy": len(self.get_busy_sessions()),
                "active_id": self._active_session_id,
                "sessions": sessions_info,
            }