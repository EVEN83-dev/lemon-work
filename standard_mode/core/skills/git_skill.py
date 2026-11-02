# -*- coding: utf-8 -*-
"""
Skill: git_skill — Git 专用 Skill（v0.9.0 新增）
=================================================
封装 Git 操作为标准 Skill，支持 8 种核心操作：
  - status   查看仓库状态
  - diff     查看 diff（工作区/暂存区/commit 之间）
  - commit   提交（支持 message + 文件列表）
  - push     推送（危险操作，需确认）
  - pull     拉取
  - log      查看日志
  - branch   分支管理（list/create/switch/delete）
  - merge    合并分支（危险操作，需确认）
  - stash    暂存管理（save/pop/list/apply）

人性化设计：
  - push / merge / branch delete 默认 requires_confirm=True
  - 操作前通过 requires_confirm 字段触发 UI 确认对话框
  - 所有操作返回结构化 SkillResult，便于 UI 渲染
"""

import os
import subprocess
from typing import Dict, Any, List, Optional

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "git_skill",
    "description": "Git 专用 Skill：status/diff/commit/push/pull/log/branch/merge/stash 操作封装",
    "category": "vcs",
    "version": "1.0.0",
}


# ============================================================
# Git 命令执行器
# ============================================================

class GitExecutor:
    """Git 命令执行器 — 封装 subprocess 调用"""

    def __init__(self, cwd: str = ""):
        self.cwd = cwd or os.getcwd()

    def _run(self, args: List[str], timeout: int = 30) -> Dict[str, Any]:
        """执行 git 命令并返回结构化结果"""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Git 命令超时（{timeout}s）",
                "success": False,
            }
        except FileNotFoundError:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": "git 命令未找到，请确保已安装 Git",
                "success": False,
            }
        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
                "success": False,
            }

    def is_repo(self) -> bool:
        """检查当前目录是否为 Git 仓库"""
        r = self._run(["rev-parse", "--is-inside-work-tree"], timeout=5)
        return r["success"] and r["stdout"].strip() == "true"

    def get_current_branch(self) -> str:
        """获取当前分支名"""
        r = self._run(["branch", "--show-current"], timeout=5)
        if r["success"]:
            return r["stdout"].strip()
        return ""


# 全局执行器（按 cwd 缓存）
_executors: Dict[str, GitExecutor] = {}


def _get_executor(cwd: str = "") -> GitExecutor:
    cwd = cwd or os.getcwd()
    if cwd not in _executors:
        _executors[cwd] = GitExecutor(cwd)
    return _executors[cwd]


# ============================================================
# 操作实现
# ============================================================

def _op_status(porcelain: bool = True, cwd: str = "") -> SkillResult:
    """查看仓库状态"""
    exe = _get_executor(cwd)
    if not exe.is_repo():
        return SkillResult(success=False, error="当前目录不是 Git 仓库")
    args = ["status"]
    if porcelain:
        args.append("--porcelain")
    args.append("-sb" if porcelain else "-sb")
    r = exe._run(args, timeout=10)
    if not r["success"]:
        return SkillResult(success=False, error=r["stderr"])
    branch = exe.get_current_branch()
    files = []
    if porcelain:
        for line in r["stdout"].strip().split("\n"):
            if line.startswith("##"):
                continue
            if len(line) >= 3:
                status = line[:2]
                fname = line[3:]
                files.append({"status": status, "file": fname})
    return SkillResult(
        success=True,
        output=f"✅ 当前分支: {branch}\n变更文件: {len(files)} 个\n" + r["stdout"][:2000],
        data={"branch": branch, "files": files, "raw": r["stdout"]},
    )


def _op_diff(
    staged: bool = False,
    file_path: str = "",
    commit_a: str = "",
    commit_b: str = "",
    stat: bool = False,
    cwd: str = "",
) -> SkillResult:
    """查看 diff"""
    exe = _get_executor(cwd)
    if not exe.is_repo():
        return SkillResult(success=False, error="当前目录不是 Git 仓库")
    args = ["diff"]
    if staged:
        args.append("--cached")
    if stat:
        args.append("--stat")
    if commit_a and commit_b:
        args.extend([commit_a, commit_b])
    elif commit_a:
        args.append(commit_a)
    if file_path:
        args.extend(["--", file_path])
    r = exe._run(args, timeout=20)
    if not r["success"]:
        return SkillResult(success=False, error=r["stderr"])
    diff_text = r["stdout"]
    if not diff_text:
        return SkillResult(success=True, output="✅ 没有差异", data={"diff": "", "files_changed": 0})
    files_changed = diff_text.count("diff --git")
    return SkillResult(
        success=True,
        output=f"✅ Diff（{files_changed} 个文件变更）:\n{diff_text[:3000]}",
        data={"diff": diff_text, "files_changed": files_changed},
    )


