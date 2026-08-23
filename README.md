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
