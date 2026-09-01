from __future__ import annotations

import argparse
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.commands.stack import cmd_capture
from tools.devstack.core.stackconf import read_conf


def _git(root: Path, argv: list[str]) -> str:
    proc = subprocess.run(["git", *argv], cwd=root, check=True, capture_output=True, text=True)
    return (proc.stdout or "").strip()


class TestStackCapture(unittest.TestCase):
    def test_preserves_explicit_branch_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git(root, ["init"])
            _git(root, ["config", "user.email", "test@example.com"])
            _git(root, ["config", "user.name", "Test"])

            (root / "README").write_text("one\n", encoding="utf-8")
            _git(root, ["add", "README"])
            _git(root, ["commit", "-m", "one"])
            _git(root, ["branch", "stack/actual-one"])

            (root / "README").write_text("two\n", encoding="utf-8")
            _git(root, ["commit", "-am", "two"])
            _git(root, ["branch", "stack/actual-two"])

            conf_path = root / ".devstack" / "stack.conf"
            conf_path.parent.mkdir(parents=True)
            conf_path.write_text(
                "\n".join(
                    [
                        "base origin/main",
                        "github_mode native",
                        "github_repo example/repo",
                        "push_remote origin",
                        "",
                        "commit 001-pr-1 stack/actual-one HEAD~1",
                        "commit 002-pr-2 stack/actual-two HEAD",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("tools.devstack.commands.stack.repo_root", return_value=root):
                cmd_capture(argparse.Namespace())

            conf = read_conf(root)
            self.assertEqual([entry.branch for entry in conf.entries], ["stack/actual-one", "stack/actual-two"])
            text = conf_path.read_text(encoding="utf-8")
            self.assertIn("commit 001-pr-1 stack/actual-one ", text)
            self.assertIn("commit 002-pr-2 stack/actual-two ", text)


if __name__ == "__main__":
    unittest.main()
