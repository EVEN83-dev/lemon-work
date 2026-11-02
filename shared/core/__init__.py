# -*- coding: utf-8 -*-
"""lemon_agent 核心能力模块（v5.5 补全）。

此前 engine_manager.py 中 17 处 `from core.xxx import` 指向的模块均不存在，
import 失败被 except 静默吞掉，导致 Agent 退化为"无智能路由的纯循环调用器"。
本目录补全以下 5 个核心能力：
  - task_classifier     任务复杂度分类（驱动引擎路由 + 迭代上限）
  - memory_manager      持久化记忆注入（MEMORY.md 等）
  - context_checkpoint  长对话上下文检查点（save/rebuild 压缩恢复）
  - goal_judge          目标达成判定（决定何时停止）
  - ollama_load_balancer Ollama 并发负载均衡
"""
