# -*- coding: utf-8 -*-
"""
Lemon Code Agent — 混合模式Web面板
加载hybrid_mode_wireframe.html并通过QWebChannel连接后端
★ v3.10 修复：使用 HybridDebugWebPage 拦截 __PYBRIDGE__ 消息，
   让前端 _callPython('agentChatWithEngine', ...) 桥接到 Python 后端 Ollama 调用
"""

import os
import re
import sys
import json
import threading
import traceback
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QObject, pyqtSlot, QMetaObject
from PyQt5.QtWebEngineWidgets import (
    QWebEngineView, QWebEngineSettings, QWebEnginePage, QWebEngineProfile,
)
from PyQt5.QtWebChannel import QWebChannel

# Windows 控制台 UTF-8（避免 print 中文崩溃）
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


# ★ v4.5 前端 H2~M5 调用 → HybridBridge 真实方法的转发清单
_BRIDGE_FORWARD_METHODS = (
    'getAgentsInfo',          # 获取 Agent 列表 (arg: filter)
    'getAgentDetail',        # 获取 Agent 详情 (arg: agent_id)
    'getWorkflowStatus',     # 工作流状态
    'getMonitorData',        # 运行监控数据
    'getOrchestratorStatus', # orchestrator 状态
    'getMultiInstanceStatus',# 多实例集群状态
    'configureAgent',        # 配置 Agent (args: agent_id, config_json)
    'addAgent',              # 新增 Agent (arg: role_key)
    'removeAgent',           # 删除 Agent (arg: agent_id)
    'pauseWorkflow',         # 暂停工作流
    'openRoleConfigDialog',  # H2 角色配置对话框 (arg: agent_id)
    'openModeSwitchDialog',  # H3 模式切换对话框
    'getRoleSkillMap',       # ★ v4.6.1 角色→可用 Skill 白名单映射
    'dispatchCrossWindowTask',     # ★ v5.P0 跨窗派发（标准/咩咩/几维鸟）
    'getCompanyArchitecture',      # ★ v5.P0 公司架构三窗状态
    'dispatchOrchestratorCrossWindow',  # ★ v5.P0 总指挥编排派发
    'getAgentRoster',              # ★ v5.P0 花名册统一数据源
    'hireAgent',                   # ★ v5.P0 入职开席
    'fireAgent',                   # ★ v5.P0 解雇关席
    'assignTask',                  # ★ v5.P0 分配任务
    'setAgentModel',               # ★ v5.P0 切换模型
    'commanderPlan',               # ★ v5.P2 策划书结构化分解
    'startCompany',                # ★ v5.P3 启动公司
    'saveRunData',                 # ★ v5.P3 保存 run 记录
    'getRunHistory',               # ★ v5.P3 run 历史
    'getAgentHealth',              # ★ v5.P3 Agent 心跳检测
    'restartAgent',                # ★ v5.P3 一键重启
    'getPoolStats',                # ★ v5.37.T1 GPU 池统计
    'getFormationConfig',          # ★ v5.37.T1 编制配置
    'getArtifacts',                # v5.37.T2 产物索引
    # ★ 2026-10 接线修复批：补齐前端真实调用的桥方法
    'getAgentOutputs',             # Agent 输出聚合（查看输出按钮）
    'setVerifyMode', 'isVerifyMode',  # 查验模式开关/读取
    'sendChat',                    # 聊天广播别名
    'stopCompany', 'stopRealInstances',  # 停转公司 / 停实例
    'fileTreeList', 'fileTreeCreate',    # 文件树真实 FS 操作
    'commanderPlanAndDispatch',    # 策划书分解+立即派发（公司主线）
    'invokeSkill', 'invokeSkillChain',   # Skill 真调用/链执行
    'listAllSkills', 'getSkillDetails',  # Skill 真清单/详情
    'getSkillCallStats', 'getSkillRouteStats',  # Skill 真统计
    'listSkillChains', 'getSkillChainDetails',  # Skill Chain 真数据
)

# ★ 2026-10：重 IO 方法（起进程/LLM/文件扫描/跨窗派发）一律后台线程执行，防卡 Qt 主线程
_BRIDGE_ASYNC_METHODS = (
    'hireAgent', 'startCompany', 'stopCompany', 'stopRealInstances',
    'commanderPlanAndDispatch', 'assignTask', 'dispatchCrossWindowTask',
    'dispatchOrchestratorCrossWindow', 'invokeSkill', 'invokeSkillChain',
    'fileTreeList', 'fileTreeCreate', 'getAgentOutputs', 'setAgentModel',
    'importConfig', 'getArtifacts', 'getCompanyArchitecture',
)


