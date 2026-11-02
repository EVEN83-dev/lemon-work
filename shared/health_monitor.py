# -*- coding: utf-8 -*-
"""
Health Monitor — 健康监控系统
==============================
实时监控引擎状态、连接健康度，支持自动重连和状态通知。

功能：
1. 实时监控引擎健康状态
2. 检测连接问题
3. 自动重连机制
4. 状态变更通知
5. 健康度评分
6. 监控历史记录

使用方式：
    monitor = HealthMonitor(engine_manager)
    monitor.start(interval=30)
    status = monitor.get_status()
    monitor.on_status_change(lambda engine, status: print(f"{engine}: {status}"))
"""

import time
import threading
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime


class HealthStatus:
    """健康状态枚举"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    RECONNECTING = "reconnecting"


class HealthMonitor:
    """健康监控器

    定期检查各引擎状态，记录健康度变化，支持自动重连。
    """

    def __init__(self, engine_manager=None):
        """
        Args:
            engine_manager: EngineManager 实例，用于检查引擎状态
        """
        self._engine_manager = engine_manager
        self._status: Dict[str, Dict[str, Any]] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 回调
        self._status_callbacks: List[Callable] = []
        self._alert_callbacks: List[Callable] = []

        # 重连配置
        self._auto_reconnect = True
        self._max_reconnect_attempts = 5
        self._reconnect_delay = 10  # 秒
        self._reconnect_attempts: Dict[str, int] = {}

        # 监控历史
        self._history: List[Dict[str, Any]] = []
        self._max_history = 100

        # 健康度阈值
        self._failure_threshold = 3  # 连续失败次数阈值
        self._failure_counts: Dict[str, int] = {}
        self._last_success: Dict[str, float] = {}

    # ============================================================
    # 启动/停止
    # ============================================================

    def start(self, interval: int = 30):
        """启动健康监控

        Args:
            interval: 检查间隔（秒）
        """
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop, args=(interval,), daemon=True
        )
        self._thread.start()

    def stop(self):
        """停止健康监控"""
        self._running = False

    def _monitor_loop(self, interval: int):
        """监控循环"""
        while self._running:
            try:
                self._check_health()
            except Exception:
                pass
            time.sleep(interval)

    # ============================================================
    # 健康检查
    # ============================================================

    def _check_health(self):
        """执行全面的健康检查"""
        # 获取引擎列表
        engines = self._get_engines()
        timestamp = datetime.now().isoformat()
        current_status = {}

        for engine_name in engines:
            try:
                is_healthy = self._check_engine(engine_name)
                old_status = self._status.get(engine_name, {}).get("status", HealthStatus.UNKNOWN)

                if is_healthy:
                    new_status = HealthStatus.HEALTHY
                    self._failure_counts[engine_name] = 0
                    self._last_success[engine_name] = time.time()
                    self._reconnect_attempts.pop(engine_name, None)
                else:
                    self._failure_counts[engine_name] = self._failure_counts.get(engine_name, 0) + 1
                    if self._failure_counts[engine_name] >= self._failure_threshold:
                        new_status = HealthStatus.UNHEALTHY
                    else:
                        new_status = HealthStatus.DEGRADED

                current_status[engine_name] = {
                    "status": new_status,
                    "healthy": is_healthy,
                    "last_check": timestamp,
                    "failure_count": self._failure_counts.get(engine_name, 0),
                    "last_success": self._last_success.get(engine_name),
                }

                # 状态变更通知
                if old_status != new_status:
                    self._notify_status_change(engine_name, old_status, new_status)

                # 自动重连
                if new_status == HealthStatus.UNHEALTHY and self._auto_reconnect:
                    self._try_reconnect(engine_name)

            except Exception as e:
                current_status[engine_name] = {
                    "status": HealthStatus.UNKNOWN,
                    "healthy": False,
                    "error": str(e),
                    "last_check": timestamp,
                    "failure_count": self._failure_counts.get(engine_name, 0) + 1,
                }

        with self._lock:
            self._status = current_status
            self._add_history(timestamp, current_status)

    def _check_engine(self, engine_name: str) -> bool:
        """检查单个引擎的健康状态

        Args:
            engine_name: 引擎名称

        Returns:
            是否健康
        """
        if self._engine_manager is None:
            return True  # 无引擎管理器时默认健康

        try:
            # 检查引擎是否在可用列表中
            available = self._engine_manager.get_available_engines()
            if engine_name not in available:
                return False

            # 尝试简单探测
            if engine_name == "ollama":
                return self._check_ollama()
            elif engine_name == "mimocode":
                return self._check_mimo()
            elif engine_name == "deepseek":
                return self._check_deepseek()

            return True
        except Exception:
            return False

    def _check_ollama(self) -> bool:
        """检查 Ollama 健康状态"""
        try:
            import requests
            host = getattr(self._engine_manager, "_configs", {}).get("ollama")
            if host:
                url = f"http://{host.host}:{host.port}/api/tags"
                resp = requests.get(url, timeout=5)
                return resp.status_code == 200
        except Exception:
            pass
        return False

    def _check_mimo(self) -> bool:
        """检查 MIMO 健康状态"""
        try:
            import requests
            port = getattr(self._engine_manager, "_configs", {}).get("mimocode")
            if port:
                url = f"http://127.0.0.1:{port.port}/session"
                resp = requests.get(url, timeout=5)
                return resp.status_code in (200, 404)  # 404 表示服务在线但无会话
        except Exception:
            pass
        return False

    def _check_deepseek(self) -> bool:
        """检查 DeepSeek 健康状态"""
        try:
            import requests
            config = getattr(self._engine_manager, "_configs", {}).get("deepseek")
            if config and config.api_key:
                return True  # 有 API key 即可用
        except Exception:
            pass
        return False

    # ============================================================
    # 自动重连
    # ============================================================

    def _try_reconnect(self, engine_name: str):
        """尝试自动重连引擎"""
        attempts = self._reconnect_attempts.get(engine_name, 0)
        if attempts >= self._max_reconnect_attempts:
            return

        self._reconnect_attempts[engine_name] = attempts + 1
        self._status[engine_name]["status"] = HealthStatus.RECONNECTING

        # 通知重连
        self._notify_alert(engine_name, f"正在尝试重连 (第 {attempts + 1} 次)")

        # 延迟后重试
        time.sleep(self._reconnect_delay)

        try:
            if self._engine_manager and hasattr(self._engine_manager, "initialize"):
                self._engine_manager.initialize()
        except Exception:
            pass

    def enable_auto_reconnect(self, enabled: bool = True):
        """启用/禁用自动重连"""
        self._auto_reconnect = enabled

    def set_reconnect_config(self, max_attempts: int = 5, delay: int = 10):
        """设置重连配置

        Args:
            max_attempts: 最大重连次数
            delay: 重连间隔（秒）
        """
        self._max_reconnect_attempts = max_attempts
        self._reconnect_delay = delay

    # ============================================================
    # 状态查询
    # ============================================================

    def get_status(self, engine_name: str = None) -> Dict[str, Any]:
        """获取健康状态

        Args:
            engine_name: 引擎名称，None 则返回所有引擎状态

        Returns:
            健康状态字典
        """
        with self._lock:
            if engine_name:
                return self._status.get(engine_name, {"status": HealthStatus.UNKNOWN})
            return dict(self._status)

    def get_overall_health(self) -> str:
        """获取整体健康状态

        Returns:
            HealthStatus 值
        """
        with self._lock:
            if not self._status:
                return HealthStatus.UNKNOWN

            statuses = [s["status"] for s in self._status.values()]
            if all(s == HealthStatus.HEALTHY for s in statuses):
                return HealthStatus.HEALTHY
            if any(s == HealthStatus.UNHEALTHY for s in statuses):
                return HealthStatus.UNHEALTHY
            if any(s == HealthStatus.DEGRADED for s in statuses):
                return HealthStatus.DEGRADED
            return HealthStatus.UNKNOWN

    def get_health_score(self) -> float:
        """获取健康度评分（0-100）

        Returns:
            健康度评分
        """
        with self._lock:
            if not self._status:
                return 0.0

            scores = []
            for s in self._status.values():
                if s["status"] == HealthStatus.HEALTHY:
                    scores.append(100)
                elif s["status"] == HealthStatus.DEGRADED:
                    scores.append(60)
                elif s["status"] == HealthStatus.UNHEALTHY:
                    scores.append(20)
                else:
                    scores.append(0)

            return sum(scores) / len(scores) if scores else 0.0

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取监控历史

        Args:
            limit: 最大返回条数

        Returns:
            历史记录列表
        """
        with self._lock:
            return self._history[-limit:]

    # ============================================================
    # 回调
    # ============================================================

    def on_status_change(self, callback: Callable[[str, str, str], None]):
        """注册状态变更回调

        Args:
            callback: (engine_name, old_status, new_status)
        """
        self._status_callbacks.append(callback)

    def on_alert(self, callback: Callable[[str, str], None]):
        """注册告警回调

        Args:
            callback: (engine_name, alert_message)
        """
        self._alert_callbacks.append(callback)

    def _notify_status_change(self, engine_name: str, old_status: str, new_status: str):
        """通知状态变更"""
        for callback in self._status_callbacks:
            try:
                callback(engine_name, old_status, new_status)
            except Exception:
                pass

    def _notify_alert(self, engine_name: str, message: str):
        """通知告警"""
        for callback in self._alert_callbacks:
            try:
                callback(engine_name, message)
            except Exception:
                pass

    # ============================================================
    # 内部方法
    # ============================================================

    def _get_engines(self) -> List[str]:
        """获取引擎列表"""
        if self._engine_manager:
            try:
                return self._engine_manager.get_available_engines()
            except Exception:
                pass
        return ["ollama", "mimocode", "deepseek"]

    def _add_history(self, timestamp: str, status: Dict[str, Any]):
        """添加监控历史"""
        self._history.append({
            "timestamp": timestamp,
            "status": {k: v["status"] for k, v in status.items()},
        })
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]


# ============================================================
# 全局单例
# ============================================================

_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor(engine_manager=None) -> HealthMonitor:
    """获取全局健康监控器单例"""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor(engine_manager)
    return _health_monitor