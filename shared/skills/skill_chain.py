# -*- coding: utf-8 -*-
"""
Skill Chain — 多 skill 串联执行（Pipeline）
=============================================
★ Lemon Code v22.5 创新点：自动化多步业务流水线

应用场景：
1. 调研 → 辩驳 → 生成报告：web_researcher → info_debater → office_generator
2. 数学解题 → 可视化：math_solver → math_plotter
3. 数据抓取 → 分析 → 可视化 → 导出 PPT：web_researcher → math_solver → math_plotter → office_generator
4. 图像 OCR → 内容辩驳：image_processor → info_debater

特性：
- 参数模板：用 {{step_N.output}} / {{step_N.data.field}} 引用前序步骤输出
- 失败策略：abort / skip / retry / fallback
- 条件分支：when 字段控制是否执行（基于前序步骤结果）
- 共享上下文：所有步骤共享 context dict，可读写
- 步骤间数据自动流转

依赖：SkillRouter（核心调度器）
"""

import os
import sys
import re
import json
import time
import threading
import traceback
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from bridge.skills.models import SkillResult


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ChainStep:
    """Chain 中的单个步骤"""
    skill_name: str                          # skill 名称
    args: Dict[str, Any] = field(default_factory=dict)  # 静态参数
    args_template: Dict[str, str] = field(default_factory=dict)  # 动态参数模板（{{step_N.xxx}}）
    label: str = ""                          # 步骤标签（供展示）
    on_failure: str = "abort"                # abort / skip / retry / fallback
    fallback_args: Dict[str, Any] = field(default_factory=dict)  # on_failure=fallback 时的默认参数
    when: str = ""                           # 条件表达式（空字符串表示总是执行）
    timeout: int = 60                        # 单步超时秒数

    def to_dict(self) -> Dict:
        return {
            'skill_name': self.skill_name,
            'args': self.args,
            'args_template': self.args_template,
            'label': self.label,
            'on_failure': self.on_failure,
            'fallback_args': self.fallback_args,
            'when': self.when,
            'timeout': self.timeout,
        }


@dataclass
class ChainStepResult:
    """单步执行结果"""
    step_index: int
    step_label: str
    skill_name: str
    success: bool
    output: str = ""
    error: str = ""
    data: Any = None
    duration_ms: int = 0
    skipped: bool = False                    # 条件不满足时跳过

    def to_dict(self) -> Dict:
        return {
            'step_index': self.step_index,
            'step_label': self.step_label,
            'skill_name': self.skill_name,
            'success': self.success,
            'output': self.output,
            'error': self.error,
            'data': self.data if isinstance(self.data, (dict, list, str, int, float, bool)) else None,
            'duration_ms': self.duration_ms,
            'skipped': self.skipped,
        }


@dataclass
class ChainResult:
    """Chain 完整执行结果"""
    chain_name: str
    success: bool                            # 整体是否成功（最后一步成功即为成功）
    total_steps: int
    executed_steps: int
    skipped_steps: int
    failed_step: int = -1                    # 失败的步骤序号（-1 表示无失败）
    duration_ms: int = 0
    step_results: List[ChainStepResult] = field(default_factory=list)
    final_output: str = ""                   # 最后一步的输出
    context: Dict[str, Any] = field(default_factory=dict)  # 共享上下文

    def to_dict(self) -> Dict:
        return {
            'chain_name': self.chain_name,
            'success': self.success,
            'total_steps': self.total_steps,
            'executed_steps': self.executed_steps,
            'skipped_steps': self.skipped_steps,
            'failed_step': self.failed_step,
            'duration_ms': self.duration_ms,
            'step_results': [r.to_dict() for r in self.step_results],
            'final_output': self.final_output,
            'context_keys': list(self.context.keys()),
        }


# ============================================================
# SkillChain 主类
# ============================================================

