# -*- coding: utf-8 -*-
"""
LagRecorder — 程序自带卡顿黑匣子（第341章）
=============================================
目标：不需要外部脚本，程序自己记录运行性能数据到文件，供事后定位。

三个组件（全部 fail-safe，任何异常静默降级）：
1. 启动剖析器  — 前 60 秒每秒用 py-spy 抓一次主线程栈（nonblocking，
   不冻结程序），写 data/perf/startup_stacks.txt → 精确定位"打开软件
   缓冲 19 秒"每一段耗时在哪个函数。
2. 冻结检测器  — 主线程 QTimer(100ms) 自测；>500ms 记入
   data/perf/lag_log.csv（时间戳/冻结时长）。
3. 冻结抓栈器  — 检测到 >1.5s 冻结后，立即连续 py-spy 抓 3 次栈写
   data/perf/freeze_stacks.txt（冻结刚结束时常能抓到相关代码帧）。

全部输出为文件，零控制台打印（控制台 print 本身是负担）。
"""
import os
import re
import subprocess
import threading
import time

_OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "perf",
)

_PYSPY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".venv", "Scripts", "py-spy.exe",
)
if not os.path.exists(_PYSPY):
    _PYSPY = "py-spy"

_MAX_LINES = 4000          # 单文件上限（防膨胀）
_FREEZE_CAP = 40           # 冻结抓栈总次数上限


def _extract_main_thread(txt: str) -> str:
    """提取 py-spy dump 输出的 MainThread 段"""
    lines = txt.splitlines()
    out, in_main = [], False
    for ln in lines:
        if '"MainThread"' in ln:
            in_main = True
            out.append(ln.strip())
            continue
        if in_main:
            if re.match(r"^\s*Thread\s+\d+", ln):
                break
            if ln.strip():
                out.append(ln.strip())
    return "\n".join(out[:15])  # 最内 15 帧


def _pyspy_dump(pid: int) -> str:
    """执行一次 py-spy dump，返回主线程段文本（失败返回空串）"""
    try:
        r = subprocess.run(
            [_PYSPY, "dump", "--pid", str(pid), "--nonblocking"],
            capture_output=True, text=True, timeout=8,
            encoding="utf-8", errors="replace",
        )
        if r.returncode == 0:
            return _extract_main_frames(r.stdout or "")
    except Exception:
        pass
    return ""


def _extract_main_frames(txt: str) -> str:
    return _extract_main_thread(txt)


class LagRecorder:
    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = LagRecorder()
        return cls._instance

    def __init__(self):
        self._pid = os.getpid()
        self._enabled = os.path.exists(
            _PYSPY if _PYSPY.endswith(".exe") else _PYSPY
        ) or _PYSPY.endswith(".exe")  # exe 存在才启用抓栈；检测器始终启用
        self._start_t = time.time()
        self._last_ts = [0.0]
        self._freeze_count = [0]
        self._dump_total = [0]
        self._csv_lock = threading.Lock()
        try:
            os.makedirs(_OUT_DIR, exist_ok=True)
        except Exception:
            pass

    # ---------- 对外 ----------
    def start(self, timer_cls=None, parent=None):
        """启动冻结检测器（QTimer 由调用方传入避免循环导入）+ 启动剖析线程"""
        # 1) 启动剖析：前 60 秒每秒 py-spy
        if self._enabled:
            threading.Thread(target=self._startup_profiler, daemon=True,
                             name="lag-profiler").start()
        # 2) 冻结检测 QTimer
        try:
            from PyQt5.QtCore import QTimer
            self._tk = QTimer(parent)
            self._tk.timeout.connect(self._tick)
            self._tk.start(100)
        except Exception:
            pass
        self._append_file("lag_log.csv",
                          f"# session start {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # ---------- 冻结检测 ----------
    def _tick(self):
        now = time.time()
        last = self._last_ts[0]
        self._last_ts[0] = now
        if last <= 0:
            return
        gap = now - last
        if gap > 0.5:
            self._freeze_count[0] += 1
            self._append_file(
                "lag_log.csv",
                f"{time.strftime('%H:%M:%S')},{gap*1000:.0f}\n")
            # >1.5s 的冻结触发事后抓栈（限流）
            if gap > 1.5 and self._enabled and \
                    self._dump_total[0] < _FREEZE_CAP and \
                    self._freeze_count[0] <= 50:
                threading.Thread(
                    target=self._freeze_capture,
                    args=(gap,),
                    daemon=True,
                ).start()

    def _freeze_capture(self, gap_s: float):
        """冻结刚结束后连抓 3 次栈（间隔 0.4s）"""
        for i in range(3):
            stack = _pyspy_dump(self._pid)
            if stack:
                self._dump_total[0] += 1
                self._append_file(
                    "freeze_stacks.txt",
                    f"\n===== 冻结 {gap_s*1000:.0f}ms 后 {i*0.4:.1f}s "
                    f"@ {time.strftime('%H:%M:%S')} =====\n{stack}\n")
            time.sleep(0.4)

    # ---------- 启动剖析 ----------
    def _startup_profiler(self):
        """前 60 秒每秒 py-spy 主线程栈 → startup_stacks.txt"""
        deadline = self._start_t + 60
        i = 0
        while time.time() < deadline:
            stack = _pyspy_dump(self._pid)
            if stack:
                self._append_file(
                    "startup_stacks.txt",
                    f"\n----- T+{time.time()-self._start_t:5.1f}s #{i} -----\n{stack}\n")
            i += 1
            time.sleep(1.0)
        self._append_file("startup_stacks.txt",
                          f"\n# startup profiling done "
                          f"{time.strftime('%H:%M:%S')}\n")

    # ---------- 文件写入 ----------
    def _append_file(self, name: str, text: str):
        try:
            path = os.path.join(_OUT_DIR, name)
            # 膨胀保护：超上限时轮转为 .old
            if os.path.exists(path):
                try:
                    if os.path.getsize(path) > 512 * 1024:
                        os.replace(path, path + ".old")
                except Exception:
                    pass
            with self._csv_lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(text)
        except Exception:
            pass


def get_lag_recorder() -> LagRecorder:
    return LagRecorder.get()
