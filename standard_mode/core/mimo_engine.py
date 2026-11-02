# -*- coding: utf-8 -*-
"""
MIMO Code 后端引擎
- 项目文件扫描与管理
- 代码变更分析与 Diff 生成
- Agent 任务编排（模拟 MiMo Auto 驱动）
"""

import os
import re
import difflib
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from pathlib import Path


@dataclass
class FileChange:
    """单次文件变更记录"""
    path: str
    old_lines: List[str] = field(default_factory=list)
    new_lines: List[str] = field(default_factory=list)
    status: str = "modified"  # added / removed / modified
    description: str = ""

    @property
    def added_count(self) -> int:
        return len([l for l in self.new_lines if l.strip()])

    @property
    def removed_count(self) -> int:
        return len([l for l in self.old_lines if l.strip()])

    @property
    def diff_lines(self) -> List[tuple]:
        """返回 (status, line) 列表，status: same/add/remove"""
        diff = list(difflib.ndiff(self.old_lines, self.new_lines))
        result = []
        for line in diff:
            if line.startswith("+ "):
                result.append(("add", line[2:]))
            elif line.startswith("- "):
                result.append(("remove", line[2:]))
            elif line.startswith("? "):
                continue
            else:
                result.append(("same", line[2:]))
        return result


class MIMOEngine:
    """
    MIMO Code Agent 核心引擎。
    负责项目文件管理、模拟 AI 代码生成、变更追踪与任务执行。
    """

    def __init__(self, project_path: str = None):
        self.project_path = project_path or os.getcwd()
        self.files: Dict[str, str] = {}
        self.changes: Dict[str, FileChange] = {}
        self.task_log: List[str] = []
        self._observers: List[Callable] = []

    def register_observer(self, callback: Callable):
        self._observers.append(callback)

    def _notify(self, event: str, data: dict):
        for cb in self._observers:
            cb(event, data)

    def scan_project(self, path: str = None) -> Dict[str, str]:
        """扫描项目目录，返回相对路径 -> 绝对路径 映射"""
        base = path or self.project_path
        self.project_path = os.path.abspath(base)
        self.files = {}
        ignore = {".git", "__pycache__", ".venv", "venv", "node_modules", ".idea", ".vscode"}

        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in ignore]
            for f in files:
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(abs_path, self.project_path)
                self.files[rel_path] = abs_path

        self._notify("project_scanned", {"path": self.project_path, "count": len(self.files)})
        return self.files

    def read_file(self, rel_path: str) -> str:
        abs_path = self.files.get(rel_path)
        if not abs_path or not os.path.exists(abs_path):
            return ""
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def write_file(self, rel_path: str, content: str):
        abs_path = self.files.get(rel_path)
        if not abs_path:
            abs_path = os.path.join(self.project_path, rel_path)
            self.files[rel_path] = abs_path
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        self._notify("file_written", {"path": rel_path})

    # ------------------------------------------------------------------
    # Agent 能力（MiMo Auto 模拟）
    # ------------------------------------------------------------------

    def analyze_task(self, command: str) -> str:
        """解析用户命令，返回任务计划"""
        cmd = command.strip().lower()
        if "修复" in command or "fix" in cmd or "bug" in cmd:
            return "计划：扫描项目 -> 定位潜在问题 -> 生成修复补丁 -> 应用变更"
        elif "优化" in command or "refactor" in cmd or "improve" in cmd:
            return "计划：分析代码结构 -> 重构重复逻辑 -> 应用优化变更"
        elif "添加" in command or "add" in cmd or "新建" in cmd:
            return "计划：创建新文件/函数 -> 写入代码 -> 验证语法"
        return "计划：理解需求 -> 分析相关文件 -> 生成代码变更 -> 验证结果"

    def execute_agent_task(self, command: str) -> List[FileChange]:
        """执行一次 Agent 任务，生成若干文件变更"""
        self.task_log.append(f"> {command}")
        plan = self.analyze_task(command)
        self.task_log.append(plan)

        changes = []
        cmd = command.strip().lower()

        if "修复" in command or "fix" in cmd or "bug" in cmd:
            changes = self._generate_fix_changes()
        elif "优化" in command or "refactor" in cmd or "improve" in cmd:
            changes = self._generate_refactor_changes()
        elif "添加" in command or "add" in cmd or "新建" in cmd:
            changes = self._generate_add_changes(command)
        else:
            changes = self._generate_default_changes(command)

        for ch in changes:
            self.changes[ch.path] = ch
            self.task_log.append(f"变更文件: {ch.path} [{ch.status}] +{ch.added_count}/-{ch.removed_count}")

        self._notify("task_completed", {"command": command, "changes": len(changes)})
        return changes

    def _get_python_files(self) -> List[str]:
        return [p for p in self.files if p.endswith(".py")]

    def _generate_fix_changes(self) -> List[FileChange]:
        """模拟修复：为第一个 .py 文件添加 try/except 或修正 import"""
        py_files = self._get_python_files()
        if not py_files:
            return []

        target = py_files[0]
        old = self.read_file(target)
        old_lines = old.splitlines() if old else []
        new_lines = list(old_lines)

        # 简单规则：在文件顶部添加编码声明或修正 import
        if old_lines and not old_lines[0].startswith("# -*- coding"):
            new_lines.insert(0, "# -*- coding: utf-8 -*-")
            desc = "添加 UTF-8 编码声明，避免中文注释乱码"
        else:
            # 给 main 函数加 try/except
            new_lines.append("")
            new_lines.append("# MIMO Auto: 增加运行保护")
            new_lines.append("try:")
            new_lines.append("    main()")
            new_lines.append("except Exception as e:")
            new_lines.append('    print(f"运行错误: {e}")')
            desc = "为入口函数增加异常保护"

        change = FileChange(
            path=target,
            old_lines=old_lines,
            new_lines=new_lines,
            status="modified",
            description=desc,
        )
        return [change]

    def _generate_refactor_changes(self) -> List[FileChange]:
        py_files = self._get_python_files()
        if not py_files:
            return []

        changes = []
        for target in py_files[:2]:
            old = self.read_file(target)
            old_lines = old.splitlines() if old else []
            new_lines = []
            for line in old_lines:
                # 简单重构：去除行尾空格
                new_lines.append(line.rstrip())
            if new_lines != old_lines:
                changes.append(FileChange(
                    path=target,
                    old_lines=old_lines,
                    new_lines=new_lines,
                    status="modified",
                    description="移除行尾空白，统一代码格式",
                ))
        return changes

    def _generate_add_changes(self, command: str) -> List[FileChange]:
        # 解析命令中的文件名
        match = re.search(r"([\w\-_]+\.py)", command)
        file_name = match.group(1) if match else "mimo_generated.py"
        new_path = os.path.join("generated", file_name)
        rel_path = os.path.relpath(os.path.join(self.project_path, new_path), self.project_path)

        code = f'''# -*- coding: utf-8 -*-
"""
由 MIMO Code Agent 自动生成
命令: {command}
"""


def generated_feature():
    """MIMO Auto 生成的功能示例"""
    print("MIMO Code Agent is working!")
    return True


if __name__ == "__main__":
    generated_feature()
'''
        change = FileChange(
            path=rel_path,
            old_lines=[],
            new_lines=code.splitlines(),
            status="added",
            description=f"根据命令创建新文件 {rel_path}",
        )
        return [change]

    def _generate_default_changes(self, command: str) -> List[FileChange]:
        # 默认也做一点格式整理
        return self._generate_refactor_changes()

    def apply_change(self, rel_path: str) -> bool:
        """应用单个变更到磁盘"""
        change = self.changes.get(rel_path)
        if not change:
            return False
        content = "\n".join(change.new_lines)
        self.write_file(rel_path, content)
        change.status = "applied"
        self._notify("change_applied", {"path": rel_path})
        return True

    def apply_all_changes(self) -> int:
        count = 0
        for rel_path in list(self.changes.keys()):
            if self.apply_change(rel_path):
                count += 1
        return count

    def discard_change(self, rel_path: str):
        if rel_path in self.changes:
            del self.changes[rel_path]
            self._notify("change_discarded", {"path": rel_path})

    def get_changes_summary(self) -> Dict:
        total = len(self.changes)
        added = sum(1 for c in self.changes.values() if c.status == "added")
        removed = sum(1 for c in self.changes.values() if c.status == "removed")
        modified = total - added - removed
        add_lines = sum(c.added_count for c in self.changes.values())
        rem_lines = sum(c.removed_count for c in self.changes.values())
        return {
            "total": total,
            "added": added,
            "removed": removed,
            "modified": modified,
            "add_lines": add_lines,
            "rem_lines": rem_lines,
        }

    def run_syntax_check(self, rel_path: str) -> str:
        """简单语法检查"""
        import py_compile
        abs_path = self.files.get(rel_path)
        if not abs_path or not os.path.exists(abs_path):
            return "文件不存在"
        try:
            py_compile.compile(abs_path, doraise=True)
            return "语法检查通过"
        except py_compile.PyCompileError as e:
            return f"语法错误: {e}"