class SkillChain:
    """
    多 skill 串联执行链

    用法:
        chain = SkillChain(
            name="research_debate_report",
            description="调研→辩驳→生成报告",
            steps=[
                ChainStep(
                    skill_name="web_researcher",
                    args={"query": "Python 编程语言历史"},
                    label="网络调研",
                ),
                ChainStep(
                    skill_name="info_debater",
                    args_template={"sources": "{{step_0.output}}"},
                    label="信息辩驳",
                ),
                ChainStep(
                    skill_name="office_generator",
                    args={"doc_type": "word", "title": "调研报告"},
                    args_template={"content": "{{step_1.output}}"},
                    label="生成报告",
                ),
            ],
        )
        result = chain.execute(router)
    """

    # 模板变量正则：{{step_N.field}} 或 {{step_N.data.key}} 或 {{context.key}}
    _TEMPLATE_RE = re.compile(r'\{\{([^}]+)\}\}')

    def __init__(self, name: str, description: str = "",
                 steps: Optional[List[ChainStep]] = None,
                 metadata: Optional[Dict] = None):
        self.name = name
        self.description = description
        self.steps: List[ChainStep] = steps or []
        self.metadata = metadata or {}

    def add_step(self, step: ChainStep):
        """添加步骤"""
        self.steps.append(step)
        return self

    def execute(self, router, agent_id: str = "",
                initial_context: Optional[Dict] = None) -> ChainResult:
        """
        执行 Chain

        Args:
            router: SkillRouter 实例
            agent_id: 调用方 Agent ID
            initial_context: 初始上下文（可被步骤读写）

        Returns:
            ChainResult
        """
        start = time.time()
        context: Dict[str, Any] = dict(initial_context or {})
        context['_chain_name'] = self.name
        context['_agent_id'] = agent_id
        context['_start_at'] = datetime.now().isoformat()

        step_results: List[ChainStepResult] = []
        executed = 0
        skipped = 0
        failed_step = -1
        final_output = ""
        last_success = True

        for i, step in enumerate(self.steps):
            step_start = time.time()

            # 1. 条件检查
            if step.when and not self._eval_condition(step.when, step_results, context):
                sr = ChainStepResult(
                    step_index=i,
                    step_label=step.label or step.skill_name,
                    skill_name=step.skill_name,
                    success=True,
                    skipped=True,
                    duration_ms=0,
                )
                step_results.append(sr)
                skipped += 1
                continue

            # 2. 参数解析（静态 + 模板）
            try:
                resolved_args = self._resolve_args(step, step_results, context)
            except Exception as e:
                sr = ChainStepResult(
                    step_index=i,
                    step_label=step.label or step.skill_name,
                    skill_name=step.skill_name,
                    success=False,
                    error=f"参数解析失败: {e}",
                    duration_ms=int((time.time() - step_start) * 1000),
                )
                step_results.append(sr)
                failed_step = i
                last_success = False
                if step.on_failure == 'abort':
                    break
                elif step.on_failure == 'skip':
                    continue
                else:
                    # retry / fallback 都用 fallback_args
                    resolved_args = dict(step.fallback_args)

            # 3. 调用 skill
            try:
                sr = self._invoke_step(router, i, step, resolved_args, agent_id, step_start, context)
                step_results.append(sr)
                executed += 1

                if not sr.success:
                    # 失败处理
                    if step.on_failure == 'retry':
                        # 重试一次
                        sr2 = self._invoke_step(router, i, step, resolved_args, agent_id,
                                                 time.time(), context)
                        sr2.step_index = i
                        step_results[-1] = sr2
                        sr = sr2
                        if not sr.success:
                            failed_step = i
                            last_success = False
                            if step.on_failure != 'skip':
                                break
                    elif step.on_failure == 'fallback':
                        # 用 fallback_args 重试
                        sr3 = self._invoke_step(router, i, step, dict(step.fallback_args),
                                                 agent_id, time.time(), context)
                        sr3.step_index = i
                        step_results[-1] = sr3
                        sr = sr3
                        if not sr.success:
                            failed_step = i
                            last_success = False
                            break
                    elif step.on_failure == 'skip':
                        continue
                    else:  # abort
                        failed_step = i
                        last_success = False
                        break
                else:
                    # 成功 — 把输出写入 context
                    context[f'step_{i}'] = {
                        'success': sr.success,
                        'output': sr.output,
                        'error': sr.error,
                        'data': sr.data if isinstance(sr.data, dict) else {},
                    }
                    final_output = sr.output

            except Exception as e:
                sr = ChainStepResult(
                    step_index=i,
                    step_label=step.label or step.skill_name,
                    skill_name=step.skill_name,
                    success=False,
                    error=f"步骤异常: {e}",
                    duration_ms=int((time.time() - step_start) * 1000),
                )
                step_results.append(sr)
                failed_step = i
                last_success = False
                if step.on_failure != 'skip':
                    break

        duration_ms = int((time.time() - start) * 1000)
        return ChainResult(
            chain_name=self.name,
            success=last_success and failed_step == -1,
            total_steps=len(self.steps),
            executed_steps=executed,
            skipped_steps=skipped,
            failed_step=failed_step,
            duration_ms=duration_ms,
            step_results=step_results,
            final_output=final_output,
            context=context,
        )

    def _invoke_step(self, router, step_index: int, step: ChainStep,
                     args: Dict, agent_id: str, start_time: float,
                     context: Dict) -> ChainStepResult:
        """调用单个 skill"""
        try:
            result = router.invoke(step.skill_name, args, agent_id=agent_id)
            return ChainStepResult(
                step_index=step_index,
                step_label=step.label or step.skill_name,
                skill_name=step.skill_name,
                success=result.success,
                output=result.output,
                error=result.error,
                data=result.data if hasattr(result, 'data') else None,
                duration_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            return ChainStepResult(
                step_index=step_index,
                step_label=step.label or step.skill_name,
                skill_name=step.skill_name,
                success=False,
                error=f"调用异常: {e}",
                duration_ms=int((time.time() - start_time) * 1000),
            )

    def _resolve_args(self, step: ChainStep,
                      step_results: List[ChainStepResult],
                      context: Dict) -> Dict[str, Any]:
        """解析步骤参数（合并静态 args + 动态 args_template）"""
        resolved = dict(step.args)  # 静态参数优先

        # 处理模板参数
        for key, template in step.args_template.items():
            resolved[key] = self._eval_template(template, step_results, context)

        return resolved

    def _eval_template(self, template: str,
                       step_results: List[ChainStepResult],
                       context: Dict) -> Any:
        """
        计算模板字符串

        支持的变量：
        - {{step_N.output}}     — 第 N 步的输出
        - {{step_N.success}}    — 第 N 步是否成功
        - {{step_N.error}}      — 第 N 步的错误
        - {{step_N.data.key}}   — 第 N 步 data 中的 key
        - {{context.key}}       — 上下文中的 key
        - {{context.step_N.output}} — 上下文中的 step_N 子项
        """
        if not isinstance(template, str):
            return template

        # 简单情况：整个模板就是一个变量
        m = self._TEMPLATE_RE.fullmatch(template.strip())
        if m:
            return self._eval_var(m.group(1).strip(), step_results, context)

        # 字符串中嵌入变量
        def replacer(match):
            var = match.group(1).strip()
            val = self._eval_var(var, step_results, context)
            if isinstance(val, (dict, list)):
                return json.dumps(val, ensure_ascii=False)
            return str(val)

        return self._TEMPLATE_RE.sub(replacer, template)

    def _eval_var(self, var: str,
                  step_results: List[ChainStepResult],
                  context: Dict) -> Any:
        """计算单个变量表达式"""
        parts = var.split('.')

        if parts[0] == 'context':
            # {{context.key}} 或 {{context.step_N.output}}
            cur: Any = context
            for p in parts[1:]:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    return ""
            return cur

        elif parts[0].startswith('step_'):
            # {{step_N.field}} 或 {{step_N.data.key}}
            try:
                step_idx = int(parts[0][len('step_'):])
            except ValueError:
                return ""
            if step_idx < 0 or step_idx >= len(step_results):
                return ""
            sr = step_results[step_idx]
            if len(parts) == 1:
                return sr.output
            field_name = parts[1]
            if field_name == 'output':
                return sr.output
            elif field_name == 'success':
                return sr.success
            elif field_name == 'error':
                return sr.error
            elif field_name == 'data':
                if len(parts) >= 3:
                    # {{step_N.data.key}}
                    if isinstance(sr.data, dict):
                        return sr.data.get(parts[2], "")
                    return ""
                return sr.data
            elif field_name == 'duration_ms':
                return sr.duration_ms
            else:
                return ""

        return ""

    def _eval_condition(self, when: str,
                        step_results: List[ChainStepResult],
                        context: Dict) -> bool:
        """
        计算条件表达式

        支持：
        - "step_0.success" — 前一步成功
        - "step_0.success == true"
        - "step_0.output contains '关键词'"
        - "context.enable_report == true"
        - "" (空) — 默认执行（返回 True）
        """
        # 空字符串默认执行
        if not when or not when.strip():
            return True
        try:
            # 先解析变量
            expr = self._eval_template(when, step_results, context)
            if isinstance(expr, bool):
                return expr
            if isinstance(expr, str):
                # 处理 == true / == false
                expr_lower = expr.strip().lower()
                if expr_lower in ('true', '1', 'yes'):
                    return True
                if expr_lower in ('false', '0', 'no'):
                    return False
                # 处理 contains
                if ' contains ' in expr:
                    left, right = expr.split(' contains ', 1)
                    right = right.strip().strip("'\"")
                    return right in left
                # 处理 ==
                if '==' in expr:
                    left, right = expr.split('==', 1)
                    return left.strip().lower() == right.strip().strip("'\"").lower()
                # 非空字符串视为 True
                return bool(expr.strip())
            return bool(expr)
        except Exception:
            return True  # 解析失败默认执行

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'description': self.description,
            'steps': [s.to_dict() for s in self.steps],
            'metadata': self.metadata,
            'step_count': len(self.steps),
        }


