# -*- coding: utf-8 -*-
"""
Skill 路由器 — mimo serve / 本地 Python 双路调度
================================================
★ Lemon Code v22.4 创新点：智能双路 Skill 调度

工作原理：
1. 每个 Agent 维护自身 skill 列表（部分来自 mimo serve，部分来自本地）
2. 当 Agent 调用 skill 时，路由器按以下优先级调度：
   a. 优先尝试 mimo serve（通过 /session/{id}/prompt_async + tools 参数）
   b. 若 mimo serve 不可用/无该能力/调用失败 → 自动 fallback 到本地 Python 执行
   c. 本地执行通过 SkillsRegistry 调用已注册的 SkillDef.handler
3. 路由器记录每次调用的来源（mimo/local）+ 耗时 + 成功率，用于后续优化

mimo serve 集成方式：
- /session/{id}/prompt_async 接口支持 tools 参数（function_call schema）
- 路由器把本地 SkillDef 转换为 OpenAI tool 定义传给 mimo serve
- mimo serve 内的模型可主动调用这些 tool（function_call）
- mimo serve 调用 tool 时，路由器拦截并执行本地 handler，返回结果给 mimo serve

兼容性：
- mimo serve 不可用时，所有 skill 走本地（不影响功能）
- mimo serve 有原生能力时（如代码生成），可跳过本地直接走 mimo
- 每个 skill 可配置 preferred_backend: 'mimo' / 'local' / 'auto'
"""

import os
import sys
import json
import time
import threading
import traceback
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from skills_registry import SkillsRegistry, SkillDef, SkillResult, get_skills_registry
from business_skills import register_business_skills, BUSINESS_SKILLS
# ★ v22.5 SkillChain 集成
try:
    from skill_chain import (
        SkillChain, ChainStep, ChainResult,
        get_predefined_chains, get_chain, list_predefined_chains,
        register_chain,
    )
    _CHAIN_AVAILABLE = True
except ImportError:
    _CHAIN_AVAILABLE = False


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SkillCallRecord:
    """Skill 调用记录"""
    skill_name: str
    backend: str               # 'mimo' / 'local' / 'failed'
    success: bool
    duration_ms: int           # 耗时毫秒
    timestamp: str
    error: str = ""
    agent_id: str = ""         # 调用方 Agent


@dataclass
class SkillRoutePolicy:
    """Skill 路由策略"""
    skill_name: str
    preferred_backend: str = 'auto'   # 'mimo' / 'local' / 'llm' / 'auto'
    fallback_enabled: bool = True      # 允许 fallback
    mimo_only_when_available: bool = True  # mimo serve 不可用时跳过


# ============================================================
# SkillRouter 主类
# ============================================================

