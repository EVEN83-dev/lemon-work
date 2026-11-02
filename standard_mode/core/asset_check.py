# -*- coding: utf-8 -*-
"""364章 T1.2: 资产完整性自检 — 启动时校验关键静态资产 SHA256 一致性"""

import hashlib
import os
import shutil
import threading
from typing import List, Tuple, Optional

ASSET_MANIFEST: List[Tuple[str, str]] = [
    ("standard_mode/ui/libs/chartjs/chart.umd.min.js", "js"),
    ("standard_mode/ui/libs/marked/marked.min.js", "js"),
    ("standard_mode/ui/qwebchannel.js", "js"),
    ("standard_mode/ui/mimo_app.js", "js"),
    ("standard_mode/ui/mimo_page.html", "html"),
    ("standard_mode/ui/mimo_style.css", "css"),
]

_COPY_TARGETS = ["bin/_internal", "dist/lemon_agent/_internal"]


def _sha256(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def check_and_repair(project_root: str) -> List[dict]:
    results = []
    for rel_path, _kind in ASSET_MANIFEST:
        src_path = os.path.join(project_root, rel_path)
        src_hash = _sha256(src_path)
        if src_hash is None:
            results.append({"path": rel_path, "status": "source_missing", "repaired": False})
            continue
        for target in _COPY_TARGETS:
            tgt_path = os.path.join(project_root, target, rel_path)
            tgt_hash = _sha256(tgt_path)
            if tgt_hash is None:
                try:
                    os.makedirs(os.path.dirname(tgt_path), exist_ok=True)
                    shutil.copy2(src_path, tgt_path)
                    results.append({"path": rel_path, "target": target, "status": "missing_copied", "repaired": True})
                except Exception as e:
                    results.append({"path": rel_path, "target": target, "status": "missing_copy_failed", "error": str(e), "repaired": False})
            elif tgt_hash != src_hash:
                try:
                    shutil.copy2(src_path, tgt_path)
                    results.append({"path": rel_path, "target": target, "status": "mismatch_repaired", "repaired": True})
                except Exception as e:
                    results.append({"path": rel_path, "target": target, "status": "mismatch_repair_failed", "error": str(e), "repaired": False})
    return results


def run_async_check(project_root: str, callback=None):
    def _worker():
        try:
            results = check_and_repair(project_root)
            repaired = [r for r in results if r.get("repaired")]
            if repaired:
                print(f"[364章][asset_check] 修复 {len(repaired)} 处资产不一致", flush=True)
            else:
                print(f"[364章][asset_check] 资产校验通过", flush=True)
            if callback:
                try:
                    callback(results)
                except Exception:
                    pass
        except Exception as e:
            print(f"[364章][asset_check] 校验异常: {e}", flush=True)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t
