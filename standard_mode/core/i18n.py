# -*- coding: utf-8 -*-
"""
i18n 国际化框架 — Lemon Code Agent
====================================
多语言支持：中文简体 (zh_CN) / 英文 (en_US)

功能：
- 自动检测系统语言、环境变量 LEMON_LANG、配置文件
- 运行时切换语言
- 点号分隔的嵌套键访问：'menu.file.open'
- 自动回退：当前语言 → 英文 → 原始 key
- 格式化参数支持：_t('greeting', name='World')
- 全局单例模式 + 便捷函数 _t()

使用方式：
    from standard_mode.core.i18n import _t, get_i18n

    print(_t('menu.file'))           # 文件
    print(_t('button.save'))         # 保存
    get_i18n().set_language('en_US')
    print(_t('menu.file'))           # File
"""

import os
import json
import locale
import threading
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 内置英文翻译（作为默认/回退语言）
# ============================================================

_BUILTIN_EN_US: Dict[str, str] = {
    # ── 菜单项 ──
    "menu.file": "File",
    "menu.file.new": "New",
    "menu.file.open": "Open",
    "menu.file.save": "Save",
    "menu.file.save_as": "Save As",
    "menu.file.close": "Close",
    "menu.file.exit": "Exit",
    "menu.edit": "Edit",
    "menu.edit.undo": "Undo",
    "menu.edit.redo": "Redo",
    "menu.edit.cut": "Cut",
    "menu.edit.copy": "Copy",
    "menu.edit.paste": "Paste",
    "menu.edit.select_all": "Select All",
    "menu.edit.find": "Find",
    "menu.edit.replace": "Replace",
    "menu.view": "View",
    "menu.view.zoom_in": "Zoom In",
    "menu.view.zoom_out": "Zoom Out",
    "menu.view.fullscreen": "Fullscreen",
    "menu.view.toggle_terminal": "Toggle Terminal",
    "menu.view.toggle_panel": "Toggle Panel",
    "menu.help": "Help",
    "menu.help.about": "About",
    "menu.help.documentation": "Documentation",
    "menu.help.check_updates": "Check for Updates",
    "menu.settings": "Settings",
    "menu.settings.preferences": "Preferences",
    "menu.settings.language": "Language",
    "menu.settings.theme": "Theme",
    "menu.tools": "Tools",
    "menu.tools.options": "Options",
    "menu.tools.plugins": "Plugins",
    "menu.window": "Window",
    "menu.window.minimize": "Minimize",
    "menu.window.maximize": "Maximize",

    # ── 常用按钮 ──
    "button.ok": "OK",
    "button.cancel": "Cancel",
    "button.save": "Save",
    "button.delete": "Delete",
    "button.search": "Search",
    "button.export": "Export",
    "button.import": "Import",
    "button.refresh": "Refresh",
    "button.reset": "Reset",
    "button.apply": "Apply",
    "button.confirm": "Confirm",
    "button.retry": "Retry",
    "button.skip": "Skip",
    "button.next": "Next",
    "button.previous": "Previous",
    "button.back": "Back",
    "button.forward": "Forward",
    "button.submit": "Submit",
    "button.clear": "Clear",
    "button.close": "Close",
    "button.add": "Add",
    "button.remove": "Remove",
    "button.edit": "Edit",
    "button.copy": "Copy",
    "button.paste": "Paste",
    "button.upload": "Upload",
    "button.download": "Download",
    "button.send": "Send",
    "button.stop": "Stop",
    "button.start": "Start",
    "button.pause": "Pause",
    "button.resume": "Resume",
    "button.restart": "Restart",

    # ── 状态消息 ──
    "status.loading": "Loading...",
    "status.connected": "Connected",
    "status.disconnected": "Disconnected",
    "status.connecting": "Connecting...",
    "status.error": "Error",
    "status.success": "Success",
    "status.warning": "Warning",
    "status.info": "Information",
    "status.processing": "Processing...",
    "status.ready": "Ready",
    "status.busy": "Busy",
    "status.idle": "Idle",
    "status.waiting": "Waiting...",
    "status.timeout": "Timeout",
    "status.retrying": "Retrying...",
    "status.cancelled": "Cancelled",
    "status.completed": "Completed",
    "status.failed": "Failed",
    "status.pending": "Pending",
    "status.running": "Running",
    "status.stopped": "Stopped",

    # ── 引擎名称 ──
    "engine.local_model": "Local Model",
    "engine.deepseek_api": "DeepSeek API",
    "engine.mimo_api": "MiMo API",
    "engine.ollama": "Ollama",
    "engine.lmstudio": "LM Studio",
    "engine.openai_api": "OpenAI API",
    "engine.auto_select": "Auto Select",

    # ── 技能分类 ──
    "skill.category.code_generation": "Code Generation",
    "skill.category.code_review": "Code Review",
    "skill.category.testing": "Testing",
    "skill.category.debugging": "Debugging",
    "skill.category.documentation": "Documentation",
    "skill.category.refactoring": "Refactoring",
    "skill.category.data_analysis": "Data Analysis",
    "skill.category.web_development": "Web Development",
    "skill.category.devops": "DevOps",
    "skill.category.security": "Security",
    "skill.category.optimization": "Optimization",
    "skill.category.conversion": "Conversion",
    "skill.category.general": "General",

    # ── 通用 UI ──
    "ui.title": "Lemon Code Agent",
    "ui.welcome": "Welcome",
    "ui.no_results": "No results found",
    "ui.please_select": "Please select",
    "ui.please_input": "Please input",
    "ui.confirm_action": "Are you sure?",
    "ui.unsaved_changes": "You have unsaved changes",
    "ui.operation_successful": "Operation completed successfully",
    "ui.operation_failed": "Operation failed",
    "ui.code_completion": "Code Completion",
    "ui.items_count": "{count} items",

    # ── Activity Bar ──
    "activity.files": "Explorer (Ctrl+Shift+E)",
    "activity.search": "Search (Ctrl+Shift+F)",
    "activity.git": "Source Control (Ctrl+Shift+G)",
    "activity.run": "Run & Debug (Ctrl+Shift+D)",
    "activity.test": "Testing (Ctrl+Shift+T)",
    "activity.extensions": "Extensions (Ctrl+Shift+X)",
    "activity.settings": "Settings (Ctrl+,)",

    # ── Agent Status Light ──
    "agent_status.working": "Agent is executing tasks",
    "agent_status.thinking": "Agent is thinking",
    "agent_status.executing": "Agent is executing tasks",
    "agent_status.idle": "Agent is on standby",
    "agent_status.ready": "Agent is on standby",
    "agent_status.connected": "Connected, on standby",
    "agent_status.standby": "Agent is on standby",
    "agent_status.confirm": "Manual confirmation required",
    "agent_status.permission": "Authorization required",
    "agent_status.waiting": "Waiting for user confirmation",
    "agent_status.error": "Agent error",
    "agent_status.failed": "Agent execution failed",
    "agent_status.unknown": "Agent status: {state}",

    # ── Onboarding 引导 ──
    "onboarding.lang_title": "Choose Language",
    "onboarding.lang_subtitle": "Select your preferred language to get started",
    "onboarding.lang_zh": "简体中文",
    "onboarding.lang_en": "English",
    "onboarding.welcome_title": "Welcome to LemonCode",
    "onboarding.welcome_subtitle": "Your AI-powered coding agent. Let me help you get started in 30 seconds.",
    "onboarding.feature_chat": "Chat with AI to generate, edit, and debug code",
    "onboarding.feature_git": "Automatic git checkpoints on every file change",
    "onboarding.feature_engines": "Works with Ollama, DeepSeek, OpenAI, and more",
    "onboarding.btn_get_started": "Get Started",
    "onboarding.engine_title": "Choose Your Engine",
    "onboarding.engine_subtitle": "Select an AI engine to power your coding assistant.",
    "onboarding.engine_ollama": "Ollama (Local)",
    "onboarding.engine_ollama_desc": "Free, runs locally, private",
    "onboarding.engine_deepseek": "DeepSeek Cloud",
    "onboarding.engine_deepseek_desc": "Fast, affordable API",
    "onboarding.engine_mimocode": "MimoCode",
    "onboarding.engine_mimocode_desc": "Built-in engine",
    "onboarding.btn_back": "Back",
    "onboarding.btn_next": "Next",
    "onboarding.tips_title": "Quick Tips",
    "onboarding.tip_send": "Send message",
    "onboarding.tip_trust": "Toggle auto-approve tool calls",
    "onboarding.tip_help": "Show all commands",
    "onboarding.tip_diff": "Review changes before applying",
    "onboarding.btn_start_coding": "Start Coding",

    # ── 会话相关 ──
    "session.new": "New Session",
    "session.switch": "Switch Session",
    "session.close": "Close Session",
    "session.rename": "Rename Session",
    "session.history": "Session History",
    "session.export": "Export Session",
    "session.clear": "Clear Session",

    # ── 代码相关 ──
    "code.run": "Run",
    "code.debug": "Debug",
    "code.format": "Format",
    "code.analyze": "Analyze",
    "code.lint": "Lint",
    "code.test": "Test",
    "code.build": "Build",
    "code.deploy": "Deploy",

    # ── 模式相关 ──
    "mode.standard": "Standard Mode",
    "mode.hybrid": "Hybrid Mode",
    "mode.build": "Build Mode",
    "mode.plan": "Plan Mode",
    "mode.compose": "Compose Mode",
    "mode.terminal": "Terminal Mode",
    "mode.demo": "Demo Mode",

    # ── 通知/提示 ──
    "notification.update_available": "A new version is available",
    "notification.connection_lost": "Connection lost, reconnecting...",
    "notification.model_switched": "Model switched to {model}",
    "notification.language_changed": "Language changed to {language}",
    "notification.save_success": "Saved successfully",
    "notification.export_success": "Exported successfully",
    "notification.import_success": "Imported successfully",

    # ── Skill 系统 ──
    "skill.execute": "Execute Skill",
    "skill.execute_success": "Skill executed successfully",
    "skill.execute_failed": "Skill execution failed",
    "skill.not_found": "Skill not found: {skill_name}",
    "skill.loading": "Loading skill...",
    "skill.loaded": "Skill loaded: {skill_name}",
    "skill.registered": "Skill registered: {skill_name}",
    "skill.unregistered": "Skill unregistered: {skill_name}",
    "skill.hot_reload": "Skill hot-reloaded: {skill_name}",
    "skill.category.all": "All Skills",
    "skill.category.builtin": "Built-in Skills",
    "skill.category.custom": "Custom Skills",
    "skill.panel.title": "Skill Panel",
    "skill.panel.search": "Search skills...",
    "skill.panel.filter": "Filter by category",

    # ── Agent 角色系统 ──
    "agent.role.coder": "Code Expert",
    "agent.role.analyst": "Data Analyst",
    "agent.role.writer": "Writing Expert",
    "agent.role.assistant": "Assistant",
    "agent.emotion.smile": "Smiling",
    "agent.emotion.angry": "Angry",
    "agent.emotion.thinking": "Thinking",
    "agent.emotion.sleepy": "Sleepy",
    "agent.emotion.surprised": "Surprised",
    "agent.emotion.happy": "Happy",
    "agent.emotion.confused": "Confused",
    "agent.emotion.bored": "Bored",
    "agent.emotion.focused": "Focused",
    "agent.emotion.shy": "Shy",
    "agent.behavior.throw_trash": "Throwing trash",
    "agent.behavior.pretend_sleep": "Pretending to sleep",
    "agent.behavior.staring": "Staring",
    "agent.behavior.yawn": "Yawning",
    "agent.behavior.stretch": "Stretching",
    "agent.behavior.check_time": "Checking time",
    "agent.behavior.drink_tea": "Drinking tea",
    "agent.behavior.read_doc": "Reading documentation",
    "agent.behavior.take_notes": "Taking notes",
    "agent.behavior.eye_mask": "Wearing eye mask",

    # ── Lemon AI Engine ──
    "engine.lemon.title": "Lemon AI Engine",
    "engine.lemon.training": "Training Lemon model...",
    "engine.lemon.evaluating": "Evaluating model...",
    "engine.lemon.quantizing": "Quantizing model...",
    "engine.lemon.deploying": "Deploying to Ollama...",
    "engine.lemon.ready": "Lemon engine ready",
    "engine.lemon.error": "Lemon engine error: {error}",

    # ── 插件市场 ──
    "plugin.market.title": "Plugin Market",
    "plugin.market.search": "Search plugins...",
    "plugin.market.install": "Install",
    "plugin.market.uninstall": "Uninstall",
    "plugin.market.enable": "Enable",
    "plugin.market.disable": "Disable",
    "plugin.market.installed": "Installed",
    "plugin.market.available": "Available",
    "plugin.market.builtin": "Built-in",
    "plugin.market.third_party": "Third-party",
    "plugin.market.version": "Version",
    "plugin.market.author": "Author",
    "plugin.market.description": "Description",
    "plugin.market.create_local": "Create Local Plugin",
    "plugin.market.create_plugin": "Create Plugin",
    "plugin.market.plugin_id": "Plugin ID",
    "plugin.market.display_name": "Display Name",
    "plugin.market.icon": "Icon",
    "plugin.market.category": "Category",
    "plugin.market.plugin_created": "Plugin created successfully",
    "plugin.market.plugin_create_failed": "Plugin creation failed",
    "plugin.market.local_only": "Local Only",

    # ── Agent 角色配置 ──
    "agent.role.config": "Role Configuration",
    "agent.role.config.dialog_title": "Agent Role Configuration",
    "agent.role.select_role": "Select Role",
    "agent.role.current_role": "Current Role",
    "agent.role.apply": "Apply Role",
    "agent.role.switch_coder": "Switch to Code Expert",
    "agent.role.switch_analyst": "Switch to Data Analyst",
    "agent.role.switch_writer": "Switch to Writing Expert",
    "agent.role.switch_assistant": "Switch to Assistant",
    "agent.role.status_prefix": "[Role: {role}]",

    # ── 窗口控制 ──
    "window.minimize": "Minimize",
    "window.maximize": "Maximize",
    "window.close": "Close Window",
    "window.engine": "AI Engine",
    "window.not_selected": "Not Selected",

    # ── 插件市场面板 (plugin_market.py) ──
    "plugin.market.search_placeholder": "Search plugins...",
    "plugin.market.refresh": "Refresh",
    "plugin.market.col_name": "Plugin Name",
    "plugin.market.col_version": "Version",
    "plugin.market.col_author": "Author",
    "plugin.market.col_status": "Status",
    "plugin.market.col_action": "Action",
    "plugin.market.detail_title": "Plugin Details",
    "plugin.market.detail_placeholder": "Select a plugin to view details...",
    "plugin.market.enable": "Enable",
    "plugin.market.disable": "Disable",
    "plugin.market.reload": "Reload",
    "plugin.market.uninstall": "Uninstall",
    "plugin.market.status_ready": "Ready",
    "plugin.market.status_enabled": "Enabled",
    "plugin.market.status_disabled": "Disabled",
    "plugin.market.manager_missing": "PluginManager not set",
    "plugin.market.loaded_count": "✅ Loaded {count} plugins",

    # ── 插件分类 ──
    "plugin.category.all": "All",
    "plugin.category.editor": "Editor",
    "plugin.category.tool": "Tool",
    "plugin.category.format": "Format",
    "plugin.category.code": "Code",
    "plugin.category.text": "Text",
    "plugin.category.document": "Document",
    "plugin.category.language": "Language",
    "plugin.category.network": "Network",
    "plugin.category.terminal": "Terminal",
    "plugin.category.data": "Data",
    "plugin.category.image": "Image",
    "plugin.category.analysis": "Analysis",
    "plugin.category.theme": "Theme",
    "plugin.category.collab": "Collaboration",
    "plugin.category.other": "Other",

    # ── 插件市场浏览器视图 ──
    "plugin.market.featured": "★ Featured",
    "plugin.market.installed_tab": "📦 Installed",
    "plugin.market.latest": "🆕 Latest",
    "plugin.market.category": "Category",
    "plugin.market.search_browser": "Search plugin name, description...",

    # ── 主窗口菜单 ──
    "menu.file_menu": "File(&F)",
    "menu.file.new_file": "New File",
    "menu.file.open_folder": "Open Folder",
    "menu.file.save_all": "Save All",
    "menu.file.close_editor": "Close Editor",
    "menu.edit_menu": "Edit(&E)",
    "menu.edit_undo": "Undo",
    "menu.edit_redo": "Redo",
    "menu.edit_cut": "Cut",
    "menu.edit_copy": "Copy",
    "menu.edit_paste": "Paste",
    "menu.edit_find": "Find",
    "menu.edit_replace": "Replace",
    "menu.edit_select_all": "Select All",
    "menu.edit_select_line": "Select Line",
    "menu.edit_extend_selection": "Extend Selection",
    "menu.select_menu": "Select(&S)",
    "menu.goto_menu": "Go To(&G)",
    "menu.view_menu": "View(&V)",
    "menu.view_toggle_sidebar": "Toggle Sidebar",
    "menu.view_toggle_panel": "Toggle Panel",
    "menu.view_toggle_terminal": "Toggle Terminal",
    "menu.view_explorer": "Explorer",
    "menu.view_search": "Search",
    "menu.view_scm": "Source Control",
    "menu.view_goto_file": "Go to File",
    "menu.view_goto_line": "Go to Line",
    "menu.view_goto_symbol": "Go to Symbol",
    "menu.view_goto_definition": "Go to Definition",
    "menu.run_menu": "Run(&R)",
    "menu.run_run": "Run",
    "menu.run_debug": "Debug",
    "menu.run_stop": "Stop",
    "menu.run_config": "Run Configuration",
    "menu.help_menu": "Help(&H)",
    "menu.help_doc": "Documentation",
    "menu.help_shortcuts": "Keyboard Shortcuts",
    "menu.help_about": "About LemonCode",

    # ── 主窗口会话/模型 ──
    "main.session": "Session:",
    "main.model": "Model:",
    "main.refresh_sessions": "Refresh session list",

    # ── Miemie panel (miemie_panel.py) ──
    "miemie.title": "MIEMIE Style Engine",
    "miemie.title_svg": '<span style="color:#ff7a2f;">MIEMIE</span> Miemie · Style Engine',
    "miemie.sub_idle": "Idle · Waiting for tasks",
    "miemie.btn.export": "Export Chat",
    "miemie.btn.history": "History (Coming soon)",
    "miemie.btn.help": "Help",
    "miemie.btn.clear": "Clear Chat",
    "miemie.btn.avatar_style": "Avatar style: {style}",
    "miemie.btn.persona": "Persona Workspace",
    "miemie.perm.auto": "Auto-run low risk; confirm for high risk (bash/write/edit/network)",
    "miemie.perm.confirm": "Ask you before every execution",
    "miemie.perm.debug": "Debug mode: log all tool calls",
    "miemie.perm.prefix": "Perm·{label}",
    "miemie.perm.auto_short": "Auto",
    "miemie.perm.confirm_short": "Confirm",
    "miemie.perm.debug_short": "Debug",
    "miemie.cmd.placeholder": "Type a task, e.g. analyze project, /search TODO, /help",
    "miemie.btn.send": "Send",
    "miemie.state.running": "Running…",
    "miemie.state.done": "Done",
    "miemie.state.error": "Failed",
    "miemie.toggle.params_open": "Args ▾",
    "miemie.toggle.params_close": "Args ▸",
    "miemie.toggle.body_open": "Collapse ▾",
    "miemie.toggle.body_close": "Expand ▸",
    "miemie.risk.high": "High Risk",
    "miemie.risk.confirm": "Confirm Mode",
    "miemie.wait_confirm": "Awaiting confirmation",
    "miemie.thinking": "Miemie is thinking…",
    "miemie.tool.failed": "Failed: {err}",
    "miemie.tool.exec_failed": "Execution failed",
    "miemie.tool.result_truncated": "… {count} total, truncated",
    "miemie.tool.no_match": "(no matches)",
    "miemie.tool.file_head": "{path}  ({lines} lines / {chars} chars)",
    "miemie.tool.content_truncated": "\n…(content too long, truncated)",
    "miemie.tool.url_head": "{url}  ({chars} chars)",
    "miemie.tool.style_target": "Target: {target}",
    "miemie.tool.style_analyzed": "Files analyzed: {count} · total lines: {total}",
    "miemie.tool.style_naming": "Naming: {style} · Indent: {indent} ({width} spaces)",
    "miemie.tool.style_avg": "Avg function length: {avg} lines · long function ratio: {ratio}%",
    "miemie.tool.style_tags": "Tags: {tags}",
    "miemie.tool.style_summary": "Summary: {summary}",
    "miemie.tool.memory_empty": "(no relevant memories)",
    "miemie.tool.sql_empty": "(empty result, {count} rows)",
    "miemie.tool.sql_goal": "Goal: {goal} · {py_files} Python files detected",
    "miemie.tool.replaced": "{path} replaced {count} places",
    "miemie.tool.written": "Written {path} ({chars} chars)",
    "miemie.tool.intent": "Intent: {intent}",
    "miemie.tool.reason": "Reason: {reason}",
    "miemie.tool.result": "Tool result",
    "miemie.persona.title": "Miemie Persona · Portrait",
    "miemie.persona.tip": "This is how Miemie understands you (Layer 1 persona, fully local).\n",
    "miemie.persona.calib_title": "Calibration chat (multi-round, the more you chat the better Miemie knows you)",
    "miemie.persona.batch_info": "Pick a folder to batch-analyze images in background",
    "miemie.persona.no_portrait": "(No portrait yet. Use \"Analyze my style\" or feed materials to create one.)",
    "miemie.persona.portrait": "Portrait: {text}",
    "miemie.persona.communication": "Communication style: {text}",
    "miemie.persona.aesthetic": "Aesthetic: {text}",
    "miemie.persona.calib_placeholder": "Calibrate: e.g. \"I'm actually very outgoing\"",
    "miemie.persona.feed_placeholder": "Feed text (optional):",
    "miemie.persona.img_placeholder": "Image path (optional, comma-separated)",
    "miemie.persona.need_calib_input": "Please enter calibration feedback first",
    "miemie.persona.calibrating": "Calibrating… (local LLM, a few seconds)",
    "miemie.persona.calib_done": "[Done] {summary}",
    "miemie.persona.calib_failed": "[Failed] {err}",
    "miemie.persona.calib_failed_short": "Calibration failed",
    "miemie.persona.need_feed_input": "Please enter feed text or image path first",
    "miemie.persona.enqueue_failed": "[Failed] {err}",
    "miemie.persona.enqueue_failed_short": "Enqueue failed",
    "miemie.persona.no_images": "No images found in folder",
    "miemie.persona.capture_paste": "[Capture] Pasted {count} clipboard image(s).",
    "miemie.persona.capture_added": "[Capture] Dropped {count} file(s).",
    "miemie.persona.capture_added_pick": "[Capture] Picked {count} file(s).",
    "miemie.persona.capture_url": "[Capture] Added {count} file(s) from URL.",
    "miemie.persona.capture_text": "[Capture] Added text material ({count} chars).",
    "miemie.persona.capture_cleared": "[Capture] Materials cleared.",
    "miemie.persona.capture_no_image": "No image in clipboard",
    "miemie.persona.capture_invalid": "Invalid clipboard image",
    "miemie.persona.capture_save_fail": "Failed to save clipboard image",
    "miemie.persona.no_material": "(no materials yet)",
    "miemie.persona.need_material": "Please add materials first (text/image/file)",
    "miemie.persona.queuing": "[Analyze] Enqueuing…",
    "miemie.persona.enqueued": "[Enqueued] {name} → #{id}",
    "miemie.persona.queued_n": "Enqueued {count} item(s), refining in background…",
    "miemie.persona.parse_fail": "(cannot parse {name}: missing library {err})",
    "miemie.persona.parse_fail_2": "(parse failed: {err})",
    "miemie.persona.queue_progress": "{done}/{total} done (running {running})",
    "miemie.persona.item_done": "[Done] #{id} {summary}",
    "miemie.persona.item_failed": "[Failed] #{id} {err}",
    "miemie.persona.analyze_done": "Analysis complete",
    "miemie.persona.analyze_finished": "[Analyze] Done ({done} ok, {err} failed), refreshing traits.",
    "miemie.persona.analyze_failed": "Analysis failed",
    "miemie.persona.no_archive": "(no archive yet)",
    "miemie.persona.saved": "Saved to persona profile",
    "miemie.persona.save_fail": "Save failed: {err}",
    "miemie.persona.calib_dialog": "AI Calibration",
    "miemie.persona.calib_input": "Enter calibration feedback (e.g. \"I'm actually very outgoing\"):",
    "miemie.persona.calibrating_short": "Calibrating…",
    "miemie.persona.calib_done_short": "Calibration done",
    "miemie.persona.calib_updated": "AI calibration updated the portrait",
    "miemie.persona.calib_failed_3": "Calibration failed",
    "miemie.persona.tag_placeholder": "One-line description of this person…",
    "miemie.persona.traits": "Feature traits (click to enable)",
    "miemie.persona.desc": "Portrait description (editable)",
    "miemie.persona.btn_save": "Save Portrait",
    "miemie.persona.btn_calib": "AI Calibrate",
    "miemie.persona.btn_clear": "Clear Materials",
    "miemie.persona.btn_analyze": "Start Analysis",
    "miemie.persona.standby": "Standby",
    "miemie.persona.big5.openness": "Openness",
    "miemie.persona.big5.conscientiousness": "Conscientiousness",
    "miemie.persona.big5.extraversion": "Extraversion",
    "miemie.persona.big5.agreeableness": "Agreeableness",
    "miemie.persona.big5.neuroticism": "Neuroticism",
}


