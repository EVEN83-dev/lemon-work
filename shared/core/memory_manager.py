# -*- coding: utf-8 -*-
"""持久化记忆注入（v5.5 补全）。

将 MEMORY.md / 历史要点注入到 system_prompt，让 Agent 具备跨会话记忆。
调用点：engine_manager.py L3142  => mem_mgr.inject_into_prompt(system_prompt, max_chars=2000)
"""
import os
import logging

logger = logging.getLogger(__name__)

_MEMORY_PATHS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "MEMORY.md"),
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "MEMORY.md"),
]


class MemoryManager:
    def __init__(self):
        self._cache = None
        self._cache_mtime = 0

    def _load_memory_text(self) -> str:
        import time
        for p in _MEMORY_PATHS:
            if os.path.exists(p):
                try:
                    mtime = os.path.getmtime(p)
                    if self._cache is None or mtime != self._cache_mtime:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            self._cache = f.read()
                        self._cache_mtime = mtime
                    return self._cache or ""
                except Exception as e:
                    logger.debug(f"[MemoryManager] 读取 {p} 失败: {e}")
        return ""

    def inject_into_prompt(self, prompt: str, max_chars: int = 2000) -> str:
        """把持久化记忆拼到 prompt 末尾（若为空则原样返回）。"""
        mem = self._load_memory_text().strip()
        if not mem:
            return prompt
        if len(mem) > max_chars:
            mem = mem[:max_chars] + "\n... (记忆截断)"
        block = "\n\n# 项目记忆 (MEMORY.md)\n" + mem
        return prompt + block


_INSTANCE = None


def get_memory_manager() -> MemoryManager:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = MemoryManager()
    return _INSTANCE
