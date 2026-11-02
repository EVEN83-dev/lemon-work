# -*- coding: utf-8 -*-
"""
Lemon Code 环境诊断工具
======================
检查内容：
A. MiMo Code 服务状态（端口 4097 / mimo.exe）
B. Ollama 本地模型状态
C. DeepSeek API 配置与连通性
D. Python 虚拟环境与关键依赖
E. 关键桥接模块可导入性
"""

import os
import sys
import socket
import subprocess
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_port(host, port):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except Exception:
        return False


def check_mimo():
    print("\n[A] MiMo Code 状态")
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mimo_exe = os.path.join(_root, "bin", "mimo.exe")
    exists = os.path.exists(mimo_exe)
    print(f"  mimo.exe 存在: {'是' if exists else '否'} ({mimo_exe})")
    port_open = check_port("127.0.0.1", 4097)
    print(f"  端口 4097 开放: {'是' if port_open else '否'}")
    return exists or port_open


def check_ollama():
    print("\n[B] Ollama 本地模型")
    try:
        import requests
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            print(f"  服务状态: 在线")
            print(f"  已安装模型数: {len(models)}")
            for m in models:
                marker = ""
                if "qwen3.5:4b" in m or "qwen3.5:9b" in m:
                    marker = "  <-- 推荐用于 Skill 调用"
                print(f"    - {m}{marker}")
            return True, models
        else:
            print(f"  服务状态: HTTP {resp.status_code}")
            return False, []
    except Exception as e:
        print(f"  服务状态: 离线 ({e})")
        return False, []


def check_deepseek():
    print("\n[C] DeepSeek API")
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    # 候选路径：~/.deepseek_key、standard_mode/.deepseek_key、lemon_agent/.deepseek_key
    if not key:
        _candidates = [
            os.path.expanduser("~/.deepseek_key"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), ".deepseek_key"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".deepseek_key"),
        ]
        for _kf in _candidates:
            if os.path.exists(_kf):
                try:
                    with open(_kf, "r", encoding="utf-8") as f:
                        key = f.read().strip()
                    if key:
                        break
                except Exception:
                    pass

    if key:
        masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        print(f"  API Key: 已配置 ({masked})")
    else:
        print("  API Key: 未配置")
        print("  请设置环境变量 DEEPSEEK_API_KEY 或创建 .deepseek_key 文件")
        return False

    try:
        import requests
        resp = requests.get(
            "https://api.deepseek.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            print("  API 连通性: 正常")
            return True
        else:
            print(f"  API 连通性: 异常 HTTP {resp.status_code} - {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"  API 连通性: 无法连接 ({e})")
        return False


def check_python_env():
    print("\n[D] Python 环境与依赖")
    print(f"  Python 解释器: {sys.executable}")
    print(f"  Python 版本: {sys.version.split()[0]}")
    deps = ["PyQt5", "PyQt5.QtWebEngineWidgets", "requests", "psutil"]
    all_ok = True
    for dep in deps:
        try:
            importlib.import_module(dep)
            print(f"  {dep}: 已安装")
        except Exception as e:
            print(f"  {dep}: 缺失 ({e})")
            all_ok = False
    return all_ok


def check_bridges():
    print("\n[E] 桥接模块可导入性")
    modules = [
        "shared.engine_mode_manager",
        "shared.bridges.mimo_process_bridge",
        "core.ollama_engine",
        "core.deepseek_engine",
        "core.serve_bridge",
    ]
    all_ok = True
    for mod in modules:
        try:
            importlib.import_module(mod)
            print(f"  {mod}: 可导入")
        except Exception as e:
            print(f"  {mod}: 导入失败 ({e})")
            all_ok = False
    return all_ok


def main():
    print("=" * 60)
    print("Lemon Code 环境诊断报告")
    print("=" * 60)

    mimo_ok = check_mimo()
    ollama_ok, models = check_ollama()
    deepseek_ok = check_deepseek()
    env_ok = check_python_env()
    bridges_ok = check_bridges()

    print("\n" + "=" * 60)
    print("诊断总结")
    print("=" * 60)
    print(f"  MiMo Code:     {'可用' if mimo_ok else '不可用（将使用 Lemon Code 降级）'}")
    print(f"  Ollama:        {'在线' if ollama_ok else '离线'}")
    print(f"  DeepSeek API:  {'可用' if deepseek_ok else '不可用'}")
    print(f"  Python 依赖:   {'完整' if env_ok else '有缺失'}")
    print(f"  桥接模块:      {'正常' if bridges_ok else '有异常'}")

    if ollama_ok and not deepseek_ok:
        print("\n[建议] 当前可使用 Ollama 本地模型进行 Skill 调用测试；")
        print("       如需 DeepSeek 模式，请配置 DEEPSEEK_API_KEY 后重试。")


if __name__ == "__main__":
    main()
