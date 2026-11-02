# -*- coding: utf-8 -*-
"""
Skill: image_analyzer — 图像识别分析
=====================================
OCR文字提取、视觉模型描述、智能分类路由。
支持小模型识图+自动路由到下游Skill。
"""

import json
import os
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "image_analyzer",
    "description": "图像识别分析：OCR文字提取、视觉模型描述、智能分类路由。支持小模型识图+自动路由到下游Skill。",
    "category": "image",
    "version": "1.0.0",
}


def _lazy_import(lib_name: str):
    try:
        mod = __import__(lib_name)
        for part in lib_name.split('.')[1:]:
            mod = getattr(mod, part)
        return mod
    except (ImportError, AttributeError):
        return None


def execute(
    image_path: str = "",
    analysis_type: str = "describe",
    detail_level: str = "medium",
) -> SkillResult:
    """图像识别分析

    Args:
        image_path: 图像路径
        analysis_type: describe/ocr/classify/route
        detail_level: low/medium/high
    """
    if not image_path:
        return SkillResult(success=False, error="image_path 参数为空")
    if not os.path.exists(image_path):
        return SkillResult(success=False, error=f"图像文件不存在: {image_path}")

    try:
        PIL = _lazy_import('PIL')
        if PIL is None:
            return SkillResult(success=False, error="依赖库 'pillow' 未安装", output="pip install pillow")
        from PIL import Image

        img = Image.open(image_path)
        file_size = os.path.getsize(image_path)

        # 基础信息
        info = {
            'path': image_path,
            'format': img.format,
            'size': list(img.size),
            'mode': img.mode,
            'file_size': file_size,
        }

        # ===== OCR =====
        if analysis_type == 'ocr':
            easyocr = _lazy_import('easyocr')
            if easyocr is None:
                return SkillResult(success=False, error="依赖库 'easyocr' 未安装", output="pip install easyocr")
            reader = easyocr.Reader(['ch_sim', 'en'])
            result = reader.readtext(image_path)
            text_lines = [item[1] for item in result]
            full_text = '\n'.join(text_lines)
            return SkillResult(
                success=True,
                output=f"OCR 识别完成，{len(text_lines)} 行文本:\n{full_text}",
                data={'text': full_text, 'lines': text_lines, 'info': info},
            )

        # ===== 分类 =====
        elif analysis_type == 'classify':
            ext = os.path.splitext(image_path)[1].lower()
            fmt_categories = {
                '.png': '位图图像', '.jpg': '位图图像', '.jpeg': '位图图像',
                '.gif': '动态图像', '.svg': '矢量图像', '.webp': '位图图像',
            }
            img_category = fmt_categories.get(ext, '未知格式')
            # 简单启发式分类
            w, h = img.size
            aspect = w / h if h else 1
            orientation = '横向' if aspect > 1.2 else ('纵向' if aspect < 0.8 else '方形')
            classification = {
                'format_category': img_category,
                'orientation': orientation,
                'resolution': '高清' if w * h > 2000000 else ('标清' if w * h > 500000 else '低清'),
                'color_mode': '彩色' if img.mode in ('RGB', 'RGBA') else '灰度/其他',
            }
            return SkillResult(
                success=True,
                output=f"图像分类: {img_category}, {orientation}, {classification['resolution']}",
                data={'classification': classification, 'info': info},
            )

        # ===== 智能路由 =====
        elif analysis_type == 'route':
            # 根据图像特征推荐下游 Skill
            recommendations = []
            if img.mode in ('1', 'L'):
                recommendations.append({'skill': 'image_processor', 'operation': 'convert', 'reason': '灰度图建议转彩色'})
            if os.path.getsize(image_path) > 5 * 1024 * 1024:
                recommendations.append({'skill': 'image_processor', 'operation': 'resize', 'reason': '文件过大建议压缩'})
            recommendations.append({'skill': 'image_processor', 'operation': 'ocr', 'reason': '可尝试 OCR 提取文字'})
            return SkillResult(
                success=True,
                output=f"智能路由建议: {len(recommendations)} 个下游 Skill",
                data={'recommendations': recommendations, 'info': info},
            )

        # ===== 描述（默认）=====
        else:
            w, h = img.size
            desc_parts = [f"{img.format} 图像, {w}x{h} 像素, {img.mode} 模式"]
            if img.mode == 'RGBA':
                desc_parts.append("含透明通道")
            if file_size > 1024 * 1024:
                desc_parts.append(f"文件大小 {file_size/1024/1024:.1f}MB")
            return SkillResult(
                success=True,
                output=f"图像描述: {', '.join(desc_parts)}",
                data={'description': ', '.join(desc_parts), 'info': info},
            )

    except Exception as e:
        return SkillResult(success=False, error=f"图像分析失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="image_analyzer",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "图像路径"},
                "analysis_type": {"type": "string", "enum": ["describe", "ocr", "classify", "route"], "description": "分析类型"},
                "detail_level": {"type": "string", "enum": ["low", "medium", "high"], "description": "详细程度", "default": "medium"},
            },
            "required": ["image_path"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=60,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
