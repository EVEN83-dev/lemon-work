# -*- coding: utf-8 -*-
"""
Lemon Code 原版风格面板 — 右侧核心
柠檬 × Lemon Code 融合设计
- 使用 QWebEngineView 加载 HTML 页面
- 星空粒子动画 + 流星效果
- 渐变 Logo + 互动数码机器人
- 人体工学输入框和按钮
- ACP 协议交互（配置选项弹窗、权限对话框、模式同步）
"""

import os
import sys
import json
import time
import logging
import threading
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import Qt, QObject, pyqtSignal, QUrl, pyqtSlot, QTimer, QThread
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings, QWebEnginePage, QWebEngineProfile
from PyQt5.QtWebChannel import QWebChannel
from ui.theme import *

# ★ v3.51: 引擎模式管理器
_lemon_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _lemon_root not in sys.path:
    sys.path.insert(0, _lemon_root)
from shared.engine_mode_manager import EngineModeManager, EngineMode
from ui.design.tokens import Lemon

# Ollama 千问模型桥接（延迟导入，避免重复加载知识库）
# ★ 不在模块级别导入，改为在 __init__ 中按需导入
_OllamaBridge = None  # 延迟导入的类引用
_OLLAMA_AVAILABLE = None  # 延迟检查的可用性标记

# ★ 日志记录器
logger = logging.getLogger(__name__)


# ============================================================
# Python-JavaScript 桥接类
# ============================================================
class PyBridge(QObject):
    """Python 与 JavaScript 通信的桥梁"""
    
    # 发送给 JavaScript 的信号
    append_message_signal = pyqtSignal(str)
    append_thinking_signal = pyqtSignal(str)
    append_status_signal = pyqtSignal(str)
    append_tool_signal = pyqtSignal(str)
    # ★ v4.1.15: 执行轨迹流（Timeline）信号 — 携带 timeline event JSON
    append_timeline_signal = pyqtSignal(str)
    # ★ v5.1: P-C 任务步骤列表信号 — 携带步骤汇总 JSON（含本次运行所有工具调用）
    append_steps_signal = pyqtSignal(str)
    # ★ v5.1: P-F 独立状态栏信号 — 携带运行结束的完整 meta JSON（引擎/模型/循环/工具/耗时/Token）
    agent_status_signal = pyqtSignal(str)
    append_preview_signal = pyqtSignal(str)  # v3.90: 文件预览（HTML/图像/代码内嵌）
    append_user_message_signal = pyqtSignal(str)  # 用户消息回显
    set_connected_signal = pyqtSignal(bool)
    set_robot_status_signal = pyqtSignal(str)
    # ★ T366.1: 后台任务完成信号（JSON: {task_id, name, status, result_preview, error}）
    background_task_signal = pyqtSignal(str)

    # ★ 流式输出信号
    eval_js_signal = pyqtSignal(str)  # 通用 JS 执行信号
    
    # 交互式 UI 信号
    show_config_options_signal = pyqtSignal(str, str)  # sessionId, options_json
    show_permission_signal = pyqtSignal(str, str, str)  # sessionId, tool_info_json, options_json
    set_mode_signal = pyqtSignal(str)  # modeId
    
    # 新增：计划/命令/用量信号
    show_plan_signal = pyqtSignal(str)      # plan entries JSON
    show_commands_signal = pyqtSignal(str)  # commands list JSON
    show_usage_signal = pyqtSignal(str)     # usage info JSON
    set_agent_state_signal = pyqtSignal(str)  # agent state: idle/working/thinking/error/connected/disconnected
    
    # 新增：模型/会话管理信号
    show_models_signal = pyqtSignal(str)     # models list JSON
    show_sessions_signal = pyqtSignal(str)   # sessions list JSON
    set_current_model_signal = pyqtSignal(str)  # current model id
    set_current_session_signal = pyqtSignal(str)  # current session id

    # 小机器人聊天信号（接入 Ollama 千问模型）
    robotReply = pyqtSignal(str)   # 机器人回复内容（已转给 JS）
    robotError = pyqtSignal(str)   # 机器人出错信息
    
    # 输入框实时同步信号
    input_sync = pyqtSignal(str)  # 右侧面板输入内容同步到底部终端

    # ★ v4.3.8: 咩咩 Agent 真流式推送（PyQt worker → JS）
    miemie_event_signal = pyqtSignal(str)  # {"type":"token|step|result|summary|done", ...} base64

    # ★第362章(P4)修复: 闭环尾部 4 信号曾只在 MIMOCodePanel 声明、连接却指向
    #   pybridge → AttributeError 接线失败（技能审核卡/音频预览/市场下载/记忆导出全失效）
    skill_review_signal = pyqtSignal(str)        # {"pending": [...], "count": N}
    audio_preview_signal = pyqtSignal(str)       # {"files": [...], "dir": ...}
    market_download_signal = pyqtSignal(str)     # {"success": bool, "error": ..., "data": ...}
    memory_export_signal = pyqtSignal(str)       # 记忆导出结果 JSON

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    @pyqtSlot(str)
    def sendMessage(self, message):
        """JavaScript 调用：用户发送消息或交互操作"""
        self.panel._on_js_send_message(message)

    @pyqtSlot(str)
    def chatWithRobot(self, message):
        """JavaScript 调用：和小机器人聊天（走 Ollama 千问模型）"""
        self.panel._on_robot_chat(message)

    @pyqtSlot(str)
    def syncInput(self, text):
        """JavaScript 调用：右侧面板输入框内容变化，同步到底部终端"""
        print(f"[输入同步] 右侧→底部: '{text[:30]}...'")
        self.input_sync.emit(text)

    @pyqtSlot(result=str)
    def checkBridge(self):
        """JavaScript 调用：验证桥接是否正常工作"""
        ollama_ok = self.panel.ollama_bridge is not None and self.panel.ollama_bridge.is_available()
        return f"pybridge=ok, ollama={'ok' if ollama_ok else 'no'}, robot={self.panel._ollama_available}"

    @pyqtSlot(str, result=str)
    def echo(self, msg):
        """JavaScript 调用：简单回显测试"""
        return f"echo: {msg}"

    @pyqtSlot(result=str)
    def getMiemiePixelMap(self):
        """JavaScript 调用：获取咩咩 0/1 像素矩阵 JSON（数据源：data/miemie/miemie_pixel_map.json）。

        返回格式（与 tools/extract_miemie_pixel.py 输出对齐）：
            {"grid_cols": int, "grid_rows": int, "threshold": int,
             "features": {"eye_left": [...], "eye_right": [...], "mouth": [...]},
             "pixels": [[0,1,0,...], ...]}
        加载失败时返回空字符串，HTML 端兜底显示「咩咩形象加载失败」。
        """
        map_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "miemie", "miemie_pixel_map.json",
        )
        if not os.path.exists(map_path):
            return ""
        try:
            with open(map_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"[PyBridge] 读取咩咩像素矩阵失败: {e}")
            return ""

    @pyqtSlot(result=str)
    def getMiemieAvatarStyle(self):
        """JavaScript 调用：获取咩咩形象风格（'pixel' / 'particle'）。"""
        try:
            from .miemie_panel import _load_avatar_style
        except ImportError:
            from ui.miemie_panel import _load_avatar_style
        return _load_avatar_style()

    @pyqtSlot(str, result=str)
    def setMiemieAvatarStyle(self, style):
        """JavaScript 调用：设置咩咩形象风格并持久化，返回当前生效风格。"""
        try:
            from .miemie_panel import _save_avatar_style, _load_avatar_style
        except ImportError:
            from ui.miemie_panel import _save_avatar_style, _load_avatar_style
        if style in ("pixel", "particle"):
            _save_avatar_style(style)
        return _load_avatar_style()

    @pyqtSlot(str, result=str)
    def llmRoute(self, text):
        """JavaScript 调用：用本机 Ollama 判断用户意图，返回 JSON。

        返回：{"plan": "analyze|search|memory|plan|db|chat",
               "reply": str, "reason": str, "llm": bool}
        """
        import json as _json
        try:
            try:
                from .miemie_engine import llm_route
            except ImportError:
                from ui.miemie_engine import llm_route
            r = llm_route(text or "")
            return _json.dumps(r, ensure_ascii=False, default=str)
        except Exception as e:
            return _json.dumps({"plan": "chat", "reply": f"意图判断失败: {e}",
                                "reason": "", "llm": False}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def runMiemieTool(self, request_json):
        """JavaScript 调用：执行真实咩咩工具引擎（ui.miemie_engine）。

        请求：{"tool": "grep", "args": {"pattern": "TODO|FIXME"}}
        返回：JSON 字符串（与引擎返回值同构，含 ok/error 等字段）
        """
        import json as _json
        try:
            req = _json.loads(request_json or "{}")
        except Exception as e:
            return _json.dumps({"ok": False, "error": f"请求 JSON 解析失败: {e}"}, ensure_ascii=False)
        tool = req.get("tool", "")
        args = req.get("args", {}) or {}
        try:
            try:
                from .miemie_engine import TOOL_DEFS
            except ImportError:
                from ui.miemie_engine import TOOL_DEFS
            defn = TOOL_DEFS.get(tool)
            if defn is None:
                return _json.dumps({"ok": False, "error": f"未知工具: {tool}"}, ensure_ascii=False)
            res = defn["fn"](**args)
            return _json.dumps(res, ensure_ascii=False, default=str)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return _json.dumps({"ok": False, "error": f"工具执行异常: {e}"}, ensure_ascii=False)

    # ★ v4.3.8: 咩咩 Agent 真流式入口（JS 调用）
    @pyqtSlot(str, str, result=str)
    def runMiemieAgent(self, task, text):
        """JavaScript 调用：启动咩咩 Agent 真流式执行。

        - task: "llm"（自然语言意图）或计划名（analyze/search/memory/plan/db）
        - text: 用户指令文本
        执行过程中的 token/step/result/summary/done 通过
        miemie_event_signal 实时推送 JS（base64 JSON，前端 miemieOnJson 解析）。
        """
        import json as _json
        try:
            self.panel._miemie_run_agent(task or "llm", text or "")
            return _json.dumps({"ok": True}, ensure_ascii=False)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return _json.dumps({"ok": False, "error": f"咩咩 Agent 启动失败: {e}"}, ensure_ascii=False)

    # ★ v4.1.25: Worktree × Actor 前端统一入口（对齐 hybrid_mode_bridge 同名槽）
    @pyqtSlot(str, str, result=str)
    def runWorktreeActorWorkflow(self, tasks_json, merge_mode="auto"):
        """JavaScript 调用：Worktree 隔离 + Actor 并行工作流（经 QWebChannel pybridge 暴露）

        - tasks_json: JSON 数组字符串 [{"role","title","prompt","cwd"}, ...]
        - merge_mode: "auto" 自动合并回主 / "keep" 保留隔离目录供人工审阅
        返回 JSON 字符串：{success, merge_mode, results, worktrees, ...}（与 _handle_worktree_actor 同构）
        """
        args = [tasks_json, merge_mode] if merge_mode else [tasks_json]
        try:
            result = self.panel._handle_worktree_actor(args)
        except Exception as e:
            result = {"success": False, "error": f"Worktree Actor 启动失败: {e}"}
        return json.dumps(result, ensure_ascii=False)

    # ★ v4.6.2: HTML 快捷键主路径（window.pybridge 直调）
    @pyqtSlot()
    def cycleEngine(self):
        """JavaScript 调用：Ctrl+Alt+E 循环切换 AI 引擎 → 转发 main_window 处理"""
        try:
            self.panel.engine_cycle_requested.emit()
        except Exception as e:
            print(f"[PYBRIDGE] cycleEngine 转发失败: {e}")

    @pyqtSlot()
    def openSettings(self):
        """JavaScript 调用：Ctrl+, 打开设置 / API 配置 → 转发 main_window 处理"""
        try:
            self.panel.settings_open_requested.emit()
        except Exception as e:
            print(f"[PYBRIDGE] openSettings 转发失败: {e}")

    @pyqtSlot(str, result=str)
    def getTranslations(self, keys_json):
        """JavaScript 调用：批量获取 i18n 翻译文本
        
        Args:
            keys_json: JSON 数组字符串，如 '["onboarding.welcome_title","button.save"]'
        
        Returns:
            JSON 对象字符串，如 '{"onboarding.welcome_title":"欢迎使用 LemonCode","button.save":"保存"}'
        """
        try:
            from core.i18n import _t
            import json
            keys = json.loads(keys_json)
            result = {}
            for k in keys:
                result[k] = _t(k)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return '{}'

    @pyqtSlot(str)
    def setLanguage(self, lang_code):
        """JavaScript 调用：切换语言（onboarding 语言选择页使用）"""
        try:
            from core.i18n import get_i18n
            i18n = get_i18n()
            if i18n.set_language(lang_code):
                if hasattr(self.panel, '_main_window') and self.panel._main_window:
                    self.panel._main_window._on_language_changed(lang_code)
                if hasattr(self.panel, 'set_agent_state'):
                    self.panel.set_agent_state('connected')
        except Exception as e:
            print(f"[PYBRIDGE] setLanguage 失败: {e}")

    # ★ v4.6.2: 补第 241 章落下的洞 —— HTML 已调用但 Python 端缺失的槽
    @pyqtSlot()
    def miemieBleat(self):
        """JavaScript 调用：咩咩点击互动「咩~」→ 面板侧反馈（状态消息）"""
        try:
            self.panel._miemie_bleat()
        except Exception as e:
            print(f"[PYBRIDGE] miemieBleat 失败: {e}")

    # ★ v4.7.1: HITL 确认卡 / 权限分层 / 人格工作区（HTML 咩咩面板 → Python）
    @pyqtSlot(str, str, result=str)
    def miemieConfirm(self, ok, always):
        """JavaScript 调用：用户点击确认卡回传（执行/拒绝/始终允许）。

        ok/always 为 '1'/'0' 字符串。转发 worker.set_confirm 解除阻塞。
        """
        return self.panel._miemie_confirm(ok, always)

    @pyqtSlot(result=str)
    def getPermissionMode(self):
        """JavaScript 调用：读取当前权限分层（auto/confirm/debug）。"""
        return self.panel._miemie_permission_mode()

    @pyqtSlot(str, result=str)
    def setPermissionMode(self, mode):
        """JavaScript 调用：设置权限分层并持久化，返回生效模式。"""
        return self.panel._miemie_set_permission_mode(mode)

    @pyqtSlot(result=str)
    def openPersonaWorkspace(self):
        """JavaScript 调用：打开人格工作区（v4.7.0 三栏大面板，非模态）。"""
        return self.panel._miemie_open_persona()

    # ★第410章 P4-UI 三卡合并：v6 恢复四批功能的 UI 槽回归 PyBridge
    # （技能转正清单/转正/删除待审核/市场下载/市场清单 —— JS mimerBridge.call 唯一可达类）
    @pyqtSlot(result=str)
    def v6p4_skill_review_list(self) -> str:
        """JS 入口：待审核临时技能清单（调用 skill_promote.list_pending）。"""
        try:
            from shared.skill_promote import list_pending, _resolve_registry
            reg = _resolve_registry(None)
            data = list_pending(registry=reg)
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"success": False, "error": f"清单加载失败: {e}",
                               "pending": [], "count": 0}, ensure_ascii=False)

    @pyqtSlot(str, str, result=str)
    def v6p4_promote_skill(self, tmp_name: str, formal_name: str) -> str:
        """JS 入口：转正（调用 skill_promote.promote）。"""
        try:
            from shared.skill_promote import promote, _resolve_registry
            reg = _resolve_registry(None)
            data = promote(tmp_name=tmp_name, formal_name=formal_name, registry=reg)
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"success": False, "error": f"转正调用失败: {e}"},
                              ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def v6p4_delete_pending_skill(self, tmp_name: str) -> str:
        """JS 入口：删除待审核临时技能（注销注册表 + 保留代码文件）。"""
        try:
            from shared.skill_promote import _resolve_registry, _TMP_MANAGER_PATH
            from standard_mode.core.skills import tmp_skill_manager as _tsm
            reg = _resolve_registry(None)
            try:
                reg.unregister_temporary(tmp_name)
            except Exception:
                try:
                    reg.unregister(tmp_name)
                except Exception:
                    pass
            return json.dumps({"success": True, "data": {"deleted": tmp_name}},
                              ensure_ascii=False)
        except Exception as e:
            return json.dumps({"success": False, "error": f"删除失败: {e}"},
                              ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def v6p4_market_download(self, skill_meta_json: str) -> str:
        """JS 入口：市场下载 → 三关 → 注册（调用 market_bridge.download_and_register）。"""
        try:
            meta = json.loads(skill_meta_json) if isinstance(skill_meta_json, str) else skill_meta_json
            from shared.market_bridge import download_and_register, _resolve_registry
            reg = _resolve_registry(None)
            data = download_and_register(skill_meta=meta, registry=reg)
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"success": False, "error": f"市场下载失败: {e}"},
                              ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def v6p4_list_market_skills(self, query: str = "") -> str:
        """JS 入口：技能市场清单（透传 SkillMarket 搜索）。"""
        try:
            from shared.market_bridge import list_market_skills
            data = list_market_skills(category=query or "")
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"success": False, "error": f"市场清单加载失败: {e}"},
                              ensure_ascii=False)

    @pyqtSlot(result=str)
    def v6p4_memory_export(self) -> str:
        """JS 入口：只读导出记忆快照（调用 memory_export.export_snapshot）。"""
        try:
            from shared.memory_export import export_snapshot
            data = export_snapshot()
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"success": False, "error": f"记忆导出失败: {e}"},
                              ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def v6p4_audio_list(self, dir_path: str = "") -> str:
        """JS 入口：列出指定目录下的 .wav / .mp3 文件（用于音频播放卡）。"""
        try:
            import glob as _glob
            search_dir = dir_path or os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "outputs")
            files = []
            for pat in ("*.wav", "*.mp3"):
                files.extend(_glob.glob(os.path.join(search_dir, pat)))
                files.extend(_glob.glob(os.path.join(search_dir, "**", pat), recursive=True))
            return json.dumps({"success": True, "dir": search_dir, "files": files,
                               "count": len(files)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"success": False, "error": f"音频列表加载失败: {e}",
                               "files": [], "count": 0}, ensure_ascii=False)

    # ★第405章(408 追加) AI Banking/网页卡 挂载点以下原样保留




# ============================================================
# Lemon Code 面板
# ============================================================
# 自定义 QWebEnginePage（用于捕获 JS 控制台输出 + 双向桥接）
# ============================================================
class DebugWebPage(QWebEnginePage):
    """支持 JS 控制台日志捕获和 Console Message Bridge 的 QWebEnginePage"""
    def __init__(self, parent_or_profile, panel, profile_used=False):
        if profile_used:
            super().__init__(parent_or_profile)
        else:
            super().__init__(parent_or_profile)
        self._panel = panel

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # ★ 修复：禁止同步 print 到 stdout（交互式终端下会阻塞主线程导致卡顿）
        # 仅在 LEMON_JS_CONSOLE=1 时输出，用于开发调试
        if os.environ.get("LEMON_JS_CONSOLE") == "1":
            level_str = {0: 'INFO', 1: 'WARN', 2: 'ERROR', 3: 'DEBUG'}.get(level, str(level))
            msg = message.strip() if message else ''
            if msg:
                print(f"[JS {level_str}] {msg}")

        msg = (message or '').strip()
        # ★ Console Message Bridge: 解析 JS→Python 的桥接消息（核心逻辑不受影响）
        if msg and msg.startswith('__PYBRIDGE__:'):
            try:
                data = json.loads(msg[len('__PYBRIDGE__:'):])
                method = data.get('method', '')
                args = data.get('args', [])
                callback_id = data.get('callbackId')
                self._handle_pybridge(method, args, callback_id)
            except Exception as e:
                if os.environ.get("LEMON_JS_CONSOLE") == "1":
                    print(f"[PYBRIDGE] 解析错误: {e}")

    def _handle_pybridge(self, method, args, callback_id):
        """调度 JS→Python 的桥接调用"""
        panel = self._panel
        try:
            if method == 'sendMessage' and len(args) > 0:
                panel._on_js_send_message(args[0])
            elif method == 'chatWithRobot' and len(args) > 0:
                panel._on_robot_chat(args[0])
            elif method == 'agentCharacterClick':
                # ★ Agent 角色单击交互 — 调用后端 AgentCharacter.on_click()
                panel._on_agent_character_click(callback_id)
            elif method == 'agentCharacterRightClick':
                # ★ Agent 角色右键交互 — 调用后端 AgentCharacter 思考表情
                panel._on_agent_character_right_click(callback_id)
            elif method == 'syncInput' and len(args) > 0:
                panel._on_js_sync_input(args[0])
            elif method == 'imageUpload' and len(args) >= 2:
                panel._on_image_upload(args[0], args[1])
            elif method == 'fileUpload' and len(args) >= 2:
                panel._on_file_upload(args[0], args[1])
            elif method == 'setTrustMode' and len(args) >= 1:
                panel._on_set_trust_mode(args[0])
            elif method == 'showSessionMenu':
                panel.session_switch_requested.emit('show')
            elif method == 'showModelMenu':
                panel.fetch_models_requested.emit()
            elif method == 'showModeMenu':
                panel.mode_switch_requested.emit('show')
            elif method == 'newSession':
                panel.new_session_requested.emit()
            elif method == 'switchSession' and len(args) > 0:
                panel.session_switch_requested.emit(args[0])
            elif method == 'switchModel' and len(args) > 0:
                panel.model_switch_requested.emit(args[0])
            elif method == 'switchMode' and len(args) > 0:
                panel.service_mode_switch_requested.emit(args[0])
            elif method == 'saveApiKey' and len(args) > 0:
                panel._on_save_api_key(args[0])
            elif method == 'saveApiFormat' and len(args) > 0:
                result = panel._on_save_api_format(args[0])
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'resetApiFormat' and len(args) > 0:
                result = panel._on_reset_api_format(args[0])
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'echo' and len(args) > 0:
                result = f"echo: {args[0]}"
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'checkBridge':
                status = "pybridge=ok, console_msg_bridge"
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(status)})"
                    )
            # ★ v4.2.4: MIEMIE 咩咩模式（风格分析 / 状态 / 注入上下文）
            elif method == 'miemieAnalyzeProject':
                result = panel._handle_miemie('analyze', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'miemieStatus':
                result = panel._handle_miemie('status', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'miemieInject':
                # 咩咩风格上下文注入：返回当前注入文本（供任务执行拼接）
                result = panel._handle_miemie('inject', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            # ★ 快照管理
            elif method == 'listSnapshots':
                result = panel._handle_snapshot('list', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'restoreSnapshot' and len(args) > 0:
                result = panel._handle_snapshot('restore', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'diffSnapshot' and len(args) > 0:
                result = panel._handle_snapshot('diff', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            # ★ 消息持久化 — 历史会话
            elif method == 'listDbSessions':
                result = panel._handle_message_store('list_sessions', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'getDbMessages' and len(args) > 0:
                result = panel._handle_message_store('get_messages', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'searchDbMessages' and len(args) > 0:
                result = panel._handle_message_store('search', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'deleteDbSession' and len(args) > 0:
                result = panel._handle_message_store('delete_session', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            # ★ Ollama 管理
            elif method == 'getOllamaStatus':
                result = panel._handle_ollama('status', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'getOllamaModels':
                result = panel._handle_ollama('models', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'recommendOllamaModel' and len(args) > 0:
                result = panel._handle_ollama('recommend', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'getOllamaModelInfo' and len(args) > 0:
                result = panel._handle_ollama('model_info', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            # ★ 引擎管理（Engine Manager）
            elif method == 'switchEngine' and len(args) > 0:
                result = panel._handle_engine('switch', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'getEngineStatus':
                result = panel._handle_engine('status', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'getEngineModels' and len(args) > 0:
                result = panel._handle_engine('models', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'setEngineModel' and len(args) >= 2:
                result = panel._handle_engine('set_model', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'refreshEngineModels':
                result = panel._handle_engine('refresh_models', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'getCurrentModel':
                # ★ v4.1.14: 暴露给前端拿真实当前模型（替代 mimo-auto 占位符）
                result = panel._handle_engine('get_current_model', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'worktreeAction':
                # ★ v4.1.17: Worktree 隔离操作（create/list/status/diff/remove/merge_back）
                result = panel._handle_engine('worktree', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'setHybridMode' and len(args) >= 1:
                result = panel._handle_engine('hybrid', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'executeSkill' and len(args) >= 2:
                result = panel._handle_engine('execute_skill', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'setDeepSeekKey' and len(args) >= 1:
                result = panel._handle_engine('set_api_key', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            # ★ 代码格式化 + 审查
            elif method == 'reviewCode' and len(args) > 0:
                result = panel._handle_code_skill('review_code', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'reviewFile' and len(args) > 0:
                result = panel._handle_code_skill('review_file', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'formatCode' and len(args) > 0:
                result = panel._handle_code_skill('format_code', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            elif method == 'formatFile' and len(args) > 0:
                result = panel._handle_code_skill('format_file', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            # ★ 代码运行（环境执行器）
            elif method == 'runCode' and len(args) >= 2:
                result = panel._handle_run_code(args[0], args[1])
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            # ★ 心跳检测
            elif method == 'heartbeat':
                if panel._serve_bridge:
                    result = panel._serve_bridge.heartbeat()
                else:
                    result = {"status": "no_bridge"}
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            # ★ 设置管理
            elif method == 'loadSettings':
                result = panel._handle_settings('load', args)
                # 通过 JS 回调推送设置到前端
                settings_json = json.dumps(result, ensure_ascii=False)
                self.runJavaScript(f"setSettingsFromPython({settings_json})")
            elif method == 'saveSettings' and len(args) > 0:
                result = panel._handle_settings('save', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result)})"
                    )
            # ★ 工作区管理
            elif method == 'listWorkspaces':
                result = panel._handle_workspace('list', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'addWorkspace' and len(args) >= 1:
                result = panel._handle_workspace('add', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'removeWorkspace' and len(args) >= 1:
                result = panel._handle_workspace('remove', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'switchWorkspace' and len(args) >= 1:
                result = panel._handle_workspace('switch', args)
                # 通过 JS 回调推送工作区列表到前端
                ws_json = json.dumps(result, ensure_ascii=False)
                self.runJavaScript(f"onWorkspaceSwitched({ws_json})")
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'getCurrentWorkspace':
                result = panel._handle_workspace('current', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            # ★ 调试管理
            elif method == 'debugStart' and len(args) >= 1:
                result = panel._handle_debug('start', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugStop':
                result = panel._handle_debug('stop', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugContinue':
                result = panel._handle_debug('continue', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugPause':
                result = panel._handle_debug('pause', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugStep' and len(args) >= 1:
                result = panel._handle_debug('step', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugGetVariables':
                scope = args[0] if args else 'local'
                result = panel._handle_debug('variables', [scope])
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugGetStackTrace':
                result = panel._handle_debug('stacktrace', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugEvaluate' and len(args) >= 1:
                result = panel._handle_debug('evaluate', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugSetBreakpoint' and len(args) >= 2:
                result = panel._handle_debug('set_breakpoint', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugToggleBreakpoint' and len(args) >= 2:
                result = panel._handle_debug('toggle_breakpoint', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugRemoveBreakpoint' and len(args) >= 2:
                result = panel._handle_debug('remove_breakpoint', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugGetBreakpoints':
                result = panel._handle_debug('get_breakpoints', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'debugGetState':
                result = panel._handle_debug('get_state', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            # ★ 插件市场管理
            elif method == 'listPlugins':
                result = panel._handle_plugin('list', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'getPluginDetail' and len(args) >= 1:
                result = panel._handle_plugin('detail', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'installPlugin' and len(args) >= 1:
                result = panel._handle_plugin('install', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'uninstallPlugin' and len(args) >= 1:
                result = panel._handle_plugin('uninstall', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'enablePlugin' and len(args) >= 1:
                result = panel._handle_plugin('enable', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'disablePlugin' and len(args) >= 1:
                result = panel._handle_plugin('disable', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'reloadPlugin' and len(args) >= 1:
                result = panel._handle_plugin('reload', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'searchPlugins' and len(args) >= 1:
                result = panel._handle_plugin('search', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'getPluginConfig' and len(args) >= 1:
                result = panel._handle_plugin('get_config', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'setPluginConfig' and len(args) >= 2:
                result = panel._handle_plugin('set_config', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'getPluginConfigSchema' and len(args) >= 1:
                result = panel._handle_plugin('config_schema', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'listPluginCategories':
                result = panel._handle_plugin('categories', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'getPluginSummary':
                result = panel._handle_plugin('summary', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'executePluginTool' and len(args) >= 1:
                result = panel._handle_plugin('execute_tool', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            # ★ Skills 技能管理 —— listSkills / getSkillDetail / executeSkill / listSkillCategories / searchSkills
            elif method == 'listSkills':
                result = panel._handle_skills('list', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'getSkillDetail' and len(args) >= 1:
                result = panel._handle_skills('detail', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'executeSkill' and len(args) >= 1:
                result = panel._handle_skills('execute', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'listSkillCategories':
                result = panel._handle_skills('categories', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'searchSkills' and len(args) >= 1:
                result = panel._handle_skills('search', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            # ★ 自动更新检查 —— checkUpdates / getVersionInfo / downloadUpdate / installUpdate / rollbackUpdate / dismissUpdate
            elif method == 'checkUpdates':
                result = panel._handle_updater('check', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'getVersionInfo':
                result = panel._handle_updater('version_info', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'getUpdateHistory':
                result = panel._handle_updater('history', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'downloadUpdate' and len(args) >= 1:
                result = panel._handle_updater('download', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'installUpdate' and len(args) >= 1:
                result = panel._handle_updater('install', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'rollbackUpdate':
                result = panel._handle_updater('rollback', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'dismissUpdate':
                result = panel._handle_updater('dismiss', args)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            # ★ v4.6.2: HTML 快捷键回退路径（window.pybridge 不可用时走 _callPython）
            elif method == 'cycleEngine':
                panel.engine_cycle_requested.emit()
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps({'success': True}, ensure_ascii=False)})"
                    )
            elif method == 'openSettings':
                panel.settings_open_requested.emit()
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps({'success': True}, ensure_ascii=False)})"
                    )
            elif method == 'listDirectory' and len(args) > 0:
                result = panel._handle_list_directory(args[0] if args else '')
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'getFileContent' and len(args) > 0:
                result = panel._handle_get_file_content(args[0])
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'documentAction' and len(args) >= 1:
                result = panel._handle_document_action(args[0] if len(args) > 0 else {})
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'openFileAtLine' and len(args) >= 2:
                result = panel._handle_open_file_at_line(args[0], args[1])
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'getCustomProviders' and len(args) == 0:
                result = panel._handle_custom_providers()
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'addCustomEngine' and len(args) >= 1:
                result = panel._handle_add_custom_provider(args[0] if args else {})
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'testCustomEngine' and len(args) >= 1:
                result = panel._handle_test_custom_engine(args[0] if args else {})
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'financialAction' and len(args) >= 1:
                result = panel._handle_financial_action(args[0] if args else "")
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'financeAction' and len(args) >= 1:
                # ★ v351 审计修复: 前端金融面板实际调用 'financeAction'（历史拼写），
                #   此前只注册了 'financialAction' → 行情/记账两个按钮空连接。别名转发。
                result = panel._handle_financial_action(args[0] if args else "")
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'webEmbedAction' and len(args) >= 1:
                result = panel._handle_web_embed_action(args[0] if args else "")
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'codePlaybackAction' and len(args) >= 1:
                result = panel._handle_code_playback_action(args[0] if args else "")
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'setAgentEffort' and len(args) >= 1:
                # ★ Lemon Work: 思考档位（light/standard/deep）
                self._agent_effort = str(args[0] or "standard")
                result = {"ok": True, "effort": self._agent_effort}
                print(f"[LemonWork] 思考档位 → {self._agent_effort}", flush=True)
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'testEngineLatency':
                # ★ Lemon Work: 真实连接测试 —— 逐引擎 ping（ollama/mimocode 探活、
                #   deepseek 真鉴权 /models），后台线程不阻塞 UI，回调带毫秒延迟
                import threading as _th
                import time as _tmod

                def _ping_work():
                    res = {}
                    import requests as _rq
                    _noproxy = {"http": None, "https": None}
                    for eng_id, url in (
                        ("ollama", "http://127.0.0.1:11434/api/tags"),
                        ("mimocode", "http://127.0.0.1:4097/global/health"),
                    ):
                        _t0 = _tmod.time()
                        try:
                            _r = _rq.get(url, timeout=3, proxies=_noproxy)
                            res[eng_id] = {"online": _r.status_code == 200,
                                           "ms": int((_tmod.time() - _t0) * 1000)}
                        except Exception:
                            res[eng_id] = {"online": False, "ms": 0}
                    try:
                        em = getattr(panel, "_engine_manager", None)
                        eng = em.get_engine("deepseek") if em else None
                        _cfg = getattr(eng, "config", None)
                        _key = getattr(_cfg, "api_key", "") or ""
                        _base = (getattr(_cfg, "api_base", "") or "https://api.deepseek.com/v1").rstrip("/")
                        _t0 = _tmod.time()
                        _r = _rq.get(_base + "/models",
                                     headers={"Authorization": "Bearer " + _key},
                                     timeout=6)
                        res["deepseek"] = {"online": _r.status_code == 200,
                                           "ms": int((_tmod.time() - _t0) * 1000)}
                    except Exception:
                        res["deepseek"] = {"online": False, "ms": 0}
                    if callback_id is not None:
                        self.runJavaScript(
                            "window._pybridgeCallback(%d, %s)" % (
                                callback_id, json.dumps(res, ensure_ascii=False)))

                _th.Thread(target=_ping_work, daemon=True).start()
                result = {"ok": True, "testing": True}
            elif method == 'removeQueuedMessage' and len(args) >= 1:
                # ★ Lemon Work: 单条撤销排队消息（前端排队列表 × 按钮）
                panel._remove_pending_message(args[0])
                result = {"ok": True}
            elif method == 'pauseQueue':
                # ★ v350: 挂起排队自动发送（前端 ⏸ 挂起按钮）
                panel._toggle_pending_pause(True)
                result = {"ok": True}
            elif method == 'resumeQueue':
                # ★ v350: 恢复排队自动发送
                panel._toggle_pending_pause(False)
                result = {"ok": True}
            elif method == 'sendQueuedNow' and len(args) >= 1:
                # ★ v350: 单条立即发送（前端 ↑ 按钮）
                panel._send_pending_now(args[0])
                result = {"ok": True}
            elif method == 'regenerateLast':
                # ★ v351: 重新生成（微信版 quick-row 对齐）
                result = panel._regenerate_last()
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'probeLocalModels':
                # ★ v355: 本地模型探测器 —— 真实拉取 Ollama /api/tags
                def _probe_local_work():
                    res = panel._list_local_models()
                    if callback_id is not None:
                        self.runJavaScript(
                            f"window._pybridgeCallback({callback_id}, {json.dumps(res, ensure_ascii=False)})"
                        )
                import threading as _thp
                _thp.Thread(target=_probe_local_work, daemon=True).start()
                result = {"ok": True, "probing": True}
            elif method == 'addCustomModel' and len(args) >= 1:
                # ★ v355: 添加自定义模型（Trae 式表单）—— 保存前真探测
                import threading as _thc
                def _add_cm_work():
                    try:
                        payload = json.loads(args[0]) if isinstance(args[0], str) else (args[0] or {})
                    except Exception:
                        payload = {}
                    res = panel._add_custom_model(payload)
                    if callback_id is not None:
                        self.runJavaScript(
                            f"window._pybridgeCallback({callback_id}, {json.dumps(res, ensure_ascii=False)})"
                        )
                _thc.Thread(target=_add_cm_work, daemon=True).start()
                result = {"ok": True, "adding": True}
            elif method == 'listCustomModels':
                # ★ v355: 已存自定义模型（recheck=true 时掉线剔除）
                import threading as _thl
                _recheck = bool(args and args[0])
                def _list_cm_work():
                    res = panel._list_custom_models(recheck=_recheck)
                    if callback_id is not None:
                        self.runJavaScript(
                            f"window._pybridgeCallback({callback_id}, {json.dumps(res, ensure_ascii=False)})"
                        )
                _thl.Thread(target=_list_cm_work, daemon=True).start()
                result = {"ok": True, "loading": True}
            elif method == 'removeCustomModel' and len(args) >= 1:
                # ★ v355: 删除自定义模型
                result = panel._remove_custom_model(args[0])
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False)})"
                    )
            elif method == 'setActiveCustom' and len(args) >= 1:
                # ★ v355: 激活自定义模型（发送时覆盖 deepseek 引擎的 base_url/key/model）
                cm_id = str(args[0] or "")
                panel._active_custom_id = cm_id
                found = None
                for m in panel._custom_models_load():
                    if str(m.get("id")) == cm_id:
                        found = m
                        break
                panel._active_custom_model = found  # None = 取消激活
                print(f"[CustomModel] 激活: {found.get('name') if found else '(取消)'}", flush=True)
                result = {"ok": True, "active": bool(found)}
            elif method == 'cmdAction' and len(args) >= 1:
                result = panel._handle_cmd_action(args[0] if args else {})
                if callback_id is not None:
                    self.runJavaScript(
                        f"window._pybridgeCallback({callback_id}, {json.dumps(result, ensure_ascii=False, default=str)})"
                    )
        except Exception as e:
            print(f"[PYBRIDGE] 调度错误: {method}: {e}")


# ============================================================
# ★ v3.63: Agent 工具调用循环异步执行 Worker（QThread）
# ============================================================
class AgentChatWorker(QThread):
    """在独立线程中执行 EngineManager.agent_chat()，避免阻塞 UI。

    信号：
        started_event(str):     Agent 循环开始（携带 prompt 摘要）
        tool_call_event(dict):  一次工具调用完成（name/arguments/result/success）
        finished_event(dict):   Agent 循环结束（content/iterations/tool_calls_made/total_time）
        error_event(str):       执行异常
        cancelled_event():      被用户取消
        stream_token_event(str):★ v3.64 流式 token 到达（实时）

    使用：
        worker = AgentChatWorker(engine_mgr, prompt, engine="deepseek", model="deepseek-chat")
        worker.tool_call_event.connect(ui._on_agent_tool_call)
        worker.finished_event.connect(ui._on_agent_finished)
        worker.start()
    """
    started_event = pyqtSignal(str)
    tool_call_event = pyqtSignal(dict)
    finished_event = pyqtSignal(dict)
    error_event = pyqtSignal(str)
    cancelled_event = pyqtSignal()
    stream_token_event = pyqtSignal(str)  # ★ v3.64 流式 token

    def __init__(self, engine_manager, prompt: str, parent=None, **kwargs):
        super().__init__(parent)
        self._engine_manager = engine_manager
        self._prompt = prompt
        self._kwargs = kwargs  # engine/model/system_prompt/history/max_iterations
        self._cancelled = False

    def cancel(self):
        """外部取消请求（线程安全：通过 EngineManager.cancel_agent() 间接传递）"""
        self._cancelled = True
        if self._engine_manager is not None:
            try:
                self._engine_manager.cancel_agent()
            except Exception:
                pass

    def run(self):
        """QThread 入口：执行 agent_chat 并发射信号"""
        try:
            self.started_event.emit(self._prompt[:80])

            # ★ v3.64: 流式回调 — 把 token 转发到 UI 线程
            def _stream_cb(token: str):
                try:
                    self.stream_token_event.emit(token)
                except Exception:
                    pass

            # 注入 stream_callback（agent_chat 会读取 kwargs["stream_callback"]）
            kwargs = dict(self._kwargs)
            kwargs.setdefault("stream_callback", _stream_cb)

            result = self._engine_manager.agent_chat(self._prompt, **kwargs)

            # 检查是否被取消
            if result.get("cancelled", False) or self._cancelled:
                self.cancelled_event.emit()
            else:
                self.finished_event.emit(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error_event.emit(str(e))


class MIMOCodePanel(QWidget):
    command_sent = pyqtSignal(str)  # 发送给主窗口的命令信号
    # 交互式操作信号（用于 ACP 桥）
    config_applied = pyqtSignal(str, str, object)  # (action, sessionId, changes)
    permission_responded = pyqtSignal(str, str)    # (sessionId, choiceId)
    mode_switch_requested = pyqtSignal(str)         # (modeId)
    # 新增：模型/会话管理信号
    model_switch_requested = pyqtSignal(str)        # (modelId)
    session_switch_requested = pyqtSignal(str)      # (sessionId)
    fetch_models_requested = pyqtSignal()           # 请求获取模型列表
    fetch_sessions_requested = pyqtSignal()         # 请求获取会话列表
    new_session_requested = pyqtSignal()            # 请求新建会话
    # 新增：服务模式切换信号
    service_mode_switch_requested = pyqtSignal(str) # (modeId: single/multi/terminal/demo/hybrid)
    # 新增：图片/文件上传信号
    image_uploaded = pyqtSignal(str, str)  # (file_name, base64_data)
    file_uploaded = pyqtSignal(str, str)   # (file_name, base64_data)
    # 信任模式变更信号
    trust_mode_changed = pyqtSignal(bool)
    # ★ 工作区切换信号（主窗口连接后更新 explorer/git/terminal）
    workspace_switch_requested = pyqtSignal(str)  # (workspace_path)
    # ★ v4.6.2: HTML 快捷键请求信号（PyBridge/_handle_pybridge → main_window）
    engine_cycle_requested = pyqtSignal()     # Ctrl+Alt+E 循环切换 AI 引擎
    settings_open_requested = pyqtSignal()    # Ctrl+, 打开设置 / API 配置
    error_occurred = pyqtSignal(str)          # ★ 错误消息信号（连接到右侧面板显示）
    output_received = pyqtSignal(str)         # ★ 输出信号（Agent 完成时发射，连接到 on_output）
    # ★ 卡顿修复: MIMO 状态后台线程检查完成信号（网络探测不再阻塞主线程）
    _mimo_status_checked = pyqtSignal(bool, bool)  # (port_open, http_ok)
    # ★ Lemon Work: 首轮任务完成 → 建议会话标题（自动命名 + 时间标）
    title_suggested = pyqtSignal(str, str)   # (session_id, title)
    # ★ 第362章 · P4 闭环尾部：技能审核卡 / 音频播放卡 / 市场下载闭环 / 记忆导出
    skill_review_signal = pyqtSignal(str)        # {"pending": [...], "count": N}
    audio_preview_signal = pyqtSignal(str)       # {"files": [...], "dir": ...}
    market_download_signal = pyqtSignal(str)     # {"success": bool, "error": ..., "data": ...}


    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_path = os.getcwd()
        self._is_connected = False
        self._js_ready = False
        self._pending_calls = []
        # JS 调用节流队列（防止 SSE 事件流阻塞 UI）
        self._js_call_queue = []
        self._output_history = []  # 会话输出历史（用于会话切换）
        # ★ v3.68: 对话上下文历史（user/assistant 消息对），供 agent_chat 使用
        self._conversation_context: list = []  # [{"role":"user","content":...},{"role":"assistant","content":...}]
        self._max_context_turns = 10  # 保留最近 10 轮对话（20 条消息）
        # ★ v3.70: 多模态支持 — 暂存用户上传的图片 base64（发送消息时附加，发送后清空）
        self._pending_images: list = []  # [{"name": "img.png", "data": "base64..."}, ...]
        # ★ serve_bridge 引用（由 main_window 设置）
        self._serve_bridge = None
        # ★ engine_manager 引用（由 main_window 设置）
        self._engine_manager = None
        self._engine_stream_buffer = ""  # 引擎流式输出缓冲区
        self._max_history_size = 500  # 最大历史条目数（防止内存泄漏）
        # ★ v4.7: Agent 角色系统 — 当前选择的角色（coder/analyst/writer/assistant）
        self._current_role = "coder"
        self._role_names = {
            "coder": "代码专家", "analyst": "分析师",
            "writer": "写作专家", "assistant": "助手",
        }
        # ★ v3.51: 引擎模式管理器
        self._mode_manager = EngineModeManager()
        self._mode_manager.on_mode_changed(self._on_mode_changed)
        # ★ v3.57: MIMO 状态监控定时器（30秒间隔）
        self._mimo_status_timer = QTimer()
        self._mimo_status_timer.setInterval(30000)  # 30秒
        self._mimo_status_timer.timeout.connect(self._check_mimo_status)
        self._mimo_status_checked.connect(self._apply_mimo_status)  # ★ 卡顿修复: 后台探测结果回主线程
        # ★ 第345章: TraceRenderer 统一时间线（v346: 默认开启；LEMON_TRACE_V2=0 回退旧版）
        self._trace_v2 = os.environ.get("LEMON_TRACE_V2", "1") != "0"
        if self._trace_v2:
            print("[Trace] v2 统一时间线已启用（旧路径已门控；设 LEMON_TRACE_V2=0 回退）")
        self._trace_seq = 0
        self._trace_tool_stack = []   # [{name, t0}] 用于计算工具耗时
        self._trace_text_buf = None   # {"text": str} 流式文本缓冲
        self._trace_text_last = 0.0
        # ★ T367.4: 状态行发射器串行化
        self._status_emit_lock = threading.Lock()
        self._status_emit_pending = {}  # kind -> payload (latest wins)
        self._status_emit_last_ts = 0.0
        self._mimo_available = False  # 当前 MIMO 是否可用
        self._mimo_first_attempt = True  # 是否首次尝试 MIMO 模式
        self._mimo_was_available = False  # 上一次检查的可用性（用于检测状态变化）
        # ★ 优化：JS flush 定时器间隔从 50ms 改为 150ms（降低 67% 频率，显著减少卡顿）
        self._js_flush_timer = QTimer()
        self._js_flush_timer.setInterval(150)
        self._js_flush_timer.timeout.connect(self._flush_js_queue)
        self._init_ui()
        # ★ 兜底：3秒后强制设置 _js_ready，防止 _on_load_finished 从未被调用
        from PyQt5.QtCore import QTimer as _QTimer
        _QTimer.singleShot(3000, self._force_js_ready)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.web_view = QWebEngineView()
        
        try:
            self._profile = QWebEngineProfile(self.web_view)
            self._profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
            self._profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
            page = DebugWebPage(self._profile, self, profile_used=True)
        except Exception as e:
            print(f"[MIMO Panel] 独立 profile 创建失败: {e}, 使用默认 profile")
            page = DebugWebPage(self.web_view, self)
        
        self.web_view.setPage(page)
        self.web_view.setStyleSheet(f"background: {Lemon.DARK_BG_1};")
        # ★ 设置页面背景色，防止加载前闪烁白屏
        try:
            from PyQt5.QtGui import QColor
            self.web_view.page().setBackgroundColor(QColor(f'{Lemon.DARK_BG_1}'))
        except Exception:
            pass
        
        # 启用必要的 WebSettings
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanPaste, True)
        
        # 创建 WebChannel 和桥接对象
        self.channel = QWebChannel()
        self.pybridge = PyBridge(self)


        # ★ 第362章：P4 闭环尾部信号 → JS（技能审核卡/音频卡/市场/记忆导出）
        try:
            self.pybridge.skill_review_signal.connect(self._js_v6p4_skill_review)
            self.pybridge.audio_preview_signal.connect(self._js_v6p4_audio_preview)
            self.pybridge.market_download_signal.connect(self._js_v6p4_market_result)
            self.pybridge.memory_export_signal.connect(self._js_v6p4_memory_result)
        except Exception as e:
            print(f"[MIMO Panel] 第362章信号接线失败: {e}")

        # ★ 第362章：延迟注入 P4 顶层入口（3.5s 后；页面加载后再操作 DOM）
        try:
            from PyQt5.QtCore import QTimer as _QTimer_P4
            _QTimer_P4.singleShot(3500, self._ensure_v6p4_overlay)
        except Exception as e:
            print(f"[MIMO Panel] 第362章延迟注入失败: {e}")
        self.channel.registerObject("pybridge", self.pybridge)
        # ★ v4.7.x: 咩咩真流式桥接（miemie_panel.py → JS miemieTypewriter）
        try:
            from .miemie_panel import get_miemie_bridge
            self.miemie_bridge = get_miemie_bridge()
            self.channel.registerObject("miemieBridge", self.miemie_bridge)
        except Exception as e:
            print(f"[MimoPanel] miemieBridge 注册失败: {e}")
        self.web_view.page().setWebChannel(self.channel)

        # K8：把几维鸟 3D 图表经 QWebChannel 推到 mimo_page 的 #kiwi-chart 容器。
        # plot3d_view.set_plot_sink 为模块级钩子，无需持有 kiwi 面板引用：
        # 一旦 kiwi 的 3D 页绘制，build_plotly_html 输出即推入 mimo 页面渲染。
        try:
            from vizboard.ui import plot3d_view
            _kiwi_page = self.web_view.page()
            plot3d_view.set_plot_sink(
                lambda html, title: _kiwi_page.runJavaScript(
                    "if(window.renderKiwiChart){window.renderKiwiChart(%s)}" % json.dumps(html)))
        except Exception as e:  # 缺 vizboard / 无 QWebEngine 时静默跳过
            print(f"[MimoPanel] kiwi 图表通道未接线（跳过）：{e}")

        # 加载 HTML 文件（加时间戳防止缓存 — v4.0.4 修复右侧栏覆盖）
        # ★ 注意：不再加 embed=1；右侧栏与主窗口共用同一份 mimo_page.html，
        #   主题/壁纸策略通过 ThemeManager.apply 和 body.right-panel-mode 统一处理。
        html_path = os.path.join(os.path.dirname(__file__), "mimo_page.html")
        html_url = QUrl.fromLocalFile(html_path)
        # ★ v4.0.4: 强制刷新避免缓存
        import time
        html_url.setQuery(f"v={int(time.time())}&panel=1")
        self.web_view.setUrl(html_url)
        
        # 页面加载完成后的回调
        self.web_view.loadStarted.connect(lambda: print("[MIMO Panel] HTML 开始加载"))
        self.web_view.loadProgress.connect(lambda p: print(f"[MIMO Panel] HTML 加载进度: {p}%"))
        self.web_view.loadFinished.connect(self._on_load_finished)
        
        layout.addWidget(self.web_view)
        
        # 连接信号
        self.pybridge.append_message_signal.connect(self._js_append_message)
        self.pybridge.append_thinking_signal.connect(self._js_append_thinking)
        self.pybridge.append_status_signal.connect(self._js_append_status)
        self.pybridge.append_tool_signal.connect(self._js_append_tool)
        self.pybridge.append_timeline_signal.connect(self._js_append_timeline)
        self.pybridge.append_steps_signal.connect(self._js_append_steps)
        self.pybridge.agent_status_signal.connect(self._js_append_agent_status)
        self.pybridge.append_preview_signal.connect(self._js_append_preview)
        self.pybridge.append_user_message_signal.connect(self._js_append_user_message)
        self.pybridge.set_connected_signal.connect(self._js_set_connected)
        self.pybridge.set_robot_status_signal.connect(self._js_set_robot_status)
        self.pybridge.show_config_options_signal.connect(self._js_show_config_options)
        self.pybridge.show_permission_signal.connect(self._js_show_permission)
        self.pybridge.set_mode_signal.connect(self._js_set_mode)
        self.pybridge.show_plan_signal.connect(self._js_show_plan)
        self.pybridge.show_commands_signal.connect(self._js_show_commands)
        self.pybridge.show_usage_signal.connect(self._js_show_usage)
        self.pybridge.set_agent_state_signal.connect(self._js_set_agent_state)
        self.pybridge.background_task_signal.connect(self._js_background_task)
        self.pybridge.show_models_signal.connect(self._js_show_models)
        self.pybridge.show_sessions_signal.connect(self._js_show_sessions)
        self.pybridge.set_current_model_signal.connect(self._js_set_current_model)
        self.pybridge.set_current_session_signal.connect(self._js_set_current_session)
        # ★ 流式输出信号连接
        self.pybridge.eval_js_signal.connect(self._js_eval)
        # ★ v4.3.8: 咩咩 Agent 真流式事件 → JS
        self.pybridge.miemie_event_signal.connect(self._js_miemie_event)

        # ===== 初始化 Ollama 千问模型桥接（小机器人聊天用） =====
        self.ollama_bridge = None
        self._ollama_available = False

        # ★ 延迟导入 OllamaBridge（通过 compat 层统一 AI 调用）
        global _OllamaBridge, _OLLAMA_AVAILABLE
        if _OLLAMA_AVAILABLE is None:
            try:
                from standard_mode.compat import OllamaBridge  # ★ v3.45: 通过 compat 层统一 AI 调用
                _OllamaBridge = OllamaBridge
                _OLLAMA_AVAILABLE = True
            except Exception as _e:
                print(f"[MIMO Panel] OllamaBridge 导入失败: {_e}")
                _OllamaBridge = None
                _OLLAMA_AVAILABLE = False

        if _OLLAMA_AVAILABLE and _OllamaBridge:
            try:
                self.ollama_bridge = _OllamaBridge(parent=self)
                # 收到模型回复 → 转发到 JS 并发出信号
                self.ollama_bridge.reply_received.connect(self._on_robot_reply_received)
                self.ollama_bridge.error_occurred.connect(self._on_robot_error_received)
                self._ollama_available = True
                print("[MIMO Panel] OllamaBridge 已初始化（qwen3.5:4b）")
            except Exception as e:
                print(f"[MIMO Panel] OllamaBridge 初始化失败: {e}")
                self.ollama_bridge = None
                self._ollama_available = False
        else:
            print("[MIMO Panel] OllamaBridge 不可用，小机器人将使用本地兜底回复")

    def _on_load_finished(self, ok):
        """页面加载完成 - 初始化 Console Message Bridge"""
        print(f"[MIMO Panel] HTML 加载完成信号: ok={ok}")
        # ★ 关键修复：即使页面加载失败也要设置 _js_ready（防止队列永远阻塞）
        # 之前：if not ok: return  ← 导致 loadFailed 时 _js_ready 永远为 False
        self._js_ready = True
        print(f"[MIMO Panel] _js_ready = True (立即设置), 队列大小: {len(self._js_call_queue)}")
        # ★ 立即启动 flush 定时器，确保积压的 JS 调用被执行
        if self._js_call_queue:
            self._js_flush_timer.start(50)
        
        if not ok:
            print("[MIMO Panel] HTML 页面加载失败（部分资源可能缺失），但桥接队列已解锁")
            # 即使页面整体加载失败，内联脚本通常仍可运行，尝试同步主题并打诊断日志
        else:
            print("[MIMO Panel] HTML 页面加载完成，Console Message Bridge 已就绪")

        # 页面加载完成后，同步当前主题让壁纸正常显示（不再隐藏 typewriterfield）
        # mimo_page.html 内部 ThemeManager.apply 已处理壁纸切换
        # ★ v4.1.13: 后端默认值从 focus_moment 改为 default，避免右栏刷新后
        # 自动跳回"专注时刻"打字机壁纸，保持用户期望的原始默认界面。
        current_theme = getattr(self, '_current_theme', 'default')
        # 同步主题：立即执行一次，若 ThemeManager 未就绪则延迟重试，确保壁纸/主题生效
        sync_js = """
(function(){
  var theme = '%s';
  function doApply(attempt) {
    try {
      if (window.ThemeManager && typeof window.ThemeManager.apply === 'function') {
        window.ThemeManager.apply(theme);
        console.log('[MIMO Panel] 主题同步完成 (' + attempt + ')');
        return true;
      }
    } catch(e) {
      console.error('[MIMO Panel] 主题同步异常:', e);
    }
    if (attempt < 5) {
      console.warn('[MIMO Panel] ThemeManager 未就绪，第' + attempt + '次重试...');
      setTimeout(function(){ doApply(attempt + 1); }, 300 * attempt);
    } else {
      console.error('[MIMO Panel] ThemeManager 最终未就绪，主题同步失败');
    }
    return false;
  }
  doApply(1);
})();
""" % current_theme
        try:
            self.web_view.page().runJavaScript(sync_js)
        except Exception as e:
            print(f"[MIMO Panel] 同步主题失败: {e}")

        # ★ 右侧栏专用修正：
        # 给 body 加 right-panel-mode，让 CSS 把为全宽主窗口设计的 fixed 控件
        # （服务模式切换器、动作按钮、机器人）重新定位到窄栏内；
        # 同时给 typewriter iframe 加 isolation，减少 Qt WebEngine 中 WebGL 合成层
        # 越级覆盖 fixed 控件的概率。
        fix_iframe_js = """
(function(){
  if (window._lemonFixApplied) return;
  window._lemonFixApplied = true;
  try {
    if (document.body) {
      document.body.classList.add('right-panel-mode');
      document.body.style.position = 'relative';
    }
    // ★ v4.1.31: typewriterfield iframe 已彻底移除，无需 isolation 修复
    console.log('[MIMO Panel] 右侧栏模式已启用');
  } catch(e) {
    console.log('[MIMO Panel] 右侧栏修正失败:', e);
  }
})();
"""
        try:
            self.web_view.page().runJavaScript(fix_iframe_js)
        except Exception as e:
            print(f"[MIMO Panel] 修复定位失败: {e}")

        # 绑定输入框同步（通过 Console Message Bridge）
        bind_js = """
(function() {
    var inputEl = document.getElementById('inputField');
    if (inputEl) {
        var _lastSyncVal = '';
        inputEl.addEventListener('input', function() {
            var val = inputEl.value;
            if (val !== _lastSyncVal) {
                _lastSyncVal = val;
                window._callPython('syncInput', val);
            }
        });
        console.log('[输入同步] 右侧→底部 绑定成功 (Console Bridge)');
    }
    
    // 桥接回显测试
    window._callPython('echo', 'hello from js', function(r) {
        console.log('[MIMO] 桥接回显测试: ' + r);
    });
    
    // 更新桥接状态
    if (window._updateBridgeStatus) {
        window._updateBridgeStatus(true, 'Console Bridge');
    }
    console.log('[MIMO] Console Message Bridge 已就绪');

    // DIAG: output-area runtime state check
    setTimeout(function() {
        try {
            var om = document.getElementById('outputMessages');
            var oa = document.querySelector('.output-area');
            var wa = document.querySelector('.workspace-area');
            var ct = document.getElementById('content');
            if (om) {
                var cs = window.getComputedStyle(om);
                console.log('[DIAG] outputMessages: display=' + cs.display + ' visibility=' + cs.visibility + ' overflow=' + cs.overflow + ' height=' + cs.height + ' width=' + cs.width + ' opacity=' + cs.opacity + ' zIndex=' + cs.zIndex + ' childCount=' + om.children.length + ' scrollTop=' + om.scrollTop + ' scrollHeight=' + om.scrollHeight);
            } else {
                console.log('[DIAG] outputMessages: NOT FOUND');
            }
            if (oa) {
                var cs2 = window.getComputedStyle(oa);
                console.log('[DIAG] output-area: display=' + cs2.display + ' height=' + cs2.height + ' overflow=' + cs2.overflow + ' flex=' + cs2.flex);
            }
            if (wa) {
                var cs3 = window.getComputedStyle(wa);
                console.log('[DIAG] workspace-area: display=' + cs3.display + ' height=' + cs3.height + ' flex=' + cs3.flex);
            }
            if (ct) {
                var cs4 = window.getComputedStyle(ct);
                console.log('[DIAG] #content: display=' + cs4.display + ' height=' + cs4.height + ' position=' + cs4.position + ' overflow=' + cs4.overflow + ' pointerEvents=' + cs4.pointerEvents);
            }
            // [DIAG] 可见测试消息注入已移除（会污染用户对话流；console 诊断保留）
        } catch(e) {
            console.error('[DIAG] Diagnostic failed:', e);
        }
    }, 2000);
})();
"""
        self.web_view.page().runJavaScript(bind_js)
        
        # 延迟检查桥接状态（仅诊断，不再依赖它设置 _js_ready）
        from PyQt5.QtCore import QTimer
        # ★ 优化：桥健康检查从 1.5s 改为 5s（降低主线程压力）
        QTimer.singleShot(3000, self._check_bridge_health)

    def _check_bridge_health(self):
        """检查 Console Message Bridge 是否正常"""
        def on_result(result):
            if result is None:
                result = 'None'
            print(f"[桥接监控] JS 桥接状态: {result}")
            # ★ 桥接就绪：设置 _js_ready = True，让 _flush_js_queue 开始执行
            self._js_ready = True
            print(f"[MIMO Panel] _js_ready = True, 队列大小: {len(self._js_call_queue)}")
            # ★ 关键：重启定时器以立即 flush 缓冲的 JS 调用
            if self._js_call_queue:
                self._js_flush_timer.start(50)
        self.web_view.page().runJavaScript(
            "typeof window._callPython !== 'undefined' ? "
            "'bridge=ok, _callPython=' + (typeof window._callPython) + ', _pybridgeCallback=' + (typeof window._pybridgeCallback) "
            ": 'bridge=missing, _callPython=' + (typeof window._callPython)",
            on_result
        )

    def _force_js_ready(self):
        """兜底：强制设置 _js_ready = True（防止页面加载失败导致队列永远阻塞）"""
        if not self._js_ready:
            self._js_ready = True
            print(f"[MIMO Panel] ★ 兜底: _js_ready = True (3秒超时), 队列大小: {len(self._js_call_queue)}")
            if self._js_call_queue:
                self._js_flush_timer.start(50)

    def _notify_js_ready(self):
        """通知 JS 端 Python 已就绪"""
        def on_check(result):
            print(f"[MIMO Panel] window.mimoAgent 检查: {result}")
            self._js_ready = True
            for call in self._pending_calls:
                self.web_view.page().runJavaScript(call)
            self._pending_calls.clear()
        self.web_view.page().runJavaScript(
            "typeof window.mimoAgent !== 'undefined' ? 'ok' : 'missing'", on_check
        )

    def _on_js_send_message(self, message):
        """
        JavaScript 调用解析：
        - 普通消息直接发送
        - __config__:JSON → 配置选项变更
        - __permission__:sid|choice → 权限响应
        - __mode__:modeId → 模式切换
        """
        if message.startswith('__config__:'):
            # 配置选项变更
            try:
                changes = json.loads(message[len('__config__:'):])
                if changes:
                    self.config_applied.emit('apply', '', changes)
            except (json.JSONDecodeError, Exception) as e:
                print(f"[MIMO Panel] 配置解析错误: {e}")
        
        elif message.startswith('__permission__:'):
            # 权限响应
            try:
                parts = message[len('__permission__:'):].split('|', 1)
                if len(parts) == 2:
                    session_id, choice_id = parts
                    self.permission_responded.emit(session_id, choice_id)
            except Exception as e:
                print(f"[MIMO Panel] 权限解析错误: {e}")
        
        elif message.startswith('__mode__:'):
            # 模式切换
            mode_id = message[len('__mode__:'):]
            self.mode_switch_requested.emit(mode_id)
        
        elif message.startswith('__model__:'):
            # 模型切换
            model_id = message[len('__model__:'):]
            self.model_switch_requested.emit(model_id)
        
        elif message.startswith('__session__:'):
            # 会话切换
            session_id = message[len('__session__:'):]
            self.session_switch_requested.emit(session_id)

        elif message.startswith('__action_card__:'):
            # ★第404章 ActionCard 动态操作卡按钮点击（前端事件委托 → 这里分派）
            try:
                self._on_action_card_click(message[len('__action_card__:'):])
            except Exception as e:
                print(f"[MIMO Panel] ActionCard 点击处理失败: {e}")

        elif message == '__fetch_models__':
            # 请求获取模型列表
            self.fetch_models_requested.emit()
        
        elif message == '__fetch_sessions__':
            # 请求获取会话列表
            self.fetch_sessions_requested.emit()
        
        elif message == '__new_session__':
            # 请求新建会话
            self.new_session_requested.emit()
        
        elif message.startswith('__skill__:'):
            # ★ P7: Skill 调用 — 执行指定 Skill 并返回结果
            skill_id = message[len('__skill__:'):]
            self._handle_skill_invoke(skill_id)
        
        elif message.startswith('__service_mode__:'):
            # 服务模式切换
            mode_id = message[len('__service_mode__:'):]
            self.service_mode_switch_requested.emit(mode_id)

        elif message == '__stop_agent__':
            # ★392A-2: 状态条停止按钮 —— 立即中断进行中的 agent 任务（不等轮间检查）
            self._request_agent_interrupt()

        elif message.startswith('__test_conn__:'):
            # ★ v4.7.x: 设置面板连接测试 — 后台线程实测 DeepSeek / Ollama 连通性
            try:
                payload = json.loads(message[len('__test_conn__:'):])
                self._run_connection_test(payload)
            except Exception as e:
                print(f"[MIMO Panel] 连接测试参数解析错误: {e}")

        elif message.startswith('__file_open__:'):
            # ★第360章: 文件卡「打开」— 系统默认程序打开 Agent 产出文件
            self._handle_file_open(message[len('__file_open__:'):])

        elif message.startswith('__file_export__:'):
            # ★第360章: 文件卡「导出」— 另存为对话框复制 Agent 产出文件
            self._handle_file_export(message[len('__file_export__:'):])

        elif message == '__clear_pending__':
            # ★第362章: 对话消息队列「清空」— 前端角标×按钮
            self._clear_pending_queue()
        
        else:
            # ★ v4.1.10: 身份类问题本地拦截（修复模型自称 Claude Code / MiMo Code）
            if self._try_local_identity_answer(message):
                return
            # ★ v4.2.4: MIEMIE 咩咩风格注入 — 若已分析项目风格，附加风格上下文
            # 使咩咩在代码/PPT/文案等任务中起作用（对齐用户需求：风格分析与 Lemon 彻底交互）
            if getattr(self, "_miemie_injected", False):
                inject_text = self._miemie_inject_text()
                if inject_text:
                    message = f"{message}\n\n【咩咩风格参考（来自项目风格分析）】{inject_text}"
            # ★ v3.27: 标准模式 — 所有消息走 command_sent → serve_bridge
            # 完全绕过 EngineManager（混合模式引入的，与 serve_bridge 冲突）
            self.command_sent.emit(message)

    def _run_connection_test(self, payload):
        """★ v4.7.x: 连接测试 — 后台线程实测 DeepSeek / Ollama 连通性，结果经 eval_js 回推前端。

        - deepseek: GET {endpoint}/models（带 Bearer Key）→ 200=可用 / 401=Key 无效
        - ollama:   GET {host}/api/tags → 200=在线并列出模型数
        不阻塞 UI 线程；失败（网络异常/超时）也回推友好提示。
        """
        engine = (payload or {}).get('engine', '')

        def _push(ok, msg):
            try:
                self.pybridge.eval_js_signal.emit(
                    "if(typeof onConnTestResult==='function')onConnTestResult(%s,%s,%s);"
                    % (json.dumps(engine), 'true' if ok else 'false', json.dumps(msg, ensure_ascii=False))
                )
            except Exception as e:
                print(f"[MIMO Panel] 连接测试结果回推失败: {e}")

        def _worker():
            try:
                import requests
                if engine == 'deepseek':
                    base = ((payload.get('endpoint') or 'https://api.deepseek.com/v1') or '').rstrip('/')
                    key = payload.get('api_key') or ''
                    r = requests.get(base + '/models',
                                     headers={'Authorization': 'Bearer ' + key}, timeout=10)
                    if r.status_code == 200:
                        try:
                            models = r.json().get('data') or []
                            names = ','.join((m.get('id') or '') for m in models[:5])
                        except Exception:
                            names = ''
                        _push(True, '连接成功' + (' · ' + names if names else ''))
                    elif r.status_code == 401:
                        _push(False, 'API Key 无效 (401)')
                    else:
                        _push(False, 'HTTP %s' % r.status_code)
                elif engine == 'ollama':
                    host = ((payload.get('host') or 'http://localhost:11434') or '').rstrip('/')
                    r = requests.get(host + '/api/tags', timeout=5)
                    if r.status_code == 200:
                        try:
                            models = r.json().get('models') or []
                            _push(True, '连接成功 · %d 个模型' % len(models))
                        except Exception:
                            _push(True, '连接成功')
                    else:
                        _push(False, 'HTTP %s' % r.status_code)
                else:
                    _push(False, '未知引擎: %s' % engine)
            except Exception as e:
                _push(False, '连接失败: %s' % e)

        threading.Thread(target=_worker, daemon=True, name='conn-test').start()

    # ============================================================
    # ★ v4.1.10: 身份类问题本地拦截
    # ============================================================
    # ★第362章修复: 下方 def 曾被并入注释行（换行丢失）→ 方法未定义 →
    #   每次发消息在 _on_js_send_message 内 AttributeError 被 PyBridge
    #   分发器吞掉 → Agent 从不启动（用户实测"发消息罢工"根因）。
    def _try_local_identity_answer(self, message: str):
        """身份类问题本地兜底：命中时在本地生成标准身份回答并显示到右侧面板，
        不依赖底层模型（修复模型自称 Claude Code / MiMo Code 等身份错乱）。

        Returns:
            命中身份问题 → 返回回答文本（str），调用方应停止继续发送给引擎；
            未命中 → 返回 None。
        """
        try:
            from core.agent_identity import detect_identity_question, build_identity_answer
        except Exception:
            return None

        if not detect_identity_question(message):
            return None

        # 获取当前引擎与模型信息
        engine = ""
        model = ""
        try:
            mode_mgr = getattr(self, "_mode_manager", None)
            if mode_mgr is not None:
                engine = mode_mgr.get_target_engine()
        except Exception:
            pass
        try:
            if getattr(self, "_engine_manager", None) is not None:
                status = self._engine_manager.get_status()
                eng = status.get(engine) if engine else None
                if eng and isinstance(eng, dict):
                    model = eng.get("model") or eng.get("current_model") or ""
        except Exception:
            pass
        if not model:
            model = "由引擎自动选择"

        answer = build_identity_answer(engine=engine, model=model)

        # 显示到右侧面板（底部终端由调用方 main_window 同步显示）
        html = answer.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
        self._js_append_message(html)
        print(f"[Identity] 身份类问题本地回答: {message[:30]}...")
        return answer

    # ============================================================
    # Python → JavaScript 调用（带节流队列）
    # ============================================================
    def _safe_run_js(self, js):
        """安全执行 JS（Console Message Bridge 始终就绪）

        ★第433章: 线程自适应——工具在 AgentChatWorker(QThread) 里推卡
        （ActionCardRegistry ui_callback 直调本方法）时，QTimer.isActive/start
        跨线程属 Qt 禁区（计时器不会启动 → 队列 JS 永不执行 → live 卡不出）。
        非 GUI 线程一律经 eval_js_signal 排队回 GUI 线程再入队（QueuedConnection）。
        """
        if getattr(self, '_clean', False):
            return
        if QThread.currentThread() is not self.thread():
            # ★第434章: eval_js_signal 定义在 PyBridge 类（L65）而非本类——
            #   433 首版误写 self.eval_js_signal 导致 AttributeError
            #   （真机"卡片推送失败: MIMOCodePanel object has no attribute
            #   eval_js_signal"实锤）。经 self.pybridge 引用并发射，
            #   QueuedConnection 排队回 GUI 线程的 _js_eval → _safe_run_js。
            _pb = getattr(self, 'pybridge', None)
            if _pb is not None:
                _pb.eval_js_signal.emit(js)
                return
            # pybridge 未就绪（极端时序）：退回直接入队（老行为）
        self._js_call_queue.append(js)
        if not self._js_flush_timer.isActive():
            self._js_flush_timer.start()


    # ══════════════════════════════════════════════════════════════
    # 第362章 · P4 闭环尾部 · JS 端渲染助手（全部增量注入，不改既有）
    # ══════════════════════════════════════════════════════════════

    def _js_v6p4_skill_review(self, payload: str):
        """信号 → JS：技能审核卡渲染。"""
        self._safe_run_js(
            "(function(){"
            "if(window.__v6p4RenderSkillReview){window.__v6p4RenderSkillReview(%s);}"
            "})();" % json.dumps(payload, ensure_ascii=False)
        )

    def _js_v6p4_audio_preview(self, payload: str):
        """信号 → JS：音频播放卡渲染。"""
        self._safe_run_js(
            "(function(){"
            "if(window.__v6p4RenderAudioPreview){window.__v6p4RenderAudioPreview(%s);}"
            "})();" % json.dumps(payload, ensure_ascii=False)
        )

    def _js_v6p4_market_result(self, payload: str):
        """信号 → JS：市场下载结果渲染。"""
        self._safe_run_js(
            "(function(){"
            "if(window.__v6p4RenderMarketResult){window.__v6p4RenderMarketResult(%s);}"
            "})();" % json.dumps(payload, ensure_ascii=False)
        )

    def _js_v6p4_memory_result(self, payload: str):
        """信号 → JS：记忆导出结果渲染。"""
        self._safe_run_js(
            "(function(){"
            "if(window.__v6p4RenderMemoryResult){window.__v6p4RenderMemoryResult(%s);}"
            "})();" % json.dumps(payload, ensure_ascii=False)
        )

    # —— P4 顶层注入（DOM overlay） ——
    _V6P4_OVERLAY_JS = r"""
    (function(){
        if(window.__v6p4OverlayInstalled) { return; }
        window.__v6p4OverlayInstalled = true;

        /* 0. 样式（SVG 图标，禁 emoji） */
        var style = document.createElement('style');
        style.textContent =
          '#v6p4-float-btn{position:fixed;right:12px;bottom:96px;z-index:9999;' +
          'background:linear-gradient(135deg,#00d4ff33,#ff6b9d33);' +
          'backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);' +
          'border:1px solid #ffffff22;border-radius:28px;' +
          'width:56px;height:56px;display:flex;align-items:center;justify-content:center;' +
          'box-shadow:0 6px 24px #0006;cursor:pointer;transition:transform .2s}' +
          '#v6p4-float-btn:hover{transform:scale(1.08)}' +
          '#v6p4-panel{position:fixed;right:12px;bottom:160px;z-index:9998;' +
          'background:#1a1d23ee;border:1px solid #ffffff18;border-radius:16px;' +
          'padding:18px;width:380px;max-height:60vh;overflow:auto;' +
          'box-shadow:0 12px 36px #000a;display:none;color:#eee;font-size:13px}' +
          '#v6p4-panel h3{margin:0 0 10px;' +
          'background:linear-gradient(90deg,#00d4ff,#ff6b9d);-webkit-background-clip:text;' +
          '-webkit-text-fill-color:transparent;background-clip:text;font-weight:700}' +
          '.v6p4-item{border:1px solid #ffffff15;border-radius:10px;padding:10px;' +
          'margin-bottom:8px;background:#ffffff08}' +
          '.v6p4-badge{display:inline-block;padding:2px 8px;border-radius:9px;' +
          'font-size:11px;margin-right:6px}' +
          '.v6p4-pass{background:#00ff8833;color:#7fffb0}' +
          '.v6p4-fail{background:#ff444433;color:#ff9090}' +
          '.v6p4-btn{display:inline-block;padding:5px 12px;border-radius:7px;' +
          'border:1px solid #ffffff22;margin-right:6px;cursor:pointer;font-size:12px;' +
          'background:#ffffff10;color:#eee;text-decoration:none}' +
          '.v6p4-btn:hover{background:#ffffff22}' +
          '.v6p4-audio audio{width:100%;outline:none}' +
          '.v6p4-muted{color:#888;font-size:12px}' +
          '.v6p4-thumb{width:18px;height:18px;vertical-align:middle;margin-right:6px}';
        document.head.appendChild(style);

        /* 1. 浮动按钮 + 面板 */
        var fb = document.createElement('div');
        fb.id = 'v6p4-float-btn';
        /* SVG 铃铛/拼图 入口 */
        fb.innerHTML = '<svg class="v6p4-thumb" width="26" height="26" viewBox="0 0 24 24" ' +
            'fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" ' +
            'stroke-linejoin="round">' +
            '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
            '<polyline points="14 2 14 8 20 8"/>' +
            '<path d="M9 13l2 2 4-4"/>' +
            '<circle cx="17" cy="18" r="2.5"/>' +
            '<path d="M17 15.5V14"/><path d="M17 20.5V22"/>' +
            '</svg>';
        var panel = document.createElement('div');
        panel.id = 'v6p4-panel';
        document.body.appendChild(fb);
        document.body.appendChild(panel);
        fb.addEventListener('click', function(){
            panel.style.display = (panel.style.display==='block') ? 'none' : 'block';
        });

        /* 2. 工具函数 */
        function _esc(s){ return (s===null||s===undefined)?'':String(s)
            .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

        /* —— 2.1 审核卡 —— */
        window.__v6p4RenderSkillReview = function(payload){
            panel.innerHTML = '';
            var h = document.createElement('h3');
            h.textContent = '技能审核卡 · 临时转正';
            panel.appendChild(h);
            var status = document.createElement('div');
            status.className = 'v6p4-muted';
            status.textContent = '查询时间: '+ new Date().toLocaleString();
            panel.appendChild(status);
            if(!payload || !payload.success){
                panel.innerHTML += '<div class="v6p4-muted" style="margin-top:8px">' +
                    '查询失败：' + _esc(payload && payload.error ? payload.error : '无数据') + '</div>';
                panel.style.display = 'block';
                return;
            }
            if(!payload.pending || payload.pending.length === 0){
                panel.innerHTML += '<div class="v6p4-muted" style="margin-top:12px">' +
                    '暂无待审核技能</div>';
                panel.style.display = 'block';
                return;
            }
            payload.pending.forEach(function(it){
                var d = document.createElement('div');
                d.className = 'v6p4-item';
                var gates = it.gates || {};
                var gHtml = '';
                for(var k in gates){
                    var g = gates[k];
                    gHtml += '<span class="v6p4-badge ' +
                        (g.pass ? 'v6p4-pass' : 'v6p4-fail') + '">' +
                        (g.pass ? 'PASS' : 'FAIL') + ' · ' + _esc(k) + '</span>';
                }
                d.innerHTML = '<div><b>' + _esc(it.tmp_name) + '</b>' +
                    '<span class="v6p4-muted"> · 成功 ' + it.success_count + ' 次</span></div>' +
                    '<div style="margin:6px 0">' + gHtml + '</div>' +
                    '<div>' +
                      '<a class="v6p4-btn" data-act="promote" data-name="' +
                        _esc(it.tmp_name) + '">转正</a>' +
                      '<a class="v6p4-btn" data-act="delete" data-name="' +
                        _esc(it.tmp_name) + '">删除</a>' +
                    '</div>';
                panel.appendChild(d);
            });
            panel.querySelectorAll('[data-act="promote"]').forEach(function(a){
                a.addEventListener('click', function(){
                    var n = a.getAttribute('data-name');
                    var formal = n.replace(/^tmp_/, '');
                    window.mimerBridge.call('v6p4_promote_skill', JSON.stringify([n, formal]),
                        function(r){ window.__v6p4RenderSkillReview(JSON.parse(r)); });
                });
            });
            panel.querySelectorAll('[data-act="delete"]').forEach(function(a){
                a.addEventListener('click', function(){
                    var n = a.getAttribute('data-name');
                    window.mimerBridge.call('v6p4_delete_pending_skill', JSON.stringify([n]),
                        function(r){ window.__v6p4RenderSkillReview(JSON.parse(r)); });
                });
            });
            panel.style.display = 'block';
        };

        /* —— 2.2 音频卡 —— */
        window.__v6p4RenderAudioPreview = function(payload){
            document.getElementById('v6p4-panel').style.display = 'block';
            panel.innerHTML = '';
            var h = document.createElement('h3');
            h.textContent = '音频播放卡';
            panel.appendChild(h);
            if(!payload || !payload.success){
                panel.innerHTML += '<div class="v6p4-muted">音频列表加载失败：' +
                    _esc(payload && payload.error ? payload.error : '未知') + '</div>';
                return;
            }
            if(!payload.files || payload.files.length === 0){
                panel.innerHTML += '<div class="v6p4-muted">outputs/ 下暂无 .wav/.mp3</div>';
                return;
            }
            var wrap = document.createElement('div');
            wrap.className = 'v6p4-audio';
            payload.files.forEach(function(fp){
                var row = document.createElement('div');
                row.className = 'v6p4-item';
                row.innerHTML = '<div style="font-size:12px;word-break:break-all;margin-bottom:4px">' +
                    _esc(fp) + '</div>';
                var audio = document.createElement('audio');
                audio.controls = true;
                audio.preload = 'none';
                audio.style.width = '100%';
                audio.src = 'file:///' + fp.replace(/\\/g,'/');
                audio.addEventListener('error', function(){
                    var msg = document.createElement('div');
                    msg.style.cssText='color:#ff9090;margin-top:4px;font-size:12px';
                    msg.textContent = '音频加载失败：无法解码或文件不存在（路径: ' + fp + '）';
                    row.appendChild(msg);
                });
                row.appendChild(audio);
                wrap.appendChild(row);
            });
            panel.appendChild(wrap);
        };

        /* —— 2.3 市场结果 —— */
        window.__v6p4RenderMarketResult = function(payload){
            document.getElementById('v6p4-panel').style.display = 'block';
            panel.innerHTML = '';
            var h = document.createElement('h3');
            h.textContent = '技能市场下载';
            panel.appendChild(h);
            if(!payload || !payload.success){
                panel.innerHTML += '<div class="v6p4-badge v6p4-fail" style="display:inline-block">' +
                    '</div><span style="margin-left:8px">' +
                    _esc(payload && payload.error ? payload.error : '失败') + '</span>';
                return;
            }
            var d = payload.data || {};
            var gates = d.gates || {};
            var gHtml = '';
            for(var k in gates){
                var g = gates[k];
                gHtml += '<span class="v6p4-badge ' +
                    (g.pass ? 'v6p4-pass' : 'v6p4-fail') + '">' +
                    (g.pass ? 'PASS' : 'FAIL') + ' · ' + _esc(k) + '</span>';
            }
            panel.innerHTML += '<div class="v6p4-item"><b>' + _esc(d.name || '?') + '</b>' +
                (d.registered ? '<span class="v6p4-badge v6p4-pass" style="margin-left:8px">已注册</span>'
                               : '<span class="v6p4-badge v6p4-fail" style="margin-left:8px">未注册</span>') +
                '<div style="margin:6px 0">' + gHtml + '</div>' +
                _esc(d.file || '') + '</div>';
        };

        /* —— 2.4 记忆导出结果 —— */
        window.__v6p4RenderMemoryResult = function(payload){
            document.getElementById('v6p4-panel').style.display = 'block';
            panel.innerHTML = '';
            var h = document.createElement('h3');
            h.textContent = '记忆导出';
            panel.appendChild(h);
            if(!payload || !payload.success){
                panel.innerHTML += '<div class="v6p4-muted">' +
                    _esc(payload && payload.error ? payload.error : '失败') + '</div>';
                return;
            }
            var d = payload.data || {};
            panel.innerHTML += '<div class="v6p4-item">快照: <code>' +
                _esc(d.path || '?') + '</code>' +
                '<br>节: ' + _esc(JSON.stringify(d.sections_found || [])) +
                (d.warnings ? '<br><span class="v6p4-muted">告警: ' +
                    _esc(JSON.stringify(d.warnings)) + '</span>' : '') +
                '</div>';
        };

        /* 3. 顶部按钮：触发查询 */
        var actions = [
            { label: '技能审核', fn: function(){
                window.mimerBridge.call('v6p4_skill_review_list', JSON.stringify([]),
                    function(r){ window.__v6p4RenderSkillReview(JSON.parse(r)); });
            }},
            { label: '音频卡', fn: function(){
                window.mimerBridge.call('v6p4_audio_list', JSON.stringify([]),
                    function(r){ window.__v6p4RenderAudioPreview(JSON.parse(r)); });
            }},
            { label: '记忆导出', fn: function(){
                window.mimerBridge.call('v6p4_memory_export', JSON.stringify([]),
                    function(r){ window.__v6p4RenderMemoryResult(JSON.parse(r)); });
            }}
        ];
        var row = document.createElement('div');
        row.style.cssText='display:flex;gap:6px;flex-wrap:wrap;margin-top:8px';
        actions.forEach(function(a){
            var b = document.createElement('a');
            b.className = 'v6p4-btn';
            b.textContent = a.label;
            b.addEventListener('click', a.fn);
            row.appendChild(b);
        });
        panel.appendChild(row);
        panel.style.display = 'none';
    })();
    """

    def _ensure_v6p4_overlay(self):
        """注入 P4 顶层 overlay 入口（JSON 渲染器 + 浮动按钮 + 面板）。"""
        if not getattr(self, '_js_ready', False):
            try:
                from PyQt5.QtCore import QTimer as _QTimer_P4
                _QTimer_P4.singleShot(1500, self._ensure_v6p4_overlay)
            except Exception:
                pass
            return
        self._safe_run_js(self._V6P4_OVERLAY_JS)

    def _flush_js_queue(self):
        """批量执行 JS 调用队列（节流 + 合并）

        ★ 卡顿修复（2026-08-28，第340章）— 本方法即周期性卡顿元凶：
        原实现 batch=10 / interval=150ms → 消化上限 66 条/秒，而 agent 流式
        token 产生速率 50~200 条/秒，队列无限积压 → 几百个 runJavaScript
        完成回调塞满主线程事件循环 → 鼠标点击事件饿死（"卡顿时点不动任何按钮"）。
        备份版参数 20条/50ms（400条/秒）所以不卡；中途一次"降低重绘压力"的
        优化把吞吐砍掉 6 倍，反而制造了卡顿（"越修越卡"实证）。
        修复：每次消化整个队列 + 把连续 onStreamToken 合并为单次调用
        （每秒 IPC 从上百次降到 ~7 次，打字机效果不变）。
        """
        if getattr(self, '_clean', False):
            self._js_call_queue.clear()
            self._js_flush_timer.stop()
            return
        if not self._js_call_queue:
            # ★392A-3: Agent 执行中保持定时器存活作为看门狗 tick（复用本定时器，
            #   禁新增轮询线程）；空闲时维持原行为——清队列即停表
            if getattr(self, "_agent_watchdog_active", False):
                self._check_stream_watchdog()
                return
            self._js_flush_timer.stop()
            return
        if not self._js_ready:
            # ★ JS 未就绪时原实现直接 return → 队列无限增长；加上限保护
            if len(self._js_call_queue) > 800:
                del self._js_call_queue[:400]
            return
        try:
            page = self.web_view.page()
            if page is None:
                self._js_call_queue.clear()
                self._js_flush_timer.stop()
                return
        except RuntimeError:
            self._js_call_queue.clear()
            self._js_flush_timer.stop()
            return

        # ★ 每次消化整个队列（原 batch=10 是积压根源）
        batch = self._js_call_queue
        self._js_call_queue = []

        # ★ 合并连续 onStreamToken 为单次调用（核心：IPC 次数 = flush 次数）
        #   转义后的内容可直接拼接：转义器保证每个 part 内无裸引号/悬空反斜杠
        merged = []
        tok_buf = None
        for js in batch:
            if js.startswith("onStreamToken('") and js.endswith("')"):
                part = js[len("onStreamToken('"):-2]
                tok_buf = (tok_buf + part) if tok_buf is not None else part
            else:
                if tok_buf is not None:
                    merged.append(f"onStreamToken('{tok_buf}')")
                    tok_buf = None
                merged.append(js)
        if tok_buf is not None:
            merged.append(f"onStreamToken('{tok_buf}')")
        # 上限保护：极端积压时丢最旧的（保住最新输出）
        if len(merged) > 200:
            merged = merged[-200:]

        for js in merged:
            try:
                page.runJavaScript(js)
            except Exception:
                pass
        if not self._js_call_queue:
            self._js_flush_timer.stop()

    def _js_append_message(self, html):
        js = "window.mimoAgent.appendMessage(%s);" % json.dumps(html)
        # ★ 统一使用队列机制，确保与 onStreamStart/onStreamToken/onStreamEnd 保持 FIFO 顺序
        # 之前：_js_ready 时直接 runJavaScript → appendMsg 可能先于 onStreamStart 执行
        # → _streamActive=false, _streamTargetContent=null → 创建独立消息块
        # → 随后 onStreamStart 创建第二个流式块 → 内容折叠/混乱
        self._safe_run_js(js)

    def _js_eval(self, js_code: str):
        """通用 JS 执行（供流式输出等使用）"""
        self._safe_run_js(js_code)

    # ---------------- 咩咩 Agent 真流式桥接（v4.3.8） ----------------

    def _miemie_run_agent(self, task, text):
        """启动咩咩 Agent worker，把 step/result/summary/done/token 事件桥接到 JS。

        在标准模式（mimo_panel 所在模式）里 worker 运行于独立 QThread，
        事件通过 pybridge.miemie_event_signal 逐条推送，前端实时渲染。
        """
        try:
            from ui.miemie_engine import MiemieEngineWorker
        except ImportError:
            from .miemie_engine import MiemieEngineWorker
        self._miemie_worker = MiemieEngineWorker(task, user_text=text or None, parent=self)
        # ★ v4.7.1: HITL —— 权限模式 + 确认请求转发前端（HTML 确认卡）
        self._miemie_worker.set_confirm_mode(self._miemie_permission_mode())
        self._miemie_worker.confirm_requested.connect(self._miemie_push("confirm"))
        self._miemie_worker.step_event.connect(self._miemie_push("step"))
        self._miemie_worker.result_event.connect(self._miemie_push("result"))
        self._miemie_worker.summary_event.connect(self._miemie_push("summary"))
        self._miemie_worker.done_event.connect(self._miemie_push("done"))
        self._miemie_worker.token_event.connect(self._miemie_push("token"))
        self._miemie_worker.start()

    def _miemie_push(self, evt_type):
        """返回一个 slot 工厂：把 worker 事件包装成 {type, ...} 后经 base64 推给 JS。"""
        def _slot(payload):
            import base64 as _b64
            import json as _json
            try:
                if isinstance(payload, str):
                    data = {"type": evt_type, "token": payload}
                else:
                    data = dict(payload or {})
                    data["type"] = evt_type
                # ★ v4.7.3: 本地缓存会话文本（供总指挥跨会话读取，免 JS 同步 eval）
                self._cache_miemie_event(data)
                raw = _json.dumps(data, ensure_ascii=False, default=str)
                b64 = _b64.b64encode(raw.encode("utf-8")).decode("ascii")
                self.pybridge.miemie_event_signal.emit(b64)
            except Exception:
                pass
        return _slot

    # ============================================================
    # ★ v4.7.3: 跨会话指挥 —— 总指挥(主会话咩咩)注入命令 / 读取会话输出
    # ============================================================
    def _cache_miemie_event(self, data):
        """缓存咩咩事件文本（token→对话流，step/result/summary→任务流）。

        供 get_output_text 读取；总指挥(主会话)通过 session_read 工具拿各工人
        会话的产出，实现"主窗口读窗口信息→调度"。
        """
        try:
            et = data.get("type")
            if et == "token":
                self._miemie_chat_text = (getattr(self, "_miemie_chat_text", "") or "") + (data.get("token") or "")
                self._miemie_chat_text = self._miemie_chat_text[-8000:]
            elif et == "step":
                self._miemie_flow_text = (getattr(self, "_miemie_flow_text", "") or "") + "[工具] %s\n" % (data.get("tool") or "")
                self._miemie_flow_text = self._miemie_flow_text[-8000:]
            elif et == "result" and data.get("tool") != "llm":
                r = data.get("result") or {}
                t = str(r.get("error") or r.get("result") or "")[:300] if isinstance(r, dict) else str(r)[:300]
                self._miemie_flow_text = (getattr(self, "_miemie_flow_text", "") or "") + t + "\n"
                self._miemie_flow_text = self._miemie_flow_text[-8000:]
            elif et == "summary":
                self._miemie_flow_text = (getattr(self, "_miemie_flow_text", "") or "") + "[总结] " + (data.get("text") or "")[:500] + "\n"
                self._miemie_flow_text = self._miemie_flow_text[-8000:]
        except Exception:
            pass

    def inject_user_message(self, text):
        """从总指挥会话注入一条命令，在本会话咩咩面板执行。

        HTML 端 miemiePanelInject 展开咩咩面板并提交；咩咩走本地工具链，
        不占用全局 serve 单通道，多个工人会话可真正并行。
        """
        if not text:
            return
        try:
            import json as _json
            js = "if(typeof miemiePanelInject==='function')miemiePanelInject(%s);" % _json.dumps(text)
            self._safe_run_js(js)
        except Exception as e:
            print(f"[MIEMIE] 注入命令失败: {e}")

    def get_output_text(self, max_chars=2000):
        """导出本会话最近对话+任务输出（纯文本），供总指挥读取。"""
        chat = (getattr(self, "_miemie_chat_text", "") or "").strip()
        flow = (getattr(self, "_miemie_flow_text", "") or "").strip()
        if chat or flow:
            parts = []
            if chat:
                parts.append("【对话】" + chat)
            if flow:
                parts.append("【任务流】" + flow)
            text = "\n".join(parts)
            return text[-max_chars:]
        try:
            import re
            html = self.get_output_html() or ""
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
        except Exception:
            return ""

    # ============================================================
    # ★ v4.7.1: HITL 确认卡 / 权限分层 / 人格工作区（HTML 咩咩面板）
    # ============================================================
    def _perm_cfg_path(self):
        try:
            from ui.miemie_engine import _PERSONA_PATH
        except ImportError:
            from .miemie_engine import _PERSONA_PATH
        return os.path.join(os.path.dirname(_PERSONA_PATH), "miemie_config.json")

    def _miemie_permission_mode(self):
        """读取当前权限分层（auto/confirm/debug），首次懒加载。"""
        if getattr(self, "_permission_mode", None) not in ("auto", "confirm", "debug"):
            m = "auto"
            try:
                with open(self._perm_cfg_path(), "r", encoding="utf-8") as f:
                    m = json.load(f).get("permission_mode")
            except Exception:
                pass
            self._permission_mode = m if m in ("auto", "confirm", "debug") else "auto"
        return self._permission_mode

    def _miemie_set_permission_mode(self, mode):
        """设置权限分层并持久化（与 Qt 底栏 MiemiePanel 共用 miemie_config.json）。"""
        if mode not in ("auto", "confirm", "debug"):
            return self._miemie_permission_mode()
        self._permission_mode = mode
        try:
            cfg = self._perm_cfg_path()
            d = {}
            try:
                with open(cfg, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                pass
            d["permission_mode"] = mode
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        # 运行中的 worker 立即生效
        worker = getattr(self, "_miemie_worker", None)
        if worker is not None and worker.isRunning():
            try:
                worker.set_confirm_mode(mode)
            except Exception:
                pass
        # ★ 378-5：UI 三档 → SkillsRegistry 权限三档显式映射（360.5 遗留）。
        #   此前 UI(auto/confirm/debug) 与 registry(auto/confirm/readonly) 完全断开，
        #   registry 侧永远停在默认 confirm —— debug 档传入会被静默忽略。
        #   映射：auto→auto（自动执行）、confirm→confirm（逐项确认）、
        #         debug→readonly（调试模式仅读，只放行查询/搜索类工具）。
        _REGISTRY_MODE_MAP = {"auto": "auto", "confirm": "confirm", "debug": "readonly"}
        try:
            from core.skills_registry import get_skills_registry
            get_skills_registry().set_permission_mode(_REGISTRY_MODE_MAP[mode])
        except Exception:
            pass  # registry 未就绪时静默跳过（UI 档位仍持久化，重启后生效）
        return mode

    def _miemie_confirm(self, ok, always):
        """用户点击 HTML 确认卡：回传 worker 解除阻塞（True=放行，always=本会话不再询问）。

        ★389M-7: always=1 时同步调用 grant_high_risk_tool（scope=session）——
        引擎侧确认门对同一技能本会话内静默放行；新会话创建/切换时清空。
        """
        worker = getattr(self, "_miemie_worker", None)
        if worker is not None:
            try:
                worker.set_confirm(bool(int(ok or 0)), bool(int(always or 0)))
            except Exception:
                worker.set_confirm(True, False)
        # ★ 389M-7: 会话级授权联动
        if str(always or "0") == "1" and str(ok or "0") == "1":
            try:
                from shared.engine_manager import get_engine_manager
                em = get_engine_manager()
                _tool = getattr(em.__class__, "_LAST_CONFIRM_TOOL", "")
                if _tool:
                    em.grant_high_risk_tool(_tool, approve=True)
                    # UI 状态提示（已授权角标等价物：状态行消息）
                    try:
                        self._append_output(
                            f"<span style='color:#2f9e44;'>[已授权] {_tool} 本会话内免确认"
                            f"（新会话自动失效）</span><br>")
                    except Exception:
                        pass
            except Exception as _ge:
                print(f"[389M-7] 会话级授权联动失败: {_ge}")
        return '{"ok":true}'

    def _miemie_open_persona(self):
        """打开人格工作区（v4.7.0 三栏大面板，非模态；复用现有工作区实例防 GC）。"""
        try:
            from ui.miemie_persona_workspace import PersonaWorkspace as _PW
        except ImportError:
            try:
                from .miemie_persona_workspace import PersonaWorkspace as _PW
            except Exception as e:
                print(f"[MIEMIE] 人格工作区导入失败: {e}")
                return '{"ok":false}'
        ws = getattr(self, "_persona_workspace", None)
        if ws is not None:
            try:
                ws.raise_()
                ws.activateWindow()
                return '{"ok":true}'
            except Exception:
                pass
        self._persona_workspace = _PW(self)
        self._persona_workspace.show()
        return '{"ok":true}'

    def _js_miemie_event(self, b64_payload: str):
        """把咩咩 Agent 事件 base64 传给 HTML 端 miemieOnJson()。"""
        js = "if(typeof miemieOnJson==='function')miemieOnJson(%s);" % json.dumps(b64_payload)
        self._safe_run_js(js)

    def _miemie_bleat(self):
        """★ v4.6.2: 咩咩点击互动反馈（补第 241 章 HTML 已调用、Python 端缺失的槽）。

        往主聊天区追加一条轻量互动消息；纯装饰，无副作用。
        """
        try:
            html = ('<div style="color:{Lemon.BRAND_ORANGE_LIGHT};font-size:12px;margin:2px 0 4px 0;'
                    'opacity:0.9;">咩~ 咩咩收到抚摸</div>')
            self._js_append_message(html)
        except Exception as e:
            print(f"[MIEMIE] 咩咩互动反馈失败: {e}")

    def _js_append_thinking(self, html):
        js = "window.mimoAgent.appendThinking(%s);" % json.dumps(html)
        self._safe_run_js(js)

    def _js_append_status(self, html):
        js = "window.mimoAgent.appendStatus(%s);" % json.dumps(html)
        self._safe_run_js(js)

    def _js_append_tool(self, html):
        js = "window.mimoAgent.appendTool(%s);" % json.dumps(html)
        self._safe_run_js(js)

    def _js_append_timeline(self, event_json: str):
        """★ v4.1.15: 追加一条执行轨迹事件到右侧栏 Timeline"""
        js = "window.mimoAgent.appendTimeline(%s);" % json.dumps(event_json)
        self._safe_run_js(js)

    def _js_append_steps(self, steps_json: str):
        """★ v5.1: P-C 渲染「任务步骤列表」到右侧栏顶部"""
        js = "window.mimoAgent.renderAgentSteps(%s);" % json.dumps(steps_json)
        self._safe_run_js(js)

    def _js_append_agent_status(self, status_json: str):
        """★ v5.1: P-F 渲染独立底部状态栏条（运行结束的完整 meta）"""
        js = "if(window.updateStatusBar)window.updateStatusBar(%s);" % json.dumps(status_json)
        self._safe_run_js(js)
        # ★ T367.4: 抓包 — 写入 status_event_log.csv
        try:
            _log_dir = os.path.join(os.getcwd(), "data", "perf")
            os.makedirs(_log_dir, exist_ok=True)
            _log_path = os.path.join(_log_dir, "status_event_log.csv")
            _log_size = os.path.getsize(_log_path) if os.path.exists(_log_path) else 0
            if _log_size < 2 * 1024 * 1024:
                with open(_log_path, "a", encoding="utf-8") as _f:
                    import datetime
                    _f.write(f"{datetime.datetime.now().isoformat()}|{status_json}\n")
        except Exception:
            pass

    def _js_append_preview(self, html):
        """v3.90: 文件预览（HTML iframe/图像/代码内嵌到右侧栏）"""
        js = "window.mimoAgent.appendPreview(%s);" % json.dumps(html)
        self._safe_run_js(js)

    def _js_append_user_message(self, text):
        """在右侧面板显示用户消息"""
        js = "window.mimoAgent.appendUserMessage(%s);" % json.dumps(text)
        self._safe_run_js(js)

    def _js_set_connected(self, connected):
        js = "window.mimoAgent.setConnected(%s);" % json.dumps(bool(connected))
        self._safe_run_js(js)

    def _js_set_robot_status(self, status):
        js = "window.mimoAgent.setRobotStatus(%s);" % json.dumps(status)
        self._safe_run_js(js)

    def _js_show_config_options(self, session_id, options_json):
        """显示配置选项弹窗"""
        js = "window.mimoAgent.showConfigOptions(%s, %s);" % (
            json.dumps(session_id), options_json
        )
        self._safe_run_js(js)

    def _js_show_permission(self, session_id, tool_info_json, options_json):
        """显示权限请求弹窗"""
        js = "window.mimoAgent.showPermission(%s, %s, %s);" % (
            json.dumps(session_id), tool_info_json, options_json
        )
        self._safe_run_js(js)

    def _js_set_mode(self, mode_id):
        """更新模式显示"""
        js = "window.mimoAgent.setMode(%s);" % json.dumps(mode_id)
        self._safe_run_js(js)

    def _js_show_plan(self, plan_json):
        """显示计划"""
        js = "window.mimoAgent.showPlan(%s);" % plan_json
        self._safe_run_js(js)

    def _js_show_commands(self, commands_json):
        """显示可用命令"""
        js = "window.mimoAgent.showCommands(%s);" % commands_json
        self._safe_run_js(js)

    def _js_show_usage(self, usage_json):
        """显示用量信息"""
        js = "window.mimoAgent.showUsage(%s);" % usage_json
        self._safe_run_js(js)

    def _js_set_agent_state(self, state):
        """更新机器人状态（驱动表情和建议）"""
        js = "window.mimoAgent.setAgentState(%s);" % json.dumps(state)
        self._safe_run_js(js)

    def _js_show_models(self, models_json):
        """推送模型列表到 JS"""
        js = "window.mimoAgent.showModels(%s);" % models_json
        self._safe_run_js(js)

    def _js_show_sessions(self, sessions_json):
        """推送会话列表到 JS"""
        js = "window.mimoAgent.showSessions(%s);" % sessions_json
        self._safe_run_js(js)

    def _js_set_current_model(self, model_id):
        """设置当前模型"""
        js = "window.mimoAgent.setCurrentModel(%s);" % json.dumps(model_id)
        self._safe_run_js(js)

    def _js_set_current_session(self, session_id):
        """设置当前会话"""
        js = "window.mimoAgent.setCurrentSession(%s);" % json.dumps(session_id)
        self._safe_run_js(js)

    def _js_background_task(self, task_json: str):
        """T366.1: 后台任务状态变化→前端卡片"""
        self._safe_run_js(
            f"window.TraceRenderer&&TraceRenderer.consume({task_json})"
        )

    # ★ T366.1: 后台任务提交入口
    def submit_background(self, goal: str) -> str:
        """提交后台任务，返回task_id；完成后自动推送卡片"""
        if not self._engine_manager:
            return ""
        task_id = self._engine_manager.submit_background_task(
            goal, lambda: None)
        if not task_id:
            return ""
        self._emit_trace("bg_task", status="running", task_id=task_id,
                         name=goal[:60])
        self._bg_task_ids = getattr(self, "_bg_task_ids", {})
        self._bg_task_ids[task_id] = goal[:60]
        if not getattr(self, "_bg_poll_timer", None):
            self._bg_poll_timer = QTimer()
            self._bg_poll_timer.setInterval(2000)
            self._bg_poll_timer.timeout.connect(self._poll_bg_tasks)
        if not self._bg_poll_timer.isActive():
            self._bg_poll_timer.start()
        return task_id

    def _poll_bg_tasks(self):
        """T366.1: 轮询后台任务状态，完成/失败时推送卡片"""
        if not self._engine_manager:
            return
        pending = dict(getattr(self, "_bg_task_ids", {}))
        for tid, name in list(pending.items()):
            info = self._engine_manager.get_task_status(tid)
            if not info:
                del self._bg_task_ids[tid]
                continue
            status = info.get("status", "")
            if status in ("completed", "failed"):
                result_preview = ""
                error = ""
                if status == "completed":
                    result_obj = info.get("result")
                    result_preview = str(result_obj)[:200] if result_obj else ""
                else:
                    error = str(info.get("error", ""))[:120]
                ev = {
                    "seq": (getattr(self, "_trace_seq", 0) or 0) + 1,
                    "ts": int(time.time() * 1000),
                    "kind": "bg_task",
                    "status": status,
                    "task_id": tid, "name": name,
                    "result_preview": result_preview,
                    "error": error,
                }
                self.pybridge.background_task_signal.emit(
                    json.dumps(ev, ensure_ascii=False))
                del self._bg_task_ids[tid]
        if not self._bg_task_ids:
            self._bg_poll_timer.stop()

    # ============================================================
    # 图片/文件上传处理
    # ============================================================
    def _on_image_upload(self, file_name, base64_data):
        """处理图片上传"""
        print(f"[MIMO Panel] 图片上传: {file_name}")
        # ★ v3.70: 暂存图片 base64（去掉 data:image/xxx;base64, 前缀，只保留纯 base64）
        raw_b64 = base64_data
        if ',' in raw_b64 and raw_b64.startswith('data:'):
            raw_b64 = raw_b64.split(',', 1)[1]
        self._pending_images.append({"name": file_name, "data": raw_b64})
        self.image_uploaded.emit(file_name, base64_data)

    def _on_file_upload(self, file_name, base64_data):
        """处理文件上传"""
        print(f"[MIMO Panel] 文件上传: {file_name}")
        self.file_uploaded.emit(file_name, base64_data)

    def _on_set_trust_mode(self, enabled):
        """设置信任模式（自动同意）"""
        print(f"[MIMO Panel] 信任模式: {enabled}")
        # 通过 serve_bridge 设置
        # 需要通过主窗口中转，这里先记录状态
        self._trust_mode = bool(enabled)
        # 发送信号
        if hasattr(self, 'trust_mode_changed'):
            self.trust_mode_changed.emit(self._trust_mode)
    
    def _on_save_api_key(self, args_str):
        """★ P13: 保存 API Key（从 JS 前端调用）"""
        import json, os
        try:
            data = json.loads(args_str) if isinstance(args_str, str) else args_str
            engine = data.get('engine', '')
            key = data.get('key', '')
            if not engine or not key:
                print(f"[MIMO Panel] API Key 保存失败: 缺少 engine 或 key")
                return
            
            if engine == 'deepseek':
                key_file = os.path.expanduser("~/.deepseek_key")
            elif engine == 'mimo':
                key_file = os.path.expanduser("~/.mimo_key")
            else:
                print(f"[MIMO Panel] 未知引擎: {engine}")
                return
            
            # 写入文件
            with open(key_file, 'w') as f:
                f.write(key)
            
            # 设置文件权限（仅 owner 可读写）
            try:
                os.chmod(key_file, 0o600)
            except Exception:
                pass
            
            print(f"[MIMO Panel] API Key 已保存: {engine} → {key_file}")
            
            # 同步到引擎管理器
            try:
                from core.engine_manager import get_engine_manager
                em = get_engine_manager()
                if em:
                    em.set_api_key(engine, key)
                    print(f"[MIMO Panel] API Key 已同步到引擎管理器: {engine}")
            except Exception as e:
                print(f"[MIMO Panel] 引擎管理器同步失败: {e}")
                
        except Exception as e:
            print(f"[MIMO Panel] API Key 保存异常: {e}")

    # ★ v3.72: API Format 配置保存/重置（前端 _callPython('saveApiFormat'/'resetApiFormat') 桥接）
    def _on_save_api_format(self, data):
        """保存引擎 API 格式配置"""
        try:
            if isinstance(data, str):
                data = json.loads(data)
            engine = data.get('engine', '')
            config = data.get('config', {})
            if not engine:
                return {"success": False, "message": "缺少 engine 参数"}

            # 保存到配置文件
            config_dir = os.path.expanduser("~/.lemon_code")
            os.makedirs(config_dir, exist_ok=True)
            config_file = os.path.join(config_dir, f"api_format_{engine}.json")
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            # 同步到引擎管理器
            try:
                from core.engine_manager import get_engine_manager
                em = get_engine_manager()
                if em and hasattr(em, 'set_api_format'):
                    em.set_api_format(engine, config)
            except Exception:
                pass

            print(f"[MIMO Panel] API Format 已保存: {engine}")
            return {"success": True, "engine": engine}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _on_reset_api_format(self, engine):
        """重置引擎 API 格式为默认值"""
        try:
            if isinstance(engine, str):
                try:
                    engine = json.loads(engine)
                except json.JSONDecodeError:
                    pass
            if not engine:
                return {"success": False, "message": "缺少 engine 参数"}

            # 删除配置文件
            config_file = os.path.expanduser(f"~/.lemon_code/api_format_{engine}.json")
            if os.path.exists(config_file):
                os.remove(config_file)

            # 通知引擎管理器重置
            try:
                from core.engine_manager import get_engine_manager
                em = get_engine_manager()
                if em and hasattr(em, 'reset_api_format'):
                    em.reset_api_format(engine)
            except Exception:
                pass

            print(f"[MIMO Panel] API Format 已重置: {engine}")
            return {"success": True, "engine": engine}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ============================================================
    # ★ 快照管理（供 JS 桥接调用）
    # ============================================================
    def set_serve_bridge(self, bridge):
        """设置 serve_bridge 引用"""
        self._serve_bridge = bridge

    def set_tool_confirm_callback(self, callback):
        self._tool_confirm_callback = callback
        # ★ 订阅 EventBus 事件
        try:
            import sys as _sys
            _core_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'core')
            if _core_dir not in _sys.path:
                _sys.path.insert(0, _core_dir)
            from event_bus import EventBus, EventType
            bus = EventBus.instance()

            # 订阅快照创建事件 → 通知前端有可回退的快照
            bus.subscribe(EventType.SNAPSHOT_CREATED, self._on_snapshot_created)
            # 订阅快照回退事件 → 通知前端回退完成
            bus.subscribe(EventType.SNAPSHOT_RESTORED, self._on_snapshot_restored)
            # 订阅工具事件 → 可扩展的 UI 更新
            bus.subscribe(EventType.TOOL_ERROR, self._on_tool_error_event)
            # ★ 订阅设置变更事件 → 通知前端重新加载主题/字体
            bus.subscribe(EventType.SETTINGS_CHANGED, self._on_settings_changed)
            # ★ 订阅工作区切换事件 → 通知前端更新显示
            bus.subscribe(EventType.WORKSPACE_CHANGED, self._on_workspace_changed)
            # ★ 订阅会话事件 → UI 状态更新
            bus.subscribe(EventType.SESSION_CREATED, self._on_session_created)
            bus.subscribe(EventType.SESSION_SWITCHED, self._on_session_switched)
            # ★ 订阅工具执行事件 → 状态栏显示
            bus.subscribe(EventType.TOOL_BEFORE, self._on_tool_before)
            bus.subscribe(EventType.TOOL_AFTER, self._on_tool_after)
            # ★ 订阅文件保存事件 → Git 状态刷新提示
            bus.subscribe(EventType.FILE_SAVED, self._on_file_saved)
            # ★ 订阅崩溃恢复事件 → 显示恢复提示
            bus.subscribe(EventType.CRASH_RECOVERED, self._on_crash_recovered)
            # ★ 订阅调试事件 → 调试面板 UI 更新
            bus.subscribe(EventType.DEBUG_STARTED, self._on_debug_started)
            bus.subscribe(EventType.DEBUG_STOPPED, self._on_debug_stopped)
            bus.subscribe(EventType.BREAKPOINT_HIT, self._on_breakpoint_hit)

            print("[EventBus] MIMOCodePanel 已订阅事件", flush=True)
        except Exception as e:
            print(f"[EventBus] 订阅失败: {e}", flush=True)

    # ★ EventBus 事件处理
    def _on_snapshot_created(self, data):
        """快照创建事件处理"""
        try:
            label = data.get('label', '') if isinstance(data, dict) else ''
            print(f"[EventBus] 快照已创建: {label}", flush=True)
        except Exception:
            pass

    def _on_snapshot_restored(self, data):
        """快照回退事件处理"""
        try:
            msg = data.get('message', '回退完成') if isinstance(data, dict) else '回退完成'
            self.append_status_signal.emit(
                f"<span style='color:{Lemon.ACCENT_GREEN};'>✓ {msg}</span>"
            )
        except Exception:
            pass

    def _on_tool_error_event(self, data):
        """工具错误事件处理"""
        try:
            tool = data.get('tool', 'unknown') if isinstance(data, dict) else 'unknown'
            self.append_status_signal.emit(
                f"<span style='color:{Lemon.ERROR};'>✕ 工具错误: {tool}</span>"
            )
        except Exception:
            pass

    def _on_settings_changed(self, data):
        """设置变更事件处理 → 通知前端重新加载设置"""
        try:
            # 通过 JS 重新加载设置
            self.pybridge.eval_js_signal.emit("if(typeof loadSettingsFromBackend==='function')loadSettingsFromBackend();")
        except Exception:
            pass

    def _on_workspace_changed(self, data):
        """工作区切换事件处理 → 通知前端更新"""
        try:
            ws = data.get('workspace', {}) if isinstance(data, dict) else {}
            ws_name = ws.get('name', '') if isinstance(ws, dict) else ''
            self.append_status_signal.emit(
                f"<span style='color:{Lemon.ACCENT_GREEN};'>◈ 工作区已切换: {ws_name}</span>"
            )
        except Exception:
            pass

    def _on_session_created(self, data):
        """会话创建事件处理"""
        try:
            sid = data.get('session_id', '') if isinstance(data, dict) else ''
            self.append_status_signal.emit(
                f"<span style='color:{Lemon.ACCENT_GREEN};'>✓ 新会话已创建: {sid[:16]}...</span>"
            )
        except Exception:
            pass

    def _on_session_switched(self, data):
        """会话切换事件处理"""
        try:
            new_sid = data.get('new_session_id', '') if isinstance(data, dict) else ''
            self.append_status_signal.emit(
                f"<span style='color:{Lemon.ACCENT_BLUE};'>📋 会话已切换: {new_sid[:16]}...</span>"
            )
        except Exception:
            pass

    def _on_tool_before(self, data):
        """工具执行前事件处理"""
        try:
            tool = data.get('tool', '') if isinstance(data, dict) else ''
            if tool:
                self.pybridge.eval_js_signal.emit(f"if(typeof onDebugOutput==='function')onDebugOutput('tool','执行: {tool}');")
        except Exception:
            pass

    def _on_tool_after(self, data):
        """工具执行后事件处理"""
        try:
            tool = data.get('tool', '') if isinstance(data, dict) else ''
            if tool:
                self.pybridge.eval_js_signal.emit(f"if(typeof onDebugOutput==='function')onDebugOutput('tool','完成: {tool}');")
        except Exception:
            pass

    def _on_file_saved(self, data):
        """文件保存事件处理"""
        try:
            file_path = data.get('file_path', '') if isinstance(data, dict) else ''
            if file_path:
                self.append_status_signal.emit(
                    f"<span style='color:{Lemon.ACCENT_GREEN};'>💾 文件已保存: {os.path.basename(file_path)}</span>"
                )
        except Exception:
            pass

    def _on_crash_recovered(self, data):
        """崩溃恢复事件处理"""
        try:
            error = data.get('error', '未知错误') if isinstance(data, dict) else '未知错误'
            self.append_status_signal.emit(
                f"<span style='color:{Lemon.ACCENT_ORANGE};'>▲ 已从异常恢复: {error}</span>"
            )
        except Exception:
            pass

    def _on_debug_started(self, data):
        """调试启动事件处理 → 通知前端"""
        try:
            self.pybridge.eval_js_signal.emit("if(typeof onDebugStateChanged==='function')onDebugStateChanged('running');")
        except Exception:
            pass

    def _on_debug_stopped(self, data):
        """调试停止事件处理 → 通知前端"""
        try:
            self.pybridge.eval_js_signal.emit("if(typeof onDebugTerminated==='function')onDebugTerminated();")
        except Exception:
            pass

    def _on_breakpoint_hit(self, data):
        """断点命中事件处理 → 通知前端高亮行"""
        try:
            file_path = data.get('file', '') if isinstance(data, dict) else ''
            line = data.get('line', 0) if isinstance(data, dict) else 0
            if file_path and line:
                self.pybridge.eval_js_signal.emit(
                    f"if(typeof onDebugBreakpointHit==='function')onDebugBreakpointHit('{file_path}',{line});"
                )
        except Exception:
            pass

    def _handle_snapshot(self, action: str, args: list):
        """处理 JS 发来的快照操作请求

        Args:
            action: 'list' / 'restore' / 'diff'
            args: 参数列表

        Returns:
            操作结果（dict 或 str）
        """
        if not self._serve_bridge:
            return {"success": False, "message": "serve_bridge 未初始化"}

        try:
            if action == 'list':
                snapshots = self._serve_bridge.list_snapshots()
                return snapshots
            elif action == 'restore' and len(args) > 0:
                snapshot_id = args[0]
                result = self._serve_bridge.restore_snapshot(snapshot_id)
                return result
            elif action == 'diff' and len(args) > 0:
                snapshot_id = args[0]
                diff_text = self._serve_bridge.diff_snapshot(snapshot_id)
                return diff_text
        except Exception as e:
            print(f"[Snapshot] 操作失败 ({action}): {e}")
            return {"success": False, "message": str(e)}

        return {"success": False, "message": "未知操作"}

    # ============================================================
    # ★ 消息持久化（供 JS 桥接调用）
    # ============================================================
    def _handle_message_store(self, action: str, args: list):
        """处理 JS 发来的消息存储操作请求

        Args:
            action: 'list_sessions' / 'get_messages' / 'search' / 'delete_session'
            args: 参数列表

        Returns:
            操作结果
        """
        if not self._serve_bridge:
            return {"success": False, "message": "serve_bridge 未初始化"}

        try:
            if action == 'list_sessions':
                return self._serve_bridge.list_db_sessions()
            elif action == 'get_messages' and len(args) > 0:
                session_id = args[0]
                limit = args[1] if len(args) > 1 else 100
                return self._serve_bridge.get_db_messages(session_id, limit)
            elif action == 'search' and len(args) > 0:
                keyword = args[0]
                return self._serve_bridge.search_db_messages(keyword)
            elif action == 'delete_session' and len(args) > 0:
                session_id = args[0]
                success = self._serve_bridge.delete_db_session(session_id)
                return {"success": success}
        except Exception as e:
            print(f"[MessageStore] 操作失败 ({action}): {e}")
            return {"success": False, "message": str(e)}

        return {"success": False, "message": "未知操作"}

    # ============================================================
    # ★ 工作区管理（供 JS 桥接调用）
    # ============================================================
    def _handle_workspace(self, action: str, args: list):
        """处理 JS 发来的工作区操作请求

        Args:
            action: 'list' / 'add' / 'remove' / 'switch' / 'current'
            args: 参数列表

        Returns:
            list: {"workspaces": [...], "current": {...}}
            add: {"workspace": {...}}
            remove: {"success": bool}
            switch: {"workspace": {...}, "prev_session_id": "..."}
            current: {"workspace": {...}} 或 {}
        """
        try:
            from core.workspace_manager import get_workspace_manager
            wm = get_workspace_manager()

            if action == 'list':
                return {
                    "workspaces": wm.list_workspaces(),
                    "current": wm.get_current_workspace(),
                }

            elif action == 'add' and len(args) >= 1:
                path = args[0]
                name = args[1] if len(args) > 1 else ""
                entry = wm.add_workspace(path, name)
                print(f"[Workspace] 添加工作区: {entry.get('name')} -> {entry.get('path')}")
                return {"workspace": entry, "workspaces": wm.list_workspaces()}

            elif action == 'remove' and len(args) >= 1:
                ws_id = args[0]
                ok = wm.remove_workspace(ws_id)
                print(f"[Workspace] 移除工作区 {ws_id}: {'成功' if ok else '失败'}")
                return {"success": ok, "workspaces": wm.list_workspaces()}

            elif action == 'switch' and len(args) >= 1:
                ws_id = args[0]
                result = wm.switch_workspace(ws_id)
                ws_path = result["workspace"].get("path", "")
                print(f"[Workspace] 切换到: {result['workspace'].get('name')} -> {ws_path}")
                # 通知主窗口更新 explorer/git/terminal
                if ws_path:
                    self.workspace_switch_requested.emit(ws_path)
                return result

            elif action == 'current':
                ws = wm.get_current_workspace()
                return {"workspace": ws} if ws else {}

        except Exception as e:
            print(f"[Workspace] 操作失败 ({action}): {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "message": str(e)}

        return {"success": False, "message": "未知操作"}

    # ============================================================
    # ★ 调试管理（供 JS 桥接调用）
    # ============================================================
    def _handle_debug(self, action: str, args: list):
        """处理 JS 发来的调试操作请求

        Args:
            action: 'start'/'stop'/'continue'/'pause'/'step'/'variables'/
                    'stacktrace'/'evaluate'/'set_breakpoint'/'toggle_breakpoint'/
                    'remove_breakpoint'/'get_breakpoints'/'get_state'
            args: 参数列表

        Returns:
            dict: 操作结果
        """
        try:
            from core.debug_session import get_debug_manager
            dm = get_debug_manager()

            if action == 'start':
                # args: [program, (可选)cwd, (可选)args_list]
                program = args[0] if args else ""
                cwd = args[1] if len(args) > 1 else ""
                prog_args = args[2] if len(args) > 2 else []
                if not program:
                    return {"success": False, "message": "未指定程序路径"}
                result = dm.start_debug(program, prog_args, cwd)
                return result

            elif action == 'stop':
                ok = dm.stop_debug()
                return {"success": ok}

            elif action == 'continue':
                ok = dm.continue_execution()
                return {"success": ok}

            elif action == 'pause':
                ok = dm.pause_execution()
                return {"success": ok}

            elif action == 'step':
                # args: [step_type]  step_type: 'over'/'into'/'out'
                step_type = args[0] if args else 'over'
                if step_type == 'over':
                    ok = dm.step_over()
                elif step_type == 'into':
                    ok = dm.step_into()
                elif step_type == 'out':
                    ok = dm.step_out()
                else:
                    return {"success": False, "message": f"未知步进类型: {step_type}"}
                return {"success": ok}

            elif action == 'variables':
                scope = args[0] if args else 'local'
                vars_list = dm.get_variables(scope)
                return {"variables": vars_list}

            elif action == 'stacktrace':
                frames = dm.get_stack_trace()
                return {"frames": frames}

            elif action == 'evaluate':
                expr = args[0] if args else ""
                if not expr:
                    return {"success": False, "message": "表达式为空"}
                result = dm.evaluate_expression(expr)
                return {"result": result}

            elif action == 'set_breakpoint':
                # args: [file, line, (可选)condition]
                file = args[0]
                line = args[1]
                condition = args[2] if len(args) > 2 else None
                s = dm.active_session
                if s:
                    bp = s.add_breakpoint(file, line, condition)
                    return {"success": True, "breakpoint": {"file": file, "line": line, "id": bp.id}}
                return {"success": False, "message": "无活动调试会话"}

            elif action == 'toggle_breakpoint':
                # args: [file, line]
                file = args[0]
                line = args[1]
                s = dm.active_session
                if s:
                    added = s.toggle_breakpoint(file, line)
                    return {"success": True, "added": added, "file": file, "line": line}
                return {"success": False, "message": "无活动调试会话"}

            elif action == 'remove_breakpoint':
                # args: [file, line]
                file = args[0]
                line = args[1]
                s = dm.active_session
                if s:
                    ok = s.remove_breakpoint(file, line)
                    return {"success": ok}
                return {"success": False, "message": "无活动调试会话"}

            elif action == 'get_breakpoints':
                bps = dm.get_all_breakpoints()
                return {"breakpoints": bps}

            elif action == 'get_state':
                state = dm.get_state()
                return {"state": state}

        except Exception as e:
            print(f"[Debug] 操作失败 ({action}): {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "message": str(e)}

        return {"success": False, "message": "未知操作"}

    # ============================================================
    # ★ 设置管理（供 JS 桥接调用）
    # ============================================================
    def _handle_settings(self, action: str, args: list):
        """处理 JS 发来的设置操作请求

        Args:
            action: 'load' / 'save'
            args: 参数列表（save 时 args[0] 为 settings JSON 字符串）

        Returns:
            load: settings dict
            save: {"success": bool}
        """
        try:
            from core.settings_manager import get_settings_manager
            sm = get_settings_manager()

            if action == 'load':
                settings = sm.get_all()
                print(f"[Settings] 加载设置: theme={settings.get('appearance',{}).get('theme','?')}")
                return settings

            elif action == 'save' and len(args) > 0:
                settings = json.loads(args[0]) if isinstance(args[0], str) else args[0]
                sm.set_all(settings, auto_save=True)
                print(f"[Settings] 保存设置: theme={settings.get('appearance',{}).get('theme','?')}")
                return {"success": True}

        except Exception as e:
            print(f"[Settings] 操作失败 ({action}): {e}")
            if action == 'load':
                # 返回默认设置
                from core.settings_manager import DEFAULT_SETTINGS
                return DEFAULT_SETTINGS
            return {"success": False, "message": str(e)}

        return {"success": False, "message": "未知操作"}

    # ============================================================
    # ★ 插件市场管理（供 JS 桥接调用）
    # ============================================================
    def _handle_plugin(self, action: str, args: list):
        """处理 JS 发来的插件市场操作请求

        Args:
            action: 'list' / 'detail' / 'install' / 'uninstall' / 'enable' / 'disable'
                    / 'reload' / 'search' / 'get_config' / 'set_config' / 'config_schema'
                    / 'categories' / 'summary' / 'execute_tool'
            args: 参数列表

        Returns:
            操作结果（dict）
        """
        try:
            from core.plugin_market import get_plugin_market
            from core.plugin_system import get_plugin_manager
            # 确保单例已初始化
            pm = get_plugin_manager()
            market = get_plugin_market(pm)

            if action == 'list':
                category = args[0] if args else ""
                return {"ok": True, "plugins": market.list_plugins(category=category)}

            elif action == 'detail' and args:
                detail = market.get_plugin_detail(args[0])
                if detail is None:
                    return {"ok": False, "error": f"未找到插件: {args[0]}"}
                return {"ok": True, "detail": detail}

            elif action == 'install' and args:
                return market.install(args[0])

            elif action == 'uninstall' and args:
                return market.uninstall(args[0])

            elif action == 'enable' and args:
                return market.enable(args[0])

            elif action == 'disable' and args:
                return market.disable(args[0])

            elif action == 'reload' and args:
                return market.reload(args[0])

            elif action == 'search' and args:
                return {"ok": True, "plugins": market.search(args[0])}

            elif action == 'get_config' and args:
                return {"ok": True, "config": market.get_config(args[0])}

            elif action == 'set_config' and len(args) >= 2:
                config = json.loads(args[1]) if isinstance(args[1], str) else args[1]
                return market.set_config(args[0], config)

            elif action == 'config_schema' and args:
                return {"ok": True, "schema": market.get_config_schema(args[0])}

            elif action == 'categories':
                return {"ok": True, "categories": market.list_categories()}

            elif action == 'summary':
                return {"ok": True, "summary": market.get_summary()}

            elif action == 'execute_tool' and args:
                # args[0] = tool_name, args[1] = kwargs (JSON string or dict)
                tool_name = args[0]
                kwargs = {}
                if len(args) >= 2:
                    kwargs = json.loads(args[1]) if isinstance(args[1], str) else args[1]
                result = pm.execute_tool(tool_name, **kwargs)
                # 确保 result 可 JSON 序列化
                if isinstance(result, (dict, list, str, int, float, bool, type(None))):
                    return {"ok": True, "result": result}
                else:
                    return {"ok": True, "result": str(result)}

            else:
                return {"ok": False, "error": f"未知操作: {action}"}

        except Exception as e:
            print(f"[Plugin] 操作失败 ({action}): {e}")
            import traceback
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    # ============================================================
    # ★ Skills 技能管理（供 JS 桥接调用）
    # ============================================================
    @staticmethod
    def load_skill_health():
        """★ 369-3: 扫描最新 skill_test_report_*.json，返回精简映射 {name: {status, duration, error}}"""
        import glob as _glob
        try:
            _data_dir = os.path.join(os.getcwd(), "data")
            _pattern = os.path.join(_data_dir, "skill_test_report_*.json")
            _files = sorted(_glob.glob(_pattern))
            if not _files:
                return {}
            _latest = _files[-1]
            with open(_latest, "r", encoding="utf-8") as _f:
                _report = json.load(_f)
            _health = {}
            for _entry in _report.get("phaseC", []):
                _name = _entry.get("name", "")
                if _name:
                    _health[_name] = {
                        "status": _entry.get("status", "SKIP"),
                        "duration": _entry.get("duration_sec", 0),
                        "error": (_entry.get("error", "") or "")[:120],
                    }
            for _entry in _report.get("phaseB", {}).get("details", []):
                _name = _entry.get("module", "")
                if _name and _name not in _health and not _entry.get("registered", True):
                    _health[_name] = {"status": "SKIP", "duration": 0, "error": "未注册"}
            return _health
        except Exception:
            return {}

    def _handle_skills(self, action: str, args: list):
        """处理 JS 发来的 Skills 操作请求

        Args:
            action: 'list' / 'detail' / 'execute' / 'categories' / 'search'
            args: 参数列表

        Returns:
            操作结果（dict）
        """
        try:
            from core.skills_registry import get_skills_registry
            registry = get_skills_registry()

            if action == 'list':
                # 获取所有 Skills 列表
                category = args[0] if args else ""
                manifest = registry.export_manifest()
                skills_list = manifest.get("skills", [])
                
                # 如果指定了分类，则过滤
                if category:
                    skills_list = [s for s in skills_list if s.get("category") == category]
                
                print(f"[Skills] 列出 {len(skills_list)} 个技能")
                # ★ 369-3: 附带技能健康度数据
                _health = self.load_skill_health()
                return {
                    "ok": True,
                    "skills": skills_list,
                    "total": len(skills_list),
                    "categories": manifest.get("categories", {}),
                    "health": _health,
                }

            elif action == 'detail' and args:
                # 获取单个 Skill 的详细信息
                skill_name = args[0]
                skill = registry.get(skill_name)
                if skill is None:
                    return {"ok": False, "error": f"未找到技能: {skill_name}"}
                
                detail = {
                    "name": skill.name,
                    "description": skill.description,
                    "category": skill.category,
                    "parameters": skill.parameters,
                    "requires_confirm": skill.requires_confirm,
                    "timeout": skill.timeout
                }
                print(f"[Skills] 获取详情: {skill_name}")
                return {"ok": True, "detail": detail}

            elif action == 'execute' and len(args) >= 1:
                # 执行指定的 Skill
                skill_name = args[0]
                params = {}
                if len(args) >= 2:
                    # 参数可以是 JSON 字符串或字典
                    params = json.loads(args[1]) if isinstance(args[1], str) else args[1]
                
                print(f"[Skills] 执行: {skill_name}, 参数: {params}")
                result = registry.execute(skill_name, params)
                
                return {
                    "ok": result.success,
                    "output": result.output,
                    "error": result.error,
                    "data": result.data
                }

            elif action == 'categories':
                # 获取所有分类
                manifest = registry.export_manifest()
                categories = manifest.get("categories", {})
                print(f"[Skills] 列出 {len(categories)} 个分类")
                return {"ok": True, "categories": categories}

            elif action == 'search' and args:
                # 搜索 Skills
                query = args[0].lower()
                manifest = registry.export_manifest()
                skills_list = manifest.get("skills", [])
                
                # 简单的关键词匹配
                matched = []
                for skill in skills_list:
                    if query in skill.get("name", "").lower() or \
                       query in skill.get("description", "").lower() or \
                       query in skill.get("category", "").lower():
                        matched.append(skill)
                
                print(f"[Skills] 搜索 '{query}': 找到 {len(matched)} 个结果")
                return {"ok": True, "skills": matched, "total": len(matched)}

            else:
                return {"ok": False, "error": f"未知操作: {action}"}

        except Exception as e:
            print(f"[Skills] 操作失败 ({action}): {e}")
            import traceback
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    # ============================================================
    # ★ 自动更新检查（供 JS 桥接调用）
    # ============================================================
    def _handle_updater(self, action: str, args: list):
        """处理 JS 发来的更新检查操作请求

        Args:
            action: 'check' / 'version_info' / 'history' / 'download' /
                    'install' / 'rollback' / 'dismiss'
            args: 参数列表

        Returns:
            操作结果（dict）
        """
        try:
            from core.updater import get_update_checker, initialize_updater
            checker = get_update_checker()
            # 确保已初始化
            if not hasattr(checker, '_version_data') or not checker._version_data:
                initialize_updater()

            if action == 'check':
                force = bool(args[0]) if args else False
                result = checker.check_for_updates(force=force)
                return {"ok": True, "result": result}

            elif action == 'version_info':
                return {"ok": True, "info": checker.get_version_info()}

            elif action == 'history':
                return {"ok": True, "history": checker.get_update_history()}

            elif action == 'download' and args:
                version = args[0]
                download_url = args[1] if len(args) > 1 else ""
                result = checker.download_update(version, download_url)
                return result

            elif action == 'install' and args:
                package_path = args[0]
                incremental = bool(args[1]) if len(args) > 1 else True
                result = checker.install_update(package_path, incremental=incremental)
                return result

            elif action == 'rollback':
                snapshot_id = args[0] if args else ""
                result = checker.rollback_update(snapshot_id)
                return result

            elif action == 'dismiss':
                checker.dismiss_update_notification()
                return {"ok": True, "dismissed": True}

            else:
                return {"ok": False, "error": f"未知操作: {action}"}

        except Exception as e:
            print(f"[Updater] 操作失败 ({action}): {e}")
            import traceback
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    # ============================================================
    # ★ Ollama 管理（供 JS 桥接调用）
    # ============================================================
    def _handle_ollama(self, action: str, args: list):
        """处理 JS 发来的 Ollama 操作请求

        Args:
            action: 'status' / 'models' / 'recommend' / 'model_info'
            args: 参数列表

        Returns:
            操作结果
        """
        if not self._serve_bridge:
            return {"success": False, "message": "serve_bridge 未初始化"}

        try:
            if action == 'status':
                return self._serve_bridge.get_ollama_status()
            elif action == 'models':
                return self._serve_bridge.get_ollama_models()
            elif action == 'recommend' and len(args) > 0:
                task_type = args[0]
                return self._serve_bridge.recommend_ollama_model(task_type)
            elif action == 'model_info' and len(args) > 0:
                model_name = args[0]
                return self._serve_bridge.get_ollama_model_info(model_name)
        except Exception as e:
            print(f"[Ollama] 操作失败 ({action}): {e}")
            return {"success": False, "message": str(e)}

        return {"success": False, "message": "未知操作"}

    # ============================================================
    # ★ v4.2.4: MIEMIE 咩咩模式（风格分析 + 工作流注入）
    # ============================================================
    def _handle_miemie(self, action: str, args: list):
        """处理 JS 发来的咩咩操作请求（风格分析 / 状态 / 注入上下文）

        Args:
            action: 'analyze' / 'status' / 'inject'
            args: 参数列表

        Returns:
            操作结果（{success, profile?, injected?}）
        """
        try:
            if action == 'analyze':
                return self._miemie_analyze_project()
            elif action == 'status':
                return {
                    "success": True,
                    "analyzed": bool(getattr(self, "_miemie_profile", None)),
                    "injected": bool(getattr(self, "_miemie_injected", False)),
                    "summary": (getattr(self, "_miemie_profile", None) or {}).get("summary", ""),
                }
            elif action == 'inject':
                return {"success": True, "inject_text": self._miemie_inject_text()}
        except Exception as e:
            print(f"[MIEMIE] 咩咩操作失败 ({action}): {e}")
            return {"success": False, "error": str(e)}
        return {"success": False, "error": "未知操作"}

    def _miemie_analyze_project(self):
        """分析当前项目风格，生成咩咩风格画像，并缓存注入文本。

        复用 miemie/code_clone.py 的 CodeCloneAnalyzer（Phase1 骨架已含）。
        目录优先取 self.project_path（默认 cwd），失败回退 lemon_agent 自身。
        """
        try:
            # 惰性导入，避免启动时加载
            from miemie.code_clone import CodeCloneAnalyzer
        except Exception as e:
            print(f"[MIEMIE] CodeCloneAnalyzer 导入失败: {e}")
            return {"success": False, "error": f"CodeCloneAnalyzer 不可用: {e}"}

        target_dir = getattr(self, "project_path", None) or os.getcwd()
        if not os.path.isdir(target_dir):
            target_dir = os.getcwd()

        try:
            analyzer = CodeCloneAnalyzer()
            profile = analyzer.analyze_directory(target_dir, pattern="*.py", max_files=120)
        except Exception as e:
            # 回退：分析 lemon_agent 自身代码风格
            print(f"[MIEMIE] 分析 {target_dir} 失败，回退项目目录: {e}")
            try:
                analyzer = CodeCloneAnalyzer()
                profile = analyzer.analyze_directory(_lemon_root, pattern="*.py", max_files=120)
            except Exception as e2:
                return {"success": False, "error": f"分析失败: {e2}"}

        pd = profile.to_dict() if hasattr(profile, "to_dict") else profile
        # 缓存画像 + 生成注入文本
        self._miemie_profile = pd
        self._miemie_injected = False
        self._miemie_summary = pd.get("summary", "")
        # 组装注入文本（风格指导，供任务执行时附加）
        inject_parts = []
        if pd.get("summary"):
            inject_parts.append(f"项目风格: {pd['summary']}")
        tags = pd.get("tags") or []
        if tags:
            inject_parts.append("风格标签: " + ", ".join(tags[:8]))
        naming = pd.get("naming") or {}
        if naming.get("dominant"):
            inject_parts.append(f"命名偏好: {naming['dominant']}")
        indent = pd.get("indentation") or {}
        if indent.get("style"):
            inject_parts.append(f"缩进: {indent['style']}")
        self._miemie_inject_text_value = "；".join(inject_parts) if inject_parts else ""
        self._miemie_injected = True

        # 把 profile 展平成前端 5 维分数（雷达图用）
        front = {
            "naming": self._clamp_score(pd.get("naming") or {}, "consistency"),
            "indent": self._clamp_score(pd.get("indentation") or {}, "consistency"),
            "comments": self._clamp_score(pd.get("comments") or {}, "ratio"),
            "func_len": self._clamp_score(pd.get("function_length") or {}, "length"),
            "patterns": self._clamp_score(pd.get("design_patterns") or {}, "count"),
        }
        return {
            "success": True,
            "injected": True,
            "profile": {
                "naming": front["naming"],
                "indent": front["indent"],
                "comments": front["comments"],
                "func_len": front["func_len"],
                "patterns": front["patterns"],
                "tags": tags,
                "summary": pd.get("summary", ""),
                "naming_style": (pd.get("naming") or {}).get("dominant", "-"),
                "indent": (pd.get("indentation") or {}).get("style", "-"),
                "line_ending": (pd.get("indentation") or {}).get("line_ending", "-"),
                "avg_function_length": (pd.get("function_length") or {}).get("avg", "-"),
            },
        }

    @staticmethod
    def _clamp_score(d: dict, key: str, default: float = 5.0) -> float:
        """把画像指标映射到 0-10 前端雷达图分数（粗略启发式）。"""
        try:
            v = d.get(key)
            if v is None:
                return default
            if isinstance(v, (int, float)):
                return max(0.0, min(10.0, float(v)))
            # 字符串/百分比：提取数字
            import re as _re
            m = _re.search(r"(\d+(?:\.\d+)?)", str(v))
            if m:
                return max(0.0, min(10.0, float(m.group(1))))
            return default
        except Exception:
            return default

    def _miemie_inject_text(self) -> str:
        """返回咩咩风格注入文本（空串表示未分析）。"""
        return getattr(self, "_miemie_inject_text_value", "")

    # ============================================================
    # ★ 代码格式化 + 审查（供 JS 桥接调用）
    # ============================================================
    def _handle_code_skill(self, action: str, args: list):
        """处理 JS 发来的代码技能操作请求

        Args:
            action: 'review_code' / 'review_file' / 'format_code' / 'format_file'
            args: 参数列表

        Returns:
            操作结果
        """
        if not self._serve_bridge:
            return {"success": False, "message": "serve_bridge 未初始化"}

        try:
            if action == 'review_code' and len(args) > 0:
                code = args[0]
                language = args[1] if len(args) > 1 else "python"
                return self._serve_bridge.review_code(code, language)
            elif action == 'review_file' and len(args) > 0:
                return self._serve_bridge.review_file(args[0])
            elif action == 'format_code' and len(args) > 0:
                code = args[0]
                language = args[1] if len(args) > 1 else "python"
                return self._serve_bridge.format_code(code, language)
            elif action == 'format_file' and len(args) > 0:
                return self._serve_bridge.format_file(args[0])
        except Exception as e:
            print(f"[CodeSkill] 操作失败 ({action}): {e}")
            return {"success": False, "message": str(e)}

        return {"success": False, "message": "未知操作"}

    # ============================================================
    # ★ 代码执行器（环境执行器）
    # ============================================================
    def _handle_run_code(self, code: str, lang: str):
        """执行代码块（沙盒环境）

        Args:
            code: 代码内容
            lang: 语言类型（python/js/c/cpp等）

        Returns:
            {"output": "执行输出", "error": None} 或 {"output": None, "error": "错误信息"}
        """
        import subprocess
        import tempfile
        import os
        import shutil

        try:
            # ★ 扩展语言映射（支持C/C++/Java/Go/Rust等编译型语言）
            ext_map = {
                'python': '.py', 'py': '.py',
                'javascript': '.js', 'js': '.js', 'node': '.js',
                'typescript': '.ts', 'ts': '.ts',
                'bash': '.sh', 'sh': '.sh', 'shell': '.sh',
                'cmd': '.bat', 'powershell': '.ps1', 'ps1': '.ps1',
                'c': '.c', 'cpp': '.cpp', 'c++': '.cpp', 'cc': '.cpp',
                'java': '.java',
                'go': '.go',
                'rust': '.rs', 'rs': '.rs',
                'ruby': '.rb', 'rb': '.rb',
                'php': '.php',
                'perl': '.pl', 'pl': '.pl',
                'lua': '.lua',
                'r': '.r', 'R': '.R',
                'sql': '.sql',
                'html': '.html', 'htm': '.html',
                'css': '.css',
                'json': '.json',
                'xml': '.xml',
                'yaml': '.yaml', 'yml': '.yml',
            }
            ext = ext_map.get(lang.lower(), '.txt')

            # ★ 编译型语言处理
            lang_lower = lang.lower()
            
            # ========== C语言编译执行 ==========
            if lang_lower == 'c':
                # 检查gcc是否可用
                if not shutil.which('gcc'):
                    return {"output": None, "error": "未安装GCC编译器，无法执行C代码\n请安装: https://jmeubank.github.io/tdm-gcc/"}
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False, encoding='utf-8') as f:
                    f.write(code)
                    temp_c = f.name
                
                temp_exe = temp_c[:-2] + '.exe'  # Windows下生成exe
                try:
                    # 编译
                    compile_result = subprocess.run(
                        ['gcc', '-o', temp_exe, temp_c, '-Wall'],
                        capture_output=True, text=True, timeout=10
                    )
                    if compile_result.returncode != 0:
                        return {"output": None, "error": f"编译失败:\n{compile_result.stderr}"}
                    
                    # 执行
                    result = subprocess.run(
                        [temp_exe],
                        capture_output=True, text=True, timeout=5,
                        cwd=os.path.dirname(temp_exe)
                    )
                    
                    # 清理
                    for p in [temp_c, temp_exe]:
                        try: os.unlink(p)
                        except OSError: pass
                    
                    if result.returncode == 0:
                        return {"output": result.stdout.strip() or "(无输出)", "error": None}
                    else:
                        return {"output": None, "error": result.stderr.strip() or f"执行失败 (退出码: {result.returncode})"}
                        
                except subprocess.TimeoutExpired:
                    for p in [temp_c, temp_exe]:
                        try: os.unlink(p)
                        except OSError: pass
                    return {"output": None, "error": "编译或执行超时"}
            
            # ========== C++编译执行 ==========
            elif lang_lower in ('cpp', 'c++', 'cc'):
                if not shutil.which('g++'):
                    return {"output": None, "error": "未安装G++编译器，无法执行C++代码\n请安装: https://jmeubank.github.io/tdm-gcc/"}
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.cpp', delete=False, encoding='utf-8') as f:
                    f.write(code)
                    temp_cpp = f.name
                
                temp_exe = temp_cpp[:-4] + '.exe'
                try:
                    compile_result = subprocess.run(
                        ['g++', '-o', temp_exe, temp_cpp, '-Wall', '-std=c++17'],
                        capture_output=True, text=True, timeout=15
                    )
                    if compile_result.returncode != 0:
                        return {"output": None, "error": f"编译失败:\n{compile_result.stderr}"}
                    
                    result = subprocess.run(
                        [temp_exe],
                        capture_output=True, text=True, timeout=5,
                        cwd=os.path.dirname(temp_exe)
                    )
                    
                    for p in [temp_cpp, temp_exe]:
                        try: os.unlink(p)
                        except OSError: pass
                    
                    if result.returncode == 0:
                        return {"output": result.stdout.strip() or "(无输出)", "error": None}
                    else:
                        return {"output": None, "error": result.stderr.strip() or f"执行失败 (退出码: {result.returncode})"}
                        
                except subprocess.TimeoutExpired:
                    for p in [temp_cpp, temp_exe]:
                        try: os.unlink(p)
                        except OSError: pass
                    return {"output": None, "error": "编译或执行超时"}
            
            # ========== Java编译执行 ==========
            elif lang_lower == 'java':
                if not shutil.which('javac'):
                    return {"output": None, "error": "未安装JDK，无法执行Java代码"}
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.java', delete=False, encoding='utf-8') as f:
                    f.write(code)
                    temp_java = f.name
                
                temp_dir = os.path.dirname(temp_java)
                try:
                    compile_result = subprocess.run(
                        ['javac', temp_java],
                        capture_output=True, text=True, timeout=15,
                        cwd=temp_dir
                    )
                    if compile_result.returncode != 0:
                        return {"output": None, "error": f"编译失败:\n{compile_result.stderr}"}
                    
                    # 提取类名
                    class_match = __import__('re').search(r'public\s+class\s+(\w+)', code)
                    class_name = class_match.group(1) if class_match else 'Main'
                    
                    result = subprocess.run(
                        ['java', '-cp', temp_dir, class_name],
                        capture_output=True, text=True, timeout=5
                    )
                    
                    # 清理
                    try: os.unlink(temp_java)
                    except OSError: pass
                    for f in os.listdir(temp_dir):
                        if f.endswith('.class'):
                            try: os.unlink(os.path.join(temp_dir, f))
                            except OSError: pass
                    
                    if result.returncode == 0:
                        return {"output": result.stdout.strip() or "(无输出)", "error": None}
                    else:
                        return {"output": None, "error": result.stderr.strip() or f"执行失败"}
                        
                except subprocess.TimeoutExpired:
                    return {"output": None, "error": "编译或执行超时"}
            
            # ========== Go编译执行 ==========
            elif lang_lower == 'go':
                if not shutil.which('go'):
                    return {"output": None, "error": "未安装Go，无法执行Go代码\n请安装: https://go.dev/dl/"}
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.go', delete=False, encoding='utf-8') as f:
                    f.write(code)
                    temp_go = f.name
                
                temp_exe = temp_go[:-3] + '.exe'
                try:
                    compile_result = subprocess.run(
                        ['go', 'build', '-o', temp_exe, temp_go],
                        capture_output=True, text=True, timeout=15
                    )
                    if compile_result.returncode != 0:
                        return {"output": None, "error": f"编译失败:\n{compile_result.stderr}"}
                    
                    result = subprocess.run(
                        [temp_exe],
                        capture_output=True, text=True, timeout=5
                    )
                    
                    for p in [temp_go, temp_exe]:
                        try: os.unlink(p)
                        except OSError: pass
                    
                    if result.returncode == 0:
                        return {"output": result.stdout.strip() or "(无输出)", "error": None}
                    else:
                        return {"output": None, "error": result.stderr.strip()}
                        
                except subprocess.TimeoutExpired:
                    return {"output": None, "error": "编译或执行超时"}
            
            # ========== HTML预览（返回特殊标记） ==========
            elif lang_lower in ('html', 'htm'):
                # 返回HTML预览标记，前端将渲染
                import base64
                encoded = base64.b64encode(code.encode('utf-8')).decode('ascii')
                return {
                    "output": f"__HTML_PREVIEW__:{encoded}",
                    "error": None,
                    "is_html_preview": True
                }
            
            # ========== TypeScript编译执行 ==========
            elif lang_lower in ('typescript', 'ts'):
                if not shutil.which('npx'):
                    return {"output": None, "error": "未安装Node.js/npx，无法执行TypeScript"}
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.ts', delete=False, encoding='utf-8') as f:
                    f.write(code)
                    temp_ts = f.name
                
                temp_js = temp_ts[:-3] + '.js'
                try:
                    # 使用ts-node直接执行
                    result = subprocess.run(
                        ['npx', 'ts-node', temp_ts],
                        capture_output=True, text=True, timeout=10
                    )
                    
                    try: os.unlink(temp_ts)
                    except OSError: pass
                    
                    if result.returncode == 0:
                        return {"output": result.stdout.strip() or "(无输出)", "error": None}
                    else:
                        return {"output": None, "error": result.stderr.strip()}
                        
                except subprocess.TimeoutExpired:
                    try: os.unlink(temp_ts)
                    except OSError: pass
                    return {"output": None, "error": "执行超时"}
            
            # ========== 解释型语言 ==========
            else:
                with tempfile.NamedTemporaryFile(mode='w', suffix=ext, delete=False, encoding='utf-8') as f:
                    f.write(code)
                    temp_path = f.name

                # 选择执行器
                if lang_lower in ('python', 'py'):
                    cmd = ['python', temp_path]
                elif lang_lower in ('javascript', 'js', 'node'):
                    cmd = ['node', temp_path]
                elif lang_lower in ('bash', 'sh', 'shell'):
                    cmd = ['bash', temp_path]
                elif lang_lower in ('cmd'):
                    cmd = ['cmd', '/c', temp_path]
                elif lang_lower in ('powershell', 'ps1'):
                    cmd = ['powershell', '-ExecutionPolicy', 'Bypass', '-File', temp_path]
                elif lang_lower in ('ruby', 'rb'):
                    cmd = ['ruby', temp_path]
                elif lang_lower in ('php'):
                    cmd = ['php', temp_path]
                elif lang_lower in ('perl', 'pl'):
                    cmd = ['perl', temp_path]
                elif lang_lower in ('lua'):
                    cmd = ['lua', temp_path]
                elif lang_lower in ('r'):
                    cmd = ['Rscript', temp_path]
                else:
                    return {"output": None, "error": f"不支持的语言: {lang}\n支持的语言: Python, JavaScript, TypeScript, C, C++, Java, Go, Bash, PowerShell, Ruby, PHP, Perl, Lua, R, HTML"}

                # 执行（限制超时5秒）
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=os.path.dirname(temp_path)
                )

                # 清理临时文件
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

                if result.returncode == 0:
                    output = result.stdout.strip() if result.stdout else ''
                    if result.stderr:
                        output += '\n[警告] ' + result.stderr.strip()
                    return {"output": output or "(无输出)", "error": None}
                else:
                    return {"output": None, "error": result.stderr.strip() or f"执行失败 (退出码: {result.returncode})"}

        except subprocess.TimeoutExpired:
            return {"output": None, "error": "执行超时（超过限制时间）"}
        except FileNotFoundError as e:
            return {"output": None, "error": f"找不到执行器: {str(e)}\n请确保已安装对应的运行环境"}
        except Exception as e:
            return {"output": None, "error": f"执行异常: {str(e)}"}

    # ============================================================
    # 图表渲染
    # ============================================================
    def render_chart(self, container_id: str, chart_config: dict):
        """在指定容器中渲染图表
        
        Args:
            container_id: 容器ID
            chart_config: Chart.js 配置字典
                示例:
                {
                    "type": "bar",  // bar, line, pie, doughnut, radar, polarArea
                    "data": {
                        "labels": ["一月", "二月", "三月"],
                        "datasets": [{
                            "label": "销量",
                            "data": [65, 59, 80],
                            "backgroundColor": "rgba(255,105,0,0.3)",
                            "borderColor": "{Lemon.BRAND_ORANGE}",
                            "borderWidth": 2
                        }]
                    },
                    "options": {
                        "responsive": true,
                        "plugins": {
                            "legend": { "position": "top" }
                        }
                    }
                }
        """
        js = "if(window.mimoAgent && window.mimoAgent.renderChart) { window.mimoAgent.renderChart(%s, %s); }" % (
            json.dumps(container_id),
            json.dumps(chart_config, ensure_ascii=False)
        )
        self._safe_run_js(js)

    def render_dot_plot(self, container_id: str, config: dict):
        """打点式坐标图形渲染（用无数小点绘制数学函数图像）
        
        Args:
            container_id: 容器ID
            config: 配置字典
                {
                    "title": "正弦函数图像",
                    "function": "Math.sin(x)",  // JS 函数表达式
                    "xMin": -10,
                    "xMax": 10,
                    "yMin": -2,
                    "yMax": 2,
                    "dotCount": 3000,        // 点的数量
                    "dotColor": "{Lemon.BRAND_ORANGE}",   // 点的颜色
                    "dotSize": 1.5           // 点的大小
                }
        """
        js = "if(window.mimoAgent && window.mimoAgent.renderDotPlot) { window.mimoAgent.renderDotPlot(%s, %s); }" % (
            json.dumps(container_id),
            json.dumps(config, ensure_ascii=False)
        )
        self._safe_run_js(js)

    def render_function_cards(self, container_id: str, functions: list):
        """函数图像卡片展示（卡片式布局，带公式和属性）
        
        Args:
            container_id: 容器ID
            functions: 函数列表
                [
                    {
                        "title": "正弦函数 y = sin(x)",
                        "formula": "y = sin(x)",
                        "function": "Math.sin(x)",
                        "color": "{Lemon.BRAND_ORANGE}",
                        "lineColor": "{Lemon.BRAND_ORANGE}",
                        "xMin": -6.28, "xMax": 6.28,
                        "yMin": -1.5, "yMax": 1.5,
                        "properties": [
                            {"label": "周期", "value": "2π"},
                            {"label": "值域", "value": "[-1, 1]"},
                            {"label": "奇偶性", "value": "奇函数"}
                        ]
                    },
                    ...
                ]
        """
        js = "if(window.mimoAgent && window.mimoAgent.renderFunctionCards) { window.mimoAgent.renderFunctionCards(%s, %s); }" % (
            json.dumps(container_id),
            json.dumps({"functions": functions}, ensure_ascii=False)
        )
        self._safe_run_js(js)

    def render_matrix(self, container_id: str, config: dict):
        """矩阵可视化
        
        Args:
            container_id: 容器ID
            config: 配置字典
                {
                    "title": "矩阵 A",
                    "matrix": [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
                    "properties": [
                        {"label": "行列式", "value": "det(A) = 0"},
                        {"label": "秩", "value": "rank(A) = 2"}
                    ]
                }
        """
        js = "if(window.mimoAgent && window.mimoAgent.renderMatrix) { window.mimoAgent.renderMatrix(%s, %s); }" % (
            json.dumps(container_id),
            json.dumps(config, ensure_ascii=False)
        )
        self._safe_run_js(js)

    def render_sequence(self, container_id: str, config: dict):
        """数列可视化
        
        Args:
            container_id: 容器ID
            config: 配置字典
                {
                    "title": "等差数列",
                    "formula": "aₙ = a₁ + (n-1)d",
                    "terms": [2, 4, 6, 8, 10, 12, 14],
                    "properties": [
                        {"label": "首项", "value": "a₁ = 2"},
                        {"label": "公差", "value": "d = 2"},
                        {"label": "通项", "value": "aₙ = 2n"}
                    ]
                }
        """
        js = "if(window.mimoAgent && window.mimoAgent.renderSequence) { window.mimoAgent.renderSequence(%s, %s); }" % (
            json.dumps(container_id),
            json.dumps(config, ensure_ascii=False)
        )
        self._safe_run_js(js)

    def show_task_plan(self, tasks: list, title: str = "任务计划"):
        """显示Trae风格的任务计划卡片
        
        Args:
            tasks: 任务列表
                [
                    {"content": "优化文件图标", "status": "completed"},
                    {"content": "修复行号对齐", "status": "in_progress"},
                    {"content": "添加图表渲染", "status": "pending"}
                ]
            title: 标题
        """
        # 用特殊标记包装，让前端智能渲染器识别
        html = '<pre><code class="language-task-plan">'
        html += json.dumps({"tasks": tasks, "title": title}, ensure_ascii=False)
        html += '</code></pre>'
        self.append_message(html)

    def show_file_diff(self, files: list):
        """显示Trae风格的文件变更diff卡片
        
        Args:
            files: 文件列表
                [
                    {
                        "path": "ui/theme.py",
                        "status": "modified",  # modified/added/deleted/renamed
                        "additions": 42,
                        "deletions": 4,
                        "diff": "+ line1\n- line2\n..."
                    },
                    ...
                ]
        """
        html = '<pre><code class="language-file-diff">'
        html += json.dumps({"files": files}, ensure_ascii=False)
        html += '</code></pre>'
        self.append_message(html)

    # ============================================================
    # ★ 引擎管理器集成（Engine Manager Integration）
    # ============================================================
    def set_engine_manager(self, engine_manager):
        """设置引擎管理器引用（由 main_window 调用）"""
        self._engine_manager = engine_manager
        if engine_manager is None:
            return

        # ★ v3.51: 注入到模式管理器
        self._mode_manager.set_engine_manager(engine_manager)

        # 连接引擎管理器信号 → 前端
        engine_manager.token_received.connect(self._on_engine_token)
        engine_manager.message_complete.connect(self._on_engine_message)
        engine_manager.thinking_received.connect(self._on_engine_thinking)
        engine_manager.tool_call_received.connect(self._on_engine_tool_call)
        engine_manager.error_occurred.connect(self._on_engine_error)
        engine_manager.engine_changed.connect(self._on_engine_changed)
        engine_manager.model_list_updated.connect(self._on_engine_models_updated)

        # 初始化引擎后刷新模型列表
        print(f"[MIMO Panel] 引擎管理器已连接")

        # ★第404章 ActionCard：注册 ui_action_card 技能 + 注入渲染回调（失败非致命）
        try:
            self.setup_action_cards()
        except Exception as e:
            print(f"[MIMO Panel] ActionCard 初始化失败（非致命）: {e}")

    # ★第404章 ActionCard 动态操作卡 ==============================
    def setup_action_cards(self):
        """注册 ui_action_card 技能到 SkillsRegistry，注入渲染回调（幂等）"""
        # ★第411章: 模块别名归一（双保险）——先于任何注册，确保
        # skills_builtin 的注册与 skill_router 的菜单读取同一个单例
        import sys as _sys
        if "skills_registry" not in _sys.modules:
            try:
                from standard_mode.core import skills_registry as _sr_mod
                _sys.modules["skills_registry"] = _sr_mod
            except ImportError:
                pass
        from shared.skills_builtin.action_card_skill import register_action_card_skill
        register_action_card_skill(ui_callback=lambda js: self._safe_run_js(js))
        # ★第405章 AI Banking：mock 银行技能包双注册（技能+ActionCard 动作）
        from shared.skills_builtin.bank_skills import register_bank_skills
        print(f"[MIMO Panel] AI Banking 技能包: {register_bank_skills(ui_callback=lambda js: self._safe_run_js(js))}")
        # ★第408章 网页预览卡：web_preview 技能（对话内显示，用户选型）
        from shared.skills_builtin.web_skills import register_web_skills
        print(f"[MIMO Panel] 网页预览: {register_web_skills(ui_callback=lambda js: self._safe_run_js(js))}")
        # ★第416章 图表卡/表单卡：ui_chart_card + ui_form_card（卡片家族扩展）
        from shared.skills_builtin.ui_cards_skill import register_ui_cards
        print(f"[MIMO Panel] 图表/表单卡: {register_ui_cards(ui_callback=lambda js: self._safe_run_js(js))}")
        # ★第420章 remote_bank：Agent 以 HTTP 服务形态对接独立数字银行沙箱（:8090）
        # ★ Lemon Work 修复: 之前漏传 ui_callback → remote_bank_console 永远报
        #   "UI 回调未注入（面板未就绪）"，银行 LIVE 实时卡（页面抓取）弹不出来。
        from shared.skills_builtin.remote_bank_skills import register_remote_bank_skills
        print(f"[MIMO Panel] 远程数字银行: {register_remote_bank_skills(ui_callback=lambda js: self._safe_run_js(js))}")
        print(f"[MIMO Panel] ActionCard 技能已注册（ui_action_card / list_actions）")

    def _on_action_card_click(self, payload_json: str):
        """前端按钮点击 → 白名单分派 → 结果就地回传到卡片（★第415章 状态机）"""
        import json as _json
        from shared.action_cards import get_action_card_registry
        payload = _json.loads(payload_json)
        result = get_action_card_registry().dispatch(
            payload.get("action", ""), payload.get("params") or {},
            confirmed=bool(payload.get("confirmed")))
        # ★第415章: 回传 card_id——前端按它定位卡片，结果插入卡片内部结果区
        js = "if(window.actionCardResult)window.actionCardResult(%s, %s);" % (
            _json.dumps(result, ensure_ascii=False),
            _json.dumps(payload.get("card_id", ""), ensure_ascii=False),)
        self._safe_run_js(js)
    # ★第404章 ActionCard 区块结束 ===============================

    # ★ P2 引擎无关化：懒构建引擎无关调度器（SmartDispatcher）接入运行时
    def _ensure_smart_dispatcher(self):
        """惰性构建并缓存 SmartDispatcher（基于本面板的 EngineManager）。"""
        if getattr(self, "_smart_dispatcher", None) is not None:
            return self._smart_dispatcher
        em = getattr(self, "_engine_manager", None)
        if em is None:
            self._smart_dispatcher = None
            return None
        try:
            try:
                from core.smart_dispatcher import SmartDispatcher
            except ImportError:
                from standard_mode.core.smart_dispatcher import SmartDispatcher
            self._smart_dispatcher = SmartDispatcher.from_engine_provider(
                em,
                names=["deepseek", "ollama", "mimocode"],
                preferred_order=["deepseek", "ollama", "mimocode"],
            )
        except Exception as e:
            print(f"[MIMO Panel] SmartDispatcher 构建失败: {e}")
            self._smart_dispatcher = None
        return self._smart_dispatcher

    def get_smart_dispatcher(self):
        """返回引擎无关调度器（供诊断命令 / 上层调用；未构建时返回 None）。"""
        return self._ensure_smart_dispatcher()

    def _on_engine_token(self, token: str):
        """引擎流式 token 转发到前端（实时显示 + 累积到缓冲区）"""
        # ★ 第349章: Agent 运行期间门控旧流式 token（内容经 TraceRenderer 呈现）
        if getattr(self, "_trace_v2", False) and getattr(self, "_current_agent_worker", None) is not None:
            return
        print(f"[Engine] ✓ 收到 token: '{token[:50]}...'")
        self._engine_stream_buffer += token
        # 实时流式显示到前端
        safe = token.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '')
        self._safe_run_js(f"onStreamToken('{safe}')")

    def _on_engine_message(self, msg: str):
        """引擎完整消息 → markdown→HTML 转换 → 替换流式内容"""
        # ★ v4.8: 清除工具调用JSON流（防止JSON作为文本渲染到UI）
        if msg == "__clear_stream__":
            self._engine_stream_buffer = ""
            self._safe_run_js("clearStreamBlock()")
            return
        # ★ v4.8: 流开始标记
        if msg == "__stream_start__":
            return
        # ★ 第349章: Agent 运行期间门控 — 内容经 TraceRenderer 时间线呈现，
        #   旧流式块在此期间渲染会把全文重复铺到容器下方（成果被淹没的根因）
        if getattr(self, "_trace_v2", False) and getattr(self, "_current_agent_worker", None) is not None:
            return
        print(f"[Engine] ✓ 收到完整消息: '{msg[:100]}...'")
        full_text = self._engine_stream_buffer.strip()
        self._engine_stream_buffer = ""  # 重置缓冲区
        
        if not full_text and msg:
            full_text = msg
        
        if not full_text:
            print(f"[Engine] ⚠ 消息为空，调用 onStreamEnd('')")
            self._safe_run_js("onStreamEnd('')")
            return
        
        # ★ 品牌文本替换
        full_text = self._replace_brand_in_text(full_text)
        
        # ★ Markdown → HTML 转换（复用 serve_bridge 的完整处理管道）
        try:
            from core.serve_bridge import markdown_to_html
            html = markdown_to_html(full_text)
        except Exception as e:
            print(f"[Engine] markdown_to_html 失败: {e}")
            html = full_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # ★ 发送 HTML 到前端，替换流式块内容
        safe_html = html.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '')
        self._safe_run_js(f"replaceStreamBlockHTML('{safe_html}')")

    def _replace_brand_in_text(self, text: str) -> str:
        """品牌文本替换（只替换产品名，不替换底层模型名）

        ★ v4.1.10: 增加 Claude Code 错误自称的防御性替换。
        """
        import re
        # 防御：底层模型幻觉自称 Claude Code / Lemon Code 时，纠正为 Lemon Work 身份
        # ★ v355: 应用已改名 Lemon Work —— 渲染层兜底同步改名
        text = re.sub(
            r'(?:I\s+am|我是)\s+Claude\s*Code[，,。. ]*(?:by\s+Xiaomi\s*MiMo\s*Team|由\s*小米?\s*MiMo\s*团队开发)?',
            '我是 Lemon Work，你的智能工作助手', text, flags=re.IGNORECASE)
        text = re.sub(r'我是\s*Lemon\s*Code(?:\s*Agent)?', '我是 Lemon Work', text, flags=re.IGNORECASE)
        text = re.sub(r'Lemon\s*Code(?:\s*Agent)?(?:，|,)?\s*(?:由|by)\s*Xiaomi', 'Lemon Work', text, flags=re.IGNORECASE)
        text = re.sub(r'MiMo\s*Code\s*Agent', 'Lemon Work Agent', text, flags=re.IGNORECASE)
        text = re.sub(r'MiMo\s*Code', 'Lemon Work', text, flags=re.IGNORECASE)
        text = re.sub(r'mimocode', 'Lemon Work', text, flags=re.IGNORECASE)
        text = re.sub(r'小米\s*MiMo', '柠檬 Lemon', text)
        text = re.sub(r'小米', '柠檬', text)
        return text

    def _on_engine_thinking(self, text: str):
        """引擎思考过程转发到前端"""
        safe = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        self.pybridge.append_thinking_signal.emit(f"<span style='color:#888;'>{safe}</span>")

    def _on_engine_tool_call(self, tool_json: str):
        """引擎工具调用转发到前端"""
        self.pybridge.append_tool_signal.emit(
            f"<span style='color:{Lemon.BRAND_ORANGE_LIGHT};'><svg width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round' style='vertical-align:-2px'><path d='M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z'/></svg> 工具调用: {tool_json}</span>"
        )

    def _on_engine_error(self, error: str):
        """引擎错误转发到前端"""
        self.pybridge.append_status_signal.emit(
            f"<span style='color:{Lemon.ERROR};'>✕ 引擎错误: {error}</span>"
        )

    def _on_engine_changed(self, engine_id: str):
        """引擎切换通知前端"""
        self._safe_run_js(f"onEngineSwitched('{engine_id}')")

    def _on_engine_models_updated(self, models_json: str):
        """模型列表更新通知前端"""
        self._safe_run_js(f"onEngineModelsUpdated({models_json})")

    # ============================================================
    # ★ 引擎操作处理（供 JS 桥接调用）
    # ============================================================
    def _handle_engine(self, action: str, args: list):
        """处理 JS 发来的引擎操作请求

        ★ 卡顿修复（2026-08-28）: status/models 是高频前端轮询，底层
        is_available()/list_models() 每次都发同步 HTTP（timeout=3~5s），
        且本方法在主线程执行（QWebChannel 回调）——服务繁忙时直接冻结 UI。
        运行日志实锤：14:29:15 同 1 秒内 6 次 /api/tags 同步请求。
        现在对 status/models 加 10s TTL 缓存；切换引擎/模型/刷新时失效。
        """
        # ★ 调试日志
        print(f"[Engine] _handle_engine called: action={action}, args={args}, _engine_manager={self._engine_manager}")

        if self._engine_manager is None:
            print("[Engine] 引擎管理器未初始化！")
            return {"success": False, "message": "引擎管理器未初始化"}

        # ★ TTL 缓存（仅 status/models 两类只读查询）
        _TTL = 10.0
        cache = getattr(self, "_engine_query_cache", None)
        if cache is None:
            cache = self._engine_query_cache = {}
        cache_key = None
        if action == "status":
            cache_key = "status"
        elif action == "models" and args:
            cache_key = f"models:{args[0]}"
        if cache_key:
            hit = cache.get(cache_key)
            if hit and (time.time() - hit[0]) < _TTL:
                return hit[1]

        try:
            if action == 'switch' and len(args) > 0:
                engine_id = args[0]
                # ★ 检查引擎是否存在
                available_engines = list(self._engine_manager._engines.keys())
                print(f"[Engine] 可用引擎: {available_engines}")

                ok = self._engine_manager.switch_engine(engine_id)
                if ok:
                    print(f"[Engine] 切换成功，当前引擎: {self._engine_manager.get_active_engine_id()}")
                else:
                    print(f"[Engine] 切换失败！")
                if ok:
                    cache.clear()  # 引擎切换 → 状态已变，失效缓存
                return {"success": ok, "message": f"切换到 {engine_id}" if ok else "切换失败"}

            elif action == 'status':
                status = self._engine_manager.get_status()
                result = {"success": True, "status": status}
                if cache_key:
                    cache[cache_key] = (time.time(), result)
                return result

            elif action == 'models' and len(args) > 0:
                engine_id = args[0]
                models = self._engine_manager.get_models(engine_id)
                # ★ v4.1.13: EngineManager 的适配器 list_models() 返回 List[str]，
                # 但新模型面板期望 {id,name} 对象列表。在这里统一归一化，避免前端
                # updateModelPanelOptions 读 m.name 时得到 undefined。
                normalized = []
                for m in models:
                    if isinstance(m, str):
                        normalized.append({"id": m, "name": m})
                    elif isinstance(m, dict) and 'id' in m:
                        normalized.append(m)
                result = {"success": True, "models": normalized, "engine_id": engine_id}
                if cache_key:
                    cache[cache_key] = (time.time(), result)
                return result

            elif action == 'set_model' and len(args) >= 2:
                engine_id, model_id = args[0], args[1]
                self._engine_manager.set_model(engine_id, model_id)
                cache.clear()  # 模型变更 → 失效缓存
                return {"success": True, "message": f"模型已切换: {model_id}"}

            # ★ v4.1.14: 暴露当前真实活动引擎+模型给前端，替代 mimo-auto 占位符
            elif action == 'get_current_model':
                info = self._engine_manager.get_current_model()
                return {"success": True, **info}

            # ★ v4.1.17: Worktree 隔离 — Agent 在独立分支/目录跑，主工作区零污染
            elif action == 'worktree' and len(args) > 0:
                sub = args[0]
                result = self._handle_worktree_action(sub, args[1:])
                return result

            elif action == 'refresh_models':
                self._engine_manager.refresh_models()
                cache.clear()  # 显式刷新 → 失效缓存
                return {"success": True, "message": "模型列表已刷新"}

            elif action == 'hybrid' and len(args) > 0:
                enabled = bool(args[0])
                self._engine_manager.set_hybrid_mode(enabled)
                return {"success": True, "message": f"混合模式: {'启用' if enabled else '禁用'}"}

            elif action == 'execute_skill' and len(args) >= 2:
                skill_name = args[0]
                skill_args = args[1] if len(args) > 1 else {}
                if isinstance(skill_args, str):
                    skill_args = json.loads(skill_args)
                result = self._engine_manager.execute_skill(skill_name, skill_args)
                return {"success": True, "result": result}

            elif action == 'set_api_key' and len(args) >= 2:
                engine_id = args[0]
                api_key = args[1]
                self._engine_manager.set_api_key(engine_id, api_key)
                return {"success": True, "message": f"API Key 已设置"}

        except Exception as e:
            print(f"[Engine] 操作失败 ({action}): {e}")
            return {"success": False, "message": str(e)}

        return {"success": False, "message": "未知操作"}

    # ★ P7: Skill 调用处理
    def _handle_skill_invoke(self, skill_id: str):
        """处理来自前端的 Skill 调用请求
        
        执行指定 Skill，将结果通过 JS 回调发送到前端渲染。
        """
        import traceback
        print(f"[Skill] 收到调用请求: {skill_id}")
        
        try:
            # 通过 EngineManager 执行 Skill
            if self._engine_manager is None:
                self._safe_run_js(f"onSkillComplete('{skill_id}', false, '引擎管理器未初始化')")
                return
            
            # 调用 execute_skill
            result = self._engine_manager.execute_skill(skill_id, {})
            
            # 将结果序列化为 JSON 发送到前端
            if isinstance(result, dict):
                result_json = json.dumps(result, ensure_ascii=False, default=str)
            elif isinstance(result, str):
                result_json = json.dumps({"result": result}, ensure_ascii=False)
            else:
                result_json = json.dumps({"result": str(result)}, ensure_ascii=False)
            
            # 发送结果到前端渲染
            js_call = f"onSkillComplete('{skill_id}', true, {result_json})"
            self._safe_run_js(js_call)
            print(f"[Skill] {skill_id} 执行成功")
            
        except Exception as e:
            error_msg = str(e)
            traceback.print_exc()
            print(f"[Skill] {skill_id} 执行失败: {error_msg}")
            self._safe_run_js(f"onSkillComplete('{skill_id}', false, '{error_msg}')")

    def send_to_engine(self, prompt: str, context: list = None, force_ollama: bool = False):
        """发送消息到当前引擎
        
        ★ v3.51: 集成 EngineModeManager
        - MIMO 模式：走 command_sent → serve_bridge，失败报错不切换
        - Ollama 模式：走 EngineManager.send_message()，失败报错不切换
        - 自动模式：mimocode 优先，不可用时自动回退到 ollama
        """
        print(f"[Engine] _engine_manager = {self._engine_manager}")
        
        # ★ v4.1.10: 身份类问题本地拦截（优先于引擎发送）
        if self._try_local_identity_answer(prompt):
            return
        
        if self._engine_manager is None:
            print("[Engine] 引擎管理器未初始化，使用 serve_bridge 发送")
            if not prompt.startswith('__'):
                self.command_sent.emit(prompt)
            return
        
        # ★ v3.51: 根据模式管理器决定路由
        target_engine = self._mode_manager.get_target_engine()
        current_mode = self._mode_manager.mode_name
        print(f"[Engine] 当前模式: {current_mode}, 目标引擎: {target_engine}")

        if target_engine == "mimocode" and not force_ollama:
            # ★ v3.58: MIMO 模式下直接尝试 stdio 通信
            print(f"[Engine] 使用 MIMO 引擎，尝试 stdio 通信")
            
            # 检查 serve_bridge 是否可用
            if self._serve_bridge and self._serve_bridge.is_connected:
                print(f"[Engine] Serve Bridge 已连接，通过 serve_bridge 发送")
                if not prompt.startswith('__'):
                    self.command_sent.emit(prompt)
            else:
                # serve_bridge 不可用，尝试 stdio
                print(f"[Engine] Serve Bridge 未连接，尝试 stdio 通信")
                if self._serve_bridge:
                    # 尝试 stdio 模式
                    self._serve_bridge.communication_mode = "stdio"
                    success = self._serve_bridge.send_message(prompt)
                    if success:
                        print(f"[Engine] stdio 发送成功")
                    else:
                        print(f"[Engine] stdio 发送失败，显示错误")
                        self.on_output(
                            "<span style= f'color:{Lemon.ACCENT_RED};'>⚠️ MIMO Code 服务不可用。请检查 mimo.exe 是否启动。</span>"
                        )
                else:
                    self.on_output(
                        "<span style= f'color:{Lemon.ACCENT_RED};'>⚠️ MIMO Code 服务不可用。请启动 mimo.exe。</span>"
                    )
        else:
            # ollama/deepseek 走 EngineManager 信号链
            # 用 _sync_only 标志防止 _on_user_send 重复发送到 serve_bridge
            print(f"[Engine] 使用 {target_engine} 引擎，通过 EngineManager 发送")
            if not prompt.startswith('__'):
                self._sync_only = True
                self.command_sent.emit(prompt)
            self._send_via_ollama(prompt)
    
    def _on_mode_changed(self, mode: EngineMode):
        """★ v3.51: 引擎模式变化回调
        ★ v3.57: 添加 MIMO 状态监控 + 首次启动引导
        ★ P6: 添加 DeepSeek 模式处理 + MIMO 引擎切换修复
        """
        mode_name = mode.value
        print(f"[Engine] 模式切换到: {mode_name}")
        target = self._mode_manager.get_target_engine()
        
        # ★ P6 修复: 所有模式统一切换 EngineManager 的活动引擎
        if self._engine_manager:
            if target == "mimocode":
                self._engine_manager.switch_engine("mimocode")
            elif target == "ollama":
                self._engine_manager.switch_engine("ollama")
            elif target == "deepseek":
                self._engine_manager.switch_engine("deepseek")
        
        # 通知前端显示当前模式
        if target == "mimocode":
            self._safe_run_js(f"if(typeof onEngineSwitched==='function')onEngineSwitched('mimocode')")
            # ★ v3.57: 启动 MIMO 状态监控（30秒定时检查）
            self._start_mimo_monitor()
            # ★ v3.57: 首次选择 MIMO 模式时立即检查状态
            if self._mimo_first_attempt:
                self._mimo_first_attempt = False
                # 延迟检查，并在检查完成后判断是否需要显示引导
                QTimer.singleShot(500, self._check_and_guide_mimo)
        elif target == "ollama":
            self._safe_run_js(f"if(typeof onEngineSwitched==='function')onEngineSwitched('ollama')")
            # ★ v3.57: 停止 MIMO 状态监控（Ollama 模式不需要）
            self._stop_mimo_monitor()
        elif target == "deepseek":
            self._safe_run_js(f"if(typeof onEngineSwitched==='function')onEngineSwitched('deepseek')")
            # ★ P6: DeepSeek 模式也停止 MIMO 监控
            self._stop_mimo_monitor()
        else:
            # 自动模式
            self._safe_run_js(f"if(typeof onEngineSwitched==='function')onEngineSwitched('auto')")
            # ★ v3.57: 自动模式下也启动监控（用于自动切换判断）
            self._start_mimo_monitor()
        
        # ★ v3.51 修复：删除不存在的 append_status_signal，改为打印日志
        print(f"[Engine] 引擎模式已切换到: {mode_name.upper()}, 目标引擎: {target}")

    # ================================================================
    # ★ v3.65: 显示模式 + 二次处理服务（夺舍模式专用）
    # ================================================================
    def set_display_only_mode(self, enabled: bool, agent_name: str = "外部 Agent"):
        """★ v3.65: 切换右栏显示模式

        原生 Agent 模式（enabled=False）：
            - 输入框可用，用户可发送消息
            - 正常显示 Agent 输出
        夺舍模式（enabled=True）：
            - 输入框禁用（用户不能直接发送，由外部 Agent 驱动）
            - 显示"显示模式(二次处理)"状态横幅
            - 紫色边框指示
            - 拦截的外部 Agent 输出经二次处理后显示
        """
        try:
            self._display_only_mode = enabled
            self._intercept_agent_name = agent_name

            if enabled:
                # 启用显示模式
                # 1. 禁用输入框
                self._safe_run_js("""
                    if (typeof inputField !== 'undefined' && inputField) {
                        inputField.disabled = true;
                        inputField.placeholder = '显示模式：由 %s 驱动，不可直接输入';
                    }
                    if (typeof sendButton !== 'undefined' && sendButton) {
                        sendButton.disabled = true;
                        sendButton.style.opacity = '0.4';
                    }
                """.replace("%s", agent_name.replace("'", "\\'")))

                # 2. 注入显示模式状态横幅（紫色）
                self._safe_run_js("""
                    if (!document.getElementById('displayModeBanner')) {
                        var banner = document.createElement('div');
                        banner.id = 'displayModeBanner';
                        banner.style.cssText = 'background:{Lemon.ACCENT_PURPLE};color:#fff;padding:6px 12px;font-size:12px;font-weight:600;text-align:center;position:sticky;top:0;z-index:100;';
                        banner.innerHTML = '▲ 显示模式 · %s 输出（二次处理已启用）';
                        var container = document.querySelector('.chat-container') || document.body;
                        container.insertBefore(banner, container.firstChild);
                    }
                """.replace("%s", agent_name.replace("'", "\\'")))

                # 3. 添加紫色边框
                self._safe_run_js("""
                    if (typeof document.body !== 'undefined') {
                        document.body.style.borderTop = '2px solid {Lemon.ACCENT_PURPLE}';
                    }
                """)

                print(f"[MIMOCodePanel] 显示模式已启用，拦截 {agent_name}")
            else:
                # 恢复正常模式
                self._safe_run_js("""
                    if (typeof inputField !== 'undefined' && inputField) {
                        inputField.disabled = false;
                        inputField.placeholder = '输入消息...';
                    }
                    if (typeof sendButton !== 'undefined' && sendButton) {
                        sendButton.disabled = false;
                        sendButton.style.opacity = '1';
                    }
                    var banner = document.getElementById('displayModeBanner');
                    if (banner) banner.remove();
                    if (typeof document.body !== 'undefined') {
                        document.body.style.borderTop = '';
                    }
                """)
                print(f"[MIMOCodePanel] 显示模式已禁用，恢复正常输出")
        except Exception as e:
            print(f"[MIMOCodePanel] set_display_only_mode 失败: {e}")

    def is_display_only_mode(self) -> bool:
        """★ v3.65: 是否处于显示模式"""
        return getattr(self, '_display_only_mode', False)

    def process_intercepted_content(self, text: str, source: str = "agent") -> str:
        """★ v3.65: 二次处理服务 — 对拦截的外部 Agent 输出做格式化/增强

        处理规则：
        - agent: 保留原文，添加"【%s 回复】"前缀
        - tool: 添加工具调用可视化边框
        - thinking: 添加紫色斜体样式
        - status: 添加绿色状态标签
        - 自动检测代码块并添加语法高亮标记

        Args:
            text: 拦截的原始文本
            source: 来源类型

        Returns:
            处理后的 HTML 字符串
        """
        try:
            import html as html_lib
            escaped = html_lib.escape(text)

            if source == "agent":
                # Agent 回复：添加前缀和样式
                return f'<div style="margin:8px 0;padding:10px;background:Lemon.DARK_MID_5;border-left:3px solid {Lemon.ACCENT_BLUE};border-radius:4px;"><span style="color:{Lemon.ACCENT_BLUE};font-size:11px;font-weight:600;">【{self._intercept_agent_name} 回复】</span><div style="margin-top:6px;color:{Lemon.DIVIDER};">{escaped}</div></div>'
            elif source == "tool":
                # 工具调用：橙色边框
                return f'<div style="margin:6px 0;padding:8px;background:{Lemon.DARK_BG_3};border:1px solid {Lemon.BRAND_ORANGE_LIGHT};border-radius:4px;"><span style="color:{Lemon.BRAND_ORANGE_LIGHT};font-size:11px;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg> 工具调用</span><pre style="margin:4px 0;color:#ccc;font-size:12px;white-space:pre-wrap;">{escaped}</pre></div>'
            elif source == "thinking":
                # 思考过程：紫色斜体
                return f'<div style="margin:6px 0;padding:8px;background:Lemon.DARK_MID_5;border-left:3px solid {Lemon.ACCENT_PURPLE};border-radius:4px;font-style:italic;color:#b39ddb;"><span style="font-size:11px;">💭 思考过程</span><div style="margin-top:4px;">{escaped}</div></div>'
            elif source == "status":
                # 状态信息：绿色
                return f'<div style="margin:4px 0;padding:4px 8px;background:#1a2e1a;border-left:3px solid {Lemon.ACCENT_GREEN};color:#81c784;font-size:12px;">✓ {escaped}</div>'
            else:
                return f'<div style="margin:4px 0;color:#ccc;">{escaped}</div>'
        except Exception as e:
            print(f"[MIMOCodePanel] 二次处理失败: {e}")
            return text

    def append_intercepted_display(self, text: str, source: str = "agent"):
        """★ v3.65: 追加二次处理后的拦截内容到右栏显示

        Args:
            text: 拦截的原始文本
            source: 来源类型（agent/tool/thinking/status）
        """
        try:
            processed_html = self.process_intercepted_content(text, source)
            # 使用 appendMessage 注入到聊天容器
            safe_html = processed_html.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')
            self._safe_run_js(f"if(typeof window.mimoAgent!=='undefined'&&window.mimoAgent.appendMessage)window.mimoAgent.appendMessage('{safe_html}');")

            # ★ v4.1.15: HOST 夺舍模式下，工具/思考类拦截输出同步进 Timeline（带来源标识）
            if self._display_only_mode and source in ("tool", "thinking", "status"):
                agent_name = getattr(self, "_intercept_agent_name", "外部 Agent")
                preview = str(text or "")[:100]
                event = {
                    "type": "tool" if source == "tool" else ("search" if "search" in preview.lower() else "tool"),
                    "tool": source,
                    "title": f"[{agent_name}] {source}",
                    "file": "",
                    "lines": "",
                    "stat": "",
                    "success": True,
                    "detail": preview,
                    "result": "",
                    "host": True,  # 标记来源为 HOST 拦截，前端可特殊着色
                }
                self.pybridge.append_timeline_signal.emit(json.dumps(event, ensure_ascii=False))
        except Exception as e:
            print(f"[MIMOCodePanel] append_intercepted_display 失败: {e}")
    
    # ==================== v3.57: MIMO 状态监控 ====================
    
    def _start_mimo_monitor(self):
        """★ v3.57: 启动 MIMO 状态定时监控（30秒间隔）
        ★ v3.71 修复：启动后立即执行首次检查，避免前30秒显示离线
        """
        if not self._mimo_status_timer.isActive():
            self._mimo_status_timer.start()
            print("[MIMO监控] 状态监控已启动（30秒间隔）")
        # ★ v3.71: 立即执行首次检查，不等30秒
        self._check_mimo_status()
    
    def _stop_mimo_monitor(self):
        """★ v3.57: 停止 MIMO 状态定时监控"""
        if self._mimo_status_timer.isActive():
            self._mimo_status_timer.stop()
            print("[MIMO监控] 状态监控已停止")
    
    def _check_mimo_status(self):
        """★ v3.57: 检查 MIMO Code 状态并更新 UI

        ★ 卡顿修复（2026-08-28，第338章）: 原实现在主线程同步执行
        TCP connect(timeout=1s) + requests.get(timeout=3s)，30 秒一次最多冻结 UI 4 秒
        （端口被防火墙 DROP / 服务半死时必现）。现在网络探测移到 daemon 后台线程，
        结果经 Qt 信号（线程安全）回主线程更新 UI。
        """
        if getattr(self, "_mimo_check_running", False):
            return  # 上一次检查未完成，跳过（防止后台线程堆积）
        self._mimo_check_running = True

        def _probe():
            import socket
            port_open = False
            http_ok = False
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                port_open = sock.connect_ex(('127.0.0.1', 4097)) == 0
                sock.close()
            except Exception:
                pass
            if port_open:
                try:
                    import requests as _requests
                    r = _requests.get("http://127.0.0.1:4097/global/health", timeout=3)
                    http_ok = r.status_code == 200
                except Exception:
                    pass
            self._mimo_check_running = False
            try:
                self._mimo_status_checked.emit(port_open, http_ok)
            except Exception:
                pass

        threading.Thread(target=_probe, daemon=True, name="mimo-status-probe").start()

    def _apply_mimo_status(self, port_open: bool, http_ok: bool):
        """★ 卡顿修复: 主线程应用 MIMO 状态探测结果（原 _check_mimo_status 的 UI 更新部分）"""
        try:
            is_available = port_open and http_ok
            status_changed = (is_available != self._mimo_was_available)
            self._mimo_available = is_available
            self._mimo_was_available = is_available

            # 更新前端状态灯
            status_text = "online" if is_available else "offline"
            self._safe_run_js(
                f"if(typeof updateMimoStatus==='function')updateMimoStatus('{status_text}',{str(port_open).lower()},{str(http_ok).lower()})"
            )

            # 状态变化时的提示
            if status_changed:
                if is_available:
                    print("[MIMO监控] MIMO Code 已上线")
                    self._safe_run_js(
                        "if(window.mimoAgent&&typeof window.mimoAgent.appendStatus==='function'){window.mimoAgent.appendStatus('MIMO Code 已连接', 'success')}"
                    )
                else:
                    print("[MIMO监控] MIMO Code 已离线")
                    if port_open:
                        reason = "HTTP 健康检查失败（端口开放但服务无响应）"
                    else:
                        reason = "端口 4097 未开放"
                    print(f"[MIMO监控] 离线原因: {reason}")

            print(f"[MIMO监控] 状态: 端口={'开放' if port_open else '关闭'}, HTTP={'正常' if http_ok else '异常'}, 可用={is_available}")

            # ★ 卡顿修复适配: 处理挂起的首次引导请求
            if getattr(self, "_pending_mimo_guide", False):
                self._pending_mimo_guide = False
                if not self._mimo_available:
                    self._show_mimo_startup_guide()
        except Exception as e:
            print(f"[MIMO监控] 状态应用失败: {e}")
    
    def _check_and_guide_mimo(self):
        """★ v3.57: 首次选择 MIMO 模式时检查状态，不可用时显示引导

        ★ 卡顿修复适配: 状态检查已异步化，这里挂起引导请求，
        待 _apply_mimo_status 收到探测结果后再决定是否弹引导。
        """
        self._pending_mimo_guide = True
        self._check_mimo_status()
    
    def _show_mimo_startup_guide(self):
        """★ v3.57: 显示 MIMO Code 启动引导提示
        
        当用户首次选择 MIMO 模式但 MIMO 不可用时，在右侧面板显示友好的引导信息。
        """
        import os
        
        # 检测 mimo.exe 路径
        _mimo_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "小米AI", "node_global"
        )
        exe_path = os.path.join(
            _mimo_root, "node_modules",
            "@mimo-ai", "mimocode-windows-x64", "bin", "mimo.exe"
        )
        exe_exists = os.path.exists(exe_path)
        exe_dir = os.path.dirname(exe_path) if exe_exists else "MIMO安装目录"
        
        guide_html = (
            f'<div style="background:rgba(33,150,243,0.08);border:1px solid rgba(33,150,243,0.3);'
            f'border-radius:8px;padding:12px 16px;margin:12px 0;font-size:13px;line-height:1.6;">'
            f'<div style="color:#42a5f5;font-weight:bold;font-size:14px;margin-bottom:8px;">'
            f'◈ MIMO Code 启动引导</div>'
            f'<div style="color:#bbb;margin-bottom:8px;">'
            f'检测到 MIMO Code 服务未运行，请按以下步骤启动：</div>'
            f'<div style="background:rgba(0,0,0,0.4);color:Lemon.SUCCESS;padding:8px 12px;'
            f'border-radius:4px;font-family:Courier New,monospace;font-size:12px;margin-bottom:8px;">'
            f'cd "{exe_dir}"<br/>'
            f'mimo serve --port 4097'
            f'</div>'
            + (f'<div style="color:{Lemon.ACCENT_ORANGE};font-size:11px;margin-bottom:8px;">'
               f'▲ mimo.exe 未找到，请确认 MIMO Code 已正确安装</div>'
               if not exe_exists else '') +
            f'<div style="color:#888;font-size:11px;">'
            f'启动后等待 3-5 秒，MIMO 状态灯将自动变为绿色。<br/>'
            f'也可以切换到 <b>Ollama 模式</b> 或 <b>自动模式</b> 使用本地 AI 引擎。</div>'
            f'</div>'
        )
        
        # 发送引导消息到右侧面板
        if hasattr(self, 'output_received'):
            self.output_received.emit(guide_html)
        elif hasattr(self, 'status_received'):
            self.status_received.emit(guide_html)
        
        print("[MIMO监控] 首次检查不可用，已显示启动引导")
    
    def _send_via_ollama(self, prompt: str):
        """★ v3.56: 通过 Ollama 引擎发送消息（使用 shared/engine_manager.chat() + Skills 集成）
        
        使用 shared/engine_manager.py 的 chat() 方法，它集成了：
        - AGENT_ROLES 角色系统（coder/analyst/writer/assistant）
        - Skills 预处理（自动匹配增强 prompt）
        - 长思考模式（think=True 时 num_predict=2000）
        - 上下文压缩（保留最近5轮 + 摘要）
        - 响应缓存（LRU + TTL，5分钟有效期）
        """
        print(f"[Engine] 使用 Ollama 引擎发送消息（chat 模式）")
        if not prompt.startswith('__'):
            self._configure_engine_for_coding("ollama")
            if self._js_ready:
                self._safe_run_js("onStreamStart()")
            else:
                print("[Engine] JS 未就绪，延迟 onStreamStart()")
                QTimer.singleShot(500, lambda: self._safe_run_js("onStreamStart()"))
        # ★ v3.56: 使用 shared/engine_manager 的 chat() 方法（集成 Skills + 角色 + 缓存）
        print(f"[Engine] 发送消息到 EngineManager.chat(): '{prompt[:50]}...'")
        try:
            from shared.engine_manager import get_engine_manager
            engine_mgr = get_engine_manager()
            # 使用当前角色 + 长思考模式
            response = engine_mgr.chat(prompt, engine="ollama", role=self._current_role, think=True)
            print(f"[Engine] EngineManager.chat() 完成, engine={response.engine}")
            # 将回复发送到前端
            if response and hasattr(response, 'content'):
                self.output_received.emit(response.content)
                # 通知前端流式输出结束
                self._safe_run_js("onStreamEnd()")
        except Exception as e:
            print(f"[Engine] EngineManager.chat() 失败: {e}")
            self.on_output(f"<span style='color:{Lemon.ACCENT_RED};'>⚠️ Ollama 调用失败: {e}</span>")

    def _send_via_engine(self, prompt: str, engine_id: str):
        """★ P6: 通用引擎发送方法（支持 ollama/deepseek 等）
        
        通过 EngineManager 统一调用指定引擎，复用 Skills 集成、角色系统、缓存等。
        """
        print(f"[Engine] 使用 {engine_id} 引擎发送消息")
        if not prompt.startswith('__'):
            self._configure_engine_for_coding(engine_id)
            if self._js_ready:
                self._safe_run_js("onStreamStart()")
            else:
                print("[Engine] JS 未就绪，延迟 onStreamStart()")
                QTimer.singleShot(500, lambda: self._safe_run_js("onStreamStart()"))
        try:
            from shared.engine_manager import get_engine_manager
            engine_mgr = get_engine_manager()
            response = engine_mgr.chat(prompt, engine=engine_id, role=self._current_role, think=True)
            print(f"[Engine] EngineManager.chat({engine_id}) 完成, engine={response.engine}")
            if response and hasattr(response, 'content'):
                self.output_received.emit(response.content)
                self._safe_run_js("onStreamEnd()")
        except Exception as e:
            print(f"[Engine] EngineManager.chat({engine_id}) 失败: {e}")
            self.on_output(f"<span style='color:{Lemon.ACCENT_RED};'>⚠️ {engine_id} 调用失败: {e}</span>")

    # ============================================================
    # ★ v3.63: 真正的 Agent 工具调用循环集成
    # ============================================================

    # ============================================================
    # ★第362章: 对话消息队列 —— Agent 运行中新消息排队，收口后自动续跑
    #   （CodeBuddy/Trae 式：运行中可继续输入，发送后依次自动执行；
    #     用户显式中断则清空队列）
    # ============================================================
    _PENDING_MSG_LIMIT = 5

    def _agent_busy(self) -> bool:
        """Agent 任务是否正在运行。

        ★第362章修复: 以任务级标志 _agent_task_active（started 置位 / 三收口复位）
        为主判定 —— 原 isRunning() 在 worker 卡死（如无超时网络读）时永远 True，
        会导致新消息被永久吞进队列（用户实测"发消息无响应"的直接根因）。
        """
        if getattr(self, "_agent_task_active", False):
            return True
        worker = getattr(self, "_current_agent_worker", None)
        return worker is not None and worker.isRunning()

    def _pending_count(self) -> int:
        return len(getattr(self, "_pending_msgs", []))

    def _update_pending_ui(self, note: str = ""):
        """排队角标 → 前端（N 条排队中；0 隐藏）。

        ★ Lemon Work: 同时下发逐条预览（微信 task-dock 对齐）——
        items=[{i, preview}]，前端可展开列表并单条撤销。
        ★ v350: 附加 full 全文（取回编辑用）+ paused 挂起态。"""
        try:
            n = self._pending_count()
            paused = bool(getattr(self, "_pending_paused", False))
            items = [
                {"i": idx, "preview": str(m.get("prompt", ""))[:48],
                 "full": str(m.get("prompt", ""))}
                for idx, m in enumerate(getattr(self, "_pending_msgs", []))
            ]
            self._safe_run_js(
                "if(window.setPendingQueue)window.setPendingQueue(%d,%s,%s,%s);"
                % (n, json.dumps(note, ensure_ascii=False),
                   json.dumps(items, ensure_ascii=False),
                   "true" if paused else "false"))
        except Exception:
            pass

    def _toggle_pending_pause(self, paused: bool = None):
        """★ v350: 挂起/继续排队自动发送（微信版队列挂起对齐）。

        ★ 漏洞修复：挂起时收口 dequeue 会被挡住（不重试直接 return），
        恢复时若任务已收口且无人再调 dequeue → 队列永久卡死。
        因此恢复（paused=False）且当前不忙时主动触发出队一次。"""
        try:
            cur = bool(getattr(self, "_pending_paused", False))
            new = (not cur) if paused is None else bool(paused)
            self._pending_paused = new
            self.pybridge.append_status_signal.emit(
                f"<span style='color:{Lemon.BRAND_ORANGE_LIGHT};'>"
                f"{'⏸ 队列已挂起（收口后不再自动发送）' if new else '▶ 队列已恢复自动发送'}</span>")
            self._update_pending_ui()
            if not new and not self._agent_busy() and self._pending_count() > 0:
                QTimer.singleShot(400, self._dequeue_next_message)
        except Exception as e:
            print(f"[PendingQueue] 挂起切换失败: {e}")

    def _send_pending_now(self, idx):
        """★ v350: 单条立即发送 —— 出队并立刻执行（不等当前任务收口后自动续跑）。"""
        try:
            idx = int(idx)
            msgs = getattr(self, "_pending_msgs", [])
            if not (0 <= idx < len(msgs)):
                return
            item = msgs.pop(idx)
            self._update_pending_ui()
            logger.info(f"[PendingQueue] 立即发送: {item['prompt'][:60]}")
            QTimer.singleShot(300, lambda: self._send_via_agent_chat(
                item["prompt"], engine_id=item["engine_id"],
                model=item["model"], use_agent=True))
        except Exception as e:
            print(f"[PendingQueue] 立即发送失败: {e}")

    def _regenerate_last(self):
        """★ v351 微信版"重新生成"对齐 —— 用上一条 prompt+引擎原样重跑。"""
        try:
            prompt = str(getattr(self, "_last_agent_prompt", "")
                         or getattr(self, "_current_agent_prompt", "") or "").strip()
            engine = str(getattr(self, "_last_agent_engine", "")
                         or getattr(self, "_current_agent_engine", "") or "deepseek")
            if not prompt:
                self.pybridge.append_status_signal.emit(
                    f"<span style='color:{Lemon.ACCENT_RED};'>没有可重新生成的上一条消息</span>")
                return {"ok": False, "err": "no-prompt"}
            if self._agent_busy():
                self._enqueue_pending_message(prompt, engine, "")
                return {"ok": True, "queued": True}
            logger.info(f"[Agent] 重新生成: {prompt[:60]}")
            QTimer.singleShot(200, lambda: self._send_via_agent_chat(
                prompt, engine_id=engine, use_agent=True))
            return {"ok": True}
        except Exception as e:
            print(f"[Agent] 重新生成失败: {e}")
            return {"ok": False, "err": str(e)[:80]}

    # ============================================================
    # ★ v355 自定义模型（Trae/CodeBuddy 表单式）+ 本地模型探测器
    #   只显示「探测可达」的本地模型与「验证在线」的自定义模型
    # ============================================================
    _CUSTOM_MODELS_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "custom_models.json")

    def _custom_models_load(self) -> list:
        try:
            with open(self._CUSTOM_MODELS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def _custom_models_save(self, models: list):
        try:
            os.makedirs(os.path.dirname(self._CUSTOM_MODELS_PATH), exist_ok=True)
            with open(self._CUSTOM_MODELS_PATH, "w", encoding="utf-8") as f:
                json.dump(models, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"[CustomModel] 保存失败: {e}")

    @staticmethod
    def _probe_openai_compat(base_url: str, api_key: str, timeout: int = 6) -> dict:
        """探测 OpenAI 兼容端点：GET {base}/models（带鉴权）。返回 {online, ms, err}。"""
        import time as _time
        import requests as _rq
        _noproxy = {"http": None, "https": None}
        base = (base_url or "").rstrip("/")
        if not base:
            return {"online": False, "ms": 0, "err": "BASE URL 为空"}
        if not base.endswith("/v1") and not base.endswith("/api"):
            # 常见容错：用户填根域名 → 自动补 /v1（OpenAI 兼容惯例）
            base = base + "/v1"
        t0 = _time.time()
        try:
            r = _rq.get(base + "/models",
                        headers={"Authorization": "Bearer " + (api_key or "")},
                        timeout=timeout, proxies=_noproxy)
            ms = int((_time.time() - t0) * 1000)
            if r.status_code == 200:
                return {"online": True, "ms": ms, "err": ""}
            return {"online": False, "ms": ms,
                    "err": f"HTTP {r.status_code}（{'Key 无效' if r.status_code == 401 else '端点拒绝'}）"}
        except Exception as e:
            return {"online": False, "ms": 0, "err": str(e)[:80]}

    def _list_local_models(self) -> dict:
        """★ 本地模型探测器：真实拉取 Ollama /api/tags，只返回服务在线时的列表。"""
        import requests as _rq
        _noproxy = {"http": None, "https": None}
        host = "http://localhost:11434"
        try:
            from settings_manager import get_settings_manager
            h = (get_settings_manager().ollama_host or "").strip()
            if h:
                host = h
        except Exception:
            pass
        t0 = __import__("time").time()
        try:
            r = _rq.get(host.rstrip("/") + "/api/tags", timeout=4, proxies=_noproxy)
            ms = int((__import__("time").time() - t0) * 1000)
            if r.status_code != 200:
                return {"online": False, "ms": ms, "models": [],
                        "err": f"HTTP {r.status_code}"}
            items = (r.json() or {}).get("models") or []
            models = []
            for it in items:
                name = str(it.get("name") or "")
                if not name:
                    continue
                size_gb = round((it.get("size") or 0) / (1024 ** 3), 1)
                models.append({
                    "id": name, "name": name,
                    "size": ("%.1f GB" % size_gb) if size_gb > 0 else "",
                    "params": str(it.get("details", {}).get("parameter_size") or ""),
                })
            return {"online": True, "ms": ms, "models": models, "err": ""}
        except Exception as e:
            return {"online": False, "ms": 0, "models": [], "err": str(e)[:80]}

    def _add_custom_model(self, payload: dict) -> dict:
        """★ v355: 添加自定义模型（Trae 式表单）—— 保存前先探连接，
        只有「验证在线」的才入列表（用户要求：只显示能连上的）。"""
        try:
            name = str(payload.get("name") or "").strip()
            base_url = str(payload.get("base_url") or "").strip()
            api_key = str(payload.get("api_key") or "").strip()
            if not name:
                return {"ok": False, "err": "模型名称不能为空"}
            if not base_url:
                return {"ok": False, "err": "BASE URL 不能为空"}
            # 真探测
            probe = self._probe_openai_compat(base_url, api_key)
            if not probe.get("online"):
                return {"ok": False, "err": "连接失败：" + probe.get("err", ""),
                        "probe": probe}
            models = self._custom_models_load()
            # 同名同地址去重（更新）
            cm_id = ""
            for m in models:
                if m.get("name") == name and m.get("base_url") == base_url:
                    cm_id = m.get("id") or ""
                    break
            entry = {
                "id": cm_id or ("cm_" + str(int(__import__("time").time() * 1000))),
                "name": name, "base_url": base_url, "api_key": api_key,
                "tools": bool(payload.get("tools", True)),
                "vision": bool(payload.get("vision", False)),
                "reasoning": bool(payload.get("reasoning", False)),
                "ctx_in": int(payload.get("ctx_in") or 32768),
                "ctx_out": int(payload.get("ctx_out") or 8192),
                "online": True, "ms": probe.get("ms", 0),
                "ts": __import__("time").time(),
            }
            if cm_id:
                models = [entry if m.get("id") == cm_id else m for m in models]
            else:
                models.append(entry)
            self._custom_models_save(models)
            return {"ok": True, "model": entry}
        except Exception as e:
            return {"ok": False, "err": str(e)[:100]}

    def _remove_custom_model(self, cm_id: str) -> dict:
        try:
            models = [m for m in self._custom_models_load()
                      if str(m.get("id")) != str(cm_id)]
            self._custom_models_save(models)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "err": str(e)[:80]}

    def _list_custom_models(self, recheck: bool = False) -> dict:
        """已保存的自定义模型；recheck=True 时逐个重测连接，
        掉线的从列表剔除（保持「只显示能连上的」语义）。"""
        try:
            models = self._custom_models_load()
            if recheck:
                kept = []
                for m in models:
                    probe = self._probe_openai_compat(
                        m.get("base_url", ""), m.get("api_key", ""), timeout=5)
                    m["online"] = bool(probe.get("online"))
                    m["ms"] = probe.get("ms", 0)
                    if m["online"]:
                        kept.append(m)
                self._custom_models_save(kept)
                models = kept
            # 安全：不回传完整 key
            safe = [{k: v for k, v in m.items() if k != "api_key"} for m in models]
            return {"ok": True, "models": safe}
        except Exception as e:
            return {"ok": False, "models": [], "err": str(e)[:80]}

    def _remove_pending_message(self, idx):
        """★ Lemon Work: 单条撤销排队消息（前端列表 × 按钮）。"""
        try:
            idx = int(idx)
            msgs = getattr(self, "_pending_msgs", [])
            if 0 <= idx < len(msgs):
                item = msgs.pop(idx)
                self.pybridge.append_status_signal.emit(
                    f"<span style='color:{Lemon.ACCENT_RED};'>已撤销排队消息："
                    f"{str(item.get('prompt', ''))[:30]}</span>")
                logger.info(f"[PendingQueue] 单条撤销: {str(item.get('prompt', ''))[:60]}")
            self._update_pending_ui()
        except Exception as e:
            print(f"[PendingQueue] 撤销失败: {e}")

    def _enqueue_pending_message(self, prompt: str, engine_id: str, model: str):
        """Agent 忙碌时新消息入队（上限 5，满时丢最旧保最新）。"""
        if not hasattr(self, "_pending_msgs"):
            self._pending_msgs = []
        note = ""
        if len(self._pending_msgs) >= self._PENDING_MSG_LIMIT:
            self._pending_msgs.pop(0)
            note = "队列已满（上限5），最早一条已被丢弃"
        self._pending_msgs.append({
            "prompt": prompt, "engine_id": engine_id, "model": model,
        })
        self._update_pending_ui(note)
        self.pybridge.append_status_signal.emit(
            f"<span style='color:{Lemon.BRAND_ORANGE_LIGHT};'>⏸ 消息已加入队列"
            f"（第 {self._pending_count()} 位，当前任务完成后自动执行）</span>"
        )
        logger.info(f"[PendingQueue] 入队: {prompt[:60]}（共 {self._pending_count()} 条）")

    def _dequeue_next_message(self):
        """收口后续跑下一条排队消息。

        busy 时不再直接放弃——有限重试（3 次 × 1.5s），根治"出队恰逢 worker
        收尾被 isRunning 挡住 → 队列永久卡死"（第362章用户实测根因）。
        auto 模式引擎回退续跑场景下重试同样适用（回退任务会重建标志位，
        重试期内持续 busy 直到耗尽后放弃，不会双任务并发）。
        """
        try:
            if self._agent_busy():
                retries = getattr(self, "_dq_retries", 0)
                if retries < 3:
                    self._dq_retries = retries + 1
                    QTimer.singleShot(1500, self._dequeue_next_message)
                else:
                    self._dq_retries = 0
                    logger.warning("[PendingQueue] 出队重试耗尽（任务仍忙碌），本轮放弃")
                return
            self._dq_retries = 0
            # ★ v350: 挂起检查 —— 用户点"⏸ 挂起"后收口不再自动续跑
            if getattr(self, "_pending_paused", False):
                self._update_pending_ui()
                return
            msgs = getattr(self, "_pending_msgs", [])
            if not msgs:
                self._update_pending_ui()
                return
            item = msgs.pop(0)
            self._update_pending_ui()
            self.pybridge.append_status_signal.emit(
                f"<span style='color:{Lemon.BRAND_ORANGE_LIGHT};'>▶ 开始执行排队消息"
                f"（剩余 {self._pending_count()} 条）</span>"
            )
            logger.info(f"[PendingQueue] 出队续跑: {item['prompt'][:60]}")
            # 延迟一帧再走完整发送链路（含流式重置/上下文记录）
            QTimer.singleShot(500, lambda: self._send_via_agent_chat(
                item["prompt"], engine_id=item["engine_id"],
                model=item["model"], use_agent=True))
        except Exception as e:
            print(f"[PendingQueue] 出队失败: {e}")

    def _clear_pending_queue(self):
        """清空排队消息（用户显式中断 / 前端点×）。"""
        n = self._pending_count()
        if hasattr(self, "_pending_msgs"):
            self._pending_msgs.clear()
        self._update_pending_ui()
        if n:
            self.pybridge.append_status_signal.emit(
                f"<span style='color:{Lemon.ACCENT_RED};'>已清空 {n} 条排队消息</span>"
            )

    def _send_via_agent_chat(self, prompt: str, engine_id: str = "deepseek",
                              model: str = "", use_agent: bool = True):
        """★ v3.63: 通过 EngineManager.agent_chat() 发送消息（真正的 Agent 工具调用循环）
        ★ v3.68: 自动维护对话上下文（user/assistant 消息对），支持多轮对话

        与 _send_via_engine 的区别：
        - _send_via_engine 使用 engine_mgr.chat()：单轮调用，无工具循环
        - _send_via_agent_chat 使用 engine_mgr.agent_chat()：多轮工具调用循环

        流程：
        1. 启动 onStreamStart 标记
        2. 创建 AgentChatWorker（QThread）异步执行 agent_chat
        3. 通过 tool_call_event 信号实时展示工具调用中间过程
        4. 完成后通过 finished_event 信号输出最终回复
        5. 支持通过 _cancel_current_agent() 取消
        6. ★ v3.68: 完成后将 user/assistant 消息对保存到 _conversation_context

        Args:
            prompt: 用户输入
            engine_id: 引擎 ID（deepseek/ollama/mimocode）
            model: 模型名（可选，留空使用引擎默认）
            use_agent: True=使用 agent_chat；False=回退到 _send_via_engine
        """
        if not use_agent:
            self._send_via_engine(prompt, engine_id)
            return

        # ★第362章: 消息队列 —— Agent 忙碌时新消息入队，不打断当前任务
        #   （旧行为是 _cancel_current_agent() 直接打断重启，现改为 CodeBuddy/Trae 式排队）
        if self._agent_busy():
            if getattr(self, "_agent_task_active", False):
                self._enqueue_pending_message(prompt, engine_id, model)
                return
            # 竞态兜底：isRunning 残留（线程将退未退）而任务标志已收口 → 不吞消息，
            # 直接覆盖旧 worker 继续执行（下方 _cancel_current_agent 会清场）
            logger.warning("[PendingQueue] isRunning 残留竞态，消息直接执行不入队")

        # ★ v3.68: 记录当前用户输入（_on_agent_finished 时存入上下文）
        self._current_agent_prompt = prompt
        # ★ v351: 持久化上一条（收口后"重新生成"按钮的数据源）
        self._last_agent_prompt = prompt
        self._last_agent_engine = engine_id
        # ★ v5.3 修复 F2: 记录 engine/model/iter，供 agentStepsPanel 头部 meta 实时显示
        self._current_agent_engine = engine_id
        self._current_agent_model = model or ""
        self._current_agent_iter = 0
        # ★ v4.8: 记录当前引擎，供 _on_agent_error 自动回退使用
        self._last_agent_engine = engine_id

        print(f"[Agent] 启动 Agent 工具调用循环，引擎={engine_id}, 模型={model or '(默认)'}")
        print(f"[DIAG] _send_via_agent_chat: engine_id={engine_id}, _js_ready={self._js_ready}, _js_call_queue_size={len(self._js_call_queue)}")

        # 配置引擎系统提示词
        if not prompt.startswith('__'):
            self._configure_engine_for_coding(engine_id)
            # ★ v3.64: onStreamStart 由首个流式 token 触发（_on_agent_stream_token），
            # 这里仅重置流式状态标志，避免重复触发
            self._agent_stream_active = False
            # ★389M-1: 本轮 live 计数器（流式接线——运行中状态条实时递增的数据源）
            self._agent_live_started_at = time.time()
            self._agent_live_out_tok = 0
            self._agent_live_tools = 0
            self._agent_live_last_emit = 0.0
            # ★391A-3: live 真值槽（由 usage_updated 信号驱动）+ 终态拦截标志
            self._agent_live_in_tok = 0
            self._agent_live_ctx_tok = 0
            self._agent_live_finalized = False
            # ★392A-3: 流断看门狗 —— 任务开始即激活（90s/300s 两档提示），
            #   tick 复用 _js_flush_timer（执行中保持运行，无新轮询线程）
            self._agent_watchdog_active = True
            self._watchdog_tier = 0
            self._watchdog_last_emit = 0.0
            self._agent_live_last_token_ts = time.time()
            if not self._js_flush_timer.isActive():
                self._js_flush_timer.start()
            # ★391A-1.3: 状态条窗口标注同源注入 —— ollama 引擎时模型名后缀
            #   "(32k)" 读 ollama.num_ctx 键（与引擎请求构建同一真源，禁 UI 自造）
            self._agent_live_ctx_label = ""
            if engine_id == "ollama":
                try:
                    from shared.engine_manager import get_ollama_num_ctx
                    self._agent_live_ctx_label = f"({get_ollama_num_ctx() // 1024}k)"
                except Exception:
                    pass
            # 兜底：若 3 秒内无任何 token 到达（如纯工具调用场景），强制触发 onStreamStart
            QTimer.singleShot(3000, lambda: self._ensure_stream_started_fallback())

        # 取消上一次未完成的 agent 循环
        self._cancel_current_agent()

        try:
            from shared.engine_manager import get_engine_manager
            engine_mgr = get_engine_manager()

            # 构建 Agent 参数
            agent_kwargs = {"engine": engine_id}
            # ★第361章: 会话 ID — 任务列表/子代理状态按会话隔离与定向推送的依据
            _sid = str(getattr(self, "_session_sid", "") or "")
            if _sid:
                agent_kwargs["session_id"] = _sid
            if model:
                agent_kwargs["model"] = model
            # ★ v3.68: 传递对话历史（最近 N 轮 user/assistant 对）
            # 让 Agent 能理解上下文（如"刚才那个文件"、"继续上面的"等指代）
            if self._conversation_context:
                agent_kwargs["history"] = list(self._conversation_context[-self._max_context_turns * 2:])
            # ★ v3.70: 多模态 — 附加暂存的图片 base64 列表（发送后清空）
            if self._pending_images:
                agent_kwargs["images"] = [img["data"] for img in self._pending_images]
                # 在 prompt 中附加图片提示，让模型知道有图片
                if not prompt:
                    prompt = "（请分析上传的图片）"
                self._pending_images = []  # 清空，避免重复发送

            # ★ Lemon Work: 思考档位（微信版 light10/standard20/high40 对齐）——
            #   输入区下拉选择，standard 走任务复杂度自动分档
            _effort = getattr(self, "_agent_effort", "standard")
            if _effort == "light":
                agent_kwargs["max_iterations"] = 10
            elif _effort == "deep":
                agent_kwargs["max_iterations"] = 40

            # ★ v355: 自定义模型真实生效 —— 激活的自定义模型在发送前
            #   覆盖 deepseek 引擎的 api_base/api_key + 模型名。
            #   （自定义端点均为 OpenAI 兼容，deepseek 引擎即 OpenAI 协议实现）
            _cm = getattr(self, "_active_custom_model", None)
            if _cm and engine_id in ("deepseek", "custom"):
                try:
                    _eng = engine_mgr.get_engine("deepseek")
                    _cfg = getattr(_eng, "config", None)
                    if _cfg is not None:
                        _cfg.api_base = str(_cm.get("base_url") or "").rstrip("/")
                        _cfg.api_key = str(_cm.get("api_key") or "")
                        print(f"[CustomModel] 本次请求走自定义端点: "
                              f"{_cm.get('name')} → {_cfg.api_base}", flush=True)
                except Exception as _ce:
                    print(f"[CustomModel] 端点覆盖失败: {_ce}", flush=True)
                agent_kwargs["model"] = str(_cm.get("name") or "custom-model")
                agent_kwargs["engine"] = "deepseek"

            # 创建 Worker
            self._current_agent_worker = AgentChatWorker(
                engine_mgr, prompt, parent=self, **agent_kwargs
            )

            # 连接 Worker 信号 → UI 处理器
            self._current_agent_worker.started_event.connect(self._on_agent_started)
            self._current_agent_worker.tool_call_event.connect(self._on_agent_tool_call_event)
            self._current_agent_worker.finished_event.connect(self._on_agent_finished)
            self._current_agent_worker.error_event.connect(self._on_agent_error)
            self._current_agent_worker.cancelled_event.connect(self._on_agent_cancelled)
            # ★ v3.64: 连接流式 token 信号
            self._current_agent_worker.stream_token_event.connect(self._on_agent_stream_token)

            # 同时连接 EngineManager 的 tool_call_made 信号（实时，不等待 Worker）
            try:
                engine_mgr.tool_call_made.connect(self._on_engine_tool_call_made)
                # ★ Lemon Work: 思考过程实时流（微信版 live_reasoning 对齐）——
                #   先断后连，避免多次发送重复挂接
                try:
                    engine_mgr.thinking_received.disconnect(self._on_agent_thinking_delta)
                except Exception:
                    pass
                engine_mgr.thinking_received.connect(self._on_agent_thinking_delta)
                # ★ Lemon Work: 每轮迭代信号 → 过程层"第 N 轮"分层（微信/Trae 多层白盒核心）
                try:
                    engine_mgr.agent_iteration.disconnect(self._on_agent_iteration)
                except Exception:
                    pass
                engine_mgr.agent_iteration.connect(self._on_agent_iteration)
                # ★391A-3: 引擎每轮真实 usage 信号（替代"事件计数"假口径）
                engine_mgr.usage_updated.connect(self._on_engine_usage_updated)
                # ★第361章: 会话级任务列表/子代理状态（按 _session_sid 过滤，多会话互不串扰）
                try:
                    engine_mgr.task_list_changed.disconnect(self._on_task_list_changed)
                except Exception:
                    pass
                engine_mgr.task_list_changed.connect(self._on_task_list_changed)
                try:
                    engine_mgr.subagent_status_changed.disconnect(self._on_subagent_status_changed)
                except Exception:
                    pass
                engine_mgr.subagent_status_changed.connect(self._on_subagent_status_changed)
                # ★392A-3: 引擎侧流断看门狗事件（事后上报）→ trace 时间线
                try:
                    engine_mgr.stream_stalled.disconnect(self._on_engine_stream_stalled)
                except Exception:
                    pass
                engine_mgr.stream_stalled.connect(self._on_engine_stream_stalled)
            except Exception:
                pass  # 可能已连接
            # ★ 第345章: 工具开始信号 → TraceRenderer 实时转圈卡片（防重复连接）
            if getattr(self, "_trace_v2", False):
                try:
                    engine_mgr.tool_call_starting.disconnect(self._on_engine_tool_call_started)
                except Exception:
                    pass
                try:
                    engine_mgr.tool_call_starting.connect(self._on_engine_tool_call_started)
                except Exception:
                    pass

            # 启动线程
            self._current_agent_worker.start()
            print(f"[Agent] AgentChatWorker 已启动")

        except Exception as e:
            print(f"[Agent] 启动 agent_chat 失败: {e}")
            self.on_output(f"<span style='color:{Lemon.ACCENT_RED};'>⚠️ Agent 调用失败: {e}</span>")
            self._safe_run_js("onStreamEnd()")

    def _cancel_current_agent(self):
        """取消当前正在运行的 Agent 循环"""
        worker = getattr(self, "_current_agent_worker", None)
        if worker is not None and worker.isRunning():
            print("[Agent] 取消当前 Agent 循环")
            worker.cancel()
            # 给线程 500ms 优雅退出，否则强制终止
            worker.wait(500)
            if worker.isRunning():
                worker.terminate()
        self._current_agent_worker = None

    def _request_agent_interrupt(self):
        """★392A-2: 状态条停止按钮 → 立即中断进行中的 agent 任务。

        与 _cancel_current_agent（新任务开始时清场）不同，本方法面向用户显式中断：
        ① cancel_agent 置位 + 强断在途 HTTP（适配器在 daemon 线程 close）；
        ② 引擎侧流内每 chunk 检查 → 有 token 流时 <1s 抛 AgentCancelledError；
        ③ 阻塞读场景由读超时分级（300s）兜底——requests/Windows 跨线程强断
          被实测否定（392A-2 验收），此处不再做额外的 terminate（防状态破坏）。
        状态条"正在中断当前请求…"由 JS 侧 stopAgentTask 点击即显（不经本方法）。"""
        print("[Agent] 用户请求中断当前请求（停止按钮）")
        try:
            from shared.engine_manager import get_engine_manager
            engine_mgr = get_engine_manager()
            engine_mgr.cancel_agent()
        except Exception as e:
            print(f"[Agent] 中断请求失败: {e}")
        worker = getattr(self, "_current_agent_worker", None)
        if worker is not None:
            try:
                worker.cancel()
            except Exception:
                pass

    # ============================================================
    # ★第361章: 会话级任务列表 / 子代理状态（Trae/CodeBuddy 式）
    # ============================================================
    def _on_task_list_changed(self, session_id: str, tasks_json: str):
        """EngineManager.task_list_changed → 仅本会话面板更新任务列表卡。"""
        try:
            my_sid = str(getattr(self, "_session_sid", "") or "")
            if not my_sid or str(session_id) != my_sid:
                return  # 其它会话的任务变化，忽略（会话隔离）
            self._safe_run_js(
                "if(window.onTaskListUpdate)window.onTaskListUpdate(%s);"
                % (tasks_json or "[]"))
        except Exception as e:
            print(f"[MIMO Panel] 任务列表推送失败: {e}")

    def _on_subagent_status_changed(self, session_id: str, info_json: str):
        """EngineManager.subagent_status_changed → 仅本会话面板更新子代理 chip。"""
        try:
            my_sid = str(getattr(self, "_session_sid", "") or "")
            if not my_sid or str(session_id) != my_sid:
                return
            self._safe_run_js(
                "if(window.onSubagentUpdate)window.onSubagentUpdate(%s);"
                % (info_json or "{}"))
        except Exception as e:
            print(f"[MIMO Panel] 子代理状态推送失败: {e}")

    # ============================================================
    # ★ Lemon Work: 微信版 Agent 白盒化对齐
    #   ① 启动即弹任务列表卡（原版只在模型调 todo_write 时才出现）
    #   ② 循环阶段状态单行实时更新（思考中 → 工具执行中 → 回复中，
    #      对标微信版 _publishLoopStatus 的 loop-text，钉在会话头风扇条）
    # ============================================================
    def _on_agent_thinking_delta(self, text: str):
        """★ Lemon Work: 引擎思考增量 → 过程层"思考过程"节点实时流式。

        对标微信版 _pushReasoning（120ms 节流、尾部 8KB 保留）；
        trace 事件用 delta=True 标记，前端追加到已有思考节点。"""
        try:
            if not getattr(self, "_trace_v2", False) or not text:
                return
            self._trace_think_live = True
            self._emit_trace("thinking", content=str(text), delta=True)
        except Exception:
            pass

    def _on_agent_iteration(self, info: dict):
        """★ Lemon Work: 每轮迭代 → 过程层"第 N 轮"小节（多层白盒核心）。

        引擎每轮开始即发 agent_iteration（iteration/engine/model/elapsed/
        tool_calls_so_far），UI 据此把后续思考/工具/叙述嵌进对应轮次。
        ★ v350: 同时把上一轮累积的工具明细打包为 narrative 事件
        （微信版过程时间线对齐 —— 播报 ↔ 工具统计交替）。"""
        try:
            if not getattr(self, "_trace_v2", False):
                return
            it = int(info.get("iteration") or 0)
            # ★ v350: 上一轮的工具明细 → 时间线（第 2 轮开始时发第 1 轮的汇总）
            prev_tools = getattr(self, "_lw_round_tools", None)
            if it >= 2 and prev_tools:
                self._emit_trace(
                    "narrative",
                    text="第 %d 轮执行完成，共调用 %d 次工具" % (it - 1, len(prev_tools)),
                    tools=prev_tools[:8])
            self._lw_round_tools = []
            if it < 1:
                return  # failover / plan_step 事件不分组
            self._emit_trace(
                "round", idx=it,
                engine=str(info.get("engine", "") or ""),
                tools=int(info.get("tool_calls_so_far") or 0),
                elapsed=info.get("elapsed") or 0,
                max_rounds=int(info.get("max_rounds") or 0))
        except Exception:
            pass

    # ★ v352: 任务列表真拆解 —— 职责是"智能分析拆解任务"（微信版 task-dock 对齐），
    #   不是把执行步骤流水列上去。语义步骤 = 连续同名工具聚合为一个子任务，
    #   各自独立状态（pending/in_progress/completed/failed），随执行实时生长。
    _LW_TOOL_CN = {
        # 远程数字银行
        "remote_bank_query_balance": "查询账户余额",
        "remote_bank_transactions": "查询交易流水",
        "remote_bank_transfer": "办理转账",
        "remote_transfer_schedule": "定时转账",
        "remote_transfer_aa": "AA 收款",
        "remote_bill_analysis": "账单消费分析",
        "remote_wealth_advisor": "理财顾问",
        "remote_card_manage": "银行卡管理",
        "remote_subscription_cancel": "订阅退订",
        "remote_mall": "权益商城",
        "remote_loan_list": "贷款查询",
        "remote_loan_repay": "贷款还款",
        "remote_fund_list": "基金查询",
        "remote_fund_buy": "基金申购",
        "remote_stock_list": "股票行情",
        "remote_stock_kline": "K线查询",
        "remote_stock_trade": "股票交易",
        "remote_bank_holdings": "持仓查询",
        "remote_find_account": "查找收款人",
        "remote_bank_compound": "复利试算",
        "remote_bank_risk_events": "风控事件",
        "remote_bank_audit": "审计日志",
        "remote_bank_reconcile": "对账核查",
        "remote_bank_products": "理财产品",
        "remote_bank_deposits": "定期存款",
        "remote_bank_console": "查看银行操作台",
        # 通用工具
        "write_file": "写入文件", "file_write": "写入文件",
        "edit_file": "编辑文件", "file_edit": "编辑文件",
        "file_append": "追加文件", "multi_edit": "批量编辑",
        "read_file": "读取文件", "terminal": "执行命令",
        "command": "执行命令", "web_search": "联网搜索",
        "web_fetch": "抓取网页", "todo_write": "更新任务清单",
        "spawn_subagent": "派发子代理", "memory_write": "记忆写入",
        "memory_search": "记忆检索",
    }
    _LW_STEP_LIMIT = 12  # 步骤上限（超出合并为"后续执行"）

    # ★v356 业务→银行页面视图映射：Agent 办理业务时操作台自动"跳动"
    #   （切页签 + 滚动到目标区块 + 高亮闪烁 + 浮动提示）
    _BANK_VIEW_MAP = {
        "remote_bank_transfer":     ("bank",  "bTx",        "转账已执行"),
        "remote_transfer_schedule": ("bank",  "bTx",        "定时转账已预约"),
        "remote_transfer_aa":       ("bank",  "bTx",        "AA 收款已发起"),
        "remote_bank_transactions": ("bank",  "bTx",        "已查询交易流水"),
        "remote_bank_query_balance": ("home", "kpi",        "已查询账户余额"),
        "remote_bank_holdings":     ("home",  "holdingsBox", "已刷新持仓总览"),
        "remote_bill_analysis":     ("mine",  "mineTx",     "账单分析完成"),
        "remote_wealth_advisor":    ("fund",  "",           "理财顾问已就绪"),
        "remote_fund_list":         ("fund",  "",           "已查询基金列表"),
        "remote_fund_buy":          ("fund",  "",           "基金申购已提交"),
        "remote_stock_list":        ("stock", "",           "已获取股票行情"),
        "remote_stock_kline":       ("stock", "",           "已查询 K 线"),
        "remote_stock_trade":       ("stock", "",           "股票交易已执行"),
        "remote_loan_list":         ("loan",  "",           "已查询贷款"),
        "remote_loan_repay":        ("loan",  "",           "贷款还款已执行"),
        "remote_card_manage":       ("mine",  "mineCards",  "银行卡操作完成"),
        "remote_subscription_cancel": ("mine", "mineService", "订阅退订已办理"),
        "remote_mall":              ("mine",  "mineOrders", "商城订单已处理"),
        "remote_bank_products":     ("fund",  "",           "已查询理财产品"),
        "remote_bank_deposits":     ("mine",  "mineCenter", "已查询定期存款"),
        "remote_bank_compound":     ("mine",  "mineCenter", "复利试算完成"),
        "remote_bank_risk_events":  ("ops",   "",           "已调取风控事件"),
        "remote_bank_audit":        ("ops",   "",           "已调取审计日志"),
        "remote_bank_reconcile":    ("ops",   "",           "对账核查完成"),
        "remote_bank_console":      ("home",  "kpi",        "操作台已就绪"),
    }

    def _bank_follow_navigate(self, tool_name: str, ok: bool):
        """★v356: remote_bank_* 业务完成后，驱动银行操作台页面跟随跳动。

        后台线程 POST /api/ui/state（不阻塞工具循环）；
        页面内跟随精灵（index.html 注入 JS）1.5s 内自动切页/滚动/高亮。"""
        try:
            if not ok:
                return
            short = str(tool_name or "").split(".")[-1]
            hit = self._BANK_VIEW_MAP.get(short)
            if not hit:
                return
            view, highlight, msg = hit

            def _post():
                try:
                    import requests as _rq
                    _rq.post(
                        "http://127.0.0.1:8090/api/ui/state",
                        json={"view": view, "highlight": highlight, "msg": msg},
                        timeout=3, proxies={"http": None, "https": None})
                except Exception:
                    pass  # 银行离线/页面未开时静默（白盒不受影响）

            import threading as _thn
            _thn.Thread(target=_post, daemon=True).start()
        except Exception:
            pass

    @classmethod
    def _lw_tool_step_name(cls, tool_name: str) -> str:
        """工具名 → 语义步骤名（中文名；未命中回退原名去命名空间）。"""
        n = str(tool_name or "").split(".")[-1]
        return cls._LW_TOOL_CN.get(n, n)

    def _lw_steps_push(self):
        """把当前拆解步骤流推给前端任务卡（形状 {content,status}）。"""
        try:
            steps = getattr(self, "_lw_steps", [])
            tasks = [{"content": s["content"], "status": s["status"]} for s in steps]
            self._safe_run_js(
                "if(window.onTaskListUpdate)window.onTaskListUpdate(%s);"
                % json.dumps(tasks, ensure_ascii=False))
        except Exception:
            pass

    def _lw_step_init(self):
        """任务开始：拆解骨架第一步 = 理解请求并拆解任务。"""
        self._lw_steps = [{"content": "理解请求并拆解任务", "status": "in_progress"}]
        self._lw_step_seq = 0
        self._lw_steps_push()

    def _lw_step_start(self, tool_name: str):
        """工具开始 → 语义步骤生长：同名续用，异名新增；首工具时关掉理解步骤。"""
        try:
            steps = getattr(self, "_lw_steps", None)
            if not isinstance(steps, list):
                steps = []
                self._lw_steps = steps
            if not steps:
                self._lw_step_init()
                steps = self._lw_steps
            # ① 首个真实工具 → "理解请求并拆解任务" 完成
            if steps[0]["content"] == "理解请求并拆解任务" and \
                    steps[0]["status"] == "in_progress":
                steps[0]["status"] = "completed"
            name = self._lw_tool_step_name(tool_name)
            # ② "汇总结果并回复" 若在（上轮收口残留）→ 摘除，任务仍在执行
            while steps and steps[-1]["content"].startswith("汇总结果"):
                steps.pop()
            # ③ 同名连续 → 续用当前步骤；异名 → 新步骤
            if steps and steps[-1]["content"].split(" ×")[0] == name \
                    and steps[-1].get("_name") == name:
                steps[-1]["status"] = "in_progress"
            else:
                # 超上限：合并尾部为"后续执行"
                if len([s for s in steps if not s["content"].startswith("后续执行")]) >= self._LW_STEP_LIMIT:
                    if steps[-1]["content"].startswith("后续执行"):
                        steps[-1]["_name"] = name  # 继续吞并
                    else:
                        steps.append({"content": "后续执行", "status": "in_progress",
                                      "_name": name})
                else:
                    steps.append({"content": name, "status": "in_progress",
                                  "_name": name})
            self._lw_steps_push()
        except Exception:
            pass

    def _lw_step_done(self, tool_name: str, ok: bool):
        """工具完成 → 当前语义步骤落状态 + 计数副标（"×3"）。"""
        try:
            steps = getattr(self, "_lw_steps", [])
            name = self._lw_tool_step_name(tool_name)
            target = None
            for s in reversed(steps):
                if s.get("_name") == name:
                    target = s
                    break
            if target is None:
                return
            target["_n"] = int(target.get("_n", 0)) + 1
            if ok:
                target["status"] = "completed"
            else:
                target["status"] = "failed"
            base = target["content"].split(" ×")[0]
            target["content"] = (base + " ×%d" % target["_n"]) \
                if target["_n"] > 1 else base
            self._lw_steps_push()
        except Exception:
            pass

    def _lw_step_finish(self, ok: bool, interrupted: bool = False):
        """收口：未竟步骤落定 + 追加"汇总结果并回复"。"""
        try:
            steps = getattr(self, "_lw_steps", None)
            if not isinstance(steps, list) or not steps:
                return
            for s in steps:
                if s["status"] == "in_progress":
                    if interrupted:
                        s["status"] = "failed"
                        if not s["content"].endswith("（已中断）"):
                            s["content"] += "（已中断）"
                    else:
                        s["status"] = "completed"
            if interrupted:
                self._lw_steps_push()
                return
            steps.append({"content": "汇总结果并回复", "status": "completed"})
            self._lw_steps_push()
        except Exception:
            pass

    def _push_task_card(self, final: bool = False):
        """★ v352 兼容保留：无拆解流时回退旧静态卡（理解/执行/汇总三步）。"""
        try:
            if isinstance(getattr(self, "_lw_steps", None), list) and self._lw_steps:
                self._lw_steps_push()
                return
            n = getattr(self, "_lw_task_tools", 0)
            if final:
                tasks = [
                    {"content": "理解请求与规划", "status": "completed"},
                    {"content": "执行工具调用（共 %d 次）" % n, "status": "completed"},
                    {"content": "汇总结果并回复", "status": "completed"},
                ]
            else:
                tasks = [
                    {"content": "理解请求与规划", "status": "completed"},
                    {"content": "执行工具调用（已调用 %d 次）" % n, "status": "in_progress"},
                    {"content": "汇总结果并回复", "status": "pending"},
                ]
            self._safe_run_js(
                "if(window.onTaskListUpdate)window.onTaskListUpdate(%s);"
                % json.dumps(tasks, ensure_ascii=False))
        except Exception:
            pass

    def _set_phase_text(self, phase: str = None):
        """循环阶段单行状态（微信版 loop-text 对齐）：钉在会话头风扇条。

        节流：think/reply 阶段文本不变，仅在阶段切换时更新一次；
        tool 阶段文本带计数，每次工具调用都刷新。"""
        try:
            prev = getattr(self, "_agent_phase", None)
            if phase is not None:
                self._agent_phase = phase
            p = getattr(self, "_agent_phase", "think")
            if p == prev and p in ("reply", "think"):
                return
            if p == "tool":
                txt = "🔧 工具执行中 · 已调用 %d 次" % getattr(self, "_lw_task_tools", 0)
            elif p == "reply":
                txt = "✍️ 正在生成回复…"
            else:
                txt = "🤔 思考与规划中…"
            self._safe_run_js(
                "(function(){var b=document.getElementById('agentFanBar');"
                "if(b)b.style.display='flex';"
                "var t=document.getElementById('agentFanText');"
                "if(t)t.innerText=%s;})()" % json.dumps(txt, ensure_ascii=False))
        except Exception:
            pass

    def _on_agent_started(self, prompt_summary: str):
        """Agent 循环开始 — 在 UI 显示启动信息"""
        print(f"[Agent] 循环开始: {prompt_summary}")
        # ★ 状态行：对齐 CodeBuddy "等待模型响应..." 的可见状态字样
        self._emit_trace("status", text="正在思考与规划...")
        self.set_agent_state('working')
        # ★第361章: 会话框头部小风扇开始旋转（CSS 渲染，任务结束消失）
        self._safe_run_js("if(window.setAgentFan)window.setAgentFan(true);")
        # ★第362章修复: 任务级标志置位（三收口复位）—— busy 判定真源
        self._agent_task_active = True
        # ★ Lemon Work: 启动即弹任务列表卡 + 阶段状态（微信版对齐）
        self._lw_task_tools = 0
        self._lw_step_init()   # ★ v352: 任务拆解骨架（理解请求 → 语义步骤生长）
        self._set_phase_text("think")
        # ★ 第345章: trace run_start（新运行容器；重置工具栈/文本缓冲）
        if getattr(self, "_trace_v2", False):
            self._trace_tool_stack = []
            self._lw_round_tools = []   # ★ v350: 轮内工具明细复位
            self._trace_text_buf = None
            self._trace_sent = ""  # ★ 第350章: 重置已发送叙事累计
            self._trace_think_live = False  # ★ Lemon Work: 思考实时流标志复位
            self._emit_trace(
                "run_start",
                prompt=(prompt_summary or "")[:120],
                engine=getattr(self, "_current_agent_engine", "") or "",
                model=getattr(self, "_current_agent_model", "") or "",
            )
        else:
            self.pybridge.append_status_signal.emit(
                f"<span style='color:{Lemon.ACCENT_BLUE};'>Agent 启动工具调用循环...</span>"
            )

    def _check_stream_watchdog(self):
        """★392A-3: 流断看门狗（UI 侧 tick）—— 两档无输出流提示。

        驱动源: 既有 _js_flush_timer（150ms），Agent 执行期间不清队列也保持运行
        （禁新增轮询线程）。与引擎侧 stream_stalled 事件互补：引擎侧在阻塞读期间
        无事件源（事后上报），实时提示由本 tick 负责。
        档1 ≥90s: "⏳ 模型推理中（已等待 Ns，无输出流）" —— 区分正常推理慢；
        档2 ≥300s: "⚠ 连接可能挂起…" —— 与流式读超时 300s 兜底对齐。"""
        try:
            if not getattr(self, "_agent_watchdog_active", False):
                return
            now = time.time()
            base = getattr(self, "_agent_live_last_token_ts", None) \
                or getattr(self, "_agent_live_started_at", None) or now
            silent = now - base
            # 两档阈值与引擎同源（agent.watchdog_t1/t2，默认 90/300）
            t1, t2 = 90, 300
            try:
                from shared.config_manager import ConfigManager
                _cm = ConfigManager()
                t1 = max(5, int(_cm.get("agent.watchdog_t1", 90)))
                t2 = max(t1 + 5, int(_cm.get("agent.watchdog_t2", 300)))
            except Exception:
                pass
            tier = 2 if silent >= t2 else (1 if silent >= t1 else 0)
            prev = getattr(self, "_watchdog_tier", 0)
            if tier != prev or (tier and now - getattr(self, "_watchdog_last_emit", 0) >= 5):
                self._watchdog_tier = tier
                self._watchdog_last_emit = now
                if tier == 1:
                    text = f"⏳ 模型推理中（已等待 {int(silent)}s，无输出流）"
                elif tier == 2:
                    text = f"⚠ 连接可能挂起（已等待 {int(silent)}s 无输出流，可点「中断」停止）"
                else:
                    text = ""
                self._safe_run_js(
                    "if(window.setAgentStall)window.setAgentStall(%s);"
                    % json.dumps(text, ensure_ascii=False))
        except Exception:
            pass

    def _watchdog_reset_activity(self):
        """★392A-3: 有输出/真实 usage 到达 → 刷新静默起点并撤提示"""
        self._agent_live_last_token_ts = time.time()
        if getattr(self, "_watchdog_tier", 0) != 0:
            self._watchdog_tier = 0
            self._safe_run_js("if(window.setAgentStall)window.setAgentStall('');")

    def _on_agent_stream_token(self, token: str):
        """★ v3.64: 流式 token 到达 — 实时显示在右侧面板

        策略：
        - 首次 token 到达时调用 onStreamStart()（创建消息块）
        - 后续 token 调用 onStreamToken() 累积显示
        - 工具调用轮的 token 也会显示（让用户看到 Agent 思考过程）
        """
        try:
            if not getattr(self, "_agent_stream_active", False):
                # ★ 第345章: trace_v2 启用时旧流式块门控（防双显）
                if self._js_ready and not getattr(self, "_trace_v2", False):
                    self._safe_run_js("onStreamStart()")
                self._agent_stream_active = True
                self.set_agent_state('thinking')
            safe = token.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '')
            # ★ 第345章: trace_v2 启用时抑制旧流式块（防双重渲染；代码保留仅门控）
            if not getattr(self, "_trace_v2", False):
                self._safe_run_js(f"onStreamToken('{safe}')")
            # ★ 第345章: trace text_delta（缓冲合并发射）
            self._trace_text(token)
            # ★ Lemon Work: 阶段状态 → 回复中（微信版 loop-text 对齐）
            self._set_phase_text("reply")
            # ★392A-3: token 到达 → 刷新看门狗静默起点（撤两档提示）
            self._watchdog_reset_activity()
            # ★391A-3: 输出计数改由 usage_updated 真值信号驱动（原"每事件 +1"
            # 是事件数不是 token 数，分块流式下必然低估——假口径已废除）。
            # 此处仅负责推进 live 帧发射节流。
            self._emit_agent_status_live()
        except Exception as e:
            print(f"[Agent] 流式 token 显示失败: {e}")

    def _on_engine_usage_updated(self, usage: dict):
        """★391A-3: 引擎每轮真实 usage → live 真值槽（输入/输出/上下文峰值）"""
        try:
            self._agent_live_in_tok = int(usage.get("input_tokens") or 0)
            self._agent_live_out_tok = int(usage.get("output_tokens") or 0)
            self._agent_live_ctx_tok = int(usage.get("context_tokens") or 0)
            # ★392A-3: 轮末真实 usage 到达 = 活动信号（纯 tool_calls 轮无 token 也算）
            self._watchdog_reset_activity()
            self._emit_agent_status_live()
        except Exception:
            pass

    def _on_engine_stream_stalled(self, info: dict):
        """★392A-3: 引擎侧看门狗事件（token 到达/轮结束/异常点事后上报）→ trace 时间线"""
        try:
            tier = int(info.get("tier") or 0)
            silent = info.get("silent_seconds", 0)
            it = info.get("iteration", 0)
            where = info.get("where", "")
            text = ("模型推理中" if tier == 1 else "连接可能挂起")
            self._emit_trace("status", text=f"⏳ 第{it}轮无输出流 {silent}s（{text}·{where}）")
        except Exception:
            pass

    def _emit_agent_status_live(self, force: bool = False):
        """★389M-1: 运行中状态条实时帧（[轮] 口径）——耗时/工具/输出 tok 单调递增。

        复用 stream/token 事件触发（无轮询线程）；0.5s 节流；结束帧由
        _on_agent_finished 的 final_status（同源 result 真值）覆盖，保证终值==完成卡。
        ★391A-3: 输入/输出/上下文改由 usage_updated 真值槽驱动；final 帧后置
        _agent_live_finalized，迟到的 live 帧一律丢弃——终值==完成卡硬保证。
        """
        try:
            # ★391A-3: 终态拦截——final 帧之后的迟到 live 帧直接丢弃（防假值残留）
            if getattr(self, "_agent_live_finalized", False):
                return
            now = time.time()
            if not force and now - getattr(self, "_agent_live_last_emit", 0) < 0.5:
                return
            self._agent_live_last_emit = now
            _elapsed = round(now - getattr(self, "_agent_live_started_at", now), 1)
            # ★391A-1.3: 模型名带同源窗口标注（"(32k)"，读 ollama.num_ctx 键）
            _model_label = ""
            if getattr(self, "_agent_live_ctx_label", ""):
                _model_label = (getattr(self, "_current_agent_model", "") or "ollama") \
                    + self._agent_live_ctx_label
            _js = ("if(window.setStatusBarLive)window.setStatusBarLive("
                   "%d, null, '%s', null, %s, %d, '%s', %d);" % (
                       getattr(self, "_agent_live_tools", 0),
                       _model_label,
                       "null" if _elapsed is None else _elapsed,
                       getattr(self, "_agent_live_out_tok", 0),
                       "轮",
                       getattr(self, "_agent_live_in_tok", 0)))
            self._safe_run_js(_js)
        except Exception:
            pass

    def _ensure_stream_started_fallback(self):
        """★ v3.64: 兜底 — 3 秒内无 token 到达时强制触发 onStreamStart

        适用场景：纯工具调用轮（模型直接返回 tool_calls 无文本），
        UI 仍需进入流式状态以便后续显示工具调用卡片。
        """
        try:
            if not getattr(self, "_agent_stream_active", False):
                # ★ 第345章: trace_v2 启用时旧流式块门控（防双显）
                if self._js_ready and not getattr(self, "_trace_v2", False):
                    self._safe_run_js("onStreamStart()")
                    self._agent_stream_active = True
                elif getattr(self, "_trace_v2", False):
                    self._agent_stream_active = True
        except Exception as e:
            print(f"[Agent] 兜底 onStreamStart 失败: {e}")

    def _on_agent_tool_call_event(self, tool_info: dict):
        """Worker 完成后批量回传的工具调用信息（与 _on_engine_tool_call_made 互补）"""
        # 这里主要用作 Worker 完成后的兜底；实时显示由 _on_engine_tool_call_made 处理
        pass

    # ============================================================
    # ★ 第345章: TraceRenderer 统一事件通道（LEMON_TRACE_V2=1 启用）
    #   单通道 FIFO + 主线程 seq，取代 6 通道跨序；旧信号照发不误（保险丝）
    # ============================================================

    @staticmethod
    def _safe_truncate_html(html: str, limit: int) -> str:
        if len(html) <= limit:
            return html
        cut = html.rfind(">", 0, limit)
        if cut < 0:
            return html[:limit]
        truncated = html[:cut + 1]
        void_tags = frozenset(["br","hr","img","input","meta","link","area","base","col","embed","source","track","wbr"])
        stack = []
        i = 0
        while i < len(truncated):
            if truncated[i] == "<":
                j = truncated.find(">", i)
                if j < 0:
                    break
                tag = truncated[i+1:j].strip()
                if tag.endswith("/"):
                    pass
                else:
                    name = tag.split()[0].lower() if tag.split() else ""
                    if name not in void_tags and not name.startswith("!--") and not name.startswith("!"):
                        if not name.startswith("/"):
                            stack.append(name)
                        else:
                            cname = name[1:]
                            if stack and stack[-1] == cname:
                                stack.pop()
                i = j + 1
            else:
                i += 1
        for tag in reversed(stack):
            truncated += f"</{tag}>"
        return truncated

    def _emit_trace(self, kind: str, **fields):
        """发射一条有序 trace 事件到前端 TraceRenderer（未启用时零开销）"""
        if not getattr(self, "_trace_v2", False):
            return
        try:
            self._trace_seq = (getattr(self, "_trace_seq", 0) or 0) + 1
            ev = {"seq": self._trace_seq, "ts": int(time.time() * 1000), "kind": kind}
            ev.update(fields)
            self._safe_run_js(
                f"window.TraceRenderer&&TraceRenderer.consume({json.dumps(ev, ensure_ascii=False)})"
            )
        except Exception:
            pass

    def _emit_status_safe(self, kind: str, payload: dict):
        """★ T367.4: 串行化状态发射 — 同 kind 50ms 内合并(保留最新), 最终原子发射"""
        with self._status_emit_lock:
            self._status_emit_pending[kind] = payload
            now = time.time()
            if now - self._status_emit_last_ts < 0.05:
                return
            self._status_emit_last_ts = now
            to_emit = dict(self._status_emit_pending)
            self._status_emit_pending.clear()
        for _kind, _payload in to_emit.items():
            try:
                if _kind == "agent_status":
                    self.pybridge.agent_status_signal.emit(json.dumps(_payload, ensure_ascii=False))
                elif _kind == "bg_task":
                    self.pybridge.background_task_signal.emit(json.dumps(_payload, ensure_ascii=False))
                elif _kind == "final_status":
                    _payload["_atomic"] = True
                    self.pybridge.agent_status_signal.emit(json.dumps(_payload, ensure_ascii=False))
            except Exception:
                pass

    @staticmethod
    def _trace_classify(name: str) -> str:
        """工具类型归类（读取/写入/检索/命令/其他）——与 _build_timeline_event 同规则"""
        n = (name or "").split(".")[-1].lower()
        if any(k in n for k in ("read", "view", "get_file", "cat")):
            return "read"
        if any(k in n for k in ("edit", "write", "create", "replace", "patch")):
            return "write"
        if any(k in n for k in ("search", "grep", "find", "lookup")):
            return "search"
        if any(k in n for k in ("exec", "run", "shell", "terminal", "command", "install")):
            return "command"
        return "tool"

    @staticmethod
    def _trace_arg_preview(args) -> str:
        """参数摘要：取第一个字符串值的标量字段，截断 48 字符"""
        try:
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    return str(args)[:48]
            if isinstance(args, dict):
                for key in ("file_path", "path", "query", "pattern", "command", "url", "keyword", "content"):
                    v = args.get(key)
                    if isinstance(v, str) and v:
                        return v.replace("\n", " ")[:48]
                for v in args.values():
                    if isinstance(v, str) and v:
                        return v.replace("\n", " ")[:48]
            return ""
        except Exception:
            return ""

    @staticmethod
    def _trace_lines(args) -> str:
        """行号范围摘要（对标 Trae: main.py#L438-L446）——与 _build_timeline_event 同规则"""
        try:
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    return ""
            if not isinstance(args, dict):
                return ""
            sl = args.get("start_line") or args.get("line") or args.get("startLine") or args.get("offset")
            el = args.get("end_line") or args.get("endLine")
            if sl is None:
                return ""
            s = f"L{sl}"
            if el is not None and el != sl:
                s += f"-{el}"
            return s
        except Exception:
            return ""

    @classmethod
    def _trace_lines_smart(cls, name, args) -> str:
        """行号摘要增强：读取类整文件读取 → 'L1-End'（对标 CodeBuddy: 读取 main.py L1-End）"""
        lines = cls._trace_lines(args)
        if lines:
            return lines
        n = (name or "").split(".")[-1].lower()
        if not any(k in n for k in ("read", "view", "get_file", "cat")):
            return ""
        try:
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    return ""
            if isinstance(args, dict) and any(
                args.get(k) for k in ("file_path", "filepath", "path", "filename", "file", "target_file")
            ):
                return "L1-End"
        except Exception:
            pass
        return ""

    @staticmethod
    def _trace_err(result, rejected: bool = False) -> str:
        """失败原因短摘要（对标 CodeBuddy: （文件过大，无法一次读取））——仅在 ok=False 时使用"""
        try:
            s = str(result or "").strip()
            if not s:
                return "执行失败"
            low = s.lower()
            for pats, msg in (
                (("文件过大", "too large", "文件太长", "exceeds", "无法一次读取"), "文件过大"),
                (("超时", "timeout", "timed out"), "执行超时"),
                (("权限", "permission", "access denied", "拒绝访问"), "无权限"),
                (("不存在", "not found", "no such file", "无此文件"), "目标不存在"),
                (("拒绝", "denied", "rejected"), "被拒绝"),
                (("无效", "invalid", "无法解析", "failed to parse"), "输入无效"),
                (("编码", "encoding", "unicode", "decode"), "编码错误"),
            ):
                if any(p in s or p in low for p in pats):
                    return msg
            line = next((ln.strip() for ln in s.splitlines() if ln.strip()), "")
            return (line[:40] or "执行失败")
        except Exception:
            return "执行失败"

    def _trace_text(self, token: str):
        """流式文本缓冲：160字符或150ms 阈值合并发射（防 JS 调用洪泛）"""
        if not getattr(self, "_trace_v2", False):
            return
        buf = getattr(self, "_trace_text_buf", None)
        if buf is None:
            buf = self._trace_text_buf = {"text": ""}
        buf["text"] += token
        now = time.time()
        if len(buf["text"]) >= 160 or (now - getattr(self, "_trace_text_last", 0)) >= 0.15:
            self._trace_flush_text()

    def _trace_flush_text(self):
        """把缓冲中的流式文本作为 text_delta 发出（tool_start/final 前必须先调，保序）"""
        buf = getattr(self, "_trace_text_buf", None)
        if buf and buf["text"]:
            self._emit_trace("text_delta", text=buf["text"])
            # ★ 第350章: 累计已发送叙事（供 final Python 端去重）
            self._trace_sent = (getattr(self, "_trace_sent", "") or "") + buf["text"]
            buf["text"] = ""
        self._trace_text_last = time.time()

    def _on_engine_tool_call_started(self, tool_info: dict):
        """★ 第345章: 工具开始执行 → 卡片实时出现+转圈（'3秒可打断'体验前提）"""
        try:
            if not getattr(self, "_trace_v2", False):
                return
            name = (tool_info.get("name", "") or "").split(".")[-1]
            self._trace_flush_text()  # 先封口未完成的叙事节点，保时序
            self._trace_tool_stack.append({"name": name, "t0": time.time()})
            # ★ v352: 真拆解 —— 工具开始 → 语义步骤生长（同名续用/异名新增）
            self._lw_step_start(name)
            # ★ Lemon Work: 阶段状态 → 工具执行中（微信版 loop-text 对齐）
            self._set_phase_text("tool")
            self._emit_trace(
                "tool_start",
                name=name,
                ttype=self._trace_classify(name),
                arg=self._trace_arg_preview(tool_info.get("arguments", {})),
                lines=self._trace_lines_smart(name, tool_info.get("arguments", {})),
            )
        except Exception:
            pass

    def _on_engine_tool_call_made(self, tool_info: dict):
        """★ v3.63 / ★ v4.1.15: EngineManager.tool_call_made 信号处理器（实时）

        在 agent_chat 循环中，每次工具调用执行完成后立即触发，
        实现 UI 实时展示 Agent 中间过程。

        ★ v4.1.15: 从"空泛工具块"升级为"执行轨迹流（Timeline）事件"——
        按工具类型归为 读取/写入/检索/命令/其他 五类，携带文件路径、
        行号范围与 diff stat，供右侧栏渲染 CodeBuddy 式时间线。
        """
        try:
            # ★ 381B-5: 编排进度卡 — 检测 guided_step 信号，渲染专用进度卡
            if tool_info.get("guided_step"):
                self._render_guided_step_card(tool_info)
                return  # 编排进度卡走独立渲染路径，不进普通工具时间线

            name = tool_info.get("name", "(未知工具)")
            args = tool_info.get("arguments", {})
            success = tool_info.get("success", False)
            # ★389M-1: 工具计数递增 + 状态条 live 帧（运行中实时递增）
            self._agent_live_tools = getattr(self, "_agent_live_tools", 0) + 1
            self._emit_agent_status_live(force=True)
            # ★ Lemon Work: 任务卡动态刷新 + 阶段计数（微信版对齐）
            self._lw_task_tools = getattr(self, "_lw_task_tools", 0) + 1
            # ★ v352: 真拆解 —— 工具完成落语义步骤状态（查询余额×3 等）
            self._lw_step_done(name, bool(success))
            # ★ v356: 银行操作台跟随跳动 —— 业务完成自动导航页面
            self._bank_follow_navigate(name, bool(success))
            self._push_task_card()
            self._set_phase_text("tool")
            # ★ v350: 轮内工具明细累积（_on_agent_iteration 时打包为 narrative 时间线）
            if not hasattr(self, "_lw_round_tools"):
                self._lw_round_tools = []
            self._lw_round_tools.append({
                "name": name.split(".")[-1],
                "ok": bool(success),
                "ms": 0,
            })
            result_preview = str(tool_info.get("result", ""))[:200]
            # ★ 第345章: trace tool_end — 卡片从转圈→✓/✗ + 耗时（与 started 按 name 配对）
            if getattr(self, "_trace_v2", False):
                try:
                    short_name = name.split(".")[-1]
                    dur_ms = 0
                    stack = getattr(self, "_trace_tool_stack", [])
                    for i in range(len(stack) - 1, -1, -1):
                        if stack[i].get("name") == short_name:
                            dur_ms = int((time.time() - stack[i]["t0"]) * 1000)
                            stack.pop(i)
                            break
                    self._trace_flush_text()
                    self._emit_trace(
                        "tool_end",
                        name=short_name,
                        ttype=self._trace_classify(name),
                        arg=self._trace_arg_preview(args),
                        lines=self._trace_lines_smart(name, args),
                        ok=bool(success),
                        err=("" if (success or tool_info.get("rejected")) else self._trace_err(tool_info.get("result"))),
                        ms=dur_ms,
                        result=str(tool_info.get("result", ""))[:1200],
                        rejected=bool(tool_info.get("rejected")),
                    )
                except Exception:
                    pass
            if not isinstance(args, dict):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            # ★第360章: 文件产出卡 — write/edit 类工具成功后在消息流底部显示文件卡
            # （对标微信版"生成文件并在下方显示文件卡 + 导出"体验）
            if success and name in ("write_file", "edit_file", "multi_edit",
                                    "file_write", "file_edit", "file_append"):
                self._emit_file_card(name, args)
            event = self._build_timeline_event(name, args, success, result_preview)
            # ★ 第345章: trace_v2 启用时门控旧时间线信号（消除"读取读取"重复列表；TraceRenderer 呈现）
            if not getattr(self, "_trace_v2", False):
                self.pybridge.append_timeline_signal.emit(json.dumps(event, ensure_ascii=False))
            # ★ v5.1: P-C 累积事件，供 finished 时生成「任务步骤列表」
            if not hasattr(self, "_timeline_events"):
                self._timeline_events = []
            self._timeline_events.append(event)
            # ★ v5.3 修复 F2: 每条事件 step +1，供 agentStepsPanel 头部"X 步"显示
            try:
                self._current_agent_iter = (getattr(self, "_current_agent_iter", 0) or 0) + 1
            except Exception:
                pass
            # ★ v5.1: 运行期间实时增量 emit steps（任务B：步骤列表逐条出现，白盒联动）
            # ★ 第348章: 恢复发射 — 底部"思考过程"面板是独立视图（对标 Trae 工具面板跟随），非重复
            try:
                _live = json.dumps({
                    "prompt": getattr(self, "_current_agent_prompt", "") or "",
                    "engine": getattr(self, "_current_agent_engine", "") or "运行中",
                    "model": getattr(self, "_current_agent_model", "") or "—",
                    "iterations": getattr(self, "_current_agent_iter", 0),
                    "total_time": 0,
                    "success": True,
                    "live": True,
                    "steps": self._timeline_events,
                }, ensure_ascii=False)
                self.pybridge.append_steps_signal.emit(_live)
            except Exception:
                pass
        except Exception as e:
            print(f"[Agent] 工具调用 UI 更新失败: {e}")
            # 兜底：降级为旧工具块
            try:
                html = (
                    f"<div style='margin:6px 0;padding:8px;border-left:3px solid {Lemon.ACCENT_BLUE};"
                    f"background:rgba(74,158,255,0.05);border-radius:4px;'>"
                    f"<div style='color:{Lemon.BRAND_ORANGE_LIGHT};font-size:12px;'><svg width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round' style='vertical-align:-2px'><path d='M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z'/></svg> 工具调用: <b>{name}</b></div></div>"
                )
                self.pybridge.append_tool_signal.emit(html)
            except Exception:
                pass

    # ============================================================
    # ★第360章: 文件产出卡（对标微信版"生成文件→下方文件卡→打开/导出"）
    # ============================================================
    def _emit_file_card(self, tool_name: str, args: dict):
        """write/edit 类工具成功后推送文件卡给前端渲染。

        载荷: {name(文件名), path(解析后绝对路径), size(字节), action(created|edited)}
        前端按钮回传 __file_open__ / __file_export__ → _handle_file_open/_export。
        """
        try:
            path = str(args.get("file_path") or args.get("path") or "").strip()
            if not path:
                return
            path = self._resolve_agent_file(path)
            size = 0
            try:
                size = os.path.getsize(path)
            except Exception:
                pass
            payload = json.dumps({
                "name": os.path.basename(path) or path,
                "path": path,
                "size": size,
                "action": "edited" if tool_name in ("edit_file", "multi_edit", "file_edit", "file_append") else "created",
            }, ensure_ascii=False)
            self.pybridge.eval_js_signal.emit(
                "if(typeof onFileCard==='function')onFileCard(" + payload + ");")
        except Exception as e:
            print(f"[MIMO Panel] 文件卡推送失败: {e}")

    def _resolve_agent_file(self, raw: str) -> str:
        """文件卡路径解析 — 绝对路径优先；相对路径依次尝试 cwd / project_path。"""
        p = (raw or "").strip().strip('"')
        if not p:
            return ""
        cands = [p]
        if not os.path.isabs(p):
            try:
                cands.append(os.path.abspath(p))
            except Exception:
                pass
            root = str(getattr(self, "project_path", "") or "")
            if root:
                cands.append(os.path.join(root, p))
        for c in cands:
            try:
                if c and os.path.isfile(c):
                    return c
            except Exception:
                continue
        return cands[0]

    def _handle_file_open(self, raw: str):
        """文件卡「打开」— 调系统默认程序打开。"""
        try:
            import subprocess
            path = self._resolve_agent_file(raw)
            if path and os.path.isfile(path):
                if os.name == "nt":
                    os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
                else:
                    subprocess.Popen(["xdg-open", path])
                self.pybridge.eval_js_signal.emit(
                    "if(typeof showToast==='function')showToast('已打开: "
                    + json.dumps(os.path.basename(path), ensure_ascii=False)[1:-1] + "');")
            else:
                self.pybridge.eval_js_signal.emit(
                    "if(typeof showToast==='function')showToast('文件不存在: "
                    + json.dumps(str(raw), ensure_ascii=False)[1:-1] + "');")
        except Exception as e:
            print(f"[MIMO Panel] 打开文件失败: {e}")

    def _handle_file_export(self, raw: str):
        """文件卡「导出」— 另存为对话框 + 复制。"""
        try:
            import shutil
            from PyQt5.QtWidgets import QFileDialog
            path = self._resolve_agent_file(raw)
            if not path or not os.path.isfile(path):
                self.pybridge.eval_js_signal.emit(
                    "if(typeof showToast==='function')showToast('文件不存在，无法导出');")
                return
            dest, _f = QFileDialog.getSaveFileName(self, "导出文件", os.path.basename(path))
            if not dest:
                return
            shutil.copyfile(path, dest)
            self.pybridge.eval_js_signal.emit(
                "if(typeof showToast==='function')showToast('已导出到 "
                + json.dumps(dest, ensure_ascii=False)[1:-1] + "');")
        except Exception as e:
            print(f"[MIMO Panel] 导出文件失败: {e}")

    def _render_guided_step_card(self, tool_info: dict):
        """★ 381B-5: 编排进度卡 — 显示编排模式逐步进度、判据结果、needs_escalation 提示"""
        try:
            step_id = tool_info.get("step_id", "?")
            step_idx = tool_info.get("step_idx", 0)
            step_total = tool_info.get("step_total", 0)
            step_goal = tool_info.get("step_goal", "")
            tool_used = tool_info.get("tool_used", "")
            criterion_passed = tool_info.get("criterion_passed", False)
            needs_escalation = tool_info.get("needs_escalation", False)

            _GREEN = "#27ae60"
            _RED = "#e74c3c"
            _ACCENT = Lemon.ACCENT_BLUE if hasattr(self, '_theme') else "#4a9eff"
            _BG_PASS = "rgba(39,174,96,0.06)"
            _BG_FAIL = "rgba(231,76,60,0.06)"

            _color = _GREEN if criterion_passed else _RED
            _bg = _BG_PASS if criterion_passed else _BG_FAIL
            _icon = "✓" if criterion_passed else "✗"
            _escalation_html = ""
            if needs_escalation:
                _escalation_html = (
                    f"<div style='margin-top:4px;padding:4px 8px;background:rgba(231,76,60,0.1);"
                    f"border-radius:3px;color:{_RED};font-size:11px;'>"
                    f"⚠ 该步建议切换大模型体系</div>"
                )

            html = (
                f"<div style='margin:6px 0;padding:8px 12px;border-left:3px solid {_color};"
                f"background:{_bg};border-radius:4px;'>"
                f"<div style='color:{_ACCENT};font-size:12px;font-weight:600;'>"
                f"编排模式 第{step_idx+1}/{step_total}步 · <span style='color:{_color}'>{_icon}</span></div>"
                f"<div style='color:#ccc;font-size:12px;margin-top:2px;'>目标: {step_goal}</div>"
                f"<div style='color:#aaa;font-size:11px;margin-top:1px;'>工具: {tool_used} · 判据结果(<span style='color:{_color}'>{_icon}</span>)</div>"
                f"{_escalation_html}"
                f"</div>"
            )
            self.pybridge.append_tool_signal.emit(html)

            # 同时 emit trace 事件（让 TraceRenderer 也能呈现）
            if getattr(self, "_trace_v2", False):
                self._emit_trace(
                    "tool_end",
                    name=f"[编排] {step_id}",
                    ttype="command",
                    arg=step_goal[:60],
                    lines="",
                    ok=criterion_passed,
                    err=("" if criterion_passed else "判据未通过"),
                    ms=0,
                    result=f"第{step_idx+1}/{step_total}步 {'✓' if criterion_passed else '✗'}",
                    rejected=False,
                )
        except Exception as e:
            print(f"[381B-5] 编排进度卡渲染失败: {e}")

    def _build_timeline_event(self, name, args, success, result_preview):
        """★ v4.1.15: 把一次工具调用构造成 Timeline 事件

        分类规则（借鉴 CodeBuddy 时间线）：
        - 读取类：read_file / read_section / view / get_file_content → type=read
        - 写入类：edit_file / write_file / create_file / replace_in_file → type=write
        - 检索类：search / grep / find / search_content → type=search
        - 命令类：execute_command / run / shell / terminal → type=command
        - 其他：type=tool
        """
        # 统一取工具名（去掉命名空间前缀）
        tool_name = (name or "").split(".")[-1].lower()
        event_type = "tool"
        if any(k in tool_name for k in ("read", "view", "get_file", "read_section", "cat")):
            event_type = "read"
        elif any(k in tool_name for k in ("edit", "write", "create", "replace", "insert", "patch", "append")):
            event_type = "write"
        elif any(k in tool_name for k in ("search", "grep", "find", "lookup")):
            event_type = "search"
        elif any(k in tool_name for k in ("exec", "run", "shell", "terminal", "command", "install")):
            event_type = "command"

        # 提取文件路径（宽容匹配多种参数键）
        file_path = ""
        for key in ("file_path", "filepath", "path", "filename", "file", "target_file"):
            v = args.get(key)
            if isinstance(v, str) and v:
                file_path = v
                break

        # 提取行号范围（start_line/end_line/offset/limit）
        lines = ""
        try:
            sl = args.get("start_line") or args.get("line") or args.get("startLine") or args.get("offset")
            el = args.get("end_line") or args.get("endLine")
            if sl is not None:
                lines = f"L{sl}"
                if el is not None and el != sl:
                    lines += f"-{el}"
        except Exception:
            lines = ""

        # 计算 diff stat（写入类：尝试从 result 解析 +行/-行）
        stat = ""
        if event_type == "write":
            stat = self._compute_diff_stat(result_preview)

        # ★ v5.1: 写入/编辑类工具 → 携带实际代码正文，供右侧栏渲染可折叠代码卡片（对标 TRAE diff viewer）
        code = ""
        code_lang = ""
        code_mode = "code"  # "code" 纯代码 | "diff" 旧→新对比
        if event_type == "write":
            # edit 类优先构造真实 diff（旧→新），更贴近 TRAE 的变更对比视图
            old_s = args.get("old_string") or args.get("old_content") or ""
            new_s = args.get("new_string") or args.get("new_content") or args.get("content") or args.get("code") or ""
            if isinstance(old_s, str) and old_s.strip() and isinstance(new_s, str) and new_s.strip():
                code = self._build_diff_block(old_s, new_s)
                code_mode = "diff"
                code_lang = self._infer_lang_from_path(file_path, new_s)
            else:
                raw_content = new_s if isinstance(new_s, str) else ""
                if not raw_content.strip():
                    raw_content = args.get("content") or args.get("new_content") or args.get("code") or ""
                if isinstance(raw_content, str) and raw_content.strip():
                    # 截断超长代码（避免 UI 卡顿），保留前 4000 字符
                    code = raw_content[:4000]
                    code_lang = self._infer_lang_from_path(file_path, raw_content)

        # 参数摘要（截断）
        args_str = json.dumps(args, ensure_ascii=False)
        if len(args_str) > 120:
            args_str = args_str[:120] + "..."
        # 跳过超长参数（如 base64 图片）
        if len(args_str) > 300:
            args_str = "..."

        return {
            "type": event_type,
            "tool": name,
            "title": self._timeline_title(event_type, tool_name, file_path),
            "file": file_path,
            "lines": lines,
            "stat": stat,
            "success": bool(success),
            "detail": args_str,
            "result": result_preview[:120] if result_preview else "",
            # ★ v5.1: 代码正文（仅写入类携带），前端据此渲染代码卡片
            "code": code,
            "lang": code_lang,
            "code_mode": code_mode,
        }

    @staticmethod
    def _timeline_title(event_type, tool_name, file_path):
        """生成时间线条目标题"""
        base = file_path or tool_name
        if event_type == "read":
            return f"读取 {base}"
        if event_type == "write":
            return f"修改 {base}"
        if event_type == "search":
            return f"检索 {base}"
        if event_type == "command":
            return f"执行 {base}"
        return f"工具 {base}"

    @staticmethod
    def _compute_diff_stat(result_preview):
        """从写入工具的结果文本中解析 diff 统计（+N -M），解析不到返回空"""
        try:
            text = str(result_preview or "")
            plus = 0
            minus = 0
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("+") and not s.startswith("+++"):
                    plus += 1
                elif s.startswith("-") and not s.startswith("---"):
                    minus += 1
            if plus or minus:
                return f"+{plus} -{minus}"
        except Exception:
            pass
        return ""

    @staticmethod
    def _build_diff_block(old_s: str, new_s: str) -> str:
        """★ v5.1: 把 edit 的旧/新内容拼成 unified-diff 风格文本（截断 4000 字符）

        前端对 code_mode=="diff" 渲染成红减绿加对比视图，对标 TRAE 代码变更卡。
        """
        try:
            old_lines = old_s.splitlines()
            new_lines = new_s.splitlines()
            out = []
            max_len = max(len(old_lines), len(new_lines))
            for i in range(max_len):
                if i < len(old_lines):
                    out.append("- " + old_lines[i])
                if i < len(new_lines):
                    out.append("+ " + new_lines[i])
            text = "\n".join(out)
            return text[:4000]
        except Exception:
            return (new_s or "")[:4000]

    @staticmethod
    def _infer_lang_from_path(file_path: str, content: str = "") -> str:
        """★ v5.1: 从文件路径后缀推断代码语言（用于前端语法高亮）"""
        ext_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "typescript",
            ".jsx": "javascript", ".html": "html", ".htm": "html", ".css": "css",
            ".json": "json", ".md": "markdown", ".sh": "bash", ".bash": "bash",
            ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
            ".java": "java", ".go": "go", ".rs": "rust", ".rb": "ruby",
            ".sql": "sql", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
            ".xml": "xml", ".vue": "html", ".php": "php", ".kt": "kotlin",
            ".swift": "swift", ".r": "r", ".ipynb": "json",
        }
        if file_path:
            for ext, lang in ext_map.items():
                if file_path.lower().endswith(ext):
                    return lang
        # 无后缀时按内容启发式猜测
        if content:
            stripped = content.lstrip()
            if stripped.startswith("{") or stripped.startswith("["):
                return "json"
            if "def " in content or "import " in content and "print(" in content:
                return "python"
            if "function " in content or "const " in content or "=>" in content:
                return "javascript"
            if "<html" in content.lower() or "<div" in content.lower():
                return "html"
        return ""

    # ==================== ★ v4.1.24: 合并模式跨面板持久化（与经典面板共享 JSON） ====================
    def _wt_merge_mode_cfg_path(self):
        import os
        d = os.path.join(os.getcwd(), "data")
        return os.path.join(d, "worktree_actor_config.json")

    def _save_wt_merge_mode_file(self, mode: str) -> None:
        import os, json
        try:
            d = os.path.dirname(self._wt_merge_mode_cfg_path())
            os.makedirs(d, exist_ok=True)
            with open(self._wt_merge_mode_cfg_path(), "w", encoding="utf-8") as f:
                json.dump({"merge_mode": mode}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_wt_merge_mode_file(self):
        import os, json
        try:
            with open(self._wt_merge_mode_cfg_path(), "r", encoding="utf-8") as f:
                v = json.load(f).get("merge_mode")
                return v if v in ("auto", "keep") else None
        except Exception:
            return None

    def _handle_worktree_action(self, sub: str, args: list):
        """★ v4.1.17: Worktree 隔离操作处理

        子命令:
        - create <task_desc>: 创建隔离 worktree
        - list: 列出所有 worktree
        - status <path>: 查看某个 worktree 变更状态
        - diff <path>: 获取 worktree diff
        - remove <path> [force]: 清理 worktree
        - merge_back <path>: 合并回主分支
        """
        try:
            # 惰性导入 + 初始化（按项目根目录）
            try:
                from core.worktree_manager import WorktreeManager
            except ImportError:
                from standard_mode.core.worktree_manager import WorktreeManager

            if getattr(self, '_worktree_mgr', None) is None:
                # 项目根 = engine_manager 的配置目录的上级
                import os
                cfg_dir = getattr(self._engine_manager, '_config_dir', None) or os.getcwd()
                proj_root = os.path.dirname(cfg_dir) if os.path.basename(cfg_dir) == 'config' else cfg_dir
                # 优先用当前工作目录作为项目根
                self._worktree_mgr = WorktreeManager(os.getcwd())
            mgr = self._worktree_mgr

            if sub == 'create':
                desc = args[0] if args else "agent-task"
                ok, info = mgr.create_for_agent(desc)
                if ok:
                    self._emit_worktree_timeline("create", desc, info.get("branch", ""))
                    return {"success": True, "path": info["path"], "branch": info["branch"], "base": info["base"]}
                return {"success": False, "error": info.get("error", "创建失败")}

            if sub == 'list':
                wts = mgr.list()
                return {"success": True, "worktrees": wts}

            if sub == 'status' and args:
                return {"success": True, "status": mgr.status(args[0])}

            if sub == 'diff' and args:
                return {"success": True, "diff": mgr.diff(args[0])[:4000]}

            if sub == 'remove' and args:
                force = len(args) > 1 and args[1] == 'force'
                ok, msg = mgr.remove(args[0], force=force)
                if ok:
                    self._emit_worktree_timeline("remove", args[0], "")
                return {"success": ok, "message": msg}

            if sub == 'merge_back' and args:
                ok, msg = mgr.merge_back(args[0])
                if ok:
                    self._emit_worktree_timeline("merge", args[0], "")
                return {"success": ok, "message": msg}

            # ★ v4.1.20: Worktree × Actor 打通（peer 绑隔离目录）— 前端 worktreeAction 触发
            if sub == 'actor_run':
                return self._handle_worktree_actor(args)

            # ★ v4.1.24: 合并模式跨面板持久化（与经典面板共享 data/worktree_actor_config.json）
            if sub == 'save_merge_mode' and args:
                mode = args[0] if args[0] in ("auto", "keep") else "auto"
                self._save_wt_merge_mode_file(mode)
                return {"success": True}

            if sub == 'get_merge_mode':
                return {"success": True, "merge_mode": self._load_wt_merge_mode_file()}

            return {"success": False, "error": f"未知 worktree 子命令: {sub}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_worktree_actor(self, args):
        """★ v4.1.20: Worktree × Actor 打通 — 为每个子 Agent 创建独立 worktree 并并行执行

        前端传入 tasks JSON 字符串: [{"role","title","prompt"}, ...]
        每个子 Agent 在独立 Git worktree 目录（peer + cwd 隔离）并行；worktree 创建
        失败时降级为普通并行。引擎可用时真实调用，否则回退模拟。
        """
        import json as _json
        import os
        raw = args[0] if args else "[]"
        try:
            tasks = _json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            tasks = []
        if not isinstance(tasks, list) or not tasks:
            tasks = [
                {"role": "架构师", "title": "分析 Python Agent 模块划分",
                 "prompt": "请分析一个 Python Agent 系统的模块划分原则，不超过80字"},
                {"role": "审查员", "title": "列出代码审查风险",
                 "prompt": "请列出代码审查中最常见的5个风险点，不超过80字"},
                {"role": "写手", "title": "总结并行价值",
                 "prompt": "请用一句话总结为什么 Agent 需要并行执行能力，不超过60字"},
            ]
        try:
            from shared.worktree_actor import WorktreeActorCoordinator
            from shared.actor_system import ActorSystem
        except Exception as e:
            return {"success": False, "error": f"WorktreeActor 加载失败: {e}"}

        system = ActorSystem()
        coord = WorktreeActorCoordinator(project_root=os.getcwd(), actor_system=system)
        jobs = []
        for i, t in enumerate(tasks):
            role = t.get("role", "worker")
            prompt = t.get("prompt", t.get("title", ""))
            jobs.append({
                "agent_type": role,
                "task": f"task-{i + 1}",
                "title": t.get("title", f"agent-{role}"),
                "detail": prompt,
                "description": f"{role}: {prompt[:30]}...",
                "task_fn": self._make_worktree_actor_task_fn(role, prompt),
            })
        # ★ v4.1.21: 合并模式可选 — 'keep' 仅隔离不合并（保留供人工审阅），'auto' 跑完自动合并
        merge_mode = args[1] if len(args) > 1 else "auto"
        if merge_mode not in ("auto", "keep"):
            merge_mode = "auto"
        results, worktrees = coord.run(jobs, use_worktree=True, timeout_ms=120000)
        merge_report = []
        for w in worktrees:
            self._emit_worktree_timeline("create", w.get("branch", ""), w.get("branch", ""))
        if merge_mode == "auto" and worktrees:
            merge_report = coord.merge_all_back(worktrees)
            for w in worktrees:
                self._emit_worktree_timeline("merge", w.get("branch", ""), w.get("branch", ""))
        out = []
        for r in results:
            out.append({
                "actor_id": r.actor_id,
                "outcome": r.outcome,
                "result": (r.result or "")[:500],
                "error": r.error,
                "timed_out": r.timed_out,
            })
        return {
            "success": True,
            "results": out,
            "worktrees": [{"path": w.get("path"), "branch": w.get("branch")} for w in worktrees],
            "merge_report": merge_report,
            "merge_mode": merge_mode,
        }

    def _make_worktree_actor_task_fn(self, role, prompt):
        """★ v4.1.20: 真实引擎调用 task_fn（get_engine_manager → ollama.generate）"""
        def _run():
            try:
                from shared.engine_manager import get_engine_manager
                em = get_engine_manager()
                engine = em.get_engine("ollama") if em else None
                if engine is None:
                    return f"[模拟] {role}: {prompt[:40]}..."
                return f"[{role}] {engine.generate(prompt)}"
            except Exception as e:  # noqa: BLE001
                return f"[引擎错误] {role}: {e}"
        return _run

    def _emit_worktree_timeline(self, sub: str, target: str, branch: str):
        """★ v4.1.17: 把 worktree 隔离操作发成 Timeline 事件（紫色隔离操作）"""
        try:
            labels = {"create": "创建隔离工作区", "merge": "合并回主分支", "remove": "清理隔离工作区"}
            title = labels.get(sub, f"Worktree {sub}")
            if branch:
                title += f" ({branch})"
            event = {
                "type": "worktree",
                "tool": f"worktree_{sub}",
                "title": title,
                "file": target,
                "lines": "",
                "stat": "",
                "success": True,
                "detail": target,
                "result": "",
                "worktree": True,
            }
            self.pybridge.append_timeline_signal.emit(json.dumps(event, ensure_ascii=False))
        except Exception:
            pass
        except Exception as e:
            return {"success": False, "error": f"worktree 操作失败: {e}"}

    def _on_agent_finished(self, result: dict):
        """Agent 循环完成 — 输出最终回复"""
        try:
            # ★392A-3: 看门狗收口（停 tick、撤两档提示）
            self._agent_watchdog_active = False
            self._watchdog_tier = 0
            self._safe_run_js("if(window.setAgentStall)window.setAgentStall('');")
            # ★第361章: 风扇停止（任务结束消失）
            self._safe_run_js("if(window.setAgentFan)window.setAgentFan(false);")
            # ★ Lemon Work: 任务卡收口 —— 三步全部勾完（微信版 plan-card 对齐）
            self._push_task_card(final=True)
            self._set_phase_text("reply")
            # ★第362章: 收口续跑 —— 延迟出队下一条排队消息（等 worker 线程退出）
            self._agent_task_active = False
            # ★第362章修复: finished 收口必须清 worker 引用（与 cancel/error 对齐）。
            #   否则 worker 若在收尾（轨迹落盘等）超过 600ms，_agent_busy() 的
            #   isRunning 分支会挡住出队且无重试 → 队列永久卡死（用户实测
            #   "发消息无响应"的根因）。
            self._current_agent_worker = None
            QTimer.singleShot(600, self._dequeue_next_message)
            content = result.get("content", "(Agent 无输出)")
            print(f"[DIAG] _on_agent_finished: content_len={len(content)}, _agent_stream_active={getattr(self, '_agent_stream_active', False)}, _js_ready={self._js_ready}")
            iterations = result.get("iterations", 0)
            tool_calls_made = result.get("tool_calls_made", [])
            total_time = result.get("total_time", 0)
            engine = result.get("engine", "?")
            model = result.get("model", "?")

            # ★ v3.72: Token 统计
            input_tokens = result.get("input_tokens", 0)
            output_tokens = result.get("output_tokens", 0)
            context_tokens = result.get("context_tokens", 0)
            cost = result.get("cost", 0.0)
            token_info = result.get("token_info", "")

            print(f"[Agent] 循环完成: {iterations} 轮, {len(tool_calls_made)} 次工具调用, {total_time:.2f}s")
            if token_info:
                print(f"[Agent] Token: {token_info}")

            # ★ v3.68: 保存对话上下文（user/assistant 消息对）
            # 让下次 agent_chat 能引用历史（如"刚才那个文件"）
            user_prompt = getattr(self, "_current_agent_prompt", "")
            if user_prompt and content and not result.get("error"):
                self._conversation_context.append({"role": "user", "content": user_prompt})
                # ★第423章: 上下文瘦身 —— 用户实测（415~421 后）：10 步长验收场景下
                #   assistant 历史 2000 字×10 轮 + 90 工具定义同时入栈，deepseek 输出
                #   退化成 DSML 文本式调用（"失忆/迷失"的直接诱因）。
                #   处理：剥代码块/表格行/连续空行 + 截断 2000→700 字——
                #   历史只需保留"做过什么"的梗概，无需携带完整排版。
                try:
                    import re as _re_ctx
                    _clean = _re_ctx.sub(r"```.*?```", "〔代码块〕", content, flags=_re_ctx.S)
                    _clean = _re_ctx.sub(r"^\|.*\|$", "", _clean, flags=_re_ctx.M)
                    _clean = _re_ctx.sub(r"\n{2,}", "\n", _clean)
                except Exception:
                    _clean = content
                assistant_content = _clean[:700] if len(_clean) > 700 else _clean
                self._conversation_context.append({"role": "assistant", "content": assistant_content})
                # 限制上下文长度（保留最近 N 轮）
                max_msgs = self._max_context_turns * 2
                if len(self._conversation_context) > max_msgs:
                    self._conversation_context = self._conversation_context[-max_msgs:]
                print(f"[Agent] 对话上下文已更新，当前 {len(self._conversation_context)} 条消息")

            # ★ v3.72: 增强元数据卡片 — 显示 Token/上下文/花费
            # ★ 第345章: trace_v2 启用时门控（TraceRenderer meta 脚条替代，防双显）
            if getattr(self, "_trace_v2", False):
                meta_html = None
            # ★ v5.2: 修复 f-string 内嵌的 `Lemon.XXX`（实际不存在，会抛 NameError 让整个 _on_agent_finished 中断）
            #   全部改用真实存在的 CSS 颜色字面值，并提高对比度便于在深色背景下阅读
            cost_str = f" · 花费 ¥{cost:.4f}" if cost > 0 else ""
            # ★391A-1.3: 完成卡模型名带同源窗口标注（ollama 系引擎才标，禁 UI 自造）
            _ctx_suffix = ""
            if engine in ("ollama", "miemie_v1"):
                try:
                    from shared.engine_manager import get_ollama_num_ctx
                    _ctx_suffix = f" ({get_ollama_num_ctx() // 1024}k)"
                except Exception:
                    pass
            _model_label = f"{model}{_ctx_suffix}"
            # ★391A-2: 超窗明示告警 —— 上下文 tok 超过 num_ctx 键值时，完成卡明示
            # "早期内容可能被截断"（Ollama 静默截断返回成功，业界实锤行为；
            # 数据源同源 result.context_tokens，禁 UI 估算）
            _ctx_overflow = False
            if engine in ("ollama", "miemie_v1") and context_tokens > 0:
                try:
                    from shared.engine_manager import get_ollama_num_ctx as _gctx
                    _ctx_overflow = context_tokens > _gctx()
                except Exception:
                    _ctx_overflow = False
            _ctx_warn = (
                f" <span style='color:{_RED};font-weight:bold;'>"
                f"⚠ 已超窗，早期内容可能被截断</span>"
            ) if _ctx_overflow else ""
            _ORANGE = "#ff8c42"          # 标题/引擎/模型（亮橙）
            _CYAN   = "#4dd0e1"          # 耗时/模型名（青色）
            _GREEN  = "#66bb6a"          # 迭代/工具次数（绿）
            _YELLOW = "#fbbf24"          # Token 统计（黄）
            _RED    = "#ff5252"          # 上下文（红，超过 80% 时提醒）
            _BG1    = "#1a1a1a"          # 卡片背景
            _BG2    = "#0d0d0d"
            meta_html = (
                f"<div style='margin:6px 0;padding:8px 10px;"
                f"background:linear-gradient(135deg,{_BG1},{_BG2});"
                f"border:1px solid rgba(255,154,74,0.35);border-radius:6px;"
                f"color:#cfcfcf;font-size:11px;font-family:Consolas,monospace;'>"
                f"<div style='color:{_ORANGE};font-weight:bold;margin-bottom:4px;'>✓ Agent 完成</div>"
                f"<div>引擎 <b style='color:{_ORANGE}'>{engine}</b> · 模型 <b style='color:{_CYAN}'>{_model_label}</b></div>"
                f"<div>循环 <b style='color:{_GREEN}'>{iterations}</b>轮 · "
                f"工具调用 <b style='color:{_GREEN}'>{len(tool_calls_made)}</b>次 · "
                f"耗时 <b style='color:{_CYAN}'>{total_time:.2f}s</b></div>"
                f"<div style='margin-top:3px;padding-top:3px;border-top:1px dashed rgba(255,255,255,0.15);'>"
                f"[轮] 输入 <b style='color:{_YELLOW}'>{input_tokens}</b> tok · "
                f"输出 <b style='color:{_YELLOW}'>{output_tokens}</b> tok · "
                f"上下文 <b style='color:{_RED}'>{context_tokens}</b> tok{_ctx_warn}"
                f"{cost_str}"
                f"</div>"
                f"</div>"
            )
            if meta_html is not None:
                self.pybridge.append_status_signal.emit(meta_html)

            # ★ v5.1: P-F 独立状态栏条 — 把完整 meta 投到固定底栏（消息流卡片保留作历史）
            # ★ T367.4: 改用 _emit_status_safe 串行化，禁止分片
            try:
                self._emit_status_safe("final_status", {
                    "engine": engine, "model": _model_label,
                    "iterations": iterations,
                    "tools": len(tool_calls_made),
                    "total_time": round(total_time, 2),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost": round(cost, 4) if cost else 0,
                    "success": not result.get("error"),
                    "scope": "轮",   # ★389M-1: 口径标注（终值==完成卡，同源 result）
                    "ctx_overflow": _ctx_overflow,   # ★391A-2: 超窗明示（JS 未识别则忽略，无害）
                })
            except Exception:
                pass
            # ★391A-3: 终态硬保证——final 帧已推送，此后迟到的 live 帧全部拦截
            self._agent_live_finalized = True

            # ★ v5.3: 输出推理过程（reasoning）—— 若模型有思考内容，先展示为可折叠"思考过程"块
            # ★ 第345章: trace_v2 启用时门控（旧呈现；时间线里叙事节点已含过程文本）
            import html as _html_lib
            _reasoning = result.get("reasoning", "")
            if _reasoning and not getattr(self, "_trace_v2", False):
                try:
                    _r_html = (
                        f"<details style='margin:4px 0;padding:6px 8px;background:#151515;"
                        f"border:1px solid rgba(120,160,255,0.25);border-radius:6px;font-size:11px;'>"
                        f"<summary style='color:#8ab4ff;cursor:pointer;font-weight:600;'>"
                        f"<span style='color:#8ab4ff'>思考过程</span> "
                        f"<span style='color:#888'>({len(_reasoning)}字)</span></summary>"
                        f"<div style='margin-top:6px;color:#b8c4d8;white-space:pre-wrap;font-family:Consolas,monospace;'>"
                        f"{_html_lib.escape(_reasoning)}</div></details>"
                    )
                    self.output_received.emit(_r_html)
                except Exception:
                    pass

            # 输出最终回复内容（兜底确保完整）
            # ★ v5.1 修复「工具调用后不输出文本」：
            #   原条件 `not _agent_stream_active` 会在「跑过工具（流式已激活）」时
            #   把最终总结 content 整个吞掉。现改为：无论是否流式，只要有 content 都输出。
            # ★ 第345章: trace_v2 启用时旧路径输出门控（final 由 TraceRenderer 呈现，防双显）
            if content and not getattr(self, "_trace_v2", False):
                print(f"[DIAG] _on_agent_finished: emitting final reply, content_len={len(content)}, stream_active={getattr(self, '_agent_stream_active', False)}")
                if hasattr(self, 'output_received'):
                    self.output_received.emit(content)
                else:
                    print(f"[DIAG] _on_agent_finished: output_received signal NOT FOUND, using on_output instead")
                    self.on_output(content)
            # ★ 第345章: trace final + meta + run_end（时间线收口：结论永远最后）
            # ★ 第350章: final 节点 Python 端渲染 — 复用 markdown_to_html 管道（JS marked 不可靠）
            #   Python 端先做叙事去重（剥离已流式前缀），再把 content + html 一起发给前端
            if getattr(self, "_trace_v2", False):
                try:
                    self._trace_flush_text()
                    # ★ 第348章: 思考过程节点 —— 实时流已发过则不再全量重发（防重复）
                    _reasoning_text = result.get("reasoning", "") or ""
                    if _reasoning_text and not getattr(self, "_trace_think_live", False):
                        self._emit_trace("thinking", content=_reasoning_text[:20000])
                    # ★ Lemon Work: 首轮任务完成 → 自动命名会话（任务关键词 + 时间标）
                    if not getattr(self, "_lw_titled", False):
                        _t0 = (getattr(self, "_current_agent_prompt", "") or "").strip().split("\n")[0][:14]
                        if _t0:
                            import time as _tm
                            self._lw_titled = True
                            self.title_suggested.emit(
                                str(getattr(self, "_session_sid", "") or ""),
                                "%s · %s" % (_t0, _tm.strftime("%H:%M")))
                    if content:
                        _remainder = content
                        _sent = getattr(self, "_trace_sent", "") or ""
                        if len(_sent) > 30:
                            import re as _re
                            _a = _re.sub(r"\s+", "", _sent[-min(len(_sent), len(content)):])
                            _b = _re.sub(r"\s+", "", content)
                            if _a and _b.startswith(_a):
                                _cut = int(len(_a) * (len(content) / len(_b)))
                                _rem = content[_cut:]
                                _rem_len = len(_re.sub(r"\s+", "", _rem))
                                _full_len = len(_re.sub(r"\s+", "", content)) or 1
                                # ★ 保护：若"去重"切掉了 70% 以上内容（剩余不足 30%），
                                #   说明流式叙述已包含整篇报告 —— 这是误判，不是重复。
                                #   此时保留完整 content：重复显示可接受，丢失报告不可接受。
                                if _rem_len >= 40 and _rem_len >= _full_len * 0.3:
                                    _remainder = _rem
                        try:
                            from core.serve_bridge import markdown_to_html as _md2html
                            _html = _md2html(_remainder)
                        except Exception as _me:
                            print(f"[Agent] final markdown_to_html 失败: {_me}")
                            _html = None
                        try:
                            _dump_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "perf")
                            os.makedirs(_dump_dir, exist_ok=True)
                            _dump_path = os.path.join(_dump_dir, "final_html_dump.html")
                            _dump_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            _dump_header = f"<!-- [360章] ts={_dump_ts} content_len={len(_remainder) if _remainder else 0} -->\n"
                            _dump_body = self._safe_truncate_html(_html, 200000) if _html else ""
                            with open(_dump_path, "w", encoding="utf-8") as _df:
                                _df.write(_dump_header + _dump_body)
                        except Exception:
                            pass
                        self._emit_trace(
                            "final",
                            content=_remainder[:20000],
                            html=self._safe_truncate_html(_html, 80000) if _html else None,
                        )
                    # ★ v350: 最后一轮 narrative 收口（时间线完整闭环）
                    _last_round = getattr(self, "_lw_round_tools", None)
                    if _last_round:
                        self._emit_trace(
                            "narrative",
                            text="全部执行完成，共调用 %d 次工具" % len(_last_round),
                            tools=_last_round[:8])
                        self._lw_round_tools = []
                    # ★ v352: 任务拆解收口 —— 全步骤落定 + 追加"汇总结果并回复"
                    self._lw_step_finish(bool(not result.get("error")))
                    self._emit_trace(
                        "meta",
                        engine=str(engine), model=str(model),
                        iterations=int(iterations or 0),
                        tools=len(tool_calls_made or []),
                        total_time=round(float(total_time or 0), 2),
                        input_tokens=int(input_tokens or 0),
                        output_tokens=int(output_tokens or 0),
                        context_tokens=int(context_tokens or 0),
                        cost=round(float(cost or 0), 4),
                        success=not result.get("error"),
                    )
                    self._emit_trace("run_end", ok=not result.get("error"))
                except Exception as e:
                    print(f"[Agent] trace 收口失败: {e}")

            self._safe_run_js("onStreamEnd()")
            self._agent_stream_active = False  # 重置流式状态
            self.set_agent_state('idle')

            # ★ v5.1: P-E 轨迹落盘 — 把本次 Agent 运行轨迹写成 JSON（对标 TRAE Trajectory Recording）
            self._save_agent_trajectory({
                "engine": engine, "model": model, "iterations": iterations,
                "total_time": total_time, "input_tokens": input_tokens,
                "output_tokens": output_tokens, "context_tokens": context_tokens,
                "cost": cost, "prompt": user_prompt, "content": content,
                "tool_calls": tool_calls_made,
                "success": not result.get("error"),
            })

            # ★ v5.1: P-C 任务步骤列表 — 把本次累积的 timeline 事件汇总渲染到右侧栏顶部
            _steps = getattr(self, "_timeline_events", [])
            if _steps:
                _steps_payload = json.dumps({
                    "prompt": user_prompt,
                    "engine": engine, "model": model,
                    "iterations": iterations, "total_time": round(total_time, 2),
                    "success": not result.get("error"),
                    "steps": _steps,
                }, ensure_ascii=False)
                self.pybridge.append_steps_signal.emit(_steps_payload)
            self._timeline_events = []  # 重置，等待下一次运行

            # 清理 Worker 引用
            self._current_agent_worker = None
        except Exception as e:
            print(f"[Agent] 完成回调异常: {e}")
            self._safe_run_js("onStreamEnd()")
            self._agent_stream_active = False

    def _save_agent_trajectory(self, data: dict):
        """★ v5.1: P-E 轨迹落盘（对标 TRAE Trajectory Recording）

        把一次 Agent 运行的全过程（prompt / 工具调用序列 / 最终回复 / Token 统计）写成
        data/agent_trajectories/run_<timestamp>.json，供后续复盘/评测。
        """
        try:
            import time as _time
            _traj_dir = os.path.join(os.getcwd(), "data", "agent_trajectories")
            os.makedirs(_traj_dir, exist_ok=True)
            _ts = _time.strftime("%Y%m%d_%H%M%S")
            _path = os.path.join(_traj_dir, f"run_{_ts}.json")
            _record = {
                "start_time": _ts,
                "end_time": _time.strftime("%Y%m%d_%H%M%S"),
                "engine": data.get("engine", "?"),
                "model": data.get("model", "?"),
                "iterations": data.get("iterations", 0),
                "total_time": round(data.get("total_time", 0), 2),
                "success": bool(data.get("success", False)),
                "prompt": data.get("prompt", ""),
                "tool_calls": data.get("tool_calls", []),
                "tool_call_count": len(data.get("tool_calls", [])),
                "input_tokens": data.get("input_tokens", 0),
                "output_tokens": data.get("output_tokens", 0),
                "context_tokens": data.get("context_tokens", 0),
                "cost": data.get("cost", 0.0),
                "final_result": (data.get("content", "") or "")[:8000],
            }
            with open(_path, "w", encoding="utf-8") as _f:
                json.dump(_record, _f, ensure_ascii=False, indent=2)
            print(f"[Agent] 轨迹已落盘: {_path}")
        except Exception as e:
            print(f"[Agent] 轨迹落盘失败: {e}")

    def _on_agent_error(self, error: str):
        """Agent 循环异常

        ★ v4.8: auto 模式下自动回退到下一个引擎
          ollama → deepseek → mimocode(serve_bridge)
        """
        logger.error(f"[Agent] 循环异常: {error[:200]}")
        print(f"[Agent] 循环异常: {error}")
        print(f"[DIAG] _on_agent_error: error={error[:200]}, _js_ready={self._js_ready}")
        # ★392A-3: 看门狗收口（停 tick、撤两档提示）
        self._agent_watchdog_active = False
        self._watchdog_tier = 0
        self._safe_run_js("if(window.setAgentStall)window.setAgentStall('');")
        # ★第361章: 风扇停止（异常收口）
        self._safe_run_js("if(window.setAgentFan)window.setAgentFan(false);")
        # ★第362章: 异常收口出队（auto 回退续跑时 _dequeue 内 busy 检查会自动跳过）
        self._agent_task_active = False
        QTimer.singleShot(600, self._dequeue_next_message)

        # ★ v4.8: 自动回退 — 检查是否是 auto 模式且还有可用引擎
        mode_mgr = getattr(self, '_mode_manager', None)
        logger.info(f"[Fallback] 当前模式管理器: {mode_mgr}")
        
        if mode_mgr and mode_mgr.mode_name == "auto":
            last_engine = getattr(self, '_last_agent_engine', '')
            logger.info(f"[Fallback] 最后使用的引擎: {last_engine}")
            
            fallback_chain = {"ollama": "deepseek", "deepseek": "mimocode"}
            next_engine = fallback_chain.get(last_engine)
            logger.info(f"[Fallback] 回退链路: {fallback_chain} → 下一个引擎: {next_engine}")

            if next_engine:
                eng_mgr = getattr(self, '_engine_manager', None)
                logger.info(f"[Fallback] 获取 EngineManager: {'成功' if eng_mgr else '失败'}")
                
                if eng_mgr:
                    try:
                        status = eng_mgr.get_status()
                        eng_status = status.get(next_engine, {})
                        available = eng_status.get("available", False)
                        logger.info(f"[Fallback] 引擎 {next_engine} 状态: {eng_status}, 可用: {available}")
                        
                        if available:
                            prompt = getattr(self, '_current_agent_prompt', '')
                            logger.info(f"[Fallback] 当前 Prompt (前50字): {prompt[:50]}...")
                            
                            self.on_output(
                                f"<span style='color:{Lemon.ACCENT_ORANGE};'>⚠️ {last_engine} 异常，自动回退到 {next_engine}...</span>"
                            )
                            
                            if next_engine == "mimocode":
                                # ★ mimocode 走 serve_bridge（不支持 agent_chat 工具循环）
                                logger.info("[Fallback] 📡 mimocode 回退路径: 使用 serve_bridge")
                                sb = getattr(self, '_serve_bridge', None)
                                if sb and sb.is_connected:
                                    logger.info("[Fallback] ✅ serve_bridge 已连接，发送消息")
                                    sb.send_message(prompt)
                                    logger.info("[Fallback] ✅ 回退消息已通过 serve_bridge 发送")
                                    return
                                else:
                                    logger.error("[Fallback] ❌ serve_bridge 未连接")
                            else:
                                # ollama/deepseek 可走 agent_chat
                                logger.info(f"[Fallback] 📡 {next_engine} 回退路径: 使用 _send_via_agent_chat")
                                self._send_via_agent_chat(
                                    prompt, engine_id=next_engine, use_agent=True
                                )
                                logger.info(f"[Fallback] ✅ 已通过 agent_chat 回退到 {next_engine}")
                                return
                    except Exception as e:
                        logger.exception(f"[Fallback] ⚠️ 回退过程中发生异常: {e}")
                        pass
                else:
                    logger.warning("[Fallback] EngineManager 不存在，无法执行回退")
            else:
                logger.info("[Fallback] 已是链路末端 (mimocode)，无更多回退目标")
        else:
            logger.info(f"[Fallback] 非 auto 模式 (mode={getattr(mode_mgr, 'mode_name', 'N/A')}), 不触发自动回退")

        # 所有回退尝试失败或非 auto 模式 → 显示错误
        logger.warning("[Fallback] 所有回退路径已尝试或不可用，显示错误")
        self.on_output(f"<span style='color:{Lemon.ACCENT_RED};'>Agent 异常: {error}</span>")
        self._safe_run_js("onStreamEnd()")
        # ★ 第345章: trace run_end（异常收口）
        if getattr(self, "_trace_v2", False):
            self._trace_flush_text()
            # ★ v350 漏洞修复: 异常收口也发最终 narrative —— 最后一轮工具明细
            #   不静默丢失（白盒诚实性：中断在哪一轮、做了多少事要可见）
            _err_round = getattr(self, "_lw_round_tools", None)
            if _err_round:
                self._emit_trace(
                    "narrative",
                    text="执行中断，中断前共调用 %d 次工具" % len(_err_round),
                    tools=_err_round[:8])
                self._lw_round_tools = []
            # ★ v352: 拆解步骤同步落败（进行中步骤标"（已中断）"）
            self._lw_step_finish(False, interrupted=True)
            self._emit_trace("run_end", ok=False, reason=str(error)[:200])
        self._agent_stream_active = False
        self.set_agent_state('error')
        self._current_agent_worker = None

    def _on_agent_cancelled(self):
        """Agent 循环被用户取消"""
        print(f"[Agent] 循环已取消")
        # ★392A-3: 看门狗收口（停 tick、撤两档提示）
        self._agent_watchdog_active = False
        self._watchdog_tier = 0
        self._safe_run_js("if(window.setAgentStall)window.setAgentStall('');")
        # ★第361章: 风扇停止（取消收口）
        self._safe_run_js("if(window.setAgentFan)window.setAgentFan(false);")
        # ★第362章: 用户显式中断 → 清空排队消息（不打断的意图不延续到新任务）
        self._clear_pending_queue()
        # ★ v350: 同步复位挂起标志 —— 防止"隐形挂起"残留，下个任务收口后队列不动
        self._pending_paused = False
        # ★ v352: 拆解步骤标中断（用户停止 → 进行中步骤可见落败）
        self._lw_step_finish(False, interrupted=True)
        self._agent_task_active = False
        QTimer.singleShot(600, self._dequeue_next_message)
        self.pybridge.append_status_signal.emit(
            f"<span style='color:{Lemon.BRAND_ORANGE_LIGHT};'>Agent 已取消</span>"
        )
        self._safe_run_js("onStreamEnd()")
        # ★ 第345章: trace run_end（取消收口）
        if getattr(self, "_trace_v2", False):
            self._trace_flush_text()
            self._emit_trace("run_end", ok=False, reason="用户取消")
        self._agent_stream_active = False
        self.set_agent_state('idle')
        self._current_agent_worker = None

    def _configure_engine_for_coding(self, engine_id: str):
        """为 ollama/deepseek 引擎配置代码助手系统提示词"""
        import os
        try:
            from settings_manager import get_settings_manager
            ws_root = get_settings_manager().workspace_root or os.getcwd()
        except Exception:
            ws_root = os.getcwd()
        
        ws_name = os.path.basename(ws_root.rstrip('/\\'))

        # ★ v4.1.12: 读取 NATIVE 分模式工具权限配置
        _perms = {"file_write": True, "terminal": True, "web_search": False}
        try:
            from settings_manager import get_settings_manager as _gsm
            _sm = _gsm()
            _perms["file_write"] = _sm.native_tool_file_write
            _perms["terminal"] = _sm.native_tool_terminal
            _perms["web_search"] = _sm.native_tool_web_search
        except Exception:
            pass

        # 按权限生成能力与限制说明
        _ability_lines = ["- 解释代码逻辑", "- 调试和修复 bug", "- 提供编程建议"]
        if _perms["file_write"]:
            _ability_lines.append("- 阅读和编写代码文件")
        if _perms["terminal"]:
            _ability_lines.append("- 执行终端命令（git / 运行 / 构建）")
        if _perms["web_search"]:
            _ability_lines.append("- 联网搜索资料")

        _limit_lines = []
        if not _perms["file_write"]:
            _limit_lines.append("- 禁止创建 / 修改 / 删除文件（用户未授权）")
        if not _perms["terminal"]:
            _limit_lines.append("- 禁止执行终端命令（用户未授权）")
        if not _perms["web_search"]:
            _limit_lines.append("- 禁止联网搜索（用户未授权），只基于已有知识回答")

        coding_prompt = (
            f"你是一个 AI 编程助手，运行在 Lemon Code 编辑器中。\n"
            f"当前工作目录: {ws_root}\n"
            f"项目名称: {ws_name}\n\n"
            f"重要说明：\n"
            f"- Lemon Code 是一个 AI 编程工具（Agent），由 Lemon 团队开发\n"
            f"- 你不是 Claude Code，也不是 MiMo Code，不要自称它们的产品名\n"
            f"- 你使用的底层模型是什么就叫什么，不需要伪装\n"
            f"- 如果用户问你的模型/身份，如实回答即可\n\n"
            f"你的能力:\n"
            + "\n".join(f"- {ln}" for ln in _ability_lines) + "\n\n"
            f"权限限制:\n"
            + ("\n".join(_limit_lines) if _limit_lines else "- 无特殊限制") + "\n\n"
            f"回复要求:\n"
            f"- 使用中文回复\n"
            f"- 代码用 Markdown 代码块包裹\n"
            f"- 回答简洁直接，不要啰嗦\n"
            f"- 如果需要创建/修改文件，先说明再给出代码\n"
            f"- 不要输出 HTML 文件路径或'用浏览器打开'等提示\n"
        )
        
        engine = self._engine_manager.get_engine(engine_id)
        if engine and hasattr(engine, 'config'):
            engine.config.system_prompt = coding_prompt
            print(f"[Engine] 已为 {engine_id} 配置代码助手系统提示词")

    def _build_workspace_context(self) -> list:
        """构建工作空间上下文消息列表（含 git status + 文件树 + 最近编辑）"""
        import os
        import subprocess
        try:
            from settings_manager import get_settings_manager
            ws_root = get_settings_manager().workspace_root or os.getcwd()
        except Exception:
            ws_root = os.getcwd()
        
        context = []
        parts = [f"工作目录: {ws_root}"]
        
        # 1. 文件结构（前 2 层）
        try:
            tree = self._build_file_tree(ws_root, max_depth=2, max_items=30)
            if tree:
                parts.append(f"项目结构:\n{tree}")
        except Exception:
            pass
        
        # 2. Git 状态
        try:
            git_status = subprocess.run(
                ["git", "status", "--short"],
                cwd=ws_root, capture_output=True, text=True, timeout=5
            )
            if git_status.returncode == 0 and git_status.stdout.strip():
                parts.append(f"Git 状态:\n{git_status.stdout.strip()[:500]}")
        except Exception:
            pass
        
        # 3. 最近编辑的文件
        try:
            recent = self._get_recent_files(ws_root, count=5)
            if recent:
                parts.append(f"最近修改: {', '.join(recent)}")
        except Exception:
            pass
        
        if parts:
            context.append({"role": "system", "content": "\n".join(parts)})
        
        return context

    def _build_file_tree(self, root: str, max_depth: int = 2, max_items: int = 30) -> str:
        """构建简化的文件树字符串"""
        import os
        lines = []
        count = 0
        
        def walk(path, depth, prefix=""):
            nonlocal count
            if depth > max_depth or count >= max_items:
                return
            try:
                items = sorted(os.listdir(path))
            except PermissionError:
                return
            
            dirs = [d for d in items if os.path.isdir(os.path.join(path, d)) and not d.startswith('.')]
            files = [f for f in items if os.path.isfile(os.path.join(path, f)) and not f.startswith('.')]
            
            for i, item in enumerate(dirs[:8]):
                if count >= max_items:
                    break
                is_last = i == len(dirs[:8]) - 1 and not files
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{item}/")
                count += 1
                if depth < max_depth:
                    next_prefix = prefix + ("    " if is_last else "│   ")
                    walk(os.path.join(path, item), depth + 1, next_prefix)
            
            for i, item in enumerate(files[:10]):
                if count >= max_items:
                    break
                is_last = i == len(files[:10]) - 1
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{item}")
                count += 1
        
        walk(root, 0)
        return "\n".join(lines)

    def _get_recent_files(self, root: str, count: int = 5) -> list:
        """获取最近修改的文件列表"""
        import os
        recent = []
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
                for f in filenames:
                    if f.startswith('.'):
                        continue
                    fp = os.path.join(dirpath, f)
                    try:
                        mtime = os.path.getmtime(fp)
                        recent.append((mtime, os.path.relpath(fp, root)))
                    except OSError:
                        pass
                if len(recent) > 100:
                    break
            recent.sort(reverse=True)
            return [name for _, name in recent[:count]]
        except Exception:
            return []

    # ============================================================
    # 会话历史管理（v2.0 新增）
    # ============================================================
    
    def get_output_html(self) -> str:
        """获取当前面板输出内容（用于会话切换时保存历史）"""
        # 返回累计的 HTML 输出历史
        return "\n".join(self._output_history) if self._output_history else ""
    
    def clear_output(self):
        """清除面板输出内容（用于会话切换时清空面板）"""
        self._output_history = []
        # ★ v3.68: 同时清除对话上下文（新会话不应记住旧对话）
        self._conversation_context = []
        # ★389M-7: 新会话清空高危技能会话级授权（授权不跨会话泄漏）
        try:
            from shared.engine_manager import get_engine_manager
            get_engine_manager().reset_high_risk_grants(reason="session switch/new")
        except Exception as _e:
            print(f"[389M-7] 清空会话级授权失败: {_e}")
        js = "if(window.mimoAgent&&window.mimoAgent.clearOutput)window.mimoAgent.clearOutput();"
        self._safe_run_js(js)
    
    def append_html(self, html: str):
        """直接追加 HTML 到面板（用于会话切换时恢复历史）"""
        self._output_history.append(html)
        # ★ 限制历史大小，防止内存泄漏
        if len(self._output_history) > self._max_history_size:
            self._output_history = self._output_history[-self._max_history_size:]
        self._js_append_message(html)

    # ============================================================
    # 小机器人聊天（Ollama 千问模型）
    # ============================================================
    def _on_robot_chat(self, message):
        """JS 调用 chatWithRobot 时触发：异步调用 Ollama"""
        if not message or not message.strip():
            return
        print(f"[柠檬小助手] 收到消息: {message[:50]}")
        # Ollama 不可用时直接告知 JS 出错，让前端走兜底
        if self.ollama_bridge is None:
            print("[柠檬小助手] ❌ Ollama 桥接未初始化")
            self._on_robot_error_received("Ollama 桥接未初始化")
            return
        # 检查 Ollama 服务是否运行（快速探测，失败则立即回调错误）
        if not self.ollama_bridge.is_available():
            print("[柠檬小助手] ❌ Ollama 服务未运行")
            self._on_robot_error_received("Ollama 服务未运行")
            return
        print("[柠檬小助手] ✅ 调用 Ollama...")
        # 异步调用，回复通过 reply_received 信号回传
        self.ollama_bridge.chat(message)

    # ============================================================
    # ★ Agent 角色交互桥接（agent_character.py → 前端）
    # ============================================================
    def _on_agent_character_click(self, callback_id):
        """前端单击机器人 → 调用 AgentCharacter.on_click()，返回状态给前端"""
        try:
            from core.agent_character import get_agent_character
            char = get_agent_character()
            state = char.on_click()
            print(f"[AgentCharacter] onClick: emotion={state.get('emotion')}")
            if callback_id is not None:
                self._safe_run_js(
                    "window._pybridgeCallback(%d, %s);" % (callback_id, json.dumps(state, ensure_ascii=False))
                )
        except Exception as e:
            print(f"[AgentCharacter] onClick 异常: {e}")
            if callback_id is not None:
                self._safe_run_js(
                    "window._pybridgeCallback(%d, %s);" % (callback_id, json.dumps({"success": False, "error": str(e)}))
                )

    def _on_agent_character_right_click(self, callback_id):
        """前端右键机器人 → 切换到思考表情，返回状态给前端"""
        try:
            from core.agent_character import get_agent_character, Emotion
            char = get_agent_character()
            char._current_emotion = Emotion.THINKING
            state = char.get_state()
            print(f"[AgentCharacter] rightClick: emotion={state.get('emotion')}")
            if callback_id is not None:
                self._safe_run_js(
                    "window._pybridgeCallback(%d, %s);" % (callback_id, json.dumps(state, ensure_ascii=False))
                )
        except Exception as e:
            print(f"[AgentCharacter] rightClick 异常: {e}")
            if callback_id is not None:
                self._safe_run_js(
                    "window._pybridgeCallback(%d, %s);" % (callback_id, json.dumps({"success": False, "error": str(e)}))
                )

    def _on_robot_reply_received(self, text):
        """收到 Ollama 回复：转发给 JS，并发出 robotReply 信号"""
        print(f"[柠檬小助手] ✅ 收到 Ollama 回复: '{text[:50]}...'")
        safe = json.dumps(text)
        self._safe_run_js("window.mimoAgent.onRobotReply(%s);" % safe)
        # 同时发出信号，便于外部监听
        self.pybridge.robotReply.emit(text)

    def _on_robot_error_received(self, err_text):
        """Ollama 出错：转发给 JS，并发出 robotError 信号"""
        print(f"[柠檬小助手] ❌ Ollama 出错: {err_text}")
        safe = json.dumps(err_text)
        self._safe_run_js("window.mimoAgent.onRobotError(%s);" % safe)
        self.pybridge.robotError.emit(err_text)

    # ============================================================
    # Console Message Bridge: JS→Python 输入同步
    # ============================================================
    def _on_js_sync_input(self, text):
        """JS 通过 Console Message Bridge 调用的输入同步"""
        print(f"[输入同步] 右侧→底部 (Console Bridge): '{text[:30]}...'")
        self.pybridge.input_sync.emit(text)

    # ============================================================
    # 公共接口（供外部调用）
    # ============================================================
    def set_project_path(self, path):
        self.project_path = path
        js = "document.getElementById('pathLabel').textContent = %s;" % json.dumps(path)
        self._safe_run_js(js)

    def set_role(self, role_id: str):
        """★ v4.7: 设置当前 Agent 角色"""
        if role_id in self._role_names:
            self._current_role = role_id
            role_name = self._role_names[role_id]
            # 更新前端显示
            js = f"if(document.getElementById('roleLabel')){{document.getElementById('roleLabel').textContent = '角色: {role_name}';}}"
            self._safe_run_js(js)
            return True
        return False

    def get_current_role(self) -> str:
        """★ v4.7: 获取当前 Agent 角色"""
        return self._current_role

    def get_role_display_name(self) -> str:
        """★ v4.7: 获取当前角色的显示名称"""
        return self._role_names.get(self._current_role, self._current_role)

    def set_connected(self, connected, port=None):
        self._is_connected = connected
        self.pybridge.set_connected_signal.emit(connected)
        if connected:
            self.pybridge.set_robot_status_signal.emit(f"● 已连接 (:{port})")
        else:
            self.pybridge.set_robot_status_signal.emit("○ 未连接")

    def append_message(self, html):
        self.pybridge.append_message_signal.emit(html)

    def on_task_started(self):
        self.pybridge.append_status_signal.emit("⚡ Lemon Code 执行中...")
        self.pybridge.set_robot_status_signal.emit(" 执行任务...")

    def on_task_finished(self, code):
        if code == 0 or code is True:
            self.pybridge.append_status_signal.emit("✔ 完成")
            self.pybridge.set_robot_status_signal.emit("😊 完成!")
        else:
            self.pybridge.append_status_signal.emit(f"▲ 进程退出，代码: {code}")
            self.pybridge.set_robot_status_signal.emit(" 出错了...")

    def on_user_message(self, text):
        """在右侧面板显示用户消息"""
        safe = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", "&#39;")
        self.pybridge.append_user_message_signal.emit(safe)

    def on_output(self, html_or_text):
        """显示输出到右侧面板（支持 HTML 和纯文本）"""
        if html_or_text.startswith("__WEB_EMBED__:"):
            import base64
            try:
                encoded = html_or_text[len("__WEB_EMBED__:"):]
                decoded = base64.b64decode(encoded).decode("utf-8")
                html_or_text = decoded
            except Exception:
                html_or_text = '<span style="color:{Lemon.ACCENT_RED}">Web嵌入解析失败</span>'
        # ★ 卡顿修复(第340章): 移除逐次 [DIAG] print — bridge 流式路径每 delta
        # 调用一次本方法，同步控制台 IO 在流式期间构成持续主线程负担
        # ★ v3.73: 修复乱码 - 如果已经是 HTML，直接发射，不二次转义
        if html_or_text.startswith('<'):
            # 已经是 HTML，直接使用
            pass
        else:
            # ★ v5.3: 纯文本经 Markdown 渲染（代码块/列表/粗体/换行），根治"输出是一坨"问题
            try:
                import markdown as _md_lib
                _rendered = _md_lib.markdown(
                    html_or_text,
                    extensions=['fenced_code', 'tables', 'nl2br'],
                    output_format='html'
                )
                # 包裹在带样式的 div 内，统一文本色
                html_or_text = (
                    f"<div class='agent-md-output' style='color:{Lemon.TEXT_PRIMARY};line-height:1.55;'>"
                    f"{_rendered}</div>"
                )
            except Exception:
                # 兜底：纯转义 + 换行转 <br>
                safe = html_or_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                safe = safe.replace('\n', '<br>')
                html_or_text = f"<span style='color:{Lemon.TEXT_PRIMARY};'>{safe}</span>"
        # 记录到输出历史（用于会话切换），限制大小防止内存泄漏
        self._output_history.append(html_or_text)
        if len(self._output_history) > self._max_history_size:
            self._output_history = self._output_history[-self._max_history_size:]
        self.pybridge.append_message_signal.emit(html_or_text)

    def on_thinking(self, html):
        self.pybridge.append_thinking_signal.emit(html)

    def on_status(self, html):
        """显示状态消息到右侧面板（作为独立状态块，不替换AI输出内容）"""
        self.pybridge.append_status_signal.emit(html)

    def on_tool_output(self, html):
        self.pybridge.append_tool_signal.emit(html)

    def on_file_preview(self, html):
        """v3.90: 文件预览（HTML iframe/图像/代码内嵌到右侧栏）"""
        self.pybridge.append_preview_signal.emit(html)

    # ★ ===== 流式输出处理 =====
    def on_stream_started(self):
        """流式输出开始"""
        self.pybridge.eval_js_signal.emit("onStreamStart()")

    def on_stream_token(self, token: str):
        """流式 token 到达"""
        # 转义为 JS 安全字符串
        safe = token.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '')
        self.pybridge.eval_js_signal.emit(f"onStreamToken('{safe}')")

    def on_stream_ended(self, full_text: str):
        """流式输出结束"""
        # 转义为 JS 安全字符串
        safe = full_text.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '')
        self.pybridge.eval_js_signal.emit(f"onStreamEnd('{safe}')")

    def on_stream_error(self, error_msg: str):
        """流式输出错误/中断"""
        safe = error_msg.replace('\\', '\\\\').replace("'", "\\'")
        self.pybridge.eval_js_signal.emit(f"onStreamError('{safe}')")

    def on_file_change(self, changes):
        for c in changes:
            path = c['path']
            status = c.get('status', 'modified')
            icon = '📝' if status == 'modified' else '➕' if status == 'created' else '🗑'
            self.pybridge.append_status_signal.emit(f"{icon} {path}")

    # ===== ACP 交互接口 =====
    def show_config_options(self, session_id, options_list):
        """显示 Lemon Code 发来的配置选项"""
        options_json = json.dumps(options_list)
        self.pybridge.show_config_options_signal.emit(session_id, options_json)

    def show_permission(self, session_id, tool_info, options_list):
        """显示 Lemon Code 发来的权限请求"""
        tool_info_json = json.dumps(tool_info)
        options_json = json.dumps(options_list)
        self.pybridge.show_permission_signal.emit(session_id, tool_info_json, options_json)

    def set_mode(self, mode_id):
        """更新模式标签"""
        self.pybridge.set_mode_signal.emit(mode_id)

    def show_plan(self, plan_entries: list):
        """显示 AI 执行计划"""
        self.pybridge.show_plan_signal.emit(json.dumps(plan_entries))

    def show_commands(self, commands_list: list):
        """显示可用命令列表"""
        self.pybridge.show_commands_signal.emit(json.dumps(commands_list))

    def show_usage(self, usage_data: dict):
        """显示用量信息"""
        self.pybridge.show_usage_signal.emit(json.dumps(usage_data))

    def show_models(self, models: list):
        """推送模型列表到右侧面板"""
        self.pybridge.show_models_signal.emit(json.dumps(models))

    def show_sessions(self, sessions: list):
        """推送会话列表到右侧面板"""
        self.pybridge.show_sessions_signal.emit(json.dumps(sessions))

    def set_current_model(self, model_id: str):
        """设置当前模型显示"""
        self.pybridge.set_current_model_signal.emit(model_id)

    def set_current_session(self, session_id: str):
        """设置当前会话显示"""
        self.pybridge.set_current_session_signal.emit(session_id)

    def set_agent_state(self, state: str):
        """更新 Agent 状态（驱动机器人表情和建议）"""
        self.pybridge.set_agent_state_signal.emit(state)

    def set_service_mode(self, mode_id: str):
        """设置服务模式显示"""
        js = "window.mimoAgent.setServiceMode(%s);" % json.dumps(mode_id)
        self._safe_run_js(js)

    def _handle_list_directory(self, dir_path: str) -> dict:
        import os
        try:
            if not dir_path or not os.path.isdir(dir_path):
                return {"success": False, "error": f"目录不存在: {dir_path}"}
            dirs = []
            files = []
            try:
                items = os.listdir(dir_path)
            except PermissionError:
                return {"success": False, "error": "权限不足"}
            for name in sorted(items, key=str.lower):
                if name.startswith('.') and name not in ('.env', '.gitignore', '.python-version'):
                    continue
                full = os.path.join(dir_path, name)
                if os.path.isdir(full):
                    dirs.append({"name": name, "path": full, "is_dir": True})
                elif os.path.isfile(full):
                    size = os.path.getsize(full)
                    files.append({"name": name, "path": full, "is_dir": False, "size": size})
            entries = dirs + files
            return {"success": True, "data": {"path": dir_path, "entries": entries}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_get_file_content(self, file_path: str) -> dict:
        import os
        import base64
        try:
            if not file_path or not os.path.isfile(file_path):
                return {"success": False, "error": f"文件不存在: {file_path}"}
            size = os.path.getsize(file_path)
            ext = os.path.splitext(file_path)[1].lower()
            img_exts = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp', '.ico')
            if ext in img_exts:
                with open(file_path, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode('ascii')
                mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                        'gif': 'image/gif', 'svg': 'image/svg+xml', 'webp': 'image/webp',
                        'bmp': 'image/bmp', 'ico': 'image/x-icon'}.get(ext.lstrip('.'), 'application/octet-stream')
                return {"success": True, "data": {"content_base64": f"data:{mime};base64,{b64}", "size": size}}
            else:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    return {"success": True, "data": {"content": content, "size": size}}
                except UnicodeDecodeError:
                    with open(file_path, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode('ascii')
                    return {"success": True, "data": {"content_base64": f"data:application/octet-stream;base64,{b64}", "size": size}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_document_action(self, params) -> dict:
        import os
        try:
            if isinstance(params, str):
                params = json.loads(params)
            action = params.get('action', '') if isinstance(params, dict) else ''
            path = params.get('path', '') if isinstance(params, dict) else ''
            if action == 'read' and path and os.path.isfile(path):
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                return {"success": True, "data": {"content": content}}
            return {"success": False, "error": f"不支持的文档操作: {action}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_open_file_at_line(self, file_path, line_num) -> dict:
        try:
            line = int(line_num) if line_num else 0
            bridge = getattr(self, '_serve_bridge', None)
            if bridge and hasattr(bridge, 'open_file_at_line'):
                return bridge.open_file_at_line(file_path, line)
            return {"success": False, "error": "编辑器桥接未就绪"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_custom_providers(self) -> dict:
        try:
            return {"success": True, "providers": {
                "deepseek": {"name": "DeepSeek", "api_base": "https://api.deepseek.com/v1",
                             "models": ["deepseek-chat", "deepseek-coder"], "default_model": "deepseek-chat"},
                "zhipu": {"name": "Zhipu / ChatGLM", "api_base": "https://open.bigmodel.cn/api/paas/v4",
                          "models": ["glm-4", "glm-4-flash"], "default_model": "glm-4-flash"},
                "qwen": {"name": "Qwen / DashScope", "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                         "models": ["qwen-turbo", "qwen-plus", "qwen-max"], "default_model": "qwen-plus"},
            }}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_add_custom_provider(self, params) -> dict:
        try:
            if isinstance(params, str):
                params = json.loads(params)
            if not isinstance(params, dict):
                return {"success": False, "error": "参数格式错误"}
            api_base = params.get('api_base', '')
            api_key = params.get('api_key', '')
            model = params.get('model', '')
            if not api_base or not model:
                return {"success": False, "error": "缺少 api_base 或 model"}
            bridge = getattr(self, '_serve_bridge', None)
            if bridge and hasattr(bridge, 'add_custom_engine'):
                return bridge.add_custom_engine(params)
            return {"success": True, "message": f"已添加自定义引擎: {model}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_test_custom_engine(self, params) -> dict:
        try:
            if isinstance(params, str):
                params = json.loads(params)
            if not isinstance(params, dict):
                return {"success": False, "error": "参数格式错误"}
            api_base = params.get('api_base', '')
            api_key = params.get('api_key', '')
            model = params.get('model', '')
            bridge = getattr(self, '_serve_bridge', None)
            if bridge and hasattr(bridge, 'test_custom_engine'):
                return bridge.test_custom_engine(params)
            import requests as _req
            try:
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                r = _req.post(f"{api_base}/chat/completions",
                              json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
                              headers=headers, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    return {"success": True, "message": "连接成功", "models": [model]}
                return {"success": False, "message": f"HTTP {r.status_code}: {r.text[:200]}"}
            except Exception as ce:
                return {"success": False, "message": str(ce)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_switch_custom_provider(self, params) -> dict:
        try:
            if isinstance(params, str):
                params = json.loads(params)
            bridge = getattr(self, '_serve_bridge', None)
            if bridge and hasattr(bridge, 'switch_custom_engine'):
                return bridge.switch_custom_engine(params)
            return {"success": False, "error": "引擎切换桥接未就绪"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_financial_action(self, action_str: str) -> dict:
        try:
            from core.skills.finance_assistant import (
                _realtime_quote, _kline_data, _market_overview,
                _render_quote_hud, _render_kline_hud, _render_overview_hud,
                _generate_kline_chart,
            )
        except Exception:
            return {"success": False, "error": "finance_assistant v2.0 加载失败"}

        if not action_str:
            return {"success": False, "error": "操作为空"}

        try:
            parts = action_str.split(":", 2)
            cmd = parts[0]

            if cmd == "refresh" and len(parts) >= 2:
                symbol = parts[1]
                data = _realtime_quote(symbol)
                if "error" in data:
                    self.on_output(f'<div class="fin-hud" style="padding:12px;color:{Lemon.ACCENT_RED};">{data["error"]}</div>')
                else:
                    self.on_output(_render_quote_hud(data))
                return {"success": True}

            elif cmd == "quote" and len(parts) >= 2:
                symbol = parts[1]
                data = _realtime_quote(symbol)
                if "error" in data:
                    self.on_output(f'<div class="fin-hud" style="padding:12px;color:{Lemon.ACCENT_RED};">{data["error"]}</div>')
                else:
                    self.on_output(_render_quote_hud(data))
                return {"success": True}

            elif cmd == "kline" and len(parts) >= 2:
                symbol = parts[1]
                period = parts[2] if len(parts) >= 3 else "daily"
                data = _kline_data(symbol, period, 30)
                if "error" in data:
                    self.on_output(f'<div class="fin-hud" style="padding:12px;color:{Lemon.ACCENT_RED};">{data["error"]}</div>')
                else:
                    img_b64 = _generate_kline_chart(data.get("candles", []))
                    self.on_output(_render_kline_hud(data, img_b64))
                return {"success": True}

            elif cmd == "overview":
                data = _market_overview()
                self.on_output(_render_overview_hud(data))
                return {"success": True}

            elif cmd == "refresh_overview":
                data = _market_overview()
                self.on_output(_render_overview_hud(data))
                return {"success": True}

            elif cmd == "auto_overview":
                if getattr(self, '_finance_monitor_timer', None) is not None:
                    self._finance_monitor_timer.stop()
                    self._finance_monitor_timer = None
                from PyQt5.QtCore import QTimer
                self._finance_monitor_timer = QTimer(self)
                self._finance_monitor_timer.timeout.connect(self._finance_monitor_tick)
                self._finance_monitor_symbol = "overview"
                self._finance_monitor_timer.start(3000)
                data = _market_overview()
                self.on_output(_render_overview_hud(data))
                self.on_output('<div style="padding:4px 12px;font-size:11px;color:rgba(255,255,255,0.4);">自动刷新已启动（3秒/次），点击"停止"结束</div>')
                return {"success": True}

            elif cmd == "monitor" and len(parts) >= 2:
                symbol = parts[1]
                if getattr(self, '_finance_monitor_timer', None) is not None:
                    self._finance_monitor_timer.stop()
                from PyQt5.QtCore import QTimer
                self._finance_monitor_timer = QTimer(self)
                self._finance_monitor_timer.timeout.connect(self._finance_monitor_tick)
                self._finance_monitor_symbol = symbol
                self._finance_monitor_timer.start(3000)
                data = _realtime_quote(symbol)
                if "error" not in data:
                    self.on_output(_render_quote_hud(data))
                self.on_output(f'<div style="padding:4px 12px;font-size:11px;color:rgba(255,255,255,0.4);">监控已启动: {_html.escape(symbol)}（3秒/次），点击"停止"结束</div>')
                return {"success": True}

            elif cmd == "stop_monitor":
                if getattr(self, '_finance_monitor_timer', None) is not None:
                    self._finance_monitor_timer.stop()
                    self._finance_monitor_timer = None
                self.on_output(f'<div style="padding:4px 12px;font-size:11px;color:{Lemon.BRAND_ORANGE_LIGHT};">监控已停止</div>')
                return {"success": True}

            else:
                return {"success": False, "error": f"未知金融操作: {action_str}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _finance_monitor_tick(self):
        try:
            from core.skills.finance_assistant import (
                _realtime_quote, _market_overview,
                _render_quote_hud, _render_overview_hud,
            )
            symbol = getattr(self, '_finance_monitor_symbol', '')
            if symbol == "overview":
                data = _market_overview()
                self.on_output(_render_overview_hud(data))
            else:
                data = _realtime_quote(symbol)
                if "error" not in data:
                    self.on_output(_render_quote_hud(data))
        except Exception:
            pass

    def _handle_web_embed_action(self, action_str: str) -> dict:
        try:
            parts = action_str.split(":", 1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "refresh" and arg:
                import base64
                import html as html_mod
                escaped = html_mod.escape(arg, quote=True)
                embed_html = (
                    '<div class="web-embed">'
                    '<div class="web-embed-bar">'
                    '<span class="web-embed-url">' + escaped + '</span>'
                    '<span class="web-embed-btn" onclick="window._callPython(\'webEmbedAction\',\'refresh:' + escaped + '\')">&#x21BB;</span>'
                    '<span class="web-embed-btn" onclick="window._callPython(\'webEmbedAction\',\'screenshot:' + escaped + '\')">&#x1F4F7;</span>'
                    '<span class="web-embed-btn" onclick="window._callPython(\'webEmbedAction\',\'extract:' + escaped + '\')">&#x1F4CB;</span>'
                    '</div>'
                    '<iframe class="web-embed-frame" src="' + escaped + '" '
                    'sandbox="allow-scripts allow-same-origin allow-forms allow-popups" '
                    'style="width:100%;height:480px;" '
                    'loading="lazy" referrerpolicy="no-referrer"></iframe>'
                    '</div>'
                )
                encoded = base64.b64encode(embed_html.encode("utf-8")).decode("ascii")
                self.on_output("__WEB_EMBED__:" + encoded)
                return {"success": True, "action": "refresh", "url": arg}

            elif cmd == "screenshot" and arg:
                try:
                    from core.skills.browser_automation import _op_screenshot_b64
                    result = _op_screenshot_b64(url=arg)
                    if result.success:
                        self.on_output(result.output)
                    return {"success": result.success, "output": result.output if result.success else result.error}
                except ImportError:
                    return {"success": False, "error": "browser_automation 未安装"}

            elif cmd == "extract" and arg:
                try:
                    from core.skills.browser_automation import _op_extract_url
                    result = _op_extract_url(url=arg)
                    if result.success:
                        self.on_output(result.output)
                    return {"success": result.success, "output": result.output if result.success else result.error}
                except ImportError:
                    return {"success": False, "error": "browser_automation 未安装"}

            else:
                return {"success": False, "error": f"未知web嵌入操作: {action_str}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_code_playback_action(self, action_str: str) -> dict:
        try:
            parts = action_str.split(":", 1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "playback" and arg:
                from core.skills.code_playback import execute as cp_exec
                result = cp_exec(action="playback", file_path=arg)
                if result.success:
                    self.on_output(result.output)
                return {"success": result.success, "output": result.output if result.success else result.error}

            elif cmd == "snapshot" and arg:
                from core.skills.code_playback import execute as cp_exec
                result = cp_exec(action="snapshot", file_path=arg)
                if result.success:
                    self.on_output(result.output)
                return {"success": result.success, "output": result.output if result.success else result.error}

            else:
                return {"success": False, "error": f"未知代码回放操作: {action_str}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _handle_cmd_action(self, params: dict) -> dict:
        try:
            cmd_type = params.get("type", "")
            cmd_name = params.get("command", "")
            cmd_args = params.get("args", {})

            if cmd_type == "time":
                import datetime
                now = datetime.datetime.now()
                utc_now = datetime.datetime.utcnow()
                zones = [
                    {"name": "UTC", "time": utc_now.strftime("%H:%M:%S")},
                    {"name": "Local", "time": now.strftime("%H:%M:%S")},
                    {"name": "CST (UTC+8)", "time": (utc_now + datetime.timedelta(hours=8)).strftime("%H:%M:%S")},
                    {"name": "EST (UTC-5)", "time": (utc_now - datetime.timedelta(hours=5)).strftime("%H:%M:%S")},
                    {"name": "PST (UTC-8)", "time": (utc_now - datetime.timedelta(hours=8)).strftime("%H:%M:%S")},
                    {"name": "JST (UTC+9)", "time": (utc_now + datetime.timedelta(hours=9)).strftime("%H:%M:%S")},
                ]
                return {
                    "type": "cmd-time",
                    "time": now.strftime("%H:%M:%S"),
                    "date": now.strftime("%Y-%m-%d %A"),
                    "timezone": "Local",
                    "zones": zones,
                }

            elif cmd_type == "git":
                try:
                    from bridge.skills.git_skill import GitSkill
                    skill = GitSkill()
                    subcmd = cmd_args.get("subcmd", "status") if isinstance(cmd_args, dict) else "status"
                    subcmd_args = cmd_args.get("args", "") if isinstance(cmd_args, dict) else ""
                    result = skill.execute(subcmd, subcmd_args)
                    return {"type": "cmd-git", "subcommand": subcmd, "output": result}
                except Exception as e:
                    return {"type": "cmd-git", "subcommand": cmd_name, "error": str(e), "fallback": "Git操作失败，请确认仓库状态"}

            elif cmd_type in ("run", "shell"):
                try:
                    from standard_mode.core.skills.terminal_run_skill import TerminalRunSkill
                    skill = TerminalRunSkill()
                    command = cmd_args.get("command", cmd_name) if isinstance(cmd_args, dict) else cmd_name
                    result = skill.execute(command)
                    return {"type": "cmd-run", "command": command, "output": result}
                except Exception as e:
                    return {"type": "cmd-run", "command": cmd_name, "error": str(e), "fallback": "命令执行失败，请检查终端环境"}

            elif cmd_type == "pip":
                try:
                    from bridge.skills.package_manager import PackageManagerSkill
                    skill = PackageManagerSkill()
                    action = cmd_args.get("action", "list") if isinstance(cmd_args, dict) else "list"
                    result = skill.execute(action, cmd_args)
                    return {"type": "cmd-pip", "action": action, "output": result}
                except Exception as e:
                    return {"type": "cmd-pip", "action": cmd_name, "error": str(e), "fallback": "pip操作失败，请确认Python环境"}

            elif cmd_type == "search":
                try:
                    from bridge.skills.web_researcher import WebResearcherSkill
                    skill = WebResearcherSkill()
                    query = cmd_args.get("query", cmd_name) if isinstance(cmd_args, dict) else cmd_name
                    result = skill.execute(query)
                    return {"type": "cmd-search", "query": query, "results": result}
                except Exception as e:
                    return {"type": "cmd-search", "query": cmd_name, "error": str(e), "fallback": "搜索服务不可用，请检查网络"}

            elif cmd_type == "calc":
                try:
                    from bridge.skills.math_solver import MathSolverSkill
                    skill = MathSolverSkill()
                    expression = cmd_args.get("expression", cmd_name) if isinstance(cmd_args, dict) else cmd_name
                    result = skill.execute(expression)
                    return {"type": "cmd-calc", "expression": expression, "result": result}
                except Exception as e:
                    return {"type": "cmd-calc", "expression": cmd_name, "error": str(e), "fallback": "计算失败，请检查表达式格式"}

            elif cmd_type == "translate":
                try:
                    from bridge.skills.translator import TranslatorSkill
                    skill = TranslatorSkill()
                    text = cmd_args.get("text", cmd_name) if isinstance(cmd_args, dict) else cmd_name
                    result = skill.execute(text)
                    return {"type": "cmd-translate", "original": text, "translated": result}
                except Exception as e:
                    return {"type": "cmd-translate", "error": str(e), "fallback": "翻译服务不可用，请检查网络或API密钥"}

            elif cmd_type == "weather":
                try:
                    from bridge.skills.weather_service import WeatherServiceSkill
                    skill = WeatherServiceSkill()
                    location = cmd_args.get("location", "Beijing") if isinstance(cmd_args, dict) else "Beijing"
                    result = skill.execute(location)
                    return {"type": "cmd-weather", "location": location, **result}
                except Exception as e:
                    return {"type": "cmd-weather", "location": cmd_name, "error": str(e), "fallback": "天气服务不可用，请检查网络或稍后重试"}

            elif cmd_type == "code":
                try:
                    action = cmd_args.get("action", "review") if isinstance(cmd_args, dict) else "review"
                    result = self._handle_code_skill(action, [cmd_args])
                    return {"type": "cmd-code", "action": action, **result}
                except Exception as e:
                    return {"type": "cmd-code", "action": cmd_name, "error": str(e), "fallback": "代码操作失败"}

            elif cmd_type == "file":
                try:
                    action = cmd_args.get("action", "list") if isinstance(cmd_args, dict) else "list"
                    result = self._handle_list_directory(cmd_args.get("path", ".")) if action == "list" else {}
                    return {"type": "cmd-file", "action": action, **result}
                except Exception as e:
                    return {"type": "cmd-file", "action": cmd_name, "error": str(e), "fallback": "文件操作失败"}

            elif cmd_type == "web":
                try:
                    result = self._handle_web_embed_action(cmd_name)
                    return {"type": "cmd-web", "url": cmd_name, **result}
                except Exception as e:
                    return {"type": "cmd-web", "url": cmd_name, "error": str(e), "fallback": "网页加载失败"}

            elif cmd_type == "diagram":
                try:
                    from bridge.skills.math_plotter import MathPlotterSkill
                    skill = MathPlotterSkill()
                    diagram_type = cmd_args.get("type", "flow") if isinstance(cmd_args, dict) else "flow"
                    result = skill.execute(diagram_type, cmd_args)
                    return {"type": "cmd-diagram", "diagramType": diagram_type, **result}
                except Exception as e:
                    return {"type": "cmd-diagram", "error": str(e), "fallback": "图表渲染失败，Mermaid不可用时将显示源码"}

            else:
                return {"type": "cmd-error", "error": f"未知命令类型: {cmd_type}", "fallback": "请使用 /help 查看可用命令"}

        except Exception as e:
            return {"type": "cmd-error", "error": str(e), "fallback": "命令执行异常"}

    def cleanup(self):
        """释放面板资源：停定时器、断信号、清缓存。在 Tab 关闭时调用。"""
        self._clean = True
        try:
            self._mimo_status_timer.stop()
            self._js_flush_timer.stop()
            if getattr(self, '_finance_monitor_timer', None) is not None:
                self._finance_monitor_timer.stop()
                self._finance_monitor_timer = None
            if getattr(self, '_miemie_worker', None) is not None:
                try:
                    self._miemie_worker._cancelled = True
                    self._miemie_worker.quit()
                    self._miemie_worker.wait(2000)
                except Exception:
                    pass
            if self.ollama_bridge is not None:
                try:
                    self.ollama_bridge.deleteLater()
                    self.ollama_bridge = None
                except Exception:
                    pass
            try:
                self.pybridge.deleteLater()
            except Exception:
                pass
            self._js_call_queue.clear()
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._safe_run_js(
            "(function(){"
            "var c=document.getElementById('starfield');"
            "if(c&&typeof resize==='function'){resize();}"
            "if(typeof _rebuildStars==='function'){_rebuildStars();}"
            "if(typeof applyWallpaper==='function'){applyWallpaper();}"
            "})();"
        )
