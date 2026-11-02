# -*- coding: utf-8 -*-
"""
Skill: template_forge — 模板生产管线（394A-2；395A-1 场景化扩充）
================================================================
agent 算力产模板三段式：

    generate  场景描述 + 风格关键词 + scene → 批量生成 N 套候选版式骨架
              （场景化 5 件套）→ data/templates/_candidates/<批次>/
    confirm   筛选确认门：人工（或代选并如实标注）挑中候选 → 记入批次 manifest
    variants  中选候选扩展配色族 → 5件套×N配色 → 终稿入 data/templates/ppt/<族名>/
              + LICENSES.md 台账登记（自产）

395A-1 场景化：scene 参数选五件套构成（generic 保持 394 兼容）：
    generic           标题/章节/两栏/图表/结束（394 原样）
    academic_defense  标题/章节/公式页/图表页/结束（学术答辩，公式页重点）
    tech_sharing      标题/章节/代码页/架构图页/结束（技术分享）
    edu_training      标题/章节/讲义页/练习页/结束（教育培训）

所有产出均为自产资产（python-pptx MIT 生态惯用法），观感终审权在用户
（394 诚实条款：agent 自评不作数；公式页为占位文本框，最终公式由用户灌装）。
"""

import json
import os
import time
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
TPL_ROOT = os.path.join(_REPO_ROOT, "data", "templates")
CAND_ROOT = os.path.join(TPL_ROOT, "_candidates")
PPT_DIR = os.path.join(TPL_ROOT, "ppt")
LEDGER = os.path.join(TPL_ROOT, "LICENSES.md")

METADATA = {
    "name": "template_forge",
    "description": ("模板生产管线：场景+风格关键词+scene→批量候选场景化五件套→确认门筛选"
                    "→配色族变体→正式模板族入库并登记台账（自产资产；场景含"
                    "学术答辩/技术分享/教育培训）。"),
    "category": "office",
    "version": "1.0.0",
}

# 风格关键词 → 配色族（RGB hex）
PALETTES = {
    "商务": {"primary": "1F3B63", "accent": "E87D1E", "text": "333333", "bg": "FFFFFF"},
    "科技": {"primary": "0B2E4F", "accent": "22C0D6", "text": "222222", "bg": "FFFFFF"},
    "极简": {"primary": "2B2B2B", "accent": "8C8C8C", "text": "333333", "bg": "FAFAFA"},
    "活力": {"primary": "5B2A86", "accent": "F25C54", "text": "333333", "bg": "FFFFFF"},
    "自然": {"primary": "1E5B3A", "accent": "9CCB3B", "text": "2F2F2F", "bg": "FFFFFF"},
    "温和": {"primary": "6B4226", "accent": "D9A404", "text": "333333", "bg": "FFFDF7"},
}

# 场景 → 五件套版式构成（395A-1：generic 与 394 完全兼容，新增 3 个场景族）
SCENES = {
    "generic": {
        "desc": "通用商务五件套（394 原样）",
        "pieces": ["01_title", "02_section", "03_two_col", "04_chart", "05_end"],
    },
    "academic_defense": {
        "desc": "学术答辩（公式页重点：核心公式框+符号说明）",
        "pieces": ["01_title", "02_section", "03_formula", "04_chart", "05_end"],
    },
    "tech_sharing": {
        "desc": "技术分享（代码页+架构图页）",
        "pieces": ["01_title", "02_section", "03_code", "04_architecture", "05_end"],
    },
    "edu_training": {
        "desc": "教育培训（讲义页+练习页）",
        "pieces": ["01_title", "02_section", "03_lecture", "04_exercise", "05_end"],
    },
}


# 版式变体（候选间的布局差异维度）
LAYOUT_VARIANTS = [
    {"title_align": "left", "title_bar": True, "num_style": "block"},
    {"title_align": "center", "title_bar": False, "num_style": "outline"},
    {"title_align": "left", "title_bar": False, "num_style": "accent_line"},
    {"title_align": "center", "title_bar": True, "num_style": "block"},
    {"title_align": "left", "title_bar": True, "num_style": "outline"},
]


