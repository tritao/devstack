from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.github import gh_default_repo_for_remotes


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class TestGithubRepoDetection(unittest.TestCase):
    def test_prefers_base_remote_over_push_remote(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run(["git", "init"], root)
            run(["git", "remote", "add", "origin", "https://github.com/coin3d/coin.git"], root)
            run(["git", "remote", "add", "tritao", "git@github.com:tritao/coin.git"], root)

            with patch.dict(os.environ, {"DEVSTACK_STACK_REMOTE": "tritao"}, clear=False), patch(
                "tools.devstack.commands.github.note"
            ):
                repo = gh_default_repo_for_remotes(root, base_remote="origin")
            self.assertEqual("coin3d/coin", repo)

    def test_ignores_mismatched_devstack_gh_repo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run(["git", "init"], root)
            run(["git", "remote", "add", "origin", "https://github.com/coin3d/coin.git"], root)

            with patch.dict(os.environ, {"DEVSTACK_GH_REPO": "FreeCAD/FreeCAD"}, clear=False), patch(
                "tools.devstack.commands.github.note"
            ):
                repo = gh_default_repo_for_remotes(root, base_remote="origin")
            self.assertEqual("coin3d/coin", repo)

    def test_remote_head_branch_exists(self) -> None:
        from tools.devstack.commands.github import _remote_head_branch_exists

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            remote = root / "remote.git"
            work = root / "work"
            remote.mkdir()
            work.mkdir()

            run(["git", "init", "--bare", str(remote)], root)
            run(["git", "init"], work)
            run(["git", "config", "user.email", "devstack@test"], work)
            run(["git", "config", "user.name", "devstack"], work)
            run(["git", "remote", "add", "origin", str(remote)], work)
            (work / "a.txt").write_text("a\n", encoding="utf-8")
            run(["git", "add", "a.txt"], work)
            run(["git", "commit", "-m", "c1"], work)
            run(["git", "branch", "-M", "master"], work)
            run(["git", "push", "-u", "origin", "master"], work)

            self.assertTrue(_remote_head_branch_exists(work, "origin", "master"))
            self.assertFalse(_remote_head_branch_exists(work, "origin", "nope"))
