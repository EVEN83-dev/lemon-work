# -*- coding: utf-8 -*-
"""
MIMO CLI 子进程桥接（稳定性回退方案）
========================================
功能：
- 通过 stdin/stdout 与 mimo CLI 通信
- 不依赖 HTTP API，更稳定
- 作为 Serve Bridge 的备用方案

技术原理：
┌─────────────────────────────────────┐
│  MiMoCode Agent (Python)            │
│    ↓ stdin (JSON)                   │
│  mimo CLI 进程                      │
│    ↑ stdout (JSON)                  │
│  MIMO Code 核心                     │
└─────────────────────────────────────┘

使用场景：
- HTTP API 不可用时自动切换
- 离线环境
- 需要更低延迟时
"""

import os
import json
import threading
import time
import subprocess
from typing import Optional, Dict, Any
from queue import Queue, Empty

from PyQt5.QtCore import QObject, pyqtSignal, QTimer


class MIMOCLIBridge(QObject):
    """
    MIMO CLI 子进程桥接
    
    功能：
    - 通过 stdin/stdout 与 mimo CLI 通信
    - 不依赖 HTTP API
    - 更稳定但功能较少
    """
    
    # 信号
    output_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    status_received = pyqtSignal(str)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        
        # 进程
        self._process: Optional[subprocess.Popen] = None
        self._running = False
        
        # 输出队列
        self._output_queue = Queue()
        
        # MIMO CLI 路径
        self._mimo_cli_path = self._find_mimo_cli()
    
    def _find_mimo_cli(self) -> Optional[str]:
        """查找 mimo CLI 路径"""
        # 尝试在系统 PATH 中查找
        try:
            result = subprocess.run(
                ["where", "mimo"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except Exception:
            pass
        
        # 尝试在项目目录查找
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        possible_paths = [
            os.path.join(project_dir, "bin", "mimo.exe"),
            os.path.join(project_dir, "mimo.exe"),
            os.path.join(os.path.dirname(project_dir), "小米AI", "node_global", "node_modules", "@mimo-ai", "mimocode-windows-x64", "bin", "mimo.exe"),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    def start(self) -> bool:
        """启动 mimo CLI 进程"""
        if not self._mimo_cli_path:
            self.error_occurred.emit("未找到 mimo CLI")
            return False
        
        try:
            # 启动子进程（stdin/stdout 管道）
            self._process = subprocess.Popen(
                [self._mimo_cli_path, "chat", "--json"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # 行缓冲
            )
            
            self._running = True
            
            # 启动输出监听线程
            self._output_thread = threading.Thread(target=self._read_output, daemon=True)
            self._output_thread.start()
            
            # 启动错误监听线程
            self._error_thread = threading.Thread(target=self._read_error, daemon=True)
            self._error_thread.start()
            
            self.connected.emit()
            self.status_received.emit("MIMO CLI 已连接")
            
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"启动 MIMO CLI 失败: {e}")
            return False
    
    def stop(self):
        """停止进程"""
        self._running = False
        
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            
            self._process = None
        
        self.disconnected.emit()
    
    def _read_output(self):
        """读取 stdout 输出"""
        while self._running and self._process:
            try:
                line = self._process.stdout.readline()
                
                if not line:
                    time.sleep(0.1)
                    continue
                
                line = line.strip()
                
                if line:
                    # 解析 JSON 输出
                    try:
                        data = json.loads(line)
                        self._handle_output(data)
                    except json.JSONDecodeError:
                        # 非 JSON 输出，直接发射
                        self.output_received.emit(line)
                        
            except Exception as e:
                if self._running:
                    self.error_occurred.emit(f"读取输出失败: {e}")
                    time.sleep(1)
    
    def _read_error(self):
        """读取 stderr 输出"""
        while self._running and self._process:
            try:
                line = self._process.stderr.readline()
                
                if not line:
                    time.sleep(0.1)
                    continue
                
                line = line.strip()
                
                if line:
                    self.error_occurred.emit(f"[MIMO CLI] {line}")
                    
            except Exception:
                time.sleep(1)
    
    def _handle_output(self, data: Dict):
        """处理输出数据"""
        output_type = data.get("type", "")
        
        if output_type == "text":
            text = data.get("text", "")
            if text:
                self.output_received.emit(text)
        
        elif output_type == "error":
            error = data.get("message", "Unknown error")
            self.error_occurred.emit(error)
        
        elif output_type == "status":
            status = data.get("message", "")
            if status:
                self.status_received.emit(status)
    
    def send_message(self, text: str) -> bool:
        """
        发送消息到 MIMO CLI
        
        Args:
            text: 消息内容
        
        Returns:
            是否发送成功
        """
        if not self._running or not self._process:
            return False
        
        try:
            # 构造 JSON 消息
            message = json.dumps({
                "type": "message",
                "text": text
            })
            
            # 写入 stdin
            self._process.stdin.write(message + "\n")
            self._process.stdin.flush()
            
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"发送失败: {e}")
            return False
    
    def send_command(self, command: str, args: Dict = None) -> bool:
        """
        发送命令
        
        Args:
            command: 命令名称
            args: 命令参数
        
        Returns:
            是否发送成功
        """
        if not self._running or not self._process:
            return False
        
        try:
            # 构造 JSON 命令
            cmd = {
                "type": "command",
                "command": command,
            }
            
            if args:
                cmd["args"] = args
            
            message = json.dumps(cmd)
            
            # 写入 stdin
            self._process.stdin.write(message + "\n")
            self._process.stdin.flush()
            
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"发送命令失败: {e}")
            return False
    
    def switch_model(self, model_id: str) -> bool:
        """切换模型"""
        return self.send_command("switch_model", {"model": model_id})
    
    def create_session(self) -> bool:
        """创建新会话"""
        return self.send_command("create_session")
    
    def switch_session(self, session_id: str) -> bool:
        """切换会话"""
        return self.send_command("switch_session", {"session_id": session_id})