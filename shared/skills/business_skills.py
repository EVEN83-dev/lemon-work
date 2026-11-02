# -*- coding: utf-8 -*-
"""
业务 Skill 实现 — Lemon Code 公司多业务能力扩展
=============================================
本模块实现 6 类非编码业务 skill，扩展 Agent 能力边界：

1. math_solver       — 数学难题运算（SymPy 符号计算 + 数值计算）
2. web_researcher    — 网络爬虫与数据调研（requests + BeautifulSoup4）
3. info_debater      — 多源信息辩驳与验证（语义对比 + 矛盾检测）
4. math_plotter      — 数学图像生成（函数图 / 3D 几何 / 矩阵热图）
5. office_generator  — 办公文档生成（PPT / Word / Excel / PDF）
6. image_processor   — 图像处理与 OCR（Pillow + EasyOCR）

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
import sys
import io
import base64
import re
import json
import traceback
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from bridge.skills.models import SkillDef, SkillResult


# ============================================================
# 工具函数
# ============================================================

def _check_lib(lib_name: str) -> bool:
    """检查库是否已安装（不导入）"""
    try:
        import importlib
        spec = importlib.util.find_spec(lib_name)
        return spec is not None
    except Exception:
        return False


def _lazy_import(lib_name: str):
    """懒加载库 — 失败返回 None"""
    try:
        return __import__(lib_name)
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
        return SkillResult(success=False, error="url or query must be provided")

    requests = _lazy_import('requests')
    if requests is None:
        return _lib_missing_result('requests', 'web_researcher')

    bs4 = _lazy_import('bs4')
    if bs4 is None:
        return _lib_missing_result('beautifulsoup4', 'web_researcher')

    try:
        results = []
        seen_urls = set()

        if url:
            r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0 (LemonAgent/2.0)'})
            r.encoding = r.apparent_encoding
            soup = bs4.BeautifulSoup(r.text, 'lxml' if _check_lib('lxml') else 'html.parser')

            title = soup.title.string if soup.title else '(no title)'

            if extract_text:
                for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                    tag.decompose()
                text = soup.get_text(separator='\n', strip=True)
                text = re.sub(r'\n{3,}', '\n\n', text)
                text = text[:5000]
            else:
                text = r.text[:5000]

            seen_urls.add(url)
            results.append({
                'url': url,
                'title': title,
                'status': r.status_code,
                'content': text,
            })

        elif query:
            ua = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            links = []

            search_engines = [
                ("duckduckgo", "https://html.duckduckgo.com/html/?q=" + query.replace(' ', '+')),
                ("bing", "https://www.bing.com/search?q=" + query.replace(' ', '+')),
            ]
            search_html = None
            used_engine = None
            for engine_name, engine_url in search_engines:
                try:
                    r = requests.get(engine_url, timeout=15, headers=ua)
                    r.raise_for_status()
                    search_html = r.text
                    used_engine = engine_name
                    break
                except Exception:
                    continue

            if search_html is None:
                return SkillResult(success=False, error="Search request failed: all engines unreachable")

            soup = bs4.BeautifulSoup(search_html, 'html.parser')

            if used_engine == "duckduckgo":
                for a in soup.select('.result__a')[:max_pages]:
                    href = a.get('href', '')
                    title = a.get_text(strip=True)
                    if href and href not in seen_urls:
                        links.append({'title': title, 'url': href})
                        seen_urls.add(href)
                if not links:
                    for a in soup.find_all('a', href=True)[:max_pages * 2]:
                        href = a.get('href', '')
                        if 'duckduckgo' in href or not href.startswith('http'):
                            continue
                        title = a.get_text(strip=True)[:80]
                        if href not in seen_urls:
                            links.append({'title': title, 'url': href})
                            seen_urls.add(href)
                        if len(links) >= max_pages:
                            break
            elif used_engine == "bing":
                for li in soup.select('#b_results .b_algo')[:max_pages]:
                    a_tag = li.find('a', href=True)
                    if not a_tag:
                        continue
                    href = a_tag['href']
                    title = a_tag.get_text(strip=True)[:120]
                    if href and href not in seen_urls:
                        links.append({'title': title, 'url': href})
                        seen_urls.add(href)

            for link in links[:max_pages]:
                try:
                    sub_r = requests.get(link['url'], timeout=20,
                                          headers={'User-Agent': 'Mozilla/5.0 (LemonAgent/2.0)'})
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
            output="Research complete, fetched " + str(len(results)) + " pages\n" +
                   "\n---\n".join(["Title: " + r.get('title', '') + "\nURL: " + r.get('url', '') + "\nSummary: " + r.get('content', '')[:200] + "..."
                                    for r in results]),
            data={'results': results, 'count': len(results)},
        )

    except Exception as e:
        return SkillResult(success=False, error="Web research failed: " + str(e))


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
                # 退化: 用 eval（受限环境）
                y = eval(expression, {'x': x, 'sin': numpy.sin, 'cos': numpy.cos,
                                       'exp': numpy.exp, 'log': numpy.log,
                                       'sqrt': numpy.sqrt, 'pi': numpy.pi, 'e': numpy.e})
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
                Z = eval(expression, {'x': X, 'y': Y, 'sin': numpy.sin, 'cos': numpy.cos,
                                       'sqrt': numpy.sqrt})
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

            prs = pptx.Presentation()
            # 标题页
            slide_layout = prs.slide_layouts[0]
            slide = prs.slides.add_slide(slide_layout)
            slide.shapes.title.text = title
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
                slide.shapes.title.text = sd.get('slide_title', '')
                slide.placeholders[1].text = sd.get('slide_content', '')

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

            wb = openpyxl.Workbook()
            try:
                sheets_data = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                sheets_data = {title: [[c.strip() for c in line.split(',')] for line in content.split('\n') if line.strip()]}

            # ★ 支持两种格式：
            # 1. 字典：{sheet_name: [[row], ...]}
            # 2. 数组：[[row], ...]（自动用 title 作为 sheet 名）
            if isinstance(sheets_data, list):
                sheets_data = {title: sheets_data}

            first = True
            for sheet_name, rows in sheets_data.items():
                if first:
                    ws = wb.active
                    ws.title = sheet_name
                    first = False
                else:
                    ws = wb.create_sheet(sheet_name)
                for row in rows:
                    ws.append(row)

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
    description="图像处理: 缩放/旋转/滤镜/格式转换/合成/OCR 文字识别。支持中文 OCR。",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "输入图像路径"},
            "operation": {
                "type": "string",
                "enum": ["info", "resize", "rotate", "filter", "convert", "composite", "ocr"],
                "description": "操作类型",
            },
            "output_path": {"type": "string", "description": "输出路径（默认覆盖原图）"},
            "options": {"type": "string", "description": "JSON 操作参数", "default": "{}"},
        },
        "required": ["image_path", "operation"],
    },
    handler=_handle_image_process,
    category="image",
    timeout=60,
)


# ============================================================
# Skill 7: code_reviewer — 代码审查
# ============================================================

def _handle_code_review(
    code: str = "",
    language: str = "python",
    review_type: str = "full",
    rules: str = "",
) -> SkillResult:
    """
    代码审查 skill — 分析代码片段并给出审查意见

    参数:
        code: 待审查的代码片段
        language: 编程语言（python / javascript / typescript / java / go / rust）
        review_type:
            - full       全面审查（质量+安全+性能）
            - security   安全审查（注入、敏感信息）
            - quality    代码质量（命名、结构、注释）
            - performance 性能审查（复杂度、内存）
            - style      代码风格（PEP8/ESLint规则）
        rules: 自定义规则（JSON 数组，格式如 [{"pattern":"...", "severity":"high", "message":"..."}]）
    """
    if not code:
        return SkillResult(success=False, error="code 参数为空")

    import re
    import ast as _ast

    findings = []
    severity_map = {"high": "[严重]", "medium": "[警告]", "low": "[建议]"}

    code_lines = code.split('\n')

    # ===== 通用审查规则 =====

    # 1. 检查行长度
    if review_type in ('full', 'quality', 'style'):
        for i, line in enumerate(code_lines, 1):
            if len(line) > 120:
                findings.append({
                    "severity": "low",
                    "line": i,
                    "title": "行过长",
                    "description": f"第{i}行长度 {len(line)} 字符，超过120字符限制",
                    "suggestion": "将长行拆分为多行，或提取为变量",
                })

    # 2. 检查 TODO/FIXME/HACK 注释
    if review_type in ('full', 'quality'):
        for i, line in enumerate(code_lines, 1):
            for tag in ('TODO', 'FIXME', 'HACK', 'XXX'):
                if tag in line and ('#' in line or '//' in line):
                    findings.append({
                        "severity": "medium",
                        "line": i,
                        "title": f"遗留{tag}标记",
                        "description": f"第{i}行发现 {tag} 标记",
                        "suggestion": f"在合并前处理 {tag} 项",
                    })
                    break

    # 3. 检查硬编码敏感信息
    if review_type in ('full', 'security'):
        sensitive_patterns = [
            (r'password\s*=\s*["\']', '硬编码密码'),
            (r'api_key\s*=\s*["\']', '硬编码 API Key'),
            (r'secret\s*=\s*["\']', '硬编码密钥'),
            (r'token\s*=\s*["\']', '硬编码 Token'),
            (r'BEGIN\s+(RSA|DSA|EC|OPENSSH)\s+PRIVATE\s+KEY', '私钥泄露'),
        ]
        for pattern, desc in sensitive_patterns:
            for i, line in enumerate(code_lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append({
                        "severity": "high",
                        "line": i,
                        "title": f"安全风险: {desc}",
                        "description": f"第{i}行检测到疑似{desc}",
                        "suggestion": "使用环境变量或密钥管理服务存储敏感信息",
                    })

    # 4. Python 专用检查
    if language == 'python' and review_type in ('full', 'quality', 'security'):
        # 检查 eval/exec
        for i, line in enumerate(code_lines, 1):
            if re.search(r'\beval\s*\(', line):
                findings.append({"severity": "high", "line": i, "title": "安全风险: 使用 eval()",
                    "description": f"第{i}行使用 eval()，可能导致代码注入",
                    "suggestion": "使用 ast.literal_eval() 替代 eval()"})
            if re.search(r'\bexec\s*\(', line):
                findings.append({"severity": "high", "line": i, "title": "安全风险: 使用 exec()",
                    "description": f"第{i}行使用 exec()，可能导致代码注入",
                    "suggestion": "避免使用 exec()，改用更安全的方式"})

        # 检查裸 except
        for i, line in enumerate(code_lines, 1):
            if re.search(r'except\s*:', line.strip()):
                findings.append({"severity": "medium", "line": i, "title": "代码质量: 裸 except",
                    "description": f"第{i}行使用裸 except 捕获所有异常",
                    "suggestion": "指定具体异常类型，如 except ValueError as e:"})

    # 5. 复杂度分析
    if review_type in ('full', 'performance'):
        # 检测嵌套循环
        for i, line in enumerate(code_lines, 1):
            depth = line.count('    ') // 4  # 粗略缩进深度
            if depth >= 4:
                findings.append({
                    "severity": "medium",
                    "line": i,
                    "title": "性能: 嵌套过深",
                    "description": f"第{i}行缩进深度 {depth}，可能嵌套过深",
                    "suggestion": f"考虑提取内层逻辑为独立函数，降低复杂度",
                })

    # 6. 自定义规则
    if rules:
        try:
            custom_rules = json.loads(rules) if isinstance(rules, str) else rules
            for rule in custom_rules:
                pattern = rule.get('pattern', '')
                severity = rule.get('severity', 'medium')
                message = rule.get('message', '')
                if pattern:
                    for i, line in enumerate(code_lines, 1):
                        if re.search(pattern, line):
                            findings.append({
                                "severity": severity,
                                "line": i,
                                "title": f"自定义规则: {message}",
                                "description": f"第{i}行匹配自定义规则 '{pattern}'",
                                "suggestion": rule.get('suggestion', ''),
                            })
        except (json.JSONDecodeError, Exception):
            pass

    # 汇总报告
    high_count = sum(1 for f in findings if f['severity'] == 'high')
    medium_count = sum(1 for f in findings if f['severity'] == 'medium')
    low_count = sum(1 for f in findings if f['severity'] == 'low')

    total_lines = len(code_lines)
    score = max(0, 100 - (high_count * 15 + medium_count * 5 + low_count * 2))

    output = (
        f"=== 代码审查报告 ===\n"
        f"语言: {language}\n"
        f"代码行数: {total_lines}\n"
        f"审查类型: {review_type}\n"
        f"质量评分: {score}/100\n"
        f"问题统计: [严重] {high_count}  [警告] {medium_count}  [建议] {low_count}\n\n"
    )

    if not findings:
        output += "✅ 未发现明显问题，代码质量良好。\n"
    else:
        for f in findings:
            output += f"{severity_map.get(f['severity'], '')} L{f['line']}: {f['title']}\n"
            output += f"  → {f['description']}\n"
            output += f"  💡 {f['suggestion']}\n\n"

    return SkillResult(
        success=True,
        output=output,
        data={
            'findings': findings,
            'score': score,
            'summary': {
                'high': high_count,
                'medium': medium_count,
                'low': low_count,
                'total_lines': total_lines,
                'language': language,
            },
        },
    )


CODE_REVIEWER_SKILL = SkillDef(
    name="code_reviewer",
    description="代码审查：分析代码片段，检测安全漏洞、代码质量问题、性能瓶颈、风格问题。支持自定义规则。",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "待审查的代码片段"},
            "language": {
                "type": "string",
                "enum": ["python", "javascript", "typescript", "java", "go", "rust"],
                "description": "编程语言",
                "default": "python",
            },
            "review_type": {
                "type": "string",
                "enum": ["full", "security", "quality", "performance", "style"],
                "description": "审查类型",
                "default": "full",
            },
            "rules": {"type": "string", "description": "自定义规则 JSON 数组", "default": ""},
        },
        "required": ["code"],
    },
    handler=_handle_code_review,
    category="code",
    timeout=30,
)


# ============================================================
# Skill 8: test_generator — 测试生成
# ============================================================

def _handle_test_generate(
    code: str = "",
    language: str = "python",
    test_framework: str = "auto",
    test_type: str = "unit",
) -> SkillResult:
    """
    测试生成 skill — 根据函数定义自动生成单元测试

    参数:
        code: 函数定义代码
        language: 编程语言
        test_framework:
            - auto    自动检测（pytest / jest / JUnit）
            - pytest  Python pytest
            - unittest Python unittest
            - jest    JavaScript Jest
            - junit   Java JUnit
        test_type:
            - unit        单元测试
            - integration 集成测试
            - edge        边界测试
    """
    if not code:
        return SkillResult(success=False, error="code 参数为空")

    import re

    # 解析函数签名
    func_match = re.search(
        r'(?:def|function|func|public\s+\w+\s+)\s*(\w+)\s*\(([^)]*)\)',
        code, re.MULTILINE
    )
    if not func_match:
        return SkillResult(
            success=False,
            error="无法解析函数签名，请提供有效的函数定义",
            output="支持格式: def func_name(args): / function funcName(args) { / public Type method(args) {"
        )

    func_name = func_match.group(1)
    params_str = func_match.group(2).strip()
    params = [p.strip().split(':')[0].split('=')[0].strip()
              for p in params_str.split(',')] if params_str else []

    # 检测参数类型提示
    has_type_hints = '->' in code or ':' in params_str

    # 生成测试用例
    test_cases = []

    if test_type in ('unit', 'edge'):
        # 空值/None 测试
        if params:
            test_cases.append({
                "name": f"test_{func_name}_with_none_arguments",
                "description": "测试输入为 None 时的行为",
                "inputs": {p: "None" for p in params},
                "expected": "应抛出 TypeError 或返回 None",
            })

        # 边界测试
        if has_type_hints and any('int' in p for p in params_str.split(',')):
            int_params = [p for p, pt in zip(params, params_str.split(',')) if 'int' in pt.lower()]
            test_cases.append({
                "name": f"test_{func_name}_boundary_values",
                "description": "测试边界值",
                "inputs": {p: "0" if p in int_params else "''" for p in params},
                "expected": "函数应正常处理边界值",
            })

    # 基础测试
    test_cases.append({
        "name": f"test_{func_name}_basic",
        "description": "基础功能测试",
        "inputs": {p: f"sample_{p}" for p in params},
        "expected": "函数应返回预期结果",
    })

    # 生成对应框架的测试代码
    if test_framework == 'auto':
        test_framework = {
            'python': 'pytest',
            'javascript': 'jest',
            'typescript': 'jest',
            'java': 'junit',
            'go': 'testing',
        }.get(language, 'pytest')

    if test_framework == 'pytest':
        import_lines = "import pytest\n"
        if '->' in code or 'List' in code or 'Dict' in code:
            import_lines += "from typing import Any\n"
        test_code = import_lines + "\n\n"
        test_code += f"# 原始函数:\n# {code}\n\n\n"
        test_code += f"class Test{func_name.capitalize()}:\n"
        for tc in test_cases:
            args_str = ", ".join(f"{k}={v}" for k, v in tc['inputs'].items())
            test_code += f"    def {tc['name']}(self):\n"
            test_code += f"        \"\"\"{tc['description']}\"\"\"\n"
            test_code += f"        result = {func_name}({args_str})\n"
            test_code += f"        # TODO: 验证 {tc['expected']}\n"
            test_code += f"        assert result is not None\n\n"

    elif test_framework == 'jest':
        test_code = (
            f"// 原始函数:\n// {code}\n\n"
            f"describe('{func_name}', () => {{\n"
        )
        for tc in test_cases:
            test_code += (
                f"  test('{tc['description']}', () => {{\n"
                f"    const result = {func_name}({', '.join(tc['inputs'].values())});\n"
                f"    // TODO: {tc['expected']}\n"
                f"    expect(result).toBeDefined();\n"
                f"  }});\n\n"
            )
        test_code += "});\n"

    elif test_framework == 'junit':
        test_code = (
            f"import org.junit.jupiter.api.Test;\n"
            f"import static org.junit.jupiter.api.Assertions.*;\n\n"
            f"// 原始函数:\n// {code}\n\n"
            f"class {func_name.capitalize()}Test {{\n"
        )
        for tc in test_cases:
            test_code += (
                f"    @Test\n"
                f"    void {tc['name']}() {{\n"
                f"        // {tc['description']}\n"
                f"        var result = {func_name}({', '.join(tc['inputs'].values())});\n"
                f"        // TODO: {tc['expected']}\n"
                f"        assertNotNull(result);\n"
                f"    }}\n\n"
            )
        test_code += "}\n"

    else:
        test_code = f"# {func_name} 测试\n" + "\n".join(
            f"# {tc['name']}: {tc['description']}" for tc in test_cases
        )

    output = (
        f"=== 测试生成报告 ===\n"
        f"函数: {func_name}\n"
        f"参数: {', '.join(params) if params else '(无)'}\n"
        f"框架: {test_framework}\n"
        f"测试类型: {test_type}\n"
        f"生成用例数: {len(test_cases)}\n\n"
        f"--- 测试代码 ---\n{test_code}"
    )

    return SkillResult(
        success=True,
        output=output,
        data={
            'function_name': func_name,
            'parameters': params,
            'test_framework': test_framework,
            'test_cases': [tc['name'] for tc in test_cases],
            'test_code': test_code,
            'test_count': len(test_cases),
        },
    )


TEST_GENERATOR_SKILL = SkillDef(
    name="test_generator",
    description="测试生成：根据函数定义自动生成单元测试/集成测试/边界测试。支持 pytest/Jest/JUnit。",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "函数定义代码"},
            "language": {
                "type": "string",
                "enum": ["python", "javascript", "typescript", "java", "go"],
                "default": "python",
            },
            "test_framework": {
                "type": "string",
                "enum": ["auto", "pytest", "unittest", "jest", "junit"],
                "default": "auto",
            },
            "test_type": {
                "type": "string",
                "enum": ["unit", "integration", "edge"],
                "default": "unit",
            },
        },
        "required": ["code"],
    },
    handler=_handle_test_generate,
    category="code",
    timeout=30,
)


# ============================================================
# Skill 9: doc_generator — 文档生成
# ============================================================

def _handle_doc_generate(
    code: str = "",
    language: str = "python",
    doc_type: str = "api",
    style: str = "markdown",
) -> SkillResult:
    """
    文档生成 skill — 根据代码文件生成 API 文档

    参数:
        code: 代码文件内容
        language: 编程语言
        doc_type:
            - api       API 文档（函数/类/方法）
            - module    模块文档（导入/依赖/结构）
            - changelog 变更日志（基于 git diff）
        style:
            - markdown  Markdown 格式
            - openapi   OpenAPI 3.0 格式
            - jsdoc     JSDoc 格式
    """
    if not code:
        return SkillResult(success=False, error="code 参数为空")

    import re

    # 解析函数和类
    functions = []
    classes = []
    imports = []

    code_lines = code.split('\n')

    # 提取导入
    for line in code_lines:
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('from '):
            imports.append(stripped)

    # 提取函数定义
    if language == 'python':
        func_pattern = re.compile(r'^\s*def\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*(\S+))?', re.MULTILINE)
        class_pattern = re.compile(r'^\s*class\s+(\w+)\s*(?:\(([^)]*)\))?', re.MULTILINE)
    elif language in ('javascript', 'typescript'):
        func_pattern = re.compile(r'(?:function\s+(\w+)\s*\(([^)]*)\)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\))', re.MULTILINE)
        class_pattern = re.compile(r'class\s+(\w+)\s*(?:extends\s+(\w+))?', re.MULTILINE)
    else:
        func_pattern = re.compile(r'(?:def|function|func)\s+(\w+)\s*\(([^)]*)\)', re.MULTILINE)
        class_pattern = re.compile(r'class\s+(\w+)', re.MULTILINE)

    for match in func_pattern.finditer(code):
        if language == 'python':
            name, params, ret_type = match.group(1), match.group(2), match.group(3)
        elif language in ('javascript', 'typescript'):
            name = match.group(1) or match.group(3) or ''
            params = match.group(2) or match.group(4) or ''
            ret_type = ''
        else:
            name, params = match.group(1), match.group(2)
            ret_type = ''

        # 提取 docstring
        func_start = match.start()
        docstring = ''
        for i in range(match.end() + 1, min(match.end() + 10, len(code_lines))):
            line = code_lines[i].strip() if i < len(code_lines) else ''
            if '"""' in line or "'''" in line or '/**' in line or '*/' in line:
                docstring = line.strip('"\'\n/* ')
                break

        functions.append({
            'name': name,
            'params': params,
            'return_type': ret_type or '',
            'docstring': docstring,
        })

    for match in class_pattern.finditer(code):
        classes.append({
            'name': match.group(1),
            'base': match.group(2) if match.lastindex and match.lastindex >= 2 else '',
        })

    # 生成文档
    if style == 'markdown':
        output = f"# API 文档\n\n"
        output += f"**语言**: {language}\n"
        output += f"**生成时间**: {__import__('datetime').datetime.now().isoformat()}\n\n"

        if imports:
            output += "## 导入依赖\n\n"
            for imp in imports:
                output += f"- `{imp}`\n"
            output += "\n"

        if classes:
            output += "## 类定义\n\n"
            for cls in classes:
                output += f"### `{cls['name']}`"
                if cls['base']:
                    output += f" (继承自 `{cls['base']}`)"
                output += "\n\n"

        if functions:
            output += "## 函数定义\n\n"
            for func in functions:
                output += f"### `{func['name']}({func['params']})`"
                if func['return_type']:
                    output += f" → `{func['return_type']}`"
                output += "\n\n"
                if func['docstring']:
                    output += f"{func['docstring']}\n\n"
                output += f"**参数**: {func['params'] or '(无)'}\n\n"
                if func['return_type']:
                    output += f"**返回**: `{func['return_type']}`\n\n"
                output += "---\n\n"

    elif style == 'openapi':
        output = json.dumps({
            "openapi": "3.0.0",
            "info": {
                "title": "Auto-generated API Documentation",
                "version": "1.0.0",
            },
            "paths": {
                f"/{func['name']}": {
                    "get": {
                        "summary": func['docstring'] or f"调用 {func['name']}",
                        "parameters": [
                            {"name": p.strip().split(':')[0].strip(), "in": "query", "schema": {"type": "string"}}
                            for p in func['params'].split(',') if p.strip()
                        ] if func['params'] else [],
                        "responses": {
                            "200": {"description": "成功"}
                        },
                    }
                }
                for func in functions
            },
        }, ensure_ascii=False, indent=2)

    elif style == 'jsdoc':
        output = "/**\n"
        for func in functions:
            output += f" * @function {func['name']}\n"
            for p in func['params'].split(','):
                if p.strip():
                    output += f" * @param {{{'string'}}} {p.strip().split(':')[0].strip()}\n"
            if func['return_type']:
                output += f" * @returns {{{func['return_type']}}}\n"
            output += f" * @description {func['docstring']}\n"
            output += " */\n\n"

    else:
        output = f"# {doc_type} 文档\n" + "\n".join(
            f"## {func['name']}\n{func['docstring'] or '(无描述)'}"
            for func in functions
        )

    if not functions and not classes:
        output += "\n> ⚠️ 未检测到函数或类定义，请检查代码格式。\n"

    return SkillResult(
        success=True,
        output=output,
        data={
            'functions': [f['name'] for f in functions],
            'classes': [c['name'] for c in classes],
            'imports': imports,
            'function_count': len(functions),
            'class_count': len(classes),
            'doc_style': style,
            'language': language,
        },
    )


