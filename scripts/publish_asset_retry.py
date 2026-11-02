# -*- coding: utf-8 -*-
"""GitHub asset 上传·自动重试版（间歇网络对策：整传失败即重来，直到成功）"""
import json
import os
import subprocess
import sys
import time
import requests

REPO = "EVEN83-dev/lemon-work"
TAG = "v1.0.0"
ZIP = r"D:\YH-lemon\release\LemonWork-v1.0.0-win64-portable.zip"
NOPROXY = {"http": None, "https": None}


def get_token():
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
        print("FAIL: 无凭据")
        return 1
    hdr = {"Authorization": "Bearer " + tok,
           "Accept": "application/vnd.github+json",
           "User-Agent": "lemon-work-release"}

    for attempt in range(1, 9):
        try:
            r = requests.get(
                f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}",
                headers=hdr, timeout=15, proxies=NOPROXY)
            if r.status_code != 200:
                print(f"[{attempt}] Release 查询失败 {r.status_code}，10s 重试")
                time.sleep(10)
                continue
            rel = r.json()
            name = os.path.basename(ZIP)
            assets = rel.get("assets") or []
            done = [a for a in assets
                    if a.get("name") == name and a.get("state") == "uploaded"]
            if done:
                print("SUCCESS 资产已在:",
                      done[0].get("browser_download_url", ""))
                return 0
            # 清残尸
            up = rel.get("upload_url", "").split("{")[0]
            for a in assets:
                if a.get("name") == name:
                    print("清理残尸（state=" + str(a.get("state")) + "）")
                    requests.delete(a["url"], headers=hdr, timeout=15,
                                    proxies=NOPROXY)
            size = os.path.getsize(ZIP)
            print(f"[{attempt}] 上传 {name}（{size//1048576} MB）…", flush=True)
            t0 = time.time()
            with open(ZIP, "rb") as f:
                r2 = requests.post(
                    up, headers={**hdr, "Content-Type": "application/zip",
                                 "Content-Length": str(size)},
                    params={"name": name}, data=f, timeout=5400,
                    proxies=NOPROXY)
            if r2.status_code == 201:
                a = r2.json()
                if a.get("state") == "uploaded":
                    mb_s = size / 1048576 / max(time.time() - t0, 1)
                    print(f"SUCCESS（{mb_s:.1f} MB/s）: "
                          + a.get("browser_download_url", ""))
                    return 0
                print(f"[{attempt}] GitHub 收到但 state="
                      f"{a.get('state')}（处理中，下轮确认）")
            else:
                print(f"[{attempt}] 上传失败 HTTP {r2.status_code}: "
                      + r2.text[:120])
        except Exception as e:
            print(f"[{attempt}] 异常: " + str(e)[:100], flush=True)
        time.sleep(15)
    print("FAIL: 8 轮尝试均未成功")
    return 1


if __name__ == "__main__":
    sys.exit(main())
