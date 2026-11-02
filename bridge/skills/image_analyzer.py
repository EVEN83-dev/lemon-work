import os
import struct
import hashlib
from .models import SkillResult, SkillDef

METADATA = {
    "name": "image_analyzer",
    "version": "2.0.0",
    "category": "vision",
    "description": "Analyze images: metadata extraction, color analysis, histogram. Falls back to file metadata if Pillow unavailable.",
}


def execute(image_path: str = "", image_url: str = "", question: str = "", **kwargs) -> SkillResult:
    source = image_path or image_url or kwargs.get("image", "")
    if not source:
        return SkillResult.fail("image_path or image_url is required")

    if source.startswith(("http://", "https://")):
        return _analyze_url(source, question)
    elif os.path.exists(source):
        return _analyze_local(source, question)
    else:
        return SkillResult.fail("Image not found: " + source[:100])


def _analyze_local(path: str, question: str) -> SkillResult:
    try:
        from PIL import Image
    except ImportError:
        return _analyze_local_fallback(path, question)

    try:
        img = Image.open(path)
        file_size = os.path.getsize(path)

        info = {
            "path": path,
            "format": img.format or "unknown",
            "mode": img.mode,
            "width": img.width,
            "height": img.height,
            "file_size": file_size,
            "aspect_ratio": round(img.width / max(1, img.height), 3),
            "megapixels": round(img.width * img.height / 1_000_000, 2),
        }

        color_info = _analyze_colors(img)
        info.update(color_info)

        output = _build_pillow_report(info, question)

        return SkillResult.ok(
            output=output,
            data={"needs_llm": False, "image_info": info, "question": question},
        )
    except Exception as e:
        return _analyze_local_fallback(path, question, str(e))


def _analyze_local_fallback(path: str, question: str, error: str = "") -> SkillResult:
    info = _extract_file_metadata(path)
    output = _build_fallback_report(info, question, error)
    return SkillResult.ok(
        output=output,
        data={"needs_llm": False, "image_path": path, "question": question, "mode": "file_metadata", "file_info": info},
    )


def _extract_file_metadata(path: str) -> dict:
    info = {
        "path": path,
        "file_size": 0,
        "filename": os.path.basename(path),
        "extension": os.path.splitext(path)[1].lower(),
        "md5": "",
        "sha256": "",
        "width": None,
        "height": None,
        "format": "unknown",
    }

    try:
        stat = os.stat(path)
        info["file_size"] = stat.st_size
        info["modified"] = stat.st_mtime
        info["created"] = stat.st_ctime
    except OSError:
        pass

    try:
        with open(path, "rb") as f:
            data = f.read()
            info["md5"] = hashlib.md5(data).hexdigest()
            info["sha256"] = hashlib.sha256(data).hexdigest()
            info["format"] = _detect_image_format(data)
            dims = _read_dimensions_from_header(data, info["format"])
            if dims:
                info["width"] = dims[0]
                info["height"] = dims[1]
    except OSError:
        pass

    return info


def _detect_image_format(data: bytes) -> str:
    if len(data) < 12:
        return "unknown"
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "PNG"
    if data[:2] == b'\xff\xd8':
        return "JPEG"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "WEBP"
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return "GIF"
    if data[:4] == b'II\x2a\x00' or data[:4] == b'MM\x00\x2a':
        return "TIFF"
    if data[:2] == b'BM':
        return "BMP"
    if data[:4] == b'\x00\x00\x01\x00':
        return "ICO"
    if data[:4] == b'\x00\x00\x02\x00':
        return "CUR"
    return "unknown"


