# -*- coding: utf-8 -*-
"""
Git 管理器 — 文件状态查询 + 快捷操作
为左侧资源管理器提供 Git 状态图标支持
"""
import os
import subprocess
from typing import Dict, Optional, List, Tuple


class GitManager:
    """Git 仓库管理器 — 轻量级 Git 操作封装"""

    def __init__(self, project_path: str):
        self.project_path = project_path
        self._git_dir = self._find_git_dir(project_path)
        self._status_cache: Dict[str, str] = {}
        self._branch = ""

    @property
    def is_git_repo(self) -> bool:
        return self._git_dir is not None

    @property
    def branch(self) -> str:
        return self._branch

    def _find_git_dir(self, path: str) -> Optional[str]:
        """查找 .git 目录"""
        current = os.path.abspath(path)
        while current:
            git_path = os.path.join(current, '.git')
            if os.path.isdir(git_path):
                return git_path
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return None

    def refresh_status(self) -> Dict[str, str]:
        """刷新 Git 状态 — 返回 {文件路径: 状态码}"""
        if not self.is_git_repo:
            self._status_cache = {}
            return {}

        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode != 0:
                self._status_cache = {}
                return {}

            self._status_cache = {}
            for line in result.stdout.split('\n'):
                if not line.strip():
                    continue
                # 格式: XY filename (X=暂存区状态, Y=工作区状态)
                # 注意: 不能对整个输出 strip(), 否则会去掉未暂存修改行的前导空格,
                # 导致 " M file.py" 变成 "M file.py" 从而 line[3:] 错位成 ".py"
                if len(line) >= 3:
                    status = line[:2].strip()
                    filename = line[3:].strip()
                    # 处理重命名: R old -> new
                    if ' -> ' in filename:
                        filename = filename.split(' -> ')[-1]
                    # 处理含空格/特殊字符文件名被 git 引号包裹的情况: "my file.py"
                    if len(filename) >= 2 and filename[0] == '"' and filename[-1] == '"':
                        filename = filename[1:-1].replace('\\"', '"').replace('\\\\', '\\')
                    self._status_cache[filename] = status

            # 获取当前分支
            branch_result = subprocess.run(
                ['git', 'branch', '--show-current'],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=5,
                encoding='utf-8',
                errors='replace'
            )
            self._branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

            return self._status_cache

        except Exception:
            self._status_cache = {}
            return {}

    def get_file_status(self, rel_path: str) -> str:
        """获取单个文件状态 — M/A/D/??/'' (空=未修改)"""
        return self._status_cache.get(rel_path, '')

    def get_status_icon(self, rel_path: str) -> str:
        """获取 Git 状态图标"""
        s = self.get_file_status(rel_path)
        if not s:
            return ''
        if s == 'M' or 'M' in s:
            return '✎'  # 修改
        if s == 'A' or 'A' in s:
            return '＋'  # 新增
        if s == 'D' or 'D' in s:
            return '✕'  # 删除
        if s == 'R' or 'R' in s:
            return '↻'  # 重命名
        if s == '??':
            return '●'  # 未跟踪
        if s == 'UU':
            return '‼'  # 冲突
        return '•'  # 其他

    def get_status_color(self, rel_path: str) -> str:
        """获取 Git 状态颜色"""
        s = self.get_file_status(rel_path)
        if not s:
            return ''
        if 'M' in s:
            return '#ffab40'  # 橙色-修改
        if 'A' in s:
            return 'Lemon.STATUS_ONLINE'  # 绿色-新增
        if 'D' in s:
            return 'Lemon.ACCENT_RED'  # 红色-删除
        if 'R' in s:
            return 'Lemon.SYNTAX_FUNCTION'  # 蓝色-重命名
        if s == '??':
            return 'Lemon.STATUS_OFFLINE'  # 灰色-未跟踪
        if 'U' in s:
            return 'Lemon.ACCENT_RED'  # 红色-冲突
        return 'Lemon.STATUS_OFFLINE'

    # ================================================================
    # Git 快捷操作
    # ================================================================

    def get_diff(self, staged: bool = False) -> str:
        """获取 git diff"""
        if not self.is_git_repo:
            return ""
        try:
            args = ['git', 'diff']
            if staged:
                args.append('--staged')
            result = subprocess.run(
                args,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace'
            )
            return result.stdout if result.returncode == 0 else ""
        except Exception:
            return ""

    def get_log(self, count: int = 10) -> str:
        """获取最近提交日志"""
        if not self.is_git_repo:
            return ""
        try:
            result = subprocess.run(
                ['git', 'log', f'-{count}', '--oneline', '--decorate'],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace'
            )
            return result.stdout if result.returncode == 0 else ""
        except Exception:
            return ""

    def get_file_at_head(self, rel_path: str) -> Optional[str]:
        """获取文件在 HEAD 版本的内容（用于对比）"""
        if not self.is_git_repo:
            return None
        try:
            result = subprocess.run(
                ['git', 'show', f'HEAD:{rel_path}'],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode == 0:
                return result.stdout
            return None
        except Exception:
            return None

    def stage_file(self, rel_path: str) -> Tuple[bool, str]:
        """git add 单个文件"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        try:
            result = subprocess.run(
                ['git', 'add', rel_path],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace'
            )
            return result.returncode == 0, result.stderr.strip()
        except Exception as e:
            return False, str(e)

    def unstage_file(self, rel_path: str) -> Tuple[bool, str]:
        """git reset 单个文件"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        try:
            result = subprocess.run(
                ['git', 'reset', 'HEAD', '--', rel_path],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace'
            )
            return result.returncode == 0, result.stderr.strip()
        except Exception as e:
            return False, str(e)

    def commit(self, message: str) -> Tuple[bool, str]:
        """git commit"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        try:
            result = subprocess.run(
                ['git', 'commit', '-m', message],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode == 0:
                # 更新分支信息
                self.refresh_status()
                return True, result.stdout.strip() or "提交成功"
            return False, result.stderr.strip() or "提交失败"
        except Exception as e:
            return False, str(e)

    def commit_all(self, message: str) -> bool:
        """暂存所有变更并提交（侧面板使用）"""
        if not self.is_git_repo:
            return False
        try:
            # 先暂存所有变更
            add_result = subprocess.run(
                ['git', 'add', '.'],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace'
            )
            if add_result.returncode != 0:
                return False
            # 再提交
            commit_result = subprocess.run(
                ['git', 'commit', '-m', message],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            if commit_result.returncode == 0:
                # 更新分支信息
                self.refresh_status()
                return True
            return False
        except Exception:
            return False

    def push(self) -> Tuple[bool, str]:
        """git push（当前分支；无上游时自动 -u 建立跟踪）"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        if not self._branch:
            return False, "无法获取当前分支"
        try:
            # 检测是否已有上游
            upstream = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', self._branch + '@{upstream}'],
                cwd=self.project_path, capture_output=True, text=True,
                timeout=10, encoding='utf-8', errors='replace'
            )
            cmd = ['git', 'push', 'origin', self._branch]
            if upstream.returncode != 0:
                cmd = ['git', 'push', '-u', 'origin', self._branch]
            result = subprocess.run(
                cmd, cwd=self.project_path, capture_output=True, text=True,
                timeout=60, encoding='utf-8', errors='replace'
            )
            if result.returncode == 0:
                return True, result.stdout.strip() or "推送成功"
            return False, result.stderr.strip() or "推送失败"
        except Exception as e:
            return False, str(e)

    def pull(self) -> Tuple[bool, str]:
        """git pull（合并）"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        try:
            result = subprocess.run(
                ['git', 'pull'],
                cwd=self.project_path, capture_output=True, text=True,
                timeout=60, encoding='utf-8', errors='replace'
            )
            if result.returncode == 0:
                return True, result.stdout.strip() or "拉取成功"
            # 检测冲突
            err = result.stderr.strip() or result.stdout.strip()
            if 'conflict' in err.lower() or 'CONFLICT' in err:
                return False, f"拉取冲突: {err[:200]}"
            return False, err
        except Exception as e:
            return False, str(e)

    def get_summary(self) -> Dict:
        """获取 Git 仓库摘要信息"""
        if not self.is_git_repo:
            return {'is_repo': False}
        summary = {
            'is_repo': True,
            'branch': self._branch,
            'modified': 0,
            'added': 0,
            'deleted': 0,
            'untracked': 0,
            'conflicts': 0,
            'total_changes': 0,
        }
        for status in self._status_cache.values():
            if 'M' in status:
                summary['modified'] += 1
            if 'A' in status:
                summary['added'] += 1
            if 'D' in status:
                summary['deleted'] += 1
            if status == '??':
                summary['untracked'] += 1
            if 'U' in status:
                summary['conflicts'] += 1
        summary['total_changes'] = len(self._status_cache)
        return summary

    def stash(self, message: str = "", include_untracked: bool = False) -> Tuple[bool, str]:
        """暂存工作区变更（git stash）

        include_untracked=True 时使用 -u，将未追踪文件一并暂存
        """
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        try:
            cmd = ['git', 'stash', 'push']
            if include_untracked:
                cmd += ['-u']
            if message:
                cmd += ['-m', message]
            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode == 0:
                return True, result.stdout.strip() or "已暂存工作区"
            return False, result.stderr.strip() or "暂存失败"
        except Exception as e:
            return False, str(e)

    def stash_pop(self) -> Tuple[bool, str]:
        """恢复最近一次暂存（git stash pop）"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        try:
            result = subprocess.run(
                ['git', 'stash', 'pop'],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode == 0:
                return True, "已恢复暂存内容"
            return False, result.stderr.strip() or "恢复失败"
        except Exception as e:
            return False, str(e)

    def stash_list(self) -> List[str]:
        """列出 stash 列表"""
        if not self.is_git_repo:
            return []
        try:
            result = subprocess.run(
                ['git', 'stash', 'list'],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode != 0:
                return []
            return [l.strip() for l in result.stdout.splitlines() if l.strip()]
        except Exception:
            return []

    @staticmethod
    def _stash_ref(stash_line: str) -> str:
        """从 stash 列表项解析出 stash 引用 id（如 stash@{1}）"""
        if not stash_line:
            return ""
        token = stash_line.split(":", 1)[0].strip()
        return token if token.startswith("stash@") else ""

    def stash_apply(self, stash_ref: str = "stash@{0}") -> Tuple[bool, str]:
        """应用指定 stash（git stash apply，不删除）；检测冲突"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        try:
            result = subprocess.run(
                ['git', 'stash', 'apply', stash_ref],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode == 0:
                return True, f"已应用 {stash_ref}"
            err = result.stderr.strip() or result.stdout.strip() or f"应用 {stash_ref} 失败"
            # 冲突检测（git 冲突时 returncode 可能仍为 0，但输出 CONFLICT）
            if 'CONFLICT' in err.upper() or 'conflict' in err.lower():
                return False, f"检测到冲突，请手动解决: {err[:200]}"
            return False, err
        except Exception as e:
            return False, str(e)

    def stash_drop(self, stash_ref: str = "stash@{0}") -> Tuple[bool, str]:
        """丢弃指定 stash（git stash drop）"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        try:
            result = subprocess.run(
                ['git', 'stash', 'drop', stash_ref],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode == 0:
                return True, f"已丢弃 {stash_ref}"
            return False, result.stderr.strip() or f"丢弃 {stash_ref} 失败"
        except Exception as e:
            return False, str(e)

    def blame(self, rel_path: str) -> str:
        """获取文件每行归属（git blame）"""
        if not self.is_git_repo:
            return ""
        try:
            result = subprocess.run(
                ['git', 'blame', rel_path],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            return result.stdout if result.returncode == 0 else result.stderr
        except Exception:
            return ""

    def list_branches(self) -> List[str]:
        """列出所有本地分支"""
        if not self.is_git_repo:
            return []
        try:
            result = subprocess.run(
                ['git', 'branch', '--format=%(refname:short)'],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode != 0:
                return []
            branches = [b.strip() for b in result.stdout.splitlines() if b.strip()]
            # 当前分支放前面
            if self._branch and self._branch in branches:
                branches.remove(self._branch)
                branches.insert(0, self._branch)
            return branches
        except Exception:
            return []

    def create_branch(self, name: str) -> Tuple[bool, str]:
        """创建新分支"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        try:
            result = subprocess.run(
                ['git', 'checkout', '-b', name],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode == 0:
                self._branch = name
                return True, f"已创建并切换到分支: {name}"
            return False, result.stderr.strip() or "创建失败"
        except Exception as e:
            return False, str(e)

    def checkout_branch(self, name: str) -> Tuple[bool, str]:
        """切换分支"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        try:
            result = subprocess.run(
                ['git', 'checkout', name],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode == 0:
                self._branch = name
                return True, f"已切换到分支: {name}"
            return False, result.stderr.strip() or "切换失败"
        except Exception as e:
            return False, str(e)

    def delete_branch(self, name: str) -> Tuple[bool, str]:
        """删除分支（非当前分支）"""
        if not self.is_git_repo:
            return False, "不是 Git 仓库"
        if name == self._branch:
            return False, "不能删除当前分支"
        try:
            result = subprocess.run(
                ['git', 'branch', '-D', name],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode == 0:
                return True, f"已删除分支: {name}"
            return False, result.stderr.strip() or "删除失败"
        except Exception as e:
            return False, str(e)