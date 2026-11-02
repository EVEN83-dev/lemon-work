# -*- coding: utf-8 -*-
"""
Skill: code_psychologist — 代码心理学家
========================================
正向模式（描述→代码框架）或逆向模式（代码→意图分析），
支持 7 种意图分类。
"""

import ast
import os
import re
import traceback
from typing import Dict, Any, List

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
"name": "code_psychologist",
# 396B-1: 描述回显评测/用户触发语（分析这段代码/作者思路/设计意图），
# 并明示不要用 execute_code 自析 —— 三连 MISS 归因：同域替代/不选 + qwen 传参错名
"description": ("代码意图分析器：用户要求“分析这段代码 / 作者思路 / 代码在做什么 / 设计意图 / "
                "为什么这么写”时必须调用本工具（reverse 模式直接给代码意图报告），"
                "不要用 execute_code 自己分析；也支持正向模式（描述→代码框架）。"),
"category": "code",
"version": "1.1.0",
}

# 7 种意图分类
INTENT_CATEGORIES = {
    'data_processing': {'name': '数据处理', 'description': '数据清洗、转换、聚合、ETL', 'icon': '🔄'},
    'api_service': {'name': 'API 服务', 'description': 'REST API、微服务、请求处理', 'icon': '🌐'},
    'automation': {'name': '自动化', 'description': '脚本、定时任务、工作流', 'icon': '⚙️'},
    'testing': {'name': '测试验证', 'description': '单元测试、集成测试、QA', 'icon': '✅'},
    'visualization': {'name': '可视化', 'description': '图表、仪表盘、报告', 'icon': '📊'},
    'security': {'name': '安全防护', 'description': '认证、加密、权限控制', 'icon': '🔒'},
    'infrastructure': {'name': '基础设施', 'description': '部署、配置、运维', 'icon': '🏗️'},
}


def _classify_intent(code: str) -> List[Dict]:
    """根据代码特征分类意图"""
    scores = {}
    # 数据处理关键词
    scores['data_processing'] = len(re.findall(r'\b(pd\.|DataFrame|read_csv|read_json|to_csv|merge|groupby|aggregate|transform|map|filter|reduce)\b', code))
    # API 服务关键词
    scores['api_service'] = len(re.findall(r'\b(@app\.|@router\.|flask|fastapi|request|response|endpoint|api|GET|POST|PUT|DELETE)\b', code, re.IGNORECASE))
    # 自动化关键词
    scores['automation'] = len(re.findall(r'\b(scheduler|cron|subprocess|os\.system|script|automate|batch|pipeline)\b', code, re.IGNORECASE))
    # 测试关键词
    scores['testing'] = len(re.findall(r'\b(assert|pytest|unittest|mock|fixture|test_|spec)\b', code, re.IGNORECASE))
    # 可视化关键词
    scores['visualization'] = len(re.findall(r'\b(plt\.|matplotlib|plotly|chart|dashboard|render|figure|ax\.)\b', code, re.IGNORECASE))
    # 安全关键词
    scores['security'] = len(re.findall(r'\b(encrypt|decrypt|hash|token|auth|jwt|ssl|certificate|password|salt)\b', code, re.IGNORECASE))
    # 基础设施关键词
    scores['infrastructure'] = len(re.findall(r'\b(docker|kubernetes|deploy|ci/cd|terraform|ansible|config|env)\b', code, re.IGNORECASE))

    total = max(sum(scores.values()), 1)
    sorted_intents = sorted(scores.items(), key=lambda x: -x[1])
    result = []
    for intent, score in sorted_intents[:3]:
        if score > 0:
            cat = INTENT_CATEGORIES[intent]
            result.append({
                'intent': intent,
                'name': cat['name'],
                'icon': cat['icon'],
                'confidence': round(score / total, 3),
            })
    if not result:
        result.append({'intent': 'automation', 'name': '自动化', 'icon': '⚙️', 'confidence': 0.5})
    return result


def _ai_analyze_intent(description: str) -> List[Dict]:
    """调用 engine_manager 让 AI 深度分析描述文本的意图
    
    双路验证之 AI 语义分析路径：构造聚焦 prompt，让模型从 7 种意图中
    选出最匹配的 3 个并给出置信度。失败时返回空列表（回退到规则引擎）。
    """
    if not description or len(description.strip()) < 3:
        return []
    try:
        import sys as _sys
        import os as _os
        _lemon_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..', '..'))
        if _lemon_root not in _sys.path:
            _sys.path.insert(0, _lemon_root)
        from shared.engine_manager import get_engine_manager
        engine = get_engine_manager()
    except Exception:
        return []

    intent_keys = " / ".join([f"{k}:{v['name']}" for k, v in INTENT_CATEGORIES.items()])
    prompt = (
        f"你是代码意图分析专家。请从以下 7 种意图中选出最匹配的 3 个（按匹配度降序），"
        f"并给出 0~1 的置信度。\n可用意图: {intent_keys}\n\n"
        f"用户描述: {description[:500]}\n\n"
        f"严格按 JSON 数组格式输出，每项 {{\"intent\": \"key\", \"confidence\": 0.xx}}，"
        f"不要输出其他内容。"
    )
    try:
        resp = engine.chat(prompt, use_cache=False)
        content = getattr(resp, 'content', '') or ''
    except Exception:
        return []

    # 从 AI 回复中提取 JSON 数组
    import json as _json
    import re as _re
    match = _re.search(r'\[.*?\]', content, _re.DOTALL)
    if not match:
        return []
    try:
        items = _json.loads(match.group(0))
    except (ValueError, SyntaxError):
        return []

    result = []
    valid_keys = set(INTENT_CATEGORIES.keys())
    for it in items:
        if not isinstance(it, dict):
            continue
        key = it.get('intent', '')
        if key not in valid_keys:
            continue
        conf = it.get('confidence', 0.5)
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        cat = INTENT_CATEGORIES[key]
        result.append({
            'intent': key,
            'name': cat['name'],
            'icon': cat['icon'],
            'confidence': round(conf, 3),
        })
    return result[:3]