DOC_GENERATOR_SKILL = SkillDef(
    name="doc_generator",
    description="文档生成：根据代码文件自动生成 API 文档 / 模块文档 / 变更日志。支持 Markdown / OpenAPI 3.0 / JSDoc 格式。",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "代码文件内容"},
            "language": {
                "type": "string",
                "enum": ["python", "javascript", "typescript", "java", "go"],
                "default": "python",
            },
            "doc_type": {
                "type": "string",
                "enum": ["api", "module", "changelog"],
                "default": "api",
            },
            "style": {
                "type": "string",
                "enum": ["markdown", "openapi", "jsdoc"],
                "default": "markdown",
            },
        },
        "required": ["code"],
    },
    handler=_handle_doc_generate,
    category="code",
    timeout=30,
)


# ============================================================
# Skill 10: refactor_suggester — 重构建议
# ============================================================

def _handle_refactor_suggest(
    code: str = "",
    language: str = "python",
    focus: str = "all",
) -> SkillResult:
    """
    重构建议 skill — 分析代码片段并给出重构方案

    参数:
        code: 待重构的代码片段
        language: 编程语言
        focus:
            - all           全面分析
            - readability   可读性优化
            - maintainability 可维护性优化
            - design_pattern 设计模式应用
            - dry            DRY 原则（消除重复）
    """
    if not code:
        return SkillResult(success=False, error="code 参数为空")

    import re

    suggestions = []
    code_lines = code.split('\n')

    # 1. 检测重复代码块
    if focus in ('all', 'dry'):
        blocks = {}
        for i, line in enumerate(code_lines, 1):
            stripped = line.strip()
            if len(stripped) > 20 and not stripped.startswith('#') and not stripped.startswith('//'):
                key = stripped[:40]
                if key not in blocks:
                    blocks[key] = []
                blocks[key].append(i)

        for key, lines in blocks.items():
            if len(lines) >= 3:
                suggestions.append({
                    "category": "DRY",
                    "priority": "medium",
                    "title": "重复代码块",
                    "description": f"第 {', '.join(map(str, lines))} 行存在相似代码",
                    "suggestion": f"将重复逻辑提取为独立函数",
                    "refactored_code": (
                        f"def shared_logic(args):\n"
                        f"    # 提取的公共逻辑\n"
                        f"    {key.replace(chr(10), chr(10) + '    ')}\n"
                        f"    return result\n\n"
                        f"# 原位置替换为:\n"
                        f"result = shared_logic(args)"
                    ),
                })

    # 2. 检测过长函数（>30行）
    if focus in ('all', 'readability', 'maintainability'):
        func_lines = []
        in_func = False
        func_start = 0
        brace_depth = 0
        for i, line in enumerate(code_lines, 1):
            stripped = line.strip()
            if re.match(r'(def|function|func|public|private|protected)\s', stripped):
                in_func = True
                func_start = i
                func_lines = [stripped]
                brace_depth = 0
            elif in_func:
                func_lines.append(stripped)
                if '{' in stripped:
                    brace_depth += 1
                if '}' in stripped:
                    brace_depth -= 1
                if language == 'python' and stripped and not stripped.startswith(' ') and not stripped.startswith('\t') and i > func_start:
                    # 函数结束
                    if len(func_lines) > 30:
                        suggestions.append({
                            "category": "可维护性",
                            "priority": "medium",
                            "title": "函数过长",
                            "description": f"函数从第{func_start}行开始，共{len(func_lines)}行，超过30行建议",
                            "suggestion": f"将函数拆分为多个小函数，每个函数只做一件事",
                            "refactored_code": (
                                f"# 原函数 ({len(func_lines)} 行)\n"
                                f"def original_func():\n"
                                f"    ...\n\n"
                                f"# 重构后:\n"
                                f"def step1_prepare():\n    ...\n\n"
                                f"def step2_process():\n    ...\n\n"
                                f"def step3_finalize():\n    ...\n\n"
                                f"def main():\n"
                                f"    data = step1_prepare()\n"
                                f"    result = step2_process(data)\n"
                                f"    return step3_finalize(result)"
                            ),
                        })
                    in_func = False
                    func_lines = []

    # 3. 检测魔法数字
    if focus in ('all', 'readability', 'maintainability'):
        for i, line in enumerate(code_lines, 1):
            # 排除常见无害数字（0, 1, -1, 2 等）
            numbers = re.findall(r'(?<![a-zA-Z_\]\)\d])(\d{2,}|[3-9]\d*)(?![a-zA-Z_\[\(\d])', line)
            for num in set(numbers):
                if not (line.strip().startswith('#') or line.strip().startswith('//')):
                    suggestions.append({
                        "category": "可读性",
                        "priority": "low",
                        "title": f"魔法数字 '{num}'",
                        "description": f"第{i}行发现魔法数字 {num}",
                        "suggestion": f"将 {num} 定义为命名常量",
                        "refactored_code": f"MAX_RETRY_COUNT = {num}\n# 替换原代码中的 {num}",
                    })

    # 4. 检测过长参数列表
    if focus in ('all', 'readability'):
        func_sig = re.findall(r'(?:def|function)\s+\w+\s*\(([^)]{60,})\)', code)
        for sig in func_sig:
            param_count = len([p for p in sig.split(',') if p.strip()])
            if param_count > 5:
                suggestions.append({
                    "category": "可读性",
                    "priority": "medium",
                    "title": "参数过多",
                    "description": f"函数有 {param_count} 个参数，超过建议的5个",
                    "suggestion": "使用参数对象（dataclass/dict）封装参数",
                    "refactored_code": (
                        "from dataclasses import dataclass\n\n"
                        "@dataclass\n"
                        "class FunctionParams:\n"
                        "    param1: str\n"
                        "    param2: int\n"
                        "    ...\n\n"
                        "def func(params: FunctionParams):\n"
                        "    ..."
                    ),
                })

    # 5. 设计模式建议
    if focus in ('all', 'design_pattern'):
        # 检测大量 if-elif 链
        if_elif_count = sum(1 for line in code_lines if line.strip().startswith('elif '))
        if if_elif_count >= 3:
            suggestions.append({
                "category": "设计模式",
                "priority": "low",
                "title": "长 if-elif 链",
                "description": f"检测到 {if_elif_count} 个 elif 分支",
                "suggestion": "考虑使用策略模式或字典映射替代 if-elif 链",
                "refactored_code": (
                    "# 策略模式:\n"
                    "strategies = {\n"
                    "    'case1': handle_case1,\n"
                    "    'case2': handle_case2,\n"
                    "    'case3': handle_case3,\n"
                    "}\n"
                    "handler = strategies.get(case_key, default_handler)\n"
                    "result = handler(data)"
                ),
            })

        # 检测单例模式需求
        if 'class' in code and '__init__' in code:
            suggestions.append({
                "category": "设计模式",
                "priority": "low",
                "title": "考虑设计模式",
                "description": "检测到类定义，可以考虑应用合适的设计模式",
                "suggestion": "根据职责选择：工厂模式（创建）、策略模式（行为）、观察者模式（事件）",
                "refactored_code": "",
            })

    # 汇总报告
    if not suggestions:
        output = "✅ 代码结构良好，未发现明显重构需求。\n"
    else:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda s: (priority_order.get(s['priority'], 9), s['category']))

        output = "=== 重构建议报告 ===\n\n"
        output += f"分析语言: {language}\n"
        output += f"分析焦点: {focus}\n"
        output += f"建议数量: {len(suggestions)}\n\n"

        for i, s in enumerate(suggestions, 1):
            output += f"## 建议 {i}: [{s['priority'].upper()}] {s['title']}\n"
            output += f"**分类**: {s['category']}\n"
            output += f"**描述**: {s['description']}\n"
            output += f"**方案**: {s['suggestion']}\n"
            if s.get('refactored_code'):
                output += f"**重构示例**:\n```\n{s['refactored_code']}\n```\n"
            output += "\n"

    return SkillResult(
        success=True,
        output=output,
        data={
            'suggestions': suggestions,
            'count': len(suggestions),
            'language': language,
            'focus': focus,
        },
    )


