# -*- coding: utf-8 -*-
"""
Lemon Code 问题回顾与解决方案汇总
==================================
全面梳理从项目启动至今遇到的所有问题、根因分析和解决方案。

按类别分：
1. 标准模式问题
2. 混合模式问题
3. 引擎/模型问题
4. 前端/UI问题
5. 架构/设计问题
"""

from typing import Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum


class IssueSeverity(Enum):
    CRITICAL = "critical"   # 致命：导致系统不可用
    MAJOR = "major"         # 严重：核心功能受阻
    MINOR = "minor"         # 一般：功能受限
    COSMETIC = "cosmetic"   # 轻微：UI/体验问题


class IssueStatus(Enum):
    RESOLVED = "resolved"       # 已解决
    MITIGATED = "mitigated"     # 已缓解
    WORKAROUND = "workaround"   # 有变通方案
    OPEN = "open"               # 未解决
    WONT_FIX = "wont_fix"       # 不修复


@dataclass
class IssueRecord:
    """问题记录"""
    id: str
    title: str
    category: str
    severity: IssueSeverity
    status: IssueStatus
    description: str
    root_cause: str
    solution: str
    fixed_in_version: str = ""
    lesson_learned: str = ""
    related_files: List[str] = field(default_factory=list)


# ============================================================
# 完整问题清单
# ============================================================

