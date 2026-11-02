# -*- coding: utf-8 -*-
"""
标准模式代码保护锁 — Code Lock for Standard Mode

规则:
1. 标准模式核心文件被锁定，修改前必须验证密码
2. 密码: 所属院校 = 天津职业技术师范大学
3. 只能在现有技术基础上完善，不得破坏或改变架构
4. 所有修改尝试都会被记录

★ Batch 10/11 授权修改记录 (2026-07-27):
- engine_manager.py: 集成 SkillCaller 多层降级策略 (Batch 11)
- engine_manager.py: 智能路由 + 健康检查 + 自动降级 (Batch 10)
- skills_registry.py: 热加载 + 动态注册/卸载 (Batch 10)
- mimo_page.html: 代码Diff块级渲染 + 打字效果增强 (Batch 9)

使用方式:
    from core.code_lock import CodeLock
    lock = CodeLock()
    lock.verify()  # 验证密码
    lock.check_file('core/serve_bridge.py')  # 检查文件是否被保护
"""

import hashlib
import json
import os
import time
import sys

# ★ 标准模式核心保护文件列表
# 注：文件路径相对于项目根目录（base_dir）。真实文件位于 standard_mode/ 下，
# 此前写为 "core/xxx" 导致 _compute_hash 永远找不到文件 → 哈希恒为 None →
# 完整性检查永久停留在 no_baseline（锁了等于没锁）。现修正为 standard_mode/ 前缀。
PROTECTED_FILES = [
    # 核心引擎
    "standard_mode/core/serve_bridge.py",
    "standard_mode/core/engine_manager.py",
    "standard_mode/core/ollama_engine.py",
    "standard_mode/core/ollama_bridge.py",
    "standard_mode/core/mimo_engine.py",
    "standard_mode/core/agent_engine.py",
    # UI 层
    "standard_mode/ui/mimo_panel.py",
    "standard_mode/ui/main_window.py",
    "standard_mode/ui/mimo_page.html",
    # 入口
    "standard_mode/main.py",
]

# ★ 密码（所属院校）
CORRECT_PASSWORD = "天津职业技术师范大学"

# ★ 锁状态文件
LOCK_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".code_lock_state.json")

# ★ 修改日志文件
MODIFICATION_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".code_lock_log.jsonl")