def _hex(color: str):
    from pptx.dml.color import RGBColor
    return RGBColor.from_string(color)


def _bg(slide, color):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def _textbox(slide, l, t, w, h, text, size, color, bold=False,
             align=None, bar=False, bar_color=None):
    from pptx.util import Inches, Pt
    if bar:
        from pptx.enum.shapes import MSO_SHAPE
        strip = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                       Inches(0), Inches(0),
                                       Inches(13.333), Inches(0.25))
        strip.fill.solid()
        strip.fill.fore_color.rgb = bar_color or color
        strip.line.fill.background()
    box = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = box.text_frame
    tf.text = text
    for p in tf.paragraphs:
        if align:
            p.alignment = align
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = color
    return box


def _rounded(slide, l, t, w, h, fill_rgb, line_rgb=None, line_w=1.5):
    """自产：圆角矩形容器（公式框/代码面板/架构块/作答区共用）。"""
    from pptx.util import Inches, Pt
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                 Inches(l), Inches(t), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill_rgb
    if line_rgb is not None:
        shp.line.color.rgb = line_rgb
        shp.line.width = Pt(line_w)
    else:
        shp.line.fill.background()
    return shp


def _style_shape_text(shp, text, size, color, bold=False, align=None,
                      font_name=None):
    """自产：给 shape 文本框统一着色（python-pptx MIT 生态惯用法）。"""
    from pptx.util import Pt
    tf = shp.text_frame
    tf.text = text
    for p in tf.paragraphs:
        if align:
            p.alignment = align
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = color
            if font_name:
                r.font.name = font_name
    return shp


