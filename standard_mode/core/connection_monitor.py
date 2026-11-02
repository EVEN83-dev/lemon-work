# -*- coding: utf-8 -*-
"""
Connection Monitor — Lemon Code 连接监测工具 v3.63
====================================================
- 启动时显示进度条，逐步检测连接
- 连接成功后不刷屏，仅在状态变化/错误时告警
- 只监测当前活动引擎对应的连接点
- 无响应/错误时自动提示原因

引擎 → 监测项映射：
  mimocode: MIMO 服务 + SSE 流 + Process Bridge（mimo.exe 子进程通信）
  ollama:   Ollama 服务 / 模型列表
  deepseek: API 连通性
"""

import os
import sys
import time
import threading
import subprocess
from typing import Dict, Optional, Callable, List

try:
    import requests
except ImportError:
    requests = None

from PyQt5.QtCore import QObject, pyqtSignal, QTimer

# ★ v3.62: MIMO 根目录（用于定位 mimo.exe）
_MIMO_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "lemon_agent"
)


ENGINE_DISPLAY_MAP = {
    "mimocode": "MIMO Code (Process Bridge)",
    "ollama": "Ollama (本地模型)",
    "deepseek": "DeepSeek (API)",
}

# 每个引擎需要监测的检查项
ENGINE_CHECKS = {
    "mimocode": ["mimo", "sse", "process_bridge"],
    "ollama": ["ollama"],
    "deepseek": ["deepseek_api"],
}


