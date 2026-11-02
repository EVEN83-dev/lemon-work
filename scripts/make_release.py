#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lemon Work · 发布流水线（发布前检查 → 绿色免安装包组装 → zip）

产物：
  D:\\YH-lemon\\release\\LemonWork-v{ver}-win64-portable\\
    ├── LemonWork\\          源码 + _py312 便携运行时（解压即用）
    ├── DigitalBank\\        数字银行沙箱（代码 + 页面 + 启动器）
    ├── 启动LemonWork.bat
    ├── 启动数字银行.bat
    ├── README.md / LICENSE / docs\\
  D:\\YH-lemon\\release\\LemonWork-v{ver}-win64-portable.zip

发布前检查（任一失败即终止）：
  ① 数字银行在线 + UI 状态总线可用
  ② 关键文件清单齐全
  ③ 空连接审计 PASS（audit_broken_links）
  ④ 最近一次白盒回归 30/30（读 %TEMP% 日志）
"""
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = r"D:\YH-lemon\LemonWork"
BANK = r"D:\虚拟系统软件模拟\数字银行"
OUT = r"D:\YH-lemon\release"
VER = "1.0.0"
NAME = f"LemonWork-v{VER}-win64-portable"

PY = os.path.join(ROOT, "_py312", "python.exe")

# 打包时从源码树剔除的运行时垃圾 / 敏感 / 巨型目录
EXCLUDE_TOP = {"__pycache__", ".lemon", "bin", "dist", "outputs", ".git",
               "release", "gui_worm_bridge.log", "nul"}
EXCLUDE_DATA_KEEP = {"custom_models.json"}  # 需要保留的 data 文件（空表也保留结构）


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore", **kw)


def check(name, ok, detail=""):
    print("[%s] %s %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)
    return ok


def precheck() -> bool:
    ok = True
    # ① 银行 + UI 总线
    try:
        import requests
        r = requests.get("http://127.0.0.1:8090/api/health", timeout=3,
                         proxies={"http": None, "https": None})
        ok &= check("① 数字银行在线", r.status_code == 200,
                    str(r.json().get("version", "")))
        r2 = requests.get("http://127.0.0.1:8090/api/ui/state", timeout=3,
                          proxies={"http": None, "https": None})
        ok &= check("① UI 状态总线", r2.status_code == 200
                    and (r2.json() or {}).get("success") is True)
    except Exception as e:
        ok &= check("① 数字银行在线", False, str(e)[:80])
    # ② 关键文件
    must = [
        ("yh_main.py", ROOT), ("yh_app.py", ROOT),
        (r"standard_mode\main.py", ROOT),
        (r"standard_mode\ui\mimo_app.js", ROOT),
        (r"standard_mode\ui\mimo_panel.py", ROOT),
        (r"standard_mode\ui\mimo_page.html", ROOT),
        (r"standard_mode\ui\mimo_style.css", ROOT),
        (r"shared\engine_manager.py", ROOT),
        (r"shared\skills_builtin\remote_bank_skills.py", ROOT),
        (r"shared\skills_builtin\bank_skills.py", ROOT),
        (r"shared\core\task_classifier.py", ROOT),
        ("server.py", BANK), ("bank_core.py", BANK),
        ("market_engine.py", BANK), ("index.html", BANK),
        (r"_py312\pythonw.exe", ROOT),
    ]
    for rel, base in must:
        p = os.path.join(base, rel)
        if not check("② " + rel, os.path.exists(p)):
            ok = False
    # ③ 空连接审计
    a = sh([PY, os.path.join(ROOT, "scripts", "audit_broken_links.py")])
    ok &= check("③ 空连接审计", "AUDIT PASS" in (a.stdout or ""), (a.stdout or "").strip().splitlines()[-1][:60] if a.stdout else "")
    # ④ 最近一次白盒回归
    import glob
    logs = sorted(glob.glob(os.path.join(os.environ.get("TEMP", "."),
                                         "lw_t_wb*.log")) +
                  glob.glob(os.path.join(os.environ.get("TEMP", "."),
                                         "lw_guitest*.log")), key=os.path.getmtime)
    if logs:
        txt = open(logs[-1], encoding="utf-8", errors="ignore").read()
        passed = [l for l in txt.splitlines() if l.startswith("SUMMARY")]
        ok &= check("④ 白盒回归（最近一次）",
                    bool(passed) and "30/30 PASS" in passed[-1], passed[-1][:40] if passed else "")
    else:
        ok &= check("④ 白盒回归（最近一次）", False, "未找到回归日志")
    return ok


def copy_tree(src, dst, exclude_dirs=(), exclude_files=()):
    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        dirs[:] = [d for d in dirs if d not in exclude_dirs
                   and d != "__pycache__" and not d.startswith(".git")]
        for f in files:
            if f in exclude_files or f.endswith((".pyc", ".log", ".tmp")):
                continue
            s = os.path.join(root, f)
            d = os.path.join(dst, rel, f) if rel != "." else os.path.join(dst, f)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            try:
                shutil.copy2(s, d)
            except (PermissionError, OSError) as e:
                print("  跳过 %s: %s" % (s, str(e)[:60]), flush=True)


def main():
    if not precheck():
        print("RELEASE BLOCKED：发布前检查未通过", flush=True)
        return 1
    print("=" * 60)
    stage = os.path.join(OUT, NAME)
    if os.path.exists(stage):
        shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage, exist_ok=True)

    # 1) LemonWork 源码（含 _py312 便携运行时；剔除运行时垃圾）
    print("[1/4] 复制 LemonWork（含便携运行时，约 1.2GB，请耐心）…", flush=True)
    lw_dst = os.path.join(stage, "LemonWork")
    copy_tree(ROOT, lw_dst, exclude_dirs=EXCLUDE_TOP)
    # data 目录只保留必要结构（ trajectories/崩溃日志/测试垃圾不入包）
    data_dst = os.path.join(lw_dst, "data")
    if os.path.isdir(data_dst):
        keep = ("custom_models.json",)
        for root, dirs, files in os.walk(data_dst):
            for f in files:
                if f not in keep:
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        pass
        for root, dirs, files in os.walk(data_dst, topdown=False):
            for d in dirs:
                p = os.path.join(root, d)
                if not os.listdir(p):
                    os.rmdir(p)
    # config 保留默认；skills/knowledge_base 随 copy_tree 已带

    # 2) 数字银行（纯代码 + 页面 + 启动器）
    print("[2/4] 复制数字银行…", flush=True)
    bank_dst = os.path.join(stage, "DigitalBank")
    copy_tree(BANK, bank_dst,
              exclude_dirs={"__pycache__", ".idea", "data"},
              exclude_files={"smoke_421.py", "smoke_436.py", "smoke_437.py",
                             "smoke_438.py"})
    # 数字银行 data 目录给空壳（运行时自动建）
    os.makedirs(os.path.join(bank_dst, "data"), exist_ok=True)

    # 3) 根启动器（相对路径，拷到哪都能跑）+ README/LICENSE
    print("[3/4] 写启动器与文档…", flush=True)
    with open(os.path.join(stage, "启动LemonWork.bat"), "w",
              encoding="gbk", errors="ignore") as f:
        f.write("@echo off\r\n"
                "cd /d \"%~dp0LemonWork\"\r\n"
                "start \"\" \"%~dp0LemonWork\\_py312\\pythonw.exe\" \"%~dp0LemonWork\\yh_main.py\"\r\n"
                "exit\r\n")
    with open(os.path.join(stage, "启动数字银行.bat"), "w",
              encoding="gbk", errors="ignore") as f:
        f.write("@echo off\r\n"
                "cd /d \"%~dp0DigitalBank\"\r\n"
                "start \"数字银行\" \"%~dp0LemonWork\\_py312\\python.exe\" server.py\r\n"
                "exit\r\n")
    src_readme = os.path.join(BANK, "README.md")
    docs = os.path.join(stage, "docs")
    os.makedirs(docs, exist_ok=True)
    if os.path.exists(src_readme):
        shutil.copy2(src_readme, os.path.join(docs, "数字银行说明.md"))
    for md in ("银行办理指令-可复制.md", "深圳金融科技大赛-测试指令.md"):
        p = os.path.join(ROOT, md)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(docs, md))
    # LICENSE（MIT）
    lic = os.path.join(stage, "LICENSE")
    if not os.path.exists(lic):
        with open(lic, "w", encoding="utf-8") as f:
            f.write(
                "MIT License\n\n"
                "Copyright (c) 2026 Lemon Work Contributors\n\n"
                "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
                "of this software and associated documentation files (the \"Software\"), to deal\n"
                "in the Software without restriction, including without limitation the rights\n"
                "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
                "copies of the Software, and to permit persons to whom the Software is\n"
                "furnished to do so, subject to the following conditions:\n\n"
                "The above copyright notice and this permission notice shall be included in all\n"
                "copies or substantial portions of the Software.\n\n"
                "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n"
                "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n"
                "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\n"
                "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\n"
                "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\n"
                "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n"
                "SOFTWARE.\n")
    # requirements.txt（供源码克隆用户 pip 安装）
    pf = sh([PY, "-m", "pip", "freeze", "--local"])
    core_pkgs = []
    want = ("PyQt5", "PyQtWebEngine", "requests", "markdown", "pyinstaller")
    for line in (pf.stdout or "").splitlines():
        low = line.lower()
        if any(low.startswith(w.lower()) for w in want):
            core_pkgs.append(line)
    with open(os.path.join(stage, "requirements.txt"), "w", encoding="utf-8") as f:
        f.write("# 源码运行所需核心依赖（绿色包已内置 _py312，无需安装）\n"
                + "\n".join(core_pkgs) + "\n")

    # 4) zip
    print("[4/4] 压缩 zip（约几分钟）…", flush=True)
    zpath = os.path.join(OUT, NAME + ".zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(stage):
            for f in files:
                fp = os.path.join(root, f)
                arc = os.path.relpath(fp, OUT)
                try:
                    z.write(fp, arc)
                except (PermissionError, OSError):
                    pass
    mb = os.path.getsize(zpath) / 1024 / 1024
    print("=" * 60, flush=True)
    print("RELEASE OK: %s (%.0f MB)" % (zpath, mb), flush=True)
    print("目录: %s" % stage, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
