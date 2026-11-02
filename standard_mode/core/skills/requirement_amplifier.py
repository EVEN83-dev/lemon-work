# -*- coding: utf-8 -*-
"""
Skill: requirement_amplifier — 需求放大器
==========================================
将用户粗略策划案自动扩展为完整需求规格说明书(SRS)。

流程：
1. 策划案解析器 — 提取显式需求（功能点/技术栈/目标用户）
2. 隐式需求推理器 — 基于行业知识库推断未说出的必要模块
3. 需求差异分析 — 显式 vs 隐式 → 生成"待确认清单"
4. 智能询问生成器 — 生成最小化问题集（≤5个关键问题）
5. SRS生成 — 输出完整需求规格说明书
"""

import os
import re
import traceback
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "requirement_amplifier",
    "description": "需求放大器：将粗略策划案自动扩展为完整需求规格说明书(SRS)，推断隐式需求并生成待确认清单",
    "category": "planning",
    "version": "1.0.0",
}

# ==================== 行业知识库 ====================

INDUSTRY_KNOWLEDGE_BASE = {
    "ecommerce": {
        "name": "电商",
        "keywords": ["电商", "商城", "购物", "店铺", "商品", "下单", "交易", "买卖", "电商平合", "e-commerce", "shop", "store"],
        "required_modules": [
            {"module": "用户认证", "reason": "用户登录/注册是电商的基础入口", "priority": "high"},
            {"module": "购物车", "reason": "商品暂存与结算的核心环节", "priority": "high"},
            {"module": "支付系统", "reason": "完成交易闭环的关键模块", "priority": "high"},
            {"module": "订单管理", "reason": "订单生命周期跟踪与管理", "priority": "high"},
            {"module": "库存管理", "reason": "防止超卖与库存同步", "priority": "medium"},
            {"module": "物流跟踪", "reason": "发货与配送状态追踪", "priority": "medium"},
            {"module": "商品搜索与筛选", "reason": "用户快速找到目标商品", "priority": "medium"},
            {"module": "用户评价", "reason": "辅助购买决策与信任建立", "priority": "low"},
            {"module": "优惠/促销", "reason": "提升转化率的营销工具", "priority": "low"},
        ],
    },
    "saas": {
        "name": "SaaS",
        "keywords": ["SaaS", "saas", "软件服务", "订阅", "云服务", "企业服务", "B2B", "multi-tenant"],
        "required_modules": [
            {"module": "用户认证", "reason": "SaaS 多租户身份管理基础", "priority": "high"},
            {"module": "多租户架构", "reason": "数据隔离与资源隔离的核心", "priority": "high"},
            {"module": "计费系统", "reason": "订阅制收费与用量计费", "priority": "high"},
            {"module": "权限管理", "reason": "组织内角色与权限控制", "priority": "high"},
            {"module": "数据分析", "reason": "用户行为分析与业务洞察", "priority": "medium"},
            {"module": "API 网关", "reason": "开放能力与第三方集成", "priority": "medium"},
            {"module": "通知系统", "reason": "租户与用户消息触达", "priority": "medium"},
            {"module": "审计日志", "reason": "操作追溯与合规要求", "priority": "low"},
        ],
    },
    "tool": {
        "name": "工具类",
        "keywords": ["工具", "转换", "生成器", "计算器", "编辑器", "批量", "处理", "tool", "utility", "converter"],
        "required_modules": [
            {"module": "配置管理", "reason": "用户偏好与参数持久化", "priority": "high"},
            {"module": "错误处理", "reason": "友好提示与异常恢复", "priority": "high"},
            {"module": "日志记录", "reason": "操作回溯与问题诊断", "priority": "medium"},
            {"module": "更新检查", "reason": "版本迭代与功能升级通知", "priority": "medium"},
            {"module": "导入/导出", "reason": "数据迁移与格式兼容", "priority": "medium"},
            {"module": "撤销/重做", "reason": "操作可回退的安全保障", "priority": "low"},
        ],
    },
    "content": {
        "name": "内容平台",
        "keywords": ["内容", "文章", "博客", "资讯", "媒体", "视频", "音频", "发布", "投稿", "CMS", "content", "blog", "media"],
        "required_modules": [
            {"module": "用户认证", "reason": "创作者与读者的身份管理", "priority": "high"},
            {"module": "内容管理", "reason": "内容的创建、编辑、发布、下架", "priority": "high"},
            {"module": "搜索系统", "reason": "用户快速检索内容", "priority": "high"},
            {"module": "推荐系统", "reason": "个性化内容分发提升粘性", "priority": "high"},
            {"module": "评论系统", "reason": "用户互动与社区氛围", "priority": "medium"},
            {"module": "分类/标签", "reason": "内容组织与导航", "priority": "medium"},
            {"module": "内容审核", "reason": "合规与社区规范保障", "priority": "medium"},
            {"module": "收藏/书签", "reason": "用户内容保存与回顾", "priority": "low"},
        ],
    },
    "social": {
        "name": "社交",
        "keywords": ["社交", "社区", "论坛", "聊天", "朋友圈", "动态", "关注", "粉丝", "social", "community", "forum", "chat"],
        "required_modules": [
            {"module": "用户认证", "reason": "社交身份与账户体系基础", "priority": "high"},
            {"module": "关系管理", "reason": "关注/粉丝/好友关系链", "priority": "high"},
            {"module": "消息系统", "reason": "即时通讯与私信功能", "priority": "high"},
            {"module": "通知系统", "reason": "互动消息实时触达", "priority": "high"},
            {"module": "内容过滤", "reason": "违规内容自动识别与拦截", "priority": "high"},
            {"module": "动态/Feed", "reason": "信息流展示与排序", "priority": "medium"},
            {"module": "举报/申诉", "reason": "社区自治与纠纷处理", "priority": "medium"},
            {"module": "隐私设置", "reason": "用户自主控制可见范围", "priority": "medium"},
        ],
    },
}

