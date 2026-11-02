# -*- coding: utf-8 -*-
"""Skill: ocr_reader — 本地OCR文字识别"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "ocr_reader",
    "description": "本地OCR文字识别：支持图片/PDF文字提取，优先使用RapidOCR/PaddleOCR，无需联网。",
    "category": "productivity",
    "version": "1.0.0",
}


def execute(image_path: str = "", lang: str = "ch", output_format: str = "text", **kwargs) -> SkillResult:
    if not image_path:
        return SkillResult(success=False, error="image_path 参数为空")

    path = os.path.expanduser(image_path)
    if not os.path.isfile(path):
        return SkillResult(success=False, error=f"文件不存在: {path}")

    ext = os.path.splitext(path)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".pdf", ".webp"):
        return SkillResult(success=False, error=f"不支持的格式: {ext}")

    ocr = _lazy_ocr()
    if ocr is None:
        return SkillResult(
            success=False,
            error="OCR引擎未安装",
            output="请执行: pip install rapidocr-onnxruntime 或 paddleocr",
        )

    try:
        if ext == ".pdf":
            result_lines = _ocr_pdf(ocr, path, lang)
        else:
            result_lines = _ocr_image(ocr, path, lang)

        if output_format == "json":
            text = str(result_lines)
        else:
            text = "\n".join(result_lines)

        return SkillResult(
            success=True,
            output=f"OCR识别结果 ({os.path.basename(path)}):\n{text}",
            data={"text": text, "line_count": len(result_lines),
                  "source": os.path.basename(path)},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"OCR识别失败: {e}")


def _lazy_ocr():
    for lib in ("rapidocr_onnxruntime", "paddleocr"):
        try:
            mod = __import__(lib)
            if lib == "rapidocr_onnxruntime":
                return mod.RapidOCR()
            else:
                return mod.PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        except ImportError:
            continue
    return None


def _ocr_image(ocr, path: str, lang: str) -> list:
    if hasattr(ocr, 'read'):
        result, _ = ocr.read(path)
        return [line[1] for line in result] if result else []
    # ★ 378-1：新版 rapidocr_onnxruntime（>=1.3）RapidOCR 实例没有 .ocr 方法，
    #   直接以实例调用：ocr(img) → [ [box, text, score], ... ]。
    #   旧代码硬编码 ocr.ocr(path, cls=True) 会 AttributeError"object has no
    #   attribute 'ocr'"，被上层误报为"OCR引擎未安装"。
    try:
        result = ocr(path)
    except TypeError:
        result = ocr.ocr(path)
    if not result:
        return []
    # 新版结构：[ [box, text, score], ... ]
    first = result[0]
    if isinstance(first, (list, tuple)) and len(first) >= 2 and isinstance(first[1], str):
        return [line[1] for line in result]
    # 旧版结构：[ [ [box, (text, score)], ... ], ... ]
    if isinstance(first, (list, tuple)) and first and isinstance(first[0], (list, tuple)):
        return [line[1][0] for line in result[0]]
    return []


def _ocr_pdf(ocr, path: str, lang: str) -> list:
    lines = []
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(path, dpi=200)
        for img in images:
            tmp_path = path + ".tmp_ocr.png"
            img.save(tmp_path)
            lines.extend(_ocr_image(ocr, tmp_path, lang))
            os.remove(tmp_path)
    except ImportError:
        return ["[PDF OCR需要pdf2image: pip install pdf2image]"]
    return lines


def register(registry) -> None:
    registry.register(SkillDef(
        name="ocr_reader",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "图片/PDF文件路径"},
                "lang": {"type": "string", "description": "OCR语言(ch/en/ja/ko等)", "default": "ch"},
                "output_format": {"type": "string", "enum": ["text", "json"], "default": "text"},
            },
            "required": ["image_path"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=120,
    ))


def get_metadata():
    return METADATA
