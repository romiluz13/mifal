# Installing Mifal

The [README](../README.md) has the quickstart. This page says exactly what the install writes, and how update and uninstall treat your files.

`./install.sh --dry-run` lists every file, link and Marked block the install would write, and changes nothing. `mifal doctor` does not intentionally edit your files or use the network, runs none of your agents and opens no settings or credential file itself. It invokes the installed validator's selfcheck, one local `git ls-tree` of the recorded revision in your clone (with lazy fetching switched off, so a partial clone is never filled in), and Herdr's `status --json`, `--version` and `api schema --json` (Herdr reads its own configuration to answer). Each failure it reports comes with its fix. For each agent Mifal serves it says which rules file holds Mifal's block, and it lists agents it detected but did not serve. It cannot see an agent's own skill filters (see "Skills of your own, precedence and filters").

## What gets written

Mifal's managed roots default to your home folder; `--allow-root-outside-home` explicitly permits others. The dry run previews the managed changes and the Herdr installation route; Herdr's own files are outside Mifal's managed rollback. Example with all five agents selected, eligible homes, default paths and no precedence or symbolic-rules conflict:

<!-- writes:begin -->
| Where | What Mifal writes |
|---|---|
| `~/.agents/mifal/` | The engine: the `mifal` command and its library, the experimental Herdr adapter and tools, the Guide (`AGENTS.md`) and the Manifest; 61 files |
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

Detection (the program on your PATH or its home folder existing) selects candidate homes, and wiring can still skip or refuse an unsafe target. `./install.sh --harness codex --harness pi` selects the ones you name on a first install; a reinstall keeps previously recorded wiring. `--home NAME=PATH`, repeatable, names one Home of one Harness to serve; for a Harness named this way only the Homes you name are served, so a stray `CODEX_HOME` adds no Home you did not name, and every other Harness is wired by detection (see "Several Homes of one agent"). Folders Mifal creates are recorded and removed on uninstall once they are empty.

Rules files are never replaced. Mifal adds only its own Marked block, and leaves the rest of the file as you wrote it. When an agent reads a file other than the one Mifal would write (an `AGENTS.override.md`, or Pi reading a `CLAUDE.md`), Mifal skips that agent and tells you which file it reads now, rather than hiding your file. OpenCode reads `~/.config/opencode/AGENTS.md` before the `~/.claude/CLAUDE.md` fallback, so Mifal writes its block there when that file is missing, and never edits `opencode.json`. If `~/.claude/CLAUDE.md` holds anything besides Mifal's block, the preview names it: once Mifal writes the OpenCode file, OpenCode stops reading the `CLAUDE.md`, so copy what you want to keep into `~/.config/opencode/AGENTS.md`. A first install prints that as a note. `mifal update` and a reinstall over an existing install stop on it once, print "Nothing was changed." and leave `~/.claude/CLAUDE.md` as it is: Mifal neither moves nor saves that file. The message ends "Run mifal update --overwrite-edits" (a reinstall says "Run again with --overwrite-edits") to accept that OpenCode then reads `~/.config/opencode/AGENTS.md` instead. Pi with a `CLAUDE.md` is still skipped, with a note that names the file it reads.

A personal layer, your own rules, belongs outside Mifal's block in each agent's own regular rules file. Mifal never writes through a linked rules file (see [ADR 0004](adr/0004-never-write-through-a-linked-rules-file.md)). If an agent's rules file is a symbolic link (a dotfiles setup, say), the install stops and writes nothing, names the link and where it points, and tells you to replace it with a regular file (the agent then reads its own copy) or to wire only the other agents with `--harness`. A Codex Home you name with `--home` is the one exception: it is served through a marked key in its own `config.toml`, never through the link (see "A linked Codex Home").

