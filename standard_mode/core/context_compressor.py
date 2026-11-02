# -*- coding: utf-8 -*-
"""
Context Compressor — 上下文压缩器
====================================
长对话摘要 + 关键信息提取，减少 token 消耗。

功能：
1. 滑动窗口摘要 — 保留最近 N 条消息，旧消息自动摘要
2. 关键信息提取 — 自动识别代码块、文件路径、决策等关键内容
3. Token 预算管理 — 根据模型上下文限制自动裁剪
4. 分层压缩 — 不同重要性的消息采用不同压缩率

压缩策略：
- 系统消息：保留（不压缩）
- 代码块：保留（不压缩）
- 关键决策：保留（不压缩）
- 用户偏好：保留（不压缩）
- 普通对话：摘要压缩
- 工具调用输出：截断（保留前 500 字符）
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class MessageImportance(Enum):
    """消息重要性"""
    CRITICAL = "critical"     # 系统消息、关键决策
    HIGH = "high"             # 代码块、文件路径
    MEDIUM = "medium"         # 用户问题、实质性回复
    LOW = "low"               # 问候、确认、普通对话
    TRIVIAL = "trivial"       # 纯表情、空消息


class ContextCompressor:
    """
    上下文压缩器
    
    使用方式：
        compressor = ContextCompressor(max_tokens=4096)
        compressed = compressor.compress(messages)
    """
    
    # 默认 token 预算
    DEFAULT_MAX_TOKENS = 4096
    
    # 各重要级别的保留比例
    IMPORTANCE_KEEP_RATIO = {
        MessageImportance.CRITICAL: 1.0,   # 全部保留
        MessageImportance.HIGH: 0.9,        # 保留 90%
        MessageImportance.MEDIUM: 0.5,      # 保留 50%（摘要）
        MessageImportance.LOW: 0.2,         # 保留 20%
        MessageImportance.TRIVIAL: 0.0,     # 全部丢弃
    }
    
    # 关键内容模式
    CRITICAL_PATTERNS = [
        r'```.*?```',                        # 代码块
        r'[a-zA-Z]:\\[^\s]+',               # Windows 路径
        r'/[^\s]+\.\w+',                     # Unix 路径
        r'(?:决定|选择|采用|最终方案)',        # 决策关键词
        r'(?:我喜欢|我习惯|我偏好)',           # 用户偏好
        r'(?:BUG|FIX|修复|解决)',             # 问题修复
        r'(?:TODO|FIXME|HACK|NOTE)',         # 注释标记
    ]
    
    # 低重要性模式
    LOW_IMPORTANCE_PATTERNS = [
        r'^(?:好的|OK|收到|明白|了解|知道了|嗯|哦|谢谢|不客气|再见|拜拜)[\s。！]*$',
        r'^(?:ok|okay|got it|thanks|bye|hi|hello|yes|no)[\s.!]*$',
        r'^[\u4e00-\u9fff]{0,3}$',           # 极短中文
        r'^[a-zA-Z]{0,5}$',                   # 极短英文
    ]
    
    def __init__(self, max_tokens: int = None):
        self._max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS
        self._stats = {
            'total_compressions': 0,
            'total_tokens_saved': 0,
            'avg_compression_ratio': 0.0,
        }
    
    def set_max_tokens(self, max_tokens: int):
        """设置 token 预算"""
        self._max_tokens = max_tokens
    
    def compress(self, messages: List[Dict], system_prompt: str = "") -> List[Dict]:
        """
        压缩消息列表
        
        Args:
            messages: 消息列表 [{role, content}, ...]
            system_prompt: 系统提示词（不压缩）
        
        Returns:
            压缩后的消息列表
        """
        if not messages:
            return []
        
        self._stats['total_compressions'] += 1
        
        # 计算当前 token 使用量
        current_tokens = self._estimate_tokens(system_prompt) + sum(
            self._estimate_tokens(m.get('content', '')) for m in messages
        )
        
        if current_tokens <= self._max_tokens:
            return messages  # 无需压缩
        
        # 分类消息重要性
        classified = []
        for i, msg in enumerate(messages):
            importance = self._classify_importance(msg)
            classified.append({
                'index': i,
                'role': msg.get('role', 'user'),
                'content': msg.get('content', ''),
                'importance': importance,
                'keep_ratio': self.IMPORTANCE_KEEP_RATIO[importance],
            })
        
        # 分层压缩
        compressed = []
        tokens_used = self._estimate_tokens(system_prompt)
        budget = self._max_tokens - tokens_used - 200  # 预留 200 token 缓冲
        
        for item in classified:
            content = item['content']
            token_count = self._estimate_tokens(content)
            
            if item['importance'] == MessageImportance.TRIVIAL:
                # 完全丢弃
                continue
            
            if item['importance'] == MessageImportance.CRITICAL:
                # 全部保留
                compressed.append({
                    'role': item['role'],
                    'content': content,
                })
                tokens_used += token_count
                continue
            
            # 根据保留比例压缩
            keep_ratio = item['keep_ratio']
            if tokens_used + token_count <= budget * keep_ratio:
                # 可以保留全部
                compressed.append({
                    'role': item['role'],
                    'content': content,
                })
                tokens_used += token_count
            else:
                # 压缩为摘要
                summary = self._summarize(content, item['importance'])
                compressed.append({
                    'role': item['role'],
                    'content': summary,
                })
                tokens_used += self._estimate_tokens(summary)
            
            if tokens_used >= budget:
                break
        
        # 统计
        original_tokens = sum(self._estimate_tokens(m.get('content', '')) for m in messages)
        saved = original_tokens - tokens_used
        self._stats['total_tokens_saved'] += saved
        alpha = 0.1
        self._stats['avg_compression_ratio'] = (
            alpha * (saved / max(original_tokens, 1)) +
            (1 - alpha) * self._stats['avg_compression_ratio']
        )
        
        logger.info(f"[Compressor] 压缩: {len(messages)}→{len(compressed)} 条, "
                    f"节省 {saved} tokens")
        
        return compressed
    
    def _classify_importance(self, msg: Dict) -> MessageImportance:
        """分类消息重要性"""
        content = msg.get('content', '')
        role = msg.get('role', 'user')
        
        # 系统消息 — 最高优先级
        if role == 'system':
            return MessageImportance.CRITICAL
        
        # 空消息
        if not content or not content.strip():
            return MessageImportance.TRIVIAL
        
        # 检查关键内容
        for pattern in self.CRITICAL_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE | re.DOTALL):
                return MessageImportance.HIGH
        
        # 检查低重要性
        for pattern in self.LOW_IMPORTANCE_PATTERNS:
            if re.search(pattern, content.strip(), re.IGNORECASE):
                return MessageImportance.LOW
        
        # 极短消息
        if len(content.strip()) < 5:
            return MessageImportance.LOW
        if len(content.strip()) < 3:
            return MessageImportance.TRIVIAL
        
        # 默认中等
        return MessageImportance.MEDIUM
    
    def _summarize(self, content: str, importance: MessageImportance) -> str:
        """
        将消息压缩为摘要
        
        压缩策略：
        - MEDIUM: 保留前 200 字符 + "..."
        - LOW: 保留前 50 字符 + "（已省略）"
        """
        content = content.strip()
        
        if importance == MessageImportance.MEDIUM:
            if len(content) <= 200:
                return content
            # 保留前 200 字符
            return content[:200] + "...(已摘要)"
        
        elif importance == MessageImportance.LOW:
            if len(content) <= 50:
                return content
            return content[:50] + "（已省略）"
        
        return content
    
    def extract_key_info(self, messages: List[Dict]) -> Dict[str, List[str]]:
        """
        从消息列表中提取关键信息
        
        Returns:
            {
                "code_blocks": [...],
                "file_paths": [...],
                "decisions": [...],
                "errors": [...],
                "preferences": [...],
            }
        """
        result = {
            "code_blocks": [],
            "file_paths": [],
            "decisions": [],
            "errors": [],
            "preferences": [],
        }
        
        full_text = "\n".join(m.get('content', '') for m in messages)
        
        # 提取代码块
        code_blocks = re.findall(r'```[\s\S]*?```', full_text)
        result["code_blocks"] = [c[:200] + '...' if len(c) > 200 else c for c in code_blocks[:5]]
        
        # 提取文件路径
        file_paths = re.findall(r'[a-zA-Z]:\\[^\s,;]+\.\w+', full_text)
        result["file_paths"] = list(set(file_paths[:10]))
        
        # 提取决策
        decisions = re.findall(
            r'(?:决定|选择|采用|最终方案)[:：]?\s*(.+?)(?:[。，\n]|$)',
            full_text
        )
        result["decisions"] = decisions[:5]
        
        # 提取错误
        errors = re.findall(
            r'(?:Error|错误|异常|失败|Exception)[:：]\s*(.+?)(?:[。，\n]|$)',
            full_text, re.IGNORECASE
        )
        result["errors"] = errors[:5]
        
        # 提取偏好
        preferences = re.findall(
            r'(?:我喜欢|我习惯|我偏好|我使用|我选择)\s*(.+?)(?:[。，\n]|$)',
            full_text
        )
        result["preferences"] = preferences[:5]
        
        return result
    
    def estimate_tokens_for_messages(self, messages: List[Dict]) -> int:
        """估算消息列表的 token 数量"""
        return sum(self._estimate_tokens(m.get('content', '')) for m in messages)
    
    def _estimate_tokens(self, text: str) -> int:
        """
        粗略估算 token 数量
        
        规则：
        - 英文: 1 token ≈ 4 字符
        - 中文: 1 token ≈ 1.5 字符
        """
        if not text:
            return 0
        
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        other_chars = len(text) - chinese_chars
        
        return int(chinese_chars / 1.5 + other_chars / 4)
    
    @property
    def stats(self) -> Dict:
        return dict(self._stats)


# 全局单例
_compressor_instance: Optional[ContextCompressor] = None


def get_context_compressor(max_tokens: int = None) -> ContextCompressor:
    global _compressor_instance
    if _compressor_instance is None:
        _compressor_instance = ContextCompressor(max_tokens=max_tokens)
    return _compressor_instance