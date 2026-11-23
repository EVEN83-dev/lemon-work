# -*- coding: utf-8 -*-
"""★ 2026-11-23: 本地视觉模型客户端（Ollama）

统一的图片理解入口，供：
  - vision_analyze / image_analyzer
  - pdf_reader 扫描件 OCR
  - video_reader 关键帧理解
  - agent_chat 附件图片预处理（文本模型不支持图片时）

只连本机 Ollama，不上传外网。模型选择优先读 /api/tags 的 capabilities
（qwen3.5 / qwen3-vl 都带 vision），失败再按名称关键词回退。
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from typing import Iterable, List, Optional

DEFAULT_HOST = "http://127.0.0.1:11434"

# 名称兜底（/api/tags 不可用或旧版 Ollama 无 capabilities 时）
_VISION_NAME_HINTS = (
    "vl", "vision", "visual", "qwen2.5-vl", "qwen3-vl", "qwen3.5",
    "llava", "bakllava", "moondream", "minicpm", "cogvlm",
    "internvl", "yi-vl", "glm-4v", "step-1v",
)


def _host() -> str:
    raw = (os.environ.get("OLLAMA_HOST") or "").strip()
    if not raw:
        return DEFAULT_HOST
    if raw.startswith(("http://", "https://")):
        host = raw.rstrip("/")
    else:
        # OLLAMA_HOST 常见值是 "0.0.0.0" / "127.0.0.1:11434"（无 scheme）
        if ":" not in raw:
            raw = raw + ":11434"
        host = "http://" + raw
    # 0.0.0.0 是监听地址，连接要换成 127.0.0.1
    return host.replace("//0.0.0.0", "//127.0.0.1")


def list_models(host: str = "", timeout: float = 3.0) -> List[dict]:
    try:
        req = urllib.request.Request((host or _host()) + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        return data.get("models") or []
    except Exception:
        return []


def is_vision_model(name: str) -> bool:
    n = (name or "").lower()
    return bool(n) and any(k in n for k in _VISION_NAME_HINTS)


def pick_vision_model(host: str = "") -> str:
    """返回本机第一个可用的视觉模型名；没有则返回空串。"""
    models = list_models(host)
    # ① capabilities 明确带 vision（最可靠）
    for m in models:
        caps = [str(c).lower() for c in (m.get("capabilities") or [])]
        if "vision" in caps:
            return str(m.get("name") or m.get("model") or "")
    # ② 名称兜底
    for m in models:
        name = str(m.get("name") or m.get("model") or "")
        if is_vision_model(name):
            return name
    # ③ 常见默认（未拉取列表时也让调用方尝试一次）
    for guess in ("qwen3.5:4b", "qwen3-vl:4b", "llava:latest"):
        if any(str(m.get("name") or "") == guess for m in models):
            return guess
    return ""


def describe_images(images_b64: Iterable[str], prompt: str,
                    model: str = "", host: str = "",
                    timeout: float = 120.0) -> str:
    """把图片 base64 列表发给本地视觉模型，返回文本；失败返回空串。"""
    imgs = [str(x) for x in (images_b64 or []) if x]
    if not imgs:
        return ""
    target = model or pick_vision_model(host)
    if not target:
        return ""
    payload = json.dumps({
        "model": target,
        "prompt": prompt or "请用中文简洁描述图片内容，并提取其中可见文字。",
        "images": imgs,
        "stream": False,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            (host or _host()) + "/api/generate", data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        return str(data.get("response") or "").strip()
    except Exception:
        return ""


def describe_image_paths(paths: Iterable[str], prompt: str,
                         model: str = "", host: str = "",
                         timeout: float = 120.0) -> str:
    imgs = []
    for p in paths or []:
        try:
            with open(str(p), "rb") as f:
                imgs.append(base64.b64encode(f.read()).decode("utf-8"))
        except Exception:
            continue
    return describe_images(imgs, prompt, model=model, host=host, timeout=timeout)
