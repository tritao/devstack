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
    return (p.stdout or "").strip()


class TestUpdateStandalone(unittest.TestCase):
    def test_update_standalone_generates_independent_layer_branches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run(["git", "init"], root)
            run(["git", "config", "user.email", "devstack@test"], root)
            run(["git", "config", "user.name", "devstack"], root)

            (root / ".gitignore").write_text(".devstack/\n", encoding="utf-8")
            (root / "base.txt").write_text("base\n", encoding="utf-8")
            run(["git", "add", ".gitignore", "base.txt"], root)
            run(["git", "commit", "-m", "base"], root)
            base = run(["git", "rev-parse", "HEAD"], root)

            (root / "a.txt").write_text("c1\n", encoding="utf-8")
            run(["git", "add", "a.txt"], root)
            run(["git", "commit", "-m", "c1"], root)
            sha1 = run(["git", "rev-parse", "--short=10", "HEAD"], root)

            (root / "b.txt").write_text("c2\n", encoding="utf-8")
            run(["git", "add", "b.txt"], root)
            run(["git", "commit", "-m", "c2"], root)
            sha2 = run(["git", "rev-parse", "--short=10", "HEAD"], root)

            (root / ".devstack").mkdir()
            (root / ".devstack" / "stack.conf").write_text(
                "\n".join(
                    [
                        f"base {base}",
                        "pr_prefix pr/test/",
                        "",
                        f"001-layer {sha1}",
                        f"002-layer {sha2}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with chdir(root), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                cmd_update(argparse.Namespace(standalone=True, only=None))

            commits_1 = run(["git", "log", "--format=%s", f"{base}..pr/test/001-layer"], root).splitlines()
            commits_2 = run(["git", "log", "--format=%s", f"{base}..pr/test/002-layer"], root).splitlines()
            self.assertEqual(["c1"], commits_1)
            self.assertEqual(["c2"], commits_2)

            # Running again should be a no-op (no output).
            buf = io.StringIO()
            with chdir(root), contextlib.redirect_stdout(buf):
                cmd_update(argparse.Namespace(standalone=True, only=None))
            self.assertEqual("", buf.getvalue().strip())
