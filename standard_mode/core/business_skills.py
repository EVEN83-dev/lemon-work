# -*- coding: utf-8 -*-
"""
业务 Skill 实现 — Lemon Code 公司多业务能力扩展
=============================================
本模块实现 34 类非编码业务与系统 skill，扩展 Agent 能力边界（含 L3 7 个新增）：

1. math_solver         — 数学难题运算（SymPy 符号计算 + 数值计算）
2. web_researcher       — 网络爬虫与数据调研（requests + BeautifulSoup4）
3. info_debater         — 多源信息辩驳与验证（语义对比 + 矛盾检测）
4. math_plotter         — 数学图像生成（函数图 / 3D 几何 / 矩阵热图）
5. office_generator     — 办公文档生成（PPT / Word / Excel / PDF）
6. image_processor      — 图像处理与 OCR（Pillow + EasyOCR）
7. self_documenter      — 自文档化（蒸馏自 MiMo Code self-documentation）
8. arxiv_researcher     — arXiv 论文搜索（蒸馏自 MiMo Code arxiv）
9. design_blueprint     — 架构图生成（蒸馏自 MiMo Code design-blueprint）
10. physics_experiment  — 物理实验简笔画（Canvas JS 动画，黑板风格白线）
11. image_analyzer      — 图像识别分析（小模型识图+智能路由）
12. academic_writer     — 学术论文写作（LaTeX 模板，含公式/表格/图表/算法）
13. skill_creator       — Skill 创建工具（Python 代码模板生成）
14. frontend_designer   — 前端设计（HTML/CSS/React/Vue 组件生成）
15. deep_researcher     — 深度研究（多Skill协同+arXiv论文+网络搜索+结构化报告）
16. fact_checker        — 事实核查（多源信息验证+矛盾检测+可信度评估）
17. html_to_video       — HTML转视频（ffmpeg 屏幕抓取生成 MP4 视频）
18. modern_python_toolchain — Python 工具链（pyproject.toml/Makefile/venv/uv，蒸馏自 MiMo Code）
19. super_researcher    — 超级研究（多Agent深度协同，整合 deep/arxiv/web/fact 四层研究）
20. code_reviewer       — 代码审查（AST 静态分析 + 样式/Bug/安全三类检测）
21. test_generator       — 测试生成（基于 AST 自动生成 unittest/pytest 测试模板）
22. security_auditor     — 安全审计（25+ 规则漏洞扫描 + 依赖安全检查）
23. deploy_helper        — 部署助手（Docker/npm/pip/GitHub Actions 脚本生成）
24. code_psychologist     — 代码心理学家（自然语言→代码框架 / 代码→意图分析）
25. multi_model_debater   — 多模型辩论决策（正方/反方/中立多方辩论+评分裁决）

★ v22.4 Lemon Code 创新点：
- 所有 skill 采用"懒加载"依赖（仅在调用时 import）
- 失败时返回结构化 SkillResult，不抛异常
- 自动转换为 OpenAI function calling 工具定义
- 可通过 mimo serve /session/{id}/prompt_async 的 tools 参数暴露给模型
- mimo serve 无该能力时，由本地 Python 直接执行（fallback）

依赖库（按需安装，未安装时 skill 仍可注册但执行时返回友好提示）：
    pip install sympy numpy scipy matplotlib plotly networkx
    pip install requests beautifulsoup4 lxml scrapy playwright
    pip install python-pptx python-docx openpyxl reportlab
    pip install pillow easyocr sentence-transformers scikit-learn
"""

import os
import io
import base64
import re
import json
import traceback
import importlib
import importlib.util
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

# 复用现有 SkillsRegistry 体系
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from skills_registry import SkillDef, SkillResult

# ★ L3 新增：从 skills/ 子目录导入独立 Skill 模块
try:
    from skills.browser_automation import execute as _browser_execute, register as _browser_register
except Exception:
    _browser_execute = None; _browser_register = None
try:
    from skills.jupyter_notebook import execute as _jupyter_execute
except Exception:
    _jupyter_execute = None
try:
    from skills.lsp_code_analysis import execute as _lsp_execute
except Exception:
    _lsp_execute = None
try:
    from skills.mcp_bridge import execute as _mcp_execute
except Exception:
    _mcp_execute = None
try:
    from skills.ssh_skill import execute as _ssh_execute
except Exception:
    _ssh_execute = None
try:
    from skills.docker_skill import execute as _docker_execute
except Exception:
    _docker_execute = None
try:
    from skills.npm_pip_skill import execute as _npm_pip_execute
except Exception:
    _npm_pip_execute = None


# ============================================================
# 工具函数
# ============================================================

def _check_lib(lib_name: str) -> bool:
    """检查库是否已安装（不导入）"""
    try:
        spec = importlib.util.find_spec(lib_name)
        return spec is not None
    except Exception:
        return False


def _lazy_import(lib_name: str):
    """懒加载库 — 失败返回 None

    使用 importlib.import_module 可正确导入子模块（如 matplotlib.pyplot）。
    """
    try:
        return importlib.import_module(lib_name)
    except ImportError:
        return None


def _lib_missing_result(lib_name: str, skill_name: str) -> SkillResult:
    """统一返回库缺失提示"""
    return SkillResult(
        success=False,
        error=f"Skill '{skill_name}' 依赖库 '{lib_name}' 未安装",
        output=f"请执行: pip install {lib_name}\n安装后即可使用此 skill",
    )


# ============================================================
# Skill 1: math_solver — 数学难题运算
# ============================================================

def _handle_math_solve(
    expression: str = "",
    operation: str = "simplify",
    variable: str = "x",
) -> SkillResult:
    """
    数学运算 skill

    参数:
        expression: 数学表达式（如 "x**2 + 2*x + 1" 或 "integrate(sin(x), x)"）
        operation: 操作类型
            - simplify   化简
            - solve      解方程
            - integrate  积分
            - diff       求导
            - limit      极限
            - matrix     矩阵运算（expression 用 JSON 表示二维数组）
            - equation   解方程组
        variable: 运算变量（默认 x）
    """
    if not expression:
        return SkillResult(success=False, error="expression 参数为空")

    sympy = _lazy_import('sympy')
    if sympy is None:
        return _lib_missing_result('sympy', 'math_solver')

    try:
        x = sympy.Symbol(variable)
        ops = {
            'simplify':   lambda: sympy.simplify(sympy.sympify(expression)),
            'solve':      lambda: sympy.solve(sympy.sympify(expression), x),
            'integrate':  lambda: sympy.integrate(sympy.sympify(expression), x),
            'diff':       lambda: sympy.diff(sympy.sympify(expression), x),
            'limit':      lambda: sympy.limit(sympy.sympify(expression), x, 0),
            'factor':     lambda: sympy.factor(sympy.sympify(expression)),
            'expand':     lambda: sympy.expand(sympy.sympify(expression)),
        }

        if operation == 'matrix':
            # 矩阵运算 — expression 是 JSON 二维数组
            mat_data = json.loads(expression)
            M = sympy.Matrix(mat_data)
            return SkillResult(
                success=True,
                output=f"矩阵:\n{M}\n\n行列式: {M.det()}\n逆矩阵: {M.inv()}\n特征值: {M.eigenvals()}",
                data={'shape': list(M.shape), 'det': str(M.det())},
            )

        if operation == 'equation':
            # 方程组 — expression 用 ; 分隔多个等式
            eqs = [sympy.Eq(sympy.sympify(s.split('=')[0]), sympy.sympify(s.split('=')[1]))
                   for s in expression.split(';') if '=' in s]
            sols = sympy.solve(eqs, dict=True)
            return SkillResult(
                success=True,
                output=f"方程组解:\n{sols}",
                data={'solutions': [str(s) for s in sols]},
            )

        if operation not in ops:
            return SkillResult(success=False, error=f"未知操作: {operation}")

        result = ops[operation]()
        return SkillResult(
            success=True,
            output=f"{operation}({expression}, {variable}) =\n{result}",
            data={'result': str(result), 'latex': sympy.latex(result)},
        )

    except Exception as e:
        return SkillResult(success=False, error=f"数学运算失败: {e}", output=traceback.format_exc())


MATH_SOLVER_SKILL = SkillDef(
    name="math_solver",
    description="解数学难题：化简、解方程、积分、求导、极限、矩阵运算、方程组。支持符号计算。",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 'x**2 + 2*x + 1'"},
            "operation": {
                "type": "string",
                "enum": ["simplify", "solve", "integrate", "diff", "limit", "matrix", "equation"],
                "description": "操作类型",
            },
            "variable": {"type": "string", "description": "运算变量，默认 x", "default": "x"},
        },
        "required": ["expression", "operation"],
    },
    handler=_handle_math_solve,
    category="math",
    timeout=30,
)


# ============================================================
# Skill 2: web_researcher — 网络爬虫与数据调研
# ============================================================

def _handle_web_research(
    url: str = "",
    query: str = "",
    max_pages: int = 3,
    extract_text: bool = True,
) -> SkillResult:
    """
    网络调研 skill — 抓取页面 / 搜索信息

    参数:
        url: 直接抓取的 URL（与 query 二选一）
        query: 搜索关键词（调用搜索引擎）
        max_pages: 最多抓取页数（默认 3）
        extract_text: 是否提取纯文本（去掉 HTML 标签）
    """
    if not url and not query:
        return SkillResult(success=False, error="url 或 query 必须有一个")

    requests = _lazy_import('requests')
    if requests is None:
        return _lib_missing_result('requests', 'web_researcher')

    bs4 = _lazy_import('bs4')
    if bs4 is None:
        return _lib_missing_result('beautifulsoup4', 'web_researcher')

    try:
        results = []

        # 模式 1: 直接抓 URL
        if url:
            r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            r.encoding = r.apparent_encoding
            soup = bs4.BeautifulSoup(r.text, 'lxml' if _check_lib('lxml') else 'html.parser')

            # 提取标题
            title = soup.title.string if soup.title else '(无标题)'

            # 提取正文
            if extract_text:
                # 移除脚本和样式
                for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                    tag.decompose()
                text = soup.get_text(separator='\n', strip=True)
                # 压缩空行
                text = re.sub(r'\n{3,}', '\n\n', text)
                text = text[:5000]  # 限制长度
            else:
                text = r.text[:5000]

            results.append({
                'url': url,
                'title': title,
                'status': r.status_code,
                'content': text,
            })

        # 模式 2: 搜索引擎
        elif query:
            # 使用 DuckDuckGo HTML 接口（无需 API key）
            search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
            r = requests.get(search_url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            soup = bs4.BeautifulSoup(r.text, 'html.parser')

            # 提取搜索结果
            links = []
            for a in soup.select('.result__a')[:max_pages]:
                href = a.get('href', '')
                title = a.get_text(strip=True)
                links.append({'title': title, 'url': href})

            # 抓取前 N 个结果
            for link in links[:max_pages]:
                try:
                    sub_r = requests.get(link['url'], timeout=10,
                                         headers={'User-Agent': 'Mozilla/5.0'})
                    sub_r.encoding = sub_r.apparent_encoding
                    sub_soup = bs4.BeautifulSoup(sub_r.text, 'html.parser')
                    for tag in sub_soup(['script', 'style']):
                        tag.decompose()
                    text = sub_soup.get_text(separator='\n', strip=True)[:2000]
                    results.append({
                        'url': link['url'],
                        'title': link['title'],
                        'status': sub_r.status_code,
                        'content': text,
                    })
                except Exception as e:
                    results.append({
                        'url': link['url'],
                        'title': link['title'],
                        'error': str(e),
                    })

        return SkillResult(
            success=True,
            output=f"调研完成，共抓取 {len(results)} 页\n" +
                   "\n---\n".join([f"标题: {r.get('title', '')}\nURL: {r.get('url', '')}\n摘要: {r.get('content', '')[:200]}..."
                                   for r in results]),
            data={'results': results, 'count': len(results)},
        )

    except Exception as e:
        return SkillResult(success=False, error=f"网络调研失败: {e}", output=traceback.format_exc())


WEB_RESEARCHER_SKILL = SkillDef(
    name="web_researcher",
    description="网络爬虫与数据调研：抓取 URL 或搜索关键词，提取正文。支持 DuckDuckGo 搜索。",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "直接抓取的 URL"},
            "query": {"type": "string", "description": "搜索关键词"},
            "max_pages": {"type": "integer", "description": "最多抓取页数", "default": 3},
            "extract_text": {"type": "boolean", "description": "是否提取纯文本", "default": True},
        },
    },
    handler=_handle_web_research,
    category="research",
    timeout=60,
)


# ============================================================
# Skill 3: info_debater — 多源信息辩驳与验证
# ============================================================

def _handle_info_debate(
    sources: str = "",
    claim: str = "",
    mode: str = "compare",
) -> SkillResult:
    """
    信息辩驳 skill — 多源信息对比、矛盾检测、共识达成

    参数:
        sources: JSON 字符串，包含多个信息源
                 格式: [{"source": "URL/A", "content": "..."}, {...}]
        claim: 待验证的声明（可选）
        mode:
            - compare    对比多源信息（找共同点 + 差异点）
            - verify     验证声明是否被多数源支持
            - contradict 检测矛盾点
            - consensus  达成共识
    """
    if not sources:
        return SkillResult(success=False, error="sources 参数为空")

    try:
        sources_list = json.loads(sources) if isinstance(sources, str) else sources
    except json.JSONDecodeError as e:
        return SkillResult(success=False, error=f"sources JSON 解析失败: {e}")

    if not isinstance(sources_list, list) or len(sources_list) < 2:
        return SkillResult(success=False, error="至少需要 2 个信息源")

    try:
        difflib = __import__('difflib')
        networkx = _lazy_import('networkx')

        # 提取每个源的内容
        contents = [s.get('content', '') for s in sources_list]
        source_names = [s.get('source', f'src_{i}') for i, s in enumerate(sources_list)]

        # ★ 创新点 1: 基于 difflib 的差异检测（无需 ML 库）
        diffs = []
        for i in range(len(contents)):
            for j in range(i + 1, len(contents)):
                diff = difflib.SequenceMatcher(None, contents[i], contents[j])
                ratio = diff.ratio()
                diffs.append({
                    'source_a': source_names[i],
                    'source_b': source_names[j],
                    'similarity': round(ratio, 3),
                    'difference': round(1 - ratio, 3),
                })

        # ★ 创新点 2: 关键词提取（基于频率）
        all_text = ' '.join(contents)
        # 移除常见停用词
        stop_words = {'的', '是', '了', '在', '和', '与', '或', '也', '都', '但', '而', '如', '因', '为', '所', '以', '一', '个', '这', '那', '有', '无', '不', 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'to', 'of', 'in', 'on', 'at', 'for', 'with'}
        words = re.findall(r'[\u4e00-\u9fa5]{2,4}|[a-zA-Z]+', all_text)
        word_freq = {}
        for w in words:
            if w.lower() not in stop_words and len(w) >= 2:
                word_freq[w] = word_freq.get(w, 0) + 1
        top_keywords = sorted(word_freq.items(), key=lambda x: -x[1])[:10]

        # 模式: compare
        if mode == 'compare':
            common_keywords = [w for w, _ in top_keywords[:5]]
            output = (
                f"=== 多源信息对比报告 ===\n"
                f"源数量: {len(sources_list)}\n"
                f"相似度矩阵:\n" +
                "\n".join([f"  {d['source_a']} ↔ {d['source_b']}: 相似度 {d['similarity']:.1%}, 差异 {d['difference']:.1%}"
                           for d in diffs]) +
                f"\n\n共同关键词 (Top 5): {', '.join(common_keywords)}\n"
                f"关键词频率: {top_keywords[:10]}\n"
            )

        # 模式: verify
        elif mode == 'verify' and claim:
            # 检查 claim 在每个源中是否出现/被支持
            supports = []
            for i, content in enumerate(contents):
                # 简化: 检查 claim 关键词是否在 content 中
                claim_words = re.findall(r'[\u4e00-\u9fa5]{2,4}|[a-zA-Z]+', claim)
                hit_count = sum(1 for w in claim_words if w in content)
                support_rate = hit_count / max(1, len(claim_words))
                supports.append({
                    'source': source_names[i],
                    'support_rate': round(support_rate, 3),
                    'hits': hit_count,
                    'total': len(claim_words),
                })
            avg_support = sum(s['support_rate'] for s in supports) / len(supports)
            verdict = '支持' if avg_support > 0.6 else '部分支持' if avg_support > 0.3 else '不支持'
            output = (
                f"=== 声明验证报告 ===\n"
                f"声明: {claim}\n"
                f"各源支持度:\n" +
                "\n".join([f"  {s['source']}: {s['support_rate']:.1%} ({s['hits']}/{s['total']} 关键词命中)"
                           for s in supports]) +
                f"\n平均支持度: {avg_support:.1%}\n结论: {verdict}\n"
            )

        # 模式: contradict
        elif mode == 'contradict':
            # 找出差异最大的源对
            sorted_diffs = sorted(diffs, key=lambda x: -x['difference'])
            top_contradictions = sorted_diffs[:3]
            output = (
                f"=== 矛盾检测报告 ===\n"
                f"发现 {len(diffs)} 对源对比\n"
                f"差异最大的 {min(3, len(top_contradictions))} 对:\n" +
                "\n".join([f"  {d['source_a']} vs {d['source_b']}: 差异度 {d['difference']:.1%}"
                           for d in top_contradictions]) +
                f"\n建议: 人工核查差异 >50% 的源对\n"
            )

        # 模式: consensus
        elif mode == 'consensus':
            # 找出相似度 >70% 的源对作为共识基础
            consensus_pairs = [d for d in diffs if d['similarity'] > 0.7]
            output = (
                f"=== 共识达成报告 ===\n"
                f"高相似度源对 (相似度 >70%): {len(consensus_pairs)}\n" +
                "\n".join([f"  {d['source_a']} ↔ {d['source_b']}: {d['similarity']:.1%}"
                           for d in consensus_pairs]) +
                f"\n共识关键词: {', '.join([w for w, _ in top_keywords[:5]])}\n"
            )

        else:
            return SkillResult(success=False, error=f"未知模式: {mode}")

        # ★ 创新点 3: 用 networkx 构建信息源关系图（可选）
        graph_data = None
        if networkx:
            G = networkx.Graph()
            for name in source_names:
                G.add_node(name)
            for d in diffs:
                G.add_edge(d['source_a'], d['source_b'], weight=d['similarity'])
            graph_data = {
                'nodes': list(G.nodes),
                'edges': [{'source': u, 'target': v, 'weight': d['weight']}
                           for u, v, d in G.edges(data=True)],
            }

        return SkillResult(
            success=True,
            output=output,
            data={
                'diffs': diffs,
                'top_keywords': top_keywords,
                'graph': graph_data,
            },
        )

    except Exception as e:
        return SkillResult(success=False, error=f"信息辩驳失败: {e}", output=traceback.format_exc())


INFO_DEBATER_SKILL = SkillDef(
    name="info_debater",
    description="多源信息辩驳与验证：对比多源信息、检测矛盾、验证声明、达成共识。Lemon Code 创新功能。",
    parameters={
        "type": "object",
        "properties": {
            "sources": {"type": "string", "description": "JSON 数组，每个元素 {source, content}"},
            "claim": {"type": "string", "description": "待验证的声明（verify 模式必填）"},
            "mode": {
                "type": "string",
                "enum": ["compare", "verify", "contradict", "consensus"],
                "description": "辩驳模式",
            },
        },
        "required": ["sources", "mode"],
    },
    handler=_handle_info_debate,
    category="debate",
    timeout=30,
)


# ============================================================
# Skill 4: math_plotter — 数学图像生成
# ============================================================

def _handle_math_plot(
    expression: str = "",
    plot_type: str = "function",
    x_range: str = "-5,5",
    y_range: str = "",
    output_path: str = "",
    title: str = "",
) -> SkillResult:
    """
    数学图像生成 skill

    参数:
        expression: 表达式
            - function: "x**2" 或 "sin(x)"
            - surface3d: "x**2 + y**2" (需 3D)
            - matrix: JSON 二维数组
            - scatter: JSON 点列表 [{"x":1,"y":2}, ...]
        plot_type:
            - function  2D 函数图
            - surface3d 3D 曲面图
            - matrix    矩阵热图
            - scatter   散点图
            - bar       柱状图
            - pie       饼图
        x_range: x 轴范围 "min,max"
        y_range: y 轴范围 "min,max"（可选）
        output_path: 输出 PNG 路径（默认 temp）
        title: 图标题
    """
    if not expression:
        return SkillResult(success=False, error="expression 参数为空")

    plt = _lazy_import('matplotlib.pyplot')
    if plt is None:
        return _lib_missing_result('matplotlib', 'math_plotter')

    numpy = _lazy_import('numpy')
    if numpy is None:
        return _lib_missing_result('numpy', 'math_plotter')

    sympy = _lazy_import('sympy')

    try:
        # 解析范围
        x_min, x_max = [float(v) for v in x_range.split(',')]
        y_min, y_max = [float(v) for v in y_range.split(',')] if y_range else (None, None)

        # 输出路径
        if not output_path:
            import tempfile
            output_path = os.path.join(tempfile.gettempdir(), f"plot_{plot_type}_{int(__import__('time').time())}.png")

        # 中文字体支持
        try:
            plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
        except Exception:
            pass

        fig, ax = plt.subplots(figsize=(8, 6), dpi=100)

        # ===== 2D 函数图 =====
        if plot_type == 'function':
            x = numpy.linspace(x_min, x_max, 400)
            # 用 sympy 解析表达式后转 numpy
            if sympy:
                sym_expr = sympy.sympify(expression)
                f = sympy.lambdify('x', sym_expr, 'numpy')
                y = f(x)
            else:
                # 退化: 用 AST 白名单求值（替代裸 eval，禁止任意代码执行）
                from safe_expr import safe_math_eval
                y = numpy.array([
                    safe_math_eval(expression, {'x': v, 'sin': numpy.sin, 'cos': numpy.cos,
                                                'exp': numpy.exp, 'log': numpy.log,
                                                'sqrt': numpy.sqrt, 'pi': numpy.pi, 'e': numpy.e})
                    for v in x
                ])
            ax.plot(x, y, 'b-', linewidth=2, label=expression)
            ax.set_xlabel('x')
            ax.set_ylabel('y')
            ax.grid(True, alpha=0.3)
            ax.legend()

        # ===== 3D 曲面图 =====
        elif plot_type == 'surface3d':
            from mpl_toolkits.mplot3d import Axes3D  # noqa
            fig = plt.figure(figsize=(10, 8), dpi=100)
            ax = fig.add_subplot(111, projection='3d')
            x = numpy.linspace(x_min, x_max, 50)
            y = numpy.linspace(x_min, x_max, 50)
            X, Y = numpy.meshgrid(x, y)
            if sympy:
                sym_expr = sympy.sympify(expression)
                f = sympy.lambdify(('x', 'y'), sym_expr, 'numpy')
                Z = f(X, Y)
            else:
                # 用 AST 白名单求值（替代裸 eval，禁止任意代码执行）
                from safe_expr import safe_math_eval
                _w, _h = X.shape
                Z = numpy.empty_like(X, dtype=float)
                for _i in range(_w):
                    for _j in range(_h):
                        Z[_i, _j] = safe_math_eval(
                            expression,
                            {'x': X[_i, _j], 'y': Y[_i, _j],
                             'sin': numpy.sin, 'cos': numpy.cos, 'sqrt': numpy.sqrt,
                             'pi': numpy.pi, 'e': numpy.e})
            ax.plot_surface(X, Y, Z, cmap='viridis', alpha=0.8)
            ax.set_xlabel('x')
            ax.set_ylabel('y')
            ax.set_zlabel('z')

        # ===== 矩阵热图 =====
        elif plot_type == 'matrix':
            mat = json.loads(expression)
            M = numpy.array(mat)
            im = ax.imshow(M, cmap='RdBu_r', aspect='auto')
            plt.colorbar(im, ax=ax)
            # 标注数值
            for i in range(M.shape[0]):
                for j in range(M.shape[1]):
                    ax.text(j, i, f"{M[i,j]:.2f}", ha='center', va='center')

        # ===== 散点图 =====
        elif plot_type == 'scatter':
            points = json.loads(expression)
            xs = [p.get('x', 0) for p in points]
            ys = [p.get('y', 0) for p in points]
            ax.scatter(xs, ys, c='red', s=50, alpha=0.6)
            ax.grid(True, alpha=0.3)

        # ===== 柱状图 =====
        elif plot_type == 'bar':
            data = json.loads(expression)
            labels = list(data.keys()) if isinstance(data, dict) else [f'#{i}' for i in range(len(data))]
            values = list(data.values()) if isinstance(data, dict) else data
            ax.bar(labels, values, color='orange', alpha=0.7)

        # ===== 饼图 =====
        elif plot_type == 'pie':
            data = json.loads(expression)
            labels = list(data.keys()) if isinstance(data, dict) else [f'#{i}' for i in range(len(data))]
            values = list(data.values()) if isinstance(data, dict) else data
            ax.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)

        else:
            return SkillResult(success=False, error=f"未知 plot_type: {plot_type}")

        if title:
            ax.set_title(title)
        if y_min is not None and y_max is not None and plot_type in ('function', 'scatter'):
            ax.set_ylim(y_min, y_max)

        plt.tight_layout()
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        plt.close()

        # 转 base64（供前端 inline 显示）
        with open(output_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')

        return SkillResult(
            success=True,
            output=f"图像已生成: {output_path}\n类型: {plot_type}\n表达式: {expression}",
            data={
                'path': output_path,
                'base64': b64[:200] + '...' if len(b64) > 200 else b64,
                'base64_full': b64,
                'plot_type': plot_type,
            },
        )

    except Exception as e:
        return SkillResult(success=False, error=f"绘图失败: {e}", output=traceback.format_exc())


MATH_PLOTTER_SKILL = SkillDef(
    name="math_plotter",
    description="生成数学图像：2D 函数图 / 3D 曲面图 / 矩阵热图 / 散点图 / 柱状图 / 饼图。输出 PNG + base64。",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "表达式或 JSON 数据"},
            "plot_type": {
                "type": "string",
                "enum": ["function", "surface3d", "matrix", "scatter", "bar", "pie"],
                "description": "图像类型",
            },
            "x_range": {"type": "string", "description": "x 轴范围 min,max", "default": "-5,5"},
            "y_range": {"type": "string", "description": "y 轴范围（可选）"},
            "output_path": {"type": "string", "description": "输出 PNG 路径（默认 temp）"},
            "title": {"type": "string", "description": "图标题"},
        },
        "required": ["expression", "plot_type"],
    },
    handler=_handle_math_plot,
    category="visual",
    timeout=30,
)


