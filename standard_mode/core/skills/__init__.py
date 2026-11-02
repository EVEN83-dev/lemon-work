# -*- coding: utf-8 -*-
"""
Lemon Code Agent — Skills 技能包
=================================
每个子模块实现一个独立的业务 Skill，通过 register() 函数
向 SkillsRegistry 注册 SkillDef。

技能列表（39 个）：
  math_solver, web_researcher, info_debater, math_plotter,
  office_generator, image_processor, self_documenter,
  arxiv_researcher, design_blueprint, physics_experiment,
  image_analyzer, academic_writer, skill_creator,
  frontend_designer, deep_researcher, fact_checker,
  html_to_video, modern_python_toolchain, super_researcher,
  code_reviewer, test_generator, security_auditor,
  deploy_helper, code_psychologist, multi_model_debater,
  requirement_amplifier,
  browser_automation, jupyter_notebook,  # v0.8.0 新增
  finance_assistant,  # v1.0.0 新增
"""

import os
import importlib
from typing import List

# 所有技能模块名（与文件名一致，不含 .py）
SKILL_MODULES = [
    "math_solver",
    "web_researcher",
    "info_debater",
    "math_plotter",
    "office_generator",
    "image_processor",
    "self_documenter",
    "arxiv_researcher",
    "design_blueprint",
    "physics_experiment",
    "image_analyzer",
    "academic_writer",
    "skill_creator",
    "frontend_designer",
    "deep_researcher",
    "fact_checker",
    "html_to_video",
    "modern_python_toolchain",
    "super_researcher",
    "code_reviewer",
    "test_generator",
    "security_auditor",
    "deploy_helper",
    "code_psychologist",
    "multi_model_debater",
    "requirement_amplifier",
    # v0.8.0 新增
    "browser_automation",
    "jupyter_notebook",
    # v0.9.0 新增
    "git_skill",
    "package_manager",
    # v1.0.0 新增
    "finance_assistant",
    "code_playback",
    # v4.8.6 364章新增 (PC工具Skill包)
    "translator",
    "ocr_reader",
    "disk_cleaner",
    "virus_scanner",
    "batch_renamer",
    "duplicate_finder",
    "file_organizer",
    "system_report",
    "clipboard_helper",
    "screenshot_qa",
    "autocheck_runner",
    # 378-1 点亮：pdf_reader（pdfplumber 依赖已装，模块有 register，此前未入清单一直沉睡）
    "pdf_reader",
    # 394A-2 新增：模板生产管线（agent 算力产模板）
    "template_forge",
    # 394A-4 新增：JSON Resume 渲染器（数据/样式分离样板）
    "resume_renderer",
    # 394C-1 转正技能追加区（skill_creator formalize 自动维护）
]


def register_skills(registry) -> int:
    """将所有 Skills 注册到 SkillsRegistry

    Args:
        registry: SkillsRegistry 实例

    Returns:
        注册成功的 skill 数量
    """
    count = 0
    pkg_dir = os.path.dirname(os.path.abspath(__file__))

    for mod_name in SKILL_MODULES:
        try:
            # 动态导入子模块
            module = importlib.import_module(f".{mod_name}", package="core.skills")
            if hasattr(module, "register"):
                module.register(registry)
                count += 1
            else:
                print(f"[skills] {mod_name} 缺少 register() 函数，跳过")
        except Exception as e:
            print(f"[skills] 注册 {mod_name} 失败: {e}")

    print(f"[skills] 已注册 {count}/{len(SKILL_MODULES)} 个技能")
    return count


def list_available_skills() -> List[dict]:
    """列出所有可用技能的元信息（不注册）"""
    skills_info = []
    pkg_dir = os.path.dirname(os.path.abspath(__file__))

    for mod_name in SKILL_MODULES:
        try:
            module = importlib.import_module(f".{mod_name}", package="core.skills")
            if hasattr(module, "get_metadata"):
                skills_info.append(module.get_metadata())
        except Exception:
            pass

    return skills_info
