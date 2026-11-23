# -*- coding: utf-8 -*-
import logging
logger = logging.getLogger(__name__)
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import os
import time
import math
import re
import threading
from collections import defaultdict


class AgentRoleType(Enum):
    ORCHESTRATOR = "orchestrator"
    FRONTEND = "frontend"
    BACKEND = "backend"
    TESTER = "tester"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"
    # ★ v8.1 (T2): 新角色必须有真实枚举值。get_builtin_roles() 按
    #   role_type != CUSTOM 过滤，偷懒写 "custom" 会让新角色从内置名册与
    #   团队展厅里凭空消失（不是报错，是静默不可见）。
    WRITER = "writer"
    ANALYST = "analyst"
    BROWSER = "browser"
    # ★ v10 (T3.1): 求职升学教练。同样必须先补枚举再建角色 ——
    #   get_builtin_roles() 按 role_type != CUSTOM 过滤，缺枚举会静默隐身。
    COACH = "coach"
    CUSTOM = "custom"


@dataclass
class AgentRoleDefinition:
    id: str
    name: str
    role_type: str
    description: str
    capabilities: List[str]
    skill_whitelist: List[str]
    input_spec: Dict[str, Any]
    output_spec: Dict[str, Any]
    max_token_budget: int
    timeout_seconds: int
    task_keywords: List[str]
    priority: int = 5
    color: str = ""
    icon_svg: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role_type": self.role_type,
            "description": self.description,
            "capabilities": self.capabilities,
            "skill_whitelist": self.skill_whitelist,
            "input_spec": self.input_spec,
            "output_spec": self.output_spec,
            "max_token_budget": self.max_token_budget,
            "timeout_seconds": self.timeout_seconds,
            "task_keywords": self.task_keywords,
            "priority": self.priority,
            "color": self.color,
            "icon_svg": self.icon_svg,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AgentRoleDefinition":
        return AgentRoleDefinition(
            id=data.get("id", ""),
            name=data.get("name", ""),
            role_type=data.get("role_type", "custom"),
            description=data.get("description", ""),
            capabilities=data.get("capabilities", []),
            skill_whitelist=data.get("skill_whitelist", []),
            input_spec=data.get("input_spec", {}),
            output_spec=data.get("output_spec", {}),
            max_token_budget=data.get("max_token_budget", 50000),
            timeout_seconds=data.get("timeout_seconds", 300),
            task_keywords=data.get("task_keywords", []),
            priority=data.get("priority", 5),
            color=data.get("color", ""),
            icon_svg=data.get("icon_svg", ""),
        )


_SKILL_CATEGORIES: Dict[str, List[str]] = {
    "core_file": ["read_file", "write_file", "edit_file", "delete_file", "multi_edit", "search_files", "list_directory", "grep_search", "search_codebase"],
    "core_project": ["scan_project", "query_knowledge_base"],
    "core_web": ["web_fetch", "web_search"],
    "core_system": ["run_command", "execute_code", "check_command_status", "stop_command", "todo_write", "update_memory"],
    "business_code": ["python_toolchain", "code_reviewer", "test_generator", "code_psychologist", "code_semantic_analyzer", "self_documenter", "lsp_code_analysis"],
    "business_research": ["web_researcher", "deep_researcher", "super_researcher", "arxiv_researcher", "fact_checker", "info_debater", "multi_model_debater"],
    "business_frontend": ["frontend_designer", "html_to_video", "design_blueprint"],
    "business_writing": ["academic_writer", "office_generator", "format_converter"],
    "business_media": ["image_processor", "image_analyzer"],
    "business_math": ["math_solver", "math_plotter"],
    "business_science": ["physics_experiment"],
    "business_security": ["security_auditor"],
    "business_devops": ["deploy_helper", "docker_skill", "npm_pip_skill", "ssh_skill", "mcp_bridge_skill"],
    "business_browser": ["browser_automation", "jupyter_notebook"],
    "business_system": ["skill_creator"],
    "version_specific": ["git_skill", "package_manager", "pdf_reader", "miemie_clone_analyze"],
}

_ORCHESTRATOR_SKILLS: List[str] = []
for _cat in _SKILL_CATEGORIES.values():
    _ORCHESTRATOR_SKILLS.extend(_cat)

_FRONTEND_SKILLS: List[str] = (
    _SKILL_CATEGORIES["core_file"]
    + _SKILL_CATEGORIES["core_project"]
    + _SKILL_CATEGORIES["core_system"]
    + _SKILL_CATEGORIES["business_code"]
    + _SKILL_CATEGORIES["business_frontend"]
    + _SKILL_CATEGORIES["business_writing"]
    + _SKILL_CATEGORIES["business_browser"]
)
_FRONTEND_SKILLS = [s for s in _FRONTEND_SKILLS if s not in ("delete_file", "stop_command", "run_command")]
# ★ 第19批（项 A6）: 四工位多模态白名单（只加白名单，不改 ACL 结构）
_MULTIMODAL_SKILLS = ["vision_chat", "image_analyzer"]
_FRONTEND_SKILLS = list(dict.fromkeys(_FRONTEND_SKILLS + _MULTIMODAL_SKILLS))