# ==================== 数据模型 ====================

@dataclass
class ParsedRequirement:
    """解析后的需求"""
    app_type: str = ""
    features: List[str] = field(default_factory=list)
    tech_stack: List[str] = field(default_factory=list)
    target_users: str = ""
    core_modules: List[str] = field(default_factory=list)
    raw_brief: str = ""


@dataclass
class ImplicitNeed:
    """隐式需求"""
    module: str
    reason: str
    priority: str  # high / medium / low
    category: str  # 来源行业分类


@dataclass
class Question:
    """待确认问题"""
    question: str
    recommended_answer: str
    related_module: str


# ==================== 策划案解析器 ====================

class RequirementParser:
    """解析策划案，提取显式需求"""

    # 应用类型识别关键词
    _APP_TYPE_PATTERNS = {
        app_type: info["keywords"]
        for app_type, info in INDUSTRY_KNOWLEDGE_BASE.items()
    }

    # 技术栈关键词
    _TECH_PATTERNS = {
        "React": r"\breact\b",
        "Vue": r"\bvue\b",
        "Angular": r"\bangular\b",
        "Next.js": r"\bnext\.?js\b",
        "Nuxt.js": r"\bnuxt\.?js\b",
        "Flutter": r"\bflutter\b",
        "React Native": r"\breact\s*native\b",
        "Swift": r"\bswift\b",
        "Kotlin": r"\bkotlin\b",
        "Python": r"\bpython\b",
        "Django": r"\bdjango\b",
        "Flask": r"\bflask\b",
        "FastAPI": r"\bfastapi\b",
        "Node.js": r"\bnode\.?js\b",
        "Express": r"\bexpress\b",
        "Spring Boot": r"\bspring\s*boot\b",
        "Go": r"\bgo(?:lang)?\b",
        "Rust": r"\brust\b",
        "MySQL": r"\bmysql\b",
        "PostgreSQL": r"\bpostgres(?:ql)?\b",
        "MongoDB": r"\bmongo(?:db)?\b",
        "Redis": r"\bredis\b",
        "Docker": r"\bdocker\b",
        "Kubernetes": r"\bkubernetes|k8s\b",
        "TypeScript": r"\btypescript|ts\b",
    }

    def parse(self, brief: str, app_type: str = "auto") -> ParsedRequirement:
        """解析策划案

        Args:
            brief: 用户输入的策划案文本
            app_type: 应用类型（auto=自动识别）

        Returns:
            ParsedRequirement 解析后的需求
        """
        parsed = ParsedRequirement(raw_brief=brief)

        # 1. 识别应用类型
        if app_type != "auto":
            parsed.app_type = app_type
        else:
            parsed.app_type = self._detect_app_type(brief)

        # 2. 提取功能点 — 按行拆分，识别动词+名词模式
        parsed.features = self._extract_features(brief)

        # 3. 提取技术栈
        parsed.tech_stack = self._extract_tech_stack(brief)

        # 4. 识别目标用户
        parsed.target_users = self._extract_target_users(brief)

        # 5. 提取核心模块
        parsed.core_modules = self._extract_core_modules(brief, parsed.app_type)

        return parsed

    def _detect_app_type(self, brief: str) -> str:
        """自动识别应用类型"""
        scores: Dict[str, int] = {}
        brief_lower = brief.lower()
        for app_type, keywords in self._APP_TYPE_PATTERNS.items():
            score = sum(1 for kw in keywords if kw.lower() in brief_lower)
            scores[app_type] = score
        if not scores or max(scores.values()) == 0:
            return "tool"  # 默认工具类
        return max(scores, key=scores.get)

    def _extract_features(self, brief: str) -> List[str]:
        """提取功能点"""
        features = []
        # 按行/分号/逗号拆分
        lines = re.split(r'[;\n。，]+', brief)
        feature_pattern = re.compile(
            r'(?:需要|支持|实现|提供|包含|能够|可以|有|做|开发|设计|建设|构建)\s*(.+?)(?:[，。；\n]|$)',
            re.IGNORECASE,
        )
        for line in lines:
            line = line.strip()
            if not line:
                continue
            match = feature_pattern.search(line)
            if match:
                feat = match.group(1).strip()
                if len(feat) > 2:
                    features.append(feat)
            elif len(line) > 2 and len(line) < 30:
                # 短语直接作为功能点
                features.append(line)
        return features[:20]  # 限制上限

    def _extract_tech_stack(self, brief: str) -> List[str]:
        """提取技术栈"""
        found = []
        brief_lower = brief.lower()
        for tech, pattern in self._TECH_PATTERNS.items():
            if re.search(pattern, brief_lower):
                found.append(tech)
        return found

    def _extract_target_users(self, brief: str) -> str:
        """识别目标用户"""
        user_patterns = [
            r'面向(.+?)(?:用户|人群|客户|群体)',
            r'目标用户[是为：:]\s*(.+?)(?:[，。；\n]|$)',
            r'(?:为|供)(.+?)(?:使用|服务|打造)',
            r'用户画像[是为：:]\s*(.+?)(?:[，。；\n]|$)',
        ]
        for pattern in user_patterns:
            match = re.search(pattern, brief)
            if match:
                return match.group(1).strip()
        return "未指定"

    def _extract_core_modules(self, brief: str, app_type: str) -> List[str]:
        """提取核心模块"""
        modules = []
        # 从行业知识库中匹配
        if app_type in INDUSTRY_KNOWLEDGE_BASE:
            for mod_info in INDUSTRY_KNOWLEDGE_BASE[app_type]["required_modules"]:
                if mod_info["module"] in brief:
                    modules.append(mod_info["module"])
        # 额外匹配常见模块名
        common_modules = ["登录", "注册", "认证", "支付", "搜索", "消息", "通知", "管理后台"]
        for mod in common_modules:
            if mod in brief and mod not in modules:
                modules.append(mod)
        return modules


