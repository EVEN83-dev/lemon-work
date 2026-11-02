# -*- coding: utf-8 -*-
"""386B-4: 技能 schema 质量分层 —— 增补数据层（B 战区）
======================================================
背景：383B/385 直调实测 74 技能 → ARGCHECK 23（首轮参数校验失败需 dummy 重试）、
SKIP 13（环境依赖/危险操作不直调）。根因：schema 声明与 handler 签名脱节，
小模型按 schema 传参一次成功率低。

本层职责（不修改 skills/ 模块文件，注册后运行时注入）：
  1. ARGCHECK_EXAMPLES —— 23 个技能的参数示例（依据 handler 实测签名逐一生成），
     注入 SkillDef.description（模型可见）与 parameters.properties[x].example；
  2. SKIP_ANNOTATIONS —— 13 个环境依赖/危险操作技能标注 skip_reason，
     get_tool_definitions() 自动从默认技能菜单剔除（防小模型误选直调必败技能）。

单一入口：apply_overrides(registry) -> {"examples": n, "skips": m}
"""
import json
from typing import Dict

# ---- 386B-4: ARGCHECK 23 技能参数示例（依据 handler 实测签名生成）----
ARGCHECK_EXAMPLES: Dict[str, Dict] = {
    "web_researcher": {"query": "Python 3.13 新特性", "max_pages": 3,
                       "extract_text": True},
    "info_debater": {"sources": "https://a.com; https://b.com 的正文摘录",
                     "claim": "Python 是编译型语言", "mode": "compare"},
    "math_plotter": {"expression": "x**2 - 2*x + 1", "plot_type": "function",
                     "x_range": "-5,5", "output_path": "outputs/plot.png"},
    "office_generator": {"doc_type": "ppt", "title": "Lemon Code 简介",
                         "content": "要点1\n要点2\n要点3",
                         "output_path": "outputs/lemon.pptx"},
    "design_blueprint": {"diagram_type": "architecture",
                         "description": "Lemon Code 双体系 Agent 架构",
                         "components": "EngineManager, Orchestrator, SkillsRegistry",
                         "style": "default"},
    "code_reviewer": {"code": "def add(a, b):\n    return a + b",
                      "review_type": "all", "language": "python"},
    "test_generator": {"code": "def add(a, b):\n    return a + b",
                       "test_framework": "pytest"},
    "code_psychologist": {"description": "分析这段代码的设计意图",
                          "code": "def add(a, b):\n    return a + b",
                          "language": "python", "mode": "forward"},
    "web_fetch": {"url": "https://example.com"},
    "delete_file": {"file_paths": "outputs/tmp_result.txt"},
    "todo_write": {"todos": json.dumps([
        {"id": "1", "content": "调研", "status": "in_progress"}],
        ensure_ascii=False), "merge": False},
    "update_memory": {"action": "append", "section": "用户偏好",
                      "content": "偏好极简回复"},
    "stop_command": {"command_id": "cmd_1788712345"},
    "multi_edit": {"edits": json.dumps([
        {"old": "foo", "new": "bar"}], ensure_ascii=False), "atomic": True},
    "task_manager": {"action": "list"},
    "code_semantic_analyzer": {"code": "def add(a, b):\n    return a + b",
                               "language": "python", "output_format": "text"},
    "format_converter": {"input_content": "# 标题\n正文",
                         "input_format": "markdown", "output_format": "html"},
    "lsp_code_analysis": {"action": "workspace_symbol", "query": "main"},
    "mcp_bridge": {"action": "mcp_list_tools"},
    "ssh_skill": {"action": "list", "host": "192.168.1.10"},
    "docker_skill": {"action": "ps"},
    "npm_pip_skill": {"action": "pip_list", "tool": "pip"},
    "terminal_run": {"command": "echo hello", "cwd": "", "timeout": 30},
}

# ---- 386B-4: SKIP 13 技能标注（环境依赖/危险操作，理由来自 385 直调实测账）----
# ★389M-8 更正：deploy_helper 经真实签名直调 PASS（纯脚本生成器，非真实部署），
#   386B-4 的"危险操作"标注属误判 → 摘除 SKIP，恢复默认菜单可见。
SKIP_ANNOTATIONS: Dict[str, str] = {
    "html_to_video": "渲染转码依赖系统 ffmpeg（直调实测：ffmpeg 未装，requires_env）",
    "browser_automation": "需要 Playwright 浏览器内核（直调实测：chromium 未下载，requires_env）",
    "jupyter_notebook": "需要 nbformat/nbclient/ipykernel（直调实测：依赖未装，requires_env）",
    "git_skill": "可能对真实仓库执行写操作（危险操作）",
    "package_manager": "可能安装/卸载真实包（危险操作）",
    "disk_cleaner": "系统级清理，有真实删除风险（危险操作）",
    "virus_scanner": "全盘扫描耗时且占用系统资源（环境依赖）",
    "batch_renamer": "批量重命名有真实文件破坏风险（危险操作）",
    "duplicate_finder": "全盘扫描耗时（环境依赖）",
    "file_organizer": "移动/重组真实文件，破坏风险（危险操作）",
    "clipboard_helper": "读写系统剪贴板影响用户现场（环境依赖）",
    "autocheck_runner": "可能触发外部命令执行（危险操作）",
}


def apply_overrides(registry) -> Dict[str, int]:
    """把参数示例与 SKIP 标注注入注册表（注册完成后调用一次）。

    Returns:
        {"examples": 注入示例数, "skips": 标注数, "menu_removed": 菜单剔除数}
    """
    n_example = n_skip = 0
    for name, example in ARGCHECK_EXAMPLES.items():
        sd = registry._skills.get(name)
        if sd is None:
            continue
        try:
            example_str = json.dumps(example, ensure_ascii=False)
            # description 追加示例（模型可见 → 一次传参成功率）
            if "参数示例" not in sd.description:
                sd.description = (f"{sd.description} 参数示例: {example_str}")[:500]
            # schema properties 注入 example（工具定义可见）
            props = (sd.parameters or {}).get("properties", {})
            for k, v in example.items():
                if k in props and isinstance(props[k], dict):
                    props[k].setdefault("example", v)
            sd.argcheck_example = example
            n_example += 1
        except Exception:
            continue
    for name, reason in SKIP_ANNOTATIONS.items():
        sd = registry._skills.get(name)
        if sd is None:
            continue
        sd.skip_reason = reason
        n_skip += 1
    return {"examples": n_example, "skips": n_skip}