_BACKEND_SKILLS: List[str] = (
    _SKILL_CATEGORIES["core_file"]
    + _SKILL_CATEGORIES["core_project"]
    + _SKILL_CATEGORIES["core_system"]
    + _SKILL_CATEGORIES["business_code"]
    + _SKILL_CATEGORIES["business_devops"]
    + _SKILL_CATEGORIES["business_browser"]
    + _SKILL_CATEGORIES["version_specific"]
)
# ★ 第19批（项 A6）: 多模态白名单
_BACKEND_SKILLS = list(dict.fromkeys(list(_BACKEND_SKILLS) + _MULTIMODAL_SKILLS))

_TESTER_SKILLS: List[str] = (
    ["read_file", "write_file", "search_files", "grep_search", "list_directory", "search_codebase", "scan_project", "query_knowledge_base"]
    + ["run_command", "execute_code", "check_command_status", "todo_write"]
    + _SKILL_CATEGORIES["business_code"]
)
_TESTER_SKILLS = [s for s in _TESTER_SKILLS if s not in ("delete_file", "stop_command", "update_memory")]
_TESTER_SKILLS = list(dict.fromkeys(_TESTER_SKILLS + _MULTIMODAL_SKILLS))

_REVIEWER_SKILLS: List[str] = (
    ["read_file", "search_files", "grep_search", "list_directory", "search_codebase", "scan_project", "query_knowledge_base"]
    + _SKILL_CATEGORIES["business_code"]
    + _SKILL_CATEGORIES["business_security"]
)

_RESEARCHER_SKILLS: List[str] = (
    ["read_file", "search_files", "grep_search", "list_directory", "search_codebase", "scan_project", "query_knowledge_base"]
    # ★ 2026-11-23: 研究/阅读类角色补齐媒体阅读（PDF/图片/截图/视频关键帧）
    + ["pdf_reader", "image_analyzer", "vision_analyze", "video_reader"]
    + _SKILL_CATEGORIES["core_web"]
    + _SKILL_CATEGORIES["business_research"]
    + _SKILL_CATEGORIES["business_math"]
    + _SKILL_CATEGORIES["business_science"]
    + _SKILL_CATEGORIES["business_writing"]
    # ★ W20-4: researcher 记忆 + 成本路由
    + ["memory_write", "memory_recall", "memory_forget", "model_route"]
)

# ═══════════════════════════════════════════════════════════════
# ★ v8.1 (T2): 编排动作只给总管
#   _SKILL_CATEGORIES 里根本没有 spawn_subagent / orchestrator_dispatch，
#   故总管角色此前拿不到派发权 —— 白名单形同"谁都别想派活"。这里显式补齐。
#   分身侧由 engine_manager._NO_DELEGATE_TOOLS 强制剔除这两个动作（铁律 5）。
# ═══════════════════════════════════════════════════════════════
_ORCHESTRATION_SKILLS: List[str] = [
    "spawn_subagent", "orchestrator_dispatch", "agent_team_status",
]
# ★ W2: orchestrator 只加 crawl 读类 + stop（不给自己写类）
# ★ W20-4: orchestrator 记忆 + 并行子任务 + 成本路由
_ORCHESTRATOR_SKILLS = _ORCHESTRATOR_SKILLS + _ORCHESTRATION_SKILLS + [
    "crawl_start", "crawl_status", "crawl_pages", "crawl_page",
    "crawl_export", "crawl_stats", "crawl_annotations", "crawl_autotag",
    "crawl_stop",
    "memory_write", "memory_recall", "memory_forget",
    "subtask_parallel", "model_route",
]

# 写手：读上下文 + 落文档。文档是要写盘的，所以 write_file/edit_file 必须在列。
_READONLY_CORE_SKILLS: List[str] = [
    "read_file", "search_files", "grep_search", "list_directory",
    "search_codebase", "scan_project", "query_knowledge_base",
    # ★ 2026-11-23: 只读类角色也能读 PDF / 图片 / 截图
    "pdf_reader", "image_analyzer", "vision_analyze",
]
_WRITER_SKILLS: List[str] = (
    _READONLY_CORE_SKILLS
    + ["write_file", "edit_file", "multi_edit", "todo_write"]
    + ["doc_studio", "slide_studio", "paper_studio", "office_generator",
       "academic_writer", "format_converter", "pdf_reader",
       "save_artifact", "list_artifacts"]
    + _SKILL_CATEGORIES["core_web"]
)

