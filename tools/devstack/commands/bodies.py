from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from tools.devstack.core.frontmatter import title_from_body_frontmatter, title_with_number
from tools.devstack.core.git import ensure_commit_exists, git, repo_root
from tools.devstack.core.proc import die, run
from tools.devstack.core.stackconf import base_branch_name, filtered_mode, key_number, read_conf, resolved_body_file


def _truncate_commit_subject(subject: str, max_len: int) -> str:
    subject = (subject or "").strip()
    if max_len <= 0:
        return subject
    if len(subject) <= max_len:
        return subject
    if max_len <= 1:
        return "…"
    return subject[: max_len - 1].rstrip() + "…"


def autogen_block(
    base_ref: str,
    pr_base: str,
    stack_pos: int,
    stack_total: int,
    from_ref: str,
    to_ref: str,
    commits: str,
    group: str = "",
    group_title: str = "",
    group_pos: int = 0,
    group_total: int = 0,
    detail: str = "compact",
) -> str:
    if stack_total == 1:
        return ""

    try:
        max_subject = int((os.environ.get("DEVSTACK_BODY_COMMIT_SUBJECT_MAX", "") or "60").strip())
    except ValueError:
        max_subject = 60

    commits_lines = "- (none)"
    if commits.strip():
        formatted: list[str] = []
        for line in commits.splitlines():
            parts = line.split(maxsplit=1)
            if parts and re.fullmatch(r"[0-9a-f]{7,40}", parts[0]):
                sha = parts[0]
                subject = parts[1] if len(parts) > 1 else ""
                subject = _truncate_commit_subject(subject, max_subject)
                formatted.append(f"- `{sha}`: {subject}".rstrip())
            else:
                formatted.append(f"- {line}")
        commits_lines = "\n".join(formatted)
    metadata = [
            "<!-- AUTOGEN:BEGIN -->",
            "### Patch Set",
            "",
            "> [!IMPORTANT]",
            f"> Part `{stack_pos}/{stack_total}` of a stacked series. Depends on `{pr_base}`; review and merge in order.",
    ]
    if group:
        metadata.append("")
        group_progress = f" (`{group_pos}/{group_total}`)" if group_pos and group_total else ""
        metadata.append(f"- Group: `{group}` — {group_title or group}{group_progress}")
    if detail == "full":
        metadata.append("")
        metadata.extend(
            [
                f"- Stack: `{stack_pos}/{stack_total}`",
                f"- Base: `{base_ref}`",
                f"- PR base (depends-on): `{pr_base}`",
                f"- Range: `{from_ref}..{to_ref}`",
                "",
                "#### Commits",
                commits_lines,
            ]
        )
    metadata.extend(["", "<!-- AUTOGEN:END -->"])
    return "\n".join(metadata)


AUTOGEN_RE = re.compile(r"<!-- AUTOGEN:BEGIN -->[\s\S]*?<!-- AUTOGEN:END -->", re.MULTILINE)
SERIES_RE = re.compile(r"<!-- AUTOGEN:SERIES:BEGIN -->[\s\S]*?<!-- AUTOGEN:SERIES:END -->", re.MULTILINE)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->")
BODY_FORBIDDEN = (
    (re.compile(r"\bdevstack\b", re.IGNORECASE), "internal tool name 'devstack'"),
    (re.compile(r"\bcodex\b", re.IGNORECASE), "AI tool name 'Codex'"),
    (re.compile(r"\bchatgpt\b", re.IGNORECASE), "AI tool name 'ChatGPT'"),
    (re.compile(r"\bAI[- ]generated\b", re.IGNORECASE), "AI-generation language"),
    (re.compile(r"(?<![\w.])/(?:home|media|tmp|Users)/\S+"), "local absolute path"),
)


def body_check_issues(conf, entries=None) -> list[str]:
    selected = conf.entries if entries is None else entries
    issues: list[str] = []
    for entry in selected:
        path = resolved_body_file(conf, entry)
        if not path.is_file():
            continue
        for number, raw_line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            line = HTML_COMMENT_RE.sub("", raw_line)
            for pattern, label in BODY_FORBIDDEN:
                match = pattern.search(line)
                if match:
                    issues.append(f"{path}:{number}: {label}: {match.group(0)}")
    return issues


def run_body_check(conf, entries=None) -> None:
    if getattr(conf, "body_check", "auto") == "off":
        return
    issues = body_check_issues(conf, entries)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        die("PR body check failed; remove internal implementation details or set `body_check off`")


def cmd_body_check(args: argparse.Namespace) -> None:
    conf = read_conf(repo_root())
    run_body_check(conf)
    print(f"PR body check: ok ({len(conf.entries)} bodies)")


