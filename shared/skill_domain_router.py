# -*- coding: utf-8 -*-
"""技能域路由器（376-2）
=====================================
背景（375-2 复测结论）：
  公平模式 fair=0/15 MISS —— SIMPLE/MODERATE 复杂度裁剪只保留文件/命令工具白名单
  （_CORE_TOOLS / _MODERATE_TOOLS），43 个模块技能在菜单里全部不可见，模型无从调用。

本模块职责：
  纯关键词规则（无 LLM 依赖、单 GPU 友好、零成本）把用户 prompt 匹配到技能域，
  返回该域应保留在工具菜单中的技能名集合，供
  EngineManager._get_tool_definitions_for_complexity 与白名单做并集。

设计原则：
  - 只做"菜单准入"，不做"技能选择"——最终仍由 LLM 从菜单中自行挑选
  - 匹配结果必须与实际注册表取交集，防止路由到未注册技能（如 web_researcher）
  - 单条规则失败不影响整体（防御式），异常时返回空集=回退原裁剪行为
"""
from typing import Iterable, List, Optional, Set

import logging
logger = logging.getLogger(__name__)

# ============================================================
# 域规则表：(域名, 关键词列表, 该域技能名列表)
# 关键词覆盖中文+英文；匹配为子串包含（prompt 统一 lower 后比对）
# ============================================================
_DOMAIN_RULES = [
    # ---- 财务（★390B-2 上移至 math 之前：防"计算/复利"双命中时 math 抢 domain；
    #      词表扩充对照 386B-2 finance 残留题实词：本金/年利率/本息） ----
    ("finance", [
        "复利", "利息", "利率", "本金", "本息", "年化", "理财", "汇率", "贷款",
        "存款", "投资", "投资回报", "股票", "收益率", "个税", "通胀", "通货膨胀",
        "按揭", "还款", "compound interest", "annuity", "interest rate",
        "inflation", "finance",
    ], ["finance_assistant"]),
    # ---- 数学/物理 ----
    ("math", [
        "解方程", "方程", "求解", "数学", "计算", "因式分解", "导数", "积分",  # ★397A-3:"计算"子串误命中"边缘计算"→见 route_skills 负向排除
        "方程组", "不等式", "solve", "equation", "math",
    ], ["math_solver", "math_plotter", "physics_experiment"]),
    # ---- 翻译 ----
    ("translate", [
    "翻译", "译成", "译为", "translate", "translation",
    ], ["translator"]),
    # ---- 学术写作（★396B-2: 写作类题目回补 academic_writer——此前无写作域，
    #      学术风格介绍/论文/综述题菜单无此技能=误排除第三例） ----
    ("writing", [
    "学术风格", "学术论文", "论文大纲", "综述", "摘要", "开题", "学术介绍",
    "写论文", "paper", "essay", "literature review",
    ], ["academic_writer"]),
    # ---- 联网调研（★390B-2: 补竞品/市场/行业类词——调研题实词） ----
    ("research", [
        "搜索", "搜一下", "查一下", "调研", "研究一下", "最新", "新特性",
        "新闻", "资料", "深度研究", "联网", "帮我查", "search", "research",
        "竞品", "对标", "同类项目", "类似项目", "竞品分析", "市场调研",
        "行业分析", "市场行情", "competitor", "market research",
    ], ["deep_researcher", "super_researcher"]),
    # ---- 论文/学术 ----
    ("academic", [
        "论文", "文献", "arxiv", "学术", "综述", "引用", "paper",
    ], ["academic_writer", "arxiv_researcher"]),
    # ---- 事实核查 ----
    ("fact_check", [
        "核查", "核实", "真假", "辟谣", "事实", "说法对", "属实",
        "fact check", "factcheck",
    ], ["fact_checker"]),
    # ---- 代码审查 ----
    ("code_review", [
        "审查", "评审", "代码质量", "代码问题", "code review", "review this",
        "帮我看看这段代码",
    ], ["code_reviewer"]),
    # ---- 测试生成 ----
    ("testing", [
        "单元测试", "测试用例", "生成测试", "写测试", "pytest", "unittest",
        "test case", "覆盖率",
    ], ["test_generator"]),
    # ---- 安全审计 ----
    ("security", [
        "安全", "漏洞", "注入", "xss", "csrf", "越权", "密码学", "加密强度",
        "security", "vulnerability",
    ], ["security_auditor"]),
    # ---- 系统信息 ----
    ("system", [
        "系统概况", "系统的概况", "系统报告", "系统信息", "系统状态", "系统情况",
        "概况报告", "概况", "硬件", "内存", "cpu", "磁盘",
        "操作系统版本", "system report", "system info",
    ], ["system_report"]),
    # ---- 辩论 ----
    ("debate", [
        "辩论", "正方", "反方", "驳斥", "争论", "debate",
    ], ["info_debater", "multi_model_debater"]),
    # ---- 需求放大 ----
    ("requirement", [
        "放大需求", "需求放大", "澄清需求", "需求文档", "需求分析",
        "帮我放大", "requirements",
    ], ["requirement_amplifier", "design_blueprint"]),
    # ---- 财务 ----
    ("finance", [
        "复利", "利息", "理财", "汇率", "贷款", "存款", "投资", "股票",
        "收益率", "finance",
    ], ["finance_assistant"]),
    # ---- 前端/设计 ----
    ("frontend", [
        "登录页", "前端", "页面设计", "界面设计", "组件设计", "落地页",
        "html页面", "css", "ui设计", "dashboard", "landing page",
    ], ["frontend_designer"]),
    # ---- 代码分析/心理 ----
    ("code_analysis", [
        "作者思路", "代码意图", "这段代码", "分析代码", "递归", "代码解读",
        "代码做了什么", "阅读代码",
        # ★390B-2: 补代码域实词（对照 15 题集与常见问法）
        "重构", "调试", "修复这段代码", "代码优化", "算法实现", "解释这段",
        "refactor", "debug this",
    ], ["code_psychologist", "code_semantic_analyzer", "lsp_code_analysis"]),
    # ---- 技能创建 ----
    ("skill_create", [
        "创建技能", "新建技能", "技能骨架", "做一个技能", "写个技能",
        "create skill", "skill template",
    ], ["skill_creator"]),
    # ---- 办公文档（★390B-2: 补办公实词） ----
    ("office", [
        "word文档", "excel", "ppt", "幻灯片", "生成文档", "docx", "xlsx",
        "格式转换", "markdown转", "转pdf",
        "周报", "日报", "会议纪要", "简历", "通知", "工作总结", "文档生成",
        "meeting minutes", "resume",
    ], ["office_generator", "format_converter", "pdf_reader"]),
    # ---- 图像 ----
    ("image", [
        "图片", "图像", "识别图片", "ocr", "截图", "看图", "图片信息",
        "image",
    ], ["image_analyzer", "image_processor", "ocr_reader", "screenshot_qa"]),
    # ---- 代码回放/Diff ----
    ("code_playback", [
        "代码diff", "diff对比", "代码变更", "改动对比", "代码回放",
    ], ["code_playback"]),
    # ---- ★第411章: 操作卡（404 Generative UI 家族）——
    #     根因修复：404~409 新技能未接入域路由，SIMPLE/MODERATE 裁剪后菜单
    #     无 ui_action_card，模型只能 write_file 硬写 HTML 文件（用户实测 MISS） ----
    ("action_card", [
        "动作卡", "操作卡", "虚拟按键", "按钮卡", "生成卡片", "一张卡片",
        "按钮", "卡片上", "action card", "ui card",
    ], ["ui_action_card", "list_actions"]),
    # ---- ★第411章: mock 银行（405/406 AI Banking 家族）----
    #   ★第420章: 服务流切换为 remote_bank_*（HTTP 对接独立数字银行沙箱）——
    #   用户明确要求：agent 服务流不走进程内模拟库，全部经 HTTP 真连银行服务。
    #   进程内 bank_* 技能保留注册（不进域路由=不出现在裁剪菜单）。
    ("bank", [
        "银行", "转账", "余额", "冲正", "撤销转账", "对账", "账本", "账单",
        "活期", "定期", "锁定存款", "赎回", "理财产品", "扣费", "订阅",
        "挂失", "银行卡", "bank",
        # ★第436章 动态银行关键词
        "利息", "到期", "兑付", "银行日", "日切", "动态事件", "倒计时",
        # ★第437章 社会级生态关键词
        "工资", "代发", "发薪", "社保", "公积金", "缴税", "个税", "税",
        "水电费", "水费", "电费", "燃气", "房租", "商户", "消费", "社会服务", "企业", "对公",
        # ★第438章 AI Banking 六场景关键词
        "定时转账", "预约转账", "AA", "平摊", "拼单", "账单", "消费分析", "异常交易",
        "风险评估", "风险等级", "产品推荐", "理财推荐", "挂失", "额度调整", "限制交易",
        "解锁", "取消订阅", "退订", "续费", "生日", "鲜花", "蛋糕", "订购", "商城", "手机号",
    ], ["remote_bank_accounts", "remote_bank_query_balance", "remote_bank_transfer",
        "remote_bank_reverse", "remote_bank_transactions", "remote_bank_audit",
        "remote_bank_risk_events", "remote_bank_reconcile", "remote_bank_compound",
        "remote_bank_products", "remote_bank_subscriptions", "remote_bank_menu",
        "remote_bank_holdings", "remote_bank_events", "remote_bank_deposits",
        "remote_bank_social",
        "remote_find_account", "remote_transfer_schedule", "remote_transfer_aa",
        "remote_bill_analysis", "remote_wealth_advisor", "remote_card_manage",
        "remote_subscription_cancel", "remote_mall"]),
    # ---- ★第411章: 网页预览卡（408 WebPageCard）----
    ("web_page", [
        "网页", "网址", "这个链接", "网页内容", "抓取", "打开网站",
        "看一下网站", "https://", "http://", "www.", "website", "webpage",
    ], ["web_preview"]),
    # ---- ★第421章: 贷款融资 / 基金 / 股票（数字银行综合金融服务）----
    ("finance", [
        "贷款", "融资", "授信", "借款", "还贷", "还款",
        "基金", "申购", "净值", "持仓",
    ], ["remote_loan_apply", "remote_loan_list", "remote_loan_repay",
        "remote_fund_list", "remote_fund_buy", "remote_bank_holdings"]),
    ("stock", [
        "股票", "行情", "K线", "k线", "买入", "卖出", "券商", "证券",
        "股市", "涨跌", "大盘",
    ], ["remote_stock_list", "remote_stock_kline", "remote_stock_trade"]),
    # ---- ★第411章: 定时调度（407 Scheduler，跨场景联动）----
    ("scheduler", [
        "定时", "每天早上", "每天晚上", "每天自动", "每天帮我", "提醒我",
        "稍后帮我", "之后帮我", "秒后", "分钟后", "小时后", "到点",
        "定时任务", "schedule",
    ], ["scheduler_create", "scheduler_list", "scheduler_cancel",
        "scheduler_run_now"]),
    # ---- ★第416章: 图表卡 + 表单卡（卡片家族扩展）----
    ("chart", [
        "图表", "画图", "曲线", "折线", "柱状", "趋势图", "画一张图",
        "画个图", "chart", "可视化",
    ], ["ui_chart_card"]),
    ("form", [
        "表单", "填写", "填一下", "输入框", "提交表单", "form",
    ], ["ui_form_card"]),
]