# 数据分析师：v6 的三个量化技能尚未注册，此处只挂**真实存在**的技能。
# 把不存在的名字写进白名单不会报错，只会让"白名单里有"变成假象 —— 故单列 pending。
_ANALYST_PENDING_SKILLS: List[str] = ["data_analysis", "quant_history", "quant_backtest"]
# ★ W2: Crawl Engine 白名单（逐条白给，不用全集减法）
_CRAWL_READ = ["crawl_start", "crawl_status", "crawl_pages", "crawl_page",
               "crawl_export", "crawl_stats", "crawl_annotations",
               "crawl_autotag"]
_CRAWL_WRITE = ["crawl_pause", "crawl_resume", "crawl_stop",
                "crawl_annotate", "crawl_annotation_update",
                "crawl_annotation_delete", "crawl_watch_set",
                "crawl_watch_eval", "crawl_schedule", "crawl_rule_set"]

_ANALYST_SKILLS: List[str] = (
    _READONLY_CORE_SKILLS
    + ["execute_code", "jupyter_notebook", "math_solver", "math_plotter",
       "physics_experiment", "todo_write"]
    # ★ W2: analyst 放行量化/爬虫统计（只读类）
    + ["crawl_stats", "crawl_pages", "crawl_page", "crawl_export"]
    # ★ W9: analyst 补量化/回测
    + ["quant_quality_check", "quant_pit_query", "backtest_run",
       "quant_quality_card"]
    # ★ W20-4: analyst 记忆召回 + 成本路由
    + ["memory_recall", "model_route"]
)
# ★ 第19批（项 A6）: 多模态白名单
_ANALYST_SKILLS = list(dict.fromkeys(list(_ANALYST_SKILLS) + _MULTIMODAL_SKILLS))

# 浏览器操作员：抓取/巡检只读动作 + 巡检看板（crawler_dashboard 本身只读，见爬虫集群铁律）。
_BROWSER_SKILLS: List[str] = (
    _READONLY_CORE_SKILLS
    + ["browser_automation", "web_preview", "web_fetch", "web_search",
       "crawler_dashboard", "crawler_report", "bank_patrol_scan", "gig_wall_scan",
       "save_artifact", "list_artifacts"]
    # ★ W2: browser 获得 crawl 读+写类技能
    + _CRAWL_READ + _CRAWL_WRITE
)

# ═══════════════════════════════════════════════════════════════
# ★ v10 (T3.1): 求职升学教练。白名单**逐条白给**，不用"全集减法规则"，
#   因为减法式写法会因为新技能不断注册而意外扩权。
#   铁律 4③ + 铁律 5：无 write_file / edit_file / delete_file / run_command /
#   execute_code，也无 spawn_subagent / orchestrator_dispatch / agent_team_status。
#   engine_manager._NO_DELEGATE_TOOLS 会在执行链上再剔一次编排入口（双保险）。
#   注意：coach 需要"读简历文件"，但只给 read_file；落盘一律走 save_artifact
#   与 doc_studio（它们各自有确认与交付物审计），不给裸写文件权限。
# ═══════════════════════════════════════════════════════════════
_COACH_SKILLS: List[str] = [
    "career_kb_ingest", "career_kb_query", "career_kb_manage",
    "resume_studio", "interview_sim", "kaoyan_pack",
    "save_artifact", "list_artifacts", "doc_studio", "fact_checker",
    "read_file", "search_files", "grep_search", "list_directory",
    "query_knowledge_base", "browser_automation", "web_preview",
    # ★ W20-4: coach 记忆（不含并行子任务）
    "memory_recall", "memory_write",
]

_SVG_ORCHESTRATOR = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><line x1="12" y1="7" x2="5" y2="17"/><line x1="12" y1="7" x2="19" y2="17"/></svg>'
_SVG_FRONTEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>'
_SVG_BACKEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><circle cx="6" cy="6" r="1"/><circle cx="6" cy="18" r="1"/></svg>'
_SVG_TESTER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>'
_SVG_REVIEWER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
_SVG_RESEARCHER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>'
_SVG_WRITER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z"/></svg>'
_SVG_ANALYST = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="20" x2="21" y2="20"/><rect x="6" y="11" width="3" height="9"/><rect x="11.5" y="6" width="3" height="14"/><rect x="17" y="14" width="3" height="6"/></svg>'
_SVG_BROWSER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>'
_SVG_COACH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l7 4v6c0 4.4-3 8.4-7 10-4-1.6-7-5.6-7-10V6z"/><path d="M9 12l2 2 4-4"/></svg>'


