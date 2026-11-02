# -*- coding: utf-8 -*-
"""
快照管理器 — Agent 代码修改自动快照 + 一键回退
=================================================
核心能力：
- 在 Agent 每次文件修改前后自动创建快照（git commit 或文件备份）
- 提供快照列表、diff 对比、一键回退功能
- 支持 Git 仓库和非 Git 仓库两种模式

架构：
┌─────────────────────────────────────────────┐
│           SnapshotManager                    │
│  ┌─────────────────────────────────────┐    │
│  │  Git 模式（优先）                    │    │
│  │  - create: git add -A && git commit │    │
│  │  - restore: git reset --hard        │    │
│  │  - diff: git diff                   │    │
│  └─────────────────────────────────────┘    │
│  ┌─────────────────────────────────────┐    │
│  │  文件备份模式（降级）                 │    │
│  │  - create: 复制到 .mimo_snapshots/   │    │
│  │  - restore: 复制回来                  │    │
│  │  - diff: 逐行对比                    │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
"""

import os
import sys
import shutil
import subprocess
import time
import json
from typing import Dict, Optional, List, Tuple
from datetime import datetime

# 同目录导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from git_manager import GitManager


class SnapshotManager:
    """Agent 代码修改快照管理器 — 自动快照 + 一键回退"""

    # 快照元数据文件
    META_FILE = ".mimo_snapshots_meta.json"

    def __init__(self, project_path: str):
        self.project_path = os.path.abspath(project_path)
        self._git = GitManager(self.project_path)
        self._snapshots_dir = os.path.join(self.project_path, ".mimo_snapshots")
        self._meta_path = os.path.join(self.project_path, self.META_FILE)
        self._meta: List[Dict] = self._load_meta()
        self._counter = 0  # ★ 快照 ID 计数器，确保同一秒内创建的快照 ID 唯一

    # ============================================================
    # 元数据管理
    # ============================================================

    def _load_meta(self) -> List[Dict]:
        """加载快照元数据"""
        try:
            if os.path.exists(self._meta_path):
                with open(self._meta_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _save_meta(self):
        """保存快照元数据"""
        try:
            with open(self._meta_path, 'w', encoding='utf-8') as f:
                json.dump(self._meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Snapshot] 保存元数据失败: {e}", flush=True)

    # ============================================================
    # 创建快照
    # ============================================================

    def create_snapshot(self, label: str = "") -> Optional[Dict]:
        """创建快照

        Args:
            label: 快照标签，如 "before_write_file" / "after_edit_file"

        Returns:
            快照信息 dict，失败返回 None
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._counter += 1  # ★ 计数器确保同一秒内创建的快照 ID 唯一
        short_ts = datetime.now().strftime("%H%M%S") + f"_{self._counter}"

        if self._git.is_git_repo:
            return self._create_git_snapshot(label, timestamp, short_ts)
        else:
            return self._create_file_snapshot(label, timestamp, short_ts)

    def _create_git_snapshot(self, label: str, timestamp: str, short_ts: str) -> Optional[Dict]:
        """Git 模式创建快照"""
        try:
            # git add -A
            subprocess.run(
                ['git', 'add', '-A'],
                cwd=self.project_path,
                capture_output=True, text=True, timeout=10,
                encoding='utf-8', errors='replace'
            )

            # 检查是否有变更
            status_result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=self.project_path,
                capture_output=True, text=True, timeout=10,
                encoding='utf-8', errors='replace'
            )
            has_changes = bool(status_result.stdout.strip())

            if has_changes:
                commit_msg = f"[AutoSnapshot] {label} @ {timestamp}"
                result = subprocess.run(
                    ['git', 'commit', '-m', commit_msg, '--no-verify'],
                    cwd=self.project_path,
                    capture_output=True, text=True, timeout=30,
                    encoding='utf-8', errors='replace'
                )
                if result.returncode != 0:
                    # 可能是 nothing to commit
                    pass

            # 获取当前 commit hash
            hash_result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=self.project_path,
                capture_output=True, text=True, timeout=5,
                encoding='utf-8', errors='replace'
            )
            commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else ""

            snapshot = {
                'id': f"git_{short_ts}",
                'label': label,
                'timestamp': timestamp,
                'commit_hash': commit_hash,
                'mode': 'git',
                'path': None,
            }
            self._meta.append(snapshot)
            # 只保留最近 50 条
            if len(self._meta) > 50:
                self._meta = self._meta[-50:]
            self._save_meta()

            print(f"[Snapshot] Git快照已创建: {label} @ {commit_hash[:8]}", flush=True)
            return snapshot

        except Exception as e:
            print(f"[Snapshot] Git快照创建失败: {e}", flush=True)
            return None

    def _create_file_snapshot(self, label: str, timestamp: str, short_ts: str) -> Optional[Dict]:
        """文件备份模式创建快照（非 Git 仓库降级方案）"""
        try:
            if not os.path.exists(self._snapshots_dir):
                os.makedirs(self._snapshots_dir)

            snapshot_dir = os.path.join(self._snapshots_dir, f"snap_{short_ts}")
            if os.path.exists(snapshot_dir):
                shutil.rmtree(snapshot_dir)

            # 复制项目文件（排除 .mimo_snapshots 自身、.venv、__pycache__ 等）
            ignore_patterns = shutil.ignore_patterns(
                '.mimo_snapshots*', '.venv*', 'venv*', '__pycache__*',
                '.git*', 'node_modules*', '.idea*', '.pytest_cache*',
                '*.pyc', '*.log', '.mimo_snapshots_meta.json'
            )
            shutil.copytree(self.project_path, snapshot_dir, ignore=ignore_patterns)

            snapshot = {
                'id': f"file_{short_ts}",
                'label': label,
                'timestamp': timestamp,
                'commit_hash': None,
                'mode': 'file',
                'path': snapshot_dir,
            }
            self._meta.append(snapshot)
            if len(self._meta) > 50:
                # 删除旧快照目录
                old = self._meta[0]
                if old.get('path') and os.path.exists(old['path']):
                    shutil.rmtree(old['path'], ignore_errors=True)
                self._meta = self._meta[-50:]
            self._save_meta()

            print(f"[Snapshot] 文件快照已创建: {label} @ {snapshot_dir}", flush=True)
            return snapshot

        except Exception as e:
            print(f"[Snapshot] 文件快照创建失败: {e}", flush=True)
            return None

    # ============================================================
    # 列出快照
    # ============================================================

    def list_snapshots(self, limit: int = 20) -> List[Dict]:
        """返回最近的快照列表"""
        return list(reversed(self._meta[-limit:]))

    # ============================================================
    # 回退快照
    # ============================================================

    def restore_snapshot(self, snapshot_id: str) -> Tuple[bool, str]:
        """回退到指定快照

        Args:
            snapshot_id: 快照 ID

        Returns:
            (成功与否, 消息)
        """
        snapshot = None
        for s in self._meta:
            if s['id'] == snapshot_id:
                snapshot = s
                break

        if not snapshot:
            return False, f"未找到快照: {snapshot_id}"

        if snapshot['mode'] == 'git':
            return self._restore_git_snapshot(snapshot)
        else:
            return self._restore_file_snapshot(snapshot)

    def _restore_git_snapshot(self, snapshot: Dict) -> Tuple[bool, str]:
        """Git 模式回退"""
        commit_hash = snapshot.get('commit_hash', '')
        if not commit_hash:
            return False, "快照无 commit hash"

        try:
            # 先创建一个当前状态的快照（安全网）
            self.create_snapshot("before_restore")

            # git reset --hard
            result = subprocess.run(
                ['git', 'reset', '--hard', commit_hash],
                cwd=self.project_path,
                capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='replace'
            )

            if result.returncode == 0:
                msg = f"已回退到 {snapshot['label']} ({snapshot['timestamp']})"
                print(f"[Snapshot] {msg}", flush=True)
                return True, msg
            else:
                return False, f"git reset 失败: {result.stderr.strip()}"

        except Exception as e:
            return False, f"回退失败: {e}"

    def _restore_file_snapshot(self, snapshot: Dict) -> Tuple[bool, str]:
        """文件备份模式回退"""
        snap_path = snapshot.get('path', '')
        if not snap_path or not os.path.exists(snap_path):
            return False, f"快照目录不存在: {snap_path}"

        try:
            # 先创建当前状态的快照（安全网）
            self.create_snapshot("before_restore")

            # 清空当前项目目录中的用户文件（保留 .mimo_snapshots 等）
            ignore_dirs = {'.mimo_snapshots', '.venv', 'venv', '__pycache__', '.git', 'node_modules', '.idea', '.pytest_cache'}
            for item in os.listdir(self.project_path):
                full_path = os.path.join(self.project_path, item)
                if item in ignore_dirs or item == self.META_FILE:
                    continue
                if os.path.isfile(full_path):
                    os.remove(full_path)
                elif os.path.isdir(full_path):
                    shutil.rmtree(full_path)

            # 从快照复制回来
            for item in os.listdir(snap_path):
                src = os.path.join(snap_path, item)
                dst = os.path.join(self.project_path, item)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                elif os.path.isdir(src):
                    shutil.copytree(src, dst)

            msg = f"已回退到 {snapshot['label']} ({snapshot['timestamp']})"
            print(f"[Snapshot] {msg}", flush=True)
            return True, msg

        except Exception as e:
            return False, f"文件回退失败: {e}"

    # ============================================================
    # Diff 对比
    # ============================================================

    def diff_snapshots(self, snapshot_id: str) -> str:
        """返回指定快照与当前版本的 diff

        Args:
            snapshot_id: 快照 ID

        Returns:
            diff 文本
        """
        snapshot = None
        for s in self._meta:
            if s['id'] == snapshot_id:
                snapshot = s
                break

        if not snapshot:
            return f"未找到快照: {snapshot_id}"

        if snapshot['mode'] == 'git':
            return self._diff_git_snapshot(snapshot)
        else:
            return self._diff_file_snapshot(snapshot)

    def _diff_git_snapshot(self, snapshot: Dict) -> str:
        """Git 模式 diff"""
        commit_hash = snapshot.get('commit_hash', '')
        if not commit_hash:
            return "快照无 commit hash"

        try:
            result = subprocess.run(
                ['git', 'diff', commit_hash, 'HEAD'],
                cwd=self.project_path,
                capture_output=True, text=True, timeout=15,
                encoding='utf-8', errors='replace'
            )
            if result.returncode == 0:
                diff = result.stdout.strip()
                return diff if diff else "无差异"
            return f"git diff 失败: {result.stderr.strip()}"
        except Exception as e:
            return f"diff 失败: {e}"

    def _diff_file_snapshot(self, snapshot: Dict) -> str:
        """文件备份模式 diff（简单对比文件列表）"""
        snap_path = snapshot.get('path', '')
        if not snap_path or not os.path.exists(snap_path):
            return f"快照目录不存在: {snap_path}"

        lines = []
        try:
            # 收集快照中的文件
            snap_files = set()
            for root, dirs, files in os.walk(snap_path):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), snap_path)
                    snap_files.add(rel)

            # 收集当前项目的文件
            ignore_dirs = {'.mimo_snapshots', '.venv', 'venv', '__pycache__', '.git', 'node_modules', '.idea', '.pytest_cache'}
            curr_files = set()
            for root, dirs, files in os.walk(self.project_path):
                # 过滤忽略目录
                dirs[:] = [d for d in dirs if d not in ignore_dirs]
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), self.project_path)
                    if rel != self.META_FILE:
                        curr_files.add(rel)

            added = curr_files - snap_files
            removed = snap_files - curr_files
            modified = set()

            for f in (curr_files & snap_files):
                snap_f = os.path.join(snap_path, f)
                curr_f = os.path.join(self.project_path, f)
                if os.path.getsize(snap_f) != os.path.getsize(curr_f):
                    modified.add(f)

            if added:
                lines.append("=== 新增文件 ===")
                for f in sorted(added):
                    lines.append(f"  + {f}")
            if removed:
                lines.append("=== 删除文件 ===")
                for f in sorted(removed):
                    lines.append(f"  - {f}")
            if modified:
                lines.append("=== 修改文件 ===")
                for f in sorted(modified):
                    lines.append(f"  ~ {f}")

            return "\n".join(lines) if lines else "无差异"

        except Exception as e:
            return f"diff 失败: {e}"

    # ============================================================
    # 清理
    # ============================================================

    def cleanup_old_snapshots(self, keep: int = 20):
        """清理旧快照，只保留最近 keep 条"""
        if len(self._meta) <= keep:
            return

        old_snapshots = self._meta[:-keep]
        for s in old_snapshots:
            if s.get('mode') == 'file' and s.get('path') and os.path.exists(s['path']):
                shutil.rmtree(s['path'], ignore_errors=True)

        self._meta = self._meta[-keep:]
        self._save_meta()
        print(f"[Snapshot] 已清理旧快照，保留最近 {keep} 条", flush=True)
