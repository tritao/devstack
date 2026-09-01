from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.core.git import default_base_remote_ref


class TestGitDefaults(unittest.TestCase):
    def test_prefers_upstream_for_pr_base(self) -> None:
        with (
            patch("tools.devstack.core.git.list_remotes", return_value=["origin", "upstream"]),
            patch("tools.devstack.core.git.remote_head_branch", return_value="main"),
            patch.dict("os.environ", {}, clear=True),
        ):
            self.assertEqual("upstream/main", default_base_remote_ref(Path("/repo")))

    def test_honors_configured_base_remote(self) -> None:
        with (
            patch("tools.devstack.core.git.list_remotes", return_value=["origin", "upstream"]),
            patch("tools.devstack.core.git.remote_head_branch", return_value="main"),
            patch.dict("os.environ", {"DEVSTACK_STACK_BASE_REMOTE": "origin"}, clear=True),
        ):
            self.assertEqual("origin/main", default_base_remote_ref(Path("/repo")))