class UniversalSkillRouter:
    """
    Skill 通用路由器（引擎无关）— P2/E1 重构

    在原 SkillRouter「mimo serve / 本地 Python 双路调度」基础上，重构为
    **引擎无关（engine-agnostic）** 的通用路由层：上层（SmartDispatcher /
    CrossEngineBridge）只需面向本类的统一 invoke 接口编程，无需感知底层走
    mimo serve 还是本地 Python，也无需感知具体 LLM 后端（Ollama / DeepSeek）。
    接口（invoke / invoke_chain / invoke_chain_custom）与旧 SkillRouter 完全兼容。

    用法:
        router = UniversalSkillRouter(mimo_port=4097)
        result = router.invoke('math_solver', {'expression': 'x**2+1', 'operation': 'simplify'})

    路由逻辑:
        1. 查询路由策略
        2. 按 preferred_backend 尝试
        3. 失败且 fallback_enabled=True 时切换后端重试
        4. 记录调用日志
    """

    def __init__(self, mimo_port: int = 4097, mimo_host: str = 'localhost',
                 registry: Optional[SkillsRegistry] = None,
                 llm_dispatcher: Optional[Any] = None):
        """
        Args:
            mimo_port: mimo serve 端口
            mimo_host: mimo serve 主机
            registry: Skill 注册中心（默认全局单例）
            llm_dispatcher: 引擎无关 LLM 调度器（如 SmartDispatcher，鸭子类型：
                需提供 dispatch_chat(messages, **kwargs) -> str）。配置后 skill
                可路由到 'llm' 后端，按引擎无关方式调用 Ollama/DeepSeek 等。
        """
        self.mimo_port = mimo_port
        self.mimo_host = mimo_host
        self.mimo_base_url = f"http://{mimo_host}:{mimo_port}"
        self._llm_dispatcher = llm_dispatcher
        self.registry = registry or get_skills_registry()
        self._policies: Dict[str, SkillRoutePolicy] = {}
        self._records: List[SkillCallRecord] = []
        self._records_lock = threading.Lock()
        self._mimo_available: Optional[bool] = None
        self._mimo_check_at: float = 0
        self._init_default_policies()
        # 注册业务 skill
        register_business_skills(self.registry)

    def _init_default_policies(self):
        """初始化默认路由策略"""
        # 业务 skill 默认本地优先（因为 mimo serve 没有这些能力）
        local_first_skills = [
            'math_solver', 'web_researcher', 'info_debater',
            'math_plotter', 'office_generator', 'image_processor',
        ]
        for name in local_first_skills:
            self._policies[name] = SkillRoutePolicy(
                skill_name=name,
                preferred_backend='local',  # 这些 skill mimo 不擅长，本地优先
                fallback_enabled=True,
            )

        # 编码相关 skill 默认 mimo 优先（mimo serve 原生能力）
        mimo_first_skills = ['code_executor', 'file_reader', 'file_writer', 'write_file', 'read_file', 'web_fetcher']
        for name in mimo_first_skills:
            self._policies[name] = SkillRoutePolicy(
                skill_name=name,
                preferred_backend='mimo',
                fallback_enabled=True,
            )

    # ==================== 路由策略管理 ====================

    def set_policy(self, skill_name: str, preferred_backend: str,
                   fallback_enabled: bool = True):
        """设置 skill 路由策略"""
        self._policies[skill_name] = SkillRoutePolicy(
            skill_name=skill_name,
            preferred_backend=preferred_backend,
            fallback_enabled=fallback_enabled,
        )

    def get_policy(self, skill_name: str) -> SkillRoutePolicy:
        """获取 skill 路由策略（不存在则返回 auto 默认）"""
        return self._policies.get(skill_name, SkillRoutePolicy(
            skill_name=skill_name, preferred_backend='auto', fallback_enabled=True
        ))

    # ==================== mimo serve 可用性检查 ====================

    def check_mimo_available(self, force: bool = False) -> bool:
        """
        检查 mimo serve 是否可用（带 10 秒缓存）

        Args:
            force: 强制刷新缓存
        """
        now = time.time()
        if not force and self._mimo_available is not None and (now - self._mimo_check_at) < 10:
            return self._mimo_available

        try:
            import requests
            r = requests.get(f"{self.mimo_base_url}/global/health", timeout=3)
            self._mimo_available = (r.status_code == 200)
        except Exception:
            self._mimo_available = False

        self._mimo_check_at = now
        return self._mimo_available

    # ==================== 主入口：调用 skill ====================

    def invoke(self, skill_name: str, args: Dict[str, Any],
               agent_id: str = "", context: Dict[str, Any] = None) -> SkillResult:
        """
        调用 skill — 智能双路调度

        Args:
            skill_name: skill 名称
            args: 调用参数
            agent_id: 调用方 Agent ID（用于日志）
            context: 调用上下文（EngineManager 透传，预留用于路由决策）

        Returns:
            SkillResult
        """
        # 将 context 合并到 args._context 中，供后端按需使用
        merged_args = dict(args) if args else {}
        if context:
            merged_args.setdefault("_context", {}).update(context)
        policy = self.get_policy(skill_name)
        start = time.time()

        # 选择主后端
        if policy.preferred_backend == 'auto':
            # auto: mimo 可用则走 mimo，否则走 local
            primary = 'mimo' if self.check_mimo_available() else 'local'
        else:
            primary = policy.preferred_backend
            # mimo 优先但 mimo 不可用时，主后端降级为 local
            if primary == 'mimo' and policy.mimo_only_when_available:
                if not self.check_mimo_available():
                    primary = 'local' if policy.fallback_enabled else 'mimo'

        # 尝试主后端
        result = self._invoke_with_backend(skill_name, merged_args, primary, agent_id)

        # 主后端失败 → fallback
        if not result.success and policy.fallback_enabled and primary != 'local':
            fallback_backend = 'local'
            result = self._invoke_with_backend(skill_name, merged_args, fallback_backend, agent_id)
            backend_used = fallback_backend if result.success else 'failed'
        else:
            backend_used = primary if result.success else 'failed'

        # 记录调用
        duration_ms = int((time.time() - start) * 1000)
        self._record_call(
            skill_name=skill_name,
            backend=backend_used,
            success=result.success,
            duration_ms=duration_ms,
            error=result.error,
            agent_id=agent_id,
        )

        return result

    def _invoke_with_backend(self, skill_name: str, args: Dict[str, Any],
                              backend: str, agent_id: str = "") -> SkillResult:
        """按指定后端调用 skill"""
        if backend == 'mimo':
            return self._invoke_via_mimo(skill_name, args, agent_id)
        elif backend == 'local':
            return self._invoke_local(skill_name, args)
        elif backend == 'llm':
            return self._invoke_via_dispatcher(skill_name, args, agent_id)
        else:
            return SkillResult(success=False, error=f"未知 backend: {backend}")

    # ==================== 本地调用 ====================

    def _invoke_local(self, skill_name: str, args: Dict[str, Any]) -> SkillResult:
        """本地调用 SkillsRegistry 中已注册的 skill"""
        return self.registry.execute(skill_name, args)

    def _invoke_via_dispatcher(self, skill_name: str, args: Dict[str, Any],
                               agent_id: str = "") -> SkillResult:
        """
        通过引擎无关 LLM 调度器（如 SmartDispatcher）执行 skill。

        把 skill 定义 + 参数构造为提示词，交给 llm_dispatcher.dispatch_chat()
        引擎无关调用（可路由到 Ollama/DeepSeek 等任意 BaseEngineAdapter 后端）。
        """
        if self._llm_dispatcher is None:
            return SkillResult(success=False,
                               error="未配置 llm_dispatcher（引擎无关 LLM 调度器）")
        skill = self.registry.get(skill_name)
        if not skill:
            return SkillResult(success=False, error=f"skill '{skill_name}' 未注册")

        args_str = json.dumps(args, ensure_ascii=False, indent=2)
        prompt = (
            f"你需要使用工具 `{skill_name}` 完成任务。\n"
            f"工具描述: {skill.description}\n"
            f"参数:\n```\n{args_str}\n```\n\n"
            f"请直接完成任务并输出最终结果，不要生成多余文字。"
        )
        try:
            reply = self._llm_dispatcher.dispatch_chat(
                [{"role": "user", "content": prompt}]
            )
        except Exception as e:
            return SkillResult(success=False, error=f"LLM 调度失败: {e}")

        if not reply or not str(reply).strip():
            return SkillResult(success=False, error="LLM 调度返回空结果")
        return SkillResult(success=True,
                           output=f"[llm 调度响应]\n{reply}",
                           error="")

    # ==================== mimo serve 调用 ====================

    def _invoke_via_mimo(self, skill_name: str, args: Dict[str, Any],
                          agent_id: str = "") -> SkillResult:
        """
        通过 mimo serve 调用 skill

        实现:
        1. 创建/复用 mimo serve 会话
        2. 把 skill 定义作为 tools 参数传给 /session/{id}/prompt_async
        3. 让 mimo 内的模型生成"调用该 skill"的决策
        4. 解析响应，若模型决策是 function_call，则回到本地执行
        5. 把本地执行结果返回给 mimo serve，让其继续生成最终输出
        """
        if not self.check_mimo_available():
            return SkillResult(success=False, error="mimo serve 不可用")

        try:
            import requests
        except ImportError:
            return SkillResult(success=False, error="requests 库未安装")

        # 1. 创建会话
        try:
            r = requests.post(f"{self.mimo_base_url}/session",
                              json={"title": f"skill_call_{skill_name}_{int(time.time())}"},
                              timeout=10)
            if r.status_code not in (200, 201):
                return SkillResult(success=False,
                                    error=f"创建会话失败: {r.status_code}")
            session_data = r.json()
            session_id = session_data.get('id')
            if not session_id:
                return SkillResult(success=False, error="未获取到 session_id")
        except Exception as e:
            return SkillResult(success=False, error=f"创建会话异常: {e}")

        # 2. 获取 skill 的 tool 定义
        skill = self.registry.get(skill_name)
        if not skill:
            return SkillResult(success=False, error=f"skill '{skill_name}' 未注册")

        tool_def = {
            "type": "function",
            "function": {
                "name": skill.name,
                "description": skill.description,
                "parameters": skill.parameters,
            },
        }

        # 3. 构造提示词 — 让模型决定是否调用 skill
        args_str = json.dumps(args, ensure_ascii=False, indent=2)
        prompt = (
            f"你需要调用工具 `{skill_name}` 完成任务。\n"
            f"工具描述: {skill.description}\n"
            f"参数:\n```\n{args_str}\n```\n\n"
            f"请直接调用该工具（function_call），不要生成多余文字。"
        )

        # 4. 异步发送给 mimo serve
        try:
            r2 = requests.post(
                f"{self.mimo_base_url}/session/{session_id}/prompt_async",
                json={
                    "parts": [{"type": "text", "text": prompt}],
                    "tools": [tool_def],
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
                timeout=15,
            )
            if r2.status_code not in (200, 201, 202, 204):
                return SkillResult(success=False,
                                    error=f"prompt_async 失败: {r2.status_code} {r2.text[:200]}")
        except Exception as e:
            return SkillResult(success=False, error=f"prompt_async 异常: {e}")

        # 5. 等待响应并轮询
        # mimo serve 是异步的，需要轮询结果
        try:
            result_text = self._poll_mimo_response(session_id, max_wait=30)
        except Exception as e:
            return SkillResult(success=False, error=f"轮询响应失败: {e}")

        if not result_text:
            return SkillResult(success=False, error="mimo serve 无响应")

        # 6. 检查响应中是否有 function_call
        #    若有，则执行本地 handler 并返回
        if '"function_call"' in result_text or 'tool_calls' in result_text:
            # 模型决定调用 skill — 执行本地 handler
            local_result = self._invoke_local(skill_name, args)
            local_result.output = (
                f"[mimo→local fallback] 模型决定调用 {skill_name}\n" +
                local_result.output
            )
            return local_result

        # 7. 模型直接生成了答案 — 作为 mimo 的输出返回
        return SkillResult(
            success=True,
            output=f"[mimo serve 响应]\n{result_text}",
            data={'session_id': session_id, 'backend': 'mimo'},
        )

    def _poll_mimo_response(self, session_id: str, max_wait: int = 30) -> str:
        """轮询 mimo serve 的响应"""
        import requests
        start = time.time()
        while time.time() - start < max_wait:
            try:
                r = requests.get(f"{self.mimo_base_url}/session/{session_id}",
                                 timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    # 检查是否有最新消息
                    messages = data.get('messages', [])
                    if messages:
                        last_msg = messages[-1]
                        content = last_msg.get('content', '')
                        if content and last_msg.get('role') == 'assistant':
                            return content
            except Exception:
                pass
            time.sleep(1)
        return ""

    # ==================== 调用记录 ====================

    def _record_call(self, skill_name: str, backend: str, success: bool,
                     duration_ms: int, error: str = "", agent_id: str = ""):
        """记录调用日志"""
        record = SkillCallRecord(
            skill_name=skill_name,
            backend=backend,
            success=success,
            duration_ms=duration_ms,
            timestamp=datetime.now().isoformat(),
            error=error,
            agent_id=agent_id,
        )
        with self._records_lock:
            self._records.append(record)
            # 保留最近 1000 条
            if len(self._records) > 1000:
                self._records = self._records[-500:]

    def get_call_records(self, skill_name: str = "",
                         backend: str = "") -> List[Dict]:
        """获取调用记录"""
        with self._records_lock:
            records = list(self._records)
        if skill_name:
            records = [r for r in records if r.skill_name == skill_name]
        if backend:
            records = [r for r in records if r.backend == backend]
        return [
            {
                'skill_name': r.skill_name,
                'backend': r.backend,
                'success': r.success,
                'duration_ms': r.duration_ms,
                'timestamp': r.timestamp,
                'error': r.error,
                'agent_id': r.agent_id,
            }
            for r in records
        ]

    def get_stats(self) -> Dict:
        """获取调用统计"""
        with self._records_lock:
            records = list(self._records)

        total = len(records)
        if total == 0:
            return {'total': 0}

        success_count = sum(1 for r in records if r.success)
        mimo_count = sum(1 for r in records if r.backend == 'mimo')
        local_count = sum(1 for r in records if r.backend == 'local')
        failed_count = sum(1 for r in records if r.backend == 'failed')
        avg_duration = sum(r.duration_ms for r in records) / total

        # 按 skill 分组统计
        per_skill = {}
        for r in records:
            if r.skill_name not in per_skill:
                per_skill[r.skill_name] = {'total': 0, 'success': 0, 'avg_ms': 0}
            per_skill[r.skill_name]['total'] += 1
            if r.success:
                per_skill[r.skill_name]['success'] += 1
            per_skill[r.skill_name]['avg_ms'] += r.duration_ms
        for k, v in per_skill.items():
            v['avg_ms'] = v['avg_ms'] / v['total'] if v['total'] > 0 else 0
            v['success_rate'] = v['success'] / v['total'] if v['total'] > 0 else 0

        return {
            'total': total,
            'success_count': success_count,
            'success_rate': success_count / total,
            'mimo_count': mimo_count,
            'local_count': local_count,
            'failed_count': failed_count,
            'avg_duration_ms': avg_duration,
            'mimo_available': self.check_mimo_available(),
            'mimo_base_url': self.mimo_base_url,
            'per_skill': per_skill,
        }

    # ==================== 工具方法 ====================

    def list_skills(self, category: str = "") -> List[Dict]:
        """列出所有已注册 skill"""
        skills = self.registry.list_skills(category=category)
        return [
            {
                'name': s.name,
                'description': s.description,
                'category': s.category,
                'timeout': s.timeout,
                'preferred_backend': self.get_policy(s.name).preferred_backend,
            }
            for s in skills
        ]

    def to_dict(self) -> Dict:
        """转换为字典（供前端展示）"""
        return {
            'mimo_base_url': self.mimo_base_url,
            'mimo_available': self.check_mimo_available(),
            'llm_backend_configured': self._llm_dispatcher is not None,
            'skills': self.list_skills(),
            'stats': self.get_stats(),
            'policies': {
                name: {
                    'preferred_backend': p.preferred_backend,
                    'fallback_enabled': p.fallback_enabled,
                }
                for name, p in self._policies.items()
            },
        }

    # ==================== v22.5 SkillChain 集成 ====================

    def invoke_chain(self, chain_name: str, agent_id: str = "",
                     initial_context: Optional[Dict] = None) -> Dict:
        """
        调用预定义 Chain（多 skill 串联执行）

        Args:
            chain_name: Chain 名称
            agent_id: 调用方 Agent ID
            initial_context: 初始上下文

        Returns:
            ChainResult.to_dict()
        """
        if not _CHAIN_AVAILABLE:
            return {
                'chain_name': chain_name,
                'success': False,
                'error': 'skill_chain 模块未加载',
            }
        chain = get_chain(chain_name)
        if chain is None:
            return {
                'chain_name': chain_name,
                'success': False,
                'error': f"Chain '{chain_name}' 不存在",
            }
        result = chain.execute(self, agent_id=agent_id,
                                initial_context=initial_context)
        return result.to_dict()

    def invoke_chain_custom(self, chain_def: Dict, agent_id: str = "",
                            initial_context: Optional[Dict] = None) -> Dict:
        """
        调用自定义 Chain（由前端动态构造）

        Args:
            chain_def: Chain 定义 dict {name, description, steps: [{skill_name, args, args_template, ...}]}
        """
        if not _CHAIN_AVAILABLE:
            return {'success': False, 'error': 'skill_chain 模块未加载'}
        try:
            steps = []
            for s in chain_def.get('steps', []):
                steps.append(ChainStep(
                    skill_name=s['skill_name'],
                    args=s.get('args', {}),
                    args_template=s.get('args_template', {}),
                    label=s.get('label', s['skill_name']),
                    on_failure=s.get('on_failure', 'abort'),
                    fallback_args=s.get('fallback_args', {}),
                    when=s.get('when', ''),
                    timeout=s.get('timeout', 60),
                ))
            chain = SkillChain(
                name=chain_def.get('name', 'custom_chain'),
                description=chain_def.get('description', ''),
                steps=steps,
                metadata=chain_def.get('metadata', {}),
            )
            result = chain.execute(self, agent_id=agent_id,
                                    initial_context=initial_context)
            return result.to_dict()
        except Exception as e:
            return {
                'chain_name': chain_def.get('name', 'custom_chain'),
                'success': False,
                'error': f'自定义 Chain 执行失败: {e}',
            }

    def list_chains(self) -> List[Dict]:
        """列出所有预定义 Chain"""
        if not _CHAIN_AVAILABLE:
            return []
        return list_predefined_chains()

    def get_chain_details(self, chain_name: str) -> Dict:
        """获取 Chain 详情"""
        if not _CHAIN_AVAILABLE:
            return {}
        chain = get_chain(chain_name)
        if chain is None:
            return {}
        return chain.to_dict()


# ============================================================
# 全局单例
# ============================================================

_global_router: Optional["UniversalSkillRouter"] = None
_router_lock = threading.Lock()


def get_skill_router(mimo_port: int = 4097) -> "UniversalSkillRouter":
    """获取全局 UniversalSkillRouter 单例"""
    global _global_router
    if _global_router is None:
        with _router_lock:
            if _global_router is None:
                _global_router = UniversalSkillRouter(mimo_port=mimo_port)
    return _global_router


# ============================================================
# 主程序 — 自测
# ============================================================

if __name__ == '__main__':
    print("=" * 60)
    print("UniversalSkillRouter v22.4 自测")
    print("=" * 60)

    router = UniversalSkillRouter(mimo_port=4097)

    print(f"\nmimo serve 可用: {router.check_mimo_available(force=True)}")
    print(f"已注册 skill 数: {len(router.list_skills())}")
    print(f"\n所有 skill:")
    for s in router.list_skills():
        print(f"  - {s['name']:<20} [{s['category']:<8}] → {s['preferred_backend']}")

    # 测试本地调用 math_solver
    print(f"\n--- 测试 math_solver (本地) ---")
    result = router.invoke('math_solver', {
        'expression': 'x**2 + 2*x + 1',
        'operation': 'simplify',
    }, agent_id='test_agent')
    print(f"success: {result.success}")
    print(f"output: {result.output}")
    print(f"error: {result.error}")

    # 测试本地调用 info_debater
    print(f"\n--- 测试 info_debater (本地) ---")
    sources = json.dumps([
        {'source': 'wiki', 'content': 'Python 是一种解释型高级编程语言'},
        {'source': 'baike', 'content': 'Python 是一种解释型、面向对象的高级编程语言'},
        {'source': 'blog', 'content': 'JavaScript 是一种动态编程语言'},
    ])
    result = router.invoke('info_debater', {
        'sources': sources,
        'mode': 'compare',
    }, agent_id='test_agent')
    print(f"success: {result.success}")
    print(f"output: {result.output[:500]}")

    # 统计
    print(f"\n--- 调用统计 ---")
    stats = router.get_stats()
    print(f"总调用: {stats['total']}")
    print(f"成功: {stats['success_count']}")
    print(f"本地: {stats['local_count']}")
    print(f"mimo: {stats['mimo_count']}")
