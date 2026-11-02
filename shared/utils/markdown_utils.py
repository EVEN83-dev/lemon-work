# -*- coding: utf-8 -*-
"""
Markdown 转 HTML 工具函数（共享版）
==================================
提供统一的 Markdown → HTML 转换，支持：
- 表格、代码块、列表
- LaTeX 数学公式（$...$ 和 $$...$$）
- 特殊可视化语言标记（function-cards, matrix 等）
- 代码高亮（Pygments）
- 图表/几何体自动检测与注入
- HTML 文件相关内容隐藏

从 serve_bridge.py 提取，供 mimo_process_bridge.py 等模块共享使用。
"""

import re
import json
from typing import Optional

# 尝试导入 markdown 库
try:
    import markdown as md_lib
    _MARKDOWN_AVAILABLE = True
except ImportError:
    _MARKDOWN_AVAILABLE = False

# 尝试导入 pygments 代码高亮
try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.formatters import HtmlFormatter
    _PYGMENTS_AVAILABLE = True
except ImportError:
    _PYGMENTS_AVAILABLE = False


# Pygments CSS（供外部使用）
_PYGMMENTS_CSS = ""
if _PYGMENTS_AVAILABLE:
    try:
        _formatter = HtmlFormatter(style='monokai')
        _PYGMMENTS_CSS = _formatter.get_style_defs('.codehilite')
    except Exception:
        pass


# 特殊可视化语言标记（保留原始 class，不做代码高亮）
_VISUAL_LANGS = {
    'function-cards', 'matrix', 'sequence', 'dot-plot',
    'function-plot', 'task-plan', 'file-diff'
}


def _highlight_code(code, lang=''):
    """使用 Pygments 进行代码高亮"""
    if not _PYGMENTS_AVAILABLE:
        safe = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<pre><code>{safe}</code></pre>'
    try:
        if lang and lang.strip():
            lexer = get_lexer_by_name(lang, stripall=False)
        else:
            lexer = guess_lexer(code)
        formatter = HtmlFormatter(
            style='monokai',
            noclasses=True,
            cssclass='codehilite',
            linenos='table',
            linenostart=1,
        )
        return highlight(code, lexer, formatter)
    except Exception:
        safe = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<pre><code>{safe}</code></pre>'


# ==================== 图表自动检测 ====================