_BUILTIN_ROLES: Dict[str, AgentRoleDefinition] = {
    "orchestrator": AgentRoleDefinition(
        id="orchestrator",
        name="主编排Agent",
        role_type=AgentRoleType.ORCHESTRATOR.value,
        description="理解用户意图，分解任务，调度子Agent，汇总结果",
        capabilities=["task_decomposition", "resource_allocation", "progress_tracking", "conflict_resolution", "decision_making"],
        skill_whitelist=_ORCHESTRATOR_SKILLS,
        input_spec={"type": "object", "properties": {"user_request": {"type": "string"}}},
        output_spec={"type": "object", "properties": {"plan": {"type": "object"}, "summary": {"type": "string"}}},
        max_token_budget=100000,
        timeout_seconds=600,
        task_keywords=["分配", "管理", "协调", "进度", "计划", "调度", "编排", "统筹", "orchestrate", "manage", "coordinate", "plan", "schedule"],
        priority=1,
        color="#FFB800",
        icon_svg=_SVG_ORCHESTRATOR,
    ),
    "frontend": AgentRoleDefinition(
        id="frontend",
        name="前端Agent",
        role_type=AgentRoleType.FRONTEND.value,
        description="专注HTML/CSS/JavaScript/React/Vue/ArkTS代码生成与UI组件开发",
        capabilities=["html_css", "javascript", "react", "vue", "tailwind", "responsive_design", "animation", "arkui", "component_design"],
        skill_whitelist=_FRONTEND_SKILLS,
        input_spec={"type": "object", "properties": {"task": {"type": "string"}, "framework": {"type": "string"}}},
        output_spec={"type": "object", "properties": {"files_created": {"type": "array"}, "code": {"type": "string"}}},
        max_token_budget=80000,
        timeout_seconds=300,
        task_keywords=["前端", "UI", "页面", "样式", "CSS", "HTML", "组件", "布局", "交互", "动效", "ArkUI", "ArkTS", "frontend", "component", "style", "widget"],
        priority=3,
        color="#4A9EFF",
        icon_svg=_SVG_FRONTEND,
    ),
    "backend": AgentRoleDefinition(
        id="backend",
        name="后端Agent",
        role_type=AgentRoleType.BACKEND.value,
        description="专注API设计、数据库操作、业务逻辑实现、服务端架构",
        capabilities=["python", "api_design", "database", "sql", "authentication", "performance", "architecture", "devops"],
        skill_whitelist=_BACKEND_SKILLS,
        input_spec={"type": "object", "properties": {"task": {"type": "string"}, "language": {"type": "string"}}},
        output_spec={"type": "object", "properties": {"endpoints": {"type": "array"}, "code": {"type": "string"}}},
        max_token_budget=80000,
        timeout_seconds=300,
        task_keywords=["后端", "API", "数据库", "接口", "服务", "业务逻辑", "SQL", "模型", "部署", "Docker", "backend", "api", "database", "server", "deploy"],
        priority=3,
        color="#3DDC84",
        icon_svg=_SVG_BACKEND,
    ),
    "tester": AgentRoleDefinition(
        id="tester",
        name="测试Agent",
        role_type=AgentRoleType.TESTER.value,
        description="专注测试用例生成、单元测试执行、覆盖率分析、质量验证",
        capabilities=["unit_test", "integration_test", "e2e_test", "performance_test", "bug_reporting", "coverage_analysis"],
        skill_whitelist=_TESTER_SKILLS,
        input_spec={"type": "object", "properties": {"target_files": {"type": "array"}, "test_type": {"type": "string"}}},
        output_spec={"type": "object", "properties": {"tests_written": {"type": "integer"}, "coverage": {"type": "number"}}},
        max_token_budget=60000,
        timeout_seconds=300,
        task_keywords=["测试", "验证", "用例", "回归", "覆盖率", "bug", "跑通", "断言", "test", "verify", "coverage", "assert", "pytest"],
        priority=4,
        color="#FF6B35",
        icon_svg=_SVG_TESTER,
    ),
    "reviewer": AgentRoleDefinition(
        id="reviewer",
        name="审查Agent",
        role_type=AgentRoleType.REVIEWER.value,
        description="专注代码审查、质量检查、安全漏洞扫描、性能分析",
        capabilities=["code_review", "lint", "static_analysis", "security_audit", "performance_review", "best_practices"],
        skill_whitelist=_REVIEWER_SKILLS,
        input_spec={"type": "object", "properties": {"files": {"type": "array"}, "check_type": {"type": "string"}}},
        output_spec={"type": "object", "properties": {"issues": {"type": "array"}, "score": {"type": "number"}}},
        max_token_budget=60000,
        timeout_seconds=180,
        task_keywords=["审查", "检查", "规范", "质量", "lint", "安全", "优化", "重构", "review", "audit", "quality", "refactor"],
        priority=4,
        color="#B366FF",
        icon_svg=_SVG_REVIEWER,
    ),
    "researcher": AgentRoleDefinition(
        id="researcher",
        name="研究Agent",
        role_type=AgentRoleType.RESEARCHER.value,
        description="专注文档阅读、API检索、技术方案调研、学术搜索",
        capabilities=["document_reading", "api_retrieval", "tech_research", "solution_design", "academic_search", "fact_checking"],
        skill_whitelist=_RESEARCHER_SKILLS,
        input_spec={"type": "object", "properties": {"topic": {"type": "string"}, "depth": {"type": "string"}}},
        output_spec={"type": "object", "properties": {"findings": {"type": "array"}, "recommendations": {"type": "string"}}},
        max_token_budget=80000,
        timeout_seconds=300,
        task_keywords=["调研", "文档", "API", "方案", "搜索", "研究", "论文", "arxiv", "research", "document", "investigate", "search", "paper"],
        priority=5,
        color="#4A9EFF",
        icon_svg=_SVG_RESEARCHER,
    ),
    # ═════════════════ v8.1 (T2) 增补三角色：只增不删，既有六角色原样保留 ═════════════════
    "writer": AgentRoleDefinition(
        id="writer",
        name="写手",
        role_type=AgentRoleType.WRITER.value,
        description="把调研结论和技术内容写成人能读的文档、报告、PPT 与论文初稿",
        capabilities=["document_writing", "report_drafting", "slides", "academic_draft",
                      "format_conversion", "artifact_saving"],
        skill_whitelist=_WRITER_SKILLS,
        input_spec={"type": "object", "properties": {
            "brief": {"type": "string"}, "doc_type": {"type": "string"}}},
        output_spec={"type": "object", "properties": {
            "path": {"type": "string"}, "summary": {"type": "string"}}},
        max_token_budget=80000,
        timeout_seconds=300,
        task_keywords=["写", "撰写", "写作", "成文", "文稿", "文档", "报告", "说明书",
                       "PPT", "幻灯片", "讲稿", "周报", "日报", "论文初稿", "排版",
                       "write", "draft", "document", "report", "slides", "deck"],
        priority=4,
        color="#22B8CF",
        icon_svg=_SVG_WRITER,
    ),
    "analyst": AgentRoleDefinition(
        id="analyst",
        name="数据分析师",
        role_type=AgentRoleType.ANALYST.value,
        description="跑数、算指标、画图表，把一堆数据变成能看懂的结论",
        capabilities=["data_profiling", "statistics", "charting", "notebook",
                      "quant_backtest_pending"],
        # 说明：v6 的 data_analysis / quant_history / quant_backtest 至今未注册
        #      （见 _ANALYST_PENDING_SKILLS），因此本白名单只列真实存在的技能，
        #      先挂 math_plotter / math_solver / execute_code / jupyter_notebook 顶上。
        skill_whitelist=_ANALYST_SKILLS,
        input_spec={"type": "object", "properties": {
            "dataset": {"type": "string"}, "question": {"type": "string"}}},
        output_spec={"type": "object", "properties": {
            "findings": {"type": "array"}, "charts": {"type": "array"}}},
        max_token_budget=70000,
        timeout_seconds=300,
        task_keywords=["分析", "数据", "统计", "指标", "图表", "可视化", "趋势", "占比",
                       "回归", "回测", "量化", "跑数", "样本", "分布",
                       "analyze", "analysis", "data", "chart", "metrics", "statistics"],
        priority=5,
        color="#F783AC",
        icon_svg=_SVG_ANALYST,
    ),
    "browser": AgentRoleDefinition(
        id="browser",
        name="浏览器操作员",
        role_type=AgentRoleType.BROWSER.value,
        description="开浏览器抓页面、点流程、截图，并盯爬虫巡检与任务墙",
        capabilities=["page_automation", "screenshot", "web_capture",
                      "crawler_patrol", "gig_wall_watch"],
        skill_whitelist=_BROWSER_SKILLS,
        input_spec={"type": "object", "properties": {
            "url": {"type": "string"}, "steps": {"type": "string"}}},
        output_spec={"type": "object", "properties": {
            "captured": {"type": "array"}, "report": {"type": "string"}}},
        max_token_budget=60000,
        timeout_seconds=300,
        task_keywords=["抓取", "爬取", "爬", "采集", "网页", "浏览器", "打开网页", "访问",
                       "截图", "点击", "表单", "巡检", "盯单", "任务墙",
                       "scrape", "crawl", "browser", "screenshot", "automate", "patrol"],
        priority=5,
        color="#7048E8",
        icon_svg=_SVG_BROWSER,
    ),
    # ═════════════════ v10 (T3.1) 第 10 角色：求职升学教练 ═════════════════
    "coach": AgentRoleDefinition(
        id="coach",
        name="求职升学教练",
        role_type=AgentRoleType.COACH.value,
        description="陪你改简历、攒面经、模拟面试和考研复试，直说问题不客套",
        capabilities=["resume_jd_gap_analysis", "interview_experience_retrieval",
                      "mock_interview", "star_rewrite", "followup_drill",
                      "scorecard_feedback", "postgrad_interview_pack"],
        skill_whitelist=_COACH_SKILLS,
        input_spec={"type": "object", "properties": {
            "goal": {"type": "string"}, "position": {"type": "string"},
            "company": {"type": "string"}}},
        output_spec={"type": "object", "properties": {
            "questions": {"type": "array"}, "scorecard": {"type": "object"}}},
        max_token_budget=80000,
        timeout_seconds=600,
        task_keywords=["简历", "面经", "面试", "求职", "模拟面试", "压力面", "反问",
                       "STAR", "复试", "考研", "调剂", "导师", "自我介绍", "个人陈述",
                       "改简历", "投递", "薪资谈判", "interview", "resume",
                       "mock interview", "job", "graduate"],
        priority=4,
        color="#FF8FB1",
        icon_svg=_SVG_COACH,
    ),
}