class ConnectionMonitor(QObject):
    """Lemon Code 连接监测器"""

    status_updated = pyqtSignal(str)
    summary_updated = pyqtSignal(dict)
    # ★ 卡顿修复(第338章): 后台线程完成探测后回主线程的信号
    _watchdog_results_ready = pyqtSignal(dict, str)  # (results, engine_id)

    _instance = None

    @staticmethod
    def instance():
        if ConnectionMonitor._instance is None:
            ConnectionMonitor._instance = ConnectionMonitor()
        return ConnectionMonitor._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer: Optional[QTimer] = None
        self._watchdog_interval = 30000  # 连接后静默监测间隔：30秒
        self._progress_interval = 800     # 进度条阶段间隔：0.8秒

        self._mimo_host = "http://127.0.0.1:4097"
        self._ollama_host = "http://127.0.0.1:11434"

        self._last_status: Dict = {}
        self._output_callback: Optional[Callable[[str], None]] = None
        self._connected = False          # 是否已完成首次连接
        self._last_known_state = {}      # 上次已知状态（用于检测变化）

    def set_output_callback(self, callback: Callable[[str], None]):
        self._output_callback = callback

    def _emit(self, html: str):
        if self._output_callback:
            try:
                self._output_callback(html)
            except Exception:
                pass

    # ==================== 生命周期 ====================

    def start(self):
        """启动：先显示进度条连接，完成后进入静默 watchdog 模式"""
        self._show_connection_progress()

    def start_watchdog(self):
        """进入 watchdog 模式：静默监测，仅在状态变化时告警"""
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._watchdog_check)
            # ★ 卡顿修复: 连接后台探测结果信号
            self._watchdog_results_ready.connect(self._apply_watchdog_results)
            self._timer.start(self._watchdog_interval)

    def stop(self):
        if self._timer:
            self._timer.stop()
            self._timer = None

    def check_now(self) -> Dict:
        """手动检查"""
        return self._do_check(report=False)

    # ==================== 进度条连接流程 ====================

    def _show_connection_progress(self):
        """Phase 1: 显示连接进度条（显示器风格，紧凑单行）"""
        engine_info = self._detect_engine_info()
        engine_id = engine_info["engine_id"]
        display_name = engine_info.get("display_name", engine_id)

        checks = ENGINE_CHECKS.get(engine_id, ["mimo", "ollama", "sse", "process_bridge"])
        total = len(checks)
        results = {}

        CYAN = "Lemon.ACCENT_BLUE"
        ORANGE = "Lemon.ACCENT_ORANGE"
        GRAY = "#888"

        # ★ v3.72: 显示器风格进度条 — 紧凑单行，不占多行
        self._emit(
            f'<div style="font-family:Consolas,monospace;font-size:11px;margin:2px 0;padding:4px 10px;'
            f'background:linear-gradient(90deg,Lemon.DARK_BG_1,Lemon.DARK_BG_2);border-radius:4px;'
            f'border:1px solid #30363d;display:flex;align-items:center;gap:8px;">'
            f'<span style="display:inline-block;width:12px;height:12px;border:1.5px solid {CYAN};'
            f'border-radius:2px;text-align:center;line-height:9px;font-size:9px;'
            f'color:{CYAN};font-weight:700;margin-right:2px;vertical-align:middle;">⟳</span>'
            f'<span style="color:{CYAN};font-weight:600;">连接中</span>'
            f'<span style="color:{GRAY};">|</span>'
            f'<span style="color:{ORANGE};">{display_name}</span>'
            f'<span style="color:{GRAY};">|</span>'
            f'<span id="conn-progress-bar" style="color:Lemon.ACCENT_GREEN;">...</span>'
            f'</div>'
        )

        # 逐项检测
        def check_step(idx):
            if idx >= total:
                self._finish_progress(results, engine_info, checks)
                return

            check_name = checks[idx]
            progress_pct = int((idx) / total * 100)

            # 显示器风格：紧凑的进度条
            bar = self._progress_bar(idx, total, progress_pct)
            check_labels = {
                "mimo": "MIMO",
                "ollama": "Ollama",
                "sse": "SSE",
                "process_bridge": "Bridge",
                "deepseek_api": "DeepSeek",
            }
            label = check_labels.get(check_name, check_name)

            self._emit(
                f'<div style="font-family:Consolas,monospace;font-size:10px;margin:1px 0;padding:2px 10px;'
                f'background:Lemon.DARK_BG_1;border-radius:2px;border-left:2px solid {CYAN};'
                f'display:flex;align-items:center;gap:6px;">'
                f'{bar}'
                f'<span style="color:{CYAN};">{label}</span>'
                f'</div>'
            )

            check_func = getattr(self, f'_check_{check_name}', None)
            if check_func:
                results[check_name] = check_func()

            QTimer.singleShot(self._progress_interval, lambda: check_step(idx + 1))

        QTimer.singleShot(300, lambda: check_step(0))

    def _progress_bar(self, done, total, pct):
        """生成显示器风格进度条（紧凑型）"""
        GREEN = "Lemon.ACCENT_GREEN"
        GRAY = "#30363d"
        bar_width = 8
        filled = int(done / total * bar_width)
        empty = bar_width - filled
        blocks = f'<span style="color:{GREEN};">{"▮" * filled}</span>' \
                 f'<span style="color:{GRAY};">{"▯" * empty}</span>'
        return f'<span style="color:Lemon.STATUS_RUNNING;">{pct:3d}%</span> {blocks}'

    def _finish_progress(self, results, engine_info, checks):
        """Phase 2: 进度条完成后，输出连接结果"""
        GREEN = "Lemon.ACCENT_GREEN"
        RED = "Lemon.ACCENT_RED"
        YELLOW = "Lemon.ACCENT_ORANGE"
        ORANGE = "Lemon.ACCENT_ORANGE"
        GRAY = "#888"
        CYAN = "Lemon.ACCENT_BLUE"

        engine_id = engine_info["engine_id"]
        display_name = engine_info.get("display_name", engine_id)
        conn_type = engine_info.get("connection_type", "未知")

        # 判断整体状态
        all_ok = all(r.get("online", False) for r in results.values())
        failed = [k for k, v in results.items() if not v.get("online", False)]

        # 缓存初始状态
        self._last_known_state = {k: v.get("online", False) for k, v in results.items()}
        self._last_known_state["_engine"] = engine_id

        if all_ok:
            # 全部连接成功
            online_items = []
            for k in checks:
                r = results.get(k, {})
                t = r.get("time_ms", 0)
                c = GREEN if t < 100 else YELLOW if t < 500 else RED
                labels = {
                    "mimo": "MIMO", "ollama": "Ollama", "sse": "SSE",
                    "process_bridge": "Bridge", "deepseek_api": "API"
                }
                online_items.append(
                    f'<span style="color:{GREEN};">&#10003;</span> '
                    f'<span style="color:Lemon.PLACEHOLDER;">{labels.get(k, k)}</span> '
                    f'<span style="color:{c};">{t}ms</span>'
                )

            self._emit(
                f'<div style="font-family:Consolas,monospace;font-size:11px;margin:2px 0 4px 0;padding:4px 10px;'
                f'background:Lemon.SUCCESS_BG_DARK;border-left:4px solid {GREEN};border-radius:0 0 4px 0;">'
                f'<span style="color:{GREEN};font-weight:bold;">&#10003; Lemon Code 已连接</span>'
                f'<span style="color:{GRAY};"> — {display_name}</span>'
                f'<span style="color:{GRAY};"> ({conn_type})</span>'
                f'<br><span style="color:{GRAY};">{" | ".join(online_items)}</span>'
                f'</div>'
            )

            self._connected = True
            # 启动静默 watchdog
            self.start_watchdog()

        else:
            # 有连接失败
            self._emit(
                f'<div style="font-family:Consolas,monospace;font-size:11px;margin:2px 0 2px 0;padding:4px 10px;'
                f'background:Lemon.ERROR_BG_DARK;border-left:4px solid {RED};">'
                f'<span style="color:{RED};font-weight:bold;">&#10007; 连接未完全就绪</span>'
                f'<span style="color:{GRAY};"> — {len(failed)} 项失败</span>'
                f'</div>'
            )

            for k in checks:
                r = results.get(k, {})
                if r.get("online", False):
                    t = r.get("time_ms", 0)
                    labels = {
                        "mimo": "MIMO", "ollama": "Ollama", "sse": "SSE",
                        "process_bridge": "Bridge", "deepseek_api": "API"
                    }
                    self._emit(
                        f'<div style="font-family:Consolas,monospace;font-size:10px;margin:0;padding:1px 10px 1px 28px;'
                        f'background:Lemon.DARK_MID_5;border-left:4px solid {RED};">'
                        f'<span style="color:{GREEN};">&#10003;</span> '
                        f'<span style="color:Lemon.PLACEHOLDER;">{labels.get(k, k)}</span> '
                        f'<span style="color:{GRAY};">{t}ms</span>'
                        f'</div>'
                    )
                else:
                    err = r.get("error", "未知")
                    labels = {
                        "mimo": "MIMO", "ollama": "Ollama", "sse": "SSE",
                        "process_bridge": "Bridge", "deepseek_api": "API"
                    }
                    self._emit(
                        f'<div style="font-family:Consolas,monospace;font-size:10px;margin:0;padding:1px 10px 1px 28px;'
                        f'background:Lemon.ERROR_BG_DARK;border-left:4px solid {RED};">'
                        f'<span style="color:{RED};">&#10007;</span> '
                        f'<span style="color:{RED};">{labels.get(k, k)}</span> '
                        f'<span style="color:{RED};">{err}</span>'
                        f'</div>'
                    )

            # 给出修复建议
            tips = self._get_fix_tips(failed, engine_id)
            if tips:
                self._emit(
                    f'<div style="font-family:Consolas,monospace;font-size:10px;margin:1px 0 4px 0;padding:2px 10px 2px 20px;'
                    f'background:Lemon.ERROR_BG_DARK;border-left:4px solid {YELLOW};">'
                    f'<span style="color:{YELLOW};">&#128161; {tips}</span>'
                    f'</div>'
                )

            # 启动 watchdog 持续重试
            self.start_watchdog()

    def _get_fix_tips(self, failed: List[str], engine_id: str) -> str:
        """根据失败项给出修复建议"""
        tips = []
        if "process_bridge" in failed:
            tips.append("检查 mimo.exe 是否存在且可执行")
        if "ollama" in failed:
            tips.append("检查 Ollama 服务是否运行 (ollama serve)")
        if "deepseek_api" in failed:
            tips.append("检查 DeepSeek API Key 和网络连接")
        return " | ".join(tips)

    # ==================== Watchdog 静默监测 ====================

    def _watchdog_check(self):
        """静默监测：仅在状态变化或错误时输出

        ★ 卡顿修复（2026-08-28，第338章）: 原实现由 30s QTimer 在主线程同步执行
        最多 3 个 HTTP 探测（各 timeout=3s，mimo+sse 最坏 6 秒冻结 UI）。
        现在网络探测移到 daemon 后台线程，结果经 Qt 信号回主线程做状态对比/输出。
        """
        if getattr(self, "_wd_probe_running", False):
            return  # 上一次探测未完成，跳过（防止后台线程堆积）
        self._wd_probe_running = True

        engine_info = self._detect_engine_info()
        engine_id = engine_info["engine_id"]
        checks = ENGINE_CHECKS.get(engine_id, ["mimo", "ollama", "sse", "process_bridge"])

        def _probe():
            results = {}
            for k in checks:
                check_func = getattr(self, f'_check_{k}', None)
                if check_func:
                    try:
                        results[k] = check_func()
                    except Exception as e:
                        results[k] = {"online": False, "time_ms": 0, "error": str(e)[:60]}
            self._wd_probe_running = False
            try:
                self._watchdog_results_ready.emit(results, engine_id)
            except Exception:
                pass

        threading.Thread(target=_probe, daemon=True, name="conn-watchdog-probe").start()

    def _apply_watchdog_results(self, results: Dict, engine_id: str):
        """★ 卡顿修复: 主线程应用探测结果（原 _watchdog_check 的状态对比与输出部分）"""
        try:
            checks = list(results.keys())
            current_state = {k: r.get("online", False) for k, r in results.items()}

            # 如果引擎切换了，重新初始化状态
            if self._last_known_state.get("_engine") != engine_id:
                self._last_known_state = {"_engine": engine_id}
                self._connected = False

            # 检测变化
            changed = False
            new_failures = []
            new_recoveries = []

            for k in checks:
                prev = self._last_known_state.get(k, None)
                curr = current_state.get(k, False)
                if prev is not None and prev != curr:
                    changed = True
                    if not curr and prev:
                        new_failures.append(k)
                    elif curr and not prev:
                        new_recoveries.append(k)

            # 如果之前没连接成功，现在全部好了
            if not self._connected and all(current_state.values()):
                self._connected = True
                changed = True
                engine_info = self._detect_engine_info()
                self._emit_connected(results, engine_info, checks)
                self._last_known_state = current_state
                self._last_known_state["_engine"] = engine_id
                return

            # 更新状态
            self._last_known_state = current_state
            self._last_known_state["_engine"] = engine_id

            if not changed:
                return  # 静默，无变化

            # 输出变化
            GREEN = "Lemon.ACCENT_GREEN"
            RED = "Lemon.ACCENT_RED"
            YELLOW = "Lemon.ACCENT_ORANGE"
            GRAY = "#888"
            CYAN = "Lemon.ACCENT_BLUE"

            labels = {
                "mimo": "MIMO", "ollama": "Ollama", "sse": "SSE",
                "process_bridge": "Bridge", "deepseek_api": "API"
            }

            ts = time.strftime("%H:%M:%S")

            if new_recoveries:
                names = ", ".join(labels.get(k, k) for k in new_recoveries)
                self._emit(
                    f'<div style="font-family:Consolas,monospace;font-size:11px;margin:2px 0;padding:3px 10px;'
                    f'background:Lemon.SUCCESS_BG_DARK;border-left:3px solid {GREEN};">'
                    f'<span style="color:{GRAY};">[{ts}]</span> '
                    f'<span style="color:{GREEN};">&#10003; {names} 已恢复</span>'
                    f'</div>'
                )

            if new_failures:
                for k in new_failures:
                    r = results.get(k, {})
                    err = r.get("error", "断开")
                    t = r.get("time_ms", 0)
                    self._emit(
                        f'<div style="font-family:Consolas,monospace;font-size:11px;margin:2px 0;padding:3px 10px;'
                        f'background:Lemon.ERROR_BG_DARK;border-left:3px solid {RED};">'
                        f'<span style="color:{GRAY};">[{ts}]</span> '
                        f'<span style="color:{RED};">&#10007; {labels.get(k, k)} 断开</span>'
                        f'<span style="color:{RED};"> — {err}</span>'
                        f'</div>'
                    )

                # 全部断了
                if len(new_failures) == len(checks):
                    self._emit(
                        f'<div style="font-family:Consolas,monospace;font-size:11px;margin:2px 0 4px 0;padding:3px 10px;'
                        f'background:#2a0a00;border-left:3px solid {RED};">'
                        f'<span style="color:{RED};font-weight:bold;">&#9888; Lemon Code 可能无响应</span>'
                        f'<span style="color:{YELLOW};"> — 所有连接已断开</span>'
                        f'</div>'
                    )
        except Exception:
            pass  # 状态应用失败不影响主流程

    def _emit_connected(self, results, engine_info, checks):
        """输出连接成功消息"""
        GREEN = "Lemon.ACCENT_GREEN"
        GRAY = "#888"
        YELLOW = "Lemon.ACCENT_ORANGE"

        display_name = engine_info.get("display_name", engine_info["engine_id"])
        conn_type = engine_info.get("connection_type", "")

        items = []
        labels = {
            "mimo": "MIMO", "ollama": "Ollama", "sse": "SSE",
            "process_bridge": "Bridge", "deepseek_api": "API"
        }
        for k in checks:
            r = results.get(k, {})
            t = r.get("time_ms", 0)
            c = GREEN if t < 100 else YELLOW
            items.append(
                f'<span style="color:{GREEN};">&#10003;</span> '
                f'<span style="color:Lemon.PLACEHOLDER;">{labels.get(k, k)}</span> '
                f'<span style="color:{c};">{t}ms</span>'
            )

        self._emit(
            f'<div style="font-family:Consolas,monospace;font-size:11px;margin:2px 0 4px 0;padding:4px 10px;'
            f'background:Lemon.SUCCESS_BG_DARK;border-left:4px solid {GREEN};">'
            f'<span style="color:{GREEN};font-weight:bold;">&#10003; Lemon Code 已连接</span>'
            f'<span style="color:{GRAY};"> — {display_name} ({conn_type})</span>'
            f'<br><span style="color:{GRAY};">{" | ".join(items)}</span>'
            f'</div>'
        )

    # ==================== 引擎检测 ====================

    def _detect_engine_info(self) -> Dict:
        info = {
            "engine_id": "unknown",
            "display_name": "未知",
            "connection_type": "未知",
            "available_engines": [],
        }
        try:
            from shared.engine_manager import get_engine_manager
            mgr = get_engine_manager()
            if mgr is None:
                return info
            active = getattr(mgr, '_active_engine', 'unknown')
            info["engine_id"] = active
            info["display_name"] = ENGINE_DISPLAY_MAP.get(active, active)
            if active == "mimocode":
                info["connection_type"] = "Process Bridge (subprocess, 绕过 HTTP 线程池)"
            elif active == "ollama":
                info["connection_type"] = "HTTP API (11434)"
            elif active == "deepseek":
                info["connection_type"] = "HTTPS API"
            engines = getattr(mgr, '_engines', {})
            info["available_engines"] = list(engines.keys())
        except Exception:
            pass
        return info

    # ==================== 各项检测 ====================

    def _check_mimo(self) -> Dict:
        if not requests:
            return {"online": False, "time_ms": 0, "error": "requests 未安装"}
        start = time.time()
        try:
            resp = requests.get(f"{self._mimo_host}/global/health", timeout=3)
            elapsed = int((time.time() - start) * 1000)
            return {"online": resp.status_code == 200, "time_ms": elapsed, "port": 4097}
        except requests.exceptions.ConnectionError:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": "端口未开放"}
        except requests.exceptions.Timeout:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": "超时"}
        except Exception as e:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": str(e)[:60]}

    def _check_ollama(self) -> Dict:
        if not requests:
            return {"online": False, "time_ms": 0, "error": "requests 未安装"}
        start = time.time()
        try:
            resp = requests.get(f"{self._ollama_host}/api/tags", timeout=3)
            elapsed = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                models = len(resp.json().get("models", []))
                return {"online": True, "time_ms": elapsed, "models": models}
            return {"online": False, "time_ms": elapsed, "error": f"HTTP {resp.status_code}"}
        except requests.exceptions.ConnectionError:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": "Ollama 未启动"}
        except requests.exceptions.Timeout:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": "超时"}
        except Exception as e:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": str(e)[:60]}

    def _check_sse(self) -> Dict:
        start = time.time()
        try:
            resp = requests.get(f"{self._mimo_host}/event", timeout=3, stream=True)
            elapsed = int((time.time() - start) * 1000)
            ok = resp.status_code == 200 and "event-stream" in resp.headers.get("content-type", "")
            resp.close()
            return {"online": ok, "time_ms": elapsed}
        except requests.exceptions.ConnectionError:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": "端口未开放"}
        except requests.exceptions.Timeout:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": "超时"}
        except Exception as e:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": str(e)[:60]}

    def _check_process_bridge(self) -> Dict:
        """★ v3.71: 检查 Process Bridge（mimo.exe 存在即可，无需端口）
        
        Process Bridge 通过 subprocess.Popen 直接运行 mimo.exe，
        使用 stdin/stdout 通信，不依赖任何网络端口。
        端口 4097 是 mimo serve 的 HTTP 服务器，由 _check_mimo 单独检测。
        """
        start = time.time()
        result = {"online": False, "time_ms": 0, "mimo_exe": False}
        possible = [
            os.path.join(_MIMO_ROOT, "bin", "mimo.exe"),
        ]
        for p in possible:
            if os.path.exists(p):
                result["mimo_exe"] = True
                result["exe_path"] = p
                break
        result["online"] = result["mimo_exe"]
        result["time_ms"] = int((time.time() - start) * 1000)
        if not result["online"]:
            result["error"] = "mimo.exe 不存在"
        return result

    def _check_deepseek_api(self) -> Dict:
        if not requests:
            return {"online": False, "time_ms": 0, "error": "requests 未安装"}
        start = time.time()
        try:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if not api_key:
                return {"online": False, "time_ms": 0, "error": "未配置 API Key"}
            resp = requests.get("https://api.deepseek.com/v1/models", timeout=3,
                                headers={"Authorization": f"Bearer {api_key}"})
            elapsed = int((time.time() - start) * 1000)
            return {"online": resp.status_code == 200, "time_ms": elapsed}
        except requests.exceptions.ConnectionError:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": "网络不通"}
        except requests.exceptions.Timeout:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": "超时"}
        except Exception as e:
            return {"online": False, "time_ms": int((time.time() - start) * 1000), "error": str(e)[:60]}

    def _do_check(self, report=True) -> Dict:
        """执行一次完整检查（用于 /diagnose /monitor）"""
        start = time.time()
        engine_info = self._detect_engine_info()
        engine_id = engine_info["engine_id"]
        checks = ENGINE_CHECKS.get(engine_id, ["mimo", "ollama", "sse", "process_bridge"])

        results = {}
        for k in checks:
            check_func = getattr(self, f'_check_{k}', None)
            if check_func:
                results[k] = check_func()

        all_ok = all(r.get("online", False) for r in results.values())
        issues = []
        for k, r in results.items():
            if not r.get("online", False):
                labels = {
                    "mimo": "MIMO", "ollama": "Ollama", "sse": "SSE",
                    "process_bridge": "Bridge", "deepseek_api": "API"
                }
                issues.append(f"{labels.get(k, k)}: {r.get('error', '离线')}")

        result = {
            "timestamp": time.strftime("%H:%M:%S"),
            "engine_info": engine_info,
            "active_engine": engine_id,
            "checks": results,
            "all_healthy": all_ok,
            "issues": issues,
            "total_ms": int((time.time() - start) * 1000),
        }
        self._last_status = result
        return result

    # ==================== 诊断报告 ====================

    def get_diagnostic_report(self) -> str:
        """生成完整诊断报告（/diagnose 命令）"""
        result = self._do_check(report=False)
        engine_info = result["engine_info"]
        results = result["checks"]

        GREEN = "Lemon.ACCENT_GREEN"
        RED = "Lemon.ACCENT_RED"
        YELLOW = "Lemon.ACCENT_ORANGE"
        ORANGE = "Lemon.ACCENT_ORANGE"
        CYAN = "Lemon.ACCENT_BLUE"
        GRAY = "#888"
        WHITE = "Lemon.PLACEHOLDER"

        def ok_badge(ok):
            return f'<span style="color:{GREEN};">&#10003; 在线</span>' if ok else f'<span style="color:{RED};">&#10007; 离线</span>'

        def time_badge(ms):
            c = GREEN if ms < 100 else YELLOW if ms < 500 else RED
            return f'<span style="color:{c};">{ms}ms</span>'

        lines = []

        # 标题
        lines.append(
            f'<div style="font-family:Consolas,monospace;font-size:12px;margin:6px 0 0 0;padding:6px 10px;'
            f'background:linear-gradient(90deg,#0d1b2a,Lemon.DARK_MID_5);border:1px solid {ORANGE};border-radius:4px 4px 0 0;">'
            f'<span style="color:{ORANGE};font-weight:bold;">&#128269; Lemon Code 诊断报告</span>'
            f'<span style="color:{GRAY};">  |  {result["timestamp"]}</span>'
            f'</div>'
        )

        # 引擎信息
        lines.append(
            f'<div style="font-family:Consolas,monospace;font-size:11px;margin:0;padding:4px 10px;'
            f'background:Lemon.DARK_MID_5;border-left:1px solid {ORANGE};border-right:1px solid {ORANGE};line-height:1.8;">'
            f'<span style="color:{CYAN};">Lemon Code</span>'
            f'<span style="color:{GRAY};"> → </span>'
            f'<span style="color:{ORANGE};">{engine_info["display_name"]}</span>'
            f'<span style="color:{GRAY};"> ({engine_info["connection_type"]})</span>'
            f'</div>'
        )

        labels = {
            "mimo": "MIMO 服务", "ollama": "Ollama 服务", "sse": "SSE 事件流",
            "process_bridge": "Process Bridge", "deepseek_api": "DeepSeek API"
        }

        for k, r in results.items():
            lines.append(
                f'<div style="font-family:Consolas,monospace;font-size:11px;margin:0;padding:3px 10px;'
                f'background:Lemon.DARK_MID_5;border-left:1px solid {ORANGE};border-right:1px solid {ORANGE};">'
                f'<span style="color:{WHITE};">{labels.get(k, k)}: </span>'
                f'{ok_badge(r["online"])} '
                f'<span style="color:{GRAY};">响应: </span>{time_badge(r["time_ms"])}'
                f'</div>'
            )
            if not r["online"]:
                err = r.get("error", "未知")
                lines.append(
                    f'<div style="font-family:Consolas,monospace;font-size:10px;margin:0;padding:2px 10px 2px 24px;'
                    f'background:Lemon.ERROR_BG_DARK;border-left:1px solid {ORANGE};border-right:1px solid {ORANGE};">'
                    f'<span style="color:{RED};">错误: {err}</span>'
                    f'</div>'
                )

        # 底部
        lines.append(
            f'<div style="font-family:Consolas,monospace;font-size:11px;margin:0 0 6px 0;padding:4px 10px;'
            f'background:Lemon.DARK_MID_5;border:1px solid {ORANGE};border-radius:0 0 4px 4px;">'
            f'<span style="color:{GRAY};">总耗时: </span>{time_badge(result["total_ms"])}'
            f'<span style="color:{GRAY};"> | 状态: </span>{ok_badge(result["all_healthy"])}'
            f'</div>'
        )

        for line in lines:
            self._emit(line)

        return "\n".join([
            f"Lemon Code 诊断 [{result['timestamp']}]",
            f"引擎: {engine_info['display_name']}",
        ] + [f"{labels.get(k, k)}: {'在线' if r['online'] else '离线'} ({r['time_ms']}ms)" for k, r in results.items()])

    def get_status_badge_html(self) -> str:
        """简洁状态徽章"""
        result = self._last_status or self._do_check(report=False)
        engine_id = result.get("active_engine", "?")
        checks = result.get("checks", {})
        G = "Lemon.ACCENT_GREEN"
        R = "Lemon.ACCENT_RED"
        parts = [f'<span style="color:Lemon.ACCENT_ORANGE;">{engine_id}</span>']
        for k, r in checks.items():
            c = G if r.get("online") else R
            parts.append(f'<span style="color:{c};">{k}:{r["time_ms"]}ms</span>')
        return " ".join(parts)