# What Mifal checks

Which promises a program enforces, and which depend on the agent. The [README](../README.md) has the overview.

## What is checked, and what relies on the agent

Checked by a program, every time it runs:

- the installer, `mifal update` and `mifal uninstall`: what they write, what they keep and how they roll back, with the Manifest as the record;
- `mifal doctor`: the install's files, links and blocks, the validator's own selfcheck, the Ask Matt pin, Herdr, and the agent-browser CLI (which Mifal does not install);
- the contract validator, `~/.agents/skills/team-lead/scripts/validate_contracts.py`: a brief, a receipt or a phase record passes or is refused, when the agent or the lead runs it.

Relying on the agent following the Guide: that it reads the engineering workflow, loads the skill for each phase, runs the validator at each gate, asks you before cutting a step and reports only what its evidence shows. The validator can refuse a record; it cannot make an agent write one. Treat a session's claims as claims until you see the evidence they cite.

## Doctor's Codex skill audit

For each wired Codex Home in the Manifest, doctor may read that Home's regular `config.toml` and parse its TOML. The new audit uses only `skills.config` entries and their `path`, `name` and `enabled` keys; other settings values never reach its output. It does not follow a linked config file or open a credential, token or auth file. The existing Guide-key and hook reads for config-delivered Homes remain.

The supported schema is Codex **0.166.0**, from [its versioned skill configuration source](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/config/src/skills_config.rs). An entry selects the canonical `SKILL.md` path or an exact skill name and sets a boolean `enabled`. Later matching entries override earlier ones. Relative paths resolve against the Codex Home, and `~/` against the user's home folder. A matching exclusion gets a WARN naming the Mifal skill, declared file and key, plus a `fix:` line to reenable it or remove the entry and restart Codex. Invalid UTF-8, TOML or entry shapes warn with a repair action; unreadable or linked files are `unknown`.

Doctor does not start Codex to determine its installed version. Version compatibility and the session's effective scope remain **unknown**, even when this file has no exclusions. In this source version, the skill-rule resolver reads user and session-flag layers, and session flags can override a user rule; doctor does not inspect them or prove that any skill loads.

When an unreadable `config.toml` also delivers the Guide, doctor warns that the Guide's integrity is unknown and suggests restoring read access. Malformed or edited owned Guide blocks fail their integrity checks.

This audit adds no process, socket or write. Doctor retains its existing validator Python selfcheck, Herdr checks and local `git ls-tree` completeness check. The audited fixtures allow only the declared Codex settings paths and those exact process arguments, refuse credential reads, filesystem writes and sockets, and compare process lists with and without an exclusion. Their audit hook observes the doctor interpreter; it does not trace the allowed child processes. Read/write access to `/dev/null` for subprocess standard input remains allowed.