def series_block(title: str, summary: str, entries: list[tuple[str, str]]) -> str:
    if not summary or len(entries) < 2:
        return ""
    lines = [
        "<!-- AUTOGEN:SERIES:BEGIN -->",
        f"## {title or 'PR series'}",
        "",
        "> [!NOTE]",
        f"> {summary}",
        ">",
    ]
    for index, (branch, title) in enumerate(entries, start=1):
        lines.append(f"> {index}. <!-- DEVSTACK:SERIES-PR {branch} -->{title}")
    lines.extend([">", "> Please review and merge the PRs in order.", "<!-- AUTOGEN:SERIES:END -->"])
    return "\n".join(lines)


def _insert_after_frontmatter(content: str, block: str) -> str:
    if not block:
        return content
    lines = content.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                prefix = "".join(lines[: index + 1]).rstrip()
                remainder = "".join(lines[index + 1 :]).lstrip("\n")
                return f"{prefix}\n\n{block}\n\n{remainder}".rstrip() + "\n"
    return f"{block}\n\n{content.lstrip()}".rstrip() + "\n"


def update_body_file(
    body_path: Path,
    autogen: str,
    *,
    series: str = "",
    title: str = "",
    template_path: Path | None = None,
) -> None:
    if not body_path.exists():
        body_path.parent.mkdir(parents=True, exist_ok=True)
        if template_path is not None:
            if not template_path.is_file():
                die(f"PR body template does not exist: {template_path}")
            content = template_path.read_text(encoding="utf-8", errors="replace")
            content = content.replace("{{ title }}", json.dumps(title))
            content = content.replace("{{ autogen }}", autogen)
            content = SERIES_RE.sub("", content).strip()
            body_path.write_text(_insert_after_frontmatter(content.rstrip() + "\n", series), encoding="utf-8")
            print(f"created {body_path} from {template_path}")
            return
        frontmatter = ""
        if title:
            frontmatter = "\n".join(["---", f"title: {json.dumps(title)}", "---", ""])
        content = "\n".join(
            [
                frontmatter + "## Summary" if frontmatter else "## Summary",
                "",
                "## Why",
                "",
                "## Changes",
                "",
                autogen,
                "",
            ]
        )
        body_path.write_text(_insert_after_frontmatter(content + "\n", series), encoding="utf-8")
        print(f"created {body_path}")
        return

    content = body_path.read_text(encoding="utf-8", errors="replace")
    content = SERIES_RE.sub("", content).strip() + "\n"
    if "<!-- AUTOGEN:BEGIN -->" in content and "<!-- AUTOGEN:END -->" in content:
        stripped = AUTOGEN_RE.sub("", content).rstrip()
        if not autogen:
            new_content = stripped + "\n" if stripped else ""
        else:
            new_content = (stripped + "\n\n" + autogen + "\n") if stripped else (autogen + "\n")
        body_path.write_text(_insert_after_frontmatter(new_content, series), encoding="utf-8")
        print(f"updated {body_path}")
        return

    content = content.rstrip() + "\n\n" + autogen + "\n"
    body_path.write_text(_insert_after_frontmatter(content, series), encoding="utf-8")
    print(f"appended {body_path}")


def cmd_body_refresh(args: argparse.Namespace) -> None:
    root = repo_root()
    conf = read_conf(root)
    template_path = None
    if conf.body_template:
        configured_template = Path(conf.body_template)
        template_path = (
            configured_template
            if configured_template.is_absolute()
            else (root / configured_template).resolve()
        )
    base_display = base_branch_name(conf.base_remote_ref)
    prev = conf.base_remote_ref
    pr_base = base_display
    total = len(conf.entries)
    series_entries: list[tuple[str, str]] = []
    for entry in conf.entries:
        body_path = resolved_body_file(conf, entry)
        to_ref = entry.branch if filtered_mode(conf) else entry.sha
        raw_title = git(["show", "-s", "--format=%s", to_ref], cwd=root) or entry.branch
        title = title_from_body_frontmatter(body_path) if body_path.is_file() else ""
        series_entries.append((entry.branch, title or title_with_number(raw_title, key_number(entry.key))))
    series = series_block(conf.series_title, conf.series_summary, series_entries)
    for idx, entry in enumerate(conf.entries, start=1):
        group_entries = [candidate for candidate in conf.entries if candidate.group == entry.group]
        group_pos = group_entries.index(entry) + 1 if entry.group else 0
        from_ref = prev
        to_ref = entry.branch if filtered_mode(conf) else entry.sha
        if filtered_mode(conf):
            try:
                run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{entry.branch}"], cwd=root)
            except subprocess.CalledProcessError:
                die(f"missing local branch: {entry.branch} (run: devstack.sh update)")
        else:
            ensure_commit_exists(root, entry.sha)
        commits = git(["log", "--oneline", "--no-decorate", f"{from_ref}..{to_ref}"], cwd=root)
        autogen = autogen_block(
            base_ref=base_display,
            pr_base=pr_base,
            stack_pos=idx,
            stack_total=total,
            from_ref=from_ref,
            to_ref=to_ref,
            commits=commits,
            group=entry.group,
            group_title=entry.group_title,
            group_pos=group_pos,
            group_total=len(group_entries) if entry.group else 0,
            detail=conf.body_detail,
        )
        body_path = resolved_body_file(conf, entry)
        if entry.body and not body_path.exists():
            die(f"missing body file for {entry.branch}: {body_path}")
        raw_title = git(["show", "-s", "--format=%s", to_ref], cwd=root) or entry.branch
        title = title_with_number(raw_title, key_number(entry.key))
        update_body_file(body_path, autogen, series=series, title=title, template_path=template_path)
        prev = entry.branch if filtered_mode(conf) else entry.sha
        pr_base = entry.branch


