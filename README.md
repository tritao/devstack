# Devstack

Developer tooling for Git worktrees, builds, linting, and stacked pull
requests.

This repository is the standalone tool home for the global `ds` command. It
can operate on any Git repository from the current working directory. The
FreeCAD adapter is included for FreeCAD-specific build and lint behavior, but
the core stack/worktree functionality is repository-agnostic.

## Install the global command

Clone this repository, then run:

```bash
./tools/devstack/devstack.sh self-check --tests
./tools/devstack/devstack.sh shell-alias
exec "$SHELL" -l
ds doctor
```

## Reproduce a FreeCAD machine setup

After cloning Devstack and creating the canonical FreeCAD checkout, install all
machine-local workflow configuration with one idempotent command:

```bash
python3 tools/devstack/devstack.py machine-setup \
  --golden-dir /path/to/FreeCAD-master \
  --worktree-root /path/to/FreeCAD-worktrees \
  --build-root /large-disk/freecad-builds \
  --ccache-dir /large-disk/ccache
```

This installs a real `~/.local/bin/ds` executable and managed configuration
blocks for Devstack, ccache, Git excludes, and Codex `AGENTS.md`. Re-running the
command updates those blocks without duplicating them. It creates storage
directories and reports missing required tools, but leaves OS package
installation to the host package manager.

`shell-alias` writes a machine-local shell function and the optional `ds`
shortcut under `~/.config/devstack/`. It records the absolute path to this
checkout, so rerun it if the checkout moves.

## Use from a project

Run `ds` from the project you want to operate on:

```bash
cd ~/src/FreeCAD
ds wt-init my-feature --dir ../FreeCAD-wt-my-feature
ds list
ds update
```

To refresh and build a pristine golden checkout before creating a worktree:

```bash
cd /path/to/FreeCAD-master
ds wt-fresh my-feature
```

This fetches `upstream/main`, rebases the golden `main`, completes its
Clang+mold build with ccache and stable virtual paths, and then creates
`feature/my-feature`. The new worktree remembers those build defaults, so plain
`ds build` continues using ccache and stable paths. Use `--no-sandbox-paths`
and/or `--no-ccache-launcher` to opt out. The command refuses dirty or
non-`main` golden checkouts. Use `--golden-dir`, `--remote`, `--main-branch`,
`--branch`, or `--dir` to override the other defaults.

When a task is finished, remove its worktree and external build data with:

```bash
ds wt-remove my-feature
```

The local branch is preserved by default. Add `--delete-branch` to delete it,
or `--keep-build` to retain its build data. Dirty worktrees are refused unless
`--force` is explicitly supplied.

To keep generated build trees outside source worktrees, set an absolute shared
parent such as `DEVSTACK_BUILD_ROOT=/mnt/builds`. Devstack generates wrapper
CMake presets storing each binary tree below
`$DEVSTACK_BUILD_ROOT/<worktree-name>/<preset>` during `ds build`.

For better ccache reuse between worktrees, install Bubblewrap and opt into
stable virtual source and build paths:

```bash
ds build --preset debug --ccache-launcher --sandbox-paths
```

The real output remains isolated at
`$DEVSTACK_BUILD_ROOT/<worktree-name>/sandbox/<preset>`. `wt-fresh` enables and
records this mode automatically; manually created worktrees can opt in with the
command above. This is path normalization, not a security sandbox, and direct
debugger, IDE, and GUI-launch integration is not yet wrapped.

Stack configuration and generated PR bodies remain local to each target
worktree under `.devstack/`. The standalone checkout supplies the executable;
it does not own the target project's stack state.

## Lint tooling

When `ds lint` or `ds provision --python-lint` uses the default `origin`
tooling source, it prefers `tools/lint` in this checkout and falls back to
`tools/lint` in the target repository. Use `--tools-from local` or an explicit
path to override that behavior.

## Development

```bash
python3 tools/devstack/devstack.py self-check --tests
python3 -m unittest discover -s tools/devstack/tests -p 'test_*.py'
```

The detailed command reference is in
[`tools/devstack/README.md`](tools/devstack/README.md).