_CHART_PATTERNS = [
    # === 函数图像 ===
    (r'(sin|cos|tan)[_]?x?[_]?(?:plot|graph|image|chart|func|函数)[_.].*(?:html|png|jpg|svg)',
     lambda m: f'y = {m.group(1).lower()}(x)'),
    (r'(正弦|sin)[^。\n]{0,30}(?:图像|曲线|函数|图)', lambda m: 'y = sin(x)'),
    (r'(余弦|cos)[^。\n]{0,30}(?:图像|曲线|函数|图)', lambda m: 'y = cos(x)'),
    (r'(正切|tan)[^。\n]{0,30}(?:图像|曲线|函数|图)', lambda m: 'y = tan(x)'),
    (r'sin\s*\(\s*x\s*\).*?(?:图像|曲线|plot|graph|chart)', lambda m: 'y = sin(x)'),
    (r'cos\s*\(\s*x\s*\).*?(?:图像|曲线|plot|graph|chart)', lambda m: 'y = cos(x)'),
    (r'tan\s*\(\s*x\s*\).*?(?:图像|曲线|plot|graph|chart)', lambda m: 'y = tan(x)'),
    (r'(?:图像|曲线|plot|graph|chart).*?sin\s*\(\s*x\s*\)', lambda m: 'y = sin(x)'),
    (r'(?:图像|曲线|plot|graph|chart).*?cos\s*\(\s*x\s*\)', lambda m: 'y = cos(x)'),
    (r'(?:图像|曲线|plot|graph|chart).*?tan\s*\(\s*x\s*\)', lambda m: 'y = tan(x)'),
    # === 饼图 ===
    (r'饼图|pie\s*chart|饼状图|扇形图|市场份额|占比|比例分布', lambda m: '【chart:pie】'),
    (r'(?:饼|扇形|pie).*?(?:图|chart|plot)', lambda m: '【chart:pie】'),
    (r'市场调查|市场调研|竞品分析|占比分析', lambda m: '【chart:pie】'),
    # === 折线图 ===
    (r'折线图|曲线图|line\s*chart|折线统计|趋势图|走势图', lambda m: '【chart:line】'),
    (r'(?:折线|曲线|line|趋势|走势).*?(?:图|chart|plot)', lambda m: '【chart:line】'),
    (r'(数据趋势|增长趋势|变化趋势|发展趋势|市场趋势|趋势分析|走势分析)', lambda m: '【chart:line】'),
    (r'[蓝红黄紫绿粉灰黑白色].*?折线.*?(?:市场|企业|数据|规模|数量|收入)', lambda m: '【chart:line】'),
    (r'[蓝红黄紫绿粉灰黑白色].*?折线', lambda m: '【chart:line】'),
    # === 柱状图 ===
    (r'直方图|柱状图|条形图|bar\s*chart|histogram|柱形图', lambda m: '【chart:bar】'),
    (r'(?:bar|柱|条|hist).*?(?:图|chart|plot|graph)', lambda m: '【chart:bar】'),
    # === 散点图 ===
    (r'散点图|scatter\s*plot|scatter\s*chart', lambda m: '【chart:scatter】'),
    (r'散点.*?(?:图|chart|plot)', lambda m: '【chart:scatter】'),
    # === 3D曲面 ===
    (r'3D\s*surface|三维曲面|3d\s*plot', lambda m: '【chart:surface3d】'),
    (r'(?:3D|三维|surface).*?(?:图|chart|plot|曲面)', lambda m: '【chart:surface3d】'),
    # === 3D几何体 ===
    (r'正方体|立方体|cube|正六面体', lambda m: '【geom:cube】'),
    (r'(?:正方|立方|cube).*?(?:体|图形|模型|几何体|shape|geometry)', lambda m: '【geom:cube】'),
    (r'长方体|四棱柱|cuboid|rectangular.*prism', lambda m: '【geom:cuboid】'),
    (r'(?:长方|四棱柱).*?(?:体|图形|模型|几何体)', lambda m: '【geom:cuboid】'),
    (r'圆柱体?|cylinder|圆柱', lambda m: '【geom:cylinder】'),
    (r'(?:圆柱).*?(?:体|图形|模型|几何体)', lambda m: '【geom:cylinder】'),
    (r'圆锥体?|cone|圆锥', lambda m: '【geom:cone】'),
    (r'(?:圆锥).*?(?:体|图形|模型|几何体)', lambda m: '【geom:cone】'),
    (r'球(?:体|形)?|sphere|球体', lambda m: '【geom:sphere】'),
    (r'(?:球|sphere).*?(?:体|图形|模型|几何体|surface)', lambda m: '【geom:sphere】'),
    (r'椭球|椭圆体|椭球体|ellipsoid|椭圆的.*(?:体|球)', lambda m: '【geom:ellipsoid】'),
    (r'(?:椭球|椭圆体|ellipsoid).*?(?:体|图形|模型)', lambda m: '【geom:ellipsoid】'),
    (r'三棱锥|四面体|triangular\s*pyramid|tetrahedron|三角锥', lambda m: '【geom:pyramid3】'),
    (r'(?:三棱锥|四面体|三角锥).*?(?:体|图形|模型|几何体)', lambda m: '【geom:pyramid3】'),
    (r'四棱锥|方锥|pyramid|棱锥', lambda m: '【geom:pyramid4】'),
    (r'(?:四棱锥|方锥|棱锥).*?(?:体|图形|模型|几何体)', lambda m: '【geom:pyramid4】'),
    (r'三棱柱|三角柱|triangular\s*prism', lambda m: '【geom:prism3】'),
    (r'3D几何体|三维几何体|几何模型|立体图形|3d.*geometry', lambda m: '【geom:cube】'),
    # === 通用图表 ===
    (r'市场分析|数据分析|数据统计|统计图|数据可视化|matplotlib|数据图表', lambda m: '【chart:bar】'),
]


