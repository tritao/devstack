from __future__ import annotations

import argparse
import contextlib
import io
import unittest
from unittest.mock import patch

from tools.devstack.commands.github import cmd_pr_layer


class TestPrLayerUrl(unittest.TestCase):
    def test_pr_layer_prints_url_on_apply(self) -> None:
        buf = io.StringIO()
        fake_conf = type(
            "Conf",
            (),
            {
                "base_remote_ref": "origin/master",
                "entries": [type("Entry", (), {"branch": "pr/test/001"})()],
            },
        )()

        with (
            contextlib.redirect_stdout(buf),
            patch("tools.devstack.commands.github.cmd_update"),
            patch("tools.devstack.commands.github.cmd_push"),
            patch("tools.devstack.commands.github.cmd_gh_sync"),
            patch("tools.devstack.commands.github.repo_root", return_value=object()),
            patch("tools.devstack.commands.github.read_conf", return_value=fake_conf),
            patch("tools.devstack.commands.github.gh_default_repo_for_remotes", return_value="org/repo"),
            patch("tools.devstack.commands.github.gh_head_ref", return_value="me:pr/test/001"),
            patch("tools.devstack.commands.github.gh_pr_number_for_head", return_value="123"),
            patch("tools.devstack.commands.github.gh_pr_url", return_value="https://example.invalid/pr/123"),
        ):
            cmd_pr_layer(argparse.Namespace(layer=1, apply=True, draft=False))

        self.assertIn("PR: https://example.invalid/pr/123", buf.getvalue())
