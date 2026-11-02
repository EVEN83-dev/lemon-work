# -*- coding: utf-8 -*-
"""
Lemon Code 模式状态报告 — 标准模式 vs 混合模式
================================================
全面分析两种模式的当前状态、历史问题、已知缺陷和未来规划。
"""

from typing import Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum


class ModeStatus(Enum):
    STABLE = "stable"           # 稳定运行
    DEGRADED = "degraded"       # 功能退化
    BROKEN = "broken"           # 已损坏
    FROZEN = "frozen"           # 已锁定
    PLANNED = "planned"         # 规划中


@dataclass
class ModeInfo:
    """模式信息"""
    name: str
    status: ModeStatus
    description: str
    core_files: List[str]
    engines: List[str]
    features: List[str]
    known_issues: List[str]
    resolved_issues: List[str]
    future_plans: List[str]


# ============================================================
# 标准模式
# ============================================================

STANDARD_MODE = ModeInfo(
    name="标准模式 (Standard Mode)",
    status=ModeStatus.FROZEN,
    description="原始 MIMO Code 集成模式，通过 Process Bridge 与 mimo.exe 通信，使用 QWebEngine 渲染前端。已锁定，防止混合模式开发破坏。",
    core_files=[
        "standard_mode/main.py",
        "standard_mode/core/serve_bridge.py",
        "standard_mode/core/engine_manager.py",
        "standard_mode/core/agent_engine.py",
        "standard_mode/ui/mimo_panel.py",
        "standard_mode/ui/mimo_page.html",
        "standard_mode/core/process_bridge.py",
        "standard_mode/core/acp_bridge.py",
    ],
    engines=["MiMoCode (主力)", "Ollama (本地)", "DeepSeek (云端)", "LM Studio (实验)"],
    features=[
        "MIMO Code 进程桥接通信",
        "Ollama/DeepSeek 多引擎切换",
        "42 个 Skill 系统",
        "右侧 Skill 可视化面板",
        "代码 Diff 块级渲染",
        "打字机变速输出 + 辉光光标",
        "函数图像/3D 几何体渲染",
        "消息搜索 + 导出",
        "底部状态栏 (引擎/内存/FPS)",
        "全局快捷键系统",
        "崩溃恢复 + 看门狗",
        "Few-Shot 蒸馏自进化",
        "Agent 角色系统（v4.7 已集成到 UI + 聊天流程）",
        "插件市场（v4.8 已本地化：离线目录+本地创建+可选远程）",
        "国际化（v4.8 已完成：100% UI 硬编码字符串替换为 i18n）",
    ],
    known_issues=[],
    resolved_issues=[
        "B4: num_predict=100 → 1500 (qwen3.5:4b 思考模型修复)",
        "B5: IPv6 localhost → 127.0.0.1 (全项目统一)",
        "B6: HTTP 连接泄漏 → Session 管理",
        "B7: 混合模式后台线程崩溃 → 生命周期管理",
        "B8: SSE 连接重复 → 单例管理",
        "B9: 蒸馏链路不完整 → 7步闭环",
        "B13: StreamOptimizer 首次刷新卡顿",
        "B14: 拓扑排序方向错误",
        "B15: 依赖字段类型兼容性",
        "B12: Agent 角色未集成到前端 → v4.7 已集成（命令面板+角色选择器+状态栏显示）",
        "B1: 底部状态栏始终显示 MIMO → v4.7 已修复（显示当前引擎+角色）",
        "B2: MIMO 引擎状态不一致 → v4.7 已明确区分语义",
        "B10: 插件市场远程 API → v4.8 已本地化（离线目录+本地创建向导，远程可选）",
        "B11: 国际化翻译文件 → v4.8 已补全（100% UI 硬编码字符串替换）",
        "B3: DeepSeek 发送路径 → v4.8 已配置 API Key（本地密钥文件）",
    ],
    future_plans=[
        "P10: 节日主题系统（暂缓）",
        "P19: 协作功能（长期）",
        "Lemon AI Engine 集成",
        "Agent 角色前端渲染",
        "代码健康度仪表盘",
        "项目时间线",
    ],
)


# ============================================================
# 混合模式
# ============================================================