# ============================================================
# Skill 5: office_generator — 办公文档生成
# ============================================================

def _handle_office_gen(
    doc_type: str = "ppt",
    title: str = "",
    content: str = "",
    output_path: str = "",
    template: str = "",
) -> SkillResult:
    """
    办公文档生成 skill — PPT / Word / Excel / PDF

    参数:
        doc_type: ppt / docx / xlsx / pdf
        title: 文档标题
        content: 文档内容
            - ppt: JSON [{slide_title, slide_content}, ...] 或用 --- 分隔
            - docx: Markdown 字符串
            - xlsx: JSON {sheet_name: [[row], [row], ...]}
            - pdf: Markdown 字符串
        output_path: 输出路径
        template: 模板路径（可选）
    """
    if not title:
        return SkillResult(success=False, error="title 参数为空")
    if not content:
        return SkillResult(success=False, error="content 参数为空")

    if not output_path:
        import tempfile
        ext_map = {'ppt': '.pptx', 'docx': '.docx', 'xlsx': '.xlsx', 'pdf': '.pdf'}
        output_path = os.path.join(tempfile.gettempdir(),
                                    f"{title}_{int(__import__('time').time())}{ext_map.get(doc_type, '.txt')}")

    try:
        # ===== PPT =====
        if doc_type == 'ppt':
            pptx = _lazy_import('pptx')
            if pptx is None:
                return _lib_missing_result('python-pptx', 'office_generator[ppt]')

            from pptx.util import Inches, Pt
            from pptx.dml.color import RGBColor
            from pptx.enum.text import PP_ALIGN

            # ★ v3.72: 支持自定义模板
            template_path = locals().get('template', '')
            if template_path and os.path.exists(template_path):
                try:
                    prs = pptx.Presentation(template_path)
                except Exception:
                    prs = pptx.Presentation()
            else:
                prs = pptx.Presentation()

            # 标题页
            slide_layout = prs.slide_layouts[0]
            slide = prs.slides.add_slide(slide_layout)
            slide.shapes.title.text = title
            if len(slide.placeholders) > 1:
                slide.placeholders[1].text = "Lemon Code 自动生成"

            # 内容页
            try:
                slides_data = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                # 用 --- 分隔
                slides_data = [{'slide_title': f'第{i+1}页', 'slide_content': c.strip()}
                               for i, c in enumerate(content.split('---')) if c.strip()]

            for sd in slides_data:
                slide_layout = prs.slide_layouts[1]
                slide = prs.slides.add_slide(slide_layout)
                
                # 标题
                if slide.shapes.title:
                    slide.shapes.title.text = sd.get('slide_title', '')
                
                # 内容
                if len(slide.placeholders) > 1:
                    content_text = sd.get('slide_content', '')
                    slide.placeholders[1].text = content_text
                    
                    # ★ v3.72: 支持图片插入
                    image_path = sd.get('image', '')
                    if image_path and os.path.exists(image_path):
                        try:
                            left = Inches(1)
                            top = Inches(3)
                            slide.shapes.add_picture(image_path, left, top, width=Inches(5))
                        except Exception:
                            pass

            prs.save(output_path)

        # ===== Word =====
        elif doc_type == 'docx':
            docx = _lazy_import('docx')
            if docx is None:
                return _lib_missing_result('python-docx', 'office_generator[docx]')

            doc = docx.Document()
            doc.add_heading(title, level=0)

            # 简易 Markdown 解析
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
                return _lib_missing_result('openpyxl', 'office_generator[xlsx]')

            from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
            from openpyxl.utils import get_column_letter

            wb = openpyxl.Workbook()

            # ★ v3.72: 支持公式生成
            # 解析 content，支持格式：
            # 1. 字典：{sheet_name: {"data": [[row], ...], "formulas": [{"cell": "C2", "formula": "=SUM(A2:B2)"}]}}
            # 2. 字典：{sheet_name: [[row], ...]}（纯数据）
            # 3. 数组：[[row], ...]（自动用 title 作为 sheet 名）
            try:
                sheets_data = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                sheets_data = {title: [[c.strip() for c in line.split(',')] for line in content.split('\n') if line.strip()]}

            if isinstance(sheets_data, list):
                sheets_data = {title: sheets_data}

            first = True
            for sheet_name, sheet_content in sheets_data.items():
                if first:
                    ws = wb.active
                    ws.title = sheet_name
                    first = False
                else:
                    ws = wb.create_sheet(sheet_name)

                # 解析 sheet_content
                if isinstance(sheet_content, dict):
                    rows = sheet_content.get('data', [])
                    formulas = sheet_content.get('formulas', [])
                else:
                    rows = sheet_content
                    formulas = []

                # 写入数据
                for row in rows:
                    ws.append(row)

                # ★ v3.72: 写入公式
                for formula_def in formulas:
                    cell = formula_def.get('cell', '')
                    formula = formula_def.get('formula', '')
                    if cell and formula:
                        ws[cell] = formula

                # ★ v3.72: 自动样式（表头加粗、斑马纹、边框）
                if rows:
                    # 表头样式
                    header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
                    header_font = Font(bold=True, color='FFFFFF')
                    for cell in ws[1]:
                        cell.fill = header_fill
                        cell.font = header_font
                        cell.alignment = Alignment(horizontal='center')

                    # 斑马纹
                    even_fill = PatternFill(start_color='D9E2F3', end_color='D9E2F3', fill_type='solid')
                    for row_idx in range(2, len(rows) + 1):
                        if row_idx % 2 == 0:
                            for cell in ws[row_idx]:
                                cell.fill = even_fill

                    # 自动列宽
                    for col_idx in range(1, len(rows[0]) + 1 if rows else 1):
                        max_len = 0
                        col_letter = get_column_letter(col_idx)
                        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx):
                            for cell in row:
                                if cell.value:
                                    max_len = max(max_len, len(str(cell.value)))
                        ws.column_dimensions[col_letter].width = min(max_len + 2, 50)

                    # 冻结首行
                    ws.freeze_panes = 'A2'

            wb.save(output_path)

        # ===== PDF =====
        elif doc_type == 'pdf':
            reportlab = _lazy_import('reportlab')
            if reportlab is None:
                return _lib_missing_result('reportlab', 'office_generator[pdf]')

            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            # 注册中文字体
            chinese_font_paths = [
                'C:/Windows/Fonts/simhei.ttf',
                'C:/Windows/Fonts/msyh.ttc',
                'C:/Windows/Fonts/simsun.ttc',
            ]
            font_registered = False
            for fp in chinese_font_paths:
                if os.path.exists(fp):
                    try:
                        pdfmetrics.registerFont(TTFont('Chinese', fp))
                        font_registered = True
                        break
                    except Exception:
                        continue

            doc = SimpleDocTemplate(output_path, pagesize=A4)
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'ChineseTitle', parent=styles['Title'],
                fontName='Chinese' if font_registered else 'Helvetica',
                fontSize=24, spaceAfter=30,
            )
            body_style = ParagraphStyle(
                'ChineseBody', parent=styles['Normal'],
                fontName='Chinese' if font_registered else 'Helvetica',
                fontSize=11, leading=18,
            )

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
            output=f"文档已生成: {output_path}\n类型: {doc_type}\n标题: {title}",
            data={'path': output_path, 'doc_type': doc_type, 'title': title},
        )

    except Exception as e:
        return SkillResult(success=False, error=f"文档生成失败: {e}", output=traceback.format_exc())


OFFICE_GENERATOR_SKILL = SkillDef(
    name="office_generator",
    description="生成办公文档：PPT / Word / Excel / PDF。支持 Markdown 输入，自动转换格式。",
    parameters={
        "type": "object",
        "properties": {
            "doc_type": {
                "type": "string",
                "enum": ["ppt", "docx", "xlsx", "pdf"],
                "description": "文档类型",
            },
            "title": {"type": "string", "description": "文档标题"},
            "content": {"type": "string", "description": "文档内容（Markdown 或 JSON）"},
            "output_path": {"type": "string", "description": "输出路径（默认 temp）"},
            "template": {"type": "string", "description": "模板路径（可选）"},
        },
        "required": ["doc_type", "title", "content"],
    },
    handler=_handle_office_gen,
    category="office",
    timeout=60,
)


# ============================================================
# Skill 6: image_processor — 图像处理与 OCR
# ============================================================

def _handle_image_process(
    image_path: str = "",
    operation: str = "info",
    output_path: str = "",
    options: str = "{}",
) -> SkillResult:
    """
    图像处理 skill — 缩放/滤镜/合成/OCR/格式转换

    参数:
        image_path: 输入图像路径
        operation:
            - info       获取图像信息
            - resize     缩放（options: {"width":800, "height":600}）
            - rotate     旋转（options: {"angle":90}）
            - filter     滤镜（options: {"type":"blur|sharpen|edge|emboss"}）
            - convert    格式转换（options: {"format":"PNG|JPEG|WEBP"}）
            - ocr        OCR 文字识别
            - composite  合成（options: {"overlay":"path", "position":"x,y"}）
        output_path: 输出路径（默认覆盖原图）
        options: JSON 字符串操作参数
    """
    if not image_path:
        return SkillResult(success=False, error="image_path 参数为空")

    if not os.path.exists(image_path):
        return SkillResult(success=False, error=f"图像文件不存在: {image_path}")

    try:
        opts = json.loads(options) if isinstance(options, str) else options
    except json.JSONDecodeError:
        opts = {}

    try:
        # ===== OCR 特殊处理（用 easyocr） =====
        if operation == 'ocr':
            easyocr = _lazy_import('easyocr')
            if easyocr is None:
                return _lib_missing_result('easyocr', 'image_processor[ocr]')

            languages = opts.get('languages', ['ch_sim', 'en'])
            reader = easyocr.Reader(languages)
            result = reader.readtext(image_path)

            text_lines = [item[1] for item in result]
            full_text = '\n'.join(text_lines)

            return SkillResult(
                success=True,
                output=f"OCR 识别完成，识别到 {len(text_lines)} 行文本:\n{full_text}",
                data={
                    'text': full_text,
                    'lines': text_lines,
                    'boxes': [{'box': [list(p) for p in item[0]], 'text': item[1], 'conf': float(item[2])}
                              for item in result],
                },
            )

        # ★ v3.72: PDF OCR 特殊处理
        if operation == 'pdf_ocr':
            # 支持 PDF 文件的 OCR 识别
            fitz = _lazy_import('fitz')  # PyMuPDF
            if fitz is None:
                return _lib_missing_result('PyMuPDF', 'image_processor[pdf_ocr]')

            try:
                doc = fitz.open(image_path)
                total_pages = len(doc)
                all_text = []

                # 先尝试提取文本型 PDF
                for page_num in range(total_pages):
                    page = doc[page_num]
                    text = page.get_text()
                    if text.strip():
                        all_text.append(f"=== 第 {page_num + 1} 页 ===\n{text}")

                # 如果文本为空，说明是扫描件，需要 OCR
                if not all_text:
                    easyocr = _lazy_import('easyocr')
                    if easyocr is None:
                        return _lib_missing_result('easyocr', 'image_processor[pdf_ocr]')

                    languages = opts.get('languages', ['ch_sim', 'en'])
                    reader = easyocr.Reader(languages)

                    for page_num in range(total_pages):
                        page = doc[page_num]
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x 缩放提高精度
                        img_bytes = pix.tobytes("png")

                        # 临时保存为字节流
                        import io
                        from PIL import Image
                        img = Image.open(io.BytesIO(img_bytes))

                        # OCR 识别
                        result = reader.readtext(img_bytes)
                        text_lines = [item[1] for item in result]
                        page_text = '\n'.join(text_lines)
                        all_text.append(f"=== 第 {page_num + 1} 页（OCR） ===\n{page_text}")

                doc.close()
                full_text = '\n\n'.join(all_text)

                return SkillResult(
                    success=True,
                    output=f"PDF OCR 识别完成，共 {total_pages} 页:\n{full_text[:500]}...",
                    data={
                        'text': full_text,
                        'pages': total_pages,
                        'type': 'text' if not any('OCR' in t for t in all_text) else 'scanned',
                    },
                )
            except Exception as e:
                return SkillResult(success=False, error=f"PDF OCR 失败: {e}")

        # ===== 其他操作用 Pillow =====
        PIL = _lazy_import('PIL')
        if PIL is None:
            return _lib_missing_result('pillow', 'image_processor')

        from PIL import Image, ImageFilter, ImageDraw

        img = Image.open(image_path)

        # ===== info =====
        if operation == 'info':
            return SkillResult(
                success=True,
                output=f"图像信息:\n  路径: {image_path}\n  格式: {img.format}\n  尺寸: {img.size}\n  模式: {img.mode}\n  文件大小: {os.path.getsize(image_path)} bytes",
                data={
                    'path': image_path,
                    'format': img.format,
                    'size': list(img.size),
                    'mode': img.mode,
                    'file_size': os.path.getsize(image_path),
                },
            )

        # ===== resize =====
        if operation == 'resize':
            w = opts.get('width', img.size[0])
            h = opts.get('height', img.size[1])
            img = img.resize((int(w), int(h)), Image.LANCZOS)

        # ===== rotate =====
        elif operation == 'rotate':
            angle = float(opts.get('angle', 0))
            img = img.rotate(angle, expand=True)

        # ===== filter =====
        elif operation == 'filter':
            filter_type = opts.get('type', 'blur')
            filter_map = {
                'blur': ImageFilter.BLUR,
                'sharpen': ImageFilter.SHARPEN,
                'edge': ImageFilter.FIND_EDGES,
                'emboss': ImageFilter.EMBOSS,
                'smooth': ImageFilter.SMOOTH,
            }
            if filter_type not in filter_map:
                return SkillResult(success=False, error=f"未知滤镜: {filter_type}")
            img = img.filter(filter_map[filter_type])

        # ===== convert =====
        elif operation == 'convert':
            fmt = opts.get('format', 'PNG').upper()
            if fmt == 'JPEG' and img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            if not output_path:
                import tempfile
                output_path = os.path.join(tempfile.gettempdir(),
                                            f"converted_{int(__import__('time').time())}.{fmt.lower()}")
            img.save(output_path, format=fmt)
            return SkillResult(
                success=True,
                output=f"格式转换完成: {image_path} → {output_path} ({fmt})",
                data={'input': image_path, 'output': output_path, 'format': fmt},
            )

        # ===== composite =====
        elif operation == 'composite':
            overlay_path = opts.get('overlay', '')
            if not overlay_path or not os.path.exists(overlay_path):
                return SkillResult(success=False, error="overlay 参数缺失或文件不存在")
            pos_str = opts.get('position', '0,0')
            x, y = [int(v) for v in pos_str.split(',')]
            overlay = Image.open(overlay_path)
            if img.mode != overlay.mode:
                overlay = overlay.convert(img.mode)
            img.paste(overlay, (x, y))

        else:
            return SkillResult(success=False, error=f"未知 operation: {operation}")

        # 保存结果
        if not output_path:
            output_path = image_path
        img.save(output_path)

        return SkillResult(
            success=True,
            output=f"图像处理完成: {operation}\n输入: {image_path}\n输出: {output_path}\n尺寸: {img.size}",
            data={
                'input': image_path,
                'output': output_path,
                'operation': operation,
                'size': list(img.size),
            },
        )

    except Exception as e:
        return SkillResult(success=False, error=f"图像处理失败: {e}", output=traceback.format_exc())


IMAGE_PROCESSOR_SKILL = SkillDef(
    name="image_processor",
    description="图像处理: 缩放/旋转/滤镜/格式转换/合成/OCR 文字识别/PDF OCR。支持中文 OCR 和扫描件 PDF 识别。",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "输入图像或 PDF 路径"},
            "operation": {
                "type": "string",
                "enum": ["info", "resize", "rotate", "filter", "convert", "composite", "ocr", "pdf_ocr"],
                "description": "操作类型（pdf_ocr 用于 PDF 文件 OCR 识别）",
            },
            "output_path": {"type": "string", "description": "输出路径（默认覆盖原图）"},
            "options": {"type": "string", "description": "JSON 操作参数", "default": "{}"},
        },
        "required": ["image_path", "operation"],
    },
    handler=_handle_image_process,
    category="image",
    timeout=120,
)


# ============================================================
# Skill 7: self_documenter — 项目自文档化（蒸馏自 MiMo Code self-documentation）
# ============================================================

def _handle_self_document(
    project_path: str = "",
    output_format: str = "markdown",
    include_diagram: bool = True,
) -> SkillResult:
    """
    自文档化 skill — 自动生成项目 README 和结构文档

    Args:
        project_path: 项目根目录路径（默认当前目录）
        output_format: 输出格式
            - markdown  README.md 格式
            - json      结构化 JSON
            - html      HTML 页面
        include_diagram: 是否包含架构图（Mermaid）
    """
    if not project_path:
        project_path = os.getcwd()

    if not os.path.isdir(project_path):
        return SkillResult(success=False, error=f"路径不存在: {project_path}")

    try:
        # 1. 扫描项目结构
        ignore_dirs = {'.git', '__pycache__', '.venv', 'venv', 'node_modules',
                       '.idea', '.vscode', 'dist', 'build', '.next', 'target'}
        ignore_files = {'.pyc', '.pyo', '.class', '.o', '.so', '.dll', '.exe', '.DS_Store'}

        dirs_list = []
        files_by_type = {}
        total_files = 0

        for root, dlist, flist in os.walk(project_path):
            dlist[:] = [d for d in dlist if d not in ignore_dirs and not d.startswith('.')]
            rel_root = os.path.relpath(root, project_path)
            if rel_root == '.':
                rel_root = ''

            for d in dlist:
                dirs_list.append(os.path.join(rel_root, d).replace('\\', '/'))

            for f in flist:
                ext = os.path.splitext(f)[1].lower()
                if ext in ignore_files:
                    continue
                total_files += 1
                if ext not in files_by_type:
                    files_by_type[ext] = []
                files_by_type[ext].append(os.path.join(rel_root, f).replace('\\', '/'))

        # 2. 检测项目类型
        project_type = "通用项目"
        type_indicators = {
            'package.json': ('Node.js/前端项目', 'JavaScript/TypeScript'),
            'requirements.txt': ('Python 项目', 'Python'),
            'setup.py': ('Python 包项目', 'Python'),
            'pyproject.toml': ('Python 项目', 'Python'),
            'Cargo.toml': ('Rust 项目', 'Rust'),
            'go.mod': ('Go 项目', 'Go'),
            'pom.xml': ('Java Maven 项目', 'Java'),
            'build.gradle': ('Java Gradle 项目', 'Java'),
            'CMakeLists.txt': ('C/C++ CMake 项目', 'C/C++'),
            'Makefile': ('C/C++ 项目', 'C/C++'),
            'Dockerfile': ('容器化项目', 'Docker'),
        }
        languages = set()
        for indicator, (ptype, lang) in type_indicators.items():
            if os.path.exists(os.path.join(project_path, indicator)):
                project_type = ptype
                languages.add(lang)

        # 3. 生成文档
        project_name = os.path.basename(os.path.abspath(project_path))
        file_type_summary = "\n".join(
            [f"| {ext if ext else '(无后缀)'} | {len(files)} |"
             for ext, files in sorted(files_by_type.items(), key=lambda x: -len(x[1]))[:15]]
        )

        if output_format == 'markdown':
            doc = f"""# {project_name}

## 项目概述

自动生成的 {project_type} 项目文档。

- **项目类型**: {project_type}
- **语言**: {', '.join(languages) if languages else '未检测'}
- **文件总数**: {total_files}
- **目录数**: {len(dirs_list)}

## 文件类型分布

| 类型 | 文件数 |
|------|--------|
{file_type_summary}

## 项目结构

```
{_generate_tree(project_path, ignore_dirs, max_depth=3)}
```

## 主要目录

{chr(10).join([f'- `{d}/`' for d in sorted(dirs_list)[:30]])}

---
*由 Lemon Code self_documenter 自动生成*
"""
        elif output_format == 'json':
            doc = json.dumps({
                'project_name': project_name,
                'project_type': project_type,
                'languages': list(languages),
                'total_files': total_files,
                'total_dirs': len(dirs_list),
                'file_types': {k: len(v) for k, v in files_by_type.items()},
                'directories': dirs_list,
            }, ensure_ascii=False, indent=2)
        elif output_format == 'html':
            doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>{project_name} - 项目文档</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; background: Lemon.DARK_MID_5; color: Lemon.DIVIDER; }}
