# -*- coding: utf-8 -*-
"""
Skill: resume_renderer — JSON Resume 渲染器（394A-4；395A-5 双栏+PDF 双路径）
==============================================================================
数据/样式分离样板：输入 JSON Resume 标准 schema（MIT，schema 落库于
data/templates/resume/schema.json）的 resume.json → 按主题文件渲染
出 .docx（可选 .pdf）。

主题 = data/templates/resume/themes/<theme>.json（纯样式 JSON，自产）。
换主题不改数据；resume.json 不含任何样式信息。

395A-5:
  - 第三主题 modern_two_col：页眉通栏 + 正文连续双栏（Word cols=2，非左右固定侧栏）
  - PDF 双路径：LibreOffice(soffice --convert-to pdf) 优先探测，不可用回退 Word COM；
    data.pdf_engine 如实记录实际可用路径
"""

import json
import os
import subprocess
import time
import traceback
from typing import Dict, Any, Tuple

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
THEMES_DIR = os.path.join(_REPO_ROOT, "data", "templates", "resume", "themes")
SCHEMA_FILE = os.path.join(_REPO_ROOT, "data", "templates", "resume", "schema.json")

METADATA = {
    "name": "resume_renderer",
    "description": ("JSON Resume 渲染器：resume.json（JSON Resume 标准schema）"
                    "+ 主题名 → .docx/.pdf。数据与样式分离，换主题不改数据；"
                    "三主题（clean_single/serif_classic/modern_two_col 双栏）；"
                    "PDF 双路径（LibreOffice 优先，回退 Word COM）。"),
    "category": "office",
    "version": "1.1.0",
}


def _load_theme(theme: str) -> Dict:
    path = os.path.join(THEMES_DIR, f"{theme}.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"主题不存在: {path}（可用: "
                                f"{', '.join(sorted(x[:-5] for x in os.listdir(THEMES_DIR) if x.endswith('.json')))}）")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _validate_resume(resume: Dict) -> str:
    """软校验：对齐 JSON Resume schema 的必要结构（不做全量 jsonschema 校验）。"""
    if not isinstance(resume, dict):
        return "resume 须为 JSON 对象"
    basics = resume.get("basics")
    if not isinstance(basics, dict):
        return "缺少 basics 节（JSON Resume schema 必需）"
    if not (basics.get("name") or basics.get("姓名")):
        return "basics.name 缺失"
    return ""


def _fmt_period(d: Dict) -> str:
    s = d.get("startDate") or ""
    e = d.get("endDate") or "至今"
    return f"{s} — {e}" if s else str(e)


def _add_section(doc, theme: Dict, key: str, resume: Dict):
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    F = theme["fonts"]
    items = resume.get(key) or []
    if key == "summary":
        summary = (resume.get("basics") or {}).get("summary")
        items = [summary] if summary else []
    if not items:
        return
    st_cfg = F["section_title"]
    p = doc.add_paragraph()
    r = p.add_run(theme["section_titles"].get(key, key))
    r.font.name = st_cfg["family"]
    r.font.size = Pt(st_cfg["size_pt"])
    r.font.bold = st_cfg.get("bold", True)
    r.font.color.rgb = RGBColor.from_string(st_cfg["color"])

    accent = theme.get("accent_color", "888888")
    bar = doc.add_paragraph()
    br = bar.add_run("─" * 24)
    br.font.color.rgb = RGBColor.from_string(accent)
    br.font.size = Pt(8)

    body_cfg, meta_cfg, item_cfg = F["body"], F["meta"], F["item_title"]

    def _run(par, text, cfg, bold=False):
        rr = par.add_run(str(text))
        rr.font.name = cfg["family"]
        rr.font.size = Pt(cfg["size_pt"])
        rr.font.color.rgb = RGBColor.from_string(cfg["color"])
        if bold or cfg.get("bold"):
            rr.font.bold = True
        return rr

    if key == "summary":
        doc_p = doc.add_paragraph()
        _run(doc_p, items[0], body_cfg)
        return
    if key == "skills":
        for it in items:
            par = doc.add_paragraph(style="List Bullet")
            _run(par, f"{it.get('name', '')}：{', '.join(it.get('keywords', []))}" if it.get("keywords")
                 else it.get("name", ""), body_cfg, bold=bool(it.get("keywords")))
        return
    if key == "languages":
        for it in items:
            par = doc.add_paragraph(style="List Bullet")
            _run(par, f"{it.get('language', '')}（{it.get('fluency', '')}）", body_cfg)
        return
    # work / education / projects：条目式
    for it in items:
        head = doc.add_paragraph()
        _run(head, it.get("position") or it.get("studyType") or it.get("name") or "", item_cfg, bold=True)
        org = it.get("company") or it.get("institution") or ""
        meta_p = doc.add_paragraph()
        _run(meta_p, f"{org} ｜ {_fmt_period(it)}", meta_cfg)
        if it.get("summary"):
            _run(doc.add_paragraph(), it["summary"], body_cfg)
        if it.get("highlights"):
            for h in it["highlights"]:
                _run(doc.add_paragraph(style="List Bullet"), h, body_cfg)


