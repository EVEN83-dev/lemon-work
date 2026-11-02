# -*- coding: utf-8 -*-
"""任务复杂度分类（v5.5 补全）。

驱动：
  - 引擎成本路由（COMPLEX→deepseek / SIMPLE→ollama）
  - agent_chat 迭代上限（SIMPLE=5 / MODERATE=10 / COMPLEX=15）
"""
from enum import Enum
import re


class TaskComplexity(Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


# 关键词启发式（中文 + 英文），用于无模型时的轻量分类
_COMPLEX_HINTS = [
    "重构", "rebuild", "重构成", "架构", "architecture", "设计模式", "design pattern",
    "多文件", "跨模块", "全量", "迁移", "migrate", "部署", "deploy", "并发", "多线程",
    "性能优化", "optimize", "分布式", "算法", "algorithm", "数据库", "database",
    "analyze", "分析", "调研", "对比", "compare", "对比分析", "全面", "详细",
]
_MODERATE_HINTS = [
    "修改", "edit", "实现", "implement", "添加", "add", "修复", "fix", "bug",
    "函数", "function", "类", "class", "接口", "api", "配置", "config",
    # ★ v356: 金融多步业务组合词 —— "查询+推荐+演示切页"这类组合动作
    #   至少给 MODERATE（20 轮），防止被 SIMPLE 12 轮预算掐断长链路
    "推荐", "演示", "联动", "办理", "切到", "切换到", "帮我看看", "汇总", "报告",
]


class _ClassificationResult:
    def __init__(self, complexity: TaskComplexity, score: float = 0.0, signals=None):
        self.complexity = complexity
        self.score = score
        self.signals = signals or []

    @property
    def value(self):
        return self.complexity.value


class TaskClassifier:
    def classify(self, prompt: str) -> _ClassificationResult:
        if not prompt:
            return _ClassificationResult(TaskComplexity.SIMPLE)
        text = prompt.lower()
        # 信号计数
        complex_hits = [h for h in _COMPLEX_HINTS if h.lower() in text]
        moderate_hits = [h for h in _MODERATE_HINTS if h.lower() in text]
        # 长度信号：>200 字倾向复杂，>80 字倾向中等
        length = len(prompt)
        score = len(complex_hits) * 2 + len(moderate_hits) * 1
        if length > 200:
            score += 2
        elif length > 80:
            score += 1
        # 多步骤信号：包含"然后/再/接着/最后/步骤"
        if re.search(r"然后|再|接着|最后|步骤|先.*再", prompt):
            score += 1
        if score >= 3 or len(complex_hits) >= 1:
            comp = TaskComplexity.COMPLEX
        elif score >= 1 or len(moderate_hits) >= 1:
            comp = TaskComplexity.MODERATE
        else:
            comp = TaskComplexity.SIMPLE
        return _ClassificationResult(comp, float(score), complex_hits + moderate_hits)


_CLASSIFIER_INSTANCE = None


def get_task_classifier() -> TaskClassifier:
    global _CLASSIFIER_INSTANCE
    if _CLASSIFIER_INSTANCE is None:
        _CLASSIFIER_INSTANCE = TaskClassifier()
    return _CLASSIFIER_INSTANCE