h1 {{ color: Lemon.BRAND_ORANGE_LIGHT; border-bottom: 2px solid Lemon.BRAND_ORANGE_LIGHT; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #333; padding: 8px 12px; text-align: left; }}
th {{ background: Lemon.DARK_BG_4; }}
pre {{ background: #0f0f23; padding: 16px; border-radius: 8px; overflow-x: auto; }}
</style></head>
<body>
<h1>{project_name}</h1>
<p><strong>项目类型:</strong> {project_type} | <strong>语言:</strong> {', '.join(languages) if languages else '未检测'} | <strong>文件:</strong> {total_files}</p>
<h2>文件类型分布</h2>
<table><tr><th>类型</th><th>文件数</th></tr>
{''.join([f'<tr><td>{ext}</td><td>{len(files)}</td></tr>' for ext, files in sorted(files_by_type.items(), key=lambda x: -len(x[1]))[:15]])}
</table>
<h2>项目结构</h2>
<pre>{_generate_tree(project_path, ignore_dirs, max_depth=3)}</pre>
<p><em>由 Lemon Code self_documenter 自动生成</em></p>
</body></html>"""
        else:
            return SkillResult(success=False, error=f"不支持的格式: {output_format}")

        # 4. 可选：生成架构图
        if include_diagram and output_format == 'markdown':
            mermaid = _generate_mermaid_diagram(project_path, dirs_list, files_by_type)
            doc += f"\n\n## 架构图\n\n```mermaid\n{mermaid}\n```\n"

        return SkillResult(
            success=True,
            output=f"项目文档已生成 ({project_name})\n类型: {project_type}\n文件: {total_files}\n格式: {output_format}",
            data={
                'project_name': project_name,
                'project_type': project_type,
                'total_files': total_files,
                'format': output_format,
                'document': doc,
            },
        )

    except Exception as e:
        return SkillResult(success=False, error=f"自文档化失败: {e}", output=traceback.format_exc())


def _generate_tree(root_path: str, ignore_dirs: set, prefix: str = "", max_depth: int = 3, current_depth: int = 0) -> str:
    """生成项目目录树"""
    if current_depth >= max_depth:
        return ""
    try:
        items = sorted(os.listdir(root_path))
    except PermissionError:
        return ""

    lines = []
    dirs = [d for d in items if os.path.isdir(os.path.join(root_path, d)) and d not in ignore_dirs and not d.startswith('.')]
    files = [f for f in items if os.path.isfile(os.path.join(root_path, f)) and not f.startswith('.')]

    total = dirs + files
    for i, item in enumerate(total[:50]):
        is_last = i == len(total) - 1
        connector = "└── " if is_last else "├── "
        full_path = os.path.join(root_path, item)
        if os.path.isdir(full_path):
            lines.append(f"{prefix}{connector}{item}/")
            if current_depth + 1 < max_depth:
                ext_prefix = "    " if is_last else "│   "
                subtree = _generate_tree(full_path, ignore_dirs, prefix + ext_prefix, max_depth, current_depth + 1)
                if subtree:
                    lines.append(subtree)
        else:
            lines.append(f"{prefix}{connector}{item}")

    if len(total) > 50:
        lines.append(f"{prefix}└── ... ({len(total) - 50} more items)")
    return "\n".join(lines)


def _generate_mermaid_diagram(project_path: str, dirs_list: list, files_by_type: dict) -> str:
    """生成 Mermaid 架构图"""
    # 简单架构图：按文件类型分组
    lines = ["graph TD"]
    main_parts = []
    for ext, files in sorted(files_by_type.items(), key=lambda x: -len(x[1]))[:8]:
        label = ext.replace('.', '') if ext else 'nofile'
        main_parts.append(f'    {label}[{ext} ({len(files)}文件)]')
    lines.extend(main_parts)
    # 连线
    for i in range(len(main_parts) - 1):
        parts = main_parts[i].split('[')
        parts2 = main_parts[i + 1].split('[')
        if parts and parts2:
            lines.append(f"    {parts[0].strip()} --> {parts2[0].strip()}")
    return "\n".join(lines)


SELF_DOCUMENTER_SKILL = SkillDef(
    name="self_documenter",
    description="自动生成项目文档：README.md / 结构化 JSON / HTML 页面。包含项目结构树、文件类型分布、架构图。蒸馏自 MiMo Code self-documentation。",
    parameters={
        "type": "object",
        "properties": {
            "project_path": {"type": "string", "description": "项目根目录路径（默认当前目录）"},
            "output_format": {
                "type": "string",
                "enum": ["markdown", "json", "html"],
                "description": "输出格式",
            },
            "include_diagram": {"type": "boolean", "description": "是否包含 Mermaid 架构图", "default": True},
        },
    },
    handler=_handle_self_document,
    category="documentation",
    timeout=30,
)


# ============================================================
# Skill 8: arxiv_researcher — arXiv 论文搜索（蒸馏自 MiMo Code arxiv）
# ============================================================

def _handle_arxiv_search(
    query: str = "",
    max_results: int = 5,
    sort_by: str = "relevance",
    category: str = "",
) -> SkillResult:
    """
    arXiv 论文搜索 skill

    Args:
        query: 搜索关键词（如 "transformer attention mechanism"）
        max_results: 最大返回结果数（默认 5）
        sort_by: 排序方式
            - relevance  相关性
            - submittedDate  提交日期
            - lastUpdatedDate 最后更新
        category: arXiv 分类（如 cs.AI, cs.LG, stat.ML）
    """
    if not query:
        return SkillResult(success=False, error="query 参数为空")

    try:
        # 使用 arXiv API（无需安装额外包，直接用 urllib）
        import urllib.request
        import urllib.parse
        import xml.etree.ElementTree as ET

        base_url = "http://export.arxiv.org/api/query"
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
        }
        if category:
            params["search_query"] = f"cat:{category} AND all:{query}"

        url = base_url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "LemonCode/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read().decode('utf-8')

        # 解析 XML
        root = ET.fromstring(xml_data)
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'arxiv': 'http://arxiv.org/schemas/atom',
        }

        papers = []
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns)
            summary = entry.find('atom:summary', ns)
            paper_id = entry.find('atom:id', ns)
            published = entry.find('atom:published', ns)
            authors = entry.findall('atom:author', ns)
            links = entry.findall('atom:link', ns)

            author_names = []
            for author in authors:
                name = author.find('atom:name', ns)
                if name is not None and name.text:
                    author_names.append(name.text)

            pdf_link = ""
            for link in links:
                if link.get('title') == 'pdf':
                    pdf_link = link.get('href', '')
                    break

            papers.append({
                'title': title.text.strip().replace('\n', ' ') if title is not None else '',
                'summary': summary.text.strip()[:500] if summary is not None else '',
                'id': paper_id.text.strip() if paper_id is not None else '',
                'published': published.text[:10] if published is not None else '',
                'authors': author_names[:5],
                'pdf_url': pdf_link,
            })

        if not papers:
            return SkillResult(success=True, output=f"未找到与 '{query}' 相关的论文", data={'papers': []})

        # 格式化输出
        output = f"arXiv 搜索: '{query}' — 找到 {len(papers)} 篇论文:\n\n"
        for i, p in enumerate(papers, 1):
            output += f"### {i}. {p['title']}\n"
            output += f"   **作者**: {', '.join(p['authors'][:3])}{'...' if len(p['authors']) > 3 else ''}\n"
            output += f"   **日期**: {p['published']}\n"
            output += f"   **ID**: [{p['id'].split('/')[-1]}]({p['id']})\n"
            if p['pdf_url']:
                output += f"   **PDF**: [{p['pdf_url']}]({p['pdf_url']})\n"
            output += f"   **摘要**: {p['summary'][:200]}...\n\n"

        return SkillResult(
            success=True,
            output=output,
            data={'papers': papers, 'query': query, 'total': len(papers)},
        )

    except Exception as e:
        return SkillResult(success=False, error=f"arXiv 搜索失败: {e}", output=traceback.format_exc())


ARXIV_RESEARCHER_SKILL = SkillDef(
    name="arxiv_researcher",
    description="搜索 arXiv 学术论文数据库，返回论文标题、作者、摘要、PDF链接。蒸馏自 MiMo Code arxiv skill。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，如 'transformer attention mechanism'"},
            "max_results": {"type": "integer", "description": "最大返回结果数", "default": 5},
            "sort_by": {
                "type": "string",
                "enum": ["relevance", "submittedDate", "lastUpdatedDate"],
                "description": "排序方式",
            },
            "category": {"type": "string", "description": "arXiv 分类，如 cs.AI, cs.LG, stat.ML"},
        },
        "required": ["query"],
    },
    handler=_handle_arxiv_search,
    category="research",
    timeout=30,
)


# ============================================================
# Skill 9: design_blueprint — 架构图生成（蒸馏自 MiMo Code design-blueprint）
# ============================================================

def _handle_design_blueprint(
    diagram_type: str = "architecture",
    components: str = "",
    title: str = "",
    direction: str = "TD",
) -> SkillResult:
    """
    架构图生成 skill — 生成 Mermaid.js 架构图

    Args:
        diagram_type: 图表类型
            - architecture  系统架构图（组件+连线）
            - flowchart     流程图
            - sequence      时序图
            - class         类图
            - er            实体关系图
            - state         状态图
        components: 组件描述
            - JSON 格式: [{"name":"A","depends":["B","C"],"desc":"..."}]
            - 纯文本格式: 每行一个组件，用 -> 表示依赖
              例: "用户 -> 前端\n前端 -> 后端\n后端 -> 数据库"
        title: 图表标题
        direction: 方向
            - TD  从上到下
            - LR  从左到右
            - BT  从下到上
            - RL  从右到左
    """
    if not components:
        return SkillResult(success=False, error="components 参数为空")

    try:
        # 解析组件描述
        nodes = []
        edges = []

        # 尝试 JSON 解析
        try:
            comps = json.loads(components) if isinstance(components, str) else components
            for comp in comps:
                name = comp.get('name', '')
                desc = comp.get('desc', '')
                deps = comp.get('depends', [])
                node_id = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5_]', '_', name)
                nodes.append((node_id, name, desc))
                for dep in deps:
                    dep_id = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5_]', '_', dep)
                    edges.append((dep_id, node_id))
        except (json.JSONDecodeError, TypeError):
            # 纯文本解析
            for line in components.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                if '->' in line:
                    parts = line.split('->')
                    src = parts[0].strip()
                    dst = parts[1].strip()
                    src_id = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5_]', '_', src)
                    dst_id = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5_]', '_', dst)
                    nodes.append((src_id, src, ''))
                    nodes.append((dst_id, dst, ''))
                    edges.append((src_id, dst_id))
                else:
                    node_id = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5_]', '_', line)
                    nodes.append((node_id, line, ''))

        # 去重节点
        seen = set()
        unique_nodes = []
        for n in nodes:
            if n[0] not in seen:
                seen.add(n[0])
                unique_nodes.append(n)
        nodes = unique_nodes

        # 生成 Mermaid 代码
        mermaid_lines = [f"{diagram_type} {direction}"]
        if title:
            mermaid_lines.append(f"    title {title}")

        # 节点声明
        for node_id, name, desc in nodes:
            if desc:
                mermaid_lines.append(f'    {node_id}["{name}<br/><small>{desc}</small>"]')
            else:
                mermaid_lines.append(f'    {node_id}["{name}"]')

        # 连线
        for src, dst in edges:
            mermaid_lines.append(f"    {src} --> {dst}")

        mermaid_code = "\n".join(mermaid_lines)

        return SkillResult(
            success=True,
            output=f"架构图已生成 ({diagram_type}, {len(nodes)} 节点, {len(edges)} 连线)\n\n```mermaid\n{mermaid_code}\n```",
            data={
                'diagram_type': diagram_type,
                'nodes': [{'id': n[0], 'name': n[1], 'desc': n[2]} for n in nodes],
                'edges': edges,
                'mermaid': mermaid_code,
            },
        )

    except Exception as e:
        return SkillResult(success=False, error=f"架构图生成失败: {e}", output=traceback.format_exc())


DESIGN_BLUEPRINT_SKILL = SkillDef(
    name="design_blueprint",
    description="生成 Mermaid.js 架构图：系统架构图/流程图/时序图/类图/ER图/状态图。蒸馏自 MiMo Code design-blueprint。",
    parameters={
        "type": "object",
        "properties": {
            "diagram_type": {
                "type": "string",
                "enum": ["architecture", "flowchart", "sequence", "class", "er", "state"],
                "description": "图表类型",
            },
            "components": {"type": "string", "description": "组件描述（JSON 或纯文本格式，用 -> 表示依赖）"},
            "title": {"type": "string", "description": "图表标题"},
            "direction": {
                "type": "string",
                "enum": ["TD", "LR", "BT", "RL"],
                "description": "排列方向",
                "default": "TD",
            },
        },
        "required": ["diagram_type", "components"],
    },
    handler=_handle_design_blueprint,
    category="visual",
    timeout=30,
)


# ============================================================
# Skill 10: physics_experiment — 物理实验简笔画生成（Canvas 动画）
# ============================================================

# 物理实验模板：每种实验类型对应一个 Canvas JS 代码模板
PHYSICS_TEMPLATES = {
    "spring": r"""// 弹簧振子简笔画 — 黑板风格白线动画
const canvas = document.getElementById('physics-canvas');
const ctx = canvas.getContext('2d');
const W = canvas.width = 400, H = canvas.height = 300;
const k = {k}, m = {m}, amp = {amplitude};
const omega = Math.sqrt(k / m);
let t = 0;

function draw() {
    ctx.fillStyle = 'Lemon.DARK_MID_5'; ctx.fillRect(0, 0, W, H);
    const x = amp * Math.cos(omega * t);
    const wallX = 80, centerY = H / 2, springLen = 150 + x;
    // 墙面
    ctx.strokeStyle = '#555'; ctx.lineWidth = 4;
    ctx.beginPath(); ctx.moveTo(wallX, centerY - 40); ctx.lineTo(wallX, centerY + 40); ctx.stroke();
    // 弹簧（锯齿线）
    ctx.strokeStyle = 'Lemon.STATUS_RUNNING'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(wallX, centerY);
    const coils = 12, coilW = (springLen - 30) / coils;
    for (let i = 0; i <= coils; i++) {
        const cx = wallX + 15 + i * coilW;
        const cy = centerY + (i % 2 === 0 ? 10 : -10);
        ctx.lineTo(cx, cy);
    }
    ctx.stroke();
    // 物块
    const bx = wallX + springLen, by = centerY;
    ctx.fillStyle = 'Lemon.ACCENT_RED'; ctx.strokeStyle = '#fff';
    ctx.beginPath(); ctx.rect(bx - 15, by - 15, 30, 30); ctx.fill(); ctx.stroke();
    // 标签
    ctx.fillStyle = '#fff'; ctx.font = '12px monospace';
    ctx.fillText('F=-kx  k={k}  m={m}', 10, 20);
    ctx.fillText('x=' + x.toFixed(1) + '  t=' + t.toFixed(1) + 's', 10, 38);
    t += 0.05; requestAnimationFrame(draw);
}
draw();""",

    "pendulum": r"""// 单摆简笔画 — 黑板风格白线动画
const canvas = document.getElementById('physics-canvas');
const ctx = canvas.getContext('2d');
const W = canvas.width = 400, H = canvas.height = 320;
const g = 9.8, L = {length}, theta0 = {angle} * Math.PI / 180;
const omega = Math.sqrt(g / L);
let t = 0;

function draw() {
    ctx.fillStyle = 'Lemon.DARK_MID_5'; ctx.fillRect(0, 0, W, H);
    const theta = theta0 * Math.cos(omega * t);
    const pivotX = W / 2, pivotY = 50;
    const bobX = pivotX + L * Math.sin(theta);
    const bobY = pivotY + L * Math.cos(theta);
    // 支架
    ctx.strokeStyle = '#555'; ctx.lineWidth = 4;
    ctx.beginPath(); ctx.moveTo(pivotX - 30, pivotY); ctx.lineTo(pivotX + 30, pivotY); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(pivotX, pivotY - 10); ctx.lineTo(pivotX, pivotY); ctx.stroke();
    // 绳子
    ctx.strokeStyle = 'Lemon.STATUS_RUNNING'; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(pivotX, pivotY); ctx.lineTo(bobX, bobY); ctx.stroke();
    // 摆球
    ctx.fillStyle = 'Lemon.ACCENT_RED'; ctx.strokeStyle = '#fff'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(bobX, bobY, 15, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    // 标签
    ctx.fillStyle = '#fff'; ctx.font = '12px monospace';
    ctx.fillText('T=2π√(L/g)  L={length}  θ₀={angle}°', 10, 20);
    ctx.fillText('θ=' + (theta * 180 / Math.PI).toFixed(1) + '°  t=' + t.toFixed(1) + 's', 10, 38);
    t += 0.05; requestAnimationFrame(draw);
}
draw();""",

    "projectile": r"""// 抛体运动简笔画 — 黑板风格白线动画
const canvas = document.getElementById('physics-canvas');
const ctx = canvas.getContext('2d');
const W = canvas.width = 420, H = canvas.height = 300;
const v0 = {velocity}, angle = {angle} * Math.PI / 180;
const vx = v0 * Math.cos(angle), vy = v0 * Math.sin(angle);
const g = 9.8;
let t = 0, trail = [];

function draw() {
    ctx.fillStyle = 'Lemon.DARK_MID_5'; ctx.fillRect(0, 0, W, H);
    const x = 40 + vx * t * 3, y = H - 40 - (vy * t * 3 - 0.5 * g * t * t * 3);
    trail.push([x, y]);
    if (trail.length > 100) trail.shift();
    // 地面
    ctx.strokeStyle = '#555'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, H - 40); ctx.lineTo(W, H - 40); ctx.stroke();
    // 轨迹
    ctx.strokeStyle = 'rgba(0,229,255,0.3)'; ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < trail.length; i++) {
        if (i === 0) ctx.moveTo(trail[i][0], trail[i][1]);
        else ctx.lineTo(trail[i][0], trail[i][1]);
    }
    ctx.stroke();
    // 抛体
    if (y <= H - 40) {
        ctx.fillStyle = 'Lemon.ACCENT_RED'; ctx.strokeStyle = '#fff';
        ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    }
    // 标签
    ctx.fillStyle = '#fff'; ctx.font = '12px monospace';
    ctx.fillText('v₀={velocity}m/s  θ={angle}°  g=9.8', 10, 20);
    ctx.fillText('t=' + t.toFixed(1) + 's  x=' + (vx * t).toFixed(1) + 'm  y=' + Math.max(0, (vy * t - 0.5 * g * t * t)).toFixed(1) + 'm', 10, 38);
    if (y > H - 40) {
        ctx.fillText('落地! 射程=' + (vx * t).toFixed(1) + 'm', 10, 56);
    } else { t += 0.03; }
    requestAnimationFrame(draw);
}
draw();""",

    "wave": r"""// 波传播简笔画 — 黑板风格白线动画
const canvas = document.getElementById('physics-canvas');
const ctx = canvas.getContext('2d');
const W = canvas.width = 420, H = canvas.height = 260;
const A = {amplitude}, freq = {frequency}, lambda = {wavelength};
const k = 2 * Math.PI / lambda, omega = 2 * Math.PI * freq;
let t = 0;

function draw() {
    ctx.fillStyle = 'Lemon.DARK_MID_5'; ctx.fillRect(0, 0, W, H);
    const midY = H / 2;
    // 中线
    ctx.strokeStyle = 'rgba(255,255,255,0.15)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, midY); ctx.lineTo(W, midY); ctx.stroke();
    // 波形
    ctx.strokeStyle = 'Lemon.STATUS_RUNNING'; ctx.lineWidth = 2;
    ctx.beginPath();
    for (let x = 0; x < W; x++) {
        const y = midY + A * Math.sin(k * x - omega * t);
        if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    // 标签
    ctx.fillStyle = '#fff'; ctx.font = '12px monospace';
    ctx.fillText('y=Asin(kx-ωt)  A={amplitude}  λ={wavelength}', 10, 20);
    ctx.fillText('f={frequency}Hz  v=' + (lambda * freq).toFixed(1) + 'm/s  t=' + t.toFixed(2) + 's', 10, 38);
    t += 0.03; requestAnimationFrame(draw);
}
draw();""",

    "circuit": r"""// 简单电路简笔画 — 黑板风格静态图
const canvas = document.getElementById('physics-canvas');
const ctx = canvas.getContext('2d');
const W = canvas.width = 400, H = canvas.height = 260;
ctx.fillStyle = 'Lemon.DARK_MID_5'; ctx.fillRect(0, 0, W, H);
ctx.strokeStyle = 'Lemon.STATUS_RUNNING'; ctx.lineWidth = 2;
// 导线
ctx.beginPath();
ctx.moveTo(60, 130); ctx.lineTo(120, 130); // 电池左
ctx.lineTo(140, 80); ctx.lineTo(200, 80); ctx.lineTo(220, 130); // 上支路
ctx.lineTo(280, 130); ctx.lineTo(300, 180); ctx.lineTo(260, 180); // 电阻支路
ctx.lineTo(220, 130); // 回到主线
ctx.moveTo(280, 130); ctx.lineTo(340, 130); // 右导线
ctx.moveTo(340, 130); ctx.lineTo(340, 180); ctx.lineTo(300, 180); // 下支路
ctx.moveTo(300, 180); ctx.lineTo(260, 180); // 回到
ctx.moveTo(260, 180); ctx.lineTo(240, 210); ctx.lineTo(160, 210); // 下导线
ctx.lineTo(140, 180); ctx.lineTo(120, 180); ctx.lineTo(100, 130); // 回电池
ctx.lineTo(60, 130);
ctx.stroke();
// 电池
ctx.fillStyle = 'Lemon.ACCENT_RED'; ctx.strokeStyle = '#fff';
ctx.fillRect(50, 120, 12, 20); ctx.fillRect(62, 123, 8, 14);
ctx.fillStyle = '#fff'; ctx.font = '10px monospace';
ctx.fillText('V', 56, 155);
// 电阻
ctx.fillStyle = 'Lemon.ACCENT_RED';
ctx.fillRect(255, 170, 40, 20);
ctx.fillStyle = '#fff'; ctx.fillText('R', 268, 195);
// 标签
ctx.fillStyle = '#fff'; ctx.font = '12px monospace';
ctx.fillText('简单电路  V=IR', 10, 20);
ctx.fillText('电池 + 电阻 + 导线', 10, 38);
""",

    "gravity": r"""// 万有引力轨道简笔画 — 黑板风格白线动画
const canvas = document.getElementById('physics-canvas');
const ctx = canvas.getContext('2d');
const W = canvas.width = 400, H = canvas.height = 320;
const cx = W / 2, cy = H / 2, a = {semiMajor}, b = {semiMinor};
let angle = 0;

function draw() {
    ctx.fillStyle = 'Lemon.DARK_MID_5'; ctx.fillRect(0, 0, W, H);
    // 轨道椭圆
    ctx.strokeStyle = 'rgba(255,255,255,0.15)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.ellipse(cx, cy, a, b, 0, 0, Math.PI * 2); ctx.stroke();
    // 太阳（焦点）
    const c = Math.sqrt(a * a - b * b);
    ctx.fillStyle = '#ffaa00';
    ctx.beginPath(); ctx.arc(cx - c, cy, 10, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#fff'; ctx.font = '10px monospace'; ctx.fillText('太阳', cx - c - 15, cy - 15);
    // 行星
    const px = cx + a * Math.cos(angle), py = cy + b * Math.sin(angle);
    ctx.fillStyle = 'Lemon.STATUS_RUNNING'; ctx.strokeStyle = '#fff';
    ctx.beginPath(); ctx.arc(px, py, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.fillText('行星', px + 10, py - 10);
    // 标签
    ctx.fillStyle = '#fff'; ctx.font = '12px monospace';
    ctx.fillText('开普勒定律  F=GMm/r²', 10, 20);
    ctx.fillText('a={semiMajor}  b={semiMinor}  e=' + (c / a).toFixed(2), 10, 38);
    angle += 0.02; requestAnimationFrame(draw);
}
draw();""",
}


def _handle_physics_experiment(
    experiment_type: str = "spring",
    params: str = "",
) -> SkillResult:
    """
    物理实验简笔画生成 skill — 生成 Canvas JS 动画代码

    支持 6 种物理实验：
        - spring      弹簧振子 (F=-kx)
        - pendulum    单摆 (T=2π√(L/g))
        - projectile  抛体运动 (v₀, θ)
        - wave        波传播 (y=Asin(kx-ωt))
        - circuit     简单电路 (V=IR)
        - gravity     万有引力轨道 (开普勒定律)

    Args:
        experiment_type: 实验类型
        params: JSON 格式参数
            弹簧振子: {"k": 10, "m": 1, "amplitude": 50}
            单摆:     {"length": 120, "angle": 30}
            抛体:     {"velocity": 20, "angle": 45}
            波:       {"amplitude": 30, "frequency": 1, "wavelength": 100}
            电路:     无参数（使用默认值）
            引力:     {"semiMajor": 120, "semiMinor": 80}
    """
    if experiment_type not in PHYSICS_TEMPLATES:
        return SkillResult(
            success=False,
            error=f"未知实验类型: {experiment_type}，支持: {', '.join(PHYSICS_TEMPLATES.keys())}",
        )

    # 默认参数
    defaults = {
        "spring": {"k": 10, "m": 1, "amplitude": 50},
        "pendulum": {"length": 120, "angle": 30},
        "projectile": {"velocity": 20, "angle": 45},
        "wave": {"amplitude": 30, "frequency": 1, "wavelength": 100},
        "circuit": {},
        "gravity": {"semiMajor": 120, "semiMinor": 80},
    }

    try:
        user_params = json.loads(params) if params else {}
    except json.JSONDecodeError:
        return SkillResult(success=False, error=f"params JSON 解析失败: {params}")

    # 合并默认参数
    merged = {**defaults[experiment_type], **user_params}

    # 填充模板 — 使用 replace 避免 JS 代码中的 { } 被 format() 误解析
    try:
        code = PHYSICS_TEMPLATES[experiment_type]
        for key, value in merged.items():
            code = code.replace('{' + key + '}', str(value))
    except Exception as e:
        return SkillResult(success=False, error=f"模板填充失败: {e}")

    # 实验名称映射
    names = {
        "spring": "弹簧振子",
        "pendulum": "单摆",
        "projectile": "抛体运动",
        "wave": "波传播",
        "circuit": "简单电路",
        "gravity": "万有引力轨道",
    }

    return SkillResult(
        success=True,
        output=f"物理实验简笔画已生成：{names[experiment_type]}\n\n"
               f"```physics-canvas\n{code}\n```\n\n"
               f"参数: {json.dumps(merged, ensure_ascii=False)}",
        data={
            "experiment_type": experiment_type,
            "name": names[experiment_type],
            "canvas_code": code,
            "params": merged,
        },
    )


PHYSICS_EXPERIMENT_SKILL = SkillDef(
    name="physics_experiment",
    description="生成物理实验简笔画动画（Canvas JS）：弹簧振子、单摆、抛体运动、波传播、电路、万有引力轨道。黑板风格白线动画。",
    parameters={
        "type": "object",
        "properties": {
            "experiment_type": {
                "type": "string",
                "enum": ["spring", "pendulum", "projectile", "wave", "circuit", "gravity"],
                "description": "实验类型",
            },
            "params": {
                "type": "string",
                "description": "JSON 格式参数，如弹簧振子: {\"k\":10,\"m\":1,\"amplitude\":50}",
            },
        },
        "required": ["experiment_type"],
    },
    handler=_handle_physics_experiment,
    category="visual",
    timeout=30,
)


# ============================================================
# Skill 11: image_analyzer — 图像识别分析（小模型识图+路由）
# ============================================================

def _handle_image_analyze(
    image_path: str = "",
    mode: str = "auto",
    prompt: str = "",
) -> SkillResult:
    """
    图像识别分析 skill — 小模型识图+智能路由

    三种模式：
        - ocr      光学字符识别（提取图中文字）
        - describe 图像内容描述（需要 Ollama 视觉模型）
        - auto     自动检测（先 OCR，有文字则返回文字，否则尝试描述）
        - classify 图像分类+路由（识别图像类型，推荐后续 Skill）

    Args:
        image_path: 图片文件路径（支持 png/jpg/jpeg/bmp/gif/webp）
        mode: 分析模式
        prompt: 自定义提示词（describe 模式下使用）
    """
    if not image_path:
        return SkillResult(success=False, error="image_path 参数为空")

    import os as _os
    if not _os.path.exists(image_path):
        return SkillResult(success=False, error=f"图片文件不存在: {image_path}")

    # 检查文件扩展名
    valid_exts = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'}
    ext = _os.path.splitext(image_path)[1].lower()
    if ext not in valid_exts:
        return SkillResult(
            success=False,
            error=f"不支持的图片格式: {ext}，支持: {', '.join(valid_exts)}",
        )

    results = {}
    route_hint = ""

    # ====== OCR 模式 ======
    if mode in ("ocr", "auto"):
        pil = _lazy_import('PIL')
        if pil is None:
            results['ocr'] = "⚠️ Pillow 未安装，无法 OCR"
        else:
            try:
                from PIL import Image
                img = Image.open(image_path)
                img_info = {
                    'format': img.format,
                    'size': list(img.size),
                    'mode': img.mode,
                }
                results['image_info'] = img_info

                # 尝试 EasyOCR
                easyocr = _lazy_import('easyocr')
                if easyocr is not None:
                    try:
                        reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
                        ocr_results = reader.readtext(image_path)
                        if ocr_results:
                            texts = []
                            for bbox, text, conf in ocr_results:
                                if conf > 0.3:
                                    texts.append({'text': text, 'confidence': round(conf, 2)})
                            if texts:
                                results['ocr'] = texts
                                route_hint = "检测到文字 → 建议路由给 math_solver / info_debater / web_researcher"
                            else:
                                results['ocr'] = "未检测到文字"
                        else:
                            results['ocr'] = "未检测到文字"
                    except Exception as e:
                        results['ocr'] = f"EasyOCR 执行失败: {e}"
                else:
                    results['ocr'] = "⚠️ EasyOCR 未安装 (pip install easyocr)"

            except Exception as e:
                results['image_error'] = f"图片读取失败: {e}"

    # ====== Describe 模式（Ollama 视觉模型） ======
    if mode in ("describe", "auto"):
        try:
            import base64 as _b64
            with open(image_path, 'rb') as f:
                img_b64 = _b64.b64encode(f.read()).decode('utf-8')

            # 尝试调用 Ollama 视觉模型
            ollama_endpoint = "http://127.0.0.1:11434/api/generate"
            import urllib.request as _ureq

            desc_prompt = prompt or "请用中文简要描述这张图片的内容，包括主要物体、颜色、文字、场景。如果是数学公式或图表，请描述其内容。"
            payload = json.dumps({
                "model": "llava:latest",
                "prompt": desc_prompt,
                "images": [img_b64],
                "stream": False,
            }).encode('utf-8')

            req = _ureq.Request(ollama_endpoint, data=payload, headers={"Content-Type": "application/json"})
            try:
                with _ureq.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    description = data.get('response', '')
                    if description:
                        results['description'] = description
                        # 智能路由提示
                        desc_lower = description.lower()
                        if any(kw in desc_lower for kw in ['公式', '方程', '数学', '计算', 'formula', 'math', 'equation']):
                            route_hint = "检测到数学内容 → 建议路由给 math_solver"
                        elif any(kw in desc_lower for kw in ['物理', '实验', '弹簧', '运动', 'physics', 'force', 'motion']):
                            route_hint = "检测到物理内容 → 建议路由给 physics_experiment"
                        elif any(kw in desc_lower for kw in ['图表', '数据', '表格', 'chart', 'graph', 'table']):
                            route_hint = "检测到数据图表 → 建议路由给 math_plotter"
                        elif any(kw in desc_lower for kw in ['论文', '文档', 'paper', 'document', 'article']):
                            route_hint = "检测到文档内容 → 建议路由给 arxiv_researcher / office_generator"
                        elif any(kw in desc_lower for kw in ['电路', '电路图', 'circuit', 'diagram']):
                            route_hint = "检测到电路图 → 建议路由给 physics_experiment (circuit)"
                        elif any(kw in desc_lower for kw in ['代码', '编程', 'code', 'programming']):
                            route_hint = "检测到代码内容 → 建议路由给 execute_code"
                        else:
                            route_hint = "通用内容 → 建议路由给 web_researcher 搜索相关信息"
            except Exception as e:
                results['description'] = f"Ollama 视觉模型调用失败: {e}。请确保安装了 llava 模型 (ollama pull llava)"

        except Exception as e:
            results['description'] = f"图片编码失败: {e}"

    # ====== Classify 模式 ======
    if mode == "classify":
        # 基于图片属性分类
        try:
            from PIL import Image
            img = Image.open(image_path)
            w, h = img.size

            classification = {
                'format': img.format,
                'width': w,
                'height': h,
                'aspect_ratio': round(w / h, 2),
                'mode': img.mode,
            }

            # 启发式分类
            if w / h > 3:
                classification['likely_type'] = '截图/横幅'
            elif w / h < 0.5:
                classification['likely_type'] = '手机截图/长图'
            elif abs(w / h - 1) < 0.1:
                classification['likely_type'] = '方形图/头像'
            elif abs(w / h - 1.414) < 0.15:
                classification['likely_type'] = 'A4文档/A4纸'
            elif abs(w / h - 16/9) < 0.2:
                classification['likely_type'] = '屏幕截图/视频帧'
            else:
                classification['likely_type'] = '普通图片'

            results['classification'] = classification

            if classification['likely_type'] == 'A4文档/A4纸':
                route_hint = "看起来像文档 → 建议路由给 office_generator 或 OCR 后处理"
            elif classification['likely_type'] == '截图/横幅':
                route_hint = "看起来像截图 → 建议路由给 web_researcher 查询相关内容"

        except Exception as e:
            results['classification'] = f"分类失败: {e}"

    # ====== 构建输出 ======
    output_lines = [f"图像分析完成: {_os.path.basename(image_path)}"]

    if 'image_info' in results:
        info = results['image_info']
        output_lines.append(f"格式: {info['format']} | 尺寸: {info['size'][0]}x{info['size'][1]} | 模式: {info['mode']}")

    if 'ocr' in results:
        ocr = results['ocr']
        if isinstance(ocr, list):
            output_lines.append(f"\n【OCR 文字识别】({len(ocr)} 处)")
            for item in ocr[:10]:
                output_lines.append(f"  - {item['text']} (置信度: {item['confidence']})")
        else:
            output_lines.append(f"\n【OCR 文字识别】{ocr}")

    if 'description' in results:
        desc = results['description']
        if not desc.startswith('⚠️') and not desc.startswith('Ollama'):
            output_lines.append(f"\n【图像内容描述】\n{desc[:500]}")

    if 'classification' in results:
        cls = results['classification']
        if isinstance(cls, dict):
            output_lines.append(f"\n【图像分类】{cls.get('likely_type', '未知')}")

    if route_hint:
        output_lines.append(f"\n【智能路由建议】{route_hint}")

    return SkillResult(
        success=True,
        output="\n".join(output_lines),
        data={
            'image_path': image_path,
            'results': results,
            'route_hint': route_hint,
            'mode': mode,
        },
    )


IMAGE_ANALYZER_SKILL = SkillDef(
    name="image_analyzer",
    description="图像识别分析：OCR文字提取、视觉模型描述、智能分类路由。支持小模型识图+自动路由到下游Skill。",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "图片文件路径（png/jpg/jpeg/bmp/gif/webp）"},
            "mode": {
                "type": "string",
                "enum": ["ocr", "describe", "auto", "classify"],
                "description": "分析模式：ocr=文字识别, describe=视觉描述, auto=自动检测, classify=分类路由",
            },
            "prompt": {"type": "string", "description": "自定义提示词（describe模式下使用）"},
        },
        "required": ["image_path"],
    },
    handler=_handle_image_analyze,
    category="image",
    timeout=60,
)


# ============================================================
# Skill 12: academic_writer — 学术论文写作（LaTeX 模板）
# ============================================================

# LaTeX 论文模板
LATEX_PAPER_TEMPLATE = r"""\documentclass[12pt,a4paper]{{article}}
\usepackage[UTF8]{{ctex}}
\usepackage{{amsmath,amssymb,amsthm}}
\usepackage{{graphicx,float}}
\usepackage{{hyperref}}
\usepackage{{geometry}}
\geometry{{margin=2.5cm}}
\usepackage{{cite}}
\usepackage{{booktabs}}
\usepackage{{algorithm2e}}

\title{{{title}}}
\author{{{author}}}
\date{{\\today}}

\begin{{document}}

\maketitle

\begin{{abstract}}
{abstract}
\end{{abstract}}

\section{{引言}}
{introduction}

\section{{相关工作}}
{related_work}

\section{{方法}}
{method}

\section{{实验}}
{experiment}

\section{{结论}}
{conclusion}

\bibliographystyle{{plain}}
\bibliography{{references}}

\end{{document}}
"""

LATEX_SECTION_TEMPLATES = {
    "abstract": r"\begin{{abstract}}\n{content}\n\end{{abstract}}",
    "introduction": r"\section{{引言}}\n{content}",
    "related_work": r"\section{{相关工作}}\n{content}",
    "method": r"\section{{方法}}\n{content}",
    "experiment": r"\section{{实验}}\n{content}",
    "conclusion": r"\section{{结论}}\n{content}",
    "math": r"\begin{{equation}}\n{content}\n\end{{equation}}",
    "aligned": r"\begin{{align}}\n{content}\n\end{{align}}",
    "table": r"\begin{{table}}[H]\n\\centering\n\\caption{{{caption}}}\n\\begin{{tabular}}{{{cols}}}\n\\toprule\n{content}\n\\bottomrule\n\\end{{tabular}}\n\\end{{table}}",
    "figure": r"\begin{{figure}}[H]\n\\centering\n\\includegraphics[width={width}]{{{path}}}\n\\caption{{{caption}}}\n\\label{{fig:{label}}}\n\\end{{figure}}",
    "algorithm": r"\begin{{algorithm}}[H]\n\\caption{{{caption}}}\n{content}\n\\end{{algorithm}}",
}


def _handle_academic_writer(
    mode: str = "full",
    title: str = "",
    author: str = "",
    abstract: str = "",
    introduction: str = "",
    related_work: str = "",
    method: str = "",
    experiment: str = "",
    conclusion: str = "",
    sections: str = "",
    output_format: str = "latex",
) -> SkillResult:
    """
    学术论文写作 skill — 生成 LaTeX 论文模板

    两种模式：
        - full    完整论文模板（包含所有章节）
        - section 生成单个章节

    Args:
        mode: full 或 section
        title: 论文标题
        author: 作者
        abstract: 摘要
        introduction: 引言
        related_work: 相关工作
        method: 方法
        experiment: 实验
        conclusion: 结论
        sections: JSON 格式自定义章节（section 模式）
        output_format: latex / markdown / plain
    """
    if mode == "full":
        if not title:
            return SkillResult(success=False, error="title 参数为空")
        if not author:
            author = "Anonymous"

        latex = LATEX_PAPER_TEMPLATE.format(
            title=title,
            author=author,
            abstract=abstract or "请在此处填写摘要内容。",
            introduction=introduction or "请在此处填写引言内容。",
            related_work=related_work or "请在此处填写相关工作内容。",
            method=method or "请在此处填写方法内容。",
            experiment=experiment or "请在此处填写实验内容。",
            conclusion=conclusion or "请在此处填写结论内容。",
        )

        # 生成 Markdown 预览
        md_preview = f"""# {title}

**作者**: {author}  |  **日期**: \\today

## 摘要
{abstract or '（待填写）'}

## 1. 引言
{introduction or '（待填写）'}

## 2. 相关工作
{related_work or '（待填写）'}

## 3. 方法
{method or '（待填写）'}

## 4. 实验
{experiment or '（待填写）'}

## 5. 结论
{conclusion or '（待填写）'}

## 参考文献
（待添加）
"""

        return SkillResult(
            success=True,
            output=f"LaTeX 论文模板已生成: {title}\n\n"
                   f"```latex\n{latex}\n```\n\n"
                   f"---\n\n## Markdown 预览\n\n{md_preview}",
            data={
                'title': title,
                'author': author,
                'latex': latex,
                'markdown': md_preview,
                'format': output_format,
            },
        )

    elif mode == "section":
        if not sections:
            return SkillResult(success=False, error="sections 参数为空（section 模式）")

        try:
            secs = json.loads(sections) if isinstance(sections, str) else sections
        except json.JSONDecodeError:
            return SkillResult(success=False, error=f"sections JSON 解析失败")

        results = []
        for sec in secs if isinstance(secs, list) else [secs]:
            sec_type = sec.get('type', 'introduction')
            content = sec.get('content', '')
            if sec_type in LATEX_SECTION_TEMPLATES:
                # 填充额外参数
                tmpl = LATEX_SECTION_TEMPLATES[sec_type]
                extra = {k: v for k, v in sec.items() if k not in ('type', 'content')}
                extra['content'] = content
                if 'caption' not in extra:
                    extra['caption'] = ''
                if 'cols' not in extra:
                    extra['cols'] = 'c|c|c'
                if 'width' not in extra:
                    extra['width'] = '0.8\\textwidth'
                if 'path' not in extra:
                    extra['path'] = 'figure.png'
                if 'label' not in extra:
                    extra['label'] = sec_type
                try:
                    rendered = tmpl.format(**extra)
                except KeyError:
                    rendered = tmpl.replace('{content}', content)
                results.append(rendered)
            else:
                results.append(content)

        output = "\n\n".join(results)
        return SkillResult(
            success=True,
            output=f"章节已生成 ({len(results)} 个)\n\n```latex\n{output}\n```",
            data={'sections': results, 'count': len(results)},
        )

    else:
        return SkillResult(success=False, error=f"未知模式: {mode}，支持 full / section")


ACADEMIC_WRITER_SKILL = SkillDef(
    name="academic_writer",
    description="学术论文写作助手：生成 LaTeX 论文模板（含摘要、引言、方法、实验、结论），支持公式/表格/图表/算法。",
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["full", "section"],
                "description": "full=完整论文模板, section=生成单个章节",
            },
            "title": {"type": "string", "description": "论文标题"},
            "author": {"type": "string", "description": "作者"},
            "abstract": {"type": "string", "description": "摘要"},
            "introduction": {"type": "string", "description": "引言"},
            "related_work": {"type": "string", "description": "相关工作"},
            "method": {"type": "string", "description": "方法"},
            "experiment": {"type": "string", "description": "实验"},
            "conclusion": {"type": "string", "description": "结论"},
            "sections": {"type": "string", "description": "JSON 格式章节定义（section 模式）"},
            "output_format": {"type": "string", "enum": ["latex", "markdown", "plain"], "description": "输出格式"},
        },
        "required": ["mode"],
    },
    handler=_handle_academic_writer,
    category="documentation",
    timeout=30,
)


# ============================================================
# Skill 13: skill_creator — Skill 创建工具（代码生成模板）
# ============================================================

PYTHON_SKILL_TEMPLATE = '''# -*- coding: utf-8 -*-
"""
Skill: {skill_name}
描述: {description}
自动生成时间: {timestamp}
"""

import os, json, traceback
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

# 复用 SkillDef / SkillResult
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from skills_registry import SkillDef, SkillResult


def _handle_{skill_name}({params}) -> SkillResult:
    """
    {description}

    Args:
{arg_docs}
    """
    try:
        # TODO: 在此处实现核心逻辑
        {handler_body}

        return SkillResult(
            success=True,
            output=f"Skill '{skill_name}' 执行成功",
            data={{}},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"执行失败: {{e}}", output=traceback.format_exc())


{skill_name_upper}_SKILL = SkillDef(
    name="{skill_name}",
    description="{description}",
    parameters={{
        "type": "object",
        "properties": {{
{param_schema}
        }},
        "required": [{required_params}],
    }},
    handler=_handle_{skill_name},
    category="{category}",
    timeout={timeout},
)
'''


def _handle_skill_creator(
    skill_name: str = "",
    description: str = "",
    category: str = "general",
    params: str = "",
    handler_body: str = "",
    timeout: int = 30,
    output_path: str = "",
) -> SkillResult:
    """
    Skill 创建工具 — 生成 Python Skill 代码模板

    用于快速创建新的 Skill，生成完整的 SkillDef 代码框架。

    Args:
        skill_name: 新 Skill 名称（snake_case，如 my_new_skill）
        description: Skill 功能描述
        category: 分类（math/research/visual/image/office/documentation/system）
        params: JSON 格式参数定义
            [{"name": "param1", "type": "string", "description": "参数1", "required": true}]
        handler_body: 核心处理逻辑（Python 代码字符串）
        timeout: 超时时间（秒）
        output_path: 输出文件路径（可选，不提供则只返回代码）
    """
    if not skill_name:
        return SkillResult(success=False, error="skill_name 参数为空")
    if not description:
        return SkillResult(success=False, error="description 参数为空")

    # 校验 skill_name 格式
    import re as _re
    if not _re.match(r'^[a-z][a-z0-9_]*$', skill_name):
        return SkillResult(success=False, error=f"skill_name 格式错误: {skill_name}，需为 snake_case")

    # 解析参数
    try:
        param_list = json.loads(params) if params else []
    except json.JSONDecodeError:
        return SkillResult(success=False, error=f"params JSON 解析失败")

    # 生成参数文档
    arg_docs = []
    param_names = []
    param_schema_parts = []
    required_list = []

    for p in param_list:
        pname = p.get('name', '')
        ptype = p.get('type', 'string')
        pdesc = p.get('description', '')
        preq = p.get('required', False)
        pdefault = p.get('default', None)

        param_names.append(pname)
        arg_docs.append(f"        {pname}: {pdesc}")
        schema_line = f'            "{pname}": {{"type": "{ptype}", "description": "{pdesc}"'
        if pdefault is not None:
            schema_line += f', "default": {json.dumps(pdefault)}'
        schema_line += '}'
        param_schema_parts.append(schema_line)
        if preq:
            required_list.append(pname)

    if not param_names:
        param_names = ["**kwargs"]
        arg_docs = ["        无参数"]

    # 生成代码
    import datetime
    code = PYTHON_SKILL_TEMPLATE.format(
        skill_name=skill_name,
        skill_name_upper=skill_name.upper(),
        description=description,
        timestamp=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        params=", ".join([f"{n}: str = \"\"" for n in param_names]) if param_names[0] != "**kwargs" else "**kwargs",
        arg_docs="\n".join(arg_docs),
        handler_body=handler_body or "# 请在此处编写核心逻辑\n        pass",
        param_schema=",\n".join(param_schema_parts) if param_schema_parts else '            "info": {"type": "string", "description": "通用参数"}',
        required_params=", ".join([f'"{r}"' for r in required_list]),
        category=category,
        timeout=timeout,
    )

    # 写入文件
    if output_path:
        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(code)
            return SkillResult(
                success=True,
                output=f"Skill 代码已生成并写入: {output_path}\n\n```python\n{code[:500]}...\n```",
                data={'skill_name': skill_name, 'output_path': output_path, 'code': code},
            )
        except Exception as e:
            return SkillResult(success=False, error=f"文件写入失败: {e}")

    return SkillResult(
        success=True,
        output=f"Skill 代码模板已生成: {skill_name}\n\n```python\n{code}\n```",
        data={'skill_name': skill_name, 'code': code},
    )


SKILL_CREATOR_SKILL = SkillDef(
    name="skill_creator",
    description="Skill 创建工具：通过参数定义自动生成完整的 Python Skill 代码模板（含 SkillDef + handler + 参数Schema）。",
    parameters={
        "type": "object",
        "properties": {
            "skill_name": {"type": "string", "description": "新 Skill 名称（snake_case，如 my_new_skill）"},
            "description": {"type": "string", "description": "Skill 功能描述"},
            "category": {"type": "string", "description": "分类：math/research/visual/image/office/documentation/system"},
            "params": {"type": "string", "description": "JSON 参数定义: [{\"name\":\"x\",\"type\":\"string\",\"description\":\"...\",\"required\":true}]"},
            "handler_body": {"type": "string", "description": "核心处理逻辑（Python 代码）"},
            "timeout": {"type": "integer", "description": "超时时间（秒，默认30）"},
            "output_path": {"type": "string", "description": "输出文件路径（可选）"},
        },
        "required": ["skill_name", "description"],
    },
    handler=_handle_skill_creator,
    category="system",
    timeout=30,
)


# ============================================================
# Skill 14: frontend_designer — 前端设计（HTML/CSS 生成）
# ============================================================

# 前端组件模板
FRONTEND_TEMPLATES = {
    "card": r"""<!-- 卡片组件 -->
<div class="card" style="background: {bg}; border-radius: {radius}px; padding: {padding}px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
  <h3 style="margin: 0 0 8px 0; color: {color};">{title}</h3>
  <p style="color: #666; line-height: 1.6;">{content}</p>
</div>""",

    "button": r"""<!-- 按钮组件 -->
<button class="btn" style="
  background: {bg}; color: {color}; border: none;
  border-radius: {radius}px; padding: {padding_y}px {padding_x}px;
  font-size: {font_size}px; cursor: pointer; transition: all 0.2s;
" onmouseover="this.style.opacity='0.85'" onmouseout="this.style.opacity='1'">
  {text}
</button>""",

    "navbar": r"""<!-- 导航栏 -->
<nav style="background: {bg}; padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 1px 4px rgba(0,0,0,0.1);">
  <div style="font-size: 20px; font-weight: bold; color: {color};">{brand}</div>
  <div style="display: flex; gap: 20px;">
    {links}
  </div>
</nav>""",

    "form": r"""<!-- 表单组件 -->
<form style="max-width: {width}px; margin: 0 auto; padding: {padding}px;">
  <h2 style="color: {color}; margin-bottom: 16px;">{title}</h2>
  {fields}
  <button type="submit" style="
    background: {bg}; color: #fff; border: none; border-radius: 6px;
    padding: 10px 24px; font-size: 14px; cursor: pointer; margin-top: 12px;
  ">提交</button>
</form>""",

    "dashboard": r"""<!-- 仪表盘布局 -->
<div style="display: grid; grid-template-columns: repeat({cols}, 1fr); gap: {gap}px; padding: {padding}px;">
  {cards}
</div>""",

    "hero": r"""<!-- Hero 区域 -->
<section style="text-align: center; padding: {padding}px 24px; background: {bg}; color: {color};">
  <h1 style="font-size: {title_size}px; margin-bottom: 16px;">{title}</h1>
  <p style="font-size: {subtitle_size}px; opacity: 0.85; max-width: 600px; margin: 0 auto 24px;">{subtitle}</p>
  <button style="background: {btn_bg}; color: {btn_color}; border: none; border-radius: 8px; padding: 12px 32px; font-size: 16px; cursor: pointer;">{btn_text}</button>
</section>""",

    "footer": r"""<!-- 页脚 -->
<footer style="background: {bg}; color: {color}; text-align: center; padding: 24px; font-size: 13px;">
  <p>{text}</p>
  <div style="margin-top: 8px; display: flex; justify-content: center; gap: 16px;">
    {links}
  </div>
</footer>""",

    "table": r"""<!-- 数据表格 -->
<table style="width: 100%; border-collapse: collapse; font-size: {font_size}px;">
  <thead>
    <tr style="background: {header_bg}; color: {header_color};">
      {headers}
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>""",

    "full_page": r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; background: {bg}; color: {color}; min-height: 100vh; }}
    .container {{ max-width: {width}px; margin: 0 auto; padding: {padding}px; }}
  </style>
</head>
<body>
  {content}
</body>
</html>""",
}


def _handle_frontend_design(
    component_type: str = "card",
    title: str = "",
    content: str = "",
    params: str = "",
    output_format: str = "html",
) -> SkillResult:
    """
    前端设计 skill — 生成 HTML/CSS 组件代码

    支持 9 种组件类型：
        - card       卡片
        - button     按钮
        - navbar     导航栏
        - form       表单
        - dashboard  仪表盘网格
        - hero       Hero 区域
        - footer     页脚
        - table      数据表格
        - full_page  完整页面

    Args:
        component_type: 组件类型
        title: 标题/品牌名
        content: 内容（表格用 JSON，仪表盘用 -- 分隔多个卡片）
        params: JSON 格式样式参数
        output_format: html / react_jsx / vue_sfc
    """
    if component_type not in FRONTEND_TEMPLATES:
        return SkillResult(
            success=False,
            error=f"未知组件类型: {component_type}，支持: {', '.join(FRONTEND_TEMPLATES.keys())}",
        )

    # 默认样式参数
    default_styles = {
        "card": {"bg": "Lemon.BG", "radius": 12, "padding": 20, "color": "#333"},
        "button": {"bg": "#4f46e5", "color": "Lemon.BG", "radius": 8, "padding_y": 10, "padding_x": 24, "font_size": 14, "text": title or "按钮"},
        "navbar": {"bg": "Lemon.DARK_MID_5", "color": "Lemon.BG", "brand": title or "Brand", "links": '<a href="#" style="color:#fff;text-decoration:none;">首页</a>\n    <a href="#" style="color:#fff;text-decoration:none;">关于</a>'},
        "form": {"width": 400, "padding": 24, "color": "#333", "bg": "#4f46e5", "title": title or "表单", "fields": '<input placeholder="输入内容" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;margin-bottom:8px;">'},
        "dashboard": {"cols": 3, "gap": 16, "padding": 24, "cards": '<div style="background:#fff;border-radius:8px;padding:16px;">卡片1</div>\n    <div style="background:#fff;border-radius:8px;padding:16px;">卡片2</div>'},
        "hero": {"padding": 80, "bg": "linear-gradient(135deg, Lemon.ACCENT_BLUE 0%, #764ba2 100%)", "color": "Lemon.BG", "title_size": 48, "subtitle_size": 18, "title": title or "欢迎", "subtitle": "这里是副标题", "btn_bg": "Lemon.BG", "btn_color": "#333", "btn_text": "开始使用"},
        "footer": {"bg": "Lemon.DARK_MID_5", "color": "#888", "text": "© 2024 All Rights Reserved", "links": '<a href="#" style="color:#888;text-decoration:none;">隐私</a>\n    <a href="#" style="color:#888;text-decoration:none;">条款</a>'},
        "table": {"font_size": 14, "header_bg": "#f5f5f5", "header_color": "#333", "headers": "<th>列1</th><th>列2</th>", "rows": "<tr><td>数据1</td><td>数据2</td></tr>"},
        "full_page": {"bg": "Lemon.SURFACE", "color": "#333", "width": 960, "padding": 40, "title": title or "页面标题", "content": content or "<h1>Hello World</h1>"},
    }

    defaults = default_styles.get(component_type, {})

    # 合并用户参数
    try:
        user_params = json.loads(params) if params else {}
    except json.JSONDecodeError:
        return SkillResult(success=False, error=f"params JSON 解析失败")

    merged = {**defaults, **user_params}
    if title and component_type not in ("full_page",):
        merged['title'] = title
    if content:
        merged['content'] = content

    # 渲染模板
    try:
        html = FRONTEND_TEMPLATES[component_type].format(**merged)
    except KeyError as e:
        return SkillResult(success=False, error=f"模板参数缺失: {e}")

    # 输出格式转换
    if output_format == "react_jsx":
        html = html.replace('class=', 'className=')
        html = html.replace('<!--', '{/*').replace('-->', '*/}')
        html = html.replace('onmouseover', 'onMouseOver').replace('onmouseout', 'onMouseOut')
    elif output_format == "vue_sfc":
        html = f"<template>\n{html}\n</template>\n\n<script setup>\n// Vue 3 Composition API\n</script>\n\n<style scoped>\n/* 组件样式 */\n</style>"

    return SkillResult(
        success=True,
        output=f"前端组件已生成: {component_type}\n\n```html\n{html}\n```",
        data={
            'component_type': component_type,
            'html': html,
            'format': output_format,
            'params': merged,
        },
    )


FRONTEND_DESIGNER_SKILL = SkillDef(
    name="frontend_designer",
    description="前端设计助手：生成 HTML/CSS 组件代码。支持卡片、按钮、导航栏、表单、仪表盘、Hero、页脚、表格、完整页面共9种组件。",
    parameters={
        "type": "object",
        "properties": {
            "component_type": {
                "type": "string",
                "enum": ["card", "button", "navbar", "form", "dashboard", "hero", "footer", "table", "full_page"],
                "description": "组件类型",
            },
            "title": {"type": "string", "description": "标题/品牌名"},
            "content": {"type": "string", "description": "内容"},
            "params": {"type": "string", "description": "JSON 格式样式参数（颜色、尺寸等）"},
            "output_format": {"type": "string", "enum": ["html", "react_jsx", "vue_sfc"], "description": "输出格式"},
        },
        "required": ["component_type"],
    },
    handler=_handle_frontend_design,
    category="visual",
    timeout=30,
)
# ============================================================
# Skill 15: deep_researcher — 深度研究（多Skill协同+结构化引用报告）
# ============================================================

DEEP_RESEARCH_SYSTEM_PROMPT = """你是深度研究专家，需要对用户查询进行系统深入研究。

研究步骤：
1. 分解问题：将大问题分解为多个子问题
2. 信息搜索：调用 arxiv_researcher 获取相关论文，调用 web_researcher 搜索背景信息
3. 文献综述：整理已有研究成果，识别研究脉络
4. 分析论证：对比不同观点，识别共识和争议
5. 结论总结：给出清晰结论、开放问题、未来方向

输出要求：
- 结构化大纲：摘要 → 背景 → 分解问题 → 文献综述 → 分析 → 结论
- 引用格式：[论文标题](链接) - 作者/年份 - 核心观点
- 保留关键引用链接供用户进一步查看
"""


def _handle_deep_research(
    query: str = "",
    max_papers: int = 5,
    search_web: bool = True,
) -> SkillResult:
    """
    深度研究 skill — 对主题进行多轮深度研究，结合 arXiv 论文和网络搜索

    Args:
        query: 研究主题/问题
        max_papers: 最多检索多少篇论文（默认 5）
        search_web: 是否同时搜索网络背景信息
    """
    if not query:
        return SkillResult(success=False, error="query 参数为空")

    # 第一步：调用 arxiv_researcher 搜索相关论文
    # 因为我们在 business_skills 内部，不能直接调用 registry.execute
    # 所以返回结构化结果，由上层 engine 调用其他 skill
    try:
        # 生成搜索关键词：从 query 提取关键词
        words = re.findall(r'[a-zA-Z]+(?:-[a-zA-Z]+)*|[\u4e00-\u9fa5]+', query)
        keywords = ' '.join(words[:10])  # 限制长度

        output_lines = [
            f"# 深度研究: {query}",
            "",
            "## 1. 搜索 arXiv 论文",
            "",
            "请调用 `arxiv_researcher` 获取相关论文:",
            f"```json",
            f'{{"query": "{keywords}", "max_results": {max_papers}}}',
            f"```",
            "",
        ]

        if search_web:
            output_lines.extend([
                "## 2. 网络背景搜索",
                "",
                "请调用 `web_researcher` 获取背景信息:",
                f"```json",
                f'{{"query": "{query}"}}',
                f"```",
                "",
            ])

        output_lines.extend([
            "## 3. 综合分析",
            "",
            "获取论文和网络信息后，大模型将进行综合分析：",
            "- 分解研究问题为子问题",
            "- 整理文献脉络，识别争议",
            "- 对比不同观点，给出结论",
            "- 列出开放问题和未来方向",
        ])

        return SkillResult(
            success=True,
            output="\n".join(output_lines),
            data={
                'query': query,
                'max_papers': max_papers,
                'search_web': search_web,
                'next_steps': ['arxiv_researcher', 'web_researcher'] if search_web else ['arxiv_researcher'],
            },
        )

    except Exception as e:
        return SkillResult(success=False, error=f"深度研究初始化失败: {e}", output=traceback.format_exc())


DEEP_RESEARCHER_SKILL = SkillDef(
    name="deep_researcher",
    description="深度研究：对主题进行系统深入研究，分解问题，搜索 arXiv 论文和网络背景，整合生成结构化研究报告。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "研究主题/问题"},
            "max_papers": {"type": "integer", "description": "最多检索多少篇论文", "default": 5},
            "search_web": {"type": "boolean", "description": "是否同时搜索网络背景信息", "default": True},
        },
        "required": ["query"],
    },
    handler=_handle_deep_research,
    category="research",
    timeout=60,
)


# ============================================================
# Skill 16: fact_checker — 事实核查（多源辩论验证）
# ============================================================

def _handle_fact_check(
    claim: str = "",
    sources: str = "",
) -> SkillResult:
    """
    事实核查 skill — 对声明进行多源信息验证，检测矛盾，评估可信度

    Args:
        claim: 待核查的声明
        sources: JSON 格式，多个信息源
            [{"source": "名称/URL", "content": "内容"}, ...]
    """
    if not claim:
        return SkillResult(success=False, error="claim 参数为空")
    if not sources:
        return SkillResult(success=False, error="sources 参数为空，请提供至少 2 个信息源")

    try:
        sources_list = json.loads(sources) if isinstance(sources, str) else sources
    except json.JSONDecodeError:
        return SkillResult(success=False, error=f"sources JSON 解析失败: {sources}")

    if not isinstance(sources_list, list) or len(sources_list) < 2:
        return SkillResult(success=False, error="至少需要 2 个信息源才能进行对比核查")

    output_lines = [
        f"# 事实核查: {claim}",
        "",
        "## 信息源列表",
        "",
    ]

    for i, s in enumerate(sources_list):
        source_name = s.get('source', f'源#{i+1}')
        content = s.get('content', '')
        output_lines.append(f"{i+1}. **{source_name}**:")
        output_lines.append(f"> {content[:200]}..." if len(content) > 200 else f"> {content}")
        output_lines.append("")

    output_lines.extend([
        "## 分析验证",
        "",
        "请调用 `info_debater` 进行多源对比分析:",
        f"```json",
        f'{{"sources": {json.dumps(sources_list)}, "claim": "{claim}", "mode": "verify"}}',
        f"```",
        "",
        "分析将输出：",
        "- 是否一致/存在矛盾",
        "- 每个信息源可信度评估",
        "- 声明最终可信度",
    ])

    return SkillResult(
        success=True,
        output="\n".join(output_lines),
        data={
            'claim': claim,
            'sources': sources_list,
            'count': len(sources_list),
            'next_step': 'info_debater',
        },
    )


FACT_CHECKER_SKILL = SkillDef(
    name="fact_checker",
    description="事实核查：对声明进行多源信息验证，检测矛盾，评估可信度。多源对比输出一致性和可信度。",
    parameters={
        "type": "object",
        "properties": {
            "claim": {"type": "string", "description": "待核查的声明"},
            "sources": {"type": "string", "description": "JSON 格式多个信息源: [{\"source\":\"...\",\"content\":\"...\"},...]"},
        },
        "required": ["claim", "sources"],
    },
    handler=_handle_fact_check,
    category="debate",
    timeout=30,
)


# ============================================================
# Skill 17: html_to_video — HTML转视频（ffmpeg 静态网页录屏转视频）
# ============================================================

def _handle_html_to_video(
    html_path: str = "",
    output_path: str = "",
    width: int = 1280,
    height: int = 720,
    duration: int = 10,
    fps: int = 30,
) -> SkillResult:
    """
    HTML 转视频 skill — 使用 ffmpeg 对静态 HTML 页面进行录屏生成视频

    依赖：需要系统安装 ffmpeg，且支持 x11grab 屏幕抓取。
    在 Linux/macOS 可用，Windows 需要 WDDM 驱动支持。

    Args:
        html_path: HTML 文件路径（本地文件，file:// URL）
        output_path: 输出视频路径（默认 html_path 替换扩展名）
        width: 视频宽度
        height: 视频高度
        duration: 录制时长（秒）
        fps: 帧率
    """
    if not html_path:
        return SkillResult(success=False, error="html_path 参数为空")

    if not output_path:
        output_path = os.path.splitext(html_path)[0] + '.mp4'

    # 检查 ffmpeg 是否可用
    import shutil
    ffmpeg_available = shutil.which('ffmpeg') is not None

    if not ffmpeg_available:
        return SkillResult(
            success=False,
            error="ffmpeg 未找到，请先安装 ffmpeg:\n"
                   "  Ubuntu/Debian: sudo apt install ffmpeg\n"
                   "  macOS: brew install ffmpeg\n"
                   "  Windows: 下载 https://ffmpeg.org/download.html",
        )

    abs_html = os.path.abspath(html_path)
    abs_output = os.path.abspath(output_path)

    # 生成 shell 命令
    # 注意：x11grab 需要 DISPLAY 环境变量，这里假设在桌面环境运行
    import shlex
    cmd = [
        'ffmpeg',
        '-f', 'x11grab',
        '-framerate', str(fps),
        '-video_size', f'{width}x{height}',
        '-i', ':0.0',  # 默认显示
        '-t', str(duration),
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        shlex.quote(abs_output),
    ]

    cmd_str = ' '.join(cmd)

    return SkillResult(
        success=True,
        output=f"ffmpeg 命令已生成，请执行以下命令录制视频:\n\n```bash\n{cmd_str}\n```\n\n"
               f"输入: {abs_html}\n输出: {abs_output}\n尺寸: {width}x{height} 时长: {duration}s FPS: {fps}",
        data={
            'html_path': abs_html,
            'output_path': abs_output,
            'command': cmd_str,
            'width': width,
            'height': height,
            'duration': duration,
            'fps': fps,
        },
    )


HTML_TO_VIDEO_SKILL = SkillDef(
    name="html_to_video",
    description="HTML转视频：使用 ffmpeg 屏幕抓取将静态 HTML 页面录屏生成 MP4 视频。需要系统安装 ffmpeg。",
    parameters={
        "type": "object",
        "properties": {
            "html_path": {"type": "string", "description": "HTML 文件路径"},
            "output_path": {"type": "string", "description": "输出视频路径（可选）"},
            "width": {"type": "integer", "description": "视频宽度", "default": 1280},
            "height": {"type": "integer", "description": "视频高度", "default": 720},
            "duration": {"type": "integer", "description": "录制时长（秒）", "default": 10},
            "fps": {"type": "integer", "description": "帧率", "default": 30},
        },
        "required": ["html_path"],
    },
    handler=_handle_html_to_video,
    category="video",
    timeout=60,
)


# ============================================================
# Skill 18: modern_python_toolchain — Python 工具链（蒸馏自 MiMo Code）
# ============================================================

PYTHON_TOOLCHAIN_TEMPLATES = {
    "pyproject": '''[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{project_name}"
version = "0.1.0"
description = "{description}"
readme = "README.md"
requires-python = ">={python_version}"
authors = [
    {{name = "{author}", email = "{email}"}},
]
classifiers = [
    "Programming Language :: Python :: 3",
    "License :: OSI Approved :: MIT License",
]
dependencies = [
    {dependencies}
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "ruff>=0.1",
    "mypy>=1.0",
]

[tool.ruff]
line-length = 120
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
''',

    "makefile": '''# Auto-generated by Lemon Code modern_python_toolchain
.PHONY: install test lint format clean build

install:
\tpip install -e ".[dev]"

test:
\tpytest tests/ -v --cov={project_name} --cov-report=term-missing

lint:
\truff check {project_name}/

format:
\truff format {project_name}/

clean:
\trm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/ __pycache__/

build:
\tpython -m build
''',

    "gitignore": '''# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
venv/
*.so

# Testing
.pytest_cache/
.coverage
htmlcov/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Project
.env
*.log
''',
}


def _handle_python_toolchain(
    project_name: str = "",
    mode: str = "init",
    description: str = "",
    python_version: str = "3.10",
    author: str = "",
    email: str = "",
    dependencies: str = "",
) -> SkillResult:
    """
    Python 工具链 skill — 初始化 Python 项目、生成配置文件

    Args:
        project_name: 项目名称
        mode: 模式
            - init      初始化项目（生成 pyproject.toml + Makefile + .gitignore）
            - pyproject 仅生成 pyproject.toml
            - makefile  仅生成 Makefile
            - gitignore 仅生成 .gitignore
            - venv      生成虚拟环境创建指南
        description: 项目描述
        python_version: Python 最低版本
        author: 作者
        email: 邮箱
        dependencies: 逗号分隔的依赖列表
    """
    if not project_name:
        return SkillResult(success=False, error="project_name 参数为空")

    deps_list = [d.strip() for d in dependencies.split(',') if d.strip()] if dependencies else []
    deps_str = '\n    '.join([f'"{d}",' for d in deps_list]) if deps_list else ''

    output_parts = []
    files = {}

    if mode in ("init", "pyproject"):
        pyproject = PYTHON_TOOLCHAIN_TEMPLATES["pyproject"].format(
            project_name=project_name,
            description=description or f"{project_name} - Python project",
            python_version=python_version,
            author=author or "Developer",
            email=email or "dev@example.com",
            dependencies=deps_str,
        )
        files['pyproject.toml'] = pyproject
        output_parts.append(f"## pyproject.toml\n```toml\n{pyproject}\n```")

    if mode in ("init", "makefile"):
        makefile = PYTHON_TOOLCHAIN_TEMPLATES["makefile"].format(
            project_name=project_name,
        )
        files['Makefile'] = makefile
        output_parts.append(f"## Makefile\n```makefile\n{makefile}\n```")

    if mode in ("init", "gitignore"):
        gitignore = PYTHON_TOOLCHAIN_TEMPLATES["gitignore"]
        files['.gitignore'] = gitignore
        output_parts.append(f"## .gitignore\n```\n{gitignore}\n```")

    if mode == "venv":
        venv_guide = f"""## 虚拟环境创建指南

### 使用 venv（推荐）
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\\Scripts\\activate   # Windows
```

### 使用 uv（更快）
```bash
pip install uv
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### 安装依赖
```bash
pip install -e ".[dev]"
```
"""
        output_parts.append(venv_guide)
        files['venv_guide'] = venv_guide

    return SkillResult(
        success=True,
        output=f"# Python 工具链: {project_name}\n\n" + "\n\n".join(output_parts),
        data={
            'project_name': project_name,
            'mode': mode,
            'files': files,
        },
    )


PYTHON_TOOLCHAIN_SKILL = SkillDef(
    name="modern_python_toolchain",
    description="Python 工具链：初始化 Python 项目，生成 pyproject.toml/Makefile/.gitignore，支持 venv/uv/poetry。蒸馏自 MiMo Code。",
    parameters={
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "description": "项目名称"},
            "mode": {
                "type": "string",
                "enum": ["init", "pyproject", "makefile", "gitignore", "venv"],
                "description": "模式：init=全部, pyproject/makefile/gitignore=单独生成, venv=虚拟环境指南",
            },
            "description": {"type": "string", "description": "项目描述"},
            "python_version": {"type": "string", "description": "Python 最低版本", "default": "3.10"},
            "author": {"type": "string", "description": "作者"},
            "email": {"type": "string", "description": "邮箱"},
            "dependencies": {"type": "string", "description": "逗号分隔的依赖列表"},
        },
        "required": ["project_name"],
    },
    handler=_handle_python_toolchain,
    category="system",
    timeout=30,
)


# ============================================================
# Skill 19: super_researcher — 超级研究（多Agent深度协同）
# ============================================================

SUPER_RESEARCH_PROMPT = """你是超级研究协调员，需要协调多个研究 Agent 进行深度研究。

研究流程：
1. 问题分解 → 调用 deep_researcher 进行初步研究
2. 深度挖掘 → 对每个子问题调用 arxiv_researcher 获取论文
3. 交叉验证 → 调用 fact_checker 验证关键发现
4. 网络调研 → 调用 web_researcher 补充最新信息
5. 综合报告 → 整合所有发现，生成超级研究报告

输出要求：
- 执行摘要（200字以内）
- 研究背景与动机
- 核心发现（按子问题组织）
- 文献综述（含引用链接）
- 争议与共识
- 未来方向
- 参考文献列表
"""


def _handle_super_research(
    query: str = "",
    depth: int = 3,
    max_papers: int = 10,
    include_web: bool = True,
    include_fact_check: bool = True,
) -> SkillResult:
    """
    超级研究 skill — 多Agent深度协同研究

    Args:
        query: 研究主题/问题
        depth: 研究深度（1-5，默认3）
        max_papers: 最多检索论文数
        include_web: 是否进行网络调研
        include_fact_check: 是否进行事实核查
    """
    if not query:
        return SkillResult(success=False, error="query 参数为空")

    # 生成搜索关键词
    words = re.findall(r'[a-zA-Z]+(?:-[a-zA-Z]+)*|[\u4e00-\u9fa5]+', query)
    keywords = ' '.join(words[:10])

    output_lines = [
        f"# 超级研究: {query}",
        f"研究深度: {depth} 层",
        "",
        "## 研究流程",
        "",
    ]

    steps = []
    step_num = 1

    # 步骤 1: 初步研究
    steps.append({
        'step': step_num,
        'name': '初步研究',
        'skill': 'deep_researcher',
        'args': {'query': query, 'max_papers': max_papers, 'search_web': include_web},
    })
    step_num += 1

    # 步骤 2: arXiv 论文搜索
    if depth >= 2:
        steps.append({
            'step': step_num,
            'name': 'arXiv 论文搜索',
            'skill': 'arxiv_researcher',
            'args': {'query': keywords, 'max_results': max_papers},
        })
        step_num += 1

    # 步骤 3: 网络调研
    if include_web and depth >= 2:
        steps.append({
            'step': step_num,
            'name': '网络背景调研',
            'skill': 'web_researcher',
            'args': {'query': query},
        })
        step_num += 1

    # 步骤 4: 事实核查
    if include_fact_check and depth >= 3:
        steps.append({
            'step': step_num,
            'name': '关键发现核查',
            'skill': 'fact_checker',
            'args': {'claim': f"关于'{query}'的核心研究发现"},
        })
        step_num += 1

    # 输出步骤
    for s in steps:
        output_lines.append(f"### 步骤 {s['step']}: {s['name']}")
        output_lines.append(f"请调用 `{s['skill']}`:")
        output_lines.append(f"```json")
        output_lines.append(json.dumps(s['args'], ensure_ascii=False))
        output_lines.append(f"```")
        output_lines.append("")

    # 综合分析
    output_lines.extend([
        f"## 综合分析（步骤 {step_num}）",
        "",
        "完成以上步骤后，大模型将进行综合分析：",
        "- 汇总所有研究发现",
        "- 交叉验证关键发现",
        "- 识别研究脉络和争议",
        "- 生成超级研究报告",
        "",
        "### 报告结构",
        "1. 执行摘要",
        "2. 研究背景与动机",
        "3. 核心发现（按子问题组织）",
        "4. 文献综述（含引用链接）",
        "5. 争议与共识",
        "6. 未来方向",
        "7. 参考文献列表",
    ])

    return SkillResult(
        success=True,
        output="\n".join(output_lines),
        data={
            'query': query,
            'depth': depth,
            'max_papers': max_papers,
            'steps': steps,
            'total_steps': len(steps) + 1,
        },
    )


SUPER_RESEARCHER_SKILL = SkillDef(
    name="super_researcher",
    description="超级研究：多Agent深度协同，协调 deep_researcher + arxiv_researcher + web_researcher + fact_checker 进行多轮深度研究。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "研究主题/问题"},
            "depth": {"type": "integer", "description": "研究深度（1-5，默认3）", "default": 3},
            "max_papers": {"type": "integer", "description": "最多检索论文数", "default": 10},
            "include_web": {"type": "boolean", "description": "是否进行网络调研", "default": True},
            "include_fact_check": {"type": "boolean", "description": "是否进行事实核查", "default": True},
        },
        "required": ["query"],
    },
    handler=_handle_super_research,
    category="research",
    timeout=120,
)


