from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.setup import cmd_machine_setup


class TestMachineSetup(unittest.TestCase):
    def test_writes_idempotent_machine_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            golden = base / "FreeCAD-master"
            golden.mkdir()
            values = argparse.Namespace(
                golden_dir=str(golden),
                worktree_root=str(base / "FreeCAD-worktrees"),
                build_root=str(base / "DATA" / "freecad-builds"),
                ccache_dir=str(base / "DATA" / "ccache"),
                ccache_max_size="12G",
                bin_dir=str(base / "bin"),
                env_file=str(base / "config" / "devstack" / "env.sh"),
                ccache_config=str(base / "config" / "ccache" / "ccache.conf"),
                no_codex_instructions=False,
            )

            def fake_git(argv: list[str], **_: object) -> str:
                if argv == ["rev-parse", "--git-common-dir"]:
                    return ".git"
                return str(golden)

            with (
                patch("tools.devstack.commands.setup.git", side_effect=fake_git),
                patch.dict("os.environ", {"CODEX_HOME": str(base / "codex")}, clear=True),
            ):
                cmd_machine_setup(values)
                cmd_machine_setup(values)

            ds = base / "bin" / "ds"
            self.assertTrue(ds.exists())
            self.assertTrue(ds.stat().st_mode & 0o111)
            env = (base / "config" / "devstack" / "env.sh").read_text()
            self.assertEqual(1, env.count("# >>> devstack machine setup >>>"))
            self.assertIn(f"DEVSTACK_GOLDEN_ROOT={golden}", env)
            self.assertIn(f"DEVSTACK_WORKTREE_ROOT={base / 'FreeCAD-worktrees'}", env)
            self.assertIn(f"CCACHE_CONFIGPATH={base / 'config' / 'ccache' / 'ccache.conf'}", env)
            ccache = (base / "config" / "ccache" / "ccache.conf").read_text()
            self.assertIn("max_size = 12G", ccache)
            agents = (base / "codex" / "AGENTS.md").read_text()
            self.assertEqual(1, agents.count("# >>> devstack FreeCAD workflow >>>"))
            self.assertIn("## Devstack publication safety", agents)
            self.assertIn("ds gh-sync --apply-plan <file>", agents)
            self.assertIn("including Coin worktrees", agents)
            excludes = (golden / ".git" / "info" / "exclude").read_text()
            self.assertIn("/CMakeUserPresets.json", excludes)
