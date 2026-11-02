# -*- coding: utf-8 -*-
"""
Skill: code_playback — TRAE风格代码回放 (v1.0.0)
=================================================
将代码变更以打字动画方式在星空HUD中回放，类似TRAE编辑器体验。

支持：
  - diff     显示文件diff（新增绿/删除红/不变灰）
  - playback 逐行打字动画回放代码变更
  - snapshot 显示文件快照（当前内容）

优雅降级：
  - 文件不存在时返回提示
  - 编码错误时安全回退
"""

import os
import html as _html
import difflib
import time
from typing import Dict, Any, Optional, List

import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "code_playback",
    "description": "TRAE风格代码回放：代码变更diff展示、逐行打字动画、文件快照，星空HUD沉浸式体验",
    "category": "code",
    "version": "1.0.0",
}

def _esc(text: Any) -> str:
    return _html.escape(str(text), quote=True)

def _hud_text_shadow() -> str:
    return "text-shadow:0 0 12px rgba(5,5,8,0.95),0 1px 3px rgba(0,0,0,0.8)"

def _read_file_safe(path: str) -> Optional[str]:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    return None

def _render_diff_hud(file_path: str, old_content: str, new_content: str, description: str = "") -> str:
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = list(difflib.ndiff(old_lines, new_lines))
    added = 0
    removed = 0
    line_htmls = []
    for d in diff:
        if d.startswith("+ "):
            added += 1
            line_htmls.append(
                '<div class="cp-line cp-line-add">'
                '<span class="cp-gutter">+</span>'
                '<span class="cp-code">' + _esc(d[2:]) + '</span>'
                '</div>'
            )
        elif d.startswith("- "):
            removed += 1
            line_htmls.append(
                '<div class="cp-line cp-line-remove">'
                '<span class="cp-gutter">-</span>'
                '<span class="cp-code">' + _esc(d[2:]) + '</span>'
                '</div>'
            )
        elif d.startswith("? "):
            continue
        else:
            line_htmls.append(
                '<div class="cp-line cp-line-same">'
                '<span class="cp-gutter">&nbsp;</span>'
                '<span class="cp-code">' + _esc(d[2:]) + '</span>'
                '</div>'
            )
    lines_html = "".join(line_htmls)
    fname = os.path.basename(file_path)
    return (
        '<div class="cp-hud" style="padding:16px 12px 8px;pointer-events:auto;">'
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">'
        '<span style="font-size:14px;font-weight:600;color:Lemon.ACCENT_BLUE;' + _hud_text_shadow() + '">' + _esc(fname) + '</span>'
        '<span style="font-size:10px;color:rgba(255,255,255,0.4);">+' + str(added) + ' -' + str(removed) + '</span>'
        '</div>'
        + ('<div style="font-size:11px;color:rgba(255,255,255,0.4);margin-bottom:6px;">' + _esc(description) + '</div>' if description else '')
        + '<div class="cp-diff">' + lines_html + '</div>'
        + '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;">'
        + _cp_btn("回放", "playback:" + _esc(file_path))
        + _cp_btn("快照", "snapshot:" + _esc(file_path))
        + '</div>'
        + '</div>'
    )

def _render_playback_hud(file_path: str, content: str, description: str = "") -> str:
    lines = content.split("\n")
    fname = os.path.basename(file_path)
    lines_json = []
    for i, line in enumerate(lines):
        lines_json.append('{"n":' + str(i+1) + ',"t":' + _html.escape(json_str(line), quote=True) + '}')
    lines_js = "[" + ",".join(lines_json) + "]"
    canvas_id = f"cpb_{fname.replace('.','_')}_{int(time.time()*1000)}"
    return (
        '<div class="cp-hud" style="padding:16px 12px 8px;pointer-events:auto;">'
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">'
        '<span style="font-size:14px;font-weight:600;color:Lemon.ACCENT_GREEN;' + _hud_text_shadow() + '">' + _esc(fname) + ' 回放</span>'
        '<span style="font-size:10px;color:rgba(255,255,255,0.4);">' + str(len(lines)) + ' lines</span>'
        '</div>'
        + ('<div style="font-size:11px;color:rgba(255,255,255,0.4);margin-bottom:6px;">' + _esc(description) + '</div>' if description else '')
        + '<div class="cp-playback" id="' + canvas_id + '"></div>'
        + '<script>(function(){'
        + 'var el=document.getElementById("' + canvas_id + '");'
        + 'if(!el)return;'
        + 'var lines=' + lines_js + ';'
        + 'var idx=0,speed=40,running=true;'
        + 'function typeLine(){'
        + 'if(idx>=lines.length||!running){running=false;return;}'
        + 'var ln=lines[idx];'
        + 'var div=document.createElement("div");div.className="cp-line cp-line-playback";'
        + 'var gut=document.createElement("span");gut.className="cp-gutter";gut.textContent=ln.n;'
        + 'var code=document.createElement("span");code.className="cp-code";'
        + 'div.appendChild(gut);div.appendChild(code);el.appendChild(div);'
        + 'var text=ln.t,charIdx=0;'
        + 'function typeChar(){if(charIdx<text.length&&running){code.textContent+=text[charIdx];charIdx++;setTimeout(typeChar,speed);}else{idx++;setTimeout(typeLine,20);}};'
        + 'typeChar();'
        + '};'
        + 'typeLine();'
        + 'el.addEventListener("dblclick",function(){if(running){running=false;var rem=lines.slice(idx);for(var i=0;i<rem.length;i++){var d=document.createElement("div");d.className="cp-line cp-line-playback";var g=document.createElement("span");g.className="cp-gutter";g.textContent=rem[i].n;var c=document.createElement("span");c.className="cp-code";c.textContent=rem[i].t;d.appendChild(g);d.appendChild(c);el.appendChild(d);}idx=lines.length;}});'
        + '})();</script>'
        + '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;">'
        + '<span style="font-size:10px;color:rgba(255,255,255,0.3);">双击跳过动画</span>'
        + '</div>'
        + '</div>'
    )