class _SimpleTokenizer:
    @staticmethod
    def tokenize(text: str) -> List[str]:
        tokens: List[str] = []
        for ch in text:
            if '\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf':
                tokens.append(ch)
        words = re.findall(r'[a-zA-Z]+', text.lower())
        tokens.extend(words)
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        for i in range(len(chinese_chars) - 1):
            tokens.append(chinese_chars[i] + chinese_chars[i + 1])
        return tokens


class _TFIDFMatcher:
    def __init__(self):
        self._idf: Dict[str, float] = {}
        self._vectors: Dict[str, Dict[str, float]] = {}
        self._tokenizer = _SimpleTokenizer()
        self._fitted = False

    def fit(self, role_texts: Dict[str, str]) -> None:
        doc_count = len(role_texts)
        if doc_count == 0:
            return
        df: Dict[str, int] = defaultdict(int)
        tokenized: Dict[str, Dict[str, int]] = {}
        for role_id, text in role_texts.items():
            tokens = self._tokenizer.tokenize(text)
            tf: Dict[str, int] = defaultdict(int)
            for t in tokens:
                tf[t] += 1
            tokenized[role_id] = dict(tf)
            for t in set(tokens):
                df[t] += 1
        self._idf = {t: math.log((doc_count + 1) / (freq + 1)) + 1 for t, freq in df.items()}
        self._vectors = {}
        for role_id, tf in tokenized.items():
            total = max(sum(tf.values()), 1)
            vec: Dict[str, float] = {}
            for t, count in tf.items():
                if t in self._idf:
                    vec[t] = (count / total) * self._idf[t]
            self._vectors[role_id] = vec
        self._fitted = True

    def match(self, query: str, top_k: int = 3) -> List[Tuple[str, float]]:
        if not self._fitted:
            return []
        tokens = self._tokenizer.tokenize(query)
        tf: Dict[str, int] = defaultdict(int)
        for t in tokens:
            tf[t] += 1
        total = max(sum(tf.values()), 1)
        qvec: Dict[str, float] = {}
        for t, count in tf.items():
            if t in self._idf:
                qvec[t] = (count / total) * self._idf[t]
        scores: List[Tuple[str, float]] = []
        for role_id, rvec in self._vectors.items():
            scores.append((role_id, self._cosine(qvec, rvec)))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    @staticmethod
    def _cosine(v1: Dict[str, float], v2: Dict[str, float]) -> float:
        dot = sum(v1.get(k, 0) * v2.get(k, 0) for k in set(v1) | set(v2))
        n1 = math.sqrt(sum(v * v for v in v1.values()))
        n2 = math.sqrt(sum(v * v for v in v2.values()))
        if n1 == 0 or n2 == 0:
            return 0.0
        return dot / (n1 * n2)


