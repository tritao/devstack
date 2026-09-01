from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from tools.devstack.commands.stack import cmd_update, pr_base_for_layer, select_entries
from tools.devstack.core.frontmatter import strip_body_frontmatter, title_from_body_frontmatter, title_with_number
from tools.devstack.core.git import default_stack_remote, ensure_commit_exists, git, repo_root, resolve_commitish, sanitize_key_to_filename
from tools.devstack.core.proc import die, have_cmd, note, run
from tools.devstack.core.stackconf import (
    base_branch_name,
    filtered_mode,
    key_number,
    read_conf,
    resolved_body_file,
    set_conf_directive,
)


def body_file_for_gh(root: Path, entry, body_file: Path) -> Path:
    """Return a body-file path safe for `gh pr create/edit` (frontmatter stripped)."""
    try:
        text = body_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return body_file

    stripped = strip_body_frontmatter(text)
    if stripped == text:
        return body_file

    tmp_dir = root / ".devstack" / "tmp" / "gh-sync-bodies"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / f"{sanitize_key_to_filename(entry.key)}.md"
    out.write_text(stripped, encoding="utf-8")
    return out


def shlex_quote(s: str) -> str:
    return shlex.quote(s)


def cmd_push(args: argparse.Namespace) -> None:
    root = repo_root()
    conf = read_conf(root)
    remote = conf.push_remote or os.environ.get("DEVSTACK_STACK_REMOTE", "origin")
    only = getattr(args, "only", None)
    for entry in select_entries(conf, only):
        print(f"pushing {entry.branch}")
        run(["git", "push", "--force-with-lease", remote, f"{entry.branch}:{entry.branch}"], cwd=root)


def cmd_pr_layer(args: argparse.Namespace) -> None:
    layer = int(args.layer)
    cmd_update(argparse.Namespace(only=layer, standalone=bool(getattr(args, "standalone", False))))
    cmd_push(argparse.Namespace(only=layer))
    cmd_gh_sync(
        argparse.Namespace(
            apply=bool(args.apply),
            only=layer,
            standalone=bool(getattr(args, "standalone", False)),
            draft=bool(getattr(args, "draft", False)),
        )
    )
    if not bool(args.apply):
        return

    root = repo_root()
    conf = read_conf(root)
    base_remote = (conf.base_remote_ref.split("/", 1)[0] if conf.base_remote_ref else "").strip()
    repo = gh_default_repo_for_remotes(root, base_remote=base_remote)
    entry = select_entries(conf, layer)[0]
    head_ref = (
        gh_head_ref(root, base_repo=repo, branch=entry.branch, push_remote=getattr(conf, "push_remote", ""))
        if repo
        else entry.branch
    )
    pr_number = gh_pr_number_for_head(root, head_ref, repo)
    url = gh_pr_url(root, pr_number, repo)
    if url:
        print(f"PR: {url}")
    else:
        note("pr-layer: could not resolve PR URL (try: gh pr view --web)")


def gh_check() -> None:
    if not have_cmd("gh"):
        die("GitHub CLI 'gh' not found on PATH")
    proc = run(["gh", "auth", "status", "--hostname", "github.com"], check=False, capture=True)
    if proc.returncode != 0:
        die("GitHub CLI is not authenticated for github.com (run: gh auth login)")


