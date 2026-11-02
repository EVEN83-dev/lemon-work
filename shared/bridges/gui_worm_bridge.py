# -*- coding: utf-8 -*-
"""
GUI Worm Bridge — GUI界面同步虫桥
================================================
核心思路：Agent 作为"信号发射器/接收器"，与原版 MIMO Code GUI 进行界面同步

架构设计：
┌─────────────────────────────────────────────────────────────┐
│                     MIMO Code Agent                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────────────────┐  │
│  │ 文件树  │  │ 代码区  │  │      MIMO Panel (显示层)     │  │
│  │(本地)   │  │(本地)   │  │  ┌─────────────────────────┐│  │
│  └─────────┘  └─────────┘  │  │  GUI Worm Bridge        ││  │
│                            │  │  ┌───────────────────┐  ││  │
│                            │  │  │ pyautogui         │  ││  │
│                            │  │  │ ↓ 模拟打字到输入框│  ││  │
│                            │  │  │ ↑ 截图OCR读取输出│  ││  │
│                            │  │  └───────────────────┘  ││  │
│                            │  └─────────────────────────┘│  │
│                            └─────────────────────────────┘  │
└───────────────────────────│───────────────────────────────│─┘
                            │  pyautogui / win32gui         │
                            ↓                               ↓
┌─────────────────────────────────────────────────────────────┐
│              原版 MIMO Code GUI（前台可见窗口）               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  MiMo Code GUI 界面                                      ││
│  │  - 输入框：接收 Agent 发来的消息                          ││
│  │  - 输出区：思考/回复内容 → 截图 OCR → 映射回 Agent         ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘

实现方式：
1. 启动原版 MIMO Code GUI（os.startfile 模拟双击）
2. 使用 win32gui 找到窗口句柄
3. 使用 pyautogui 向输入框发送文本
4. 定期截图 OCR 或读取控制台缓冲区获取输出
"""

import os, sys, time, threading, subprocess
import pyautogui
import win32gui
import win32con
import win32clipboard
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from typing import Optional, List, Tuple
import logging

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('gui_worm_bridge.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# 路径配置
# ============================================================
_XIAOMI_AI_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "小米AI")
_MIMO_NODE_GLOBAL = os.path.join(_XIAOMI_AI_ROOT, "node_global")
MIMO_BAT = os.path.join(_MIMO_NODE_GLOBAL, "启动MIMICode.bat")

# 设置 pyautogui 安全措施
pyautogui.PAUSE = 0.1  # 每次操作间隔 0.1 秒
pyautogui.FAILSAFE = True  # 鼠标移动到左上角可中断


