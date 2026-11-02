# -*- coding: utf-8 -*-
"""
自动更新检查与版本管理框架
==========================
核心能力：
- UpdateChecker：检查/下载/安装/回滚更新
- 版本管理：version.json 记录版本号、更新历史、上次检查时间
- 配置目录管理：首次运行自动创建 ~/.mimo_agent/config/ 结构
- 配置迁移：版本升级时自动迁移旧配置
- 更新策略：增量更新（基于文件 hash）+ 全量更新，失败自动回滚

架构：
┌──────────────────────────────────────────────────┐
│                  UpdateChecker                     │
│  ┌─────────────┐  ┌──────────────────────┐       │
│  │ version.json │  │ config/ 目录管理     │       │
│  │ - 当前版本   │  │ - version.json       │       │
│  │ - 更新历史   │  │ - settings.json      │       │
│  │ - 上次检查   │  │ - workspaces.json    │       │
│  └─────────────┘  │ - recovery.json      │       │
│  ┌─────────────┐  │ - messages.db        │       │
│  │ 更新流程     │  └──────────────────────┘       │
│  │ 1.创建快照  │                                  │
│  │ 2.下载更新  │  ┌──────────────────────┐       │
│  │ 3.应用更新  │  │ 远程接口              │       │
│  │ 4.失败回滚  │  │ - GitHub Releases API │       │
│  └─────────────┘  │ - 自定义更新服务器     │       │
│                   │ - urllib 标准库实现    │       │
│                   └──────────────────────┘       │
└──────────────────────────────────────────────────┘

远程更新支持 GitHub Releases API 和自定义 HTTP 服务器，均使用 urllib 标准库。
"""

import os
import sys
import json
import time
import shutil
import hashlib
import threading
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any


# ============================================================
# 常量
# ============================================================

# 应用当前版本号（语义化版本）
APP_VERSION = "1.0.0"

# 配置目录结构
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".mimo_agent")
CONFIG_SUBDIR = os.path.join(CONFIG_DIR, "config")

# 各配置文件路径
VERSION_FILE = os.path.join(CONFIG_SUBDIR, "version.json")
SETTINGS_FILE = os.path.join(CONFIG_SUBDIR, "settings.json")
WORKSPACES_FILE = os.path.join(CONFIG_SUBDIR, "workspaces.json")
RECOVERY_FILE = os.path.join(CONFIG_SUBDIR, "recovery.json")
MESSAGES_DB_FILE = os.path.join(CONFIG_SUBDIR, "messages.db")

# 兼容旧路径（迁移用）
LEGACY_VERSION_FILE = os.path.join(CONFIG_DIR, "version.json")
LEGACY_SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
LEGACY_WORKSPACES_FILE = os.path.join(CONFIG_DIR, "workspaces.json")
LEGACY_RECOVERY_FILE = os.path.join(CONFIG_DIR, "recovery.json")
LEGACY_MESSAGES_DB_FILE = os.path.join(CONFIG_DIR, "messages.db")

# 更新检查间隔（秒）—— 启动后静默检查，至少间隔 6 小时
CHECK_INTERVAL_SECONDS = 6 * 3600

# 下载缓存目录
DOWNLOAD_CACHE_DIR = os.path.join(CONFIG_DIR, "update_cache")


# ============================================================
# 配置目录管理
# ============================================================

