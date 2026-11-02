# -*- coding: utf-8 -*-
"""
shared/file_watcher.py — v6 文件事件监听

架构决策（二选一论证）:
  选择: 纯轮询（不依赖 QFileSystemWatcher）
  原因:
    - bridge_server.py 运行时无 Qt 事件循环（Pure Sanic + asyncio）
    - shared/ 层应可被任意运行时引用（bridge / lemon_agent CLI / 测试）
    - 轮询实现无外部依赖 (仅 os + threading)
  代价: 轮询间隔 1s 无法做到真正的 OS 级实时，通过去抖 + 灵活间隔补偿

功能:
  - watch(path, patterns, on_event) / unwatch(path)
  - 去抖 (500ms 内同文件多次变更合并)
  - 事件注入统一总线 type=EventType.FILE_CHANGED (file.changed)
  - 提供 file_watch / file_unwatch 技能经 SkillsRegistry.register() 运行时注册
  - 旧 30s 轮询热加载保留不动，日志"过时技术条目"预告收敛计划
"""
import os
import time
import threading
import logging
import fnmatch
from typing import Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _WatchEntry:
    path: str
    patterns: List[str]
    on_event: Callable
    last_mtime: float = 0
    last_size: int = 0
    last_debounce_ts: float = 0
    debounce_ms: int = 500
    is_dir: bool = False
    _file_states: Dict[str, tuple] = field(default_factory=dict)  # relpath -> (mtime, size)


