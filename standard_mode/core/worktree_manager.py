# -*- coding: utf-8 -*-
"""
Worktree 管理器 — Git Worktree 隔离（安全跑 Agent）
=====================================================
蒸馏自 MiMo-Code opencode 的 worktree 隔离理念（spawn.ts 中 cwd 绑定 +
git worktree 隔离），用 Python subprocess 实现。

核心能力：
1. create()     - 创建隔离 worktree + 新分支（Agent 在独立工作区改代码，不动主工作区）
2. list()       - 列出全部 worktree
3. status()     - 查看某个 worktree 的 diff/未提交变更
4. remove()     - 清理 worktree（可带 --force，丢弃其变更）
5. merge_back() - 将 worktree 的提交合并回主分支

设计要点（对齐 MiMo-Code）：
- worktree 是一个"目录"—— ActorSystem.spawn 的 cwd 参数可直接绑定它，
  子 Agent 的所有文件工具都解析到该目录，实现真正的写入隔离。
- 主工作区零污染：Agent 在 worktree 分支上工作，主分支完全不受影响。
- 快照（snapshot_manager）仍作用于主工作区；worktree 内可用 git commit
  作为更精细的快照点。
"""
import os
import subprocess
import time
from typing import Dict, List, Optional, Tuple


class WorktreeManager:
    """Git Worktree 管理器 — 隔离分支跑 Agent"""

    def __init__(self, project_path: str):
        self.project_path = os.path.abspath(project_path)

    # ==================== 工具方法 ====================

    def _run(self, args: List[str], cwd: str = None, timeout: int = 15) -> Tuple[bool, str]:
        """执行 git 命令，返回 (成功?, 输出)"""
        try:
            result = subprocess.run(
                ['git'] + args,
                cwd=cwd or self.project_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8',
                errors='replace'
            )
            output = (result.stdout or "") + (result.stderr or "")
            return result.returncode == 0, output.strip()
        except FileNotFoundError:
            return False, "git 命令不存在（未安装 Git？）"
        except subprocess.TimeoutExpired:
            return False, f"git 命令超时: {' '.join(args)}"
        except Exception as e:
            return False, str(e)

    def is_git_repo(self) -> bool:
        """是否是 Git 仓库（含 worktree 场景）"""
        ok, _ = self._run(['rev-parse', '--is-inside-work-tree'])
        return ok

    def current_branch(self) -> str:
        ok, out = self._run(['branch', '--show-current'])
        return out if ok else ""

    def commit_head(self) -> str:
        ok, out = self._run(['rev-parse', 'HEAD'])
        return out[:12] if ok else ""

    # ==================== Worktree 操作 ====================

    def create(self, name: str, base_branch: str = None, path: str = None) -> Tuple[bool, str]:
        """创建隔离 worktree + 新分支

        name:       分支名（如 "lemon-agent-sandbox"）
        base_branch: 从哪个分支拉出（默认当前分支）
        path:       worktree 目录（默认 <project>/.worktrees/<name>）

        返回 (成功?, worktree_path)
        """
        if not self.is_git_repo():
            return False, "不是 Git 仓库"

        branch = f"{name}"
        # 分支名防冲突：若已存在则加时间戳后缀
        ok, out = self._run(['rev-parse', '--verify', f'refs/heads/{branch}'])
        if ok:
            branch = f"{name}-{int(time.time()) % 10000}"

        base = base_branch or self.current_branch() or "HEAD"
        if not path:
            path = os.path.join(self.project_path, ".worktrees", branch)

        # git worktree add -b <branch> <path> <base>
        ok, out = self._run(['worktree', 'add', '-b', branch, path, base], timeout=30)
        if not ok:
            return False, f"创建 worktree 失败: {out}"
        return True, path

    def list(self) -> List[Dict]:
        """列出全部 worktree"""
        ok, out = self._run(['worktree', 'list', '--porcelain'])
        if not ok:
            return []
        worktrees = []
        current = {}
        for line in out.split('\n'):
            if line == 'worktree':
                if current:
                    worktrees.append(current)
                    current = {}
            elif line.startswith('worktree '):
                current = {"path": line[len('worktree '):].strip()}
            elif line.startswith('HEAD '):
                current["head"] = line[len('HEAD '):].strip()[:12]
            elif line.startswith('branch '):
                current["branch"] = line[len('branch '):].strip().replace('refs/heads/', '')
            elif line.startswith('detached'):
                current["detached"] = True
        if current:
            worktrees.append(current)
        return worktrees

    def status(self, path: str) -> Dict:
        """查看 worktree 的变更状态"""
        data = {"path": path, "branch": "", "head": "", "changes": "", "commits": 0, "clean": True}
        ok, out = self._run(['branch', '--show-current'], cwd=path)
        data["branch"] = out if ok else ""
        ok, out = self._run(['rev-parse', 'HEAD'], cwd=path)
        data["head"] = out[:12] if ok else ""
        ok, out = self._run(['status', '--porcelain'], cwd=path)
        data["changes"] = out
        data["clean"] = (out.strip() == "")
        ok, out = self._run(['rev-list', '--count', 'HEAD', f'^@{"{upstream}"}'], cwd=path)
        return data

    def diff(self, path: str) -> str:
        """获取 worktree 的未提交 diff"""
        ok, out = self._run(['diff', 'HEAD'], cwd=path)
        return out if ok else ""

    def remove(self, path: str, force: bool = False) -> Tuple[bool, str]:
        """清理 worktree（force=True 丢弃其所有未提交/未推送变更）"""
        args = ['worktree', 'remove']
        if force:
            args.append('--force')
        args.append(path)
        ok, out = self._run(args, timeout=30)
        if not ok:
            return False, f"删除 worktree 失败: {out}"
        # 删除残留分支（可选；被 check out 时 git 会拒绝）
        return True, "worktree 已清理"

    def merge_back(self, path: str, commit_message: str = None) -> Tuple[bool, str]:
        """把 worktree 的变更合并回主分支

        策略：先确保 worktree 已提交 → 切回主工作区 → merge worktree 分支
        """
        if not self.is_git_repo():
            return False, "不是 Git 仓库"

        branch = ""
        ok, out = self._run(['branch', '--show-current'], cwd=path)
        branch = out if ok else ""
        if not branch:
            return False, "worktree 不在分支上（detached），无法合并"

        # 1. 检查 worktree 是否有未提交变更
        ok, out = self._run(['status', '--porcelain'], cwd=path)
        if out.strip():
            return False, "worktree 有未提交变更，请先在 worktree 内 commit 后再合并"

        # 2. 切回主工作区（如果当前在 worktree 里则需要先切走）
        # 3. 从主工作区 merge worktree 分支
        ok, out = self._run(['merge', '--no-edit', branch], timeout=30)
        if not ok:
            return False, f"合并失败: {out}"
        return True, f"已合并分支 {branch} → 主分支"

    # ==================== Agent 场景助手 ====================

    def create_for_agent(self, task_desc: str) -> Tuple[bool, Dict]:
        """为一次 Agent 任务创建隔离环境

        返回 (成功?, {path, branch, base})
        """
        import re
        # 从任务描述生成分支名（安全化）
        safe = re.sub(r'[^a-zA-Z0-9_\-\u4e00-\u9fff]', '-', task_desc.strip())[:30] or "agent-task"
        branch = f"agent-{safe}"
        ok, path = self.create(branch)
        if not ok:
            return False, {"error": path}
        return True, {"path": path, "branch": branch, "base": self.current_branch()}
