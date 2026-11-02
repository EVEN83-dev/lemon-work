# -*- coding: utf-8 -*-
"""
Lemon Agent 工作群机制
=======================
实现AI之间的沟通协调系统：
- 类似微信群的沟通机制
- 支持点对点和广播消息
- 消息历史记录
- 汇报系统

核心功能：
1. WorkGroup - 工作群管理器
2. Message - 消息结构
3. ReportSystem - 汇报系统
4. StatusBlackboard - 状态黑板
5. FileLock - 文件锁机制
"""

import os
import json
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field, asdict
from enum import Enum


# ============================================================================
# 消息类型
# ============================================================================

class MessageType(Enum):
    """消息类型"""
    TEXT = "text"           # 普通文本
    COMMAND = "command"     # 命令（分配任务）
    RESULT = "result"       # 结果（汇报）
    ERROR = "error"         # 错误
    STATUS = "status"       # 状态更新
    HEARTBEAT = "heartbeat" # 心跳


# ============================================================================
# 消息结构
# ============================================================================

@dataclass
class Message:
    """工作群消息"""
    id: str
    from_ai: str           # 发送者ID
    to_ai: str             # 接收者ID ("all"表示广播)
    content: str           # 消息内容
    msg_type: str = "text" # 消息类型
    timestamp: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)  # 附加元数据

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "from": self.from_ai,
            "to": self.to_ai,
            "content": self.content,
            "type": self.msg_type,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat(),
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Message':
        return cls(
            id=data["id"],
            from_ai=data["from"],
            to_ai=data["to"],
            content=data["content"],
            msg_type=data.get("type", "text"),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {})
        )


# ============================================================================
# 工作群管理器
# ============================================================================