def _read_dimensions_from_header(data: bytes, fmt: str):
    try:
        if fmt == "PNG" and len(data) >= 24:
            w = struct.unpack(">I", data[16:20])[0]
            h = struct.unpack(">I", data[20:24])[0]
            return (w, h)
        if fmt == "JPEG":
            i = 2
            while i < len(data) - 1:
                if data[i] != 0xFF:
                    break
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    if i + 9 < len(data):
                        h = struct.unpack(">H", data[i + 5:i + 7])[0]
                        w = struct.unpack(">H", data[i + 7:i + 9])[0]
                        return (w, h)
                if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9):
                    i += 2
                elif i + 3 < len(data):
                    length = struct.unpack(">H", data[i + 2:i + 4])[0]
                    i += 2 + length
                else:
                    break
        if fmt == "GIF" and len(data) >= 10:
            w = struct.unpack("<H", data[6:8])[0]
            h = struct.unpack("<H", data[8:10])[0]
            return (w, h)
        if fmt == "BMP" and len(data) >= 26:
            w = struct.unpack("<I", data[18:22])[0]
            h = struct.unpack("<I", data[22:26])[0]
            return (w, h)
    except (struct.error, IndexError):
        pass
    return None


def _analyze_url(url: str, question: str) -> SkillResult:
    try:
        import requests
        import tempfile
        from PIL import Image

        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, dir=tempfile.gettempdir())
        tmp.write(resp.content)
        tmp.close()

        result = _analyze_local(tmp.name, question)
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        if result.data and isinstance(result.data, dict):
            result.data["url"] = url
        return result
    except ImportError:
        return _analyze_url_fallback(url, question)
    except Exception as e:
        return _analyze_url_fallback(url, question, str(e))


def _analyze_url_fallback(url: str, question: str, error: str = "") -> SkillResult:
    from urllib.parse import urlparse, unquote
    parsed = urlparse(url)
    filename = unquote(os.path.basename(parsed.path)) or "unknown"
    ext = os.path.splitext(filename)[1].lower()

    format_guess = _ext_to_format(ext)
    domain = parsed.hostname or "unknown"

    output = (
        "=== Image Analysis (URL Metadata Mode) ===\n"
        "\n"
        "URL: " + url + "\n"
        "Filename: " + filename + "\n"
        "Domain: " + domain + "\n"
        "Detected Format: " + format_guess + "\n"
        "Extension: " + ext + "\n"
    )
    if error:
        output += "Download Error: " + error + "\n"
    output += (
        "\n"
        "Question: " + question + "\n"
        "\n"
        "Note: Pillow/requests not available. Only URL-derived metadata provided.\n"
        "Install Pillow and requests for full image analysis."
    )

    return SkillResult.ok(
        output=output,
        data={"needs_llm": False, "image_url": url, "question": question, "mode": "url_metadata", "format_guess": format_guess},
    )


def _ext_to_format(ext: str) -> str:
    mapping = {
        ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".gif": "GIF",
        ".bmp": "BMP", ".webp": "WEBP", ".tiff": "TIFF", ".tif": "TIFF",
        ".ico": "ICO", ".svg": "SVG", ".avif": "AVIF", ".heic": "HEIC",
    }
    return mapping.get(ext, "unknown")


