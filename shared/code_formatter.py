# -*- coding: utf-8 -*-
"""
代码格式化器（v0.6.0 新增）
=============================
功能：
- Python: Black 自动格式化
- JavaScript/TypeScript: Prettier 格式化
- Go: gofmt
- JSON: 内置格式化
- 保存时自动格式化（可选）
"""

import os
import subprocess
import json
import tempfile
from typing import Optional, Tuple, List, Dict


class CodeFormatter:
    """
    代码格式化器
    
    支持的语言和工具：
    - Python: black (pip install black)
    - JavaScript/TypeScript: prettier (npm install -g prettier)
    - Go: gofmt (Go 自带)
    - JSON: 内置 json 模块
    """
    
    # 格式化工具配置
    FORMATTERS = {
        ".py": {
            "tool": "black",
            "args": ["--stdin-filename", "$FILE", "-"],
            "install": "pip install black",
        },
        ".pyw": {
            "tool": "black",
            "args": ["--stdin-filename", "$FILE", "-"],
            "install": "pip install black",
        },
        ".js": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".mjs": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".cjs": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".ts": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".tsx": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".jsx": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".json": {
            "tool": "builtin",
            "args": [],
            "install": None,
        },
        ".go": {
            "tool": "gofmt",
            "args": [],
            "install": "go install golang.org/x/tools/cmd/gofmt@latest",
        },
        ".css": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".scss": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".less": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".html": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".htm": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".md": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".yaml": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
        ".yml": {
            "tool": "prettier",
            "args": ["--stdin-filepath", "$FILE"],
            "install": "npm install -g prettier",
        },
    }
    
    def __init__(self):
        self._tool_cache: Dict[str, bool] = {}  # 工具可用性缓存
    
    def is_supported(self, file_path: str) -> bool:
        """检查文件是否支持格式化"""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in self.FORMATTERS
    
    def get_formatter(self, file_path: str) -> Optional[str]:
        """获取文件的格式化工具名称"""
        ext = os.path.splitext(file_path)[1].lower()
        config = self.FORMATTERS.get(ext)
        return config.get("tool") if config else None
    
    def format_file(self, file_path: str, content: str) -> Tuple[bool, str, str]:
        """
        格式化代码
        
        Args:
            file_path: 文件路径（用于确定格式化工具）
            content: 原始代码内容
        
        Returns:
            (success, formatted_content, error_message)
        """
        ext = os.path.splitext(file_path)[1].lower()
        config = self.FORMATTERS.get(ext)
        
        if not config:
            return False, content, f"不支持的文件类型: {ext}"
        
        tool = config["tool"]
        
        # 内置格式化器
        if tool == "builtin":
            return self._format_builtin(file_path, content)
        
        # 检查工具是否可用
        if not self._check_tool_available(tool):
            install_cmd = config.get("install", "")
            return False, content, f"格式化工具未安装: {tool}\n安装命令: {install_cmd}"
        
        # 使用外部工具格式化
        return self._format_with_tool(file_path, content, config)
    
    def _format_builtin(self, file_path: str, content: str) -> Tuple[bool, str, str]:
        """内置格式化器（JSON等）"""
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == ".json":
            try:
                parsed = json.loads(content)
                formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
                return True, formatted, ""
            except json.JSONDecodeError as e:
                return False, content, f"JSON解析错误: {e}"
        
        # 其他内置格式化（未来扩展）
        return True, content, ""
    
    def _format_with_tool(self, file_path: str, content: str, config: Dict) -> Tuple[bool, str, str]:
        """使用外部工具格式化"""
        tool = config["tool"]
        args = config.get("args", [])
        
        # 替换参数中的占位符
        processed_args = []
        for arg in args:
            if arg == "$FILE":
                processed_args.append(file_path)
            else:
                processed_args.append(arg)
        
        try:
            # Windows 下使用 subprocess
            process = subprocess.Popen(
                [tool] + processed_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            
            stdout, stderr = process.communicate(input=content, timeout=30)
            
            if process.returncode == 0:
                return True, stdout, ""
            else:
                error_msg = stderr.strip() or f"{tool} 返回错误码 {process.returncode}"
                return False, content, error_msg
        
        except subprocess.TimeoutExpired:
            process.kill()
            return False, content, f"{tool} 格式化超时"
        
        except FileNotFoundError:
            self._tool_cache[tool] = False
            return False, content, f"格式化工具未找到: {tool}"
        
        except Exception as e:
            return False, content, f"格式化错误: {str(e)}"
    
    def _check_tool_available(self, tool: str) -> bool:
        """检查工具是否可用"""
        if tool in self._tool_cache:
            return self._tool_cache[tool]
        
        try:
            result = subprocess.run(
                ["where", tool] if os.name == "nt" else ["which", tool],
                capture_output=True,
                timeout=5
            )
            available = result.returncode == 0
            self._tool_cache[tool] = available
            return available
        except Exception:
            self._tool_cache[tool] = False
            return False
    
    def format_and_save(self, file_path: str, content: str) -> Tuple[bool, str]:
        """
        格式化并保存文件
        
        Args:
            file_path: 文件路径
            content: 原始内容
        
        Returns:
            (success, message)
        """
        success, formatted, error = self.format_file(file_path, content)
        
        if success and formatted != content:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(formatted)
                return True, "格式化完成"
            except Exception as e:
                return False, f"保存失败: {str(e)}"
        
        return success, error or "无需格式化"
    
    def get_supported_extensions(self) -> List[str]:
        """获取支持的文件扩展名列表"""
        return list(self.FORMATTERS.keys())
    
    def get_missing_tools(self) -> List[Tuple[str, str]]:
        """
        获取缺失的格式化工具
        
        Returns:
            List of (tool_name, install_command)
        """
        missing = []
        checked = set()
        
        for ext, config in self.FORMATTERS.items():
            tool = config.get("tool")
            if tool and tool != "builtin" and tool not in checked:
                checked.add(tool)
                if not self._check_tool_available(tool):
                    install_cmd = config.get("install", "")
                    missing.append((tool, install_cmd))
        
        return missing


# 导入 Dict 类型
from typing import Dict


# ============================================================
# 格式化管理器（集成到主窗口）
# ============================================================

class FormatterManager:
    """
    格式化管理器 — 提供统一的格式化接口
    
    功能：
    - 自动检测文件类型
    - 调用对应格式化工具
    - 支持保存时自动格式化
    - 缺失工具提示
    """
    
    def __init__(self):
        self.formatter = CodeFormatter()
        self._format_on_save = True
    
    @property
    def format_on_save(self) -> bool:
        """是否在保存时自动格式化"""
        return self._format_on_save
    
    @format_on_save.setter
    def format_on_save(self, value: bool):
        self._format_on_save = value
    
    def format(self, file_path: str, content: str) -> Tuple[bool, str, str]:
        """
        格式化代码
        
        Args:
            file_path: 文件路径
            content: 原始内容
        
        Returns:
            (success, formatted_content, message)
        """
        return self.formatter.format_file(file_path, content)
    
    def format_if_enabled(self, file_path: str, content: str) -> Tuple[bool, str, str]:
        """
        如果启用了保存时格式化，则格式化
        
        Args:
            file_path: 文件路径
            content: 原始内容
        
        Returns:
            (success, formatted_content, message)
        """
        if not self._format_on_save:
            return True, content, ""
        
        return self.format(file_path, content)
    
    def check_availability(self) -> Dict[str, bool]:
        """检查所有格式化工具的可用性"""
        availability = {}
        
        for ext, config in self.formatter.FORMATTERS.items():
            tool = config.get("tool")
            if tool and tool != "builtin":
                if tool not in availability:
                    availability[tool] = self.formatter._check_tool_available(tool)
        
        return availability
    
    def get_install_suggestions(self) -> str:
        """获取缺失工具的安装建议"""
        missing = self.formatter.get_missing_tools()
        if not missing:
            return "所有格式化工具已安装"
        
        lines = ["以下格式化工具未安装："]
        for tool, install_cmd in missing:
            lines.append(f"  - {tool}: {install_cmd}")
        
        return "\n".join(lines)