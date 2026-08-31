from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from tools.devstack.core.git import (
    current_branch,
    default_base_remote_ref,
    default_stack_remote,
    git,
    repo_root,
    sanitize_branch_to_conf_name,
)
from tools.devstack.core.proc import die, note, run
from tools.devstack.core.stackconf import default_body_dir, read_conf, stack_name_from_conf

def default_pr_prefix_for_branch(root: Path, conf_path: Path) -> str:
    b = current_branch(root)
    if not b:
        return f"pr/{stack_name_from_conf(conf_path)}/"
    leaf = sanitize_branch_to_conf_name(b.split("/")[-1])
    return f"pr/{leaf}/"

def _ensure_stack_conf_and_bodies_dir(root: Path, *, force_conf: bool, quiet: bool) -> Path:
    stack_dir = root / ".devstack"
    conf_path = stack_dir / "stack.conf"

    if conf_path.exists() and not force_conf:
        if not quiet:
            note(f"{conf_path} already exists (use --force-conf to overwrite)")
    else:
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        base_remote_ref = default_base_remote_ref(root)
        pr_prefix = default_pr_prefix_for_branch(root, conf_path)
        body_dir = default_body_dir(root, conf_path, pr_prefix)
        conf_path.write_text(
            "\n".join(
                [
                    "# Cut-point branches for stacked PRs (GitHub).",
                    "#",
                    "# This file is local-only (gitignored). Fill in cut points as you decide how to split your branch.",
                    "#",
                    "# Config directives:",
                    "#   base <remote>/<branch>         Base branch for the first PR (default: origin/main)",
                    "#   pr_prefix <prefix/>            Prefix to apply to branch keys (optional)",
                    "#   body_dir <path>                PR body directory for this stack (optional)",
                    "#   cut_prefix <prefix/>           Source cut-point branch prefix (optional; used when ignore is enabled)",
                    "#   ignore <commit-ish|ref>        Exclude commit from generated PR branches (optional; enables filtered mode)",
                    "#",
                    "# Stack entries:",
                    "#   <branch-key-or-name> <commit-ish> [body-file]",
                    "",
                    f"base {base_remote_ref}",
                    "",
                    f"pr_prefix {pr_prefix}",
                    "",
                    f"body_dir {body_dir}",
                    "",
                    "# Example:",
                    "# 001-my-layer <sha>",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        if not quiet:
            print(f"created {conf_path}")

    conf = read_conf(root)
    body_dir_path = Path(conf.body_dir)
    if not body_dir_path.is_absolute():
        body_dir_path = (root / body_dir_path).resolve()
    body_dir_path.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(f"ensured {body_dir_path}")

    return conf_path

def cmd_init(args: argparse.Namespace) -> None:
    root = repo_root()
    force = bool(getattr(args, "force", False))
    mode = getattr(args, "mode", "copy")
    force_conf = force or bool(getattr(args, "force_conf", False))

    # Back-compat: these flags used to control installing .devstack/devstack.py|.sh.
    # Devstack now runs from a single checkout (typically via the `ds` shell alias), so
    # these are ignored.
    force_script = force or bool(getattr(args, "force_script", False))
    if force_script or mode != "copy":
        note("init: --copy/--symlink/--force-script are deprecated and are now ignored")

    conf_path = _ensure_stack_conf_and_bodies_dir(root, force_conf=force_conf, quiet=False)

    print()
    print("next:")
    print(f"  edit: {conf_path}")
    devstack_py = (Path(__file__).resolve().parents[1] / "devstack.py").resolve()
    print("  then: ds list")
    print(f"  # or: python3 {devstack_py} list")


def worktree_list_paths(root: Path) -> list[Path]:
    proc = run(["git", "worktree", "list", "--porcelain"], cwd=root, capture=True)
    paths: list[Path] = []
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.split(" ", 1)[1]).resolve())
    return paths


def worktree_current_branch(wt: Path) -> str:
    try:
        b = git(["branch", "--show-current"], cwd=wt)
        if b:
            return b
    except subprocess.CalledProcessError:
        pass
    try:
        bisect_path = Path(git(["rev-parse", "--git-path", "BISECT_START"], cwd=wt))
        if bisect_path.is_file():
            return bisect_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    return ""


def import_devstack_for_branch(from_root: Path, to_dir: Path, branch: str) -> None:
    stack_name = sanitize_branch_to_conf_name(branch)
    dst_conf = to_dir / ".devstack" / "stack.conf"
    if not dst_conf.exists():
        # Prefer legacy per-branch config storage if it exists in import_from.
        src_legacy = from_root / ".devstack" / "stacks" / f"{stack_name}.conf"
        src_conf: Optional[Path] = None
        if src_legacy.is_file():
            src_conf = src_legacy
        else:
            # Otherwise only copy stack.conf if the import_from worktree is on the same branch.
            src_stack_conf = from_root / ".devstack" / "stack.conf"
            if src_stack_conf.is_file() and current_branch(from_root) == branch:
                src_conf = src_stack_conf

        if src_conf and src_conf.is_file():
            dst_conf.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_conf, dst_conf)
            if src_conf.parent.name == "stacks":
                ensure_body_dir_directive(dst_conf, f".devstack/pr-bodies/{src_conf.stem}")
            print(f"imported stack config: {dst_conf}")

    src_bodies = from_root / ".devstack" / "pr-bodies" / stack_name
    dst_bodies = to_dir / ".devstack" / "pr-bodies" / stack_name
    if src_bodies.is_dir() and not dst_bodies.exists():
        dst_bodies.mkdir(parents=True, exist_ok=True)
        for item in src_bodies.iterdir():
            if item.is_file():
                shutil.copy2(item, dst_bodies / item.name)
        print(f"imported pr bodies: {dst_bodies}")

    src_readme = from_root / ".devstack" / "README.md"
    dst_readme = to_dir / ".devstack" / "README.md"
    if src_readme.is_file() and not dst_readme.exists():
        dst_readme.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_readme, dst_readme)


