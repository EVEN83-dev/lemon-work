"""
B-P2-007: AI Engine Manager

Manages multiple AI engines with auto-fallback:
  local_ai  → HarmonyOS HiAI Foundation Kit (on-device)
  cloud_api → User-configured cloud API (DeepSeek, etc.)
  pangu     → Huawei Pangu (if available)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("lemon_bridge.ai_engine")


class EngineTier(str, Enum):
    LOCAL = "local_ai"
    CLOUD = "cloud_api"
    PANGU = "pangu"


@dataclass
class EngineStatus:
    name: str = ""
    tier: EngineTier = EngineTier.LOCAL
    available: bool = False
    latency_ms: int = 0
    model: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "tier": self.tier.value,
            "available": self.available,
            "latencyMs": self.latency_ms,
            "model": self.model,
        }


class AIEngineManager:
    def __init__(self):
        self._engines: Dict[str, EngineStatus] = {}
        self._primary: str = "cloud_api"
        self._fallback_order: List[EngineTier] = [
            EngineTier.CLOUD,
            EngineTier.LOCAL,
            EngineTier.PANGU,
        ]

    def register(self, name: str, tier: EngineTier, model: str = "") -> None:
        self._engines[name] = EngineStatus(
            name=name, tier=tier, model=model, available=False
        )

    def set_primary(self, name: str) -> None:
        if name in self._engines:
            self._primary = name

    def get_primary(self) -> str:
        return self._primary

    async def health_check(self) -> Dict[str, Any]:
        import time as _time
        for name, status in self._engines.items():
            try:
                if status.tier == EngineTier.LOCAL:
                    import requests
                    start = _time.monotonic()
                    resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
                    status.available = resp.status_code == 200
                    status.latency_ms = int((_time.monotonic() - start) * 1000)
                elif status.tier == EngineTier.CLOUD:
                    import requests as _req
                    start = _time.monotonic()
                    resp = _req.get("https://api.deepseek.com/models", timeout=3,
                                    headers={"Authorization": "Bearer test"})
                    status.available = resp.status_code in (200, 401, 403)
                    status.latency_ms = int((_time.monotonic() - start) * 1000)
                elif status.tier == EngineTier.PANGU:
                    status.available = False
                    status.latency_ms = -1
                else:
                    status.available = False
            except Exception:
                status.available = False
                status.latency_ms = -1
        return {name: s.to_dict() for name, s in self._engines.items()}

    async def get_available_engine(self) -> Optional[str]:
        if self._primary in self._engines and self._engines[self._primary].available:
            return self._primary

        for tier in self._fallback_order:
            for name, status in self._engines.items():
                if status.tier == tier and status.available:
                    logger.info(f"Auto-fallback to engine: {name} (tier: {tier.value})")
                    return name

        return None

    def list_engines(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self._engines.values()]

    def get_engine_status(self, name: str) -> Optional[Dict[str, Any]]:
        status = self._engines.get(name)
        return status.to_dict() if status else None
