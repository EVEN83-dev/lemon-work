# -*- coding: utf-8 -*-
"""
Agent Pipeline — P12 蒸馏 Step 5
==================================
本地 Agent Pipeline：7B 模型 + Few-shot RAG + Skill 调用引擎。

核心流程：
1. 接收用户输入 → TaskClassifier 分类
2. 简单任务 → KnowledgeBase 检索 few-shot 示例
3. 构建增强 prompt → Ollama 7B 模型推理
4. 解析模型输出中的工具调用 → 执行 Skills
5. 收集结果 → 生成最终回复

设计原则：
- 最小化 API 调用，最大化本地处理
- 自动降级：本地失败时回退到 API
- 工具调用解析：从模型输出中提取代码块作为指令
"""

import re
import json
import time
import threading
import logging
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum

from .task_classifier import TaskClassifier, TaskComplexity, get_task_classifier
from .knowledge_base import KnowledgeBase, get_knowledge_base
from .interaction_logger import get_interaction_logger

logger = logging.getLogger(__name__)


class PipelineStage(Enum):
    """Pipeline 阶段"""
    IDLE = "idle"
    CLASSIFYING = "classifying"
    RETRIEVING = "retrieving"
    REASONING = "reasoning"
    EXECUTING_TOOLS = "executing_tools"
    SYNTHESIZING = "synthesizing"
    DONE = "done"
    ERROR = "error"


@dataclass
class PipelineResult:
    """Pipeline 执行结果"""
    success: bool
    response: str
    engine: str  # 实际使用的引擎
    complexity: TaskComplexity
    stages_completed: List[PipelineStage]
    tool_calls: List[Dict] = field(default_factory=list)
    few_shot_used: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None


