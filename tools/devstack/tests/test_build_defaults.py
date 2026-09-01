from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.devstack.core.build_defaults import load_build_defaults, write_build_defaults


class TestBuildDefaults(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = write_build_defaults(root, sandbox_paths=True, ccache_launcher=True)
            self.assertEqual(root / ".devstack" / "build-defaults.json", path)
            self.assertEqual(
                {"sandbox_paths": True, "ccache_launcher": True},
                load_build_defaults(root),
            )
