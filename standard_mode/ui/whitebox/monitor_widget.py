# -*- coding: utf-8 -*-
"""
MonitorWidget — 资源占用监控
=============================
周期性采集内存/CPU占用，超阈值在状态栏显示警告。
"""
from __future__ import annotations

import os
import time
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QLabel, QWidget

from ui.design.tokens import Lemon


class MonitorWidget(QLabel):
    warning_triggered = pyqtSignal(str)
    warning_cleared = pyqtSignal()

    MEM_WARNING_MB = 1024
    CPU_WARNING_PCT = 90
    SAMPLE_INTERVAL_MS = 10000

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._warning_active = False
        self._init_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._sample)
        self._timer.start(self.SAMPLE_INTERVAL_MS)
        self._sample()

    def _init_ui(self):
        T = Lemon
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: 10px; "
            f"font-family: '{T.FONT}'; background: transparent; border: none; "
            f"padding: 0 4px;"
        )
        self.setFixedWidth(100)
        self.setToolTip("资源监控")

    def _sample(self):
        mem_mb = self._get_memory_mb()
        cpu_pct = self._get_cpu_pct()
        if mem_mb is not None and cpu_pct is not None:
            self.setText(f"{mem_mb:.0f}MB | {cpu_pct:.0f}%")
            if mem_mb > self.MEM_WARNING_MB or cpu_pct > self.CPU_WARNING_PCT:
                if not self._warning_active:
                    self._warning_active = True
                    self.setStyleSheet(
                        f"color: {Lemon.ACCENT_ORANGE}; font-size: 10px; "
                        f"font-family: '{Lemon.FONT}'; background: transparent; "
                        f"border: none; padding: 0 4px;"
                    )
                    msg = f"内存 {mem_mb:.0f}MB" if mem_mb > self.MEM_WARNING_MB else f"CPU {cpu_pct:.0f}%"
                    self.warning_triggered.emit(msg)
            else:
                if self._warning_active:
                    self._warning_active = False
                    self.setStyleSheet(
                        f"color: {Lemon.TEXT_MUTED}; font-size: 10px; "
                        f"font-family: '{Lemon.FONT}'; background: transparent; "
                        f"border: none; padding: 0 4px;"
                    )
                    self.warning_cleared.emit()

    @staticmethod
    def _get_memory_mb() -> float:
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            return proc.memory_info().rss / 1024 / 1024
        except ImportError:
            try:
                import resource
                return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            except Exception:
                return -1
        except Exception:
            return -1

    @staticmethod
    def _get_cpu_pct() -> float:
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            return proc.cpu_percent(interval=0.1)
        except Exception:
            return -1