# ============================================================
# ★ v3.10 HybridDebugWebPage — 拦截 JS 控制台 __PYBRIDGE__ 消息
# ============================================================
class HybridDebugWebPage(QWebEnginePage):
    """捕获 JS 控制台日志 + Console Message Bridge（agentChatWithEngine 等）"""

    def __init__(self, parent, panel):
        super().__init__(parent)
        self._panel = panel  # HybridModeWebPanel 引用

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # ★ 修复：禁止同步 print 到 stdout（交互式终端下会阻塞主线程导致卡顿）
        # 仅在 LEMON_JS_CONSOLE=1 时输出，用于开发调试
        if os.environ.get("LEMON_JS_CONSOLE") == "1":
            level_str = {0: 'INFO', 1: 'WARN', 2: 'ERROR', 3: 'DEBUG'}.get(level, str(level))
            msg = message.strip() if message else ''
            if msg and not msg.startswith('__PYBRIDGE__:'):
                print(f"[JS {level_str}] {msg}")

        msg = (message or '').strip()
        # ★ 拦截 __PYBRIDGE__ 消息并分发（核心桥接逻辑，不受日志开关影响）
        if msg and msg.startswith('__PYBRIDGE__:'):
            try:
                data = json.loads(msg[len('__PYBRIDGE__:'):])
                method = data.get('method', '')
                args = data.get('args', [])
                callback_id = data.get('callbackId')
                self._handle_pybridge(method, args, callback_id)
            except Exception as e:
                print(f"[PYBRIDGE] 解析错误: {e}")
                traceback.print_exc()

    # ------------------------------------------------------------
    # 桥接方法分发
    # ------------------------------------------------------------
    def _handle_pybridge(self, method, args, callback_id):
        """调度 JS→Python 的桥接调用"""
        try:
            if method == 'agentChatWithEngine' and len(args) >= 3:
                # 前端 sendAgentMessage 调用：args = [engine, model, fullPrompt]
                self._panel.handle_agent_chat_with_engine(args[0], args[1], args[2], callback_id)
            elif method == 'agentChat' and len(args) >= 2:
                # 兼容旧接口：args = [model, prompt]
                self._panel.handle_agent_chat(args[0], args[1], callback_id)
            elif method == 'switchMode' and len(args) >= 1:
                # 切换模式：args = [mode_id]
                self._panel.handle_switch_mode(args[0], callback_id)
            elif method == 'checkBridge':
                # 桥接自检
                self._reply(callback_id, {
                    "success": True,
                    "status": "hybrid_pybridge_ok_v3.10",
                    "panel": "HybridModeWebPanel"
                })
            elif method == 'echo' and len(args) >= 1:
                self._reply(callback_id, {"success": True, "echo": args[0]})
            elif method == 'getOllamaStatus':
                # 同步检查 Ollama 状态
                self._panel.handle_get_ollama_status(callback_id)
            elif method == 'getOllamaModels':
                self._panel.handle_get_ollama_models(callback_id)
            elif method == 'getMimoStatus':
                # ★ v3.11 检查 MIMO Code 服务状态（端口 4097）
                self._panel.handle_get_mimo_status(callback_id)
            elif method == 'checkAllAIStatus':
                # ★ v3.18 一次性检查所有 AI 服务状态
                self._panel.handle_check_all_ai_status(callback_id)
            elif method == 'hireAgent':
                # ★ 第456章：hireAgent→start_instance 可能秒级耗时，放后台线程防卡 UI 主线程
                threading.Thread(target=self._forward_to_bridge, args=(method, args, callback_id), daemon=True).start()
            elif method == 'saveUiOverrides' and len(args) >= 1:
                # ★ 2026-10：界面设置（粗调+专业微调）持久化到 config/ui_overrides.json
                result = self._panel.save_ui_overrides(args[0])
                try:
                    self._reply(callback_id, {"success": True, "data": json.loads(result)})
                except Exception:
                    self._reply(callback_id, {"success": True, "data": result})
            elif method == 'loadUiOverrides':
                result = self._panel.load_ui_overrides()
                try:
                    self._reply(callback_id, {"success": True, "data": json.loads(result).get("data", {})})
                except Exception:
                    self._reply(callback_id, {"success": True, "data": {}})
            elif method in _BRIDGE_FORWARD_METHODS:
                # ★ v4.5 把前端 H2~M5 调用转发到 HybridBridge 的真实方法
                # ★ 2026-10：重 IO 方法放后台线程执行（与 hireAgent 同策略），防卡 Qt 主线程
                if method in _BRIDGE_ASYNC_METHODS:
                    threading.Thread(target=self._forward_to_bridge,
                                     args=(method, args, callback_id), daemon=True).start()
                else:
                    self._forward_to_bridge(method, args, callback_id)
            else:
                # 未知方法：返回失败，让前端 fallback
                self._reply(callback_id, {
                    "success": False,
                    "error": f"未知方法: {method}"
                })
        except Exception as e:
            print(f"[PYBRIDGE] 调度异常: {e}")
            traceback.print_exc()
            self._reply(callback_id, {"success": False, "error": str(e)})

    def _forward_to_bridge(self, method, args, callback_id):
        """★ v4.5 把前端 H2~M5 调用转发到 HybridBridge 的真实方法。

        HybridBridge 的 @pyqtSlot(result=str) 方法返回 JSON 字符串；
        无 result 的 @pyqtSlot 方法返回 None（动作类，成功即回复）。
        """
        bridge = getattr(self._panel, '_bridge', None)
        if bridge is None or not hasattr(bridge, method):
            self._reply(callback_id, {"success": False, "error": f"Bridge 不支持方法: {method}"})
            return
        try:
            fn = getattr(bridge, method)
            result = fn(*args) if args else fn()
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    self._reply(callback_id, {"success": True, "data": parsed})
                except Exception:
                    self._reply(callback_id, {"success": True, "data": result})
            else:
                self._reply(callback_id, {"success": True, "result": result})
        except Exception as e:
            print(f"[PYBRIDGE] 转发 {method} 失败: {e}")
            traceback.print_exc()
            self._reply(callback_id, {"success": False, "error": str(e)})

    def _reply(self, callback_id, result):
        """通过 runJavaScript 回调前端"""
        if callback_id is None:
            return
        try:
            js = f"window._pybridgeCallback && window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
            self.runJavaScript(js)
        except Exception as e:
            print(f"[PYBRIDGE] 回调失败: {e}")


