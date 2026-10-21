# Installing Mifal

The [README](../README.md) has the quickstart. This page says exactly what the install writes, and how update and uninstall treat your files.

`./install.sh --dry-run` lists every file, link and Marked block the install would write, and changes nothing. `mifal doctor` is read-only: it writes nothing, uses no network, runs none of your agents and opens no settings or credential file itself. It does run `herdr status --json`, and Herdr reads its own configuration to answer. Each failure it reports comes with its fix.

## What gets written

Mifal writes only into your home folder, and only where the dry run says. On a machine with all five agents detected:

<!-- writes:begin -->
| Where | What Mifal writes |
|---|---|
| `~/.agents/mifal/` | The engine: the `mifal` command and its library, the experimental Herdr adapter and tools, the Guide (`AGENTS.md`) and the Manifest; 44 files |
| `~/.agents/skills/` | 39 skills, 241 files |
| `~/.local/bin/mifal` | A link to the engine's `mifal` command |
| `~/.claude/CLAUDE.md` | A Marked block that imports the Guide |
| `~/.claude/skills/` | 39 links, one per skill, into `~/.agents/skills/` |
| `~/.codex/AGENTS.md` | A Marked block holding the Guide |
| `~/.factory/AGENTS.md` | A Marked block holding the Guide |
| `~/.pi/agent/AGENTS.md` | A Marked block holding the Guide |
| `~/.config/opencode/AGENTS.md` | A Marked block holding the Guide |
<!-- writes:end -->

An agent is wired when its program is on your PATH or its home folder exists; `./install.sh --harness codex --harness pi` wires exactly the ones you name. Folders Mifal creates are recorded and removed on uninstall once they are empty.

Rules files are never replaced. Mifal adds only its own Marked block, and leaves the rest of the file as you wrote it. When an agent reads a file other than the one Mifal would write (an `AGENTS.override.md`, or OpenCode or Pi reading a `CLAUDE.md`), Mifal skips that agent and tells you which file it reads now, rather than hiding your file.

An existing skill or file in Mifal's way is moved to `~/.agents/mifal/backup/` and restored on uninstall. A file you edit after the install is yours: a reinstall stops before overwriting it, and `--overwrite-edits` saves a copy to `~/.agents/mifal-saved/` first.

Skills of your own can live beside Mifal's in `~/.agents/skills/`. Mifal's skill names are reserved: if a skill of yours has the same name as one Mifal installs, the install moves your folder to `~/.agents/mifal/backup/` and uninstall puts it back. Files you add inside a Mifal skill's folder are kept on update and uninstall. Skills with other names are never touched.

## Update and uninstall

```sh
mifal update
mifal uninstall --dry-run
mifal uninstall
```

`mifal update` fetches in the clone you installed from and moves to the newest release tag (`vX.Y.Z`, never a pre-release), so commits on `main` that are not yet released are not offered; a clone whose remote has no release tags follows its recorded upstream branch instead. It shows the incoming commits and the exact writes, and asks before it changes anything (`--yes` applies without asking). It installs exactly the revision you saw, and refuses a clone with uncommitted changes or one that is not a fast-forward of its upstream. An interrupted install or update is rolled back the next time you run `mifal` or the installer.

`mifal uninstall` removes every file and link Mifal wrote and every Marked block it added, restores what it moved aside, and keeps anything you changed since, saying so. Herdr stays installed after uninstall, because other tools may use it. If Mifal installed it with Homebrew, remove it with:

```sh
brew uninstall herdr
```

If Mifal installed it with Herdr's own script, uninstall prints the command for that route.
