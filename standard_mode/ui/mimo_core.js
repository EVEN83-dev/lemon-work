"use strict";

// ============================================================
// ★ 调试日志（科学调试专用）
// ============================================================
window._dbgLog = function(hypId, msg, data) {
  var logStr = '[DEBUG][' + hypId + '] ' + msg + ' ' + JSON.stringify(data||{});
  console.log(logStr);
  try {
    var payload = {sessionId:'starfield-missing',runId:'pre-fix',hypothesisId:hypId,location:'mimo_core.js',msg:logStr,data:data||{},ts:Date.now()};
    fetch('http://127.0.0.1:7777/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),mode:'no-cors'}).catch(function(){});
  } catch(e) {}
};

// ============================================================
// ★ 全局错误捕获 — 防止JS崩溃导致整个页面不可用
// ============================================================
window.onerror = function(msg, url, line, col, error) {
  console.error('[JS Error]', msg, 'at', url, line + ':' + col);
  // 不阻止默认错误处理，让控制台也能看到
  return false;
};
window.addEventListener('unhandledrejection', function(e) {
  console.error('[Unhandled Promise]', e.reason);
});

// ============================================================
// ★ 全局兜底对象 — 防止 Python 端过早调用导致崩溃
// ============================================================
window.mimoAgent = window.mimoAgent || {
  appendMessage: function(html) { console.log('[mimoAgent兜底] appendMessage:', (html||'').substring(0,80)); },
  appendData: function(data) { console.log('[mimoAgent兜底] appendData:', data); },
  appendThinking: function(html) {},
  appendStatus: function(html) {},
  appendTool: function(html) {},
  appendTimeline: function(eventStr) {},  // ★ v4.1.15: 执行轨迹流
  appendPreview: function(html) {},
  appendUserMessage: function(text) {},
  clearOutput: function() {},
  setConnected: function(connected) {},
  setRobotStatus: function(status) {},
  setAgentState: function(state) {},
  setCurrentSession: function(sessionId) {},
  showConfigOptions: function(s, o) {},
  showPermission: function(s, t, o) {},
  showToolResult: function(s, r) {}
};

// ============================================================
// ★ 全局函数兜底 — 防止 onclick 找不到函数（真实函数在后面定义）
// ============================================================

// ============================================================
// ★ i18n — 前端国际化系统
// ============================================================
var i18n = {
  currentLang: 'zh',
  translations: {
    zh: {
      // 输入区
      'input.placeholder': '输入消息... (Enter 发送)',
      'input.send': 'LEMON',
      'input.upload': '上传图片',
      'input.attach': '附件',
      
      // 模式行
      'mode.build': 'Build',
      'mode.switch': 'Tab 切换',
      'mode.settings': 'Ctrl+P 设置',
      
      // 状态栏
      'status.engine': '引擎',
      'status.memory': 'JS堆内存',
      'status.fps': '渲染帧率',
      'status.search': '搜索消息 (Ctrl+F)',
      'status.export': '导出对话 (Ctrl+E)',
      'status.shortcuts': '快捷键 (Ctrl+/)',
      
      // 调试面板
      'debug.title': '调试',
      'debug.start': '开始',
      'debug.continue': '继续',
      'debug.pause': '暂停',
      'debug.stop': '停止',
      'debug.stepOver': '跳过',
      'debug.stepInto': '进入',
      'debug.stepOut': '跳出',
      'debug.variables': '变量',
      'debug.stack': '调用栈',
      'debug.breakpoints': '断点',
      'debug.watch': '监视',
      'debug.output': '输出',
      'debug.localVars': '局部变量',
      'debug.globalVars': '全局变量',
      'debug.noSession': '无调试会话',
      'debug.noStack': '无调用栈信息',
      'debug.noBreakpoints': '无断点',
      'debug.watchPlaceholder': '输入表达式并按 Enter 添加监视...',
      
      // 插件市场
      'plugin.title': '插件市场',
      'plugin.search': '搜索插件...',
      'plugin.market': '市场',
      'plugin.installed': '已安装',
      'plugin.config': '配置',
      'plugin.loading': '加载中...',
      
      // 设置面板
      'settings.title': '设置',
      'settings.general': '通用',
      'settings.ai': 'AI',
      'settings.appearance': '外观',
      'settings.visualization': '可视化',
      'settings.shortcuts': '快捷键',
      'settings.skin': '皮肤',
      'settings.agent': 'Agent',
      'settings.apikey': '密钥',
      'settings.about': '关于',
      'settings.language': '语言',
      'settings.languageDesc': '界面显示语言',
      'settings.reopenLast': '启动时打开上次会话',
      'settings.reopenDesc': '自动恢复上次的对话',
      'settings.sandbox': '沙箱模式',
      'settings.sandboxDesc': '代码执行安全级别',
      'settings.sandboxTrust': '信任模式（无确认）',
      'settings.sandboxManual': '手动确认（危险语言需确认）',
      'settings.sandboxStrict': '严格模式（禁止危险语言）',
      'settings.sandboxHint': '<strong>信任模式:</strong> 所有代码自动执行<br><strong>手动确认:</strong> C/C++/Bash等危险语言需确认<br><strong>严格模式:</strong> 禁止执行编译型/系统语言',
      'settings.execLanguages': '支持的执行语言',
      'settings.execDesc': '可在代码块中运行',
      'settings.aiModel': 'AI 模型',
      'settings.aiModelDesc': '选择 AI 后端服务',
      'settings.temperature': '温度参数',
      'settings.temperatureDesc': '0=精确, 1=创意, 默认 0.7',
      'settings.maxTokens': '最大 Token 数',
      'settings.maxTokensDesc': 'AI 回复的最大长度',
      'settings.agentMode': 'Agent 模式',
      'settings.agentModeDesc': '选择 Agent 运行的引擎和身份',
      'settings.agentIdentity': 'Agent 身份',
      'settings.agentIdentityDesc': 'Lemon Agent = 本地AI驱动 / MIMO Agent = 夺舍MIMO Code',
      'settings.agentAuto': '自动选择',
      'settings.agentLemon': 'Lemon Agent (本地)',
      'settings.agentMimo': 'MIMO Agent (夺舍)',
      'settings.agentIdentityHint': '<strong>Lemon Agent:</strong> 使用本地 Ollama 或 DeepSeek API 驱动，完全自主运行，不依赖 MIMO Code。<br><strong>MIMO Agent:</strong> 通过 Process Bridge 夺舍 MIMO Code 窗口，共享其 AI 能力和文件系统。',
      'settings.computeEngine': '算力引擎',
      'settings.computeEngineDesc': '选择 AI 推理的后端引擎',
      'settings.defaultEngine': '默认引擎',
      'settings.defaultEngineDesc': '新建对话时使用的引擎',
      'settings.apiKeyConfig': 'API 密钥配置',
      
      // 会话面板
      'session.search': '搜索历史消息...',
      'session.settings': '设置 (Ctrl+,)',
      
      // 搜索面板
      'search.placeholder': '搜索消息内容...',
      'search.empty': '输入关键词开始搜索...',
      
      // 通用
      'common.send': '发送',
      'common.confirm': '确认',
      'common.cancel': '取消',

      // ── 工作区 / 会话 ──
      'ws.title': '工作区列表',
      'ws.add': '＋ 添加工作区',
      'ws.pathPlaceholder': '项目路径（如 D:\\projects\\my_app）',
      'ws.namePlaceholder': '显示名称（可选）',
      'ws.cancel': '取消',
      'ws.confirmAdd': '添加',
      'ws.switch': '切换工作区...',
      'ws.loading': '加载中...',
      'ws.refresh': '刷新工作区',
      'ws.openInExplorer': '在资源管理器中打开',
      'session.label': '会话: 默认',
      'session.model': '模型: Auto',
      'session.switchHint': '切换模型 → 引擎选择器',

      // ── 输入区 / 模式行 ──
      'input.placeholderFull': '输入消息... (Enter 发送 / Shift+Enter 换行)',
      'mode.engineChip': '点击选择 AI 引擎 / 模型',
      'mode.engineStatus': 'Lemon Code',
      'mode.modelAuto': '模型: 自动',
      'mode.hintTab': '切换',
      'mode.hintSettings': '设置',
      'mode.desc.agent': '完整 AI 编程助手模式',
      'mode.desc.code': '代码生成与编辑模式',
      'mode.desc.edit': '快速编辑现有代码',
      'mode.desc.architect': '架构设计与规划',
      'mode.desc.ask': '问答与知识查询',

      // ── 咩咩面板 ──
      'miemie.panelTitle': 'MIEMIE 咩咩 · Agent 工作台',
      'miemie.subIdle': '空闲 · 等待任务',
      'miemie.moodIdle': '空闲',
      'miemie.permAuto': '权限·自动',
      'miemie.tabChat': '对话',
      'miemie.tabFlow': '任务流',
      'miemie.emptyChatTitle': '和咩咩聊聊',
      'miemie.emptyChatDesc': '聊天、提问、闲聊都在这里。发任务时自动转到任务流。',
      'miemie.emptyFlowTitle': '任务流',
      'miemie.emptyFlowDesc': '咩咩执行任务的每一步都会显示在这里，高风险操作会弹确认卡。',
      'miemie.quickAnalyze': '分析',
      'miemie.quickSearch': '搜索',
      'miemie.quickMemory': '记忆',
      'miemie.quickPlan': '规划',
      'miemie.quickDb': '数据库',
      'miemie.quickPersona': '人格分身',
      'miemie.chipAnalyze': '分析项目',
      'miemie.chipSearch': '搜索代码',
      'miemie.chipMemory': '查记忆',
      'miemie.chipPlan': '规划任务',
      'miemie.chipDb': '查数据库',
      'miemie.inputPlaceholder': '输入任务、聊天或 / 指令…',
      'miemie.permTip': '权限模式',
      'miemie.styleTip': '形象：像素',
      'miemie.collapseTip': '收起',
      'miemie.avatarTip': '点我互动',
      'miemie.sendTip': '发送',
      'miemie.clearFlowTip': '清空任务流',
      'miemie.serviceTip': '打开服务主页',

      // ── 历史会话侧边栏 ──
      'history.title': '历史会话',
      'history.search': '搜索历史消息...',
      'history.loading': '加载中...',
      'history.toggle': '历史会话',

      // ── 工作表 / Plan / Worktree ──
      'todo.title': '工作表',
      'todo.count': '0 项',
      'todo.tasks': '任务列表',
      'todo.files': '文件列表',
      'todo.clearCompleted': '清除已完成',
      'todo.add': '＋ 添加任务',
      'todo.close': '关闭',
      'plan.title': 'Plan 规划模式',
      'plan.clear': '清空',
      'plan.execute': '执行规划',
      'worktree.title': 'Worktree 隔离区',
      'worktree.count': '0 个',
      'worktree.taskPlaceholder': '输入任务描述，创建隔离分支... (Enter 创建)',
      'worktree.create': '＋ 创建',
      'worktree.autoMerge': '自动合并回主',
      'worktree.keep': '保留供审阅',
      'worktree.refresh': '刷新',
      'worktree.actor': '⛓ Worktree Actor',
      'worktree.hint': 'Agent 在隔离分支工作，主工作区零污染',

      // ── 模型选择 / 会话管理 ──
      'model.title': '模型选择',
      'model.ollama': 'Ollama 本地',
      'model.deepseek': 'DeepSeek 云端',
      'model.miemie': 'MIEMIE 咩咩',
      'model.switch': '切换模型',
      'session.title': '会话管理',
      'session.new': '+ 新建会话',
      'session.cancel': '取消',
      'session.current': '会话: 默认',

      // ── 设置 ──
      'settings.panelTitle': '设置',
      'settings.tabGeneral': '通用',
      'settings.tabAi': 'AI',
      'settings.tabAppearance': '外观',
      'settings.tabVisualization': '可视化',
      'settings.tabShortcuts': '快捷键',
      'settings.tabSkin': '皮肤',
      'settings.tabAgent': 'Agent',
      'settings.tabPlugin': '插件',
      'settings.tabApikey': '密钥',
      'settings.tabAbout': '关于',
      'settings.lang': '语言',
      'settings.langZh': '中文',
      'settings.langEn': 'English',
      'settings.langDesc': '界面显示语言',
      'settings.reopenLast': '启动时打开上次会话',
      'settings.reopenDesc': '自动恢复上次的对话',

      // ── 搜索 / 快捷键 ──
      'search.placeholder': '搜索消息内容...',
      'search.empty': '输入关键词开始搜索...',
      'search.session': '会话:',
      'search.type': '类型:',
      'search.allSessions': '全部会话',
      'search.allTypes': '全部',
      'search.userMsg': '用户消息',
      'search.aiReply': 'AI回复',
      'shortcuts.title': '快捷键参考',

      // ── 配置 / 权限 ──
      'config.title': '配置选项',
      'config.desc': '请选择以下配置项',
      'config.cancel': '取消',
      'config.confirm': '确认',
      'perm.title': '权限请求',
      'perm.tool': '工具: {tool}',
      'perm.desc': 'Lemon Code 请求执行操作',
      'perm.toolShort': '工具: ',
      'perm.descDefault': 'Lemon Code 请求执行操作',

      // ── 会话管理动态 ──
      'session.modelLabel': '模型: {model}',
      'session.autoBtn': '自动',
      'session.newDialogTitle': '新建会话',
      'session.newDialogInput': '输入新会话名称：',
      'session.renameDialogTitle': '重命名会话',
      'session.renameDialogInput': '输入新会话名称：',
      'session.deleteDialogTitle': '删除会话',
      'session.deleteDialogMsg': '确认删除此会话？此操作不可恢复！',
      'session.addTaskTitle': '添加任务',
      'session.addTaskInput': '输入任务标题:',
      'session.exportTitle': '导出对话',
      'session.exportDesc': '输入导出文件名：',
      'session.defaultName': '默认',
      'session.renamedToast': '已重命名',

      // ── 弹窗 ──
      'mode.switchTitle': '切换工作模式',
      'mode.cancelEsc': '取消 (Esc)',
      'cmd.title': '可用命令',
      'planArea.title': '执行计划',
      'snapshot.title': '↩ 代码回退确认',
      'snapshot.loading': '加载中...',
      'snapshot.cancel': '取消',
      'snapshot.confirm': '确认回退',
      'confirm.title': '确认操作',
      'confirm.message': '确定要执行此操作吗？',
      'confirm.cancel': '取消',
      'confirm.ok': '确认',
      'input.title': '请输入',
      'input.cancel': '取消',
      'input.ok': '确定',

      // ── 状态栏 ──
      'status.engineLabel': '当前引擎',
      'status.memLabel': 'JS堆内存',
      'status.fpsLabel': '渲染帧率',
      'status.engine': '引擎: Auto',
      'status.mem': '内存: --MB',
      'status.fps': 'FPS: --',

      // ── 机器人 ──
      'robot.chatTitle': '柠檬助手',
      'robot.inputPlaceholder': '和柠檬小助手说点什么...',
      'robot.send': '发送',
      'robot.tip': '左键互动 · 右键聊天'
    },
    en: {
      // Input area
      'input.placeholder': 'Type a message... (Enter to send)',
      'input.send': 'LEMON',
      'input.upload': 'Upload image',
      'input.attach': 'Attach file',
      
      // Mode row
      'mode.build': 'Build',
      'mode.switch': 'Tab to switch',
      'mode.settings': 'Ctrl+P Settings',
      
      // Status bar
      'status.engine': 'Engine',
      'status.memory': 'JS Heap',
      'status.fps': 'FPS',
      'status.search': 'Search messages (Ctrl+F)',
      'status.export': 'Export chat (Ctrl+E)',
      'status.shortcuts': 'Shortcuts (Ctrl+/)',
      
      // Debug panel
      'debug.title': 'Debug',
      'debug.start': 'Start',
      'debug.continue': 'Continue',
      'debug.pause': 'Pause',
      'debug.stop': 'Stop',
      'debug.stepOver': 'Step Over',
      'debug.stepInto': 'Step Into',
      'debug.stepOut': 'Step Out',
      'debug.variables': 'Variables',
      'debug.stack': 'Call Stack',
      'debug.breakpoints': 'Breakpoints',
      'debug.watch': 'Watch',
      'debug.output': 'Output',
      'debug.localVars': 'Local Variables',
      'debug.globalVars': 'Global Variables',
      'debug.noSession': 'No debug session',
      'debug.noStack': 'No call stack info',
      'debug.noBreakpoints': 'No breakpoints',
      'debug.watchPlaceholder': 'Enter expression and press Enter to add watch...',
      
      // Plugin market
      'plugin.title': 'Plugin Market',
      'plugin.search': 'Search plugins...',
      'plugin.market': 'Market',
      'plugin.installed': 'Installed',
      'plugin.config': 'Config',
      'plugin.loading': 'Loading...',
      
      // Settings panel
      'settings.title': 'Settings',
      'settings.general': 'General',
      'settings.ai': 'AI',
      'settings.appearance': 'Appearance',
      'settings.visualization': 'Visualization',
      'settings.shortcuts': 'Shortcuts',
      'settings.skin': 'Skin',
      'settings.agent': 'Agent',
      'settings.apikey': 'API Key',
      'settings.about': 'About',
      'settings.language': 'Language',
      'settings.languageDesc': 'Interface display language',
      'settings.reopenLast': 'Reopen last session on startup',
      'settings.reopenDesc': 'Automatically restore last conversation',
      'settings.sandbox': 'Sandbox Mode',
      'settings.sandboxDesc': 'Code execution security level',
      'settings.sandboxTrust': 'Trust mode (no confirmation)',
      'settings.sandboxManual': 'Manual confirmation (dangerous languages require confirmation)',
      'settings.sandboxStrict': 'Strict mode (forbid dangerous languages)',
      'settings.sandboxHint': '<strong>Trust mode:</strong> All code executes automatically<br><strong>Manual confirmation:</strong> C/C++/Bash and other dangerous languages require confirmation<br><strong>Strict mode:</strong> Forbid compiled/system languages',
      'settings.execLanguages': 'Supported execution languages',
      'settings.execDesc': 'Can run in code blocks',
      'settings.aiModel': 'AI Model',
      'settings.aiModelDesc': 'Select AI backend service',
      'settings.temperature': 'Temperature',
      'settings.temperatureDesc': '0=Precise, 1=Creative, default 0.7',
      'settings.maxTokens': 'Max Tokens',
      'settings.maxTokensDesc': 'Maximum length of AI response',
      'settings.agentMode': 'Agent Mode',
      'settings.agentModeDesc': 'Select engine and identity for Agent',
      'settings.agentIdentity': 'Agent Identity',
      'settings.agentIdentityDesc': 'Lemon Agent = Local AI / MIMO Agent = Take over MIMO Code',
      'settings.agentAuto': 'Auto select',
      'settings.agentLemon': 'Lemon Agent (Local)',
      'settings.agentMimo': 'MIMO Agent (Take over)',
      'settings.agentIdentityHint': '<strong>Lemon Agent:</strong> Driven by local Ollama or DeepSeek API, fully autonomous, no dependency on MIMO Code.<br><strong>MIMO Agent:</strong> Take over MIMO Code window via Process Bridge, share its AI capabilities and file system.',
      'settings.computeEngine': 'Compute Engine',
      'settings.computeEngineDesc': 'Select backend engine for AI inference',
      'settings.defaultEngine': 'Default Engine',
      'settings.defaultEngineDesc': 'Engine used for new conversations',
      'settings.apiKeyConfig': 'API Key Configuration',
      
      // Session panel
      'session.search': 'Search history...',
      'session.settings': 'Settings (Ctrl+,)',
      
      // Search panel
      'search.placeholder': 'Search message content...',
      'search.empty': 'Enter keywords to start searching...',
      
      // Common
      'common.send': 'Send',
      'common.confirm': 'Confirm',
      'common.cancel': 'Cancel',

      // ── Workspace / Session ──
      'ws.title': 'Workspaces',
      'ws.add': '+ Add Workspace',
      'ws.pathPlaceholder': 'Project path (e.g. D:\\projects\\my_app)',
      'ws.namePlaceholder': 'Display name (optional)',
      'ws.cancel': 'Cancel',
      'ws.confirmAdd': 'Add',
      'ws.switch': 'Switch workspace...',
      'ws.loading': 'Loading...',
      'ws.refresh': 'Refresh workspace',
      'ws.openInExplorer': 'Open in Explorer',
      'session.label': 'Session: Default',
      'session.model': 'Model: Auto',
      'session.switchHint': 'Switch model → engine selector',

      // ── Input / Mode row ──
      'input.placeholderFull': 'Type a message... (Enter send / Shift+Enter newline)',
      'mode.engineChip': 'Click to select AI engine / model',
      'mode.engineStatus': 'Lemon Code',
      'mode.modelAuto': 'Model: Auto',
      'mode.hintTab': 'Switch',
      'mode.hintSettings': 'Settings',
      'mode.desc.agent': 'Full AI coding assistant mode',
      'mode.desc.code': 'Code generation & editing mode',
      'mode.desc.edit': 'Quickly edit existing code',
      'mode.desc.architect': 'Architecture design & planning',
      'mode.desc.ask': 'Q&A and knowledge queries',

      // ── Miemie panel ──
      'miemie.panelTitle': 'MIEMIE · Agent Workbench',
      'miemie.subIdle': 'Idle · Waiting for tasks',
      'miemie.moodIdle': 'Idle',
      'miemie.permAuto': 'Perm·Auto',
      'miemie.tabChat': 'Chat',
      'miemie.tabFlow': 'Task Flow',
      'miemie.emptyChatTitle': 'Chat with Miemie',
      'miemie.emptyChatDesc': 'Chat, ask questions here. Tasks auto-switch to Task Flow.',
      'miemie.emptyFlowTitle': 'Task Flow',
      'miemie.emptyFlowDesc': 'Every step Miemie takes shows here; high-risk actions show a confirm card.',
      'miemie.quickAnalyze': 'Analyze',
      'miemie.quickSearch': 'Search',
      'miemie.quickMemory': 'Memory',
      'miemie.quickPlan': 'Plan',
      'miemie.quickDb': 'Database',
      'miemie.quickPersona': 'Persona',
      'miemie.chipAnalyze': 'Analyze project',
      'miemie.chipSearch': 'Search code',
      'miemie.chipMemory': 'Memory',
      'miemie.chipPlan': 'Plan task',
      'miemie.chipDb': 'Query DB',
      'miemie.inputPlaceholder': 'Type a task, chat, or / command…',
      'miemie.permTip': 'Permission mode',
      'miemie.styleTip': 'Style: Pixel',
      'miemie.collapseTip': 'Collapse',
      'miemie.avatarTip': 'Click to interact',
      'miemie.sendTip': 'Send',
      'miemie.clearFlowTip': 'Clear task flow',
      'miemie.serviceTip': 'Open service page',

      // ── History sidebar ──
      'history.title': 'History Sessions',
      'history.search': 'Search history...',
      'history.loading': 'Loading...',
      'history.toggle': 'History sessions',

      // ── Todo / Plan / Worktree ──
      'todo.title': 'Work Sheet',
      'todo.count': '0 items',
      'todo.tasks': 'Tasks',
      'todo.files': 'Files',
      'todo.clearCompleted': 'Clear completed',
      'todo.add': '+ Add Task',
      'todo.close': 'Close',
      'plan.title': 'Plan Mode',
      'plan.clear': 'Clear',
      'plan.execute': 'Execute Plan',
      'worktree.title': 'Worktree Sandbox',
      'worktree.count': '0 items',
      'worktree.taskPlaceholder': 'Describe task to create isolated branch... (Enter create)',
      'worktree.create': '+ Create',
      'worktree.autoMerge': 'Auto-merge to main',
      'worktree.keep': 'Keep for review',
      'worktree.refresh': 'Refresh',
      'worktree.actor': '⛓ Worktree Actor',
      'worktree.hint': 'Agent works in isolated branch; main workspace stays clean',

      // ── Model / Session ──
      'model.title': 'Select Model',
      'model.ollama': 'Ollama Local',
      'model.deepseek': 'DeepSeek Cloud',
      'model.miemie': 'MIEMIE',
      'model.switch': 'Switch Model',
      'session.title': 'Session Manager',
      'session.new': '+ New Session',
      'session.cancel': 'Cancel',
      'session.current': 'Session: Default',

      // ── Settings ──
      'settings.panelTitle': 'Settings',
      'settings.tabGeneral': 'General',
      'settings.tabAi': 'AI',
      'settings.tabAppearance': 'Appearance',
      'settings.tabVisualization': 'Visualization',
      'settings.tabShortcuts': 'Shortcuts',
      'settings.tabSkin': 'Skin',
      'settings.tabAgent': 'Agent',
      'settings.tabApikey': 'API Key',
      'settings.tabAbout': 'About',
      'settings.lang': 'Language',
      'settings.langZh': '中文',
      'settings.langEn': 'English',
      'settings.langDesc': 'Interface display language',
      'settings.reopenLast': 'Reopen last session on startup',
      'settings.reopenDesc': 'Automatically restore last conversation',

      // ── Search / Shortcuts ──
      'search.placeholder': 'Search message content...',
      'search.empty': 'Enter keywords to start searching...',
      'search.session': 'Session:',
      'search.type': 'Type:',
      'search.allSessions': 'All sessions',
      'search.allTypes': 'All',
      'search.userMsg': 'User messages',
      'search.aiReply': 'AI replies',
      'shortcuts.title': 'Keyboard Shortcuts',

      // ── Config / Permission ──
      'config.title': 'Configuration Options',
      'config.desc': 'Please select an option',
      'config.cancel': 'Cancel',
      'config.confirm': 'Confirm',
      'perm.title': 'Permission Request',
      'perm.tool': 'Tool: {tool}',
      'perm.desc': 'Lemon Code requests to execute an operation',
      'perm.toolShort': 'Tool: ',
      'perm.descDefault': 'Lemon Code requests to execute an operation',

      // ── Session management dynamic ──
      'session.modelLabel': 'Model: {model}',
      'session.autoBtn': 'Auto',
      'session.newDialogTitle': 'New Session',
      'session.newDialogInput': 'Enter new session name:',
      'session.renameDialogTitle': 'Rename Session',
      'session.renameDialogInput': 'Enter new session name:',
      'session.deleteDialogTitle': 'Delete Session',
      'session.deleteDialogMsg': 'Delete this session? This cannot be undone!',
      'session.addTaskTitle': 'Add Task',
      'session.addTaskInput': 'Enter task title:',
      'session.exportTitle': 'Export Chat',
      'session.exportDesc': 'Enter export filename:',
      'session.defaultName': 'Default',
      'session.renamedToast': 'Renamed',

      // ── Dialogs ──
      'mode.switchTitle': 'Switch Working Mode',
      'mode.cancelEsc': 'Cancel (Esc)',
      'cmd.title': 'Available Commands',
      'planArea.title': 'Execution Plan',
      'snapshot.title': '↩ Confirm Code Revert',
      'snapshot.loading': 'Loading...',
      'snapshot.cancel': 'Cancel',
      'snapshot.confirm': 'Confirm Revert',
      'confirm.title': 'Confirm Action',
      'confirm.message': 'Are you sure you want to do this?',
      'confirm.cancel': 'Cancel',
      'confirm.ok': 'Confirm',
      'input.title': 'Please Input',
      'input.cancel': 'Cancel',
      'input.ok': 'OK',

      // ── Status bar ──
      'status.engineLabel': 'Current engine',
      'status.memLabel': 'JS heap memory',
      'status.fpsLabel': 'Render FPS',
      'status.engine': 'Engine: Auto',
      'status.mem': 'Mem: --MB',
      'status.fps': 'FPS: --',

      // ── Robot ──
      'robot.chatTitle': 'Lemon Assistant',
      'robot.inputPlaceholder': 'Say something to Lemon Assistant...',
      'robot.send': 'Send',
      'robot.tip': 'Left-click interact · Right-click chat'
    }
  },
  
  // 获取翻译文本
  t: function(key, params) {
    var text = this.translations[this.currentLang][key] || key;
    if (params) {
      Object.keys(params).forEach(function(paramKey) {
        text = text.replace('{' + paramKey + '}', params[paramKey]);
      });
    }
    return text;
  },
  
  // 切换语言
  setLanguage: function(lang) {
    if (lang !== 'zh' && lang !== 'en') return;
    this.currentLang = lang;
    localStorage.setItem('lemon_lang', lang);
    this.applyTranslations();
    console.log('[i18n] Language switched to:', lang);
  },
  
  // ★ 安全文本替换：只修改第一个文本节点，不破坏子元素和事件监听器
  _safeSetText: function(el, text) {
    if (!el) return;
    // 找到第一个文本节点并修改
    for (var i = 0; i < el.childNodes.length; i++) {
      if (el.childNodes[i].nodeType === 3) { // TEXT_NODE
        el.childNodes[i].nodeValue = text;
        return;
      }
    }
    // 没有文本节点，在开头插入一个
    el.insertBefore(document.createTextNode(text), el.firstChild);
  },
  
  // 应用翻译到 DOM（安全模式：不破坏 DOM 结构和事件）
  applyTranslations: function() {
    try {
      // 输入框 placeholder
      var inputField = document.getElementById('inputField');
      if (inputField) inputField.placeholder = this.t('input.placeholder');
      
      // 模式行提示（hint 元素只含文本，安全替换）
      var modeHints = document.querySelectorAll('.mode-row .hint');
      if (modeHints.length >= 2) {
        modeHints[0].innerHTML = '<kbd>Tab</kbd> ' + this.t('mode.switch');
        modeHints[1].innerHTML = '<kbd>Ctrl+P</kbd> ' + this.t('mode.settings');
      }
      
      // 状态栏（只改 title 属性，安全）
      var statusBtns = document.querySelectorAll('.status-btn');
      if (statusBtns.length >= 3) {
        statusBtns[0].title = this.t('status.search');
        statusBtns[1].title = this.t('status.export');
        statusBtns[2].title = this.t('status.shortcuts');
      }
      
      // 调试面板标题（toolbar-title 只含文本+emoji，安全）
      var debugTitle = document.querySelector('.debug-toolbar-title');
      if (debugTitle) this._safeSetText(debugTitle, this.t('debug.title'));
      
      // 调试按钮（只改 title 属性，安全）
      var debugBtns = document.querySelectorAll('.debug-btn');
      if (debugBtns.length >= 7) {
        debugBtns[0].title = this.t('debug.start');
        debugBtns[1].title = this.t('debug.continue');
        debugBtns[2].title = this.t('debug.pause');
        debugBtns[3].title = this.t('debug.stop');
        debugBtns[4].title = this.t('debug.stepOver');
        debugBtns[5].title = this.t('debug.stepInto');
        debugBtns[6].title = this.t('debug.stepOut');
      }
      
      // 调试标签页 — 只替换第一个文本节点，保留 badge 子元素
      var debugTabs = document.querySelectorAll('.debug-tab');
      var debugLabels = [
        this.t('debug.variables'),
        this.t('debug.stack'),
        this.t('debug.breakpoints'),
        this.t('debug.watch'),
        this.t('debug.output')
      ];
      for (var i = 0; i < Math.min(debugTabs.length, debugLabels.length); i++) {
        this._safeSetText(debugTabs[i], debugLabels[i]);
      }
      
      // 调试变量组标题
      var debugVarHeaders = document.querySelectorAll('.debug-var-group-header');
      if (debugVarHeaders.length >= 2) {
        this._safeSetText(debugVarHeaders[0], this.t('debug.localVars'));
        this._safeSetText(debugVarHeaders[1], this.t('debug.globalVars'));
      }
      
      // 调试空状态
      var debugEmpty = document.querySelectorAll('.debug-empty');
      var emptyTexts = [this.t('debug.noSession'), this.t('debug.noSession'), this.t('debug.noStack'), this.t('debug.noBreakpoints')];
      for (var j = 0; j < Math.min(debugEmpty.length, emptyTexts.length); j++) {
        this._safeSetText(debugEmpty[j], emptyTexts[j]);
      }
      
      // 监视输入框
      var watchInput = document.getElementById('debugWatchInput');
      if (watchInput) watchInput.placeholder = this.t('debug.watchPlaceholder');
      
      // 插件市场标题
      var pluginTitle = document.querySelector('.plugin-toolbar-title');
      if (pluginTitle) this._safeSetText(pluginTitle, this.t('plugin.title'));
      
      // 插件搜索框
      var pluginSearch = document.getElementById('pluginSearchInput');
      if (pluginSearch) pluginSearch.placeholder = this.t('plugin.search');
      
      // 插件标签页 — 只替换第一个文本节点，保留 badge 子元素
      var pluginTabs = document.querySelectorAll('.plugin-tab');
      var pluginLabels = [this.t('plugin.market'), this.t('plugin.installed'), this.t('plugin.config')];
      for (var k = 0; k < Math.min(pluginTabs.length, pluginLabels.length); k++) {
        this._safeSetText(pluginTabs[k], pluginLabels[k]);
      }
      
      // 插件空状态
      var pluginEmpty = document.querySelector('.plugin-empty');
      if (pluginEmpty) this._safeSetText(pluginEmpty, this.t('plugin.loading'));
      
      // 设置面板标题 — 只替换文本节点，保留 SVG 图标
      var settingsTitle = document.querySelector('.settings-title');
      if (settingsTitle) this._safeSetText(settingsTitle, ' ' + this.t('settings.title'));
      
      // 设置标签页 — 只替换第一个文本节点，保留 emoji
      var settingsTabs = document.querySelectorAll('.settings-tab');
      var settingsLabels = [
        this.t('settings.general'),
        this.t('settings.ai'),
        this.t('settings.appearance'),
        this.t('settings.visualization'),
        this.t('settings.shortcuts'),
        this.t('settings.skin'),
        this.t('settings.agent'),
        this.t('settings.apikey'),
        this.t('settings.about')
      ];
      for (var m = 0; m < Math.min(settingsTabs.length, settingsLabels.length); m++) {
        this._safeSetText(settingsTabs[m], settingsLabels[m]);
      }
      
      // 通用设置标签 — 只替换第一个文本节点，保留 .setting-desc 子元素
      var settingLabels = document.querySelectorAll('.setting-label');
      if (settingLabels.length >= 2) {
        this._safeSetText(settingLabels[0], this.t('settings.language'));
        // 更新 desc 子元素
        var desc0 = settingLabels[0].querySelector('.setting-desc');
        if (desc0) desc0.textContent = this.t('settings.languageDesc');
        
        this._safeSetText(settingLabels[1], this.t('settings.reopenLast'));
        var desc1 = settingLabels[1].querySelector('.setting-desc');
        if (desc1) desc1.textContent = this.t('settings.reopenDesc');
      }
      
      // 搜索面板
      var searchInput = document.getElementById('searchInput');
      if (searchInput) searchInput.placeholder = this.t('search.placeholder');
      
      var searchEmpty = document.querySelector('.search-empty');
      if (searchEmpty) this._safeSetText(searchEmpty, this.t('search.empty'));
      
      // 发送按钮
      var sendBtn = document.getElementById('sendBtn');
      if (sendBtn) this._safeSetText(sendBtn, this.t('input.send'));

      // ★ 数据驱动：遍历 [data-i18n] 元素批量替换（placeholder/title/text）
      // 由 mimo_page.html 中 data-i18n="key" 声明，避免每个元素手写映射
      var elList = document.querySelectorAll('[data-i18n]');
      for (var di = 0; di < elList.length; di++) {
        var el = elList[di];
        var key = el.getAttribute('data-i18n');
        if (!key) continue;
        var text = this.t(key);
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
          el.placeholder = text;
        } else if (el.hasAttribute('data-i18n-title')) {
          el.title = text;
        } else {
          this._safeSetText(el, text);
        }
      }
      // ★ 数据驱动：title 属性（[data-i18n-title]）
      var tElList = document.querySelectorAll('[data-i18n-title]');
      for (var tj = 0; tj < tElList.length; tj++) {
        var tEl = tElList[tj];
        var tKey = tEl.getAttribute('data-i18n-title');
        if (tKey) tEl.title = this.t(tKey);
      }
      
      console.log('[i18n] Translations applied to DOM (safe mode)');
    } catch(e) {
      console.error('[i18n] applyTranslations error:', e);
    }
  },
  
  // 初始化
  init: function() {
    // 从 localStorage 读取语言设置
    var savedLang = localStorage.getItem('lemon_lang');
    if (savedLang && (savedLang === 'zh' || savedLang === 'en')) {
      this.currentLang = savedLang;
    } else {
      // 检测浏览器语言
      var browserLang = navigator.language || navigator.userLanguage;
      this.currentLang = browserLang && browserLang.startsWith('zh') ? 'zh' : 'en';
    }
    
    // 应用翻译
    this.applyTranslations();
    
    // 绑定语言选择器事件
    var langSelect = document.getElementById('set-language');
    if (langSelect) {
      langSelect.value = this.currentLang;
      langSelect.addEventListener('change', function() {
        i18n.setLanguage(this.value);
      });
    }
    
    console.log('[i18n] Initialized with language:', this.currentLang);
  }
};