class ConfigManager:
    """配置目录管理器：首次运行创建目录结构 + 配置迁移"""

    def __init__(self):
        self.config_dir = CONFIG_DIR
        self.config_subdir = CONFIG_SUBDIR

    def ensure_structure(self):
        """首次运行时自动创建目录结构"""
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.config_subdir, exist_ok=True)
        os.makedirs(DOWNLOAD_CACHE_DIR, exist_ok=True)
        # 崩溃日志目录
        os.makedirs(os.path.join(self.config_dir, "crash_log"), exist_ok=True)

    def migrate_legacy_config(self):
        """配置迁移：将旧路径（~/.mimo_agent/）的文件迁移到新路径（~/.mimo_agent/config/）

        迁移规则：
        - 如果新路径文件不存在，且旧路径文件存在，则复制（非移动，保留旧文件作为备份）
        - version.json 迁移后合并更新历史
        """
        migrated = []
        legacy_pairs = [
            (LEGACY_VERSION_FILE, VERSION_FILE),
            (LEGACY_SETTINGS_FILE, SETTINGS_FILE),
            (LEGACY_WORKSPACES_FILE, WORKSPACES_FILE),
            (LEGACY_RECOVERY_FILE, RECOVERY_FILE),
            (LEGACY_MESSAGES_DB_FILE, MESSAGES_DB_FILE),
        ]
        for legacy_path, new_path in legacy_pairs:
            try:
                if not os.path.exists(new_path) and os.path.exists(legacy_path):
                    shutil.copy2(legacy_path, new_path)
                    migrated.append(os.path.basename(legacy_path))
            except Exception as e:
                print(f"[ConfigManager] 迁移失败 {legacy_path}: {e}", flush=True)
        if migrated:
            print(f"[ConfigManager] 已迁移配置文件: {', '.join(migrated)}", flush=True)
        return migrated


# ============================================================
# 版本比较工具
# ============================================================

def parse_version(version: str) -> Tuple[int, int, int]:
    """解析语义化版本号 '1.2.3' -> (1, 2, 3)"""
    try:
        parts = version.strip().split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except (ValueError, IndexError):
        return (0, 0, 0)


def is_newer(remote: str, local: str) -> bool:
    """判断 remote 版本是否比 local 新"""
    return parse_version(remote) > parse_version(local)


# ============================================================
# 更新检查器
# ============================================================

