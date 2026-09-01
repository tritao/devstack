from __future__ import annotations

import json
from pathlib import Path


BUILD_DEFAULTS_PATH = Path(".devstack/build-defaults.json")


def load_build_defaults(root: Path) -> dict[str, bool]:
    path = root / BUILD_DEFAULTS_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, bool)}


def write_build_defaults(root: Path, *, sandbox_paths: bool, ccache_launcher: bool) -> Path:
    path = root / BUILD_DEFAULTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "sandbox_paths": sandbox_paths,
        "ccache_launcher": ccache_launcher,
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path