def _classify_intent_dual_path(text: str, description: str = "") -> List[Dict]:
    """双路验证：规则引擎关键词匹配 + AI 语义分析，融合两路结果
    
    融合策略：
    - 两路都命中同一意图 → 置信度加权提升（取均值后 +0.15，上限 1.0）
    - 仅规则引擎命中 → 保留规则引擎结果
    - 仅 AI 命中 → 采用 AI 结果（标记 ai_only=True）
    - 两路都为空 → 回退默认 automation
    """
    rule_results = _classify_intent(text + " " + description)
    ai_results = _ai_analyze_intent(description or text)

    if not ai_results:
        return rule_results
    if not rule_results:
        # AI 独占路径
        for r in ai_results:
            r['ai_only'] = True
        return ai_results

    # 融合：以规则引擎为主，AI 提升一致项的置信度
    rule_map = {r['intent']: r for r in rule_results}
    ai_map = {r['intent']: r for r in ai_results}

    fused = []
    # 先处理两路都命中的意图
    for key in rule_map:
        if key in ai_map:
            r_conf = rule_map[key]['confidence']
            a_conf = ai_map[key]['confidence']
            merged_conf = min(1.0, (r_conf + a_conf) / 2 + 0.15)
            fused.append({
                'intent': key,
                'name': rule_map[key]['name'],
                'icon': rule_map[key]['icon'],
                'confidence': round(merged_conf, 3),
                'verified': True,  # 双路验证通过
            })
    # 再补充仅规则引擎命中的意图
    for key, r in rule_map.items():
        if key not in ai_map:
            fused.append(dict(r))
    # 再补充仅 AI 命中的意图
    for key, a in ai_map.items():
        if key not in rule_map:
            a_copy = dict(a)
            a_copy['ai_only'] = True
            fused.append(a_copy)

    fused.sort(key=lambda x: -x['confidence'])
    return fused[:3]


def _generate_framework(description: str, intent: str) -> str:
    """根据描述生成代码框架"""
    templates = {
        'data_processing': f'''# 数据处理框架
import pandas as pd

def load_data(source: str) -> pd.DataFrame:
    """加载数据"""
    # TODO: 根据描述实现 - {description}
    raise NotImplementedError

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """数据清洗"""
    df = df.dropna()
    df = df.drop_duplicates()
    return df

def transform_data(df: pd.DataFrame) -> pd.DataFrame:
    """数据转换"""
    # TODO: 根据描述实现转换逻辑
    return df

def main():
    df = load_data("source")
    df = clean_data(df)
    df = transform_data(df)
    df.to_csv("output.csv", index=False)

if __name__ == "__main__":
    main()
''',
        'api_service': f'''# API 服务框架
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="{description}")

class Item(BaseModel):
    """数据模型"""
    # TODO: 定义字段
    pass

@app.get("/")
async def root():
    return {{"message": "Welcome to {description}"}}

@app.post("/items")
async def create_item(item: Item):
    # TODO: 实现创建逻辑
    return {{"id": 1, **item.model_dump()}}

@app.get("/items/{{item_id}}")
async def get_item(item_id: int):
    # TODO: 实现查询逻辑
    return {{"id": item_id}}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
''',
        'automation': f'''# 自动化脚本
import os
import subprocess
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup():
    """初始化"""
    logger.info("初始化自动化任务: {description}")

def run():
    """执行自动化"""
    logger.info("开始执行")
    # TODO: 根据描述实现自动化逻辑
    pass

def cleanup():
    """清理"""
    logger.info("清理完成")

def main():
    try:
        setup()
        run()
    finally:
        cleanup()

if __name__ == "__main__":
    main()
''',
        'visualization': f'''# 可视化框架
import matplotlib.pyplot as plt
import numpy as np

def load_data():
    """加载数据"""
    # TODO: 根据描述加载实际数据 - {description}
    x = np.linspace(0, 10, 100)
    y = np.sin(x)
    return x, y

def plot_data(x, y):
    """绘制图表"""
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(x, y, label='数据')
    ax.set_title("{description}")
    ax.set_xlabel("X轴")
    ax.set_ylabel("Y轴")
    ax.legend()
    ax.grid(True, alpha=0.3)
    return fig

def main():
    x, y = load_data()
    fig = plot_data(x, y)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()
''',
        'testing': f'''# 测试框架
import pytest
from typing import Any

# 被测模块导入
# from your_module import YourClass

class Test{description.replace(" ", "")[:20]}:
    """{description} 测试类"""

    @pytest.fixture
    def setup(self):
        """测试初始化"""
        # TODO: 初始化测试数据
        return {{}}

    def test_basic(self, setup):
        """基本功能测试"""
        # TODO: 实现基本测试逻辑
        assert True

    def test_edge_case(self, setup):
        """边界条件测试"""
        # TODO: 实现边界测试逻辑
        assert True

    def test_error_handling(self, setup):
        """异常处理测试"""
        # TODO: 实现异常测试逻辑
        with pytest.raises(Exception):
            raise Exception("预期异常")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
''',
        'security': f'''# 安全防护框架
import hashlib
import secrets
import hmac
from functools import wraps

def generate_token(length: int = 32) -> str:
    """生成安全随机令牌"""
    return secrets.token_hex(length)

def hash_password(password: str, salt: str = None) -> tuple:
    """密码哈希（PBKDF2 + salt）"""
    if salt is None:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return key.hex(), salt

def verify_password(password: str, key: str, salt: str) -> bool:
    """验证密码"""
    new_key, _ = hash_password(password, salt)
    return hmac.compare_digest(new_key, key)

def require_auth(func):
    """认证装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # TODO: 实现认证逻辑 - {description}
        return func(*args, **kwargs)
    return wrapper

if __name__ == "__main__":
    key, salt = hash_password("test_password")
    print(f"验证: {{verify_password('test_password', key, salt)}}")
''',
        'infrastructure': f'''# 基础设施框架
import os
import json
import logging
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeployManager:
    """部署管理器 — {description}"""

    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)

    def _load_config(self, path: str) -> dict:
        """加载配置"""
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"配置文件不存在: {{path}}，使用默认配置")
            return {{"env": "development"}}

    def check_prerequisites(self) -> bool:
        """检查前置条件"""
        # TODO: 实现环境检查
        return True

    def deploy(self, env: str = "production"):
        """执行部署"""
        logger.info(f"开始部署到 {{env}}")
        if not self.check_prerequisites():
            raise RuntimeError("前置条件检查失败")
        # TODO: 实现部署逻辑
        logger.info("部署完成")

    def rollback(self):
        """回滚"""
        logger.info("开始回滚")
        # TODO: 实现回滚逻辑
        logger.info("回滚完成")

if __name__ == "__main__":
    dm = DeployManager()
    dm.deploy()
''',
    }
    return templates.get(intent, templates['automation'])


