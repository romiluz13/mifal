# What Mifal checks

Which promises a program enforces, and which depend on the agent. The [README](../README.md) has the overview.

## What is checked, and what relies on the agent

Checked by a program, every time it runs:

- the installer, `mifal update` and `mifal uninstall`: what they write, what they keep and how they roll back, with the Manifest as the record;
- `mifal doctor`: the install's files, links and blocks, the validator's own selfcheck, the Ask Matt pin, Herdr, and the agent-browser CLI (which Mifal does not install);
- the contract validator, `~/.agents/skills/team-lead/scripts/validate_contracts.py`: a brief, a receipt or a phase record passes or is refused, when the agent or the lead runs it.

Relying on the agent following the Guide: that it reads the engineering workflow, loads the skill for each phase, runs the validator at each gate, asks you before cutting a step and reports only what its evidence shows. The validator can refuse a record; it cannot make an agent write one. Treat a session's claims as claims until you see the evidence they cite.

## Doctor's Codex skill audit

For each wired Codex Home in the Manifest, doctor may read that Home's `config.toml` and parse its TOML. A linked config is opened only when its final resolved target is a regular file whose name ends in `.toml`. The existing exact-name credential refusals check only the final target's filename; folders named `auth` or `token` are ordinary. The audit uses only `skills.config` entries and their `path`, `name` and `enabled` keys; other settings values never reach its output. The existing Guide-key and hook reads for config-delivered Homes remain.

The supported schema is Codex **0.166.0**, from [its versioned skill configuration source](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/config/src/skills_config.rs). An entry selects the canonical `SKILL.md` path or an exact skill name and sets a boolean `enabled`. Later matching entries override earlier ones. Relative paths resolve against the Codex Home, and `~/` against the user's home folder. A matching exclusion gets a WARN naming the Mifal skill, declared file and key, plus a `fix:` line to reenable it or remove the entry and restart Codex. Invalid UTF-8, TOML or typed entry shapes warn with a repair action; unreadable files are `unknown`. A blank name, both selectors or no selector is skipped with a note, as Codex skips it; other entries remain checked.

Doctor does not start Codex to determine its installed version. A note names the supported schema and leaves version compatibility and the session's effective scope **unknown**. A missing config or one without a skill exclusion produces no new WARN. A dangling link warns that it points to a missing file and Codex 0.166.0 reads no settings from it. A FIFO, device or directory warns with a fix to make it a regular TOML file. In this source version, the skill-rule resolver reads user and session-flag layers, and session flags can override a user rule; doctor does not inspect them or prove that any skill loads. The per-Harness settings facts and parser live in `lib/mifal/harness.py`; doctor reports their result.

When an unreadable `config.toml` also delivers the Guide, doctor reports FAIL because the Guide is not delivered, and prints the restore-access fix once. Malformed or edited owned Guide blocks fail their integrity checks.

This audit adds no process, socket or write. Doctor retains its existing validator Python selfcheck, Herdr checks and local `git ls-tree` completeness check. The audited fixtures allow only the declared Codex settings paths and their resolved targets, plus those exact process arguments, refuse credential reads, filesystem writes and sockets, and compare process lists with and without an exclusion. Their independent credential fixture catalog includes `~/.aws/credentials`, `~/.claude.json`, `~/.netrc`, `~/.config/gh/hosts.yml` and `~/.ssh/id_ed25519`; opening any of them fails the audit even through the declared link. Their audit hook observes the doctor interpreter; it does not trace the allowed child processes. Read/write access to `/dev/null` for subprocess standard input remains allowed.