def cmd_wt_sync(args: argparse.Namespace) -> None:
    root = repo_root()
    dry = bool(args.dry_run)
    import_enabled = not args.no_import
    import_from = Path(args.import_from).resolve() if args.import_from else root
    # Back-compat: these flags used to control syncing per-worktree devstack scripts.
    # Devstack now runs from a single checkout, so they are ignored.
    mode = getattr(args, "mode", "copy")
    no_force_script = bool(getattr(args, "no_force_script", False))
    if mode != "copy" or no_force_script:
        note("wt-sync: --copy/--symlink/--no-force-script are deprecated and are now ignored")

    print(f"syncing devstack state to worktrees (import={1 if import_enabled else 0})", flush=True)

    for wt in worktree_list_paths(root):
        b = worktree_current_branch(wt)
        print(f"- {wt}{f' ({b})' if b else ''}", flush=True)
        if dry:
            continue
        try:
            if import_enabled and b:
                import_devstack_for_branch(import_from, wt, b)
            wt_root = repo_root(wt)
            _ensure_stack_conf_and_bodies_dir(wt_root, force_conf=False, quiet=True)
        except SystemExit as exc:
            note(f"wt-sync failed for {wt}: {exc}")
            continue
        except Exception as exc:
            note(f"wt-sync failed for {wt}: {exc}")
            continue


