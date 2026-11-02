# -*- coding: utf-8 -*-
"""
380B-2→381B-1: 预置计划模板库 — 编排器的弹药
======================================
381B-1: 从 5 域扩展到 18 域全覆盖。
18 域 = skill_domain_router._DOMAIN_RULES 的全部域名。
每域 ≥3 步，判据类型覆盖 artifact_exists / return_success / field_complete 三类。
通用两步模板(执行+汇报)用于未命中域。

接口：
    get_plan(domain, prompt) -> List[Dict]
    validate_templates() -> List[str]  # 自检，返回告警列表
"""

import json
import logging
from typing import Dict, List

_logger = logging.getLogger("plan_templates")

# 385B-3: 调研域前置"列目录快照"子步（纯代码执行，不耗模型轮次）。
# 产出注入后续各步 system prompt，消除"猜测路径首调失败"与本机目录误判。
# 单一常量 + 拷贝注入 research/generic/simple 短模板（防双源漂移）。
_DIR_SNAPSHOT_STEP: Dict = {
    "step_id": "dir_snapshot",
    "goal": "列目录快照（纯代码执行，产出注入后续步骤 system）",
    "candidate_skills": ["scan_project", "list_directory"],
    "criterion": {"type": "return_success", "description": "目录快照生成"},
    "code_exec": {"tool": "list_directory", "args": {"path": "."}},
}


def get_dir_snapshot_step() -> Dict:
    """385B-3: 返回目录快照子步深拷贝（供 simple 短模板动态前置）。"""
    return json.loads(json.dumps(_DIR_SNAPSHOT_STEP))


