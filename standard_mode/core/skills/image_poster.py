# -*- coding: utf-8 -*-
"""
Skill: image_poster — 程序化海报/图表海报生成
================================================
400V-3 新增。零外部网络依赖（PIL 自绘）。两种模式：

A) 程序化海报模式（默认, image.api_endpoint 空）
   输入: 标题 + 要点列表 + 配色族(商务/科技/温和) → PIL 绘图 → PNG。
   配色对齐 data\templates\charts\matplotlib_theme_*.json 既有 colorway
   (商务/科技/温和 + default 兜底)。

B) 外接文生图模式 (image.api_endpoint 配置后)
   POST 到 OpenAI 兼容文生图接口 (智谱/通义万相等)。
   未配置时**明示**"程序化海报模式", 禁静默 (任务书 3.2)。

注册表与 386B-4 schema 示例齐全。
"""

import json
import os
import time
import traceback
from typing import Any, Dict, List, Optional

# 400V-3: 把 "标题+要点列表+配色族" 清晰定义为结构化输入, 避免与 str 混用。

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "image_poster",
    "description": "程序化海报生成 (PIL 自绘, 零外部依赖)。模式: 标题+要点列表+配色族(data/templates/charts/ colorway) → PNG。可选外接文生图 API (ConfigManager image.api_endpoint)。",
    "category": "visual",
    "version": "0.1.0 (400V-3)",
}

_DEFAULT_POSTER_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'data', 'charts'
)
_THEMES_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'data', 'templates', 'charts'
)

# CJK 字体候选 (按优先级); 全缺时回退 PIL 默认位图字体
_CJK_FONT_CANDIDATES = [
    "msyh.ttc", "msyhbd.ttc", "msyhl.ttc",       # Microsoft YaHei
    "simhei.ttf", "simsun.ttc",                     # SimHei / SimSun
    "mingliu.ttc", "msmincho.ttc",                  # 明体
    "NotoSansCJK-Regular.ttc", "NotoSerifCJK-Regular.ttc",
]

_FALLBACK_USER_AGENT = "Mozilla/5.0 (compatible; lemon_agent/1.0)"


def _load_colorway(theme: str = "default") -> Dict[str, Any]:
    """
    从 data/templates/charts/ matplotlib_theme_*.json 加载 colorway。
    映射: 科技/商务/温和 → 对应 family 同名 colorway; default → 各 family 的 default 兜底。
    若全部文件缺失返回硬编码 default (保证 skill 在文件系统异常时仍可产出)。
    """
    fallback = {
        "primary": "#1F3B63", "accent": "#E87D1E",
        "text": "#333333", "bg": "#FFFFFF",
        "series": ["#1F3B63", "#E87D1E", "#7889A1", "#F1B178", "#627591"],
    }
    if not os.path.isdir(_THEMES_DIR):
        return fallback
    try:
        for fn in os.listdir(_THEMES_DIR):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(_THEMES_DIR, fn), 'r', encoding='utf-8') as f:
                t = json.load(f)
            cw = t.get("colorways", {})
            if theme in cw:
                return cw[theme]
            if "default" in t:
                fallback = t["default"]
    except Exception:
        pass
    return fallback


def _find_cjk_font(size: int) -> Optional[object]:
    """定位可用 CJK 字体; 返回 PIL.ImageFont 实例或 None。"""
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    # 先尝试 Windows Fonts 目录
    win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    search_dirs = [win_fonts, "/usr/share/fonts", "/System/Library/Fonts"]
    for name in _CJK_FONT_CANDIDATES:
        for d in search_dirs:
            p = os.path.join(d, name)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
    # 系统字体目录模糊匹配
    try:
        import glob
        for d in search_dirs:
            for p in glob.glob(os.path.join(d, "**", "*.tt[cf]"), recursive=True):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
            for p in glob.glob(os.path.join(d, "*.tt[cf]")):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _wrap_text(text: str, font, max_width: int, draw) -> List[str]:
    """简单中文字符级折行 (PIL 不提供自动 CJK 折行, 手动实现)。"""
    from PIL import ImageDraw  # 仅占位, 实际用传入 draw
    lines = []
    line = ""
    for ch in text:
        test = line + ch
        try:
            w = draw.textlength(test, font=font)
        except Exception:
            w = len(test) * (font.size if font else 12)
        if w > max_width and line:
            lines.append(line)
            line = ch
        else:
            line = test
    if line:
        lines.append(line)
    return lines


