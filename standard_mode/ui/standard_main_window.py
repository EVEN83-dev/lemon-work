# -*- coding: utf-8 -*-
"""
标准模式主窗口

继承自 MIMOWindow，但：
- 跳过混合模式页面创建
- 只保留原始模式、单AI模式、多AI模式
- 独立的引擎管理
"""

import sys
import os

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import pyqtSignal, Qt

# 导入原始主窗口
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.main_window import MIMOWindow


class StandardMainWindow(MIMOWindow):
    """
    标准模式主窗口

    与 MIMOWindow 的区别：
    - _create_hybrid_page() 被覆盖为空实现
    - 不初始化混合模式相关信号
    - 只使用 MIMO Code 和 Ollama 引擎
    """

    # 信号
    mode_changed = pyqtSignal(str)

    def __init__(self):
        """初始化标准模式主窗口"""
        # 设置标志，告知父类跳过混合模式
        self._skip_hybrid_mode = True

        # 调用父类初始化
        super().__init__()

        print("[StandardMainWindow] 标准模式窗口初始化完成")

    def _create_hybrid_page(self):
        """覆盖父类方法：跳过混合模式页面创建"""
        print("[StandardMainWindow] 跳过混合模式页面创建（标准模式独立运行）")
        # 创建空白占位符，避免布局错误
        placeholder = QWidget()
        placeholder.setObjectName("hybrid_placeholder")
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(0, 0, 0, 0)
        return placeholder

    def _connect_signals(self):
        """连接信号（跳过混合模式相关信号）"""
        # 调用父类的信号连接
        super()._connect_signals()

        # 移除混合模式信号连接（如果存在）
        if hasattr(self, 'hybrid_mode_panel') and self.hybrid_mode_panel:
            try:
                self.hybrid_mode_panel.command_sent.disconnect()
                self.hybrid_mode_panel.nav_action.disconnect()
                self.hybrid_mode_panel.workflow_step.disconnect()
            except Exception:
                pass

        print("[StandardMainWindow] 信号连接完成（不含混合模式）")

    def get_active_engine(self):
        """获取当前活动引擎"""
        if hasattr(self, '_engine_manager'):
            return self._engine_manager.get_active_engine()
        return None

    def switch_engine(self, engine_name: str):
        """切换引擎"""
        if hasattr(self, '_engine_manager'):
            try:
                self._engine_manager.switch_engine(engine_name)
                self.mode_changed.emit(engine_name)
                print(f"[StandardMainWindow] 切换引擎: {engine_name}")
                return True
            except Exception as e:
                print(f"[StandardMainWindow] 切换引擎失败: {e}")
                return False
        return False


# ============================================================
# 测试入口
# ============================================================

if __name__ == '__main__':
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = StandardMainWindow()
    window.show()
    sys.exit(app.exec_())