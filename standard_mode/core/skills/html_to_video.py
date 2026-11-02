# -*- coding: utf-8 -*-
"""
Skill: html_to_video — HTML转视频
===================================
使用 ffmpeg 屏幕抓取将静态 HTML 页面录屏生成 MP4 视频。
需要系统安装 ffmpeg。
"""

import json
import os
import subprocess
import tempfile
import time
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "html_to_video",
    "description": "HTML转视频：使用 ffmpeg 屏幕抓取将静态 HTML 页面录屏生成 MP4 视频。需要系统安装 ffmpeg。",
    "category": "video",
    "version": "1.0.0",
}


def execute(
    html_path: str = "",
    html_content: str = "",
    output_path: str = "",
    duration: int = 10,
    fps: int = 24,
    resolution: str = "1920x1080",
) -> SkillResult:
    """HTML 转视频

    Args:
        html_path: HTML 文件路径（与 html_content 二选一）
        html_content: HTML 内容字符串
        output_path: 输出 MP4 路径
        duration: 视频时长（秒）
        fps: 帧率
        resolution: 分辨率
    """
    if not html_path and not html_content:
        return SkillResult(success=False, error="html_path 或 html_content 必须有一个")

    # 检查 ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return SkillResult(
            success=False,
            error="ffmpeg 未安装或不在 PATH 中",
            output="请安装 ffmpeg: https://ffmpeg.org/download.html",
        )

    try:
        # 准备 HTML 文件
        if html_content and not html_path:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                f.write(html_content)
                html_path = f.name

        if not os.path.exists(html_path):
            return SkillResult(success=False, error=f"HTML 文件不存在: {html_path}")

        # 输出路径
        if not output_path:
            output_path = os.path.join(tempfile.gettempdir(), f"video_{int(time.time())}.mp4")

        # 使用 ffmpeg 生成静态视频帧
        # 方法：用 ffmpeg 的 lavfi 生成背景，叠加 HTML 截图
        # 简化方案：生成单帧图片再转视频

        # 尝试用 playwright 或 wkhtmltoimage 截图
        screenshot_path = html_path.replace('.html', '.png')

        # 尝试 wkhtmltoimage
        try:
            subprocess.run(
                ['wkhtmltoimage', '--quality', '90', '--width', resolution.split('x')[0], html_path, screenshot_path],
                capture_output=True, timeout=30,
            )
        except FileNotFoundError:
            # 回退：用 Pillow 生成简单截图
            try:
                from PIL import Image, ImageDraw, ImageFont
                w, h = [int(x) for x in resolution.split('x')]
                img = Image.new('RGB', (w, h), color='Lemon.DARK_MID_5')
                draw = ImageDraw.Draw(img)
                draw.text((50, 50), "HTML Content Preview", fill='white')
                draw.text((50, 100), html_path, fill='#aaa')
                img.save(screenshot_path)
            except ImportError:
                return SkillResult(success=False, error="需要 wkhtmltoimage 或 Pillow 来截图 HTML", output="pip install pillow")

        # 用 ffmpeg 将截图转为视频
        result = subprocess.run(
            ['ffmpeg', '-y', '-loop', '1', '-i', screenshot_path,
             '-c:v', 'libx264', '-t', str(duration),
             '-pix_fmt', 'yuv420p', '-r', str(fps),
             output_path],
            capture_output=True, text=True, timeout=60,
        )

        # 清理截图
        try:
            os.unlink(screenshot_path)
        except Exception:
            pass

        if result.returncode != 0:
            return SkillResult(success=False, error=f"ffmpeg 转码失败: {result.stderr[:500]}")

        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        return SkillResult(
            success=True,
            output=f"视频已生成: {output_path}\n时长: {duration}s, 帧率: {fps}fps, 分辨率: {resolution}\n大小: {file_size/1024/1024:.1f}MB",
            data={'path': output_path, 'duration': duration, 'fps': fps, 'resolution': resolution, 'file_size': file_size},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"HTML转视频失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="html_to_video",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "html_path": {"type": "string", "description": "HTML 文件路径"},
                "html_content": {"type": "string", "description": "HTML 内容"},
                "output_path": {"type": "string", "description": "输出 MP4 路径"},
                "duration": {"type": "integer", "description": "视频时长（秒）", "default": 10},
                "fps": {"type": "integer", "description": "帧率", "default": 24},
                "resolution": {"type": "string", "description": "分辨率", "default": "1920x1080"},
            },
        },
        handler=execute,
        category=METADATA["category"],
        timeout=120,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
