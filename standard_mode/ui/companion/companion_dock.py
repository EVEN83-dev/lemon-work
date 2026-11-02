# -*- coding: utf-8 -*-
"""
LemonGaze C4 · 陪伴模式入口（驱动右栏网页背景虚拟人物）
=========================================================
★ 改版（用户定稿）：不再外挂 PyQt 面板（用户反馈像"独立框框"）。
   改为：陪伴开关 → runJavaScript 调用右栏网页的
   window.lemonGazeSetActive(true/false)，由网页背景层 (#lemongazeEye)
   呈现霓虹发光眼，并在开启时压掉星空/流星背景（body.lemongaze-on）。
   多会话 / 页面重载由网页 localStorage 自恢复，PyQt 只负责开关与表情推送。

- 保留：标题栏开关双向绑定、右下角小点、CompanionState、CompanionBrain、
  隐私边界（C6 mount_privacy_ui）。
- 无框 / 零布局侵入：视觉完全在网页内，不占任何 PyQt 布局。
"""
from PyQt5.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush
from PyQt5.QtWidgets import QToolButton

from .companion_state import CompanionState
from .companion_brain import CompanionBrain
from .companion_privacy import mount_privacy_ui

# 每窗口实例序号（仅作 persist 键分配，不是全局陪伴态）
_INSTANCE_SEQ = 0


class CompanionDot(QToolButton):
    """右下角可点击小点：单击收起/展开眼睛；长按(600ms)→摄像头授权回调。"""

    long_pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("柠檬之瞳（单击展开/收起 · 长按摄像头授权）")
        self._press_timer = QTimer(self)
        self._press_timer.setSingleShot(True)
        self._press_timer.timeout.connect(self._on_long_press)
        self._long_fired = False

    def _on_long_press(self):
        self._long_fired = True
        self.long_pressed.emit()

    def mousePressEvent(self, event):
        self._long_fired = False
        self._press_timer.start(600)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_timer.stop()
        super().mouseReleaseEvent(event)
        if not self._long_fired:
            self.click()  # 单击语义

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor("#ff6900") if self.isEnabled() else QColor("#555555")
        p.setPen(QPen(col, 1))
        p.setBrush(QBrush(col))
        p.drawEllipse(3, 3, 6, 6)
        p.end()


class _ResizePinner(QObject):
    """窗口 resize 时把小点钉在右下角（事件过滤器，不改 MIMOWindow 代码）。"""

    def __init__(self, window, dot):
        super().__init__(window)
        self._dot = dot

    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() == QEvent.Resize:
            self._dot.move(obj.width() - 20, obj.height() - 20)
        return False


class _EyeStub:
    """无 PyQt 眼睛控件时的占位（视觉由右栏网页 canvas 承担）。

    CompanionBrain 仅需 set_glow_scale（夜间降亮），此处静默忽略。
    """

    def set_glow_scale(self, scale: float) -> None:
        pass

    def set_expression(self, expr) -> None:  # 兼容旧接口
        pass

    def stop(self) -> None:
        pass


def _iter_web_views(window):
    """枚举本窗口所有会话的 QWebEngineView（右栏网页）。"""
    ws = getattr(window, "session_workspace", None)
    panels = []
    if ws is not None:
        try:
            panels = list(getattr(ws, "_panels", {}).values())
        except Exception:
            panels = []
    if not panels:
        p = getattr(window, "mimo_panel", None)
        if p is not None:
            panels = [p]
    views = []
    for p in panels:
        wv = getattr(p, "web_view", None)
        if wv is not None:
            views.append(wv)
    return views


def _push_js(window, js: str) -> None:
    """把 JS 推到本窗口所有右栏网页；带回调回读执行结果（终端可直接诊断）。"""
    for wv in _iter_web_views(window):
        try:
            wv.page().runJavaScript(
                js, 0, lambda res: print(f"[LemonGaze] page -> {res}", flush=True))
        except Exception:
            pass


def _push_js_quiet(window, js: str) -> None:
    """静默推送（无回调打印），用于周期同步，避免日志刷屏。"""
    for wv in _iter_web_views(window):
        try:
            wv.page().runJavaScript(js)
        except Exception:
            pass


# 页面状态诊断 JS：回读 canvas 尺寸/透明度/层级/body 类名（终端直接可见）
_DIAG_JS = (
    "(function(){var c=document.getElementById('lemongazeEye');"
    "if(!c)return JSON.stringify({hasCanvas:false});"
    "var cs=getComputedStyle(c);"
    "return JSON.stringify({api:typeof window.lemonGazeSetActive,"
    "w:c.clientWidth,h:c.clientHeight,op:cs.opacity,z:cs.zIndex,"
    "disp:cs.display,cls:(document.body.className||'').slice(0,60)});})()"
)