def cmd_wt_feature(args: argparse.Namespace) -> None:
    root = repo_root()
    base_default = default_base_remote_ref(root)

    name = args.name
    branch = args.branch or f"feature/{name}"
    base_ref = args.base or base_default
    safe = sanitize_branch_to_conf_name(name)
    series = _infer_repo_series_name(root)
    dir_path = Path(args.dir).resolve() if args.dir else (root.parent / f"{series}-wt-{safe}").resolve()
    if dir_path.exists():
        die(f"worktree path already exists: {dir_path}")
    try:
        git(["show-ref", "--verify", f"refs/heads/{feature_branch}"], cwd=golden)
    except subprocess.CalledProcessError:
        pass
    else:
        die(f"feature branch already exists: {feature_branch}")

    print("creating worktree:")
    print(f"  branch: {branch}")
    print(f"  base:   {base_ref}")
    print(f"  path:   {dir_path}")

    try:
        run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=root, capture=True)
        exists = True
    except subprocess.CalledProcessError:
        exists = False

    if exists:
        run(["git", "worktree", "add", str(dir_path), branch], cwd=root)
    else:
        run(["git", "worktree", "add", "-b", branch, str(dir_path), base_ref], cwd=root)

    devstack_py = (Path(__file__).resolve().parents[1] / "devstack.py").resolve()
    run(["python3", str(devstack_py), "init"], cwd=dir_path)

    if args.build:
        build_args = [
            "build",
            "--preset",
            args.preset,
            "--adapter",
            getattr(args, "adapter", os.environ.get("DEVSTACK_ADAPTER", "auto")),
            "--toolchain",
            args.toolchain,
            "--build-mode",
            args.build_mode,
        ]
        if args.jobs is not None:
            build_args += ["--jobs", str(args.jobs)]
        if args.core:
            build_args.append("--core")
        if args.clang_mold:
            build_args.append("--clang-mold")
        if args.distcc:
            build_args.append("--distcc")
        if getattr(args, 'no_distcc', False):
            build_args.append("--no-distcc")
        if args.distcc_hosts:
            build_args += ["--distcc-hosts", args.distcc_hosts]
        if args.distcc_verbose:
            build_args.append("--distcc-verbose")
        if args.ccache_launcher:
            build_args.append("--ccache-launcher")
        if args.env_file:
            build_args += ["--env-file", args.env_file]
        if args.no_env_file:
            build_args.append("--no-env-file")
        if args.target:
            build_args += ["--target", args.target]
        if args.clean:
            build_args.append("--clean")
        run(["python3", str(devstack_py), *build_args], cwd=dir_path)

    print()
    print("next:")
    print(f"  cd {dir_path}")
    print("  ds list")
    print(f"  # or: python3 {devstack_py} list")


def cmd_wt_fresh(args: argparse.Namespace) -> None:
    """Refresh and build a pristine baseline before creating a feature worktree."""
    current_root = repo_root()
    golden = Path(args.golden_dir).expanduser().resolve() if args.golden_dir else current_root
    golden = repo_root(golden)
    remote = args.remote
    main_branch = args.main_branch

    dirty = git(["status", "--porcelain", "--untracked-files=all"], cwd=golden)
    if dirty:
        die(f"golden checkout is not pristine: {golden}\n{dirty}")
    branch_now = current_branch(golden)
    if branch_now != main_branch:
        die(f"golden checkout must be on {main_branch}, currently on {branch_now or 'detached HEAD'}")

    name = args.name
    feature_branch = args.branch or f"feature/{name}"
    safe = sanitize_branch_to_conf_name(name)
    series = golden.name.removesuffix("-master")
    configured_root = os.environ.get("DEVSTACK_WORKTREE_ROOT", "").strip()
    worktree_root = Path(configured_root).expanduser().resolve() if configured_root else golden.parent / f"{series}-worktrees"
    dir_path = Path(args.dir).expanduser().resolve() if args.dir else (worktree_root / safe).resolve()
    if dir_path.exists():
        die(f"worktree path already exists: {dir_path}")

    devstack_py = (Path(__file__).resolve().parents[1] / "devstack.py").resolve()
    print("refreshing golden checkout:")
    print(f"  path:   {golden}")
    print(f"  update: {main_branch} onto {remote}/{main_branch}")
    run(["git", "fetch", remote, main_branch], cwd=golden)
    run(["git", "rebase", f"{remote}/{main_branch}"], cwd=golden)

    build_args = [
        "python3",
        str(devstack_py),
        "build",
        "--preset",
        args.preset,
        "--toolchain",
        "clang-mold",
        "--ccache-launcher",
    ]
    if args.jobs is not None:
        build_args += ["--jobs", str(args.jobs)]
    run(build_args, cwd=golden)

    # Creating the worktree is deliberately last: update or build failures leave
    # no half-created feature checkout behind.
    create_args = [
        "python3",
        str(devstack_py),
        "wt-init",
        name,
        "--base",
        "HEAD",
        "--branch",
        feature_branch,
        "--dir",
        str(dir_path),
    ]
    run(create_args, cwd=golden)


