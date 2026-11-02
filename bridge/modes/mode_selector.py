from __future__ import annotations

import html
from typing import List


_PERMISSION_COLORS = {
    "full": "Lemon.ACCENT_GREEN",
    "elevated": "Lemon.STATUS_WARNING",
    "standard": "Lemon.ACCENT_BLUE",
    "restricted": "Lemon.ACCENT_RED",
}


class ModeSelector:
    def render_selector(self, current_mode: str, available_modes: List[dict]) -> str:
        cards: List[str] = []
        for mode in available_modes:
            name = html.escape(mode.get("name", ""))
            display_name = html.escape(mode.get("display_name", ""))
            description = html.escape(mode.get("description", ""))
            permission_level = html.escape(mode.get("permission_level", "standard"))
            is_active = mode.get("name", "") == current_mode
            perm_color = _PERMISSION_COLORS.get(mode.get("permission_level", ""), "Lemon.ACCENT_BLUE")
            tool_label = html.escape(
                "All tools" if not mode.get("allowed_tools") else f"{len(mode['allowed_tools'])} tools"
            )

            border = "border: 2px solid Lemon.BRAND_ORANGE_LIGHT;" if is_active else "border: 1px solid rgba(255,255,255,0.1);"
            bg = "background: rgba(255,154,74,0.12);" if is_active else "background: rgba(15,15,30,0.7);"

            cards.append(
                f'<div style="{border} {bg} border-radius:12px; padding:16px; cursor:pointer; '
                f'transition:all 0.3s ease; backdrop-filter:blur(10px);" '
                f'onclick="_callPython(\'modeAction\', \'switch:{name}\')">'
                f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">'
                f'<span style="font-size:16px; font-weight:600; color:#e2e8f0; '
                f'text-shadow:0 0 10px rgba(255,255,255,0.1);">{display_name}</span>'
                f'<span style="font-size:11px; padding:2px 8px; border-radius:9999px; '
                f'background:rgba(255,255,255,0.06); color:{perm_color}; '
                f'border:1px solid {perm_color}; text-transform:uppercase; '
                f'letter-spacing:0.5px;">{permission_level}</span>'
                f'</div>'
                f'<div style="font-size:13px; color:#94a3b8; margin-bottom:8px; '
                f'text-shadow:0 0 8px rgba(148,163,184,0.1);">{description}</div>'
                f'<div style="font-size:11px; color:#64748b;">{tool_label}</div>'
                f'</div>'
            )

        cards_html = "\n".join(cards)

        return (
            f'<div style="font-family:\'Inter\',system-ui,sans-serif; padding:20px;">'
            f'<div style="font-size:20px; font-weight:700; color:#e2e8f0; margin-bottom:16px; '
            f'text-shadow:0 0 20px rgba(255,255,255,0.15);">Select Mode</div>'
            f'<div style="display:grid; gap:12px;">{cards_html}</div>'
            f'</div>'
        )

    def render_indicator(self, mode_name: str, permission_level: str = "standard") -> str:
        escaped = html.escape(mode_name)
        color = _PERMISSION_COLORS.get(permission_level, _PERMISSION_COLORS.get("standard", "Lemon.ACCENT_BLUE"))

        label = escaped.replace("_", " ").title()
        escaped_label = html.escape(label)

        return (
            f'<span style="display:inline-flex; align-items:center; gap:4px; '
            f'padding:2px 10px; border-radius:9999px; font-size:11px; font-weight:500; '
            f'background:rgba(255,255,255,0.06); color:{color}; '
            f'border:1px solid {color}; '
            f'text-shadow:0 0 6px {color}33; '
            f'letter-spacing:0.3px;">{escaped_label}</span>'
        )
