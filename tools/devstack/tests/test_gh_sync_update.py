from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.github import cmd_gh_sync


class TestGhSyncUpdate(unittest.TestCase):
    def test_updates_existing_pr_via_api(self) -> None:
        entry = type("Entry", (), {"key": "001-layer", "branch": "pr/test/001", "sha": "abc"})()
        conf = type("Conf", (), {"base_remote_ref": "origin/main", "entries": [entry]})()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            body = root / "body.md"
            body.write_text("body\n", encoding="utf-8")
            with (
                patch("tools.devstack.commands.github.repo_root", return_value=root),
                patch("tools.devstack.commands.github.read_conf", return_value=conf),
                patch("tools.devstack.commands.github.gh_check"),
                patch("tools.devstack.commands.github.default_stack_remote", return_value="origin"),
                patch("tools.devstack.commands.github.gh_default_repo_for_remotes", return_value="me/repo"),
                patch("tools.devstack.commands.github.select_entries", return_value=[entry]),
                patch("tools.devstack.commands.github.filtered_mode", return_value=False),
                patch("tools.devstack.commands.github.ensure_commit_exists"),
                patch("tools.devstack.commands.github.git", return_value="Layer title"),
                patch("tools.devstack.commands.github.resolved_body_file", return_value=body),
                patch("tools.devstack.commands.github.title_from_body_frontmatter", return_value=""),
                patch("tools.devstack.commands.github.body_file_for_gh", return_value=body),
                patch("tools.devstack.commands.github.gh_head_ref", return_value="pr/test/001"),
                patch("tools.devstack.commands.github.gh_pr_number_for_head", return_value="42"),
                patch("tools.devstack.commands.github.gh_pr_url", return_value=""),
                patch("tools.devstack.commands.github._remote_head_branch_exists", return_value=True),
                patch("tools.devstack.commands.github.run") as run,
            ):
                cmd_gh_sync(argparse.Namespace(apply=True, only=None, draft=False))

            command = run.call_args.args[0]
            self.assertEqual(command[:4], ["gh", "api", "repos/me/repo/pulls/42", "--method"])
            self.assertIn("base=main", command)
            self.assertIn("title=[001] Layer title", command)
            self.assertIn(f"body=@{body}", command)
