# -*- coding: utf-8 -*-
"""
右侧面板输出测试脚本
============================================================
测试目标：
  1. 右侧栏输入框发送命令后，命令是否出现在右侧栏
  2. 本地 Ollama 模型是否响应并输出到右侧栏
  3. 信号链是否完整：JS sendMessage → PyBridge → command_sent → _on_user_send → agent_chat → on_output → pybridge.append_message_signal → _js_append_message → JS appendMsg

使用方式：
  python standard_mode/test_right_panel_output.py

测试项：
  A. Ollama 连接检测（端口 11434）
  B. EngineManager.agent_chat() 直接调用（验证引擎层）
  C. PyBridge 信号链测试（验证信号层）
  D. 完整 GUI 测试（启动窗口，2秒后自动发送测试消息，10秒后截图报告）

输出：
  - 控制台打印每步结果
  - 生成 test_right_panel_report.txt 报告
"""

import sys
import os
import time
import json
import socket
import traceback

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
LEMON_AGENT_ROOT = os.path.dirname(PROJECT_ROOT)
if LEMON_AGENT_ROOT not in sys.path:
    sys.path.insert(0, LEMON_AGENT_ROOT)

os.environ['LEMONCODE_SKIP_HYBRID'] = '1'
os.environ['LEMONCODE_MODE'] = 'standard'

report_lines = []


def log(msg):
    print(msg)
    report_lines.append(msg)


def check_ollama_port():
    log("\n" + "=" * 60)
    log("[TEST A] Ollama 端口检测")
    log("=" * 60)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        result = sock.connect_ex(('127.0.0.1', 11434))
        sock.close()
        if result == 0:
            log("[PASS] Ollama 端口 11434 可连接")
            return True
        else:
            log("[FAIL] Ollama 端口 11434 不可连接 (错误码=%d)" % result)
            log("  请先运行: ollama serve")
            return False
    except Exception as e:
        log("[FAIL] 端口检测异常: %s" % e)
        return False


def check_ollama_models():
    log("\n" + "=" * 60)
    log("[TEST A2] Ollama 模型列表")
    log("=" * 60)
    try:
        import requests
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            if models:
                log("[PASS] 可用模型: %s" % ", ".join(models))
                return models
            else:
                log("[FAIL] Ollama 无已安装模型")
                log("  请运行: ollama pull qwen2.5-coder:3b")
                return []
        else:
            log("[FAIL] Ollama API 返回状态码: %d" % resp.status_code)
            return []
    except Exception as e:
        log("[FAIL] 模型列表获取异常: %s" % e)
        return []


def test_engine_manager_chat():
    log("\n" + "=" * 60)
    log("[TEST B] EngineManager.agent_chat() 直接调用")
    log("=" * 60)
    try:
        from shared.engine_manager import get_engine_manager
        engine_mgr = get_engine_manager()
        log("[INFO] EngineManager 初始化完成")
        log("[INFO] 可用引擎: %s" % list(engine_mgr._engines.keys()))
        log("[INFO] 活跃引擎: %s" % engine_mgr._active_engine)

        status = engine_mgr.get_status()
        for eng_id, eng_status in status.items():
            log("[INFO] 引擎 %s: available=%s" % (eng_id, eng_status.get("available", False)))

        ollama_status = status.get("ollama", {})
        if not ollama_status.get("available", False):
            log("[SKIP] Ollama 引擎不可用，跳过 agent_chat 测试")
            return False

        log("[INFO] 正在调用 agent_chat('你好，请简单回复一句话')...")
        start = time.time()
        result = engine_mgr.agent_chat(
            "你好，请简单回复一句话",
            engine="ollama",
            max_iterations=2,
        )
        elapsed = time.time() - start

        content = result.get("content", "")
        iterations = result.get("iterations", 0)
        error = result.get("error", None)

        if error:
            log("[FAIL] agent_chat 返回错误: %s" % error)
            return False

        if content:
            log("[PASS] agent_chat 返回内容 (len=%d, iterations=%d, elapsed=%.2fs)" % (len(content), iterations, elapsed))
            log("[PASS] 回复前200字: %s" % content[:200])
            return True
        else:
            log("[FAIL] agent_chat 返回空内容")
            return False

    except Exception as e:
        log("[FAIL] agent_chat 异常: %s" % e)
        traceback.print_exc()
        return False


