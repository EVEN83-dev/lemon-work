# -*- coding: utf-8 -*-
"""
TerminalHost — 底部终端宿主抽象（真/假终端统一）· v4.1.11
============================================================

背景：
- 第198章日志"底栏真/假终端抽象化"待办。
- 此前 BottomPanel.set_fake_terminal_mode() 用 if/else 硬编码真/假两种行为，
  每次接入新的宿主（Host Agent / 原生 Agent / 拦截模式）都要改这个大方法。

设计：
- TerminalHost(基类) 定义统一接口：activate / deactivate / is_active / append_output
- NativeTerminalHost    真终端宿主：默认原生态，可输入，输出直接追加
- InterceptTerminalHost 假终端宿主：夺舍拦截态，只读 + 紫色横幅 + 彩色前缀

用法（BottomPanel）：
    self._native_host = NativeTerminalHost(self)
    self._intercept_host = InterceptTerminalHost(self)
    self._active_host = self._native_host
    # 切换：
    self._active_host = self._intercept_host; self._intercept_host.activate(agent_name)
    self._active_host.deactivate(); self._active_host = self._native_host

兼容性：BottomPanel 对外方法（set_fake_terminal_mode / is_fake_terminal_mode /
append_intercepted_output）保持不变，内部委托给 host，避免破坏外部调用点。
"""

from PyQt5.QtCore import QObject, Qt
from standard_mode.ui.design.tokens import Lemon


class TerminalHost(QObject):
    """终端宿主抽象基类

    Attributes:
        owner: 宿主容器（BottomPanel），提供 mimo_console / tab_btns / layout / log_output 等
        _active: 当前是否激活
        _agent_name: 当前拦截的 Agent 品牌名（假终端用）
    """

    #: 宿主类型名，子类覆写
    HOST_NAME = "base"

    def __init__(self, owner: QObject):
        super().__init__(owner)
        self.owner = owner
        self._active = False
        self._agent_name = ""

    # --------------------------------------------------------
    # 统一接口
    # --------------------------------------------------------

    def activate(self, agent_name: str = ""):
        """进入该宿主模式"""
        self._agent_name = agent_name
        self._active = True

    def deactivate(self):
        """退出该宿主模式，恢复原生"""
        self._active = False

    def is_active(self) -> bool:
        return self._active

    def append_output(self, text: str, source: str = "agent"):
        """追加输出到终端"""
        raise NotImplementedError

    @property
    def agent_name(self) -> str:
        return self._agent_name

    def get_mode_id(self) -> str:
        """返回宿主模式标识（native / intercept）"""
        return "base"


class NativeTerminalHost(TerminalHost):
    """真终端宿主 — 原生 Agent 模式（默认态）

    - 输入框可输入（由 MIMOConsoleWidget 正常管理）
    - 输出直接追加，无拦截前缀
    """

    HOST_NAME = "原生终端"

    def activate(self, agent_name: str = ""):
        super().activate(agent_name)
        # 恢复真终端 tab / 标题 / 输入框（幂等）
        owner = self.owner
        try:
            if hasattr(owner, "_intercept_banner"):
                owner._intercept_banner.hide()
            if "Lemon 终端" in owner.tab_btns:
                owner.tab_btns["Lemon 终端"].setText("  L>_  Lemon 终端")
            if hasattr(owner.mimo_console, "input_field"):
                owner.mimo_console.input_field.setPlaceholderText("输入消息...")
                owner.mimo_console.input_field.setReadOnly(False)
            if "终端" in owner.tab_btns:
                owner.tab_btns["终端"].setEnabled(True)
                owner.tab_btns["终端"].setToolTip("")
        except Exception as e:
            print(f"[NativeTerminalHost] activate 失败: {e}")

    def append_output(self, text: str, source: str = "agent"):
        try:
            if hasattr(self.owner.mimo_console, "append_html"):
                self.owner.mimo_console.append_html(f"<div>{text}</div>")
        except Exception as e:
            print(f"[NativeTerminalHost] append_output 失败: {e}")

    def get_mode_id(self) -> str:
        return "native"