A skills folder that is a symbolic link to a real folder in your home, such as a second Claude home sharing one skills folder with the first, is written through: Mifal puts its links in the folder behind the link and leaves your link and your own skills alone, and `mifal uninstall` removes only Mifal's links. A link that points outside your home needs `--allow-root-outside-home`. A link that is broken, or that points at a file or at another link, stops the install and writes nothing; point it at a real folder, or leave that agent out with `--harness`.

A skill of yours that has a reserved name, or a skill link in Mifal's way, is moved to `~/.agents/mifal/backup/` when that is safe; an unsafe engine or rules-file target makes the install refuse, and uninstall restores a backup only into a free target and keeps the others. A file you edit after the install is yours: a reinstall stops before overwriting it, and `--overwrite-edits` saves a copy to `~/.agents/mifal-saved/` first.

Skills of your own can live beside Mifal's in `~/.agents/skills/`. Mifal's skill names are reserved: if a skill of yours has the same name as one Mifal installs, a first install backs your folder up to `~/.agents/mifal/backup/`. An update or reinstall that reserves a name you already use stops, lists each clash and changes nothing until you run it again with `--overwrite-edits`, which backs yours up first. `mifal uninstall` restores a backup if the destination is free; otherwise the backup is kept and reported, and `mifal doctor` notes how many backups exist. Files you add inside a Mifal skill's folder are kept on update and uninstall. Skills with other names are never touched.

### Several Homes of one agent

An agent can have several Homes: a work and a personal Codex account, or two Claude Code configurations. One install serves them all. Name each one with `--home NAME=PATH`; the Manifest keeps a list of Homes per Harness, one record per Home, and `mifal doctor` prints one line per recorded Home and names an unrecorded Home whose rules file links to or imports a shared file a recorded Home reads ("reads PATH, not served by this install"). Each Claude Home gets its own skill links; every other Harness keeps reading `~/.agents/skills/` as before.

A reinstall plans the union of recorded and named Homes: naming fewer never drops a recorded Home, and only `mifal uninstall` drops one. A recorded Home whose folder has been deleted stays recorded as skipped, and nothing is written there until you name it again with `--home`; to drop it, uninstall. A stop in one Home stops the whole run before any write, so one run over all your Homes is all or nothing. `mifal update` re-plans every recorded Home, wired or skipped, so every Home moves to the new release together.

An install made by Mifal 0.2.x kept one Home per Harness. The next install or update reads each such record as a one-Home list and writes the record back in the new shape, keeping every recorded Home. A Manifest that cannot be read in the new shape stops the run with nothing written.

### A linked Codex Home: the marked developer_instructions key

A Codex Home you name with `--home codex=PATH` whose rules file is a symbolic link to a shared file is not refused: the install serves that Home by adding one Mifal-marked top-level `developer_instructions` key to the top of that Home's own `config.toml` (see [ADR 0005](adr/0005-a-marked-developer-instructions-key-for-a-linked-codex-home.md)). The link stays a link, so your own edits to the shared file keep reaching every Home that reads it, and the shared file itself is never written. Every other byte of `config.toml` is kept: update and uninstall touch only the marked block, so a model or provider change you make later survives. The whole document is parsed with a real TOML parser before anything is written, so Mifal never writes a config Codex cannot read. A `config.toml` that is a symbolic link, one that already sets `developer_instructions` anywhere, or one that would not parse with the key added is refused with nothing written, and an owner-only backup of the file is recorded under `~/.agents/mifal/backup/`. Mifal checks the integrity of its own marked block against the Manifest and never prints your config's values; it does not verify that a session loaded the key, which is Codex's own runtime behaviour.

Mifal never edits or runs a hook, a settings file or another tool's session-start line. Before it writes the key it reads the served Home's own `hooks.json` and inline `[hooks]` table, as data, and classifies what it finds. A `SessionStart` command that references the Guide, or one Mifal cannot classify, makes that Home pending: no key is written, the reason is recorded, `mifal doctor` warns with it, and the Home is re-checked on every run; once the hooks are gone, `mifal update` serves the Home. A hook file or `[hooks]` table Mifal cannot read makes the Home unknown: no key is written, and doctor fails the Home with its fix. A hook that appears later beside an owned key holds the next install or update until the hook is gone or the key is removed.

