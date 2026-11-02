from __future__ import annotations

import inspect
import os
import sys
import unittest
from typing import Set

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from bridge.skills.registry import SkillsRegistry as BridgeRegistry
from standard_mode.core.skills_registry import SkillsRegistry as StandardRegistry


class TestRegistryParity(unittest.TestCase):
    def test_core_methods_present(self):
        required = {"register", "unregister", "get", "list_skills", "execute", "count"}
        bridge_methods = {name for name, _ in inspect.getmembers(BridgeRegistry, predicate=inspect.isfunction) if not name.startswith("_")}
        standard_methods = {name for name, _ in inspect.getmembers(StandardRegistry, predicate=inspect.isfunction) if not name.startswith("_")}

        for method in required:
            self.assertIn(method, bridge_methods, "Bridge registry missing method: " + method)
            self.assertIn(method, standard_methods, "Standard registry missing method: " + method)

    def test_method_signature_compatible(self):
        core_methods = ["register", "unregister", "get", "execute", "count"]
        for method_name in core_methods:
            bridge_sig = inspect.signature(getattr(BridgeRegistry, method_name))
            standard_sig = inspect.signature(getattr(StandardRegistry, method_name))
            bridge_params = list(bridge_sig.parameters.keys())
            standard_params = list(standard_sig.parameters.keys())
            if bridge_params != standard_params:
                bridge_core = [p for p in bridge_params if _is_required_param(bridge_sig.parameters[p])]
                standard_core = [p for p in standard_params if _is_required_param(standard_sig.parameters[p])]
                self.assertEqual(
                    bridge_core,
                    standard_core,
                    "Method '" + method_name + "' required params differ: bridge=" + str(bridge_core) + " standard=" + str(standard_core),
                )

    def test_list_skills_compatible(self):
        bridge_sig = inspect.signature(getattr(BridgeRegistry, "list_skills"))
        standard_sig = inspect.signature(getattr(StandardRegistry, "list_skills"))
        bridge_required = [p for p in bridge_sig.parameters if _is_required_param(bridge_sig.parameters[p])]
        standard_required = [p for p in standard_sig.parameters if _is_required_param(standard_sig.parameters[p])]
        self.assertEqual(bridge_required, standard_required, "list_skills required params differ")


def _is_required_param(param):
    return param.default is inspect.Parameter.empty and param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)


if __name__ == "__main__":
    unittest.main()
