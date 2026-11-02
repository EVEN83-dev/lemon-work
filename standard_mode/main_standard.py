# -*- coding: utf-8 -*-
"""
标准模式独立启动脚本

目标：
- 只启动标准模式组件
- 不初始化混合模式
- 右侧栏使用 Lemon Code / LLAMA 引擎
- 底部终端同步日志

★ FROZEN 标记：
- 标准模式已锁定，请勿修改此文件中的核心逻辑
"""

# ============================================================
# ★★★ FROZEN 标记（已解除，2026-08-08 作者授权） ★★★
# 口令校验通过：天津职业技术师范大学。解除后核心改动仍须 CodeLock 留痕，
# 且仅"在现有技术基础上完善，不得破坏架构"。
# ============================================================
STANDARD_MODE_FROZEN = False
FREEZE_VERSION = "1.0"
FREEZE_DATE = "2026-07-24"
FREEZE_REASON = "标准模式功能已验证通过，为防止混合模式开发破坏，已锁定（已于 2026-08-08 由作者授权解除）"
# ============================================================

import sys
import os
import time

# ★ 关键：正确设置 sys.path
# main_standard.py 位于 standard_mode/ 目录
# 需要将 standard_mode 目录添加到 sys.path，使得 from core.xxx 可以正确导入
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# 同时添加项目根目录（用于可能的共享模块导入）
LEMON_AGENT_ROOT = os.path.dirname(PROJECT_ROOT)
if LEMON_AGENT_ROOT not in sys.path:
    sys.path.insert(0, LEMON_AGENT_ROOT)

# 禁用混合模式（通过环境变量）
os.environ['LEMONCODE_SKIP_HYBRID'] = '1'
os.environ['LEMONCODE_MODE'] = 'standard'

# QWebEngine 必须先导入
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QTimer

_START_TIME = time.time()

def main():
    """标准模式主入口"""
    print("=" * 60)
    print("Lemon Code - 标准模式")
    print("=" * 60)

    # 1. 初始化崩溃恢复
    try:
        from core.crash_recovery import CrashRecovery
        crash_recovery = CrashRecovery()
        crash_recovery.install_excepthook()
        crash_recovery.install_threading_excepthook()
        print("[Standard] 崩溃恢复系统已启用")
    except Exception as e:
        print(f"[Standard] 崩溃恢复系统初始化失败: {e}")

    # 2. 创建应用
    os.environ['QTWEBENGINE_REMOTE_DEBUGGING'] = '9222'
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setFont(QFont('Segoe UI', 14))

    qt_init_time = time.time() - _START_TIME
    print(f"[Standard] QApplication 初始化耗时: {qt_init_time:.2f}s")

    # 3. 初始化引擎管理器（只有MIMO和Ollama，不含混合模式）
    print("[Standard] 正在初始化引擎管理器...")
    from core.engine_manager import get_engine_manager
    engine_manager = get_engine_manager()

    # 注册标准模式引擎
    from core.ollama_engine import OllamaEngine
    ollama_engine = OllamaEngine()
    engine_manager.register_engine("ollama", ollama_engine)

    print(f"[Standard] 可用引擎: {engine_manager.list_engines()}")

    # 4. 创建主窗口（标准模式版）
    print("[Standard] 正在创建主窗口...")
    from ui.standard_main_window import StandardMainWindow
    window = StandardMainWindow()
    window.show()

    window_create_time = time.time() - _START_TIME
    print(f"[Standard] 主窗口创建耗时: {window_create_time:.2f}s")

    # 5. 注入引擎管理器
    if hasattr(window, 'mimo_panel') and hasattr(window.mimo_panel, 'set_engine_manager'):
        window.mimo_panel.set_engine_manager(engine_manager)
        print("[Standard] 引擎管理器已注入")

    # 6. 启动MIMO Code服务
    print("[Standard] 正在启动 Lemon Code 服务...")
    if hasattr(window, 'serve_bridge'):
        window.serve_bridge.start()
        print("[Standard] Lemon Code 服务已启动 (端口 4097)")

    # 7. 内存监控（可选）
    try:
        import psutil
        process = psutil.Process()

        def check_memory():
            mem = process.memory_info()
            if mem.rss > 500 * 1024 * 1024:  # 500MB
                print(f"[Memory] 警告: RSS={mem.rss / 1024 / 1024:.1f}MB")

        timer = QTimer()
        timer.timeout.connect(check_memory)
        timer.start(30000)  # 30秒检查一次
    except ImportError:
        pass

    total_time = time.time() - _START_TIME
    print(f"[Standard] 启动完成，总耗时: {total_time:.2f}s")

    # 8. 运行应用
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()