// 页面加载完成后延迟初始化 i18n（避免阻塞 DOM 渲染和事件绑定）
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function() { setTimeout(function() { i18n.init(); }, 500); });
} else {
  setTimeout(function() { i18n.init(); }, 500);
}

// ============================================================
// ★ ThemeManager — 节日主题管理器
// ============================================================
var ThemeManager = {
  currentTheme: 'default',
  effectsEnabled: true,
  starfieldEnabled: true,
  robotThemeEnabled: true,
  autoFestival: false,
  effectInterval: null,

  // ★ v4.1.30 主题配置：仅保留三个核心壁纸主题
  // 节日主题（christmas/halloween/cny/newyear/valentine/easter/national/space）
  // 因其本身的渲染/层叠有遗留问题，用户要求先封存；需要重做后再恢复。
  // 已验证稳定的主题：default（星空+流星）、ocean（海洋）、focus_moment（专注时刻）。
  themes: {
    'default':      { name: '默认',     accent: '#ff6900', effect: null },
    'ocean':        { name: '海洋',     accent: '#0ea5e9', effect: null, hasOceanWallpaper: true },
    'focus_moment': { name: '专注时刻', accent: '#ff6900', effect: 'warm', hasWallpaper: true, wallpaperPath: 'data/lemon_wallpaper.png' }
    /* ★ v4.1.30 封存：
    'christmas': { name: '圣诞节', accent: '#c41e3a', effect: 'snow' },
    'halloween': { name: '万圣节', accent: '#ff6b00', effect: 'pumpkin' },
    'cny': { name: '春节', accent: '#dc2626', effect: 'firework' },
    'newyear': { name: '新年', accent: '#0ea5e9', effect: 'firework' },
    'valentine': { name: '情人节', accent: '#ec4899', effect: 'heart' },
    'easter': { name: '复活节', accent: '#22c55e', effect: 'leaf' },
    'national': { name: '国庆', accent: '#dc2626', effect: 'firework' },
    'space': { name: '星空', accent: '#8b5cf6', effect: 'star' }
    */
  },

  // 应用主题
  apply: function(themeId) {
    this.currentTheme = themeId;
    document.documentElement.setAttribute('data-festival', themeId);

    // ★ 只更新节日主题卡片（#themeGrid内的），不影响主主题卡片
    var grid = document.getElementById('themeGrid');
    if (grid) {
      grid.querySelectorAll('.theme-card').forEach(function(card) {
        card.classList.toggle('selected', card.dataset.theme === themeId);
      });
    }

    // 保存到localStorage
    localStorage.setItem('festivalTheme', themeId);

    // ★ 渲染节日装饰
    this.renderDecorations(themeId);

    // ★ 显示节日祝福语横幅
    this.showBlessing(themeId);

    // 触发特效
    if (this.effectsEnabled) {
      var eff = this.themes[themeId] ? this.themes[themeId].effect : null;
      this.startEffect(eff);
    }

    // 更新小机器人颜色
    if (this.robotThemeEnabled) {
      this.updateRobot(themeId);
    }

    // 更新星空背景
    if (this.starfieldEnabled) {
      this.updateStarfield(themeId);
    }

    // ★ v4.8.1 星空安全网：default 主题强制确保 starfield 动画运行
    if (themeId === 'default') {
      setTimeout(function() {
        if (typeof initStarfield === 'function') {
          initStarfield();
        }
      }, 100);
    }

    // 更新海洋壁纸
    this.updateOceanWallpaper(themeId);

    // ★ v12.10 REBUILD: 主题切换后强制重排 — 防止 CSS 变量变化导致 flex 容器塌陷
    if (typeof window.fixBodyHeight === 'function') {
      requestAnimationFrame(function() {
        window.fixBodyHeight();
        var c = document.getElementById('content');
        if (c) {
          var h = c.getBoundingClientRect().height;
          if (h < 50) {
            // 布局塌陷：强制重建 #content 高度
            c.style.transition = 'none';
            c.style.height = '1px';
            void c.offsetHeight;
            c.style.height = '';
            window.fixBodyHeight();
            c.style.transition = '';
          }
        }
      });
    }

    console.log('[ThemeManager] 应用主题:', themeId);
  },

  // ★ 渲染节日装饰（顶部Logo两侧）
  renderDecorations: function(themeId) {
    var decorations = this.getDecorations(themeId);
    var leftContainer = document.getElementById('festivalDecoLeft');
    var rightContainer = document.getElementById('festivalDecoRight');

    if (!leftContainer || !rightContainer) return;

    // 清空现有装饰
    leftContainer.innerHTML = '';
    rightContainer.innerHTML = '';

    if (!decorations || decorations.length === 0) {
      leftContainer.classList.remove('visible');
      rightContainer.classList.remove('visible');
      return;
    }

    // 随机选择两个不同的装饰
    var indices = this._getRandomIndices(decorations.length, 2);
    if (indices.length >= 1) {
      leftContainer.innerHTML = decorations[indices[0]];
      leftContainer.classList.add('visible');
    }
    if (indices.length >= 2) {
      rightContainer.innerHTML = decorations[indices[1]];
      rightContainer.classList.add('visible');
    }
  },

  // 获取节日装饰SVG
  getDecorations: function(themeId) {
    var decoMap = {
      'christmas': [
        '<svg viewBox="0 0 40 50" fill="none"><polygon points="20,2 38,35 2,35" fill="#22c55e" stroke="#fff" stroke-width="1"/><circle cx="20" cy="8" r="3" fill="#ffd700"/><circle cx="14" cy="18" r="2" fill="#c41e3a"/><circle cx="26" cy="18" r="2" fill="#c41e3a"/></svg>',
        '<svg viewBox="0 0 30 30" fill="none"><rect x="3" y="10" width="24" height="17" rx="2" fill="#c41e3a" stroke="#fff" stroke-width="1"/><line x1="15" y1="10" x2="15" y2="27" stroke="#ffd700" stroke-width="3"/></svg>',
        '<svg viewBox="0 0 24 24" fill="none"><line x1="12" y1="2" x2="12" y2="22" stroke="#fff" stroke-width="1.5"/><line x1="2" y1="12" x2="22" y2="12" stroke="#fff" stroke-width="1.5"/><line x1="5" y1="5" x2="19" y2="19" stroke="#fff" stroke-width="1.5"/></svg>',
        '<svg viewBox="0 0 24 32" fill="none"><path d="M12 2 Q4 8 4 16 L4 20 L20 20 L20 16 Q20 8 12 2 Z" fill="#ffd700" stroke="#fff" stroke-width="1"/></svg>'
      ],
      'halloween': [
        '<svg viewBox="0 0 32 32" fill="none"><ellipse cx="16" cy="18" rx="14" ry="12" fill="#ff6b00"/><polygon points="10,14 8,16 10,18" fill="#ffd700"/><polygon points="22,14 24,16 22,18" fill="#ffd700"/><path d="M10 22 Q16 26 22 22" fill="#ffd700"/></svg>',
        '<svg viewBox="0 0 28 36" fill="none"><path d="M14 2 Q2 6 2 18 L2 32 L6 28 L10 32 L14 28 L18 32 L22 28 L26 32 L26 18 Q26 6 14 2 Z" fill="#fff" fill-opacity="0.9" stroke="#9333ea" stroke-width="1"/><circle cx="10" cy="14" r="2" fill="#000"/><circle cx="18" cy="14" r="2" fill="#000"/></svg>',
        '<svg viewBox="0 0 32 20" fill="none"><path d="M16 10 L10 4 L2 2 L8 10 L2 18 L10 12 L16 16 L22 12 L30 18 L24 10 L30 2 L22 4 L16 10 Z" fill="#000" stroke="#9333ea"/></svg>'
      ],
      'cny': [
        '<svg viewBox="0 0 32 48" fill="none"><rect x="12" y="2" width="8" height="4" fill="#ffd700"/><ellipse cx="16" cy="24" rx="14" ry="16" fill="#dc2626" stroke="#ffd700" stroke-width="1"/><rect x="6" y="20" width="20" height="3" fill="#ffd700"/></svg>',
        '<svg viewBox="0 0 32 32" fill="none"><rect x="2" y="2" width="28" height="28" fill="#dc2626" stroke="#ffd700" stroke-width="2"/><text x="16" y="22" font-size="20" font-weight="bold" fill="#ffd700" text-anchor="middle">福</text></svg>',
        '<svg viewBox="0 0 20 40" fill="none"><rect x="6" y="8" width="8" height="28" fill="#dc2626" stroke="#ffd700" stroke-width="1"/><rect x="6" y="8" width="8" height="4" fill="#ffd700"/></svg>',
        '<svg viewBox="0 0 28 40" fill="none"><rect x="2" y="4" width="24" height="34" rx="3" fill="#dc2626" stroke="#ffd700" stroke-width="1"/><ellipse cx="14" cy="16" rx="8" ry="6" fill="#ffd700"/></svg>'
      ],
      'newyear': [
        '<svg viewBox="0 0 40 40" fill="none"><circle cx="20" cy="20" r="3" fill="#ffd700"/><line x1="20" y1="20" x2="20" y2="5" stroke="#0ea5e9" stroke-width="2"/><line x1="20" y1="20" x2="5" y2="20" stroke="#ff6b00" stroke-width="2"/><line x1="20" y1="20" x2="35" y2="20" stroke="#ff6b00" stroke-width="2"/><circle cx="20" cy="5" r="2" fill="#ffd700"/><circle cx="5" cy="20" r="2" fill="#ff6b00"/></svg>',
        '<svg viewBox="0 0 24 24" fill="none"><polygon points="12,2 15,9 22,9 17,14 19,21 12,17 5,21 7,14 2,9 9,9" fill="#ffd700" stroke="#0ea5e9" stroke-width="1"/></svg>',
        '<svg viewBox="0 0 32 36" fill="none"><polygon points="16,2 28,32 4,32" fill="#0ea5e9" stroke="#ffd700" stroke-width="1"/><circle cx="12" cy="14" r="2" fill="#ff6b00"/><circle cx="18" cy="10" r="2" fill="#22c55e"/></svg>'
      ],
      'valentine': [
        '<svg viewBox="0 0 32 28" fill="none"><path d="M16 26 Q2 16 2 8 Q2 2 8 2 Q12 2 16 8 Q20 2 24 2 Q30 2 30 8 Q30 16 16 26 Z" fill="#ec4899" stroke="#f472b6" stroke-width="1"/></svg>',
        '<svg viewBox="0 0 40 20" fill="none"><path d="M2 10 L30 10" stroke="#ec4899" stroke-width="2"/><polygon points="30,10 38,10 32,6 32,14" fill="#ec4899"/></svg>'
      ],
      'easter': [
        '<svg viewBox="0 0 28 36" fill="none"><ellipse cx="14" cy="20" rx="12" ry="14" fill="#22c55e"/><ellipse cx="14" cy="20" rx="8" ry="10" fill="#fde047"/><circle cx="10" cy="16" r="2" fill="#ec4899"/><circle cx="18" cy="18" r="2" fill="#0ea5e9"/></svg>',
        '<svg viewBox="0 0 32 36" fill="none"><ellipse cx="16" cy="24" rx="10" ry="10" fill="#fff" stroke="#fde047" stroke-width="1"/><ellipse cx="10" cy="8" rx="4" ry="10" fill="#fff" stroke="#fde047" stroke-width="1"/><ellipse cx="22" cy="8" rx="4" ry="10" fill="#fff" stroke="#fde047" stroke-width="1"/></svg>'
      ],
      'national': [
        '<svg viewBox="0 0 32 40" fill="none"><rect x="4" y="2" width="2" height="36" fill="#ffd700"/><rect x="6" y="2" width="22" height="16" fill="#dc2626"/><polygon points="10,6 10,14 18,10" fill="#ffd700"/></svg>',
        '<svg viewBox="0 0 40 40" fill="none"><circle cx="20" cy="20" r="4" fill="#dc2626"/><line x1="20" y1="20" x2="20" y2="4" stroke="#fcd34d" stroke-width="2"/><line x1="20" y1="20" x2="36" y2="20" stroke="#fcd34d" stroke-width="2"/><line x1="20" y1="20" x2="4" y2="20" stroke="#fcd34d" stroke-width="2"/></svg>'
      ],
      'space': [
        '<svg viewBox="0 0 24 24" fill="none"><polygon points="12,2 14,10 22,10 16,14 18,22 12,18 6,22 8,14 2,10 10,10" fill="#a78bfa" stroke="#e0e7ff" stroke-width="1"/></svg>',
        '<svg viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="10" fill="#8b5cf6"/><ellipse cx="16" cy="16" rx="14" ry="4" fill="none" stroke="#a78bfa" stroke-width="2"/></svg>',
        '<svg viewBox="0 0 20 40" fill="none"><path d="M10 2 Q4 8 4 20 L6 30 L14 30 L16 20 Q16 8 10 2 Z" fill="#e0e7ff"/><circle cx="10" cy="14" r="3" fill="#06b6d4"/></svg>'
      ],
      'focus_moment': []
    };
    return decoMap[themeId] || [];
  },

  // 显示节日祝福语
  showBlessing: function(themeId) {
    if (themeId === 'default') return;

    var blessings = {
      'christmas': ['圣诞快乐！愿您在这个温馨的节日里收获满满的幸福', 'Merry Christmas！愿圣诞老人为您带来惊喜与欢乐'],
      'halloween': ['万圣节快乐！不给糖就捣蛋！', 'Trick or Treat！愿您度过一个神秘的夜晚'],
      'cny': ['新春大吉！愿您在新的一年里万事如意', '恭喜发财！愿红包带来满满的好运'],
      'newyear': ['新年快乐！愿新的一年充满希望与美好', '新年新气象，愿梦想照进现实'],
      'valentine': ['情人节快乐！愿爱永远陪伴您', '爱在心中，情暖人间'],
      'easter': ['复活节快乐！愿新生带来希望', '寻找彩蛋，发现惊喜！'],
      'national': ['国庆快乐！愿祖国繁荣昌盛', '庆祝华诞，共祝祖国好'],
      'space': ['星空璀璨，愿您的梦想如星辰闪耀', '探索宇宙，发现无限可能'],
      'focus_moment': ['专注时刻，让每一个字符都有意义', '沉浸在创造的节奏里，打字即是冥想']
    };

    var texts = blessings[themeId];
    if (!texts || texts.length === 0) return;

    var text = texts[Math.floor(Math.random() * texts.length)];
    var banner = document.getElementById('festivalBanner');
    var bannerText = document.getElementById('festivalBannerText');

    if (banner && bannerText) {
      bannerText.textContent = text;
      banner.style.display = 'flex';

      // 8秒后自动隐藏
      setTimeout(function() {
        if (banner) banner.style.display = 'none';
      }, 8000);
    }
  },

  // 辅助函数：获取随机索引
  _getRandomIndices: function(max, count) {
    var indices = [];
    while (indices.length < count && indices.length < max) {
      var idx = Math.floor(Math.random() * max);
      if (indices.indexOf(idx) === -1) {
        indices.push(idx);
      }
    }
    return indices;
  },

  // 更新星空背景
  updateStarfield: function(themeId) {
    var canvas = document.getElementById('starfield');
    if (!canvas) return;
    if (themeId === 'ocean') {
      canvas.style.opacity = '0';
      return;
    }
    canvas.style.opacity = '1';
    if (canvas.width === 0 || canvas.height === 0) {
      if (typeof initStarfield === 'function') {
        initStarfield();
      }
    }
    if (typeof _starfieldRAF === 'undefined' || !_starfieldRAF) {
      if (typeof render === 'function') {
        _starfieldRAF = requestAnimationFrame(render);
      }
    }
  },

  // 更新海洋壁纸
  updateOceanWallpaper: function(themeId) {
    if (themeId === 'focus_moment') {
      _wallpaperTheme = 'focus_moment';
    } else if (themeId === 'ocean') {
      _wallpaperTheme = 'ocean';
    } else {
      _wallpaperTheme = 'starfield';
    }
    // ★ v4.8.1: 强制确保 typewriterfield 和 oceanfield 在非 focus_moment/ocean 主题下被完全隐藏
    if (themeId !== 'focus_moment' && themeId !== 'ocean') {
      try {
        var twf = document.getElementById('typewriterfield');
        if (twf) { twf.style.opacity = '0'; twf.style.display = 'none'; twf.src = 'about:blank'; }
        var ocf = document.getElementById('oceanfield');
        if (ocf) { ocf.style.opacity = '0'; ocf.style.display = 'none'; ocf.src = 'about:blank'; }
      } catch(e) {}
    }
    applyWallpaper();
  },

  // ★ 更新小机器人节日装饰
  updateRobot: function(themeId) {
    var robot = document.getElementById('robot');
    var decoLayer = document.getElementById('robotFestivalDeco');
    if (!robot || !decoLayer) return;

    var theme = this.themes[themeId];
    if (!theme) return;

    // 清空装饰层
    decoLayer.innerHTML = '';
    decoLayer.classList.remove('visible');

    // 设置data-festival属性用于CSS伪元素装饰
    robot.setAttribute('data-festival', themeId);

    if (themeId === 'default') {
      // 默认主题无装饰
      return;
    }

    // 根据节日添加不同的装饰SVG
    var decoSVGs = {
      'christmas': '<svg viewBox="0 0 40 20" fill="none"><rect x="5" y="2" width="30" height="16" rx="2" fill="#c41e3a" stroke="#fff" stroke-width="1"/><rect x="5" y="2" width="30" height="5" fill="#fff"/><circle cx="12" cy="12" r="3" fill="#22c55e"/><circle cx="28" cy="12" r="3" fill="#ffd700"/></svg>',
      'halloween': '<svg viewBox="0 0 32 28" fill="none"><ellipse cx="16" cy="16" rx="14" ry="10" fill="#ff6b00"/><polygon points="10,12 8,14 10,16" fill="#ffd700"/><polygon points="22,12 24,14 22,16" fill="#ffd700"/></svg>',
      'cny': '<svg viewBox="0 0 32 32" fill="none"><rect x="2" y="2" width="28" height="28" fill="#dc2626" stroke="#ffd700" stroke-width="2"/><text x="16" y="22" font-size="16" fill="#ffd700" text-anchor="middle">福</text></svg>',
      'newyear': '<svg viewBox="0 0 40 30" fill="none"><circle cx="20" cy="15" r="3" fill="#ffd700"/><line x1="20" y1="15" x2="20" y2="3" stroke="#0ea5e9" stroke-width="2"/><line x1="20" y1="15" x2="35" y2="15" stroke="#ff6b00" stroke-width="2"/><circle cx="20" cy="3" r="2" fill="#ffd700"/></svg>',
      'valentine': '<svg viewBox="0 0 28 24" fill="none"><path d="M14 22 Q2 14 2 8 Q2 2 8 2 Q12 2 14 8 Q16 2 20 2 Q26 2 26 8 Q26 14 14 22 Z" fill="#ec4899"/></svg>',
      'easter': '<svg viewBox="0 0 24 24" fill="none"><ellipse cx="12" cy="14" rx="10" ry="8" fill="#22c55e"/><ellipse cx="12" cy="14" rx="6" ry="5" fill="#fde047"/><circle cx="8" cy="12" r="2" fill="#ec4899"/></svg>',
      'national': '<svg viewBox="0 0 32 32" fill="none"><rect x="4" y="2" width="2" height="28" fill="#ffd700"/><rect x="6" y="2" width="20" height="14" fill="#dc2626"/><polygon points="10,6 10,12 14,9" fill="#ffd700"/></svg>',
      'space': '<svg viewBox="0 0 20 28" fill="none"><path d="M10 2 Q4 6 4 14 L6 22 L14 22 L16 14 Q16 6 10 2 Z" fill="#e0e7ff"/><circle cx="10" cy="10" r="3" fill="#8b5cf6"/></svg>',
      'focus_moment': '<svg viewBox="0 0 40 32" fill="none"><rect x="6" y="8" width="28" height="18" rx="3" fill="#ff6900" opacity="0.3"/><rect x="10" y="12" width="20" height="10" rx="2" fill="#ffd700"/><circle cx="16" cy="16" r="1.5" fill="#cc5400"/><circle cx="20" cy="16" r="1.5" fill="#cc5400"/><circle cx="24" cy="16" r="1.5" fill="#cc5400"/></svg>'
    };

    if (decoSVGs[themeId]) {
      decoLayer.innerHTML = decoSVGs[themeId];
      decoLayer.classList.add('visible');
    }

    // 更新机器人眼睛颜色
    var eyes = robot.querySelectorAll('.robot-eye');
    eyes.forEach(function(eye) {
      eye.style.background = theme.accent;
      eye.style.boxShadow = 'inset 0 0 3px rgba(255,255,255,0.3), 0 0 6px ' + theme.accent;
    });

    // 更新机器人身体边框
    var robotStyle = robot.style;
    robotStyle.borderColor = theme.accent + 'cc';
  },

  // 启动特效
  startEffect: function(effectType) {
    this.stopEffect();
    if (!effectType) return;

    var container = document.getElementById('festivalEffects');
    if (!container) return;

    var self = this;
    var particles = {
      'snow': ['❄', '❅', '❆', '✻', '✼'],
      'pumpkin': ['🎃', '👻', '🦇', '🕷️', '🕯️'],
      'firework': ['✨', '🎆', '🎇', '💫', '⭐'],
      'heart': ['❤️', '💕', '💖', '💗', '💓'],
      'leaf': ['🍃', '🍂', '🌿', '☘️', '🌱'],
      'star': ['⭐', '✨', '💫', '🌟', '✴️']
    };

    var chars = particles[effectType] || particles['star'];
    var colorMap = {
      'christmas': ['#fff', '#c41e3a', '#22c55e'],
      'halloween': ['#ff6b00', '#9333ea', '#ffd700'],
      'cny': ['#ffd700', '#dc2626', '#ff6b00'],
      'newyear': ['#ffd700', '#0ea5e9', '#38bdf8'],
      'valentine': ['#ff69b4', '#ec4899', '#f472b6'],
      'easter': ['#22c55e', '#fde047', '#4ade80'],
      'national': ['#ffd700', '#dc2626', '#fcd34d'],
      'space': ['#a78bfa', '#8b5cf6', '#e0e7ff'],
      'focus_moment': ['#ff6900', '#ffd700', '#ffaa55']
    };
    var colors = colorMap[this.currentTheme] || ['#fff'];

    // 初始化环境光效
    this._initAmbientEffects(this.currentTheme);

    // 初始化四角装饰
    this._initCornerDecorations(this.currentTheme);

    // 初始化胶片颗粒
    this._initGrainEffect();

    // 启用鼠标跟随光晕
    this._initMouseGlow();

    // 粒子飘落特效
    if (['snow', 'pumpkin', 'heart', 'leaf', 'star'].indexOf(effectType) >= 0) {
      this.effectInterval = setInterval(function() {
        var particle = document.createElement('div');
        particle.className = 'festival-particle';
        particle.textContent = chars[Math.floor(Math.random() * chars.length)];
        particle.style.left = Math.random() * 100 + '%';
        particle.style.color = colors[Math.floor(Math.random() * colors.length)];
        particle.style.fontSize = (14 + Math.random() * 12) + 'px';
        particle.style.animationDuration = (6 + Math.random() * 6) + 's';
        container.appendChild(particle);

        // 清理旧粒子
        setTimeout(function() {
          if (particle.parentNode) {
            particle.parentNode.removeChild(particle);
          }
        }, 12000);
      }, 600);
    }

    // 烟花爆炸特效（定时爆炸）
    if (effectType === 'firework') {
      this.fireworkInterval = setInterval(function() {
        self._createFirework(container, colors);
      }, 1500);
    }
  },

  // ★ 初始化环境光效
  _initAmbientEffects: function(themeId) {
    var vignette = document.getElementById('ambientVignette');
    var glowBottom = document.getElementById('ambientGlowBottom');
    if (!vignette) return;

    // 渐变遮罩随主题变化
    var darken = 0.6;
    if (['christmas', 'cny', 'national'].indexOf(themeId) >= 0) {
      darken = 0.7; // 更深的背景突出节日氛围
    }
    vignette.style.background = 'radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,' + darken + ') 100%)';
  },

  // ★ 初始化四角装饰
  _initCornerDecorations: function(themeId) {
    var corners = [
      {id: 'festivalCornerTL', position: 'tl'},
      {id: 'festivalCornerTR', position: 'tr'},
      {id: 'festivalCornerBL', position: 'bl'},
      {id: 'festivalCornerBR', position: 'br'},
    ];

    var cornerSVGs = this._getCornerDecorations(themeId);
    corners.forEach(function(corner, i) {
      var el = document.getElementById(corner.id);
      if (el && cornerSVGs[i]) {
        el.innerHTML = cornerSVGs[i];
        el.classList.add('visible');
      }
    });
  },

  // ★ 获取四个角装饰SVG
  _getCornerDecorations: function(themeId) {
    var deco = {
      'christmas': [
        '<svg viewBox="0 0 80 80"><path d="M5 65 Q40 30 75 5" fill="none" stroke="#c41e3a" stroke-width="2"/><circle cx="10" cy="60" r="3" fill="#22c55e"/><circle cx="20" cy="55" r="3" fill="#fff"/><circle cx="30" cy="45" r="3" fill="#ffd700"/></svg>',
        '<svg viewBox="0 0 80 80"><polygon points="70 10 40 35 70 60" fill="#22c55e"/></svg>',
        '<svg viewBox="0 0 80 80"><rect x="5" y="10" width="20" height="60" rx="3" fill="#c41e3a" stroke="#fff"/><rect x="5" y="15" width="20" height="8" fill="#fff"/></svg>',
        '<svg viewBox="0 0 80 80"><circle cx="60" cy="60" r="12" fill="#22c55e" stroke="#fff"/><polygon points="60 48 66 54 54 54" fill="#fff"/></svg>',
      ],
      'halloween': [
        '<svg viewBox="0 0 80 80"><ellipse cx="15" cy="65" rx="12" ry="10" fill="#ff6b00"/><circle cx="10" cy="62" r="2" fill="#000"/><circle cx="20" cy="62" r="2" fill="#000"/></svg>',
        '<svg viewBox="0 0 80 80"><path d="M60 15 L70 5 L75 15" fill="#9333ea"/></svg>',
        '<svg viewBox="0 0 80 80"><polygon points="5 65 15 75 25 65" fill="#ff6b00"/></svg>',
        '<svg viewBox="0 0 80 80"><circle cx="65" cy="65" r="10" fill="#9333ea" stroke="#ff6b00" stroke-width="1"/></svg>',
      ],
      'cny': [
        '<svg viewBox="0 0 80 80"><ellipse cx="20" cy="50" rx="8" ry="20" fill="#dc2626" stroke="#ffd700" stroke-width="1"/></svg>',
        '<svg viewBox="0 0 80 80"><rect x="40" y="10" width="30" height="50" rx="3" fill="#dc2626" stroke="#ffd700" stroke-width="1"><text x="55" y="35" font-size="18" fill="#ffd700" text-anchor="middle">福</text></rect></svg>',
        '<svg viewBox="0 0 80 80"><text x="15" y="65" font-size="20" fill="#ffd700" text-anchor="middle" transform="rotate(180 15 65)">福</text></svg>',
        '<svg viewBox="0 0 80 80"><rect x="30" y="30" width="40" height="40" rx="4" fill="#dc2626" stroke="#ffd700" stroke-width="2"/></svg>',
      ],
      'newyear': [
        '<svg viewBox="0 0 80 80"><circle cx="15" cy="65" r="5" fill="#ffd700"/><line x1="15" y1="65" x2="15" y2="15" stroke="#0ea5e9" stroke-width="3"/></svg>',
        '<svg viewBox="0 0 80 80"><circle cx="65" cy="15" r="5" fill="#ffd700"/><line x1="65" y1="15" x2="15" y2="65" stroke="#0ea5e9" stroke-width="3"/></svg>',
        '<svg viewBox="0 0 80 80"><circle cx="15" cy="15" r="5" fill="#ffd700"/><line x1="15" y1="15" x2="65" y2="15" stroke="#0ea5e9" stroke-width="3"/></svg>',
        '<svg viewBox="0 0 80 80"><polygon points="55 55 65 65 75 55 65 65" fill="#ffd700"/></svg>',
      ],
      'valentine': [
        '<svg viewBox="0 0 80 80"><path d="M10 60 Q5 50 10 40 Q15 35 20 40 Q25 35 30 40 Q35 50 30 60 L20 70 L10 60 Z" fill="#ec4899" fill-opacity="0.5"/></svg>',
        '<svg viewBox="0 0 80 80"><path d="M60 10 Q50 20 55 30 Q60 35 65 25 Q70 35 75 30 Q80 20 70 10 Z" fill="#f472b6" fill-opacity="0.5"/></svg>',
        '<svg viewBox="0 0 80 80"><path d="M5 70 Q2 60 8 50 Q12 55 15 50 Q18 55 20 50 Q25 60 22 70 L14 78 L5 70 Z" fill="#ec4899" fill-opacity="0.4"/></svg>',
        '<svg viewBox="0 0 80 80"><path d="M60 50 Q50 55 55 65 Q60 70 70 60 Q75 65 78 58 Q80 48 68 44 Z" fill="#f472b6" fill-opacity="0.4"/></svg>',
      ],
      'easter': [
        '<svg viewBox="0 0 80 80"><ellipse cx="15" cy="55" rx="8" ry="12" fill="#22c55e"/><ellipse cx="15" cy="55" rx="5" ry="8" fill="#fde047"/></svg>',
        '<svg viewBox="0 0 80 80"><ellipse cx="65" cy="15" rx="8" ry="12" fill="#22c55e"/><ellipse cx="65" cy="15" rx="5" ry="8" fill="#fde047"/></svg>',
        '<svg viewBox="0 0 80 80"><ellipse cx="15" cy="15" rx="8" ry="12" fill="#22c55e"/><ellipse cx="15" cy="15" rx="5" ry="8" fill="#fde047"/></svg>',
        '<svg viewBox="0 0 80 80"><ellipse cx="65" cy="65" rx="8" ry="12" fill="#22c55e"/><ellipse cx="65" cy="65" rx="5" ry="8" fill="#fde047"/></svg>',
      ],
      'national': [
        '<svg viewBox="0 0 80 80"><rect x="5" y="10" width="2" height="60" fill="#ffd700"/><rect x="7" y="10" width="25" height="18" fill="#dc2626"/><polygon points="10,14 10,24 18,19" fill="#ffd700"/></svg>',
        '<svg viewBox="0 0 80 80"><rect x="50" y="10" width="2" height="60" fill="#ffd700"/><rect x="52" y="10" width="25" height="18" fill="#dc2626"/><polygon points="55,14 55,24 63,19" fill="#ffd700"/></svg>',
        '<svg viewBox="0 0 80 80"><circle cx="15" cy="65" r="8" fill="#dc2626"/><polygon points="15,59 17,63 21,63 18,66 19,70 15,67 11,70 12,66 9,63 13,63" fill="#ffd700"/></svg>',
        '<svg viewBox="0 0 80 80"><circle cx="65" cy="65" r="8" fill="#dc2626"/><polygon points="65,59 67,63 71,63 68,66 69,70 65,67 61,70 62,66 59,63 63,63" fill="#ffd700"/></svg>',
      ],
      'space': [
        '<svg viewBox="0 0 80 80"><circle cx="15" cy="65" r="6" fill="#8b5cf6"/><ellipse cx="15" cy="65" rx="10" ry="3" fill="none" stroke="#a78bfa" stroke-width="1"/></svg>',
        '<svg viewBox="0 0 80 80"><circle cx="65" cy="15" r="6" fill="#8b5cf6"/><ellipse cx="65" cy="15" rx="10" ry="3" fill="none" stroke="#a78bfa" stroke-width="1"/></svg>',
        '<svg viewBox="0 0 80 80"><polygon points="12,12 8,8 6,14 10,18" fill="#a78bfa"/><polygon points="8,8 4,4 2,10 6,14" fill="#8b5cf6"/></svg>',
        '<svg viewBox="0 0 80 80"><polygon points="65,65 70,60 72,68 68,72" fill="#a78bfa"/><polygon points="70,60 75,55 77,63 73,67" fill="#8b5cf6"/></svg>',
      ],
    };
    return deco[themeId] || ['', '', '', ''];
  },

  // ★ 创建烟花爆炸
  _createFirework: function(container, colors) {
    var cx = Math.random() * 100 + '%';
    var cy = Math.random() * 40 + '%';
    var numParticles = 20 + Math.floor(Math.random() * 30);
    var baseColor = colors[Math.floor(Math.random() * colors.length)];

    // 爆炸光晕
    var puff = document.createElement('div');
    puff.className = 'firework-puff';
    puff.style.left = cx;
    puff.style.top = cy;
    puff.style.width = (80 + Math.random() * 80) + 'px';
    puff.style.height = puff.style.width;
    puff.style.background = 'radial-gradient(circle, ' + baseColor + ' 0%, transparent 70%)';
    puff.style.transform = 'translate(-50%, -50%)';
    container.appendChild(puff);

    // 火花粒子
    for (var i = 0; i < numParticles; i++) {
      var angle = (Math.PI * 2 * i) / numParticles;
      var speed = 2 + Math.random() * 3;
      var dx = Math.cos(angle) * speed * 10;
      var dy = Math.sin(angle) * speed * 10;
      var trail = document.createElement('div');
      trail.className = 'firework-trail';
      trail.style.left = cx;
      trail.style.top = cy;
      trail.style.transform = 'translate(-50%, -50%)';
      trail.style.setProperty('--dx', dx + 'px');
      trail.style.setProperty('--dy', dy + 'px');
      trail.style.background = baseColor;
      container.appendChild(trail);

      // ★ 修复：用 IIFE 捕获当前 trail 和 puff 的引用
      (function(t, p, isFirst) {
        setTimeout(function() {
          if (t.parentNode) t.parentNode.removeChild(t);
          if (isFirst && p.parentNode) p.parentNode.removeChild(p);
        }, 1500);
      })(trail, puff, i === 0);
    }
  },

  // ★ 胶片颗粒效果
  _initGrainEffect: function() {
    var canvas = document.getElementById('ambientGrain');
    if (!canvas) return;

    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    var ctx = canvas.getContext('2d');
    var imageData = ctx.createImageData(canvas.width, canvas.height);
    var data = imageData.data;

    for (var i = 0; i < data.length; i += 4) {
      var grain = Math.random() * 255;
      data[i] = data[i + 1] = data[i + 2] = grain;
      data[i + 3] = 8; // 透明度很低
    }
    ctx.putImageData(imageData, 0, 0);
  },

  // ★ 鼠标跟随光晕
  _initMouseGlow: function() {
    var light = document.getElementById('ambientMouseLight');
    if (!light) return;

    light.classList.add('active');
    var self = this;
    document.addEventListener('mousemove', function(e) {
      light.style.left = e.clientX + 'px';
      light.style.top = e.clientY + 'px';
    });
  },

  // 停止特效
  stopEffect: function() {
    if (this.effectInterval) {
      clearInterval(this.effectInterval);
      this.effectInterval = null;
    }
    if (this.fireworkInterval) {
      clearInterval(this.fireworkInterval);
      this.fireworkInterval = null;
    }
    var container = document.getElementById('festivalEffects');
    if (container) {
      container.innerHTML = '';
    }
    // 隐藏四角装饰
    ['festivalCornerTL', 'festivalCornerTR', 'festivalCornerBL', 'festivalCornerBR'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) {
        el.classList.remove('visible');
        el.innerHTML = '';
      }
    });
  },

  // 预览特效
  previewEffect: function(effectType) {
    this.startEffect(effectType);
    var self = this;
    setTimeout(function() {
      self.stopEffect();
    }, 3000);
  },

  // 自动检测节日
  autoDetect: function() {
    if (!this.autoFestival) return;

    var now = new Date();
    var month = now.getMonth() + 1;
    var day = now.getDate();

    // 节日检测规则
    if (month === 12 && day >= 20 && day <= 26) {
      this.apply('christmas');
    } else if (month === 10 && day >= 25 && day <= 31) {
      this.apply('halloween');
    } else if ((month === 1 && day >= 21 && day <= 31) || (month === 2 && day <= 10)) {
      this.apply('cny');
    } else if ((month === 1 && day === 1) || (month === 12 && day === 31)) {
      this.apply('newyear');
    } else if (month === 2 && day >= 12 && day <= 16) {
      this.apply('valentine');
    } else if (month === 4 && day >= 10 && day <= 25) {
      this.apply('easter');
    } else if (month === 10 && day === 1) {
      this.apply('national');
    }
  },

  // 初始化
  init: function() {
    var saved = localStorage.getItem('festivalTheme');
    var isValid = saved && this.themes[saved];
    var isFestivalActive = isValid ? this._isFestivalActive(saved) : false;
    if (isFestivalActive) {
      this.apply(saved);
    } else {
      if (saved && saved !== 'default') {
        try { localStorage.removeItem('festivalTheme'); } catch (e) {}
      }
      this.apply('default');
    }
    if (typeof updateOceanModeUI === 'function') {
      updateOceanModeUI('default');
    }
  },

  // ★ v12.9: 核心主题（default/ocean/focus_moment）始终可持久化
  // 节日主题（christmas等）一律封存，不可持久化
  _isFestivalActive: function(themeId) {
    var festivalThemes = ['christmas','halloween','cny','newyear','valentine','easter','national'];
    return festivalThemes.indexOf(themeId) !== -1;
  }
};