def _build_5piece(out_path: str, palette: Dict, variant: Dict,
                  scenario: str, only: int = None,
                  scene: str = "generic") -> str:
    """生成场景化 5 件套（395A-1）。

    Args:
        only: None=完整五页；0..4=仅生成第几件（variants 终稿按件拆分用）。
        scene: generic（394 兼容）/ academic_defense / tech_sharing / edu_training。
    """
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.enum.text import PP_ALIGN
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE

    primary = _hex(palette["primary"])
    accent = _hex(palette["accent"])
    text = _hex(palette["text"])
    bgc = _hex(palette["bg"])
    talign = PP_ALIGN.CENTER if variant.get("title_align") == "center" else PP_ALIGN.LEFT
    bar = bool(variant.get("title_bar"))

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    def _page(idx):
        # 1 标题页
        if idx == 0:
            s = prs.slides.add_slide(prs.slide_layouts[6])
            _bg(s, primary)
            _textbox(s, 1.0, 2.6, 11.3, 1.4, f"{scenario}·[报告标题]", 40,
                     _hex("FFFFFF"), bold=True, align=talign)
            _textbox(s, 1.0, 4.2, 11.3, 0.8, "[副标题 / 一句话结论]", 20,
                     accent, align=talign)
            _textbox(s, 1.0, 6.4, 11.3, 0.5, "[汇报人] · [日期]", 14,
                     _hex("FFFFFF"), align=talign)
        # 2 章节页
        elif idx == 1:
            s = prs.slides.add_slide(prs.slide_layouts[6])
            _bg(s, bgc)
            num = variant.get("num_style", "block")
            if num == "block":
                _textbox(s, 0.9, 0.6, 2.0, 1.0, "01", 44, accent, bold=True)
                _textbox(s, 2.4, 0.9, 9.8, 0.9, "[章节标题]", 30, primary, bold=True)
            elif num == "outline":
                _textbox(s, 0.9, 0.55, 11.5, 0.9, "01  [章节标题]", 30, primary, bold=True)
            else:  # accent_line
                _textbox(s, 0.9, 0.6, 11.5, 0.9, "[章节标题]", 30, primary, bold=True)
                from pptx.enum.shapes import MSO_SHAPE
                ln = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.95),
                                        Inches(1.45), Inches(2.2), Inches(0.06))
                ln.fill.solid(); ln.fill.fore_color.rgb = accent
                ln.line.fill.background()
            _textbox(s, 0.9, 2.2, 11.5, 4.4, "[本章要点一]\n[本章要点二]\n[本章要点三]",
                     18, text)
        # 3 内容页（按 scene 分派：两栏/公式/代码/讲义）
        elif idx == 2:
            s = prs.slides.add_slide(prs.slide_layouts[6])
            _bg(s, bgc)
            if bar:
                _textbox(s, 0, 0, 0.1, 0.1, "", 1, bgc, bar=True, bar_color=primary)
            _textbox(s, 0.9, 0.6, 11.5, 0.8, "[页面标题]", 26, primary, bold=True)
            if scene == "academic_defense":
                # 公式页（重点页）：核心公式框 + 符号说明 + 定理编号
                fbox = _rounded(s, 1.6, 2.0, 10.1, 1.9, _hex("FFFFFF"), accent)
                _style_shape_text(fbox, "[核心公式：LaTeX 表达，如 y = β₀ + β₁x]",
                                  22, primary, bold=True, align=PP_ALIGN.CENTER)
                _textbox(s, 1.6, 4.3, 10.1, 1.2, "[符号与参数说明]", 16, text)
                _textbox(s, 1.6, 5.7, 10.1, 0.8, "[定理 / 引理编号与出处]", 13, accent)
            elif scene == "tech_sharing":
                # 代码页：深色代码面板 + 文件名标签 + 右侧解读
                panel = _rounded(s, 0.9, 1.7, 8.2, 5.0, _hex("1E1E1E"))
                _style_shape_text(panel, "[文件名 / 语言]\n[代码块：关键实现节选]",
                                  14, _hex("D4D4D4"), font_name="Consolas")
                _textbox(s, 9.4, 1.8, 3.0, 4.8, "[代码要点解读]", 15, text)
            elif scene == "edu_training":
                # 讲义页：知识点标签 + 讲解正文 + 板书区
                _textbox(s, 0.9, 1.6, 6.9, 0.6, "[知识点]", 16, accent, bold=True)
                _textbox(s, 0.9, 2.4, 6.9, 4.2, "[讲解正文：定义 / 步骤 / 例子]", 16, text)
                bbox = _rounded(s, 8.1, 1.7, 4.3, 4.9, _hex("FFFFFF"), primary, 1.2)
                _style_shape_text(bbox, "[板书区 / 图示]", 14,
                                  _hex("8C8C8C"), align=PP_ALIGN.CENTER)
            else:
                _textbox(s, 0.9, 1.8, 5.5, 4.6, "[左栏：现状/问题/文本要点]", 16, text)
                _textbox(s, 6.9, 1.8, 5.5, 4.6, "[右栏：方案/数据/对照要点]", 16, text)
        # 4 图表/架构/练习页（按 scene 分派）
        elif idx == 3:
            s = prs.slides.add_slide(prs.slide_layouts[6])
            _bg(s, bgc)
            if scene == "tech_sharing":
                # 架构图页：三层块 + 箭头 + 说明
                _textbox(s, 0.9, 0.6, 11.5, 0.8, "[架构图标题]", 26, primary, bold=True)
                layers = [("[入口层 / API]", 0.9), ("[服务层 / 业务逻辑]", 4.6),
                          ("[存储层 / 数据库]", 8.3)]
                for label, x in layers:
                    blk = _rounded(s, x, 2.7, 3.3, 1.7, _hex("FFFFFF"), primary, 1.5)
                    _style_shape_text(blk, label, 16, primary, bold=True,
                                      align=PP_ALIGN.CENTER)
                from pptx.enum.shapes import MSO_SHAPE
                for ax in (4.28, 7.98):
                    ar = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(ax),
                                            Inches(3.25), Inches(0.5), Inches(0.6))
                    ar.fill.solid(); ar.fill.fore_color.rgb = accent
                    ar.line.fill.background()
                _textbox(s, 0.9, 5.0, 11.5, 1.6, "[架构说明要点]", 15, text)
            elif scene == "edu_training":
                # 练习页：题目 + 作答区 + 提示
                _textbox(s, 0.9, 0.6, 11.5, 0.8, "[练习标题]", 26, primary, bold=True)
                _textbox(s, 0.9, 1.7, 11.5, 1.5, "[题目描述]", 16, text)
                abox = _rounded(s, 0.9, 3.3, 11.5, 2.6, _hex("FFFFFF"), accent, 1.2)
                _style_shape_text(abox, "[作答区]", 14, _hex("8C8C8C"),
                                  align=PP_ALIGN.CENTER)
                _textbox(s, 0.9, 6.1, 11.5, 0.7, "[提示 / 答案要点（写入备注栏）]", 12, accent)
            else:
                _textbox(s, 0.9, 0.6, 11.5, 0.8, "[数据结论标题]", 26, primary, bold=True)
                data = CategoryChartData()
                data.categories = ["Q1", "Q2", "Q3", "Q4"]
                data.add_series("系列A", (1.2, 2.4, 1.9, 3.1))
                data.add_series("系列B", (0.8, 1.6, 2.6, 2.2))
                s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,
                                   Inches(0.9), Inches(1.7), Inches(8.0), Inches(5.0), data)
                _textbox(s, 9.2, 2.0, 3.2, 4.2, "[图表解读要点]", 15, text)
        # 5 结束页
        else:
            s = prs.slides.add_slide(prs.slide_layouts[6])
            _bg(s, primary)
            _textbox(s, 1.0, 3.0, 11.3, 1.2, "谢谢 · Q&A", 40, _hex("FFFFFF"),
                     bold=True, align=talign)
            _textbox(s, 1.0, 4.4, 11.3, 0.6, "[联系方式 / 附件链接]", 16,
                     accent, align=talign)

    pages = [only] if only is not None else [0, 1, 2, 3, 4]
    for i in pages:
        _page(i)
    prs.save(out_path)
    return out_path


