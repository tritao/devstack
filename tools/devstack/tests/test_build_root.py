from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.devstack.core.build_root import ensure_external_build_preset


class TestExternalBuildRoot(unittest.TestCase):
    def test_disabled_leaves_worktree_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "feature"
            root.mkdir()
            self.assertEqual("debug", ensure_external_build_preset(root, "debug", {}))
            self.assertFalse((root / "CMakeUserPresets.json").exists())

    def test_creates_worktree_and_preset_specific_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "feature-a"
            build_root = base / "builds"
            root.mkdir()
            name = ensure_external_build_preset(root, "debug", {"DEVSTACK_BUILD_ROOT": str(build_root)})
            self.assertEqual("devstack-external-debug", name)
            user = json.loads((root / "CMakeUserPresets.json").read_text())
            wrapper = user["configurePresets"][0]
            self.assertEqual(["debug"], wrapper["inherits"])
            self.assertEqual(str(build_root / "feature-a" / "debug"), wrapper["binaryDir"])
            self.assertFalse((root / "build").exists())

    def test_wrapper_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "feature-a"
            root.mkdir()
            env = {"DEVSTACK_BUILD_ROOT": str(base / "builds")}
            ensure_external_build_preset(root, "debug", env)
            ensure_external_build_preset(root, "debug", env)
            user = json.loads((root / "CMakeUserPresets.json").read_text())
            self.assertEqual(1, len(user["configurePresets"]))

    def test_requires_absolute_build_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "feature-a"
            root.mkdir()
            with self.assertRaises(SystemExit):
                ensure_external_build_preset(root, "debug", {"DEVSTACK_BUILD_ROOT": "relative/builds"})
