# -*- coding: utf-8 -*-
"""
Input Validator — 输入验证加固
===============================
提供输入验证、清理、长度限制、敏感词过滤、SQL注入防护等功能。

功能：
1. 输入长度限制
2. 输入格式验证（类型检查、空值检查）
3. 敏感词过滤
4. XSS 防护
5. SQL 注入防护
6. 路径遍历防护
7. 输入清理（sanitize）

使用方式：
    validator = InputValidator(max_length=10000)
    validator.validate("用户输入")
    cleaned = validator.sanitize("用户输入 <script>alert(1)</script>")
"""

import re
import os
from typing import Optional, List, Tuple


class InputValidator:
    """输入验证器

    提供多层输入验证和安全防护，确保系统安全。
    """

    # 默认敏感词列表
    DEFAULT_SENSITIVE_PATTERNS = [
        r"(?i)password\s*[:=]\s*\S+",
        r"(?i)secret\s*[:=]\s*\S+",
        r"(?i)token\s*[:=]\s*\S+",
        r"(?i)api[_-]?key\s*[:=]\s*\S+",
        r"(?i)access[_-]?key\s*[:=]\s*\S+",
        r"(?i)private[_-]?key\s*[:=]\s*\S+",
    ]

    # SQL 注入模式
    SQL_INJECTION_PATTERNS = [
        r"(?i)(\bSELECT\b.*\bFROM\b)",
        r"(?i)(\bINSERT\b.*\bINTO\b)",
        r"(?i)(\bUPDATE\b.*\bSET\b)",
        r"(?i)(\bDELETE\b.*\bFROM\b)",
        r"(?i)(\bDROP\b.*\bTABLE\b)",
        r"(?i)(\bUNION\b.*\bSELECT\b)",
        r"(?i)(\bEXEC\b.*\bxp_cmdshell\b)",
        r"(?i)(--\s*$)",
        r"(?i)(;\s*$)",
        r"(?i)(/\*.*\*/)",
    ]

    # XSS 模式
    XSS_PATTERNS = [
        r"<script[^>]*>.*?</script>",
        r"javascript\s*:",
        r"on\w+\s*=",
        r"<iframe[^>]*>",
        r"<embed[^>]*>",
        r"<object[^>]*>",
        r"expression\s*\(",
        r"eval\s*\(",
    ]

    # 路径遍历模式
    PATH_TRAVERSAL_PATTERNS = [
        r"\.\./",
        r"\.\.\\",
        r"%2e%2e/",
        r"%2e%2e%5c",
    ]

    def __init__(self, max_length: int = 10000, min_length: int = 0):
        """
        Args:
            max_length: 最大输入长度（字符数）
            min_length: 最小输入长度（字符数）
        """
        self.max_length = max_length
        self.min_length = min_length
        self._custom_sensitive_patterns: List[str] = []

    # ============================================================
    # 核心验证
    # ============================================================

    def validate(self, text: str, check_sensitive: bool = True,
                 check_sql: bool = True, check_xss: bool = True,
                 check_path: bool = False) -> Tuple[bool, Optional[str]]:
        """完整验证输入

        Args:
            text: 输入文本
            check_sensitive: 是否检查敏感词
            check_sql: 是否检查 SQL 注入
            check_xss: 是否检查 XSS
            check_path: 是否检查路径遍历

        Returns:
            (是否通过, 错误消息)
        """
        # 类型检查
        if not isinstance(text, str):
            return False, "输入必须是字符串类型"

        # 长度检查
        if len(text) > self.max_length:
            return False, f"输入长度 {len(text)} 超过最大限制 {self.max_length}"

        if len(text) < self.min_length:
            return False, f"输入长度 {len(text)} 低于最小要求 {self.min_length}"

        # 空值检查（允许空白字符，但拒绝纯空白）
        if not text.strip() and self.min_length > 0:
            return False, "输入不能为空"

        # 敏感词检查
        if check_sensitive:
            ok, err = self._check_sensitive(text)
            if not ok:
                return False, err

        # SQL 注入检查
        if check_sql:
            ok, err = self._check_sql_injection(text)
            if not ok:
                return False, err

        # XSS 检查
        if check_xss:
            ok, err = self._check_xss(text)
            if not ok:
                return False, err

        # 路径遍历检查
        if check_path:
            ok, err = self._check_path_traversal(text)
            if not ok:
                return False, err

        return True, None

    def validate_quick(self, text: str) -> bool:
        """快速验证（仅长度和类型检查）"""
        if not isinstance(text, str):
            return False
        if len(text) > self.max_length:
            return False
        return True

    # ============================================================
    # 输入清理
    # ============================================================

    def sanitize(self, text: str, strip_html: bool = True,
                 strip_xss: bool = True) -> str:
        """清理输入，移除危险内容

        Args:
            text: 输入文本
            strip_html: 是否移除 HTML 标签
            strip_xss: 是否移除 XSS 代码

        Returns:
            清理后的文本
        """
        if not isinstance(text, str):
            return ""

        # 移除 XSS 代码
        if strip_xss:
            for pattern in self.XSS_PATTERNS:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        # 移除 HTML 标签
        if strip_html:
            text = re.sub(r"<[^>]+>", "", text)

        # 移除危险协议
        text = text.replace("javascript:", "")
        text = text.replace("data:text/html", "")

        # 脱敏敏感信息
        all_patterns = self.DEFAULT_SENSITIVE_PATTERNS + self._custom_sensitive_patterns
        for pattern in all_patterns:
            text = re.sub(pattern, "***MASKED***", text)

        return text.strip()

    def sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除危险字符

        Args:
            filename: 原始文件名

        Returns:
            安全的文件名
        """
        # 移除路径分隔符
        filename = filename.replace("/", "_").replace("\\", "_")
        # 移除非法字符
        filename = re.sub(r'[<>:"|?*]', "_", filename)
        # 移除路径遍历
        filename = filename.replace("..", "_")
        # 限制长度
        if len(filename) > 255:
            name, ext = os.path.splitext(filename)
            filename = name[:255 - len(ext)] + ext
        return filename.strip()

    # ============================================================
    # 内部检查方法
    # ============================================================

    def _check_sensitive(self, text: str) -> Tuple[bool, Optional[str]]:
        """检查敏感信息"""
        all_patterns = self.DEFAULT_SENSITIVE_PATTERNS + self._custom_sensitive_patterns
        for pattern in all_patterns:
            if re.search(pattern, text):
                return False, "输入包含敏感信息（密码/密钥等），已被拒绝"
        return True, None

    def _check_sql_injection(self, text: str) -> Tuple[bool, Optional[str]]:
        """检查 SQL 注入"""
        for pattern in self.SQL_INJECTION_PATTERNS:
            if re.search(pattern, text):
                return False, "检测到潜在的 SQL 注入攻击"
        return True, None

    def _check_xss(self, text: str) -> Tuple[bool, Optional[str]]:
        """检查 XSS 攻击"""
        for pattern in self.XSS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return False, "检测到潜在的 XSS 攻击"
        return True, None

    def _check_path_traversal(self, text: str) -> Tuple[bool, Optional[str]]:
        """检查路径遍历"""
        for pattern in self.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return False, "检测到潜在的路径遍历攻击"
        return True, None

    # ============================================================
    # 配置
    # ============================================================

    def add_sensitive_pattern(self, pattern: str):
        """添加自定义敏感模式"""
        self._custom_sensitive_patterns.append(pattern)

    def set_max_length(self, max_length: int):
        """设置最大长度"""
        self.max_length = max_length

    def set_min_length(self, min_length: int):
        """设置最小长度"""
        self.min_length = min_length


# ============================================================
# 全局默认实例
# ============================================================

_default_validator = InputValidator()


def validate_input(text: str, max_length: int = 10000) -> Tuple[bool, Optional[str]]:
    """便捷验证函数"""
    validator = InputValidator(max_length=max_length)
    return validator.validate(text)


def sanitize_input(text: str) -> str:
    """便捷清理函数"""
    return _default_validator.sanitize(text)


def sanitize_filename_input(filename: str) -> str:
    """便捷文件名清理"""
    return _default_validator.sanitize_filename(filename)