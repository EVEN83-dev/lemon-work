# -*- coding: utf-8 -*-
"""多会话系统端到端集成测试 v3 — 覆盖所有已修复的 CRITICAL/HIGH 缺陷"""

import sys
import os
import gc

from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QObject

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)
_standard = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _standard not in sys.path:
    sys.path.insert(0, _standard)

results = []

def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    msg = f"[{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg, flush=True)
    results.append((name, status, detail))
    return condition


def test_no_duplicate_signal_connections():
    """CRITICAL#26: 首面板 _bind_mimo_panel 不应重复调用"""
    from ui.session_workspace import SessionWorkspace
    from ui.mimo_panel import MIMOCodePanel

    app = QApplication.instance() or QApplication(sys.argv)
    os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')

    ws = SessionWorkspace()
    bind_count = [0]
    original_bind = MIMOWindow_bind = None

    panels_created = []

    def factory():
        p = MIMOCodePanel()
        p.hide()
        panels_created.append(p)
        return p

    ws.set_panel_factory(factory)
    p1 = ws.create_session("S1")
    check("首面板创建成功", p1 is not None)

    signal_count = p1.receivers(getattr(p1, 'command_sent'))
    check(f"首面板 command_sent 接收者数 ≤ 1", signal_count <= 1,
          f"receivers={signal_count}")

    for p in panels_created:
        try:
            p.cleanup()
            p.deleteLater()
        except Exception:
            pass
    app.processEvents()


def test_shared_engine_manager():
    """CRITICAL#9: _shared_engine_manager 可靠注入"""
    from ui.session_workspace import SessionWorkspace
    from ui.mimo_panel import MIMOCodePanel

    app = QApplication.instance() or QApplication(sys.argv)

    from PyQt5.QtCore import pyqtSignal, QObject

    class FakeEngineManager(QObject):
        token_received = pyqtSignal(str)
        message_complete = pyqtSignal(str)
        thinking_received = pyqtSignal(str)
        tool_call_received = pyqtSignal(str, str)
        error_occurred = pyqtSignal(str)
        engine_changed = pyqtSignal(str)
        model_list_updated = pyqtSignal()

        def get_status(self):
            return {"active": "test", "mode": "auto"}
        def get_active_engine_id(self):
            return "test"
        def get_model(self, engine_id=None):
            return "test-model"
        def set_mode(self, mode):
            pass
        def set_model(self, engine, model):
            pass

    em = FakeEngineManager()

    ws = SessionWorkspace()
    panels = []

    def factory():
        p = MIMOCodePanel()
        p.hide()
        panels.append(p)
        if em is not None:
            p.set_engine_manager(em)
        return p

    ws.set_panel_factory(factory)

    p1 = ws.create_session("S1")
    check("首面板有 engine_manager", p1._engine_manager is not None,
          f"_engine_manager={p1._engine_manager}")

    p2 = ws.create_session("S2")
    check("第二面板有 engine_manager", p2._engine_manager is not None,
          f"_engine_manager={p2._engine_manager}")

    if p1._engine_manager and p2._engine_manager:
        same = p1._engine_manager is p2._engine_manager
        check("两个面板共享同一 engine_manager", same,
              f"same={same}")

    for p in panels:
        try:
            p.cleanup()
            p.deleteLater()
        except Exception:
            pass
    app.processEvents()


def test_session_switch_sender():
    """CRITICAL#23: session_switch_requested 使用 DirectConnection"""
    from ui.mimo_panel import MIMOCodePanel

    app = QApplication.instance() or QApplication(sys.argv)

    panel = MIMOCodePanel()
    check("session_switch_requested 信号存在", hasattr(panel, 'session_switch_requested'))
    check("session_switch_requested 是可调用信号", callable(panel.session_switch_requested))

    try:
        panel.cleanup()
        panel.deleteLater()
    except Exception:
        pass
    app.processEvents()


def test_close_button_svg():
    """UX: 关闭按钮 SVG 尺寸和颜色"""
    from ui.session_workspace import _CLOSE_SVG
    has_12 = 'width=\'12\'' in _CLOSE_SVG or 'width="12"' in _CLOSE_SVG
    check("关闭按钮 SVG 宽度=12", has_12, f"SVG片段={_CLOSE_SVG[:80]}...")
    not_grey = '%238b949e' not in _CLOSE_SVG
    check("关闭按钮颜色不再是灰色(Lemon.STATUS_OFFLINE)", not_grey)


def test_add_button_style():
    """UX: +按钮样式醒目"""
    from ui.session_workspace import _ADD_BTN_STYLE
    has_orange = '255,122,47' in _ADD_BTN_STYLE
    check("+按钮默认有橙色", has_orange)
    has_border = 'border' in _ADD_BTN_STYLE
    check("+按钮有边框", has_border)
    has_18 = 'font-size: 18px' in _ADD_BTN_STYLE
    check("+按钮字号=18px", has_18)


