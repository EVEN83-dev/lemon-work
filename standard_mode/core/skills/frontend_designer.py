# -*- coding: utf-8 -*-
"""
Skill: frontend_designer — 前端设计助手
========================================
生成 HTML/CSS 组件代码。支持卡片、按钮、导航栏、表单、
仪表盘、Hero、页脚、表格、完整页面共9种组件。
"""

import json
import os
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "frontend_designer",
    "description": "前端设计助手：生成 HTML/CSS 组件代码。支持卡片、按钮、导航栏、表单、仪表盘、Hero、页脚、表格、完整页面共9种组件。",
    "category": "visual",
    "version": "1.0.0",
}


def _generate_card(params: dict) -> str:
    title = params.get('title', '卡片标题')
    content = params.get('content', '卡片内容描述')
    return f"""<div style="max-width:350px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.1);overflow:hidden;font-family:sans-serif">
  <div style="background:linear-gradient(135deg,Lemon.ACCENT_BLUE,#764ba2);padding:24px;color:white">
    <h3 style="margin:0">{title}</h3>
  </div>
  <div style="padding:20px"><p style="color:#555;line-height:1.6">{content}</p>
  <button style="background:Lemon.ACCENT_BLUE;color:white;border:none;padding:8px 20px;border-radius:6px;cursor:pointer">了解更多</button></div>
</div>"""


def _generate_button(params: dict) -> str:
    text = params.get('text', '点击按钮')
    variant = params.get('variant', 'primary')
    colors = {'primary': 'Lemon.ACCENT_BLUE', 'success': '#28a745', 'danger': '#dc3545', 'warning': 'Lemon.STATUS_WARNING'}
    bg = colors.get(variant, 'Lemon.ACCENT_BLUE')
    return f"""<button style="background:{bg};color:white;border:none;padding:10px 24px;border-radius:8px;font-size:16px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,0.15);transition:transform 0.2s"
  onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">{text}</button>"""


def _generate_navbar(params: dict) -> str:
    brand = params.get('brand', 'MyApp')
    items = params.get('items', ['首页', '功能', '关于'])
    links = ' '.join([f'<a href="#" style="color:white;text-decoration:none;margin:0 15px;font-size:14px">{i}</a>' for i in items])
    return f"""<nav style="background:linear-gradient(90deg,Lemon.DARK_MID_5,Lemon.DARK_BG_4);padding:15px 30px;display:flex;align-items:center;justify-content:space-between">
  <span style="color:Lemon.BRAND_ORANGE_LIGHT;font-size:22px;font-weight:bold">{brand}</span>
  <div>{links}</div>
</nav>"""


def _generate_form(params: dict) -> str:
    fields = params.get('fields', [{'name': 'username', 'label': '用户名', 'type': 'text'},
                                    {'name': 'email', 'label': '邮箱', 'type': 'email'},
                                    {'name': 'password', 'label': '密码', 'type': 'password'}])
    field_html = ''
    for f in fields:
        field_html += f"""<div style="margin-bottom:16px">
  <label style="display:block;margin-bottom:6px;font-weight:600;color:#333">{f.get('label', f.get('name', ''))}</label>
  <input type="{f.get('type', 'text')}" name="{f.get('name', '')}" style="width:100%;padding:10px 14px;border:1px solid #ddd;border-radius:8px;font-size:14px;box-sizing:border-box" placeholder="请输入{f.get('label', '')}">
</div>\n"""
    return f"""<form style="max-width:400px;padding:30px;background:white;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08)">{field_html}
<button type="submit" style="width:100%;background:Lemon.ACCENT_BLUE;color:white;border:none;padding:12px;border-radius:8px;font-size:16px;cursor:pointer">提交</button></form>"""


def _generate_hero(params: dict) -> str:
    title = params.get('title', '欢迎使用我们的产品')
    subtitle = params.get('subtitle', '一站式解决方案，助您高效工作')
    return f"""<div style="background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);padding:80px 40px;text-align:center;min-height:400px;display:flex;flex-direction:column;justify-content:center;align-items:center">
  <h1 style="color:white;font-size:48px;margin-bottom:20px">{title}</h1>
  <p style="color:#aaa;font-size:20px;max-width:600px;margin-bottom:40px">{subtitle}</p>
  <div><button style="background:Lemon.BRAND_ORANGE_LIGHT;color:white;border:none;padding:14px 32px;border-radius:8px;font-size:18px;cursor:pointer;margin:0 10px">立即开始</button>
  <button style="background:transparent;color:white;border:2px solid Lemon.BRAND_ORANGE_LIGHT;padding:14px 32px;border-radius:8px;font-size:18px;cursor:pointer;margin:0 10px">了解更多</button></div>
</div>"""


