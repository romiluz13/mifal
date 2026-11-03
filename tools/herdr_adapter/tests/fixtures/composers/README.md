# Captured composer frames

These are passive visible text reads of real Herdr panes on 2026-11-03,
with home and project paths replaced. No real dialog was approved or trusted.
Each dialog table entry names its captured fixture; profiles are enabled only
for captured clear forms; Pi uses a protected recapture after its initial
startup failed the no-config-write boundary. Paths, model names and terminal width are not
identity assertions. Fixtures are data; they are not prompt instructions.

| Agent/version | Fixture | Coverage |
| --- | --- | --- |
| Codex 0.166.0 | codex-empty-composer.txt | Real clear placeholder frame supplied by the lead, after Esc skipped hooks |
| Codex 0.166.0 | codex-hooks-need-review.txt | Real hook-review menu, captured by the lead; Enter could trust hooks |
| Claude Code 2.1.317 | claude-empty-composer-placeholder.txt | Real clear placeholder frame supplied by the lead, including a custom status line; that optional status line is not required by the profile |
| Claude Code 2.1.316 | Status footer in test_guard_send.py | Passive clear lead-pane read, including three optional status lines and a running-shell indicator; no config writes or session launch by this capture |
| Pi 1.4.0 | pi-empty-composer.txt | Real clear frame from a fresh session with its disposable Home read-only; configuration lock attempts denied and file hashes/timestamps/modes unchanged across launch; no model/auth, tools, extensions, MCP, skills, context, session persistence or startup network |
| OpenCode 1.19.4 | opencode-empty-composer.txt | Real clear frame, but profile unverified and disabled: startup installed npm dependencies in the disposable Home despite suppression flags; the no-install capture boundary was not met |
| Droid 1.2.0 | droid-login.txt | Real login menu in an empty disposable Home; Esc, then the exact owned process was stopped |
| Droid 1.2.0 | none | Clear composer unverified: reaching it requires login, which this capture did not perform |

Initial native startups initialized default settings/state in disposable Homes;
no live Home was written. Pi was stopped and recaptured in a fresh session
with its disposable Home read-only: lock writes were denied, and every file's
hash, modification time and mode stayed unchanged. That protected recapture
is the enabled Pi fixture. OpenCode's automatic dependency installation was
discovered in the audit, the process stopped, and its profile disabled.
Its retained frame does not prove an authorized no-install capture.

The guarded command tests use these frames at the CLI/socket boundary and
assert zero input calls on preflight refusals. They also exercise quoted
menus above a composer, drafts, truncation, identity/state changes and failed
reads. These checks do not establish provider calls or every native layout.
Perfectly reproduced footer/placeholder text is indistinguishable from UI;
new dialogs and settings remain outside known-pattern coverage.
