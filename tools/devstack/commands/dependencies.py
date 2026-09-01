from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.devstack.core.dependencies import Dependency, read_dependencies, select_dependency
from tools.devstack.core.git import git, repo_root
from tools.devstack.core.proc import die, note, run
from tools.devstack.core.stackconf import read_conf


def _gitlink_sha(root: Path, path: str, treeish: str = "HEAD") -> str:
    command = ["git", "ls-files", "--stage", "--", path] if treeish == ":" else ["git", "ls-tree", treeish, "--", path]
    proc = run(command, cwd=root, capture=True, check=False)
    fields = (proc.stdout or "").strip().split()
    if len(fields) < 4 or fields[0] != "160000":
        return ""
    return fields[1] if treeish == ":" else fields[2]


def _worktree_sha(root: Path, path: str) -> str:
    submodule = root / path
    if not (submodule / ".git").exists() and not (submodule / ".git").is_file():
        return ""
    proc = run(["git", "rev-parse", "HEAD"], cwd=submodule, capture=True, check=False)
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def _submodule_dirty(root: Path, path: str) -> bool:
    submodule = root / path
    if not _worktree_sha(root, path):
        return False
    return bool(git(["status", "--porcelain"], cwd=submodule).strip())


def _remote_branch_sha(dep: Dependency) -> str:
    url = f"https://github.com/{dep.repo}.git"
    proc = run(["git", "ls-remote", "--heads", url, f"refs/heads/{dep.branch}"], capture=True, check=False)
    if proc.returncode != 0:
        die(f"cannot read dependency remote: {dep.repo}")
    fields = (proc.stdout or "").strip().split()
    return fields[0] if fields else ""


def _select_stack_layer(source: Path, layer: str):
    conf = read_conf(source)
    if not conf.entries:
        die(f"source stack has no layers: {source}")
    if not layer or layer == "top":
        return conf, conf.entries[-1]
    matches = [entry for entry in conf.entries if layer in (entry.key, entry.branch)]
    if layer.isdigit():
        index = int(layer)
        if 1 <= index <= len(conf.entries):
            matches.append(conf.entries[index - 1])
    unique = {entry.key: entry for entry in matches}
    if len(unique) != 1:
        die(f"unknown or ambiguous source stack layer: {layer}")
    return conf, next(iter(unique.values()))


def dependency_status(root: Path, dep: Dependency) -> dict[str, object]:
    pinned = _gitlink_sha(root, dep.path)
    checked_out = _worktree_sha(root, dep.path)
    remote = _remote_branch_sha(dep)
    return {
        "name": dep.name,
        "path": dep.path,
        "repo": dep.repo,
        "branch": dep.branch,
        "pinned_sha": pinned,
        "checked_out_sha": checked_out,
        "remote_sha": remote,
        "initialized": bool(checked_out),
        "dirty": _submodule_dirty(root, dep.path),
        "checkout_matches_pin": bool(checked_out and checked_out == pinned),
        "pin_matches_remote": bool(pinned and pinned == remote),
    }


def cmd_dep_status(args: argparse.Namespace) -> None:
    root = repo_root()
    dependencies = [select_dependency(root, args.dependency)] if args.dependency else read_dependencies(root)
    statuses = [dependency_status(root, dep) for dep in dependencies]
    if args.json:
        print(json.dumps(statuses, indent=2, sort_keys=True))
        return
    for status in statuses:
        print(f"Dependency:       {status['name']}")
        print(f"Path:             {status['path']}")
        print(f"Repository:       {status['repo']}")
        print(f"Tracked branch:   {status['branch']}")
        print(f"Pinned SHA:       {status['pinned_sha'] or '(missing gitlink)'}")
        print(f"Checked out SHA:  {status['checked_out_sha'] or '(not initialized)'}")
        print(f"Remote SHA:       {status['remote_sha'] or '(missing branch)'}")
        print(f"Dirty:            {'yes' if status['dirty'] else 'no'}")
        print(f"Checkout locked:  {'yes' if status['checkout_matches_pin'] else 'no'}")
        print(f"Published pin:    {'yes' if status['pin_matches_remote'] else 'no'}")


def cmd_dep_pin(args: argparse.Namespace) -> None:
    root = repo_root()
    dep = select_dependency(root, args.dependency)
    source = Path(args.from_stack).expanduser().resolve()
    conf, entry = _select_stack_layer(source, args.layer)
    selected_sha = git(["rev-parse", f"{entry.sha}^{{commit}}"], cwd=source)
    if conf.github_repo and conf.github_repo != dep.repo:
        die(f"source stack repository is {conf.github_repo}, expected {dep.repo}")
    if entry.branch != dep.branch:
        note(f"selected layer branch differs from configured tracked branch: {entry.branch} (using selected layer)")
        dep = Dependency(dep.name, dep.path, dep.repo, entry.branch)

    remote_sha = _remote_branch_sha(dep)
    if not remote_sha:
        die(f"dependency branch is not published: {dep.repo}:{dep.branch}")
    if remote_sha != selected_sha:
        die(
            f"selected dependency commit is not the published branch head\n"
            f"branch:   {dep.repo}:{dep.branch}\n"
            f"selected: {selected_sha}\n"
            f"remote:   {remote_sha}"
        )

    old_sha = _gitlink_sha(root, dep.path)
    if not old_sha:
        die(f"path is not a committed submodule gitlink: {dep.path}")
    staged_sha = _gitlink_sha(root, dep.path, ":")
    if staged_sha and staged_sha != old_sha:
        die(f"dependency gitlink already has a staged update: {dep.path}")
    if _submodule_dirty(root, dep.path):
        die(f"dependency submodule has local changes: {dep.path}")

    print(f"Dependency:       {dep.name}")
    print(f"Path:             {dep.path}")
    print(f"Repository:       {dep.repo}")
    print(f"Source layer:     {entry.key}")
    print(f"Source branch:    {entry.branch}")
    print(f"Current pin:      {old_sha}")
    print(f"Proposed pin:     {selected_sha}")
    print("Published:        yes")
    if not args.apply:
        print("Dry run only; rerun with --apply to update and stage the gitlink.")
        return
    if old_sha == selected_sha and _worktree_sha(root, dep.path) == selected_sha:
        print("Already pinned and checked out.")
        return

    submodule = root / dep.path
    if not _worktree_sha(root, dep.path):
        run(["git", "submodule", "update", "--init", "--", dep.path], cwd=root)
    run(["git", "fetch", "origin", dep.branch], cwd=submodule)
    run(["git", "checkout", "--detach", selected_sha], cwd=submodule)
    run(["git", "add", "--", dep.path], cwd=root)
    if _gitlink_sha(root, dep.path, ":") != selected_sha:
        die(f"failed to stage dependency gitlink: {dep.path}")
    print(f"Updated and staged {dep.path} at {selected_sha}")