# ============================================================
# 代码风格分析 — 开发者画像
# ============================================================

# 设计模式检测关键词
_DESIGN_PATTERNS = {
    'singleton': [r'class\s+\w+.*?:\s*.*?_instance', r'__new__'],
    'factory': [r'create_\w+', r'factory', r'build_\w+'],
    'observer': [r'add_observer', r'register_listener', r'notify_observers', r'subscribe'],
    'strategy': [r'strategy', r'algorithm', r'context'],
    'decorator': [r'@\w+', r'def wrapper', r'functools\.wraps'],
    'adapter': [r'adapter', r'adapt'],
    'command': [r'command', r'execute', r'undo'],
    'repository': [r'repository', r'repo\.'],
    'mvc': [r'controller', r'model', r'view'],
}


def _detect_naming_style(names: List[str]) -> Dict[str, Any]:
    """检测命名风格：驼峰 / 下划线 / 混合"""
    camel = 0
    snake = 0
    pascal = 0
    upper = 0
    for name in names:
        if not name:
            continue
        if name.isupper() and '_' in name:
            upper += 1
        elif name[0].isupper() and '_' not in name:
            pascal += 1
        elif '_' in name and name[0].islower():
            snake += 1
        elif name[0].islower() and any(c.isupper() for c in name):
            camel += 1
        else:
            snake += 1  # 单词小写归入 snake
    total = max(len(names), 1)
    return {
        'camel': camel, 'snake': snake, 'pascal': pascal, 'upper': upper,
        'dominant': (
            'snake_case' if snake >= max(camel, pascal, upper) else
            'camelCase' if camel >= max(pascal, upper) else
            'PascalCase' if pascal >= upper else
            'UPPER_SNAKE'
        ),
        'snake_ratio': round(snake / total, 2),
        'camel_ratio': round(camel / total, 2),
        'pascal_ratio': round(pascal / total, 2),
    }


def _detect_indent_style(code: str) -> Dict[str, Any]:
    """检测缩进偏好：2空格 / 4空格 / Tab"""
    lines = code.split('\n')
    two_space = 0
    four_space = 0
    tab_indent = 0
    for line in lines:
        if not line:
            continue
        leading = len(line) - len(line.lstrip(' \t'))
        if leading == 0:
            continue
        if line.startswith('\t'):
            tab_indent += 1
        elif leading % 4 == 0:
            four_space += 1
        elif leading % 2 == 0:
            two_space += 1
        else:
            four_space += 1
    total = max(two_space + four_space + tab_indent, 1)
    dominant = (
        'tab' if tab_indent > max(two_space, four_space) else
        '4-spaces' if four_space >= two_space else
        '2-spaces'
    )
    return {
        'dominant': dominant,
        'two_space': two_space, 'four_space': four_space, 'tab': tab_indent,
        'consistency': round(max(two_space, four_space, tab_indent) / total, 2),
    }