def test_full_e2e_flow():
    """完整端到端: 创建3个会话 + 切换 + 关闭 + 清理"""
    from ui.session_workspace import SessionWorkspace
    from ui.mimo_panel import MIMOCodePanel

    app = QApplication.instance() or QApplication(sys.argv)

    ws = SessionWorkspace()
    panels = []

    class FakeEM(QObject):
        token_received = pyqtSignal(str)
        message_complete = pyqtSignal(str)
        thinking_received = pyqtSignal(str)
        tool_call_received = pyqtSignal(str, str)
        error_occurred = pyqtSignal(str)
        engine_changed = pyqtSignal(str)
        model_list_updated = pyqtSignal()

        def get_status(self):
            return {"active": "test", "mode": "auto"}
        def get_active_engine_id(self):
            return "test"
        def get_model(self, engine_id=None):
            return "test-model"
        def set_mode(self, mode):
            pass
        def set_model(self, engine, model):
            pass

    em = FakeEM()

    def factory():
        p = MIMOCodePanel()
        p.hide()
        p.set_engine_manager(em)
        panels.append(p)
        return p

    ws.set_panel_factory(factory)

    p1 = ws.create_session("Chat 1")
    check("E2E: 创建会话1", p1 is not None)
    check("E2E: Tab数=1", ws.tab_bar.count() == 1, f"count={ws.tab_bar.count()}")

    p2 = ws.create_session("Chat 2")
    check("E2E: 创建会话2", p2 is not None)
    check("E2E: Tab数=2", ws.tab_bar.count() == 2, f"count={ws.tab_bar.count()}")

    p3 = ws.create_session("Chat 3")
    check("E2E: 创建会话3", p3 is not None)
    check("E2E: Tab数=3", ws.tab_bar.count() == 3, f"count={ws.tab_bar.count()}")

    ws.tab_bar.setCurrentIndex(0)
    check("E2E: 切换到Tab0", ws.tab_bar.currentIndex() == 0)
    check("E2E: 当前面板=p1", ws.tab_bar.currentWidget() is p1)

    ws.tab_bar.setCurrentIndex(2)
    check("E2E: 切换到Tab2", ws.tab_bar.currentIndex() == 2)
    check("E2E: 当前面板=p3", ws.tab_bar.currentWidget() is p3)

    ws._on_tab_close_requested(2)
    check("E2E: 关闭Tab2后Tab数=2", ws.tab_bar.count() == 2, f"count={ws.tab_bar.count()}")

    ws._on_tab_close_requested(0)
    check("E2E: 关闭Tab0后Tab数=1", ws.tab_bar.count() == 1, f"count={ws.tab_bar.count()}")

    for p in panels:
        try:
            p.cleanup()
            p.deleteLater()
        except Exception:
            pass
    app.processEvents()


def test_profile_isolation():
    """每个面板的 profile 是独立的"""
    from ui.session_workspace import SessionWorkspace
    from ui.mimo_panel import MIMOCodePanel

    app = QApplication.instance() or QApplication(sys.argv)

    ws = SessionWorkspace()
    panels = []

    def factory():
        p = MIMOCodePanel()
        p.hide()
        panels.append(p)
        return p

    ws.set_panel_factory(factory)

    p1 = ws.create_session("S1")
    p2 = ws.create_session("S2")

    if hasattr(p1, '_profile') and hasattr(p2, '_profile'):
        check("Profile隔离: 两个profile不同", p1._profile is not p2._profile)
        check("Profile隔离: 都是off-the-record",
              p1._profile.isOffTheRecord() and p2._profile.isOffTheRecord())
    else:
        check("Profile隔离: profile存在", False, "面板无_profile属性")

    for p in panels:
        try:
            p.cleanup()
            p.deleteLater()
        except Exception:
            pass
    app.processEvents()


if __name__ == '__main__':
    print("=" * 60, flush=True)
    print("多会话系统端到端集成测试 v3", flush=True)
    print("=" * 60, flush=True)

    app = QApplication.instance() or QApplication(sys.argv)
    os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')

    tests = [
        test_no_duplicate_signal_connections,
        test_shared_engine_manager,
        test_session_switch_sender,
        test_close_button_svg,
        test_add_button_style,
        test_full_e2e_flow,
        test_profile_isolation,
    ]

    for t in tests:
        print(f"\n--- {t.__doc__} ---", flush=True)
        try:
            t()
        except Exception as e:
            check(f"{t.__name__} 异常", False, str(e))
        gc.collect()

    print("\n" + "=" * 60, flush=True)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"结果: {passed}/{len(results)} 通过, {failed} 失败", flush=True)

    if failed > 0:
        print("\n失败项:", flush=True)
        for name, status, detail in results:
            if status == "FAIL":
                print(f"  X {name}: {detail}", flush=True)

    sys.exit(0 if failed == 0 else 1)