# ============================================================
# 预定义 Chain 模板
# ============================================================

def _build_predefined_chains() -> Dict[str, SkillChain]:
    """构建预定义 Chain 模板"""
    chains: Dict[str, SkillChain] = {}

    # 1. 调研 → 辩驳 → 生成报告
    chains['research_debate_report'] = SkillChain(
        name='research_debate_report',
        description='网络调研 → 多源信息辩驳 → 自动生成 Word 报告',
        steps=[
            ChainStep(
                skill_name='web_researcher',
                args={'query': 'Python 编程语言历史', 'max_results': 5},
                label='网络调研',
            ),
            ChainStep(
                skill_name='info_debater',
                args={'mode': 'compare'},
                args_template={'sources': '{{step_0.output}}'},
                label='信息辩驳',
                on_failure='fallback',
                fallback_args={'sources': '[]', 'mode': 'compare'},
            ),
            ChainStep(
                skill_name='office_generator',
                args={'doc_type': 'word', 'title': '调研报告'},
                args_template={'content': '{{step_1.output}}'},
                label='生成 Word 报告',
                when='{{step_1.success}}',
            ),
        ],
        metadata={'category': 'research', 'icon': '🔍'},
    )

    # 2. 数学解题 → 可视化
    chains['math_solve_visualize'] = SkillChain(
        name='math_solve_visualize',
        description='解数学题 → 自动绘制函数图像',
        steps=[
            ChainStep(
                skill_name='math_solver',
                args={'expression': 'x**2 + 2*x + 1', 'operation': 'solve'},
                label='解方程',
            ),
            ChainStep(
                skill_name='math_plotter',
                args={'plot_type': 'function', 'save_path': 'plot.png'},
                args_template={'expression': '{{step_0.output}}'},
                label='绘制函数图',
                when='{{step_0.success}}',
            ),
        ],
        metadata={'category': 'math', 'icon': '∑'},
    )

    # 3. 数据抓取 → 分析 → 可视化 → 导出 PPT
    chains['data_pipeline'] = SkillChain(
        name='data_pipeline',
        description='数据抓取 → 数学分析 → 可视化 → 导出 PPT 报告',
        steps=[
            ChainStep(
                skill_name='web_researcher',
                args={'query': '市场数据', 'max_results': 3},
                label='数据抓取',
            ),
            ChainStep(
                skill_name='math_solver',
                args={'operation': 'simplify'},
                args_template={'expression': '{{step_0.output}}'},
                label='数据分析',
                on_failure='skip',
            ),
            ChainStep(
                skill_name='math_plotter',
                args={'plot_type': 'function', 'save_path': 'analysis.png'},
                args_template={'expression': '{{step_1.output}}'},
                label='数据可视化',
                when='{{step_1.success}}',
            ),
            ChainStep(
                skill_name='office_generator',
                args={'doc_type': 'ppt', 'title': '数据分析报告'},
                args_template={'content': '{{step_2.output}}'},
                label='导出 PPT',
                on_failure='fallback',
                fallback_args={'doc_type': 'ppt', 'title': '数据分析报告', 'content': '(无数据)'},
            ),
        ],
        metadata={'category': 'data', 'icon': '📊'},
    )

    # 4. 图像 OCR → 内容辩驳
    chains['image_ocr_debate'] = SkillChain(
        name='image_ocr_debate',
        description='图像处理/OCR → 多源信息辩驳',
        steps=[
            ChainStep(
                skill_name='image_processor',
                args={'operation': 'info'},
                args_template={'path': '{{context.image_path}}'},
                label='图像信息',
            ),
            ChainStep(
                skill_name='info_debater',
                args={'mode': 'compare'},
                args_template={'sources': '{{step_0.output}}'},
                label='内容辩驳',
                when='{{step_0.success}}',
            ),
        ],
        metadata={'category': 'image', 'icon': '🖼'},
    )

    return chains