def _op_commit(message: str, file_paths: str = "", amend: bool = False, cwd: str = "") -> SkillResult:
    """提交"""
    if not message:
        return SkillResult(success=False, error="commit 需要 message 参数")
    exe = _get_executor(cwd)
    if not exe.is_repo():
        return SkillResult(success=False, error="当前目录不是 Git 仓库")

    # 添加文件
    if file_paths:
        for fp in file_paths.split(","):
            fp = fp.strip()
            if fp:
                r = exe._run(["add", fp], timeout=10)
                if not r["success"]:
                    return SkillResult(success=False, error=f"git add 失败: {r['stderr']}")
    else:
        # 默认添加所有变更
        exe._run(["add", "-A"], timeout=10)

    args = ["commit", "-m", message]
    if amend:
        args.append("--amend")
    r = exe._run(args, timeout=15)
    if not r["success"]:
        return SkillResult(success=False, error=r["stderr"] or r["stdout"])
    return SkillResult(
        success=True,
        output=f"✅ 提交成功:\n{r['stdout']}",
        data={"message": message, "amend": amend, "output": r["stdout"]},
    )


def _op_push(remote: str = "origin", branch: str = "", force: bool = False, cwd: str = "") -> SkillResult:
    """推送（危险操作，handler 在 SkillDef 中标记 requires_confirm=True）"""
    exe = _get_executor(cwd)
    if not exe.is_repo():
        return SkillResult(success=False, error="当前目录不是 Git 仓库")
    if not branch:
        branch = exe.get_current_branch()
    args = ["push"]
    if force:
        args.append("--force-with-lease")
    args.extend([remote, branch])
    r = exe._run(args, timeout=60)
    if not r["success"]:
        return SkillResult(success=False, error=r["stderr"] or r["stdout"])
    return SkillResult(
        success=True,
        output=f"✅ 推送成功: {remote}/{branch}\n{r['stdout']}",
        data={"remote": remote, "branch": branch, "force": force},
    )


def _op_pull(remote: str = "origin", branch: str = "", cwd: str = "") -> SkillResult:
    """拉取"""
    exe = _get_executor(cwd)
    if not exe.is_repo():
        return SkillResult(success=False, error="当前目录不是 Git 仓库")
    if not branch:
        branch = exe.get_current_branch()
    args = ["pull", remote]
    if branch:
        args.append(branch)
    r = exe._run(args, timeout=60)
    if not r["success"]:
        return SkillResult(success=False, error=r["stderr"] or r["stdout"])
    return SkillResult(
        success=True,
        output=f"✅ 拉取成功: {remote}/{branch}\n{r['stdout']}",
        data={"remote": remote, "branch": branch},
    )


def _op_log(
    count: int = 20,
    oneline: bool = True,
    file_path: str = "",
    graph: bool = False,
    cwd: str = "",
) -> SkillResult:
    """查看日志"""
    exe = _get_executor(cwd)
    if not exe.is_repo():
        return SkillResult(success=False, error="当前目录不是 Git 仓库")
    args = ["log", f"-n{count}"]
    if oneline:
        args.append("--oneline")
    if graph:
        args.extend(["--graph", "--all", "--decorate"])
    if file_path:
        args.extend(["--", file_path])
    r = exe._run(args, timeout=15)
    if not r["success"]:
        return SkillResult(success=False, error=r["stderr"])
    return SkillResult(
        success=True,
        output=f"✅ 最近 {count} 条日志:\n{r['stdout']}",
        data={"log": r["stdout"], "count": count},
    )


def _op_branch(
    sub_action: str = "list",
    branch_name: str = "",
    cwd: str = "",
) -> SkillResult:
    """分支管理"""
    exe = _get_executor(cwd)
    if not exe.is_repo():
        return SkillResult(success=False, error="当前目录不是 Git 仓库")

    if sub_action == "list":
        r = exe._run(["branch", "-a"], timeout=10)
        if not r["success"]:
            return SkillResult(success=False, error=r["stderr"])
        branches = [
            {"name": b.strip().lstrip("* ").strip(), "current": b.strip().startswith("*")}
            for b in r["stdout"].strip().split("\n") if b.strip()
        ]
        return SkillResult(
            success=True,
            output=f"✅ 分支列表:\n{r['stdout']}",
            data={"branches": branches},
        )

    if sub_action == "create":
        if not branch_name:
            return SkillResult(success=False, error="create 需要 branch_name 参数")
        r = exe._run(["branch", branch_name], timeout=10)
        if not r["success"]:
            return SkillResult(success=False, error=r["stderr"])
        return SkillResult(success=True, output=f"✅ 已创建分支: {branch_name}")

    if sub_action == "switch":
        if not branch_name:
            return SkillResult(success=False, error="switch 需要 branch_name 参数")
        r = exe._run(["checkout", branch_name], timeout=15)
        if not r["success"]:
            return SkillResult(success=False, error=r["stderr"])
        return SkillResult(success=True, output=f"✅ 已切换到分支: {branch_name}")

    if sub_action == "delete":
        if not branch_name:
            return SkillResult(success=False, error="delete 需要 branch_name 参数")
        # 删除分支是危险操作，强制使用 -d（不是 -D）
        r = exe._run(["branch", "-d", branch_name], timeout=10)
        if not r["success"]:
            return SkillResult(success=False, error=r["stderr"])
        return SkillResult(success=True, output=f"✅ 已删除分支: {branch_name}")

    return SkillResult(success=False, error=f"未知 branch 子操作: {sub_action}")


