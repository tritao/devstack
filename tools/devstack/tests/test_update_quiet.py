from __future__ import annotations

import argparse
import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.devstack.commands.stack import cmd_update


@contextlib.contextmanager
def chdir(path: Path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def run(cmd: list[str], cwd: Path) -> str:
    p = subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.stdout.strip()


class TestUpdateQuiet(unittest.TestCase):
    def test_update_no_output_when_up_to_date(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run(["git", "init"], root)
            run(["git", "config", "user.email", "devstack@test"], root)
            run(["git", "config", "user.name", "devstack"], root)
            (root / "f.txt").write_text("a\n", encoding="utf-8")
            run(["git", "add", "f.txt"], root)
            run(["git", "commit", "-m", "c1"], root)

            sha = run(["git", "rev-parse", "--short=10", "HEAD"], root)
            (root / ".devstack").mkdir()
            (root / ".devstack" / "stack.conf").write_text(
                "\n".join(
                    [
                        "base origin/main",
                        "pr_prefix pr/test/",
                        "",
                        f"001-layer {sha}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            run(["git", "branch", "-f", "pr/test/001-layer", sha], root)

            buf = io.StringIO()
            with chdir(root), contextlib.redirect_stdout(buf):
                cmd_update(argparse.Namespace())
            self.assertEqual("", buf.getvalue().strip())

    def test_update_no_output_when_checked_out_and_up_to_date(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run(["git", "init"], root)
            run(["git", "config", "user.email", "devstack@test"], root)
            run(["git", "config", "user.name", "devstack"], root)
            (root / "f.txt").write_text("a\n", encoding="utf-8")
            run(["git", "add", "f.txt"], root)
            run(["git", "commit", "-m", "c1"], root)

            sha = run(["git", "rev-parse", "--short=10", "HEAD"], root)
            (root / ".devstack").mkdir()
            (root / ".devstack" / "stack.conf").write_text(
                "\n".join(
                    [
                        "base origin/main",
                        "pr_prefix pr/test/",
                        "",
                        f"001-layer {sha}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            run(["git", "checkout", "-b", "pr/test/001-layer"], root)

            buf = io.StringIO()
            with chdir(root), contextlib.redirect_stdout(buf):
                cmd_update(argparse.Namespace())
            self.assertEqual("", buf.getvalue().strip())

    def test_update_prints_when_moving_branch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run(["git", "init"], root)
            run(["git", "config", "user.email", "devstack@test"], root)
            run(["git", "config", "user.name", "devstack"], root)
            (root / "f.txt").write_text("a\n", encoding="utf-8")
            run(["git", "add", "f.txt"], root)
            run(["git", "commit", "-m", "c1"], root)
            sha1 = run(["git", "rev-parse", "--short=10", "HEAD"], root)
            (root / "f.txt").write_text("b\n", encoding="utf-8")
            run(["git", "add", "f.txt"], root)
            run(["git", "commit", "-m", "c2"], root)

            (root / ".devstack").mkdir()
            (root / ".devstack" / "stack.conf").write_text(
                "\n".join(
                    [
                        "base origin/main",
                        "pr_prefix pr/test/",
                        "",
                        f"001-layer {sha1}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            # Branch currently points to HEAD (sha2), but config wants sha1.
            run(["git", "branch", "-f", "pr/test/001-layer", "HEAD"], root)

            buf = io.StringIO()
            with chdir(root), contextlib.redirect_stdout(buf):
                cmd_update(argparse.Namespace())
            out = buf.getvalue()
            self.assertIn("moved pr/test/001-layer ->", out)
            self.assertIn(sha1, out)

