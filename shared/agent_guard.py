# -*- coding: utf-8 -*-
"""
Lemon Agent 安全守卫模块
=========================
实现 Agent 安全规则：
1. 权限分级（允许/需审核/禁止）
2. 循环检测（防止死循环）
3. 超时控制（防止单轮卡死）
4. 审核回调（人工确认危险操作）
5. 验证脚本（验证任务结果）
6. 状态追踪（记录 Agent 运行状态）

规范文档：agent_safety_rules.md
"""

import os
import re
import time
import json
import threading
import subprocess
from enum import Enum
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field


# ============================================================================
# 权限级别
# ============================================================================

class PermissionLevel(Enum):
    """工具权限级别"""
    ALLOWED = "allowed"          # 允许，无需审核
    NEEDS_REVIEW = "review"      # 需要人工审核
    DENIED = "denied"            # 禁止执行


# ============================================================================
# Agent 状态
# ============================================================================

@dataclass
class AgentState:
    """Agent 运行状态追踪"""
    iterations: int = 0
    max_iterations: int = 8
    started_at: float = field(default_factory=time.time)
    tools_called: int = 0
    tool_history: List[Dict] = field(default_factory=list)
    consecutive_errors: int = 0
    consecutive_empty: int = 0
    total_output_size: int = 0
    is_active: bool = False

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    def reset(self, max_iterations: int = 8):
        self.iterations = 0
        self.max_iterations = max_iterations
        self.started_at = time.time()
        self.tools_called = 0
        self.tool_history.clear()
        self.consecutive_errors = 0
        self.consecutive_empty = 0
        self.total_output_size = 0
        self.is_active = True

    def to_dict(self) -> Dict:
        return {
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "elapsed": round(self.elapsed, 2),
            "tools_called": self.tools_called,
            "consecutive_errors": self.consecutive_errors,
            "consecutive_empty": self.consecutive_empty,
            "total_output_size": self.total_output_size,
            "is_active": self.is_active,
        }


# ============================================================================
# 安全守卫
# ============================================================================