ISSUE_DATABASE: List[IssueRecord] = [
    # ==================== 标准模式问题 ====================
    IssueRecord(
        id="B01",
        title="MIMO Code 多会话架构缺失",
        category="标准模式",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.RESOLVED,
        description="标准模式无法同时管理多个 MIMO Code 会话，需要重启才能切换项目。",
        root_cause="原始设计中 Process Bridge 只支持单会话，缺少多实例管理。",
        solution="创建 MultiSessionManager + MultiInstanceManager，支持多会话隔离和并行管理。",
        fixed_in_version="v3.0",
        lesson_learned="进程通信架构需要从一开始就考虑多实例场景。",
        related_files=["multi_session_manager.py", "multi_instance_manager.py"],
    ),
    IssueRecord(
        id="B02",
        title="Process Bridge 回显过滤不完整",
        category="标准模式",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.RESOLVED,
        description="stdin/stdout 通信中，发送的命令被回显到输出中，污染 AI 响应。",
        root_cause="回显过滤器仅过滤完全相同的消息内容，前缀匹配未实现。",
        solution="改为完全匹配过滤，同时跟踪已发送消息队列进行精确过滤。",
        fixed_in_version="v3.0",
        lesson_learned="进程通信中的回显问题需要在协议层面解决，而非上层过滤。",
        related_files=["process_bridge.py"],
    ),
    IssueRecord(
        id="B03",
        title="MIMO Code 窗口检测失败",
        category="标准模式",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.RESOLVED,
        description="无法检测到 MIMO Code 窗口（类名 CASCADIA_HOSTING_WINDOW_CLASS），导致桥接失败。",
        root_cause="窗口检测使用 Win32 API，MIMO Code 窗口在启动时可能尚未创建。",
        solution="增加重试机制（最多 5 次，间隔 1 秒），并添加窗口存在性轮询检查。",
        fixed_in_version="v3.0",
        lesson_learned="外部进程窗口检测必须有重试和超时机制。",
        related_files=["mimo_hook.py", "gui_worm_bridge.py"],
    ),
    IssueRecord(
        id="B04",
        title="标准模式 Ollama 对话无响应",
        category="标准模式",
        severity=IssueSeverity.CRITICAL,
        status=IssueStatus.RESOLVED,
        description="标准模式切换到 Ollama 引擎后，发送消息无任何回复。",
        root_cause="qwen3.5:4b 思考模型 num_predict=100 太小，所有 token 消耗在思考过程中。",
        solution="num_predict 从 100 提升到 1500，全项目 7 个文件统一修改。",
        fixed_in_version="v3.15",
        lesson_learned="思考模型的 num_predict 必须足够大（>=1500），否则 content 始终为空。",
        related_files=["ollama_engine.py", "ollama_bridge.py", "engine_manager.py"],
    ),
    IssueRecord(
        id="B05",
        title="IPv6 连接失败（localhost→127.0.0.1）",
        category="标准模式",
        severity=IssueSeverity.CRITICAL,
        status=IssueStatus.RESOLVED,
        description="Ollama 连接失败，原因是 localhost 被解析为 IPv6 ::1，而 Ollama 监听 IPv4。",
        root_cause="Windows 默认优先解析 IPv6，Ollama 默认只监听 127.0.0.1。",
        solution="全项目 16 处 localhost 改为 127.0.0.1，确保 IPv4 连接。",
        fixed_in_version="v3.8",
        lesson_learned="网络连接应统一使用 127.0.0.1 而非 localhost，避免 IPv6 解析问题。",
        related_files=["ollama_engine.py", "ollama_bridge.py", "hybrid_mode_web_panel.py"],
    ),
    IssueRecord(
        id="B06",
        title="MIMO Code HTTP 线程池耗尽",
        category="标准模式",
        severity=IssueSeverity.CRITICAL,
        status=IssueStatus.MITIGATED,
        description="MIMO Code 在第一次 AI 响应后进入半死状态：SSE 连接正常但 HTTP 请求完全阻塞。",
        root_cause="SSE 长连接占用线程，HTTP 请求处理线程池耗尽。",
        solution="增加连接超时和重试机制，检测到阻塞时自动重启 MIMO 服务。",
        fixed_in_version="v3.0",
        lesson_learned="SSE 长连接和 HTTP 短连接需要独立的线程池管理。",
        related_files=["process_bridge.py", "serve_bridge.py"],
    ),
    IssueRecord(
        id="B07",
        title="MIMO 模式下自动切换到 Ollama",
        category="标准模式",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.RESOLVED,
        description="MIMO 模式下系统自动切换到 Ollama，覆盖用户手动选择的引擎。",
        root_cause="EngineManager 初始化逻辑中，MIMO 未注册时自动回退到 Ollama，但未检查用户偏好。",
        solution="禁止 MIMO 模式下的自动切换，增加用户偏好持久化。",
        fixed_in_version="v3.6",
        lesson_learned="引擎切换必须尊重用户手动选择，自动切换仅作为最后的降级手段。",
        related_files=["engine_manager.py"],
    ),

    # ==================== 混合模式问题 ====================
    IssueRecord(
        id="B08",
        title="混合模式面板崩溃（RuntimeError）",
        category="混合模式",
        severity=IssueSeverity.CRITICAL,
        status=IssueStatus.RESOLVED,
        description="混合模式面板隐藏/删除后，后台线程继续运行，访问已删除的 Qt 对象导致崩溃。",
        root_cause="面板隐藏时未停止后台线程，线程继续访问已销毁的 Qt 控件。",
        solution="面板隐藏时通过标志位停止所有后台线程，线程执行前检查控件有效性。",
        fixed_in_version="v3.0",
        lesson_learned="Qt 线程安全：任何跨线程访问 Qt 对象前必须检查 isValid()。",
        related_files=["hybrid_mode_web_panel.py"],
    ),
    IssueRecord(
        id="B09",
        title="混合模式 Agent 回复模拟",
        category="混合模式",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.RESOLVED,
        description="混合模式 Agent 聊天使用 setTimeout 模拟回复，非真实 AI 响应。",
        root_cause="初期快速原型开发，未接入真实 AI 引擎。",
        solution="11 个 AI 调用点全部接入真实 Ollama，通过 EngineManager 统一调用。",
        fixed_in_version="v3.1",
        lesson_learned="原型阶段应明确标注 TODO，避免模拟代码遗留到生产环境。",
        related_files=["hybrid_mode_web_panel.py", "hybrid_mode_wireframe.html"],
    ),
    IssueRecord(
        id="B10",
        title="混合模式数据硬编码",
        category="混合模式",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.RESOLVED,
        description="混合模式中 Agent 卡片、角色、技能数据全部硬编码，无法动态配置。",
        root_cause="初期快速开发，未设计数据层。",
        solution="接入真实引擎数据，Agent 卡片从 EngineManager 获取，Skill 从 SkillsRegistry 获取。",
        fixed_in_version="v3.2",
        lesson_learned="数据层应最早设计，UI 层应最晚绑定数据。",
        related_files=["hybrid_mode_bridge.py", "hybrid_mode_wireframe.html"],
    ),

    # ==================== 引擎/模型问题 ====================
    IssueRecord(
        id="B11",
        title="qwen2.5:1.5b 无法胜任 Agent 工具调用",
        category="引擎/模型",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.WORKAROUND,
        description="1.5B 参数模型可以选工具但无法合成结果，Agent 无法持续 skill 调用。",
        root_cause="小模型（<=3B）擅长选工具但无法合成结果，这是已知的模型能力限制。",
        solution="推荐使用 7B+ 模型进行 Agent 任务，1.5B 仅用于简单对话。",
        fixed_in_version="v3.15",
        lesson_learned="Agent 工具调用至少需要 7B 参数模型，1.5B 仅适合简单对话。",
        related_files=["ollama_engine.py", "engine_manager.py"],
    ),
    IssueRecord(
        id="B12",
        title="HTTP 连接泄漏（CLOSE_WAIT 堆积）",
        category="引擎/模型",
        severity=IssueSeverity.CRITICAL,
        status=IssueStatus.RESOLVED,
        description="长时间运行后，HTTP 连接处于 CLOSE_WAIT 状态堆积，导致新请求超时。",
        root_cause="使用模块级 requests.get/post 而非 Session 管理，连接未正确关闭。",
        solution="统一使用 requests.Session() 管理连接，设置合理的 keep-alive 和超时。",
        fixed_in_version="v3.5",
        lesson_learned="HTTP 客户端必须使用 Session 管理，模块级调用会导致连接泄漏。",
        related_files=["ollama_engine.py", "ollama_bridge.py", "deepseek_engine.py"],
    ),
    IssueRecord(
        id="B13",
        title="StreamOptimizer 首块刷新延迟",
        category="引擎/模型",
        severity=IssueSeverity.MINOR,
        status=IssueStatus.RESOLVED,
        description="流式输出首块 token 刷新延迟过长，用户体验不佳。",
        root_cause="StreamOptimizer 缓冲区阈值设置过大，首块等待时间过长。",
        solution="降低首块缓冲区阈值，增加首块优先刷新策略。",
        fixed_in_version="v3.110",
        lesson_learned="流式输出应优先保证首块低延迟，后续可适当缓冲。",
        related_files=["stream_optimizer.py"],
    ),
    IssueRecord(
        id="B14",
        title="拓扑排序方向错误",
        category="引擎/模型",
        severity=IssueSeverity.MINOR,
        status=IssueStatus.RESOLVED,
        description="插件依赖拓扑排序方向错误，导致依赖顺序颠倒。",
        root_cause="拓扑排序算法中边的方向定义与依赖关系不一致。",
        solution="修正拓扑排序算法，依赖方在前、被依赖方在后。",
        fixed_in_version="v3.110",
        lesson_learned="图算法中的方向定义必须与业务语义严格一致。",
        related_files=["plugin_lifecycle.py"],
    ),
    IssueRecord(
        id="B15",
        title="dependencies 字段类型兼容性",
        category="引擎/模型",
        severity=IssueSeverity.MINOR,
        status=IssueStatus.RESOLVED,
        description="插件配置中 dependencies 字段有时是字符串有时是列表，导致解析失败。",
        root_cause="不同插件来源的配置格式不一致。",
        solution="统一解析逻辑，兼容字符串和列表两种格式。",
        fixed_in_version="v3.110",
        lesson_learned="外部数据入口需要做格式兼容处理，不能假设统一格式。",
        related_files=["plugin_manifest.py"],
    ),

    # ==================== 前端/UI问题 ====================
    IssueRecord(
        id="B16",
        title="底部栏终端始终显示 MIMO",
        category="前端/UI",
        severity=IssueSeverity.MINOR,
        status=IssueStatus.RESOLVED,
        description="通过右上角模型选择器切换模型后，底部栏终端仍显示 'MIMO'。",
        root_cause="底部栏显示逻辑未与引擎切换事件同步。",
        solution="引擎切换时同步更新底部栏显示文本。",
        fixed_in_version="v3.6",
        lesson_learned="UI 状态变化必须通过事件总线同步，不能各自独立更新。",
        related_files=["mimo_page.html", "engine_manager.py"],
    ),
    IssueRecord(
        id="B17",
        title="代码 Diff 缺少块级渲染",
        category="前端/UI",
        severity=IssueSeverity.MINOR,
        status=IssueStatus.RESOLVED,
        description="代码 Diff 只有行级高亮，缺少 MIMO Code 的块级整块标色。",
        root_cause="初始实现仅做了逐行标识，未做连续行分组。",
        solution="实现连续行分组算法，diff-block 容器包裹，块级指示器。",
        fixed_in_version="v3.160 (Patch 9)",
        lesson_learned="对标竞品时需要逐功能对比，而非仅实现基本功能。",
        related_files=["mimo_page.html"],
    ),
    IssueRecord(
        id="B18",
        title="打字效果缺少变速和辉光",
        category="前端/UI",
        severity=IssueSeverity.COSMETIC,
        status=IssueStatus.RESOLVED,
        description="打字效果仅有基础逐字输出，缺少 MIMO Code 的平滑体验。",
        root_cause="初始实现仅做了简单的 setTimeout 逐字输出。",
        solution="增加标点停顿映射、辉光光标动画、字符入场效果。",
        fixed_in_version="v3.160 (Patch 9)",
        lesson_learned="用户体验细节（动画、过渡）与核心功能同等重要。",
        related_files=["mimo_page.html"],
    ),

    # ==================== 架构/设计问题 ====================
    IssueRecord(
        id="B19",
        title="AI 调用入口分散",
        category="架构/设计",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.RESOLVED,
        description="Ollama 调用分散在 7+ 个文件中，参数不一致，修复遗漏。",
        root_cause="初期没有统一的 AI 调用入口，各模块独立实现。",
        solution="EngineManager 作为唯一入口，所有 AI 调用必须经过 EngineManager。",
        fixed_in_version="v3.0",
        lesson_learned="核心能力（AI 调用）必须统一入口，避免分散实现。",
        related_files=["engine_manager.py", "ollama_engine.py", "deepseek_engine.py"],
    ),
    IssueRecord(
        id="B20",
        title="标准模式与混合模式代码耦合",
        category="架构/设计",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.MITIGATED,
        description="混合模式开发曾修改标准模式文件，导致标准模式功能退化。",
        root_cause="两个模式共享部分代码文件，修改时未隔离。",
        solution="制定核心开发铁律：标准模式与混合模式永久隔离，修改前检查清单。",
        fixed_in_version="v3.0",
        lesson_learned="多模式架构必须明确代码隔离边界，防止交叉污染。",
        related_files=["PROJECT_DEVELOPMENT_LOG.md (核心铁律)"],
    ),
    IssueRecord(
        id="B21",
        title="mimo.exe 僵尸进程",
        category="架构/设计",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.RESOLVED,
        description="start-server.js 启动的 mimo.exe 进程在异常退出后成为僵尸进程，占用端口 4096。",
        root_cause="进程管理未正确清理子进程，未设置进程组。",
        solution="使用进程组管理，退出时清理所有子进程，端口占用检测。",
        fixed_in_version="v3.0",
        lesson_learned="进程管理必须使用进程组，确保所有子进程被正确清理。",
        related_files=["process_bridge.py", "startup_optimizer.py"],
    ),
    IssueRecord(
        id="B22",
        title="SSE 连接重复创建",
        category="架构/设计",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.RESOLVED,
        description="创建第二个 SSE 连接时未停止旧线程，导致 MIMO Code 不稳定。",
        root_cause="SSE 连接管理未实现单例模式，允许多个连接并存。",
        solution="SSE 连接使用单例管理，新建前先停止旧连接。",
        fixed_in_version="v3.0",
        lesson_learned="长连接（SSE/WebSocket）必须使用单例模式管理。",
        related_files=["process_bridge.py", "serve_bridge.py"],
    ),
    IssueRecord(
        id="B23",
        title="ConnectionResetError (10054) 需要全服务重启",
        category="架构/设计",
        severity=IssueSeverity.MAJOR,
        status=IssueStatus.MITIGATED,
        description="MIMO Code 连接重置后，简单重连无效，需要全服务重启。",
        root_cause="MIMO Code 内部状态在连接重置后未清理，新连接继承旧状态。",
        solution="检测到 ConnectionResetError 时执行全服务重启流程。",
        fixed_in_version="v3.0",
        lesson_learned="外部服务连接异常不应仅重连，需要评估是否需要全量重启。",
        related_files=["process_bridge.py", "crash_recovery.py"],
    ),
]


