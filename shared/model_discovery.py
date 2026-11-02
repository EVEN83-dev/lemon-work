# -*- coding: utf-8 -*-
"""
Lemon Agent 模型自动发现模块
==============================
自动扫描电脑上安装的 AI 软件和模型：

支持检测的软件类型：
1. 本地 LLM 推理引擎：Ollama, LM Studio, GPT4All, LocalAI
2. 模型文件：.gguf, .bin, .safetensors
3. 云端 API：MIMO Code, DeepSeek, OpenAI, Anthropic
4. APP 类：暂时不支持（需要特殊集成）

用法：
    from core.model_discovery import ModelDiscovery
    discovery = ModelDiscovery()
    models = discovery.scan_all()
    for model in models:
        print(f"{model['name']} ({model['type']}) - {model['path']}")
"""

import os
import json
import shutil
import subprocess
import re
import glob
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict


# ============================================================================
# 模型类型
# ============================================================================

class ModelType:
    """模型类型"""
    OLLAMA = "ollama"           # Ollama 本地模型
    LM_STUDIO = "lm_studio"     # LM Studio
    GPT4ALL = "gpt4all"         # GPT4All
    LOCALAI = "localai"         # LocalAI
    GGUF = "gguf"               # GGUF 模型文件
    SAFETENSORS = "safetensors" # SafeTensors 模型文件
    BIN = "bin"                 # PyTorch/ONNX 模型文件
    MIMOCODE = "mimocode"       # MIMO Code 云端
    DEEPSEEK = "deepseek"       # DeepSeek 云端
    OPENAI = "openai"           # OpenAI 云端
    ANTHROPIC = "anthropic"     # Anthropic 云端


@dataclass
class ModelInfo:
    """模型信息"""
    id: str                     # 唯一标识
    name: str                   # 显示名称
    type: str                   # 类型
    path: str = ""              # 文件路径（本地模型）
    size: int = 0               # 文件大小（字节）
    api_key: str = ""           # API Key（云端模型）
    host: str = ""              # API 地址
    port: int = 0               # 端口
    running: bool = False       # 是否运行中
    installed: bool = False     # 是否已安装
    description: str = ""       # 描述
    download_url: str = ""      # 下载地址
    last_checked: str = ""      # 最后检测时间
    source: str = ""            # 来源软件

    def to_dict(self) -> Dict:
        return asdict(self)


# ============================================================================
# 模型发现器
# ============================================================================