def cmd_wt_add(args: argparse.Namespace) -> None:
    root = repo_root()
    remote = default_stack_remote(root)
    branch = args.branch

    work_branch = branch
    try:
        run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=root, capture=True)
        exists_local = True
    except subprocess.CalledProcessError:
        exists_local = False

    if not exists_local:
        try:
            run(["git", "show-ref", "--verify", "--quiet", f"refs/remotes/{branch}"], cwd=root, capture=True)
            exists_remote = True
        except subprocess.CalledProcessError:
            exists_remote = False
        if exists_remote:
            local_branch = branch
            if branch.startswith(f"{remote}/"):
                local_branch = branch[len(remote) + 1 :]
            try:
                run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{local_branch}"], cwd=root, capture=True)
            except subprocess.CalledProcessError:
                run(["git", "branch", local_branch, branch], cwd=root)
            work_branch = local_branch
        else:
            die(f"unknown branch/ref: {branch}")

    safe = sanitize_branch_to_conf_name(work_branch)
    series = _infer_repo_series_name(root)
    dir_path = Path(args.dir).resolve() if args.dir else (root.parent / f"{series}-wt-{safe}").resolve()
    if dir_path.exists():
        die(f"worktree path already exists: {dir_path}")

    print("creating worktree:")
    print(f"  branch: {work_branch}")
    print(f"  path:   {dir_path}")
    run(["git", "worktree", "add", str(dir_path), work_branch], cwd=root)

    if not args.no_import:
        import_devstack_for_branch(Path(args.import_from).resolve() if args.import_from else root, dir_path, work_branch)

    devstack_py = (Path(__file__).resolve().parents[1] / "devstack.py").resolve()
    run(["python3", str(devstack_py), "init"], cwd=dir_path)

    if args.build:
        build_args = [
            "build",
            "--preset",
            args.preset,
            "--adapter",
            getattr(args, "adapter", os.environ.get("DEVSTACK_ADAPTER", "auto")),
            "--toolchain",
            args.toolchain,
            "--build-mode",
            args.build_mode,
        ]
        if args.jobs is not None:
            build_args += ["--jobs", str(args.jobs)]
        if args.core:
            build_args.append("--core")
        if args.clang_mold:
            build_args.append("--clang-mold")
        if args.distcc:
            build_args.append("--distcc")
        if getattr(args, 'no_distcc', False):
            build_args.append("--no-distcc")
        if args.distcc_hosts:
            build_args += ["--distcc-hosts", args.distcc_hosts]
        if args.distcc_verbose:
            build_args.append("--distcc-verbose")
        if args.ccache_launcher:
            build_args.append("--ccache-launcher")
        if args.env_file:
            build_args += ["--env-file", args.env_file]
        if args.no_env_file:
            build_args.append("--no-env-file")
        if args.target:
            build_args += ["--target", args.target]
        if args.clean:
            build_args.append("--clean")
        run(["python3", str(devstack_py), *build_args], cwd=dir_path)

    print()
    print("next:")
    print(f"  cd {dir_path}")
    print("  ds list")
    print(f"  # or: python3 {devstack_py} list")


def _infer_repo_series_name(root: Path) -> str:
    name = root.name
    if "-wt-" in name:
        return name.split("-wt-", 1)[0]
    return name


def _copy_stack_state(from_root: Path, to_dir: Path) -> None:
    """Copy stack.conf + PR bodies into the new worktree (best-effort)."""
    try:
        conf = read_conf(from_root)
    except SystemExit:
        return

    dst_conf = to_dir / ".devstack" / "stack.conf"
    if not dst_conf.exists():
        try:
            dst_conf.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(conf.path, dst_conf)
        except OSError:
            pass

    # Copy PR bodies (small; helps `--layer` usage in the new worktree).
    src_bodies = (from_root / conf.body_dir).resolve()
    dst_bodies = (to_dir / conf.body_dir).resolve()
    if src_bodies.is_dir() and not dst_bodies.exists():
        try:
            dst_bodies.mkdir(parents=True, exist_ok=True)
            for item in src_bodies.iterdir():
                if item.is_file():
                    shutil.copy2(item, dst_bodies / item.name)
        except OSError:
            pass


