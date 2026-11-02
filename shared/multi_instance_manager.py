# -*- coding: utf-8 -*-
"""
多实例编排管理器 — 多 MIMO Code 进程协同（v2.0 新增）
======================================================
核心思路：
- 管理多个独立的 MIMO Code serve 进程（不同端口）
- Director-Worker 模型：1个指挥官 + 4个执行者
- 任务分发：Director 分解任务 → Workers 并行执行
- 结果聚合：Workers 输出汇总到 Director

架构：
┌──────────────────────────────────────────────────────┐
│              MultiInstanceManager                     │
│  ┌──────────────────────────────────────────────────┐│
│  │  Director (Director Role)  — port 4097           ││
│  │  任务分解 → 分发 → 聚合结果                       ││
│  └──────────────────────────────────────────────────┘│
│  ┌──────────────────────────────────────────────────┐│
│  │  Workers:                                        ││
│  │  ├─ Worker A (Build)    — port 4098              ││
│  │  ├─ Worker B (Plan)     — port 4099              ││
│  │  ├─ Worker C (Compose)  — port 4100              ││
│  │  └─ Worker D (General)  — port 4101              ││
│  └──────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘
"""

import os
import sys
import time
import json
import threading
import subprocess
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

from PyQt5.QtCore import QObject, pyqtSignal


class InstanceRole(Enum):
    DIRECTOR = "director"   # 指挥官 — 任务分解、分发、聚合
    BUILD = "build"         # 构建 — 代码生成、编译
    PLAN = "plan"           # 规划 — 架构设计、分析
    COMPOSE = "compose"     # 组合 — 编辑、重构
    GENERAL = "general"     # 通用 — 任意任务
    # ★ v3.42: 新增4个角色，支持9 Agent员工公司架构
    REVIEW = "review"       # 审查 — 代码审查、质量保证
    TEST = "test"           # 测试 — 单元测试、集成测试
    DOCS = "docs"           # 文档 — 文档撰写、API文档
    DEVOPS = "devops"       # 运维 — 部署、CI/CD


class InstanceState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    BUSY = "busy"
    ERROR = "error"


@dataclass
class InstanceInfo:
    """实例元信息"""
    instance_id: str
    name: str
    role: InstanceRole
    port: int
    state: InstanceState = InstanceState.STOPPED
    session_id: Optional[str] = None
    process: Optional[subprocess.Popen] = None
    bridge: Any = None  # ServeBridge 实例
    output_buffer: List[str] = field(default_factory=list)
    max_buffer_size: int = 200  # 最大输出缓存条目数
    task_count: int = 0
    error_count: int = 0
    created_at: float = field(default_factory=time.time)
    model: str = "mimo-auto"
    last_cwd: str = ""


