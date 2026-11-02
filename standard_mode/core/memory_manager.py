# -*- coding: utf-8 -*-
"""
Memory Manager — 项目级持久化记忆系统
=====================================
★ v3.64: 参考 MiMo Code 的 MEMORY.md 模式，提供文件式持久化记忆。

设计原则：
- Markdown 格式，用户可阅读/编辑
- 自动注入到 EngineManager 的 system_prompt
- 支持分类（用户偏好 / 项目约束 / 决策记录 / 教训总结）
- Agent 可通过 update_memory skill 主动更新

文件位置：lemon_agent/data/MEMORY.md
"""

import os
import threading
import logging
from typing import Optional, Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


# 默认记忆模板（首次创建时使用）
DEFAULT_MEMORY_TEMPLATE = """# Lemon Code 项目记忆

> 此文件由 Lemon Code 自动维护，记录用户偏好、项目约束、关键决策与教训。
> 用户可手动编辑；Agent 可通过 update_memory 技能追加内容。

## 用户偏好
（暂无记录）

## 项目约束
（暂无记录）

## 关键决策
（暂无记录）

## 教训总结
（暂无记录）
"""


class MemoryManager:
    """
    项目级持久化记忆管理器

    使用示例：
        mem = MemoryManager()
        mem.append("用户偏好", "代码风格偏好：使用 4 空格缩进")
        prompt = mem.get_memory_for_prompt()  # 注入到 system_prompt
    """

    # 支持的章节名（规范化）
    SECTIONS = ["用户偏好", "项目约束", "关键决策", "教训总结"]

    def __init__(self, memory_path: Optional[str] = None):
        if memory_path is None:
            # 默认路径：lemon_agent/data/MEMORY.md
            lemon_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            memory_path = os.path.join(lemon_root, "data", "MEMORY.md")
        self._memory_path = memory_path
        self._lock = threading.Lock()
        self._cache: Optional[str] = None
        self._cache_mtime: float = 0.0

    # ============================================================
    # 读取 / 保存
    # ============================================================

    def load_memory(self, force_reload: bool = False) -> str:
        """读取 MEMORY.md 内容（带 mtime 缓存）"""
        with self._lock:
            try:
                if not os.path.exists(self._memory_path):
                    return ""
                mtime = os.path.getmtime(self._memory_path)
                if not force_reload and self._cache is not None and mtime == self._cache_mtime:
                    return self._cache
                with open(self._memory_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self._cache = content
                self._cache_mtime = mtime
                return content
            except Exception as e:
                logger.warning(f"[Memory] 读取失败: {e}")
                return ""

    def save_memory(self, content: str) -> bool:
        """完整覆盖保存"""
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self._memory_path), exist_ok=True)
                with open(self._memory_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self._cache = content
                self._cache_mtime = os.path.getmtime(self._memory_path)
                logger.info(f"[Memory] 已保存 ({len(content)} 字符)")
                return True
            except Exception as e:
                logger.error(f"[Memory] 保存失败: {e}")
                return False

    def ensure_exists(self) -> bool:
        """若文件不存在则创建默认模板"""
        try:
            if not os.path.exists(self._memory_path):
                return self.save_memory(DEFAULT_MEMORY_TEMPLATE)
            return True
        except Exception as e:
            logger.warning(f"[Memory] 初始化失败: {e}")
            return False

    # ============================================================
    # 章节级追加
    # ============================================================

    def append(self, section: str, content: str, timestamp: bool = True) -> bool:
        """向指定章节追加一条记录

        Args:
            section: 章节名（如 "用户偏好"），不存在则创建
            content: 记录内容
            timestamp: 是否附带时间戳
        """
        try:
            current = self.load_memory()
            if not current:
                current = DEFAULT_MEMORY_TEMPLATE

            ts = f" [{datetime.now().strftime('%Y-%m-%d %H:%M')}]" if timestamp else ""
            new_line = f"-{ts} {content}\n"

            # 定位章节
            section_header = f"## {section}"
            lines = current.split("\n")
            section_idx = -1
            next_section_idx = -1

            for i, line in enumerate(lines):
                if line.strip() == section_header:
                    section_idx = i
                    break

            if section_idx == -1:
                # 章节不存在，追加到文件末尾
                new_content = current.rstrip() + f"\n\n{section_header}\n{new_line}\n"
                return self.save_memory(new_content)

            # 找到下一个 ## 章节位置
            for j in range(section_idx + 1, len(lines)):
                if lines[j].startswith("## "):
                    next_section_idx = j
                    break

            # 在章节内找到 "（暂无记录）" 占位符则替换
            insert_idx = next_section_idx if next_section_idx != -1 else len(lines)
            replaced = False
            for k in range(section_idx + 1, insert_idx):
                if "（暂无记录）" in lines[k]:
                    lines[k] = lines[k].replace("（暂无记录）", "").rstrip() + new_line.rstrip()
                    replaced = True
                    break

            if not replaced:
                # 在章节末尾插入新行
                # 跳过章节末尾的空行
                while insert_idx > 0 and lines[insert_idx - 1].strip() == "":
                    insert_idx -= 1
                lines.insert(insert_idx, new_line.rstrip())

            new_content = "\n".join(lines)
            return self.save_memory(new_content)
        except Exception as e:
            logger.error(f"[Memory] 追加失败: {e}")
            return False

    def clear_section(self, section: str) -> bool:
        """清空指定章节（保留章节标题）"""
        try:
            current = self.load_memory()
            if not current:
                return True
            section_header = f"## {section}"
            lines = current.split("\n")
            new_lines: List[str] = []
            in_target = False
            for line in lines:
                if line.startswith("## "):
                    in_target = (line.strip() == section_header)
                    new_lines.append(line)
                    if in_target:
                        new_lines.append("（已清空）")
                    continue
                if in_target:
                    continue  # 跳过原章节内容
                new_lines.append(line)
            return self.save_memory("\n".join(new_lines))
        except Exception as e:
            logger.error(f"[Memory] 清空章节失败: {e}")
            return False

    # ============================================================
    # 注入到系统提示词
    # ============================================================

    def get_memory_for_prompt(self, max_chars: int = 2000) -> str:
        """返回格式化的记忆字符串，供注入到 system_prompt

        Args:
            max_chars: 最大字符数（截断保护）
        """
        content = self.load_memory().strip()
        if not content:
            return ""
        if len(content) > max_chars:
            content = content[:max_chars] + "\n...(记忆已截断)"
        return f"\n\n=== 项目记忆（MEMORY.md）===\n{content}\n=== 记忆结束 ===\n"

    def inject_into_prompt(self, system_prompt: str, max_chars: int = 2000) -> str:
        """把记忆注入到现有 system_prompt 末尾"""
        mem = self.get_memory_for_prompt(max_chars=max_chars)
        if not mem:
            return system_prompt
        if not system_prompt:
            return f"你是 Lemon Code Agent。{mem}"
        return system_prompt.rstrip() + mem


# ============================================================
# 全局单例
# ============================================================

_global_memory: Optional[MemoryManager] = None
_memory_lock = threading.Lock()


def get_memory_manager() -> MemoryManager:
    """获取全局 MemoryManager 单例"""
    global _global_memory
    if _global_memory is None:
        with _memory_lock:
            if _global_memory is None:
                _global_memory = MemoryManager()
                _global_memory.ensure_exists()
    return _global_memory