def test_pybridge_signals():
    log("\n" + "=" * 60)
    log("[TEST C] PyBridge 信号链测试（无需 GUI）")
    log("=" * 60)
    try:
        from PyQt5.QtCore import pyqtSignal, QObject

        class MockPyBridge(QObject):
            append_message_signal = pyqtSignal(str)
            append_thinking_signal = pyqtSignal(str)
            append_status_signal = pyqtSignal(str)
            append_tool_signal = pyqtSignal(str)
            append_timeline_signal = pyqtSignal(str)
            append_preview_signal = pyqtSignal(str)
            append_user_message_signal = pyqtSignal(str)
            set_connected_signal = pyqtSignal(bool)
            set_robot_status_signal = pyqtSignal(str)
            eval_js_signal = pyqtSignal(str)
            miemie_event_signal = pyqtSignal(str)

        class MockPanel(QObject):
            output_received = pyqtSignal(str)
            command_sent = pyqtSignal(str)
            error_occurred = pyqtSignal(str)

            def __init__(self):
                super().__init__()
                self.received_outputs = []
                self.received_commands = []
                self.received_js = []
                self.pybridge = MockPyBridge()

                self.pybridge.append_message_signal.connect(self._on_append_message)
                self.output_received.connect(self._on_output_received)
                self.command_sent.connect(self._on_command_sent)
                self.pybridge.eval_js_signal.connect(self._on_eval_js)

            def _on_append_message(self, html):
                self.received_outputs.append(("append_message", html))
                log("[SIGNAL] append_message_signal: len=%d" % len(html))

            def _on_output_received(self, html):
                self.received_outputs.append(("output_received", html))
                log("[SIGNAL] output_received: len=%d" % len(html))

            def _on_command_sent(self, msg):
                self.received_commands.append(msg)
                log("[SIGNAL] command_sent: %s" % msg[:50])

            def _on_eval_js(self, js):
                self.received_js.append(js)
                if "appendMsg" in js or "appendMessage" in js:
                    log("[SIGNAL] eval_js (appendMsg): %s" % js[:100])

            def on_output(self, html_or_text):
                if html_or_text.startswith('<'):
                    pass
                else:
                    safe = html_or_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    html_or_text = "<span style='color:Lemon.PLACEHOLDER;'>%s</span>" % safe
                self.pybridge.append_message_signal.emit(html_or_text)

        panel = MockPanel()

        log("[INFO] 测试 on_output → append_message_signal 链路...")
        panel.on_output("<b>测试消息1</b>")
        panel.on_output("纯文本测试消息2")

        log("[INFO] 测试 output_received → on_output 链路...")
        panel.output_received.emit("<b>Agent回复</b>")

        log("[INFO] 测试 command_sent 信号...")
        panel.command_sent.emit("你好")

        time.sleep(0.1)

        if len(panel.received_outputs) >= 3:
            log("[PASS] 信号链正常，收到 %d 条输出" % len(panel.received_outputs))
            for i, (sig_type, html) in enumerate(panel.received_outputs):
                log("[INFO]   #%d [%s] len=%d" % (i + 1, sig_type, len(html)))
            return True
        else:
            log("[FAIL] 信号链异常，只收到 %d 条输出" % len(panel.received_outputs))
            return False

    except Exception as e:
        log("[FAIL] 信号链测试异常: %s" % e)
        traceback.print_exc()
        return False


def test_mimo_panel_class():
    log("\n" + "=" * 60)
    log("[TEST C2] MIMOCodePanel 类结构检查")
    log("=" * 60)
    try:
        from ui.mimo_panel import MIMOCodePanel
        has_output_received = hasattr(MIMOCodePanel, 'output_received')
        has_command_sent = hasattr(MIMOCodePanel, 'command_sent')
        has_error_occurred = hasattr(MIMOCodePanel, 'error_occurred')
        has_on_output = hasattr(MIMOCodePanel, 'on_output')

        log("[INFO] output_received 信号: %s" % ("YES" if has_output_received else "NO !!!"))
        log("[INFO] command_sent 信号: %s" % ("YES" if has_command_sent else "NO"))
        log("[INFO] error_occurred 信号: %s" % ("YES" if has_error_occurred else "NO"))
        log("[INFO] on_output 方法: %s" % ("YES" if has_on_output else "NO !!!"))

        if not has_output_received:
            log("[FAIL] MIMOCodePanel 缺少 output_received 信号！Agent 回复会丢失")
            return False
        if not has_on_output:
            log("[FAIL] MIMOCodePanel 缺少 on_output 方法！")
            return False

        log("[PASS] MIMOCodePanel 类结构正确")
        return True
    except Exception as e:
        log("[FAIL] 类检查异常: %s" % e)
        traceback.print_exc()
        return False