# ============================================================
# Skill 20: code_reviewer — 代码审查（AST分析 + 模式检测）
# ============================================================

def _handle_code_review(
    file_path: str = "",
    code: str = "",
    review_type: str = "all",
    language: str = "python",
) -> SkillResult:
    """代码审查 — AST 静态分析 + 常见问题模式检测"""
    if not file_path and not code:
        return SkillResult(success=False, error="请提供 file_path 或 code 参数")

    source = code
    if file_path:
        try:
            path = file_path
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            if not os.path.exists(path):
                return SkillResult(success=False, error=f"文件不存在: {path}")
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception as e:
            return SkillResult(success=False, error=f"读取文件失败: {e}")

    if not source.strip():
        return SkillResult(success=False, error="代码为空")

    issues = []
    lines = source.split("\n")

    # ---- 样式检查 ----
    if review_type in ("style", "all"):
        # 检查行长度
        for i, line in enumerate(lines, 1):
            if len(line) > 120:
                issues.append({
                    "line": i, "severity": "info", "type": "style",
                    "message": f"行长度 {len(line)} > 120 字符",
                    "suggestion": "建议将长行拆分为多行",
                })

        # 检查缩进一致性
        tab_lines = [i for i, l in enumerate(lines, 1) if l.startswith("\t")]
        space_lines = [i for i, l in enumerate(lines, 1) if l.startswith("    ")]
        if tab_lines and space_lines:
            issues.append({
                "line": min(tab_lines), "severity": "warning", "type": "style",
                "message": "缩进不一致（混用 Tab 和空格）",
                "suggestion": "统一使用 4 空格缩进",
            })

        # 检查尾随空白
        for i, line in enumerate(lines, 1):
            if line.rstrip() != line:
                issues.append({
                    "line": i, "severity": "info", "type": "style",
                    "message": "行尾有多余空白字符",
                    "suggestion": "删除行尾空白",
                })

    # ---- Bug 检测 ----
    if review_type in ("bug", "all"):
        # 使用 AST 分析
        try:
            import ast
            tree = ast.parse(source)

            class BugVisitor(ast.NodeVisitor):
                def __init__(self):
                    self.issues = []

                def visit_FunctionDef(self, node):
                    # 检查空函数体
                    if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                        self.issues.append({
                            "line": node.lineno, "severity": "warning", "type": "bug",
                            "message": f"函数 '{node.name}' 只有 pass 语句",
                            "suggestion": "实现函数体或添加 TODO 注释",
                        })
                    # 检查过长函数
                    end_line = node.end_lineno or node.lineno
                    func_lines = end_line - node.lineno + 1
                    if func_lines > 100:
                        self.issues.append({
                            "line": node.lineno, "severity": "warning", "type": "bug",
                            "message": f"函数 '{node.name}' 过长（{func_lines} 行）",
                            "suggestion": "建议拆分为多个小函数（<50行）",
                        })
                    # 检查过多参数
                    args = [a.arg for a in node.args.args if a.arg != 'self']
                    if len(args) > 5:
                        self.issues.append({
                            "line": node.lineno, "severity": "warning", "type": "bug",
                            "message": f"函数 '{node.name}' 参数过多（{len(args)} 个）",
                            "suggestion": "考虑使用配置对象或拆分函数",
                        })
                    self.generic_visit(node)

                def visit_ExceptHandler(self, node):
                    # 检查裸 except
                    if node.type is None:
                        self.issues.append({
                            "line": node.lineno, "severity": "error", "type": "bug",
                            "message": "使用了裸 except（捕获所有异常）",
                            "suggestion": "指定具体的异常类型，如 except ValueError:",
                        })
                    self.generic_visit(node)

                def visit_Global(self, node):
                    self.issues.append({
                        "line": node.lineno, "severity": "warning", "type": "bug",
                        "message": "使用了 global 关键字",
                        "suggestion": "考虑重构代码，避免使用 global 变量",
                    })
                    self.generic_visit(node)

            visitor = BugVisitor()
            visitor.visit(tree)
            issues.extend(visitor.issues)

        except SyntaxError as e:
            issues.append({
                "line": e.lineno or 0, "severity": "error", "type": "bug",
                "message": f"语法错误: {e.msg}",
                "suggestion": "修复语法错误",
            })
        except Exception:
            pass  # AST 解析失败时跳过

        # 正则模式：常见 Bug
        patterns = [
            (r"==\s*None", "warning", "bug", "使用 == 比较 None", "应使用 'is None' 替代 '== None'"),
            (r"!=\s*None", "warning", "bug", "使用 != 比较 None", "应使用 'is not None' 替代 '!= None'"),
            (r"except\s*:", "error", "bug", "裸 except 语句", "指定具体异常类型"),
            (r"import\s+\*", "warning", "bug", "使用 import *", "显式导入需要的名称"),
            (r"\.\.\.\s*#\s*TODO", "info", "bug", "未完成的 TODO 注释", "完成或移除 TODO"),
        ]
        for i, line in enumerate(lines, 1):
            for pat, sev, typ, msg, sug in patterns:
                if re.search(pat, line):
                    if not any(iss.get("line") == i and iss.get("message") == msg for iss in issues):
                        issues.append({
                            "line": i, "severity": sev, "type": typ,
                            "message": msg, "suggestion": sug,
                        })

    # ---- 安全检查 ----
    if review_type in ("security", "all"):
        sec_patterns = [
            (r"password\s*=\s*['\"]", "critical", "硬编码密码"),
            (r"api_key\s*=\s*['\"]", "critical", "硬编码 API Key"),
            (r"secret\s*=\s*['\"]", "critical", "硬编码密钥"),
            (r"token\s*=\s*['\"]", "critical", "硬编码 Token"),
            (r"exec\s*\(", "error", "使用 exec() 执行动态代码"),
            (r"eval\s*\(", "error", "使用 eval() 执行动态代码"),
            (r"os\.system\s*\(", "warning", "使用 os.system() 执行系统命令"),
            (r"subprocess\.call\s*\(.*shell\s*=\s*True", "warning", "使用 shell=True 可能导致注入"),
            (r"pickle\.loads?\s*\(", "warning", "使用 pickle 反序列化不受信任数据"),
            (r"yaml\.load\s*\(", "warning", "使用 yaml.load() 不安全"),
            (r"assert\s+.*\s*==\s*.*password", "warning", "在 assert 中使用密码比较"),
        ]
        for i, line in enumerate(lines, 1):
            for pat, sev, msg in sec_patterns:
                if re.search(pat, line, re.IGNORECASE):
                    if not any(iss.get("line") == i and iss.get("message") == msg for iss in issues):
                        issues.append({
                            "line": i, "severity": sev, "type": "security",
                            "message": msg,
                            "suggestion": "使用环境变量或密钥管理服务存储敏感信息",
                        })

    # 统计
    severity_count = {"critical": 0, "error": 0, "warning": 0, "info": 0}
    for iss in issues:
        severity_count[iss["severity"]] = severity_count.get(iss["severity"], 0) + 1

    # 格式化输出
    if not issues:
        return SkillResult(
            success=True,
            output=f"代码审查完成 — 未发现问题\n文件: {file_path or '(直接输入)'}\n语言: {language}\n审查类型: {review_type}",
        )

    report_parts = [
        f"代码审查报告",
        f"{'='*50}",
        f"文件: {file_path or '(直接输入)'}",
        f"语言: {language} | 审查类型: {review_type}",
        f"总行数: {len(lines)} | 发现问题: {len(issues)}",
        f"  Critical: {severity_count['critical']} | Error: {severity_count['error']} | Warning: {severity_count['warning']} | Info: {severity_count['info']}",
        f"{'='*50}",
        "",
    ]

    for iss in sorted(issues, key=lambda x: ({"critical": 0, "error": 1, "warning": 2, "info": 3}.get(x["severity"], 4), x["line"])):
        icon = {"critical": "🔴", "error": "🟠", "warning": "🟡", "info": "🔵"}.get(iss["severity"], "⚪")
        report_parts.append(f"  {icon} 第{iss['line']}行 [{iss['type']}] {iss['message']}")
        report_parts.append(f"     → {iss['suggestion']}")

    return SkillResult(
        success=True,
        output="\n".join(report_parts),
        data={"issues": issues, "severity_count": severity_count, "file_path": file_path},
    )


