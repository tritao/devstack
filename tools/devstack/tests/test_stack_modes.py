from __future__ import annotations

import argparse
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.github import cmd_stack_mode, native_link_command, stack_topology
from tools.devstack.core.stackconf import read_conf


class TestStackModes(unittest.TestCase):
    def test_reads_mode_and_publication_remotes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".devstack").mkdir()
            (root / ".devstack" / "stack.conf").write_text(
                "\n".join(
                    [
                        "base upstream/main",
                        "github_mode native",
                        "github_repo FreeCAD/coin",
                        "push_remote origin",
                        "001-one abc",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            conf = read_conf(root)
            self.assertEqual("native", conf.github_mode)
            self.assertEqual("FreeCAD/coin", conf.github_repo)
            self.assertEqual("origin", conf.push_remote)

    def test_native_eligibility_depends_on_repository_identity(self) -> None:
        conf = type(
            "Conf",
            (),
            {
                "base_remote_ref": "upstream/main",
                "push_remote": "origin",
                "github_repo": "FreeCAD/FreeCAD",
                "github_mode": "chained",
                "entries": [],
            },
        )()
        with (
            patch("tools.devstack.commands.github._repo_for_remote", side_effect=["FreeCAD/FreeCAD", "tritao/FreeCAD"]),
            patch("tools.devstack.commands.github._gh_stack_installed", return_value=True),
        ):
            status = stack_topology(Path("/repo"), conf)
        self.assertEqual("cross-fork", status["repository_layout"])
        self.assertFalse(status["native_eligible"])

    def test_same_repository_is_native_eligible(self) -> None:
        conf = type(
            "Conf",
            (),
            {
                "base_remote_ref": "origin/freecad-master",
                "push_remote": "origin",
                "github_repo": "FreeCAD/coin",
                "github_mode": "native",
                "entries": [],
            },
        )()
        with (
            patch("tools.devstack.commands.github._repo_for_remote", side_effect=["FreeCAD/coin", "FreeCAD/coin"]),
            patch("tools.devstack.commands.github._gh_stack_installed", return_value=True),
        ):
            status = stack_topology(Path("/repo"), conf)
        self.assertEqual("same-repository", status["repository_layout"])
        self.assertTrue(status["native_eligible"])
        self.assertTrue(status["valid"])

    def test_native_mode_refuses_cross_fork_before_writing(self) -> None:
        conf = type("Conf", (), {"github_mode": "chained", "path": Path("stack.conf")})()
        status = {
            "repository_layout": "cross-fork",
            "native_eligible": False,
            "gh_stack_installed": True,
            "base_repo": "FreeCAD/FreeCAD",
            "head_repo": "tritao/FreeCAD",
        }
        with (
            patch("tools.devstack.commands.github.repo_root", return_value=Path("/repo")),
            patch("tools.devstack.commands.github.read_conf", return_value=conf),
            patch("tools.devstack.commands.github.stack_topology", return_value=status),
            patch("tools.devstack.commands.github.set_conf_directive") as write,
        ):
            with self.assertRaises(SystemExit):
                cmd_stack_mode(argparse.Namespace(mode="native", apply=True))
        write.assert_not_called()

    def test_native_link_uses_complete_ordered_branch_list(self) -> None:
        entries = [
            type("Entry", (), {"branch": "stack/one"})(),
            type("Entry", (), {"branch": "stack/two"})(),
        ]
        conf = type("Conf", (), {"base_remote_ref": "origin/main", "entries": entries})()
        self.assertEqual(
            ["gh", "stack", "link", "--base", "main", "stack/one", "stack/two"],
            native_link_command(conf),
        )
