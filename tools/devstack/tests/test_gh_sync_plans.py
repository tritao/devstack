from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.github import (
    _canonical_fingerprint,
    apply_native_link,
    cmd_gh_sync,
    desired_draft_for_entry,
    push_planned_branch,
    write_sync_plan,
)


class TestGhSyncPlans(unittest.TestCase):
    def test_stacked_draft_policy_keeps_only_first_layer_ready(self) -> None:
        first = type("Entry", (), {"branch": "stack/first"})()
        second = type("Entry", (), {"branch": "stack/second"})()
        conf = type("Conf", (), {"entries": [first, second], "draft_mode": "stacked"})()

        self.assertFalse(desired_draft_for_entry(conf, first, force_draft=False))
        self.assertTrue(desired_draft_for_entry(conf, second, force_draft=False))
        self.assertTrue(desired_draft_for_entry(conf, first, force_draft=True))

        conf.draft_mode = "off"
        self.assertFalse(desired_draft_for_entry(conf, second, force_draft=False))
        conf.draft_mode = "all"
        self.assertTrue(desired_draft_for_entry(conf, first, force_draft=False))

    def test_native_link_preserves_historical_stack_members(self) -> None:
        conf = type("Conf", (), {"base_remote_ref": "upstream/main", "push_remote": "target", "entries": []})()
        error = subprocess.CalledProcessError(
            5,
            ["gh", "stack", "link"],
            output="Cannot update stack: this would remove #11 from the stack\nCurrent stack: #11, #12, #65\n",
            stderr="",
        )
        with patch("tools.devstack.commands.github.run", side_effect=error):
            apply_native_link(Path("/repo"), conf, {12, 65})

    def test_native_link_does_not_hide_missing_active_pr(self) -> None:
        conf = type("Conf", (), {"base_remote_ref": "upstream/main", "push_remote": "target", "entries": []})()
        error = subprocess.CalledProcessError(
            5,
            ["gh", "stack", "link"],
            output="Cannot update stack: this would remove #11 from the stack\nCurrent stack: #11, #12\n",
            stderr="",
        )
        with (
            patch("tools.devstack.commands.github.run", side_effect=error),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            apply_native_link(Path("/repo"), conf, {12, 65})

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
            "draft_mode": "stacked",
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
                    "desired_draft": False,
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
        self.assertEqual(2, saved["schema"])
        self.assertEqual("push", saved["operations"][0]["type"])
        self.assertEqual("remote-sha", saved["operations"][0]["expected_remote_sha"])
        self.assertEqual("local-sha", saved["operations"][0]["new_sha"])
        self.assertEqual("pr-sync", saved["operations"][1]["type"])
        self.assertFalse(saved["operations"][1]["draft"])
        self.assertEqual("native-link", saved["operations"][2]["type"])

    def test_plan_records_creation_lease_for_missing_remote_branch(self) -> None:
        state = self.sample_state()
        state["layers"][0]["remote_sha"] = ""
        with tempfile.TemporaryDirectory() as td:
            plan = write_sync_plan(Path(td) / "plan.json", state)
        push = plan["operations"][0]
        self.assertEqual("", push["expected_remote_sha"])
        self.assertEqual("", push["rollback_sha"])

    def test_planned_push_uses_explicit_sha_and_lease(self) -> None:
        planned = self.sample_state()["layers"][0]
        with patch("tools.devstack.commands.github.run") as run:
            push_planned_branch(Path("/repo"), "target", "stack/egl-offscreen", planned)
        self.assertEqual(
            [
                "git",
                "push",
                "target",
                "local-sha:refs/heads/stack/egl-offscreen",
                "--force-with-lease=refs/heads/stack/egl-offscreen:remote-sha",
            ],
            run.call_args.args[0],
        )

    def test_planned_push_updates_local_bare_remote_and_rejects_stale_lease(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "work"
            remote = Path(td) / "remote.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Devstack Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "devstack@example.invalid"], cwd=root, check=True)
            tracked = root / "tracked.txt"
            tracked.write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "old"], cwd=root, check=True, capture_output=True)
            old_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
            ).stdout.strip()
            subprocess.run(["git", "push", str(remote), "HEAD:refs/heads/stack/test"], cwd=root, check=True)
            tracked.write_text("new\n", encoding="utf-8")
            subprocess.run(["git", "commit", "-am", "new"], cwd=root, check=True, capture_output=True)
            new_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
            ).stdout.strip()

            push_planned_branch(
                root,
                str(remote),
                "stack/test",
                {"remote_sha": old_sha, "local_sha": new_sha},
            )
            remote_sha = subprocess.run(
                ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/stack/test"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            self.assertEqual(new_sha, remote_sha)

            tracked.write_text("newer\n", encoding="utf-8")
            subprocess.run(["git", "commit", "-am", "newer"], cwd=root, check=True, capture_output=True)
            newer_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
            ).stdout.strip()
            with self.assertRaises(subprocess.CalledProcessError):
                push_planned_branch(
                    root,
                    str(remote),
                    "stack/test",
                    {"remote_sha": old_sha, "local_sha": newer_sha},
                )

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

    def test_apply_plan_rejects_tampered_saved_state_before_mutation(self) -> None:
        state = self.sample_state()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.json"
            write_sync_plan(path, state)
            saved = json.loads(path.read_text(encoding="utf-8"))
            saved["state"]["layers"][0]["desired_title"] = "tampered"
            path.write_text(json.dumps(saved), encoding="utf-8")
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
                patch("tools.devstack.commands.github.run") as run,
            ):
                with self.assertRaises(SystemExit):
                    cmd_gh_sync(args)
        run.assert_not_called()
