from __future__ import annotations

import argparse
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.dependencies import cmd_dep_pin, dependency_status
from tools.devstack.core.dependencies import Dependency, read_dependencies


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "protocol.file.allow=always", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip()


def _init_repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")


class TestDependencies(unittest.TestCase):
    def test_read_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".devstack").mkdir()
            (root / ".devstack" / "dependencies.conf").write_text(
                "dependency coin src/3rdParty/coin FreeCAD/coin stack/top\n",
                encoding="utf-8",
            )
            self.assertEqual(
                read_dependencies(root),
                [Dependency("coin", "src/3rdParty/coin", "FreeCAD/coin", "stack/top")],
            )

    def test_dep_pin_updates_and_stages_gitlink(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            dependency = base / "dependency"
            dependency.mkdir()
            _init_repo(dependency)
            (dependency / "value").write_text("old\n", encoding="utf-8")
            _git(dependency, "add", "value")
            _git(dependency, "commit", "-m", "old")
            old_sha = _git(dependency, "rev-parse", "HEAD")
            (dependency / "value").write_text("new\n", encoding="utf-8")
            _git(dependency, "commit", "-am", "new")
            new_sha = _git(dependency, "rev-parse", "HEAD")
            _git(dependency, "branch", "stack/top", new_sha)

            source = base / "source-stack"
            _git(base, "clone", str(dependency), str(source))
            (source / ".devstack").mkdir()
            (source / ".devstack" / "stack.conf").write_text(
                f"base origin/main\ngithub_repo FreeCAD/coin\ncommit 001-top stack/top {new_sha}\n",
                encoding="utf-8",
            )

            consumer = base / "consumer"
            consumer.mkdir()
            _init_repo(consumer)
            _git(consumer, "-c", "protocol.file.allow=always", "submodule", "add", str(dependency), "deps/coin")
            _git(consumer / "deps/coin", "checkout", "--detach", old_sha)
            _git(consumer, "add", "deps/coin")
            _git(consumer, "commit", "-m", "pin old")
            (consumer / ".devstack").mkdir()
            (consumer / ".devstack" / "dependencies.conf").write_text(
                "dependency coin deps/coin FreeCAD/coin stack/top\n",
                encoding="utf-8",
            )

            args = argparse.Namespace(dependency="coin", from_stack=str(source), layer="top", apply=True)
            with (
                patch("tools.devstack.commands.dependencies.repo_root", return_value=consumer),
                patch("tools.devstack.commands.dependencies._remote_branch_sha", return_value=new_sha),
            ):
                cmd_dep_pin(args)
                status = dependency_status(consumer, Dependency("coin", "deps/coin", "FreeCAD/coin", "stack/top"))

            self.assertEqual(_git(consumer / "deps/coin", "rev-parse", "HEAD"), new_sha)
            staged = _git(consumer, "ls-files", "--stage", "deps/coin").split()[1]
            self.assertEqual(staged, new_sha)
            self.assertEqual(status["pinned_sha"], old_sha)
            self.assertEqual(status["checked_out_sha"], new_sha)


if __name__ == "__main__":
    unittest.main()