# ============================================================
# 内置中文翻译 (zh_CN) — 硬编码作为内置回退
# ============================================================

_BUILTIN_ZH_CN: Dict[str, str] = {
    # ── 菜单项 ──
    "menu.file": "文件",
    "menu.file.new": "新建",
    "menu.file.open": "打开",
    "menu.file.save": "保存",
    "menu.file.save_as": "另存为",
    "menu.file.close": "关闭",
    "menu.file.exit": "退出",
    "menu.edit": "编辑",
    "menu.edit.undo": "撤销",
    "menu.edit.redo": "重做",
    "menu.edit.cut": "剪切",
    "menu.edit.copy": "复制",
    "menu.edit.paste": "粘贴",
    "menu.edit.select_all": "全选",
    "menu.edit.find": "查找",
    "menu.edit.replace": "替换",
    "menu.view": "视图",
    "menu.view.zoom_in": "放大",
    "menu.view.zoom_out": "缩小",
    "menu.view.fullscreen": "全屏",
    "menu.view.toggle_terminal": "切换终端",
    "menu.view.toggle_panel": "切换面板",
    "menu.help": "帮助",
    "menu.help.about": "关于",
    "menu.help.documentation": "文档",
    "menu.help.check_updates": "检查更新",
    "menu.settings": "设置",
    "menu.settings.preferences": "偏好设置",
    "menu.settings.language": "语言",
    "menu.settings.theme": "主题",
    "menu.tools": "工具",
    "menu.tools.options": "选项",
    "menu.tools.plugins": "插件",
    "menu.window": "窗口",
    "menu.window.minimize": "最小化",
    "menu.window.maximize": "最大化",

    # ── 常用按钮 ──
    "button.ok": "确定",
    "button.cancel": "取消",
    "button.save": "保存",
    "button.delete": "删除",
    "button.search": "搜索",
    "button.export": "导出",
    "button.import": "导入",
    "button.refresh": "刷新",
    "button.reset": "重置",
    "button.apply": "应用",
    "button.confirm": "确认",
    "button.retry": "重试",
    "button.skip": "跳过",
    "button.next": "下一步",
    "button.previous": "上一步",
    "button.back": "返回",
    "button.forward": "前进",
    "button.submit": "提交",
    "button.clear": "清空",
    "button.close": "关闭",
    "button.add": "添加",
    "button.remove": "移除",
    "button.edit": "编辑",
    "button.copy": "复制",
    "button.paste": "粘贴",
    "button.upload": "上传",
    "button.download": "下载",
    "button.send": "发送",
    "button.stop": "停止",
    "button.start": "启动",
    "button.pause": "暂停",
    "button.resume": "继续",
    "button.restart": "重启",

    # ── 状态消息 ──
    "status.loading": "加载中...",
    "status.connected": "已连接",
    "status.disconnected": "已断开",
    "status.connecting": "连接中...",
    "status.error": "错误",
    "status.success": "成功",
    "status.warning": "警告",
    "status.info": "信息",
    "status.processing": "处理中...",
    "status.ready": "就绪",
    "status.busy": "忙碌",
    "status.idle": "空闲",
    "status.waiting": "等待中...",
    "status.timeout": "超时",
    "status.retrying": "重试中...",
    "status.cancelled": "已取消",
    "status.completed": "已完成",
    "status.failed": "失败",
    "status.pending": "待处理",
    "status.running": "运行中",
    "status.stopped": "已停止",

    # ── 引擎名称 ──
    "engine.local_model": "本地模型",
    "engine.deepseek_api": "DeepSeek API",
    "engine.mimo_api": "MiMo API",
    "engine.ollama": "Ollama",
    "engine.lmstudio": "LM Studio",
    "engine.openai_api": "OpenAI API",
    "engine.auto_select": "自动选择",

    # ── 技能分类 ──
    "skill.category.code_generation": "代码生成",
    "skill.category.code_review": "代码审查",
    "skill.category.testing": "测试",
    "skill.category.debugging": "调试",
    "skill.category.documentation": "文档",
    "skill.category.refactoring": "重构",
    "skill.category.data_analysis": "数据分析",
    "skill.category.web_development": "Web 开发",
    "skill.category.devops": "运维部署",
    "skill.category.security": "安全",
    "skill.category.optimization": "性能优化",
    "skill.category.conversion": "格式转换",
    "skill.category.general": "通用",

    # ── 通用 UI ──
    "ui.title": "Lemon Code Agent",
    "ui.welcome": "欢迎使用",
    "ui.no_results": "未找到结果",
    "ui.please_select": "请选择",
    "ui.please_input": "请输入",
    "ui.confirm_action": "确定要执行此操作吗？",
    "ui.unsaved_changes": "您有未保存的更改",
    "ui.operation_successful": "操作成功完成",
    "ui.operation_failed": "操作失败",
    "ui.code_completion": "代码补全",
    "ui.items_count": "{count} 项",

    # ── Activity Bar ──
    "activity.files": "资源管理器 (Ctrl+Shift+E)",
    "activity.search": "搜索 (Ctrl+Shift+F)",
    "activity.git": "源码管理 (Ctrl+Shift+G)",
    "activity.run": "运行和调试 (Ctrl+Shift+D)",
    "activity.test": "测试 (Ctrl+Shift+T)",
    "activity.extensions": "扩展 (Ctrl+Shift+X)",
    "activity.settings": "设置 (Ctrl+,)",

    # ── Agent Status Light ──
    "agent_status.working": "Agent 正在执行任务",
    "agent_status.thinking": "Agent 正在思考",
    "agent_status.executing": "Agent 正在执行任务",
    "agent_status.idle": "Agent 待命中",
    "agent_status.ready": "Agent 待命中",
    "agent_status.connected": "已连接，待命中",
    "agent_status.standby": "Agent 待命中",
    "agent_status.confirm": "需要手动确认",
    "agent_status.permission": "需要授权",
    "agent_status.waiting": "等待用户确认",
    "agent_status.error": "Agent 异常",
    "agent_status.failed": "Agent 执行失败",
    "agent_status.unknown": "状态: {state}",

    # ── Onboarding 引导 ──
    "onboarding.lang_title": "选择语言",
    "onboarding.lang_subtitle": "选择您偏好的语言以开始使用",
    "onboarding.lang_zh": "简体中文",
    "onboarding.lang_en": "English",
    "onboarding.welcome_title": "欢迎使用 LemonCode",
    "onboarding.welcome_subtitle": "您的 AI 编程助手，30 秒即可上手。",
    "onboarding.feature_chat": "与 AI 对话，生成、编辑和调试代码",
    "onboarding.feature_git": "每次文件变更自动创建 git 检查点",
    "onboarding.feature_engines": "支持 Ollama、DeepSeek、OpenAI 等",
    "onboarding.btn_get_started": "开始使用",
    "onboarding.engine_title": "选择引擎",
    "onboarding.engine_subtitle": "选择一个 AI 引擎来驱动您的编程助手。",
    "onboarding.engine_ollama": "Ollama（本地）",
    "onboarding.engine_ollama_desc": "免费、本地运行、隐私安全",
    "onboarding.engine_deepseek": "DeepSeek 云端",
    "onboarding.engine_deepseek_desc": "快速、实惠的 API",
    "onboarding.engine_mimocode": "MimoCode",
    "onboarding.engine_mimocode_desc": "内置引擎",
    "onboarding.btn_back": "返回",
    "onboarding.btn_next": "下一步",
    "onboarding.tips_title": "快捷提示",
    "onboarding.tip_send": "发送消息",
    "onboarding.tip_trust": "切换自动批准工具调用",
    "onboarding.tip_help": "显示所有命令",
    "onboarding.tip_diff": "应用前预览变更",
    "onboarding.btn_start_coding": "开始编程",

    # ── 会话相关 ──
    "session.new": "新建会话",
    "session.switch": "切换会话",
    "session.close": "关闭会话",
    "session.rename": "重命名会话",
    "session.history": "会话历史",
    "session.export": "导出会话",
    "session.clear": "清空会话",

    # ── 代码相关 ──
    "code.run": "运行",
    "code.debug": "调试",
    "code.format": "格式化",
    "code.analyze": "分析",
    "code.lint": "代码检查",
    "code.test": "测试",
    "code.build": "构建",
    "code.deploy": "部署",

    # ── 模式相关 ──
    "mode.standard": "标准模式",
    "mode.hybrid": "混合模式",
    "mode.build": "构建模式",
    "mode.plan": "计划模式",
    "mode.compose": "编写模式",
    "mode.terminal": "终端模式",
    "mode.demo": "演示模式",

    # ── 通知/提示 ──
    "notification.update_available": "有新版本可用",
    "notification.connection_lost": "连接断开，正在重连...",
    "notification.model_switched": "模型已切换至 {model}",
    "notification.language_changed": "语言已切换至 {language}",
    "notification.save_success": "保存成功",
    "notification.export_success": "导出成功",
    "notification.import_success": "导入成功",

    # ── Skill 系统 ──
    "skill.execute": "执行技能",
    "skill.execute_success": "技能执行成功",
    "skill.execute_failed": "技能执行失败",
    "skill.not_found": "未找到技能: {skill_name}",
    "skill.loading": "加载技能中...",
    "skill.loaded": "技能已加载: {skill_name}",
    "skill.registered": "技能已注册: {skill_name}",
    "skill.unregistered": "技能已注销: {skill_name}",
    "skill.hot_reload": "技能已热加载: {skill_name}",
    "skill.category.all": "全部技能",
    "skill.category.builtin": "内置技能",
    "skill.category.custom": "自定义技能",
    "skill.panel.title": "技能面板",
    "skill.panel.search": "搜索技能...",
    "skill.panel.filter": "按分类筛选",

    # ── Agent 角色系统 ──
    "agent.role.coder": "代码专家",
    "agent.role.analyst": "数据分析师",
    "agent.role.writer": "写作专家",
    "agent.role.assistant": "助手",
    "agent.emotion.smile": "微笑",
    "agent.emotion.angry": "生气",
    "agent.emotion.thinking": "思考中",
    "agent.emotion.sleepy": "困倦",
    "agent.emotion.surprised": "惊讶",
    "agent.emotion.happy": "开心",
    "agent.emotion.confused": "困惑",
    "agent.emotion.bored": "无聊",
    "agent.emotion.focused": "专注",
    "agent.emotion.shy": "害羞",
    "agent.behavior.throw_trash": "扔垃圾",
    "agent.behavior.pretend_sleep": "装睡",
    "agent.behavior.staring": "发呆",
    "agent.behavior.yawn": "打哈欠",
    "agent.behavior.stretch": "伸懒腰",
    "agent.behavior.check_time": "看时间",
    "agent.behavior.drink_tea": "喝茶",
    "agent.behavior.read_doc": "看文档",
    "agent.behavior.take_notes": "记笔记",
    "agent.behavior.eye_mask": "戴眼罩",

    # ── Lemon AI Engine ──
    "engine.lemon.title": "Lemon AI 引擎",
    "engine.lemon.training": "正在训练 Lemon 模型...",
    "engine.lemon.evaluating": "正在评估模型...",
    "engine.lemon.quantizing": "正在量化模型...",
    "engine.lemon.deploying": "正在部署到 Ollama...",
    "engine.lemon.ready": "Lemon 引擎就绪",
    "engine.lemon.error": "Lemon 引擎错误: {error}",

    # ── 插件市场 ──
    "plugin.market.title": "插件市场",
    "plugin.market.search": "搜索插件...",
    "plugin.market.install": "安装",
    "plugin.market.uninstall": "卸载",
    "plugin.market.enable": "启用",
    "plugin.market.disable": "禁用",
    "plugin.market.installed": "已安装",
    "plugin.market.available": "可用",
    "plugin.market.builtin": "内置",
    "plugin.market.third_party": "第三方",
    "plugin.market.version": "版本",
    "plugin.market.author": "作者",
    "plugin.market.description": "描述",
    "plugin.market.create_local": "创建本地插件",
    "plugin.market.create_plugin": "创建插件",
    "plugin.market.plugin_id": "插件标识",
    "plugin.market.display_name": "显示名称",
    "plugin.market.icon": "图标",
    "plugin.market.category": "分类",
    "plugin.market.plugin_created": "插件创建成功",
    "plugin.market.plugin_create_failed": "插件创建失败",
    "plugin.market.local_only": "纯本地",

    # ── Agent 角色配置 ──
    "agent.role.config": "角色配置",
    "agent.role.config.dialog_title": "Agent 角色配置",
    "agent.role.select_role": "选择角色",
    "agent.role.current_role": "当前角色",
    "agent.role.apply": "应用角色",
    "agent.role.switch_coder": "切换代码专家",
    "agent.role.switch_analyst": "切换数据分析师",
    "agent.role.switch_writer": "切换写作专家",
    "agent.role.switch_assistant": "切换助手",
    "agent.role.status_prefix": "[角色: {role}]",

    # ── 窗口控制 ──
    "window.minimize": "最小化窗口",
    "window.maximize": "最大化窗口",
    "window.close": "关闭窗口",
    "window.engine": "AI引擎",
    "window.not_selected": "未选择",

    # ── 插件市场面板 ──
    "plugin.market.search_placeholder": "搜索插件...",
    "plugin.market.refresh": "刷新",
    "plugin.market.col_name": "插件名称",
    "plugin.market.col_version": "版本",
    "plugin.market.col_author": "作者",
    "plugin.market.col_status": "状态",
    "plugin.market.col_action": "操作",
    "plugin.market.detail_title": "插件详情",
    "plugin.market.detail_placeholder": "选择插件查看详情...",
    "plugin.market.enable": "启用",
    "plugin.market.disable": "禁用",
    "plugin.market.reload": "重载",
    "plugin.market.uninstall": "卸载",
    "plugin.market.status_ready": "就绪",
    "plugin.market.status_enabled": "已启用",
    "plugin.market.status_disabled": "已禁用",
    "plugin.market.manager_missing": "PluginManager 未设置",
    "plugin.market.loaded_count": "✅ 已加载 {count} 个插件",

    # ── 插件分类 ──
    "plugin.category.all": "全部",
    "plugin.category.editor": "编辑器",
    "plugin.category.tool": "工具",
    "plugin.category.format": "格式",
    "plugin.category.code": "代码",
    "plugin.category.text": "文本",
    "plugin.category.document": "文档",
    "plugin.category.language": "语言",
    "plugin.category.network": "网络",
    "plugin.category.terminal": "终端",
    "plugin.category.data": "数据",
    "plugin.category.image": "图像",
    "plugin.category.analysis": "分析",
    "plugin.category.theme": "主题",
    "plugin.category.collab": "协作",
    "plugin.category.other": "其他",

    # ── 插件市场浏览器视图 ──
    "plugin.market.featured": "★ 精选推荐",
    "plugin.market.installed_tab": "📦 已安装",
    "plugin.market.latest": "🆕 最新发布",
    "plugin.market.category": "分类",
    "plugin.market.search_browser": "搜索插件名称、描述…",

    # ── 主窗口菜单 ──
    "menu.file_menu": "文件(&F)",
    "menu.file.new_file": "新建文件",
    "menu.file.open_folder": "打开文件夹",
    "menu.file.save_all": "全部保存",
    "menu.file.close_editor": "关闭编辑器",
    "menu.edit_menu": "编辑(&E)",
    "menu.edit_undo": "撤销",
    "menu.edit_redo": "重做",
    "menu.edit_cut": "剪切",
    "menu.edit_copy": "复制",
    "menu.edit_paste": "粘贴",
    "menu.edit_find": "查找",
    "menu.edit_replace": "替换",
    "menu.edit_select_all": "全选",
    "menu.edit_select_line": "选择行",
    "menu.edit_extend_selection": "扩展选择",
    "menu.select_menu": "选择(&S)",
    "menu.goto_menu": "转到(&G)",
    "menu.view_menu": "视图(&V)",
    "menu.view_toggle_sidebar": "切换侧边栏",
    "menu.view_toggle_panel": "切换面板",
    "menu.view_toggle_terminal": "切换终端",
    "menu.view_explorer": "资源管理器",
    "menu.view_search": "搜索",
    "menu.view_scm": "源码管理",
    "menu.view_goto_file": "转到文件",
    "menu.view_goto_line": "转到行",
    "menu.view_goto_symbol": "转到符号",
    "menu.view_goto_definition": "转到定义",
    "menu.run_menu": "运行(&R)",
    "menu.run_run": "运行",
    "menu.run_debug": "调试",
    "menu.run_stop": "停止",
    "menu.run_config": "运行配置",
    "menu.help_menu": "帮助(&H)",
    "menu.help_doc": "文档",
    "menu.help_shortcuts": "键盘快捷方式",
    "menu.help_about": "关于 LemonCode",

    # ── 主窗口会话/模型 ──
    "main.session": "会话:",
    "main.model": "模型:",
    "main.refresh_sessions": "刷新会话列表",

    # ── 咩咩面板 (miemie_panel.py) ──
    "miemie.title": "MIEMIE 咩咩 · 风格引擎",
    "miemie.title_svg": '<span style="color:#ff7a2f;">MIEMIE</span> 咩咩 · 风格引擎',
    "miemie.sub_idle": "空闲 · 等待任务",
    "miemie.btn.export": "导出对话",
    "miemie.btn.history": "历史（即将上线）",
    "miemie.btn.help": "帮助",
    "miemie.btn.clear": "清空对话",
    "miemie.btn.avatar_style": "形象风格：{style}",
    "miemie.btn.persona": "人格工作区（分身分析）",
    "miemie.perm.auto": "低风险自动跑，高风险(bash/写/改/网络)弹确认",
    "miemie.perm.confirm": "所有执行都先问你",
    "miemie.perm.debug": "调试模式：记录全部工具调用详情",
    "miemie.perm.prefix": "权限·{label}",
    "miemie.perm.auto_short": "自动",
    "miemie.perm.confirm_short": "确认",
    "miemie.perm.debug_short": "调试",
    "miemie.cmd.placeholder": "输入任务，例如：分析项目结构、/search TODO、/help",
    "miemie.btn.send": "发送",
    "miemie.state.running": "执行中…",
    "miemie.state.done": "已完成",
    "miemie.state.error": "失败",
    "miemie.toggle.params_open": "参数 ▾",
    "miemie.toggle.params_close": "参数 ▸",
    "miemie.toggle.body_open": "收起 ▾",
    "miemie.toggle.body_close": "展开 ▸",
    "miemie.risk.high": "高风险",
    "miemie.risk.confirm": "确认模式",
    "miemie.wait_confirm": "等待确认",
    "miemie.thinking": "咩咩思考中…",
    "miemie.tool.failed": "失败：{err}",
    "miemie.tool.exec_failed": "执行失败",
    "miemie.tool.result_truncated": "… 共 {count} 条，已截断",
    "miemie.tool.no_match": "（无匹配）",
    "miemie.tool.file_head": "{path}  （{lines} 行 / {chars} 字符）",
    "miemie.tool.content_truncated": "\n…（内容过长，已截断）",
    "miemie.tool.url_head": "{url}  （{chars} 字符）",
    "miemie.tool.style_target": "目标：{target}",
    "miemie.tool.style_analyzed": "分析文件：{count} 个  ·  总行数：{total}",
    "miemie.tool.style_naming": "命名风格：{style}  ·  缩进：{indent}（{width} 空格）",
    "miemie.tool.style_avg": "平均函数长度：{avg} 行  ·  长函数占比：{ratio}%",
    "miemie.tool.style_tags": "标签：{tags}",
    "miemie.tool.style_summary": "摘要：{summary}",
    "miemie.tool.memory_empty": "（记忆中无相关条目）",
    "miemie.tool.sql_empty": "（空结果，{count} 行）",
    "miemie.tool.sql_goal": "目标：{goal}  ·  检测到 {py_files} 个 Python 文件",
    "miemie.tool.replaced": "{path} 已替换 {count} 处",
    "miemie.tool.written": "已写入 {path}  （{chars} 字符）",
    "miemie.tool.intent": "意图识别：{intent}",
    "miemie.tool.reason": "理解：{reason}",
    "miemie.tool.result": "工具结果",
    "miemie.persona.title": "咩咩分身 · 人格画像",
    "miemie.persona.tip": "这里是咩咩对你的理解（Layer 1 人格档案，全程本地）。\n",
    "miemie.persona.calib_title": "校准对话（多轮，越聊咩咩越懂你）",
    "miemie.persona.batch_info": "选择文件夹后自动扫描图片批量炼化（后台）",
    "miemie.persona.no_portrait": "（尚无画像。用「分析我的风格」或喂料炼化后生成。）",
    "miemie.persona.portrait": "画像：{text}",
    "miemie.persona.communication": "沟通风格：{text}",
    "miemie.persona.aesthetic": "审美偏好：{text}",
    "miemie.persona.calib_placeholder": "校准：例如「我其实很外向，爱和人交流」",
    "miemie.persona.feed_placeholder": "喂料文本（可选）：",
    "miemie.persona.img_placeholder": "图片路径（可选，逗号分隔多个）",
    "miemie.persona.need_calib_input": "请先输入校准反馈",
    "miemie.persona.calibrating": "校准中…（本机 LLM 处理，约几秒）",
    "miemie.persona.calib_done": "[完成] {summary}",
    "miemie.persona.calib_failed": "[失败] {err}",
    "miemie.persona.calib_failed_short": "校准失败",
    "miemie.persona.need_feed_input": "请先输入喂料文本或图片路径",
    "miemie.persona.enqueue_failed": "[失败] {err}",
    "miemie.persona.enqueue_failed_short": "入队失败",
    "miemie.persona.no_images": "目录中未找到图片",
    "miemie.persona.capture_paste": "[采集] 粘贴 {count} 张剪贴板图片。",
    "miemie.persona.capture_added": "[采集] 拖入 {count} 个文件。",
    "miemie.persona.capture_added_pick": "[采集] 选择 {count} 个文件。",
    "miemie.persona.capture_url": "[采集] 地址引用加入 {count} 个文件。",
    "miemie.persona.capture_text": "[采集] 加入文本素材（{count} 字）。",
    "miemie.persona.capture_cleared": "[采集] 已清空素材。",
    "miemie.persona.capture_no_image": "剪贴板里没有图片",
    "miemie.persona.capture_invalid": "剪贴板图片无效",
    "miemie.persona.capture_save_fail": "保存剪贴板图片失败",
    "miemie.persona.no_material": "（暂无素材）",
    "miemie.persona.need_material": "请先添加素材（文本/图片/文件）",
    "miemie.persona.queuing": "[分析] 开始入队…",
    "miemie.persona.enqueued": "[入队] {name} → #{id}",
    "miemie.persona.queued_n": "已入队 {count} 项，后台炼化中…",
    "miemie.persona.parse_fail": "（无法解析 {name}：缺少库 {err}）",
    "miemie.persona.parse_fail_2": "（解析失败：{err}）",
    "miemie.persona.queue_progress": "完成 {done}/{total}（运行中 {running}）",
    "miemie.persona.item_done": "[完成] #{id} {summary}",
    "miemie.persona.item_failed": "[失败] #{id} {err}",
    "miemie.persona.analyze_done": "分析完成",
    "miemie.persona.analyze_finished": "[分析] 完成（成功 {done}，失败 {err}），刷新特征面板。",
    "miemie.persona.analyze_failed": "分析失败",
    "miemie.persona.no_archive": "（尚无档案）",
    "miemie.persona.saved": "已保存到人格档案",
    "miemie.persona.save_fail": "保存失败：{err}",
    "miemie.persona.calib_dialog": "AI 校准",
    "miemie.persona.calib_input": "输入校准反馈（如「我其实很外向」）：",
    "miemie.persona.calibrating_short": "校准中…",
    "miemie.persona.calib_done_short": "校准完成",
    "miemie.persona.calib_updated": "AI 校准已更新画像",
    "miemie.persona.calib_failed_3": "校准失败",
    "miemie.persona.tag_placeholder": "一句话描述这个人的画像…",
    "miemie.persona.traits": "特征标签（点选启用）",
    "miemie.persona.desc": "画像描述（可编辑）",
    "miemie.persona.btn_save": "保存画像",
    "miemie.persona.btn_calib": "AI 校准",
    "miemie.persona.btn_clear": "清空素材",
    "miemie.persona.btn_analyze": "开始分析",
    "miemie.persona.standby": "待机",
    "miemie.persona.big5.openness": "开放性",
    "miemie.persona.big5.conscientiousness": "尽责性",
    "miemie.persona.big5.extraversion": "外向性",
    "miemie.persona.big5.agreeableness": "宜人性",
    "miemie.persona.big5.neuroticism": "神经质",
}


