# -*- coding: utf-8 -*-
"""shared/scheduler.py — V6-P1 定时调度器引擎（第359章）

对标 OpenClaw Heartbeat/Cron 与 OpenAI Codex 任务调度，为 Lemon Agent
补上 always-on 的时间维度：到点执行已注册技能（SkillsRegistry.execute）
或经 Commander 派发自然语言指令。

设计选型（线程模型，第359章日志论证）：
  单线程守护调度循环 + threading.Event 停止开关。理由：
  1) 验收脚本必须无 QApplication 可独立运行，QTimer 依赖 Qt 事件循环，
     thread 模型让引擎在 headless 环境同样可用；
  2) 任务数级别为"个位数十"，1 秒粒度轮询的 CPU 开销可忽略，
     单循环天然串行化执行，杜绝每任务一线程的泄漏风险；
  3) Qt 耦合留给挂载点（main.py 用 QTimer.singleShot 延迟启动，风格对齐
     既有"分批延迟加载"），引擎本体保持零 Qt 依赖（Commander 仅惰性导入）。

可靠性约定（铁律4：假实现零容忍）：
  - 所有公开接口返回 dict 且必带 success 字段，失败带中文 error；
  - 触发表达式解析失败显式抛 ValueError（中文），禁止猜默认值；
  - 持久化 data/scheduler/jobs.json，tmp 文件 + os.replace 原子替换（D4 惯例）；
  - 执行日志 data/scheduler/runs/YYYY-MM-DD.log，中文八段字段。
"""
import io
import json
import os
import re
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA_DIR = os.path.join(_PROJECT_ROOT, "data", "scheduler")

_JOBS_FILE = "jobs.json"
# 单次执行重试退避上限（秒）：30s → 1m → 2m → … 封顶 30 分钟
_RETRY_BASE_SECONDS = 30
_RETRY_CAP_SECONDS = 1800
# Agent 忙碌时排队复检间隔（秒）
_QUEUE_RECHECK_SECONDS = 5
# 调度循环轮询间隔（秒）
_TICK_SECONDS = 1.0


# ────────────────────────── 触发表达式解析 ──────────────────────────
_INTERVAL_RE = re.compile(r"^(?:interval\s+|every\s+|@)?(\d+)\s*([smhd])$", re.IGNORECASE)
_DAILY_RE = re.compile(r"^(?:daily\s+|@)?([01]?\d|2[0-3]):([0-5]\d)$", re.IGNORECASE)


def _parse_datetime_once(text: str) -> datetime:
    """once 的绝对时间：ISO 8601 或 'YYYY-MM-DD HH:MM(:SS)'，失败抛 ValueError。"""
    raw = text.strip()
    iso = raw.replace("T", " ") if "T" in raw else raw
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(iso, fmt)
        except ValueError:
            continue
    try:  # ISO 8601 兜底（含时区/秒）
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    raise ValueError(
        f"无法解析一次性触发时间 '{raw}'：要求 ISO 8601 或 'YYYY-MM-DD HH:MM'，禁止猜测默认值")


def parse_trigger(expr: str) -> dict:
    """解析触发表达式 → {'type': interval|daily|once, ...}。

    支持三种写法（前缀可省略）：
      interval: "30s" / "10m" / "2h" / "1d"，可加前缀 "interval "/"every "
      daily:    "09:30"，可加前缀 "daily "
      once:     "2026-09-30 10:00" 或 ISO 8601，可加前缀 "once "
    解析失败抛 ValueError（中文错误），绝不返回默认值。
    """
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("触发表达式为空：需 interval（如 30s/10m/2h）、daily（如 09:30）或 once（绝对时间）")
    raw = expr.strip()

    m = _INTERVAL_RE.match(raw)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if n <= 0:
            raise ValueError(f"间隔必须为正整数，收到 '{raw}'")
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        secs = n * mult
        if secs < 5:
            raise ValueError(f"间隔最小 5s（收到 '{raw}'），防止空转风暴")
        return {"type": "interval", "seconds": secs}

    m = _DAILY_RE.match(raw)
    if m:
        return {"type": "daily", "hh": int(m.group(1)), "mm": int(m.group(2))}

    if raw.lower().startswith("once"):
        return {"type": "once", "dt": _parse_datetime_once(raw[4:])}

    # 无前缀：尝试当 once 绝对时间（含日期才算，纯 "HH:MM" 已被 daily 吃掉）
    if re.search(r"\d{4}-\d{2}-\d{2}", raw):
        return {"type": "once", "dt": _parse_datetime_once(raw)}

    raise ValueError(
        f"无法解析触发表达式 '{raw}'：合法格式为 interval（30s/10m/2h）、daily（09:30）、"
        f"once（2026-09-30 10:00 或 ISO 8601）")