# ============================================================
# 统计与报告
# ============================================================

def get_issue_stats() -> Dict:
    """获取问题统计"""
    stats = {
        "total": len(ISSUE_DATABASE),
        "by_severity": {},
        "by_status": {},
        "by_category": {},
        "resolved_rate": 0,
    }
    for issue in ISSUE_DATABASE:
        sev = issue.severity.value
        stats["by_severity"][sev] = stats["by_severity"].get(sev, 0) + 1
        st = issue.status.value
        stats["by_status"][st] = stats["by_status"].get(st, 0) + 1
        cat = issue.category
        stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

    resolved = stats["by_status"].get("resolved", 0)
    stats["resolved_rate"] = f"{resolved / stats['total'] * 100:.1f}%"
    return stats


def generate_issue_report() -> str:
    """生成问题回顾报告"""
    stats = get_issue_stats()
    lines = [
        "=" * 70,
        "  Lemon Code 问题回顾与解决方案汇总",
        f"  总计: {stats['total']} 个问题 | 已解决率: {stats['resolved_rate']}",
        "=" * 70,
        "",
        "## 概览",
        f"  总问题数: {stats['total']}",
        f"  已解决: {stats['by_status'].get('resolved', 0)}",
        f"  已缓解: {stats['by_status'].get('mitigated', 0)}",
        f"  有变通方案: {stats['by_status'].get('workaround', 0)}",
        f"  未解决: {stats['by_status'].get('open', 0)}",
        f"  解决率: {stats['resolved_rate']}",
        "",
        "## 按严重程度",
    ]
    for sev, count in stats["by_severity"].items():
        lines.append(f"  {sev}: {count}")
    lines.append("")
    lines.append("## 按类别")
    for cat, count in stats["by_category"].items():
        lines.append(f"  {cat}: {count}")
    lines.append("")
    lines.append("## 详细清单")
    lines.append("")

    for issue in ISSUE_DATABASE:
        lines.append(f"### [{issue.severity.value.upper()}] {issue.id}: {issue.title}")
        lines.append(f"- 类别: {issue.category}")
        lines.append(f"- 状态: {issue.status.value}")
        lines.append(f"- 描述: {issue.description}")
        lines.append(f"- 根因: {issue.root_cause}")
        lines.append(f"- 解决方案: {issue.solution}")
        if issue.fixed_in_version:
            lines.append(f"- 修复版本: {issue.fixed_in_version}")
        if issue.lesson_learned:
            lines.append(f"- 经验教训: {issue.lesson_learned}")
        lines.append("")

    lines.append("=" * 70)
    lines.append("")
    lines.append("## 核心经验教训总结")
    lines.append("")
    lessons = set(i.lesson_learned for i in ISSUE_DATABASE if i.lesson_learned)
    for i, lesson in enumerate(sorted(lessons), 1):
        lines.append(f"{i}. {lesson}")

    return "\n".join(lines)


if __name__ == "__main__":
    print(generate_issue_report())