def cmd_wt_layer(args: argparse.Namespace) -> None:
    root = repo_root()
    conf = read_conf(root)

    layer = int(args.layer)
    if layer < 1 or layer > len(conf.entries):
        die(f"layer must be 1..{len(conf.entries)}")

    view = (args.view or "source").strip().lower()
    if view not in ("source", "pr"):
        die("--view must be one of: source|pr")

    entry = conf.entries[layer - 1]
    stack_name = stack_name_from_conf(conf.path)
    key_safe = sanitize_key_to_filename(entry.key)

    # Resolve the ref to check out.
    ref: str
    if view == "source":
        if filtered_mode(conf):
            ref = cut_branch_for_entry(conf, entry)
            try:
                run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{ref}"], cwd=root)
            except subprocess.CalledProcessError:
                die(f"missing cut branch for layer {layer}: {ref} (run: ds update)")
        else:
            ensure_commit_exists(root, entry.sha)
            ref = entry.sha
    else:
        # PR view is for inspection; do not commit directly on generated branches in filtered mode.
        ref = entry.branch
        try:
            run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{ref}"], cwd=root)
        except subprocess.CalledProcessError:
            # Fall back to the SHA if the PR branch doesn't exist yet.
            ensure_commit_exists(root, entry.sha)
            ref = entry.sha

    series = _infer_repo_series_name(root)
    default_dir = root.parent / f"{series}-wt-layer-{key_safe}{'-pr' if view == 'pr' else ''}"
    dir_path = Path(args.dir).resolve() if args.dir else default_dir.resolve()
    if dir_path.exists():
        die(f"worktree path already exists: {dir_path}")

    branch = (args.branch or "").strip()
    if not branch and view == "source":
        branch = f"layer/{sanitize_branch_to_conf_name(stack_name)}/{key_safe}"

    print("creating worktree:")
    print(f"  dir:    {dir_path}")
    print(f"  view:   {view}")
    print(f"  ref:    {ref}")
    if branch:
        print(f"  branch: {branch}")

    def branch_worktree_paths(branch_name: str) -> list[str]:
        try:
            out = git(["worktree", "list", "--porcelain"], cwd=root)
        except subprocess.CalledProcessError:
            return []
        current_path = ""
        paths: list[str] = []
        for line in out.splitlines():
            if line.startswith("worktree "):
                current_path = line.split(" ", 1)[1].strip()
                continue
            if line.startswith("branch "):
                b = line.split(" ", 1)[1].strip()
                if b == f"refs/heads/{branch_name}" and current_path:
                    paths.append(current_path)
        return paths

    if branch:
        try:
            run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=root)
            if not getattr(args, "force", False):
                die(f"branch already exists: {branch} (use --branch to pick a different name, or --force)")
            if current_branch(root) == branch:
                die(f"refusing to delete currently checked out branch: {branch}")
            paths = branch_worktree_paths(branch)
            if paths:
                die(f"refusing to delete {branch}; checked out in worktree(s): {', '.join(paths)}")
            run(["git", "branch", "-D", branch], cwd=root, check=True)
        except subprocess.CalledProcessError:
            pass
        run(["git", "worktree", "add", "-b", branch, str(dir_path), ref], cwd=root)
    else:
        run(["git", "worktree", "add", str(dir_path), ref], cwd=root)

    _copy_stack_state(root, dir_path)

    print()
    print("next:")
    print(f"  cd {dir_path}")
    if view == "pr":
        print("  # PR view is for inspection; avoid committing here if you use `ignore`/filtered stacks.")
    else:
        print("  # Make changes and commit here; then bring them back via rebase/cherry-pick on your main stack branch.")
    print("  ds lint --layer 1")
