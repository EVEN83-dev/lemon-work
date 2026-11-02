# -*- coding: utf-8 -*-
"""
Lemon Agent 超级大脑
====================
实现项目公司化的核心决策系统：
- 任务分解
- 复杂度评估
- 任务分配
- 进度监控
- 错误处理
- 结果聚合

核心功能：
1. Superbrain - 超级大脑核心
2. TaskDecomposer - 任务分解器
3. ComplexityEvaluator - 复杂度评估器
4. Scheduler - 调度器
"""

import os
import sys
import json
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.work_group import (
    WorkGroup, Message, ReportSystem, StatusBlackboard,
    get_workgroup, get_report_system, get_blackboard
)


# ============================================================================
# 数据结构
# ============================================================================

class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutorType(Enum):
    """执行者类型"""
    CLOUD = "cloud"       # 云端执行
    LOCAL = "local"       # 本地执行
    HYBRID = "hybrid"     # 混合执行


@dataclass
class SubTask:
    """子任务"""
    id: str
    name: str
    description: str
    complexity: float  # 0-10
    executor: str      # 执行者AI ID
    executor_type: str  # cloud/local
    priority: int = 2
    status: str = "pending"
    dependencies: List[str] = field(default_factory=list)
    result: Any = None
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "complexity": self.complexity,
            "executor": self.executor,
            "executor_type": self.executor_type,
            "priority": self.priority,
            "status": self.status,
            "dependencies": self.dependencies,
            "result": self.result,
            "error": self.error
        }


@dataclass
class ProjectContext:
    """项目上下文"""
    project_name: str
    root_path: str
    tech_stack: List[str] = field(default_factory=list)
    constraints: Dict = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)


# ============================================================================
# 复杂度评估器
# ============================================================================

class ComplexityEvaluator:
    """任务复杂度评估器"""

    def __init__(self):
        # 关键词权重
        self.keyword_weights = {
            # 高复杂度关键词（+3分）
            "架构": 3.0, "设计": 3.0, "重构": 3.0, "优化": 3.0,
            "分布式": 3.0, "微服务": 3.0, "安全": 3.0,
            # 中等复杂度关键词（+2分）
            "实现": 2.0, "开发": 2.0, "编写": 2.0, "修改": 2.0,
            "添加": 2.0, "集成": 2.0, "部署": 2.0,
            # 低复杂度关键词（+1分）
            "修复": 1.0, "删除": 1.0, "移动": 1.0, "重命名": 1.0,
            "配置": 1.0, "调整": 1.0
        }

        # 技术栈复杂度
        self.tech_complexity = {
            "frontend": 3.0,
            "backend": 4.0,
            "database": 4.0,
            "api": 3.5,
            "test": 2.0,
            "devops": 3.5
        }

    def evaluate(self, task: str, context: Dict = None) -> float:
        """
        评估任务复杂度 (0.0 - 10.0)

        维度：
        1. 任务长度
        2. 关键词权重
        3. 技术栈复杂度
        4. 文件数量
        5. 依赖关系
        """
        score = 0.0

        # 1. 长度评分
        length = len(task)
        if length < 50:
            score += 1.0
        elif length < 200:
            score += 3.0
        else:
            score += 5.0

        # 2. 关键词评分
        for keyword, weight in self.keyword_weights.items():
            if keyword in task:
                score += weight

        # 3. 技术栈复杂度
        if context:
            tech_stack = context.get("tech_stack", [])
            for tech in tech_stack:
                if tech in self.tech_complexity:
                    score += self.tech_complexity[tech]

            # 4. 文件数量
            files = context.get("files", [])
            score += min(len(files) * 0.5, 2.0)

            # 5. 依赖关系
            deps = context.get("dependencies", [])
            score += min(len(deps) * 0.5, 2.0)

        return min(score, 10.0)

    def get_recommendation(self, complexity: float) -> Dict:
        """根据复杂度推荐执行方案"""
        if complexity >= 8.0:
            return {
                "executor_type": "cloud",
                "model": "DeepSeek V4",
                "reason": "超复杂任务，需要最强推理能力"
            }
        elif complexity >= 6.0:
            return {
                "executor_type": "cloud",
                "model": "MIMO Code",
                "reason": "复杂任务，需要强推理能力"
            }
        elif complexity >= 4.0:
            return {
                "executor_type": "local",
                "model": "qwen3.5:9b",
                "reason": "中等任务，本地大模型足够"
            }
        else:
            return {
                "executor_type": "local",
                "model": "qwen3.5:4b",
                "reason": "简单任务，本地快速模型"
            }


