# -*- coding: utf-8 -*-
"""364章 T1.5: 模型故障回退链 — 云API失败时自动降级到备用引擎"""

import time
from typing import List, Optional, Callable


class FailoverChain:
    def __init__(self, engine_names: List[str], max_retries: int = 1, max_fallbacks: int = 2):
        self.engine_names = engine_names
        self.max_retries = max_retries
        self.max_fallbacks = max_fallbacks

    def execute(self, call_fn: Callable, engine_names: Optional[List[str]] = None) -> dict:
        engines = engine_names or self.engine_names
        fallbacks_used = 0
        for engine_name in engines:
            for attempt in range(self.max_retries + 1):
                try:
                    result = call_fn(engine_name)
                    return {"success": True, "engine": engine_name, "attempt": attempt + 1,
                            "fallbacks_used": fallbacks_used, "result": result}
                except Exception as e:
                    err_str = str(e).lower()
                    is_transient = any(kw in err_str for kw in
                                       ["timeout", "timed out", "429", "rate limit", "connection",
                                        "network", "503", "502", "connecttimeout"])
                    if not is_transient:
                        return {"success": False, "engine": engine_name, "error": str(e),
                                "attempt": attempt + 1, "fallbacks_used": fallbacks_used}
                    if attempt < self.max_retries:
                        time.sleep(0.5 * (attempt + 1))
                        continue
            fallbacks_used += 1
            if fallbacks_used >= self.max_fallbacks:
                break
        return {"success": False, "engine": engines[-1] if engines else "",
                "error": "All engines in failover chain exhausted",
                "fallbacks_used": fallbacks_used}