class AgentGuard:
    """Agent 安全守卫 — 权限检查、循环检测、超时控制"""

    # 危险文件路径正则
    DANGEROUS_PATHS = [
        r'^[/\\]etc[/\\]',
        r'^[/\\]windows[/\\]',
        r'^[/\\]System32[/\\]',
        r'^[/\\]Program Files[/\\]',
        r'^C:[/\\]Windows',           # 匹配 C:\Windows 和 C:/Windows
        r'^C:[/\\]System32',
        r'^/usr/sbin',
        r'^/bin/',
        r'^/sbin/',
        r'^/root/',
        r'^[/\\]boot[/\\]',
        r'^[/\\]dev[/\\]',
    ]

    # 危险命令正则
    DANGEROUS_COMMANDS = [
        r'\bsudo\b',
        r'\bchmod\s+777\b',
        r'\bformat\b',
        r'\brm\s+-rf\s+/',
        r'\bdd\s+if=',
        r'\bmkfs\b',
        r'\bshutdown\b',
        r'\breboot\b',
        r'\:()\{\s*:\|:&\s*\};:',  # fork bomb
    ]

    # 只读命令白名单
    SAFE_COMMANDS = [
        r'^ls(\s|$)',
        r'^cat(\s|$)',
        r'^git\s+(status|log|diff|branch|show)',
        r'^pwd$',
        r'^echo\s',
        r'^head(\s|$)',
        r'^tail(\s|$)',
        r'^wc(\s|$)',
        r'^grep(\s|$)',
        r'^find\s.*-name',
        r'^python\s+-c\s+print',
    ]

    # 需审核命令
    REVIEW_COMMANDS = [
        r'^pip\s+install',
        r'^npm\s+install',
        r'^git\s+(push|commit|merge|rebase)',
        r'^curl\s',
        r'^wget\s',
        r'^mv\s',
        r'^cp\s.*\s+/',
        r'^rm\s',
    ]

    def __init__(self, project_root: str = "."):
        self.project_root = os.path.abspath(project_root)
        self.state = AgentState()
        self._review_callback: Optional[Callable[[str, Dict], bool]] = None
        self._notification_callback: Optional[Callable[[str, str], None]] = None
        self._lock = threading.Lock()
        # 会话内记住的权限决策
        self._session_decisions: Dict[str, PermissionLevel] = {}

    # ==================== 权限检查 ====================

    def check_permission(self, tool_name: str, args: Dict) -> PermissionLevel:
        """检查工具调用权限"""
        # 1. 检查会话决策缓存
        decision_key = self._make_decision_key(tool_name, args)
        if decision_key in self._session_decisions:
            return self._session_decisions[decision_key]

        # 2. 根据工具类型检查
        perm = self._evaluate_permission(tool_name, args)
        return perm

    def _evaluate_permission(self, tool_name: str, args: Dict) -> PermissionLevel:
        """评估工具权限"""
        if tool_name == "read_file":
            return self._check_read_permission(args.get("file_path", ""))
        elif tool_name == "write_file":
            return self._check_write_permission(args.get("file_path", ""))
        elif tool_name == "list_directory":
            return PermissionLevel.ALLOWED
        elif tool_name == "search_files":
            return PermissionLevel.ALLOWED
        elif tool_name == "grep_search":
            return PermissionLevel.ALLOWED
        elif tool_name == "scan_project":
            return PermissionLevel.ALLOWED
        elif tool_name == "execute_code":
            return self._check_code_permission(args.get("code", ""))
        elif tool_name == "run_command":
            return self._check_command_permission(args.get("command", ""))
        elif tool_name == "web_fetch":
            return PermissionLevel.NEEDS_REVIEW
        elif tool_name == "query_knowledge_base":
            return PermissionLevel.ALLOWED
        else:
            return PermissionLevel.NEEDS_REVIEW  # 未知工具默认需审核

    def _check_read_permission(self, file_path: str) -> PermissionLevel:
        """检查文件读取权限"""
        if not file_path:
            return PermissionLevel.DENIED
        # 检查危险路径
        for pattern in self.DANGEROUS_PATHS:
            if re.match(pattern, file_path, re.IGNORECASE):
                return PermissionLevel.DENIED
        # 项目内文件允许
        abs_path = os.path.abspath(file_path)
        if abs_path.startswith(self.project_root):
            return PermissionLevel.ALLOWED
        # 项目外文件需审核
        return PermissionLevel.NEEDS_REVIEW

    def _check_write_permission(self, file_path: str) -> PermissionLevel:
        """检查文件写入权限"""
        if not file_path:
            return PermissionLevel.DENIED
        # 危险路径禁止
        for pattern in self.DANGEROUS_PATHS:
            if re.match(pattern, file_path, re.IGNORECASE):
                return PermissionLevel.DENIED
        abs_path = os.path.abspath(file_path)
        if abs_path.startswith(self.project_root):
            return PermissionLevel.ALLOWED
        # 项目外需审核
        return PermissionLevel.NEEDS_REVIEW

    def _check_code_permission(self, code: str) -> PermissionLevel:
        """检查代码执行权限"""
        if not code:
            return PermissionLevel.DENIED
        # 检查危险代码
        dangerous_patterns = [
            r'import\s+os',
            r'import\s+subprocess',
            r'os\.system',
            r'os\.remove',
            r'os\.rmdir',
            r'subprocess\.',
            r'__import__',
            r'eval\s*\(',
            r'exec\s*\(',
        ]
        for pattern in dangerous_patterns:
            if re.search(pattern, code):
                return PermissionLevel.NEEDS_REVIEW
        return PermissionLevel.ALLOWED

    def _check_command_permission(self, command: str) -> PermissionLevel:
        """检查命令执行权限"""
        if not command:
            return PermissionLevel.DENIED
        # 危险命令禁止
        for pattern in self.DANGEROUS_COMMANDS:
            if re.search(pattern, command, re.IGNORECASE):
                return PermissionLevel.DENIED
        # 只读命令允许
        for pattern in self.SAFE_COMMANDS:
            if re.match(pattern, command):
                return PermissionLevel.ALLOWED
        # 需审核命令
        for pattern in self.REVIEW_COMMANDS:
            if re.match(pattern, command):
                return PermissionLevel.NEEDS_REVIEW
        # 其他命令默认需审核
        return PermissionLevel.NEEDS_REVIEW

    def _make_decision_key(self, tool_name: str, args: Dict) -> str:
        """生成决策缓存键（基于工具名+关键参数）"""
        if tool_name == "run_command":
            # 命令按前缀缓存（前 2 个词）
            parts = args.get("command", "").split()[:2]
            return f"{tool_name}:{' '.join(parts)}"
        elif tool_name in ("read_file", "write_file"):
            abs_path = os.path.abspath(args.get("file_path", ""))
            in_project = abs_path.startswith(self.project_root)
            return f"{tool_name}:in_project={in_project}"
        return tool_name

    # ==================== 循环检测 ====================

    def check_loop(self, tool_name: str, args: Dict) -> Tuple[bool, str]:
        """检测死循环 — 同一工具+相同参数连续调用"""
        with self._lock:
            # 检查最近 3 次调用
            recent = self.state.tool_history[-3:]
            same_count = 0
            for h in recent:
                if h["tool"] == tool_name and h["args"] == args:
                    same_count += 1
            if same_count >= 2:
                return True, f"死循环检测: {tool_name} 连续调用 {same_count + 1} 次相同参数"
            return False, ""

    # ==================== 超时控制 ====================

    def check_timeout(self, per_iteration_timeout: float = 90.0) -> Tuple[bool, str]:
        """检查是否超时"""
        if not self.state.is_active:
            return False, ""
        # 检查总时间
        if self.state.elapsed > 1800:  # 30 分钟
            return True, f"总运算超时: {self.state.elapsed:.0f}s > 1800s"
        return False, ""

    # ==================== 中断判断 ====================

    def should_break(self) -> Tuple[bool, str]:
        """检查是否应该中断 Agent 循环"""
        # 1. 迭代次数超限
        if self.state.iterations >= self.state.max_iterations:
            return True, f"超过最大迭代次数: {self.state.max_iterations}"
        # 2. 连续错误
        if self.state.consecutive_errors >= 3:
            return True, f"连续错误 {self.state.consecutive_errors} 次"
        # 3. 连续空响应
        if self.state.consecutive_empty >= 2:
            return True, f"连续空响应 {self.state.consecutive_empty} 次"
        # 4. 总工具调用次数
        if self.state.tools_called >= 50:
            return True, f"总工具调用次数超限: {self.state.tools_called}"
        # 5. 输出累积过大
        if self.state.total_output_size > 50000:  # 50KB
            return True, f"工具输出累积过大: {self.state.total_output_size} 字符"
        # 6. 总时间
        if self.state.elapsed > 1800:
            return True, f"总运算超时: {self.state.elapsed:.0f}s"
        return False, ""

    # ==================== 工具调用记录 ====================

    def record_tool_call(self, tool_name: str, args: Dict, result: str, success: bool):
        """记录工具调用"""
        with self._lock:
            self.state.tools_called += 1
            self.state.tool_history.append({
                "tool": tool_name,
                "args": args,
                "success": success,
                "output_size": len(result),
                "timestamp": time.time(),
            })
            self.state.total_output_size += len(result)
            if not success:
                self.state.consecutive_errors += 1
            else:
                self.state.consecutive_errors = 0

    def record_empty_response(self):
        """记录空响应"""
        with self._lock:
            self.state.consecutive_empty += 1

    def record_iteration(self):
        """记录一次迭代"""
        with self._lock:
            self.state.iterations += 1

    # ==================== 审核回调 ====================

    def set_review_callback(self, callback: Callable[[str, Dict], bool]):
        """设置人工审核回调函数

        回调函数签名: callback(tool_name: str, args: Dict) -> bool
        返回 True 表示允许执行，False 表示拒绝
        """
        self._review_callback = callback

    def set_notification_callback(self, callback: Callable[[str, str], None]):
        """设置通知回调函数

        回调函数签名: callback(level: str, message: str)
        level: "info" | "warn" | "error"
        """
        self._notification_callback = callback

    def request_review(self, tool_name: str, args: Dict) -> bool:
        """请求人工审核"""
        if self._review_callback:
            return self._review_callback(tool_name, args)
        # 无回调时默认拒绝
        self.notify("warn", f"需审核但无回调: {tool_name}({args})，默认拒绝")
        return False

    def notify(self, level: str, message: str):
        """发送通知"""
        if self._notification_callback:
            self._notification_callback(level, message)
        else:
            print(f"[AgentGuard:{level}] {message}")

    # ==================== 会话决策 ====================

    def remember_decision(self, tool_name: str, args: Dict, level: PermissionLevel):
        """记住会话内决策"""
        key = self._make_decision_key(tool_name, args)
        self._session_decisions[key] = level

    def clear_decisions(self):
        """清除会话决策"""
        self._session_decisions.clear()

    # ==================== 状态查询 ====================

    def get_state(self) -> Dict:
        """获取当前 Agent 状态"""
        return self.state.to_dict()

    def list_safety_rules(self) -> List[Dict]:
        """列出所有安全规则"""
        return [
            {"category": "文件读取", "rule": "项目内允许，项目外需审核，系统文件禁止"},
            {"category": "文件写入", "rule": "项目内允许，项目外需审核，系统文件禁止"},
            {"category": "命令执行", "rule": "只读命令允许，写命令需审核，危险命令禁止"},
            {"category": "代码执行", "rule": "纯计算允许，import os/subprocess 需审核"},
            {"category": "网络访问", "rule": "web_fetch 需审核"},
            {"category": "迭代上限", "rule": f"默认 {self.state.max_iterations} 轮"},
            {"category": "超时", "rule": "单轮 90s，总运算 30 分钟"},
            {"category": "循环检测", "rule": "同一工具+相同参数连续 2 次触发警告"},
            {"category": "错误恢复", "rule": "连续 3 次错误中断"},
        ]