HYBRID_MODE = ModeInfo(
    name="混合模式 (Hybrid Mode)",
    status=ModeStatus.DEGRADED,
    description="多 Agent 协作模式，模拟公司运转。多个 AI Agent 同时工作，协作编码。因标准模式锁定策略，混合模式开发暂停，部分功能待修复。",
    core_files=[
        "hybrid_mode/core/hybrid_mode_bridge.py",
        "hybrid_mode/core/agent_container.py",
        "hybrid_mode/core/single_ai_multi_window.py",
        "hybrid_mode/core/multi_ai_panel.py",
    ],
    engines=["Ollama (本地)", "DeepSeek (云端)"],
    features=[
        "多 Agent 协作（10 种角色 SVG）",
        "公司运转模拟",
        "Agent 卡片持久化",
        "超级大脑调度",
        "Token 管理",
        "任务分配",
    ],
    known_issues=[
        "H1: 后台线程在面板隐藏后继续运行 → RuntimeError",
        "H2: 混合模式修改影响标准模式（mimo_panel.py 注入）",
        "H3: sendAgentChatV18 仍用 setTimeout 模拟",
        "H4: 多个文件独立实现 Ollama 调用（未走 EngineManager）",
        "H5: 前端 XMLHttpRequest 直接调用 Ollama（应走 PyBridge）",
        "H6: Agent 卡片固定 220x200，不可定制",
        "H7: 混合模式启动时可能触发 mimo.exe 崩溃",
    ],
    resolved_issues=[
        "H8: 数据全硬编码 → 部分接入真实 AI",
        "H9: 11 个 AI 调用点接入真实 Ollama",
        "H10: IPv6 localhost → 127.0.0.1",
    ],
    future_plans=[
        "统一 AI 调用入口（EngineManager）",
        "修复后台线程生命周期",
        "真实 Agent 协作调度",
        "与标准模式共享 Skill 系统",
    ],
)


# ============================================================
# 模式隔离规则
# ============================================================

MODE_ISOLATION_RULES = [
    "禁止混合模式修改标准模式文件",
    "所有 AI 调用必须经过 EngineManager",
    "混合模式 AI 引擎禁止绕过 EngineManager",
    "标准模式稳定后禁止混合模式改动",
    "新增 AI 入口必须走 shared/engine_manager",
]


# ============================================================
# 历史问题总结（项目级）
# ============================================================

@dataclass
class ProjectIssue:
    """项目级问题"""
    issue_id: str
    title: str
    category: str          # 架构/连接/模型/UI/性能
    severity: str          # 致命/严重/一般/轻微
    root_cause: str
    solution: str
    status: str            # 已解决/已知/待修复
    recurrence_risk: str   # 复发风险
    lesson: str