class CodeLock:
    """标准模式代码保护锁"""

    def __init__(self, base_dir=None):
        self.base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._verified = False
        self._load_state()

    def _load_state(self):
        """加载锁状态"""
        if os.path.exists(LOCK_STATE_FILE):
            try:
                with open(LOCK_STATE_FILE, 'r', encoding='utf-8') as f:
                    self.state = json.load(f)
            except Exception:
                self.state = {"verified": False, "file_hashes": {}, "locked": True}
        else:
            self.state = {"verified": False, "file_hashes": {}, "locked": True}
            self._save_state()

    def _save_state(self):
        """保存锁状态"""
        with open(LOCK_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _log_attempt(self, action, file_path, success, detail=""):
        """记录修改尝试"""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "file": file_path,
            "success": success,
            "detail": detail,
        }
        try:
            with open(MODIFICATION_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _compute_hash(self, file_path):
        """计算文件 SHA256 哈希"""
        full_path = os.path.join(self.base_dir, file_path)
        if not os.path.exists(full_path):
            return None
        h = hashlib.sha256()
        with open(full_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    def verify(self, password=None):
        """
        验证密码

        参数:
            password: 用户输入的密码，如果为 None 则从环境变量 CODE_LOCK_PASSWORD 读取

        返回:
            bool: 验证是否通过
        """
        if self._verified:
            return True

        if password is None:
            password = os.environ.get("CODE_LOCK_PASSWORD", "")

        if password == CORRECT_PASSWORD:
            self._verified = True
            self.state["verified"] = True
            self.state["last_verify_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save_state()
            self._log_attempt("verify", "*", True, "密码验证通过")
            print("[CodeLock] 密码验证通过，标准模式文件已解锁", flush=True)
            return True
        else:
            self._log_attempt("verify", "*", False, "密码错误")
            print("[CodeLock] 密码验证失败！标准模式文件保持锁定状态", flush=True)
            return False

    def is_locked(self):
        """检查是否处于锁定状态"""
        return not self._verified

    def check_file(self, file_path):
        """
        检查文件是否受保护

        返回:
            dict: {"protected": bool, "locked": bool, "hash_changed": bool}
        """
        # 统一路径格式
        normalized = file_path.replace("\\", "/")
        # 去掉 competition_archive/LemonCode_TRAE_Submission/ 前缀
        for prefix in ["competition_archive/LemonCode_TRAE_Submission/", "competition_archive\\LemonCode_TRAE_Submission\\"]:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]

        is_protected = normalized in PROTECTED_FILES
        hash_changed = False

        if is_protected:
            current_hash = self._compute_hash(normalized)
            stored_hash = self.state.get("file_hashes", {}).get(normalized)
            if stored_hash and current_hash and current_hash != stored_hash:
                hash_changed = True

        return {
            "protected": is_protected,
            "locked": self.is_locked(),
            "hash_changed": hash_changed,
            "file": normalized,
        }

    def save_hashes(self):
        """保存当前所有保护文件的哈希值（用于完整性检查）"""
        hashes = {}
        for f in PROTECTED_FILES:
            h = self._compute_hash(f)
            if h:
                hashes[f] = h
        self.state["file_hashes"] = hashes
        self.state["hash_saved_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._save_state()
        print(f"[CodeLock] 已保存 {len(hashes)} 个文件的完整性哈希", flush=True)

    def check_integrity(self):
        """检查所有保护文件的完整性"""
        results = []
        for f in PROTECTED_FILES:
            current_hash = self._compute_hash(f)
            stored_hash = self.state.get("file_hashes", {}).get(f)
            if stored_hash is None:
                results.append({"file": f, "status": "no_baseline", "msg": "无基准哈希"})
            elif current_hash is None:
                results.append({"file": f, "status": "missing", "msg": "文件不存在"})
            elif current_hash == stored_hash:
                results.append({"file": f, "status": "ok", "msg": "完整"})
            else:
                results.append({"file": f, "status": "modified", "msg": "文件已被修改（未通过密码验证）"})
        return results

    def allow_modification(self, file_path, reason=""):
        """
        请求修改受保护文件的权限

        返回:
            bool: 是否允许修改
        """
        result = self.check_file(file_path)
        if not result["protected"]:
            return True  # 非保护文件，允许修改
        if self._verified:
            self._log_attempt("modify", file_path, True, reason)
            print(f"[CodeLock] 已授权修改: {file_path} (原因: {reason})", flush=True)
            return True
        else:
            self._log_attempt("modify", file_path, False, f"未验证密码, 原因: {reason}")
            print(f"[CodeLock] 拒绝修改: {file_path} — 请先验证密码 (密码: 所属院校)", flush=True)
            return False

    def get_status(self):
        """获取锁状态摘要"""
        return {
            "locked": self.is_locked(),
            "verified": self._verified,
            "protected_files": len(PROTECTED_FILES),
            "hashes_saved": len(self.state.get("file_hashes", {})),
            "last_verify": self.state.get("last_verify_time", "never"),
        }


# ★ 模块级单例
_lock_instance = None

def get_lock():
    """获取 CodeLock 单例"""
    global _lock_instance
    if _lock_instance is None:
        _lock_instance = CodeLock()
    return _lock_instance


def verify_lock(password=None):
    """便捷函数: 验证密码锁"""
    return get_lock().verify(password)


def check_protected(file_path):
    """便捷函数: 检查文件是否受保护"""
    return get_lock().check_file(file_path)


def allow_modify(file_path, reason=""):
    """便捷函数: 请求修改权限"""
    return get_lock().allow_modification(file_path, reason)


if __name__ == "__main__":
    lock = CodeLock()
    print("=== CodeLock 状态 ===")
    print(json.dumps(lock.get_status(), ensure_ascii=False, indent=2))

    print("\n=== 完整性检查 ===")
    for r in lock.check_integrity():
        status_icon = {"ok": "[OK]", "modified": "[CHANGED]", "missing": "[MISSING]", "no_baseline": "[NO BASE]"}
        icon = status_icon.get(r["status"], "[?]")
        print(f"  {icon} {r['file']}: {r['msg']}")

    print("\n=== 保护文件列表 ===")
    for f in PROTECTED_FILES:
        print(f"  - {f}")