def cmd_body_context(args: argparse.Namespace) -> None:
    root = repo_root()
    conf = read_conf(root)
    want = args.branch or ""
    base_display = base_branch_name(conf.base_remote_ref)
    prev = conf.base_remote_ref
    for entry in conf.entries:
        if want and want not in (entry.branch, entry.key):
            prev = entry.branch if filtered_mode(conf) else entry.sha
            continue
        from_ref = prev
        to_ref = entry.branch if filtered_mode(conf) else entry.sha
        if filtered_mode(conf):
            try:
                run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{entry.branch}"], cwd=root)
            except subprocess.CalledProcessError:
                die(f"missing local branch: {entry.branch} (run: devstack.sh update)")
        else:
            ensure_commit_exists(root, entry.sha)
        print()
        print(f"## Context: `{entry.branch}`")
        print()
        print(f"- Base: `{base_display}`")
        if entry.group:
            print(f"- Group: `{entry.group}` — {entry.group_title or entry.group}")
        print(f"- Range: `{from_ref}..{to_ref}`")
        print()
        print("### Commits")
        proc = run(["git", "log", "--oneline", "--no-decorate", f"{from_ref}..{to_ref}"], cwd=root, check=False, capture=True)
        if proc.stdout:
            print(proc.stdout.rstrip())
        print()
        print("### Areas Touched")
        names = git(["diff", "--name-only", f"{from_ref}..{to_ref}"], cwd=root)
        counts: dict[str, int] = {}
        for p in names.splitlines():
            segs = p.split("/")
            prefix = "/".join(segs[:2]) if len(segs) >= 2 else p
            counts[prefix] = counts.get(prefix, 0) + 1
        for prefix, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
            print(f"- {c} files in {prefix}")
        prev = entry.branch if filtered_mode(conf) else entry.sha


def _is_under_dir(path: Path, root_dir: Path) -> bool:
    try:
        path.resolve().relative_to(root_dir.resolve())
        return True
    except Exception:
        return False


def cmd_body_prune(args: argparse.Namespace) -> None:
    root = repo_root()
    conf = read_conf(root)

    body_dir_cfg = Path(conf.body_dir)
    body_dir = body_dir_cfg if body_dir_cfg.is_absolute() else (root / body_dir_cfg)
    body_dir = body_dir.resolve()

    if not body_dir.exists():
        print(f"body dir does not exist: {body_dir}")
        return
    if not body_dir.is_dir():
        die(f"body dir is not a directory: {body_dir}")

    keep: set[Path] = set()
    for entry in conf.entries:
        rp = resolved_body_file(conf, entry).resolve()
        if _is_under_dir(rp, body_dir):
            keep.add(rp)

    candidates = [p.resolve() for p in body_dir.rglob("*.md") if p.is_file()]
    stale = [p for p in candidates if p not in keep]

    if not stale:
        print(f"no stale body files under {body_dir}")
        return

    stale.sort()
    print(f"stale body files under {body_dir}:")
    for pth in stale:
        rel = pth.relative_to(body_dir)
        print(f"  {rel}")

    if not getattr(args, "apply", False):
        print("\n(dry-run) pass --apply to delete these files")
        return

    for pth in stale:
        try:
            pth.unlink()
        except OSError as exc:
            die(f"failed to delete {pth}: {exc}")
    print(f"\ndeleted {len(stale)} file(s)")