PROJECT_ISSUES: List[ProjectIssue] = [
    ProjectIssue(
        issue_id="PJ-001",
        title="思考模型 token 不足导致空回复",
        category="模型",
        severity="致命",
        root_cause="qwen3.5:4b 是思考模型，num_predict=100 全部消耗在推理过程",
        solution="num_predict 100 → 1500，全项目 7 文件统一",
        status="已解决 (v3.15)",
        recurrence_risk="低（已标准化为 1500）",
        lesson="思考模型需要更大的 num_predict，绝不能小于 1000",
    ),
    ProjectIssue(
        issue_id="PJ-002",
        title="IPv6 连接问题导致 Ollama 不可用",
        category="连接",
        severity="严重",
        root_cause="localhost 优先解析为 IPv6 ::1，Ollama 默认监听 IPv4 127.0.0.1",
        solution="所有 localhost 改为 127.0.0.1（16 处）",
        status="已解决 (v3.14)",
        recurrence_risk="中（新文件可能使用 localhost）",
        lesson="统一使用 127.0.0.1，避免 localhost",
    ),
    ProjectIssue(
        issue_id="PJ-003",
        title="HTTP 连接泄漏 (CLOSE_WAIT)",
        category="连接",
        severity="严重",
        root_cause="模块级 requests.get/post 无 Session 管理",
        solution="使用 requests.Session() 统一管理连接",
        status="已解决 (v3.20)",
        recurrence_risk="低（已建立 Session 模式）",
        lesson="HTTP 请求必须使用 Session 管理",
    ),
    ProjectIssue(
        issue_id="PJ-004",
        title="混合模式后台线程崩溃导致标准模式不可用",
        category="架构",
        severity="致命",
        root_cause="混合模式面板隐藏后后台线程继续运行，访问已删除的 Qt 对象",
        solution="混合模式独立生命周期管理，不修改标准模式文件",
        status="已知 (v3.30)",
        recurrence_risk="高（混合模式未完全隔离）",
        lesson="标准模式和混合模式必须永久隔离",
    ),
    ProjectIssue(
        issue_id="PJ-005",
        title="mimo.exe 半死状态",
        category="连接",
        severity="严重",
        root_cause="SSE 长连接保持活跃但 HTTP 线程池耗尽",
        solution="SSE 连接单例管理，避免重复创建",
        status="已解决 (v3.25)",
        recurrence_risk="中（依赖 mimo.exe 状态）",
        lesson="mimo.exe 不稳定，需要 Watchdog 监控",
    ),
    ProjectIssue(
        issue_id="PJ-006",
        title="AI 调用入口分散（7 个文件独立实现）",
        category="架构",
        severity="严重",
        root_cause="标准模式和混合模式各自独立实现 Ollama 调用",
        solution="统一到 EngineManager，所有 AI 调用走唯一入口",
        status="部分解决（标准模式已统一，混合模式待修复）",
        recurrence_risk="高（混合模式仍需修复）",
        lesson="AI 调用必须走统一入口，禁止分散实现",
    ),
    ProjectIssue(
        issue_id="PJ-007",
        title="Process Bridge 回显导致消息重复",
        category="架构",
        severity="一般",
        root_cause="Process Bridge 回显过滤不完整",
        solution="回显过滤器仅过滤完全相同的消息内容",
        status="已解决 (v3.35)",
        recurrence_risk="低",
        lesson="回显过滤使用精确匹配，不使用前缀匹配",
    ),
    ProjectIssue(
        issue_id="PJ-008",
        title="mimo.exe 僵尸进程导致端口冲突",
        category="连接",
        severity="一般",
        root_cause="start-server.js 启动的进程未正确终止",
        solution="使用进程管理器监控，kill 时使用 taskkill /F /T",
        status="已解决 (v3.40)",
        recurrence_risk="中（依赖 OS 进程管理）",
        lesson="Windows 进程管理需要 /T 参数终止子进程",
    ),
    ProjectIssue(
        issue_id="PJ-009",
        title="小模型无法胜任 Agent 工具调用",
        category="模型",
        severity="严重",
        root_cause="qwen2.5:1.5b (1.5B) 只能选工具但无法合成结果",
        solution="使用 7B+ 模型进行 Agent 任务，1.5B 仅用于简单对话",
        status="已解决 (模型选择策略)",
        recurrence_risk="低（已建立模型选择指南）",
        lesson="≤3B 模型适合选工具，≥7B 模型才能合成结果",
    ),
    ProjectIssue(
        issue_id="PJ-010",
        title="MIMO Code 缺少 AI Provider 配置",
        category="配置",
        severity="致命",
        root_cause="MIMO Code 需要 Ollama 凭证才能生成 AI 回复",
        solution="配置 Ollama 作为 AI Provider，确保通信正常",
        status="已解决 (v3.45)",
        recurrence_risk="低",
        lesson="MIMO Code 只是前端，AI 能力来自 Provider 配置",
    ),
]


# ============================================================
# 报告生成
# ============================================================

def generate_mode_status_report() -> str:
    """生成模式状态报告"""
    lines = [
        "=" * 70,
        "  Lemon Code 模式状态报告",
        "  标准模式 vs 混合模式",
        "=" * 70,
        "",
        "## 标准模式",
        f"  状态: {STANDARD_MODE.status.value}",
        f"  说明: {STANDARD_MODE.description}",
        "",
        "  核心文件:",
    ]
    for f in STANDARD_MODE.core_files:
        lines.append(f"    - {f}")
    lines.append("")
    lines.append("  支持引擎:")
    for e in STANDARD_MODE.engines:
        lines.append(f"    - {e}")
    lines.append("")
    lines.append("  功能列表:")
    for f in STANDARD_MODE.features:
        lines.append(f"    ✅ {f}")
    lines.append("")
    lines.append("  已知问题:")
    for i in STANDARD_MODE.known_issues:
        lines.append(f"    ⚠ {i}")
    lines.append("")
    lines.append("  已解决问题:")
    for i in STANDARD_MODE.resolved_issues:
        lines.append(f"    ✅ {i}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 混合模式")
    lines.append(f"  状态: {HYBRID_MODE.status.value}")
    lines.append(f"  说明: {HYBRID_MODE.description}")
    lines.append("")
    lines.append("  已知问题:")
    for i in HYBRID_MODE.known_issues:
        lines.append(f"    ⚠ {i}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 历史问题总结")
    lines.append("")
    for issue in PROJECT_ISSUES:
        lines.append(f"### {issue.issue_id}: {issue.title}")
        lines.append(f"  - 严重程度: {issue.severity}")
        lines.append(f"  - 根因: {issue.root_cause}")
        lines.append(f"  - 解决方案: {issue.solution}")
        lines.append(f"  - 状态: {issue.status}")
        lines.append(f"  - 复发风险: {issue.recurrence_risk}")
        lines.append(f"  - 教训: {issue.lesson}")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


if __name__ == "__main__":
    print(generate_mode_status_report())