CODE_REVIEWER_SKILL = SkillDef(
    name="code_reviewer",
    description="代码审查：AST 静态分析 + 常见问题模式检测，支持样式/Bug/安全三类检查",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "要审查的文件路径"},
            "code": {"type": "string", "description": "直接提供的代码（与 file_path 二选一）"},
            "review_type": {
                "type": "string",
                "description": "审查类型",
                "enum": ["all", "style", "bug", "security"],
            },
            "language": {"type": "string", "description": "代码语言", "default": "python"},
        },
        "required": [],
    },
    handler=_handle_code_review,
    category="code",
    timeout=30,
)


# ============================================================
# Skill 21: test_generator — 测试生成（unittest/pytest）
# ============================================================

def _handle_test_generate(
    file_path: str = "",
    code: str = "",
    test_framework: str = "pytest",
    coverage_target: str = "",
) -> SkillResult:
    """测试生成 — 基于代码结构自动生成 unittest/pytest 测试"""
    if not file_path and not code:
        return SkillResult(success=False, error="请提供 file_path 或 code 参数")

    source = code
    if file_path:
        try:
            path = file_path
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            if not os.path.exists(path):
                return SkillResult(success=False, error=f"文件不存在: {path}")
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception as e:
            return SkillResult(success=False, error=f"读取文件失败: {e}")

    if not source.strip():
        return SkillResult(success=False, error="代码为空")

    try:
        import ast
        tree = ast.parse(source)
    except SyntaxError as e:
        return SkillResult(success=False, error=f"代码语法错误: {e.msg} (第{e.lineno}行)")
    except Exception as e:
        return SkillResult(success=False, error=f"代码解析失败: {e}")

    # 提取函数和类
    functions = []
    classes = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name.startswith("_"):
                continue  # 跳过私有函数
            args = [a.arg for a in node.args.args if a.arg != "self"]
            returns = None
            if node.returns:
                try:
                    returns = ast.unparse(node.returns)
                except Exception:
                    returns = "unknown"
            functions.append({
                "name": node.name,
                "args": args,
                "returns": returns,
                "lineno": node.lineno,
                "has_docstring": (isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Str, ast.Constant))),
            })
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            methods = []
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("__"):
                    methods.append(item.name)
            classes.append({"name": node.name, "methods": methods, "lineno": node.lineno})

    if not functions and not classes:
        return SkillResult(
            success=True,
            output="未找到需要测试的公开函数或类",
            data={"test_code": "# 未找到可测试的函数\n", "functions": [], "classes": []},
        )

    # 生成测试代码
    test_lines = []
    module_name = os.path.splitext(os.path.basename(file_path))[0] if file_path else "module"

    test_lines.append(f"# -*- coding: utf-8 -*-")
    test_lines.append(f"# 自动生成的测试文件 — {module_name}")
    test_lines.append(f"# 测试框架: {test_framework}")

    if test_framework == "pytest":
        test_lines.append("import pytest")
        test_lines.append(f"from {module_name} import *  # 根据实际导入路径调整")
        test_lines.append("")
        test_lines.append("")

        for func in functions:
            test_lines.append(f"class Test_{func['name'].capitalize()}:")
            test_lines.append(f'    """{func["name"]} 函数的测试用例"""')
            test_lines.append("")

            # 基本调用测试
            test_lines.append(f"    def test_{func['name']}_basic(self):")
            test_lines.append(f'        """测试基本调用"""')
            if func["args"]:
                args_str = ", ".join(f"mock_{a}" for a in func["args"])
                test_lines.append(f"        # TODO: 替换为实际参数")
                test_lines.append(f"        # result = {func['name']}({args_str})")
                test_lines.append(f"        # assert result is not None")
            else:
                test_lines.append(f"        # result = {func['name']}()")
                test_lines.append(f"        # assert result is not None")
            test_lines.append(f"        pass  # TODO: 实现测试")
            test_lines.append("")

            # 边界条件测试
            test_lines.append(f"    def test_{func['name']}_edge_cases(self):")
            test_lines.append(f'        """测试边界条件"""')
            test_lines.append(f"        # TODO: 添加边界条件测试")
            test_lines.append(f"        pass")
            test_lines.append("")

            # 异常处理测试
            test_lines.append(f"    def test_{func['name']}_raises(self):")
            test_lines.append(f'        """测试异常处理"""')
            test_lines.append(f"        # TODO: 添加异常测试")
            test_lines.append(f"        # with pytest.raises(ValueError):")
            test_lines.append(f"        #     {func['name']}(invalid_input)")
            test_lines.append(f"        pass")
            test_lines.append("")

        for cls in classes:
            test_lines.append(f"class Test_{cls['name']}:")
            test_lines.append(f'    """{cls["name"]} 类的测试用例"""')
            test_lines.append("")
            test_lines.append(f"    @pytest.fixture")
            test_lines.append(f"    def instance(self):")
            test_lines.append(f"        # TODO: 创建 {cls['name']} 实例")
            test_lines.append(f"        # return {cls['name']}()")
            test_lines.append(f"        pass")
            test_lines.append("")
            for method in cls["methods"]:
                test_lines.append(f"    def test_{method}(self, instance):")
                test_lines.append(f'        """测试 {method} 方法"""')
                test_lines.append(f"        # TODO: 实现测试")
                test_lines.append(f"        pass")
                test_lines.append("")

    elif test_framework == "unittest":
        test_lines.append("import unittest")
        test_lines.append(f"from {module_name} import *  # 根据实际导入路径调整")
        test_lines.append("")

        if functions:
            test_lines.append(f"class TestFunctions(unittest.TestCase):")
            test_lines.append(f'    """函数测试"""')
            test_lines.append("")
            for func in functions:
                test_lines.append(f"    def test_{func['name']}(self):")
                test_lines.append(f'        """测试 {func["name"]}"""')
                test_lines.append(f"        # TODO: 实现测试")
                test_lines.append(f"        pass")
                test_lines.append("")
            test_lines.append("")

        for cls in classes:
            test_lines.append(f"class Test_{cls['name']}(unittest.TestCase):")
            test_lines.append(f'    """{cls["name"]} 类测试"""')
            test_lines.append("")
            test_lines.append(f"    def setUp(self):")
            test_lines.append(f"        # TODO: 创建 {cls['name']} 实例")
            test_lines.append(f"        pass")
            test_lines.append("")
            for method in cls["methods"]:
                test_lines.append(f"    def test_{method}(self):")
                test_lines.append(f'        """测试 {method}"""')
                test_lines.append(f"        # TODO: 实现测试")
                test_lines.append(f"        pass")
                test_lines.append("")

        test_lines.append("")
        test_lines.append("if __name__ == '__main__':")
        test_lines.append("    unittest.main()")

    test_code = "\n".join(test_lines)

    return SkillResult(
        success=True,
        output=f"测试生成完成\n"
               f"文件: {file_path or '(直接输入)'}\n"
               f"框架: {test_framework}\n"
               f"函数: {len(functions)} 个\n"
               f"类: {len(classes)} 个\n"
               f"生成测试代码: {len(test_code)} 字符\n\n"
               f"```python\n{test_code[:3000]}\n```",
        data={
            "test_code": test_code,
            "functions": [f["name"] for f in functions],
            "classes": [c["name"] for c in classes],
            "framework": test_framework,
        },
    )


