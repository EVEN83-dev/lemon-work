# -*- coding: utf-8 -*-
"""
Lemon Logger — 日志系统加固
============================
提供分级日志、日志轮转、结构化日志、敏感信息脱敏功能。

功能：
1. 分级日志（DEBUG/INFO/WARNING/ERROR/CRITICAL）
2. 日志轮转（按大小 + 按时间）
3. 结构化日志输出
4. 敏感信息自动脱敏
5. 多目标输出（文件 + 控制台）
6. 上下文信息附加

使用方式：
    logger = LemonLogger("main")
    logger.info("程序启动", engine="ollama", model="qwen2.5")
    logger.error("连接失败", port=4097)
    logger.debug("调试信息", context={"session_id": "xxx"})
"""

import os
import re
import json
import logging
import threading
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Dict, Any, Optional
from datetime import datetime


class SensitiveFormatter(logging.Formatter):
    """敏感信息脱敏格式化器"""

    # 敏感信息模式
    SENSITIVE_PATTERNS = [
        (r'(password\s*[:=]\s*)(\S+)', r'\1***'),
        (r'(passwd\s*[:=]\s*)(\S+)', r'\1***'),
        (r'(secret\s*[:=]\s*)(\S+)', r'\1***'),
        (r'(token\s*[:=]\s*)(\S+)', r'\1***'),
        (r'(api[_-]?key\s*[:=]\s*)(\S+)', r'\1***'),
        (r'(access[_-]?key\s*[:=]\s*)(\S+)', r'\1***'),
        (r'(private[_-]?key\s*[:=]\s*)(\S+)', r'\1***'),
        (r'(Authorization:\s*)(\S+)', r'\1***'),
        (r'(Bearer\s+)(\S+)', r'\1***'),
    ]

    def format(self, record):
        """格式化日志记录，并对敏感信息脱敏"""
        formatted = super().format(record)
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            formatted = re.sub(pattern, replacement, formatted, flags=re.IGNORECASE)
        return formatted


