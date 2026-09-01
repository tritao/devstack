from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.github import _canonical_fingerprint, cmd_gh_sync, write_sync_plan


class TestGhSyncPlans(unittest.TestCase):
    def sample_state(self) -> dict[str, object]:
        return {
            "schema": 1,
            "repository_root": "/repo",
            "github_mode": "native",
            "github_repo": "FreeCAD/coin",
            "base_ref": "upstream/freecad-master",
            "base_remote_sha": "base-sha",
            "push_remote": "target",
            "repository_layout": "same-repository",
            "native_eligible": True,
            "gh_stack_installed": True,
            "configured_repo_matches": True,
            "only": None,
            "standalone": False,
            "draft": False,
            "layers": [
                {
                    "key": "001-pr-12",
                    "branch": "stack/egl-offscreen",
                    "configured_sha": "local-sha",
                    "local_sha": "local-sha",
                    "remote_sha": "remote-sha",
                    "desired_base": "freecad-master",
                    "desired_title": "EGL support",
                    "desired_body_sha256": "body-hash",
                    "pr": {"number": 12, "base": "freecad-master"},
                }
            ],
        }

    def test_plan_is_reviewable_and_fingerprinted(self) -> None:
        state = self.sample_state()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.json"
            plan = write_sync_plan(path, state)
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(_canonical_fingerprint(state), plan["fingerprint"])
        self.assertEqual(plan["fingerprint"], saved["fingerprint"])
        self.assertEqual("FreeCAD/coin", saved["summary"]["repository"])
        self.assertEqual(1, saved["summary"]["layers"])
        self.assertTrue(saved["summary"]["native_link"])

    def test_remote_or_pr_change_invalidates_fingerprint(self) -> None:
        before = self.sample_state()
        after = self.sample_state()
        after["layers"][0]["remote_sha"] = "changed-remote-sha"
        self.assertNotEqual(_canonical_fingerprint(before), _canonical_fingerprint(after))

        after = self.sample_state()
        after["layers"][0]["pr"]["base"] = "different-base"
        self.assertNotEqual(_canonical_fingerprint(before), _canonical_fingerprint(after))

    def test_apply_plan_rejects_stale_state_before_mutation(self) -> None:
        saved_state = self.sample_state()
        changed_state = self.sample_state()
        changed_state["layers"][0]["remote_sha"] = "changed-remote-sha"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.json"
            write_sync_plan(path, saved_state)
            args = argparse.Namespace(
                apply=False,
                apply_plan=str(path),
                plan=None,
                only=None,
                standalone=False,
                draft=False,
            )
            with (
                patch("tools.devstack.commands.github.repo_root", return_value=Path("/repo")),
                patch("tools.devstack.commands.github.read_conf", return_value=object()),
                patch("tools.devstack.commands.github.gh_check"),
                patch("tools.devstack.commands.github.build_sync_state", return_value=changed_state),
                patch("tools.devstack.commands.github.run") as run,
            ):
                with self.assertRaises(SystemExit):
                    cmd_gh_sync(args)
        run.assert_not_called()