class FileWatcher:
    """轮询式文件变更监听器。

    线程安全，支持 watch / unwatch / start / stop。
    检测到变更后调用注册回调，默认行为是注入统一事件总线。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, poll_interval: float = 1.0):
        if self._initialized:
            return
        self._initialized = True
        self._watches: Dict[str, _WatchEntry] = {}
        self._watches_lock = threading.RLock()
        self._poll_interval = poll_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stats = {"events_detected": 0, "events_debounced": 0, "events_sent": 0, "errors": 0}
        self._stats_lock = threading.Lock()

    # ----------------------------------------------------------
    # lifecycle
    # ----------------------------------------------------------

    def start(self) -> dict:
        """启动后台轮询线程。失败返回 success:false + error。"""
        try:
            if self._running:
                return {"success": True, "message": "already_running"}
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="file_watcher_poll")
            self._thread.start()
            self._running = True
            logger.info("[FileWatcher] started")
            return {"success": True}
        except Exception as e:
            logger.error(f"[FileWatcher] start failed: {e}")
            return {"success": False, "error": str(e)}

    def stop(self) -> dict:
        try:
            if not self._running:
                return {"success": True, "message": "not_running"}
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5)
            self._running = False
            logger.info("[FileWatcher] stopped")
            return {"success": True}
        except Exception as e:
            logger.error(f"[FileWatcher] stop failed: {e}")
            return {"success": False, "error": str(e)}

    # ----------------------------------------------------------
    # watch / unwatch
    # ----------------------------------------------------------

    def watch(self, path: str, patterns: List[str], on_event: Callable,
             debounce_ms: int = 500) -> dict:
        """注册一个监听路径。

        Args:
            path: 文件或目录路径
            patterns: glob 模式列表 (如 ["*.py", "*.md"])
            on_event: 变更回调 fn(event_dict)
            debounce_ms: 去抖窗口（毫秒）
        """
        try:
            if not os.path.exists(path):
                return {"success": False, "error": f"path not found: {path}"}
            is_dir = os.path.isdir(path)
            entry = _WatchEntry(
                path=os.path.abspath(path),
                patterns=patterns or ["*"],
                on_event=on_event,
                debounce_ms=debounce_ms,
                is_dir=is_dir,
            )
            if is_dir:
                entry._file_states = self._scan_dir(entry.path, entry.patterns)
            else:
                st = os.stat(entry.path)
                entry.last_mtime = st.st_mtime
                entry.last_size = st.st_size
                entry._file_states["."] = (st.st_mtime, st.st_size)

            with self._watches_lock:
                self._watches[entry.path] = entry
            logger.info(f"[FileWatcher] watch: {path} (dir={is_dir}, patterns={patterns})")
            return {"success": True, "watched": entry.path}
        except Exception as e:
            logger.error(f"[FileWatcher] watch failed: {e}")
            return {"success": False, "error": str(e)}

    def unwatch(self, path: str) -> dict:
        try:
            with self._watches_lock:
                p = os.path.abspath(path)
                if p in self._watches:
                    del self._watches[p]
                    return {"success": True, "unwatched": p}
                return {"success": False, "error": f"not watching: {p}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ----------------------------------------------------------
    # polling
    # ----------------------------------------------------------

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                self._check_all()
            except Exception as e:
                logger.error(f"[FileWatcher] poll loop error: {e}")
                with self._stats_lock:
                    self._stats["errors"] += 1
            self._stop_event.wait(self._poll_interval)

    def _check_all(self):
        with self._watches_lock:
            entries = list(self._watches.values())
        now = time.time()
        for entry in entries:
            changes = self._check_entry(entry, now)
            for change in changes:
                # 去抖
                with self._stats_lock:
                    self._stats["events_detected"] += 1
                rel_path = change.get("path", "")
                last = entry._file_states.get(rel_path, (0, 0))
                last_debounce = entry.last_debounce_ts
                if now - last_debounce < entry.debounce_ms / 1000.0:
                    continue  # 去抖中，跳过
                with self._stats_lock:
                    self._stats["events_debounced"] += 1
                entry.last_debounce_ts = now
                try:
                    entry.on_event(change)
                    with self._stats_lock:
                        self._stats["events_sent"] += 1
                except Exception as e:
                    logger.warning(f"[FileWatcher] callback error: {e}")
                    with self._stats_lock:
                        self._stats["errors"] += 1

    def _check_entry(self, entry: _WatchEntry, now: float) -> List[dict]:
        changes = []
        if entry.is_dir:
            current = self._scan_dir(entry.path, entry.patterns)
            # 新增或修改
            for rel, (mtime, size) in current.items():
                prev = entry._file_states.get(rel)
                if prev is None:
                    changes.append({"path": rel, "type": "created", "mtime": mtime, "size": size,
                                    "watched_dir": entry.path})
                elif prev[0] != mtime or prev[1] != size:
                    changes.append({"path": rel, "type": "modified", "mtime": mtime, "size": size,
                                    "watched_dir": entry.path})
            # 删除
            for rel in entry._file_states:
                if rel not in current:
                    changes.append({"path": rel, "type": "deleted", "watched_dir": entry.path})
            entry._file_states = current
        else:
            if not os.path.exists(entry.path):
                return [{"path": ".", "type": "deleted", "watched_dir": entry.path}]
            st = os.stat(entry.path)
            if st.st_mtime != entry.last_mtime or st.st_size != entry.last_size:
                changes.append({"path": ".", "type": "modified", "mtime": st.st_mtime,
                                "size": st.st_size, "watched_dir": os.path.dirname(entry.path)})
                entry.last_mtime = st.st_mtime
                entry.last_size = st.st_size
                entry._file_states["."] = (st.st_mtime, st.st_size)
        return changes

    def _scan_dir(self, dir_path: str, patterns: List[str]) -> Dict[str, tuple]:
        """扫描目录返回 {relpath: (mtime, size)}"""
        states = {}
        if not os.path.isdir(dir_path):
            return states
        for root, dirs, files in os.walk(dir_path):
            for fn in files:
                matched = any(fnmatch.fnmatch(fn, p) for p in patterns)
                if matched:
                    fp = os.path.join(root, fn)
                    try:
                        st = os.stat(fp)
                        rel = os.path.relpath(fp, dir_path)
                        states[rel] = (st.st_mtime, st.st_size)
                    except OSError:
                        pass
        return states

    # ----------------------------------------------------------
    # stats
    # ----------------------------------------------------------

    def get_stats(self) -> dict:
        with self._stats_lock:
            return dict(self._stats)

    def get_watched_paths(self) -> List[str]:
        with self._watches_lock:
            return list(self._watches.keys())


# ============================================================
# 默认实例 + 注册到统一总线
# ============================================================

def get_file_watcher(**kwargs) -> FileWatcher:
    return FileWatcher(**kwargs)


def _default_on_file_change(event: dict):
    """默认文件变更回调：注入统一事件总线"""
    try:
        from shared.event_bus import Event, EventType, get_event_bus
        bus = get_event_bus()
        ev = Event(
            type=EventType.FILE_CHANGED,
            source="file_watcher",
            payload=event,
            session_id="",
        )
        bus.publish(ev)
    except Exception as e:
        logger.error(f"[FileWatcher] default callback failed: {e}")


# ============================================================
# 技能注册入口（运行时注册，不修改冻结区）
# ============================================================

def register_file_watcher_skills(skills_registry):
    """通过 SkillsRegistry.register() 运行时注册 file_watch/file_unwatch 技能。

    调用方: standard_mode/core/builtin_skills.py 或其他注册点
    本函数不直接修改冻结区文件，仅在注册点被调用时注入。
    """
    try:

        def file_watch_skill(args: dict) -> dict:
            """注册文件监听。args: {path, patterns, debounce_ms?}"""
            try:
                path = args.get("path", "")
                patterns = args.get("patterns", ["*"])
                debounce = args.get("debounce_ms", 500)
                watcher = get_file_watcher()
                r = watcher.watch(path, patterns, _default_on_file_change, debounce_ms=debounce)
                if r.get("success"):
                    return {"success": True, "watched": r.get("watched"),
                            "patterns": patterns, "debounce_ms": debounce}
                return r
            except Exception as e:
                return {"success": False, "error": str(e)}

        def file_unwatch_skill(args: dict) -> dict:
            try:
                path = args.get("path", "")
                watcher = get_file_watcher()
                return watcher.unwatch(path)
            except Exception as e:
                return {"success": False, "error": str(e)}

        skills_registry.register("file_watch", file_watch_skill,
                                  description="监听目录文件变更",
                                  category="file")
        skills_registry.register("file_unwatch", file_unwatch_skill,
                                  description="取消监听目录",
                                  category="file")
        return {"success": True, "registered": ["file_watch", "file_unwatch"]}
    except Exception as e:
        logger.error(f"[FileWatcher] skill registration failed: {e}")
        return {"success": False, "error": str(e)}


# 过时技术条目（预告但不删除）:
#   - 旧 30s 轮询热加载: shared/hot_reload.py / agent_container.py 中的轮询检测
#   - 替代方案: 使用本模块 FileWatcher + get_file_watcher() 注册 file_watch 技能
#   - 收敛计划: 当所有热加载调用方迁移到本模块后，旧轮询代码移除
#   - 本窗口未删除任何旧代码（遵守铁律第6条）
