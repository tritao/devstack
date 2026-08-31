from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.worktrees import cmd_wt_remove


def args(**overrides: object) -> argparse.Namespace:
    values = {
        "name": "my-fix",
        "dir": None,
        "keep_build": False,
        "delete_branch": False,
        "force": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class TestWtRemove(unittest.TestCase):
    def test_removes_worktree_and_build_but_keeps_branch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            golden = base / "FreeCAD-master"
            worktree = base / "FreeCAD-worktrees" / "my-fix"
            build_root = base / "builds"
            build_dir = build_root / "my-fix"
            golden.mkdir()
            worktree.mkdir(parents=True)
            build_dir.mkdir(parents=True)
            with (
                patch("tools.devstack.commands.worktrees.repo_root", return_value=golden),
                patch("tools.devstack.commands.worktrees.worktree_list_paths", return_value=[golden, worktree]),
                patch("tools.devstack.commands.worktrees.current_branch", return_value="feature/my-fix"),
                patch("tools.devstack.commands.worktrees.git", return_value=""),
                patch(
                    "tools.devstack.commands.worktrees.load_devstack_env",
                    return_value={"DEVSTACK_BUILD_ROOT": str(build_root)},
                ),
                patch("tools.devstack.commands.worktrees.run") as run,
                patch("tools.devstack.commands.worktrees.shutil.rmtree") as rmtree,
            ):
                cmd_wt_remove(args())
            run.assert_called_once_with(["git", "worktree", "remove", str(worktree)], cwd=golden)
            rmtree.assert_called_once_with(build_dir)

    def test_refuses_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            golden = base / "FreeCAD-master"
            worktree = base / "my-fix"
            golden.mkdir()
            worktree.mkdir()
            with (
                patch("tools.devstack.commands.worktrees.repo_root", return_value=golden),
                patch("tools.devstack.commands.worktrees.worktree_list_paths", return_value=[golden, worktree]),
                patch("tools.devstack.commands.worktrees.current_branch", return_value="feature/my-fix"),
                patch("tools.devstack.commands.worktrees.git", return_value=" M source.cpp"),
                patch("tools.devstack.commands.worktrees.run") as run,
            ):
                with self.assertRaises(SystemExit):
                    cmd_wt_remove(args())
            run.assert_not_called()
