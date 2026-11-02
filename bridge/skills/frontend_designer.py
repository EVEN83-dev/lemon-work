import os
import re as _re
from .models import SkillResult, SkillDef

METADATA = {
    "name": "frontend_designer",
    "version": "2.0.0",
    "category": "development",
    "description": "Generate frontend UI code for HTML/Vue/React/ArkTS with layout computation and component scaffolding.",
}


def execute(
    description: str = "",
    framework: str = "html",
    style: str = "modern",
    **kwargs,
) -> SkillResult:
    if not description.strip():
        return SkillResult.fail("description is required")

    valid_frameworks = ("html", "vue", "react", "arkts")
    if framework not in valid_frameworks:
        return SkillResult.fail("Invalid framework '" + str(framework) + "'. Must be one of: " + str(valid_frameworks))

    valid_styles = ("modern", "minimal", "material")
    if style not in valid_styles:
        return SkillResult.fail("Invalid style '" + str(style) + "'. Must be one of: " + str(valid_styles))

    components = _parse_components(description)
    style_vars = _get_style_vars(style)

    if framework == "html":
        code = _generate_html(components, style_vars, description)
    elif framework == "vue":
        code = _generate_vue(components, style_vars, description)
    elif framework == "react":
        code = _generate_react(components, style_vars, description)
    elif framework == "arkts":
        code = _generate_arkts(components, style_vars, description)
    else:
        code = "<!-- unsupported framework -->"

    return SkillResult.ok(
        output="Generated " + framework + " code for: " + description + "\n\n" + code,
        data={
            "framework": framework,
            "style": style,
            "components": [c["name"] for c in components],
            "code": code,
        },
    )


def _parse_components(description: str) -> list:
    components = []
    keywords = {
        "header": {"name": "Header", "type": "header"},
        "navbar": {"name": "Navbar", "type": "nav"},
        "nav": {"name": "Nav", "type": "nav"},
        "sidebar": {"name": "Sidebar", "type": "sidebar"},
        "footer": {"name": "Footer", "type": "footer"},
        "form": {"name": "Form", "type": "form"},
        "login": {"name": "LoginForm", "type": "form"},
        "card": {"name": "Card", "type": "card"},
        "list": {"name": "List", "type": "list"},
        "table": {"name": "Table", "type": "table"},
        "button": {"name": "Button", "type": "button"},
        "input": {"name": "Input", "type": "input"},
        "modal": {"name": "Modal", "type": "modal"},
        "dialog": {"name": "Dialog", "type": "modal"},
        "tabs": {"name": "Tabs", "type": "tabs"},
        "chart": {"name": "Chart", "type": "chart"},
        "dashboard": {"name": "Dashboard", "type": "dashboard"},
        "search": {"name": "SearchBar", "type": "search"},
        "profile": {"name": "Profile", "type": "card"},
        "image": {"name": "ImageGallery", "type": "gallery"},
        "gallery": {"name": "Gallery", "type": "gallery"},
    }

    desc_lower = description.lower()
    found = set()
    for kw, comp in keywords.items():
        if kw in desc_lower and comp["type"] not in found:
            components.append(comp)
            found.add(comp["type"])

    if not components:
        components.append({"name": "MainContent", "type": "content"})

    return components


def _get_style_vars(style: str) -> dict:
    base = {
        "font_family": "system-ui, -apple-system, sans-serif",
        "border_radius": "8px",
        "transition": "all 0.2s ease",
    }
    if style == "modern":
        return {**base, "bg": "#ffffff", "fg": "#1a1a2e", "accent": "#6c5ce7",
                "muted": "#636e72", "border": "#dfe6e9", "card_bg": "#f8f9fa",
                "shadow": "0 2px 12px rgba(0,0,0,0.08)", "gradient": "linear-gradient(135deg, #6c5ce7, #a29bfe)"}
    elif style == "minimal":
        return {**base, "bg": "#fafafa", "fg": "#212121", "accent": "#212121",
                "muted": "#9e9e9e", "border": "#e0e0e0", "card_bg": "#ffffff",
                "shadow": "none", "gradient": "none"}
    elif style == "material":
        return {**base, "bg": "#fafafa", "fg": "#212121", "accent": "#1976d2",
                "muted": "#757575", "border": "#e0e0e0", "card_bg": "#ffffff",
                "shadow": "0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24)",
                "gradient": "linear-gradient(135deg, #1976d2, #42a5f5)"}
    return base