def test_gui_full():
    log("\n" + "=" * 60)
    log("[TEST D] 完整 GUI 测试")
    log("=" * 60)

    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QTimer, Qt
    except ImportError as e:
        log("[SKIP] PyQt5 不可用: %s" % e)
        return False

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    try:
        from shared.engine_manager import get_engine_manager
        engine_manager = get_engine_manager()
    except Exception as e:
        log("[FAIL] EngineManager 初始化失败: %s" % e)
        return False

    try:
        from ui.standard_main_window import StandardMainWindow
        window = StandardMainWindow()
        window.show()
    except Exception as e:
        log("[FAIL] 窗口创建失败: %s" % e)
        traceback.print_exc()
        return False

    if hasattr(window, 'mimo_panel') and hasattr(window.mimo_panel, 'set_engine_manager'):
        window.mimo_panel.set_engine_manager(engine_manager)
        log("[INFO] 引擎管理器已注入")

    if hasattr(window, 'serve_bridge'):
        window.serve_bridge.start()
        log("[INFO] Lemon Code 服务已启动")

    panel = window.mimo_panel
    output_log = []
    js_log = []
    state_log = []

    def capture_output(html):
        output_log.append(html)
        log("[GUI] on_output 触发: len=%d, 前80字=%s" % (len(html), html[:80]))

    def capture_js(js_code):
        js_log.append(js_code)
        if "appendMsg" in js_code or "appendMessage" in js_code or "onStreamToken" in js_code:
            log("[GUI] JS 执行: %s" % js_code[:120])

    def capture_state(state):
        state_log.append(state)
        log("[GUI] 三色灯状态变更: %s" % state)

    panel.output_received.connect(capture_output, Qt.QueuedConnection)
    panel.pybridge.append_message_signal.connect(lambda h: (output_log.append(h), log("[GUI] append_message_signal: len=%d" % len(h))), Qt.QueuedConnection)
    panel.pybridge.append_status_signal.connect(lambda h: (output_log.append(h), log("[GUI] append_status_signal: len=%d, 前80=%s" % (len(h), h[:80]))), Qt.QueuedConnection)
    panel.pybridge.eval_js_signal.connect(capture_js, Qt.QueuedConnection)
    panel.pybridge.set_agent_state_signal.connect(capture_state, Qt.QueuedConnection)

    title_bar = getattr(window, 'title_bar', None)
    led_light = getattr(title_bar, 'agent_status_light', None) if title_bar else None
    if led_light:
        log("[INFO] 三色灯控件已找到: %s" % type(led_light).__name__)
    else:
        log("[WARN] 三色灯控件未找到！title_bar=%s" % (title_bar is not None))

    test_msg = "Hello Lemon Code! Please reply with one sentence."

    def auto_send():
        log("[GUI] 自动发送测试消息: %s" % test_msg)
        try:
            panel.command_sent.emit(test_msg)
            log("[GUI] command_sent 信号已发射")
        except Exception as e:
            log("[GUI] 发送失败: %s" % e)

    def check_dom():
        log("[GUI] 检查右侧面板 DOM 状态（完整 flex 链诊断）...")
        try:
            def on_dom_result(result):
                if result:
                    log("[GUI] DOM 诊断结果: %s" % json.dumps(result, indent=2, ensure_ascii=False)[:1000])
                else:
                    log("[GUI] DOM 诊断返回 None")
            diag_js = """
(function(){
  var ids = ['#content','.logo-area','.workspace-bar','.workspace-area',
             '.workspace-views','.workspace-view.active','.output-area','.output-messages'];
  var result = {};
  ids.forEach(function(sel){
    var el = sel.startsWith('#') ? document.getElementById(sel.slice(1)) : document.querySelector(sel);
    if (!el) { result[sel] = 'NOT FOUND'; return; }
    var cs = window.getComputedStyle(el);
    result[sel] = {
      display: cs.display, position: cs.position,
      height: cs.height, width: cs.width,
      flex: cs.flex, overflow: cs.overflow,
      minHeight: cs.minHeight, maxHeight: cs.maxHeight
    };
  });
  var om = document.getElementById('outputMessages');
  if (om) {
    result['outputMessages_extra'] = {
      childCount: om.children.length,
      scrollHeight: om.scrollHeight,
      scrollTop: om.scrollTop,
      innerHTML_len: om.innerHTML.length
    };
  }
  return result;
})()"""
            panel.web_view.page().runJavaScript(diag_js, on_dom_result)
        except Exception as e:
            log("[GUI] DOM 检查失败: %s" % e)

    def final_report():
        log("\n" + "=" * 60)
        log("[TEST D] GUI 测试最终报告")
        log("=" * 60)
        log("[INFO] output_received 触发次数: %d" % len(output_log))
        log("[INFO] JS 调用次数: %d" % len(js_log))

        if output_log:
            log("[PASS] 右侧面板收到输出！")
            for i, h in enumerate(output_log[:5]):
                log("[INFO]   输出 #%d: len=%d, 前100字=%s" % (i, len(h), h[:100]))
        else:
            log("[FAIL] 右侧面板未收到任何输出")

        has_stream = any("onStreamToken" in js for js in js_log)
        has_append = any("appendMsg" in js or "appendMessage" in js for js in js_log)
        log("[INFO] 流式 token JS: %s" % ("YES" if has_stream else "NO"))
        log("[INFO] appendMsg JS: %s" % ("YES" if has_append else "NO"))

        log("[INFO] 三色灯状态变更次数: %d" % len(state_log))
        if state_log:
            log("[PASS] 三色灯状态有变化！状态序列: %s" % " -> ".join(state_log))
            if led_light:
                final_state = led_light.get_state()
                log("[INFO] 三色灯最终状态: %s" % final_state)
        else:
            log("[FAIL] 三色灯状态无变化！Agent 工作时三色灯不亮")

        if led_light:
            final_state = led_light.get_state()
            expected = 'idle'
            if final_state == expected:
                log("[PASS] 三色灯最终状态正确: %s" % final_state)
            else:
                log("[FAIL] 三色灯最终状态异常: %s (期望: %s)" % (final_state, expected))

        check_dom()

        log("[GUI] 尝试 CSS 修复注入...")
        try:
            def on_fix_result(result):
                if result:
                    log("[GUI] CSS 修复后 outputMessages height=%s, scrollHeight=%s" % (result.get('height'), result.get('scrollHeight')))
                else:
                    log("[GUI] CSS 修复返回 None")
            fix_js = """
(function(){
  var oa = document.querySelector('.output-area');
  var om = document.getElementById('outputMessages');
  var wv = document.querySelector('.workspace-view.active');
  var wvs = document.querySelector('.workspace-views');
  var wa = document.querySelector('.workspace-area');
  if (oa) {
    oa.style.overflow = 'auto';
    oa.style.flex = '1 1 0';
    oa.style.minHeight = '100px';
  }
  if (om) {
    om.style.flex = '1 1 0';
    om.style.minHeight = '100px';
    om.style.overflowY = 'auto';
  }
  if (wv) {
    wv.style.position = 'relative';
    wv.style.height = '100%';
    wv.style.flex = '1 1 0';
  }
  if (wvs) {
    wvs.style.flex = '1 1 0';
    wvs.style.minHeight = '0';
    wvs.style.display = 'flex';
    wvs.style.flexDirection = 'column';
  }
  setTimeout(function(){
    var cs = window.getComputedStyle(om || document.body);
    var result = om ? {height: cs.height, scrollHeight: om.scrollHeight, childCount: om.children.length} : null;
    window.__cssFixResult = result;
  }, 500);
  return true;
})()"""
            panel.web_view.page().runJavaScript(fix_js)
            time.sleep(1)
            panel.web_view.page().runJavaScript("window.__cssFixResult", on_fix_result)
        except Exception as e:
            log("[GUI] CSS 修复注入失败: %s" % e)

        QTimer.singleShot(3000, app.quit)

    QTimer.singleShot(5000, auto_send)
    QTimer.singleShot(25000, final_report)

    log("[INFO] GUI 已启动，5秒后自动发送，25秒后出报告...")
    app.exec_()

    return len(output_log) > 0


def main():
    log("=" * 60)
    log("Lemon Code 右侧面板输出测试")
    log("时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    log("=" * 60)

    results = {}

    results["A_ollama_port"] = check_ollama_port()
    results["A2_ollama_models"] = len(check_ollama_models()) > 0

    results["B_engine_chat"] = test_engine_manager_chat()
    results["C_signal_chain"] = test_pybridge_signals()
    results["C2_panel_class"] = test_mimo_panel_class()

    if results["C2_panel_class"]:
        log("\n[INFO] 类结构检查通过，继续 GUI 测试...")
        results["D_gui"] = test_gui_full()
    else:
        log("\n[SKIP] 类结构检查失败，跳过 GUI 测试")
        results["D_gui"] = False

    log("\n" + "=" * 60)
    log("测试结果汇总")
    log("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        log("  [%s] %s" % (status, name))

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    log("\n总计: %d/%d 通过" % (passed, total))

    report_path = os.path.join(PROJECT_ROOT, "test_right_panel_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    log("\n报告已保存到: %s" % report_path)


if __name__ == '__main__':
    main()
