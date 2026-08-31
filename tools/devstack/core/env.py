from __future__ import annotations

import subprocess
from pathlib import Path
import os

from .proc import die, have_cmd


def parse_env0(data: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in data.split(b"\0"):
        if not item:
            continue
        if b"=" not in item:
            continue
        k, v = item.split(b"=", 1)
        out[k.decode("utf-8", errors="replace")] = v.decode("utf-8", errors="replace")
    return out


def load_env_from_sh(path: Path, base_env: dict[str, str]) -> dict[str, str]:
    if not have_cmd("bash"):
        die("bash not found (required for --env-file)")
    if not path.is_file():
        die(f"env file not found: {path}")
    try:
        proc = subprocess.run(
            ["bash", "-lc", 'set -a; source "$1"; env -0', "bash", str(path)],
            check=True,
            env=base_env,
            stdout=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        die(f"failed to load env file: {path} (exit {exc.returncode})")
    return parse_env0(proc.stdout or b"")


def load_devstack_env(base_env: dict[str, str] | None = None, root: Path | None = None) -> dict[str, str]:
    """Load the configured Devstack env file using build-command precedence."""
    env = dict(os.environ if base_env is None else base_env)
    configured = env.get("DEVSTACK_ENV_FILE", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    if root is not None:
        candidates.append(root / ".devstack" / "env.sh")
    candidates.append(Path.home() / ".config" / "devstack" / "env.sh")
    for candidate in candidates:
        if candidate.is_file():
            return load_env_from_sh(candidate, env)
    return env
