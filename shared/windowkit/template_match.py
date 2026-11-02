"""模板匹配定位。

基于 OpenCV matchTemplate，模板图存放于 vizboard/assets/templates/。
返回匹配在「截图内像素坐标」以及换算后的「窗口归一化客户坐标」，
供 input_sim.click 直接消费 —— 形成 看→定→做 闭环。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .exceptions import TemplateMatchError

# 模板默认目录：vizboard/assets/templates/
# __file__ = shared/windowkit/template_match.py -> dirname x3 得到项目根（lemon_agent）
_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "vizboard", "assets", "templates",
)


@dataclass
class Match:
    """单个模板命中。"""

    x: int            # 命中中心在截图内的像素 x
    y: int            # 命中中心在截图内的像素 y
    confidence: float

    def to_tuple(self) -> Tuple[int, int]:
        return (self.x, self.y)


def list_templates(template_dir: str = _TEMPLATE_DIR) -> List[str]:
    """列出可用模板文件名。"""
    if not os.path.isdir(template_dir):
        return []
    return sorted(
        f for f in os.listdir(template_dir)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))
    )


def match_template(
    image,
    template,
    threshold: float = 0.8,
) -> List[Match]:
    """在 image(numpy BGR) 中匹配 template(numpy BGR)，返回置信度≥阈值的命中。

    多目标：对重叠框做非极大值抑制。
    """
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise TemplateMatchError("缺少 opencv-python / numpy：%s" % exc)

    if image is None or template is None:
        raise TemplateMatchError("image 或 template 为空")
    if image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
        return []

    res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    th, tw = template.shape[:2]
    raw: List[Match] = []
    for pt in zip(*loc[::-1]):
        raw.append(Match(x=int(pt[0] + tw / 2), y=int(pt[1] + th / 2),
                         confidence=float(res[pt[1], pt[0]])))
    return _nms(raw, th, tw)


def _nms(matches: List[Match], th: int, tw: int) -> List[Match]:
    """按置信度做非极大值抑制，避免同一目标多框。"""
    if not matches:
        return []
    matches.sort(key=lambda m: m.confidence, reverse=True)
    kept: List[Match] = []
    for m in matches:
        if all(abs(m.x - k.x) > tw / 2 or abs(m.y - k.y) > th / 2 for k in kept):
            kept.append(m)
    return kept


def match_template_in_window(
    hwnd: int,
    template_path: str,
    threshold: float = 0.8,
    topk: int = 0,
) -> List[Tuple[float, float, float]]:
    """对窗口抓图做模板匹配，返回窗口客户区归一化坐标 + 置信度。

    返回元素为 (nx, ny, confidence) 三元组（K11：confidence 来自
    matchTemplate 的 TM_CCOEFF_NORMED 最大值，写入 VisualLandmark.confidence）。
    topk>0 时仅保留置信度最高的前 topk 个（默认 0 = 全部）。
    依赖 capture.capture_window 与 numpy/cv2。
    """
    from . import capture as _cap

    result = _cap.capture_window(hwnd, client_only=True)
    import cv2
    import numpy as np

    template = cv2.imread(template_path)
    if template is None:
        raise TemplateMatchError("无法读取模板：%s" % template_path)
    img = result.numpy()
    matches = match_template(img, template, threshold)
    if not matches:
        return []
    # 截图即客户区像素，直接用截图尺寸推算归一化坐标
    norm: List[Tuple[float, float, float]] = []
    for m in matches:
        nx = m.x / max(1, result.width)
        ny = m.y / max(1, result.height)
        norm.append((nx, ny, m.confidence))
    # 按置信度降序（match_template 已 NMS 但顺序未必严格）
    norm.sort(key=lambda t: t[2], reverse=True)
    if topk and topk > 0:
        norm = norm[:topk]
    return norm


def ensure_template_dir(template_dir: str = _TEMPLATE_DIR) -> str:
    """确保模板目录存在，返回路径。"""
    os.makedirs(template_dir, exist_ok=True)
    return template_dir


# ---------------------------------------------------------------------------
# 内存模板注册表（K4：scan_templates 自动注册，免改代码即可匹配新增 PNG）
# ---------------------------------------------------------------------------
_REGISTRY: Dict[str, object] = {}  # name -> numpy BGR 图像


def register_template(name: str, image) -> None:
    """把一个已读入的模板图（numpy BGR）按 name 注册到内存库。"""
    _REGISTRY[name] = image


def find(name: str):
    """按 name 取回已注册模板图（numpy 数组）；未注册返回 None。"""
    return _REGISTRY.get(name)


def list_registered() -> List[str]:
    """列出当前已注册模板名。"""
    return list(_REGISTRY.keys())


def normalize_coords(matches, width: int, height: int) -> List[Tuple[float, float]]:
    """把命中中心像素坐标换算为窗口客户区归一化坐标 (nx, ny) ∈ [0,1]。

    供 看→定→做 闭环统一消费（与 capture.match_template_in_window 同算法）。
    """
    out: List[Tuple[float, float]] = []
    for m in matches:
        out.append((m.x / max(1, width), m.y / max(1, height)))
    return out


def match_template_by_name(image, name: str, threshold: float = 0.8):
    """在 image 中匹配已注册模板 name（来自 scan_templates）。

    未注册时抛 TemplateMatchError，提示先调用 scan_templates。
    """
    tpl = find(name)
    if tpl is None:
        raise TemplateMatchError("模板未注册：%s（请先 scan_templates）" % name)
    return match_template(image, tpl, threshold)