_PLAN_TEMPLATES: Dict[str, List[Dict]] = {
    "research": [
        dict(_DIR_SNAPSHOT_STEP),
        {
            "step_id": "research_search",
            "goal": "搜索并收集相关资料",
            "candidate_skills": ["deep_researcher", "super_researcher", "web_search", "web_fetch"],
            # 386B-1: 内容型判据 —— 搜索结果须含来源/链接特征
            # （386B-1 二轮：min_hits 2→1，web_search 摘要常只报条数不报 URL 样式）
            "criterion": {"type": "contains_keywords",
                          "list": ["http", "来源", "结果", "title", "标题", "url", "URL", "链接",
                                   "搜索", "资料"],
                          "min_hits": 1,
                          "description": "搜索结果含来源/链接特征词"},
        },
        {
            "step_id": "research_analyze",
            "goal": "分析资料并提取关键信息",
            "candidate_skills": ["read_file", "grep_search", "search_codebase"],
            "criterion": {"type": "field_complete", "field": "content", "description": "分析结果包含内容字段"},
        },
        {
            "step_id": "research_report",
            "goal": "整理分析结果，输出调研报告",
            "candidate_skills": ["write_file", "execute_code"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "报告文件已生成"},
        },
    ],
    "math": [
        {
            "step_id": "math_solve",
            "goal": "调用数学求解工具解方程/计算",
            "candidate_skills": ["math_solver", "execute_code"],
            "criterion": {"type": "return_success", "description": "求解工具返回成功结果"},
        },
        {
            "step_id": "math_verify",
            "goal": "验证计算结果是否正确",
            "candidate_skills": ["math_solver", "execute_code"],
            "criterion": {"type": "field_complete", "field": "result", "description": "结果字段非空"},
        },
        {
            "step_id": "math_visualize",
            "goal": "如需可视化则绘图",
            "candidate_skills": ["math_plotter"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "图像文件生成"},
        },
    ],
    "file_ops": [
        {
            "step_id": "file_scan",
            "goal": "扫描项目结构，定位目标文件",
            "candidate_skills": ["scan_project", "list_directory", "grep_search"],
            "criterion": {"type": "return_success", "description": "找到目标文件"},
        },
        {
            "step_id": "file_read",
            "goal": "读取目标文件内容",
            "candidate_skills": ["read_file"],
            "criterion": {"type": "field_complete", "field": "content", "description": "文件内容字段非空"},
        },
        {
            "step_id": "file_write",
            "goal": "修改/写入文件",
            "candidate_skills": ["write_file", "edit_file", "multi_edit"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "目标文件已写入"},
        },
        {
            "step_id": "file_verify",
            "goal": "验证写入结果",
            "candidate_skills": ["read_file"],
            "criterion": {"type": "return_success", "description": "验证文件内容正确"},
        },
    ],
    "code_review": [
        {
            "step_id": "review_scan",
            "goal": "扫描代码文件结构",
            "candidate_skills": ["scan_project", "read_file", "code_reviewer"],
            # 386B-1: 内容型判据 —— 扫描结果须含代码文件特征
            "criterion": {"type": "contains_keywords",
                          "list": [".py", ".js", ".ts", "文件", "file", "def ", "class ", "function"],
                          "min_hits": 1,
                          "description": "扫描结果含代码文件特征词"},
        },
        {
            "step_id": "review_analyze",
            "goal": "调用代码审查工具分析代码质量",
            "candidate_skills": ["code_reviewer", "grep_search", "execute_code"],
            "criterion": {"type": "field_complete", "field": "issues", "description": "审查结果含问题字段"},
        },
        {
            "step_id": "review_report",
            "goal": "输出审查报告",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "报告文件已生成"},
        },
    ],
    "system": [
        {
            "step_id": "system_info",
            "goal": "调用系统报告工具获取系统信息",
            "candidate_skills": ["system_report", "execute_code"],
            # 386B-1: 内容型判据 —— 系统报告必须含资源项关键词
            "criterion": {"type": "contains_keywords",
                          "list": ["CPU", "内存", "Memory", "磁盘", "Disk", "OS", "系统", "percent", "%"],
                          "min_hits": 2,
                          "description": "报告含 ≥2 个系统资源项关键词"},
        },
        {
            "step_id": "system_analyze",
            "goal": "分析系统状态，输出概况",
            "candidate_skills": ["execute_code", "write_file"],
            "criterion": {"type": "field_complete", "field": "CPU", "description": "报告包含关键字段"},
        },
        {
            "step_id": "system_report_file",
            "goal": "生成系统概况报告文件",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "报告文件已生成"},
        },
    ],
    "translate": [
        {
            "step_id": "translate_call",
            "goal": "调用翻译工具执行翻译",
            "candidate_skills": ["translator"],
            # 386B-1: 内容型判据 —— 结果须含实质译文文本（≥12 连续非空白字符）
            "criterion": {"type": "matches_regex",
                          "pattern": r"\S.{10,}",
                          "description": "结果含 ≥12 字符实质译文文本"},
        },
        {
            "step_id": "translate_verify",
            "goal": "验证翻译结果完整性",
            "candidate_skills": ["read_file"],
            "criterion": {"type": "field_complete", "field": "translated", "description": "翻译结果字段非空"},
        },
        {
            "step_id": "translate_save",
            "goal": "保存翻译结果到文件",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "翻译文件已保存"},
        },
    ],
    "academic": [
        {
            "step_id": "academic_search",
            "goal": "搜索相关学术论文",
            "candidate_skills": ["arxiv_researcher", "deep_researcher"],
            "criterion": {"type": "return_success", "description": "论文搜索成功"},
        },
        {
            "step_id": "academic_write",
            "goal": "生成学术风格文本",
            "candidate_skills": ["academic_writer"],
            "criterion": {"type": "field_complete", "field": "content", "description": "学术文本内容字段非空"},
        },
        {
            "step_id": "academic_save",
            "goal": "保存学术文档",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "学术文档已保存"},
        },
    ],
    "fact_check": [
        {
            "step_id": "factcheck_call",
            "goal": "调用事实核查工具",
            "candidate_skills": ["fact_checker"],
            "criterion": {"type": "return_success", "description": "核查工具返回成功"},
        },
        {
            "step_id": "factcheck_verify",
            "goal": "验证核查结果含可信度字段",
            "candidate_skills": ["read_file"],
            "criterion": {"type": "field_complete", "field": "credibility", "description": "含可信度字段"},
        },
        {
            "step_id": "factcheck_report",
            "goal": "输出核查报告",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "核查报告已生成"},
        },
    ],
    "testing": [
        {
            "step_id": "test_generate",
            "goal": "调用测试生成工具创建测试用例",
            "candidate_skills": ["test_generator"],
            "criterion": {"type": "return_success", "description": "测试生成成功"},
        },
        {
            "step_id": "test_run",
            "goal": "执行生成的测试",
            "candidate_skills": ["execute_code"],
            "criterion": {"type": "field_complete", "field": "output", "description": "测试输出非空"},
        },
        {
            "step_id": "test_report",
            "goal": "输出测试报告",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "测试报告文件已生成"},
        },
    ],
    "security": [
        {
            "step_id": "security_scan",
            "goal": "调用安全审计工具扫描代码",
            "candidate_skills": ["security_auditor"],
            "criterion": {"type": "return_success", "description": "安全扫描完成"},
        },
        {
            "step_id": "security_analyze",
            "goal": "分析漏洞详情",
            "candidate_skills": ["grep_search", "execute_code"],
            "criterion": {"type": "field_complete", "field": "vulnerabilities", "description": "漏洞字段非空"},
        },
        {
            "step_id": "security_report",
            "goal": "生成安全审计报告",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "安全报告已生成"},
        },
    ],
    "debate": [
        {
            "step_id": "debate_call",
            "goal": "调用辩论工具生成论点",
            "candidate_skills": ["info_debater", "multi_model_debater"],
            "criterion": {"type": "return_success", "description": "辩论工具返回成功"},
        },
        {
            "step_id": "debate_verify",
            "goal": "验证辩论结果完整性",
            "candidate_skills": ["read_file"],
            "criterion": {"type": "field_complete", "field": "arguments", "description": "论点字段非空"},
        },
        {
            "step_id": "debate_save",
            "goal": "保存辩论记录",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "辩论文件已保存"},
        },
    ],
    "requirement": [
        {
            "step_id": "req_amplify",
            "goal": "调用需求放大器扩展需求",
            "candidate_skills": ["requirement_amplifier", "design_blueprint"],
            "criterion": {"type": "return_success", "description": "需求放大成功"},
        },
        {
            "step_id": "req_validate",
            "goal": "验证需求文档关键字段完整",
            "candidate_skills": ["read_file", "grep_search"],
            "criterion": {"type": "field_complete", "field": "requirements", "description": "需求字段完整"},
        },
        {
            "step_id": "req_save",
            "goal": "保存需求文档",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "需求文档已保存"},
        },
    ],
    "finance": [
        {
            # 386B-2: finance 残留裸答治理 —— goal 明示必须调用工具（379 章裸答 MISS 根因）
            "step_id": "finance_calc",
            "goal": "调用 finance_assistant 工具执行财务计算（复利/利率/收益等），"
                    "纯数学部分才允许 math_solver；禁止不调工具直接口算作答",
            "candidate_skills": ["finance_assistant", "math_solver"],
            # 386B-1: 内容型判据 —— 财务结果须含金额/数值特征
            "criterion": {"type": "contains_keywords",
                          "list": ["金额", "amount", "计算", "结果", "￥", "$", "元", "利率", "收益", "成本"],
                          "min_hits": 1,
                          "description": "结果含金额/数值特征关键词"},
        },
        {
            "step_id": "finance_verify",
            "goal": "验证计算结果关键字段",
            "candidate_skills": ["execute_code"],
            "criterion": {"type": "field_complete", "field": "amount", "description": "金额字段非空"},
        },
        {
            "step_id": "finance_report",
            "goal": "输出财务分析报告",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "财务报告已生成"},
        },
    ],
    "frontend": [
        {
            "step_id": "frontend_design",
            "goal": "调用前端设计工具生成组件",
            "candidate_skills": ["frontend_designer"],
            "criterion": {"type": "return_success", "description": "前端组件生成成功"},
        },
        {
            "step_id": "frontend_preview",
            "goal": "预览生成结果",
            "candidate_skills": ["read_file"],
            "criterion": {"type": "field_complete", "field": "html", "description": "HTML字段非空"},
        },
        {
            "step_id": "frontend_save",
            "goal": "保存前端文件",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "HTML文件已保存"},
        },
    ],
    "code_analysis": [
        {
            "step_id": "analysis_read",
            "goal": "读取目标代码文件",
            "candidate_skills": ["read_file", "scan_project"],
            "criterion": {"type": "return_success", "description": "代码读取成功"},
        },
        {
            "step_id": "analysis_call",
            "goal": "调用代码分析工具解读代码意图",
            "candidate_skills": ["code_psychologist", "code_semantic_analyzer", "code_reviewer"],
            "criterion": {"type": "field_complete", "field": "analysis", "description": "分析结果字段非空"},
        },
        {
            "step_id": "analysis_report",
            "goal": "输出代码分析报告",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "分析报告已生成"},
        },
    ],
    "skill_create": [
        {
            "step_id": "skill_gen",
            "goal": "调用技能创建工具生成骨架",
            "candidate_skills": ["skill_creator"],
            "criterion": {"type": "return_success", "description": "技能骨架生成成功"},
        },
        {
            "step_id": "skill_validate",
            "goal": "验证技能代码结构完整",
            "candidate_skills": ["read_file", "grep_search"],
            "criterion": {"type": "field_complete", "field": "handler", "description": "handler字段存在"},
        },
        {
            "step_id": "skill_save",
            "goal": "保存技能文件",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "技能文件已保存"},
        },
    ],
    "office": [
        {
            "step_id": "office_gen",
            "goal": "调用办公工具生成文档",
            "candidate_skills": ["office_generator", "format_converter"],
            "criterion": {"type": "return_success", "description": "文档生成成功"},
        },
        {
            "step_id": "office_pdf",
            "goal": "读取/转换PDF内容",
            "candidate_skills": ["pdf_reader"],
            "criterion": {"type": "field_complete", "field": "text", "description": "文档内容字段非空"},
        },
        {
            "step_id": "office_save",
            "goal": "保存办公文档",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "文档文件已保存"},
        },
    ],
    "image": [
        {
            "step_id": "image_analyze",
            "goal": "调用图像分析工具识别图片",
            "candidate_skills": ["image_analyzer", "ocr_reader"],
            "criterion": {"type": "return_success", "description": "图像分析成功"},
        },
        {
            "step_id": "image_process",
            "goal": "处理/转换图像",
            "candidate_skills": ["image_processor"],
            "criterion": {"type": "field_complete", "field": "format", "description": "格式字段非空"},
        },
        {
            "step_id": "image_save",
            "goal": "保存图像处理结果",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "图像文件已保存"},
        },
    ],
    "code_playback": [
        {
            "step_id": "playback_scan",
            "goal": "扫描代码变更记录",
            "candidate_skills": ["scan_project", "grep_search"],
            "criterion": {"type": "return_success", "description": "变更扫描成功"},
        },
        {
            "step_id": "playback_gen",
            "goal": "生成代码回放/Diff展示",
            "candidate_skills": ["code_playback"],
            "criterion": {"type": "field_complete", "field": "diff", "description": "Diff结果字段非空"},
        },
        {
            "step_id": "playback_save",
            "goal": "保存回放结果",
            "candidate_skills": ["write_file"],
            "criterion": {"type": "artifact_exists", "path": "", "description": "回放文件已保存"},
        },
    ],
}

