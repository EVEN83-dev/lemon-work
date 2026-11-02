from __future__ import annotations

import os
import tempfile
import unittest

from scripts.audit_codelock import _scan_file, run


class TestAuditCodelock(unittest.TestCase):
    def test_detects_frozen_import(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("from standard_mode.core.agent_engine import AgentEngine\n")
            f.flush()
            violations = _scan_file(f.name)
        os.unlink(f.name)
        self.assertEqual(len(violations), 1)
        self.assertIn("agent_engine", violations[0][2])

    def test_clean_file_no_violations(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("from bridge.core.context_compressor import ContextCompressor\n")
            f.flush()
            violations = _scan_file(f.name)
        os.unlink(f.name)
        self.assertEqual(len(violations), 0)

    def test_submodule_import_detected(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("from standard_mode.ui.whitebox.whitebox_panel import WhiteboxPanel\n")
            f.flush()
            violations = _scan_file(f.name)
        os.unlink(f.name)
        self.assertEqual(len(violations), 1)


if __name__ == "__main__":
    unittest.main()
