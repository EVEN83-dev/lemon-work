# -*- coding: utf-8 -*-
"""
Task Classifier — P12 蒸馏 Step 3
==================================
根据任务复杂度自动选择引擎：
- SIMPLE → 本地 Ollama (免费)
- MODERATE → DeepSeek API (性价比)
- COMPLEX → MiMo API (最强能力)

分类规则：
1. 关键词匹配：代码生成/重构/架构 → 高复杂度
2. 上下文长度：长 prompt → 需要大上下文
3. 工具调用需求：多步骤 → 需要强 Agent 能力
4. 文件操作范围：多文件 → 需要长程记忆
"""

import re
from enum import Enum
from typing import Dict, Optional, Tuple


class TaskComplexity(Enum):
    SIMPLE = "simple"       # 简单问答/代码解释/单文件修改
    MODERATE = "moderate"   # 代码重构/调试/多步骤任务
    COMPLEX = "complex"     # 架构设计/多文件重构/长程任务


class EngineRecommendation:
    """引擎推荐结果"""
    def __init__(self, engine: str, complexity: TaskComplexity, reason: str, confidence: float):
        self.engine = engine
        self.complexity = complexity
        self.reason = reason
        self.confidence = confidence  # 0.0 ~ 1.0
    
    def to_dict(self) -> Dict:
        return {
            "engine": self.engine,
            "complexity": self.complexity.value,
            "reason": self.reason,
            "confidence": self.confidence,
        }


