# -*- coding: utf-8 -*-
"""Lemon Work · GitHub Release 自动发布（tag v1.0.0 + 285MB 便携包上传）
凭据：从 Git Credential Manager 提取（用户此前已授权）
"""
import json
import os
import subprocess
import sys
import time
import requests

REPO = "EVEN83-dev/lemon-work"
TAG = "v1.0.0"
ZIP = r"D:\YH-lemon\release\LemonWork-v1.0.0-win64-portable.zip"


def get_token():
    """从 GCM 提取 GitHub token（host=github.com）"""
    inp = "protocol=https\nhost=github.com\n\n"
    r = subprocess.run(["git", "credential", "fill"], input=inp,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="ignore", timeout=15)
    for line in (r.stdout or "").splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return None


def main():
    tok = get_token()
    if not tok:
        print("FAIL: 未取到 GitHub 凭据（GCM 无 github.com 记录）")
        return 1
    hdr = {"Authorization": "Bearer " + tok,
           "Accept": "application/vnd.github+json",
           "User-Agent": "lemon-work-release"}

    # 1) 已有 Release？
    r = requests.get(f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}",
                     headers=hdr, timeout=15,
                     proxies={"http": None, "https": None})
    if r.status_code == 200:
        rel = r.json()
        print("Release 已存在: " + rel.get("html_url", ""))
    else:
        body = {
            "tag_name": TAG,
            "target_commitish": "main",
            "name": "Lemon Work v1.0.0 · 绿色免安装版（含数字银行沙箱）",
            "body": (
                "## 🍋 Lemon Work v1.0.0\n\n"
                "AI 智能工作助手 + 数字银行沙箱 —— **解压即用，无需安装任何依赖**。\n\n"
                "### 包含\n"
                "- `LemonWork/` 主程序（含便携 Python 运行时）\n"
                "- `DigitalBank/` 数字银行沙箱（14 账户 / 36 项业务 API）\n"
                "- `启动LemonWork.bat` / `启动数字银行.bat` 双击即用\n\n"
                "### 快速开始\n"
                "1. 解压 zip 到任意目录\n"
                "2. 双击 `启动数字银行.bat`（或直接启动主程序，它会自动拉起银行）\n"
                "3. 双击 `启动LemonWork.bat`\n"
                "4. 设置 → 模型 → 填入 DeepSeek API Key（或探测本地 Ollama 模型）\n\n"
                "### 免责声明\n"
                "数字银行为纯本地模拟沙箱，所有账户/资金/行情均为虚构数据，"
                "仅用于 AI Agent 能力验证与赛事演示，不涉及任何真实资金。"),
            "draft": False,
            "prerelease": False,
        }
        r = requests.post(f"https://api.github.com/repos/{REPO}/releases",
                          headers=hdr, data=json.dumps(body), timeout=20,
                          proxies={"http": None, "https": None})
        if r.status_code not in (201, 200):
            print("FAIL 创建 Release:", r.status_code, r.text[:200])
            return 1
        rel = r.json()
        print("Release 已创建: " + rel.get("html_url", ""))

    up = rel.get("upload_url", "").split("{")[0]
    if not up:
        print("FAIL: 无 upload_url")
        return 1

    # 2) 已传过？（必须 state=uploaded 才算数 —— 中断上传留下的残尸资产
    #    会被 GitHub 自动回收，name 匹配但 state!=uploaded 时要重新传）
    assets = requests.get(rel["assets_url"], headers=hdr, timeout=15,
                          proxies={"http": None, "https": None}).json()
    name = os.path.basename(ZIP)
    done = [a for a in assets
            if a.get("name") == name and a.get("state") == "uploaded"]
    if done:
        print("资产已完整上传:", name,
              "（%.0f MB）" % (done[0].get("size", 0) / 1048576),
              "—— 无需重复上传")
        print("下载地址:", done[0].get("browser_download_url", ""))
        return 0
    # 清理同名的残尸资产（state != uploaded），否则重传会 422
    for a in assets:
        if a.get("name") == name:
            print("清理残尸资产（state=" + str(a.get("state")) + "）…")
            requests.delete(a["url"], headers=hdr, timeout=15,
                            proxies={"http": None, "https": None})

    # 3) 上传 285MB（分块由 requests 处理；大文件走一次 PUT）
    size = os.path.getsize(ZIP)
    print(f"上传 {name}（{size/1024/1024:.0f} MB）…", flush=True)
    t0 = time.time()
    with open(ZIP, "rb") as f:
        r = requests.post(
            up, headers={**hdr, "Content-Type": "application/zip",
                         "Content-Length": str(size)},
            params={"name": name}, data=f, timeout=7200,
            proxies={"http": None, "https": None})
    if r.status_code == 201:
        mb_s = size / 1024 / 1024 / max(time.time() - t0, 1)
        print(f"OK 资产上传完成（{mb_s:.1f} MB/s）: " + r.json().get("browser_download_url", ""))
        print("RELEASE DONE: " + rel.get("html_url", ""))
        return 0
    print("FAIL 上传:", r.status_code, r.text[:200])
    return 1


if __name__ == "__main__":
    sys.exit(main())