def _detect_design_patterns(code: str) -> List[Dict]:
    """检测设计模式使用频率"""
    found = []
    for pattern, keywords in _DESIGN_PATTERNS.items():
        count = 0
        for kw in keywords:
            count += len(re.findall(kw, code, re.IGNORECASE))
        if count > 0:
            found.append({
                'pattern': pattern,
                'count': count,
            })
    found.sort(key=lambda x: -x['count'])
    return found


def _analyze_code_style(code: str) -> Dict[str, Any]:
    """分析代码风格，输出开发者画像数据
    
    维度：命名风格 / 缩进偏好 / 注释密度 / 函数平均长度 / 设计模式
    """
    if not code or not code.strip():
        return {'error': '代码为空，无法分析风格'}

    style: Dict[str, Any] = {}

    # 1. AST 分析
    func_names: List[str] = []
    class_names: List[str] = []
    func_lengths: List[int] = []
    arg_counts: List[int] = []
    parse_ok = False
    try:
        tree = ast.parse(code)
        parse_ok = True
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_names.append(node.name)
                # 函数长度（按源代码行数）
                if hasattr(node, 'end_lineno') and node.end_lineno:
                    length = node.end_lineno - node.lineno + 1
                else:
                    length = 1
                func_lengths.append(length)
                arg_counts.append(len(node.args.args))
            elif isinstance(node, ast.ClassDef):
                class_names.append(node.name)
    except SyntaxError:
        style['ast_parse_failed'] = True

    # 2. 命名风格
    all_names = func_names + class_names
    if all_names:
        style['naming'] = _detect_naming_style(all_names)
    else:
        style['naming'] = {'dominant': 'unknown', 'snake_ratio': 0, 'camel_ratio': 0, 'pascal_ratio': 0}

    # 3. 缩进偏好
    style['indent'] = _detect_indent_style(code)

    # 4. 注释密度
    lines = code.split('\n')
    total_lines = max(len(lines), 1)
    comment_lines = 0
    docstring_lines = 0
    blank_lines = 0
    in_docstring = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_lines += 1
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if in_docstring:
                in_docstring = False
                docstring_lines += 1
            elif stripped.count('"""') == 2 or stripped.count("'''") == 2:
                docstring_lines += 1
            else:
                in_docstring = True
                docstring_lines += 1
            continue
        if in_docstring:
            docstring_lines += 1
            continue
        if stripped.startswith('#'):
            comment_lines += 1
    code_lines = total_lines - blank_lines - comment_lines - docstring_lines
    style['comments'] = {
        'comment_lines': comment_lines,
        'docstring_lines': docstring_lines,
        'blank_lines': blank_lines,
        'code_lines': max(code_lines, 1),
        'comment_density': round((comment_lines + docstring_lines) / max(total_lines, 1), 3),
    }

    # 5. 函数平均长度
    if func_lengths:
        style['functions'] = {
            'count': len(func_lengths),
            'avg_length': round(sum(func_lengths) / len(func_lengths), 1),
            'max_length': max(func_lengths),
            'min_length': min(func_lengths),
            'avg_args': round(sum(arg_counts) / len(arg_counts), 1) if arg_counts else 0,
            'long_functions': sum(1 for l in func_lengths if l > 50),
        }
    else:
        style['functions'] = {'count': 0, 'avg_length': 0, 'max_length': 0, 'min_length': 0, 'avg_args': 0, 'long_functions': 0}

    # 6. 类统计
    style['classes'] = {
        'count': len(class_names),
        'names': class_names[:10],
    }

    # 7. 设计模式
    style['design_patterns'] = _detect_design_patterns(code)

    # 8. 整体规模
    style['scale'] = {
        'total_lines': total_lines,
        'total_chars': len(code),
        'avg_line_length': round(len(code) / max(total_lines, 1), 1),
    }

    return style