# ==================== 隐式需求推理器 ====================

class ImplicitNeedInferrer:
    """基于行业知识库推断隐式需求"""

    def infer(self, parsed: ParsedRequirement) -> List[ImplicitNeed]:
        """推断隐式需求

        Args:
            parsed: 解析后的需求

        Returns:
            隐式需求列表
        """
        implicit_needs: List[ImplicitNeed] = []

        app_type = parsed.app_type
        if app_type not in INDUSTRY_KNOWLEDGE_BASE:
            return implicit_needs

        industry = INDUSTRY_KNOWLEDGE_BASE[app_type]
        explicit_modules = set(parsed.core_modules)
        # 也从 features 中提取已提及的模块名
        for feat in parsed.features:
            for mod_info in industry["required_modules"]:
                if mod_info["module"] in feat:
                    explicit_modules.add(mod_info["module"])

        # 差异分析：知识库中的必要模块 - 已显式提及的
        for mod_info in industry["required_modules"]:
            if mod_info["module"] not in explicit_modules:
                implicit_needs.append(ImplicitNeed(
                    module=mod_info["module"],
                    reason=mod_info["reason"],
                    priority=mod_info["priority"],
                    category=industry["name"],
                ))

        # 按优先级排序：high > medium > low
        priority_order = {"high": 0, "medium": 1, "low": 2}
        implicit_needs.sort(key=lambda x: priority_order.get(x.priority, 3))

        return implicit_needs