def _op_merge(
    branch_name: str,
    no_ff: bool = False,
    message: str = "",
    cwd: str = "",
) -> SkillResult:
    """合并分支（危险操作）"""
    if not branch_name:
        return SkillResult(success=False, error="merge 需要 branch_name 参数")
    exe = _get_executor(cwd)
    if not exe.is_repo():
        return SkillResult(success=False, error="当前目录不是 Git 仓库")
    args = ["merge"]
    if no_ff:
        args.append("--no-ff")
    if message:
        args.extend(["-m", message])
    args.append(branch_name)
    r = exe._run(args, timeout=30)
    if not r["success"]:
        # 检测冲突
        conflict = "conflict" in r["stdout"].lower() or "conflict" in r["stderr"].lower()
        return SkillResult(
            success=False,
            error=f"合并失败{'（有冲突）' if conflict else ''}: {r['stderr'] or r['stdout']}",
            data={"conflict": conflict},
        )
    return SkillResult(
        success=True,
        output=f"✅ 已合并分支 {branch_name}\n{r['stdout']}",
        data={"branch": branch_name, "no_ff": no_ff},
    )


def _op_stash(
    sub_action: str = "list",
    message: str = "",
    stash_id: str = "",
    cwd: str = "",
) -> SkillResult:
    """暂存管理"""
    exe = _get_executor(cwd)
    if not exe.is_repo():
        return SkillResult(success=False, error="当前目录不是 Git 仓库")

    if sub_action == "list":
        r = exe._run(["stash", "list"], timeout=10)
        if not r["success"]:
            return SkillResult(success=False, error=r["stderr"])
        return SkillResult(
            success=True,
            output=f"✅ Stash 列表:\n{r['stdout'] or '(空)'}",
            data={"list": r["stdout"]},
        )

    if sub_action == "save":
        args = ["stash", "push"]
        if message:
            args.extend(["-m", message])
        r = exe._run(args, timeout=15)
        if not r["success"]:
            return SkillResult(success=False, error=r["stderr"])
        return SkillResult(success=True, output=f"✅ 已暂存: {r['stdout']}")

    if sub_action == "pop":
        args = ["stash", "pop"]
        if stash_id:
            args.append(stash_id)
        r = exe._run(args, timeout=15)
        if not r["success"]:
            return SkillResult(success=False, error=r["stderr"])
        return SkillResult(success=True, output=f"✅ 已恢复并删除 stash: {r['stdout']}")

    if sub_action == "apply":
        args = ["stash", "apply"]
        if stash_id:
            args.append(stash_id)
        r = exe._run(args, timeout=15)
        if not r["success"]:
            return SkillResult(success=False, error=r["stderr"])
        return SkillResult(success=True, output=f"✅ 已恢复 stash（保留）: {r['stdout']}")

    return SkillResult(success=False, error=f"未知 stash 子操作: {sub_action}")


# ============================================================
# 统一入口
# ============================================================

