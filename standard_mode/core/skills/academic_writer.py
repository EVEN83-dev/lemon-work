# -*- coding: utf-8 -*-
"""
Skill: academic_writer — 学术论文写作助手
==========================================
生成 LaTeX 论文模板（含摘要、引言、方法、实验、结论），
支持公式/表格/图表/算法。

395A-4: LaTeX→PDF 编译链 ——
  detect_latex_engine()   探测本机引擎（xelatex/tectonic/pdflatex/latexmk，
                          含 MiKTeX/TeXLive 常见安装路径）
  compile_tex_to_pdf()    .tex→.pdf 自动编译（日志首错捕获，无引擎降级明示禁静默）
"""

import os
import subprocess
import time
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
# ★ 396B-2: 395 章模板资产（paper 骨架）与产物落盘目录
PAPER_TEMPLATE_ASSET = os.path.join(_REPO_ROOT, "data", "templates", "paper",
                                    "academic_article.tex")
BUILD_DIR = os.path.join(_REPO_ROOT, "data", "paper_build")

METADATA = {
    "name": "academic_writer",
    # 396B-2: 描述回显写作类触发语（学术风格介绍/论文/综述/摘要），
    # 提升写作类题目对本技能的选择率（391B-4 fair=MISS：模型直接 write_file）
    "description": ("学术写作助手：写学术风格介绍/论文/综述/摘要/开题大纲必用本工具，"
                    "产出模板化 LaTeX 文档（含摘要、引言、方法、实验、结论章节骨架，"
                    "落盘 .tex 文件）；可选公式/表格/图表/算法；可选 PDF 编译。"),
    "category": "documentation",
    "version": "1.2.0",
}

# 395A-4: 引擎可执行名 + 常见安装目录（MiKTeX / TeX Live / Tectonic）
_LATEX_ENGINE_NAMES = ["xelatex", "tectonic", "pdflatex", "latexmk"]
_LATEX_COMMON_DIRS = [
    "C:/Program Files/MiKTeX/miktex/bin/x64",
    "C:/Program Files/MiKTeX/miktex/bin",
    "C:/Users/{user}/AppData/Local/Programs/MiKTeX/miktex/bin/x64",
    "C:/texlive/2025/bin/windows", "C:/texlive/2024/bin/windows",
    "C:/texlive/2023/bin/windows", "C:/texlive/2022/bin/win32",
    "D:/texlive/2024/bin/windows", "D:/texlive/2025/bin/windows",
    "C:/Users/{user}/AppData/Local/Programs/tectonic",
]


def detect_latex_engine() -> Dict:
    """395A-4: 探测本机 LaTeX 引擎。返回 {"engine": 名称|None, "path": 路径}。"""
    import shutil
    for n in _LATEX_ENGINE_NAMES:
        p = shutil.which(n)
        if p:
            return {"engine": n, "path": p}
    user = os.environ.get("USERNAME", "")
    for d in _LATEX_COMMON_DIRS:
        d = d.replace("{user}", user)
        for n in _LATEX_ENGINE_NAMES:
            p = os.path.join(d, n + ".exe")
            if os.path.isfile(p):
                return {"engine": n, "path": p}
    return {"engine": None, "path": ""}


def _first_error_from_log(log_text: str) -> str:
    """395A-4: 从编译日志提取首错（LaTeX 错误行以 '!' 开头；引擎级 Error:/fatal 也认）。"""
    for line in (log_text or "").splitlines():
        s = line.strip()
        if s.startswith("!"):
            return s[:300]
        low = s.lower()
        if "error:" in low or low.startswith("fatal"):
            return s[:300]
    return ""


