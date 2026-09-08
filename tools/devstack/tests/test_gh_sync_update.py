from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.github import cmd_gh_sync, resolve_body_dependency_link


class TestGhSyncUpdate(unittest.TestCase):
    def test_resolves_published_predecessor_to_pr_link(self) -> None:
        first = type("Entry", (), {"branch": "stack/first"})()
        second = type("Entry", (), {"branch": "stack/second"})()
        conf = type("Conf", (), {"entries": [first, second]})()
        body = "> Part `2/3`. Depends on `stack/first`; review and merge in order.\n"
        with (
            patch("tools.devstack.commands.github.gh_head_ref", return_value="owner:stack/first"),
            patch("tools.devstack.commands.github.gh_pr_number_for_head", return_value="29700"),
        ):
            resolved = resolve_body_dependency_link(Path("/repo"), conf, second, body, "FreeCAD/FreeCAD", "origin")

        self.assertIn("Depends on [#29700](https://github.com/FreeCAD/FreeCAD/pull/29700);", resolved)
        self.assertNotIn("`stack/first`", resolved)

    def test_keeps_branch_when_predecessor_is_unpublished(self) -> None:
        first = type("Entry", (), {"branch": "stack/first"})()
        second = type("Entry", (), {"branch": "stack/second"})()
        conf = type("Conf", (), {"entries": [first, second]})()
        body = "Depends on `stack/first`;"
        with (
            patch("tools.devstack.commands.github.gh_head_ref", return_value="owner:stack/first"),
            patch("tools.devstack.commands.github.gh_pr_number_for_head", return_value=""),
        ):
            resolved = resolve_body_dependency_link(Path("/repo"), conf, second, body, "FreeCAD/FreeCAD", "origin")

        self.assertEqual(body, resolved)

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

    def test_existing_pr_omits_unchanged_fields(self) -> None:
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
                patch("tools.devstack.commands.github._remote_head_branch_exists", return_value=True),
                patch(
                    "tools.devstack.commands.github._current_pr_state",
                    return_value={
                        "base": "main",
                        "title": "[001] Layer title",
                        "body_sha256": "9e2ec912af5dff2a72300863864fc4da04e81999339d9fac5c7590ba8a3f4e11",
                    },
                ),
                patch("tools.devstack.commands.github.run") as run,
            ):
                cmd_gh_sync(argparse.Namespace(apply=True, only=None, draft=False))

            self.assertFalse(
                any(call.args and call.args[0][:3] == ["gh", "api", "repos/me/repo/pulls/42"] for call in run.call_args_list)
            )

    def test_existing_later_pr_is_converted_to_draft(self) -> None:
        first = type("Entry", (), {"key": "001-first", "branch": "pr/test/001", "sha": "aaa"})()
        second = type("Entry", (), {"key": "002-second", "branch": "pr/test/002", "sha": "bbb"})()
        conf = type(
            "Conf",
            (),
            {"base_remote_ref": "origin/main", "entries": [first, second], "draft_mode": "stacked"},
        )()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            body = root / "body.md"
            body.write_text("body\n", encoding="utf-8")
            current = {
                "base": "pr/test/001",
                "title": "[002] Layer title",
                "body_sha256": "9e2ec912af5dff2a72300863864fc4da04e81999339d9fac5c7590ba8a3f4e11",
                "draft": False,
            }
            with (
                patch("tools.devstack.commands.github.repo_root", return_value=root),
                patch("tools.devstack.commands.github.read_conf", return_value=conf),
                patch("tools.devstack.commands.github.gh_check"),
                patch("tools.devstack.commands.github.default_stack_remote", return_value="origin"),
                patch("tools.devstack.commands.github.gh_default_repo_for_remotes", return_value="me/repo"),
                patch("tools.devstack.commands.github.select_entries", return_value=[second]),
                patch("tools.devstack.commands.github.filtered_mode", return_value=False),
                patch("tools.devstack.commands.github.ensure_commit_exists"),
                patch("tools.devstack.commands.github.git", return_value="Layer title"),
                patch("tools.devstack.commands.github.resolved_body_file", return_value=body),
                patch("tools.devstack.commands.github.title_from_body_frontmatter", return_value=""),
                patch("tools.devstack.commands.github.body_file_for_gh", return_value=body),
                patch("tools.devstack.commands.github.gh_head_ref", return_value="pr/test/002"),
                patch("tools.devstack.commands.github.gh_pr_number_for_head", return_value="43"),
                patch("tools.devstack.commands.github.gh_pr_url", return_value=""),
                patch("tools.devstack.commands.github._remote_head_branch_exists", return_value=True),
                patch("tools.devstack.commands.github._current_pr_state", return_value=current),
                patch("tools.devstack.commands.github.run") as run,
            ):
                cmd_gh_sync(argparse.Namespace(apply=True, only=2, draft=False))

            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn(["gh", "pr", "ready", "43", "--repo", "me/repo", "--undo"], commands)