class TaskClassifier:
    """任务分类器 — 蒸馏路由核心"""
    
    # 复杂度关键词
    SIMPLE_KEYWORDS = [
        "解释", "介绍", "什么是", "怎么用", "示例", "example", "文档",
        "注释", "打印", "hello", "格式化", "重命名", "查找", "搜索",
        "hello world", "简单", "基础", "basic",
    ]
    
    MODERATE_KEYWORDS = [
        "重构", "调试", "修复", "优化", "实现", "编写", "创建", "添加", "修改", "多文件", "功能",
        "bug", "debug",
        "添加功能", "改进", "implement",
        "单元测试", "unittest", "pytest",
    ]
    
    COMPLEX_KEYWORDS = [
        "架构", "设计", "系统", "项目", "框架", "部署", "分布式", "微服务", "全栈", "大文件", "迁移", "集成",
        "从零",
        "完整项目", "多模块", "微服务", "部署",
        "重构整个", "重写", "迁移", "升级",
        "安全审计", "性能优化", "并发",
        # ★ v5.6: 调研/对比/分析类任务 → 直接归 COMPLEX（需联网检索 + 多步本地读取）
        "调研", "调查", "对比", "比较", "分析", "市场", "同类", "竞品", "市面上",
        "市面", "有哪些", "类似项目", "开源项目", "技术亮点", "技术创新", "定位",
        "差异", "不同", "评估", "review", "analyze", "compare", "research", "survey",
    ]
    
    # 工具调用需求关键词
    MULTI_TOOL_KEYWORDS = [
        "先...然后", "第一步", "接下来", "依次",
        "多个文件", "全部", "所有", "整个项目",
        "生成并测试", "写代码并运行",
    ]
    
    def classify(self, prompt: str, context: Optional[Dict] = None) -> EngineRecommendation:
        """
        分类任务并推荐引擎
        
        Args:
            prompt: 用户输入
            context: 附加上下文（文件数、历史长度等）
        
        Returns:
            EngineRecommendation 对象
        """
        score = 0.0  # 复杂度分数，越高越复杂
        reasons = []
        
        # 1. 关键词匹配
        prompt_lower = prompt.lower()
        
        for kw in self.SIMPLE_KEYWORDS:
            if kw.lower() in prompt_lower:
                score -= 0.1
                break
        
        moderate_hits = 0
        for kw in self.MODERATE_KEYWORDS:
            if kw.lower() in prompt_lower:
                moderate_hits += 1
        if moderate_hits >= 2:
            score += 0.3
            reasons.append(f"检测到 {moderate_hits} 个中等复杂度关键词")
        elif moderate_hits == 1:
            score += 0.15
        
        complex_hits = 0
        last_complex_kw = ""
        for kw in self.COMPLEX_KEYWORDS:
            if kw.lower() in prompt_lower:
                complex_hits += 1
                last_complex_kw = kw
        if complex_hits >= 2:
            score += 1.0
            reasons.append(f"检测到 {complex_hits} 个高复杂度关键词")
        elif complex_hits == 1:
            score += 0.3
            reasons.append(f"检测到高复杂度关键词: {last_complex_kw}")

        # ★ v5.6: 强调研/对比信号 — 直接强制 COMPLEX（调研类任务必须联网+多步本地读取）
        _STRONG_RESEARCH_KWS = ["调研", "对比", "比较", "竞品", "市场", "市面上", "类似项目", "技术创新", "技术亮点", "有哪些不同", "开源项目", "analyze", "compare", "research", "survey"]
        _strong_hits = [k for k in _STRONG_RESEARCH_KWS if k.lower() in prompt_lower]
        if _strong_hits:
            score += 1.5
            reasons.append(f"检测到调研/对比强信号: {_strong_hits[:3]}")

        # 2. 工具调用需求
        multi_tool_hits = 0
        for kw in self.MULTI_TOOL_KEYWORDS:
            if kw.lower() in prompt_lower:
                multi_tool_hits += 1
        if multi_tool_hits >= 2:
            score += 0.4
            reasons.append("检测到多步骤工具调用需求")
        
        if len(prompt) > 2000:
            score += 0.3
        elif len(prompt) > 1000:
            score += 0.1
        
        _multi_action_kws = ["然后", "同时", "并且", "接着", "之后", "还要", "and then", "after that"]
        _multi_action_hits = sum(1 for kw in _multi_action_kws if kw in prompt.lower())
        if _multi_action_hits >= 2:
            score += 0.4
        elif _multi_action_hits >= 1:
            score += 0.2
        
        # 3. 上下文长度
        if context:
            file_count = context.get("file_count", 0)
            if file_count >= 5:
                score += 0.4
                reasons.append(f"涉及 {file_count} 个文件")
            elif file_count >= 2:
                score += 0.2
                reasons.append(f"涉及 {file_count} 个文件")
            
            history_length = context.get("history_length", 0)
            if history_length > 10:
                score += 0.3
                reasons.append("长对话历史")
        
        # 4. prompt 长度 — already scored above, skip duplicate
        
        # 5. 代码块检测
        code_blocks = len(re.findall(r'```', prompt))
        if code_blocks >= 4:
            score += 0.3
            reasons.append("多个代码块")
        
        # 确定复杂度等级
        if score >= 0.7:
            complexity = TaskComplexity.COMPLEX
            engine = "mimocode"
            confidence = min(score, 1.0)
        elif score >= 0.3:
            complexity = TaskComplexity.MODERATE
            engine = "deepseek"
            confidence = min(score, 0.85)
        else:
            complexity = TaskComplexity.SIMPLE
            engine = "ollama"
            confidence = max(0.5, 1.0 - abs(score))
        
        if not reasons:
            reasons.append("任务复杂度较低，适合本地处理")
        
        return EngineRecommendation(
            engine=engine,
            complexity=complexity,
            reason="; ".join(reasons),
            confidence=confidence,
        )
    
    def should_use_api(self, prompt: str, context: Optional[Dict] = None) -> Tuple[bool, str]:
        """快速判断是否应使用 API（供 UI 提示使用）"""
        result = self.classify(prompt, context)
        if result.complexity == TaskComplexity.COMPLEX:
            return True, f"建议使用 MiMo API ({result.reason})"
        elif result.complexity == TaskComplexity.MODERATE:
            return True, f"建议使用 DeepSeek API ({result.reason})"
        return False, "本地模型可处理"


# 全局单例
_classifier_instance: Optional[TaskClassifier] = None


def get_task_classifier() -> TaskClassifier:
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = TaskClassifier()
    return _classifier_instance