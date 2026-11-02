import io
import os
import tempfile

from .models import SkillResult, SkillDef

METADATA = {
    "name": "image_processor",
    "version": "1.0.0",
    "category": "vision",
    "description": "Basic image processing: resize, crop, grayscale, blur.",
}


def execute(image_url: str, operation: str = "resize", params: dict = None, **kwargs) -> SkillResult:
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        return SkillResult.fail("Pillow is not installed. Install with: pip install Pillow")

    if params is None:
        params = {}

    try:
        if image_url.startswith(("http://", "https://")):
            try:
                import requests
                resp = requests.get(image_url, timeout=15)
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content))
            except Exception as e:
                return SkillResult.fail(f"Failed to download image: {e}")
        else:
            if not os.path.exists(image_url):
                return SkillResult.fail(f"Image file not found: {image_url}")
            img = Image.open(image_url)

        if operation == "resize":
            w = int(params.get("width", img.width // 2))
            h = int(params.get("height", img.height // 2))
            img = img.resize((w, h), Image.LANCZOS)
        elif operation == "crop":
            left = int(params.get("left", 0))
            top = int(params.get("top", 0))
            right = int(params.get("right", img.width))
            bottom = int(params.get("bottom", img.height))
            img = img.crop((left, top, right, bottom))
        elif operation == "grayscale":
            img = img.convert("L")
        elif operation == "blur":
            radius = int(params.get("radius", 2))
            img = img.filter(ImageFilter.GaussianBlur(radius=radius))
        else:
            return SkillResult.fail(f"Unknown operation: {operation}. Use resize/crop/grayscale/blur.")

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=tempfile.gettempdir())
        tmp_path = tmp.name
        tmp.close()
        img.save(tmp_path)

        return SkillResult.ok(output=tmp_path, data={"file_path": tmp_path, "format": "png", "operation": operation})
    except ImportError:
        return SkillResult.fail("requests is not installed for URL-based images. Install with: pip install requests")
    except Exception as e:
        return SkillResult.fail(f"Image processing error: {e}")


def register(registry) -> None:
    registry.register(SkillDef(
        name="image_processor",
        description="[DEPRECATED] Use business.image_processor instead. Legacy 4-op processor (resize/crop/grayscale/blur).",
        category="vision",
        parameters={
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "description": "URL or local file path of the image",
                },
                "operation": {
                    "type": "string",
                    "enum": ["resize", "crop", "grayscale", "blur"],
                    "description": "Operation to perform",
                },
                "params": {
                    "type": "object",
                    "description": "Parameters for the operation (e.g. width/height for resize, radius for blur)",
                },
            },
            "required": ["image_url"],
        },
        handler=execute,
        timeout=30,
        deprecated=True,
        deprecation_message="Superseded by business.image_processor (7 ops: info/resize/rotate/filter/convert/composite/OCR + EasyOCR).",
    ))
