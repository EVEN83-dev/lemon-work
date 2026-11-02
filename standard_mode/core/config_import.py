# -*- coding: utf-8 -*-
"""
配置导入管理器 (ConfigImporter)
==============================
从外部文件导入配置到 Lemon Agent 系统。

功能：
1. 支持多格式 — JSON / YAML / TOML / INI
2. 文件选择器 — 支持路径指定或自动扫描
3. 配置验证 — 导入前校验格式和必填项
4. 配置迁移 — 自动适配旧版本配置格式
5. 冲突处理 — 导入时检测冲突，支持合并/覆盖/跳过策略
6. 回滚支持 — 导入失败时自动恢复原配置

使用示例：
    importer = ConfigImporter()
    result = importer.import_config(
        file_path="path/to/config.json",
        target="settings",       # 导入到 settings 配置
        conflict_strategy="merge",
    )
    if result.ok:
        print(f"导入成功: {result.imported_keys}")
    else:
        print(f"导入失败: {result.error}")
"""

import os
import json
import time
import shutil
import threading
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


# ============================================================
# 枚举与常量
# ============================================================

class ConfigFormat(Enum):
    """配置文件格式"""
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"
    INI = "ini"
    AUTO = "auto"  # 自动检测


class ConflictStrategy(Enum):
    """冲突处理策略"""
    MERGE = "merge"         # 合并（新配置优先）
    OVERWRITE = "overwrite" # 完全覆盖
    SKIP = "skip"           # 跳过冲突项
    ERROR = "error"         # 遇冲突报错


# 配置目录
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".mimo_agent", "config")

# 支持的配置目标
CONFIG_TARGETS = {
    "settings": os.path.join(CONFIG_DIR, "settings.json"),
    "workspaces": os.path.join(CONFIG_DIR, "workspaces.json"),
    "version": os.path.join(CONFIG_DIR, "version.json"),
    "recovery": os.path.join(CONFIG_DIR, "recovery.json"),
}