def render_docx(resume: Dict, theme: Dict, out_path: str) -> str:
    """按主题渲染 .docx（样式全部来自主题文件；395A-5 支持双栏布局）。"""
    import docx
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_SECTION_START
    from docx.oxml.ns import qn

    F = theme["fonts"]
    doc = docx.Document()
    mg = theme.get("page", {}).get("margin_cm", {})
    for sec in doc.sections:
        sec.top_margin = Cm(mg.get("top", 1.8))
        sec.bottom_margin = Cm(mg.get("bottom", 1.8))
        sec.left_margin = Cm(mg.get("left", 2.2))
        sec.right_margin = Cm(mg.get("right", 2.2))

    basics = resume.get("basics") or {}
    # 姓名头（双栏布局时页眉仍通栏）
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _cfg = F["name"]
    r = p.add_run(basics.get("name", ""))
    r.font.name = _cfg["family"]
    r.font.size = Pt(_cfg["size_pt"])
    r.font.bold = _cfg.get("bold", True)
    r.font.color.rgb = RGBColor.from_string(_cfg["color"])
    # 联系行
    profiles = " ｜ ".join(
        f"{pf.get('network', '')}: {pf.get('username', '')}" for pf in basics.get("profiles", []))
    contact = " ｜ ".join(x for x in [
        basics.get("email", ""), basics.get("phone", ""),
        basics.get("location", {}).get("city", "") if isinstance(basics.get("location"), dict) else "",
        profiles] if x)
    hp = doc.add_paragraph()
    hr = hp.add_run(contact)
    hr.font.name = F["headline"]["family"]
    hr.font.size = Pt(F["headline"]["size_pt"])
    hr.font.color.rgb = RGBColor.from_string(F["headline"]["color"])

    # ★ 395A-5: 双栏布局 —— 页眉后插入连续分节并设 cols=2，正文在双栏内排布
    layout = theme.get("layout") or {}
    if layout.get("type") == "two_col":
        sec2 = doc.add_section(WD_SECTION_START.CONTINUOUS)
        sect_pr = sec2._sectPr
        cols_list = sect_pr.xpath("./w:cols")
        cols = cols_list[0] if cols_list else None
        if cols is None:
            from docx.oxml import OxmlElement
            cols = OxmlElement("w:cols")
            sect_pr.append(cols)
        cols.set(qn("w:num"), str(int(layout.get("columns", 2))))
        # w:space 单位为二十分之一磅；0.8cm ≈ 453
        cols.set(qn("w:space"), str(int(float(layout.get("col_space_cm", 0.8)) * 567)))

    for key in theme.get("section_order", ["summary", "work", "education", "skills"]):
        _add_section(doc, theme, key, resume)

    doc.save(out_path)
    return out_path


