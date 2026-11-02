# -*- coding: utf-8 -*-
"""
Skill: deploy_helper — 部署助手
================================
生成 Docker/npm/pip/GitHub Actions 部署脚本和配置文件。
"""

import json
import os
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "deploy_helper",
    "description": "部署助手：生成 Docker/npm/pip/GitHub Actions 部署脚本和配置文件",
    "category": "system",
    "version": "1.0.0",
}


def execute(
    project_name: str = "",
    project_type: str = "python",
    deploy_target: str = "docker",
    output_dir: str = "",
    python_version: str = "3.11",
    node_version: str = "18",
    port: int = 8000,
) -> SkillResult:
    """生成部署配置

    Args:
        project_name: 项目名称
        project_type: python/node/go
        deploy_target: docker/github_actions/kubernetes/heroku
        output_dir: 输出目录
        python_version: Python 版本
        node_version: Node.js 版本
        port: 服务端口
    """
    if not project_name:
        return SkillResult(success=False, error="project_name 参数为空")

    try:
        if not output_dir:
            output_dir = os.getcwd()
        os.makedirs(output_dir, exist_ok=True)
        files_created = []

        # ===== Docker =====
        if deploy_target in ('docker', 'all'):
            if project_type == 'python':
                dockerfile = f"""FROM python:{python_version}-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE {port}
CMD ["python", "-m", "{project_name}"]
"""
            elif project_type == 'node':
                dockerfile = f"""FROM node:{node_version}-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --production
COPY . .
EXPOSE {port}
CMD ["node", "server.js"]
"""
            else:
                dockerfile = f"""FROM golang:1.21-alpine
WORKDIR /app
COPY go.* ./
RUN go mod download
COPY . .
RUN go build -o /{project_name}
EXPOSE {port}
CMD ["/{project_name}"]
"""
            path = os.path.join(output_dir, 'Dockerfile')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(dockerfile)
            files_created.append('Dockerfile')

            # .dockerignore
            dockerignore = """__pycache__/
*.pyc
.git
.venv/
venv/
node_modules/
.env
*.egg-info/
dist/
build/
"""
            path = os.path.join(output_dir, '.dockerignore')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(dockerignore)
            files_created.append('.dockerignore')

        # ===== GitHub Actions =====
        if deploy_target in ('github_actions', 'all'):
            if project_type == 'python':
                workflow = f"""name: CI/CD
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '{python_version}'
      - run: pip install -r requirements.txt
      - run: pip install pytest ruff
      - run: ruff check .
      - run: pytest tests/
  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - run: echo "Deploy {project_name}"
"""
            elif project_type == 'node':
                workflow = f"""name: CI/CD
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '{node_version}'
      - run: npm ci
      - run: npm test
  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - run: echo "Deploy {project_name}"
"""
            else:
                workflow = f"""name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: echo "Build {project_name}"
"""
            gh_dir = os.path.join(output_dir, '.github', 'workflows')
            os.makedirs(gh_dir, exist_ok=True)
            path = os.path.join(gh_dir, 'ci.yml')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(workflow)
            files_created.append('.github/workflows/ci.yml')

        # ===== docker-compose =====
        if deploy_target in ('docker', 'all'):
            compose = f"""version: '3.8'
services:
  app:
    build: .
    ports:
      - "{port}:{port}"
    environment:
      - ENV=production
    restart: unless-stopped
"""
            path = os.path.join(output_dir, 'docker-compose.yml')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(compose)
            files_created.append('docker-compose.yml')

        return SkillResult(
            success=True,
            output=f"部署配置已生成: {project_name}\n类型: {project_type}\n目标: {deploy_target}\n文件: {', '.join(files_created)}",
            data={'output_dir': output_dir, 'files': files_created, 'project_type': project_type, 'deploy_target': deploy_target},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"部署配置生成失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="deploy_helper",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "project_type": {"type": "string", "enum": ["python", "node", "go"], "description": "项目类型", "default": "python"},
                "deploy_target": {"type": "string", "enum": ["docker", "github_actions", "kubernetes", "heroku", "all"], "description": "部署目标", "default": "docker"},
                "output_dir": {"type": "string", "description": "输出目录"},
                "python_version": {"type": "string", "description": "Python 版本", "default": "3.11"},
                "node_version": {"type": "string", "description": "Node.js 版本", "default": "18"},
                "port": {"type": "integer", "description": "服务端口", "default": 8000},
            },
            "required": ["project_name"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=15,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
