# -*- coding: utf-8 -*-
"""
Intelligent Bridge Router — 多桥接智能路由
===========================================
核心功能：
1. 管理多种桥接通道（HTTP Bridge / Process Bridge / Ollama）
2. 实时健康监控（周期性检测 + 主动探测）
3. 自动切换最佳通道（优先级 + 健康度）

通道优先级：
  HTTP Bridge (mimo serve)  →  Process Bridge (mimo run)  →  Ollama

设计原则：
- 每个通道独立健康检测，不互相阻塞
- 切换时保留上下文（会话ID、对话历史）
- 支持手动指定通道（MIMO模式/自动模式）
"""

import os
import time
import threading
import json
from typing import Optional, Dict, List, Callable
from enum import Enum

from PyQt5.QtCore import QObject, pyqtSignal, QTimer


class BridgeType(Enum):
    """桥接通道类型"""
    HTTP = "http"           # HTTP + SSE（mimo serve）
    PROCESS = "process"     # QProcess（mimo run）
    OLLAMA = "ollama"       # Ollama 本地引擎


class BridgeStatus(Enum):
    """桥接通道状态"""
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"   # 降级运行（功能受限）
    UNKNOWN = "unknown"


class BridgeHealth:
    """桥接通道健康状态"""
    
    def __init__(self, bridge_type: BridgeType):
        self.bridge_type = bridge_type
        self.status = BridgeStatus.UNKNOWN
        self.last_check = 0.0
        self.last_success = 0.0
        self.last_failure = 0.0
        self.failure_count = 0
        self.success_count = 0
        self.latency_ms = 0.0
        self.error_message = ""
    
    @property
    def is_healthy(self) -> bool:
        return self.status == BridgeStatus.ONLINE
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total
    
    def record_success(self, latency_ms: float = 0):
        self.status = BridgeStatus.ONLINE
        self.last_success = time.time()
        self.last_check = time.time()
        self.success_count += 1
        self.latency_ms = latency_ms
        self.error_message = ""
    
    def record_failure(self, error: str = ""):
        self.status = BridgeStatus.OFFLINE
        self.last_failure = time.time()
        self.last_check = time.time()
        self.failure_count += 1
        self.error_message = error
    
    def to_dict(self) -> dict:
        return {
            "type": self.bridge_type.value,
            "status": self.status.value,
            "is_healthy": self.is_healthy,
            "latency_ms": self.latency_ms,
            "success_rate": round(self.success_rate, 2),
            "failure_count": self.failure_count,
            "last_check": self.last_check,
            "error": self.error_message,
        }


