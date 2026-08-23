from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from tools.devstack.commands.bodies import autogen_block


class TestBodies(unittest.TestCase):
    def test_autogen_commits_format_sha_colon_subject(self) -> None:
        commits = "2454222e59 Add render tests infrastructure.\n"
        with patch.dict(os.environ, {"DEVSTACK_BODY_COMMIT_SUBJECT_MAX": "200"}, clear=False):
            out = autogen_block(
                base_ref="main",
                pr_base="pr/base",
                stack_pos=1,
                stack_total=2,
                from_ref="a",
                to_ref="b",
                commits=commits,
            )
        self.assertIn("- `2454222e59`: Add render tests infrastructure.", out)

    def test_autogen_commits_truncates_subject(self) -> None:
        commits = "2454222e59 " + ("x" * 200) + "\n"
        with patch.dict(os.environ, {"DEVSTACK_BODY_COMMIT_SUBJECT_MAX": "10"}, clear=False):
            out = autogen_block(
                base_ref="main",
                pr_base="pr/base",
                stack_pos=1,
                stack_total=2,
                from_ref="a",
                to_ref="b",
                commits=commits,
            )
        # 10 chars max => 9 + ellipsis.
        self.assertIn("- `2454222e59`: " + ("x" * 9) + "…", out)

