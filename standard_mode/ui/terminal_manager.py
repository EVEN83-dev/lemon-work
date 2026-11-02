# -*- coding: utf-8 -*-
"""
多终端管理器 — 支持多个独立终端会话
====================================
对标 VS Code / PyCharm 的多终端架构：
- 每个终端独立 PTY 进程
- 独立历史记录
- 独立工作目录
- 可持久化配置

使用方式：
    manager = TerminalManager()
    term_id = manager.create_terminal(name="PowerShell", cwd="D:/project")
    manager.switch_terminal(term_id)
    manager.close_terminal(term_id)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QWidget


class TerminalInstance:
    """单个终端实例的元数据"""
    
    def __init__(
        self,
        term_id: str,
        name: str,
        cwd: str,
        shell: Optional[List[str]] = None,
    ):
        self.id = term_id
        self.name = name
        self.cwd = cwd
        self.shell = shell or []
        self.panel: Optional[QWidget] = None
        self.created_at = datetime.now()
        self.last_active = datetime.now()
    
    def update_active(self):
        """更新最后活跃时间"""
        self.last_active = datetime.now()


class TerminalManager(QObject):
    """多终端管理器"""
    
    # 信号
    terminal_created = pyqtSignal(str)    # term_id
    terminal_closed = pyqtSignal(str)     # term_id
    terminal_switched = pyqtSignal(str)   # term_id
    terminal_renamed = pyqtSignal(str, str)  # term_id, new_name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._terminals: Dict[str, TerminalInstance] = {}
        self._active_id: Optional[str] = None
        self._terminal_count = 0  # 用于生成默认名称
    
    # ============================================================
    # 终端创建/关闭
    # ============================================================
    def create_terminal(
        self,
        name: Optional[str] = None,
        cwd: Optional[str] = None,
        shell: Optional[List[str]] = None,
    ) -> str:
        """创建新终端，返回终端 ID"""
        # 生成唯一 ID
        term_id = f"term_{uuid.uuid4().hex[:8]}"
        
        # 生成默认名称
        if not name:
            self._terminal_count += 1
            name = f"终端 {self._terminal_count}"
        
        # 默认工作目录
        if not cwd:
            cwd = os.getcwd()
        
        # 创建实例
        instance = TerminalInstance(
            term_id=term_id,
            name=name,
            cwd=cwd,
            shell=shell,
        )
        
        self._terminals[term_id] = instance
        self.terminal_created.emit(term_id)
        
        # 如果是第一个终端，自动激活
        if len(self._terminals) == 1:
            self.switch_terminal(term_id)
        
        return term_id
    
    def close_terminal(self, term_id: str) -> bool:
        """关闭终端"""
        if term_id not in self._terminals:
            return False
        
        instance = self._terminals[term_id]
        
        # 关闭面板
        if instance.panel:
            try:
                # 调用 shutdown 清理资源
                if hasattr(instance.panel, 'shutdown'):
                    instance.panel.shutdown()
                instance.panel.deleteLater()
            except Exception as e:
                print(f"[TerminalManager] 关闭面板失败: {e}", flush=True)
            instance.panel = None
        
        # 从字典移除
        del self._terminals[term_id]
        self.terminal_closed.emit(term_id)
        
        # 如果关闭的是当前激活的，切换到其他
        if self._active_id == term_id:
            self._active_id = None
            if self._terminals:
                # 切换到最近活跃的
                sorted_terms = sorted(
                    self._terminals.values(),
                    key=lambda t: t.last_active,
                    reverse=True
                )
                self.switch_terminal(sorted_terms[0].id)
        
        return True
    
    def close_all(self):
        """关闭所有终端"""
        term_ids = list(self._terminals.keys())
        for term_id in term_ids:
            self.close_terminal(term_id)
    
    # ============================================================
    # 终端切换
    # ============================================================
    def switch_terminal(self, term_id: str) -> bool:
        """切换到指定终端"""
        if term_id not in self._terminals:
            return False
        
        old_id = self._active_id
        self._active_id = term_id
        
        # 更新活跃时间
        self._terminals[term_id].update_active()
        
        if old_id != term_id:
            self.terminal_switched.emit(term_id)
        
        return True
    
    # ============================================================
    # 终端信息
    # ============================================================
    def get_terminal(self, term_id: str) -> Optional[TerminalInstance]:
        """获取终端实例"""
        return self._terminals.get(term_id)
    
    def get_active_terminal(self) -> Optional[TerminalInstance]:
        """获取当前激活的终端"""
        if self._active_id:
            return self._terminals.get(self._active_id)
        return None
    
    def get_all_terminals(self) -> List[TerminalInstance]:
        """获取所有终端（按创建时间排序）"""
        return sorted(
            self._terminals.values(),
            key=lambda t: t.created_at
        )
    
    def get_terminal_count(self) -> int:
        """获取终端数量"""
        return len(self._terminals)
    
    def has_terminal(self, term_id: str) -> bool:
        """检查终端是否存在"""
        return term_id in self._terminals
    
    @property
    def active_id(self) -> Optional[str]:
        """当前激活的终端 ID"""
        return self._active_id
    
    # ============================================================
    # 终端配置
    # ============================================================
    def rename_terminal(self, term_id: str, new_name: str) -> bool:
        """重命名终端"""
        if term_id not in self._terminals:
            return False
        
        self._terminals[term_id].name = new_name
        self.terminal_renamed.emit(term_id, new_name)
        return True
    
    def set_terminal_cwd(self, term_id: str, cwd: str) -> bool:
        """设置终端工作目录"""
        if term_id not in self._terminals:
            return False
        
        self._terminals[term_id].cwd = cwd
        
        # 如果面板已创建，更新面板的 cwd
        instance = self._terminals[term_id]
        if instance.panel and hasattr(instance.panel, 'set_cwd'):
            instance.panel.set_cwd(cwd)
        
        return True
    
    def bind_panel(self, term_id: str, panel: QWidget) -> bool:
        """绑定终端面板"""
        if term_id not in self._terminals:
            return False
        
        self._terminals[term_id].panel = panel
        return True
    
    # ============================================================
    # 持久化（可选）
    # ============================================================
    def save_config(self) -> dict:
        """保存配置到字典"""
        return {
            "terminals": [
                {
                    "id": t.id,
                    "name": t.name,
                    "cwd": t.cwd,
                    "shell": t.shell,
                }
                for t in self._terminals.values()
            ],
            "active_id": self._active_id,
        }
    
    def load_config(self, config: dict):
        """从字典加载配置"""
        self.close_all()
        
        for term_config in config.get("terminals", []):
            term_id = term_config.get("id")
            if not term_id:
                continue
            
            instance = TerminalInstance(
                term_id=term_id,
                name=term_config.get("name", "终端"),
                cwd=term_config.get("cwd", os.getcwd()),
                shell=term_config.get("shell"),
            )
            self._terminals[term_id] = instance
        
        # 恢复激活状态
        active_id = config.get("active_id")
        if active_id and active_id in self._terminals:
            self.switch_terminal(active_id)