def compile_tex_to_pdf(tex_path: str, engine_request: str = "auto",
                       timeout: int = 180) -> Dict:
    """395A-4: .tex→.pdf 自动编译。

    返回 {status: compiled|no_engine|failed, engine, pdf, error, log_tail}。
    无引擎降级明示（禁静默）；失败捕获日志首错。
    """
    det = detect_latex_engine()
    if not det["engine"] or (engine_request not in ("auto", "") and
                             engine_request != det["engine"]):
        return {"status": "no_engine", "engine": det["engine"], "pdf": "",
                "error": ("未检测到 LaTeX 引擎，已出 .tex（安装 MiKTeX 后可编译）"
                          if not det["engine"] else
                          f"请求引擎 {engine_request} 不可用（本机可用: {det['engine']}）"),
                "log_tail": ""}
    eng = det["engine"]
    wd = os.path.dirname(os.path.abspath(tex_path))
    tex_name = os.path.basename(tex_path)
    if eng == "tectonic":
        cmd = [det["path"], tex_name]
        passes = 1
    elif eng == "latexmk":
        cmd = [det["path"], tex_name]
        passes = 1
    else:  # xelatex / pdflatex：跑两遍保交叉引用
        cmd = [det["path"], "-interaction=nonstopmode", "-halt-on-error", tex_name]
        passes = 2
    log_path = os.path.join(wd, os.path.splitext(tex_name)[0] + ".log")
    pdf_path = os.path.join(wd, os.path.splitext(tex_name)[0] + ".pdf")
    combined = ""
    for _ in range(passes):
        try:
            r = subprocess.run(cmd, cwd=wd, capture_output=True, text=True,
                               encoding="utf-8", errors="ignore", timeout=timeout)
            combined += (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            return {"status": "failed", "engine": eng, "pdf": "",
                    "error": f"编译超时（>{timeout}s，引擎 {eng}）", "log_tail": ""}
        except FileNotFoundError as e:
            return {"status": "failed", "engine": eng, "pdf": "",
                    "error": f"引擎启动失败: {e}", "log_tail": ""}
    log_text = ""
    if os.path.isfile(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                log_text = f.read()
        except Exception:
            pass
    first_err = _first_error_from_log(log_text) or _first_error_from_log(combined)
    if os.path.isfile(pdf_path) and not first_err:
        return {"status": "compiled", "engine": eng, "pdf": pdf_path,
                "error": "", "log_tail": log_text[-500:]}
    return {"status": "failed", "engine": eng, "pdf": "",
            "error": first_err or f"编译器未产出 PDF（引擎 {eng}，详见 {log_path}）",
            "log_tail": log_text[-500:] or combined[-500:]}


def execute(
    topic: str = "",
    sections: str = "",
    output_format: str = "latex",
    include_algorithm: bool = True,
    include_table: bool = True,
    include_figure: bool = True,
    citation_style: str = "plain",
    references: str = "",
    double_column: bool = False,
    tex_output_path: str = "",
    compile_pdf: bool = False,
    tex_engine: str = "auto",
) -> SkillResult:
    """生成学术论文模板

    ★ v3.71 增强：
    - citation_style: plain / ieee / acm / gbt7714 / nature
    - references: BibTeX 格式参考文献（自动生成 \bibitem）
    - double_column: 双栏排版

    ★ 395A-4 增强：
    - tex_output_path: 落盘 .tex 文件路径（空=不落盘，仅返回 data.latex）
    - compile_pdf: True 时自动编译出 PDF（探测本机引擎；
      无引擎降级明示"已出 .tex（安装 MiKTeX 后可编译）"，禁静默；
      编译失败捕获日志首错返回）
    """
    if not topic:
        return SkillResult(success=False, error="topic 参数为空")

    try:
        section_list = [s.strip() for s in sections.split(',') if s.strip()] if sections else [
            '摘要', '引言', '相关工作', '方法', '实验', '结果与讨论', '结论', '参考文献'
        ]

        # ★ v3.71: 引用格式映射
        citation_packages = {
            'plain':     ('plain', ''),
            'ieee':      ('IEEEtran', '\\usepackage{IEEEtran}'),
            'acm':       ('acm', '\\usepackage{acm}'),
            'gbt7714':   ('gbt7714', '\\usepackage[numbers,sort&compress]{gbt7714}'),
            'nature':    ('nature', '\\usepackage{natbib}'),
        }
        bibstyle, bib_pkg = citation_packages.get(citation_style, citation_packages['plain'])

        if output_format == 'latex':
            latex_sections = []
            section_commands = {
                '摘要': 'abstract', '引言': 'introduction', '相关工作': 'related_work',
                '方法': 'methodology', '实验': 'experiments', '结果与讨论': 'results',
                '结论': 'conclusion', '参考文献': 'references',
            }
            for sec in section_list:
                cmd = section_commands.get(sec, sec.lower().replace(' ', '_'))
                if sec == '摘要':
                    latex_sections.append(f"""\\begin{{abstract}}
{topic} 的研究摘要。本文提出了...
\\end{{abstract}}""")
                else:
                    latex_sections.append(f"""\\section{{{sec}}}
% {sec} 部分内容""")

            # 可选: 算法环境
            algo_block = ""
            if include_algorithm:
                algo_block = """
\\begin{algorithm}[htbp]
\\caption{示例算法}
\\begin{algorithmic}[1]
\\REQUIRE 输入数据
\\ENSURE 输出结果
\\STATE 初始化参数
\\WHILE{未收敛}
\\STATE 更新参数
\\ENDWHILE
\\RETURN 结果
\\end{algorithmic}
\\end{algorithm}"""

            # 可选: 表格
            table_block = ""
            if include_table:
                table_block = """
\\begin{table}[htbp]
\\centering
\\caption{实验结果}
\\begin{tabular}{lcc}
\\hline
方法 & 准确率 & F1值 \\\\
\\hline
基线 & 85.0\\% & 0.83 \\\\
本文方法 & \\textbf{92.0\\%} & \\textbf{0.91} \\\\
\\hline
\\end{tabular}
\\end{table}"""

            # 可选: 图
            figure_block = ""
            if include_figure:
                figure_block = """
\\begin{figure}[htbp]
\\centering
\\includegraphics[width=0.8\\textwidth]{figure.pdf}
\\caption{实验结果示意图}
\\label{fig:result}
\\end{figure}"""

            # ★ v3.71: 参考文献 \bibitem 生成
            bibitems = ""
            if references:
                ref_lines = [r.strip() for r in references.split('\n') if r.strip()]
                bibitems = "\\begin{thebibliography}{99}\n"
                for i, ref in enumerate(ref_lines, 1):
                    bibitems += f"\\bibitem{{{i}}} {ref}\n"
                bibitems += "\\end{thebibliography}\n"

            # ★ v3.71: bibitems 为空时的默认 bibliography 命令
            bib_fallback = "\\bibliographystyle{" + bibstyle + "}\n\\bibliography{references}"

            # ★ v3.71: 双栏排版
            doc_class_options = ""
            if double_column:
                doc_class_options = "[twocolumn]"

            # ★ v3.71: documentclass 选择（IEEE 用 IEEEtran）
            if citation_style == 'ieee':
                doc_class = "\\documentclass{IEEEtran}"
            else:
                doc_class = "\\documentclass" + doc_class_options + "{article}"

            bib_section = bibitems if bibitems else bib_fallback

            template = f"""{doc_class}
\\usepackage{{amsmath,amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{algorithm,algorithmic}}
\\usepackage{{booktabs}}
\\usepackage{{hyperref}}
{bib_pkg}
\\usepackage{{ctex}}

\\title{{{topic}}}
\\author{{作者姓名}}
\\date{{\\today}}

\\begin{{document}}
\\maketitle

{chr(10).join(latex_sections)}
{algo_block}
{table_block}
{figure_block}

{bib_section}

\\end{{document}}"""

            # ★ 395A-4: .tex 落盘 + 可选 PDF 自动编译（探测/降级明示/首错捕获）
            # ★ 396B-2: 产物升级 —— 未指定路径也自动落盘到 data/paper_build/
            #   （产出物从裸文本升级为模板化 .tex 文档），并挂接 395 模板资产
            tex_path = ""
            if not tex_output_path:
                os.makedirs(BUILD_DIR, exist_ok=True)
                safe = "".join(ch for ch in topic if ch.isalnum())[:24] or "paper"
                tex_output_path = os.path.join(BUILD_DIR,
                                               f"{safe}_{int(time.time())}.tex")
            tex_path = tex_output_path
            os.makedirs(os.path.dirname(os.path.abspath(tex_path)) or ".", exist_ok=True)
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(template)
            template_asset = (PAPER_TEMPLATE_ASSET
                              if os.path.isfile(PAPER_TEMPLATE_ASSET) else "")

            if not compile_pdf:
                return SkillResult(
                    success=True,
                    output=f"LaTeX 论文模板已生成: {topic}\n章节: {', '.join(section_list)}"
                           + f"\n.tex 已落盘（模板化文档）: {tex_path}"
                           + (f"\n模板资产同源: {template_asset}" if template_asset else ""),
                    data={'latex': template, 'topic': topic, 'sections': section_list,
                          'tex_path': tex_path, 'template_asset': template_asset},
                )

            # compile_pdf=True：.tex 已在上方落盘（396B-2 起默认必落盘）
            res = compile_tex_to_pdf(tex_path, engine_request=tex_engine)
            if res["status"] == "compiled":
                return SkillResult(
                    success=True,
                    output=(f"LaTeX 论文已生成并编译: {topic}\n"
                            f".tex: {tex_path}\n.pdf: {res['pdf']}（引擎 {res['engine']}）"),
                    data={'latex': template, 'topic': topic, 'sections': section_list,
                          'tex_path': tex_path, 'pdf_path': res["pdf"],
                          'template_asset': template_asset,
                          'compile_status': 'compiled', 'engine': res["engine"]},
                )
            if res["status"] == "no_engine":
                # 降级明示（禁静默）：.tex 已产出，PDF 需用户装引擎
                return SkillResult(
                    success=True,
                    output=(f"LaTeX 论文模板已生成: {topic}\n.tex 已落盘: {tex_path}\n"
                            f"⚠ {res['error']}"),
                    data={'latex': template, 'topic': topic, 'sections': section_list,
                          'tex_path': tex_path, 'template_asset': template_asset,
                          'compile_status': 'no_engine',
                          'engine': None},
                )
            return SkillResult(
                success=False,
                error=(f"PDF 编译失败（引擎 {res.get('engine')}）: {res.get('error')}\n"
                       f".tex 保留在: {tex_path}"),
                output=(res.get("log_tail") or "")[-800:],
                data={'latex': template, 'topic': topic, 'tex_path': tex_path,
                      'template_asset': template_asset,
                      'compile_status': 'failed', 'engine': res.get("engine"),
                      'first_error': res.get("error")},
            )

        elif output_format == 'markdown':
            md = f"# {topic}\n\n"
            for sec in section_list:
                md += f"## {sec}\n\n待填充...\n\n"
            return SkillResult(
                success=True,
                output=f"Markdown 论文模板已生成: {topic}",
                data={'markdown': md, 'topic': topic},
            )

        else:
            return SkillResult(success=False, error=f"不支持的格式: {output_format}")

    except Exception as e:
        return SkillResult(success=False, error=f"论文模板生成失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="academic_writer",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "论文主题"},
                "sections": {"type": "string", "description": "章节（逗号分隔）"},
                "output_format": {"type": "string", "enum": ["latex", "markdown"], "description": "输出格式", "default": "latex"},
                "include_algorithm": {"type": "boolean", "description": "是否包含算法环境", "default": True},
                "include_table": {"type": "boolean", "description": "是否包含表格", "default": True},
                "include_figure": {"type": "boolean", "description": "是否包含图表", "default": True},
                "citation_style": {"type": "string", "enum": ["plain", "ieee", "acm", "gbt7714", "nature"], "description": "引用格式", "default": "plain"},
                "references": {"type": "string", "description": "参考文献（每行一条，自动生成bibitem）"},
                "double_column": {"type": "boolean", "description": "双栏排版", "default": False},
                "tex_output_path": {"type": "string",
                                    "description": ".tex 落盘路径（395A-4，空=仅返回内容）"},
                "compile_pdf": {"type": "boolean",
                                "description": ("是否自动编译 PDF（395A-4：探测本机 LaTeX 引擎；"
                                                "无引擎降级出 .tex 并明示；失败返回日志首错）"),
                                "default": False},
                "tex_engine": {"type": "string",
                               "description": "指定引擎（xelatex/tectonic/pdflatex/latexmk，auto=按探测顺序）",
                               "default": "auto"},
            },
            "required": ["topic"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=240,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