def _generate_html(components: list, sv: dict, desc: str) -> str:
    parts = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '  <title>' + desc[:50] + '</title>',
        '  <style>',
        '    * { margin: 0; padding: 0; box-sizing: border-box; }',
        '    body { font-family: ' + sv["font_family"] + '; background: ' + sv["bg"] + '; color: ' + sv["fg"] + '; }',
        '    .container { max-width: 1200px; margin: 0 auto; padding: 20px; }',
        '    .card { background: ' + sv["card_bg"] + '; border-radius: ' + sv["border_radius"] + '; box-shadow: ' + sv["shadow"] + '; padding: 24px; margin-bottom: 16px; }',
        '    .btn { background: ' + sv["accent"] + '; color: #fff; border: none; padding: 10px 20px; border-radius: ' + sv["border_radius"] + '; cursor: pointer; transition: ' + sv["transition"] + '; }',
        '    .btn:hover { opacity: 0.9; }',
        '    input, textarea { width: 100%; padding: 10px; border: 1px solid ' + sv["border"] + '; border-radius: ' + sv["border_radius"] + '; font-size: 14px; }',
        '    h1, h2, h3 { color: ' + sv["fg"] + '; margin-bottom: 12px; }',
        '  </style>',
        '</head>',
        '<body>',
        '  <div class="container">',
    ]

    for comp in components:
        if comp["type"] == "header":
            parts.append('    <header class="card"><h1>' + desc[:50] + '</h1></header>')
        elif comp["type"] == "nav":
            parts.append('    <nav class="card"><a href="#">Home</a> | <a href="#">About</a> | <a href="#">Contact</a></nav>')
        elif comp["type"] == "form":
            parts.append('    <div class="card"><h2>Form</h2><form><input type="text" placeholder="Enter value..." /><br><br><button class="btn" type="submit">Submit</button></form></div>')
        elif comp["type"] == "card":
            parts.append('    <div class="card"><h2>Card Title</h2><p>Card content goes here.</p><button class="btn">Action</button></div>')
        elif comp["type"] == "table":
            parts.append('    <div class="card"><h2>Data Table</h2><table style="width:100%;border-collapse:collapse;"><tr><th style="border:1px solid ' + sv["border"] + ';padding:8px;">Name</th><th style="border:1px solid ' + sv["border"] + ';padding:8px;">Value</th></tr><tr><td style="border:1px solid ' + sv["border"] + ';padding:8px;">Item 1</td><td style="border:1px solid ' + sv["border"] + ';padding:8px;">100</td></tr></table></div>')
        elif comp["type"] == "modal":
            parts.append('    <div class="card" id="modal" style="display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);"><h2>Modal</h2><p>Modal content</p><button class="btn" onclick="document.getElementById(\'modal\').style.display=\'none\'">Close</button></div>')
        elif comp["type"] == "footer":
            parts.append('    <footer class="card" style="text-align:center;color:' + sv["muted"] + ';">&copy; 2026 ' + desc[:30] + '</footer>')
        else:
            parts.append('    <div class="card"><h2>' + comp["name"] + '</h2><p>Content area for ' + comp["name"] + '.</p></div>')

    parts.append('  </div>')
    parts.append('</body>')
    parts.append('</html>')
    return '\n'.join(parts)


def _generate_vue(components: list, sv: dict, desc: str) -> str:
    template_parts = ['<template>', '  <div class="app">']
    for comp in components:
        if comp["type"] == "header":
            template_parts.append('    <header class="card"><h1>' + desc[:50] + '</h1></header>')
        elif comp["type"] == "nav":
            template_parts.append('    <nav class="card"><router-link to="/">Home</router-link> | <router-link to="/about">About</router-link></nav>')
        elif comp["type"] == "form":
            template_parts.append('    <div class="card"><h2>Form</h2><form @submit.prevent="handleSubmit"><input v-model="formData.input" placeholder="Enter value..." /><button type="submit" class="btn">Submit</button></form></div>')
        elif comp["type"] == "card":
            template_parts.append('    <div class="card"><h2>{{ title }}</h2><p>{{ content }}</p><button class="btn" @click="handleAction">Action</button></div>')
        else:
            template_parts.append('    <div class="card"><h2>' + comp["name"] + '</h2><slot /></div>')
    template_parts.append('  </div>')
    template_parts.append('</template>')

    script = (
        '<script setup>\n'
        'import { ref, reactive } from "vue"\n\n'
        'const title = ref("' + desc[:40] + '")\n'
        'const content = ref("Content goes here")\n'
        'const formData = reactive({ input: "" })\n\n'
        'function handleSubmit() {\n'
        '  console.log("Submitted:", formData)\n'
        '}\n\n'
        'function handleAction() {\n'
        '  console.log("Action triggered")\n'
        '}\n'
        '</script>'
    )

    style_block = (
        '<style scoped>\n'
        '.app { max-width: 1200px; margin: 0 auto; padding: 20px; font-family: ' + sv["font_family"] + '; }\n'
        '.card { background: ' + sv["card_bg"] + '; border-radius: ' + sv["border_radius"] + '; box-shadow: ' + sv["shadow"] + '; padding: 24px; margin-bottom: 16px; }\n'
        '.btn { background: ' + sv["accent"] + '; color: #fff; border: none; padding: 10px 20px; border-radius: ' + sv["border_radius"] + '; cursor: pointer; }\n'
        'input { width: 100%; padding: 10px; border: 1px solid ' + sv["border"] + '; border-radius: ' + sv["border_radius"] + '; }\n'
        '</style>'
    )

    return '\n\n'.join(['\n'.join(template_parts), script, style_block])