def _build_developer_profile(style: Dict[str, Any]) -> Dict[str, Any]:
    """将风格分析转化为开发者画像（标签云数据）"""
    tags = []
    # 命名风格标签
    naming = style.get('naming', {})
    dom = naming.get('dominant', 'unknown')
    if dom != 'unknown':
        tags.append({'label': dom, 'weight': 5, 'category': 'naming'})
    if naming.get('snake_ratio', 0) > 0.5:
        tags.append({'label': 'PEP8命名', 'weight': 4, 'category': 'naming'})
    if naming.get('pascal_ratio', 0) > 0.5:
        tags.append({'label': '类Pascal', 'weight': 3, 'category': 'naming'})

    # 缩进标签
    indent = style.get('indent', {})
    ind_dom = indent.get('dominant', 'unknown')
    if ind_dom != 'unknown':
        tags.append({'label': ind_dom, 'weight': 5, 'category': 'indent'})
    if indent.get('consistency', 0) > 0.8:
        tags.append({'label': '缩进一致', 'weight': 4, 'category': 'indent'})
    else:
        tags.append({'label': '缩进混乱', 'weight': 3, 'category': 'indent'})

    # 注释标签
    comments = style.get('comments', {})
    density = comments.get('comment_density', 0)
    if density > 0.3:
        tags.append({'label': '注释丰富', 'weight': 5, 'category': 'docs'})
    elif density > 0.1:
        tags.append({'label': '适量注释', 'weight': 4, 'category': 'docs'})
    elif density > 0.03:
        tags.append({'label': '注释偏少', 'weight': 2, 'category': 'docs'})
    else:
        tags.append({'label': '几乎无注释', 'weight': 3, 'category': 'docs'})

    # 函数标签
    funcs = style.get('functions', {})
    avg_len = funcs.get('avg_length', 0)
    if avg_len > 50:
        tags.append({'label': '长函数偏好', 'weight': 4, 'category': 'structure'})
    elif avg_len > 20:
        tags.append({'label': '中等函数', 'weight': 4, 'category': 'structure'})
    elif avg_len > 0:
        tags.append({'label': '短小函数', 'weight': 5, 'category': 'structure'})
    if funcs.get('long_functions', 0) > 2:
        tags.append({'label': '需重构', 'weight': 3, 'category': 'structure'})

    # 设计模式标签
    patterns = style.get('design_patterns', [])
    for p in patterns[:5]:
        tags.append({'label': f"{p['pattern']}模式", 'weight': min(3 + p['count'], 7), 'category': 'pattern'})

    # 规模标签
    scale = style.get('scale', {})
    total = scale.get('total_lines', 0)
    if total > 500:
        tags.append({'label': '大型模块', 'weight': 5, 'category': 'scale'})
    elif total > 100:
        tags.append({'label': '中型模块', 'weight': 4, 'category': 'scale'})
    elif total > 0:
        tags.append({'label': '小型片段', 'weight': 3, 'category': 'scale'})

    # 综合画像
    profile_type = 'unknown'
    if density > 0.2 and avg_len < 25 and indent.get('consistency', 0) > 0.8:
        profile_type = '严谨工程师'
    elif avg_len > 50 or funcs.get('long_functions', 0) > 3:
        profile_type = '快速原型手'
    elif density < 0.05 and total > 200:
        profile_type = '极简主义者'
    elif len(patterns) >= 3:
        profile_type = '架构设计者'
    elif total < 50:
        profile_type = '脚本爱好者'

    return {
        'profile_type': profile_type,
        'tags': tags,
        'tag_count': len(tags),
        'summary': f"开发者画像: {profile_type}（{len(tags)} 个特征标签）",
    }


def _format_style_report(style: Dict[str, Any], profile: Dict[str, Any]) -> str:
    """格式化风格分析报告为可读文本"""
    lines = []
    lines.append("📊 代码风格分析报告")
    lines.append("=" * 40)

    naming = style.get('naming', {})
    lines.append(f"\n命名风格: {naming.get('dominant', '未知')}")
    lines.append(f"  snake_case: {naming.get('snake_ratio', 0):.0%} | camelCase: {naming.get('camel_ratio', 0):.0%} | PascalCase: {naming.get('pascal_ratio', 0):.0%}")

    indent = style.get('indent', {})
    lines.append(f"\n缩进偏好: {indent.get('dominant', '未知')} (一致性 {indent.get('consistency', 0):.0%})")

    comments = style.get('comments', {})
    lines.append(f"\n注释密度: {comments.get('comment_density', 0):.1%}")
    lines.append(f"  代码行: {comments.get('code_lines', 0)} | 注释行: {comments.get('comment_lines', 0)} | 文档行: {comments.get('docstring_lines', 0)} | 空行: {comments.get('blank_lines', 0)}")

    funcs = style.get('functions', {})
    lines.append(f"\n函数统计: {funcs.get('count', 0)} 个")
    lines.append(f"  平均长度: {funcs.get('avg_length', 0)} 行 | 最长: {funcs.get('max_length', 0)} 行 | 平均参数: {funcs.get('avg_args', 0)} 个")
    if funcs.get('long_functions', 0):
        lines.append(f"  ⚠ 超长函数(>50行): {funcs['long_functions']} 个")

    classes = style.get('classes', {})
    lines.append(f"\n类统计: {classes.get('count', 0)} 个")

    patterns = style.get('design_patterns', [])
    if patterns:
        lines.append(f"\n设计模式:")
        for p in patterns[:5]:
            lines.append(f"  {p['pattern']}: {p['count']} 处")

    scale = style.get('scale', {})
    lines.append(f"\n代码规模: {scale.get('total_lines', 0)} 行 ({scale.get('total_chars', 0)} 字符)")

    lines.append("\n" + "=" * 40)
    lines.append(f"👤 {profile.get('summary', '')}")
    tag_labels = [f"#{t['label']}" for t in profile.get('tags', [])]
    if tag_labels:
        lines.append(f"标签云: {' '.join(tag_labels)}")

    return '\n'.join(lines)


# ============================================================
# 可视化卡片 — 意图饼图 + 风格雷达图 + 标签云
# ============================================================

# 意图配色（与 INTENT_CATEGORIES 对应）
_INTENT_COLORS = {
    'data_processing': '#4FC3F7',
    'api_service': '#81C784',
    'automation': '#FFB74D',
    'testing': '#BA68C8',
    'visualization': '#4DD0E1',
    'security': '#E57373',
    'infrastructure': '#A1887F',
}
# 雷达图维度配色
_RADAR_COLOR = '#7E57C2'
_RADAR_FILL = 'rgba(126, 87, 194, 0.25)'
# 标签云配色（按权重）
_TAG_COLORS = [
    'Lemon.ACCENT_RED', '#FF8E53', '#FFA94D', 'Lemon.STATUS_WARNING',
    '#A9E34B', 'Lemon.ACCENT_GREEN', '#38D9A9', '#3BC9DB',
    'Lemon.ACCENT_BLUE', '#748FFC', '#9775FA', '#DA77F2',
]