def _js_str(s: str) -> str:
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def mount_companion(window) -> None:
    """在 MIMOWindow 上挂载陪伴模式入口（state + 网页背景人物 + dot）。

    只动 ui 挂载段；失败可整体降级（try/except 由调用方兜底）。
    """
    global _INSTANCE_SEQ
    _INSTANCE_SEQ += 1
    instance_id = _INSTANCE_SEQ
    window.companion_instance_id = instance_id

    # ── 状态（每窗口独立实例，restore 还原上次会话快照）──
    state = CompanionState()
    state.restore(instance_id)
    window.companion_state = state

    # 视觉由右栏网页背景层承担（无 PyQt 控件）；brain 用 stub 作光晕目标
    eye = _EyeStub()

    # ── 状态 → 网页：开关（显示大眼 + 压掉星空/流星）──
    def _apply_enabled(on: bool) -> None:
        _push_js(window,
                 "window.lemonGazeSetActive && window.lemonGazeSetActive(%s)"
                 % ("true" if on else "false"))
        if on:
            _push_js(window,
                     "window.lemonGazeSetExpression && "
                     "window.lemonGazeSetExpression(%s)"
                     % _js_str(state.current_expression))
        state.persist(instance_id)

    window._companion_apply_enabled = _apply_enabled
    state.enabled_changed.connect(_apply_enabled)

    # ── 状态 → 网页：表情推送 ──
    def _push_expression(expr: str) -> None:
        _push_js_quiet(window,
                       "window.lemonGazeSetExpression && "
                       "window.lemonGazeSetExpression(%s)" % _js_str(expr))

    state.expression_changed.connect(_push_expression)

    # ── 右下角小点 ──
    dot = CompanionDot(window)
    dot.move(window.width() - 20, window.height() - 20)
    dot.show()

    def _toggle_eye():
        state.set_enabled(not state.enabled)

    dot.clicked.connect(_toggle_eye)
    window.companion_dot = dot
    # 长按 → 摄像头授权（C6 挂接；此处先留回调位）
    window._companion_camera_auth_cb = None

    def _dot_long_press():
        cb = getattr(window, "_companion_camera_auth_cb", None)
        if cb:
            cb()

    dot.long_pressed.connect(_dot_long_press)

    # ── C5: L0 表情大脑（事件驱动；命令/工具/完成事件挂接逐项容错）──
    brain = CompanionBrain(window, state, eye)
    window.companion_brain = brain
    for _sig_holder, _attr in ((getattr(window, "bottom_panel", None),
                                "command_sent"),
                               (getattr(window, "title_bar", None),
                                "command_sent")):
        try:
            if _sig_holder is not None and hasattr(_sig_holder, _attr):
                getattr(_sig_holder, _attr).connect(brain.on_command_sent)
        except Exception:
            pass
    try:
        _ea = getattr(window, "_bridge_event_adapter", None)
        if _ea is not None:
            _ea.tool_call.connect(brain.on_tool_call)
            _ea.done.connect(brain.on_done)
            _ea.error.connect(brain.on_error)
    except Exception:
        pass

    # 窗口 resize 时小点钉在右下角（事件过滤器实现，零侵入）
    window._companion_pinner = _ResizePinner(window, dot)
    window.installEventFilter(window._companion_pinner)

    # 还原上次开关状态（窗口重建时还原，双向绑定收口）
    _apply_enabled(state.enabled)

    # 页面加载晚于一次性推送 → 周期同步兜底（幂等；页面就绪后 ≤4s 内必然生效）
    def _sync() -> None:
        on = state.enabled
        _push_js_quiet(window,
                       "window.lemonGazeSetActive && "
                       "window.lemonGazeSetActive(%s)"
                       % ("true" if on else "false"))
        if on:
            _push_js_quiet(window,
                           "window.lemonGazeSetExpression && "
                           "window.lemonGazeSetExpression(%s)"
                           % _js_str(state.current_expression))

    _sync()
    _sync_timer = QTimer(window)
    _sync_timer.timeout.connect(_sync)
    _sync_timer.start(4000)
    window._companion_sync_timer = _sync_timer
    # 一次性页面诊断（观察期保留：终端打印 canvas 真实状态）
    QTimer.singleShot(5000, lambda: _push_js(window, _DIAG_JS))

    # ── C6: 隐私边界（默认关 + 显式授权 + 状态栏本地处理指示）──
    try:
        mount_privacy_ui(window, state)
    except Exception as _pv_e:
        print(f"[LemonGaze] 隐私UI挂载失败(降级): {_pv_e}", flush=True)

    print(f"[LemonGaze] 陪伴层挂载完成 (instance={instance_id}, "
          f"enabled={state.enabled})", flush=True)


def unmount_companion(window) -> None:
    """窗口关闭时释放：停大脑/动画 + 移除过滤 + 释放状态快照。"""
    brain = getattr(window, "companion_brain", None)
    if brain:
        try:
            window.removeEventFilter(brain)
        except Exception:
            pass
        brain.stop()
    sync_t = getattr(window, "_companion_sync_timer", None)
    if sync_t:
        try:
            sync_t.stop()
        except RuntimeError:
            pass
    pinner = getattr(window, "_companion_pinner", None)
    if pinner:
        try:
            window.removeEventFilter(pinner)
        except Exception:
            pass
    dot = getattr(window, "companion_dot", None)
    if dot:
        try:
            dot.hide()
            dot.deleteLater()
        except RuntimeError:
            pass
    # 关闭该窗口的网页眼睛（页面若已销毁则忽略）
    try:
        _push_js(window,
                 "window.lemonGazeSetActive && window.lemonGazeSetActive(false)")
    except Exception:
        pass
    iid = getattr(window, "companion_instance_id", None)
    if iid is not None:
        CompanionState.drop(iid)
