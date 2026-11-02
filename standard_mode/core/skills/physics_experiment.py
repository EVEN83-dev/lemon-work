# -*- coding: utf-8 -*-
"""
Skill: physics_experiment — 物理实验简笔画动画
===============================================
生成 Canvas JS 动画（黑板风格白线）：弹簧振子、单摆、
抛体运动、波传播、电路、万有引力轨道。
"""

import json
import os
import traceback
from typing import Dict, Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from skills_registry import SkillDef, SkillResult

METADATA = {
    "name": "physics_experiment",
    "description": "生成物理实验简笔画动画（Canvas JS）：弹簧振子、单摆、抛体运动、波传播、电路、万有引力轨道。黑板风格白线动画。",
    "category": "visual",
    "version": "1.0.0",
}


def _generate_spring_animation(params: dict) -> str:
    amplitude = params.get('amplitude', 100)
    frequency = params.get('frequency', 2)
    return f"""const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
ctx.strokeStyle = 'white'; ctx.lineWidth = 2;
let t = 0;
function draw() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const x = 200 + {amplitude} * Math.sin({frequency} * t);
  // 弹簧
  ctx.beginPath(); ctx.moveTo(50, 200);
  for (let i = 0; i < 20; i++) {{
    ctx.lineTo(50 + (x-50)*(i/20) + (i%2===0?10:-10), 190 + (i%2===0?10:-10));
  }}
  ctx.lineTo(x, 200); ctx.stroke();
  // 质量块
  ctx.strokeRect(x-15, 185, 30, 30);
  t += 0.03; requestAnimationFrame(draw);
}}
draw();"""


def _generate_pendulum_animation(params: dict) -> str:
    length = params.get('length', 150)
    gravity = params.get('gravity', 9.8)
    return f"""const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
ctx.strokeStyle = 'white'; ctx.lineWidth = 2;
let t = 0; const g = {gravity}; const L = {length};
function draw() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const theta = 0.5 * Math.cos(Math.sqrt(g/L*100) * t * 0.01);
  const px = 250 + L * Math.sin(theta);
  const py = 50 + L * Math.cos(theta);
  ctx.beginPath(); ctx.moveTo(250, 50); ctx.lineTo(px, py); ctx.stroke();
  ctx.beginPath(); ctx.arc(px, py, 12, 0, Math.PI*2); ctx.stroke();
  t += 1; requestAnimationFrame(draw);
}}
draw();"""


def _generate_projectile_animation(params: dict) -> str:
    v0 = params.get('velocity', 50)
    angle = params.get('angle', 45)
    return f"""const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
ctx.strokeStyle = 'white'; ctx.lineWidth = 2;
let t = 0; const g = 9.8; const v = {v0}; const a = {angle} * Math.PI / 180;
const vx = v * Math.cos(a); const vy = v * Math.sin(a);
const trail = [];
function draw() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const x = 50 + vx * t; const y = 350 - (vy * t - 0.5 * g * t * t);
  if (y > 350 || t > 15) {{ t = 0; trail.length = 0; }}
  trail.push({{x, y}}); if (trail.length > 200) trail.shift();
  ctx.beginPath(); trail.forEach((p,i) => i===0?ctx.moveTo(p.x,p.y):ctx.lineTo(p.x,p.y)); ctx.stroke();
  ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI*2); ctx.stroke();
  t += 0.05; requestAnimationFrame(draw);
}}
draw();"""


def _generate_wave_animation(params: dict) -> str:
    wavelength = params.get('wavelength', 60)
    speed = params.get('speed', 2)
    return f"""const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
ctx.strokeStyle = 'white'; ctx.lineWidth = 2;
let t = 0;
function draw() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.beginPath();
  for (let x = 0; x < 500; x++) {{
    const y = 200 + 50 * Math.sin(2 * Math.PI * x / {wavelength} - {speed} * t);
    x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }}
  ctx.stroke();
  t += 0.05; requestAnimationFrame(draw);
}}
draw();"""


def _generate_orbit_animation(params: dict) -> str:
    return """const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
ctx.strokeStyle = 'white'; ctx.lineWidth = 2;
let t = 0;
function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const cx = 250, cy = 200;
  // Sun
  ctx.beginPath(); ctx.arc(cx, cy, 15, 0, Math.PI*2); ctx.stroke();
  // Planet orbit
  const r = 120; const angle = t * 0.02;
  const px = cx + r * Math.cos(angle);
  const py = cy + r * 0.6 * Math.sin(angle);
  ctx.beginPath(); ctx.ellipse(cx, cy, r, r*0.6, 0, 0, Math.PI*2); ctx.stroke();
  ctx.beginPath(); ctx.arc(px, py, 6, 0, Math.PI*2); ctx.stroke();
  t += 1; requestAnimationFrame(draw);
}
draw();"""


ANIMATION_GENERATORS = {
    'spring': _generate_spring_animation,
    'pendulum': _generate_pendulum_animation,
    'projectile': _generate_projectile_animation,
    'wave': _generate_wave_animation,
    'orbit': _generate_orbit_animation,
}


def execute(
    experiment: str = "spring",
    params: str = "{}",
    output_path: str = "",
    title: str = "",
) -> SkillResult:
    """生成物理实验动画 HTML"""
    if experiment not in ANIMATION_GENERATORS:
        return SkillResult(success=False, error=f"未知实验类型: {experiment}，可选: {list(ANIMATION_GENERATORS.keys())}")

    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError:
        p = {}

    try:
        js_code = ANIMATION_GENERATORS[experiment](p)
        exp_title = title or {'spring': '弹簧振子', 'pendulum': '单摆', 'projectile': '抛体运动',
                              'wave': '波传播', 'orbit': '万有引力轨道'}.get(experiment, experiment)

        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{exp_title}</title>
<style>body{{background:Lemon.DARK_MID_5;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}}
canvas{{background:#222;border:2px solid #444;border-radius:8px}}</style></head>
<body><canvas id="canvas" width="500" height="400"></canvas>
<script>{js_code}</script></body></html>"""

        if output_path:
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html)

        return SkillResult(
            success=True,
            output=f"物理实验动画已生成: {exp_title}\n类型: {experiment}",
            data={'html': html, 'experiment': experiment, 'title': exp_title, 'path': output_path},
        )
    except Exception as e:
        return SkillResult(success=False, error=f"物理实验动画生成失败: {e}", output=traceback.format_exc())


def register(registry) -> None:
    registry.register(SkillDef(
        name="physics_experiment",
        description=METADATA["description"],
        parameters={
            "type": "object",
            "properties": {
                "experiment": {"type": "string", "enum": ["spring", "pendulum", "projectile", "wave", "orbit"], "description": "实验类型"},
                "params": {"type": "string", "description": "JSON 实验参数", "default": "{}"},
                "output_path": {"type": "string", "description": "输出 HTML 路径"},
                "title": {"type": "string", "description": "动画标题"},
            },
            "required": ["experiment"],
        },
        handler=execute,
        category=METADATA["category"],
        timeout=15,
    ))


def get_metadata() -> Dict[str, Any]:
    return METADATA