class HybridModeWebPanel(QWidget):
    """混合模式Web面板 — 加载HTML并通过QWebChannel连接Python后端"""

    # 信号
    command_sent = pyqtSignal(str)
    nav_action = pyqtSignal(str)
    workflow_step = pyqtSignal(str)
    mode_switch_requested = pyqtSignal(str)  # ★ v3.10 切换到标准模式
    # ★ v3.13 线程安全回调信号（子线程→主线程）
    _reply_signal = pyqtSignal(int, object)  # (callback_id, result)

    def __init__(self, engine_manager=None, parent=None):
        super().__init__(parent)
        self._engine_manager = engine_manager
        self._bridge = None
        self._backend_initialized = False
        self._page_loaded = False
        # ★ v3.34: 销毁标志 — 防止后台线程访问已删除对象
        self._destroyed = False
        # ★ v3.10 Ollama 配置（确保有 http:// 前缀）
        # ★ 第456章补：OLLAMA_HOST=0.0.0.0 是 Ollama 服务端"监听所有网卡"的绑定配置，
        #   不能当客户端地址用（实测 WinError 10049 地址无效 → 引擎灯误报离线，
        #   而桥本体检测 11434 在线）。客户端侧归一为 127.0.0.1，无端口补 11434。
        _ollama_raw = os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
        if not _ollama_raw.startswith('http://') and not _ollama_raw.startswith('https://'):
            _ollama_raw = 'http://' + _ollama_raw
        if '0.0.0.0' in _ollama_raw:
            _ollama_raw = _ollama_raw.replace('0.0.0.0', '127.0.0.1')
        if ':' not in _ollama_raw.split('://', 1)[-1]:
            _ollama_raw = _ollama_raw + ':11434'
        self._ollama_host = _ollama_raw
        # 已知有效的 Ollama 模型
        self._valid_ollama_models = [
            'qwen3.5:4b', 'qwen3.5:9b',
            'qwen3-vl:4b', 'aleshribar3/deepseek-r1-tool-calling:8b'
        ]
        # ★ 第458章：本机可用模型缓存（/api/tags，60s TTL）——员工配置模型可能未拉取
        self._ollama_models_cache = None
        self._ollama_models_ts = 0.0
        self._init_ui()
        self._setup_bridge()
        # ★ v3.13 连接线程安全回调信号
        self._reply_signal.connect(self._handle_reply_signal)

    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ★ 2026-10 持久化修复：file:// 页面的 localStorage「重启即丢」的根因是
        #   默认 profile 的存储路径不可写/临时。按 Qt 官方建议指向 AppLocalDataLocation，
        #   页面内全部 localStorage（聊天记录/人格/界面设置）即自动跨会话持久化。
        try:
            from PyQt5.QtCore import QStandardPaths
            base = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
            storage = os.path.join(base, "hybrid_web_profile")
            os.makedirs(storage, exist_ok=True)
            profile = QWebEngineProfile.defaultProfile()
            profile.setPersistentStoragePath(storage)
            profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
            print(f"[HybridPanel] WebEngine 持久化存储: {storage}")
        except Exception as e:
            print(f"[HybridPanel] 持久化路径设置失败（localStorage 退化为会话级）: {e}")

        # 创建WebEngine视图
        self.web_view = QWebEngineView()
        # ★ v3.10 关键修复：使用 HybridDebugWebPage 拦截 __PYBRIDGE__ 消息
        self.web_view.setPage(HybridDebugWebPage(self.web_view, self))

        # 启用必要设置
        settings = self.web_view.page().settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)

        # ★ 2026-10：页面每次加载完成后注入「界面设置覆盖」（粗调/微调 token）
        self.web_view.loadFinished.connect(self._on_load_finished_apply_overrides)

        # ★ 2026-10：拉起混合模式旁路服务（7790 桥 / 7791 指挥官）
        self._service_processes = []
        self._ensure_bridge_services()

        layout.addWidget(self.web_view)

    # ------------------------------------------------------------
    # ★ 2026-10 旁路服务自启动（7790/7791）
    # ------------------------------------------------------------
    def _ensure_bridge_services(self):
        """探活 7790/7791，未启动则用自身解释器后台拉起（worker 再入模式）。

        最佳实践依据：PyInstaller onefile 场景用 `sys.executable + 参数` 自身再入；
        开发场景 sys.executable 即 python.exe。进程句柄保留，cleanup() 时 terminate。
        探活失败不阻断面板加载，仅在终端如实提示（绝不假装在线）。
        """
        import socket
        import subprocess
        import threading
        import time as _time

        def _port_open(port, timeout=0.6):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                    return True
            except OSError:
                return False

        targets = [
            (7790, ["-m", "hybrid_mode.server"], "混合模式桥"),
            (7791, ["-m", "hybrid_mode.core.commander_server"] if True else [], "指挥官服务"),
        ]
        for port, extra_args, label in targets:
            if _port_open(port):
                print(f"[HybridPanel] {label}({port}) 已在运行，复用")
                continue
            try:
                kwargs = {}
                if os.name == "nt":
                    kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                proc = subprocess.Popen(
                    [sys.executable] + extra_args,
                    cwd=self._repo_root(),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    **kwargs,
                )
                self._service_processes.append(proc)
                print(f"[HybridPanel] 已拉起 {label}(port {port}) pid={proc.pid}")

                def _wait_alive(p=proc, pt=port, lb=label):
                    for _ in range(10):
                        if _port_open(pt):
                            print(f"[HybridPanel] {lb}({pt}) 探活成功")
                            return
                        _time.sleep(0.5)
                    print(f"[HybridPanel] [WARN] {lb}({pt}) 10s 内未探活——相关按钮将如实报错")
                threading.Thread(target=_wait_alive, daemon=True).start()
            except Exception as e:
                print(f"[HybridPanel] [WARN] 拉起 {label}({port}) 失败: {e}（按钮将如实报错）")

    @staticmethod
    def _repo_root():
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # ------------------------------------------------------------
    # ★ 2026-10 界面设置覆盖（token 微调）注入
    # ------------------------------------------------------------
    def _on_load_finished_apply_overrides(self, ok):
        """页面加载完成后：1) 注入持久化界面设置；2) 注入 SSOT token 常量兜底。"""
        if not ok or self._destroyed:
            return
        try:
            overrides = self._load_ui_overrides()
            js_vars = []
            for k, v in (overrides.get("vars") or {}).items():
                safe_key = re.sub(r"[^a-z0-9-]", "", str(k).lower())
                safe_val = str(v).replace("\\", "").replace("'", "")
                if safe_key and safe_val:
                    js_vars.append(f"'--{safe_key}':'{safe_val}'")
            effects = bool(overrides.get("effects", False))
            starfield = bool(overrides.get("starfield", False))
            js = (
                "window.__UI_OVERRIDES__ = {vars:{" + ",".join(js_vars) + "},"
                f"effects:{'true' if effects else 'false'},starfield:{'true' if starfield else 'false'}}};"
                "if (typeof window.__applyUiOverrides === 'function') window.__applyUiOverrides();"
            )
            self.web_view.page().runJavaScript(js)
        except Exception as e:
            print(f"[HybridPanel] 界面设置注入失败: {e}")

    _UI_OVERRIDES_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config", "ui_overrides.json",
    )

    def _load_ui_overrides(self):
        try:
            with open(self._UI_OVERRIDES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_ui_overrides(self, overrides_json):
        """供 __PYBRIDGE__ 分发：持久化界面设置（粗调+专业微调）。"""
        try:
            data = json.loads(overrides_json) if isinstance(overrides_json, str) else (overrides_json or {})
            os.makedirs(os.path.dirname(self._UI_OVERRIDES_PATH), exist_ok=True)
            with open(self._UI_OVERRIDES_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 立即生效
            self._on_load_finished_apply_overrides(True)
            return json.dumps({"success": True, "path": self._UI_OVERRIDES_PATH}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    def load_ui_overrides(self):
        return json.dumps({"success": True, "data": self._load_ui_overrides()}, ensure_ascii=False)

    # ============================================================
    # ★ v3.13 线程安全回调 — 子线程通过信号触发主线程执行 runJavaScript
    # ============================================================
    def _handle_reply_signal(self, callback_id, result):
        """主线程执行：通过 runJavaScript 回调前端"""
        try:
            js = f"window._pybridgeCallback && window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
            print(f"[PYBRIDGE] => JS回调: callback_id={callback_id}, success={result.get('success')}, online={result.get('online', 'N/A')}")
            self.web_view.page().runJavaScript(js)
        except Exception as e:
            print(f"[PYBRIDGE] 主线程回调失败: {e}")
            traceback.print_exc()
    
    def _reply_thread_safe(self, callback_id, result):
        """子线程安全回调（v3.34: 使用 _destroyed 标志防止崩溃）"""
        if self._destroyed:
            return  # 面板已销毁，静默跳过
        try:
            self._reply_signal.emit(callback_id, result)
        except RuntimeError:
            pass  # C/C++ 对象已删除，静默忽略

    # ============================================================
    # ★ v3.10 Python 后端处理 — Agent 对话桥接
    # ============================================================
    def handle_agent_chat_with_engine(self, engine, model, prompt, callback_id):
        """
        处理前端 _callPython('agentChatWithEngine', engine, model, prompt, callback)
        engine: 'ollama' / 'mimo'
        model: Ollama 模型名（如 qwen3.5:4b）
        prompt: 完整提示词（已包含角色设定）
        callback_id: JS 回调 ID
        """
        # 强制使用子线程，避免阻塞 UI
        t = threading.Thread(
            target=self._do_agent_chat,
            args=(engine, model, prompt, callback_id),
            daemon=True
        )
        t.start()

    def handle_agent_chat(self, model, prompt, callback_id):
        """兼容旧接口：默认使用 ollama 引擎"""
        self.handle_agent_chat_with_engine('ollama', model, prompt, callback_id)

    def set_engine_manager(self, engine_manager):
        """★ 第458章：延迟注入引擎管理器（构造期窗口尚未持有 _engine_manager）。
        注入后 agentChatWithEngine 走 unified_chat 正路，不再降级直连。"""
        self._engine_manager = engine_manager
        if engine_manager is not None:
            print("[HybridModeWebPanel] 引擎管理器已延迟注入（unified_chat 正路生效）")

    def _resolve_chat_model(self, want):
        """★ 第458章：按本机 /api/tags 实况解析聊天模型（缓存 60s）。
        want 可用 → 原样返回；不可用 → 按速度偏好选最小可用模型；
        查询失败 → 沿用旧硬编码规则（诚实暴露原错误）。"""
        try:
            import requests as _rq
            import time as _t
            now = _t.time()
            if self._ollama_models_cache is not None and now - self._ollama_models_ts < 60:
                names = self._ollama_models_cache
            else:
                r = _rq.get(self._ollama_host + "/api/tags", timeout=3)
                names = [m.get("name", "") for m in r.json().get("models", [])]
                self._ollama_models_cache = names
                self._ollama_models_ts = now
            for n in names:
                if n == want or n.startswith(want):
                    return want
            for pref in ("qwen2.5:1.5b", "qwen3:4b", "qwen3.5:4b", "qwen3.5:9b"):
                for n in names:
                    if n == pref or n.startswith(pref):
                        return n
            base = (want or "").split(":")[0]
            if base:
                for n in names:
                    if n.startswith(base):
                        return n
            return want
        except Exception:
            return want if want in self._valid_ollama_models else 'qwen3.5:4b'

    def _do_agent_chat(self, engine, model, prompt, callback_id):
        """子线程执行：调用 AI 引擎（★ v3.17 优先使用 EngineManager.unified_chat）"""
        import time as _time
        start_time = _time.time()
        print(f"[PYBRIDGE] ★ 开始调用引擎: {engine}, 模型: {model}, callback_id: {callback_id}")

        # ★ v5.1 P0修复：空 prompt 守卫（此前前端发 null 导致空调用，引擎必报错）
        if not prompt or not str(prompt).strip():
            self._reply_thread_safe(callback_id, {
                "success": False, "reply": "", "error": "空消息：请输入内容后再发送",
                "engine": engine or "unknown", "model": model,
            })
            return
        try:
            # ★ v3.17 优先使用统一的 AI 调用接口
            if self._engine_manager is not None:
                print(f"[PYBRIDGE] 使用 EngineManager.unified_chat()")
                # ★ 第458章续：unified_chat 路径同样按本机 /api/tags 实况解析模型。
                #   截图实锤：员工配置 qwen2.5:1.5b 未拉取 → /api/chat 404 →
                #   错误文本被 unified_chat 包装成 success 回复（气泡显示报错）。
                model = self._resolve_chat_model(model)
                print(f"[PYBRIDGE] unified_chat 模型解析: {model}")
                result = self._engine_manager.unified_chat(
                    prompt=prompt,
                    model=model,
                    engine_id=engine,
                )
                elapsed = _time.time() - start_time
                result['elapsed_ms'] = int(elapsed * 1000)
                print(f"[PYBRIDGE] unified_chat 结果: success={result.get('success')}, engine={result.get('engine')}, {len(result.get('reply',''))}字")
                self._reply_thread_safe(callback_id, result)
                return
            else:
                print(f"[PYBRIDGE] ⚠ EngineManager 不可用，使用直接调用")
        except Exception as e:
            print(f"[PYBRIDGE] ⚠ unified_chat 失败: {e}，使用直接调用")
        
        # ★ 降级：直接调用（保留原有逻辑作为 fallback）
        try:
            import requests as _req
            
            # 1. 如果是 mimo 引擎，尝试调用 mimo serve
            if engine == 'mimo':
                print(f"[PYBRIDGE] 尝试调用 MIMO Code...")
                mimo_result = self._call_mimo_serve(prompt)
                if mimo_result.get('success'):
                    elapsed = _time.time() - start_time
                    mimo_result['elapsed_ms'] = int(elapsed * 1000)
                    mimo_result['engine'] = 'mimo'
                    self._reply_thread_safe(callback_id, mimo_result)
                    return
                print(f"[PYBRIDGE] ⚠ mimo 引擎调用失败: {mimo_result.get('error')}, 降级 ollama")

            # 2. 调用 Ollama（★ 第458章：模型按本机实况动态解析，员工配置模型未拉取时自动选最快可用）
            use_model = self._resolve_chat_model(model)
            print(f"[PYBRIDGE] 直接调用 Ollama: {self._ollama_host}, 模型: {use_model}")
            _is_thinking = any(t in use_model.lower() for t in ['4b', '7b', '14b', 'qwen3'])
            _num_predict = 1500 if _is_thinking else 300
            payload = {
                "model": use_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": _num_predict,
                    "top_p": 0.85,
                    "top_k": 20,
                    "repeat_penalty": 1.1
                }
            }
            resp = _req.post(f"{self._ollama_host}/api/generate", json=payload, timeout=180)
            print(f"[PYBRIDGE] Ollama HTTP 状态: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                reply_text = data.get('response', '').strip()
                if not reply_text:
                    raw_thinking = data.get('thinking', '').strip()
                    if raw_thinking:
                        parts = [p.strip() for p in raw_thinking.split('\n\n') if p.strip()]
                        for p in reversed(parts):
                            if not any(m in p.lower() for m in ['thinking process', 'analyze', 'step ', '1.', '2.', 'let me', '**']):
                                reply_text = p
                                break
                        if not reply_text and parts:
                            reply_text = parts[-1]
                elapsed = _time.time() - start_time
                result = {
                    "success": True,
                    "reply": reply_text or '(空回复)',
                    "tokens": data.get('eval_count', 0),
                    "elapsed_ms": int(elapsed * 1000),
                    "engine": "ollama",
                    "model": use_model
                }
                self._reply_thread_safe(callback_id, result)
            else:
                err = f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"
                self._reply_thread_safe(callback_id, {"success": False, "error": err, "engine": "ollama"})

        except Exception as e:
            print(f"[PYBRIDGE] ✗ Agent 对话异常: {e}")
            traceback.print_exc()
            self._reply_thread_safe(callback_id, {"success": False, "error": str(e), "engine": engine})

    def _call_mimo_serve(self, prompt):
        """★ v3.12 尝试调用本地 mimo serve（兼容端口 4096 和 4097）
        - 4096: MIMO Code GUI 默认端口（D:\\mimo_ai\\mimo-gui\\start-server.js）
        - 4097: 项目 multi_instance_manager 默认端口
        """
        try:
            import requests as _req
            # ★ 依次尝试 4096 和 4097 端口（短超时，避免阻塞）
            online_port = None
            for port in [4096, 4097]:
                try:
                    health = _req.get(f'http://127.0.0.1:{port}/global/health', timeout=1)
                    if health.status_code == 200:
                        online_port = port
                        break
                except Exception:
                    continue

            if online_port is None:
                return {"success": False, "error": "mimo serve 未运行 (端口 4096/4097 均不可达，请先启动 D:\\mimo_ai\\mimo-gui\\start-desktop.bat 或运行 mimo serve --port 4097)"}

            # 调用 mimo serve
            payload = {"prompt": prompt, "stream": False}
            resp = _req.post(f'http://127.0.0.1:{online_port}/v1/chat', json=payload, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                reply_text = data.get('response', '') or data.get('content', '') or ''
                return {
                    "success": True,
                    "reply": reply_text,
                    "tokens": data.get('usage', {}).get('total_tokens', 0),
                    "model": "mimo",
                    "port": online_port
                }
            return {"success": False, "error": f"mimo serve HTTP {resp.status_code} (port {online_port})"}
        except Exception as e:
            return {"success": False, "error": f"mimo serve 调用异常: {e}"}

    # ============================================================
    # 其他桥接方法
    # ============================================================
    def handle_switch_mode(self, mode, callback_id):
        """切换模式：发送信号到主窗口"""
        print(f"[PYBRIDGE] 切换模式: {mode}")
        self.mode_switch_requested.emit(mode)
        self._reply(callback_id, {"success": True, "mode": mode})

    def handle_get_ollama_status(self, callback_id):
        """获取 Ollama 服务状态"""
        print(f"[PYBRIDGE] handle_get_ollama_status: callback_id={callback_id}, host={self._ollama_host}")
        def _check():
            if self._destroyed:
                return  # ★ v3.34: 面板已销毁，跳过
            try:
                import requests as _req
                print(f"[PYBRIDGE] 正在检测 Ollama: {self._ollama_host}/api/tags")
                resp = _req.get(f"{self._ollama_host}/api/tags", timeout=3)
                print(f"[PYBRIDGE] Ollama 响应: HTTP {resp.status_code}")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    print(f"[PYBRIDGE] Ollama 在线，{len(models)} 个模型")
                    self._reply_thread_safe(callback_id, {"success": True, "online": True, "host": self._ollama_host, "models": len(models)})
                else:
                    print(f"[PYBRIDGE] Ollama 异常: HTTP {resp.status_code}")
                    self._reply_thread_safe(callback_id, {"success": True, "online": False, "error": f"HTTP {resp.status_code}"})
            except Exception as e:
                print(f"[PYBRIDGE] Ollama 检测失败: {e}")
                self._reply_thread_safe(callback_id, {"success": True, "online": False, "error": str(e)})

        threading.Thread(target=_check, daemon=True).start()

    def handle_get_ollama_models(self, callback_id):
        """获取 Ollama 模型列表"""
        def _fetch():
            if self._destroyed:
                return  # ★ v3.34: 面板已销毁，跳过
            try:
                import requests as _req
                resp = _req.get(f"{self._ollama_host}/api/tags", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get('name', '') for m in data.get('models', [])]
                    self._reply_thread_safe(callback_id, {"success": True, "models": models})
                else:
                    self._reply_thread_safe(callback_id, {"success": False, "error": f"HTTP {resp.status_code}"})
            except Exception as e:
                self._reply_thread_safe(callback_id, {"success": False, "error": str(e)})

        threading.Thread(target=_fetch, daemon=True).start()

    def handle_get_mimo_status(self, callback_id):
        """★ v3.12 获取 MIMO Code 服务状态（兼容端口 4096 和 4097）
        - 4096: MIMO Code GUI 默认端口
        - 4097: 项目 multi_instance_manager 默认端口
        """
        print(f"[PYBRIDGE] handle_get_mimo_status: callback_id={callback_id}")
        def _check():
            if self._destroyed:
                return  # ★ v3.34: 面板已销毁，跳过
            try:
                import requests as _req
                online_port = None
                # ★ 依次尝试 4096 和 4097
                for port in [4096, 4097]:
                    try:
                        print(f"[PYBRIDGE] 检测 MIMO 端口 {port}...")
                        resp = _req.get(f'http://127.0.0.1:{port}/global/health', timeout=2)
                        if resp.status_code == 200:
                            online_port = port
                            print(f"[PYBRIDGE] MIMO 在线: 端口 {port}")
                            break
                    except Exception:
                        # fallback: 尝试根路径
                        try:
                            resp = _req.get(f'http://127.0.0.1:{port}/', timeout=2)
                            if resp.status_code in (200, 401, 404):
                                online_port = port
                                print(f"[PYBRIDGE] MIMO 在线(根路径): 端口 {port}")
                                break
                        except Exception:
                            continue

                if online_port is None:
                    print(f"[PYBRIDGE] MIMO 离线 (端口 4096/4097 均不可达)")
                
                self._reply_thread_safe(callback_id, {
                    "success": True,
                    "online": online_port is not None,
                    "port": online_port,
                    "checked_ports": [4096, 4097]
                })
            except Exception as e:
                print(f"[PYBRIDGE] MIMO 检测失败: {e}")
                self._reply_thread_safe(callback_id, {"success": True, "online": False, "error": str(e)})

        threading.Thread(target=_check, daemon=True).start()

    def handle_check_all_ai_status(self, callback_id):
        """★ v3.18 一次性检查所有 AI 服务状态（Ollama + MIMO）"""
        print(f"[PYBRIDGE] handle_check_all_ai_status: callback_id={callback_id}")
        def _check_all():
            if self._destroyed:
                return  # ★ v3.34: 面板已销毁，跳过
            import requests as _req
            import time as _time
            start = _time.time()
            result = {
                "success": True,
                "ollama": {"online": False, "error": ""},
                "mimo": {"online": False, "port": None, "error": ""},
                "elapsed_ms": 0
            }
            
            # 1. 检查 Ollama
            try:
                resp = _req.get(f"{self._ollama_host}/api/tags", timeout=3)
                if resp.status_code == 200:
                    result["ollama"]["online"] = True
                    result["ollama"]["models"] = len(resp.json().get("models", []))
                else:
                    result["ollama"]["error"] = f"HTTP {resp.status_code}"
            except Exception as e:
                result["ollama"]["error"] = str(e)[:100]
            
            # 2. 检查 MIMO Code（★ v3.60: 使用 /global/health 而非 /health）
            for port in [4096, 4097]:
                try:
                    resp = _req.get(f'http://127.0.0.1:{port}/global/health', timeout=2)
                    if resp.status_code == 200:
                        result["mimo"]["online"] = True
                        result["mimo"]["port"] = port
                        break
                except Exception:
                    continue
            
            if not result["mimo"]["online"]:
                result["mimo"]["error"] = "端口 4096/4097 均不可达"
            
            result["elapsed_ms"] = int((_time.time() - start) * 1000)
            print(f"[PYBRIDGE] checkAllAIStatus 完成: ollama={result['ollama']['online']}, mimo={result['mimo']['online']}, {result['elapsed_ms']}ms")
            self._reply_thread_safe(callback_id, result)
        
        threading.Thread(target=_check_all, daemon=True).start()

    def _reply(self, callback_id, result):
        """通过 runJavaScript 回调前端（主线程安全）"""
        if callback_id is None:
            return
        try:
            js = f"window._pybridgeCallback && window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
            # QWebEnginePage.runJavaScript 是线程安全的（会自动切到 WebEngine 线程）
            self.web_view.page().runJavaScript(js)
        except Exception as e:
            print(f"[PYBRIDGE] 回调失败: {e}")
    
    def _setup_bridge(self):
        """设置前后端桥接"""
        # 创建QWebChannel
        self._channel = QWebChannel()

        # 导入并创建HybridBridge
        try:
            # ★ 第453章修复：弹性行内路径引导 + 残缺命名空间清缓存
            # GUI 实测出现 ModuleNotFoundError: No module named 'hybrid_mode.core'
            # （启动早期虽有多处 sys.path 引导，但 hybrid_page 创建时仍可能因
            #   引导次序/模块缓存命中残缺命名空间而失败）。
            # 此处按 __file__ 三级 dirname 直算仓库根（与下方 HTML 路径解析器同款
            # 算法，已被验证可靠），强制入 path 并清掉 hybrid_mode 模块缓存。
            _repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if _repo_root not in sys.path:
                sys.path.insert(0, _repo_root)
            for _m in [m for m in list(sys.modules) if m == 'hybrid_mode' or m.startswith('hybrid_mode.')]:
                del sys.modules[_m]
            from hybrid_mode.core.hybrid_mode_bridge import HybridBridge
            self._bridge = HybridBridge(self._engine_manager, self)

            # 注册bridge对象到channel（必须与 HTML 中的 hybridBridge 一致）
            self._channel.registerObject('hybridBridge', self._bridge)

            # 设置channel到web页面
            self.web_view.page().setWebChannel(self._channel)

            # 连接后端信号到前端 JS 全局回调（pyqtSignal 不会通过 QWebChannel 暴露 connect）
            self._connect_signals_to_frontend()

            print("[HybridModeWebPanel] Bridge初始化成功")

        except Exception as e:
            print(f"[HybridModeWebPanel] Bridge初始化失败: {e}")
            import traceback
            traceback.print_exc()
            # ★ 第453章：失败诊断（下次复发可直读根因）
            try:
                _hm_dir = os.path.join(_repo_root, 'hybrid_mode')
                _core_dir = os.path.join(_hm_dir, 'core')
                print(f"[HybridModeWebPanel][诊断] repo_root={_repo_root} 存在={os.path.isdir(_repo_root)}")
                print(f"[HybridModeWebPanel][诊断] hybrid_mode/ 存在={os.path.isdir(_hm_dir)} core/ 存在={os.path.isdir(_core_dir)}")
                print(f"[HybridModeWebPanel][诊断] sys.path 前6项={sys.path[:6]}")
            except Exception:
                pass

        # ★ 修复：混合模式 HTML 路径解算
        # __file__ = standard_mode/ui/hybrid_mode_web_panel.py
        #   dirname 1 → standard_mode/ui
        #   dirname 2 → standard_mode         (旧版只走到这层，恰好少了一层，root 到不了，永远 404)
        #   dirname 3 → lemon_agent            (真正仓库根，第232章的功能版 HTML 就在这层)
        # PyInstaller 打包后 __file__ 落到 bin/_internal/standard_mode/ui/...，_MEIPASS 即等于仓库根
        here = os.path.abspath(__file__)
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))  # lemon_agent/
        candidates = [
            os.path.join(repo_root, 'hybrid_mode_wireframe.html'),                                # 仓库根（第232章的功能版HTML）
            os.path.join(os.path.dirname(repo_root), 'hybrid_mode_wireframe.html'),                # lemon_agent 的父级（兜底）
            os.path.join(getattr(sys, '_MEIPASS', repo_root), 'hybrid_mode_wireframe.html'),      # PyInstaller 解包目录
            os.path.join(os.path.dirname(here), '..', 'hybrid_mode_wireframe.html'),              # standard_mode/ 子目录（如果以后复制过来）
        ]
        # 去重 + 实际存在优先
        html_path = None
        seen = set()
        for c in candidates:
            c_abs = os.path.normpath(c)
            if c_abs in seen:
                continue
            seen.add(c_abs)
            if os.path.exists(c_abs):
                html_path = c_abs
                break
        # 兜底：candidates 都没命中，再递归向上找一次，最多 4 层
        if html_path is None:
            cur = here
            for _ in range(5):
                cur = os.path.dirname(cur)
                guess = os.path.join(cur, 'hybrid_mode_wireframe.html')
                if os.path.exists(guess):
                    html_path = guess
                    break

        if html_path:
            self.web_view.setUrl(QUrl.fromLocalFile(html_path))
            print(f"[HybridModeWebPanel] 加载HTML: {html_path}")
        else:
            # 全候选都没命中 — 显示错误信息（给开发期排查用，绝不会"静默失败"）
            tried = ' | '.join(sorted(seen))
            error_html = f"""
            <html>
            <body style="background:#0d0d0d;color:#ff6900;font-family:Segoe UI;padding:20px;">
                <h1>混合模式加载失败</h1>
                <p>HTML文件不存在（已尝试以下路径）：</p>
                <pre style="background:#1a1a1a;padding:12px;color:#ddd;white-space:pre-wrap;">{tried}</pre>
            </body>
            </html>
            """
            self.web_view.setHtml(error_html)
            print(f"[HybridModeWebPanel] HTML文件不存在，尝试过: {tried}", flush=True)

    def _connect_signals_to_frontend(self):
        """将 HybridBridge 的 pyqtSignal 通过 runJavaScript 转发到前端全局函数"""
        if not self._bridge:
            return

        import json as _json

        page = self.web_view.page()

        def _js(expr):
            """安全执行 JS，忽略页面未加载时的错误"""
            try:
                page.runJavaScript(expr)
            except Exception as e:
                print(f"[HybridModeWebPanel] runJavaScript 失败: {e}")

        self._bridge.agentStatusChanged.connect(
            lambda agent_id, status, progress:
            _js(f"window.onAgentStatusChanged && window.onAgentStatusChanged({_json.dumps(agent_id)}, {_json.dumps(status)}, {_json.dumps(progress)})")
        )
        self._bridge.chatMessageReceived.connect(
            lambda sender, content, timestamp:
            _js(f"window.onChatMessageReceived && window.onChatMessageReceived({_json.dumps(sender)}, {_json.dumps(content)}, {_json.dumps(timestamp)})")
        )
        self._bridge.monitorDataUpdated.connect(
            lambda json_data:
            _js(f"window.onMonitorDataUpdated && window.onMonitorDataUpdated({_json.dumps(json_data)})")
        )
        self._bridge.workflowStepChanged.connect(
            lambda step_id, status:
            _js(f"window.onWorkflowStepChanged && window.onWorkflowStepChanged({_json.dumps(step_id)}, {_json.dumps(status)})")
        )
        self._bridge.errorOccurred.connect(
            lambda err:
            _js(f"window.onErrorOccurred && window.onErrorOccurred({_json.dumps(err)})")
        )
        self._bridge.agentOutputReceived.connect(
            lambda agent_id, text:
            _js(f"window.onAgentOutputReceived && window.onAgentOutputReceived({_json.dumps(agent_id)}, {_json.dumps(text)})")
        )
        self._bridge.agentThinkingReceived.connect(
            lambda agent_id, thinking:
            _js(f"window.onAgentThinkingReceived && window.onAgentThinkingReceived({_json.dumps(agent_id)}, {_json.dumps(thinking)})")
        )

        print("[HybridModeWebPanel] 后端信号已连接到前端 JS 回调")

    def get_bridge(self):
        """获取Bridge对象"""
        return self._bridge

    def get_view(self):
        """获取WebEngine视图（供诊断脚本使用）"""
        return self.web_view

    # ============================================================
    # ★ v3.34: 生命周期管理 — 防止后台线程访问已删除对象
    # ============================================================
    def closeEvent(self, event):
        print("[HybridModeWebPanel] 关闭事件，清理资源...")
        self._destroyed = True  # ★ v3.34: 立即标记销毁，阻止后台线程访问
        self._cleanup_resources()
        event.accept()

    def hideEvent(self, event):
        """面板被隐藏时（切换模式），标记为不可用"""
        self._destroyed = True  # ★ v3.34: 隐藏也标记，防止后台线程访问
        super().hideEvent(event)

    def showEvent(self, event):
        """面板再次显示时，重置销毁标志"""
        self._destroyed = False  # ★ v3.34: 重新可用
        super().showEvent(event)

    def _cleanup_resources(self):
        """清理所有资源"""
        # ★ 2026-10：停掉本面板拉起的旁路服务（7790/7791 worker 进程）
        try:
            for proc in getattr(self, "_service_processes", []):
                if proc.poll() is None:
                    proc.terminate()
            self._service_processes = []
        except Exception as e:
            print(f"[HybridModeWebPanel] 停止旁路服务时出错: {e}")
        if self._bridge:
            try:
                self._bridge.agentStatusChanged.disconnect()
                self._bridge.chatMessageReceived.disconnect()
                self._bridge.monitorDataUpdated.disconnect()
                self._bridge.workflowStepChanged.disconnect()
                self._bridge.errorOccurred.disconnect()
                self._bridge.agentOutputReceived.disconnect()
                self._bridge.agentThinkingReceived.disconnect()
            except Exception as e:
                print(f"[HybridModeWebPanel] 断开信号时出错: {e}")
            try:
                self._channel.deregisterObject('hybridBridge')
            except Exception as e:
                print(f"[HybridModeWebPanel] 注销对象时出错: {e}")
            self._bridge = None
        if self._channel:
            self._channel = None
        if self.web_view:
            try:
                self.web_view.load(QUrl("about:blank"))
                self.web_view.stop()
                self.web_view.page().setWebChannel(None)
                self.web_view.deleteLater()
            except Exception as e:
                print(f"[HybridModeWebPanel] 清理 WebView 时出错: {e}")
            self.web_view = None
        self._backend_initialized = False
        self._page_loaded = False
        print("[HybridModeWebPanel] 资源清理完成")

    def cleanup(self):
        """外部调用清理"""
        self._destroyed = True
        self._cleanup_resources()