class WorkGroup:
    """工作群管理器 — AI沟通协调中心"""

    def __init__(self, name: str = "Lemon Agent WorkGroup"):
        self.name = name
        self.members: Dict[str, Dict] = {}  # ai_id -> {role, status, ...}
        self.messages: List[Message] = []    # 消息历史
        self._lock = threading.Lock()
        self._message_handlers: List[Callable] = []
        self._max_history = 1000  # 最大历史消息数

    # ==================== 成员管理 ====================

    def add_member(self, ai_id: str, role: str, metadata: Dict = None):
        """添加成员"""
        with self._lock:
            self.members[ai_id] = {
                "role": role,
                "status": "idle",
                "join_time": time.time(),
                "last_active": time.time(),
                "message_count": 0,
                "metadata": metadata or {}
            }
            # 广播加入消息
            self.broadcast("system", f"{ai_id} ({role}) 加入了工作群")

    def remove_member(self, ai_id: str):
        """移除成员"""
        with self._lock:
            if ai_id in self.members:
                role = self.members[ai_id]["role"]
                del self.members[ai_id]
                self.broadcast("system", f"{ai_id} ({role}) 离开了工作群")

    def update_status(self, ai_id: str, status: str):
        """更新成员状态"""
        with self._lock:
            if ai_id in self.members:
                self.members[ai_id]["status"] = status
                self.members[ai_id]["last_active"] = time.time()

    def get_member(self, ai_id: str) -> Optional[Dict]:
        """获取成员信息"""
        return self.members.get(ai_id)

    def get_all_members(self) -> Dict[str, Dict]:
        """获取所有成员"""
        return self.members.copy()

    def get_members_by_role(self, role: str) -> List[str]:
        """按角色获取成员"""
        return [ai_id for ai_id, info in self.members.items() if info["role"] == role]

    # ==================== 消息发送 ====================

    def send_message(self, from_ai: str, to_ai: str, content: str,
                     msg_type: str = "text", metadata: Dict = None) -> Message:
        """发送消息"""
        import uuid
        message = Message(
            id=str(uuid.uuid4())[:8],
            from_ai=from_ai,
            to_ai=to_ai,
            content=content,
            msg_type=msg_type,
            metadata=metadata or {}
        )

        with self._lock:
            self.messages.append(message)
            # 更新发送者活跃度
            if from_ai in self.members:
                self.members[from_ai]["message_count"] += 1
                self.members[from_ai]["last_active"] = time.time()
            # 限制历史大小
            if len(self.messages) > self._max_history:
                self.messages = self.messages[-self._max_history:]

        # 触发消息处理器
        self._trigger_handlers(message)

        return message

    def broadcast(self, from_ai: str, content: str, msg_type: str = "text") -> Message:
        """广播消息（发给所有人）"""
        return self.send_message(from_ai, "all", content, msg_type)

    def command(self, from_ai: str, to_ai: str, command: str, params: Dict = None) -> Message:
        """发送命令"""
        return self.send_message(from_ai, to_ai, command, "command",
                                  {"params": params or {}})

    def report(self, from_ai: str, to_ai: str, content: str, result_type: str = "result") -> Message:
        """发送汇报"""
        return self.send_message(from_ai, to_ai, content, result_type)

    # ==================== 消息获取 ====================

    def get_messages_for(self, ai_id: str, limit: int = 50) -> List[Message]:
        """获取指定AI的消息"""
        with self._lock:
            messages = [
                m for m in self.messages[-limit * 2:]
                if m.to_ai == ai_id or m.to_ai == "all" or m.from_ai == ai_id
            ]
            return messages[-limit:]

    def get_recent_messages(self, limit: int = 50) -> List[Message]:
        """获取最近的消息"""
        with self._lock:
            return self.messages[-limit:]

    def get_unread_count(self, ai_id: str, last_read_time: float = 0) -> int:
        """获取未读消息数"""
        with self._lock:
            return len([
                m for m in self.messages
                if (m.to_ai == ai_id or m.to_ai == "all")
                and m.from_ai != ai_id
                and m.timestamp > last_read_time
            ])

    # ==================== 消息处理器 ====================

    def add_handler(self, handler: Callable[[Message], None]):
        """添加消息处理器"""
        self._message_handlers.append(handler)

    def remove_handler(self, handler: Callable):
        """移除消息处理器"""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)

    def _trigger_handlers(self, message: Message):
        """触发所有处理器"""
        for handler in self._message_handlers:
            try:
                handler(message)
            except Exception as e:
                print(f"[WorkGroup] Handler error: {e}")

    # ==================== 持久化 ====================

    def save_history(self, filepath: str):
        """保存消息历史"""
        with self._lock:
            data = {
                "name": self.name,
                "members": self.members,
                "messages": [m.to_dict() for m in self.messages],
                "saved_at": datetime.now().isoformat()
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def load_history(self, filepath: str):
        """加载消息历史"""
        if not os.path.exists(filepath):
            return
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.name = data.get("name", self.name)
        self.members = data.get("members", {})
        self.messages = [Message.from_dict(m) for m in data.get("messages", [])]

    # ==================== Agent 间点对点通信 ====================

    def send_agent_message(self, from_ai: str, to_ai: str, content: str,
                           data: Any = None) -> Optional[Message]:
        """Agent 间直连通信（点对点，不广播）

        区别于 command/broadcast，此方法：
        1. 仅目标 Agent 收到消息
        2. 不会触发工作群全局广播
        3. 适用于 Agent 间私下协商/协助

        Args:
            from_ai: 发送方 Agent ID
            to_ai: 接收方 Agent ID
            content: 消息内容
            data: 附加数据

        Returns:
            Message 或 None
        """
        with self._lock:
            if from_ai not in self.members:
                print(f"[WorkGroup] send_agent_message: 发送方 {from_ai} 不存在",
                      flush=True)
                return None
            if to_ai not in self.members:
                print(f"[WorkGroup] send_agent_message: 接收方 {to_ai} 不存在",
                      flush=True)
                return None

            msg = Message(
                id=self._next_msg_id(),
                from_ai=from_ai,
                to_ai=to_ai,
                type="agent_message",
                content=content,
                data=data,
                timestamp=time.time(),
            )
            self.messages.append(msg)
            self.members[from_ai]["message_count"] += 1

        # 通知目标 Agent 的处理器
        self._notify_handler(msg)
        return msg

    def relay_message(self, from_ai: str, to_ai: str, content: str,
                      data: Any = None) -> Optional[Message]:
        """中继转发消息 — superbrain 作为中继站转达两个 Agent

        用于两个在消息队列中互相收不到的 Agent 通过 superbrain 中转通信。
        与 send_agent_message 的区别：
        - 消息的 from_ai 保留原始发送者
        - 会额外注册中继记录

        Args:
            from_ai: 原始发送方 Agent ID
            to_ai: 目标接收方 Agent ID
            content: 消息内容
            data: 附加数据

        Returns:
            Message 或 None
        """
        return self.send_agent_message(from_ai, to_ai, content, data)

    # ==================== 统计 ====================

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            return {
                "name": self.name,
                "member_count": len(self.members),
                "message_count": len(self.messages),
                "members": {
                    ai_id: {
                        "role": info["role"],
                        "status": info["status"],
                        "message_count": info["message_count"]
                    }
                    for ai_id, info in self.members.items()
                }
            }


# ============================================================================
# 汇报系统
# ============================================================================

class ReportSystem:
    """汇报系统 — 执行AI向超级大脑汇报"""

    def __init__(self, workgroup: WorkGroup):
        self.workgroup = workgroup
        self.reports: Dict[str, List[Dict]] = {}  # ai_id -> reports
        self._lock = threading.Lock()

    def submit_progress(self, ai_id: str, task_id: str, progress: float,
                        message: str = ""):
        """提交进度汇报"""
        report = {
            "type": "progress",
            "ai_id": ai_id,
            "task_id": task_id,
            "progress": progress,
            "message": message,
            "timestamp": time.time()
        }
        self._add_report(ai_id, report)
        # 发送到工作群
        self.workgroup.report(
            ai_id, "superbrain",
            f"进度汇报: 任务{task_id} {progress*100:.0f}%",
            "result"
        )

    def submit_result(self, ai_id: str, task_id: str, result: Any):
        """提交结果汇报"""
        report = {
            "type": "result",
            "ai_id": ai_id,
            "task_id": task_id,
            "result": result,
            "timestamp": time.time()
        }
        self._add_report(ai_id, report)
        # 发送到工作群
        self.workgroup.report(
            ai_id, "superbrain",
            f"任务{task_id}完成: {result}",
            "result"
        )

    def submit_error(self, ai_id: str, task_id: str, error: str):
        """提交错误汇报"""
        report = {
            "type": "error",
            "ai_id": ai_id,
            "task_id": task_id,
            "error": error,
            "timestamp": time.time()
        }
        self._add_report(ai_id, report)
        # 发送到工作群
        self.workgroup.report(
            ai_id, "superbrain",
            f"任务{task_id}错误: {error}",
            "error"
        )

    def _add_report(self, ai_id: str, report: Dict):
        """添加汇报"""
        with self._lock:
            if ai_id not in self.reports:
                self.reports[ai_id] = []
            self.reports[ai_id].append(report)

    def get_reports(self, ai_id: str = None) -> Dict:
        """获取汇报"""
        with self._lock:
            if ai_id:
                return self.reports.get(ai_id, [])
            return self.reports.copy()


# ============================================================================
# 状态黑板
# ============================================================================

class StatusBlackboard:
    """状态黑板 — 所有AI共享状态"""

    def __init__(self):
        self.states: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._listeners: List[Callable] = []

    def update(self, ai_id: str, state: Dict):
        """更新状态"""
        with self._lock:
            self.states[ai_id] = {
                **state,
                "ai_id": ai_id,
                "last_update": time.time()
            }
        # 通知监听器
        for listener in self._listeners:
            try:
                listener(ai_id, self.states[ai_id])
            except Exception as e:
                print(f"[StatusBlackboard] Listener error: {e}")

    def get(self, ai_id: str) -> Optional[Dict]:
        """获取状态"""
        return self.states.get(ai_id)

    def get_all(self) -> Dict[str, Dict]:
        """获取所有状态"""
        with self._lock:
            return self.states.copy()

    def get_others(self, my_ai_id: str) -> Dict[str, Dict]:
        """获取其他AI的状态"""
        with self._lock:
            return {
                k: v for k, v in self.states.items()
                if k != my_ai_id
            }

    def add_listener(self, listener: Callable):
        """添加状态变化监听器"""
        self._listeners.append(listener)


# ============================================================================
# 文件锁机制
# ============================================================================

class FileLock:
    """文件锁 — 防止并发修改冲突"""

    def __init__(self):
        self.locks: Dict[str, str] = {}  # filepath -> ai_id
        self.queue: Dict[str, List[str]] = {}  # filepath -> [waiting_ai_ids]
        self._lock = threading.Lock()

    def acquire(self, filepath: str, ai_id: str, timeout: float = 30.0) -> bool:
        """请求文件锁"""
        import time
        start = time.time()

        while time.time() - start < timeout:
            with self._lock:
                if filepath not in self.locks:
                    self.locks[filepath] = ai_id
                    return True
                elif self.locks[filepath] == ai_id:
                    return True  # 已经持有锁
                else:
                    # 加入等待队列
                    if filepath not in self.queue:
                        self.queue[filepath] = []
                    if ai_id not in self.queue[filepath]:
                        self.queue[filepath].append(ai_id)
            time.sleep(0.1)

        return False  # 超时

    def release(self, filepath: str, ai_id: str):
        """释放文件锁"""
        with self._lock:
            if self.locks.get(filepath) == ai_id:
                del self.locks[filepath]
                # 通知下一个等待者
                if filepath in self.queue and self.queue[filepath]:
                    next_ai = self.queue[filepath].pop(0)
                    self.locks[filepath] = next_ai
                    # 触发通知（实际应用中应通过回调）
                    print(f"[FileLock] {filepath} 锁已转移给 {next_ai}")

    def is_locked(self, filepath: str) -> bool:
        """检查文件是否被锁"""
        return filepath in self.locks

    def get_lock_owner(self, filepath: str) -> Optional[str]:
        """获取文件锁持有者"""
        return self.locks.get(filepath)


# ============================================================================
# 全局实例
# ============================================================================

_global_workgroup: Optional[WorkGroup] = None
_global_report_system: Optional[ReportSystem] = None
_global_blackboard: Optional[StatusBlackboard] = None
_global_filelock: Optional[FileLock] = None


def get_workgroup() -> WorkGroup:
    """获取全局工作群实例"""
    global _global_workgroup
    if _global_workgroup is None:
        _global_workgroup = WorkGroup()
    return _global_workgroup


def get_report_system() -> ReportSystem:
    """获取全局汇报系统实例"""
    global _global_report_system
    if _global_report_system is None:
        _global_report_system = ReportSystem(get_workgroup())
    return _global_report_system


def get_blackboard() -> StatusBlackboard:
    """获取全局状态黑板实例"""
    global _global_blackboard
    if _global_blackboard is None:
        _global_blackboard = StatusBlackboard()
    return _global_blackboard


def get_filelock() -> FileLock:
    """获取全局文件锁实例"""
    global _global_filelock
    if _global_filelock is None:
        _global_filelock = FileLock()
    return _global_filelock