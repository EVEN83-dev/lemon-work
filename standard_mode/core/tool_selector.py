# -*- coding: utf-8 -*-
"""
Tool Selector — 动态工具选择器
================================
按任务相关性自动筛选可用 Skills，减少模型面对的工具列表。

功能：
1. 任务→工具映射 — 根据任务类型推荐相关工具
2. 相关性评分 — 余弦相似度 + 关键词匹配
3. 工具分组 — 按分类组织工具列表
4. 智能裁剪 — 限制工具列表长度以提高模型准确率

设计原则：
- 7B 模型能处理的工具数有限（3-8 个），筛选后精确匹配
- 工具描述和分类标签用于相关性计算
- 支持热更新（新 Skill 注册后自动纳入）
"""

import re
import logging
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


# 任务类型 → 相关工具映射
TASK_TOOL_MAP = {
    "code_reading": [
        "read_file", "list_directory", "grep_search", "search_codebase",
        "scan_project",
    ],
    "code_writing": [
        "read_file", "write_file", "edit_file", "search_codebase",
        "execute_code", "run_command",
    ],
    "code_review": [
        "read_file", "code_reviewer", "security_auditor",
        "grep_search", "search_codebase",
    ],
    "debugging": [
        "read_file", "grep_search", "search_codebase",
        "run_command", "execute_code",
    ],
    "refactoring": [
        "read_file", "edit_file", "search_codebase", "grep_search",
        "test_generator", "code_reviewer",
    ],
    "testing": [
        "read_file", "test_generator", "run_command",
        "execute_code", "grep_search",
    ],
    "documentation": [
        "read_file", "search_codebase", "self_documenter",
        "academic_writer", "web_fetch",
    ],
    "research": [
        "web_search", "web_fetch", "web_researcher",
        "arxiv_researcher", "deep_researcher", "super_researcher",
    ],
    "data_analysis": [
        "read_file", "math_solver", "math_plotter",
        "execute_code", "run_command",
    ],
    "deployment": [
        "read_file", "deploy_helper", "run_command",
        "modern_python_toolchain",
    ],
    "visual_design": [
        "design_blueprint", "frontend_designer", "physics_experiment",
        "math_plotter", "image_processor", "image_analyzer",
    ],
    "file_management": [
        "read_file", "write_file", "edit_file", "delete_file",
        "list_directory", "search_files", "grep_search",
    ],
    "general": [
        "read_file", "search_codebase", "grep_search",
        "web_search", "web_fetch", "todo_write",
    ],
}