# ============================================================================
# 任务分解器
# ============================================================================

class TaskDecomposer:
    """任务分解器"""

    def __init__(self):
        self.evaluator = ComplexityEvaluator()

        # 分解模板
        self.templates = {
            "web_project": [
                "前端UI设计与实现",
                "后端API开发",
                "数据库设计",
                "前后端联调",
                "功能测试",
                "代码审查"
            ],
            "api_project": [
                "API接口设计",
                "数据库模型设计",
                "业务逻辑实现",
                "接口测试",
                "文档编写"
            ],
            "refactor": [
                "代码审查与分析",
                "重构方案设计",
                "模块重构",
                "测试验证",
                "性能对比"
            ]
        }

    def decompose(self, task: str, context: Dict = None) -> List[SubTask]:
        """
        分解任务为子任务

        步骤：
        1. 识别项目类型
        2. 应用分解模板
        3. 评估每个子任务复杂度
        4. 生成任务依赖关系
        """
        subtasks = []

        # 1. 识别项目类型
        project_type = self._detect_project_type(task, context)

        # 2. 应用分解模板
        template = self.templates.get(project_type, ["任务实现"])

        # 3. 生成子任务
        import uuid
        for i, task_name in enumerate(template):
            task_id = f"task_{uuid.uuid4().hex[:6]}"
            complexity = self.evaluator.evaluate(task_name, context)
            recommendation = self.evaluator.get_recommendation(complexity)

            subtask = SubTask(
                id=task_id,
                name=task_name,
                description=f"{task_name}（源自: {task[:50]}...）",
                complexity=complexity,
                executor="",  # 待分配
                executor_type=recommendation["executor_type"],
                priority=2,
                status="pending",
                dependencies=[subtasks[i-1].id] if i > 0 else []
            )
            subtasks.append(subtask)

        return subtasks

    def _detect_project_type(self, task: str, context: Dict) -> str:
        """检测项目类型"""
        task_lower = task.lower()

        if any(kw in task_lower for kw in ["web", "网站", "前端", "ui", "页面"]):
            return "web_project"
        elif any(kw in task_lower for kw in ["api", "接口", "后端", "服务"]):
            return "api_project"
        elif any(kw in task_lower for kw in ["重构", "优化", "改进"]):
            return "refactor"
        else:
            return "web_project"  # 默认


# ============================================================================
# 调度器
# ============================================================================

class Scheduler:
    """任务调度器"""

    def __init__(self, workgroup: WorkGroup):
        self.workgroup = workgroup
        self.executors: Dict[str, Dict] = {}  # ai_id -> {role, model, load, ...}
        self._lock = threading.Lock()

    def register_executor(self, ai_id: str, role: str, model: str, max_load: int = 3):
        """注册执行者"""
        with self._lock:
            self.executors[ai_id] = {
                "role": role,
                "model": model,
                "max_load": max_load,
                "current_load": 0,
                "tasks": []
            }

    def assign(self, subtask: SubTask) -> str:
        """
        分配任务给最合适的执行者

        策略：
        1. 根据角色匹配
        2. 根据复杂度选择模型
        3. 根据负载均衡
        """
        with self._lock:
            # 1. 根据角色筛选
            candidates = []
            for ai_id, info in self.executors.items():
                if info["current_load"] < info["max_load"]:
                    candidates.append((ai_id, info))

            if not candidates:
                # 所有执行者都忙，选择负载最小的
                min_load_ai = min(
                    self.executors.items(),
                    key=lambda x: x[1]["current_load"]
                )
                return min_load_ai[0]

            # 2. 根据复杂度选择
            if subtask.executor_type == "cloud":
                # 选择云端模型
                for ai_id, info in candidates:
                    if info["model"] in ["DeepSeek V4", "MIMO Code"]:
                        return ai_id

            # 3. 本地模型，按负载均衡
            min_load = min(info["current_load"] for _, info in candidates)
            for ai_id, info in candidates:
                if info["current_load"] == min_load:
                    return ai_id

            return candidates[0][0]

    def update_load(self, ai_id: str, delta: int):
        """更新执行者负载"""
        with self._lock:
            if ai_id in self.executors:
                self.executors[ai_id]["current_load"] += delta
                self.executors[ai_id]["current_load"] = max(
                    0,
                    self.executors[ai_id]["current_load"]
                )