def _render_intent_pie_svg(intents: List[Dict], size: int = 220) -> str:
    """渲染意图分布饼图为 SVG（内联，无需外部依赖）"""
    if not intents:
        return "<div style='color:#888;font-size:12px;'>无意图数据</div>"

    cx = cy = size / 2
    r = size / 2 - 10
    total = sum(i.get('confidence', 0) for i in intents) or 1.0
    start_angle = -90.0  # 从 12 点钟方向开始

    slices = []
    labels = []
    for idx, it in enumerate(intents):
        conf = it.get('confidence', 0)
        sweep = (conf / total) * 360.0
        end_angle = start_angle + sweep
        # 计算 SVG arc 路径
        import math as _m
        a1 = _m.radians(start_angle)
        a2 = _m.radians(end_angle)
        x1 = cx + r * _m.cos(a1)
        y1 = cy + r * _m.sin(a1)
        x2 = cx + r * _m.cos(a2)
        y2 = cy + r * _m.sin(a2)
        large = 1 if sweep > 180 else 0
        color = _INTENT_COLORS.get(it.get('intent', ''), '#999')
        path = (
            f"M {cx:.1f},{cy:.1f} "
            f"L {x1:.1f},{y1:.1f} "
            f"A {r:.1f},{r:.1f} 0 {large} 1 {x2:.1f},{y2:.1f} Z"
        )
        slices.append(
            f"<path d='{path}' fill='{color}' stroke='Lemon.DARK_MID_3' stroke-width='1.5' opacity='0.92'/>"
        )
        # 图例
        verified = it.get('verified')
        ai_only = it.get('ai_only')
        tag = '✓' if verified else ('AI' if ai_only else '')
        labels.append(
            f"<g transform='translate({size + 12}, {20 + idx * 22})'>"
            f"<rect width='14' height='14' rx='3' fill='{color}'/>"
            f"<text x='20' y='11' font-size='11' fill='#ddd' font-family='sans-serif'>"
            f"{it.get('icon','')} {it.get('name','')} {conf:.0%} {tag}</text>"
            f"</g>"
        )
        start_angle = end_angle

    legend_width = 180
    total_w = size + legend_width
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{total_w}' height='{size}' "
        f"viewBox='0 0 {total_w} {size}'>"
        f"<rect width='{total_w}' height='{size}' fill='Lemon.DARK_BG_4' rx='6'/>"
        f"<text x='{size/2}' y='16' text-anchor='middle' font-size='11' fill='#aaa' font-family='sans-serif'>意图分布</text>"
        + ''.join(slices)
        + ''.join(labels)
        + "</svg>"
    )
    return svg


def _render_style_radar_svg(style: Dict[str, Any], size: int = 240) -> str:
    """渲染代码风格雷达图为 SVG
    
    六个维度：命名一致性、缩进一致性、注释密度、函数简洁度、模块化、设计模式丰富度
    """
    import math as _m

    # 提取六维数据（归一化到 0~1）
    naming = style.get('naming', {})
    naming_consistency = max(
        naming.get('snake_ratio', 0),
        naming.get('camel_ratio', 0),
        naming.get('pascal_ratio', 0),
    )

    indent = style.get('indent', {})
    indent_consistency = indent.get('consistency', 0)

    comments = style.get('comments', {})
    comment_density = min(comments.get('comment_density', 0) * 3, 1.0)  # 0~33% 映射到 0~1

    funcs = style.get('functions', {})
    avg_len = funcs.get('avg_length', 0)
    # 函数越短越简洁：<=10行=1.0，>=50行=0.0
    func_conciseness = max(0.0, min(1.0, (50 - avg_len) / 40)) if avg_len > 0 else 0.5

    classes = style.get('classes', {})
    func_count = funcs.get('count', 0)
    class_count = classes.get('count', 0)
    # 模块化：有类且函数数适中 → 高分
    modularization = min(1.0, (class_count * 0.3 + min(func_count, 10) * 0.07))

    patterns = style.get('design_patterns', [])
    pattern_richness = min(1.0, len(patterns) * 0.25)

    dims = [
        ('命名一致', naming_consistency),
        ('缩进一致', indent_consistency),
        ('注释密度', comment_density),
        ('函数简洁', func_conciseness),
        ('模块化', modularization),
        ('设计模式', pattern_richness),
    ]

    cx = cy = size / 2
    r = size / 2 - 30
    n = len(dims)

    # 网格圆（4 层）
    grid = []
    for layer in range(1, 5):
        rr = r * layer / 4
        pts = []
        for i in range(n):
            ang = -_m.pi / 2 + 2 * _m.pi * i / n
            pts.append(f"{cx + rr * _m.cos(ang):.1f},{cy + rr * _m.sin(ang):.1f}")
        grid.append(
            f"<polygon points='{' '.join(pts)}' fill='none' stroke='#333' stroke-width='0.8' opacity='0.6'/>"
        )

    # 轴线 + 标签
    axes = []
    labels = []
    for i, (label, _) in enumerate(dims):
        ang = -_m.pi / 2 + 2 * _m.pi * i / n
        x = cx + r * _m.cos(ang)
        y = cy + r * _m.sin(ang)
        axes.append(f"<line x1='{cx:.1f}' y1='{cy:.1f}' x2='{x:.1f}' y2='{y:.1f}' stroke='#444' stroke-width='0.8'/>")
        lx = cx + (r + 14) * _m.cos(ang)
        ly = cy + (r + 14) * _m.sin(ang)
        labels.append(
            f"<text x='{lx:.1f}' y='{ly:.1f}' text-anchor='middle' dominant-baseline='middle' "
            f"font-size='10' fill='#bbb' font-family='sans-serif'>{label}</text>"
        )

    # 数据多边形
    data_pts = []
    for i, (_, val) in enumerate(dims):
        ang = -_m.pi / 2 + 2 * _m.pi * i / n
        rr = r * max(0.0, min(1.0, val))
        data_pts.append(f"{cx + rr * _m.cos(ang):.1f},{cy + rr * _m.sin(ang):.1f}")
    polygon = (
        f"<polygon points='{' '.join(data_pts)}' "
        f"fill='{_RADAR_FILL}' stroke='{_RADAR_COLOR}' stroke-width='2'/>"
    )
    # 数据点
    dots = []
    for i, (_, val) in enumerate(dims):
        ang = -_m.pi / 2 + 2 * _m.pi * i / n
        rr = r * max(0.0, min(1.0, val))
        dots.append(
            f"<circle cx='{cx + rr * _m.cos(ang):.1f}' cy='{cy + rr * _m.sin(ang):.1f}' "
            f"r='3' fill='{_RADAR_COLOR}'/>"
        )

    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' "
        f"viewBox='0 0 {size} {size}'>"
        f"<rect width='{size}' height='{size}' fill='Lemon.DARK_BG_4' rx='6'/>"
        f"<text x='{size/2}' y='16' text-anchor='middle' font-size='11' fill='#aaa' font-family='sans-serif'>代码风格雷达</text>"
        + ''.join(grid)
        + ''.join(axes)
        + polygon
        + ''.join(dots)
        + ''.join(labels)
        + "</svg>"
    )
    return svg