def json_str(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'

def _render_snapshot_hud(file_path: str, content: str) -> str:
    lines = content.split("\n")
    fname = os.path.basename(file_path)
    line_htmls = []
    for i, line in enumerate(lines):
        num = str(i + 1)
        line_htmls.append(
            '<div class="cp-line cp-line-snapshot">'
            '<span class="cp-gutter">' + _esc(num) + '</span>'
            '<span class="cp-code">' + _esc(line) + '</span>'
            '</div>'
        )
    lines_html = "".join(line_htmls)
    return (
        '<div class="cp-hud" style="padding:16px 12px 8px;pointer-events:auto;">'
        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">'
        '<span style="font-size:14px;font-weight:600;color:Lemon.DIVIDER;' + _hud_text_shadow() + '">' + _esc(fname) + '</span>'
        '<span style="font-size:10px;color:rgba(255,255,255,0.4);">' + str(len(lines)) + ' lines</span>'
        '</div>'
        '<div class="cp-snapshot">' + lines_html + '</div>'
        + '</div>'
    )

def _cp_btn(label: str, action: str) -> str:
    return (
        '<button class="fin-hud-btn" onclick="window._callPython(\'codePlaybackAction\',\'' + action + '\')" '
        'style="background:rgba(8,8,12,0.75);border:1px solid rgba(255,255,255,0.08);'
        'color:rgba(255,255,255,0.7);padding:3px 10px;border-radius:4px;font-size:11px;'
        'cursor:pointer;backdrop-filter:blur(6px);transition:all 0.2s;pointer-events:auto;" '
        'onmouseover="this.style.background=\'rgba(255,105,0,0.12)\';this.style.color=\'Lemon.BRAND_ORANGE_LIGHT\'" '
        'onmouseout="this.style.background=\'rgba(8,8,12,0.75)\';this.style.color=\'rgba(255,255,255,0.7)\'"'
        '>' + label + '</button>'
    )

def execute(
    action: str = "diff",
    file_path: str = "",
    old_content: str = "",
    new_content: str = "",
    description: str = "",
    **kwargs,
) -> SkillResult:
    action = (action or "").lower().strip()
    if not file_path:
        return SkillResult(success=False, error="需要 file_path 参数")

    if action == "diff":
        if not old_content and not new_content:
            return SkillResult(success=False, error="diff 操作需要 old_content 和 new_content")
        hud_html = _render_diff_hud(file_path, old_content, new_content, description)
        return SkillResult(success=True, output=hud_html, data={"action": "diff"})

    elif action == "playback":
        content = new_content or _read_file_safe(file_path)
        if content is None:
            return SkillResult(success=False, error=f"文件不存在: {file_path}")
        hud_html = _render_playback_hud(file_path, content, description)
        return SkillResult(success=True, output=hud_html, data={"action": "playback"})

    elif action == "snapshot":
        content = _read_file_safe(file_path)
        if content is None:
            return SkillResult(success=False, error=f"文件不存在: {file_path}")
        hud_html = _render_snapshot_hud(file_path, content)
        return SkillResult(success=True, output=hud_html, data={"action": "snapshot"})

    return SkillResult(success=False, error=f"未知 action: {action}（支持: diff/playback/snapshot）")


def register(registry) -> None:
    registry.register(SkillDef(
        name="code_playback",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型",
                    "enum": ["diff", "playback", "snapshot"],
                },
                "file_path": {"type": "string", "description": "文件路径"},
                "old_content": {"type": "string", "description": "旧内容（diff用）"},
                "new_content": {"type": "string", "description": "新内容（diff/playback用）"},
                "description": {"type": "string", "description": "变更描述"},
            },
            "required": ["action", "file_path"],
        },
        handler=execute,
        category=METADATA["category"],
        requires_confirm=False,
        timeout=30,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
