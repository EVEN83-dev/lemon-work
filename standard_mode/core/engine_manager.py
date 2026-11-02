# -*- coding: utf-8 -*-
"""Re-export from shared module to avoid code duplication."""
try:
    from shared.engine_manager import *  # noqa: F401,F403
except ImportError:
    # 降级：如果 shared.engine_manager 不可用，尝试直接导入
    import os
    import sys
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from shared.engine_manager import *  # noqa: F401,F403
