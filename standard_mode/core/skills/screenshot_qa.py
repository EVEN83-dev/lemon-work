# -*- coding: utf-8 -*-
"""Skill: screenshot_qa — 截图理解问答"""

import sys, os, base64, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "screenshot_qa",
    "description": "截图理解问答：截取屏幕/窗口并提问，支持保存截图。纯只读。",
    "category": "productivity",
    "version": "1.0.0",
}


def execute(action: str = "capture", question: str = "",
            save_path: str = "", region: str = "fullscreen") -> SkillResult:
    if action == "capture":
        img_data = _capture_screenshot(region)
        if img_data is None:
            return SkillResult(
                success=False,
                error="截图工具均不可用，请安装 mss 或 pillow",
                data={"hint": "pip install mss"},
            )

        if save_path:
            sp = os.path.expanduser(save_path)
            with open(sp, "wb") as f:
                f.write(img_data)
            return SkillResult(
                success=True,
                output=f"截图已保存: {sp} ({len(img_data)} bytes)",
                data={"action": "capture", "save_path": sp, "size": len(img_data)},
            )

        return SkillResult(
            success=True,
            output=f"截图完成 ({len(img_data)} bytes, {region})。请提问以分析截图内容。",
            data={"action": "capture", "size": len(img_data), "region": region},
        )

    if action == "describe":
        if not question:
            question = "请描述这张截图的内容"
        return SkillResult(
            success=True,
            output=f"[截图问答] 问题: {question}\n(需要多模态模型支持，当前为占位实现)",
            data={"action": "describe", "question": question},
        )

    return SkillResult(success=False, error=f"未知操作: {action}")


def _capture_screenshot(region: str) -> bytes:
    """截图三级兜底（378-2）：a. mss → b. Pillow ImageGrab → c. PowerShell。
    全部失败返回 None，由调用方返回明确的安装 hint（不再笼统报"无可用工具"）。
    """
    # a. mss（多显示器/速度快；若已安装优先）
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            monitor = sct.monitors[1] if region != "all" else sct.monitors[0]
            raw = sct.grab(monitor)
            return mss.tools.to_png(raw.rgb, raw.size)
    except ImportError:
        pass
    except Exception:
        pass

    # b. Pillow ImageGrab（Windows 内置截图 API，pillow 已随 378-1 安装）
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        pass
    except Exception:
        pass

    try:
        tmp = tempfile.mktemp(suffix=".png")
        result = subprocess.run(
            ["powershell", "-Command",
             f"Add-Type -AssemblyName System.Windows.Forms; "
             f"[System.Windows.Forms.Screen]::PrimaryScreen | Out-Null; "
             f"$bmp = New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); "
             f"$g = [System.Drawing.Graphics]::FromImage($bmp); "
             f"$g.CopyFromScreen(0,0,0,0,$bmp.Size); "
             f"$bmp.Save('{tmp}'); $g.Dispose(); $bmp.Dispose()"],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if os.path.isfile(tmp):
            with open(tmp, "rb") as f:
                data = f.read()
            os.remove(tmp)
            return data
    except Exception:
        pass

    return None


def register(registry) -> None:
    registry.register(SkillDef(
        name="screenshot_qa",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["capture", "describe"],
                           "description": "操作类型", "default": "capture"},
                "question": {"type": "string", "description": "关于截图的问题"},
                "save_path": {"type": "string", "description": "截图保存路径"},
                "region": {"type": "string", "enum": ["fullscreen", "window"],
                           "description": "截图区域", "default": "fullscreen"},
            },
            "required": [],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata():
    return METADATA
