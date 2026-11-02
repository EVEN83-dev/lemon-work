import json
import time
import threading
import re
import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_SENSITIVE_RULES = [
    # ★ v5.7: 分隔符类补入 \\ —— json.dumps 会把引号转义成 \"，
    #   旧正则遇到反斜杠即断链，导致 api_key=\"sk-...\" 完全不脱敏
    (re.compile(r'(api[_-]?key|token|secret|password|auth)["\s:=\\]+(["\']?)([\w\-\.]{8,})\2', re.IGNORECASE), r'\1\2***REDACTED***\2'),
    (re.compile(r'(sk-|pk-|Bearer\s+)([\w\-]{20,})', re.IGNORECASE), r'\1***REDACTED***'),
]


@dataclass
class TelemetryConfig:
    enabled: bool = False
    endpoint: str = ""
    sample_rate: float = 1.0
    batch_size: int = 10
    flush_interval: float = 30.0


class TelemetryReporter:
    def __init__(self, config: Optional[TelemetryConfig] = None):
        self._config = config or TelemetryConfig()
        self._queue: List[Dict] = []
        # ★ v5.7: 必须用可重入锁 RLock —— report_error() 持锁期间在凑满
        #   batch_size 时会调用 _flush()，_flush() 再次抢同一把锁；
        #   threading.Lock 不可重入会永久死锁
        self._lock = threading.RLock()
        self._last_flush = time.time()
        self._timer = None
        if self._config.enabled and self._config.endpoint:
            self._start_timer()

    def report_error(self, error_dict: Dict) -> None:
        if not self._config.enabled or not self._config.endpoint:
            return
        import random
        if random.random() > self._config.sample_rate:
            return
        sanitized = self._sanitize(error_dict)
        with self._lock:
            self._queue.append(sanitized)
            if len(self._queue) >= self._config.batch_size:
                self._flush()

    def _sanitize(self, data: Dict) -> Dict:
        text = json.dumps(data, ensure_ascii=False)
        for pattern, replacement in _SENSITIVE_RULES:
            text = pattern.sub(replacement, text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": "sanitization_failed"}

    def _flush(self) -> None:
        if not self._queue:
            return
        batch = []
        with self._lock:
            batch = self._queue[:]
            self._queue.clear()
        try:
            self._send_batch(batch)
        except Exception as e:
            logger.debug(f"[Telemetry] flush failed (silently dropped): {e}")

    def _send_batch(self, batch: List[Dict]) -> None:
        try:
            import requests
            resp = requests.post(
                self._config.endpoint,
                json={"events": batch},
                timeout=5,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 300:
                logger.debug(f"[Telemetry] server returned {resp.status_code}")
        except Exception as e:
            logger.debug(f"[Telemetry] send failed: {e}")

    def _start_timer(self) -> None:
        if self._config.flush_interval > 0:
            self._timer = threading.Timer(self._config.flush_interval, self._flush_and_reschedule)
            self._timer.daemon = True
            self._timer.start()

    def _flush_and_reschedule(self) -> None:
        self._flush()
        self._start_timer()

    def shutdown(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._flush()


_telemetry_instance: Optional[TelemetryReporter] = None


def get_telemetry_reporter() -> TelemetryReporter:
    global _telemetry_instance
    if _telemetry_instance is None:
        try:
            from standard_mode.core.config_manager import get_config
            cfg = get_config()
            tel_cfg = cfg.get("telemetry", {})
            _telemetry_instance = TelemetryReporter(TelemetryConfig(
                enabled=tel_cfg.get("enabled", False),
                endpoint=tel_cfg.get("endpoint", ""),
                sample_rate=tel_cfg.get("sample_rate", 1.0),
            ))
        except Exception:
            _telemetry_instance = TelemetryReporter()
    return _telemetry_instance