class StructuredFormatter(logging.Formatter):
    """结构化日志格式化器（JSON 格式）"""

    def format(self, record):
        """格式化为 JSON 结构"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加上下文信息
        if hasattr(record, "context") and record.context:
            log_entry["context"] = record.context

        # 添加异常信息
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        return json.dumps(log_entry, ensure_ascii=False)


class LemonLogger:
    """Lemon Code 日志管理器

    提供统一的分级日志接口，支持多目标输出和敏感信息脱敏。
    """

    # 日志级别映射
    LEVELS = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    def __init__(self, name: str = "lemon_agent",
                 log_dir: str = None,
                 level: str = "INFO",
                 max_bytes: int = 10 * 1024 * 1024,  # 10MB
                 backup_count: int = 5,
                 enable_console: bool = True,
                 enable_file: bool = True,
                 structured: bool = False):
        """
        Args:
            name: 日志记录器名称
            log_dir: 日志目录，默认 ~/.lemon_agent/logs
            level: 日志级别
            max_bytes: 单个日志文件最大大小
            backup_count: 保留的备份文件数量
            enable_console: 是否输出到控制台
            enable_file: 是否输出到文件
            structured: 是否使用结构化 JSON 格式
        """
        if log_dir is None:
            log_dir = os.path.join(os.path.expanduser("~"), ".lemon_agent", "logs")
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

        self.name = name
        self._lock = threading.Lock()

        # 创建 logger
        self._logger = logging.getLogger(name)
        self._logger.setLevel(self.LEVELS.get(level.upper(), logging.INFO))
        self._logger.handlers.clear()

        # 格式化器
        if structured:
            self._formatter = StructuredFormatter()
        else:
            self._formatter = SensitiveFormatter(
                '%(asctime)s [%(levelname)s] %(name)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )

        # 文件处理器
        if enable_file:
            file_handler = RotatingFileHandler(
                os.path.join(self.log_dir, f"{name}.log"),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(self._formatter)
            self._logger.addHandler(file_handler)

        # 控制台处理器
        if enable_console:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.LEVELS.get(level.upper(), logging.INFO))
            # 控制台使用简化格式
            console_formatter = SensitiveFormatter(
                '%(asctime)s [%(levelname)s] %(message)s',
                datefmt='%H:%M:%S'
            )
            console_handler.setFormatter(console_formatter)
            self._logger.addHandler(console_handler)

    # ============================================================
    # 日志方法
    # ============================================================

    def debug(self, message: str, *args, **kwargs):
        """DEBUG 级别日志"""
        self._log(logging.DEBUG, self._apply_args(message, args), **kwargs)

    def info(self, message: str, *args, **kwargs):
        """INFO 级别日志"""
        self._log(logging.INFO, self._apply_args(message, args), **kwargs)

    def warning(self, message: str, *args, **kwargs):
        """WARNING 级别日志"""
        self._log(logging.WARNING, self._apply_args(message, args), **kwargs)

    def error(self, message: str, *args, **kwargs):
        """ERROR 级别日志"""
        self._log(logging.ERROR, self._apply_args(message, args), **kwargs)

    def critical(self, message: str, *args, **kwargs):
        """CRITICAL 级别日志"""
        self._log(logging.CRITICAL, self._apply_args(message, args), **kwargs)

    def exception(self, message: str, exc: Exception = None, **kwargs):
        """记录异常日志（包含堆栈）"""
        self._log(logging.ERROR, message, exc_info=True, **kwargs)

    @staticmethod
    def _apply_args(message: str, args: tuple) -> str:
        """★ v5.8: 兼容 stdlib 风格调用 logger.info("... %s", a, b)。

        项目源码混用两种风格（LemonLogger kwargs 风格 / stdlib % 风格），
        旧签名不接受位置参数会直接 TypeError 崩掉调用方。
        格式化失败时降级为拼接，保证日志调用本身永不抛异常。
        """
        if not args:
            return message
        try:
            return message % args
        except (TypeError, ValueError, KeyError):
            return f"{message} | args={args}"

    def _log(self, level: int, message: str, **kwargs):
        """内部日志记录

        Args:
            level: 日志级别
            message: 日志消息
            **kwargs: 附加上下文（通过 extra 传递）
        """
        with self._lock:
            # 构建上下文信息
            context = {k: v for k, v in kwargs.items() if k != "exc_info"}
            if context:
                context_str = " ".join(f"{k}={v}" for k, v in context.items())
                message = f"{message} | {context_str}"

            exc_info = kwargs.get("exc_info", False)
            self._logger.log(level, message, exc_info=exc_info)

    # ============================================================
    # 脱敏
    # ============================================================

    @staticmethod
    def sanitize(text: str) -> str:
        """脱敏处理文本

        Args:
            text: 原始文本

        Returns:
            脱敏后的文本
        """
        for pattern, replacement in SensitiveFormatter.SENSITIVE_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    # ============================================================
    # 配置
    # ============================================================

    def set_level(self, level: str):
        """设置日志级别

        Args:
            level: 日志级别名称
        """
        self._logger.setLevel(self.LEVELS.get(level.upper(), logging.INFO))

    def get_level(self) -> str:
        """获取当前日志级别"""
        level = self._logger.getEffectiveLevel()
        for name, value in self.LEVELS.items():
            if value == level:
                return name
        return "INFO"

    # ============================================================
    # 日志文件管理
    # ============================================================

    def get_log_files(self) -> list:
        """获取日志文件列表"""
        files = []
        try:
            for filename in os.listdir(self.log_dir):
                if filename.startswith(self.name) and filename.endswith(".log"):
                    filepath = os.path.join(self.log_dir, filename)
                    files.append({
                        "name": filename,
                        "path": filepath,
                        "size": os.path.getsize(filepath),
                        "modified": datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
                    })
        except Exception:
            pass
        return sorted(files, key=lambda x: x["name"])

    def clear_logs(self):
        """清除所有日志文件"""
        # ★ v3.60: 先关闭所有文件处理器，再删除文件（Windows 不允许删除打开的文件）
        for handler in list(self._logger.handlers):
            if isinstance(handler, RotatingFileHandler):
                handler.close()
                self._logger.removeHandler(handler)
        try:
            for filename in os.listdir(self.log_dir):
                if filename.startswith(self.name) and filename.endswith(".log"):
                    os.remove(os.path.join(self.log_dir, filename))
        except Exception:
            pass


# ============================================================
# 全局日志实例
# ============================================================

_loggers: Dict[str, LemonLogger] = {}
_logger_lock = threading.Lock()


def get_logger(name: str = "lemon_agent", **kwargs) -> LemonLogger:
    """获取或创建日志记录器

    Args:
        name: 日志记录器名称
        **kwargs: 传递给 LemonLogger 的参数

    Returns:
        LemonLogger 实例
    """
    with _logger_lock:
        if name not in _loggers:
            _loggers[name] = LemonLogger(name=name, **kwargs)
        return _loggers[name]