# ==================== 智能询问生成器 ====================

class SmartQuestionGenerator:
    """生成最小化问题集（≤5个关键问题）"""

    def generate(self, explicit: List[str], implicit: List[ImplicitNeed]) -> List[Question]:
        """生成问题集

        Args:
            explicit: 显式需求列表
            implicit: 隐式需求列表

        Returns:
            问题列表（最多5个）
        """
        questions: List[Question] = []

        # 策略：按优先级选取隐式需求中最重要的模块，生成确认问题
        high_priority = [n for n in implicit if n.priority == "high"]
        medium_priority = [n for n in implicit if n.priority == "medium"]

        # 高优先级隐式需求 → 确认问题
        for need in high_priority:
            if len(questions) >= 5:
                break
            questions.append(Question(
                question=f"是否需要「{need.module}」模块？({need.reason})",
                recommended_answer="是",
                related_module=need.module,
            ))

        # 中优先级隐式需求 → 确认问题
        for need in medium_priority:
            if len(questions) >= 5:
                break
            questions.append(Question(
                question=f"是否需要「{need.module}」功能？({need.reason})",
                recommended_answer="建议添加",
                related_module=need.module,
            ))

        # 如果问题不足5个且有显式需求，补充架构/平台问题
        architecture_questions = [
            Question(
                question="是否需要支持移动端（App/小程序）？",
                recommended_answer="建议至少支持 H5 响应式",
                related_module="跨端适配",
            ),
            Question(
                question="是否需要管理后台？",
                recommended_answer="建议包含基础管理后台",
                related_module="管理后台",
            ),
            Question(
                question="预计用户规模量级？",
                recommended_answer="初期 1K-10K，架构预留扩展空间",
                related_module="架构设计",
            ),
        ]
        for q in architecture_questions:
            if len(questions) >= 5:
                break
            questions.append(q)

        return questions[:5]


# ==================== SRS 生成器 ====================

