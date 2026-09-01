from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .proc import die


@dataclass(frozen=True)
class Dependency:
    name: str
    path: str
    repo: str
    branch: str


def dependency_conf_path(root: Path) -> Path:
    return root / ".devstack" / "dependencies.conf"


def read_dependencies(root: Path) -> list[Dependency]:
    path = dependency_conf_path(root)
    if not path.is_file():
        die(f"missing dependency config: {path}")
    result: list[Dependency] = []
    names: set[str] = set()
    paths: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 5 or parts[0] != "dependency":
            die(f"bad dependency directive in {path}: {raw}")
        dep = Dependency(parts[1], parts[2].rstrip("/"), parts[3], parts[4])
        if not dep.path or Path(dep.path).is_absolute() or ".." in Path(dep.path).parts:
            die(f"dependency path must be repository-relative: {dep.path}")
        if "/" not in dep.repo:
            die(f"dependency repo must be OWNER/REPO: {dep.repo}")
        if dep.name in names or dep.path in paths:
            die(f"duplicate dependency name or path: {dep.name} ({dep.path})")
        names.add(dep.name)
        paths.add(dep.path)
        result.append(dep)
    return result


def select_dependency(root: Path, selector: str) -> Dependency:
    matches = [dep for dep in read_dependencies(root) if selector in (dep.name, dep.path)]
    if not matches:
        die(f"unknown dependency: {selector}")
    return matches[0]
