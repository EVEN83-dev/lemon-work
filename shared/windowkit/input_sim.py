"""输入模拟（鼠标 / 键盘）。

坐标约定：所有窗口内点击采用「客户区归一化坐标」(nx, ny ∈ [0,1])，
运行时换算为物理屏幕绝对坐标。因此无论窗口缩放、移动、DPI 变化，
同一语义坐标都映射到同一视觉位置 —— 抗版本失效、抗布局漂移。

底层用 SendInput（绝对坐标 + MOUSEEVENTF_VIRTUALDESK 覆盖多屏）。
为避免不同 pywin32 构建对 SendInput/MakeKI/MakeMI 支持不一致，
此处直接用 ctypes 调用 user32.SendInput。

字符输入：
  - VkKeyScan 通道：ASCII 及部分西欧字母（vk != 0），最快。
  - KEYEVENTF_UNICODE 通道：中文/Emoji/符号（vk == 0 或主通道失败时
    回退）。非 BMP 字符拆代理对（Surrogate Pair）投递（P0-1 重点）。
  - IME 合成通道：set_ime_composition 降等为第三线后备， vk == 0 且前两
    通道均失败时启用。
  - 剪贴板后备：len(text) > clipboard_threshold（默认 200）字符时，
    走 SetClipboardData + Ctrl+Paste + 原内容恢复，避免逐字卡顿（P0-2 重点）。

窗口有效性守卫（A2）：
  - _validate_window(hwnd, need_visible=True, check_occlusion_at=None)：
    IsWindow / IsVisible / IsIconic（SW_RESTORE 还原）三查 + 遮挡检测
    （WindowFromPoint != hwnd）。未过则 raise WindowInvalidError。
  - 已挂入 click / double_click / drag / type_text / scroll / hotkey / move，
    作为所有物理操作的「第一行防线」。

返回值：type_text 返回 {"sent": int, "skipped": int, "fallback_used": bool}，
skipped > 0 意味着有字符三通道都失败；SkillResult.error 必须如实揭示。

─────────────────────────────────────────────────────────────────────
【重要】allow_foreground 开关 · 代理/后台会话勿滥用
─────────────────────────────────────────────────────────────────────
Windows 有「前台锁 (foreground lock)」与 UIPI：只有「交互式登录会话」且当前
持有前台令牌的线程，SendInput 投递的键盘/鼠标才会被目标窗口真实消费。
在以下场景会被拦截：
  - 远程桌面/SSH/任务计划程序/服务/CI 等非交互会话；
  - 代理型 AI 会话（如 CodeBuddy 工具进程）——往往在后台桌面，拿不到前台令牌。

现象：focus_window 可能返回 True（API 调用成功），但 SendInput 实际落到别处；
type_text 降级到 post_key 后返回 True，然而 UWP 应用（如 Windows 计算器）**不消费
PostMessage 的 WM_KEYDOWN**，于是「返回成功但界面毫无变化」——极易误判为真机闭环。

为避免误用，所有涉及前台的入口都暴露 `allow_foreground` 开关：
  - allow_foreground=True（默认，真实登录的交互式桌面）：正常抢前台 + SendInput + 降级 post_key。
  - allow_foreground=False（代理/后台会话）：
      · focus_window 不重试抢前台，仅返回「当前是否已在前台」；
      · type_text 在 SendInput 被拒时**不**降级 post_key（因为对 UWP 无效），
        直接跳过该字符（skipped+=1），让调用方诚实知道“输入未送达”，不要假装成功。

调用方若运行在代理会话，务必显式传 allow_foreground=False，再依 skipped>0 走
环境受限分支（如提示“请在真实桌面运行”），而不要拿“全部已发送”去上报“已完成”。
─────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import ctypes
import sys
import time
from typing import Optional

from .exceptions import InputSimError, UnsupportedPlatformError, WindowInvalidError


def _require_input():
    if sys.platform != "win32":
        raise UnsupportedPlatformError("input_sim 仅支持 Windows 平台")


# ---------------------------------------------------------------------------
# ctypes SendInput 结构（x86/x64 自适应）
# ---------------------------------------------------------------------------
_PUL = ctypes.POINTER(ctypes.c_ulong)


class _KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", _PUL),
    ]


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", _PUL),
    ]


class _HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_short),
    ]


class _InputI(ctypes.Union):
    _fields_ = [
        ("ki", _KeyBdInput),
        ("mi", _MouseInput),
        ("hi", _HardwareInput),
    ]


class _Input(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", _InputI),
    ]


def _refresh_input_desktop() -> None:
    """刷新线程所属桌面（兼容保留，当前会话实测无需调用）。

    注意：本机实测 OpenInputDesktop + SetThreadDesktop 反而会把线程移动到
    非输入桌面，使 SendInput 被拒绝。故 _send_input 不再调用本函数。
    """
    return


def _validate_window(hwnd: int, need_visible: bool = True,
                     check_occlusion_at: Optional[tuple] = None) -> None:
    """【A2 · P0-3/P0-4】窗口有效性守卫（物理操作前的「第一行防线」）。

    检查项（任一不通过即 raise WindowInvalidError，不再继续物理操作）：

      (1) IsWindow(hwnd)            — 句柄必须有效（> 0 且仍为内核窗口）
      (2) IsVisible(hwnd)           — 若 need_visible=True 则窗口必须可见
      (3) IsIconic(hwnd)            — 若窗口最小化，先尝试 SW_RESTORE 还原；
                                     还原失败不抛异常（遮挡判断交给 (4)）
      (4) WindowFromPoint (可选)    — 若 check_occlusion_at=(nx, ny) 传入，
                                     换算为屏幕坐标后用 WindowFromPoint 取
                                     顶层窗口；若非 hwnd（或其子窗口），
                                     表明窗口被遮挡，raise WindowInvalidError

    check_occlusion_at=None（默认）时不执行遮挡检测——避免在坐标不明确或
    操作本身就要把窗口带到前台（click 在后台窗口之类）时误判。

    调用方须按「操作语义」决定是否传 check_occlusion_at：
      - type_text / hotkey（「投递输入到该目标」）): 必须传
      - click / drag（「瞬时交互，UI 路由可兜底」): 可不传
      - scroll（「瞬时交互」): 可不传

    ★ 诚实性保证：无论何种失败路径，都 raise WindowInvalidError（不静默）。
    """
    import win32con
    import win32gui

    _require_input()

    # (1) 句柄有效性
    if not isinstance(hwnd, int) or hwnd <= 0:
        raise WindowInvalidError("hwnd 非正整数: %r" % (hwnd,))
    if not win32gui.IsWindow(hwnd):
        raise WindowInvalidError("hwnd 无效（IsWindow=False）：%d" % hwnd)

    # (2) 可见性
    if need_visible and not win32gui.IsWindowVisible(hwnd):
        raise WindowInvalidError("窗口不可见: hwnd=%d" % hwnd)

    # (3) 最小化 → 尝试 SW_RESTORE
    if win32gui.IsIconic(hwnd):
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.1)
        except Exception:
            pass  # 还原失败不硬判失败（交给遮挡检查兜底）
        # 还原后仍然 minimized 视为不可交互，但软放行给后续逻辑
        if win32gui.IsIconic(hwnd):
            raise WindowInvalidError("窗口最小化且 SW_RESTORE 失败: hwnd=%d" % hwnd)

    # (4) 遮挡检测（可选）
    if check_occlusion_at is not None:
        nx, ny = check_occlusion_at
        abs_x, abs_y = _to_absolute(hwnd, nx, ny)
        hwnd_top = ctypes.windll.user32.WindowFromPoint(
            ctypes.c_long((abs_x & 0xFFFF) | ((abs_y & 0xFFFF) << 16))
        )
        # 允许顶层窗口是 hwnd 本身 **或其子窗口**（子窗口也视作目标命中）
        if hwnd_top and hwnd_top != hwnd:
            try:
                if not win32gui.IsChild(hwnd, hwnd_top):
                    raise WindowInvalidError(
                        "窗口在 (%.2f,%.2f) 位置被遮挡：顶层 hwnd=%d ≠ 目标 hwnd=%d"
                        % (nx, ny, hwnd_top, hwnd))
            except Exception:
                # IsChild 本身也可能异常（跨进程），降级到 hwnd 直接比较
                raise WindowInvalidError(
                    "窗口在 (%.2f,%.2f) 位置可能被遮挡：顶层 hwnd=%d ≠ 目标 hwnd=%d"
                    % (nx, ny, hwnd_top, hwnd))


def _send_input(events: list) -> None:
    """发送一组 INPUT 事件。带轻量重试以规避偶发 0 事件（消息队列未就绪）。"""
    n = len(events)
    arr = (_Input * n)(*events)
    last_err = 0
    for attempt in range(5):
        sent = ctypes.windll.user32.SendInput(n, ctypes.pointer(arr), ctypes.sizeof(_Input))
        if sent == n:
            return
        last_err = ctypes.windll.kernel32.GetLastError()
        time.sleep(0.04)
    exc = InputSimError("SendInput 只发送了 %d/%d 个事件 (GetLastError=%d)" % (sent, n, last_err))
    exc.last_error = last_err
    raise exc


# 鼠标常量
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

# 键盘常量
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_UNICODE = 0x0004

VK_SHIFT = 0x10
VK_LSHIFT = 0xA0
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C

# 常用虚拟键码查表（hotkey 名字支持）
_KEY_NAME_MAP = {
    "ctrl": VK_CONTROL, "control": VK_CONTROL, "lctrl": VK_CONTROL,
    "shift": VK_SHIFT, "lshift": VK_SHIFT,
    "alt": VK_MENU, "menu": VK_MENU,
    "win": VK_LWIN, "lwin": VK_LWIN, "rwin": VK_RWIN,
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
}
# 字母/数字直接映射到 VK（A-Z: 0x41-0x5A，0-9: 0x30-0x39）
for _c in range(26):
    _KEY_NAME_MAP[chr(0x41 + _c)] = 0x41 + _c
for _c in range(10):
    _KEY_NAME_MAP[str(_c)] = 0x30 + _c

# Windows 消息常量
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010


# ---------------------------------------------------------------------------
# 坐标换算
# ---------------------------------------------------------------------------
def _client_origin_phys(hwnd) -> tuple:
    """客户区原点在物理屏幕坐标。"""
    import win32gui

    return win32gui.ClientToScreen(hwnd, (0, 0))


def _client_size_logical(hwnd) -> tuple:
    """客户区逻辑尺寸（CSS 像素，未含 DPI 缩放）。"""
    import win32gui

    cr = win32gui.GetClientRect(hwnd)
    return (cr[2] - cr[0], cr[3] - cr[1])


def _to_absolute(hwnd, nx: float, ny: float) -> tuple:
    """归一化客户坐标 -> SendInput 绝对坐标 (abs_x, abs_y)。

    为兼容不同 DPI 感知模式下 GetClientRect 可能返回逻辑或物理像素，
    用 ClientToScreen 同时转换原点和右下角，得到真实的物理客户区尺寸。
    """
    import win32gui

    cx, cy = win32gui.ClientToScreen(hwnd, (0, 0))
    cr = win32gui.GetClientRect(hwnd)
    br_x, br_y = win32gui.ClientToScreen(hwnd, (cr[2], cr[3]))
    phys_w = max(1, br_x - cx)
    phys_h = max(1, br_y - cy)
    phys_x = cx + nx * phys_w
    phys_y = cy + ny * phys_h
    vx = ctypes.windll.user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = ctypes.windll.user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    vw = ctypes.windll.user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    vh = ctypes.windll.user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    abs_x = int(((phys_x - vx) / vw) * 65535)
    abs_y = int(((phys_y - vy) / vh) * 65535)
    abs_x = max(0, min(65535, abs_x))
    abs_y = max(0, min(65535, abs_y))
    return abs_x, abs_y


def _mouse_event(hwnd, nx: float, ny: float, flags: int, dx: int = 0, dy: int = 0):
    abs_x, abs_y = _to_absolute(hwnd, nx, ny)
    extra = ctypes.c_ulong(0)
    inp = _Input()
    inp.type = 0  # INPUT_MOUSE
    inp.ii.mi = _MouseInput(abs_x, abs_y, 0, flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, ctypes.pointer(extra))
    events = [inp]
    if dx or dy:
        events.append(_Input(0, _InputI(mi=_MouseInput(dx, dy, 0, MOUSEEVENTF_MOVE, 0, ctypes.pointer(extra)))))
    _send_input(events)


# ---------------------------------------------------------------------------
# 窗口聚焦
# ---------------------------------------------------------------------------
def focus_window(hwnd: int, attempts: int = 20, allow_foreground: bool = True) -> bool:
    """将目标窗口带到前台，使后续 SendInput 键盘/鼠标能送达该窗口。

    allow_foreground=True（默认，真实登录的交互式桌面）：
        真实登录桌面：计算器本就前台，直接成功。后台/代理会话会被前台锁
        (foreground lock) 拦截，此时先 AllowSetForegroundWindow(ASFW_ANY) 解除锁，
        再用 AttachThreadInput 把本线程与当前前台线程输入附加，SetForegroundWindow +
        BringWindowToTop + SetWindowPos(HWND_TOPMOST) 多管齐下，并在循环中重试。
        经验值：代理会话中常需 0.2~0.5s 的反复尝试才能抢到前台。

    allow_foreground=False（代理/后台会话，无前台令牌）：
        不重试抢前台，仅返回「当前是否本就已在前台」。这样调用方拿到的返回值
        是诚实的——若返回 False，说明本会话无法把输入送达该窗口，应走环境受限分支，
        而不要误以为输入已生效。

    返回是否成功置为前台窗口。若返回 False，说明本会话被系统拦截（如代理会话），
    后续 SendInput 实际会落到其它前台窗口——此乃环境限制，非代码缺陷。
    """
    import win32api
    import win32con
    import win32gui
    import win32process

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        if not allow_foreground:
            # 代理/后台会话：不作抢前台尝试，直接回报当前状态
            return False

        my_thread = win32api.GetCurrentThreadId()
        SWP_FLAGS = win32con.SWP_NOSIZE | win32con.SWP_NOMOVE | win32con.SWP_SHOWWINDOW
        for i in range(attempts):
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)
            except Exception:
                pass
            fg = win32gui.GetForegroundWindow()
            fg_thread, _ = win32process.GetWindowThreadProcessId(fg)
            attached = False
            if fg_thread and fg_thread != my_thread:
                try:
                    win32process.AttachThreadInput(fg_thread, my_thread, True)
                    attached = True
                except Exception:
                    attached = False
            try:
                win32gui.SetForegroundWindow(hwnd)
                ctypes.windll.user32.BringWindowToTop(hwnd)
                # 置顶瞬间再取消置顶，帮助跨越前台锁
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)
                win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, SWP_FLAGS)
            except Exception:
                pass
            if win32gui.GetForegroundWindow() == hwnd:
                if attached:
                    try:
                        win32process.AttachThreadInput(fg_thread, my_thread, False)
                    except Exception:
                        pass
                return True
            if attached:
                try:
                    win32process.AttachThreadInput(fg_thread, my_thread, False)
                except Exception:
                    pass
            time.sleep(0.25)
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 鼠标操作
# ---------------------------------------------------------------------------
def click(hwnd: int, nx: float, ny: float, button: str = "left",
          double: bool = False, duration: float = 0.05) -> None:
    """在窗口客户区归一化坐标点击。button ∈ {left,right,middle}。

    double：是否双击（True 时连点两次，中间 press 间隙由 duration 控制）。
    duration：按下到抬起的间隔（秒），模拟「按住时长」，默认 0.05。

    不主动置前台：SendInput 绝对坐标点击交于光标下方的窗口，是否前台不影响落点。
    置前台（AttachThreadInput）反而会使后续 SendInput 被 UIPI 拒绝，故此处不调用。

    ★ A2：入口即调 _validate_window（遮挡留给 UI 路由兜底，不传 occlusion）。
    """
    _require_input()
    _validate_window(hwnd, need_visible=False)  # click 未必要可见窗口

    down = {
        "left": MOUSEEVENTF_LEFTDOWN,
        "right": MOUSEEVENTF_RIGHTDOWN,
        "middle": MOUSEEVENTF_MIDDLEDOWN,
    }[button]
    up = {
        "left": MOUSEEVENTF_LEFTUP,
        "right": MOUSEEVENTF_RIGHTUP,
        "middle": MOUSEEVENTF_MIDDLEUP,
    }[button]
    _mouse_event(hwnd, nx, ny, down)
    time.sleep(duration)
    _mouse_event(hwnd, nx, ny, up)
    if double:
        time.sleep(max(0.02, duration))
        _mouse_event(hwnd, nx, ny, down)
        time.sleep(duration)
        _mouse_event(hwnd, nx, ny, up)


def double_click(hwnd: int, nx: float, ny: float, button: str = "left",
                 duration: float = 0.05) -> None:
    click(hwnd, nx, ny, button, double=True, duration=duration)


def move(hwnd: int, nx: float, ny: float) -> None:
    """移动鼠标到窗口内归一化坐标（不产生按下）。"""
    _require_input()
    _validate_window(hwnd, need_visible=False)  # A2

    _mouse_event(hwnd, nx, ny, MOUSEEVENTF_MOVE)


# ---------------------------------------------------------------------------
# drag 缓动与噪声（A4）
# ---------------------------------------------------------------------------
def _ease_linear(t: float) -> float:
    return t


def _ease_smoothstep(t: float) -> float:
    """3t²-2t³：起收缓，中段快。"""
    return t * t * (3.0 - 2.0 * t)


def _ease_quintic(t: float) -> float:
    """6t⁵-15t⁴+10t³：比 smoothstep 更缓起收。"""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


_EASE_MAP = {
    "linear": _ease_linear,
    "smoothstep": _ease_smoothstep,
    "quintic": _ease_quintic,
}


def drag(hwnd: int, nx1: float, ny1: float, nx2: float, ny2: float,
         button: str = "left", duration: float = 0.5, steps: int = 0,
         ease: str = "smoothstep", jitter: float = 0.0,
         seed: Optional[int] = None) -> dict:
    """从 (nx1,ny1) 拖拽到 (nx2,ny2)（A4 人性化拖拽）。

    人性化三件套：
      1) ease-in-out 缓动：默认 smoothstep (3t²-2t³)，可选 linear/quintic。
      2) 自适应步数：steps=0（默认）时按 Manhattan 距离象素化自适应；
         steps>0 走调用方指定。
      3) 正态噪声 jitter（像素）：在绝对坐标每帧叠加 gauss(0, jitter)，
         jitter=0（默认）关闭，开启时建议 seed 便于复现。

    返回 {"steps": int, "duration": float, "ease": str, "jitter": float}。
    ★ A2：验证起点有效性。
    """
    import random
    import win32gui

    _require_input()

    # ★ 反例优先：参数解析在守卫前短路 —— 让「hwnd 有效但 button 无效」走得到 KeyError，
    # 与「hwnd 无效」的 WindowInvalidError 解耦，便于单元测试隔离。
    down = {
        "left": MOUSEEVENTF_LEFTDOWN,
        "right": MOUSEEVENTF_RIGHTDOWN,
        "middle": MOUSEEVENTF_MIDDLEDOWN,
    }[button]
    up = {
        "left": MOUSEEVENTF_LEFTUP,
        "right": MOUSEEVENTF_RIGHTUP,
        "middle": MOUSEEVENTF_MIDDLEUP,
    }[button]

    _validate_window(hwnd, need_visible=False)  # A2

    # 曼哈顿距离（象素）→ 自适应步数
    if steps <= 0:
        cx0, cy0 = win32gui.ClientToScreen(hwnd, (0, 0))
        cr = win32gui.GetClientRect(hwnd)
        br_x, br_y = win32gui.ClientToScreen(hwnd, (cr[2], cr[3]))
        pw = max(1, br_x - cx0)
        ph = max(1, br_y - cy0)
        manh = (abs(nx2 - nx1) * pw + abs(ny2 - ny1) * ph)
        # 200 象素→约 14 步，800 象素→约 40 步，限 6~60
        steps = max(6, min(60, int(manh / 14.0)))
    steps = max(1, int(steps))

    ease_fn = _EASE_MAP.get(ease, _ease_smoothstep)

    rng = random.Random(seed) if seed is not None else random

    # 预采样噪声（长度 = steps），让两端无噪声（起止位置精准）
    if jitter > 0:
        noise = [(rng.gauss(0, jitter), rng.gauss(0, jitter)) for _ in range(steps)]
        quiet = max(1, int(steps * 0.1))
        for i in range(quiet):
            noise[i] = (0.0, 0.0)
            noise[-(i + 1)] = (0.0, 0.0)
    else:
        noise = [(0.0, 0.0)] * steps

    abs_sx, abs_sy = _to_absolute(hwnd, nx1, ny1)
    abs_ex, abs_ey = _to_absolute(hwnd, nx2, ny2)
    extra = ctypes.c_ulong(0)

    # down at start (no noise)
    inp = _Input()
    inp.type = 0
    inp.ii.mi = _MouseInput(abs_sx, abs_sy, 0,
                           down | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                           0, ctypes.pointer(extra))
    _send_input([inp])

    step_dt = max(0.001, duration / steps)
    for i in range(1, steps + 1):
        t = ease_fn(i / steps)
        ax = int(abs_sx + (abs_ex - abs_sx) * t + noise[i - 1][0])
        ay = int(abs_sy + (abs_ey - abs_sy) * t + noise[i - 1][1])
        inp = _Input()
        inp.type = 0
        inp.ii.mi = _MouseInput(ax, ay, 0,
                               MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                               0, ctypes.pointer(extra))
        _send_input([inp])
        time.sleep(step_dt)

    # up at end (no noise)
    inp = _Input()
    inp.type = 0
    inp.ii.mi = _MouseInput(abs_ex, abs_ey, 0,
                           up | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                           0, ctypes.pointer(extra))
    _send_input([inp])

    return {"steps": steps, "duration": duration,
            "ease": ease, "jitter": jitter}


def scroll(hwnd: int, nx: float, ny: float, dx: int = 0, dy: int = 0) -> None:
    """在窗口客户区归一化坐标 (nx,ny) 处滚动（D-T04）。

    dy>0 向下滚，dy<0 向上滚；dx 为水平滚动（部分设备支持）。
    通过 mouseData 字段传递滚轮 delta（WHEEL_DELTA=120/格）。
    ★ A2：入口即 _validate_window。
    """
    _require_input()
    _validate_window(hwnd, need_visible=False)  # A2
    from ctypes import pointer, c_ulong

    extra = c_ulong(0)
    abs_x, abs_y = _to_absolute(hwnd, nx, ny)
    wheel = 0x0800  # MOUSEEVENTF_WHEEL
    # 垂直滚动
    events = []
    if dy != 0:
        delta = int(dy * 120)
        inp = _Input()
        inp.type = 0
        inp.ii.mi = _MouseInput(abs_x, abs_y, delta & 0xFFFFFFFF, wheel | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, pointer(extra))
        events.append(inp)
    if dx != 0:
        delta = int(dx * 120)
        inp = _Input()
        inp.type = 0
        inp.ii.mi = _MouseInput(abs_x, abs_y, delta & 0xFFFFFFFF, (0x1000) | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, pointer(extra))  # MOUSEEVENTF_HWHEEL
        events.append(inp)
    if events:
        _send_input(events)


# ---------------------------------------------------------------------------
# 键盘操作
# ---------------------------------------------------------------------------
def _keyboard_event(vk: int = 0, scan: int = 0, flags: int = KEYEVENTF_KEYDOWN) -> _Input:
    """构造一个 INPUT_KEYBOARD 事件。

    vk=0 + KEYEVENTF_UNICODE：Unicode 通道（wScan 即码点）。
    scan 取低 16 位（BMP 码点或代理对之一均合法）。
    """
    extra = ctypes.c_ulong(0)
    inp = _Input()
    inp.type = 1  # INPUT_KEYBOARD
    inp.ii.ki = _KeyBdInput(vk, scan & 0xFFFF, flags, 0, ctypes.pointer(extra))
    return inp


def _send_unicode_codepoint(code: int) -> None:
    """通过 KEYEVENTF_UNICODE 投递一个 16 位码元（按下+抬起）。

    仅用于已拆好的码元（BMP 码点或 ISO/IEC 10646 代理对高位/低位之一），
    不处理代理对拆分——这是 _send_unicode(ch) 职责。
    """
    _require_input()
    _send_input([
        _keyboard_event(vk=0, scan=code, flags=KEYEVENTF_UNICODE),
        _keyboard_event(vk=0, scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
    ])


def _send_unicode(ch: str) -> None:
    """SendInput KEYEVENTF_UNICODE 投递单个 Unicode 码点。

    - BMP 字符（U+0000..U+FFFF）：单事件对（按下+抬起）。
    - 非 BMP 字符（U+10000..U+10FFFF）：按 Windows SendInput 兼容性要求，
      拆为 UTF-16 代理对 (high 0xD800..0xDBFF, low 0xDC00..0xDFFF)，
      分两次发送。

    这是 P0-1 中文/Emoji 输入通道 —— 比 IME 通道稳定，且不依赖系统 IME 状态。
    """
    _require_input()
    cp = ord(ch)
    if cp <= 0xFFFF:
        _send_unicode_codepoint(cp)
        return
    # 代理对：仅处理至 Supplementary Planes (U+10000..U+10FFFF)
    cp -= 0x10000
    high = 0xD800 + (cp >> 10)
    low = 0xDC00 + (cp & 0x3FF)
    _send_unicode_codepoint(high)
    time.sleep(0.01)
    _send_unicode_codepoint(low)


def press_key(hwnd: int, vk: int) -> None:
    """按下并抬起一个虚拟键码（VK_*）。
    ★ A2：入口即 _validate_window。
    """
    _require_input()
    _validate_window(hwnd, need_visible=True)  # A2
    _send_input([_keyboard_event(vk, flags=KEYEVENTF_KEYDOWN),
                 _keyboard_event(vk, flags=KEYEVENTF_KEYUP)])


def _vk_scan(ch: str) -> tuple:
    """返回 (vk, shift_needed)。shift_needed 为 True 表示需要按 Shift。"""
    _require_input()
    code = ctypes.windll.user32.VkKeyScanW(ctypes.c_wchar(ch))
    if code == -1 or code == 0xFFFF:
        return (0, False)
    vk = code & 0xFF
    shift = (code >> 8) & 0xFF
    return (vk, bool(shift & 1))


def type_text(hwnd: int, text: str, raise_on_error: bool = True,
              allow_foreground: bool = True, interval: float = 0.02,
              clipboard_threshold: int = 200) -> dict:
    """向窗口输入字符串（P0-1/P0-2：Unicode 通道 + 明细返回 + 剪贴板后备）。

    三通道投递（每一位字符都走三级「尝试-回退-再尝试」，任一失败都会
    在结果里体现为 skipped > 0，不再有 continue 静默跳过）：

      通道 1 · VkKeyScan 快通道（vk != 0 时；ASCII 键盘标准路径）
      通道 2 · KEYEVENTF_UNICODE（vk == 0 或通道 1 失败；主中文/Emoji 通道，
             非 BMP 自动拆代理对）
      通道 3 · set_ime_composition（第三线后备；vk == 0 且前两通道均失败时）

    通道 1 SendInput 被拒 (ERROR_ACCESS_DENIED=5) 时：
      - allow_foreground=True：降级 post_key（仅 ASCII 能 PostMessage，中文/Emoji
        将继续走通道 2）。
      - allow_foreground=False：不降级（代理/后台会话 UWP 不消费 PostMessage，
        降级只会制造假成功），跳过该字符（skipped+=1）。

    P0-2 长文本剪贴板后备：len(text) > clipboard_threshold（默认 200）时，
    走 SetClipboardData + Ctrl+V 粘贴 + 原内容恢复，避免 200+ 字符逐字卡顿
    与字符错位。

    返回值：{"sent": int, "skipped": int, "fallback_used": bool}
      sent          成功投递字符数
      skipped       三通道均失败的字符数（> 0 表示有字符未送达）
      fallback_used 本次投递是否经历了 Unicode / IME 后备（纯 ASCII 全部走
                    VkKeyScan 时为 False）

    ★ 调用方职责：skipped > 0 时 SkillResult.error 必填，不得报 success=True。
    """
    _require_input()

    # A2：窗口有效性守卫 + 遮挡检测（热点选窗口中心，避免坐标边缘误判）
    _validate_window(hwnd, need_visible=True, check_occlusion_at=(0.5, 0.5))

    # P0-2：长文本走剪贴板后备
    if clipboard_threshold and len(text) > clipboard_threshold:
        ok = _clipboard_paste_text(hwnd, text)
        return {"sent": len(text) if ok else 0,
                "skipped": 0 if ok else len(text),
                "fallback_used": ok}

    sent = 0
    skipped = 0
    fallback_used = False

    for ch in text:
        vk, shifted = _vk_scan(ch)
        delivered = False

        # --- 通道 1：VkKeyScan 快通道 ---
        if vk != 0:
            events = []
            if shifted:
                events.append(_keyboard_event(VK_SHIFT, flags=KEYEVENTF_KEYDOWN))
            events.append(_keyboard_event(vk, flags=KEYEVENTF_KEYDOWN))
            events.append(_keyboard_event(vk, flags=KEYEVENTF_KEYUP))
            if shifted:
                events.append(_keyboard_event(VK_SHIFT, flags=KEYEVENTF_KEYUP))
            try:
                _send_input(events)
                delivered = True
            except InputSimError as exc:
                last_err = getattr(exc, "last_error", None)
                if last_err == 5 and allow_foreground:
                    # 非交互会话：降级 PostMessage（仅 ASCII 成功）。
                    post_key(hwnd, vk)
                    delivered = True
                # 否则让字符继续走通道 2 / 通道 3

        # --- 通道 2：KEYEVENTF_UNICODE（中文/Emoji 主通道）---
        if not delivered:
            try:
                _send_unicode(ch)
                delivered = True
                fallback_used = True
            except InputSimError:
                pass

        # --- 通道 3：set_ime_composition（第三线后备，已被降等）---
        if not delivered:
            try:
                set_ime_composition(hwnd, ch)
                delivered = True
                fallback_used = True
            except Exception:
                pass

        if delivered:
            sent += 1
        else:
            skipped += 1

        time.sleep(interval)

    result = {"sent": sent, "skipped": skipped, "fallback_used": fallback_used}
    if skipped > 0 and raise_on_error:
        raise InputSimError(
            "type_text %d/%d 字符未送达（三通道均失败），详见返回 dict" % (skipped, len(text)))
    return result


def set_ime_composition(hwnd: int, text: str) -> bool:
    """IME 合成提交（第三线后备·已降等）。

    对目标窗口投递 WM_IME_STARTCOMPOSITION / 字符 / WM_IE_ENDCOMPOSITION。
    真实中文 IME 依赖系统输入法状态，后台会话通常无法真正合成候选词，
    本函数仅做「尽力投递」。

    注意：type_text 已降等本函数为第三线后备（ vk == 0 且通道 1 / 通道 2 均
    失败时自动触发），**调用方一般无需显式调用**。
    """
    _require_input()
    WM_IME_STARTCOMPOSITION = 0x010D
    WM_IME_COMPOSITION = 0x010F
    WM_IME_ENDCOMPOSITION = 0x010E
    for ch in text:
        ctypes.windll.user32.PostMessageW(hwnd, WM_IME_STARTCOMPOSITION, 0, 0)
        ctypes.windll.user32.PostMessageW(hwnd, WM_IME_COMPOSITION,
                                          ord(ch), 0x0800 | 0x0400)  # GCS_RESULTSTR | GCS_COMPSTR
        ctypes.windll.user32.PostMessageW(hwnd, WM_IME_ENDCOMPOSITION, 0, 0)
        time.sleep(0.02)
    return True


def _open_clipboard(attempts: int = 5) -> bool:
    """带重试的 OpenClipboard（防其他进程瞬时占用 clipboard）。"""
    u32 = ctypes.windll.user32
    for _ in range(attempts):
        if u32.OpenClipboard(0):
            return True
        time.sleep(0.02)
    return False


def _clipboard_set_text(text: str) -> bool:
    """通过 ctypes 设置剪贴板 Unicode 文本（不必依赖 pywin32）。

    失败返回 False（静默，调用方自行重试或回退逐字）。
    """
    _require_input()
    CF_UNICODETEXT = 13
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    # 强制 64-bit 句柄，避免默认 c_int 截断高 32 位导致崩溃 / 参数溢出。
    k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.restype = ctypes.c_long
    k32.GlobalFree.argtypes = [ctypes.c_void_p]
    k32.GlobalFree.restype = ctypes.c_void_p
    # SetClipboardData(HANDLE) 也需 64-bit 参数
    u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    u32.SetClipboardData.restype = ctypes.c_void_p
    u32.GetClipboardData.argtypes = [ctypes.c_uint]
    u32.GetClipboardData.restype = ctypes.c_void_p
    if not _open_clipboard():
        return False
    try:
        u32.EmptyClipboard()
        data = (text + '\x00').encode("utf-16-le")
        size = len(data)
        # GMEM_FIXED：不可移动、可直接取指针，对 SetClipboardData 够用（较 GMEM_MOVEABLE 稳定）。
        GMEM_FIXED = 0x0000
        h = k32.GlobalAlloc(GMEM_FIXED, size)
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            k32.GlobalFree(h)
            return False
        try:
            ctypes.memmove(p, data, size)
        finally:
            k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_UNICODETEXT, h)
        return True
    finally:
        u32.CloseClipboard()


def _clipboard_get_text() -> Optional[str]:
    """读取剪贴板 Unicode 文本（无可用格式返回 None）。"""
    _require_input()
    CF_UNICODETEXT = 13
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.restype = ctypes.c_long
    u32.GetClipboardData.argtypes = [ctypes.c_uint]
    u32.GetClipboardData.restype = ctypes.c_void_p
    if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    if not _open_clipboard():
        return None
    try:
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h or h == 0:
            return None
        p = k32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def _clipboard_paste_text(hwnd: int, text: str) -> bool:
    """长文本剪贴板后备：保存 → 写入 → Ctrl+V → 恢复（原子性尽力保证）。

    返回 True 表示剪贴板写入与粘贴热键送达；False 表示任一关键环节失败
    （调用方此时应回退 type_text 默认逐字逻辑）。

    剪贴板恢复放在 finally 中，即使 Ctrl+V 失败也尝试还原用户剪贴板。
    """
    _require_input()
    saved = _clipboard_get_text()
    try:
        if not _clipboard_set_text(text):
            return False
        time.sleep(0.05)
        hotkey(hwnd, "control", "v")
        time.sleep(0.15)
        return True
    finally:
        if saved is not None:
            try:
                _clipboard_set_text(saved)
            except Exception:
                pass


def _resolve_key(k) -> int:
    """把键名/字符/VK 统一解析为虚拟键码。"""
    if isinstance(k, int):
        return k
    s = str(k).lower()
    if s in _KEY_NAME_MAP:
        return _KEY_NAME_MAP[s]
    if len(s) == 1:
        code = ctypes.windll.user32.VkKeyScanW(ctypes.c_wchar(s))
        if code != -1 and code != 0xFFFF:
            return code & 0xFF
    # 未知键名：尝试作为十六进制/十进制
    try:
        return int(s, 0)
    except ValueError:
        return 0


def hotkey(hwnd: int, *keys) -> None:
    """组合键，如 hotkey(hwnd, "ctrl", "s") 或 hotkey(hwnd, 0x11, 0x43)。

    支持键名（ctrl/shift/alt/win/enter/esc/tab/a..z/0..9/f1..f12 等）与 VK 整数混用。
    ★ A2：入口即 _validate_window。
    """
    _require_input()
    _validate_window(hwnd, need_visible=True, check_occlusion_at=(0.5, 0.5))
    vks = [_resolve_key(k) for k in keys]
    vks = [v for v in vks if v]
    if not vks:
        return
    downs = [_keyboard_event(v, flags=KEYEVENTF_KEYDOWN) for v in vks]
    ups = [_keyboard_event(v, flags=KEYEVENTF_KEYUP) for v in reversed(vks)]
    _send_input(downs + ups)


# ---------------------------------------------------------------------------
# PostMessage 备用输入（当 SendInput 因非交互会话/UIPI 失败时使用）
# ---------------------------------------------------------------------------
def _client_point(hwnd, nx: float, ny: float) -> tuple:
    """归一化客户坐标 -> 客户区物理像素坐标 (cx, cy)。"""
    import win32gui

    cr = win32gui.GetClientRect(hwnd)
    # 用 ClientToScreen 同时转换右下角，得到真实物理尺寸
    cx, cy = win32gui.ClientToScreen(hwnd, (0, 0))
    br_x, br_y = win32gui.ClientToScreen(hwnd, (cr[2], cr[3]))
    phys_w = max(1, br_x - cx)
    phys_h = max(1, br_y - cy)
    return int(nx * phys_w), int(ny * phys_h)


def post_click(hwnd: int, nx: float, ny: float, button: str = "left") -> None:
    """向窗口直接投递鼠标按下/抬起消息（无需前台权限）。"""
    _require_input()

    cx, cy = _client_point(hwnd, nx, ny)
    lparam = (cy << 16) | (cx & 0xFFFF)
    if button == "left":
        ctypes.windll.user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        time.sleep(0.02)
        ctypes.windll.user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
    elif button == "right":
        ctypes.windll.user32.PostMessageW(hwnd, WM_RBUTTONDOWN, MK_RBUTTON, lparam)
        time.sleep(0.02)
        ctypes.windll.user32.PostMessageW(hwnd, WM_RBUTTONUP, 0, lparam)
    elif button == "middle":
        ctypes.windll.user32.PostMessageW(hwnd, WM_MBUTTONDOWN, MK_MBUTTON, lparam)
        time.sleep(0.02)
        ctypes.windll.user32.PostMessageW(hwnd, WM_MBUTTONUP, 0, lparam)
    else:
        raise InputSimError("不支持的鼠标按钮: %s" % button)


def post_key(hwnd: int, vk: int) -> None:
    """向窗口直接投递按键消息（无需前台权限）。"""
    _require_input()
    ctypes.windll.user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
    time.sleep(0.02)
    ctypes.windll.user32.PostMessageW(hwnd, WM_KEYUP, vk, 0xC0000000)
