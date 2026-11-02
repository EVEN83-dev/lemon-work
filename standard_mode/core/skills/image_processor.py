# -*- coding: utf-8 -*-
"""
Skill: image_processor — 图像处理与 OCR
========================================
缩放/旋转/滤镜/格式转换/合成/OCR 文字识别。支持中文 OCR。
"""

import json
import os
import tempfile
import time
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "image_processor",
    "description": "图像处理: 缩放/旋转/滤镜/格式转换/合成/OCR 文字识别。支持中文 OCR。",
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


def _lib_missing(lib_name: str) -> SkillResult:
    return SkillResult(success=False, error=f"依赖库 '{lib_name}' 未安装", output=f"pip install {lib_name}")


def execute(
    image_path: str = "",
    operation: str = "info",
    output_path: str = "",
    options: str = "{}",
) -> SkillResult:
    """图像处理"""
    if not image_path:
        return SkillResult(success=False, error="image_path 参数为空")
    if not os.path.exists(image_path):
        return SkillResult(success=False, error=f"图像文件不存在: {image_path}")

    try:
        opts = json.loads(options) if isinstance(options, str) else options
    except json.JSONDecodeError:
        opts = {}

    try:
        # OCR 特殊处理
        if operation == 'ocr':
            easyocr = _lazy_import('easyocr')
            if easyocr is None:
                return _lib_missing('easyocr')
            languages = opts.get('languages', ['ch_sim', 'en'])
            reader = easyocr.Reader(languages)
            result = reader.readtext(image_path)
            text_lines = [item[1] for item in result]
            full_text = '\n'.join(text_lines)
            return SkillResult(
                success=True,
                output=f"OCR 识别完成，识别到 {len(text_lines)} 行文本:\n{full_text}",
                data={'text': full_text, 'lines': text_lines},
            )

        # 其他操作用 Pillow
        PIL = _lazy_import('PIL')
        if PIL is None:
            return _lib_missing('pillow')
        from PIL import Image, ImageFilter

        img = Image.open(image_path)

        if operation == 'info':
            return SkillResult(
                success=True,
                output=f"图像信息:\n  路径: {image_path}\n  格式: {img.format}\n  尺寸: {img.size}\n  模式: {img.mode}",
                data={'path': image_path, 'format': img.format, 'size': list(img.size), 'mode': img.mode},
            )

        elif operation == 'resize':
            w, h = opts.get('width', img.size[0]), opts.get('height', img.size[1])
            img = img.resize((int(w), int(h)), Image.LANCZOS)

        elif operation == 'rotate':
            angle = float(opts.get('angle', 0))
            img = img.rotate(angle, expand=True)

        elif operation == 'filter':
            filter_type = opts.get('type', 'blur')
            filter_map = {'blur': ImageFilter.BLUR, 'sharpen': ImageFilter.SHARPEN,
                          'edge': ImageFilter.FIND_EDGES, 'emboss': ImageFilter.EMBOSS, 'smooth': ImageFilter.SMOOTH}
            if filter_type not in filter_map:
                return SkillResult(success=False, error=f"未知滤镜: {filter_type}")
            img = img.filter(filter_map[filter_type])

        elif operation == 'convert':
            fmt = opts.get('format', 'PNG').upper()
            if fmt == 'JPEG' and img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            if not output_path:
                output_path = os.path.join(tempfile.gettempdir(), f"converted_{int(time.time())}.{fmt.lower()}")
            img.save(output_path, format=fmt)
            return SkillResult(
                success=True,
                output=f"格式转换完成: {image_path} → {output_path} ({fmt})",
                data={'input': image_path, 'output': output_path, 'format': fmt},
            )

        elif operation == 'composite':
            overlay_path = opts.get('overlay', '')
            if not overlay_path or not os.path.exists(overlay_path):
                return SkillResult(success=False, error="overlay 参数缺失或文件不存在")
            pos_str = opts.get('position', '0,0')
            x, y = [int(v) for v in pos_str.split(',')]
            overlay = Image.open(overlay_path)
            if img.mode != overlay.mode:
                overlay = overlay.convert(img.mode)
            img.paste(overlay, (x, y))

        else:
            return SkillResult(success=False, error=f"未知 operation: {operation}")

        if not output_path:
            output_path = image_path
        img.save(output_path)

        return SkillResult(
            success=True,
            output=f"图像处理完成: {operation}\n输入: {image_path}\n输出: {output_path}\n尺寸: {img.size}",
            data={'input': image_path, 'output': output_path, 'operation': operation, 'size': list(img.size)},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"图像处理失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="image_processor",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "输入图像路径"},
                "operation": {"type": "string", "enum": ["info", "resize", "rotate", "filter", "convert", "composite", "ocr"], "description": "操作类型"},
                "output_path": {"type": "string", "description": "输出路径"},
                "options": {"type": "string", "description": "JSON 操作参数", "default": "{}"},
            },
            "required": ["image_path", "operation"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=60,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
