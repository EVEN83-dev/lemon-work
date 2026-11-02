# -*- coding: utf-8 -*-
"""
LemonGaze · 柠檬之瞳 —— 标准模式右边栏陪伴子层

归属：嵌套在标准模式内（非独立模式、非并行模式），只是右边栏 dock 里的活体组件。
分层：
  L0 基础态（默认，无摄像头）：拟人态 + 鼠标跟随，像 lemon 小助手
  L1 摄像头态（用户主动开启）：本地 YOLO/OpenCV/MediaPipe 眼脸追踪，视觉跟随
  L2 agent 态（后续）：接本机 LLM，事件驱动多元互动

本包只新增 standard_mode/ui/companion/，不触碰 standard_mode/core 冻结区。
DriveEye（驭瞳）仅作算法参考，CV 代码独立实现，避免软著归属问题。
"""
from .companion_eye_view import CompanionEyeView, EyeExpression, EyeShapeParams
from .companion_state import CompanionState

__all__ = ["CompanionEyeView", "EyeExpression", "EyeShapeParams", "CompanionState"]
