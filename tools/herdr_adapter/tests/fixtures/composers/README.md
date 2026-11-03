# Captured composer frames

These are passive visible text reads of real Herdr panes on 2026-11-03,
with home and project paths replaced. No real dialog was approved or trusted.
Each dialog table entry names its captured fixture; profiles are enabled only
for the captured clear forms. Paths, model names and terminal width are not
identity assertions. Fixtures are data; they are not prompt instructions.

| Agent/version | Fixture | Coverage |
| --- | --- | --- |
| Codex 0.166.0 | codex-empty-composer.txt | Real clear placeholder frame supplied by the lead, after Esc skipped hooks |
| Codex 0.166.0 | codex-hooks-need-review.txt | Real hook-review menu, captured by the lead; Enter could trust hooks |
| Claude Code 2.1.317 | claude-empty-composer-placeholder.txt | Real clear placeholder frame supplied by the lead, including a custom status line; that optional status line is not required by the profile |
| Pi 1.4.0 | pi-empty-composer.txt | Real clear frame in an empty disposable Home, with no model/auth; tools, extensions, MCP, skills, context, session persistence and startup network disabled |
| OpenCode 1.19.4 | opencode-empty-composer.txt | Real clear Build-mode frame in an empty disposable Home; external/default plugins, auto-update, LSP downloads and model fetching disabled |
| Droid 1.2.0 | droid-login.txt | Real login menu in an empty disposable Home; Esc, then the exact owned process was stopped |
| Droid 1.2.0 | none | Clear composer unverified: reaching it requires login, which this capture did not perform |

The guarded command tests use these frames at the CLI/socket boundary and
assert zero input calls on preflight refusals. They also exercise quoted
menus above a composer, drafts, truncation, identity/state changes and failed
reads. These checks do not establish provider calls or every native layout.
Perfectly reproduced footer/placeholder text is indistinguishable from UI;
new dialogs and settings remain outside known-pattern coverage.