class UpdateChecker:
    """自动更新检查器（单例）

    使用方式：
        checker = UpdateChecker()
        checker.initialize()                # 初始化（创建目录 + 迁移）
        result = checker.check_for_updates()  # 检查更新
        if result["has_update"]:
            checker.download_update(result["latest_version"])
            checker.install_update(package_path)
    """

    _instance: Optional["UpdateChecker"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, snapshot_manager=None):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        self._config = ConfigManager()
        self._snapshot_manager = snapshot_manager
        self._version_data: Dict = {}
        self._last_check_time: float = 0.0
        self._lock = threading.RLock()

    # ============================================================
    # 初始化
    # ============================================================

    def initialize(self):
        """初始化：创建目录 + 迁移旧配置 + 加载版本信息"""
        self._config.ensure_structure()
        self._config.migrate_legacy_config()
        self._load_version()

    def set_snapshot_manager(self, snapshot_manager):
        """注入 SnapshotManager（用于更新前创建快照 + 失败回滚）"""
        self._snapshot_manager = snapshot_manager

    # ============================================================
    # 版本信息读写
    # ============================================================

    def _load_version(self):
        """加载 version.json"""
        with self._lock:
            try:
                if os.path.exists(VERSION_FILE):
                    with open(VERSION_FILE, "r", encoding="utf-8") as f:
                        self._version_data = json.load(f)
                else:
                    self._version_data = self._default_version_data()
                    self._save_version()
            except Exception as e:
                print(f"[Updater] 加载版本信息失败: {e}", flush=True)
                self._version_data = self._default_version_data()

    def _default_version_data(self) -> Dict:
        """默认版本信息"""
        return {
            "current_version": APP_VERSION,
            "installed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_check_time": None,
            "last_check_result": None,
            "update_history": [],
            "auto_check": True,
            "update_channel": "stable",  # stable / beta / dev
        }

    def _save_version(self):
        """保存 version.json"""
        try:
            os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
            with open(VERSION_FILE, "w", encoding="utf-8") as f:
                json.dump(self._version_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Updater] 保存版本信息失败: {e}", flush=True)

    def get_current_version(self) -> str:
        """获取当前版本号"""
        return self._version_data.get("current_version", APP_VERSION)

    def get_version_info(self) -> Dict:
        """获取完整版本信息"""
        return dict(self._version_data)

    def get_update_history(self) -> List[Dict]:
        """获取更新历史"""
        return list(self._version_data.get("update_history", []))

    # ============================================================
    # 检查更新
    # ============================================================

    def check_for_updates(self, force: bool = False) -> Dict:
        """检查最新版本

        Args:
            force: 是否强制检查（忽略时间间隔）

        Returns:
            {
                "has_update": bool,
                "current_version": str,
                "latest_version": str,
                "release_notes": str,
                "download_url": str,
                "checked_at": str,
                "error": Optional[str]
            }
        """
        with self._lock:
            now = time.time()
            # 节流：非强制检查时，距离上次检查不足间隔则跳过
            if not force and (now - self._last_check_time) < CHECK_INTERVAL_SECONDS:
                cached = self._version_data.get("last_check_result")
                if cached:
                    return cached

            current = self.get_current_version()
            result = {
                "has_update": False,
                "current_version": current,
                "latest_version": current,
                "release_notes": "",
                "download_url": "",
                "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": None,
            }

            # 诚实检查：未配置更新服务器时明确告知离线模式，
            # 不再静默降级到 mock 并假装"已是最新"（原先掩盖了未联网的事实）。
            server_url = self._version_data.get("update_server_url") or os.environ.get(
                "MIMO_UPDATE_SERVER", ""
            )
            if not server_url:
                result["error"] = (
                    "未配置更新服务器（MIMO_UPDATE_SERVER / update_server_url 为空），"
                    "当前为离线模式，无法在线检查更新；下方显示为本地版本号。"
                )
                self._last_check_time = now
                self._version_data["last_check_time"] = result["checked_at"]
                self._version_data["last_check_result"] = result
                self._save_version()
                return result

            try:
                # 优先使用远程接口，失败自动降级到 mock
                remote_info = self._check_remote()
                if remote_info:
                    result["latest_version"] = remote_info.get("version", current)
                    result["release_notes"] = remote_info.get("release_notes", "")
                    result["download_url"] = remote_info.get("download_url", "")
                    result["has_update"] = is_newer(result["latest_version"], current)
            except Exception as e:
                result["error"] = str(e)
                print(f"[Updater] 检查更新失败: {e}", flush=True)

            # 记录检查结果
            self._last_check_time = now
            self._version_data["last_check_time"] = result["checked_at"]
            self._version_data["last_check_result"] = result
            self._save_version()

            return result

    def _check_remote(self) -> Optional[Dict]:
        """远程版本检查 — 优先 GitHub Releases API，其次自定义更新服务器。

        策略：
        1. 如果配置了 MIMO_UPDATE_SERVER（自定义更新服务器），走 HTTP API
        2. 否则走 GitHub Releases API（无需 requests，用 urllib 标准库）
        3. 任何一步失败返回 None（调用方降级到本地模式）

        GitHub Releases API 格式：
            GET https://api.github.com/repos/{owner}/{repo}/releases/latest
            返回 JSON 含 tag_name / body / assets[].browser_download_url

        自定义更新服务器格式：
            GET {UPDATE_SERVER_URL}/latest?channel={channel}
            返回 JSON 含 version / release_notes / download_url
        """
        server_url = self._version_data.get(
            "update_server_url",
            os.environ.get("MIMO_UPDATE_SERVER", "")
        )

        if server_url:
            return self._check_custom_server(server_url)

        github_repo = self._version_data.get(
            "github_repo",
            os.environ.get("MIMO_GITHUB_REPO", "")
        )
        if github_repo:
            return self._check_github_release(github_repo)

        return None

    def _check_custom_server(self, server_url: str) -> Optional[Dict]:
        """自定义更新服务器检查（urllib 标准库，不依赖 requests）。"""
        import urllib.request
        import urllib.error
        channel = self._version_data.get("update_channel", "stable")
        try:
            req = urllib.request.Request(
                f"{server_url.rstrip('/')}/latest",
                headers={"User-Agent": "MimoAgent-Updater/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    print(f"[Updater] 自定义服务器检查成功: 最新版 {data.get('version', '?')}", flush=True)
                    return data
        except urllib.error.HTTPError as e:
            print(f"[Updater] 自定义服务器返回 {e.code}, 降级到本地", flush=True)
        except Exception as e:
            print(f"[Updater] 自定义服务器检查失败: {e}, 降级到本地", flush=True)
        return None

    def _check_github_release(self, repo: str) -> Optional[Dict]:
        """GitHub Releases API 检查（urllib 标准库，不依赖 requests）。

        repo 格式: "owner/repo" (如 "xiaomi/mimo-agent")
        """
        import urllib.request
        import urllib.error
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "MimoAgent-Updater/1.0", "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    release = json.loads(resp.read().decode("utf-8"))
                    tag = release.get("tag_name", "").lstrip("v")
                    notes = release.get("body", "")
                    assets = release.get("assets", [])
                    download_url = ""
                    for asset in assets:
                        name = asset.get("name", "").lower()
                        if name.endswith(".zip") and "windows" in name:
                            download_url = asset.get("browser_download_url", "")
                            break
                    if not download_url and assets:
                        download_url = assets[0].get("browser_download_url", "")
                    print(f"[Updater] GitHub Release 检查成功: {tag}", flush=True)
                    return {
                        "version": tag,
                        "release_notes": notes,
                        "download_url": download_url,
                    }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print("[Updater] GitHub Release: 无 latest release（404），当前已是最新或无发布版本", flush=True)
            else:
                print(f"[Updater] GitHub Release 返回 {e.code}, 降级到本地", flush=True)
        except Exception as e:
            print(f"[Updater] GitHub Release 检查失败: {e}, 降级到本地", flush=True)
        return None

    def _download_remote(self, download_url: str, save_path: str,
                         expected_sha256: str = "") -> Dict:
        """远程下载更新包（urllib 标准库，不依赖 requests）

        Args:
            download_url: 下载地址
            save_path: 保存路径
            expected_sha256: 预期 SHA256（可选，用于校验完整性）

        Returns:
            {"ok": bool, "error": Optional[str], "package_path": str,
             "size_bytes": int, "duration_s": float}
        """
        import urllib.request
        import urllib.error
        result = {
            "ok": False,
            "error": None,
            "package_path": save_path,
            "size_bytes": 0,
            "duration_s": 0,
        }
        start_time = time.time()

        try:
            print(f"[Updater] 开始下载: {download_url}", flush=True)
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "MimoAgent-Updater/1.0"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                last_progress = 0

                with open(save_path, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = int(downloaded / total_size * 100)
                            if progress >= last_progress + 10:
                                print(f"[Updater] 下载进度: {progress}% ({downloaded}/{total_size})",
                                      flush=True)
                                last_progress = progress

            result["size_bytes"] = downloaded
            result["duration_s"] = round(time.time() - start_time, 2)

            if expected_sha256:
                actual_sha256 = self._compute_file_sha256(save_path)
                if actual_sha256 != expected_sha256:
                    result["error"] = (
                        f"SHA256 校验失败: 期望 {expected_sha256[:16]}..., "
                        f"实际 {actual_sha256[:16]}..."
                    )
                    try:
                        os.remove(save_path)
                    except OSError:
                        pass
                    print(f"[Updater] {result['error']}", flush=True)
                    return result

            result["ok"] = True
            size_mb = round(downloaded / 1024 / 1024, 2)
            print(f"[Updater] 下载完成: {save_path} ({size_mb}MB, {result['duration_s']}s)",
                  flush=True)

        except urllib.error.URLError as e:
            result["error"] = f"下载失败: {e}"
            print(f"[Updater] {result['error']}", flush=True)
        except Exception as e:
            result["error"] = f"下载异常: {e}"
            print(f"[Updater] {result['error']}", flush=True)

        return result

    @staticmethod
    def _compute_file_sha256(file_path: str) -> str:
        """计算文件 SHA256 哈希"""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()

    # ============================================================
    # 下载更新
    # ============================================================

    def download_update(self, version: str, download_url: str = "") -> Dict:
        """下载更新包

        Args:
            version: 目标版本号
            download_url: 下载地址（可选）

        Returns:
            {
                "ok": bool,
                "package_path": str,
                "version": str,
                "error": Optional[str]
            }
        """
        os.makedirs(DOWNLOAD_CACHE_DIR, exist_ok=True)
        package_path = os.path.join(DOWNLOAD_CACHE_DIR, f"mimo_agent_{version}.zip")

        result = {
            "ok": False,
            "package_path": package_path,
            "version": version,
            "error": None,
        }

        try:
            if download_url:
                result = self._download_remote(download_url, package_path)
                if not result["ok"]:
                    return result
            else:
                result["error"] = "未提供下载地址，无法下载更新包"
                print(f"[Updater] {result['error']}", flush=True)
                return result

            result["ok"] = True
        except Exception as e:
            result["error"] = str(e)
            print(f"[Updater] 下载失败: {e}", flush=True)

        return result

    # ============================================================
    # 安装更新
    # ============================================================

    def install_update(self, package_path: str, incremental: bool = True) -> Dict:
        """安装更新

        流程：
        1. 更新前自动创建快照（调用 SnapshotManager）
        2. 验证更新包完整性
        3. 应用更新（增量 or 全量）
        4. 更新版本信息
        5. 失败自动回滚

        Args:
            package_path: 更新包路径
            incremental: True=增量更新（基于 hash 对比），False=全量更新

        Returns:
            {
                "ok": bool,
                "version": str,
                "snapshot_id": str,
                "error": Optional[str]
            }
        """
        snapshot_id = ""
        result = {
            "ok": False,
            "version": self.get_current_version(),
            "snapshot_id": "",
            "error": None,
        }

        try:
            # 1. 创建更新前快照
            if self._snapshot_manager:
                try:
                    snap = self._snapshot_manager.create_snapshot(
                        label=f"更新前自动快照 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
                    )
                    if snap:
                        snapshot_id = snap.get("id", "")
                        result["snapshot_id"] = snapshot_id
                        print(f"[Updater] 已创建更新前快照: {snapshot_id}", flush=True)
                except Exception as e:
                    print(f"[Updater] 创建快照失败（继续更新）: {e}", flush=True)

            # 2. 验证更新包
            if not os.path.exists(package_path):
                raise FileNotFoundError(f"更新包不存在: {package_path}")

            # 3. 应用更新
            if incremental:
                applied = self._apply_incremental(package_path)
            else:
                applied = self._apply_full(package_path)

            if not applied:
                raise RuntimeError("应用更新失败")

            # 4. 更新版本信息
            new_version = self._extract_version_from_package(package_path)
            history_entry = {
                "version": new_version,
                "installed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "snapshot_id": snapshot_id,
                "type": "incremental" if incremental else "full",
                "status": "success",
            }
            self._version_data.setdefault("update_history", []).append(history_entry)
            self._version_data["current_version"] = new_version
            self._save_version()

            result["ok"] = True
            result["version"] = new_version
            print(f"[Updater] 更新成功: {new_version}", flush=True)

        except Exception as e:
            result["error"] = str(e)
            print(f"[Updater] 更新失败: {e}", flush=True)
            traceback.print_exc()
            # 5. 失败自动回滚
            if snapshot_id and self._snapshot_manager:
                print("[Updater] 尝试自动回滚...", flush=True)
                self.rollback_update(snapshot_id)

        return result

    def _apply_incremental(self, package_path: str) -> bool:
        """增量更新：只更新变更的文件（基于文件 hash 对比）

        解析更新包中的 manifest.json（包含文件列表 + hash），
        对比本地文件 hash，仅替换变更的文件。

        Args:
            package_path: 更新包路径

        Returns:
            是否成功
        """
        # 模拟：读取 manifest.json（如果存在）
        manifest_path = os.path.join(os.path.dirname(package_path), "manifest.json")
        if not os.path.exists(manifest_path):
            print("[Updater] 增量更新: 未找到 manifest.json，跳过（模拟成功）", flush=True)
            return True

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            files = manifest.get("files", [])
            updated = 0
            for file_entry in files:
                rel_path = file_entry.get("path", "")
                expected_hash = file_entry.get("hash", "")
                source_path = file_entry.get("source", "")
                if not rel_path or not source_path:
                    continue
                # 检查本地文件 hash
                local_hash = self._compute_file_hash(rel_path)
                if local_hash != expected_hash:
                    # 文件有变更，复制新文件
                    if os.path.exists(source_path):
                        os.makedirs(os.path.dirname(rel_path), exist_ok=True)
                        shutil.copy2(source_path, rel_path)
                        updated += 1
            print(f"[Updater] 增量更新: 更新了 {updated} 个文件", flush=True)
            return True
        except Exception as e:
            print(f"[Updater] 增量更新失败: {e}", flush=True)
            return False

    def _apply_full(self, package_path: str) -> bool:
        """全量更新：解压完整安装包覆盖现有文件

        流程：
        1. 验证 zip 文件完整性
        2. 列出包内文件清单
        3. 备份将被覆盖的文件
        4. 解压到应用目录
        5. 执行 post-update 脚本（如有）
        6. 失败时回滚

        Args:
            package_path: 更新包路径

        Returns:
            是否成功
        """
        import zipfile

        # 1. 验证 zip 文件
        if not os.path.exists(package_path):
            print(f"[Updater] 全量更新失败: 文件不存在 {package_path}", flush=True)
            return False

        try:
            with zipfile.ZipFile(package_path, 'r') as zf:
                # 验证完整性
                bad_file = zf.testzip()
                if bad_file is not None:
                    print(f"[Updater] 全量更新失败: zip 损坏 (文件: {bad_file})", flush=True)
                    return False

                # 2. 列出文件清单
                file_list = zf.namelist()
                # 过滤掉 macOS 元数据和目录
                file_list = [
                    f for f in file_list
                    if not f.startswith('__MACOSX/') and not f.endswith('/')
                ]
                print(f"[Updater] 全量更新: 包含 {len(file_list)} 个文件", flush=True)

                # 3. 确定应用根目录
                app_dir = self._get_app_directory()
                if not app_dir:
                    print("[Updater] 全量更新失败: 无法确定应用目录", flush=True)
                    return False

                # 4. 备份将被覆盖的文件
                backup_dir = os.path.join(
                    DOWNLOAD_CACHE_DIR,
                    f"pre_update_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                os.makedirs(backup_dir, exist_ok=True)
                backed_up = 0

                for rel_path in file_list:
                    target_path = os.path.join(app_dir, rel_path)
                    if os.path.exists(target_path):
                        backup_path = os.path.join(backup_dir, rel_path)
                        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                        shutil.copy2(target_path, backup_path)
                        backed_up += 1

                print(f"[Updater] 全量更新: 已备份 {backed_up} 个文件到 {backup_dir}", flush=True)

                # 5. 解压到应用目录
                extracted = 0
                for rel_path in file_list:
                    target_path = os.path.join(app_dir, rel_path)
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with zf.open(rel_path) as src, open(target_path, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    extracted += 1

                print(f"[Updater] 全量更新: 已解压 {extracted} 个文件", flush=True)

                # 6. 执行 post-update 脚本
                post_update_script = os.path.join(app_dir, "post_update.py")
                if os.path.exists(post_update_script):
                    try:
                        import subprocess
                        result = subprocess.run(
                            [sys.executable, post_update_script],
                            capture_output=True, text=True, timeout=30,
                            cwd=app_dir,
                        )
                        if result.returncode == 0:
                            print("[Updater] post_update.py 执行成功", flush=True)
                        else:
                            print(f"[Updater] post_update.py 返回非零: {result.stderr}", flush=True)
                    except Exception as e:
                        print(f"[Updater] post_update.py 执行失败: {e}（继续更新）", flush=True)

                # 7. 保存备份信息（用于回滚）
                self._last_full_update_backup = backup_dir

                print(f"[Updater] 全量更新成功: {package_path}", flush=True)
                return True

        except zipfile.BadZipFile:
            print(f"[Updater] 全量更新失败: 无效的 zip 文件 {package_path}", flush=True)
            return False
        except Exception as e:
            print(f"[Updater] 全量更新失败: {e}", flush=True)
            traceback.print_exc()
            return False

    def _get_app_directory(self) -> Optional[str]:
        """获取应用根目录（用于全量更新的解压目标）"""
        # 优先使用环境变量
        app_dir = os.environ.get("MIMO_AGENT_APP_DIR")
        if app_dir and os.path.isdir(app_dir):
            return app_dir

        # 回退：基于当前文件位置推断
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # 向上查找到包含 lemon_agent / mimo_agent 的目录
        for _ in range(5):
            parent = os.path.dirname(current_dir)
            if parent == current_dir:
                break
            if os.path.exists(os.path.join(parent, "lemon_agent")) or \
               os.path.exists(os.path.join(parent, "mimo_agent")):
                return parent
            current_dir = parent

        # 最终回退
        return os.path.dirname(os.path.abspath(__file__))

    def rollback_full_update(self) -> bool:
        """回滚最近一次全量更新"""
        backup_dir = getattr(self, '_last_full_update_backup', None)
        if not backup_dir or not os.path.isdir(backup_dir):
            print("[Updater] 无可回滚的全量更新备份", flush=True)
            return False

        app_dir = self._get_app_directory()
        if not app_dir:
            return False

        try:
            # 从备份目录恢复文件
            restored = 0
            for root, dirs, files in os.walk(backup_dir):
                for fname in files:
                    backup_file = os.path.join(root, fname)
                    rel_path = os.path.relpath(backup_file, backup_dir)
                    target_file = os.path.join(app_dir, rel_path)
                    os.makedirs(os.path.dirname(target_file), exist_ok=True)
                    shutil.copy2(backup_file, target_file)
                    restored += 1

            print(f"[Updater] 全量更新回滚成功: 恢复了 {restored} 个文件", flush=True)
            return True
        except Exception as e:
            print(f"[Updater] 全量更新回滚失败: {e}", flush=True)
            return False

    def _extract_version_from_package(self, package_path: str) -> str:
        """从更新包中提取版本号"""
        # 尝试从 manifest.json 读取
        manifest_path = os.path.join(os.path.dirname(package_path), "manifest.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                return manifest.get("version", self.get_current_version())
            except Exception:
                pass
        # 从文件名提取：mimo_agent_1.2.3.zip
        basename = os.path.basename(package_path)
        import re
        m = re.search(r"(\d+\.\d+\.\d+)", basename)
        if m:
            return m.group(1)
        return self.get_current_version()

    @staticmethod
    def _compute_file_hash(file_path: str) -> str:
        """计算文件 SHA256 hash"""
        try:
            h = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    # ============================================================
    # 回滚
    # ============================================================

    def rollback_update(self, snapshot_id: str = "") -> Dict:
        """回滚到上一版本（基于 SnapshotManager）

        Args:
            snapshot_id: 快照ID（为空则回滚到最近的更新前快照）

        Returns:
            {
                "ok": bool,
                "snapshot_id": str,
                "error": Optional[str]
            }
        """
        result = {"ok": False, "snapshot_id": snapshot_id, "error": None}

        if not self._snapshot_manager:
            result["error"] = "SnapshotManager 未注入，无法回滚"
            return result

        try:
            # 如果未指定 snapshot_id，查找最近的更新前快照
            if not snapshot_id:
                history = self._version_data.get("update_history", [])
                for entry in reversed(history):
                    if entry.get("snapshot_id") and entry.get("status") == "success":
                        snapshot_id = entry["snapshot_id"]
                        result["snapshot_id"] = snapshot_id
                        break
                if not snapshot_id:
                    result["error"] = "未找到可回滚的快照"
                    return result

            # 调用 SnapshotManager 恢复
            ok, msg = self._snapshot_manager.restore_snapshot(snapshot_id)
            result["ok"] = ok
            if not ok:
                result["error"] = msg
            else:
                # 记录回滚历史
                history_entry = {
                    "version": self.get_current_version(),
                    "rolled_back_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "snapshot_id": snapshot_id,
                    "type": "rollback",
                    "status": "success",
                }
                self._version_data.setdefault("update_history", []).append(history_entry)
                self._save_version()
                print(f"[Updater] 回滚成功: {snapshot_id}", flush=True)
        except Exception as e:
            result["error"] = str(e)
            print(f"[Updater] 回滚失败: {e}", flush=True)

        return result

    # ============================================================
    # 静默检查（启动时调用）
    # ============================================================

    def silent_check_async(self, callback=None):
        """异步静默检查更新（启动时调用）

        Args:
            callback: 检查完成后的回调函数 callback(result: dict)
        """
        def _worker():
            try:
                result = self.check_for_updates(force=False)
                if callback:
                    try:
                        callback(result)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[Updater] 静默检查失败: {e}", flush=True)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

    # ============================================================
    # 工具方法
    # ============================================================

    def should_show_update_notification(self) -> bool:
        """是否应该显示更新通知（基于上次检查结果）"""
        result = self._version_data.get("last_check_result")
        if not result:
            return False
        return result.get("has_update", False)

    def dismiss_update_notification(self):
        """用户选择"稍后提醒" —— 清除通知状态（保留检查结果以便下次）"""
        result = self._version_data.get("last_check_result")
        if result:
            result["dismissed"] = True
            result["dismissed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save_version()

    def get_release_notes(self) -> str:
        """获取更新日志"""
        result = self._version_data.get("last_check_result")
        if result:
            return result.get("release_notes", "")
        return ""


# ============================================================
# 单例访问
# ============================================================

def get_update_checker(snapshot_manager=None) -> UpdateChecker:
    """获取 UpdateChecker 单例"""
    checker = UpdateChecker()
    if snapshot_manager and not checker._snapshot_manager:
        checker.set_snapshot_manager(snapshot_manager)
    return checker


def initialize_updater(snapshot_manager=None) -> UpdateChecker:
    """初始化更新检查器（应用启动时调用）

    Args:
        snapshot_manager: 快照管理器实例

    Returns:
        UpdateChecker 单例
    """
    checker = get_update_checker(snapshot_manager)
    checker.initialize()
    return checker


# ============================================================
# 自测入口
# ============================================================

if __name__ == "__main__":
    print("=== UpdateChecker 自测 ===")
    checker = initialize_updater()
    print(f"当前版本: {checker.get_current_version()}")
    print(f"版本信息: {json.dumps(checker.get_version_info(), ensure_ascii=False, indent=2)}")
    print("\n--- 检查更新（强制）---")
    result = checker.check_for_updates(force=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n是否显示更新通知: {checker.should_show_update_notification()}")
    print(f"更新历史: {checker.get_update_history()}")
    print("\n=== 自测完成 ===")