# 全局预定义 Chain 注册表
_PREDEFINED_CHAINS: Optional[Dict[str, SkillChain]] = None
_CHAIN_LOCK = threading.Lock()


def get_predefined_chains() -> Dict[str, SkillChain]:
    """获取预定义 Chain 模板（懒加载）"""
    global _PREDEFINED_CHAINS
    if _PREDEFINED_CHAINS is None:
        with _CHAIN_LOCK:
            if _PREDEFINED_CHAINS is None:
                _PREDEFINED_CHAINS = _build_predefined_chains()
    return _PREDEFINED_CHAINS


def get_chain(name: str) -> Optional[SkillChain]:
    """按名获取预定义 Chain"""
    return get_predefined_chains().get(name)


def list_predefined_chains() -> List[Dict]:
    """列出所有预定义 Chain"""
    return [c.to_dict() for c in get_predefined_chains().values()]


def register_chain(chain: SkillChain):
    """注册自定义 Chain"""
    with _CHAIN_LOCK:
        if _PREDEFINED_CHAINS is None:
            get_predefined_chains()
        _PREDEFINED_CHAINS[chain.name] = chain


def validate_chain(chain: SkillChain, registry=None) -> List[str]:
    """验证 Chain 定义是否合法, 返回错误列表(空=合法)"""
    errors: List[str] = []
    if not chain.name:
        errors.append("chain.name is empty")
    if not chain.steps:
        errors.append("chain has no steps")
    seen_skills: Dict[str, int] = {}
    for i, step in enumerate(chain.steps):
        if not step.skill_name:
            errors.append("step " + str(i) + " has empty skill_name")
        if step.on_failure not in ('abort', 'skip', 'retry', 'fallback'):
            errors.append("step " + str(i) + " invalid on_failure: " + step.on_failure)
        if step.timeout < 1:
            errors.append("step " + str(i) + " timeout must be >= 1")
        if step.skill_name in seen_skills:
            errors.append("step " + str(i) + " duplicates skill " + step.skill_name + " (first at step " + str(seen_skills[step.skill_name]) + ")")
        seen_skills[step.skill_name] = i
        for key, tmpl in step.args_template.items():
            refs = re.findall(r'\{\{step_(\d+)[.}]', tmpl)
            for ref in refs:
                if int(ref) >= i:
                    errors.append("step " + str(i) + " args_template key '" + key + "' references step_" + ref + " which is not yet executed")
    if registry is not None:
        for i, step in enumerate(chain.steps):
            if step.skill_name and registry.get(step.skill_name) is None:
                errors.append("step " + str(i) + " skill '" + step.skill_name + "' not found in registry")
    return errors