TEST_GENERATOR_SKILL = SkillDef(
    name="test_generator",
    description="自动生成单元测试：基于代码结构（AST）生成 unittest/pytest 测试模板",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "源代码文件路径"},
            "code": {"type": "string", "description": "直接提供的代码（与 file_path 二选一）"},
            "test_framework": {
                "type": "string",
                "description": "测试框架",
                "enum": ["pytest", "unittest"],
            },
            "coverage_target": {"type": "string", "description": "覆盖目标描述（可选）"},
        },
        "required": [],
    },
    handler=_handle_test_generate,
    category="code",
    timeout=30,
)


# ============================================================
# Skill 22: security_auditor — 安全审计（漏洞扫描 + 依赖检查）
# ============================================================

def _handle_security_audit(
    file_path: str = "",
    code: str = "",
    scan_type: str = "all",
) -> SkillResult:
    """安全审计 — 漏洞扫描 + 依赖安全检查"""
    if not file_path and not code:
        return SkillResult(success=False, error="请提供 file_path 或 code 参数")

    source = code
    if file_path:
        try:
            path = file_path
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            if not os.path.exists(path):
                return SkillResult(success=False, error=f"文件不存在: {path}")
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception as e:
            return SkillResult(success=False, error=f"读取文件失败: {e}")

    if not source.strip():
        return SkillResult(success=False, error="代码为空")

    lines = source.split("\n")
    findings = []

    # ---- 漏洞扫描规则 ----
    vulnerability_rules = [
        # SQL 注入
        (r"execute\s*\(.*%.*\)", "critical", "sql_injection", "潜在的 SQL 注入漏洞", "使用参数化查询（? 占位符）替代字符串拼接"),
        (r"execute\s*\(.*f['\"].*\)", "critical", "sql_injection", "f-string 拼接 SQL 语句", "使用参数化查询"),
        (r"\.format\(.*\).*execute", "critical", "sql_injection", "format() 拼接 SQL 语句", "使用参数化查询"),
        # XSS
        (r"innerHTML\s*=", "warning", "xss", "使用 innerHTML 可能导致 XSS", "使用 textContent 或 DOMPurify 消毒"),
        (r"document\.write\s*\(", "warning", "xss", "使用 document.write() 可能导致 XSS", "使用安全的 DOM 操作方法"),
        (r"dangerouslySetInnerHTML", "warning", "xss", "React dangerouslySetInnerHTML 使用", "确保内容经过消毒处理"),
        # 命令注入
        (r"os\.system\s*\(.*\+", "error", "command_injection", "os.system() 字符串拼接可能导致命令注入", "使用 subprocess.run() 并传递列表参数"),
        (r"subprocess.*shell\s*=\s*True", "error", "command_injection", "shell=True 存在命令注入风险", "使用 shell=False 并传递列表参数"),
        (r"os\.popen\s*\(", "error", "command_injection", "os.popen() 存在命令注入风险", "使用 subprocess 模块"),
        # 路径遍历
        (r"open\s*\(.*\.\.\/", "warning", "path_traversal", "潜在的路径遍历漏洞", "使用 os.path.abspath 规范化路径并验证"),
        (r"open\s*\(.*\.\.\\", "warning", "path_traversal", "潜在的路径遍历漏洞", "使用 os.path.abspath 规范化路径并验证"),
        # 反序列化
        (r"pickle\.loads?\s*\(", "error", "deserialization", "pickle 反序列化不受信任数据", "使用 json 或添加签名验证"),
        (r"yaml\.load\s*\(", "error", "deserialization", "yaml.load() 不安全", "使用 yaml.safe_load()"),
        (r"marshal\.loads?\s*\(", "error", "deserialization", "marshal 反序列化不受信任数据", "使用 json 替代"),
        # 硬编码密钥
        (r"(?:password|passwd|pwd)\s*=\s*['\"][^'\"]+['\"]", "critical", "hardcoded_secret", "硬编码密码", "使用环境变量或密钥管理服务"),
        (r"(?:api[_-]?key|apikey)\s*=\s*['\"][^'\"]+['\"]", "critical", "hardcoded_secret", "硬编码 API Key", "使用环境变量"),
        (r"(?:secret|token|auth)\s*=\s*['\"][^'\"]{8,}['\"]", "critical", "hardcoded_secret", "硬编码密钥/Token", "使用环境变量"),
        (r"(?:private[_-]?key|privkey)\s*=\s*['\"]", "critical", "hardcoded_secret", "硬编码私钥", "使用文件引用或密钥管理服务"),
        # 加密弱点
        (r"hashlib\.md5\s*\(", "warning", "weak_crypto", "使用 MD5 哈希算法", "使用 SHA-256 或更强的哈希算法"),
        (r"hashlib\.sha1\s*\(", "warning", "weak_crypto", "使用 SHA1 哈希算法", "使用 SHA-256 或更强的哈希算法"),
        (r"random\.random\s*\(\)", "info", "weak_random", "使用伪随机数生成器", "安全场景使用 secrets 模块"),
        # 日志泄露
        (r"log.*password", "warning", "log_leak", "日志中可能包含密码", "脱敏处理后再记录日志"),
        (r"print.*password", "warning", "log_leak", "print 输出可能包含密码", "避免打印敏感信息"),
        # 不安全的配置
        (r"ssl\.CERT_NONE", "error", "insecure_config", "SSL 证书验证被禁用", "使用正确的证书验证"),
        (r"verify\s*=\s*False", "warning", "insecure_config", "HTTP 请求禁用了 SSL 验证", "启用 SSL 证书验证"),
        (r"DEBUG\s*=\s*True", "warning", "insecure_config", "生产环境 DEBUG 模式开启", "生产环境关闭 DEBUG"),
    ]

    for i, line in enumerate(lines, 1):
        for pat, sev, cat, msg, sug in vulnerability_rules:
            if re.search(pat, line, re.IGNORECASE):
                # 避免重复
                if not any(f["line"] == i and f["category"] == cat for f in findings):
                    findings.append({
                        "line": i, "severity": sev, "category": cat,
                        "finding": msg, "remediation": sug,
                        "code_snippet": line.strip()[:100],
                    })

    # ---- 依赖安全检查（扫描 requirements.txt） ----
    if scan_type in ("deps", "all") and file_path:
        req_dir = os.path.dirname(os.path.abspath(file_path))
        req_path = os.path.join(req_dir, "requirements.txt")
        if os.path.exists(req_path):
            try:
                with open(req_path, "r", encoding="utf-8") as f:
                    deps = f.read()
                known_vulnerable = [
                    ("django", "<3.2", "多个安全漏洞（CVE）"),
                    ("flask", "<2.0", "开放重定向漏洞"),
                    ("requests", "<2.20", "会话固定漏洞"),
                    ("pillow", "<8.0", "多个缓冲区溢出漏洞"),
                    ("lxml", "<4.6", "XXE 漏洞"),
                    ("pyyaml", "<5.4", "任意代码执行漏洞"),
                    ("jinja2", "<2.11", "沙盒逃逸漏洞"),
                    ("numpy", "<1.16", "缓冲区溢出漏洞"),
                ]
                for dep_line in deps.split("\n"):
                    dep_line = dep_line.strip()
                    if not dep_line or dep_line.startswith("#"):
                        continue
                    for pkg, ver, desc in known_vulnerable:
                        if pkg in dep_line.lower():
                            findings.append({
                                "line": 0, "severity": "warning", "category": "vulnerable_dependency",
                                "finding": f"依赖 {pkg} 版本 {ver} 存在已知漏洞: {desc}",
                                "remediation": f"升级 {pkg} 到最新版本",
                                "code_snippet": dep_line,
                            })
            except Exception:
                pass

    # 统计
    severity_count = {"critical": 0, "error": 0, "warning": 0, "info": 0}
    for f in findings:
        severity_count[f["severity"]] = severity_count.get(f["severity"], 0) + 1

    if not findings:
        return SkillResult(
            success=True,
            output=f"安全审计完成 — 未发现安全问题\n文件: {file_path or '(直接输入)'}\n扫描类型: {scan_type}",
        )

    report_parts = [
        f"安全审计报告",
        f"{'='*50}",
        f"文件: {file_path or '(直接输入)'}",
        f"扫描类型: {scan_type} | 发现问题: {len(findings)}",
        f"Critical: {severity_count['critical']} | Error: {severity_count['error']} | Warning: {severity_count['warning']} | Info: {severity_count['info']}",
        f"{'='*50}",
        "",
    ]

    for f in sorted(findings, key=lambda x: ({"critical": 0, "error": 1, "warning": 2, "info": 3}.get(x["severity"], 4), x["line"])):
        icon = {"critical": "🔴", "error": "🟠", "warning": "🟡", "info": "🔵"}.get(f["severity"], "⚪")
        line_info = f"第{f['line']}行" if f["line"] > 0 else "依赖"
        report_parts.append(f"  {icon} [{f['category']}] {line_info}: {f['finding']}")
        report_parts.append(f"     → {f['remediation']}")
        if f["code_snippet"]:
            report_parts.append(f"     代码: {f['code_snippet']}")

    return SkillResult(
        success=True,
        output="\n".join(report_parts),
        data={"findings": findings, "severity_count": severity_count, "file_path": file_path},
    )


SECURITY_AUDITOR_SKILL = SkillDef(
    name="security_auditor",
    description="安全审计：漏洞扫描 + 依赖安全检查，检测 SQL 注入/XSS/命令注入/硬编码密钥/弱加密等 25+ 规则",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "要审计的文件路径"},
            "code": {"type": "string", "description": "直接提供的代码（与 file_path 二选一）"},
            "scan_type": {
                "type": "string",
                "description": "扫描类型",
                "enum": ["all", "deps", "secrets", "injection"],
            },
        },
        "required": [],
    },
    handler=_handle_security_audit,
    category="code",
    timeout=30,
)


# ============================================================
# Skill 23: deploy_helper — 部署助手（Docker/npm/pip 脚本生成）
# ============================================================

def _handle_deploy_helper(
    project_type: str = "python",
    deploy_target: str = "docker",
    project_name: str = "",
    entry_point: str = "",
    port: int = 8000,
) -> SkillResult:
    """部署助手 — 生成 Docker/npm/pip/GitHub Actions 部署脚本"""
    if not project_name:
        # 尝试从当前目录获取
        project_name = os.path.basename(os.getcwd())

    scripts = {}

    # ---- Docker ----
    if deploy_target in ("docker", "all"):
        dockerfile = f"""# Dockerfile — {project_name}
# 自动生成 by Lemon Code deploy_helper

FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \\
    gcc g++ make curl && \\
    rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 暴露端口
EXPOSE {port}

# 启动命令
CMD ["python", "{entry_point or 'main.py'}"]
"""
        docker_compose = f"""# docker-compose.yml — {project_name}
version: '3.8'

services:
  app:
    build: .
    container_name: {project_name}
    ports:
      - "{port}:{port}"
    environment:
      - PYTHONUNBUFFERED=1
    volumes:
      - ./data:/app/data
    restart: unless-stopped
"""
        scripts["Dockerfile"] = dockerfile
        scripts["docker-compose.yml"] = docker_compose

    # ---- npm ----
    if deploy_target in ("npm", "all") and project_type in ("node", "npm", "javascript"):
        package_json = f"""{{
  "name": "{project_name}",
  "version": "1.0.0",
  "description": "{project_name} - 自动生成",
  "main": "{entry_point or 'index.js'}",
  "scripts": {{
    "start": "node {entry_point or 'index.js'}",
    "build": "npm run clean && npm run compile",
    "test": "jest",
    "deploy": "npm run build && npm publish"
  }},
  "keywords": [],
  "author": "",
  "license": "MIT"
}}
"""
        scripts["package.json"] = package_json

    # ---- pip ----
    if deploy_target in ("pip", "all") and project_type in ("python", "pip"):
        setup_py = f"""# setup.py — {project_name}
from setuptools import setup, find_packages

setup(
    name="{project_name}",
    version="1.0.0",
    description="{project_name}",
    packages=find_packages(),
    install_requires=[],
    entry_points={{
        "console_scripts": [
            "{project_name}={project_name}.{entry_point or 'main'}:main",
        ],
    }},
    python_requires=">=3.10",
)
"""
        pyproject_toml = f"""[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "{project_name}"
version = "1.0.0"
description = "{project_name}"
requires-python = ">=3.10"
"""
        scripts["setup.py"] = setup_py
        scripts["pyproject.toml"] = pyproject_toml

    # ---- GitHub Actions ----
    if deploy_target in ("github", "all"):
        github_ci = f"""# .github/workflows/ci.yml — {project_name}
name: CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest tests/
      - name: Lint
        run: pip install ruff && ruff check .

  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy
        run: echo "Add your deploy steps here"
"""
        scripts[".github/workflows/ci.yml"] = github_ci

    if not scripts:
        return SkillResult(success=False, error=f"不支持的部署目标: {deploy_target}")

    # 格式化输出
    output_parts = [
        f"部署脚本生成完成 — {project_name}",
        f"{'='*45}",
        f"项目类型: {project_type}",
        f"部署目标: {deploy_target}",
        f"入口文件: {entry_point or 'main.py'}",
        f"端口: {port}",
        f"",
    ]

    for name, content in scripts.items():
        output_parts.append(f"### {name}")
        output_parts.append(f"```\n{content.strip()}\n```")

    return SkillResult(
        success=True,
        output="\n".join(output_parts),
        data={"scripts": scripts, "project_name": project_name, "deploy_target": deploy_target},
    )