def _extract_chart_data(text: str, chart_type: str) -> Optional[dict]:
    """从 AI 回复文本中提取图表数据"""
    if not text or not chart_type:
        return None
    if not chart_type.startswith('【chart:'):
        return None

    # 1. JSON 数据块
    for m in re.finditer(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL):
        try:
            obj = json.loads(m.group(1).strip())
            if isinstance(obj, dict):
                values = obj.get('values') or obj.get('value') or obj.get('data')
                labels = obj.get('labels') or obj.get('label') or obj.get('categories')
                if isinstance(values, list) and values:
                    if not isinstance(labels, list) or len(labels) != len(values):
                        labels = [f'项{i+1}' for i in range(len(values))]
                    num_values = []
                    for v in values:
                        try:
                            num_values.append(float(v))
                        except (TypeError, ValueError):
                            num_values.append(0)
                    return {'labels': [str(l) for l in labels], 'values': num_values}
        except (json.JSONDecodeError, TypeError):
            continue

    # 2. Markdown 表格
    table_match = re.search(r'((?:^\|.*\|\n?)+)', text, re.MULTILINE)
    if not table_match:
        lines = [l.strip() for l in text.strip().split('\n') if l.strip() and '|' in l]
    else:
        lines = [l.strip() for l in table_match.group(1).strip().split('\n') if l.strip()]

    if lines:
        data_lines = [l for l in lines if not re.match(r'^\|[\s\-:|]+\|$', l)]
        if len(data_lines) >= 2:
            headers = [h.strip() for h in data_lines[0].strip('|').split('|')]
            rows = []
            for line in data_lines[1:]:
                cells = [c.strip() for c in line.strip('|').split('|')]
                rows.append(cells)
            if rows and len(headers) >= 2:
                labels = [r[0] for r in rows if r]
                values = []
                for r in rows:
                    if len(r) >= 2:
                        cleaned = r[1].replace(',', '').replace('%', '').replace('万', '0000')
                        num_match = re.search(r'[\d.]+', cleaned)
                        try:
                            values.append(float(num_match.group()) if num_match else 0)
                        except (ValueError, AttributeError):
                            values.append(0)
                if values:
                    return {'labels': labels, 'values': values}

    # 3. 百分比格式
    pct_matches = re.findall(r'([^\s,，、()%]+?)\s*(?:占|占比|为|比例|份额)\s*([\d.]+)\s*%', text)
    if len(pct_matches) >= 2:
        labels = [m[0].strip() for m in pct_matches]
        values = []
        for m in pct_matches:
            try:
                values.append(float(m[1]))
            except ValueError:
                values.append(0)
        return {'labels': labels, 'values': values}

    # 4. 纯文本列表
    list_matches = re.findall(r'([^\s,，、:：]+?)\s*[:：][ \t]*([\d.]+)(?![\d.])', text)
    if len(list_matches) >= 2:
        labels = [m[0].strip() for m in list_matches]
        values = []
        for m in list_matches:
            try:
                values.append(float(m[1]))
            except ValueError:
                values.append(0)
        return {'labels': labels, 'values': values}

    return None