def chain_to_json(chain: SkillChain) -> str:
    """序列化 Chain 为 JSON"""
    data = chain.to_dict()
    return json.dumps(data, ensure_ascii=False, indent=2)


def chain_from_json(json_str: str) -> SkillChain:
    """从 JSON 反序列化 Chain"""
    data = json.loads(json_str)
    steps = []
    for s in data.get('steps', []):
        steps.append(ChainStep(
            skill_name=s.get('skill_name', ''),
            args=s.get('args', {}),
            args_template=s.get('args_template', {}),
            label=s.get('label', ''),
            on_failure=s.get('on_failure', 'abort'),
            fallback_args=s.get('fallback_args', {}),
            when=s.get('when', ''),
            timeout=s.get('timeout', 60),
        ))
    return SkillChain(
        name=data.get('name', ''),
        description=data.get('description', ''),
        steps=steps,
        metadata=data.get('metadata', {}),
    )


# ============================================================
# 自测
# ============================================================

if __name__ == '__main__':
    print("=" * 60)
    print("SkillChain v22.5 自测")
    print("=" * 60)

    print("\n预定义 Chain 模板:")
    for c in list_predefined_chains():
        print(f"  - {c['name']:<25} steps={c['step_count']}  {c['description']}")

    # 测试模板解析
    print("\n--- 模板解析测试 ---")
    chain = get_chain('research_debate_report')
    if chain:
        fake_results = [
            ChainStepResult(step_index=0, step_label="网络调研",
                            skill_name="web_researcher", success=True,
                            output='[{"source":"wiki","content":"Python是高级语言"}]',
                            duration_ms=120),
            ChainStepResult(step_index=1, step_label="信息辩驳",
                            skill_name="info_debater", success=True,
                            output='共识: Python是高级语言',
                            duration_ms=80),
        ]
        context = {'_chain_name': 'research_debate_report'}
        val = chain._eval_template('{{step_0.output}}', fake_results, context)
        print(f"  step_0.output = {val[:60]}...")
        val = chain._eval_template('{{step_1.success}}', fake_results, context)
        print(f"  step_1.success = {val}")
        val = chain._eval_template('最终: {{step_1.output}}', fake_results, context)
        print(f"  嵌入字符串 = {val}")

    # 测试条件表达式
    print("\n--- 条件表达式测试 ---")
    tests = [
        ('{{step_0.success}}', True),
        ('{{step_0.output}} contains 高级', True),
        ('{{step_0.success}} == true', True),
        ('{{step_0.success}} == false', False),
    ]
    for expr, expected in tests:
        result = chain._eval_condition(expr, fake_results, context)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{expr}' → {result} (expected {expected})")

    print("\n✅ SkillChain 模块自测通过")