def _analyze_colors(img) -> dict:
    result = {"dominant_colors": [], "brightness": "unknown", "is_grayscale": False}

    try:
        if img.mode in ("L", "1"):
            result["is_grayscale"] = True
            pixels = list(img.getdata())
            avg = sum(pixels) / max(1, len(pixels))
            if avg < 85:
                result["brightness"] = "dark"
            elif avg > 170:
                result["brightness"] = "bright"
            else:
                result["brightness"] = "medium"
            return result

        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        small = img.resize((50, 50))
        pixels = list(small.getdata())

        color_buckets = {}
        total_brightness = 0
        for p in pixels:
            r, g, b = p[0], p[1], p[2]
            total_brightness += (r + g + b) / 3
            qr = (r // 64) * 64
            qg = (g // 64) * 64
            qb = (b // 64) * 64
            key = (qr, qg, qb)
            color_buckets[key] = color_buckets.get(key, 0) + 1

        sorted_colors = sorted(color_buckets.items(), key=lambda x: -x[1])[:5]
        result["dominant_colors"] = [
            {"rgb": list(c[0]), "count": c[1], "hex": "#%02x%02x%02x" % c[0]}
            for c in sorted_colors
        ]

        avg_brightness = total_brightness / max(1, len(pixels))
        if avg_brightness < 85:
            result["brightness"] = "dark"
        elif avg_brightness > 170:
            result["brightness"] = "bright"
        else:
            result["brightness"] = "medium"

        is_gray = all(abs(p[0] - p[1]) < 15 and abs(p[1] - p[2]) < 15 for p in pixels[:100] if len(p) >= 3)
        result["is_grayscale"] = is_gray

    except Exception:
        pass

    return result


def _build_pillow_report(info: dict, question: str) -> str:
    parts = [
        "=== Image Analysis ===",
        "",
        "Path: " + str(info["path"]),
        "Format: " + str(info["format"]),
        "Mode: " + str(info["mode"]),
        "Dimensions: " + str(info["width"]) + " x " + str(info["height"]),
        "Aspect Ratio: " + str(info["aspect_ratio"]),
        "Megapixels: " + str(info["megapixels"]),
        "File Size: " + str(info["file_size"]) + " bytes",
        "",
    ]

    if info.get("dominant_colors"):
        parts.append("[Dominant Colors]")
        for c in info["dominant_colors"]:
            parts.append("  " + c["hex"] + " (rgb: " + str(c["rgb"]) + ", pixels: " + str(c["count"]) + ")")
        parts.append("")

    parts.append("Brightness: " + str(info.get("brightness", "unknown")))
    parts.append("Is Grayscale: " + str(info.get("is_grayscale", False)))

    if info.get("is_grayscale"):
        parts.append("")
        parts.append("Note: Image appears to be grayscale.")
    if info.get("brightness") == "dark":
        parts.append("")
        parts.append("Note: Image appears to be dark/underexposed.")
    elif info.get("brightness") == "bright":
        parts.append("")
        parts.append("Note: Image appears to be bright/overexposed.")

    parts.append("")
    parts.append("Question: " + question)

    return "\n".join(parts)


def _build_fallback_report(info: dict, question: str, error: str = "") -> str:
    parts = [
        "=== Image Analysis (File Metadata Mode) ===",
        "",
        "Path: " + str(info.get("path", "N/A")),
        "Filename: " + str(info.get("filename", "N/A")),
        "Extension: " + str(info.get("extension", "N/A")),
        "Detected Format: " + str(info.get("format", "unknown")),
        "File Size: " + str(info.get("file_size", 0)) + " bytes",
    ]

    if info.get("width") is not None and info.get("height") is not None:
        parts.append("Dimensions: " + str(info["width"]) + " x " + str(info["height"]))
        ratio = round(info["width"] / max(1, info["height"]), 3)
        parts.append("Aspect Ratio: " + str(ratio))
        parts.append("Megapixels: " + str(round(info["width"] * info["height"] / 1_000_000, 2)))
    else:
        parts.append("Dimensions: Could not determine (header parsing failed)")

    if info.get("md5"):
        parts.append("MD5: " + info["md5"])
    if info.get("sha256"):
        parts.append("SHA256: " + info["sha256"])
    if info.get("modified"):
        import time
        parts.append("Last Modified: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info["modified"])))

    if error:
        parts.append("")
        parts.append("Pillow Error: " + error)

    parts.append("")
    parts.append("Question: " + question)
    parts.append("")
    parts.append("Note: Pillow not available. Analysis based on file metadata and binary header parsing.")
    parts.append("Install Pillow for full color analysis and image content inspection.")

    return "\n".join(parts)


def register(registry) -> None:
    registry.register(SkillDef(
        name="image_analyzer",
        description="Analyze images: extract metadata, color analysis, brightness detection. Supports local files and URLs. Falls back to file metadata mode if Pillow not installed.",
        category="vision",
        parameters={
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Local file path of the image",
                },
                "image_url": {
                    "type": "string",
                    "description": "URL of the image to analyze",
                },
                "question": {
                    "type": "string",
                    "description": "Question to ask about the image",
                },
            },
        },
        handler=execute,
        timeout=30,
    ))