def _generate_react(components: list, sv: dict, desc: str) -> str:
    jsx_parts = [
        'import React, { useState } from "react";',
        '',
        'const styles = {',
        '  container: { maxWidth: "1200px", margin: "0 auto", padding: "20px", fontFamily: "' + sv["font_family"] + '" },',
        '  card: { background: "' + sv["card_bg"] + '", borderRadius: "' + sv["border_radius"] + '", boxShadow: "' + sv["shadow"] + '", padding: "24px", marginBottom: "16px" },',
        '  btn: { background: "' + sv["accent"] + '", color: "#fff", border: "none", padding: "10px 20px", borderRadius: "' + sv["border_radius"] + '", cursor: "pointer" },',
        '  input: { width: "100%", padding: "10px", border: "1px solid ' + sv["border"] + '", borderRadius: "' + sv["border_radius"] + '" },',
        '};',
        '',
        'export default function App() {',
        '  const [inputValue, setInputValue] = useState("");',
        '',
        '  return (',
        '    <div style={styles.container}>',
    ]
    for comp in components:
        if comp["type"] == "header":
            jsx_parts.append('      <header style={styles.card}><h1>' + desc[:50] + '</h1></header>')
        elif comp["type"] == "form":
            jsx_parts.append('      <div style={styles.card}><h2>Form</h2><input style={styles.input} value={inputValue} onChange={(e) => setInputValue(e.target.value)} placeholder="Enter value..." /><br/><button style={styles.btn} onClick={() => console.log(inputValue)}>Submit</button></div>')
        elif comp["type"] == "card":
            jsx_parts.append('      <div style={styles.card}><h2>' + comp["name"] + '</h2><p>Content goes here</p><button style={styles.btn}>Action</button></div>')
        else:
            jsx_parts.append('      <div style={styles.card}><h2>' + comp["name"] + '</h2><p>Content area</p></div>')
    jsx_parts.append('    </div>')
    jsx_parts.append('  );')
    jsx_parts.append('}')
    return '\n'.join(jsx_parts)


def _generate_arkts(components: list, sv: dict, desc: str) -> str:
    comp_vars = []
    build_parts = []
    for comp in components:
        var_name = comp["name"][0].lower() + comp["name"][1:]
        if comp["type"] == "header":
            comp_vars.append('  @State headerTitle: string = "' + desc[:40] + '"')
            build_parts.append('      Text(this.headerTitle).fontSize(24).fontWeight(FontWeight.Bold).padding(16)')
        elif comp["type"] == "form":
            comp_vars.append('  @State inputValue: string = ""')
            build_parts.append('      TextInput({ placeholder: "Enter value..." }).onChange((value: string) => { this.inputValue = value }).width("100%").padding(10)')
            build_parts.append('      Button("Submit").backgroundColor("' + sv["accent"] + '").fontColor("#ffffff").borderRadius(8).padding({ left: 20, right: 20, top: 10, bottom: 10 }).onClick(() => { console.info("Submitted: " + this.inputValue) })')
        elif comp["type"] == "card":
            build_parts.append('      Column() {')
            build_parts.append('        Text("' + comp["name"] + '").fontSize(18).fontWeight(FontWeight.Medium)')
            build_parts.append('        Text("Content goes here").fontSize(14).fontColor("' + sv["muted"] + '")')
            build_parts.append('      }.width("100%").padding(24).backgroundColor("' + sv["card_bg"] + '").borderRadius(8).shadow({ radius: 4, color: "#00000012" })')
        else:
            build_parts.append('      Text("' + comp["name"] + '").fontSize(18).padding(16)')

    state_vars = '\n'.join(comp_vars) if comp_vars else '  @State message: string = "Hello"'
    build_body = '\n'.join(build_parts) if build_parts else '      Text(this.message)'

    return (
        '@Entry\n'
        '@Component\n'
        'struct Index {\n'
        + state_vars + '\n\n'
        '  build() {\n'
        '    Column() {\n'
        + build_body + '\n'
        '    }.width("100%").height("100%").backgroundColor("' + sv["bg"] + '")\n'
        '  }\n'
        '}'
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="frontend_designer",
        description="Generate frontend UI code with real layout/component scaffolding for HTML, Vue, React, or ArkTS. Parses description into components and generates runnable code.",
        category="development",
        parameters={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Description of the UI to design",
                },
                "framework": {
                    "type": "string",
                    "enum": ["html", "vue", "react", "arkts"],
                    "description": "Frontend framework to target",
                },
                "style": {
                    "type": "string",
                    "enum": ["modern", "minimal", "material"],
                    "description": "Visual style to apply",
                },
            },
            "required": ["description"],
        },
        handler=execute,
        timeout=30,
    ))