# ============================================================================
# 工具验证器
# ============================================================================

class ToolValidator:
    """任务结果验证器 — 验证 Agent 任务是否真正完成"""

    @staticmethod
    def validate_file_exists(file_path: str) -> Tuple[bool, str]:
        """验证文件是否存在"""
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            return True, f"文件存在: {file_path} ({size} bytes)"
        return False, f"文件不存在: {file_path}"

    @staticmethod
    def validate_file_content(file_path: str, expected_content: str = None,
                              contains: str = None) -> Tuple[bool, str]:
        """验证文件内容"""
        if not os.path.exists(file_path):
            return False, f"文件不存在: {file_path}"
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            if expected_content and content != expected_content:
                return False, f"内容不匹配: 期望 {expected_content[:50]}..., 实际 {content[:50]}..."
            if contains and contains not in content:
                return False, f"未找到内容: {contains}"
            return True, f"内容验证通过: {file_path}"
        except Exception as e:
            return False, f"读取失败: {e}"

    @staticmethod
    def validate_code_syntax(file_path: str) -> Tuple[bool, str]:
        """验证 Python 代码语法"""
        if not os.path.exists(file_path):
            return False, f"文件不存在: {file_path}"
        try:
            import py_compile
            py_compile.compile(file_path, doraise=True)
            return True, f"语法正确: {file_path}"
        except py_compile.PyCompileError as e:
            return False, f"语法错误: {e}"
        except Exception as e:
            return False, f"验证失败: {e}"

    @staticmethod
    def validate_command_result(command: str, expected_output: str = None,
                                expected_contains: str = None) -> Tuple[bool, str]:
        """验证命令执行结果"""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return False, f"命令失败: {result.stderr[:100]}"
            output = result.stdout
            if expected_output and output.strip() != expected_output.strip():
                return False, f"输出不匹配: 期望 {expected_output[:50]}, 实际 {output[:50]}"
            if expected_contains and expected_contains not in output:
                return False, f"未找到: {expected_contains}"
            return True, f"命令验证通过: {output[:50]}"
        except subprocess.TimeoutExpired:
            return False, f"命令超时"
        except Exception as e:
            return False, f"执行失败: {e}"

    @staticmethod
    def validate_execution_output(code: str, expected_output: str = None,
                                  expected_contains: str = None) -> Tuple[bool, str]:
        """验证代码执行输出"""
        try:
            # 在受限环境中执行
            import io
            import contextlib
            stdout_capture = io.StringIO()
            with contextlib.redirect_stdout(stdout_capture):
                exec(code, {"__builtins__": __builtins__})
            output = stdout_capture.getvalue()
            if expected_output and output.strip() != expected_output.strip():
                return False, f"输出不匹配: 期望 {expected_output}, 实际 {output}"
            if expected_contains and expected_contains not in output:
                return False, f"未找到: {expected_contains}"
            return True, f"执行验证通过: {output[:50]}"
        except Exception as e:
            return False, f"执行失败: {e}"

    @staticmethod
    def validate_search_results(results: List, expected_count: int = None,
                                min_count: int = None) -> Tuple[bool, str]:
        """验证搜索结果"""
        if not isinstance(results, list):
            return False, f"结果不是列表: {type(results)}"
        if expected_count is not None and len(results) != expected_count:
            return False, f"数量不匹配: 期望 {expected_count}, 实际 {len(results)}"
        if min_count is not None and len(results) < min_count:
            return False, f"数量不足: 期望至少 {min_count}, 实际 {len(results)}"
        return True, f"搜索验证通过: {len(results)} 个结果"


# ============================================================================
# 全局单例
# ============================================================================

_global_guard: Optional[AgentGuard] = None


def get_agent_guard(project_root: str = ".") -> AgentGuard:
    """获取全局 AgentGuard 单例"""
    global _global_guard
    if _global_guard is None:
        _global_guard = AgentGuard(project_root)
    return _global_guard


def get_tool_permission(tool_name: str, args: Dict) -> PermissionLevel:
    """查询工具权限（快捷接口）"""
    return get_agent_guard().check_permission(tool_name, args)


def get_agent_status() -> Dict:
    """查询 Agent 状态（快捷接口）"""
    return get_agent_guard().get_state()


def list_safety_rules() -> List[Dict]:
    """列出安全规则（快捷接口）"""
    return get_agent_guard().list_safety_rules()