def _inject_func_plot_expr(html: str, plain_text: str) -> str:
    """检测输出中是否包含图表/几何体提及，注入标记并隐藏 HTML 文件相关内容"""
    if not plain_text:
        return html

    # 检测图表/几何体类型
    marker = None
    for pattern, builder in _CHART_PATTERNS:
        m = re.search(pattern, plain_text, re.IGNORECASE)
        if m:
            marker = builder(m)
            break

    result = html

    # 隐藏 explorer 命令
    result = re.sub(
        r'(?:explorer|start)\s+[^\s<]*\.html[^\n。]*',
        '<span style="display:none;">\\g<0></span>',
        result, flags=re.IGNORECASE
    )
    # 隐藏"已生成 xxx.html"
    result = re.sub(
        r'已生成[^。\n]*\.html[^。\n]*。?',
        '<span style="display:none;">\\g<0></span>', result
    )
    # 隐藏"已打开 xxx.html"
    result = re.sub(
        r'已打开[^。\n]*\.html[^。\n]*。?',
        '<span style="display:none;">\\g<0></span>', result
    )
    # 隐藏"用浏览器打开"
    result = re.sub(
        r'用浏览器打开[^。\n]*。?',
        '<span style="display:none;">\\g<0></span>', result
    )
    # 隐藏文件路径
    result = re.sub(
        r'(?:file:///|D:\\[^\s<>]+\.html|C:\\[^\s<>]+\.html)',
        '<span style="display:none;">\\g<0></span>',
        result, flags=re.IGNORECASE
    )
    # 隐藏 HTML 文件描述
    result = re.sub(
        r'(?:绿色发光边框|粉色顶点|橙色边框|蓝色背景)[^。\n]*。?',
        '<span style="display:none;">\\g<0></span>', result
    )

    # 注入图表标记
    if marker:
        print(f"[markdown_utils] 注入 chart-marker: {marker} (plain_text前80字: {plain_text[:80]})", flush=True)
        # ★ v3.88: 同时设置 data-type 属性和文本内容，确保前端兼容
        result = f'<div class="chart-marker" data-type="{marker}" style="display:none;">{marker}</div>' + result
    else:
        # ★ v3.88 调试: 记录未匹配的情况，帮助诊断图像不渲染问题
        if len(plain_text) > 10:
            # 检查是否包含函数/图表关键词但未匹配
            kw_check = any(kw in plain_text.lower() for kw in ['sin', 'cos', 'tan', '图像', '曲线', '图表', '几何', '公式'])
            if kw_check:
                print(f"[markdown_utils] 未匹配到chart-marker (含关键词但无匹配模式): plain_text前100字={plain_text[:100]}", flush=True)

    return result