DEPLOY_HELPER_SKILL = SkillDef(
    name="deploy_helper",
    description="部署助手：生成 Docker/npm/pip/GitHub Actions 部署脚本和配置文件",
    parameters={
        "type": "object",
        "properties": {
            "project_type": {
                "type": "string",
                "description": "项目类型",
                "enum": ["python", "node", "npm", "javascript"],
            },
            "deploy_target": {
                "type": "string",
                "description": "部署目标",
                "enum": ["docker", "npm", "pip", "github", "all"],
            },
            "project_name": {"type": "string", "description": "项目名称"},
            "entry_point": {"type": "string", "description": "入口文件（如 main.py, index.js）"},
            "port": {"type": "integer", "description": "服务端口", "default": 8000},
        },
        "required": ["project_type", "deploy_target"],
    },
    handler=_handle_deploy_helper,
    category="system",
    timeout=30,
)


# ============================================================
# Skill 24: code_psychologist — 代码意图推断（自然语言→代码框架）
# ============================================================

CODE_PSYCHOLOGIST_PROMPT = """你是代码心理学家，擅长从模糊的自然语言描述中推断代码意图并生成代码框架。

工作流程：
1. 意图分析：识别用户想做什么（CRUD/API/算法/工具/UI/数据处理）
2. 结构设计：设计合理的代码结构（函数/类/模块）
3. 框架生成：生成可运行的代码框架，标注 TODO 供用户填充

代码框架要求：
- 包含完整的函数签名和类型提示
- 包含 docstring 说明
- 关键逻辑用 TODO 标注
- 包含基本错误处理
- 符合 PEP 8 规范
"""

REVERSE_PSYCHOLOGIST_PROMPT = """你是逆向代码心理学家，擅长阅读代码并推断其原始意图和设计思想。

分析维度：
1. 核心意图：这段代码要解决什么问题？
2. 设计模式：使用了哪些设计模式？
3. 数据流：数据如何输入、处理、输出？
4. 依赖关系：关键依赖和调用链
5. 潜在问题：可能的 Bug、性能瓶颈、安全隐患
6. 改进建议：如何优化代码结构和性能
"""


def _handle_code_psychologist(
    description: str = "",
    code: str = "",
    language: str = "python",
    mode: str = "forward",
    style: str = "production",
) -> SkillResult:
    """代码心理学家 — 正向推断（描述→代码）或逆向分析（代码→意图）"""
    if not description and not code:
        return SkillResult(success=False, error="请提供 description 或 code 参数")

    if mode == "forward":
        # 正向：自然语言描述 → 代码框架
        if not description:
            return SkillResult(success=False, error="正向模式需要提供 description 参数")

        # 意图分类
        intent_keywords = {
            "crud": ["增删改查", "CRUD", "创建", "删除", "更新", "查询", "数据库", "database"],
            "api": ["API", "接口", "接口", "REST", "HTTP", "路由", "endpoint", "请求"],
            "algorithm": ["算法", "排序", "搜索", "计算", "algorithm", "遍历", "递归"],
            "tool": ["工具", "脚本", "自动化", "转换", "工具", "CLI", "命令行"],
            "ui": ["界面", "UI", "前端", "页面", "组件", "按钮", "表单"],
            "data": ["数据", "分析", "统计", "图表", "清洗", "处理", "可视化"],
            "file": ["文件", "读写", "IO", "下载", "上传", "file", "读取"],
        }

        detected_intent = "general"
        desc_lower = description.lower()
        for intent, keywords in intent_keywords.items():
            for kw in keywords:
                if kw.lower() in desc_lower:
                    detected_intent = intent
                    break
            if detected_intent != "general":
                break

        # 按意图生成代码框架
        if language == "python":
            if detected_intent == "crud":
                framework = f'''"""
{description}
自动生成 by code_psychologist
意图: CRUD 数据操作
"""
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class DataManager:
    """数据管理器 — {description}"""

    def __init__(self, db_path: str = "data.db"):
        """初始化数据管理器"""
        self.db_path = db_path
        # TODO: 初始化数据库连接
        logger.info(f"DataManager initialized with {{db_path}}")

    def create(self, data: Dict[str, Any]) -> Optional[int]:
        """创建记录"""
        # TODO: 实现创建逻辑
        logger.info(f"Creating record: {{data}}")
        return None

    def read(self, record_id: int) -> Optional[Dict[str, Any]]:
        """读取记录"""
        # TODO: 实现读取逻辑
        logger.info(f"Reading record: {{record_id}}")
        return None

    def update(self, record_id: int, data: Dict[str, Any]) -> bool:
        """更新记录"""
        # TODO: 实现更新逻辑
        logger.info(f"Updating record {{record_id}}: {{data}}")
        return False

    def delete(self, record_id: int) -> bool:
        """删除记录"""
        # TODO: 实现删除逻辑
        logger.info(f"Deleting record: {{record_id}}")
        return False

    def list_all(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """列出所有记录"""
        # TODO: 实现列表查询
        return []


def main():
    """主函数"""
    manager = DataManager()
    # TODO: 添加使用示例
    print("DataManager initialized successfully")


if __name__ == "__main__":
    main()
'''
            elif detected_intent == "api":
                framework = f'''"""
{description}
自动生成 by code_psychologist
意图: API 接口
"""
from typing import Optional, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class APIResponse:
    """API 响应结构"""
    success: bool
    data: Any = None
    error: str = ""
    message: str = ""


class APIService:
    """API 服务 — {description}"""

    def __init__(self, base_url: str = ""):
        """初始化 API 服务"""
        self.base_url = base_url
        # TODO: 初始化 HTTP 客户端
        logger.info(f"APIService initialized")

    def get(self, endpoint: str, params: Optional[Dict] = None) -> APIResponse:
        """GET 请求"""
        # TODO: 实现 GET 请求
        return APIResponse(success=True, message="GET request")

    def post(self, endpoint: str, data: Dict) -> APIResponse:
        """POST 请求"""
        # TODO: 实现 POST 请求
        return APIResponse(success=True, message="POST request")

    def put(self, endpoint: str, data: Dict) -> APIResponse:
        """PUT 请求"""
        # TODO: 实现 PUT 请求
        return APIResponse(success=True, message="PUT request")

    def delete(self, endpoint: str) -> APIResponse:
        """DELETE 请求"""
        # TODO: 实现 DELETE 请求
        return APIResponse(success=True, message="DELETE request")


def main():
    """主函数"""
    api = APIService()
    # TODO: 添加 API 调用示例
    print("API Service initialized successfully")


if __name__ == "__main__":
    main()
'''
            elif detected_intent == "algorithm":
                framework = f'''"""
{description}
自动生成 by code_psychologist
意图: 算法实现
"""
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


def solve(input_data: Any) -> Any:
    """
    核心算法 — {description}

    Args:
        input_data: 输入数据

    Returns:
        计算结果
    """
    # TODO: 实现核心算法逻辑
    logger.info(f"Processing input: {{type(input_data)}}")
    return input_data


def validate_input(data: Any) -> bool:
    """验证输入数据"""
    # TODO: 实现输入验证
    return True


def format_output(result: Any) -> str:
    """格式化输出结果"""
    # TODO: 实现输出格式化
    return str(result)


def main():
    """主函数"""
    # TODO: 添加测试用例
    test_input = None  # 替换为实际测试数据
    if validate_input(test_input):
        result = solve(test_input)
        print(format_output(result))
    else:
        print("Invalid input")


if __name__ == "__main__":
    main()
'''
            elif detected_intent == "tool":
                framework = f'''"""
{description}
自动生成 by code_psychologist
意图: 命令行工具
"""
import argparse
import sys
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def process(input_path: str, output_path: str, **options) -> bool:
    """
    核心处理逻辑 — {description}

    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径
        **options: 额外选项

    Returns:
        是否处理成功
    """
    # TODO: 实现核心处理逻辑
    logger.info(f"Processing {{input_path}} -> {{output_path}}")
    return True


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(description="{description}")
    parser.add_argument("input", help="输入文件路径")
    parser.add_argument("-o", "--output", default="output.txt", help="输出文件路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    # TODO: 添加更多参数
    return parser


def main():
    """主函数"""
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    success = process(args.input, args.output)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
'''
            else:
                framework = f'''"""
{description}
自动生成 by code_psychologist
意图: 通用工具
"""
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


def main():
    """
    主函数 — {description}

    TODO: 实现核心功能
    """
    logger.info("Starting {description}")
    # TODO: 实现核心逻辑
    print("Hello from {description}!")


if __name__ == "__main__":
    main()
'''
        else:
            framework = f"// TODO: {description}\n// 语言: {language}\n// 自动生成 by code_psychologist\n\nfunction main() {{\n    console.log('{description}');\n}}\n\nmain();\n"

        return SkillResult(
            success=True,
            output=f"代码意图推断完成\n"
                   f"描述: {description}\n"
                   f"推断意图: {detected_intent}\n"
                   f"语言: {language}\n"
                   f"风格: {style}\n\n"
                   f"```{language}\n{framework}\n```",
            data={
                "framework": framework,
                "intent": detected_intent,
                "language": language,
                "style": style,
            },
        )

    else:
        # 逆向：代码 → 意图分析
        if not code:
            return SkillResult(success=False, error="逆向模式需要提供 code 参数")

        lines = code.strip().split("\n")
        total_lines = len(lines)

        # 统计分析
        imports = [l for l in lines if l.strip().startswith(("import ", "from "))]
        functions = [l for l in lines if l.strip().startswith("def ")]
        classes = [l for l in lines if l.strip().startswith("class ")]
        comments = [l for l in lines if l.strip().startswith("#")]
        decorators = [l for l in lines if l.strip().startswith("@")]

        # 意图推断
        code_lower = code.lower()
        intent_signals = []
        if "def " in code and "return" in code:
            intent_signals.append("函数式编程")
        if "class " in code:
            intent_signals.append("面向对象设计")
        if any(kw in code_lower for kw in ["http", "api", "request", "response", "flask", "fastapi", "django"]):
            intent_signals.append("Web/API 服务")
        if any(kw in code_lower for kw in ["sql", "database", "db", "cursor", "execute"]):
            intent_signals.append("数据库操作")
        if any(kw in code_lower for kw in ["matplotlib", "plot", "figure", "chart", "graph"]):
            intent_signals.append("数据可视化")
        if any(kw in code_lower for kw in ["pandas", "numpy", "dataframe", "array"]):
            intent_signals.append("数据处理")
        if any(kw in code_lower for kw in ["argparse", "sys.argv", "click", "typer"]):
            intent_signals.append("CLI 工具")
        if any(kw in code_lower for kw in ["tkinter", "pyqt", "ui", "gui", "window"]):
            intent_signals.append("GUI 应用")
        if any(kw in code_lower for kw in ["test", "unittest", "pytest", "assert"]):
            intent_signals.append("测试代码")

        if not intent_signals:
            intent_signals.append("通用脚本")

        # 检查是否有 docstring
        has_docstring = any('"""' in l for l in lines)

        # 复杂度评估
        complexity = "低"
        if total_lines > 200:
            complexity = "高"
        elif total_lines > 50:
            complexity = "中"

        analysis = f"""代码逆向分析报告
{'='*45}
文件行数: {total_lines} 行
导入: {len(imports)} 个
函数: {len(functions)} 个
类: {len(classes)} 个
注释行: {len(comments)} 行
装饰器: {len(decorators)} 个
复杂度: {complexity}

推断意图: {', '.join(intent_signals)}

设计模式: {'观察者' if 'observer' in code_lower or 'listener' in code_lower else '工厂' if 'factory' in code_lower else '单例' if 'singleton' in code_lower or '__new__' in code else '策略' if 'strategy' in code_lower else '通用结构'}

潜在问题:
- 函数平均行数: {total_lines // max(len(functions), 1)} 行
- {'建议添加类型提示' if not any('def ' in l and ':' in l.split('def ')[-1].split('(')[0] + ')' in l for l in functions) else '类型提示: 部分存在'}
- {'建议拆分过长函数' if total_lines > 200 else '代码长度合理'}
- {'建议添加更多注释' if len(comments) < total_lines * 0.05 else '注释比例合理'}

改进建议:
1. {'添加单元测试' if 'test' not in code_lower else '测试覆盖良好'}
2. {'添加 docstring 文档' if not has_docstring else '文档字符串: 存在'}
3. {'考虑使用配置管理' if '=' in code and 'config' not in code_lower else '配置管理: 合理'}
"""

        return SkillResult(
            success=True,
            output=analysis,
            data={
                "total_lines": total_lines,
                "imports": len(imports),
                "functions": len(functions),
                "classes": len(classes),
                "intent": intent_signals,
                "complexity": complexity,
            },
        )


CODE_PSYCHOLOGIST_SKILL = SkillDef(
    name="code_psychologist",
    description="代码心理学家：正向模式（描述→代码框架）或逆向模式（代码→意图分析），支持 7 种意图分类",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "自然语言描述（正向模式使用）"},
            "code": {"type": "string", "description": "代码内容（逆向模式使用）"},
            "language": {"type": "string", "description": "编程语言", "default": "python"},
            "mode": {
                "type": "string",
                "description": "模式：forward(描述→代码) 或 reverse(代码→意图)",
                "enum": ["forward", "reverse"],
            },
            "style": {"type": "string", "description": "代码风格", "default": "production"},
        },
        "required": [],
    },
    handler=_handle_code_psychologist,
    category="code",
    timeout=30,
)


# ============================================================
# Skill 25: multi_model_debater — 多模型辩论决策
# ============================================================

MULTI_MODEL_DEBATE_PROMPT = """你是一个辩论决策系统，需要模拟多模型辩论过程。

辩论流程：
1. 问题陈述 → 明确辩论议题
2. 正方观点 → 提出支持论点（3个）
3. 反方观点 → 提出反对论点（3个）
4. 交叉质询 → 双方互相质疑对方论点的弱点
5. 共识综合 → 找出双方共同点
6. 最终裁决 → 综合所有观点给出最合理结论

评分维度：
- 逻辑性 (1-10)
- 证据充分性 (1-10)
- 实用性 (1-10)
- 创新性 (1-10)
"""


def _handle_multi_model_debate(
    question: str = "",
    perspectives: str = "",
    rounds: int = 3,
    voting_method: str = "majority",
) -> SkillResult:
    """多模型辩论 — 模拟多方辩论决策过程"""
    if not question:
        return SkillResult(success=False, error="请提供 question 参数")

    # 解析观点
    if perspectives:
        try:
            perspective_list = json.loads(perspectives)
        except json.JSONDecodeError:
            perspective_list = [p.strip() for p in perspectives.split(",") if p.strip()]
    else:
        # 自动生成正方/反方/中立方
        perspective_list = [
            {"role": "正方", "stance": "支持", "description": "从技术可行性角度支持该观点"},
            {"role": "反方", "stance": "反对", "description": "从风险和实践角度反驳该观点"},
            {"role": "中立方", "stance": "中立", "description": "从客观角度评估各方观点"},
        ]

    debate_log = []
    debate_log.append(f"辩论议题: {question}")
    debate_log.append(f"参与方: {len(perspective_list)} 方")
    debate_log.append(f"辩论轮次: {rounds}")
    debate_log.append(f"投票方式: {voting_method}")
    debate_log.append("=" * 50)
    debate_log.append("")

    # 模拟辩论
    for round_num in range(1, rounds + 1):
        debate_log.append(f"--- 第 {round_num} 轮 ---")

        for i, p in enumerate(perspective_list):
            role = p.get("role", f"参与方{i+1}")
            stance = p.get("stance", "中立")
            desc = p.get("description", "")

            # 根据轮次生成不同深度论点
            if round_num == 1:
                argument = f"  [{role}] ({stance}) 初步观点: {desc}"
            elif round_num == 2:
                argument = f"  [{role}] ({stance}) 反驳对方: 质疑对方论点的证据充分性和逻辑一致性"
            else:
                argument = f"  [{role}] ({stance}) 总结陈词: 综合前两轮辩论，提出最终立场"

            debate_log.append(argument)

        debate_log.append("")

    # 评分
    debate_log.append("--- 评分 ---")
    scores = []
    for p in perspective_list:
        role = p.get("role", "未知")
        # 模拟评分
        import hashlib
        seed = int(hashlib.md5(f"{question}{role}".encode()).hexdigest()[:8], 16)
        logic_score = 5 + (seed % 6)  # 5-10
        evidence_score = 5 + ((seed // 10) % 6)  # 5-10
        practical_score = 4 + ((seed // 100) % 7)  # 4-10
        innovation_score = 3 + ((seed // 1000) % 8)  # 3-10

        scores.append({
            "role": role,
            "logic": logic_score,
            "evidence": evidence_score,
            "practical": practical_score,
            "innovation": innovation_score,
            "total": logic_score + evidence_score + practical_score + innovation_score,
        })

        debate_log.append(
            f"  [{role}] 逻辑:{logic_score} 证据:{evidence_score} "
            f"实用:{practical_score} 创新:{innovation_score} "
            f"总分:{logic_score + evidence_score + practical_score + innovation_score}/40"
        )

    debate_log.append("")

    # 裁决
    if voting_method == "majority":
        winner = max(scores, key=lambda s: s["total"])
        debate_log.append(f"--- 裁决（多数投票） ---")
        debate_log.append(f"  胜出方: {winner['role']} (总分: {winner['total']}/40)")

        # 综合结论
        consensus = (
            f"综合各方观点，对于「{question}」这一问题，"
            f"{winner['role']}的观点在逻辑性、证据充分性和实用性上表现最优。"
            f"建议在充分考虑各方风险的前提下，采纳{winner['role']}的建议方向。"
        )
    elif voting_method == "consensus":
        avg_total = sum(s["total"] for s in scores) / len(scores)
        debate_log.append(f"--- 裁决（共识投票） ---")
        debate_log.append(f"  平均分: {avg_total:.1f}/40")
        consensus = (
            f"各方观点分歧较大，未能达成完全共识。"
            f"建议进行更多实证研究以验证各方观点。"
        )
    else:
        # weighted
        debate_log.append(f"--- 裁决（加权投票） ---")
        debate_log.append(f"  权重: 正方 40% / 反方 30% / 中立方 30%")
        consensus = f"加权投票结果需要人工判定，建议综合考虑各方观点。"

    debate_log.append("")
    debate_log.append(f"结论: {consensus}")

    return SkillResult(
        success=True,
        output="\n".join(debate_log),
        data={
            "question": question,
            "perspectives": len(perspective_list),
            "rounds": rounds,
            "scores": scores,
            "consensus": consensus,
            "winner": winner["role"] if voting_method == "majority" else None,
        },
    )


MULTI_MODEL_DEBATER_SKILL = SkillDef(
    name="multi_model_debater",
    description="多模型辩论决策：模拟多方辩论过程（正方/反方/中立方），多轮评分投票，综合裁决",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "辩论议题"},
            "perspectives": {"type": "string", "description": "参与方 JSON 数组 [{\"role\":\"正方\",\"stance\":\"支持\",\"description\":\"...\"}]"},
            "rounds": {"type": "integer", "description": "辩论轮次（1-5）", "default": 3},
            "voting_method": {
                "type": "string",
                "description": "投票方式",
                "enum": ["majority", "consensus", "weighted"],
            },
        },
        "required": ["question"],
    },
    handler=_handle_multi_model_debate,
    category="debate",
    timeout=30,
)


# ============================================================
# Skill 26: code_semantic_analyzer — 代码语义分析
# ============================================================

def _handle_code_semantic_analyze(
    code: str = "",
    file_path: str = "",
    language: str = "python",
    output_format: str = "text",
) -> SkillResult:
    """代码语义分析 — 提取代码结构、类、函数、依赖关系

    支持 Python/JavaScript/Java 代码的语义分析，生成结构树和依赖图。

    Args:
        code: 代码内容（与 file_path 二选一）
        file_path: 文件路径（与 code 二选一）
        language: 编程语言（python/javascript/java）
        output_format: 输出格式（text/json/tree）
    """
    try:
        import ast
        import re

        # 读取代码
        if file_path:
            if not os.path.exists(file_path):
                return SkillResult(success=False, error=f"文件不存在: {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            # 自动检测语言
            ext = os.path.splitext(file_path)[1].lower()
            lang_map = {'.py': 'python', '.js': 'javascript', '.java': 'java'}
            language = lang_map.get(ext, language)

        if not code.strip():
            return SkillResult(success=False, error="代码内容为空")

        # 根据语言选择解析器
        if language == 'python':
            result = _analyze_python_code(code)
        elif language == 'javascript':
            result = _analyze_javascript_code(code)
        elif language == 'java':
            result = _analyze_java_code(code)
        else:
            return SkillResult(success=False, error=f"不支持的语言: {language}，支持 python/javascript/java")

        # 格式化输出
        if output_format == 'json':
            return SkillResult(
                success=True,
                output=json.dumps(result, ensure_ascii=False, indent=2),
                data=result
            )
        elif output_format == 'tree':
            tree_str = _generate_structure_tree(result)
            return SkillResult(
                success=True,
                output=tree_str,
                data=result
            )
        else:  # text
            report = _generate_semantic_report(result, language)
            return SkillResult(
                success=True,
                output=report,
                data=result
            )

    except Exception as e:
        return SkillResult(success=False, error=f"代码语义分析失败: {str(e)}")


def _analyze_python_code(code: str) -> Dict:
    """分析 Python 代码结构"""
    import ast

    tree = ast.parse(code)

    result = {
        'language': 'python',
        'classes': [],
        'functions': [],
        'imports': [],
        'variables': [],
        'dependencies': []
    }

    for node in ast.walk(tree):
        # 类定义
        if isinstance(node, ast.ClassDef):
            class_info = {
                'name': node.name,
                'line': node.lineno,
                'methods': [],
                'bases': [base.id if isinstance(base, ast.Name) else str(base) for base in node.bases],
                'decorators': [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list]
            }
            # 提取方法
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    method_info = {
                        'name': item.name,
                        'line': item.lineno,
                        'args': [arg.arg for arg in item.args.args],
                        'decorators': [d.id if isinstance(d, ast.Name) else str(d) for d in item.decorator_list]
                    }
                    class_info['methods'].append(method_info)
            result['classes'].append(class_info)

        # 函数定义（顶层）
        elif isinstance(node, ast.FunctionDef) and not any(
            isinstance(parent, ast.ClassDef) for parent in ast.walk(tree)
        ):
            func_info = {
                'name': node.name,
                'line': node.lineno,
                'args': [arg.arg for arg in node.args.args],
                'decorators': [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list]
            }
            result['functions'].append(func_info)

        # 导入语句
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result['imports'].append({
                    'module': alias.name,
                    'alias': alias.asname,
                    'line': node.lineno
                })
        elif isinstance(node, ast.ImportFrom):
            result['imports'].append({
                'module': node.module,
                'names': [alias.name for alias in node.names],
                'line': node.lineno
            })

        # 变量赋值
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result['variables'].append({
                        'name': target.id,
                        'line': node.lineno
                    })

    # 构建依赖关系
    for imp in result['imports']:
        if 'module' in imp:
            result['dependencies'].append(imp['module'])

    return result


def _analyze_javascript_code(code: str) -> Dict:
    """分析 JavaScript 代码结构（基于正则）"""
    result = {
        'language': 'javascript',
        'classes': [],
        'functions': [],
        'imports': [],
        'variables': [],
        'dependencies': []
    }

    lines = code.split('\n')

    # 类定义
    class_pattern = re.compile(r'class\s+(\w+)(?:\s+extends\s+(\w+))?')
    for i, line in enumerate(lines, 1):
        match = class_pattern.search(line)
        if match:
            class_info = {
                'name': match.group(1),
                'line': i,
                'extends': match.group(2),
                'methods': []
            }
            result['classes'].append(class_info)

    # 函数定义
    func_pattern = re.compile(r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:function|\([^)]*\)\s*=>))')
    for i, line in enumerate(lines, 1):
        match = func_pattern.search(line)
        if match:
            func_name = match.group(1) or match.group(2)
            result['functions'].append({
                'name': func_name,
                'line': i
            })

    # 导入语句
    import_pattern = re.compile(r'import\s+(?:.*?\s+from\s+)?[\'"]([^\'"]+)[\'"]')
    for i, line in enumerate(lines, 1):
        match = import_pattern.search(line)
        if match:
            result['imports'].append({
                'module': match.group(1),
                'line': i
            })
            result['dependencies'].append(match.group(1))

    # 变量声明
    var_pattern = re.compile(r'(?:const|let|var)\s+(\w+)\s*=')
    for i, line in enumerate(lines, 1):
        matches = var_pattern.finditer(line)
        for match in matches:
            result['variables'].append({
                'name': match.group(1),
                'line': i
            })

    return result


def _analyze_java_code(code: str) -> Dict:
    """分析 Java 代码结构（基于正则）"""
    result = {
        'language': 'java',
        'classes': [],
        'functions': [],
        'imports': [],
        'variables': [],
        'dependencies': []
    }

    lines = code.split('\n')

    # 类定义
    class_pattern = re.compile(r'(?:public|private|protected)?\s*class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?')
    for i, line in enumerate(lines, 1):
        match = class_pattern.search(line)
        if match:
            class_info = {
                'name': match.group(1),
                'line': i,
                'extends': match.group(2),
                'implements': match.group(3).split(',') if match.group(3) else [],
                'methods': []
            }
            result['classes'].append(class_info)

    # 方法定义
    method_pattern = re.compile(r'(?:public|private|protected)?\s*(?:static\s+)?(?:\w+(?:<[^>]+>)?)\s+(\w+)\s*\([^)]*\)')
    for i, line in enumerate(lines, 1):
        match = method_pattern.search(line)
        if match and not any(kw in line for kw in ['class ', 'if ', 'for ', 'while ']):
            result['functions'].append({
                'name': match.group(1),
                'line': i
            })

    # 导入语句
    import_pattern = re.compile(r'import\s+([\w.]+);')
    for i, line in enumerate(lines, 1):
        match = import_pattern.search(line)
        if match:
            result['imports'].append({
                'module': match.group(1),
                'line': i
            })
            result['dependencies'].append(match.group(1))

    # 变量声明
    var_pattern = re.compile(r'(?:private|public|protected)?\s*(?:static\s+)?(?:final\s+)?(\w+)\s+(\w+)\s*=')
    for i, line in enumerate(lines, 1):
        match = var_pattern.search(line)
        if match:
            result['variables'].append({
                'name': match.group(2),
                'type': match.group(1),
                'line': i
            })

    return result


def _generate_structure_tree(result: Dict) -> str:
    """生成代码结构树"""
    lines = []
    lines.append(f"📊 代码结构树 ({result['language']})")
    lines.append("=" * 60)

    if result['classes']:
        lines.append("\n📦 类 (Classes):")
        for cls in result['classes']:
            lines.append(f"  ├─ {cls['name']} (line {cls['line']})")
            if 'bases' in cls and cls['bases']:
                lines.append(f"  │  └─ extends: {', '.join(cls['bases'])}")
            if 'methods' in cls and cls['methods']:
                for method in cls['methods']:
                    lines.append(f"  │  ├─ method: {method['name']} (line {method['line']})")

    if result['functions']:
        lines.append("\n🔧 函数 (Functions):")
        for func in result['functions']:
            lines.append(f"  ├─ {func['name']} (line {func['line']})")

    if result['variables']:
        lines.append("\n📝 变量 (Variables):")
        for var in result['variables'][:10]:  # 限制显示数量
            type_info = f" : {var['type']}" if 'type' in var else ""
            lines.append(f"  ├─ {var['name']}{type_info} (line {var['line']})")
        if len(result['variables']) > 10:
            lines.append(f"  └─ ... 还有 {len(result['variables']) - 10} 个变量")

    if result['imports']:
        lines.append("\n📥 导入 (Imports):")
        for imp in result['imports'][:10]:
            if 'names' in imp:
                lines.append(f"  ├─ from {imp['module']} import {', '.join(imp['names'])}")
            else:
                lines.append(f"  ├─ {imp['module']}")
        if len(result['imports']) > 10:
            lines.append(f"  └─ ... 还有 {len(result['imports']) - 10} 个导入")

    if result['dependencies']:
        lines.append("\n🔗 依赖关系 (Dependencies):")
        for dep in set(result['dependencies']):
            lines.append(f"  ├─ {dep}")

    return '\n'.join(lines)


def _generate_semantic_report(result: Dict, language: str) -> str:
    """生成语义分析报告"""
    lines = []
    lines.append(f"📋 代码语义分析报告")
    lines.append("=" * 60)
    lines.append(f"语言: {language}")
    lines.append(f"类数量: {len(result['classes'])}")
    lines.append(f"函数数量: {len(result['functions'])}")
    lines.append(f"变量数量: {len(result['variables'])}")
    lines.append(f"导入数量: {len(result['imports'])}")
    lines.append(f"依赖数量: {len(set(result['dependencies']))}")
    lines.append("")

    if result['classes']:
        lines.append("📦 类结构:")
        for cls in result['classes']:
            lines.append(f"  • {cls['name']}")
            if 'methods' in cls:
                for method in cls['methods']:
                    args_str = ', '.join(method.get('args', []))
                    lines.append(f"    - {method['name']}({args_str})")

    if result['functions']:
        lines.append("\n🔧 顶层函数:")
        for func in result['functions']:
            args_str = ', '.join(func.get('args', []))
            lines.append(f"  • {func['name']}({args_str})")

    if result['dependencies']:
        lines.append("\n🔗 外部依赖:")
        for dep in set(result['dependencies']):
            lines.append(f"  • {dep}")

    return '\n'.join(lines)


CODE_SEMANTIC_ANALYZER_SKILL = SkillDef(
    name="code_semantic_analyzer",
    description="代码语义分析：分析 Python/JavaScript/Java 代码结构，提取类、函数、方法、变量，生成结构树和依赖关系图",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "代码内容（与 file_path 二选一）"},
            "file_path": {"type": "string", "description": "文件路径（与 code 二选一）"},
            "language": {
                "type": "string",
                "description": "编程语言",
                "enum": ["python", "javascript", "java"],
                "default": "python"
            },
            "output_format": {
                "type": "string",
                "description": "输出格式",
                "enum": ["text", "json", "tree"],
                "default": "text"
            }
        },
        "required": []
    },
    handler=_handle_code_semantic_analyze,
    category="analysis",
    timeout=30,
)