def route_domains(prompt: str) -> List[str]:
    """返回 prompt 命中的域列表（仅用于日志/调试）。"""
    if not prompt:
        return []
    try:
        text = prompt.lower()
        return [name for name, kws, _ in _DOMAIN_RULES
                if any(kw.lower() in text for kw in kws)]
    except Exception:
        return []


def route_skills(prompt: str, available: Optional[Iterable[str]] = None) -> Set[str]:
    """按关键词规则路由出应保留在菜单中的技能名集合。

    Args:
        prompt: 用户输入文本
        available: 实际已注册的工具/技能名集合；提供时结果与其取交集，
                   防止路由到未注册技能（如 web_researcher）
    Returns:
        技能名集合；无命中或异常时返回空集（调用方回退原裁剪行为）
    """
    if not prompt:
        return set()
    routed: Set[str] = set()
    try:
        text = prompt.lower()
        for _name, kws, skills in _DOMAIN_RULES:
            if any(kw.lower() in text for kw in kws):
                routed.update(skills)
    except Exception:
        return set()
    # ★ 397A-3: 域路由子串误命中修复 ——「边缘计算」≠ 数学计算。
    #   根因: math 域关键词"计算"以子串包含匹配命中了"边缘计算"；
    #   此处加负向排除: prompt 含"边缘计算"时从路由结果剔除 math 域技能
    #   (math_solver/math_plotter/physics_experiment)，防误挂 math 域。
    #   "复利计算"仍因"复利"关键词保留 finance 域命中（回归项）。
    if "边缘计算" in text:
        routed -= {"math_solver", "math_plotter", "physics_experiment"}
        logger.debug(f"[397A-3] 边缘计算→math 排除: math 域技能已移除")
    if available is not None:
        try:
            routed &= set(available)
        except Exception:
            pass
    return routed


def get_domain_rules_count() -> int:
    """规则表条目数（自检用）。"""
    return len(_DOMAIN_RULES)
