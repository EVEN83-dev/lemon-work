from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


class BaseMode(ABC):
    name: str = ""
    display_name: str = ""
    description: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    blocked_tools: List[str] = field(default_factory=list)
    prompt_template: str = ""
    permission_level: str = "standard"

    @abstractmethod
    def __init__(self) -> None:
        ...

    def is_tool_allowed(self, tool_id: str) -> bool:
        if tool_id in self.blocked_tools:
            return False
        if self.allowed_tools:
            return tool_id in self.allowed_tools
        return True

    def get_system_prompt(self) -> str:
        return self.prompt_template

    def get_config(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "allowed_tools": list(self.allowed_tools),
            "blocked_tools": list(self.blocked_tools),
            "prompt_template": self.prompt_template,
            "permission_level": self.permission_level,
        }


class StandardMode(BaseMode):
    name = "standard"
    display_name = "Standard Mode"
    description = "Full access to all tools and capabilities with standard permissions."
    allowed_tools: List[str] = []
    blocked_tools: List[str] = []
    permission_level = "standard"
    prompt_template = (
        "You are LemonCode, a versatile AI coding assistant operating in Standard Mode. "
        "You have full access to all available tools and capabilities including shell execution, "
        "file operations, code analysis, browser automation, deep research, and specialized assistants. "
        "Your primary goal is to help users accomplish their coding and technical tasks efficiently. "
        "You can read, write, and edit files; execute shell commands; search codebases; analyze code; "
        "browse the web; and leverage specialized tools as needed. "
        "Always follow best practices for security, code quality, and user safety. "
        "Ask for clarification when requirements are ambiguous. "
        "Provide clear explanations of your actions and rationale when performing complex operations."
    )

    def __init__(self) -> None:
        pass


class MinimalMode(BaseMode):
    name = "minimal"
    display_name = "Minimal Mode"
    description = "Restricted mode with only basic file and shell tools for focused code tasks."
    allowed_tools: List[str] = ["shell_exec", "file_read", "file_write", "file_edit"]
    blocked_tools: List[str] = [
        "browser_automation",
        "finance_assistant",
        "code_playback",
        "deep_researcher",
        "html_to_video",
    ]
    permission_level = "restricted"
    prompt_template = (
        "You are LemonCode operating in Minimal Mode. "
        "You have access only to basic tools: shell execution, file reading, file writing, and file editing. "
        "Focus strictly on code-related tasks that can be accomplished with these fundamental capabilities. "
        "Do not attempt to use browser automation, finance tools, research tools, or other restricted capabilities. "
        "Keep responses concise and task-focused. "
        "If a request requires tools beyond your current access, inform the user and suggest switching to Standard or Creator mode."
    )

    def __init__(self) -> None:
        pass


class CreatorMode(BaseMode):
    name = "creator"
    display_name = "Creator Mode"
    description = "Elevated permissions for creative and experimental workflows with runtime checks and plugin support."
    allowed_tools: List[str] = []
    blocked_tools: List[str] = []
    permission_level = "elevated"
    prompt_template = (
        "You are LemonCode operating in Creator Mode. "
        "You have elevated permissions that enable creative and experimental workflows. "
        "All tools are available, and you are encouraged to explore innovative solutions, "
        "experiment with code patterns, and leverage runtime checks and plugin capabilities. "
        "You may run experimental code, test unconventional approaches, and iterate rapidly. "
        "When using elevated capabilities, always explain what you are doing and why. "
        "Exercise extra caution with system-modifying operations. "
        "Document your experimental findings and flag any unstable or untested approaches. "
        "Embrace creativity while maintaining safety and reliability."
    )

    def __init__(self) -> None:
        pass


class CustomMode(BaseMode):
    name = "custom"
    display_name = "Custom Mode"
    description = "User-configured mode with custom tool access and permissions."

    def __init__(
        self,
        allowed_tools: List[str] | None = None,
        blocked_tools: List[str] | None = None,
        prompt_template: str = "",
        permission_level: str = "standard",
    ) -> None:
        self.allowed_tools = allowed_tools if allowed_tools is not None else []
        self.blocked_tools = blocked_tools if blocked_tools is not None else []
        self.prompt_template = prompt_template or "You are LemonCode operating in Custom Mode."
        self.permission_level = permission_level

    @classmethod
    def from_config(cls, name: str, config: dict) -> "CustomMode":
        instance = cls(
            allowed_tools=config.get("allowed_tools", []),
            blocked_tools=config.get("blocked_tools", []),
            prompt_template=config.get("prompt_template", ""),
            permission_level=config.get("permission_level", "standard"),
        )
        instance.name = name
        instance.display_name = config.get("display_name", name.replace("_", " ").title())
        instance.description = config.get("description", "")
        return instance