# ============================================================
# 语言名称映射
# ============================================================

_LANGUAGE_NAMES: Dict[str, str] = {
    "zh_CN": "简体中文",
    "en_US": "English",
}

_SUPPORTED_LANGUAGES: Tuple[str, ...] = ("zh_CN", "en_US")


# ============================================================
# I18nManager
# ============================================================

class I18nManager:
    """国际化管理器 — 单例模式

    负责多语言翻译、语言检测、运行时切换和自定义翻译注入。

    使用方式：
        i18n = I18nManager()
        text = i18n.t('menu.file.open')           # 打开
        text = i18n.t('notification.model_switched', model='GPT-4')

        i18n.set_language('en_US')
        text = i18n.t('menu.file.open')           # Open
    """

    _instance: Optional["I18nManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "I18nManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # 翻译数据: {lang_code: {key: value}}
        self._translations: Dict[str, Dict[str, str]] = {}

        # 加载内置英文翻译（永远作为回退）
        self._translations["en_US"] = dict(_BUILTIN_EN_US)

        # 加载内置中文翻译
        self._translations["zh_CN"] = dict(_BUILTIN_ZH_CN)

        # 当前语言
        self._current_lang: str = "zh_CN"

        # 尝试从外部 JSON 文件加载中文翻译（覆盖内置翻译）
        self._load_locale_files()

        # 检测语言
        self._auto_detect_language()

    # ── 语言检测 ──────────────────────────────────────────

    def _auto_detect_language(self) -> None:
        """按优先级自动检测语言：
        1. 环境变量 LEMON_LANG
        2. 配置文件中的 language 设置
        3. 系统 locale
        4. 默认为 zh_CN
        """
        detected = None

        # 1. 环境变量
        env_lang = os.environ.get("LEMON_LANG", "").strip()
        if env_lang and self._is_valid_lang(env_lang):
            detected = env_lang
            logger.debug("Language detected from LEMON_LANG: %s", detected)

        # 2. 配置文件
        if detected is None:
            config_lang = self._get_config_language()
            if config_lang and self._is_valid_lang(config_lang):
                detected = config_lang
                logger.debug("Language detected from config: %s", detected)

        # 3. 系统 locale
        if detected is None:
            sys_lang = self._detect_system_locale()
            if sys_lang and self._is_valid_lang(sys_lang):
                detected = sys_lang
                logger.debug("Language detected from system locale: %s", detected)

        # 4. 默认
        if detected is None:
            detected = "zh_CN"

        self._current_lang = detected

    @staticmethod
    def _detect_system_locale() -> Optional[str]:
        """检测系统 locale 并映射到支持的语言代码。"""
        try:
            loc = locale.getdefaultlocale()
            if loc and loc[0]:
                lang_part = loc[0].lower().replace("_", "-")
                if lang_part.startswith("zh"):
                    return "zh_CN"
                if lang_part.startswith("en"):
                    return "en_US"
        except Exception:
            pass

        # 备选方案：通过环境变量
        for env_var in ("LANG", "LC_ALL", "LC_MESSAGES"):
            val = os.environ.get(env_var, "")
            if val.lower().startswith("zh"):
                return "zh_CN"
            if val.lower().startswith("en"):
                return "en_US"

        return None

    @staticmethod
    def _get_config_language() -> Optional[str]:
        """从项目配置文件中读取语言设置。"""
        config_paths = [
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "settings.json"),
            os.path.expanduser("~/.lemon_agent/settings.json"),
            os.path.expanduser("~/.mimo_agent/settings.json"),
        ]
        for config_path in config_paths:
            try:
                if os.path.isfile(config_path):
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    lang = config.get("general", {}).get("language", "")
                    if lang:
                        return lang
            except Exception:
                continue
        return None

    def _is_valid_lang(self, lang_code: str) -> bool:
        """检查语言代码是否在支持列表中。"""
        return lang_code in _SUPPORTED_LANGUAGES

    def _load_locale_files(self) -> None:
        """从 locale/ 目录加载 JSON 翻译文件，覆盖内置翻译。"""
        locale_dirs = [
            os.path.join(os.path.dirname(__file__), "locale"),
            os.path.join(os.path.dirname(__file__), "locales"),
        ]
        for locale_dir in locale_dirs:
            if not os.path.isdir(locale_dir):
                continue
            for filename in os.listdir(locale_dir):
                if not filename.endswith(".json"):
                    continue
                lang_code = filename[:-5]
                _LANG_ALIASES = {"zh": "zh_CN", "en": "en_US", "cn": "zh_CN"}
                lang_code = _LANG_ALIASES.get(lang_code, lang_code)
                if not self._is_valid_lang(lang_code):
                    continue

                filepath = os.path.join(locale_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._merge_translations(lang_code, data)
                        logger.info("Loaded locale file: %s (%d keys)", filename, len(data))
                except Exception as e:
                    logger.warning("Failed to load locale file %s: %s", filepath, e)

    # ── 翻译操作 ──────────────────────────────────────────

    def t(self, key: str, **kwargs: Any) -> str:
        """翻译给定的 key，支持格式化参数。

        Args:
            key: 翻译键，支持点号分隔的嵌套键，如 'menu.file.open'
            **kwargs: 格式化参数，如 name='World'

        Returns:
            翻译后的字符串；如果 key 不存在，返回 key 本身

        回退顺序：
            1. 当前语言
            2. 英文 (en_US)
            3. 原始 key
        """
        # 优先使用当前语言
        result = self._lookup(self._current_lang, key)
        if result is not None:
            return result.format(**kwargs) if kwargs else result

        # 回退到英文
        if self._current_lang != "en_US":
            result = self._lookup("en_US", key)
            if result is not None:
                return result.format(**kwargs) if kwargs else result

        # 最终回退到 key 本身
        return key.format(**kwargs) if kwargs else key

    def _lookup(self, lang_code: str, key: str) -> Optional[str]:
        """在指定语言中查找翻译键。"""
        translations = self._translations.get(lang_code)
        if translations is None:
            return None
        return translations.get(key)

    def set_language(self, lang_code: str) -> bool:
        """运行时切换语言。

        Args:
            lang_code: 语言代码，如 'zh_CN' 或 'en_US'

        Returns:
            True 如果切换成功，False 否则
        """
        if not self._is_valid_lang(lang_code):
            logger.warning("Unsupported language code: %s", lang_code)
            return False
        old_lang = self._current_lang
        self._current_lang = lang_code
        logger.info("Language switched: %s → %s", old_lang, lang_code)
        return True

    # ★ v5.8: 兼容别名 —— 部分测试/旧调用方使用 set_locale/_locales 命名
    def set_locale(self, lang_code: str) -> bool:
        """set_language 的别名。"""
        return self.set_language(lang_code)

    @property
    def _locales(self) -> Dict[str, Dict[str, str]]:
        """_translations 的只读别名。"""
        return self._translations

    def get_current_language(self) -> str:
        """返回当前语言代码。"""
        return self._current_lang

    def get_current_language_name(self) -> str:
        """返回当前语言的显示名称。"""
        return _LANGUAGE_NAMES.get(self._current_lang, self._current_lang)

    def get_available_languages(self) -> List[Dict[str, str]]:
        """返回可用语言列表。

        Returns:
            [{"code": "zh_CN", "name": "简体中文"}, {"code": "en_US", "name": "English"}]
        """
        return [
            {"code": code, "name": _LANGUAGE_NAMES.get(code, code)}
            for code in _SUPPORTED_LANGUAGES
        ]

    def add_translations(self, lang_code: str, translations_dict: Dict[str, str]) -> bool:
        """添加或覆盖自定义翻译。

        Args:
            lang_code: 语言代码
            translations_dict: 翻译字典，键为翻译 key，值为翻译文本

        Returns:
            True 如果添加成功，False 否则
        """
        if not lang_code or not isinstance(translations_dict, dict):
            return False
        if lang_code not in self._translations:
            self._translations[lang_code] = {}
        self._translations[lang_code].update(translations_dict)
        logger.debug("Added %d translations for %s", len(translations_dict), lang_code)
        return True

    def _merge_translations(self, lang_code: str, data: dict, prefix: str = "") -> None:
        """递归合并嵌套的翻译字典（支持 JSON 中的嵌套结构）。

        将嵌套 JSON 展平为点号分隔的键：
            {"menu": {"file": {"open": "打开"}}} → {"menu.file.open": "打开"}
        """
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                self._merge_translations(lang_code, value, full_key)
            elif isinstance(value, str):
                if lang_code not in self._translations:
                    self._translations[lang_code] = {}
                self._translations[lang_code][full_key] = value

    def reload_locale_files(self) -> None:
        """重新加载所有 locale 文件（用于开发时热更新翻译）。"""
        self._load_locale_files()
        logger.info("Locale files reloaded")


# ============================================================
# 全局单例 + 便捷函数
# ============================================================

def get_i18n() -> I18nManager:
    """获取 I18nManager 单例。"""
    return I18nManager()


def _t(key: str, **kwargs: Any) -> str:
    """便捷翻译函数 — 全局使用。

    用法：
        from standard_mode.core.i18n import _t

        label = _t('button.save')           # 保存
        msg = _t('notification.model_switched', model='DeepSeek')
    """
    return get_i18n().t(key, **kwargs)


def t(key: str, **kwargs: Any) -> str:
    return get_i18n().t(key, **kwargs)


def set_language(lang: str) -> bool:
    return get_i18n().set_language(lang)


def get_language() -> str:
    return get_i18n().get_current_language()