class SRSGenerator:
    """生成完整的 SRS Markdown 文档"""

    def generate(
        self,
        parsed: ParsedRequirement,
        implicit_needs: List[ImplicitNeed],
        answers: Dict[str, str],
    ) -> str:
        """生成 SRS 文档

        Args:
            parsed: 解析后的需求
            implicit_needs: 隐式需求列表
            answers: 用户对问题的回答 {问题: 回答}

        Returns:
            SRS Markdown 文档字符串
        """
        industry_name = INDUSTRY_KNOWLEDGE_BASE.get(parsed.app_type, {}).get("name", "通用")

        # 合并确认的模块
        confirmed_modules = list(parsed.core_modules)
        declined_modules = []
        for need in implicit_needs:
            q_text = f"是否需要「{need.module}」模块？"
            q_text_alt = f"是否需要「{need.module}」功能？"
            answer = answers.get(q_text, answers.get(q_text_alt, ""))
            if answer and answer not in ("否", "不需要", "不用", "no", "No"):
                confirmed_modules.append(need.module)
            elif answer in ("否", "不需要", "不用", "no", "No"):
                declined_modules.append(need.module)

        # 处理额外回答
        for key, val in answers.items():
            if "移动端" in key and val not in ("否", "不需要", "不用"):
                confirmed_modules.append("移动端适配")
            if "管理后台" in key and val not in ("否", "不需要", "不用"):
                confirmed_modules.append("管理后台")
            if "用户规模" in key:
                pass  # 记录在架构约束中

        # 去重
        confirmed_modules = list(dict.fromkeys(confirmed_modules))

        sections = []

        # 文档头
        sections.append(self._header(parsed, industry_name))

        # 1. 项目概述
        sections.append(self._project_overview(parsed, industry_name))

        # 2. 目标用户
        sections.append(self._target_users(parsed))

        # 3. 功能需求
        sections.append(self._functional_requirements(parsed, confirmed_modules))

        # 4. 非功能需求
        sections.append(self._nonfunctional_requirements())

        # 5. 技术栈
        sections.append(self._tech_stack(parsed))

        # 6. 系统架构
        sections.append(self._system_architecture(confirmed_modules))

        # 7. 模块清单
        sections.append(self._module_list(confirmed_modules, declined_modules))

        # 8. 待确认项
        sections.append(self._pending_items(implicit_needs, answers))

        return "\n\n".join(sections)

    # ---------- 各节生成 ----------

    def _header(self, parsed: ParsedRequirement, industry_name: str) -> str:
        return (
            f"# 需求规格说明书 (SRS)\n\n"
            f"> 基于「需求放大器」自动生成\n\n"
            f"| 字段 | 值 |\n|---|---|\n"
            f"| 应用类型 | {industry_name} |\n"
            f"| 核心模块数 | {len(parsed.core_modules)} |\n"
            f"| 技术栈 | {', '.join(parsed.tech_stack) or '待定'} |"
        )

    def _project_overview(self, parsed: ParsedRequirement, industry_name: str) -> str:
        brief_summary = parsed.raw_brief[:200] + ("..." if len(parsed.raw_brief) > 200 else "")
        return (
            f"## 1. 项目概述\n\n"
            f"**应用类型**: {industry_name}类应用\n\n"
            f"**策划案摘要**: {brief_summary}"
        )

    def _target_users(self, parsed: ParsedRequirement) -> str:
        return (
            f"## 2. 目标用户\n\n"
            f"{parsed.target_users}"
        )

    def _functional_requirements(self, parsed: ParsedRequirement, confirmed_modules: List[str]) -> str:
        lines = [f"## 3. 功能需求\n"]
        # 显式功能
        if parsed.features:
            lines.append("### 3.1 显式功能点\n")
            for i, feat in enumerate(parsed.features, 1):
                lines.append(f"{i}. {feat}")
        # 确认模块
        if confirmed_modules:
            lines.append("\n### 3.2 模块功能\n")
            for i, mod in enumerate(confirmed_modules, 1):
                lines.append(f"{i}. **{mod}**")
        return "\n".join(lines)

    def _nonfunctional_requirements(self) -> str:
        return (
            "## 4. 非功能需求\n\n"
            "| 维度 | 要求 |\n|---|---|\n"
            "| 性能 | 页面加载 ≤ 3s，API 响应 ≤ 500ms |\n"
            "| 可用性 | 99.9% SLA |\n"
            "| 安全性 | HTTPS + 数据加密 + XSS/CSRF 防护 |\n"
            "| 可扩展性 | 微服务友好，支持水平扩展 |\n"
            "| 兼容性 | 主流浏览器最近2个版本 |\n"
            "| 可维护性 | 代码覆盖率 ≥ 70%，文档齐全 |"
        )

    def _tech_stack(self, parsed: ParsedRequirement) -> str:
        lines = ["## 5. 技术栈\n"]
        if parsed.tech_stack:
            for tech in parsed.tech_stack:
                lines.append(f"- {tech}")
        else:
            lines.append("- 待定（建议根据应用类型选择合适技术栈）")
        return "\n".join(lines)

    def _system_architecture(self, confirmed_modules: List[str]) -> str:
        lines = ["## 6. 系统架构\n"]
        layers = {
            "前端": [],
            "后端": [],
            "数据层": [],
            "基础设施": [],
        }
        for mod in confirmed_modules:
            if mod in ("用户认证", "权限管理", "多租户架构"):
                layers["后端"].append(mod)
            elif mod in ("支付系统", "订单管理", "计费系统"):
                layers["后端"].append(mod)
            elif mod in ("搜索系统", "推荐系统", "数据分析"):
                layers["后端"].append(mod)
            elif mod in ("消息系统", "通知系统"):
                layers["后端"].append(mod)
            elif mod in ("内容管理", "内容审核", "内容过滤"):
                layers["后端"].append(mod)
            elif mod in ("购物车", "库存管理", "物流跟踪"):
                layers["后端"].append(mod)
            elif mod in ("配置管理", "错误处理", "日志记录"):
                layers["后端"].append(mod)
            elif mod in ("关系管理", "动态/Feed"):
                layers["后端"].append(mod)
            elif mod in ("移动端适配", "管理后台"):
                layers["前端"].append(mod)
            elif mod in ("评论系统", "举报/申诉", "隐私设置"):
                layers["前端"].append(mod)
            else:
                layers["后端"].append(mod)

        # 补充通用层
        layers["数据层"].append("主数据库")
        layers["数据层"].append("缓存(Redis)")
        layers["基础设施"].append("容器化部署")
        layers["基础设施"].append("CI/CD 流水线")

        for layer_name, modules in layers.items():
            if modules:
                lines.append(f"\n**{layer_name}**")
                for m in modules:
                    lines.append(f"  - {m}")
        return "\n".join(lines)

    def _module_list(self, confirmed: List[str], declined: List[str]) -> str:
        lines = ["## 7. 模块清单\n"]
        lines.append("| # | 模块 | 状态 |")
        lines.append("|---|---|---|")
        for i, mod in enumerate(confirmed, 1):
            lines.append(f"| {i} | {mod} | ✅ 已确认 |")
        for i, mod in enumerate(declined, len(confirmed) + 1):
            lines.append(f"| {i} | {mod} | ❌ 已排除 |")
        return "\n".join(lines)

    def _pending_items(self, implicit: List[ImplicitNeed], answers: Dict[str, str]) -> str:
        lines = ["## 8. 待确认项\n"]
        unanswered = []
        for need in implicit:
            q_text = f"是否需要「{need.module}」模块？"
            q_text_alt = f"是否需要「{need.module}」功能？"
            if q_text not in answers and q_text_alt not in answers:
                unanswered.append(need)

        if unanswered:
            for need in unanswered:
                lines.append(f"- [ ] **{need.module}** — {need.reason} (优先级: {need.priority})")
        else:
            lines.append("> 所有隐式需求均已确认 ✅")
        return "\n".join(lines)


