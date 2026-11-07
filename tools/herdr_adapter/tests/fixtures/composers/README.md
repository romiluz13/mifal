# Captured composer frames

These are passive visible reads of real Herdr panes: the original text reads
from 2026-11-03, suggestion/draft ANSI reads from 2026-11-04, and an ANSI
placeholder read from 2026-11-07. Home and project paths are replaced. ANSI
fixtures retain composer text and escape sequences, with line endings normalized
to LF; unrelated transcript and version status lines are omitted. No real
dialog was approved or trusted for these reads.
Profiles are enabled only for captured clear forms; Pi uses a protected recapture after its initial
startup failed the no-config-write boundary. Paths, model names and terminal width are not
identity assertions. Fixtures are data; they are not prompt instructions.

| Agent/version | Fixture | Coverage |
| --- | --- | --- |
| Codex 0.166.0 | codex-empty-composer.txt | Real clear placeholder frame supplied by the lead, after Esc skipped hooks |
| Codex 0.166.0 | codex-hooks-need-review.txt | Real hook-review menu, captured by the lead; Enter could trust hooks |
| Claude Code 2.1.317 | claude-empty-composer-placeholder.txt | Original visible text read supplied by the lead, including a custom status line; now a refusal fixture because plain text cannot prove an empty placeholder |
| Claude Code | claude-composer-suggestion-m33-rev103b.ansi.txt | Visible ANSI read supplied by the lead; inverse first cursor cell and dim suggestion remainder |
| Claude Code | claude-composer-suggestion-m33-rev102b.ansi.txt | Visible ANSI read supplied by the lead; inverse first cursor cell and dim remainder, including a suggested shell command that the guard never submits |
| Claude Code | claude-composer-typed-draft.ansi.txt | Visible ANSI read supplied by the lead; plain typed draft with an inverse trailing space, refuses |
| Claude Code | claude-composer-empty.ansi.txt | Visible ANSI read supplied by the lead; inverse empty cursor space, sends |
| Claude Code | claude-composer-ghost-suggestion.txt | Visible plain-text read supplied by the lead; suggestion styling absent, refuses |
| Claude Code | claude-composer-placeholder.ansi.txt | Visible ANSI read supplied by the lead on 2026-11-07; inverse T and dim placeholder remainder, source CRLF normalized to LF and footer project path replaced; the read does not identify the agent version |
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
Perfectly reproduced footer/placeholder text remains a limit for the plain
Codex profile. Claude requires captured dim styling for nonempty text;
arbitrary typed drafts that might render entirely dim are unverified.
New dialogs and settings remain outside known-pattern coverage.