class RoleMatcher:
    KEYWORD_WEIGHT = 0.6
    SEMANTIC_WEIGHT = 0.4

    def __init__(self, roles: Dict[str, AgentRoleDefinition]):
        self._roles = roles
        self._tfidf = _TFIDFMatcher()
        self._build_index()

    def _build_index(self) -> None:
        role_texts: Dict[str, str] = {}
        for role_id, role in self._roles.items():
            parts = [role.description] + role.task_keywords + role.capabilities
            role_texts[role_id] = " ".join(parts)
        self._tfidf.fit(role_texts)

    def rebuild_index(self, roles: Dict[str, AgentRoleDefinition]) -> None:
        self._roles = roles
        self._build_index()

    def match(self, task_description: str, top_k: int = 3, exclude_roles: Optional[List[str]] = None) -> List[Tuple[str, float]]:
        exclude = set(exclude_roles or [])
        kw_scores = self._keyword_match(task_description)
        sem_scores = self._semantic_match(task_description, top_k=len(self._roles))
        all_ids = set(kw_scores.keys()) | set(sem_scores.keys())
        combined: List[Tuple[str, float]] = []
        for rid in all_ids:
            if rid in exclude:
                continue
            if rid not in self._roles:
                continue
            kw = kw_scores.get(rid, 0.0)
            sem = sem_scores.get(rid, 0.0)
            combined.append((rid, self.KEYWORD_WEIGHT * kw + self.SEMANTIC_WEIGHT * sem))
        combined.sort(key=lambda x: x[1], reverse=True)
        return combined[:top_k]

    def match_best(self, task_description: str) -> Optional[AgentRoleDefinition]:
        results = self.match(task_description, top_k=1)
        if results:
            return self._roles.get(results[0][0])
        return None

    def _keyword_match(self, task_description: str) -> Dict[str, float]:
        task_lower = task_description.lower()
        scores: Dict[str, float] = {}
        for role_id, role in self._roles.items():
            score = 0.0
            for kw in role.task_keywords:
                if kw.lower() in task_lower:
                    score += 1.0
            for cap in role.capabilities:
                if cap.lower() in task_lower:
                    score += 0.5
            if score > 0:
                scores[role_id] = score / max(len(role.task_keywords), 1)
        return scores

    def _semantic_match(self, task_description: str, top_k: int = 3) -> Dict[str, float]:
        results = self._tfidf.match(task_description, top_k=top_k)
        max_score = max((s for _, s in results), default=0.0)
        if max_score == 0:
            return {}
        return {rid: s / max_score for rid, s in results}