## Skills of your own, precedence and filters

When a skill of yours and a Mifal skill share a name, which one the agent uses depends on the agent, and Mifal does not move its links to change that. As documented for the versions in the README matrix:

- **Claude Code**: personal skills (`~/.claude/skills`, where Mifal's links are) win over a project's `.claude/skills` skill of the same name.
- **Pi**: a project skill wins over `~/.pi/agent/skills`, which wins over `~/.agents/skills`; the first discovered name is kept with a warning.
- **Droid**: project and project-plugin skills win over personal ones; it keeps one effective copy and shows the others as overridden. Where `~/.agents/skills` falls against `~/.factory/skills` is not documented.
- **Codex**: no precedence is documented; two skills with one name both appear in its selectors.
- **OpenCode**: no precedence is documented; its source logs a duplicate name and keeps one copy, and which one is not deterministic.

So a project skill named like a Mifal skill replaces Mifal's on Pi and Droid, not on Claude Code, and is listed beside it on Codex.

An agent's own settings can also hide Mifal's skills where `mifal doctor` cannot see: Pi's `skills` setting, Droid's `disabledSkills`, Codex's `[[skills.config]]` and OpenCode's `permission.skill`. Pi also reads a `.gitignore`, `.ignore` or `.fdignore` inside a skills folder: a `.gitignore` in `~/.agents/skills` that lists Mifal's skill names hides them from Pi unless they are also linked from `~/.pi/agent/skills`. If your skills folder is a git repository, put those names in `.git/info/exclude` instead; Pi does not read it.

## Install, update, rollback and uninstall

One path for each; the README has the quickstart.

1. **Install**: `./install.sh --dry-run`, then `./install.sh`, from a clone of the release you want. `mifal doctor` checks the result.
2. **Update**: `mifal update`.
3. **Rollback**: there is no rollback command. Run `mifal uninstall`, clone the older release tag (`git clone --branch v0.2.3 https://github.com/romiluz13/mifal.git`), and run `./install.sh` from that clone, with `--harness` for each agent you want wired. Uninstall keeps your edits and your own skills, and the older installer puts its own version in place. Uninstall removes the OpenCode file Mifal created but, when it holds your own lines, keeps it with only Mifal's block taken out. 0.2.3's installer skips OpenCode, so OpenCode reads the `~/.claude/CLAUDE.md` fallback, only when `~/.claude/CLAUDE.md` exists and `~/.config/opencode/AGENTS.md` does not; otherwise 0.2.3 writes its block into `~/.config/opencode/AGENTS.md`, and OpenCode reads that file first.
4. **Uninstall**: `mifal uninstall --dry-run`, then `mifal uninstall`.

```sh
mifal update
mifal uninstall --dry-run
mifal uninstall
```

### Update

`mifal update` re-plans every agent the install recorded, including one it recorded as skipped, so an install made before 0.3.0 that skipped OpenCode picks it up the same way when the folder exists. It re-plans every Home each Harness recorded, wired or skipped, so all your Homes move to the new release in one run; a skipped Home whose folder is gone stays skipped until you name it with `--home`, and nothing is written there. For OpenCode with your own lines in `~/.claude/CLAUDE.md`, the update stops once with the conflict above and changes nothing; run `mifal update --overwrite-edits` and it writes `~/.config/opencode/AGENTS.md`, leaving the `CLAUDE.md` as it is. When no newer release exists, `mifal update` prints "Mifal is up to date" and does nothing, so `--overwrite-edits` has no effect there; run `./install.sh --overwrite-edits` in your clone instead. `mifal doctor` says the same: for an agent the install recorded as skipped that it could now serve, it prints `WARN guide opencode: found at ~/.config/opencode, not served`, and its fix is `run ./install.sh --overwrite-edits in your Mifal clone; OpenCode then reads ~/.config/opencode/AGENTS.md, not ~/.claude/CLAUDE.md`; when the skipped Home's folder is gone the fix names its root instead: `run ./install.sh --home opencode=PATH --overwrite-edits in your Mifal clone`.

`mifal update` fetches in the clone you installed from and moves to the newest release tag (`vX.Y.Z`, never a pre-release), so commits on `main` that are not yet released are not offered; a clone whose remote has no release tags follows its recorded upstream branch instead. It fetches the clone first, then previews the managed install changes and asks before applying them unless `--yes` is set. If the install already holds the newest release but lacks files that release installs (an update from 0.2.3 leaves the licence files out), the same command lists the missing files and installs them. It refuses a clone with uncommitted changes to tracked files or one that is not a fast-forward of its upstream; untracked files do not stop it unless the release adds a tracked file at the same path, when Git refuses the fast-forward, the update rolls back and your file is kept. A file Git ignores in the clone is checked while the update plans, before it writes anything of yours (the fetch has already updated the clone's Git data), and once more after you approve at the prompt: where the release adds, renames, copies or changes the type of a tracked path (or needs a folder where your file is), the update lists each such file, says "Nothing was changed" and stops. Move the file out of the clone and run `mifal update` again, or run `mifal update --overwrite-edits`, which saves a copy of each file it found under `~/.agents/mifal/backup/` first and then updates; if the fast-forward fails, each saved file is put back when its place is free, and otherwise stays in `~/.agents/mifal/backup/` and the update says so. A file Git ignores that you create after that last check, before the fast-forward, is not covered: Git can replace it, the update has not saved it, and nothing restores it. A saved clone file stays in the backup folder: the release's tracked file is now at its path, so `mifal uninstall` keeps the copy and says so rather than moving it back. A release the install already includes is never downgraded. An interrupted install or update is rolled back by the next update or uninstall, or by an install from a clone of the version that was installed before it or newer; an install from an older clone of Mifal 0.3.0 or later refuses while one is pending.

Update protection starts with 0.3.0. An update from 0.2.3 (or from a local 0.2.4 build) runs the old release's installed code for its first run, and that code cannot stop on a clash: it moves a skill of yours that has a newly reserved name into `~/.agents/mifal/backup/` and carries on, and it does not check for a file Git ignores in the clone, which the release's file can then overwrite. Before updating from 0.2.3, look in `~/.agents/skills/` for skills of yours that a release might reserve, and check the clone for ignored files of yours at paths a release might add. An update from 0.2.3 also takes two runs of `mifal update`: the first installs the new release but not the licence files, and the second lists them and adds them once you confirm; `mifal doctor` warns until then.

### Uninstall

`mifal uninstall` removes unchanged recorded files, links and Marked blocks, keeps edited or diverted paths and says so, and restores a backup only if its original target is free, reporting any material it keeps. It acts on every recorded Home: each one is left byte for byte as it was, a linked Codex Home gets its marked key taken out and keeps every other byte of its `config.toml`, and anything you edited after the install is kept with its backup. `./install.sh` from a clone of Mifal 0.3.0 or later that is older than the installed version refuses and changes nothing, even while an interrupted install is pending (it names both versions; use `mifal update`, install from a newer clone, or run `mifal uninstall` first to install an older one on purpose; see Rollback). A clone of Mifal 0.2.3 or earlier runs its own installer, which has no such check, and installs its older version over the newer one; use `mifal update` instead. A Manifest belongs to the home that installed it, and Mifal refuses to act on another home's: if `~/.agents/mifal` is a link into another home's install, remove the link first.

Herdr stays installed after uninstall, because other tools may use it. If Mifal installed it with Homebrew, remove it with:

```sh
brew uninstall herdr
```

If Mifal installed it with Herdr's own script, uninstall prints the command for that route.
