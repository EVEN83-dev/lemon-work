# -*- coding: utf-8 -*-
"""
Context Manager — 对话上下文管理器
===================================
为 Lemon Code 标准模式提供多轮对话上下文管理能力。

功能：
1. 管理对话历史（user/assistant/system 消息）
2. 自动压缩上下文（超过阈值时生成摘要）
3. 支持上下文持久化（SQLite）
4. 支持上下文注入（few-shot examples）
"""

import json
import time
import threading
from typing import List, Dict, Optional
from datetime import datetime


class ContextMessage:
    """上下文消息"""
    def __init__(self, role: str, content: str, timestamp: float = None):
        self.role = role  # 'user', 'assistant', 'system'
        self.content = content
        self.timestamp = timestamp or time.time()
    
    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ContextMessage':
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", time.time()),
        )


class ContextManager:
    """对话上下文管理器
    
    使用示例：
        ctx = ContextManager(max_history=20)
        ctx.add_message("user", "你好")
        ctx.add_message("assistant", "你好！有什么可以帮助你的？")
        context = ctx.get_context()
        compressed = ctx.compress_context()
    """
    
    def __init__(self, max_history: int = 20, max_tokens_estimate: int = 4000):
        """
        Args:
            max_history: 最大保留的消息轮数（每轮=user+assistant）
            max_tokens_estimate: 最大 token 估算数（用于触发压缩）
        """
        self._history: List[ContextMessage] = []
        self._max_history = max_history
        self._max_tokens_estimate = max_tokens_estimate
        self._lock = threading.Lock()
        
        # 系统提示词（可选）
        self._system_prompt: Optional[str] = None
        
        # 注入的 few-shot 示例
        self._few_shot_examples: List[Dict[str, str]] = []
        
        # 持久化
        self._db_path: Optional[str] = None
    
    def set_system_prompt(self, prompt: str):
        """设置系统提示词"""
        self._system_prompt = prompt
    
    def set_few_shot_examples(self, examples: List[Dict[str, str]]):
        """设置 few-shot 示例
        
        Args:
            examples: [{"user": "...", "assistant": "..."}, ...]
        """
        self._few_shot_examples = examples
    
    def add_message(self, role: str, content: str):
        """添加消息到上下文
        
        Args:
            role: 'user', 'assistant', 或 'system'
            content: 消息内容
        """
        with self._lock:
            msg = ContextMessage(role=role, content=content)
            self._history.append(msg)
            
            # 超过最大轮数时自动裁剪
            max_messages = self._max_history * 2  # 每轮2条消息
            if len(self._history) > max_messages:
                self._history = self._history[-max_messages:]
    
    def get_context(self, include_system: bool = True) -> List[dict]:
        """获取完整的上下文消息列表
        
        Args:
            include_system: 是否包含系统提示词
            
        Returns:
            消息列表，格式为 [{"role": "...", "content": "..."}, ...]
        """
        with self._lock:
            result = []
            
            # 1. 系统提示词
            if include_system and self._system_prompt:
                result.append({"role": "system", "content": self._system_prompt})
            
            # 2. Few-shot 示例
            for example in self._few_shot_examples:
                if "user" in example:
                    result.append({"role": "user", "content": example["user"]})
                if "assistant" in example:
                    result.append({"role": "assistant", "content": example["assistant"]})
            
            # 3. 对话历史
            for msg in self._history:
                result.append(msg.to_dict())
            
            return result
    
    def get_recent_context(self, n: int = 10) -> List[dict]:
        """获取最近 n 条消息（不含 system prompt 和 few-shot）"""
        with self._lock:
            recent = self._history[-n:] if len(self._history) > n else self._history
            return [msg.to_dict() for msg in recent]
    
    def compress_context(self) -> Optional[str]:
        """压缩上下文（当消息过多时生成摘要）
        
        Returns:
            压缩后的摘要文本，如果不需要压缩则返回 None
        """
        with self._lock:
            if len(self._history) <= self._max_history:
                return None
            
            # 保留最近的消息，将早期消息压缩为摘要
            keep_recent = self._max_history // 2  # 保留最近一半
            to_compress = self._history[:-keep_recent]
            
            # 生成摘要
            summary_parts = []
            for msg in to_compress:
                role_label = "用户" if msg.role == "user" else "助手"
                # 截断长消息
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                summary_parts.append(f"[{role_label}]: {content}")
            
            summary = "以下是之前对话的摘要：\n" + "\n".join(summary_parts)
            
            # 替换历史：摘要 + 最近消息
            self._history = [
                ContextMessage(role="system", content=summary)
            ] + self._history[-keep_recent:]
            
            return summary
    
    def estimate_tokens(self) -> int:
        """估算当前上下文的总 token 数（粗略估算：中文约1.5字符/token，英文约4字符/token）"""
        total_chars = 0
        with self._lock:
            for msg in self._history:
                total_chars += len(msg.content)
            if self._system_prompt:
                total_chars += len(self._system_prompt)
            for example in self._few_shot_examples:
                total_chars += len(example.get("user", "")) + len(example.get("assistant", ""))
        
        # 粗略估算：中英文混合，约 2.5 字符/token
        return total_chars // 2
    
    def should_compress(self) -> bool:
        """判断是否需要压缩上下文"""
        return len(self._history) > self._max_history or self.estimate_tokens() > self._max_tokens_estimate
    
    def clear(self):
        """清空上下文"""
        with self._lock:
            self._history.clear()
    
    def to_json(self) -> str:
        """序列化为 JSON"""
        with self._lock:
            data = {
                "history": [msg.to_dict() for msg in self._history],
                "system_prompt": self._system_prompt,
                "few_shot_examples": self._few_shot_examples,
                "max_history": self._max_history,
                "saved_at": datetime.now().isoformat(),
            }
            return json.dumps(data, ensure_ascii=False, indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ContextManager':
        """从 JSON 反序列化"""
        data = json.loads(json_str)
        ctx = cls(max_history=data.get("max_history", 20))
        ctx._system_prompt = data.get("system_prompt")
        ctx._few_shot_examples = data.get("few_shot_examples", [])
        for msg_data in data.get("history", []):
            ctx._history.append(ContextMessage.from_dict(msg_data))
        return ctx
    
    def save_to_file(self, filepath: str):
        """保存上下文到文件"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self.to_json())
    
    def load_from_file(self, filepath: str) -> bool:
        """从文件加载上下文"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                ctx = self.from_json(f.read())
            self._history = ctx._history
            self._system_prompt = ctx._system_prompt
            self._few_shot_examples = ctx._few_shot_examples
            return True
        except (FileNotFoundError, json.JSONDecodeError):
            return False
    
    @property
    def history_length(self) -> int:
        """当前历史消息数量"""
        return len(self._history)
    
    @property
    def is_empty(self) -> bool:
        """上下文是否为空"""
        return len(self._history) == 0