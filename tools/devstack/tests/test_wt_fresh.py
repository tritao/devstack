from __future__ import annotations

import argparse
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.worktrees import cmd_wt_fresh


def args(**overrides: object) -> argparse.Namespace:
    values = {
        "name": "my-fix",
        "golden_dir": None,
        "remote": "upstream",
        "main_branch": "main",
        "branch": None,
        "dir": None,
        "preset": "debug",
        "jobs": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class TestWtFresh(unittest.TestCase):
    def test_uses_configured_golden_without_discovering_current_repo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            golden = Path(td) / "FreeCAD-master"
            golden.mkdir()

            def resolve_repo(path: Path | None = None) -> Path:
                self.assertEqual(golden, path)
                return golden

            def fake_git(argv: list[str], **_: object) -> str:
                if argv[0] == "status":
                    return ""
                raise subprocess.CalledProcessError(1, ["git", *argv])

            with (
                patch("tools.devstack.commands.worktrees.repo_root", side_effect=resolve_repo),
                patch(
                    "tools.devstack.commands.worktrees.load_devstack_env",
                    return_value={"DEVSTACK_GOLDEN_ROOT": str(golden)},
                ),
                patch("tools.devstack.commands.worktrees.git", side_effect=fake_git),
                patch("tools.devstack.commands.worktrees.current_branch", return_value="main"),
                patch("tools.devstack.commands.worktrees.run"),
                patch.dict("os.environ", {}, clear=True),
            ):
                cmd_wt_fresh(args(dir=str(Path(td) / "new-worktree")))

    def test_builds_before_creating_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            golden = Path(td) / "FreeCAD-master"
            golden.mkdir()
            def fake_git(argv: list[str], **_: object) -> str:
                if argv[0] == "status":
                    return ""
                raise subprocess.CalledProcessError(1, ["git", *argv])

            with (
                patch("tools.devstack.commands.worktrees.repo_root", return_value=golden),
                patch("tools.devstack.commands.worktrees.load_devstack_env", return_value={}),
                patch("tools.devstack.commands.worktrees.git", side_effect=fake_git),
                patch("tools.devstack.commands.worktrees.current_branch", return_value="main"),
                patch("tools.devstack.commands.worktrees.run") as run,
                patch.dict("os.environ", {}, clear=True),
            ):
                cmd_wt_fresh(args())

            commands = [entry.args[0] for entry in run.call_args_list]
            self.assertEqual(["git", "fetch", "upstream", "main"], commands[0])
            self.assertEqual(["git", "rebase", "upstream/main"], commands[1])
            self.assertIn("build", commands[2])
            self.assertIn("--toolchain", commands[2])
            self.assertIn("clang-mold", commands[2])
            self.assertIn("--ccache-launcher", commands[2])
            self.assertIn("wt-init", commands[3])
            self.assertLess(commands[2].index("build"), len(commands[2]))
            self.assertEqual(str(Path(td) / "FreeCAD-worktrees" / "my-fix"), commands[3][-1])

    def test_refuses_dirty_golden_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            golden = Path(td) / "FreeCAD-master"
            golden.mkdir()
            with (
                patch("tools.devstack.commands.worktrees.repo_root", return_value=golden),
                patch("tools.devstack.commands.worktrees.load_devstack_env", return_value={}),
                patch("tools.devstack.commands.worktrees.git", return_value=" M source.cpp"),
                patch("tools.devstack.commands.worktrees.run") as run,
            ):
                with self.assertRaises(SystemExit):
                    cmd_wt_fresh(args())
            run.assert_not_called()