def _render_tag_cloud_svg(profile: Dict[str, Any], width: int = 360, height: int = 140) -> str:
    """渲染开发者画像标签云为 SVG"""
    tags = profile.get('tags', [])
    if not tags:
        return "<div style='color:#888;font-size:12px;'>无画像标签</div>"

    # 按权重排序，最大权重的标签字号最大
    sorted_tags = sorted(tags, key=lambda t: -t.get('weight', 1))
    max_w = max((t.get('weight', 1) for t in sorted_tags), default=1)
    min_w = min((t.get('weight', 1) for t in sorted_tags), default=1)
    span = max(max_w - min_w, 0.001)

    # 简单流式布局：从左到右排，超出宽度换行
    elements = []
    x = 12
    y = 28
    line_h = 28
    for idx, t in enumerate(sorted_tags):
        w = t.get('weight', 1)
        # 字号 12~22
        fs = 12 + int(10 * (w - min_w) / span)
        label = t.get('label', '')
        color = _TAG_COLORS[idx % len(_TAG_COLORS)]
        # 估算文字宽度（粗略：字号 × 字符数 × 0.6）
        tw = len(label) * fs * 0.62 + 18
        if x + tw > width - 12:
            x = 12
            y += line_h
        elements.append(
            f"<g transform='translate({x}, {y})'>"
            f"<rect width='{tw:.0f}' height='{fs + 8}' rx='{(fs+8)/2}' fill='{color}' opacity='0.18'/>"
            f"<text x='{tw/2:.0f}' y='{fs - 1}' text-anchor='middle' font-size='{fs}' "
            f"fill='{color}' font-family='sans-serif' font-weight='600'>#{label}</text>"
            f"</g>"
        )
        x += tw + 6

    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}'>"
        f"<rect width='{width}' height='{height}' fill='Lemon.DARK_BG_4' rx='6'/>"
        f"<text x='{width/2}' y='16' text-anchor='middle' font-size='11' fill='#aaa' font-family='sans-serif'>开发者画像标签云</text>"
        + ''.join(elements)
        + "</svg>"
    )
    return svg


def _render_visualization_card(
    intents: List[Dict],
    style: Dict[str, Any],
    profile: Dict[str, Any],
) -> str:
    """组合可视化卡片：饼图 + 雷达图 + 标签云（HTML 卡片）"""
    pie_svg = _render_intent_pie_svg(intents)
    radar_svg = _render_style_radar_svg(style)
    tag_svg = _render_tag_cloud_svg(profile)

    card = f"""<div style="font-family:sans-serif;background:#16161e;border:1px solid Lemon.DARK_BG_4;border-radius:10px;padding:14px;margin:8px 0;">
  <div style="color:#9fa6ff;font-size:13px;font-weight:600;margin-bottom:10px;">🎨 代码心理分析可视化</div>
  <div style="display:flex;flex-wrap:wrap;gap:10px;">
    <div style="background:Lemon.DARK_BG_4;border-radius:6px;padding:6px;">{pie_svg}</div>
    <div style="background:Lemon.DARK_BG_4;border-radius:6px;padding:6px;">{radar_svg}</div>
  </div>
  <div style="background:Lemon.DARK_BG_4;border-radius:6px;padding:6px;margin-top:10px;">{tag_svg}</div>
</div>"""
    return card