# ==================== 主入口函数 ====================

def execute(brief: str, app_type: str = "auto") -> SkillResult:
    """需求放大器主入口

    Args:
        brief: 用户输入的策划案文本
        app_type: 应用类型 (auto=自动识别, ecommerce/saas/tool/content/social)
    """
    try:
        if not brief or not brief.strip():
            return SkillResult(success=False, error="策划案内容不能为空")

        # 1. 解析策划案
        parser = RequirementParser()
        parsed = parser.parse(brief, app_type)

        # 2. 推断隐式需求
        inferrer = ImplicitNeedInferrer()
        implicit_needs = inferrer.infer(parsed)

        # 3. 生成待确认问题
        question_gen = SmartQuestionGenerator()
        questions = question_gen.generate(parsed.features, implicit_needs)

        # 4. 生成 SRS（默认自动采纳推荐答案，生成初版）
        default_answers: Dict[str, str] = {}
        for q in questions:
            default_answers[q.question] = q.recommended_answer

        srs_gen = SRSGenerator()
        srs_doc = srs_gen.generate(parsed, implicit_needs, default_answers)

        # 组装输出
        industry_name = INDUSTRY_KNOWLEDGE_BASE.get(parsed.app_type, {}).get("name", "通用")

        output_parts = []
        output_parts.append(f"🔍 需求放大器 — {industry_name}类应用\n")
        output_parts.append("=" * 50)

        # 解析结果
        output_parts.append(f"\n📋 **显式需求解析**")
        output_parts.append(f"  应用类型: {industry_name}")
        output_parts.append(f"  功能点数: {len(parsed.features)}")
        output_parts.append(f"  技术栈: {', '.join(parsed.tech_stack) or '未指定'}")
        output_parts.append(f"  目标用户: {parsed.target_users}")
        output_parts.append(f"  核心模块: {', '.join(parsed.core_modules) or '未明确'}")

        # 隐式需求
        output_parts.append(f"\n💡 **隐式需求推断** (共 {len(implicit_needs)} 项)")
        for need in implicit_needs:
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(need.priority, "⚪")
            output_parts.append(f"  {icon} {need.module} — {need.reason}")

        # 待确认问题
        if questions:
            output_parts.append(f"\n❓ **待确认问题** (共 {len(questions)} 个)")
            for i, q in enumerate(questions, 1):
                output_parts.append(f"  {i}. {q.question}")
                output_parts.append(f"     💬 推荐答案: {q.recommended_answer}")

        output_parts.append(f"\n{'=' * 50}")
        output_parts.append("📄 SRS 文档已生成（见 data.srs）")

        output = "\n".join(output_parts)

        return SkillResult(
            success=True,
            output=output,
            data={
                "app_type": parsed.app_type,
                "industry_name": industry_name,
                "parsed": {
                    "features": parsed.features,
                    "tech_stack": parsed.tech_stack,
                    "target_users": parsed.target_users,
                    "core_modules": parsed.core_modules,
                },
                "implicit_needs": [
                    {"module": n.module, "reason": n.reason, "priority": n.priority}
                    for n in implicit_needs
                ],
                "questions": [
                    {"question": q.question, "recommended_answer": q.recommended_answer, "related_module": q.related_module}
                    for q in questions
                ],
                "srs": srs_doc,
            },
        )

    except Exception as e:
        return SkillResult(success=False, error=f"需求放大失败: {e}", output=traceback.format_exc())


# ==================== 注册函数 ====================

def register(registry) -> None:
    registry.register(SkillDef(
        name="requirement_amplifier",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "brief": {
                    "type": "string",
                    "description": "用户输入的策划案文本",
                },
                "app_type": {
                    "type": "string",
                    "enum": ["auto", "ecommerce", "saas", "tool", "content", "social"],
                    "description": "应用类型: auto=自动识别, ecommerce=电商, saas=SaaS, tool=工具类, content=内容平台, social=社交",
                    "default": "auto",
                },
            },
            "required": ["brief"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=20,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