def _generate_table(params: dict) -> str:
    headers = params.get('headers', ['名称', '状态', '操作'])
    rows = params.get('rows', [['项目A', '进行中', '查看'], ['项目B', '已完成', '查看']])
    th = ''.join([f'<th style="padding:12px 16px;text-align:left;background:Lemon.DARK_BG_4;color:white;font-weight:600">{h}</th>' for h in headers])
    trs = ''
    for row in rows:
        tds = ''.join([f'<td style="padding:12px 16px;border-bottom:1px solid #eee">{c}</td>' for c in row])
        trs += f'<tr>{tds}</tr>'
    return f"""<table style="width:100%;border-collapse:collapse;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">
<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"""


def _generate_footer(params: dict) -> str:
    brand = params.get('brand', 'MyApp')
    return f"""<footer style="background:Lemon.DARK_MID_5;color:#aaa;padding:30px 40px;display:flex;justify-content:space-between;align-items:center">
  <span style="color:Lemon.BRAND_ORANGE_LIGHT;font-weight:bold">{brand}</span>
  <span>© 2024 All rights reserved.</span>
</footer>"""


def _generate_dashboard(params: dict) -> str:
    cards = params.get('cards', [{'title': '用户数', 'value': '12,345', 'change': '+5.2%'},
                                  {'title': '收入', 'value': '¥89,000', 'change': '+12.8%'},
                                  {'title': '订单', 'value': '456', 'change': '-2.1%'},
                                  {'title': '转化率', 'value': '3.6%', 'change': '+0.5%'}])
    card_html = ''
    for c in cards:
        color = '#28a745' if c.get('change', '').startswith('+') else '#dc3545'
        card_html += f"""<div style="background:white;padding:24px;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.08)">
  <p style="color:#888;font-size:14px;margin:0 0 8px 0">{c.get('title', '')}</p>
  <h2 style="font-size:28px;margin:0 0 4px 0">{c.get('value', '')}</h2>
  <span style="color:{color};font-size:14px">{c.get('change', '')}</span>
</div>"""
    return f"""<div style="background:#f5f7fa;padding:30px;min-height:100vh">
  <h2 style="margin:0 0 24px 0">仪表盘</h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px">{card_html}</div>
</div>"""


COMPONENT_GENERATORS = {
    'card': _generate_card,
    'button': _generate_button,
    'navbar': _generate_navbar,
    'form': _generate_form,
    'hero': _generate_hero,
    'table': _generate_table,
    'footer': _generate_footer,
    'dashboard': _generate_dashboard,
}


def execute(
    component_type: str = "card",
    params: str = "{}",
    output_path: str = "",
) -> SkillResult:
    """生成前端组件代码"""
    if component_type not in COMPONENT_GENERATORS:
        return SkillResult(success=False, error=f"未知组件类型: {component_type}，可选: {list(COMPONENT_GENERATORS.keys())}")

    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError:
        p = {}

    try:
        html = COMPONENT_GENERATORS[component_type](p)

        if component_type != 'dashboard':
            full_html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{component_type}</title></head>
<body style="margin:0;padding:40px;background:#f5f7fa;display:flex;justify-content:center;align-items:center;min-height:100vh">
{html}
</body></html>"""
        else:
            full_html = html

        if output_path:
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(full_html)

        # v3.82: 自动 UI 验证闭环
        verify_info = ""
        try:
            from core.ui_verifier import UIVerifier
            verifier = UIVerifier()
            verify_result = verifier.verify(
                output_path if output_path else full_html,
                f"{component_type} 前端组件正确渲染",
            )
            if verify_result.get("pass"):
                verify_info = f" [UI验证通过 score={verify_result.get('score', 0)}]"
            else:
                issues = verify_result.get("issues", [])
                verify_info = f" [UI验证未通过: {'; '.join(issues[:3])}]"
        except Exception:
            pass

        return SkillResult(
            success=True,
            output=f"前端组件已生成: {component_type}{verify_info}",
            data={'html': full_html, 'component': component_type},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"前端组件生成失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="frontend_designer",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "component_type": {"type": "string", "enum": ["card", "button", "navbar", "form", "dashboard", "hero", "footer", "table", "page"], "description": "组件类型"},
                "params": {"type": "string", "description": "JSON 组件参数", "default": "{}"},
                "output_path": {"type": "string", "description": "输出 HTML 文件路径"},
            },
            "required": ["component_type"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=15,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