class InterceptTerminalHost(TerminalHost):
    """假终端宿主 — 夺舍拦截态

    - 输入框只读（外部 Agent 输出不可由用户控制）
    - 紫色横幅"⚠ 拦截模式：显示 <agent> 输出"
    - 输出带彩色前缀（agent / tool / thinking / status）
    - 自动切到 "Lemon 终端" tab，禁用真终端 tab
    """

    HOST_NAME = "拦截终端"

    def activate(self, agent_name: str = "外部 Agent"):
        super().activate(agent_name)
        owner = self.owner
        try:
            # 创建/获取拦截横幅
            if not hasattr(owner, "_intercept_banner"):
                from PyQt5.QtWidgets import QLabel
                owner._intercept_banner = QLabel()
                owner._intercept_banner.setFixedHeight(22)
                owner._intercept_banner.setAlignment(Qt.AlignCenter)
                owner._intercept_banner.setStyleSheet("""
                    background: {Lemon.ACCENT_PURPLE};
                    color: {Lemon.BG};
                    font-size: 11px;
                    font-weight: 600;
                    border: none;
                """)
                owner.layout().insertWidget(1, owner._intercept_banner)

            owner._intercept_banner.setText(
                f"⚠ 拦截模式：显示 {agent_name} 输出（二次处理已启用）"
            )
            owner._intercept_banner.show()

            # 修改 tab 标题
            if "Lemon 终端" in owner.tab_btns:
                owner.tab_btns["Lemon 终端"].setText("  L>_  Lemon 终端 (拦截)")

            # 输入框只读
            if hasattr(owner.mimo_console, "input_field"):
                owner.mimo_console.input_field.setPlaceholderText(
                    f"拦截模式：{agent_name} 输出只读"
                )
                owner.mimo_console.input_field.setReadOnly(True)

            # 禁用真终端 tab
            if "终端" in owner.tab_btns:
                owner.tab_btns["终端"].setEnabled(False)
                owner.tab_btns["终端"].setToolTip(
                    "夺舍模式下真终端已禁用，请使用 Lemon 终端查看拦截输出"
                )

            # 自动切到 Lemon 终端
            owner._switch_tab("Lemon 终端")

            owner.log_output(
                f"[夺舍] 假终端模式已启用，拦截 {agent_name} 输出",
                "{Lemon.ACCENT_PURPLE}",
            )
        except Exception as e:
            print(f"[InterceptTerminalHost] activate 失败: {e}")

    def deactivate(self):
        owner = self.owner
        try:
            if hasattr(owner, "_intercept_banner"):
                owner._intercept_banner.hide()
            if "Lemon 终端" in owner.tab_btns:
                owner.tab_btns["Lemon 终端"].setText("  L>_  Lemon 终端")
            if hasattr(owner.mimo_console, "input_field"):
                owner.mimo_console.input_field.setPlaceholderText("输入消息...")
                owner.mimo_console.input_field.setReadOnly(False)
            if "终端" in owner.tab_btns:
                owner.tab_btns["终端"].setEnabled(True)
                owner.tab_btns["终端"].setToolTip("")
            owner.log_output("[夺舍] 假终端模式已禁用，恢复真终端", "{Lemon.DARK_MIMO_ORANGE}")
        except Exception as e:
            print(f"[InterceptTerminalHost] deactivate 失败: {e}")
        super().deactivate()

    def append_output(self, text: str, source: str = "agent"):
        """追加拦截输出（带来源彩色前缀）

        ★ v4.1.12: 尊重 HOST 配置 show_source_prefix / color_output
        """
        source_styles = {
            "agent": "color: {Lemon.ACCENT_BLUE};",
            "tool": "color: {Lemon.BRAND_ORANGE_LIGHT};",
            "thinking": "color: {Lemon.ACCENT_PURPLE}; font-style: italic;",
            "status": "color: {Lemon.ACCENT_GREEN};",
        }
        prefix_map = {
            "agent": "[Agent]",
            "tool": "[Tool]",
            "thinking": "[思考]",
            "status": "[状态]",
        }
        style = source_styles.get(source, "color: {Lemon.BORDER_HOVER};")
        prefix = prefix_map.get(source, "[拦截]")

        # ★ v4.1.12: 读取 HOST 配置
        show_prefix = True
        color_on = True
        try:
            from core.settings_manager import get_settings_manager as _gsm
            _sm = _gsm()
            show_prefix = _sm.host_show_source_prefix
            color_on = _sm.host_color_output
        except Exception:
            pass

        if not show_prefix:
            prefix = ""
        if not color_on:
            style = "color: {Lemon.BORDER_HOVER};"

        try:
            if hasattr(self.owner.mimo_console, "append_html"):
                pad = (prefix + " ") if prefix else ""
                html = f'<div style="{style}">{pad}{text}</div>'
                self.owner.mimo_console.append_html(html)
        except Exception as e:
            print(f"[InterceptTerminalHost] append_output 失败: {e}")

    def get_mode_id(self) -> str:
        return "intercept"


def create_host(owner: QObject, mode: str = "native") -> TerminalHost:
    """工厂：按模式创建宿主"""
    if mode == "intercept":
        return InterceptTerminalHost(owner)
    return NativeTerminalHost(owner)
