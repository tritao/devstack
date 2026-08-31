from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from .proc import die, note


def ensure_external_build_dir(root: Path, env: Mapping[str, str] | None = None) -> Path | None:
    """Link ``<worktree>/build`` into DEVSTACK_BUILD_ROOT when configured."""
    values = os.environ if env is None else env
    configured = values.get("DEVSTACK_BUILD_ROOT", "").strip()
    if not configured:
        return None

    build_root = Path(configured).expanduser()
    if not build_root.is_absolute():
        die("DEVSTACK_BUILD_ROOT must be an absolute path")
    build_root = build_root.resolve()

    root = root.resolve()
    if not root.name:
        die(f"cannot derive worktree name from repository root: {root}")

    target = build_root / root.name
    local = root / "build"

    if local.is_symlink():
        actual = local.resolve(strict=False)
        if actual != target:
            die(f"build symlink points to {actual}, expected {target}")
        target.mkdir(parents=True, exist_ok=True)
        return target

    if local.exists():
        die(
            f"build path already exists and is not a symlink: {local}; "
            f"move it to {target} and replace it with a symlink"
        )

    target.mkdir(parents=True, exist_ok=True)
    local.symlink_to(target, target_is_directory=True)
    note(f"external build dir: {local} -> {target}")
    return target
