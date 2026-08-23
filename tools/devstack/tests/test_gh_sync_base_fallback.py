from __future__ import annotations

import argparse
import contextlib
import io
import unittest
from unittest.mock import patch

from tools.devstack.commands.github import cmd_gh_sync


class TestGhSyncBaseFallback(unittest.TestCase):
    def test_falls_back_to_default_base_when_layer_base_missing(self) -> None:
        # Simulate a fork-style stack: base repo doesn't have pr/... branches.
        fake_conf = type(
            "Conf",
            (),
            {
                "base_remote_ref": "origin/master",
                "entries": [type("Entry", (), {"key": "001", "branch": "pr/test/001", "sha": "abc"})()],
            },
        )()

        buf = io.StringIO()
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            # Mimic `run(..., capture=True)` interface for gh_pr_number_for_head etc.
            return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with (
            contextlib.redirect_stderr(buf),
            patch("tools.devstack.commands.github.repo_root", return_value=object()),
            patch("tools.devstack.commands.github.read_conf", return_value=fake_conf),
            patch("tools.devstack.commands.github.gh_check"),
            patch("tools.devstack.commands.github.default_stack_remote", return_value="tritao"),
            patch("tools.devstack.commands.github.gh_default_repo_for_remotes", return_value="coin3d/coin"),
            patch("tools.devstack.commands.github.select_entries", return_value=[fake_conf.entries[0]]),
            patch("tools.devstack.commands.github.pr_base_for_layer", return_value="pr/test/000"),
            patch("tools.devstack.commands.github.filtered_mode", return_value=False),
            patch("tools.devstack.commands.github.ensure_commit_exists"),
            patch("tools.devstack.commands.github.git", return_value="Title"),
            patch("tools.devstack.commands.github.resolved_body_file"),
            patch("tools.devstack.commands.github.title_from_body_frontmatter", return_value=""),
            patch("tools.devstack.commands.github.body_file_for_gh"),
            patch("tools.devstack.commands.github.gh_head_ref", return_value="me:pr/test/001"),
            patch("tools.devstack.commands.github.gh_pr_number_for_head", return_value=""),
            patch(
                "tools.devstack.commands.github._remote_head_branch_exists",
                side_effect=lambda _r, remote, br: br in ("master", "pr/test/001"),
            ),
            patch("tools.devstack.commands.github.run", side_effect=fake_run),
        ):
            cmd_gh_sync(argparse.Namespace(apply=True, only=2, draft=False))

        # Ensure the gh command uses --base master (fallback), not the missing pr/test/000.
        gh_cmds = [c for c in calls if c and c[0] == "gh" and "pr" in c]
        self.assertTrue(any("--base" in c and c[c.index("--base") + 1] == "master" for c in gh_cmds))
