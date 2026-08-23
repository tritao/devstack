from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.devstack.commands.bodies import cmd_body_context


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


class TestBodyContext(unittest.TestCase):
    def test_body_context_does_not_print_diffstat_section(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run(["git", "init"], root)
            run(["git", "config", "user.email", "devstack@test"], root)
            run(["git", "config", "user.name", "devstack"], root)

            (root / "a.txt").write_text("a\n", encoding="utf-8")
            run(["git", "add", "a.txt"], root)
            run(["git", "commit", "-m", "base"], root)
            base = run(["git", "rev-parse", "HEAD"], root)

            (root / "a.txt").write_text("b\n", encoding="utf-8")
            run(["git", "add", "a.txt"], root)
            run(["git", "commit", "-m", "change"], root)
            tip = run(["git", "rev-parse", "HEAD"], root)

            (root / ".devstack").mkdir()
            (root / ".devstack" / "stack.conf").write_text(
                "\n".join(
                    [
                        f"base {base}",
                        "pr_prefix pr/test/",
                        "",
                        f"001-layer {tip}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            buf = io.StringIO()
            with chdir(root), contextlib.redirect_stdout(buf):
                cmd_body_context(type("Args", (), {"branch": ""})())

            out = buf.getvalue()
            self.assertNotIn("Top Files By Churn", out)

