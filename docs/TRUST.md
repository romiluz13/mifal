# What Mifal checks

Which promises a program enforces, and which depend on the agent. The [README](../README.md) has the overview.

## What is checked, and what relies on the agent

Checked by a program, every time it runs:

- the installer, `mifal update` and `mifal uninstall`: what they write, what they keep and how they roll back, with the Manifest as the record;
- `mifal doctor`: the install's files, links and blocks, declared skill-setting keys, the validator's own selfcheck, the Ask Matt pin, Herdr, and the agent-browser CLI (which Mifal does not install);
- the contract validator, `~/.agents/skills/team-lead/scripts/validate_contracts.py`: a brief, a receipt or a phase record passes or is refused, when the agent or the lead runs it.

Relying on the agent following the Guide: that it reads the engineering workflow, loads the skill for each phase, runs the validator at each gate, asks you before cutting a step and reports only what its evidence shows. The validator can refuse a record; it cannot make an agent write one. Treat a session's claims as claims until you see the evidence they cite.

## Doctor's skill-filter audit

For each wired Home in the Manifest, doctor may open and parse only the declared settings files below. It reads their text as data, uses only skill keys, prints no unrelated values, and never executes a setting. The existing config-delivered Codex Guide and hooks.json reads remain. Home variables or `--home` affect the recorded root; doctor does not substitute the shell's unrecorded Home for it.

| Supported source | Declared files relative to the recorded Home | Exclusion rule |
|---|---|---|
| [Claude Code 2.1.316](https://github.com/anthropics/claude-code/releases/tag/v2.1.316) | `settings.json` | `skillOverrides`: off hides both listings; user-invocable-only hides the model listing; on and name-only do not exclude |
| [Codex 0.166.0](https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/config/src/skills_config.rs) | `config.toml` | `[[skills.config]]`, path or exact name and boolean enabled; later matching entries win |
| [Droid 1.1.0](https://downloads.factory.ai/factory-cli/releases/1.1.0/darwin/arm64/droid) | `settings.json` | `disabledSkills`: normalized names; any combined disable wins |
| [Pi 1.4.0](https://github.com/earendil-works/pi/tree/v1.4.0/packages/coding-agent) | `settings.json`, `skills/.gitignore`, plus shared `~/.agents/skills/.gitignore` | `skills`: !glob excludes, +exact restores, -exact excludes last; ignored parents prune discovery |
| [OpenCode 1.19.4](https://github.com/anomalyco/opencode/tree/v1.19.4) | Global directory: `config.json`, `opencode.json`, `opencode.jsonc`; overridden directory: `opencode.json`, `opencode.jsonc` | Ordered `permission.skill` action or pattern map, and matching global permission rules; only deny excludes, ask remains listed |

Claude and Droid's installed schemas and precedence were checked against those source versions, alongside their official settings/skills documentation. Claude and Pi settings are JSON. Droid accepts JSON comments but rejects trailing commas. OpenCode files are JSONC: comments and trailing commas are accepted without changing quoted strings. Later files merge permission maps while keeping existing key positions; the last matching rule in the merged order wins. Environment/file substitutions are not expanded by doctor and remain unknown.

The shared reader resolves once and refuses an unresolved/changing link result. It opens that resolved path once with non-blocking, no-follow flags, checks the descriptor is a regular file, and reads that descriptor. The final filename must fit TOML, JSON, JSONC or gitignore as declared; suffix comparison is case-insensitive. Known credential filenames such as auth.json, credentials.json and .credentials.json are refused before opening. settings.json and opencode.json are legitimate settings names; folders named auth or token are ordinary. This shape rule is not proof of content: it cannot distinguish a hard link to secret data or an allowed-format file containing credentials, and the filename catalog cannot identify every credential location.

A matching exclusion gets a WARN naming the Mifal skill, declared file and key, plus a fix to change/remove the entry and restart the agent. Invalid encoding, syntax or typed skill entries warn with a repair action; unreadable files are unknown. Missing files or absent skill keys add no new WARN. A dangling link says the source version reads no settings from it; a looping link has a replace-link fix. FIFOs, devices and directories are refused without a blocking read. Codex path selectors compare file identity, falling back to normalized strings when the selector is missing; relative selectors use the Codex Home and ~/ uses the user's Home. Blank names or entries with both/no selectors are skipped with a note, as Codex skips them.

Pi and OpenCode pattern audits allow up to 1,024 characters per pattern, 1,024 selectors and 8,192 total pattern characters per source; OpenCode's merged rules use the same budget. Larger inputs are not matched: doctor warns that exclusions are unknown and asks the developer to reduce them. Pi ignore-file lines count toward these limits.

Pi uses each discovery folder's own pattern base: the shared Pool uses ~/.agents even with an overridden Pi Home. The audit covers ordinary *, ?, bracket and globstar patterns and exact paths; brace, extglob, POSIX/caret-class, escaped-ignore and dot-segment file-URL syntax is unknown when encountered. Parent ignore rules cannot be undone by a descendant-only negation. Nested ignore files, .ignore, .fdignore, project settings, packages and added resource paths are not read; other discovered copies may change the effective skill.

The coverage line names a supported schema and source version. Doctor starts no agent to establish compatibility and never proves that a skill loads. Claude's permission rules in settings.json are not read. Its project, local, managed, flag and synced layers are not read. Droid's org-remote, runtime, folder, project and dynamic settings and frontmatter are not read. OpenCode's ordinary global config in ~/.config/opencode (or the XDG global directory) still applies under OPENCODE_CONFIG_DIR and is not read by this audit. Other agents' project/session layers, OpenCode's legacy TOML migration, agent/managed permissions and other global Homes remain uninspected. “No exclusion found” describes the inspected files; effective session scope remains unknown.

When an unreadable Codex config.toml also delivers the Guide, doctor reports FAIL because the Guide is not delivered, with its read/type fix once. An intact linked config-delivered key passes its integrity check. Malformed or edited owned Guide blocks still fail.

This audit adds no process, socket or write. Doctor retains the validator Python selfcheck, Herdr checks and local git ls-tree completeness check. Audited fixtures allow only declared settings paths and their resolved targets, plus those exact process arguments, and refuse filesystem mutations and sockets. Their independent credential catalog includes default and recorded custom agent Homes, plus ~/.aws/credentials, ~/.claude.json, ~/.netrc, ~/.config/gh/hosts.yml and ~/.ssh/id_ed25519. A forbidden read fails even through a declared link. The hook observes the doctor interpreter, not the allowed child processes; read/write access to /dev/null for subprocess standard input remains allowed.