def compute_next_run(parsed: dict, now: datetime):
    """按解析结果计算下一次执行时间（本地时间）。"""
    t = parsed["type"]
    if t == "interval":
        return now + timedelta(seconds=parsed["seconds"])
    if t == "daily":
        cand = now.replace(hour=parsed["hh"], minute=parsed["mm"], second=0, microsecond=0)
        if cand <= now:
            cand += timedelta(days=1)
        return cand
    # once
    return parsed["dt"]


def validate_action(action) -> dict:
    """校验 action：{'skill': 名称, 'args': {...}} 或 {'command': 指令, 'mode': auto|manual}。"""
    if not isinstance(action, dict):
        raise ValueError("action 必须为 dict：{'skill': 名称, 'args': {}} 或 {'command': 指令, 'mode': 'auto'|'manual'}")
    has_skill = bool(action.get("skill"))
    has_cmd = bool((action.get("command") or "").strip())
    if has_skill == has_cmd:  # 双有或双无都拒绝
        raise ValueError("action 需二选一：'skill'（已注册技能名 + args）或 'command'（自然语言指令经 Commander 派发）")
    if has_skill:
        return {"type": "skill", "skill": action["skill"], "args": dict(action.get("args") or {})}
    mode = (action.get("mode") or "auto").lower()
    if mode not in ("auto", "manual"):
        raise ValueError(f"command 审批模式只能为 auto/manual，收到 '{mode}'")
    return {"type": "command", "command": action["command"].strip(), "mode": mode}