class IntelligentBridgeRouter(QObject):
    """
    智能桥接路由器
    ================
    管理多个通信通道，自动选择最佳可用通道。
    
    切换逻辑：
    1. 优先使用 HTTP Bridge（功能最完整）
    2. HTTP 不可用时尝试 Process Bridge（绕过线程池）
    3. 两者都不可用时回退到 Ollama
    
    使用方式：
        router = IntelligentBridgeRouter()
        router.set_http_checker(lambda: check_mimo_http())
        router.set_process_available(lambda: check_mimo_exe())
        router.start_monitoring()
        
        # 发送消息
        bridge = router.get_best_bridge()
        if bridge == BridgeType.HTTP:
            send_via_http(msg)
        elif bridge == BridgeType.PROCESS:
            send_via_process(msg)
        else:
            send_via_ollama(msg)
    """
    
    # 信号
    bridge_changed = pyqtSignal(str, str)      # (old_bridge, new_bridge)
    health_updated = pyqtSignal(str)            # JSON 健康状态
    bridge_error = pyqtSignal(str, str)         # (bridge_type, error_msg)
    
    # 通道优先级（从高到低）
    # ★ v3.60: 仅 Process Bridge，移除 HTTP 和 Ollama
    # MIMO 模式下只使用 MIMO Code，绝不自动回退到 Ollama
    BRIDGE_PRIORITY = [BridgeType.PROCESS]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 健康状态
        self._health: Dict[BridgeType, BridgeHealth] = {
            bt: BridgeHealth(bt) for bt in BridgeType
        }
        
        # 健康检查回调
        self._checkers: Dict[BridgeType, Callable[[], bool]] = {}
        
        # 当前活动通道
        self._active_bridge = BridgeType.PROCESS  # ★ v3.60: 默认 Process，不是 Ollama
        self._manual_mode = True  # ★ v3.60: 始终手动模式，禁止自动切换
        self._fallback_disabled = True  # ★ v3.60: 始终禁止回退
        
        # 监控定时器
        self._monitor_timer = QTimer()
        self._monitor_timer.timeout.connect(self._check_all_bridges)
        self._monitor_interval = 30000  # 30秒检测一次
        
        # 锁
        self._lock = threading.Lock()
    
    # ==================== 健康检查设置 ====================
    
    def set_http_checker(self, checker: Callable[[], bool]):
        """设置 HTTP 桥接健康检查回调"""
        self._checkers[BridgeType.HTTP] = checker
    
    def set_process_checker(self, checker: Callable[[], bool]):
        """设置 Process 桥接可用性检查回调"""
        self._checkers[BridgeType.PROCESS] = checker
    
    def set_ollama_checker(self, checker: Callable[[], bool]):
        """设置 Ollama 可用性检查回调"""
        self._checkers[BridgeType.OLLAMA] = checker
    
    # ==================== 监控控制 ====================
    
    def start_monitoring(self, interval_ms: int = 30000):
        """启动健康监控"""
        self._monitor_interval = interval_ms
        self._monitor_timer.start(interval_ms)
        # 立即执行一次检查
        QTimer.singleShot(100, self._check_all_bridges)
    
    def stop_monitoring(self):
        """停止健康监控"""
        self._monitor_timer.stop()
    
    def check_now(self):
        """立即执行一次全面健康检查"""
        self._check_all_bridges()
    
    # ==================== 通道选择 ====================
    
    def get_best_bridge(self) -> BridgeType:
        """获取当前最佳可用通道
        
        优先级: Process Bridge 唯一
        """
        # 手动模式：直接返回指定通道
        if self._manual_mode:
            return self._active_bridge
        
        with self._lock:
            for bridge_type in self.BRIDGE_PRIORITY:
                health = self._health[bridge_type]
                if health.is_healthy:
                    if bridge_type != self._active_bridge:
                        old = self._active_bridge
                        self._active_bridge = bridge_type
                        self.bridge_changed.emit(old.value, bridge_type.value)
                    return bridge_type
            
            # 所有通道都不可用，返回当前（通常是最安全的 Ollama）
            return self._active_bridge
    
    def force_bridge(self, bridge_type: BridgeType):
        """强制切换到指定通道"""
        self._manual_mode = True
        self._fallback_disabled = True
        old = self._active_bridge
        self._active_bridge = bridge_type
        self.bridge_changed.emit(old.value, bridge_type.value)
    
    def set_auto_mode(self):
        """★ v3.60: 自动模式已禁用，始终保持 Process Bridge"""
        pass  # 不做任何操作，保持手动模式 + Process Bridge
    
    def set_fallback_disabled(self, disabled: bool):
        """设置是否禁止回退"""
        self._fallback_disabled = disabled
    
    @property
    def active_bridge(self) -> BridgeType:
        return self._active_bridge
    
    @property
    def is_manual_mode(self) -> bool:
        return self._manual_mode
    
    # ==================== 健康检查执行 ====================
    
    def _check_all_bridges(self):
        """检查所有通道的健康状态"""
        for bridge_type in self.BRIDGE_PRIORITY:
            self._check_single_bridge(bridge_type)
        
        # 发射健康状态更新
        self._emit_health_update()
        
        # 自动模式下重新评估最佳通道
        if not self._manual_mode:
            self.get_best_bridge()
    
    def _check_single_bridge(self, bridge_type: BridgeType):
        """检查单个通道"""
        checker = self._checkers.get(bridge_type)
        if checker is None:
            return
        
        health = self._health[bridge_type]
        start = time.time()
        
        try:
            if checker():
                latency = (time.time() - start) * 1000
                health.record_success(latency)
            else:
                health.record_failure("不可用")
        except Exception as e:
            health.record_failure(str(e))
    
    def _emit_health_update(self):
        """发射健康状态更新"""
        health_data = {
            bt.value: h.to_dict()
            for bt, h in self._health.items()
        }
        health_data["active_bridge"] = self._active_bridge.value
        health_data["manual_mode"] = self._manual_mode
        self.health_updated.emit(json.dumps(health_data, ensure_ascii=False))
    
    # ==================== 健康查询 ====================
    
    def get_health(self, bridge_type: BridgeType = None) -> dict:
        """获取健康状态"""
        if bridge_type:
            return self._health[bridge_type].to_dict()
        return {
            bt.value: h.to_dict()
            for bt, h in self._health.items()
        }
    
    def is_available(self, bridge_type: BridgeType) -> bool:
        """检查指定通道是否可用"""
        return self._health[bridge_type].is_healthy
    
    def get_latency(self, bridge_type: BridgeType) -> float:
        """获取通道延迟（毫秒）"""
        return self._health[bridge_type].latency_ms
    
    # ==================== 手动健康更新（由外部调用） ====================
    
    def report_success(self, bridge_type: BridgeType, latency_ms: float = 0):
        """外部报告通道成功"""
        self._health[bridge_type].record_success(latency_ms)
        self._emit_health_update()
    
    def report_failure(self, bridge_type: BridgeType, error: str = ""):
        """外部报告通道失败"""
        self._health[bridge_type].record_failure(error)
        self.bridge_error.emit(bridge_type.value, error)
        self._emit_health_update()
        
        # 自动回退
        if not self._fallback_disabled and bridge_type == self._active_bridge:
            self.get_best_bridge()