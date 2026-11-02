# -*- coding: utf-8 -*-
"""
Skill: office_generator — 办公文档生成
=======================================
PPT / Word / Excel / PDF。支持 Markdown 输入，自动转换格式。

★ 394A-3 模板填充优先：
- template_path 可选参数（模板 .pptx 文件 或 data/templates/ppt/<族名>/ 目录，
  或 "auto"=按 doc_type+场景关键词路由 data/templates/）；
- 有模板 → 打开母版原型页克隆灌内容（观感对齐母版）；
- 无模板/模板缺失 → 现有空白构建路径兜底（零回归），并在 output 中明示。
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
    "name": "office_generator",
    "description": ("生成办公文档：PPT / Word / Excel / PDF。支持 Markdown 输入。"
                    "394A-3: 支持模板灌装（template_path 母版/族目录/auto 场景路由）。"),
    "category": "office",
    "version": "2.0.0",
}

# ★ 394A-3: 模板根目录与场景关键词 → 模板族路由表（关键词匹配即可，禁过度设计）
_TEMPLATES_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "data", "templates")
_DOC_DIR = {"ppt": "ppt", "docx": "doc", "xlsx": "xlsx"}
_ROUTE_KEYWORDS = {
"business_report_v1": ["商务", "汇报", "报告", "季度", "总结", "评审", "规划"],
# 395A-1 场景族路由（与 template_forge.SCENES 对应）
"academic_defense_v1": ["答辩", "学术", "论文", "公式", "开题", "课题", "毕业"],
"tech_sharing_v1": ["技术分享", "技术", "代码", "架构", "实现", "开发", "工程"],
"edu_training_v1": ["培训", "教学", "课程", "讲义", "练习", "课件", "授课"],
}

# ★ 395A-2: 图表主题目录（matplotlib_theme_<族名>.json，与母版配色同源）
_CHARTS_DIR = os.path.join(_TEMPLATES_ROOT, "charts")

# ★ 395A-3: xlsx 三型模板路由（财务/周报/数据，openpyxl 自产）
_XLSX_TEMPLATE_KEYWORDS = {
    "finance_monthly": ["财务", "收支", "预算", "报表", "会计", "月度"],
    "weekly_report": ["周报", "周度", "本周", "工作总结"],
    "data_table": ["数据", "明细", "台账", "清单"],
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


def _resolve_template_path(doc_type: str, title: str, content: str) -> str:
    """★394A-3.2 模板路由：按 doc_type + 场景关键词在 data/templates/ 下选最匹配模板族。

    返回模板族目录或 ""（无命中）。评分 = 族名+关键词表在 文本 的命中次数。
    """
    doc_dir = _DOC_DIR.get(doc_type)
    if not doc_dir:
        return ""
    root = os.path.join(_TEMPLATES_ROOT, doc_dir)
    if not os.path.isdir(root):
        return ""
    text = f"{title}\n{content}"
    # ★ 395A-3: xlsx 模板为单文件型（<型名>.xlsx），按关键词表选型
    if doc_type == "xlsx":
        best, best_score = "", 0
        for name, kws in _XLSX_TEMPLATE_KEYWORDS.items():
            path = os.path.join(root, f"{name}.xlsx")
            if not os.path.isfile(path):
                continue
            score = sum(1 for kw in kws if kw in text)
            if score > best_score:
                best, best_score = path, score
        return best if best_score > 0 else ""
    best, best_score = "", 0
    for name in sorted(os.listdir(root)):
        family_dir = os.path.join(root, name)
        if not os.path.isdir(family_dir):
            continue
        score = sum(1 for kw in _ROUTE_KEYWORDS.get(name, [name]) if kw in text)
        score += sum(1 for ch in name if ch in text and not ch.isascii())
        if score > best_score:
            best, best_score = family_dir, score
    return best if best_score > 0 else ""


_PIECE_FILES = {
"cover": "01_title", "section": "02_section", "content": "03_two_col",
"chart": "04_chart", "end": "05_end",
}

# 395A-1 场景族件名兼容：03/04 件按场景不同，按子串逐一回退
_PIECE_PREFIXES = {
    "cover": ["01_title"],
    "section": ["02_section"],
    "content": ["03_two_col", "03_formula", "03_code", "03_lecture"],
    "chart": ["04_chart", "04_architecture", "04_exercise"],
    "end": ["05_end"],
}


def _pick_family_pieces(family_dir: str):
    """族目录 → (五件原型文件映射, 元信息)。

    族文件命名: <族名>_<配色>_<件名>.pptx —— 按"件名子串"匹配。
    395A-1: 兼容场景族件名（03_formula/03_code/03_lecture、04_architecture/04_exercise）。
    meta: colorway=选中配色族名；content_kind/chart_kind=命中的件名前缀。
    """
    pieces, meta = {}, {}
    for key, prefixes in _PIECE_PREFIXES.items():
        for pfx in prefixes:
            for name in sorted(os.listdir(family_dir)):
                if pfx in name and name.endswith(".pptx"):
                    pieces[key] = os.path.join(family_dir, name)
                    meta[f"{key}_kind"] = pfx
                    break
            if key in pieces:
                break
    cover = pieces.get("cover", "")
    if cover:
        stem = os.path.basename(cover)[:-5]
        kind = meta.get("cover_kind", "01_title")
        head = stem[:stem.rfind("_" + kind)]
        meta["colorway"] = head.rsplit("_", 1)[-1] if head else ""
    return pieces, meta


def _clone_slide(prs, src_slide, skip_charts: bool = False):
    """克隆母版原型页（含背景与全部形状；图表框按需跳过后原生重建）。"""
    import copy as _copy
    new_slide = prs.slides.add_slide(prs.slide_layouts[6])
    try:  # 背景色迁移（观感对齐母版的关键）
        src_fill = src_slide.background.fill
        new_slide.background.fill.solid()
        new_slide.background.fill.fore_color.rgb = src_fill.fore_color.rgb
    except Exception:
        pass
    for shp in src_slide.shapes:
        if skip_charts and shp.shape_type is not None and "CHART" in str(shp.shape_type):
            continue
        el = _copy.deepcopy(shp._element)
        new_slide.shapes._spTree.append(el)
    return new_slide


def _fill_texts(slide, mapping: Dict[str, str]):
    """run 级占位符替换（保留母版字体/颜色/字号格式）。"""
    for shp in slide.shapes:
        if not shp.has_text_frame:
            continue
        for para in shp.text_frame.paragraphs:
            for run in para.runs:
                for k, v in mapping.items():
                    if k in run.text:
                        run.text = run.text.replace(k, v)


def _load_chart_theme(family: str):
    """395A-2: 读族名对应的图表主题（charts/matplotlib_theme_<族名>.json）。"""
    if not family:
        return None
    path = os.path.join(_CHARTS_DIR, f"matplotlib_theme_{family}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _apply_chart_theme(chart, family: str, colorway: str) -> bool:
    """395A-2: PPT 原生图表配色与母版同源。

    主题按所选模板族加载；系列色取主题内该配色族的 series 序列
    （柱/条/面积改填充色，折线改线色，饼图按数据点着色）。
    返回是否成功应用（供灌装结果如实标注）。
    """
    theme = _load_chart_theme(family)
    if not theme:
        return False
    pal = (theme.get("colorways") or {}).get(colorway) or theme.get("default") or {}
    series_colors = pal.get("series") or []
    if not series_colors:
        return False
    try:
        from pptx.dml.color import RGBColor
        from pptx.util import Pt
        from pptx.enum.chart import XL_CHART_TYPE as _XT
        is_line = False
        is_pie = False
        try:
            ct = chart.chart_type
            is_line = ct in (_XT.LINE, _XT.LINE_MARKERS, _XT.LINE_STACKED,
                             _XT.LINE_STACKED_MARKERS)
            is_pie = ct in (_XT.PIE, _XT.DOUGHNUT)
        except Exception:
            pass
        if is_pie:
            pts = chart.plots[0].series[0].points if chart.plots else []
            for i, pt in enumerate(pts):
                if i >= len(series_colors):
                    break
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = RGBColor.from_string(
                    str(series_colors[i]).lstrip("#"))
            return True
        for i, serie in enumerate(chart.series):
            if i >= len(series_colors):
                break
            rgb = RGBColor.from_string(str(series_colors[i]).lstrip("#"))
            if is_line:
                serie.format.line.color.rgb = rgb
                serie.format.line.width = Pt(2.25)
            else:
                serie.format.fill.solid()
                serie.format.fill.fore_color.rgb = rgb
        return True
    except Exception:
        return False


def _audit_outline(slides_data: list, min_slides: int = 8, max_slides: int = 15,
                   max_bullets: int = 4, max_chars: int = 40) -> Dict:
    """★395B-1 大纲质量自检清单（页数/要点/备注三项勾选 + 字数/图表占比）。"""
    n = len(slides_data or [])
    chart_pages = sum(1 for s in (slides_data or [])
                      if s.get("slide_type") == "chart" and s.get("chart_data"))
    notes_covered = sum(1 for s in (slides_data or []) if (s.get("notes") or "").strip())
    bullets_bad, chars_bad = [], []
    for i, s in enumerate(slides_data or []):
        sc = s.get("slide_content") or ""
        if isinstance(sc, list):  # 395B-1: 模型可能产出要点数组，与多行文本同义
            sc = "\n".join(str(x) for x in sc)
        if isinstance(sc, str) and sc.strip():
            lines = [ln.strip() for ln in sc.splitlines() if ln.strip()]
            if len(lines) > max_bullets:
                bullets_bad.append(i + 1)
            if any(len(ln) > max_chars for ln in lines):
                chars_bad.append(i + 1)
    chart_ratio = round(chart_pages / n, 3) if n else 0.0
    return {
        "pages_total": n,
        "pages_ok": min_slides <= n <= max_slides,          # 勾选①页数 8-15
        "bullets_ok": not bullets_bad,                        # 勾选②每页要点 ≤4
        "notes_ok": n > 0 and notes_covered == n,             # 勾选③备注栏每页一句讲稿
        "pages_over_bullet_limit": bullets_bad,
        "pages_over_char_limit": chars_bad,                   # 每条要点 ≤40 字
        "chart_pages": chart_pages,
        "chart_ratio": chart_ratio,
        "chart_ratio_ok": chart_ratio >= 0.2,                 # 图表页占比 ≥20%
        "notes_covered": notes_covered,
        "spec": {"min_slides": min_slides, "max_slides": max_slides,
                 "max_bullets": max_bullets, "max_chars": max_chars,
                 "min_chart_ratio": 0.2},
    }


def _fill_xlsx_from_template(template_path: str, content: str):
    """★395A-3 xlsx 模板填充优先：{{key}} 占位替换，公式/条件格式原样保留。

    content JSON: {"fields": {key: value, ...}}（或直接就是 flat dict）。
    返回 (workbook|None, err, filled, missing)；公式/条件格式由 openpyxl
    load/save 周期天然存活（不触碰非占位单元格）。
    """
    openpyxl = _lazy_import('openpyxl')
    if openpyxl is None:
        return None, "openpyxl 未安装", 0, []
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        data = None
    fields = {}
    if isinstance(data, dict):
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else data
    try:
        wb = openpyxl.load_workbook(template_path)  # data_only=False: 公式保留
    except Exception as e:
        return None, f"模板加载失败: {e}", 0, []
    filled, missing = 0, []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if not (isinstance(v, str) and "{{" in v):
                    continue
                nv = v
                for k, val in fields.items():
                    token = "{{" + str(k) + "}}"
                    if token in nv:
                        nv = nv.replace(token, str(val))
                if nv != v:
                    cell.value = nv
                    filled += 1
                if "{{" in nv:
                    import re as _re
                    missing.extend(_re.findall(r"\{\{(\w+)\}\}", nv))
    return wb, "", filled, sorted(set(missing))


def _fill_ppt_from_template(template_path: str, title: str, slides_data: list,
                            date_line: str):
    """★394A-3.1 母版灌装：克隆原型页 + run 级占位替换。

    template_path 可为：单个母版 .pptx（第一页作标题原型、末页作内容原型）
    或 5 件套模板族目录（01~05 件各为对应原型）。
    """
    pptx = _lazy_import('pptx')
    if pptx is None:
        return None, "python-pptx 未安装"
    from pptx.util import Inches
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE

    if os.path.isdir(template_path):
        pieces, meta = _pick_family_pieces(template_path)
        if not pieces.get("cover"):
            return None, f"模板族目录缺 01_title 原型件: {template_path}"
        protos = {k: pptx.Presentation(v) for k, v in pieces.items()}
        family_name = os.path.basename(os.path.normpath(template_path))
    else:
        proto = pptx.Presentation(template_path)
        protos = {"cover": proto, "section": proto, "content": proto,
                  "chart": proto, "end": proto}
        meta, family_name = {}, ""

    prs = pptx.Presentation()
    prs.slide_width = protos["cover"].slide_width
    prs.slide_height = protos["cover"].slide_height

    # 封面
    cover = _clone_slide(prs, protos["cover"].slides[0])
    _fill_texts(cover, {"[报告标题]": title,
                        "[副标题 / 一句话结论]": f"{title} · 要点简述",
                        "[汇报人] · [日期]": date_line})

    for idx, sd in enumerate(slides_data):
        slide_type = sd.get('slide_type', 'content')
        st = sd.get('slide_title', f'第{idx+2}页')
        sc = sd.get('slide_content', '')
        if slide_type == 'section':
            sl = _clone_slide(prs, protos["section"].slides[0])
            _fill_texts(sl, {"01": f"{idx+1:02d}", "[章节标题]": st,
                             "[本章要点一]\n[本章要点二]\n[本章要点三]": sc or st})
        elif slide_type == 'chart' and sd.get('chart_data'):
            sl = _clone_slide(prs, protos["chart"].slides[0], skip_charts=True)
            _fill_texts(sl, {"[数据结论标题]": st,
                             "[图表解读要点]": sc or "[图表解读要点]"})
            chart_theme_ok = None
            try:
                cd = CategoryChartData()
                cd.categories = sd['chart_data'].get('categories', [])
                for serie in sd['chart_data'].get('series', []):
                    cd.add_series(serie.get('name', '数据'), serie.get('values', []))
                cmap = {'bar': XL_CHART_TYPE.COLUMN_CLUSTERED, 'line': XL_CHART_TYPE.LINE,
                        'pie': XL_CHART_TYPE.PIE, 'scatter': XL_CHART_TYPE.XY_SCATTER}
                gshape = sl.shapes.add_chart(
                    cmap.get(sd['chart_data'].get('type', 'bar'),
                             XL_CHART_TYPE.COLUMN_CLUSTERED),
                    Inches(0.9), Inches(1.7), Inches(8.0), Inches(5.0), cd)
                gchart = gshape.chart
                gchart.has_title = False
                gchart.has_legend = True
                # ★ 395A-2: 图表配色与母版同源（按族加载主题，按配色族取系列色）
                chart_theme_ok = _apply_chart_theme(
                    gchart, family_name, meta.get("colorway", ""))
            except Exception:
                pass
        else:
            sl = _clone_slide(prs, protos["content"].slides[0])
            _sc = sc if isinstance(sc, str) else "\n".join(str(x) for x in (sc or []))
            body = (_sc or f"第{idx+2}页内容").split('\n')
            left = "\n".join(body[:max(1, len(body) // 2)])
            right = "\n".join(body[max(1, len(body) // 2):]) or "（待补充）"
            mapping = {"[页面标题]": st,
                       "[左栏：现状/问题/文本要点]": left,
                       "[右栏：方案/数据/对照要点]": right}
            # ★ 395A-1: 场景族内容件占位灌装（未提供的留原占位符明示）
            kind = meta.get("content_kind", "03_two_col")
            if kind == "03_formula":
                mapping["[核心公式：LaTeX 表达，如 y = β₀ + β₁x]"] = sc or st
                mapping["[符号与参数说明]"] = left
                mapping["[定理 / 引理编号与出处]"] = right if right != "（待补充）" else right
            elif kind == "03_code":
                mapping["[代码块：关键实现节选]"] = sc or st
                mapping["[代码要点解读]"] = right
            elif kind == "03_lecture":
                mapping["[知识点]"] = st
                mapping["[讲解正文：定义 / 步骤 / 例子]"] = left
            _fill_texts(sl, mapping)

    end = _clone_slide(prs, protos["end"].slides[0])
    _fill_texts(end, {"[联系方式 / 附件链接]": date_line})
    return prs, ""


def execute(
    doc_type: str = "ppt",
    title: str = "",
    content: str = "",
    output_path: str = "",
    template: str = "",
    theme: str = "lemon",
    template_path: str = "",
    min_slides: int = 8,
    max_slides: int = 15,
) -> SkillResult:
    """生成办公文档

    ★ v3.71 增强：
    - PPT: 多布局（标题页/章节页/两栏/图表页）+ 配色方案 + 图表 + 备注
    - Excel: 标题行样式 + 公式支持 + 条件格式
    - theme: lemon(柠檬橙) / business(商务蓝) / academic(学术绿) / tech(科技紫)

    ★ 394A-3 模板填充优先：
    - template_path: 母版 .pptx 文件 / 模板族目录 / "auto"（按场景关键词路由）；
      兼容旧占位参 template（等价 template_path 的别名）；
    - 有模板 → 母版原型克隆灌装（观感对齐母版）；
    - 无模板/模板缺失 → 空白构建路径兜底（零回归），output 明示 fallback。

    ★ 395B-1 质量规范：PPT 大纲按质量护栏自检（总页数 8-15 可由
    min_slides/max_slides 覆盖、每页要点 ≤4、每条 ≤40 字、图表页占比 ≥20%、
    备注栏每页一句讲稿），产出物附 quality_checklist（页数/要点/备注三项勾选）。
    """
    quality_checklist = None
    if not title:
        return SkillResult(success=False, error="title 参数为空")
    if not content:
        return SkillResult(success=False, error="content 参数为空")

    if not output_path:
        ext_map = {'ppt': '.pptx', 'docx': '.docx', 'xlsx': '.xlsx', 'pdf': '.pdf'}
        output_path = os.path.join(tempfile.gettempdir(),
                                   f"{title}_{int(time.time())}{ext_map.get(doc_type, '.txt')}")

    # ★ 394A-3: 模板解析（template 为旧占位别名；"auto" 走场景路由）
    _tp = (template_path or template or "").strip()
    _fallback_note = ""
    if _tp == "auto":
        _tp = _resolve_template_path(doc_type, title, content)
        if not _tp:
            _fallback_note = "（auto 路由无命中模板）"
    if _tp and not os.path.exists(_tp):
        _fallback_note = f"（模板缺失已兜底: {_tp}）"
        _tp = ""
    if _tp and doc_type not in ('ppt', 'xlsx'):
        _fallback_note = f"（394A-3 模板灌装当前支持 doc_type=ppt/xlsx，{doc_type} 走空白构建）"
        _tp = ""

    try:
        # ===== PPT =====
        if doc_type == 'ppt':
            pptx = _lazy_import('pptx')
            if pptx is None:
                return _lib_missing('python-pptx')
            from pptx.util import Inches, Pt, Emu
            from pptx.dml.color import RGBColor
            from pptx.enum.text import PP_ALIGN

            # ★ v3.71: 配色方案
            themes = {
                'lemon':    {'bg': RGBColor(0xFF, 0xF8, 0xE7), 'title': RGBColor(0xE5, 0x5A, 0x00), 'accent': RGBColor(0xFF, 0x9A, 0x4A), 'text': RGBColor(0x33, 0x33, 0x33)},
                'business': {'bg': RGBColor(0xF0, 0xF4, 0xF8), 'title': RGBColor(0x1A, 0x3C, 0x6E), 'accent': RGBColor(0x2E, 0x75, 0xB6), 'text': RGBColor(0x2D, 0x2D, 0x2D)},
                'academic': {'bg': RGBColor(0xF5, 0xF7, 0xF2), 'title': RGBColor(0x1B, 0x5E, 0x20), 'accent': RGBColor(0x43, 0xA0, 0x47), 'text': RGBColor(0x21, 0x21, 0x21)},
                'tech':     {'bg': RGBColor(0xF3, 0xF0, 0xF7), 'title': RGBColor(0x4A, 0x14, 0x8C), 'accent': RGBColor(0x7B, 0x1F, 0xA2), 'text': RGBColor(0x2D, 0x2D, 0x2D)},
            }
            colors = themes.get(theme, themes['lemon'])

            prs = pptx.Presentation()

            # 解析 slides 数据
            try:
                slides_data = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                slides_data = [{'slide_title': f'第{i+1}页', 'slide_content': c.strip()}
                               for i, c in enumerate(content.split('---')) if c.strip()]

            # ★ 395B-1: 大纲质量自检（产出物附清单入 data 字段）
            quality_checklist = _audit_outline(slides_data, min_slides=min_slides,
                                               max_slides=max_slides)

            # ★ 394A-3.1: 模板填充优先 —— 有模板走母版灌装，失败/无模板走空白构建兜底
            date_line = f"Lemon Code · {time.strftime('%Y-%m-%d')}"
            if _tp:
                prs, err = _fill_ppt_from_template(_tp, title, slides_data, date_line)
                if prs is None:
                    _fallback_note = f"（模板灌装失败已兜底: {err}）"
                    prs = None
            else:
                prs = None

            if prs is not None:
                prs.save(output_path)
                return SkillResult(
                    success=True,
                    output=(f"文档已生成（母版灌装）: {output_path}\n类型: ppt\n标题: {title}\n"
                            f"模板: {_tp}\n页数: {len(slides_data) + 2}"),
                    data={'path': output_path, 'doc_type': 'ppt', 'title': title,
                          'mode': 'template_filled', 'template': _tp,
                          'quality_checklist': quality_checklist,
                          'chart_theme': ("matplotlib_theme_" +
                                          os.path.basename(os.path.normpath(_tp)) +
                                          ".json") if os.path.isdir(_tp) else None},
                )
            # ===== 空白构建路径（既有逻辑，零回归兜底）=====
            prs = pptx.Presentation()

            # ★ 封面页
            slide_layout = prs.slide_layouts[0]  # Title Slide
            slide = prs.slides.add_slide(slide_layout)
            slide.shapes.title.text = title
            if len(slide.placeholders) > 1:
                slide.placeholders[1].text = f"Lemon Code · {time.strftime('%Y-%m-%d')}"
            # 封面配色
            if slide.shapes.title and slide.shapes.title.text_frame:
                for p in slide.shapes.title.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.color.rgb = colors['title']
                        r.font.size = Pt(40)
                        r.font.bold = True

            # ★ 内容页
            for idx, sd in enumerate(slides_data):
                slide_title = sd.get('slide_title', f'第{idx+2}页')
                slide_content = sd.get('slide_content', '')
                slide_type = sd.get('slide_type', 'content')  # content / section / two_column / chart
                chart_data = sd.get('chart_data')  # {"type": "bar", "categories": [...], "series": [...]}
                notes = sd.get('notes', '')

                if slide_type == 'section':
                    # ★ 章节分隔页（居中大字）
                    slide_layout = prs.slide_layouts[5]  # Blank
                    slide = prs.slides.add_slide(slide_layout)
                    left = top = width = height = None
                    txBox = slide.shapes.add_textbox(Inches(1), Inches(2.5), Inches(8), Inches(2))
                    tf = txBox.text_frame
                    tf.word_wrap = True
                    p = tf.paragraphs[0]
                    p.text = slide_title
                    p.alignment = PP_ALIGN.CENTER
                    for r in p.runs:
                        r.font.size = Pt(36)
                        r.font.bold = True
                        r.font.color.rgb = colors['accent']
                elif slide_type == 'chart' and chart_data:
                    # ★ 图表页
                    slide_layout = prs.slide_layouts[5]  # Blank
                    slide = prs.slides.add_slide(slide_layout)
                    # 标题
                    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(0.8))
                    tf = txBox.text_frame
                    p = tf.paragraphs[0]
                    p.text = slide_title
                    for r in p.runs:
                        r.font.size = Pt(28)
                        r.font.bold = True
                        r.font.color.rgb = colors['title']
                    # 图表
                    try:
                        from pptx.chart.data import CategoryChartData
                        from pptx.enum.chart import XL_CHART_TYPE
                        chart_type_str = chart_data.get('type', 'bar')
                        chart_type_map = {
                            'bar': XL_CHART_TYPE.COLUMN_CLUSTERED,
                            'line': XL_CHART_TYPE.LINE,
                            'pie': XL_CHART_TYPE.PIE,
                            'scatter': XL_CHART_TYPE.XY_SCATTER,
                        }
                        xl_type = chart_type_map.get(chart_type_str, XL_CHART_TYPE.COLUMN_CLUSTERED)
                        cd = CategoryChartData()
                        cd.categories = chart_data.get('categories', [])
                        for serie in chart_data.get('series', []):
                            cd.add_series(serie.get('name', '数据'), serie.get('values', []))
                        chart_shape = slide.shapes.add_chart(
                            xl_type, Inches(1), Inches(1.5), Inches(8), Inches(5), cd
                        )
                        chart = chart_shape.chart
                        chart.has_title = False
                        chart.has_legend = True
                    except Exception as chart_err:
                        # 图表失败时回退为文本
                        txBox2 = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(4))
                        txBox2.text_frame.text = f"（图表生成失败: {chart_err}）\n{slide_content}"
                else:
                    # ★ 标准内容页
                    slide_layout = prs.slide_layouts[1]  # Title and Content
                    slide = prs.slides.add_slide(slide_layout)
                    slide.shapes.title.text = slide_title
                    if slide.shapes.title and slide.shapes.title.text_frame:
                        for p in slide.shapes.title.text_frame.paragraphs:
                            for r in p.runs:
                                r.font.color.rgb = colors['title']
                                r.font.size = Pt(32)
                                r.font.bold = True
                    if len(slide.placeholders) > 1:
                        slide.placeholders[1].text = slide_content
                        for p in slide.placeholders[1].text_frame.paragraphs:
                            for r in p.runs:
                                r.font.color.rgb = colors['text']
                                r.font.size = Pt(18)

                # ★ 备注
                if notes and hasattr(slide, 'notes_slide'):
                    slide.notes_slide.notes_text_frame.text = notes

            prs.save(output_path)

        # ===== Word =====
        elif doc_type == 'docx':
            docx = _lazy_import('docx')
            if docx is None:
                return _lib_missing('python-docx')
            doc = docx.Document()
            doc.add_heading(title, level=0)
            for line in content.split('\n'):
                line = line.strip()
                if not line:
                    continue
                if line.startswith('# '):
                    doc.add_heading(line[2:], level=1)
                elif line.startswith('## '):
                    doc.add_heading(line[3:], level=2)
                elif line.startswith('### '):
                    doc.add_heading(line[4:], level=3)
                elif line.startswith('- '):
                    doc.add_paragraph(line[2:], style='List Bullet')
                elif line.startswith('1. ') or line.startswith('1) '):
                    doc.add_paragraph(line[3:], style='List Number')
                else:
                    doc.add_paragraph(line)
            doc.save(output_path)

        # ===== Excel =====
        elif doc_type == 'xlsx':
            openpyxl = _lazy_import('openpyxl')
            if openpyxl is None:
                return _lib_missing('openpyxl')
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter

            # ★ 395A-3: xlsx 模板填充优先（{{key}} 数据绑定，公式/条件格式存活），
            #   失败/无模板走空白构建兑底（零回归）
            if _tp:
                wb_t, err_t, filled_t, missing_t = _fill_xlsx_from_template(_tp, content)
                if wb_t is not None:
                    wb_t.save(output_path)
                    miss_note = (f"，未提供的占位符: {missing_t}" if missing_t
                                 else "，占位符全部命中")
                    return SkillResult(
                        success=True,
                        output=(f"文档已生成（模板灌装）: {output_path}\n类型: xlsx\n"
                                f"标题: {title}\n模板: {_tp}\n"
                                f"占位符填充: {filled_t} 处{miss_note}"),
                        data={'path': output_path, 'doc_type': 'xlsx', 'title': title,
                              'mode': 'template_filled', 'template': _tp,
                              'placeholders_filled': filled_t,
                              'placeholders_missing': missing_t},
                    )
                _fallback_note = f"（xlsx 模板灌装失败已兑底: {err_t}）"

            wb = openpyxl.Workbook()
            try:
                sheets_data = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                sheets_data = {title: [[c.strip() for c in line.split(',')] for line in content.split('\n') if line.strip()]}
            if isinstance(sheets_data, list):
                sheets_data = {title: sheets_data}

            # ★ v3.71: Excel 配色方案
            xl_themes = {
                'lemon':    {'header_bg': 'FF9A4A', 'header_fg': 'FFFFFF', 'alt_row': 'FFF8E7'},
                'business': {'header_bg': '2E75B6', 'header_fg': 'FFFFFF', 'alt_row': 'F0F4F8'},
                'academic': {'header_bg': '43A047', 'header_fg': 'FFFFFF', 'alt_row': 'F5F7F2'},
                'tech':     {'header_bg': '7B1FA2', 'header_fg': 'FFFFFF', 'alt_row': 'F3F0F7'},
            }
            xl_colors = xl_themes.get(theme, xl_themes['lemon'])

            first = True
            for sheet_name, rows in sheets_data.items():
                if first:
                    ws = wb.active
                    ws.title = sheet_name
                    first = False
                else:
                    ws = wb.create_sheet(sheet_name)

                # ★ 写入数据
                for row in rows:
                    ws.append(row)

                # ★ v3.71: 标题行样式（第一行加粗+背景色+白字）
                if ws.max_row >= 1:
                    header_font = Font(name='微软雅黑', bold=True, color=xl_colors['header_fg'], size=11)
                    header_fill = PatternFill(start_color=xl_colors['header_bg'], end_color=xl_colors['header_bg'], fill_type='solid')
                    header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
                    thin_border = Border(
                        left=Side(style='thin', color='CCCCCC'),
                        right=Side(style='thin', color='CCCCCC'),
                        top=Side(style='thin', color='CCCCCC'),
                        bottom=Side(style='thin', color='CCCCCC'),
                    )
                    for cell in ws[1]:
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.alignment = header_align
                        cell.border = thin_border

                    # ★ 隔行变色（斑马纹）
                    alt_fill = PatternFill(start_color=xl_colors['alt_row'], end_color=xl_colors['alt_row'], fill_type='solid')
                    for row_idx in range(2, ws.max_row + 1):
                        if row_idx % 2 == 0:
                            for cell in ws[row_idx]:
                                cell.fill = alt_fill
                        for cell in ws[row_idx]:
                            cell.border = thin_border

                    # ★ 自动列宽（根据内容长度）
                    for col_idx in range(1, ws.max_column + 1):
                        max_len = 0
                        for row_idx in range(1, min(ws.max_row + 1, 50)):
                            val = ws.cell(row=row_idx, column=col_idx).value
                            if val:
                                max_len = max(max_len, len(str(val)))
                        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 50)

                    # ★ 冻结首行
                    ws.freeze_panes = 'A2'

            wb.save(output_path)

        # ===== PDF =====
        elif doc_type == 'pdf':
            reportlab = _lazy_import('reportlab')
            if reportlab is None:
                return _lib_missing('reportlab')
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            font_registered = False
            for fp in ['C:/Windows/Fonts/simhei.ttf', 'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simsun.ttc']:
                if os.path.exists(fp):
                    try:
                        pdfmetrics.registerFont(TTFont('Chinese', fp))
                        font_registered = True
                        break
                    except Exception:
                        continue

            doc = SimpleDocTemplate(output_path, pagesize=A4)
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle('ChineseTitle', parent=styles['Title'],
                                         fontName='Chinese' if font_registered else 'Helvetica', fontSize=24, spaceAfter=30)
            body_style = ParagraphStyle('ChineseBody', parent=styles['Normal'],
                                        fontName='Chinese' if font_registered else 'Helvetica', fontSize=11, leading=18)
            story = [Paragraph(title, title_style), Spacer(1, 20)]
            for line in content.split('\n'):
                line = line.strip()
                if not line:
                    story.append(Spacer(1, 6))
                elif line.startswith('# '):
                    story.append(Paragraph(line[2:], title_style))
                else:
                    story.append(Paragraph(line, body_style))
            doc.build(story)

        else:
            return SkillResult(success=False, error=f"未知 doc_type: {doc_type}")

        return SkillResult(
            success=True,
            output=(f"文档已生成: {output_path}\n类型: {doc_type}\n标题: {title}"
                    f"{_fallback_note}"),
            data={'path': output_path, 'doc_type': doc_type, 'title': title,
                  **({"quality_checklist": quality_checklist} if quality_checklist else {}),
                  **({"fallback_note": _fallback_note} if _fallback_note else {})},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"文档生成失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="office_generator",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "doc_type": {"type": "string", "enum": ["ppt", "docx", "xlsx", "pdf"], "description": "文档类型"},
                "title": {"type": "string", "description": "文档标题"},
                "content": {"type": "string",
                            "description": ("文档内容（Markdown/JSON）。PPT支持slide_type: content/section/chart，"
                                            "chart_data: {type:bar/line/pie, categories:[], series:[]}。"
                                            "【PPT大纲质量规范(395B-1)】总页数 8-15 页；每页要点 ≤4 条；"
                                            "每条要点 ≤40 字；图表页占比 ≥20%（≥2 页 chart）；"
                                            "每页必须带 notes 备注栏一句讲稿。")},
                "output_path": {"type": "string", "description": "输出路径"},
                "template": {"type": "string", "description": "模板路径（可选，394A-3 起生效；等价 template_path）"},
                "template_path": {"type": "string", "description": "模板：母版.pptx 文件 / 模板族目录 / \"auto\"（按 doc_type+场景关键词路由 data/templates/）；无模板或缺失自动走空白构建兜底"},
                "theme": {"type": "string", "enum": ["lemon", "business", "academic", "tech"], "description": "配色方案", "default": "lemon"},
                "min_slides": {"type": "integer", "description": "PPT 总页数下限（395B-1 质量规范参数覆盖）", "default": 8},
                "max_slides": {"type": "integer", "description": "PPT 总页数上限（395B-1 质量规范参数覆盖）", "default": 15},
            },
            "required": ["doc_type", "title", "content"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