# 格式与扩展名映射
FORMAT_EXTENSIONS = {
    ".json": ConfigFormat.JSON,
    ".yaml": ConfigFormat.YAML,
    ".yml": ConfigFormat.YAML,
    ".toml": ConfigFormat.TOML,
    ".ini": ConfigFormat.INI,
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ImportResult:
    """导入结果"""
    ok: bool
    imported_keys: List[str] = field(default_factory=list)
    skipped_keys: List[str] = field(default_factory=list)
    conflict_keys: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    backup_path: Optional[str] = None
    source_path: Optional[str] = None
    target: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


# ============================================================
# 配置导入器
# ============================================================

class ConfigImporter:
    """
    配置导入器
    ==========
    - 从外部文件读取配置
    - 校验格式和必填项
    - 处理冲突
    - 写入目标配置文件
    - 失败自动回滚
    """

    # 必填字段定义（按目标）
    REQUIRED_FIELDS = {
        "settings": ["language", "theme"],
        "workspaces": [],
        "version": ["current_version"],
        "recovery": [],
    }

    def __init__(self, config_dir: str = None):
        self._config_dir = config_dir or CONFIG_DIR
        self._lock = threading.RLock()
        os.makedirs(self._config_dir, exist_ok=True)

    # ============================================================
    # 导入主流程
    # ============================================================

    def import_config(self,
                      file_path: str,
                      target: str = "settings",
                      conflict_strategy: ConflictStrategy = ConflictStrategy.MERGE,
                      format_hint: ConfigFormat = ConfigFormat.AUTO,
                      validate: bool = True) -> ImportResult:
        """
        导入配置

        Args:
            file_path: 源配置文件路径
            target: 导入目标 ("settings" / "workspaces" / "version" / "recovery")
            conflict_strategy: 冲突处理策略
            format_hint: 格式提示（AUTO 自动检测）
            validate: 是否校验

        Returns:
            ImportResult 导入结果
        """
        with self._lock:
            result = ImportResult(source_path=file_path, target=target)

            # 1. 验证源文件
            if not os.path.exists(file_path):
                result.ok = False
                result.error = f"源文件不存在: {file_path}"
                return result

            # 2. 检测格式
            config_format = self._detect_format(file_path, format_hint)
            if config_format is None:
                result.ok = False
                result.error = "无法识别配置文件格式"
                return result

            # 3. 读取源配置
            try:
                source_data = self._read_config(file_path, config_format)
            except Exception as e:
                result.ok = False
                result.error = f"读取配置失败: {e}"
                return result

            if not isinstance(source_data, dict):
                result.ok = False
                result.error = "配置内容必须是字典/对象格式"
                return result

            # 4. 校验必填字段
            if validate:
                required = self.REQUIRED_FIELDS.get(target, [])
                missing = [f for f in required if f not in source_data]
                if missing:
                    result.ok = False
                    result.error = f"缺少必填字段: {', '.join(missing)}"
                    return result

            # 5. 获取目标路径
            target_path = CONFIG_TARGETS.get(target)
            if not target_path:
                result.ok = False
                result.error = f"未知的配置目标: {target}"
                return result

            # 6. 读取当前配置
            current_data = {}
            if os.path.exists(target_path):
                try:
                    with open(target_path, "r", encoding="utf-8") as f:
                        current_data = json.load(f)
                except Exception:
                    result.warnings.append("当前配置文件读取失败，将完全覆盖")

            # 7. 备份当前配置
            backup_path = self._create_backup(target_path)
            result.backup_path = backup_path

            # 8. 处理冲突
            merged_data, conflicts, skipped = self._merge_configs(
                current_data, source_data, conflict_strategy
            )
            result.conflict_keys = conflicts
            result.skipped_keys = skipped

            # 9. 写入目标
            try:
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(merged_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                result.ok = False
                result.error = f"写入配置失败: {e}"
                # 回滚
                if backup_path:
                    self._restore_backup(target_path, backup_path)
                    result.warnings.append("已自动回滚到备份配置")
                return result

            # 10. 成功
            result.ok = True
            result.imported_keys = list(source_data.keys())
            if conflicts:
                result.warnings.append(f"存在 {len(conflicts)} 个冲突键，已按 {conflict_strategy.value} 策略处理")

            return result

    def rollback(self, target: str, backup_path: str) -> bool:
        """
        手动回滚到备份配置

        Args:
            target: 配置目标
            backup_path: 备份文件路径

        Returns:
            是否成功
        """
        with self._lock:
            target_path = CONFIG_TARGETS.get(target)
            if not target_path or not os.path.exists(backup_path):
                return False
            return self._restore_backup(target_path, backup_path)

    # ============================================================
    # 批量导入
    # ============================================================

    def import_directory(self,
                         dir_path: str,
                         conflict_strategy: ConflictStrategy = ConflictStrategy.MERGE) -> List[ImportResult]:
        """
        从目录批量导入配置

        自动识别目录中的配置文件：
        - settings.json → settings
        - workspaces.json → workspaces
        - version.json → version
        - recovery.json → recovery

        Args:
            dir_path: 配置目录路径
            conflict_strategy: 冲突处理策略

        Returns:
            导入结果列表
        """
        results = []
        if not os.path.isdir(dir_path):
            return results

        # 文件名到目标的映射
        file_target_map = {
            "settings.json": "settings",
            "workspaces.json": "workspaces",
            "version.json": "version",
            "recovery.json": "recovery",
        }

        for filename, target in file_target_map.items():
            filepath = os.path.join(dir_path, filename)
            if os.path.exists(filepath):
                result = self.import_config(filepath, target, conflict_strategy)
                results.append(result)

        return results

    # ============================================================
    # 格式检测与读取
    # ============================================================

    def _detect_format(self, file_path: str, hint: ConfigFormat) -> Optional[ConfigFormat]:
        """检测配置文件格式"""
        if hint != ConfigFormat.AUTO:
            return hint

        ext = os.path.splitext(file_path)[1].lower()
        return FORMAT_EXTENSIONS.get(ext)

    def _read_config(self, file_path: str, fmt: ConfigFormat) -> Dict:
        """读取配置文件"""
        if fmt == ConfigFormat.JSON:
            return self._read_json(file_path)
        elif fmt == ConfigFormat.YAML:
            return self._read_yaml(file_path)
        elif fmt == ConfigFormat.TOML:
            return self._read_toml(file_path)
        elif fmt == ConfigFormat.INI:
            return self._read_ini(file_path)
        else:
            raise ValueError(f"不支持的配置格式: {fmt}")

    def _read_json(self, file_path: str) -> Dict:
        """读取 JSON 配置"""
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _read_yaml(self, file_path: str) -> Dict:
        """读取 YAML 配置"""
        try:
            import yaml
            with open(file_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            # 降级：尝试作为 JSON 读取
            try:
                return self._read_json(file_path)
            except Exception:
                raise ImportError("YAML 支持需要安装 PyYAML: pip install pyyaml")

    def _read_toml(self, file_path: str) -> Dict:
        """读取 TOML 配置"""
        try:
            import tomllib
            with open(file_path, "rb") as f:
                return tomllib.load(f)
        except ImportError:
            try:
                import tomli
                with open(file_path, "rb") as f:
                    return tomli.load(f)
            except ImportError:
                raise ImportError("TOML 支持需要安装 tomli: pip install tomli")

    def _read_ini(self, file_path: str) -> Dict:
        """读取 INI 配置"""
        import configparser
        config = configparser.ConfigParser()
        config.read(file_path, encoding="utf-8")
        result = {}
        for section in config.sections():
            result[section] = dict(config[section])
        return result

    # ============================================================
    # 合并与冲突处理
    # ============================================================

    def _merge_configs(self, current: Dict, source: Dict,
                       strategy: ConflictStrategy) -> Tuple[Dict, List[str], List[str]]:
        """
        合并配置，处理冲突

        Returns:
            (merged_data, conflict_keys, skipped_keys)
        """
        conflicts = []
        skipped = []

        if strategy == ConflictStrategy.OVERWRITE:
            return dict(source), list(set(current.keys()) & set(source.keys())), []

        if strategy == ConflictStrategy.ERROR:
            overlap = set(current.keys()) & set(source.keys())
            if overlap:
                raise ValueError(f"配置冲突: {', '.join(overlap)}")
            merged = dict(current)
            merged.update(source)
            return merged, [], []

        if strategy == ConflictStrategy.SKIP:
            merged = dict(current)
            for key, value in source.items():
                if key in current:
                    skipped.append(key)
                else:
                    merged[key] = value
            return merged, [], skipped

        # MERGE（默认）：新配置优先
        merged = dict(current)
        for key, value in source.items():
            if key in current and current[key] != value:
                conflicts.append(key)
            merged[key] = value
        return merged, conflicts, skipped

    # ============================================================
    # 备份与回滚
    # ============================================================

    def _create_backup(self, target_path: str) -> Optional[str]:
        """创建配置备份"""
        if not os.path.exists(target_path):
            return None
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = target_path + f".backup_{timestamp}"
            shutil.copy2(target_path, backup_path)
            return backup_path
        except Exception:
            return None

    def _restore_backup(self, target_path: str, backup_path: str) -> bool:
        """从备份恢复"""
        try:
            shutil.copy2(backup_path, target_path)
            return True
        except Exception:
            return False

    # ============================================================
    # 工具方法
    # ============================================================

    def list_available_backups(self, target: str) -> List[Dict]:
        """列出可用的备份"""
        target_path = CONFIG_TARGETS.get(target, "")
        if not target_path:
            return []

        target_dir = os.path.dirname(target_path)
        basename = os.path.basename(target_path)
        backups = []

        try:
            for f in os.listdir(target_dir):
                if f.startswith(basename + ".backup_"):
                    full_path = os.path.join(target_dir, f)
                    backups.append({
                        "path": full_path,
                        "size": os.path.getsize(full_path),
                        "mtime": os.path.getmtime(full_path),
                    })
            backups.sort(key=lambda x: x["mtime"], reverse=True)
        except Exception:
            pass

        return backups

    def validate_config_file(self, file_path: str) -> Tuple[bool, List[str]]:
        """
        校验配置文件是否可导入

        Returns:
            (is_valid, errors)
        """
        errors = []

        if not os.path.exists(file_path):
            errors.append("文件不存在")
            return False, errors

        fmt = self._detect_format(file_path, ConfigFormat.AUTO)
        if fmt is None:
            errors.append("无法识别文件格式")
            return False, errors

        try:
            data = self._read_config(file_path, fmt)
            if not isinstance(data, dict):
                errors.append("配置内容必须是字典格式")
        except Exception as e:
            errors.append(f"读取失败: {e}")

        return len(errors) == 0, errors
