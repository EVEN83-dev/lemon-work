# -*- coding: utf-8 -*-
"""shared/skills_builtin — 调度器内置技能（第359章）

四个运行时注册技能（通过 SkillsRegistry.register() 公开 API，不动冻结区文件）：
  scheduler_create / scheduler_list / scheduler_cancel / scheduler_run_now

调度引擎实例由本包全局单例获取；挂载由 main.py 编排区注入，技能无需关心 Qt。
"""
from shared.skills_builtin.scheduler_skills import register_scheduler_skills

__all__ = ["register_scheduler_skills"]