class AgentPipeline:
    """
    本地 Agent Pipeline — 蒸馏核心执行引擎
    
    使用方式：
        pipeline = AgentPipeline(ollama_adapter, skill_executor)
        result = pipeline.run("帮我写一个排序算法")
    """
    
    MAX_TOOL_ROUNDS = 5          # 最大工具调用轮次
    MAX_RETRY = 2                # 最大重试次数
    TOOL_CALL_TIMEOUT = 30       # 单次工具调用超时（秒）
    
    # 工具调用模式：匹配 `[TOOL:name]` 或 ````tool:name ... ````
    TOOL_PATTERN = re.compile(
        r'\[TOOL:(\w+)\s*(.*?)\]|'           # [TOOL:name args]
        r'```tool:(\w+)\s*\n(.*?)\n```',     # ```tool:name\nargs\n```
        re.DOTALL
    )
    
    def __init__(self, 
                 ollama_adapter=None,
                 skill_executor=None,
                 interaction_logger=None):
        """
        Args:
            ollama_adapter: Ollama 适配器（用于调用本地模型）
            skill_executor: Skill 执行器（用于执行工具调用）
            interaction_logger: 交互日志记录器
        """
        self._ollama = ollama_adapter
        self._skill_executor = skill_executor
        self._classifier = get_task_classifier()
        self._knowledge_base = get_knowledge_base()
        self._logger = interaction_logger or get_interaction_logger()
        
        self._lock = threading.Lock()
        self._stage: PipelineStage = PipelineStage.IDLE
        self._cancel_flag = False
        
        # 统计
        self._stats = {
            'total_runs': 0,
            'successful_runs': 0,
            'local_runs': 0,
            'api_fallback': 0,
            'avg_duration_ms': 0.0,
        }
    
    @property
    def stage(self) -> PipelineStage:
        return self._stage
    
    @property
    def stats(self) -> Dict:
        return dict(self._stats)
    
    def cancel(self):
        """取消当前执行"""
        self._cancel_flag = True
    
    def run(self, 
            prompt: str, 
            context: Optional[Dict] = None,
            session_id: str = "default",
            engine_override: Optional[str] = None) -> PipelineResult:
        """
        执行 Agent Pipeline
        
        Args:
            prompt: 用户输入
            context: 附加上下文（文件列表、历史等）
            session_id: 会话 ID
            engine_override: 强制指定引擎（跳过分类器）
        
        Returns:
            PipelineResult
        """
        start_time = time.time()
        stages = []
        tool_calls = []
        self._cancel_flag = False
        
        self._stats['total_runs'] += 1
        
        try:
            # Stage 1: 分类
            if engine_override:
                recommendation = self._classifier.classify(prompt, context)
                recommendation.engine = engine_override
            else:
                self._stage = PipelineStage.CLASSIFYING
                recommendation = self._classifier.classify(prompt, context)
            stages.append(PipelineStage.CLASSIFYING)
            
            # 非简单任务 → 直接路由到 API（Pipeline 不处理）
            if recommendation.complexity != TaskComplexity.SIMPLE:
                return PipelineResult(
                    success=False,
                    response="",
                    engine=recommendation.engine,
                    complexity=recommendation.complexity,
                    stages_completed=stages,
                    error=f"任务复杂度为 {recommendation.complexity.value}，应由 API 处理"
                )
            
            # Stage 2: 检索 Few-shot 示例
            self._stage = PipelineStage.RETRIEVING
            few_shot_prompt = self._knowledge_base.format_few_shot(prompt, k=3)
            few_shot_count = len(self._knowledge_base.retrieve(prompt, k=3))
            stages.append(PipelineStage.RETRIEVING)
            
            # Stage 3: 构建增强 prompt
            enhanced_prompt = self._build_system_prompt() + "\n\n"
            if few_shot_prompt:
                enhanced_prompt += few_shot_prompt + "\n\n"
            enhanced_prompt += f"用户问题: {prompt}\n\n请回答："
            
            # Stage 4: 本地模型推理
            self._stage = PipelineStage.REASONING
            response = self._call_ollama(enhanced_prompt)
            stages.append(PipelineStage.REASONING)
            
            if self._cancel_flag:
                return PipelineResult(
                    success=False, response="", engine="ollama",
                    complexity=TaskComplexity.SIMPLE, stages_completed=stages,
                    error="用户取消"
                )
            
            # Stage 5: 解析并执行工具调用（多轮）
            self._stage = PipelineStage.EXECUTING_TOOLS
            for round_num in range(self.MAX_TOOL_ROUNDS):
                if self._cancel_flag:
                    break
                
                tool_matches = self._parse_tool_calls(response)
                if not tool_matches:
                    break
                
                stages.append(PipelineStage.EXECUTING_TOOLS)
                
                # 执行工具调用
                tool_results = self._execute_tools(tool_matches)
                tool_calls.extend(tool_matches)
                
                # 将工具结果反馈给模型
                feedback = self._format_tool_results(tool_results)
                response = self._call_ollama(
                    enhanced_prompt + "\n\n" + response + "\n\n" + feedback + "\n\n请继续回答："
                )
            
            # Stage 6: 最终合成
            self._stage = PipelineStage.SYNTHESIZING
            stages.append(PipelineStage.SYNTHESIZING)
            
            duration_ms = (time.time() - start_time) * 1000
            
            # 记录交互日志
            self._logger.log_interaction(
                session_id=session_id,
                prompt=prompt,
                response=response,
                engine="ollama",
                model="qwen2.5:7b",
                tool_calls=tool_calls,
                duration_ms=duration_ms,
            )
            
            # 更新统计
            self._stats['successful_runs'] += 1
            self._stats['local_runs'] += 1
            alpha = 0.1
            self._stats['avg_duration_ms'] = (
                alpha * duration_ms + (1 - alpha) * self._stats['avg_duration_ms']
            )
            
            self._stage = PipelineStage.DONE
            stages.append(PipelineStage.DONE)
            
            return PipelineResult(
                success=True,
                response=response,
                engine="ollama",
                complexity=TaskComplexity.SIMPLE,
                stages_completed=stages,
                tool_calls=tool_calls,
                few_shot_used=few_shot_count,
                duration_ms=duration_ms,
            )
            
        except Exception as e:
            logger.error(f"[AgentPipeline] 执行失败: {e}")
            self._stage = PipelineStage.ERROR
            stages.append(PipelineStage.ERROR)
            
            return PipelineResult(
                success=False,
                response="",
                engine="ollama",
                complexity=TaskComplexity.SIMPLE,
                stages_completed=stages,
                error=str(e),
            )
    
    def _build_system_prompt(self) -> str:
        """构建系统 prompt"""
        available_tools = self._get_available_tools()
        return f"""你是一个 AI 编程助手，运行在本地 7B 模型上。

你可以使用以下工具：
{available_tools}

使用工具时，用以下格式：
[TOOL:工具名 参数]

例如：
[TOOL:read_file path=main.py]
[TOOL:search_codebase query=认证逻辑]

请用中文回复，保持简洁专业。"""
    
    def _get_available_tools(self) -> str:
        """获取可用工具列表"""
        tools = [
            "read_file(path) - 读取文件",
            "write_file(path, content) - 写入文件",
            "edit_file(path, old, new) - 编辑文件",
            "search_codebase(query) - 搜索代码库",
            "grep_search(pattern) - 正则搜索",
            "list_directory(path) - 列出目录",
            "run_command(cmd) - 执行命令",
            "web_search(query) - 网络搜索",
            "web_fetch(url) - 获取网页内容",
            "todo_write(tasks) - 任务管理",
        ]
        return "\n".join(f"  - {t}" for t in tools)
    
    def _call_ollama(self, prompt: str) -> str:
        """调用 Ollama 本地模型"""
        if self._ollama is None:
            return "[Pipeline] Ollama 适配器未配置，请检查引擎设置。"
        
        messages = [{"role": "user", "content": prompt}]
        
        for attempt in range(self.MAX_RETRY):
            try:
                response = self._ollama.chat(
                    messages,
                    model="qwen2.5:7b",
                    num_predict=1500,
                    temperature=0.7,
                )
                if response and len(response.strip()) > 10:
                    return response
            except Exception as e:
                logger.warning(f"[AgentPipeline] Ollama 调用失败 (尝试 {attempt+1}/{self.MAX_RETRY}): {e}")
                if attempt < self.MAX_RETRY - 1:
                    time.sleep(1)
        
        return "[Pipeline] 本地模型调用失败，请稍后重试或切换到 API 引擎。"
    
    def _parse_tool_calls(self, text: str) -> List[Dict]:
        """从模型输出中解析工具调用"""
        calls = []
        
        for match in self.TOOL_PATTERN.finditer(text):
            if match.group(1):  # [TOOL:name args]
                tool_name = match.group(1)
                args_str = match.group(2).strip()
            elif match.group(3):  # ```tool:name\nargs\n```
                tool_name = match.group(3)
                args_str = match.group(4).strip()
            else:
                continue
            
            # 解析参数
            args = {}
            for arg_match in re.finditer(r'(\w+)\s*=\s*["\']?([^"\'\s,]+)["\']?', args_str):
                args[arg_match.group(1)] = arg_match.group(2)
            if not args and args_str:
                args = {"_raw": args_str}
            
            calls.append({
                "tool": tool_name,
                "args": args,
                "raw": match.group(0),
            })
        
        return calls
    
    def _execute_tools(self, tool_calls: List[Dict]) -> List[Dict]:
        """执行工具调用"""
        results = []
        
        for call in tool_calls:
            tool_name = call["tool"]
            args = call["args"]
            
            result = {
                "tool": tool_name,
                "success": False,
                "output": "",
                "error": None,
            }
            
            if self._skill_executor is None:
                result["error"] = "Skill 执行器未配置"
                results.append(result)
                continue
            
            try:
                output = self._skill_executor.execute(tool_name, args)
                result["success"] = True
                result["output"] = str(output)[:2000]  # 截断过长输出
            except Exception as e:
                result["error"] = str(e)
            
            results.append(result)
        
        return results
    
    def _format_tool_results(self, results: List[Dict]) -> str:
        """格式化工具执行结果"""
        lines = ["工具执行结果：", ""]
        for r in results:
            status = "✅" if r["success"] else "❌"
            lines.append(f"{status} {r['tool']}:")
            if r["success"]:
                lines.append(f"   {r['output'][:500]}")
            else:
                lines.append(f"   错误: {r['error']}")
            lines.append("")
        return "\n".join(lines)
    
    def execute_full_pipeline(self, user_prompt: str) -> dict:
        """
        执行完整端到端 Pipeline

        完整流程：
        1. TaskClassifier 分类任务
        2. SuperBrain 分解复杂任务
        3. ToolSelector 选择工具
        4. SkillCaller 调用技能（带降级回退）
        5. SkillChain 多步执行
        6. 返回结构化结果

        Args:
            user_prompt: 用户输入

        Returns:
            包含完整执行信息的字典
        """
        start_time = time.time()
        result = {
            "success": False,
            "response": "",
            "complexity": None,
            "classification": None,
            "decomposed_tasks": [],
            "selected_tools": [],
            "skill_traces": [],
            "chain_result": None,
            "error": None,
            "duration_ms": 0.0,
        }

        try:
            # ---- Step 1: 任务分类 ----
            self._stage = PipelineStage.CLASSIFYING
            recommendation = self._classifier.classify(user_prompt)
            result["complexity"] = recommendation.complexity.value
            result["classification"] = recommendation.to_dict()
            logger.info(
                "[execute_full_pipeline] 任务分类: complexity=%s, engine=%s, confidence=%.2f",
                recommendation.complexity.value,
                recommendation.engine,
                recommendation.confidence,
            )

            # ---- Step 2: 复杂任务分解 (SuperBrain) ----
            if recommendation.complexity in (TaskComplexity.MODERATE, TaskComplexity.COMPLEX):
                try:
                    from .superbrain import get_superbrain
                    superbrain = get_superbrain()
                    orchestration_result = superbrain.orchestrate_and_execute(user_prompt)
                    result["decomposed_tasks"] = orchestration_result.get("subtasks", [])
                    if orchestration_result.get("success"):
                        result["response"] = orchestration_result.get("final_output", "")
                        result["success"] = True
                        logger.info(
                            "[execute_full_pipeline] SuperBrain 成功处理，子任务数=%d",
                            len(orchestration_result.get("subtasks", [])),
                        )
                except Exception as e:
                    logger.warning("[execute_full_pipeline] SuperBrain 分解失败: %s", e)
                    result["decomposed_tasks"] = [{"error": str(e)}]

            # ---- Step 3: 工具选择 (ToolSelector) ----
            self._stage = PipelineStage.RETRIEVING
            selected_tools = []
            try:
                from .tool_selector import get_tool_selector
                tool_selector = get_tool_selector()
                selected_tools = tool_selector.select_tools(user_prompt)
                result["selected_tools"] = [
                    {"name": t.get("name", ""), "description": t.get("description", "")}
                    for t in selected_tools
                ]
                logger.info(
                    "[execute_full_pipeline] 工具选择完成，选中 %d 个工具",
                    len(selected_tools),
                )
            except Exception as e:
                logger.warning("[execute_full_pipeline] 工具选择失败: %s", e)

            # ---- Step 4: SkillCaller 调用技能 (带降级回退) ----
            self._stage = PipelineStage.EXECUTING_TOOLS
            try:
                from .skill_caller import get_skill_caller
                skill_caller = get_skill_caller()
                tool_defs = selected_tools if selected_tools else []

                if tool_defs:
                    traces, response, strategy = skill_caller.smart_call(
                        prompt=user_prompt,
                        tools=tool_defs,
                        ollama_engine=self._ollama,
                    )
                    result["skill_traces"] = [
                        {
                            "tool": t.tool_name,
                            "status": t.status.value,
                            "strategy": t.strategy.value,
                            "result": t.result[:200] if t.result else "",
                            "duration_ms": t.duration_ms,
                        }
                        for t in traces
                    ]
                    if response and not result["response"]:
                        result["response"] = response
                    logger.info(
                        "[execute_full_pipeline] SkillCaller 完成，策略=%s，调用数=%d",
                        strategy.value,
                        len(traces),
                    )
            except Exception as e:
                logger.warning("[execute_full_pipeline] SkillCaller 调用失败: %s", e)

            # ---- Step 5: SkillChain 多步执行 ----
            if recommendation.complexity in (TaskComplexity.MODERATE, TaskComplexity.COMPLEX):
                try:
                    from .skill_chain import SkillChain, ChainStep, get_predefined_chains
                    predefined = get_predefined_chains()
                    chain = self._find_matching_chain(user_prompt, predefined)

                    if chain and self._skill_executor:
                        chain_result = chain.execute(
                            router=self._skill_executor,
                            agent_id="pipeline",
                            initial_context={"user_prompt": user_prompt},
                        )
                        result["chain_result"] = chain_result.to_dict()
                        if chain_result.success and chain_result.final_output:
                            result["response"] = chain_result.final_output
                        logger.info(
                            "[execute_full_pipeline] SkillChain 完成，成功=%s，步骤=%d/%d",
                            chain_result.success,
                            chain_result.executed_steps,
                            chain_result.total_steps,
                        )
                except Exception as e:
                    logger.warning("[execute_full_pipeline] SkillChain 执行失败: %s", e)

            # ---- Step 6: 回退到基础 pipeline ----
            if not result["response"]:
                self._stage = PipelineStage.REASONING
                pipeline_result = self.run(user_prompt)
                result["response"] = pipeline_result.response
                result["success"] = pipeline_result.success
                if pipeline_result.error:
                    result["error"] = pipeline_result.error
            else:
                result["success"] = True

            self._stage = PipelineStage.DONE

        except Exception as e:
            logger.error("[execute_full_pipeline] 执行失败: %s", e)
            result["error"] = str(e)
            self._stage = PipelineStage.ERROR
        finally:
            result["duration_ms"] = (time.time() - start_time) * 1000

        return result

    def _find_matching_chain(self, prompt: str, predefined_chains: dict):
        """根据 prompt 查找匹配的预定义 SkillChain"""
        prompt_lower = prompt.lower()

        chain_keywords = {
            "research_debate_report": ["调研", "报告", "研究", "research", "report", "辩驳"],
            "math_solve_visualize": ["数学", "方程", "函数", "math", "solve", "可视化"],
            "data_pipeline": ["数据", "分析", "可视化", "data", "analysis", "ppt"],
            "image_ocr_debate": ["图像", "图片", "ocr", "image", "辩驳"],
        }

        best_chain = None
        best_score = 0

        for chain_name, keywords in chain_keywords.items():
            score = sum(1 for kw in keywords if kw in prompt_lower)
            if score > best_score and chain_name in predefined_chains:
                best_score = score
                best_chain = predefined_chains[chain_name]

        if best_chain:
            logger.info(
                "[_find_matching_chain] 匹配到 chain: %s (score=%d)",
                best_chain.name, best_score,
            )

        return best_chain

    def get_pipeline_status(self) -> Dict:
        """获取 Pipeline 状态"""
        return {
            "stage": self._stage.value,
            "stats": dict(self._stats),
            "kb_stats": self._knowledge_base.get_stats(),
        }


# 全局单例
_pipeline_instance: Optional[AgentPipeline] = None
_pipeline_lock = threading.Lock()


def get_agent_pipeline(ollama_adapter=None, skill_executor=None) -> AgentPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        with _pipeline_lock:
            if _pipeline_instance is None:
                _pipeline_instance = AgentPipeline(
                    ollama_adapter=ollama_adapter,
                    skill_executor=skill_executor,
                )
    return _pipeline_instance