def _pick_palette(keywords: str, idx: int) -> str:
    """风格关键词命中配色族；未命中按 idx 轮转。"""
    for kw, name in (("商务", "商务"), ("科技", "科技"), ("蓝", "科技"),
                     ("极简", "极简"), ("素", "极简"), ("活力", "活力"),
                     ("年轻", "活力"), ("自然", "自然"), ("绿", "自然"),
                     ("温和", "温和"), ("暖", "温和")):
        if kw in (keywords or ""):
            return name
    return list(PALETTES)[idx % len(PALETTES)]


def _do_generate(scenario: str, style_keywords: str, count: int,
                 batch_id: str, scene: str = "generic") -> SkillResult:
    if not scenario:
        return SkillResult(success=False, error="scenario（场景描述）为空")
    scene = scene if scene in SCENES else "generic"
    batch_id = batch_id or time.strftime("%Y%m%d_%H%M%S")
    batch_dir = os.path.join(CAND_ROOT, batch_id)
    os.makedirs(batch_dir, exist_ok=True)
    candidates = []
    for i in range(max(1, min(int(count or 10), 30))):
        pname = _pick_palette(style_keywords, i)
        variant = LAYOUT_VARIANTS[i % len(LAYOUT_VARIANTS)]
        fname = f"{''.join(ch for ch in scenario if ch.isalnum())[:12] or 'cand'}_{i+1:02d}_{pname}.pptx"
        path = os.path.join(batch_dir, fname)
        _build_5piece(path, PALETTES[pname], variant, scenario, scene=scene)
        candidates.append({"file": fname, "palette": pname, "variant": variant})
    manifest = {"batch_id": batch_id, "scenario": scenario,
                "style_keywords": style_keywords or "", "scene": scene,
                "count": len(candidates),
                "candidates": candidates, "selected": None, "created_at":
                time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(batch_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    listing = "\n".join(f"  [{i+1}] {c['file']}（配色={c['palette']}）"
                        for i, c in enumerate(candidates))
    return SkillResult(
        success=True,
        output=(f"候选批次 {batch_id} 已生成 {len(candidates)} 套（每套 5 件）\n{listing}\n"
                f"下一步：action=confirm 选定候选（筛选确认门），再 action=variants 出终稿族。"),
        data={"batch_id": batch_id, "candidates": candidates})


def _load_manifest(batch_id: str):
    path = os.path.join(CAND_ROOT, batch_id, "manifest.json")
    if not os.path.isfile(path):
        return None, path
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f), path


def _do_confirm(batch_id: str, selected: str, confirmed_by: str) -> SkillResult:
    manifest, path = _load_manifest(batch_id)
    if not manifest:
        return SkillResult(success=False, error=f"批次不存在: {path}")
    idx = None
    sel = (selected or "").strip()
    for i, c in enumerate(manifest["candidates"]):
        if sel in (c["file"], str(i + 1), f"[{i+1}]"):
            idx = i
            break
    if idx is None:
        return SkillResult(success=False,
                           error=f"未找到候选 '{sel}'（可用 1~{len(manifest['candidates'])} 或文件名）")
    manifest["selected"] = {"index": idx, "file": manifest["candidates"][idx]["file"],
                            "confirmed_by": confirmed_by or "user",
                            "confirmed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return SkillResult(success=True,
                       output=(f"筛选确认门通过：批次 {batch_id} 选定 "
                               f"[{idx+1}] {manifest['selected']['file']}"
                               f"（确认人: {manifest['selected']['confirmed_by']}）。"
                               f"下一步 action=variants 生成配色族终稿。"),
                       data={"selected": manifest["selected"]})


def _register_ledger(family: str, files: int, note: str):
    """向 LICENSES.md §2 追加自产登记行（幂等：同族名只记一次）。

    格式保证：行紧贴 §2 表头分隔线之后（Markdown 表不因空行断开）；
    首跑同时清掉占位行。
    """
    try:
        with open(LEDGER, "r", encoding="utf-8") as f:
            content = f.read()
        if family in content:
            return
        row = (f"| `ppt/{family}/`（{files} 文件） | template_forge 自产"
               f"（{note}） | 项目自产 | {time.strftime('%Y-%m-%d')} | "
               f"场景族模板，观感终审权在用户 |\n")
        sec2 = content.find("## 2.")
        sep = content.find("|---|---|---|---|---|", sec2)
        line_end = content.find("\n", sep)
        content = (content[:line_end + 1] + row + content[line_end + 1:])
        content = content.replace(
            "| （待 394A-2 首跑登记） | template_forge 自产 | 项目自产 | — | 商务汇报族 5件套×3配色 |\n",
            "")
        with open(LEDGER, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[template_forge] 台账登记失败(忽略): {e}")


def _do_variants(batch_id: str, family_name: str,
                 colorways: str) -> SkillResult:
    manifest, path = _load_manifest(batch_id)
    if not manifest:
        return SkillResult(success=False, error=f"批次不存在: {path}")
    if not manifest.get("selected"):
        return SkillResult(success=False,
                           error="批次尚未过筛选确认门（请先 action=confirm）——"
                                 "禁跳过人工筛选直接出终稿")
    sel = manifest["candidates"][manifest["selected"]["index"]]
    family_name = family_name or f"{manifest['scenario'][:12]}_family_v1"
    family_dir = os.path.join(PPT_DIR, family_name)
    if os.path.isdir(family_dir) and os.listdir(family_dir):
        return SkillResult(success=False, error=f"模板族目录已存在: {family_dir}（请换族名）")
    os.makedirs(family_dir, exist_ok=True)
    # 中选配色在前，其余取词表轮转补足 3 个配色族
    cway_names = [c.strip() for c in (colorways or "").split(",") if c.strip()]
    names = list(PALETTES)
    ordered = ([n for n in cway_names if n in PALETTES] or []) + \
              [n for n in names if n not in cway_names]
    if sel["palette"] in ordered:
        ordered.remove(sel["palette"])
    ordered = [sel["palette"]] + ordered[:2] if len(ordered) >= 2 else [sel["palette"]]
    # 中选候选按批次 scene 的五件套拆件出终稿（395A-1 场景化；老批次无 scene 键回退 generic）
    scene = manifest.get("scene", "generic")
    pieces = SCENES.get(scene, SCENES["generic"])["pieces"]
    files, idx = [], 0
    for cway in ordered:
        for piece_idx, piece in enumerate(pieces):
            idx += 1
            fname = f"{family_name}_{cway}_{piece}.pptx"
            _build_5piece(os.path.join(family_dir, fname),
                          PALETTES[cway], sel["variant"],
                          manifest["scenario"], only=piece_idx, scene=scene)
            files.append(fname)
    manifest["family"] = {"name": family_name, "dir": family_dir,
                          "scene": scene, "pieces": pieces,
                          "colorways": ordered, "files": len(files),
                          "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    _register_ledger(family_name, len(files),
                     f"批次 {batch_id} 中选候选扩展，配色族 {('/'.join(ordered))}")
    return SkillResult(
        success=True,
        output=(f"模板族 {family_name} 入库：{len(files)} 文件（5件套×{len(ordered)}配色："
                f"{'/'.join(ordered)}）\n目录: {family_dir}\n"
                f"LICENSES.md 台账已登记（自产）。观感终审权在用户。"),
        data={"family": manifest["family"]})


def execute(action: str = "generate", scenario: str = "",
            style_keywords: str = "", count: int = 10, batch_id: str = "",
            selected: str = "", confirmed_by: str = "", family_name: str = "",
            colorways: str = "", scene: str = "generic") -> SkillResult:
    try:
        if action == "generate":
            return _do_generate(scenario, style_keywords, count, batch_id, scene)
        if action == "confirm":
            return _do_confirm(batch_id, selected, confirmed_by)
        if action == "variants":
            return _do_variants(batch_id, family_name, colorways)
        return SkillResult(success=False,
                           error=f"未知 action='{action}'（generate/confirm/variants）")
    except Exception as e:
        import traceback
        return SkillResult(success=False, error=f"template_forge 异常: {e}",
                           output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="template_forge",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["generate", "confirm", "variants"],
                           "description": "generate=批量候选 / confirm=筛选确认门 / variants=配色族终稿",
                           "default": "generate"},
                "scenario": {"type": "string", "description": "场景描述（如：商务汇报）"},
                "style_keywords": {"type": "string",
                                   "description": "风格关键词（商务/科技/极简/活力/自然/温和）"},
                "count": {"type": "integer", "description": "候选套数", "default": 10},
                "batch_id": {"type": "string", "description": "批次号（confirm/variants 用）"},
                "selected": {"type": "string", "description": "选中的候选序号或文件名"},
                "confirmed_by": {"type": "string",
                                 "description": "确认人（user=用户本人；agent 代选须如实标注）",
                                 "default": "user"},
                "family_name": {"type": "string", "description": "终稿模板族名"},
                "colorways": {"type": "string",
                              "description": "配色族名逗号分隔（默认含中选配色在内取 3 个）"},
                "scene": {"type": "string",
                          "enum": ["generic", "academic_defense", "tech_sharing", "edu_training"],
                          "description": ("五件套场景（395A-1）：generic=通用两栏+图表 / "
                                          "academic_defense=学术答辩公式页 / "
                                          "tech_sharing=技术分享代码页+架构图页 / "
                                          "edu_training=教育培训讲义页+练习页"),
                          "default": "generic"},
            },
            "required": ["action"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=120,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
