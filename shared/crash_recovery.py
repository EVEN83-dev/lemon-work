# -*- coding: utf-8 -*-
"""
崩溃恢复系统
============
CrashRecovery:
  - 恢复点注册/恢复（持久化到 ~/.mimo_agent/recovery.json）
  - 全局异常处理器（记录到 ~/.mimo_agent/crash_log/）
  - 看门狗线程（检测主线程心跳超时）
  - 自动重启机制（watchdog 子进程）

架构：
┌──────────────────────────────────────────────┐
│              CrashRecovery                     │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │ recovery.json │  │ crash_log/           │  │
│  │ - 恢复点列表   │  │ - 2026-07-12_15h.log │  │
│  │ - 最后会话ID   │  │ - 异常堆栈           │  │
│  │ - 最后消息     │  │ - 系统状态快照       │  │
│  └──────────────┘  └──────────────────────┘  │
│  ┌──────────────────────────────────────┐    │
│  │ Watchdog Thread                       │    │
│  │ - 心跳检测（30秒超时）                  │    │
│  │ - 主线程卡死时记录并通知                │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
"""

import os
import sys
import json
import time
import threading
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Any


class CrashRecovery:
    """崩溃恢复管理器 — 单例"""

    _instance: Optional["CrashRecovery"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "CrashRecovery":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        # 目录结构
        home = os.path.expanduser("~")
        self._data_dir = os.path.join(home, ".mimo_agent")
        self._crash_log_dir = os.path.join(self._data_dir, "crash_log")
        self._recovery_file = os.path.join(self._data_dir, "recovery.json")
        os.makedirs(self._data_dir, exist_ok=True)
        os.makedirs(self._crash_log_dir, exist_ok=True)

        # 恢复点列表
        self._recovery_points: List[Dict] = []
        # 心跳时间戳
        self._heartbeat: float = time.time()
        self._heartbeat_lock = threading.Lock()
        # 看门狗线程
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_running = False
        # 主线程引用
        self._main_thread: Optional[threading.Thread] = None

        # 加载已有恢复点
        self._load_recovery_file()

    # ============================================================
    # 恢复点管理
    # ============================================================

    def register_recovery_point(self, name: str, state: dict) -> int:
        """注册恢复点

        Args:
            name: 恢复点名称（如 "before_write_file"）
            state: 状态数据（如 {"file": "xxx.py", "session_id": "xxx"}）

        Returns:
            恢复点索引
        """
        point = {
            "name": name,
            "state": state,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "epoch": time.time(),
        }
        self._recovery_points.append(point)
        # 最多保留 50 个恢复点
        if len(self._recovery_points) > 50:
            self._recovery_points = self._recovery_points[-50:]
        self._save_recovery_file()
        return len(self._recovery_points) - 1

    def recover(self) -> Optional[Dict]:
        """从最近恢复点恢复状态

        Returns:
            恢复点数据，如果没有返回 None
        """
        if not self._recovery_points:
            return None
        point = self._recovery_points[-1]
        print(f"[CrashRecovery] 恢复到: {point['name']} ({point['timestamp']})", flush=True)
        return point

    def list_recovery_points(self) -> List[Dict]:
        """列出所有恢复点"""
        return list(self._recovery_points)

    def clear_recovery_points(self):
        """清除所有恢复点"""
        self._recovery_points.clear()
        self._save_recovery_file()

    def has_crash_record(self) -> bool:
        """是否有崩溃记录（上次异常退出）"""
        return (os.path.exists(self._recovery_file)
                and len(self._recovery_points) > 0
                and self._recovery_points[-1].get("state", {}).get("_crashed") is True)

    def mark_crashed(self):
        """标记当前为崩溃状态"""
        if self._recovery_points:
            self._recovery_points[-1]["state"]["_crashed"] = True
            self._save_recovery_file()

    def clear_crash_flag(self):
        """清除崩溃标记"""
        for p in self._recovery_points:
            p.get("state", {}).pop("_crashed", None)
        self._save_recovery_file()

    # ============================================================
    # 持久化
    # ============================================================

    def _save_recovery_file(self):
        """保存恢复点到文件"""
        try:
            data = {
                "recovery_points": self._recovery_points,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "pid": os.getpid(),
            }
            with open(self._recovery_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[CrashRecovery] 保存恢复文件失败: {e}", flush=True)

    def _load_recovery_file(self):
        """从文件加载恢复点"""
        try:
            if os.path.exists(self._recovery_file):
                with open(self._recovery_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._recovery_points = data.get("recovery_points", [])
                print(f"[CrashRecovery] 加载了 {len(self._recovery_points)} 个恢复点", flush=True)
        except Exception as e:
            print(f"[CrashRecovery] 加载恢复文件失败: {e}", flush=True)

    # ============================================================
    # 崩溃日志
    # ============================================================

    def log_crash(self, exc_type, exc_value, exc_tb):
        """记录崩溃日志

        Args:
            exc_type: 异常类型
            exc_value: 异常值
            exc_tb: 异常堆栈
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(self._crash_log_dir, f"crash_{timestamp}.log")

        try:
            # 获取堆栈信息
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
            tb_text = ''.join(tb_lines)

            # 收集系统状态
            sys_info = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "python": sys.version,
                "platform": sys.platform,
                "pid": os.getpid(),
                "cwd": os.getcwd(),
                "recovery_points": len(self._recovery_points),
                "last_recovery_point": self._recovery_points[-1] if self._recovery_points else None,
            }

            with open(log_file, 'w', encoding='utf-8') as f:
                f.write("=" * 60 + "\n")
                f.write(f"MIMO Agent 崩溃日志\n")
                f.write(f"时间: {sys_info['timestamp']}\n")
                f.write(f"PID: {sys_info['pid']}\n")
                f.write("=" * 60 + "\n\n")
                f.write("--- 系统信息 ---\n")
                f.write(json.dumps(sys_info, ensure_ascii=False, indent=2))
                f.write("\n\n--- 异常堆栈 ---\n")
                f.write(tb_text)
                f.write("\n\n--- 活跃线程 ---\n")
                for t in threading.enumerate():
                    f.write(f"  {t.name} (alive={t.is_alive()}, daemon={t.daemon})\n")

            print(f"[CrashRecovery] 崩溃日志已保存: {log_file}", flush=True)

            # 标记崩溃
            self.mark_crashed()

        except Exception as e:
            print(f"[CrashRecovery] 记录崩溃日志失败: {e}", flush=True)

    def list_crash_logs(self) -> List[Dict]:
        """列出崩溃日志"""
        logs = []
        try:
            for fn in sorted(os.listdir(self._crash_log_dir), reverse=True):
                if fn.startswith("crash_") and fn.endswith(".log"):
                    fp = os.path.join(self._crash_log_dir, fn)
                    stat = os.stat(fp)
                    logs.append({
                        "file": fn,
                        "path": fp,
                        "size": stat.st_size,
                        "time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    })
        except Exception:
            pass
        return logs

    # ============================================================
    # 全局异常处理器
    # ============================================================

    def install_excepthook(self):
        """安装全局异常处理器"""
        # ★ 376-0: 输出流兜底 —— GBK 控制台下打印中文/特殊字符不再触发二次崩溃
        for _stream in (sys.stdout, sys.stderr):
            try:
                if _stream and hasattr(_stream, "reconfigure"):
                    _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

        original_hook = sys.excepthook

        def _hook(exc_type, exc_value, exc_tb):
            # ★ 376-0: UnicodeDecodeError 非致命化 —— 解码修复(defense-in-depth)之外的
            #   最后防线：记录为 DECODE 警告并吞掉，避免应用因子进程/文件解码直接崩溃
            if exc_type is UnicodeDecodeError:
                try:
                    print(f"[CrashRecovery] 捕获解码异常(已吞掉，不影响运行): {exc_value}", flush=True)
                except Exception:
                    pass
                return
            # 记录崩溃
            self.log_crash(exc_type, exc_value, exc_tb)
            # 调用原始 hook
            if original_hook:
                original_hook(exc_type, exc_value, exc_tb)

        sys.excepthook = _hook
        print("[CrashRecovery] 全局异常处理器已安装", flush=True)

    def install_threading_excepthook(self):
        """安装线程异常处理器（Python 3.8+）"""
        if not hasattr(threading, 'excepthook'):
            return

        def _hook(args):
            # ★ 376-0: 线程内解码异常静默吞掉（线程异常本不致死进程，
            #   只需防止 crash 日志被解码错误刷屏）
            if args.exc_type is UnicodeDecodeError:
                try:
                    print(f"[CrashRecovery] 线程解码异常(已吞掉): {args.exc_value}", flush=True)
                except Exception:
                    pass
                return
            self.log_crash(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = _hook
        print("[CrashRecovery] 线程异常处理器已安装", flush=True)

    # ============================================================
    # 心跳 / 看门狗
    # ============================================================

    def heartbeat(self):
        """更新心跳时间戳（主线程定期调用）"""
        with self._heartbeat_lock:
            self._heartbeat = time.time()

    def get_last_heartbeat(self) -> float:
        """获取上次心跳时间"""
        with self._heartbeat_lock:
            return self._heartbeat

    def start_watchdog(self, main_thread: Optional[threading.Thread] = None,
                       timeout: float = 30.0, on_stuck: Optional[callable] = None):
        """启动看门狗线程

        Args:
            main_thread: 主线程引用
            timeout: 心跳超时秒数
            on_stuck: 主线程卡死时的回调
        """
        if self._watchdog_running:
            return

        self._main_thread = main_thread or threading.main_thread()
        self._watchdog_running = True

        def _watch():
            while self._watchdog_running:
                time.sleep(5)  # 每5秒检查一次
                try:
                    last = self.get_last_heartbeat()
                    elapsed = time.time() - last
                    if elapsed > timeout:
                        print(f"[Watchdog] 主线程心跳超时 ({elapsed:.1f}s)，可能卡死", flush=True)
                        if on_stuck:
                            on_stuck(elapsed)
                        # 记录但不强制退出（避免数据丢失）
                        self.log_crash(
                            RuntimeError,
                            RuntimeError(f"Main thread stuck for {elapsed:.1f}s"),
                            None,
                        )
                        # 重置心跳避免重复触发
                        self.heartbeat()
                except Exception as e:
                    print(f"[Watchdog] 检查异常: {e}", flush=True)

        self._watchdog_thread = threading.Thread(target=_watch, daemon=True, name="watchdog")
        self._watchdog_thread.start()
        print(f"[CrashRecovery] 看门狗已启动（超时={timeout}s）", flush=True)

    def stop_watchdog(self):
        """停止看门狗"""
        self._watchdog_running = False
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=3)

    # ============================================================
    # 自动重启
    # ============================================================

    @staticmethod
    def restart_process(delay: float = 1.0):
        """重启当前进程

        Args:
            delay: 重启前延迟（秒）
        """
        print(f"[CrashRecovery] {delay}秒后重启进程...", flush=True)
        time.sleep(delay)
        # 使用 os.execv 替换当前进程
        python = sys.executable
        os.execv(python, [python] + sys.argv)

    @staticmethod
    def spawn_watchdog_process():
        """启动看门狗子进程（在主进程崩溃时自动重启）

        在 main.py 启动时调用：
            if os.environ.get('_MIMO_WATCHDOG') != '1':
                CrashRecovery.spawn_watchdog_process()
        """
        import subprocess

        env = os.environ.copy()
        env['_MIMO_WATCHDOG'] = '1'

        # 看门狗脚本
        watchdog_code = f'''
import subprocess, sys, os, time

PYTHON = {repr(sys.executable)}
ARGV = {repr(sys.argv)}
ENV = {repr(dict(env))}
MAX_RESTARTS = 5
RESTART_WINDOW = 300  # 5分钟内最多重启5次
restarts = []

while True:
    print(f"[Watchdog] 启动主进程: {{ARGV}}", flush=True)
    proc = subprocess.Popen([PYTHON] + ARGV, env=ENV)
    proc.wait()
    exit_code = proc.returncode
    now = time.time()
    restarts.append(now)
    # 清理5分钟前的记录
    restarts = [t for t in restarts if now - t < RESTART_WINDOW]
    if len(restarts) >= MAX_RESTARTS:
        print(f"[Watchdog] 重启次数过多 ({{len(restarts)}}次/5分钟)，停止重启", flush=True)
        break
    if exit_code == 0:
        print("[Watchdog] 主进程正常退出", flush=True)
        break
    print(f"[Watchdog] 主进程异常退出 (code={{exit_code}})，3秒后重启...", flush=True)
    time.sleep(3)
'''

        subprocess.Popen(
            [sys.executable, '-c', watchdog_code],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0,
        )
