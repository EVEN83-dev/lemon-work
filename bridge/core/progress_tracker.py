from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ProgressEvent:
    event_type: str = ""
    session_id: str = ""
    step: int = 0
    total_steps: int = 0
    description: str = ""
    timestamp: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eventType": self.event_type,
            "sessionId": self.session_id,
            "step": self.step,
            "totalSteps": self.total_steps,
            "description": self.description,
            "timestamp": self.timestamp,
            **self.extra,
        }


@dataclass
class IntermediateFinding:
    finding_id: str = ""
    content: str = ""
    source_skill: str = ""
    importance: str = "normal"
    timestamp: float = 0.0
    files_analyzed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "findingId": self.finding_id,
            "content": self.content,
            "sourceSkill": self.source_skill,
            "importance": self.importance,
            "timestamp": self.timestamp,
            "filesAnalyzed": self.files_analyzed,
        }


class ProgressTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: List[ProgressEvent] = []
        self._findings: List[IntermediateFinding] = []
        self._callback: Optional[Callable[[ProgressEvent], None]] = None
        self._finding_callback: Optional[Callable[[IntermediateFinding], None]] = None
        self._current_step: int = 0
        self._total_steps: int = 0
        self._session_id: str = ""
        self._start_time: float = 0.0

    def set_callback(self, callback: Callable[[ProgressEvent], None]) -> None:
        self._callback = callback

    def set_finding_callback(self, callback: Callable[[IntermediateFinding], None]) -> None:
        self._finding_callback = callback

    def start(self, session_id: str, total_steps: int = 10) -> None:
        with self._lock:
            self._session_id = session_id
            self._current_step = 0
            self._total_steps = total_steps
            self._start_time = time.time()
            self._events.clear()
            self._findings.clear()
        self._emit("progress_start", "开始执行任务...")

    def tool_call(self, skill_name: str, args: Dict[str, Any]) -> None:
        with self._lock:
            self._current_step += 1
            step = self._current_step
            total = self._total_steps
        desc = self._describe_tool_call(skill_name, args, step, total)
        self._emit("progress_tool", desc, step=step, total_steps=total,
                    extra={"skillName": skill_name})

    def summarizing(self) -> None:
        with self._lock:
            step = self._current_step
            total = self._total_steps
        self._emit("progress_summary", "正在生成总结...", step=step, total_steps=total)

    def done(self) -> None:
        with self._lock:
            step = self._total_steps
            total = self._total_steps
        self._emit("progress_done", "任务完成", step=step, total_steps=total)

    def intent_analyzed(self, intent_type: str, confidence: float) -> None:
        with self._lock:
            step = self._current_step
            total = self._total_steps
        self._emit("progress_intent",
                   f"意图识别: {intent_type} (置信度: {confidence:.2f})",
                   step=step, total_steps=total,
                   extra={"intentType": intent_type, "confidence": confidence})

    def context_compressed(self, original_tokens: int, compressed_tokens: int) -> None:
        ratio = (1 - compressed_tokens / max(1, original_tokens)) * 100
        with self._lock:
            step = self._current_step
            total = self._total_steps
        self._emit("progress_compress",
                   f"上下文压缩: {original_tokens} -> {compressed_tokens} tokens ({ratio:.0f}%)",
                   step=step, total_steps=total,
                   extra={"originalTokens": original_tokens,
                          "compressedTokens": compressed_tokens,
                          "ratio": round(ratio, 1)})

    def tool_result_received(self, skill_name: str, success: bool,
                              output_preview: str) -> None:
        status = "成功" if success else "失败"
        with self._lock:
            step = self._current_step
            total = self._total_steps
        self._emit("progress_result",
                   f"{skill_name} 执行{status}: {output_preview[:80]}",
                   step=step, total_steps=total,
                   extra={"skillName": skill_name, "success": success})

    def add_finding(self, content: str, source_skill: str = "",
                    importance: str = "normal", files_analyzed: int = 0) -> IntermediateFinding:
        with self._lock:
            finding = IntermediateFinding(
                finding_id=f"f_{len(self._findings)}_{int(time.time())}",
                content=content,
                source_skill=source_skill,
                importance=importance,
                timestamp=time.time(),
                files_analyzed=files_analyzed,
            )
            self._findings.append(finding)
        if self._finding_callback:
            try:
                self._finding_callback(finding)
            except Exception:
                pass
        return finding

    def generate_finding_summary(self, interval: int = 5) -> Optional[str]:
        with self._lock:
            findings = list(self._findings)
        if len(findings) < interval:
            return None
        recent = findings[-interval:]
        parts = [f"已分析 {recent[-1].files_analyzed} 个文件，发现以下关键信息："]
        for i, f in enumerate(recent, 1):
            parts.append(f"  {i}. {f.content}")
        return "\n".join(parts)

    def get_progress_pct(self) -> float:
        if self._total_steps <= 0:
            return 0.0
        return round(min(1.0, self._current_step / self._total_steps), 4)

    def get_elapsed_seconds(self) -> float:
        if self._start_time <= 0:
            return 0.0
        return time.time() - self._start_time

    def get_eta_seconds(self) -> float:
        pct = self.get_progress_pct()
        elapsed = self.get_elapsed_seconds()
        if pct <= 0:
            return 0.0
        return round(elapsed / pct - elapsed, 1)

    def render_progress_hud(self) -> str:
        with self._lock:
            step = self._current_step
            total = self._total_steps
            last_event = self._events[-1] if self._events else None
        pct = self.get_progress_pct()
        elapsed = self.get_elapsed_seconds()
        eta = self.get_eta_seconds()

        desc = last_event.description if last_event else "等待中..."
        bar_len = 20
        filled = int(pct * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        return (
            f'<div style="font-family:monospace; padding:12px; '
            f'background:rgba(8,8,16,0.8); border:1px solid rgba(255,154,74,0.2); '
            f'border-radius:8px; backdrop-filter:blur(8px);">'
            f'<div style="font-size:11px; color:#94a3b8; margin-bottom:6px;">'
            f'Agent 进度</div>'
            f'<div style="color:Lemon.BRAND_ORANGE_LIGHT; font-size:13px; margin-bottom:4px;">'
            f'{bar} {int(pct * 100)}%</div>'
            f'<div style="font-size:12px; color:#cbd5e1; margin-bottom:2px;">'
            f'{desc} ({step}/{total})</div>'
            f'<div style="font-size:10px; color:#64748b;">'
            f'已耗时 {elapsed:.0f}s · 预计剩余 {eta:.0f}s</div>'
            f'</div>'
        )

    def render_findings_hud(self) -> str:
        with self._lock:
            findings = list(self._findings)
        if not findings:
            return ""
        items = []
        for f in findings:
            color = "Lemon.STATUS_WARNING" if f.importance == "high" else "Lemon.ACCENT_BLUE"
            items.append(
                f'<div style="padding:4px 0; border-left:2px solid {color}; '
                f'padding-left:8px; margin-bottom:4px; font-size:12px; color:#e2e8f0;'
                f' text-shadow:0 0 6px rgba(255,255,255,0.05);">'
                f'{_esc(f.content)}</div>'
            )
        findings_html = "\n".join(items)
        return (
            f'<div style="font-family:monospace; padding:12px; '
            f'background:rgba(8,8,16,0.8); border:1px solid rgba(96,165,250,0.2); '
            f'border-radius:8px; backdrop-filter:blur(8px);">'
            f'<div style="font-size:11px; color:#94a3b8; margin-bottom:6px;">'
            f'中间发现 ({len(findings)})</div>'
            f'{findings_html}</div>'
        )

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            findings_count = len(self._findings)
            events_count = len(self._events)
        return {
            "current_step": self._current_step,
            "total_steps": self._total_steps,
            "progress_pct": self.get_progress_pct(),
            "elapsed_seconds": self.get_elapsed_seconds(),
            "eta_seconds": self.get_eta_seconds(),
            "findings_count": findings_count,
            "events_count": events_count,
        }

    def _emit(self, event_type: str, description: str,
              step: int = 0, total_steps: int = 0,
              extra: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            evt = ProgressEvent(
                event_type=event_type,
                session_id=self._session_id,
                step=step or self._current_step,
                total_steps=total_steps or self._total_steps,
                description=description,
                timestamp=time.time(),
                extra=extra or {},
            )
            self._events.append(evt)
        if self._callback:
            try:
                self._callback(evt)
            except Exception:
                pass

    @staticmethod
    def _describe_tool_call(skill_name: str, args: Dict[str, Any],
                            step: int, total: int) -> str:
        name_map = {
            "file_read": "读取文件",
            "read_file": "读取文件",
            "code_review": "分析代码",
            "search": "搜索信息",
            "web_search": "搜索网络",
            "deep_research": "深度研究",
            "super_research": "综合研究",
        }
        action = name_map.get(skill_name, f"执行 {skill_name}")
        target = ""
        if "path" in args:
            target = f" {args['path']}"
        elif "query" in args:
            target = f" {args['query']}"
        elif "file" in args:
            target = f" {args['file']}"
        return f"正在{action}{target}... ({step}/{total})"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