def execute(
    mode: str = "forward",
    code: str = "",
    description: str = "",
    **kwargs,
) -> SkillResult:
    """代码心理分析

    Args:
        mode: forward(描述→代码)/reverse(代码→意图)
        code: 代码（reverse 模式）
        description: 描述（forward 模式）
    """
    try:
        # ★ 396B-1: 参数自纠 —— 只给 code 不给 description 时自动视为 reverse
        #   （三连 MISS 实证：模型常省略 mode，缺省 forward 会把分析题跑成生成题）
        if mode == "forward" and code and not description:
            mode = "reverse"
        if mode == 'reverse':
            if not code:
                return SkillResult(success=False, error="reverse 模式需要 code 参数")

            # 分析代码意图 — 双路验证（规则引擎 + AI 语义分析）
            intents = _classify_intent_dual_path(code, description)

            # 提取代码结构
            structure = {'functions': [], 'classes': [], 'imports': []}
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        structure['functions'].append(node.name)
                    elif isinstance(node, ast.ClassDef):
                        structure['classes'].append(node.name)
                    elif isinstance(node, (ast.Import, ast.ImportFrom)):
                        for alias in node.names if hasattr(node, 'names') else []:
                            structure['imports'].append(alias.name)
            except SyntaxError:
                pass

            # 代码风格分析 + 开发者画像
            style = _analyze_code_style(code)
            profile = _build_developer_profile(style)
            style_report = _format_style_report(style, profile)

            primary = intents[0] if intents else {'intent': 'unknown', 'name': '未知', 'icon': '❓', 'confidence': 0}
            verified_tag = ""
            if primary.get('verified'):
                verified_tag = " ✓双路验证"
            elif primary.get('ai_only'):
                verified_tag = " (AI分析)"

            output = f"🧠 代码心理分析（逆向）\n\n"
            output += f"主要意图: {primary['icon']} {primary['name']} (置信度 {primary['confidence']:.1%}){verified_tag}\n\n"
            output += f"意图分析:\n"
            for i in intents:
                tag = ""
                if i.get('verified'):
                    tag = " ✓"
                elif i.get('ai_only'):
                    tag = " (AI)"
                output += f"  {i['icon']} {i['name']}: {i['confidence']:.1%}{tag}\n"
            output += f"\n代码结构:\n"
            output += f"  函数: {', '.join(structure['functions'][:10]) or '无'}\n"
            output += f"  类: {', '.join(structure['classes'][:10]) or '无'}\n"
            output += f"  导入: {', '.join(structure['imports'][:10]) or '无'}\n"
            output += f"\n{style_report}\n"

            # ★ 人性化设计：可视化卡片（意图饼图 + 风格雷达图 + 标签云）
            vis_card = _render_visualization_card(intents, style, profile)

            return SkillResult(
                success=True,
                output=output,
                data={
                    'mode': 'reverse', 'intents': intents, 'structure': structure,
                    'style': style, 'profile': profile,
                    'visualization': vis_card,
                },
            )

        elif mode == 'forward':
            if not description:
                return SkillResult(success=False, error="forward 模式需要 description 参数")

            # 推断意图 — 双路验证（规则引擎 + AI 深度分析），深度语义而非简单分类
            intents = _classify_intent_dual_path(description, description)
            primary_intent = intents[0]['intent'] if intents else 'automation'

            # 生成代码框架
            framework = _generate_framework(description, primary_intent)
            primary = intents[0] if intents else {'icon': '⚙️', 'name': '自动化', 'confidence': 0.5}
            verified_tag = ""
            if primary.get('verified'):
                verified_tag = " ✓双路验证"
            elif primary.get('ai_only'):
                verified_tag = " (AI分析)"

            output = f"🧠 代码心理分析（正向）\n\n"
            output += f"推断意图: {primary['icon']} {primary['name']} (置信度 {primary['confidence']:.1%}){verified_tag}\n\n"
            output += f"意图分析:\n"
            for i in intents:
                tag = ""
                if i.get('verified'):
                    tag = " ✓"
                elif i.get('ai_only'):
                    tag = " (AI)"
                output += f"  {i['icon']} {i['name']}: {i['confidence']:.1%}{tag}\n"
            output += f"\n生成的代码框架:\n```python\n{framework}\n```"

            # ★ 人性化设计：意图分布饼图（forward 模式仅有意图，无源码风格）
            vis_card = _render_intent_pie_svg(intents)

            return SkillResult(
                success=True,
                output=output,
                data={
                    'mode': 'forward', 'framework': framework, 'intents': intents,
                    'primary_intent': primary_intent,
                    'visualization': vis_card,
                },
            )

        else:
            return SkillResult(success=False, error=f"未知模式: {mode}，可选: forward/reverse")

    except Exception as e:
        return SkillResult(success=False, error=f"代码心理分析失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="code_psychologist",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["forward", "reverse"], "description": "模式: reverse=分析代码意图(分析/思路类问题用这个) / forward=描述→代码框架", "default": "forward"},
                "code": {"type": "string", "description": "要分析的代码原文（reverse 模式必填，把用户的代码完整粘入本参数，参数名是 code 不是 code_snippet）"},
                "description": {"type": "string", "description": "功能描述（仅 forward 模式用；reverse 模式不要传此参数）"},
                "language": {"type": "string", "description": "代码语言（如 python），可选", "default": "python"},
            },
        },
        handler=execute,
        category=METADATA["category"],
        timeout=15,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
