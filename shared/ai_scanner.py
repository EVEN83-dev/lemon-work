# -*- coding: utf-8 -*-
"""
AI 资源扫描模块 — 自动检测本地 AI 工具、模型和 Agent
================================================================
功能：
- 扫描 Ollama 安装位置和已下载模型
- 扫描 MIMO Code 安装位置
- 扫描其他本地 Agent
- 扫描本地模型文件
- 提供统一的资源选择接口
"""

import os
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum


class AIType(Enum):
    OLLAMA = "ollama"
    MIMO_CODE = "mimo_code"
    DEEPSEEK = "deepseek"
    LM_STUDIO = "lm_studio"
    OTHER_AGENT = "other_agent"


@dataclass
class AIResource:
    """AI资源信息"""
    name: str
    ai_type: AIType
    path: str
    version: Optional[str] = None
    status: str = "unknown"
    models: List[str] = None
    port: Optional[int] = None
    
    def __post_init__(self):
        if self.models is None:
            self.models = []


class AIScanner:
    """AI资源扫描器"""
    
    def __init__(self):
        self.resources: List[AIResource] = []
        self._drives = self._get_drives()
    
    def _get_drives(self) -> List[str]:
        """获取所有可用驱动器"""
        drives = []
        for letter in ['C', 'D', 'E', 'F']:
            if os.path.exists(f"{letter}:\\"):
                drives.append(f"{letter}:")
        return drives
    
    def scan_all(self) -> List[AIResource]:
        """扫描所有AI资源"""
        self.resources = []
        self.scan_ollama()
        self.scan_mimo_code()
        self.scan_lm_studio()
        self.scan_other_agents()
        return self.resources
    
    def scan_ollama(self) -> Optional[AIResource]:
        """扫描 Ollama"""
        # 检查默认安装位置
        default_paths = [
            os.path.expanduser(r"~\AppData\Local\Programs\Ollama"),
            r"C:\Users\Legion\AppData\Local\Programs\Ollama",
        ]
        
        # 检查所有驱动器
        for drive in self._drives:
            default_paths.append(f"{drive}\\ollama")
            default_paths.append(f"{drive}\\Program Files\\Ollama")
        
        ollama_path = None
        for path in default_paths:
            if os.path.exists(path) and os.path.isfile(os.path.join(path, "ollama.exe")):
                ollama_path = path
                break
        
        if not ollama_path:
            return None
        
        # 获取已安装模型
        models = self._get_ollama_models()
        
        resource = AIResource(
            name="Ollama",
            ai_type=AIType.OLLAMA,
            path=ollama_path,
            status="installed",
            models=models,
            port=11434
        )
        
        # 检查是否运行中
        if self._is_port_in_use(11434):
            resource.status = "running"
        
        self.resources.append(resource)
        return resource
    
    def _get_ollama_models(self) -> List[str]:
        """获取 Ollama 已安装模型"""
        models = []
        
        # 方法1：通过 API 获取
        try:
            import requests
            response = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                for model in data.get("models", []):
                    models.append(model.get("name", "unknown"))
                return models
        except Exception:
            pass  # API 不可用，尝试命令行方式
        
        # 方法2：通过命令行获取
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=10)
            for line in result.stdout.strip().split("\n")[1:]:  # 跳过标题行
                if line.strip():
                    model_name = line.split()[0]
                    models.append(model_name)
        except Exception:
            pass  # 命令行也不可用，尝试扫描目录
        
        # 方法3：扫描本地模型目录
        model_dirs = [
            os.path.expanduser(r"~\.ollama\models"),
            r"C:\Users\Legion\.ollama\models",
        ]
        
        for model_dir in model_dirs:
            if os.path.exists(model_dir):
                blobs_dir = os.path.join(model_dir, "blobs")
                if os.path.exists(blobs_dir):
                    # 模型信息在 manifests 目录
                    manifests_dir = os.path.join(model_dir, "manifests")
                    if os.path.exists(manifests_dir):
                        for root, dirs, files in os.walk(manifests_dir):
                            for d in dirs:
                                if d not in ["registry.ollama.ai"]:
                                    models.append(d)
        
        return list(set(models))  # 去重
    
    def scan_mimo_code(self) -> List[AIResource]:
        """扫描 MIMO Code"""
        mimo_resources = []
        
        # 检查所有驱动器
        for drive in self._drives:
            search_paths = [
                f"{drive}\\mimo_ai",
                f"{drive}\\小米MIMO Code",
                os.path.expanduser(r"~\AppData\Local\Programs\@mimo-ai\mimocode-windows-x64"),
            ]
            
            for path in search_paths:
                mimo_exe = os.path.join(path, "mimo.exe")
                if os.path.exists(mimo_exe):
                    resource = AIResource(
                        name="MIMO Code",
                        ai_type=AIType.MIMO_CODE,
                        path=path,
                        status="found"
                    )
                    
                    # 检查是否运行中
                    if self._is_process_running("mimo.exe"):
                        resource.status = "running"
                    
                    mimo_resources.append(resource)
                    self.resources.append(resource)
        
        return mimo_resources
    
    def scan_lm_studio(self) -> Optional[AIResource]:
        """扫描 LM Studio"""
        lm_studio_paths = [
            os.path.expanduser(r"~\AppData\Local\LM-Studio"),
            r"C:\Program Files\LM-Studio",
        ]
        
        for drive in self._drives:
            lm_studio_paths.append(f"{drive}\\LM-Studio")
            lm_studio_paths.append(f"{drive}\\lm-studio")
        
        for path in lm_studio_paths:
            if os.path.exists(path):
                resource = AIResource(
                    name="LM Studio",
                    ai_type=AIType.LM_STUDIO,
                    path=path,
                    status="found"
                )
                self.resources.append(resource)
                return resource
        
        return None
    
    def scan_other_agents(self) -> List[AIResource]:
        """扫描其他 Agent"""
        agents = []
        
        # 扫描常见Agent目录
        for drive in self._drives:
            agent_patterns = [
                f"{drive}\\*agent*",
                f"{drive}\\*Agent*",
            ]
            
            for pattern in agent_patterns:
                import glob
                for path in glob.glob(pattern):
                    if os.path.isdir(path) and "mimo_agent" not in path and "lemon_agent" not in path:
                        # 检查是否是Python项目
                        if os.path.exists(os.path.join(path, "main.py")) or \
                           os.path.exists(os.path.join(path, "requirements.txt")):
                            resource = AIResource(
                                name=os.path.basename(path),
                                ai_type=AIType.OTHER_AGENT,
                                path=path,
                                status="found"
                            )
                            agents.append(resource)
                            self.resources.append(resource)
        
        return agents
    
    def _is_port_in_use(self, port: int) -> bool:
        """检查端口是否被占用"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    
    def _is_process_running(self, process_name: str) -> bool:
        """检查进程是否运行中"""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
                capture_output=True,
                text=True
            )
            return process_name.lower() in result.stdout.lower()
        except Exception:
            return False  # 进程检查失败（权限不足或命令不可用）
    
    def get_summary(self) -> str:
        """获取扫描结果摘要"""
        lines = ["=== AI 资源扫描结果 ===\n"]
        
        # 按类型分组
        by_type = {}
        for r in self.resources:
            type_name = r.ai_type.value
            if type_name not in by_type:
                by_type[type_name] = []
            by_type[type_name].append(r)
        
        for type_name, resources in by_type.items():
            lines.append(f"\n【{type_name.upper()}】")
            for r in resources:
                status_icon = "🟢" if r.status == "running" else "⚪"
                lines.append(f"  {status_icon} {r.name}")
                lines.append(f"     路径: {r.path}")
                if r.models:
                    lines.append(f"     模型: {', '.join(r.models[:5])}")
                if r.port:
                    lines.append(f"     端口: {r.port}")
        
        return "\n".join(lines)
    
    def to_json(self) -> str:
        """导出为JSON"""
        data = []
        for r in self.resources:
            data.append({
                "name": r.name,
                "type": r.ai_type.value,
                "path": r.path,
                "status": r.status,
                "models": r.models,
                "port": r.port
            })
        return json.dumps(data, ensure_ascii=False, indent=2)
    
    def cleanup(self):
        """释放资源（清理扫描结果和缓存）"""
        self.resources.clear()
        self._drives.clear()


# 便捷函数
def scan_ai_resources() -> List[AIResource]:
    """扫描所有AI资源"""
    scanner = AIScanner()
    return scanner.scan_all()

def get_ollama_models() -> List[str]:
    """获取Ollama模型列表"""
    scanner = AIScanner()
    resource = scanner.scan_ollama()
    return resource.models if resource else []

def print_scan_result():
    """打印扫描结果"""
    scanner = AIScanner()
    scanner.scan_all()
    print(scanner.get_summary())


if __name__ == "__main__":
    print_scan_result()