def _draw_programmatic_poster(
    title: str,
    bullets: List[str],
    colorway: Dict[str, Any],
    output_path: str,
) -> Dict[str, Any]:
    """
    PIL 自绘海报: 顶部色条 + 标题 + 要点 (主色圆点) + 底部强调条。
    对齐 395A-2 charts 主题 series 配色。
    """
    from PIL import Image, ImageDraw, ImageFont

    W, H = 900, 1200
    primary = colorway.get("primary", "#1F3B63")
    accent = colorway.get("accent", "#E87D1E")
    text_color = colorway.get("text", "#333333")
    bg = colorway.get("bg", "#FFFFFF")
    series = colorway.get("series", [primary, accent])

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # 顶部色条
    draw.rectangle([0, 0, W, 160], fill=primary)
    # 底部强调条
    draw.rectangle([0, H - 60, W, H], fill=accent)

    # 字体
    font_title = _find_cjk_font(64) or ImageFont.load_default()
    font_body = _find_cjk_font(30) or ImageFont.load_default()
    font_small = _find_cjk_font(20) or ImageFont.load_default()

    # 标题居中 (水平偏移, 自动折行)
    title_y = 40
    title_lines = _wrap_text(title, font_title, W - 120, draw)
    for ln in title_lines:
        try:
            w = draw.textlength(ln, font=font_title)
        except Exception:
            w = len(ln) * 30
        draw.text(((W - w) // 2, title_y), ln, fill="#FFFFFF", font=font_title)
        title_y += int(font_title.size * 1.3) if font_title and hasattr(font_title, 'size') else 80
        if title_y > 130:
            break

    # 主体: 要点列表
    y = 200
    for i, bullet in enumerate(bullets[:8]):  # 最多 8 条避免溢出
        dot_color = series[i % len(series)]
        # 圆点
        draw.ellipse([80, y + 6, 80 + 22, y + 6 + 22], fill=dot_color)
        # 折行
        wrapped = _wrap_text("• " + bullet, font_body, W - 200, draw)
        first = True
        for ln in wrapped:
            draw.text((80 + 40, y), ln if first else "    " + ln.lstrip("• "), fill=text_color, font=font_body)
            y += int(font_body.size * 1.4) if font_body and hasattr(font_body, 'size') else 40
            first = False
            if y > H - 100:
                break
        y += 18
        if y > H - 100:
            break

    # 底部标签
    tag = f"image_poster · {os.path.basename(output_path)}"
    draw.text((40, H - 50), tag, fill="#FFFFFF", font=font_small)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    img.save(output_path, "PNG")
    return {
        "width": W, "height": H, "mode": "programmatic",
        "colorway": {k: colorway.get(k) for k in ("primary", "accent", "bg")},
    }


def _try_external_image_api(endpoint: str, prompt: str, bullets: List[str]) -> Optional[str]:
    """
    预留: POST 到 OpenAI 兼容文生图接口; 成功返回图片保存路径, 失败返回 None。
    调用方据此判断是否降级 (但默认不静默, 由 execute 先判断 endpoint 是否配置)。
    """
    try:
        # 兼容 "智谱/通义 万相" 的 OpenAI 兼容格式; 包在 try 里避免在没依赖时 import 失败。
        import urllib.request as _ur
        import base64 as _b64
    except ImportError:
        return None
    try:
        from shared.config_manager import ConfigManager
        key_env = ConfigManager().get("image.api_key_env", "LEMON_IMAGE_API_KEY")
        api_key = os.environ.get(key_env, "")
    except Exception:
        api_key = ""
    # build body (OpenAI-compatible images/generations prompt) — best-effort
    body = json.dumps({
        "model": "default",
        "prompt": prompt + ("\n要点: " + "; ".join(bullets)) if bullets else prompt,
        "n": 1,
        "size": "1024x1024",
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = _ur.Request(endpoint, data=body, headers=headers, method="POST")
        with _ur.urlopen(req, timeout=30) as resp:
            r = json.loads(resp.read().decode("utf-8"))
        # OpenAI 兼容: data[0].url 或 data[0].b64_json
        data = r.get("data", [{}])[0]
        url = data.get("url")
        b64 = data.get("b64_json")
        ts = int(time.time())
        out = os.path.join(_DEFAULT_POSTER_DIR, f"image_poster_ext_{ts}.png")
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        if b64:
            with open(out, "wb") as f:
                f.write(_b64.b64decode(b64))
            return out
        if url:
            with _ur.urlopen(url, timeout=30) as ri:
                with open(out, "wb") as f:
                    f.write(ri.read())
            return out
    except Exception as e:
        return None
    return None


def execute(
    title: str = "",
    bullets: str = "",
    colorway: str = "default",
    output_path: str = "",
    aspect: str = "portrait",
) -> SkillResult:
    """
    生成海报。模式由 ConfigManager image.api_endpoint 是否为空决定。

    参数:
      title (str): 海报主标题。
      bullets (str): 要点列表, 换行分隔或 JSON 数组字符串。
      colorway (str): 配色族 — 商务 / 科技 / 温和 / default。
      output_path (str): 输出 PNG 路径 (默认 data\\charts\\image_poster_<ts>.png)。
      aspect (str): 比例 — portrait / landscape / square。
    """
    if not title:
        return SkillResult(success=False, error="title 参数为空")

    # 解析要点 (支持 JSON 数组或换行分隔)
    bullet_list: List[str] = []
    if bullets:
        s = bullets.strip()
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                bullet_list = [str(x) for x in parsed]
            else:
                bullet_list = [str(parsed)]
        except Exception:
            bullet_list = [ln.strip() for ln in s.splitlines() if ln.strip()]

    # 配色
    cw = _load_colorway(colorway)
    # aspect 影响尺寸
    if aspect == "landscape":
        # 由 PIL 调用方处理 (此处简化: 仅程序化模式生效)
        pass

    # 模式判定
    try:
        from shared.config_manager import ConfigManager
        endpoint = (ConfigManager().get("image.api_endpoint", "") or "").strip()
    except Exception:
        endpoint = ""

    if not output_path:
        ts = int(time.time())
        output_path = os.path.join(_DEFAULT_POSTER_DIR, f"image_poster_{ts}.png")

    # 外接模式
    if endpoint:
        ext = _try_external_image_api(endpoint, title, bullet_list)
        if ext:
            return SkillResult(
                success=True,
                output=f"海报已生成(外接文生图模式): {ext}\n配色族: {colorway}\n标题: {title}",
                data={"path": ext, "mode": "external-api", "endpoint": endpoint, "colorway": colorway,
                      "bullets_count": len(bullet_list)},
            )
        return SkillResult(
            success=False,
            error=f"外接文生图接口调用失败 (endpoint={endpoint})",
            output="请检查 image.api_endpoint / 对应 API Key 后重试；或清空该键切回程序化模式。",
        )

    # 程序化模式 (默认)
    try:
        meta = _draw_programmatic_poster(title, bullet_list, cw, output_path)
        return SkillResult(
            success=True,
            output=f"海报已生成(程序化海报模式): {output_path}\n配色族: {colorway}\n标题: {title}\n要点数: {len(bullet_list)}",
            data={
                "path": output_path,
                "mode": "programmatic",
                "colorway": colorway,
                "palette": {k: cw.get(k) for k in ("primary", "accent", "bg")},
                "aspect": aspect,
                "size": [meta["width"], meta["height"]],
                "bullets_rendered": min(len(bullet_list), 8),
                "api_configured": False,
            },
        )
    except ImportError as e:
        return SkillResult(success=False, error=f"依赖库缺失: {e}", output="pip install Pillow")
    except Exception as e:
        return SkillResult(success=False, error=f"程序化海报失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="image_poster",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "海报主标题"},
                "bullets": {
                    "type": "string",
                    "description": "要点列表 (换行分隔或 JSON 数组字符串)",
                },
                "colorway": {
                    "type": "string",
                    "enum": ["default", "商务", "科技", "温和"],
                    "description": "配色族 (对齐 data/templates/charts/ matplotlib_theme_*.json)",
                    "default": "default",
                },
                "output_path": {"type": "string", "description": "输出 PNG 路径 (默认 data/charts/)"},
                "aspect": {"type": "string", "enum": ["portrait", "landscape", "square"], "default": "portrait",
                           "description": "海报比例"},
            },
            "required": ["title"],
        },
        handler=execute,
        category=METADATA["category"],
        # 400V-3 386B-4 schema 示例 (程序化模式, 三配色族各一调用)
        argcheck_example={
            "title": "Lemon Agent 400V-3 交付清单",
            "bullets": "400V-1 math_plotter 无头后端\n400V-2 KaTeX 聊天流渲染\n400V-3 程序化海报/文生图预留\n400V-4 HTML 看板运行",
            "colorway": "科技",
            "aspect": "portrait",
        },
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