class ToolSelector:
    """
    动态工具选择器
    
    使用方式：
        selector = ToolSelector()
        tools = selector.select_tools("帮我写一个排序算法")
        # → ["read_file", "write_file", "edit_file", "search_codebase", "execute_code"]
    """
    
    MAX_TOOLS = 8  # 7B 模型最大工具数
    MIN_TOOLS = 3   # 最少工具数
    
    # 任务类型关键词
    TASK_KEYWORDS = {
        "code_reading": ["看", "查看", "读", "read", "view", "show", "显示", "看看", "检查"],
        "code_writing": ["写", "编写", "创建", "生成", "create", "write", "make", "实现", "开发"],
        "code_review": ["审查", "review", "检查代码", "审计", "audit", "安全"],
        "debugging": ["调试", "debug", "修复", "fix", "bug", "错误", "error", "解决"],
        "refactoring": ["重构", "refactor", "优化", "optimize", "改进", "改善"],
        "testing": ["测试", "test", "单元测试", "unittest", "pytest"],
        "documentation": ["文档", "doc", "文档化", "说明", "注释", "注释化"],
        "research": ["研究", "搜索", "search", "查找", "查询", "调研", "了解"],
        "data_analysis": ["分析", "计算", "数学", "统计", "图表", "数据"],
        "deployment": ["部署", "deploy", "发布", "构建", "build", "docker"],
        "visual_design": ["设计", "design", "画", "图", "可视化", "图表", "UI"],
        "file_management": ["文件", "目录", "移动", "复制", "删除", "重命名"],
    }
    
    def __init__(self):
        self._usage_stats = defaultdict(int)  # 工具使用统计
        self._all_tools: List[Dict] = []      # 所有可用工具
    
    def register_tools(self, tools: List[Dict]):
        """
        注册所有可用工具
        
        Args:
            tools: [{name, description, category, ...}, ...]
        """
        self._all_tools = tools
        logger.info(f"[ToolSelector] 注册 {len(tools)} 个工具")
    
    def select_tools(self, 
                     prompt: str, 
                     max_tools: int = None,
                     context: Optional[Dict] = None) -> List[Dict]:
        """
        根据任务选择相关工具
        
        Args:
            prompt: 用户输入
            max_tools: 最大工具数
            context: 附加上下文
        
        Returns:
            筛选后的工具列表
        """
        if max_tools is None:
            max_tools = self.MAX_TOOLS
        
        if not self._all_tools:
            return []
        
        # 1. 识别任务类型
        task_type = self._identify_task_type(prompt)
        
        # 2. 获取推荐工具列表
        recommended_names = TASK_TOOL_MAP.get(task_type, TASK_TOOL_MAP["general"])
        
        # 3. 从所有工具中筛选
        recommended = []
        other = []
        
        for tool in self._all_tools:
            name = tool.get("name", "")
            if name in recommended_names:
                recommended.append(tool)
            else:
                other.append(tool)
        
        # 4. 评分排序
        scored = []
        for tool in self._all_tools:
            score = self._score_tool_relevance(tool, prompt, task_type)
            scored.append((score, tool))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # 5. 选择前 N 个工具
        selected = []
        selected_names = set()
        
        # 优先添加推荐工具
        for tool in recommended:
            if len(selected) >= max_tools:
                break
            name = tool.get("name", "")
            if name not in selected_names:
                selected.append(tool)
                selected_names.add(name)
        
        # 补充高评分工具
        for score, tool in scored:
            if len(selected) >= max_tools:
                break
            name = tool.get("name", "")
            if name not in selected_names:
                selected.append(tool)
                selected_names.add(name)
        
        # 确保最少工具数
        if len(selected) < self.MIN_TOOLS:
            for tool in self._all_tools:
                if len(selected) >= self.MIN_TOOLS:
                    break
                name = tool.get("name", "")
                if name not in selected_names:
                    selected.append(tool)
                    selected_names.add(name)
        
        logger.info(f"[ToolSelector] 任务: {task_type}, 选择 {len(selected)}/{len(self._all_tools)} 个工具")
        
        return selected[:max_tools]
    
    def _identify_task_type(self, prompt: str) -> str:
        """识别任务类型"""
        prompt_lower = prompt.lower()
        
        scores = defaultdict(int)
        for task_type, keywords in self.TASK_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in prompt_lower:
                    scores[task_type] += 1
        
        if not scores:
            return "general"
        
        return max(scores, key=scores.get)
    
    def _score_tool_relevance(self, 
                               tool: Dict, 
                               prompt: str, 
                               task_type: str) -> float:
        """
        计算工具与任务的相关性分数
        
        评分维度：
        1. 工具名/描述与 prompt 关键词匹配
        2. 工具分类与任务类型匹配
        3. 工具使用频率
        """
        score = 0.0
        prompt_lower = prompt.lower()
        
        name = tool.get("name", "")
        description = tool.get("description", "")
        category = tool.get("category", "")
        
        # 1. 名称匹配
        name_words = re.findall(r'[a-z]+', name.lower())
        for word in name_words:
            if word in prompt_lower:
                score += 0.4
                break
        
        # 2. 描述匹配
        desc_words = set(re.findall(r'[\w\u4e00-\u9fff]+', description.lower()))
        prompt_words = set(re.findall(r'[\w\u4e00-\u9fff]+', prompt_lower))
        overlap = desc_words & prompt_words
        if overlap:
            score += 0.2 * min(len(overlap), 5)
        
        # 3. 分类匹配
        recommended = TASK_TOOL_MAP.get(task_type, [])
        if name in recommended:
            score += 0.3
        
        # 4. 使用频率加分
        usage = self._usage_stats.get(name, 0)
        score += min(usage * 0.05, 0.2)
        
        return score
    
    def record_usage(self, tool_name: str):
        """记录工具使用"""
        self._usage_stats[tool_name] += 1
    
    def get_tool_groups(self) -> Dict[str, List[Dict]]:
        """按分类获取工具分组"""
        groups = defaultdict(list)
        for tool in self._all_tools:
            category = tool.get("category", "other")
            groups[category].append(tool)
        return dict(groups)
    
    def format_for_prompt(self, tools: List[Dict]) -> str:
        """格式化工具列表为 prompt 文本"""
        lines = []
        for tool in tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)
    
    @property
    def stats(self) -> Dict:
        return {
            'total_tools': len(self._all_tools),
            'usage_stats': dict(self._usage_stats),
        }


# 全局单例
_selector_instance: Optional[ToolSelector] = None


def get_tool_selector() -> ToolSelector:
    global _selector_instance
    if _selector_instance is None:
        _selector_instance = ToolSelector()
    return _selector_instance