// 全局函数
function applyFestivalTheme(themeId) {
  ThemeManager.apply(themeId);
  updateOceanModeUI(themeId);
  // ★ v4.1.9: 用户主动点击的节日主题才持久化到 localStorage
  // default 永远是默认入口，不需要存；启动时 init() 会按 _isFestivalActive 判定是否恢复
  if (themeId === 'default' || ThemeManager._isFestivalActive(themeId)) {
    try { localStorage.setItem('festivalTheme', themeId); } catch (e) {}
  }
}

function previewThemeEffect(effectType) {
  ThemeManager.previewEffect(effectType);
}

// ★ 关闭节日祝福语横幅
function closeFestivalBanner() {
  var banner = document.getElementById('festivalBanner');
  if (banner) {
    banner.style.display = 'none';
  }
}

// ============================================================
// Console Message Bridge — JS → Python 双向通信
// Python→JS: 使用 runJavaScript (由 Python 端直接调用)
// JS→Python: 使用 console.log + DebugWebPage 拦截
// ============================================================
(function() {
    var _callbacks = {};
    var _callbackId = 0;

    // JS → Python 调用
    window._callPython = function(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        var callback = null;
        // 检查最后一个参数是否是回调函数
        if (args.length > 0 && typeof args[args.length - 1] === 'function') {
            callback = args.pop();
        }
        var msg = { method: method, args: args };
        if (callback) {
            _callbackId++;
            _callbacks[_callbackId] = callback;
            msg.callbackId = _callbackId;
        }
        console.log('__PYBRIDGE__:' + JSON.stringify(msg));
    };

    // Python 回调响应
    window._pybridgeCallback = function(callbackId, result) {
        if (_callbacks[callbackId]) {
            _callbacks[callbackId](result);
            delete _callbacks[callbackId];
        }
    };

    // 等待 DOM 准备好再添加状态指示器
    function initBridgeStatus() {
        if (document.body) {
            var bridgeStatus = document.createElement('div');
            bridgeStatus.id = 'bridgeStatus';
            bridgeStatus.style.cssText = 'position:fixed;top:2px;left:2px;z-index:99999;font-size:10px;color:rgba(255,255,255,0.05);pointer-events:none;';
            bridgeStatus.textContent = '桥接: Console Bridge';
            document.body.appendChild(bridgeStatus);

            window._updateBridgeStatus = function(ok, msg) {
                bridgeStatus.textContent = '桥接: ' + (ok ? 'OK' : 'FAIL') + (msg ? ' ' + msg : '');
                bridgeStatus.style.color = ok ? 'rgba(0,255,100,0.15)' : 'rgba(255,100,100,0.15)';
            };
        } else {
            setTimeout(initBridgeStatus, 10);
        }
    }
    initBridgeStatus();

    console.log('[MIMO] Console Message Bridge 已加载');
})();