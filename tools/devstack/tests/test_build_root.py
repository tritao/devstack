from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.devstack.core.build_root import ensure_external_build_dir


class TestExternalBuildRoot(unittest.TestCase):
    def test_disabled_leaves_worktree_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "feature"
            root.mkdir()

            self.assertIsNone(ensure_external_build_dir(root, {}))
            self.assertFalse((root / "build").exists())

    def test_creates_worktree_specific_target_and_link(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "feature-a"
            build_root = base / "builds"
            root.mkdir()

            target = ensure_external_build_dir(root, {"DEVSTACK_BUILD_ROOT": str(build_root)})

            self.assertEqual(build_root / "feature-a", target)
            self.assertTrue(target.is_dir())
            self.assertTrue((root / "build").is_symlink())
            self.assertEqual(target, (root / "build").resolve())

    def test_matching_link_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "feature-a"
            build_root = base / "builds"
            target = build_root / root.name
            root.mkdir()
            target.mkdir(parents=True)
            (root / "build").symlink_to(target, target_is_directory=True)

            self.assertEqual(target, ensure_external_build_dir(root, {"DEVSTACK_BUILD_ROOT": str(build_root)}))

    def test_refuses_existing_real_build_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "feature-a"
            root.mkdir()
            (root / "build").mkdir()

            with self.assertRaises(SystemExit):
                ensure_external_build_dir(root, {"DEVSTACK_BUILD_ROOT": str(base / "builds")})

    def test_refuses_conflicting_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "feature-a"
            root.mkdir()
            other = base / "other"
            other.mkdir()
            (root / "build").symlink_to(other, target_is_directory=True)

            with self.assertRaises(SystemExit):
                ensure_external_build_dir(root, {"DEVSTACK_BUILD_ROOT": str(base / "builds")})

    def test_requires_absolute_build_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "feature-a"
            root.mkdir()

            with self.assertRaises(SystemExit):
                ensure_external_build_dir(root, {"DEVSTACK_BUILD_ROOT": "relative/builds"})
