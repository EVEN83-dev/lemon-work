# -*- coding: utf-8 -*-
"""Lemon Agent 轨迹事件协议
所属窗口: bridge.trajectory  品牌组件: 事件类型定义
说明: 核心类型定义在 shared/tracer.py 的 TrajectoryEventType,
      此文件提供兼容导入 + 扩展辅助函数
"""
from shared.tracer import (
    TrajectoryEvent,
    TrajectoryEventType,
)

__all__ = ["TrajectoryEvent", "TrajectoryEventType"]


def make_event_dict(event: TrajectoryEvent) -> dict:
    return {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "event_type": event.event_type,
        "timestamp": event.timestamp,
        "data": event.data,
        "parent_event_id": event.parent_event_id,
        "agent_id": event.agent_id,
        "agent_name": event.agent_name,
    }