class ModelDiscovery:
    """模型自动发现器 — 扫描电脑上的 AI 软件和模型"""

    # 常见安装路径
    INSTALL_PATHS = {
        ModelType.OLLAMA: [
            r"C:\Users\{}\AppData\Local\Programs\Ollama",
            r"C:\Program Files\Ollama",
            "/usr/local/share/ollama",
            "/opt/ollama",
        ],
        ModelType.LM_STUDIO: [
            r"C:\Users\{}\AppData\Local\LM Studio",
            r"C:\Program Files\LM Studio",
            "/usr/local/bin/lm-studio",
        ],
        ModelType.GPT4ALL: [
            r"C:\Users\{}\AppData\Local\GPT4All",
            r"C:\Program Files\GPT4All",
            "/usr/local/bin/gpt4all",
        ],
    }

    # 模型文件常见目录
    MODEL_DIRS = [
        r"C:\Users\{}\.ollama\models",
        r"C:\Users\{}\.cache\lm-studio",
        r"C:\Users\{}\AppData\Local\nomic.ai",
        r"C:\Users\{}\models",
        r"C:\Users\{}\Downloads\models",
        os.path.expanduser("~/.ollama/models"),
        os.path.expanduser("~/.cache/lm-studio"),
        "/usr/share/models",
    ]

    # 模型文件扩展名
    MODEL_EXTENSIONS = [".gguf", ".bin", ".safetensors", ".pt", ".pth", ".onnx"]

    def __init__(self):
        self._models: Dict[str, ModelInfo] = {}
        self._lock = None

    # ==================== 扫描所有 ====================

    def scan_all(self) -> List[ModelInfo]:
        """扫描所有模型"""
        self._models.clear()

        # 1. 扫描 Ollama
        self._scan_ollama()

        # 2. 扫描 LM Studio
        self._scan_lm_studio()

        # 3. 扫描 GPT4All
        self._scan_gpt4all()

        # 4. 扫描模型文件
        self._scan_model_files()

        # 5. 检查云端 API
        self._check_cloud_apis()

        return list(self._models.values())

    # ==================== Ollama ====================

    def _scan_ollama(self):
        """扫描 Ollama"""
        # 检查是否安装
        ollama_exe = shutil.which("ollama") or self._find_in_common_paths("ollama.exe", ModelType.OLLAMA)
        if not ollama_exe:
            return

        self._models["ollama_engine"] = ModelInfo(
            id="ollama_engine",
            name="Ollama",
            type=ModelType.OLLAMA,
            path=ollama_exe,
            installed=True,
            source="ollama",
            host="http://localhost",
            port=11434,
        )

        # 获取已安装模型列表
        try:
            import requests
            resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)  # ★ v3.14 改用127.0.0.1
            if resp.status_code == 200:
                self._models["ollama_engine"].running = True
                data = resp.json()
                for model in data.get("models", []):
                    model_id = f"ollama:{model['name']}"
                    self._models[model_id] = ModelInfo(
                        id=model_id,
                        name=model["name"],
                        type=ModelType.OLLAMA,
                        source="ollama",
                        installed=True,
                        running=True,
                        description=model.get("details", {}).get("family", ""),
                    )
        except Exception:
            pass

    # ==================== LM Studio ====================

    def _scan_lm_studio(self):
        """扫描 LM Studio"""
        lm_studio_exe = self._find_in_common_paths("LM Studio.exe", ModelType.LM_STUDIO)
        if not lm_studio_exe:
            return

        self._models["lm_studio_engine"] = ModelInfo(
            id="lm_studio_engine",
            name="LM Studio",
            type=ModelType.LM_STUDIO,
            path=lm_studio_exe,
            installed=True,
            source="lm_studio",
            host="http://localhost",
            port=1234,  # LM Studio 默认端口
        )

        # 检查是否运行
        try:
            import requests
            resp = requests.get("http://localhost:1234/v1/models", timeout=3)
            if resp.status_code == 200:
                self._models["lm_studio_engine"].running = True
                data = resp.json()
                for model in data.get("data", []):
                    model_id = f"lm_studio:{model['id']}"
                    self._models[model_id] = ModelInfo(
                        id=model_id,
                        name=model["id"],
                        type=ModelType.LM_STUDIO,
                        source="lm_studio",
                        installed=True,
                        running=True,
                    )
        except Exception:
            pass

    # ==================== GPT4All ====================

    def _scan_gpt4all(self):
        """扫描 GPT4All"""
        gpt4all_exe = self._find_in_common_paths("GPT4All.exe", ModelType.GPT4ALL)
        if not gpt4all_exe:
            return

        self._models["gpt4all_engine"] = ModelInfo(
            id="gpt4all_engine",
            name="GPT4All",
            type=ModelType.GPT4ALL,
            path=gpt4all_exe,
            installed=True,
            source="gpt4all",
            host="http://localhost",
            port=4891,  # GPT4All 默认端口
        )

    # ==================== 模型文件 ====================

    def _scan_model_files(self):
        """扫描模型文件"""
        for model_dir in self._get_expanded_paths(self.MODEL_DIRS):
            if not os.path.exists(model_dir):
                continue

            for ext in self.MODEL_EXTENSIONS:
                pattern = os.path.join(model_dir, f"*{ext}")
                for filepath in glob.glob(pattern, recursive=True):
                    self._add_model_file(filepath)

    def _add_model_file(self, filepath: str):
        """添加模型文件"""
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filepath)[1].lower()

        model_id = f"file:{filepath}"
        model_type = {
            ".gguf": ModelType.GGUF,
            ".bin": ModelType.BIN,
            ".safetensors": ModelType.SAFETENSORS,
        }.get(ext, ext[1:])

        try:
            size = os.path.getsize(filepath)
        except Exception:
            size = 0

        self._models[model_id] = ModelInfo(
            id=model_id,
            name=filename,
            type=model_type,
            path=filepath,
            size=size,
            installed=True,
            source="local_file",
        )

    # ==================== 云端 API ====================

    def _check_cloud_apis(self):
        """检查云端 API"""
        # MIMO Code
        try:
            import requests
            resp = requests.get("http://localhost:4097/health", timeout=2)
            if resp.status_code == 200:
                self._models["mimocode"] = ModelInfo(
                    id="mimocode",
                    name="MIMO Code",
                    type=ModelType.MIMOCODE,
                    installed=True,
                    running=True,
                    source="mimocode",
                    host="http://localhost",
                    port=4097,
                )
        except Exception:
            pass

        # DeepSeek（需要 API Key）
        # OpenAI（需要 API Key）
        # Anthropic（需要 API Key）

    # ==================== 工具函数 ====================

    def _find_in_common_paths(self, exe_name: str, model_type: str) -> Optional[str]:
        """在常见路径中查找可执行文件"""
        paths = self.INSTALL_PATHS.get(model_type, [])
        for path in paths:
            if "{}" in path:
                try:
                    username = os.environ.get("USERNAME") or os.environ.get("USER", "")
                    if username:
                        path = path.replace("{}", username)
                except Exception:
                    continue

            exe_path = os.path.join(path, exe_name)
            if os.path.isfile(exe_path):
                return exe_path
        return None

    def _get_expanded_paths(self, paths: List[str]) -> List[str]:
        """展开路径中的用户目录"""
        expanded = []
        for path in paths:
            if "{}" in path:
                try:
                    username = os.environ.get("USERNAME") or os.environ.get("USER", "")
                    if username:
                        expanded.append(path.replace("{}", username))
                except Exception:
                    pass
            else:
                expanded.append(os.path.expanduser(path))
        return expanded

    # ==================== 模型操作 ====================

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        """获取模型信息"""
        return self._models.get(model_id)

    def get_all_models(self) -> List[ModelInfo]:
        """获取所有模型"""
        return list(self._models.values())

    def get_installed_models(self) -> List[ModelInfo]:
        """获取已安装模型"""
        return [m for m in self._models.values() if m.installed]

    def get_running_models(self) -> List[ModelInfo]:
        """获取运行中的模型"""
        return [m for m in self._models.values() if m.running]

    def get_models_by_type(self, model_type: str) -> List[ModelInfo]:
        """按类型获取模型"""
        return [m for m in self._models.values() if m.type == model_type]

    # ==================== 手动添加模型 ====================

    def add_model_manually(self, name: str, model_type: str, path: str = "",
                           api_key: str = "", host: str = "", port: int = 0) -> str:
        """手动添加模型"""
        import uuid
        model_id = f"manual:{uuid.uuid4().hex[:8]}"

        self._models[model_id] = ModelInfo(
            id=model_id,
            name=name,
            type=model_type,
            path=path,
            api_key=api_key,
            host=host,
            port=port,
            installed=True,
            source="manual",
        )

        return model_id

    def remove_model(self, model_id: str):
        """移除模型"""
        if model_id in self._models:
            del self._models[model_id]


# ============================================================================
# 全局单例
# ============================================================================

_global_discovery: Optional[ModelDiscovery] = None


def get_model_discovery() -> ModelDiscovery:
    """获取全局 ModelDiscovery 单例"""
    global _global_discovery
    if _global_discovery is None:
        _global_discovery = ModelDiscovery()
    return _global_discovery