def markdown_to_html(text: str) -> str:
    """将 Markdown 文本转换为 HTML（完整版本）"""
    if not text:
        return ""

    # ★ v3.88 调试: 确认函数被调用
    print(f"[markdown_to_html] 被调用, _MARKDOWN_AVAILABLE={_MARKDOWN_AVAILABLE}, text前60字={text[:60]}", flush=True)

    # 保护数学公式
    _math_placeholders = []
    def save_math(m):
        idx = len(_math_placeholders)
        _math_placeholders.append(m.group(0))
        return f'\x00MATH{idx}\x00'

    text = re.sub(r'\$\$(.+?)\$\$', save_math, text, flags=re.DOTALL)
    text = re.sub(r'\$([^\$\n]+?)\$', save_math, text)
    text = re.sub(r'\\\((.+?)\\\)', save_math, text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.+?)\\\]', save_math, text, flags=re.DOTALL)

    if _MARKDOWN_AVAILABLE:
        try:
            extensions = [
                'extra', 'tables', 'fenced_code',
                'nl2br', 'sane_lists', 'admonition',
            ]
            html = md_lib.markdown(text, extensions=extensions, output_format='html5')

            # 代码块高亮
            def replace_code_block(m):
                lang = m.group(1) or ''
                code = m.group(2)
                if lang.lower() in _VISUAL_LANGS:
                    return m.group(0)
                return _highlight_code(code, lang)

            html = re.sub(
                r'<pre><code class="language-([^"]*)">(.*?)</code></pre>',
                replace_code_block, html, flags=re.DOTALL
            )
            html = re.sub(
                r'<pre><code>(.*?)</code></pre>',
                lambda m: _highlight_code(m.group(1), ''),
                html, flags=re.DOTALL
            )

            # 函数图像检测注入
            html = _inject_func_plot_expr(html, text)

            # 恢复数学公式
            for i, math_expr in enumerate(_math_placeholders):
                html = html.replace(f'\x00MATH{i}\x00', math_expr)

            return html
        except Exception as e:
            print(f"[markdown_to_html] 转换失败: {e}", flush=True)

    # ===== 备用方案：手动轻量转换 =====
    _original_text = text

    # 保护代码块
    code_blocks = []
    def save_code_block(m):
        idx = len(code_blocks)
        lang = m.group(1) if m.group(1) else ''
        code = m.group(2)
        code_blocks.append((lang, code))
        return f'\x00CODEBLOCK{idx}\x00'

    text = re.sub(r'```(\w*)\n(.*?)```', save_code_block, text, flags=re.DOTALL)

    # 保护行内代码
    inline_codes = []
    def save_inline_code(m):
        idx = len(inline_codes)
        inline_codes.append(m.group(1))
        return f'\x00INLINECODE{idx}\x00'

    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # 转义 HTML
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # 标题
    text = re.sub(r'^######\s+(.+)$', r'<h6>\1</h6>', text, flags=re.MULTILINE)
    text = re.sub(r'^#####\s+(.+)$', r'<h5>\1</h5>', text, flags=re.MULTILINE)
    text = re.sub(r'^####\s+(.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^###\s+(.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)

    # 粗体和斜体
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'___(.+?)___', r'<b><i>\1</i></b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)

    # 恢复行内代码
    for i, code in enumerate(inline_codes):
        safe = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        text = text.replace(f'\x00INLINECODE{i}\x00',
            f'<code class="inline-code">{safe}</code>')

    # 恢复代码块
    _VISUAL_LANGS_FALLBACK = {'function-cards', 'matrix', 'sequence', 'dot-plot',
                              'function-plot', 'task-plan', 'file-diff'}
    for i, (lang, code) in enumerate(code_blocks):
        if lang.lower() in _VISUAL_LANGS_FALLBACK:
            safe = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            text = text.replace(f'\x00CODEBLOCK{i}\x00',
                f'<pre><code class="language-{lang}">{safe}</code></pre>')
        else:
            highlighted = _highlight_code(code, lang)
            text = text.replace(f'\x00CODEBLOCK{i}\x00', highlighted)

    # 无序列表
    text = re.sub(r'^[\-\*\+]\s+(.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)

    # 有序列表
    text = re.sub(r'^(\d+)\.\s+(.+)$', r'<li>\2</li>', text, flags=re.MULTILINE)

    # 包裹列表
    lines = text.split('\n')
    result_lines = []
    in_list = False
    list_type = 'ul'
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('<li>'):
            if not in_list:
                if i > 0 and re.match(r'^\d+\.', lines[i-1].strip()):
                    list_type = 'ol'
                else:
                    list_type = 'ul'
                result_lines.append(f'<{list_type}>')
                in_list = True
            result_lines.append(line)
        else:
            if in_list:
                result_lines.append(f'</{list_type}>')
                in_list = False
            result_lines.append(line)
        i += 1
    if in_list:
        result_lines.append(f'</{list_type}>')
    text = '\n'.join(result_lines)

    # 水平线
    text = re.sub(r'^---+\s*$', '<hr>', text, flags=re.MULTILINE)
    text = re.sub(r'^\*\*\*+\s*$', '<hr>', text, flags=re.MULTILINE)

    # 引用
    text = re.sub(r'^&gt;\s+(.+)$', r'<blockquote>\1</blockquote>', text, flags=re.MULTILINE)

    # Markdown 表格
    lines = text.split('\n')
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if '|' in line and i + 1 < len(lines) and re.match(r'^\s*\|[\s\-:|]+\|\s*$', lines[i + 1]):
            headers = [h.strip() for h in line.split('|')[1:-1]]
            i += 2
            rows = []
            while i < len(lines) and '|' in lines[i]:
                cells = [c.strip() for c in lines[i].split('|')[1:-1]]
                if cells:
                    rows.append(cells)
                i += 1
            table_html = '<table class="md-table">'
            table_html += '<thead><tr>'
            for h in headers:
                table_html += f'<th>{h}</th>'
            table_html += '</tr></thead><tbody>'
            for row_idx, row in enumerate(rows):
                table_html += '<tr>'
                for cell in row:
                    table_html += f'<td>{cell}</td>'
                table_html += '</tr>'
            table_html += '</tbody></table>'
            result_lines.append(table_html)
        else:
            result_lines.append(line)
            i += 1
    text = '\n'.join(result_lines)

    # 换行
    text = text.replace('\n', '<br>')

    # 函数图像检测注入
    text = _inject_func_plot_expr(text, _original_text)

    # 恢复数学公式
    for i, math_expr in enumerate(_math_placeholders):
        text = text.replace(f'\x00MATH{i}\x00', math_expr)

    return text