def execute(
    action: str = "status",
    message: str = "",
    file_path: str = "",
    file_paths: str = "",
    branch_name: str = "",
    remote: str = "origin",
    commit_a: str = "",
    commit_b: str = "",
    count: int = 20,
    staged: bool = False,
    stat: bool = False,
    oneline: bool = True,
    graph: bool = False,
    force: bool = False,
    amend: bool = False,
    no_ff: bool = False,
    porcelain: bool = True,
    sub_action: str = "list",
    stash_id: str = "",
    cwd: str = "",
) -> SkillResult:
    """Git Skill 统一入口

    Args:
        action: 操作类型 status/diff/commit/push/pull/log/branch/merge/stash
        message: commit/merge/stash 的消息
        file_path: 单文件路径（diff/log 使用）
        file_paths: 逗号分隔的文件列表（commit 使用）
        branch_name: 分支名（branch/merge 使用）
        remote: 远程仓库名（push/pull 使用，默认 origin）
        commit_a, commit_b: diff 的 commit 范围
        count: log 条数
        staged: diff 是否查看暂存区
        stat: diff 是否只看统计
        oneline: log 是否单行显示
        graph: log 是否显示图形
        force: push 是否强制（--force-with-lease）
        amend: commit 是否修订
        no_ff: merge 是否禁用快进
        porcelain: status 是否用 porcelain 格式
        sub_action: branch/stash 的子操作
        stash_id: stash 的 ID
        cwd: 工作目录（默认当前目录）
    """
    action = (action or "").lower().strip()

    if action == "status":
        return _op_status(porcelain=porcelain, cwd=cwd)
    if action == "diff":
        return _op_diff(staged=staged, file_path=file_path, commit_a=commit_a, commit_b=commit_b, stat=stat, cwd=cwd)
    if action == "commit":
        return _op_commit(message=message, file_paths=file_paths, amend=amend, cwd=cwd)
    if action == "push":
        return _op_push(remote=remote, branch=branch_name, force=force, cwd=cwd)
    if action == "pull":
        return _op_pull(remote=remote, branch=branch_name, cwd=cwd)
    if action == "log":
        return _op_log(count=count, oneline=oneline, file_path=file_path, graph=graph, cwd=cwd)
    if action == "branch":
        return _op_branch(sub_action=sub_action, branch_name=branch_name, cwd=cwd)
    if action == "merge":
        return _op_merge(branch_name=branch_name, no_ff=no_ff, message=message, cwd=cwd)
    if action == "stash":
        return _op_stash(sub_action=sub_action, message=message, stash_id=stash_id, cwd=cwd)

    return SkillResult(
        success=False,
        error=f"未知 action: {action}（支持: status/diff/commit/push/pull/log/branch/merge/stash）",
    )


def register(registry) -> None:
    """向 SkillsRegistry 注册 git_skill"""
    # 主入口（默认 requires_confirm=False，由 UI 层根据 action 判断是否需要确认）
    registry.register(SkillDef(
        name="git_skill",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Git 操作类型",
                    "enum": ["status", "diff", "commit", "push", "pull", "log", "branch", "merge", "stash"],
                },
                "message": {"type": "string", "description": "commit/merge/stash 的消息"},
                "file_path": {"type": "string", "description": "单文件路径（diff/log 使用）"},
                "file_paths": {"type": "string", "description": "逗号分隔的文件列表（commit 使用）"},
                "branch_name": {"type": "string", "description": "分支名（branch/merge/push/pull 使用）"},
                "remote": {"type": "string", "description": "远程仓库名", "default": "origin"},
                "commit_a": {"type": "string", "description": "diff 的起始 commit"},
                "commit_b": {"type": "string", "description": "diff 的结束 commit"},
                "count": {"type": "integer", "description": "log 条数", "default": 20},
                "staged": {"type": "boolean", "description": "diff 是否查看暂存区", "default": False},
                "stat": {"type": "boolean", "description": "diff 是否只看统计", "default": False},
                "oneline": {"type": "boolean", "description": "log 是否单行", "default": True},
                "graph": {"type": "boolean", "description": "log 是否显示图形", "default": False},
                "force": {"type": "boolean", "description": "push 是否强制（--force-with-lease）", "default": False},
                "amend": {"type": "boolean", "description": "commit 是否修订", "default": False},
                "no_ff": {"type": "boolean", "description": "merge 是否禁用快进", "default": False},
                "porcelain": {"type": "boolean", "description": "status 是否用 porcelain 格式", "default": True},
                "sub_action": {
                    "type": "string",
                    "description": "branch/stash 的子操作",
                    "enum": ["list", "create", "switch", "delete", "save", "pop", "apply"],
                },
                "stash_id": {"type": "string", "description": "stash 的 ID（如 stash@{0}）"},
                "cwd": {"type": "string", "description": "工作目录（默认当前目录）"},
            },
            "required": ["action"],
        },
        handler=execute,
        category=METADATA["category"],
        # ★ push/merge/branch delete 是危险操作 — UI 层通过 is_dangerous_action() 判断
        requires_confirm=False,
        timeout=60,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA


def is_dangerous_action(action: str, sub_action: str = "") -> bool:
    """判断是否为危险操作（UI 层调用以决定是否弹出确认对话框）"""
    if action in ("push", "merge"):
        return True
    if action == "branch" and sub_action == "delete":
        return True
    if action == "stash" and sub_action == "pop":
        return True
    return False
