# -*- coding: utf-8 -*-
"""Ollama 并发负载均衡（v5.5 补全）。

防止高并发下 Ollama 显存溢出。
调用点：engine_manager.py L2085 => OllamaLoadBalancer(max_concurrent=2)
"""
import threading
import logging

logger = logging.getLogger(__name__)


class OllamaLoadBalancer:
    def __init__(self, max_concurrent: int = 2):
        self.max_concurrent = max_concurrent
        self._sem = threading.Semaphore(max_concurrent)
        self._active = 0
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> bool:
        ok = self._sem.acquire(timeout=timeout)
        if ok:
            with self._lock:
                self._active += 1
        return ok

    def release(self):
        with self._lock:
            if self._active > 0:
                self._active -= 1
        self._sem.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()

    @property
    def active(self) -> int:
        with self._lock:
            return self._active
