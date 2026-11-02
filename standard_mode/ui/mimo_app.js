// ===== 交互状态 =====
// ★ v3.82-C3: Icon placeholder replacement (expanded v4.8.1 to handle SVG_ICONS[] literals)
function replaceIconPlaceholders(html) {
  if (!html || typeof SVG_ICONS === 'undefined') return html;
  // 1. Handle {ICON:xxx} placeholders
  html = html.replace(/\{ICON:([\w-]+)\}/g, function(m, name) {
    return SVG_ICONS[name] || m;
  });
  // 2. Handle literal SVG_ICONS["xxx"] or SVG_ICONS['xxx'] text leaking into content
  html = html.replace(/SVG_ICONS\[["']([\w-]+)["']\]/g, function(m, name) {
    return SVG_ICONS[name] || '';
  });
  return html;
}

// ★ v3.82-C3: Timeline event helper
function appendTimelineEvent(eventStr) {
  if (typeof window._appendTimelineEvent === 'function') {
    window._appendTimelineEvent(eventStr);
  }
}

var _configSessionId = '';
var _configOptions = [];
var _permSessionId = '';
var _permCallback = null;
var _currentMode = 'Build';
var _serviceMode = 'single';  // 服务模式: single, multi, terminal, demo, hybrid
var _builtinModes = [
  { id: 'agent', name: 'Agent', icon: '{ICON:bot}', desc: 'mode.desc.agent', color: '#ff6900' },
  { id: 'code', name: 'Code', icon: '{ICON:square-terminal}', desc: 'mode.desc.code', color: '#30d158' },
  { id: 'edit', name: 'Edit', icon: '{ICON:square-pen}', desc: 'mode.desc.edit', color: '#5e5ce6' },
  { id: 'architect', name: 'Architect', icon: '{ICON:layout-template}', desc: 'mode.desc.architect', color: '#ff9f43' },
  { id: 'ask', name: 'Ask', icon: '{ICON:message-circle}', desc: 'mode.desc.ask', color: '#5cadff' },
];

// Python 调用接口
window.mimoAgent = {
  appendMessage: function(html) {
    if (!window._appendMsg) {
      console.error('[mimoAgent] _appendMsg 未定义，消息丢失:', html ? html.substring(0, 100) : 'null');
      // ★ 兜底：直接调用 appendMsg（如果它已在全局作用域中）
      if (typeof appendMsg === 'function') { appendMsg('ai', html); }
      return;
    }
    window._appendMsg('ai', html);
  },
  appendData: function(data) {
    if (!data || !data.type) { return; }
    if (data.type === 'md' && typeof marked !== 'undefined') {
      var rendered = marked.parse(data.text || '', { breaks: true, gfm: true });
      var html = "<div class='agent-md-output' style='color:" + (data.color || '#e0e0e0') + ";line-height:1.55;'>" + rendered + "</div>";
      if (window._appendMsg) { window._appendMsg('ai', html); }
      else if (typeof appendMsg === 'function') { appendMsg('ai', html); }
    } else {
      var fallback = "<span style='color:" + (data.color || '#e0e0e0') + ";'>" + (data.text || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>') + "</span>";
      if (window._appendMsg) { window._appendMsg('ai', fallback); }
      else if (typeof appendMsg === 'function') { appendMsg('ai', fallback); }
    }
  },
  appendThinking: function(html) { if (window._appendMsg) window._appendMsg('thinking', replaceIconPlaceholders(html)); },
  appendStatus: function(html) { if (window._appendMsg) window._appendMsg('status', replaceIconPlaceholders(html)); },
  appendTool: function(html) { if (window._appendMsg) window._appendMsg('tool', replaceIconPlaceholders(html)); },
  // ★ v3.82-C3: Stream token (typewriter effect)
  appendStreamToken: function(tok) {
    var reply = document.querySelector('.trace-reply:last-child');
    if (!reply) {
      var container = document.querySelector('.msg-ai:last-child .trace-body');
      if (container) {
        reply = document.createElement('div');
        reply.className = 'trace-reply';
        container.appendChild(reply);
      }
    }
    if (reply) {
      var cursor = reply.querySelector('.type-cursor');
      if (cursor) cursor.remove();
      reply.appendChild(document.createTextNode(tok));
      var nc = document.createElement('span');
      nc.className = 'type-cursor';
      reply.appendChild(nc);
      reply.scrollTop = reply.scrollHeight;
    }
  },
  // ★ v3.82-C3: Sub-agent card
  appendSubagent: function(specJson) {
    var spec = typeof specJson === 'string' ? JSON.parse(specJson) : specJson;
    var container = document.querySelector('.msg-ai:last-child .trace-subagents');
    if (!container) return;
    var card = document.createElement('details');
    card.className = 'sub-card';
    card.setAttribute('data-id', spec.id || '');
    card.innerHTML = '<summary>' + SVG_ICONS['git-branch'] + ' ' + (spec.name || 'sub') + ' ' + SVG_ICONS['loader-circle'] + '</summary><div class="sub-result">running...</div>';
    container.appendChild(card);
  },
  updateSubagent: function(id, resultJson) {
    var card = document.querySelector('.sub-card[data-id="' + id + '"]');
    if (!card) return;
    var result = typeof resultJson === 'string' ? JSON.parse(resultJson) : resultJson;
    card.querySelector('.sub-result').textContent = result.content || result.error || 'done';
    var statusIcon = result.status === 'success' ? SVG_ICONS.check : SVG_ICONS['circle-x'];
    card.querySelector('summary').innerHTML = SVG_ICONS['git-branch'] + ' ' + (result.name || id) + ' ' + statusIcon;
  },
  // ★ v3.82-C3: Task started/finished
  appendTaskStarted: function(taskId) {
    appendTimelineEvent(JSON.stringify({type:'task_start', id:taskId, ts:Date.now()}));
  },
  appendTaskFinished: function(ok, taskId) {
    appendTimelineEvent(JSON.stringify({type:'task_end', id:taskId, ok:ok, ts:Date.now()}));
  },
  appendDelta: function(text) {
    var terminal = document.querySelector('.msg-ai:last-child .terminal-line');
    if (!terminal) {
      var body = document.querySelector('.msg-ai:last-child .trace-body');
      if (body) {
        terminal = document.createElement('div');
        terminal.className = 'terminal-line';
        body.appendChild(terminal);
      }
    }
    if (terminal) {
      terminal.appendChild(document.createTextNode(text));
      terminal.scrollTop = terminal.scrollHeight;
    }
  },
  streamEnded: function() {
    var cursor = document.querySelector('.type-cursor');
    if (cursor) cursor.remove();
    var reply = document.querySelector('.trace-reply:last-child');
    if (reply && window.marked && window.marked.parse) {
      var raw = reply.textContent || '';
      reply.innerHTML = window.marked.parse(raw);
    }
  },
  onFileStatus: function(path, status) {
    var panel = document.querySelector('.file-change-panel');
    if (!panel) return;
    var item = panel.querySelector('.file-change-item[data-path="' + path + '"]');
    if (status === 'writing') {
      if (!item) {
        item = document.createElement('div');
        item.className = 'file-change-item file-writing';
        item.setAttribute('data-path', path);
        item.innerHTML = '<span class="writing-spinner">' + SVG_ICONS['loader-circle'] + '</span><span class="fc-path">' + path + '</span><span class="writing-label">正在写入...</span>';
        panel.appendChild(item);
      } else {
        var icon = item.querySelector('.fc-icon');
        if (icon) icon.innerHTML = SVG_ICONS['loader-circle'];
        item.className = 'file-change-item file-writing';
      }
    } else if (status === 'done') {
      if (item) {
        item.className = 'file-change-item file-modified';
        var icon = item.querySelector('.fc-icon, .writing-spinner');
        if (icon) icon.innerHTML = SVG_ICONS.check;
        var label = item.querySelector('.writing-label');
        if (label) label.textContent = '';
      }
    } else if (status === 'failed') {
      if (item) {
        item.className = 'file-change-item file-deleted';
        var icon2 = item.querySelector('.fc-icon, .writing-spinner');
        if (icon2) icon2.innerHTML = SVG_ICONS['circle-x'];
      }
    }
  },
  // ★ v4.1.15: 执行轨迹流（Timeline）—— CodeBuddy 式时间线事件
  appendTimeline: function(eventStr) {
    if (typeof window._appendTimelineEvent === 'function') {
      window._appendTimelineEvent(eventStr);
    }
  },
  // ★ v5.1: P-C 任务步骤列表 — 汇总本次运行所有工具调用，渲染到右侧栏顶部
  renderAgentSteps: function(stepsJson) {
    if (typeof window._renderAgentSteps === 'function') {
      window._renderAgentSteps(stepsJson);
    }
  },
  // ★ v3.90: 文件预览（HTML iframe/图像/代码内嵌到右侧栏）
  appendPreview: function(html) {
    console.log('[mimoAgent.appendPreview] 收到文件预览, htmlLen=' + (html||'').length);
    if (!window._appendMsg) {
      if (typeof appendMsg === 'function') { appendMsg('ai', html); }
      return;
    }
    // 文件预览作为 AI 消息的一部分显示（内嵌在右侧栏）
    window._appendMsg('ai', html);
    // ★ 绑定运行按钮点击事件
    setTimeout(function() {
      var area = document.getElementById('outputMessages');
      if (!area) return;
      var btns = area.querySelectorAll('.run-code-btn:not([data-bound])');
      btns.forEach(function(btn) {
        btn.setAttribute('data-bound', 'true');
        btn.addEventListener('click', function() {
          var lang = btn.getAttribute('data-lang') || 'python';
          var code = btn.getAttribute('data-code') || '';
          // 解码 HTML 实体
          var textarea = document.createElement('textarea');
          textarea.innerHTML = code;
          code = textarea.value;
          console.log('[run-code-btn] 运行代码, lang=' + lang + ', len=' + code.length);
          // 通过 pybridge 调用 Python 运行代码
          if (window.pybridge && window.pybridge.runCode) {
            window.pybridge.runCode(lang, code);
          } else if (window.qt && window.qt.webChannelTransport) {
            // QWebChannel 方式
            window.qt.webChannelTransport.send(JSON.stringify({
              type: 'run_code', lang: lang, code: code
            }));
          } else {
            // 临时方案：在终端显示
            appendMsg('status', '<span style="color:#ff9800;">代码运行功能正在加载中...</span>');
          }
        });
      });
    }, 300);
  },
  appendUserMessage: function(text) { if (window._appendMsg) window._appendMsg('user', text); },
  clearOutput: function() {
    if (typeof clearOutput === 'function') clearOutput();
    // ★ 清除思考内容（现在在outputMessages内部）
    var area = document.getElementById('outputMessages');
    if (area) {
      var thinkings = area.querySelectorAll('.thinking-inline');
      thinkings.forEach(function(t) { t.remove(); });
    }
  },
  setConnected: function(connected) {
    var dot = document.getElementById('statusDot');
    var txt = document.getElementById('statusText');
    if (!dot || !txt) return;
    if (connected) {
      dot.className = 'status-dot connected';
      txt.textContent = 'connected';
    } else {
      dot.className = 'status-dot disconnected';
      txt.textContent = 'ready';
    }
  },
  setRobotStatus: function(status) {
    // 机器人状态通过表情表达，不再显示外部文字
  },
  
  // ===== 配置选项交互 =====
  showConfigOptions: function(sessionId, options) {
    _configSessionId = sessionId;
    _configOptions = options;
    renderConfigOptions(options);
    var overlay = document.getElementById('configOverlay');
    if (overlay) overlay.classList.add('show');
  },
  
  // ===== 权限请求 =====  
  showPermission: function(sessionId, toolInfo, options) {
    _permSessionId = sessionId;
    var permTool = document.getElementById('permTool');
    var permDesc = document.getElementById('permDesc');
    if (permTool) permTool.textContent = i18n.t('perm.toolShort') + (toolInfo.title || toolInfo.kind || 'unknown');
    if (permDesc) permDesc.textContent = toolInfo.description || i18n.t('perm.descDefault');
    
    var container = document.getElementById('permOptions');
    container.innerHTML = '';
    options.forEach(function(opt) {
      var btn = document.createElement('button');
      btn.className = 'perm-btn';
      if (opt.kind === 'allow_once' || opt.kind === 'allow_always') {
        btn.className += opt.kind === 'allow_always' ? ' perm-btn-always' : ' perm-btn-allow';
      } else {
        btn.className += ' perm-btn-reject';
      }
      btn.textContent = opt.name;
      btn.onclick = function() { respondPermission(sessionId, opt.id); };
      container.appendChild(btn);
    });
    document.getElementById('permissionOverlay').classList.add('show');
  },
  
  // ===== 模式更新 =====
  setMode: function(modeId) {
    _currentMode = modeId;
    updateModeDisplay();
    // 刷新模式面板高亮
    if (document.getElementById('modePanel').classList.contains('show')) {
      renderModeList();
    }
  },
  
  // ===== 模式切换 =====
  switchToMode: function(modeId) {
    closeModePanel();
    window._callPython('sendMessage', '__mode__:' + modeId);
  },
  
  // ===== 计划显示 =====
  showPlan: function(entries) {
    var area = document.getElementById('planArea');
    var list = document.getElementById('planList');
    if (!list) return;
    if (!entries || entries.length === 0) {
      if (area) area.classList.remove('show');
      return;
    }
    list.innerHTML = '';
    var hasIncomplete = false;
    entries.forEach(function(entry) {
      var div = document.createElement('div');
      var status = entry.status || 'pending';
      if (status === 'completed') { div.className = 'plan-item completed'; }
      else if (status === 'in_progress') { div.className = 'plan-item in_progress'; hasIncomplete = true; }
      else { div.className = 'plan-item'; hasIncomplete = true; }
      var icon = status === 'completed' ? SVG_ICONS.check : status === 'in_progress' ? '◉' : '○';
      div.innerHTML = '<span class="plan-status">' + icon + '</span><span>' + (entry.content || '') + '</span>';
      list.appendChild(div);
    });
    if (hasIncomplete) {
      if (area) area.classList.add('show');
    } else {
      if (area) area.classList.remove('show');
    }
  },
  
  // ===== 可用命令显示 =====
  showCommands: function(commands) {
    var list = document.getElementById('cmdList');
    if (!list) return;
    list.innerHTML = '';
    if (!commands || commands.length === 0) {
      list.innerHTML = '<div style="color:rgba(255,255,255,0.2);font-size:11px;padding:12px;text-align:center;">暂无可用命令</div>';
      return;
    }
    commands.forEach(function(cmd) {
      var div = document.createElement('div');
      div.className = 'cmd-item';
      div.onclick = function() { sendCommand(cmd.name); };
      div.innerHTML = '<div class="cmd-name">' + (cmd.name || '') + '</div>' +
        (cmd.description ? '<div class="cmd-desc">' + cmd.description + '</div>' : '');
      list.appendChild(div);
    });
  },
  
  // ===== 用量显示 =====
  showUsage: function(tokens) {
    var bar = document.getElementById('usageBar');
    if (tokens && (tokens.input_tokens || tokens.output_tokens || tokens.total_tokens)) {
      var input = tokens.input_tokens || 0;
      var output = tokens.output_tokens || 0;
      var total = tokens.total_tokens || (input + output);
      if (bar) bar.innerHTML = '<span>in: ' + input + '</span><span>out: ' + output + '</span><span title="总计">∑: ' + total + '</span>';
      // 更新底部输入行统计（★ v4.1.28: 积分/Tokens/耗时）
      _updateInputStats(total);
    } else if (tokens && (tokens.input || tokens.output)) {
      var inp = tokens.input || 0;
      var out = tokens.output || 0;
      if (bar) bar.innerHTML = '<span>in: ' + inp + '</span><span>out: ' + out + '</span>';
      _updateInputStats(inp + out);
    }
  }
};

// ===== 更新模式显示 =====
function updateModeDisplay() {
  var modeLabel = document.querySelector('.mode-label');
  if (modeLabel) modeLabel.textContent = _currentMode;
}

// ===== 服务模式切换（右上角） =====
var _svcModeConfig = {
  original: { icon: SVG_ICONS['layout-template'], label: '原始界面', desc: '文件树+编辑器+AI面板，经典布局' },
  single: { icon: SVG_ICONS.diamond, label: '单窗口', desc: '一个 Lemon Code，简单任务' },
  multi: { icon: SVG_ICONS.diamond, label: '多窗口', desc: '多个 Lemon Code 并行协同' },
  terminal: { icon: '⬛', label: '纯终端', desc: '专注编码，隐藏右侧面板' },
  demo: { icon: '⬜', label: '演示', desc: '可视化展示，隐藏终端' },
  hybrid: { icon: SVG_ICONS.database, label: '混合AI', desc: 'Lemon + Ollama 协同算力' }
};

function toggleServiceModeMenu() {
  var menu = document.getElementById('svcModeMenu');
  var btn = document.getElementById('svcModeBtn');
  if (!menu || !btn) return;
  if (menu.classList.contains('show')) {
    closeServiceModeMenu();
  } else {
    menu.classList.add('show');
    btn.classList.add('open');
    setTimeout(function() {
      document.addEventListener('click', closeServiceModeOnClickOutside);
    }, 0);
  }
}

function closeServiceModeMenu() {
  var menu = document.getElementById('svcModeMenu');
  var btn = document.getElementById('svcModeBtn');
  if (!menu || !btn) return;
  menu.classList.remove('show');
  btn.classList.remove('open');
  document.removeEventListener('click', closeServiceModeOnClickOutside);
}

function closeServiceModeOnClickOutside(e) {
  var sw = document.getElementById('serviceModeSwitcher');
  if (sw && !sw.contains(e.target)) {
    closeServiceModeMenu();
  }
}

function switchServiceMode(modeId) {
  if (_serviceMode === modeId) { closeServiceModeMenu(); return; }
  _serviceMode = modeId;
  var cfg = _svcModeConfig[modeId];
  if (!cfg) return;
  
  // 更新按钮显示
  document.getElementById('svcModeIcon').textContent = cfg.icon;
  document.getElementById('svcModeLabel').textContent = cfg.label;
  
  // 更新菜单高亮
  var items = document.querySelectorAll('.svc-mode-item');
  items.forEach(function(item) {
    item.classList.toggle('active', item.dataset.mode === modeId);
  });
  
  closeServiceModeMenu();
  
  // 通知 Python 切换服务模式
  window._callPython('sendMessage', '__service_mode__:' + modeId);
}

// Python 回调：设置服务模式
window.mimoAgent.setServiceMode = function(modeId) {
  _serviceMode = modeId;
  var cfg = _svcModeConfig[modeId];
  if (cfg) {
    document.getElementById('svcModeIcon').textContent = cfg.icon;
    document.getElementById('svcModeLabel').textContent = cfg.label;
  }
  var items = document.querySelectorAll('.svc-mode-item');
  items.forEach(function(item) {
    item.classList.toggle('active', item.dataset.mode === modeId);
  });
};

// ===== 模式面板 =====
function toggleModePanel() {
  var panel = document.getElementById('modePanel');
  if (panel.classList.contains('show')) {
    closeModePanel();
  } else {
    renderModeList();
    panel.classList.add('show');
  }
}
function closeModePanel() {
  document.getElementById('modePanel').classList.remove('show');
}
function renderModeList() {
  var list = document.getElementById('modeList');
  if (!list) return;
  list.innerHTML = '';
  // 显示 ACP 提供的模式 + 内置模式
  var allModes = _builtinModes.slice();
  allModes.forEach(function(mode) {
    var div = document.createElement('div');
    div.className = 'mode-item' + (mode.id.toLowerCase() === _currentMode.toLowerCase() ? ' active' : '');
    div.onclick = function() { window.mimoAgent.switchToMode(mode.id); };
    var iconColor = mode.color || '#ff6900';
    div.innerHTML = '<div class="mode-icon" style="' + (mode.id.toLowerCase() === _currentMode.toLowerCase() ? '' : 'color:' + iconColor) + '">' + mode.icon + '</div>' +
      '<div class="mode-info"><div class="mode-name">' + mode.name + '</div>' +
      (mode.desc ? '<div class="mode-desc">' + i18n.t(mode.desc) + '</div>' : '') + '</div>';
    list.appendChild(div);
  });
}

// ===== 命令面板 =====
function toggleCmdPanel() {
  var overlay = document.getElementById('cmdOverlay');
  overlay.classList.toggle('show');
}
function closeCmdPanel() {
  document.getElementById('cmdOverlay').classList.remove('show');
}
function sendCommand(cmdName) {
  window._callPython('sendMessage', '/' + cmdName);
  closeCmdPanel();
}

// ===== 模型面板（旧兼容层）=====
// ★ v4.1.13: 将旧的 _currentModel 字符串变量重命名为 _legacyCurrentModel，
// 避免与第19160行新模型选择逻辑的 _currentModel 对象（{provider, modelId, modelName}）
// 发生同名冲突。该冲突会导致 Python 调用 window.mimoAgent.setCurrentModel 时把全局
// _currentModel 覆写为字符串，进而让顶部状态栏/模型下拉显示 undefined。
var _modelList = [];
var _legacyCurrentModel = 'mimo-auto';

// ★ 旧版本toggleModelPanel已废弃（操作已不存在的modelPanel）
// 使用第10311行的新版本，操作modelSelectPanel
function toggleModelPanel_DEPRECATED() {
  console.warn('toggleModelPanel旧版本已废弃，请使用新版本');
}
function closeModelPanel() {
  document.getElementById('modelPanel').classList.remove('show');
}
function fetchModels() {
  window._callPython('sendMessage', '__fetch_models__');
}
function renderModelList(models) {
  _modelList = models || [];
  var list = document.getElementById('modelList');
  if (!list) return;
  if (!_modelList || _modelList.length === 0) {
    list.innerHTML = '<div style="color:rgba(255,255,255,0.2);font-size:11px;padding:12px;text-align:center;">正在加载模型列表...</div>';
    return;
  }
  list.innerHTML = '';
  _modelList.forEach(function(m) {
    var mid = m.id || m.model_id || '?';
    var mname = m.name || m.display_name || mid;
    var isActive = mid === _legacyCurrentModel;
    var div = document.createElement('div');
    div.className = 'mode-item' + (isActive ? ' active' : '');
    div.onclick = function() { switchModel(mid); };
    div.innerHTML = '<div class="mode-icon" style="' + (isActive ? '' : 'color:#ff9a4a') + '">' + SVG_ICONS.bot + '</div>' +
      '<div class="mode-info"><div class="mode-name">' + mname + '</div>' +
      '<div class="mode-desc">' + mid + '</div></div>';
    list.appendChild(div);
  });
}
function switchModel(modelId) {
  _legacyCurrentModel = modelId;
  closeModelPanel();
  window._callPython('sendMessage', '__model__:' + modelId);
  // 更新模式行显示
  var modeSub = document.querySelector('.mode-sub');
  if (modeSub) modeSub.textContent = modelId;
}
window.mimoAgent.showModels = function(models) {
  renderModelList(models);
};
window.mimoAgent.setCurrentModel = function(modelId) {
  _legacyCurrentModel = modelId;
  var modeSub = document.querySelector('.mode-sub');
  if (modeSub) modeSub.textContent = modelId;
  // ★ 同时更新会话管理栏的模型显示（v2.1）
  var modelLabel = document.getElementById('modelLabel');
  if (modelLabel) modelLabel.textContent = i18n.t('session.modelLabel', {model: modelId});
};

// ===== 会话面板 =====
var _sessionList = [];
var _currentSessionId = '';

function toggleSessionPanel() {
  var panel = document.getElementById('sessionPanel');
  if (panel.classList.contains('show')) {
    closeSessionPanel();
  } else {
    closeModePanel();
    closeModelPanel();
    fetchSessions();
    panel.classList.add('show');
  }
}
function closeSessionPanel() {
  document.getElementById('sessionPanel').classList.remove('show');
}
function fetchSessions() {
  window._callPython('sendMessage', '__fetch_sessions__');
}
function renderSessionList(sessions) {
  _sessionList = sessions || [];
  var list = document.getElementById('sessionList');
  if (!list) return;
  if (!_sessionList || _sessionList.length === 0) {
    list.innerHTML = '<div style="color:rgba(255,255,255,0.2);font-size:11px;padding:12px;text-align:center;">暂无会话</div>';
    return;
  }
  list.innerHTML = '';
  _sessionList.forEach(function(s) {
    var sid = s.id || '?';
    var title = s.title || '无标题';
    var isActive = sid === _currentSessionId;
    var div = document.createElement('div');
    div.className = 'mode-item' + (isActive ? ' active' : '');
    div.onclick = function() { switchSession(sid); };
    div.innerHTML = '<div class="mode-icon" style="' + (isActive ? '' : 'color:#5cadff') + '">' + SVG_ICONS['message-circle'] + '</div>' +
      '<div class="mode-info"><div class="mode-name">' + title + '</div>' +
      '<div class="mode-desc">' + (sid ? sid.substring(0, 20) + '...' : '') + '</div></div>';
    list.appendChild(div);
  });
}
function switchSession(sessionId) {
  _currentSessionId = sessionId;
  closeSessionPanel();
  window._callPython('sendMessage', '__session__:' + sessionId);
}
function createNewSession() {
  // ★ v4.8.1: 不依赖旧的 closeSessionPanel()，直接使用本地会话创建
  // 优先使用本地会话创建（即使 Python 端未连接也能工作）
  if (typeof _createSession === 'function') {
    var defaultName = '会话 ' + new Date().toLocaleString('zh-CN', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
    _createSession(defaultName);
    console.log('[createNewSession] 本地创建会话成功:', defaultName);
  } else {
    // 回退方案
    console.warn('[createNewSession] _createSession 未定义，回退到 Python 端');
    if (typeof window._callPython === 'function') {
      window._callPython('sendMessage', '__new_session__');
    } else {
      showToast('❌ 无法创建会话：桥接未就绪');
    }
  }
}
window.mimoAgent.showSessions = function(sessions) {
  renderSessionList(sessions);
};
window.mimoAgent.setCurrentSession = function(sessionId) {
  _currentSessionId = sessionId;
  // ★ 同时更新会话管理栏的会话显示（v2.1）
  var sessionLabel = document.getElementById('sessionLabel');
  if (sessionLabel) sessionLabel.textContent = '会话: ' + sessionId;
};

// ===== 输出操作 =====
function clearOutput() {
  var area = document.getElementById('outputMessages');
  if (area) area.innerHTML = '';
  window._globalMsgCount = 0;  // ★ 重置消息计数器
  _streamActive = false;
  _streamRendered = false;
  // ★ v4.1.15 + v5.3: 清空时同时重置 Timeline 文件统计（明确用 window._timelineFiles，避免隐式全局依赖）
  window._timelineFiles = {};
  var fileCountEl = document.getElementById('fileTabCount');
  if (fileCountEl) { fileCountEl.textContent = '(0)'; }
  try { localStorage.removeItem('mimo_chat_history'); } catch(e) {}
}

// ★ P8: 会话管理器（右侧面板"历史"Tab）
var _sessionsDirty = false;  // 会话数据是否已变更
var _autoSaveTimer = null;   // 自动保存计时器

// ============================================================
// ★ 增强右侧面板 — 任务/思考/文件/Diff 渲染
// ============================================================

// ===== 任务面板 =====
function _renderTasksPanel() {
  var html = '';
  var total = _tasks.length;
  var completed = _tasks.filter(function(t) { return t.status === 'completed'; }).length;
  var progress = total > 0 ? Math.round(completed / total * 100) : 0;

  html += '<div style="padding:10px 12px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,0.06);">';
  html += '<span style="color:rgba(255,255,255,0.8);font-size:13px;font-weight:600;">任务列表</span>';
  html += '<span style="color:rgba(255,255,255,0.5);font-size:11px;">' + completed + '/' + total + ' 完成</span>';
  html += '</div>';
  html += '<div style="padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.06);">';
  html += '<div style="height:3px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden;">';
  html += '<div style="height:100%;width:' + progress + '%;background:linear-gradient(90deg,#4caf50,#8bc34a);border-radius:2px;transition:width 0.3s;"></div></div></div>';
  html += '<div style="overflow-y:auto;max-height:calc(100% - 120px);">';
  if (_tasks.length === 0) {
    html += '<div style="padding:20px;text-align:center;color:rgba(255,255,255,0.4);font-size:12px;">暂无任务，AI 回复中的任务计划将自动提取</div>';
  } else {
    _tasks.forEach(function(task) {
      var isCompleted = task.status === 'completed';
      html += '<div style="padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.04);cursor:pointer;" onclick="_toggleTask(\'' + task.id + '\')">';
      html += '<div style="display:flex;align-items:center;gap:8px;">';
      html += '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="' + (isCompleted ? '#4caf50' : 'rgba(255,255,255,0.3)') + '" stroke-width="2" style="flex-shrink:0;">';
      if (isCompleted) { html += '<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'; }
      else { html += '<rect x="3" y="3" width="18" height="18" rx="2"/>'; }
      html += '</svg>';
      html += '<span style="color:' + (isCompleted ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.85)') + ';font-size:12px;' + (isCompleted ? 'text-decoration:line-through;' : '') + '">' + _escapeHtml(task.title) + '</span>';
      html += '</div></div>';
    });
  }
  html += '</div>';
  html += '<div style="padding:8px;border-top:1px solid rgba(255,255,255,0.06);">';
  html += '<button onclick="_addTask()" style="width:100%;padding:6px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:rgba(255,255,255,0.7);font-size:12px;cursor:pointer;">+ 添加任务</button>';
  html += '</div>';
  return html;
}

function _addTask() {
  _showInput(i18n.t('session.addTaskTitle'), i18n.t('session.addTaskInput'), '', function(title) {
    if (!title || !title.trim()) return;
    _tasks.push({ id: 'task_' + Date.now(), title: title.trim(), status: 'pending', progress: 0 });
    _refreshCurrentPanel();
  });
}
function _toggleTask(taskId) {
  var task = _tasks.find(function(t) { return t.id === taskId; });
  if (!task) return;
  task.status = task.status === 'completed' ? 'pending' : 'completed';
  _refreshCurrentPanel();
}

// ===== 思考面板 =====
function _renderThinkingPanel() {
  var html = '';
  html += '<div class="thinking-panel">';
  // 标题栏
  html += '<div style="padding:8px 12px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,0.06);">';
  html += '<span style="color:rgba(255,255,255,0.8);font-size:13px;font-weight:600;display:flex;align-items:center;gap:6px;">';
  html += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ff9a4a" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/><circle cx="12" cy="12" r="3"/><path d="M12 2v4"/><path d="M12 18v4"/><path d="M4.93 4.93l2.83 2.83"/><path d="M16.24 16.24l2.83 2.83"/><path d="M2 12h4"/><path d="M18 12h4"/></svg>';
  html += '思考过程</span>';
  html += '<button onclick="_clearThinking()" style="background:none;border:none;color:rgba(255,255,255,0.4);font-size:11px;cursor:pointer;">清除</button></div>';

  var thinkingList = _thinkingEntries.filter(function(e) { return !e.isWorking; });
  var workingList = _thinkingEntries.filter(function(e) { return e.isWorking; });

  // 思考中区域
  html += '<div class="thinking-section">';
  html += '<div class="thinking-section-header">';
  html += '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/><circle cx="12" cy="12" r="3"/></svg>';
  html += '思考中</div>';
  html += '<div class="thinking-content-box">';
  if (thinkingList.length === 0) {
    html += '<div class="thinking-empty">暂无思考记录</div>';
  } else {
    thinkingList.forEach(function(e) {
      html += '<div class="thinking-entry">';
      html += '<div class="thinking-entry-time">' + _escapeHtml(e.timestamp) + '</div>';
      html += '<div>' + _escapeHtml(e.content) + '</div>';
      html += '</div>';
    });
  }
  html += '</div></div>';

  // 工作中区域
  html += '<div class="working-section">';
  html += '<div class="working-section-header">';
  html += '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>';
  html += '工作中</div>';
  html += '<div class="working-content-box">';
  if (workingList.length === 0) {
    html += '<div class="thinking-empty">暂无工作记录</div>';
  } else {
    workingList.forEach(function(e) {
      html += '<div class="thinking-entry">';
      html += '<div class="thinking-entry-time">' + _escapeHtml(e.timestamp) + '</div>';
      html += '<div style="color:#4ade80;">' + _escapeHtml(e.content) + '</div>';
      html += '</div>';
    });
  }
  html += '</div></div>';

  html += '</div>'; // .thinking-panel
  return html;
}
function _padZero(n) { return n < 10 ? '0' + n : '' + n; }
function _addThinkingEntry(content, isWorking) {
  var now = new Date();
  var ts = _padZero(now.getHours()) + ':' + _padZero(now.getMinutes()) + ':' + _padZero(now.getSeconds());
  _thinkingEntries.push({ content: content || '', timestamp: ts, isWorking: !!isWorking });
  if (_thinkingEntries.length > 100) { _thinkingEntries = _thinkingEntries.slice(-100); }
  _refreshCurrentPanel();
}
function _clearThinking() { _thinkingEntries = []; _refreshCurrentPanel(); }

// ===== 文件变更面板 =====
function _renderFilePanel() {
  var html = '';
  html += '<div class="file-panel">';
  // 标题栏
  html += '<div style="padding:10px 12px;border-bottom:1px solid rgba(255,255,255,0.06);">';
  html += '<div style="display:flex;align-items:center;gap:6px;">';
  html += SVG_ICONS['file-text'];
  html += '<span style="color:var(--text-primary,rgba(255,255,255,0.8));font-size:13px;font-weight:600;">文件变更</span>';
  html += '<span class="file-summary-added stat-add">+' + _fileChanges.totalAdded + '</span>';
  html += '<span class="file-summary-deleted stat-del">-' + _fileChanges.totalDeleted + '</span></div></div>';
  html += '<div style="overflow-y:auto;flex:1;min-height:0;">';
  if (_fileChanges.files.length === 0) {
    html += '<div style="padding:20px;text-align:center;color:rgba(255,255,255,0.4);font-size:12px;">暂无文件变更</div>';
  } else {
    _fileChanges.files.forEach(function(fc, index) {
      var isExpanded = _expandedFileDiff === index;
      var iconSvg = fc.type === 'added' ? SVG_ICONS['file-plus'] : fc.type === 'deleted' ? SVG_ICONS['file-x'] : SVG_ICONS['file-edit'];
      var iconColor = fc.type === 'added' ? 'var(--success)' : fc.type === 'deleted' ? 'var(--danger)' : 'var(--warning)';
      html += '<div style="border-bottom:1px solid rgba(255,255,255,0.04);">';
      html += '<div style="padding:8px 12px;cursor:pointer;display:flex;align-items:center;gap:8px;" onclick="_toggleFileDiff(' + index + ')">';
      html += '<span class="fc-icon" style="color:' + iconColor + ';flex-shrink:0;">' + iconSvg + '</span>';
      html += '<span class="fc-path" style="color:var(--text-primary,rgba(255,255,255,0.85));font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + _escapeHtml(fc.path) + '</span>';
      html += '<span class="fc-diff-stats" style="color:var(--success);font-size:10px;flex-shrink:0;">+' + fc.added + '</span>';
      html += '<span class="fc-diff-stats" style="color:var(--danger);font-size:10px;flex-shrink:0;">-' + fc.deleted + '</span>';
      html += '<span style="font-size:9px;padding:1px 4px;border-radius:2px;background:' + iconColor + '22;color:' + iconColor + ';flex-shrink:0;">' + (fc.type || '修改') + '</span>';
      html += SVG_ICONS['chevron-down'].replace('width="16" height="16"', 'width="10" height="10"').replace('stroke="currentColor"', 'stroke="rgba(255,255,255,0.3)"').replace('/>', ' style="flex-shrink:0;transform:' + (isExpanded ? 'rotate(180deg)' : '') + ';transition:transform 0.2s;" />');
      html += '</div>';
      if (isExpanded) { html += '<div style="padding:0 12px 8px 12px;">' + _renderDiffViewer(fc) + '</div>'; }
      html += '</div>';
    });
  }
  html += '</div>'; // inner scroll
  html += '<div style="padding:8px;border-top:1px solid rgba(255,255,255,0.06);">';
  html += '<button onclick="_clearFileChanges()" style="width:100%;padding:6px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:rgba(255,255,255,0.5);font-size:12px;cursor:pointer;">清除变更记录</button></div>';
  html += '</div>'; // .file-panel
  return html;
}
function _addFileChange(path, added, deleted, diff, type) {
  _fileChanges.files.push({ path: path || '', added: added || 0, deleted: deleted || 0, diff: diff || '', type: type || 'modified' });
  _fileChanges.totalAdded += (added || 0); _fileChanges.totalDeleted += (deleted || 0);
  _refreshCurrentPanel();
}
function _clearFileChanges() { _fileChanges = {files: [], totalAdded: 0, totalDeleted: 0}; _expandedFileDiff = null; _refreshCurrentPanel(); }
function _toggleFileDiff(index) { _expandedFileDiff = _expandedFileDiff === index ? null : index; _refreshCurrentPanel(); }

function _renderDiffViewer(fileChange) {
  var diff = fileChange.diff || '';
  if (!diff) return '<div style="color:rgba(255,255,255,0.4);font-size:11px;padding:8px;text-align:center;">无差异内容</div>';
  var ext = (fileChange.path || '').split('.').pop().toLowerCase();
  var html = '<div class="diff-viewer">';
  html += '<div class="diff-header">';
  html += '<span class="diff-header-name">' + _escapeHtml(fileChange.path || 'unknown') + '</span>';
  html += '<span style="color:#4ade80;">+<b>' + (fileChange.added || 0) + '</b></span> <span style="color:#f87171;">-<b>' + (fileChange.deleted || 0) + '</b></span>';
  html += '</div>';
  html += '<div class="diff-body">';
  var lines = diff.split('\n');
  // ★ 块级渲染：将连续的同类型行分组
  var blocks = [];
  var currentBlock = null;
  var lineNum = 0;
  lines.forEach(function(line) {
    var type;
    if (line.indexOf('@@') === 0) {
      type = 'hunk';
    } else if (line.indexOf('+') === 0 && line.indexOf('+++') !== 0) {
      type = 'added';
      lineNum++;
    } else if (line.indexOf('-') === 0 && line.indexOf('---') !== 0) {
      type = 'removed';
    } else {
      type = 'context';
    }
    if (type === 'hunk' || type === 'context') {
      if (currentBlock) { blocks.push(currentBlock); currentBlock = null; }
      blocks.push({ type: type, lines: [line] });
    } else if (type === 'added') {
      if (!currentBlock || currentBlock.type !== 'added') {
        if (currentBlock) blocks.push(currentBlock);
        currentBlock = { type: 'added', lines: [], count: 0 };
      }
      currentBlock.lines.push(line);
      currentBlock.count++;
    } else if (type === 'removed') {
      if (!currentBlock || currentBlock.type !== 'removed') {
        if (currentBlock) blocks.push(currentBlock);
        currentBlock = { type: 'removed', lines: [], count: 0 };
      }
      currentBlock.lines.push(line);
      currentBlock.count++;
    }
  });
  if (currentBlock) blocks.push(currentBlock);

  // ★ 渲染块级diff
  blocks.forEach(function(block) {
    if (block.type === 'hunk') {
      block.lines.forEach(function(line) {
        var escaped = _escapeHtml(line);
        if (ext === 'py' || ext === 'js' || ext === 'ts' || ext === 'html' || ext === 'css') {
          escaped = _highlightCode(escaped, ext);
        }
        html += '<div class="diff-line unchanged"><span class="diff-line-num"></span><span class="diff-line-content" style="color:#6495ed;">' + escaped + '</span></div>';
      });
    } else if (block.type === 'context') {
      block.lines.forEach(function(line) {
        var escaped = _escapeHtml(line);
        if (ext === 'py' || ext === 'js' || ext === 'ts' || ext === 'html' || ext === 'css') {
          escaped = _highlightCode(escaped, ext);
        }
        html += '<div class="diff-line unchanged"><span class="diff-line-num"></span><span class="diff-line-content">' + escaped + '</span></div>';
      });
    } else if (block.type === 'added') {
      var indicator = block.count > 1 ? ('+ ' + block.count + ' 行') : '+ 新增';
      html += '<div class="diff-block added">';
      html += '<div class="diff-block-indicator">' + indicator + '</div>';
      block.lines.forEach(function(line) {
        var escaped = _escapeHtml(line);
        if (ext === 'py' || ext === 'js' || ext === 'ts' || ext === 'html' || ext === 'css') {
          escaped = _highlightCode(escaped, ext);
        }
        html += '<div class="diff-line added"><span class="diff-line-num">+</span><span class="diff-line-content">' + escaped + '</span></div>';
      });
      html += '</div>';
    } else if (block.type === 'removed') {
      var indicator = block.count > 1 ? ('- ' + block.count + ' 行') : '- 删除';
      html += '<div class="diff-block removed">';
      html += '<div class="diff-block-indicator">' + indicator + '</div>';
      block.lines.forEach(function(line) {
        var escaped = _escapeHtml(line);
        if (ext === 'py' || ext === 'js' || ext === 'ts' || ext === 'html' || ext === 'css') {
          escaped = _highlightCode(escaped, ext);
        }
        html += '<div class="diff-line deleted"><span class="diff-line-num">-</span><span class="diff-line-content">' + escaped + '</span></div>';
      });
      html += '</div>';
    }
  });
  html += '</div></div>';
  return html;
}

// ★ W1 说明：diff 视图专用「行级」代码高亮。
// 与 `renderMarkdown`（整块 markdown，块级 hljs）不同——diff 行带 + / - 前缀且逐行渲染，
// 无法用块级 hljs.highlight（会丢失多行字符串/注释上下文），故保留此正则实现。
// 语言覆盖（11 种）与 hljs 扩展后（js/py/go/rust/java/cpp/sql/sh/css/xml/json/ts）保持对齐。
// 这不是"散点管线"，而是 diff 场景的合法行级实现。
function _highlightCode(text, lang) {
  var keywords = {
    py: ['def','class','import','from','return','if','else','elif','for','while','try','except','with','as','yield','lambda','pass','break','continue','and','or','not','in','is','None','True','False','self','async','await','raise','finally','global','nonlocal'],
    js: ['function','const','let','var','return','if','else','for','while','try','catch','throw','new','this','class','extends','import','export','default','async','await','typeof','instanceof','null','undefined','true','false','switch','case','break','continue','yield'],
    ts: ['function','const','let','var','return','if','else','for','while','try','catch','throw','new','this','class','extends','import','export','default','async','await','typeof','instanceof','null','undefined','true','false','interface','type','enum','readonly'],
    html: ['div','span','button','input','html','head','body','script','style','link','meta','title','a','p','h1','h2','h3','img','table','tr','td','th','ul','ol','li','form','select','option','textarea','label'],
    css: ['color','background','border','margin','padding','width','height','display','position','flex','grid','font','text','align','justify','overflow','opacity','transform','transition','animation','box-shadow','border-radius','z-index'],
    go: ['func','package','import','return','if','else','for','range','switch','case','default','defer','go','chan','select','map','struct','interface','type','var','const','nil','true','false','break','continue','make','new','append','len','cap','error','string','int','bool','byte','float64'],
    rust: ['fn','let','mut','pub','use','mod','struct','enum','impl','trait','match','if','else','loop','while','for','in','return','self','Self','where','as','ref','move','unsafe','extern','crate','super','const','static','type','true','false','Some','None','Ok','Err','Vec','String','Option','Result','Box'],
    java: ['public','private','protected','class','interface','extends','implements','new','return','if','else','for','while','switch','case','default','break','continue','try','catch','finally','throw','throws','import','package','static','final','abstract','synchronized','volatile','transient','void','int','long','double','float','boolean','char','String','null','true','false','this','super','enum'],
    cpp: ['include','using','namespace','class','struct','public','private','protected','virtual','override','const','static','template','typename','auto','decltype','new','delete','nullptr','this','return','if','else','for','while','switch','case','default','break','continue','try','catch','throw','int','long','double','float','bool','char','void','true','false','std','vector','string','map','shared_ptr','unique_ptr'],
    sql: ['SELECT','FROM','WHERE','INSERT','UPDATE','DELETE','CREATE','ALTER','DROP','TABLE','INDEX','INTO','VALUES','SET','JOIN','LEFT','RIGHT','INNER','OUTER','ON','AND','OR','NOT','IN','LIKE','BETWEEN','ORDER','BY','GROUP','HAVING','LIMIT','OFFSET','ASC','DESC','NULL','IS','AS','COUNT','SUM','AVG','MAX','MIN','DISTINCT','UNION','ALL','EXISTS','CASE','WHEN','THEN','ELSE','END','PRIMARY','KEY','FOREIGN','REFERENCES','CASCADE','DEFAULT','CHECK','UNIQUE','IF','BEGIN','END','COMMIT','ROLLBACK','TRANSACTION'],
    sh: ['echo','cd','ls','mkdir','rm','cp','mv','cat','grep','sed','awk','find','chmod','chown','export','source','sudo','apt','pip','npm','git','docker','curl','wget','tar','gzip','ssh','scp','if','then','else','elif','fi','for','do','done','while','case','esac','exit','return','set','unset','read','printf','exec','kill','ps','top','tail','head','sort','uniq','wc','tee','xargs','cut','tr','diff','patch','ln','stat','du','df','mount','umount','env','which','type','alias','unalias','history','clear','true','false','test']
  };
  var kw = keywords[lang] || [];
  // 高亮关键词
  kw.forEach(function(k) {
    var re = new RegExp('\\b(' + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')\\b', 'gi');
    text = text.replace(re, '<span style="color:#c792ea;">$1</span>');
  });
  // 高亮字符串
  text = text.replace(/(["'`])(?:(?!\1)[^\\]|\\.)*\1/g, '<span style="color:#c3e88d;">$&</span>');
  // 高亮数字
  text = text.replace(/\b(\d+\.?\d*)\b/g, '<span style="color:#f78c6c;">$1</span>');
  // 高亮注释
  text = text.replace(/(#.*$)/gm, '<span style="color:#546e7a;">$1</span>');
  text = text.replace(/(\/\/.*$)/gm, '<span style="color:#546e7a;">$1</span>');
  return text;
}

// ===== 自动从AI消息中提取内容 =====
function _extractTasksFromAI(response) {
  if (!response) return;
  var text = typeof response === 'string' ? response : (response.innerHTML || response.textContent || '');
  if (!text) return;
  var taskMarkerRe = /\[TASK:\s*([^\]]+)\]/gi, match;
  while ((match = taskMarkerRe.exec(text)) !== null) {
    var title = match[1].trim();
    if (title && !_tasks.some(function(t) { return t.title === title; })) {
      _tasks.push({ id: 'task_' + Date.now() + '_' + _tasks.length, title: title, status: 'pending', progress: 0 });
    }
  }
  var mdTaskRe = /-\s*\[([ xX✓✔])\]\s*([^\n]+)/g;
  while ((match = mdTaskRe.exec(text)) !== null) {
    var isDone = match[1].toLowerCase() === 'x' || match[1] === '✓' || match[1] === '✔';
    var mdTitle = match[2].trim();
    if (mdTitle && !_tasks.some(function(t) { return t.title === mdTitle; })) {
      _tasks.push({ id: 'task_' + Date.now() + '_' + _tasks.length, title: mdTitle, status: isDone ? 'completed' : 'pending', progress: isDone ? 100 : 0 });
    }
  }
}

function _scanAIResponseForPanel(responseHTML) {
  if (!responseHTML) return;
  _extractTasksFromAI(responseHTML);
  var thinkingRe = /\[THINKING:\s*([^\]]*)\]/gi, match;
  while ((match = thinkingRe.exec(responseHTML)) !== null) { _addThinkingEntry(match[1].trim(), false); }
  var workingRe = /\[WORKING:\s*([^\]]*)\]/gi;
  while ((match = workingRe.exec(responseHTML)) !== null) { _addThinkingEntry(match[1].trim(), true); }
  var diffBlockRe = /```diff\s*\n([\s\S]*?)```/g;
  while ((match = diffBlockRe.exec(responseHTML)) !== null) {
    var diffContent = match[1];
    var lines = diffContent.split('\n');
    var addedLines = lines.filter(function(l) { return l.indexOf('+') === 0 && l.indexOf('+++') !== 0; }).length;
    var deletedLines = lines.filter(function(l) { return l.indexOf('-') === 0 && l.indexOf('---') !== 0; }).length;
    _addFileChange('unknown', addedLines, deletedLines, diffContent, 'modified');
  }
  _refreshCurrentPanel();
}

// ===== Bridge 集成 =====
function _handleVisualizerMessage(data) {
  if (!data || !data.type) return;
  var now = Date.now();
  switch (data.type) {
    case 'skill_started':
      _skillStatuses[data.skillId] = { status: 'running', startTime: now, endTime: null, output: '' };
      _skillInProgress = data.skillId;
      if (_skillTimeout) clearTimeout(_skillTimeout);
      _skillTimeout = setTimeout(function() { _skillInProgress = null; _refreshCurrentPanel(); }, 30000);
      _refreshCurrentPanel(); break;
    case 'skill_completed':
      _skillStatuses[data.skillId] = { status: 'completed', startTime: _skillStatuses[data.skillId] ? _skillStatuses[data.skillId].startTime : now, endTime: now, output: data.output || '' };
      _skillOutputs[data.skillId] = { output: data.output || '', timestamp: new Date().toISOString() };
      _skillInProgress = null; if (_skillTimeout) clearTimeout(_skillTimeout);
      _refreshCurrentPanel(); break;
    case 'skill_failed':
      _skillStatuses[data.skillId] = { status: 'failed', startTime: _skillStatuses[data.skillId] ? _skillStatuses[data.skillId].startTime : now, endTime: now, output: data.error || '执行失败' };
      _skillInProgress = null; if (_skillTimeout) clearTimeout(_skillTimeout);
      _refreshCurrentPanel(); break;
    case 'task_updated':
      if (data.tasks && Array.isArray(data.tasks)) _tasks = data.tasks;
      _refreshCurrentPanel(); break;
    case 'thinking_added':
      _addThinkingEntry(data.content, data.isWorking); break;
    case 'file_changed':
      _addFileChange(data.path, data.added, data.deleted, data.diff, data.type); break;
    case 'dashboard_state':
      // 映射 Python 后端字段到前端字段
      if (data.active_skills) {
        data.active_skills.forEach(function(s) {
          _skillStatuses[s.skill_id] = { status: s.status, startTime: Date.parse(s.started_at), endTime: s.completed_at ? Date.parse(s.completed_at) : null, output: s.output_summary || '' };
          if (s.output_summary) _skillOutputs[s.skill_id] = { output: s.output_summary, timestamp: s.completed_at || new Date().toISOString() };
        });
      }
      if (data.recent_skills) {
        data.recent_skills.forEach(function(s) {
          _skillStatuses[s.skill_id] = { status: s.status, startTime: Date.parse(s.started_at), endTime: s.completed_at ? Date.parse(s.completed_at) : null, output: s.output_summary || '' };
          if (s.output_summary) _skillOutputs[s.skill_id] = { output: s.output_summary, timestamp: s.completed_at || new Date().toISOString() };
        });
      }
      if (data.tasks && Array.isArray(data.tasks)) {
        _tasks = data.tasks.map(function(t) { return { id: t.task_id, title: t.title, status: t.status, progress: t.progress || 0 }; });
      }
      if (data.thinking && Array.isArray(data.thinking)) {
        _thinkingEntries = data.thinking.map(function(t) { return { content: t.content, timestamp: t.timestamp ? t.timestamp.substring(11, 19) : '', isWorking: t.is_working }; });
      }
      if (data.file_changes) {
        _fileChanges = {files: [], totalAdded: data.file_changes.total_added || 0, totalDeleted: data.file_changes.total_deleted || 0};
        if (data.file_changes.files) {
          data.file_changes.files.forEach(function(f) {
            _fileChanges.files.push({ path: f.file_path, added: f.lines_added, deleted: f.lines_deleted, diff: f.diff_content || '', type: f.change_type });
          });
        }
      }
      _refreshCurrentPanel(); break;
  }
}

// ===== 辅助函数 =====
function _switchToolPanelTab(tabId) { if (tabId) switchToolPanel(tabId); }
function _openRightPanel() { var panel = document.getElementById('rightPanel'); if (panel) { panel.classList.add('open'); renderToolPanelTabs(); _refreshCurrentPanel();
  // ★ v4.1.31: typewriterfield 已彻底移除，不再需要裁剪
} }
function _closeRightPanel() { var panel = document.getElementById('rightPanel'); if (panel) panel.classList.remove('open');
  // ★ v4.1.31: typewriterfield 已彻底移除
}
function _toggleRightPanel() { var panel = document.getElementById('rightPanel'); if (!panel) return; if (panel.classList.contains('open')) _closeRightPanel(); else _openRightPanel(); }

// ===== 初始化 =====
function _initVisualizerPanel() {
  _skillStatuses = _skillStatuses || {};
  _skillOutputs = _skillOutputs || {};
  _tasks = _tasks || [];
  _thinkingEntries = _thinkingEntries || [];
  _fileChanges = _fileChanges || {files: [], totalAdded: 0, totalDeleted: 0};
  _expandedSkillOutput = null;
  _expandedFileDiff = null;
  if (typeof window._bridgeMessageHandler === 'undefined') {
    window._bridgeMessageHandler = function(msg) {
      try { var data = typeof msg === 'string' ? JSON.parse(msg) : msg; if (data && data._visualizer) _handleVisualizerMessage(data); } catch(e) {}
    };
  }
  _refreshCurrentPanel();
}

// ★ 在 AI 消息处理完毕后自动扫描
(function() {
  var _origOnStreamEnd = onStreamEnd;
  if (typeof _origOnStreamEnd === 'function') {
    onStreamEnd = function(fullText) { _origOnStreamEnd(fullText); try { if (fullText) _scanAIResponseForPanel(fullText); } catch(e) {} };
  }
})();
(function() {
  var _origAppendMsg = appendMsg;
  if (typeof _origAppendMsg === 'function') {
    appendMsg = function(type, text) { _origAppendMsg(type, text); if (type === 'ai' && text && !_streamActive) { try { setTimeout(function() { _scanAIResponseForPanel(text); }, 50); } catch(e) {} } };
  }
})();
setTimeout(function() { _initVisualizerPanel(); }, 200);

// ============================================================

function _renderSessionManager() {
  var html = '';
  // 搜索栏
  html += '<div style="padding:8px 10px;">';
  html += '<input type="text" class="session-search-input" id="sessionSearchInput" placeholder="搜索会话..." oninput="_filterSessions(this.value)" style="width:100%;padding:6px 10px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.08);border-radius:6px;color:#ccc;font-size:11px;outline:none;box-sizing:border-box;">';
  html += '</div>';

  // 操作栏
  html += '<div style="padding:4px 10px 8px;display:flex;gap:6px;">';
  html += '<button class="session-action-btn primary" onclick="_showNewSessionDialog()" style="flex:1;">+ 新建会话</button>';
  html += '<button class="session-action-btn" onclick="_saveCurrentSession()" title="保存当前会话">保存</button>';
  html += '<button class="session-action-btn" onclick="_autoSaveToggle()" id="autoSaveBtn" title="自动保存">自动</button>';
  html += '</div>';

  // 会话列表
  html += '<div class="session-manager-list" id="sessionManagerList" style="flex:1;overflow-y:auto;">';
  html += _renderSessionListItems();
  html += '</div>';

  // 底部统计
  html += '<div style="padding:6px 10px;font-size:10px;color:rgba(255,255,255,0.25);border-top:1px solid rgba(255,255,255,0.04);">';
  html += '共 ' + _sessionList.length + ' 个会话 | 当前: ' + (_currentSessionId || '默认');
  html += '</div>';

  return html;
}

function _renderSessionListItems(filter) {
  var html = '';
  var sessions = _sessionList || [];
  if (filter) {
    var f = filter.toLowerCase();
    sessions = sessions.filter(function(s) {
      return (s.title || '').toLowerCase().indexOf(f) >= 0 || (s.id || '').toLowerCase().indexOf(f) >= 0;
    });
  }
  if (!sessions.length) {
    html += '<div style="padding:20px;text-align:center;color:rgba(255,255,255,0.2);font-size:11px;">暂无会话</div>';
    return html;
  }
  sessions.forEach(function(s) {
    var isActive = s.id === _currentSessionId;
    var msgCount = s.msg_count || 0;
    var timeStr = (s.updated_at || s.created_at || '').substring(5, 16);
    html += '<div class="session-mgr-item' + (isActive ? ' active' : '') + '" onclick="_restoreSession(\'' + s.id + '\')">';
    html += '<div class="session-mgr-icon">' + (isActive ? '●' : '○') + '</div>';
    html += '<div class="session-mgr-info">';
    html += '<div class="session-mgr-title">' + (s.title || '未命名') + '</div>';
    html += '<div class="session-mgr-meta">' + msgCount + '条 · ' + timeStr + '</div>';
    html += '</div>';
    html += '<div class="session-mgr-actions">';
    html += '<button class="session-mgr-btn" onclick="event.stopPropagation();_renameSession(\'' + s.id + '\')" title="重命名">' + SVG_ICONS['square-pen'] + '</button>';
    html += '<button class="session-mgr-btn danger" onclick="event.stopPropagation();_deleteSession(\'' + s.id + '\')" title="删除">×</button>';
    html += '</div>';
    html += '</div>';
  });
  return html;
}

function _filterSessions(keyword) {
  var list = document.getElementById('sessionManagerList');
  if (list) list.innerHTML = _renderSessionListItems(keyword);
}

function _showNewSessionDialog() {
  var defaultName = '会话 ' + new Date().toLocaleString('zh-CN', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
  _showInput(i18n.t('session.newDialogTitle'), i18n.t('session.newDialogInput'), defaultName, function(name) {
    if (name && name.trim()) {
      _createSession(name.trim());
    }
  });
}

function _createSession(name) {
  _saveChatToStorage(_currentSessionId);
  var newId = 'session_' + Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 6);
  _currentSessionId = newId;
  _sessionList.unshift({
    id: newId,
    title: name,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    msg_count: 0
  });
  clearOutput();
  _persistSessions();
  if (typeof window._callPython === 'function') {
    try {
      if (/[?&]panel=1/.test(window.location.search)) {
        window._callPython('sendMessage', '__new_session__');
      } else {
        window._callPython('sendMessage', '__session__:' + newId);
      }
    } catch(e) {
      window._callPython('sendMessage', '__session__:' + newId);
    }
  }
  _refreshSessionUI();
  showToast('会话已创建: ' + name);
}

function _renameSession(sessionId) {
  var session = _sessionList.find(function(s) { return s.id === sessionId; });
  if (!session) return;
  _showInput(i18n.t('session.renameDialogTitle'), i18n.t('session.renameDialogInput'), session.title || '', function(newName) {
    if (newName && newName.trim()) {
      session.title = newName.trim();
      session.updated_at = new Date().toISOString();
      _persistSessions();
      _refreshSessionUI();
      showToast(i18n.t('session.renamedToast'));
    }
  });
}

function _deleteSession(sessionId) {
  _showConfirm(i18n.t('session.deleteDialogTitle'), i18n.t('session.deleteDialogMsg'), function() {
    _sessionList = _sessionList.filter(function(s) { return s.id !== sessionId; });
    // 清除该会话的存储
    try { localStorage.removeItem('mimo_chat_' + sessionId); } catch(e) {}
  _persistSessions();
  // 如果删除的是当前会话，切换到最近会话
  if (_currentSessionId === sessionId) {
    if (_sessionList.length > 0) {
      _restoreSession(_sessionList[0].id);
    } else {
      _currentSessionId = '';
      clearOutput();
    }
  }
  _refreshSessionUI();
  // 通知 Python 删除
  if (typeof window._callPython === 'function') {
    window._callPython('deleteDbSession', sessionId);
  }
  showToast('会话已删除');
  }); // _showConfirm callback
}

function _saveCurrentSession() {
  if (!_currentSessionId) return;
  var saved = _saveChatToStorage(_currentSessionId);
  if (saved) {
    showToast('会话已保存 (' + saved + ' 条消息)');
  } else {
    showToast('无消息可保存');
  }
}

function _saveChatToStorage(sessionId) {
  if (!sessionId) return 0;
  var area = document.getElementById('outputMessages');
  if (!area) return 0;
  var messages = [];
  var blocks = area.querySelectorAll('.msg-block');
  blocks.forEach(function(block) {
    var isUser = block.classList.contains('msg-user');
    var isAi = block.classList.contains('msg-ai');
    if (isUser) {
      var bubble = block.querySelector('.msg-bubble');
      if (bubble) messages.push({role: 'user', content: bubble.innerHTML, time: Date.now()});
    } else if (isAi) {
      var content = block.querySelector('.ai-content');
      var thinking = block.querySelector('.thinking-inline-body');
      var msg = {role: 'ai', content: content ? content.innerHTML : '', time: Date.now()};
      if (thinking) msg.thinking = thinking.innerHTML;
      messages.push(msg);
    }
  });
  if (messages.length === 0) return 0;
  try {
    localStorage.setItem('mimo_chat_' + sessionId, JSON.stringify(messages));
  } catch(e) {
    console.warn('[Session] 保存失败:', e);
  }
  // 更新会话元数据
  var session = _sessionList.find(function(s) { return s.id === sessionId; });
  if (session) {
    session.msg_count = messages.length;
    session.updated_at = new Date().toISOString();
  }
  _persistSessions();
  return messages.length;
}

function _restoreSession(sessionId) {
  // 先保存当前会话
  if (_currentSessionId && _currentSessionId !== sessionId) {
    _saveChatToStorage(_currentSessionId);
  }
  _currentSessionId = sessionId;
  var area = document.getElementById('outputMessages');
  if (!area) return;
  area.innerHTML = '';
  window._globalMsgCount = 0;
  _streamActive = false;
  _streamRendered = false;

  // 从 localStorage 恢复
  var saved = null;
  try {
    var raw = localStorage.getItem('mimo_chat_' + sessionId);
    if (raw) saved = JSON.parse(raw);
  } catch(e) {}
  if (saved && saved.length > 0) {
    saved.forEach(function(msg) {
      if (msg.role === 'user') {
        var block = document.createElement('div');
        block.className = 'msg-block msg-user';
        block.dataset.msgIndex = window._globalMsgCount++;
        block.innerHTML = '<div class="msg-bubble">' + (msg.content || '') + '</div>';
        area.appendChild(block);
      } else if (msg.role === 'ai') {
        var block = document.createElement('div');
        block.className = 'msg-block msg-ai';
        block.dataset.msgIndex = window._globalMsgCount++;
        if (msg.thinking) {
          var thinkDiv = document.createElement('div');
          thinkDiv.className = 'thinking-inline';
          thinkDiv.innerHTML = '<div class="thinking-inline-header" onclick="toggleThinkingInline(this)"><span class="think-icon">' + SVG_ICONS['chevron-down'] + '</span><span class="think-badge">思考</span></div><div class="thinking-inline-body">' + msg.thinking + '</div>';
          block.appendChild(thinkDiv);
        }
        var contentDiv = document.createElement('div');
        contentDiv.className = 'ai-content';
        contentDiv.innerHTML = msg.content || '';
        block.appendChild(contentDiv);
        area.appendChild(block);
      }
    });
    area.scrollTop = area.scrollHeight;
  } else {
    // 没有本地缓存，尝试从 Python 后端加载
    if (typeof window._callPython === 'function') {
      window._callPython('getDbMessages', sessionId, function(result) {
        try {
          if (typeof result === 'string') result = JSON.parse(result);
          if (result && result.messages) {
            result.messages.forEach(function(msg) {
              appendMsg(msg.role === 'user' ? 'user' : 'ai', msg.content || '');
            });
          }
        } catch(e) { console.warn('[Session] 恢复失败:', e); }
      });
    }
  }
  _refreshSessionUI();
  // 通知 Python
  if (typeof window._callPython === 'function') {
    window._callPython('sendMessage', '__session__:' + sessionId);
  }
  showToast('已切换到: ' + (_sessionList.find(function(s){return s.id===sessionId;}) || {}).title || sessionId);
}

function _persistSessions() {
  try {
    localStorage.setItem('mimo_sessions_list', JSON.stringify(_sessionList));
  } catch(e) {}
  _sessionsDirty = true;
}

function _loadSessionsFromStorage() {
  try {
    var raw = localStorage.getItem('mimo_sessions_list');
    if (raw) _sessionList = JSON.parse(raw);
  } catch(e) { _sessionList = []; }
}

function _refreshSessionUI() {
  // 更新工具面板中的会话列表
  var list = document.getElementById('sessionManagerList');
  if (list) list.innerHTML = _renderSessionListItems();
  // 更新会话栏标签
  var label = document.getElementById('sessionLabel');
  if (label) {
    var session = _sessionList.find(function(s) { return s.id === _currentSessionId; });
    label.textContent = i18n.t('session.current') + ' ' + (session ? session.title : (_currentSessionId || i18n.t('session.defaultName')));
  }
}

// ★ 自动保存
function _autoSaveToggle() {
  if (_autoSaveTimer) {
    clearInterval(_autoSaveTimer);
    _autoSaveTimer = null;
    var btn = document.getElementById('autoSaveBtn');
    if (btn) { btn.classList.remove('active'); btn.textContent = '自动'; }
    showToast('自动保存已关闭');
  } else {
    _autoSaveTimer = setInterval(function() {
      if (_currentSessionId) {
        var count = _saveChatToStorage(_currentSessionId);
        if (count > 0) console.log('[AutoSave] ' + _currentSessionId + ': ' + count + ' 条消息');
      }
    }, 30000);
    var btn = document.getElementById('autoSaveBtn');
    if (btn) { btn.classList.add('active'); btn.innerHTML = '自动 ' + SVG_ICONS.check; }
    showToast('自动保存已开启 (30s)');
  }
}

// ★ 页面加载时恢复会话
function _initSessionManager() {
  _loadSessionsFromStorage();
  var _isPanelMode = (function() {
    try { return /[?&]panel=1/.test(window.location.search); } catch(e) { return false; }
  })();
  if (_isPanelMode) {
    _currentSessionId = 'session_' + Date.now().toString(36);
    _sessionList.unshift({
      id: _currentSessionId,
      title: '新会话',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      msg_count: 0
    });
    _persistSessions();
  } else if (_sessionList.length > 0) {
    _currentSessionId = _sessionList[0].id;
    _restoreSession(_currentSessionId);
  } else {
    _currentSessionId = 'session_' + Date.now().toString(36);
    _sessionList.push({
      id: _currentSessionId,
      title: '默认会话',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      msg_count: 0
    });
    _persistSessions();
  }
  _autoSaveTimer = setInterval(function() {
    if (_currentSessionId) {
      _saveChatToStorage(_currentSessionId);
    }
  }, 30000);
  console.log('[Session] 会话管理器初始化完成, 共 ' + _sessionList.length + ' 个会话 (panel=' + _isPanelMode + ')');
}

// ===== ★ P11: 消息搜索系统 =====
function _openSearchPanel() {
  var overlay = document.getElementById('searchOverlay');
  if (overlay) {
    overlay.classList.add('show');
    var input = document.getElementById('searchInput');
    if (input) { input.value = ''; setTimeout(function() { input.focus(); }, 100); }
    // 更新会话过滤选项
    _updateSearchSessionFilter();
    document.getElementById('searchResults').innerHTML = '<div class="search-empty">输入关键词开始搜索...</div>';
    document.getElementById('searchResultCount').textContent = '';
  }
}

function _closeSearchPanel() {
  var overlay = document.getElementById('searchOverlay');
  if (overlay) overlay.classList.remove('show');
}

function _updateSearchSessionFilter() {
  var select = document.getElementById('searchSessionFilter');
  if (!select) return;
  select.innerHTML = '<option value="all">全部会话</option>';
  (_sessionList || []).forEach(function(s) {
    select.innerHTML += '<option value="' + s.id + '">' + (s.title || '未命名') + '</option>';
  });
}

function _doSearch(keyword) {
  var resultsDiv = document.getElementById('searchResults');
  var countSpan = document.getElementById('searchResultCount');
  if (!resultsDiv) return;
  
  var kw = keyword || document.getElementById('searchInput').value;
  if (!kw || kw.trim().length < 1) {
    resultsDiv.innerHTML = '<div class="search-empty">输入关键词开始搜索...</div>';
    if (countSpan) countSpan.textContent = '';
    return;
  }
  
  var sessionFilter = document.getElementById('searchSessionFilter').value;
  var typeFilter = document.getElementById('searchTypeFilter').value;
  var results = [];
  
  // 搜索当前会话的消息
  _searchInSession(_currentSessionId, kw, typeFilter, results);
  
  // 如果是全部会话，也搜索其他会话
  if (sessionFilter === 'all') {
    (_sessionList || []).forEach(function(s) {
      if (s.id !== _currentSessionId) {
        _searchInSession(s.id, kw, typeFilter, results);
      }
    });
  } else if (sessionFilter !== _currentSessionId) {
    _searchInSession(sessionFilter, kw, typeFilter, results);
  }
  
  if (results.length === 0) {
    resultsDiv.innerHTML = '<div class="search-empty">未找到匹配 "' + kw + '" 的消息</div>';
    if (countSpan) countSpan.textContent = '0 条结果';
    return;
  }
  
  if (countSpan) countSpan.textContent = results.length + ' 条结果';
  
  var html = '';
  results.forEach(function(r) {
    var preview = r.content.replace(/<[^>]+>/g, '').substring(0, 120);
    var highlighted = preview.replace(new RegExp('(' + kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'), '<span class="highlight">$1</span>');
    html += '<div class="search-result-item" onclick="_jumpToSearchResult(\'' + r.sessionId + '\', ' + r.index + ')">';
    html += '<div class="search-result-header">';
    html += '<span style="font-size:11px;color:rgba(255,255,255,0.5);">' + (r.role === 'user' ? SVG_ICONS.user + ' 用户' : SVG_ICONS.bot + ' AI') + '</span>';
    html += '<span class="search-result-meta">' + (r.sessionTitle || '') + ' · #' + (r.index + 1) + '</span>';
    html += '</div>';
    html += '<div class="search-result-preview">' + highlighted + '</div>';
    html += '</div>';
  });
  resultsDiv.innerHTML = html;
}

function _searchInSession(sessionId, keyword, typeFilter, results) {
  var session = _sessionList.find(function(s) { return s.id === sessionId; });
  var sessionTitle = session ? session.title : '';
  try {
    var raw = localStorage.getItem('mimo_chat_' + sessionId);
    if (!raw) return;
    var messages = JSON.parse(raw);
    var kw = keyword.toLowerCase();
    messages.forEach(function(msg, idx) {
      if (typeFilter !== 'all' && msg.role !== typeFilter) return;
      var text = (msg.content || '').replace(/<[^>]+>/g, '').toLowerCase();
      if (text.indexOf(kw) >= 0) {
        results.push({
          sessionId: sessionId,
          sessionTitle: sessionTitle,
          index: idx,
          role: msg.role,
          content: msg.content || ''
        });
      }
    });
  } catch(e) {}
}

function _jumpToSearchResult(sessionId, msgIndex) {
  _closeSearchPanel();
  if (sessionId !== _currentSessionId) {
    _restoreSession(sessionId);
    // 延迟滚动到目标消息
    setTimeout(function() {
      _scrollToMessage(msgIndex);
    }, 300);
  } else {
    _scrollToMessage(msgIndex);
  }
}

function _scrollToMessage(index) {
  var area = document.getElementById('outputMessages');
  if (!area) return;
  var blocks = area.querySelectorAll('.msg-block');
  if (blocks[index]) {
    blocks[index].scrollIntoView({ behavior: 'smooth', block: 'center' });
    // 高亮闪烁
    blocks[index].style.transition = 'background 0.3s';
    blocks[index].style.background = 'rgba(255,105,0,0.1)';
    setTimeout(function() { blocks[index].style.background = ''; }, 1500);
  }
}

// ===== ★ P11: 导出功能 =====
function _exportChat() {
  var area = document.getElementById('outputMessages');
  if (!area) return;
  var blocks = area.querySelectorAll('.msg-block');
  if (blocks.length === 0) { showToast('无消息可导出'); return; }
  
  var session = _sessionList.find(function(s) { return s.id === _currentSessionId; });
  var title = session ? session.title : '对话导出';
  var date = new Date().toISOString().substring(0, 10);
  var md = '# ' + title + '\n\n> 导出时间: ' + new Date().toLocaleString('zh-CN') + '\n\n---\n\n';
  var html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>' + title + '</title>';
  html += '<style>body{font-family:system-ui;max-width:800px;margin:0 auto;padding:20px;background:#1a1a2e;color:#e0e0e0;}' +
    '.user{background:rgba(255,105,0,0.1);padding:12px;border-radius:8px;margin:8px 0;}' +
    '.ai{background:rgba(255,255,255,0.04);padding:12px;border-radius:8px;margin:8px 0;}' +
    '.meta{font-size:11px;color:#666;margin-bottom:4px;}</style></head><body>';
  html += '<h1>' + title + '</h1><p style="color:#666;">导出时间: ' + new Date().toLocaleString('zh-CN') + '</p><hr>';
  
  blocks.forEach(function(block) {
    var isUser = block.classList.contains('msg-user');
    var isAi = block.classList.contains('msg-ai');
    var text = '';
    if (isUser) {
      var bubble = block.querySelector('.msg-bubble');
      text = bubble ? bubble.innerText : '';
      md += '**用户**: ' + text + '\n\n';
      html += '<div class="user"><div class="meta">' + SVG_ICONS.user + ' 用户</div>' + (bubble ? bubble.innerHTML : '') + '</div>';
    } else if (isAi) {
      var content = block.querySelector('.ai-content');
      text = content ? content.innerText : '';
      md += '**AI**: ' + text + '\n\n';
      html += '<div class="ai"><div class="meta">' + SVG_ICONS.bot + ' AI</div>' + (content ? content.innerHTML : '') + '</div>';
    }
  });
  
  html += '</body></html>';
  
  // 下载 Markdown
  var mdBlob = new Blob([md], {type: 'text/markdown;charset=utf-8'});
  var mdUrl = URL.createObjectURL(mdBlob);
  var mdLink = document.createElement('a');
  mdLink.href = mdUrl;
  mdLink.download = title.replace(/[\\/:*?"<>|]/g, '_') + '_' + date + '.md';
  mdLink.click();
  URL.revokeObjectURL(mdUrl);
  
  // 下载 HTML
  var htmlBlob = new Blob([html], {type: 'text/html;charset=utf-8'});
  var htmlUrl = URL.createObjectURL(htmlBlob);
  var htmlLink = document.createElement('a');
  htmlLink.href = htmlUrl;
  htmlLink.download = title.replace(/[\\/:*?"<>|]/g, '_') + '_' + date + '.html';
  htmlLink.click();
  URL.revokeObjectURL(htmlUrl);
  
  showToast('已导出: Markdown + HTML');
}

// ===== ★ P11: 快捷键系统 =====
var _shortcuts = [
  {key: 'Ctrl+F', desc: '搜索消息'},
  {key: 'Ctrl+E', desc: '导出对话'},
  {key: 'Ctrl+/', desc: '快捷键帮助'},
  {key: 'Ctrl+N', desc: '新建会话'},
  {key: 'Ctrl+S', desc: '保存当前会话'},
  {key: 'Ctrl+Enter', desc: '发送消息'},
  {key: 'Ctrl+L', desc: '清空聊天'},
  {key: 'Ctrl+Alt+E', desc: '循环切换 AI 引擎（Ollama → DeepSeek → MIMO）'},  // ★ v4.6.1
  {key: 'Ctrl+,', desc: '打开设置 / API 配置'},                            // ★ v4.6.1
  {key: 'Escape', desc: '关闭搜索/帮助面板'},
];

function _showShortcutsHelp() {
  var overlay = document.getElementById('shortcutsOverlay');
  var list = document.getElementById('shortcutsList');
  if (!overlay || !list) return;
  overlay.classList.add('show');
  var html = '';
  _shortcuts.forEach(function(s) {
    html += '<div class="shortcut-row"><span class="shortcut-key">' + s.key + '</span><span class="shortcut-desc">' + s.desc + '</span></div>';
  });
  list.innerHTML = html;
}

function _closeShortcutsHelp() {
  var overlay = document.getElementById('shortcutsOverlay');
  if (overlay) overlay.classList.remove('show');
}

// ★ 全局键盘事件监听
document.addEventListener('keydown', function(e) {
  // 不在输入框中时处理快捷键
  var tag = (e.target.tagName || '').toLowerCase();
  var isInput = tag === 'input' || tag === 'textarea' || e.target.isContentEditable;
  
  // Ctrl+F: 搜索（覆盖浏览器默认搜索）
  if (e.ctrlKey && e.key === 'f') {
    e.preventDefault();
    _openSearchPanel();
    return;
  }
  
  // Ctrl+E: 导出
  if (e.ctrlKey && e.key === 'e') {
    e.preventDefault();
    _exportChat();
    return;
  }
  
  // Ctrl+/: 快捷键帮助
  if (e.ctrlKey && e.key === '/') {
    e.preventDefault();
    _showShortcutsHelp();
    return;
  }
  
  // Ctrl+N: 新建会话
  if (e.ctrlKey && e.key === 'n') {
    e.preventDefault();
    _showNewSessionDialog();
    return;
  }
  
  // Ctrl+S: 保存会话
  if (e.ctrlKey && e.key === 's') {
    e.preventDefault();
    _saveCurrentSession();
    return;
  }
  
  // Ctrl+L: 清空聊天
  if (e.ctrlKey && e.key === 'l') {
    e.preventDefault();
    _showConfirm('清空聊天', '确定清空当前聊天？', function() { clearOutput(); });
    return;
  }
  
  // Escape: 关闭面板
  if (e.key === 'Escape') {
    _closeSearchPanel();
    _closeShortcutsHelp();
    return;
  }

  // ★ v4.6.1 Ctrl+Alt+E: 循环切换 AI 引擎（Ollama → DeepSeek → MIMO）
  if (e.ctrlKey && e.altKey && e.key === 'e') {
    e.preventDefault();
    if (typeof window.pybridge !== 'undefined' && window.pybridge && typeof window.pybridge.cycleEngine === 'function') {
      window.pybridge.cycleEngine();
    } else {
      // 回退：通过 _callPython 转发到 Python
      _callPython('cycleEngine', null, function(res){
        if (res && res.success) showToast('引擎已切换: ' + (res.engine || ''));
        else showToast('引擎切换失败');
      });
    }
    return;
  }

  // ★ v4.6.1 Ctrl+,: 打开设置 / API 配置
  if (e.ctrlKey && (e.key === ',' || e.code === 'Comma')) {
    e.preventDefault();
    if (typeof window.pybridge !== 'undefined' && window.pybridge && typeof window.pybridge.openSettings === 'function') {
      window.pybridge.openSettings();
    } else {
      _callPython('openSettings', null, function(){});
    }
    return;
  }
});

// ===== ★ P11: 状态栏实时更新 =====
var _statusUpdateTimer = null;
var _fpsFrames = 0;
var _fpsLastTime = performance.now();
var _currentFPS = 0;

function _startStatusUpdates() {
  // 内存/FPS 更新
  _statusUpdateTimer = setInterval(function() {
    _updateMemDisplay();
    _updateFPSDisplay();
  }, 3000);
  
  // FPS 计数
  requestAnimationFrame(_countFPS);
  console.log('[StatusBar] 实时状态更新已启动 (3s间隔)');
}

function _countFPS() {
  _fpsFrames++;
  var now = performance.now();
  if (now - _fpsLastTime >= 1000) {
    _currentFPS = Math.round(_fpsFrames * 1000 / (now - _fpsLastTime));
    _fpsFrames = 0;
    _fpsLastTime = now;
  }
  requestAnimationFrame(_countFPS);
}

function _updateMemDisplay() {
  var label = document.getElementById('memLabel');
  if (!label) return;
  var memMB = '--';
  if (performance.memory) {
    memMB = Math.round(performance.memory.usedJSHeapSize / 1024 / 1024) + 'MB';
  } else if (typeof PerfOpt !== 'undefined' && PerfOpt.getMemoryStatus) {
    var s = PerfOpt.getMemoryStatus();
    memMB = s.memoryMB > 0 ? s.memoryMB + 'MB' : s.messages + '条';
  }
  label.textContent = '内存: ' + memMB;
}

function _updateFPSDisplay() {
  var label = document.getElementById('fpsLabel');
  if (!label) return;
  label.textContent = 'FPS: ' + _currentFPS;
}

function _updateEngineDisplay(mode, model) {
  var label = document.getElementById('engineLabel');
  if (!label) return;
  var modeNames = {mimocode: 'Lemon Code', mimo: 'Lemon Code', ollama: 'Ollama', deepseek: 'DeepSeek', auto: 'Auto'};
  var display = modeNames[mode] || mode || 'Auto';
  if (model) display += ' (' + model + ')';
  label.textContent = '引擎: ' + display;
}

// 在页面加载时启动状态更新
if (typeof _startStatusUpdates === 'function') {
  document.addEventListener('DOMContentLoaded', function() {
    setTimeout(_startStatusUpdates, 2000);
  });
}

// ★ P13 B4修复: 事件监听器清理
var _eventListeners = [];

function _addCleanableListener(element, event, handler) {
  if (!element) return;
  element.addEventListener(event, handler);
  _eventListeners.push({ element: element, event: event, handler: handler });
}

function cleanupEventListeners() {
  _eventListeners.forEach(function(entry) {
    try { entry.element.removeEventListener(entry.event, entry.handler); } catch(e) {}
  });
  _eventListeners = [];
}

// 页面卸载时清理
window.addEventListener('beforeunload', cleanupEventListeners);


// ============================================================
// ===== 设置面板逻辑 =====
// ============================================================

// 默认设置（与 settings_manager.py 中 DEFAULT_SETTINGS 保持一致）
var DEFAULT_SETTINGS = {
  general: { language: 'zh', reopen_last_session: true },
  ai: { model: 'auto', temperature: 0.7, max_tokens: 4096 },
  appearance: {
    theme: 'cyber', font_size: 14, code_font: 'Consolas',
    // ★ v4.1.9: 模式开关收敛为两键 — NATIVE / HOST
    mode_switches: {
      native_agent_enabled: true,   // NATIVE — LemonCode 本体 Agent
      host_agent_enabled: true      // HOST — 外部 Agent 夺舍
    }
  },
  visualization: { chart_style: 'neon', render_quality: 'high', animation: true },
  shortcuts: { send: 'Ctrl+Enter', new_session: 'Ctrl+N', switch_session: 'Ctrl+Tab', settings: 'Ctrl+,' },
  // ★ v4.1.12: 分模式差异化配置（NATIVE 本体 vs HOST 夺舍）
  modes: {
    native: {
      enabled: true,
      tool_file_write: true,
      tool_terminal: true,
      tool_web_search: false,
      tool_code_review: false,
      session_memory: true
    },
    host: {
      enabled: true,
      default_agent: 'mimo_code',
      acp_port: 0,
      connect_timeout: 30,
      intercept_output: true,
      reprocess_output: true,
      show_source_prefix: true,
      color_output: true
    }
  }
};

// 当前设置（运行时副本）
var _currentSettings = null;
// 设置变更前的快照（用于取消恢复）
var _settingsBackup = null;

function openSettings() {
  // 打开前先加载当前设置
  loadSettingsFromBackend(function(settings) {
    _currentSettings = settings;
    _settingsBackup = JSON.parse(JSON.stringify(settings));
    populateSettingsUI(settings);
    document.getElementById('settingsOverlay').classList.add('active');
    // 初始化主题卡片选中状态
    selectTheme(settings.appearance.theme, false);
    // ★ v354: CodeBuddy 式模型中心 —— 打开设置即渲染分组列表 + 静默测一次连接
    try {
      ['mimocode', 'ollama', 'deepseek'].forEach(function(p) { loadEngineModels(p); });
      renderMsList();
      window.testEngineLatency();
      // ★ v355: 本地探测器 + 自定义模型（recheck 掉线剔除）
      probeLocalModels();
      refreshCustomModels(true);
    } catch (e) { console.warn('[Settings] 模型中心初始化失败:', e); }
  });
}

function closeSettings() {
  // 未保存时恢复预览
  if (_settingsBackup) {
    applyTheme(_settingsBackup.appearance.theme);
    applyFontSize(_settingsBackup.appearance.font_size);
  }
  _currentSettings = null;
  _settingsBackup = null;
  document.getElementById('settingsOverlay').classList.remove('active');
}

function saveDeepSeekApiKey() {
  var key = document.getElementById('deepseekApiKeyInput').value.trim();
  if (!key) return;
  window._callPython('saveApiKey', JSON.stringify({engine: 'deepseek', key: key}));
  showToast('DeepSeek API Key 已保存');
}

// ★ v4.7.17+: 模型选择面板内的「自定义 API 密钥」入口（Trae/Cursor 风格）
function toggleCustomKeyInput() {
  var body = document.getElementById('customKeyBody');
  if (!body) return;
  var hidden = body.style.display === 'none';
  body.style.display = hidden ? 'block' : 'none';
}
function savePanelDeepseekKey() {
  var input = document.getElementById('panelDeepseekKeyInput');
  var key = input ? input.value.trim() : '';
  if (!key) {
    showToast('请先粘贴 DeepSeek API Key');
    return;
  }
  if (typeof window._callPython === 'function') {
    window._callPython('saveApiKey', JSON.stringify({engine: 'deepseek', key: key}), function() {
      showToast('DeepSeek API Key 已保存');
    });
  } else {
    showToast('Python 桥接未就绪');
  }
  // 清空输入框，避免明文残留
  if (input) input.value = '';
}

function saveMiMoApiKey() {
  var key = document.getElementById('mimoApiKeyInput').value.trim();
  if (!key) return;
  window._callPython('saveApiKey', JSON.stringify({engine: 'mimo', key: key}));
  showToast('MiMo API Key 已保存');
}

// ===== ★ 自定义 API 格式配置 =====
var _API_FORMAT_DEFAULTS = {
  ollama: {
    endpoint: 'http://localhost:11434/api/chat',
    body: '{"model":"{{model}}","messages":[{"role":"user","content":"{{prompt}}"}],"stream":true}',
    headers: '{"Content-Type":"application/json"}'
  },
  deepseek: {
    endpoint: 'https://api.deepseek.com/v1/chat/completions',
    body: '{"model":"{{model}}","messages":[{"role":"user","content":"{{prompt}}"}],"stream":true,"temperature":0.7}',
    headers: '{"Authorization":"Bearer {{api_key}}","Content-Type":"application/json"}'
  },
  mimo: {
    endpoint: 'http://localhost:4097/v1/chat/completions',
    body: '{"model":"{{model}}","messages":[{"role":"user","content":"{{prompt}}"}],"stream":true}',
    headers: '{"Content-Type":"application/json"}'
  },
  custom: {
    endpoint: '',
    body: '{"model":"{{model}}","messages":[{"role":"user","content":"{{prompt}}"}],"stream":true}',
    headers: '{"Authorization":"Bearer {{api_key}}","Content-Type":"application/json"}'
  }
};

function _loadApiFormat(engine) {
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem('mimo_api_formats') || '{}'); } catch(e) {}
  var fmt = saved[engine] || _API_FORMAT_DEFAULTS[engine] || _API_FORMAT_DEFAULTS.custom;
  document.getElementById('apiFormatEndpoint').value = fmt.endpoint || '';
  document.getElementById('apiFormatBody').value = fmt.body || '';
  document.getElementById('apiFormatHeaders').value = fmt.headers || '';
}

function _saveApiFormat() {
  var engine = document.getElementById('apiFormatEngine').value;
  var endpoint = document.getElementById('apiFormatEndpoint').value.trim();
  var body = document.getElementById('apiFormatBody').value.trim();
  var headers = document.getElementById('apiFormatHeaders').value.trim();

  // 验证 JSON 格式
  if (body) {
    try {
      var testBody = body.replace(/\{\{prompt\}\}/g, 'test').replace(/\{\{model\}\}/g, 'test').replace(/\{\{api_key\}\}/g, 'test');
      JSON.parse(testBody);
    } catch(e) {
      showToast('请求体 JSON 格式错误: ' + e.message);
      return;
    }
  }
  if (headers) {
    try { JSON.parse(headers); } catch(e) {
      showToast('请求头 JSON 格式错误: ' + e.message);
      return;
    }
  }

  var saved = {};
  try { saved = JSON.parse(localStorage.getItem('mimo_api_formats') || '{}'); } catch(e) {}
  saved[engine] = { endpoint: endpoint, body: body, headers: headers };
  localStorage.setItem('mimo_api_formats', JSON.stringify(saved));

  // 通知 Python 后端
  if (typeof window._callPython === 'function') {
    window._callPython('saveApiFormat', JSON.stringify({ engine: engine, config: saved[engine] }));
  }
  showToast(engine + ' API 格式已保存');
}

function _resetApiFormat() {
  var engine = document.getElementById('apiFormatEngine').value;
  var defaults = _API_FORMAT_DEFAULTS[engine] || _API_FORMAT_DEFAULTS.custom;
  document.getElementById('apiFormatEndpoint').value = defaults.endpoint;
  document.getElementById('apiFormatBody').value = defaults.body;
  document.getElementById('apiFormatHeaders').value = defaults.headers;

  // 清除保存的配置
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem('mimo_api_formats') || '{}'); } catch(e) {}
  delete saved[engine];
  localStorage.setItem('mimo_api_formats', JSON.stringify(saved));

  if (typeof window._callPython === 'function') {
    window._callPython('resetApiFormat', engine);
  }
  showToast(engine + ' 已重置为默认格式');
}

// 初始化加载当前引擎的 API 格式
try {
  var _initEngine = document.getElementById('apiFormatEngine');
  if (_initEngine) _loadApiFormat(_initEngine.value);
} catch(e) {}

function showToast(msg) {
  var toast = document.createElement('div');
  toast.textContent = msg;
  toast.style.cssText = 'position:fixed;bottom:60px;left:50%;transform:translateX(-50%);background:#ff6900;color:#fff;padding:8px 20px;border-radius:20px;font-size:13px;z-index:9999;animation:fadeInOut 2s forwards;';
  document.body.appendChild(toast);
  setTimeout(function() { toast.remove(); }, 2100);
}

function switchSettingsTab(tabName) {
  // 切换标签页
  var tabs = document.querySelectorAll('.settings-tab');
  var sections = document.querySelectorAll('.settings-section');
  for (var i = 0; i < tabs.length; i++) {
    tabs[i].classList.toggle('active', tabs[i].getAttribute('data-tab') === tabName);
  }
  for (var j = 0; j < sections.length; j++) {
    sections[j].classList.toggle('active', sections[j].getAttribute('data-section') === tabName);
  }
  // 切换到"关于"标签时加载版本信息
  if (tabName === 'about') {
    loadAboutInfo();
  }
  if (tabName === 'agent') {
    syncSettingsModelDisplay();
    ['mimocode', 'ollama', 'deepseek'].forEach(function(p) { loadEngineModels(p); });
  }
}

// ===== ★ 自动更新检查 =====

function _callUpdater(method, args, cb) {
  if (window._callPython) {
    window._callPython(method, args || [], cb);
  } else if (window.pybridge) {
    window.pybridge.call(method, JSON.stringify(args || []), cb);
  } else {
    if (cb) cb({ ok: false, error: 'bridge unavailable' });
  }
}

function loadAboutInfo() {
  _callUpdater('getVersionInfo', [], function(res) {
    if (res && res.ok && res.info) {
      var info = res.info;
      var elV = document.getElementById('about-version');
      var elI = document.getElementById('about-installed');
      var elL = document.getElementById('about-last-check');
      var elC = document.getElementById('about-channel');
      if (elV) elV.textContent = info.current_version || '1.0.0';
      if (elI) elI.textContent = info.installed_at || '-';
      if (elL) elL.textContent = info.last_check_time || '从未检查';
      if (elC) elC.textContent = info.update_channel || 'stable';
      // 显示上次检查结果
      var lc = info.last_check_result;
      if (lc && lc.has_update) {
        _showUpdateStatusBox(lc);
      }
    } else {
      var elVe = document.getElementById('about-version');
      if (elVe) elVe.textContent = '1.0.0';
    }
  });
}

function checkForUpdates(force) {
  var statusBox = document.getElementById('update-status-box');
  var statusText = document.getElementById('update-status-text');
  var actionRow = document.getElementById('update-action-row');
  if (statusBox) { statusBox.style.display = 'block'; }
  if (statusText) { statusText.textContent = '正在检查更新...'; }
  if (actionRow) { actionRow.style.display = 'none'; }
  _callUpdater('checkUpdates', [!!force], function(res) {
    if (res && res.ok && res.result) {
      var r = res.result;
      if (r.has_update) {
        _showUpdateStatusBox(r);
        _showUpdateBadge(true);
      } else {
        if (statusText) {
          statusText.textContent = r.error
            ? ('检查失败: ' + r.error)
            : ('已是最新版本 (' + r.current_version + ')');
        }
        if (actionRow) { actionRow.style.display = 'none'; }
        _showUpdateBadge(false);
      }
    } else {
      if (statusText) { statusText.textContent = '检查失败: ' + (res && res.error ? res.error : '未知错误'); }
    }
  });
}

function _showUpdateStatusBox(result) {
  var statusBox = document.getElementById('update-status-box');
  var statusText = document.getElementById('update-status-text');
  var actionRow = document.getElementById('update-action-row');
  if (statusBox) { statusBox.style.display = 'block'; }
  if (statusText) {
    var notes = result.release_notes ? ('\n' + result.release_notes.substring(0, 200)) : '';
    statusText.textContent = '发现新版本: ' + result.latest_version + ' (当前: ' + result.current_version + ')' + notes;
    statusText.style.whiteSpace = 'pre-wrap';
  }
  if (actionRow) { actionRow.style.display = 'flex'; }
}

function _showUpdateBadge(show) {
  var badge = document.getElementById('updateBadge');
  if (badge) { badge.style.display = show ? 'block' : 'none'; }
}

function performUpdate() {
  var statusText = document.getElementById('update-status-text');
  if (statusText) { statusText.textContent = '正在下载更新...'; }
  // 获取上次检查结果中的版本号和下载URL
  _callUpdater('getVersionInfo', [], function(res) {
    if (!res || !res.ok || !res.info || !res.info.last_check_result) {
      if (statusText) { statusText.textContent = '无法获取更新信息'; }
      return;
    }
    var lc = res.info.last_check_result;
    var version = lc.latest_version;
    var url = lc.download_url || '';
    _callUpdater('downloadUpdate', [version, url], function(dlRes) {
      if (!dlRes || !dlRes.ok) {
        if (statusText) { statusText.textContent = '下载失败: ' + (dlRes && dlRes.error ? dlRes.error : '未知错误'); }
        return;
      }
      if (statusText) { statusText.textContent = '下载完成，正在安装...'; }
      _callUpdater('installUpdate', [dlRes.package_path, true], function(instRes) {
        if (instRes && instRes.ok) {
          if (statusText) { statusText.textContent = '更新成功! 当前版本: ' + instRes.version + '。请重启应用以完成更新。'; }
          _showUpdateBadge(false);
          var actionRow = document.getElementById('update-action-row');
          if (actionRow) { actionRow.style.display = 'none'; }
        } else {
          if (statusText) { statusText.textContent = '安装失败: ' + (instRes && instRes.error ? instRes.error : '未知错误'); }
        }
      });
    });
  });
}

function dismissUpdate() {
  _callUpdater('dismissUpdate', [], function() {
    var statusBox = document.getElementById('update-status-box');
    var actionRow = document.getElementById('update-action-row');
    if (statusBox) { statusBox.style.display = 'none'; }
    if (actionRow) { actionRow.style.display = 'none'; }
    _showUpdateBadge(false);
  });
}

function showUpdateHistory() {
  _callUpdater('getUpdateHistory', [], function(res) {
    if (!res || !res.ok) { return; }
    var history = res.history || [];
    var statusBox = document.getElementById('update-status-box');
    var statusText = document.getElementById('update-status-text');
    var actionRow = document.getElementById('update-action-row');
    if (!statusBox || !statusText) { return; }
    statusBox.style.display = 'block';
    actionRow.style.display = 'none';
    if (history.length === 0) {
      statusText.textContent = '暂无更新历史';
    } else {
      var lines = ['更新历史 (' + history.length + ' 条):'];
      for (var i = history.length - 1; i >= 0 && i >= history.length - 10; i--) {
        var h = history[i];
        var ts = h.installed_at || h.rolled_back_at || '-';
        var ver = h.version || '-';
        var type = h.type || '-';
        var status = h.status || '-';
        lines.push('  [' + ts + '] v' + ver + ' (' + type + ', ' + status + ')');
      }
      statusText.textContent = lines.join('\n');
      statusText.style.whiteSpace = 'pre-wrap';
    }
  });
}

// 启动时静默检查更新通知状态
function initUpdateNotification() {
  _callUpdater('getVersionInfo', [], function(res) {
    if (res && res.ok && res.info && res.info.last_check_result) {
      var lc = res.info.last_check_result;
      if (lc.has_update && !lc.dismissed) {
        _showUpdateBadge(true);
      }
    }
  });
}

function toggleSetting(btn) {
  btn.classList.toggle('on');
}

function updateSliderValue(slider, valueId) {
  var valEl = document.getElementById(valueId);
  if (valEl) valEl.textContent = slider.value;
  // 实时预览字体大小
  if (slider.id === 'set-font-size') {
    applyFontSize(parseInt(slider.value));
  }
}

function selectTheme(themeName, preview) {
  if (preview === undefined) preview = true;
  // ★ 只更新主主题卡片（#themeCards内的），不影响节日主题卡片
  var container = document.getElementById('themeCards');
  if (container) {
    var cards = container.querySelectorAll('.theme-card');
    for (var i = 0; i < cards.length; i++) {
      cards[i].classList.toggle('selected', cards[i].getAttribute('data-theme') === themeName);
    }
  }
  // 实时预览主题
  if (preview) applyTheme(themeName);
}

function applyTheme(themeName) {
  document.documentElement.setAttribute('data-theme', themeName);
}

function applyFontSize(size) {
  document.body.style.fontSize = size + 'px';
}

// 从 UI 控件收集设置
function collectSettingsFromUI() {
  return {
    general: {
      language: document.getElementById('set-language').value,
      reopen_last_session: document.getElementById('set-reopen').classList.contains('on')
    },
    ai: {
      model: document.getElementById('set-model').value,
      temperature: parseFloat(document.getElementById('set-temperature').value),
      max_tokens: parseInt(document.getElementById('set-max-tokens').value)
    },
    appearance: {
      theme: document.querySelector('.theme-card.selected') ? document.querySelector('.theme-card.selected').getAttribute('data-theme') : 'cyber',
      font_size: parseInt(document.getElementById('set-font-size').value),
      code_font: document.getElementById('set-code-font').value,
      // ★ v4.1.9: 收集顶部模式段的两键开关
      mode_switches: {
        native_agent_enabled: document.getElementById('set-native-agent').classList.contains('on'),
        host_agent_enabled: document.getElementById('set-host-agent').classList.contains('on')
      }
    },
    visualization: {
      chart_style: document.getElementById('set-chart-style').value,
      render_quality: document.getElementById('set-render-quality').value,
      animation: document.getElementById('set-animation').classList.contains('on')
    },
    // ★ v4.1.12: 分模式差异化配置
    modes: {
      native: {
        enabled: true,
        tool_file_write: document.getElementById('set-native-tool-file').classList.contains('on'),
        tool_terminal: document.getElementById('set-native-tool-term').classList.contains('on'),
        tool_web_search: document.getElementById('set-native-tool-web').classList.contains('on'),
        tool_code_review: document.getElementById('set-native-review').classList.contains('on'),
        session_memory: document.getElementById('set-native-memory').classList.contains('on')
      },
      host: {
        enabled: true,
        default_agent: document.getElementById('set-host-default-agent').value,
        acp_port: 0,
        connect_timeout: parseInt(document.getElementById('set-host-timeout').value) || 30,
        intercept_output: document.getElementById('set-host-intercept').classList.contains('on'),
        reprocess_output: document.getElementById('set-host-reprocess').classList.contains('on'),
        show_source_prefix: document.getElementById('set-host-prefix').classList.contains('on'),
        color_output: document.getElementById('set-host-color').classList.contains('on')
      }
    },
    shortcuts: _currentSettings ? _currentSettings.shortcuts : DEFAULT_SETTINGS.shortcuts
  };
}

// 将设置填充到 UI 控件
function populateSettingsUI(settings) {
  if (!settings) return;
  // 通用
  document.getElementById('set-language').value = settings.general.language || 'zh';
  document.getElementById('set-reopen').classList.toggle('on', !!settings.general.reopen_last_session);
  // AI
  document.getElementById('set-model').value = settings.ai.model || 'auto';
  document.getElementById('set-temperature').value = settings.ai.temperature || 0.7;
  document.getElementById('set-temperature-val').textContent = settings.ai.temperature || 0.7;
  document.getElementById('set-max-tokens').value = settings.ai.max_tokens || 4096;
  document.getElementById('set-max-tokens-val').textContent = settings.ai.max_tokens || 4096;
  // 外观
  document.getElementById('set-font-size').value = settings.appearance.font_size || 14;
  document.getElementById('set-font-size-val').textContent = settings.appearance.font_size || 14;
  document.getElementById('set-code-font').value = settings.appearance.code_font || 'Consolas';
  // ★ v4.1.9: 顶部模式段独立开关（两键）
  var ms = (settings.appearance && settings.appearance.mode_switches) || DEFAULT_SETTINGS.appearance.mode_switches;
  document.getElementById('set-native-agent').classList.toggle('on', ms.native_agent_enabled !== false);
  document.getElementById('set-host-agent').classList.toggle('on', ms.host_agent_enabled !== false);
  // ★ v4.1.9: 兼容旧配置 — 如果存在 set-solo-mode 节点，强制隐藏（避免遗留 DOM 影响）
  var soloNode = document.getElementById('set-solo-mode');
  if (soloNode) {
    var row = soloNode.closest('.setting-row');
    if (row) row.style.display = 'none';
  }
  // 可视化
  document.getElementById('set-chart-style').value = settings.visualization.chart_style || 'neon';
  document.getElementById('set-render-quality').value = settings.visualization.render_quality || 'high';
  document.getElementById('set-animation').classList.toggle('on', settings.visualization.animation !== false);
  // ★ v4.1.12: 分模式配置回填
  var md = settings.modes || DEFAULT_SETTINGS.modes;
  var mn = md.native || DEFAULT_SETTINGS.modes.native;
  document.getElementById('set-native-tool-file').classList.toggle('on', mn.tool_file_write !== false);
  document.getElementById('set-native-tool-term').classList.toggle('on', mn.tool_terminal !== false);
  document.getElementById('set-native-tool-web').classList.toggle('on', mn.tool_web_search === true);
  document.getElementById('set-native-review').classList.toggle('on', mn.tool_code_review === true);
  document.getElementById('set-native-memory').classList.toggle('on', mn.session_memory !== false);
  var mh = md.host || DEFAULT_SETTINGS.modes.host;
  document.getElementById('set-host-default-agent').value = mh.default_agent || 'mimo_code';
  document.getElementById('set-host-timeout').value = mh.connect_timeout || 30;
  document.getElementById('set-host-timeout-val').textContent = (mh.connect_timeout || 30) + 's';
  document.getElementById('set-host-intercept').classList.toggle('on', mh.intercept_output !== false);
  document.getElementById('set-host-reprocess').classList.toggle('on', mh.reprocess_output !== false);
  document.getElementById('set-host-prefix').classList.toggle('on', mh.show_source_prefix !== false);
  document.getElementById('set-host-color').classList.toggle('on', mh.color_output !== false);
  // 应用实时预览
  applyTheme(settings.appearance.theme || 'cyber');
  applyFontSize(settings.appearance.font_size || 14);
}

function saveSettings() {
  var settings = collectSettingsFromUI();
  _currentSettings = settings;
  // 通过 Python 桥接保存
  saveSettingsToBackend(settings);
  // 应用设置
  applyTheme(settings.appearance.theme);
  applyFontSize(settings.appearance.font_size);
  // 关闭面板
  document.getElementById('settingsOverlay').classList.remove('active');
  console.log('[Settings] 已保存设置:', settings);
}

function resetSettings() {
  _currentSettings = JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
  populateSettingsUI(_currentSettings);
  selectTheme(DEFAULT_SETTINGS.appearance.theme, true);
  console.log('[Settings] 已重置为默认设置');
}

// ===== Python 桥接 =====
function loadSettingsFromBackend(callback) {
  if (typeof window._callPython === 'function') {
    try {
      window._callPython('loadSettings');
    } catch(e) { console.warn('[Settings] 调用 Python loadSettings 失败:', e); }
  }
  // 回调由 Python 端通过 setSettingsFromPython 触发
  // 设置 3 秒超时，使用默认值
  setTimeout(function() {
    if (!_currentSettings) {
      console.warn('[Settings] 后端加载超时，使用默认值');
      callback(JSON.parse(JSON.stringify(DEFAULT_SETTINGS)));
    }
  }, 3000);
  // 如果 _currentSettings 已设置（Python 端已回调），直接使用
  if (_currentSettings) {
    callback(_currentSettings);
  }
}

// Python 端调用此方法传入设置
function setSettingsFromPython(settingsJson) {
  try {
    var settings = typeof settingsJson === 'string' ? JSON.parse(settingsJson) : settingsJson;
    _currentSettings = settings;
    if (_settingsBackup === null) {
      _settingsBackup = JSON.parse(JSON.stringify(settings));
    }
    // 如果面板已打开，更新 UI
    if (document.getElementById('settingsOverlay').classList.contains('active')) {
      populateSettingsUI(settings);
      selectTheme(settings.appearance.theme, true);
    } else {
      // 面板未打开时，仅应用主题和字体
      applyTheme(settings.appearance.theme || 'cyber');
      applyFontSize(settings.appearance.font_size || 14);
    }
  } catch(e) {
    console.error('[Settings] 解析后端设置失败:', e);
  }
}

function saveSettingsToBackend(settings) {
  if (typeof window._callPython === 'function') {
    try {
      window._callPython('saveSettings', JSON.stringify(settings));
    } catch(e) { console.warn('[Settings] 调用 Python saveSettings 失败:', e); }
  }
  // 本地缓存（以防 Python 端不可用）
  try { localStorage.setItem('mimo_settings', JSON.stringify(settings)); } catch(e) {}
}

// ===== 启动时加载设置 =====
function initSettingsOnLoad() {
  // 尝试从 localStorage 加载（快速恢复）
  try {
    var cached = localStorage.getItem('mimo_settings');
    if (cached) {
      var settings = JSON.parse(cached);
      applyTheme(settings.appearance ? settings.appearance.theme : 'cyber');
      applyFontSize(settings.appearance ? settings.appearance.font_size : 14);
    }
  } catch(e) {}
  // 从后端加载最新设置
  if (typeof window._callPython === 'function') {
    try { window._callPython('loadSettings'); } catch(e) {}
  }
}

// 点击遮罩关闭
document.addEventListener('DOMContentLoaded', function() {
  // ★ v4.8.1 布局安全守卫：right-panel-mode 由 Python 注入管理，JS 不再移除
  // 清理本地存储中的异常状态
  try {
    if (localStorage.getItem('bodyRightPanelMode') === '1') {
      localStorage.removeItem('bodyRightPanelMode');
    }
  } catch(e) {}

  // ★ 关键修复：QWebEngineView 中 body 的 height:100% 可能无法正确解析
  // 用 JS 强制设置 body 高度 = 容器实际渲染高度，确保 flex 布局正确
  // ★ v12.10 REBUILD: 将 fixBodyHeight 暴露到全局，供 ThemeManager / applyWallpaper 调用
  window.fixBodyHeight = function() {
    var h = document.documentElement.clientHeight || window.innerHeight || document.body.clientHeight;
    if (h > 0) {
      document.body.style.height = h + 'px';
      document.body.style.minHeight = h + 'px';
    }
  }
  window.fixBodyHeight();
  window.addEventListener('resize', window.fixBodyHeight);

  // #region debug-point D:dom-ready
  var bodyClasses = [];
  for (var i = 0; i < document.body.classList.length; i++) {
    bodyClasses.push(document.body.classList[i]);
  }
  var contentEl = document.getElementById('content');
  _dbgLog('D','dom-ready',{bodyClasses:bodyClasses,contentDisplay:contentEl?getComputedStyle(contentEl).display:'N/A',contentBg:contentEl?getComputedStyle(contentEl).backgroundColor:'N/A',contentOpacity:contentEl?getComputedStyle(contentEl).opacity:'N/A',contentH:contentEl?contentEl.offsetHeight:0,contentW:contentEl?contentEl.offsetWidth:0,starfieldDisplay:canvas?getComputedStyle(canvas).display:'N/A',starfieldOpacity:canvas?getComputedStyle(canvas).opacity:'N/A',nebulaDisplay:document.getElementById('nebula')?getComputedStyle(document.getElementById('nebula')).display:'N/A'});
  // #endregion

  var overlay = document.getElementById('settingsOverlay');
  if (overlay) {
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) closeSettings();
    });
  }
  // ★ 启动时初始化节日主题
  if (typeof ThemeManager !== 'undefined') {
    ThemeManager.init();
  }
  // ★ v4.8.1 星空动画安全网：每5秒检查一次 starfield 动画是否在运行
  setInterval(function() {
    if (_wallpaperMode === 'dynamic' && _wallpaperTheme !== 'ocean' && _wallpaperTheme !== 'focus_moment') {
      if (!_starfieldRAF && typeof render === 'function') {
        console.warn('[Starfield] 动画帧丢失，正在重启...');
        initStarfield();
      }
    }
  }, 5000);
  // ★ 启动时加载设置
  setTimeout(initSettingsOnLoad, 500);
  // ★ 启动时加载工作区
  setTimeout(initWorkspaceOnLoad, 800);
  // ★ 启动时检查更新通知状态（延迟1.5秒，避免与其他初始化竞争）
  setTimeout(initUpdateNotification, 1500);

  // ★ v4.8.1: 延迟2秒后强制重设 starfield canvas 尺寸
  // 确保面板显示后 canvas 有正确的宽高
  setTimeout(function() {
    if (typeof initStarfield === 'function') {
      initStarfield();
    }
    window.dispatchEvent(new Event('resize'));
  }, 2000);

  // ★ 节日祝福语定时显示系统（每30分钟显示一次）
  setInterval(function() {
    if (typeof ThemeManager !== 'undefined' && ThemeManager.currentTheme !== 'default') {
      ThemeManager.showBlessing(ThemeManager.currentTheme);
    }
  }, 30 * 60 * 1000); // 30分钟

  // #region debug-point D:periodic-status
  // 运行时状态巡检：前10秒每秒上报一次
  (function() {
    var checkCount = 0;
    var timer = setInterval(function() {
      checkCount++;
      if (checkCount > 10) { clearInterval(timer); return; }
      var bodyClasses = [];
      for (var ci = 0; ci < document.body.classList.length; ci++) { bodyClasses.push(document.body.classList[ci]); }
      var sfCanvas = document.getElementById('starfield');
      var bgEl = document.getElementById('content');
      var hasRaf = typeof _starfieldRAF !== 'undefined' && _starfieldRAF !== null;
      _dbgLog('D','periodic-check',{count:checkCount,bodyClasses:bodyClasses,hasRightPanelMode:document.body.classList.contains('right-panel-mode'),wallpaperMode:_wallpaperMode,wallpaperTheme:_wallpaperTheme,hasRaf:hasRaf,sfOpacity:sfCanvas?getComputedStyle(sfCanvas).opacity:'N/A',sfDisplay:sfCanvas?getComputedStyle(sfCanvas).display:'N/A',sfVisibility:sfCanvas?getComputedStyle(sfCanvas).visibility:'N/A',contentBg:bgEl?getComputedStyle(bgEl).backgroundColor:'N/A',contentOpacity:bgEl?getComputedStyle(bgEl).opacity:'N/A',contentW:bgEl?bgEl.offsetWidth:0,contentH:bgEl?bgEl.offsetHeight:0});
    }, 1000);
  })();
  // #endregion

  // 点击外部关闭工作区下拉
  document.addEventListener('click', function(e) {
    var wsBar = document.querySelector('.workspace-bar');
    var wsDropdown = document.getElementById('workspaceDropdown');
    var wsSelector = document.getElementById('workspaceSelector');
    if (wsDropdown && wsDropdown.classList.contains('open')) {
      if (wsBar && !wsBar.contains(e.target)) {
        wsDropdown.classList.remove('open');
        wsSelector.classList.remove('open');
      }
    }
  });
});

// ============================================================
// ★ 工作区管理 JS
// ============================================================
var _currentWorkspace = null;
var _workspaceList = [];

function initWorkspaceOnLoad() {
  // ★ v4.8.1 Cleanup stale workspace tabs that may have been corrupted
  try {
    var corruptedTabs = _workspaceTabs.filter(function(t) {
      return t.title && (t.title.indexOf('SVG_ICONS') !== -1 || t.title.indexOf('{ICON:') !== -1);
    });
    if (corruptedTabs.length > 0) {
      _workspaceTabs = _workspaceTabs.filter(function(t) {
        return !corruptedTabs.includes(t);
      });
      console.warn('[Workspace] 已清理 ' + corruptedTabs.length + ' 个异常标签页');
    }
  } catch(e) {}
  // ★ v4.8.1 Clear stale skill outputs from previous sessions
  try {
    _skillOutputs = {};
    _skillStatuses = {};
    _skillInProgress = null;
  } catch(e) {}
  loadWorkspaces();
}

function loadWorkspaces() {
  if (typeof window._callPython === 'function') {
    try {
      window._callPython('listWorkspaces', [], function(result) {
        if (result && result.workspaces) {
          setWorkspacesFromPython(result);
        }
      });
    } catch(e) { console.error('[Workspace] 加载失败:', e); }
  }
}

function setWorkspacesFromPython(data) {
  if (!data) return;
  _workspaceList = data.workspaces || [];
  _currentWorkspace = data.current || null;
  renderWorkspaceList();
  updateWorkspaceDisplay();
}

function updateWorkspaceDisplay() {
  var nameEl = document.getElementById('workspaceName');
  if (nameEl) {
    if (_currentWorkspace && _currentWorkspace.name) {
      nameEl.textContent = _currentWorkspace.name;
      nameEl.title = _currentWorkspace.path || '';
    } else {
      nameEl.textContent = '未选择工作区';
    }
  }
}

function renderWorkspaceList() {
  var listEl = document.getElementById('workspaceList');
  if (!listEl) return;
  if (_workspaceList.length === 0) {
    listEl.innerHTML = '<div style="padding:16px;text-align:center;color:rgba(255,255,255,0.3);font-size:11px;">暂无工作区，点击下方添加</div>';
    return;
  }
  var currentId = _currentWorkspace ? _currentWorkspace.id : '';
  var html = '';
  for (var i = 0; i < _workspaceList.length; i++) {
    var ws = _workspaceList[i];
    var isActive = ws.id === currentId;
    var icon = isActive ? '●' : '○';
    html += '<div class="workspace-item' + (isActive ? ' active' : '') + '" onclick="switchWorkspace(\'' + ws.id + '\')">';
    html += '<span class="workspace-item-icon">' + icon + '</span>';
    html += '<div class="workspace-item-info">';
    html += '<div class="workspace-item-name">' + escapeHtml(ws.name || '未命名') + '</div>';
    html += '<div class="workspace-item-path">' + escapeHtml(ws.path || '') + '</div>';
    html += '</div>';
    if (!isActive) {
      html += '<button class="workspace-item-remove" onclick="event.stopPropagation();removeWorkspace(\'' + ws.id + '\')" title="移除">×</button>';
    }
    html += '</div>';
  }
  listEl.innerHTML = html;
}

function toggleWorkspaceDropdown() {
  var dropdown = document.getElementById('workspaceDropdown');
  var selector = document.getElementById('workspaceSelector');
  if (dropdown && selector) {
    dropdown.classList.toggle('open');
    selector.classList.toggle('open');
    if (dropdown.classList.contains('open')) {
      hideWorkspaceAddDialog();
    }
  }
}

function switchWorkspace(wsId) {
  if (!wsId) return;
  // 关闭下拉
  var dropdown = document.getElementById('workspaceDropdown');
  var selector = document.getElementById('workspaceSelector');
  if (dropdown) dropdown.classList.remove('open');
  if (selector) selector.classList.remove('open');
  // 显示过渡动画
  showWorkspaceTransition();
  // 调用后端切换
  if (typeof window._callPython === 'function') {
    try {
      window._callPython('switchWorkspace', [wsId], function(result) {
        onWorkspaceSwitched(result);
      });
    } catch(e) {
      console.error('[Workspace] 切换失败:', e);
      hideWorkspaceTransition();
    }
  } else {
    hideWorkspaceTransition();
  }
  // 安全兜底：3秒后自动隐藏过渡
  setTimeout(function() { hideWorkspaceTransition(); }, 3000);
}

function onWorkspaceSwitched(result) {
  if (!result) { hideWorkspaceTransition(); return; }
  if (result.workspace) {
    _currentWorkspace = result.workspace;
  }
  if (result.workspaces) {
    _workspaceList = result.workspaces;
  } else {
    // 重新加载列表
    loadWorkspaces();
  }
  updateWorkspaceDisplay();
  renderWorkspaceList();
  // 隐藏过渡动画
  setTimeout(function() { hideWorkspaceTransition(); }, 400);
}

function removeWorkspace(wsId) {
  if (!wsId) return;
  _showConfirm('移除工作区', '确定要移除这个工作区吗？（不会删除实际文件）', function() {
  if (typeof window._callPython === 'function') {
    try {
      window._callPython('removeWorkspace', [wsId], function(result) {
        if (result && result.success) {
          if (result.workspaces) {
            _workspaceList = result.workspaces;
            renderWorkspaceList();
          }
        }
      });
    } catch(e) { console.error('[Workspace] 移除失败:', e); }
  }
  }); // _showConfirm callback
}

function showWorkspaceAddDialog() {
  var dialog = document.getElementById('workspaceAddDialog');
  var addBtn = document.getElementById('workspaceAddBtn');
  if (dialog) {
    dialog.classList.add('open');
    addBtn.style.display = 'none';
    var pathInput = document.getElementById('workspacePathInput');
    if (pathInput) pathInput.focus();
  }
}

function hideWorkspaceAddDialog() {
  var dialog = document.getElementById('workspaceAddDialog');
  var addBtn = document.getElementById('workspaceAddBtn');
  if (dialog) {
    dialog.classList.remove('open');
    if (addBtn) addBtn.style.display = '';
  }
  var pathInput = document.getElementById('workspacePathInput');
  var nameInput = document.getElementById('workspaceNameInput');
  if (pathInput) pathInput.value = '';
  if (nameInput) nameInput.value = '';
}

function confirmAddWorkspace() {
  var pathInput = document.getElementById('workspacePathInput');
  var nameInput = document.getElementById('workspaceNameInput');
  var path = pathInput ? pathInput.value.trim() : '';
  var name = nameInput ? nameInput.value.trim() : '';
  if (!path) {
    pathInput.style.borderColor = '#f85149';
    setTimeout(function() { pathInput.style.borderColor = ''; }, 1500);
    return;
  }
  if (typeof window._callPython === 'function') {
    try {
      window._callPython('addWorkspace', [path, name], function(result) {
        if (result && result.workspace) {
          hideWorkspaceAddDialog();
          if (result.workspaces) {
            _workspaceList = result.workspaces;
            renderWorkspaceList();
          }
        } else if (result && result.error) {
          showToast('添加失败: ' + result.error);
        }
      });
    } catch(e) { console.error('[Workspace] 添加失败:', e); }
  }
}

function refreshWorkspace() {
  loadWorkspaces();
}

function openWorkspaceInExplorer() {
  if (!_currentWorkspace || !_currentWorkspace.path) {
    showToast('请先选择一个工作区');
    return;
  }
  // 通过后端打开资源管理器（使用 explorer 命令）
  if (typeof window._callPython === 'function') {
    try {
      window._callPython('sendMessage', '请打开文件夹: ' + _currentWorkspace.path);
    } catch(e) {}
  }
}

function showWorkspaceTransition() {
  var trans = document.getElementById('workspaceTransition');
  if (trans) trans.classList.add('active');
}

function hideWorkspaceTransition() {
  var trans = document.getElementById('workspaceTransition');
  if (trans) trans.classList.remove('active');
}

// ============================================================
// ★ 调试面板 JS
// ============================================================
var _debugState = 'idle';
var _debugWatchExprs = [];
var _debugBreakpoints = [];

function toggleDebugPanel() {
  var panel = document.getElementById('debugPanel');
  if (panel) panel.classList.toggle('collapsed');
}

function switchDebugTab(tabName, el) {
  // 切换标签页
  var tabs = document.querySelectorAll('.debug-tab');
  tabs.forEach(function(t) { t.classList.remove('active'); });
  if (el) el.classList.add('active');
  // 切换内容
  var sections = document.querySelectorAll('.debug-section');
  sections.forEach(function(s) { s.classList.remove('active'); });
  var section = document.getElementById('debugSection' + tabName.charAt(0).toUpperCase() + tabName.slice(1));
  if (section) section.classList.add('active');
  // 切换到变量/栈/断点标签时刷新数据
  if (tabName === 'variables') debugRefreshVariables();
  else if (tabName === 'stack') debugRefreshStackTrace();
  else if (tabName === 'breakpoints') debugRefreshBreakpoints();
}

function debugCall(method, args, callback) {
  if (typeof window._callPython === 'function') {
    try {
      window._callPython(method, args || [], callback);
    } catch(e) { console.error('[Debug] ' + method + ' 失败:', e); }
  }
}

function debugStart() {
  // 获取当前工作区路径作为 cwd
  var cwd = (_currentWorkspace && _currentWorkspace.path) || '';
  _showInput('启动调试', '请输入要调试的 Python 文件路径：', cwd ? cwd + '\\main.py' : '', function(program) {
    if (!program) return;
    debugCall('debugStart', [program, cwd], function(result) {
      if (result && result.success) {
        updateDebugState('running');
        debugRefreshBreakpoints();
      } else {
        showToast('启动调试失败: ' + (result && result.message ? result.message : '未知错误'));
      }
    });
  });
}

function debugContinue() {
  debugCall('debugContinue', [], function(result) {
    if (result && result.success) updateDebugState('running');
  });
}

function debugPause() {
  debugCall('debugPause', [], function(result) {
    if (result && result.success) updateDebugState('stopped');
  });
}

function debugStop() {
  debugCall('debugStop', [], function(result) {
    if (result && result.success) updateDebugState('idle');
  });
}

function debugStep(stepType) {
  debugCall('debugStep', [stepType], function(result) {
    if (result && result.success) {
      // 步进后刷新数据
      setTimeout(function() {
        debugRefreshVariables();
        debugRefreshStackTrace();
      }, 200);
    }
  });
}

function debugRefreshVariables() {
  // 局部变量
  debugCall('debugGetVariables', ['local'], function(result) {
    if (result && result.variables) {
      renderDebugVariables('debugLocalVars', result.variables);
      updateBadge('debugVarCount', result.variables.length);
    }
  });
  // 全局变量
  debugCall('debugGetVariables', ['global'], function(result) {
    if (result && result.variables) {
      renderDebugVariables('debugGlobalVars', result.variables);
    }
  });
  // 监视表达式
  refreshWatchExprs();
}

function renderDebugVariables(containerId, variables) {
  var el = document.getElementById(containerId);
  if (!el) return;
  if (!variables || variables.length === 0) {
    el.innerHTML = '<div class="debug-empty">无变量</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < variables.length; i++) {
    var v = variables[i];
    html += '<div class="debug-var-item" title="' + escapeHtml(v.name + ' = ' + v.value) + '">';
    html += '<span class="debug-var-name">' + escapeHtml(v.name) + '</span>';
    html += '<span class="debug-var-value">' + escapeHtml(v.value) + '</span>';
    if (v.type) html += '<span class="debug-var-type">' + escapeHtml(v.type) + '</span>';
    html += '</div>';
  }
  el.innerHTML = html;
}

function debugRefreshStackTrace() {
  debugCall('debugGetStackTrace', [], function(result) {
    if (result && result.frames) {
      renderDebugStackTrace(result.frames);
      updateBadge('debugStackCount', result.frames.length);
    }
  });
}

function renderDebugStackTrace(frames) {
  var el = document.getElementById('debugStackList');
  if (!el) return;
  if (!frames || frames.length === 0) {
    el.innerHTML = '<div class="debug-empty">无调用栈信息</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < frames.length; i++) {
    var f = frames[i];
    var isCurrent = i === 0;
    var fileName = f.file ? f.file.split(/[\\/]/).pop() : '<unknown>';
    html += '<div class="debug-stack-item' + (isCurrent ? ' current' : '') + '" onclick="jumpToStackFrame(\'' + escapeHtml(f.file || '') + '\',' + f.line + ')" title="' + escapeHtml(f.file || '') + '">';
    html += '<div class="debug-stack-name">' + escapeHtml(f.name) + '</div>';
    html += '<div class="debug-stack-location">' + escapeHtml(fileName) + ':' + f.line + '</div>';
    html += '</div>';
  }
  el.innerHTML = html;
}

function jumpToStackFrame(file, line) {
  // 通过后端打开文件到指定行
  if (file) {
    debugCall('debugEvaluate', ['open("' + file + ':' + line + '")']);
  }
}

function debugRefreshBreakpoints() {
  debugCall('debugGetBreakpoints', [], function(result) {
    if (result && result.breakpoints) {
      _debugBreakpoints = result.breakpoints;
      renderDebugBreakpoints(result.breakpoints);
      updateBadge('debugBpCount', result.breakpoints.length);
    }
  });
}

function renderDebugBreakpoints(breakpoints) {
  var el = document.getElementById('debugBpList');
  if (!el) return;
  if (!breakpoints || breakpoints.length === 0) {
    el.innerHTML = '<div class="debug-empty">无断点</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < breakpoints.length; i++) {
    var bp = breakpoints[i];
    var fileName = bp.file ? bp.file.split(/[\\/]/).pop() : '<unknown>';
    var bpId = 'bp_' + i;
    html += '<div class="debug-bp-item" id="' + bpId + '">';
    html += '<span class="debug-bp-dot' + (bp.enabled ? '' : ' disabled') + '"></span>';
    html += '<div class="debug-bp-info">';
    html += '<div class="debug-bp-file">' + escapeHtml(fileName) + '</div>';
    html += '<div class="debug-bp-line">行 ' + bp.line + (bp.condition ? ' · 条件: ' + escapeHtml(bp.condition) : '') + '</div>';
    html += '</div>';
    html += '<button class="debug-bp-remove" onclick="debugRemoveBreakpoint(\'' + escapeHtml(bp.file) + '\',' + bp.line + ')" title="删除断点">×</button>';
    html += '</div>';
  }
  el.innerHTML = html;
}

function debugRemoveBreakpoint(file, line) {
  debugCall('debugRemoveBreakpoint', [file, line], function(result) {
    if (result && result.success) {
      debugRefreshBreakpoints();
    }
  });
}

function debugToggleBreakpoint(file, line) {
  debugCall('debugToggleBreakpoint', [file, line], function(result) {
    if (result && result.success) {
      debugRefreshBreakpoints();
    }
  });
}

function addWatchExpr() {
  var input = document.getElementById('debugWatchInput');
  if (!input || !input.value.trim()) return;
  var expr = input.value.trim();
  if (_debugWatchExprs.indexOf(expr) === -1) {
    _debugWatchExprs.push(expr);
  }
  input.value = '';
  refreshWatchExprs();
}

function removeWatchExpr(expr) {
  var idx = _debugWatchExprs.indexOf(expr);
  if (idx !== -1) {
    _debugWatchExprs.splice(idx, 1);
    refreshWatchExprs();
  }
}

function refreshWatchExprs() {
  var el = document.getElementById('debugWatchList');
  if (!el) return;
  if (_debugWatchExprs.length === 0) {
    el.innerHTML = '<div class="debug-empty">无监视表达式</div>';
    return;
  }
  var html = '';
  var pending = _debugWatchExprs.length;
  for (var i = 0; i < _debugWatchExprs.length; i++) {
    (function(expr) {
      debugCall('debugEvaluate', [expr], function(result) {
        var value = (result && result.result) ? result.result : '<unavailable>';
        var idx = _debugWatchExprs.indexOf(expr);
        // 直接渲染（可能乱序，但简单有效）
        var item = document.createElement('div');
        item.className = 'debug-var-item';
        item.innerHTML = '<span class="debug-var-name">' + escapeHtml(expr) + '</span>' +
                         '<span class="debug-var-value">' + escapeHtml(value) + '</span>' +
                         '<button class="debug-bp-remove" onclick="removeWatchExpr(\'' + escapeHtml(expr) + '\')" title="移除">×</button>';
        el.appendChild(item);
      });
    })(_debugWatchExprs[i]);
  }
  el.innerHTML = '';
}

function updateDebugState(state) {
  _debugState = state;
  var badge = document.getElementById('debugStateBadge');
  if (badge) {
    badge.textContent = state;
    badge.className = 'debug-state-badge ' + state;
  }
  // 更新按钮状态
  var isRunning = state === 'running';
  var isStopped = state === 'stopped';
  var isActive = isRunning || isStopped;
  setBtnDisabled('debugStartBtn', isActive);
  setBtnDisabled('debugContinueBtn', !isStopped);
  setBtnDisabled('debugPauseBtn', !isRunning);
  setBtnDisabled('debugStopBtn', !isActive);
  setBtnDisabled('debugStepOverBtn', !isStopped);
  setBtnDisabled('debugStepIntoBtn', !isStopped);
  setBtnDisabled('debugStepOutBtn', !isStopped);
  // 如果停止状态，自动刷新变量和调用栈
  if (isStopped) {
    debugRefreshVariables();
    debugRefreshStackTrace();
  }
}

function setBtnDisabled(btnId, disabled) {
  var btn = document.getElementById(btnId);
  if (btn) btn.disabled = disabled;
}

function updateBadge(badgeId, count) {
  var badge = document.getElementById(badgeId);
  if (badge) badge.textContent = count;
}

function appendDebugOutput(category, text) {
  var el = document.getElementById('debugOutputList');
  if (!el) return;
  var line = document.createElement('div');
  line.textContent = '[' + category + '] ' + text;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

// Python 回调：调试状态变更
function onDebugStateChanged(state) {
  updateDebugState(state);
}

// Python 回调：断点命中
function onDebugBreakpointHit(file, line) {
  appendDebugOutput('breakpoint', '断点命中: ' + file + ':' + line);
  updateDebugState('stopped');
}

// Python 回调：调试输出
function onDebugOutput(category, text) {
  appendDebugOutput(category, text);
}

// Python 回调：调试终止
function onDebugTerminated() {
  updateDebugState('idle');
  appendDebugOutput('terminated', '调试会话已终止');
}

// ============================================================
// ★ 插件市场 JS
// ============================================================
// 别名：统一使用 callPython 调用 Python 桥接
var callPython = window._callPython || function() { console.warn('Python 桥接未就绪'); };
var _pluginTab = 'market';
var _pluginList = [];
var _pluginSearchQuery = '';
var _pluginSelectedName = '';

function togglePluginPanel() {
  var panel = document.getElementById('pluginPanel');
  if (!panel) return;
  panel.classList.toggle('collapsed');
  if (!panel.classList.contains('collapsed') && _pluginList.length === 0) {
    loadPlugins();
  }
}

function switchPluginTab(tabName, el) {
  _pluginTab = tabName;
  // 更新标签高亮
  document.querySelectorAll('.plugin-tab').forEach(function(t) { t.classList.remove('active'); });
  if (el) el.classList.add('active');
  renderPluginContent();
}

function onPluginSearchInput(value) {
  _pluginSearchQuery = value || '';
  if (_pluginSearchQuery.length > 0) {
    // 搜索模式：调用后端搜索
    callPython('searchPlugins', [_pluginSearchQuery], function(data) {
      if (data && data.ok) {
        _pluginList = data.plugins || [];
        renderPluginContent();
      }
    });
  } else {
    loadPlugins();
  }
}

function loadPlugins() {
  callPython('listPlugins', [], function(data) {
    if (data && data.ok) {
      _pluginList = data.plugins || [];
      updatePluginBadges();
      renderPluginContent();
    } else {
      document.getElementById('pluginContent').innerHTML =
        '<div class="plugin-empty">加载失败</div>';
    }
  });
}

function updatePluginBadges() {
  var totalCount = _pluginList.length;
  var installedCount = _pluginList.filter(function(p) { return p.is_installed; }).length;
  var marketBadge = document.getElementById('pluginMarketCount');
  var installedBadge = document.getElementById('pluginInstalledCount');
  if (marketBadge) marketBadge.textContent = totalCount;
  if (installedBadge) installedBadge.textContent = installedCount;
}

function renderPluginContent() {
  var container = document.getElementById('pluginContent');
  if (!container) return;

  if (_pluginTab === 'market') {
    renderPluginGrid(_pluginList);
  } else if (_pluginTab === 'installed') {
    var installed = _pluginList.filter(function(p) { return p.is_installed; });
    renderPluginGrid(installed);
  } else if (_pluginTab === 'config') {
    renderPluginConfigTab(container);
  }
}

function renderPluginGrid(plugins) {
  var container = document.getElementById('pluginContent');
  if (!container) return;
  if (!plugins || plugins.length === 0) {
    container.innerHTML = '<div class="plugin-empty">暂无插件</div>';
    return;
  }
  var html = '<div class="plugin-grid">';
  plugins.forEach(function(p) {
    var cardClass = p.is_installed ? 'plugin-card installed' : 'plugin-card';
    var tagsHtml = (p.tags || []).slice(0, 3).map(function(t) {
      return '<span class="plugin-tag">' + escapeHtml(t) + '</span>';
    }).join('');
    // 操作按钮
    var actionsHtml = '';
    if (p.is_installed) {
      var toggleClass = p.is_enabled ? 'plugin-toggle on' : 'plugin-toggle';
      actionsHtml =
        '<button class="plugin-btn" onclick="event.stopPropagation();showPluginDetail(\'' + p.name + '\')">详情</button>' +
        '<button class="plugin-btn danger" onclick="event.stopPropagation();uninstallPlugin(\'' + p.name + '\')">卸载</button>' +
        '<div class="' + toggleClass + '" onclick="event.stopPropagation();togglePluginEnable(\'' + p.name + '\', ' + !p.is_enabled + ')"></div>';
    } else {
      actionsHtml =
        '<button class="plugin-btn primary" onclick="event.stopPropagation();installPlugin(\'' + p.name + '\')">安装</button>' +
        '<button class="plugin-btn" onclick="event.stopPropagation();showPluginDetail(\'' + p.name + '\')">详情</button>';
    }
    html +=
      '<div class="' + cardClass + '" onclick="showPluginDetail(\'' + p.name + '\')">' +
        '<div class="plugin-card-header">' +
          '<span class="plugin-card-icon">' + (p.icon || SVG_ICONS.package) + '</span>' +
          '<span class="plugin-card-name">' + escapeHtml(p.display_name || p.name) + '</span>' +
          '<span class="plugin-card-version">v' + escapeHtml(p.version || '1.0.0') + '</span>' +
        '</div>' +
        '<div class="plugin-card-desc">' + escapeHtml(p.description || '') + '</div>' +
        (tagsHtml ? '<div class="plugin-card-tags">' + tagsHtml + '</div>' : '') +
        '<div class="plugin-card-actions">' + actionsHtml + '</div>' +
      '</div>';
  });
  html += '</div>';
  container.innerHTML = html;
}

function renderPluginConfigTab(container) {
  var installed = _pluginList.filter(function(p) { return p.is_installed; });
  if (installed.length === 0) {
    container.innerHTML = '<div class="plugin-empty">未安装任何插件，无配置项</div>';
    return;
  }
  // 获取每个已安装插件的配置 schema
  var pending = installed.length;
  var results = {};
  installed.forEach(function(p) {
    callPython('getPluginConfigSchema', [p.name], function(data) {
      if (data && data.ok && data.schema && data.schema.schema) {
        results[p.name] = data.schema;
      }
      pending--;
      if (pending === 0) {
        renderPluginConfigForms(container, results);
      }
    });
  });
}

function renderPluginConfigForms(container, schemas) {
  var html = '';
  var hasAny = false;
  for (var name in schemas) {
    var schemaData = schemas[name];
    var schema = schemaData.schema || {};
    var current = schemaData.current || {};
    var defaultCfg = schemaData.default || {};
    var keys = Object.keys(schema);
    if (keys.length === 0) continue;
    hasAny = true;
    var pluginInfo = _pluginList.find(function(p) { return p.name === name; });
    html +=
      '<div style="margin-bottom:14px;">' +
        '<div style="font-size:12px;font-weight:600;color:var(--text-primary,#f0f0f0);margin-bottom:6px;">' +
          (pluginInfo ? (pluginInfo.icon || SVG_ICONS.package) + ' ' + escapeHtml(pluginInfo.display_name || name) : name) +
        '</div>';
    keys.forEach(function(key) {
      var item = schema[key];
      var val = current[key] !== undefined ? current[key] : item.default;
      var label = item.label || key;
      var inputHtml = '';
      if (item.type === 'boolean') {
        inputHtml =
          '<div class="plugin-toggle ' + (val ? 'on' : '') + '" onclick="togglePluginConfigBool(\'' + name + '\',\'' + key + '\',this)"></div>';
      } else if (item.type === 'integer') {
        inputHtml =
          '<input type="number" class="plugin-config-input" value="' + val + '"' +
          (item.min !== undefined ? ' min="' + item.min + '"' : '') +
          (item.max !== undefined ? ' max="' + item.max + '"' : '') +
          ' onchange="setPluginConfigValue(\'' + name + '\',\'' + key + '\', this.value)">';
      } else if (item.type === 'list') {
        var listVal = Array.isArray(val) ? val.join(', ') : (val || '');
        inputHtml =
          '<input type="text" class="plugin-config-input" style="width:160px;" value="' + escapeHtml(listVal) + '"' +
          ' placeholder="逗号分隔" onchange="setPluginConfigList(\'' + name + '\',\'' + key + '\', this.value)">';
      } else {
        inputHtml =
          '<input type="text" class="plugin-config-input" value="' + escapeHtml(val || '') + '"' +
          ' onchange="setPluginConfigValue(\'' + name + '\',\'' + key + '\', this.value)">';
      }
      html +=
        '<div class="plugin-config-row">' +
          '<span class="plugin-config-label">' + escapeHtml(label) + '</span>' +
          inputHtml +
        '</div>';
    });
    html += '</div>';
  }
  if (!hasAny) {
    html = '<div class="plugin-empty">已安装的插件没有可配置项</div>';
  }
  container.innerHTML = html;
}

function togglePluginConfigBool(name, key, el) {
  var isOn = el.classList.toggle('on');
  setPluginConfigValue(name, key, isOn);
}

function setPluginConfigValue(name, key, value) {
  // 获取当前完整配置，更新单项，再保存
  callPython('getPluginConfig', [name], function(data) {
    if (data && data.ok) {
      var config = data.config || {};
      // 尝试转换为合适的类型
      var numVal = Number(value);
      if (!isNaN(numVal) && value !== '' && typeof value === 'string') {
        config[key] = numVal;
      } else if (value === 'true') {
        config[key] = true;
      } else if (value === 'false') {
        config[key] = false;
      } else {
        config[key] = value;
      }
      callPython('setPluginConfig', [name, JSON.stringify(config)], function(r) {
        if (r && r.ok) {
          console.log('[Plugin] 配置已保存:', name, key);
        }
      });
    }
  });
}

function setPluginConfigList(name, key, value) {
  callPython('getPluginConfig', [name], function(data) {
    if (data && data.ok) {
      var config = data.config || {};
      config[key] = value.split(',').map(function(s) { return s.trim(); }).filter(function(s) { return s; });
      callPython('setPluginConfig', [name, JSON.stringify(config)], function(r) {
        if (r && r.ok) console.log('[Plugin] 列表配置已保存:', name, key);
      });
    }
  });
}

function installPlugin(name) {
  callPython('installPlugin', [name], function(data) {
    if (data && data.ok) {
      console.log('[Plugin] 安装成功:', name);
      loadPlugins();
    } else {
      showToast('安装失败: ' + (data ? data.error : '未知错误'));
    }
  });
}

function uninstallPlugin(name) {
  _showConfirm('卸载插件', '确定卸载插件 ' + name + ' ?', function() {
  callPython('uninstallPlugin', [name], function(data) {
    if (data && data.ok) {
      console.log('[Plugin] 卸载成功:', name);
      loadPlugins();
    } else {
      _showConfirm('卸载失败', data ? data.error : '未知错误', null, {icon: SVG_ICONS['circle-x'], okText: '关闭', danger: false});
    }
  });
  }); // _showConfirm callback
}

function togglePluginEnable(name, enable) {
  if (enable) {
    callPython('enablePlugin', [name], function(data) {
      if (data && data.ok) {
        console.log('[Plugin] 已启用:', name);
        loadPlugins();
      }
    });
  } else {
    callPython('disablePlugin', [name], function(data) {
      if (data && data.ok) {
        console.log('[Plugin] 已禁用:', name);
        loadPlugins();
      }
    });
  }
}

function reloadPlugin(name) {
  callPython('reloadPlugin', [name], function(data) {
    if (data && data.ok) {
      console.log('[Plugin] 热重载成功:', name);
      showToast('插件 ' + name + ' 热重载成功');
    } else {
      showToast('热重载失败: ' + (data ? data.error : '未知错误'));
    }
  });
}

function showPluginDetail(name) {
  _pluginSelectedName = name;
  callPython('getPluginDetail', [name], function(data) {
    if (data && data.ok && data.detail) {
      renderPluginDetail(data.detail);
    } else {
      showToast('获取详情失败');
    }
  });
}

function renderPluginDetail(d) {
  var modal = document.getElementById('pluginDetailModal');
  if (!modal) return;
  var runtime = d.runtime || {};
  var tools = runtime.tools || [];
  var perms = d.permissions || {};
  var permBadges =
    '<span class="plugin-perm-badge ' + (perms.file_access && perms.file_access !== 'none' ? 'allow' : 'deny') + '">文件:' + (perms.file_access || 'none') + '</span>' +
    '<span class="plugin-perm-badge ' + (perms.network_access ? 'allow' : 'deny') + '">网络:' + (perms.network_access ? '是' : '否') + '</span>' +
    '<span class="plugin-perm-badge ' + (perms.system_command ? 'allow' : 'deny') + '">命令:' + (perms.system_command ? '是' : '否') + '</span>';
  var toolsHtml = tools.map(function(t) {
    return '<span class="plugin-detail-tool">' + escapeHtml(t.name) + '</span>';
  }).join('');
  var actionsHtml = '';
  if (d.is_installed) {
    actionsHtml =
      '<button class="plugin-btn" onclick="reloadPlugin(\'' + d.name + '\')">' + SVG_ICONS['loader-circle'] + ' 热重载</button>' +
      '<button class="plugin-btn danger" onclick="closePluginDetail();uninstallPlugin(\'' + d.name + '\')">卸载</button>';
  } else {
    actionsHtml =
      '<button class="plugin-btn primary" onclick="closePluginDetail();installPlugin(\'' + d.name + '\')">安装</button>';
  }
  modal.innerHTML =
    '<div class="plugin-detail-header">' +
      '<span class="plugin-detail-icon">' + (d.icon || SVG_ICONS.package) + '</span>' +
      '<div>' +
        '<div class="plugin-detail-title">' + escapeHtml(d.display_name || d.name) + '</div>' +
        '<div class="plugin-detail-meta">v' + escapeHtml(d.version || '1.0.0') + ' · ' + escapeHtml(d.author || 'unknown') + ' · ' + escapeHtml(d.category || 'general') + '</div>' +
      '</div>' +
      '<button class="plugin-detail-close" onclick="closePluginDetail()">' + SVG_ICONS['circle-x'] + '</button>' +
    '</div>' +
    '<div class="plugin-detail-desc">' + escapeHtml(d.description || '') + '</div>' +
    (d.tags && d.tags.length > 0 ?
      '<div class="plugin-detail-section"><div class="plugin-detail-section-title">标签</div>' +
      d.tags.map(function(t) { return '<span class="plugin-tag">' + escapeHtml(t) + '</span>'; }).join(' ') + '</div>' : '') +
    (toolsHtml ?
      '<div class="plugin-detail-section"><div class="plugin-detail-section-title">工具 (' + tools.length + ')</div><div class="plugin-detail-tools">' + toolsHtml + '</div></div>' : '') +
    '<div class="plugin-detail-section"><div class="plugin-detail-section-title">权限</div>' + permBadges + '</div>' +
    (d.is_installed ?
      '<div class="plugin-detail-section"><div class="plugin-detail-section-title">安装信息</div>' +
      '<div style="font-size:11px;color:rgba(255,255,255,0.5);">安装时间: ' + escapeHtml(d.installed_at || '未知') + '<br>状态: ' + (d.is_enabled ? '已启用' : '已禁用') + '</div></div>' : '') +
    '<div style="display:flex;gap:6px;margin-top:16px;">' + actionsHtml + '</div>';
  document.getElementById('pluginDetailOverlay').classList.add('show');
}

function closePluginDetail() {
  document.getElementById('pluginDetailOverlay').classList.remove('show');
}

// Python 回调：插件列表更新通知
function onPluginListUpdated() {
  loadPlugins();
}

// 启动时延迟加载插件列表
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    // 预加载插件列表（不展开面板）
    callPython('listPlugins', [], function(data) {
      if (data && data.ok) {
        _pluginList = data.plugins || [];
        updatePluginBadges();
      }
    });
  }, 1500);
});

// ============================================================
// ★ Skills 技能面板 JS
// ============================================================
var _skillList = [];
var _skillCategories = {};
var _skillSearchQuery = '';
var _skillSelectedCategory = '';
var _skillDetailCache = {};

// ★ 376-1: 技能面板桥接胶水（技能区JS编写时预设的接口，此前缺失导致面板不可用）
// 走 __PYBRIDGE__ console 通道（与 runCode 相同机制），Python 侧经 _pybridgeCallback 回调
function callPython(method, args, callback) {
  var callbackId = Date.now() + Math.floor(Math.random() * 100000);
  window._pybridgeCallback = window._pybridgeCallback || {};
  window._pybridgeCallback[callbackId] = function(result) {
    if (typeof callback === 'function') callback(result);
    delete window._pybridgeCallback[callbackId];
  };
  console.log('__PYBRIDGE__:' + JSON.stringify({ method: method, args: args || [], callbackId: callbackId }));
}

function toggleSkillPanel() {
  var panel = document.getElementById('skillPanel');
  if (!panel) return;
  panel.classList.toggle('collapsed');
  if (!panel.classList.contains('collapsed') && _skillList.length === 0) {
    loadSkills();
  }
}

function onSkillSearchInput(value) {
  _skillSearchQuery = value || '';
  if (_skillSearchQuery.length > 0) {
    // 搜索模式：调用后端搜索
    callPython('searchSkills', [_skillSearchQuery], function(data) {
      if (data && data.ok) {
        _skillList = data.skills || [];
        window._skillHealthMap = data.health || window._skillHealthMap || {};
        renderSkillContent();
      }
    });
  } else {
    loadSkills();
  }
}

function filterSkillsByCategory(category, btn) {
  _skillSelectedCategory = category;
  // 更新按钮状态
  document.querySelectorAll('.skill-filter-btn').forEach(function(b) {
    b.classList.remove('active');
  });
  if (btn) btn.classList.add('active');
  // 重新加载或过滤
  if (category) {
    callPython('listSkills', [category], function(data) {
      if (data && data.ok) {
        _skillList = data.skills || [];
        window._skillHealthMap = data.health || window._skillHealthMap || {};
        renderSkillContent();
      }
    });
  } else {
    loadSkills();
  }
}

function loadSkills() {
  callPython('listSkills', [], function(data) {
    if (data && data.ok) {
      _skillList = data.skills || [];
      _skillCategories = data.categories || {};
      window._skillHealthMap = data.health || {};
      updateSkillFilters();
      renderSkillContent();
    } else {
      document.getElementById('skillContent').innerHTML =
        '<div class="skill-empty">加载失败</div>';
    }
  });
}

function updateSkillFilters() {
  var container = document.getElementById('skillFilters');
  if (!container) return;
  
  var html = '<button class="skill-filter-btn active" onclick="filterSkillsByCategory(\'\', this)">全部</button>';
  
  // 按数量排序分类（★ v4.1.11: 防 _skillCategories 非对象时崩溃）
  var _catObj = (_skillCategories && typeof _skillCategories === 'object' && !Array.isArray(_skillCategories)) ? _skillCategories : {};
  var sortedCategories = Object.keys(_catObj).sort(function(a, b) {
    return (_catObj[b] || 0) - (_catObj[a] || 0);
  });
  
  sortedCategories.forEach(function(cat) {
    var count = _catObj[cat] || 0;
    var displayName = cat;
    // 分类名称映射
    var nameMap = {
      'code': '代码执行',
      'file': '文件操作',
      'project': '项目管理',
      'knowledge': '知识库',
      'web': '网络操作',
      'system': '系统命令'
    };
    if (nameMap[cat]) {
      displayName = nameMap[cat];
    }
    html += '<button class="skill-filter-btn" onclick="filterSkillsByCategory(\'' + cat + '\', this)">' + 
            escapeHtml(displayName) + ' (' + count + ')</button>';
  });
  
  container.innerHTML = html;
}

function renderSkillContent() {
  var container = document.getElementById('skillContent');
  if (!container) return;
  
  if (!_skillList || _skillList.length === 0) {
    container.innerHTML = '<div class="skill-empty">暂无技能</div>';
    return;
  }
  
  var html = '<div class="skill-list">';
  var _hMap = window._skillHealthMap || {};
  _skillList.forEach(function(skill) {
    html += renderSkillCard(skill, _hMap);
  });
  html += '</div>';
  container.innerHTML = html;
}

// ★ 369-3: 技能健康度徽章颜色映射
function _healthBadgeStyle(status) {
  switch (status) {
    case 'PASS': return 'background:#4caf5022;color:#4caf50;border:1px solid #4caf5044;';
    case 'ARGCHECK': return 'background:#ff980022;color:#ff9800;border:1px solid #ff980044;';
    case 'FAIL': return 'background:#f4433622;color:#f44336;border:1px solid #f4433644;';
    case 'SKIP': return 'background:rgba(255,255,255,0.06);color:rgba(255,255,255,0.35);border:1px solid rgba(255,255,255,0.1);';
    default: return '';
  }
}

function renderSkillCard(skill, healthMap) {
  var name = skill.name || '';
  var desc = skill.description || '';
  var category = skill.category || 'general';
  var requiresConfirm = skill.requires_confirm || false;

  // ★ 369-3: 健康度徽章
  var healthBadge = '';
  var hMap = healthMap || window._skillHealthMap || {};
  var hInfo = hMap[name];
  if (hInfo && hInfo.status) {
    var badgeStyle = _healthBadgeStyle(hInfo.status);
    var tipText = hInfo.status;
    if (hInfo.duration) tipText += ' | ' + hInfo.duration.toFixed(2) + 's';
    if (hInfo.error) tipText += ' | ' + hInfo.error.substring(0, 80);
    healthBadge = '<span style="font-size:9px;border-radius:8px;padding:1px 5px;margin-left:4px;' + badgeStyle + '" title="' + escapeHtml(tipText) + '">' + hInfo.status + '</span>';
  }

  var cardHtml = 
    '<div class="skill-card" id="skill-' + name + '">' +
      '<div class="skill-card-header">' +
        '<div class="skill-card-name">' + escapeHtml(name) + healthBadge + '</div>' +
        '<div class="skill-card-category">' + escapeHtml(category) + '</div>' +
      '</div>' +
      '<div class="skill-card-desc">' + escapeHtml(desc) + '</div>' +
      '<div class="skill-card-actions">' +
        '<button class="skill-btn primary" onclick="executeSkillByName(\'' + name + '\')">执行</button>' +
        '<button class="skill-btn" onclick="toggleSkillDetail(\'' + name + '\')">详情</button>' +
        (requiresConfirm ? '<span style="font-size:9px;color:rgba(255,165,0,0.7);margin-left:8px;">▲ 需确认</span>' : '') +
      '</div>' +
      '<div class="skill-card-detail" id="skill-detail-' + name + '"></div>' +
    '</div>';
  
  return cardHtml;
}

function toggleSkillDetail(skillName) {
  var detailEl = document.getElementById('skill-detail-' + skillName);
  if (!detailEl) return;
  
  if (detailEl.classList.contains('show')) {
    detailEl.classList.remove('show');
    return;
  }
  
  // 检查缓存
  if (_skillDetailCache[skillName]) {
    renderSkillDetailContent(detailEl, _skillDetailCache[skillName]);
    detailEl.classList.add('show');
    return;
  }
  
  // 从后端获取详情
  callPython('getSkillDetail', [skillName], function(data) {
    if (data && data.ok && data.detail) {
      _skillDetailCache[skillName] = data.detail;
      renderSkillDetailContent(detailEl, data.detail);
      detailEl.classList.add('show');
    } else {
      detailEl.innerHTML = '<div class="skill-detail-section"><div class="skill-detail-content">获取详情失败</div></div>';
      detailEl.classList.add('show');
    }
  });
}

function renderSkillDetailContent(container, detail) {
  var paramsHtml = '';
  if (detail.parameters && detail.parameters.properties) {
    paramsHtml = '<div class="skill-detail-section">' +
      '<div class="skill-detail-label">参数定义:</div>' +
      '<div class="skill-detail-content skill-detail-params">' +
        escapeHtml(JSON.stringify(detail.parameters, null, 2)) +
      '</div>' +
    '</div>';
  }
  
  var infoHtml = '<div class="skill-detail-section">' +
    '<div class="skill-detail-label">基本信息:</div>' +
    '<div class="skill-detail-content">' +
      '超时时间: ' + (detail.timeout || 30) + ' 秒<br>' +
      '需要确认: ' + (detail.requires_confirm ? '是' : '否') +
    '</div>' +
  '</div>';
  
  container.innerHTML = infoHtml + paramsHtml;
}

function executeSkillByName(skillName) {
  // 显示执行中状态
  var card = document.getElementById('skill-' + skillName);
  if (card) {
    card.classList.add('skill-executing');
  }
  
  // 获取参数（可以后续扩展为弹窗输入）
  var params = {};
  
  callPython('executeSkill', [skillName, JSON.stringify(params)], function(data) {
    if (card) {
      card.classList.remove('skill-executing');
    }
    
    if (data) {
      var resultMsg = data.ok ? 
        (SVG_ICONS.check + ' ' + (data.output || '执行成功')) : 
        (SVG_ICONS['circle-x'] + ' ' + (data.error || '未知错误'));
      
      // ★ 使用自定义确认弹窗显示执行结果
      _showConfirm(
        data.ok ? '执行成功' : '执行失败',
        resultMsg,
        null,
        {icon: data.ok ? SVG_ICONS.check : SVG_ICONS['circle-x'], okText: '关闭', danger: !data.ok}
      );
      
      console.log('[Skills] 执行结果:', skillName, data);
    }
  });
}

// Python 回调：技能列表更新通知
function onSkillListUpdated() {
  loadSkills();
}

// 启动时延迟加载技能列表
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    // 预加载技能列表（不展开面板）
    callPython('listSkills', [], function(data) {
      if (data && data.ok) {
        _skillList = data.skills || [];
        _skillCategories = data.categories || {};
        window._skillHealthMap = data.health || {};
        updateSkillFilters();
      }
    });
  }, 2000);
});

// ============================================================
// ★ 性能优化模块（虚拟滚动已禁用，仅保留Canvas节流和事件委托）
// ============================================================
var PerfOpt = (function() {
  var _virtualScrollEnabled = false;  // ★ 永久禁用虚拟滚动
  var _container = null;
  var _fpsLastTime = performance.now();
  var _fpsFrameCount = 0;
  var _fpsCurrent = 0;
  var _fpsDisplay = null;
  var _fpsTimer = null;
  var _chartObserver = null;
  var _eventDelegated = false;

  // ===== 1. 虚拟滚动（已禁用） =====
  function initVirtualScroll() {
    // ★ 虚拟滚动已禁用 - 它会导致滚动回弹、消息隐藏、卡顿等一系列问题
    _virtualScrollEnabled = false;
    console.log('[PerfOpt] 虚拟滚动已永久禁用');
  }

  function _onVirtualScroll() { /* no-op */ }
  function _updateVirtualViewport() { /* no-op */ }
  function _applyVirtualRange(start, end) { /* no-op */ }

  function setMessageCount(count) {
    window._globalMsgCount = count;
    // ★ 不再启用虚拟滚动
  }

  // ===== 2. Canvas requestAnimationFrame 节流 =====
  var _canvasRenderQueue = [];
  var _canvasRafScheduled = false;

  function scheduleCanvasRender(canvasEl, renderFn) {
    _canvasRenderQueue.push({ el: canvasEl, fn: renderFn });
    if (!_canvasRafScheduled) {
      _canvasRafScheduled = true;
      requestAnimationFrame(_flushCanvasQueue);
    }
  }

  function _flushCanvasQueue() {
    _canvasRafScheduled = false;
    var queue = _canvasRenderQueue;
    _canvasRenderQueue = [];
    for (var i = 0; i < queue.length; i++) {
      try {
        if (queue[i].el && queue[i].el.parentNode) {
          queue[i].fn(queue[i].el);
        }
      } catch (e) {
        console.warn('[PerfOpt] Canvas 渲染错误:', e);
      }
    }
  }

  // ===== 3. DocumentFragment 批量插入 =====
  function batchAppend(parent, elements) {
    if (!parent || !elements || elements.length === 0) return;
    var fragment = document.createDocumentFragment();
    for (var i = 0; i < elements.length; i++) {
      fragment.appendChild(elements[i]);
    }
    parent.appendChild(fragment);
  }

  // ===== 4. 事件委托 =====
  function initEventDelegation() {
    if (_eventDelegated) return;
    _eventDelegated = true;
    var container = document.getElementById('outputMessages');
    if (!container) return;
    // 统一处理点击事件（代码块复制、工具展开等）
    container.addEventListener('click', function(e) {
      var target = e.target;
      // 代码块复制按钮
      var copyBtn = target.closest('.code-copy-btn');
      if (copyBtn) {
        var codeEl = copyBtn.parentElement.querySelector('code');
        if (codeEl) {
          _copyToClipboard(codeEl.textContent);
          copyBtn.innerHTML = SVG_ICONS.check;
          setTimeout(function() { copyBtn.innerHTML = SVG_ICONS['file-text']; }, 1500);
        }
        e.stopPropagation();
        return;
      }
      // 工具调用展开/折叠
      var toolHeader = target.closest('.tool-call-header');
      if (toolHeader) {
        var body = toolHeader.nextElementSibling;
        if (body) {
          body.style.display = body.style.display === 'none' ? '' : 'none';
        }
        e.stopPropagation();
        return;
      }
    });
    console.log('[PerfOpt] 事件委托已启用');
  }

  function _copyToClipboard(text) {
    try {
      navigator.clipboard.writeText(text);
    } catch (e) {
      var ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (e2) {}
      document.body.removeChild(ta);
    }
  }

  // ===== ★ 代码块工具栏：为所有代码块添加运行/复制按钮 =====
  function initCodeToolbars() {
    var container = document.getElementById('outputMessages');
    if (!container) return;
    
    // 查找所有代码块
    var codeBlocks = container.querySelectorAll('.codehilite, pre > code');
    codeBlocks.forEach(function(codeEl) {
      var pre = codeEl.tagName === 'PRE' ? codeEl : codeEl.closest('pre');
      if (!pre || pre.dataset.toolbarAdded) return;
      
      var codehilite = pre.closest('.codehilite') || pre;
      if (codehilite.dataset.toolbarAdded) return;
      
      // 标记已添加，避免重复
      codehilite.dataset.toolbarAdded = '1';
      
      // 获取语言类型
      var lang = '';
      var codeTag = codehilite.querySelector('code');
      if (codeTag) {
        var cls = codeTag.className || '';
        var match = cls.match(/language-(\w+)/);
        if (match) lang = match[1].toLowerCase();
      }
      
      // 判断是否可执行（Python/JS/Shell等）
      var executable = /^(python|py|javascript|js|node|bash|sh|shell|cmd|powershell|ps1)$/i.test(lang);
      
      // 创建工具栏
      var toolbar = document.createElement('div');
      toolbar.className = 'code-toolbar';
      
      // 运行按钮（仅对可执行语言显示）
      if (executable) {
        var runBtn = document.createElement('button');
        runBtn.className = 'code-toolbar-btn run-btn';
        runBtn.innerHTML = SVG_ICONS['chevron-down'];
        runBtn.title = '运行代码 (Ctrl+Enter)';
        runBtn.onclick = function(e) {
          e.stopPropagation();
          _runCodeBlock(codehilite, lang);
        };
        toolbar.appendChild(runBtn);
      }

      // ★ 400V-4: HTML 看板 [▶ 运行看板] 按钮 (AI回复的 ```html 代码块)
      if (lang === 'html') {
        var dashBtn = document.createElement('button');
        dashBtn.className = 'code-toolbar-btn dash-btn';
        dashBtn.innerHTML = SVG_ICONS['play'] || '▶';
        dashBtn.title = '运行看板 (sandbox 隔离)';
        dashBtn.onclick = function(e) {
          e.stopPropagation();
          _runHtmlDashboard(codehilite, lang);
        };
        toolbar.appendChild(dashBtn);
      }
      
      // 复制按钮
      var copyBtn = document.createElement('button');
      copyBtn.className = 'code-toolbar-btn';
        copyBtn.innerHTML = SVG_ICONS['file-text'];
      copyBtn.title = '复制代码';
      copyBtn.onclick = function(e) {
        e.stopPropagation();
        var code = codehilite.querySelector('code');
        if (code) {
          _copyToClipboard(code.textContent);
          copyBtn.innerHTML = SVG_ICONS.check;
          setTimeout(function() { copyBtn.innerHTML = SVG_ICONS['file-text']; }, 1500);
        }
      };
      toolbar.appendChild(copyBtn);
      
      // 插入工具栏到代码块
      codehilite.style.position = 'relative';
      codehilite.insertBefore(toolbar, codehilite.firstChild);
      
      // 创建输出区域（仅对可执行语言）
      if (executable) {
        var outputDiv = document.createElement('div');
        outputDiv.className = 'code-output';
        codehilite.appendChild(outputDiv);
      }
    });
  }

  // ★ 400V-4: HTML 看板运行 (sandbox 隔离, 右栏卡片内联渲染)
  //   安全约束: sandbox="allow-scripts" (禁同源, 防 cookie/存储逃逸);
  //   ≥2MB 或含外部网络请求(fetch/XMLHttpRequest/ws/http链接) → 提示确认;
  //   渲染结果跟在原代码块后(同卡片内, 不弹窗)。
  var _DASH_SIZE_MAX = 2 * 1024 * 1024; // 2MB
  var _DASH_EXTNET_RE = /(fetch\s*\(|XMLHttpRequest|WebSocket\s*\(|import\s*\(|<\s*script[^>]*\ssrc\s*=\s*["']https?:)/i;
  function _runHtmlDashboard(codehilite, lang) {
    var code = codehilite.querySelector('code');
    if (!code) return;
    var html = code.textContent || '';
    var size = html.length;
    var risky = size >= _DASH_SIZE_MAX || _DASH_EXTNET_RE.test(html);
    if (risky && !confirm('该看板较大的 (' + Math.round(size/1024) + 'KB) 或含外部网络请求.\n允许在主窗口 iframe sandbox="allow-scripts" 内运行?',
    )) {
      return;
    }
    // 复用代码块的输出位, 没有则新建
    var out = codehilite.querySelector('.code-output');
    if (!out) {
      out = document.createElement('div');
      out.className = 'code-output';
      codehilite.appendChild(out);
    }
    out.innerHTML = '';
    var frameBox = document.createElement('div');
    frameBox.style.cssText = 'margin-top:8px;border:1px solid rgba(255,255,255,0.1);border-radius:6px;overflow:hidden;background:#fff;';
    var iframe = document.createElement('iframe');
    iframe.style.cssText = 'width:100%;min-height:320px;height:60vh;border:0;background:#fff;';
    // sandbox="allow-scripts" 仅; 不含 allow-same-origin → 防 cookie/localStorage/同源逃逸
    iframe.sandbox = 'allow-scripts';
    iframe.setAttribute('title', 'html-dashboard');
    frameBox.appendChild(iframe);
    out.appendChild(frameBox);
    try {
      iframe.contentDocument.open();
      iframe.contentDocument.write(html);
      iframe.contentDocument.close();
    } catch(e) {
      frameBox.innerHTML = '<div style="padding:12px;color:#c678dd;">看板渲染失败: ' + esc(String(e)) + '</div>';
    }
  }

  // ★ 运行代码块
  function _runCodeBlock(codehilite, lang) {
    var code = codehilite.querySelector('code');
    if (!code) return;

    var codeText = code.textContent;
    var outputDiv = codehilite.querySelector('.code-output');
    if (!outputDiv) return;

    // ★ 沙箱模式检查
    var sandboxMode = _getSandboxMode();
    var isDangerousLang = ['bash', 'sh', 'shell', 'cmd', 'powershell', 'ps1', 'c', 'cpp', 'go'].indexOf(lang.toLowerCase()) >= 0;

    // 如果是危险语言且非信任模式，弹出确认框
    if (isDangerousLang && sandboxMode !== 'trust') {
      _showConfirm(
        '安全提示',
        '即将执行 ' + lang.toUpperCase() + ' 代码。编译型/系统语言可能会对系统造成影响。是否继续执行？（可在设置中将沙箱模式改为"信任模式"以跳过确认）',
        function() { _doExecuteCode(code, lang, outputDiv); },
        {icon: '▲', okText: '继续执行'}
      );
      return;
    }

    _doExecuteCode(code, lang, outputDiv);
  }

  // ★ 实际执行代码（从 executeCode 中提取，供确认对话框回调使用）
  function _doExecuteCode(code, lang, outputDiv) {
    var codeText = code.textContent || code.innerText || '';
    // 显示运行中状态
    outputDiv.className = 'code-output show';
    outputDiv.innerHTML = SVG_ICONS.hourglass + ' 运行中...';
    outputDiv.classList.remove('error');

    // 通过桥接调用Python执行代码
    if (window._pybridge) {
      try {
        window._pybridge.runCode(codeText, lang, function(result) {
          if (result.error) {
            outputDiv.className = 'code-output show error';
            outputDiv.innerHTML = SVG_ICONS['circle-x'] + ' 错误:<br>' + escapeHtml(result.error);
          } else if (result.is_html_preview) {
            _renderHtmlPreview(outputDiv, result.output);
          } else {
            outputDiv.className = 'code-output show';
            outputDiv.textContent = result.output || '(无输出)';
          }
        });
      } catch (e) {
        outputDiv.className = 'code-output show error';
        outputDiv.innerHTML = SVG_ICONS['circle-x'] + ' 桥接错误: ' + escapeHtml(e.message);
      }
    } else {
      var callbackId = Date.now();
      window._pybridgeCallback = window._pybridgeCallback || {};
      window._pybridgeCallback[callbackId] = function(result) {
        if (result.error) {
          outputDiv.className = 'code-output show error';
            outputDiv.innerHTML = SVG_ICONS['circle-x'] + ' 错误:<br>' + escapeHtml(result.error);
        } else if (result.is_html_preview) {
          _renderHtmlPreview(outputDiv, result.output);
        } else {
          outputDiv.className = 'code-output show';
          outputDiv.textContent = result.output || '(无输出)';
        }
        delete window._pybridgeCallback[callbackId];
      };

      var msg = '__PYBRIDGE__:' + JSON.stringify({
        method: 'runCode',
        args: [codeText, lang],
        callbackId: callbackId
      });
      console.log(msg);
    }
  }

  // ★ 获取沙箱模式设置
  function _getSandboxMode() {
    // 从localStorage读取（默认为manual）
    return localStorage.getItem('sandboxMode') || 'manual';
  }

  function _setSandboxMode(mode) {
    // 信任模式: trust（无确认）
    // 手动确认: manual（每次确认）
    // 严格模式: strict（禁止危险语言）
    localStorage.setItem('sandboxMode', mode);
  }

  // ★ HTML预览渲染
  function _renderHtmlPreview(container, encodedHtml) {
    if (!encodedHtml || !encodedHtml.startsWith('__HTML_PREVIEW__:')) {
      container.textContent = '(HTML预览数据无效)';
      return;
    }
    var base64Html = encodedHtml.slice('__HTML_PREVIEW__:'.length);
    try {
      var html = decodeURIComponent(escape(atob(base64Html)));
      container.innerHTML = '';
      // 创建iframe沙箱
      var iframe = document.createElement('iframe');
      iframe.style.cssText = 'width:100%;min-height:200px;max-height:400px;border:1px solid rgba(255,255,255,0.1);border-radius:6px;background:#fff;';
      iframe.sandbox = 'allow-scripts allow-same-origin';
      container.appendChild(iframe);
      // 写入HTML内容
      iframe.contentDocument.open();
      iframe.contentDocument.write(html);
      iframe.contentDocument.close();
      // 添加预览标签
      var label = document.createElement('div');
      label.style.cssText = 'font-size:10px;color:rgba(255,255,255,0.4);margin-top:4px;';
      label.innerHTML = SVG_ICONS.file + ' HTML预览';
      container.appendChild(label);
    } catch (e) {
      container.textContent = 'HTML预览解析失败: ' + e.message;
    }
  }

  // ===== 5. 图表懒加载（IntersectionObserver） =====
  function initLazyChartRendering() {
    if (!('IntersectionObserver' in window)) return;
    _chartObserver = new IntersectionObserver(function(entries) {
      for (var i = 0; i < entries.length; i++) {
        var entry = entries[i];
        if (entry.isIntersecting) {
          var el = entry.target;
          var renderFn = el.dataset.chartRenderFn;
          if (renderFn && window[renderFn]) {
            try {
              window[renderFn](el);
            } catch (e) {
              console.warn('[PerfOpt] 图表懒渲染错误:', e);
            }
          }
          el.dataset.chartRendered = '1';
          _chartObserver.unobserve(el);
        }
      }
    }, { rootMargin: '100px', threshold: 0.1 });
    console.log('[PerfOpt] 图表懒加载已启用');
  }

  function observeChart(el, renderFnName) {
    if (_chartObserver && el && !el.dataset.chartRendered) {
      el.dataset.chartRenderFn = renderFnName;
      _chartObserver.observe(el);
      return true;
    }
    return false;
  }

  // ===== 6. 内存清理 =====
  function cleanupSessionResources() {
    // 清理所有 Canvas 元素的引用
    var canvases = document.querySelectorAll('canvas');
    canvases.forEach(function(c) {
      try {
        var ctx = c.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, c.width, c.height);
      } catch (e) {}
    });
    // 清理图表观察者
    if (_chartObserver) {
      _chartObserver.disconnect();
      initLazyChartRendering();  // 重新初始化
    }
    // 清理 Canvas 渲染队列
    _canvasRenderQueue = [];
    // 清理隐藏消息的 DOM 引用
    if (_container) {
      var hidden = _container.querySelectorAll('[data-hidden="1"]');
      hidden.forEach(function(el) {
        _cleanupCanvasInElement(el);
      });
    }
    // 建议 GC
    if (window.gc) {
      try { window.gc(); } catch (e) {}
    }
    console.log('[PerfOpt] 会话资源已清理');
  }

  function _cleanupCanvasInElement(el) {
    if (!el) return;
    var canvases = el.querySelectorAll('canvas');
    canvases.forEach(function(c) {
      try {
        var ctx = c.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, c.width, c.height);
        c.width = 0;
        c.height = 0;
      } catch (e) {}
    });
  }

  // ===== 7. FPS 计数器（开发模式） =====
  function initFPSCounter() {
    // 仅在开发模式（URL 包含 localhost 或 ?dev=1）时显示
    var isDev = location.hostname === 'localhost' || location.hostname === '127.0.0.1' ||
                location.search.indexOf('dev=1') >= 0 ||
                localStorage.getItem('mimo_dev_mode') === '1';
    if (!isDev) return;

    _fpsDisplay = document.createElement('div');
    _fpsDisplay.style.cssText = [
      'position:fixed', 'bottom:4px', 'right:4px', 'z-index:9999',
      'background:rgba(0,0,0,0.7)', 'color:#0f0', 'padding:2px 6px',
      'border-radius:3px', 'font-size:10px', 'font-family:monospace',
      'pointer-events:none', 'min-width:60px', 'text-align:right',
    ].join(';');
    _fpsDisplay.textContent = 'FPS: --';
    document.body.appendChild(_fpsDisplay);

    _fpsLoop();
    console.log('[PerfOpt] FPS 计数器已启用（开发模式）');
  }

  function _fpsLoop() {
    _fpsFrameCount++;
    var now = performance.now();
    var elapsed = now - _fpsLastTime;
    if (elapsed >= 1000) {
      _fpsCurrent = Math.round((_fpsFrameCount * 1000) / elapsed);
      _fpsFrameCount = 0;
      _fpsLastTime = now;
      if (_fpsDisplay) {
        var color = _fpsCurrent >= 50 ? '#0f0' : (_fpsCurrent >= 30 ? '#ff0' : '#f00');
        _fpsDisplay.style.color = color;
        _fpsDisplay.textContent = 'FPS: ' + _fpsCurrent;
      }
    }
    requestAnimationFrame(_fpsLoop);
  }

  function getFPS() { return _fpsCurrent; }

  // ===== 初始化 =====
  function init() {
    initEventDelegation();
    initLazyChartRendering();
    initFPSCounter();
    // ★ 虚拟滚动已禁用，不再需要延迟初始化
    setTimeout(function() {
      var container = document.getElementById('outputMessages');
      if (container) {
        _container = container;
        window._globalMsgCount = container.children.length;
      }
    }, 2000);
    // ★ P9: 启动内存监控
    _startMemoryMonitor();
    console.log('[PerfOpt] 性能优化模块已初始化（虚拟滚动已禁用）');
  }

  // ★ P9: 消息数量限制（超过阈值自动裁剪旧消息）
  var MAX_MESSAGES = 200;
  var PRUNE_THRESHOLD = 250;
  var _pruneTimer = null;

  function pruneOldMessages() {
    var container = _container || document.getElementById('outputMessages');
    if (!container) return;
    var children = container.children;
    if (children.length <= PRUNE_THRESHOLD) return;
    var removeCount = children.length - MAX_MESSAGES;
    for (var i = 0; i < removeCount; i++) {
      if (children[0]) {
        container.removeChild(children[0]);
      }
    }
    console.log('[PerfOpt] 消息裁剪: 移除 ' + removeCount + ' 条旧消息, 剩余 ' + MAX_MESSAGES);
  }

  function checkMessageLimit() {
    var container = _container || document.getElementById('outputMessages');
    if (!container) return;
    if (container.children.length >= PRUNE_THRESHOLD) {
      pruneOldMessages();
    }
  }

  // ★ P9: DOM 大小监控
  function _startMemoryMonitor() {
    _pruneTimer = setInterval(function() {
      checkMessageLimit();
      _checkDOMMemory();
    }, 60000); // 每60秒检查一次
    console.log('[PerfOpt] 内存监控已启动 (60s间隔)');
  }

  function _checkDOMMemory() {
    var container = _container || document.getElementById('outputMessages');
    if (!container) return;
    var nodeCount = container.querySelectorAll('*').length;
    var msgCount = container.children.length;
    // 如果DOM节点数超过3000，强制清理
    if (nodeCount > 3000) {
      console.warn('[PerfOpt] DOM节点过多: ' + nodeCount + ', 消息: ' + msgCount + ', 执行裁剪');
      pruneOldMessages();
    }
    // 如果消息数超过警告阈值
    if (msgCount > 150) {
      console.log('[PerfOpt] 消息数: ' + msgCount + ', DOM节点: ' + nodeCount);
    }
  }

  // ★ P9: 清理不可见元素（Canvas等）
  function cleanupInvisibleCanvases() {
    var container = _container || document.getElementById('outputMessages');
    if (!container) return;
    var canvases = container.querySelectorAll('canvas');
    var cleaned = 0;
    for (var i = 0; i < canvases.length; i++) {
      var canvas = canvases[i];
      var rect = canvas.getBoundingClientRect();
      // 远在视口上方的Canvas，释放其上下文
      if (rect.bottom < -500) {
        var ctx = canvas.getContext('2d');
        if (ctx) {
          canvas.width = 0;
          canvas.height = 0;
          cleaned++;
        }
      }
    }
    if (cleaned > 0) console.log('[PerfOpt] 清理 ' + cleaned + ' 个不可见Canvas');
  }

  // ★ P9: 获取内存使用状态
  function getMemoryStatus() {
    var status = { messages: 0, domNodes: 0, canvasCount: 0, memoryMB: 0 };
    var container = _container || document.getElementById('outputMessages');
    if (container) {
      status.messages = container.children.length;
      status.domNodes = container.querySelectorAll('*').length;
      status.canvasCount = container.querySelectorAll('canvas').length;
    }
    // 尝试获取浏览器内存信息（Chrome only）
    if (performance.memory) {
      status.memoryMB = Math.round(performance.memory.usedJSHeapSize / 1024 / 1024);
    }
    return status;
  }

  // ★ P9: 强制清理（切换会话时调用）
  function forceCleanup() {
    pruneOldMessages();
    cleanupInvisibleCanvases();
    // 清理所有定时器引用
    if (_pruneTimer) clearInterval(_pruneTimer);
    console.log('[PerfOpt] 强制清理完成');
  }

  return {
    init: init,
    setMessageCount: setMessageCount,
    scheduleCanvasRender: scheduleCanvasRender,
    batchAppend: batchAppend,
    observeChart: observeChart,
    cleanupSessionResources: cleanupSessionResources,
    getFPS: getFPS,
    pruneOldMessages: pruneOldMessages,
    checkMessageLimit: checkMessageLimit,
    getMemoryStatus: getMemoryStatus,
    forceCleanup: forceCleanup,
    cleanupInvisibleCanvases: cleanupInvisibleCanvases,
  };
})();

// 启动性能优化模块
document.addEventListener('DOMContentLoaded', function() {
  PerfOpt.init();
  updateModelDisplay();
  // ★ v4.1.14: 启动时主动拉取后端真实活动引擎+模型（替代硬编码占位符 mimo-auto）
  // 不阻塞 UI；拉到后再 updateModelDisplay 一次
  setTimeout(function() {
    if (typeof window._callPython === 'function') {
      window._callPython('getCurrentModel', [], function(result) {
        try {
          if (typeof result === 'string') result = JSON.parse(result);
          if (result && result.success && result.model) {
            _currentModel.provider = result.engine || 'mimocode';
            _currentModel.modelId = result.model;
            _currentModel.modelName = result.display || result.model;
            updateModelDisplay();
          }
        } catch(e) { console.warn('[Model] 解析 getCurrentModel 失败:', e); }
      });
      ['mimocode', 'ollama', 'deepseek'].forEach(function(eng) {
        window._callPython('getEngineStatus', [], function(st) {
          try {
            if (st && st.success && st.status) {
              var engines = st.status.engines || {};
              var e = engines[eng];
              if (e) {
                setModelConnectionStatus(eng, e.available ? 'online' : 'offline');
              }
            }
          } catch(ex) {}
        });
        loadEngineModels(eng);
      });
    }
  }, 300);
});

// ===== 全局键盘快捷键 =====
document.addEventListener('keydown', function(e) {
  // Ctrl+P: 命令面板
  if (e.ctrlKey && e.key === 'p') {
    e.preventDefault();
    toggleCmdPanel();
    return;
  }
  // ★ 调试快捷键（F5/F9/F10/F11）
  if (e.key === 'F5') {
    e.preventDefault();
    if (_debugState === 'idle') debugStart();
    else if (_debugState === 'stopped') debugContinue();
    return;
  }
  if (e.key === 'F9') {
    e.preventDefault();
    // F9: 切换断点（需要编辑器集成，暂用提示）
    debugRefreshBreakpoints();
    return;
  }
  if (e.key === 'F10') {
    e.preventDefault();
    debugStep('over');
    return;
  }
  if (e.key === 'F11' && !e.shiftKey) {
    e.preventDefault();
    debugStep('into');
    return;
  }
  if (e.key === 'F11' && e.shiftKey) {
    e.preventDefault();
    debugStep('out');
    return;
  }
  // Ctrl+L: 清除输出
  if (e.ctrlKey && e.key === 'l') {
    e.preventDefault();
    clearOutput();
    return;
  }
  // Ctrl+,: 打开设置面板
  if (e.ctrlKey && e.key === ',') {
    e.preventDefault();
    openSettings();
    return;
  }
  // Ctrl+Shift+Enter: 强制发送（在输入框外触发）
  if (e.ctrlKey && e.shiftKey && e.key === 'Enter') {
    e.preventDefault();
    sendMessage();
    return;
  }
  // Tab: 模式切换
  if (e.key === 'Tab') {
    // 只在输入框没有焦点时触发模式面板
    var activeEl = document.activeElement;
    if (activeEl && activeEl.id === 'inputField') {
      return; // 输入框中 Tab 用于缩进
    }
    e.preventDefault();
    toggleModePanel();
    return;
  }
  // ?: 快捷键提示 或 Escape
  if (e.key === '?' && !e.ctrlKey && !e.altKey && !e.metaKey) {
    var activeEl = document.activeElement;
    if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA')) {
      return; // 输入框中 ? 用于输入
    }
    e.preventDefault();
    _showShortcutsHelp();
    return;
  }
  if (e.key === 'Escape') {
    // 关闭所有面板
    if (document.getElementById('modePanel').classList.contains('show')) {
      closeModePanel(); return;
    }
    if (document.getElementById('modelPanel').classList.contains('show')) {
      closeModelPanel(); return;
    }
    if (document.getElementById('sessionPanel').classList.contains('show')) {
      closeSessionPanel(); return;
    }
    if (document.getElementById('cmdOverlay').classList.contains('show')) {
      closeCmdPanel(); return;
    }
    if (document.getElementById('configOverlay').classList.contains('show')) {
      closeConfigPanel(); return;
    }
    if (document.getElementById('permissionOverlay').classList.contains('show')) {
      document.getElementById('permissionOverlay').classList.remove('show'); return;
    }
  }
});

// ===== 配置选项渲染 =====
function renderConfigOptions(options) {
  var container = document.getElementById('configOptionsContainer');
  container.innerHTML = '';
  
  var hasMultiple = options.length > 1;
  document.getElementById('configTitle').textContent = hasMultiple ? '配置选项' : (options[0] ? options[0].name : '配置选项');
  document.getElementById('configDesc').textContent = hasMultiple ? '请选择以下配置项' : (options[0] ? (options[0].description || '请选择一个选项') : '');
  
  options.forEach(function(opt) {
    var div = document.createElement('div');
    div.className = 'config-option';
    div.dataset.optId = opt.id;
    
    if (opt.type === 'select') {
      div.innerHTML = '<div class="opt-name">' + (opt.name || opt.id) + '</div>' +
        (opt.description ? '<div class="opt-desc">' + opt.description + '</div>' : '') +
        '<select id="sel_' + opt.id + '">' +
        (opt.select_options || []).map(function(so) {
          if (so.group) {
            return '<optgroup label="' + so.name + '">' +
              (so.options || []).map(function(gso) {
                return '<option value="' + gso.value + '"' + (gso.value === opt.current_value ? ' selected' : '') + '>' + gso.name + '</option>';
              }).join('') +
              '</optgroup>';
          }
          return '<option value="' + so.value + '"' + (so.value === opt.current_value ? ' selected' : '') + '>' + so.name + '</option>';
        }).join('') +
        '</select>';
    } else if (opt.type === 'boolean') {
      var isOn = opt.current_value === true;
      div.innerHTML = '<div class="toggle-row">' +
        '<div class="toggle-switch' + (isOn ? ' on' : '') + '" id="toggle_' + opt.id + '" onclick="toggleBoolean(\'' + opt.id + '\')"></div>' +
        '<span class="toggle-label">' + (opt.name || opt.id) + '</span>' +
        '</div>' +
        (opt.description ? '<div class="opt-desc" style="margin-top:8px;">' + opt.description + '</div>' : '');
    }
    
    container.appendChild(div);
  });
}

function toggleBoolean(optId) {
  var toggle = document.getElementById('toggle_' + optId);
  if (toggle) toggle.classList.toggle('on');
}

function closeConfigPanel() {
  document.getElementById('configOverlay').classList.remove('show');
}

function applyConfigOptions() {
  var changes = [];
  _configOptions.forEach(function(opt) {
    if (opt.type === 'select') {
      var sel = document.getElementById('sel_' + opt.id);
      if (sel && sel.value !== opt.current_value) {
        changes.push({ id: opt.id, value: sel.value });
      }
    } else if (opt.type === 'boolean') {
      var toggle = document.getElementById('toggle_' + opt.id);
      var isOn = toggle && toggle.classList.contains('on');
      if (isOn !== opt.current_value) {
        changes.push({ id: opt.id, value: isOn });
      }
    }
  });
  
  // 通过 Python 桥发送配置变更
  window._callPython('sendMessage', '__config__:' + JSON.stringify(changes));
  
  closeConfigPanel();
}

function respondPermission(sessionId, choiceId) {
  document.getElementById('permissionOverlay').classList.remove('show');
  window._callPython('sendMessage', '__permission__:' + sessionId + '|' + choiceId);
}

// ===================== 星云背景（合并光晕与网格） =====================
var nebulaCanvas = document.getElementById('nebula');
var nebCtx = nebulaCanvas.getContext('2d');

function resizeNebula() {
  nebulaCanvas.width = window.innerWidth;
  nebulaCanvas.height = window.innerHeight;
}
resizeNebula();
window.addEventListener('resize', resizeNebula);

function drawNebula() {
  var W = nebulaCanvas.width, H = nebulaCanvas.height;
  nebCtx.clearRect(0, 0, W, H);

  // 纯黑星空背景 —— 仅用极淡的深灰渐变增加一点层次感，不添加任何彩色光晕
  var grad = nebCtx.createRadialGradient(W*0.5, H*0.5, 0, W*0.5, H*0.5, Math.max(W, H)*0.75);
  grad.addColorStop(0, '#050508');
  grad.addColorStop(0.5, '#020204');
  grad.addColorStop(1, '#000000');
  nebCtx.fillStyle = grad;
  nebCtx.fillRect(0, 0, W, H);

  requestAnimationFrame(drawNebula);
}
drawNebula();

// ===================== 3D 旋转星空 =====================
// ★ 壁纸系统变量（提前声明，供 render 引用）
var _wallpaperMode = 'dynamic';   // dynamic | static | system
var _wallpaperTheme = 'starfield'; // starfield | ocean
var _oceanMode = localStorage.getItem('oceanMode') || 'day'; // day | sunset | night
var _starfieldRAF = null;         // 星空动画帧ID
var _staticWallpaperUrl = '';     // 静态壁纸URL

var canvas = document.getElementById('starfield');
var ctx = canvas.getContext('2d');
var W, H, CX, CY;

// #region debug-point B:canvas-init
// 运行时日志上报函数（用于科学调试）
function _dbgLog(hypId, msg, data) {
  var logStr = '[DEBUG][' + hypId + '] ' + msg + ' ' + JSON.stringify(data||{});
  console.log(logStr);
  try {
    var payload = {sessionId:'starfield-missing',runId:'pre-fix',hypothesisId:hypId,location:'mimo_app.js',msg:logStr,data:data||{},ts:Date.now()};
    fetch('http://127.0.0.1:7777/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),mode:'no-cors'}).catch(function(){});
  } catch(e) {}
}
_dbgLog('B','canvas-init',{canvasExists:!!canvas,ctxExists:!!ctx,innerW:window.innerWidth,innerH:window.innerHeight});
// #endregion

function resize() {
  W = canvas.width = window.innerWidth;
  H = canvas.height = window.innerHeight;
  CX = W / 2;
  CY = H / 2;
  // #region debug-point B:resize
  _dbgLog('B','resize',{W:W,H:H,CX:CX,CY:CY,canvasW:canvas.width,canvasH:canvas.height});
  // #endregion
}
resize();
window.addEventListener('resize', resize);

// 多层星星：远景、中景、近景、极近景（纯白色调，去除暖色系）
var layers = [
  { count: 320, depth: [2000, 4500], speed: 0.00025, size: [0.4, 1.1], alpha: [0.25, 0.55], color: [220, 225, 255] },
  { count: 220, depth: [900, 2200], speed: 0.0005, size: [0.7, 1.7], alpha: [0.45, 0.8], color: [240, 245, 255] },
  { count: 90, depth: [350, 1100], speed: 0.0009, size: [1.3, 3.2], alpha: [0.65, 1], color: [250, 252, 255] },
  { count: 28, depth: [120, 420], speed: 0.0016, size: [2.5, 6], alpha: [0.8, 1], color: [255, 255, 255] }
];
var stars = [];
for (var li = 0; li < layers.length; li++) {
  var L = layers[li];
  for (var i = 0; i < L.count; i++) {
    stars.push({
      x: (Math.random() - 0.5) * 6000,
      y: (Math.random() - 0.5) * 6000,
      z: L.depth[0] + Math.random() * (L.depth[1] - L.depth[0]),
      size: L.size[0] + Math.random() * (L.size[1] - L.size[0]),
      baseAlpha: L.alpha[0] + Math.random() * (L.alpha[1] - L.alpha[0]),
      twinkle: Math.random() * Math.PI * 2,
      twinkleSpeed: Math.random() * 0.035 + 0.005,
      speed: L.speed,
      layer: li,
      color: L.color
    });
  }
}

// ★ 星星重建钩子：DOM 重建后可调用 window._rebuildStars() 恢复星星数据
window._rebuildStars = function() {
  stars.length = 0;
  for (var li = 0; li < layers.length; li++) {
    var L = layers[li];
    for (var i = 0; i < L.count; i++) {
      stars.push({
        x: (Math.random() - 0.5) * 6000,
        y: (Math.random() - 0.5) * 6000,
        z: L.depth[0] + Math.random() * (L.depth[1] - L.depth[0]),
        size: L.size[0] + Math.random() * (L.size[1] - L.size[0]),
        baseAlpha: L.alpha[0] + Math.random() * (L.alpha[1] - L.alpha[0]),
        twinkle: Math.random() * Math.PI * 2,
        twinkleSpeed: Math.random() * 0.035 + 0.005,
        speed: L.speed,
        layer: li,
        color: L.color
      });
    }
  }
};

// 流星池
var meteors = [];
var lastMeteor = 0;
function spawnMeteor(now) {
  if (!W || !H || W <= 0 || H <= 0) {
    console.warn('[Starfield] spawnMeteor 被拦截：W=' + W + ' H=' + H);
    return;
  }
  // 45% 近距离大流星
  var near = Math.random() < 0.45;
  var side = Math.random();
  var x, y, vx, vy;
  if (side < 0.4) {
    x = Math.random() * W * 0.75 + W * 0.15;
    y = -100;
    vx = -(Math.random() * 4 + 4);
    vy = Math.random() * 3 + 4;
  } else if (side < 0.7) {
    x = W + 100;
    y = Math.random() * H * 0.4;
    vx = -(Math.random() * 6 + 7);
    vy = Math.random() * 4 + 4;
  } else {
    x = W + 80;
    y = -80;
    vx = -(Math.random() * 5 + 6);
    vy = Math.random() * 3 + 5;
  }
  var m = {
    x: x, y: y, vx: vx, vy: vy,
    len: near ? Math.random() * 320 + 260 : Math.random() * 200 + 150,    // ★ v4.8.1 加强拖尾
    width: near ? Math.random() * 3.8 + 2.8 : Math.random() * 2.4 + 1.5, // ★ 略加粗
    alpha: 1,
    life: 1,
    decay: near ? Math.random() * 0.0055 + 0.0035 : Math.random() * 0.009 + 0.0045, // 稍慢衰减
    near: near
  };
  if (near) {
    m.vx *= 1.7;
    m.vy *= 1.7;
  }
  meteors.push(m);
  lastMeteor = now;
}

var angleX = 0, angleY = 0;

function rotate3D(x, y, z, ax, ay) {
  var cosY = Math.cos(ay), sinY = Math.sin(ay);
  var x1 = x * cosY - z * sinY;
  var z1 = z * cosY + x * sinY;
  var cosX = Math.cos(ax), sinX = Math.sin(ax);
  var y1 = y * cosX - z1 * sinX;
  var z2 = z1 * cosX + y * sinX;
  return { x: x1, y: y1, z: z2 };
}

function drawStarShape(px, py, r, alpha, color) {
  ctx.fillStyle = 'rgba(' + color[0] + ', ' + color[1] + ', ' + color[2] + ', ' + alpha + ')';
  ctx.beginPath();
  ctx.arc(px, py, r * 0.55, 0, Math.PI * 2);
  ctx.fill();
  var arm = Math.min(r * 5, 14);
  ctx.fillRect(px - r * 0.12, py - arm, r * 0.24, arm * 2);
  ctx.fillRect(px - arm, py - r * 0.12, arm * 2, r * 0.24);
}

function render(now) {
  try {
    if (!window._renderLogged) {
      window._renderLogged = true;
      _dbgLog('A','render-first-frame',{now:now,W:W,H:H,CX:CX,CY:CY,starsCount:stars.length,meteorsCount:meteors.length,canvasW:canvas.width,canvasH:canvas.height,ctxExists:!!ctx});
      spawnMeteor(now);
      lastMeteor = now - 500;
    }
    ctx.clearRect(0, 0, W, H);

  angleY += 0.00045;
  angleX += 0.00018;

  var visibleStars = [];
  for (var i = 0; i < stars.length; i++) {
    var s = stars[i];
    var localAngleY = angleY * (1 + s.layer * 0.7);
    var localAngleX = angleX * (1 + s.layer * 0.45);
    var r = rotate3D(s.x, s.y, s.z, localAngleX, localAngleY);
    if (r.z <= 0) continue;
    var scale = 1000 / r.z;
    var px = CX + r.x * scale;
    var py = CY + r.y * scale;
    if (px < -80 || px > W + 80 || py < -80 || py > H + 80) continue;

    s.twinkle += s.twinkleSpeed;
    var tw = 0.5 + 0.5 * Math.sin(s.twinkle);
    var depthFade = Math.min(1, 1600 / r.z);
    var a = Math.min(1, s.baseAlpha * tw * depthFade * 1.4);
    var sr = s.size * scale * 0.9;
    visibleStars.push({ px: px, py: py, r: Math.min(sr, 7), alpha: a, z: r.z, color: s.color, layer: s.layer });
  }

  visibleStars.sort(function(a, b) { return b.z - a.z; });
  for (var i = 0; i < visibleStars.length; i++) {
    var s = visibleStars[i];
    drawStarShape(s.px, s.py, s.r, s.alpha, s.color);
  }

  // 流星生成
  if (now - lastMeteor > 900 + Math.random() * 1400) {
    spawnMeteor(now);
  }

  // 流星
  for (var i = meteors.length - 1; i >= 0; i--) {
    var m = meteors[i];
    m.x += m.vx;
    m.y += m.vy;
    m.life -= m.decay;

    if (m.life <= 0 || m.x < -500 || m.y > H + 300) {
      meteors.splice(i, 1);
      continue;
    }

    var speed = Math.sqrt(m.vx*m.vx + m.vy*m.vy);
    var tailX = m.x - m.vx * (m.len / speed * 0.35);
    var tailY = m.y - m.vy * (m.len / speed * 0.35);

    var grad = ctx.createLinearGradient(m.x, m.y, tailX, tailY);
    grad.addColorStop(0, 'rgba(255, 255, 255, ' + m.life + ')');
    grad.addColorStop(0.2, 'rgba(200, 220, 255, ' + (m.life * 0.85) + ')');
    grad.addColorStop(0.5, 'rgba(150, 180, 230, ' + (m.life * 0.4) + ')');
    grad.addColorStop(1, 'rgba(100, 140, 200, 0)');

    ctx.strokeStyle = grad;
    ctx.lineWidth = m.width;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(m.x, m.y);
    ctx.lineTo(tailX, tailY);
    ctx.stroke();

    // 头部光晕 —— 冷白色
    var glowR = m.near ? m.width * 10 : m.width * 7;
    var glow = ctx.createRadialGradient(m.x, m.y, 0, m.x, m.y, glowR);
    glow.addColorStop(0, 'rgba(255, 255, 255, ' + (m.life * 0.9) + ')');
    glow.addColorStop(0.4, 'rgba(180, 200, 240, ' + (m.life * 0.4) + ')');
    glow.addColorStop(1, 'rgba(100, 140, 200, 0)');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(m.x, m.y, glowR, 0, Math.PI * 2);
    ctx.fill();

    // 近距离流星加屏幕闪光（冷白色）
    if (m.near && m.life > 0.55) {
      var flash = ctx.createRadialGradient(m.x, m.y, 0, m.x, m.y, glowR * 3);
      flash.addColorStop(0, 'rgba(220, 235, 255, ' + (m.life * 0.1) + ')');
      flash.addColorStop(1, 'rgba(100, 140, 200, 0)');
      ctx.fillStyle = flash;
      ctx.beginPath();
      ctx.arc(m.x, m.y, glowR * 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  } catch(e) {
    _dbgLog('A','render-error',{error:String(e),stack:e.stack,W:W,H:H,CX:CX,CY:CY,starsCount:stars.length});
    console.error('[Starfield] render 内部错误:', e);
  }

  _starfieldRAF = requestAnimationFrame(render);
}
function initStarfield() {
  try {
    var sfCanvas = document.getElementById('starfield');
    if (!sfCanvas) return;
    var w = window.innerWidth || document.documentElement.clientWidth;
    var h = window.innerHeight || document.documentElement.clientHeight;
    if (w > 0 && h > 0) {
      W = sfCanvas.width = w;
      H = sfCanvas.height = h;
      CX = W / 2;
      CY = H / 2;
    }
    sfCanvas.style.opacity = '1';
    var nebulaCanvas = document.getElementById('nebula');
    if (nebulaCanvas) nebulaCanvas.style.opacity = '1';
    if (_starfieldRAF) {
      cancelAnimationFrame(_starfieldRAF);
      _starfieldRAF = null;
    }
    _starfieldRAF = requestAnimationFrame(render);
  } catch(e) {
    console.error('[Starfield] initStarfield 失败:', e);
  }
}
_starfieldRAF = requestAnimationFrame(render);

// ===================== ★ 壁纸系统：星空 / 海浪 / 静态 =====================
// 壁纸切换函数
function selectWallpaper(theme) {
  _wallpaperTheme = theme;

  // 更新UI选中状态
  var cards = document.querySelectorAll('[data-wallpaper]');
  cards.forEach(function(c) { c.classList.remove('active'); });
  var selected = document.querySelector('[data-wallpaper="' + theme + '"]');
  if (selected) selected.classList.add('active');

  applyWallpaper();
}

function changeWallpaperType(type) {
  _wallpaperMode = type;
  var themeRow = document.getElementById('wallpaperThemeRow');
  var staticRow = document.getElementById('wallpaperStaticRow');

  if (type === 'dynamic') {
    if (themeRow) themeRow.style.display = 'flex';
    if (staticRow) staticRow.style.display = 'none';
  } else if (type === 'static') {
    if (themeRow) themeRow.style.display = 'none';
    if (staticRow) staticRow.style.display = 'flex';
  } else {
    // system
    if (themeRow) themeRow.style.display = 'none';
    if (staticRow) staticRow.style.display = 'none';
  }

  applyWallpaper();
}

function applyWallpaper() {
  // 壁纸始终加载（右侧面板也显示动态背景），不再因 embed 跳过
  // 停止星空动画
  if (_starfieldRAF) { cancelAnimationFrame(_starfieldRAF); _starfieldRAF = null; }

  var sfCanvas = document.getElementById('starfield');
  var nebulaCanvas = document.getElementById('nebula');
  if (!sfCanvas) return;
  var sfCtx = sfCanvas.getContext('2d');

  if (_wallpaperMode === 'system') {
    // 系统默认：深色背景，无动画
    sfCtx.clearRect(0, 0, sfCanvas.width, sfCanvas.height);
    sfCanvas.style.opacity = '0';
    if (nebulaCanvas) nebulaCanvas.style.opacity = '0';
  } else if (_wallpaperMode === 'static') {
    // 静态壁纸
    sfCanvas.style.opacity = '1';
    if (nebulaCanvas) nebulaCanvas.style.opacity = '0';
    if (_staticWallpaperUrl) {
      // 用静态图片绘制
      sfCtx.clearRect(0, 0, sfCanvas.width, sfCanvas.height);
      var img = new Image();
      img.onload = function() {
        sfCtx.drawImage(img, 0, 0, sfCanvas.width, sfCanvas.height);
      };
      img.src = _staticWallpaperUrl;
    } else {
      sfCtx.clearRect(0, 0, sfCanvas.width, sfCanvas.height);
      // 默认静态渐变
      var g = sfCtx.createLinearGradient(0, 0, 0, sfCanvas.height);
      g.addColorStop(0, '#0a0a1a');
      g.addColorStop(1, '#1a1a2e');
      sfCtx.fillStyle = g;
      sfCtx.fillRect(0, 0, sfCanvas.width, sfCanvas.height);
    }
  } else {
    // 动态壁纸
    var oceanFrame = document.getElementById('oceanfield');
    if (_wallpaperTheme === 'focus_moment') {
      // ★ v12.10 REBUILD: 重新引入 Three.js typewriter iframe
      // 已确认：iframe 在 #wallpaper-layer 内，position:absolute, z-index:0, pointer-events:none
      // #content 有 isolation:isolate + z-index:100，不会被 iframe 覆盖
      if (typeof _starfieldRAF !== 'undefined' && _starfieldRAF) {
        cancelAnimationFrame(_starfieldRAF); _starfieldRAF = null;
      }
      sfCanvas.style.opacity = '0';
      if (nebulaCanvas) nebulaCanvas.style.opacity = '0';
      if (oceanFrame) {
        oceanFrame.style.opacity = '0';
        setTimeout(function() { oceanFrame.style.display = 'none'; oceanFrame.src = 'about:blank'; }, 600);
      }
      var twFrame = document.getElementById('typewriterfield');
      if (twFrame) {
        twFrame.style.display = 'block';
        twFrame.style.opacity = '0';
        twFrame.style.transition = 'opacity 0.8s ease';
        var twLoaded = false;
        twFrame.onload = function() {
          twLoaded = true;
          twFrame.style.opacity = '1';
        };
        // ★ v12.10 REBUILD: 超时 fallback — 3秒内未加载则恢复星空
        setTimeout(function() {
          if (!twLoaded) {
            console.warn('[Wallpaper] typewriter iframe 加载超时，回退到星空壁纸');
            sfCanvas.style.opacity = '1';
            if (nebulaCanvas) nebulaCanvas.style.opacity = '1';
            if (typeof render === 'function' && !_starfieldRAF) {
              _starfieldRAF = requestAnimationFrame(render);
            }
            twFrame.style.opacity = '0';
            setTimeout(function() { twFrame.style.display = 'none'; twFrame.src = 'about:blank'; }, 300);
          }
        }, 3000);
        twFrame.onerror = function() {
          if (!twLoaded) {
            console.warn('[Wallpaper] typewriter iframe 加载出错，回退到星空壁纸');
            sfCanvas.style.opacity = '1';
            if (nebulaCanvas) nebulaCanvas.style.opacity = '1';
            if (typeof render === 'function' && !_starfieldRAF) {
              _starfieldRAF = requestAnimationFrame(render);
            }
          }
        };
        twFrame.src = 'typewriter_wallpaper.html?v=' + Date.now();
      }
    } else if (_wallpaperTheme === 'ocean') {
      // 停止星空，加载并显示 Three.js 海洋 iframe
      if (typeof _starfieldRAF !== 'undefined' && _starfieldRAF) {
        cancelAnimationFrame(_starfieldRAF); _starfieldRAF = null;
      }
      sfCanvas.style.opacity = '0';
      if (nebulaCanvas) nebulaCanvas.style.opacity = '0';
      if (oceanFrame) {
        // ★ v4.1.31: 彻底移除 typewriterfield 相关处理
        var newSrc = 'ocean.html?mode=' + _oceanMode + '&v=' + Date.now();
        oceanFrame.style.display = 'block';
        oceanFrame.style.opacity = '0';
        oceanFrame.style.transition = 'none';
        _bindOceanFrameEvents(oceanFrame);
        // 直接替换 src 并加时间戳，确保重新加载
        oceanFrame.src = newSrc;
      }
    } else {
      // 停止海洋/专注时刻，显示星空
      // ★ 先确保 canvas 尺寸正确
      if (sfCanvas.width !== window.innerWidth || sfCanvas.height !== window.innerHeight) {
        W = sfCanvas.width = window.innerWidth;
        H = sfCanvas.height = window.innerHeight;
        CX = W / 2;
        CY = H / 2;
      }
      sfCanvas.style.opacity = '1';
      if (nebulaCanvas) nebulaCanvas.style.opacity = '1';
      if (oceanFrame) {
        oceanFrame.style.opacity = '0';
        setTimeout(function() { oceanFrame.style.display = 'none'; oceanFrame.src = 'about:blank'; }, 1200);
      }
      // ★ v12.2: 专注时刻 iframe 也要隐藏
      var twFrameOff = document.getElementById('typewriterfield');
      if (twFrameOff) {
        twFrameOff.style.opacity = '0';
        setTimeout(function() { twFrameOff.style.display = 'none'; twFrameOff.src = 'about:blank'; }, 600);
      }
      // ★ v4.8.1 修复：强制启动星空动画，不再依赖 !_starfieldRAF 条件
      // 因为 applyWallpaper 开头已经取消了 RAF，这里必须无条件重启
      if (typeof render === 'function') {
        _starfieldRAF = requestAnimationFrame(render);
      }
    }
  }

  // 延迟通知机器人（showBubble在后面定义）
  setTimeout(function() {
    if (_wallpaperMode !== 'dynamic') return;
    if (_wallpaperTheme === 'ocean') {
      if (typeof showBubble === 'function') showBubble(SVG_ICONS.zap + ' 海浪壁纸~', 2000);
    } else if (_wallpaperTheme === 'focus_moment') {
      if (typeof showBubble === 'function') showBubble('⌨ 专注时刻壁纸~', 2000);
    } else if (_wallpaperTheme === 'starfield') {
      if (typeof showBubble === 'function') showBubble(SVG_ICONS.zap + ' 星空壁纸~', 2000);
    }
  }, 500);
}

// ★ 绑定海洋 iframe 加载事件与错误消息监听
function _bindOceanFrameEvents(frame) {
  if (!frame || frame._oceanEventsBound) return;
  frame._oceanEventsBound = true;

  var _fadeIn = function() {
    try {
      frame.style.transition = 'opacity 1.2s ease';
      frame.style.opacity = '1';
    } catch (e) {}
  };

  frame.addEventListener('load', _fadeIn);
  frame.addEventListener('error', function(e) {
    console.error('[Ocean Frame] iframe 加载失败', e);
  });

  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'ocean-error') {
      console.error('[Ocean Frame] 子页面错误:', e.data.message);
    }
  });

  // 兜底：若 iframe 已加载完成或超时仍未触发 load，也尝试淡入
  try {
    if (frame.contentDocument && frame.contentDocument.readyState === 'complete') {
      _fadeIn();
    }
  } catch (e) {}
  setTimeout(_fadeIn, 2500);
}

// ============================================================
// 海洋时段切换 UI
// ============================================================
function setOceanMode(mode) {
  if (['day', 'sunset', 'night'].indexOf(mode) === -1) return;
  _oceanMode = mode;
  try { localStorage.setItem('oceanMode', mode); } catch (e) {}
  updateOceanModeButtons();

  var oceanFrame = document.getElementById('oceanfield');
  if (_wallpaperTheme === 'ocean' && _wallpaperMode === 'dynamic' && oceanFrame && oceanFrame.contentWindow) {
    try {
      oceanFrame.contentWindow.postMessage({ type: 'ocean-set-mode', mode: mode }, '*');
    } catch (e) {
      // 若 postMessage 失败，回退到重新加载 iframe
      applyWallpaper();
    }
  }
}

function updateOceanModeUI(themeId) {
  var row = document.getElementById('oceanModeRow');
  if (!row) return;
  row.style.display = (themeId === 'ocean') ? 'flex' : 'none';
  if (themeId === 'ocean') updateOceanModeButtons();
}

function updateOceanModeButtons() {
  ['day', 'sunset', 'night'].forEach(function(m) {
    var btn = document.getElementById('ocean-mode-' + m);
    if (btn) btn.classList.toggle('active', m === _oceanMode);
  });
}

function pickStaticWallpaper() {
  // 创建隐藏的file input
  var input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.onchange = function(e) {
    var file = e.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function(ev) {
      _staticWallpaperUrl = ev.target.result;
      applyWallpaper();
    };
    reader.readAsDataURL(file);
  };
  input.click();
}

function clearStaticWallpaper() {
  _staticWallpaperUrl = '';
  applyWallpaper();
}

// ===================== 左下角数码机器人交互 =====================
var robot = document.getElementById('robot');
var robotBubble = document.getElementById('robotBubble');
var robotChat = document.getElementById('robotChat');
var chatMessages = document.getElementById('chatMessages');
var chatInput = document.getElementById('chatInput');
var robotEyes = document.querySelectorAll('.robot-eye');
var clickCount = 0;
var clickTimer = null;
var idleTimer = null;
var bubbleTimer = null;
var _agentState = 'idle'; // idle, working, error, thinking, connected, disconnected
var _chatHistory = [];
var _waitingForReply = false; // 是否正在等待 Ollama 回复
var _behaviorTimer = null;    // 随机行为定时器
var _lastExpr = '';           // 上一个非临时表情，用于恢复

// 所有表情类名（setExpression 会清掉这些）
var allExpressions = [
  'happy', 'angry', 'thinking', 'looking-left', 'looking-right', 'looking-up', 'looking-down',
  'surprised', 'sleepy', 'worried', 'excited', 'confused', 'alert',
  'curious', 'love', 'dizzy', 'blinking',
  'eating', 'sleeping2', 'drinking', 'writing', 'organizing', 'file-eating',
  'tea-making', 'walking', 'shrug', 'cool', 'shy', 'proud', 'wander', 'stroll'
];
// 手臂动作类名（动作结束时清理）
var allArmActions = [
  'arms-out', 'wall-climb', 'hiding', 'note-taking', 'trash-throw', 'waving', 'stretching'
];
// 闲置时随机切换的表情
var idleExpressions = ['looking-left', 'looking-right', 'looking-up', 'looking-down', 'curious', 'sleepy', 'blinking'];
var exprIndex = 0;

function setExpression(expr) {
  allExpressions.forEach(function(e) { robot.classList.remove(e); });
  if (expr) {
    robot.classList.add(expr);
    _lastExpr = expr;
  } else {
    _lastExpr = '';
  }
}

// 临时表情：执行完后恢复到上一个表情
function setTempExpression(expr, duration) {
  allExpressions.forEach(function(e) { robot.classList.remove(e); });
  if (expr) robot.classList.add(expr);
  if (duration) {
    setTimeout(function() {
      if (_waitingForReply) { setExpression('thinking'); return; }
      // 恢复一个合理的状态
      if (_agentState === 'working' || _agentState === 'thinking') setExpression('thinking');
      else if (_agentState === 'error') setExpression('alert');
      else setExpression(_lastExpr && _lastExpr !== expr ? _lastExpr : '');
    }, duration);
  }
}

// 触发一次眨眼（不破坏当前表情主线）
function blinkOnce() {
  robot.classList.add('blinking');
  setTimeout(function() { robot.classList.remove('blinking'); }, 240);
}

function showBubble(text, duration) {
  if (!robotBubble) return;
  clearTimeout(bubbleTimer);
  robotBubble.innerHTML = text;
  // 定位到机器人右上角
  var rect = robot.getBoundingClientRect();
  robotBubble.style.left = (rect.right + 6) + 'px';
  robotBubble.style.bottom = (window.innerHeight - rect.top + 6) + 'px';
  robotBubble.classList.add('show');
  bubbleTimer = setTimeout(function() {
    robotBubble.classList.remove('show');
  }, duration || 6000);
}

function handleRobotClick() {
  clickCount++;
  clearTimeout(clickTimer);
  clearTimeout(idleTimer);

  // ★ 联动 agent character 表情系统 + 通知 Python 后端
  if (clickCount === 1) {
    setExpression('happy');
    if (typeof _updateAgentEmotion === 'function') _updateAgentEmotion('happy');
    if (window._callPython) window._callPython('agentCharacterClick');
    // 偶尔挥手
    if (Math.random() < 0.4) {
      var robot = document.getElementById('robot');
      robot.classList.add('waving');
      setTimeout(function() { robot.classList.remove('waving'); }, 1800);
    }
    showBubble(randomPick(['你好呀~', '有什么需要帮忙的吗？', '我在呢~', '嘿嘿~', '柠檬向你问好！', '嗨~今天好吗？', '主人好！', '嗯？叫我吗？', '随时待命~', '有什么指示？', '我在听着呢~', '需要我做什么？', '柠檬报到！', '准备好啦~ ' + SVG_ICONS.sparkles, '今天也要加油哦！']), 3000);
  } else if (clickCount === 2) {
    setExpression('excited');
    if (typeof _updateAgentEmotion === 'function') _updateAgentEmotion('happy');
    if (window._callPython) window._callPython('agentCharacterClick');
    // 伸展
    var robot2 = document.getElementById('robot');
    robot2.classList.add('stretching');
    setTimeout(function() { robot2.classList.remove('stretching'); }, 1500);
    showBubble(randomPick(['开心！再来点~', '哈哈~', '好开心呀！', '继续继续~', '被点了好开心~', '嗯嗯！我在~', '嘻嘻嘻~', '收到收到！', '好嘞好嘞~', '嘿嘿嘿~']), 2500);
  } else if (clickCount === 3) {
    // 第三次点击：随机拟人表情
    var expr3 = randomPick(['love', 'cool', 'shy', 'proud']);
    setExpression(expr3);
    // ★ 联动 agent character：映射到后端表情
    var emotionMap3 = { love: 'happy', cool: 'focused', shy: 'shy', proud: 'happy' };
    if (typeof _updateAgentEmotion === 'function') _updateAgentEmotion(emotionMap3[expr3] || 'happy');
    if (window._callPython) window._callPython('agentCharacterClick');
    var msg3 = {
      'love': randomPick(['爱你哦~ ' + SVG_ICONS.sparkles, '心动了~', '么么哒~', '好喜欢~ ' + SVG_ICONS['sparkles'], '心都化了~']),
      'cool': randomPick(['酷不酷？' + SVG_ICONS.bot, '这就是我~', '帅不帅？', '实力在线！', '稳如老狗~']),
      'shy': randomPick(['哎呀~别点了 ' + SVG_ICONS.bot, '人家害羞了~', '讨厌啦~', '不要这样~', '脸红了...']),
      'proud': randomPick(['哼哼~', '我可是最棒的！', '嘿嘿，骄傲~', '实力证明一切！', '柠檬出品，必属精品~'])
    };
    showBubble(msg3[expr3], 2200);
  }

  clickTimer = setTimeout(function() {
    clickCount = 0;
    idleTimer = setTimeout(function() {
      // 恢复到平静状态（不清除所有表情，而是移除临时表情回到默认）
      if (_agentState === 'working' || _agentState === 'thinking') setExpression('thinking');
      else if (_agentState === 'error') setExpression('alert');
      else setExpression('');  // 默认平静（无额外表情类 = 平静）
    }, 2400);
  }, 420);

  if (clickCount >= 5) {
    clickCount = 0;
    clearTimeout(idleTimer);
    setExpression('angry');
    if (typeof _updateAgentEmotion === 'function') _updateAgentEmotion('angry');
    if (window._callPython) window._callPython('agentCharacterClick');
    // 躲起来
    var robot3 = document.getElementById('robot');
    robot3.classList.add('hiding');
    setTimeout(function() { robot3.classList.remove('hiding'); }, 3000);
    showBubble(randomPick(['别戳了！', '好痛！', '你再戳我生气了！', '哼！', '生气了！不理你了！', '呜呜呜...', '疼疼疼！', '再戳就不理你了！', '柠檬要炸了！' + SVG_ICONS['circle-x'], '住手住手！']), 3000);
    idleTimer = setTimeout(function() { setExpression(''); }, 2800);
  }
}

function handleRobotRightClick(e) {
  e.preventDefault();
  // ★ 右键不改变眼睛外观，仅打开聊天框
  if (window._callPython) window._callPython('agentCharacterRightClick');
  openRobotChat(e);
}

// ===== 右键聊天框 =====
function openRobotChat(e) {
  // 定位到机器人右上角
  var rect = robot.getBoundingClientRect();
  robotChat.style.left = (rect.right + 10) + 'px';
  robotChat.style.top = Math.max(10, rect.top - 200) + 'px';
  robotChat.classList.add('show');
  chatInput.focus();
  // 不改变表情，保持当前眼睛状态
  if (_chatHistory.length === 0) {
    addChatMsg('robot', '嗨！我是柠檬小助手，住在编辑器里的数字小帮手~ 右键随时找我聊哦');
  }
}

function closeRobotChat() {
  robotChat.classList.remove('show');
}

function addChatMsg(role, text) {
  _chatHistory.push({ role: role, text: text });
  var div = document.createElement('div');
  div.className = 'chat-msg ' + (role === 'robot' ? 'robot-msg' : 'user-msg');
  div.textContent = text;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ===== 发送聊天消息：优先走 Python 桥接调用 Ollama 千问模型 =====
function sendChatMsg() {
  var text = chatInput.value.trim();
  if (!text) return;
  if (_waitingForReply) {
    showBubble('柠檬助手还在思考上一句呢~', 2000);
    return;
  }
  addChatMsg('user', text);
  chatInput.value = '';

  // 优先通过 Console Message Bridge 调用 Ollama 千问模型
  if (typeof window._callPython === 'function') {
    _waitingForReply = true;
    setExpression('thinking');
    showBubble('让我想想...', 4000);
    try {
      console.log('[柠檬助手] 调用 Ollama: ' + text);
      window._callPython('chatWithRobot', text);
    } catch (err) {
      console.error('[柠檬助手] 调用异常: ' + err);
      _waitingForReply = false;
      setExpression('confused');
      addChatMsg('robot', '哎呀，桥接出问题了：' + err);
    }
    return;
  }

  // 兜底：本地规则回复（桥接不可用时）
  console.log('[柠檬助手] 桥接不可用，使用本地兜底');
  setTimeout(function() {
    var reply = generateRobotReply(text);
    addChatMsg('robot', reply.text);
    setExpression(reply.expression || 'happy');
    if (reply.bubble) showBubble(reply.bubble, 3000);
  }, 400 + Math.random() * 600);
}

// ===== Python 桥接回调：收到 Ollama 回复 =====
window.mimoAgent.onRobotReply = function(text) {
  _waitingForReply = false;
  addChatMsg('robot', text);
  setExpression('happy');  // 回复完变开心
  showBubble(text.length > 30 ? text.substring(0, 30) + '...' : text, 4000);
  setTimeout(function() {
    if (!_waitingForReply && _agentState === 'idle') setExpression('');
  }, 2600);
};

// ===== Python 桥接回调：Ollama 出错 =====
window.mimoAgent.onRobotError = function(errText) {
  _waitingForReply = false;
  setExpression('confused');
  addChatMsg('robot', '（柠檬助手走神了，Ollama 没回应~ 可能服务没启动哦）');
  showBubble('连接不到千问模型~', 3500);
};

// ===== 本地兜底对话引擎（Ollama 不可用时使用） =====
function generateRobotReply(userText) {
  var t = userText.toLowerCase();
  // 状态查询
  if (t.indexOf('状态') >= 0 || t.indexOf('怎么样') >= 0 || t.indexOf('情况') >= 0) {
    var stateMap = {
      'idle': { text: '目前一切正常，Lemon Code 待命中~', expression: 'happy' },
      'working': { text: 'Lemon Code 正在努力工作中，请稍等~', expression: 'thinking' },
      'thinking': { text: 'AI 正在思考中，深呼吸~', expression: 'thinking' },
      'error': { text: '检测到异常！建议检查网络连接或重启服务。', expression: 'alert' },
      'connected': { text: '已成功连接 Lemon Code，随时可以开始！', expression: 'excited' },
      'disconnected': { text: '连接已断开，正在尝试重连...', expression: 'worried' }
    };
    var info = stateMap[_agentState] || stateMap['idle'];
    return { text: info.text, expression: info.expression, bubble: info.text.substring(0, 15) + '...' };
  }
  // 问候
  if (t.indexOf('你好') >= 0 || t.indexOf('hi') >= 0 || t.indexOf('hello') >= 0) {
    return { text: randomPick(['你好呀！我是柠檬小助手，今天想写点什么代码？', '嗨~柠檬小助手为你服务，有什么我能帮忙的吗？', 'Hello！柠檬小助手已就绪，准备好编程了吗？']), expression: 'excited' };
  }
  // 帮助
  if (t.indexOf('帮助') >= 0 || t.indexOf('help') >= 0) {
    return { text: '柠檬小助手可以帮你：查看状态、给建议、聊天解闷 试试输入"状态"看看~', expression: 'happy', bubble: '试试问"状态"' };
  }
  // 教程：教用户使用 agent
  if (t.indexOf('教程') >= 0 || t.indexOf('怎么用') >= 0 || t.indexOf('使用') >= 0 || t.indexOf('功能') >= 0) {
    return {
      text: ' Lemon Code 使用教程：\n1. 在右侧输入框输入你的需求，AI会自动生成代码\n2. 支持函数图像、3D几何体、图表的自动渲染\n3. 底部终端实时显示AI输出\n4. 点击工具栏可以切换模式、查看快照、管理文件\n5. 试试问我"状态"查看当前运行情况~',
      expression: 'excited',
      bubble: '柠檬教程时间~'
    };
  }
  // 教用户画函数图
  if (t.indexOf('画图') >= 0 || t.indexOf('函数') >= 0 || t.indexOf('图像') >= 0 || t.indexOf('画') >= 0) {
    return {
      text: ' 想画函数图？直接在输入框输入"画一个sin(x)的图像"或"y = sin(x)"就行！支持sin/cos/tan、多项式、对数、指数等~ 还能画3D几何体哦，试试"画一个正方体"！',
      expression: 'happy',
      bubble: '画图so easy~'
    };
  }
  // 教用户画3D
  if (t.indexOf('3d') >= 0 || t.indexOf('三维') >= 0 || t.indexOf('几何') >= 0 || t.indexOf('立方') >= 0) {
    return {
      text: ' 3D功能：输入"正方体""圆柱体""球体"等关键词，右边栏会自动渲染白色线框3D模型！支持9种几何体：正方体、长方体、圆柱、圆锥、球、椭球、三棱锥、四棱锥、三棱柱~',
      expression: 'excited',
      bubble: '3D魔法~'
    };
  }
  // 教用户图表
  if (t.indexOf('图表') >= 0 || t.indexOf('表格') >= 0 || t.indexOf('数据') >= 0 || t.indexOf('统计') >= 0) {
    return {
      text: ' 图表功能：AI输出中包含Markdown表格时，右边栏会自动渲染为可视化图表！支持柱状图、折线图、饼图、散点图~ 试试问"画一个季度销售柱状图"！',
      expression: 'happy',
      bubble: '数据可视化~'
    };
  }
  // agent 能做什么
  if (t.indexOf('能做') >= 0 || t.indexOf('能帮') >= 0 || t.indexOf('你会') >= 0 || t.indexOf('可以') >= 0) {
    return {
      text: ' Lemon Code 能帮你：\n• 写代码、改bug、重构项目\n• 画函数图像和3D几何体\n• 生成数据可视化图表\n• 代码审查和格式化\n• 管理文件和快照\n• 聊天解闷（找我聊就行！）\n我是柠檬小助手，随时陪你~',
      expression: 'proud',
      bubble: '我超厉害的~'
    };
  }
  // 模式
  if (t.indexOf('模式') >= 0 || t.indexOf('mode') >= 0) {
    return { text: '按 Tab 键可以切换工作模式哦！有 Agent、Code、Edit 等模式可选~', expression: 'happy' };
  }
  // 快捷键
  if (t.indexOf('快捷') >= 0 || t.indexOf('快捷键') >= 0) {
    return { text: '常用快捷键：Tab=切换模式，Ctrl+P=命令面板，Ctrl+L=清屏，?=帮助', expression: 'happy' };
  }
  // 闲聊：吃饭（触发吃饭行为）
  if (t.indexOf('吃饭') >= 0 || t.indexOf('吃了') >= 0 || t.indexOf('午饭') >= 0 || t.indexOf('晚饭') >= 0) {
    setTimeout(eatingBehavior, 500);
    return { text: randomPick(['我最爱吃柠檬了！ 你呢？', '吃饭重要！但别忘了代码也要写哦~', '柠檬奶茶是我的最爱~' + SVG_ICONS.coffee, '吃饱了才有力气写代码！']), expression: 'eating' };
  }
  // 闲聊：睡觉（触发睡觉行为）
  if (t.indexOf('睡觉') >= 0 || t.indexOf('困了') >= 0 || t.indexOf('累了') >= 0) {
    setTimeout(sleepingBehavior, 500);
    return { text: randomPick(['累了就休息一下吧~身体最重要！', '我也有点困了...zzZ', '适当的休息能提高效率哦~', '要不要我陪你小睡一会儿？' + SVG_ICONS.bot]), expression: 'sleeping2' };
  }
  // 闲聊：奶茶（触发奶茶行为）
  if (t.indexOf('奶茶') >= 0 || t.indexOf('柠檬茶') >= 0 || t.indexOf('喝') >= 0) {
    setTimeout(drinkingBehavior, 500);
    return { text: randomPick(['柠檬奶茶是我的招牌！' + SVG_ICONS.coffee, '来一杯？我帮你做~', '喝口奶茶，bug全消~', '甜蜜蜜的柠檬奶茶~']), expression: 'drinking' };
  }
  // 新增：丢垃圾
  if (t.indexOf('垃圾') >= 0 || t.indexOf('扔') >= 0 || t.indexOf('丢') >= 0 || t.indexOf('清理') >= 0) {
    setTimeout(trashThrowBehavior, 500);
    return { text: randomPick(['好的，帮我丢掉垃圾~ ' + SVG_ICONS['file-x'], '清理时间到！', '分类分类~', '不用的东西扔掉~']), expression: 'happy' };
  }
  // 新增：记笔记
  if (t.indexOf('笔记') >= 0 || t.indexOf('记') >= 0 || t.indexOf('写') >= 0) {
    setTimeout(writingBehavior, 500);
    return { text: randomPick(['好记性不如烂笔头！' + SVG_ICONS['file-edit'], '记下来~', '写写笔记~', '重要的事情要记下来！']), expression: 'writing' };
  }
  // 新增：整理文件
  if (t.indexOf('整理') >= 0 || t.indexOf('文件') >= 0 || t.indexOf('收拾') >= 0) {
    setTimeout(organizingBehavior, 500);
    return { text: randomPick(['整理一下文件~ ' + SVG_ICONS.folder, '收拾收拾~', '分类分类~', '整齐多了！']), expression: 'organizing' };
  }
  // 新增：发呆
  if (t.indexOf('发呆') >= 0 || t.indexOf('无聊') >= 0 || t.indexOf('放空') >= 0) {
    setTimeout(spacingBehavior, 500);
    return { text: randomPick(['发呆中...', '脑子放空~', '无聊的时候最适合发呆', '...']), expression: 'thinking' };
  }
  // 新增：装睡
  if (t.indexOf('装睡') >= 0 || t.indexOf('偷看') >= 0 || t.indexOf('假装') >= 0) {
    setTimeout(fakeSleepBehavior, 500);
    return { text: randomPick(['z z z...（假装睡觉）', '我在看什么呢~', '...']), expression: 'sleeping2' };
  }
  // 闲聊：夸奖
  if (t.indexOf('厉害') >= 0 || t.indexOf('棒') >= 0 || t.indexOf('好看') >= 0 || t.indexOf('可爱') >= 0) {
    return { text: randomPick(['嘿嘿，谢谢夸奖~ ' + SVG_ICONS.bot, '人家不好意思了啦~', '哼哼，我可是最棒的柠檬！', '你也很厉害呀~']), expression: 'shy' };
  }
  // 闲聊：天气
  if (t.indexOf('天气') >= 0 || t.indexOf('下雨') >= 0 || t.indexOf('热') >= 0 || t.indexOf('冷') >= 0) {
    return { text: randomPick(['不管什么天气，写代码的心情最重要~', '下雨天最适合写代码了！', '热了来杯柠檬冰茶？', '记得开空调哦~']), expression: 'happy' };
  }
  // 闲聊：名字/身份/模型（★ v4.1.10 增强：身份类问题本地兜底，不依赖底层模型）
  if (t.indexOf('名字') >= 0 || t.indexOf('叫什么') >= 0 || t.indexOf('你是') >= 0
      || t.indexOf('什么模型') >= 0 || t.indexOf('什么ai') >= 0 || t.indexOf('什么AI') >= 0
      || t.indexOf('模型型号') >= 0 || t.indexOf('哪个模型') >= 0 || t.indexOf('你是什么') >= 0
      || t.indexOf('claude') >= 0 || t.indexOf('mimo') >= 0) {
    // ★ v355: 应用品牌统一为 Lemon Work —— 身份兜底同步改名
    return { text: '我是 Lemon Work，你的智能工作助手！可以陪你写代码、操作数字银行、做数据分析——底层模型（DeepSeek/Ollama 等）只是我的引擎之一。有什么可以帮你？', expression: 'excited' };
  }
  // 默认回复
  var defaults = [
    { text: '嗯嗯，这个柠檬小助手得想想~', expression: 'thinking' },
    { text: '这个问题有点意思！让右边的 Lemon Code 帮你看看？', expression: 'confused' },
    { text: '我在呢～不过这个可能得靠 Lemon Code 来解答', expression: 'happy' },
    { text: '收到！虽然柠檬小助手不太确定，但你可以问问右边的 AI 助手~', expression: 'excited' },
    { text: '专注编程中...有事叫柠檬小助手！', expression: 'thinking' },
    { text: '我虽然是柠檬小助手，但我会努力帮你的！', expression: 'excited' },
    { text: '虽然我不太懂这个，但我相信你能搞定的！加油~' + SVG_ICONS.zap, expression: 'happy' },
    { text: '柠檬觉得这个问题很有深度~让我再想想...', expression: 'thinking' },
    { text: '要不先喝口水休息一下？然后再来解决这个问题~' + SVG_ICONS.coffee, expression: 'curious' },
    { text: '虽然我只是一个小柠檬，但我会一直陪着你的！', expression: 'love' },
  ];
  return randomPick(defaults);
}

function randomPick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

// ===== ★ 首次使用引导教程 =====
var _tutorialShown = false;
var _tutorialStep = 0;
var _tutorialSteps = [
  {
    text: ' 欢迎使用 Lemon Code！我是柠檬小助手，住在左下角~',
    expression: 'excited',
    delay: 4000
  },
  {
    text: SVG_ICONS.lightbulb + ' 在右侧输入框输入你的需求，AI 会自动帮你写代码~',
    expression: 'happy',
    delay: 4500
  },
  {
    text: SVG_ICONS.palette + ' 试试输入"画一个sin(x)的图像"，右边栏会显示白色线条函数图！',
    expression: 'curious',
    delay: 5000
  },
  {
    text: SVG_ICONS.gamepad + ' 还能画3D几何体！输入"正方体""球体"等关键词试试~',
    expression: 'excited',
    delay: 4500
  },
  {
    text: SVG_ICONS.chart_bar + ' AI输出表格时会自动渲染柱状图、折线图、饼图~',
    expression: 'happy',
    delay: 4500
  },
  {
    text: SVG_ICONS.sparkles + ' 底部终端实时显示AI输出，右边栏同步渲染可视化内容~',
    expression: 'proud',
    delay: 4000
  },
  {
    text: SVG_ICONS.bot + ' 点击我可以互动，问我"教程""怎么用"可以了解更多！',
    expression: 'love',
    delay: 4000
  }
];

function startTutorial() {
  if (_tutorialShown) return;
  _tutorialShown = true;
  _tutorialStep = 0;
  _runTutorialStep();
}

function _runTutorialStep() {
  if (_tutorialStep >= _tutorialSteps.length) {
    setExpression('');
    return;
  }
  var step = _tutorialSteps[_tutorialStep];
  setExpression(step.expression);
  showBubble(step.text, step.delay - 500);
  setTimeout(function() {
    _tutorialStep++;
    _runTutorialStep();
  }, step.delay);
}

// 页面加载后 5 秒启动教程
setTimeout(function() {
  if (!_tutorialShown && _agentState === 'idle') {
    startTutorial();
  }
}, 5000);

// ===== ★ Agent 状态感知行为：机器人根据 agent 状态做出相应反应 =====
var _lastStateChange = Date.now();
var _originalSetAgentState = window.setAgentState || null;

// 增强 setAgentState：在状态变化时触发机器人感知行为
if (_originalSetAgentState) {
  window._setAgentStateEnhanced = function(state) {
    var prevState = _agentState;
    _originalSetAgentState(state);

    // 状态变化后触发感知行为
    setTimeout(function() {
      _onAgentStateChange(state, prevState);
    }, 300);
  };
  window.setAgentState = window._setAgentStateEnhanced;
}

function _onAgentStateChange(newState, prevState) {
  _lastStateChange = Date.now();

  // ★ 联动 agent character 表情系统
  var _acEmotionMap = {
    'working': 'focused',
    'thinking': 'thinking',
    'error': 'surprised',
    'idle': 'smile',
    'connected': 'happy',
    'disconnected': 'bored'
  };
  if (_acEmotionMap[newState] && typeof _updateAgentEmotion === 'function') {
    _updateAgentEmotion(_acEmotionMap[newState]);
  }

  if (newState === 'working' && prevState !== 'working') {
    // AI 开始工作：机器人关注下边栏
    setTempExpression('looking-down', 1500);
    if (Math.random() < 0.5) {
      showBubble(randomPick(['AI 开始工作啦~', '加油加油！' + SVG_ICONS.zap, '我在旁边看着呢~']), 2500);
    }
  } else if (newState === 'thinking' && prevState !== 'thinking') {
    // AI 思考中：机器人也跟着思考
    setTempExpression('thinking', 2000);
    if (Math.random() < 0.3) {
      showBubble(randomPick(['嗯嗯，让我想想...', '思考中...' + SVG_ICONS.bot, '这个问题有深度~']), 2000);
    }
  } else if (newState === 'error') {
    // 出错了：机器人警觉
    setTempExpression('alert', 2500);
    showBubble(randomPick(['哎呀，出错了！' + SVG_ICONS.bot, '别急，检查一下~', '错误不可怕，排查就好~']), 3000);
  } else if (newState === 'connected' && prevState === 'disconnected') {
    // 重连成功
    setExpression('excited');
    showBubble('重新连接成功！' + SVG_ICONS.sparkles, 2500);
    setTimeout(function() { setExpression(''); }, 2500);
  } else if (newState === 'disconnected') {
    // 断开连接
    setExpression('worried');
    showBubble('连接断了...正在重连~', 3000);
  }
}

// ===== ★ 首次互动后减少教程频率 =====
var _firstInteraction = true;
var _origHandleRobotClick = window.handleRobotClick;
if (_origHandleRobotClick) {
  window.handleRobotClick = function() {
    if (_firstInteraction) {
      _firstInteraction = false;
      // 首次点击：跳过教程
      _tutorialShown = true;
      _tutorialStep = _tutorialSteps.length;
    }
    _origHandleRobotClick();
  };
}

// ===== 眼神跟踪鼠标 =====
// 监听全局 mousemove，让整个眼睛微移跟随鼠标
(function() {
  // 这些表情下眼睛形状已改变，无需跟踪
  var noTrackExpr = ['happy', 'angry', 'sleepy', 'surprised', 'love', 'dizzy', 'thinking',
    'eating', 'sleeping2', 'drinking', 'writing', 'organizing', 'file-eating', 'tea-making',
    'walking', 'shrug', 'cool', 'shy', 'proud', 'wander', 'stroll', 'hiding', 'waving', 'stretching',
    'blinking'];
  document.addEventListener('mousemove', function(e) {
    // 等待回复时不跟踪
    if (_waitingForReply) { resetEyeTrack(); return; }
    // 当前表情不跟踪
    for (var i = 0; i < noTrackExpr.length; i++) {
      if (robot.classList.contains(noTrackExpr[i])) { resetEyeTrack(); return; }
    }
    moveEyesTo(e.clientX, e.clientY);
  });

  function moveEyesTo(mx, my) {
    var rect = robot.getBoundingClientRect();
    var cx = rect.left + rect.width / 2;
    var cy = rect.top + rect.height / 2;
    var dx = mx - cx;
    var dy = my - cy;
    var dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < 1) { resetEyeTrack(); return; }
    // 眼睛整体偏移最大 3px
    var maxOffset = 3;
    var nx = dx / dist;
    var ny = dy / dist;
    var ex = nx * Math.min(maxOffset, dist / 30);
    var ey = ny * Math.min(maxOffset, dist / 30);
    robotEyes.forEach(function(eye) {
      eye.style.transform = 'translate(' + ex.toFixed(2) + 'px, ' + ey.toFixed(2) + 'px)';
    });
  }

  function resetEyeTrack() {
    robotEyes.forEach(function(eye) {
      eye.style.transform = '';
    });
  }
})();

// ===== 随机行为系统：每 5-15 秒触发一个随机行为 =====
// 行为：看下边栏、看左边工作栏、看右边、眨眼、发呆、思考、开心
function scheduleNextBehavior() {
  var delay = 8000 + Math.random() * 15000; // 8-23 秒（降低触发频率）
  _behaviorTimer = setTimeout(function() {
    triggerRandomBehavior();
    scheduleNextBehavior();
  }, delay);
}

function triggerRandomBehavior() {
  // 仅在闲置且未聊天时触发
  if (_waitingForReply) return;
  if (clickCount !== 0) return;
  // 工作中偏向思考，闲置偏向看四周和拟人行为
  var behaviors = [
    lookDownBehavior,     // 看下边栏
    lookLeftBehavior,     // 看左边工作栏
    lookRightBehavior,    // 看右边
    blinkBehavior,        // 眨眼
    dazeBehavior,         // 发呆
    thinkBehavior,        // 思考漩涡
    happyBehavior,        // 开心 ^ ^
    wallClimbBehavior,    // 扒墙
    hideBehavior,         // 躲起来
    noteTakingBehavior,   // 记笔记
    trashThrowBehavior,   // 丢文件
    stretchBehavior,      // 伸展
    waveBehavior,         // 挥手
    timeBehavior,         // 报时
    weatherBehavior,      // 天气闲聊
    newsBehavior,         // 新闻闲聊
    // ★ 拟人化增强行为
    eatingBehavior,       // 吃饭
    sleepingBehavior,     // 睡觉
    drinkingBehavior,     // 喝奶茶
    writingBehavior,      // 写笔记
    organizingBehavior,   // 整理文件
    fileEatingBehavior,   // 吃文件
    teaMakingBehavior,    // 制作柠檬奶茶
    shrugBehavior,        // 耸肩
    coolBehavior,         // 耍酷
    shyBehavior,          // 害羞
    proudBehavior,        // 骄傲
    wanderBehavior,       // 中范围走动
    strollBehavior        // 大范围屏幕漫步
  ];
  // 工作中偏向思考和记笔记
  if (_agentState === 'working' || _agentState === 'thinking') {
    behaviors = [thinkBehavior, thinkBehavior, writingBehavior, noteTakingBehavior, lookDownBehavior, blinkBehavior, organizingBehavior];
  } else if (_agentState === 'error') {
    behaviors = [dazeBehavior, blinkBehavior, hideBehavior, lookDownBehavior, shrugBehavior, shyBehavior];
  }
  randomPick(behaviors)();
}

function lookDownBehavior() {
  setTempExpression('looking-down', 1600);
  if (Math.random() < 0.5) showBubble(randomPick(['看看状态栏~', '几点了？', '进度如何~', '底下在跑什么？', '终端有新输出吗？']), 2200);
}
function lookLeftBehavior() {
  setTempExpression('looking-left', 1600);
  if (Math.random() < 0.4) showBubble(randomPick(['左边在写啥~', '文件树看看~', '代码写了多少了？', '项目结构瞧瞧~']), 2200);
}
function lookRightBehavior() {
  setTempExpression('looking-right', 1600);
  if (Math.random() < 0.4) showBubble(randomPick(['右边有啥~', '瞅瞅~', '输出面板看看~', '右边栏有什么新东西？']), 2200);
}
function blinkBehavior() {
  if (Math.random() < 0.3) {
    // Double blink
    robot.classList.add('double-blinking');
    setTimeout(function() { robot.classList.remove('double-blinking'); }, 520);
  } else {
    blinkOnce();
  }
}
function dazeBehavior() {
  setTempExpression('', 1800);
  if (Math.random() < 0.5) showBubble(randomPick(['发呆中...', '嗯...', 'zzZ...', '放空中~', '脑子在休息~', '什么都不想~', '发呆是生产力~']), 2200);
}
function thinkBehavior() {
  setTempExpression('thinking', 2000);
  if (Math.random() < 0.4) showBubble(randomPick(['让我想想...', '嗯~思考一下~', '这个问题有意思~', '逻辑梳理中...', '嗯...有道理~', '推理中...' + SVG_ICONS.bot]), 2400);
}
function happyBehavior() {
  setTempExpression('happy', 1800);
  if (Math.random() < 0.5) showBubble(randomPick(['今天心情不错~', '嘿嘿~', '加油呀~ ' + SVG_ICONS.sparkles, '生活美好~', '开心每一天！', '笑容是最好的代码~', '元气满满！']), 2400);
}

// ===== 带手的互动动作 =====
function wallClimbBehavior() {
  // 扒墙：手伸出来扒住边缘
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('wall-climb');
  setExpression('curious');
  showBubble(randomPick(['扒墙看看...', '上面有啥？', '爬爬~']), 2200);
  setTimeout(function() {
    robot.classList.remove('wall-climb');
    setExpression('');
  }, 2000);
}

function hideBehavior() {
  // 躲起来：缩小并半透明
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('hiding');
  setExpression('sleepy');
  showBubble(randomPick(['嘘...躲一下~', '看不到我~', '藏起来！']), 2800);
  setTimeout(function() {
    robot.classList.remove('hiding');
    setExpression('');
  }, 3000);
}

function noteTakingBehavior() {
  // 记笔记：右手拿笔写字
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('note-taking');
  setExpression('thinking');
  showBubble(randomPick(['记一下笔记...', '这个很重要！' + SVG_ICONS['file-edit'], '嗯嗯，记下了~']), 2400);
  setTimeout(function() {
    robot.classList.remove('note-taking');
    setExpression('');
  }, 2500);
}

function trashThrowBehavior() {
  // 丢文件：做出投掷动作
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('trash-throw');
  setExpression('excited');
  showBubble(randomPick(['丢掉丢掉！' + SVG_ICONS['file-x'], '这个不要了~', '清理一下~']), 2000);
  setTimeout(function() {
    robot.classList.remove('trash-throw');
    setExpression('');
  }, 1800);
}

function stretchBehavior() {
  // 伸展：双手张开伸懒腰
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('stretching');
  setExpression('happy');
  showBubble(randomPick(['伸个懒腰~', '啊~好舒服', '动动身子~']), 2200);
  setTimeout(function() {
    robot.classList.remove('stretching');
    setExpression('');
  }, 1500);
}

function waveBehavior() {
  // 挥手
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('waving');
  setExpression('happy');
  showBubble(randomPick(['嗨~', '你好呀！' + SVG_ICONS['message-circle'], '哈喽~']), 2000);
  setTimeout(function() {
    robot.classList.remove('waving');
    setExpression('');
  }, 1800);
}

// ===== 实时拟人句子：时间/天气/新闻 =====
function timeBehavior() {
  var now = new Date();
  var h = now.getHours();
  var m = now.getMinutes();
  var timeStr = h + ':' + (m < 10 ? '0' + m : m);
  var greetings = [];
  if (h < 6) greetings = ['夜深了... ' + timeStr + ' 了，还不睡吗？', '凌晨 ' + timeStr + '... zzZ'];
  else if (h < 9) greetings = ['早上好！现在 ' + timeStr, '早安~ ' + timeStr + ' 了'];
  else if (h < 12) greetings = ['上午 ' + timeStr + '，工作顺利吗？', '已经 ' + timeStr + ' 了~'];
  else if (h < 14) greetings = ['中午 ' + timeStr + '，该吃饭啦！', '午安~ ' + timeStr];
  else if (h < 18) greetings = ['下午 ' + timeStr + '，加油~', timeStr + ' 了，下午茶时间~'];
  else if (h < 22) greetings = ['晚上 ' + timeStr + '，今天辛苦了~', timeStr + ' ~ 晚上好'];
  else greetings = ['夜 ' + timeStr + ' 了，注意休息呀', '快 ' + timeStr + ' 了，早点睡吧~'];
  showBubble(randomPick(greetings), 3000);
  setTempExpression('happy', 2000);
}

function weatherBehavior() {
  // 天气闲聊（根据季节和时段模拟）
  var now = new Date();
  var month = now.getMonth() + 1;
  var weatherMsgs = [];
  if (month >= 3 && month <= 5) weatherMsgs = ['春天来了，天气不错呢~ ' + SVG_ICONS.sparkles, '今天适合出去走走~', '春风十里~', '花都开了~', '春暖花开，写代码的心情也好了~'];
  else if (month >= 6 && month <= 8) weatherMsgs = ['夏天好热啊... ' + SVG_ICONS.sparkles, '记得多喝水~', '空调是我的救命恩人~', '热到融化...', '夏天就该喝冰柠檬水！'];
  else if (month >= 9 && month <= 11) weatherMsgs = ['秋高气爽~ ' + SVG_ICONS.sparkles, '天气凉了，注意保暖', '秋天适合写代码~', '金黄的叶子好美~', '秋天的午后最惬意了~'];
  else weatherMsgs = ['冬天好冷... ' + SVG_ICONS.sparkles, '手都冻僵了~', '想窝在被窝里...', '冷到打字都慢了...', '冬日暖阳最舒服了~'];
  showBubble(randomPick(weatherMsgs), 3000);
  setTempExpression('curious', 2500);
}

function newsBehavior() {
  // 新闻/技术闲聊
  var techNews = [
    '听说 AI 又进步了~ ' + SVG_ICONS.bot, '今天的代码量达标了吗？', 'Vue 4 要出了？',
    'Python 4 还远吗~', '听说有人用 AI 写了一整个项目！', '今天的 bug 修完了吗？' + SVG_ICONS['circle-x'],
    '程序员三件套：咖啡、代码、加班 ' + SVG_ICONS.coffee, '我的千问大脑今天状态不错~',
    '听说 Trae 更新了？', '代码就像诗，写好了很美~',
    '今天 GitHub 又宕机了？', '深呼吸，bug 总会修好的~',
    'Rust 又出新版了？', 'WebAssembly 越来越流行了~',
    'TypeScript 5.0 听说很厉害！', 'GPU 算力越来越强了~',
    '量子计算离我们还有多远？', '低代码平台越来越多了~',
    'AI 编程助手越来越智能了~', '今天的 StackOverflow 访问量达标了吗？'
  ];
  showBubble(randomPick(techNews), 3000);
  setTempExpression('thinking', 2500);
}

// ===== ★ 拟人化增强行为：吃饭、睡觉、写笔记、整理文件、吃文件、制作柠檬奶茶、小范围走动 =====

// 吃饭行为
function eatingBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('eating');
  showBubble(randomPick(['好吃好吃~ ' + SVG_ICONS.coffee, '嗯~味道不错！', '吃饭ing...', '柠檬味的好吃！']), 3000);
  setTimeout(function() {
    robot.classList.remove('eating');
    setExpression('happy');
    showBubble(randomPick(['吃饱了~', '嗝~', '满足~']), 1800);
    setTimeout(function() { setExpression(''); }, 1800);
  }, 3500);
}

// 睡觉行为
function sleepingBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('sleeping2');
  showBubble(randomPick(['困了...zzZ', '午休一下~ ' + SVG_ICONS.bot, '眯一会儿...', '好困啊~']), 3500);
  setTimeout(function() {
    robot.classList.remove('sleeping2');
    setExpression('happy');
    showBubble(randomPick(['精神多了！', '睡得好香~', '又是元气满满！']), 2000);
    setTimeout(function() { setExpression(''); }, 2000);
  }, 5000);
}

// 喝奶茶行为
function drinkingBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('drinking');
  showBubble(randomPick(['来杯柠檬奶茶~ ' + SVG_ICONS.coffee, '好喝！', '续命奶茶~', '甜蜜蜜~']), 3000);
  setTimeout(function() {
    robot.classList.remove('drinking');
    setExpression('happy');
    setTimeout(function() { setExpression(''); }, 1500);
  }, 3000);
}

// 写笔记行为（增强版）
function writingBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('writing');
  showBubble(randomPick(['写写笔记~ ' + SVG_ICONS['file-edit'], '这个要记下来！', '好记性不如烂笔头~', '记一下重点...']), 3000);
  setTimeout(function() {
    robot.classList.remove('writing');
    setExpression('proud');
    showBubble(randomPick(['记好了！', '笔记完成~', '嗯嗯，学到了！']), 1800);
    setTimeout(function() { setExpression(''); }, 1800);
  }, 3500);
}

// 整理文件行为
function organizingBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('organizing');
  showBubble(randomPick(['整理一下文件~ ' + SVG_ICONS.folder, '这个放这里...', '分类分类~', '收拾收拾~']), 3000);
  setTimeout(function() {
    robot.classList.remove('organizing');
    setExpression('proud');
    showBubble(randomPick(['整整齐齐~', '干净多了！', '收纳完成~']), 1800);
    setTimeout(function() { setExpression(''); }, 1800);
  }, 3000);
}

// 吃文件行为
function fileEatingBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('file-eating');
  showBubble(randomPick(['这个文件好好吃~ ' + SVG_ICONS.file, '嚼嚼嚼...', '文件真好吃！', '删掉不如吃掉~']), 3000);
  setTimeout(function() {
    robot.classList.remove('file-eating');
    setExpression('happy');
    showBubble(randomPick(['嗝~文件好吃！', '消化中...', '美味~']), 1800);
    setTimeout(function() { setExpression(''); }, 1800);
  }, 3000);
}

// 制作柠檬奶茶行为
function teaMakingBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('tea-making');
  showBubble(randomPick(['来做柠檬奶茶~ ' + SVG_ICONS.coffee, '加点柠檬...', '搅拌搅拌~', '奶茶完成~']), 3500);
  // 制作过程分阶段
  setTimeout(function() {
    showBubble('加柠檬汁...', 1200);
  }, 1000);
  setTimeout(function() {
    showBubble('加奶茶底...', 1200);
  }, 2200);
  setTimeout(function() {
    robot.classList.remove('tea-making');
    robot.classList.add('drinking');
    showBubble('柠檬奶茶做好啦！尝一口~', 2500);
    setTimeout(function() {
      robot.classList.remove('drinking');
      setExpression('love');
      showBubble('好好喝！' + SVG_ICONS.sparkles, 2000);
      setTimeout(function() { setExpression(''); }, 2000);
    }, 2500);
  }, 3800);
}

// 耸肩行为
function shrugBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('shrug');
  showBubble(randomPick(['不知道呢~ ' + SVG_ICONS['message-circle'], '无能为力...', '这个嘛...', '我也不知道~']), 2200);
  setTimeout(function() {
    robot.classList.remove('shrug');
    setExpression('');
  }, 1200);
}

// 耍酷行为
function coolBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('cool');
  showBubble(randomPick(['酷~ ' + SVG_ICONS.bot, '这就是实力', '不用看了，我知道我很帅', '小菜一碟~']), 2500);
  setTimeout(function() {
    robot.classList.remove('cool');
    setExpression('');
  }, 2500);
}

// 害羞行为
function shyBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('shy');
  showBubble(randomPick(['哎呀~别这样 ' + SVG_ICONS.bot, '害羞了...', '人家不好意思嘛~', '讨厌啦~']), 2200);
  setTimeout(function() {
    robot.classList.remove('shy');
    setExpression('');
  }, 1500);
}

// 骄傲行为
function proudBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('proud');
  showBubble(randomPick(['哼哼，我很厉害的！', '小意思~', '这就是实力的证明！', '完美！']), 2500);
  setTimeout(function() {
    robot.classList.remove('proud');
    setExpression('');
  }, 2000);
}

// ===== ★ 走动行为：在周边移动然后回到原位 =====
function wanderBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;

  // 随机选择走动路径（中范围，不超过 120px）
  var directions = [
    { x: 80, y: -20 },   // 右上
    { x: -70, y: -15 },  // 左上
    { x: 100, y: 0 },    // 右
    { x: -90, y: -10 },  // 左上
    { x: 40, y: -40 },   // 上
    { x: -60, y: 0 },    // 左
    { x: 50, y: -60 },   // 上右
    { x: -40, y: -50 },  // 上左
  ];
  var dest = randomPick(directions);

  // 添加走动类
  robot.classList.add('wander', 'walking');
  setExpression('curious');
  showBubble(randomPick(['出去溜达溜达~', '走走走~', '活动活动筋骨~', '散步时间~', '出去转转~']), 2200);

  // 阶段1：走到目的地
  robot.style.setProperty('--wander-x', dest.x + 'px');
  robot.style.setProperty('--wander-y', dest.y + 'px');

  // 阶段2：到达后看看四周
  setTimeout(function() {
    robot.classList.remove('walking');
    setTempExpression('looking-around', 800);
    if (Math.random() < 0.5) {
      showBubble(randomPick(['这里看看~', '嗯嗯~', '到了到了~', '风景不错~']), 1500);
    }
  }, 1200);

  // 阶段3：回到原位
  setTimeout(function() {
    robot.classList.add('walking');
    showBubble(randomPick(['回家咯~', '回去了~', '该回去了~', '溜了溜了~']), 1800);
    robot.style.setProperty('--wander-x', '0px');
    robot.style.setProperty('--wander-y', '0px');
  }, 2800);

  // 阶段4：到家，恢复状态
  setTimeout(function() {
    robot.classList.remove('walking', 'wander');
    robot.style.removeProperty('--wander-x');
    robot.style.removeProperty('--wander-y');
    setExpression('happy');
    showBubble(randomPick(['到家啦~', '还是家里舒服~', '休息一下~', '回来了~']), 1800);
    setTimeout(function() { setExpression(''); }, 1800);
  }, 4200);
}

// ===== ★ 屏幕漫步行为：在屏幕上大范围移动然后回到原位 =====
function strollBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  if (robot.classList.contains('wander') || robot.classList.contains('stroll')) return;

  var vw = window.innerWidth;
  var vh = window.innerHeight;

  // 随机选择屏幕上的漫步目的地（可达屏幕中间区域）
  var strollTargets = [
    { x: Math.min(vw * 0.3, 300), y: -(vh * 0.15) },   // 右侧中间
    { x: Math.min(vw * 0.5, 500), y: -(vh * 0.05) },   // 远右
    { x: -20, y: -(vh * 0.3) },                          // 上方
    { x: Math.min(vw * 0.2, 200), y: -(vh * 0.25) },    // 右上
    { x: Math.min(vw * 0.4, 400), y: -(vh * 0.1) },     // 中右
    { x: 30, y: -(vh * 0.35) },                          // 正上方远处
  ];
  var dest = randomPick(strollTargets);

  // 启动漫步
  robot.classList.add('stroll', 'walking');
  setExpression('excited');
  showBubble(randomPick(['出去逛逛！', '屏幕漫步~', '溜达溜达~', '走你~ ' + SVG_ICONS['message-circle'], '兜一圈去~']), 2500);

  // 阶段1：走到目的地
  robot.style.setProperty('--wander-x', dest.x + 'px');
  robot.style.setProperty('--wander-y', dest.y + 'px');

  // 阶段2：到达后四处看看
  setTimeout(function() {
    robot.classList.remove('walking');
    setExpression('curious');
    showBubble(randomPick(['哇，这里好远~', '嗯，风景不错~', '到新地方了！', '四处看看~ ' + SVG_ICONS.eye]), 2200);

    // 左右看
    setTimeout(function() { setExpression('looking-left'); }, 600);
    setTimeout(function() { setExpression('looking-right'); }, 1200);
    setTimeout(function() { setExpression('looking-up'); }, 1800);
  }, 2200);

  // 阶段3：逛一会，可能说点什么
  setTimeout(function() {
    if (Math.random() < 0.6) {
      showBubble(randomPick(['嗯...差不多该回去了', '逛够了~', '还是老地方好~', '有点想家了~']), 2000);
    }
    setExpression('thinking');
  }, 4500);

  // 阶段4：启程回家
  setTimeout(function() {
    robot.classList.add('walking');
    setExpression('happy');
    showBubble(randomPick(['回家！', '走回去~', '回去咯~', '出发回家~ ' + SVG_ICONS['layout-template']]), 2200);
    robot.style.setProperty('--wander-x', '0px');
    robot.style.setProperty('--wander-y', '0px');
  }, 6000);

  // 阶段5：到家
  setTimeout(function() {
    robot.classList.remove('walking', 'stroll');
    robot.style.removeProperty('--wander-x');
    robot.style.removeProperty('--wander-y');
    setExpression('love');
    showBubble(randomPick(['家！到家啦~ ' + SVG_ICONS['layout-template'], '还是家里舒服~', '终于回来了~', '好安心~']), 2200);
    setTimeout(function() { setExpression(''); }, 2200);
  }, 8500);
}

// 查看四周表情（辅助）
function lookingAroundExpression() {
  setExpression('looking-left');
  setTimeout(function() { setExpression('looking-right'); }, 400);
  setTimeout(function() { setExpression('looking-up'); }, 800);
}

// ===== 新增道具互动行为 =====

// 丢垃圾行为（垃圾桶从右侧弹出）
function trashThrowBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('trash-throw');
  showBubble(randomPick(['扔掉垃圾~ ' + SVG_ICONS['file-x'], '垃圾分类中...', '不用的东西丢掉~', '清理清理~']), 2500);
  setTimeout(function() {
    robot.classList.remove('trash-throw');
    setExpression('happy');
    showBubble(randomPick(['干净了！', '清理完毕~', '舒服~']), 1500);
    setTimeout(function() { setExpression(''); }, 1500);
  }, 3000);
}

// 装睡行为（偷看用户）
function fakeSleepBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('sleeping2');
  showBubble('z z z...', 2000);

  // 偷看
  setTimeout(function() {
    robot.classList.remove('sleeping2');
    setExpression('curious');
    showBubble(randomPick(['咦，你还在吗？', '偷看~ ' + SVG_ICONS.eye, '你在干嘛？', '...假装睡觉被发现了']), 2500);
    setTimeout(function() {
      setExpression('shy');
      showBubble('嘿嘿~', 1500);
      setTimeout(function() { setExpression(''); }, 1500);
    }, 2500);
  }, 3000);
}

// 发呆行为
function spacingBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  setExpression('thinking');
  showBubble(randomPick(['发呆中...', '发呆ing~', '脑子放空...', '在想什么呢...']), 2500);

  // 眼神游移
  setTimeout(function() { setExpression('looking-left'); }, 800);
  setTimeout(function() { setExpression('looking-right'); }, 1600);
  setTimeout(function() { setExpression('looking-up'); }, 2400);
  setTimeout(function() {
    setExpression('confused');
    showBubble(randomPick(['刚才想啥了？', '忘了在想什么了...', '啊，回神了~']), 2000);
    setTimeout(function() { setExpression(''); }, 2000);
  }, 3200);
}

// 打哈欠行为
function yawnBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  setExpression('sleepy');
  showBubble(randomPick(['哈欠~ ' + SVG_ICONS['message-circle'], '好困啊...', '有点累了...', '需要休息一下~']), 2000);
  setTimeout(function() {
    setExpression('');
    robot.classList.add('blinking');
    setTimeout(function() {
      robot.classList.remove('blinking');
      showBubble(randomPick(['精神了！', '还好还好~', '继续工作~']), 1500);
    }, 300);
  }, 2000);
}

// 伸懒腰行为
function stretchBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('stretching');
  showBubble(randomPick(['伸个懒腰~ ' + SVG_ICONS['message-circle'], '舒展一下~', '活动活动筋骨~']), 2000);
  setTimeout(function() {
    robot.classList.remove('stretching');
    setExpression('happy');
    showBubble(randomPick(['舒服~', '精神多了！']), 1500);
    setTimeout(function() { setExpression(''); }, 1500);
  }, 2500);
}

// 喝水行为
function waterDrinkingBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  robot.classList.add('drinking');
  showBubble(randomPick(['喝口水~ ' + SVG_ICONS.zap, '补水补水~', '多喝水对身体好~']), 2500);
  setTimeout(function() {
    robot.classList.remove('drinking');
    setExpression('happy');
    showBubble(randomPick(['解渴了~', '精神了！']), 1500);
    setTimeout(function() { setExpression(''); }, 1500);
  }, 3000);
}

// 看时间行为
function checkTimeBehavior() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  setExpression('looking-up');
  var now = new Date();
  var hour = now.getHours();
  var min = now.getMinutes();
  var timeStr = (hour < 10 ? '0' : '') + hour + ':' + (min < 10 ? '0' : '') + min;
  showBubble(randomPick(['现在 ' + timeStr + '~', '看下时间...', '几点了？', timeStr + ' 啦~']), 2500);
  setTimeout(function() { setExpression(''); }, 2500);
}

// 随机日常互动（自动触发）
function randomDailyBehavior() {
  var behaviors = [
    { name: 'yawn', fn: yawnBehavior, weight: 3 },
    { name: 'stretch', fn: stretchBehavior, weight: 2 },
    { name: 'spacing', fn: spacingBehavior, weight: 2 },
    { name: 'fakeSleep', fn: fakeSleepBehavior, weight: 1 },
    { name: 'water', fn: waterDrinkingBehavior, weight: 2 },
    { name: 'checkTime', fn: checkTimeBehavior, weight: 2 },
    { name: 'sleeping', fn: sleepingBehavior, weight: 1 },
    { name: 'writing', fn: writingBehavior, weight: 2 },
  ];

  // 根据权重随机选择
  var totalWeight = 0;
  behaviors.forEach(function(b) { totalWeight += b.weight; });
  var rand = Math.random() * totalWeight;
  var cumulative = 0;
  for (var i = 0; i < behaviors.length; i++) {
    cumulative += behaviors[i].weight;
    if (rand < cumulative) {
      behaviors[i].fn();
      return;
    }
  }
}

// 启动随机日常互动定时器（每30-90秒触发一次）
var _dailyBehaviorTimer = null;
function startDailyBehaviorTimer() {
  if (_dailyBehaviorTimer) clearInterval(_dailyBehaviorTimer);
  function scheduleNext() {
    var delay = 30000 + Math.random() * 60000; // 30-90秒
    _dailyBehaviorTimer = setTimeout(function() {
      // 只有在空闲状态才触发
      if (!_waitingForReply && _agentState === 'idle') {
        randomDailyBehavior();
      }
      scheduleNext();
    }, delay);
  }
  scheduleNext();
}
// 页面加载后启动
setTimeout(startDailyBehaviorTimer, 10000);

// ===== 状态监视与自动建议（增强：随机鼓励） =====
window.mimoAgent.setAgentState = function(state) {
  var prevState = _agentState;
  _agentState = state;

  // 根据状态设置表情
  var exprMap = {
    'idle': '',
    'working': 'thinking',
    'thinking': 'thinking',
    'error': 'alert',
    'connected': 'excited',
    'disconnected': 'worried'
  };
  if (!_waitingForReply) setExpression(exprMap[state] || '');

  // 状态变化时给出建议
  if (prevState !== state) {
    if (state === 'working') {
      showBubble(randomPick(['Lemon Code 工作中...', '工作中...', '加油！我陪着你~ ' + SVG_ICONS.zap]), 4000);
    } else if (state === 'error') {
      showBubble('哎呀出问题了 ' + SVG_ICONS['message-circle'], 5000);
      setExpression('alert');
    } else if (state === 'connected') {
      showBubble('连接成功！' + SVG_ICONS.sparkles, 3000);
    } else if (state === 'disconnected') {
      showBubble('连接断开了...', 4000);
    } else if (state === 'idle' && prevState === 'working') {
      showBubble(randomPick([
        '任务完成！' + SVG_ICONS.sparkles, '搞定了~', 'Nice！' + SVG_ICONS.sparkles, '辛苦啦~',
        '太棒了！该休息一下了~', '完成！来杯柠檬奶茶庆祝一下？',
        '又是完美的一天！', '哼哼，我就知道你能行！' + SVG_ICONS.zap
      ]), 3000);
      setExpression('proud');
      setTimeout(function() { setExpression('happy'); }, 2000);
    }
  }
};

// ===== Agent 工作中随机鼓励 / 空闲主动搭话 =====
setInterval(function() {
  if (_waitingForReply) return;
  if (_agentState === 'working' || _agentState === 'thinking') {
    // 工作中 20% 概率说一句鼓励
    if (Math.random() < 0.2) {
      showBubble(randomPick([
        '工作中... 加油！', '稳住~', '我在旁边守着呢 ' + SVG_ICONS.zap, '快好了吧~',
        '写代码辛苦了~', '你真努力！', '需要柠檬奶茶吗？',
        '我帮你看着呢~', 'bug 不可怕，可怕的是不修~'
      ]), 3000);
    }
  } else if (_agentState === 'idle') {
    // 空闲 15% 概率主动搭话或做拟人行为
    if (Math.random() < 0.15) {
      var idleActions = [
        function() {
          setTempExpression(randomPick(['curious', 'happy', 'looking-up']), 2000);
          showBubble(randomPick([
            '在写什么呀？', '需要帮忙吗？~', '喝口水休息一下吧 ' + SVG_ICONS.coffee,
            '代码写累了叫我~', '今天天气如何呀~', '嘿，还在吗？',
            '要不要来杯柠檬奶茶？', '一起加油吧~', '你今天真棒！',
            '坐久了站起来活动活动~', '别忘了眨眨眼哦~', '今天的目标完成了多少呀？'
          ]), 3200);
        },
        // 空闲时偶尔触发拟人行为（降低概率避免频繁变色）
        function() { if (Math.random() < 0.15) eatingBehavior(); },
        function() { if (Math.random() < 0.1) drinkingBehavior(); },
        function() { if (Math.random() < 0.15) writingBehavior(); },
        function() { if (Math.random() < 0.1) wanderBehavior(); },
        function() { if (Math.random() < 0.1) organizingBehavior(); },
      ];
      randomPick(idleActions)();
    }
  }
}, 8000);

// ===== 聊天框拖拽 =====
(function() {
  var header = document.getElementById('chatHeader');
  var chat = document.getElementById('robotChat');
  var dragging = false, startX, startY, origX, origY;

  header.addEventListener('mousedown', function(e) {
    if (e.target.classList.contains('chat-close')) return;
    dragging = true;
    startX = e.clientX;
    startY = e.clientY;
    origX = parseInt(chat.style.left) || 0;
    origY = parseInt(chat.style.top) || 0;
    e.preventDefault();
  });

  document.addEventListener('mousemove', function(e) {
    if (!dragging) return;
    chat.style.left = (origX + e.clientX - startX) + 'px';
    chat.style.top = (origY + e.clientY - startY) + 'px';
  });

  document.addEventListener('mouseup', function() { dragging = false; });
})();

// ===== 启动随机行为系统（替代原闲置动画） =====
scheduleNextBehavior();

// ===================== ★ 自定义确认对话框 =====================
var _confirmCallback = null;
function _showConfirm(title, message, onConfirm, opts) {
  var opts = opts || {};
  var icon = opts.icon || '▲';
  var okText = opts.okText || '确认';
  var danger = opts.danger !== false;
  document.getElementById('confirmIcon').textContent = icon;
  document.getElementById('confirmTitle').textContent = title;
  document.getElementById('confirmMessage').textContent = message;
  var okBtn = document.getElementById('confirmOkBtn');
  okBtn.textContent = okText;
  okBtn.className = danger ? 'confirm-btn danger' : 'confirm-btn cancel';
  _confirmCallback = onConfirm || null;
  document.getElementById('confirmOverlay').classList.add('show');
}
function _confirmOk() {
  document.getElementById('confirmOverlay').classList.remove('show');
  if (typeof _confirmCallback === 'function') _confirmCallback();
  _confirmCallback = null;
}
function _confirmCancel() {
  document.getElementById('confirmOverlay').classList.remove('show');
  _confirmCallback = null;
}

// ===================== ★ 自定义输入对话框 =====================
var _inputCallback = null;
function _showInput(title, message, defaultValue, onDone, opts) {
  var opts = opts || {};
  var icon = opts.icon || SVG_ICONS['square-pen'];
  document.getElementById('inputIcon').innerHTML = icon;
  document.getElementById('inputTitle').textContent = title;
  document.getElementById('inputMessage').textContent = message || '';
  var field = document.getElementById('inputDialogField');
  field.value = defaultValue || '';
  _inputCallback = onDone || null;
  document.getElementById('inputOverlay').classList.add('show');
  setTimeout(function() { field.focus(); field.select(); }, 100);
}
function _inputOk() {
  var val = document.getElementById('inputDialogField').value;
  document.getElementById('inputOverlay').classList.remove('show');
  if (typeof _inputCallback === 'function') _inputCallback(val);
  _inputCallback = null;
}
function _inputCancel() {
  document.getElementById('inputOverlay').classList.remove('show');
  if (typeof _inputCallback === 'function') _inputCallback(null);
  _inputCallback = null;
}

// ===================== 消息处理 =====================
function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

// ★ v3.70: textarea 自动增高（内容增多时自动变高，最高 200px）
function autoGrowInput(el) {
  try {
    el.style.height = 'auto';
    var h = el.scrollHeight;
    // ★ v4.7.x: 200→140（更紧凑，避免输入区吃掉对话区视觉空间）
    if (h > 140) h = 140;
    el.style.height = h + 'px';
  } catch(e) { /* 忽略 */ }
}

// ==================== ★ v4.1.28: 输入区增强（任务条 / 展开 / 统计） ====================
var _sessionStartTs = Date.now();
var _sessionTokens = 0;

function _fmtDur(ms) {
  var s = Math.floor(ms / 1000);
  var m = Math.floor(s / 60);
  s = s % 60;
  return (m > 0) ? (m + '分' + s + '秒') : (s + '秒');
}

function _updateInputStats(tokensTotal) {
  if (typeof tokensTotal === 'number' && tokensTotal > 0) _sessionTokens = tokensTotal;
  var inline = document.getElementById('usageInline');
  if (!inline) return;
  // ★389M-1: 口径标注 —— 此处为会话累计口径（区别于完成卡/状态条的 [轮] 单次口径）
  inline.textContent = '[累计] 积分 ' + Math.round(_sessionTokens / 1000) + ' · Tokens ' + _sessionTokens + ' · ' + _fmtDur(Date.now() - _sessionStartTs);
}

function toggleAgentTaskbar(show) {
  var bar = document.getElementById('agentTaskbar');
  if (!bar) return;
  var next = (show === undefined) ? (bar.style.display === 'none') : show;
  bar.style.display = next ? 'flex' : 'none';
  if (typeof _taskbarCollapsed !== 'undefined') { _taskbarCollapsed = !next; }
  if (!next) {
    var panel = document.getElementById('agentTaskbarPanel');
    if (panel) panel.style.display = 'none';
    return;
  }
  var done = _todoList.filter(function(t) { return t.status === 'completed'; }).length;
  var run = _todoList.filter(function(t) { return t.status === 'in_progress'; }).length;
  var st = document.getElementById('taskbarStatus');
    if (st) st.innerHTML = run > 0 ? ('执行中 ' + run + ' 步…') : (done > 0 && done === _todoList.length ? '全部完成 ' + SVG_ICONS.check : '就绪');
}

function showTaskbarPanel(kind) {
  var panel = document.getElementById('agentTaskbarPanel');
  if (!panel) return;
  var tasks = document.getElementById('taskbarTabTasks');
  var files = document.getElementById('taskbarTabFiles');
  if (tasks) tasks.classList.toggle('active', kind === 'tasks');
  if (files) files.classList.toggle('active', kind === 'files');
  var src = document.getElementById(kind === 'files' ? 'todoFileList' : 'todoList');
  panel.innerHTML = '<div class="taskbar-inner">' + (src ? src.innerHTML : '') + '</div>';
  panel.style.display = 'block';
}

function toggleInputExpand() {
  var input = document.getElementById('inputField');
  if (!input) return;
  var expanded = document.body.classList.toggle('input-expanded');
  try { localStorage.setItem('lemon_input_expanded', expanded ? '1' : '0'); } catch(e) {}
  if (expanded) {
    var bar = document.getElementById('agentTaskbar');
    if (bar) { bar.style.display = 'flex'; toggleAgentTaskbar(true); }
  }
  if (input.rows !== undefined) input.rows = expanded ? 8 : 1;
  autoGrowInput(input);
}

// ★ v4.1.28: 启动时恢复输入区展开态 + 定时刷新统计
(function() {
  try {
    if (localStorage.getItem('lemon_input_expanded') === '1') {
      document.body.classList.add('input-expanded');
      var bar = document.getElementById('agentTaskbar');
      if (bar) bar.style.display = 'flex';
      var input = document.getElementById('inputField');
      if (input) input.rows = 8;
    }
  } catch(e) {}
  _updateInputStats(0);
  setInterval(function() { _updateInputStats(0); }, 30000);
})();

// ★ v3.70: 把长文本（>200 字符 或 含 ≥3 换行）压缩成可展开的引用框
function _buildCompressedQuote(text) {
  // 转义 HTML
  var esc = String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  var firstLine = esc.split('\n')[0].substring(0, 60);
  var lineCount = esc.split('\n').length;
  var charCount = esc.length;
  var summary = SVG_ICONS.file + ' ' + firstLine + (firstLine.length >= 60 ? '…' : '') +
                '  (' + lineCount + ' 行 / ' + charCount + ' 字符)';
  var uid = 'q' + Math.random().toString(36).substring(2, 9);
  var html = '<div class="msg-quote-collapsed" id="' + uid + '" onclick="toggleQuoteBox(\'' + uid + '\')">' +
             '<div class="quote-summary"><span>' + summary + '</span>' +
             '<span class="quote-toggle"></span></div>' +
             '<div class="msg-quote-full">' + esc + '</div>' +
             '</div>';
  return html;
}

// ★ v3.70: 切换引用框展开/收起
function toggleQuoteBox(id) {
  var box = document.getElementById(id);
  if (box) box.classList.toggle('expanded');
}

// ★ v3.70: 判断是否需要压缩（长内容或多行）
function _shouldCompress(text) {
  if (!text) return false;
  // 排除已经是 HTML 的内容
  if (/<[a-z][\s\S]*>/i.test(text)) return false;
  if (text.length > 200) return true;
  if (text.split('\n').length >= 4) return true;
  return false;
}

// ★ v4.1.15: 输入工具栏增强（借鉴 CodeBuddy 输入区）
function insertSlashCommand(symbol) {
  var input = document.getElementById('inputField');
  if (!input) return;
  // 聚焦并在光标处插入符号
  input.focus();
  var start = input.selectionStart || 0;
  var end = input.selectionEnd || 0;
  input.value = input.value.slice(0, start) + symbol + input.value.slice(end);
  input.selectionStart = input.selectionEnd = start + symbol.length;
  autoGrowInput(input);
}
function insertCodeBlock() {
  var input = document.getElementById('inputField');
  if (!input) return;
  var lang = 'python';
  var code = '';
  var insert = '```' + lang + '\n' + code + '\n```';
  var start = input.selectionStart || 0;
  input.value = input.value.slice(0, start) + insert + input.value.slice(start);
  input.selectionStart = input.selectionEnd = start + insert.length;
  autoGrowInput(input);
  input.focus();
}
// ★ Skills 面板开关（右侧工具面板 skills tab）
function toggleSkillsPanel() {
  var btn = document.getElementById('skillsToggleBtn');
  if (btn) {
    var active = btn.classList.toggle('active');
    btn.style.borderColor = active ? '#ff9a4a' : '';
    btn.style.color = active ? '#ff9a4a' : '';
  }
  _openRightPanel();
  _switchToolPanelTab('skills');
}

// ★ v4.1.15: 消息队列机制 — Agent 忙时新提问排队，空闲自动出队
var _pendingQueue = [];
var _agentBusy = false;

function _updateQueueBadge() {
  var el = document.getElementById('queueBadge');
  if (el) {
    el.style.display = _pendingQueue.length > 0 ? 'block' : 'none';
    el.textContent = _pendingQueue.length;
  }
  var bar = document.getElementById('queueBar');
  if (bar) {
    bar.style.display = _pendingQueue.length > 0 ? 'flex' : 'none';
  }
}

function sendMessage() {
  try {
    var input = document.getElementById('inputField');
    if (!input) return;
    var msg = input.value.trim();
    // ★ v4.7.x: 附件（粘贴/拖拽图片）即使无文本也可发送；只有空文本且无附件才忽略
    var hasAttachments = (_inputAttachments && _inputAttachments.length > 0);
    if (!msg && !hasAttachments) return;
    // 把附件 dataURL 列表一并送 Python 端（imageUpload 协议），最后清空
    if (hasAttachments) {
      for (var i = 0; i < _inputAttachments.length; i++) {
        var att = _inputAttachments[i];
        try {
          window._callPython('imageUpload', att.name, att.dataUrl);
        } catch (eAttach) {
          console.error('[sendMessage][attach]', eAttach);
        }
      }
      clearInputAttachments();
    }
    // ★ v4.7.x: 发送消息后立即隐藏空状态引导
    _hideEmptyState();
    input.value = '';
    // ★ 重置 textarea 高度
    input.style.height = 'auto';
    // ★ v4.1.15: Agent 忙时入队，而非直接发送（避免并发冲突）
    if (_agentBusy || _streamActive) {
      _pendingQueue.push(msg);
      _updateQueueBadge();
      appendMsg('status', '<span style="color:#ff9a4a;">' + SVG_ICONS.hourglass + ' Agent 正在处理，消息已入队（' + _pendingQueue.length + '）</span>');
      return;
    }
    _sendMessageDirect(msg);
  } catch(e) {
    console.error('[sendMessage]', e);
  }
}

// ===== ★ v4.7.x: 空状态引导管理 =====
function _hideEmptyState() {
  var es = document.getElementById('emptyState');
  if (es) es.classList.add('hidden');
}

function _refreshEmptyState() {
  var out = document.getElementById('outputMessages');
  var es = document.getElementById('emptyState');
  if (!es || !out) return;
  // 有真实消息（不计 status）就隐藏；否则显示
  var has_real = out.querySelector('.msg-user, .msg-ai, .msg-block');
  if (has_real) {
    es.classList.add('hidden');
  } else {
    es.classList.remove('hidden');
  }
}

// ★ v4.7.x: 空状态快捷提示按钮 → 把文本填入输入框并自动发送
function quickSend(text) {
  try {
    var input = document.getElementById('inputField');
    if (!input) return;
    input.value = text;
    autoGrowInput(input);
    input.focus();
    sendMessage();
  } catch (e) {
    console.error('[quickSend]', e);
  }
}

// ★ v4.7.x: 启动时挂 MutationObserver 监听 outputMessages，自动显示/隐藏空状态引导
(function _init_empty_state_observer() {
  try {
    var area = document.getElementById('outputMessages');
    if (!area || typeof MutationObserver === 'undefined') return;
    var mo = new MutationObserver(function() { _refreshEmptyState(); });
    mo.observe(area, { childList: true });
    _refreshEmptyState();
  } catch (e) {
    console.error('[empty-state-observer]', e);
  }
})();

// ===== ★ v4.7.x: 粘贴 / 拖拽图片支持 =====
var _inputAttachments = [];   // [{name, dataUrl, type}]，发送时清空

function _addInputAttachment(file) {
  if (!file) return;
  // ★ 仅图片走 dataURL 预览；非图片仅通知 Python（与 handleFileUpload 一致）
  if (!file.type || !file.type.startsWith('image/')) {
    var fr = new FileReader();
    fr.onload = function(ev) {
      try { window._callPython('fileUpload', file.name, ev.target.result); } catch(e){}
      appendStatusMessage('已上传文件: ' + file.name);
    };
    fr.readAsDataURL(file);
    return;
  }
  var reader = new FileReader();
  reader.onload = function(ev) {
    _inputAttachments.push({ name: file.name, dataUrl: ev.target.result, type: file.type });
    _renderInputAttachments();
    // ★ 在用户消息区追加一张图片预览（学 Claude Code 显示在气泡内）
    appendImageMessage(ev.target.result, file.name);
  };
  reader.readAsDataURL(file);
}

function _renderInputAttachments() {
  var box = document.getElementById('inputAttachments');
  var cnt = document.getElementById('inputAttachmentsCount');
  if (!box || !cnt) return;
  if (_inputAttachments.length === 0) {
    box.style.display = 'none';
    cnt.textContent = '0';
    return;
  }
  box.style.display = 'flex';
    cnt.innerHTML = SVG_ICONS.link + ' 已附加 ' + _inputAttachments.length + ' 张图片';
}

function clearInputAttachments() {
  _inputAttachments = [];
  _renderInputAttachments();
}

// ★ 粘贴事件（Ctrl+V 图片）
function handleInputPaste(event) {
  try {
    var items = (event.clipboardData && event.clipboardData.items) || [];
    var hasFile = false;
    for (var i = 0; i < items.length; i++) {
      if (items[i].kind === 'file') {
        var file = items[i].getAsFile();
        if (file) {
          _addInputAttachment(file);
          hasFile = true;
        }
      }
    }
    // 仅当确实粘了文件才阻止默认（避免拦截纯文本粘贴）
    if (hasFile) event.preventDefault();
  } catch (e) {
    console.error('[handleInputPaste]', e);
  }
}

// ★ 拖拽支持：dragover 高亮、drop 接收、leave 还原
function handleInputDragOver(event) {
  event.preventDefault();
  try { event.dataTransfer.dropEffect = 'copy'; } catch (e) {}
  var box = document.getElementById('inputBox');
  if (box) box.classList.add('drag-over');
}
function handleInputDragLeave(event) {
  var box = document.getElementById('inputBox');
  if (box) box.classList.remove('drag-over');
}
function handleInputDrop(event) {
  event.preventDefault();
  var box = document.getElementById('inputBox');
  if (box) box.classList.remove('drag-over');
  try {
    var files = (event.dataTransfer && event.dataTransfer.files) || [];
    for (var i = 0; i < files.length; i++) {
      _addInputAttachment(files[i]);
    }
  } catch (e) {
    console.error('[handleInputDrop]', e);
  }
}

function _sendMessageDirect(msg) {
  try {
    // ★ v4.8.1: 诊断日志
    console.log('[sendMessage] 入口 msg=', (msg||'').slice(0,80), 'pybridge=', typeof window.pybridge, '_callPython=', typeof window._callPython);
    // ★ 重置流式状态
    _streamActive = false;
    _streamRendered = false;
    _streamTargetContent = null;
    _streamTargetBlock = null;
    _streamCursor = null;
    
    // ★ 先显示用户消息（确保即使后端不可用，用户也能看到自己的输入）
    try {
      appendMsg('user', msg);
      console.log('[sendMessage] appendMsg(user) 成功');
    } catch(eA) {
      console.error('[sendMessage] appendMsg(user) 失败:', eA);
      // 兜底：直接 innerHTML 渲染用户气泡
      try {
        var area = document.getElementById('outputMessages');
        if (area) {
          var block = document.createElement('div');
          block.className = 'msg-block msg-user';
          var esc = String(msg).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
          block.innerHTML = '<div class="msg-bubble">' + esc + '</div>';
          area.appendChild(block);
          console.log('[sendMessage] 兜底渲染成功');
        }
      } catch(eB) { console.error('[sendMessage] 兜底也失败:', eB); }
    }
    
    // ★ v4.2.4: 咩咩进入思考状态
    if (document.getElementById('miemiePanel') && document.getElementById('miemiePanel').style.display !== 'none') {
      try { setMiemieMood('thinking'); } catch(eM) {}
    }
    
    // ★ 多级桥接机制：确保消息能送达 Python 端
    var sent = false;
    
    // 路径1: 使用 window._callPython (Console Message Bridge)
    if (typeof window._callPython === 'function') {
      try {
        window._callPython('sendMessage', msg);
        console.log('[sendMessage] 路径1成功: _callPython');
        sent = true;
      } catch(eC) {
        console.error('[sendMessage] _callPython 抛错:', eC);
      }
    }
    
    // 路径2: 直接使用 console.log 桥接（绕过 _callPython 的封装）
    if (!sent) {
      try {
        var bridgeMsg = { method: 'sendMessage', args: [msg] };
        console.log('__PYBRIDGE__:' + JSON.stringify(bridgeMsg));
        console.log('[sendMessage] 路径2成功: 直接 console.log 桥接');
        sent = true;
      } catch(eC2) {
        console.error('[sendMessage] 直接 console.log 桥接失败:', eC2);
      }
    }
    
    // 路径3: QWebChannel pybridge 兜底
    if (!sent && typeof window.pybridge !== 'undefined' && window.pybridge) {
      try {
        if (typeof window.pybridge.sendMessage === 'function') {
          window.pybridge.sendMessage(msg);
          console.log('[sendMessage] 路径3成功: pybridge.sendMessage');
          sent = true;
        }
      } catch(eD) {
        console.error('[sendMessage] pybridge.sendMessage 抛错:', eD);
      }
    }
    
    // 路径4: pybridge.call 兜底（某些 QWebChannel 实现用 call 方法）
    if (!sent && typeof window.pybridge !== 'undefined' && window.pybridge) {
      try {
        if (typeof window.pybridge.call === 'function') {
          window.pybridge.call('sendMessage', msg);
          console.log('[sendMessage] 路径4成功: pybridge.call');
          sent = true;
        }
      } catch(eD2) {
        console.error('[sendMessage] pybridge.call 抛错:', eD2);
      }
    }
    
    // 所有路径都失败 - 显示错误
    if (!sent) {
      console.error('[sendMessage] 所有桥接路径都失败，消息未送出！');
      try {
        appendMsg('status', '<span style="color:#ff6b6b;">⚠️ 后端桥接未就绪（Console Bridge / QWebChannel 均不可用）<br>请检查：1) lemon_agent 主程序是否已启动<br>2) 刷新页面或重启应用</span>');
      } catch(eE) {}
      // 显示 toast 提示
      try { showToast('⚠️ 后端连接失败，请检查主程序状态'); } catch(eE2) {}
    }
  } catch(e) {
    console.error('[sendMessage]', e);
  }
}

// ★ v4.1.15: Agent 流结束后自动出队（由 onStreamEnd 调用）
function _drainQueue() {
  if (_pendingQueue.length === 0) {
    _updateQueueBadge();
    return;
  }
  var next = _pendingQueue.shift();
  _updateQueueBadge();
  _sendMessageDirect(next);
}

// ===================== 会话/模型/模式管理（v2.1） =====================
// ★ P13: showSessionMenu/showModelMenu/showModeMenu 已移除 — UI 按钮已在 P6 精简，
//    功能统一由引擎选择器和右侧面板入口替代。Python 端信号处理器保留作为备用。

function newSession() {
  window._callPython('newSession');
}

function toggleTrustMode() {
  // ★ v4.7.x: 兼容两种 id（trustModeBtn = 历史；trustModeBtnMini = 输入区新位置）
  var btn = document.getElementById('trustModeBtnMini') || document.getElementById('trustModeBtn');
  if (!btn) return;
  var isTrust = btn.classList.toggle('trust-active');
  btn.innerHTML = isTrust ? SVG_ICONS.shield : SVG_ICONS.shield;
  btn.title = isTrust ? '信任模式已开启（自动同意）' : '信任模式已关闭（需确认）';
  // ★ 同步另一个 id（如有），保持两边一致
  var otherId = (btn.id === 'trustModeBtnMini') ? 'trustModeBtn' : 'trustModeBtnMini';
  var other = document.getElementById(otherId);
  if (other && other !== btn) {
    if (isTrust) other.classList.add('trust-active'); else other.classList.remove('trust-active');
    other.innerHTML = isTrust ? SVG_ICONS.shield : SVG_ICONS.shield;
    other.title = btn.title;
  }
  if (isTrust) {
    showToast(SVG_ICONS.shield + ' 信任模式已开启，将自动同意所有操作');
  } else {
    showToast(SVG_ICONS.shield + ' 信任模式已关闭');
  }
  window._callPython('setTrustMode', isTrust);
}

// Toast 提示
function showToast(msg) {
  var container = document.getElementById('toastContainer');
  if (!container) return;
  var toast = document.createElement('div');
  toast.className = 'toast-msg';
  toast.innerHTML = msg;
  container.appendChild(toast);
  setTimeout(function() {
    if (toast.parentNode) {
      toast.parentNode.removeChild(toast);
    }
  }, 2500);
}

function switchSession(sessionId) {
  // ★ 性能优化：切换会话前清理旧会话的 Canvas 和 DOM 引用
  if (window.PerfOpt) { PerfOpt.cleanupSessionResources(); }
  window._callPython('switchSession', sessionId);
  document.getElementById('sessionLabel').textContent = '会话: ' + sessionId;
  // ★ v4.1.15: 同步右栏标题为当前会话（CodeBuddy 式会话标题提示）
  var titleEl = document.getElementById('panelTitleText');
  if (titleEl && sessionId) {
    var sid = String(sessionId).slice(0, 12);
    titleEl.textContent = '会话 ' + sid + '...';
  }
}

function switchModel(modelName) {
  window._callPython('switchModel', modelName);
  document.getElementById('modelLabel').textContent = '模型: ' + modelName;
}

function switchMode(modeName) {
  window._callPython('switchMode', modeName);
  document.getElementById('modeLabelSm').textContent = modeName;
}

// Python 端更新会话/模型/模式显示
window.updateSessionDisplay = function(sessionId) {
  document.getElementById('sessionLabel').textContent = '会话: ' + sessionId;
};
window.updateModelDisplay = function(modelName) {
  document.getElementById('modelLabel').textContent = '模型: ' + modelName;
};
window.updateModeDisplay = function(modeName) {
  document.getElementById('modeLabelSm').textContent = modeName;
};

// ===== 思考面板控制（现在嵌入对话流中） =====
function toggleThinkingInline(header) {
  var inline = header.parentElement;
  if (!inline) return;
  inline.classList.toggle('collapsed');
}

// ★ v3.73: 工具调用折叠切换
function toggleToolCollapsible(header) {
  var section = header.parentElement;
  if (!section) return;
  section.classList.toggle('collapsed');
  var icon = header.querySelector('.tool-toggle-icon');
  if (icon) {
    icon.innerHTML = section.classList.contains('collapsed') ? SVG_ICONS['chevron-down'] : SVG_ICONS['chevron-down'];
  }
}

// ===== 消息处理（对标Trae：思考嵌入对话中，输出→主窗口） =====
var _MAX_VISIBLE_MESSAGES = 200;  // 内存优化：最多保留200条消息在DOM中
var _MSG_CLEANUP_THRESHOLD = 250; // 达到250条时触发清理

function _cleanupOldMessages() {
  var area = document.getElementById('outputMessages');
  if (!area) return;
  var count = area.children.length;
  if (count <= _MSG_CLEANUP_THRESHOLD) return;
  // 移除最旧的消息，保留最新的 _MAX_VISIBLE_MESSAGES 条
  var removeCount = count - _MAX_VISIBLE_MESSAGES;
  for (var i = 0; i < removeCount; i++) {
    var child = area.firstElementChild;
    if (child) {
      // 清理Canvas元素避免内存泄漏
      var canvases = child.querySelectorAll('canvas');
      for (var j = 0; j < canvases.length; j++) {
        canvases[j].width = 0; canvases[j].height = 0;
      }
      area.removeChild(child);
    }
  }
  console.log('[Memory] 清理 ' + removeCount + ' 条旧消息，剩余 ' + area.children.length + ' 条');
}

function _escHtmlForTimeline(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ★ v5.1: 代码卡片折叠控制（TRAE 式 diff viewer）
function toggleTimelineCode(headerEl) {
  try {
    var card = headerEl.closest('.timeline-code-card');
    if (!card) return;
    var body = card.querySelector('.timeline-code-body');
    var toggle = card.querySelector('.timeline-code-toggle');
    if (!body) return;
    var hidden = body.style.display === 'none';
    body.style.display = hidden ? 'flex' : 'none';
    if (toggle) toggle.innerHTML = hidden ? SVG_ICONS['chevron-down'] : SVG_ICONS['chevron-down'];
  } catch (e) { console.warn('[Timeline] 折叠切换失败:', e); }
}

// ★ v4.1.15: 执行轨迹流（Timeline）事件渲染 — 借鉴 CodeBuddy 时间线
// event 字段: {type: read|write|search|command|tool, tool, title, file, lines, stat, success, detail, result}
window._appendTimelineEvent = function(eventStr) {
  var area = document.getElementById('outputMessages');
  if (!area) return;
  var event;
  try { event = (typeof eventStr === 'string') ? JSON.parse(eventStr) : eventStr; }
  catch(e) { console.warn('[Timeline] 解析失败:', eventStr); return; }
  if (!event || !event.type) return;

  // ★ v4.7.23: 去 emoji — tool/worktree 换极简线条 SVG（与全站统一风格）
  var _svgTool = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>';
  var _svgWorktree = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h10"/><circle cx="20" cy="18" r="2"/></svg>';
  var iconMap  = { read:SVG_ICONS.eye, write:SVG_ICONS['square-pen'], search:SVG_ICONS.search, command:SVG_ICONS.zap, tool:_svgTool, worktree:_svgWorktree };
  var colorMap = { read:'#4a9eff', write:'#ff9800', search:'#b388ff', command:'#4caf50', tool:'#ff9a4a', worktree:'#9b59b6' };
  var labelMap = { read:'读取', write:'修改', search:'检索', command:'命令', tool:'工具', worktree:'隔离' };

  var icon  = iconMap[event.type] || '·';
  var color = colorMap[event.type] || '#a0a0a0';
  var label = labelMap[event.type] || event.type;
  var title = event.title || (event.file || event.tool || '工具调用');
  var metaParts = [];
  if (event.lines) metaParts.push(_escHtmlForTimeline(event.lines));
  if (event.stat)  metaParts.push('<b style="color:#4caf50">' + _escHtmlForTimeline(event.stat) + '</b>');
  var statusIcon  = event.success ? SVG_ICONS.check : SVG_ICONS['circle-x'];
  var statusColor = event.success ? '#4caf50' : '#f44336';

  var entry = document.createElement('div');
  entry.className = 'timeline-entry' + (event.host ? ' timeline-host' : '') + (event.worktree ? ' timeline-worktree' : '');
  entry.innerHTML =
    '<div class="timeline-row">' +
      '<span class="timeline-icon" style="color:' + color + '">' + icon + '</span>' +
      '<span class="timeline-label" style="color:' + color + '">' + label + '</span>' +
      (event.host ? '<span class="timeline-host-badge">外部</span>' : '') +
      (event.worktree ? '<span class="timeline-host-badge" style="background:#9b59b6;">隔离</span>' : '') +
      '<span class="timeline-title">' + _escHtmlForTimeline(title) + '</span>' +
      (metaParts.length ? '<span class="timeline-meta">' + metaParts.join(' · ') + '</span>' : '') +
      '<span class="timeline-status" style="color:' + statusColor + '">' + statusIcon + '</span>' +
    '</div>';

  // ★ v5.1: 写入/编辑类工具 → 渲染可折叠代码卡片（对标 TRAE 的 diff viewer）
  // 携带实际代码正文（event.code），带语法高亮 + 行号 + 折叠；diff 模式渲染红减绿加对比
  if (event.code && (event.type === 'write')) {
    try {
      var codeBlock = document.createElement('div');
      codeBlock.className = 'timeline-code-card';
      var langLabel = event.lang ? event.lang : 'text';
      var isDiff = (event.code_mode === 'diff');
      var codeLines = event.code.split('\n');
      var lineCount = codeLines.length;
      var linesHtml = '';
      var codeHtml = '';
      if (isDiff) {
        // diff 模式：逐行渲染，+ 绿 / - 红（不带行号，对比更直观）
        for (var di = 0; di < codeLines.length; di++) {
          var dl = codeLines[di];
          var cls = 'diff-line';
          if (dl.charAt(0) === '+') cls += ' diff-add';
          else if (dl.charAt(0) === '-') cls += ' diff-del';
          codeHtml += '<div class="' + cls + '">' + _escHtmlForTimeline(dl) + '</div>';
        }
        linesHtml = ''; // diff 模式不显示行号栏
      } else {
        for (var li = 0; li < codeLines.length; li++) {
          linesHtml += '<span class="code-line-no">' + (li + 1) + '</span>';
        }
        codeHtml = '<code class="language-' + _escHtmlForTimeline(langLabel) + '">' +
          _escHtmlForTimeline(event.code) + '</code>';
      }
      codeBlock.innerHTML =
        '<div class="timeline-code-header" onclick="toggleTimelineCode(this)">' +
          '<span class="timeline-code-lang">' + _escHtmlForTimeline(isDiff ? (langLabel + ' · diff') : langLabel) + '</span>' +
          '<span class="timeline-code-lines">' + lineCount + ' 行</span>' +
          (event.stat ? '<span class="timeline-code-stat">' + _escHtmlForTimeline(event.stat) + '</span>' : '') +
          '<span class="timeline-code-toggle">' + SVG_ICONS['chevron-down'] + '</span>' +
        '</div>' +
        '<div class="timeline-code-body">' +
          (isDiff ? '' : '<div class="code-gutter">' + linesHtml + '</div>') +
          '<pre class="code-content' + (isDiff ? ' code-diff' : '') + '">' + codeHtml + '</pre>' +
        '</div>';
      entry.appendChild(codeBlock);
      // 语法高亮（仅非 diff 模式）
      try {
        if (!isDiff && typeof hljs !== 'undefined') {
          var codeEl = codeBlock.querySelector('code');
          if (codeEl) hljs.highlightElement(codeEl);
        }
      } catch (e) { /* 高亮失败不影响展示 */ }
    } catch (e) {
      console.warn('[Timeline] 代码卡片渲染失败:', e);
    }
  }

  var detail = event.detail || event.result || '';
  if (detail) {
    var body = document.createElement('div');
    body.className = 'timeline-detail';
    body.style.display = 'none';
    body.textContent = detail;
    entry.appendChild(body);
    entry.querySelector('.timeline-row').onclick = function() {
      body.style.display = body.style.display === 'none' ? 'block' : 'none';
    };
  }
  area.appendChild(entry);
  if (_autoScroll) { area.scrollTop = area.scrollHeight; }
  // ★ v4.1.15: 同步统计到"文件列表"tab
  if (typeof window._trackTimelineFile === 'function') { window._trackTimelineFile(event); }
};

// ★ v5.1: P-C 任务步骤列表渲染 — 汇总本次 Agent 运行的所有工具调用，显示在右侧栏顶部
window._renderAgentSteps = function(stepsJson) {
  try {
    var data = typeof stepsJson === 'string' ? JSON.parse(stepsJson) : stepsJson;
    if (!data || !data.steps || !data.steps.length) return;
    // ★ v5.1: 运行期间实时模式 → 同步更新底部状态栏（工具计数递增）
    if (data.live && typeof window.setStatusBarLive === 'function') {
      window.setStatusBarLive(data.steps.length, data.engine, data.model, data.iterations);
    }
    var panel = document.getElementById('agentStepsPanel');
    var _panelIsNew = false;
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'agentStepsPanel';
      panel.className = 'agent-steps-panel collapsed';  // ★ 默认折叠，避免遮挡右栏内容
      _panelIsNew = true;
      // ★ v5.3 修复 F1: 插入到真正的右栏（#toolPanelContent 顶部），不再误插入到中央对话流
      var container = document.getElementById('toolPanelContent') || document.getElementById('rightPanelBody') || document.getElementById('outputMessages');
      if (container) {
        // 右栏容器直接 prepend；中央容器 prepend 到父元素顶部（兜底）
        if (container.id === 'outputMessages' && container.parentNode) {
          container.parentNode.insertBefore(panel, container);
        } else {
          container.insertBefore(panel, container.firstChild);
        }
      }
    }
    // ★ v5.3 F4: 增量渲染 — 保留 collapsed 状态，只追加新增 step，避免每帧全量重建闪烁
    var _wasCollapsed = panel.classList.contains('collapsed');

    // 头部 meta（只更新 meta 文本，不重建整个 head）
    var head = panel.querySelector('.agent-steps-head');
    if (!head) {
      head = document.createElement('div');
      head.className = 'agent-steps-head';
      head.title = '点击展开/折叠任务步骤详情';
      var okIcon = SVG_ICONS.check || '';
      head.innerHTML = okIcon +
        '<span class="agent-steps-title">任务步骤</span>' +
        '<span class="agent-steps-meta"></span>' +
        '<span class="agent-steps-toggle">▾</span>';
      head.addEventListener('click', function() {
        panel.classList.toggle('collapsed');
      });
      panel.insertBefore(head, panel.firstChild);
    }
    var metaEl = head.querySelector('.agent-steps-meta');
    if (metaEl) {
      metaEl.textContent = data.steps.length + ' 步 · ' +
        (data.engine || '?') + '/' + (data.model || '?') + ' · ' + (data.total_time || 0) + 's';
    }

    // 步骤列表（增量：只追加新增的）
    var list = panel.querySelector('.agent-steps-list');
    if (!list) {
      list = document.createElement('div');
      list.className = 'agent-steps-list';
      panel.appendChild(list);
    }
    var _renderedCount = list.childElementCount;
    for (var i = _renderedCount; i < data.steps.length; i++) {
      var s = data.steps[i];
      var item = document.createElement('div');
      var _failed = !s.success;
      item.className = 'agent-step-item' + (_failed ? ' step-failed' : '');
      var icon = _timelineIcon(s.type);
      var title = s.title || s.tool || (s.type || 'step');
      // ★ v5.3 F8: 失败 step 用 ✕ 图标 + 红色，而非统一绿色勾
      var _dotIcon = _failed ? (SVG_ICONS['circle-x'] || SVG_ICONS.close || SVG_ICONS.check || '') : (SVG_ICONS.check || '');
      item.innerHTML =
        '<span class="agent-step-dot" style="color:' + (_failed ? '#f44336' : '#4caf50') + '">' + _dotIcon + '</span>' +
        '<span class="agent-step-icon">' + icon + '</span>' +
        '<span class="agent-step-text">' + _escHtmlForTimeline(title) + '</span>' +
        (s.stat ? '<span class="agent-step-stat">' + _escHtmlForTimeline(s.stat) + '</span>' : '');
      list.appendChild(item);
    }

    // 文件清单（增量重建，避免重复 append）
    var oldFileBlock = panel.querySelector('.agent-steps-files');
    if (oldFileBlock) oldFileBlock.remove();
    var fileKeys = (typeof window._timelineFiles !== 'undefined') ? Object.keys(window._timelineFiles) : [];
    if (fileKeys.length) {
      var fileBlock = document.createElement('div');
      fileBlock.className = 'agent-steps-files';
      var typeIconMap = {
        read: (SVG_ICONS.eye || ''), write: (SVG_ICONS.pencil || ''),
        search: (SVG_ICONS.search || ''), command: (SVG_ICONS.terminal || SVG_ICONS.zap || ''),
        tool: (SVG_ICONS.tool || ''), worktree: (SVG_ICONS.tool || '')
      };
      var typeColorMap = { read:'#4a9eff', write:'#ff9800', search:'#b388ff', command:'#4caf50', tool:'#ff9a4a', worktree:'#9b59b6' };
      var fileHtml = '<div class="agent-files-head">' + (SVG_ICONS.file_default || '') +
        '<span>涉及文件 (' + fileKeys.length + ')</span></div><div class="agent-files-list">';
      fileKeys.forEach(function(f) {
        var info = window._timelineFiles[f];
        if (!info) return;
        var t = info.lastType || 'tool';
        var ic = typeIconMap[t] || '';
        var col = typeColorMap[t] || '#a0a0a0';
        fileHtml += '<div class="agent-file-item" title="' + _escHtmlForTimeline(f) + '">' +
          '<span class="agent-file-icon" style="color:' + col + '">' + ic + '</span>' +
          '<span class="agent-file-path">' + _escHtmlForTimeline(f) + '</span>' +
          '<span class="agent-file-count">' + (info.count || 1) + ' 次</span></div>';
      });
      fileHtml += '</div>';
      fileBlock.innerHTML = fileHtml;
      panel.appendChild(fileBlock);
    }

    // 恢复 collapsed 状态（F4：用户折叠后不被重建重置）
    if (_wasCollapsed) panel.classList.add('collapsed');
  } catch (e) {
    console.warn('[Steps] 渲染失败:', e);
  }
};

// ★ v5.1: P-F 独立底部状态栏条渲染（运行结束的完整 meta）
// ★ T367.4: 状态行防抖队列 + payload 完整性校验
window._statusBarQueue = null;
window._statusBarLastPayload = null;
window._statusLogBuffer = [];
window._statusLogFlushTimer = null;

function _validateStatusBarPayload(data) {
  if (!data || typeof data !== 'object') return false;
  if (data.engine === undefined && data.model === undefined) return false;
  return true;
}

function _flushStatusBarLog() {
  if (!window._statusLogBuffer.length) return;
  try {
    var csvLines = window._statusLogBuffer.join('\n');
    window._statusLogBuffer = [];
    if (window._statusLogFlushTimer) { clearTimeout(window._statusLogFlushTimer); window._statusLogFlushTimer = null; }
    // 写入通过 PyBridge 的 perf 日志（仅内存缓存，持久化由 Python 侧 perf 写入节流模式处理）
    if (window.traceLog) {
      window.traceLog(csvLines);
    }
  } catch(e) {}
}

function _logStatusEvent(payload) {
  try {
    var ts = new Date().toISOString();
    var line = ts + '|' + JSON.stringify(payload).replace(/\|/g, '_');
    window._statusLogBuffer.push(line);
    if (window._statusLogBuffer.length > 100) window._statusLogBuffer.shift();
    if (!window._statusLogFlushTimer) {
      window._statusLogFlushTimer = setTimeout(_flushStatusBarLog, 2000);
    }
  } catch(e) {}
}

window.updateStatusBar = function(data) {
  try {
    // ★ T367.4: payload 完整性校验 — 缺失关键字段则丢弃，保留上一帧
    if (!_validateStatusBarPayload(data)) {
      console.warn('[StatusBar] T367.4: payload 不完整，丢弃:', JSON.stringify(data).slice(0, 200));
      return;
    }
    // ★ T367.4: 150ms 防抖 — 多次快速更新只渲染最终值
    if (window._statusBarQueue) { clearTimeout(window._statusBarQueue); }
    window._statusBarLastPayload = data;
    // ★ T367.4: 抓包日志
    _logStatusEvent(data);
    window._statusBarQueue = setTimeout(function() {
      window._statusBarQueue = null;
      var d = window._statusBarLastPayload;
      if (!d) return;
      var bar = document.getElementById('agentStatusBar');
      if (!bar) return;
      bar.style.display = 'flex';
      var set = function(id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
      set('sbEngine', d.engine || '—');
      set('sbModel', d.model || '—');
      set('sbIter', d.iterations != null ? d.iterations : 0);
      set('sbTools', d.tools != null ? d.tools : 0);
      set('sbTime', d.total_time != null ? d.total_time : 0);
      set('sbIn', d.input_tokens != null ? d.input_tokens : 0);
      set('sbOut', d.output_tokens != null ? d.output_tokens : 0);
      var costEl = document.getElementById('sbCost');
      var costVal = document.getElementById('sbCostVal');
      if (costEl && costVal) {
        if (d.cost && d.cost > 0) { costEl.style.display = 'inline-flex'; costVal.textContent = d.cost; }
        else { costEl.style.display = 'none'; }
      }
      var dot = document.getElementById('sbEngineDot');
      var state = document.getElementById('sbState');
      if (dot) dot.className = 'statusbar-dot' + (d.success ? '' : ' error');
      if (state) {
        state.className = 'statusbar-item statusbar-state' + (d.success ? '' : ' error');
        // ★389M-1: 口径标注 —— final 帧与完成卡同源（单轮 result），标 [轮]
        state.textContent = (d.scope ? '[' + d.scope + '] ' : '') + (d.success ? '完成' : '失败');
      }
      // ★392A-2/3: 终态收口 —— 停止按钮隐藏、看门狗文案清空
      var stopBtn = document.getElementById('sbStopBtn');
      if (stopBtn) stopBtn.style.display = 'none';
      if (window.setAgentStall) window.setAgentStall('');
    }, 150);
  } catch (e) { console.warn('[StatusBar] 更新失败:', e); }
};

// ★ v5.1: 运行期间实时状态（工具计数递增 + busy 态）
// ★389M-1: 扩展 elapsed/outTok/scope —— 流式接线（py 侧 token/tool 事件驱动，
//   无轮询线程）；运行中耗时与输出 tok 单调递增，scope 标注 [轮] 口径。
// ★391A-3: 第 8 参 inTok —— 引擎 done 帧 prompt_eval_count 累计（真值），
//   修复"运行中输入恒 0"（原 live 帧无人写 sbIn）。
window.setStatusBarLive = function(toolCount, engine, model, iter, elapsed, outTok, scope, inTok) {
  try {
    var bar = document.getElementById('agentStatusBar');
    if (!bar) return;
    bar.style.display = 'flex';
    var set = function(id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
    if (engine) set('sbEngine', engine);
    if (model) set('sbModel', model);
    set('sbTools', toolCount);
    if (iter != null) set('sbIter', iter);
    if (elapsed != null) set('sbTime', elapsed);
    if (outTok != null) set('sbOut', outTok);
    if (inTok != null) set('sbIn', inTok);
    var dot = document.getElementById('sbEngineDot');
    var state = document.getElementById('sbState');
    if (dot) dot.className = 'statusbar-dot busy';
    if (state) { state.className = 'statusbar-item statusbar-state busy';
      state.textContent = (scope ? '[' + scope + '] ' : '') + '执行中'; }
    // ★392A-2: 运行中显示停止按钮（用户可随时中断在途请求）
    var stopBtn = document.getElementById('sbStopBtn');
    if (stopBtn) stopBtn.style.display = 'inline-flex';
  } catch (e) { console.warn('[StatusBar] live 更新失败:', e); }
};

// ★392A-2: 停止按钮 —— 点击后不等轮间检查，立即经 pybridge 请求中断
window.stopAgentTask = function() {
  try {
    console.log('[StopBtn] 用户点击中断');
    window.setStatusBarInterrupting();
    if (typeof window._callPython === 'function') {
      window._callPython('sendMessage', '__stop_agent__');
    } else if (typeof window.pybridge !== 'undefined' && window.pybridge && window.pybridge.sendMessage) {
      window.pybridge.sendMessage('__stop_agent__');
    } else {
      console.warn('[StopBtn] pybridge 不可用，中断请求未送达');
    }
  } catch (e) { console.warn('[StopBtn] 中断请求失败:', e); }
};

// ★392A-2: 中断中状态（点击即显，不等引擎响应）
window.setStatusBarInterrupting = function() {
  try {
    var state = document.getElementById('sbState');
    if (state) { state.className = 'statusbar-item statusbar-state busy';
      state.textContent = '正在中断当前请求…'; }
    var stall = document.getElementById('sbStall');
    if (stall) { stall.style.display = 'none'; }
  } catch (e) {}
};

// ★392A-3: 流断看门狗文案位（tier1=推理慢提示, tier2=连接挂起告警; 传空串隐藏）
window.setAgentStall = function(text) {
  try {
    var el = document.getElementById('sbStall');
    if (!el) return;
    if (text) { el.textContent = text; el.style.display = 'inline-flex'; }
    else { el.textContent = ''; el.style.display = 'none'; }
  } catch (e) {}
};


// ★ v5.1: 步骤列表里的类型图标（仅用 SVG_ICONS 中确认存在的键；缺失则回退空串避免 undefined）
function _timelineIcon(type) {
  switch (type) {
    case 'read': return (SVG_ICONS.eye || SVG_ICONS.file_default || '');
    case 'write': return (SVG_ICONS.pencil || '');
    case 'search': return (SVG_ICONS.search || '');
    case 'command': return (SVG_ICONS.terminal || SVG_ICONS.zap || '');
    case 'worktree': return (SVG_ICONS.tool || '');
    default: return (SVG_ICONS.tool || '');
  }
}

function appendMsg(type, text) {
  var area = document.getElementById('outputMessages');
  if (!area) return;

  if (type === 'thinking') {
    // ★ 思考内容 → 嵌入到最后一个AI消息块中
    var lastAiBlock = area.lastElementChild;
    if (!lastAiBlock || !lastAiBlock.classList.contains('msg-ai')) {
      // 还没有AI消息块，先创建一个
      lastAiBlock = document.createElement('div');
      lastAiBlock.className = 'msg-block msg-ai';
      area.appendChild(lastAiBlock);
    }
    
    // 查找或创建思考行内块
    var thinkInline = lastAiBlock.querySelector('.thinking-inline');
    if (!thinkInline) {
      thinkInline = document.createElement('div');
      thinkInline.className = 'thinking-inline';
      thinkInline.innerHTML = 
        '<div class="thinking-inline-header" onclick="toggleThinkingInline(this)">' +
        '<span class="think-icon">' + SVG_ICONS['chevron-down'] + '</span>' +
        '<span class="think-badge">思考</span>' +
        '<span class="think-summary"></span>' +
        '</div>' +
        '<div class="thinking-inline-body"></div>';
      lastAiBlock.insertBefore(thinkInline, lastAiBlock.firstChild);
    }
    
    var body = thinkInline.querySelector('.thinking-inline-body');
    var summary = thinkInline.querySelector('.think-summary');
    if (body) {
      body.innerHTML = text;
      body.scrollTop = body.scrollHeight;
      // ★ 节流渲染：仅在内容包含数学符号时进行数学渲染
      if (text.indexOf('$') > -1 || text.indexOf('\\(') > -1) {
        if (_thinkingMathTimer) clearTimeout(_thinkingMathTimer);
        _thinkingMathTimer = setTimeout(function() {
          renderMathInContainer(body);
        }, 300);
      }
    }
    if (summary) {
      // 摘要：取前50个字符
      var plain = text.replace(/<[^>]*>/g, '').substring(0, 50);
      summary.textContent = plain + (text.length > 50 ? '...' : '');
    }
    return;
  }

  var target = null;

  if (type === 'user') {
    // 用户消息 → 右侧气泡
    // ★ v3.70: 长内容（>200字符 或 ≥4行）压缩为可展开引用框，节省对话框空间
    var bubbleHtml;
    if (_shouldCompress(text)) {
      bubbleHtml = '<div class="msg-bubble">' + _buildCompressedQuote(text) + '</div>';
    } else {
      // 转义纯文本中的 HTML，保留换行
      var esc = String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');
      bubbleHtml = '<div class="msg-bubble">' + esc + '</div>';
    }
    var block = document.createElement('div');
    block.className = 'msg-block msg-user';
    block.dataset.msgIndex = window._globalMsgCount++;
    block.innerHTML = bubbleHtml;
    area.appendChild(block);
    target = block;
  } else if (type === 'ai') {
    // ★ 如果正在流式输出，直接更新流式块内容（避免重复创建）
    console.log('[appendMsg] ai message, _streamActive=' + _streamActive + ', _streamRendered=' + _streamRendered + ', _streamTargetContent=' + (_streamTargetContent ? 'not-null' : 'null') + ', textLen=' + (text||'').length);
    if ((_streamActive || _streamRendered) && _streamTargetContent) {
      // ★ 流式已渲染完成 — 将最终内容追加到现有块中（而不是跳过！）
      if (_streamRendered) {
        _streamRendered = false; // 重置标记
        // ★ 确保消息块有索引
        if (_streamTargetBlock && !_streamTargetBlock.dataset.msgIndex) {
          _streamTargetBlock.dataset.msgIndex = window._globalMsgCount++;
        }
        // ★ 关键修复：不要跳过！将最终分析报告追加到现有内容后面
        var appendDiv = document.createElement('div');
        appendDiv.className = 'ai-final-summary';
        appendDiv.innerHTML = '<hr style="border:none;border-top:1px solid rgba(255,255,255,0.1);margin:12px 0;">' + text;
        _streamTargetContent.appendChild(appendDiv);
        safeScrollToBottom(area);
        return;
      }
      _streamTargetContent.innerHTML = text;
      // 重新添加回退按钮
      if (_streamTargetBlock && !_streamTargetBlock.querySelector('.snapshot-rollback-btn')) {
        var rb2 = document.createElement('div');
        rb2.className = 'snapshot-rollback-btn';
        rb2.title = '回退到此次修改前';
        rb2.innerHTML = SVG_ICONS['corner-down-left'];
        rb2.onclick = function(e) {
          e.stopPropagation();
          showSnapshotRollbackModal(_streamTargetBlock);
        };
        _streamTargetBlock.insertBefore(rb2, _streamTargetContent);
      }
      return;
    }
    
    // AI回复 → 主窗口流式文本（追加到最后一个ai块，或新建）
    var lastBlock = area.lastElementChild;
    if (lastBlock && lastBlock.classList.contains('msg-ai')) {
      // 追加到现有AI块（流式更新）
      var thinkInline = lastBlock.querySelector('.thinking-inline');
      var contentWrap = lastBlock.querySelector('.ai-content');
      if (!contentWrap) {
        contentWrap = document.createElement('div');
        contentWrap.className = 'ai-content';
        lastBlock.appendChild(contentWrap);
      }
      // ★ 保存滚动位置，避免 innerHTML 替换导致跳动
      var savedScroll = area.scrollTop;
      contentWrap.innerHTML = text;
      // 恢复滚动位置（如果内容高度变化，按比例调整）
      if (savedScroll !== area.scrollTop && !_autoScroll) {
        area.scrollTop = savedScroll;
      }
      target = contentWrap;
    } else {
      // 新建AI块
      var block = document.createElement('div');
      block.className = 'msg-block msg-ai';
      block.dataset.msgIndex = window._globalMsgCount++;
      // ★ 添加回退按钮
      var rollbackBtn = document.createElement('div');
      rollbackBtn.className = 'snapshot-rollback-btn';
      rollbackBtn.title = '回退到此次修改前';
      rollbackBtn.innerHTML = SVG_ICONS['corner-down-left'];
      rollbackBtn.onclick = function(e) {
        e.stopPropagation();
        showSnapshotRollbackModal(block);
      };
      block.appendChild(rollbackBtn);
      var contentWrap = document.createElement('div');
      contentWrap.className = 'ai-content';
      contentWrap.innerHTML = text;
      block.appendChild(contentWrap);
      area.appendChild(block);
      target = contentWrap;
    }
  } else if (type === 'status' || type === 'error') {
    // 状态/错误 → 紧凑行内显示
    var block = document.createElement('div');
    block.className = 'msg-block msg-' + type;
    block.dataset.msgIndex = window._globalMsgCount++;
    block.innerHTML = text;
    area.appendChild(block);
    target = block;
  } else if (type === 'tool') {
    // ★ v3.73: Skills/工具调用 → 可折叠区域（工作时展开，完成后折叠）
    var lastAiBlock = area.lastElementChild;
    if (!lastAiBlock || !lastAiBlock.classList.contains('msg-ai')) {
      lastAiBlock = document.createElement('div');
      lastAiBlock.className = 'msg-block msg-ai';
      area.appendChild(lastAiBlock);
    }

    // 查找或创建工具调用折叠区
    var toolSection = lastAiBlock.querySelector('.tool-collapsible');
    if (!toolSection) {
      toolSection = document.createElement('div');
      toolSection.className = 'tool-collapsible';
      toolSection.innerHTML =
        '<div class="tool-collapsible-header" onclick="toggleToolCollapsible(this)">' +
        '<span class="tool-toggle-icon">' + SVG_ICONS['chevron-down'] + '</span>' +
        '<span class="tool-badge">工具调用</span>' +
        '<span class="tool-summary"></span>' +
        '</div>' +
        '<div class="tool-collapsible-body"></div>';
      lastAiBlock.appendChild(toolSection);
    }

    var toolBody = toolSection.querySelector('.tool-collapsible-body');
    var toolSummary = toolSection.querySelector('.tool-summary');
    if (toolBody) {
      // 追加内容（不替换）
      var entry = document.createElement('div');
      entry.innerHTML = text;
      toolBody.appendChild(entry);
    }
    // 更新摘要
    if (toolSummary) {
      var toolCount = toolBody ? toolBody.children.length : 0;
      toolSummary.textContent = ' (' + toolCount + ' 项)';
    }
    target = toolSection;
  }

  // ★ 渲染数学公式和图表（节流 + 强制检测，确保不遗漏）
  // ★ v3.88 增强: 无论什么类型的消息，只要是AI消息就强制扫描chart-marker和数学公式
  if (target && window.renderMathInContainer) {
    if (_mathRenderTimer) clearTimeout(_mathRenderTimer);
    var targetText = target.textContent || '';
    var hasMath = targetText.indexOf('$') > -1 || targetText.indexOf('\\(') > -1 || targetText.indexOf('\\[') > -1;
    var isAiMessage = (type === 'ai');
    // ★ v3.88: 不仅检测 target，还检测整个消息块（解决chart-marker在块级别的问题）
    var msgBlock = target.closest ? target.closest('.msg-ai') : null;
    var chartContainer = msgBlock || target;
    var hasChartMarkerDom = isAiMessage && chartContainer.querySelector && chartContainer.querySelector('.chart-marker');
    var hasGraphKeywords = isAiMessage && /(?:sin|cos|tan|log|ln|sqrt|pi|π|函数|图像|曲线|plot|graph|y\s*=)/i.test(targetText);
    var hasChartKeywords = isAiMessage && /(?:chart|pie|bar|line|scatter|柱状|折线|饼图|直方|散点)/i.test(targetText);
    var hasGeomMarker = isAiMessage && /(?:geom|正方体|圆柱|圆锥|球体|椭球|棱锥|棱柱|几何|立方|长方体)/i.test(targetText);
    // ★ v3.88: 新增 - 检测 $$ 或 LaTeX 命令
    var hasLatex = isAiMessage && /(?:\\int|\\sum|\\frac|\\sqrt|\\pi|\\infty|\\alpha|\\beta|\\gamma|\\delta|\\theta)/i.test(targetText);
    console.log('[appendMsg] renderCheck v3.88: hasMath=' + hasMath + ', hasLatex=' + hasLatex + ', hasGraph=' + hasGraphKeywords + ', hasChart=' + hasChartKeywords + ', hasGeom=' + hasGeomMarker + ', hasMarkerDom=' + !!hasChartMarkerDom + ', isAi=' + isAiMessage + ', targetClass=' + (target.className || ''));
    if (isAiMessage && (hasMath || hasLatex || hasGraphKeywords || hasChartKeywords || hasGeomMarker || hasChartMarkerDom)) {
      _mathRenderTimer = setTimeout(function() {
        // ★ v3.88: 使用 msgBlock 作为渲染容器（更完整的范围）
        var renderTarget = msgBlock || target;
        try {
          if (hasMath || hasLatex) {
            console.log('[appendMsg] 开始渲染数学公式');
            renderMathInContainer(renderTarget);
          }
        } catch(e) { console.warn('[appendMsg] renderMath 异常:', e); }
        try {
          // 智能渲染：扫描代码块并转换为可视化组件
          renderSmartComponents(renderTarget);
        } catch(e) { console.warn('[appendMsg] renderSmartComponents 异常:', e); }
        try {
          // ★ 自动检测：扫描文本中的函数表达式，渲染为简笔白线图（仅AI回复）
          if (hasGraphKeywords || hasChartKeywords || hasGeomMarker || hasChartMarkerDom) {
            console.log('[appendMsg] 开始渲染图表/函数图像');
            // ★ v3.88: 优先使用 scanAndRenderCharts（更全面）
            if (typeof scanAndRenderCharts === 'function') {
              scanAndRenderCharts(renderTarget);
            } else {
              renderAutoDetectedGraphs(renderTarget);
            }
          }
        } catch(e) { console.warn('[appendMsg] renderAutoDetectedGraphs 异常:', e); }
        try {
          // 初始化代码块工具栏（运行按钮）
          if (typeof PerfOpt !== 'undefined' && PerfOpt.initCodeToolbars) {
            PerfOpt.initCodeToolbars();
          }
        } catch(e) {}
      }, 200);
    } else {
      // 即使没有数学/图表，也要初始化代码块工具栏
      setTimeout(function() {
        if (typeof PerfOpt !== 'undefined' && PerfOpt.initCodeToolbars) {
          PerfOpt.initCodeToolbars();
        }
      }, 300);
    }
  }

  // ★ Trae风格：AI回复时自动提取任务生成工作表
  if (type === 'ai' && typeof autoGenerateTodos === 'function') {
    var aiText = target ? (target.textContent || '') : '';
    if (aiText.length > 10) {
      setTimeout(function() { autoGenerateTodos(aiText); }, 500);
      // ★ Trae风格：内嵌任务进度追踪
      setTimeout(function() { autoRenderTaskProgress(target); }, 600);
    }
  }

  // 自动滚动到底部
  if (_autoScroll) {
    area.scrollTop = area.scrollHeight;
  }
  // 更新输出badge
  var badge = document.getElementById('outputBadge');
  if (badge) {
    var count = area.children.length;
    badge.textContent = count > 0 ? count + ' 条消息' : '';
  }
  saveHistory();
  updateScrollBtn();
  // ★ 更新虚拟滚动消息数
  if (typeof PerfOpt !== 'undefined' && PerfOpt.setMessageCount) {
    PerfOpt.setMessageCount(window._globalMsgCount);
  }
}

// ★ ===== 快照回退功能 =====
var _pendingSnapshotId = null;

function showSnapshotRollbackModal(aiBlock) {
  // 获取快照列表
  if (typeof window._callPython !== 'function') {
    appendMsg('status', '<span style="color:#ff9800;">快照功能不可用</span>');
    return;
  }
  window._callPython('listSnapshots', function(result) {
    var snapshots = [];
    try {
      if (typeof result === 'string') result = JSON.parse(result);
      snapshots = result || [];
    } catch(e) {}

    if (!snapshots.length) {
      appendMsg('status', '<span style="color:#ff9800;">暂无可用快照</span>');
      return;
    }

    // 取最近的快照
    var snap = snapshots[0];
    _pendingSnapshotId = snap.id;

    // 显示对话框
    var overlay = document.getElementById('snapshotModalOverlay');
    var title = document.getElementById('snapshotModalTitle');
    var preview = document.getElementById('snapshotDiffPreview');

    title.innerHTML = SVG_ICONS['corner-down-left'] + ' 回退到: ' + (snap.label || snap.id) + ' (' + (snap.timestamp || '') + ')';
    preview.textContent = '正在获取差异...';

    overlay.classList.add('show');

    // 获取 diff
    window._callPython('diffSnapshot', snap.id, function(diffResult) {
      var diffText = diffResult || '无差异';
      if (diffText.length > 3000) diffText = diffText.substring(0, 3000) + '\n... (截断)';
      preview.textContent = diffText;
    });
  });
}

function closeSnapshotModal() {
  document.getElementById('snapshotModalOverlay').classList.remove('show');
  _pendingSnapshotId = null;
}

function confirmSnapshotRestore() {
  if (!_pendingSnapshotId) return;
  if (typeof window._callPython !== 'function') return;

  var btn = document.getElementById('snapshotConfirmBtn');
  btn.textContent = '回退中...';
  btn.disabled = true;

  window._callPython('restoreSnapshot', _pendingSnapshotId, function(result) {
    btn.textContent = '确认回退';
    btn.disabled = false;
    closeSnapshotModal();

    var res = result;
    try {
      if (typeof res === 'string') res = JSON.parse(res);
    } catch(e) {}

    if (res && res.success) {
      appendMsg('status', '<span style="color:#4caf50;">' + SVG_ICONS.check + ' ' + (res.message || '回退成功') + '</span>');
    } else {
      appendMsg('status', '<span style="color:#ff5252;">' + SVG_ICONS['circle-x'] + ' ' + (res && res.message ? res.message : '回退失败') + '</span>');
    }
  });
}

// ★ ===== Trae风格工作表功能 =====
var _todoList = [];
var _taskbarCollapsed = false;  // ★ v5.1: 任务条被用户收起后保持收起，避免 renderTodos 反复弹出
var _todoIdCounter = 0;
var _autoTodoEnabled = true;  // ★ 自动生成任务开关

// ★ v4.1.17: Worktree 隔离工作区
var _worktreeCache = null;

function toggleWorktreePanel() {
  var panel = document.getElementById('worktreePanel');
  if (!panel) return;
  var isOpen = panel.style.display !== 'none';
  if (isOpen) {
    panel.style.display = 'none';
  } else {
    panel.style.display = 'flex';
    refreshWorktreeList();
  }
}

function _callWorktree(sub, args, cb) {
  if (typeof window._callPython !== 'function') {
    if (cb) cb({success: false, error: '无后端通道'});
    return;
  }
  window._callPython('worktreeAction', [sub].concat(args || []), function(result) {
    try { if (typeof result === 'string') result = JSON.parse(result); } catch(e) {}
    if (cb) cb(result);
  });
}

function createWorktree() {
  var input = document.getElementById('worktreeTaskInput');
  var desc = input ? input.value.trim() : '';
  if (!desc) { input && input.focus(); return; }
  _callWorktree('create', [desc], function(r) {
    if (r && r.success) {
      input.value = '';
      refreshWorktreeList();
      // 提示隔离目录
      appendMsg('status', '<span style="color:#c39bd3;">◈ 已创建隔离工作区: <b>' + (r.branch||'') + '</b><br><span style="font-size:11px;">' + (r.path||'') + '</span></span>');
    } else {
      appendMsg('status', '<span style="color:#f44336;">◈ 创建失败: ' + ((r && r.error)||'未知') + '</span>');
    }
  });
}

function refreshWorktreeList() {
  _callWorktree('list', [], function(r) {
    if (!r || !r.success) return;
    _worktreeCache = r.worktrees || [];
    renderWorktreeList();
  });
}

function renderWorktreeList() {
  var listEl = document.getElementById('worktreeList');
  var countEl = document.getElementById('worktreeCount');
  var badge = document.getElementById('worktreeBadge');
  if (!listEl) return;
  var wts = _worktreeCache || [];
  if (countEl) countEl.textContent = wts.length + ' 个';
  if (badge) {
    var active = wts.filter(function(w){ return !/^(\s*)$/.test((w.branch||'').replace('agent-','')); }).length;
    badge.style.display = (wts.length > 1) ? 'block' : 'none';
    badge.textContent = wts.length - 1;  // 减去主 worktree
  }
  if (wts.length === 0) {
    listEl.innerHTML = '<div style="padding:20px;text-align:center;color:rgba(255,255,255,0.4);font-size:12px;">暂无隔离工作区<br><span style="font-size:10px;">输入任务描述创建（如: 重构 utils.py）</span></div>';
    return;
  }
  var html = '';
  wts.forEach(function(w) {
    var isAgent = /^agent-/.test(w.branch || '');
    html += '<div class="worktree-item" style="border-left-color:' + (isAgent ? '#9b59b6' : 'rgba(255,255,255,0.2)') + ';">' +
      '<div class="worktree-item-head">' +
        '<span class="worktree-item-branch">' + _escHtmlForTimeline(w.branch || '(detached)') + '</span>' +
        (isAgent ? '<span style="font-size:9px;background:#9b59b6;color:#fff;border-radius:3px;padding:0 4px;">隔离</span>' : '') +
        '<span style="margin-left:auto;font-size:10px;color:rgba(255,255,255,0.3);">' + _escHtmlForTimeline(w.head || '') + '</span>' +
      '</div>' +
      '<div class="worktree-item-path">' + _escHtmlForTimeline(w.path || '') + '</div>' +
      (isAgent ? '<div class="worktree-item-actions">' +
        '<button onclick="worktreeAction(\'status\',\'' + encodeURIComponent(w.path||'') + '\')">状态</button>' +
        '<button onclick="worktreeAction(\'merge_back\',\'' + encodeURIComponent(w.path||'') + '\')">合并回主</button>' +
        '<button class="danger" onclick="worktreeAction(\'remove\',\'' + encodeURIComponent(w.path||'') + '\')">清理</button>' +
      '</div>' : '') +
    '</div>';
  });
  listEl.innerHTML = html;
}

function worktreeAction(sub, encodedPath) {
  var path = decodeURIComponent(encodedPath || '');
  _callWorktree(sub, [path], function(r) {
    var ok = r && r.success;
    var msg = ok ? (r.message || (sub + ' 成功')) : ((r && r.error) || (sub + ' 失败'));
    appendMsg('status', '<span style="color:' + (ok ? '#c39bd3' : '#f44336') + ';">◈ ' + msg + '</span>');
    refreshWorktreeList();
  });
}

// ★ v4.1.20: Worktree × Actor 打通 — 每个子 Agent 在独立隔离 worktree 目录并行（真实引擎调用）
// ★ v4.1.21: 合并模式可选（auto 自动合并 / keep 保留供人工审阅）
// ★ v4.1.23: 打开页面时恢复上次持久化的合并模式
// ★ v4.1.24: 合并模式变更 — 同时记忆到 localStorage 与磁盘 JSON（与经典面板共享默认项）
function onWorktreeMergeModeChange(mode) {
  try { localStorage.setItem('lemon_worktree_actor_merge_mode', mode); } catch (e) {}
  try { _callWorktree('save_merge_mode', [mode]); } catch (e) {}
}
// ★ v4.1.24: 打开页面时恢复合并模式 — 优先读磁盘 JSON（与经典面板共享），回退 localStorage
(function restoreWorktreeActorMergeMode() {
  try {
    var sel = document.getElementById('worktreeActorMergeMode');
    if (!sel) return;
    var apply = function(mode) {
      try {
        if (mode === 'auto' || mode === 'keep') { sel.value = mode; }
        else {
          var ls = localStorage.getItem('lemon_worktree_actor_merge_mode');
          if (ls === 'auto' || ls === 'keep') sel.value = ls;
        }
      } catch (e) {}
    };
    try { _callWorktree('get_merge_mode', [], function(r) { apply(r && r.merge_mode); }); }
    catch (e) { apply(null); }
  } catch (e) {}
})();
function _renderWorktreeActorResult(r) {
  if (!r || !r.success) {
    appendMsg('status', '<span style="color:#f44336;">◈ Worktree Actor 失败: ' + ((r && r.error) || '未知') + '</span>');
    return;
  }
  var merged = (r.merge_mode === 'keep') ? false : true;
  var lines = '◈ Worktree Actor 完成：' + (r.worktrees || []).length + ' 个隔离目录，' + (r.results || []).length + ' 个子 Agent'
            + ' ｜ 合并模式：' + ((r.merge_mode === 'keep') ? '保留供审阅（未合并）' : '已自动合并回主分支') + '<br>';
  (r.results || []).forEach(function(res) {
    var ok = res.outcome === 'success';
    var txt = (res.result || res.error || '').toString();
    txt = txt.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    lines += '<span style="font-size:11px;color:' + (ok ? '#7bed9f' : '#f44336') + ';">' + (ok ? SVG_ICONS.check : SVG_ICONS['circle-x']) + ' ' + (res.actor_id || '') + ': ' + txt + '</span><br>';
  });
  if (!merged && (r.worktrees || []).length) {
    lines += '<span style="font-size:10px;color:#c39bd3;">' + SVG_ICONS['chevron-down'] + ' 隔离目录已保留在上方列表，可点"合并回主"手动合并。</span>';
  }
  appendMsg('status', '<span style="color:#c39bd3;">' + lines + '</span>');
  refreshWorktreeList();
}

function runWorktreeActor() {
  var tasks = [
    {"role":"架构师","title":"分析 Python Agent 模块划分","prompt":"请分析一个 Python Agent 系统的模块划分原则，不超过80字"},
    {"role":"审查员","title":"列出代码审查风险","prompt":"请列出代码审查中最常见的5个风险点，不超过80字"},
    {"role":"写手","title":"总结并行价值","prompt":"请用一句话总结为什么 Agent 需要并行执行能力，不超过60字"}
  ];
  var sel = document.getElementById('worktreeActorMergeMode');
  var mergeMode = (sel && sel.value) ? sel.value : 'auto';
  // ★ v4.1.23: 记忆本次选择，下次默认沿用
  try { localStorage.setItem('lemon_worktree_actor_merge_mode', mergeMode); } catch (e) {}
  var modeLabel = (mergeMode === 'keep') ? '保留隔离目录（不合并，供人工审阅）' : '自动合并回主分支';
  appendMsg('status', '<span style="color:#c39bd3;">◈ Worktree Actor 启动：为每个子 Agent 创建独立隔离 worktree 并并行执行（合并模式：' + modeLabel + '）...</span>');
  // ★ v4.1.25: 前端统一经 runWorktreeActorWorkflow pyqtSlot（hybrid_mode_bridge / PyBridge）走 QWebChannel；
  //   无 QWebChannel（如纯浏览器调试）时回退到 _callWorktree('actor_run', ...) 旧通道
  if (window.pybridge && typeof window.pybridge.runWorktreeActorWorkflow === 'function') {
    try {
      window.pybridge.runWorktreeActorWorkflow(JSON.stringify(tasks), mergeMode, function(res) {
        try { if (typeof res === 'string') res = JSON.parse(res); } catch(e) {}
        _renderWorktreeActorResult(res);
      });
      return;
    } catch (e) {}
  }
  _callWorktree('actor_run', [JSON.stringify(tasks), mergeMode], function(r) {
    try { if (typeof r === 'string') r = JSON.parse(r); } catch(e) {}
    _renderWorktreeActorResult(r);
  });
}

// ★ v4.1.15: 双 tab 切换（任务列表 / 文件列表）
// ★ v5.3: 明确挂在 window 上（clearOutput 用 window._timelineFiles 重置，避免 var hoisting 时序歧义）
window._timelineFiles = {};
var _currentTodoTab = 'tasks';

function switchTodoTab(tab) {
  _currentTodoTab = tab;
  var tabTasks = document.getElementById('tabTasks');
  var tabFiles = document.getElementById('tabFiles');
  var listEl = document.getElementById('todoList');
  var fileEl = document.getElementById('todoFileList');
  if (tab === 'files') {
    tabTasks.classList.remove('active');
    tabFiles.classList.add('active');
    listEl.style.display = 'none';
    fileEl.style.display = 'block';
    renderTodoFileList();
  } else {
    tabFiles.classList.remove('active');
    tabTasks.classList.add('active');
    fileEl.style.display = 'none';
    listEl.style.display = 'block';
  }
}

// ★ v4.1.15: 从 Timeline 事件统计文件操作（供"文件列表"tab使用）
function _trackTimelineFile(event) {
  if (!event || !event.file) return;
  var key = event.file;
  if (!_timelineFiles[key]) {
    _timelineFiles[key] = { count: 0, lastType: event.type || 'tool', lastTs: Date.now() };
  }
  _timelineFiles[key].count++;
  _timelineFiles[key].lastType = event.type || _timelineFiles[key].lastType;
  _timelineFiles[key].lastTs = Date.now();
  var countEl = document.getElementById('fileTabCount');
  if (countEl) {
    countEl.textContent = '(' + Object.keys(_timelineFiles).length + ')';
  }
  // ★ v4.1.28: 同步输入区任务条的文件数
  var tbFiles = document.getElementById('taskbarFileCount');
  if (tbFiles) tbFiles.textContent = Object.keys(_timelineFiles).length;
}

function renderTodoFileList() {
  var fileEl = document.getElementById('todoFileList');
  if (!fileEl) return;
  var files = Object.keys(_timelineFiles);
  if (files.length === 0) {
    fileEl.innerHTML = '<div style="padding:20px;text-align:center;color:rgba(255,255,255,0.4);">暂无文件操作<br><span style="font-size:11px;">Agent 读写文件时自动记录</span></div>';
    return;
  }
  // ★ v4.7.23: 去 emoji — tool 换极简线条 SVG（与 timeline iconMap 一致）
  var _svgToolTodo = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>';
  var typeIcon = { read:SVG_ICONS.eye, write:SVG_ICONS['square-pen'], search:SVG_ICONS.search, command:SVG_ICONS.zap, tool:_svgToolTodo };
  var typeColor = { read:'#4a9eff', write:'#ff9800', search:'#b388ff', command:'#4caf50', tool:'#ff9a4a' };
  var html = '';
  files.forEach(function(f) {
    var info = _timelineFiles[f];
    var icon = typeIcon[info.lastType] || '·';
    var color = typeColor[info.lastType] || '#a0a0a0';
    html += '<div class="todo-item pending" style="cursor:default;" title="' + _escHtmlForTimeline(f) + '">' +
      '<div class="todo-item-checkbox" style="background:' + color + ';color:#000;font-size:10px;display:flex;align-items:center;justify-content:center;">' + icon + '</div>' +
      '<div class="todo-text">' + _escHtmlForTimeline(f) +
        '<span style="color:rgba(255,255,255,0.35);font-size:10px;margin-left:6px;">' + info.count + ' 次</span>' +
      '</div>' +
    '</div>';
  });
  fileEl.innerHTML = html;
}

function toggleTodoPanel() {
  var panel = document.getElementById('todoPanel');
  if (panel.classList.contains('show')) {
    panel.classList.remove('show');
  } else {
    panel.classList.add('show');
    renderTodoList();
  }
}

function renderTodoList() {
  var listEl = document.getElementById('todoList');
  var countEl = document.getElementById('todoCount');
  var badgeEl = document.getElementById('todoBadge');

  if (!listEl) return;

  // 统计
  var completed = _todoList.filter(function(t) { return t.status === 'completed'; }).length;
  var total = _todoList.length;

  countEl.textContent = total + ' 项 (' + completed + '/' + total + ')';
  // ★ v4.1.15: 同步任务 tab 计数
  var tabCountEl = document.getElementById('todoTabCount');
  if (tabCountEl) { tabCountEl.textContent = '(' + total + ')'; }
  var fileCountEl = document.getElementById('fileTabCount');
  if (fileCountEl) { fileCountEl.textContent = '(' + Object.keys(_timelineFiles).length + ')'; }
  if (badgeEl) {
    if (total > 0) {
      badgeEl.style.display = 'block';
      badgeEl.textContent = total;
    } else {
      badgeEl.style.display = 'none';
    }
  }
  // ★ v4.1.28: 同步输入区任务条（CodeBuddy 式）
  var tbTasks = document.getElementById('taskbarTodoCount');
  if (tbTasks) tbTasks.textContent = total;
  var tbStatus = document.getElementById('taskbarStatus');
  if (tbStatus) {
    var _run = _todoList.filter(function(t) { return t.status === 'in_progress'; }).length;
    tbStatus.innerHTML = _run > 0 ? ('执行中 ' + _run + ' 步…') : (total > 0 && completed === total ? '全部完成 ' + SVG_ICONS.check : '就绪');
  }
  var tbBar = document.getElementById('agentTaskbar');
  // ★ v5.1: 仅当用户未主动收起任务条时才自动显示（收起状态由 _taskbarCollapsed 记录）
  if (tbBar && total > 0 && tbBar.style.display === 'none' && !_taskbarCollapsed) {
    tbBar.style.display = 'flex';
  }

  // 渲染列表
  if (_todoList.length === 0) {
    listEl.innerHTML = '<div style="padding:20px;text-align:center;color:rgba(255,255,255,0.4);">暂无任务<br><span style="font-size:11px;">AI回复时自动生成</span></div>';
    return;
  }

  var html = '';
  _todoList.forEach(function(todo) {
    var statusClass = todo.status === 'completed' ? 'completed' : (todo.status === 'in_progress' ? 'in-progress' : 'pending');
    var priorityClass = todo.priority || 'medium';
    var priorityText = todo.priority === 'high' ? '高' : (todo.priority === 'low' ? '低' : '中');

    html += '<div class="todo-item ' + statusClass + '" onclick="toggleTodoStatus(' + todo.id + ')">' +
      '<div class="todo-item-checkbox"></div>' +
      '<div class="todo-item-content">' + todo.content + '</div>' +
      '<span class="todo-item-priority ' + priorityClass + '">' + priorityText + '</span>' +
      '</div>';
  });
  listEl.innerHTML = html;
}

function toggleTodoStatus(id) {
  var todo = _todoList.find(function(t) { return t.id === id; });
  if (!todo) return;

  if (todo.status === 'pending') {
    todo.status = 'in_progress';
  } else if (todo.status === 'in_progress') {
    todo.status = 'completed';
    todo.completedAt = new Date().toISOString();
  } else {
    todo.status = 'pending';
    delete todo.completedAt;
  }
  renderTodoList();
}

function showAddTodoDialog() {
  _showInput('添加任务', '请输入任务内容：', '', function(content) {
    if (!content || !content.trim()) return;

  var priority = 'medium';
  if (content.indexOf('【高】') >= 0 || content.indexOf('紧急') >= 0 || content.indexOf('重要') >= 0) {
    priority = 'high';
  } else if (content.indexOf('【低】') >= 0 || content.indexOf('可选') >= 0) {
    priority = 'low';
  }

  _todoList.push({
    id: ++_todoIdCounter,
    content: content.trim(),
    status: 'pending',
    priority: priority,
    createdAt: new Date().toISOString()
  });
  renderTodoList();
  }); // _showInput callback
}

function clearCompletedTodos() {
  _todoList = _todoList.filter(function(t) { return t.status !== 'completed'; });
  renderTodoList();
}

// ★ ===== Trae风格：从AI回复中自动提取任务并生成工作表 =====
function autoGenerateTodos(text) {
  if (!_autoTodoEnabled || !text) return;
  
  var newTodos = [];
  
  // 模式1：检测带序号的任务列表（1. 2. 3. 或 - [ ] - [x]）
  var numberedTasks = text.match(/(?:^|\n)\s*(?:\d+[.、)]\s*|[-*]\s*\[[ x]\]\s*)([^\n]{2,80})/g);
  if (numberedTasks && numberedTasks.length > 0) {
    numberedTasks.forEach(function(line) {
      var content = line.replace(/(?:^|\n)\s*(?:\d+[.、)]\s*|[-*]\s*\[[ x]\]\s*)/, '').trim();
      if (content.length > 2 && content.length < 80) {
        // 判断优先级
        var priority = 'medium';
        if (/重要|紧急|必须|关键|核心/.test(content)) priority = 'high';
        else if (/可选|建议|后续|如果/.test(content)) priority = 'low';
        
        // 判断是否已完成
        var isCompleted = /\[[x]\]/.test(line);
        
        newTodos.push({
          id: ++_todoIdCounter,
          content: content,
          status: isCompleted ? 'completed' : 'pending',
          priority: priority,
          createdAt: new Date().toISOString()
        });
      }
    });
  }
  
  // 模式2：检测"首先...然后...最后"等步骤词
  if (newTodos.length === 0) {
    var steps = text.match(/(?:首先|然后|接着|其次|最后|第一步|第二步|第三步)[，,：:]\s*([^\n。；]{4,60})/g);
    if (steps && steps.length > 0) {
      steps.forEach(function(step) {
        var content = step.replace(/(?:首先|然后|接着|其次|最后|第一步|第二步|第三步)[，,：:]\s*/, '').trim();
        if (content.length > 2) {
          newTodos.push({
            id: ++_todoIdCounter,
            content: content,
            status: 'pending',
            priority: 'medium',
            createdAt: new Date().toISOString()
          });
        }
      });
    }
  }
  
  // 模式3：检测"需要""将要"开头的任务
  if (newTodos.length === 0) {
    var needs = text.match(/(?:需要|将要|应该|可以)([^\n。；]{4,50})/g);
    if (needs && needs.length > 0 && needs.length <= 8) {
      needs.forEach(function(need) {
        var content = need.trim();
        if (content.length > 4) {
          newTodos.push({
            id: ++_todoIdCounter,
            content: content,
            status: 'pending',
            priority: 'medium',
            createdAt: new Date().toISOString()
          });
        }
      });
    }
  }
  
  // 添加新任务（最多8个，避免过多）
  if (newTodos.length > 0 && newTodos.length <= 8) {
    _todoList = _todoList.concat(newTodos);
    renderTodoList();
    
    // 显示提示
    var badgeEl = document.getElementById('todoBadge');
    if (badgeEl) {
      badgeEl.style.display = 'block';
      badgeEl.textContent = _todoList.length;
      badgeEl.style.animation = 'pulse 0.5s ease';
      setTimeout(function() { badgeEl.style.animation = ''; }, 500);
    }
  }
}

// ★ ===== Agent设置面板 =====
function openAgentSettings() {
  openSettings();
  setTimeout(function() {
    var agentTab = document.querySelector('[data-section="agent"]');
    if (agentTab) agentTab.click();
  }, 100);
}

// Agent 身份切换
function onAgentIdentityChange(value) {
  var desc = document.getElementById('agentIdentityDesc');
  if (!desc) return;
  var descs = {
    'auto': '<strong>自动选择:</strong> 优先使用 MIMO Agent，当 MIMO Code 不可用时自动切换到 Lemon Agent。',
    'lemon': '<strong>Lemon Agent:</strong> 使用本地 Ollama 或 DeepSeek API 驱动，完全自主运行，不依赖 MIMO Code。<br><span style="color:#ff9a4a;">当前模式: 本地AI自主运行</span>',
    'mimo': '<strong>MIMO Agent:</strong> 通过 Process Bridge 夺舍 MIMO Code 窗口，共享其 AI 能力和文件系统。<br><span style="color:#ff9a4a;">当前模式: 夺舍 MIMO Code</span>'
  };
  desc.innerHTML = descs[value] || descs['auto'];

  // 通知 Python 端
  if (typeof pybridge !== 'undefined' && pybridge.sendMessage) {
    pybridge.sendMessage(JSON.stringify({
      type: 'agent_identity_change',
      identity: value
    }));
  }
}

// ★ v4.7.x: 设置面板连接测试（DeepSeek / Ollama）— 请求经 pybridge 到 Python 后台线程实测
function testApiConnection(engine) {
  var status = document.getElementById('connTestStatus-' + engine);
  function setStatus(text, color) {
    if (status) { status.textContent = text; status.style.color = color || 'rgba(255,255,255,0.5)'; }
  }
  var payload;
  if (engine === 'deepseek') {
    var keyEl = document.getElementById('set-deepseek-key');
    var epEl = document.getElementById('set-api-endpoint');
    var key = (keyEl && keyEl.value || '').trim();
    var ep = (epEl && epEl.value || '').trim() || 'https://api.deepseek.com/v1';
    if (!key) { setStatus('请先填写 API Key', '#ff6b6b'); return; }
    payload = { engine: 'deepseek', api_key: key, endpoint: ep };
  } else if (engine === 'ollama') {
    var hostEl = document.getElementById('set-ollama-host');
    payload = { engine: 'ollama', host: ((hostEl && hostEl.value) || 'http://localhost:11434').trim() };
  } else {
    return;
  }
  setStatus('测试中…', '#ffaa55');
  if (typeof pybridge !== 'undefined' && pybridge.sendMessage) {
    pybridge.sendMessage('__test_conn__:' + JSON.stringify(payload));
  } else {
    setStatus('桥接不可用', '#ff6b6b');
  }
}

// Python 端测试完成后回推（eval_js_signal 调用）
function onConnTestResult(engine, ok, message) {
  var status = document.getElementById('connTestStatus-' + engine);
  if (status) {
    status.textContent = message;
    status.style.color = ok ? '#51cf66' : '#ff6b6b';
  }
}

// ★第360章: 文件产出卡 — write/edit 工具成功后由 Python 推送（eval_js_signal 调用）
// 对标微信版"生成文件 → 下方文件卡 → 打开/导出"体验
function onFileCard(card) {
  try {
    var area = document.getElementById('outputMessages');
    if (!area || !card || !card.path) return;
    var esc = function (s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    };
    var sizeTxt = '';
    if (card.size >= 1048576) sizeTxt = (card.size / 1048576).toFixed(1) + ' MB';
    else if (card.size >= 1024) sizeTxt = (card.size / 1024).toFixed(1) + ' KB';
    else if (card.size > 0) sizeTxt = card.size + ' B';
    var el = document.createElement('div');
    el.className = 'file-card';
    el.innerHTML =
      '<div class="file-card-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/></svg></div>'
      + '<div class="file-card-info"><div class="file-card-name">' + esc(card.name) + '</div>'
      + '<div class="file-card-meta">' + (card.action === 'edited' ? '已编辑' : '已创建')
      + (sizeTxt ? ' · ' + sizeTxt : '') + '</div></div>'
      + '<div class="file-card-actions">'
      + '<button class="file-card-btn" data-act="open">打开</button>'
      + '<button class="file-card-btn primary" data-act="export">导出</button></div>';
    el.querySelector('[data-act="open"]').onclick = function () { sendFileAction('open', card.path); };
    el.querySelector('[data-act="export"]').onclick = function () { sendFileAction('export', card.path); };
    area.appendChild(el);
    area.scrollTop = area.scrollHeight;
  } catch (e) { console.error('[file-card]', e); }
}

function sendFileAction(act, path) {
  if (typeof pybridge !== 'undefined' && pybridge.sendMessage) {
    pybridge.sendMessage((act === 'export' ? '__file_export__:' : '__file_open__:') + path);
  }
}

// ★第361章: 会话框头部小风扇 — Agent 工作时旋转，任务结束消失（CSS 渲染）
function setAgentFan(on) {
  try {
    var bar = document.getElementById('agentFanBar');
    if (!bar) return;
    bar.style.display = on ? 'flex' : 'none';
  } catch (e) { console.error('[agent-fan]', e); }
}

// ★第361章: 会话级任务列表（Trae/CodeBuddy 式）— 数据来自 task_manager 工具，
// 按 session 隔离：本会话面板只收本会话的 task_list_changed 推送
// ★ Lemon Work: 默认折叠成细条 —— 展开态贴在聊天区顶部会压住内容/搜索框
var _taskPanelCollapsed = true;
function onTaskListUpdate(tasks) {
  try {
    var panel = document.getElementById('agentTaskPanel');
    if (!panel) return;
    // ★ Lemon Work: 默认停靠输入框上方（用户手动切回顶部后记忆为 top）
    if (!_taskPanelDocked && !_taskPanelDockTrying) _ensureTaskDock();
    tasks = Array.isArray(tasks) ? tasks : [];
    if (tasks.length === 0) { panel.style.display = 'none'; panel.innerHTML = ''; return; }
    var completed = tasks.filter(function (t) {
      return (t.status === 'completed' || t.status === 'done');
    }).length;
    var total = tasks.length;
    var pct = Math.round(completed / total * 100);
    var esc = function (s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    };
    var html = '<div class="atl-header" onclick="_toggleTaskPanel()">';
    html += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ff9a4a" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="4"/><polyline points="8,12.5 11,15.5 16,9.5"/></svg>';
    html += '<span class="atl-title">任务列表</span>';
    html += '<span class="atl-count">' + completed + '/' + total + '</span>';
    html += '<span class="atl-dock" title="停靠到输入框上方" onclick="event.stopPropagation();_toggleTaskDock()">⬇</span>';
    html += '<span class="atl-caret">' + (_taskPanelCollapsed ? '展开' : '收起') + '</span>';
    html += '</div>';
    html += '<div class="atl-progress"><div class="atl-progress-fill" style="width:' + pct + '%"></div></div>';
    if (!_taskPanelCollapsed) {
      html += '<div class="atl-items">';
      tasks.forEach(function (t) {
        var st = t.status || 'pending';
        var icon = '○', cls = 'pending';
        if (st === 'completed' || st === 'done') { icon = '✓'; cls = 'completed'; }
        else if (st === 'in_progress' || st === 'running') { icon = '◐'; cls = 'in-progress'; }
        else if (st === 'failed') { icon = '✗'; cls = 'failed'; }
        else if (st === 'blocked') { icon = '⊘'; cls = 'blocked'; }
        html += '<div class="atl-item ' + cls + '"><span class="atl-item-icon">' + icon + '</span>'
          + '<span class="atl-item-text">' + esc(t.content || t.title || t.id) + '</span></div>';
      });
      html += '</div>';
    }
    panel.innerHTML = html;
    panel._lastTasks = tasks;  // 折叠/展开重渲染用
    panel.style.display = 'block';
  } catch (e) { console.error('[task-list]', e); }
}

function _toggleTaskPanel() {
  _taskPanelCollapsed = !_taskPanelCollapsed;
  var panel = document.getElementById('agentTaskPanel');
  if (panel) { var head = panel.querySelector('.atl-header'); }
  // 重新渲染折叠态：记录 tasks 到面板数据集
  if (panel && panel._lastTasks) onTaskListUpdate(panel._lastTasks);
}

// ★ Lemon Work: 任务卡停靠 —— 顶部 sticky ⇄ 输入框上方（微信 task-dock 底部化）
// ★ 默认停靠：localStorage 记忆，用户手动切回顶部后记忆为 top
var _taskPanelDocked = false;
var _taskPanelHome = null;
var _taskPanelDockTrying = false;

function _ensureTaskDock() {
  try {
    if (_taskPanelDocked) return;
    // ★ v5: 换新 key（旧的 'top' 记忆不再生效）—— 默认必须停靠输入框上方
    if (localStorage.getItem('lw_task_dock_v3') === 'top') return;
    _taskPanelDockTrying = true;
    _toggleTaskDock();
  } catch (e) {}
}

function _toggleTaskDock() {
  var panel = document.getElementById('agentTaskPanel');
  if (!panel) return;
  if (!_taskPanelDocked) {
    _taskPanelHome = panel.nextSibling;   // 记住原位置（pendingQueueBar 前）
    var ia = document.querySelector('#content .input-area');
    var box = ia ? ia.querySelector('.input-box') : null;
    if (ia && box) {
      ia.insertBefore(panel, box);
      panel.classList.add('docked');
      _taskPanelDocked = true;
      try { localStorage.setItem('lw_task_dock_v3', 'docked'); } catch (e) {}
    }
  } else {
    var oa = document.getElementById('outputArea');
    if (oa) {
      var fan = document.getElementById('agentFanBar');
      if (fan && fan.nextSibling) oa.insertBefore(panel, fan.nextSibling);
      else oa.insertBefore(panel, oa.firstChild);
      panel.classList.remove('docked');
      _taskPanelDocked = false;
      try { localStorage.setItem('lw_task_dock_v3', 'top'); } catch (e) {}
    }
  }
  if (panel._lastTasks) onTaskListUpdate(panel._lastTasks);
}

// ★第361章: 子代理状态（每会话独立）
// ★ Lemon Work: 一行 chip 升级为专属卡（微信版子代理气泡对齐）——
//   名称/任务/状态/耗时/结果摘要全展示，插入对话流不随轮次折叠
function onSubagentUpdate(info) {
  try {
    var area = document.getElementById('outputMessages');
    if (!area || !info) return;
    var esc = function (s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    };
    var done = info.phase === 'done';
    var failed = info.phase === 'failed';
    var card = document.createElement('div');
    card.className = 'subagent-card ' + (done ? 'done' : (failed ? 'failed' : 'running'));
    card.innerHTML =
      '<div class="sa-head">' +
        '<span class="sa-icon">⧉</span>' +
        '<span class="sa-name">' + esc(info.name || '子代理') + '</span>' +
        '<span class="sa-phase">' + (done ? '✓ 已完成' : (failed ? '✗ 失败' : '◐ 运行中')) + '</span>' +
        (info.elapsed ? '<span class="sa-elapsed">' + esc(info.elapsed) + 's</span>' : '') +
      '</div>' +
      (info.task ? '<div class="sa-task">' + esc(info.task) + '</div>' : '') +
      (info.summary ? '<div class="sa-summary">' + esc(info.summary) + '</div>' : '');
    area.appendChild(card);
    area.scrollTop = area.scrollHeight;
    // 底部任务看板 chip 保留一行最小状态（向后兼容）
    var panel = document.getElementById('agentTaskPanel');
    if (!panel) return;
    var chip = document.getElementById('atlSubagentChip');
    if (!chip) {
      chip = document.createElement('div');
      chip.id = 'atlSubagentChip';
      panel.appendChild(chip);
    }
    var cls = info.phase === 'done' ? 'done' : (info.phase === 'failed' ? 'failed' : 'running');
    chip.className = 'atl-subagent ' + cls;
    chip.textContent = '⧉ 子代理 · ' + (info.name || '') + ' · ' +
      (cls === 'running' ? '运行中' : (cls === 'done' ? '已完成' : '失败'));
  } catch (e) { console.error('[subagent-card]', e); }
}

// ★第362章: 对话消息排队角标 — Agent 运行中新消息排队，收口自动续跑
// ★ Lemon Work: 升级为可展开列表 —— 逐条预览 + 单条撤销（微信 task-dock 对齐）
var _pqExpanded = false;
var _pqItems = [];

function setPendingQueue(n, note, items, paused) {
  try {
    var bar = document.getElementById('pendingQueueBar');
    if (!bar) return;
    n = parseInt(n || 0, 10) || 0;
    _pqItems = Array.isArray(items) ? items : [];
    _pqPaused = !!paused;
    bar.style.display = n > 0 ? 'flex' : 'none';
    if (n > 0) {
      document.getElementById('pendingQueueText').textContent = n + ' 条排队中';
      document.getElementById('pendingQueueNote').textContent = note || '';
      if (_pqItems.length) _pqExpanded = true;  // ★ 有内容自动展开列表
      renderPendingQueueList(bar);
    }
  } catch (e) { console.error('[pending-queue]', e); }
}

// ★ v350 微信版队列对齐：挂起/继续 —— 状态真源在后端。
//   ★ 漏洞修复：此前前端本地翻转 _pqPaused，刷新/重连后与后端不同步；
//   现只调后端，由 _update_pending_ui 回推真实 paused 态重渲染。
var _pqPaused = false;
function _toggleQueuePause() {
  if (typeof window._callPython === 'function') {
    window._callPython(_pqPaused ? 'resumeQueue' : 'pauseQueue', '');
  }
  // 乐观更新 UI（后端回推会再校正一次）
  _pqPaused = !_pqPaused;
  var bar = document.getElementById('pendingQueueBar');
  if (bar) renderPendingQueueList(bar);
}

function _togglePendingQueueList() {
  _pqExpanded = !_pqExpanded;
  var bar = document.getElementById('pendingQueueBar');
  if (bar) renderPendingQueueList(bar);
}

function renderPendingQueueList(bar) {
  var old = bar.parentNode.querySelector('.pq-items');
  if (old) old.remove();
  // ★ v350: 挂起旗标 + 挂起态操作行（继续发送 / 清空队列）
  var pq = bar.parentNode.querySelector('.pq-paused-row');
  if (pq) pq.remove();
  var note = document.getElementById('pendingQueueNote');
  if (note) {
    note.textContent = _pqPaused ? '已挂起（不再自动发送）' : (note.dataset.base || '');
    note.dataset.base = note.dataset.base || note.textContent;
    if (_pqPaused) note.textContent = '已挂起（不再自动发送）';
  }
  var pauseBtn = bar.querySelector('.pq-pause');
  if (pauseBtn) pauseBtn.textContent = _pqPaused ? '▶ 继续' : '⏸ 挂起';
  if (_pqPaused) {
    var prow = document.createElement('div');
    prow.className = 'pq-paused-row';
    prow.innerHTML = '<span class="pq-resume" onclick="_toggleQueuePause()">▶ 继续发送</span>' +
      '<span class="pq-clear" onclick="clearPendingQueue()">清空队列</span>';
    bar.parentNode.insertBefore(prow, bar.nextSibling);
  }
  if (!_pqExpanded || !_pqItems.length) return;
  var list = document.createElement('div');
  list.className = 'pq-items';
  for (var i = 0; i < _pqItems.length; i++) {
    (function (it) {
      var row = document.createElement('div');
      row.className = 'pq-item';
      row.innerHTML =
        '<span class="pq-item-idx">' + (it.i + 1) + '</span>' +
        '<span class="pq-item-text">' + String(it.preview || '').replace(/</g, '&lt;') + '</span>' +
        '<span class="pq-item-ops">' +
        '<span class="pq-op pq-op-send" title="立即发送">↑</span>' +
        '<span class="pq-op pq-op-edit" title="取回编辑">✎</span>' +
        '<span class="pq-op pq-op-del" title="撤销这条">✕</span></span>';
      row.querySelector('.pq-op-send').onclick = function () {
        if (typeof window._callPython === 'function') {
          window._callPython('sendQueuedNow', it.i);
        }
      };
      row.querySelector('.pq-op-edit').onclick = function () {
        // 取回编辑：内容填回输入框 + 从队列移除
        var ta = document.getElementById('userInput') ||
                 document.querySelector('.input-box textarea');
        if (ta && it.full) { ta.value = it.full; ta.focus(); }
        if (typeof window._callPython === 'function') {
          window._callPython('removeQueuedMessage', it.i);
        }
      };
      row.querySelector('.pq-op-del').onclick = function () {
        if (typeof window._callPython === 'function') {
          window._callPython('removeQueuedMessage', it.i);
        }
      };
      list.appendChild(row);
    })(_pqItems[i]);
  }
  bar.parentNode.insertBefore(list, bar.nextSibling);
}

function clearPendingQueue() {
  if (typeof pybridge !== 'undefined' && pybridge.sendMessage) {
    pybridge.sendMessage('__clear_pending__');
  }
}

// ★ 保存 Agent 设置
function saveAgentSettings() {
  var settings = {
    agent_identity: (document.getElementById('set-agent-identity') || {}).value || 'auto',
    default_engine: (document.getElementById('set-default-engine') || {}).value || 'auto',
    deepseek_key: (document.getElementById('set-deepseek-key') || {}).value || '',
    api_endpoint: (document.getElementById('set-api-endpoint') || {}).value || '',
    ollama_model: (document.getElementById('set-ollama-model') || {}).value || 'qwen2.5:1.5b',
    ollama_host: (document.getElementById('set-ollama-host') || {}).value || 'http://localhost:11434',
    hybrid_mode: (document.getElementById('set-hybrid-mode') || {}).classList ? document.getElementById('set-hybrid-mode').classList.contains('active') : false,
    smart_route: (document.getElementById('set-smart-route') || {}).classList ? document.getElementById('set-smart-route').classList.contains('active') : true,
  };
  localStorage.setItem('lemon_agent_settings', JSON.stringify(settings));

  // 通知 Python 端
  if (typeof pybridge !== 'undefined' && pybridge.sendMessage) {
    pybridge.sendMessage(JSON.stringify({
      type: 'agent_settings_save',
      settings: settings
    }));
  }
  console.log('[Agent] 设置已保存:', settings);
}

// 加载 Agent 设置
function loadAgentSettings() {
  try {
    var saved = localStorage.getItem('lemon_agent_settings');
    if (saved) {
      var settings = JSON.parse(saved);
      document.getElementById('set-agent-identity') && (document.getElementById('set-agent-identity').value = settings.agent_identity || 'auto');
      document.getElementById('set-default-engine') && (document.getElementById('set-default-engine').value = settings.default_engine || 'auto');
      document.getElementById('set-deepseek-key') && (document.getElementById('set-deepseek-key').value = settings.deepseek_key || '');
      document.getElementById('set-api-endpoint') && (document.getElementById('set-api-endpoint').value = settings.api_endpoint || '');
      document.getElementById('set-ollama-model') && (document.getElementById('set-ollama-model').value = settings.ollama_model || 'qwen2.5:1.5b');
      document.getElementById('set-ollama-host') && (document.getElementById('set-ollama-host').value = settings.ollama_host || 'http://localhost:11434');
      if (settings.hybrid_mode) { var hm = document.getElementById('set-hybrid-mode'); if (hm) hm.classList.add('active'); }
      if (!settings.smart_route) { var sr = document.getElementById('set-smart-route'); if (sr) sr.classList.remove('active'); }
    }
  } catch(e) {}
}

// 初始化时加载
document.addEventListener('DOMContentLoaded', function() {
  loadAgentSettings();
  // ★ P8: 初始化会话管理器
  if (typeof _initSessionManager === 'function') {
    _initSessionManager();
  }
});

// ★ 保存设置时同时保存 Agent 配置
var _origSaveSettings = typeof saveSettings === 'function' ? saveSettings : null;
if (typeof saveSettings !== 'undefined') {
  // 在 saveSettings 之后也保存 Agent 配置
  document.addEventListener('settings-saved', saveAgentSettings);
}

// ★ ===== 快捷键绑定：Ctrl+T 打开工作表 =====
document.addEventListener('keydown', function(e) {
  if (e.ctrlKey && e.key === 't') {
    e.preventDefault();
    toggleTodoPanel();
  }
});

// ★ ===== Trae风格：对话流折叠（已完成步骤自动折叠为摘要） =====
function createCollapsibleSection(title, content, isCompleted) {
  var id = 'collapse_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
  var html = '<div class="dialog-flow-collapse' + (isCompleted ? '' : ' expanded') + '" id="' + id + '">';
  html += '<div class="dialog-flow-collapse-header" onclick="toggleCollapseSection(\'' + id + '\')">';
  html += '<svg class="collapse-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>';
  html += '<span class="collapse-summary">' + title + '</span>';
  if (isCompleted) {
    html += '<span class="collapse-status">已完成</span>';
  }
  html += '</div>';
  html += '<div class="dialog-flow-collapse-body">' + content + '</div>';
  html += '</div>';
  return html;
}

function toggleCollapseSection(id) {
  var section = document.getElementById(id);
  if (section) {
    section.classList.toggle('expanded');
  }
}

// ★ ===== Trae风格：任务进度追踪（内嵌对话流） =====
function renderTaskProgressInline(tasks) {
  if (!tasks || tasks.length === 0) return '';
  
  var completed = tasks.filter(function(t) { return t.status === 'completed'; }).length;
  var total = tasks.length;
  var progress = Math.round(completed / total * 100);
  
  var html = '<div class="task-progress-inline">';
  html += '<div class="task-progress-inline-header">';
  html += '<div class="task-progress-inline-title">';
  html += '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ff6900" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><polyline points="7,9 8,10 10,8"/><line x1="12" y1="9" x2="17" y2="9"/></svg>';
  html += '任务进度';
  html += '</div>';
  html += '<span class="task-progress-inline-count">' + completed + '/' + total + '</span>';
  html += '</div>';
  html += '<div class="task-progress-inline-bar">';
  html += '<div class="task-progress-inline-fill" style="width:' + progress + '%"></div>';
  html += '</div>';
  html += '<div class="task-progress-inline-list">';
  
  tasks.forEach(function(task) {
    var statusClass = task.status === 'completed' ? 'completed' : (task.status === 'in_progress' ? 'in-progress' : '');
    html += '<div class="task-progress-inline-item ' + statusClass + '">';
    html += '<div class="task-dot"></div>';
    html += '<span class="task-text">' + task.content + '</span>';
    html += '</div>';
  });
  
  html += '</div>';
  html += '</div>';
  return html;
}

// ★ ===== 自动检测AI回复中的任务列表并渲染进度追踪 =====
function autoRenderTaskProgress(container) {
  if (!container) return;
  var text = container.textContent || '';
  
  // 检测带序号的任务列表
  var taskMatches = text.match(/(?:^|\n)\s*(?:\d+[.、)]\s*|[-*]\s*\[[ x]\]\s*)([^\n]{2,60})/g);
  if (taskMatches && taskMatches.length >= 2 && taskMatches.length <= 10) {
    var tasks = [];
    taskMatches.forEach(function(match) {
      var content = match.replace(/(?:^|\n)\s*(?:\d+[.、)]\s*|[-*]\s*\[[ x]\]\s*)/, '').trim();
      if (content.length > 2) {
        var isCompleted = /\[[x]\]/.test(match);
        tasks.push({
          content: content,
          status: isCompleted ? 'completed' : 'pending'
        });
      }
    });
    
    if (tasks.length >= 2) {
      var progressHtml = renderTaskProgressInline(tasks);
      if (progressHtml) {
        var progressDiv = document.createElement('div');
        progressDiv.innerHTML = progressHtml;
        container.appendChild(progressDiv);
      }
    }
  }
}

// ★ ===== Trae风格：Diff视图渲染（代码变更对比） =====
function renderDiffView(oldText, newText, fileName) {
  var id = 'diff_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
  var oldLines = (oldText || '').split('\n');
  var newLines = (newText || '').split('\n');

  // 简化的LCS差异算法
  var diffs = _computeDiff(oldLines, newLines);
  var addedCount = 0, removedCount = 0;
  var html = '<div class="diff-view" id="' + id + '">';
  html += '<div class="diff-view-header">';
  html += '<div class="diff-view-title">';
  html += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ff9a4a" stroke-width="2"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 21h16"/></svg>';
  html += '<span>' + (fileName || '代码变更') + '</span>';
  html += '</div>';
  html += '<div class="diff-view-stats">';

  // 统计增删
  diffs.forEach(function(d) {
    if (d.type === 'added') addedCount++;
    else if (d.type === 'removed') removedCount++;
  });
  html += '<span class="added">+' + addedCount + '</span>';
  html += '<span class="removed">-' + removedCount + '</span>';
  html += '</div></div>';

  // ★ 块级渲染：将连续的同类型行分组
  var blocks = [];
  var currentBlock = null;
  diffs.forEach(function(d) {
    if (d.type === 'context') {
      if (currentBlock) { blocks.push(currentBlock); currentBlock = null; }
      blocks.push({ type: 'context', lines: [d] });
      d._lineNum = newLineNum;
      oldLineNum++; newLineNum++;
    } else if (d.type === 'added') {
      if (!currentBlock || currentBlock.type !== 'added') {
        if (currentBlock) blocks.push(currentBlock);
        currentBlock = { type: 'added', lines: [], count: 0 };
      }
      currentBlock.lines.push(d);
      currentBlock.count++;
      d._lineNum = newLineNum;
      newLineNum++;
    } else if (d.type === 'removed') {
      if (!currentBlock || currentBlock.type !== 'removed') {
        if (currentBlock) blocks.push(currentBlock);
        currentBlock = { type: 'removed', lines: [], count: 0 };
      }
      currentBlock.lines.push(d);
      currentBlock.count++;
      d._lineNum = oldLineNum;
      oldLineNum++;
    }
  });
  if (currentBlock) blocks.push(currentBlock);

  // ★ 渲染块级diff
  html += '<div class="diff-view-body">';
  blocks.forEach(function(block) {
    if (block.type === 'context') {
      block.lines.forEach(function(d) {
        html += '<div class="diff-line context">';
        html += '<div class="diff-line-num">' + d._lineNum + '</div>';
        html += '<div class="diff-line-content">' + _escapeHtml(d.text) + '</div>';
        html += '</div>';
      });
    } else if (block.type === 'added') {
      var indicator = block.count > 1 ? ('+ ' + block.count + ' 行') : '+ 新增';
      html += '<div class="diff-block added">';
      html += '<div class="diff-block-indicator">' + indicator + '</div>';
      block.lines.forEach(function(d) {
        html += '<div class="diff-line added">';
        html += '<div class="diff-line-num">+</div>';
        html += '<div class="diff-line-content">' + _escapeHtml(d.text) + '</div>';
        html += '</div>';
      });
      html += '</div>';
    } else if (block.type === 'removed') {
      var indicator = block.count > 1 ? ('- ' + block.count + ' 行') : '- 删除';
      html += '<div class="diff-block removed">';
      html += '<div class="diff-block-indicator">' + indicator + '</div>';
      block.lines.forEach(function(d) {
        html += '<div class="diff-line removed">';
        html += '<div class="diff-line-num">-</div>';
        html += '<div class="diff-line-content">' + _escapeHtml(d.text) + '</div>';
        html += '</div>';
      });
      html += '</div>';
    }
  });
  html += '</div></div>';
  return html;
}

// 简化LCS差异算法
function _computeDiff(oldLines, newLines) {
  var m = oldLines.length, n = newLines.length;
  // 简单的逐行对比（避免O(m*n)内存爆炸，限制行数）
  if (m > 200 || n > 200) {
    var result = [];
    var max = Math.max(m, n);
    for (var i = 0; i < max; i++) {
      if (i < m && i < n && oldLines[i] === newLines[i]) {
        result.push({type: 'context', text: oldLines[i]});
      } else {
        if (i < m) result.push({type: 'removed', text: oldLines[i]});
        if (i < n) result.push({type: 'added', text: newLines[i]});
      }
    }
    return result;
  }
  // LCS动态规划
  var dp = [];
  for (var i = 0; i <= m; i++) {
    dp.push(new Array(n + 1).fill(0));
  }
  for (i = 1; i <= m; i++) {
    for (var j = 1; j <= n; j++) {
      if (oldLines[i-1] === newLines[j-1]) {
        dp[i][j] = dp[i-1][j-1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i-1][j], dp[i][j-1]);
      }
    }
  }
  // 回溯
  var result = [];
  i = m; j = n;
  while (i > 0 && j > 0) {
    if (oldLines[i-1] === newLines[j-1]) {
      result.unshift({type: 'context', text: oldLines[i-1]});
      i--; j--;
    } else if (dp[i-1][j] >= dp[i][j-1]) {
      result.unshift({type: 'removed', text: oldLines[i-1]});
      i--;
    } else {
      result.unshift({type: 'added', text: newLines[j-1]});
      j--;
    }
  }
  while (i > 0) {
    result.unshift({type: 'removed', text: oldLines[i-1]});
    i--;
  }
  while (j > 0) {
    result.unshift({type: 'added', text: newLines[j-1]});
    j--;
  }
  return result;
}

function _escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ★ ===== Trae风格：工具面板Tab切换 =====
var _toolPanelTabs = [
  {id: 'skills', name: '技能', icon: '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>'},
  {id: 'tasks', name: '任务', icon: '<polyline points="7,9 8,10 10,8"/><line x1="12" y1="9" x2="17" y2="9"/>'},
  {id: 'thinking', name: '思考', icon: '<path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/><circle cx="12" cy="12" r="3"/><path d="M12 2v4"/><path d="M12 18v4"/><path d="M4.93 4.93l2.83 2.83"/><path d="M16.24 16.24l2.83 2.83"/><path d="M2 12h4"/><path d="M18 12h4"/>'},
  {id: 'files', name: '文件', icon: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'},
  {id: 'market', name: '市场', icon: '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>'},
  {id: 'snaps', name: '快照', icon: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="3"/>'},
  {id: 'history', name: '历史', icon: '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/>'},
  {id: 'docs', name: '文档', icon: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'},
  {id: 'charts', name: '图表', icon: '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>'},
  {id: 'finance', name: '金融', icon: '<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>'},
  {id: 'notes', name: '笔记', icon: '<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>'}
];
var _activeToolPanel = 'skills';

function renderToolPanelTabs() {
  var container = document.getElementById('toolPanelTabs');
  if (!container) return;
  var html = '';
  _toolPanelTabs.forEach(function(tab) {
    var cls = tab.id === _activeToolPanel ? 'tool-panel-tab active' : 'tool-panel-tab';
    html += '<div class="' + cls + '" onclick="switchToolPanel(\'' + tab.id + '\')">';
    html += '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">';
    html += tab.icon;
    html += '</svg>';
    html += '<span>' + tab.name + '</span>';
    html += '</div>';
  });
  container.innerHTML = html;
}

function switchToolPanel(tabId) {
  _activeToolPanel = tabId;
  renderToolPanelTabs();
  _refreshCurrentPanel();
}

// ============================================================
// ★ 增强右侧面板 — 状态管理
// ============================================================
var _skillStatuses = {};
var _skillOutputs = {};
var _expandedSkillOutput = null;
var _tasks = [];
var _thinkingEntries = [];
var _fileChanges = {files: [], totalAdded: 0, totalDeleted: 0};
var _expandedFileDiff = null;

function _refreshCurrentPanel() {
  var content = document.getElementById('toolPanelContent');
  if (!content) return;
  var titleEl = document.getElementById('panelTitleText');
  if (titleEl) {
    var tabNames = {skills:'技能面板', tasks:'任务列表', thinking:'思考过程', files:'文件变更', market:'插件市场', snaps:'代码快照', history:'会话管理', docs:'文档预览', charts:'数据图表', finance:'金融助手', notes:'AI笔记'};
    titleEl.textContent = tabNames[_activeToolPanel] || '工具面板';
  }
  switch (_activeToolPanel) {
    case 'skills': content.innerHTML = _renderSkillsList(); break;
    case 'tasks': content.innerHTML = _renderTasksPanel(); break;
    case 'thinking': content.innerHTML = _renderThinkingPanel(); break;
    case 'files': content.innerHTML = _renderFilePanel(); break;
    case 'snaps': content.innerHTML = '<div style="padding:12px;color:rgba(255,255,255,0.6);font-size:12px;">点击快照按钮管理代码快照</div>'; break;
    case 'market': content.innerHTML = _renderMarketplacePanel(); break;
    case 'history': content.innerHTML = _renderSessionManager(); break;
    case 'docs': content.innerHTML = _renderDocsPanel(); break;
    case 'charts': content.innerHTML = _renderChartsPanel(); break;
    case 'finance': content.innerHTML = _renderFinancePanel(); break;
    case 'notes': content.innerHTML = _renderNotesPanel(); break;
  }
}

// ============================================================
// ★ 插件市场面板 — 浏览/搜索/安装插件
// ============================================================

// 插件市场数据（内置示例，与 plugin_repository.py 同步）
var _marketPlugins = [
  {name:'code_reviewer', version:'1.0.0', desc:'代码审查助手 — 自动检测代码质量问题', author:'Lemon Team', category:'code', downloads:1250, rating:4.7, verified:true, official:true},
  {name:'test_generator', version:'1.0.0', desc:'测试生成器 — 自动生成单元测试', author:'Lemon Team', category:'code', downloads:980, rating:4.5, verified:true, official:true},
  {name:'deep_researcher', version:'1.0.0', desc:'深度研究器 — 多轮搜索+信息验证', author:'Lemon Team', category:'research', downloads:750, rating:4.3, verified:true},
  {name:'security_auditor', version:'1.0.0', desc:'安全审计员 — 代码漏洞扫描', author:'Lemon Team', category:'security', downloads:680, rating:4.8, verified:true, official:true},
  {name:'math_solver', version:'1.0.0', desc:'数学求解器 — 方程/微积分/线性代数', author:'Lemon Team', category:'math', downloads:890, rating:4.6, verified:true},
  {name:'web_researcher', version:'1.0.0', desc:'网络研究员 — 实时搜索+网页抓取', author:'Lemon Team', category:'research', downloads:620, rating:4.2, verified:true},
  {name:'math_plotter', version:'1.0.0', desc:'数学绘图器 — 函数图像+3D图形', author:'Lemon Team', category:'visual', downloads:540, rating:4.4, verified:true},
  {name:'office_generator', version:'1.0.0', desc:'办公文档生成器 — Word/Excel/PPT', author:'Lemon Team', category:'office', downloads:430, rating:4.1, verified:true},
  {name:'fact_checker', version:'1.0.0', desc:'事实核查器 — 交叉验证+来源对比', author:'Lemon Team', category:'research', downloads:320, rating:4.3, verified:true},
  {name:'html_to_video', version:'1.0.0', desc:'HTML转视频 — 网页渲染为视频', author:'Lemon Team', category:'media', downloads:290, rating:3.9},
  {name:'deploy_helper', version:'1.0.0', desc:'部署助手 — 一键部署到Docker/K8s', author:'Lemon Team', category:'devops', downloads:260, rating:4.0, verified:true},
  {name:'code_psychologist', version:'1.0.0', desc:'代码心理学家 — 代码风格心理分析', author:'Lemon Team', category:'fun', downloads:450, rating:4.5},
  {name:'multi_model_debater', version:'1.0.0', desc:'多模型辩论家 — AI多模型共识', author:'Lemon Team', category:'ai', downloads:350, rating:4.4, verified:true},
  {name:'self_documenter', version:'1.0.0', desc:'自文档化 — 自动生成API文档', author:'Lemon Team', category:'documentation', downloads:410, rating:4.2, verified:true},
  {name:'arxiv_researcher', version:'1.0.0', desc:'arXiv研究员 — 学术论文搜索', author:'Lemon Team', category:'research', downloads:310, rating:4.1, verified:true},
  {name:'academic_writer', version:'1.0.0', desc:'学术写作助手 — LaTeX论文写作', author:'Lemon Team', category:'documentation', downloads:240, rating:4.0},
  {name:'skill_creator', version:'1.0.0', desc:'Skill创建器 — 快速创建自定义Skill', author:'Lemon Team', category:'system', downloads:180, rating:3.8, verified:true},
  {name:'frontend_designer', version:'1.0.0', desc:'前端设计师 — HTML/CSS/JSX组件', author:'Lemon Team', category:'visual', downloads:220, rating:3.9},
  {name:'physics_experiment', version:'1.0.0', desc:'物理实验模拟 — 力学/电磁学可视化', author:'Lemon Team', category:'visual', downloads:190, rating:4.0},
  {name:'image_processor', version:'1.0.0', desc:'图像处理器 — 格式转换+裁剪+滤镜', author:'Lemon Team', category:'image', downloads:380, rating:4.0, verified:true}
];
var _marketSearch = '';
var _marketCategory = 'all';
var _marketSort = 'downloads';

function _renderMarketplacePanel() {
  var html = '';
  // 搜索栏
  html += '<div style="padding:10px 12px;border-bottom:1px solid rgba(255,255,255,0.06);">';
  html += '<div style="display:flex;gap:6px;">';
  html += '<input type="text" id="marketSearchInput" placeholder="搜索插件..." value="' + _escapeHtml(_marketSearch) + '" oninput="_marketSearch=this.value;_refreshCurrentPanel()" style="flex:1;padding:6px 10px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:rgba(255,255,255,0.8);font-size:12px;outline:none;">';
  html += '<select onchange="_marketCategory=this.value;_refreshCurrentPanel()" style="width:80px;padding:6px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:rgba(255,255,255,0.7);font-size:11px;outline:none;">';
  html += '<option value="all"' + (_marketCategory==='all'?' selected':'') + '>全部</option>';
  var cats = {};
  _marketPlugins.forEach(function(p) { cats[p.category] = (cats[p.category]||0)+1; });
  Object.keys(cats).sort().forEach(function(c) {
    html += '<option value="' + c + '"' + (_marketCategory===c?' selected':'') + '>' + c + ' (' + cats[c] + ')</option>';
  });
  html += '</select></div></div>';
  // 排序
  html += '<div style="padding:6px 12px;display:flex;gap:8px;border-bottom:1px solid rgba(255,255,255,0.04);">';
  var sorts = [{id:'downloads',label:'热门'},{id:'rating',label:'评分'},{id:'name',label:'名称'}];
  sorts.forEach(function(s) {
    html += '<button onclick="_marketSort=\'' + s.id + '\'; _refreshCurrentPanel()" style="padding:3px 10px;border-radius:3px;font-size:11px;border:1px solid ' + (_marketSort===s.id?'rgba(255,154,74,0.4)':'rgba(255,255,255,0.08)') + ';background:' + (_marketSort===s.id?'rgba(255,154,74,0.15)':'rgba(0,0,0,0.2)') + ';color:' + (_marketSort===s.id?'#ff9a4a':'rgba(255,255,255,0.5)') + ';cursor:pointer;">' + s.label + '</button>';
  });
  html += '<span style="margin-left:auto;color:rgba(255,255,255,0.3);font-size:10px;">共' + _marketPlugins.length + '个插件</span></div>';
  // 插件列表
  var filtered = _marketPlugins;
  if (_marketSearch) {
    var kw = _marketSearch.toLowerCase();
    filtered = filtered.filter(function(p) { return p.name.toLowerCase().indexOf(kw)>=0 || p.desc.toLowerCase().indexOf(kw)>=0 || p.category.toLowerCase().indexOf(kw)>=0; });
  }
  if (_marketCategory !== 'all') {
    filtered = filtered.filter(function(p) { return p.category === _marketCategory; });
  }
  if (_marketSort === 'downloads') filtered.sort(function(a,b) { return b.downloads - a.downloads; });
  else if (_marketSort === 'rating') filtered.sort(function(a,b) { return b.rating - a.rating; });
  else filtered.sort(function(a,b) { return a.name.localeCompare(b.name); });

  html += '<div style="overflow-y:auto;flex:1;min-height:0;">';
  if (filtered.length === 0) {
    html += '<div style="padding:20px;text-align:center;color:rgba(255,255,255,0.3);font-size:12px;">未找到插件</div>';
  } else {
    filtered.forEach(function(p) {
      var stars = '';
      for (var i = 0; i < 5; i++) { stars += i < Math.round(p.rating) ? '★' : SVG_ICONS.sparkles; }
      html += '<div class="market-plugin-card" onclick="_installMarketPlugin(\'' + p.name + '\')" style="padding:10px 12px;border-bottom:1px solid rgba(255,255,255,0.04);cursor:pointer;transition:background 0.2s;">';
      html += '<div style="display:flex;align-items:center;gap:8px;">';
      html += '<span style="color:rgba(255,255,255,0.85);font-size:13px;font-weight:600;">' + _escapeHtml(p.name) + '</span>';
      html += '<span style="color:rgba(255,255,255,0.3);font-size:10px;">v' + p.version + '</span>';
      if (p.verified) html += '<span style="color:#4ade80;font-size:10px;background:rgba(74,222,128,0.1);padding:1px 4px;border-radius:2px;">' + SVG_ICONS.check + '</span>';
      if (p.official) html += '<span style="color:#ff9a4a;font-size:10px;background:rgba(255,154,74,0.1);padding:1px 4px;border-radius:2px;">官方</span>';
      html += '</div>';
      html += '<div style="color:rgba(255,255,255,0.5);font-size:11px;margin:4px 0;">' + _escapeHtml(p.desc) + '</div>';
      html += '<div style="display:flex;align-items:center;gap:10px;color:rgba(255,255,255,0.35);font-size:10px;">';
      html += '<span>' + _escapeHtml(p.author) + '</span>';
      html += '<span style="color:#ff9a4a;">' + stars + '</span>';
      html += '<span>' + (p.downloads >= 1000 ? (p.downloads/1000).toFixed(1)+'k' : p.downloads) + ' 下载</span>';
      html += '<span style="margin-left:auto;color:rgba(255,255,255,0.2);">' + p.category + '</span>';
      html += '</div></div>';
    });
  }
  html += '</div>';
  return html;
}

/* ====================================================================== */
/* 4 New Tool Panel Tabs: Docs / Charts / Finance / Notes                */
/* ====================================================================== */

var _chartInstance = null;
var _chartAnimInterval = null;
var _financeSubTab = 'stock';
var _notesSubTab = 'ai';
var _notesList = JSON.parse(localStorage.getItem('lemon_notes') || '[]');
var _financeLedger = [];
var _docCurrentPdf = null;
var _docCurrentPage = 1;
var _docTotalPages = 0;
var _docZoom = 100;
var _workspaceTabs = [];
var _activeWorkspaceTab = 'chat';
var monacoEditor = null;

function _renderDocsPanel() {
  var html = '<div style="padding:12px;">';
  html += '<div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;">';
  html += '<button onclick="_docUploadClick()" style="padding:6px 12px;background:rgba(255,154,74,0.15);color:#ff9a4a;border:1px solid rgba(255,154,74,0.3);border-radius:6px;cursor:pointer;font-size:12px;">上传文档</button>';
  html += '<input type="file" id="docFileInput" accept=".pdf,.doc,.docx,.xls,.xlsx,.md,.txt" style="display:none;" onchange="_docFileSelected(this)">';
  html += '<button onclick="_docPrevPage()" style="padding:4px 10px;background:var(--bg-tertiary,#2a2a3a);color:#e0e0e0;border:none;border-radius:4px;cursor:pointer;font-size:11px;">&#9664;</button>';
  html += '<span id="docPageInfo" style="color:#aaa;font-size:11px;">0/0</span>';
  html += '<button onclick="_docNextPage()" style="padding:4px 10px;background:var(--bg-tertiary,#2a2a3a);color:#e0e0e0;border:none;border-radius:4px;cursor:pointer;font-size:11px;">&#9654;</button>';
  html += '<button onclick="_docZoomOut()" style="padding:4px 8px;background:var(--bg-tertiary,#2a2a3a);color:#e0e0e0;border:none;border-radius:4px;cursor:pointer;font-size:11px;">-</button>';
  html += '<span id="docZoomInfo" style="color:#aaa;font-size:11px;">100%</span>';
  html += '<button onclick="_docZoomIn()" style="padding:4px 8px;background:var(--bg-tertiary,#2a2a3a);color:#e0e0e0;border:none;border-radius:4px;cursor:pointer;font-size:11px;">+</button>';
  html += '</div>';
  html += '<div id="miemieDocViewer" style="overflow:auto;max-height:calc(100vh - 180px);min-height:200px;background:rgba(0,0,0,0.2);border-radius:8px;padding:8px;" ondrop="_docDrop(event)" ondragover="_docDragOver(event)">';
  html += '<div class="doc-drop-zone" style="border:2px dashed rgba(255,255,255,0.15);border-radius:12px;padding:40px;text-align:center;color:rgba(255,255,255,0.3);font-size:13px;">';
  html += '拖拽文件到此处或点击上传<br><span style="font-size:11px;color:rgba(255,255,255,0.2);">支持 PDF / Word / Excel / Markdown / TXT</span>';
  html += '</div></div></div>';
  return html;
}

function _docUploadClick() { var el = document.getElementById('docFileInput'); if (el) el.click(); }
function _docDragOver(e) { e.preventDefault(); e.currentTarget.style.borderColor = '#ff9a4a'; }
function _docDrop(e) {
  e.preventDefault(); e.currentTarget.style.borderColor = '';
  var files = e.dataTransfer.files;
  if (files.length > 0) _docLoadFile(files[0]);
}
function _docFileSelected(input) { if (input.files.length > 0) _docLoadFile(input.files[0]); }
function _docLoadFile(file) {
  var viewer = document.getElementById('miemieDocViewer');
  if (!viewer) return;
  var ext = file.name.split('.').pop().toLowerCase();
  if (ext === 'pdf' && window.pdfjsLib) {
    var reader = new FileReader();
    reader.onload = function() {
      var typedArray = new Uint8Array(reader.result);
      pdfjsLib.getDocument(typedArray).promise.then(function(pdf) {
        _docCurrentPdf = pdf; _docTotalPages = pdf.numPages; _docCurrentPage = 1;
        _docRenderPage(1);
      });
    };
    reader.readAsArrayBuffer(file);
  } else if (ext === 'md' || ext === 'txt') {
    var reader = new FileReader();
    reader.onload = function() {
      var text = reader.result;
      if (ext === 'md' && window.marked) {
        viewer.innerHTML = '<div style="color:#e0e0e0;padding:12px;">' + marked.parse(text) + '</div>';
        _docApplyKatex(viewer);
      } else {
        viewer.innerHTML = '<pre style="color:#e0e0e0;padding:12px;white-space:pre-wrap;font-size:12px;">' + text.replace(/</g,'&lt;') + '</pre>';
      }
      _docTotalPages = 1; _docCurrentPage = 1;
      _docUpdatePageInfo();
    };
    reader.readAsText(file);
  } else if ((ext === 'docx' || ext === 'doc') && window.mammoth) {
    var reader = new FileReader();
    reader.onload = function() {
      mammoth.convertToHtml({arrayBuffer: reader.result}).then(function(result) {
        viewer.innerHTML = '<div style="color:#e0e0e0;padding:12px;">' + result.value + '</div>';
      });
    };
    reader.readAsArrayBuffer(file);
  } else if ((ext === 'xlsx' || ext === 'xls') && window.XLSX) {
    var reader = new FileReader();
    reader.onload = function() {
      var wb = XLSX.read(reader.result, {type: 'array'});
      var sheet = wb.Sheets[wb.SheetNames[0]];
      viewer.innerHTML = '<div style="color:#e0e0e0;padding:12px;overflow:auto;">' + XLSX.utils.sheet_to_html(sheet) + '</div>';
    };
    reader.readAsArrayBuffer(file);
  } else {
    viewer.innerHTML = '<div style="padding:20px;color:#ff9a4a;text-align:center;">不支持的文件格式: ' + ext + '</div>';
  }
}
function _docRenderPage(num) {
  if (!_docCurrentPdf) return;
  _docCurrentPdf.getPage(num).then(function(page) {
    var viewer = document.getElementById('miemieDocViewer');
    var scale = _docZoom / 100;
    var viewport = page.getViewport({scale: scale});
    var canvas = document.createElement('canvas');
    canvas.width = viewport.width; canvas.height = viewport.height;
    canvas.style.maxWidth = '100%'; canvas.style.margin = '8px auto'; canvas.style.display = 'block';
    viewer.innerHTML = '';
    viewer.appendChild(canvas);
    page.render({canvasContext: canvas.getContext('2d'), viewport: viewport});
    _docCurrentPage = num;
    _docUpdatePageInfo();
  });
}
function _docPrevPage() { if (_docCurrentPage > 1) _docRenderPage(_docCurrentPage - 1); }
function _docNextPage() { if (_docCurrentPage < _docTotalPages) _docRenderPage(_docCurrentPage + 1); }
function _docZoomIn() { _docZoom = Math.min(300, _docZoom + 25); if (_docCurrentPdf) _docRenderPage(_docCurrentPage); _docUpdatePageInfo(); }
function _docZoomOut() { _docZoom = Math.max(50, _docZoom - 25); if (_docCurrentPdf) _docRenderPage(_docCurrentPage); _docUpdatePageInfo(); }
function _docUpdatePageInfo() {
  var el = document.getElementById('docPageInfo'); if (el) el.textContent = _docCurrentPage + '/' + _docTotalPages;
  var zl = document.getElementById('docZoomInfo'); if (zl) zl.textContent = _docZoom + '%';
}
function _docApplyKatex(el) {
  if (!window.katex) return;
  var html = el.innerHTML;
  html = html.replace(/\$\$([\s\S]*?)\$\$/g, function(m, tex) { try { return katex.renderToString(tex, {displayMode:true}); } catch(e) { return m; } });
  html = html.replace(/\$([^\$]+?)\$/g, function(m, tex) { try { return katex.renderToString(tex, {displayMode:false}); } catch(e) { return m; } });
  el.innerHTML = html;
}

function _renderChartsPanel() {
  var html = '<div style="padding:12px;">';
  html += '<div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;">';
  var types = [{id:'line',name:'折线'},{id:'bar',name:'柱状'},{id:'pie',name:'饼图'},{id:'scatter',name:'散点'},{id:'radar',name:'雷达'},{id:'area',name:'面积'}];
  types.forEach(function(t) {
    html += '<button onclick="_chartSetType(\'' + t.id + '\')" id="chartTypeBtn_' + t.id + '" style="padding:5px 10px;background:var(--bg-tertiary,#2a2a3a);color:#e0e0e0;border:1px solid rgba(255,255,255,0.1);border-radius:5px;cursor:pointer;font-size:11px;">' + t.name + '</button>';
  });
  html += '<button onclick="addChartDemo(\'stock\')" style="padding:5px 10px;background:rgba(76,175,80,0.15);color:#4caf50;border:1px solid rgba(76,175,80,0.3);border-radius:5px;cursor:pointer;font-size:11px;">股票示例</button>';
  html += '<button onclick="addChartDemo(\'code\')" style="padding:5px 10px;background:rgba(76,175,80,0.15);color:#4caf50;border:1px solid rgba(76,175,80,0.3);border-radius:5px;cursor:pointer;font-size:11px;">代码统计</button>';
  html += '<button onclick="addChartDemo(\'skill\')" style="padding:5px 10px;background:rgba(76,175,80,0.15);color:#4caf50;border:1px solid rgba(76,175,80,0.3);border-radius:5px;cursor:pointer;font-size:11px;">技能分布</button>';
  html += '<label style="display:flex;align-items:center;gap:4px;color:#aaa;font-size:11px;margin-left:auto;"><input type="checkbox" id="chartLiveToggle" onchange="_chartToggleLive()"> 实时数据</label>';
  html += '</div>';
  html += '<div style="display:flex;gap:6px;margin-bottom:10px;">';
  html += '<input id="chartTitle" placeholder="图表标题" style="flex:1;padding:6px 8px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:#e0e0e0;font-size:12px;">';
  html += '<button onclick="_chartExportPng()" style="padding:6px 10px;background:var(--bg-tertiary,#2a2a3a);color:#e0e0e0;border:none;border-radius:4px;cursor:pointer;font-size:11px;">导出PNG</button>';
  html += '</div>';
  html += '<div style="background:rgba(0,0,0,0.2);border-radius:8px;padding:12px;">';
  html += '<canvas id="miemieChartCanvas" width="400" height="300"></canvas>';
  html += '</div></div>';
  return html;
}

var _chartType = 'line';
function _chartSetType(t) {
  _chartType = t;
  document.querySelectorAll('[id^=chartTypeBtn_]').forEach(function(b) { b.style.borderColor = 'rgba(255,255,255,0.1)'; });
  var btn = document.getElementById('chartTypeBtn_' + t); if (btn) btn.style.borderColor = '#ff9a4a';
}
function renderChart(data, chartType, options) {
  if (!window.Chart) return;
  var canvas = document.getElementById('miemieChartCanvas');
  if (!canvas) return;
  if (_chartInstance) _chartInstance.destroy();
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  var type = chartType || _chartType;
  if (type === 'area') type = 'line';
  var opts = options || {};
  var config = {
    type: type,
    data: data,
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#aaa' } }, title: { display: !!opts.title, text: opts.title || '', color: '#e0e0e0' } },
      scales: (type === 'pie' || type === 'radar') ? {} : { x: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.05)' } }, y: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.05)' } } },
    }
  };
  if (chartType === 'area') config.data.datasets.forEach(function(ds) { ds.fill = true; });
  _chartInstance = new Chart(ctx, config);
}
function addChartDemo(type) {
  if (!window.Chart) return;
  if (type === 'stock') {
    var labels = ['9:30','10:00','10:30','11:00','11:30','13:00','13:30','14:00','14:30','15:00'];
    var prices = [3280,3295,3310,3298,3305,3320,3315,3330,3325,3340];
    renderChart({labels: labels, datasets: [{label:'价格',data: prices, borderColor:'#4caf50',backgroundColor:'rgba(76,175,80,0.1)',tension:0.3}]}, 'line', {title:'股票走势示例'});
  } else if (type === 'code') {
    renderChart({labels:['Python','JavaScript','TypeScript','HTML/CSS','SQL','Go'], datasets:[{label:'代码行数',data:[12500,8300,6100,4800,3200,1900],backgroundColor:['#3572A5','#f1e05a','#3178c6','#e34c26','#e38c00','#00ADD8']}]}, 'bar', {title:'代码统计示例'});
  } else if (type === 'skill') {
    renderChart({labels:['代码生成','调试','搜索','文档','重构','测试'], datasets:[{label:'使用次数',data:[45,28,22,15,12,8],backgroundColor:['#ff6384','#36a2eb','#ffce56','#4bc0c0','#9966ff','#ff9f40']}]}, 'pie', {title:'技能分布示例'});
  }
}
function _chartToggleLive() {
  var cb = document.getElementById('chartLiveToggle'); if (!cb) return;
  if (cb.checked) {
    var idx = 0;
    _chartAnimInterval = setInterval(function() {
      if (!window.Chart || !_chartInstance) return;
      var ds = _chartInstance.data.datasets[0];
      ds.data.push(Math.floor(Math.random()*100)+3200);
      _chartInstance.data.labels.push('' + (++idx));
      if (ds.data.length > 30) { ds.data.shift(); _chartInstance.data.labels.shift(); }
      _chartInstance.update('none');
    }, 2000);
  } else {
    clearInterval(_chartAnimInterval); _chartAnimInterval = null;
  }
}
function _chartExportPng() {
  var canvas = document.getElementById('miemieChartCanvas'); if (!canvas) return;
  var a = document.createElement('a'); a.download = 'chart.png'; a.href = canvas.toDataURL(); a.click();
}

function _renderFinancePanel() {
  var html = '<div style="padding:12px;">';
  html += '<div style="display:flex;gap:6px;margin-bottom:12px;">';
  [{id:'stock',name:'股票查询'},{id:'ledger',name:'记账'},{id:'stats',name:'统计'}].forEach(function(t) {
    var active = _financeSubTab === t.id;
    html += '<button onclick="_financeSwitchSub(\'' + t.id + '\')" style="padding:6px 12px;background:' + (active ? 'rgba(255,154,74,0.2)' : 'var(--bg-tertiary,#2a2a3a)') + ';color:' + (active ? '#ff9a4a' : '#aaa') + ';border:1px solid ' + (active ? 'rgba(255,154,74,0.4)' : 'rgba(255,255,255,0.1)') + ';border-radius:6px;cursor:pointer;font-size:12px;">' + t.name + '</button>';
  });
  html += '</div>';
  if (_financeSubTab === 'stock') {
    html += '<div style="margin-bottom:10px;"><input id="finSymbol" placeholder="股票代码（如 600519）" style="padding:6px 8px;width:60%;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:#e0e0e0;font-size:12px;">';
    html += '<select id="finPeriod" style="padding:6px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:#e0e0e0;font-size:12px;"><option value="1m">月</option><option value="3m">季</option><option value="1y">年</option></select>';
    html += '<button onclick="_financeStockQuery()" style="padding:6px 12px;background:rgba(255,154,74,0.2);color:#ff9a4a;border:1px solid rgba(255,154,74,0.3);border-radius:4px;cursor:pointer;font-size:12px;margin-left:6px;">查询</button></div>';
    html += '<div id="finStockResult" style="color:#aaa;font-size:12px;min-height:100px;"></div>';
  } else if (_financeSubTab === 'ledger') {
    html += '<div style="margin-bottom:10px;">';
    html += '<select id="finCat" style="padding:6px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:#e0e0e0;font-size:12px;"><option>餐饮</option><option>交通</option><option>购物</option><option>娱乐</option><option>其他</option></select>';
    html += '<input id="finAmount" placeholder="金额" type="number" style="padding:6px 8px;width:80px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:#e0e0e0;font-size:12px;">';
    html += '<input id="finNote" placeholder="备注" style="padding:6px 8px;width:120px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:#e0e0e0;font-size:12px;">';
    html += '<button onclick="_financeRecordExpense()" style="padding:6px 12px;background:rgba(76,175,80,0.2);color:#4caf50;border:1px solid rgba(76,175,80,0.3);border-radius:4px;cursor:pointer;font-size:12px;margin-left:6px;">记一笔</button></div>';
    html += '<div id="finLedgerList" style="color:#aaa;font-size:12px;max-height:300px;overflow:auto;">' + _financeRenderLedger() + '</div>';
  } else if (_financeSubTab === 'stats') {
    html += '<div id="finStatsArea" style="color:#aaa;font-size:12px;">';
    html += '<div style="text-align:center;padding:30px;color:rgba(255,255,255,0.3);">记账后可查看统计图表</div>';
    html += '</div>';
  }
  html += '</div>';
  return html;
}
function _financeSwitchSub(tab) { _financeSubTab = tab; _refreshCurrentPanel(); }
function _financeStockQuery() {
  var result = document.getElementById('finStockResult'); if (!result) return;
  var sym = document.getElementById('finSymbol'); var symbol = sym ? sym.value : '';
  if (!symbol) { result.innerHTML = '<span style="color:#f44336;">请输入股票代码</span>'; return; }
  result.innerHTML = '<span style="color:#aaa;">查询中...</span>';
  if (typeof window._callPython === 'function') {
    window._callPython('financeAction', JSON.stringify({action:'stock_quote',symbol:symbol,period:'1m'}), function(r) {
      if (r && r.success) { result.innerHTML = '<pre style="color:#e0e0e0;font-size:11px;">' + JSON.stringify(r.data, null, 2).replace(/</g,'&lt;') + '</pre>'; }
      else { result.innerHTML = '<span style="color:#f44336;">' + (r && r.error || '查询失败') + '</span>'; }
    });
  } else { result.innerHTML = '<div style="color:#aaa;">模拟: ' + symbol + ' 当前价格 3280.50 涨幅 +1.2%</div>'; }
}
function _financeRecordExpense() {
  var cat = document.getElementById('finCat'); var amt = document.getElementById('finAmount'); var note = document.getElementById('finNote');
  var entry = {category: cat ? cat.value : '其他', amount: amt ? parseFloat(amt.value) || 0 : 0, note: note ? note.value : '', date: new Date().toISOString().slice(0,10)};
  if (entry.amount <= 0) return;
  _financeLedger.push(entry);
  localStorage.setItem('lemon_finance_ledger', JSON.stringify(_financeLedger));
  if (typeof window._callPython === 'function') {
    window._callPython('financeAction', JSON.stringify({action:'record_expense',category:entry.category,amount:entry.amount,note:entry.note,date:entry.date}));
  }
  _refreshCurrentPanel();
}
function _financeRenderLedger() {
  var stored = localStorage.getItem('lemon_finance_ledger');
  if (stored) { try { _financeLedger = JSON.parse(stored); } catch(e) {} }
  if (!_financeLedger.length) return '<div style="color:rgba(255,255,255,0.3);text-align:center;padding:20px;">暂无记录</div>';
  var html = '<table style="width:100%;border-collapse:collapse;">';
  html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.1);"><th style="text-align:left;padding:4px;color:#888;">分类</th><th style="text-align:right;padding:4px;color:#888;">金额</th><th style="text-align:left;padding:4px;color:#888;">备注</th></tr>';
  _financeLedger.slice(-10).reverse().forEach(function(e) {
    html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:4px;">' + e.category + '</td><td style="padding:4px;text-align:right;color:#f44336;">-' + e.amount.toFixed(2) + '</td><td style="padding:4px;color:#888;">' + (e.note || '') + '</td></tr>';
  });
  html += '</table>';
  return html;
}

function _renderNotesPanel() {
  var html = '<div style="padding:12px;">';
  html += '<div style="display:flex;gap:6px;margin-bottom:12px;">';
  [{id:'ai',name:'AI生成'},{id:'manual',name:'手动记'},{id:'list',name:'历史笔记'}].forEach(function(t) {
    var active = _notesSubTab === t.id;
    html += '<button onclick="_notesSwitchSub(\'' + t.id + '\')" style="padding:6px 12px;background:' + (active ? 'rgba(255,154,74,0.2)' : 'var(--bg-tertiary,#2a2a3a)') + ';color:' + (active ? '#ff9a4a' : '#aaa') + ';border:1px solid ' + (active ? 'rgba(255,154,74,0.4)' : 'rgba(255,255,255,0.1)') + ';border-radius:6px;cursor:pointer;font-size:12px;">' + t.name + '</button>';
  });
  html += '</div>';
  if (_notesSubTab === 'ai') {
    html += '<div style="margin-bottom:10px;"><textarea id="notesAiPrompt" rows="3" placeholder="输入主题，AI 生成笔记..." style="width:100%;padding:8px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:6px;color:#e0e0e0;font-size:12px;resize:vertical;"></textarea></div>';
    html += '<div style="display:flex;gap:6px;margin-bottom:10px;">';
    html += '<select id="notesAiType" style="padding:6px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:4px;color:#e0e0e0;font-size:12px;"><option value="report">报告</option><option value="paper">论文</option><option value="outline">大纲</option><option value="summary">摘要</option></select>';
    html += '<button onclick="_notesAiGenerate()" style="padding:6px 12px;background:rgba(255,154,74,0.2);color:#ff9a4a;border:1px solid rgba(255,154,74,0.3);border-radius:4px;cursor:pointer;font-size:12px;">生成</button></div>';
    html += '<div id="notesAiResult" style="color:#e0e0e0;font-size:12px;min-height:80px;padding:8px;background:rgba(0,0,0,0.15);border-radius:6px;"></div>';
  } else if (_notesSubTab === 'manual') {
    html += '<div style="margin-bottom:10px;"><input id="notesManualTitle" placeholder="标题" style="width:100%;padding:8px;margin-bottom:6px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:6px;color:#e0e0e0;font-size:12px;">';
    html += '<textarea id="notesManualContent" rows="5" placeholder="笔记内容（支持 Markdown + $公式$）..." style="width:100%;padding:8px;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.1);border-radius:6px;color:#e0e0e0;font-size:12px;resize:vertical;"></textarea></div>';
    html += '<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px;">';
    [{label:'x=(-b\u00B1\u221A(b\u00B2-4ac))/(2a)',tex:'x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}'},{label:'a\u00B2+b\u00B2=c\u00B2',tex:'a^2 + b^2 = c^2'},{label:'\u222Bf(x)dx',tex:'\\int f(x)dx'},{label:'lim(x\u2192\u221E)',tex:'\\lim_{x \\to \\infty}'},{label:'\u2211(n=1)',tex:'\\sum_{n=1}^{\\infty}'},{label:'\u33A1',tex:'\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}'}].forEach(function(t) {
      html += '<button onclick="_notesInsertFormula(\'' + t.tex.replace(/'/g,"\\'") + '\')" style="padding:3px 8px;background:var(--bg-tertiary,#2a2a3a);color:#aaa;border:1px solid rgba(255,255,255,0.1);border-radius:4px;cursor:pointer;font-size:10px;">' + t.label + '</button>';
    });
    html += '</div>';
    html += '<div style="display:flex;gap:6px;"><button onclick="_notesSaveManual()" style="padding:6px 12px;background:rgba(76,175,80,0.2);color:#4caf50;border:1px solid rgba(76,175,80,0.3);border-radius:4px;cursor:pointer;font-size:12px;">保存</button>';
    html += '<button onclick="_notesPreviewManual()" style="padding:6px 12px;background:var(--bg-tertiary,#2a2a3a);color:#aaa;border:1px solid rgba(255,255,255,0.1);border-radius:4px;cursor:pointer;font-size:12px;">预览</button></div>';
    html += '<div id="notesManualPreview" style="color:#e0e0e0;font-size:12px;margin-top:10px;padding:8px;background:rgba(0,0,0,0.15);border-radius:6px;display:none;"></div>';
  } else if (_notesSubTab === 'list') {
    html += '<div id="notesListArea">';
    if (_notesList.length === 0) {
      html += '<div style="color:rgba(255,255,255,0.3);text-align:center;padding:30px;">暂无笔记</div>';
    } else {
      _notesList.slice(0, 20).forEach(function(n, i) {
        html += '<div style="background:rgba(0,0,0,0.15);border-radius:6px;padding:10px;margin-bottom:8px;">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;"><span style="color:#ff9a4a;font-size:13px;font-weight:600;">' + (n.title || '无标题') + '</span>';
        html += '<span style="color:rgba(255,255,255,0.3);font-size:10px;">' + (n.date || '') + '</span></div>';
        html += '<div style="color:#aaa;font-size:11px;margin-top:4px;max-height:60px;overflow:hidden;">' + (n.summary || n.content || '').slice(0, 120) + '</div>';
        html += '<div style="margin-top:6px;display:flex;gap:4px;">';
        html += '<button onclick="_notesExpand(' + i + ')" style="padding:2px 8px;background:var(--bg-tertiary,#2a2a3a);color:#aaa;border:none;border-radius:3px;cursor:pointer;font-size:10px;">展开</button>';
        html += '<button onclick="_notesDelete(' + i + ')" style="padding:2px 8px;background:rgba(244,67,54,0.1);color:#f44336;border:none;border-radius:3px;cursor:pointer;font-size:10px;">删除</button>';
        html += '</div></div>';
      });
    }
    html += '</div>';
  }
  html += '</div>';
  return html;
}
function _notesSwitchSub(tab) { _notesSubTab = tab; _refreshCurrentPanel(); }
function _notesInsertFormula(tex) {
  var el = document.getElementById('notesManualContent'); if (!el) return;
  var start = el.selectionStart; var end = el.selectionEnd;
  var text = el.value; el.value = text.slice(0, start) + '$$' + tex + '$$' + text.slice(end);
}
function _notesPreviewManual() {
  var el = document.getElementById('notesManualContent'); if (!el) return;
  var preview = document.getElementById('notesManualPreview'); if (!preview) return;
  var text = el.value;
  if (window.marked) { preview.innerHTML = marked.parse(text); _docApplyKatex(preview); }
  else { preview.innerHTML = '<pre>' + text.replace(/</g,'&lt;') + '</pre>'; }
  preview.style.display = 'block';
}
function _notesSaveManual() {
  var title = document.getElementById('notesManualTitle'); var content = document.getElementById('notesManualContent');
  if (!title || !content) return;
  var entry = {title: title.value, content: content.value, summary: content.value.slice(0,100), date: new Date().toISOString().slice(0,10), type: 'manual'};
  _notesList.unshift(entry);
  localStorage.setItem('lemon_notes', JSON.stringify(_notesList));
  title.value = ''; content.value = '';
  _notesSubTab = 'list'; _refreshCurrentPanel();
}
function _notesAiGenerate() {
  var prompt = document.getElementById('notesAiPrompt'); var type = document.getElementById('notesAiType');
  var result = document.getElementById('notesAiResult');
  if (!prompt || !result) return;
  result.innerHTML = '<span style="color:#aaa;">生成中...</span>';
  if (typeof window._callPython === 'function') {
    window._callPython('executeSkill', 'academic_writer', JSON.stringify({prompt:prompt.value,type:type?type.value:'report'}), function(r) {
      if (r && r.success && r.result) { result.innerHTML = '<div>' + (window.marked ? marked.parse(r.result) : r.result.replace(/</g,'&lt;')) + '</div>'; _docApplyKatex(result); }
      else { result.innerHTML = '<span style="color:#f44336;">生成失败</span>'; }
    });
  } else { result.innerHTML = '<div style="color:#aaa;">AI 生成功能需要在应用内使用</div>'; }
}
function _notesExpand(idx) {
  var n = _notesList[idx]; if (!n) return;
  var area = document.getElementById('notesListArea'); if (!area) return;
  var html = '<div style="color:#ff9a4a;font-size:14px;font-weight:600;margin-bottom:8px;">' + (n.title||'无标题') + '</div>';
  html += '<div style="color:#aaa;font-size:10px;margin-bottom:8px;">' + (n.date||'') + '</div>';
  var content = n.content || n.summary || '';
  if (window.marked) { html += '<div style="color:#e0e0e0;font-size:12px;">' + marked.parse(content) + '</div>'; } else { html += '<pre style="color:#e0e0e0;font-size:12px;white-space:pre-wrap;">' + content.replace(/</g,'&lt;') + '</pre>'; }
  html += '<button onclick="_notesSwitchSub(\'list\')" style="margin-top:10px;padding:6px 12px;background:var(--bg-tertiary,#2a2a3a);color:#aaa;border:none;border-radius:4px;cursor:pointer;font-size:12px;">返回列表</button>';
  area.innerHTML = html;
  _docApplyKatex(area);
}
function _notesDelete(idx) { _notesList.splice(idx,1); localStorage.setItem('lemon_notes', JSON.stringify(_notesList)); _refreshCurrentPanel(); }

function renderMathInElement(element) {
  if (!window.katex || !element) return;
  _docApplyKatex(element);
}

/* Workspace Tab System */
function addWorkspaceTab(title, type, path, contentHtml) {
  var existing = _workspaceTabs.find(function(t) { return t.path === path; });
  if (existing) { switchWorkspaceTab(existing.id); return existing.id; }
  var id = 'ws_' + Date.now();
  _workspaceTabs.push({id:id, title:title, type:type, path:path, contentHtml:contentHtml});
  _renderWorkspaceTabs();
  switchWorkspaceTab(id);
  return id;
}
function switchWorkspaceTab(tabId) {
  _activeWorkspaceTab = tabId;
  if (tabId === 'workspace-chat') { switchWorkspaceView('chat'); _renderWorkspaceTabs(); return; }
  var tab = _workspaceTabs.find(function(t) { return t.id === tabId; });
  if (!tab) return;
  var views = document.querySelectorAll('.workspace-view');
  views.forEach(function(v) { v.classList.remove('active'); v.style.display = 'none'; });
  var container = document.getElementById(tabId);
  if (!container) {
    var viewName = tab.type === 'code' ? 'code' : tab.type === 'doc' ? 'doc' : tab.type === 'image' ? 'image' : 'chat';
    var parent = document.getElementById('workspaceView' + viewName.charAt(0).toUpperCase() + viewName.slice(1));
    if (!parent) { parent = document.getElementById('workspaceViewChat'); }
    container = document.createElement('div');
    container.className = 'workspace-view active';
    container.id = tabId;
    container.style.cssText = 'width:100%;height:100%;overflow:auto;';
    parent.parentNode.appendChild(container);
  }
  container.classList.add('active');
  container.style.display = 'block';
  _renderWorkspaceTabs();
}
function closeWorkspaceTab(tabId) {
  _workspaceTabs = _workspaceTabs.filter(function(t) { return t.id !== tabId; });
  if (_activeWorkspaceTab === tabId) { _activeWorkspaceTab = 'workspace-chat'; }
  switchWorkspaceTab(_activeWorkspaceTab);
  _renderWorkspaceTabs();
}
function switchWorkspaceView(viewName) {
  var views = document.querySelectorAll('.workspace-view');
  views.forEach(function(v) { v.classList.remove('active'); v.style.display = 'none'; });
  var view = document.getElementById('workspaceView' + viewName.charAt(0).toUpperCase() + viewName.slice(1));
  if (view) { view.classList.add('active'); view.style.display = 'block'; }
  var tabs = document.querySelectorAll('.workspace-tab');
  tabs.forEach(function(t) { t.classList.remove('active'); if (t.getAttribute('data-view') === viewName) t.classList.add('active'); });
}
function _renderWorkspaceTabs() {
  var bar = document.getElementById('workspaceTabBar'); if (!bar) return;
  var html = '<button class="workspace-tab' + (_activeWorkspaceTab==='workspace-chat'?' active':'') + '" data-view="chat" onclick="switchWorkspaceView(\'chat\')">' +
    '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>Chat</button>';
  _workspaceTabs.forEach(function(t) {
    var viewName = t.type === 'code' ? 'code' : t.type === 'doc' ? 'doc' : t.type === 'image' ? 'image' : 'chat';
    // ★ v4.8.1 Sanitize tab title: replace icon placeholders and strip SVG_ICONS literal text
    var safeTitle = replaceIconPlaceholders(t.title || '未命名');
    html += '<button class="workspace-tab' + (_activeWorkspaceTab===t.id?' active':'') + '" data-view="' + viewName + '" onclick="switchWorkspaceTab(\'' + t.id + '\')">';
    html += '<span>' + safeTitle + '</span><span class="tab-close" onclick="event.stopPropagation();closeWorkspaceTab(\'' + t.id + '\')">x</span></button>';
  });
  bar.innerHTML = html;
}

function initMonacoEditor(containerId) {
  if (typeof require === 'undefined' || !require.config) return;
  require.config({ paths: { 'vs': 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs' }});
  require(['vs/editor/editor.main'], function() {
    monacoEditor = monaco.editor.create(document.getElementById(containerId), {
      model: null, theme: 'vs-dark', fontSize: 14, fontFamily: 'Consolas, "Courier New", monospace',
      lineNumbers: 'on', minimap: {enabled: true}, scrollBeyondLastLine: false,
      automaticLayout: true, wordWrap: 'on', tabSize: 4,
    });
  });
}

var _langMap = {'.py':'python','.js':'javascript','.ts':'typescript','.html':'html','.css':'css','.json':'json','.md':'markdown','.xml':'xml','.yaml':'yaml','.yml':'yaml','.sql':'sql','.java':'java','.cpp':'cpp','.c':'c','.go':'go','.rs':'rust','.txt':'plaintext','.sh':'shell','.rb':'ruby','.php':'php','.swift':'swift','.kt':'kotlin','.r':'r','.lua':'lua'};
function openFileInEditor(filePath, language, content) {
  var tabId = addWorkspaceTab(filePath.split('/').pop().split('\\').pop(), 'code', filePath, '');
  var container = document.getElementById(tabId);
  if (!container) {
    var view = document.createElement('div'); view.className = 'workspace-view'; view.id = tabId; view.style.cssText = 'width:100%;height:100%;';
    document.querySelector('.workspace-views').appendChild(view);
    container = view;
  }
  if (monacoEditor) {
    var lang = language || _langMap[filePath.substring(filePath.lastIndexOf('.'))] || 'plaintext';
    var model = monaco.editor.createModel(content, lang);
    monacoEditor.setModel(model);
    monacoEditor.container = container;
  }
  switchWorkspaceTab(tabId);
}
function openDocumentViewer(filePath, fileType, base64Content) {
  var tabId = addWorkspaceTab(filePath.split('/').pop().split('\\').pop(), 'doc', filePath, '');
  var container = document.getElementById(tabId);
  if (!container) {
    var view = document.createElement('div'); view.className = 'workspace-view'; view.id = tabId; view.style.cssText = 'width:100%;height:100%;overflow:auto;padding:12px;color:#e0e0e0;font-size:12px;';
    document.querySelector('.workspace-views').appendChild(view);
    container = view;
  }
  container.innerHTML = '<div style="color:#aaa;">文档加载中...</div>';
  switchWorkspaceTab(tabId);
}
function openImageViewer(filePath, base64Content) {
  var tabId = addWorkspaceTab(filePath.split('/').pop().split('\\').pop(), 'image', filePath, '');
  var container = document.getElementById(tabId);
  if (!container) {
    var view = document.createElement('div'); view.className = 'workspace-view'; view.id = tabId; view.style.cssText = 'width:100%;height:100%;overflow:auto;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.3);';
    document.querySelector('.workspace-views').appendChild(view);
    container = view;
  }
  container.innerHTML = '<img src="data:image/png;base64,' + base64Content + '" style="max-width:100%;max-height:100%;object-fit:contain;">';
  switchWorkspaceTab(tabId);
}

var _fileExplorerPath = '';
var _fileExplorerVisible = false;
function toggleFileExplorer() {
  _fileExplorerVisible = !_fileExplorerVisible;
  var el = document.getElementById('fileExplorerSidebar');
  if (el) el.style.display = _fileExplorerVisible ? 'flex' : 'none';
  if (_fileExplorerVisible && !_fileExplorerPath) fileExplorerRefresh();
}
function fileExplorerRefresh() {
  var pathEl = document.getElementById('fileExplorerPath');
  var bodyEl = document.getElementById('fileExplorerBody');
  if (!pathEl || !bodyEl) return;
  var ws = document.getElementById('workspaceName');
  var dirPath = _fileExplorerPath || (ws ? ws.getAttribute('data-path') : '');
  if (!dirPath) { bodyEl.innerHTML = '<div class="file-explorer-empty">No workspace open</div>'; return; }
  _callPython('listDirectory', [dirPath], function(res) {
    if (!res || !res.success) { bodyEl.innerHTML = '<div class="file-explorer-empty">Error loading files</div>'; return; }
    _fileExplorerPath = res.data.path;
    pathEl.textContent = res.data.path;
    var entries = (res.data.entries || []).slice();
    var dirs = [], files = [];
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].is_dir) dirs.push(entries[i]); else files.push(entries[i]);
    }
    dirs.sort(function(a,b){ return a.name.toLowerCase().localeCompare(b.name.toLowerCase()); });
    files.sort(function(a,b){ return a.name.toLowerCase().localeCompare(b.name.toLowerCase()); });
    var sorted = dirs.concat(files);
    var html = '<div class="file-explorer-item" onclick="fileExplorerNavigateUp()" style="color:rgba(255,255,255,0.4);"><span class="fe-icon">..</span>..</div>';
    sorted.forEach(function(e) {
      var icon = e.is_dir ? '\u{1F4C1}' : _fileIcon(e.name);
      var cls = e.is_dir ? 'folder' : '';
      var sizeInfo = '';
      if (!e.is_dir && e.size != null) {
        if (e.size > 1048576) sizeInfo = ' <span style="color:rgba(255,255,255,0.25);font-size:10px;">' + (e.size/1048576).toFixed(1) + 'MB</span>';
        else if (e.size > 1024) sizeInfo = ' <span style="color:rgba(255,255,255,0.25);font-size:10px;">' + (e.size/1024).toFixed(1) + 'KB</span>';
      }
      var action = e.is_dir ? 'fileExplorerNavigate(\'' + e.path.replace(/\\/g, '\\\\') + '\')' : 'fileExplorerOpenFile(\'' + e.path.replace(/\\/g, '\\\\') + '\')';
      html += '<div class="file-explorer-item ' + cls + '" onclick="' + action + '"><span class="fe-icon">' + icon + '</span>' + e.name + sizeInfo + '</div>';
    });
    bodyEl.innerHTML = html;
  });
}
function _fileIcon(name) {
  var ext = name.split('.').pop().toLowerCase();
  var map = {py:'\u{1F40D}',js:'\u{1F4E6}',ts:'\u{1F4E6}',html:'\u{1F310}',css:'\u{1F3A8}',json:'\u{1F4CB}',md:'\u{1F4D3}',txt:'\u{1F4C4}',pdf:'\u{1F4D5}',png:'\u{1F5BC}',jpg:'\u{1F5BC}',svg:'\u{1F5BC}',ppt:'\u{1F4CA}',pptx:'\u{1F4CA}',doc:'\u{1F4DD}',docx:'\u{1F4DD}',xls:'\u{1F4CA}',xlsx:'\u{1F4CA}',csv:'\u{1F4CA}',exe:'\u{2699}',dll:'\u{2699}',zip:'\u{1F4E6}',rar:'\u{1F4E6}',tar:'\u{1F4E6}',gz:'\u{1F4E6}',yml:'\u{1F4CB}',yaml:'\u{1F4CB}',toml:'\u{1F4CB}',ini:'\u{1F4CB}',cfg:'\u{1F4CB}',log:'\u{1F4C4}',sql:'\u{1F4CB}',sh:'\u{2699}',bat:'\u{2699}',ps1:'\u{2699}'};
  return map[ext] || '\u{1F4C4}';
}
function fileExplorerNavigate(path) {
  _fileExplorerPath = path;
  fileExplorerRefresh();
}
function fileExplorerNavigateUp() {
  if (!_fileExplorerPath) return;
  var parts = _fileExplorerPath.replace(/\\/g, '/').split('/');
  parts.pop();
  _fileExplorerPath = parts.join('/') || _fileExplorerPath;
  fileExplorerRefresh();
}
function fileExplorerOpenFile(filePath) {
  var ext = filePath.split('.').pop().toLowerCase();
  var imgExts = ['png','jpg','jpeg','gif','bmp','svg','webp','ico'];
  var docExts = ['pdf','docx','xlsx','csv'];
  var mdExts = ['md','markdown'];
  if (imgExts.indexOf(ext) >= 0) {
    _callPython('getFileContent', [filePath], function(res) {
      if (res && res.success && res.data && res.data.content_base64) {
        openImageViewer(filePath, res.data.content_base64);
      }
    });
  } else if (mdExts.indexOf(ext) >= 0) {
    _callPython('getFileContent', [filePath], function(res) {
      if (res && res.success && res.data) openMarkdownEditor(filePath, res.data.content || '');
    });
  } else if (docExts.indexOf(ext) >= 0) {
    _callPython('documentAction', [{action:'read', path:filePath}], function(res) {
      if (res && res.success) openDocumentViewer(filePath, ext, res.data.content);
    });
  } else {
    _callPython('getFileContent', [filePath], function(res) {
      if (res && res.success && res.data) {
        var lang = _langMap['.' + ext] || 'plaintext';
        openFileInEditor(filePath, lang, res.data.content || '');
      }
    });
  }
}

function openMarkdownEditor(filePath, content) {
  var tabId = addWorkspaceTab(filePath.split('/').pop().split('\\').pop(), 'code', filePath, '');
  var container = document.getElementById(tabId);
  if (!container) {
    var view = document.createElement('div'); view.className = 'workspace-view'; view.id = tabId;
    view.style.cssText = 'width:100%;height:100%;display:flex;flex-direction:column;';
    document.querySelector('.workspace-views').appendChild(view);
    container = view;
  }
  container.innerHTML = '<div style="display:flex;align-items:center;padding:4px 10px;background:rgba(255,255,255,0.03);border-bottom:1px solid rgba(255,255,255,0.06);gap:8px;">' +
    '<span style="font-size:11px;color:rgba(255,255,255,0.5);">Markdown</span>' +
    '<span style="flex:1;"></span>' +
    '<button onclick="mdTogglePane(this)" style="font-size:10px;padding:2px 8px;background:rgba(255,105,0,0.1);border:1px solid rgba(255,105,0,0.2);border-radius:4px;color:#ff9a4a;cursor:pointer;">Split</button>' +
    '<button onclick="mdExportHtml(\'' + tabId + '\')" style="font-size:10px;padding:2px 8px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:4px;color:rgba(255,255,255,0.5);cursor:pointer;">Export HTML</button>' +
    '</div>' +
    '<div id="mdPanels_' + tabId + '" style="flex:1;display:flex;overflow:hidden;">' +
    '<textarea id="mdSource_' + tabId + '" style="flex:1;width:50%;background:#1e1e1e;color:#e0e0e0;border:none;resize:none;padding:12px;font-family:Consolas,monospace;font-size:13px;line-height:1.5;outline:none;" oninput="mdRenderPreview(\'' + tabId + '\')">' + (content || '').replace(/</g, '&lt;') + '</textarea>' +
    '<div id="mdPreview_' + tabId + '" style="flex:1;width:50%;overflow-y:auto;padding:12px;color:#e0e0e0;font-size:13px;line-height:1.6;border-left:1px solid rgba(255,255,255,0.06);"></div>' +
    '</div>';
  mdRenderPreview(tabId);
  switchWorkspaceTab(tabId);
}
function mdRenderPreview(tabId) {
  var src = document.getElementById('mdSource_' + tabId);
  var prev = document.getElementById('mdPreview_' + tabId);
  if (!src || !prev) return;
  if (window.marked) {
    prev.innerHTML = marked.parse(src.value || '');
  } else {
    prev.innerHTML = '<pre style="color:#aaa;">' + (src.value || '').replace(/</g, '&lt;') + '</pre>';
  }
  if (window.katex) {
    try { renderMathInElement(prev, {delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}], throwOnError:false}); } catch(e) {}
  }
}
function mdTogglePane(btn) {
  var container = btn.parentElement.nextElementSibling;
  if (!container) return;
  var src = container.querySelector('textarea');
  var prev = container.querySelector('div[id^="mdPreview_"]');
  if (!src || !prev) return;
  if (src.style.width === '100%') { src.style.width = '50%'; prev.style.display = 'block'; prev.style.width = '50%'; btn.textContent = 'Split'; }
  else if (prev.style.display !== 'none') { src.style.width = '100%'; prev.style.display = 'none'; prev.style.width = '0'; btn.textContent = 'Preview'; }
  else { src.style.width = '0'; src.style.display = 'none'; prev.style.display = 'block'; prev.style.width = '100%'; btn.textContent = 'Source'; }
}
function mdExportHtml(tabId) {
  var prev = document.getElementById('mdPreview_' + tabId);
  if (!prev) return;
  var html = '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Export</title>' +
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">' +
    '<style>body{font-family:system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;color:#333;line-height:1.6;}pre{background:#f5f5f5;padding:12px;border-radius:4px;overflow-x:auto;}code{background:#f0f0f0;padding:2px 4px;border-radius:3px;}</style>' +
    '</head><body>' + prev.innerHTML + '</body></html>';
  var blob = new Blob([html], {type: 'text/html'});
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a'); a.href = url; a.download = 'export.html'; a.click();
  URL.revokeObjectURL(url);
}

function _installMarketPlugin(name) {
  var plugin = _marketPlugins.find(function(p) { return p.name === name; });
  if (!plugin) return;
  // 显示安装状态
  _addThinkingEntry('正在安装插件: ' + name + ' v' + plugin.version, true);
  // 模拟安装（实际由 Python 后端 plugin_repository 处理）
  setTimeout(function() {
    _addThinkingEntry('插件 ' + name + ' v' + plugin.version + ' 安装完成', false);
    _refreshCurrentPanel();
  }, 1500);
  _refreshCurrentPanel();
}

// ============================================================
// ★ Skill 系统 — 25个业务Skill + 调用机制 + 特效
// ============================================================

// Skill 定义（25个业务Skill，含分类、图标、描述、自动调用标记）
var _allSkills = [
  // === 原创（6个） ===
  {id:'math_solver', name:'数学求解', cat:'math', desc:'符号计算与方程求解', auto:true,
   icon:'<path d="M4 14h2v-4h4v-2H4v6z"/><path d="M14 10h2v2h2v-2h2v-2h-2V6h-2v2h-2v2z"/><path d="M18 18H6"/>'},
  {id:'web_researcher', name:'网页研究', cat:'research', desc:'多源网络信息搜索与综合', auto:true,
   icon:'<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>'},
  {id:'info_debater', name:'信息辩论', cat:'debate', desc:'多源信息对比与辩论分析', auto:false,
   icon:'<path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>'},
  {id:'math_plotter', name:'数学绘图', cat:'visual', desc:'函数图像与数据可视化', auto:true,
   icon:'<path d="M3 3v18h18"/><polyline points="3,15 7,9 11,12 15,6 19,10 21,8"/><circle cx="7" cy="9" r="1.5"/>'},
  {id:'office_generator', name:'办公文档', cat:'office', desc:'Word/Excel/PPT 自动生成', auto:true,
   icon:'<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/>'},
  {id:'image_processor', name:'图像处理', cat:'image', desc:'图片编辑/增强/格式转换', auto:true,
   icon:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>'},
  // === 蒸馏自 MiMo Code（6个） ===
  {id:'self_documenter', name:'自文档化', cat:'documentation', desc:'一键生成项目文档结构', auto:true,
   icon:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'},
  {id:'arxiv_researcher', name:'学术搜索', cat:'research', desc:'arXiv 论文检索与摘要', auto:true,
   icon:'<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'},
  {id:'design_blueprint', name:'架构蓝图', cat:'visual', desc:'流程图/架构图自动生成', auto:true,
   icon:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>'},
  {id:'image_analyzer', name:'图像分析', cat:'image', desc:'OCR/人脸/物体识别分析', auto:true,
   icon:'<circle cx="12" cy="12" r="3"/><path d="M12 2v4"/><path d="M12 18v4"/><path d="M4.93 4.93l2.83 2.83"/><path d="M16.24 16.24l2.83 2.83"/><path d="M2 12h4"/><path d="M18 12h4"/>'},
  {id:'modern_python_toolchain', name:'Python工具链', cat:'system', desc:'项目初始化/依赖/部署配置', auto:true,
   icon:'<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>'},
  {id:'super_researcher', name:'超级研究', cat:'research', desc:'多Agent协同深度研究', auto:false,
   icon:'<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/><circle cx="12" cy="12" r="3"/>'},
  // === 原创增强（7个） ===
  {id:'physics_experiment', name:'物理实验', cat:'visual', desc:'交互式物理模拟与可视化', auto:true,
   icon:'<path d="M12 3v2"/><path d="M12 19v2"/><path d="M3 12h2"/><path d="M19 12h2"/><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/>'},
  {id:'academic_writer', name:'学术写作', cat:'documentation', desc:'论文/报告/LaTeX 生成', auto:true,
   icon:'<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>'},
  {id:'skill_creator', name:'Skill创建', cat:'system', desc:'自定义Skill模板生成', auto:false,
   icon:'<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M12 22V12"/>'},
  {id:'frontend_designer', name:'前端设计', cat:'visual', desc:'Tailwind/Shadcn UI组件生成', auto:true,
   icon:'<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>'},
  {id:'deep_researcher', name:'深度研究', cat:'research', desc:'分层递归信息采集与综合', auto:false,
   icon:'<path d="M12 2a7 7 0 0 0-7 7c0 2.5 1.5 4.5 3 6l4 6 4-6c1.5-1.5 3-3.5 3-6a7 7 0 0 0-7-7z"/><circle cx="12" cy="9" r="2"/>'},
  {id:'fact_checker', name:'事实核查', cat:'debate', desc:'多源交叉验证事实准确性', auto:false,
   icon:'<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'},
  {id:'html_to_video', name:'HTML转视频', cat:'video', desc:'HTML动画/页面转视频录制', auto:true,
   icon:'<polygon points="5 3 19 12 5 21 5 3"/><rect x="1" y="1" width="22" height="22" rx="3" fill="none"/>'},
  // === P5 代码工程 + 创新（6个） ===
  {id:'code_reviewer', name:'代码审查', cat:'code', desc:'AST静态分析+样式/Bug/安全', auto:true,
   icon:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><path d="M10 13l-1 1 1 1"/>'},
  {id:'test_generator', name:'测试生成', cat:'code', desc:'AST解析生成pytest/unittest', auto:true,
   icon:'<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/><circle cx="12" cy="12" r="10" fill="none"/>'},
  {id:'security_auditor', name:'安全审计', cat:'code', desc:'25+规则漏洞扫描+依赖检查', auto:true,
   icon:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>'},
  {id:'deploy_helper', name:'部署助手', cat:'system', desc:'Docker/npm/pip/GitHub部署', auto:true,
   icon:'<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="3" x2="9" y2="9"/><line x1="15" y1="3" x2="15" y2="9"/>'},
   {id:'code_psychologist', name:'代码心理', cat:'code', desc:'描述→代码/代码→意图分析', auto:false,
   icon:'<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/><circle cx="12" cy="12" r="3" fill="none"/>'},
  {id:'multi_model_debater', name:'多模型辩论', cat:'debate', desc:'多方辩论+评分投票裁决', auto:false,
   icon:'<rect x="3" y="5" width="18" height="12" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="12" y1="5" x2="12" y2="17"/>'}
];

// 分类定义（★ v4.1.11: 改名 _skillCatDefs，避免与上方对象版 _skillCategories 同名覆盖导致 .forEach 崩溃）
var _skillCatDefs = [
  {id:'all', name:'全部', icon:'<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/>'},
  {id:'code', name:'代码', icon:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>'},
  {id:'research', name:'研究', icon:'<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>'},
  {id:'debate', name:'辩论', icon:'<path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>'},
  {id:'visual', name:'视觉', icon:'<path d="M3 3v18h18"/><polyline points="3,15 7,9 11,12 15,6 19,10 21,8"/>'},
  {id:'system', name:'系统', icon:'<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/>'},
  {id:'image', name:'图像', icon:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>'},
  {id:'documentation', name:'文档', icon:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'},
  {id:'office', name:'办公', icon:'<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/>'},
  {id:'video', name:'视频', icon:'<polygon points="5 3 19 12 5 21 5 3"/>'}
];

var _autoSkillMode = true;  // true=自动调用, false=手动选择
var _activeSkillCat = 'all';
var _skillSearchTerm = '';
var _skillInProgress = null;  // 正在执行的skill
var _skillTimeout = null;     // Skill执行超时计时器

// 渲染Skills列表
function _renderSkillsList() {
  var html = '';

  // 搜索栏 + 自动/手动切换
  html += '<div class="skill-control-bar">';
  html += '<div class="skill-search-box">';
  html += '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
  html += '<input type="text" placeholder="搜索 Skills..." id="skillSearchInput" oninput="_onSkillSearch()" value="' + _escapeHtml(_skillSearchTerm) + '">';
  if (_skillSearchTerm) {
    html += '<button class="skill-search-clear" onclick="_clearSkillSearch()">×</button>';
  }
  html += '</div>';
  html += '<button class="skill-auto-toggle ' + (_autoSkillMode ? 'active' : '') + '" onclick="_toggleAutoSkill()" title="自动调用模式">';
  html += _autoSkillMode ? 'AUTO' : '手动';
  html += '</button>';
  html += '</div>';

  // 分类筛选
  html += '<div class="skill-cat-bar">';
  _skillCatDefs.forEach(function(cat) {
    var active = cat.id === _activeSkillCat ? ' active' : '';
    html += '<button class="skill-cat-btn' + active + '" onclick="_filterSkillCat(\'' + cat.id + '\')" title="' + cat.name + '">';
    html += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">' + cat.icon + '</svg>';
    html += '<span>' + cat.name + '</span>';
    html += '</button>';
  });
  html += '</div>';

  // Skill列表
  html += '<div class="skill-list">';
  var filtered = _allSkills;
  if (_activeSkillCat !== 'all') {
    filtered = filtered.filter(function(s) { return s.cat === _activeSkillCat; });
  }
  if (_skillSearchTerm) {
    var term = _skillSearchTerm.toLowerCase();
    filtered = filtered.filter(function(s) {
      return s.name.toLowerCase().indexOf(term) !== -1 ||
             s.desc.toLowerCase().indexOf(term) !== -1 ||
             s.id.toLowerCase().indexOf(term) !== -1;
    });
  }

  if (filtered.length === 0) {
    html += '<div class="skill-empty">未找到匹配的 Skill</div>';
  } else {
    filtered.forEach(function(skill) {
      var ss = _skillStatuses[skill.id] || {};
      var status = ss.status || 'idle';
      var isRunning = _skillInProgress === skill.id || status === 'running';
      var isCompleted = status === 'completed';
      var isFailed = status === 'failed';
      var duration = ss.endTime && ss.startTime ? ((ss.endTime - ss.startTime) / 1000).toFixed(1) + 's' : '';
      var hasOutput = _skillOutputs[skill.id] && _skillOutputs[skill.id].output;

      var cls = 'skill-card';
      if (isRunning) cls += ' skill-running';
      if (isCompleted) cls += ' completed';
      if (isFailed) cls += ' failed';
      if (skill.auto) cls += ' skill-auto';

      html += '<div class="' + cls + '" onclick="_invokeSkill(\'' + skill.id + '\')" title="' + skill.desc + '">';
      // 图标
      html += '<div class="skill-icon">';
      html += '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">';
      html += skill.icon;
      html += '</svg>';
      if (isRunning) {
        html += '<div class="skill-spinner-simple"></div>';
      }
      html += '</div>';
      // 信息
      html += '<div class="skill-info">';
      html += '<div class="skill-name">' + skill.name;
      if (skill.auto) html += '<span class="skill-auto-badge">AUTO</span>';
      // 状态指示器
      if (isCompleted) html += '<span class="skill-status-dot completed"></span>';
      else if (isFailed) html += '<span class="skill-status-dot failed"></span>';
      else if (isRunning) html += '<span class="skill-status-dot running"></span>';
      html += '</div>';
      html += '<div class="skill-desc">' + replaceIconPlaceholders(skill.desc) + '</div>';
      // 状态文本
      if (isRunning && !duration) {
        html += '<div class="skill-status-text" style="color:#ff9a4a;">执行中...</div>';
      } else if (isCompleted && duration) {
        html += '<div class="skill-status-text" style="color:#4ade80;">已完成 · ' + duration + '</div>';
      } else if (isFailed) {
        html += '<div class="skill-status-text" style="color:#f87171;">执行失败</div>';
      }
      html += '</div>';
      // 调用按钮
      html += '<div class="skill-trigger">';
      if (isRunning) {
        html += '<div class="skill-spinner-simple" style="width:14px;height:14px;"></div>';
      } else {
        html += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
      }
      html += '</div>';
      // 输出预览（已完成且有输出时）
      if (hasOutput) {
        html += '<div class="skill-output-preview show">' + _escapeHtml(_skillOutputs[skill.id].output.substring(0, 150)) + '</div>';
      }
      html += '</div>';
    });
  }
  html += '</div>';

  // 底部统计
  html += '<div class="skill-footer">';
  html += '<span>' + filtered.length + ' / ' + _allSkills.length + ' Skills</span>';
  html += '<span class="skill-mode-hint">' + (_autoSkillMode ? '自动调用模式' : '手动选择模式') + '</span>';
  html += '</div>';

  return html;
}

// Skill 搜索
function _onSkillSearch() {
  var input = document.getElementById('skillSearchInput');
  if (input) {
    _skillSearchTerm = input.value;
    var content = document.getElementById('toolPanelContent');
    if (content) content.innerHTML = _renderSkillsList();
  }
}

function _clearSkillSearch() {
  _skillSearchTerm = '';
  var content = document.getElementById('toolPanelContent');
  if (content) content.innerHTML = _renderSkillsList();
}

// 分类筛选
function _filterSkillCat(catId) {
  _activeSkillCat = catId;
  var content = document.getElementById('toolPanelContent');
  if (content) content.innerHTML = _renderSkillsList();
}

// 自动/手动切换
function _toggleAutoSkill() {
  _autoSkillMode = !_autoSkillMode;
  var content = document.getElementById('toolPanelContent');
  if (content) content.innerHTML = _renderSkillsList();
}

// ★ Skill 调用（核心）
function _invokeSkill(skillId) {
  var skill = _allSkills.find(function(s) { return s.id === skillId; });
  if (!skill) return;

  // 显示调用特效
  _showSkillEffect(skill);

  // 设置运行状态
  _skillInProgress = skillId;
  _skillStatuses[skillId] = { status: 'running', startTime: Date.now(), endTime: null, output: '' };
  var content = document.getElementById('toolPanelContent');
  if (content) content.innerHTML = _renderSkillsList();

  // ★ P7: 通过 __skill__: 前缀发送到 Python 后端
  if (typeof pybridge !== 'undefined' && pybridge.sendMessage) {
    pybridge.sendMessage('__skill__:' + skillId);
  }

  // 在聊天区显示 Skill 调用提示
  appendMsg('ai', '<div class="skill-invoke-indicator">' +
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ff9a4a" stroke-width="1.5" style="vertical-align:middle;margin-right:6px;">' +
    skill.icon +
    '</svg>' +
    '<span style="color:#ff9a4a;font-weight:600;">' + skill.name + '</span>' +
    '<span style="color:rgba(255,255,255,0.5);margin-left:6px;">执行中...</span>' +
    '</div>');

  // 3秒超时后清除运行状态
  if (_skillTimeout) clearTimeout(_skillTimeout);
  _skillTimeout = setTimeout(function() {
    _skillInProgress = null;
    var content = document.getElementById('toolPanelContent');
    if (content && _activeToolPanel === 'skills') {
      content.innerHTML = _renderSkillsList();
    }
  }, 15000);
}

// ★ Skill 调用特效
function _showSkillEffect(skill) {
  // 创建粒子特效
  var overlay = document.createElement('div');
  overlay.className = 'skill-effect-overlay';
  overlay.innerHTML = '<div class="skill-effect-ripple"></div>';
  document.body.appendChild(overlay);

  // 粒子爆发
  for (var i = 0; i < 12; i++) {
    var particle = document.createElement('div');
    particle.className = 'skill-effect-particle';
    var angle = (Math.PI * 2 * i) / 12;
    var distance = 40 + Math.random() * 60;
    particle.style.setProperty('--tx', Math.cos(angle) * distance + 'px');
    particle.style.setProperty('--ty', Math.sin(angle) * distance + 'px');
    particle.style.setProperty('--delay', (i * 0.03) + 's');
    overlay.appendChild(particle);
  }

  // 技能名称提示
  var toast = document.createElement('div');
  toast.className = 'skill-toast';
  toast.textContent = skill.name + ' 已调用';
  document.body.appendChild(toast);

  // 清除
  setTimeout(function() {
    overlay.remove();
    toast.remove();
  }, 1500);
}

// ★ 外部调用接口（其他模块可直接调用skill）
function invokeSkillById(skillId) {
  _invokeSkill(skillId);
}

// ★ 获取所有Skill定义（供外部查询）
function getAllSkills() {
  return _allSkills;
}

// ★ 完成Skill调用（由Python侧通知）
function onSkillComplete(skillId, success, result) {
  _skillInProgress = null;
  if (_skillTimeout) clearTimeout(_skillTimeout);
  // 更新状态
  var now = Date.now();
  _skillStatuses[skillId] = {
    status: success ? 'completed' : 'failed',
    startTime: (_skillStatuses[skillId] && _skillStatuses[skillId].startTime) || now,
    endTime: now,
    output: success ? (typeof result === 'string' ? result.substring(0, 200) : JSON.stringify(result).substring(0, 200)) : ''
  };
  if (success && result) {
    _skillOutputs[skillId] = { output: typeof result === 'string' ? result : JSON.stringify(result), timestamp: new Date().toISOString() };
  }
  var content = document.getElementById('toolPanelContent');
  if (content && _activeToolPanel === 'skills') {
    content.innerHTML = _renderSkillsList();
  }

  // ★ P7: 在聊天区渲染 Skill 结果
  var skill = _allSkills.find(function(s) { return s.id === skillId; });
  var skillName = skill ? skill.name : skillId;
  var skillIcon = skill ? skill.icon : '';

  if (success && result) {
    // 根据结果类型选择渲染方式
    var resultHtml = _renderSkillResult(skillId, skillName, skillIcon, result);
    appendMsg('ai', resultHtml);
  } else if (!success) {
    appendMsg('ai', '<div class="skill-invoke-indicator" style="border-left:2px solid #f44336;">' +
      '<span style="color:#f44336;font-weight:600;">' + skillName + '</span>' +
      '<span style="color:rgba(255,255,255,0.5);margin-left:6px;">执行失败</span>' +
      (result ? '<div style="margin-top:6px;color:#f44336;font-size:12px;">' + _escapeHtml(String(result)) + '</div>' : '') +
      '</div>');
  }
  console.log('[Skill] ' + skillId + ' 完成: ' + (success ? '成功' : '失败'));
}

// ★ P7: Skill结果智能渲染
function _renderSkillResult(skillId, skillName, skillIcon, result) {
  var html = '';

  // ★ 369-2: 剥离嵌套 SkillResult（数据层修复前止血）
  if (typeof result === 'string' && result.indexOf('SkillResult(') === 0) {
    var stripped = stripNestedSkillResult(result);
    var _inner = stripped.text;
    try { var _parsed = JSON.parse(_inner); result = _parsed; } catch(e) { result = _inner; }
  }

  // 结果体
  // 尝试解析结果
  var parsed = result;
  if (typeof result === 'string') {
    try { parsed = JSON.parse(result); } catch(e) {}
  }

  // 确定状态
  var _isSuccess = true;
  if (typeof parsed === 'object' && parsed !== null) {
    _isSuccess = parsed.success !== undefined ? parsed.success : true;
  }
  var _statusColor = _isSuccess ? '#4caf50' : '#f44336';
  var _statusLabel = _isSuccess ? 'completed' : 'failed';
  var _statusIcon = _isSuccess ? (SVG_ICONS.check || '') : (SVG_ICONS['circle-x'] || '');

  // Skill 结果头部
  html += '<div class="skill-result-block">';
  html += '<div class="skill-result-header" onclick="var b=this.nextElementSibling;b.style.display=b.style.display===\'none\'?\'\':\'none\';">';
  html += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ff9a4a" stroke-width="1.5" style="vertical-align:middle;margin-right:6px;">' + skillIcon + '</svg>';
  html += '<span style="color:#ff9a4a;font-weight:600;">' + skillName + '</span>';
  html += '<span style="color:' + _statusColor + ';margin-left:8px;font-size:11px;">' + _statusIcon + ' ' + _statusLabel + '</span>';
  html += '<span style="float:right;color:rgba(255,255,255,0.3);font-size:11px;">点击折叠</span>';
  html += '</div>';

  html += '<div class="skill-result-body">';

  if (typeof parsed === 'object' && parsed !== null) {
    // 结构化结果
    if (parsed.type === 'task-plan') {
      html += _renderTaskPlanResult(parsed);
    } else if (parsed.type === 'file-diff') {
      html += _renderFileDiffResult(parsed);
    } else if (parsed.type === 'code-review') {
      html += _renderCodeReviewResult(parsed);
    } else if (parsed.type === 'function-plot') {
      html += _renderFunctionPlotResult(parsed);
    } else if (parsed.type === 'matrix') {
      html += _renderMatrixResult(parsed);
    } else if (parsed.type === 'deploy') {
      html += _renderDeployResult(parsed);
    } else if (parsed.type === 'cmd-search') {
      html += _renderCmdSearch(parsed);
    } else if (parsed.type === 'cmd-code') {
      html += _renderCmdCode(parsed);
    } else if (parsed.type === 'cmd-file') {
      html += _renderCmdFile(parsed);
    } else if (parsed.type === 'cmd-git') {
      html += _renderCmdGit(parsed);
    } else if (parsed.type === 'cmd-run') {
      html += _renderCmdRun(parsed);
    } else if (parsed.type === 'cmd-pip') {
      html += _renderCmdPip(parsed);
    } else if (parsed.type === 'cmd-shell') {
      html += _renderCmdShell(parsed);
    } else if (parsed.type === 'cmd-web') {
      html += _renderCmdWeb(parsed);
    } else if (parsed.type === 'cmd-diagram') {
      html += _renderCmdDiagram(parsed);
    } else if (parsed.type === 'cmd-translate') {
      html += _renderCmdTranslate(parsed);
    } else if (parsed.type === 'cmd-calc') {
      html += _renderCmdCalc(parsed);
    } else if (parsed.type === 'cmd-weather') {
      html += _renderCmdWeather(parsed);
    } else if (parsed.type === 'cmd-time') {
      html += _renderCmdTime(parsed);
    } else if (parsed.type === 'cmd-error') {
      html += _renderCmdError(parsed);
    } else {
      // ★ 369-1: 通用兜底渲染（升级为结构化卡片）
      html += _renderGenericObject(parsed, skillName);
    }
  } else {
    // 纯文本/Markdown结果 — ★ 369-2: 先剥离嵌套 SkillResult
    var _textResult = String(result);
    if (_textResult.indexOf('SkillResult(') === 0) {
      var _sr = stripNestedSkillResult(_textResult);
      _textResult = _sr.text;
      if (!_sr.success) {
        _statusColor = '#f44336';
        _statusLabel = 'failed';
      }
    }
    html += '<div class="skill-result-text">' + escapeHtml(_textResult) + '</div>';
  }

  html += '</div></div>';
  return html;
}

// 任务规划结果渲染
function _renderTaskPlanResult(data) {
  var html = '<div class="task-plan-card">';
  html += '<div class="task-plan-header">';
  html += '<div class="task-plan-title">' + (data.title || '任务规划') + '</div>';
  var total = (data.tasks || []).length;
  var completed = (data.tasks || []).filter(function(t) { return t.status === 'completed'; }).length;
  var progress = total > 0 ? Math.round(completed / total * 100) : 0;
  html += '<div class="task-plan-progress-text">' + completed + '/' + total + ' 已完成</div>';
  html += '</div>';
  html += '<div class="task-plan-progress-bar"><div class="task-plan-progress-fill" style="width:' + progress + '%"></div></div>';
  html += '<div class="task-plan-list">';
  (data.tasks || []).forEach(function(task) {
    var statusClass = task.status === 'completed' ? 'task-completed' : (task.status === 'in_progress' ? 'task-in-progress' : '');
    html += '<div class="task-plan-item ' + statusClass + '">';
    html += '<span class="task-item-status">' + (task.status === 'completed' ? SVG_ICONS.check : (task.status === 'in_progress' ? '●' : '○')) + '</span>';
    html += '<span class="task-item-content">' + (task.title || task.name || '') + '</span>';
    html += '</div>';
  });
  html += '</div></div>';
  return html;
}

// 代码审查结果渲染
function _renderCodeReviewResult(data) {
  var html = '<div class="skill-result-card">';
  html += '<div style="font-weight:600;color:rgba(255,255,255,0.8);margin-bottom:8px;">代码审查结果</div>';
  if (data.issues && data.issues.length > 0) {
    html += '<div style="color:#ff9a4a;font-size:12px;margin-bottom:6px;">发现 ' + data.issues.length + ' 个问题</div>';
    data.issues.forEach(function(issue) {
      var sevColor = issue.severity === 'high' ? '#f44336' : (issue.severity === 'medium' ? '#ff9800' : '#ffc107');
      html += '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);">';
      html += '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + sevColor + ';margin-right:6px;"></span>';
      html += '<span style="font-size:12px;color:rgba(255,255,255,0.7);">' + (issue.message || issue.description || '') + '</span>';
      if (issue.line) html += '<span style="font-size:10px;color:rgba(255,255,255,0.3);margin-left:8px;">L' + issue.line + '</span>';
      html += '</div>';
    });
  } else {
    html += '<div style="color:#4caf50;font-size:12px;">' + SVG_ICONS.check + ' 未发现问题</div>';
  }
  html += '</div>';
  return html;
}

// 文件变更结果渲染
function _renderFileDiffResult(data) {
  var html = '<div class="file-diff-card">';
  html += '<div class="file-diff-header">';
  html += '<div class="file-diff-title">文件变更</div>';
  var stats = data.stats || {};
  html += '<div class="file-diff-stats">';
  html += '<span class="diff-added">+' + (stats.added || 0) + '</span>';
  html += '<span class="diff-removed">-' + (stats.removed || 0) + '</span>';
  html += '</div></div>';
  html += '<div class="file-diff-list">';
  (data.files || []).forEach(function(file) {
    var statusClass = 'file-' + (file.status || 'modified');
    var statusIcon = file.status === 'added' ? '+' : (file.status === 'deleted' ? '-' : '~');
    html += '<div class="file-diff-item ' + statusClass + '">';
    html += '<span class="file-diff-icon">' + statusIcon + '</span>';
    html += '<span class="file-diff-path">' + (file.path || file.name || '') + '</span>';
    html += '<span class="file-diff-changes">+' + (file.additions || 0) + ' -' + (file.deletions || 0) + '</span>';
    html += '</div>';
  });
  html += '</div></div>';
  return html;
}

// 函数图像结果渲染
function _renderFunctionPlotResult(data) {
  var html = '<div class="skill-result-card">';
  html += '<div style="font-weight:600;color:rgba(255,255,255,0.8);margin-bottom:8px;">' + (data.title || '函数图像') + '</div>';
  html += '<div class="dot-plot-container">';
  html += '<canvas class="plot-canvas" width="400" height="280" data-function="' + _escapeHtml(data.function || '') + '" data-range="' + _escapeHtml(data.range || '-10,10') + '"></canvas>';
  html += '</div>';
  if (data.description) {
    html += '<div style="font-size:11px;color:rgba(255,255,255,0.4);margin-top:8px;">' + data.description + '</div>';
  }
  html += '</div>';
  // 延迟渲染Canvas
  setTimeout(function() {
    var canvases = document.querySelectorAll('.plot-canvas');
    canvases.forEach(function(c) { renderFunctionPlot(c); });
  }, 100);
  return html;
}

// 矩阵结果渲染
function _renderMatrixResult(data) {
  return renderMatrix(data.matrix || [], data.title || '矩阵', data.props || []);
}

// 部署结果渲染
function _renderDeployResult(data) {
  var html = '<div class="skill-result-card">';
  html += '<div style="font-weight:600;color:rgba(255,255,255,0.8);margin-bottom:8px;">部署配置</div>';
  if (data.files) {
    html += '<div class="file-diff-list">';
    Object.keys(data.files).forEach(function(filename) {
      html += '<div class="file-diff-item file-added">';
      html += '<span class="file-diff-icon">+</span>';
      html += '<span class="file-diff-path">' + filename + '</span>';
      html += '</div>';
    });
    html += '</div>';
  }
  if (data.commands) {
    html += '<div style="margin-top:8px;font-size:12px;color:rgba(255,255,255,0.5);">运行命令:</div>';
    data.commands.forEach(function(cmd) {
      html += '<div class="code-block" style="margin:4px 0;padding:6px 10px;background:rgba(0,0,0,0.3);border-radius:4px;font-family:monospace;font-size:11px;color:#a5d6ff;">$ ' + cmd + '</div>';
    });
  }
  html += '</div>';
  return html;
}

// ★ 369-2: 嵌套 SkillResult 前端防御剥离（数据层修复前的止血补丁）
// TODO: 数据层 execute 统一解包后可移除此函数
function stripNestedSkillResult(text) {
  if (typeof text !== 'string') return { text: String(text || ''), success: true, error: '' };
  var result = { text: text, success: true, error: '' };
  var maxIter = 5;
  var current = text;
  for (var i = 0; i < maxIter; i++) {
    var trimmed = current.trim();
    if (trimmed.indexOf('SkillResult(') !== 0) break;
    var innerSuccess = true;
    var innerOutput = '';
    var innerError = '';
    var successMatch = trimmed.match(/success=(True|False)/);
    if (successMatch) innerSuccess = successMatch[1] === 'True';
    var outputMatch = trimmed.match(/output=(['"])(.*?)\1/);
    if (outputMatch) innerOutput = outputMatch[2];
    var errorMatch = trimmed.match(/error=(['"])(.*?)\1/);
    if (errorMatch) innerError = errorMatch[2];
    if (innerOutput) {
      current = innerOutput;
      result.success = innerSuccess;
      result.error = innerError;
    } else {
      break;
    }
  }
  result.text = current;
  return result;
}

// ★ 369-1: 通用兜底渲染升级 — 结构化卡片（替代 JSON 倾倒）
function _categoryIcon(cat) {
  var map = {
    'code': 'square-terminal', 'file': 'file-text', 'search': 'search',
    'web': 'globe', 'system': 'wrench', 'planning': 'layout-template',
    'research': 'search', 'debate': 'message_circle', 'math': 'zap',
    'orchestration': 'rocket', 'office': 'file', 'pc_tool': 'tool',
    'security': 'shield', 'finance': 'chart_bar', 'general': 'tool'
  };
  return SVG_ICONS[map[cat] || 'tool'] || SVG_ICONS.tool || '';
}

function _renderGenericObject(obj, skillName, category) {
  try {
    var name = skillName || obj.name || 'skill';
    var cat = category || obj.category || 'general';
    var icon = _categoryIcon(cat);
    var success = obj.success !== undefined ? obj.success : true;
    var output = obj.output || '';
    var error = obj.error || '';
    var data = obj.data;

    // ★ 369-2: 剥离嵌套 SkillResult
    if (output && typeof output === 'string' && output.indexOf('SkillResult(') === 0) {
      var stripped = stripNestedSkillResult(output);
      output = stripped.text;
      if (!stripped.success) { success = false; error = stripped.error || error; }
    }
    if (error && typeof error === 'string' && error.indexOf('SkillResult(') === 0) {
      var stripped2 = stripNestedSkillResult(error);
      error = stripped2.text;
    }

    var statusColor = success ? '#4caf50' : '#f44336';
    var statusLabel = success ? 'completed' : 'failed';
    var statusIcon = success ? (SVG_ICONS.check || '') : (SVG_ICONS['circle-x'] || '');

    var html = '<div class="skill-result-card" style="background:rgba(20,20,28,0.8);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:10px 12px;margin:6px 0;">';

    // 头部：图标 + 技能名 + 状态徽章
    html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">';
    html += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ff9a4a" stroke-width="1.5" style="flex-shrink:0;">' + icon + '</svg>';
    html += '<span style="color:#ff9a4a;font-weight:600;font-size:12px;">' + escapeHtml(name) + '</span>';
    html += '<span style="color:' + statusColor + ';font-size:10px;margin-left:auto;display:inline-flex;align-items:center;gap:2px;border:1px solid ' + statusColor + '33;border-radius:10px;padding:1px 6px;">' + statusIcon + ' ' + statusLabel + '</span>';
    html += '</div>';

    // 正文：output 文本摘要（前8行/300字符，超出折叠）
    if (output) {
      var outputText = String(output);
      var lines = outputText.split('\n');
      var truncated = lines.length > 8 || outputText.length > 300;
      var displayText = lines.slice(0, 8).join('\n');
      if (displayText.length > 300) displayText = displayText.substring(0, 300);
      html += '<div style="font-size:12px;color:rgba(255,255,255,0.8);white-space:pre-wrap;word-break:break-word;line-height:1.5;">';
      html += escapeHtml(displayText);
      if (truncated) {
        html += '<span style="color:rgba(255,255,255,0.3);"> ...</span>';
        html += '</div>';
        html += '<details style="margin-top:4px;"><summary style="color:rgba(255,255,255,0.4);font-size:10px;cursor:pointer;">展开全文</summary>';
        html += '<div style="font-size:11px;color:rgba(255,255,255,0.7);white-space:pre-wrap;word-break:break-word;margin-top:4px;">' + escapeHtml(outputText) + '</div>';
        html += '</details>';
      } else {
        html += '</div>';
      }
    }

    // error 显示
    if (error) {
      html += '<div style="margin-top:6px;font-size:11px;color:#f44336;background:rgba(244,67,54,0.08);border-radius:4px;padding:4px 8px;">' + escapeHtml(String(error)) + '</div>';
    }

    // 详情：data 字段可折叠
    if (data !== undefined && data !== null) {
      var dataStr = typeof data === 'object' ? JSON.stringify(data, null, 2) : String(data);
      var dataKeys = typeof data === 'object' && data !== null ? Object.keys(data).length : 0;
      var summary = typeof data === 'object' && data !== null ? '展开详情 (' + dataKeys + ' 项)' : '展开详情';
      html += '<details style="margin-top:6px;"><summary style="color:rgba(255,255,255,0.4);font-size:10px;cursor:pointer;">' + summary + '</summary>';
      html += '<div style="font-size:11px;color:rgba(255,255,255,0.5);background:rgba(0,0,0,0.2);border-radius:4px;padding:6px 8px;margin-top:4px;white-space:pre-wrap;word-break:break-word;max-height:200px;overflow-y:auto;">' + escapeHtml(dataStr) + '</div>';
      html += '</details>';
    }

    html += '</div>';
    return html;
  } catch(e) {
    // ★ 降级：任何异常直接渲染原始文本
    var fallback = '<div class="skill-result-card" style="background:rgba(20,20,28,0.8);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:10px 12px;margin:6px 0;">';
    fallback += '<div style="font-size:12px;color:rgba(255,255,255,0.8);white-space:pre-wrap;">' + escapeHtml(typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2)) + '</div>';
    fallback += '<details style="margin-top:4px;"><summary style="color:rgba(255,255,255,0.4);font-size:10px;cursor:pointer;">原始输出</summary>';
    fallback += '<div style="font-size:11px;color:rgba(255,255,255,0.5);white-space:pre-wrap;margin-top:4px;">' + escapeHtml(JSON.stringify(obj, null, 2)) + '</div></details>';
    fallback += '</div>';
    return fallback;
  }
}

var CMD_ICONS = {
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg>',
  code: '<svg viewBox="0 0 24 24"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
  file: '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
  git: '<svg viewBox="0 0 24 24"><circle cx="12" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><line x1="6" y1="9" x2="6" y2="15"/><line x1="18" y1="9" x2="18" y2="15"/><path d="M6 15a6 6 0 0 0 12 0"/></svg>',
  run: '<svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
  pip: '<svg viewBox="0 0 24 24"><rect x="2" y="7" width="20" height="10" rx="2"/><line x1="9" y1="7" x2="9" y2="17"/><line x1="15" y1="7" x2="15" y2="17"/></svg>',
  shell: '<svg viewBox="0 0 24 24"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>',
  web: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><line x1="3" y1="12" x2="21" y2="12"/><path d="M12 3a15 15 0 0 1 4 9 15 15 0 0 1-4 9"/><path d="M12 3a15 15 0 0 0-4 9 15 15 0 0 0 4 9"/></svg>',
  diagram: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="8" y="14" width="7" height="7" rx="1"/><line x1="6.5" y1="10" x2="6.5" y2="14"/><line x1="17.5" y1="10" x2="17.5" y2="14"/><line x1="6.5" y1="14" x2="11.5" y2="14"/><line x1="17.5" y1="14" x2="11.5" y2="14"/></svg>',
  translate: '<svg viewBox="0 0 24 24"><path d="M5 8l6 6"/><path d="M4 14l6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="M22 22l-5-10-5 10"/><path d="M14 18h6"/></svg>',
  calc: '<svg viewBox="0 0 24 24"><rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="6" x2="16" y2="6"/><line x1="8" y1="10" x2="8" y2="10.01"/><line x1="12" y1="10" x2="12" y2="10.01"/><line x1="16" y1="10" x2="16" y2="10.01"/><line x1="8" y1="14" x2="8" y2="14.01"/><line x1="12" y1="14" x2="12" y2="14.01"/><line x1="16" y1="14" x2="16" y2="14.01"/><line x1="8" y1="18" x2="16" y2="18"/></svg>',
  weather: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="M4.93 4.93l1.41 1.41"/><path d="M17.66 17.66l1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="M6.34 17.66l-1.41 1.41"/><path d="M19.07 4.93l-1.41 1.41"/></svg>',
  time: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 16 14"/></svg>',
  error: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
};

function _cmdCardHeader(type, title, badge) {
  var icon = CMD_ICONS[type] || CMD_ICONS.error;
  var html = '<div class="cmd-card-header">';
  html += '<div class="cmd-card-icon">' + icon + '</div>';
  html += '<div class="cmd-card-title">' + _escapeHtml(title) + '</div>';
  if (badge) html += '<div class="cmd-card-badge">' + _escapeHtml(badge) + '</div>';
  html += '</div>';
  return html;
}

function _cmdCardFooter(meta) {
  if (!meta) return '';
  var html = '<div class="cmd-card-footer">';
  if (meta.time) html += '<span class="cmd-meta-item">' + _escapeHtml(String(meta.time)) + '</span>';
  if (meta.source) html += '<span class="cmd-meta-item">' + _escapeHtml(String(meta.source)) + '</span>';
  html += '</div>';
  return html;
}

function _cmdFallback(msg) {
  return '<div class="cmd-card-fallback">' + _escapeHtml(msg) + '</div>';
}

function _renderCmdSearch(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('search', '搜索结果', data.query || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || '外部搜索服务不可用，请稍后重试');
  } else if (data.results && data.results.length > 0) {
    data.results.forEach(function(r) {
      html += '<div style="margin-bottom:10px;">';
      html += '<div style="color:#ff9a4a;font-size:12px;font-weight:600;">' + _escapeHtml(r.title || '') + '</div>';
      html += '<div style="color:rgba(255,255,255,0.5);font-size:10px;margin:2px 0;">' + _escapeHtml(r.url || '') + '</div>';
      if (r.snippet) html += '<div style="font-size:11px;color:rgba(255,255,255,0.6);">' + _escapeHtml(r.snippet) + '</div>';
      html += '</div>';
    });
    if (data.total > data.results.length) {
      html += '<div style="font-size:10px;color:rgba(255,255,255,0.35);">共 ' + data.total + ' 条结果</div>';
    }
  } else {
    html += '<div style="color:rgba(255,255,255,0.4);font-size:12px;">未找到相关结果</div>';
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdCode(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('code', data.title || '代码操作', data.action || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || '代码操作失败');
  } else {
    if (data.code) html += '<pre><code>' + _escapeHtml(data.code) + '</code></pre>';
    if (data.description) html += '<div style="margin-top:6px;font-size:11px;color:rgba(255,255,255,0.5);">' + _escapeHtml(data.description) + '</div>';
    if (data.issues && data.issues.length > 0) {
      data.issues.forEach(function(issue) {
        var c = issue.severity === 'high' ? '#f44336' : (issue.severity === 'medium' ? '#ff9800' : '#ffc107');
        html += '<div style="padding:4px 0;font-size:11px;"><span style="color:' + c + ';">●</span> ' + _escapeHtml(issue.message || '') + '</div>';
      });
    }
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdFile(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('file', data.path || '文件操作', data.action || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || '文件操作失败');
  } else {
    if (data.content) html += '<pre><code>' + _escapeHtml(data.content) + '</code></pre>';
    if (data.size) html += '<div style="font-size:10px;color:rgba(255,255,255,0.35);margin-top:4px;">大小: ' + data.size + '</div>';
    if (data.files) {
      html += '<table class="cmd-table"><tr><th>文件</th><th>大小</th></tr>';
      data.files.forEach(function(f) {
        html += '<tr><td>' + _escapeHtml(f.name || '') + '</td><td>' + (f.size || '') + '</td></tr>';
      });
      html += '</table>';
    }
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdGit(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('git', 'Git', data.subcommand || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || 'Git操作失败，请确认仓库状态');
  } else {
    if (data.output) html += '<pre><code>' + _escapeHtml(data.output) + '</code></pre>';
    if (data.branch) html += '<div style="font-size:10px;color:rgba(255,255,255,0.35);">分支: ' + _escapeHtml(data.branch) + '</div>';
    if (data.stats) {
      html += '<div style="margin-top:6px;">';
      if (data.stats.ahead) html += '<span class="cmd-tag">ahead ' + data.stats.ahead + '</span>';
      if (data.stats.behind) html += '<span class="cmd-tag">behind ' + data.stats.behind + '</span>';
      if (data.stats.modified) html += '<span class="cmd-tag">modified ' + data.stats.modified + '</span>';
      html += '</div>';
    }
    if (data.files) {
      html += '<table class="cmd-table"><tr><th>状态</th><th>文件</th></tr>';
      data.files.forEach(function(f) {
        var sc = f.status === 'added' ? '#4caf50' : (f.status === 'deleted' ? '#f44336' : '#ff9800');
        html += '<tr><td><span style="color:' + sc + ';">' + _escapeHtml(f.status || '') + '</span></td><td>' + _escapeHtml(f.path || '') + '</td></tr>';
      });
      html += '</table>';
    }
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdRun(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('run', '运行', data.command || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || '命令执行失败');
  } else {
    if (data.output) html += '<pre><code>' + _escapeHtml(data.output) + '</code></pre>';
    if (data.exitCode !== undefined) {
      var ec = data.exitCode === 0 ? '#4caf50' : '#f44336';
      html += '<div style="font-size:10px;margin-top:4px;">退出码: <span style="color:' + ec + ';">' + data.exitCode + '</span></div>';
    }
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdPip(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('pip', 'Pip', data.action || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || 'pip操作失败，请确认Python环境');
  } else {
    if (data.output) html += '<pre><code>' + _escapeHtml(data.output) + '</code></pre>';
    if (data.packages) {
      html += '<table class="cmd-table"><tr><th>包</th><th>版本</th></tr>';
      data.packages.forEach(function(p) {
        html += '<tr><td>' + _escapeHtml(p.name || '') + '</td><td>' + _escapeHtml(p.version || '') + '</td></tr>';
      });
      html += '</table>';
    }
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdShell(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('shell', 'Shell', data.shell || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || 'Shell命令执行失败');
  } else {
    if (data.output) html += '<pre><code>' + _escapeHtml(data.output) + '</code></pre>';
    if (data.exitCode !== undefined) {
      var ec2 = data.exitCode === 0 ? '#4caf50' : '#f44336';
      html += '<div style="font-size:10px;margin-top:4px;">退出码: <span style="color:' + ec2 + ';">' + data.exitCode + '</span></div>';
    }
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdWeb(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('web', '网页', data.title || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || '网页加载失败');
  } else {
    if (data.url) html += '<div style="font-size:10px;color:rgba(255,255,255,0.35);margin-bottom:6px;">' + _escapeHtml(data.url) + '</div>';
    if (data.content) html += '<div style="font-size:12px;color:rgba(255,255,255,0.6);">' + _escapeHtml(data.content) + '</div>';
    if (data.preview) html += '<div style="margin-top:8px;padding:8px;border-radius:6px;background:rgba(255,255,255,0.03);max-height:200px;overflow:auto;font-size:11px;">' + data.preview + '</div>';
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdDiagram(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('diagram', data.title || '图表', data.diagramType || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || '图表渲染失败，Mermaid不可用时将显示源码');
    if (data.source) html += '<pre><code>' + _escapeHtml(data.source) + '</code></pre>';
  } else {
    if (data.svg) html += '<div style="text-align:center;padding:8px;">' + data.svg + '</div>';
    if (data.source) html += '<details style="margin-top:6px;"><summary style="font-size:10px;color:rgba(255,255,255,0.35);cursor:pointer;">源码</summary><pre><code>' + _escapeHtml(data.source) + '</code></pre></details>';
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdTranslate(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('translate', '翻译', (data.from || '') + ' → ' + (data.to || ''));
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || '翻译服务不可用');
  } else {
    if (data.original) html += '<div style="font-size:11px;color:rgba(255,255,255,0.4);margin-bottom:4px;">' + _escapeHtml(data.original) + '</div>';
    if (data.translated) html += '<div style="font-size:13px;color:rgba(255,255,255,0.85);">' + _escapeHtml(data.translated) + '</div>';
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdCalc(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('calc', '计算', data.expression || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || '计算失败');
  } else {
    if (data.expression) html += '<div style="font-size:11px;color:rgba(255,255,255,0.4);">' + _escapeHtml(data.expression) + '</div>';
    if (data.result !== undefined) html += '<div style="font-size:16px;color:#ff9a4a;font-weight:600;margin-top:4px;">' + _escapeHtml(String(data.result)) + '</div>';
    if (data.steps) html += '<pre style="margin-top:6px;"><code>' + _escapeHtml(data.steps) + '</code></pre>';
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdWeather(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('weather', '天气', data.location || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
    html += _cmdFallback(data.fallback || '天气服务不可用，请检查网络或稍后重试');
  } else {
    if (data.temperature !== undefined) html += '<div style="font-size:20px;color:#ff9a4a;font-weight:600;">' + data.temperature + (data.unit || '°C') + '</div>';
    if (data.condition) html += '<div style="font-size:12px;color:rgba(255,255,255,0.6);margin-top:2px;">' + _escapeHtml(data.condition) + '</div>';
    if (data.details) {
      html += '<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:8px;">';
      if (data.details.humidity) html += '<span class="cmd-tag">湿度 ' + data.details.humidity + '</span>';
      if (data.details.wind) html += '<span class="cmd-tag">风速 ' + data.details.wind + '</span>';
      if (data.details.feelsLike) html += '<span class="cmd-tag">体感 ' + data.details.feelsLike + '</span>';
      html += '</div>';
    }
    if (data.forecast) {
      html += '<table class="cmd-table" style="margin-top:8px;"><tr><th>日期</th><th>天气</th><th>温度</th></tr>';
      data.forecast.forEach(function(d) {
        html += '<tr><td>' + _escapeHtml(d.day || '') + '</td><td>' + _escapeHtml(d.condition || '') + '</td><td>' + _escapeHtml(d.temp || '') + '</td></tr>';
      });
      html += '</table>';
    }
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdTime(data) {
  var html = '<div class="cmd-card">';
  html += _cmdCardHeader('time', '时间', data.timezone || '');
  html += '<div class="cmd-card-body">';
  if (data.error) {
    html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error) + '</div>';
  } else {
    if (data.time) html += '<div style="font-size:20px;color:#ff9a4a;font-weight:600;">' + _escapeHtml(data.time) + '</div>';
    if (data.date) html += '<div style="font-size:12px;color:rgba(255,255,255,0.6);margin-top:2px;">' + _escapeHtml(data.date) + '</div>';
    if (data.zones) {
      html += '<table class="cmd-table" style="margin-top:8px;"><tr><th>时区</th><th>时间</th></tr>';
      data.zones.forEach(function(z) {
        html += '<tr><td>' + _escapeHtml(z.name || '') + '</td><td>' + _escapeHtml(z.time || '') + '</td></tr>';
      });
      html += '</table>';
    }
  }
  html += '</div>';
  html += _cmdCardFooter(data.meta);
  html += '</div>';
  return html;
}

function _renderCmdError(data) {
  var html = '<div class="cmd-card cmd-card-error">';
  html += _cmdCardHeader('error', data.title || '命令执行错误', '');
  html += '<div class="cmd-card-body">';
  html += '<div style="color:#f44336;font-size:12px;">' + _escapeHtml(data.error || '未知错误') + '</div>';
  if (data.fallback) html += _cmdFallback(data.fallback);
  if (data.suggestion) html += '<div style="margin-top:6px;font-size:11px;color:rgba(255,255,255,0.5);">建议: ' + _escapeHtml(data.suggestion) + '</div>';
  html += '</div>';
  html += '</div>';
  return html;
}

// ★ ===== Plan规划模式（Trae风格任务规划） =====
var _planSteps = [];
var _planModeActive = false;

function togglePlanMode() {
  var panel = document.getElementById('planModePanel');
  var btn = document.getElementById('planModeBtn');
  if (!panel) return;
  _planModeActive = !_planModeActive;
  if (_planModeActive) {
    panel.classList.add('show');
    if (btn) btn.style.background = 'rgba(255,105,0,0.2)';
    if (_planSteps.length === 0) {
      _planSteps = _autoExtractPlanSteps();
    }
    renderPlanSteps();
  } else {
    panel.classList.remove('show');
    if (btn) btn.style.background = '';
  }
}

// 自动从对话内容提取规划步骤
function _autoExtractPlanSteps() {
  var steps = [];
  var messages = document.querySelectorAll('.ai-message, .message-content');
  var lastMsg = messages[messages.length - 1];
  if (!lastMsg) {
    // 提供默认规划模板
    return [
      {title: '需求分析', desc: '深入剖析任务目标与代码库上下文', status: 'pending'},
      {title: '代码调研', desc: '检索相关文件、文档与网络资源', status: 'pending'},
      {title: '方案设计', desc: '拆解任务步骤，动态优化策略', status: 'pending'},
      {title: '实施变更', desc: '按计划实施代码变更', status: 'pending'},
      {title: '交付验收', desc: '完成验证后移交控制权', status: 'pending'}
    ];
  }
  var text = lastMsg.textContent || '';
  // 匹配带序号的步骤
  var matches = text.match(/(?:^|\n)\s*(?:\d+[.、)]\s*)([^\n]{4,80})/g);
  if (matches && matches.length >= 2) {
    matches.forEach(function(m, i) {
      var content = m.replace(/(?:^|\n)\s*(?:\d+[.、)]\s*)/, '').trim();
      steps.push({title: content.slice(0, 40), desc: content, status: 'pending'});
    });
  } else {
    // 默认模板
    steps = [
      {title: '需求分析', desc: '深入剖析任务目标与代码库上下文', status: 'pending'},
      {title: '代码调研', desc: '检索相关文件、文档与网络资源', status: 'pending'},
      {title: '方案设计', desc: '拆解任务步骤，动态优化策略', status: 'pending'},
      {title: '实施变更', desc: '按计划实施代码变更', status: 'pending'},
      {title: '交付验收', desc: '完成验证后移交控制权', status: 'pending'}
    ];
  }
  return steps;
}

function renderPlanSteps() {
  var body = document.getElementById('planModeBody');
  if (!body) return;
  if (_planSteps.length === 0) {
    body.innerHTML = '<div style="padding:20px;text-align:center;color:rgba(255,255,255,0.4);font-size:12px;">暂无规划步骤<br>发送任务后将自动生成</div>';
    return;
  }
  var html = '';
  _planSteps.forEach(function(step, i) {
    var statusClass = step.status === 'completed' ? 'completed' :
                      (step.status === 'in_progress' ? 'in-progress' : 'pending');
    var num = step.status === 'completed' ? SVG_ICONS.check : (i + 1);
    html += '<div class="plan-step ' + statusClass + '">';
    html += '<div class="plan-step-num">' + num + '</div>';
    html += '<div class="plan-step-title">' + _escapeHtml(step.title) + '</div>';
    if (step.desc && step.desc !== step.title) {
      html += '<div class="plan-step-desc">' + _escapeHtml(step.desc) + '</div>';
    }
    html += '</div>';
  });
  body.innerHTML = html;
}

function clearPlanSteps() {
  _planSteps = [];
  renderPlanSteps();
}

function executePlanSteps() {
  // 标记第一个pending为in_progress
  for (var i = 0; i < _planSteps.length; i++) {
    if (_planSteps[i].status === 'pending') {
      _planSteps[i].status = 'in_progress';
      renderPlanSteps();
      return;
    }
  }
}

// 标记当前步骤完成，进入下一步
function advancePlanStep() {
  for (var i = 0; i < _planSteps.length; i++) {
    if (_planSteps[i].status === 'in_progress') {
      _planSteps[i].status = 'completed';
      if (i + 1 < _planSteps.length) {
        _planSteps[i + 1].status = 'in_progress';
      }
      renderPlanSteps();
      return;
    }
  }
}

// ★ ===== Builder构建模式 =====
var _builderModeActive = false;

function toggleBuilderMode() {
  _builderModeActive = !_builderModeActive;
  var btn = document.getElementById('builderModeBtn');
  if (_builderModeActive) {
    if (btn) btn.style.background = 'rgba(255,105,0,0.2)';
    // 在输入区上方显示Builder模式横幅
    _showBuilderBanner();
  } else {
    if (btn) btn.style.background = '';
    _hideBuilderBanner();
  }
}

function _showBuilderBanner() {
  var existing = document.getElementById('builderBanner');
  if (existing) return;
  var inputArea = document.querySelector('.input-container, .input-area, #inputArea');
  if (!inputArea) return;
  var banner = document.createElement('div');
  banner.id = 'builderBanner';
  banner.className = 'builder-mode-banner active';
  banner.innerHTML = '<div class="builder-banner-icon">' +
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M3 21 L21 21 M5 21 L5 8 L12 3 L19 8 L19 21"/></svg>' +
    '</div>' +
    '<div class="builder-banner-text">' +
    '<strong>Builder 构建模式已启用</strong>' +
    '描述你想要的项目，AI将自动生成完整代码结构' +
    '</div>';
  inputArea.parentNode.insertBefore(banner, inputArea);
}

function _hideBuilderBanner() {
  var banner = document.getElementById('builderBanner');
  if (banner) banner.remove();
}

// ★ ===== 多任务并行视图（Multi-Agent协作） =====
function renderMultiAgentGrid(agents) {
  if (!agents || agents.length === 0) {
    agents = [
      {role: 'architect', name: '架构师Agent', status: 'idle', progress: 0},
      {role: 'developer', name: '开发Agent', status: 'idle', progress: 0},
      {role: 'tester', name: '测试Agent', status: 'idle', progress: 0},
      {role: 'devops', name: '运维Agent', status: 'idle', progress: 0}
    ];
  }
  var html = '<div class="multi-agent-grid">';
  agents.forEach(function(a) {
    var statusText = a.status === 'active' ? '运行中' :
                     (a.status === 'completed' ? '已完成' : '待命');
    var statusClass = a.status === 'active' ? 'active' :
                      (a.status === 'completed' ? 'completed' : '');
    var cardClass = a.status === 'active' ? 'active' : '';
    html += '<div class="agent-card ' + a.role + ' ' + cardClass + '">';
    html += '<div class="agent-card-header">';
    var iconText = a.role === 'architect' ? 'A' :
                   (a.role === 'developer' ? 'D' :
                   (a.role === 'tester' ? 'T' : 'O'));
    html += '<div class="agent-card-icon">' + iconText + '</div>';
    html += '<div class="agent-card-name">' + a.name + '</div>';
    html += '<div class="agent-card-status ' + statusClass + '">' + statusText + '</div>';
    html += '</div>';
    html += '<div class="agent-card-progress">';
    html += '<div class="agent-card-progress-fill" style="width:' + (a.progress || 0) + '%"></div>';
    html += '</div>';
    html += '</div>';
  });
  html += '</div>';
  return html;
}

// ★ ===== 快捷键：Ctrl+Shift+P（Plan模式）/ Ctrl+Shift+B（Builder模式） =====
document.addEventListener('keydown', function(e) {
  if (e.ctrlKey && e.shiftKey && e.key === 'P') {
    e.preventDefault();
    togglePlanMode();
  }
  if (e.ctrlKey && e.shiftKey && e.key === 'B') {
    e.preventDefault();
    toggleBuilderMode();
  }
});

// ★ ===== 历史会话功能 =====
var _historySearchTimer = null;
var _currentHistorySessionId = null;

function toggleHistorySidebar() {
  var sidebar = document.getElementById('historySidebar');
  if (sidebar.classList.contains('show')) {
    sidebar.classList.remove('show');
  } else {
    sidebar.classList.add('show');
    loadHistorySessions();
  }
}

function loadHistorySessions() {
  if (typeof window._callPython !== 'function') return;
  var list = document.getElementById('historyList');
  list.innerHTML = '<div class="history-empty">加载中...</div>';

  window._callPython('listDbSessions', function(result) {
    var sessions = [];
    try {
      if (typeof result === 'string') result = JSON.parse(result);
      sessions = result || [];
    } catch(e) {}

    if (!sessions.length) {
      list.innerHTML = '<div class="history-empty">暂无历史会话</div>';
      return;
    }

    list.innerHTML = '';
    for (var i = 0; i < sessions.length; i++) {
      var s = sessions[i];
      var item = document.createElement('div');
      item.className = 'history-item';
      if (s.id === _currentHistorySessionId) item.className += ' active';
      item.onclick = (function(sid, stitle) {
        return function() { loadSessionMessages(sid, stitle); };
      })(s.id, s.title);

      var title = document.createElement('div');
      title.className = 'history-item-title';
      title.textContent = s.title || '未命名会话';

      var delBtn = document.createElement('button');
      delBtn.className = 'history-item-delete';
      delBtn.textContent = '×';
      delBtn.title = '删除';
      delBtn.onclick = (function(sid) {
        return function(e) {
          e.stopPropagation();
          deleteHistorySession(sid);
        };
      })(s.id);

      title.appendChild(delBtn);

      var meta = document.createElement('div');
      meta.className = 'history-item-meta';
      var timeStr = s.updated_at || s.created_at || '';
      timeStr = timeStr.substring(5);  // 去掉年份
      meta.innerHTML = '<span>' + timeStr + '</span><span>' + (s.msg_count || 0) + ' 条消息</span>';

      item.appendChild(title);
      item.appendChild(meta);
      list.appendChild(item);
    }
  });
}

function loadSessionMessages(sessionId, sessionTitle) {
  if (typeof window._callPython !== 'function') return;
  _currentHistorySessionId = sessionId;

  // 高亮选中项
  var items = document.querySelectorAll('.history-item');
  for (var i = 0; i < items.length; i++) {
    items[i].classList.remove('active');
  }
  event.currentTarget.classList.add('active');

  window._callPython('getDbMessages', sessionId, function(result) {
    var messages = [];
    try {
      if (typeof result === 'string') result = JSON.parse(result);
      messages = result || [];
    } catch(e) {}

    // 清空当前消息区
    var outputArea = document.getElementById('outputMessages');
    if (outputArea) outputArea.innerHTML = '';

    // 添加状态提示
    appendMsg('status', '<span style="color:#ff9a4a;">≡ 已加载历史会话: ' + (sessionTitle || '') + ' (' + messages.length + ' 条消息)</span>');

    // 逐条加载消息
    for (var i = 0; i < messages.length; i++) {
      var msg = messages[i];
      if (msg.role === 'user') {
        appendMsg('user', msg.content);
      } else if (msg.role === 'assistant') {
        appendMsg('ai', msg.content);
      } else if (msg.role === 'tool') {
        var meta = msg.metadata || {};
        appendMsg('tool', '<strong>' + (meta.tool || 'tool') + '</strong>\n' + msg.content);
      } else if (msg.role === 'status') {
        appendMsg('status', msg.content);
      }
    }

    // 滚动到底部
    var area = document.getElementById('outputMessages');
    if (area) area.scrollTop = area.scrollHeight;

    // 关闭侧边栏
    document.getElementById('historySidebar').classList.remove('show');
  });
}

function onHistorySearch(keyword) {
  if (_historySearchTimer) clearTimeout(_historySearchTimer);
  _historySearchTimer = setTimeout(function() {
    if (!keyword || keyword.trim().length < 2) {
      loadHistorySessions();
      return;
    }
    searchHistoryMessages(keyword.trim());
  }, 300);
}

function searchHistoryMessages(keyword) {
  if (typeof window._callPython !== 'function') return;
  var list = document.getElementById('historyList');
  list.innerHTML = '<div class="history-empty">搜索中...</div>';

  window._callPython('searchDbMessages', keyword, function(result) {
    var results = [];
    try {
      if (typeof result === 'string') result = JSON.parse(result);
      results = result || [];
    } catch(e) {}

    if (!results.length) {
      list.innerHTML = '<div class="history-empty">未找到匹配消息</div>';
      return;
    }

    list.innerHTML = '';
    for (var i = 0; i < results.length; i++) {
      var r = results[i];
      var item = document.createElement('div');
      item.className = 'history-item';
      item.onclick = (function(sid, stitle) {
        return function() { loadSessionMessages(sid, stitle); };
      })(r.session_id, r.session_title);

      var title = document.createElement('div');
      title.className = 'history-item-title';
      // 显示匹配内容片段
      var snippet = r.content.substring(0, 60);
      if (r.content.length > 60) snippet += '...';
      title.textContent = (r.session_title || '会话') + ': ' + snippet;

      var meta = document.createElement('div');
      meta.className = 'history-item-meta';
      meta.innerHTML = '<span>' + (r.role || '') + '</span><span>' + (r.timestamp || '').substring(5) + '</span>';

      item.appendChild(title);
      item.appendChild(meta);
      list.appendChild(item);
    }
  });
}

function deleteHistorySession(sessionId) {
  if (typeof window._callPython !== 'function') return;
  _showConfirm('删除会话', '确认删除此会话？', function() {
  window._callPython('deleteDbSession', sessionId, function(result) {
    loadHistorySessions();
    appendMsg('status', '<span style="color:#ff9a4a;">已删除会话</span>');
  });
  }); // _showConfirm callback
}

// ★ ===== Ollama 模型状态指示器 =====
var _ollamaCheckInterval = null;

function checkOllamaStatus() {
  if (typeof window._callPython !== 'function') return;
  var dot = document.getElementById('modelDisplayDot');
  if (!dot) return;
  // ★ v4.1.28: 仅当当前引擎是 Ollama 时才接管芯片圆点；其他引擎状态由 updateModelDisplay 维护
  if (typeof _currentModel === 'undefined' || !_currentModel || _currentModel.provider !== 'ollama') return;

  dot.className = 'engine-chip-dot checking';

  window._callPython('getOllamaStatus', function(result) {
    var status = result;
    try {
      if (typeof result === 'string') status = JSON.parse(result);
    } catch(e) {}

    if (!status) {
      dot.className = 'engine-chip-dot offline';
      return;
    }

    if (status.running) {
      dot.className = 'engine-chip-dot online';
    } else if (status.installed) {
      dot.className = 'engine-chip-dot offline';
    } else {
      dot.className = 'engine-chip-dot offline';
    }
  });
}

function toggleOllamaInfo() {
  var popup = document.getElementById('ollamaInfoPopup');
  if (popup.classList.contains('show')) {
    popup.classList.remove('show');
    return;
  }
  popup.classList.add('show');
  loadOllamaInfo();
}

function loadOllamaInfo() {
  var content = document.getElementById('ollamaInfoContent');
  if (!content) return;
  content.innerHTML = '<div style="color:#888;">加载中...</div>';

  if (typeof window._callPython !== 'function') return;

  // 先获取状态
  window._callPython('getOllamaStatus', function(statusResult) {
    var status = statusResult;
    try {
      if (typeof status === 'string') status = JSON.parse(status);
    } catch(e) {}

    var html = '';

    if (status) {
      html += '<div class="model-row"><span class="model-name">安装状态</span><span class="model-size">' +
              (status.installed ? '已安装' : '未安装') + '</span></div>';
      html += '<div class="model-row"><span class="model-name">运行状态</span><span class="model-size">' +
              (status.running ? '运行中' : '未运行') + '</span></div>';
      if (status.version) {
        html += '<div class="model-row"><span class="model-name">版本</span><span class="model-size">' +
                status.version.substring(0, 30) + '</span></div>';
      }
    }

    // 如果运行中，获取模型列表
    if (status && status.running) {
      html += '<h4 style="margin-top:10px;">已安装模型</h4>';
      window._callPython('getOllamaModels', function(modelsResult) {
        var models = modelsResult;
        try {
          if (typeof models === 'string') models = JSON.parse(models);
        } catch(e) {}

        if (!models || !models.length) {
          html += '<div style="color:#888;padding:4px 0;">暂无已安装模型</div>';
        } else {
          for (var i = 0; i < models.length; i++) {
            var m = models[i];
            html += '<div class="model-row"><span class="model-name">' + m.name +
                    '</span><span class="model-size">' + (m.size || '') + '</span></div>';
          }
        }

        // 获取推荐模型
        html += '<h4 style="margin-top:10px;">推荐模型 (代码任务)</h4>';
        window._callPython('recommendOllamaModel', 'coding', function(recResult) {
          var rec = recResult;
          try {
            if (typeof rec === 'string') rec = JSON.parse(rec);
          } catch(e) {}

          if (rec) {
            html += '<div class="model-row"><span class="model-name">' + rec.recommended +
                    '</span><span class="model-size">' + (rec.available ? '已安装' : '未安装') + '</span></div>';
            if (rec.reason) {
              html += '<div style="color:#666;font-size:10px;padding:2px 0;">' + rec.reason + '</div>';
            }
          }

          content.innerHTML = html;
        });
      });
    } else {
      html += '<div style="color:#888;padding:8px 0;font-size:10px;">Ollama 未运行，当前使用 Lemon Code</div>';
      content.innerHTML = html;
    }
  });
}

// 启动时检测 Ollama 状态
setTimeout(function() { checkOllamaStatus(); }, 3000);
// 每 60 秒刷新一次
_ollamaCheckInterval = setInterval(function() { checkOllamaStatus(); }, 60000);

// ★ ===== 心跳检测 =====
var _heartbeatTimer = null;
var _heartbeatFailCount = 0;
var _heartbeatMaxFail = 3;  // 连续3次失败（30秒）判定断连
var _savedScrollTop = 0;
var _savedInputText = "";

function startHeartbeat() {
  if (_heartbeatTimer) clearInterval(_heartbeatTimer);
  _heartbeatTimer = setInterval(function() {
    if (typeof window._callPython !== 'function') return;
    window._callPython('heartbeat', function(result) {
      if (result && result.status === 'ok') {
        // 心跳成功
        if (_heartbeatFailCount > 0) {
          console.log('[Heartbeat] 恢复连接');
          onHeartbeatReconnected();
        }
        _heartbeatFailCount = 0;
      } else {
        _heartbeatFailCount++;
        console.log('[Heartbeat] 失败 ' + _heartbeatFailCount + '/' + _heartbeatMaxFail);
        if (_heartbeatFailCount >= _heartbeatMaxFail) {
          onHeartbeatDisconnected();
        }
      }
    });
  }, 10000);  // 每10秒一次
}

function onHeartbeatDisconnected() {
  var popup = document.getElementById('heartbeatDisconnect');
  if (!popup) return;
  // 保存当前状态
  var area = document.getElementById('outputArea');
  if (area) _savedScrollTop = area.scrollTop;
  var input = document.getElementById('messageInput');
  if (input) _savedInputText = input.value || '';

  popup.classList.add('show');
  document.getElementById('hbDisconnectText').textContent = '连接断开，正在重连...';
}

function onHeartbeatReconnected() {
  var popup = document.getElementById('heartbeatDisconnect');
  if (!popup) return;
  popup.classList.remove('show');

  // 恢复滚动位置
  var area = document.getElementById('outputArea');
  if (area) area.scrollTop = _savedScrollTop;

  // 恢复输入框内容
  var input = document.getElementById('messageInput');
  if (input && _savedInputText) {
    if (!input.value) input.value = _savedInputText;
  }

  // 显示恢复提示
  appendMsg('status', '<span style="color:#4caf50;">' + SVG_ICONS.check + ' 连接已恢复</span>');
}

// 启动心跳（延迟5秒，等页面完全加载）
setTimeout(function() { startHeartbeat(); }, 5000);

// ★ 全局消息计数器，用于虚拟滚动索引（统一使用 window._globalMsgCount）
window._globalMsgCount = 0;
var _streamTargetBlock = null;   // 当前流式目标消息块
var _streamTargetContent = null; // 目标块的 .ai-content 元素
var _streamCursor = null;        // 光标元素
var _streamFlushTimer = null;    // 50ms 批量刷新定时器
var _streamPendingText = "";     // 待刷新的文本缓冲
var _streamRendered = false;     // 标记流式内容是否已渲染完成（防止appendMsg双渲染）
var _streamActive = false;       // ★ 流式输出是否正在进行（修复未定义错误）
var _streamBuffer = "";          // ★ 流式输出缓冲区

// ===================== 统一模型显示框与模型选择 =====================
// ★ v4.7.x+: 模型选择持久化到 localStorage（刷新/重启不丢失）
var _SAVED_MODEL_KEY = 'lemoncode.selectedModel.v1';
function _loadSavedModel() {
  try {
    var raw = localStorage.getItem(_SAVED_MODEL_KEY);
    if (!raw) return null;
    var obj = JSON.parse(raw);
    if (obj && obj.provider && obj.modelId) return obj;
  } catch (e) {
    console.warn('[Model] localStorage 读取失败:', e);
  }
  return null;
}
function _saveModel(provider, modelId, modelName) {
  try {
    localStorage.setItem(_SAVED_MODEL_KEY, JSON.stringify({
      provider: provider, modelId: modelId, modelName: modelName || modelId, ts: Date.now()
    }));
  } catch (e) {
    console.warn('[Model] localStorage 写入失败:', e);
  }
}
var _saved = _loadSavedModel();
var _currentModel = _saved || { provider: 'mimocode', modelId: 'auto', modelName: '自动' };
var _modelConnectionStatus = { mimocode: 'checking', ollama: 'checking', deepseek: 'checking', miemie_v1: 'checking' };
var _engineModels = { mimocode: [], ollama: [], deepseek: [], miemie_v1: [] };
var _isHybridMode = false;

function switchEngine(engineId) {
  _currentModel.provider = engineId;
  var models = _engineModels[engineId] || [];
  if (models.length > 0) {
    _currentModel.modelId = models[0].id;
    _currentModel.modelName = models[0].name;
  } else {
    _currentModel.modelId = engineId === 'mimocode' ? 'auto' : (engineId === 'ollama' ? 'qwen2.5:1.5b' : 'deepseek-v4-flash');
    _currentModel.modelName = _currentModel.modelId;
  }

  setModelConnectionStatus(engineId, 'checking');
  updateModelDisplay();

  if (typeof window._callPython === 'function') {
    window._callPython('switchEngine', engineId, function(result) {
      if (result && result.success) {
        var reachable = result.reachable !== false;
        setModelConnectionStatus(engineId, reachable ? 'online' : 'offline');
        if (!reachable) {
          appendMsg('status', '<span style="color:#ff9800;">&#9888; 引擎 ' + getEngineDisplayName(engineId) + ' 不可用（API Key 未配置或服务未启动）</span>');
        } else {
          window._callPython('setEngineModel', engineId, _currentModel.modelId, function(r2) {
            if (r2 && r2.success) {
              appendMsg('status', '<span style="color:#4caf50;">&#10003; 引擎已切换: ' + getEngineDisplayName(engineId) + ' · ' + (r2.model || _currentModel.modelName) + '</span>');
              window._callPython('getCurrentModel', [], function(r3) {
                if (r3 && r3.success && r3.model) {
                  _currentModel.provider = r3.engine || engineId;
                  _currentModel.modelId = r3.model;
                  _currentModel.modelName = r3.display || r3.model;
                  updateModelDisplay();
                }
              });
            } else {
              appendMsg('status', '<span style="color:#ff9800;">&#9888; 模型设置失败: ' + (r2 && r2.message || '未知错误') + '</span>');
            }
          });
          loadEngineModels(engineId);
        }
      } else {
        setModelConnectionStatus(engineId, 'offline');
        appendMsg('status', '<span style="color:#f44336;">&#10007; 引擎切换失败: ' + getEngineDisplayName(engineId) + ' — ' + (result && result.message || '后端无响应') + '</span>');
      }
    });
  }

  refreshModelPanel();
}

function switchModel(provider, modelId, modelName) {
  _currentModel.provider = provider;
  _currentModel.modelId = modelId;
  _currentModel.modelName = modelName || modelId;

  _saveModel(provider, modelId, _currentModel.modelName);

  if (typeof window._callPython === 'function') {
    window._callPython('switchEngine', provider, function(r1) {
      window._callPython('setEngineModel', provider, modelId, function(r2) {
        if (r2 && r2.success) {
          setModelConnectionStatus(provider, 'online');
          appendMsg('status', '<span style="color:#4caf50;">&#10003; 模型已切换: ' + getEngineDisplayName(provider) + ' · ' + _currentModel.modelName + '</span>');
          window._callPython('getCurrentModel', [], function(r3) {
            if (r3 && r3.success && r3.model) {
              _currentModel.provider = r3.engine || provider;
              _currentModel.modelId = r3.model;
              _currentModel.modelName = r3.display || r3.model;
              updateModelDisplay();
            }
          });
        } else {
          setModelConnectionStatus(provider, 'offline');
          appendMsg('status', '<span style="color:#f44336;">&#10007; 模型切换失败: ' + (r2 && r2.message || '未知错误') + '</span>');
        }
      });
    });
  }

  updateModelDisplay();
  refreshModelPanel();
}

function getEngineDisplayName(engineId) {
  var names = { 'mimocode': 'Lemon Code', 'ollama': 'Ollama 本地', 'deepseek': 'DeepSeek(测试)', 'miemie_v1': 'MIEMIE 咩咩' };
  return names[engineId] || engineId;
}

function loadEngineModels(engineId) {
  if (typeof window._callPython === 'function') {
    window._callPython('getEngineModels', engineId, function(result) {
      if (result && result.success && result.models) {
        _engineModels[engineId] = result.models;
        updateModelPanelOptions(engineId);
      }
    });
  }
}

function updateModelPanelOptions(engineId) {
  var container = document.getElementById(engineId + 'ModelOptions');
  if (!container) return;
  var models = _engineModels[engineId] || [];
  container.innerHTML = '';
  if (models.length === 0) {
    container.innerHTML = '<div class="model-option" style="cursor:default;color:rgba(255,255,255,0.3);">无可用模型</div>';
    return;
  }
  models.forEach(function(m) {
    var div = document.createElement('div');
    div.className = 'model-option' + (_currentModel.provider === engineId && _currentModel.modelId === m.id ? ' active' : '');
    div.onclick = function() { switchModel(engineId, m.id, m.name); };
    var status = _modelConnectionStatus[engineId] || 'checking';
    div.innerHTML = '<span>' + m.name + '</span><span class="model-option-status ' + status + '">●</span>';
    container.appendChild(div);
  });
  if (engineId === 'ollama') {
    var customDiv = document.createElement('div');
    customDiv.className = 'model-option';
    customDiv.style.cssText = 'border:1px dashed rgba(255,255,255,0.2);color:rgba(255,255,255,0.5);';
    customDiv.innerHTML = '<span>+ {ICON:plus-circle} 自定义模型</span>';
    customDiv.onclick = function() {
      _showInput('自定义 Ollama 模型', '输入模型名称（如 qwen2.5:7b, deepseek-r1:8b）', '', function(val) {
        if (val && val.trim()) {
          var name = val.trim();
          _engineModels.ollama = _engineModels.ollama || [];
          var found = false;
          for (var i = 0; i < _engineModels.ollama.length; i++) {
            if (_engineModels.ollama[i].id === name) { found = true; break; }
          }
          if (!found) _engineModels.ollama.push({ id: name, name: name });
          switchModel('ollama', name, name);
        }
      });
    };
    container.appendChild(customDiv);
  }
}

function refreshModelPanel() {
  ['mimocode', 'ollama', 'deepseek', 'miemie_v1'].forEach(function(p) {
    updateModelPanelOptions(p);
  });
  _ceRefreshCustomSections();
  syncSettingsModelDisplay();
}

function updateModelDisplay() {
  var nameEl = document.getElementById('modelDisplayName');
  var dotEl = document.getElementById('modelDisplayDot');
  var modelLabel = document.getElementById('modelLabel');
  var modeSub = document.querySelector('.mode-sub');

  var display = _currentModel.modelName;
  if (nameEl) nameEl.textContent = '模型: ' + display;
  if (modelLabel) modelLabel.textContent = '模型: ' + display;
  if (modeSub) modeSub.textContent = getEngineDisplayName(_currentModel.provider) + ' · ' + display;

  var status = _modelConnectionStatus[_currentModel.provider] || 'checking';
  if (dotEl) {
    dotEl.className = 'engine-chip-dot ' + status;
  }
  var statusEl = document.getElementById('engineStatusText');
  if (statusEl) statusEl.textContent = getEngineDisplayName(_currentModel.provider);
  syncSettingsModelDisplay();
}

function setModelConnectionStatus(provider, status) {
  _modelConnectionStatus[provider] = status;
  updateModelDisplay();
  refreshModelPanel();
}

// ★ Lemon Work: 真实连接测试 —— 顶层定义（不依赖面板开启）
window.testEngineLatency = function () {
  var el = document.getElementById('mpConnResult');
  var el2 = document.getElementById('mpConnResult2');   // ★ v354: 设置弹窗里的结果行
  if (el) el.innerHTML = '⏳ 测试中…（ollama / Lemon Code / DeepSeek 真鉴权）';
  if (el2) el2.innerHTML = '⏳ 测试中…';
  if (typeof window._callPython !== 'function') {
    if (el) el.textContent = '✗ 桥接不可用';
    if (el2) el2.textContent = '✗ 桥接不可用';
    return;
  }
  window._callPython('testEngineLatency', '', function (res) {
    try {
      var parts = [];
      var order = [['ollama', 'Ollama'], ['mimocode', 'Lemon Code'], ['deepseek', 'DeepSeek']];
      for (var i = 0; i < order.length; i++) {
        var k = order[i][0], label = order[i][1];
        var v = res && res[k];
        if (!v) {
          parts.push('<span class="bad">' + label + ' ✗ 无结果</span>');
          _modelConnectionStatus[k] = 'err';
          continue;
        }
        if (v.online) {
          parts.push('<span class="ok">' + label + ' ● ' + v.ms + 'ms</span>');
          _modelConnectionStatus[k] = 'ok';
        } else {
          parts.push('<span class="bad">' + label + ' ✗ 不可达</span>');
          _modelConnectionStatus[k] = 'err';
        }
      }
      var html = parts.join(' &nbsp;·&nbsp; ');
      if (el) el.innerHTML = html;
      if (el2) el2.innerHTML = html;
      renderMsList();   // ★ v354: 刷新设置弹窗分组列表的状态灯
    } catch (e) {
      if (el) el.textContent = '✗ 解析失败';
      if (el2) el2.textContent = '✗ 解析失败';
    }
  });
};

// ══════════════════════════════════════════════════════════════
// ★ v354/v355 CodeBuddy 式模型中心 + Trae 式自定义模型表单 + 本地探测器
//   只显示「探测可达」的本地模型与「验证在线」的自定义模型
// ══════════════════════════════════════════════════════════════
var _msListOpen = true;
var _localProbe = { state: 'idle', models: [], ms: 0, err: '' };   // 本地探测状态机
var _customModels = [];                                             // 已存自定义模型

function _msEsc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;')
    .replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function _msDotCls(provider) {
  var st = _modelConnectionStatus[provider] || 'checking';
  return st === 'ok' ? 'ms-dot ok' : (st === 'err' ? 'ms-dot err' : 'ms-dot checking');
}

function toggleMsList() {
  _msListOpen = !_msListOpen;
  var list = document.getElementById('msList');
  if (list) list.style.display = _msListOpen ? 'block' : 'none';
  var caret = document.querySelector('#msCurrentRow .ms-current-caret');
  if (caret) caret.textContent = _msListOpen ? '▾' : '▸';
}

// ★ v355: 本地模型探测器 —— 真实拉取 Ollama /api/tags，只显示能连上的
function probeLocalModels() {
  _localProbe = { state: 'probing', models: [], ms: 0, err: '' };
  renderMsList();
  if (typeof window._callPython !== 'function') {
    _localProbe = { state: 'offline', models: [], ms: 0, err: '桥接不可用' };
    renderMsList();
    return;
  }
  window._callPython('probeLocalModels', '', function (res) {
    try {
      var d = typeof res === 'string' ? JSON.parse(res) : (res || {});
      if (d.online) {
        _localProbe = { state: 'online', models: d.models || [], ms: d.ms || 0, err: '' };
        _modelConnectionStatus.ollama = 'ok';
        _engineModels.ollama = d.models || [];
      } else {
        _localProbe = { state: 'offline', models: [], ms: d.ms || 0, err: d.err || '服务未响应' };
        _modelConnectionStatus.ollama = 'err';
      }
    } catch (e) {
      _localProbe = { state: 'offline', models: [], ms: 0, err: '解析失败' };
    }
    renderMsList();
  });
}

// ★ v355: 拉取已存自定义模型（recheck=true 时掉线剔除）
function refreshCustomModels(recheck) {
  if (typeof window._callPython !== 'function') return;
  window._callPython('listCustomModels', recheck ? '1' : '', function (res) {
    try {
      var d = typeof res === 'string' ? JSON.parse(res) : (res || {});
      _customModels = d.models || [];
    } catch (e) { _customModels = []; }
    renderMsList();
  });
}

function renderMsList() {
  var list = document.getElementById('msList');
  if (!list) return;
  list.style.display = _msListOpen ? 'block' : 'none';
  var html = '';

  // ── 云端组：DeepSeek（状态来自真实连接测试）──
  var dsStatus = _modelConnectionStatus.deepseek || 'checking';
  var dsModels = _engineModels.deepseek && _engineModels.deepseek.length
    ? _engineModels.deepseek
    : [{ id: 'deepseek-chat', name: 'deepseek-chat' },
       { id: 'deepseek-reasoner', name: 'deepseek-reasoner' }];
  html += '<div class="ms-group-title">☁ 云端模型</div>';
  for (var m = 0; m < dsModels.length; m++) {
    (function (id, name) {
      var sel = (_currentModel.provider === 'deepseek' && _currentModel.modelId === id);
      var d = id === 'deepseek-reasoner' ? '深度推理 · 复杂分析' : '性价比高 · 日常任务与工具调用';
      html += '<div class="ms-item' + (sel ? ' selected' : '') + '"' +
        ' onclick="selectMsModel(\'deepseek\',\'' + _msEsc(id) + '\',\'' + _msEsc(name) + '\')">' +
        '<span class="' + _msDotCls('deepseek') + '"></span>' +
        '<span class="ms-item-main"><span class="ms-item-name">' + _msEsc(name) + '</span>' +
        '<span class="ms-item-desc">' + _msEsc(d) + '</span></span>' +
        (sel ? '<span class="ms-check">✓</span>' : '') + '</div>';
    })(dsModels[m].id, dsModels[m].name);
  }

  // ── 本地组：只显示探测器确认在线的模型 ──
  html += '<div class="ms-group-title">💻 本地模型（Ollama）' +
    '<span class="ms-probe-note">' +
    (_localProbe.state === 'probing' ? '探测中…' :
     (_localProbe.state === 'online' ? '● ' + _localProbe.ms + 'ms · ' + _localProbe.models.length + ' 个在线' :
      (_localProbe.state === 'offline' ? '未发现本地服务' : '未探测'))) +
    '</span></div>';
  if (_localProbe.state === 'probing') {
    html += '<div class="ms-empty">正在探测本地 Ollama 服务…</div>';
  } else if (_localProbe.state === 'offline') {
    html += '<div class="ms-empty">未发现能连接的本地模型（' + _msEsc(_localProbe.err) + '）</div>';
  } else {
    for (var l = 0; l < _localProbe.models.length; l++) {
      (function (id, name, size, params) {
        var sel = (_currentModel.provider === 'ollama' && _currentModel.modelId === id);
        var d = (params ? params + ' · ' : '') + (size || '本地运行 · 数据不出机');
        html += '<div class="ms-item' + (sel ? ' selected' : '') + '"' +
          ' onclick="selectMsModel(\'ollama\',\'' + _msEsc(id) + '\',\'' + _msEsc(name) + '\')">' +
          '<span class="ms-dot ok"></span>' +
          '<span class="ms-item-main"><span class="ms-item-name">' + _msEsc(name) + '</span>' +
          '<span class="ms-item-desc">' + _msEsc(d) + '</span></span>' +
          (sel ? '<span class="ms-check">✓</span>' : '') + '</div>';
      })(_localProbe.models[l].id, _localProbe.models[l].name,
         _localProbe.models[l].size, _localProbe.models[l].params);
    }
  }

  // ── 自定义组：只显示保存时验证在线的模型（可删除）──
  html += '<div class="ms-group-title">⚡ 自定义模型' +
    '<span class="ms-probe-note">' + (_customModels.length ? _customModels.length + ' 个在线' : '无') + '</span></div>';
  for (var c = 0; c < _customModels.length; c++) {
    (function (cm) {
      var sel = (_currentModel.provider === 'custom' && _currentModel.modelId === cm.id);
      var d = (cm.base_url || '').replace(/^https?:\/\//, '').slice(0, 40) +
        (cm.ms ? ' · ' + cm.ms + 'ms' : '');
      html += '<div class="ms-item' + (sel ? ' selected' : '') + '"' +
        ' onclick="selectCustomModel(\'' + _msEsc(cm.id) + '\')">' +
        '<span class="ms-dot ok"></span>' +
        '<span class="ms-item-main"><span class="ms-item-name">' + _msEsc(cm.name) + '</span>' +
        '<span class="ms-item-desc">' + _msEsc(d) + '</span></span>' +
        '<span class="ms-del" title="删除此模型" onclick="event.stopPropagation();removeCustomModelById(\'' + _msEsc(cm.id) + '\')">✕</span>' +
        (sel ? '<span class="ms-check">✓</span>' : '') + '</div>';
    })(_customModels[c]);
  }

  // ── 添加自定义模型入口 ──
  html += '<div class="ms-add" onclick="openCmForm()">＋ 添加自定义模型</div>';

  list.innerHTML = html;
}

function selectMsModel(provider, modelId, modelName) {
  switchModel(provider, modelId, modelName);
  renderMsList();
  syncSettingsModelDisplay();
}

// ★ v355: 选中自定义模型 —— 真实生效：发送时用它自己的 BASE URL/KEY/模型名
function selectCustomModel(cmId) {
  var cm = null;
  for (var i = 0; i < _customModels.length; i++) {
    if (_customModels[i].id === cmId) { cm = _customModels[i]; break; }
  }
  if (!cm) return;
  _currentModel = { provider: 'custom', modelId: cm.id, modelName: cm.name, custom: cm };
  try { localStorage.setItem('lw_current_model', JSON.stringify(
    { provider: 'custom', modelId: cm.id, modelName: cm.name, custom: cm })); } catch (e) {}
  if (typeof window._callPython === 'function') {
    window._callPython('setActiveCustom', cm.id, function () {});
  }
  renderMsList();
  syncSettingsModelDisplay();
}

function removeCustomModelById(cmId) {
  if (typeof window._callPython !== 'function') return;
  window._callPython('removeCustomModel', cmId, function () {
    if (_currentModel.provider === 'custom' && _currentModel.modelId === cmId) {
      _currentModel = { provider: 'deepseek', modelId: 'deepseek-chat', modelName: 'deepseek-chat' };
    }
    refreshCustomModels(false);
    syncSettingsModelDisplay();
  });
}

// ── 自定义模型表单（Trae 式）──
function openCmForm() {
  var mask = document.getElementById('cmFormMask');
  if (!mask) return;
  var err = document.getElementById('cmErr');
  if (err) { err.style.display = 'none'; }
  mask.style.display = 'flex';
}
function closeCmForm() {
  var mask = document.getElementById('cmFormMask');
  if (mask) mask.style.display = 'none';
}
function toggleCmKeyVis() {
  var inp = document.getElementById('cmApiKey');
  if (inp) inp.type = (inp.type === 'password') ? 'text' : 'password';
}
// 长度快捷档 chips
(function () {
  function bindChips(boxId, inputId) {
    var box = document.getElementById(boxId);
    if (!box) return;
    box.addEventListener('click', function (e) {
      var chip = e.target;
      if (!chip.classList || !chip.classList.contains('cm-chip')) return;
      var chips = box.querySelectorAll('.cm-chip');
      for (var i = 0; i < chips.length; i++) chips[i].removeAttribute('data-on');
      chip.setAttribute('data-on', '1');
      var inp = document.getElementById(inputId);
      if (inp) inp.value = chip.getAttribute('data-v');
    });
  }
  bindChips('cmCtxChips', 'cmCtxIn');
  bindChips('cmOutChips', 'cmCtxOut');
})();

function saveCmForm() {
  var errEl = document.getElementById('cmErr');
  var showErr = function (msg) {
    if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; }
  };
  var g = function (id) { var el = document.getElementById(id); return el ? el.value.trim() : ''; };
  var payload = {
    name: g('cmName'), base_url: g('cmBaseUrl'), api_key: g('cmApiKey'),
    tools: document.getElementById('cmTools').checked,
    vision: document.getElementById('cmVision').checked,
    reasoning: document.getElementById('cmReasoning').checked,
    ctx_in: parseInt(g('cmCtxIn') || '0', 10) || 32768,
    ctx_out: parseInt(g('cmCtxOut') || '0', 10) || 8192,
  };
  if (!payload.name) { showErr('模型名称不能为空'); return; }
  if (!payload.base_url) { showErr('BASE URL 不能为空'); return; }
  var btn = document.getElementById('cmSaveBtn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 正在探测连接…'; }
  if (typeof window._callPython !== 'function') {
    showErr('桥接不可用，无法测试连接');
    if (btn) { btn.disabled = false; btn.textContent = '保存并测试连接'; }
    return;
  }
  window._callPython('addCustomModel', JSON.stringify(payload), function (res) {
    if (btn) { btn.disabled = false; btn.textContent = '保存并测试连接'; }
    try {
      var d = typeof res === 'string' ? JSON.parse(res) : (res || {});
      if (!d.ok) {
        showErr(d.err || '连接失败（只有能连上的模型才会入列表）');
        return;
      }
      closeCmForm();
      refreshCustomModels(false);
      appendMsg('status', '<span style="color:#57d98a;">✓ 自定义模型「' +
        _msEsc(payload.name) + '」已验证在线（' + (d.model && d.model.ms ? d.model.ms + 'ms' : '') + '）</span>');
    } catch (e) {
      showErr('解析失败');
    }
  });
}

function toggleModelPanel() {
  var panel = document.getElementById('modelSelectPanel');
  if (!panel) { console.warn('[ModelPanel] modelSelectPanel not found'); return; }
  var isHidden = panel.style.display === 'none';
  if (isHidden) {
    // ★ v4.8.1: 把面板移到 engine-chip 内部，使定位锚定在点击的引擎芯片位置
    var chip = document.getElementById('engineChip');
    if (chip && panel.parentNode !== chip) {
      // 保存原始位置备用
      panel._originalParent = panel.parentNode;
      chip.appendChild(panel);
      // ★ 阻止面板内的点击冒泡到 engine-chip 触发 toggle
      if (!panel._chipStopPropagationBound) {
        panel.addEventListener('click', function(e) { e.stopPropagation(); });
        panel._chipStopPropagationBound = true;
      }
    }
    panel.style.display = 'block';
    ['mimocode', 'ollama', 'deepseek', 'miemie_v1'].forEach(function(p) { loadEngineModels(p); });
    _ceLoadCustomEngineModels();
    refreshModelPanel();
  } else {
    panel.style.display = 'none';
    // ★ v4.8.1: 关闭时恢复原位置，避免干扰引擎芯片点击
    if (panel._originalParent && panel._originalParent !== document.body) {
      try { panel._originalParent.appendChild(panel); } catch(e) {}
    }
  }
  console.log('[ModelPanel] toggle:', isHidden ? 'open' : 'close');
}

// ★ v4.2.4 / 补记19: 咩咩引擎选项暂时禁用（等待 logo 重画）
function renderMiemieOption() {
  // var box = document.getElementById('miemieModelOptions');
  // if (!box || box.dataset.rendered === '1') return;
  // box.dataset.rendered = '1';
  // ... 原渲染逻辑 ...
}

// ★ v4.2.4 / 补记19: 选中咩咩引擎暂时只关闭面板，不打开工作区
function selectMiemieEngine() {
  var panel = document.getElementById('modelSelectPanel');
  if (panel) panel.style.display = 'none';
  console.log('[MIEMIE] 引擎选项已暂时隐藏，等待 logo 重画完成后恢复');
}

function onEngineModelsUpdated(modelsJson) {
  try {
    var models = typeof modelsJson === 'string' ? JSON.parse(modelsJson) : modelsJson;
    for (var key in models) {
      _engineModels[key] = models[key];
    }
    refreshModelPanel();
  } catch(e) {
    console.log('[Engine] 模型更新解析错误:', e);
  }
}

function onEngineSwitched(engineId) {
  switchEngine(engineId);
}

function updateEngineDisplay(engineId) {
  // Kept for backward compatibility; now delegates to unified display
  switchEngine(engineId);
}

function onEngineModelChange() {
  // Old dropdown removed; no-op
}

function toggleHybridMode() {
  _isHybridMode = !_isHybridMode;
  if (typeof window._callPython === 'function') {
    window._callPython('setHybridMode', _isHybridMode ? 1 : 0, function(result) {
      console.log('[Engine] 混合模式结果:', result);
    });
  }
  appendMsg('status', '<span style="color:#ff9a4a;">' + SVG_ICONS['file-symlink'] + ' 混合模式: ' + (_isHybridMode ? '已启用' : '已禁用') + '</span>');
}

function syncSettingsModelDisplay() {
  var dot = document.getElementById('settingsModelDot');
  var nameEl = document.getElementById('settingsModelName');

  var status = _modelConnectionStatus[_currentModel.provider] || 'checking';
  if (dot) dot.className = 'model-display-dot ' + status;
  if (nameEl) nameEl.textContent = '模型: ' + _currentModel.modelName;
  // ★ v354: 旧 provider/model 双下拉已删（CodeBuddy 式分组列表替代）
  renderMsList();
}

function onSettingsProviderChange(provider) {
  var modelSelect = document.getElementById('settings-model-select');
  if (!modelSelect) return;
  var models = _engineModels[provider] || [];
  modelSelect.innerHTML = '';
  if (models.length === 0) {
    var opt = document.createElement('option');
    opt.value = provider === 'mimocode' ? 'auto' : (provider === 'ollama' ? 'qwen2.5:1.5b' : 'deepseek-chat');
    opt.textContent = opt.value;
    modelSelect.appendChild(opt);
  } else {
    models.forEach(function(m) {
      var opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = m.name;
      modelSelect.appendChild(opt);
    });
  }
}

function onSettingsModelChange(modelId) {
  var providerSelect = document.getElementById('settings-provider-select');
  var provider = providerSelect ? providerSelect.value : _currentModel.provider;
  var modelSelect = document.getElementById('settings-model-select');
  var modelName = modelSelect ? modelSelect.options[modelSelect.selectedIndex].text : modelId;
  switchModel(provider, modelId, modelName);
}

function onSetModelChange(value) {
  if (value === 'mimo') value = 'mimocode';
  if (['mimocode', 'ollama', 'deepseek'].indexOf(value) !== -1) {
    switchEngine(value);
  }
}

function onSetOllamaModelChange(modelId) {
  if (modelId === 'custom') {
    var sel = document.getElementById('set-ollama-model');
    _showInput('自定义模型', '输入 Ollama 模型名称（如 qwen2.5:7b）', '', function(val) {
      if (val && val.trim()) {
        var name = val.trim();
        if (sel) {
          var exists = false;
          for (var i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === name) { exists = true; break; }
          }
          if (!exists) {
            var opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            sel.insertBefore(opt, sel.querySelector('option[value="custom"]'));
          }
          sel.value = name;
        }
        switchModel('ollama', name, name);
      } else {
        if (sel) sel.value = _currentModel.modelId || 'qwen2.5:1.5b';
      }
    });
    return;
  }
  switchModel('ollama', modelId, modelId);
}

// 点击模型面板外部关闭
document.addEventListener('click', function(e) {
  var box = document.getElementById('engineChip');
  var panel = document.getElementById('modelSelectPanel');
  if (box && panel && !box.contains(e.target) && !panel.contains(e.target)) {
    panel.style.display = 'none';
  }
});

// ===================== ★ Custom Engine Wizard =====================
var _ceWizardStep = 1;
var _ceProviderId = '';
var _ceProviders = {};
var _ceTestPassed = false;

function openCustomEngineWizard() {
  _ceWizardStep = 1;
  _ceProviderId = '';
  _ceTestPassed = false;
  var overlay = document.getElementById('customEngineOverlay');
  overlay.classList.add('show');
  _ceRenderStep();
  _ceLoadProviders();
}

function closeCustomEngineWizard() {
  document.getElementById('customEngineOverlay').classList.remove('show');
}

function _ceLoadProviders() {
  if (typeof window._callPython === 'function') {
    window._callPython('getCustomProviders', function(result) {
      if (result && result.success && result.providers) {
        _ceProviders = result.providers;
        _ceRenderProviders();
      }
    });
  } else {
    _ceProviders = {
      deepseek: {name:'DeepSeek', api_base:'https://api.deepseek.com/v1', models:['deepseek-chat','deepseek-coder'], default_model:'deepseek-chat'},
      moonshot: {name:'Moonshot / Kimi', api_base:'https://api.moonshot.cn/v1', models:['moonshot-v1-8k','moonshot-v1-32k'], default_model:'moonshot-v1-8k'},
      zhipu: {name:'Zhipu / ChatGLM', api_base:'https://open.bigmodel.cn/api/paas/v4', models:['glm-4','glm-4-flash'], default_model:'glm-4-flash'},
      qwen: {name:'Qwen / DashScope', api_base:'https://dashscope.aliyuncs.com/compatible-mode/v1', models:['qwen-turbo','qwen-plus','qwen-max'], default_model:'qwen-plus'},
      siliconflow: {name:'SiliconFlow', api_base:'https://api.siliconflow.cn/v1', models:['Qwen/Qwen2.5-7B-Instruct'], default_model:'Qwen/Qwen2.5-7B-Instruct'},
      groq: {name:'Groq', api_base:'https://api.groq.com/openai/v1', models:['llama-3.1-8b-instant'], default_model:'llama-3.1-8b-instant'},
      openrouter: {name:'OpenRouter', api_base:'https://openrouter.ai/api/v1', models:['openai/gpt-4o-mini'], default_model:'openai/gpt-4o-mini'},
      lmstudio: {name:'LM Studio (Local)', api_base:'http://localhost:1234/v1', models:[], default_model:''},
      custom: {name:'Custom (OpenAI Compatible)', api_base:'', models:[], default_model:''}
    };
    _ceRenderProviders();
  }
}

function _ceRenderProviders() {
  var grid = document.getElementById('ceProviderGrid');
  if (!grid) return;
  grid.innerHTML = '';
  var keys = Object.keys(_ceProviders);
  for (var i = 0; i < keys.length; i++) {
    var k = keys[i];
    var p = _ceProviders[k];
    var card = document.createElement('div');
    card.className = 'ce-provider-card' + (_ceProviderId === k ? ' selected' : '');
    card.innerHTML = '<div class="ce-provider-name">' + p.name + '</div>' +
                     '<div class="ce-provider-url">' + (p.api_base || 'Custom endpoint') + '</div>';
    card.setAttribute('data-provider', k);
    card.onclick = (function(key) {
      return function() { _ceSelectProvider(key); };
    })(k);
    grid.appendChild(card);
  }
}

function _ceSelectProvider(id) {
  _ceProviderId = id;
  _ceRenderProviders();
}

function _ceRenderStep() {
  for (var i = 1; i <= 4; i++) {
    var page = document.getElementById('cePage' + i);
    if (page) page.style.display = (i === _ceWizardStep) ? 'block' : 'none';
  }
  var nums = document.querySelectorAll('.ce-step-num');
  for (var j = 0; j < nums.length; j++) {
    var step = parseInt(nums[j].parentElement.getAttribute('data-step'));
    nums[j].className = 'ce-step-num';
    if (step < _ceWizardStep) nums[j].className += ' done';
    else if (step === _ceWizardStep) nums[j].className += ' active';
  }
  var prev = document.getElementById('cePrevBtn');
  var next = document.getElementById('ceNextBtn');
  var save = document.getElementById('ceSaveBtn');
  prev.style.display = _ceWizardStep > 1 ? 'inline-block' : 'none';
  next.style.display = _ceWizardStep < 4 ? 'inline-block' : 'none';
  save.style.display = _ceWizardStep === 4 ? 'inline-block' : 'none';

  if (_ceWizardStep === 2) _cePopulatePage2();
  if (_ceWizardStep === 4) _ceRenderSummary();
}

function _cePopulatePage2() {
  var p = _ceProviders[_ceProviderId] || {};
  var baseInput = document.getElementById('ceApiBase');
  var modelInput = document.getElementById('ceModelName');
  if (baseInput && !baseInput.value) baseInput.value = p.api_base || '';
  if (modelInput && !modelInput.value) modelInput.value = p.default_model || '';
  var chipBox = document.getElementById('ceModelChips');
  var chipField = document.getElementById('ceModelSelectField');
  if (p.models && p.models.length > 0) {
    chipField.style.display = 'block';
    chipBox.innerHTML = '';
    for (var i = 0; i < p.models.length; i++) {
      var chip = document.createElement('span');
      chip.className = 'ce-model-chip';
      chip.textContent = p.models[i];
      chip.onclick = (function(m) {
        return function() {
          document.getElementById('ceModelName').value = m;
          var all = chipBox.querySelectorAll('.ce-model-chip');
          for (var j = 0; j < all.length; j++) all[j].className = 'ce-model-chip';
          this.className += ' selected';
        };
      })(p.models[i]);
      chipBox.appendChild(chip);
    }
  } else {
    chipField.style.display = 'none';
  }
}

function _ceRenderSummary() {
  var box = document.getElementById('ceSummary');
  var p = _ceProviders[_ceProviderId] || {};
  var apiBase = document.getElementById('ceApiBase').value || '';
  var model = document.getElementById('ceModelName').value || '';
  var key = document.getElementById('ceApiKey').value || '';
  var maskedKey = key ? key.substring(0, 4) + '****' + key.substring(key.length - 4) : '(none)';
  var name = document.getElementById('ceDisplayName').value || p.name || _ceProviderId;
  box.innerHTML =
    '<div class="ce-summary-row"><span class="ce-summary-key">Provider</span><span class="ce-summary-val">' + (p.name || _ceProviderId) + '</span></div>' +
    '<div class="ce-summary-row"><span class="ce-summary-key">API Endpoint</span><span class="ce-summary-val">' + apiBase + '</span></div>' +
    '<div class="ce-summary-row"><span class="ce-summary-key">Model</span><span class="ce-summary-val">' + model + '</span></div>' +
    '<div class="ce-summary-row"><span class="ce-summary-key">API Key</span><span class="ce-summary-val">' + maskedKey + '</span></div>' +
    '<div class="ce-summary-row"><span class="ce-summary-key">Display Name</span><span class="ce-summary-val">' + name + '</span></div>';
  var testResult = document.getElementById('ceTestResult');
  testResult.style.display = 'none';
  _ceTestPassed = false;
}

function ceWizardNext() {
  if (_ceWizardStep === 1) {
    if (!_ceProviderId) { _ceShowInlineError('Please select a provider'); return; }
  } else if (_ceWizardStep === 2) {
    var base = document.getElementById('ceApiBase').value.trim();
    var model = document.getElementById('ceModelName').value.trim();
    if (!base) { _ceShowInlineError('API Endpoint is required'); return; }
    if (!model) { _ceShowInlineError('Model name is required'); return; }
  } else if (_ceWizardStep === 3) {
    // Key is optional for local providers like LM Studio
  }
  _ceWizardStep++;
  _ceRenderStep();
}

function ceWizardPrev() {
  if (_ceWizardStep > 1) { _ceWizardStep--; _ceRenderStep(); }
}

function testCustomEngineConnection() {
  var base = document.getElementById('ceApiBase').value.trim();
  var key = document.getElementById('ceApiKey').value.trim();
  var model = document.getElementById('ceModelName').value.trim();
  var btn = document.getElementById('ceTestBtn');
  var result = document.getElementById('ceTestResult');
  btn.className += ' testing';
  btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-2px;margin-right:6px;animation:spin 1s linear infinite"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Testing...';
  result.style.display = 'none';

  var payload = JSON.stringify({ api_base: base, api_key: key, model: model });
  if (typeof window._callPython === 'function') {
    window._callPython('testCustomEngine', payload, function(resp) {
      btn.className = 'ce-test-btn';
      btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-2px;margin-right:6px"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> Test Connection';
      result.style.display = 'block';
      if (resp && resp.success) {
        result.className = 'ce-test-result success';
        result.textContent = 'Connected! ' + resp.message + (resp.models && resp.models.length > 0 ? ' Models: ' + resp.models.slice(0, 8).join(', ') : '');
        _ceTestPassed = true;
        if (resp.models && resp.models.length > 0 && !document.getElementById('ceModelName').value) {
          document.getElementById('ceModelName').value = resp.models[0];
        }
      } else {
        result.className = 'ce-test-result fail';
        result.textContent = 'Failed: ' + (resp ? resp.message : 'Unknown error');
        _ceTestPassed = false;
      }
    });
  } else {
    btn.className = 'ce-test-btn';
    result.style.display = 'block';
    result.className = 'ce-test-result fail';
    result.textContent = 'Bridge not available (not running inside LemonCode)';
  }
}

function ceWizardSave() {
  var base = document.getElementById('ceApiBase').value.trim();
  var key = document.getElementById('ceApiKey').value.trim();
  var model = document.getElementById('ceModelName').value.trim();
  var name = document.getElementById('ceDisplayName').value.trim();
  var p = _ceProviders[_ceProviderId] || {};
  if (!base || !model) { _ceShowInlineError('API Endpoint and Model are required'); return; }

  var payload = JSON.stringify({
    provider_id: _ceProviderId,
    display_name: name || p.name || _ceProviderId,
    api_base: base,
    api_key: key,
    model: model,
    models: p.models || []
  });

  if (typeof window._callPython === 'function') {
    window._callPython('addCustomEngine', payload, function(resp) {
      if (resp && resp.success) {
        switchModel(_ceProviderId, model, name || model);
        closeCustomEngineWizard();
        appendMsg('status', '<span style="color:#4caf50;">{ICON:check-circle} Custom engine "' + (name || _ceProviderId) + '" connected!</span>');
        toggleModelPanel();
        refreshModelPanel();
      } else {
        _ceShowInlineError(resp ? resp.message : 'Failed to add engine');
      }
    });
  }
}

function toggleCeKeyVisibility() {
  var input = document.getElementById('ceApiKey');
  input.type = input.type === 'password' ? 'text' : 'password';
}

function _ceShowInlineError(msg) {
  var existing = document.querySelector('.ce-inline-error');
  if (existing) existing.remove();
  var body = document.querySelector('#cePage' + _ceWizardStep);
  if (!body) return;
  var err = document.createElement('div');
  err.className = 'ce-inline-error';
  err.style.cssText = 'color:#f44336;font-size:11px;margin-top:8px;padding:6px 10px;background:rgba(244,67,54,0.1);border:1px solid rgba(244,67,54,0.2);border-radius:4px;';
  err.textContent = msg;
  body.appendChild(err);
  setTimeout(function() { if (err.parentNode) err.remove(); }, 4000);
}

function _ceLoadCustomEngineModels() {
  for (var key in _engineModels) {
    if (key.indexOf('compat_') === 0) {
      loadEngineModels(key);
    }
  }
}

function _ceRefreshCustomSections() {
  var container = document.getElementById('customEngineSections');
  if (!container) return;
  container.innerHTML = '';
  for (var key in _engineModels) {
    if (key.indexOf('compat_') !== 0) continue;
    var models = _engineModels[key] || [];
    var displayKey = key.replace('compat_', '');
    var section = document.createElement('div');
    section.className = 'model-provider-section';
    section.setAttribute('data-provider', key);
    var displayName = _currentModel.provider === key ? _currentModel.modelName : displayKey;
    section.innerHTML = '<div class="model-provider-title"><span class="provider-dot" style="background:#9b59b6;"></span>' + (displayName || displayKey) + '</div><div class="model-options" id="' + key + 'ModelOptions"></div>';
    container.appendChild(section);
    var opts = document.getElementById(key + 'ModelOptions');
    if (opts) {
      if (models.length === 0) {
        opts.innerHTML = '<div class="model-option" style="cursor:default;color:rgba(255,255,255,0.3);">No models</div>';
      } else {
        for (var i = 0; i < models.length; i++) {
          var m = models[i];
          var div = document.createElement('div');
          div.className = 'model-option' + (_currentModel.provider === key && _currentModel.modelId === m.id ? ' active' : '');
          div.innerHTML = '<span>' + m.name + '</span><span class="model-option-status online">●</span>';
          div.onclick = (function(k, mid, mname) {
            return function() { switchModel(k, mid, mname); };
          })(key, m.id, m.name);
          opts.appendChild(div);
        }
      }
    }
  }
}

function onStreamStart() {
  // 创建新的 AI 消息块
  _streamActive = true;
  _streamBuffer = "";
  _streamPendingText = "";
  // ★ v5.1: P-F 运行状态栏进入 busy 态
  if (typeof window.setStatusBarLive === 'function') {
    window.setStatusBarLive(0, '', '');
  }
  // ★ v5.1: 新会话开始 → 重置任务条收起状态（允许本次自动显示，用户收起后本会话内不再弹回）
  if (typeof _taskbarCollapsed !== 'undefined') { _taskbarCollapsed = false; }

  var outputMessages = document.getElementById('outputMessages');
  if (!outputMessages) return;

  var block = document.createElement('div');
  block.className = 'msg-block msg-ai';
  block.dataset.msgIndex = window._globalMsgCount++;  // ★ 设置消息索引（虚拟滚动用）

  // 添加回退按钮
  var rollbackBtn = document.createElement('div');
  rollbackBtn.className = 'snapshot-rollback-btn';
  rollbackBtn.title = '回退到此次修改前';
  rollbackBtn.innerHTML = SVG_ICONS['corner-down-left'];
  rollbackBtn.onclick = function(e) {
    e.stopPropagation();
    showSnapshotRollbackModal(block);
  };
  block.appendChild(rollbackBtn);

  var contentWrap = document.createElement('div');
  contentWrap.className = 'ai-content';
  block.appendChild(contentWrap);

  // 添加打字机光标
  _streamCursor = document.createElement('span');
  _streamCursor.className = 'stream-cursor';
  contentWrap.appendChild(_streamCursor);

  outputMessages.appendChild(block);
  _streamTargetBlock = block;
  _streamTargetContent = contentWrap;

  // ★ 自动滚动（仅在用户未手动滚动时）
  if (_autoScroll) {
    var area = document.getElementById('outputMessages');
    if (area) area.scrollTop = area.scrollHeight;
  }
}

// ★ 品牌文本替换：将后端返回的 mimocode 相关文本替换为 Lemon Code
function _replaceBrandText(text) {
  if (!text) return text;
  // ★ 只替换产品名称 "MiMo Code Agent" → "Lemon Code Agent"
  // 不替换底层模型名（mimo-auto 保持原样，因为确实是它在提供算力）
  text = text.replace(/MiMo\s*Code\s*Agent/gi, 'Lemon Code Agent');
  text = text.replace(/MiMo\s*Code/gi, 'Lemon Code');
  text = text.replace(/mimocode/gi, 'Lemon Code');
  text = text.replace(/小米\s*MiMo/gi, '柠檬 Lemon');
  text = text.replace(/小米/gi, '柠檬');
  return text;
}

// ★ 打字机标点停顿映射（毫秒）
var _PUNCTUATION_PAUSE = {
  '.': 120, '。': 150, '!': 100, '！': 120, '?': 100, '？': 120,
  ',': 40, '，': 50, ';': 60, '；': 70, ':': 60, '：': 70,
  '\n': 30
};
var _charQueue = [];
var _charTimer = null;
var _CHAR_SPEED = 18; // 基础字符间隔（ms）

function onStreamToken(token) {
  if (!_streamActive || !_streamTargetContent) return;

  _streamBuffer += token;
  _streamPendingText += token;

  // ★ 将 token 拆分为字符队列，支持变速输出
  for (var i = 0; i < token.length; i++) {
    _charQueue.push(token[i]);
  }
  _flushCharQueue();

  // 50ms 批量滚动
  if (!_streamFlushTimer) {
    _streamFlushTimer = setTimeout(function() {
      _streamFlushTimer = null;
      if (_autoScroll) {
        var area = document.getElementById('outputMessages');
        if (area) area.scrollTop = area.scrollHeight;
      }
      _streamPendingText = "";
    }, 50);
  }
}

function _flushCharQueue() {
  if (_charTimer || _charQueue.length === 0) return;
  _processNextChar();
}

function _processNextChar() {
  if (_charQueue.length === 0) {
    _charTimer = null;
    return;
  }
  var ch = _charQueue.shift();
  if (ch === '\n') {
    _streamTargetContent.insertBefore(document.createElement('br'), _streamCursor);
  } else {
    var span = document.createElement('span');
    span.className = 'stream-char-enter';
    span.textContent = ch;
    _streamTargetContent.insertBefore(span, _streamCursor);
  }
  // ★ 标点符号自然停顿
  var delay = _PUNCTUATION_PAUSE[ch] || _CHAR_SPEED;
  _charTimer = setTimeout(_processNextChar, delay);
}

function onStreamEnd(fullText) {
  if (!_streamActive) return;
  _streamActive = false;
  _streamRendered = true;  // ★ 标记渲染完成，防止 appendMsg 重复渲染
  // ★ v4.2.4: 咩咩任务完成，切庆祝/成功状态
  if (document.getElementById('miemiePanel') && document.getElementById('miemiePanel').style.display !== 'none') {
    setMiemieMood('success', 4);
  }

  // ★ 清理字符队列和定时器
  _charQueue = [];
  if (_charTimer) {
    clearTimeout(_charTimer);
    _charTimer = null;
  }

  // 清理定时器
  if (_streamFlushTimer) {
    clearTimeout(_streamFlushTimer);
    _streamFlushTimer = null;
  }

  // 移除光标
  if (_streamCursor && _streamCursor.parentNode) {
    _streamCursor.parentNode.removeChild(_streamCursor);
  }
  _streamCursor = null;

  // ★ 回退渲染：仅在内容为空时执行
  if (_streamTargetContent && fullText) {
    var hasChartMarkers = _streamTargetContent.querySelector('.chart-marker');
    if (!hasChartMarkers && !_streamTargetContent.textContent.trim()) {
      var html = window.mimoAgent && window.mimoAgent.markdownToHtml
        ? window.mimoAgent.markdownToHtml(fullText)
        : fullText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      _streamTargetContent.innerHTML = html;
    }
    // ★ 保存滚动位置
    var area = document.getElementById('outputMessages');
    var savedScroll = area ? area.scrollTop : 0;
    if (!_autoScroll && area && savedScroll > 0) {
      area.scrollTop = savedScroll;
    }

    // 重新添加回退按钮
    if (_streamTargetBlock && !_streamTargetBlock.querySelector('.snapshot-rollback-btn')) {
      var rb = document.createElement('div');
      rb.className = 'snapshot-rollback-btn';
      rb.title = '回退到此次修改前';
      rb.innerHTML = SVG_ICONS['corner-down-left'];
      rb.onclick = function(e) {
        e.stopPropagation();
        showSnapshotRollbackModal(_streamTargetBlock);
      };
      _streamTargetBlock.insertBefore(rb, _streamTargetContent);
    }
  }

  // ★ 移除自动折叠功能（超过5000字符自动折叠导致内容消失）
  // 之前：_streamBuffer.length > 5000 → 添加 msg-collapsed 类 → 内容被隐藏
  // 现在：不自动折叠，始终显示完整内容

  // ★ 流式结束后触发图表检测和渲染（保存引用，避免被 null 重置影响）
  var savedBlock = _streamTargetBlock;
  var savedContent = _streamTargetContent;
  if (savedBlock) {
    setTimeout(function() {
      try {
        scanAndRenderCharts(savedBlock);
      } catch(e) {
        console.log('[Stream] 图表检测异常:', e);
      }
    }, 100);
  }

  // ★ 最终滚动（仅在用户未手动滚动时）
  if (_autoScroll) {
    var area = document.getElementById('outputMessages');
    if (area) area.scrollTop = area.scrollHeight;
  }

  // 重置状态
  _streamBuffer = "";
  _streamPendingText = "";
  _streamTargetBlock = null;
  _streamTargetContent = null;
  // ★ v4.1.15: 队列出队 — Agent 空闲后自动处理排队消息
  if (typeof _drainQueue === 'function') { setTimeout(_drainQueue, 300); }
}

// ★ 引擎模式流式替换：用后端渲染的 HTML 替换流式块内容
function clearStreamBlock() {
  if (!_streamTargetBlock) return;
  _streamTargetBlock.parentNode.removeChild(_streamTargetBlock);
  _streamTargetBlock = null;
  _streamTargetContent = null;
  _streamActive = false;
  _streamBuffer = "";
  _streamPendingText = "";
  _charQueue = [];
  if (_charTimer) { clearTimeout(_charTimer); _charTimer = null; }
  if (_streamFlushTimer) { clearTimeout(_streamFlushTimer); _streamFlushTimer = null; }
  if (_streamCursor && _streamCursor.parentNode) { _streamCursor.parentNode.removeChild(_streamCursor); _streamCursor = null; }
}

function replaceStreamBlockHTML(html) {
  if (!_streamTargetContent || !_streamActive) return;
  // 移除光标
  if (_streamCursor && _streamCursor.parentNode) {
    _streamCursor.parentNode.removeChild(_streamCursor);
    _streamCursor = null;
  }
  // 替换内容为后端渲染的 HTML
  _streamTargetContent.innerHTML = html;
  _streamActive = false;
  _streamRendered = true;  // ★ 标记渲染完成
  // 触发图表检测（保存引用，避免被 null 重置影响）
  var savedBlock = _streamTargetBlock;
  if (savedBlock) {
    setTimeout(function() {
      try { scanAndRenderCharts(savedBlock); } catch(e) {}
    }, 100);
  }
  // 重置
  _streamBuffer = "";
  _streamPendingText = "";
  _streamTargetBlock = null;
  _streamTargetContent = null;
}

function onStreamError(errorMsg) {
  if (!_streamActive) return;
  _streamActive = false;

  // 清理定时器
  if (_streamFlushTimer) {
    clearTimeout(_streamFlushTimer);
    _streamFlushTimer = null;
  }

  // 移除光标
  if (_streamCursor && _streamCursor.parentNode) {
    _streamCursor.parentNode.removeChild(_streamCursor);
  }
  _streamCursor = null;

  // 显示中断提示
  if (_streamTargetContent) {
    var notice = document.createElement('span');
    notice.className = 'stream-interrupted';
    notice.textContent = '▲ ' + (errorMsg || '连接中断');
    _streamTargetContent.appendChild(notice);
  }

  // 仍然尝试图表渲染（可能部分内容已到达）
  if (_streamTargetBlock && _streamBuffer.length > 10) {
    setTimeout(function() {
      try { scanAndRenderCharts(_streamTargetBlock); } catch(e) {}
    }, 100);
  }

  // 重置
  _streamBuffer = "";
  _streamTargetBlock = null;
  _streamTargetContent = null;
  // ★ v4.1.15: 出错也允许队列出队（避免卡死）
  if (typeof _drainQueue === 'function') { setTimeout(_drainQueue, 300); }
}

var _mathRenderTimer = null;
var _thinkingMathTimer = null;  // 思考内容数学渲染节流定时器

// ★ ===== 输入区域保护监控 =====
// 防止输入区域被意外隐藏或移除
function _protectInputArea() {
  try {
    var inputArea = document.querySelector('.input-area');
    var inputField = document.getElementById('inputField');
    var content = document.getElementById('content');
    var actionButtons = document.querySelector('.action-buttons');

    if (inputArea) {
      // 确保输入区域可见
      if (inputArea.style.display === 'none') {
        inputArea.style.display = '';
        console.log('[保护] 输入区域已恢复');
      }
      if (inputArea.style.visibility === 'hidden') {
        inputArea.style.visibility = '';
        console.log('[保护] 输入区域可见性已恢复');
      }
      // 确保 pointer-events 正常
      if (inputArea.style.pointerEvents === 'none') {
        inputArea.style.pointerEvents = '';
        console.log('[保护] 输入区域交互已恢复');
      }
    }
    if (inputField) {
      // 确保输入框可交互
      if (inputField.disabled) {
        inputField.disabled = false;
        console.log('[保护] 输入框已启用');
      }
    }

    // ★ 保护 #content 区域
    if (content) {
      if (content.style.display === 'none') {
        content.style.display = '';
        console.log('[保护] #content 已恢复');
      }
    }

    // ★ 保护顶部按钮区域
    if (actionButtons) {
      if (actionButtons.style.display === 'none') {
        actionButtons.style.display = '';
        console.log('[保护] 顶部按钮已恢复');
      }
    }
  } catch(e) {
    console.error('[保护监控]', e);
  }
}
// 每2秒检查一次
setInterval(_protectInputArea, 2000);

// ★ ===== 代码审查结果展示 =====
function showCodeReviewPanel(issues, fileName) {
  if (!issues || !issues.length) return;

  var outputMessages = document.getElementById('outputMessages');
  if (!outputMessages) return;

  var errors = 0, warnings = 0, infos = 0;
  for (var i = 0; i < issues.length; i++) {
    if (issues[i].severity === 'error') errors++;
    else if (issues[i].severity === 'warning') warnings++;
    else infos++;
  }

  var panel = document.createElement('div');
  panel.className = 'code-review-panel';

  // 头部
  var header = document.createElement('div');
  header.className = 'code-review-header';
  header.innerHTML = '<span>' + SVG_ICONS['file-text'] + ' 代码审查' + (fileName ? ' — ' + fileName : '') + '</span>' +
    '<div class="code-review-summary">' +
    (errors ? '<span class="cr-error">"var(--danger)" ' + errors + ' 错误</span>' : '') +
    (warnings ? '<span class="cr-warning">"var(--warning)" ' + warnings + ' 警告</span>' : '') +
    (infos ? '<span class="cr-info">"var(--accent-blue, #007AFF)" ' + infos + ' 提示</span>' : '') +
    '</div>';
  panel.appendChild(header);

  // 问题列表
  var list = document.createElement('div');
  list.className = 'code-review-list';

  for (var j = 0; j < issues.length; j++) {
    var issue = issues[j];
    var item = document.createElement('div');
    item.className = 'code-review-item';

    var iconChar = issue.severity === 'error' ? '!' : (issue.severity === 'warning' ? '!' : 'i');
    var html = '<div class="cr-item-header">' +
      '<span class="cr-icon ' + issue.severity + '">' + iconChar + '</span>' +
      '<span class="cr-line">L' + issue.line + (issue.col ? ':' + issue.col : '') + '</span>' +
      '<span class="cr-desc">' + escapeHtml(issue.description) + '</span>' +
      '</div>';

    if (issue.suggestion) {
      html += '<div class="cr-suggestion">' + SVG_ICONS.lightbulb + ' ' + escapeHtml(issue.suggestion) + '</div>';
    }
    if (issue.code_snippet) {
      html += '<div class="cr-snippet">' + escapeHtml(issue.code_snippet) + '</div>';
    }

    item.innerHTML = html;
    // 点击跳转到对应文件和行号（通过 JS 桥接调用编辑器）
    (function(ln, fn) {
      item.onclick = function() {
        if (typeof window._callPython === 'function') {
          window._callPython('openFileAtLine', fn || '', ln);
        }
      };
    })(issue.line, fileName);

    list.appendChild(item);
  }

  panel.appendChild(list);
  outputMessages.appendChild(panel);

  // 自动滚动
  safeScrollToBottom();
}

// 主动调用代码审查
function runCodeReview(code, language) {
  if (typeof window._callPython !== 'function') return;
  window._callPython('reviewCode', code, language || 'python', function(result) {
    if (result && result.issues) {
      showCodeReviewPanel(result.issues, '');
    }
  });
}

function runFileReview(filePath) {
  if (typeof window._callPython !== 'function') return;
  window._callPython('reviewFile', filePath, function(result) {
    if (result && result.issues) {
      showCodeReviewPanel(result.issues, result.file || filePath);
    }
  });
}

// 数学公式渲染封装
function renderMathInContainer(container) {
  if (!container) return;
  console.log('[renderMathInContainer] 开始渲染, container=' + (container.className || container.id || 'unknown'));
  // ★ 重试机制：KaTeX 使用 defer 异步加载，可能尚未就绪
  var attempts = 0;
  var maxAttempts = 20;  // v3.88: 增加到20次（约6秒），给CDN足够加载时间
  function tryRender() {
    attempts++;
    if (window.renderMathInElement && window.katex) {
      try {
        renderMathInElement(container, {
          delimiters: [
            {left: '$$', right: '$$', display: true},
            {left: '$', right: '$', display: false},
            {left: '\\(', right: '\\)', display: false},
            {left: '\\[', right: '\\]', display: true}
          ],
          throwOnError: false,
          trust: true
        });
        console.log('[renderMathInContainer] KaTeX 渲染成功, attempts=' + attempts);
      } catch(e) {
        console.warn('[renderMathInContainer] KaTeX 渲染异常:', e);
      }
    } else if (attempts < maxAttempts) {
      console.log('[renderMathInContainer] KaTeX 未就绪, 等待中... attempts=' + attempts);
      setTimeout(tryRender, 300);
    } else {
      // ★ v3.88: KaTeX 加载失败回退 - 用CSS美化公式显示
      console.warn('[renderMathInContainer] KaTeX 加载超时，使用CSS回退样式');
      _applyMathFallbackStyle(container);
    }
  }
  tryRender();
}

// ★ v3.88: KaTeX 加载失败时的回退样式（纯CSS美化公式）
function _applyMathFallbackStyle(container) {
  if (!container) return;
  // 处理 $$...$$ 块级公式
  var html = container.innerHTML;
  html = html.replace(/\$\$([^$]+)\$\$/g, function(match, expr) {
    return '<div style="text-align:center;margin:12px 0;padding:8px 12px;background:rgba(255,154,74,0.08);border-left:3px solid #ff9a4a;border-radius:4px;font-family:serif;font-size:1.1em;color:#ffd4a8;">' + expr + '</div>';
  });
  // 处理 $...$ 行内公式
  html = html.replace(/\$([^$\n]+)\$/g, function(match, expr) {
    return '<code style="background:rgba(255,154,74,0.15);color:#ffb380;padding:1px 6px;border-radius:3px;font-family:serif;font-size:0.95em;">' + expr + '</code>';
  });
  container.innerHTML = html;
}

// ===== 图表渲染：扫描 .chart-marker 元素并渲染 =====
function scanAndRenderCharts(container) {
  if (!container) return;
  try {
    // ★ 先扫描后端注入的 .chart-marker DOM 元素
    renderAutoDetectedGraphs(container);
    // ★ 再扫描文本中的图表描述（如 [chart:bar] 或图表说明）
    renderTextBasedCharts(container);
    // ★ 最后渲染数学公式
    renderMathInContainer(container);
  } catch(e) {
    console.warn('[scanAndRenderCharts] 异常:', e);
  }
}

// ===== 基于文本的图表渲染（检测 AI 回复中的图表描述） =====
function renderTextBasedCharts(container) {
  if (!container) return;
  var textContent = container.textContent || container.innerText || '';
  
  // 检测图表关键词
  var chartKeywords = [
    /折线图|line\s*chart/i,
    /柱状图|bar\s*chart/i,
    /饼图|pie\s*chart/i,
    /散点图|scatter\s*plot/i,
    /图表说明|数据点|labels.*values/i
  ];
  
  var hasChart = chartKeywords.some(function(kw) { return kw.test(textContent); });
  if (!hasChart) return;
  
  // 检查是否已经渲染过
  if (container.querySelector('.auto-graph-rendered')) return;
  
  // 尝试从文本中提取数据
  var data = extractChartDataFromText(textContent);
  if (!data || !data.labels || !data.values) return;
  
  // 创建图表容器
  var graphId = 'auto_graph_' + Math.random().toString(36).substr(2, 9);
  var graphDiv = document.createElement('div');
  graphDiv.className = 'auto-graph-rendered';
  graphDiv.id = graphId;
  container.insertBefore(graphDiv, container.firstChild);
  
  // 渲染图表
  var chartType = detectChartType(textContent);
  _renderChartByType(graphId, { type: chartType, data: data });
}

// 从文本中提取图表数据
function extractChartDataFromText(text) {
  // 尝试提取 JSON 格式数据
  var jsonMatch = text.match(/\{[\s\S]*?"labels"\s*:\s*\[[\s\S]*?\][\s\S]*?"values"\s*:\s*\[[\s\S]*?\][\s\S]*?\}/);
  if (jsonMatch) {
    try {
      return JSON.parse(jsonMatch[0]);
    } catch(e) {}
  }
  
  // 尝试提取 Markdown 表格
  var tableMatch = text.match(/((?:\|[^\n]+\|\n)+)/);
  if (tableMatch) {
    var lines = tableMatch[1].trim().split('\n').filter(function(l) { return l.trim(); });
    if (lines.length >= 2) {
      var headers = lines[0].split('|').map(function(h) { return h.trim(); }).filter(Boolean);
      var labels = [];
      var values = [];
      for (var i = 1; i < lines.length; i++) {
        var cells = lines[i].split('|').map(function(c) { return c.trim(); }).filter(Boolean);
        if (cells.length >= 2) {
          labels.push(cells[0]);
          values.push(parseFloat(cells[1]) || 0);
        }
      }
      if (labels.length > 0) return { labels: labels, values: values };
    }
  }
  
  // 尝试提取 "标签：数值" 格式
  var pairs = text.match(/([^\n:：]+)[：:]\s*([\d.]+)/g);
  if (pairs && pairs.length >= 2) {
    var labels = [];
    var values = [];
    pairs.forEach(function(p) {
      var parts = p.split(/[：:]\s*/);
      if (parts.length === 2) {
        labels.push(parts[0].trim());
        values.push(parseFloat(parts[1]) || 0);
      }
    });
    if (labels.length > 0) return { labels: labels, values: values };
  }
  
  return null;
}

// 检测图表类型
function detectChartType(text) {
  if (/饼图|pie\s*chart/i.test(text)) return 'pie';
  if (/散点图|scatter\s*plot/i.test(text)) return 'scatter';
  if (/折线图|line\s*chart/i.test(text)) return 'line';
  return 'bar'; // 默认柱状图
}

// ===== 智能组件渲染：扫描代码块并转换为可视化组件 =====
function renderSmartComponents(container) {
  if (!container) return;
  
  // 查找所有 pre > code 代码块
  var codeBlocks = container.querySelectorAll('pre > code');
  codeBlocks.forEach(function(codeEl) {
    var pre = codeEl.parentElement;
    var lang = codeEl.className || '';
    var text = codeEl.textContent || '';
    
    // ★ P13: 检测 ui-sketch 代码块，渲染为白线素描 UI 概念图
    if (lang.includes('ui-sketch') || (text.indexOf('\u250c') > -1 && text.indexOf('\u2510') > -1 && text.indexOf('\u2502') > -1 && (text.indexOf('[') > -1 || text.indexOf('File') > -1 || text.indexOf('Edit') > -1))) {
      var sketchDiv = document.createElement('div');
      sketchDiv.className = 'smart-rendered';
      pre.parentNode.replaceChild(sketchDiv, pre);
      renderUiSketch(sketchDiv, text);
      return;
    }
    
    // 检查语言类型
    if (lang.includes('language-function-cards') || lang.includes('function-cards')) {
      try {
        var config = JSON.parse(text);
        var div = document.createElement('div');
        div.className = 'smart-rendered';
        var id = 'func_cards_' + Math.random().toString(36).substr(2, 9);
        div.id = id;
        pre.parentNode.replaceChild(div, pre);
        renderFunctionCards(id, config.functions || config);
      } catch(e) {
        console.warn('函数卡片解析失败:', e);
      }
    }
    else if (lang.includes('language-matrix') || lang.includes('matrix')) {
      try {
        var config = JSON.parse(text);
        var div = document.createElement('div');
        div.className = 'smart-rendered';
        var id = 'matrix_' + Math.random().toString(36).substr(2, 9);
        div.id = id;
        pre.parentNode.replaceChild(div, pre);
        renderMatrix(id, config);
      } catch(e) {
        console.warn('矩阵解析失败:', e);
      }
    }
    else if (lang.includes('language-sequence') || lang.includes('sequence')) {
      try {
        var config = JSON.parse(text);
        var div = document.createElement('div');
        div.className = 'smart-rendered';
        var id = 'seq_' + Math.random().toString(36).substr(2, 9);
        div.id = id;
        pre.parentNode.replaceChild(div, pre);
        renderSequence(id, config);
      } catch(e) {
        console.warn('数列解析失败:', e);
      }
    }
    else if (lang.includes('language-dot-plot') || lang.includes('dot-plot') || lang.includes('function-plot')) {
      try {
        var config = JSON.parse(text);
        var div = document.createElement('div');
        div.className = 'smart-rendered chart-container';
        var id = 'dot_plot_' + Math.random().toString(36).substr(2, 9);
        div.id = id;
        pre.parentNode.replaceChild(div, pre);
        renderDotPlot(id, config);
      } catch(e) {
        console.warn('打点图解析失败:', e);
      }
    }
    else if (lang.includes('language-task-plan') || lang.includes('task-plan')) {
      try {
        var config = JSON.parse(text);
        var div = document.createElement('div');
        div.className = 'smart-rendered';
        renderTaskPlanInline(div, config);
        pre.parentNode.replaceChild(div, pre);
      } catch(e) {
        console.warn('任务计划解析失败:', e);
      }
    }
    else if (lang.includes('language-file-diff') || lang.includes('file-diff')) {
      try {
        var config = JSON.parse(text);
        var div = document.createElement('div');
        div.className = 'smart-rendered';
        renderFileDiffInline(div, config);
        pre.parentNode.replaceChild(div, pre);
      } catch(e) {
        console.warn('文件diff解析失败:', e);
      }
    }
  });
}

// ===== 内联任务计划展示（Trae风格） =====
function renderTaskPlanInline(container, config) {
  var tasks = config.tasks || config.entries || [];
  var title = config.title || '任务计划';
  
  var completed = 0;
  var inProgress = 0;
  tasks.forEach(function(t) {
    if (t.status === 'completed') completed++;
    else if (t.status === 'in_progress') inProgress++;
  });
  var total = tasks.length;
  var progress = total > 0 ? Math.round((completed / total) * 100) : 0;
  
  var html = '<div class="task-plan-card">';
  html += '<div class="task-plan-header">';
  html += '<div class="task-plan-title">' + SVG_ICONS['file-text'] + ' ' + title + '</div>';
  html += '<div class="task-plan-progress-text">' + completed + '/' + total + ' 已完成</div>';
  html += '</div>';
  html += '<div class="task-plan-progress-bar">';
  html += '<div class="task-plan-progress-fill" style="width:' + progress + '%"></div>';
  html += '</div>';
  html += '<div class="task-plan-list">';
  
  tasks.forEach(function(task, idx) {
    var status = task.status || 'pending';
    var statusClass = '';
    var statusIcon = '○';
    if (status === 'completed') {
      statusClass = 'task-completed';
      statusIcon = SVG_ICONS.check;
    } else if (status === 'in_progress') {
      statusClass = 'task-in-progress';
      statusIcon = '◉';
    }
    
    html += '<div class="task-plan-item ' + statusClass + '">';
    html += '<span class="task-item-status">' + statusIcon + '</span>';
    html += '<span class="task-item-content">' + (task.content || task.title || '') + '</span>';
    if (task.detail) {
      html += '<div class="task-item-detail">' + task.detail + '</div>';
    }
    html += '</div>';
  });
  
  html += '</div></div>';
  container.innerHTML = html;
}

// ===== 内联文件修改Diff展示（Trae风格） =====
function renderFileDiffInline(container, config) {
  var files = config.files || [];
  
  var totalAdditions = 0;
  var totalDeletions = 0;
  files.forEach(function(f) {
    totalAdditions += f.additions || 0;
    totalDeletions += f.deletions || 0;
  });
  
  var html = '<div class="file-diff-card">';
  html += '<div class="file-diff-header">';
  html += '<div class="file-diff-title">◈ 文件变更</div>';
  html += '<div class="file-diff-stats">';
  html += '<span class="diff-add">+' + totalAdditions + '</span>';
  html += '<span class="diff-del">-' + totalDeletions + '</span>';
  html += '<span class="diff-files">' + files.length + ' 个文件</span>';
  html += '</div></div>';
  html += '<div class="file-diff-list">';
  
  files.forEach(function(file) {
    var status = file.status || 'modified';
    // ★ v4.7.23: 去 emoji — git diff 状态用极简线条字符
    var statusIcon = '◈';   // modified
    var statusClass = 'file-modified';
    if (status === 'added' || status === 'created') {
      statusIcon = SVG_ICONS.zap;     // added
      statusClass = 'file-added';
    } else if (status === 'deleted' || status === 'removed') {
      statusIcon = SVG_ICONS['circle-x'];     // deleted
      statusClass = 'file-deleted';
    } else if (status === 'renamed') {
      statusIcon = SVG_ICONS['file-symlink'];     // renamed
      statusClass = 'file-renamed';
    }
    
    html += '<div class="file-diff-item ' + statusClass + '">';
    html += '<span class="file-diff-icon">' + statusIcon + '</span>';
    html += '<span class="file-diff-path" title="' + (file.path || '') + '">' + (file.path || file.name || '') + '</span>';
    html += '<span class="file-diff-changes">';
    if (file.additions !== undefined) {
      html += '<span class="diff-add">+' + file.additions + '</span>';
    }
    if (file.deletions !== undefined) {
      html += '<span class="diff-del">-' + file.deletions + '</span>';
    }
    html += '</span></div>';
    
    // 如果有diff内容，可展开查看
    if (file.diff) {
      html += '<div class="file-diff-content">';
      var lines = file.diff.split('\n');
      lines.forEach(function(line) {
        var lineClass = 'diff-line';
        if (line.startsWith('+')) lineClass += ' diff-add-line';
        else if (line.startsWith('-')) lineClass += ' diff-del-line';
        else if (line.startsWith('@@')) lineClass += ' diff-hunk-line';
        html += '<div class="' + lineClass + '">' + escapeHtml(line) + '</div>';
      });
      html += '</div>';
    }
  });
  
  html += '</div></div>';
  container.innerHTML = html;
}

function escapeHtml(text) {
  var div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ===== 自动检测并渲染图表/函数图像 =====
function _parseMarker(markerText) {
  if (!markerText) return null;
  // 【chart:xxx】标记
  var chartMatch = markerText.match(/【chart:(\w+)】/);
  if (chartMatch) {
    var type = chartMatch[1];
    var names = { bar: '柱状图', line: '折线图', scatter: '散点图', pie: '饼图', surface3d: '3D曲面' };
    return { type: type, data: null, name: names[type] || '图表' };
  }
  // 【geom:xxx】标记
  var geomMatch = markerText.match(/【geom:(\w+)】/);
  if (geomMatch) {
    var subtype = geomMatch[1];
    var geomNames = {
      cube: '正方体', cuboid: '长方体', cylinder: '圆柱体', cone: '圆锥体',
      sphere: '球体', ellipsoid: '椭球体', pyramid3: '三棱锥',
      pyramid4: '四棱锥', prism3: '三棱柱'
    };
    return { type: 'geom', subtype: subtype, data: null, name: geomNames[subtype] || '几何体' };
  }
  // 函数表达式（y = sin(x) 等）
  if (/y\s*=\s*(sin|cos|tan)\s*\(\s*x\s*\)/i.test(markerText)) {
    var fn = markerText.match(/(sin|cos|tan)/i)[1].toLowerCase();
    return { type: 'function', data: { fn: 'Math.' + fn, amp: 1, freq: 1, name: 'y = ' + fn + '(x)' } };
  }
  return null;
}

function _renderChartByType(containerId, detection) {
  console.log('[_renderChartByType] containerId=' + containerId + ', type=' + detection.type + (detection.subtype ? '/' + detection.subtype : '') + ', name=' + (detection.name || ''));
  setTimeout(function() {
    try {
      var el = document.getElementById(containerId);
      if (!el) { console.warn('[_renderChartByType] 容器不存在: ' + containerId); return; }
      if (detection.type === 'function') {
        renderSimpleGraph(containerId, detection.data);
      } else if (detection.type === 'bar') {
        renderBarChart(containerId, detection.data, detection.name);
      } else if (detection.type === 'line') {
        renderLineChart(containerId, detection.data, detection.name);
      } else if (detection.type === 'scatter') {
        renderScatterPlot(containerId, detection.data, detection.name);
      } else if (detection.type === 'pie') {
        renderPieChart(containerId, detection.data, detection.name);
      } else if (detection.type === 'surface3d') {
        render3DSurface(containerId, detection.data, detection.name);
      } else if (detection.type === 'geom') {
        _dispatchGeom(containerId, detection.subtype, detection.name);
      }
      console.log('[_renderChartByType] 渲染完成: ' + detection.type);
    } catch(e) {
      console.error('[_renderChartByType] 渲染异常:', e);
      var _failedEl = document.getElementById(containerId);
      if (_failedEl && _failedEl.parentNode) _failedEl.parentNode.removeChild(_failedEl);
    }
  }, 50);
}

function renderUiSketch(container, sketchText) {
  // 创建 Canvas
  var canvas = document.createElement('canvas');
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  
  // 解析文本行
  var lines = sketchText.split('\n').filter(function(l) { return l.trim(); });
  
  // 计算画布尺寸
  var maxWidth = 0;
  lines.forEach(function(line) {
    // 移除 ANSI 颜色码
    var clean = line.replace(/\x1b\[[0-9;]*m/g, '');
    maxWidth = Math.max(maxWidth, clean.length);
  });
  
  var charWidth = 7;   // 等宽字体字符宽度
  var lineHeight = 14; // 行高
  var padding = 16;
  
  canvas.width = Math.min(maxWidth * charWidth + padding * 2, 800);
  canvas.height = lines.length * lineHeight + padding * 2;
  canvas.style.maxWidth = '100%';
  canvas.style.height = 'auto';
  canvas.style.borderRadius = '6px';
  canvas.style.margin = '8px 0';
  
  // 深色背景
  ctx.fillStyle = '#1a1a2e';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  
  // 绘制每一行
  lines.forEach(function(line, rowIdx) {
    var clean = line.replace(/\x1b\[[0-9;]*m/g, '');
    var y = padding + rowIdx * lineHeight;
    
    // 检测 Box-drawing 字符
    for (var i = 0; i < clean.length; i++) {
      var ch = clean[i];
      var x = padding + i * charWidth;
      
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1;
      ctx.fillStyle = '#ffffff';
      ctx.font = '10px monospace';
      
      // 绘制 Box-drawing 字符
      switch(ch) {
        case '\u250c': break; // ┌
        case '\u2510': break; // ┐
        case '\u2514': break; // └
        case '\u2518': break; // ┘
        case '\u2502': ctx.fillRect(x + charWidth/2 - 0.5, y, 1, lineHeight); break; // │
        case '\u2500': ctx.fillRect(x, y + lineHeight/2 - 0.5, charWidth, 1); break; // ─
        case '\u251c': break; // ├
        case '\u2524': break; // ┤
        case '\u252c': break; // ┬
        case '\u2534': break; // ┴
        case '\u253c': break; // ┼
        default:
          // 绘制普通文本
          if (ch !== ' ') {
            ctx.fillStyle = '#888888';
            ctx.fillText(ch, x, y + 10);
          }
      }
    }
  });
  
  container.appendChild(canvas);
  
  // 添加 "UI 概念图" 标签
  var label = document.createElement('div');
  label.textContent = 'UI 概念图';
  label.style.cssText = 'font-size:10px;color:#555;text-align:center;margin-bottom:4px;';
  container.insertBefore(label, canvas);
}

function renderAutoDetectedGraphs(container) {
  if (!container) return;
  console.log('[renderAutoDetectedGraphs] 开始扫描, container=' + (container.className || container.id || 'unknown'));

  function detectFromText(text) {
    var results = [];
    if (!text) return results;
    
    var lower = text.toLowerCase();
    
    // ===== 模式1：检测【chart:xxx】标记（后端注入的） =====
    var chartMarker = text.match(/【chart:(\w+)】/);
    if (chartMarker) {
      var type = chartMarker[1];
      if (type === 'bar') results.push({ type: 'bar', data: null, name: '柱状图' });
      else if (type === 'line') results.push({ type: 'line', data: null, name: '折线图' });
      else if (type === 'scatter') results.push({ type: 'scatter', data: null, name: '散点图' });
      else if (type === 'pie') results.push({ type: 'pie', data: null, name: '饼图' });
      else if (type === 'surface3d') results.push({ type: 'surface3d', data: null, name: '3D曲面' });
      return results;
    }
    
    // ===== 模式1b：检测【geom:xxx】3D几何体标记（后端注入的） =====
    var geomMarker = text.match(/【geom:(\w+)】/);
    if (geomMarker) {
      var gtype = geomMarker[1];
      var geomNames = {
        'cube': '正方体',
        'cuboid': '长方体',
        'cylinder': '圆柱体',
        'cone': '圆锥体',
        'sphere': '球体',
        'ellipsoid': '椭球体',
        'pyramid3': '三棱锥',
        'pyramid4': '四棱锥',
        'prism3': '三棱柱'
      };
      results.push({ type: 'geom', subtype: gtype, data: null, name: geomNames[gtype] || '几何体' });
      return results;
    }
    
    // ===== 模式2：文件名匹配（函数图像） =====
    var fileMatch = text.match(/(sin|cos|tan)[_]?x?[_]?(?:plot|graph|image|chart|func|函数)?[_.].*(?:html|png|jpg|svg)/i);
    if (fileMatch) {
      var fn = fileMatch[1].toLowerCase();
      results.push({ type: 'function', data: { fn: 'Math.' + fn, amp: 1, freq: 1, name: 'y = ' + fn + '(x)' } });
      return results;
    }

    // ===== 模式2b：中文函数图像检测 =====
    var cnFuncMatch = text.match(/(sin|cos|tan|正弦|余弦|正切)[^。\n]{0,20}(?:函数)?图像|函数图像.*?(sin|cos|tan)/i);
    if (cnFuncMatch) {
      var fnStr = cnFuncMatch[1] || cnFuncMatch[2];
      var fnName = fnStr.toLowerCase().replace(/正弦/, 'sin').replace(/余弦/, 'cos').replace(/正切/, 'tan');
      if (['sin', 'cos', 'tan'].indexOf(fnName) >= 0) {
        results.push({ type: 'function', data: { fn: 'Math.' + fnName, amp: 1, freq: 1, name: 'y = ' + fnName + '(x)' } });
        return results;
      }
    }

    // ===== 模式2d：函数表达式（y = sin(x)、y = cos(x) 等，后端 chart-marker 注入） =====
    var funcExprMatch = text.match(/y\s*=\s*(sin|cos|tan)\s*\(\s*x\s*\)/i);
    if (funcExprMatch) {
      var fnName2 = funcExprMatch[1].toLowerCase();
      results.push({ type: 'function', data: { fn: 'Math.' + fnName2, amp: 1, freq: 1, name: 'y = ' + fnName2 + '(x)' } });
      return results;
    }

    // ===== 模式2c：ASCII art 函数图像检测 =====
    // 匹配 box-drawing 字符的 ASCII art
    var asciiArtMatch = text.match(/```[\s\S]*?[─│┼┤┬┴└┘┌├┝┞┟┠┡┢┣┥┦┧┨┩┪┫┽┾┿╀╁╂╃╄╅╆╇╈╉╊╋][\s\S]*?```/);
    // ★ v3.91: 同时匹配普通 ASCII 字符的函数图像（.|*-+ 构成的坐标系）
    var plainAsciiMatch = text.match(/```(?:text|plain|ascii)?\s*\n([\s\S]*?)```/);
    var isPlainAsciiFuncPlot = false;
    if (plainAsciiMatch && /(sin|cos|tan|函数|图像)/i.test(text)) {
      var codeBlock = plainAsciiMatch[1];
      var lines = codeBlock.split('\n');
      var hasAxisLabels = /[xy]\s*[|:]/.test(codeBlock) || /[-]*x/.test(codeBlock);
      var hasPlotChars = /[\.\*\+\-]{3,}/.test(codeBlock);
      var hasMultiLines = lines.length >= 3;
      if (hasAxisLabels && hasPlotChars && hasMultiLines) {
        isPlainAsciiFuncPlot = true;
      }
    }
    if ((asciiArtMatch || isPlainAsciiFuncPlot) && /(sin|cos|tan|x|y|π|函数)/i.test(text)) {
      var fnDetected = '';
      if (/sin/i.test(text)) fnDetected = 'sin';
      else if (/cos/i.test(text)) fnDetected = 'cos';
      else if (/tan/i.test(text)) fnDetected = 'tan';
      if (fnDetected) {
        results.push({ type: 'function', data: { fn: 'Math.' + fnDetected, amp: 1, freq: 1, name: 'y = ' + fnDetected + '(x)' } });
        return results;
      }
    }
    
    // ===== 模式3：中文自然语言检测 =====
    // 柱状图/直方图
    if (/(直方图|柱状图|条形图)/i.test(text)) {
      // 检查是否有数据
      var dataMatch = text.match(/数据[：:]\s*([\d,\s]+)/);
      var data = dataMatch ? dataMatch[1].split(',').map(Number) : null;
      results.push({ type: 'bar', data: data, name: '柱状图' });
      return results;
    }
    // 折线图
    if (/(折线图|line\s*chart)/i.test(text)) {
      var dataMatch = text.match(/数据[：:]\s*([\d,\s]+)/);
      var data = dataMatch ? dataMatch[1].split(',').map(Number) : null;
      results.push({ type: 'line', data: data, name: '折线图' });
      return results;
    }
    // 散点图
    if (/(散点图|scatter)/i.test(text)) {
      results.push({ type: 'scatter', data: null, name: '散点图' });
      return results;
    }
    // 饼图/扇形图（市场份额/占比优先匹配饼图）
    if (/(饼图|pie\s*chart|饼状图|扇形图|市场份额|占比|比例分布|市场调查|市场调研|竞品分析)/i.test(text)) {
      results.push({ type: 'pie', data: null, name: '饼图' });
      return results;
    }
    // 折线图/曲线图/趋势图（宽泛匹配）
    if (/(折线图|曲线图|line\s*chart|折线统计|趋势图|走势图|数据趋势|增长趋势|变化趋势|发展趋势|市场趋势|趋势分析|走势分析)/i.test(text)) {
      results.push({ type: 'line', data: null, name: '折线图' });
      return results;
    }
    // 检测"蓝色折线""红色折线"等描述
    if (/[蓝红黄紫绿粉灰黑白色].*?折线/i.test(text)) {
      results.push({ type: 'line', data: null, name: '折线图' });
      return results;
    }
    // 3D曲面/三维
    if (/(3D\s*surface|三维曲面|三维图像)/i.test(text)) {
      results.push({ type: 'surface3d', data: null, name: '3D曲面' });
      return results;
    }
    // 3D几何体：正方体/立方体
    if (/(正方体|立方体|cube|正六面体)/i.test(text)) {
      results.push({ type: 'geom', subtype: 'cube', data: null, name: '正方体' });
      return results;
    }
    // 3D几何体：长方体
    if (/(长方体|四棱柱|cuboid|rectangular.*prism)/i.test(text)) {
      results.push({ type: 'geom', subtype: 'cuboid', data: null, name: '长方体' });
      return results;
    }
    // 3D几何体：圆柱
    if (/(圆柱体?|cylinder)/i.test(text)) {
      results.push({ type: 'geom', subtype: 'cylinder', data: null, name: '圆柱体' });
      return results;
    }
    // 3D几何体：圆锥
    if (/(圆锥体?|cone)/i.test(text)) {
      results.push({ type: 'geom', subtype: 'cone', data: null, name: '圆锥体' });
      return results;
    }
    // 3D几何体：球
    if (/(球[体]?|球体|sphere)/i.test(text) && !/椭球/.test(text)) {
      results.push({ type: 'geom', subtype: 'sphere', data: null, name: '球体' });
      return results;
    }
    // 3D几何体：椭球/椭圆体
    if (/(椭球|椭圆体|椭球体|ellipsoid)/i.test(text)) {
      results.push({ type: 'geom', subtype: 'ellipsoid', data: null, name: '椭球体' });
      return results;
    }
    // 3D几何体：三棱锥/四面体
    if (/(三棱锥|四面体|三角锥|tetrahedron)/i.test(text)) {
      results.push({ type: 'geom', subtype: 'pyramid3', data: null, name: '三棱锥' });
      return results;
    }
    // 3D几何体：四棱锥
    if (/(四棱锥|方锥|棱锥|pyramid)/i.test(text)) {
      results.push({ type: 'geom', subtype: 'pyramid4', data: null, name: '四棱锥' });
      return results;
    }
    // 3D几何体：三棱柱
    if (/(三棱柱|三角柱|triangular\s*prism)/i.test(text)) {
      results.push({ type: 'geom', subtype: 'prism3', data: null, name: '三棱柱' });
      return results;
    }
    // 统计图/数据可视化（通用，放最后）
    if (/(统计图|数据可视化|数据分析|数据统计|数据图表|市场分析)/i.test(text)) {
      results.push({ type: 'bar', data: null, name: '柱状图' });
      return results;
    }
    
    // ===== 模式4：函数描述模式 =====
    var descPatterns = [
      { regex: /(?:sin|cos|tan)\s*\(\s*x\s*\).*?(?:图像|曲线|函数|图|plot|graph|chart)/i, 
        extract: function(m) { 
          var fn = m[0].match(/(sin|cos|tan)/i)[1].toLowerCase();
          return { type: 'function', data: { fn: 'Math.' + fn, amp: 1, freq: 1, name: 'y = ' + fn + '(x)' } }; 
        }
      },
      { regex: /(?:图像|曲线|函数|图|plot|graph|chart).*?(sin|cos|tan)\s*\(\s*x\s*\)/i, 
        extract: function(m) { 
          var fn = m[1].toLowerCase();
          return { type: 'function', data: { fn: 'Math.' + fn, amp: 1, freq: 1, name: 'y = ' + fn + '(x)' } }; 
        }
      },
      { regex: /(正弦|sin)[^。\n]{0,20}(?:图像|曲线|函数|图)/i,
        extract: function() { return { type: 'function', data: { fn: 'Math.sin', amp: 1, freq: 1, name: 'y = sin(x)' } }; }
      },
      { regex: /(余弦|cos)[^。\n]{0,20}(?:图像|曲线|函数|图)/i,
        extract: function() { return { type: 'function', data: { fn: 'Math.cos', amp: 1, freq: 1, name: 'y = cos(x)' } }; }
      },
      { regex: /(正切|tan)[^。\n]{0,20}(?:图像|曲线|函数|图)/i,
        extract: function() { return { type: 'function', data: { fn: 'Math.tan', amp: 1, freq: 1, name: 'y = tan(x)' } }; }
      },
    ];
    for (var i = 0; i < descPatterns.length; i++) {
      var m = text.match(descPatterns[i].regex);
      if (m) { results.push(descPatterns[i].extract(m)); return results; }
    }
    
    // ===== 模式5：y = f(x) 表达式 =====
    var yPatterns = [
      { regex: /y\s*=\s*([0-9.]*)\s*sin\s*\(\s*([0-9.]*)\s*x\s*\)/gi, 
        build: function(m) { return { type: 'function', data: { fn: 'Math.sin', amp: parseFloat(m[1])||1, freq: parseFloat(m[2])||1, name: m[0] } }; } },
      { regex: /y\s*=\s*([0-9.]*)\s*cos\s*\(\s*([0-9.]*)\s*x\s*\)/gi, 
        build: function(m) { return { type: 'function', data: { fn: 'Math.cos', amp: parseFloat(m[1])||1, freq: parseFloat(m[2])||1, name: m[0] } }; } },
      { regex: /y\s*=\s*([0-9.]*)\s*tan\s*\(\s*([0-9.]*)\s*x\s*\)/gi, 
        build: function(m) { return { type: 'function', data: { fn: 'Math.tan', amp: parseFloat(m[1])||1, freq: parseFloat(m[2])||1, name: m[0] } }; } },
      { regex: /y\s*=\s*x\s*\^\s*(\d+)/gi, build: function(m) { return { type: 'function', data: { poly: true, power: parseInt(m[1]), name: m[0] } }; } },
      { regex: /y\s*=\s*1\s*\/\s*x/gi, build: function() { return { type: 'function', data: { spec: 'reciprocal', name: 'y = 1/x' } }; } },
      { regex: /y\s*=\s*e\s*\^\s*x/gi, build: function() { return { type: 'function', data: { spec: 'exp', name: 'y = eˣ' } }; } },
      { regex: /y\s*=\s*ln\s*\(\s*x\s*\)/gi, build: function() { return { type: 'function', data: { spec: 'ln', name: 'y = ln(x)' } }; } },
      { regex: /y\s*=\s*log\s*\(\s*x\s*\)/gi, build: function() { return { type: 'function', data: { spec: 'ln', name: 'y = log(x)' } }; } },
      { regex: /y\s*=\s*sqrt\s*\(\s*x\s*\)/gi, build: function() { return { type: 'function', data: { spec: 'sqrt', name: 'y = √x' } }; } },
    ];
    for (var p = 0; p < yPatterns.length; p++) {
      yPatterns[p].regex.lastIndex = 0;
      var match = yPatterns[p].regex.exec(text);
      if (match) { results.push(yPatterns[p].build(match)); return results; }
    }
    
    return results;
  }
  
  // ===== 优先检测：后端注入的 .chart-marker DOM 标记（最可靠） =====
  var found = false;
  var domMarkers = container.querySelectorAll('.chart-marker');
  console.log('[renderAutoDetectedGraphs] 找到 ' + domMarkers.length + ' 个 chart-marker DOM 元素');
  for (var m = 0; m < domMarkers.length; m++) {
    var marker = domMarkers[m];
    // ★ 黑屏根治 v2: 已渲染过/已冻结的 marker 直接跳过 —— 防止"重扫→再插新图→
    //   活canvas被GPU逐出→黑屏"循环（此前每次重扫都会无条件再插一个 graphDiv）
    var _prev = marker.previousElementSibling;
    if (_prev && (_prev.classList && _prev.classList.contains('auto-graph-rendered') ||
        _prev.dataset && _prev.dataset.chartFrozen === '1')) continue;
    if (marker.dataset && marker.dataset.chartFrozen === '1') continue;
    // ★ v3.88 修复: 优先读取 data-type 属性，回退到文本内容（后端可能只注入文本内容）
    var markerType = marker.getAttribute('data-type') || (marker.textContent || '').trim();
    console.log('[renderAutoDetectedGraphs] markerType=' + markerType);
    if (!markerType) continue;
    // [360章] 无数据标记：跳过渲染，防黑块
    if (!marker.dataset || !marker.dataset.values) {
      marker.dataset.skip = '1';
      continue;
    }
    
    var det = _parseMarker(markerType);
    if (!det) continue;
    
    // ★ 读取 data-values 属性中的结构化数据（后端 _extract_chart_data 提取）
    var dataValuesAttr = marker.getAttribute('data-values');
    if (dataValuesAttr) {
      try {
        det.data = JSON.parse(dataValuesAttr);
      } catch(e) {
        console.warn('[ChartMarker] data-values JSON 解析失败:', e);
      }
    }
    
    var graphId = 'auto_graph_' + Math.random().toString(36).substr(2, 9);
    var graphDiv = document.createElement('div');
    graphDiv.className = 'auto-graph-rendered';
    graphDiv.id = graphId;
    marker.parentNode.insertBefore(graphDiv, marker);
    
    _renderChartByType(graphId, det);
    found = true;
    break;
  }
  
  if (found) return;
  
  // 扫描所有消息块
  var msgBlocks = container.querySelectorAll('.msg-ai, .msg-content, .msg-tool, .msg-status');
  
  for (var b = 0; b < msgBlocks.length; b++) {
    var block = msgBlocks[b];
    if (block.querySelector('.auto-graph-rendered')) continue;
    
    var textContent = block.textContent || block.innerText || '';
    var detections = detectFromText(textContent);
    
    if (detections.length > 0) {
      var det = detections[0];
      var graphId = 'auto_graph_' + Math.random().toString(36).substr(2, 9);
      var graphDiv = document.createElement('div');
      graphDiv.className = 'auto-graph-rendered';
      graphDiv.id = graphId;
      block.insertBefore(graphDiv, block.firstChild);
      _renderChartByType(graphId, det);
      
      found = true;
      break;
    }
  }
  
  // 回退到文本节点扫描
  if (!found) {
    var walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
    var textNodes = [];
    while (walker.nextNode()) {
      textNodes.push(walker.currentNode);
    }
    for (var t = 0; t < textNodes.length; t++) {
      var textNode = textNodes[t];
      var text = textNode.textContent;
      if (!text) continue;
      if (textNode.parentElement && textNode.parentElement.closest('.auto-graph-rendered')) continue;
      var detections = detectFromText(text);
      if (detections.length > 0) {
        var det = detections[0];
        var graphId = 'auto_graph_' + Math.random().toString(36).substr(2, 9);
        var graphDiv = document.createElement('div');
        graphDiv.className = 'auto-graph-rendered';
        graphDiv.id = graphId;
        textNode.parentNode.insertBefore(graphDiv, textNode.nextSibling);
        _renderChartByType(graphId, det);
        break;
      }
    }
  }
}

function renderSimpleGraph(containerId, funcInfo) {
  var container = document.getElementById(containerId);
  if (!container) return;
  
  // 紧凑、无框、融入背景 — 纯数学图风格
  container.style.cssText = 'margin: 8px 0; padding: 0; width: 100%; max-width: 420px;';
  
  // 标题 + Canvas
  var html = '';
  // 标题（顶部居中，像 y = sin(x)）
  html += '<div style="text-align:center; font-size:15px; color:#ffffff; font-family:serif; font-style:italic; margin-bottom:2px; letter-spacing:0.5px;">';
  html += (funcInfo.name || 'y = f(x)');
  html += '</div>';
  // Canvas（透明背景，融入右边栏）
  html += '<canvas id="' + containerId + '_canvas" style="width:100%; height:130px; display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  var cssW = canvas.offsetWidth || 380;
  var cssH = canvas.offsetHeight || 130;
  canvas.width = cssW * 2;
  canvas.height = cssH * 2;
  ctx.scale(2, 2);
  
  var width = cssW;
  var height = cssH;
  
  // 边距（给刻度留空间）
  var pad = { top: 6, right: 12, bottom: 18, left: 28 };
  var plotW = width - pad.left - pad.right;
  var plotH = height - pad.top - pad.bottom;
  
  // 确定x范围
  var xMin = -2 * Math.PI, xMax = 2 * Math.PI;
  if (funcInfo.fn === 'Math.sin' || funcInfo.fn === 'Math.cos' || funcInfo.fn === 'Math.tan') {
    xMin = -2 * Math.PI;
    xMax = 2 * Math.PI;
  } else if (funcInfo.spec === 'reciprocal') { xMin = -5; xMax = 5; }
  else if (funcInfo.spec === 'ln' || funcInfo.spec === 'sqrt') { xMin = 0.01; xMax = 8; }
  else if (funcInfo.spec === 'exp') { xMin = -4; xMax = 4; }
  else if (funcInfo.poly) { xMin = -4; xMax = 4; }
  else if (funcInfo.linear) { xMin = -5; xMax = 5; }
  
  // 计算y范围
  var yMin = -2, yMax = 2;
  if (funcInfo.fn === 'Math.sin' || funcInfo.fn === 'Math.cos') {
    var amp = funcInfo.amp || 1;
    yMin = -amp * 2; yMax = amp * 2;
  } else if (funcInfo.spec === 'exp') { yMin = -1; yMax = 8; }
  else if (funcInfo.spec === 'sqrt') { yMin = -0.5; yMax = 3; }
  else if (funcInfo.linear) {
    var y1 = funcInfo.slope * xMin + funcInfo.intercept;
    var y2 = funcInfo.slope * xMax + funcInfo.intercept;
    yMin = Math.min(y1, y2, -1);
    yMax = Math.max(y1, y2, 1);
  } else if (funcInfo.poly) {
    yMin = -1;
    yMax = Math.pow(Math.max(Math.abs(xMin), Math.abs(xMax)), funcInfo.power || 2);
    if (yMax > 16) yMax = 16;
  }
  
  function toX(x) { return pad.left + (x - xMin) / (xMax - xMin) * plotW; }
  function toY(y) { return pad.top + (1 - (y - yMin) / (yMax - yMin)) * plotH; }
  
  // ===== 网格线（虚线，淡灰色） =====
  ctx.strokeStyle = 'rgba(255,255,255,0.12)';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  
  // 计算合理的网格数量
  var xGridCount = 8;
  var yGridCount = 6;
  
  // 垂直网格线 + X轴刻度
  for (var i = 0; i <= xGridCount; i++) {
    var xv = xMin + (xMax - xMin) * i / xGridCount;
    var gx = toX(xv);
    ctx.beginPath();
    ctx.moveTo(gx, pad.top);
    ctx.lineTo(gx, height - pad.bottom);
    ctx.stroke();
  }
  
  // 水平网格线 + Y轴刻度
  for (var i = 0; i <= yGridCount; i++) {
    var yv = yMin + (yMax - yMin) * i / yGridCount;
    var gy = toY(yv);
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(width - pad.right, gy);
    ctx.stroke();
  }
  
  ctx.setLineDash([]);
  
  // ===== 坐标轴（实线，白色稍亮） =====
  ctx.strokeStyle = 'rgba(255,255,255,0.45)';
  ctx.lineWidth = 1;
  
  // X轴（y=0 如果在范围内）
  var showXAxis = (yMin < 0 && yMax > 0);
  var y0 = showXAxis ? toY(0) : height - pad.bottom;
  ctx.beginPath();
  ctx.moveTo(pad.left, y0);
  ctx.lineTo(width - pad.right, y0);
  ctx.stroke();
  
  // Y轴（x=0 如果在范围内）
  var showYAxis = (xMin < 0 && xMax > 0);
  var x0 = showYAxis ? toX(0) : pad.left;
  ctx.beginPath();
  ctx.moveTo(x0, pad.top);
  ctx.lineTo(x0, height - pad.bottom);
  ctx.stroke();
  
  // X轴箭头
  ctx.beginPath();
  ctx.moveTo(width - pad.right, y0);
  ctx.lineTo(width - pad.right - 5, y0 - 3);
  ctx.lineTo(width - pad.right - 5, y0 + 3);
  ctx.closePath();
  ctx.fillStyle = 'rgba(255,255,255,0.45)';
  ctx.fill();
  
  // Y轴箭头
  ctx.beginPath();
  ctx.moveTo(x0, pad.top);
  ctx.lineTo(x0 - 3, pad.top + 5);
  ctx.lineTo(x0 + 3, pad.top + 5);
  ctx.closePath();
  ctx.fill();
  
  // ===== 刻度标签 =====
  ctx.fillStyle = 'rgba(255,255,255,0.5)';
  ctx.font = '10px monospace';
  
  // X轴刻度
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (var i = 0; i <= xGridCount; i++) {
    var xv = xMin + (xMax - xMin) * i / xGridCount;
    var gx = toX(xv);
    
    // 刻度小短线
    ctx.beginPath();
    ctx.moveTo(gx, y0);
    ctx.lineTo(gx, y0 + 3);
    ctx.strokeStyle = 'rgba(255,255,255,0.45)';
    ctx.stroke();
    
    // 标签
    var label;
    var isTrig = (funcInfo.fn === 'Math.sin' || funcInfo.fn === 'Math.cos' || funcInfo.fn === 'Math.tan');
    if (isTrig) {
      var piVal = xv / Math.PI;
      if (Math.abs(piVal) < 0.02) label = '0';
      else if (Math.abs(piVal - 1) < 0.02) label = 'π';
      else if (Math.abs(piVal + 1) < 0.02) label = '-π';
      else if (Math.abs(piVal - 2) < 0.02) label = '2π';
      else if (Math.abs(piVal + 2) < 0.02) label = '-2π';
      else if (Math.abs(piVal - 0.5) < 0.02) label = 'π/2';
      else if (Math.abs(piVal + 0.5) < 0.02) label = '-π/2';
      else continue;
    } else {
      if (Math.abs(xv) < 0.01) label = '0';
      else label = xv.toFixed(1);
    }
    
    // 如果刻度在0附近且y轴可见，跳过（避免和原点重复）
    if (showYAxis && Math.abs(xv) < (xMax - xMin) / xGridCount * 0.3) continue;
    
    ctx.fillText(label, gx, y0 + 5);
  }
  
  // Y轴刻度
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (var i = 0; i <= yGridCount; i++) {
    var yv = yMin + (yMax - yMin) * i / yGridCount;
    var gy = toY(yv);
    
    // 跳过0点（原点已由X轴处理）
    if (showXAxis && Math.abs(yv) < (yMax - yMin) / yGridCount * 0.3) continue;
    
    // 刻度小短线
    ctx.beginPath();
    ctx.moveTo(x0, gy);
    ctx.lineTo(x0 - 3, gy);
    ctx.strokeStyle = 'rgba(255,255,255,0.45)';
    ctx.stroke();
    
    // 标签
    var ylabel;
    if (Math.abs(yv) < 0.01) ylabel = '0';
    else ylabel = yv.toFixed(1);
    
    ctx.fillText(ylabel, x0 - 5, gy);
  }
  
  // ===== 函数曲线（白色实线） =====
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  var started = false;
  var steps = 600;
  
  var prevY = null;
  for (var i = 0; i <= steps; i++) {
    var x = xMin + (xMax - xMin) * i / steps;
    var y = 0;
    
    try {
      if (funcInfo.fn === 'Math.sin') y = funcInfo.amp * Math.sin(funcInfo.freq * x);
      else if (funcInfo.fn === 'Math.cos') y = funcInfo.amp * Math.cos(funcInfo.freq * x);
      else if (funcInfo.fn === 'Math.tan') y = funcInfo.amp * Math.tan(funcInfo.freq * x);
      else if (funcInfo.poly) y = Math.pow(x, funcInfo.power);
      else if (funcInfo.spec === 'reciprocal') y = 1 / x;
      else if (funcInfo.spec === 'exp') y = Math.exp(x);
      else if (funcInfo.spec === 'ln') y = Math.log(x);
      else if (funcInfo.spec === 'sqrt') y = Math.sqrt(x);
      else if (funcInfo.linear) y = funcInfo.slope * x + funcInfo.intercept;
      else continue;
    } catch(e) { started = false; prevY = null; continue; }
    
    if (typeof y !== 'number' || !isFinite(y)) { started = false; prevY = null; continue; }
    
    // 防止tan等函数在渐近线处画穿
    if (prevY !== null && Math.abs(y - prevY) > (yMax - yMin) * 0.5) {
      started = false;
    }
    
    var cx = toX(x), cy = toY(y);
    
    // 超出绘图区域时断开
    if (cy < pad.top - 5 || cy > height - pad.bottom + 5) {
      started = false;
      prevY = null;
      continue;
    }
    
    if (!started) {
      ctx.moveTo(cx, cy);
      started = true;
    } else {
      ctx.lineTo(cx, cy);
    }
    prevY = y;
  }
  ctx.stroke();
  
  // X轴标签（右下角）
  ctx.fillStyle = 'rgba(255,255,255,0.4)';
  ctx.font = '10px serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'top';
  ctx.fillText('x', width - pad.right + 2, y0 + 5);
  
  // Y轴标签（左上角）
  ctx.textAlign = 'left';
  ctx.textBaseline = 'bottom';
  ctx.fillText('y', x0 + 5, pad.top - 2);
}

// ===== 柱状图渲染器 =====
function renderBarChart(containerId, data, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  // ★ 解析结构化数据 {labels, values}，兼容旧格式（纯数组）和默认数据
  var sampleData, labels;
  if (data && typeof data === 'object' && !Array.isArray(data) && data.values) {
    sampleData = data.values;
    labels = data.labels || [];
    while (labels.length < sampleData.length) labels.push('项' + (labels.length + 1));
  } else if (data && Array.isArray(data) && data.length > 0) {
    sampleData = data;
    labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'];
    if (sampleData.length <= 5) labels = ['A','B','C','D','E'];
  } else {
    sampleData = [12, 28, 8, 35, 18, 22, 15];
    labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'];
    if (sampleData.length <= 5) labels = ['A','B','C','D','E'];
  }
  
  // ★ 白线风格：统一白色线框、无背景、紧凑尺寸
  var html = '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;padding-left:2px;">'
           + '<span style="font-size:12px;color:rgba(255,255,255,0.7);font-family:sans-serif;font-weight:500;">' + (name || '柱状图') + '</span>'
           + '</div>';
  html += '<canvas id="' + containerId + '_canvas" style="width:100%;height:150px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 150 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 150;
  
  var pad = {top: 10, right: 12, bottom: 24, left: 32};
  var plotW = W - pad.left - pad.right, plotH = H - pad.top - pad.bottom;
  var n = sampleData.length;
  var maxVal = Math.max.apply(null, sampleData) * 1.2;
  if (maxVal < 1) maxVal = 1;
  var barW = plotW / n * 0.55;
  var gap = plotW / n * 0.45;
  
  // ★ 白线风格：网格线用淡白色
  ctx.strokeStyle = 'rgba(255,255,255,0.1)';
  ctx.lineWidth = 1;
  for (var i = 0; i <= 4; i++) {
    var gy = pad.top + i * plotH / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(W - pad.right, gy);
    ctx.stroke();
    var val = Math.round(maxVal - (maxVal / 4) * i);
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '9px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(val, pad.left - 6, gy);
  }
  
  // ★ X轴线（白色）
  ctx.strokeStyle = 'rgba(255,255,255,0.5)';
  ctx.lineWidth = 1;
  var yBase = pad.top + plotH;
  ctx.beginPath();
  ctx.moveTo(pad.left, yBase);
  ctx.lineTo(W - pad.right, yBase);
  ctx.stroke();
  
  // ★ 柱体：白色线框（无填充）
  for (var i = 0; i < n; i++) {
    var x = pad.left + i * (plotW / n) + gap / 2;
    var h = (sampleData[i] / maxVal) * plotH;
    var y = yBase - h;
    
    // 白色线框
    ctx.strokeStyle = 'rgba(255,255,255,0.75)';
    ctx.lineWidth = 1.2;
    ctx.strokeRect(x, y, barW, h);
    
    // 底部标签
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.font = '9px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(labels[i] || '', x + barW/2, yBase + 6);
    
    // 顶部数值
    ctx.fillStyle = 'rgba(255,255,255,0.8)';
    ctx.font = 'bold 9px sans-serif';
    ctx.fillText(sampleData[i].toString(), x + barW/2, y - 12);
  }
}

// ===== 折线图渲染器 =====
function renderLineChart(containerId, data, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  // ★ 解析结构化数据 {labels, values}，兼容旧格式（纯数组）和默认数据
  var sampleData, labels;
  if (data && typeof data === 'object' && !Array.isArray(data) && data.values) {
    sampleData = data.values;
    labels = data.labels || [];
    while (labels.length < sampleData.length) labels.push('项' + (labels.length + 1));
  } else if (data && Array.isArray(data) && data.length > 0) {
    sampleData = data;
    labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'];
  } else {
    sampleData = [10, 25, 15, 30, 20, 28, 18];
    labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'];
  }
  
  // ★ 白线风格
  var html = '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;padding-left:2px;">'
           + '<span style="font-size:12px;color:rgba(255,255,255,0.7);font-family:sans-serif;font-weight:500;">' + (name || '折线图') + '</span>'
           + '</div>';
  html += '<canvas id="' + containerId + '_canvas" style="width:100%;height:150px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 150 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 150;
  
  var pad = {top: 10, right: 12, bottom: 24, left: 32};
  var plotW = W - pad.left - pad.right, plotH = H - pad.top - pad.bottom;
  var n = sampleData.length;
  var maxVal = Math.max.apply(null, sampleData) * 1.2;
  if (maxVal < 1) maxVal = 1;
  
  // ★ 白线风格：网格线
  ctx.strokeStyle = 'rgba(255,255,255,0.1)';
  ctx.lineWidth = 1;
  for (var i = 0; i <= 4; i++) {
    var gy = pad.top + i * plotH / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(W - pad.right, gy);
    ctx.stroke();
    var val = Math.round(maxVal - (maxVal / 4) * i);
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '9px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(val, pad.left - 6, gy);
  }
  
  // ★ X轴线（白色）
  ctx.strokeStyle = 'rgba(255,255,255,0.5)';
  ctx.lineWidth = 1;
  var yBase = pad.top + plotH;
  ctx.beginPath();
  ctx.moveTo(pad.left, yBase);
  ctx.lineTo(W - pad.right, yBase);
  ctx.stroke();
  
  // 计算数据点坐标
  var points = [];
  for (var i = 0; i < n; i++) {
    var x = pad.left + (i + 0.5) * (plotW / n);
    var y = yBase - (sampleData[i] / maxVal) * plotH;
    points.push({ x: x, y: y });
  }
  
  // ★ 白线风格：折线（白色细线，无填充区域）
  ctx.strokeStyle = 'rgba(255,255,255,0.85)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (var i = 0; i < n; i++) {
    if (i === 0) ctx.moveTo(points[i].x, points[i].y);
    else ctx.lineTo(points[i].x, points[i].y);
  }
  ctx.stroke();
  
  // ★ 数据点（白色小圆点）
  for (var i = 0; i < n; i++) {
    ctx.beginPath();
    ctx.arc(points[i].x, points[i].y, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,255,255,0.9)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.5)';
    ctx.lineWidth = 1;
    ctx.stroke();
    
    // 底部标签
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.font = '9px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(labels[i] || '', points[i].x, yBase + 6);
    
    // 顶部数值
    ctx.fillStyle = 'rgba(255,255,255,0.8)';
    ctx.font = 'bold 9px sans-serif';
    ctx.fillText(sampleData[i].toString(), points[i].x, points[i].y - 12);
  }
}

// ===== 散点图渲染器 =====
function renderScatterPlot(containerId, data, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  // ★ 解析结构化数据 {labels, values}，兼容旧格式和默认数据
  var points;
  if (data && typeof data === 'object' && !Array.isArray(data) && data.values) {
    var vals = data.values;
    var labs = data.labels || [];
    points = [];
    for (var pi = 0; pi < vals.length; pi++) {
      var xVal = pi + 1;
      if (labs[pi] !== undefined) {
        var parsed = parseFloat(labs[pi]);
        if (!isNaN(parsed)) xVal = parsed;
      }
      points.push([xVal, vals[pi]]);
    }
  } else {
    points = [
      [1,3], [2,5], [3,4], [4,7], [5,6], [6,8], [7,5], [8,7], [9,9], [10,6],
      [1.5,2], [2.5,6], [3.5,5], [4.5,8], [5.5,7], [6.5,9], [7.5,6], [8.5,8]
    ];
  }
  
  // ★ 白线风格
  var html = '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;padding-left:2px;">'
           + '<span style="font-size:12px;color:rgba(255,255,255,0.7);font-family:sans-serif;font-weight:500;">' + (name || '散点图') + '</span>'
           + '</div>';
  html += '<canvas id="' + containerId + '_canvas" style="width:100%;height:150px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 150 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 150;
  
  var pad = {top: 10, right: 12, bottom: 24, left: 32};
  var plotW = W - pad.left - pad.right, plotH = H - pad.top - pad.bottom;
  
  var xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
  for (var pi2 = 0; pi2 < points.length; pi2++) {
    if (points[pi2][0] < xMin) xMin = points[pi2][0];
    if (points[pi2][0] > xMax) xMax = points[pi2][0];
    if (points[pi2][1] < yMin) yMin = points[pi2][1];
    if (points[pi2][1] > yMax) yMax = points[pi2][1];
  }
  var xRange = xMax - xMin || 1;
  var yRange = yMax - yMin || 1;
  xMin -= xRange * 0.1; xMax += xRange * 0.1;
  yMin -= yRange * 0.1; yMax += yRange * 0.1;
  if (xMin > 0) xMin = 0;
  if (yMin > 0) yMin = 0;
  
  // ★ 白线风格：网格线
  ctx.strokeStyle = 'rgba(255,255,255,0.1)';
  ctx.lineWidth = 1;
  for (var i = 0; i <= 4; i++) {
    var gy = pad.top + i * plotH / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(W - pad.right, gy);
    ctx.stroke();
    var val = Math.round(yMax - (yMax / 4) * i);
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '9px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(val, pad.left - 6, gy);
  }
  
  // ★ X轴（白色）
  ctx.strokeStyle = 'rgba(255,255,255,0.5)';
  ctx.lineWidth = 1;
  var yBase = pad.top + plotH;
  ctx.beginPath();
  ctx.moveTo(pad.left, yBase);
  ctx.lineTo(W - pad.right, yBase);
  ctx.stroke();
  
  function toX(v) { return pad.left + (v - xMin) / (xMax - xMin) * plotW; }
  function toY(v) { return pad.top + (1 - (v - yMin) / (yMax - yMin)) * plotH; }
  
  // ★ 白线风格：散点（白色小圆点）
  for (var i = 0; i < points.length; i++) {
    var cx = toX(points[i][0]), cy = toY(points[i][1]);
    ctx.beginPath();
    ctx.arc(cx, cy, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.4)';
    ctx.lineWidth = 1;
    ctx.stroke();
  }
  
  // X轴刻度
  ctx.fillStyle = 'rgba(255,255,255,0.5)';
  ctx.font = '9px monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  var xStep = (xMax - xMin) / 5 || 1;
  for (var i = 0; i <= 5; i++) {
    var tickVal = xMin + i * xStep;
    ctx.fillText(Math.round(tickVal * 100) / 100, toX(tickVal), yBase + 6);
  }
}

// ===== 饼图渲染器（白线风格） =====
function renderPieChart(containerId, data, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  // ★ 解析结构化数据 {labels, values}，兼容旧格式和默认数据
  var values, labels;
  if (data && typeof data === 'object' && !Array.isArray(data) && data.values) {
    values = data.values;
    labels = data.labels || [];
    while (labels.length < values.length) labels.push('类别' + (labels.length + 1));
  } else {
    values = [30, 25, 20, 15, 10];
    labels = ['Electronics', 'Laptops', 'iPhones', 'Accessories', 'Others'];
  }
  
  // ★ 白线风格
  var html = '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;padding-left:2px;">'
           + '<span style="font-size:12px;color:rgba(255,255,255,0.7);font-family:sans-serif;font-weight:500;">' + (name || '占比图') + '</span>'
           + '</div>';
  html += '<canvas id="' + containerId + '_canvas" style="width:100%;height:160px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 160 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 160;
  
  var cx = W * 0.38, cy = H / 2 + 5;
  var outerR = Math.min(W * 0.32, H * 0.42);
  var innerR = outerR * 0.6;
  var total = values.reduce(function(a,b) { return a + b; }, 0);
  var startAngle = -Math.PI / 2;
  
  // ★ 白线风格：画环形扇区（白色线框，无填充）
  for (var i = 0; i < values.length; i++) {
    var sliceAngle = (values[i] / total) * 2 * Math.PI;
    var endAngle = startAngle + sliceAngle;
    
    // 白色线框扇区
    ctx.beginPath();
    ctx.arc(cx, cy, outerR, startAngle, endAngle);
    ctx.arc(cx, cy, innerR, endAngle, startAngle, true);
    ctx.closePath();
    ctx.strokeStyle = 'rgba(255,255,255,0.75)';
    ctx.lineWidth = 1.2;
    ctx.stroke();
    
    // 分隔线（从中心向外）
    var midAngle = startAngle;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(midAngle) * innerR, cy + Math.sin(midAngle) * innerR);
    ctx.lineTo(cx + Math.cos(midAngle) * outerR, cy + Math.sin(midAngle) * outerR);
    ctx.strokeStyle = 'rgba(255,255,255,0.4)';
    ctx.lineWidth = 0.8;
    ctx.stroke();
    
    startAngle = endAngle;
  }
  
  // 中心文字
  ctx.fillStyle = 'rgba(255,255,255,0.85)';
  ctx.font = 'bold 13px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(total.toString(), cx, cy - 4);
  ctx.fillStyle = 'rgba(255,255,255,0.5)';
  ctx.font = '9px sans-serif';
  ctx.fillText('Total', cx, cy + 10);
  
  // ★ 右侧图例（白线风格）
  var legendX = W * 0.66;
  var legendY = H / 2 - (values.length * 16) / 2;
  for (var i = 0; i < values.length; i++) {
    // 白色线框方块（无填充）
    ctx.strokeStyle = 'rgba(255,255,255,0.7)';
    ctx.lineWidth = 1;
    ctx.strokeRect(legendX, legendY + i * 16, 10, 10);
    
    // 标签
    ctx.fillStyle = 'rgba(255,255,255,0.7)';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(labels[i] || ('类别' + (i+1)), legendX + 16, legendY + i * 16 + 5);
    
    // 百分比
    var pct = Math.round(values[i] / total * 100) + '%';
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.font = 'bold 10px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(pct, W - 10, legendY + i * 16 + 5);
  }
}

// ===== 3D曲面渲染器（2D Canvas 投影） =====
function render3DSurface(containerId, data, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  var html = '<div style="text-align:center;font-size:15px;color:#ffffff;font-family:serif;margin-bottom:2px;">' + (name || '3D曲面') + '</div>';
  html += '<canvas id="' + containerId + '_canvas" style="width:100%;height:160px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 160 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 160;
  
  var cx = W / 2, cy = H / 2 + 10;
  var scale = Math.min(W, H) * 0.35;
  var gridSize = 16;
  var viewAngleX = 0.5, viewAngleY = -0.6;
  
  function f(x, y) {
    return Math.sin(Math.sqrt(x*x + y*y)) * 0.8;
  }
  
  function project(x, y, z) {
    var rx = x * Math.cos(viewAngleY) + z * Math.sin(viewAngleY);
    var ry = x * Math.sin(viewAngleX) * Math.sin(viewAngleY) + y * Math.cos(viewAngleX) - z * Math.sin(viewAngleX) * Math.cos(viewAngleY);
    var rz = -x * Math.cos(viewAngleX) * Math.sin(viewAngleY) + y * Math.sin(viewAngleX) + z * Math.cos(viewAngleX) * Math.cos(viewAngleY);
    return { sx: cx + rx * scale, sy: cy - rz * scale };
  }
  
  var range = 4;
  var step = range / gridSize;
  
  // 从后往前绘制网格线
  for (var i = -gridSize; i <= gridSize; i++) {
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    var started = false;
    for (var j = -gridSize; j <= gridSize; j++) {
      var x = i * step, y = j * step;
      var z = f(x, y);
      var p = project(x, y, z);
      if (!started) { ctx.moveTo(p.sx, p.sy); started = true; }
      else ctx.lineTo(p.sx, p.sy);
    }
    ctx.stroke();
  }
  for (var j = -gridSize; j <= gridSize; j++) {
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    var started = false;
    for (var i = -gridSize; i <= gridSize; i++) {
      var x = i * step, y = j * step;
      var z = f(x, y);
      var p = project(x, y, z);
      if (!started) { ctx.moveTo(p.sx, p.sy); started = true; }
      else ctx.lineTo(p.sx, p.sy);
    }
    ctx.stroke();
  }
  
  // 标题
  ctx.fillStyle = 'rgba(255,255,255,0.4)';
  ctx.font = '10px serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  ctx.fillText('z = sin(√(x²+y²))', cx, H - 2);
}

// ===== 3D 几何体公共工具函数 =====
function _dispatchGeom(containerId, subtype, name) {
  if (subtype === 'cube') renderCube(containerId, name);
  else if (subtype === 'cuboid') renderCuboid(containerId, name);
  else if (subtype === 'cylinder') renderCylinder(containerId, name);
  else if (subtype === 'cone') renderCone(containerId, name);
  else if (subtype === 'sphere') renderSphere(containerId, name);
  else if (subtype === 'ellipsoid') renderEllipsoid(containerId, name);
  else if (subtype === 'pyramid3') renderTetrahedron(containerId, name);
  else if (subtype === 'pyramid4') renderPyramid4(containerId, name);
  else if (subtype === 'prism3') renderTriangularPrism(containerId, name);
  else renderCube(containerId, name);
}

function _geomProject(px, py, pz, cx, cy, scale, rotX, rotY) {
  // 绕Y轴旋转
  var cosY = Math.cos(rotY), sinY = Math.sin(rotY);
  var x1 = px * cosY + pz * sinY;
  var z1 = -px * sinY + pz * cosY;
  var y1 = py;
  // 绕X轴旋转
  var cosX = Math.cos(rotX), sinX = Math.sin(rotX);
  var y2 = y1 * cosX - z1 * sinX;
  var z2 = y1 * sinX + z1 * cosX;
  return { x: cx + x1 * scale, y: cy - y2 * scale, z: z2 };
}

function _drawGeomTitle(canvas, ctx, title, H) {
  ctx.fillStyle = 'rgba(255,255,255,0.6)';
  ctx.font = '14px serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText(title, canvas.offsetWidth / 2, 4);
}

function _drawGeomEdges(ctx, vertices, edges, rotX, rotY, cx, cy, scale) {
  for (var i = 0; i < edges.length; i++) {
    var v1 = vertices[edges[i][0]];
    var v2 = vertices[edges[i][1]];
    var p1 = _geomProject(v1[0], v1[1], v1[2], cx, cy, scale, rotX, rotY);
    var p2 = _geomProject(v2[0], v2[1], v2[2], cx, cy, scale, rotX, rotY);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  }
}

function _drawGeomVertices(ctx, vertices, rotX, rotY, cx, cy, scale) {
  for (var i = 0; i < vertices.length; i++) {
    var p = _geomProject(vertices[i][0], vertices[i][1], vertices[i][2], cx, cy, scale, rotX, rotY);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2);
    ctx.fill();
  }
}

// ===== 正方体渲染器 =====
function renderCube(containerId, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  var html = '<canvas id="' + containerId + '_canvas" style="width:100%;height:160px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 160 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 160;
  var cx = W / 2, cy = H / 2 + 8, scale = Math.min(W, H) * 0.28;
  
  var rotX = 0.5, rotY = -0.6;
  var s = 1;
  var vertices = [
    [-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
    [-s, -s, s],  [s, -s, s],  [s, s, s],  [-s, s, s]
  ];
  var edges = [
    [0,1],[1,2],[2,3],[3,0],
    [4,5],[5,6],[6,7],[7,4],
    [0,4],[1,5],[2,6],[3,7]
  ];
  
  ctx.strokeStyle = 'rgba(255,255,255,0.75)';
  ctx.lineWidth = 1;
  _drawGeomEdges(ctx, vertices, edges, rotX, rotY, cx, cy, scale);
  
  // 顶点
  ctx.fillStyle = 'rgba(255,255,255,0.9)';
  _drawGeomVertices(ctx, vertices, rotX, rotY, cx, cy, scale);
  
  _drawGeomTitle(canvas, ctx, name || '正方体', H);
}

// ===== 长方体渲染器 =====
function renderCuboid(containerId, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  var html = '<canvas id="' + containerId + '_canvas" style="width:100%;height:160px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 160 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 160;
  var cx = W / 2, cy = H / 2 + 8, scale = Math.min(W, H) * 0.26;
  
  var rotX = 0.5, rotY = -0.6;
  var a = 1.2, b = 0.7, c = 0.9;
  var vertices = [
    [-a, -b, -c], [a, -b, -c], [a, b, -c], [-a, b, -c],
    [-a, -b, c],  [a, -b, c],  [a, b, c],  [-a, b, c]
  ];
  var edges = [
    [0,1],[1,2],[2,3],[3,0],
    [4,5],[5,6],[6,7],[7,4],
    [0,4],[1,5],[2,6],[3,7]
  ];
  
  ctx.strokeStyle = 'rgba(255,255,255,0.75)';
  ctx.lineWidth = 1;
  _drawGeomEdges(ctx, vertices, edges, rotX, rotY, cx, cy, scale);
  
  ctx.fillStyle = 'rgba(255,255,255,0.9)';
  _drawGeomVertices(ctx, vertices, rotX, rotY, cx, cy, scale);
  
  _drawGeomTitle(canvas, ctx, name || '长方体', H);
}

// ===== 圆柱体渲染器 =====
function renderCylinder(containerId, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  var html = '<canvas id="' + containerId + '_canvas" style="width:100%;height:170px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 170 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 170;
  var cx = W / 2, cy = H / 2 + 10, scale = Math.min(W, H) * 0.28;
  
  var rotX = 0.45, rotY = -0.5;
  var r = 1, h = 1.3, segs = 24;
  var topPts = [], botPts = [];
  for (var i = 0; i < segs; i++) {
    var a = (i / segs) * Math.PI * 2;
    topPts.push([r * Math.cos(a), h, r * Math.sin(a)]);
    botPts.push([r * Math.cos(a), -h, r * Math.sin(a)]);
  }
  
  ctx.strokeStyle = 'rgba(255,255,255,0.75)';
  ctx.lineWidth = 1;
  
  // 上下底椭圆
  ctx.beginPath();
  for (var i = 0; i <= segs; i++) {
    var p = _geomProject(topPts[i % segs][0], topPts[i % segs][1], topPts[i % segs][2], cx, cy, scale, rotX, rotY);
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  }
  ctx.stroke();
  ctx.beginPath();
  for (var i = 0; i <= segs; i++) {
    var p = _geomProject(botPts[i % segs][0], botPts[i % segs][1], botPts[i % segs][2], cx, cy, scale, rotX, rotY);
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  }
  ctx.stroke();
  
  // 母线（每4条显示1条，避免太密）
  for (var i = 0; i < segs; i += 3) {
    var p1 = _geomProject(topPts[i][0], topPts[i][1], topPts[i][2], cx, cy, scale, rotX, rotY);
    var p2 = _geomProject(botPts[i][0], botPts[i][1], botPts[i][2], cx, cy, scale, rotX, rotY);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  }
  
  _drawGeomTitle(canvas, ctx, name || '圆柱体', H);
}

// ===== 圆锥体渲染器 =====
function renderCone(containerId, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  var html = '<canvas id="' + containerId + '_canvas" style="width:100%;height:170px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 170 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 170;
  var cx = W / 2, cy = H / 2 + 12, scale = Math.min(W, H) * 0.28;
  
  var rotX = 0.45, rotY = -0.5;
  var r = 1, h = 1.4, segs = 24;
  var apex = [0, h, 0];
  var basePts = [];
  for (var i = 0; i < segs; i++) {
    var a = (i / segs) * Math.PI * 2;
    basePts.push([r * Math.cos(a), -h * 0.2, r * Math.sin(a)]);
  }
  
  ctx.strokeStyle = 'rgba(255,255,255,0.75)';
  ctx.lineWidth = 1;
  
  // 底面椭圆
  ctx.beginPath();
  for (var i = 0; i <= segs; i++) {
    var p = _geomProject(basePts[i % segs][0], basePts[i % segs][1], basePts[i % segs][2], cx, cy, scale, rotX, rotY);
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  }
  ctx.stroke();
  
  // 母线（每4条显示1条）
  var apexP = _geomProject(apex[0], apex[1], apex[2], cx, cy, scale, rotX, rotY);
  for (var i = 0; i < segs; i += 3) {
    var bp = _geomProject(basePts[i][0], basePts[i][1], basePts[i][2], cx, cy, scale, rotX, rotY);
    ctx.beginPath();
    ctx.moveTo(apexP.x, apexP.y);
    ctx.lineTo(bp.x, bp.y);
    ctx.stroke();
  }
  
  // 顶点
  ctx.fillStyle = 'rgba(255,255,255,0.9)';
  ctx.beginPath();
  ctx.arc(apexP.x, apexP.y, 2.5, 0, Math.PI * 2);
  ctx.fill();
  
  _drawGeomTitle(canvas, ctx, name || '圆锥体', H);
}

// ===== 球体渲染器 =====
function renderSphere(containerId, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  var html = '<canvas id="' + containerId + '_canvas" style="width:100%;height:170px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 170 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 170;
  var cx = W / 2, cy = H / 2 + 10, scale = Math.min(W, H) * 0.32;
  
  var rotX = 0.4, rotY = -0.5;
  var r = 1, latSegs = 8, lonSegs = 16;
  
  ctx.strokeStyle = 'rgba(255,255,255,0.5)';
  ctx.lineWidth = 0.8;
  
  // 纬线（水平圈）
  for (var lat = 1; lat < latSegs; lat++) {
    var phi = (lat / latSegs) * Math.PI;
    ctx.beginPath();
    for (var lon = 0; lon <= lonSegs; lon++) {
      var theta = (lon / lonSegs) * Math.PI * 2;
      var px = r * Math.sin(phi) * Math.cos(theta);
      var py = r * Math.cos(phi);
      var pz = r * Math.sin(phi) * Math.sin(theta);
      var p = _geomProject(px, py, pz, cx, cy, scale, rotX, rotY);
      if (lon === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
  }
  
  // 经线（垂直圈）
  for (var lon = 0; lon < lonSegs; lon += 2) {
    var theta = (lon / lonSegs) * Math.PI * 2;
    ctx.beginPath();
    for (var lat = 0; lat <= latSegs; lat++) {
      var phi = (lat / latSegs) * Math.PI;
      var px = r * Math.sin(phi) * Math.cos(theta);
      var py = r * Math.cos(phi);
      var pz = r * Math.sin(phi) * Math.sin(theta);
      var p = _geomProject(px, py, pz, cx, cy, scale, rotX, rotY);
      if (lat === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
  }
  
  // 外轮廓（大圆）
  ctx.strokeStyle = 'rgba(255,255,255,0.8)';
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.arc(cx, cy, r * scale, 0, Math.PI * 2);
  ctx.stroke();
  
  _drawGeomTitle(canvas, ctx, name || '球体', H);
}

// ===== 椭球体渲染器 =====
function renderEllipsoid(containerId, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  var html = '<canvas id="' + containerId + '_canvas" style="width:100%;height:170px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 170 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 170;
  var cx = W / 2, cy = H / 2 + 10, scale = Math.min(W, H) * 0.28;
  
  var rotX = 0.4, rotY = -0.5;
  var a = 1.2, b = 0.7, c = 0.9, latSegs = 8, lonSegs = 16;
  
  ctx.strokeStyle = 'rgba(255,255,255,0.5)';
  ctx.lineWidth = 0.8;
  
  // 纬线
  for (var lat = 1; lat < latSegs; lat++) {
    var phi = (lat / latSegs) * Math.PI;
    ctx.beginPath();
    for (var lon = 0; lon <= lonSegs; lon++) {
      var theta = (lon / lonSegs) * Math.PI * 2;
      var px = a * Math.sin(phi) * Math.cos(theta);
      var py = b * Math.cos(phi);
      var pz = c * Math.sin(phi) * Math.sin(theta);
      var p = _geomProject(px, py, pz, cx, cy, scale, rotX, rotY);
      if (lon === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
  }
  
  // 经线
  for (var lon = 0; lon < lonSegs; lon += 2) {
    var theta = (lon / lonSegs) * Math.PI * 2;
    ctx.beginPath();
    for (var lat = 0; lat <= latSegs; lat++) {
      var phi = (lat / latSegs) * Math.PI;
      var px = a * Math.sin(phi) * Math.cos(theta);
      var py = b * Math.cos(phi);
      var pz = c * Math.sin(phi) * Math.sin(theta);
      var p = _geomProject(px, py, pz, cx, cy, scale, rotX, rotY);
      if (lat === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
  }
  
  _drawGeomTitle(canvas, ctx, name || '椭球体', H);
}

// ===== 三棱锥（四面体）渲染器 =====
function renderTetrahedron(containerId, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  var html = '<canvas id="' + containerId + '_canvas" style="width:100%;height:170px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 170 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 170;
  var cx = W / 2, cy = H / 2 + 12, scale = Math.min(W, H) * 0.32;
  
  var rotX = 0.35, rotY = -0.5;
  var s = 1, h = s * Math.sqrt(2/3);
  var vertices = [
    [0, h, 0],
    [-s * Math.sqrt(3)/3, -h/3, s/3],
    [s * Math.sqrt(3)/3, -h/3, s/3],
    [0, -h/3, -s * 2/3]
  ];
  var edges = [[0,1],[0,2],[0,3],[1,2],[2,3],[3,1]];
  
  ctx.strokeStyle = 'rgba(255,255,255,0.75)';
  ctx.lineWidth = 1;
  _drawGeomEdges(ctx, vertices, edges, rotX, rotY, cx, cy, scale);
  
  ctx.fillStyle = 'rgba(255,255,255,0.9)';
  _drawGeomVertices(ctx, vertices, rotX, rotY, cx, cy, scale);
  
  _drawGeomTitle(canvas, ctx, name || '三棱锥', H);
}

// ===== 四棱锥渲染器 =====
function renderPyramid4(containerId, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  var html = '<canvas id="' + containerId + '_canvas" style="width:100%;height:170px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 170 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 170;
  var cx = W / 2, cy = H / 2 + 12, scale = Math.min(W, H) * 0.3;
  
  var rotX = 0.4, rotY = -0.6;
  var s = 1, h = 1.2;
  var vertices = [
    [0, h, 0],
    [-s, -h*0.3, -s], [s, -h*0.3, -s], [s, -h*0.3, s], [-s, -h*0.3, s]
  ];
  var edges = [[0,1],[0,2],[0,3],[0,4],[1,2],[2,3],[3,4],[4,1]];
  
  ctx.strokeStyle = 'rgba(255,255,255,0.75)';
  ctx.lineWidth = 1;
  _drawGeomEdges(ctx, vertices, edges, rotX, rotY, cx, cy, scale);
  
  ctx.fillStyle = 'rgba(255,255,255,0.9)';
  _drawGeomVertices(ctx, vertices, rotX, rotY, cx, cy, scale);
  
  _drawGeomTitle(canvas, ctx, name || '四棱锥', H);
}

// ===== 三棱柱渲染器 =====
function renderTriangularPrism(containerId, name) {
  var container = document.getElementById(containerId);
  if (!container) return;
  container.style.cssText = 'margin: 6px 0; padding: 0; width: 100%; max-width: 420px;';
  
  var html = '<canvas id="' + containerId + '_canvas" style="width:100%;height:170px;display:block;"></canvas>';
  container.innerHTML = html;
  
  var canvas = document.getElementById(containerId + '_canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  canvas.width = canvas.offsetWidth * 2; canvas.height = 170 * 2;
  ctx.scale(2, 2);
  var W = canvas.offsetWidth, H = 170;
  var cx = W / 2, cy = H / 2 + 10, scale = Math.min(W, H) * 0.3;
  
  var rotX = 0.4, rotY = -0.5;
  var s = 1, h = 1;
  var topY = h, botY = -h;
  var triH = s * Math.sqrt(3) / 2;
  var vertices = [
    // 上底
    [-s, topY, -triH/3],
    [s, topY, -triH/3],
    [0, topY, triH*2/3],
    // 下底
    [-s, botY, -triH/3],
    [s, botY, -triH/3],
    [0, botY, triH*2/3],
  ];
  var edges = [
    [0,1],[1,2],[2,0],
    [3,4],[4,5],[5,3],
    [0,3],[1,4],[2,5]
  ];
  
  ctx.strokeStyle = 'rgba(255,255,255,0.75)';
  ctx.lineWidth = 1;
  _drawGeomEdges(ctx, vertices, edges, rotX, rotY, cx, cy, scale);
  
  ctx.fillStyle = 'rgba(255,255,255,0.9)';
  _drawGeomVertices(ctx, vertices, rotX, rotY, cx, cy, scale);
  
  _drawGeomTitle(canvas, ctx, name || '三棱柱', H);
}
window._appendMsg = appendMsg;

// 思考完成时更新标签（现在嵌入在对话流中）
window.mimoAgent.hideThinking = function() {
  var area = document.getElementById('outputMessages');
  if (!area) return;
  var thinkInline = area.querySelector('.thinking-inline');
  if (thinkInline) {
    var summary = thinkInline.querySelector('.think-summary');
    if (summary) summary.innerHTML = SVG_ICONS.check + ' 完成';
    // 3秒后自动收起
    setTimeout(function() {
      if (!thinkInline.classList.contains('collapsed')) {
        thinkInline.classList.add('collapsed');
      }
    }, 3000);
  }
};

// ===== 滚动管理 =====
var _autoScroll = true;

// ★ 安全滚动函数：仅在 _autoScroll 为 true 时滚动
function safeScrollToBottom(area) {
  if (!area) area = document.getElementById('outputMessages');
  if (!area) return;
  if (_autoScroll) {
    area.scrollTop = area.scrollHeight;
  }
}

function scrollToBottom() {
  var area = document.getElementById('outputMessages');
  if (!area) return;
  _cleanupOldMessages();  // ★ 内存优化：清理旧消息
  area.scrollTop = area.scrollHeight;
  _autoScroll = true;
  updateScrollBtn();
}

function updateScrollBtn() {
  var area = document.getElementById('outputMessages');
  var btn = document.getElementById('scrollBottomBtn');
  if (!area || !btn) return;
  var isAtBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 60;
  if (isAtBottom) {
    btn.classList.remove('show');
    _autoScroll = true;
  } else {
    btn.classList.add('show');
    _autoScroll = false;
  }
}

// 监听滚动事件（★ 节流：每100ms最多处理一次，减少重排）
(function() {
  var area = document.getElementById('outputMessages');
  if (area) {
    var _scrollThrottle = null;
    area.addEventListener('scroll', function() {
      if (_scrollThrottle) return;
      _scrollThrottle = setTimeout(function() {
        _scrollThrottle = null;
        updateScrollBtn();
      }, 100);
    });
  }
})();

// ===== 对话历史持久化 (localStorage) =====
var _msgHistory = [];
var _saveHistoryTimer = null;
var _HISTORY_VERSION = 2;  // ★ 历史格式版本号，修改格式时递增

function saveHistory() {
  // ★ 节流：最多每2秒保存一次，避免频繁序列化
  if (_saveHistoryTimer) return;
  _saveHistoryTimer = setTimeout(function() {
    _saveHistoryTimer = null;
    try {
      var area = document.getElementById('outputMessages');
      if (!area) return;
      var messages = [];
      var children = area.children;
      for (var i = 0; i < children.length; i++) {
        var el = children[i];
        var cls = '';
        if (el.classList.contains('msg-user')) cls = 'user';
        else if (el.classList.contains('msg-ai')) cls = 'ai';
        else if (el.classList.contains('msg-status')) cls = 'status';
        else if (el.classList.contains('msg-tool')) cls = 'tool';
        else if (el.classList.contains('msg-error')) cls = 'error';
        else continue;
        var contentHtml = '';
        if (cls === 'user') {
          var bubble = el.querySelector('.msg-bubble');
          contentHtml = bubble ? bubble.innerHTML : el.textContent;
        } else if (cls === 'ai') {
          var aiContent = el.querySelector('.ai-content');
          contentHtml = aiContent ? aiContent.innerHTML : el.textContent;
        } else {
          contentHtml = el.textContent;
        }
        messages.push({ type: cls, html: contentHtml });
      }
      if (messages.length > 200) messages = messages.slice(-200);
      localStorage.setItem('mimo_chat_history', JSON.stringify({
        version: _HISTORY_VERSION,
        messages: messages
      }));
    } catch(e) {}
  }, 2000);
}

function loadHistory() {
  try {
    var rawData = localStorage.getItem('mimo_chat_history');
    if (!rawData) return;
    var parsed = JSON.parse(rawData);
    var messages;
    // ★ 版本检测：旧格式是没有 version 字段的数组
    if (Array.isArray(parsed)) {
      // 旧格式，清除并重新开始
      console.log('[History] 检测到旧格式历史数据，已清除');
      localStorage.removeItem('mimo_chat_history');
      return;
    }
    messages = parsed.messages;
    if (!messages || !messages.length) return;
    var area = document.getElementById('outputMessages');
    if (!area) return;
    area.innerHTML = '';
    window._globalMsgCount = 0;
    messages.forEach(function(m) {
      var block = document.createElement('div');
      block.className = 'msg-block msg-' + m.type;
      block.dataset.msgIndex = window._globalMsgCount++;
      if (m.type === 'user') {
        block.innerHTML = '<div class="msg-bubble">' + m.html + '</div>';
      } else if (m.type === 'ai') {
        var rollbackBtn = document.createElement('div');
        rollbackBtn.className = 'snapshot-rollback-btn';
        rollbackBtn.title = '回退到此次修改前';
      rollbackBtn.innerHTML = SVG_ICONS['corner-down-left'];
        rollbackBtn.onclick = function(e) {
          e.stopPropagation();
          showSnapshotRollbackModal(block);
        };
        block.appendChild(rollbackBtn);
        var contentWrap = document.createElement('div');
        contentWrap.className = 'ai-content';
        contentWrap.innerHTML = m.html;
        block.appendChild(contentWrap);
      } else {
        block.innerHTML = m.html;
      }
      area.appendChild(block);
    });
    if (typeof PerfOpt !== 'undefined' && PerfOpt.setMessageCount) {
      PerfOpt.setMessageCount(window._globalMsgCount);
    }
    safeScrollToBottom();
  } catch(e) {}
}

// 页面加载时不自动恢复历史（用户要求每次启动新对话）
// loadHistory();  // ★ 已禁用自动恢复，每次启动都是新对话

// ===================== Agent 数字角色渲染器 =====================
// 矩形身体 + 椭圆形眼睛 + 10表情 + 10行为 + 8道具
// 与 agent_character.py 后端联动

var _agentCharacter = {
  emotion: 'smile',
  behavior: 'idle',
  prop: 'none',
  clickCount: 0,
  eyes: {
    left: { width: 9, height: 14, angle: 0, offset_y: 0 },
    right: { width: 9, height: 14, angle: 0, offset_y: 0 },
    spacing: 18,
    color: '#ff6900',
    pupilVisible: false
  },
  mouth: 'none',
  blinkInterval: 3.0,
  lastBlink: 0,
  isBlinking: false
};

// 表情参数映射（与 agent_character.py 同步）
var _EMOTION_PARAMS = {
  smile:    { lw:13,lh:18,la:0,ly:-2, rw:13,rh:18,ra:0,ry:-2, sp:22, ec:'#ff6900', mouth:'smile', blink:3.0 },
  angry:    { lw:13,lh:9,la:10,ly:0,  rw:13,rh:9,ra:-10,ry:0, sp:22, ec:'#ff453a', mouth:'frown', blink:2.0 },
  thinking: { lw:13,lh:20,la:0,ly:4,  rw:13,rh:20,ra:0,ry:-4, sp:22, ec:'#ff6900', mouth:'line', blink:8.0 },
  sleepy:   { lw:13,lh:6,la:0,ly:2,   rw:13,rh:6,ra:0,ry:2,  sp:22, ec:'#ff9800', mouth:'o', blink:5.0 },
  surprised: { lw:15,lh:22,la:0,ly:0, rw:15,rh:22,ra:0,ry:0, sp:18, ec:'#ff6900', mouth:'o', blink:4.0 },
  happy:    { lw:13,lh:15,la:0,ly:-2, rw:13,rh:15,ra:0,ry:-2, sp:22, ec:'#ff6900', mouth:'smile', blink:3.0 },
  confused: { lw:15,lh:18,la:0,ly:0, rw:9,rh:10,ra:0,ry:0,  sp:22, ec:'#ff6900', mouth:'zigzag', blink:4.0 },
  bored:    { lw:13,lh:11,la:0,ly:2,   rw:13,rh:11,ra:0,ry:2,  sp:22, ec:'#ff9800', mouth:'line', blink:6.0 },
  focused:  { lw:10,lh:14,la:0,ly:0,  rw:10,rh:14,ra:0,ry:0,  sp:22, ec:'#ff6900', mouth:'line', blink:10.0 },
  shy:      { lw:13,lh:9,la:0,ly:2,   rw:13,rh:9,ra:0,ry:2,  sp:22, ec:'#ff8a65', mouth:'smile', blink:3.0 }
};

function _updateAgentEmotion(emotion) {
  var params = _EMOTION_PARAMS[emotion] || _EMOTION_PARAMS['smile'];
  _agentCharacter.emotion = emotion;
  _agentCharacter.eyes.left.width = params.lw;
  _agentCharacter.eyes.left.height = params.lh;
  _agentCharacter.eyes.left.angle = params.la;
  _agentCharacter.eyes.left.offset_y = params.ly;
  _agentCharacter.eyes.right.width = params.rw;
  _agentCharacter.eyes.right.height = params.rh;
  _agentCharacter.eyes.right.angle = params.ra;
  _agentCharacter.eyes.right.offset_y = params.ry;
  _agentCharacter.eyes.spacing = params.sp;
  _agentCharacter.eyes.color = params.ec;
  _agentCharacter.mouth = params.mouth;
  _agentCharacter.blinkInterval = params.blink;
  _renderAgentCharacter();
}

function _renderAgentCharacter() {
  var robot = document.getElementById('robot');
  if (!robot) return;
  var eyes = robot.querySelectorAll('.robot-eye');
  if (!eyes || eyes.length < 2) return;
  var e = _agentCharacter.eyes;
  var bl = _agentCharacter.isBlinking ? 2 : e.left.height;
  var br = _agentCharacter.isBlinking ? 2 : e.right.height;
  eyes[0].style.cssText = 'width:' + e.left.width + 'px;height:' + bl + 'px;transform:rotate(' + e.left.angle + 'deg) translateY(' + e.left.offset_y + 'px);background:' + e.color + ';transition:all 0.15s;';
  eyes[1].style.cssText = 'width:' + e.right.width + 'px;height:' + br + 'px;transform:rotate(' + e.right.angle + 'deg) translateY(' + e.right.offset_y + 'px);background:' + e.color + ';transition:all 0.15s;';
  var mouth = robot.querySelector('.robot-mouth');
  if (mouth) {
    var mouthStyle = '';
    switch (_agentCharacter.mouth) {
      case 'smile': mouthStyle = 'width:16px;height:8px;border-bottom:2px solid ' + e.color + ';border-radius:0 0 8px 8px;'; break;
      case 'frown': mouthStyle = 'width:16px;height:8px;border-top:2px solid ' + e.color + ';border-radius:8px 8px 0 0;'; break;
      case 'o': mouthStyle = 'width:8px;height:8px;border:2px solid ' + e.color + ';border-radius:50%;'; break;
      case 'line': mouthStyle = 'width:12px;height:0;border-top:2px solid ' + e.color + ';'; break;
      case 'zigzag': mouthStyle = 'width:14px;height:6px;border-bottom:2px solid ' + e.color + ';'; break;
      default: mouthStyle = 'display:none;';
    }
    mouth.style.cssText = 'position:absolute;top:40px;left:50%;transform:translateX(-50%);' + mouthStyle;
  }
}

// 自动眨眼
setInterval(function() {
  if (Math.random() < 0.02) {
    _agentCharacter.isBlinking = true;
    _renderAgentCharacter();
    setTimeout(function() {
      _agentCharacter.isBlinking = false;
      _renderAgentCharacter();
    }, 150);
  }
}, 200);

// ★ _onAgentStateChange 已在前面的 Agent 状态感知行为区统一定义，
//   同时联动 CSS class 动画和 _updateAgentEmotion 表情系统，此处不再重复。

// ===================== 时间日期小部件 =====================
function updateClock() {
  var now = new Date();
  var hours = _padZero(now.getHours());
  var minutes = _padZero(now.getMinutes());
  var month = _padZero(now.getMonth() + 1);
  var day = _padZero(now.getDate());
  var weekDays = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
  var week = weekDays[now.getDay()];

  var timeEl = document.getElementById('clockTime');
  var dateEl = document.getElementById('clockDate');
  if (timeEl) timeEl.textContent = hours + ':' + minutes;
  if (dateEl) dateEl.textContent = month + '/' + day + ' ' + week;
}
updateClock();
setInterval(updateClock, 1000);

// 悬停时间组件时机器人会看过来，增加互动
var timeWidget = document.getElementById('timeWidget');
if (timeWidget) {
  timeWidget.addEventListener('mouseenter', function() {
    if (clickCount === 0) setExpression('looking-right');
  });
  timeWidget.addEventListener('mouseleave', function() {
    if (clickCount === 0) setExpression('');
  });
}

// ===================== 图片上传功能 =====================
function handleImageUpload(event) {
  var files = event.target.files;
  if (!files || files.length === 0) return;
  
  for (var i = 0; i < files.length; i++) {
    var file = files[i];
    if (!file.type.startsWith('image/')) continue;
    
    var reader = new FileReader();
    reader.onload = function(e) {
      var imgData = e.target.result;
      // 在输出区显示图片
      appendImageMessage(imgData, file.name);
      // 通知 Python 端
      window._callPython('imageUpload', file.name, imgData);
    };
    reader.readAsDataURL(file);
  }
  
  // 清空 input 以便再次选择同一文件
  event.target.value = '';
}

function handleFileUpload(event) {
  var files = event.target.files;
  if (!files || files.length === 0) return;
  
  for (var i = 0; i < files.length; i++) {
    var file = files[i];
    var reader = new FileReader();
    reader.onload = function(e) {
      // 通知 Python 端
      window._callPython('fileUpload', file.name, e.target.result);
      // 显示文件上传状态
      appendStatusMessage('已上传文件: ' + file.name);
    };
    reader.readAsDataURL(file);
  }
  
  event.target.value = '';
}

function appendImageMessage(imgSrc, fileName) {
  var area = document.getElementById('outputMessages');
  if (!area) return;
  
  var block = document.createElement('div');
  block.className = 'msg-block msg-user';
  block.innerHTML = '<div class="msg-bubble">' +
    '<div style="margin-bottom:8px;font-size:14px;color:rgba(255,255,255,0.6);">' + SVG_ICONS.camera + ' ' + fileName + '</div>' +
    '<img src="' + imgSrc + '" class="msg-image" alt="' + fileName + '" onclick="window.open(\'' + imgSrc + '\', \'_blank\')">' +
    '</div>';
  area.appendChild(block);
  safeScrollToBottom();
}

// ===================== 图表可视化功能 =====================
var _chartInstances = {};
var _chartScriptLoaded = false;

function loadChartScript() {
  return new Promise(function(resolve, reject) {
    if (_chartScriptLoaded) {
      resolve();
      return;
    }
    // ★ v4.8.4 图表库本地化补完（353章意图落地）：本地优先 → CDN 回退 → canvas 降级
    //   此前只走 CDN，图表显示依赖网络，离线/网络差时图表消失
    var sources = [
      'libs/chartjs/chart.umd.min.js',
      'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js'
    ];
    var idx = 0;
    function tryNext() {
      if (idx >= sources.length) {
        console.warn('Chart.js 本地+CDN 均加载失败，使用降级方案');
        _chartScriptLoaded = 'fallback';
        resolve();
        return;
      }
      var script = document.createElement('script');
      script.src = sources[idx++];
      script.onload = function() {
        _chartScriptLoaded = true;
        resolve();
      };
      script.onerror = function() {
        console.warn('[Chart] 加载失败，切换下一来源: ' + script.src);
        try { document.head.removeChild(script); } catch (e) {}
        tryNext();
      };
      document.head.appendChild(script);
    }
    tryNext();
  });
}

// ★ 修复"图表几秒后变黑"：QtWebEngine GPU 合成层中 canvas 纹理易被逐出
//   （日志有 Shader Cache Creation failed，GPU 进程不稳定）。动画完成后把
//   canvas 快照为 <img>，彻底脱离合成层，从根上杜绝黑屏。
function _freezeChartCanvas(containerId, canvas) {
  try {
    if (!canvas || !canvas.isConnected || canvas._frozen) return;
    var url = canvas.toDataURL('image/png');
    if (!url || url.length < 500 || url === 'data:,') return;  // 空画布不冻结
    var img = document.createElement('img');
    img.src = url;
    img.alt = 'chart';
    img.style.cssText = 'max-width:100%;display:block;';
    img.dataset.frozenFrom = canvas.id || '';
    canvas._frozen = true;
    if (canvas.parentNode) {
      canvas.parentNode.replaceChild(img, canvas);
      // ★ 黑屏根治 v2: 冻结标记打到父容器上 —— 所有重扫入口（900ms重扫/滚动钩子/
      //   renderAutoDetectedGraphs/createChart）见到此标记即短路，杜绝"冻结→重扫→
      //   再建活canvas→GPU逐出→黑屏"的无限循环（2026-08-30 实锤根因）
      canvas.parentNode.dataset.chartFrozen = '1';
    }
  } catch (e) {}
}

function createChart(containerId, chartConfig) {
  loadChartScript().then(function() {
    var container = document.getElementById(containerId);
    if (!container) return;
    // ★ 黑屏根治 v2: 容器已冻结（img 快照在位）→ 不再重建活 canvas（重建即黑屏风险）
    if (container.dataset && container.dataset.chartFrozen === '1') return;
    if (container.querySelector('img[data-frozen-from]')) return;

    var canvas = document.createElement('canvas');
    canvas.id = 'chart_' + containerId;
    container.innerHTML = '';
    container.appendChild(canvas);

    if (_chartScriptLoaded === true && window.Chart) {
      // 使用 Chart.js
      var ctx = canvas.getContext('2d', { willReadFrequently: true });
      if (_chartInstances[containerId]) {
        _chartInstances[containerId].destroy();
      }
      var cfg = chartConfig || {};
      cfg.options = cfg.options || {};
      // ★ 尊重原配置：animation===false 时不强行开启（靠 1500ms 兜底冻结）
      if (cfg.options.animation !== false) {
        var _userComplete = (cfg.options.animation && typeof cfg.options.animation === 'object')
          ? cfg.options.animation.onComplete : null;
        cfg.options.animation = (typeof cfg.options.animation === 'object' && cfg.options.animation)
          ? cfg.options.animation : {};
        cfg.options.animation.onComplete = function () {
          try { if (typeof _userComplete === 'function') _userComplete.apply(this, arguments); } catch (e) {}
          _freezeChartCanvas(containerId, canvas);
        };
      }
      _chartInstances[containerId] = new Chart(ctx, cfg);
      // 兜底：动画被禁用/未触发时延迟快照
      setTimeout(function () { _freezeChartCanvas(containerId, canvas); }, 1500);
    } else {
      // 降级方案：简单的柱状图绘制
      drawFallbackChart(canvas, chartConfig);
    }
  });
}

function drawFallbackChart(canvas, config) {
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  var W = canvas.width = canvas.offsetWidth || 400;
  var H = canvas.height = canvas.offsetHeight || 300;
  
  var data = (config.data && config.data.datasets && config.data.datasets[0] && config.data.datasets[0].data) || [];
  var labels = (config.data && config.data.labels) || [];
  
  if (data.length === 0) {
    ctx.fillStyle = 'rgba(255,255,255,0.3)';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('暂无数据', W/2, H/2);
    return;
  }
  
  var maxVal = Math.max.apply(null, data);
  var minVal = Math.min.apply(null, [0].concat(data));
  var range = maxVal - minVal || 1;
  
  var padding = { top: 30, right: 20, bottom: 40, left: 50 };
  var chartW = W - padding.left - padding.right;
  var chartH = H - padding.top - padding.bottom;
  
  // 绘制坐标轴
  ctx.strokeStyle = 'rgba(255,255,255,0.2)';
  ctx.lineWidth = 1;
  
  // Y轴
  ctx.beginPath();
  ctx.moveTo(padding.left, padding.top);
  ctx.lineTo(padding.left, H - padding.bottom);
  ctx.stroke();
  
  // X轴
  ctx.beginPath();
  ctx.moveTo(padding.left, H - padding.bottom);
  ctx.lineTo(W - padding.right, H - padding.bottom);
  ctx.stroke();
  
  // 绘制柱状图/折线图
  var type = config.type || 'bar';
  var color = (config.data && config.data.datasets && config.data.datasets[0] && config.data.datasets[0].borderColor) || '#ff6900';
  var bgColor = (config.data && config.data.datasets && config.data.datasets[0] && config.data.datasets[0].backgroundColor) || 'rgba(255,105,0,0.3)';
  
  var barW = chartW / data.length * 0.6;
  var gap = chartW / data.length * 0.4;
  
  if (type === 'bar') {
    data.forEach(function(val, i) {
      var x = padding.left + i * (barW + gap) + gap/2;
      var barH = (val - minVal) / range * chartH;
      var y = H - padding.bottom - barH;
      
      ctx.fillStyle = bgColor;
      ctx.fillRect(x, y, barW, barH);
      
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, barW, barH);
      
      // 标签
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(labels[i] || '', x + barW/2, H - padding.bottom + 16);
    });
  } else if (type === 'line') {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    data.forEach(function(val, i) {
      var x = padding.left + i * (chartW / (data.length - 1 || 1));
      var y = H - padding.bottom - (val - minVal) / range * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    
    // 数据点
    ctx.fillStyle = color;
    data.forEach(function(val, i) {
      var x = padding.left + i * (chartW / (data.length - 1 || 1));
      var y = H - padding.bottom - (val - minVal) / range * chartH;
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
      
      // 标签
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(labels[i] || '', x, H - padding.bottom + 16);
    });
  }
}

// Python 调用：渲染图表
window.mimoAgent.renderChart = function(containerId, chartConfigJson) {
  try {
    var config = JSON.parse(chartConfigJson);
    // 确保容器存在
    var container = document.getElementById(containerId);
    if (!container) {
      var area = document.getElementById('outputMessages');
      if (area) {
        var block = document.createElement('div');
        block.className = 'msg-block';
        var chartDiv = document.createElement('div');
        chartDiv.id = containerId;
        chartDiv.className = 'chart-container';
        block.appendChild(chartDiv);
        area.appendChild(block);
        safeScrollToBottom();
      }
    }
    createChart(containerId, config);
  } catch(e) {
    console.error('图表渲染失败:', e);
  }
};

// ===================== 打点式坐标图形绘制 =====================
// 用无数个小点绘制数学函数图形，类似打点计时器的效果
function renderDotPlot(containerId, config) {
  var container = document.getElementById(containerId);
  if (!container) return;
  
  var title = config.title || '函数图像';
  var funcStr = config.function || 'Math.sin(x)';
  var xMin = config.xMin || -10;
  var xMax = config.xMax || 10;
  var yMin = config.yMin || -5;
  var yMax = config.yMax || 5;
  var dotCount = config.dotCount || 2000;
  var dotColor = config.dotColor || '#ff6900';
  var dotSize = config.dotSize || 1.5;
  
  container.innerHTML = '<div class="dot-plot-container">' +
    '<div class="plot-title">' + title + '</div>' +
    '<canvas id="dotplot_' + containerId + '"></canvas>' +
    '</div>';
  
  var canvas = document.getElementById('dotplot_' + containerId);
  if (!canvas) return;
  
  // 等待 canvas 布局完成
  setTimeout(function() {
    var ctx = canvas.getContext('2d', { willReadFrequently: true });
    var W = canvas.width = canvas.offsetWidth * 2;
    var H = canvas.height = canvas.offsetHeight * 2;
    ctx.scale(2, 2);
    
    var width = canvas.offsetWidth;
    var height = canvas.offsetHeight;
    var padding = { top: 20, right: 20, bottom: 30, left: 40 };
    var plotW = width - padding.left - padding.right;
    var plotH = height - padding.top - padding.bottom;
    
    // 坐标转换函数
    function toCanvasX(x) {
      return padding.left + (x - xMin) / (xMax - xMin) * plotW;
    }
    function toCanvasY(y) {
      return padding.top + (1 - (y - yMin) / (yMax - yMin)) * plotH;
    }
    
    // 绘制坐标轴
    ctx.strokeStyle = 'rgba(255,255,255,0.15)';
    ctx.lineWidth = 1;
    
    // X轴
    var yZero = Math.max(padding.top, Math.min(height - padding.bottom, toCanvasY(0)));
    ctx.beginPath();
    ctx.moveTo(padding.left, yZero);
    ctx.lineTo(width - padding.right, yZero);
    ctx.stroke();
    
    // Y轴
    var xZero = Math.max(padding.left, Math.min(width - padding.right, toCanvasX(0)));
    ctx.beginPath();
    ctx.moveTo(xZero, padding.top);
    ctx.lineTo(xZero, height - padding.bottom);
    ctx.stroke();
    
    // 网格线
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    var xStep = (xMax - xMin) / 10;
    var yStep = (yMax - yMin) / 8;
    for (var x = xMin; x <= xMax; x += xStep) {
      var cx = toCanvasX(x);
      ctx.beginPath();
      ctx.moveTo(cx, padding.top);
      ctx.lineTo(cx, height - padding.bottom);
      ctx.stroke();
    }
    for (var y = yMin; y <= yMax; y += yStep) {
      var cy = toCanvasY(y);
      ctx.beginPath();
      ctx.moveTo(padding.left, cy);
      ctx.lineTo(width - padding.right, cy);
      ctx.stroke();
    }
    
    // 刻度标签
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'center';
    for (var x = xMin; x <= xMax; x += xStep * 2) {
      var cx = toCanvasX(x);
      ctx.fillText(x.toFixed(1), cx, height - padding.bottom + 14);
    }
    ctx.textAlign = 'right';
    for (var y = yMin; y <= yMax; y += yStep * 2) {
      var cy = toCanvasY(y);
      ctx.fillText(y.toFixed(1), padding.left - 6, cy + 4);
    }
    
    // 使用函数构造器
    var func;
    try {
      func = new Function('x', 'return ' + funcStr + ';');
    } catch(e) {
      ctx.fillStyle = 'rgba(255,100,100,0.6)';
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('函数表达式错误', width/2, height/2);
      return;
    }
    
    // 打点绘制（类似打点计时器）
    ctx.fillStyle = dotColor;
    var drawn = 0;
    var x = xMin;
    var step = (xMax - xMin) / dotCount;
    
    function drawBatch() {
      var batchSize = 100;
      for (var i = 0; i < batchSize && x <= xMax; i++) {
        try {
          var y = func(x);
          if (typeof y === 'number' && isFinite(y) && y >= yMin - 10 && y <= yMax + 10) {
            var cx = toCanvasX(x);
            var cy = toCanvasY(y);
            ctx.beginPath();
            ctx.arc(cx, cy, dotSize, 0, Math.PI * 2);
            ctx.fill();
            drawn++;
          }
        } catch(e) {}
        x += step;
      }
      
      if (x <= xMax) {
        requestAnimationFrame(drawBatch);
      }
    }
    
    drawBatch();
  }, 50);
}

// Python 调用：打点式函数图像
window.mimoAgent.renderDotPlot = function(containerId, configJson) {
  try {
    var config = JSON.parse(configJson);
    var container = document.getElementById(containerId);
    if (!container) {
      var area = document.getElementById('outputMessages');
      if (area) {
        var block = document.createElement('div');
        block.className = 'msg-block msg-ai';
        var div = document.createElement('div');
        div.id = containerId;
        block.appendChild(div);
        area.appendChild(block);
        safeScrollToBottom();
      }
    }
    renderDotPlot(containerId, config);
  } catch(e) {
    console.error('打点图渲染失败:', e);
  }
};

// ===================== 函数图像卡片展示 =====================
// 类似用户截图中的三角函数卡片风格
function renderFunctionCards(containerId, functions) {
  var container = document.getElementById(containerId);
  if (!container) return;
  
  var html = '<div class="func-cards-grid">';
  
  functions.forEach(function(func, idx) {
    var cardId = 'func_card_' + containerId + '_' + idx;
    html += '<div class="func-card">' +
      '<div class="func-card-header" style="background: ' + (func.color || 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)') + ';">' +
        '<div class="func-card-title">' + (func.title || '函数图像') + '</div>' +
      '</div>' +
      '<div class="func-card-canvas-wrap">' +
        '<canvas id="' + cardId + '" class="func-card-canvas"></canvas>' +
      '</div>' +
      '<div class="func-card-formula">' + (func.formula || 'y = f(x)') + '</div>' +
      '<div class="func-card-props">' +
        (func.properties ? func.properties.map(function(p) { return '<div class="func-prop"><span class="func-prop-label">' + p.label + ':</span> <span class="func-prop-value">' + p.value + '</span></div>'; }).join('') : '') +
      '</div>' +
    '</div>';
  });
  
  html += '</div>';
  container.innerHTML = html;
  
  // 延迟渲染每个函数图像
  setTimeout(function() {
    functions.forEach(function(func, idx) {
      var canvasId = 'func_card_' + containerId + '_' + idx;
      var canvas = document.getElementById(canvasId);
      if (canvas) {
        renderFunctionCardCanvas(canvas, func);
      }
    });
  }, 50);
}

function renderFunctionCardCanvas(canvas, func) {
  var ctx = canvas.getContext('2d', { willReadFrequently: true });
  var W = canvas.width = canvas.offsetWidth * 2;
  var H = canvas.height = canvas.offsetHeight * 2;
  ctx.scale(2, 2);
  
  var width = canvas.offsetWidth;
  var height = canvas.offsetHeight;
  var padding = { top: 10, right: 10, bottom: 10, left: 10 };
  var plotW = width - padding.left - padding.right;
  var plotH = height - padding.top - padding.bottom;
  
  var xMin = func.xMin || -Math.PI * 2;
  var xMax = func.xMax || Math.PI * 2;
  var yMin = func.yMin || -1.5;
  var yMax = func.yMax || 1.5;
  var color = func.lineColor || func.color || '#ff6900';
  
  function toCX(x) {
    return padding.left + (x - xMin) / (xMax - xMin) * plotW;
  }
  function toCY(y) {
    return padding.top + (1 - (y - yMin) / (yMax - yMin)) * plotH;
  }
  
  // 网格线
  ctx.strokeStyle = 'rgba(255,255,255,0.06)';
  ctx.lineWidth = 1;
  var gridX = 8;
  var gridY = 6;
  for (var i = 0; i <= gridX; i++) {
    var x = padding.left + i * plotW / gridX;
    ctx.beginPath();
    ctx.moveTo(x, padding.top);
    ctx.lineTo(x, height - padding.bottom);
    ctx.stroke();
  }
  for (var i = 0; i <= gridY; i++) {
    var y = padding.top + i * plotH / gridY;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
  }
  
  // 坐标轴
  ctx.strokeStyle = 'rgba(255,255,255,0.25)';
  ctx.lineWidth = 1;
  var y0 = Math.max(padding.top, Math.min(height - padding.bottom, toCY(0)));
  var x0 = Math.max(padding.left, Math.min(width - padding.right, toCX(0)));
  
  ctx.beginPath();
  ctx.moveTo(padding.left, y0);
  ctx.lineTo(width - padding.right, y0);
  ctx.stroke();
  
  ctx.beginPath();
  ctx.moveTo(x0, padding.top);
  ctx.lineTo(x0, height - padding.bottom);
  ctx.stroke();
  
  // 函数曲线
  try {
    var funcExpr = func.function || 'Math.sin(x)';
    var fn = new Function('x', 'return ' + funcExpr + ';');
    
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    var started = false;
    var steps = 500;
    for (var i = 0; i <= steps; i++) {
      var x = xMin + (xMax - xMin) * i / steps;
      try {
        var y = fn(x);
        if (typeof y === 'number' && isFinite(y)) {
          var cx = toCX(x);
          var cy = toCY(y);
          if (cy >= padding.top && cy <= height - padding.bottom) {
            if (!started) {
              ctx.moveTo(cx, cy);
              started = true;
            } else {
              ctx.lineTo(cx, cy);
            }
          } else {
            started = false;
          }
        } else {
          started = false;
        }
      } catch(e) {
        started = false;
      }
    }
    ctx.stroke();
  } catch(e) {
    console.error('函数绘制失败:', e);
  }
}

// Python 调用：函数卡片展示
window.mimoAgent.renderFunctionCards = function(containerId, configJson) {
  try {
    var config = JSON.parse(configJson);
    var container = document.getElementById(containerId);
    if (!container) {
      var area = document.getElementById('outputMessages');
      if (area) {
        var block = document.createElement('div');
        block.className = 'msg-block msg-ai';
        var div = document.createElement('div');
        div.id = containerId;
        block.appendChild(div);
        area.appendChild(block);
        safeScrollToBottom();
      }
    }
    renderFunctionCards(containerId, config.functions || []);
  } catch(e) {
    console.error('函数卡片渲染失败:', e);
  }
};

// ===================== 矩阵可视化 =====================
function renderMatrix(containerId, config) {
  var container = document.getElementById(containerId);
  if (!container) return;
  
  var matrix = config.matrix || [];
  var title = config.title || '';
  var rows = matrix.length;
  var cols = rows > 0 ? matrix[0].length : 0;
  
  var html = '<div class="matrix-container">';
  if (title) {
    html += '<div class="matrix-title">' + title + '</div>';
  }
  html += '<div class="matrix-wrapper">';
  html += '<div class="matrix-bracket matrix-bracket-left"></div>';
  html += '<table class="matrix-table">';
  
  for (var i = 0; i < rows; i++) {
    html += '<tr>';
    for (var j = 0; j < cols; j++) {
      var val = matrix[i][j];
      html += '<td class="matrix-cell">' + val + '</td>';
    }
    html += '</tr>';
  }
  
  html += '</table>';
  html += '<div class="matrix-bracket matrix-bracket-right"></div>';
  html += '</div>';
  
  if (config.properties) {
    html += '<div class="matrix-props">';
    config.properties.forEach(function(p) {
      html += '<div class="matrix-prop"><span class="matrix-prop-label">' + p.label + ':</span> <span class="matrix-prop-value">' + p.value + '</span></div>';
    });
    html += '</div>';
  }
  
  html += '</div>';
  container.innerHTML = html;
}

// Python 调用：矩阵可视化
window.mimoAgent.renderMatrix = function(containerId, configJson) {
  try {
    var config = JSON.parse(configJson);
    var container = document.getElementById(containerId);
    if (!container) {
      var area = document.getElementById('outputMessages');
      if (area) {
        var block = document.createElement('div');
        block.className = 'msg-block msg-ai';
        var div = document.createElement('div');
        div.id = containerId;
        block.appendChild(div);
        area.appendChild(block);
        safeScrollToBottom();
      }
    }
    renderMatrix(containerId, config);
  } catch(e) {
    console.error('矩阵渲染失败:', e);
  }
};

// ===================== 数列可视化 =====================
function renderSequence(containerId, config) {
  var container = document.getElementById(containerId);
  if (!container) return;
  
  var terms = config.terms || [];
  var title = config.title || '数列';
  var formula = config.formula || '';
  
  var html = '<div class="sequence-container">';
  html += '<div class="sequence-title">' + title + '</div>';
  
  if (formula) {
    html += '<div class="sequence-formula">' + formula + '</div>';
  }
  
  // 数列项展示
  html += '<div class="sequence-terms">';
  terms.forEach(function(term, idx) {
    html += '<div class="sequence-term">' +
      '<div class="term-index">a<sub>' + (idx + 1) + '</sub></div>' +
      '<div class="term-value">' + term + '</div>' +
      '</div>';
  });
  html += '</div>';
  
  // 数列图像（散点图）
  html += '<div class="sequence-chart-wrap">' +
    '<canvas id="seq_canvas_' + containerId + '" class="sequence-canvas"></canvas>' +
    '</div>';
  
  if (config.properties) {
    html += '<div class="sequence-props">';
    config.properties.forEach(function(p) {
      html += '<div class="seq-prop"><span class="seq-prop-label">' + p.label + ':</span> <span class="seq-prop-value">' + p.value + '</span></div>';
    });
    html += '</div>';
  }
  
  html += '</div>';
  container.innerHTML = html;
  
  // 绘制散点图
  setTimeout(function() {
    var canvas = document.getElementById('seq_canvas_' + containerId);
    if (canvas) {
      var ctx = canvas.getContext('2d', { willReadFrequently: true });
      var W = canvas.width = canvas.offsetWidth * 2;
      var H = canvas.height = canvas.offsetHeight * 2;
      ctx.scale(2, 2);
      
      var width = canvas.offsetWidth;
      var height = canvas.offsetHeight;
      var padding = { top: 20, right: 20, bottom: 30, left: 40 };
      var plotW = width - padding.left - padding.right;
      var plotH = height - padding.top - padding.bottom;
      
      var maxVal = Math.max.apply(null, terms);
      var minVal = Math.min.apply(null, [0].concat(terms));
      var range = maxVal - minVal || 1;
      
      function toCX(i) {
        return padding.left + (i + 0.5) / terms.length * plotW;
      }
      function toCY(v) {
        return padding.top + (1 - (v - minVal) / range) * plotH;
      }
      
      // 坐标轴
      ctx.strokeStyle = 'rgba(255,255,255,0.2)';
      ctx.lineWidth = 1;
      
      ctx.beginPath();
      ctx.moveTo(padding.left, height - padding.bottom);
      ctx.lineTo(width - padding.right, height - padding.bottom);
      ctx.stroke();
      
      ctx.beginPath();
      ctx.moveTo(padding.left, padding.top);
      ctx.lineTo(padding.left, height - padding.bottom);
      ctx.stroke();
      
      // 散点
      var colors = ['#ff6900', '#ff9a4a', '#58a6ff', '#3fb950', '#d2a8ff', '#f778ba'];
      terms.forEach(function(term, i) {
        var cx = toCX(i);
        var cy = toCY(term);
        var color = colors[i % colors.length];
        
        // 点
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(cx, cy, 5, 0, Math.PI * 2);
        ctx.fill();
        
        // 从x轴到点的虚线
        ctx.strokeStyle = color + '40';
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(cx, height - padding.bottom);
        ctx.lineTo(cx, cy);
        ctx.stroke();
        ctx.setLineDash([]);
        
        // 数值标签
        ctx.fillStyle = 'rgba(255,255,255,0.7)';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(term.toString(), cx, cy - 10);
      });
      
      // 下标标签
      ctx.fillStyle = 'rgba(255,255,255,0.4)';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      terms.forEach(function(_, i) {
        var cx = toCX(i);
        ctx.fillText((i + 1).toString(), cx, height - padding.bottom + 14);
      });
    }
  }, 50);
}

// Python 调用：数列可视化
window.mimoAgent.renderSequence = function(containerId, configJson) {
  try {
    var config = JSON.parse(configJson);
    var container = document.getElementById(containerId);
    if (!container) {
      var area = document.getElementById('outputMessages');
      if (area) {
        var block = document.createElement('div');
        block.className = 'msg-block msg-ai';
        var div = document.createElement('div');
        div.id = containerId;
        block.appendChild(div);
        area.appendChild(block);
        safeScrollToBottom();
      }
    }
    renderSequence(containerId, config);
  } catch(e) {
    console.error('数列渲染失败:', e);
  }
};

// ===================== SVG 图标工具函数 =====================
function getSvgIcon(name, size, color) {
  var icons = {
    search: '<svg width="W" height="H" viewBox="0 0 24 24" fill="none" stroke="COLOR" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    folder: '<svg width="W" height="H" viewBox="0 0 24 24" fill="none" stroke="COLOR" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
    image: '<svg width="W" height="H" viewBox="0 0 24 24" fill="none" stroke="COLOR" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21,15 16,10 5,21"/></svg>',
  };
  var svg = icons[name] || icons.folder;
  svg = svg.replace(/W/g, size || 16).replace(/H/g, size || 16).replace(/COLOR/g, color || 'currentColor');
  return svg;
}

// ★ 兜底初始化模型显示框
setTimeout(updateModelDisplay, 500);

// =====================================================================
// ★★★★★ v4.2.4: MIEMIE 咩咩模式（风格分析 + 粒子咩咩交互 + 工作流注入） ★★★★★
// =====================================================================

// ---- 面板开关 ----
function toggleMiemiePanel(force) {
  var panel = document.getElementById('miemiePanel');
  if (!panel) { console.warn('[MIEMIE] panel not found in DOM'); return; }
  var btn = document.getElementById('miemieToggleBtn');
  var isHidden = panel.style.display === 'none' || !panel.style.display;
  var show = (force !== undefined) ? force : isHidden;
  panel.style.display = show ? 'block' : 'none';
  if (btn) btn.classList.toggle('active', show);
  if (show) {
    startMiemieParticles();
    miemieStatus('咩咩就绪 · 点击「分析当前项目」开始');
  } else {
    stopMiemieParticles();
  }
}
// =====================================================================
// ★ v4.3.0: MIEMIE 咩咩引擎（仿 Claude Code / Kimi Code）
//   - 状态管理（mood / sub / 当前任务）
//   - DOM 网格咩咩（黑底白线，无背景框，每个像素点可独立动画）
//   - 能力调用（工具集 + 任务计划）
//   - 任务流渲染（用户消息 + 助手工具调用块链）
//   - 鼠标 hover 散开、点击迸发、状态切换颜色
// =====================================================================

var _miemieState = {
  mood: 'idle',
  moodTimer: 0,
  sub: '空闲 · 等待任务',
  pixelImage: null,
  pixelLoaded: false,
  gridCols: 60, gridRows: 80,
  pts: [],
  cells: [],
  wrapEl: null, gridEl: null,
  RAF: 0, t0: 0,
  mouseX: -9999, mouseY: -9999, mouseIn: false, scatterAmp: 0,
  busy: false,
  stepCount: 0,
  taskStartTime: 0,
  taskHistory: [],
  toolTypeCounts: {},
  filesModified: 0,
  successCount: 0,
  failCount: 0,
  agent: null,   // { bodyEl, replyEl, tcEls: [], pending: [] }
};

var MIEMIE_MOOD_LABELS = {
  idle: '空闲', thinking: '思考中', analyzing: '分析中',
  writing: '写入中', success: '完成', error: '出错', celebrating: '庆祝'
};

function miemieStatus(subText) {
  _miemieState.sub = subText;
  var subEl = document.getElementById('miemieSub');
  var moodEl = document.getElementById('miemieMoodPill');
  var gridEl = document.getElementById('miemiePixelGrid');
  if (subEl) subEl.textContent = subText;
  if (moodEl) {
    moodEl.textContent = MIEMIE_MOOD_LABELS[_miemieState.mood] || _miemieState.mood;
    moodEl.className = 'miemie-mood-pill mood-' + _miemieState.mood;
  }
  if (gridEl) {
    gridEl.classList.remove('mood-idle','mood-thinking','mood-analyzing','mood-writing','mood-success','mood-error','mood-celebrating');
    gridEl.classList.add('mood-' + _miemieState.mood);
  }
}
function setMiemieMood(mood, seconds) {
  if (!MIEMIE_MOOD_LABELS[mood]) mood = 'idle';
  _miemieState.mood = mood;
  if (_miemieState.moodTimer) { clearTimeout(_miemieState.moodTimer); _miemieState.moodTimer = 0; }
  if (seconds) {
    _miemieState.moodTimer = setTimeout(function(){ setMiemieMood('idle'); }, seconds * 1000);
  }
  miemieStatus('咩咩状态：' + MIEMIE_MOOD_LABELS[mood]);
  // 按心情给顶部头像换色
  var colorMap = {
    idle: '#f5e6d3', thinking: '#ffffff', analyzing: '#ffb86b',
    writing: '#ff9a5f', success: '#62d47e', error: '#ff5a5a', celebrating: '#e78ac3'
  };
  setMiemieAvatarColor(colorMap[mood] || colorMap.idle);
  // ★ v4.6.1 切换头像 mood class → 驱动粒子运动模式
  var av = document.getElementById('miemieAvatarMini');
  if (av) {
    ['idle','thinking','analyzing','writing','success','error','celebrating'].forEach(function(m){
      av.classList.remove('mood-' + m);
    });
    av.classList.add('mood-' + mood);
  }
}

function buildMiemiePixelGrid(img, cols, rows) {
  var pts = [];
  var cv = document.createElement('canvas');
  cv.width = cols; cv.height = rows;
  var ctx = cv.getContext('2d');
  ctx.drawImage(img, 0, 0, cols, rows);
  var data;
  try { data = ctx.getImageData(0, 0, cols, rows).data; }
  catch (e) { return null; }
  for (var y = 0; y < rows; y++) {
    for (var x = 0; x < cols; x++) {
      var i = (y * cols + x) * 4;
      var a = data[i + 3];
      if (a < 40) continue;
      var r = data[i], g = data[i+1], b = data[i+2];
      var lum = (r + g + b) / 3;
      if (lum < 150) {
        pts.push({ gx: x, gy: y, lum: lum });
      }
    }
  }
  return pts.length > 10 ? pts : null;
}

// =====================================================================
// 咩咩头像渲染（图片提取的 0/1 像素矩阵 → DOM grid）
// 数据源：data/miemie/miemie_pixel_map.json（由 PyBridge.getMiemiePixelMap() 注入）
// 形象唯一来源：用户拍的咩咩 OC 图（已脚本化提取，禁止再手绘 SVG/ASCII 点阵）
// =====================================================================
var _miemieAvatar = {
  initialized: false,
  cols: 80, rows: 74, pixels: null, features: null,
  defaultColor: '#f5e6d3'
};

function initMiemieAvatar() {
  var av = document.getElementById('miemieAvatarMini');
  if (!av || _miemieAvatar.initialized) return;
  var raw = '';
  try {
    if (window.pybridge && typeof window.pybridge.getMiemiePixelMap === 'function') {
      raw = window.pybridge.getMiemiePixelMap();
    }
  } catch (e) { /* bridge 未就绪时静默 */ }
  if (!raw) {
    av.innerHTML = '<span class="miemie-avatar-fallback">' + MIEMIE_SVG.sheep + '</span>';
    return;
  }
  var data;
  try { data = JSON.parse(raw); }
  catch (e) {
    av.innerHTML = '<span class="miemie-avatar-fallback">' + MIEMIE_SVG.sheep + '</span>';
    return;
  }
  _miemieAvatar.cols = data.grid_cols || 80;
  _miemieAvatar.rows = data.grid_rows || 74;
  _miemieAvatar.pixels = data.pixels || [];
  _miemieAvatar.features = data.features || {};

  // ★ v4.4.4: 形象风格（pixel / particle）
  var mstyle = 'pixel';
  try {
    if (window.pybridge && typeof window.pybridge.getMiemieAvatarStyle === 'function') {
      mstyle = window.pybridge.getMiemieAvatarStyle();
    }
  } catch (e) {}
  if (mstyle === 'particle') {
    try {
      renderMiemieParticle(av);
      _miemieAvatar.initialized = true;
      return;
    } catch (e) {
      console.warn('[MIEMIE] 粒子风格初始化失败:', e);
      // 不再强制回退像素，让用户能看到尝试结果；继续走像素分支
    }
  }

  av.innerHTML = '';
  av.style.gridTemplateColumns = 'repeat(' + _miemieAvatar.cols + ', 1fr)';
  av.style.gridTemplateRows = 'repeat(' + _miemieAvatar.rows + ', 1fr)';
  var frag = document.createDocumentFragment();
  for (var y = 0; y < _miemieAvatar.rows; y++) {
    var row = _miemieAvatar.pixels[y] || [];
    for (var x = 0; x < _miemieAvatar.cols; x++) {
      var cell = document.createElement('div');
      cell.className = 'mpix' + (row[x] ? ' on' : '');
      frag.appendChild(cell);
    }
  }
  av.appendChild(frag);
  av.style.setProperty('--mpix-color', _miemieAvatar.defaultColor);
  _miemieAvatar.initialized = true;
  // ★ v4.6.1 绑定点击爆散反馈
  initMiemieAvatarClick();
}

// ★ v4.4.4: 粒子风格渲染 + 形象切换
function hexA(hex, a) {
  if (typeof hex !== 'string' || hex[0] !== '#' || hex.length < 7) return hex;
  var r = parseInt(hex.substr(1, 2), 16),
      g = parseInt(hex.substr(3, 2), 16),
      b = parseInt(hex.substr(5, 2), 16);
  return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
}

function renderMiemieParticle(av) {
  console.log('[MIEMIE] 进入粒子渲染');
  try {
    av.classList.remove('bounce', 'spin', 'blink', 'wink');
    av.style.position = 'relative';
    av.innerHTML = '';
    var cols = _miemieAvatar.cols, rows = _miemieAvatar.rows;
    var pixels = _miemieAvatar.pixels || [];
    var feats = _miemieAvatar.features || {};
    var S = 48;                     // 头像容器视觉尺寸
    var cw = S / cols, ch = S / rows; // 单格屏幕尺寸
    var step = 2;                   // 采样步长：每 2 格取 1 点，防止过密糊团
    var pts = [];
    for (var y = 0; y < rows; y += step) {
      var row = pixels[y] || [];
      for (var x = 0; x < cols; x += step) {
        if (row[x] === 1) pts.push({ gx: x, gy: y });
      }
    }
    // 若仍过多则均匀抽取到 ~220 个，保证点间有间距、形状可辨
    var MAX = 220;
    if (pts.length > MAX) {
      var n = Math.ceil(pts.length / MAX);
      pts = pts.filter(function (_, i) { return i % n === 0; });
    }
    // 眼睛/嘴：标记最近采样点为深色粒子，五官清晰
    var eyeIdx = {};
    ['eye_left', 'eye_right', 'mouth'].forEach(function (k) {
      var p = feats[k];
      if (!p || p.length < 2) return;
      var best = -1, bd = 1e9;
      for (var i = 0; i < pts.length; i++) {
        var dx = pts[i].gx - p[0], dy = pts[i].gy - p[1];
        var d = dx * dx + dy * dy;
        if (d < bd) { bd = d; best = i; }
      }
      if (best >= 0) eyeIdx[best] = true;
    });
    pts.forEach(function (p, i) {
      var el = document.createElement('div');
      el.className = 'mparticle' + (eyeIdx[i] ? ' eye' : '');
      el.style.left = ((p.gx + 0.5) * cw - 1) + 'px';
      el.style.top = ((p.gy + 0.5) * ch - 1) + 'px';
      el.style.animationDelay = (-(Math.random() * 3.2)).toFixed(2) + 's';
      av.appendChild(el);
    });
    console.log('[MIEMIE] 粒子渲染完成，粒子数:', pts.length);
  } catch (e) {
    console.error('[MIEMIE] 粒子渲染失败（不影响其他功能）:', e);
    // ★ 不抛异常，避免外层强制回退像素
  }
}

function toggleMiemieAvatarStyle() {
  var cur = 'pixel';
  try {
    if (window.pybridge && typeof window.pybridge.getMiemieAvatarStyle === 'function') {
      cur = window.pybridge.getMiemieAvatarStyle();
    }
  } catch (e) {}
  var nxt = (cur === 'particle') ? 'pixel' : 'particle';
  try {
    if (window.pybridge && typeof window.pybridge.setMiemieAvatarStyle === 'function') {
      window.pybridge.setMiemieAvatarStyle(nxt);
    }
  } catch (e) {}
  var btn = document.getElementById('miemieStyleBtn');
  if (btn) btn.title = (nxt === 'particle') ? '形象：粒子' : '形象：像素';
  var av = document.getElementById('miemieAvatarMini');
  if (av) {
    if (av._raf) { cancelAnimationFrame(av._raf); av._raf = null; }
    _miemieAvatar.initialized = false;  // 允许重渲染
    initMiemieAvatar();
  }
}

function setMiemieAvatarColor(hex) {
  _miemieAvatar.defaultColor = hex || '#f5e6d3';
  var av = document.getElementById('miemieAvatarMini');
  if (av) {
    av.style.setProperty('--mpix-color', _miemieAvatar.defaultColor);
    av._color = _miemieAvatar.defaultColor;  // ★ v4.4.4: 供粒子 canvas 取色
  }
}

// ★ v4.6.1 咩咩头像点击：爆散重组反馈
function initMiemieAvatarClick() {
  var av = document.getElementById('miemieAvatarMini');
  if (!av || av._clickBound) return;
  av._clickBound = true;
  av.addEventListener('click', function() {
    if (av.classList.contains('burst') || av.classList.contains('bursting')) return;
    // 爆散环
    var ring = document.createElement('div');
    ring.className = 'burst-ring';
    av.appendChild(ring);
    av.classList.add('burst', 'bursting');
    setTimeout(function() { av.classList.remove('burst'); }, 520);
    setTimeout(function() { av.classList.remove('bursting'); if (ring.parentNode) ring.parentNode.removeChild(ring); }, 640);
    // 像素点随机飞散后回归（视觉爆散重组）
    var px = av.querySelectorAll('.mpix.on');
    px.forEach(function(p) {
      var dx = (Math.random() - 0.5) * 28;
      var dy = (Math.random() - 0.5) * 28;
      p.style.transition = 'transform 0.28s cubic-bezier(.34,1.56,.64,1)';
      p.style.transform = 'translate(' + dx + 'px,' + dy + 'px) scale(0.4)';
      setTimeout(function() { p.style.transform = ''; }, 300);
    });
    // 像素粒子（particle 模式）爆散
    var pt = av.querySelectorAll('.mparticle');
    pt.forEach(function(p) {
      var dx = (Math.random() - 0.5) * 40;
      var dy = (Math.random() - 0.5) * 40;
      p.style.transition = 'transform 0.3s cubic-bezier(.34,1.56,.64,1), opacity 0.3s';
      p.style.transform = 'translate(' + dx + 'px,' + dy + 'px) scale(0)';
      p.style.opacity = '0';
      setTimeout(function() { p.style.transform = ''; p.style.opacity = ''; }, 320);
    });
    // 互动反馈：咩一声
    miemieStatus(SVG_ICONS.sparkles + ' 咩~');
    if (typeof window.pybridge !== 'undefined' && window.pybridge && typeof window.pybridge.miemieBleat === 'function') {
      window.pybridge.miemieBleat();
    }
  });
}

// ★ v4.3.6: 全站统一极简线条 SVG 图标（与 theme.py SVG_ICONS 同款，禁用 emoji）
// ★ v4.8.1 安全守卫：如果 svg_icons.js 已加载并定义了 SVG_ICONS，则跳过本定义
var _svgIconsAlreadyDefined = (typeof SVG_ICONS !== 'undefined');
if (typeof SVG_ICONS === "undefined") {
SVG_ICONS = {
  check_circle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9 12l2 2 4-4"/></svg>',
  chart_bar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/></svg>',
  wrench: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
  message_circle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>',
  hourglass: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3h14M5 21h14M7 3v3a5 5 0 0 0 5 5 5 5 0 0 0-5 5v3M17 3v3a5 5 0 0 1-5 5 5 5 0 0 1 5 5v3"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  pencil: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
  alert_triangle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  x_circle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
  dot: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><circle cx="12" cy="12" r="4"/></svg>',
  lightning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
  rocket: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  file_plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>',
  file_edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M12 18l-2-2h4l-2 2"/><path d="M10 14l2 2-2 2"/></svg>',
  file_x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="15" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/></svg>',
  chevron_down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
  chevron_right: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
  external_link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  zap: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
  bot: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>',
  sparkles: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z"/><path d="M5 17l.75 2.25L8 20l-2.25.75L5 23l-.75-2.25L2 20l2.25-.75L5 17z"/></svg>',
  coffee: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
  eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
  lightbulb: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/></svg>',
  gamepad: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="12" x2="10" y2="12"/><line x1="8" y1="10" x2="8" y2="14"/><line x1="15" y1="13" x2="15.01" y2="13"/><line x1="18" y1="11" x2="18.01" y2="11"/><rect x="2" y="6" width="20" height="12" rx="2"/></svg>',
  diamond: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 22 8.5 12 22 2 8.5"/><line x1="2" y1="8.5" x2="22" y2="8.5"/><line x1="12" y1="2" x2="8" y2="8.5"/><line x1="12" y1="2" x2="16" y2="8.5"/><line x1="12" y1="22" x2="8" y2="8.5"/><line x1="12" y1="22" x2="16" y2="8.5"/></svg>',
  package: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="16.5" y1="9.4" x2="7.5" y2="4.21"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>',
  link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
  file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
  'circle-x': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
  'circle-check': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="9 12 11.5 14.5 15 10"/></svg>',
  'layout-template': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>',
  'square-pen': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
  'chevron-down': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
  'arrow-right': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>',
  'loader-circle': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>',
  'file-text': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>',
  'file-symlink': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M10 18l4-4"/><path d="M14 14v4h-4"/></svg>',
  'square-terminal': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><polyline points="7 8 11 12 7 16"/><line x1="13" y1="16" x2="17" y2="16"/></svg>',
  'corner-down-left': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/></svg>',
  'git-branch': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>'
};
// ★ v4.8.1: Store reference to primary SVG_ICONS (for later merge if needed)
window._mimoSVGIcons = SVG_ICONS;
} // closes if (!_svgIconsAlreadyDefined)

// ★ v4.8.1: MIEMIE_SVG 必须始终在全局定义（不依赖 SVG_ICONS 是否存在）。
// 旧版误将其放在 if (typeof SVG_ICONS === "undefined") 块内，导致加载 svg_icons.js 后
// if 块被跳过、MIEMIE_SVG 永远 undefined，进而 MIEMIE_TOOLS 初始化崩溃、
// 整段 mimo_app.js 后续初始化（星空/面板交互）全部失败。
var MIEMIE_SVG = {
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  file_default: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg>',
  pencil: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
  tool: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
  terminal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="4,17 10,11 4,5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>',
  globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
  palette: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/></svg>',
  star: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  database: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
  clipboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><line x1="9" y1="12" x2="15" y2="12"/><line x1="9" y1="16" x2="13" y2="16"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  sheep: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4c-2.6 0-4.5 2-4.5 4.5 0 1.2-.6 2.2-1.7 2.8-1.9 1-2.8 3.2-2 5 1 2.2 3.2 3.7 5.7 3.7h5c2.5 0 4.7-1.5 5.7-3.7.8-1.8-.1-4-2-5-1.1-.6-1.7-1.6-1.7-2.8C16.5 6 14.6 4 12 4z"/><circle cx="9.5" cy="12.5" r=".5" fill="currentColor"/><circle cx="14" cy="12.5" r=".5" fill="currentColor"/><path d="M10 15.5c1.3 1 2.7 1 4 0"/></svg>'
};

// ★ v4.3.3: 工具统一桥接到真实引擎（PyBridge.runMiemieTool → ui.miemie_engine）
// 全部真实执行：glob/grep/read/write/edit/bash/web_fetch/analyze_style/memory_search/sql_query/plan
function _runMiemieTool(tool, args) {
  try {
    if (window.pybridge && typeof window.pybridge.runMiemieTool === 'function') {
      var raw = window.pybridge.runMiemieTool(JSON.stringify({ tool: tool, args: args || {} }));
      if (raw) {
        var r = JSON.parse(raw);
        return Promise.resolve(r);
      }
    }
  } catch (e) { console.error('[MIEMIE] 工具桥接失败', tool, e); }
  return Promise.resolve({ ok: false, error: '桥接不可用：' + tool });
}

function _miemieFormatResult(r) {
  if (!r || typeof r !== 'object') return String(r);
  if (r.ok === false) return SVG_ICONS.x_circle + ' ' + (r.error || '执行失败');
  if (r.matches && r.matches.length) {
    var lines = [];
    for (var i = 0; i < Math.min(r.matches.length, 40); i++) {
      var m = r.matches[i];
      if (m && typeof m === 'object') lines.push((m.file || '?') + (m.line ? ':' + m.line : '') + '  ' + (m.text || ''));
      else lines.push(String(m));
    }
    if ((r.count || 0) > lines.length) lines.push('… 共 ' + r.count + ' 条，已截断');
    return lines.join('\n');
  }
  if (r.content !== undefined && r.path !== undefined) {
    var c = String(r.content);
    if (c.length > 2000) c = c.slice(0, 2000) + '\n…（内容过长，已截断）';
    return r.path + '（' + (r.lines || '?') + ' 行）\n' + c;
  }
  if (r.stdout !== undefined || r.stderr !== undefined) {
    return '$ ' + (r.command || '') + '\n' + (r.stdout || '') + (r.stderr ? '\n[stderr]\n' + r.stderr : '') + '\nexit_code=' + (r.exit_code === 0 || r.exit_code === '0' ? 0 : r.exit_code);
  }
  if (r.text !== undefined && r.url !== undefined) {
    return r.url + '\n' + String(r.text).slice(0, 2000);
  }
  if (r.naming_style !== undefined) {
    return '命名：' + r.naming_style + '  ·  缩进：' + r.indent_style + '(' + r.indent_width + ')\n' +
           '文件：' + (r.files_analyzed || '?') + '  ·  平均函数：' + (r.avg_function_length || '?') + ' 行\n' +
           (r.summary ? '摘要：' + r.summary : '');
  }
  if (r.entries && r.entries.length) {
    return r.entries.map(function(e){ return '· ' + (e.topic || '') + '：' + (e.detail || ''); }).join('\n');
  }
  if (r.columns) {
    var head = r.columns.join('  ');
    var rows = (r.rows || []).map(function(row){ return row.join('  '); }).join('\n');
    return head + (rows ? '\n' + rows : '\n（空结果）');
  }
  if (r.steps && r.steps.length) {
    return r.steps.map(function(s){ return s.n + '. ' + s.action + '  ' + SVG_ICONS.lightning + '  ' + (s.tools || []).join(', '); }).join('\n');
  }
  return JSON.stringify(r, null, 2).slice(0, 2000);
}

var MIEMIE_TOOL_TYPES = {
  read_file: { type: 'read', color: '#4da6ff', label: 'READ' },
  glob: { type: 'read', color: '#4da6ff', label: 'READ' },
  grep: { type: 'read', color: '#4da6ff', label: 'READ' },
  analyze_style: { type: 'analyze', color: '#b39ddb', label: 'ANALYZE' },
  write_file: { type: 'write', color: '#4caf50', label: 'WRITE' },
  edit_file: { type: 'write', color: '#4caf50', label: 'WRITE' },
  bash: { type: 'execute', color: '#ff9a4a', label: 'EXEC' },
  web_fetch: { type: 'fetch', color: '#4dd0e1', label: 'FETCH' },
  plan: { type: 'plan', color: '#9e9e9e', label: 'PLAN' },
  sql_query: { type: 'query', color: '#ffb74d', label: 'QUERY' },
  memory_search: { type: 'search', color: '#f48fb1', label: 'SEARCH' }
};

var MIEMIE_TOOLS = {
  read_file: { icon: MIEMIE_SVG.file_default, name: 'read_file', desc: '读取文件内容', run: function(a){ return _runMiemieTool('read_file', a); } },
  glob: { icon: MIEMIE_SVG.folder, name: 'glob', desc: '按 glob 模式匹配文件', run: function(a){ return _runMiemieTool('glob', a); } },
  grep: { icon: MIEMIE_SVG.search, name: 'grep', desc: '在文件中正则搜索', run: function(a){ return _runMiemieTool('grep', a); } },
  analyze_style: { icon: MIEMIE_SVG.palette, name: 'analyze_style', desc: '扫描代码提取风格画像', run: function(a){ return _runMiemieTool('analyze_style', a); } },
  memory_search: { icon: MIEMIE_SVG.star, name: 'memory_search', desc: '查咩咩记忆库', run: function(a){ return _runMiemieTool('memory_search', a); } },
  sql_query: { icon: MIEMIE_SVG.database, name: 'sql_query', desc: '查数据库', run: function(a){ return _runMiemieTool('sql_query', a); } },
  write_file: { icon: MIEMIE_SVG.pencil, name: 'write_file', desc: '创建/覆盖文件', run: function(a){ return _runMiemieTool('write_file', a); } },
  edit_file: { icon: MIEMIE_SVG.tool, name: 'edit_file', desc: '精确字符串替换', run: function(a){ return _runMiemieTool('edit_file', a); } },
  bash: { icon: MIEMIE_SVG.terminal, name: 'bash', desc: '执行 shell 命令', run: function(a){ return _runMiemieTool('bash', a); } },
  web_fetch: { icon: MIEMIE_SVG.globe, name: 'web_fetch', desc: '抓取网页', run: function(a){ return _runMiemieTool('web_fetch', a); } },
  plan: { icon: MIEMIE_SVG.clipboard, name: 'plan', desc: '任务规划/拆解', run: function(a){ return _runMiemieTool('plan', a); } }
};

var MIEMIE_PLANS = {
  analyze: [
    { tool: 'glob', args: { pattern: '**/*.py' }, desc: '枚举 Python 文件' },
    { tool: 'read_file', args: { path: 'standard_mode/ui/miemie_panel.py' }, desc: '读取咩咩面板源码' },
    { tool: 'analyze_style', args: {}, desc: '扫描代码风格' },
    { tool: 'memory_search', args: { query: '用户风格偏好' }, desc: '查咩咩记忆' }
  ],
  search: [
    { tool: 'grep', args: { pattern: 'TODO' }, desc: '搜 TODO 标记' },
    { tool: 'grep', args: { pattern: 'FIXME' }, desc: '搜 FIXME 标记' },
    { tool: 'grep', args: { pattern: 'class \\w+' }, desc: '搜类定义' }
  ],
  memory: [
    { tool: 'memory_search', args: { query: '项目' }, desc: '查项目相关记忆' },
    { tool: 'memory_search', args: { query: '用户偏好' }, desc: '查用户偏好' },
    { tool: 'memory_search', args: { query: '上次会话' }, desc: '查上次会话' }
  ],
  plan: [
    { tool: 'plan', args: { goal: '实现咩咩能力引擎' }, desc: '拆解任务' },
    { tool: 'sql_query', args: { query: 'SELECT * FROM tasks' }, desc: '查历史任务' }
  ],
  db: [
    { tool: 'sql_query', args: { query: 'SELECT * FROM tasks LIMIT 10' }, desc: '查任务表' },
    { tool: 'sql_query', args: { query: 'SELECT * FROM sessions' }, desc: '查会话表' },
    { tool: 'memory_search', args: { query: '数据库' }, desc: '查数据库相关记忆' }
  ]
};

// ★ v4.7.1: 双视图 —— 用户消息进「对话」视图
function miemieAppendUserMsg(text) {
  var stream = document.getElementById('miemieChatStream');
  if (!stream) return null;
  var empty = document.getElementById('miemieChatEmpty');
  if (empty) empty.remove();
  var div = document.createElement('div');
  div.className = 'miemie-msg miemie-msg-user';
  div.innerHTML = '<span class="msg-icon">' + MIEMIE_SVG.user + '</span><span class="msg-text"></span>';
  div.querySelector('.msg-text').textContent = text;
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
  miemieSwitchView('chat');
  return div;
}
// ★ v4.7.1: 双视图 —— 同时创建「对话」回复块 + 「任务流」任务根节点
// 返回任务流根节点（工具/结果挂其下）；聊天回复容器挂在 _miemieState.agent.chatEl
// title：任务流根节点标题（用户任务文本），任务流视图可识别"这条任务是什么"
function miemieAppendAssistantStart(title) {
  var chatBody = miemieAppendChatReply();
  var flowStream = document.getElementById('miemieStream');
  var flowRoot = null;
  if (flowStream) {
    var fEmpty = document.getElementById('miemieStreamEmpty');
    if (fEmpty) fEmpty.remove();
    flowRoot = document.createElement('div');
    flowRoot.className = 'miemie-task';
    if (title) {
      var th = document.createElement('div');
      th.className = 'miemie-task-title';
      th.textContent = title;
      var stepSpan = document.createElement('span');
      stepSpan.className = 'miemie-task-title-step';
      stepSpan.id = 'miemieStepLabel';
      th.appendChild(stepSpan);
      flowRoot.appendChild(th);
    }
    flowStream.appendChild(flowRoot);
    flowStream.scrollTop = flowStream.scrollHeight;
  }
  _miemieState.stepCount = 0;
  _miemieState.taskStartTime = Date.now();
  _miemieState.toolTypeCounts = {};
  _miemieState.filesModified = 0;
  _miemieState.successCount = 0;
  _miemieState.failCount = 0;
  if (!_miemieState.agent) _miemieState.agent = {};
  _miemieState.agent.chatEl = chatBody;
  return flowRoot;
}
// 在「对话」视图追加一条咩咩回复块（打字机目标）
function miemieAppendChatReply() {
  var stream = document.getElementById('miemieChatStream');
  if (!stream) return null;
  var empty = document.getElementById('miemieChatEmpty');
  if (empty) empty.remove();
  var div = document.createElement('div');
  div.className = 'miemie-msg miemie-msg-assistant';
  div.innerHTML = '<div class="msg-head"><span class="msg-logo">' + MIEMIE_SVG.sheep + '</span><span>MIEMIE</span></div><div class="msg-body"></div>';
  stream.appendChild(div);
  stream.scrollTop = stream.scrollHeight;
  return div.querySelector('.msg-body');
}
// ★ v4.7.1: 任务流节点树 —— 默认折叠参数，点击头部展开（渐进式披露）
function miemieAppendToolCall(bodyEl, toolName, args, desc) {
  if (!bodyEl) return null;
  var tool = MIEMIE_TOOLS[toolName] || { icon: MIEMIE_SVG.tool, name: toolName, desc: '' };
  var typeInfo = MIEMIE_TOOL_TYPES[toolName] || { type: 'other', color: '#9e9e9e', label: 'TOOL' };
  _miemieState.stepCount++;
  var stepNum = _miemieState.stepCount;
  if (!_miemieState.toolTypeCounts[toolName]) _miemieState.toolTypeCounts[toolName] = 0;
  _miemieState.toolTypeCounts[toolName]++;
  var stepLabel = document.getElementById('miemieStepLabel');
  if (stepLabel) stepLabel.textContent = 'Step ' + stepNum;
  var typeBg = typeInfo.color + '22';
  var typeBorder = typeInfo.color + '44';
  var div = document.createElement('div');
  div.className = 'miemie-tool-call';
  div.setAttribute('data-step', String(stepNum));
  div._startTime = Date.now();
  div._toolName = toolName;
  div._args = args;
  div.innerHTML =
    '<div class="tc-head">' +
      '<span class="tc-toggle">' + SVG_ICONS.chevron_right + '</span>' +
      '<span class="tc-icon">' + tool.icon + '</span>' +
      '<span class="tc-name">' + tool.name + '</span>' +
      '<span class="tc-type" style="background:' + typeBg + ';color:' + typeInfo.color + ';border:1px solid ' + typeBorder + ';">' + typeInfo.label + '</span>' +
      '<span class="tc-step-label">Step ' + stepNum + '</span>' +
      '<span class="tc-state running">' + SVG_ICONS.hourglass + ' 执行中</span>' +
    '</div>' +
    '<div class="tc-detail" style="display:none;">' +
      '<div class="tc-desc"></div>' +
      '<div class="tc-args"></div>' +
    '</div>';
  var dd = div.querySelector('.tc-desc');
  if (dd) dd.textContent = desc || tool.desc || '';
  var da = div.querySelector('.tc-args');
  if (da && args && Object.keys(args).length) da.textContent = JSON.stringify(args, null, 1);
  div.querySelector('.tc-head').addEventListener('click', function(ev) {
    ev.stopPropagation();
    var d = div.querySelector('.tc-detail');
    var t = div.querySelector('.tc-toggle');
    if (!d) return;
    var hidden = d.style.display === 'none';
    d.style.display = hidden ? '' : 'none';
    if (t) t.innerHTML = hidden ? SVG_ICONS.chevron_down : SVG_ICONS.chevron_right;
  });
  if (args && args.path) {
    div.classList.add('clickable');
    div.addEventListener('click', function(ev) {
      if (ev.target.closest('.tc-head') || ev.target.closest('.tc-detail')) return;
      var path = args.path;
      try {
        if (window.pybridge && typeof window.pybridge.openFile === 'function') {
          window.pybridge.openFile(path);
          if (args.line && typeof window.pybridge.gotoLine === 'function') {
            window.pybridge.gotoLine(path, String(args.line));
          }
          var hl = document.createElement('div');
          hl.className = 'tc-highlight';
          div.appendChild(hl);
          setTimeout(function(){ if (hl.parentNode) hl.remove(); }, 2000);
        }
      } catch (e) {}
    });
  }
  bodyEl.appendChild(div);
  _updateTimelineNodes(bodyEl);
  var stream = document.getElementById('miemieStream');
  if (stream) stream.scrollTop = stream.scrollHeight;
  miemieSwitchView('flow');
  return div;
}
function _updateTimelineNodes(bodyEl) {
  if (!bodyEl) return;
  var calls = bodyEl.querySelectorAll('.miemie-tool-call');
  for (var i = 0; i < calls.length; i++) {
    calls[i].classList.toggle('tc-last', i === calls.length - 1);
  }
}
function miemieMarkToolCall(tcEl, state) {
  if (!tcEl) return;
  var s = tcEl.querySelector('.tc-state');
  if (!s) return;
  var elapsed = '';
  if (tcEl._startTime) {
    var ms = ((Date.now() - tcEl._startTime) / 1000).toFixed(1);
    elapsed = ms + 's';
  }
  var stateIcon = state === 'done' ? SVG_ICONS.check_circle : (state === 'error' ? SVG_ICONS.x_circle : SVG_ICONS.hourglass);
  var stateText = state === 'done' ? '完成' : (state === 'error' ? '失败' : '执行中');
  s.className = 'tc-state ' + state;
  s.innerHTML = stateIcon + ' ' + stateText;
  tcEl.classList.toggle('tc-failed', state === 'error');
  tcEl.classList.add('tc-state-' + state);
  if (elapsed) {
    var old = tcEl.querySelector('.tc-timing');
    if (old) old.remove();
    var tEl = document.createElement('span');
    tEl.className = 'tc-timing ' + state;
    tEl.textContent = elapsed;
    s.parentNode.insertBefore(tEl, s.nextSibling);
  }
  if (state === 'done') _miemieState.successCount++;
  else if (state === 'error') _miemieState.failCount++;
}
// ★ v4.7.1: 工具结果折叠卡（收起/展开）
function miemieAppendToolResult(bodyEl, payload) {
  if (!bodyEl) return null;
  var div = document.createElement('div');
  div.className = 'miemie-tool-result';
  div.innerHTML = '<div class="tr-head"><span class="tr-toggle">' + SVG_ICONS.chevron_down + ' 收起</span></div><div class="tr-body"></div>';
  var body = div.querySelector('.tr-body');
  var text = typeof payload === 'string' ? payload : _miemieFormatResult(payload);
  if (typeof renderMarkdown === 'function') {
    body.innerHTML = '<div class="md-rendered">' + renderMarkdown(text) + '</div>';
  } else {
    body.textContent = text;
  }
  div.querySelector('.tr-head').addEventListener('click', function() {
    var b = div.querySelector('.tr-body');
    var t = div.querySelector('.tr-toggle');
    if (!b) return;
    var hidden = b.style.display === 'none';
    b.style.display = hidden ? '' : 'none';
    if (t) t.innerHTML = hidden ? SVG_ICONS.chevron_down + ' 收起' : SVG_ICONS.chevron_right + ' 展开';
  });
  bodyEl.appendChild(div);
  var stream = document.getElementById('miemieStream');
  if (stream) stream.scrollTop = stream.scrollHeight;
  return div;
}
// ★ v4.7.1: 总结同时进「对话」与「任务流」底部
function miemieAppendSummary(bodyEl, text, ok) {
  var cls = 'miemie-summary ' + (ok === false ? 'error' : (ok ? 'ok' : ''));
  var ag = _miemieState.agent;
  var totalMs = _miemieState.taskStartTime ? (Date.now() - _miemieState.taskStartTime) : 0;
  var totalSec = (totalMs / 1000).toFixed(1);
  var steps = _miemieState.stepCount;
  var suc = _miemieState.successCount;
  var fail = _miemieState.failCount;
  var taskRec = {
    title: (bodyEl && bodyEl.querySelector('.miemie-task-title')) ? bodyEl.querySelector('.miemie-task-title').textContent.replace(/Step \d+$/, '').trim() : '',
    ok: ok,
    steps: steps,
    success: suc,
    fail: fail,
    duration: totalSec,
    time: new Date().toLocaleTimeString()
  };
  _miemieState.taskHistory.unshift(taskRec);
  if (_miemieState.taskHistory.length > 20) _miemieState.taskHistory.length = 20;
  if (bodyEl && steps > 0) {
    var pBar = document.createElement('div');
    pBar.className = 'miemie-task-progress-bar';
    for (var i = 0; i < steps; i++) {
      var dot = document.createElement('span');
      dot.className = 'pp-dot pending';
      pBar.appendChild(dot);
    }
    bodyEl.appendChild(pBar);
  }
  if (bodyEl && steps > 0) {
    var card = document.createElement('div');
    card.className = 'miemie-summary-card';
    var titleIcon = ok ? SVG_ICONS.check_circle : SVG_ICONS.x_circle;
    var titleClass = ok ? '' : ' error-title';
    var titleText = ok ? '任务完成' : '任务结束';
    var h = '<div class="sc-title' + titleClass + '"><span class="sc-icon">' + titleIcon + '</span>' + titleText + '</div>';
    h += '<div class="sc-divider"></div>';
    h += '<div class="sc-stat-row"><span class="sc-stat-icon">' + SVG_ICONS.chart_bar + '</span>总步骤<span class="sc-stat-val">' + steps + '</span></div>';
    h += '<div class="sc-stat-row"><span class="sc-stat-icon">' + SVG_ICONS.check_circle + '</span>成功<span class="sc-stat-val">' + suc + '</span></div>';
    h += '<div class="sc-stat-row"><span class="sc-stat-icon">' + SVG_ICONS.x_circle + '</span>失败<span class="sc-stat-val">' + fail + '</span></div>';
    h += '<div class="sc-stat-row"><span class="sc-stat-icon">' + SVG_ICONS.clock + '</span>耗时<span class="sc-stat-val">' + totalSec + 's</span></div>';
    if (_miemieState.filesModified > 0) {
      h += '<div class="sc-stat-row"><span class="sc-stat-icon">' + SVG_ICONS.file_edit + '</span>修改文件<span class="sc-stat-val">' + _miemieState.filesModified + '</span></div>';
    }
    var toolKeys = Object.keys(_miemieState.toolTypeCounts);
    if (toolKeys.length > 0) {
      h += '<div class="sc-divider"></div>';
      for (var ti = 0; ti < toolKeys.length; ti++) {
        var tk = toolKeys[ti];
        var tDef = MIEMIE_TOOLS[tk] || { icon: MIEMIE_SVG.tool };
        h += '<div class="sc-tool-detail"><span class="sc-tool-icon">' + tDef.icon + '</span>' + tk + '<span style="margin-left:auto;font-family:ui-monospace,monospace;">x' + _miemieState.toolTypeCounts[tk] + '</span></div>';
      }
    }
    h += '<div class="sc-divider"></div>';
    h += '<div class="sc-actions">';
    h += '<button class="sc-btn" onclick="miemieShowFileChanges()">' + SVG_ICONS.folder + ' 查看文件变更</button>';
    h += '<button class="sc-btn" onclick="miemieCopyResult(this)">' + SVG_ICONS.copy + ' 复制结果</button>';
    h += '</div>';
    h += '<div class="sc-timestamp">' + new Date().toLocaleString() + '</div>';
    card.innerHTML = h;
    bodyEl.appendChild(card);
  }
  if (ag && ag.chatEl) {
    var div = document.createElement('div');
    div.className = cls;
    if (typeof renderMarkdown === 'function') {
      div.innerHTML = '<div class="md-rendered">' + renderMarkdown(text || '') + '</div>';
    } else {
      div.textContent = text;
    }
    ag.chatEl.appendChild(div);
    var cs = document.getElementById('miemieChatStream');
    if (cs) cs.scrollTop = cs.scrollHeight;
  }
  if (bodyEl) {
    var fdiv = document.createElement('div');
    fdiv.className = cls;
    if (typeof renderMarkdown === 'function') {
      fdiv.innerHTML = '<div class="md-rendered">' + renderMarkdown(text || '') + '</div>';
    } else {
      fdiv.textContent = text;
    }
    bodyEl.appendChild(fdiv);
  }
}

// ★ v4.3.5: LLM 回复打字机（逐字渲染，体现及时响应）
function miemieTypewriter(el, text, speed) {
  // ★ v4.7.x: 真流式 QWebChannel 打字机 —— 优先监听 miemieBridge.token_received
  // speed 参数保留向后兼容，用于非桥接环境下的 setTimeout 兜底
  if (!el) return;
  el.textContent = '';
  el._typewriterActive = false;

  // 清理上一次监听器
  if (el._bridgeCallback) {
    try {
      if (window.miemieBridge && window.miemieBridge.token_received) {
        window.miemieBridge.token_received.disconnect(el._bridgeCallback);
      }
    } catch (ex) {}
    el._bridgeCallback = null;
  }

  // 优先使用 QWebChannel 真流式桥接
  if (window.miemieBridge && window.miemieBridge.token_received) {
    el._typewriterActive = true;
    el._bridgeCallback = function(token) {
      if (!el._typewriterActive) { el._bridgeCallback = null; return; }
      el.textContent += token;
      var s = document.getElementById('miemieChatStream');
      if (s) s.scrollTop = s.scrollHeight;
    };
    window.miemieBridge.token_received.connect(el._bridgeCallback);

    // 监听 stream_done 自动清理
    if (window.miemieBridge.stream_done) {
      var doneCb = function(ok) {
        el._typewriterActive = false;
        if (el._bridgeCallback && window.miemieBridge && window.miemieBridge.token_received) {
          try { window.miemieBridge.token_received.disconnect(el._bridgeCallback); } catch (ex) {}
        }
        el._bridgeCallback = null;
        if (window.miemieBridge.stream_done) {
          try { window.miemieBridge.stream_done.disconnect(doneCb); } catch (ex) {}
        }
      };
      try {
        window.miemieBridge.stream_done.connect(doneCb);
      } catch (ex) {}
    }
    return;
  }

  // 兜底：JS setTimeout 模拟打字机（桥接不可用时）
  el._typewriterActive = true;
  var i = 0;
  speed = speed || 12;
  (function step() {
    if (!el._typewriterActive) return;
    if (i < text.length) {
      el.textContent += text.charAt(i);
      i++;
      var s = document.getElementById('miemieChatStream');
      if (s) s.scrollTop = s.scrollHeight;
      setTimeout(step, speed);
    }
  })();
}
// 类型书写完成标记（供外部调用以清理监听器）
function miemieTypewriterDone(el) {
  if (!el) return;
  el._typewriterActive = false;
  if (el._bridgeCallback && window.miemieBridge && window.miemieBridge.token_received) {
    try { window.miemieBridge.token_received.disconnect(el._bridgeCallback); } catch (ex) {}
  }
  el._bridgeCallback = null;
  if (typeof renderMarkdown === 'function' && el.textContent) {
    var wrapper = document.createElement('div');
    wrapper.className = 'md-rendered';
    wrapper.innerHTML = renderMarkdown(el.textContent);
    el.innerHTML = '';
    el.appendChild(wrapper);
  }
}

function miemieAppendThinkingBubble(bodyEl, text, isWorking) {
  if (!bodyEl) return null;
  var div = document.createElement('div');
  div.className = 'miemie-thinking-bubble' + (isWorking ? ' is-working' : '');
  var iconSvg = isWorking ? SVG_ICONS.hourglass : SVG_ICONS.message_circle;
  div.innerHTML = '<span class="tb-icon">' + iconSvg + '</span>' + (text || '');
  bodyEl.appendChild(div);
  var stream = document.getElementById('miemieStream');
  if (stream) stream.scrollTop = stream.scrollHeight;
  return div;
}

function renderMarkdown(text) {
  // ★ W1: JS 侧唯一 Markdown 渲染入口（咩咩面板工具结果 / 消息正文 / 任务摘要）。
  // 分工约定：
  //   - 主面板（Mimo 对话流）：走 Python `core.serve_bridge.markdown_to_html`（Pygments，带行号）
  //   - 咩咩面板（工具结果/卡片）：走本函数（marked + highlight.js）
  //   - diff 视图单行高亮：走 `_highlightCode`（行级场景，见该函数注释）
  // 视觉对齐：代码块容器样式统一为 `.codehilite` 同款（深色 #1e1e1e + 橙色左边框 + 8px 圆角），
  // 配色统一为 monokai（见 mimo_style.css `.hljs-*` 与 `.codehilite .k/.s/.m` 同色）。
  if (!text) return '';
  if (typeof marked !== 'undefined' && marked.parse) {
    try {
      marked.setOptions({ breaks: true, gfm: true });
      var html = marked.parse(text);
      if (typeof hljs !== 'undefined') {
        var temp = document.createElement('div');
        temp.innerHTML = html;
        var codeBlocks = temp.querySelectorAll('pre code');
        for (var i = 0; i < codeBlocks.length; i++) {
          try { hljs.highlightElement(codeBlocks[i]); } catch (e) {}
        }
        html = temp.innerHTML;
      }
      return html;
    } catch (e) {}
  }
  // 兜底：marked 未加载时的手写轻量转换
  var escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  escaped = escaped.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');
  escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');
  escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  escaped = escaped.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  escaped = escaped.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  escaped = escaped.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  escaped = escaped.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  escaped = escaped.replace(/\n/g, '<br>');
  return escaped;
}

function miemieShowFileChanges() {
  try {
    if (window.pybridge && typeof window.pybridge.showFileChanges === 'function') {
      window.pybridge.showFileChanges();
      return;
    }
  } catch (e) {}
  miemieStatus('文件变更面板需在桌面端打开');
}

function miemieCopyResult(btn) {
  var card = btn && btn.closest('.miemie-summary-card');
  var text = '';
  if (card) {
    var rows = card.querySelectorAll('.sc-stat-row');
    for (var i = 0; i < rows.length; i++) text += rows[i].textContent.trim() + '\n';
  }
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function() {
        miemieShowToast('已复制到剪贴板');
      });
    } else {
      var ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
      miemieShowToast('已复制到剪贴板');
    }
  } catch (e) {}
}

function miemieShowToast(msg) {
  var toast = document.createElement('div');
  toast.style.cssText = 'position:fixed;bottom:60px;left:50%;transform:translateX(-50%);background:rgba(255,122,47,0.9);color:#fff;padding:6px 16px;border-radius:6px;font-size:12px;z-index:99999;pointer-events:none;animation:fadeUp 0.25s ease-out;';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(function() { toast.remove(); }, 2000);
}

function addDiffGutterMarkers(filePath, diffData) {
  try {
    if (window.pybridge && typeof window.pybridge.addDiffGutterMarkers === 'function') {
      window.pybridge.addDiffGutterMarkers(filePath, JSON.stringify(diffData));
    }
  } catch (e) {}
}

function renderOverview() {
  var view = document.getElementById('miemieOverviewView');
  if (!view) return;
  var totalTasks = _miemieState.taskHistory.length;
  var totalSteps = 0;
  var totalFiles = 0;
  for (var i = 0; i < _miemieState.taskHistory.length; i++) {
    totalSteps += _miemieState.taskHistory[i].steps || 0;
  }
  var h = '<div class="miemie-overview-grid">';
  h += '<div class="miemie-overview-card"><div class="ov-val">' + totalTasks + '</div><div class="ov-label">任务</div></div>';
  h += '<div class="miemie-overview-card"><div class="ov-val">' + totalSteps + '</div><div class="ov-label">步骤</div></div>';
  h += '<div class="miemie-overview-card"><div class="ov-val">' + _miemieState.filesModified + '</div><div class="ov-label">文件</div></div>';
  h += '</div>';
  h += '<div class="overview-section-title">' + SVG_ICONS.clock + ' 最近任务</div>';
  h += '<div class="miemie-overview-timeline">';
  var recent = _miemieState.taskHistory.slice(0, 5);
  for (var j = 0; j < recent.length; j++) {
    var r = recent[j];
    var dotCls = r.ok ? 'ok' : 'err';
    h += '<div class="miemie-overview-tl-item" onclick="miemieSwitchView(\'flow\')">';
    h += '<span class="tl-dot ' + dotCls + '"></span>';
    h += '<span>' + (r.title || '任务') + '</span>';
    h += '<span class="tl-time">' + (r.duration || '?') + 's</span>';
    h += '</div>';
  }
  h += '</div>';
  var toolKeys = Object.keys(_miemieState.toolTypeCounts);
  if (toolKeys.length > 0) {
    h += '<div class="overview-section-title">' + SVG_ICONS.chart_bar + ' 工具使用频率</div>';
    h += '<div class="miemie-overview-bars">';
    var maxCount = 1;
    for (var k = 0; k < toolKeys.length; k++) {
      if (_miemieState.toolTypeCounts[toolKeys[k]] > maxCount) maxCount = _miemieState.toolTypeCounts[toolKeys[k]];
    }
    for (var m = 0; m < toolKeys.length; m++) {
      var tk = toolKeys[m];
      var cnt = _miemieState.toolTypeCounts[tk];
      var pct = Math.round((cnt / maxCount) * 100);
      h += '<div class="miemie-overview-bar-row">';
      h += '<span class="bar-label">' + tk + '</span>';
      h += '<span class="bar-track"><span class="bar-fill" style="width:' + pct + '%;"></span></span>';
      h += '<span class="bar-count">' + cnt + '</span>';
      h += '</div>';
    }
    h += '</div>';
  }
  view.querySelector('.miemie-stream').innerHTML = h;
}

// ★ v4.3.8: Python 真流式事件（base64 JSON → 实时渲染）
// 事件类型：token / step / result / summary / done
function miemieOnJson(b64) {
  var raw = b64;
  try { raw = decodeURIComponent(escape(atob(b64))); } catch (e) { try { raw = atob(b64); } catch (e2) { return; } }
  var evt;
  try { evt = JSON.parse(raw); } catch (e) { console.error('[MIEMIE] 事件解析失败', e); return; }
  var ag = _miemieState.agent;
  var stream = document.getElementById('miemieStream');
  switch (evt.type) {
    case 'token':
      if (!ag) return;
      if (!ag.chatEl) ag.chatEl = miemieAppendChatReply();
      ag.chatEl.textContent += evt.token || '';
      miemieSwitchView('chat');
      var cs = document.getElementById('miemieChatStream');
      if (cs) cs.scrollTop = cs.scrollHeight;
      break;
    case 'step':
      if (!ag) return;
      miemieAppendThinkingBubble(ag.bodyEl, '正在分析...', true);
      var tcEl = miemieAppendToolCall(ag.bodyEl, evt.tool, evt.args, evt.desc);
      ag.tcEls.push(tcEl);
      ag.pending.push(tcEl);
      if (evt.tool === 'write_file' || evt.tool === 'edit_file') _miemieState.filesModified++;
      setMiemieMood('analyzing');
      break;
    case 'result':
      if (!ag) return;
      var target = ag.pending.shift();
      if (target) miemieMarkToolCall(target, evt.state);
      miemieAppendThinkingBubble(ag.bodyEl, '完成，结果是...', false);
      if (evt.tool === 'llm') {
        // LLM 回复已通过 token 流式显示到对话视图；仅失败且无内容时兜底
        var hasStream = ag.chatEl && ag.chatEl.textContent && ag.chatEl.textContent.length > 3;
        if (evt.result && evt.result.ok === false && !hasStream) {
          var fallbackEl = miemieAppendChatReply();
          fallbackEl.textContent = evt.result.error || '咩咩处理失败';
          miemieSwitchView('chat');
        }
        break;
      }
      miemieAppendToolResult(ag.bodyEl, evt.result);
      break;
    case 'summary':
      if (!ag) return;
      miemieAppendSummary(ag.bodyEl, evt.text || '', evt.ok);
      setMiemieMood(evt.ok ? 'success' : 'error', 3);
      break;
    case 'confirm':
      // ★ v4.7.1: HITL 确认卡（worker 阻塞等用户决定，threading.Event）
      if (!ag) break;
      miemieAppendConfirmCard(ag.bodyEl, evt);
      setMiemieMood('thinking');
      break;
    case 'done':
      _miemieState.busy = false;
      _miemieState.agent = null;
      setMiemieMood(evt.ok ? 'idle' : 'error', 2);
      miemieStatus(evt.ok ? '咩咩任务完成' : '咩咩任务结束（部分失败）');
      break;
  }
}
function miemieClearStream() {
  var chatStream = document.getElementById('miemieChatStream');
  if (chatStream) {
    chatStream.innerHTML = '<div class="miemie-empty" id="miemieChatEmpty">' +
      '<p class="miemie-empty-title">和咩咩聊聊</p>' +
      '<p class="miemie-empty-desc">聊天、提问、闲聊都在这里。发任务时自动转到任务流。</p>' +
    '</div>';
  }
  var flowStream = document.getElementById('miemieStream');
  if (flowStream) {
    flowStream.innerHTML = '<div class="miemie-empty" id="miemieStreamEmpty">' +
      '<p class="miemie-empty-title">任务流</p>' +
      '<p class="miemie-empty-desc">咩咩执行任务的每一步都会显示在这里，高风险操作会弹确认卡。</p>' +
      '<div class="miemie-quick" id="miemieQuick">' +
        '<button onclick="miemieRunTask(\'analyze\')">分析</button>' +
        '<button onclick="miemieRunTask(\'search\')">搜索</button>' +
        '<button onclick="miemieRunTask(\'memory\')">记忆</button>' +
        '<button onclick="miemieRunTask(\'plan\')">规划</button>' +
        '<button onclick="miemieRunTask(\'db\')">数据库</button>' +
        '<button class="miemie-quick-special" onclick="miemieOpenPersona()">人格分身</button>' +
      '</div>' +
    '</div>';
  }
  setMiemieMood('idle');
  _miemieState.busy = false;
  _miemieState.agent = null;
  miemieSwitchView('chat');
}

// =====================================================================
// ★ v4.7.1: 双视图切换 + 指令 chips + 权限分层 + 人格入口 + HITL 确认卡
// =====================================================================
var MIEMIE_VIEW = { cur: 'chat' };

// 对话 / 任务流 视图切换
function miemieSwitchView(view) {
  if (view !== 'chat' && view !== 'flow' && view !== 'overview') return;
  MIEMIE_VIEW.cur = view;
  var chat = document.getElementById('miemieChatView');
  var flow = document.getElementById('miemieFlowView');
  var overview = document.getElementById('miemieOverviewView');
  var t1 = document.getElementById('miemieTabChat');
  var t2 = document.getElementById('miemieTabFlow');
  var t3 = document.getElementById('miemieTabOverview');
  if (chat) chat.style.display = view === 'chat' ? '' : 'none';
  if (flow) flow.style.display = view === 'flow' ? '' : 'none';
  if (overview) overview.style.display = view === 'overview' ? '' : 'none';
  if (t1) t1.className = 'miemie-tab' + (view === 'chat' ? ' active' : '');
  if (t2) t2.className = 'miemie-tab' + (view === 'flow' ? ' active' : '');
  if (t3) t3.className = 'miemie-tab' + (view === 'overview' ? ' active' : '');
  if (view === 'overview') renderOverview();
}

// 指令 chip 点击：填入输入框，执行权归用户（第 246 章结论）
function miemieChipFill(text) {
  var inp = document.getElementById('miemieInput');
  if (!inp) return;
  inp.value = text;
  inp.focus();
  try { inp.setSelectionRange(inp.value.length, inp.value.length); } catch (e) {}
}

// 打开人格工作区（v4.7.0 三栏大面板，经 pybridge）
function miemieOpenPersona() {
  try {
    if (window.pybridge && typeof window.pybridge.openPersonaWorkspace === 'function') {
      window.pybridge.openPersonaWorkspace();
      return;
    }
  } catch (e) {}
  miemieStatus('人格工作区需在桌面端打开');
}

// ---- 权限分层（auto/confirm/debug，与 Python 端 miemie_config.json 同步） ----
var _PERM_SEQ = ['auto', 'confirm', 'debug'];
var _PERM_LABEL = { auto: '自动', confirm: '确认', debug: '调试' };
var _PERM_TIP = {
  auto: '低风险自动跑，高风险(bash/写/改/网络)弹确认',
  confirm: '咩咩先展示工具计划，确认后才执行',
  debug: '逐步执行，每一步都确认'
};

function miemieRefreshPermBtn(mode) {
  var btn = document.getElementById('miemiePermBtn');
  if (!btn) return;
  btn.textContent = '权限·' + (_PERM_LABEL[mode] || '自动');
  btn.title = _PERM_TIP[mode] || '';
  btn.setAttribute('data-mode', mode || 'auto');
}

function miemieInitPermBtn() {
  var cur = 'auto';
  try {
    if (window.pybridge && typeof window.pybridge.getPermissionMode === 'function') {
      cur = window.pybridge.getPermissionMode() || 'auto';
    }
  } catch (e) {}
  miemieRefreshPermBtn(cur);
}

function miemieCyclePermission() {
  var cur = 'auto';
  try {
    if (window.pybridge && typeof window.pybridge.getPermissionMode === 'function') {
      cur = window.pybridge.getPermissionMode() || 'auto';
    }
  } catch (e) {}
  var nxt = _PERM_SEQ[(_PERM_SEQ.indexOf(cur) + 1) % 3];
  try {
    if (window.pybridge && typeof window.pybridge.setPermissionMode === 'function') {
      var r = window.pybridge.setPermissionMode(nxt);
      if (r) nxt = r;
    }
  } catch (e) {}
  miemieRefreshPermBtn(nxt);
  miemieStatus('权限模式 ' + SVG_ICONS.lightning + ' ' + (_PERM_LABEL[nxt] || nxt) + '（' + (_PERM_TIP[nxt] || '') + '）');
}

// ---- HITL 确认卡（worker 阻塞等决定；执行 / 拒绝 / 始终允许） ----
function miemieAppendConfirmCard(bodyEl, info) {
  var tool = (info && info.tool) || 'tool';
  var args = (info && info.args) || {};
  var desc = (info && info.desc) || '';
  var risk = (info && info.risk) || 'low';
  var toolDef = MIEMIE_TOOLS[tool] || { icon: MIEMIE_SVG.tool };
  var div = document.createElement('div');
  div.className = 'miemie-confirm';
  div.innerHTML =
    '<div class="mf-head">' +
      '<span class="mf-icon">' + toolDef.icon + '</span>' +
      '<span class="mf-title">等待确认</span>' +
      '<span class="mf-risk' + (risk === 'high' ? ' high' : '') + '">' + (risk === 'high' ? '高风险' : '确认模式') + '</span>' +
    '</div>' +
    '<div class="mf-name"><b>' + tool + '</b>' + (desc ? ' · ' + desc : '') + '</div>' +
    '<pre class="mf-args">' + (Object.keys(args).length ? JSON.stringify(args, null, 1) : '') + '</pre>' +
    '<div class="mf-actions">' +
      '<button class="mf-ok" onclick="miemieConfirmDecision(1,0)">执行</button>' +
      '<button class="mf-no" onclick="miemieConfirmDecision(0,0)">拒绝</button>' +
      '<button class="mf-alw" onclick="miemieConfirmDecision(1,1)">始终允许</button>' +
    '</div>';
  if (bodyEl) bodyEl.appendChild(div);
  var stream = document.getElementById('miemieStream');
  if (stream) stream.scrollTop = stream.scrollHeight;
  miemieSwitchView('flow');
  return div;
}

// 用户点击确认卡：回传 Python worker（pybridge.miemieConfirm）
function miemieConfirmDecision(ok, always) {
  try {
    if (window.pybridge && typeof window.pybridge.miemieConfirm === 'function') {
      window.pybridge.miemieConfirm(ok ? '1' : '0', always ? '1' : '0');
    }
  } catch (e) { console.error('[MIEMIE] 确认回传失败', e); }
  miemieStatus(ok ? '已放行该步骤' : '已拒绝该步骤');
}

// ★ v4.7.3: 总指挥(主会话)注入命令 → 本会话咩咩面板执行
// 由 Python 端 inject_user_message 调用；展开面板→填入输入框→提交。
function miemiePanelInject(text) {
  toggleMiemiePanel(true);
  var inp = document.getElementById('miemieInput');
  if (inp) inp.value = text;
  miemieSubmitInput();
}

// 打开 MIEMIE 服务主页（通过 pybridge 通知 PyQt 用浏览器/内嵌打开）
function miemieOpenService() {
  try {
    if (window.pybridge && window.pybridge.openMiemieService) {
      window.pybridge.openMiemieService();
      return;
    }
  } catch (e) {}
  // 兜底：浏览器直接打开
  var svc = 'service.html';
  var base = location.href.substring(0, location.href.lastIndexOf('/') + 1);
  window.open(base + svc, '_blank');
}

async function miemieRunTask(taskName, skipUserMsg) {
  if (_miemieState.busy) { miemieStatus('咩咩正忙，请稍候…'); return; }
  var plan = MIEMIE_PLANS[taskName];
  if (!plan) { miemieStatus('未知任务：' + taskName); return; }
  var userText = taskName === 'analyze' ? '分析当前项目风格' :
                 taskName === 'search' ? '搜索代码 TODO/FIXME' :
                 taskName === 'memory' ? '查咩咩记忆库' :
                 taskName === 'plan' ? '规划任务' :
                 taskName === 'db' ? '查数据库' : taskName;
  if (!skipUserMsg) miemieAppendUserMsg(userText);
  var bodyEl = miemieAppendAssistantStart(userText);
  _miemieState.busy = true;
  if (!_miemieState.agent) _miemieState.agent = {};
  _miemieState.agent.bodyEl = bodyEl;
  _miemieState.agent.replyEl = null;
  _miemieState.agent.tcEls = [];
  _miemieState.agent.pending = [];
  setMiemieMood('thinking');
  miemieStatus('咩咩正在执行任务：' + userText);
  // ★ v4.3.8: 真流式优先（Python worker 实时推送 token/step/result）
  if (window.pybridge && typeof window.pybridge.runMiemieAgent === 'function') {
    try {
      var r = JSON.parse(window.pybridge.runMiemieAgent(taskName, userText));
      if (r.ok) return;   // 后续渲染由 miemieOnJson 驱动
      console.error('[MIEMIE] Agent 启动失败', r);
    } catch (e) {
      console.error('[MIEMIE] 真流式启动异常，回退本地执行', e);
    }
    _miemieState.agent = null;
  }
  var allOk = true;
  for (var i = 0; i < plan.length; i++) {
    var step = plan[i];
    var tcEl = miemieAppendToolCall(bodyEl, step.tool, step.args, step.desc);
    setMiemieMood('analyzing');
    try {
      var res = await MIEMIE_TOOLS[step.tool].run(step.args || {});
      miemieMarkToolCall(tcEl, 'ok' in res && res.ok ? 'done' : 'error');
      miemieAppendToolResult(bodyEl, res);
      if ('ok' in res && !res.ok) allOk = false;
    } catch (e) {
      miemieMarkToolCall(tcEl, 'error');
      miemieAppendToolResult(bodyEl, SVG_ICONS.x_circle + ' ' + e.message);
      allOk = false;
    }
    await new Promise(function(r){ setTimeout(r, 250); });
  }
  setMiemieMood(allOk ? 'success' : 'error', 3);
  miemieAppendSummary(bodyEl, allOk ? '任务完成 · 咩咩已' + userText : '任务部分失败', allOk);
  _miemieState.busy = false;
  _miemieState.agent = null;
}

// ★ M17: 真流式聊天 —— 经 fetch 消费咩咩后端 /api/chat?stream=true 的 SSE 流。
// 后端逐块推送 data: {"token": 增量, "full": 累计} 与 data: {"done": true}；
// 这里用 ReadableStream reader 逐块读取、按行解析，每出一个 token 立即追加到
// replyEl（真流式打字机，与后端 token 同步，而非 setTimeout 视觉模拟）。
// 返回 Promise<boolean>：true=流式完成，false=失败（调用方应降级视觉打字机）。
function miemieHttpChatStream(replyEl, text) {
  return new Promise(function(resolve) {
    if (!replyEl) { resolve(false); return; }
    var apiPort = 7780; // 咩咩独立后端默认端口（miemie/api_server.py 模块级 start）
    var url = 'http://127.0.0.1:' + apiPort + '/api/chat?stream=true';
    var controller = null;
    // AbortController 让连接可被外部终止（防悬空 fetch）
    try { controller = new AbortController(); } catch (e) {}
    replyEl._httpStreamActive = true;
    replyEl._httpAbort = controller;

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text || '' }),
      signal: controller ? controller.signal : undefined
    }).then(function(resp) {
      if (!resp || !resp.body || !resp.body.getReader) {
        throw new Error('no readable stream (status=' + (resp && resp.status) + ')');
      }
      var reader = resp.body.getReader();
      var decoder = new TextDecoder('utf-8');
      var buf = '';
      function pump() {
        reader.read().then(function(chunk) {
          if (chunk.done) {
            replyEl._httpStreamActive = false;
            resolve(true);
            return;
          }
          buf += decoder.decode(chunk.value || new Uint8Array(), { stream: true });
          // 按行解析 SSE data: 事件
          var lines = buf.split('\n');
          buf = lines.pop(); // 末行可能未完整，留待下一块
          lines.forEach(function(line) {
            line = line.trim();
            if (line.indexOf('data:') !== 0) return; // 忽略空行 / 注释 / ping
            var payload = line.slice(5).trim();
            var evt;
            try { evt = JSON.parse(payload); } catch (e) { return; }
            if (evt.done) {
              // 流已结束，不再继续读取
              replyEl._httpStreamActive = false;
              try { if (controller) controller.abort(); } catch (e) {}
              resolve(true);
              return;
            }
            if (evt.token) {
              replyEl.textContent += evt.token;
              var cs = document.getElementById('miemieChatStream');
              if (cs) cs.scrollTop = cs.scrollHeight;
            }
          });
          if (replyEl._httpStreamActive) pump();
        }).catch(function(err) {
          replyEl._httpStreamActive = false;
          // 主动 abort 或已完成视为成功收尾
          resolve(true);
        });
      }
      pump();
    }).catch(function(err) {
      replyEl._httpStreamActive = false;
      console.error('[MIEMIE] HTTP 真流式失败，降级视觉打字机', err);
      resolve(false);
    });
  });
}

// ★ C-T07: MIEMIE.V1 代码风格/质量评审（前端入口）
// 取输入区代码，流式调用后端，渲染评审块 + 复制按钮。
function miemieStyleReview(intent) {
  intent = intent || 'style_review';
  var code = '';
  var inp = document.getElementById('miemieInput');
  if (inp) code = (inp.value || '').trim();
  if (!code) {
    miemieAppendNote('请先在输入框粘贴代码，再点代码风格 / 代码质量评审。');
    return;
  }
  var label = intent === 'quality_review' ? '代码质量评审' : '代码风格分析';
  // 组装发给后端的文本：用特殊前缀让意图路由命中 MIEMIE.V1
  var text = '【' + label + '】\n' + code;
  // 在任务流插入代码块 + 评审回复块
  var stream = document.getElementById('miemieChatStream');
  if (!stream) { miemieHttpChatStream(null, text); return; }
  var codeBlock = document.createElement('div');
  codeBlock.className = 'miemie-msg miemie-msg-user';
  codeBlock.innerHTML = SVG_ICONS['square-terminal'] + ' ' + label + '：\n' + code;
  stream.appendChild(codeBlock);

  var replyEl = document.createElement('div');
  replyEl.className = 'miemie-msg miemie-msg-assistant miemie-style-review';
  replyEl.style.whiteSpace = 'pre-wrap';
  stream.appendChild(replyEl);

  // 复制完整回复按钮
  var copyBtn = document.createElement('button');
  copyBtn.className = 'miemie-foot-btn miemie-foot-btn-mini';
  copyBtn.textContent = '复制';
  copyBtn.onclick = function() {
    try {
      navigator.clipboard.writeText(replyEl.textContent || '');
      copyBtn.textContent = '已复制';
      setTimeout(function() { copyBtn.textContent = '复制'; }, 1200);
    } catch (e) {
      copyBtn.textContent = '复制失败';
    }
  };
  replyEl.appendChild(copyBtn);

  stream.scrollTop = stream.scrollHeight;
  // 流式输出（复用真实 HTTP 流式；失败自动降级）
  miemieHttpChatStream(replyEl, text).then(function(ok) {
    if (!ok) {
      // 降级：视觉打字机
      miemieTypewriter(replyEl, '（MIEMIE.V1 暂不可用，已降级为视觉打字机）', 12);
    }
  });
}

function miemieSubmitInput() {
  var inp = document.getElementById('miemieInput');
  if (!inp) return;
  var raw = (inp.value || '').trim();
  if (!raw) return;
  inp.value = '';
  var lower = raw.toLowerCase();
  if (lower === '/help' || lower === 'help') {
    miemieAppendUserMsg(raw);
    var helpEl = miemieAppendChatReply();
    helpEl.style.whiteSpace = 'pre-wrap';
    helpEl.innerHTML =
      '可用指令：\n' +
      '  /analyze 或「分析」→ 分析当前项目风格\n' +
      '  /search 或「搜索」→ 搜索代码 TODO/FIXME\n' +
      '  /memory 或「记忆」→ 查咩咩记忆库\n' +
      '  /plan 或「规划」→ 任务规划\n' +
      '  /db 或「数据库」→ 查数据库\n' +
      '  /clear 或「清空」→ 清空任务流\n' +
      '\n任意自然语言：咩咩会用本机 Ollama 理解意图并自动选任务，闲聊也能回复。';
    miemieSwitchView('chat');
    return;
  }
  if (lower === '/clear' || lower === '清空') { miemieClearStream(); return; }
  // 命令直达
  if (lower === '/analyze') { miemieRunTask('analyze'); return; }
  if (lower === '/search') { miemieRunTask('search'); return; }
  if (lower === '/memory') { miemieRunTask('memory'); return; }
  if (lower === '/plan') { miemieRunTask('plan'); return; }
  if (lower === '/db') { miemieRunTask('db'); return; }
  miemieAppendUserMsg(raw);
  var body = miemieAppendAssistantStart(raw);
  setMiemieMood('thinking');
  miemieStatus('咩咩正在理解：' + raw.slice(0, 30));
  // LLM 意图路由（本机 Ollama）；失败自动降级
  var intent = '';
  var llmReply = '';
  try {
    if (window.pybridge && typeof window.pybridge.llmRoute === 'function') {
      var r = JSON.parse(window.pybridge.llmRoute(raw));
      intent = r.plan || '';
      llmReply = r.reply || '';
    }
  } catch (e) { console.error('[MIEMIE] llmRoute 失败', e); }
  if (MIEMIE_PLANS[intent]) {
    miemieAppendToolResult(body, '意图识别：' + intent);
    miemieRunTask(intent, true);
  } else {
    // ★ M17: 真流式聊天 —— 优先 fetch /api/chat?stream=true 的 SSE 流，
    // 与后端 token 同步（ReadableStream 逐块读取）；失败降级 Python worker，
    // 再失败才用视觉打字机（miemieTypewriter）。
    var replyEl = miemieAppendChatReply();
    miemieSwitchView('chat');
    _miemieState.busy = true;
    setMiemieMood('thinking');
    if (!_miemieState.agent) _miemieState.agent = {};
    _miemieState.agent.bodyEl = body;
    _miemieState.agent.replyEl = replyEl;
    miemieHttpChatStream(replyEl, raw).then(function(ok) {
      if (ok) {
        _miemieState.busy = false;
        setMiemieMood('idle', 2);
        return;
      }
      // 降级 1: Python worker 真流式（runMiemieAgent -> token_event -> miemieBridge）
      if (window.pybridge && typeof window.pybridge.runMiemieAgent === 'function') {
        try {
          _miemieState.busy = true;
          _miemieState.agent.tcEls = [];
          _miemieState.agent.pending = [];
          var r = JSON.parse(window.pybridge.runMiemieAgent('llm', raw));
          if (r.ok) return;   // 后续渲染由 miemieOnJson 驱动
          _miemieState.busy = false;
        } catch (e) {
          _miemieState.busy = false;
          console.error('[MIEMIE] 真流式启动异常', e);
        }
      }
      // 降级 2: 视觉打字机兜底（对话视图）
      miemieTypewriter(replyEl, llmReply || '咩咩在听～（本机 Ollama 未启动时请用 /help 查看能力）');
      setMiemieMood('idle', 2);
    });
  }
}

function toggleMiemiePanel(force) {
  var panel = document.getElementById('miemiePanel');
  if (!panel) return;
  var isHidden = panel.style.display === 'none' || !panel.style.display;
  var show = (force !== undefined) ? force : isHidden;
  panel.style.display = show ? 'block' : 'none';
  if (show) {
    initMiemieAvatar();
    miemieInitPermBtn();
    miemieStatus('咩咩就绪 · 输入任务开始工作');
  }
}

function bindMiemieAvatarInteractions() {
  var avEl = document.getElementById('miemieAvatarMini');
  if (!avEl || avEl._miemieBound) return;
  avEl._miemieBound = true;

  // 点击随机触发一种反应动画（不再随机 blink，blink 由定时器接管）
  avEl.addEventListener('click', function() {
    var anims = ['bounce', 'spin'];
    var cls = anims[Math.floor(Math.random() * anims.length)];
    avEl.classList.remove('bounce', 'spin', 'blink');
    void avEl.offsetWidth;
    avEl.classList.add(cls);
    setTimeout(function() { avEl.classList.remove(cls); }, 600);
  });

  // 随机眨眼（间隔拉长，更自然）
  function randomBlink() {
    if (avEl.classList.contains('bounce') || avEl.classList.contains('spin')) {
      setTimeout(randomBlink, 3000);
      return;
    }
    avEl.classList.remove('blink');
    void avEl.offsetWidth;
    avEl.classList.add('blink');
    setTimeout(function() { avEl.classList.remove('blink'); }, 220);
    setTimeout(randomBlink, 5000 + Math.random() * 5000);
  }
  setTimeout(randomBlink, 3000);
}

window.addEventListener('DOMContentLoaded', function(){
  // 等待用户从引擎下拉里点开咩咩入口
  bindMiemieAvatarInteractions();
  // ★ v4.7.13: 顶部 TopBar 初始化（积分显示/快捷键/通知计数）
  initTopbarExtras();
});

/* ====================================================================== */
/* ★ v4.7.13: 顶部 TopBar 新增工具（搜索/积分/主题/辅助/账户/通知）       */
/* ====================================================================== */

function initTopbarExtras(){
  try {
    var stored = localStorage.getItem('lemon_credits_total');
    if(!stored) stored = '2010';
    var used = parseInt(localStorage.getItem('lemon_credits_used') || '0', 10);
    var total = parseInt(stored, 10);
    var creditsNum = document.getElementById('creditsNumber');
    if(creditsNum) creditsNum.textContent = total.toLocaleString();
    var usedEl = document.getElementById('creditsUsed');
    var remEl = document.getElementById('creditsRemaining');
    var totalEl = document.getElementById('creditsTotal');
    if(usedEl) usedEl.textContent = used.toLocaleString();
    if(remEl) remEl.textContent = (total - used).toLocaleString();
    if(totalEl) totalEl.textContent = total.toLocaleString();
    var pct = total > 0 ? (used / total * 100).toFixed(1) : 0;
    var bar = document.getElementById('creditsProgressBar');
    if(bar) bar.style.width = pct + '%';
    var tokens = parseInt(localStorage.getItem('lemon_total_tokens') || '0', 10);
    var todayTokens = parseInt(localStorage.getItem('lemon_today_tokens') || '0', 10);
    var conv = parseInt(localStorage.getItem('lemon_conversations') || '0', 10);
    var t1 = document.getElementById('creditsTodayTokens');
    var t2 = document.getElementById('creditsTotalTokens');
    var t3 = document.getElementById('creditsConversations');
    if(t1) t1.textContent = todayTokens.toLocaleString();
    if(t2) t2.textContent = tokens.toLocaleString();
    if(t3) t3.textContent = conv.toLocaleString();
  } catch(e) {}

  document.addEventListener('click', function(e){
    var ids = ['themeQuickMenu','accessibilityMenu','accountMenu','creditsPanel'];
    for(var i=0;i<ids.length;i++){
      var el = document.getElementById(ids[i]);
      if(!el || el.style.display === 'none') continue;
      var triggerIds = {themeQuickMenu:'themeQuickBtn',accessibilityMenu:'a11yBtn',accountMenu:'accountBtn',creditsPanel:'topbarCredits'};
      var trigger = document.getElementById(triggerIds[ids[i]]);
      if(!el.contains(e.target) && (!trigger || !trigger.contains(e.target))){
        el.style.display = 'none';
      }
    }
    var notif = document.getElementById('notificationPanel');
    var notifBtn = document.getElementById('statusNotificationBtn');
    if(notif && notif.style.display !== 'none' && !notif.contains(e.target) && (!notifBtn || !notifBtn.contains(e.target))){
      notif.style.display = 'none';
    }
  });

  document.addEventListener('keydown', function(e){
    if(e.ctrlKey && e.shiftKey && (e.key==='F' || e.key==='f')){
      e.preventDefault();
      var sb = document.getElementById('topbarSearchInput');
      if(sb){ sb.focus(); sb.select(); }
    }
  });
}

function onTopbarSearch(q){
  if(!q || !q.trim()){
    document.querySelectorAll('.search-hit').forEach(function(el){
      var txt = el.textContent;
      el.parentNode.replaceChild(document.createTextNode(txt), el);
    });
    return;
  }
  var msgs = document.querySelectorAll('.msg-user, .msg-ai, .msg-block');
  msgs.forEach(function(m){
    if(m.textContent && m.textContent.toLowerCase().indexOf(q.toLowerCase()) >= 0){
      m.style.outline = '1px solid rgba(255,105,0,0.4)';
      m.style.outlineOffset = '2px';
    } else {
      m.style.outline = '';
    }
  });
}
function execTopbarSearch(q){
  if(!q || !q.trim()){
    _showToast('请输入要搜索的内容（消息/文件/命令）');
    return;
  }
  if(typeof _openSearchPanel === 'function'){
    _openSearchPanel();
    var inp = document.getElementById('searchInput');
    if(inp){ inp.value = q; if(typeof _doSearch === 'function') _doSearch(q); }
  } else {
    _showToast('搜索: ' + q);
  }
}

function toggleCreditsPanel(){
  var p = document.getElementById('creditsPanel');
  if(!p) return;
  closeAllTopbarMenus();
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
}
function closeCreditsPanel(){
  var p = document.getElementById('creditsPanel');
  if(p) p.style.display = 'none';
}

function toggleThemeQuickMenu(){
  var m = document.getElementById('themeQuickMenu');
  if(!m) return;
  closeAllTopbarMenus();
  m.style.display = m.style.display === 'none' ? 'block' : 'none';
}
function toggleAccessibilityMenu(){
  var m = document.getElementById('accessibilityMenu');
  if(!m) return;
  closeAllTopbarMenus();
  m.style.display = m.style.display === 'none' ? 'block' : 'none';
}
function toggleAccountMenu(){
  var m = document.getElementById('accountMenu');
  if(!m) return;
  closeAllTopbarMenus();
  m.style.display = m.style.display === 'none' ? 'block' : 'none';
}
function closeAllTopbarMenus(){
  ['themeQuickMenu','accessibilityMenu','accountMenu','creditsPanel','notificationPanel'].forEach(function(id){
    var el = document.getElementById(id);
    if(el) el.style.display = 'none';
  });
}

function cyclePanelLayout(){
  try {
    var layouts = ['default','single','multi'];
    var cur = localStorage.getItem('lemon_panel_layout') || 'default';
    var idx = (layouts.indexOf(cur) + 1) % layouts.length;
    var next = layouts[idx];
    localStorage.setItem('lemon_panel_layout', next);
    document.body.setAttribute('data-panel-layout', next);
    _showToast('面板布局: ' + next);
  } catch(e){ _showToast('面板布局切换失败'); }
}

function toggleA11y(key){
  var btn = document.getElementById('a11y-' + key);
  if(!btn) return;
  btn.classList.toggle('on');
  var on = btn.classList.contains('on');
  try { localStorage.setItem('a11y_' + key, on ? '1' : '0'); } catch(e){}
  document.body.setAttribute('data-a11y-' + key, on ? '1' : '0');
  if(key === 'font'){ document.body.style.fontSize = on ? '15px' : ''; }
  if(key === 'motion'){ document.body.style.setProperty('--motion-off', on ? '1' : '0'); }
  _showToast('辅助 · ' + key + ': ' + (on ? '开' : '关'));
}

function toggleNotificationPanel(){
  var p = document.getElementById('notificationPanel');
  if(!p) return;
  closeAllTopbarMenus();
  p.style.display = p.style.display === 'none' ? 'flex' : 'none';
}
function closeNotificationPanel(){
  var p = document.getElementById('notificationPanel');
  if(p) p.style.display = 'none';
}
function clearAllNotifications(){
  document.querySelectorAll('.notification-item.unread').forEach(function(el){ el.classList.remove('unread'); });
  var badge = document.getElementById('notificationBadge');
  if(badge){ badge.style.display = 'none'; badge.textContent = '0'; }
  _showToast('已全部标记为已读');
}

function setSubtoolMode(mode){
  var nativeBtn = document.getElementById('subtoolNativeBtn');
  var hostBtn = document.getElementById('subtoolHostBtn');
  if(!nativeBtn || !hostBtn) return;
  if(mode === 'native'){
    nativeBtn.classList.add('active');
    hostBtn.classList.remove('active');
  } else {
    hostBtn.classList.add('active');
    nativeBtn.classList.remove('active');
  }
  try { localStorage.setItem('subtoolbar_mode', mode); } catch(e){}
  _showToast('运行模式: ' + mode.toUpperCase());
}
function updateSubtoolStats(){
  try {
    if(window.performance && window.performance.memory){
      var mb = (window.performance.memory.usedJSHeapSize / (1024*1024)).toFixed(0);
      var memEl = document.getElementById('subtoolMemLabel');
      if(memEl) memEl.textContent = mb + 'MB';
    }
  } catch(e){}
}
setTimeout(function(){ updateSubtoolStats(); }, 1000);
setInterval(function(){ updateSubtoolStats(); }, 5000);

function _showToast(msg, type){
  try {
    var c = document.getElementById('toastContainer');
    if(!c){
      c = document.createElement('div');
      c.id = 'toastContainer';
      c.className = 'toast-container';
      c.style.cssText = 'position:fixed;bottom:60px;left:50%;transform:translateX(-50%);z-index:99999;display:flex;flex-direction:column;gap:8px;pointer-events:none;';
      document.body.appendChild(c);
    }
    var t = document.createElement('div');
    t.textContent = msg;
    t.style.cssText = 'padding:8px 16px;background:rgba(20,20,28,0.92);border:1px solid rgba(255,105,0,0.3);border-radius:6px;color:#fff;font-size:12px;backdrop-filter:blur(8px);box-shadow:0 4px 16px rgba(0,0,0,0.3);animation:toast-in 0.18s ease-out;opacity:0;transition:opacity 0.2s;';
    if(type === 'error') t.style.borderColor = 'rgba(255,80,80,0.4)';
    c.appendChild(t);
    requestAnimationFrame(function(){ t.style.opacity = '1'; });
    setTimeout(function(){
      t.style.opacity = '0';
      setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); }, 250);
    }, 2200);
  } catch(e){}
}

// ============================================================

// ============================================================

// ============================================================

// ============================================================
// ★ 第348章: TraceRenderer v3 — 对齐 Trae 真实设计语言
//   核心变化: 同类连续工具 → 分组摘要行（"已读取 3 个文件 ˅"）
//   极简无框 / 思考行 / 正常字号叙述 / 展开子项列表
// ============================================================
(function () {
  if (window.TraceRenderer && window.TraceRenderer.v >= 349) return;
  try { console.log('[TraceRenderer] v349 过程层/结论层分层已加载'); } catch (e) {}

  var runEl = null, textEl = null;
  var groupEl = null;        // 当前打开的工具分组
  var processEl = null;      // ★ 布局基线 v1: 过程层折叠容器（思考/工具/叙述/状态）
  var roundBodyEl = null;    // ★ Lemon Work: 当前轮次容器（多层白盒：第 N 轮小节）
  var statusEl = null;       // ★ 状态行（被后续事件取代或运行结束时清除）
  function clearStatus() {
    if (statusEl && statusEl.isConnected) statusEl.remove();
    statusEl = null;
  }
  var doneCount = 0, runCount = 0, elapsedTimer = null, runT0 = 0;

  function area() { return document.getElementById('outputMessages'); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function baseName(p) {
    var s = String(p || '').replace(/\\/g, '/');
    var i = s.lastIndexOf('/');
    return i >= 0 ? s.slice(i + 1) : s;
  }
  function scrollBottom() {
    if (typeof _autoScroll !== 'undefined' && _autoScroll === false) return;
    var a = area(); if (a) a.scrollTop = a.scrollHeight;
  }
  var ICONS = (typeof SVG_ICONS !== 'undefined') ? SVG_ICONS : (window.SVG_ICONS || {});
  var TYPE_ICON = { read: 'file-text', write: 'file-edit', search: 'search', command: 'square-terminal', tool: 'wrench' };
  // Trae 式动词: 进行时(运行中) / 完成时(折叠摘要)
  var GROUP_DOING = { read: '正在读取文件', write: '正在修改文件', search: '正在搜索', command: '正在执行命令', tool: '正在执行操作' };
  var GROUP_DONE = { read: '已读取 N 个文件', write: '已修改 N 个文件', search: '已搜索 N 次', command: '已执行 N 个命令', tool: '已执行 N 次操作' };
  var ITEM_DONE = { read: '已读取', write: '已修改', search: '已搜索', command: '已执行', tool: '已执行' };

  function updateProgress() {
    if (!runEl) return;
    var p = runEl.querySelector('.ar-progress');
    if (p) p.textContent = '✓' + doneCount + (runCount ? ' · 运行中' + runCount : '');
  }
  function startElapsed() {
    stopElapsed();
    runT0 = Date.now();
    elapsedTimer = setInterval(function () {
      if (!runEl || !runEl.isConnected) { stopElapsed(); return; }
      var e2 = runEl.querySelector('.ar-elapsed');
      if (e2) e2.textContent = fmtDur(Date.now() - runT0) || '0.0s';
    }, 1000);
  }
  function stopElapsed() {
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
  }
  function fmtDur(ms) {
    ms = Number(ms) || 0;
    if (ms >= 60000) return Math.floor(ms / 60000) + 'm ' + Math.round((ms % 60000) / 1000) + 's';
    return (ms / 1000).toFixed(1) + 's';
  }
  // ★ 网页引用卡: 从工具结果中提取 URL（去重、限数）
  function extractUrls(text, max) {
    var out = [], re = /https?:\/\/[^\s"'<>)\]}]+/g, m;
    try {
      while ((m = re.exec(String(text || ''))) !== null) {
        var u = m[0].replace(/[.,;:]+$/, '');
        if (out.indexOf(u) === -1) out.push(u);
        if (out.length >= (max || 4)) break;
      }
    } catch (e) {}
    return out;
  }
  function hostOf(u) {
    try { return (new URL(u)).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
  }
  // ★ 收集分组内的文件名 / URL（供 closeGroup 渲染 chips）
  function collectFromTool(group, arg, result) {
    if (!group) return;
    group._files = group._files || [];
    group._urls = group._urls || [];
    var bn = arg ? baseName(arg) : '';
    if (bn) group._files.push(bn);
    var us = extractUrls(result, 4);
    for (var i = 0; i < us.length; i++) {
      if (group._urls.indexOf(us[i]) === -1) group._urls.push(us[i]);
    }
  }
  // ★ 工具标签：文件名 + 行号（对标 Trae: main.py#L438-L446）
  function toolLabel(ev) {
    var t = ev.arg ? baseName(ev.arg) : (ev.name || '');
    if (ev.lines) t += '#' + ev.lines;
    return t;
  }
  // ★ Lemon Work: 条目行 = 工具中文名 + 参数摘要（微信版 toolLabels 对齐）
  function itemLine(ev) {
    var n = toolCN(ev.name);
    var a = ev.arg ? ' · ' + ev.arg : '';
    return n + a;
  }
  // ★ v350: 动作短语动词表（微信版 D5 对齐 —— 头部标题"正在读取 server.py"）
  var ACTION_VERB = {
    read: '正在读取', write: '正在写入', edit: '正在编辑',
    search: '正在搜索', command: '正在执行', worktree: '正在切换',
    tool: '正在调用'
  };
  // ★ v351 微信版 toolLabels 对齐：工具中文名（白盒可读性——
  //   用户看"查询账户余额"而不是 remote_bank_query_balance）。
  //   覆盖远程银行 26 项 + 通用工具 16 项；未命中回退原名。
  var TOOL_CN = {
    // 远程数字银行
    remote_bank_query_balance: '查询账户余额',
    remote_bank_transactions: '查询交易流水',
    remote_bank_transfer: '办理转账',
    remote_transfer_schedule: '定时转账',
    remote_transfer_aa: 'AA 收款',
    remote_bill_analysis: '账单消费分析',
    remote_wealth_advisor: '理财顾问',
    remote_card_manage: '银行卡管理',
    remote_subscription_cancel: '订阅退订',
    remote_mall: '权益商城',
    remote_loan_list: '贷款查询',
    remote_loan_repay: '贷款还款',
    remote_fund_list: '基金查询',
    remote_fund_buy: '基金申购',
    remote_stock_list: '股票行情',
    remote_stock_kline: 'K线查询',
    remote_stock_trade: '股票交易',
    remote_bank_holdings: '持仓查询',
    remote_find_account: '查找收款人',
    remote_bank_compound: '复利试算',
    remote_bank_risk_events: '风控事件',
    remote_bank_audit: '审计日志',
    remote_bank_reconcile: '对账核查',
    remote_bank_products: '理财产品',
    remote_bank_deposits: '定期存款',
    remote_bank_console: '银行操作台',
    // 通用工具
    write_file: '写入文件', file_write: '写入文件',
    edit_file: '编辑文件', file_edit: '编辑文件',
    file_append: '追加文件', multi_edit: '批量编辑',
    read_file: '读取文件', terminal: '执行命令',
    command: '执行命令', web_search: '联网搜索',
    web_fetch: '抓取网页', todo_write: '任务清单',
    spawn_subagent: '子代理', think: '深度思考',
    memory_write: '记忆写入', memory_search: '记忆检索'
  };
  function toolCN(name) {
    var n = String(name || '').split('.').pop();
    return TOOL_CN[n] || n;
  }
  // ★ 子项点击展开详情（参数 + 结果预览）——解决"看不到工具干了什么/查了什么词条"
  function bindItemDetail(item, ev, result) {
    item._arg = (ev && ev.arg) || '';
    item._result = String(result || '');
    item.classList.add('clickable');
    item.onclick = function () { toggleItemDetail(item); };
    // ★ Lemon Work: 自动内联一行结果摘要（微信版卡片默认可见，点击看全量）
    if (item._result && !item.parentNode.querySelector('.ti-brief[data-for="' + (item._bid || '') + '"]')) {
      item._bid = 'b' + Math.random().toString(36).slice(2, 8);
      var brief = document.createElement('div');
      brief.className = 'ti-brief';
      brief.setAttribute('data-for', item._bid);
      var _r = item._result.replace(/\s+/g, ' ').trim();
      brief.textContent = _r.slice(0, 110) + (_r.length > 110 ? '…' : '');
      item.parentNode.insertBefore(brief, item.nextSibling);
    }
  }
  function toggleItemDetail(item) {
    var ex = item.nextSibling;
    if (ex && ex.classList && ex.classList.contains('ti-detail')) { ex.remove(); return; }
    var all = item.parentNode.parentNode.querySelectorAll('.ti-detail');
    for (var i = 0; i < all.length; i++) all[i].remove();
    var arg = String(item._arg || '');
    var res = String(item._result || '');
    if (!arg && !res) return;
    var d = document.createElement('div');
    d.className = 'ti-detail';
    d.innerHTML =
      (arg ? '<div class="tid-row"><span class="tid-k">参数</span><span class="tid-v">' + esc(arg) + '</span></div>' : '') +
      (res ? '<div class="tid-row"><span class="tid-k">结果</span><span class="tid-v"><pre>' +
        esc(res.slice(0, 1200)) + (res.length > 1200 ? '\n…（已截断）' : '') + '</pre></span></div>' : '') +
      (res.length > 1200 ? '<div class="tid-full"><span class="tid-full-link" data-len="' +
        res.length + '">查看全量（' + res.length + ' 字）</span></div>' : '');
    if (res.length > 1200) {
      var link = d.querySelector('.tid-full-link');
      if (link) link.onclick = function () { showFullResultPanel(itemLine({ name: item._name || '工具', arg: item._arg }), res); };
    }
    item.parentNode.insertBefore(d, item.nextSibling);
    scrollBottom();
  }

  // ★ v350: 全量结果浮层（微信版 fhtml 面板对齐）—— 摘要化后查看原文的出口
  function showFullResultPanel(title, text) {
    var old = document.getElementById('lwFullResultMask');
    if (old) old.remove();
    var mask = document.createElement('div');
    mask.id = 'lwFullResultMask';
    mask.className = 'lw-fr-mask';
    mask.innerHTML =
      '<div class="lw-fr-panel">' +
      '<div class="lw-fr-head"><span class="lw-fr-title">' + esc(title) + '</span>' +
      '<span class="lw-fr-close">关闭</span></div>' +
      '<div class="lw-fr-body"><pre>' + esc(text) + '</pre></div></div>';
    mask.onclick = function (e) { if (e.target === mask) mask.remove(); };
    mask.querySelector('.lw-fr-close').onclick = function () { mask.remove(); };
    document.body.appendChild(mask);
  }

  function ensureRun(ev) {
    var a = area(); if (!a) return null;
    if (!runEl || !runEl.isConnected) {
      runEl = document.createElement('div');
      runEl.className = 'agent-run';
      var head = document.createElement('div');
      head.className = 'agent-run-head';
      head.innerHTML = '<span class="ar-dot"></span><span class="ar-title">Agent</span>' +
        '<span class="ar-progress"></span>' +
        '<span class="ar-elapsed">0.0s</span>' +
        (ev && ev.engine ? '<span class="ar-meta">' + esc(ev.engine) + '</span>' : '');
      runEl.appendChild(head);
      // ★ Lemon Work v5: 过程层改为「懒创建」——首个过程事件（思考/工具/叙述）
      //   到来时才建 .run-process，杜绝"第一个过程层什么都没有"的空横幅。
      //   结论(.trace-final)/meta 留在 runEl 顶层 → 过程/结论分层。
      processEl = null;
      roundBodyEl = null;
      a.appendChild(runEl);
      textEl = null; groupEl = null; doneCount = 0; runCount = 0;
      startElapsed();
    }
    return runEl;
  }

  // ★ 布局基线 v1: 过程层容器访问器（不存在则建）。过程节点统一挂这里。
  // ★ Lemon Work: 轮次开启时返回轮次 body —— 思考/工具/叙述自动嵌进"第 N 轮"
  // ★ v350 微信版对齐：run-process-head 升级为「统一过程头 proc-head」——
  //   状态灯（live/run/done 三态）+ 动态标题（动作短语 D5）+ 统计（思考 Ns · 工具 N 次）
  //   + 折叠箭头，一个头管整段过程（思考链/时间线/工具卡全部收进 body）。
  function processRoot() {
    var r = ensureRun(); if (!r) return null;
    if (roundBodyEl && roundBodyEl.isConnected) return roundBodyEl;
    if (!processEl || !processEl.isConnected) {
      processEl = document.createElement('div');
      processEl.className = 'run-process';
      var pf = document.createElement('div');
      pf.className = 'run-process-head proc-head';
      pf.innerHTML = '<span class="proc-dot proc-dot-run"></span>' +
        '<span class="proc-title">深度思考与执行中</span>' +
        '<span class="proc-stats"></span>' +
        '<span class="rp-chev">▾</span>';
      pf.onclick = function () {
        var open = processEl.classList.toggle('collapsed');
        pf.querySelector('.rp-chev').textContent = open ? '▸' : '▾';
        // 折叠态常驻：最新思考预览行（TRAE 式存在感）
        var pv = processEl.querySelector('.proc-preview');
        if (pv) pv.style.display = open ? 'flex' : 'none';
        scrollBottom();
      };
      var pv0 = document.createElement('div');
      pv0.className = 'proc-preview';
      pv0.style.display = 'none';
      pv0.innerHTML = '<span class="proc-preview-text"></span>';
      processEl.appendChild(pf);
      processEl.appendChild(pv0);
      r.insertBefore(processEl, r.querySelector('.trace-final') || null);
    }
    return processEl;
  }
  // ★ v350: 统一过程头控制（动作短语 / 统计 / 状态灯）
  function _procHead() {
    return processEl && processEl.isConnected ? processEl.querySelector('.proc-head') : null;
  }
  function setProcTitle(t) {
    var h = _procHead(); if (!h) return;
    var el = h.querySelector('.proc-title');
    if (el && el.textContent !== t) el.textContent = t;
  }
  function setProcDot(mode) {  // 'run' | 'live' | 'done'
    var h = _procHead(); if (!h) return;
    var d = h.querySelector('.proc-dot');
    if (d) d.className = 'proc-dot proc-dot-' + mode;
  }
  function setProcStats() {
    var h = _procHead(); if (!h) return;
    var el = h.querySelector('.proc-stats'); if (!el) return;
    var parts = [];
    if (runEl && runEl._thinkMs > 0) parts.push('思考 ' + (runEl._thinkMs / 1000).toFixed(1) + 's');
    if (doneCount > 0) parts.push('已调用 ' + doneCount + ' 次');
    if (runEl && runEl._maxRounds) parts.push('第 ' + (runEl._roundIdx || 1) + '/' + runEl._maxRounds + ' 轮');
    el.textContent = parts.join(' · ');
  }
  function setProcPreview(line) {
    if (!processEl || !processEl.isConnected) return;
    var pv = processEl.querySelector('.proc-preview-text');
    if (pv && line) pv.textContent = String(line).slice(0, 60);
  }

  // ★ Lemon Work v5: 空过程层直接移除（不是 display:none）——
  //   DOM 里不再留下"第一个空过程层、第二个才有内容"的结构。
  function isEmptyProcess(p) {
    return !p.querySelector('.trace-text,.trace-group,.trace-status,.trace-think,' +
      '.ti-brief,.trace-bg-task,.tr-round,.subagent-card,.web-page-card,.narr-wrap');
  }
  function hideProcessIfEmpty() {
    if (processEl && processEl.isConnected && isEmptyProcess(processEl)) {
      processEl.remove();
    }
    processEl = null;
  }
  function hideAllEmptyProcesses() {
    var a = area(); if (!a) return;
    var list = a.querySelectorAll('.run-process');
    for (var i = 0; i < list.length; i++) {
      if (isEmptyProcess(list[i])) list[i].remove();
    }
  }

  // ★ Lemon Work: 多层白盒核心 —— "第 N 轮"小节。
  //   思考/工具卡/叙述经 processRoot() 自动落入当前轮；轮与轮视觉分组，
  //   上一轮自动加 done 态（左边框变淡）。对标微信版逐轮呈现。
  function openRound(ev) {
    closeText(); closeGroup(); clearStatus();
    var pe = (roundBodyEl && roundBodyEl.isConnected)
      ? roundBodyEl.closest('.run-process') : processRoot();
    if (!pe) return;
    var last = pe.querySelector('.tr-round:last-of-type');
    if (last) last.classList.add('done');
    var sec = document.createElement('div');
    sec.className = 'tr-round';
    var mx = parseInt(ev.max_rounds || 0, 10);
    var head = document.createElement('div');
    head.className = 'tr-round-head';
    head.innerHTML = '<span class="tr-round-badge">第 ' + (ev.idx || 1) +
      (mx ? '/' + mx : '') + ' 轮</span>' +
      '<span class="tr-round-meta">' + esc(ev.engine || '') +
      (ev.tools ? ' · 已用工具 ' + ev.tools + ' 次' : ' · 规划中') + '</span>' +
      '<span class="tr-round-chev">▾</span>';
    // ★ v5: 每轮可独立折叠成小卡片（保留轮次徽标，收起该轮思考/工具/叙述）
    head.onclick = function () {
      var folded = sec.classList.toggle('folded');
      var ch = head.querySelector('.tr-round-chev');
      if (ch) ch.textContent = folded ? '▸' : '▾';
      scrollBottom();
    };
    var body = document.createElement('div');
    body.className = 'tr-round-body';
    sec.appendChild(head);
    sec.appendChild(body);
    pe.appendChild(sec);
    roundBodyEl = body;
    // ★ v350: 统一过程头联动 —— 轮次/上限/统计
    if (runEl) {
      runEl._roundIdx = parseInt(ev.idx || 1, 10);
      if (mx) runEl._maxRounds = mx;
      if (ev.think_ms) runEl._thinkMs = ev.think_ms;
    }
    setProcDot('run');
    setProcTitle('深度思考与执行中');
    setProcStats();
    scrollBottom();
  }

  function closeText() {
    if (!textEl) return;
    textEl.classList.remove('typing');
    // ★ 长叙述收纳为可折叠块 —— ★ Lemon Work: 阈值 400→2000 字。
    //   用户实测：400 字就把思考层折起来，正式内容一出现过程全被折叠，
    //   展开内容"消失"。2000 字内保持展开（"折叠≠隐藏"但别乱折）。
    var txt = textEl.textContent || '';
    if (txt.length > 2000 && !textEl._folded) {
      textEl._folded = true;
      textEl.classList.add('folded');
      var head = document.createElement('div');
      head.className = 'tt-fold-head';
      head.innerHTML = '<span>📝 分析叙述（' + txt.length + ' 字）</span><span class="tt-fold-chev">▸</span>';
      var body = document.createElement('div');
      body.className = 'tt-body';
      // ★ 关键：先把 textEl 既有正文节点全部移入 body（此前误用 head.nextSibling——head
      //   尚未插入 DOM 时恒为 null，导致 body 恒空，折叠纯属摆设）
      while (textEl.firstChild) body.appendChild(textEl.firstChild);
      textEl.appendChild(head);
      textEl.appendChild(body);
      head.onclick = function () {
        var open = textEl.classList.toggle('open');
        head.querySelector('.tt-fold-chev').textContent = open ? '▾' : '▸';
        scrollBottom();
      };
    }
    textEl = null;
  }

  function openText() {
    var p = processRoot(); if (!p) return null;
    clearStatus();  // 叙述到来 → 状态行退场
    if (!textEl) {
      textEl = document.createElement('div');
      textEl.className = 'trace-text typing';
      p.appendChild(textEl);
    }
    return textEl;
  }

  // ---------- Trae 式分组 ----------
  function closeGroup() {
    if (!groupEl) return;
    var n = groupEl._count || 0;
    var label;
    var single = (n === 1 && groupEl._first);
    if (single) {
      // ★ CodeBuddy 式动作行：单个工具直接显示 "已读取 main.py#L1-End"，无需展开
      label = (ITEM_DONE[groupEl._ttype] || '已执行') + ' ' + groupEl._first;
      // ★ Lemon Work: 单工具组标记 —— 头部已含工具信息，条目行不再重复
      groupEl.classList.add('single');
    } else {
      label = (GROUP_DONE[groupEl._ttype] || '已执行 N 次操作').replace('N', n);
    }
    var span = groupEl.querySelector('.tg-label');
    if (span) {
      span.textContent = label;
      // ★ 文件名 chips（对标 Trae：已读取 2 个文件 (README.md, main.py)）——仅多工具组
      var files = (groupEl._files || []).filter(function (v, i, a) { return v && a.indexOf(v) === i; });
      if (!single && files.length) {
        var chips = document.createElement('span');
        chips.className = 'tg-chips';
        for (var i = 0; i < Math.min(files.length, 6); i++) {
          var c = document.createElement('span');
          c.className = 'tg-chip';
          c.textContent = files[i];
          c.title = files[i];
          chips.appendChild(c);
        }
        if (files.length > 6) {
          var more = document.createElement('span');
          more.className = 'tg-chip more';
          more.textContent = '+' + (files.length - 6);
          chips.appendChild(more);
        }
        span.parentNode.insertBefore(chips, span.nextSibling);
      }
    }
    // ★ 网页引用卡（search 分组：favicon + 域名，点击新窗打开）
    var urls = (groupEl._urls || []).filter(function (v, i, a) { return v && a.indexOf(v) === i; });
    if (urls.length && groupEl._ttype === 'search') {
      var web = document.createElement('div');
      web.className = 'tg-web';
      var seenHost = {};
      var shown = 0;
      for (var u = 0; u < urls.length && shown < 4; u++) {
        var host = hostOf(urls[u]);
        if (!host || seenHost[host]) continue;   // ★ 按域名去重，消灭 "github.com ×3"
        seenHost[host] = 1;
        shown++;
        var a2 = document.createElement('a');
        a2.className = 'tg-web-item';
        a2.href = urls[u];
        a2.target = '_blank';
        a2.rel = 'noopener noreferrer';
        // ★ 字母头像替代远程 favicon（离线可用，不依赖 google 服务）
        a2.innerHTML =
          '<span class="tw-fav-l">' + esc((host[0] || '?').toUpperCase()) + '</span>' +
          '<span class="tw-host">' + esc(host) + '</span>';
        a2.title = urls[u];
        web.appendChild(a2);
      }
      if (web.childNodes.length) groupEl.appendChild(web);
    }
    if (single) {
      var ch = groupEl.querySelector('.tg-chevron');
      if (ch) ch.style.display = 'none';
    }
    // ★ 白盒底线：含失败的组强制保持展开（对标 GitHub Actions 失败步骤自动展开）
    var fails = groupEl._fails || 0;
    if (fails > 0) {
      groupEl.classList.add('has-fail', 'open');
      groupEl.classList.remove('folded');
      var fb = document.createElement('span');
      fb.className = 'tg-failbadge';
      fb.textContent = '✗ ' + fails + ' 失败';
      var hd = groupEl.querySelector('.tg-head');
      if (hd) hd.appendChild(fb);
    }
    groupEl.classList.remove('running');
    groupEl.classList.add('done');
    // ★ Lemon Work: 完成的工具组保持展开 —— 微信版工具卡片始终可见，
    //   折叠后用户就"看不到执行了什么"（点击仍可手动折叠）
    groupEl.classList.add('open');
    groupEl.classList.remove('folded');
    // ★ v350 微信版 WP4 对齐：同名工具聚合 —— 组内连续 ≥3 个同名条目
    //   折叠为一条聚合条（"已查询 ×5"），点击展开逐条还原。
    _applyAggregation(groupEl);
    groupEl = null;
  }

  // ★ v350: 同名聚合（微信版 WP4 对齐）。按【工具名】聚合（参数不同也算同名），
  //   连续 ≥3 条 → agg-bar 替换，原条目收进隐藏 .agg-items，点击 bar 切换。
  function _applyAggregation(group) {
    if (!group) return;
    var items = group.querySelectorAll('.tg-items .tg-item');
    if (items.length < 3) return;
    var itemsBox = group.querySelector('.tg-items');
    var i = 0;
    while (i < items.length) {
      var key = items[i].querySelector('.ti-text');
      // key = 工具名（" · " 前缀），同名合并（微信版按 name 聚合语义）
      var ktxt = key ? (key.textContent.split(' · ')[0] || key.textContent) : '';
      if (!ktxt) { i++; continue; }
      var j = i;
      while (j < items.length) {
        var kj = items[j].querySelector('.ti-text');
        if (kj && (kj.textContent.split(' · ')[0] || kj.textContent) === ktxt) j++; else break;
      }
      var n = j - i;
      if (n >= 3) {
        var bar = document.createElement('div');
        bar.className = 'agg-bar';
        var hasFail = false;
        for (var f = i; f < j; f++) if (items[f].classList.contains('fail')) hasFail = true;
        if (hasFail) bar.classList.add('has-fail');
        bar.innerHTML = '<span class="agg-dot"></span>' +
          '<span class="agg-text">已执行「' + esc(ktxt) + '」×' + n + '</span>' +
          '<span class="agg-toggle">展开</span>';
        var holder = document.createElement('div');
        holder.className = 'agg-items';
        holder.style.display = 'none';
        var first = items[i];
        itemsBox.insertBefore(bar, first);
        itemsBox.insertBefore(holder, bar.nextSibling);
        for (var k = i; k < j; k++) holder.appendChild(items[k]);
        var open = false;
        bar.onclick = function () {
          open = !open;
          holder.style.display = open ? 'block' : 'none';
          this.querySelector('.agg-toggle').textContent = open ? '收起' : '展开';
          scrollBottom();
        };
        i = j;
      } else {
        i = j;
      }
    }
  }

  function openGroup(ev) {
    closeText();
    clearStatus();  // 动作开始 → 状态行退场
    closeGroup();  // Trae: 不同类动作 → 上一组折叠
    var r = ensureRun(); if (!r) return;
    var iconKey = TYPE_ICON[ev.ttype] || 'wrench';
    var iconSvg = ICONS[iconKey] || ICONS['wrench'] || '';
    groupEl = document.createElement('div');
    groupEl.className = 'trace-group running g-' + (ev.ttype || 'tool');
    groupEl._ttype = ev.ttype || 'tool';
    groupEl._count = 0;
    groupEl._files = [];
    groupEl._urls = [];
    groupEl._fails = 0;
    groupEl.innerHTML =
      '<div class="tg-head">' +
        '<span class="tg-icon">' + iconSvg + '</span>' +
        '<span class="tg-label">' + (GROUP_DOING[groupEl._ttype] || '正在执行') + '</span>' +
        '<span class="tg-chevron">' + (ICONS['chevron-down'] || '') + '</span>' +
      '</div>' +
      '<div class="tg-items"></div>';
    groupEl.querySelector('.tg-head').onclick = function () {
      groupEl.classList.toggle('open');
      groupEl.classList.toggle('folded');
    };
    var _p = processRoot(); if (_p) _p.appendChild(groupEl);
    runCount++;
    updateProgress();
  }

  function addToolToGroup(ev, ok, ms, result, rejected) {
    var r = ensureRun(); if (!r) return;
    if (!groupEl || groupEl._ttype !== (ev.ttype || 'tool')) openGroup(ev);
    if (!groupEl) return;
    groupEl._count++;
    collectFromTool(groupEl, ev.arg, result);
    if (!groupEl._first) groupEl._first = toolLabel(ev);
    if (!ok) groupEl._fails = (groupEl._fails || 0) + 1;
    var items = groupEl.querySelector('.tg-items');
    var item = document.createElement('div');
    item.className = 'tg-item' + (ok ? '' : ' fail');
    var verb = ITEM_DONE[ev.ttype || 'tool'] || '已执行';
    var target = toolLabel(ev);
    var iconKey = TYPE_ICON[ev.ttype] || 'wrench';
    item.innerHTML =
      '<span class="ti-icon">' + (ICONS[iconKey] || '') + '</span>' +
      '<span class="ti-text">' + verb + ' ' + esc(target) + '</span>' +
      (ev.err ? '<span class="ti-err">（' + esc(ev.err) + '）</span>' : '') +
      '<span class="ti-dur">' + (ms ? fmtDur(ms) : '') + '</span>' +
      (rejected ? '<span class="ti-rej">已拒绝</span>' : '');
    item.title = String(result || '').slice(0, 400);
    bindItemDetail(item, ev, result);
    items.appendChild(item);
    doneCount++;
    updateProgress();
    scrollBottom();
  }

  // ★ 第348章补丁: 思考过程节点（可折叠，置于容器头部之后）
  // ★ v350 微信版 D2 对齐：思考链分节点 —— 按空行段落切分，每节点
  //   序号 + 独立展开/收起；流式期间仅重渲染最后一个"活跃节点"，
  //   用户手动收起的前序节点不被重绘（状态保留）。<2 段退回整块渲染。
  // ★ v353 乱码根治: markdown 渲染统一入口。
  //   此前两条裸奔路径：① 叙述 text_delta 走 esc() 直出（**/##/|---| 全裸）
  //   ② 思考层 marked 未就绪时 <pre>esc(原文)</pre> 兜底。
  //   现统一走 _mdRender：marked 可用 → parse；不可用 → _liteMarkdown 兜底，
  //   流式半截 markdown 先经 _balanceMarkdown 容错（未闭合 ** / ``` 处理），
  //   任何路径都不再出现 markdown 源码直出。
  function _balanceMarkdown(txt) {
    var t = String(txt || '');
    // ① 围栏 ``` 奇数个 → 末尾补闭合（流式代码块中途渲染）
    var fences = (t.match(/```/g) || []).length;
    if (fences % 2 === 1) t += '\n```';
    // ② 行内 ** 奇数个 → 去掉最后一个未闭合标记（收口后全量渲染自动恢复）
    var bolds = (t.match(/\*\*/g) || []).length;
    if (bolds % 2 === 1) {
      var i = t.lastIndexOf('**');
      t = t.slice(0, i) + t.slice(i + 2);
    }
    // ③ 表格行孤悬（上一行不是 | 开头）→ 前后补空行，marked/兜底都能识别
    t = t.replace(/([^\n|])\n(\|[^\n]*\|)/g, '$1\n\n$2');
    return t;
  }
  function _liteMarkdown(txt) {
    // marked 不可用时的兜底渲染器：转义后做最小 markdown 子集，
    // 永不源码直出（**→<b>、##→标题、|...|→表格行、- →列表、`x`→code）
    var t = String(txt || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    var lines = t.split('\n');
    var out = [], inCode = false, codeBuf = [];
    var inTable = false, tableRows = [];
    var inList = false;
    var flushTable = function () {
      if (!tableRows.length) return;
      var h = '<table class="lite-md-table">';
      for (var r = 0; r < tableRows.length; r++) {
        var cells = tableRows[r].replace(/^\||\|$/g, '').split('|');
        if (/^[\s:|-]+$/.test(tableRows[r])) continue;  // 分隔行跳过
        h += '<tr>';
        for (var c = 0; c < cells.length; c++) {
          h += '<td>' + _liteInline(cells[c].trim()) + '</td>';
        }
        h += '</tr>';
      }
      h += '</table>';
      out.push(h);
      tableRows = [];
      inTable = false;
    };
    var flushList = function () {
      if (inList) { out.push('</ul>'); inList = false; }
    };
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i];
      // 围栏代码
      if (/^\s*```/.test(ln)) {
        if (inCode) { out.push('<pre class="lite-md-code">' + codeBuf.join('\n') + '</pre>'); codeBuf = []; inCode = false; }
        else { flushTable(); flushList(); inCode = true; }
        continue;
      }
      if (inCode) { codeBuf.push(ln); continue; }
      // 表格行
      if (/^\s*\|.*\|\s*$/.test(ln)) {
        flushList();
        tableRows.push(ln.trim());
        inTable = true;
        continue;
      }
      if (inTable) flushTable();
      // 标题
      var h = ln.match(/^(#{1,4})\s+(.*)/);
      if (h) { flushList(); out.push('<div class="lite-md-h lite-md-h' + h[1].length + '">' + _liteInline(h[2]) + '</div>'); continue; }
      // 列表
      var li = ln.match(/^\s*[-*•]\s+(.*)/);
      if (li) {
        if (!inList) { out.push('<ul class="lite-md-ul">'); inList = true; }
        out.push('<li>' + _liteInline(li[1]) + '</li>');
        continue;
      }
      flushList();
      // 分割线 / 空行 / 段落
      if (/^\s*(-{3,}|\*{3,})\s*$/.test(ln)) { out.push('<hr class="lite-md-hr">'); continue; }
      if (ln.trim() === '') { continue; }
      out.push('<p class="lite-md-p">' + _liteInline(ln) + '</p>');
    }
    if (inCode) out.push('<pre class="lite-md-code">' + codeBuf.join('\n') + '</pre>');
    flushTable();
    flushList();
    return out.join('');
  }
  function _liteInline(s) {
    return String(s || '')
      .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
  }
  function _mdRender(txt) {
    var t = _balanceMarkdown(txt);
    try {
      if (window.marked && window.marked.parse) {
        return window.marked.parse(t, { breaks: true, gfm: true });
      }
    } catch (e) {}
    return _liteMarkdown(t);
  }
  function _buildThinkNode(tb, idx, text, live) {
    var nd = document.createElement('div');
    nd.className = 'think-node open';
    var head = document.createElement('div');
    head.className = 'tn-head';
    head.innerHTML = '<span class="tn-no">' + idx + '</span>' +
      (live ? '<span class="tn-live">思考中…</span>' : '') +
      '<span class="tn-caret">收起</span>';
    var body = document.createElement('div');
    body.className = 'tn-body';
    body.innerHTML = _mdRender(text);
    head.onclick = function () {
      var open = nd.classList.toggle('open');
      head.querySelector('.tn-caret').textContent = open ? '收起' : '展开';
      scrollBottom();
    };
    nd.appendChild(head);
    nd.appendChild(body);
    return nd;
  }
  function _renderThinkNodes(tb, raw) {
    var paras = String(raw || '').split(/\n{2,}/).filter(function (s) { return s.trim().length > 0; });
    if (paras.length < 2) {
      // 不足两段：整块渲染
      tb.innerHTML = _mdRender(raw);
      tb._noded = false;
      setProcPreview(String(raw || '').split('\n').pop());
      return;
    }
    if (!tb._noded) {
      // 首次节点化：全部段建节点
      tb.innerHTML = '';
      tb._nodes = [];
      for (var i = 0; i < paras.length; i++) {
        var nd = _buildThinkNode(tb, i + 1, paras[i], i === paras.length - 1);
        tb.appendChild(nd);
        tb._nodes.push(nd);
      }
      tb._noded = true;
    } else {
      // 流式增量：仅更新最后节点文本（用户手动收起的前序节点不被重绘）
      var lastNd = tb._nodes[tb._nodes.length - 1];
      var newCount = paras.length;
      if (newCount > tb._nodes.length) {
        // 长出新段：最后节点转正（去掉 live 标记），补新节点
        var liveEl = lastNd.querySelector('.tn-live');
        if (liveEl) liveEl.remove();
        while (tb._nodes.length < newCount) {
          var ni = tb._nodes.length;
          var nd2 = _buildThinkNode(tb, ni + 1, paras[ni], ni === newCount - 1);
          tb.appendChild(nd2);
          tb._nodes.push(nd2);
        }
      } else {
        var lb = lastNd.querySelector('.tn-body');
        if (lb) lb.innerHTML = _mdRender(paras[paras.length - 1]);
      }
    }
    // 折叠态预览行：最后段最后一行
    var tail = paras[paras.length - 1].split('\n').filter(function (s) { return s.trim(); }).pop() || '';
    setProcPreview(tail);
  }
  function addThinking(ev) {
    closeText(); closeGroup(); clearStatus();
    var r = ensureRun(); if (!r) return;
    if (!r._thinkStart) { r._thinkStart = Date.now(); }
    r._thinkMs = Date.now() - r._thinkStart;
    setProcDot('live');
    setProcTitle('深度思考中');
    setProcStats();
    // ★ v5 修复"思考串轮"：思考节点只在【当前轮】作用域内查找/追加。
    //   此前用 r.querySelector 全局查找 → 第 2 轮所有 delta 都追加到第 1 轮节点。
    var pr = processRoot();
    var existing = pr ? pr.querySelector('.trace-think') : null;
    if (existing && ev.delta) {
      var tb = existing.querySelector('.th-body');
      if (tb) {
        if (tb._raw == null) tb._raw = tb.textContent;
        tb._raw += String(ev.content || '');
        // 尾部 8KB 保留（对齐微信版），避免超长思考撑爆 DOM
        if (tb._raw.length > 8192) tb._raw = tb._raw.slice(-8192);
        _renderThinkNodes(tb, tb._raw);
        if (!existing.classList.contains('open')) {
          existing.classList.add('open');
          var st0 = existing.querySelector('.th-state'); if (st0) st0.textContent = '收起';
        }
        existing._live = true;
        scrollBottom();
      }
      return;
    }
    if (existing && !ev.delta) {
      if (existing._live) return;  // 实时流已展示，全量不再重发
      var old = existing.parentNode; existing.remove();
      // 继续走下方整体渲染（旧版一次性内容）
    }
    var node = document.createElement('div');
    node.className = 'trace-think';
    node.innerHTML =
      '<div class="th-head"><span class="th-icon">🧠</span><span class="th-title">思考过程</span>' +
      '<span class="th-state">展开</span></div>' +
      '<div class="th-body"></div>';
    var body = node.querySelector('.th-body');
    body._raw = String(ev.content || '');
    _renderThinkNodes(body, body._raw);
    // ★ v5: 思考默认常驻展开 —— 出结论后不再被折叠，"展开的内容"不会消失。
    node.classList.add('open');
    node.querySelector('.th-state').textContent = '收起';
    node.querySelector('.th-head').onclick = function () {
      var open = node.classList.toggle('open');
      node.querySelector('.th-state').textContent = open ? '收起' : '展开';
      scrollBottom();
    };
    if (pr) pr.appendChild(node);
    scrollBottom();
  }

  function renderFinal(ev) {
    closeText();
    closeGroup();
    clearStatus();
    stopElapsed();
    hideAllEmptyProcesses();  // ★ Lemon Work: 结论落地前清扫全区域空过程层
    var r = ensureRun(); if (!r) return;
    var content = String(ev.content || '');
    // ★ 第348章补丁: 结论去重 — 已流式展示的叙事前缀不再重复渲染
    //   ★ v353: 叙述已 markdown 化，textContent 与原文不再逐字相等，
    //   去重改用 _raw（流式原始累计文本）
    var _shown = '';
    var _narrs = r.querySelectorAll('.trace-text');
    for (var _i = 0; _i < _narrs.length; _i++) {
      _shown += (_narrs[_i]._raw || _narrs[_i].textContent || '');
    }
    if (!ev.html && _shown && _shown.length > 30) {
      var _tail = _shown.slice(-Math.min(_shown.length, Math.floor(content.length)));
      var _a = _tail.replace(/\s+/g, ''), _b = content.replace(/\s+/g, '');
      if (_a && _b.indexOf(_a) === 0) {
        var _cut = Math.floor(_a.length * (content.length / _b.length));
        var _rem = content.slice(_cut);
        content = (_rem.replace(/\s+/g, '').length < 40) ? content : _rem;
      }
    }
    // ★ 空结论兜底（2026-08-30）: 工具超时/快速结束时结论可能为空 —— 给明确提示，
    //   避免空白结论卡被误认为"没输出"
    if (!ev.html && !content.trim()) {
      content = '（本次运行没有产出文本结论：通常是工具超时或提前终止。上方过程层有已完成的工具结果，可据此继续提问。）';
    }
    var node = document.createElement('div');
    node.className = 'trace-final';
    node.innerHTML = '<div class="tf-badge">结论</div><div class="tf-body"></div>' +
      '<div class="tf-actions"><button class="tf-copy">复制全文</button>' +
      '<button class="tf-regen">↻ 重新生成</button></div>';
    var body = node.querySelector('.tf-body');
    if (ev.html) {
      body.innerHTML = ev.html;
    } else {
      // ★ 第348章补丁: marked.parse（gfm 表格/breaks），修复表格/标题源码显示
      try {
        if (window.marked && window.marked.parse) {
          body.innerHTML = window.marked.parse(content, { breaks: true, gfm: true });
        } else {
          body.innerHTML = '<pre style="white-space:pre-wrap">' + esc(content) + '</pre>';
        }
      } catch (_e) {
        body.innerHTML = '<pre style="white-space:pre-wrap">' + esc(content) + '</pre>';
      }
    }
    node.querySelector('.tf-copy').onclick = function () {
      var btn = this;
      try {
        (navigator.clipboard || {}).writeText ?
          navigator.clipboard.writeText(content) :
          (function (t) { var ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); })(content);
        btn.textContent = '✓ 已复制';
        setTimeout(function () { btn.textContent = '复制全文'; }, 1200);
      } catch (e2) {}
    };
    // ★ v351: 重新生成（微信版 quick-row 对齐）
    var regenBtn = node.querySelector('.tf-regen');
    if (regenBtn) {
      regenBtn.onclick = function () {
        var btn2 = this;
        btn2.disabled = true;
        btn2.textContent = '↻ 已提交…';
        if (typeof window._callPython === 'function') {
          window._callPython('regenerateLast', '', function () {
            btn2.disabled = false;
            btn2.textContent = '↻ 重新生成';
          });
        } else {
          btn2.disabled = false;
          btn2.textContent = '↻ 重新生成';
        }
      };
    }
    r.appendChild(node);
    // ★ v350 漏洞修复: 超长结论折叠（微信版 fold-wrap 对齐）——
    //   >6000 字收进 max-height 容器，"展示更多/收起"切换。
    //   此前全量渲染，500 行报告直接把消息流撑到不可读。
    try {
      var _txt = body.textContent || '';
      if (_txt.length > 6000) {
        node.classList.add('fold-long');
        var fb = document.createElement('div');
        fb.className = 'tf-fold-btn';
        fb.textContent = '展示更多 ˅';
        fb.onclick = function () {
          var open = node.classList.toggle('expanded');
          fb.textContent = open ? '收起 ˄' : '展示更多 ˅';
          scrollBottom();
        };
        r.appendChild(fb);
      }
    } catch (_fe) {}
    try {
      if (typeof scanAndRenderCharts === 'function') scanAndRenderCharts(node);
      if (typeof renderMathInContainer === 'function') renderMathInContainer(node);
    } catch (e) {}
    // ★ 第350章: 图表延迟重试（首扫时容器未完成布局导致占位框空白）
    // ★ 黑屏根治 v2: 已冻结（img[data-frozen-from] 存在）则不再重扫 ——
    //   否则"冻结→重扫→重建活canvas→GPU逐出→黑屏"循环
    setTimeout(function () {
      try {
        if (node.isConnected && !node.querySelector('canvas') &&
            !node.querySelector('img[data-frozen-from]')) {
          if (typeof scanAndRenderCharts === 'function') scanAndRenderCharts(node);
        }
      } catch (_e2) {}
    }, 900);
    scrollBottom();
  }

  // ★ v350 微信版 V1.9 对齐: usage 品牌小卡片 —— 输入/输出/缓存 token ·
  //   轮数 · 工具数 · 耗时 · 费用，两行格子形态（替代旧 trace-meta 灰行）。
  function renderMeta(ev) {
    var r = ensureRun(); if (!r) return;
    var node = document.createElement('div');
    node.className = 'usage-card';
    var row1 =
      '<span class="uc-cell">输入 ' + (ev.input_tokens || 0) + ' tok</span>' +
      '<span class="uc-cell">输出 ' + (ev.output_tokens || 0) + ' tok</span>' +
      ((ev.cache_hit_tokens || 0) > 0 ? '<span class="uc-cell uc-gold">缓存命中 ' + ev.cache_hit_tokens + '</span>' : '');
    var row2 =
      '<span class="uc-cell">' + (ev.iterations || 0) + ' 轮 · ' + (ev.tools || 0) + ' 次工具</span>' +
      '<span class="uc-cell">' + (ev.total_time || 0) + 's</span>' +
      ((ev.context_tokens || 0) > 0 ? '<span class="uc-cell">上下文 ' + (ev.context_tokens / 1000).toFixed(1) + 'k tok</span>' : '') +
      (ev.cost ? '<span class="uc-cell uc-gold">≈¥' + ev.cost + '</span>' : '') +
      (ev.success === false ? '<span class="uc-cell uc-bad">✗ 异常结束</span>' : '');
    node.innerHTML = '<div class="uc-mark">◆</div><div class="uc-main">' +
      '<div class="uc-row">' + row1 + '</div>' +
      '<div class="uc-row">' + row2 + '</div></div>';
    r.appendChild(node);
    scrollBottom();
  }

  // ★ 渲染窗口（微信版 RENDER_WINDOW=30 对齐）：超过 30 个 agent-run 移除最早
  function trimRenderWindow() {
    var a = area(); if (!a) return;
    var runs = a.querySelectorAll('.agent-run');
    for (var i = 0; i < runs.length - 30; i++) runs[i].remove();
  }

  // ★ v3: 图表滚动重绘
  (function () {
    var a = area();
    if (!a || a._trChartHook) return;
    a._trChartHook = true;
    var t = null;
    a.addEventListener('scroll', function () {
      if (t) return;
      t = setTimeout(function () {
        t = null;
        try {
          var finals = a.querySelectorAll('.trace-final');
          for (var i = 0; i < finals.length; i++) {
            // ★ 黑屏根治 v2: 已冻结（有 img）不重扫，杜绝滚动触发重建活 canvas
            if (finals[i].querySelector('.chart-marker') && !finals[i].querySelector('canvas') &&
                !finals[i].querySelector('img[data-frozen-from]')) {
              if (typeof scanAndRenderCharts === 'function') scanAndRenderCharts(finals[i]);
            }
          }
        } catch (e) {}
      }, 350);
    }, { passive: true });
  })();

  window.TraceRenderer = {
    v: 349,
    consume: function (ev) {
      try {
        if (!ev || !ev.kind) return;
        switch (ev.kind) {
          case 'run_start':
            stopElapsed();
            hideProcessIfEmpty();  // ★ Lemon Work: 上一个空 run 的过程层就地隐藏
            runEl = null; textEl = null; groupEl = null; processEl = null; roundBodyEl = null;
            ensureRun(ev);
            break;
          case 'thinking':
            addThinking(ev);
            break;
          case 'round':
            // ★ Lemon Work: 多层白盒 —— 每轮一个小节，思考/工具/叙述嵌套其内
            openRound(ev);
            break;
          case 'status': {
            // ★ 状态行（对齐 CodeBuddy "等待模型响应..." 的可见状态字样）
            closeGroup();
            clearStatus();
            var p5 = processRoot(); if (!p5) break;
            var s5 = document.createElement('div');
            s5.className = 'trace-status';
            s5.innerHTML = '<span class="ts-spin"></span><span class="ts-text">' + esc(ev.text || '处理中...') + '</span>';
            p5.appendChild(s5);
            statusEl = s5;
            scrollBottom();
            break;
          }
          case 'text_delta':
            closeGroup();  // ★ Trae: 工具组结束后叙述文本回到正常流
            var t = openText(); if (!t) return;
            // ★ v353 乱码根治: 叙述也是 markdown —— 此前 esc() 直出导致
            //   **加粗**、## 标题、|表格| 源码裸奔；现累计 _raw 全量重渲。
            t._raw = (t._raw || '') + String(ev.text || '');
            if (t._raw.length > 20000) t._raw = t._raw.slice(-20000);
            t.innerHTML = _mdRender(t._raw);
            scrollBottom();
            break;
          case 'tool_start': {
            // 运行中: 打开对应分组（同类合并），子项转圈
            closeText();
            if (!groupEl || groupEl._ttype !== (ev.ttype || 'tool')) openGroup(ev);
            if (groupEl) {
              groupEl._count++;
              var items = groupEl.querySelector('.tg-items');
              var item = document.createElement('div');
              item.className = 'tg-item running';
              item.innerHTML =
                '<span class="ti-spin"></span>' +
                '<span class="ti-text">' + esc(itemLine(ev)) + '</span>';
              item._name = ev.name;
              items.appendChild(item);
              var lbl = groupEl.querySelector('.tg-label');
              if (lbl) lbl.textContent = GROUP_DOING[ev.ttype] || '正在执行';
              // ★ v350: 动作短语（微信版 D5）—— 头部标题实时反映当前动作
              setProcDot('run');
              setProcTitle((ACTION_VERB[ev.ttype || 'tool'] || '正在调用') + ' ' + itemLine(ev));
              setProcStats();
              scrollBottom();
            }
            break;
          }
          case 'tool_end': {
            // 完成最近一个同名 running 子项（转圈→✓），否则新增完成子项
            var it = null;
            if (groupEl) {
              var ris = groupEl.querySelectorAll('.tg-item.running');
              for (var i = ris.length - 1; i >= 0; i--) {
                if (ris[i]._name === ev.name) { it = ris[i]; break; }
              }
            }
            var ok = ev.ok !== false;
            collectFromTool(groupEl, ev.arg, ev.result);
            if (groupEl && !groupEl._first) groupEl._first = toolLabel(ev);
            if (groupEl && !ok) groupEl._fails = (groupEl._fails || 0) + 1;
            if (it) {
              it.classList.remove('running');
              it.classList.add(ok ? 'done' : 'fail');
              var sp = it.querySelector('.ti-spin');
              if (sp) { sp.outerHTML = '<span class="ti-icon">' + (ICONS['check'] || '✓') + '</span>'; }
              var tt = it.querySelector('.ti-text');
              if (tt) {
                var _lbl = itemLine(ev);
                if (tt.textContent !== _lbl) tt.textContent = _lbl;
              }
              if (ev.err && !it.querySelector('.ti-err')) {
                var es = document.createElement('span');
                es.className = 'ti-err';
                es.textContent = '（' + ev.err + '）';
                var _d0 = it.querySelector('.ti-dur');
                if (_d0) it.insertBefore(es, _d0); else it.appendChild(es);
              }
              if (ev.ms) {
                var d2 = document.createElement('span');
                d2.className = 'ti-dur';
                d2.textContent = fmtDur(ev.ms);
                it.appendChild(d2);
              }
              bindItemDetail(it, ev, ev.result);
            } else {
              addToolToGroup(ev, ok, ev.ms, ev.result, ev.rejected);
            }
            updateProgress();
            setProcStats();   // ★ v350: 头部计数联动
            break;
          }
          case 'final': renderFinal(ev); break;
          case 'meta': renderMeta(ev); break;
          case 'bg_task': {
            // T366.1: 后台任务状态卡（运行中→完成/失败）
            if (ev.status === 'running') {
              var a2 = area(); if (!a2) break;
              var bgR = document.createElement('div');
              bgR.className = 'trace-bg-task running';
              bgR.setAttribute('data-tid', ev.task_id || '');
              bgR.innerHTML = '<span class="ts-spin"></span>' +
                '<span style="color:#4dd0e1;font-size:12px;">后台任务运行中: ' + esc(ev.name || '') + '</span>';
              var p6 = processRoot();
              if (p6) p6.appendChild(bgR); else a2.appendChild(bgR);
              scrollBottom();
            } else if (ev.status === 'completed' || ev.status === 'failed') {
              var a3 = area(); if (!a3) break;
              // remove running indicator
              var existing = a3.querySelector('.trace-bg-task[data-tid="' + (ev.task_id || '') + '"]');
              if (existing) existing.remove();
              var ok2 = ev.status === 'completed';
              var card = document.createElement('div');
              card.className = 'trace-bg-task ' + (ok2 ? 'done' : 'fail');
              card.innerHTML = '<div style="padding:8px 10px;background:' +
                (ok2 ? 'rgba(102,187,106,0.08);border:1px solid rgba(102,187,106,0.3)' : 'rgba(255,82,82,0.08);border:1px solid rgba(255,82,82,0.3)') +
                ';border-radius:6px;font-size:12px;">' +
                '<div style="color:' + (ok2 ? '#66bb6a' : '#ff5252') + ';font-weight:600;">' +
                (ok2 ? '✓ 后台任务完成' : '✗ 后台任务失败') + '</div>' +
                '<div style="color:#b0b0b0;margin-top:4px;">' + esc(ev.name || '') + '</div>' +
                (ok2 && ev.result_preview ? '<div style="color:#cfcfcf;margin-top:2px;max-height:60px;overflow:hidden;">' + esc(ev.result_preview) + '</div>' : '') +
                (!ok2 && ev.error ? '<div style="color:#ff8a80;margin-top:2px;">' + esc(ev.error) + '</div>' : '') +
                '</div>';
              a3.appendChild(card);
              scrollBottom();
            }
            break;
          }
          case 'run_end':
            closeText(); closeGroup(); clearStatus();
            stopElapsed();
            hideProcessIfEmpty();
            if (runEl) {
              var e3 = runEl.querySelector('.ar-elapsed');
              if (e3) e3.textContent = fmtDur(Date.now() - runT0) || e3.textContent;
              runEl.classList.add(ev.ok ? 'is-ok' : 'is-bad');
              var dot = runEl.querySelector('.ar-dot');
              if (dot) dot.classList.add(ev.ok ? 'ok' : 'bad');
            }
            // ★ v350: 统一过程头收口（微信版"已深度思考与执行"）——
            //   灯转绿、标题定格、折叠态预览行退场。
            //   注意：hideProcessIfEmpty 会把 processEl 置空，故从 runEl 查询。
            (function () {
              var ph = runEl ? runEl.querySelector('.proc-head') : null;
              if (ph) {
                var dd = ph.querySelector('.proc-dot');
                if (dd) dd.className = 'proc-dot proc-dot-done';
                var tt = ph.querySelector('.proc-title');
                if (tt) tt.textContent = ev.ok ? '已深度思考与执行' : '执行异常终止';
              }
              if (runEl) {
                var pv = runEl.querySelector('.proc-preview');
                if (pv) pv.style.display = 'none';
              }
            })();
            runEl = null; textEl = null; groupEl = null; processEl = null; roundBodyEl = null;
            trimRenderWindow();   // ★ v350: 渲染窗口裁剪（保留最近 30 个 run）
            break;
          case 'narrative': {
            // ★ v350 微信版时间线对齐: 过程时间线 —— 播报 ↔ 工具统计交替。
            //   后端每轮结束时 emit {text, tools:[{name,ok,ms}]}。
            closeText(); closeGroup();
            var p7 = processRoot(); if (!p7) break;
            var nw = p7.querySelector('.narr-wrap');
            if (!nw) {
              nw = document.createElement('div');
              nw.className = 'narr-wrap';
              var nh = document.createElement('div');
              nh.className = 'narr-head';
              nh.innerHTML = '<span class="narr-head-text">过程时间线 · 0 段</span>' +
                '<span class="narr-head-caret">收起</span>';
              var nlist = document.createElement('div');
              nlist.className = 'narr-list';
              nh.onclick = function () {
                var open = nlist.style.display !== 'none';
                nlist.style.display = open ? 'none' : 'block';
                nh.querySelector('.narr-head-caret').textContent = open ? '展开' : '收起';
                scrollBottom();
              };
              nw.appendChild(nh);
              nw.appendChild(nlist);
              p7.appendChild(nw);
            }
            var nlist2 = nw.querySelector('.narr-list');
            var ncount = nw.querySelectorAll('.narr-item').length + 1;
            var head0 = nw.querySelector('.narr-head-text');
            if (head0) head0.textContent = '过程时间线 · ' + ncount + ' 段';
            var ni2 = document.createElement('div');
            ni2.className = 'narr-item';
            var th2 = '<div class="narr-text-row"><span class="narr-caret"></span>' +
              '<span class="narr-text">' + esc(ev.text || '') + '</span></div>';
            if (ev.tools && ev.tools.length) {
              th2 += '<div class="narr-tools">';
              for (var ti = 0; ti < ev.tools.length && ti < 8; ti++) {
                var nt = ev.tools[ti];
                th2 += '<span class="narr-tool"><span class="narr-tool-dot ' +
                  (nt.ok === false ? 'narr-tool-dot-fail' : '') + '"></span>' +
                  esc(toolCN(nt.name)) + (nt.ms ? ' · ' + fmtDur(nt.ms) : '') + '</span>';
              }
              th2 += '</div>';
            }
            ni2.innerHTML = th2;
            nlist2.appendChild(ni2);
            scrollBottom();
            break;
          }
          case 'full_result': {
            // ★ v350: 全量结果浮层（微信版"工具结果全量"对齐）
            showFullResultPanel(ev.title || '工具结果全量', String(ev.text || ''));
            break;
          }
        }
      } catch (e) {
        try { console.log('[TraceRenderer]', e); } catch (e2) {}
      }
    }
  };
})();



// ==================== ★第404章 ActionCard 动态操作卡 ====================
// 生成式 UI：Agent 经 ui_action_card 技能实时生成按钮卡（非硬编码），
// 卡片 DOM 属于消息流 → 随页面滑动；点击走事件委托 → 滑回历史会话依然有效。
(function() {
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  // Python → JS：渲染卡片（来自 ui_action_card / web_preview 技能，按 type 分流）
  window.onActionCard = function(card) {
    try {
      if (card && card.type === 'web_page_card') { renderWebPageCard(card); return; }
      if (card && card.type === 'chart_card') { renderChartCard(card); return; }   // ★第416章
      if (card && card.type === 'form_card') { renderFormCard(card); return; }     // ★第416章
      if (!card || !card.buttons || !card.buttons.length) return;
      var area = document.getElementById('outputMessages');
      if (!area) return;
      var wrap = document.createElement('div');
      wrap.className = 'action-card';
      wrap.setAttribute('data-card-id', card.card_id || '');
      // ★第414章: 精致化结构——头部（柠檬标+标题+ACTION徽标）/按钮/注释
      var html =
        '<div class="ac-head">' +
          '<span class="ac-lemon"></span>' +
          '<span class="ac-title">' + esc(card.title) + '</span>' +
          '<span class="ac-badge">ACTION</span>' +
        '</div>';
      for (var i = 0; i < card.buttons.length; i++) {
        var b = card.buttons[i];
        html += '<button class="ac-btn' + (b.confirm ? ' ac-btn-confirm' : '') +
                '" data-action="' + esc(b.action) + '"' +
                ' data-params="' + esc(JSON.stringify(b.params || {})) + '">' +
                '<span class="ac-btn-ico">' + (b.confirm ? '⚠' : '▸') + '</span>' +
                '<span class="ac-btn-label">' + esc(b.label) + '</span>' +
                '</button>';
      }
      if (card.note) html += '<div class="ac-note">' + esc(card.note) + '</div>';
      wrap.innerHTML = html;
      area.appendChild(wrap);
      area.scrollTop = area.scrollHeight;
    } catch (e) { console.warn('[ActionCard] 渲染失败:', e); }
  };

  // 事件委托：历史消息里的按钮重渲染后依然有效（不逐卡绑定）
  document.addEventListener('click', function(e) {
    var btn = e.target.closest ? e.target.closest('.ac-btn') : null;
    if (!btn || typeof window._callPython !== 'function') return;
    if (btn.getAttribute('data-form') === '1') return; // ★第416章: 表单提交按钮走专属委托
    if (btn.classList.contains('ac-btn-loading')) return; // 执行中防重复点击
    var payload = {
      card_id: btn.closest('.action-card') ? btn.closest('.action-card').getAttribute('data-card-id') : '',
      action: btn.getAttribute('data-action'),
      params: JSON.parse(btn.getAttribute('data-params') || '{}')
    };
    if (btn.classList.contains('ac-btn-confirm') && !btn.dataset.armed) {
      btn.dataset.armed = '1';
      btn.classList.add('ac-btn-armed');
      var old = btn.textContent;
      btn.textContent = '再点一次确认执行';
      setTimeout(function() {
        btn.dataset.armed = ''; btn.classList.remove('ac-btn-armed');
        btn.textContent = old;
      }, 3000);
      return; // 高危动作首次点击只进入待确认态
    }
    payload.confirmed = true;
    window._callPython('sendMessage', '__action_card__:' + JSON.stringify(payload));
    // ★第415章: 进入执行中态——按钮转 spinner，结果回来由 actionCardResult 就地解除
    btn.dataset.origHtml = btn.innerHTML;
    btn.classList.add('ac-btn-loading');
    btn.innerHTML = '<span class="ac-spinner"></span><span class="ac-btn-label">执行中…</span>';
    // 安全阀：若 Python 侧 12s 未回结果，自动解除 loading（防永久卡死）
    setTimeout(function() {
      if (btn.classList.contains('ac-btn-loading')) {
        btn.classList.remove('ac-btn-loading');
        if (btn.dataset.origHtml) { btn.innerHTML = btn.dataset.origHtml; }
      }
    }, 12000);
  }, true);

  // Python → JS：执行结果就地回显（★第415章 状态机——结果进入卡片内部而非另起消息）
  window.actionCardResult = function(res, cardId) {
    try {
      var area = document.getElementById('outputMessages');
      if (!area) return;
      // 定位卡片并解除执行中态
      var card = null;
      try {
        var sel = '.action-card[data-card-id="' + String(cardId || '').replace(/"/g, '') + '"]';
        card = area.querySelector(sel) || area.querySelector('.action-card.ac-last-clicked');
      } catch (err) { card = null; }
      var busyBtns = document.querySelectorAll('.ac-btn-loading');
      for (var bi = 0; bi < busyBtns.length; bi++) {
        var bb = busyBtns[bi];
        var inTarget = !card || (card && bb.closest('.action-card') === card);
        var aidMatch = !(res && res.action_id) || bb.getAttribute('data-action') === res.action_id;
        if (inTarget && aidMatch) {
          bb.classList.remove('ac-btn-loading');
          if (bb.dataset.origHtml) { bb.innerHTML = bb.dataset.origHtml; }
        }
      }
      // 结果渲染：结构化数据→键值行；否则文本
      var tip = document.createElement('div');
      var ok = res && res.success;
      tip.className = 'ac-result' + (ok ? ' ac-ok' : (res && res.confirm_required ? ' ac-warn' : ' ac-err'));
      if (ok) {
        var dataObj = null;
        if (res.result_data && typeof res.result_data === 'object') dataObj = res.result_data;
        else if (res.data && typeof res.data === 'object' && Object.keys(res.data).length) dataObj = res.data;
        var head = res.message || res.output || res.result || '操作完成';
        var kvHtml = '<div class="ac-r-head">✓ ' + esc(String(head)) + '</div>';
        if (dataObj) {
          var keys = Object.keys(dataObj).filter(function(k) {
            return k !== 'action_id' && k !== 'success' && k !== 'message'
                && k !== 'risk' && k !== 'audit_id';
          });
          if (keys.length) {
            kvHtml += '<div class="ac-kv-wrap">';
            for (var ki = 0; ki < Math.min(keys.length, 8); ki++) {
              var v = dataObj[keys[ki]];
              var vStr = (v === null || v === undefined) ? '—'
                : (typeof v === 'object' ? JSON.stringify(v) : String(v));
              if (vStr.length > 60) vStr = vStr.slice(0, 60) + '…';
              kvHtml += '<div class="ac-kv"><span class="ac-kv-k">' + esc(keys[ki]) +
                        '</span><span class="ac-kv-v">' + esc(vStr) + '</span></div>';
            }
            kvHtml += '</div>';
          }
        }
        tip.innerHTML = kvHtml;
      } else {
        tip.textContent = res && res.confirm_required
          ? ('⚠ ' + (res.message || '需要确认'))
          : ('✗ ' + ((res && res.error) || '操作失败'));
      }
      // 就地插入：卡片内结果区（替换旧结果）；无卡片则兜底追加消息流
      if (card) {
        var zone = card.querySelector('.ac-result-zone');
        if (!zone) {
          zone = document.createElement('div');
          zone.className = 'ac-result-zone';
          card.appendChild(zone);
        }
        zone.innerHTML = '';
        zone.appendChild(tip);
      } else {
        area.appendChild(tip);
      }
      area.scrollTop = area.scrollHeight;
    } catch (e) { console.warn('[ActionCard] 结果回显失败:', e); }
  };

// ★第408章 WebPageCard：对话内网页卡（标题+摘要+展开净化HTML+原文链接）
  function renderWebPageCard(card) {
    var area = document.getElementById('outputMessages');
    if (!area) return;
    var wrap = document.createElement('div');
    wrap.className = 'web-page-card';
    wrap.setAttribute('data-card-id', card.card_id || '');
    // ★第424章: live 活页嵌入模式 —— iframe 直连目标服务（如数字银行操作台），
    //   页面自带 JS 照常运行（数据实时刷新），与静态净化快照（srcdoc）分流。
    //   仅当卡片显式携带 live:true 时启用（可信同机服务）。
    if (card.live && card.url) {
      // ★第435章: 双视图 —— iframe 真实网页为主视图（main.py Chromium 旗标
      //   --allow-running-insecure-content 授权 file:// 宿主嵌 http://127.0.0.1，
      //   银行侧无 X-Frame-Options/CSP 天然可嵌）；430 原生数据面板降为备用视图
      //   （tab 切换 + 轮询懒启动）。iframe 若仍被环境拦截（空白），一键切面板，
      //   双向互动能力不丢失。
      var base = card.url.replace(/\/$/, '');
      wrap.innerHTML =
        '<div class="ac-head">' +
          '<span class="ac-lemon"></span>' +
          '<span class="ac-title">' + esc(card.title || '实时页面') + '</span>' +
          '<span class="ac-badge ac-badge-live">LIVE</span>' +
          '<span class="lv-tabs">' +
            '<button class="lv-tab lv-tab-web on">网页</button>' +
            '<button class="lv-tab lv-tab-panel">面板</button>' +
          '</span>' +
          '<span class="lv-collapse" title="收起/展开">▾</span>' +
        '</div>' +
        '<div class="ac-wp-url">' + esc(base) + '</div>' +
        '<div class="lv-web"><iframe class="lv-frame" src="' + esc(base) + '/"' +
          ' referrerpolicy="no-referrer"></iframe></div>' +
        '<div class="lv-panel" style="display:none">' +
          '<div class="ac-live-body"><div class="empty">连接银行中…</div></div>' +
          '<div class="ac-live-form">' +
            '<input class="lv-to" placeholder="收款账号 ACC00x" size="14">' +
            '<input class="lv-amt" placeholder="金额(元)" type="number" size="8">' +
            '<button class="ac-btn lv-go"><span class="ac-btn-ico">▸</span>' +
            '<span class="ac-btn-label">转账</span></button>' +
            '<span class="lv-msg"></span>' +
          '</div>' +
          '<div class="ac-live-foot">每 3 秒自动刷新 · 也可直接让我代你操作</div>' +
        '</div>';
      area.appendChild(wrap);
      area.scrollTop = area.scrollHeight;
      // 视图切换：面板懒启动轮询（iframe 正常工作时零额外请求）
      var polled = false;
      function _pollOnce() {
        if (!polled) { polled = true; try { startLivePoll(wrap, base); } catch (e) { console.warn('[LIVE] 轮询失败:', e); } }
      }
      wrap.querySelector('.lv-tab-web').addEventListener('click', function () {
        wrap.querySelector('.lv-web').style.display = '';
        wrap.querySelector('.lv-panel').style.display = 'none';
        this.classList.add('on');
        wrap.querySelector('.lv-tab-panel').classList.remove('on');
      });
      wrap.querySelector('.lv-tab-panel').addEventListener('click', function () {
        wrap.querySelector('.lv-web').style.display = 'none';
        wrap.querySelector('.lv-panel').style.display = '';
        this.classList.add('on');
        wrap.querySelector('.lv-tab-web').classList.remove('on');
        _pollOnce();
      });
      // ★ Lemon Work: 页面卡可折叠（微信版 web-view 横条式）——
      //   收起时 iframe 高度塌陷，对话流不再被整屏推开
      wrap.querySelector('.lv-collapse').addEventListener('click', function () {
        var folded = wrap.classList.toggle('collapsed');
        this.textContent = folded ? '▸' : '▾';
      });
      return;
    }
    // ★第427章: autopen 快照卡 —— 呈现型卡片默认展开 iframe（用户直接看到界面）
    var autoFrame = card.autopen && card.clean_html
      ? '<iframe class="ac-wp-frame" sandbox="" srcdoc="' +
        esc(card.clean_html) + '"></iframe>' : '';
    var openBtn = autoFrame ? '' :
      '<button class="ac-btn ac-wp-expand" data-html="' +
      esc(card.clean_html || '') + '">在对话中展开阅读</button> ';
    wrap.innerHTML =
      '<div class="ac-head">' +
        '<span class="ac-lemon"></span>' +
        '<span class="ac-title">' + esc(card.title || '网页') + '</span>' +
        '<span class="ac-badge">' + (autoFrame ? 'SNAPSHOT' : 'WEB') + '</span>' +
      '</div>' +
      '<div class="ac-wp-url">' + esc(card.url) + '</div>' +
      '<div class="ac-note">' + esc(card.preview || '') + '</div>' +
      openBtn + autoFrame +
      '<a class="ac-wp-link" href="' + esc(card.url) + '" target="_blank" rel="noopener">打开原文</a>';
    area.appendChild(wrap);
    area.scrollTop = area.scrollHeight;
  }

  // 事件委托：展开 → iframe srcdoc 沙箱（sandbox 禁脚本，净化 HTML 双保险）
  document.addEventListener('click', function(e) {
    var btn = e.target.closest ? e.target.closest('.ac-wp-expand') : null;
    if (!btn) return;
    var wrapEl = btn.closest('.web-page-card');
    if (!wrapEl) return;
    var old = wrapEl.querySelector('.ac-wp-frame');
    if (old) { old.remove(); btn.textContent = '在对话中展开阅读'; return; }
    var frame = document.createElement('iframe');
    frame.className = 'ac-wp-frame';
    frame.setAttribute('sandbox', '');           // 禁脚本/表单/弹窗
    frame.srcdoc = btn.getAttribute('data-html');
    btn.textContent = '收起';
    wrapEl.appendChild(frame);
    area_scroll();
  }, true);
  function area_scroll() {
    var area = document.getElementById('outputMessages');
    if (area) area.scrollTop = area.scrollHeight;
  }
  // ==================== WebPageCard 区块结束 ====================

  // ═══════════════════════════════════════════════════════════
  // ★第416章 图表卡（SVG 矢量渲染，无第三方依赖）+ 表单卡
  // ═══════════════════════════════════════════════════════════

  function card_shell(card, cls) {
    var area = document.getElementById('outputMessages');
    if (!area) return null;
    var wrap = document.createElement('div');
    wrap.className = cls;
    wrap.setAttribute('data-card-id', card.card_id || '');
    var head =
      '<div class="ac-head">' +
        '<span class="ac-lemon"></span>' +
        '<span class="ac-title">' + esc(card.title) + '</span>' +
        '<span class="ac-badge">' + (cls === 'chart-card' ? 'CHART' : 'FORM') + '</span>' +
      '</div>';
    var tail = card.note ? '<div class="ac-note">' + esc(card.note) + '</div>' : '';
    return { wrap: wrap, head: head, tail: tail, area: area };
  }

  // ---- 图表卡：line 折线（渐变面积）/ bar 柱状 ----
  function renderChartCard(card) {
    try {
      var sh = card_shell(card, 'chart-card');
      if (!sh) return;
      var s = Array.isArray(card.series) ? card.series : [];
      if (s.length < 2) return;
      var vals = s.map(function(p) { return Number(p.value) || 0; });
      var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
      if (mx === mn) { mx = mn + 1; }
      var W = 340, H = 170, PL = 46, PR = 12, PT = 14, PB = 30;
      var iw = W - PL - PR, ih = H - PT - PB;
      var unit = card.unit || '';
      var svg = '';
      if (card.chart_type === 'bar') {
        var bw = iw / s.length * 0.58;
        for (var i = 0; i < s.length; i++) {
          var bh = (vals[i] - mn) / (mx - mn) * (ih - 18) + 12;
          var x = PL + (iw / s.length) * i + (iw / s.length - bw) / 2;
          var y = PT + ih - bh;
          svg += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) +
                 '" height="' + bh.toFixed(1) + '" rx="4" fill="url(#acBarG)" opacity="0.92">' +
                 '<title>' + esc(s[i].label + ': ' + vals[i] + unit) + '</title></rect>';
          svg += '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (y - 5).toFixed(1) +
                 '" text-anchor="middle" font-size="9.5" fill="#ffcf8f">' + vals[i] + '</text>';
          if (s.length <= 12) {
            svg += '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 12) +
                   '" text-anchor="middle" font-size="9" fill="rgba(255,214,160,0.55)">' +
                   esc(s[i].label) + '</text>';
          }
        }
      } else {
        var pts = [];
        for (var j = 0; j < s.length; j++) {
          var px = PL + (s.length === 1 ? iw / 2 : iw * j / (s.length - 1));
          var py = PT + ih - ((vals[j] - mn) / (mx - mn) * (ih - 18) + 9);
          pts.push([px, py]);
        }
        var line = pts.map(function(p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ');
        var areaPts = pts.slice();
        areaPts.push([pts[pts.length - 1][0], PT + ih], [pts[0][0], PT + ih]);
        svg += '<polygon points="' + areaPts.map(function(p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ') +
               '" fill="url(#acAreaG)" opacity="0.75"/>';
        svg += '<polyline points="' + line + '" fill="none" stroke="url(#acLineG)" stroke-width="2.4" ' +
               'stroke-linecap="round" stroke-linejoin="round"/>';
        for (var k = 0; k < pts.length; k++) {
          svg += '<circle cx="' + pts[k][0].toFixed(1) + '" cy="' + pts[k][1].toFixed(1) +
                 '" r="3.2" fill="#ffd700" stroke="rgba(20,14,6,0.9)" stroke-width="1.2">' +
                 '<title>' + esc(s[k].label + ': ' + vals[k] + unit) + '</title></circle>';
          if (s.length <= 12) {
            svg += '<text x="' + pts[k][0].toFixed(1) + '" y="' + (H - 12) +
                   '" text-anchor="middle" font-size="9" fill="rgba(255,214,160,0.55)">' +
                   esc(s[k].label) + '</text>';
          }
        }
        svg += '<text x="' + PL + '" y="' + (PT + 4) + '" font-size="9" fill="rgba(255,214,160,0.6)">' + mx + unit + '</text>';
        svg += '<text x="' + PL + '" y="' + (PT + ih + 2) + '" font-size="9" fill="rgba(255,214,160,0.6)">' + mn + unit + '</text>';
      }
      sh.wrap.innerHTML =
        sh.head +
        '<svg class="ac-chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">' +
          '<defs>' +
            '<linearGradient id="acLineG" x1="0" y1="0" x2="1" y2="0">' +
              '<stop offset="0" stop-color="#ff8f00"/><stop offset="1" stop-color="#ffd700"/>' +
            '</linearGradient>' +
            '<linearGradient id="acAreaG" x1="0" y1="0" x2="0" y2="1">' +
              '<stop offset="0" stop-color="rgba(255,150,20,0.35)"/><stop offset="1" stop-color="rgba(255,150,20,0.02)"/>' +
            '</linearGradient>' +
            '<linearGradient id="acBarG" x1="0" y1="0" x2="0" y2="1">' +
              '<stop offset="0" stop-color="#ffd700"/><stop offset="1" stop-color="rgba(255,120,0,0.55)"/>' +
            '</linearGradient>' +
          '</defs>' +
          '<line x1="' + PL + '" y1="' + (PT + ih) + '" x2="' + (W - PR) + '" y2="' + (PT + ih) +
          '" stroke="rgba(255,180,90,0.3)" stroke-width="1" stroke-dasharray="3 3"/>' +
          svg +
        '</svg>' + sh.tail;
      sh.area.appendChild(sh.wrap);
      sh.area.scrollTop = sh.area.scrollHeight;
    } catch (e) { console.warn('[ChartCard] 渲染失败:', e); }
  }

  // ---- 表单卡：输入框 + 提交（走 __action_card__ 通道，confirm 门自动生效）----
  function renderFormCard(card) {
    try {
      var sh = card_shell(card, 'form-card');
      if (!sh) return;
      var fields = Array.isArray(card.fields) ? card.fields : [];
      var body = '<div class="ac-form">';
      for (var i = 0; i < fields.length; i++) {
        var f = fields[i];
        body += '<label class="ac-f-row">' +
                  '<span class="ac-f-label">' + esc(f.label) +
                  (f.required ? ' <i class="ac-f-req">*</i>' : '') + '</span>' +
                  '<input class="ac-f-input" type="' + esc(f.type || 'text') + '"' +
                  ' data-fname="' + esc(f.name) + '"' +
                  ' placeholder="' + esc(f.placeholder || '') + '"' +
                  ' value="' + esc(f.value || '') + '"' +
                  (f.required ? ' required' : '') + '/>' +
                '</label>';
      }
      body += '</div>';
      var submit = '<button class="ac-btn ac-f-submit' + (card.submit_confirm ? ' ac-btn-confirm' : '') + '"' +
                   ' data-form="1" data-action="' + esc(card.submit_action) + '">' +
                   '<span class="ac-btn-ico">' + (card.submit_confirm ? '⚠' : '▸') + '</span>' +
                   '<span class="ac-btn-label">' + esc(card.submit_label || '提交') + '</span></button>';
      sh.wrap.innerHTML = sh.head + body + submit + sh.tail;
      sh.area.appendChild(sh.wrap);
      sh.area.scrollTop = sh.area.scrollHeight;
    } catch (e) { console.warn('[FormCard] 渲染失败:', e); }
  }

  // 表单提交：收集字段 → __action_card__ 通道（专属委托；高危动作两段式确认）
  document.addEventListener('click', function(e) {
    var btn = e.target.closest ? e.target.closest('.ac-f-submit') : null;
    if (!btn || btn.classList.contains('ac-btn-loading')) return;
    var formEl = btn.closest('.form-card');
    if (!formEl || typeof window._callPython !== 'function') return;
    // ★第416章: 高危动作两段式确认（与通用 .ac-btn 委托同语义，但走表单通道收集字段）
    if (btn.classList.contains('ac-btn-confirm') && !btn.dataset.armed) {
      btn.dataset.armed = '1';
      btn.classList.add('ac-btn-armed');
      btn.dataset.origHtml2 = btn.innerHTML;
      btn.innerHTML = '<span class="ac-btn-ico">⚠</span><span class="ac-btn-label">再点一次确认执行</span>';
      setTimeout(function() {
        btn.dataset.armed = ''; btn.classList.remove('ac-btn-armed');
        if (btn.dataset.origHtml2) { btn.innerHTML = btn.dataset.origHtml2; }
      }, 3000);
      return;
    }
    var inputs = formEl.querySelectorAll('.ac-f-input');
    var params = {};
    for (var i = 0; i < inputs.length; i++) {
      var v = inputs[i].value;
      if (inputs[i].required && String(v).trim() === '') {
        inputs[i].classList.add('ac-f-err'); inputs[i].focus();
        setTimeout(function(el) { return function() { el.classList.remove('ac-f-err'); }; }(inputs[i]), 1600);
        return;
      }
      params[inputs[i].getAttribute('data-fname')] =
        inputs[i].type === 'number' ? (parseFloat(v) || 0) : v;
    }
    var payload = {
      card_id: formEl.getAttribute('data-card-id') || '',
      action: btn.getAttribute('data-action'),
      params: params,
      confirmed: true // 两段式确认已完成（或动作本就无需确认）；Python confirm 门仍兜底
    };
    window._callPython('sendMessage', '__action_card__:' + JSON.stringify(payload));
    btn.dataset.origHtml = btn.innerHTML;
    btn.classList.add('ac-btn-loading');
    btn.innerHTML = '<span class="ac-spinner"></span><span class="ac-btn-label">执行中…</span>';
    setTimeout(function() {
      if (btn.classList.contains('ac-btn-loading')) {
        btn.classList.remove('ac-btn-loading');
        if (btn.dataset.origHtml) { btn.innerHTML = btn.dataset.origHtml; }
      }
    }, 12000);
  }, true);
  // ==================== 图表卡/表单卡区块结束 ====================

  // ★第430章: live 面板轮询（fetch 银行 API → 原地渲染；CORS * 已开）
  function startLivePoll(wrap, base) {
    var body = wrap.querySelector('.ac-live-body');
    if (!body) return;
    function render(d) {
      var accs = (d && d.acc && d.acc.items) || [];
      var txs = (d && d.tx && d.tx.items) || [];
      var risks = (d && d.risk && d.risk.items) || [];
      var html = '<div class="lv-sec"><b>◈ 账户</b>' +
        (accs.length ? accs.map(function(a) {
          return '<div class="lv-row"><span>' + esc(a.owner) + '(' + esc(a.account_id) + ')</span>' +
                 '<b>¥' + a.balance_yuan + '</b></div>';
        }).join('') : '<span class="dim">无</span>') + '</div>';
      html += '<div class="lv-sec"><b>◈ 最近交易</b>' +
        (txs.length ? txs.slice(0, 8).map(function(t) {
          return '<div class="lv-row"><span>#' + t.tx_id + ' ' + esc(t.from_acc) + '→' +
                 esc(t.to_acc) + '</span><span class="' +
                 (t.status === 'success' ? 'lv-ok' : 'lv-rev') + '">¥' + t.amount_yuan + '</span></div>';
        }).join('') : '<span class="dim">暂无</span>') + '</div>';
      html += '<div class="lv-sec"><b>◈ 风控事件</b>' +
        (risks.length ? risks.slice(0, 4).map(function(r) {
          return '<div class="lv-row"><span class="' + (r.level === 'HIGH' ? 'lv-err' : 'lv-warn') +
                 '">' + esc(r.level) + ' ' + esc(r.rule) + '</span><span class="dim">' +
                 esc((r.detail || '').slice(0, 26)) + '</span></div>';
        }).join('') : '<span class="dim">正常</span>') + '</div>';
      body.innerHTML = html;
    }
    function tick() {
      if (!document.body.contains(wrap)) { clearInterval(h); return; }  // 卡片移除即停
      Promise.all([
        fetch(base + '/api/accounts').then(function(r) { return r.json(); }).catch(function() { return null; }),
        fetch(base + '/api/transactions?limit=8').then(function(r) { return r.json(); }).catch(function() { return null; }),
        fetch(base + '/api/risk-events?limit=4').then(function(r) { return r.json(); }).catch(function() { return null; })
      ]).then(function(rs) {
        if (rs[0]) render({acc: rs[0], tx: rs[1], risk: rs[2]});
      });
    }
    tick();
    var h = setInterval(tick, 3000);
  }
  // live 卡手动转账（走银行 API，双向互动的手动通道）
  document.addEventListener('click', function(e) {
    var btn = e.target.closest ? e.target.closest('.lv-go') : null;
    if (!btn) return;
    var wrapEl = btn.closest('.web-page-card');
    var base = (wrapEl && wrapEl.querySelector('.ac-wp-url') || {}).textContent || '';
    base = base.trim().replace(/\/$/, '');
    var to = wrapEl.querySelector('.lv-to').value.trim();
    var amt = Math.round(parseFloat(wrapEl.querySelector('.lv-amt').value || '0') * 100);
    var msgEl = wrapEl.querySelector('.lv-msg');
    if (!to || !amt) { msgEl.textContent = '请填账号与金额'; msgEl.className = 'lv-msg lv-err2'; return; }
    fetch(base + '/api/transfer', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({to: to, amount: amt, note: '界面手动操作'})})
      .then(function(r) { return r.json(); })
      .then(function(d) {
        msgEl.textContent = d.message || d.reason || d.error || '已完成';
        msgEl.className = 'lv-msg ' + (d.success ? 'lv-ok2' : 'lv-err2');
        if (window.actionCardResult) window.actionCardResult(
          {success: !!d.success, message: d.message, error: d.error, action_id: 'bank.transfer'},
          wrapEl.getAttribute('data-card-id'));
      })
      .catch(function(err) { msgEl.textContent = '请求失败: ' + err; msgEl.className = 'lv-msg lv-err2'; });
  }, true);
})();