def _find_soffice() -> str:
    """395A-5: 探测 LibreOffice soffice（PATH + 常见安装路径）。"""
    import shutil
    p = shutil.which("soffice")
    if p:
        return p
    candidates = [
        "C:/Program Files/LibreOffice/program/soffice.exe",
        "C:/Program Files (x86)/LibreOffice/program/soffice.exe",
        "D:/Program Files/LibreOffice/program/soffice.exe",
        "E:/LibreOffice/program/soffice.exe",
        "C:/LibreOffice/program/soffice.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""


def _docx_to_pdf(docx_path: str, pdf_path: str) -> Tuple[str, str]:
    """395A-5 PDF 双路径：LibreOffice 优先（减少 Word 依赖），不可用回退 Word COM。

    返回 (warn, engine)：warn 非空=失败原因；engine=libreoffice|word_com|""。
    """
    soffice = _find_soffice()
    if soffice:
        try:
            outdir = os.path.dirname(os.path.abspath(pdf_path))
            subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf", "--outdir", outdir,
                 os.path.abspath(docx_path)],
                capture_output=True, text=True, timeout=120)
            produced = os.path.join(
                outdir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
            if os.path.isfile(produced):
                if os.path.abspath(produced) != os.path.abspath(pdf_path):
                    os.replace(produced, pdf_path)
                return "", "libreoffice"
        except Exception:
            pass  # LibreOffice 路径失败，静默回退 Word COM（最终结果如实入 data）
    try:
        import win32com.client
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(os.path.abspath(docx_path))
        doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)  # wdFormatPDF
        doc.Close(False)
        word.Quit()
        return "", "word_com"
    except Exception as e:
        return f"pdf 跳过（LibreOffice 与 Word COM 均不可用: {str(e)[:80]}）", ""


def execute(resume_json: str = "", resume_path: str = "", theme: str = "clean_single",
            output_path: str = "", output_format: str = "docx") -> SkillResult:
    try:
        if resume_path:
            with open(resume_path, "r", encoding="utf-8") as f:
                resume_json = f.read()
        try:
            resume = json.loads(resume_json) if isinstance(resume_json, str) else resume_json
        except json.JSONDecodeError as e:
            return SkillResult(success=False, error=f"resume.json 解析失败: {e}")
        err = _validate_resume(resume)
        if err:
            return SkillResult(success=False,
                               error=f"{err}（schema 参考 data/templates/resume/schema.json，JSON Resume v1.0.0/MIT）")
        try:
            theme_cfg = _load_theme(theme)
        except FileNotFoundError as e:
            return SkillResult(success=False, error=str(e))

        base = output_path or os.path.join(
            tempfile.gettempdir(),
            f"resume_{(resume.get('basics') or {}).get('name', 'me')}_{int(time.time())}")
        docx_path = base if base.endswith(".docx") else base + ".docx"
        render_docx(resume, theme_cfg, docx_path)

        outputs, notes = [docx_path], []
        fmt = (output_format or "docx").lower()
        pdf_engine = ""
        if fmt in ("pdf", "both"):
            pdf_path = docx_path[:-5] + ".pdf"
            warn, pdf_engine = _docx_to_pdf(docx_path, pdf_path)
            if warn:
                notes.append(warn)
            else:
                outputs.append(pdf_path)
        return SkillResult(
            success=True,
            output=(f"简历渲染完成（主题 {theme}）: {' , '.join(outputs)}"
                    + (f"；PDF 引擎: {pdf_engine}" if pdf_engine else "")
                    + ("；" + "；".join(notes) if notes else "")),
            data={"outputs": outputs, "theme": theme,
                  "theme_file": os.path.join(THEMES_DIR, f"{theme}.json"),
                  "pdf_engine": pdf_engine, "notes": notes},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"resume_renderer 异常: {e}",
                           output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="resume_renderer",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "resume_json": {"type": "string", "description": "resume.json 内容字符串（JSON Resume schema）"},
                "resume_path": {"type": "string", "description": "resume.json 文件路径（与 resume_json 二选一）"},
                "theme": {"type": "string", "description": "主题名（data/templates/resume/themes/ 下纯样式文件：clean_single/serif_classic/modern_two_col）",
                          "default": "clean_single"},
                "output_path": {"type": "string", "description": "输出 .docx 路径"},
                "output_format": {"type": "string", "enum": ["docx", "pdf", "both"],
                                  "description": "docx(默认)/pdf(LibreOffice优先,回退Word COM)/both", "default": "docx"},
            },
        },
        handler=execute,
        category=METADATA["category"],
        timeout=60,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
