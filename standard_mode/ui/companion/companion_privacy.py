# -*- coding: utf-8 -*-
"""
LemonGaze C6 · 隐私与权限边界（默认关 / 本地处理 / 审计）
==========================================================
铁律：
  - 摄像头/麦克风默认 camera_on=mic_on=False；绝不伪造"已授权"，
    绝不静默开启；开启必须经显式授权弹窗（"本地处理·数据不出机"）；
    随时可一键关（点状态栏指示灯即关）。
  - 陪伴层（L0 现阶段）不调用任何工具；未来 L1/L2 若调用，必须走
    shared/engine_manager 统一入口 + 383A 安全审计层
    （skill_audit / grant_high_risk_tool confirm 门），
    且仅允许下方白名单内的只读/低风险工具——高危一律拒绝。
  - 摄像头开启时状态栏常驻 ●红 "本地处理" 指示。
"""
from typing import List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QMessageBox

# ── 陪伴层允许的工具白名单（仅只读/低风险；L1/L2 落地时强制走审计门）──
COMPANION_ALLOWED_TOOLS = {
    "read_file", "search_files", "list_dir", "get_status", "read_config",
}
COMPANION_BLOCKED_TOOLS = {
    "delete_file", "write_file", "shell_exec", "network_write",
    "git_push", "install_package", "run_command",
}


def companion_tool_allowed(tool_name: str) -> bool:
    """陪伴层工具准入：白名单内且不在高危黑名单 → True。

    注意：这只是陪伴子层的第二道闸；第一道是全局 383A 审计层
    （skill_audit / grant_high_risk_tool confirm 门），两者都过才放行。
    """
    if tool_name in COMPANION_BLOCKED_TOOLS:
        return False
    return tool_name in COMPANION_ALLOWED_TOOLS


def request_device_authorization(parent, device: str, state=None) -> bool:
    """显式授权弹窗（摄像头/麦克风）。取消 → 权限保持 False。

   绝不静默开摄像头；用户确认后由调用方 state.set_camera(True)。
    返回值仅为弹窗结果；真正的权限位以 state 为准。
    """
    name = "摄像头" if device == "camera" else (
        "麦克风" if device == "mic" else device)
    box = QMessageBox(parent)
    box.setWindowTitle(f"柠檬之瞳 · {name}授权")
    box.setIcon(QMessageBox.Question)
    box.setText(f"允许陪伴模式使用{name}吗？")
    box.setInformativeText(
        f"· 仅本地处理，{name}数据不出机、不上传任何服务器\n"
        f"· 可随时在状态栏指示灯一键关闭\n"
        f"· 视觉/语音推理全部在本机完成")
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    approved = box.exec_() == QMessageBox.Yes
    if state is not None and approved:
        # 仅"确认"才置 True；取消=维持现状（关闭走一键关，不让弹窗悄悄撤销）
        if device == "camera":
            state.set_camera(True)
        elif device == "mic":
            state.set_mic(True)
    return approved


def mount_privacy_ui(window, state) -> None:
    """状态栏常驻"本地处理"指示 + 长按授权流程挂接（一键可关）。"""
    # ── 指示灯（默认隐藏；摄像头开→●红，点击=一键关闭）──
    indicator = QLabel("● 摄像头·本地处理")
    indicator.setObjectName("CompanionPrivacyIndicator")
    indicator.setStyleSheet(
        "color:#ff3333; font-size:11px; font-weight:700;"
        " background:transparent; border:none; padding:0 6px;")
    indicator.setToolTip(
        "摄像头已开启（仅本地处理，数据不出机）\n点击立即关闭")
    indicator.setCursor(Qt.PointingHandCursor)
    indicator.hide()
    indicator.mousePressEvent = lambda ev: state.set_camera(False)
    try:
        sb = window.statusBar()
        if sb is not None:
            sb.addPermanentWidget(indicator)
    except Exception:
        pass
    window.companion_privacy_indicator = indicator

    def _on_camera(on: bool) -> None:
        indicator.setVisible(on)

    state.camera_changed.connect(_on_camera)
    _on_camera(state.camera_on)  # 还原已开状态

    # ── dot 长按 → 显式授权弹窗 ──
    def _auth_camera() -> None:
        if state.camera_on:
            state.set_camera(False)  # 已开 → 长按变一键关
            return
        request_device_authorization(window, "camera", state)

    window._companion_camera_auth_cb = _auth_camera
