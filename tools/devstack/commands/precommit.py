from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from tools.devstack.core.git import git, repo_root, resolve_commitish
from tools.devstack.core.proc import die, run
from tools.devstack.core.stackconf import StackConfig, filtered_mode, read_conf


def layer_range(root: Path, conf: StackConfig, layer: int) -> tuple[str, str]:
    if layer < 1 or layer > len(conf.entries):
        die(f"--layer must be 1..{len(conf.entries)}")
    entry = conf.entries[layer - 1]
    base = conf.base_remote_ref if layer == 1 else conf.entries[layer - 2].sha
    tip = entry.branch if filtered_mode(conf) else entry.sha
    return resolve_commitish(root, base), resolve_commitish(root, tip)


def _precommit_command(base: str, tip: str) -> list[str]:
    return ["pre-commit", "run", "--from-ref", base, "--to-ref", tip, "--show-diff-on-failure"]


def _require_precommit() -> None:
    if shutil.which("pre-commit") is None:
        die("pre-commit is required; install it with `python3 -m pip install --user pre-commit`")


def check_layer_in_temporary_worktree(root: Path, conf: StackConfig, layer: int) -> None:
    """Validate one layer without allowing hooks to modify the source worktree."""
    if not (root / ".pre-commit-config.yaml").is_file():
        return
    _require_precommit()
    base, tip = layer_range(root, conf, layer)
    with tempfile.TemporaryDirectory(prefix="devstack-precommit-") as directory:
        worktree = Path(directory) / "worktree"
        run(["git", "worktree", "add", "--quiet", "--detach", str(worktree), tip], cwd=root)
        try:
            proc = run(_precommit_command(base, tip), cwd=worktree, check=False, capture=True)
            dirty = git(["status", "--short"], cwd=worktree)
            if proc.returncode != 0 or dirty:
                output = "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part and part.strip())
                details = f"\n{output}" if output else ""
                if dirty:
                    details += f"\nFiles modified by hooks:\n{dirty}"
                die(f"pre-commit validation failed for layer {layer}{details}")
        finally:
            run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root, check=False, capture=True)


def run_precommit_gate(root: Path, conf: StackConfig, only: int | None) -> None:
    if getattr(conf, "precommit_check", "auto") == "off" or not (root / ".pre-commit-config.yaml").is_file():
        return
    layers = [only] if only is not None else list(range(1, len(conf.entries) + 1))
    for layer in layers:
        print(f"pre-commit: checking layer {layer}/{len(conf.entries)}")
        check_layer_in_temporary_worktree(root, conf, layer)


def cmd_precommit(args: argparse.Namespace) -> None:
    root = repo_root()
    conf = read_conf(root)
    layer = int(args.layer)
    if bool(getattr(args, "check", False)):
        check_layer_in_temporary_worktree(root, conf, layer)
        print(f"pre-commit: layer {layer} passed")
        return

    _require_precommit()
    base, tip = layer_range(root, conf, layer)
    head = resolve_commitish(root, "HEAD")
    if head != tip:
        die(f"layer {layer} ends at {tip[:12]}, but HEAD is {head[:12]}; check out that layer before applying fixes")
    if git(["status", "--porcelain"], cwd=root):
        die("worktree has uncommitted changes; commit or stash them before running pre-commit fixes")
    proc = run(_precommit_command(base, tip), cwd=root, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    print(f"pre-commit: layer {layer} passed")
