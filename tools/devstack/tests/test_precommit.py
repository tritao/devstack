from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.precommit import (
    check_layer_has_no_precommit_bot_commits,
    check_layer_in_temporary_worktree,
    layer_range,
    run_precommit_gate,
)


class TestPrecommit(unittest.TestCase):
    def test_rejects_precommit_bot_fixup_commit(self) -> None:
        conf = type("Conf", (), {})()
        history = "abc1234\x00bot@pre-commit.ci\x00pre-commit-ci[bot]\x00[pre-commit.ci] auto fixes"
        with (
            patch("tools.devstack.commands.precommit.layer_range", return_value=("base", "tip")),
            patch("tools.devstack.commands.precommit.git", return_value=history),
            self.assertRaises(SystemExit),
        ):
            check_layer_has_no_precommit_bot_commits(Path("/repo"), conf, 1)

    def test_accepts_human_precommit_configuration_commit(self) -> None:
        conf = type("Conf", (), {})()
        history = "abc1234\x00dev@example.com\x00Developer\x00Configure pre-commit hooks"
        with (
            patch("tools.devstack.commands.precommit.layer_range", return_value=("base", "tip")),
            patch("tools.devstack.commands.precommit.git", return_value=history),
        ):
            check_layer_has_no_precommit_bot_commits(Path("/repo"), conf, 1)

    def test_layer_range_uses_previous_cut_point(self) -> None:
        entries = [
            type("Entry", (), {"sha": "first", "branch": "stack/first"})(),
            type("Entry", (), {"sha": "second", "branch": "stack/second"})(),
        ]
        conf = type("Conf", (), {"base_remote_ref": "upstream/main", "entries": entries, "ignore": []})()
        with patch("tools.devstack.commands.precommit.resolve_commitish", side_effect=lambda _root, ref: f"resolved-{ref}"):
            base, tip = layer_range(Path("/repo"), conf, 2)

        self.assertEqual(base, "resolved-first")
        self.assertEqual(tip, "resolved-second")

    def test_temporary_check_removes_worktree_after_hook_failure(self) -> None:
        conf = type("Conf", (), {})()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
            calls: list[list[str]] = []

            def fake_run(argv, **_kwargs):
                calls.append(argv)
                if argv[:2] == ["pre-commit", "run"]:
                    return subprocess.CompletedProcess(argv, 1, "hook failed", "")
                return subprocess.CompletedProcess(argv, 0, "", "")

            with (
                patch("tools.devstack.commands.precommit._require_precommit"),
                patch("tools.devstack.commands.precommit.layer_range", return_value=("base", "tip")),
                patch("tools.devstack.commands.precommit.run", side_effect=fake_run),
                patch("tools.devstack.commands.precommit.git", return_value=" M changed.cpp"),
                self.assertRaises(SystemExit),
            ):
                check_layer_in_temporary_worktree(root, conf, 1)

        self.assertTrue(any(call[:3] == ["git", "worktree", "remove"] for call in calls))

    def test_gate_can_be_disabled_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
            conf = type("Conf", (), {"precommit_check": "off", "entries": [object()]})()
            with (
                patch("tools.devstack.commands.precommit.check_layer_has_no_precommit_bot_commits") as bot_check,
                patch("tools.devstack.commands.precommit.check_layer_in_temporary_worktree") as check,
            ):
                run_precommit_gate(root, conf, None)
        check.assert_not_called()
        bot_check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