REFACTOR_SUGGESTER_SKILL = SkillDef(
    name="refactor_suggester",
    description="重构建议：分析代码片段，给出可读性/可维护性/DRY/设计模式等重构方案，含代码示例。",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "待重构的代码片段"},
            "language": {
                "type": "string",
                "enum": ["python", "javascript", "typescript", "java", "go"],
                "default": "python",
            },
            "focus": {
                "type": "string",
                "enum": ["all", "readability", "maintainability", "design_pattern", "dry"],
                "default": "all",
            },
        },
        "required": ["code"],
    },
    handler=_handle_refactor_suggest,
    category="code",
    timeout=30,
)


# ============================================================
# Skill 11: perf_analyzer — 性能分析
# ============================================================

def _handle_perf_analyze(
    code: str = "",
    language: str = "python",
    analysis_type: str = "full",
) -> SkillResult:
    """
    性能分析 skill — 分析代码片段并找出性能瓶颈

    参数:
        code: 待分析的代码片段
        language: 编程语言
        analysis_type:
            - full        全面分析
            - complexity  时间复杂度分析
            - memory      内存使用分析
            - io          I/O 操作分析
            - database    数据库查询分析
    """
    if not code:
        return SkillResult(success=False, error="code 参数为空")

    import re

    bottlenecks = []
    code_lines = code.split('\n')

    # 1. 时间复杂度分析 - 嵌套循环 (O(n²) 或更高)
    if analysis_type in ('full', 'complexity'):
        loop_stack = []
        for i, line in enumerate(code_lines, 1):
            stripped = line.strip()
            if re.match(r'(for|while)\s', stripped):
                loop_stack.append(i)
            if stripped == '' or (stripped and not stripped.startswith(' ')):
                if loop_stack and loop_stack[-1] and i > loop_stack[-1] and not re.match(r'(for|while)\s', stripped):
                    pass  # 保持嵌套层级
        # 更精确的嵌套检测
        indent_levels = []
        for i, line in enumerate(code_lines, 1):
            stripped = line.strip()
            if re.match(r'(for|while)\s', stripped):
                indent = len(line) - len(line.lstrip())
                indent_levels.append((indent, i))
        if len(indent_levels) >= 2:
            for idx in range(1, len(indent_levels)):
                if indent_levels[idx][0] > indent_levels[idx - 1][0]:
                    bottlenecks.append({
                        "category": "时间复杂度",
                        "severity": "high",
                        "title": "嵌套循环 O(n²)",
                        "description": f"第{indent_levels[idx-1][1]}行和第{indent_levels[idx][1]}行存在嵌套循环",
                        "suggestion": "使用哈希表或预计算减少嵌套循环，目标复杂度 O(n) 或 O(n log n)",
                        "impact": "数据量大时性能急剧下降",
                    })
                    break

    # 2. 内存分析 - 大列表/字典创建
    if analysis_type in ('full', 'memory'):
        for i, line in enumerate(code_lines, 1):
            stripped = line.strip()
            # 检测列表推导式中大量数据
            if re.search(r'\[.*for.*in\s+range\(\d{4,}\)', stripped):
                bottlenecks.append({
                    "category": "内存",
                    "severity": "medium",
                    "title": "大列表推导式",
                    "description": f"第{i}行可能创建大型列表",
                    "suggestion": "考虑使用生成器表达式 ( ) 替代列表推导式 [ ]，或使用 itertools",
                    "impact": "可能导致内存峰值",
                })
            # 检测 range 大数字
            range_match = re.search(r'range\(\s*(\d{5,})\s*\)', stripped)
            if range_match:
                bottlenecks.append({
                    "category": "内存",
                    "severity": "medium",
                    "title": "大范围迭代",
                    "description": f"第{i}行 range({range_match.group(1)}) 可能产生大量迭代",
                    "suggestion": "考虑分批处理（batch processing）或使用生成器",
                    "impact": "可能导致内存或CPU飙升",
                })

    # 3. I/O 分析
    if analysis_type in ('full', 'io'):
        io_patterns = [
            (r'open\(', '文件 I/O'),
            (r'requests\.(get|post|put|delete)', 'HTTP 请求'),
            (r'socket\.', 'Socket 连接'),
            (r'subprocess\.', '子进程调用'),
            (r'input\(', '用户输入阻塞'),
        ]
        for pattern, desc in io_patterns:
            for i, line in enumerate(code_lines, 1):
                if re.search(pattern, line.strip()):
                    bottlenecks.append({
                        "category": "I/O",
                        "severity": "low",
                        "title": f"{desc} 操作",
                        "description": f"第{i}行包含 {desc} 操作",
                        "suggestion": "使用异步 I/O (async/await) 或添加超时(timeout)，使用连接池复用连接",
                        "impact": "I/O 操作是主要性能瓶颈",
                    })
                    break  # 每种只报一次

    # 4. 数据库查询分析
    if analysis_type in ('full', 'database'):
        db_patterns = [
            (r'\.execute\(', 'SQL 执行'),
            (r'\.fetchall\(\)', '全量查询'),
            (r'SELECT\s+\*', 'SELECT * 查询'),
            (r'\.all\(\)', 'ORM 全量查询'),
        ]
        for pattern, desc in db_patterns:
            for i, line in enumerate(code_lines, 1):
                if re.search(pattern, line.strip(), re.IGNORECASE):
                    bottlenecks.append({
                        "category": "数据库",
                        "severity": "medium",
                        "title": f"数据库: {desc}",
                        "description": f"第{i}行存在 {desc}",
                        "suggestion": "添加 LIMIT 分页，使用索引，避免 N+1 查询，使用批量操作",
                        "impact": "数据库查询是大数据量场景的主要瓶颈",
                    })
                    break

    # 5. 递归检测
    if analysis_type in ('full', 'complexity'):
        func_names = re.findall(r'def\s+(\w+)\s*\(', code)
        for func_name in func_names:
            for i, line in enumerate(code_lines, 1):
                if re.search(rf'\b{func_name}\s*\(', line) and f'def {func_name}' not in line:
                    bottlenecks.append({
                        "category": "时间复杂度",
                        "severity": "medium",
                        "title": f"递归调用: {func_name}",
                        "description": f"第{i}行检测到 {func_name} 的递归调用",
                        "suggestion": "添加记忆化(memoization)或转为迭代实现，设置递归深度限制",
                        "impact": "无终止条件或深度过大时导致栈溢出",
                    })
                    break

    # 汇总报告
    if not bottlenecks:
        output = "✅ 未检测到明显性能瓶颈。\n\n"
        output += "建议:\n"
        output += "- 使用 profiler 工具（cProfile / py-spy）进行运行时分析\n"
        output += "- 关注实际数据量下的性能表现\n"
    else:
        severity_order = {"high": 0, "medium": 1, "low": 2}
        bottlenecks.sort(key=lambda b: severity_order.get(b['severity'], 9))

        output = "=== 性能分析报告 ===\n\n"
        output += f"分析类型: {analysis_type}\n"
        output += f"瓶颈数量: {len(bottlenecks)}\n\n"

        for i, b in enumerate(bottlenecks, 1):
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}[b['severity']]
            output += f"## 瓶颈 {i}: {icon} [{b['severity'].upper()}] {b['title']}\n"
            output += f"**分类**: {b['category']}\n"
            output += f"**描述**: {b['description']}\n"
            output += f"**影响**: {b['impact']}\n"
            output += f"**优化建议**: {b['suggestion']}\n\n"

    return SkillResult(
        success=True,
        output=output,
        data={
            'bottlenecks': bottlenecks,
            'count': len(bottlenecks),
            'analysis_type': analysis_type,
            'language': language,
            'severity': {
                'high': sum(1 for b in bottlenecks if b['severity'] == 'high'),
                'medium': sum(1 for b in bottlenecks if b['severity'] == 'medium'),
                'low': sum(1 for b in bottlenecks if b['severity'] == 'low'),
            },
        },
    )


PERF_ANALYZER_SKILL = SkillDef(
    name="perf_analyzer",
    description="性能分析：分析代码片段，检测时间复杂度、内存使用、I/O 瓶颈、数据库查询等问题，给出优化建议。",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "待分析的代码片段"},
            "language": {
                "type": "string",
                "enum": ["python", "javascript", "typescript", "java", "go"],
                "default": "python",
            },
            "analysis_type": {
                "type": "string",
                "enum": ["full", "complexity", "memory", "io", "database"],
                "default": "full",
            },
        },
        "required": ["code"],
    },
    handler=_handle_perf_analyze,
    category="code",
    timeout=30,
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
    CODE_REVIEWER_SKILL,
    TEST_GENERATOR_SKILL,
    DOC_GENERATOR_SKILL,
    REFACTOR_SUGGESTER_SKILL,
    PERF_ANALYZER_SKILL,
]


def register_business_skills(registry) -> int:
    """
    将 6 个业务 skill 注册到 SkillsRegistry

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
    }
    result = {}
    for skill_name, libs in deps.items():
        result[skill_name] = {lib: _check_lib(lib) for lib in libs}
    return result
