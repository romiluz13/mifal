# Installing Mifal

The [README](../README.md) has the quickstart. This page says exactly what the install writes, and how update and uninstall treat your files.

`./install.sh --dry-run` lists every file, link and Marked block the install would write, and changes nothing. `mifal doctor` does not intentionally edit your files or use the network, runs none of your agents and opens no settings or credential file itself. It invokes the installed validator's selfcheck, one local `git ls-tree` of the recorded revision in your clone (with lazy fetching switched off, so a partial clone is never filled in), and Herdr's `status --json`, `--version` and `api schema --json` (Herdr reads its own configuration to answer). Each failure it reports comes with its fix.

## What gets written

Mifal's managed roots default to your home folder; `--allow-root-outside-home` explicitly permits others. The dry run previews the managed changes and the Herdr installation route; Herdr's own files are outside Mifal's managed rollback. Example with all five agents selected, eligible homes, default paths and no precedence or symbolic-rules conflict:

<!-- writes:begin -->
| Where | What Mifal writes |
|---|---|
| `~/.agents/mifal/` | The engine: the `mifal` command and its library, the experimental Herdr adapter and tools, the Guide (`AGENTS.md`) and the Manifest; 53 files |
| `~/.agents/skills/` | 39 skills, 242 files |
| `~/.local/bin/mifal` | A link to the engine's `mifal` command |
| `~/.claude/CLAUDE.md` | A Marked block that imports the Guide |
| `~/.claude/skills/` | 39 links, one per skill, into `~/.agents/skills/` |
| `~/.codex/AGENTS.md` | A Marked block holding the Guide |
| `~/.factory/AGENTS.md` | A Marked block holding the Guide |
| `~/.pi/agent/AGENTS.md` | A Marked block holding the Guide |
| `~/.config/opencode/AGENTS.md` | A Marked block holding the Guide |
<!-- writes:end -->

Installed `~/.agents/mifal/NOTICE` and `~/.agents/mifal/third_party/` record component provenance and most licence texts; the adapted frontend references also carry their licence texts under the installed frontend-design skill.

Detection (the program on your PATH or its home folder existing) selects candidate homes, and wiring can still skip or refuse an unsafe target. `./install.sh --harness codex --harness pi` selects the ones you name on a first install; a reinstall keeps previously recorded wiring. Folders Mifal creates are recorded and removed on uninstall once they are empty.

Rules files are never replaced. Mifal adds only its own Marked block, and leaves the rest of the file as you wrote it. When an agent reads a file other than the one Mifal would write (an `AGENTS.override.md`, or OpenCode or Pi reading a `CLAUDE.md`), Mifal skips that agent and tells you which file it reads now, rather than hiding your file. If an agent's rules file is a symbolic link (a dotfiles setup, say), the install stops and writes nothing, names the link and where it points, and tells you to replace it with a regular file (the agent then reads its own copy) or to wire only the other agents with `--harness`.

A skills folder that is a symbolic link to a real folder in your home, such as a second Claude home sharing one skills folder with the first, is written through: Mifal puts its links in the folder behind the link and leaves your link and your own skills alone, and `mifal uninstall` removes only Mifal's links. A link that points outside your home needs `--allow-root-outside-home`. A link that is broken, or that points at a file or at another link, stops the install and writes nothing; point it at a real folder, or leave that agent out with `--harness`.

A skill of yours that has a reserved name, or a skill link in Mifal's way, is moved to `~/.agents/mifal/backup/` when that is safe; an unsafe engine or rules-file target makes the install refuse, and uninstall restores a backup only into a free target and keeps the others. A file you edit after the install is yours: a reinstall stops before overwriting it, and `--overwrite-edits` saves a copy to `~/.agents/mifal-saved/` first.

Skills of your own can live beside Mifal's in `~/.agents/skills/`. Mifal's skill names are reserved: if a skill of yours has the same name as one Mifal installs, the install backs your folder up to `~/.agents/mifal/backup/` on first install, and uninstall restores it if the destination is free; otherwise the backup is kept and reported. Files you add inside a Mifal skill's folder are kept on update and uninstall. Skills with other names are never touched.

## Update and uninstall

```sh
mifal update
mifal uninstall --dry-run
mifal uninstall
```

`mifal update` fetches in the clone you installed from and moves to the newest release tag (`vX.Y.Z`, never a pre-release), so commits on `main` that are not yet released are not offered; a clone whose remote has no release tags follows its recorded upstream branch instead. It fetches the clone first, then previews the managed install changes and asks before applying them unless `--yes` is set. If the install already holds the newest release but lacks files that release installs (an update from 0.2.3 leaves the licence files out), the same command lists the missing files and installs them. It refuses a clone with uncommitted changes to tracked files or one that is not a fast-forward of its upstream; untracked files do not stop it unless the release adds a tracked file at the same path, when Git refuses the fast-forward, the update rolls back and your file is kept. A release the install already includes is never downgraded. An interrupted install or update is rolled back by the next update or uninstall, or by an install from a clone of the version that was installed before it or newer; an install from an older clone refuses while one is pending.

`mifal uninstall` removes unchanged recorded files, links and Marked blocks, keeps edited or diverted paths and says so, and restores a backup only if its original target is free, reporting any material it keeps. `./install.sh` from a clone older than the installed version refuses and changes nothing, even while an interrupted install is pending (it names both versions; use `mifal update`, install from a newer clone, or run `mifal uninstall` first to install an older one on purpose). A Manifest belongs to the home that installed it, and Mifal refuses to act on another home's: if `~/.agents/mifal` is a link into another home's install, remove the link first.

Herdr stays installed after uninstall, because other tools may use it. If Mifal installed it with Homebrew, remove it with:

```sh
brew uninstall herdr
```

If Mifal installed it with Herdr's own script, uninstall prints the command for that route.