# ============================================================
# GUI Worm Bridge — 界面同步虫桥
# ============================================================
class GUIWormBridge(QObject):
    """
    GUI Worm Bridge — 界面同步虫桥
    
    通过 pyautogui 和 win32gui 实现与原版 MIMO Code GUI 的界面同步：
    - 启动 MIMO Code GUI
    - 找到窗口句柄
    - 发送消息到输入框
    - 监听输出内容
    """
    
    # PyQt 信号
    gui_started = pyqtSignal()             # MIMO Code GUI 已启动
    gui_found = pyqtSignal(int)            # 找到窗口句柄
    output_received = pyqtSignal(str)      # 收到输出内容
    thinking_received = pyqtSignal(str)    # 收到思考内容
    error_occurred = pyqtSignal(str)       # 错误
    task_started = pyqtSignal(str)         # 任务开始
    task_finished = pyqtSignal(int)        # 任务完成
    
    # 窗口标题（实际是 "MiMoCode" 无空格）
    MIMO_WINDOW_TITLE = "MiMoCode"
    
    def __init__(self, project_path: str = None):
        super().__init__()
        self.project_path = os.path.abspath(project_path or os.getcwd())
        self._mimo_hwnd: Optional[int] = None
        self._running = False
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        
    # ================================================================
    # 启动 MIMO Code GUI
    # ================================================================
    def start_mimo_gui(self) -> bool:
        """连接已运行的 MIMO Code GUI（不自动启动）"""
        try:
            print(f"[GUI虫桥] 开始查找已运行的 MIMO Code 窗口...")
            sys.stdout.flush()
            
            # 先查找已存在的窗口（不启动新实例）
            if not self._find_mimo_window(timeout=10):
                # 如果没找到，尝试启动
                print(f"[GUI虫桥] 未找到已运行的窗口，尝试启动...")
                sys.stdout.flush()
                if os.path.exists(MIMO_BAT):
                    os.startfile(MIMO_BAT)
                    print(f"[GUI虫桥] 等待窗口出现...")
                    sys.stdout.flush()
                    time.sleep(5)
                    if not self._find_mimo_window(timeout=15):
                        print(f"[GUI虫桥] 错误: 无法找到 MIMO Code 窗口")
                        self.error_occurred.emit("无法找到 MIMO Code 窗口")
                        return False
                else:
                    print(f"[GUI虫桥] 错误: 批处理文件不存在")
                    self.error_occurred.emit(f"批处理文件不存在: {MIMO_BAT}")
                    return False
            
            print(f"[GUI虫桥] 窗口已找到，句柄: {self._mimo_hwnd}")
            sys.stdout.flush()
            self.gui_started.emit()
            
            # 启动输出监听线程
            self._start_output_monitor()
            print(f"[GUI虫桥] 输出监听线程已启动")
            sys.stdout.flush()
            
            return True
            
        except Exception as e:
            print(f"[GUI虫桥] 异常: {e}")
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            self.error_occurred.emit(f"启动 MIMO Code GUI 失败: {e}")
            return False
    
    def _find_mimo_window(self, timeout: int = 30) -> bool:
        """查找 MIMO Code 窗口（通过进程名和窗口类名）"""
        start = time.time()
        attempt = 0
        while time.time() - start < timeout:
            attempt += 1
            found_hwnd = None
            all_titles = []
            
            def enum_callback(hwnd, _):
                nonlocal found_hwnd
                try:
                    if win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        class_name = win32gui.GetClassName(hwnd)
                        if title:
                            all_titles.append(title)
                            # 排除Agent自己的窗口
                            if 'agent' in title.lower():
                                return True
                            # MIMO Code 的窗口标题格式是 "MC | 会话名"
                            # 窗口类名是 CASCADIA_HOSTING_WINDOW_CLASS (Electron)
                            if title.startswith('MC |') or class_name == 'CASCADIA_HOSTING_WINDOW_CLASS':
                                found_hwnd = hwnd
                                return False  # 停止枚举
                except Exception:
                    pass
                return True
            
            try:
                win32gui.EnumWindows(enum_callback, None)
            except Exception as e:
                logger.debug(f"EnumWindows 异常: {e}")
            
            if found_hwnd:
                self._mimo_hwnd = found_hwnd
                title = win32gui.GetWindowText(found_hwnd)
                logger.info(f"找到窗口: hwnd={found_hwnd}, title='{title}'")
                self.gui_found.emit(found_hwnd)
                return True
            
            if attempt <= 3:
                logger.debug(f"第 {attempt} 次尝试，未找到窗口。当前可见窗口: {all_titles[:10]}")
            
            time.sleep(1)
        
        logger.warning(f"超时未找到窗口，已等待 {timeout} 秒")
        return False
    
    # ================================================================
    # 发送消息到 MIMO Code 输入框
    # ================================================================
    def _find_input_child_window(self, parent_hwnd):
        """找到 MIMO Code 中输入框所在的子窗口（Electron WebView）"""
        found = [None]
        
        def enum_child_cb(child_hwnd, _):
            try:
                class_name = win32gui.GetClassName(child_hwnd)
                # Electron 的 WebView 子窗口类名
                if 'Chrome_RenderWidgetHostHWND' in class_name or 'CASCADIA' in class_name:
                    found[0] = child_hwnd
                    return False
            except Exception:
                pass
            return True
        
        win32gui.EnumChildWindows(parent_hwnd, enum_child_cb, None)
        return found[0]
    
    def _send_enter_key(self):
        """发送回车键 — 多种方式尝试，确保 Electron 应用能接收到"""
        import ctypes
        
        # === 方式1: PostMessage 直接对子窗口发送 WM_KEYDOWN/WM_UP ===
        VK_RETURN = 0x0D
        WM_KEYDOWN = 0x0100
        WM_KEYUP = 0x0101
        WM_CHAR = 0x0102
        SCANCODE_ENTER = 0x1C
        MAPVK_VK_TO_VSC = 0
        
        user32 = ctypes.windll.user32
        
        # 找到输入框子窗口
        child_hwnd = self._find_input_child_window(self._mimo_hwnd)
        target_hwnd = child_hwnd or self._mimo_hwnd
        logger.info(f"发送回车目标窗口: hwnd={target_hwnd}")
        
        # 方式1: PostMessage WM_KEYDOWN + WM_KEYUP 到目标窗口
        for _ in range(3):
            lparam = 1 | (SCANCODE_ENTER << 16)  # repeat=1, scancode, no extra flags
            user32.PostMessageW(target_hwnd, WM_KEYDOWN, VK_RETURN, lparam)
            time.sleep(0.05)
            user32.PostMessageW(target_hwnd, WM_KEYUP, VK_RETURN, lparam | 0xC0000000)
            time.sleep(0.1)
        
        # 方式2: 同时发送 WM_CHAR (\r) 确保内容被提交
        user32.PostMessageW(target_hwnd, WM_CHAR, 0x0D, 0)
        time.sleep(0.05)
        
        # 方式3: SendInput 全局回车（兜底）
        KEYEVENTF_KEYUP = 0x0002
        INPUT_KEYBOARD = 1
        
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.c_void_p)]
        
        class INPUT(ctypes.Structure):
            class _U(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]
            _anonymous_ = ("_u",)
            _fields_ = [("type", ctypes.c_ulong), ("_u", _U)]
        
        # 带 scan code 的 SendInput
        ki_down = KEYBDINPUT(VK_RETURN, SCANCODE_ENTER, 0, 0, None)
        input_down = INPUT(INPUT_KEYBOARD, ki_down)
        ki_up = KEYBDINPUT(VK_RETURN, SCANCODE_ENTER, KEYEVENTF_KEYUP, 0, None)
        input_up = INPUT(INPUT_KEYBOARD, ki_up)
        inputs = (INPUT * 2)(input_down, input_up)
        result = user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
        logger.info(f"SendInput 结果: {result}")
        time.sleep(0.15)
        
        # 方式4: pyautogui 回车（最终兜底）
        pyautogui.press('enter')
        time.sleep(0.1)
        logger.info("回车发送完成（多种方式）")
    
    def _dismiss_popup(self):
        """检测并关闭 MIMO Code 的弹窗（如"订阅token plan"、"知道了"等）"""
        if not self._mimo_hwnd:
            return
        
        popup_keywords = ['知道了', '知道了', 'Got it', 'OK', '关闭', 'Close',
                          '订阅', 'Subscribe', '排队', 'Queue', 'Token']
        
        def find_popup_button(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    class_name = win32gui.GetClassName(hwnd)
                    # 查找按钮类或包含关键词的窗口
                    if 'Button' in class_name or any(kw in title for kw in popup_keywords):
                        rect = win32gui.GetWindowRect(hwnd)
                        cx = (rect[0] + rect[2]) // 2
                        cy = (rect[1] + rect[3]) // 2
                        # 确保按钮在 MIMO Code 窗口范围内
                        mimo_rect = win32gui.GetWindowRect(self._mimo_hwnd)
                        if (mimo_rect[0] <= cx <= mimo_rect[2] and
                            mimo_rect[1] <= cy <= mimo_rect[3]):
                            logger.info(f"发现弹窗按钮: '{title}' at ({cx}, {cy})")
                            pyautogui.click(cx, cy)
                            time.sleep(0.3)
                            self.output_received.emit(
                                f"<span style='color:Lemon.ACCENT_ORANGE;'>🔔 已自动关闭弹窗: {title}</span>"
                            )
                            return False
            except Exception:
                pass
            return True
        
        # 先枚举 MIMO Code 的子窗口
        win32gui.EnumChildWindows(self._mimo_hwnd, find_popup_button, None)
        
        # 再枚举所有顶层窗口（弹窗可能是独立窗口）
        def find_top_popup(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd) and hwnd != self._mimo_hwnd:
                    title = win32gui.GetWindowText(hwnd)
                    if any(kw in title for kw in popup_keywords):
                        # 点击窗口中央关闭
                        rect = win32gui.GetWindowRect(hwnd)
                        cx = (rect[0] + rect[2]) // 2
                        cy = (rect[1] + rect[3]) // 2
                        pyautogui.click(cx, cy)
                        time.sleep(0.3)
                        self.output_received.emit(
                            f"<span style='color:Lemon.ACCENT_ORANGE;'> 已自动关闭弹窗: {title}</span>"
                        )
                        return False
            except Exception:
                pass
            return True
        
        win32gui.EnumWindows(find_top_popup, None)
    
    def send_message(self, message: str) -> bool:
        """发送消息到 MIMO Code GUI 的输入框（支持中文）"""
        if not self._mimo_hwnd:
            self.error_occurred.emit("MIMO Code 窗口未找到")
            return False
        
        self._running = True
        self.task_started.emit(message)
        
        try:
            # 0. 先检查并关闭可能的弹窗
            self._dismiss_popup()
            time.sleep(0.5)
            
            # 1. 强制激活窗口到前台
            win32gui.ShowWindow(self._mimo_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(self._mimo_hwnd)
            time.sleep(0.8)
            
            # 2. 获取窗口位置
            rect = win32gui.GetWindowRect(self._mimo_hwnd)
            window_width = rect[2] - rect[0]
            window_height = rect[3] - rect[1]
            
            # 3. 点击输入框位置（底部中央偏下，MIMO Code 输入框通常在底部）
            input_x = rect[0] + window_width // 2
            input_y = rect[3] - 100  # 调整到更靠近底部
            logger.info(f"点击输入框位置: ({input_x}, {input_y})")
            
            # 单击激活输入框
            pyautogui.click(input_x, input_y)
            time.sleep(0.5)
            
            # 再次单击确保焦点
            pyautogui.click(input_x, input_y)
            time.sleep(0.3)
            
            # 4. 全选清空输入框
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.2)
            pyautogui.press('delete')
            time.sleep(0.2)
            
            # 5. 使用剪贴板粘贴消息（支持中文）
            self._set_clipboard(message)
            time.sleep(0.1)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.6)
            
            # 6. 再次确保 MIMO Code 窗口在前台并有焦点
            win32gui.SetForegroundWindow(self._mimo_hwnd)
            time.sleep(0.3)
            
            # 7. 点击输入框确保焦点
            pyautogui.click(input_x, input_y)
            time.sleep(0.3)
            
            # 8. 用多种方式发送回车
            self._send_enter_key()
            time.sleep(0.5)
            
            self.output_received.emit(f"<span style='color:Lemon.ACCENT_GREEN;'>✓ 已发送: {message}</span>")
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"发送消息失败: {e}")
            self._running = False
            self.task_finished.emit(-1)
            return False
    
    def _set_clipboard(self, text: str):
        """设置剪贴板内容"""
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    
    # ================================================================
    # 输出监听
    # ================================================================
    def _start_output_monitor(self):
        """启动输出监听线程"""
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_output, daemon=True)
        self._monitor_thread.start()
    
    def _monitor_output(self):
        """监听 MIMO Code 的输出（通过数据库 part 表 + actor_registry 状态）"""
        import sqlite3
        import json
        
        db_path = os.path.join(_MIMO_NODE_GLOBAL, "data", "mimocode", "mimocode.db")
        last_part_id = None
        last_title = ""
        last_actor_status = ""
        
        # 获取当前最新的 part ID
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM part ORDER BY rowid DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                last_part_id = row[0]
            conn.close()
            logger.info(f"开始监听数据库，当前最新 part ID: {last_part_id}")
        except Exception as e:
            logger.error(f"初始化数据库监听失败: {e}")
        
        while not self._stop_event.is_set():
            try:
                # 1. 监听窗口标题变化
                if self._mimo_hwnd and win32gui.IsWindowVisible(self._mimo_hwnd):
                    current_title = win32gui.GetWindowText(self._mimo_hwnd)
                    if current_title != last_title:
                        if current_title != self.MIMO_WINDOW_TITLE:
                            self.output_received.emit(
                                f"<span style='color:Lemon.ACCENT_BLUE;'>[状态] {current_title}</span>"
                            )
                        last_title = current_title
                
                # 2. 监听数据库 part 表的新增记录
                if os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    
                    # 查询新增的 part
                    if last_part_id:
                        cursor.execute(
                            "SELECT id, message_id, data FROM part WHERE rowid > (SELECT rowid FROM part WHERE id=?) ORDER BY rowid",
                            (last_part_id,)
                        )
                    else:
                        cursor.execute("SELECT id, message_id, data FROM part ORDER BY rowid DESC LIMIT 10")
                    
                    new_parts = cursor.fetchall()
                    
                    # 3. 同时检查 actor_registry 的错误状态
                    cursor.execute(
                        "SELECT status, last_error FROM actor_registry ORDER BY rowid DESC LIMIT 1"
                    )
                    actor_row = cursor.fetchone()
                    conn.close()
                    
                    if actor_row:
                        actor_status, actor_error = actor_row
                        status_key = f"{actor_status}:{actor_error or ''}"
                        if status_key != last_actor_status and actor_error:
                            last_actor_status = status_key
                            safe_error = actor_error.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            self.output_received.emit(
                                f"<span style='color:Lemon.ACCENT_ORANGE;'>⚠ Agent状态: {actor_status} - {safe_error}</span>"
                            )
                    
                    # 处理新增的 part
                    for part_id, message_id, data_json in new_parts:
                        try:
                            data = json.loads(data_json)
                            part_type = data.get('type', '')
                            
                            if part_type == 'text':
                                text = data.get('text', '').strip()
                                if text:
                                    safe_text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                                    self.output_received.emit(
                                        f"<span style='color:Lemon.PLACEHOLDER;'>{safe_text}</span>"
                                    )
                            
                            elif part_type == 'reasoning':
                                reasoning = data.get('text', '').strip()
                                if reasoning:
                                    safe_reasoning = reasoning.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                                    self.thinking_received.emit(
                                        f"<span style='color:#888;font-style:italic;'>💭 {safe_reasoning[:200]}...</span>"
                                    )
                            
                            elif part_type == 'step-start':
                                self.output_received.emit(
                                    f"<span style='color:Lemon.ACCENT_BLUE;'>⚡ 开始执行...</span>"
                                )
                            
                            elif part_type == 'step-finish':
                                self.output_received.emit(
                                    f"<span style='color:Lemon.ACCENT_GREEN;'>✓ 步骤完成</span>"
                                )
                                self.task_finished.emit(0)
                            
                            elif part_type == 'tool':
                                tool_name = data.get('tool', 'unknown')
                                state = data.get('state', {})
                                status = state.get('status', '')
                                if status == 'running':
                                    self.output_received.emit(
                                        f"<span style='color:Lemon.ACCENT_ORANGE;'>🔧 调用工具: {tool_name}...</span>"
                                    )
                                elif status == 'completed':
                                    self.output_received.emit(
                                        f"<span style='color:Lemon.ACCENT_GREEN;'>✅ 工具 {tool_name} 完成</span>"
                                    )
                                elif status == 'error':
                                    error_msg = state.get('error', '未知错误')
                                    safe_error = error_msg.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                                    self.output_received.emit(
                                        f"<span style='color:Lemon.ACCENT_RED;'>❌ 工具 {tool_name} 错误: {safe_error}</span>"
                                    )
                            
                            elif part_type == 'file':
                                file_name = data.get('name', data.get('path', 'unknown'))
                                file_op = data.get('operation', data.get('action', ''))
                                self.output_received.emit(
                                    f"<span style='color:#2196f3;'>📄 文件 {file_op}: {file_name}</span>"
                                )
                            
                            last_part_id = part_id
                            
                        except json.JSONDecodeError as e:
                            logger.debug(f"解析 part 数据失败: {e}")
                            last_part_id = part_id
                
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"监听错误: {e}", exc_info=True)
                self.error_occurred.emit(f"监听错误: {e}")
                time.sleep(5)
    
    # ================================================================
    # 控制
    # ================================================================
    def stop(self):
        """停止虫桥"""
        self._stop_event.set()
        self._running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)
    
    def is_running(self) -> bool:
        return self._running
    
    def get_window_handle(self) -> Optional[int]:
        return self._mimo_hwnd


# ============================================================
# 测试代码
# ============================================================
if __name__ == "__main__":
    bridge = GUIWormBridge()
    
    def on_output(text):
        print(f"[输出] {text}")
    
    def on_error(err):
        print(f"[错误] {err}")
    
    bridge.output_received.connect(on_output)
    bridge.error_occurred.connect(on_error)
    
    print("启动 MIMO Code GUI...")
    if bridge.start_mimo_gui():
        print("MIMO Code GUI 已启动，等待 5 秒...")
        time.sleep(5)
        
        print("发送测试消息...")
        bridge.send_message("你好")
        
        print("等待 10 秒观察输出...")
        time.sleep(10)
    
    bridge.stop()
    print("测试完成")