# ============================================================================
# 超级大脑核心
# ============================================================================

class Superbrain:
    """超级大脑 — 项目公司化的核心决策系统"""

    def __init__(self, name: str = "Superbrain"):
        self.name = name
        self.workgroup = get_workgroup()
        self.report_system = get_report_system()
        self.blackboard = get_blackboard()

        self.decomposer = TaskDecomposer()
        self.evaluator = ComplexityEvaluator()
        self.scheduler = Scheduler(self.workgroup)

        self.projects: Dict[str, Dict] = {}  # project_id -> project_info
        self.active_tasks: Dict[str, SubTask] = {}  # task_id -> SubTask
        self._lock = threading.Lock()

        # 注册到工作群
        self.workgroup.add_member("superbrain", "项目经理")
        self.workgroup.add_handler(self._handle_message)

    # ==================== 项目管理 ====================

    def start_project(self, project_name: str, description: str,
                      context: ProjectContext = None) -> str:
        """
        启动项目

        流程：
        1. 分解任务
        2. 评估复杂度
        3. 分配执行者
        4. 通知工作群
        """
        import uuid
        project_id = f"proj_{uuid.uuid4().hex[:8]}"

        # 1. 分解任务
        subtasks = self.decomposer.decompose(
            description,
            context.__dict__ if context else None
        )

        # 2. 创建项目记录
        project = {
            "id": project_id,
            "name": project_name,
            "description": description,
            "subtasks": {st.id: st.to_dict() for st in subtasks},
            "status": "running",
            "start_time": time.time(),
            "context": context.__dict__ if context else {}
        }

        with self._lock:
            self.projects[project_id] = project
            for st in subtasks:
                self.active_tasks[st.id] = st

        # 3. 广播项目启动
        self.workgroup.broadcast(
            "superbrain",
            f"项目【{project_name}】启动，共 {len(subtasks)} 个子任务"
        )

        # 4. 分配任务
        for subtask in subtasks:
            executor = self.scheduler.assign(subtask)
            subtask.executor = executor
            subtask.status = "assigned"

            # 通知执行者
            self.workgroup.command(
                "superbrain",
                executor,
                f"执行任务: {subtask.name}",
                {"task_id": subtask.id, "description": subtask.description}
            )

        return project_id

    def get_project_status(self, project_id: str) -> Dict:
        """获取项目状态"""
        project = self.projects.get(project_id)
        if not project:
            return {"error": "项目不存在"}

        subtasks = project.get("subtasks", {})
        completed = sum(1 for st in subtasks.values() if st.get("status") == "completed")
        running = sum(1 for st in subtasks.values() if st.get("status") == "running")
        failed = sum(1 for st in subtasks.values() if st.get("status") == "failed")

        progress = completed / len(subtasks) if subtasks else 0

        return {
            "project_id": project_id,
            "name": project["name"],
            "status": project["status"],
            "progress": progress,
            "completed": completed,
            "running": running,
            "failed": failed,
            "total": len(subtasks)
        }

    # ==================== 消息处理 ====================

    def _handle_message(self, message: Message):
        """处理工作群消息"""
        # 只处理发给超级大脑或广播的消息
        if message.to_ai not in ["superbrain", "all"]:
            return

        # 处理不同类型的消息
        if message.msg_type == "result":
            self._handle_result(message)
        elif message.msg_type == "error":
            self._handle_error(message)
        elif message.msg_type == "status":
            self._handle_status(message)

    def _handle_result(self, message: Message):
        """处理结果汇报"""
        # 更新任务状态
        metadata = message.metadata
        task_id = metadata.get("task_id")

        if task_id and task_id in self.active_tasks:
            subtask = self.active_tasks[task_id]
            subtask.status = "completed"
            subtask.result = message.content
            subtask.end_time = time.time()

            # 更新负载
            self.scheduler.update_load(subtask.executor, -1)

            # 广播完成
            self.workgroup.broadcast(
                "superbrain",
                f"任务【{subtask.name}】完成"
            )

    def _handle_error(self, message: Message):
        """处理错误汇报"""
        metadata = message.metadata
        task_id = metadata.get("task_id")

        if task_id and task_id in self.active_tasks:
            subtask = self.active_tasks[task_id]
            subtask.status = "failed"
            subtask.error = message.content

            # 决策：重试或重新分配
            self.workgroup.broadcast(
                "superbrain",
                f"任务【{subtask.name}】失败: {message.content}"
            )

            # 尝试重新分配
            self._retry_task(subtask)

    def _handle_status(self, message: Message):
        """处理状态更新"""
        # 更新黑板状态
        self.blackboard.update(
            message.from_ai,
            {"status": message.content, "last_active": time.time()}
        )

    def _retry_task(self, subtask: SubTask):
        """重试失败的任务"""
        # 重新分配执行者
        new_executor = self.scheduler.assign(subtask)
        if new_executor != subtask.executor:
            subtask.executor = new_executor
            subtask.status = "assigned"

            self.workgroup.command(
                "superbrain",
                new_executor,
                f"重试任务: {subtask.name}",
                {"task_id": subtask.id}
            )

    # ==================== 聚合结果 ====================

    def aggregate_results(self, project_id: str) -> Dict:
        """聚合项目结果"""
        project = self.projects.get(project_id)
        if not project:
            return {"error": "项目不存在"}

        subtasks = project.get("subtasks", {})

        # 统计结果
        results = {
            "project_id": project_id,
            "project_name": project["name"],
            "total_tasks": len(subtasks),
            "completed_tasks": 0,
            "failed_tasks": 0,
            "total_time": 0,
            "task_results": []
        }

        for task_id, task_info in subtasks.items():
            if task_info.get("status") == "completed":
                results["completed_tasks"] += 1
                results["task_results"].append({
                    "task_id": task_id,
                    "name": task_info["name"],
                    "result": task_info.get("result")
                })
            elif task_info.get("status") == "failed":
                results["failed_tasks"] += 1

        # 标记项目完成
        if results["completed_tasks"] == results["total_tasks"]:
            project["status"] = "completed"
            project["end_time"] = time.time()
            results["total_time"] = project["end_time"] - project["start_time"]

        return results

    # ==================== 统计 ====================

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            return {
                "name": self.name,
                "projects_count": len(self.projects),
                "active_tasks_count": len(self.active_tasks),
                "workgroup_stats": self.workgroup.get_stats()
            }

    # ==================== 端到端编排执行 ====================

    def orchestrate_and_execute(self, task_description: str) -> Dict:
        """
        端到端编排与执行：分解任务 → AgentOrchestrator 分配 → SkillChain 执行 → 聚合结果

        完整流程：
        1. 使用 TaskDecomposer 分解任务为子任务
        2. 使用 AgentOrchestrator 注册 agent 并分配子任务
        3. 使用 SkillChain 串行执行子任务
        4. 聚合所有子任务结果

        Args:
            task_description: 任务描述

        Returns:
            包含编排与执行完整信息的字典
        """
        import logging
        import uuid
        logger = logging.getLogger(__name__)

        start_time = time.time()
        result = {
            "success": False,
            "task_description": task_description,
            "subtasks": [],
            "orchestrator_status": None,
            "chain_results": [],
            "final_output": "",
            "errors": [],
            "duration_ms": 0.0,
        }

        try:
            # ---- Step 1: 分解任务 ----
            subtasks = self.decomposer.decompose(task_description)
            result["subtasks"] = [st.to_dict() for st in subtasks]
            logger.info(
                "[orchestrate_and_execute] 任务分解完成，子任务数=%d",
                len(subtasks),
            )

            if not subtasks:
                result["errors"].append("任务分解结果为空")
                return result

            # ---- Step 2: 使用 AgentOrchestrator 分配子任务 ----
            orchestrator = None
            project_id = f"sb_{uuid.uuid4().hex[:8]}"

            try:
                # 构造 AgentOrchestrator 所需的依赖
                from shared.agent_orchestrator import AgentOrchestrator

                # SessionContinuity 和 ProjectLog 可能不可用，提供轻量级替代
                session_continuity = self._create_stub_session_continuity()
                project_log = self._create_stub_project_log()

                orchestrator = AgentOrchestrator(
                    project_id=project_id,
                    project_name=task_description[:50],
                    session_continuity=session_continuity,
                    project_log=project_log,
                )

                # 注册默认 agent（本地执行者）
                orchestrator.register_agent("local_agent", "executor", "本地执行者")
                orchestrator.register_agent("cloud_agent", "cloud_executor", "云端执行者")

                # 将子任务添加到 orchestrator
                for i, subtask in enumerate(subtasks):
                    required_role = "cloud_executor" if subtask.executor_type == "cloud" else "executor"
                    orchestrator.add_task(
                        task_id=subtask.id,
                        title=subtask.name,
                        description=subtask.description,
                        required_role=required_role,
                        dependencies=subtask.dependencies,
                        priority=subtask.priority,
                    )

                result["orchestrator_status"] = orchestrator.get_status()
                logger.info(
                    "[orchestrate_and_execute] Orchestrator 初始化完成，任务已入队",
                )
            except Exception as e:
                logger.warning(
                    "[orchestrate_and_execute] AgentOrchestrator 初始化失败: %s，回退到直接执行",
                    e,
                )
                result["errors"].append(f"Orchestrator 初始化失败: {e}")
                orchestrator = None

            # ---- Step 3: 使用 SkillChain 串行执行子任务 ----
            try:
                from core.skill_chain import SkillChain, ChainStep, ChainStepResult

                # 构建执行链：按依赖顺序排列子任务
                chain_steps = []
                for subtask in subtasks:
                    step = ChainStep(
                        skill_name=self._map_subtask_to_skill(subtask),
                        args={"task": subtask.description, "subtask_id": subtask.id},
                        label=subtask.name,
                        on_failure="skip",
                        timeout=60,
                    )
                    chain_steps.append(step)

                chain = SkillChain(
                    name=f"sb_chain_{project_id}",
                    description=f"SuperBrain 编排链: {task_description[:50]}",
                    steps=chain_steps,
                )

                # 获取 SkillRouter 用于执行
                router = self._get_skill_router()
                if router:
                    chain_result = chain.execute(
                        router=router,
                        agent_id="superbrain",
                        initial_context={"task_description": task_description},
                    )
                    result["chain_results"] = chain_result.to_dict()
                    if chain_result.success and chain_result.final_output:
                        result["final_output"] = chain_result.final_output
                        result["success"] = True

                    # 更新子任务状态
                    for sr in chain_result.step_results:
                        for subtask in subtasks:
                            if subtask.name == sr.step_label:
                                subtask.status = "completed" if sr.success else "failed"
                                subtask.result = sr.output if sr.success else sr.error

                    logger.info(
                        "[orchestrate_and_execute] SkillChain 执行完成，成功=%s，步骤=%d/%d",
                        chain_result.success,
                        chain_result.executed_steps,
                        chain_result.total_steps,
                    )
                else:
                    # 无 Router，手动聚合
                    result["final_output"] = "; ".join(
                        f"{st.name}: 待执行" for st in subtasks
                    )
                    logger.warning(
                        "[orchestrate_and_execute] 无可用 SkillRouter，跳过链式执行",
                    )
            except Exception as e:
                logger.warning(
                    "[orchestrate_and_execute] SkillChain 执行失败: %s",
                    e,
                )
                result["errors"].append(f"SkillChain 执行失败: {e}")

            # ---- Step 4: 聚合结果 ----
            # 如果 orchestrator 可用，同步子任务状态
            if orchestrator is not None:
                try:
                    for subtask in subtasks:
                        if subtask.status == "completed":
                            orchestrator.mark_task_completed(
                                subtask.id,
                                result=subtask.result or "",
                            )
                        elif subtask.status == "failed":
                            orchestrator.mark_task_failed(
                                subtask.id,
                                error=subtask.error or "执行失败",
                            )
                    result["orchestrator_status"] = orchestrator.get_status()
                except Exception as e:
                    logger.warning(
                        "[orchestrate_and_execute] 同步 orchestrator 状态失败: %s",
                        e,
                    )

            # 如果 chain 执行未产出 final_output，尝试手动聚合
            if not result["final_output"]:
                completed_outputs = []
                for subtask in subtasks:
                    if subtask.status == "completed" and subtask.result:
                        completed_outputs.append(f"{subtask.name}: {subtask.result}")
                if completed_outputs:
                    result["final_output"] = "\n".join(completed_outputs)
                    result["success"] = True

        except Exception as e:
            logger.error("[orchestrate_and_execute] 执行失败: %s", e)
            result["errors"].append(str(e))
        finally:
            result["duration_ms"] = (time.time() - start_time) * 1000

        return result

    def _map_subtask_to_skill(self, subtask: SubTask) -> str:
        """将子任务映射到合适的 Skill 名称"""
        name_lower = subtask.name.lower()
        desc_lower = subtask.description.lower()

        # 关键词 → Skill 映射
        skill_mapping = {
            "前端": "frontend_designer",
            "后端": "code_reviewer",
            "api": "code_reviewer",
            "数据库": "code_reviewer",
            "联调": "test_generator",
            "测试": "test_generator",
            "审查": "code_reviewer",
            "重构": "code_reviewer",
            "设计": "design_blueprint",
            "文档": "self_documenter",
            "调研": "web_researcher",
            "辩驳": "info_debater",
            "报告": "office_generator",
            "数学": "math_solver",
            "可视化": "math_plotter",
            "图像": "image_processor",
        }

        for keyword, skill_name in skill_mapping.items():
            if keyword in name_lower or keyword in desc_lower:
                return skill_name

        return "code_reviewer"  # 默认 Skill

    def _get_skill_router(self):
        """获取 SkillRouter 实例（懒加载）"""
        try:
            from core.skills_registry import get_skills_registry
            return get_skills_registry()
        except Exception:
            return None

    def _create_stub_session_continuity(self):
        """创建轻量级 SessionContinuity 替代（避免硬依赖）"""
        class _StubSessionContinuity:
            def get_all_agents_status(self):
                return []
            def handoff_session(self, agent_id, summary=""):
                class _StubSession:
                    session_id = "stub"
                return _StubSession()
        return _StubSessionContinuity()

    def _create_stub_project_log(self):
        """创建轻量级 ProjectLog 替代（避免硬依赖）"""
        class _StubProjectLog:
            def log_project_init(self, *a, **kw):
                pass
            def log_project_start(self, *a, **kw):
                pass
            def log_project_pause(self, *a, **kw):
                pass
            def log_project_resume(self, *a, **kw):
                pass
            def log_project_complete(self, *a, **kw):
                pass
            def log(self, *a, **kw):
                pass
            def log_error(self, *a, **kw):
                pass
            def log_milestone(self, *a, **kw):
                pass
            def log_task_dispatched(self, *a, **kw):
                pass
            def log_agent_progress(self, *a, **kw):
                pass
            def log_agent_started(self, *a, **kw):
                pass
            def log_agent_completed(self, *a, **kw):
                pass
            def log_agent_failed(self, *a, **kw):
                pass
            def log_session_handed_off(self, *a, **kw):
                pass
        return _StubProjectLog()


# ============================================================================
# 全局实例
# ============================================================================

_global_superbrain: Optional[Superbrain] = None


def get_superbrain() -> Superbrain:
    """获取全局超级大脑实例"""
    global _global_superbrain
    if _global_superbrain is None:
        _global_superbrain = Superbrain()
    return _global_superbrain