def _parse_github_owner_repo(remote_url: str) -> str:
    url = (remote_url or "").strip()
    if not url:
        return ""
    m = re.match(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", url)
    if m:
        return f"{m.group('owner')}/{m.group('repo')}"
    m = re.match(r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$", url)
    if m:
        return f"{m.group('owner')}/{m.group('repo')}"
    return ""


def _repo_for_remote(root: Path, remote: str) -> str:
    if not remote:
        return ""
    try:
        return _parse_github_owner_repo(git(["remote", "get-url", remote], cwd=root))
    except subprocess.CalledProcessError:
        return ""


def _gh_stack_installed(root: Path) -> bool:
    if not have_cmd("gh"):
        return False
    proc = run(["gh", "extension", "list"], cwd=root, check=False, capture=True)
    return any(
        "github/gh-stack" in line or line.split("\t", 1)[0].strip() == "gh-stack"
        for line in (proc.stdout or "").splitlines()
    )


def stack_topology(root: Path, conf) -> dict[str, object]:
    base_remote = conf.base_remote_ref.split("/", 1)[0] if "/" in conf.base_remote_ref else ""
    push_remote = getattr(conf, "push_remote", "") or default_stack_remote(root)
    detected_base_repo = _repo_for_remote(root, base_remote)
    configured_repo = getattr(conf, "github_repo", "")
    base_repo = detected_base_repo or configured_repo
    head_repo = _repo_for_remote(root, push_remote)
    configured_repo_matches = bool(
        not configured_repo or not detected_base_repo or configured_repo.lower() == detected_base_repo.lower()
    )
    same_repo = bool(
        base_repo and head_repo and base_repo.lower() == head_repo.lower() and configured_repo_matches
    )
    extension = _gh_stack_installed(root)
    return {
        "mode": getattr(conf, "github_mode", "chained"),
        "base_ref": conf.base_remote_ref,
        "base_remote": base_remote,
        "push_remote": push_remote,
        "base_repo": base_repo,
        "configured_repo": configured_repo,
        "configured_repo_matches": configured_repo_matches,
        "detected_base_repo": detected_base_repo,
        "head_repo": head_repo,
        "repository_layout": "same-repository" if same_repo else "cross-fork" if base_repo and head_repo else "unknown",
        "native_eligible": same_repo,
        "gh_stack_installed": extension,
        "valid": getattr(conf, "github_mode", "chained") != "native" or (same_repo and extension),
        "layers": len(conf.entries),
    }


def native_link_command(conf) -> list[str]:
    command = [
        "gh",
        "stack",
        "link",
        "--base",
        base_branch_name(conf.base_remote_ref),
    ]
    push_remote = getattr(conf, "push_remote", "")
    if push_remote:
        command.extend(["--remote", push_remote])
    command.extend(entry.branch for entry in conf.entries)
    return command


def cmd_stack_status(args: argparse.Namespace) -> None:
    root = repo_root()
    conf = read_conf(root)
    status = stack_topology(root, conf)
    if bool(getattr(args, "json", False)):
        print(json.dumps(status, indent=2, sort_keys=True))
        return
    print(f"GitHub mode:       {status['mode']}")
    print(f"Repository layout: {status['repository_layout']}")
    print(f"Base repository:   {status['base_repo'] or '(unknown)'}")
    print(f"Head repository:   {status['head_repo'] or '(unknown)'}")
    print(f"Base ref:          {status['base_ref']}")
    print(f"Push remote:       {status['push_remote']}")
    print(f"Layers:            {status['layers']}")
    print(f"gh-stack:          {'installed' if status['gh_stack_installed'] else 'not installed'}")
    if not status["configured_repo_matches"]:
        print(
            f"Repository config: mismatch ({status['configured_repo']} does not match "
            f"{status['detected_base_repo']})"
        )
    if status["mode"] == "native" and not status["native_eligible"]:
        print("Native stack:      unavailable (GitHub requires all branches in the same repository)")
    elif status["mode"] == "native" and not status["gh_stack_installed"]:
        print("Native stack:      unavailable (install with: gh extension install github/gh-stack)")
    elif status["mode"] == "native":
        print("Native stack:      supported")
    else:
        print("Native stack:      not requested")


def cmd_stack_mode(args: argparse.Namespace) -> None:
    root = repo_root()
    conf = read_conf(root)
    requested = (getattr(args, "mode", None) or "").strip()
    if not requested:
        cmd_stack_status(argparse.Namespace(json=False))
        return
    status = stack_topology(root, conf)
    print(f"current mode:  {conf.github_mode}")
    print(f"proposed mode: {requested}")
    print(f"layout:        {status['repository_layout']}")
    if requested == "native" and not status["native_eligible"]:
        die(
            "GitHub native stacks require all branches in the same repository\n"
            f"base repository: {status['base_repo'] or '(unknown)'}\n"
            f"head repository: {status['head_repo'] or '(unknown)'}\n"
            "Use: ds stack-mode chained --apply"
        )
    if requested == "native" and not status["gh_stack_installed"]:
        die("native mode requires the official extension: gh extension install github/gh-stack")
    if not bool(getattr(args, "apply", False)):
        note("dry-run; pass --apply to save this mode")
        return
    if requested == "native":
        confirmation = (getattr(args, "confirm_repository", "") or "").strip()
        expected = str(status["base_repo"] or "")
        if confirmation.lower() != expected.lower():
            die(
                "saving native mode requires explicit repository confirmation\n"
                f"rerun with: --confirm-repository {expected}"
            )
    set_conf_directive(conf, "github_mode", requested)
    print(f"saved github_mode {requested} in {conf.path}")


def gh_default_repo(root: Path) -> str:
    return gh_default_repo_for_remotes(root)


def _remote_owner_repos(root: Path) -> dict[str, str]:
    remotes: dict[str, str] = {}
    try:
        out = git(["remote"], cwd=root)
    except subprocess.CalledProcessError:
        return remotes
    for r in [x.strip() for x in out.splitlines() if x.strip()]:
        try:
            url = git(["remote", "get-url", r], cwd=root).strip()
        except subprocess.CalledProcessError:
            continue
        repo = _parse_github_owner_repo(url)
        if repo:
            remotes[r] = repo
    return remotes


def gh_default_repo_for_remotes(root: Path, *, base_remote: str = "") -> str:
    """
    Pick a GitHub OWNER/REPO for `gh pr ... --repo`.

    Preference order:
    - DEVSTACK_GH_REPO (but ignored if it doesn't match any remote in this repo)
    - base_remote (derived from stack.conf `base <remote>/<branch>`)
    - origin/upstream/fork (common upstream remotes)
    - default_stack_remote(root) (push remote)
    - any other remote that points at GitHub
    """
    env_repo = (os.environ.get("DEVSTACK_GH_REPO", "")).strip()
    remotes = _remote_owner_repos(root)
    known = set(remotes.values())

    if env_repo:
        if env_repo in known:
            return env_repo
        note(f"DEVSTACK_GH_REPO={env_repo} does not match any git remote in {root}; ignoring")

    def want_remote(r: str) -> str:
        return remotes.get(r, "")

    if base_remote:
        repo = want_remote(base_remote)
        if repo:
            return repo

    for r in ("origin", "upstream", "fork"):
        repo = want_remote(r)
        if repo:
            return repo

    push_remote = default_stack_remote(root)
    repo = want_remote(push_remote)
    if repo:
        return repo

    # Last resort: first GitHub remote in lexical order.
    for r in sorted(remotes.keys()):
        return remotes[r]
    return ""


def gh_head_ref(root: Path, *, base_repo: str, branch: str, push_remote: str = "") -> str:
    branch = (branch or "").strip()
    base_repo = (base_repo or "").strip()
    if not base_repo or not branch:
        return branch

    push_remote = push_remote or default_stack_remote(root)
    try:
        url = git(["remote", "get-url", push_remote], cwd=root).strip()
    except subprocess.CalledProcessError:
        return branch

    push_repo = _parse_github_owner_repo(url)
    if not push_repo or push_repo == base_repo:
        return branch

    owner = push_repo.split("/", 1)[0]
    return f"{owner}:{branch}"


def gh_pr_number_for_head(root: Path, head_branch: str, repo: str) -> str:
    repo_args = ["--repo", repo] if repo else []

    def parse_number(stdout: str) -> str:
        try:
            data = json.loads(stdout or "")
            if not data:
                return ""
            return str(data[0].get("number") or "")
        except Exception:
            return ""

    proc = run(
        ["gh", "pr", "list", *repo_args, "--head", head_branch, "--state", "all", "--json", "number", "--limit", "1"],
        capture=True,
        check=False,
    )
    num = parse_number(proc.stdout)
    if num:
        return num

    search_head = head_branch.split(":", 1)[-1]
    proc2 = run(
        [
            "gh",
            "pr",
            "list",
            *repo_args,
            "--search",
            f"head:{search_head}",
            "--state",
            "all",
            "--json",
            "number",
            "--limit",
            "1",
        ],
        capture=True,
        check=False,
    )
    return parse_number(proc2.stdout)


def gh_pr_url(root: Path, pr_number: str, repo: str) -> str:
    pr_number = (pr_number or "").strip()
    if not pr_number:
        return ""
    repo_args = ["--repo", repo] if repo else []
    proc = run(
        ["gh", "pr", "view", pr_number, *repo_args, "--json", "url", "--jq", ".url"],
        cwd=root,
        capture=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _remote_head_branch_exists(root: Path, remote: str, branch: str) -> bool:
    remote = (remote or "").strip()
    branch = (branch or "").strip()
    if not remote or not branch:
        return False
    try:
        proc = run(["git", "ls-remote", "--heads", remote, branch], cwd=root, capture=True, check=False)
    except Exception:
        return False
    return bool((proc.stdout or "").strip())


def _remote_head_sha(root: Path, remote: str, branch: str) -> str:
    if not remote or not branch:
        return ""
    proc = run(["git", "ls-remote", "--heads", remote, branch], cwd=root, capture=True, check=False)
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return ""
    return (proc.stdout or "").split()[0]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_fingerprint(state: dict[str, object]) -> str:
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256_text(encoded)


def _current_pr_state(root: Path, repo: str, number: str) -> dict[str, object]:
    if not repo or not number:
        return {}
    proc = run(
        ["gh", "api", f"repos/{repo}/pulls/{number}"],
        cwd=root,
        capture=True,
        check=False,
    )
    if proc.returncode != 0:
        return {"number": int(number), "lookup_error": True}
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"number": int(number), "lookup_error": True}
    return {
        "number": data.get("number"),
        "state": data.get("state"),
        "draft": bool(data.get("draft")),
        "base": ((data.get("base") or {}).get("ref")),
        "head": ((data.get("head") or {}).get("ref")),
        "head_sha": ((data.get("head") or {}).get("sha")),
        "title": data.get("title"),
        "body_sha256": _sha256_text(data.get("body") or ""),
        "updated_at": data.get("updated_at"),
    }


def build_sync_state(root: Path, conf, args: argparse.Namespace) -> dict[str, object]:
    """Capture all local and GitHub inputs that affect a gh-sync operation."""
    base_remote = conf.base_remote_ref.split("/", 1)[0] if "/" in conf.base_remote_ref else ""
    push_remote = getattr(conf, "push_remote", "") or default_stack_remote(root)
    repo = getattr(conf, "github_repo", "") or gh_default_repo_for_remotes(root, base_remote=base_remote)
    only = getattr(args, "only", None)
    standalone = bool(getattr(args, "standalone", False))
    entries = select_entries(conf, only)
    next_base = base_branch_name(conf.base_remote_ref)
    if only is not None and not standalone:
        next_base = pr_base_for_layer(conf, only)

    layers: list[dict[str, object]] = []
    for entry in entries:
        try:
            local_sha = resolve_commitish(root, entry.branch) if filtered_mode(conf) else resolve_commitish(root, entry.sha)
        except Exception:
            local_sha = ""
        body_file = resolved_body_file(conf, entry)
        body_text = body_file.read_text(encoding="utf-8", errors="replace") if body_file.is_file() else ""
        title = git(["show", "-s", "--format=%s", local_sha], cwd=root) if local_sha else entry.branch
        frontmatter_title = title_from_body_frontmatter(body_file) if body_file.is_file() else ""
        title = frontmatter_title or title_with_number(title, key_number(entry.key))
        title = " ".join((title or "").splitlines()).strip()
        head_ref = gh_head_ref(root, base_repo=repo, branch=entry.branch, push_remote=push_remote)
        pr_number = gh_pr_number_for_head(root, head_ref, repo)
        layers.append(
            {
                "key": entry.key,
                "branch": entry.branch,
                "configured_sha": entry.sha,
                "local_sha": local_sha,
                "remote_sha": _remote_head_sha(root, push_remote, entry.branch),
                "desired_base": next_base,
                "desired_title": title,
                "desired_body_sha256": _sha256_text(strip_body_frontmatter(body_text)),
                "pr": _current_pr_state(root, repo, pr_number),
            }
        )
        next_base = entry.branch

    topology = stack_topology(root, conf)
    return {
        "schema": 1,
        "repository_root": str(root.resolve()),
        "github_mode": getattr(conf, "github_mode", "chained"),
        "github_repo": repo,
        "base_ref": conf.base_remote_ref,
        "base_remote_sha": _remote_head_sha(root, base_remote, base_branch_name(conf.base_remote_ref)),
        "push_remote": push_remote,
        "repository_layout": topology["repository_layout"],
        "native_eligible": topology["native_eligible"],
        "gh_stack_installed": topology["gh_stack_installed"],
        "configured_repo_matches": topology["configured_repo_matches"],
        "only": only,
        "standalone": standalone,
        "draft": bool(getattr(args, "draft", False)),
        "layers": layers,
    }


def write_sync_plan(path: Path, state: dict[str, object]) -> dict[str, object]:
    plan = {
        "schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": _canonical_fingerprint(state),
        "summary": {
            "repository": state["github_repo"],
            "mode": state["github_mode"],
            "layers": len(state["layers"]),
            "native_link": state["github_mode"] == "native" and state["only"] is None,
        },
        "state": state,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan


def cmd_stack_doctor(args: argparse.Namespace) -> None:
    root = repo_root()
    conf = read_conf(root)
    gh_check()
    state = build_sync_state(root, conf, argparse.Namespace(only=None, standalone=False, draft=False))
    errors: list[str] = []
    if not state["github_repo"]:
        errors.append("GitHub repository could not be determined")
    if not state["base_remote_sha"]:
        errors.append(f"base branch is missing on {conf.base_remote_ref}")
    if state["github_mode"] == "native" and not state["native_eligible"]:
        errors.append("native mode requires base and head branches in the same repository")
    if state["github_mode"] == "native" and not state["gh_stack_installed"]:
        errors.append("native mode requires github/gh-stack")
    for layer in state["layers"]:
        if not layer["local_sha"]:
            errors.append(f"{layer['branch']}: local branch/commit is missing")
        if not layer["remote_sha"]:
            errors.append(f"{layer['branch']}: branch is missing on {state['push_remote']}")
        elif layer["local_sha"] != layer["remote_sha"]:
            errors.append(
                f"{layer['branch']}: remote SHA {str(layer['remote_sha'])[:12]} "
                f"does not match local SHA {str(layer['local_sha'])[:12]}"
            )
        pr = layer["pr"]
        if pr.get("lookup_error"):
            errors.append(f"{layer['branch']}: existing PR could not be read")
        if pr and pr.get("head") != layer["branch"]:
            errors.append(f"{layer['branch']}: PR head is {pr.get('head')}")
    result = {"ok": not errors, "errors": errors, "state": state}
    if bool(getattr(args, "json", False)):
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Stack doctor:      {'ok' if not errors else 'FAILED'}")
        print(f"Repository:        {state['github_repo'] or '(unknown)'}")
        print(f"Mode:              {state['github_mode']}")
        print(f"Layout:            {state['repository_layout']}")
        print(f"Layers:            {len(state['layers'])}")
        for error in errors:
            print(f"ERROR: {error}")
    if errors:
        raise SystemExit(1)


def cmd_gh_sync(args: argparse.Namespace) -> None:
    root = repo_root()
    conf = read_conf(root)
    gh_check()

    plan_path = getattr(args, "plan", None)
    apply_plan_path = getattr(args, "apply_plan", None)
    apply = bool(getattr(args, "apply", False) or apply_plan_path)
    if plan_path:
        state = build_sync_state(root, conf, args)
        if not state["configured_repo_matches"]:
            die("cannot create plan: configured github_repo does not match the base remote")
        if state["github_mode"] == "native" and not state["native_eligible"]:
            die("cannot create plan: native mode requires a same-repository stack")
        unsynced = [
            layer["branch"]
            for layer in state["layers"]
            if not layer["local_sha"] or layer["local_sha"] != layer["remote_sha"]
        ]
        if not state["base_remote_sha"] or unsynced:
            details = ", ".join(unsynced) if unsynced else "base branch"
            die(f"cannot create plan: required remote refs are missing or stale: {details}")
        plan = write_sync_plan(Path(plan_path).expanduser(), state)
        print(f"wrote gh-sync plan: {Path(plan_path).expanduser()}")
        print(f"fingerprint: {plan['fingerprint']}")
        return
    if apply_plan_path:
        path = Path(apply_plan_path).expanduser()
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            die(f"cannot read gh-sync plan {path}: {exc}")
        saved_state = saved.get("state") or {}
        args.only = saved_state.get("only")
        args.standalone = bool(saved_state.get("standalone", False))
        args.draft = bool(saved_state.get("draft", False))
        state = build_sync_state(root, conf, args)
        current = _canonical_fingerprint(state)
        if saved.get("fingerprint") != current:
            die(
                "gh-sync plan is stale; local refs, remote branches, PR state, or configuration changed\n"
                f"saved:   {saved.get('fingerprint', '(missing)')}\n"
                f"current: {current}\n"
                "Generate and review a new plan before applying."
            )
        print(f"validated gh-sync plan: {path}")
    if not apply:
        note("dry-run; pass --apply to create/edit PRs")

    def env_truthy(key: str) -> bool:
        return os.environ.get(key, "").strip().lower() in ("1", "true", "yes", "on")

    draft = bool(getattr(args, "draft", False) or env_truthy("DEVSTACK_GH_DRAFT"))

    base_remote = (conf.base_remote_ref.split("/", 1)[0] if conf.base_remote_ref else "").strip()
    github_mode = getattr(conf, "github_mode", "chained")
    repo = getattr(conf, "github_repo", "") or gh_default_repo_for_remotes(root, base_remote=base_remote)
    repo_args = ["--repo", repo] if repo else []

    base_default = base_branch_name(conf.base_remote_ref)
    base = base_default
    only = getattr(args, "only", None)
    entries = select_entries(conf, only)
    if only is not None and not bool(getattr(args, "standalone", False)):
        base = pr_base_for_layer(conf, only)

    push_remote = getattr(conf, "push_remote", "") or default_stack_remote(root)
    topology = stack_topology(root, conf)
    if not topology.get("configured_repo_matches", True):
        die(
            f"configured github_repo {topology['configured_repo']} does not match "
            f"base remote repository {topology['detected_base_repo']}"
        )
    if github_mode == "native" and not topology["native_eligible"]:
        die(
            "GitHub native stacks require all branches in the same repository\n"
            f"base repository: {topology['base_repo'] or '(unknown)'}\n"
            f"head repository: {topology['head_repo'] or '(unknown)'}\n"
            "Set `github_mode chained` (or run: ds stack-mode chained --apply)."
        )
    if github_mode == "native" and apply and not topology["gh_stack_installed"]:
        die("native mode requires the official extension: gh extension install github/gh-stack")
    if github_mode == "native" and apply and not apply_plan_path:
        die(
            "native stack mutations require a reviewed plan\n"
            "run: ds gh-sync --plan .devstack/gh-sync-plan.json\n"
            "then: ds gh-sync --apply-plan .devstack/gh-sync-plan.json"
        )
    if apply:
        print("mutation summary:")
        print(f"  repository:        {repo or '(unknown)'}")
        print(f"  PRs create/update: {len(entries)}")
        print(f"  native relink:     {'yes' if github_mode == 'native' and only is None else 'no'}")
    # If applying, fail fast with a clear hint when branches aren't pushed yet.
    if apply and push_remote:
        base_default = base_branch_name(conf.base_remote_ref)
        if base_remote and not _remote_head_branch_exists(root, base_remote, base):
            # In fork workflows, stacked PR base branches (pr/... from prior layer) typically exist only on the fork,
            # not in the upstream/base repo. GitHub requires `--base` to be a branch in the base repo, so fall back.
            if (
                base.startswith("pr/")
                and base != base_default
                and _remote_head_branch_exists(root, base_remote, base_default)
                and not bool(getattr(args, "standalone", False))
            ):
                note(
                    f"gh-sync: base branch not found on remote {base_remote}: {base}; "
                    f"using {base_default} as PR base (fork-style stack)"
                )
                base = base_default
            else:
                die(f"gh-sync: base branch not found on remote {base_remote}: {base} (check .devstack/stack.conf base)")

    for entry in entries:
        head_commit = entry.sha
        if filtered_mode(conf):
            try:
                head_commit = resolve_commitish(root, entry.branch)
            except Exception:
                die(f"missing local branch: {entry.branch} (run: devstack.sh update)")
        else:
            ensure_commit_exists(root, entry.sha)

        title = git(["show", "-s", "--format=%s", head_commit], cwd=root) or entry.branch
        body_file = resolved_body_file(conf, entry)
        draft_title = title_from_body_frontmatter(body_file) if body_file.is_file() else ""
        if draft_title:
            title = draft_title
        else:
            title = title_with_number(title, key_number(entry.key))
        title = " ".join((title or "").splitlines()).strip()

        head_ref = (
            gh_head_ref(root, base_repo=repo, branch=entry.branch, push_remote=push_remote) if repo else entry.branch
        )

        if apply:
            # gh PR create/edit requires the head to exist as a branch on the remote fork.
            if not _remote_head_branch_exists(root, push_remote, entry.branch):
                die(
                    f"gh-sync: head branch not pushed to {push_remote}: {entry.branch}\n"
                    f"hint: run `ds push{' --only '+str(only) if only else ''}` (or `ds pr-layer {only}`) first"
                )

        pr_number = gh_pr_number_for_head(root, head_ref, repo)
        if pr_number:
            if repo:
                # `gh pr edit` in older gh releases queries the retired
                # Projects Classic field even when only editing title/base/body.
                # The REST endpoint updates exactly those fields and works with
                # both older and current gh versions.
                cmd = [
                    "gh",
                    "api",
                    f"repos/{repo}/pulls/{pr_number}",
                    "--method",
                    "PATCH",
                    "-f",
                    f"base={base}",
                    "-f",
                    f"title={title}",
                ]
            else:
                cmd = ["gh", "pr", "edit", pr_number, *repo_args, "--base", base, "--title", title]
        else:
            cmd = ["gh", "pr", "create", *repo_args, "--head", head_ref, "--base", base, "--title", title]
            if draft:
                cmd.append("--draft")

        if body_file.is_file():
            gh_body_file = body_file_for_gh(root, entry, body_file)
            if pr_number and repo:
                cmd.extend(["-F", f"body=@{gh_body_file}"])
            else:
                cmd.extend(["--body-file", str(gh_body_file)])
        else:
            body = f"Stacked PR: {entry.branch} ({entry.sha})"
            cmd.extend(["-f", f"body={body}"] if pr_number and repo else ["--body", body])

        if apply:
            try:
                run(cmd, cwd=root, check=True, capture=True)
            except subprocess.CalledProcessError as exc:
                note("gh-sync failed")
                if not repo:
                    note("hint: set a default repo for gh, or pass it via env:")
                    note("  gh repo set-default OWNER/REPO")
                    note("  export DEVSTACK_GH_REPO=OWNER/REPO")
                out = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()
                if "projectCards" in out or "Projects (classic) is being deprecated" in out:
                    ver = ""
                    try:
                        proc = run(["gh", "--version"], cwd=root, check=False, capture=True)
                        ver = (proc.stdout or "").splitlines()[0].strip()
                    except Exception:
                        ver = ""
                    die(
                        "your `gh` CLI is using a deprecated Projects Classic GraphQL field (projectCards); "
                        "upgrade `gh` and retry"
                        + (f" (current: {ver})" if ver else "")
                    )
                raise

            if not pr_number:
                pr_number = gh_pr_number_for_head(root, head_ref, repo)
            url = gh_pr_url(root, pr_number, repo)
            if url:
                print(url)
        else:
            print(" ".join(shlex_quote(x) for x in cmd))
        base = entry.branch

    if github_mode == "native":
        if only is not None:
            note("native stack linking requires the full stack; run `ds gh-sync` without --only")
            return
        link_cmd = native_link_command(conf)
        if apply:
            run(link_cmd, cwd=root)
        else:
            print(" ".join(shlex_quote(x) for x in link_cmd))
