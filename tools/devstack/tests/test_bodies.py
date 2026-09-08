from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.bodies import autogen_block, update_body_file


class TestBodies(unittest.TestCase):
    def test_new_body_omits_testing_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            body_path = Path(directory) / "body.md"
            update_body_file(body_path, "<!-- AUTOGEN -->", title="Layer title")

            body = body_path.read_text(encoding="utf-8")

        self.assertIn("## Summary", body)
        self.assertIn("## Why", body)
        self.assertIn("## Changes", body)
        self.assertNotIn("## Testing", body)

    def test_new_body_uses_configured_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body_path = root / "body.md"
            template_path = root / "template.md"
            template_path.write_text(
                "---\ntitle: {{ title }}\n---\n\nDirect summary.\n\n{{ autogen }}\n",
                encoding="utf-8",
            )

            update_body_file(
                body_path,
                "<!-- AUTOGEN -->",
                title="Layer title",
                template_path=template_path,
            )

            body = body_path.read_text(encoding="utf-8")

        self.assertIn('title: "Layer title"', body)
        self.assertIn("Direct summary.", body)
        self.assertIn("<!-- AUTOGEN -->", body)
        self.assertNotIn("{{ title }}", body)

    def test_autogen_is_compact_by_default(self) -> None:
        out = autogen_block(
            base_ref="main",
            pr_base="pr/base",
            stack_pos=1,
            stack_total=2,
            from_ref="a",
            to_ref="b",
            commits="2454222e59 Add render tests infrastructure.\n",
        )
        self.assertIn("### Patch Set", out)
        self.assertIn("Part `1/2` of a stacked series", out)
        self.assertIn("Depends on `pr/base`", out)
        self.assertNotIn("- Stack:", out)
        self.assertNotIn("2454222e59", out)
        self.assertNotIn("- Range:", out)
        self.assertNotIn("#### Commits", out)

    def test_single_layer_stack_omits_autogen_block(self) -> None:
        out = autogen_block(
            base_ref="main",
            pr_base="main",
            stack_pos=1,
            stack_total=1,
            from_ref="a",
            to_ref="b",
            commits="2454222e59 Single PR change.\n",
        )

        self.assertEqual(out, "")

    def test_empty_autogen_removes_existing_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            body_path = Path(directory) / "body.md"
            body_path.write_text(
                "## Summary\n\nDirect summary.\n\n"
                "<!-- AUTOGEN:BEGIN -->\n"
                "### Patch Set\n\n"
                "> Part `1/1` of a stacked series.\n"
                "<!-- AUTOGEN:END -->\n",
                encoding="utf-8",
            )

            update_body_file(body_path, "")
            body = body_path.read_text(encoding="utf-8")

        self.assertEqual(body, "## Summary\n\nDirect summary.\n")
        self.assertNotIn("AUTOGEN", body)

    def test_full_autogen_commits_format_sha_colon_subject(self) -> None:
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
                detail="full",
            )
        self.assertIn("- `2454222e59`: Add render tests infrastructure.", out)

    def test_full_autogen_commits_truncates_subject(self) -> None:
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
                detail="full",
            )
        # 10 chars max => 9 + ellipsis.
        self.assertIn("- `2454222e59`: " + ("x" * 9) + "…", out)

    def test_autogen_includes_optional_group(self) -> None:
        out = autogen_block(
            base_ref="main",
            pr_base="pr/base",
            stack_pos=3,
            stack_total=8,
            from_ref="a",
            to_ref="b",
            commits="",
            group="retained-core",
            group_title="Retained core and snapshots",
            group_pos=2,
            group_total=6,
        )
        self.assertIn("- Group: `retained-core` — Retained core and snapshots (`2/6`)", out)
