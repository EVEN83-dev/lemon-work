import html
import json

from .models import SkillResult, SkillDef

METADATA = {
    "name": "html_to_video",
    "version": "1.0.0",
    "category": "media",
    "description": "Generate HTML storyboards from content (placeholder for video generation).",
}


def execute(content: str, style: str = "modern", duration: int = 30, **kwargs) -> SkillResult:
    if not content.strip():
        return SkillResult.fail("No content provided")

    duration = max(5, min(300, duration))

    style_configs = {
        "modern": {"bg": "Lemon.DARK_MID_5", "text": "Lemon.ERROR", "accent": "Lemon.INFO_BORDER_DARK", "font": "Segoe UI, sans-serif"},
        "classic": {"bg": "#f5f5dc", "text": "Lemon.TEXT_DISABLED", "accent": "#8b4513", "font": "Georgia, serif"},
        "minimal": {"bg": "Lemon.BG", "text": "Lemon.PRIMARY", "accent": "#cccccc", "font": "Helvetica, Arial, sans-serif"},
        "bold": {"bg": "Lemon.ACCENT_RED", "text": "Lemon.BG", "accent": "#ffd93d", "font": "Impact, sans-serif"},
    }

    config = style_configs.get(style, style_configs["modern"])
    safe_content = html.escape(content)
    slides = _create_slides(content, duration)
    slides_json = json.dumps(slides)

    html_output = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Storyboard: {html.escape(content[:50])}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: {config['bg']}; color: {config['text']}; font-family: {config['font']}; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 2rem; }}
  .storyboard {{ max-width: 800px; width: 100%; }}
  .slide {{ background: {config['accent']}; border-radius: 12px; padding: 2rem; margin-bottom: 1.5rem; opacity: 0; animation: fadeIn 0.8s forwards; }}
  .slide h2 {{ font-size: 1.5rem; margin-bottom: 1rem; }}
  .slide p {{ line-height: 1.6; font-size: 1rem; }}
  .meta {{ text-align: center; margin-bottom: 2rem; opacity: 0.7; font-size: 0.9rem; }}
  .controls {{ text-align: center; margin-top: 1rem; }}
  .controls button {{ background: {config['text']}; color: {config['bg']}; border: none; padding: 0.5rem 1.5rem; border-radius: 6px; cursor: pointer; font-size: 1rem; margin: 0 0.5rem; }}
  @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
</style>
</head>
<body>
<div class="storyboard">
  <div class="meta">
    <p>Duration: {duration}s | Style: {style} | Slides: {len(slides)}</p>
  </div>
  <div id="slides-container"></div>
  <div class="controls">
    <button onclick="prevSlide()">Previous</button>
    <button onclick="nextSlide()">Next</button>
  </div>
</div>
<script>
const slides = {slides_json};
let current = 0;
const container = document.getElementById('slides-container');
function render() {{
  container.innerHTML = '<div class="slide" style="animation-delay:0s"><h2>' + slides[current].title + '</h2><p>' + slides[current].content + '</p></div>';
}}
function nextSlide() {{ current = Math.min(current + 1, slides.length - 1); render(); }}
function prevSlide() {{ current = Math.max(current - 1, 0); render(); }}
render();
</script>
</body>
</html>"""

    return SkillResult.ok(
        output=html_output,
        data={"format": "html", "style": style, "duration": duration, "slides_count": len(slides), "note": "Placeholder: actual video generation requires external service"},
    )


def _create_slides(content: str, duration: int) -> list:
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    if not paragraphs:
        paragraphs = [content]

    slides_per_duration = max(1, duration // 10)
    slides = []

    title = paragraphs[0][:60] if paragraphs else "Untitled"
    slides.append({"title": "Introduction", "content": paragraphs[0]})

    if len(paragraphs) > 1:
        for i, para in enumerate(paragraphs[1:slides_per_duration], 1):
            slides.append({"title": f"Part {i}", "content": para})
    else:
        words = content.split()
        chunk_size = max(20, len(words) // slides_per_duration)
        for i in range(1, slides_per_duration):
            start = i * chunk_size
            chunk = " ".join(words[start:start + chunk_size])
            if chunk:
                slides.append({"title": f"Section {i + 1}", "content": chunk})

    slides.append({"title": "Summary", "content": f"Key takeaway: {paragraphs[0][:200]}"})

    return slides


def register(registry) -> None:
    registry.register(SkillDef(
        name="html_to_video",
        description="Generate HTML storyboards from content. Returns HTML string (video requires external service).",
        category="media",
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Content to convert into a storyboard",
                },
                "style": {
                    "type": "string",
                    "enum": ["modern", "classic", "minimal", "bold"],
                    "description": "Visual style of the storyboard",
                },
                "duration": {
                    "type": "integer",
                    "description": "Target duration in seconds (5-300)",
                    "minimum": 5,
                    "maximum": 300,
                },
            },
            "required": ["content"],
        },
        handler=execute,
        timeout=15,
    ))
