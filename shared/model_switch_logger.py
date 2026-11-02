# -*- coding: utf-8 -*-
"""
模型切换日志系统
=================
为 Lemon Agent 提供完整的模型切换记录，包括：
- 切换时间戳
- 从哪个引擎/模型切换到哪个引擎/模型
- 切换原因（手动/自动/故障转移）
- 引擎可用性状态
- 模型响应性能统计

日志输出位置：
- 控制台（实时）
- 日志文件（logs/model_switch.log）
"""

import os
import json
import threading
from datetime import datetime
from typing import Optional, Dict, List
from enum import Enum


class SwitchReason(Enum):
    MANUAL = "manual"           # 用户手动切换
    AUTO_ROUTE = "auto_route"   # 智能路由自动切换
    FALLBACK = "fallback"       # 故障转移
    STARTUP = "startup"         # 启动时初始化
    HYBRID = "hybrid"           # 混合模式切换


class ModelSwitchLogger:
    """
    模型切换日志记录器

    用法：
        logger = ModelSwitchLogger()
        logger.log_switch(
            from_engine="ollama",
            to_engine="lmstudio",
            from_model="qwen3.5:4b",
            to_model="llama-3.1-8b",
            reason=SwitchReason.MANUAL,
            success=True,
        )
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
        self._log_file = os.path.join(self._log_dir, "model_switch.log")
        self._switches: List[Dict] = []
        self._lock = threading.Lock()

        # 确保日志目录存在
        os.makedirs(self._log_dir, exist_ok=True)

    def log_switch(self,
                   from_engine: str = "",
                   to_engine: str = "",
                   from_model: str = "",
                   to_model: str = "",
                   reason: SwitchReason = SwitchReason.MANUAL,
                   success: bool = True,
                   error: str = "",
                   extra: Dict = None) -> Dict:
        """记录一次模型切换"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "from_engine": from_engine,
            "to_engine": to_engine,
            "from_model": from_model,
            "to_model": to_model,
            "reason": reason.value,
            "success": success,
            "error": error,
            "extra": extra or {},
        }

        with self._lock:
            self._switches.append(entry)
            # 只保留最近 500 条记录
            if len(self._switches) > 500:
                self._switches = self._switches[-500:]

        # 写入日志文件
        self._write_to_file(entry)

        # 控制台输出
        status = "✓" if success else "✗"
        print(f"[ModelSwitch] {status} {from_engine}/{from_model} → {to_engine}/{to_model} | 原因: {reason.value}")

        return entry

    def log_engine_status(self, engine_id: str, available: bool, model: str = "",
                          models_count: int = 0, extra: Dict = None):
        """记录引擎状态"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "engine_status",
            "engine_id": engine_id,
            "available": available,
            "model": model,
            "models_count": models_count,
            "extra": extra or {},
        }

        with self._lock:
            self._switches.append(entry)
            if len(self._switches) > 500:
                self._switches = self._switches[-500:]

        self._write_to_file(entry)
        status = "在线" if available else "离线"
        print(f"[ModelSwitch] 引擎状态: {engine_id} [{status}] 模型: {model}")

    def log_performance(self, engine_id: str, model: str, response_time: float,
                        tokens_used: int = 0, success: bool = True):
        """记录模型性能"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "performance",
            "engine_id": engine_id,
            "model": model,
            "response_time": round(response_time, 3),
            "tokens_used": tokens_used,
            "success": success,
        }

        with self._lock:
            self._switches.append(entry)
            if len(self._switches) > 500:
                self._switches = self._switches[-500:]

        self._write_to_file(entry)

    def _write_to_file(self, entry: Dict):
        """写入日志文件"""
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_recent_switches(self, limit: int = 50) -> List[Dict]:
        """获取最近切换记录"""
        with self._lock:
            return self._switches[-limit:]

    def get_switches_by_engine(self, engine_id: str) -> List[Dict]:
        """获取指定引擎的切换记录"""
        with self._lock:
            return [s for s in self._switches
                    if s.get("from_engine") == engine_id or s.get("to_engine") == engine_id]

    def get_summary(self) -> Dict:
        """获取切换摘要"""
        with self._lock:
            switches = [s for s in self._switches if "to_engine" in s]
            total = len(switches)
            successful = sum(1 for s in switches if s.get("success"))
            failed = total - successful

            # 按引擎统计
            engine_stats = {}
            for s in switches:
                eng = s.get("to_engine", "unknown")
                if eng not in engine_stats:
                    engine_stats[eng] = {"total": 0, "success": 0, "failed": 0}
                engine_stats[eng]["total"] += 1
                if s.get("success"):
                    engine_stats[eng]["success"] += 1
                else:
                    engine_stats[eng]["failed"] += 1

            return {
                "total_switches": total,
                "successful": successful,
                "failed": failed,
                "success_rate": f"{successful/max(total,1)*100:.1f}%",
                "by_engine": engine_stats,
                "last_switch": switches[-1] if switches else None,
            }

    def clear(self):
        """清空日志"""
        with self._lock:
            self._switches.clear()
            try:
                open(self._log_file, "w").close()
            except Exception:
                pass


# ==================== 全局单例 ====================

def get_switch_logger() -> ModelSwitchLogger:
    """获取全局切换日志记录器"""
    return ModelSwitchLogger()