_GENERIC_PLAN: List[Dict] = [
    # 385B-3: 兜底模板同样前置目录快照子步（general 域调研防幻觉）
    dict(_DIR_SNAPSHOT_STEP),
    {
        "step_id": "generic_execute",
        "goal": "执行用户请求的核心操作",
        "candidate_skills": [],
        "criterion": {"type": "return_success", "description": "工具调用成功"},
    },
    {
        "step_id": "generic_report",
        "goal": "汇报执行结果",
        "candidate_skills": ["write_file", "execute_code"],
        "criterion": {"type": "return_success", "description": "结果汇报完成"},
    },
]

_MAPPED_DOMAINS: Dict[str, str] = {}


def get_plan(domain: str, prompt: str = "") -> List[Dict]:
    _actual = _MAPPED_DOMAINS.get(domain, domain)
    plan = _PLAN_TEMPLATES.get(_actual)
    if plan:
        return json.loads(json.dumps(plan))
    return json.loads(json.dumps(_GENERIC_PLAN))


def list_template_domains() -> List[str]:
    return sorted(set(list(_PLAN_TEMPLATES.keys()) + list(_MAPPED_DOMAINS.keys())))


def get_template_count() -> int:
    return len(_PLAN_TEMPLATES)


def validate_templates() -> List[str]:
    """381B-1.2: 模板自检函数。启动时校验结构完整性，坏模板降级为通用模板并告警。

    Returns:
        告警字符串列表（空=全部通过）
    """
    warnings = []
    _VALID_CRITERION_TYPES = {"artifact_exists", "return_success", "field_complete"}
    _REQUIRED_STEP_KEYS = {"step_id", "goal", "candidate_skills", "criterion"}
    _REQUIRED_CRITERION_KEYS = {"type", "description"}

    bad_domains = []
    for domain, steps in _PLAN_TEMPLATES.items():
        if not steps or len(steps) < 2:
            warnings.append(f"域 {domain}: 步骤数 <2 ({len(steps)})")
            bad_domains.append(domain)
            continue
        for i, step in enumerate(steps):
            missing_keys = _REQUIRED_STEP_KEYS - set(step.keys())
            if missing_keys:
                warnings.append(f"域 {domain} 步骤 {i}: 缺字段 {missing_keys}")
                bad_domains.append(domain)
                break
            criterion = step.get("criterion", {})
            if not isinstance(criterion, dict):
                warnings.append(f"域 {domain} 步骤 {i}: criterion 非dict")
                bad_domains.append(domain)
                break
            c_missing = _REQUIRED_CRITERION_KEYS - set(criterion.keys())
            if c_missing:
                warnings.append(f"域 {domain} 步骤 {i}: criterion 缺 {c_missing}")
                bad_domains.append(domain)
                break
            if criterion.get("type") not in _VALID_CRITERION_TYPES:
                warnings.append(f"域 {domain} 步骤 {i}: criterion.type='{criterion.get('type')}' 不合法")
                bad_domains.append(domain)
                break

    for domain in set(bad_domains):
        _logger.warning(f"[381B-1] 模板自检: 域 {domain} 降级为通用模板")
        _PLAN_TEMPLATES[domain] = json.loads(json.dumps(_GENERIC_PLAN))

    if warnings:
        _logger.warning(f"[381B-1] 模板自检告警: {warnings}")
    else:
        _logger.info(f"[381B-1] 模板自检通过: {len(_PLAN_TEMPLATES)} 域, 0 告警")

    return warnings
