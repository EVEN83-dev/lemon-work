# -*- coding: utf-8 -*-
"""
Ollama 负载均衡器
================
多 Agent 同时调用 Ollama 时的请求排队和负载均衡。

核心能力：
1. 请求队列 — 先进先出排队
2. 并发控制 — 限制同时请求数（默认 2）
3. 优先级调度 — 高优先级请求插队
4. 超时保护 — 请求超时自动移除
"""
import time
import threading
import heapq
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class OllamaInstance:
    host: str = "127.0.0.1"
    port: int = 11434
    weight: int = 1
    success_count: int = 0
    fail_count: int = 0
    last_latency_ms: float = 0.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.5


class RequestStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    FAILED = "failed"


@dataclass
class OllamaRequest:
    """Ollama 请求"""
    req_id: str
    agent_id: str
    prompt: str
    priority: int = 5          # 1(最高)-10(最低)
    status: RequestStatus = RequestStatus.QUEUED
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    callback: Optional[Callable] = None


class OllamaLoadBalancer:
    """Ollama 负载均衡器"""

    def __init__(self, max_concurrent: int = 2, request_timeout: float = 600.0):  # ★ v4.7.17+: 120→600 对齐 8B 模型
        self._max_concurrent = max_concurrent
        self._request_timeout = request_timeout
        self._queue: List[tuple] = []        # (priority, counter, req_id)
        self._requests: Dict[str, OllamaRequest] = {}
        self._running: Dict[str, OllamaRequest] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._completed_count = 0
        self._timeout_count = 0
        self._instances: List[OllamaInstance] = []
        self._instance_idx = 0

    def submit(self, agent_id: str, prompt: str, priority: int = 5, callback: Callable = None) -> str:
        """提交请求到队列"""
        with self._lock:
            self._counter += 1
            req_id = f"ollama_req_{self._counter}"
            req = OllamaRequest(
                req_id=req_id,
                agent_id=agent_id,
                prompt=prompt,
                priority=priority,
                callback=callback,
            )
            self._requests[req_id] = req
            heapq.heappush(self._queue, (priority, self._counter, req_id))
            return req_id

    def next_request(self) -> Optional[OllamaRequest]:
        """获取下一个可执行请求"""
        with self._lock:
            # 检查超时
            now = time.time()
            timed_out = []
            for rid, req in self._running.items():
                if now - req.started_at > self._request_timeout:
                    req.status = RequestStatus.TIMEOUT
                    timed_out.append(rid)
                    self._timeout_count += 1
            for rid in timed_out:
                del self._running[rid]

            # 如果有空位，取下一个
            if len(self._running) < self._max_concurrent and self._queue:
                _, _, req_id = heapq.heappop(self._queue)
                req = self._requests.get(req_id)
                if req:
                    req.status = RequestStatus.RUNNING
                    req.started_at = time.time()
                    self._running[req_id] = req
                    return req
            return None

    def complete_request(self, req_id: str, result: Any = None, error: str = ""):
        """标记请求完成"""
        with self._lock:
            req = self._requests.get(req_id)
            if req:
                req.status = RequestStatus.FAILED if error else RequestStatus.COMPLETED
                req.result = result
                req.error = error
                req.completed_at = time.time()
                self._running.pop(req_id, None)
                if req.status == RequestStatus.COMPLETED:
                    self._completed_count += 1
                if req.callback:
                    try:
                        req.callback(result if not error else None, error)
                    except Exception:
                        pass

    def get_status(self) -> Dict:
        """获取负载均衡器状态"""
        with self._lock:
            return {
                "queue_length": len(self._queue),
                "running": len(self._running),
                "max_concurrent": self._max_concurrent,
                "completed": self._completed_count,
                "timeout": self._timeout_count,
                "total": len(self._requests),
                "instances": [{"host": i.host, "port": i.port, "weight": i.weight, "success_rate": i.success_rate} for i in self._instances],
            }

    def cancel(self, req_id: str) -> bool:
        """取消请求"""
        with self._lock:
            if req_id in self._requests:
                del self._requests[req_id]
                self._running.pop(req_id, None)
                self._queue = [(p, c, r) for p, c, r in self._queue if r != req_id]
                heapq.heapify(self._queue)
                return True
            return False

    def add_instance(self, host: str, port: int = 11434, weight: int = 1):
        inst = OllamaInstance(host=host, port=port, weight=weight)
        with self._lock:
            self._instances.append(inst)

    def select_instance(self) -> Optional[OllamaInstance]:
        with self._lock:
            if not self._instances:
                return None
            weighted = []
            for inst in self._instances:
                effective_weight = inst.weight * (0.5 + 0.5 * inst.success_rate)
                weighted.extend([inst] * max(1, int(effective_weight * 10)))
            if not weighted:
                return self._instances[0]
            import random
            return random.choice(weighted)

    def record_instance_result(self, host: str, port: int, success: bool, latency_ms: float = 0):
        with self._lock:
            for inst in self._instances:
                if inst.host == host and inst.port == port:
                    if success:
                        inst.success_count += 1
                    else:
                        inst.fail_count += 1
                    inst.last_latency_ms = latency_ms
                    break