class SchedulerEngine:
    """定时调度引擎单例。线程模型见模块 docstring。"""

    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls, data_dir: str = None) -> "SchedulerEngine":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = SchedulerEngine(data_dir=data_dir)
        return cls._instance

    def __init__(self, data_dir: str = None):
        # 单例唯一性由 instance() 在 _instance_lock 内保证（构造器绝不再抢同一把非重入锁，否则死锁）。
        # 测试显式重建走 _reset_for_test（同样在锁内清零后构造），不得直接 SchedulerEngine(data_dir=...)。
        self._lock = threading.RLock()
        self._data_dir = data_dir or DEFAULT_DATA_DIR
        self._runs_dir = os.path.join(self._data_dir, "runs")
        self._jobs = {}            # job_id -> job dict
        self._stop_event = threading.Event()
        self._thread = None
        self._commander = None     # 由 main.py 挂载（attach_commander）
        self._running_flag = False  # 当前是否有任务体正在执行（排队判定用）
        self._load_jobs()
        self.start()

    # ══════════════════════ 生命周期 ══════════════════════
    def start(self):
        """启动单线程调度循环；启动时做 once 任务错过补偿。"""
        if self._thread and self._thread.is_alive():
            return {"success": True, "note": "调度线程已在运行"}
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="lemon-scheduler", daemon=True)
        self._thread.start()
        self._compensate_misfires()
        return {"success": True}

    def stop(self) -> dict:
        """停止调度线程（jobs.json 已实时落盘，重启自动恢复）。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        return {"success": True, "stopped_at": datetime.now().isoformat(timespec="seconds")}

    @classmethod
    def _reset_for_test(cls, data_dir: str = None) -> "SchedulerEngine":
        """仅供验收脚本重建实例（持久化复检用），业务代码禁止调用。"""
        with cls._instance_lock:
            if cls._instance is not None:
                try:
                    cls._instance.stop()
                except Exception:
                    pass
            cls._instance = None
        return cls.instance(data_dir=data_dir)

    def attach_commander(self, commander) -> dict:
        """挂载 Commander（自然语言指令派发用；无 Commander 时 skill 动作不受影响）。"""
        if commander is None:
            return {"success": False, "error": "Commander 实例为空，拒绝挂载"}
        self._commander = commander
        return {"success": True}

    # ══════════════════════ 对外接口 ══════════════════════
    def create_job(self, trigger: str, action, name: str = None,
                   max_retry: int = 2, enabled: bool = True) -> dict:
        """创建任务并落盘。返回 {'success': bool, 'job': {...} | 'error': 中文}"""
        try:
            parsed = parse_trigger(trigger)
            act = validate_action(action)
        except ValueError as e:
            return {"success": False, "error": str(e)}
        now = datetime.now()
        job = {
            "job_id": f"job_{uuid.uuid4().hex[:10]}",
            "name": (name or f"未命名任务_{now.strftime('%m%d_%H%M%S')}"),
            "trigger": trigger.strip(),
            "trigger_parsed": parsed["type"],
            "action": act,
            "enabled": bool(enabled),
            "max_retry": max(0, int(max_retry)),
            "created_at": now.isoformat(timespec="seconds"),
            "last_run": None,
            "next_run": compute_next_run(parsed, now).isoformat(timespec="seconds"),
            "state": "idle",
            "retry_count": 0,
            "run_count": 0,
            "last_error": None,
        }
        with self._lock:
            self._jobs[job["job_id"]] = job
            self._save_jobs()
        return {"success": True, "job": dict(job)}

    def cancel_job(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return {"success": False, "error": f"任务不存在: {job_id}"}
            job["enabled"] = False
            job["state"] = "cancelled"
            job["next_run"] = None
            self._save_jobs()
        return {"success": True, "job_id": job_id, "state": "cancelled"}

    def list_jobs(self) -> dict:
        with self._lock:
            jobs = [dict(j) for j in self._jobs.values()]
        jobs.sort(key=lambda x: (x["next_run"] is None, x["next_run"] or ""))
        return {"success": True, "jobs": jobs, "count": len(jobs)}

    def run_now(self, job_id: str) -> dict:
        """立即手动触发一次（不改 next_run 计划，仅插入一次即时执行）。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return {"success": False, "error": f"任务不存在: {job_id}"}
            if self._running_flag:
                # 引擎忙：任务入等待队列（state=queued），由调度循环复检执行
                job["state"] = "queued"
                job["_run_now_pending"] = True
                self._save_jobs()
                return {"success": True, "queued": True, "job_id": job_id,
                        "note": "引擎正忙，已入等待队列（state=queued）"}
        ok, err, secs = self._execute_job(job_id, trigger_way="手动 run_now")
        return {"success": ok, "job_id": job_id, "elapsed_sec": round(secs, 3),
                **({"error": err} if not ok else {})}

    def get_job(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    # ══════════════════════ 调度循环 ══════════════════════
    def _loop(self):
        while not self._stop_event.wait(_TICK_SECONDS):
            try:
                self._tick()
            except Exception as e:  # 调度循环绝不因单次异常死亡
                self._append_run_log("system", "调度循环", "内部", "-",
                                     f"FAIL: {e}", 0.0, traceback.format_exc()[-500:], "-")

    def _tick(self):
        now = datetime.now()
        due_ids = []
        with self._lock:
            for job in self._jobs.values():
                if not job["enabled"]:
                    continue
                # run_now 排队复检
                if job.get("_run_now_pending") and not self._running_flag:
                    job.pop("_run_now_pending", None)
                    due_ids.append((job["job_id"], "手动 run_now(队列补偿)"))
                    continue
                nr = job.get("next_run")
                if not nr or job["state"] in ("running",):
                    continue
                try:
                    nr_dt = datetime.fromisoformat(nr)
                except ValueError:
                    continue
                if nr_dt <= now:
                    due_ids.append((job["job_id"], "定时触发"))
        for job_id, way in due_ids:
            if self._stop_event.is_set():
                break
            self._execute_job(job_id, trigger_way=way)

    # ══════════════════════ 执行链路 ══════════════════════
    def _execute_job(self, job_id: str, trigger_way: str) -> tuple:
        """执行单个任务。返回 (ok, error, elapsed)。失败按 max_retry 指数退避。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False, f"任务不存在: {job_id}", 0.0
            act = dict(job["action"])
            job_name = job["name"]
            # Agent/Commander 忙 → 入等待队列（state=queued），不占重试次数
            if act["type"] == "command" and self._commander_busy():
                job["state"] = "queued"
                job["_queued_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_jobs()
                return True, None, 0.0  # 排队不算失败，复检 tick 会再触发
            job["state"] = "running"
            self._running_flag = True

        t0 = time.time()
        ok, err, detail = False, None, ""
        try:
            if act["type"] == "skill":
                ok, err, detail = self._run_skill(act)
            else:
                ok, err, detail = self._run_command(act)
        except Exception as e:
            ok, err, detail = False, f"执行链路异常: {e}", traceback.format_exc()[-500:]
        elapsed = time.time() - t0

        with self._lock:
            self._running_flag = False
            job = self._jobs.get(job_id)
            if not job:
                return ok, err, elapsed
            job["last_run"] = datetime.now().isoformat(timespec="seconds")
            job["run_count"] += 1
            now = datetime.now()
            if ok:
                job["state"] = "idle"
                job["retry_count"] = 0
                job["last_error"] = None
                if not job.get("_run_now_pending"):
                    job["next_run"] = compute_next_run(
                        parse_trigger(job["trigger"]), now).isoformat(timespec="seconds")
            elif job["retry_count"] < job["max_retry"]:
                job["retry_count"] += 1
                backoff = min(_RETRY_BASE_SECONDS * (2 ** (job["retry_count"] - 1)), _RETRY_CAP_SECONDS)
                job["state"] = "retrying"
                job["last_error"] = err
                job["next_run"] = (now + timedelta(seconds=backoff)).isoformat(timespec="seconds")
            else:
                # 重试耗尽：once 任务停用；周期任务按计划推进（下轮再战），错误留痕
                job["state"] = "failed"
                job["last_error"] = err
                job["retry_count"] = 0
                if job["trigger_parsed"] == "once":
                    job["enabled"] = False
                    job["next_run"] = None
                else:
                    job["next_run"] = compute_next_run(
                        parse_trigger(job["trigger"]), now).isoformat(timespec="seconds")
            self._save_jobs()

        cred_note = f"data/scheduler/runs/{datetime.now().strftime('%Y-%m-%d')}.log"
        self._append_run_log(job_name, trigger_way, self._action_desc(act),
                             "PASS" if ok else "FAIL", detail, elapsed, err, cred_note)
        return ok, err, elapsed

    def _run_skill(self, act: dict) -> tuple:
        """经 SkillsRegistry 公开 execute 执行已注册技能（带异常兜底）。"""
        try:
            from standard_mode.core.skills_registry import get_skills_registry
        except ImportError:
            from bridge.skills.registry import get_skills_registry
        registry = get_skills_registry()
        # execute 对未注册技能返回 success=False 的 SkillResult（冻结区 L427 行为），不会抛异常
        result = registry.execute(act["skill"], dict(act["args"]))
        ok = bool(getattr(result, "success", False))
        out = getattr(result, "output", "") or ""
        err = getattr(result, "error", None) or (None if ok else out[-300:] or "技能返回 success=False")
        return ok, err, f"skill={act['skill']} args={json.dumps(act['args'], ensure_ascii=False)} out={out[:200]}"

    def _run_command(self, act: dict) -> tuple:
        """经 Commander 派发自然语言指令（复用既有 submit/dispatch/approval 信号链）。"""
        cmdr = self._commander
        if cmdr is None:
            return False, "Commander 未挂载（main.py 启动编排区 attach_commander），无法派发 command 动作", ""
        try:
            idxs = cmdr.submit_cluster(act["command"])
            if not idxs:
                return False, "Commander.submit_cluster 返回空列表（指令文本为空或解析失败）", ""
            rec = cmdr.dispatch_next()
            manual_note = ""
            if act["mode"] == "manual" and not getattr(cmdr, "_manual", False):
                manual_note = "；注意：Commander 实例为自动审批模式，manual 请求无法走 approval_needed（该参数为构造级）"
            dispatched = bool(rec and rec.get("ok"))
            if not dispatched:
                return False, "Commander.dispatch_next 未成功派发（无可用 worker 或命令均已完成）", act["command"]
            return True, None, (f"command='{act['command']}' mode={act['mode']} "
                                f"cmd_idxs={idxs}{manual_note}（执行结果经 worker_reported 信号异步回传）")
        except Exception as e:
            return False, f"Commander 派发异常: {e}", act["command"]

    def _commander_busy(self) -> bool:
        """Agent 忙碌判定：任一命令 RUNNING 或任一窗口 RUNNING 或审批挂起。"""
        cmdr = self._commander
        if cmdr is None:
            return False
        try:
            from shared.window_commander import CmdStatus, WindowStatus
            if getattr(cmdr, "_approval_event", None) is not None:
                return True
            for c in cmdr.commands:
                if c.status == CmdStatus.RUNNING:
                    return True
            for w in cmdr.windows.values():
                if w.status == WindowStatus.RUNNING:
                    return True
            return False
        except Exception:
            return False  # Commander 状态不可读时按空闲处理，交给 dispatch 自行拒绝

    @staticmethod
    def _action_desc(act: dict) -> str:
        if act["type"] == "skill":
            return f"技能 {act['skill']} args={json.dumps(act['args'], ensure_ascii=False)}"
        return f"指令 '{act['command']}' (mode={act['mode']})"

    # ══════════════════════ 错过补偿 ══════════════════════
    def _compensate_misfires(self):
        """启动时发现 next_run 已过期的一次性任务 → 补跑一次，日志标记 [misfire-compensated]。"""
        now = datetime.now()
        with self._lock:
            stale = []
            for job in self._jobs.values():
                if not job["enabled"] or job["trigger_parsed"] != "once":
                    continue
                nr = job.get("next_run")
                if not nr:
                    continue
                try:
                    if datetime.fromisoformat(nr) <= now:
                        stale.append(job["job_id"])
                except ValueError:
                    continue
        for job_id in stale:
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job["_misfire"] = True
            ok, err, secs = self._execute_job(job_id, trigger_way="启动错过补偿 [misfire-compensated]")
            print(f"[Scheduler] [misfire-compensated] 任务 {job_id} 补跑 "
                  f"{'成功' if ok else '失败: ' + str(err)}", flush=True)

    # ══════════════════════ 持久化 ══════════════════════
    def _jobs_path(self) -> str:
        return os.path.join(self._data_dir, _JOBS_FILE)

    def _save_jobs(self):
        """tmp 文件 + os.replace 原子替换（D4 惯例）。调用方需持锁。"""
        os.makedirs(self._data_dir, exist_ok=True)
        snap = []
        for j in self._jobs.values():
            clean = {k: v for k, v in j.items() if not k.startswith("_")}
            snap.append(clean)
        tmp = self._jobs_path() + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "updated_at": datetime.now().isoformat(timespec="seconds"),
                       "jobs": snap}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._jobs_path())

    def _load_jobs(self):
        path = self._jobs_path()
        if not os.path.isfile(path):
            return
        try:
            with io.open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for j in data.get("jobs", []):
                self._jobs[j["job_id"]] = j
        except (OSError, ValueError, KeyError) as e:
            # 损坏不静默：重命名保留现场，从空表启动
            print(f"[Scheduler] jobs.json 解析失败({e})，已备份为 jobs.json.corrupt 后重建", flush=True)
            try:
                os.replace(path, path + ".corrupt")
            except OSError:
                pass

    # ══════════════════════ 执行日志（中文八段） ══════════════════════
    def _append_run_log(self, name, trigger_way, content, result, detail, elapsed, err, cred):
        os.makedirs(self._runs_dir, exist_ok=True)
        path = os.path.join(self._runs_dir, datetime.now().strftime("%Y-%m-%d") + ".log")
        line = (
            f"[{datetime.now().isoformat(timespec='seconds')}] "
            f"时间={datetime.now().strftime('%H:%M:%S')} | 任务={name} | 触发方式={trigger_way} | "
            f"执行内容={content} | 结果={result} {detail[:120]} | 耗时={elapsed:.3f}s | "
            f"错误={str(err)[:200] if err else '无'} | 凭据路径={cred}\n"
        )
        try:
            with io.open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            print(f"[Scheduler] 执行日志写入失败: {e}", flush=True)
