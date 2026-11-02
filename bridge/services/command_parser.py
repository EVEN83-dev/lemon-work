"""
B-P2-001: Command Parser Service

Parses user input into commands or skill routes.
Flow: /command → builtin | keyword match → skill | LLM intent → skill
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CommandType(str, Enum):
    BUILTIN = "builtin"
    SKILL = "skill"
    CHAT = "chat"


@dataclass
class ParsedCommand:
    command_type: CommandType = CommandType.CHAT
    command_name: str = ""
    skill_id: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    original_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commandType": self.command_type.value,
            "commandName": self.command_name,
            "skillId": self.skill_id,
            "params": self.params,
            "originalText": self.original_text,
        }


BUILTIN_COMMANDS: Dict[str, Dict[str, Any]] = {
    "help": {"description": "显示帮助"},
    "skills": {"description": "列出所有 Skill"},
    "history": {"description": "查看历史会话"},
    "new": {"description": "新建会话"},
    "clear": {"description": "清除当前会话"},
    "pomodoro": {"description": "启动番茄钟", "skill": "pomodoro_skill"},
    "memory": {"description": "管理记忆", "skill": "memory_query"},
    "search": {"description": "搜索网页/代码", "skill": "web_researcher", "card": "search"},
    "code": {"description": "代码操作(生成/审查/格式化)", "skill": "code_helper", "card": "code"},
    "file": {"description": "操作文件", "skill": "file_service", "card": "file"},
    "git": {"description": "Git版本控制", "skill": "git_skill", "card": "git"},
    "run": {"description": "运行命令/脚本", "skill": "terminal_run_skill", "card": "run"},
    "pip": {"description": "Python包管理", "skill": "package_manager", "card": "pip"},
    "shell": {"description": "执行Shell命令", "skill": "terminal_run_skill", "card": "shell"},
    "web": {"description": "网页嵌入/预览", "skill": "browser_automation", "card": "web"},
    "diagram": {"description": "生成图表", "skill": "math_plotter", "card": "diagram"},
    "translate": {"description": "翻译文本", "skill": "translator", "card": "translate"},
    "calc": {"description": "数学计算", "skill": "math_solver", "card": "calc"},
    "weather": {"description": "查询天气", "skill": "weather_service", "card": "weather"},
    "time": {"description": "查看时间/时区", "card": "time"},
    "mode": {"description": "切换显示模式"},
}

INTENT_RULES: List[Dict[str, Any]] = [
    {"pattern": r"番茄钟|番茄|计时|倒计时", "skill": "pomodoro_skill",
     "param_extractors": {"minutes": r"(\d+)\s*分钟"}},
    {"pattern": "写文档|生成文档|周报|日报|文档生成", "skill": "office_generator",
     "param_extractors": {"template": r"(周报|日报|月报|报告)"}},
    {"pattern": "分析PDF|读取PDF|PDF|pdf", "skill": "pdf_reader"},
    {"pattern": "写代码|编程|代码|实现|函数|排序|算法", "skill": "code_helper"},
    {"pattern": "搜索|查询|查一下|百度|google|搜索代码", "skill": "web_researcher",
     "param_extractors": {"query": r"搜索[：:]?\s*(.+)"}},
    {"pattern": "数据分析|图表|统计|可视化", "skill": "data_analysis"},
    {"pattern": "邮件|发送邮件|写信", "skill": "email_composer"},
    {"pattern": "翻译|英文|中文|translate", "skill": "translator",
     "param_extractors": {"text": r"翻译[：:]?\s*(.+)"}},
    {"pattern": "记忆|我记得|我之前|我告诉过", "skill": "memory_query"},
    {"pattern": "天气|气温|温度|下雨|下雪|晴|阴", "skill": "weather_service",
     "param_extractors": {"location": r"([\u4e00-\u9fff]+)(?:的)?天气"}},
    {"pattern": "日程|日历|会议|安排|行程", "skill": "calendar_service",
     "param_extractors": {"date": r"(今天|明天|本周|下周)"}},
    {"pattern": "文件|打开|读取|保存|下载", "skill": "file_service"},
    {"pattern": "录音|语音|录制|麦克风", "skill": "audio_service"},
    {"pattern": "联系人|电话|号码|通讯录", "skill": "contact_service"},
    {"pattern": "git|提交|推送|拉取|分支|合并|checkout|commit|push|pull", "skill": "git_skill",
     "param_extractors": {"subcmd": r"(commit|push|pull|checkout|merge|stash|log|status|diff|branch)"}},
    {"pattern": "运行|执行|跑一下|run|npm|python|启动", "skill": "terminal_run_skill",
     "param_extractors": {"command": r"(?:运行|执行|跑一下|run)\s*(.+)"}},
    {"pattern": "pip|安装包|卸载包|包管理|install|uninstall|requirements", "skill": "package_manager",
     "param_extractors": {"package": r"(?:install|uninstall)\s+(\S+)"}},
    {"pattern": "shell|终端|命令行|cmd|bash|powershell", "skill": "terminal_run_skill",
     "param_extractors": {"command": r"(?:shell|终端|命令行)\s*[：:]?\s*(.+)"}},
    {"pattern": "图表|流程图|diagram|mermaid|架构图", "skill": "math_plotter",
     "param_extractors": {"type": r"(流程图|架构图|时序图|类图)"}},
    {"pattern": "计算|算一下|calc|等于多少|数学", "skill": "math_solver",
     "param_extractors": {"expression": r"(?:计算|算一下|calc)\s*(.+)"}},
    {"pattern": "时间|几点|时区|clock|当前时间", "skill": "time_service"},
]


class CommandParser:
    def __init__(self, intent_rules: Optional[List[Dict[str, Any]]] = None):
        self.rules = intent_rules or INTENT_RULES

    def parse(self, text: str) -> ParsedCommand:
        text = text.strip()
        if not text:
            return ParsedCommand(command_type=CommandType.CHAT, original_text=text)

        if text.startswith("/"):
            return self._parse_builtin(text)

        for rule in self.rules:
            pattern = rule["pattern"]
            if re.search(pattern, text):
                params = self._extract_params(text, rule.get("param_extractors", {}))
                return ParsedCommand(
                    command_type=CommandType.SKILL,
                    command_name=rule["skill"],
                    skill_id=rule["skill"],
                    params=params,
                    original_text=text,
                )

        return ParsedCommand(command_type=CommandType.CHAT, original_text=text)

    def _parse_builtin(self, text: str) -> ParsedCommand:
        parts = text[1:].split()
        if not parts:
            return ParsedCommand(command_type=CommandType.CHAT, original_text=text)

        cmd_name = parts[0].lower()
        if cmd_name in BUILTIN_COMMANDS:
            cmd_info = BUILTIN_COMMANDS[cmd_name]
            params: Dict[str, Any] = {}
            if len(parts) > 1:
                params["args"] = " ".join(parts[1:])
            result = ParsedCommand(
                command_type=CommandType.BUILTIN,
                command_name=cmd_name,
                params=params,
                original_text=text,
            )
            if "skill" in cmd_info:
                result.command_type = CommandType.SKILL
                result.skill_id = cmd_info["skill"]
            return result

        return ParsedCommand(command_type=CommandType.CHAT, original_text=text)

    def _extract_params(
        self, text: str, extractors: Dict[str, str]
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for key, pattern in extractors.items():
            match = re.search(pattern, text)
            if match:
                params[key] = match.group(1)
        return params