class RoleSkillGuard:
    def __init__(self, roles: Dict[str, AgentRoleDefinition]):
        self._roles = roles

    def check(self, role_id: str, skill_name: str) -> Dict[str, Any]:
        role = self._roles.get(role_id)
        if not role:
            return {"allowed": False, "reason": f"Role '{role_id}' not found"}
        if not role.skill_whitelist:
            return {"allowed": True, "reason": "No whitelist restriction"}
        if skill_name in role.skill_whitelist:
            return {"allowed": True, "reason": f"Skill '{skill_name}' in whitelist for role '{role.name}'"}
        return {"allowed": False, "reason": f"Skill '{skill_name}' not allowed for role '{role.name}' (whitelist: {len(role.skill_whitelist)} skills)"}

    def filter_skills(self, role_id: str, requested_skills: List[str]) -> Dict[str, Any]:
        role = self._roles.get(role_id)
        if not role:
            return {"allowed": [], "denied": requested_skills, "reason": f"Role '{role_id}' not found"}
        if not role.skill_whitelist:
            return {"allowed": requested_skills, "denied": [], "reason": "No whitelist restriction"}
        allowed = [s for s in requested_skills if s in role.skill_whitelist]
        denied = [s for s in requested_skills if s not in role.skill_whitelist]
        return {"allowed": allowed, "denied": denied, "reason": f"Filtered {len(allowed)}/{len(requested_skills)} skills"}