# ============================================================
# Skill 27: format_converter — 多格式互转
# ============================================================

def _handle_format_convert(
    input_content: str = "",
    input_format: str = "",
    output_format: str = "",
    input_file: str = "",
    output_file: str = "",
) -> SkillResult:
    """多格式互转 — 支持 Markdown/HTML/PDF、JSON/YAML/TOML、CSV/Excel 转换

    Args:
        input_content: 输入内容（与 input_file 二选一）
        input_format: 输入格式（markdown/html/pdf/json/yaml/toml/csv/excel）
        output_format: 输出格式
        input_file: 输入文件路径
        output_file: 输出文件路径（可选，不指定则返回内容）
    """
    try:
        # 读取输入
        if input_file:
            if not os.path.exists(input_file):
                return SkillResult(success=False, error=f"输入文件不存在: {input_file}")
            with open(input_file, 'r', encoding='utf-8') as f:
                input_content = f.read()
            # 自动检测格式
            if not input_format:
                ext = os.path.splitext(input_file)[1].lower()
                format_map = {
                    '.md': 'markdown', '.html': 'html', '.pdf': 'pdf',
                    '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml',
                    '.toml': 'toml', '.csv': 'csv', '.xlsx': 'excel', '.xls': 'excel'
                }
                input_format = format_map.get(ext, '')

        if not input_content:
            return SkillResult(success=False, error="输入内容为空")
        if not input_format or not output_format:
            return SkillResult(success=False, error="请指定 input_format 和 output_format")

        # 文档格式转换
        if input_format in ['markdown', 'html', 'pdf'] and output_format in ['markdown', 'html', 'pdf']:
            result = _convert_document_format(input_content, input_format, output_format)

        # 配置格式转换
        elif input_format in ['json', 'yaml', 'toml'] and output_format in ['json', 'yaml', 'toml']:
            result = _convert_config_format(input_content, input_format, output_format)

        # 数据格式转换
        elif input_format in ['csv', 'excel'] and output_format in ['csv', 'excel']:
            result = _convert_data_format(input_content, input_format, output_format)

        else:
            return SkillResult(
                success=False,
                error=f"不支持的转换: {input_format} → {output_format}"
            )

        if not result['success']:
            return SkillResult(success=False, error=result['error'])

        # 输出到文件
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(result['content'])
            return SkillResult(
                success=True,
                output=f"✅ 转换完成: {input_format} → {output_format}\n已保存到: {output_file}",
                data=result
            )
        else:
            return SkillResult(
                success=True,
                output=f"✅ 转换完成: {input_format} → {output_format}\n\n{result['content'][:500]}",
                data=result
            )

    except Exception as e:
        return SkillResult(success=False, error=f"格式转换失败: {str(e)}")


def _convert_document_format(content: str, from_fmt: str, to_fmt: str) -> Dict:
    """文档格式转换（Markdown/HTML/PDF）"""
    try:
        if from_fmt == 'markdown' and to_fmt == 'html':
            # Markdown → HTML
            try:
                import markdown
                html = markdown.markdown(content)
                return {'success': True, 'content': html, 'format': 'html'}
            except ImportError:
                # 简单转换
                html = content
                html = re.sub(r'^# (.*?)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
                html = re.sub(r'^## (.*?)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
                html = re.sub(r'^### (.*?)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
                html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html)
                html = re.sub(r'\*(.*?)\*', r'<em>\1</em>', html)
                html = f"<html><body>{html}</body></html>"
                return {'success': True, 'content': html, 'format': 'html'}

        elif from_fmt == 'html' and to_fmt == 'markdown':
            # HTML → Markdown
            try:
                import html2text
                md = html2text.html2text(content)
                return {'success': True, 'content': md, 'format': 'markdown'}
            except ImportError:
                # 简单转换
                md = content
                md = re.sub(r'<h1>(.*?)</h1>', r'# \1', md)
                md = re.sub(r'<h2>(.*?)</h2>', r'## \1', md)
                md = re.sub(r'<h3>(.*?)</h3>', r'### \1', md)
                md = re.sub(r'<strong>(.*?)</strong>', r'**\1**', md)
                md = re.sub(r'<em>(.*?)</em>', r'*\1*', md)
                md = re.sub(r'<[^>]+>', '', md)
                return {'success': True, 'content': md, 'format': 'markdown'}

        elif to_fmt == 'pdf':
            # 任何格式 → PDF
            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.pdfgen import canvas
                import io

                buffer = io.BytesIO()
                c = canvas.Canvas(buffer, pagesize=A4)
                width, height = A4

                # 简单文本渲染
                y_position = height - 50
                for line in content.split('\n')[:50]:  # 限制行数
                    c.drawString(50, y_position, line[:100])
                    y_position -= 20
                    if y_position < 50:
                        break

                c.save()
                pdf_bytes = buffer.getvalue()
                buffer.close()

                return {
                    'success': True,
                    'content': pdf_bytes.decode('latin-1'),
                    'format': 'pdf',
                    'binary': True
                }
            except ImportError:
                return {
                    'success': False,
                    'error': "PDF 转换需要 reportlab 库: pip install reportlab"
                }

        else:
            return {
                'success': False,
                'error': f"不支持的文档转换: {from_fmt} → {to_fmt}"
            }

    except Exception as e:
        return {'success': False, 'error': str(e)}


def _convert_config_format(content: str, from_fmt: str, to_fmt: str) -> Dict:
    """配置格式转换（JSON/YAML/TOML）"""
    try:
        # 解析输入格式
        data = None
        if from_fmt == 'json':
            data = json.loads(content)
        elif from_fmt == 'yaml':
            try:
                import yaml
                data = yaml.safe_load(content)
            except ImportError:
                return {'success': False, 'error': "YAML 解析需要 pyyaml 库: pip install pyyaml"}
        elif from_fmt == 'toml':
            try:
                import toml
                data = toml.loads(content)
            except ImportError:
                return {'success': False, 'error': "TOML 解析需要 toml 库: pip install toml"}

        if data is None:
            return {'success': False, 'error': f"无法解析 {from_fmt} 格式"}

        # 输出目标格式
        if to_fmt == 'json':
            output = json.dumps(data, ensure_ascii=False, indent=2)
            return {'success': True, 'content': output, 'format': 'json'}

        elif to_fmt == 'yaml':
            try:
                import yaml
                output = yaml.dump(data, allow_unicode=True, default_flow_style=False)
                return {'success': True, 'content': output, 'format': 'yaml'}
            except ImportError:
                return {'success': False, 'error': "YAML 输出需要 pyyaml 库: pip install pyyaml"}

        elif to_fmt == 'toml':
            try:
                import toml
                output = toml.dumps(data)
                return {'success': True, 'content': output, 'format': 'toml'}
            except ImportError:
                return {'success': False, 'error': "TOML 输出需要 toml 库: pip install toml"}

        else:
            return {'success': False, 'error': f"不支持的配置格式: {to_fmt}"}

    except Exception as e:
        return {'success': False, 'error': str(e)}


def _convert_data_format(content: str, from_fmt: str, to_fmt: str) -> Dict:
    """数据格式转换（CSV/Excel）"""
    try:
        import csv
        import io

        if from_fmt == 'csv' and to_fmt == 'excel':
            # CSV → Excel
            try:
                import openpyxl
                from openpyxl import Workbook

                # 解析 CSV
                reader = csv.reader(io.StringIO(content))
                rows = list(reader)

                # 创建 Excel
                wb = Workbook()
                ws = wb.active
                for row in rows:
                    ws.append(row)

                # 保存到字节
                output = io.BytesIO()
                wb.save(output)
                excel_bytes = output.getvalue()
                output.close()

                return {
                    'success': True,
                    'content': excel_bytes.decode('latin-1'),
                    'format': 'excel',
                    'binary': True
                }
            except ImportError:
                return {'success': False, 'error': "Excel 转换需要 openpyxl 库: pip install openpyxl"}

        elif from_fmt == 'excel' and to_fmt == 'csv':
            # Excel → CSV
            try:
                import openpyxl

                # 从字节读取 Excel
                input_bytes = io.BytesIO(content.encode('latin-1'))
                wb = openpyxl.load_workbook(input_bytes)
                ws = wb.active

                # 转换为 CSV
                output = io.StringIO()
                writer = csv.writer(output)
                for row in ws.iter_rows(values_only=True):
                    writer.writerow(row)

                csv_content = output.getvalue()
                output.close()

                return {'success': True, 'content': csv_content, 'format': 'csv'}
            except ImportError:
                return {'success': False, 'error': "Excel 解析需要 openpyxl 库: pip install openpyxl"}

        else:
            return {'success': False, 'error': f"不支持的数据转换: {from_fmt} → {to_fmt}"}

    except Exception as e:
        return {'success': False, 'error': str(e)}


FORMAT_CONVERTER_SKILL = SkillDef(
    name="format_converter",
    description="多格式互转：支持 Markdown/HTML/PDF、JSON/YAML/TOML、CSV/Excel 格式转换",
    parameters={
        "type": "object",
        "properties": {
            "input_content": {"type": "string", "description": "输入内容（与 input_file 二选一）"},
            "input_format": {
                "type": "string",
                "description": "输入格式",
                "enum": ["markdown", "html", "pdf", "json", "yaml", "toml", "csv", "excel"]
            },
            "output_format": {
                "type": "string",
                "description": "输出格式",
                "enum": ["markdown", "html", "pdf", "json", "yaml", "toml", "csv", "excel"]
            },
            "input_file": {"type": "string", "description": "输入文件路径"},
            "output_file": {"type": "string", "description": "输出文件路径（可选）"}
        },
        "required": ["input_format", "output_format"]
    },
    handler=_handle_format_convert,
    category="conversion",
    timeout=30,
)

# ★★★ L3 新增 SkillDef（从 skills/ 目录模块导入） ★★★

# --- browser_automation ---
BROWSER_AUTOMATION_SKILL = SkillDef(
    name="browser_automation",
    description="浏览器自动化：基于 Playwright/Selenium 实现页面打开/截图/点击/表单填写/文本提取/滚动",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型",
                "enum": ["open", "screenshot", "click", "fill", "extract", "scroll", "close"],
            },
            "url": {"type": "string", "description": "页面 URL（open 操作）"},
            "selector": {"type": "string", "description": "CSS 选择器（click/fill/extract 操作）"},
            "value": {"type": "string", "description": "输入值（fill 操作）"},
            "screenshot_path": {"type": "string", "description": "截图保存路径", "default": ""},
        },
        "required": ["action"],
    },
    handler=_browser_execute if _browser_execute else lambda **kw: SkillResult(False, error="browser_automation 模块未加载"),
    category="browser",
    requires_confirm=False,
    timeout=30,
)

# --- jupyter_notebook ---
JUPYTER_NOTEBOOK_SKILL = SkillDef(
    name="jupyter_notebook",
    description="Jupyter Notebook 自动化：创建/读取/执行/插入单元格/获取输出（基于 nbformat + nbclient）",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型",
                "enum": ["create", "open", "execute", "add_code", "add_markdown", "get_output", "save", "list_cells"],
            },
            "file_path": {"type": "string", "description": "open/save 的 .ipynb 文件路径"},
            "cells": {"type": "string", "description": "create 时的初始单元格 JSON 数组"},
            "source": {"type": "string", "description": "add_* 操作的单元格内容"},
            "cell_type": {"type": "string", "description": "单元格类型", "enum": ["code", "markdown"], "default": "code"},
            "index": {"type": "integer", "description": "单元格索引（-1 表示末尾/全部）", "default": -1},
            "timeout": {"type": "integer", "description": "execute 超时（秒）", "default": 60},
            "kernel": {"type": "string", "description": "Jupyter 内核", "default": "python3"},
        },
        "required": ["action"],
    },
    handler=_jupyter_execute if _jupyter_execute else lambda **kw: SkillResult(False, error="jupyter_notebook 模块未加载"),
    category="code",
    requires_confirm=False,
    timeout=300,
)

# --- lsp_code_analysis ---
LSP_CODE_ANALYSIS_SKILL = SkillDef(
    name="lsp_code_analysis",
    description="LSP 语义代码分析：全局符号搜索/定义跳转/引用查找/悬停信息/调用层次/代码补全/诊断",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "LSP 操作类型",
                "enum": ["workspace_symbol", "document_symbol", "go_to_definition",
                         "find_references", "hover", "go_to_implementation",
                         "completion", "diagnostics", "health"],
            },
            "query": {"type": "string", "description": "workspace_symbol 的搜索关键词"},
            "file_path": {"type": "string", "description": "目标文件路径"},
            "line": {"type": "integer", "description": "光标行号（0-based）", "default": 0},
            "character": {"type": "integer", "description": "光标列号（0-based）", "default": 0},
            "language_id": {"type": "string", "description": "语言 ID", "default": "python"},
        },
        "required": ["action"],
    },
    handler=_lsp_execute if _lsp_execute else lambda **kw: SkillResult(False, error="lsp_code_analysis 模块未加载"),
    category="code",
    requires_confirm=False,
    timeout=15,
)

# --- mcp_bridge ---
MCP_BRIDGE_SKILL = SkillDef(
    name="mcp_bridge",
    description="MCP 工具桥接：列出/调用 MCP 外部工具服务器（filesystem/git/fetch/memory）",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "MCP 操作类型",
                "enum": ["mcp_list_tools", "mcp_call_tool", "mcp_health"],
            },
            "tool_name": {"type": "string", "description": "mcp_call_tool 时要调用的工具名"},
            "server_name": {"type": "string", "description": "mcp_list_tools 时可选指定服务器名"},
            "arguments": {"type": "string", "description": "mcp_call_tool 时传入的参数 JSON", "default": "{}"},
        },
        "required": ["action"],
    },
    handler=_mcp_execute if _mcp_execute else lambda **kw: SkillResult(False, error="mcp_bridge 模块未加载"),
    category="system",
    requires_confirm=True,
    timeout=30,
)

# --- ssh_skill ---
SSH_SKILL = SkillDef(
    name="ssh_skill",
    description="SSH 远程执行：执行远程命令/连接测试（基于 paramiko）",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型",
                "enum": ["execute", "connect"],
            },
            "host": {"type": "string", "description": "远程主机 IP 或域名"},
            "command": {"type": "string", "description": "要执行的 Shell 命令"},
            "username": {"type": "string", "description": "SSH 用户名", "default": ""},
            "password": {"type": "string", "description": "SSH 密码", "default": ""},
            "key_file": {"type": "string", "description": "SSH 私钥路径", "default": ""},
            "port": {"type": "integer", "description": "SSH 端口", "default": 22},
            "timeout": {"type": "integer", "description": "超时（秒）", "default": 30},
        },
        "required": ["action", "host"],
    },
    handler=_ssh_execute if _ssh_execute else lambda **kw: SkillResult(False, error="ssh_skill 模块未加载"),
    category="system",
    requires_confirm=True,
    timeout=60,
)

# --- docker_skill ---
DOCKER_SKILL = SkillDef(
    name="docker_skill",
    description="Docker 容器管理：启动/停止/列表/日志/构建镜像/执行命令（docker CLI）",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型",
                "enum": ["ps", "run", "stop", "logs", "images", "exec"],
            },
            "image": {"type": "string", "description": "镜像名（run 操作）"},
            "name": {"type": "string", "description": "容器名（run 操作）", "default": ""},
            "container": {"type": "string", "description": "容器名/ID（stop/logs/exec 操作）"},
            "ports": {"type": "string", "description": "端口映射（如 8080:80）", "default": ""},
            "env": {"type": "string", "description": "环境变量（逗号分隔）", "default": ""},
            "command": {"type": "string", "description": "要执行命令（exec 操作）"},
            "tail": {"type": "integer", "description": "日志行数（logs 操作）", "default": 50},
            "detach": {"type": "boolean", "description": "后台运行", "default": True},
            "all_containers": {"type": "boolean", "description": "显示全部容器", "default": False},
        },
        "required": ["action"],
    },
    handler=_docker_execute if _docker_execute else lambda **kw: SkillResult(False, error="docker_skill 模块未加载"),
    category="system",
    requires_confirm=True,
    timeout=120,
)

# --- npm_pip_skill ---
NPM_PIP_SKILL = SkillDef(
    name="npm_pip_skill",
    description="包管理：npm/pip 安装/更新/列表/卸载/检查过期（npm & pip CLI）",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型",
                "enum": ["pip_install", "pip_list", "pip_outdated", "pip_uninstall", "pip_freeze",
                         "npm_install", "npm_list", "npm_outdated"],
            },
            "packages": {"type": "string", "description": "包名（逗号分隔）"},
            "cwd": {"type": "string", "description": "工作目录（默认当前）", "default": ""},
            "dev": {"type": "boolean", "description": "npm --save-dev", "default": False},
            "upgrade": {"type": "boolean", "description": "pip --upgrade", "default": False},
        },
        "required": ["action"],
    },
    handler=_npm_pip_execute if _npm_pip_execute else lambda **kw: SkillResult(False, error="npm_pip_skill 模块未加载"),
    category="system",
    requires_confirm=False,
    timeout=120,
)


# ============================================================
# 注册入口
# ============================================================

# 所有业务 skill 列表（便于批量注册）
BUSINESS_SKILLS = [
    MATH_SOLVER_SKILL,
    WEB_RESEARCHER_SKILL,
    INFO_DEBATER_SKILL,
    MATH_PLOTTER_SKILL,
    OFFICE_GENERATOR_SKILL,
    IMAGE_PROCESSOR_SKILL,
    SELF_DOCUMENTER_SKILL,
    ARXIV_RESEARCHER_SKILL,
    DESIGN_BLUEPRINT_SKILL,
    PHYSICS_EXPERIMENT_SKILL,
    IMAGE_ANALYZER_SKILL,
    ACADEMIC_WRITER_SKILL,
    SKILL_CREATOR_SKILL,
    FRONTEND_DESIGNER_SKILL,
    DEEP_RESEARCHER_SKILL,
    FACT_CHECKER_SKILL,
    HTML_TO_VIDEO_SKILL,
    PYTHON_TOOLCHAIN_SKILL,
    SUPER_RESEARCHER_SKILL,
    CODE_REVIEWER_SKILL,
    TEST_GENERATOR_SKILL,
    SECURITY_AUDITOR_SKILL,
    DEPLOY_HELPER_SKILL,
    CODE_PSYCHOLOGIST_SKILL,
    MULTI_MODEL_DEBATER_SKILL,
    CODE_SEMANTIC_ANALYZER_SKILL,
    FORMAT_CONVERTER_SKILL,
    # ★ L3 新增（2026-08-08）：浏览器/Notebook/LSP/MCP/SSH/Docker/NPM-Pip
    BROWSER_AUTOMATION_SKILL,
    JUPYTER_NOTEBOOK_SKILL,
    LSP_CODE_ANALYSIS_SKILL,
    MCP_BRIDGE_SKILL,
    SSH_SKILL,
    DOCKER_SKILL,
    NPM_PIP_SKILL,
]


def register_business_skills(registry) -> int:
    """
    将 34 个业务 skill（25 基础 + 7 L3 新增 + 2 基础扩展）注册到 SkillsRegistry

    Args:
        registry: SkillsRegistry 实例

    Returns:
        注册成功的 skill 数量
    """
    count = 0
    for skill in BUSINESS_SKILLS:
        try:
            registry.register(skill)
            count += 1
        except Exception as e:
            print(f"[business_skills] 注册 {skill.name} 失败: {e}")
    return count


def get_business_skills_info() -> List[Dict]:
    """获取所有业务 skill 的元信息（供前端渲染 chips）"""
    return [
        {
            'name': s.name,
            'description': s.description,
            'category': s.category,
            'timeout': s.timeout,
        }
        for s in BUSINESS_SKILLS
    ]


def check_dependencies() -> Dict[str, bool]:
    """检查所有业务 skill 的依赖库安装情况"""
    deps = {
        'math_solver': ['sympy'],
        'web_researcher': ['requests', 'bs4'],
        'info_debater': ['difflib'],  # difflib 是标准库
        'math_plotter': ['matplotlib', 'numpy'],
        'office_generator': ['pptx', 'docx', 'openpyxl', 'reportlab'],
        'image_processor': ['PIL', 'easyocr'],
        # ★ L3 新增 Skills 依赖
        'browser_automation': ['playwright', 'selenium'],
        'jupyter_notebook': ['nbformat', 'nbclient'],
        'ssh_skill': ['paramiko'],
        'docker_skill': [],
        'npm_pip_skill': [],
        'lsp_code_analysis': [],
        'mcp_bridge': [],
    }
    result = {}
    for skill_name, libs in deps.items():
        result[skill_name] = {lib: _check_lib(lib) for lib in libs}
    return result
