"""
B-010: Lemon Bridge Startup Script.

Initializes all components and starts the FastAPI server.
"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def main():
    from bridge.core.settings_manager import SettingsManager
    from bridge.core.i18n import set_language

    settings = SettingsManager.instance()
    settings.load()

    set_language(settings.get("general.language", "zh"))

    print("=" * 50)
    print("  Lemon Bridge Server")
    print("=" * 50)
    print(f"  Host: {settings.get('bridge.host', '0.0.0.0')}")
    print(f"  Port: {settings.get('bridge.port', 8765)}")
    print("=" * 50)

    from bridge_server import main as serve
    serve()


if __name__ == "__main__":
    main()
