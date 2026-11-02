# -*- coding: utf-8 -*-
"""PyQt5\\Qt5 junction -> 实体目录（根治打包缺 Qt DLL）"""
import os
import shutil
import subprocess
import sys

J = r"D:\YH-lemon\LemonWork\_py312\Lib\site-packages\PyQt5\Qt5"
REAL = r"D:\xiaomi_temp\lemon_agent\_py312\Lib\site-packages\PyQt5\Qt5"

if not os.path.isdir(REAL):
    print("FATAL: junction 目标不存在:", REAL)
    sys.exit(1)

# 1) 删除 junction
if os.path.lexists(J):
    if os.path.islink(J) or os.path.realpath(J) != J:
        # junction: 用 rmdir 只删链接本身
        r = subprocess.run(["cmd", "/c", "rmdir", J], capture_output=True)
        if os.path.lexists(J):
            shutil.rmtree(J, ignore_errors=True)
    else:
        shutil.rmtree(J, ignore_errors=True)
print("junction 已移除:", not os.path.lexists(J))

# 2) 实体复制（copytree 跟随源侧文件；目标侧不存在链接问题）
shutil.copytree(REAL, J, dirs_exist_ok=True)

# 3) 校验
n = sum(len(f) for _, _, f in os.walk(J))
bin_n = len(os.listdir(os.path.join(J, "bin"))) if os.path.isdir(os.path.join(J, "bin")) else 0
lt = "junction" if os.path.realpath(J) != J else "real"
print(f"实体文件: {n}（源 1665）| Qt5\\bin DLL: {bin_n}（应 63）| 类型: {lt}")
if n >= 1600 and bin_n >= 60 and lt == "real":
    print("JUNCTION-FIX OK")
else:
    print("JUNCTION-FIX FAILED")
    sys.exit(1)