class RoleManager:
    def __init__(self, roles_dir: str = ""):
        self.roles: Dict[str, AgentRoleDefinition] = dict(_BUILTIN_ROLES)
        self._custom_roles_dir = roles_dir or os.path.join(
            os.path.expanduser("~"), ".lemoncode", "data", "agent_roles"
        )
        self._matcher = RoleMatcher(self.roles)
        self._guard = RoleSkillGuard(self.roles)
        self._lock = threading.Lock()

    def get_role(self, role_id: str) -> Optional[AgentRoleDefinition]:
        return self.roles.get(role_id)

    def get_all_roles(self) -> Dict[str, AgentRoleDefinition]:
        return dict(self.roles)

    def get_builtin_roles(self) -> Dict[str, AgentRoleDefinition]:
        return {k: v for k, v in self.roles.items() if v.role_type != AgentRoleType.CUSTOM.value}

    def get_custom_roles(self) -> Dict[str, AgentRoleDefinition]:
        return {k: v for k, v in self.roles.items() if v.role_type == AgentRoleType.CUSTOM.value}

    def create_custom_role(self, role: AgentRoleDefinition) -> bool:
        with self._lock:
            if role.id in _BUILTIN_ROLES:
                return False
            role.role_type = AgentRoleType.CUSTOM.value
            self.roles[role.id] = role
            self._rebuild_matcher()
            self._save_custom_role(role)
        return True

    def update_custom_role(self, role_id: str, updates: Dict[str, Any]) -> bool:
        with self._lock:
            if role_id in _BUILTIN_ROLES:
                return False
            role = self.roles.get(role_id)
            if not role or role.role_type != AgentRoleType.CUSTOM.value:
                return False
            for key, value in updates.items():
                if hasattr(role, key):
                    setattr(role, key, value)
            self._rebuild_matcher()
            self._save_custom_role(role)
        return True

    def delete_custom_role(self, role_id: str) -> bool:
        with self._lock:
            if role_id in _BUILTIN_ROLES:
                return False
            if role_id in self.roles:
                del self.roles[role_id]
                self._rebuild_matcher()
                self._delete_custom_role_file(role_id)
                return True
        return False

    def match_roles(self, task_description: str, top_k: int = 3, exclude_roles: Optional[List[str]] = None) -> List[Tuple[str, float]]:
        return self._matcher.match(task_description, top_k, exclude_roles)

    def match_best_role(self, task_description: str) -> Optional[AgentRoleDefinition]:
        return self._matcher.match_best(task_description)

    def route_task(self, task_description: str) -> List[str]:
        results = self._matcher.match(task_description, top_k=len(self.roles))
        return [r[0] for r in results if r[1] > 0]

    def can_use_skill(self, role_id: str, skill_name: str) -> bool:
        return self._guard.check(role_id, skill_name)["allowed"]

    def check_skill(self, role_id: str, skill_name: str) -> Dict[str, Any]:
        return self._guard.check(role_id, skill_name)

    def filter_skills(self, role_id: str, requested_skills: List[str]) -> Dict[str, Any]:
        return self._guard.filter_skills(role_id, requested_skills)

    def get_role_responsibilities(self, role_id: str) -> List[str]:
        role = self.get_role(role_id)
        return role.capabilities if role else []

    def get_role_skills(self, role_id: str) -> List[str]:
        role = self.get_role(role_id)
        return role.skill_whitelist if role else []

    def format_report(self, role_id: str, **kwargs) -> str:
        role = self.get_role(role_id)
        if not role:
            return ""
        return role.description

    def get_role_color(self, role_id: str) -> str:
        role = self.get_role(role_id)
        return role.color if role else "#888888"

    def get_role_icon(self, role_id: str) -> str:
        role = self.get_role(role_id)
        return role.icon_svg if role else ""

    def export_role(self, role_id: str) -> Optional[str]:
        role = self.roles.get(role_id)
        if not role:
            return None
        return json.dumps(role.to_dict(), ensure_ascii=False, indent=2)

    def import_role(self, json_str: str) -> Optional[AgentRoleDefinition]:
        try:
            data = json.loads(json_str)
            role = AgentRoleDefinition.from_dict(data)
            with self._lock:
                self.roles[role.id] = role
                if role.role_type == AgentRoleType.CUSTOM.value:
                    self._save_custom_role(role)
                self._rebuild_matcher()
            return role
        except Exception:
            return None

    def load_custom_roles(self) -> int:
        if not os.path.exists(self._custom_roles_dir):
            return 0
        count = 0
        for fname in os.listdir(self._custom_roles_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(self._custom_roles_dir, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                role = AgentRoleDefinition.from_dict(data)
                role.role_type = AgentRoleType.CUSTOM.value
                with self._lock:
                    self.roles[role.id] = role
                count += 1
            except Exception:
                logger.debug("suppressed exception")
        if count > 0:
            self._rebuild_matcher()
        return count

    def get_skill_categories(self) -> Dict[str, List[str]]:
        return dict(_SKILL_CATEGORIES)

    def _rebuild_matcher(self) -> None:
        self._matcher = RoleMatcher(self.roles)
        self._guard = RoleSkillGuard(self.roles)

    def _save_custom_role(self, role: AgentRoleDefinition) -> None:
        os.makedirs(self._custom_roles_dir, exist_ok=True)
        path = os.path.join(self._custom_roles_dir, role.id + ".json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(role.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            logger.debug("suppressed exception")

    def _delete_custom_role_file(self, role_id: str) -> None:
        path = os.path.join(self._custom_roles_dir, role_id + ".json")
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                logger.debug("suppressed exception")


_global_role_manager: Optional[RoleManager] = None
_manager_lock = threading.Lock()


def get_role_manager() -> RoleManager:
    global _global_role_manager
    if _global_role_manager is None:
        with _manager_lock:
            if _global_role_manager is None:
                _global_role_manager = RoleManager()
                _global_role_manager.load_custom_roles()
    return _global_role_manager


ROLE_DEFINITIONS = {k: v for k, v in _BUILTIN_ROLES.items()}