class MultiInstanceManager(QObject):
    """
    多实例编排管理器
    
    功能：
    - 启动/停止/监控多个 MIMO Code serve 进程
    - Director-Worker 角色分配
    - 任务分解、分发、并行执行
    - 结果聚合到 Director
    - 动态扩展：支持 1-5 个实例
    """
    
    # ==================== 信号 ====================
    instance_added = pyqtSignal(str, str, int)       # (instance_id, name, port)
    instance_removed = pyqtSignal(str)                # (instance_id)
    instance_state_changed = pyqtSignal(str, str)     # (instance_id, state)
    instance_output = pyqtSignal(str, str)            # (instance_id, text)
    director_aggregated = pyqtSignal(str)             # (aggregated_result)
    all_instances_idle = pyqtSignal()
    task_dispatched = pyqtSignal(str, str, str)       # (task, from_instance, to_instance)
    worker_result = pyqtSignal(str, str, str)         # (instance_id, task_id, result)
    
    # 默认端口配置（★ v3.42: 扩展到9个端口）
    DEFAULT_PORTS = {
        InstanceRole.DIRECTOR: 4097,
        InstanceRole.BUILD: 4098,
        InstanceRole.PLAN: 4099,
        InstanceRole.COMPOSE: 4100,
        InstanceRole.GENERAL: 4101,
        InstanceRole.REVIEW: 4102,
        InstanceRole.TEST: 4103,
        InstanceRole.DOCS: 4104,
        InstanceRole.DEVOPS: 4105,
    }
    
    # MIMO Code 可执行文件路径
    MIMO_EXE_NAME = "mimo.exe"
    
    def __init__(self, project_path: str = "", parent=None):
        super().__init__(parent)
        self._project_path = project_path or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._instances: Dict[str, InstanceInfo] = {}
        self._lock = threading.Lock()
        self._active_worker_count = 0
        self._mimo_exe_path = self._find_mimo_exe()
        self._serve_bridge_class = None
        self._snapshot_dir = os.path.join(self._project_path, "state", "snapshots")
        self._snapshot_interval = 5.0
        self._snapshot_thread: Optional[threading.Thread] = None
        self._snapshot_running = False
        
        self._init_pool()
        self._restore_recent_sessions()
        self._start_snapshot_thread()
    
    def _find_mimo_exe(self) -> str:
        """查找 MIMO Code 可执行文件"""
        # 先在 bin 目录找
        bin_path = os.path.join(self._project_path, "bin", self.MIMO_EXE_NAME)
        if os.path.isfile(bin_path):
            return bin_path
        
        # 在根目录找
        root_path = os.path.join(self._project_path, self.MIMO_EXE_NAME)
        if os.path.isfile(root_path):
            return root_path
        
        # 在 PATH 中找
        import shutil
        found = shutil.which(self.MIMO_EXE_NAME)
        if found:
            return found
        
        return ""
    
    def _init_pool(self):
        """初始化实例池（★ v3.42: 扩展到9个角色，预配置不启动）"""
        for role in [InstanceRole.DIRECTOR, InstanceRole.BUILD, 
                     InstanceRole.PLAN, InstanceRole.COMPOSE, InstanceRole.GENERAL,
                     InstanceRole.REVIEW, InstanceRole.TEST, InstanceRole.DOCS, InstanceRole.DEVOPS]:
            port = self.DEFAULT_PORTS[role]
            inst_id = f"mimo_{role.value}"
            info = InstanceInfo(
                instance_id=inst_id,
                name=self._get_role_display_name(role),
                role=role,
                port=port,
            )
            self._instances[inst_id] = info
    
    @staticmethod
    def _get_role_display_name(role: InstanceRole) -> str:
        names = {
            InstanceRole.DIRECTOR: "指挥官",
            InstanceRole.BUILD: "构建者",
            InstanceRole.PLAN: "规划师",
            InstanceRole.COMPOSE: "编辑者",
            InstanceRole.GENERAL: "执行者",
            InstanceRole.REVIEW: "审查员",
            InstanceRole.TEST: "测试工程师",
            InstanceRole.DOCS: "文档撰写员",
            InstanceRole.DEVOPS: "运维工程师",
        }
        return names.get(role, role.value)
    
    # ================================================================
    # 实例管理 API
    # ================================================================
    
    @property
    def instances(self) -> Dict[str, InstanceInfo]:
        return dict(self._instances)
    
    @property
    def running_count(self) -> int:
        return sum(1 for i in self._instances.values() 
                   if i.state in (InstanceState.RUNNING, InstanceState.BUSY))
    
    @property
    def director(self) -> Optional[InstanceInfo]:
        for info in self._instances.values():
            if info.role == InstanceRole.DIRECTOR:
                return info
        return None
    
    @property
    def workers(self) -> List[InstanceInfo]:
        return [i for i in self._instances.values() 
                if i.role != InstanceRole.DIRECTOR]
    
    @property
    def active_workers(self) -> List[InstanceInfo]:
        return [i for i in self.workers 
                if i.state in (InstanceState.RUNNING, InstanceState.BUSY)]
    
    def start_instance(self, instance_id: str, model: str = None) -> bool:
        """启动单个 MIMO Code 实例

        ★ v5.1 P0修复：接收 model 参数（hybrid_mode_bridge 的 hireAgent /
        setAgentModel / startCompany 均按 model= 传参，此前签名不匹配导致
        TypeError 被吞成"启动失败"）。model 记录到实例元信息供花名册与
        分级调度使用；mimo serve 进程本身不区分模型。
        """
        info = self._instances.get(instance_id)
        if not info:
            return False

        if model:
            info.model = model
        
        if info.state in (InstanceState.RUNNING, InstanceState.BUSY, InstanceState.STARTING):
            return True  # 已经在运行
        
        if not self._mimo_exe_path:
            self.instance_state_changed.emit(instance_id, InstanceState.ERROR.value)
            info.state = InstanceState.ERROR
            return False
        
        try:
            info.state = InstanceState.STARTING
            self.instance_state_changed.emit(instance_id, InstanceState.STARTING.value)
            
            # 启动 MIMO Code serve 进程
            env = os.environ.copy()
            env["MIMO_PORT"] = str(info.port)

            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            info.process = subprocess.Popen(
                [self._mimo_exe_path, "serve", "--port", str(info.port)],
                cwd=self._project_path,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=flags,
                text=True,
            )

            # ★ v22.2 API 就绪轮询（替代 sleep(2)）
            # 健康检查通过后，还需等 /session API 完全就绪（实验一经验：约 8s）
            api_ready = self._wait_for_api_ready(info.port, max_wait=30)
            if api_ready:
                info.state = InstanceState.RUNNING
                self.instance_state_changed.emit(instance_id, InstanceState.RUNNING.value)
                self.instance_added.emit(instance_id, info.name, info.port)
                self._active_worker_count += 1
                return True
            else:
                info.state = InstanceState.ERROR
                self.instance_state_changed.emit(instance_id, InstanceState.ERROR.value)
                return False
                
        except Exception as e:
            info.state = InstanceState.ERROR
            self.instance_state_changed.emit(instance_id, InstanceState.ERROR.value)
            return False
    
    def start_all(self, count: int = 5) -> int:
        """启动指定数量的实例（1-5）"""
        count = max(1, min(5, count))
        started = 0
        
        # 先启动 Director
        if self.director:
            if self.start_instance(self.director.instance_id):
                started += 1
        
        # 再启动 Workers
        for worker in self.workers[:count - 1]:
            if self.start_instance(worker.instance_id):
                started += 1
        
        return started
    
    def start_minimal(self) -> int:
        """启动最小模式（仅 Director + 1 Worker）"""
        return self.start_all(count=2)
    
    def stop_instance(self, instance_id: str):
        """停止单个实例"""
        info = self._instances.get(instance_id)
        if not info:
            return
        
        if info.process:
            try:
                info.process.terminate()
                info.process.wait(timeout=5)
            except Exception:
                try:
                    info.process.kill()
                except Exception:
                    pass
            info.process = None
        
        if info.state in (InstanceState.RUNNING, InstanceState.BUSY):
            self._active_worker_count = max(0, self._active_worker_count - 1)
        
        info.state = InstanceState.STOPPED
        info.session_id = None
        info.bridge = None
        self.instance_state_changed.emit(instance_id, InstanceState.STOPPED.value)
        self.instance_removed.emit(instance_id)
    
    def stop_all(self):
        """停止所有实例"""
        for instance_id in list(self._instances.keys()):
            self.stop_instance(instance_id)
    
    def _check_instance_health(self, port: int) -> bool:
        """检查实例健康状态"""
        try:
            import requests
            r = requests.get(f"http://localhost:{port}/global/health", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def _wait_for_api_ready(self, port: int, max_wait: int = 30) -> bool:
        """
        ★ v22.2 等待 mimo serve API 完全就绪
        判定标准: /global/health 通过 AND /session API 可访问
        轮询间隔: 1s，最长等待 max_wait 秒
        """
        deadline = time.time() + max_wait
        health_ok = False
        session_ok = False
        last_err = ""
        while time.time() < deadline:
            # 1. 健康检查
            if not health_ok:
                if self._check_instance_health(port):
                    health_ok = True
            # 2. session API 检查（仅在健康后）
            if health_ok and not session_ok:
                try:
                    import requests
                    r = requests.get(f"http://localhost:{port}/session", timeout=3)
                    if r.status_code == 200:
                        session_ok = True
                        break
                    else:
                        last_err = f"session API HTTP {r.status_code}"
                except Exception as e:
                    last_err = f"session API 异常: {e}"
            time.sleep(1)
        if session_ok:
            print(f"[MultiInstance] ✅ 实例 :{port} API 就绪 (健康={health_ok}, session={session_ok})")
            return True
        else:
            print(f"[MultiInstance] ❌ 实例 :{port} API 未就绪 (健康={health_ok}, session={session_ok}, err={last_err})")
            return False

    # ================================================================
    # ★ v22.1 真实 HTTP 派发 (Phase 2)
    # ================================================================

    def ensure_session(self, instance_id: str, title: str = None) -> Optional[str]:
        """确保实例有可用 session_id（不存在则创建）。返回 session_id 或 None。"""
        info = self._instances.get(instance_id)
        if not info:
            return None
        if info.session_id and self._check_session_alive(info.port, info.session_id):
            return info.session_id
        try:
            import requests
            url = f"http://localhost:{info.port}/session"
            r = requests.post(url, json={"title": title or f"session_{instance_id}"}, timeout=10)
            if r.status_code in (200, 201):
                data = r.json()
                sid = data.get('id') if isinstance(data, dict) else None
                if sid:
                    info.session_id = sid
                    return sid
            return None
        except Exception:
            return None

    def _check_session_alive(self, port: int, session_id: str) -> bool:
        """检查 session 是否仍然存在"""
        try:
            import requests
            r = requests.get(f"http://localhost:{port}/session", timeout=5)
            if r.status_code == 200:
                data = r.json()
                sids = [s.get('id') for s in data] if isinstance(data, list) else []
                return session_id in sids
            return False
        except Exception:
            return False

    def dispatch_to_instance(self, instance_id: str, prompt: str,
                              temperature: float = 0.7, max_tokens: int = 2000,
                              timeout: int = 60) -> Dict[str, Any]:
        """
        ★ v22.1 真实派发：将 prompt 通过 HTTP API 派发到指定实例
        ★ v22.2 timeout 默认 60s（原 30s 太短，长任务需要 60-120s）

        Returns:
            {
                "success": bool,
                "instance_id": str,
                "session_id": str | None,
                "http_status": int | None,
                "error": str | None,
                "dispatched_at": float,
            }
        """
        import time
        result: Dict[str, Any] = {
            "success": False,
            "instance_id": instance_id,
            "session_id": None,
            "http_status": None,
            "error": None,
            "dispatched_at": time.time(),
        }
        info = self._instances.get(instance_id)
        if not info:
            result["error"] = f"实例 {instance_id} 不存在"
            return result
        if info.state not in (InstanceState.RUNNING, InstanceState.BUSY):
            result["error"] = f"实例 {instance_id} 状态为 {info.state.value}，未运行"
            return result

        # 1. 确保 session
        sid = self.ensure_session(instance_id, title=f"task_{int(time.time())}")
        if not sid:
            result["error"] = "无法创建/获取 session_id"
            info.error_count += 1
            return result
        result["session_id"] = sid

        # 2. 标记 BUSY
        prev_state = info.state
        info.state = InstanceState.BUSY
        self.instance_state_changed.emit(instance_id, InstanceState.BUSY.value)
        info.task_count += 1

        # 3. POST /session/{sid}/prompt_async
        try:
            import requests
            url = f"http://localhost:{info.port}/session/{sid}/prompt_async"
            body = {
                "parts": [{"type": "text", "text": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            r = requests.post(url, json=body, timeout=timeout)
            result["http_status"] = r.status_code
            if r.status_code in (200, 201, 202, 204):
                result["success"] = True
                self.task_dispatched.emit(prompt, "hybrid_bridge", instance_id)
            else:
                result["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
                info.error_count += 1
        except Exception as e:
            result["error"] = f"请求异常: {e}"
            info.error_count += 1
        finally:
            # 4. 恢复状态
            info.state = prev_state
            self.instance_state_changed.emit(instance_id, prev_state.value)
        return result

    def get_instance_status(self, instance_id: str = None) -> Dict:
        """获取实例状态（单个或全部）。无参=全部集群摘要。"""
        if instance_id:
            return self.get_instance_summary(instance_id)
        return self.get_cluster_summary()
    
    def get_running_ports(self) -> List[int]:
        """获取所有运行中实例的端口"""
        return [i.port for i in self._instances.values() 
                if i.state in (InstanceState.RUNNING, InstanceState.BUSY)]
    
    # ================================================================
    # Director-Worker 编排
    # ================================================================
    
    def dispatch_task(self, task: str, target_role: InstanceRole = None) -> Optional[str]:
        """Director 分发任务给 Worker"""
        director_info = self.director
        if not director_info or director_info.state not in (InstanceState.RUNNING, InstanceState.BUSY):
            return None
        
        # 选择目标 Worker
        target = None
        if target_role:
            target = self._find_worker_by_role(target_role)
        if not target:
            target = self._find_least_busy_worker()
        if not target:
            return None
        
        # 标记 Worker 为忙碌
        target.state = InstanceState.BUSY
        self.instance_state_changed.emit(target.instance_id, InstanceState.BUSY.value)
        target.task_count += 1
        
        self.task_dispatched.emit(task, director_info.instance_id, target.instance_id)
        
        return target.instance_id
    
    def dispatch_batch(self, tasks: List[str]) -> Dict[str, str]:
        """
        批量分发任务给多个 Worker
        
        Returns: {instance_id: task, ...}
        """
        assignments = {}
        available = self.active_workers
        
        for i, task in enumerate(tasks):
            if not available:
                break
            worker = available[i % len(available)]
            worker_id = self.dispatch_task(task)
            if worker_id:
                assignments[worker_id] = task
        
        return assignments
    
    def dispatch_parallel(self, task: str, worker_count: int = None) -> List[str]:
        """
        将同一任务并行发送给多个 Worker
        
        Returns: list of worker instance_ids
        """
        assigned = []
        workers = self.active_workers[:worker_count] if worker_count else self.active_workers
        
        for worker in workers:
            worker_id = self.dispatch_task(task)
            if worker_id:
                assigned.append(worker_id)
        
        return assigned
    
    def _find_worker_by_role(self, role: InstanceRole) -> Optional[InstanceInfo]:
        for info in self.workers:
            if info.role == role and info.state in (InstanceState.RUNNING, InstanceState.BUSY):
                return info
        return None
    
    def _find_least_busy_worker(self) -> Optional[InstanceInfo]:
        workers = self.active_workers
        if not workers:
            return None
        return min(workers, key=lambda w: w.task_count)
    
    def mark_worker_done(self, instance_id: str, result: str = ""):
        """标记 Worker 任务完成"""
        info = self._instances.get(instance_id)
        if not info:
            return
        # 无论之前是 BUSY 还是 RUNNING（多次派发场景），都记录结果并把状态置回 RUNNING
        if info.state == InstanceState.BUSY:
            info.state = InstanceState.RUNNING
            self.instance_state_changed.emit(instance_id, InstanceState.RUNNING.value)
        if result:
            info.output_buffer.append(result)
            # ★ 限制 buffer 大小，防止内存泄漏
            if len(info.output_buffer) > info.max_buffer_size:
                info.output_buffer = info.output_buffer[-info.max_buffer_size:]
            self.worker_result.emit(instance_id, f"task_{info.task_count}", result)

        # 检查是否所有 Worker 空闲
        if not any(w.state == InstanceState.BUSY for w in self.workers):
            self.all_instances_idle.emit()
    
    def aggregate_results(self) -> str:
        """聚合所有 Worker 的输出结果"""
        results = []
        for info in self.workers:
            if info.output_buffer:
                results.append(f"## {info.name} ({info.role.value})\n")
                for output in info.output_buffer[-5:]:  # 最近5条
                    results.append(f"- {output[:200]}\n")
                results.append("")
        
        aggregated = "\n".join(results) if results else "暂无 Worker 输出"
        self.director_aggregated.emit(aggregated)
        return aggregated
    
    def get_instance_summary(self, instance_id: str) -> Dict:
        """获取实例摘要"""
        info = self._instances.get(instance_id)
        if not info:
            return {"error": "instance not found"}
        
        return {
            "id": info.instance_id,
            "name": info.name,
            "role": info.role.value,
            "state": info.state.value,
            "port": info.port,
            "tasks": info.task_count,
            "errors": info.error_count,
            "has_bridge": info.bridge is not None,
            "has_session": info.session_id is not None,
        }
    
    def get_cluster_summary(self) -> Dict:
        """获取整个集群摘要"""
        return {
            "total": len(self._instances),
            "running": self.running_count,
            "director": self.get_instance_summary(
                self.director.instance_id) if self.director else None,
            "workers": [self.get_instance_summary(w.instance_id) for w in self.workers],
            "active_workers": self._active_worker_count,
            "mimo_exe": self._mimo_exe_path,
        }
    
    def get_status_text(self) -> str:
        """获取集群状态文本（用于状态栏显示）"""
        total = len(self._instances)
        running = self.running_count
        
        if running == 0:
            return "⚪ 未启动"
        elif running == 1:
            return "🟢 单实例模式"
        elif running <= 2:
            return "🔵 最小模式 (2实例)"
        elif running <= 4:
            return "🟣 工作组模式"
        else:
            return "🟡 全集群模式 (5实例)"

    def _start_snapshot_thread(self) -> None:
        self._snapshot_running = True
        self._snapshot_thread = threading.Thread(target=self._snapshot_loop, daemon=True)
        self._snapshot_thread.start()

    def _stop_snapshot_thread(self) -> None:
        self._snapshot_running = False
        if self._snapshot_thread and self._snapshot_thread.is_alive():
            self._snapshot_thread.join(timeout=3)

    def _snapshot_loop(self) -> None:
        while self._snapshot_running:
            try:
                self._write_health_snapshot()
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug("[MultiInstanceManager] snapshot失败: %s", e)
            time.sleep(self._snapshot_interval)

    def _write_health_snapshot(self) -> None:
        try:
            os.makedirs(self._snapshot_dir, exist_ok=True)
        except Exception:
            return
        snapshot = {
            "timestamp": time.time(),
            "cluster": self.get_cluster_summary(),
            "sessions": [],
        }
        with self._lock:
            for inst_id, info in self._instances.items():
                if info.state in (InstanceState.RUNNING, InstanceState.BUSY):
                    snapshot["sessions"].append({
                        "instance_id": inst_id,
                        "name": info.name,
                        "role": info.role.value,
                        "port": info.port,
                        "cwd": info.last_cwd,
                        "buffer_tail": info.output_buffer[-5:] if info.output_buffer else [],
                        "session_id": info.session_id,
                    })
        ts_str = time.strftime("%Y%m%d_%H%M%S", time.localtime(snapshot["timestamp"]))
        snap_path = os.path.join(self._snapshot_dir, f"health_{ts_str}.json")
        try:
            with open(snap_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        try:
            snaps = sorted(
                [os.path.join(self._snapshot_dir, f) for f in os.listdir(self._snapshot_dir)
                 if f.startswith("health_") and f.endswith(".json")])
            for old in snaps[:-10]:
                os.remove(old)
        except Exception:
            pass

    def _restore_recent_sessions(self) -> None:
        try:
            if not os.path.isdir(self._snapshot_dir):
                return
            snaps = sorted(
                [os.path.join(self._snapshot_dir, f) for f in os.listdir(self._snapshot_dir)
                 if f.startswith("health_") and f.endswith(".json")], reverse=True)
            if not snaps:
                return
            latest = snaps[0]
            with open(latest, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
            restored = 0
            stale = 0
            for sess in snapshot.get("sessions", [])[:3]:
                inst_id = sess.get("instance_id", "")
                if inst_id in self._instances:
                    info = self._instances[inst_id]
                    if sess.get("cwd"):
                        info.last_cwd = sess["cwd"]
                    if sess.get("buffer_tail"):
                        info.output_buffer = sess["buffer_tail"]
                    if sess.get("session_id"):
                        info.session_id = sess["session_id"]
                    restored += 1
                else:
                    stale += 1
            import logging
            logging.getLogger(__name__).info(
                "[MultiInstanceManager] 恢复%d个会话状态, %d个已过期(from %s)",
                restored, stale, os.path.basename(latest))
        except Exception:
            pass